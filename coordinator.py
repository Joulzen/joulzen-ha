"""Coordinator for Joulzen MQTT publishing via Home Assistant's MQTT integration."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_MQTT_TOPIC,
    CONF_PUBLISH_INTERVAL,
    CONF_SENSOR_MAPPING,
    DEFAULT_MQTT_TOPIC,
    DEFAULT_PUBLISH_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class JoulzenCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls sensor states and publishes via HA's MQTT integration."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: dict[str, Any],
    ) -> None:
        """Initialize the coordinator."""
        interval_seconds = config.get(CONF_PUBLISH_INTERVAL, DEFAULT_PUBLISH_INTERVAL)
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
        _LOGGER.info(
            "Joulzen coordinator config: topic=%s mapping=%s",
            self._topic_prefix,
            self._sensor_mappings,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch sensor states and publish via MQTT as a single JSON payload."""
        results: dict[str, Any] = {}
        entities: dict[str, str] = {}
        now = datetime.now(tz=timezone.utc)

        for mapping in self._sensor_mappings:
            ha_entity = mapping.get("ha_entity")
            my_id = mapping.get("my_id")

            if not ha_entity or not my_id:
                continue

            state = self.hass.states.get(ha_entity)
            if state is None or state.state in ("unavailable", "unknown"):
                _LOGGER.debug(
                    "Skipping %s, state is %s",
                    ha_entity,
                    state.state if state else "None",
                )
                continue

            value = state.state
            unit = state.attributes.get("unit_of_measurement")
            entry = {"value": value, "unit": unit}
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
            _LOGGER.debug("Published %s to %s", payload, topic)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to publish to %s: %s", topic, err)

        results["_last_published"] = now
        return results
