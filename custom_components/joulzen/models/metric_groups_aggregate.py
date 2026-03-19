from dataclasses import dataclass, fields
from typing import List, Dict, Any, Type, Tuple
from datetime import datetime, timedelta
from statistics import mean
from .metric_groups_live import MetricGroupLive


def _calculate_weights(
    components: List[MetricGroupLive]
) -> Tuple[List[float], List[MetricGroupLive]]:
    if not components:
        return [], []

    # Filter and sort
    valid_items = []
    for c in components:
        if c.dateTime:
            valid_items.append(c)

    sorted_items = sorted(valid_items, key=lambda x: x.dateTime)

    dates = []
    final_items = []
    for item in sorted_items:
        try:
            dt_str = item.dateTime.replace("Z", "+00:00")
            if 'T' in dt_str:
                dt = datetime.fromisoformat(dt_str)
            else:
                # fallback for YYYY-MM-DD
                dt = datetime.strptime(dt_str, "%Y-%m-%d")
            dates.append(dt)
            final_items.append(item)
        except ValueError:
            pass

    if not dates:
        return [], []

    weights = []
    for i, current_dt in enumerate(dates):
        # Start
        if i == 0:
            start = current_dt.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        else:
            prev_dt = dates[i-1]
            start = prev_dt + (current_dt - prev_dt) / 2

        # End
        if i == len(dates) - 1:
            end = (current_dt + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        else:
            next_dt = dates[i+1]
            end = current_dt + (next_dt - current_dt) / 2

        duration = (end - start).total_seconds() / 3600.0
        weights.append(duration)

    return weights, final_items


def _calculate_stats(
    items: List[Any], weights: List[float], attr: str
) -> Tuple[float, float, float]:
    weighted_sum = 0.0
    total_weight = 0.0
    min_v = float('inf')
    max_v = float('-inf')
    count = 0

    for item, w in zip(items, weights):
        val = getattr(item, attr, None)
        if val is not None:
            weighted_sum += val * w
            total_weight += w
            if val < min_v:
                min_v = val
            if val > max_v:
                max_v = val
            count += 1

    if count == 0:
        return 0.0, 0.0, 0.0

    mean_v = (weighted_sum / total_weight) if total_weight > 0 else 0.0
    min_v = min_v if min_v != float('inf') else 0.0
    max_v = max_v if max_v != float('-inf') else 0.0

    return mean_v, min_v, max_v


# Marker base interface for all aggregate metric groups
@dataclass
class MetricGroupAggregate:
    dateTime: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MetricGroupAggregate":
        known_fields = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered_data)

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__

    @classmethod
    def aggregate_values(
        cls, components: List[any]
    ) -> "MetricGroupAggregate":
        raise NotImplementedError("Subclasses must implement aggregate_values")

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> "MetricGroupAggregate":
        """
        Aggregates a list of MetricGroupLive objects into a single
        MetricGroupAggregate object using the subclass's static
        aggregate_live_values method.

        The aggregation is done as a weighted sum/mean of the MetricGroupLive
        objects. The weights are the length of the time interval [midpoint
        between the selected object' dateTime and the previous object'
        dateTime; midpoint between the selected object' dateTime and the next
        object' dateTime].

        If the first object is selected, the interval starts at the start of
        the day of the first object's dateTime.
        If the last object is selected, the interval ends at the end of the
        day of the last object's dateTime.

        Args:
            cls_live: The MetricGroupLive subclass to aggregate from.
            components: A list of MetricGroupLive objects (of the
                specific subclass).

        Returns:
            The aggregated MetricGroupAggregate object of the aggregate
            subclass that corresponds to the MetricGroupLive subclass.
        """
        raise NotImplementedError(
            "Subclasses must implement aggregate_live_values"
        )


