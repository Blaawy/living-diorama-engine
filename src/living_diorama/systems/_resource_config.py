"""Shared numeric and configuration validation for the resource systems.

Private to the systems package. It exists because ProductionSystem,
ConsumptionSystem, and ResourceFlowSystem all take the same shape of
normalized allocation mapping and all need the same float discipline; three
copies of that validation would drift apart. It is deliberately a handful of
functions rather than a framework.
"""

import math
from collections.abc import Iterable, Mapping
from types import MappingProxyType

from living_diorama.entities import ResourcePool, ResourceType

FLOAT_TOLERANCE = 1e-9
"""The single numeric tolerance used across the resource systems.

Applied to four things and nothing else:

* deciding whether an allocation mapping sums to 1.0,
* clamping a tiny negative float produced by subtraction to exactly 0.0,
* deciding whether a staged transfer is large enough to be worth applying,
* confirming that resource totals are conserved across a flow update.

It is small enough that it cannot mask a meaningful quantity: a stock error of
1e-9 food is not a simulation outcome, while anything a system could plausibly
get wrong is orders of magnitude larger and still raises.
"""

PROJECTION_TOLERANCE = FLOAT_TOLERANCE / 100
"""How close the fair-allocation projection must get before it stops.

Deliberately stricter than :data:`FLOAT_TOLERANCE`, because the two answer
different questions. ``FLOAT_TOLERANCE`` asks whether a *quantity* matters: a
billionth of a unit of food is not a simulation outcome. This asks whether an
iterative search has *converged*, and the answer it settles on is only as
precise as the step it was willing to stop at.

The distinction is forced, not stylistic. The projection halts once no further
improvement exceeds its threshold, which leaves each edge within a small
multiple of that threshold of the true optimum -- measured at roughly four
times it. Two runs starting from different maximum flows therefore land within
about eight times the threshold of each other. Stopping at
``FLOAT_TOLERANCE`` would leave renamed runs differing by several times
``FLOAT_TOLERANCE``, so a single tolerance can never both stop the search and
certify its answer: the certificate has to be finer than the stopping rule.
A hundredfold gap puts the observed residue about twenty times inside the
quantity tolerance, which is margin enough to be a guarantee rather than a
coincidence.

This changes no domain decision. Whether a transfer is worth making, whether
stock has gone negative, whether resources balance, and whether an event is
published are all still judged at :data:`FLOAT_TOLERANCE`.
"""

RESOURCE_ORDER: tuple[ResourceType, ...] = (
    ResourceType.FOOD,
    ResourceType.MATERIALS,
    ResourceType.ENERGY,
)
"""The explicit iteration order for resources.

Every loop over resource kinds uses this tuple rather than iterating a dict,
a set, or the enum itself, so that event order and floating-point accumulation
order are properties of a written-down decision rather than of how a mapping
happened to be built.
"""


def validate_allocation(
    allocation: Mapping[ResourceType, float], label: str
) -> Mapping[ResourceType, float]:
    """Validate a normalized allocation mapping and return a read-only copy.

    The returned mapping is a fresh, read-only view built in
    :data:`RESOURCE_ORDER`, so a caller mutating the mapping they passed in
    cannot reach the system's configuration afterwards.

    Type errors and value errors are kept distinct: a key or weight of the
    wrong kind raises ``TypeError``, while a mapping that is the right shape
    but does not describe a valid allocation raises ``ValueError``. Note that
    an "extra" key is necessarily not a ``ResourceType`` -- there are exactly
    three members and all three are required -- so extras surface as
    ``TypeError``.

    Args:
        allocation: Weight per resource kind. Must name every ResourceType.
        label: Name of the configuration field, used in error messages.

    Returns:
        A read-only mapping in RESOURCE_ORDER.

    Raises:
        TypeError: If the argument is not a mapping, if any key is not a
            ResourceType, or if any weight is not a real number (bool included,
            since it subclasses int).
        ValueError: If a resource kind is missing, if any weight is negative or
            not finite, or if the weights do not sum to 1.0 within
            :data:`FLOAT_TOLERANCE`.
    """
    if not isinstance(allocation, Mapping):
        raise TypeError(f"{label} must be a mapping, got {type(allocation).__name__}")

    for key in allocation:
        if not isinstance(key, ResourceType):
            raise TypeError(
                f"{label} keys must be ResourceType members, got {type(key).__name__} ({key!r})"
            )

    missing = [resource.value for resource in RESOURCE_ORDER if resource not in allocation]
    if missing:
        raise ValueError(f"{label} is missing weights for: {', '.join(missing)}")

    weights: dict[ResourceType, float] = {}
    for resource in RESOURCE_ORDER:
        weight = allocation[resource]
        if type(weight) is bool or not isinstance(weight, int | float):
            raise TypeError(
                f"{label}[{resource.value}] must be a real number, got {type(weight).__name__}"
            )
        weight = float(weight)
        if not math.isfinite(weight):
            raise ValueError(f"{label}[{resource.value}] must be finite, got {weight!r}")
        if weight < 0.0:
            raise ValueError(f"{label}[{resource.value}] must be >= 0, got {weight}")
        weights[resource] = weight

    total = math.fsum(weights[resource] for resource in RESOURCE_ORDER)
    if abs(total - 1.0) > FLOAT_TOLERANCE:
        raise ValueError(f"{label} weights must sum to 1.0 within {FLOAT_TOLERANCE}, got {total}")

    return MappingProxyType(weights)


