"""Tests for InfrastructureAdaptationSystem.

Dependency is the mechanism that makes a wall outlive the rule that built it,
and nothing in this phase ever gives it back. So most of these tests are about
what the system refuses to do: grow without a standing wall, decay when one
comes down, let a removed route erase a reliance the world already built, or
touch anything it does not own.
"""

import itertools
import json
import math
import random

import pytest
from systems_builders import (
    build_district,
    build_law,
    build_wall,
    build_world,
)

from living_diorama.entities import (
    Infrastructure,
    InfrastructureType,
    IsolationState,
    ResourceType,
)
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.systems import InfrastructureAdaptationSystem
from living_diorama.systems.infrastructure_adaptation_system import _clamp_unit

ALL_TYPES = list(InfrastructureType)
"""Every infrastructure kind, so no test silently covers only the default."""


def run_adaptation(world, system=None) -> EventLog:
    """Run one adaptation update and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    (system or InfrastructureAdaptationSystem()).update(world, bus)
    return log


def make_infrastructure(
    infrastructure_id: str,
    boundary_id: str = "bnd",
    *,
    kind: InfrastructureType = InfrastructureType.TRANSIT_ROUTE,
    dependency: float = 0.0,
    capacity: float = 1.0,
    degraded: bool = False,
    created_tick: int = 0,
) -> Infrastructure:
    """Build infrastructure with a chosen kind, dependency, and health."""
    return Infrastructure(
        id=infrastructure_id,
        created_tick=created_tick,
        boundary_id=boundary_id,
        infrastructure_type=kind,
        capacity=capacity,
        dependency_score=dependency,
        degraded=degraded,
    )


def walled_world(
    *,
    active: bool = True,
    permanent: bool = True,
    infrastructure: list[Infrastructure] | None = None,
    wall_dependency: float = 0.0,
    transport: float | None = None,
    resource: float | None = None,
    tick: int = 1,
):
    """Build one boundary carrying one wall, with chosen infrastructure.

    The three wall fields default to the same value for brevity, but each can be
    set independently. They are genuinely independent in the entity model, and
    defaulting them together is exactly what hid a defect in Candidate V1: a
    wall whose historical category scores disagreed with its overall score never
    appeared in any test.
    """
    world = build_world(
        [build_district("a"), build_district("b")],
        boundaries=[("bnd", "a", "b")],
        tick=tick,
    )
    wall = build_wall("w", "bnd", active=active, permanent=permanent)
    wall.dependency_score = wall_dependency
    wall.transport_dependency = wall_dependency if transport is None else transport
    wall.resource_dependency = wall_dependency if resource is None else resource
    world.add_wall(wall)
    for piece in infrastructure if infrastructure is not None else [make_infrastructure("i1")]:
        world.add_infrastructure(piece)
    return world


def unwalled_world(*, infrastructure: list[Infrastructure] | None = None, tick: int = 1):
    """Build one boundary with no wall at all."""
    world = build_world(
        [build_district("a"), build_district("b")],
        boundaries=[("bnd", "a", "b")],
        tick=tick,
    )
    for piece in infrastructure if infrastructure is not None else [make_infrastructure("i1")]:
        world.add_infrastructure(piece)
    return world


# --- 29. Constructor validation ---------------------------------------------


def test_default_configuration_is_accepted() -> None:
    """The documented default is usable without argument."""
    assert InfrastructureAdaptationSystem().adaptation_rate == 0.10


@pytest.mark.parametrize("rate", [0.0, 0.25, 0.5, 1.0])
def test_valid_rates_are_accepted(rate: float) -> None:
    """Any share of the remaining distance is a legitimate rate."""
    assert InfrastructureAdaptationSystem(adaptation_rate=rate).adaptation_rate == rate


@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), float("inf"), float("-inf")])
def test_invalid_rates_are_rejected(bad: float) -> None:
    """A rate is a share of a distance, so it cannot fall outside that distance."""
    with pytest.raises(ValueError):
        InfrastructureAdaptationSystem(adaptation_rate=bad)


@pytest.mark.parametrize("bad", [True, False, "0.1", None])
def test_non_numeric_and_boolean_rates_are_rejected(bad: object) -> None:
    """Bool subclasses int, so True would silently mean a rate of 1.0."""
    with pytest.raises(TypeError):
        InfrastructureAdaptationSystem(adaptation_rate=bad)


def test_the_rate_is_read_only() -> None:
    """Configuration is fixed at construction; nothing rewrites it mid-run."""
    system = InfrastructureAdaptationSystem()
    with pytest.raises(AttributeError):
        system.adaptation_rate = 0.5  # type: ignore[misc]


# --- 30. The adaptation formula ---------------------------------------------


@pytest.mark.parametrize(
    "previous,expected",
    [(0.0, 0.10), (0.50, 0.55), (0.90, 0.91), (0.99, 0.991)],
)
def test_each_tick_closes_a_tenth_of_the_remaining_distance(
    previous: float, expected: float
) -> None:
    """Gap-closing, not linear addition: growth slows as reliance nears total."""
    world = walled_world(infrastructure=[make_infrastructure("i1", dependency=previous)])
    run_adaptation(world)
    assert world.infrastructure["i1"].dependency_score == pytest.approx(expected)


def test_total_dependency_stays_exactly_total() -> None:
    """There is nothing left to close, so nothing moves and nothing is reported."""
    world = walled_world(infrastructure=[make_infrastructure("i1", dependency=1.0)])
    log = run_adaptation(world)

    assert world.infrastructure["i1"].dependency_score == 1.0
    assert len(log.query(event_type=EventType.INFRASTRUCTURE_ADAPTED)) == 0


def test_a_zero_rate_freezes_dependency_and_reports_nothing() -> None:
    """A frozen adaptation layer is a valid configuration, not an absent one."""
    # The wall starts level with its infrastructure, so a frozen rate leaves the
    # whole world still. Starting it lower would let the wall legitimately catch
    # up to reliance that already existed, which is aggregation, not adaptation.
    world = walled_world(
        wall_dependency=0.3,
        infrastructure=[make_infrastructure("i1", dependency=0.3)],
    )
    log = run_adaptation(world, InfrastructureAdaptationSystem(adaptation_rate=0.0))

    assert world.infrastructure["i1"].dependency_score == 0.3
    assert world.walls["w"].dependency_score == 0.3
    assert len(log) == 0


def test_a_full_rate_reaches_total_dependency_immediately() -> None:
    """The only setting under which reliance may complete in one tick."""
    world = walled_world(infrastructure=[make_infrastructure("i1", dependency=0.2)])
    run_adaptation(world, InfrastructureAdaptationSystem(adaptation_rate=1.0))
    assert world.infrastructure["i1"].dependency_score == 1.0


def test_a_tiny_rate_is_not_treated_as_zero() -> None:
    """A representable movement is a real movement and is recorded.

    Suppressing a change this small with an epsilon would silently reconfigure
    the system to a zero rate, freezing the world while appearing to adapt.
    """
    world = walled_world(infrastructure=[make_infrastructure("i1", dependency=0.0)])
    log = run_adaptation(world, InfrastructureAdaptationSystem(adaptation_rate=1e-12))

    assert world.infrastructure["i1"].dependency_score > 0.0
    assert len(log.query(event_type=EventType.INFRASTRUCTURE_ADAPTED)) == 1


def test_growth_is_monotonic_across_many_starting_points() -> None:
    """No valid starting dependency can be reduced by an adaptation step."""
    for start in (0.0, 0.01, 0.2, 0.5, 0.75, 0.999, 1.0):
        world = walled_world(infrastructure=[make_infrastructure("i1", dependency=start)])
        run_adaptation(world)
        assert world.infrastructure["i1"].dependency_score >= start
        assert 0.0 <= world.infrastructure["i1"].dependency_score <= 1.0


@pytest.mark.parametrize("bad", [2.0, -1.0, 1.5, float("nan"), float("inf")])
def test_meaningful_out_of_range_results_are_rejected(bad: float) -> None:
    """A value far outside the interval is a defect, not a value to tidy away."""
    with pytest.raises(ValueError):
        _clamp_unit(bad, "test")


def test_one_ulp_residue_is_flattened() -> None:
    """The single bit an arithmetic step can lose is exactly what may be tidied."""
    assert _clamp_unit(math.nextafter(0.0, -math.inf), "test") == 0.0
    assert _clamp_unit(math.nextafter(1.0, math.inf), "test") == 1.0
    assert _clamp_unit(0.5, "test") == 0.5


def test_just_beyond_one_ulp_is_rejected() -> None:
    """The residue window is exactly one ULP wide, not a soft tolerance."""
    with pytest.raises(ValueError):
        _clamp_unit(math.nextafter(math.nextafter(1.0, math.inf), math.inf), "test")


# --- 31. Eligibility --------------------------------------------------------


@pytest.mark.parametrize("permanent", [True, False])
def test_an_active_wall_drives_growth_whether_or_not_it_is_permanent(
    permanent: bool,
) -> None:
    """Permanence records intent; only standing decides whether reliance grows."""
    world = walled_world(permanent=permanent)
    run_adaptation(world)
    assert world.infrastructure["i1"].dependency_score == pytest.approx(0.10)


@pytest.mark.parametrize("permanent", [True, False])
def test_an_inactive_wall_drives_no_growth(permanent: bool) -> None:
    """A wall that is not standing is not being organized around."""
    world = walled_world(
        active=False,
        permanent=permanent,
        infrastructure=[make_infrastructure("i1", dependency=0.4)],
    )
    log = run_adaptation(world)

    assert world.infrastructure["i1"].dependency_score == 0.4
    assert len(log) == 0


def test_infrastructure_on_a_wall_free_boundary_does_not_adapt() -> None:
    """Without a barrier there is nothing to reorganize around."""
    world = unwalled_world(infrastructure=[make_infrastructure("i1", dependency=0.3)])
    log = run_adaptation(world)

    assert world.infrastructure["i1"].dependency_score == 0.3
    assert len(log) == 0


@pytest.mark.parametrize("kind", ALL_TYPES)
def test_every_infrastructure_kind_can_accumulate_dependency(
    kind: InfrastructureType,
) -> None:
    """Category affects which wall field grows, never whether growth happens."""
    world = walled_world(infrastructure=[make_infrastructure("i1", kind=kind)])
    run_adaptation(world)
    assert world.infrastructure["i1"].dependency_score == pytest.approx(0.10)


def test_degraded_infrastructure_still_accumulates_dependency() -> None:
    """A bad route everyone relies on is precisely what makes a wall permanent.

    Dependency measures how far the world has reorganized itself, not whether
    the thing it reorganized around is in good repair.
    """
    world = walled_world(infrastructure=[make_infrastructure("i1", degraded=True)])
    run_adaptation(world)

    assert world.infrastructure["i1"].dependency_score == pytest.approx(0.10)
    assert world.infrastructure["i1"].degraded is True


def test_zero_capacity_infrastructure_still_accumulates_dependency() -> None:
    """Capacity is reported, never a gate."""
    world = walled_world(infrastructure=[make_infrastructure("i1", capacity=0.0)])
    run_adaptation(world)

    assert world.infrastructure["i1"].dependency_score == pytest.approx(0.10)
    assert world.infrastructure["i1"].capacity == 0.0


def test_infrastructure_on_another_boundary_is_untouched() -> None:
    """Each piece answers to the wall on its own boundary and no other."""
    world = build_world(
        [build_district("a"), build_district("b"), build_district("c")],
        boundaries=[("walled", "a", "b"), ("open", "b", "c")],
        tick=1,
    )
    world.add_wall(build_wall("w", "walled", active=True))
    world.add_infrastructure(make_infrastructure("i_walled", "walled"))
    world.add_infrastructure(make_infrastructure("i_open", "open", dependency=0.5))

    run_adaptation(world)

    assert world.infrastructure["i_walled"].dependency_score == pytest.approx(0.10)
    assert world.infrastructure["i_open"].dependency_score == 0.5


# --- 32. Wall aggregation ---------------------------------------------------


def test_a_transit_route_raises_transport_and_overall_only() -> None:
    """Category routing: transit feeds transport, never resource."""
    world = walled_world(
        infrastructure=[make_infrastructure("i1", kind=InfrastructureType.TRANSIT_ROUTE)]
    )
    run_adaptation(world)
    wall = world.walls["w"]

    assert wall.transport_dependency == pytest.approx(0.10)
    assert wall.resource_dependency == 0.0
    assert wall.dependency_score == pytest.approx(0.10)


def test_a_resource_route_raises_resource_and_overall_only() -> None:
    """And resource feeds resource, never transport."""
    world = walled_world(
        infrastructure=[make_infrastructure("i1", kind=InfrastructureType.RESOURCE_ROUTE)]
    )
    run_adaptation(world)
    wall = world.walls["w"]

    assert wall.resource_dependency == pytest.approx(0.10)
    assert wall.transport_dependency == 0.0
    assert wall.dependency_score == pytest.approx(0.10)


@pytest.mark.parametrize("kind", [InfrastructureType.HOUSING, InfrastructureType.CIVIC_SERVICE])
def test_housing_and_civic_service_raise_overall_only(kind: InfrastructureType) -> None:
    """Neither is a route, so neither belongs to a route category."""
    world = walled_world(infrastructure=[make_infrastructure("i1", kind=kind)])
    run_adaptation(world)
    wall = world.walls["w"]

    assert wall.dependency_score == pytest.approx(0.10)
    assert wall.transport_dependency == 0.0
    assert wall.resource_dependency == 0.0


def test_mixed_categories_produce_the_documented_maxima() -> None:
    """The worked example: transit 0.40, resource 0.70, civic 0.90."""
    world = walled_world(
        infrastructure=[
            make_infrastructure("t", kind=InfrastructureType.TRANSIT_ROUTE, dependency=0.4),
            make_infrastructure("r", kind=InfrastructureType.RESOURCE_ROUTE, dependency=0.7),
            make_infrastructure("c", kind=InfrastructureType.CIVIC_SERVICE, dependency=0.9),
        ]
    )
    run_adaptation(world, InfrastructureAdaptationSystem(adaptation_rate=0.0))
    wall = world.walls["w"]

    assert wall.transport_dependency == pytest.approx(0.40)
    assert wall.resource_dependency == pytest.approx(0.70)
    assert wall.dependency_score == pytest.approx(0.90)


def test_duplicate_infrastructure_does_not_inflate_a_wall_score() -> None:
    """Two identical routes are not twice the reliance.

    Summing would make the score depend on how many objects happen to exist,
    and averaging would let an indifferent piece dilute a critical one. A wall
    is as load-bearing as its single most dependent attachment.
    """
    one = walled_world(
        infrastructure=[
            make_infrastructure("t1", kind=InfrastructureType.TRANSIT_ROUTE, dependency=0.5)
        ]
    )
    two = walled_world(
        infrastructure=[
            make_infrastructure("t1", kind=InfrastructureType.TRANSIT_ROUTE, dependency=0.5),
            make_infrastructure("t2", kind=InfrastructureType.TRANSIT_ROUTE, dependency=0.5),
        ]
    )
    system = InfrastructureAdaptationSystem(adaptation_rate=0.0)
    run_adaptation(one, system)
    run_adaptation(two, system)

    assert two.walls["w"].transport_dependency == one.walls["w"].transport_dependency
    assert two.walls["w"].dependency_score == one.walls["w"].dependency_score


def test_infrastructure_registration_order_does_not_change_the_wall() -> None:
    """Maximum is invariant to the order equivalent objects were registered."""
    forward = walled_world(
        infrastructure=[
            make_infrastructure("i_a", kind=InfrastructureType.TRANSIT_ROUTE, dependency=0.2),
            make_infrastructure("i_b", kind=InfrastructureType.RESOURCE_ROUTE, dependency=0.8),
            make_infrastructure("i_c", kind=InfrastructureType.HOUSING, dependency=0.5),
        ]
    )
    backward = walled_world(
        infrastructure=[
            make_infrastructure("i_c", kind=InfrastructureType.HOUSING, dependency=0.5),
            make_infrastructure("i_b", kind=InfrastructureType.RESOURCE_ROUTE, dependency=0.8),
            make_infrastructure("i_a", kind=InfrastructureType.TRANSIT_ROUTE, dependency=0.2),
        ]
    )
    run_adaptation(forward)
    run_adaptation(backward)

    for field in ("dependency_score", "transport_dependency", "resource_dependency"):
        assert getattr(forward.walls["w"], field) == getattr(backward.walls["w"], field)


def test_a_historical_wall_score_above_its_infrastructure_is_preserved() -> None:
    """What the world already built around the wall is not handed back."""
    world = walled_world(
        wall_dependency=0.8,
        infrastructure=[make_infrastructure("i1", dependency=0.1)],
    )
    run_adaptation(world, InfrastructureAdaptationSystem(adaptation_rate=0.0))

    assert world.walls["w"].dependency_score == 0.8
    assert world.walls["w"].transport_dependency == 0.8


def test_a_missing_category_does_not_reset_its_historical_score() -> None:
    """Removing every transit route does not undo the reliance it created.

    Journeys were re-planned around the wall; the routes disappearing does not
    un-plan them.
    """
    world = walled_world(
        wall_dependency=0.0,
        infrastructure=[
            make_infrastructure("only_resource", kind=InfrastructureType.RESOURCE_ROUTE)
        ],
    )
    world.walls["w"].transport_dependency = 0.6
    run_adaptation(world)

    assert world.walls["w"].transport_dependency == 0.6
    assert world.walls["w"].resource_dependency == pytest.approx(0.10)


def test_a_wall_with_no_infrastructure_is_left_alone() -> None:
    """Nothing attached means nothing to become dependent."""
    world = walled_world(wall_dependency=0.4, infrastructure=[])
    log = run_adaptation(world)

    assert world.walls["w"].dependency_score == 0.4
    assert len(log) == 0


def test_an_inactive_wall_freezes_every_dependency_field() -> None:
    """Standing down stops accumulation without surrendering any of it."""
    world = walled_world(
        active=False,
        wall_dependency=0.55,
        infrastructure=[make_infrastructure("i1", dependency=0.9)],
    )
    log = run_adaptation(world)
    wall = world.walls["w"]

    assert (wall.dependency_score, wall.transport_dependency, wall.resource_dependency) == (
        0.55,
        0.55,
        0.55,
    )
    assert len(log) == 0


def test_a_wall_already_wholly_depended_upon_stays_there() -> None:
    """Total reliance is a ceiling, not a value that drifts."""
    world = walled_world(
        wall_dependency=1.0, infrastructure=[make_infrastructure("i1", dependency=1.0)]
    )
    log = run_adaptation(world)

    assert world.walls["w"].dependency_score == 1.0
    assert len(log) == 0


# --- 33. Corrupted stored state ---------------------------------------------

CORRUPT_UNIT_VALUES = [True, False, "0.5", float("nan"), float("inf"), float("-inf"), -0.1, 1.1]
"""Stored scores that must never be accepted, however plausible they look."""

CORRUPT_FLAGS = [0, 1, "true", None]
"""Values that are truthy or falsy but are not flags."""

CORRUPT_TICKS = [True, 1.5, "5", -1]
"""Values that are not exact non-negative ints."""


def unit_error(bad: object) -> type[Exception]:
    """Return the precise exception a corrupted unit score must raise."""
    if type(bad) is bool or not isinstance(bad, int | float):
        return TypeError
    return ValueError


INFRASTRUCTURE_FIELDS = ("dependency_score", "capacity", "degraded", "boundary_id", "created_tick")
WALL_FIELDS = (
    "dependency_score",
    "transport_dependency",
    "resource_dependency",
    "integrity",
    "active",
    "permanent",
    "built_tick",
)
BOUNDARY_FIELDS = ("district_a_id", "district_b_id", "wall_id")

_MISSING = object()


def capture(registry, fields: tuple[str, ...]) -> dict:
    """Read chosen fields off every entry, tolerating deliberately corrupt state.

    Several tests file the wrong kind of object into a registry, or a key that
    is not a string, on purpose. The snapshot has to survive that in order to
    prove nothing changed, so it sorts by ``repr`` and treats an absent field as
    a recorded absence rather than an error.
    """
    return {
        repr(key): tuple(getattr(registry[key], field, _MISSING) for field in fields)
        for key in sorted(registry, key=repr)
    }


def snapshot(world) -> dict:
    """Capture everything an adaptation must leave alone on failure."""
    return {
        "infrastructure": capture(world.infrastructure, INFRASTRUCTURE_FIELDS),
        "walls": capture(world.walls, WALL_FIELDS),
        "boundaries": capture(world.boundaries, BOUNDARY_FIELDS),
        "tick": world.tick,
        "episode": world.episode,
        "rng": world.rng.get_state(),
    }


def run_expecting(world, error: type[Exception], system=None) -> None:
    """Run an adaptation expecting failure, and prove nothing at all happened."""
    before = snapshot(world)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)

    with pytest.raises(error):
        (system or InfrastructureAdaptationSystem()).update(world, bus)

    assert snapshot(world) == before
    assert len(log) == 0


def three_piece_world(*, tick: int = 1):
    """A world with three eligible infrastructure pieces sorting a/m/z."""
    return walled_world(
        infrastructure=[
            make_infrastructure("a_first"),
            make_infrastructure("m_middle"),
            make_infrastructure("z_last"),
        ],
        tick=tick,
    )


@pytest.mark.parametrize("bad", CORRUPT_UNIT_VALUES)
@pytest.mark.parametrize("position", ["a_first", "m_middle", "z_last"])
def test_corrupted_infrastructure_dependency_aborts_everything(bad: object, position: str) -> None:
    """One corrupt score anywhere leaves every other piece untouched."""
    world = three_piece_world()
    world.infrastructure[position].dependency_score = bad  # type: ignore[assignment]

    run_expecting(world, unit_error(bad))


@pytest.mark.parametrize("bad", [True, False, "1.0", float("nan"), float("inf"), -0.1])
def test_corrupted_infrastructure_capacity_aborts_everything(bad: object) -> None:
    """Capacity does not gate adaptation, but a corrupt entity is not trustworthy."""
    world = three_piece_world()
    world.infrastructure["m_middle"].capacity = bad  # type: ignore[assignment]

    expected = TypeError if type(bad) is bool or not isinstance(bad, int | float) else ValueError
    run_expecting(world, expected)


@pytest.mark.parametrize("bad", CORRUPT_FLAGS)
def test_corrupted_degraded_flag_aborts_everything(bad: object) -> None:
    """A flag has to be a flag, not merely truthy."""
    world = three_piece_world()
    world.infrastructure["z_last"].degraded = bad  # type: ignore[assignment]

    run_expecting(world, TypeError)


@pytest.mark.parametrize("bad", ["TRANSIT_ROUTE", None, ResourceType.FOOD, object()])
def test_corrupted_infrastructure_type_aborts_everything(bad: object) -> None:
    """Category routing depends on the real member, so nothing else is accepted."""
    world = three_piece_world()
    world.infrastructure["a_first"].infrastructure_type = bad  # type: ignore[assignment]

    run_expecting(world, TypeError)


@pytest.mark.parametrize("bad", CORRUPT_UNIT_VALUES)
@pytest.mark.parametrize(
    "field", ["dependency_score", "transport_dependency", "resource_dependency", "integrity"]
)
def test_corrupted_wall_scores_abort_everything(bad: object, field: str) -> None:
    """A wall carrying an impossible score is not one to accumulate onto."""
    world = three_piece_world()
    setattr(world.walls["w"], field, bad)

    run_expecting(world, unit_error(bad))


@pytest.mark.parametrize("bad", CORRUPT_FLAGS)
@pytest.mark.parametrize("field", ["active", "permanent"])
def test_corrupted_wall_flags_abort_everything(bad: object, field: str) -> None:
    """Whether a wall is standing decides everything here, so it must be a bool."""
    world = three_piece_world()
    setattr(world.walls["w"], field, bad)

    run_expecting(world, TypeError)


@pytest.mark.parametrize("bad", CORRUPT_TICKS)
def test_corrupted_world_tick_aborts_everything(bad: object) -> None:
    """Every event is stamped with the tick, so a corrupt one poisons the record."""
    world = three_piece_world()
    world._tick = bad

    run_expecting(world, TypeError if not isinstance(bad, int) or type(bad) is bool else ValueError)


@pytest.mark.parametrize("field", ["created_tick", "built_tick"])
@pytest.mark.parametrize("bad", CORRUPT_TICKS)
def test_corrupted_wall_ticks_abort_everything(field: str, bad: object) -> None:
    """A wall's history has to be a history."""
    world = three_piece_world()
    setattr(world.walls["w"], field, bad)

    run_expecting(world, TypeError if type(bad) is bool or not isinstance(bad, int) else ValueError)


