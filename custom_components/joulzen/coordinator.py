"""Coordinator for Joulzen: fetches live API data and posts overrides."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .component_registry import extract_components_by_type
from .const import (
    CONF_HOUSEHOLD_JSON,
    CONF_PUBLISH_INTERVAL,
    CONF_SENSOR_MAPPING,
    DEFAULT_PUBLISH_INTERVAL,
    DOMAIN,
    JOULZEN_API_URL,
    OVERRIDE_SOURCE_ID,
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
    """Polls Joulzen live API and POSTs entity overrides to local service."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
        oauth_session: config_entry_oauth2_flow.OAuth2Session,
    ) -> None:
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
        # Extract systemId and component metadata from household JSON
        self.components_info: dict[str, dict[str, str]] = {}
        self.tank_children: dict[str, list[str]] = {}
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
            # Map each joulzenTank to its ordered layer component IDs
            for arr in household.get("componentsByType", {}).values():
                if not isinstance(arr, list):
                    continue
                for comp in arr:
                    if comp.get("type") == "joulzenTank":
                        tank_id = comp.get("componentId", "")
                        layers = [
                            layer.get("componentId", "")
                            for layer in comp.get("tankLayers", [])
                            if layer.get("componentId")
                        ]
                        if tank_id:
                            self.tank_children[tank_id] = layers
        except (json.JSONDecodeError, AttributeError):
            self._system_id = ""

        self._oauth_session = oauth_session

        _LOGGER.info(
            "Joulzen coordinator: system_id=%s",
            self._system_id,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch live data from API and POST entity overrides."""
        results: dict[str, Any] = {"live": {}}
        now = datetime.now(tz=timezone.utc)
        session = async_get_clientsession(self.hass)

        # ── Fetch live data from Joulzen API ─────────────────────────────
        if self._system_id:
            await self._oauth_session.async_ensure_token_valid()
            access_token = self._oauth_session.token["access_token"]
            url = f"{JOULZEN_API_URL}/live?system_id={quote(self._system_id)}"
            try:
                async with session.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
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
                "Skipping live fetch: system_id=%r", self._system_id
            )

        # ── Collect mapped HA entity states ──────────────────────────────
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
                "last_updated": state.last_updated.isoformat(),
            }
            results[my_id] = entry
            entities[my_id] = entry

        # ── POST entity states to local override endpoint ────────────────
        if entities and self._system_id:
            payload: dict[str, Any] = {
                "sourceId": OVERRIDE_SOURCE_ID,
                "entities": entities,
                "timestamp": now.isoformat(),
            }
            url = f"{JOULZEN_API_URL}?system_id={quote(self._system_id)}"
            _LOGGER.debug("Override POST url=%s payload=%s", url, payload)
            await self._oauth_session.async_ensure_token_valid()
            access_token = self._oauth_session.token["access_token"]
            try:
                async with session.post(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    json=payload,
                ) as resp:
                    if not resp.ok:
                        body = await resp.text()
                        _LOGGER.warning(
                            "Override POST failed: status=%s body=%s",
                            resp.status, body,
                        )
                    else:
                        _LOGGER.debug("Override POST to %s succeeded", url)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Override POST error: %s", err)

        results["_last_published"] = now
        return results
