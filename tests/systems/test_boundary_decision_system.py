"""Tests for BoundaryDecisionSystem.

A wall is the first thing this engine builds that can never be undone, so most
of these tests are about what the system refuses to do: build on a threshold it
has not reached, touch a wall that already exists, act on an abandoned
district's history, reuse an identifier, or leave a half-built tick behind.
"""

import itertools
import json
import math
import random

import pytest
from systems_builders import (
    build_district,
    build_infrastructure,
    build_law,
    build_wall,
    build_world,
)

from living_diorama.entities import Boundary, District, IsolationState, ResourceType
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.systems import BoundaryDecisionSystem
from living_diorama.systems.boundary_decision_system import (
    DECISION_MODE,
    WALL_ID_PREFIX,
)


def run_decision(world, system=None) -> EventLog:
    """Run one boundary decision update and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    (system or BoundaryDecisionSystem()).update(world, bus)
    return log


def pressured(
    district_id: str,
    *,
    pressure: float = 0.0,
    population: int = 100,
) -> District:
    """Build a district with a chosen population and institutional pressure."""
    return build_district(district_id, population=population, institutional_pressure=pressure)


def two_district_world(
    *,
    pressure_a: float = 0.0,
    pressure_b: float = 0.0,
    population_a: int = 100,
    population_b: int = 100,
    tick: int = 1,
):
    """Build two districts joined by one wall-free boundary."""
    return build_world(
        [
            pressured("a", pressure=pressure_a, population=population_a),
            pressured("b", pressure=pressure_b, population=population_b),
        ],
        boundaries=[("bnd", "a", "b")],
        tick=tick,
    )


# --- 20. Constructor validation ---------------------------------------------


def test_default_configuration_is_accepted() -> None:
    """The documented default is usable without argument."""
    assert BoundaryDecisionSystem().build_threshold == 0.75


@pytest.mark.parametrize("threshold", [0.0, 0.25, 0.5, 1.0])
def test_valid_thresholds_are_accepted(threshold: float) -> None:
    """Any pressure in the unit interval is a legitimate threshold."""
    assert BoundaryDecisionSystem(build_threshold=threshold).build_threshold == threshold


@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), float("inf"), float("-inf")])
def test_invalid_thresholds_are_rejected(bad: float) -> None:
    """A threshold outside the interval could never be reached or never missed."""
    with pytest.raises(ValueError):
        BoundaryDecisionSystem(build_threshold=bad)


@pytest.mark.parametrize("bad", [True, False, "0.75", None])
def test_non_numeric_and_boolean_thresholds_are_rejected(bad: object) -> None:
    """Bool subclasses int, so True would silently mean a threshold of 1.0."""
    with pytest.raises(TypeError):
        BoundaryDecisionSystem(build_threshold=bad)


# --- 21. The build rule -----------------------------------------------------


def test_below_threshold_builds_nothing() -> None:
    """Pressure short of the threshold leaves the boundary open."""
    world = two_district_world(pressure_a=0.74)
    log = run_decision(world)

    assert len(world.walls) == 0
    assert world.boundaries["bnd"].wall_id is None
    assert len(log) == 0


def test_exactly_at_threshold_builds_a_wall() -> None:
    """Reaching the threshold is enough; the comparison is not strict."""
    world = two_district_world(pressure_a=0.75)
    log = run_decision(world)

    assert len(world.walls) == 1
    assert len(log) == 1


def test_above_threshold_builds_a_wall() -> None:
    """The ordinary case."""
    world = two_district_world(pressure_a=0.95)
    run_decision(world)
    assert len(world.walls) == 1


def test_either_endpoint_may_decide_alone() -> None:
    """Walls are built by whoever needs one; a calm neighbour has no veto."""
    from_a = two_district_world(pressure_a=0.9, pressure_b=0.0)
    from_b = two_district_world(pressure_a=0.0, pressure_b=0.9)

    run_decision(from_a)
    run_decision(from_b)

    assert len(from_a.walls) == 1
    assert len(from_b.walls) == 1


def test_boundary_pressure_is_the_larger_endpoint_not_the_average() -> None:
    """Averaging would let a comfortable district veto a desperate one.

    Pressures of 0.9 and 0.1 average to 0.5, which is below the threshold. The
    wall is built anyway, and the payload records 0.9 as the boundary pressure.
    """
    world = two_district_world(pressure_a=0.9, pressure_b=0.1)
    log = run_decision(world)

    assert len(world.walls) == 1
    assert log.events()[0].payload["boundary_pressure"] == 0.9


def test_neither_endpoint_reaching_the_threshold_builds_nothing() -> None:
    """Two moderately strained districts are still two open districts."""
    world = two_district_world(pressure_a=0.6, pressure_b=0.7)
    assert len(run_decision(world)) == 0
    assert len(world.walls) == 0


@pytest.mark.parametrize("threshold", [0.0, 0.3, 0.9, 1.0])
def test_the_configured_threshold_is_what_decides(threshold: float) -> None:
    """The rule follows configuration, not a constant baked into the code."""
    just_under = BoundaryDecisionSystem(build_threshold=threshold)
    world = two_district_world(pressure_a=threshold)
    run_decision(world, just_under)
    assert len(world.walls) == 1

    if threshold > 0.0:
        below = two_district_world(pressure_a=math.nextafter(threshold, -math.inf))
        run_decision(below, just_under)
        assert len(below.walls) == 0


# --- 22. Zero population ----------------------------------------------------


def test_a_boundary_between_two_empty_districts_builds_nothing() -> None:
    """With nobody on either side there is nobody to want a barrier."""
    world = two_district_world(pressure_a=1.0, pressure_b=1.0, population_a=0, population_b=0)
    log = run_decision(world)

    assert len(world.walls) == 0
    assert len(log) == 0


def test_one_populated_endpoint_can_still_decide() -> None:
    """An abandoned neighbour does not stop a populated district walling itself in."""
    world = two_district_world(pressure_a=0.9, pressure_b=1.0, population_b=0)
    log = run_decision(world)

    assert len(world.walls) == 1
    payload = log.events()[0].payload_as_dict()
    assert payload["active_endpoint_count"] == 1
    assert payload["district_b_institutional_pressure"] is None
    assert payload["boundary_pressure"] == 0.9


def test_an_empty_districts_pressure_cannot_justify_a_wall() -> None:
    """Historical pressure in an abandoned district is not a reason to build."""
    world = two_district_world(pressure_a=0.1, pressure_b=1.0, population_b=0)
    log = run_decision(world)

    assert len(world.walls) == 0
    assert len(log) == 0


@pytest.mark.parametrize("bad", [True, "0.9", float("nan"), 5.0])
def test_an_empty_districts_pressure_is_never_read_at_all(bad: object) -> None:
    """Corruption in an abandoned district cannot matter, because nothing reads it."""
    empty = pressured("b", population=0)
    empty.institutional_pressure = bad  # type: ignore[assignment]
    world = build_world(
        [pressured("a", pressure=0.9), empty], boundaries=[("bnd", "a", "b")], tick=1
    )
    log = run_decision(world)

    assert len(world.walls) == 1
    assert len(log) == 1
    assert world.districts["b"].institutional_pressure == bad or (
        isinstance(bad, float) and math.isnan(bad)
    )


# --- 23. Existing walls are never touched -----------------------------------


@pytest.mark.parametrize("active", [True, False])
@pytest.mark.parametrize("permanent", [True, False])
def test_a_boundary_with_a_wall_is_left_entirely_alone(active: bool, permanent: bool) -> None:
    """Construction only: an existing wall is not reinforced or reactivated."""
    world = two_district_world(pressure_a=1.0)
    world.add_wall(build_wall("w_old", "bnd", active=active, permanent=permanent))
    before = (
        world.walls["w_old"].active,
        world.walls["w_old"].permanent,
        world.walls["w_old"].integrity,
        world.walls["w_old"].dependency_score,
        world.walls["w_old"].built_tick,
    )

    log = run_decision(world)

    assert len(world.walls) == 1
    assert (
        world.walls["w_old"].active,
        world.walls["w_old"].permanent,
        world.walls["w_old"].integrity,
        world.walls["w_old"].dependency_score,
        world.walls["w_old"].built_tick,
    ) == before
    assert world.boundaries["bnd"].wall_id == "w_old"
    assert len(log) == 0


def test_running_twice_builds_only_once() -> None:
    """The second tick finds the boundary already walled and does nothing."""
    world = two_district_world(pressure_a=1.0)
    system = BoundaryDecisionSystem()

    first = run_decision(world, system)
    second = run_decision(world, system)

    assert len(first) == 1
    assert len(second) == 0
    assert len(world.walls) == 1


# --- 24. Wall creation and permanence ---------------------------------------


def test_a_new_wall_has_the_required_shape() -> None:
    """Every wall this system builds is active, permanent, and undamaged."""
    world = two_district_world(pressure_a=0.9, tick=42)
    run_decision(world)

    wall = world.walls[f"{WALL_ID_PREFIX}bnd"]
    assert wall.boundary_id == "bnd"
    assert wall.created_tick == 42
    assert wall.built_tick == 42
    assert wall.integrity == 1.0
    assert wall.active is True
    assert wall.permanent is True
    assert wall.dependency_score == 0.0
    assert wall.transport_dependency == 0.0
    assert wall.resource_dependency == 0.0


def test_the_wall_is_registered_through_the_world() -> None:
    """Registration goes through World, which maintains the back-reference."""
    world = two_district_world(pressure_a=0.9)
    run_decision(world)

    wall_id = f"{WALL_ID_PREFIX}bnd"
    assert world.get_wall(wall_id) is world.walls[wall_id]
    assert world.has_entity(wall_id)
    assert world.boundaries["bnd"].wall_id == wall_id
    assert world.get_boundary("bnd").wall_id == wall_id


def test_the_wall_survives_a_law_being_repealed() -> None:
    """The scar outlives the rule: this system never consults a law at all."""
    world = build_world(
        [pressured("a", pressure=0.9), pressured("b")],
        boundaries=[("bnd", "a", "b")],
        law=build_law(active=True, current_value=True),
        tick=1,
    )
    run_decision(world)
    assert len(world.walls) == 1

    world.laws["law_movement_sharing"].active = False
    world.laws["law_movement_sharing"].current_value = False
    world.districts["a"].institutional_pressure = 0.0

    log = run_decision(world)
    assert len(world.walls) == 1
    assert world.walls[f"{WALL_ID_PREFIX}bnd"].active is True
    assert world.walls[f"{WALL_ID_PREFIX}bnd"].permanent is True
    assert len(log) == 0


def test_falling_pressure_never_removes_a_wall() -> None:
    """Relief cannot unbuild what a crisis built."""
    world = two_district_world(pressure_a=1.0)
    system = BoundaryDecisionSystem()
    run_decision(world, system)

    world.districts["a"].institutional_pressure = 0.0
    world.districts["b"].institutional_pressure = 0.0
    run_decision(world, system)

    assert len(world.walls) == 1
    assert world.walls[f"{WALL_ID_PREFIX}bnd"].active is True


# --- 25. Identifier determinism ---------------------------------------------


def test_wall_identifiers_are_derived_from_the_boundary() -> None:
    """The same world always names the same scar the same way."""
    world = two_district_world(pressure_a=0.9)
    run_decision(world)
    assert set(world.walls) == {f"{WALL_ID_PREFIX}bnd"}


def test_identical_worlds_produce_identical_wall_identifiers() -> None:
    """No counter, clock, hash, or random source is involved."""
    identifiers = []
    for _ in range(3):
        world = two_district_world(pressure_a=0.9)
        run_decision(world)
        identifiers.append(sorted(world.walls))
    assert identifiers[0] == identifiers[1] == identifiers[2]


def test_a_taken_wall_identifier_is_reported_rather_than_worked_around() -> None:
    """Suffixing would produce a differently-named scar for the same boundary."""
    world = build_world(
        [
            pressured("a", pressure=0.9),
            pressured("b"),
            pressured(f"{WALL_ID_PREFIX}bnd"),
        ],
        boundaries=[("bnd", "a", "b")],
        tick=1,
    )
    with pytest.raises(ValueError):
        run_decision(world)

    assert len(world.walls) == 0
    assert world.boundaries["bnd"].wall_id is None


def test_a_taken_identifier_aborts_before_any_other_wall_is_built() -> None:
    """One naming collision leaves the whole tick unbuilt."""
    world = build_world(
        [
            pressured("a", pressure=0.9),
            pressured("b", pressure=0.9),
            pressured("c", pressure=0.9),
            pressured(f"{WALL_ID_PREFIX}zzz"),
        ],
        boundaries=[("aaa", "a", "b"), ("zzz", "b", "c")],
        tick=1,
    )
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)

    with pytest.raises(ValueError):
        BoundaryDecisionSystem().update(world, bus)

    assert len(world.walls) == 0
    assert world.boundaries["aaa"].wall_id is None
    assert world.boundaries["zzz"].wall_id is None
    assert len(log) == 0


# --- 26. Multiple boundaries and atomicity ----------------------------------


def build_three_boundary_world(*, pressures: tuple[float, float, float], tick: int = 1):
    """Build three districts joined pairwise, each with a chosen pressure."""
    pressure_a, pressure_b, pressure_c = pressures
    return build_world(
        [
            pressured("a", pressure=pressure_a),
            pressured("b", pressure=pressure_b),
            pressured("c", pressure=pressure_c),
        ],
        boundaries=[("ab", "a", "b"), ("bc", "b", "c"), ("ca", "c", "a")],
        tick=tick,
    )


def test_several_boundaries_may_qualify_in_one_tick() -> None:
    """Each qualifying boundary gets its own wall and its own event."""
    world = build_three_boundary_world(pressures=(0.9, 0.9, 0.9))
    log = run_decision(world)

    assert len(world.walls) == 3
    assert len(log) == 3
    for boundary_id in ("ab", "bc", "ca"):
        assert world.boundaries[boundary_id].wall_id == f"{WALL_ID_PREFIX}{boundary_id}"


def test_only_qualifying_boundaries_get_walls() -> None:
    """A boundary between two calm districts is left open."""
    world = build_three_boundary_world(pressures=(0.9, 0.1, 0.1))
    run_decision(world)

    # 'a' is over threshold, so both boundaries touching it qualify; 'bc' does not.
    assert set(world.walls) == {f"{WALL_ID_PREFIX}ab", f"{WALL_ID_PREFIX}ca"}
    assert world.boundaries["bc"].wall_id is None


def test_walls_are_built_in_sorted_boundary_order() -> None:
    """Traversal order is fixed by identifier, and shows up in the event order."""
    world = build_world(
        [
            pressured("a", pressure=0.9),
            pressured("b", pressure=0.9),
            pressured("c", pressure=0.9),
        ],
        boundaries=[("zulu", "a", "b"), ("alpha", "b", "c"), ("mike", "c", "a")],
        tick=1,
    )
    log = run_decision(world)

    assert [str(event.payload["boundary_id"]) for event in log] == ["alpha", "mike", "zulu"]


def test_registration_order_does_not_change_the_outcome() -> None:
    """Insertion order is not part of the simulation's meaning."""

    def build(reverse: bool):
        """Build the same world with registration order optionally reversed."""
        districts = [
            pressured("a", pressure=0.9),
            pressured("b", pressure=0.2),
            pressured("c", pressure=0.8),
        ]
        boundaries = [("ab", "a", "b"), ("bc", "b", "c"), ("ca", "c", "a")]
        if reverse:
            districts = list(reversed(districts))
            boundaries = list(reversed(boundaries))
        return build_world(districts, boundaries=boundaries, tick=1)

    forward, backward = build(False), build(True)
    forward_log = run_decision(forward)
    backward_log = run_decision(backward)

    assert sorted(forward.walls) == sorted(backward.walls)
    assert [event.payload_as_dict() for event in forward_log] == [
        event.payload_as_dict() for event in backward_log
    ]


