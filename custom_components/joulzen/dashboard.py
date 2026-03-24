"""Auto-generate a Lovelace dashboard for the Joulzen integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .coordinator import COMPONENT_TYPE_LABELS, JoulzenCoordinator

_LOGGER = logging.getLogger(__name__)

# Lowercase-keyed version of COMPONENT_TYPE_LABELS for lookup by lowercased type
_TYPE_LABELS: dict[str, str] = {
    k.lower(): v for k, v in COMPONENT_TYPE_LABELS.items()
}

DASHBOARD_URL_PATH = "joulzen"
_LOVELACE_CONTENT_KEY = f"lovelace.{DASHBOARD_URL_PATH}"
_LOVELACE_DASHBOARDS_KEY = "lovelace_dashboards"

# (icon, live_fields, daily_fields) per component type
# Field names are lowercased here because entity IDs use comp_type.lower()
_CARD_TEMPLATES: dict[str, tuple[str, list[str], list[str]]] = {
    "grid": (
        "mdi:transmission-tower",
        ["eSupplying", "eUsing", "price", "spending", "earning"],
        ["esupplied", "eused", "cost", "totalearned"],
    ),
    "pv": (
        "mdi:solar-panel-large",
        ["eSupplying"],
        ["esupplied"],
    ),
    "battery": (
        "mdi:battery-charging",
        ["soc", "eSupplying", "eUsing"],
        ["esupplied", "eused"],
    ),
    "heater": (
        "mdi:heat-pump-outline",
        ["eUsing", "hSupplying", "cop"],
        ["eused", "hsupplied", "meancop"],
    ),
    "ev": (
        "mdi:car-electric",
        ["eUsing", "soc"],
        ["eused"],
    ),
    "thermostat": (
        "mdi:thermostat",
        ["hUsing", "temperature", "targetTemperature"],
        ["hused"],
    ),
    "joulzentank": (
        "mdi:thermometer-water",
        ["hUsing", "hSupplying", "soc", "cop"],
        ["hused", "hsupplied"],
    ),
    "energycommunity": (
        "mdi:account-group",
        ["eSupplying", "price", "spending"],
        ["esupplied", "cost"],
    ),
    "districtheating": (
        "mdi:radiator",
        ["hSupplying", "price", "spending"],
        ["hsupplied", "cost"],
    ),
    "weather": (
        "mdi:weather-sunny",
        ["temperature"],
        ["meantemperature"],
    ),
    "appliance": (
        "mdi:lightning-bolt",
        ["eUsing"],
        ["eused"],
    ),
}

# Preferred display order (lowercase, matching comp_type.lower())
_TYPE_ORDER = [
    "grid", "energycommunity", "pv", "battery",
    "heater", "joulzentank", "districtheating",
    "ev", "appliance", "thermostat", "weather",
]


def _entity_id(comp_type: str, n: int, multi: bool, field: str) -> str:
    """Build sensor entity ID; comp_type is lowercased to match sensor.py."""
    parts = ["joulzen", comp_type.lower()]
    if multi:
        parts.append(str(n))
    parts.append(field.lower())
    return f"sensor.{'_'.join(parts)}"


def _layer_entity_id(
    layer_type: str, layer_n: int, layer_multi: bool, field: str
) -> str:
    return _entity_id(layer_type, layer_n, layer_multi, field)


def _build_tank_card(
    comp_type: str,
    comp_name: str,
    n: int,
    multi: bool,
    layer_comp_ids: list[str],
    all_layer_ids: list[str],  # all layers across all tanks, for n-indexing
) -> dict[str, Any]:
    icon, live_fields, daily_fields = _CARD_TEMPLATES.get(
        comp_type, ("mdi:lightning-bolt", [], [])
    )
    type_label = _TYPE_LABELS.get(comp_type, comp_type.title())
    base_title = comp_name if comp_name else type_label
    title = f"{base_title} {n}" if multi else base_title

    layer_multi = len(all_layer_ids) > 1

    entities: list[Any] = [
        _entity_id(comp_type, n, multi, f) for f in live_fields
    ]
    if daily_fields:
        entities.append({"type": "section", "label": "Today"})
        entities += [_entity_id(comp_type, n, multi, f) for f in daily_fields]

    # Add layer temperatures as a section
    if layer_comp_ids:
        entities.append({"type": "section", "label": "Tank Layers"})
        for layer_id in layer_comp_ids:
            layer_n = all_layer_ids.index(layer_id) + 1
            entities.append(_layer_entity_id(
                "tanklayer", layer_n, layer_multi, "temperature"
            ))

    return {
        "type": "entities",
        "title": title,
        "icon": icon,
        "entities": entities,
    }


def _build_card(
    comp_type: str,
    comp_name: str,
    n: int,
    multi: bool,
) -> dict[str, Any]:
    icon, live_fields, daily_fields = _CARD_TEMPLATES.get(
        comp_type, ("mdi:lightning-bolt", [], [])
    )
    type_label = _TYPE_LABELS.get(comp_type, comp_type.title())
    base_title = comp_name if comp_name else type_label
    title = f"{base_title} {n}" if multi else base_title

    entities: list[Any] = [
        _entity_id(comp_type, n, multi, f) for f in live_fields
    ]
    if daily_fields:
        entities.append({"type": "section", "label": "Today"})
        entities += [_entity_id(comp_type, n, multi, f) for f in daily_fields]

    return {
        "type": "entities",
        "title": title,
        "icon": icon,
        "entities": entities,
    }


def _build_dashboard_config(
    coordinator: JoulzenCoordinator,
) -> dict[str, Any]:
    # Group by lowercased type; sort IDs for deterministic n-indexing
    by_type: dict[str, list[tuple[str, str]]] = {}
    for comp_id, info in coordinator.components_info.items():
        comp_type = info.get("type", "").lower()
        by_type.setdefault(comp_type, []).append(
            (comp_id, info.get("name", ""))
        )
    for comps in by_type.values():
        comps.sort(key=lambda x: x[0])

    ordered = [t for t in _TYPE_ORDER if t in by_type]
    ordered += [
        t for t in by_type if t not in _TYPE_ORDER and t != "tanklayer"
    ]

    # All tank layer IDs in sorted order (for n-indexing)
    all_layer_ids = sorted(
        comp_id
        for comp_id, info in coordinator.components_info.items()
        if info.get("type", "").lower() == "tanklayer"
    )

    # tank_children keyed by original (non-lowercased) comp_id
    tank_children = coordinator.tank_children

    cards = []
    for comp_type in ordered:
        components = by_type[comp_type]
        multi = len(components) > 1
        for n, (comp_id, comp_name) in enumerate(components, start=1):
            if comp_type == "joulzentank":
                layer_ids = tank_children.get(comp_id, [])
                cards.append(_build_tank_card(
                    comp_type, comp_name, n, multi,
                    layer_ids, all_layer_ids,
                ))
            else:
                cards.append(_build_card(comp_type, comp_name, n, multi))

    return {
        "views": [
            {
                "title": "Overview",
                "path": "overview",
                "icon": "mdi:view-dashboard",
                "cards": cards,
            }
        ]
    }


async def async_create_dashboard(
    hass: HomeAssistant,
    coordinator: JoulzenCoordinator,
) -> None:
    """Create the Joulzen Lovelace dashboard if it doesn't already exist."""
    try:
        content_store = Store(hass, 1, _LOVELACE_CONTENT_KEY)
        if await content_store.async_load():
            _LOGGER.debug(
                "Joulzen dashboard already exists, skipping creation"
            )
            return

        config = _build_dashboard_config(coordinator)
        await content_store.async_save({"config": config})
        _LOGGER.info("Joulzen Lovelace dashboard content saved")

        dashboards_store = Store(hass, 1, _LOVELACE_DASHBOARDS_KEY)
        data = await dashboards_store.async_load() or {"items": []}
        if not any(
            d.get("url_path") == DASHBOARD_URL_PATH
            for d in data.get("items", [])
        ):
            data.setdefault("items", []).append({
                "id": DASHBOARD_URL_PATH,
                "url_path": DASHBOARD_URL_PATH,
                "title": "Joulzen",
                "icon": "mdi:lightning-bolt-circle",
                "show_in_sidebar": True,
                "require_admin": False,
                "mode": "storage",
            })
            await dashboards_store.async_save(data)
            _LOGGER.info("Joulzen dashboard registered in sidebar")

        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Joulzen Dashboard Ready",
                "message": (
                    "A Joulzen dashboard was created. "
                    "Reload your browser to see it in the sidebar."
                ),
                "notification_id": "joulzen_dashboard",
            },
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Failed to create Joulzen dashboard")
