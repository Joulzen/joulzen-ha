"""Config flow for Joulzen integration."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets as py_secrets
from typing import Any

import aiohttp

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult, section
from homeassistant.helpers import config_entry_oauth2_flow, selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    LocalOAuth2Implementation,
)

from .component_registry import (
    COMPONENT_TYPE_ORDER,
    build_component_sections,
    extract_components_by_type,
)
from .const import (
    CONF_HOUSEHOLD_JSON,
    CONF_PUBLISH_INTERVAL,
    CONF_SENSOR_MAPPING,
    DEFAULT_PUBLISH_INTERVAL,
    DOMAIN,
    JOULZEN_API_URL,
    OAUTH_CLIENT_ID,
    OAUTH_CLIENT_SECRET,
    SUPABASE_URL,
)

_LOGGER = logging.getLogger(__name__)

_BACK_KEY = "_back"
_SELECTED_HOUSEHOLD_KEY = "selected_household"


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

def _household_label(h: dict) -> str:
    """Build a human-readable label for a household entry."""
    name = h.get("name", "")
    address = h.get("address", "")
    if name and address:
        return f"{name} \u2014 {address}"
    return name or address or h.get("systemId", "Unknown")


def _schema_select_household(households: list) -> vol.Schema:
    """Schema for the household selection dropdown."""
    return vol.Schema({
        vol.Required(_SELECTED_HOUSEHOLD_KEY, default="0"):
            selector.SelectSelector(selector.SelectSelectorConfig(
                options=[
                    selector.SelectOptionDict(
                        value=str(i),
                        label=_household_label(h),
                    )
                    for i, h in enumerate(households)
                ]
            ))
    })


def _schema_select_components(
    type_all: list[str], selected: set[str] | None = None
) -> vol.Schema:
    """Schema for the component selection step.

    Each available component type becomes a boolean checkbox.
    ``selected`` pre-populates checkboxes when the user navigates back.
    """
    selected = selected or set()
    schema_dict: dict = {}
    for type_name in type_all:
        schema_dict[
            vol.Optional(f"select_{type_name}", default=(type_name in selected))
        ] = selector.BooleanSelector()
    schema_dict[vol.Optional(_BACK_KEY, default=False)] = selector.BooleanSelector()
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


async def _fetch_households(
    hass: HomeAssistant, access_token: str
) -> tuple:
    """GET /household and return (list, None) or (None, error_key)."""
    session = async_get_clientsession(hass)
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with session.get(
            f"{JOULZEN_API_URL}/household",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        ) as resp:
            if not resp.ok:
                body = await resp.text()
                _LOGGER.error(
                    "Joulzen /household fetch failed: status=%s body=%s",
                    resp.status,
                    body,
                )
                return None, "cannot_fetch_household"
            data = await resp.json(content_type=None)
            return data, None
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Error fetching Joulzen households")
        return None, "cannot_fetch_household"


# ---------------------------------------------------------------------------
# PKCE OAuth2 implementation
# ---------------------------------------------------------------------------

class JoulzenOAuth2Impl(LocalOAuth2Implementation):
    """LocalOAuth2Implementation with PKCE (S256) for Supabase."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            DOMAIN,
            OAUTH_CLIENT_ID,
            OAUTH_CLIENT_SECRET,
            f"{SUPABASE_URL}/auth/v1/oauth/authorize",
            f"{SUPABASE_URL}/auth/v1/oauth/token",
        )
        self._code_verifier: str = ""

    async def async_generate_authorize_url(self, flow_id: str) -> str:
        """Generate auth URL with PKCE challenge appended."""
        verifier = (
            base64.urlsafe_b64encode(py_secrets.token_bytes(32))
            .rstrip(b"=")
            .decode()
        )
        self._code_verifier = verifier
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode()).digest()
            )
            .rstrip(b"=")
            .decode()
        )
        url = await super().async_generate_authorize_url(flow_id)
        return (
            f"{url}&code_challenge={challenge}"
            "&code_challenge_method=S256"
        )

    def _basic_auth_header(self) -> str:
        return base64.b64encode(
            f"{OAUTH_CLIENT_ID}:{OAUTH_CLIENT_SECRET}".encode()
        ).decode()

    async def async_resolve_external_data(
        self, external_data: Any
    ) -> dict:
        """Exchange auth code for token, including PKCE verifier."""
        session = async_get_clientsession(self.hass)
        async with session.post(
            f"{SUPABASE_URL}/auth/v1/oauth/token",
            headers={"Authorization": f"Basic {self._basic_auth_header()}"},
            data={
                "grant_type": "authorization_code",
                "code": external_data["code"],
                "redirect_uri": self.redirect_uri,
                "code_verifier": self._code_verifier,
            },
        ) as resp:
            body = await resp.text()
            if not resp.ok:
                _LOGGER.error(
                    "Supabase token exchange failed: status=%s body=%s"
                    " redirect_uri=%s verifier_len=%d",
                    resp.status,
                    body,
                    self.redirect_uri,
                    len(self._code_verifier),
                )
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def async_refresh_token(self, token: dict) -> dict:
        """Refresh the access token using Basic auth, as Supabase requires."""
        session = async_get_clientsession(self.hass)
        async with session.post(
            f"{SUPABASE_URL}/auth/v1/oauth/token",
            headers={"Authorization": f"Basic {self._basic_auth_header()}"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": token["refresh_token"],
            },
        ) as resp:
            if not resp.ok:
                body = await resp.text()
                _LOGGER.error(
                    "Supabase token refresh failed: status=%s body=%s",
                    resp.status,
                    body,
                )
            resp.raise_for_status()
            new_token = await resp.json(content_type=None)
            return {**token, **new_token}


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------

class JoulzenConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler,
    domain=DOMAIN,
):
    """Handle a config flow for Joulzen (OAuth2 + household)."""

    VERSION = 2
    DOMAIN = DOMAIN

    @property
    def logger(self) -> logging.Logger:
        """Return the logger."""
        return _LOGGER

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Entry point: inject PKCE implementation and start OAuth."""
        self.flow_impl = JoulzenOAuth2Impl(self.hass)
        return await self.async_step_auth()

    # ------------------------------------------------------------------
    # OAuth2 callback → fetch households from API.
    # ------------------------------------------------------------------

    async def async_oauth_create_entry(
        self, data: dict[str, Any]
    ) -> FlowResult:
        """OAuth complete — fetch households and show selection."""
        self._oauth_data = data
        return await self._fetch_and_show_households()

    async def _fetch_and_show_households(self) -> FlowResult:
        """Fetch /household and render the selection form."""
        token = self._oauth_data["token"]["access_token"]
        households, error = await _fetch_households(self.hass, token)
        if error:
            return self.async_show_form(
                step_id="select_household",
                data_schema=vol.Schema({}),
                errors={"base": error},
                last_step=False,
            )
        if not households:
            return self.async_abort(reason="no_household")
        self._households: list = households
        return self.async_show_form(
            step_id="select_household",
            data_schema=_schema_select_household(households),
            last_step=False,
        )

    # ------------------------------------------------------------------
    # Step: Select household
    # ------------------------------------------------------------------

    async def async_step_select_household(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Step: choose one household from the fetched list."""
        if user_input is not None:
            idx = int(user_input[_SELECTED_HOUSEHOLD_KEY])
            household = self._households[idx]
            self._household_json = json.dumps(household)
            self._components_by_type = extract_components_by_type(household)
            type_all = [
                t for t in COMPONENT_TYPE_ORDER
                if self._components_by_type.get(t)
            ]
            self._type_all_household = type_all
            self._type_all: list[str] = []
            self._selected_types: set[str] = set()
            self._type_idx = 0
            self._mapping_accumulator: dict[str, str] = {}
            return self._show_select_components()

        # Back-navigation: re-use cached list if available
        if getattr(self, "_households", None):
            return self.async_show_form(
                step_id="select_household",
                data_schema=_schema_select_household(self._households),
                last_step=False,
            )
        return await self._fetch_and_show_households()

    # ------------------------------------------------------------------
    # Step: Select components
    # ------------------------------------------------------------------

    async def async_step_select_components(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Show all components as checkboxes; only selected get a config page."""
        type_all_household: list[str] = getattr(
            self, "_type_all_household", []
        )

        if user_input is not None:
            if user_input.get(_BACK_KEY):
                return await self.async_step_select_household()

            selected = [
                t for t in type_all_household if user_input.get(f"select_{t}")
            ]
            self._selected_types = set(selected)
            self._type_all = selected
            self._type_idx = 0
            self._mapping_accumulator = {}

            if not selected:
                return self._finish_config()
            return self._show_type_step("[]")

        return self._show_select_components()

    def _show_select_components(self) -> FlowResult:
        """Render the component selection form."""
        type_all_household: list[str] = getattr(self, "_type_all_household", [])
        selected_types: set[str] = getattr(self, "_selected_types", set())
        # last_step=True  → button reads "Submit" (no types to configure)
        # last_step=False → button reads "Next"   (user may select types)
        return self.async_show_form(
            step_id="select_components",
            data_schema=_schema_select_components(type_all_household, selected_types),
            last_step=not type_all_household,
        )

    # ------------------------------------------------------------------
    # Steps: Per-component-type pages (dynamic via __getattr__)
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
                    self._type_idx = 0
                    return self._show_select_components()
                return self._show_type_step(last_mapping)

            self._mapping_accumulator.update(
                _collect_from_user_input(user_input)
            )
            self._type_idx += 1
            if self._type_idx >= len(getattr(self, "_type_all", [])):
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
        data = {
            # OAuth token data (token + auth_implementation keys)
            **getattr(self, "_oauth_data", {}),
            CONF_PUBLISH_INTERVAL: DEFAULT_PUBLISH_INTERVAL,
            CONF_HOUSEHOLD_JSON: getattr(self, "_household_json", ""),
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
    """Handle Joulzen options (reconfigure household and mapping)."""

    def __init__(
        self, config_entry: config_entries.ConfigEntry
    ) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    def _config(self) -> dict[str, Any]:
        return self.config_entry.data | self.config_entry.options

    # ------------------------------------------------------------------
    # Entry point: fetch households from API
    # ------------------------------------------------------------------

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Fetch households and show selection."""
        return await self._fetch_and_show_households()

    async def _fetch_and_show_households(self) -> FlowResult:
        """Fetch /household and render the selection form."""
        token = self.config_entry.data["token"]["access_token"]
        households, error = await _fetch_households(self.hass, token)
        if error:
            return self.async_show_form(
                step_id="select_household",
                data_schema=vol.Schema({}),
                errors={"base": error},
                last_step=False,
            )
        if not households:
            return self.async_abort(reason="no_household")
        self._households: list = households
        return self.async_show_form(
            step_id="select_household",
            data_schema=_schema_select_household(households),
            last_step=False,
        )

    # ------------------------------------------------------------------
    # Step: Select household
    # ------------------------------------------------------------------

    async def async_step_select_household(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Step: choose one household from the fetched list."""
        if user_input is not None:
            idx = int(user_input[_SELECTED_HOUSEHOLD_KEY])
            household = self._households[idx]
            self._household_json = json.dumps(household)
            self._components_by_type = extract_components_by_type(household)
            type_all = [
                t for t in COMPONENT_TYPE_ORDER
                if self._components_by_type.get(t)
            ]
            self._type_all_household = type_all
            self._type_all: list[str] = []
            self._selected_types: set[str] = set()
            self._type_idx = 0
            self._mapping_accumulator: dict[str, str] = {}
            return self._show_select_components()

        if getattr(self, "_households", None):
            return self.async_show_form(
                step_id="select_household",
                data_schema=_schema_select_household(self._households),
                last_step=False,
            )
        return await self._fetch_and_show_households()

    # ------------------------------------------------------------------
    # Step: Select components
    # ------------------------------------------------------------------

    async def async_step_select_components(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Show all components as checkboxes; only selected get a config page."""
        type_all_household: list[str] = getattr(
            self, "_type_all_household", []
        )
        config = self._config()

        if user_input is not None:
            if user_input.get(_BACK_KEY):
                return await self.async_step_select_household()

            selected = [
                t for t in type_all_household if user_input.get(f"select_{t}")
            ]
            self._selected_types = set(selected)
            self._type_all = selected
            self._type_idx = 0
            self._mapping_accumulator = {}

            if not selected:
                return self._finish_options()
            return self._show_type_step(config.get(CONF_SENSOR_MAPPING, "[]"))

        return self._show_select_components()

    def _show_select_components(self) -> FlowResult:
        """Render the component selection form."""
        type_all_household: list[str] = getattr(self, "_type_all_household", [])
        selected_types: set[str] = getattr(self, "_selected_types", set())
        return self.async_show_form(
            step_id="select_components",
            data_schema=_schema_select_components(type_all_household, selected_types),
            last_step=not type_all_household,
        )

    # ------------------------------------------------------------------
    # Steps: Per-component-type pages (dynamic via __getattr__)
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
                    self._type_idx = 0
                    return self._show_select_components()
                return self._show_type_step(existing_mapping)

            self._mapping_accumulator.update(
                _collect_from_user_input(user_input)
            )
            self._type_idx += 1
            if self._type_idx >= len(getattr(self, "_type_all", [])):
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
        sensor_mapping = _mapping_from_accumulator(
            getattr(self, "_mapping_accumulator", {})
        )
        data = {
            CONF_PUBLISH_INTERVAL: DEFAULT_PUBLISH_INTERVAL,
            CONF_HOUSEHOLD_JSON: getattr(
                self, "_household_json",
                config.get(CONF_HOUSEHOLD_JSON, ""),
            ),
            CONF_SENSOR_MAPPING: sensor_mapping,
        }
        _LOGGER.info(
            "Saving Joulzen options: interval=%s",
            data[CONF_PUBLISH_INTERVAL],
        )
        self.hass.config_entries.async_update_entry(
            self.config_entry, options=data
        )
        return self.async_create_entry(title="", data=data)
