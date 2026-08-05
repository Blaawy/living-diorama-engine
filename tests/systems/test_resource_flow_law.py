"""Tests for the law contract that gates ResourceFlowSystem.

Sharing is a rule, and the whole series premise is that changing that rule
changes the world. So the gate is checked with exact boolean identity rather
than truthiness: the integer 1 is not permission to share.
"""

import pytest
from systems_builders import EVEN_ALLOCATION, LAW_ID, build_district, build_law, build_world

from living_diorama.entities import ResourceType
from living_diorama.events import EventBus, EventLog
from living_diorama.systems import ResourceFlowSystem


def build_flow(reserve_ticks: float = 1.0) -> ResourceFlowSystem:
    """Build a flow system bound to the standard sharing law."""
    return ResourceFlowSystem(
        law_id=LAW_ID, consumption_allocation=EVEN_ALLOCATION, reserve_ticks=reserve_ticks
    )


def build_donor_receiver_world(law=None):
    """Build a two-district world where 'a' has surplus food and 'b' needs it."""
    return build_world(
        [
            build_district("a", population=0, consumption_rate=1.0, food=100.0),
            build_district("b", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("bound", "a", "b")],
        law=law,
        tick=1,
    )


def run_flow(world, flow=None) -> EventLog:
    """Run one flow update and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    (flow or build_flow()).update(world, bus)
    return log


def test_missing_law_raises_key_error() -> None:
    """A flow system bound to a law that is not in the world cannot proceed."""
    world = build_donor_receiver_world(law=None)
    with pytest.raises(KeyError):
        run_flow(world)


def test_active_law_with_true_value_allows_transfers() -> None:
    """The ordinary enabled case: surplus reaches a connected district in need."""
    world = build_donor_receiver_world(law=build_law(active=True, current_value=True))
    log = run_flow(world)

    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 5.0
    assert len(log) == 1


def test_inactive_law_blocks_every_transfer() -> None:
    """A law that is not in force cannot permit anything."""
    world = build_donor_receiver_world(law=build_law(active=False, current_value=True))
    pool_before = world.districts["a"].resources
    log = run_flow(world)

    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 0.0
    assert world.districts["a"].resources is pool_before
    assert len(log) == 0


def test_active_law_with_false_value_blocks_every_transfer() -> None:
    """This is the case the series depends on: the law is repealed and flow stops."""
    world = build_donor_receiver_world(law=build_law(active=True, current_value=False))
    log = run_flow(world)

    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 0.0
    assert len(log) == 0


def test_non_boolean_law_values_are_rejected() -> None:
    """Truthiness is not permission: 1, 'true', and 0.0 are all malformed here."""
    for bad_value in (1, 0, "true", 1.0, None):
        world = build_donor_receiver_world(law=build_law(active=True, current_value=bad_value))
        with pytest.raises(TypeError):
            run_flow(world)


def test_law_value_is_validated_even_when_the_law_is_inactive() -> None:
    """A malformed law is reported the tick it appears, not the tick it matters."""
    world = build_donor_receiver_world(law=build_law(active=False, current_value=1))
    with pytest.raises(TypeError):
        run_flow(world)


def test_law_value_is_validated_even_when_no_district_needs_anything() -> None:
    """The gate is checked before need is examined, so config errors surface early."""
    world = build_world(
        [build_district("a", population=0, food=0.0), build_district("b", population=0)],
        boundaries=[("bound", "a", "b")],
        law=build_law(active=True, current_value="yes"),
        tick=1,
    )
    with pytest.raises(TypeError):
        run_flow(world)


def test_law_state_is_never_modified() -> None:
    """The flow system obeys the law; it has no authority to change it."""
    law = build_law(active=True, current_value=True)
    world = build_donor_receiver_world(law=law)
    before = (
        law.active,
        law.current_value,
        law.previous_value,
        law.changed_episode,
        law.restored_tick,
        law.name,
    )

    run_flow(world)

    assert (
        law.active,
        law.current_value,
        law.previous_value,
        law.changed_episode,
        law.restored_tick,
        law.name,
    ) == before


def test_disabled_sharing_consumes_no_rng() -> None:
    """The disabled path must be inert in every respect, including randomness."""
    world = build_donor_receiver_world(law=build_law(active=True, current_value=False))
    before = world.rng.get_state()
    run_flow(world)
    assert world.rng.get_state() == before
