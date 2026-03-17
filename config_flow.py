"""Config flow for Joulzen integration."""
from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult, section
from homeassistant.helpers import selector

from .component_registry import (
    COMPONENT_TYPE_ORDER,
    build_component_sections,
    extract_components_by_type,
)
from .const import (
    CONF_HOUSEHOLD_JSON,
    CONF_MQTT_TOPIC,
    CONF_PUBLISH_INTERVAL,
    CONF_SENSOR_MAPPING,
    DEFAULT_MQTT_TOPIC,
    DEFAULT_PUBLISH_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_HOUSEHOLD_KEY = "household_json"
_BACK_KEY = "_back"


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _schema_step1(defaults: dict[str, Any]) -> vol.Schema:
    """Schema for step 1: topic and interval."""
    return vol.Schema(
        {
            vol.Required(
                CONF_MQTT_TOPIC,
                default=defaults.get(CONF_MQTT_TOPIC, DEFAULT_MQTT_TOPIC),
            ): str,
            vol.Required(
                CONF_PUBLISH_INTERVAL,
                default=defaults.get(
                    CONF_PUBLISH_INTERVAL, DEFAULT_PUBLISH_INTERVAL
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=5, max=3600)),
        }
    )


def _schema_step_household(
    default_json: str, include_back: bool = True
) -> vol.Schema:
    """Schema for step 2: paste household JSON."""
    field: Any
    if default_json:
        field = vol.Required(_HOUSEHOLD_KEY, default=default_json)
    else:
        field = vol.Required(_HOUSEHOLD_KEY)
    schema_dict: dict = {
        field: selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        )
    }
    if include_back:
        schema_dict[
            vol.Optional(_BACK_KEY, default=False)
        ] = selector.BooleanSelector()
    return vol.Schema(schema_dict)


def _entity_defaults_from_mapping(mapping_str: str) -> dict[str, str]:
    """Build {my_id: ha_entity} lookup from stored mapping JSON."""
    try:
        mapping = json.loads(mapping_str or "[]")
    except json.JSONDecodeError:
        return {}
    if not isinstance(mapping, list):
        return {}
    return {
        item["my_id"]: item["ha_entity"]
        for item in mapping
        if isinstance(item, dict)
        and "my_id" in item
        and "ha_entity" in item
    }


def _schema_step_type(
    component_sections: dict[str, tuple[list[str], list[str]]],
    mapping_str: str,
) -> vol.Schema:
    """Schema for a component-type step: Live/Day sections per component."""
    entity_defaults = _entity_defaults_from_mapping(mapping_str)
    entity_sel = selector.EntitySelector()
    schema_dict: dict = {}

    for comp_id, (live_keys, agg_keys) in component_sections.items():
        live_dict: dict = {}
        for key in live_keys:
            dv = entity_defaults.get(key)
            if dv:
                live_dict[
                    vol.Optional(
                        key, description={"suggested_value": dv}
                    )
                ] = entity_sel
            else:
                live_dict[vol.Optional(key)] = entity_sel

        agg_dict: dict = {}
        for key in agg_keys:
            dv = entity_defaults.get(key)
            if dv:
                agg_dict[
                    vol.Optional(
                        key, description={"suggested_value": dv}
                    )
                ] = entity_sel
            else:
                agg_dict[vol.Optional(key)] = entity_sel

        if live_dict:
            schema_dict[f"{comp_id}_live"] = section(
                vol.Schema(live_dict), {"collapsed": False}
            )
        if agg_dict:
            schema_dict[f"{comp_id}_day"] = section(
                vol.Schema(agg_dict), {"collapsed": False}
            )

    # Back button at the bottom
    schema_dict[
        vol.Optional(_BACK_KEY, default=False)
    ] = selector.BooleanSelector()

    return vol.Schema(schema_dict)


def _collect_from_user_input(
    user_input: dict[str, Any],
) -> dict[str, str]:
    """Flatten sectioned user_input into {field_key: ha_entity}."""
    result: dict[str, str] = {}
    for key, value in user_input.items():
        if key == _BACK_KEY:
            continue
        if isinstance(value, dict):
            # Section data — flatten one level
            for field_key, entity in value.items():
                if isinstance(entity, list):
                    entity = entity[0] if entity else ""
                if entity and isinstance(entity, str) and entity.strip():
                    result[field_key] = entity.strip()
        else:
            if isinstance(value, list):
                value = value[0] if value else ""
            if value and isinstance(value, str) and value.strip():
                result[key] = value.strip()
    return result


def _mapping_from_accumulator(accumulator: dict[str, str]) -> str:
    """Convert accumulator to CONF_SENSOR_MAPPING JSON."""
    return json.dumps(
        [
            {"ha_entity": entity, "my_id": key}
            for key, entity in accumulator.items()
            if entity
        ]
    )


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------

class JoulzenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Joulzen."""

    VERSION = 2

    # ------------------------------------------------------------------
    # Step 1: MQTT settings
    # ------------------------------------------------------------------

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Step 1: Topic and interval."""
        if user_input is not None:
            self._step1_data = user_input
            return self.async_show_form(
                step_id="household",
                data_schema=_schema_step_household("", include_back=True),
                last_step=False,
            )
        return self.async_show_form(
            step_id="user",
            data_schema=_schema_step1({}),
            last_step=False,
        )

    # ------------------------------------------------------------------
    # Step 2: Household JSON
    # ------------------------------------------------------------------

    async def async_step_household(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Step 2: Paste household JSON."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get(_BACK_KEY):
                return self.async_show_form(
                    step_id="user",
                    data_schema=_schema_step1(
                        getattr(self, "_step1_data", {})
                    ),
                    last_step=False,
                )

            raw = user_input.get(_HOUSEHOLD_KEY, "")
            try:
                household = json.loads(raw)
            except json.JSONDecodeError:
                errors[_HOUSEHOLD_KEY] = "invalid_json"
            else:
                self._household_json = raw
                self._components_by_type = extract_components_by_type(
                    household
                )
                self._type_all = [
                    t
                    for t in COMPONENT_TYPE_ORDER
                    if self._components_by_type.get(t)
                ]
                self._type_idx = 0
                self._mapping_accumulator: dict[str, str] = {}
                return self._show_type_step("[]")

        return self.async_show_form(
            step_id="household",
            data_schema=_schema_step_household(
                "", include_back=True
            ),
            errors=errors,
            last_step=False,
        )

    # ------------------------------------------------------------------
    # Steps 3..N: Per-component-type pages (dynamic via __getattr__)
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        if name.startswith("async_step_ct_"):
            async def _handler(
                user_input: dict[str, Any] | None = None,
            ) -> FlowResult:
                return await self._handle_type_step(
                    user_input, last_mapping="[]"
                )
            return _handler
        raise AttributeError(name)

    async def _handle_type_step(
        self,
        user_input: dict[str, Any] | None,
        last_mapping: str,
    ) -> FlowResult:
        """Shared handler for all component-type steps."""
        if user_input is not None:
            if user_input.get(_BACK_KEY):
                self._type_idx -= 1
                if self._type_idx < 0:
                    return self.async_show_form(
                        step_id="household",
                        data_schema=_schema_step_household(
                            getattr(self, "_household_json", ""),
                            include_back=True,
                        ),
                        last_step=False,
                    )
                return self._show_type_step(last_mapping)

            self._mapping_accumulator.update(
                _collect_from_user_input(user_input)
            )
            self._type_idx += 1
            if self._type_idx >= len(
                getattr(self, "_type_all", [])
            ):
                return self._finish_config()
            return self._show_type_step(last_mapping)

        return self._show_type_step(last_mapping)

    def _show_type_step(self, mapping_str: str) -> FlowResult:
        """Show the type page at the current index."""
        type_all: list[str] = getattr(self, "_type_all", [])
        idx: int = getattr(self, "_type_idx", 0)
        type_name = type_all[idx]
        components = getattr(
            self, "_components_by_type", {}
        ).get(type_name, [])
        comp_sections = build_component_sections(type_name, components)
        is_last = idx == len(type_all) - 1
        return self.async_show_form(
            step_id=f"ct_{type_name}",
            data_schema=_schema_step_type(comp_sections, mapping_str),
            last_step=is_last,
        )

    def _finish_config(self) -> FlowResult:
        """Build config data and create the entry."""
        step1 = getattr(self, "_step1_data", {})
        data = {
            CONF_MQTT_TOPIC: step1.get(
                CONF_MQTT_TOPIC, DEFAULT_MQTT_TOPIC
            ),
            CONF_PUBLISH_INTERVAL: step1.get(
                CONF_PUBLISH_INTERVAL, DEFAULT_PUBLISH_INTERVAL
            ),
            CONF_HOUSEHOLD_JSON: getattr(
                self, "_household_json", ""
            ),
            CONF_SENSOR_MAPPING: _mapping_from_accumulator(
                getattr(self, "_mapping_accumulator", {})
            ),
        }
        return self.async_create_entry(
            title="Joulzen MQTT Bridge", data=data
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return JoulzenOptionsFlowHandler(config_entry)


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------

class JoulzenOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Joulzen options (reconfigure topic, household, mapping)."""

    def __init__(
        self, config_entry: config_entries.ConfigEntry
    ) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    def _config(self) -> dict[str, Any]:
        return self.config_entry.data | self.config_entry.options

    # ------------------------------------------------------------------
    # Step 1: MQTT settings
    # ------------------------------------------------------------------

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Step 1: Topic and interval."""
        config = self._config()

        if user_input is not None:
            self._step1_data = user_input
            return self.async_show_form(
                step_id="household",
                data_schema=_schema_step_household(
                    config.get(CONF_HOUSEHOLD_JSON, ""),
                    include_back=True,
                ),
                last_step=False,
            )
        return self.async_show_form(
            step_id="init",
            data_schema=_schema_step1(config),
            last_step=False,
        )

    # ------------------------------------------------------------------
    # Step 2: Household JSON
    # ------------------------------------------------------------------

    async def async_step_household(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Step 2: Paste household JSON."""
        config = self._config()
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get(_BACK_KEY):
                return self.async_show_form(
                    step_id="init",
                    data_schema=_schema_step1(
                        getattr(self, "_step1_data", config)
                    ),
                    last_step=False,
                )

            raw = user_input.get(_HOUSEHOLD_KEY, "")
            try:
                household = json.loads(raw)
            except json.JSONDecodeError:
                errors[_HOUSEHOLD_KEY] = "invalid_json"
            else:
                self._household_json = raw
                self._components_by_type = extract_components_by_type(
                    household
                )
                self._type_all = [
                    t
                    for t in COMPONENT_TYPE_ORDER
                    if self._components_by_type.get(t)
                ]
                self._type_idx = 0
                self._mapping_accumulator: dict[str, str] = {}
                existing = config.get(CONF_SENSOR_MAPPING, "[]")
                return self._show_type_step(existing)

        return self.async_show_form(
            step_id="household",
            data_schema=_schema_step_household(
                config.get(CONF_HOUSEHOLD_JSON, ""),
                include_back=True,
            ),
            errors=errors,
            last_step=False,
        )

    # ------------------------------------------------------------------
    # Steps 3..N: Per-component-type pages (dynamic via __getattr__)
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        if name.startswith("async_step_ct_"):
            async def _handler(
                user_input: dict[str, Any] | None = None,
            ) -> FlowResult:
                config = self._config()
                return await self._handle_type_step(
                    user_input,
                    existing_mapping=config.get(
                        CONF_SENSOR_MAPPING, "[]"
                    ),
                )
            return _handler
        raise AttributeError(name)

    async def _handle_type_step(
        self,
        user_input: dict[str, Any] | None,
        existing_mapping: str,
    ) -> FlowResult:
        """Shared handler for all component-type steps."""
        if user_input is not None:
            if user_input.get(_BACK_KEY):
                self._type_idx -= 1
                if self._type_idx < 0:
                    return self.async_show_form(
                        step_id="household",
                        data_schema=_schema_step_household(
                            getattr(
                                self, "_household_json",
                                self._config().get(
                                    CONF_HOUSEHOLD_JSON, ""
                                ),
                            ),
                            include_back=True,
                        ),
                        last_step=False,
                    )
                return self._show_type_step(existing_mapping)

            self._mapping_accumulator.update(
                _collect_from_user_input(user_input)
            )
            self._type_idx += 1
            if self._type_idx >= len(
                getattr(self, "_type_all", [])
            ):
                return self._finish_options()
            return self._show_type_step(existing_mapping)

        return self._show_type_step(existing_mapping)

    def _show_type_step(self, mapping_str: str) -> FlowResult:
        """Show the type page at the current index."""
        type_all: list[str] = getattr(self, "_type_all", [])
        idx: int = getattr(self, "_type_idx", 0)
        type_name = type_all[idx]
        components = getattr(
            self, "_components_by_type", {}
        ).get(type_name, [])
        comp_sections = build_component_sections(type_name, components)
        is_last = idx == len(type_all) - 1
        return self.async_show_form(
            step_id=f"ct_{type_name}",
            data_schema=_schema_step_type(comp_sections, mapping_str),
            last_step=is_last,
        )

    def _finish_options(self) -> FlowResult:
        """Persist updated options and complete flow."""
        config = self._config()
        step1 = getattr(self, "_step1_data", config)
        sensor_mapping = _mapping_from_accumulator(
            getattr(self, "_mapping_accumulator", {})
        )
        data = {
            CONF_MQTT_TOPIC: step1.get(
                CONF_MQTT_TOPIC, config.get(CONF_MQTT_TOPIC)
            ),
            CONF_PUBLISH_INTERVAL: step1.get(
                CONF_PUBLISH_INTERVAL,
                config.get(CONF_PUBLISH_INTERVAL),
            ),
            CONF_HOUSEHOLD_JSON: getattr(
                self, "_household_json",
                config.get(CONF_HOUSEHOLD_JSON, ""),
            ),
            CONF_SENSOR_MAPPING: sensor_mapping,
        }
        _LOGGER.info(
            "Saving Joulzen options: topic=%s interval=%s",
            data[CONF_MQTT_TOPIC],
            data[CONF_PUBLISH_INTERVAL],
        )
        self.hass.config_entries.async_update_entry(
            self.config_entry, options=data
        )
        return self.async_create_entry(title="", data=data)