# Electricity - price index
@dataclass
class EPriceIndexAggregate(MetricGroupAggregate):
    totalAvailability: float = 0.0  # [0-1]
    minPrice: float = 0.0  # [ct/kWh]
    meanPrice: float = 0.0  # [ct/kWh]
    maxPrice: float = 0.0  # [ct/kWh]

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'EPriceIndexAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        timestamp = items[0].dateTime if items[0].dateTime else ""

        availabilities = [
            1.0 if getattr(i, 'isAvailable', False) else 0.0 for i in items
        ]

        min_prices = [i.minPrice for i in items if i.minPrice is not None]
        mean_prices = [i.meanPrice for i in items if i.meanPrice is not None]
        max_prices = [i.maxPrice for i in items if i.maxPrice is not None]

        return cls(
            dateTime=timestamp,
            totalAvailability=(
                mean(availabilities)
                if availabilities else 0.0
            ),
            minPrice=min(min_prices) if min_prices else 0.0,
            meanPrice=(
                mean(mean_prices) if mean_prices else 0.0
            ),
            maxPrice=max(max_prices) if max_prices else 0.0
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'EPriceIndexAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        # totalAvailability
        avail_weighted_sum = 0.0
        total_weight = sum(weights)
        for item, w in zip(items, weights):
            if getattr(item, 'isAvailable', False):
                avail_weighted_sum += 1.0 * w

        avg_avail = (
            (avail_weighted_sum / total_weight) if total_weight > 0 else 0.0
        )

        # Price stats
        mean_p, min_p, max_p = _calculate_stats(items, weights, 'price')

        return cls(
            dateTime=items[0].dateTime,
            totalAvailability=avg_avail,
            minPrice=min_p,
            meanPrice=mean_p,
            maxPrice=max_p
        )


# Electricity - flow/capabilities
@dataclass
class ESupplierAggregate(MetricGroupAggregate):
    eSupplied: float = 0.0  # [kWh]

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'ESupplierAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            eSupplied=sum(
                i.eSupplied for i in items if i.eSupplied is not None
            )
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'ESupplierAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        e_supplied = 0.0
        for item, w in zip(items, weights):
            val = getattr(item, 'eSupplying', None)
            if val is not None:
                e_supplied += val * w  # kW * h = kWh

        return cls(
            dateTime=items[0].dateTime,
            eSupplied=e_supplied
        )


@dataclass
class EUserAggregate(MetricGroupAggregate):
    eUsed: float = 0.0  # [kWh]

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'EUserAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            eUsed=sum(i.eUsed for i in items if i.eUsed is not None)
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'EUserAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        e_used = 0.0
        for item, w in zip(items, weights):
            val = getattr(item, 'eUsing', None)
            if val is not None:
                e_used += val * w

        return cls(
            dateTime=items[0].dateTime,
            eUsed=e_used
        )


