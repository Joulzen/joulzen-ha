from dataclasses import dataclass
from .metric_groups_live import (
    ESupplierLive,
    EUserLive,
    EVendorLive,
    HUserLive,
    ECustomerLive,
    EProducerLive,
    EStorageLive,
    EConsumerLive,
    HVendorLive,
    HStorageLive,
    HConsumerLive,
    HTransformerLive,
    ThermometerLive,
    HStorageStatusLive,
    ActivationStatusLive,
)


# Base Component Live Interface
@dataclass
class SystemComponentLive:
    componentId: str = ""


# Component Implementations based on Image + src/lib/component.types.ts

@dataclass
class GridLive(SystemComponentLive, EVendorLive, ECustomerLive):
    pass


@dataclass
class EnergyCommunityLive(SystemComponentLive, EVendorLive):
    pass


@dataclass
class PVLive(SystemComponentLive, EProducerLive):
    pass


@dataclass
class BatteryLive(SystemComponentLive, EUserLive, ESupplierLive, EStorageLive):
    pass


@dataclass
class ApplianceLive(SystemComponentLive, EConsumerLive):
    pass


@dataclass
class HeaterLive(
    SystemComponentLive,
    HTransformerLive,
):
    pass


@dataclass
class DistrictHeatingLive(SystemComponentLive, HVendorLive):
    pass


@dataclass
class TankLayerLive(SystemComponentLive, ThermometerLive):
    pass


@dataclass
class JoulzenTankLive(
    SystemComponentLive,
    HUserLive,
    HStorageLive,
    HTransformerLive,
    HStorageStatusLive,
):
    pass


@dataclass
class ThermostatLive(
    SystemComponentLive, HConsumerLive, ThermometerLive
):
    pass


@dataclass
class EVLive(SystemComponentLive, EConsumerLive, EStorageLive):
    pass


@dataclass
class WeatherLive(SystemComponentLive, ThermometerLive):
    pass


@dataclass
class HeatingCircuitLive(SystemComponentLive, ActivationStatusLive):
    pass