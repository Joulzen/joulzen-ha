from dataclasses import dataclass
from .metric_groups_aggregate import (
    ESupplierAggregate,
    EVendorAggregate,
    ECustomerAggregate,
    EProducerAggregate,
    EStorageAggregate,
    EConsumerAggregate,
    HVendorAggregate,
    HStorageAggregate,
    HUserAggregate,
    HConsumerAggregate,
    HTransformerAggregate,
    ThermometerAggregate,
    HStorageStatusAggregate,
    ActivationStatusAggregate,
)


# Base Component Aggregate Interface
@dataclass
class SystemComponentAggregate:
    componentId: str = ""


# Component Implementations


@dataclass
class GridAggregate(
    SystemComponentAggregate,
    EVendorAggregate,
    ECustomerAggregate,
):
    pass


@dataclass
class EnergyCommunityAggregate(
    SystemComponentAggregate, EVendorAggregate
):
    pass


@dataclass
class PVAggregate(
    SystemComponentAggregate,
    EProducerAggregate,
):
    pass


@dataclass
class BatteryAggregate(
    SystemComponentAggregate,
    ESupplierAggregate,
    EStorageAggregate,
):
    pass


@dataclass
class ApplianceAggregate(
    SystemComponentAggregate,
    EConsumerAggregate,
):
    pass


@dataclass
class HeaterAggregate(
    SystemComponentAggregate,
    HTransformerAggregate,
):
    pass


@dataclass
class DistrictHeatingAggregate(
    SystemComponentAggregate, HVendorAggregate
):
    pass


@dataclass
class TankLayerAggregate(SystemComponentAggregate, ThermometerAggregate):
    pass


@dataclass
class JoulzenTankAggregate(
    SystemComponentAggregate,
    HUserAggregate,
    HStorageAggregate,
    HTransformerAggregate,
    HStorageStatusAggregate,
):
    pass


@dataclass
class ThermostatAggregate(
    SystemComponentAggregate,
    HConsumerAggregate,
    ThermometerAggregate,
):
    pass


@dataclass
class EVAggregate(
    SystemComponentAggregate,
    EConsumerAggregate,
    EStorageAggregate,
):
    pass


@dataclass
class WeatherAggregate(SystemComponentAggregate, ThermometerAggregate):
    pass


@dataclass
class HeatingCircuitAggregate(
    SystemComponentAggregate, ActivationStatusAggregate
):
    pass