@dataclass
class EVendorAggregate(ESupplierAggregate, EPriceIndexAggregate):
    cost: float = 0.0  # [€]

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'EVendorAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        timestamp = items[0].dateTime if items[0].dateTime else ""

        total_availabilities = [
            i.totalAvailability
            for i in items
            if i.totalAvailability is not None
        ]

        min_prices = [i.minPrice for i in items if i.minPrice is not None]
        mean_prices = [i.meanPrice for i in items if i.meanPrice is not None]
        max_prices = [i.maxPrice for i in items if i.maxPrice is not None]

        cost_sum = sum(i.cost for i in items if i.cost is not None)
        e_supplied_sum = sum(
            i.eSupplied for i in items if i.eSupplied is not None
        )

        return cls(
            dateTime=timestamp,
            totalAvailability=(
                mean(total_availabilities)
                if total_availabilities else 0.0
            ),
            minPrice=min(min_prices) if min_prices else 0.0,
            meanPrice=(
                mean(mean_prices) if mean_prices else 0.0
            ),
            maxPrice=max(max_prices) if max_prices else 0.0,
            eSupplied=e_supplied_sum,
            cost=cost_sum
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'EVendorAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        # Availability
        total_weight = sum(weights)
        avail_sum = sum(
            1.0 * w
            for i, w in zip(items, weights)
            if getattr(i, 'isAvailable', False)
        )
        avg_avail = (avail_sum / total_weight) if total_weight > 0 else 0.0

        # Price
        mean_p, min_p, max_p = _calculate_stats(items, weights, 'price')

        # Supplied
        e_supplied = 0.0
        cost_sum = 0.0

        for item, w in zip(items, weights):
            # eSupplying [kW]
            sup = getattr(item, 'eSupplying', None)
            if sup is not None:
                e_supplied += sup * w

            # spending [ct/h] (assumed rate) -> cost [€]
            # spending * w [h] = ct. ct / 100 = €
            spending = getattr(item, 'spending', None)
            if spending is not None:
                cost_sum += (spending * w) / 100.0

        return cls(
            dateTime=items[0].dateTime,
            totalAvailability=avg_avail,
            minPrice=min_p,
            meanPrice=mean_p,
            maxPrice=max_p,
            eSupplied=e_supplied,
            cost=cost_sum
        )


@dataclass
class ECustomerAggregate(EUserAggregate, EPriceIndexAggregate):
    totalEarned: float = 0.0  # [€]

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'ECustomerAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        timestamp = items[0].dateTime if items[0].dateTime else ""

        total_availabilities = [
            i.totalAvailability
            for i in items
            if i.totalAvailability is not None
        ]
        min_prices = [i.minPrice for i in items if i.minPrice is not None]
        mean_prices = [i.meanPrice for i in items if i.meanPrice is not None]
        max_prices = [i.maxPrice for i in items if i.maxPrice is not None]

        earned_sum = sum(
            i.totalEarned for i in items if i.totalEarned is not None
        )
        e_used_sum = sum(i.eUsed for i in items if i.eUsed is not None)

        return cls(
            dateTime=timestamp,
            totalAvailability=(
                mean(total_availabilities)
                if total_availabilities else 0.0
            ),
            minPrice=min(min_prices) if min_prices else 0.0,
            meanPrice=(
                mean(mean_prices) if mean_prices else 0.0
            ),
            maxPrice=max(max_prices) if max_prices else 0.0,
            eUsed=e_used_sum,
            totalEarned=earned_sum
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'ECustomerAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        # Availability
        total_weight = sum(weights)
        avail_sum = sum(
            1.0 * w
            for i, w in zip(items, weights)
            if getattr(i, 'isAvailable', False)
        )
        avg_avail = (avail_sum / total_weight) if total_weight > 0 else 0.0

        # Price
        mean_p, min_p, max_p = _calculate_stats(items, weights, 'price')

        # Used & Earned
        e_used = 0.0
        earned_sum = 0.0

        for item, w in zip(items, weights):
            used = getattr(item, 'eUsing', None)
            if used is not None:
                e_used += used * w

            # earning [ct/h] -> [€]
            earn = getattr(item, 'earning', None)
            if earn is not None:
                earned_sum += (earn * w) / 100.0

        return cls(
            dateTime=items[0].dateTime,
            totalAvailability=avg_avail,
            minPrice=min_p,
            meanPrice=mean_p,
            maxPrice=max_p,
            eUsed=e_used,
            totalEarned=earned_sum
        )


@dataclass
class EProducerAggregate(ESupplierAggregate):

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'EProducerAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            eSupplied=sum(
                i.eSupplied for i in items if i.eSupplied is not None
            )
        )


