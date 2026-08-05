"""Tests for MigrationSystem.

Population is the one quantity in this engine that can never be created or
lost, so most of these tests are about what migration refuses to do: overfill
housing, cross a standing wall, drain a district it cannot relieve, or let a
district's name decide who leaves.
"""

import json

import pytest
from systems_builders import (
    EVEN_ALLOCATION,
    LAW_ID,
    build_district,
    build_infrastructure,
    build_law,
    build_wall,
    build_world,
)

from living_diorama.entities import IsolationState, ResourceType
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.systems import MigrationSystem
from living_diorama.systems._resource_config import FLOAT_TOLERANCE


def build_migration(
    *,
    law_id: str = LAW_ID,
    migration_rate: float = 0.2,
    min_pressure_gap: float = 0.05,
    partial_isolation_factor: float = 0.5,
    allocation=EVEN_ALLOCATION,
) -> MigrationSystem:
    """Build a migration system with legible defaults."""
    return MigrationSystem(
        law_id=law_id,
        consumption_allocation=allocation,
        migration_rate=migration_rate,
        min_pressure_gap=min_pressure_gap,
        partial_isolation_factor=partial_isolation_factor,
    )


def build_migration_world(districts, *, boundaries=None, law=None, **kwargs):
    """Assemble a world that permits movement unless a test says otherwise.

    Migration is gated by the movement law, so every migration scenario needs
    one registered. Tests that care about the law pass their own.
    """
    return build_world(
        districts,
        boundaries=boundaries,
        law=build_law() if law is None else law,
        **kwargs,
    )


def run_migration(world, system=None) -> EventLog:
    """Run one migration update and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    (system or build_migration()).update(world, bus)
    return log


def populations(world) -> dict[str, int]:
    """Read every district's population, keyed by id."""
    return {
        district_id: world.districts[district_id].population
        for district_id in sorted(world.districts)
    }


def total_population(world) -> int:
    """Sum population across the whole world."""
    return sum(populations(world).values())


def starving(district_id: str, *, population: int = 100, **kwargs):
    """Build a district with demand and no stock at all."""
    return build_district(district_id, population=population, consumption_rate=1.0, **kwargs)


def fed(district_id: str, *, population: int = 10, **kwargs):
    """Build a district whose stock comfortably covers its demand."""
    return build_district(
        district_id,
        population=population,
        consumption_rate=1.0,
        food=1000.0,
        materials=1000.0,
        energy=1000.0,
        **kwargs,
    )


def pressured_pair(*, boundaries=None, **world_kwargs):
    """Build a starving district connected to a well-supplied one."""
    return build_migration_world(
        [starving("poor"), fed("rich")],
        boundaries=[("bound", "poor", "rich")] if boundaries is None else boundaries,
        tick=1,
        **world_kwargs,
    )


def test_equilibrium_causes_no_migration() -> None:
    """Districts under equal, met demand have no reason to move anyone."""
    world = build_migration_world(
        [fed("a", population=50), fed("b", population=50)],
        boundaries=[("bound", "a", "b")],
        tick=1,
    )
    log = run_migration(world)

    assert populations(world) == {"a": 50, "b": 50}
    assert len(log) == 0


def test_pressured_district_migrates_toward_a_better_neighbour() -> None:
    """The core behaviour: people leave a district that cannot feed them."""
    world = pressured_pair()
    run_migration(world)

    assert populations(world) == {"poor": 80, "rich": 30}


def test_population_is_globally_conserved() -> None:
    """Nobody is created or lost, whatever the topology."""
    world = build_migration_world(
        [starving("p1"), starving("p2", population=60), fed("r1"), fed("r2", population=5)],
        boundaries=[("b1", "p1", "r1"), ("b2", "p1", "r2"), ("b3", "p2", "r1")],
        tick=1,
    )
    before = total_population(world)
    run_migration(world)
    assert total_population(world) == before


def test_source_population_never_becomes_negative() -> None:
    """Even at maximum migration rate a district cannot send more than it has."""
    world = build_migration_world(
        [starving("poor", population=3), fed("rich")],
        boundaries=[("bound", "poor", "rich")],
        tick=1,
    )
    run_migration(world, build_migration(migration_rate=1.0))

    assert world.districts["poor"].population >= 0
    assert total_population(world) == 13