def test_renaming_districts_does_not_change_which_boundaries_qualify() -> None:
    """Identifiers order traversal; they never decide anything."""

    def build(names: tuple[str, str]):
        """Build one boundary under a chosen pair of district names."""
        first, second = names
        return build_world(
            [pressured(first, pressure=0.9), pressured(second, pressure=0.1)],
            boundaries=[("bnd", first, second)],
            tick=1,
        )

    original = build(("aaa", "zzz"))
    renamed = build(("zzz", "aaa"))
    run_decision(original)
    run_decision(renamed)

    assert len(original.walls) == len(renamed.walls) == 1
    assert original.walls[f"{WALL_ID_PREFIX}bnd"].boundary_id == "bnd"
    assert renamed.walls[f"{WALL_ID_PREFIX}bnd"].boundary_id == "bnd"


# --- 27. Corrupted stored state ---------------------------------------------

CORRUPTED_PRESSURES = [True, False, "0.5", float("nan"), float("inf"), -0.1, 1.1]
"""Stored pressures that must never justify a permanent wall.

The booleans and the numeric string are the dangerous ones: each converts
silently into an ordinary float inside the permitted interval, so a validator
shown the converted value would have nothing to object to.
"""

CORRUPTED_POPULATIONS = [True, False, 1.5, "10", -1]
"""Stored populations that must never be read as a district's size."""