def test_a_wall_built_before_it_was_created_aborts_everything() -> None:
    """Causality is a stored invariant too, and it stays mutable."""
    world = three_piece_world(tick=5)
    world.walls["w"].created_tick = 4
    world.walls["w"].built_tick = 2

    run_expecting(world, ValueError)


def test_a_wall_built_in_the_future_aborts_everything() -> None:
    """A wall cannot already have been built on a tick that has not happened."""
    world = three_piece_world(tick=2)
    world.walls["w"].built_tick = 9
    world.walls["w"].created_tick = 9

    run_expecting(world, ValueError)


def test_infrastructure_created_in_the_future_aborts_everything() -> None:
    """The same rule, for infrastructure."""
    world = three_piece_world(tick=2)
    world.infrastructure["a_first"].created_tick = 7

    run_expecting(world, ValueError)


# --- 34. Identifiers and registry coherence ---------------------------------


@pytest.mark.parametrize("corrupted", ["i1 ", " i1", "", "  ", 1, True, None])
def test_noncanonical_or_mistyped_infrastructure_id_is_rejected(corrupted: object) -> None:
    """Constructors strip on the way in, but entities stay mutable afterwards."""
    world = three_piece_world()
    world._infrastructure[corrupted] = world._infrastructure.pop("a_first")
    world._infrastructure[corrupted].id = corrupted
    world._entities[corrupted] = world._entities.pop("a_first")

    expected = TypeError if type(corrupted) is not str else ValueError
    run_expecting(world, expected)