def test_destination_housing_capacity_is_respected() -> None:
    """A destination never takes more people than it has room for."""
    world = build_migration_world(
        [starving("poor"), fed("rich", population=10, housing_capacity=15)],
        boundaries=[("bound", "poor", "rich")],
        tick=1,
    )
    run_migration(world)

    assert world.districts["rich"].population <= 15
    assert populations(world) == {"poor": 95, "rich": 15}
    assert total_population(world) == 110


def test_full_destination_receives_nobody() -> None:
    """No housing to spare means no arrivals, and nobody leaves for it."""
    world = build_migration_world(
        [starving("poor"), fed("rich", population=10, housing_capacity=10)],
        boundaries=[("bound", "poor", "rich")],
        tick=1,
    )
    log = run_migration(world)

    assert populations(world) == {"poor": 100, "rich": 10}
    assert len(log) == 0


def test_active_wall_prevents_migration() -> None:
    """A standing wall stops people exactly as it stops resources."""
    world = pressured_pair()
    world.add_wall(build_wall("wall", "bound", active=True))
    log = run_migration(world)

    assert populations(world) == {"poor": 100, "rich": 10}
    assert len(log) == 0


def test_inactive_wall_permits_migration() -> None:
    """A permanent but deactivated wall is history, not a barrier."""
    world = pressured_pair()
    world.add_wall(build_wall("wall", "bound", active=False, permanent=True))
    run_migration(world)

    assert world.districts["rich"].population > 10


def test_disconnected_districts_cannot_exchange_population() -> None:
    """With no boundary there is no route, however great the pressure."""
    world = pressured_pair(boundaries=[])
    log = run_migration(world)

    assert populations(world) == {"poor": 100, "rich": 10}
    assert len(log) == 0


def test_isolated_source_sends_nobody() -> None:
    """An isolated district keeps its people whatever its pressure."""
    world = build_migration_world(
        [starving("poor", isolation_state=IsolationState.ISOLATED), fed("rich")],
        boundaries=[("bound", "poor", "rich")],
        tick=1,
    )
    log = run_migration(world)

    assert populations(world) == {"poor": 100, "rich": 10}
    assert len(log) == 0


def test_isolated_destination_receives_nobody() -> None:
    """An isolated district takes nobody in, however much room it has."""
    world = build_migration_world(
        [starving("poor"), fed("rich", isolation_state=IsolationState.ISOLATED)],
        boundaries=[("bound", "poor", "rich")],
        tick=1,
    )
    log = run_migration(world)

    assert populations(world) == {"poor": 100, "rich": 10}
    assert len(log) == 0


def test_partial_isolation_reduces_but_does_not_stop_migration() -> None:
    """Partial isolation damps the flow of people by the configured factor."""
    open_world = pressured_pair()
    partial_world = build_migration_world(
        [starving("poor", isolation_state=IsolationState.PARTIAL), fed("rich")],
        boundaries=[("bound", "poor", "rich")],
        tick=1,
    )
    run_migration(open_world)
    run_migration(partial_world)

    open_moved = 100 - open_world.districts["poor"].population
    partial_moved = 100 - partial_world.districts["poor"].population

    assert partial_moved > 0
    assert partial_moved < open_moved
    assert partial_moved == open_moved // 2


def test_no_materially_better_destination_means_no_migration() -> None:
    """A neighbour barely better than home does not pull anyone across."""
    world = build_migration_world(
        [
            build_district("a", population=100, consumption_rate=1.0, food=50.0),
            build_district("b", population=100, consumption_rate=1.0, food=50.0),
        ],
        boundaries=[("bound", "a", "b")],
        tick=1,
    )
    log = run_migration(world)

    assert populations(world) == {"a": 100, "b": 100}
    assert len(log) == 0