def expected_pressure_error(bad: object) -> type[Exception]:
    """Return the precise exception a corrupted pressure must raise."""
    if type(bad) is bool or not isinstance(bad, int | float):
        return TypeError
    return ValueError


@pytest.mark.parametrize("bad", CORRUPTED_PRESSURES)
def test_corrupted_pressure_on_a_populated_district_fails_fast(bad: object) -> None:
    """Stored pressure is validated as found, never after a repairing conversion."""
    world = two_district_world(pressure_a=0.0)
    world.districts["a"].institutional_pressure = bad  # type: ignore[assignment]

    with pytest.raises(expected_pressure_error(bad)):
        run_decision(world)
    assert len(world.walls) == 0


@pytest.mark.parametrize("bad", CORRUPTED_POPULATIONS)
def test_corrupted_population_fails_fast(bad: object) -> None:
    """A population is checked as found; ``int(1.5)`` would repair the corruption."""
    world = two_district_world(pressure_a=0.9)
    world.districts["b"].population = bad  # type: ignore[assignment]

    expected = TypeError if type(bad) is bool or not isinstance(bad, int) else ValueError
    with pytest.raises(expected):
        run_decision(world)
    assert len(world.walls) == 0


@pytest.mark.parametrize("corrupted_first", [True, False])
def test_a_corrupted_district_leaves_no_wall_anywhere(corrupted_first: bool) -> None:
    """One bad district anywhere means no wall is built at all this tick.

    A wall is permanent, so a partially applied tick would leave a scar the
    recorded history could never explain.
    """
    healthy_left = pressured("m_left", pressure=0.9)
    healthy_right = pressured("m_right", pressure=0.9)
    corrupted = pressured("a_bad" if corrupted_first else "z_bad", pressure=0.0)
    corrupted.institutional_pressure = "0.9"  # type: ignore[assignment]

    world = build_world(
        [healthy_left, healthy_right, corrupted],
        boundaries=[("bnd_healthy", "m_left", "m_right"), ("bnd_bad", "m_right", corrupted.id)],
        tick=1,
    )
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)

    with pytest.raises(TypeError):
        BoundaryDecisionSystem().update(world, bus)

    assert len(world.walls) == 0
    assert world.boundaries["bnd_healthy"].wall_id is None
    assert world.boundaries["bnd_bad"].wall_id is None
    assert len(log) == 0


def test_a_dangling_boundary_wall_reference_fails_fast() -> None:
    """A broken reference is reported, never quietly repaired."""
    world = two_district_world(pressure_a=0.9)
    world.boundaries["bnd"].wall_id = "ghost"

    with pytest.raises(ValueError):
        run_decision(world)
    assert len(world.walls) == 0


