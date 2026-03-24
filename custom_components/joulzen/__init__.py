"""
The Joulzen custom component.

Config flow based integration with MQTT publishing to a backend.
Add via Settings → Integrations → Add Integration → Joulzen.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow
from .const import (
    CONF_MQTT_TOPIC,
    DATA_COORDINATOR,
    DOMAIN,
)
from .config_flow import JoulzenOAuth2Impl
from .coordinator import JoulzenCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Joulzen component (legacy YAML not supported)."""
    config_entry_oauth2_flow.async_register_implementation(
        hass, DOMAIN, JoulzenOAuth2Impl(hass)
    )
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config to new structure (topic, interval, mapping only)."""
    if entry.version > 2:
        return True

    data = dict(entry.data)

    # Extract topic from old config (was mqtt_broker or mqtt_topic)
    if CONF_MQTT_TOPIC not in data:
        old_topic = data.pop("mqtt_broker", data.pop("mqtt_topic", "jouli"))
        data[CONF_MQTT_TOPIC] = (
            old_topic.split("/")[0] if "/" in str(old_topic) else old_topic
        )

    # Remove deprecated broker/port/use_ha_mqtt
    data.pop("mqtt_port", None)
    data.pop("use_ha_mqtt", None)

    hass.config_entries.async_update_entry(entry, data=data, version=2)
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

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


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