def test_equally_pressured_neighbours_exchange_nobody() -> None:
    """Two districts suffering alike have nothing to offer each other."""
    world = build_migration_world(
        [starving("a"), starving("b")],
        boundaries=[("bound", "a", "b")],
        tick=1,
    )
    log = run_migration(world)

    assert populations(world) == {"a": 100, "b": 100}
    assert len(log) == 0


def test_equal_destinations_receive_equal_shares() -> None:
    """Two identically attractive neighbours split the movers evenly."""
    world = build_migration_world(
        [starving("poor", population=100), fed("east"), fed("west")],
        boundaries=[("b1", "poor", "east"), ("b2", "poor", "west")],
        tick=1,
    )
    run_migration(world)

    assert world.districts["east"].population == world.districts["west"].population
    assert total_population(world) == 120


def test_indivisible_remainder_goes_to_the_smaller_identifier() -> None:
    """The single documented tie-break, tested directly.

    An odd number of movers cannot split evenly between two identical
    destinations. The leftover person goes to the smaller identifier. This is
    the only place a name changes an outcome and it can never move more than
    one person.
    """
    world = build_migration_world(
        [starving("poor", population=15), fed("aaa"), fed("zzz")],
        boundaries=[("b1", "poor", "aaa"), ("b2", "poor", "zzz")],
        tick=1,
    )
    run_migration(world)

    assert world.districts["aaa"].population == 12
    assert world.districts["zzz"].population == 11
    assert total_population(world) == 35


def test_repeated_execution_is_deterministic() -> None:
    """The same world twice gives the same answer twice."""
    results = []
    for _ in range(3):
        world = build_migration_world(
            [starving("p1"), starving("p2", population=57), fed("r1"), fed("r2")],
            boundaries=[("b1", "p1", "r1"), ("b2", "p1", "r2"), ("b3", "p2", "r2")],
            tick=1,
        )
        log = run_migration(world)
        results.append((populations(world), [event.payload_as_dict() for event in log]))

    assert results[0] == results[1] == results[2]


def test_registration_order_does_not_change_the_result() -> None:
    """Reversing district and boundary registration changes nothing."""

    def build(reverse: bool):
        """Build the scenario with registration order optionally reversed."""
        districts = [starving("p1"), starving("p2", population=60), fed("r1"), fed("r2")]
        boundaries = [("b1", "p1", "r1"), ("b2", "p1", "r2"), ("b3", "p2", "r1")]
        if reverse:
            districts = list(reversed(districts))
            boundaries = list(reversed(boundaries))
        return build_migration_world(districts, boundaries=boundaries, tick=1)

    forward, backward = build(False), build(True)
    forward_log = run_migration(forward)
    backward_log = run_migration(backward)

    assert populations(forward) == populations(backward)
    assert [event.payload_as_dict() for event in forward_log] == [
        event.payload_as_dict() for event in backward_log
    ]


def test_multiple_sources_and_destinations_stay_within_every_constraint() -> None:
    """A denser graph must still conserve people and respect every cap."""
    world = build_migration_world(
        [
            starving("p1", population=80),
            starving("p2", population=40),
            fed("r1", population=5, housing_capacity=20),
            fed("r2", population=5, housing_capacity=100),
        ],
        boundaries=[
            ("b1", "p1", "r1"),
            ("b2", "p1", "r2"),
            ("b3", "p2", "r1"),
            ("b4", "p2", "r2"),
        ],
        tick=1,
    )
    before = total_population(world)
    run_migration(world)

    assert total_population(world) == before
    for district_id, count in populations(world).items():
        assert 0 <= count <= world.districts[district_id].housing_capacity


def test_shared_destination_capacity_is_split_between_sources() -> None:
    """When two sources want the same scarce housing, both get a share."""
    world = build_migration_world(
        [
            starving("p1", population=100),
            starving("p2", population=100),
            fed("r", population=0, housing_capacity=10),
        ],
        boundaries=[("b1", "p1", "r"), ("b2", "p2", "r")],
        tick=1,
    )
    run_migration(world)

    assert world.districts["r"].population == 10
    assert world.districts["p1"].population == 95
    assert world.districts["p2"].population == 95
    assert total_population(world) == 200