@pytest.mark.parametrize("corrupted", ["bnd ", " bnd", ""])
def test_noncanonical_infrastructure_boundary_id_is_rejected(corrupted: str) -> None:
    """A reference carrying whitespace resolves to nothing."""
    world = three_piece_world()
    world.infrastructure["m_middle"].boundary_id = corrupted

    run_expecting(world, ValueError)


@pytest.mark.parametrize("corrupted", ["w ", " w", ""])
def test_noncanonical_wall_id_is_rejected(corrupted: str) -> None:
    """The same rule for walls, whose names the boundary points back at."""
    world = three_piece_world()
    world._walls[corrupted] = world._walls.pop("w")
    world._walls[corrupted].id = corrupted
    world._entities[corrupted] = world._entities.pop("w")

    run_expecting(world, ValueError)


def test_noncanonical_wall_boundary_id_is_rejected() -> None:
    """A wall must name its boundary exactly."""
    world = three_piece_world()
    world.walls["w"].boundary_id = "bnd "

    run_expecting(world, ValueError)


def test_noncanonical_boundary_id_is_rejected() -> None:
    """Registry key and id can agree and still both be wrong."""
    world = three_piece_world()
    world._boundaries["bnd "] = world._boundaries.pop("bnd")
    world._boundaries["bnd "].id = "bnd "
    world._entities["bnd "] = world._entities.pop("bnd")

    run_expecting(world, ValueError)


