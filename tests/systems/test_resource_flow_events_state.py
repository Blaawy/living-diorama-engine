"""Tests for what ResourceFlowSystem publishes, what it changes, and what it conserves."""

import json

import pytest
from living_diorama.entities import ResourceType
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.systems import ResourceFlowSystem
from living_diorama.systems._resource_config import FLOAT_TOLERANCE
from systems_builders import (
    EVEN_ALLOCATION,
    FOOD_ONLY_ALLOCATION,
    LAW_ID,
    build_district,
    build_infrastructure,
    build_law,
    build_wall,
    build_world,
    stocks,
    total_of,
)


def build_flow(reserve_ticks: float = 1.0, allocation=FOOD_ONLY_ALLOCATION):
    """Build a flow system for event and state tests."""
    return ResourceFlowSystem(
        law_id=LAW_ID, consumption_allocation=allocation, reserve_ticks=reserve_ticks
    )


def run_flow(world, flow=None) -> EventLog:
    """Run one flow update and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    (flow or build_flow()).update(world, bus)
    return log


def simple_world():
    """Build 'a' (surplus) connected to 'b' (need)."""
    return build_world(
        [
            build_district("a", population=0, consumption_rate=1.0, food=30.0),
            build_district("b", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("ab", "a", "b")],
        law=build_law(),
        tick=4,
    )


def test_one_event_per_non_zero_transfer_with_correct_shape() -> None:
    """Each applied transfer is announced exactly once, fully described."""
    world = simple_world()
    log = run_flow(world)

    assert len(log) == 1
    event = log.events()[0]
    assert event.type is EventType.RESOURCE_TRANSFERRED
    assert event.tick == 4
    assert event.source_id == "a"
    assert event.payload_as_dict() == {
        "from_district_id": "a",
        "to_district_id": "b",
        "boundary_id": "ab",
        "resource_type": "FOOD",
        "amount": 10.0,
    }


def test_transfer_payload_is_strict_json_compatible() -> None:
    """A transfer event must survive RFC-compliant serialization."""
    payload = run_flow(simple_world()).events()[0].payload_as_dict()
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


def test_no_events_when_nothing_moves() -> None:
    """Silence is correct when there is no surplus or no need."""
    world = build_world(
        [
            build_district("a", population=10, consumption_rate=1.0, food=10.0),
            build_district("b", population=10, consumption_rate=1.0, food=10.0),
        ],
        boundaries=[("ab", "a", "b")],
        law=build_law(),
        tick=1,
    )
    assert len(run_flow(world)) == 0


def test_effectively_zero_transfers_emit_no_events() -> None:
    """A transfer smaller than the tolerance is arithmetic noise, not an event."""
    world = build_world(
        [
            build_district("a", population=0, consumption_rate=1.0,
                           food=FLOAT_TOLERANCE / 10),
            build_district("b", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("ab", "a", "b")],
        law=build_law(),
        tick=1,
    )
    assert len(run_flow(world)) == 0


def test_event_order_follows_resource_then_donor_then_receiver() -> None:
    """Order is fixed by explicit resource order, then donor id, then receiver id."""
    world = build_world(
        [
            build_district("d_one", population=0, consumption_rate=1.0,
                           food=100.0, materials=100.0),
            build_district("d_two", population=0, consumption_rate=1.0,
                           food=100.0, materials=100.0),
            build_district("r_one", population=10, consumption_rate=1.0),
            build_district("r_two", population=10, consumption_rate=1.0),
        ],
        boundaries=[
            ("b1", "d_one", "r_one"),
            ("b2", "d_two", "r_two"),
        ],
        law=build_law(),
        tick=1,
    )
    log = run_flow(world, build_flow(allocation=EVEN_ALLOCATION))
    ordering = [
        (event.payload["resource_type"], event.payload["from_district_id"],
         event.payload["to_district_id"])
        for event in log
    ]

    assert ordering == sorted(
        ordering, key=lambda item: (["FOOD", "MATERIALS", "ENERGY"].index(str(item[0])),
                                    item[1], item[2])
    )
    assert ordering[0][0] == "FOOD"
    assert ordering[-1][0] == "MATERIALS"


def test_event_order_is_independent_of_insertion_order() -> None:
    """Reordering registration must not reorder the published history."""
    def make(order):
        """Build the world with districts registered in the given order."""
        districts = {
            "d_one": build_district("d_one", population=0, consumption_rate=1.0, food=50.0),
            "d_two": build_district("d_two", population=0, consumption_rate=1.0, food=50.0),
            "r_one": build_district("r_one", population=10, consumption_rate=1.0),
            "r_two": build_district("r_two", population=10, consumption_rate=1.0),
        }
        return build_world(
            [districts[key] for key in order],
            boundaries=[("b1", "d_one", "r_one"), ("b2", "d_two", "r_two")],
            law=build_law(),
            tick=1,
        )

    forward = run_flow(make(["d_one", "d_two", "r_one", "r_two"]))
    backward = run_flow(make(["r_two", "r_one", "d_two", "d_one"]))
    assert [event.payload_as_dict() for event in forward] == [
        event.payload_as_dict() for event in backward
    ]


def test_resources_are_conserved_for_every_resource_type() -> None:
    """Flow moves quantity; it never creates or destroys any."""
    world = build_world(
        [
            build_district("a", population=0, consumption_rate=1.0,
                           food=60.0, materials=40.0, energy=20.0),
            build_district("b", population=20, consumption_rate=1.0,
                           food=0.0, materials=0.0, energy=0.0),
            build_district("c", population=30, consumption_rate=1.0,
                           food=5.0, materials=5.0, energy=5.0),
        ],
        boundaries=[("ab", "a", "b"), ("ac", "a", "c")],
        law=build_law(),
        tick=1,
    )
    before = {resource: total_of(world, resource) for resource in ResourceType}

    run_flow(world, build_flow(allocation=EVEN_ALLOCATION))

    for resource in ResourceType:
        assert abs(total_of(world, resource) - before[resource]) <= FLOAT_TOLERANCE


def test_conservation_holds_with_duplicate_boundaries_and_many_participants() -> None:
    """Duplicated edges must not manufacture quantity."""
    world = build_world(
        [
            build_district("d1", population=0, consumption_rate=1.0, food=80.0),
            build_district("d2", population=0, consumption_rate=1.0, food=80.0),
            build_district("r1", population=40, consumption_rate=1.0),
            build_district("r2", population=60, consumption_rate=1.0),
        ],
        boundaries=[
            ("a", "d1", "r1"), ("b", "d1", "r1"), ("c", "d1", "r2"),
            ("d", "d2", "r1"), ("e", "d2", "r2"), ("f", "d2", "r2"),
        ],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    assert abs(total_of(world, ResourceType.FOOD) - 160.0) <= FLOAT_TOLERANCE
    assert all(value >= 0.0 for value in stocks(world, ResourceType.FOOD).values())


def test_untouched_resources_are_left_exactly_alone() -> None:
    """A resource with no staged transfer keeps its exact quantity."""
    world = build_world(
        [
            build_district("a", population=0, consumption_rate=1.0, food=30.0,
                           materials=7.5),
            build_district("b", population=10, consumption_rate=1.0, food=0.0,
                           materials=7.5),
        ],
        boundaries=[("ab", "a", "b")],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    assert stocks(world, ResourceType.MATERIALS) == {"a": 7.5, "b": 7.5}


def test_affected_pools_are_replaced_and_previous_pools_are_unchanged() -> None:
    """Pools are immutable, so both sides of a transfer get new value objects."""
    world = simple_world()
    donor_pool = world.districts["a"].resources
    receiver_pool = world.districts["b"].resources

    run_flow(world)

    assert world.districts["a"].resources is not donor_pool
    assert world.districts["b"].resources is not receiver_pool
    assert donor_pool.amount_of(ResourceType.FOOD) == 30.0
    assert receiver_pool.amount_of(ResourceType.FOOD) == 0.0


def test_unaffected_district_keeps_its_existing_pool() -> None:
    """Non-participation is observable by identity, which proves nothing was rewritten."""
    world = build_world(
        [
            build_district("a", population=0, consumption_rate=1.0, food=30.0),
            build_district("b", population=10, consumption_rate=1.0, food=0.0),
            build_district("bystander", population=0, consumption_rate=0.0, food=1.0),
        ],
        boundaries=[("ab", "a", "b")],
        law=build_law(),
        tick=1,
    )
    bystander_pool = world.districts["bystander"].resources
    run_flow(world)
    assert world.districts["bystander"].resources is bystander_pool


def test_flow_does_not_consume_rng() -> None:
    """All tie-breaking uses identifiers, never randomness."""
    world = build_world(
        [
            build_district("d1", population=0, consumption_rate=1.0, food=50.0),
            build_district("d2", population=0, consumption_rate=1.0, food=50.0),
            build_district("r1", population=30, consumption_rate=1.0),
            build_district("r2", population=30, consumption_rate=1.0),
        ],
        boundaries=[("a", "d1", "r1"), ("b", "d1", "r2"), ("c", "d2", "r1")],
        law=build_law(),
        tick=1,
    )
    before = world.rng.get_state()
    run_flow(world)
    assert world.rng.get_state() == before


def test_flow_leaves_every_non_resource_field_untouched() -> None:
    """Flow moves resources only; nothing else in the world is its business."""
    donor = build_district("a", population=5, consumption_rate=1.0,
                           production_rate=3.0, food=100.0)
    receiver = build_district("b", population=10, consumption_rate=2.0,
                              production_rate=4.0, food=0.0)
    world = build_world([donor, receiver], boundaries=[("ab", "a", "b")],
                        law=build_law(), tick=1)
    world.add_wall(build_wall("wall", "ab", active=False))
    world.add_infrastructure(build_infrastructure("infra", "ab"))

    run_flow(world)

    assert (donor.population, receiver.population) == (5, 10)
    assert (donor.consumption_rate, receiver.consumption_rate) == (1.0, 2.0)
    assert (donor.production_rate, receiver.production_rate) == (3.0, 4.0)
    assert world.infrastructure["infra"].dependency_score == 0.0
    assert world.walls["wall"].active is False
    assert world.boundaries["ab"].wall_id == "wall"
    assert world.laws[LAW_ID].current_value is True


def test_no_per_tick_state_leaks_between_updates() -> None:
    """A reused system must behave as though each update started fresh."""
    flow = build_flow()
    assert not hasattr(flow, "__dict__")

    first = simple_world()
    run_flow(first, flow)
    second = simple_world()
    run_flow(second, flow)

    assert stocks(first, ResourceType.FOOD) == stocks(second, ResourceType.FOOD)


class _NonConservingFlowSystem(ResourceFlowSystem):
    """A flow system whose delta calculation invents quantity, to trip the guard.

    A subclass rather than a monkeypatch: rebinding a staticmethod on the real
    class and restoring it unwraps the descriptor into a plain function, which
    silently turns it into an instance method for everything that runs after.
    """

    @staticmethod
    def _apply_deltas(snapshot, staged):
        """Return post-transfer stock that does not conserve FOOD."""
        result = {
            district_id: dict(amounts) for district_id, amounts in snapshot.items()
        }
        result["b"][ResourceType.FOOD] += 500.0
        return result


def test_failed_conservation_raises_and_publishes_no_events() -> None:
    """Events describe applied state, so a rejected update must announce nothing."""
    world = simple_world()
    flow = _NonConservingFlowSystem(
        law_id=LAW_ID, consumption_allocation=FOOD_ONLY_ALLOCATION, reserve_ticks=1.0
    )
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)

    with pytest.raises(ValueError):
        flow.update(world, bus)

    assert len(log) == 0
    assert stocks(world, ResourceType.FOOD) == {"a": 30.0, "b": 0.0}


def test_multiple_resource_types_transfer_in_one_update() -> None:
    """A single update can move more than one kind of resource."""
    world = build_world(
        [
            build_district("a", population=0, consumption_rate=1.0,
                           food=100.0, materials=100.0, energy=100.0),
            build_district("b", population=10, consumption_rate=1.0),
        ],
        boundaries=[("ab", "a", "b")],
        law=build_law(),
        tick=1,
    )
    log = run_flow(world, build_flow(allocation=EVEN_ALLOCATION))
    moved = {str(event.payload["resource_type"]) for event in log}
    assert moved == {"FOOD", "MATERIALS", "ENERGY"}