def test_a_wall_pointing_at_the_wrong_boundary_fails_fast() -> None:
    """Back-references must agree in both directions."""
    world = build_world(
        [pressured("a", pressure=0.9), pressured("b"), pressured("c")],
        boundaries=[("bnd", "a", "b"), ("other", "b", "c")],
        tick=1,
    )
    world.add_wall(build_wall("w", "bnd", active=True))
    world.walls["w"].boundary_id = "other"

    with pytest.raises(ValueError):
        run_decision(world)


def test_a_boundary_referencing_an_unknown_district_fails_fast() -> None:
    """A dangling endpoint means the topology cannot be reasoned about."""
    world = two_district_world(pressure_a=0.9)
    world.boundaries["bnd"].district_b_id = "nowhere"

    with pytest.raises(ValueError):
        run_decision(world)
    assert len(world.walls) == 0


def test_topology_is_checked_before_any_decision_is_made() -> None:
    """A fault on one boundary stops a wall qualifying on another."""
    world = build_world(
        [
            pressured("a", pressure=0.9),
            pressured("b", pressure=0.9),
            pressured("c", pressure=0.9),
        ],
        boundaries=[("aaa", "a", "b"), ("zzz", "b", "c")],
        tick=1,
    )
    world.boundaries["zzz"].wall_id = "ghost"

    with pytest.raises(ValueError):
        run_decision(world)
    assert len(world.walls) == 0
    assert world.boundaries["aaa"].wall_id is None


# --- 28. Events -------------------------------------------------------------


def test_event_shape_and_ordering() -> None:
    """One event per wall, correctly typed and sourced, in sorted order."""
    world = build_three_boundary_world(pressures=(0.9, 0.9, 0.9), tick=8)
    log = run_decision(world)

    assert len(log) == 3
    for event in log:
        assert event.type is EventType.WALL_BUILT
        assert event.tick == 8
    assert [event.source_id for event in log] == [
        f"{WALL_ID_PREFIX}ab",
        f"{WALL_ID_PREFIX}bc",
        f"{WALL_ID_PREFIX}ca",
    ]


def test_event_payload_is_complete_and_json_safe() -> None:
    """The payload explains the decision using strict JSON primitives."""
    world = two_district_world(pressure_a=0.9, pressure_b=0.1, tick=4)
    payload = run_decision(world).events()[0].payload_as_dict()

    assert payload["wall_id"] == f"{WALL_ID_PREFIX}bnd"
    assert payload["boundary_id"] == "bnd"
    assert payload["district_a_id"] == "a"
    assert payload["district_b_id"] == "b"
    assert payload["district_a_population"] == 100
    assert payload["district_b_population"] == 100
    assert payload["district_a_institutional_pressure"] == 0.9
    assert payload["district_b_institutional_pressure"] == 0.1
    assert payload["active_endpoint_count"] == 2
    assert payload["boundary_pressure"] == 0.9
    assert payload["build_threshold"] == 0.75
    assert payload["decision_mode"] == DECISION_MODE
    assert payload["created_tick"] == 4
    assert payload["built_tick"] == 4
    assert payload["integrity"] == 1.0
    assert payload["active"] is True
    assert payload["permanent"] is True
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


def test_event_payload_is_immutable_after_construction() -> None:
    """A published construction is history and cannot be edited."""
    world = two_district_world(pressure_a=0.9)
    payload = run_decision(world).events()[0].payload

    with pytest.raises(TypeError):
        payload["boundary_pressure"] = 0.0  # type: ignore[index]


def test_event_payload_contains_only_primitives() -> None:
    """No enums, entities, sets, or dataclasses reach the recorded history."""
    world = two_district_world(pressure_a=0.9, pressure_b=1.0, population_b=0)
    for event in run_decision(world):
        for key, value in event.payload_as_dict().items():
            assert isinstance(key, str)
            assert value is None or isinstance(value, str | int | float)
            if isinstance(value, float):
                assert math.isfinite(value)


def test_no_events_when_nothing_is_built() -> None:
    """Silence is correct when no boundary qualifies."""
    assert len(run_decision(two_district_world(pressure_a=0.1))) == 0


# --- 29. Mutation isolation -------------------------------------------------


def test_nothing_but_walls_and_the_back_reference_changes() -> None:
    """Districts, laws, infrastructure, resources, and the tick are untouched."""
    district = build_district(
        "a",
        population=100,
        housing_capacity=50,
        production_rate=3.0,
        consumption_rate=2.0,
        food=7.0,
        scarcity=0.6,
        fear=0.7,
        trust=0.2,
        institutional_pressure=0.9,
    )
    world = build_world(
        [district, pressured("b", pressure=0.1)],
        boundaries=[("bnd", "a", "b")],
        law=build_law(),
        tick=5,
    )
    world.add_infrastructure(build_infrastructure("infra", "bnd"))

    before_pool = district.resources
    before_stock = {r: district.resources.amount_of(r) for r in ResourceType}
    rng_before = world.rng.get_state()

    run_decision(world)

    assert district.population == 100
    assert district.housing_capacity == 50
    assert district.production_rate == 3.0
    assert district.consumption_rate == 2.0
    assert district.scarcity == 0.6
    assert district.fear == 0.7
    assert district.trust == 0.2
    assert district.institutional_pressure == 0.9
    assert district.isolation_state is IsolationState.OPEN
    assert district.resources is before_pool
    for resource, amount in before_stock.items():
        assert district.resources.amount_of(resource) == amount

    assert world.tick == 5
    assert world.episode == 0
    assert world.rng.get_state() == rng_before
    assert world.laws["law_movement_sharing"].current_value is True
    assert world.infrastructure["infra"].dependency_score == 0.0
    assert world.infrastructure["infra"].capacity == 1.0
    assert world.boundaries["bnd"].district_a_id == "a"
    assert world.boundaries["bnd"].district_b_id == "b"
    assert len(world.walls) == 1


def test_the_system_does_not_advance_the_tick() -> None:
    """Tick progression belongs to SimulationLoop alone."""
    world = two_district_world(pressure_a=0.9, tick=11)
    run_decision(world)
    assert world.tick == 11


def test_the_system_uses_only_the_public_world_api() -> None:
    """Parsed from the code, so a docstring cannot be mistaken for a read.

    Laws and infrastructure are read, but only as places an identifier can
    live: a wall's name has to be free across the whole world, not merely
    inside the wall registry. The test below proves neither influences a
    decision.
    """
    import ast  # noqa: PLC0415
    import pathlib  # noqa: PLC0415

    import living_diorama.systems.boundary_decision_system as module  # noqa: PLC0415

    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "world"
    }
    assert attributes <= {
        "districts",
        "boundaries",
        "walls",
        "laws",
        "infrastructure",
        "tick",
        "has_entity",
        "get_entity",
        "add_wall",
    }
    assert not any(name.startswith("_") for name in attributes)