@pytest.mark.parametrize("field", ["district_a_id", "district_b_id"])
def test_noncanonical_boundary_endpoint_is_rejected(field: str) -> None:
    """Endpoints are references and get the same treatment."""
    world = three_piece_world()
    setattr(world.boundaries["bnd"], field, "a ")

    run_expecting(world, ValueError)


def test_a_registry_key_disagreeing_with_its_entity_is_rejected() -> None:
    """The key and the entity have to be talking about the same thing."""
    world = three_piece_world()
    world.infrastructure["a_first"].id = "renamed"

    run_expecting(world, ValueError)


def test_an_id_missing_from_the_aggregate_index_is_rejected() -> None:
    """``has_entity`` cannot vouch for a world whose two views have drifted."""
    world = three_piece_world()
    del world._entities["a_first"]

    run_expecting(world, ValueError)


def test_an_aggregate_index_pointing_at_another_object_is_rejected() -> None:
    """An index entry must resolve to the very object the registry holds."""
    world = three_piece_world()
    world._entities["a_first"] = world._infrastructure["z_last"]

    run_expecting(world, ValueError)


def test_the_same_id_in_two_typed_registries_is_rejected() -> None:
    """One identifier may not name two things, even the same object twice."""
    world = three_piece_world()
    world._walls["a_first"] = world._infrastructure["a_first"]  # type: ignore[assignment]

    run_expecting(world, ValueError)


def test_infrastructure_pointing_at_an_unknown_boundary_is_rejected() -> None:
    """A dangling attachment cannot be adapted."""
    world = three_piece_world()
    world.infrastructure["z_last"].boundary_id = "nowhere"

    run_expecting(world, ValueError)


def test_a_wall_pointing_at_an_unknown_boundary_is_rejected() -> None:
    """Nor can a wall standing nowhere carry dependency."""
    world = three_piece_world()
    world.walls["w"].boundary_id = "nowhere"

    run_expecting(world, ValueError)


def test_a_boundary_naming_a_missing_wall_is_rejected() -> None:
    """A back-reference to nothing is a broken world, not an empty boundary."""
    world = three_piece_world()
    world.boundaries["bnd"].wall_id = "ghost"

    run_expecting(world, ValueError)


def test_a_wall_and_boundary_disagreeing_is_rejected() -> None:
    """References must be consistent in both directions."""
    world = build_world(
        [build_district("a"), build_district("b"), build_district("c")],
        boundaries=[("bnd", "a", "b"), ("other", "b", "c")],
        tick=1,
    )
    world.add_wall(build_wall("w", "bnd", active=True))
    world.add_infrastructure(make_infrastructure("i1", "bnd"))
    world.walls["w"].boundary_id = "other"

    run_expecting(world, ValueError)


def test_a_wall_free_boundary_secretly_carrying_a_wall_is_rejected() -> None:
    """A wall pointing at a boundary that disowns it is a defect either way."""
    world = three_piece_world()
    world.boundaries["bnd"].wall_id = None

    run_expecting(world, ValueError)


def test_two_walls_claiming_one_boundary_is_rejected() -> None:
    """At most one wall may stand on a boundary."""
    world = three_piece_world()
    intruder = build_wall("w2", "bnd", active=True)
    world._walls["w2"] = intruder
    world._entities["w2"] = intruder

    run_expecting(world, ValueError)


def test_a_mutated_self_loop_boundary_is_rejected() -> None:
    """The constructor forbids it, but ``Boundary`` stays mutable."""
    world = three_piece_world()
    world.boundaries["bnd"].district_b_id = "a"

    run_expecting(world, ValueError)


# --- 35. Atomicity across several walls -------------------------------------


def multi_wall_world(*, tick: int = 1):
    """Three boundaries, each with an active wall and its own infrastructure."""
    world = build_world(
        [build_district(name) for name in ("a", "b", "c", "d")],
        boundaries=[("b_aaa", "a", "b"), ("b_mmm", "b", "c"), ("b_zzz", "c", "d")],
        tick=tick,
    )
    for boundary_id in ("b_aaa", "b_mmm", "b_zzz"):
        world.add_wall(build_wall(f"w_{boundary_id}", boundary_id, active=True))
        world.add_infrastructure(make_infrastructure(f"i_{boundary_id}", boundary_id))
    return world


@pytest.mark.parametrize("position", ["b_aaa", "b_mmm", "b_zzz"])
def test_one_corrupt_wall_leaves_every_other_wall_untouched(position: str) -> None:
    """Failure at any sort position aborts the entire tick."""
    world = multi_wall_world()
    world.walls[f"w_{position}"].dependency_score = 1.5

    run_expecting(world, ValueError)


@pytest.mark.parametrize("position", ["b_aaa", "b_mmm", "b_zzz"])
def test_one_corrupt_infrastructure_leaves_every_other_piece_untouched(
    position: str,
) -> None:
    """The same guarantee from the infrastructure side."""
    world = multi_wall_world()
    world.infrastructure[f"i_{position}"].dependency_score = "0.5"  # type: ignore[assignment]

    run_expecting(world, TypeError)


