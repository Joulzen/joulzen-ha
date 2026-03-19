from dataclasses import dataclass, fields
from typing import Optional, List, Any, Dict, Type
from statistics import mean

# Live metric group interfaces (electricity + heat + temperature)


@dataclass
class MetricGroupLive:
    dateTime: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetricGroupLive":
        known_fields = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered_data)

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__

    @classmethod
    def aggregate_values(
        cls, components: List[any]
    ) -> "MetricGroupLive":
        raise NotImplementedError("Subclasses must implement aggregate_values")


# Electricity - price index
@dataclass
class EPriceIndexLive(MetricGroupLive):
    price: float = 0.0  # [ct/kWh]
    isAvailable: bool = False

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "EPriceIndexLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        # price -> mean
        prices = [i.price for i in items if i.price is not None]

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            price=mean(prices) if prices else 0.0,
            isAvailable=any(i.isAvailable for i in items),
        )


# Electricity - flow/capabilities
@dataclass
class ESupplierLive(MetricGroupLive):
    eSupplying: float = 0.0  # [kW]

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "ESupplierLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            eSupplying=sum(i.eSupplying for i in items if i.eSupplying is not None),
        )


@dataclass
class EUserLive(MetricGroupLive):
    eUsing: float = 0.0  # [kW]

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "EUserLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            eUsing=sum(i.eUsing for i in items if i.eUsing is not None),
        )


@dataclass
class EVendorLive(ESupplierLive, EPriceIndexLive):
    spending: float = 0.0  # [ct]

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "EVendorLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        prices = [i.price for i in items if i.price is not None]

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            price=mean(prices) if prices else 0.0,
            isAvailable=any(i.isAvailable for i in items),
            eSupplying=sum(i.eSupplying for i in items if i.eSupplying is not None),
            spending=sum(i.spending for i in items if i.spending is not None),
        )


@dataclass
class ECustomerLive(EUserLive, EPriceIndexLive):
    earning: float = 0.0  # [ct]

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "ECustomerLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        prices = [i.price for i in items if i.price is not None]

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            price=mean(prices) if prices else 0.0,
            isAvailable=any(i.isAvailable for i in items),
            eUsing=sum(i.eUsing for i in items if i.eUsing is not None),
            earning=sum(i.earning for i in items if i.earning is not None),
        )


@dataclass
class EProducerLive(ESupplierLive):
    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "EProducerLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            eSupplying=sum(i.eSupplying for i in items if i.eSupplying is not None),
        )


@dataclass
class StorageLive(MetricGroupLive):
    soc: float = 0.0  # [0-1]

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "StorageLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        socs = [i.soc for i in items if i.soc is not None]

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            soc=mean(socs) if socs else 0.0,
        )


@dataclass
class EStorageLive(StorageLive):
    pass


@dataclass
class EConsumerLive(EUserLive):
    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "EConsumerLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            eUsing=sum(i.eUsing for i in items if i.eUsing is not None),
        )


# Heat - price index
@dataclass
class HPriceIndexLive(MetricGroupLive):
    price: float = 0.0  # [ct/kWh]
    isAvailable: bool = False

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "HPriceIndexLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        prices = [i.price for i in items if i.price is not None]

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            price=mean(prices) if prices else 0.0,
            isAvailable=any(i.isAvailable for i in items),
        )


# Heat - flow/capabilities
@dataclass
class HSupplierLive(MetricGroupLive):
    hSupplying: float = 0.0  # [kW]

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "HSupplierLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            hSupplying=sum(i.hSupplying for i in items if i.hSupplying is not None),
        )


@dataclass
class HUserLive(MetricGroupLive):
    hUsing: float = 0.0  # [kW]

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "HUserLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            hUsing=sum(i.hUsing for i in items if i.hUsing is not None),
        )