def test_law_and_infrastructure_state_cannot_change_a_decision() -> None:
    """Reading those registries for names must not let them influence outcomes.

    The identifier check walks every typed registry, so laws and infrastructure
    are touched. Varying everything about them that could plausibly matter --
    whether the law is active, what it says, how depended-upon the
    infrastructure is -- must leave the decision untouched.
    """

    def outcome(*, law_active: bool, law_value: bool, with_infrastructure: bool):
        """Build and run a world under one law and infrastructure configuration."""
        world = build_world(
            [pressured("a", pressure=0.9), pressured("b", pressure=0.1)],
            boundaries=[("bnd", "a", "b")],
            law=build_law(active=law_active, current_value=law_value),
            tick=2,
        )
        if with_infrastructure:
            world.add_infrastructure(build_infrastructure("infra", "bnd"))
        log = run_decision(world)
        return (
            sorted(world.walls),
            world.boundaries["bnd"].wall_id,
            [event.payload_as_dict() for event in log],
        )

    baseline = outcome(law_active=True, law_value=True, with_infrastructure=False)
    assert baseline[0] == [f"{WALL_ID_PREFIX}bnd"], "the baseline must actually build"
    assert outcome(law_active=False, law_value=False, with_infrastructure=False) == baseline
    assert outcome(law_active=True, law_value=False, with_infrastructure=True) == baseline
    assert outcome(law_active=False, law_value=True, with_infrastructure=True) == baseline


# --- 30. Determinism --------------------------------------------------------


def test_repeated_runs_on_identical_worlds_agree_exactly() -> None:
    """The same inputs give the same walls and the same events, every time."""
    results = []
    for _ in range(3):
        world = build_three_boundary_world(pressures=(0.9, 0.4, 0.8))
        log = run_decision(world)
        results.append(
            (
                sorted(world.walls),
                {b: world.boundaries[b].wall_id for b in sorted(world.boundaries)},
                [event.payload_as_dict() for event in log],
            )
        )
    assert results[0] == results[1] == results[2]


def test_rng_state_is_untouched() -> None:
    """This system decides nothing by chance."""
    world = two_district_world(pressure_a=0.9)
    before = world.rng.get_state()
    run_decision(world)
    assert world.rng.get_state() == before


def test_system_holds_no_per_tick_state() -> None:
    """Configuration only; nothing from one tick survives into the next."""
    assert not hasattr(BoundaryDecisionSystem(), "__dict__")


def test_empty_world_builds_nothing() -> None:
    """A world with no boundaries is valid and simply has nothing to decide."""
    assert len(run_decision(build_world([], tick=1))) == 0


def test_a_world_with_districts_but_no_boundaries_builds_nothing() -> None:
    """Walls stand on boundaries; without one there is nowhere to build."""
    world = build_world([pressured("a", pressure=1.0)], tick=1)
    assert len(run_decision(world)) == 0
    assert len(world.walls) == 0


# --- 31. Randomized adversarial sweep ---------------------------------------


def test_generated_worlds_never_violate_an_invariant() -> None:
    """A bounded seeded sweep over pressures, populations, and thresholds."""
    rng = random.Random(20260806)

    for _ in range(200):
        names = [f"d{index}" for index in range(rng.randint(2, 4))]
        districts = [
            build_district(
                name,
                population=rng.choice([0, 1, 50, 900]),
                institutional_pressure=round(rng.random(), 6),
            )
            for name in names
        ]
        boundaries = [
            (f"b_{first}_{second}", first, second)
            for first, second in itertools.combinations(names, 2)
            if rng.random() < 0.7
        ]
        threshold = rng.choice([0.0, 0.25, 0.75, 1.0])
        world = build_world(districts, boundaries=boundaries, tick=rng.randint(0, 50))

        pressures = {d.id: d.institutional_pressure for d in districts}
        populations = {d.id: d.population for d in districts}
        rng_before = world.rng.get_state()
        tick_before = world.tick

        log = run_decision(world, BoundaryDecisionSystem(build_threshold=threshold))

        assert world.rng.get_state() == rng_before
        assert world.tick == tick_before
        for district in districts:
            assert district.institutional_pressure == pressures[district.id]
            assert district.population == populations[district.id]

        assert len(world.walls) == len(log)
        for wall in world.walls.values():
            assert wall.active is True
            assert wall.permanent is True
            assert wall.integrity == 1.0
            assert wall.built_tick == world.tick
            assert world.boundaries[wall.boundary_id].wall_id == wall.id

        for boundary_id, boundary in world.boundaries.items():
            endpoints = (boundary.district_a_id, boundary.district_b_id)
            active = [pressures[e] for e in endpoints if populations[e] > 0]
            should_build = bool(active) and max(active) >= threshold
            assert (boundary.wall_id is not None) is should_build, boundary_id


def test_generated_worlds_are_order_invariant() -> None:
    """Reordering registration never changes which boundaries get walls."""
    rng = random.Random(4242)

    for _ in range(60):
        specs = [
            (f"d{index}", rng.choice([0, 10, 500]), round(rng.random(), 4)) for index in range(3)
        ]
        pairs = [("b_ab", "d0", "d1"), ("b_bc", "d1", "d2")]

        outcomes = []
        for order in (specs, list(reversed(specs))):
            districts = [
                build_district(name, population=population, institutional_pressure=pressure)
                for name, population, pressure in order
            ]
            world = build_world(districts, boundaries=pairs, tick=1)
            run_decision(world)
            outcomes.append({b: world.boundaries[b].wall_id for b in sorted(world.boundaries)})
        assert outcomes[0] == outcomes[1]


def test_a_boundary_cannot_be_built_on_twice_across_many_ticks() -> None:
    """Sustained pressure builds one wall, not one per tick."""
    world = two_district_world(pressure_a=1.0)
    system = BoundaryDecisionSystem()

    total_events = 0
    for _ in range(20):
        total_events += len(run_decision(world, system))

    assert total_events == 1
    assert len(world.walls) == 1


def test_a_district_may_be_walled_off_on_several_sides() -> None:
    """Nothing limits how many of a district's boundaries may carry walls."""
    world = build_world(
        [
            pressured("hub", pressure=0.95),
            pressured("n"),
            pressured("e"),
            pressured("s"),
        ],
        boundaries=[("bn", "hub", "n"), ("be", "hub", "e"), ("bs", "hub", "s")],
        tick=1,
    )
    log = run_decision(world)

    assert len(world.walls) == 3
    assert len(log) == 3
    assert all(
        world.boundaries[boundary_id].wall_id is not None for boundary_id in ("bn", "be", "bs")
    )


def test_duplicate_boundaries_between_the_same_pair_each_get_a_wall() -> None:
    """A wall belongs to a boundary, not to a pair of districts.

    Two parallel boundaries are two separate places a barrier can stand, and
    each is decided on its own. Collapsing them would require this system to
    reinterpret the topology, which is not its concern.
    """
    world = build_world(
        [pressured("a", pressure=0.9), pressured("b")],
        boundaries=[("first", "a", "b"), ("second", "a", "b")],
        tick=1,
    )
    run_decision(world)

    assert set(world.walls) == {f"{WALL_ID_PREFIX}first", f"{WALL_ID_PREFIX}second"}


