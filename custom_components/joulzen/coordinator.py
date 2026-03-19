"""Coordinator for Joulzen: fetches live API data and publishes via MQTT."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .component_registry import extract_components_by_type
from .const import (
    CONF_HOUSEHOLD_JSON,
    CONF_MQTT_TOPIC,
    CONF_PUBLISH_INTERVAL,
    CONF_SENSOR_MAPPING,
    DEFAULT_MQTT_TOPIC,
    DEFAULT_PUBLISH_INTERVAL,
    DOMAIN,
    JOULZEN_API_URL,
)

# Component type → human-readable label
COMPONENT_TYPE_LABELS: dict[str, str] = {
    "grid": "Grid",
    "energyCommunity": "Energy Community",
    "pv": "Solar PV",
    "battery": "Battery",
    "appliance": "Appliance",
    "heater": "Heat Pump",
    "districtHeating": "District Heating",
    "joulzenTank": "Thermal Tank",
    "tankLayer": "Tank Layer",
    "thermostat": "Thermostat",
    "ev": "EV Charger",
    "weather": "Weather Station",
    "heatingCircuit": "Heating Circuit",
    "household": "Household Load",
}

_LOGGER = logging.getLogger(__name__)

# Fields that carry no numeric sensor value
_SKIP_FIELDS: frozenset[str] = frozenset({
    "componentId", "dateTime",
    "isAvailable", "isActivated", "isConstrained", "hasError",
    "errorCode", "constraints",
})

# 0-1 ratio fields → multiply by 100 so HA displays them as %
_RATIO_FIELDS: frozenset[str] = frozenset({
    "soc", "totalAvailability",
    "activeTime", "constrainedTime", "errorTime",
    "autarky",
})


def _parse_live_response(data: dict) -> dict[str, float]:
    """Flatten live API JSON into {field_key: numeric_value}."""
    result: dict[str, float] = {}

    def _add(prefix: str, section: dict) -> None:
        for field, raw in section.items():
            if field in _SKIP_FIELDS:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            key = f"{prefix}_{field}"
            scaled = round(value * 100, 2) if field in _RATIO_FIELDS else value
            result[key] = scaled

    # Per-component current + day readings
    for comp_id, sections in data.get("components", {}).items():
        for section_data in sections.values():
            if isinstance(section_data, dict):
                _add(comp_id, section_data)

    # Aggregate metric groups (hyphens → underscores)
    for group_name, sections in data.get("metric-groups", {}).items():
        prefix = group_name.replace("-", "_")
        for section_data in sections.values():
            if isinstance(section_data, dict):
                _add(prefix, section_data)

    # KPIs — grouped by period (current / day / month)
    for period, kpi_data in data.get("kpis", {}).items():
        if isinstance(kpi_data, dict):
            _add(f"kpi_{period}", kpi_data)

    return result


class JoulzenCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls Joulzen live API and publishes HA sensor states via MQTT."""

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        interval_seconds = config.get(
            CONF_PUBLISH_INTERVAL, DEFAULT_PUBLISH_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval_seconds),
        )
        self._sensor_mappings: list[dict[str, str]] = json.loads(
            config.get(CONF_SENSOR_MAPPING, "[]")
        )
        self._topic_prefix = config.get(CONF_MQTT_TOPIC, DEFAULT_MQTT_TOPIC)

        # Extract systemId and component metadata from household JSON
        self.components_info: dict[str, dict[str, str]] = {}
        try:
            household = json.loads(config.get(CONF_HOUSEHOLD_JSON, "{}"))
            self._system_id: str = household.get("systemId", "")
            for comp_type, comp_list in (
                extract_components_by_type(household).items()
            ):
                label = COMPONENT_TYPE_LABELS.get(comp_type, comp_type)
                for comp in comp_list:
                    cid = comp.get("componentId", "")
                    if cid:
                        self.components_info[cid] = {
                            "type": comp_type,
                            "name": comp.get("name") or label,
                        }
        except (json.JSONDecodeError, AttributeError):
            self._system_id = ""

        # OAuth2 access token stored by HA
        self._access_token: str = (
            config.get("token", {}).get("access_token", "")
        )

        _LOGGER.info(
            "Joulzen coordinator: topic=%s system_id=%s",
            self._topic_prefix,
            self._system_id,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch live data from API and publish sensor states via MQTT."""
        results: dict[str, Any] = {"live": {}}
        now = datetime.now(tz=timezone.utc)

        # ── Fetch live data from Joulzen API ─────────────────────────────
        if self._system_id and self._access_token:
            url = f"{JOULZEN_API_URL}/live?system_id={quote(self._system_id)}"
            session = async_get_clientsession(self.hass)
            try:
                async with session.get(
                    url,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                ) as resp:
                    body = await resp.text()
                    if resp.ok:
                        _LOGGER.debug("Live data: %s", body)
                        results["live"] = _parse_live_response(
                            json.loads(body)
                        )
                    else:
                        raise UpdateFailed(
                            f"Live data fetch failed: status={resp.status}"
                            f" body={body}"
                        )
            except UpdateFailed:
                raise
            except Exception as err:  # noqa: BLE001
                raise UpdateFailed(f"Live data request error: {err}") from err
        else:
            _LOGGER.debug(
                "Skipping live fetch: system_id=%r token_present=%s",
                self._system_id, bool(self._access_token),
            )

        # ── Publish HA sensor states via MQTT ────────────────────────────
        entities: dict[str, Any] = {}
        for mapping in self._sensor_mappings:
            ha_entity = mapping.get("ha_entity")
            my_id = mapping.get("my_id")
            if not ha_entity or not my_id:
                continue
            state = self.hass.states.get(ha_entity)
            if state is None or state.state in ("unavailable", "unknown"):
                _LOGGER.debug(
                    "Skipping %s: state=%s",
                    ha_entity,
                    state.state if state else "None",
                )
                continue
            entry = {
                "value": state.state,
                "unit": state.attributes.get("unit_of_measurement"),
            }
            results[my_id] = entry
            entities[my_id] = entry

        payload: dict[str, Any] = {
            "entities": entities,
            "timestamp": now.isoformat(),
        }
        topic = self._topic_prefix.rstrip("/")
        try:
            await mqtt.async_publish(
                self.hass, topic, json.dumps(payload), qos=0, retain=False
            )
            _LOGGER.debug("Published to %s", topic)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("MQTT publish failed: %s", err)

        results["_last_published"] = now
        return results
