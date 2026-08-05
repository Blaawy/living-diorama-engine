"""Tests for the shared allocation and numeric configuration validation.

Configuration errors must surface at construction, not on the first tick of a
5,000-tick episode, so these tests focus on what the constructors refuse.
"""

import math

import pytest
from systems_builders import EVEN_ALLOCATION, LAW_ID

from living_diorama.entities import ResourceType
from living_diorama.systems import ConsumptionSystem, ProductionSystem, ResourceFlowSystem
from living_diorama.systems._resource_config import (
    FLOAT_TOLERANCE,
    PROJECTION_TOLERANCE,
    RESOURCE_ORDER,
    clamp_near_zero,
    require_finite,
    validate_allocation,
)

SYSTEM_FACTORIES = (ProductionSystem, ConsumptionSystem)


def test_resource_order_covers_every_resource_type_exactly_once() -> None:
    """The explicit order must not silently drift from the enum it mirrors."""
    assert set(RESOURCE_ORDER) == set(ResourceType)
    assert len(RESOURCE_ORDER) == len(ResourceType)


def test_valid_allocation_is_accepted_by_both_systems() -> None:
    """A normalized three-key allocation is the ordinary case."""
    for factory in SYSTEM_FACTORIES:
        system = factory(allocation=dict(EVEN_ALLOCATION))
        assert system.allocation[ResourceType.FOOD] == 0.5


def test_missing_resource_keys_are_rejected() -> None:
    """Every resource kind must be given a weight, even a zero one."""
    for factory in SYSTEM_FACTORIES:
        with pytest.raises(ValueError):
            factory(allocation={ResourceType.FOOD: 1.0})


def test_unknown_or_extra_keys_are_rejected() -> None:
    """A key that is not a ResourceType is necessarily an extra one."""
    bad = dict(EVEN_ALLOCATION) | {"FOOD": 0.0}
    for factory in SYSTEM_FACTORIES:
        with pytest.raises(TypeError):
            factory(allocation=bad)  # type: ignore[arg-type]


def test_negative_weights_are_rejected() -> None:
    """A negative weight would produce negative production or demand."""
    bad = {ResourceType.FOOD: 1.5, ResourceType.MATERIALS: -0.5, ResourceType.ENERGY: 0.0}
    for factory in SYSTEM_FACTORIES:
        with pytest.raises(ValueError):
            factory(allocation=bad)


def test_non_finite_weights_are_rejected() -> None:
    """NaN and the infinities cannot describe a share of anything."""
    for bad_value in (float("nan"), float("inf"), float("-inf")):
        bad = dict(EVEN_ALLOCATION) | {ResourceType.FOOD: bad_value}
        for factory in SYSTEM_FACTORIES:
            with pytest.raises(ValueError):
                factory(allocation=bad)


def test_boolean_weights_are_rejected() -> None:
    """Bool subclasses int, so True would silently mean a weight of 1.0."""
    bad = {ResourceType.FOOD: True, ResourceType.MATERIALS: 0.0, ResourceType.ENERGY: 0.0}
    for factory in SYSTEM_FACTORIES:
        with pytest.raises(TypeError):
            factory(allocation=bad)  # type: ignore[dict-item]


def test_non_numeric_weights_are_rejected() -> None:
    """A weight must be a real number, not a string that looks like one."""
    bad = dict(EVEN_ALLOCATION) | {ResourceType.FOOD: "0.5"}
    for factory in SYSTEM_FACTORIES:
        with pytest.raises(TypeError):
            factory(allocation=bad)  # type: ignore[dict-item]


def test_allocation_totals_outside_tolerance_are_rejected() -> None:
    """Weights are normalized shares, so they must add up to the whole."""
    for total_off in (0.9, 1.1, 0.0):
        scale = total_off / 1.0
        bad = {resource: EVEN_ALLOCATION[resource] * scale for resource in RESOURCE_ORDER}
        for factory in SYSTEM_FACTORIES:
            with pytest.raises(ValueError):
                factory(allocation=bad)


def test_allocation_totals_within_tolerance_are_accepted() -> None:
    """Float arithmetic rarely lands on exactly 1.0, and that must not be fatal."""
    nudged = {
        ResourceType.FOOD: 0.5 + FLOAT_TOLERANCE / 4,
        ResourceType.MATERIALS: 0.3,
        ResourceType.ENERGY: 0.2,
    }
    for factory in SYSTEM_FACTORIES:
        assert factory(allocation=nudged) is not None


def test_allocation_total_just_outside_tolerance_is_rejected() -> None:
    """The tolerance is a boundary, not an open door."""
    bad = {
        ResourceType.FOOD: 0.5 + FLOAT_TOLERANCE * 100,
        ResourceType.MATERIALS: 0.3,
        ResourceType.ENERGY: 0.2,
    }
    for factory in SYSTEM_FACTORIES:
        with pytest.raises(ValueError):
            factory(allocation=bad)