def test_a_healthy_multi_wall_world_adapts_everything() -> None:
    """The control case: with nothing corrupt, all three walls advance."""
    world = multi_wall_world()
    log = run_adaptation(world)

    for boundary_id in ("b_aaa", "b_mmm", "b_zzz"):
        assert world.infrastructure[f"i_{boundary_id}"].dependency_score == pytest.approx(0.10)
        assert world.walls[f"w_{boundary_id}"].dependency_score == pytest.approx(0.10)
    assert len(log.query(event_type=EventType.INFRASTRUCTURE_ADAPTED)) == 3
    assert len(log.query(event_type=EventType.WALL_CHANGED)) == 3


# --- 36. Events -------------------------------------------------------------


def test_one_event_per_changed_infrastructure_in_sorted_order() -> None:
    """Traversal order is fixed by identifier and shows up in the record."""
    world = walled_world(
        infrastructure=[
            make_infrastructure("zulu"),
            make_infrastructure("alpha"),
            make_infrastructure("mike"),
        ],
        tick=6,
    )
    log = run_adaptation(world)
    adapted = log.query(event_type=EventType.INFRASTRUCTURE_ADAPTED)

    assert [event.source_id for event in adapted] == ["alpha", "mike", "zulu"]
    for event in adapted:
        assert event.tick == 6


def test_infrastructure_events_precede_wall_events() -> None:
    """Causally the wall becomes load-bearing because its attachments did."""
    world = multi_wall_world()
    kinds = [event.type for event in run_adaptation(world)]

    last_infrastructure = max(
        index for index, kind in enumerate(kinds) if kind is EventType.INFRASTRUCTURE_ADAPTED
    )
    first_wall = kinds.index(EventType.WALL_CHANGED)
    assert last_infrastructure < first_wall


def test_wall_events_are_sorted_by_wall_id() -> None:
    """Deterministic ordering across the wall events too."""
    world = multi_wall_world()
    changed = run_adaptation(world).query(event_type=EventType.WALL_CHANGED)
    assert [event.source_id for event in changed] == sorted(event.source_id for event in changed)


def test_the_infrastructure_payload_is_complete_and_json_safe() -> None:
    """Everything needed to explain the step, as strict primitives."""
    world = walled_world(
        infrastructure=[
            make_infrastructure(
                "i1",
                kind=InfrastructureType.RESOURCE_ROUTE,
                dependency=0.5,
                capacity=2.5,
                degraded=True,
            )
        ],
        tick=4,
    )
    payload = (
        run_adaptation(world)
        .query(event_type=EventType.INFRASTRUCTURE_ADAPTED)[0]
        .payload_as_dict()
    )

    assert payload["infrastructure_id"] == "i1"
    assert payload["boundary_id"] == "bnd"
    assert payload["wall_id"] == "w"
    assert payload["infrastructure_type"] == "RESOURCE_ROUTE"
    assert payload["capacity"] == 2.5
    assert payload["degraded"] is True
    assert payload["adaptation_rate"] == 0.10
    assert payload["previous_dependency_score"] == 0.5
    assert payload["new_dependency_score"] == pytest.approx(0.55)
    assert payload["wall_active"] is True
    assert payload["wall_permanent"] is True
    assert payload["wall_built_tick"] == 0
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


def test_the_infrastructure_type_is_reported_as_a_string_not_an_enum() -> None:
    """An enum object would not survive serialization."""
    world = walled_world(infrastructure=[make_infrastructure("i1")])
    payload = (
        run_adaptation(world)
        .query(event_type=EventType.INFRASTRUCTURE_ADAPTED)[0]
        .payload_as_dict()
    )

    assert payload["infrastructure_type"] == "TRANSIT_ROUTE"
    assert isinstance(payload["infrastructure_type"], str)
    assert not isinstance(payload["infrastructure_type"], InfrastructureType)


def test_the_wall_payload_is_complete_and_json_safe() -> None:
    """Both previous and new values for all three fields, plus the counts."""
    world = walled_world(
        infrastructure=[
            make_infrastructure("t", kind=InfrastructureType.TRANSIT_ROUTE, dependency=0.2),
            make_infrastructure("r", kind=InfrastructureType.RESOURCE_ROUTE, dependency=1.0),
        ],
        tick=3,
    )
    payload = run_adaptation(world).query(event_type=EventType.WALL_CHANGED)[0].payload_as_dict()

    assert payload["wall_id"] == "w"
    assert payload["boundary_id"] == "bnd"
    assert payload["active"] is True
    assert payload["permanent"] is True
    assert payload["integrity"] == 1.0
    assert payload["adaptation_rate"] == 0.10
    assert payload["connected_infrastructure_count"] == 2
    assert payload["adapted_infrastructure_count"] == 1, "the saturated route did not move"
    assert payload["previous_dependency_score"] == 0.0
    assert payload["new_dependency_score"] == 1.0
    assert payload["previous_transport_dependency"] == 0.0
    assert payload["new_transport_dependency"] == pytest.approx(0.28)
    assert payload["previous_resource_dependency"] == 0.0
    assert payload["new_resource_dependency"] == 1.0
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


def test_event_payloads_are_immutable_after_construction() -> None:
    """A published reading is history and cannot be edited."""
    world = walled_world()
    for event in run_adaptation(world):
        with pytest.raises(TypeError):
            event.payload["adaptation_rate"] = 0.0  # type: ignore[index]


def test_no_wall_event_when_the_wall_fields_do_not_move() -> None:
    """A wall already above everything attached to it reports nothing."""
    world = walled_world(
        wall_dependency=1.0, infrastructure=[make_infrastructure("i1", dependency=0.1)]
    )
    log = run_adaptation(world)

    assert len(log.query(event_type=EventType.INFRASTRUCTURE_ADAPTED)) == 1
    assert len(log.query(event_type=EventType.WALL_CHANGED)) == 0


def test_phase_nine_never_emits_wall_built() -> None:
    """Construction belongs to the previous phase and is not repeated here."""
    world = multi_wall_world()
    log = run_adaptation(world)
    assert len(log.query(event_type=EventType.WALL_BUILT)) == 0


# --- 37. Mutation isolation -------------------------------------------------


def test_only_dependency_fields_are_ever_written() -> None:
    """Everything else in the world is read-only to this system."""
    world = build_world(
        [
            build_district(
                "a",
                population=100,
                food=7.0,
                scarcity=0.3,
                fear=0.4,
                trust=0.6,
                institutional_pressure=0.5,
            ),
            build_district("b"),
        ],
        boundaries=[("bnd", "a", "b")],
        law=build_law(),
        tick=5,
    )
    world.add_wall(build_wall("w", "bnd", active=True, permanent=False))
    world.add_infrastructure(
        make_infrastructure("i1", capacity=3.0, degraded=True, kind=InfrastructureType.HOUSING)
    )
    district = world.districts["a"]
    wall = world.walls["w"]
    infrastructure = world.infrastructure["i1"]

    before_pool = district.resources
    before_stock = {r: district.resources.amount_of(r) for r in ResourceType}
    rng_before = world.rng.get_state()

    run_adaptation(world)

    assert district.population == 100
    assert district.scarcity == 0.3
    assert district.fear == 0.4
    assert district.trust == 0.6
    assert district.institutional_pressure == 0.5
    assert district.isolation_state is IsolationState.OPEN
    assert district.resources is before_pool
    for resource, amount in before_stock.items():
        assert district.resources.amount_of(resource) == amount

    assert infrastructure.capacity == 3.0
    assert infrastructure.degraded is True
    assert infrastructure.infrastructure_type is InfrastructureType.HOUSING
    assert infrastructure.boundary_id == "bnd"
    assert infrastructure.created_tick == 0

    assert wall.integrity == 1.0
    assert wall.active is True
    assert wall.permanent is False
    assert wall.built_tick == 0
    assert wall.created_tick == 0
    assert wall.boundary_id == "bnd"

    assert world.boundaries["bnd"].district_a_id == "a"
    assert world.boundaries["bnd"].wall_id == "w"
    assert world.laws["law_movement_sharing"].current_value is True
    assert world.laws["law_movement_sharing"].active is True
    assert world.tick == 5
    assert world.episode == 0
    assert world.rng.get_state() == rng_before

    assert infrastructure.dependency_score == pytest.approx(0.10)
    assert wall.dependency_score == pytest.approx(0.10)