@dataclass
class HVendorLive(HSupplierLive, HPriceIndexLive):
    spending: float = 0.0  # [ct]

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "HVendorLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        prices = [i.price for i in items if i.price is not None]

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            price=mean(prices) if prices else 0.0,
            isAvailable=any(i.isAvailable for i in items),
            hSupplying=sum(i.hSupplying for i in items if i.hSupplying is not None),
            spending=sum(i.spending for i in items if i.spending is not None),
        )


@dataclass
class HCustomerLive(HUserLive):
    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "HCustomerLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            hUsing=sum(i.hUsing for i in items if i.hUsing is not None),
        )


@dataclass
class HProducerLive(HSupplierLive):
    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "HProducerLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            hSupplying=sum(i.hSupplying for i in items if i.hSupplying is not None),
        )


@dataclass
class HStorageLive(StorageLive):
    pass


@dataclass
class HConsumerLive(HUserLive):
    targetTemperature: float = 0.0  # [°C]

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "HConsumerLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        temps = [i.targetTemperature for i in items if i.targetTemperature is not None]

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            hUsing=sum(i.hUsing for i in items if i.hUsing is not None),
            targetTemperature=mean(temps) if temps else 0.0,
        )


@dataclass
class HTransformerLive(EConsumerLive, HProducerLive):
    cop: float = 0.0

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "HTransformerLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        cops = [i.cop for i in items if i.cop is not None]

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            eUsing=sum(i.eUsing for i in items if i.eUsing is not None),
            hSupplying=sum(i.hSupplying for i in items if i.hSupplying is not None),
            cop=mean(cops) if cops else 0.0,
        )


# Heat - storage status
@dataclass
class HStorageStatusLive(MetricGroupLive):
    isActivated: bool = False
    isConstrained: bool = False
    hasError: bool = False
    errorCode: Optional[str] = None
    constraints: Optional[List[str]] = None

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "HStorageStatusLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        error_codes = []
        all_constraints = []
        for i in items:
            if i.errorCode:
                error_codes.append(i.errorCode)
            if i.constraints:
                all_constraints.extend(i.constraints)

        unique_errors = sorted(list(set(error_codes)))
        unique_constraints = sorted(list(set(all_constraints)))

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            isActivated=any(i.isActivated for i in items),
            isConstrained=any(i.isConstrained for i in items),
            hasError=any(i.hasError for i in items),
            errorCode=", ".join(unique_errors) if unique_errors else None,
            constraints=unique_constraints if unique_constraints else None,
        )


# General status
@dataclass
class ActivationStatusLive(MetricGroupLive):
    isActive: bool = False

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "ActivationStatusLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            isActive=any(i.isActive for i in items),
        )


# Temperature
@dataclass
class ThermometerLive(MetricGroupLive):
    temperature: float = 0.0  # [°C]

    @classmethod
    def aggregate_values(cls, components: List[Any]) -> "ThermometerLive":
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls()

        temps = [i.temperature for i in items if i.temperature is not None]

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            temperature=mean(temps) if temps else 0.0,
        )


# Mapping from metric group id to corresponding live metric class
METRIC_GROUP_MAP_LIVE: Dict[str, Type[MetricGroupLive]] = {
    "e-price-index": EPriceIndexLive,
    "e-supply": ESupplierLive,
    "e-usage": EUserLive,
    "e-vendor": EVendorLive,
    "e-customer": ECustomerLive,
    "e-production": EProducerLive,
    "e-storage": EStorageLive,
    "e-consumption": EConsumerLive,
    "h-price-index": HPriceIndexLive,
    "h-supply": HSupplierLive,
    "h-usage": HUserLive,
    "h-vendor": HVendorLive,
    "h-customer": HCustomerLive,
    "h-production": HProducerLive,
    "h-storage": HStorageLive,
    "h-consumption": HConsumerLive,
    "h-transformer": HTransformerLive,
    "h-storage-status": HStorageStatusLive,
    "temperature": ThermometerLive,
    "activation-status": ActivationStatusLive,
}