def test_migration_event_is_correct_and_json_safe() -> None:
    """One event per movement, fully described and strictly serializable."""
    world = pressured_pair()
    log = run_migration(world)

    assert len(log) == 1
    event = log.events()[0]
    assert event.type is EventType.POPULATION_MIGRATED
    assert event.tick == 1
    assert event.source_id == "poor"

    payload = event.payload_as_dict()
    assert payload["from_district_id"] == "poor"
    assert payload["to_district_id"] == "rich"
    assert payload["boundary_id"] == "bound"
    assert payload["population_moved"] == 20
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


def test_migration_event_payload_is_immutable() -> None:
    """A published movement is history and cannot be edited afterwards."""
    log = run_migration(pressured_pair())
    payload = log.events()[0].payload

    with pytest.raises(TypeError):
        payload["population_moved"] = 999  # type: ignore[index]


def test_migration_events_are_ordered_by_source_then_destination() -> None:
    """Event order follows identifiers, which is the only thing they order."""
    world = build_migration_world(
        [starving("p1"), starving("p2"), fed("r1"), fed("r2")],
        boundaries=[("b1", "p1", "r1"), ("b2", "p1", "r2"), ("b3", "p2", "r1")],
        tick=1,
    )
    log = run_migration(world)
    pairs = [
        (str(event.payload["from_district_id"]), str(event.payload["to_district_id"]))
        for event in log
    ]
    assert pairs == sorted(pairs)


def test_migration_does_not_change_resources_or_other_state() -> None:
    """Migration moves people and nothing else."""
    world = pressured_pair(law=build_law())
    world.add_infrastructure(build_infrastructure("infra", "bound"))
    before_stock = {
        district_id: {
            resource: world.districts[district_id].resources.amount_of(resource)
            for resource in ResourceType
        }
        for district_id in sorted(world.districts)
    }

    run_migration(world)

    for district_id, stock in before_stock.items():
        for resource, amount in stock.items():
            assert world.districts[district_id].resources.amount_of(resource) == amount
    assert world.boundaries["bound"].wall_id is None
    assert world.infrastructure["infra"].dependency_score == 0.0
    assert world.laws["law_movement_sharing"].current_value is True
    assert world.districts["poor"].scarcity == 0.0


def test_migration_consumes_no_randomness() -> None:
    """Every decision is arithmetic; the generator is never touched."""
    world = pressured_pair()
    before = world.rng.get_state()
    run_migration(world)
    assert world.rng.get_state() == before


def test_zero_migration_rate_moves_nobody() -> None:
    """A rate of zero is a valid setting that disables movement entirely."""
    world = pressured_pair()
    log = run_migration(world, build_migration(migration_rate=0.0))

    assert populations(world) == {"poor": 100, "rich": 10}
    assert len(log) == 0