def test_the_system_does_not_advance_the_tick() -> None:
    """Tick progression belongs to SimulationLoop alone."""
    world = walled_world(tick=11)
    run_adaptation(world)
    assert world.tick == 11


def test_the_system_uses_only_the_public_world_api() -> None:
    """Parsed from the code, so a docstring cannot be mistaken for a read."""
    import ast  # noqa: PLC0415
    import pathlib  # noqa: PLC0415

    import living_diorama.systems.infrastructure_adaptation_system as module  # noqa: PLC0415

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
    }
    assert not any(name.startswith("_") for name in attributes)
    assert "add_wall" not in attributes
    assert "add_infrastructure" not in attributes
    assert "advance_tick" not in attributes


def test_law_and_district_state_cannot_change_adaptation() -> None:
    """Those registries are read for names only, never for what they say."""

    def outcome(*, law_active: bool, law_value: bool, pressure: float):
        """Run one world under a chosen law and district configuration."""
        world = build_world(
            [build_district("a", institutional_pressure=pressure), build_district("b")],
            boundaries=[("bnd", "a", "b")],
            law=build_law(active=law_active, current_value=law_value),
            tick=2,
        )
        world.add_wall(build_wall("w", "bnd", active=True))
        world.add_infrastructure(make_infrastructure("i1"))
        log = run_adaptation(world)
        return (
            world.infrastructure["i1"].dependency_score,
            world.walls["w"].dependency_score,
            [event.payload_as_dict() for event in log],
        )

    baseline = outcome(law_active=True, law_value=True, pressure=0.0)
    assert outcome(law_active=False, law_value=False, pressure=1.0) == baseline
    assert outcome(law_active=True, law_value=False, pressure=0.5) == baseline


# --- 38. Determinism --------------------------------------------------------


def test_identical_worlds_produce_identical_results() -> None:
    """The same inputs give the same dependency and the same events, every time."""
    results = []
    for _ in range(3):
        world = multi_wall_world()
        log = run_adaptation(world)
        results.append(
            (
                {k: world.infrastructure[k].dependency_score for k in sorted(world.infrastructure)},
                {
                    k: (
                        world.walls[k].dependency_score,
                        world.walls[k].transport_dependency,
                        world.walls[k].resource_dependency,
                    )
                    for k in sorted(world.walls)
                },
                [(e.type.value, e.source_id, e.payload_as_dict()) for e in log],
            )
        )
    assert results[0] == results[1] == results[2]


def test_rng_state_is_untouched() -> None:
    """This system decides nothing by chance."""
    world = multi_wall_world()
    before = world.rng.get_state()
    run_adaptation(world)
    assert world.rng.get_state() == before


def test_a_reused_system_instance_leaks_nothing_between_worlds() -> None:
    """No hidden counter: the stored score is the entire memory."""
    system = InfrastructureAdaptationSystem()
    scores = []
    for _ in range(4):
        world = walled_world()
        run_adaptation(world, system)
        scores.append(world.infrastructure["i1"].dependency_score)
    assert len(set(scores)) == 1


def test_the_system_holds_no_instance_state() -> None:
    """Configuration only; nothing from one tick survives into the next."""
    assert not hasattr(InfrastructureAdaptationSystem(), "__dict__")


def test_renaming_entities_changes_labels_only() -> None:
    """Identifiers order traversal; they never decide a number."""

    def build(names: tuple[str, str, str]):
        """Build the same world under a chosen set of names."""
        infra_id, wall_id, boundary_id = names
        world = build_world(
            [build_district("a"), build_district("b")],
            boundaries=[(boundary_id, "a", "b")],
            tick=1,
        )
        world.add_wall(build_wall(wall_id, boundary_id, active=True))
        world.add_infrastructure(make_infrastructure(infra_id, boundary_id, dependency=0.3))
        run_adaptation(world)
        return (
            world.infrastructure[infra_id].dependency_score,
            world.walls[wall_id].dependency_score,
        )

    assert build(("i1", "w", "bnd")) == build(("zzz_infra", "aaa_wall", "mmm_boundary"))


def test_subscriber_order_does_not_affect_world_state() -> None:
    """Publication is a report, never part of the computation."""

    def run(reverse: bool):
        """Run with two subscribers attached in a chosen order."""
        world = multi_wall_world()
        first, second = EventLog(), EventLog()
        bus = EventBus()
        for log in (second, first) if reverse else (first, second):
            bus.subscribe(log.append)
        InfrastructureAdaptationSystem().update(world, bus)
        return {k: world.infrastructure[k].dependency_score for k in sorted(world.infrastructure)}

    assert run(False) == run(True)


# --- 39. Multi-tick behaviour -----------------------------------------------


def test_the_documented_growth_sequence() -> None:
    """0.10, 0.19, 0.271 -- gap-closing, so each step is smaller than the last."""
    world = walled_world()
    system = InfrastructureAdaptationSystem()
    observed = []
    for _ in range(3):
        run_adaptation(world, system)
        observed.append(world.infrastructure["i1"].dependency_score)

    assert observed == [pytest.approx(0.10), pytest.approx(0.19), pytest.approx(0.271)]


def test_dependency_approaches_but_never_exceeds_total() -> None:
    """Sixty ticks of an active wall converge without overshooting."""
    world = walled_world()
    system = InfrastructureAdaptationSystem()
    values = [world.infrastructure["i1"].dependency_score]
    for _ in range(60):
        run_adaptation(world, system)
        values.append(world.infrastructure["i1"].dependency_score)

    assert values == sorted(values)
    assert all(0.0 <= value <= 1.0 for value in values)
    assert values[-1] == pytest.approx(1.0, abs=1e-2)


def test_deactivating_a_wall_freezes_dependency_without_decay() -> None:
    """The asymmetry that makes a consequence outlive its cause.

    Growth stops the moment the wall stops standing, but nothing gives back
    what the world already reorganized around it.
    """
    world = walled_world()
    system = InfrastructureAdaptationSystem()
    for _ in range(5):
        run_adaptation(world, system)
    accumulated = world.infrastructure["i1"].dependency_score
    wall_accumulated = world.walls["w"].dependency_score
    assert accumulated > 0.0

    world.walls["w"].active = False
    for _ in range(10):
        log = run_adaptation(world, system)
        assert len(log) == 0

    assert world.infrastructure["i1"].dependency_score == accumulated
    assert world.walls["w"].dependency_score == wall_accumulated


def test_reactivation_resumes_from_the_stored_value() -> None:
    """Nothing resets: growth continues from where it left off."""
    world = walled_world()
    system = InfrastructureAdaptationSystem()
    for _ in range(5):
        run_adaptation(world, system)
    frozen = world.infrastructure["i1"].dependency_score

    world.walls["w"].active = False
    run_adaptation(world, system)
    world.walls["w"].active = True
    run_adaptation(world, system)

    assert world.infrastructure["i1"].dependency_score == pytest.approx(
        frozen + 0.10 * (1.0 - frozen)
    )


def test_one_event_per_actual_change_over_many_ticks() -> None:
    """Saturated infrastructure stops reporting once it stops moving."""
    world = walled_world(infrastructure=[make_infrastructure("i1")])
    system = InfrastructureAdaptationSystem(adaptation_rate=1.0)

    first = run_adaptation(world, system)
    second = run_adaptation(world, system)

    assert len(first.query(event_type=EventType.INFRASTRUCTURE_ADAPTED)) == 1
    assert len(first.query(event_type=EventType.WALL_CHANGED)) == 1
    assert len(second) == 0


# --- 42. Randomized adversarial sweep ---------------------------------------