def test_caller_mutation_cannot_change_stored_configuration() -> None:
    """The allocation is copied, so the caller's dict is no longer connected."""
    supplied = dict(EVEN_ALLOCATION)
    systems = [factory(allocation=supplied) for factory in SYSTEM_FACTORIES]
    flow = ResourceFlowSystem(law_id=LAW_ID, consumption_allocation=supplied, reserve_ticks=1.0)

    supplied[ResourceType.FOOD] = 99.0
    for system in systems:
        assert system.allocation[ResourceType.FOOD] == 0.5
    assert flow.consumption_allocation[ResourceType.FOOD] == 0.5


def test_stored_allocation_is_read_only() -> None:
    """Configuration cannot be edited through the system's own accessor."""
    for factory in SYSTEM_FACTORIES:
        system = factory(allocation=dict(EVEN_ALLOCATION))
        with pytest.raises(TypeError):
            system.allocation[ResourceType.FOOD] = 99.0  # type: ignore[index]


def test_negative_reserve_ticks_is_rejected() -> None:
    """A district cannot hold back a negative amount of consumption."""
    with pytest.raises(ValueError):
        ResourceFlowSystem(
            law_id=LAW_ID, consumption_allocation=EVEN_ALLOCATION, reserve_ticks=-1.0
        )


def test_non_finite_reserve_ticks_is_rejected() -> None:
    """An infinite reserve horizon would make every district permanently needy."""
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            ResourceFlowSystem(
                law_id=LAW_ID, consumption_allocation=EVEN_ALLOCATION, reserve_ticks=bad
            )


def test_boolean_reserve_ticks_is_rejected() -> None:
    """True would silently mean a one-tick reserve."""
    with pytest.raises(TypeError):
        ResourceFlowSystem(
            law_id=LAW_ID,
            consumption_allocation=EVEN_ALLOCATION,
            reserve_ticks=True,  # type: ignore[arg-type]
        )


def test_non_numeric_reserve_ticks_is_rejected() -> None:
    """The reserve horizon must be a real number."""
    with pytest.raises(TypeError):
        ResourceFlowSystem(
            law_id=LAW_ID,
            consumption_allocation=EVEN_ALLOCATION,
            reserve_ticks="1.0",  # type: ignore[arg-type]
        )


def test_zero_reserve_ticks_is_accepted() -> None:
    """Zero is a meaningful setting: every unit of stock becomes shareable."""
    flow = ResourceFlowSystem(
        law_id=LAW_ID, consumption_allocation=EVEN_ALLOCATION, reserve_ticks=0
    )
    assert flow.reserve_ticks == 0.0


def test_blank_law_id_is_rejected() -> None:
    """The gating law must actually be nameable."""
    with pytest.raises(ValueError):
        ResourceFlowSystem(law_id="   ", consumption_allocation=EVEN_ALLOCATION, reserve_ticks=1.0)


def test_non_string_law_id_is_rejected() -> None:
    """A law identifier is a string, like every other entity id."""
    with pytest.raises(TypeError):
        ResourceFlowSystem(
            law_id=5,  # type: ignore[arg-type]
            consumption_allocation=EVEN_ALLOCATION,
            reserve_ticks=1.0,
        )


def test_validate_allocation_rejects_a_non_mapping() -> None:
    """An allocation is a mapping of weights, not a sequence."""
    with pytest.raises(TypeError):
        validate_allocation([0.5, 0.3, 0.2], "test allocation")  # type: ignore[arg-type]


def test_clamp_near_zero_flattens_float_residue() -> None:
    """Subtracting nearly-equal floats routinely lands a hair below zero."""
    assert clamp_near_zero(-FLOAT_TOLERANCE / 2, "residue") == 0.0


def test_clamp_near_zero_refuses_a_meaningful_negative() -> None:
    """The tolerance must never hide a real accounting error."""
    with pytest.raises(ValueError):
        clamp_near_zero(-0.5, "real shortfall")


def test_require_finite_rejects_nan_and_infinity() -> None:
    """A non-finite computed value is a defect, not a value."""
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError):
            require_finite(bad, "computed value")
    assert require_finite(1.5, "computed value") == 1.5


def test_tolerance_is_small_enough_to_be_meaningless_as_a_quantity() -> None:
    """The tolerance must be arithmetic noise, not a quantity a district could hold."""
    assert 0 < FLOAT_TOLERANCE <= 1e-6
    assert math.isfinite(FLOAT_TOLERANCE)


def test_projection_tolerance_is_strictly_finer_than_the_quantity_tolerance() -> None:
    """Convergence must be judged more finely than significance.

    An iterative search settles within a small multiple of whatever threshold
    stopped it, so a result can only be certified to a bound coarser than that
    threshold. Sharing one constant would mean asserting agreement at exactly
    the precision the search was allowed to stop at, which cannot hold.
    """
    assert 0 < PROJECTION_TOLERANCE < FLOAT_TOLERANCE
    assert PROJECTION_TOLERANCE * 100 == FLOAT_TOLERANCE


def test_projection_tolerance_leaves_room_for_measured_residue() -> None:
    """The gap must exceed the residue the projection actually leaves behind.

    Measured worst-case rename residue is around four times the projection
    threshold, so the gap has to be comfortably larger than that to make the
    quantity tolerance a guarantee rather than a near miss.
    """
    assert PROJECTION_TOLERANCE * 10 <= FLOAT_TOLERANCE
