"""Registry mapping household component type strings to model classes."""
from __future__ import annotations

from dataclasses import fields as dc_fields
from typing import NamedTuple, Type

from .models.component_types_live import (
    GridLive,
    EnergyCommunityLive,
    PVLive,
    BatteryLive,
    ApplianceLive,
    HeaterLive,
    DistrictHeatingLive,
    TankLayerLive,
    JoulzenTankLive,
    ThermostatLive,
    EVLive,
    WeatherLive,
    HeatingCircuitLive,
)
from .models.component_types_aggregate import (
    GridAggregate,
    EnergyCommunityAggregate,
    PVAggregate,
    BatteryAggregate,
    ApplianceAggregate,
    HeaterAggregate,
    DistrictHeatingAggregate,
    TankLayerAggregate,
    JoulzenTankAggregate,
    ThermostatAggregate,
    EVAggregate,
    WeatherAggregate,
    HeatingCircuitAggregate,
)


class ComponentTypeInfo(NamedTuple):
    live_cls: Type
    agg_cls: Type
    title: str
    description: str


COMPONENT_TYPE_REGISTRY: dict[str, ComponentTypeInfo] = {
    "grid": ComponentTypeInfo(
        GridLive, GridAggregate,
        "Grid",
        "Map entities for grid connection fields.",
    ),
    "energyCommunity": ComponentTypeInfo(
        EnergyCommunityLive, EnergyCommunityAggregate,
        "Energy Community",
        "Map entities for energy community fields.",
    ),
    "pv": ComponentTypeInfo(
        PVLive, PVAggregate,
        "Solar PV",
        "Map entities for solar PV fields.",
    ),
    "battery": ComponentTypeInfo(
        BatteryLive, BatteryAggregate,
        "Battery",
        "Map entities for battery storage fields.",
    ),
    "appliance": ComponentTypeInfo(
        ApplianceLive, ApplianceAggregate,
        "Appliance",
        "Map entities for appliance consumption fields.",
    ),
    "heater": ComponentTypeInfo(
        HeaterLive, HeaterAggregate,
        "Heat Pump / Heater",
        "Map entities for heat pump or heater fields.",
    ),
    "districtHeating": ComponentTypeInfo(
        DistrictHeatingLive, DistrictHeatingAggregate,
        "District Heating",
        "Map entities for district heating fields.",
    ),
    "joulzenTank": ComponentTypeInfo(
        JoulzenTankLive, JoulzenTankAggregate,
        "Joulzen Tank",
        "Map entities for thermal storage tank fields.",
    ),
    "tankLayer": ComponentTypeInfo(
        TankLayerLive, TankLayerAggregate,
        "Tank Layer",
        "Map entities for individual tank layer temperature fields.",
    ),
    "thermostat": ComponentTypeInfo(
        ThermostatLive, ThermostatAggregate,
        "Thermostat",
        "Map entities for thermostat fields.",
    ),
    "ev": ComponentTypeInfo(
        EVLive, EVAggregate,
        "Electric Vehicle",
        "Map entities for EV charging fields.",
    ),
    "weather": ComponentTypeInfo(
        WeatherLive, WeatherAggregate,
        "Weather Station",
        "Map entities for weather observation fields.",
    ),
    "heatingCircuit": ComponentTypeInfo(
        HeatingCircuitLive, HeatingCircuitAggregate,
        "Heating Circuit",
        "Map entities for heating circuit fields.",
    ),
}

# Canonical display order for type pages
COMPONENT_TYPE_ORDER: list[str] = [
    "grid",
    "energyCommunity",
    "pv",
    "battery",
    "appliance",
    "heater",
    "districtHeating",
    "joulzenTank",
    "tankLayer",
    "thermostat",
    "ev",
    "weather",
    "heatingCircuit",
]

_EXCLUDED_FIELDS = {"componentId", "dateTime"}


def get_component_fields(type_str: str) -> list[str]:
    """Return all field names for a type (live + aggregate, no duplicates)."""
    info = COMPONENT_TYPE_REGISTRY.get(type_str)
    if info is None:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for cls in (info.live_cls, info.agg_cls):
        for f in dc_fields(cls):
            if f.name not in _EXCLUDED_FIELDS and f.name not in seen:
                seen.add(f.name)
                result.append(f.name)
    return result


def get_live_field_names(type_str: str) -> list[str]:
    """Return live-only data field names (excl. componentId, dateTime)."""
    info = COMPONENT_TYPE_REGISTRY.get(type_str)
    if info is None:
        return []
    return [
        f.name for f in dc_fields(info.live_cls)
        if f.name not in _EXCLUDED_FIELDS
    ]


def get_agg_field_names(type_str: str) -> list[str]:
    """Return aggregate-only data field names (excl. componentId, dateTime)."""
    info = COMPONENT_TYPE_REGISTRY.get(type_str)
    if info is None:
        return []
    return [
        f.name for f in dc_fields(info.agg_cls)
        if f.name not in _EXCLUDED_FIELDS
    ]


def build_component_sections(
    type_str: str, components: list[dict]
) -> dict[str, tuple[list[str], list[str]]]:
    """Return {comp_id: (live_keys, agg_keys)} for each component."""
    live_names = get_live_field_names(type_str)
    agg_names = get_agg_field_names(type_str)
    result: dict[str, tuple[list[str], list[str]]] = {}
    for comp in components:
        cid = comp.get("componentId", "")
        result[cid] = (
            [f"{cid}_{n}" for n in live_names],
            [f"{cid}_{n}" for n in agg_names],
        )
    return result


def extract_components_by_type(
    household: dict,
) -> dict[str, list[dict]]:
    """Group all components from a household JSON by their type string."""
    by_type: dict[str, list[dict]] = {}
    for arr in household.get("componentsByType", {}).values():
        if not isinstance(arr, list):
            continue
        for comp in arr:
            t = comp.get("type")
            if t:
                by_type.setdefault(t, []).append(comp)
            # Flatten nested tankLayers
            for layer in comp.get("tankLayers", []):
                lt = layer.get("type")
                if lt:
                    by_type.setdefault(lt, []).append(layer)
    return by_type


def build_field_keys(
    type_str: str, components: list[dict]
) -> list[str]:
    """Return prefixed field keys: {componentId}_{fieldName}."""
    field_names = get_component_fields(type_str)
    keys: list[str] = []
    for comp in components:
        cid = comp.get("componentId", "")
        for field in field_names:
            keys.append(f"{cid}_{field}")
    return keys