def test_generated_worlds_never_violate_an_invariant() -> None:
    """A bounded seeded sweep across rates, kinds, states, and orderings."""
    rng = random.Random(20260806)

    for _ in range(220):
        rate = rng.choice([0.0, 0.05, 0.1, 0.5, 1.0])
        active = rng.choice([True, False])
        permanent = rng.choice([True, False])
        wall_previous = round(rng.random(), 6)
        pieces = [
            make_infrastructure(
                f"i{index}",
                kind=rng.choice(ALL_TYPES),
                dependency=round(rng.random(), 6),
                capacity=rng.choice([0.0, 1.0, 12.5]),
                degraded=rng.choice([True, False]),
            )
            for index in range(rng.randint(0, 3))
        ]
        if rng.random() < 0.5:
            pieces = list(reversed(pieces))

        world = walled_world(
            active=active,
            permanent=permanent,
            infrastructure=pieces,
            wall_dependency=wall_previous,
            tick=rng.randint(0, 30),
        )
        previous_scores = {p.id: p.dependency_score for p in pieces}
        rng_before = world.rng.get_state()
        tick_before = world.tick

        log = run_adaptation(world, InfrastructureAdaptationSystem(adaptation_rate=rate))

        assert world.rng.get_state() == rng_before
        assert world.tick == tick_before
        wall = world.walls["w"]

        for piece_id, previous in previous_scores.items():
            current = world.infrastructure[piece_id].dependency_score
            assert math.isfinite(current)
            assert 0.0 <= current <= 1.0
            assert current >= previous, "dependency must never decay"
            if active:
                assert current == pytest.approx(previous + rate * (1.0 - previous))
            else:
                assert current == previous

        for field in ("dependency_score", "transport_dependency", "resource_dependency"):
            value = getattr(wall, field)
            assert math.isfinite(value)
            assert 0.0 <= value <= 1.0
            assert value >= wall_previous, "wall dependency must never decay"

        if not active:
            assert len(log) == 0
            assert wall.dependency_score == wall_previous
        else:
            staged = {
                piece_id: world.infrastructure[piece_id].dependency_score
                for piece_id in previous_scores
            }
            transit = [
                staged[p.id]
                for p in pieces
                if p.infrastructure_type is InfrastructureType.TRANSIT_ROUTE
            ]
            resource = [
                staged[p.id]
                for p in pieces
                if p.infrastructure_type is InfrastructureType.RESOURCE_ROUTE
            ]
            assert wall.transport_dependency == pytest.approx(
                max([wall_previous, *transit]) if transit else wall_previous
            )
            assert wall.resource_dependency == pytest.approx(
                max([wall_previous, *resource]) if resource else wall_previous
            )
            assert wall.dependency_score == pytest.approx(
                max(
                    [
                        wall_previous,
                        wall.transport_dependency,
                        wall.resource_dependency,
                        *staged.values(),
                    ]
                )
            )


def test_generated_cases_are_reproducible() -> None:
    """The same generated case run twice gives the same answer twice."""
    rng = random.Random(31337)

    for _ in range(60):
        spec = (round(rng.random(), 4), rng.choice(ALL_TYPES), round(rng.random(), 4))
        outcomes = []
        for _ in range(2):
            dependency, kind, wall_previous = spec
            world = walled_world(
                infrastructure=[make_infrastructure("i1", kind=kind, dependency=dependency)],
                wall_dependency=wall_previous,
            )
            log = run_adaptation(world)
            outcomes.append(
                (
                    world.infrastructure["i1"].dependency_score,
                    world.walls["w"].dependency_score,
                    [(event.type.value, event.source_id) for event in log],
                )
            )
        assert outcomes[0] == outcomes[1]


def test_generated_orderings_agree() -> None:
    """Permuting registration never changes a number or an event order."""
    rng = random.Random(4242)

    for _ in range(40):
        specs = [(f"i{index}", rng.choice(ALL_TYPES), round(rng.random(), 4)) for index in range(3)]
        outcomes = []
        for order in itertools.permutations(range(3)):
            world = walled_world(
                infrastructure=[
                    make_infrastructure(specs[i][0], kind=specs[i][1], dependency=specs[i][2])
                    for i in order
                ]
            )
            log = run_adaptation(world)
            outcomes.append(
                (
                    {
                        key: world.infrastructure[key].dependency_score
                        for key in sorted(world.infrastructure)
                    },
                    world.walls["w"].dependency_score,
                    [(event.type.value, event.source_id) for event in log],
                )
            )
        assert all(outcome == outcomes[0] for outcome in outcomes)


def test_an_empty_world_adapts_nothing() -> None:
    """A world with no infrastructure is valid and simply has nothing to adapt."""
    assert len(run_adaptation(build_world([], tick=1))) == 0


def test_a_healthy_piece_of_infrastructure_is_not_marked_degraded() -> None:
    """Adaptation observes health; it never reports on it or changes it.

    The broader isolation test starts from degraded infrastructure, which would
    not notice a system that marked everything degraded. This one starts healthy.
    """
    world = walled_world(
        infrastructure=[
            make_infrastructure("healthy", degraded=False),
            make_infrastructure("broken", degraded=True),
        ]
    )
    run_adaptation(world)

    assert world.infrastructure["healthy"].degraded is False
    assert world.infrastructure["broken"].degraded is True
    assert world.infrastructure["healthy"].dependency_score == pytest.approx(0.10)


def test_a_full_capacity_piece_keeps_its_capacity() -> None:
    """The same argument for capacity, from a non-zero starting value."""
    world = walled_world(infrastructure=[make_infrastructure("i1", capacity=7.5)])
    run_adaptation(world)
    assert world.infrastructure["i1"].capacity == 7.5


def test_staging_writes_nothing_to_the_world() -> None:
    """Nothing is applied while the world is still being scanned.

    Complete preflight means staging cannot fail, so no world can prove this by
    failing halfway. Parsing the staging routines is what proves it: they read
    and compute, and every write happens later in ``update``. Mutating during
    the scan would make a later failure leave a partly-adapted world behind.
    """
    import ast  # noqa: PLC0415
    import pathlib  # noqa: PLC0415

    import living_diorama.systems.infrastructure_adaptation_system as module  # noqa: PLC0415

    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    staging = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_stage_infrastructure", "_stage_walls", "_aggregate"}
    ]
    assert len(staging) == 3, "all three staging routines must be present"

    for routine in staging:
        for node in ast.walk(routine):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    assert not isinstance(target, ast.Attribute), (
                        f"{routine.name} assigns to {getattr(target, 'attr', '?')!r}; "
                        "staging must not write to the world"
                    )
            assert not isinstance(node, ast.AugAssign) or not isinstance(
                node.target, ast.Attribute
            ), f"{routine.name} mutates an attribute in place"


def test_preflight_and_staging_both_traverse_in_sorted_order() -> None:
    """Both loops sort, so neither validation nor results follow insertion order."""
    import ast  # noqa: PLC0415
    import pathlib  # noqa: PLC0415

    import living_diorama.systems.infrastructure_adaptation_system as module  # noqa: PLC0415

    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for routine_name, registry in (
        ("_verify_topology", "world.infrastructure"),
        ("_stage_infrastructure", "world.infrastructure"),
        ("_stage_walls", "world.walls"),
    ):
        routine = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == routine_name
        )
        sorted_calls = [
            node
            for node in ast.walk(routine)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "sorted"
        ]
        assert sorted_calls, f"{routine_name} must traverse {registry} in sorted order"


def test_event_order_follows_identifiers_not_registration() -> None:
    """Registering in reverse order must not reverse the recorded history."""
    world = walled_world(
        infrastructure=[
            make_infrastructure("zulu"),
            make_infrastructure("mike"),
            make_infrastructure("alpha"),
        ]
    )
    adapted = run_adaptation(world).query(event_type=EventType.INFRASTRUCTURE_ADAPTED)
    assert [event.source_id for event in adapted] == ["alpha", "mike", "zulu"]


# --- An infrastructure-free wall is not aggregated at all --------------------
#
# Every test below was written against a real defect found in independent
# review. Candidate V1 ran the aggregation for any active wall, and because the
# overall score folds in the two category scores, a wall with no infrastructure
# had its overall figure pulled up to its highest historical category -- growth
# in reliance that no infrastructure produced. The three fields are
# independently valid and may legitimately disagree; the answer is to leave them
# alone rather than reconcile them.


def unattached_wall_world(
    *, dependency: float, transport: float, resource: float, active: bool = True
):
    """Build an active wall with divergent historical scores and nothing attached."""
    return walled_world(
        active=active,
        infrastructure=[],
        wall_dependency=dependency,
        transport=transport,
        resource=resource,
        tick=5,
    )