def test_a_self_referential_boundary_cannot_be_constructed() -> None:
    """The entity layer already forbids it, so this system never sees one."""
    with pytest.raises(ValueError):
        Boundary(id="self", created_tick=0, district_a_id="a", district_b_id="a")


def test_building_one_wall_does_not_disturb_an_existing_wall_elsewhere() -> None:
    """A tick that builds must leave every wall already standing exactly as it was.

    The existing-wall tests above use worlds where nothing qualifies, so they
    only prove the system declines to build twice on one boundary. This one
    puts a qualifying wall-free boundary beside an already-walled one, which is
    the case where a stray write to the wall registry would actually land.
    """
    world = build_world(
        [
            pressured("a", pressure=0.9),
            pressured("b", pressure=0.9),
            pressured("c", pressure=0.9),
        ],
        boundaries=[("walled", "a", "b"), ("open", "b", "c")],
        tick=3,
    )
    world.add_wall(build_wall("w_old", "walled", active=False, permanent=False))
    existing = world.walls["w_old"]
    before = (
        existing.boundary_id,
        existing.created_tick,
        existing.built_tick,
        existing.integrity,
        existing.active,
        existing.permanent,
        existing.dependency_score,
        existing.transport_dependency,
        existing.resource_dependency,
    )

    log = run_decision(world)

    assert set(world.walls) == {"w_old", f"{WALL_ID_PREFIX}open"}, "the open boundary must build"
    assert len(log) == 1, "only the new wall may be announced"
    assert (
        existing.boundary_id,
        existing.created_tick,
        existing.built_tick,
        existing.integrity,
        existing.active,
        existing.permanent,
        existing.dependency_score,
        existing.transport_dependency,
        existing.resource_dependency,
    ) == before
    assert world.boundaries["walled"].wall_id == "w_old"


def test_an_existing_wall_survives_many_ticks_of_building_around_it() -> None:
    """Repeated qualifying ticks never accumulate changes on an untouched wall."""
    world = build_world(
        [
            pressured("hub", pressure=0.95),
            pressured("n"),
            pressured("e"),
            pressured("s"),
        ],
        boundaries=[("bn", "hub", "n"), ("be", "hub", "e"), ("bs", "hub", "s")],
        tick=1,
    )
    world.add_wall(build_wall("w_old", "bn", active=False, permanent=False))
    system = BoundaryDecisionSystem()

    for _ in range(5):
        run_decision(world, system)

    assert world.walls["w_old"].integrity == 1.0
    assert world.walls["w_old"].active is False
    assert world.walls["w_old"].permanent is False
    assert set(world.walls) == {"w_old", f"{WALL_ID_PREFIX}be", f"{WALL_ID_PREFIX}bs"}


# --- 32. Corrupted state that survived Candidate V1 --------------------------
#
# Every test below was written against a real defect found in independent
# review. Entities stay mutable after construction, so an invariant the
# constructor enforced once is not an invariant that still holds.


def full_snapshot(world) -> dict:
    """Capture everything a boundary decision must leave alone on failure."""
    return {
        "walls": {
            wall_id: (
                world.walls[wall_id].boundary_id,
                world.walls[wall_id].built_tick,
                world.walls[wall_id].integrity,
                world.walls[wall_id].active,
                world.walls[wall_id].permanent,
            )
            for wall_id in sorted(world.walls)
        },
        "wall_ids": {
            boundary_id: world.boundaries[boundary_id].wall_id
            for boundary_id in sorted(world.boundaries)
        },
        "districts": {
            district_id: (
                world.districts[district_id].population,
                world.districts[district_id].institutional_pressure,
            )
            for district_id in sorted(world.districts)
        },
        "tick": world.tick,
        "episode": world.episode,
        "rng": world.rng.get_state(),
    }


def assert_nothing_happened(world, before: dict, log: EventLog) -> None:
    """Assert a failed update left the world and the event history untouched."""
    assert full_snapshot(world) == before
    assert len(log) == 0


def run_expecting(world, error: type[Exception], system=None):
    """Run a decision expecting it to fail, and return the untouched log."""
    before = full_snapshot(world)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    with pytest.raises(error):
        (system or BoundaryDecisionSystem()).update(world, bus)
    assert_nothing_happened(world, before, log)
    return log


def build_qualifying_chain(names: tuple[str, ...], boundaries: list[tuple[str, str, str]]):
    """Build a world where every listed boundary would otherwise qualify."""
    return build_world(
        [pressured(name, pressure=1.0) for name in names],
        boundaries=boundaries,
        tick=5,
    )


# --- Self-loop --------------------------------------------------------------


def test_mutated_self_loop_boundary_is_rejected_atomically() -> None:
    """A boundary mutated to join a district to itself is not a boundary.

    The constructor forbids it, but ``Boundary`` stays mutable, so the invariant
    has to be checked again here. Left unchecked, the same district is read as
    both endpoints and counted twice, and a wall gets built across nothing.
    """
    world = two_district_world(pressure_a=1.0, tick=5)
    world.boundaries["bnd"].district_b_id = "a"

    run_expecting(world, ValueError)
    assert world.boundaries["bnd"].district_b_id == "a", "corruption is preserved"


def test_mutated_self_loop_on_the_other_endpoint_is_also_rejected() -> None:
    """The inverse mutation is the same defect and gets the same answer."""
    world = two_district_world(pressure_a=1.0, tick=5)
    world.boundaries["bnd"].district_a_id = "b"

    run_expecting(world, ValueError)


def test_a_self_loop_elsewhere_stops_a_healthy_boundary_building() -> None:
    """One malformed boundary aborts the whole tick, not just its own decision."""
    world = build_qualifying_chain(("a", "b", "c"), [("aaa", "a", "b"), ("zzz", "b", "c")])
    world.boundaries["zzz"].district_b_id = "b"

    run_expecting(world, ValueError)


# --- Noncanonical identifiers ------------------------------------------------


def corrupt_boundary_key(world, boundary_id: str, corrupted: str) -> None:
    """Rename a boundary's registry key, id, and index entry to a corrupt value.

    Private registries are reached into deliberately: this reproduces a world
    that has already been corrupted, which is the only way to reach the state
    under test. Production code never does this.
    """
    world._boundaries[corrupted] = world._boundaries.pop(boundary_id)
    world._boundaries[corrupted].id = corrupted
    world._entities[corrupted] = world._entities.pop(boundary_id)


