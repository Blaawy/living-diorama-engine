"""Shared measurement of the pressure a district faces going into the next tick.

Private to the systems package. Both MigrationSystem and ScarcitySystem need
the same number -- what fraction of a district's *projected* demand its
*remaining* stock cannot cover -- and they must agree on it exactly, because
migration decides who leaves based on that pressure and scarcity then records
the pressure that remains. Two independent formulas would let a district appear
pressured enough to depopulate and relieved enough to be scored comfortable in
the same tick.

This is forward-looking, and that distinction matters. It is not a second
reading of what went unmet during the tick just completed: ConsumptionSystem
already reports that, as ``unmet_total``. This asks a different question --
given what the district is left holding, and what it will need next tick, how
much of that need is already unfunded?

The two answers routinely differ, and the case that shows it most sharply is a
district that ends the tick having eaten exactly its last reserves. Its
consumption was fully met, so ``unmet_total`` is zero; its stock is now zero
against an undiminished projected demand, so its forward pressure is one. That
is the correct reading of both: nobody went hungry today, and there is nothing
left for tomorrow.

Projected demand is sized the way ConsumptionSystem sizes actual demand --
population times the consumption rate, split across resource kinds by the same
normalized allocation -- so the projection is of the same tick the district is
about to live, not of a different regime. Nothing here reads or writes world
state.
"""

import math
from collections.abc import Mapping

from living_diorama.entities import District, ResourceType
from living_diorama.systems._resource_config import (
    FLOAT_TOLERANCE,
    RESOURCE_ORDER,
    fsum_ordered,
    require_finite,
)


def validate_unit_scalar(value: float, field_name: str) -> float:
    """Validate a normalized configuration value and return it as a float.

    Args:
        value: The value to check.
        field_name: Name of the field, used in error messages.

    Returns:
        The value as a float.

    Raises:
        TypeError: If the value is not a real number, or is a bool. ``bool``
            is rejected explicitly because it subclasses ``int``, so ``True``
            would silently mean a rate of 1.0.
        ValueError: If the value is not finite or falls outside 0.0-1.0.
    """
    if type(value) is bool or not isinstance(value, int | float):
        raise TypeError(f"{field_name} must be a real number, got {type(value).__name__}")
    scalar = float(value)
    if not math.isfinite(scalar):
        raise ValueError(f"{field_name} must be finite, got {scalar!r}")
    if not 0.0 <= scalar <= 1.0:
        raise ValueError(f"{field_name} must be within 0.0-1.0, got {scalar}")
    return scalar


def required_amounts(
    district: District, allocation: Mapping[ResourceType, float]
) -> dict[ResourceType, float]:
    """Return how much of each resource a district's population will need.

    Sized from the district's current population and consumption rate, so when
    it is called at the end of a tick it describes the demand the district is
    about to face rather than the one it has just met.

    Args:
        district: The district whose projected demand is wanted.
        allocation: Normalized consumption weight per resource kind.

    Returns:
        Required quantity per resource kind, in RESOURCE_ORDER.

    Raises:
        ValueError: If a computed requirement is not finite.
    """
    total = require_finite(
        float(district.population) * float(district.consumption_rate),
        f"required total of {district.id!r}",
    )
    return {
        resource: require_finite(
            total * allocation[resource],
            f"required {resource.value} of {district.id!r}",
        )
        for resource in RESOURCE_ORDER
    }


def shortfall_ratio(district: District, allocation: Mapping[ResourceType, float]) -> float:
    """Return the fraction of a district's projected demand its stock cannot cover.

    Zero means the district could meet its next tick's needs out of what it
    holds now; one means it could meet none of them. The shortfall is measured
    per resource kind and then summed, so a district drowning in energy while
    starving for food is not scored as comfortable -- a surplus of one resource
    never offsets a deficit in another.

    Because this reads stock *after* the tick's consumption, a district that
    has just eaten its last reserves scores one even though nothing went unmet
    while it was eating. That is the intended meaning: the score describes
    exposure going forward, not hunger already suffered.

    A district with no projected demand -- no population, or a zero consumption
    rate -- has nothing it can fall short of, so the ratio is zero rather than
    a division by zero. That is a deliberate reading: an empty district is not
    under pressure, it is simply empty.

    Args:
        district: The district to measure.
        allocation: Normalized consumption weight per resource kind.

    Returns:
        A value in 0.0-1.0.

    Raises:
        ValueError: If a computed value is not finite.
    """
    required = required_amounts(district, allocation)
    total_required = fsum_ordered(required[resource] for resource in RESOURCE_ORDER)
    if total_required <= FLOAT_TOLERANCE:
        return 0.0

    shortfalls = {
        resource: max(0.0, required[resource] - district.resources.amount_of(resource))
        for resource in RESOURCE_ORDER
    }
    total_shortfall = fsum_ordered(shortfalls[resource] for resource in RESOURCE_ORDER)

    ratio = require_finite(total_shortfall / total_required, f"shortfall ratio of {district.id!r}")
    return min(1.0, max(0.0, ratio))


def shortfall_breakdown(
    district: District, allocation: Mapping[ResourceType, float]
) -> tuple[float, float]:
    """Return a district's projected demand and how much of it is unfunded.

    Args:
        district: The district to measure.
        allocation: Normalized consumption weight per resource kind.

    Returns:
        A pair of (total projected demand, total projected shortfall).
    """
    required = required_amounts(district, allocation)
    total_required = fsum_ordered(required[resource] for resource in RESOURCE_ORDER)
    total_shortfall = fsum_ordered(
        max(0.0, required[resource] - district.resources.amount_of(resource))
        for resource in RESOURCE_ORDER
    )
    return total_required, total_shortfall