def assert_wall_untouched(world, expected: tuple[float, float, float], log: EventLog) -> None:
    """Assert the wall kept all three scores and nothing at all was reported."""
    wall = world.walls["w"]
    assert (
        wall.dependency_score,
        wall.transport_dependency,
        wall.resource_dependency,
    ) == expected
    assert len(log.query(event_type=EventType.INFRASTRUCTURE_ADAPTED)) == 0
    assert len(log.query(event_type=EventType.WALL_CHANGED)) == 0
    assert len(log) == 0


@pytest.mark.parametrize(
    "dependency,transport,resource",
    [
        (0.10, 0.80, 0.20),
        (0.10, 0.20, 0.90),
        (0.00, 0.60, 0.70),
        (0.50, 1.00, 1.00),
        (0.00, 0.00, 0.01),
    ],
)
def test_a_wall_with_no_infrastructure_keeps_divergent_scores(
    dependency: float, transport: float, resource: float
) -> None:
    """A category score above the overall one is valid state, not a growth signal.

    No cross-field invariant says overall must be at least the category maximum,
    so a wall in this shape is neither corrupt nor due an update. With nothing
    attached, there is nothing adapting around it.
    """
    world = unattached_wall_world(dependency=dependency, transport=transport, resource=resource)
    rng_before = world.rng.get_state()

    log = run_adaptation(world, InfrastructureAdaptationSystem(adaptation_rate=0.0))

    assert_wall_untouched(world, (dependency, transport, resource), log)
    assert world.tick == 5
    assert world.episode == 0
    assert world.rng.get_state() == rng_before


@pytest.mark.parametrize("rate", [0.0, 0.10, 0.5, 1.0])
def test_the_rate_cannot_move_a_wall_with_nothing_attached(rate: float) -> None:
    """Even a full rate has no object to act upon.

    The rate governs how fast infrastructure adapts. With no infrastructure, it
    has nothing to multiply, so it cannot manufacture a change in the wall.
    """
    world = unattached_wall_world(dependency=0.10, transport=0.80, resource=0.20)
    rng_before = world.rng.get_state()

    log = run_adaptation(world, InfrastructureAdaptationSystem(adaptation_rate=rate))

    assert_wall_untouched(world, (0.10, 0.80, 0.20), log)
    assert world.rng.get_state() == rng_before


def test_an_inactive_wall_with_nothing_attached_is_also_untouched() -> None:
    """Both guards hold at once, and neither depends on the other."""
    world = unattached_wall_world(dependency=0.10, transport=0.80, resource=0.20, active=False)
    log = run_adaptation(world)
    assert_wall_untouched(world, (0.10, 0.80, 0.20), log)


def test_an_inactive_wall_with_infrastructure_keeps_divergent_scores() -> None:
    """The mirror case: something attached, but the wall is not standing."""
    world = walled_world(
        active=False,
        wall_dependency=0.10,
        transport=0.80,
        resource=0.20,
        infrastructure=[make_infrastructure("i1", dependency=0.95)],
        tick=5,
    )
    log = run_adaptation(world)

    assert_wall_untouched(world, (0.10, 0.80, 0.20), log)
    assert world.infrastructure["i1"].dependency_score == 0.95


def test_infrastructure_on_a_different_boundary_does_not_count_as_connected() -> None:
    """Connectedness is per boundary, so a neighbour's route is not attachment."""
    world = build_world(
        [build_district("a"), build_district("b"), build_district("c")],
        boundaries=[("lonely", "a", "b"), ("busy", "b", "c")],
        tick=5,
    )
    lonely = build_wall("w_lonely", "lonely", active=True)
    lonely.dependency_score, lonely.transport_dependency, lonely.resource_dependency = (
        0.10,
        0.80,
        0.20,
    )
    world.add_wall(lonely)
    world.add_wall(build_wall("w_busy", "busy", active=True))
    world.add_infrastructure(make_infrastructure("i_busy", "busy"))

    log = run_adaptation(world)

    assert (
        lonely.dependency_score,
        lonely.transport_dependency,
        lonely.resource_dependency,
    ) == (0.10, 0.80, 0.20)
    assert [event.source_id for event in log.query(event_type=EventType.WALL_CHANGED)] == ["w_busy"]


def build_mixed_world(*, unattached_first: bool):
    """Build one adapting wall and one infrastructure-free wall, in a chosen order."""
    world = build_world(
        [build_district(name) for name in ("a", "b", "c")],
        boundaries=[("b_busy", "a", "b"), ("b_lonely", "b", "c")],
        tick=5,
    )

    lonely = build_wall("w_lonely", "b_lonely", active=True)
    lonely.dependency_score, lonely.transport_dependency, lonely.resource_dependency = (
        0.10,
        0.80,
        0.20,
    )
    busy = build_wall("w_busy", "b_busy", active=True)

    for wall in (lonely, busy) if unattached_first else (busy, lonely):
        world.add_wall(wall)
    world.add_infrastructure(
        make_infrastructure("i_busy", "b_busy", kind=InfrastructureType.TRANSIT_ROUTE)
    )
    return world


def test_one_wall_adapts_while_an_unattached_wall_beside_it_does_not() -> None:
    """The mixed case: a real adaptation must not drag an unrelated wall along."""
    world = build_mixed_world(unattached_first=False)
    log = run_adaptation(world)

    assert world.infrastructure["i_busy"].dependency_score == pytest.approx(0.10)
    busy = world.walls["w_busy"]
    assert busy.dependency_score == pytest.approx(0.10)
    assert busy.transport_dependency == pytest.approx(0.10)
    assert busy.resource_dependency == 0.0

    lonely = world.walls["w_lonely"]
    assert (
        lonely.dependency_score,
        lonely.transport_dependency,
        lonely.resource_dependency,
    ) == (0.10, 0.80, 0.20)

    assert [event.source_id for event in log.query(event_type=EventType.WALL_CHANGED)] == ["w_busy"]
    assert [
        event.source_id for event in log.query(event_type=EventType.INFRASTRUCTURE_ADAPTED)
    ] == ["i_busy"]
    assert len(log) == 2


def test_the_mixed_world_is_insertion_order_invariant() -> None:
    """Registering the unattached wall first must change nothing at all."""

    def outcome(unattached_first: bool):
        """Run the mixed world with a chosen wall registration order."""
        world = build_mixed_world(unattached_first=unattached_first)
        log = run_adaptation(world)
        return (
            {
                key: (
                    world.walls[key].dependency_score,
                    world.walls[key].transport_dependency,
                    world.walls[key].resource_dependency,
                )
                for key in sorted(world.walls)
            },
            {
                key: world.infrastructure[key].dependency_score
                for key in sorted(world.infrastructure)
            },
            [(event.type.value, event.source_id, event.payload_as_dict()) for event in log],
        )

    assert outcome(True) == outcome(False)


def test_an_unattached_wall_stays_put_across_many_ticks() -> None:
    """Repetition must not accumulate a change that one tick declined to make."""
    world = unattached_wall_world(dependency=0.10, transport=0.80, resource=0.20)
    system = InfrastructureAdaptationSystem()

    for _ in range(15):
        assert len(run_adaptation(world, system)) == 0

    assert (
        world.walls["w"].dependency_score,
        world.walls["w"].transport_dependency,
        world.walls["w"].resource_dependency,
    ) == (0.10, 0.80, 0.20)


def test_attaching_infrastructure_later_resumes_aggregation() -> None:
    """The guard withholds growth; it does not disable the wall permanently."""
    world = unattached_wall_world(dependency=0.10, transport=0.80, resource=0.20)
    system = InfrastructureAdaptationSystem()
    assert len(run_adaptation(world, system)) == 0

    world.add_infrastructure(
        make_infrastructure("i1", "bnd", kind=InfrastructureType.RESOURCE_ROUTE)
    )
    log = run_adaptation(world, system)

    assert world.infrastructure["i1"].dependency_score == pytest.approx(0.10)
    wall = world.walls["w"]
    assert wall.transport_dependency == 0.80, "the historical category is preserved"
    assert wall.resource_dependency == pytest.approx(0.20)
    assert wall.dependency_score == 0.80, "now legitimately folded in, with infrastructure present"
    assert len(log.query(event_type=EventType.WALL_CHANGED)) == 1
