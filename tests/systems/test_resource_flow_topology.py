"""Tests for which boundaries resource flow may cross, and the reserve model.

The wall is the artifact the whole MVP exists to produce, so what a wall does
and does not block is worth pinning down precisely: an active wall stops
resources, while a permanent-but-deactivated wall stays in the world's history
without obstructing anything.
"""

import pytest
from living_diorama.entities import Boundary, ResourceType
from living_diorama.events import EventBus, EventLog
from living_diorama.systems import ResourceFlowSystem
from systems_builders import (
    EVEN_ALLOCATION,
    LAW_ID,
    build_district,
    build_infrastructure,
    build_law,
    build_wall,
    build_world,
)


def build_flow(reserve_ticks: float = 1.0) -> ResourceFlowSystem:
    """Build a flow system bound to the standard sharing law."""
    return ResourceFlowSystem(
        law_id=LAW_ID, consumption_allocation=EVEN_ALLOCATION, reserve_ticks=reserve_ticks
    )


def run_flow(world, flow=None) -> EventLog:
    """Run one flow update and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    (flow or build_flow()).update(world, bus)
    return log


def donor_receiver_world(boundaries=None):
    """Build 'a' (surplus 100 food) connected to 'b' (need 5 food)."""
    return build_world(
        [
            build_district("a", population=0, consumption_rate=1.0, food=100.0),
            build_district("b", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=boundaries if boundaries is not None else [("bound", "a", "b")],
        law=build_law(),
        tick=1,
    )


def test_boundary_with_no_wall_permits_flow() -> None:
    """An open boundary is the default case."""
    world = donor_receiver_world()
    run_flow(world)
    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 5.0


def test_active_wall_blocks_flow() -> None:
    """A standing wall is what turns a shared world into two separated ones."""
    world = donor_receiver_world()
    world.add_wall(build_wall("wall", "bound", active=True))
    log = run_flow(world)

    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 0.0
    assert len(log) == 0


def test_inactive_wall_permits_flow() -> None:
    """A permanent but deactivated wall remains history without blocking resources."""
    world = donor_receiver_world()
    world.add_wall(build_wall("wall", "bound", active=False, permanent=True))
    run_flow(world)
    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 5.0


def test_wall_and_boundary_state_are_never_modified() -> None:
    """Flow reads the topology; only later phases may reshape it."""
    world = donor_receiver_world()
    world.add_wall(build_wall("wall", "bound", active=False))
    wall = world.walls["wall"]
    boundary = world.boundaries["bound"]
    wall_before = (wall.active, wall.permanent, wall.integrity, wall.boundary_id,
                   wall.dependency_score, wall.transport_dependency, wall.resource_dependency)
    boundary_before = (boundary.wall_id, boundary.district_a_id, boundary.district_b_id)

    run_flow(world)

    assert (wall.active, wall.permanent, wall.integrity, wall.boundary_id,
            wall.dependency_score, wall.transport_dependency,
            wall.resource_dependency) == wall_before
    assert (boundary.wall_id, boundary.district_a_id,
            boundary.district_b_id) == boundary_before


def test_infrastructure_is_untouched_and_unused_in_this_phase() -> None:
    """Infrastructure plays no part in flow yet, and must not be altered by it."""
    world = donor_receiver_world()
    world.add_infrastructure(build_infrastructure("infra", "bound"))
    infra = world.infrastructure["infra"]
    before = (infra.capacity, infra.dependency_score, infra.degraded)

    run_flow(world)

    assert (infra.capacity, infra.dependency_score, infra.degraded) == before


def test_disconnected_districts_do_not_transfer() -> None:
    """Resources move across boundaries, so an isolated district is on its own."""
    world = donor_receiver_world(boundaries=[])
    log = run_flow(world)
    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 0.0
    assert len(log) == 0


def test_unresolvable_wall_reference_fails_clearly() -> None:
    """World forbids this state, so reaching it means something is badly wrong."""
    world = donor_receiver_world()
    world.boundaries["bound"].wall_id = "ghost_wall"
    with pytest.raises(ValueError):
        run_flow(world)


def test_duplicate_boundaries_do_not_duplicate_need_or_capacity() -> None:
    """Two boundaries between the same pair describe one connection, not two."""
    single = donor_receiver_world()
    run_flow(single)
    expected = single.districts["b"].resources.amount_of(ResourceType.FOOD)

    doubled = donor_receiver_world(
        boundaries=[("bound_a", "a", "b"), ("bound_b", "a", "b")]
    )
    run_flow(doubled)

    assert doubled.districts["b"].resources.amount_of(ResourceType.FOOD) == expected


def test_duplicate_boundaries_report_the_smallest_boundary_id() -> None:
    """One deterministic identifier is chosen so events never become ambiguous."""
    world = donor_receiver_world(
        boundaries=[("zzz_boundary", "a", "b"), ("aaa_boundary", "a", "b")]
    )
    log = run_flow(world)
    assert log.events()[0].payload["boundary_id"] == "aaa_boundary"


def test_boundary_insertion_order_does_not_change_results() -> None:
    """Every traversal is sorted, so the order boundaries were added is irrelevant."""
    forward = donor_receiver_world(
        boundaries=[("aaa_boundary", "a", "b"), ("zzz_boundary", "a", "b")]
    )
    reverse = donor_receiver_world(
        boundaries=[("zzz_boundary", "a", "b"), ("aaa_boundary", "a", "b")]
    )
    forward_log = run_flow(forward)
    reverse_log = run_flow(reverse)

    assert [event.payload_as_dict() for event in forward_log] == [
        event.payload_as_dict() for event in reverse_log
    ]


def test_a_district_cannot_transfer_to_itself() -> None:
    """Boundaries join distinct districts, so self-transfer is not representable."""
    world = donor_receiver_world()
    with pytest.raises(ValueError):
        Boundary(id="self", created_tick=0, district_a_id="a", district_b_id="a")
    assert world.districts["a"].resources.amount_of(ResourceType.FOOD) == 100.0


def test_reserve_target_uses_population_rate_allocation_and_horizon() -> None:
    """reserve = population x consumption_rate x weight x reserve_ticks."""
    world = build_world(
        [
            build_district("a", population=0, consumption_rate=1.0, food=100.0),
            build_district("b", population=10, consumption_rate=2.0, food=0.0),
        ],
        boundaries=[("bound", "a", "b")],
        law=build_law(),
        tick=1,
    )
    run_flow(world, build_flow(reserve_ticks=3.0))
    # 10 population x 2.0 rate x 0.5 food weight x 3 ticks = 30.0
    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 30.0


def test_donor_retains_its_own_reserve() -> None:
    """A donor shares only what it holds above its own reserve."""
    world = build_world(
        [
            build_district("a", population=10, consumption_rate=1.0, food=20.0),
            build_district("b", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("bound", "a", "b")],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    # a reserves 10 x 1.0 x 0.5 x 1 = 5.0, so shares up to 15; b needs 5.
    assert world.districts["a"].resources.amount_of(ResourceType.FOOD) == 15.0
    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 5.0


def test_stock_exactly_at_reserve_produces_no_surplus_and_no_need() -> None:
    """Sitting exactly on the reserve makes a district neither donor nor receiver."""
    world = build_world(
        [
            build_district("a", population=10, consumption_rate=1.0, food=5.0),
            build_district("b", population=10, consumption_rate=1.0, food=5.0),
        ],
        boundaries=[("bound", "a", "b")],
        law=build_law(),
        tick=1,
    )
    pools = {key: world.districts[key].resources for key in ("a", "b")}
    log = run_flow(world)

    assert len(log) == 0
    assert world.districts["a"].resources is pools["a"]
    assert world.districts["b"].resources is pools["b"]


def test_zero_reserve_ticks_makes_all_stock_shareable() -> None:
    """With no reserve horizon every unit above zero counts as surplus."""
    world = build_world(
        [
            build_district("a", population=10, consumption_rate=1.0, food=40.0),
            build_district("b", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("bound", "a", "b")],
        law=build_law(),
        tick=1,
    )
    log = run_flow(world, build_flow(reserve_ticks=0.0))
    # Both reserves are zero, so b has no need either and nothing moves.
    assert len(log) == 0
    assert world.districts["a"].resources.amount_of(ResourceType.FOOD) == 40.0


def test_donor_never_sends_more_than_its_stock() -> None:
    """A donor with little stock cannot fill a large need."""
    world = build_world(
        [
            build_district("a", population=0, consumption_rate=1.0, food=2.0),
            build_district("b", population=100, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("bound", "a", "b")],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    assert world.districts["a"].resources.amount_of(ResourceType.FOOD) == 0.0
    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 2.0


def test_receiver_never_receives_more_than_its_original_need() -> None:
    """A receiver is filled to its reserve target and no further."""
    world = build_world(
        [
            build_district("a", population=0, consumption_rate=1.0, food=1000.0),
            build_district("b", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("bound", "a", "b")],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    assert world.districts["b"].resources.amount_of(ResourceType.FOOD) == 5.0
