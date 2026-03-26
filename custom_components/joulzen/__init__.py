"""
The Joulzen custom component.

Add via Settings → Integrations → Add Integration → Joulzen.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow, entity_registry as er
from .const import (
    DATA_COORDINATOR,
    DOMAIN,
)
from .config_flow import JoulzenOAuth2Impl
from .coordinator import JoulzenCoordinator
from .dashboard import async_create_dashboard, async_remove_dashboard

PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Joulzen component (legacy YAML not supported)."""
    config_entry_oauth2_flow.async_register_implementation(
        hass, DOMAIN, JoulzenOAuth2Impl(hass)
    )
    return True



async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Joulzen from a config entry."""
    config = entry.data | entry.options
    implementation = await (
        config_entry_oauth2_flow
        .async_get_config_entry_implementation(hass, entry)
    )
    oauth_session = config_entry_oauth2_flow.OAuth2Session(
        hass, entry, implementation
    )
    coordinator = JoulzenCoordinator(hass, config, oauth_session)

    # Store coordinator before first refresh so sensor platform can access it
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_COORDINATOR: coordinator,
    }

    await coordinator.async_config_entry_first_refresh()

    # Remove entity registry entries whose component IDs are no longer
    # present in the current household (e.g. after a household switch).
    current_comp_ids = set(coordinator.components_info)
    if current_comp_ids:
        ent_reg = er.async_get(hass)
        uid_prefix = entry.entry_id + "_"
        for entity_entry in er.async_entries_for_config_entry(
            ent_reg, entry.entry_id
        ):
            uid = entity_entry.unique_id
            if not uid.startswith(uid_prefix):
                continue
            uid_suffix = uid[len(uid_prefix):]
            if not any(
                uid_suffix.startswith(cid + "_")
                for cid in current_comp_ids
            ):
                ent_reg.async_remove(entity_entry.entity_id)

    hass.async_create_task(async_create_dashboard(hass, coordinator))
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove dashboard when the config entry is deleted."""
    await async_remove_dashboard(hass)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, PLATFORMS
    )

    if unload_ok and DOMAIN in hass.data:
        data = hass.data[DOMAIN].pop(entry.entry_id, None)
        if data and (coordinator := data.get(DATA_COORDINATOR)):
            await coordinator.async_shutdown()

    return unload_ok
