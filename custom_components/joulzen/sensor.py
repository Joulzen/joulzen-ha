"""Platform for Joulzen live data sensors."""
from __future__ import annotations

import logging
import re
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import COMPONENT_TYPE_LABELS, JoulzenCoordinator

_LOGGER = logging.getLogger(__name__)

# (unit, device_class, state_class) keyed by bare field name
_FIELD_META: dict[str, tuple] = {
    # Instantaneous power – kW
    "eSupplying": (
        "kW", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT,
    ),
    "eUsing": (
        "kW", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT,
    ),
    "hSupplying": (
        "kW", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT,
    ),
    "hUsing": (
        "kW", SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT,
    ),
    # Daily energy totals – kWh
    "eSupplied": (
        "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING,
    ),
    "eUsed": (
        "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING,
    ),
    "hSupplied": (
        "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING,
    ),
    "hUsed": (
        "kWh", SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING,
    ),
    # Temperature – °C
    "temperature": (
        "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,
    ),
    "meanTemperature": (
        "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,
    ),
    "minTemperature": (
        "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,
    ),
    "maxTemperature": (
        "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,
    ),
    "targetTemperature": (
        "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,
    ),
    "meanTargetTemperature": (
        "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,
    ),
    "minTargetTemperature": (
        "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,
    ),
    "maxTargetTemperature": (
        "°C", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT,
    ),
    # State of charge – % (value already ×100 from parser)
    "soc": ("%", SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT),
    # Coefficient of Performance – dimensionless
    "cop":     (None, None, SensorStateClass.MEASUREMENT),
    "meanCop": (None, None, SensorStateClass.MEASUREMENT),
    "maxCop":  (None, None, SensorStateClass.MEASUREMENT),
    "minCop":  (None, None, SensorStateClass.MEASUREMENT),
    # Electricity price – ct/kWh
    "price":     ("ct/kWh", None, SensorStateClass.MEASUREMENT),
    "meanPrice": ("ct/kWh", None, SensorStateClass.MEASUREMENT),
    "minPrice":  ("ct/kWh", None, SensorStateClass.MEASUREMENT),
    "maxPrice":  ("ct/kWh", None, SensorStateClass.MEASUREMENT),
    # Money – EUR
    "spending": (
        "EUR", SensorDeviceClass.MONETARY, SensorStateClass.TOTAL_INCREASING,
    ),
    "earning": (
        "EUR", SensorDeviceClass.MONETARY, SensorStateClass.TOTAL_INCREASING,
    ),
    "cost": (
        "EUR", SensorDeviceClass.MONETARY, SensorStateClass.TOTAL_INCREASING,
    ),
    "totalEarned": (
        "EUR", SensorDeviceClass.MONETARY, SensorStateClass.TOTAL_INCREASING,
    ),
    "money_saved": (
        "EUR", SensorDeviceClass.MONETARY, SensorStateClass.TOTAL_INCREASING,
    ),
    # Ratio fields – % (value already ×100 from parser)
    "totalAvailability": ("%", None, SensorStateClass.MEASUREMENT),
    "activeTime":        ("%", None, SensorStateClass.MEASUREMENT),
    "constrainedTime":   ("%", None, SensorStateClass.MEASUREMENT),
    "errorTime":         ("%", None, SensorStateClass.MEASUREMENT),
    "autarky":           ("%", None, SensorStateClass.MEASUREMENT),
    # KPI durations
    "heat_autarky_duration": ("h", None, SensorStateClass.MEASUREMENT),
}

_DEFAULT_META: tuple = (None, None, SensorStateClass.MEASUREMENT)

_ACRONYMS = {"cop", "soc", "ev", "pv", "kpi"}


def _fmt(text: str) -> str:
    """Expand camelCase / underscore text into a title-cased label."""
    result = []
    for part in text.split("_"):
        for word in re.sub(r"([A-Z])", r" \1", part).split():
            lower = word.lower()
            result.append(
                lower.upper() if lower in _ACRONYMS else word.capitalize()
            )
    return " ".join(result)


def _component_id_from_key(
    field_key: str, known_ids: set[str]
) -> str | None:
    """Return the longest matching component_id prefix of field_key."""
    for cid in sorted(known_ids, key=len, reverse=True):
        if field_key.startswith(cid + "_"):
            return cid
    return None


def _field_meta(field_key: str) -> tuple:
    """Look up (unit, device_class, state_class) by field name suffix."""
    for field_name, meta in _FIELD_META.items():
        if field_key == field_name or field_key.endswith("_" + field_name):
            return meta
    return _DEFAULT_META


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Joulzen sensors from a config entry."""
    coordinator: JoulzenCoordinator = (
        hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    )

    entities: list[SensorEntity] = [MqttLastPublishedSensor(coordinator)]

    known_comp_ids = set(coordinator.components_info)
    live_data: dict = (coordinator.data or {}).get("live", {})
    for field_key in live_data:
        # Skip metric-group aggregates; keep component fields and KPIs
        if (
            _component_id_from_key(field_key, known_comp_ids) is None
            and not field_key.startswith("kpi_")
        ):
            continue
        entities.append(
            JoulzenLiveSensor(coordinator, field_key, entry.entry_id)
        )

    _LOGGER.debug("Creating %d live sensors", len(entities) - 1)
    async_add_entities(entities)


class MqttLastPublishedSensor(
    CoordinatorEntity[JoulzenCoordinator], SensorEntity
):
    """Sensor showing when MQTT data was last published."""

    _attr_name = "MQTT last published"
    _attr_unique_id = "joulzen_mqtt_last_published"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: JoulzenCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def native_value(self) -> datetime | None:
        return (self.coordinator.data or {}).get("_last_published")


class JoulzenLiveSensor(
    CoordinatorEntity[JoulzenCoordinator], SensorEntity
):
    """One sensor per live API field."""

    def __init__(
        self,
        coordinator: JoulzenCoordinator,
        field_key: str,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._field_key = field_key
        self._attr_unique_id = f"{entry_id}_{field_key}"

        comp_id = _component_id_from_key(
            field_key, set(coordinator.components_info)
        )
        if comp_id:
            comp_info = coordinator.components_info.get(comp_id, {})
            comp_type = comp_info.get("type", "")
            type_label = COMPONENT_TYPE_LABELS.get(
                comp_type, comp_type.title()
            )
            field_name = field_key[len(comp_id) + 1:]

            # Determine index within siblings of the same type
            siblings = sorted(
                cid for cid, info in coordinator.components_info.items()
                if info.get("type") == comp_type
            )
            multi = len(siblings) > 1
            n = siblings.index(comp_id) + 1  # 1-based, no zero padding

            # entity_id: sensor.joulzen_{type_lower}[_{n}]_{fieldname_lower}
            id_parts = ["joulzen", comp_type.lower()]
            if multi:
                id_parts.append(str(n))
            id_parts.append(field_name.lower())
            self.entity_id = f"sensor.{'_'.join(id_parts)}"

            # friendly name: JZ {TypeLabel}[ {n}] {Field Name}
            name_parts = ["JZ", type_label]
            if multi:
                name_parts.append(str(n))
            name_parts.append(_fmt(field_name))
            self._attr_name = " ".join(name_parts)
        else:
            # Metric groups / KPIs: no component type, use group prefix as-is
            self.entity_id = f"sensor.joulzen_{field_key.lower()}"
            self._attr_name = f"JZ {_fmt(field_key)}"

        unit, device_class, state_class = _field_meta(field_key)
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class

    @property
    def native_value(self) -> float | None:
        return (self.coordinator.data or {}).get("live", {}).get(
            self._field_key
        )