@pytest.mark.parametrize("corrupted", ["zzz ", " zzz", "zzz\t", "  ", ""])
def test_noncanonical_boundary_id_is_rejected_before_any_wall(corrupted: str) -> None:
    """Key and id can agree and still both be wrong.

    Checking only that they match accepts an identifier carrying whitespace.
    ``Wall`` then normalizes it away during construction, so the wall points at
    a boundary that no longer resolves -- and registration fails only after
    earlier walls have already been applied.
    """
    world = build_qualifying_chain(("a", "b"), [("bnd", "a", "b")])
    corrupt_boundary_key(world, "bnd", corrupted)

    run_expecting(world, ValueError)


def test_noncanonical_boundary_id_first_does_not_partially_apply() -> None:
    """The corrupt boundary sorting first must still leave the others alone."""
    world = build_qualifying_chain(("a", "b", "c"), [("aaa", "a", "b"), ("zzz", "b", "c")])
    corrupt_boundary_key(world, "aaa", " aaa")

    run_expecting(world, ValueError)


def test_noncanonical_boundary_id_middle_does_not_partially_apply() -> None:
    """Nor when it sorts between two boundaries that would both qualify."""
    world = build_qualifying_chain(
        ("a", "b", "c", "d"),
        [("aaa", "a", "b"), ("mmm", "b", "c"), ("zzz", "c", "d")],
    )
    corrupt_boundary_key(world, "mmm", "mmm ")

    run_expecting(world, ValueError)


def test_noncanonical_boundary_id_last_does_not_partially_apply() -> None:
    """This is the exact shape that left a wall behind in Candidate V1.

    The first boundary was registered successfully, then the second failed
    inside ``World.add_wall`` because its normalized boundary no longer
    resolved. No event was published, but the world had already changed.
    """
    world = build_qualifying_chain(("a", "b", "c"), [("aaa", "a", "b"), ("zzz", "b", "c")])
    corrupt_boundary_key(world, "zzz", "zzz ")

    run_expecting(world, ValueError)
    assert "wall_aaa" not in world.walls, "the earlier wall must not survive the failure"


@pytest.mark.parametrize("field", ["district_a_id", "district_b_id"])
@pytest.mark.parametrize("corrupted", ["a ", " a", ""])
def test_noncanonical_endpoint_id_is_rejected(field: str, corrupted: str) -> None:
    """An endpoint reference carrying whitespace resolves to nothing."""
    world = build_qualifying_chain(("a", "b"), [("bnd", "a", "b")])
    setattr(world.boundaries["bnd"], field, corrupted)

    run_expecting(world, ValueError)


def test_noncanonical_district_id_is_rejected() -> None:
    """A district whose own id drifted from its key is refused."""
    world = build_qualifying_chain(("a", "b"), [("bnd", "a", "b")])
    world._districts["a "] = world._districts.pop("a")
    world._districts["a "].id = "a "
    world._entities["a "] = world._entities.pop("a")

    run_expecting(world, ValueError)


def test_noncanonical_existing_wall_id_is_rejected() -> None:
    """An existing wall named with whitespace corrupts the topology too."""
    world = build_qualifying_chain(("a", "b", "c"), [("aaa", "a", "b"), ("zzz", "b", "c")])
    world.add_wall(build_wall("w_old", "aaa", active=True))
    world._walls["w_old "] = world._walls.pop("w_old")
    world._walls["w_old "].id = "w_old "
    world._entities["w_old "] = world._entities.pop("w_old")
    world.boundaries["aaa"].wall_id = "w_old "

    run_expecting(world, ValueError)


def test_a_noncanonical_boundary_wall_reference_is_rejected() -> None:
    """A back-reference carrying whitespace names a wall that does not exist."""
    world = build_qualifying_chain(("a", "b"), [("bnd", "a", "b")])
    world.add_wall(build_wall("w_old", "bnd", active=True))
    world.boundaries["bnd"].wall_id = "w_old "

    run_expecting(world, ValueError)


@pytest.mark.parametrize("bad", [123, None, b"bnd"])
def test_an_identifier_of_the_wrong_type_is_rejected(bad: object) -> None:
    """Identifiers must be exactly ``str``; nothing else is coerced."""
    world = build_qualifying_chain(("a", "b"), [("bnd", "a", "b")])
    world.boundaries["bnd"].district_b_id = bad  # type: ignore[assignment]

    run_expecting(world, TypeError)


def test_noncanonical_candidate_id_is_rejected_before_application() -> None:
    """A candidate name inherits its boundary's name, so it inherits the fault."""
    world = build_qualifying_chain(("a", "b"), [("bnd", "a", "b")])
    corrupt_boundary_key(world, "bnd", "bnd ")

    run_expecting(world, ValueError)
    assert "wall_bnd" not in world.walls
    assert "wall_bnd " not in world.walls


# --- Aggregate index coherence ----------------------------------------------


def test_missing_aggregate_index_entry_is_rejected() -> None:
    """``has_entity`` cannot prove a name is free if the index has forgotten it.

    A district still present in ``world.districts`` but absent from the
    aggregate index let Candidate V1 build a wall under that district's name,
    leaving two entities claiming one identifier.
    """
    world = build_world(
        [
            pressured("a", pressure=1.0),
            pressured("b"),
            pressured(f"{WALL_ID_PREFIX}bnd"),
        ],
        boundaries=[("bnd", "a", "b")],
        tick=5,
    )
    del world._entities[f"{WALL_ID_PREFIX}bnd"]

    run_expecting(world, ValueError)
    assert f"{WALL_ID_PREFIX}bnd" in world.districts, "the district must still be there"
    assert f"{WALL_ID_PREFIX}bnd" not in world.walls


def test_missing_aggregate_entry_for_a_boundary_is_rejected() -> None:
    """The same drift, detected through the boundary registry."""
    world = build_qualifying_chain(("a", "b"), [("bnd", "a", "b")])
    del world._entities["bnd"]

    run_expecting(world, ValueError)


def test_missing_aggregate_entry_for_a_wall_is_rejected() -> None:
    """And through the wall registry."""
    world = build_qualifying_chain(("a", "b", "c"), [("aaa", "a", "b"), ("zzz", "b", "c")])
    world.add_wall(build_wall("w_old", "aaa", active=True))
    del world._entities["w_old"]

    run_expecting(world, ValueError)


def test_wrong_aggregate_index_object_is_rejected() -> None:
    """An index entry must resolve to the very object the registry holds."""
    world = build_qualifying_chain(("a", "b"), [("bnd", "a", "b")])
    world._entities["a"] = world._districts["b"]

    run_expecting(world, ValueError)


def test_duplicate_id_across_typed_registries_is_rejected() -> None:
    """One identifier may not name both a district and a law."""
    world = build_world(
        [pressured("a", pressure=1.0), pressured("b")],
        boundaries=[("bnd", "a", "b")],
        law=build_law(),
        tick=5,
    )
    law = world.laws["law_movement_sharing"]
    world._laws["a"] = law
    law.id = "a"

    run_expecting(world, ValueError)