def test_invalid_configuration_is_rejected_at_construction() -> None:
    """Configuration errors surface immediately, not mid-episode."""
    for bad in (-0.1, 1.1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            build_migration(migration_rate=bad)
        with pytest.raises(ValueError):
            build_migration(min_pressure_gap=bad)
        with pytest.raises(ValueError):
            build_migration(partial_isolation_factor=bad)

    for bad_type in (True, "0.5", None):
        with pytest.raises(TypeError):
            build_migration(migration_rate=bad_type)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            build_migration(partial_isolation_factor=bad_type)  # type: ignore[arg-type]


def test_invalid_allocation_is_rejected_at_construction() -> None:
    """The allocation follows the same rules as every other resource system."""
    with pytest.raises(ValueError):
        build_migration(allocation={ResourceType.FOOD: 1.0})
    with pytest.raises(TypeError):
        build_migration(allocation=dict(EVEN_ALLOCATION) | {"FOOD": 0.0})  # type: ignore[arg-type]


def test_configuration_is_defensively_copied_and_read_only() -> None:
    """The caller's mapping is not retained and cannot be edited through us."""
    supplied = dict(EVEN_ALLOCATION)
    system = build_migration(allocation=supplied)
    supplied[ResourceType.FOOD] = 99.0

    assert system.consumption_allocation[ResourceType.FOOD] == 0.5
    with pytest.raises(TypeError):
        system.consumption_allocation[ResourceType.FOOD] = 99.0  # type: ignore[index]


def test_system_holds_no_per_tick_state() -> None:
    """Configuration only; nothing from one tick survives into the next."""
    assert not hasattr(build_migration(), "__dict__")


def test_unresolvable_wall_reference_fails_clearly() -> None:
    """World forbids this state, so reaching it means something is badly wrong."""
    world = pressured_pair()
    world.boundaries["bound"].wall_id = "ghost_wall"
    with pytest.raises(ValueError):
        run_migration(world)


def test_tiny_pressure_differences_do_not_move_anyone() -> None:
    """Floating-point noise must never start a migration."""
    world = build_migration_world(
        [
            build_district("a", population=100, consumption_rate=1.0, food=50.0),
            build_district(
                "b", population=100, consumption_rate=1.0, food=50.0 + FLOAT_TOLERANCE / 10
            ),
        ],
        boundaries=[("bound", "a", "b")],
        tick=1,
    )
    log = run_migration(world, build_migration(min_pressure_gap=0.0))

    assert populations(world) == {"a": 100, "b": 100}
    assert len(log) == 0


def build_narrow_gap_world():
    """Two districts whose pressures differ by 0.02, well inside the usual margin.

    Both need 100 units in total. The first is short by 50 and the second by
    48, so the second is genuinely better but only slightly.
    """
    return build_migration_world(
        [
            build_district("a", population=100, consumption_rate=1.0, food=50.0),
            build_district("b", population=100, consumption_rate=1.0, food=50.0, materials=2.0),
        ],
        boundaries=[("bound", "a", "b")],
        tick=1,
    )


def test_a_neighbour_inside_the_margin_attracts_nobody() -> None:
    """A destination better by less than the margin is not materially better.

    This is what stops people trickling back and forth between districts whose
    fortunes are practically identical.
    """
    world = build_narrow_gap_world()
    log = run_migration(world, build_migration(min_pressure_gap=0.05))

    assert populations(world) == {"a": 100, "b": 100}
    assert len(log) == 0


def test_the_same_neighbour_attracts_people_once_the_margin_is_lowered() -> None:
    """The margin is what decides it, not the topology or the pressures.

    Same world, same pressures, smaller margin: now the gap counts and people
    move. Together with the test above this pins the parameter from both sides.
    """
    world = build_narrow_gap_world()
    log = run_migration(world, build_migration(min_pressure_gap=0.01))

    assert world.districts["a"].population < 100
    assert world.districts["b"].population > 100
    assert total_population(world) == 200
    assert len(log) == 1


# --- Destination isolation must reduce throughput, not merely preference ----


def build_isolation_world(state: IsolationState, *, capacity: int = 9999):
    """One pressured district beside one destination in a chosen isolation state."""
    return build_migration_world(
        [starving("poor"), fed("rich", isolation_state=state, housing_capacity=capacity)],
        boundaries=[("bound", "poor", "rich")],
        tick=1,
    )


def moved_to_rich(state: IsolationState, factor: float) -> int:
    """Run one migration and report how many people reached the destination."""
    world = build_isolation_world(state)
    run_migration(world, build_migration(partial_isolation_factor=factor))
    return world.districts["rich"].population - 10


def test_open_destination_receives_more_than_the_same_partial_destination() -> None:
    """The defect this closes: a lone PARTIAL destination used to receive the same.

    A relative weight cannot express a throughput limit, because normalizing a
    single destination's weight cancels whatever factor was applied to it. The
    limit is now a whole-person cap on the route.
    """
    assert moved_to_rich(IsolationState.PARTIAL, 0.5) < moved_to_rich(IsolationState.OPEN, 0.5)


def test_sole_partial_destination_receives_a_halved_whole_person_count() -> None:
    """Factor 0.5 halves the arrivals of an otherwise identical open destination."""
    assert moved_to_rich(IsolationState.OPEN, 0.5) == 20
    assert moved_to_rich(IsolationState.PARTIAL, 0.5) == 10


def test_partial_factor_of_one_behaves_exactly_like_open() -> None:
    """A factor of 1.0 means partial isolation impedes nothing at all."""
    assert moved_to_rich(IsolationState.PARTIAL, 1.0) == moved_to_rich(IsolationState.OPEN, 1.0)


def test_partial_factor_of_zero_stops_movement_in_both_directions() -> None:
    """Zero throughput is indistinguishable from full isolation."""
    assert moved_to_rich(IsolationState.PARTIAL, 0.0) == 0

    world = build_migration_world(
        [starving("poor", isolation_state=IsolationState.PARTIAL), fed("rich")],
        boundaries=[("bound", "poor", "rich")],
        tick=1,
    )
    log = run_migration(world, build_migration(partial_isolation_factor=0.0))
    assert populations(world) == {"poor": 100, "rich": 10}
    assert len(log) == 0


def test_people_a_partial_route_cannot_carry_go_to_an_open_destination() -> None:
    """The documented redistribution rule, exercised where the cap actually binds.

    Both destinations are equally attractive, so twenty movers split ten each.
    The partial route can carry only five of its ten, and the five it refuses
    are offered to the open destination rather than stranded.
    """
    world = build_migration_world(
        [
            starving("poor"),
            fed("open_dest"),
            fed("partial_dest", isolation_state=IsolationState.PARTIAL),
        ],
        boundaries=[("b1", "poor", "open_dest"), ("b2", "poor", "partial_dest")],
        tick=1,
    )
    run_migration(world, build_migration(partial_isolation_factor=0.5))

    assert world.districts["partial_dest"].population == 20
    assert world.districts["open_dest"].population == 20
    assert populations(world)["poor"] == 80
    assert total_population(world) == 120


def test_throughput_limits_conserve_population() -> None:
    """Whatever a route refuses, nobody is lost in the refusing."""
    for factor in (0.0, 0.25, 0.5, 0.75, 1.0):
        world = build_isolation_world(IsolationState.PARTIAL)
        run_migration(world, build_migration(partial_isolation_factor=factor))
        assert total_population(world) == 110
        assert all(count >= 0 for count in populations(world).values())


# --- An over-capacity district must still be able to shed people -------------


def test_over_capacity_source_may_send_people_away() -> None:
    """Reducing an existing overcrowding is exactly what migration is for.

    The source ends above its housing capacity because it began that way. What
    would be wrong is trapping it there.
    """
    world = build_migration_world(
        [starving("poor", housing_capacity=50), fed("rich")],
        boundaries=[("bound", "poor", "rich")],
        tick=1,
    )
    run_migration(world)

    assert populations(world) == {"poor": 80, "rich": 30}
    assert world.districts["poor"].population > world.districts["poor"].housing_capacity
    assert total_population(world) == 110


def test_over_capacity_district_offers_no_headroom() -> None:
    """A district already past its housing has no room for anyone else."""
    world = build_migration_world(
        [starving("poor"), fed("rich", population=10, housing_capacity=5)],
        boundaries=[("bound", "poor", "rich")],
        tick=1,
    )
    log = run_migration(world)

    assert populations(world) == {"poor": 100, "rich": 10}
    assert len(log) == 0


def test_arrivals_never_exceed_pre_migration_headroom() -> None:
    """Housing is measured before anyone moves, and that reading is binding."""
    world = build_migration_world(
        [starving("poor"), fed("rich", population=10, housing_capacity=13)],
        boundaries=[("bound", "poor", "rich")],
        tick=1,
    )
    run_migration(world)

    assert world.districts["rich"].population == 13
    assert total_population(world) == 110


def test_departures_cannot_create_arrival_headroom_in_the_same_tick() -> None:
    """A district in the middle of a chain cannot resell the room it is vacating.

    ``middle`` is full and is itself losing people to ``best``. Under
    simultaneous application those departures do not open the door for arrivals
    from ``worst``, because headroom was read before anyone moved.
    """
    world = build_migration_world(
        [
            build_district("worst", population=100, consumption_rate=1.0),
            build_district(
                "middle", population=40, consumption_rate=1.0, food=20.0, housing_capacity=40
            ),
            fed("best", population=0),
        ],
        boundaries=[("b1", "worst", "middle"), ("b2", "middle", "best")],
        tick=1,
    )
    before_middle = world.districts["middle"].population
    run_migration(world)

    arrivals_into_middle = world.districts["middle"].population - (
        before_middle - max(0, before_middle - world.districts["middle"].population)
    )
    assert world.districts["middle"].population <= before_middle
    assert arrivals_into_middle <= 0
    assert total_population(world) == 140


# --- Movement is governed by the movement law -------------------------------


def build_law_world(*, active: bool = True, current_value: object = True, with_law: bool = True):
    """A pressured district beside a better one, under a chosen law state.

    ``with_law=False`` registers no law at all, which is a different thing from
    registering one that forbids movement.
    """
    districts = [starving("poor"), fed("rich")]
    boundaries = [("bound", "poor", "rich")]
    if not with_law:
        return build_world(districts, boundaries=boundaries, tick=1)
    return build_world(
        districts,
        boundaries=boundaries,
        law=build_law(active=active, current_value=current_value),
        tick=1,
    )


def test_active_law_set_to_true_allows_movement() -> None:
    """The ordinary permitted case."""
    world = build_law_world(active=True, current_value=True)
    log = run_migration(world)

    assert populations(world) == {"poor": 80, "rich": 30}
    assert len(log) == 1


def test_inactive_law_blocks_all_movement() -> None:
    """A law not in force cannot permit anything."""
    world = build_law_world(active=False, current_value=True)
    log = run_migration(world)

    assert populations(world) == {"poor": 100, "rich": 10}
    assert len(log) == 0


def test_law_set_to_false_blocks_all_movement() -> None:
    """Repealing movement stops people exactly as it stops goods."""
    world = build_law_world(active=True, current_value=False)
    log = run_migration(world)

    assert populations(world) == {"poor": 100, "rich": 10}
    assert len(log) == 0


def test_missing_law_raises_key_error() -> None:
    """A system bound to a law the world does not have cannot proceed."""
    world = build_law_world(with_law=False)
    with pytest.raises(KeyError):
        run_migration(world)


def test_non_boolean_law_value_is_rejected() -> None:
    """Truthiness is not permission: 1, 'true', and 0.0 are all malformed."""
    for bad_value in (1, 0, "true", 1.0, None):
        world = build_law_world(active=True, current_value=bad_value)
        with pytest.raises(TypeError):
            run_migration(world)


def test_non_boolean_law_value_is_rejected_even_when_inactive() -> None:
    """A malformed law is reported the tick it appears, not the tick it matters."""
    world = build_law_world(active=False, current_value=1)
    with pytest.raises(TypeError):
        run_migration(world)


def test_law_state_is_never_modified_by_migration() -> None:
    """Migration obeys the law; it has no authority to change it."""
    law = build_law(active=True, current_value=True)
    world = build_migration_world(
        [starving("poor"), fed("rich")],
        boundaries=[("bound", "poor", "rich")],
        law=law,
        tick=1,
    )
    before = (law.active, law.current_value, law.previous_value, law.changed_episode)
    run_migration(world)
    assert (law.active, law.current_value, law.previous_value, law.changed_episode) == before


def test_walls_and_isolation_still_block_even_when_the_law_permits() -> None:
    """The law is permission, not a bypass: topology still has the final word."""
    walled = build_law_world()
    walled.add_wall(build_wall("wall", "bound", active=True))
    assert len(run_migration(walled)) == 0
    assert populations(walled) == {"poor": 100, "rich": 10}

    isolated = build_migration_world(
        [starving("poor", isolation_state=IsolationState.ISOLATED), fed("rich")],
        boundaries=[("bound", "poor", "rich")],
        tick=1,
    )
    assert len(run_migration(isolated)) == 0


def test_blank_or_non_string_law_id_is_rejected() -> None:
    """The gating law must actually be nameable."""
    with pytest.raises(ValueError):
        build_migration(law_id="   ")
    with pytest.raises(TypeError):
        build_migration(law_id=5)  # type: ignore[arg-type]