@dataclass
class StorageAggregate(MetricGroupAggregate):
    minSoc: float = 0.0
    meanSoc: float = 0.0
    maxSoc: float = 0.0

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'StorageAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        timestamp = items[0].dateTime if items[0].dateTime else ""

        min_socs = [i.minSoc for i in items if i.minSoc is not None]
        mean_socs = [i.meanSoc for i in items if i.meanSoc is not None]
        max_socs = [i.maxSoc for i in items if i.maxSoc is not None]

        return cls(
            dateTime=timestamp,
            minSoc=min(min_socs) if min_socs else 0.0,
            meanSoc=mean(mean_socs) if mean_socs else 0.0,
            maxSoc=max(max_socs) if max_socs else 0.0
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'StorageAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        mean_s, min_s, max_s = _calculate_stats(items, weights, 'soc')

        return cls(
            dateTime=items[0].dateTime,
            minSoc=min_s,
            meanSoc=mean_s,
            maxSoc=max_s
        )


@dataclass
class EStorageAggregate(EUserAggregate, StorageAggregate):

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'EStorageAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        timestamp = items[0].dateTime if items[0].dateTime else ""

        # EUserAggregate
        e_used_sum = sum(i.eUsed for i in items if i.eUsed is not None)

        # StorageAggregate
        min_socs = [i.minSoc for i in items if i.minSoc is not None]
        mean_socs = [i.meanSoc for i in items if i.meanSoc is not None]
        max_socs = [i.maxSoc for i in items if i.maxSoc is not None]

        return cls(
            dateTime=timestamp,
            eUsed=e_used_sum,
            minSoc=min(min_socs) if min_socs else 0.0,
            meanSoc=mean(mean_socs) if mean_socs else 0.0,
            maxSoc=max(max_socs) if max_socs else 0.0
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'EStorageAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        # EUserAggregate
        e_used = 0.0
        for item, w in zip(items, weights):
            val = getattr(item, 'eUsing', None)
            if val is not None:
                e_used += val * w

        # StorageAggregate
        mean_s, min_s, max_s = _calculate_stats(items, weights, 'soc')

        return cls(
            dateTime=items[0].dateTime,
            eUsed=e_used,
            minSoc=min_s,
            meanSoc=mean_s,
            maxSoc=max_s
        )


@dataclass
class EConsumerAggregate(EUserAggregate):

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'EConsumerAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            eUsed=sum(i.eUsed for i in items if i.eUsed is not None)
        )


# Heat - price index
@dataclass
class HPriceIndexAggregate(MetricGroupAggregate):
    totalAvailability: float = 0.0  # [0-1]
    minPrice: float = 0.0  # [ct/kWh]
    meanPrice: float = 0.0  # [ct/kWh]
    maxPrice: float = 0.0  # [ct/kWh]

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'HPriceIndexAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        timestamp = items[0].dateTime if items[0].dateTime else ""

        total_availabilities = [
            i.totalAvailability
            for i in items
            if i.totalAvailability is not None
        ]
        min_prices = [i.minPrice for i in items if i.minPrice is not None]
        mean_prices = [i.meanPrice for i in items if i.meanPrice is not None]
        max_prices = [i.maxPrice for i in items if i.maxPrice is not None]

        return cls(
            dateTime=timestamp,
            totalAvailability=(
                mean(total_availabilities)
                if total_availabilities else 0.0
            ),
            minPrice=min(min_prices) if min_prices else 0.0,
            meanPrice=(
                mean(mean_prices) if mean_prices else 0.0
            ),
            maxPrice=max(max_prices) if max_prices else 0.0
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'HPriceIndexAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        total_weight = sum(weights)
        avail_sum = sum(
            1.0 * w
            for i, w in zip(items, weights)
            if getattr(i, 'isAvailable', False)
        )
        avg_avail = (avail_sum / total_weight) if total_weight > 0 else 0.0

        mean_p, min_p, max_p = _calculate_stats(items, weights, 'price')

        return cls(
            dateTime=items[0].dateTime,
            totalAvailability=avg_avail,
            minPrice=min_p,
            meanPrice=mean_p,
            maxPrice=max_p
        )


# Heat - flow/capabilities
@dataclass
class HSupplierAggregate(MetricGroupAggregate):
    hSupplied: float = 0.0  # [kWh]

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'HSupplierAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            hSupplied=sum(
                i.hSupplied for i in items if i.hSupplied is not None
            )
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'HSupplierAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        h_supplied = 0.0
        for item, w in zip(items, weights):
            val = getattr(item, 'hSupplying', None)
            if val is not None:
                h_supplied += val * w

        return cls(
            dateTime=items[0].dateTime,
            hSupplied=h_supplied
        )


@dataclass
class HUserAggregate(MetricGroupAggregate):
    hUsed: float = 0.0  # [kWh]

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'HUserAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            hUsed=sum(i.hUsed for i in items if i.hUsed is not None)
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'HUserAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        h_used = 0.0
        for item, w in zip(items, weights):
            val = getattr(item, 'hUsing', None)
            if val is not None:
                h_used += val * w

        return cls(
            dateTime=items[0].dateTime,
            hUsed=h_used
        )


@dataclass
class HVendorAggregate(HSupplierAggregate, HPriceIndexAggregate):
    cost: float = 0.0  # [€]

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'HVendorAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        timestamp = items[0].dateTime if items[0].dateTime else ""

        total_availabilities = [
            i.totalAvailability
            for i in items
            if i.totalAvailability is not None
        ]
        min_prices = [i.minPrice for i in items if i.minPrice is not None]
        mean_prices = [i.meanPrice for i in items if i.meanPrice is not None]
        max_prices = [i.maxPrice for i in items if i.maxPrice is not None]

        cost_sum = sum(i.cost for i in items if i.cost is not None)
        h_supplied_sum = sum(
            i.hSupplied for i in items if i.hSupplied is not None
        )

        return cls(
            dateTime=timestamp,
            totalAvailability=(
                mean(total_availabilities)
                if total_availabilities else 0.0
            ),
            minPrice=min(min_prices) if min_prices else 0.0,
            meanPrice=(
                mean(mean_prices) if mean_prices else 0.0
            ),
            maxPrice=max(max_prices) if max_prices else 0.0,
            hSupplied=h_supplied_sum,
            cost=cost_sum
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'HVendorAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        # Availability
        total_weight = sum(weights)
        avail_sum = sum(
            1.0 * w
            for i, w in zip(items, weights)
            if getattr(i, 'isAvailable', False)
        )
        avg_avail = (avail_sum / total_weight) if total_weight > 0 else 0.0

        # Price
        mean_p, min_p, max_p = _calculate_stats(items, weights, 'price')

        # Supplied & Cost
        h_supplied = 0.0
        cost_sum = 0.0

        for item, w in zip(items, weights):
            sup = getattr(item, 'hSupplying', None)
            if sup is not None:
                h_supplied += sup * w

            spending = getattr(item, 'spending', None)
            if spending is not None:
                cost_sum += (spending * w) / 100.0

        return cls(
            dateTime=items[0].dateTime,
            totalAvailability=avg_avail,
            minPrice=min_p,
            meanPrice=mean_p,
            maxPrice=max_p,
            hSupplied=h_supplied,
            cost=cost_sum
        )


@dataclass
class HCustomerAggregate(HUserAggregate):

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'HCustomerAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            hUsed=sum(i.hUsed for i in items if i.hUsed is not None)
        )


@dataclass
class HProducerAggregate(HSupplierAggregate):

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'HProducerAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        return cls(
            dateTime=items[0].dateTime if items[0].dateTime else "",
            hSupplied=sum(
                i.hSupplied for i in items if i.hSupplied is not None
            )
        )