def validate_reserve_ticks(value: float) -> float:
    """Validate the reserve horizon and return it as a float.

    Args:
        value: How many ticks of consumption a district holds back before any
            of its stock counts as shareable surplus.

    Returns:
        The value as a float.

    Raises:
        TypeError: If the value is not a real number, or is a bool.
        ValueError: If the value is negative or not finite.
    """
    if type(value) is bool or not isinstance(value, int | float):
        raise TypeError(f"reserve_ticks must be a real number, got {type(value).__name__}")
    reserve = float(value)
    if not math.isfinite(reserve):
        raise ValueError(f"reserve_ticks must be finite, got {reserve!r}")
    if reserve < 0.0:
        raise ValueError(f"reserve_ticks must be >= 0, got {reserve}")
    return reserve


def require_finite(value: float, description: str) -> float:
    """Return the value, or raise if a computation produced NaN or an infinity.

    Args:
        value: The computed value to check.
        description: What was being computed, used in the error message.

    Returns:
        The value unchanged.

    Raises:
        ValueError: If the value is not finite.
    """
    if not math.isfinite(value):
        raise ValueError(f"{description} must be finite, got {value!r}")
    return value


def clamp_near_zero(value: float, description: str) -> float:
    """Clamp a tiny negative float to zero, but refuse a meaningful one.

    Subtracting two nearly-equal floats routinely lands a hair below zero. That
    residue is arithmetic noise and is flattened. A negative larger than the
    tolerance is a real defect -- stock that went below zero, or a transfer that
    took more than existed -- and must not be quietly repaired.

    Args:
        value: The computed value.
        description: What the value represents, used in the error message.

    Returns:
        The value, or 0.0 if it sits within tolerance below zero.

    Raises:
        ValueError: If the value is not finite, or is meaningfully negative.
    """
    require_finite(value, description)
    if value < -FLOAT_TOLERANCE:
        raise ValueError(f"{description} must not be negative, got {value}")
    return 0.0 if value < 0.0 else value


def stock_snapshot(pool: ResourcePool) -> dict[ResourceType, float]:
    """Read a pool into a plain dict keyed in RESOURCE_ORDER.

    Args:
        pool: The pool to read.

    Returns:
        A new dict holding the quantity of every resource kind.

    Raises:
        ValueError: If any quantity is not finite or is meaningfully negative.
    """
    return {
        resource: clamp_near_zero(pool.amount_of(resource), f"stock[{resource.value}]")
        for resource in RESOURCE_ORDER
    }


def fsum_ordered(values: Iterable[float]) -> float:
    """Sum floats exactly, accumulating in the order supplied.

    Every caller passes a deliberately ordered iterable, so the result is
    reproducible rather than dependent on how a mapping happened to iterate.

    Args:
        values: The floats to add, already in the intended order.

    Returns:
        The exact-as-possible sum.
    """
    return math.fsum(values)


def sum_amounts(amounts: Mapping[ResourceType, float]) -> float:
    """Sum per-resource amounts in explicit resource order.

    Uses ``math.fsum`` so a reported total matches the per-resource parts as
    closely as floating point allows, which is what the event invariants
    ("total equals the sum of its parts within tolerance") are checked against.

    Args:
        amounts: Amount per resource kind.

    Returns:
        The exact-as-possible sum, accumulated in RESOURCE_ORDER.
    """
    return fsum_ordered(amounts[resource] for resource in RESOURCE_ORDER)


def build_pool(amounts: Mapping[ResourceType, float]) -> ResourcePool:
    """Build a new ResourcePool from computed amounts.

    Resource pools are immutable, so every quantity change in this engine is an
    explicit replacement of the whole value object rather than an edit.

    Args:
        amounts: Quantity per resource kind.

    Returns:
        A new pool holding those quantities.
    """
    return ResourcePool(stock={resource: amounts[resource] for resource in RESOURCE_ORDER})
