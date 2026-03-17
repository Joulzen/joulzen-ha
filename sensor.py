"""Platform for Joulzen sensors."""
from __future__ import annotations

from datetime import datetime

import logging
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfPower
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import JoulzenCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Joulzen sensors from a config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinator = data.get(DATA_COORDINATOR)

    entities: list[SensorEntity] = [PVESupplyingSensor()]
    # log wherhe
    _LOGGER.info(f"Setting up Joulzen sensors for entry {entry.entry_id}")
    _LOGGER.info(f"Coordinator: {coordinator}")
    _LOGGER.info(f"Data: {data}")
    if coordinator is not None:
        entities.insert(0, MqttLastPublishedSensor(coordinator))
    _LOGGER.info(f"Entities: {entities}")

    async_add_entities(entities)


class MqttLastPublishedSensor(CoordinatorEntity[JoulzenCoordinator], SensorEntity):
    """Sensor showing when MQTT was last published."""

    _attr_name = "MQTT last published"
    _attr_unique_id = "joulzen_mqtt_last_published"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: JoulzenCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def native_value(self) -> datetime | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("_last_published")


class PVESupplyingSensor(SensorEntity):
    """Representation of a PV E-supplying sensor (mock constant value).

    Will be replaced with an external sensor later.
    """

    _attr_name = "PV E-supplying"
    _attr_unique_id = "joulzen_pv_e_supplying"
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_value = 5.2