@dataclass
class HStorageAggregate(EUserAggregate, HSupplierAggregate, StorageAggregate):

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'HStorageAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        timestamp = items[0].dateTime if items[0].dateTime else ""

        # EUserAggregate
        e_used_sum = sum(i.eUsed for i in items if i.eUsed is not None)
        # HSupplierAggregate
        h_supplied_sum = sum(
            i.hSupplied for i in items if i.hSupplied is not None
        )
        # StorageAggregate
        min_socs = [i.minSoc for i in items if i.minSoc is not None]
        mean_socs = [i.meanSoc for i in items if i.meanSoc is not None]
        max_socs = [i.maxSoc for i in items if i.maxSoc is not None]

        return cls(
            dateTime=timestamp,
            eUsed=e_used_sum,
            hSupplied=h_supplied_sum,
            minSoc=min(min_socs) if min_socs else 0.0,
            meanSoc=mean(mean_socs) if mean_socs else 0.0,
            maxSoc=max(max_socs) if max_socs else 0.0
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'HStorageAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        e_used = 0.0
        h_supplied = 0.0

        for item, w in zip(items, weights):
            ev = getattr(item, 'eUsing', None)
            if ev is not None:
                e_used += ev * w

            hv = getattr(item, 'hSupplying', None)
            if hv is not None:
                h_supplied += hv * w

        mean_s, min_s, max_s = _calculate_stats(items, weights, 'soc')

        return cls(
            dateTime=items[0].dateTime,
            eUsed=e_used,
            hSupplied=h_supplied,
            minSoc=min_s,
            meanSoc=mean_s,
            maxSoc=max_s
        )


@dataclass
class HConsumerAggregate(HUserAggregate):
    meanTargetTemperature: float = 0.0  # [°C]
    minTargetTemperature: float = 0.0  # [°C]
    maxTargetTemperature: float = 0.0  # [°C]

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'HConsumerAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        timestamp = items[0].dateTime if items[0].dateTime else ""

        mean_temps = [
            i.meanTargetTemperature
            for i in items
            if i.meanTargetTemperature is not None
        ]
        min_temps = [
            i.minTargetTemperature
            for i in items
            if i.minTargetTemperature is not None
        ]
        max_temps = [
            i.maxTargetTemperature
            for i in items
            if i.maxTargetTemperature is not None
        ]

        return cls(
            dateTime=timestamp,
            hUsed=sum(i.hUsed for i in items if i.hUsed is not None),
            meanTargetTemperature=(
                mean(mean_temps) if mean_temps else 0.0
            ),
            minTargetTemperature=min(min_temps) if min_temps else 0.0,
            maxTargetTemperature=max(max_temps) if max_temps else 0.0
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'HConsumerAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        h_used = 0.0
        for item, w in zip(items, weights):
            val = getattr(item, 'hUsing', None)
            if val is not None:
                h_used += val * w

        mean_t, min_t, max_t = _calculate_stats(
            items, weights, 'targetTemperature'
        )

        return cls(
            dateTime=items[0].dateTime,
            hUsed=h_used,
            meanTargetTemperature=mean_t,
            minTargetTemperature=min_t,
            maxTargetTemperature=max_t
        )


@dataclass
class HTransformerAggregate(EConsumerAggregate, HProducerAggregate):
    meanCop: float = 0.0
    maxCop: float = 0.0
    minCop: float = 0.0

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'HTransformerAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        timestamp = items[0].dateTime if items[0].dateTime else ""

        mean_cops = [i.meanCop for i in items if i.meanCop is not None]
        max_cops = [i.maxCop for i in items if i.maxCop is not None]
        min_cops = [i.minCop for i in items if i.minCop is not None]

        return cls(
            dateTime=timestamp,
            meanCop=mean(mean_cops) if mean_cops else 0.0,
            maxCop=max(max_cops) if max_cops else 0.0,
            minCop=min(min_cops) if min_cops else 0.0,
            eUsed=sum(i.eUsed for i in items if i.eUsed is not None),
            hSupplied=sum(
                i.hSupplied for i in items if i.hSupplied is not None
            ),
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'HTransformerAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        e_used = 0.0
        h_supplied = 0.0

        for item, w in zip(items, weights):
            e = getattr(item, 'eUsing', None)
            if e is not None:
                e_used += e * w

            h = getattr(item, 'hSupplying', None)
            if h is not None:
                h_supplied += h * w

        mean_c, min_c, max_c = _calculate_stats(items, weights, 'cop')

        return cls(
            dateTime=items[0].dateTime,
            meanCop=mean_c,
            minCop=min_c,
            maxCop=max_c,
            eUsed=e_used,
            hSupplied=h_supplied
        )


# Heat - storage status (aggregate)
@dataclass
class HStorageStatusAggregate(MetricGroupAggregate):
    activeTime: float = 0.0  # [0-1]
    constrainedTime: float = 0.0  # [0-1]
    errorTime: float = 0.0  # [0-1]

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'HStorageStatusAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        timestamp = items[0].dateTime if items[0].dateTime else ""

        active_times = [
            i.activeTime for i in items if i.activeTime is not None
        ]
        constrained_times = [
            i.constrainedTime
            for i in items
            if i.constrainedTime is not None
        ]
        error_times = [
            i.errorTime for i in items if i.errorTime is not None
        ]

        return cls(
            dateTime=timestamp,
            activeTime=(
                mean(active_times) if active_times else 0.0
            ),
            constrainedTime=(
                mean(constrained_times)
                if constrained_times else 0.0
            ),
            errorTime=(
                mean(error_times) if error_times else 0.0
            )
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'HStorageStatusAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        total_weight = sum(weights)
        if total_weight == 0:
            return cls(dateTime=items[0].dateTime)

        active_sum = 0.0
        constrained_sum = 0.0
        error_sum = 0.0

        for item, w in zip(items, weights):
            if getattr(item, 'isActivated', False):
                active_sum += w
            if getattr(item, 'isConstrained', False):
                constrained_sum += w
            if getattr(item, 'hasError', False):
                error_sum += w

        return cls(
            dateTime=items[0].dateTime,
            activeTime=active_sum / total_weight,
            constrainedTime=constrained_sum / total_weight,
            errorTime=error_sum / total_weight
        )


# General status
@dataclass
class ActivationStatusAggregate(MetricGroupAggregate):
    activeTime: float = 0.0  # [0-1]

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'ActivationStatusAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        timestamp = items[0].dateTime if items[0].dateTime else ""

        active_times = [
            i.activeTime for i in items if i.activeTime is not None
        ]

        return cls(
            dateTime=timestamp,
            activeTime=(
                mean(active_times) if active_times else 0.0
            )
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'ActivationStatusAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        total_weight = sum(weights)
        if total_weight == 0:
            return cls(dateTime=items[0].dateTime)

        active_sum = 0.0

        for item, w in zip(items, weights):
            if getattr(item, 'isActive', False):
                active_sum += w

        return cls(
            dateTime=items[0].dateTime,
            activeTime=active_sum / total_weight
        )


# Temperature
@dataclass
class ThermometerAggregate(MetricGroupAggregate):
    meanTemperature: float = 0.0  # [°C]
    minTemperature: float = 0.0  # [°C]
    maxTemperature: float = 0.0  # [°C]

    @classmethod
    def aggregate_values(
        cls, components: List[Any]
    ) -> 'ThermometerAggregate':
        items = [c for c in components if isinstance(c, cls)]
        if not items:
            return cls(dateTime="")

        timestamp = items[0].dateTime if items[0].dateTime else ""

        mean_temps = [
            i.meanTemperature
            for i in items
            if i.meanTemperature is not None
        ]
        min_temps = [
            i.minTemperature
            for i in items
            if i.minTemperature is not None
        ]
        max_temps = [
            i.maxTemperature
            for i in items
            if i.maxTemperature is not None
        ]

        return cls(
            dateTime=timestamp,
            meanTemperature=(
                mean(mean_temps) if mean_temps else 0.0
            ),
            minTemperature=min(min_temps) if min_temps else 0.0,
            maxTemperature=max(max_temps) if max_temps else 0.0
        )

    @classmethod
    def aggregate_live_values(
        cls, cls_live: Type[MetricGroupLive], components: List[MetricGroupLive]
    ) -> 'ThermometerAggregate':
        weights, items = _calculate_weights(components)
        if not items:
            return cls(dateTime="")

        mean_t, min_t, max_t = _calculate_stats(items, weights, 'temperature')

        return cls(
            dateTime=items[0].dateTime,
            meanTemperature=mean_t,
            minTemperature=min_t,
            maxTemperature=max_t
        )


# Mapping from metric group id to corresponding aggregate metric class
METRIC_GROUP_MAP_AGGREGATE: Dict[str, Type[MetricGroupAggregate]] = {
    "e-price-index": EPriceIndexAggregate,
    "e-supply": ESupplierAggregate,
    "e-usage": EUserAggregate,
    "e-vendor": EVendorAggregate,
    "e-customer": ECustomerAggregate,
    "e-production": EProducerAggregate,
    "e-storage": EStorageAggregate,
    "e-consumption": EConsumerAggregate,
    "h-price-index": HPriceIndexAggregate,
    "h-supply": HSupplierAggregate,
    "h-usage": HUserAggregate,
    "h-vendor": HVendorAggregate,
    "h-customer": HCustomerAggregate,
    "h-production": HProducerAggregate,
    "h-storage": HStorageAggregate,
    "h-consumption": HConsumerAggregate,
    "h-transformer": HTransformerAggregate,
    "h-storage-status": HStorageStatusAggregate,
    "temperature": ThermometerAggregate,
    "activation-status": ActivationStatusAggregate,
}