def test_desynchronised_collision_cannot_overwrite_existing_entity() -> None:
    """The candidate name is checked against every registry, not just the index.

    Even with the aggregate index desynchronized, a district already holding the
    generated name must stop the build.
    """
    world = build_world(
        [
            pressured("a", pressure=1.0),
            pressured("b"),
            pressured(f"{WALL_ID_PREFIX}bnd"),
        ],
        boundaries=[("bnd", "a", "b")],
        tick=5,
    )
    del world._entities[f"{WALL_ID_PREFIX}bnd"]

    run_expecting(world, ValueError)
    assert isinstance(world.districts[f"{WALL_ID_PREFIX}bnd"], District)
    assert world.boundaries["bnd"].wall_id is None


def test_a_candidate_colliding_with_infrastructure_is_rejected() -> None:
    """Infrastructure holds identifiers too, and they are equally reserved."""
    world = build_qualifying_chain(("a", "b"), [("bnd", "a", "b")])
    world.add_infrastructure(build_infrastructure(f"{WALL_ID_PREFIX}bnd", "bnd"))

    run_expecting(world, ValueError)


def test_a_healthy_world_with_laws_and_infrastructure_still_builds() -> None:
    """The coherence preflight must not refuse a perfectly ordinary world."""
    world = build_world(
        [pressured("a", pressure=0.9), pressured("b")],
        boundaries=[("bnd", "a", "b")],
        law=build_law(),
        tick=5,
    )
    world.add_infrastructure(build_infrastructure("infra", "bnd"))

    log = run_decision(world)

    assert set(world.walls) == {f"{WALL_ID_PREFIX}bnd"}
    assert len(log) == 1


# --- Guards that the full preflight makes unreachable ------------------------
#
# The three checks below cannot be triggered through update() once the earlier
# preflight stages are in place: coherence already refuses any world where a
# typed registry and the aggregate index disagree, and canonical identifiers
# already stop Wall construction from altering one. They are kept as defence in
# depth precisely because they do not assume the earlier stages ran correctly,
# and they are exercised directly here so that value is not merely asserted.


def test_the_same_object_in_two_typed_registries_is_rejected() -> None:
    """One object filed under two registries is caught by duplicate detection alone.

    When two registries hold *different* objects under one name, the aggregate
    index can only resolve to one of them, so the object-identity check fires
    first. Filing the very same object twice slips past that check, leaving the
    duplicate scan as the only thing standing between it and a decision.
    """
    world = build_qualifying_chain(("a", "b"), [("bnd", "a", "b")])
    world._walls["a"] = world._districts["a"]  # type: ignore[assignment]

    # The generic snapshot helper cannot be used here: it reads wall fields, and
    # the object wrongly filed under the wall registry is a district.
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    rng_before = world.rng.get_state()

    with pytest.raises(ValueError):
        BoundaryDecisionSystem().update(world, bus)

    assert sorted(world.walls) == ["a"], "no wall may have been added"
    assert world.boundaries["bnd"].wall_id is None
    assert world.tick == 5
    assert world.episode == 0
    assert world.rng.get_state() == rng_before
    assert len(log) == 0


def test_the_candidate_scan_does_not_depend_on_the_aggregate_index() -> None:
    """Exercised directly, since coherence stops such a world reaching it.

    If the index ever reported a name as free while a district still held it,
    this scan is what would prevent a wall overwriting that district.
    """
    world = build_qualifying_chain(("a", "b"), [("bnd", "a", "b")])
    world._districts[f"{WALL_ID_PREFIX}bnd"] = build_district(f"{WALL_ID_PREFIX}bnd")

    assert not world.has_entity(f"{WALL_ID_PREFIX}bnd"), (
        "the index must be unaware of it for this to test anything"
    )
    with pytest.raises(ValueError):
        BoundaryDecisionSystem._reserve_wall_id(world, "bnd", set())


def test_the_candidate_scan_still_accepts_a_free_name() -> None:
    """The scan must not reject an identifier nothing actually holds."""
    world = build_qualifying_chain(("a", "b"), [("bnd", "a", "b")])
    assert BoundaryDecisionSystem._reserve_wall_id(world, "bnd", set()) == f"{WALL_ID_PREFIX}bnd"


@pytest.mark.parametrize(
    "wall_id,boundary_id,created,built",
    [
        ("wall_other", "bnd", 5, 5),
        ("wall_bnd", "other", 5, 5),
        ("wall_bnd", "bnd", 4, 5),
        ("wall_bnd", "bnd", 5, 6),
    ],
)
def test_a_staged_wall_that_drifted_is_refused(
    wall_id: str, boundary_id: str, created: int, built: int
) -> None:
    """Construction must not be able to quietly alter what it was handed.

    ``Wall`` normalizes its identifiers, so a wall whose ``boundary_id`` came
    back changed would fail registration only after earlier walls had already
    been applied -- which is exactly the partial application this phase forbids.
    """
    wall = build_wall(wall_id, boundary_id, active=True)
    wall.created_tick = created
    wall.built_tick = built

    with pytest.raises(ValueError):
        BoundaryDecisionSystem._verify_staged_wall(wall, "wall_bnd", "bnd", 5)


def test_a_correctly_staged_wall_passes_verification() -> None:
    """The guard must not reject a wall that is exactly as intended."""
    wall = build_wall("wall_bnd", "bnd", active=True)
    wall.created_tick = 5
    wall.built_tick = 5

    BoundaryDecisionSystem._verify_staged_wall(wall, "wall_bnd", "bnd", 5)


def test_staging_actually_invokes_the_staged_wall_guard() -> None:
    """The guard must be wired in, not merely present and separately tested.

    Because full preflight makes a drifted wall unreachable, no world can prove
    the call happens by failing. Parsing the staging routine is what proves it:
    the check has to run on every staged wall before its event is built, which
    is the last point before anything is applied.
    """
    import ast  # noqa: PLC0415
    import pathlib  # noqa: PLC0415

    import living_diorama.systems.boundary_decision_system as module  # noqa: PLC0415

    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    staging = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_stage_walls"
    )

    calls = [
        node.func.attr
        for node in ast.walk(staging)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert "_verify_staged_wall" in calls, (
        "_stage_walls must verify each constructed wall before staging its event"
    )

    constructors = [
        node.func.id
        for node in ast.walk(staging)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "Event" in constructors, "the event is constructed during staging"

    guard_line = min(
        node.lineno
        for node in ast.walk(staging)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_verify_staged_wall"
    )
    event_line = min(
        node.lineno
        for node in ast.walk(staging)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Event"
    )
    assert guard_line < event_line, "the wall must be verified before its event is built"
