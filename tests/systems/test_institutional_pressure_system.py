"""Tests for InstitutionalPressureSystem.

Institutional pressure is the state a future boundary decision will act on, so
it has to be bounded, slow, and derived from nothing but the district's own
settled position for the tick. Most of these tests are about what the system
refuses to do: jump, overshoot, reset, launder corrupted state, touch anything
it does not own, or let a district's name affect the answer.
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

from living_diorama.entities import IsolationState, ResourceType
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.systems import InstitutionalPressureSystem
from living_diorama.systems.institutional_pressure_system import _clamp_unit


def run_pressure(world, system=None) -> EventLog:
    """Run one institutional pressure update and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    (system or InstitutionalPressureSystem()).update(world, bus)
    return log


def stressed_district(
    district_id: str = "a",
    *,
    scarcity: float = 1.0,
    fear: float = 1.0,
    trust: float = 0.0,
    institutional_pressure: float = 0.0,
    population: int = 100,
):
    """Build a district with chosen social and material state."""
    return build_district(
        district_id,
        population=population,
        housing_capacity=10_000,
        scarcity=scarcity,
        fear=fear,
        trust=trust,
        institutional_pressure=institutional_pressure,
    )


def score(district, system=None) -> float:
    """Score a lone district and return its resulting institutional pressure."""
    world = build_world([district], tick=1)
    run_pressure(world, system)
    return district.institutional_pressure


def target_of(*, scarcity: float, fear: float, trust: float, system=None) -> float:
    """Return the target a district heads for, by snapping straight to it."""
    district = stressed_district(
        scarcity=scarcity, fear=fear, trust=trust, institutional_pressure=0.0
    )
    return score(
        district,
        system or InstitutionalPressureSystem(response_rate=1.0),
    )


# --- 24. Constructor validation ---------------------------------------------


def test_default_configuration_is_accepted() -> None:
    """The documented defaults are usable without argument."""
    system = InstitutionalPressureSystem()
    assert system.scarcity_weight == 1.0
    assert system.fear_weight == 1.0
    assert system.distrust_weight == 1.0
    assert system.response_rate == 0.20


@pytest.mark.parametrize(
    "weights",
    [(0.0, 1.0, 1.0), (1.0, 0.0, 1.0), (1.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)],
)
def test_any_single_weight_may_be_zero(weights: tuple[float, float, float]) -> None:
    """Ignoring one or two stresses entirely is a legitimate experiment."""
    scarcity, fear, distrust = weights
    assert (
        InstitutionalPressureSystem(
            scarcity_weight=scarcity, fear_weight=fear, distrust_weight=distrust
        )
        is not None
    )


def test_all_three_weights_zero_is_rejected() -> None:
    """With nothing weighted, the target would have nothing to measure."""
    with pytest.raises(ValueError):
        InstitutionalPressureSystem(scarcity_weight=0.0, fear_weight=0.0, distrust_weight=0.0)


@pytest.mark.parametrize("field", ["scarcity_weight", "fear_weight", "distrust_weight"])
def test_negative_weights_are_rejected(field: str) -> None:
    """A negative weight would make hardship reduce institutional pressure."""
    with pytest.raises(ValueError):
        InstitutionalPressureSystem(**{field: -0.1})


@pytest.mark.parametrize("field", ["scarcity_weight", "fear_weight", "distrust_weight"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_weights_are_rejected(field: str, bad: float) -> None:
    """NaN and the infinities cannot describe a relative importance."""
    with pytest.raises(ValueError):
        InstitutionalPressureSystem(**{field: bad})


@pytest.mark.parametrize("field", ["scarcity_weight", "fear_weight", "distrust_weight"])
@pytest.mark.parametrize("bad", [True, False, "1.0", None])
def test_non_numeric_and_boolean_weights_are_rejected(field: str, bad: object) -> None:
    """Bool subclasses int, so True would silently mean a weight of 1.0."""
    with pytest.raises(TypeError):
        InstitutionalPressureSystem(**{field: bad})


def test_response_rate_boundaries_are_accepted() -> None:
    """Zero and one are both meaningful settings, not edge-case failures."""
    assert InstitutionalPressureSystem(response_rate=0.0).response_rate == 0.0
    assert InstitutionalPressureSystem(response_rate=1.0).response_rate == 1.0


@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), float("inf"), float("-inf")])
def test_invalid_response_rates_are_rejected(bad: float) -> None:
    """A rate is a share of a gap, so it cannot fall outside the whole gap."""
    with pytest.raises(ValueError):
        InstitutionalPressureSystem(response_rate=bad)


@pytest.mark.parametrize("bad", [True, False, "0.2", None])
def test_non_numeric_and_boolean_response_rates_are_rejected(bad: object) -> None:
    """The rate must be a real number, not a bool or a string."""
    with pytest.raises(TypeError):
        InstitutionalPressureSystem(response_rate=bad)


def test_extreme_finite_weights_are_accepted() -> None:
    """A finite non-negative weight is valid however large or small it is."""
    assert (
        InstitutionalPressureSystem(scarcity_weight=1e308, fear_weight=1e308, distrust_weight=1e308)
        is not None
    )
    assert (
        InstitutionalPressureSystem(
            scarcity_weight=5e-324, fear_weight=5e-324, distrust_weight=5e-324
        )
        is not None
    )


# --- 25. The target formula -------------------------------------------------


def test_no_stress_produces_no_target_pressure() -> None:
    """Nothing scarce, nobody afraid, everybody trusting: nothing to respond to."""
    assert target_of(scarcity=0.0, fear=0.0, trust=1.0) == 0.0


def test_total_stress_produces_maximum_target_pressure() -> None:
    """Every stress at its limit is total pressure to act."""
    assert target_of(scarcity=1.0, fear=1.0, trust=0.0) == 1.0


def test_evenly_mixed_stress_produces_the_midpoint() -> None:
    """Half of each, weighted equally, is exactly half."""
    assert target_of(scarcity=0.5, fear=0.5, trust=0.5) == pytest.approx(0.5)


def test_scarcity_only_weighting_ignores_the_social_state() -> None:
    """A district's alarm is irrelevant when only material exposure is weighted."""
    system = InstitutionalPressureSystem(
        scarcity_weight=1.0, fear_weight=0.0, distrust_weight=0.0, response_rate=1.0
    )
    assert target_of(scarcity=0.4, fear=1.0, trust=0.0, system=system) == pytest.approx(0.4)


def test_fear_only_weighting_ignores_scarcity_and_distrust() -> None:
    """Only accumulated alarm counts when only fear is weighted."""
    system = InstitutionalPressureSystem(
        scarcity_weight=0.0, fear_weight=1.0, distrust_weight=0.0, response_rate=1.0
    )
    assert target_of(scarcity=1.0, fear=0.3, trust=1.0, system=system) == pytest.approx(0.3)


def test_distrust_only_weighting_reads_the_inverse_of_trust() -> None:
    """Distrust is derived, never stored, and is exactly what trust is not."""
    system = InstitutionalPressureSystem(
        scarcity_weight=0.0, fear_weight=0.0, distrust_weight=1.0, response_rate=1.0
    )
    assert target_of(scarcity=1.0, fear=1.0, trust=0.75, system=system) == pytest.approx(0.25)


def test_unequal_weighting_leans_toward_the_heavier_stress() -> None:
    """Weighting scarcity more heavily pulls the target toward scarcity."""
    heavy_scarcity = InstitutionalPressureSystem(
        scarcity_weight=3.0, fear_weight=1.0, distrust_weight=1.0, response_rate=1.0
    )
    heavy_fear = InstitutionalPressureSystem(
        scarcity_weight=1.0, fear_weight=3.0, distrust_weight=1.0, response_rate=1.0
    )
    # scarcity 1.0, fear 0.0, trust 1.0 -> distrust 0.0
    assert target_of(scarcity=1.0, fear=0.0, trust=1.0, system=heavy_scarcity) > target_of(
        scarcity=1.0, fear=0.0, trust=1.0, system=heavy_fear
    )


def test_rising_scarcity_never_lowers_the_target() -> None:
    """Monotonic in material exposure, all else fixed."""
    targets = [
        target_of(scarcity=value, fear=0.3, trust=0.7) for value in (0.0, 0.2, 0.5, 0.8, 1.0)
    ]
    assert targets == sorted(targets)
    assert targets[-1] > targets[0]


def test_rising_fear_never_lowers_the_target() -> None:
    """Monotonic in accumulated alarm, all else fixed."""
    targets = [
        target_of(scarcity=0.3, fear=value, trust=0.7) for value in (0.0, 0.2, 0.5, 0.8, 1.0)
    ]
    assert targets == sorted(targets)
    assert targets[-1] > targets[0]


def test_falling_trust_never_lowers_the_target() -> None:
    """Monotonic in lost confidence, all else fixed."""
    targets = [
        target_of(scarcity=0.3, fear=0.3, trust=value) for value in (1.0, 0.8, 0.5, 0.2, 0.0)
    ]
    assert targets == sorted(targets)
    assert targets[-1] > targets[0]


# --- 26. Weight scale invariance --------------------------------------------


def target_under_weights(weights: tuple[float, float, float]) -> float:
    """Return the target for fixed inputs under one weighting."""
    scarcity_weight, fear_weight, distrust_weight = weights
    system = InstitutionalPressureSystem(
        scarcity_weight=scarcity_weight,
        fear_weight=fear_weight,
        distrust_weight=distrust_weight,
        response_rate=1.0,
    )
    return target_of(scarcity=0.8, fear=0.4, trust=0.9, system=system)


@pytest.mark.parametrize(
    "weights",
    [
        (10.0, 10.0, 10.0),
        (1e8, 1e8, 1e8),
        (1e308, 1e308, 1e308),
        (5e-324, 5e-324, 5e-324),
        (1e-200, 1e-200, 1e-200),
    ],
)
def test_equal_weights_mean_the_same_at_any_finite_scale(
    weights: tuple[float, float, float],
) -> None:
    """Summing huge weights overflows and multiplying tiny ones underflows.

    Either would drive the target to zero and report a stressed district as
    untroubled, so the weights are normalized by the largest of them before any
    arithmetic. Only the ratio was ever meaningful.
    """
    assert target_under_weights(weights) == pytest.approx(target_under_weights((1.0, 1.0, 1.0)))


def test_unequal_ratios_survive_large_finite_scaling() -> None:
    """A 4:2:1 weighting means the same written small or enormous."""
    ordinary = target_under_weights((1.0, 0.5, 0.25))
    scaled = target_under_weights((1e308, 5e307, 2.5e307))
    assert scaled == pytest.approx(ordinary)


def test_huge_weights_do_not_collapse_a_stressed_district_to_zero() -> None:
    """The concrete failure the normalization prevents."""
    system = InstitutionalPressureSystem(
        scarcity_weight=1e308, fear_weight=1e308, distrust_weight=1e308, response_rate=1.0
    )
    assert target_of(scarcity=1.0, fear=1.0, trust=0.0, system=system) == pytest.approx(1.0)


def test_tiny_weights_do_not_collapse_a_stressed_district_to_zero() -> None:
    """The mirror failure, at the other end of the float range."""
    system = InstitutionalPressureSystem(
        scarcity_weight=5e-324, fear_weight=5e-324, distrust_weight=5e-324, response_rate=1.0
    )
    assert target_of(scarcity=1.0, fear=1.0, trust=0.0, system=system) == pytest.approx(1.0)


# --- 27. Response rate ------------------------------------------------------


def test_response_rate_zero_changes_nothing_and_emits_nothing() -> None:
    """A frozen institutional layer is a valid configuration, not an absent one."""
    district = stressed_district(institutional_pressure=0.3)
    world = build_world([district], tick=1)
    log = run_pressure(world, InstitutionalPressureSystem(response_rate=0.0))

    assert district.institutional_pressure == 0.3
    assert len(log) == 0


def test_response_rate_one_reaches_the_target_immediately() -> None:
    """The only setting under which institutional pressure may jump."""
    district = stressed_district(institutional_pressure=0.0)
    assert score(district, InstitutionalPressureSystem(response_rate=1.0)) == pytest.approx(1.0)


def test_default_rate_closes_exactly_one_fifth_of_the_gap_upward() -> None:
    """Rising pressure moves a fifth of the way, not all of it."""
    district = stressed_district(institutional_pressure=0.2)
    assert score(district) == pytest.approx(0.2 + 0.20 * (1.0 - 0.2))


def test_default_rate_closes_exactly_one_fifth_of_the_gap_downward() -> None:
    """Falling pressure is governed by the same rule as rising pressure."""
    district = stressed_district(scarcity=0.0, fear=0.0, trust=1.0, institutional_pressure=0.8)
    assert score(district) == pytest.approx(0.8 + 0.20 * (0.0 - 0.8))


def test_a_tiny_positive_response_rate_is_not_treated_as_zero() -> None:
    """A representable movement is a real movement and is recorded.

    Suppressing a change this small with a tolerance would silently reconfigure
    the system to a zero rate, freezing the district forever while appearing to
    be set up to move.
    """
    district = stressed_district(institutional_pressure=0.0)
    world = build_world([district], tick=1)
    log = run_pressure(world, InstitutionalPressureSystem(response_rate=1e-10))

    assert district.institutional_pressure == pytest.approx(1e-10)
    assert district.institutional_pressure > 0.0
    assert len(log) == 1


def test_a_tiny_response_rate_still_makes_monotonic_progress() -> None:
    """Repeated ticks at a tiny rate accumulate rather than freezing."""
    district = stressed_district(institutional_pressure=0.0)
    world = build_world([district], tick=1)
    system = InstitutionalPressureSystem(response_rate=1e-6)

    values = [district.institutional_pressure]
    for _ in range(10):
        run_pressure(world, system)
        values.append(district.institutional_pressure)

    assert values == sorted(values)
    assert values[-1] > values[0]
    assert all(0.0 <= value <= 1.0 for value in values)


# --- 28. Institutional memory and recovery ----------------------------------


def test_pressure_rises_monotonically_toward_a_constant_target() -> None:
    """Under constant stress the approach is monotone and never overshoots."""
    district = stressed_district(institutional_pressure=0.0)
    world = build_world([district], tick=1)
    system = InstitutionalPressureSystem()

    values = [district.institutional_pressure]
    for _ in range(40):
        run_pressure(world, system)
        values.append(district.institutional_pressure)

    assert values == sorted(values)
    assert all(value <= 1.0 for value in values)
    assert values[-1] == pytest.approx(1.0, abs=1e-3)
    assert all(math.isfinite(value) for value in values)


def test_pressure_lags_behind_a_sudden_improvement() -> None:
    """Institutions do not stand down the instant conditions improve.

    The stored value is the entire memory: no history is kept inside the system.
    """
    district = stressed_district(institutional_pressure=0.0)
    world = build_world([district], tick=1)
    system = InstitutionalPressureSystem()

    for _ in range(20):
        run_pressure(world, system)
    elevated = district.institutional_pressure
    assert elevated > 0.9

    district.scarcity = 0.0
    district.fear = 0.0
    district.trust = 1.0

    run_pressure(world, system)
    assert district.institutional_pressure < elevated
    assert district.institutional_pressure > 0.5, "one good tick must not reset the memory"

    for _ in range(30):
        run_pressure(world, system)
    assert district.institutional_pressure == pytest.approx(0.0, abs=1e-2)


def test_recovery_is_gradual_rather_than_instant_under_the_default_rate() -> None:
    """Falling pressure descends in steps and stays above the new target early on."""
    district = stressed_district(scarcity=0.0, fear=0.0, trust=1.0, institutional_pressure=1.0)
    world = build_world([district], tick=1)
    system = InstitutionalPressureSystem()

    values = [district.institutional_pressure]
    for _ in range(5):
        run_pressure(world, system)
        values.append(district.institutional_pressure)

    assert values == sorted(values, reverse=True)
    assert all(value > 0.0 for value in values)
    assert values[-1] > 0.0, "the default rate must not reset pressure to the target"


def test_a_district_already_at_its_target_is_left_alone() -> None:
    """Equilibrium means no mutation and no event."""
    district = stressed_district(scarcity=0.5, fear=0.5, trust=0.5, institutional_pressure=0.5)
    world = build_world([district], tick=1)
    log = run_pressure(world)

    assert district.institutional_pressure == 0.5
    assert len(log) == 0


# --- 29. Zero population ----------------------------------------------------


def test_zero_population_preserves_pressure_and_emits_nothing() -> None:
    """An empty district keeps the institutional history it had."""
    district = stressed_district(population=0, institutional_pressure=0.7)
    world = build_world([district], tick=1)
    rng_before = world.rng.get_state()
    log = run_pressure(world)

    assert district.institutional_pressure == 0.7
    assert len(log) == 0
    assert world.rng.get_state() == rng_before


def test_a_zero_population_district_with_corrupted_inputs_is_not_read() -> None:
    """Inputs of an empty district are never touched, so corruption cannot bite."""
    empty = stressed_district("empty", population=0, institutional_pressure=0.7)
    empty.fear = "corrupt"  # type: ignore[assignment]
    healthy = stressed_district("healthy", institutional_pressure=0.0)
    world = build_world([empty, healthy], tick=1)

    log = run_pressure(world)

    assert empty.institutional_pressure == 0.7
    assert healthy.institutional_pressure > 0.0
    assert len(log) == 1


def test_an_empty_district_does_not_change_another_district_result() -> None:
    """Emptiness next door is not an institutional input."""

    def pressure_with(neighbour_population: int) -> float:
        """Score 'target' beside a neighbour of a chosen population."""
        neighbour = stressed_district("neighbour", population=neighbour_population)
        subject = stressed_district("target", institutional_pressure=0.1)
        world = build_world([neighbour, subject], tick=1)
        run_pressure(world)
        return subject.institutional_pressure

    assert pressure_with(0) == pressure_with(500)


# --- 30. Corrupted stored state ---------------------------------------------

CORRUPTED_VALUES = [True, False, "0.5", float("nan"), float("inf"), float("-inf"), -0.1, 1.1]
"""Stored values that must never be accepted, whatever their apparent plausibility.

The booleans and the numeric string are the dangerous ones: each converts
silently into an ordinary float inside the permitted interval, so a validator
shown the converted value would have nothing to object to.
"""

INPUT_FIELDS = ["scarcity", "fear", "trust", "institutional_pressure"]


def expected_error(bad: object) -> type[Exception]:
    """Return the precise exception a given corruption must raise."""
    if type(bad) is bool or not isinstance(bad, int | float):
        return TypeError
    return ValueError


@pytest.mark.parametrize("field", INPUT_FIELDS)
@pytest.mark.parametrize("bad", CORRUPTED_VALUES)
def test_corrupted_stored_input_fails_fast(field: str, bad: object) -> None:
    """Every input is validated as found, never after a repairing conversion."""
    district = stressed_district(institutional_pressure=0.2)
    setattr(district, field, bad)
    world = build_world([district], tick=1)

    with pytest.raises(expected_error(bad)):
        run_pressure(world)
    assert getattr(district, field) is bad or getattr(district, field) == bad


def build_corrupted_pair(field: str, bad: object, *, corrupted_first: bool):
    """Build a healthy district beside a corrupted one, in a chosen sort order."""
    corrupted_id = "a_corrupt" if corrupted_first else "z_corrupt"
    healthy = stressed_district("m_healthy", institutional_pressure=0.2)
    corrupted = stressed_district(corrupted_id, institutional_pressure=0.2)
    setattr(corrupted, field, bad)

    districts = [corrupted, healthy] if corrupted_first else [healthy, corrupted]
    return build_world(districts, tick=1), healthy, corrupted


@pytest.mark.parametrize("field", INPUT_FIELDS)
@pytest.mark.parametrize("corrupted_first", [True, False])
def test_a_corrupted_district_aborts_the_whole_update(field: str, corrupted_first: bool) -> None:
    """Staging means one bad district leaves every other district untouched.

    A partially applied tick would be worse than no tick at all: half the world
    would have moved and nothing would record which half.
    """
    world, healthy, corrupted = build_corrupted_pair(field, "0.5", corrupted_first=corrupted_first)
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)

    with pytest.raises(TypeError):
        InstitutionalPressureSystem().update(world, bus)

    assert healthy.institutional_pressure == 0.2
    assert getattr(corrupted, field) == "0.5"
    assert len(log) == 0


def test_a_corrupted_district_in_the_middle_also_aborts_cleanly() -> None:
    """The abort holds wherever the bad district falls in the traversal."""
    first = stressed_district("a_first", institutional_pressure=0.2)
    middle = stressed_district("m_middle", institutional_pressure=0.2)
    middle.trust = True  # type: ignore[assignment]
    last = stressed_district("z_last", institutional_pressure=0.2)
    world = build_world([first, middle, last], tick=1)

    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    with pytest.raises(TypeError):
        InstitutionalPressureSystem().update(world, bus)

    assert first.institutional_pressure == 0.2
    assert last.institutional_pressure == 0.2
    assert middle.trust is True
    assert len(log) == 0


@pytest.mark.parametrize("bad", [2.0, -1.0, 1.5, float("nan"), float("inf")])
def test_meaningful_out_of_range_results_are_rejected(bad: float) -> None:
    """A value far outside the interval is a defect, not a value to tidy away."""
    with pytest.raises(ValueError):
        _clamp_unit(bad, "test")


def test_one_ulp_residue_is_flattened() -> None:
    """The single bit a division can lose is exactly what may be tidied."""
    assert _clamp_unit(math.nextafter(0.0, -math.inf), "test") == 0.0
    assert _clamp_unit(math.nextafter(1.0, math.inf), "test") == 1.0
    assert _clamp_unit(0.5, "test") == 0.5


def test_just_beyond_one_ulp_is_rejected() -> None:
    """The residue window is exactly one ULP wide, not a soft tolerance."""
    with pytest.raises(ValueError):
        _clamp_unit(math.nextafter(math.nextafter(0.0, -math.inf), -math.inf), "test")
    with pytest.raises(ValueError):
        _clamp_unit(math.nextafter(math.nextafter(1.0, math.inf), math.inf), "test")


def test_valid_integer_stored_values_are_accepted() -> None:
    """Rejecting bool must not also reject an honest int at an interval boundary."""
    district = build_district(
        "a", population=10, scarcity=0, fear=0, trust=1, institutional_pressure=0
    )
    world = build_world([district], tick=1)
    run_pressure(world)
    assert 0.0 <= district.institutional_pressure <= 1.0


# --- 31. Events -------------------------------------------------------------


def test_one_event_per_changed_district() -> None:
    """Each district that moves reports once, in sorted identifier order."""
    world = build_world(
        [
            stressed_district("a", institutional_pressure=0.0),
            stressed_district("b", scarcity=0.5, fear=0.5, trust=0.5, institutional_pressure=0.0),
        ],
        tick=7,
    )
    log = run_pressure(world)

    assert len(log) == 2
    assert [event.source_id for event in log] == ["a", "b"]
    for event in log:
        assert event.type is EventType.INSTITUTIONAL_PRESSURE_CHANGED
        assert event.tick == 7


def test_unchanged_and_empty_districts_produce_no_events() -> None:
    """Only real movement is recorded."""
    world = build_world(
        [
            stressed_district("moves", institutional_pressure=0.0),
            stressed_district(
                "settled", scarcity=0.5, fear=0.5, trust=0.5, institutional_pressure=0.5
            ),
            stressed_district("empty", population=0, institutional_pressure=0.3),
        ],
        tick=1,
    )
    log = run_pressure(world)
    assert [event.source_id for event in log] == ["moves"]


def test_event_payload_matches_the_calculation_and_is_json_safe() -> None:
    """Every reported number is the one that was actually used."""
    district = stressed_district(scarcity=0.8, fear=0.4, trust=0.9, institutional_pressure=0.1)
    world = build_world([district], tick=3)
    payload = run_pressure(world).events()[0].payload_as_dict()

    expected_target = (0.8 + 0.4 + (1.0 - 0.9)) / 3.0
    assert payload["district_id"] == "a"
    assert payload["scarcity"] == 0.8
    assert payload["fear"] == 0.4
    assert payload["trust"] == 0.9
    assert payload["distrust"] == pytest.approx(0.1)
    assert payload["social_stability"] == pytest.approx((0.9 + 0.6) / 2.0)
    assert payload["social_strain"] == pytest.approx(1.0 - (0.9 + 0.6) / 2.0)
    assert payload["scarcity_weight"] == 1.0
    assert payload["fear_weight"] == 1.0
    assert payload["distrust_weight"] == 1.0
    assert payload["response_rate"] == 0.20
    assert payload["target_institutional_pressure"] == pytest.approx(expected_target)
    assert payload["previous_institutional_pressure"] == 0.1
    assert payload["new_institutional_pressure"] == pytest.approx(
        0.1 + 0.20 * (expected_target - 0.1)
    )
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


def test_event_payload_is_immutable_after_construction() -> None:
    """A published reading is history and cannot be edited."""
    world = build_world([stressed_district(institutional_pressure=0.0)], tick=1)
    payload = run_pressure(world).events()[0].payload

    with pytest.raises(TypeError):
        payload["new_institutional_pressure"] = 0.0  # type: ignore[index]


def test_event_payload_contains_only_finite_primitives() -> None:
    """No enums, entities, sets, or dataclasses reach the recorded history."""
    world = build_world([stressed_district(institutional_pressure=0.0)], tick=1)
    for event in run_pressure(world):
        for key, value in event.payload_as_dict().items():
            assert isinstance(key, str)
            assert isinstance(value, str | int | float)
            if isinstance(value, float):
                assert math.isfinite(value)


# --- 32. Mutation isolation -------------------------------------------------


def test_only_institutional_pressure_is_ever_written() -> None:
    """Everything else in the world is read-only to this system."""
    district = build_district(
        "a",
        population=100,
        housing_capacity=50,
        production_rate=3.0,
        consumption_rate=2.0,
        food=7.0,
        scarcity=1.0,
        fear=0.8,
        trust=0.2,
        institutional_pressure=0.1,
    )
    world = build_world(
        [district, build_district("b")],
        boundaries=[("bound", "a", "b")],
        law=build_law(),
        tick=5,
    )
    world.add_wall(build_wall("wall", "bound", active=True))
    world.add_infrastructure(build_infrastructure("infra", "bound"))

    before_pool = district.resources
    before_stock = {r: district.resources.amount_of(r) for r in ResourceType}
    rng_before = world.rng.get_state()

    run_pressure(world)

    assert district.population == 100
    assert district.housing_capacity == 50
    assert district.production_rate == 3.0
    assert district.consumption_rate == 2.0
    assert district.scarcity == 1.0
    assert district.fear == 0.8
    assert district.trust == 0.2
    assert district.isolation_state is IsolationState.OPEN
    assert district.resources is before_pool
    for resource, amount in before_stock.items():
        assert district.resources.amount_of(resource) == amount

    assert world.tick == 5
    assert world.episode == 0
    assert world.rng.get_state() == rng_before
    assert world.laws["law_movement_sharing"].current_value is True
    assert world.walls["wall"].active is True
    assert world.boundaries["bound"].wall_id == "wall"
    assert world.infrastructure["infra"].dependency_score == 0.0
    assert district.institutional_pressure > 0.1


def test_the_system_does_not_advance_the_tick() -> None:
    """Tick progression belongs to SimulationLoop alone."""
    world = build_world([stressed_district(institutional_pressure=0.0)], tick=9)
    run_pressure(world)
    assert world.tick == 9


# --- 33. Determinism and invariance -----------------------------------------


def test_repeated_runs_on_identical_worlds_agree_exactly() -> None:
    """The same inputs give the same institutional state, every time."""
    results = []
    for _ in range(3):
        world = build_world(
            [
                stressed_district(
                    "a", scarcity=0.7, fear=0.3, trust=0.6, institutional_pressure=0.2
                ),
                stressed_district(
                    "b", scarcity=0.1, fear=0.9, trust=0.1, institutional_pressure=0.4
                ),
            ],
            tick=1,
        )
        log = run_pressure(world)
        results.append(
            (
                {key: world.districts[key].institutional_pressure for key in ("a", "b")},
                [event.payload_as_dict() for event in log],
            )
        )
    assert results[0] == results[1] == results[2]


def test_rng_state_is_untouched() -> None:
    """This system decides nothing by chance."""
    world = build_world([stressed_district(institutional_pressure=0.0)], tick=1)
    before = world.rng.get_state()
    run_pressure(world)
    assert world.rng.get_state() == before


def test_registration_order_does_not_change_the_result() -> None:
    """Insertion order is not part of the simulation's meaning."""

    def build(reverse: bool):
        """Build the same districts in a chosen registration order."""
        districts = [
            stressed_district("a", scarcity=0.6, fear=0.1, trust=0.9, institutional_pressure=0.1),
            stressed_district("b", scarcity=0.2, fear=0.8, trust=0.2, institutional_pressure=0.5),
            stressed_district("c", scarcity=1.0, fear=0.5, trust=0.5, institutional_pressure=0.9),
        ]
        return build_world(list(reversed(districts)) if reverse else districts, tick=1)

    forward, backward = build(False), build(True)
    run_pressure(forward)
    run_pressure(backward)

    for district_id in ("a", "b", "c"):
        assert (
            forward.districts[district_id].institutional_pressure
            == backward.districts[district_id].institutional_pressure
        )


def test_renaming_districts_does_not_change_their_pressure() -> None:
    """Identifiers are labels, never institutional priority."""

    def build(names: tuple[str, str]):
        """Build two districts under a chosen pair of names."""
        first, second = names
        return build_world(
            [
                stressed_district(
                    first, scarcity=0.6, fear=0.1, trust=0.9, institutional_pressure=0.1
                ),
                stressed_district(
                    second, scarcity=0.2, fear=0.8, trust=0.2, institutional_pressure=0.5
                ),
            ],
            tick=1,
        )

    original = build(("aaa", "zzz"))
    renamed = build(("zzz", "aaa"))
    run_pressure(original)
    run_pressure(renamed)

    assert (
        original.districts["aaa"].institutional_pressure
        == renamed.districts["zzz"].institutional_pressure
    )
    assert (
        original.districts["zzz"].institutional_pressure
        == renamed.districts["aaa"].institutional_pressure
    )


def test_events_follow_sorted_district_order() -> None:
    """Event order is fixed by identifier, which is all identifiers decide."""
    world = build_world(
        [
            stressed_district("zulu", institutional_pressure=0.0),
            stressed_district("alpha", institutional_pressure=0.0),
            stressed_district("mike", institutional_pressure=0.0),
        ],
        tick=1,
    )
    log = run_pressure(world)
    assert [event.source_id for event in log] == ["alpha", "mike", "zulu"]


# --- 22. Multi-district independence ----------------------------------------


def test_one_district_does_not_influence_another() -> None:
    """There is no institutional coordination between districts in this phase."""

    def score_b(neighbour_scarcity: float, neighbour_pressure: float) -> float:
        """Score district 'b' beside a neighbour in a chosen state."""
        world = build_world(
            [
                stressed_district(
                    "a", scarcity=neighbour_scarcity, institutional_pressure=neighbour_pressure
                ),
                stressed_district(
                    "b", scarcity=0.4, fear=0.3, trust=0.7, institutional_pressure=0.2
                ),
            ],
            boundaries=[("bound", "a", "b")],
            tick=1,
        )
        run_pressure(world)
        return world.districts["b"].institutional_pressure

    assert score_b(0.0, 0.0) == score_b(1.0, 1.0)


def test_the_system_never_reads_world_topology() -> None:
    """Boundaries, walls, and laws are not institutional inputs in this phase.

    Parsed from the code rather than matched in the text, so a docstring saying
    the system does not consult them cannot be mistaken for it consulting them.
    """
    import ast  # noqa: PLC0415
    import pathlib  # noqa: PLC0415

    import living_diorama.systems.institutional_pressure_system as module  # noqa: PLC0415

    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "world"
    }
    assert attributes <= {"districts", "tick"}


def test_system_holds_no_per_tick_state() -> None:
    """Configuration only; nothing from one tick survives into the next."""
    assert not hasattr(InstitutionalPressureSystem(), "__dict__")


def test_empty_world_scores_nothing_and_emits_nothing() -> None:
    """A world with no districts is valid and simply has no institutions."""
    assert len(run_pressure(build_world([], tick=1))) == 0


# --- 34. Randomized adversarial sweep ---------------------------------------


def test_generated_combinations_stay_bounded_and_finite() -> None:
    """A bounded seeded sweep over the whole valid input space.

    Deliberately small enough for the ordinary test run, and deterministic, so
    a failure is reproducible rather than a story about one unlucky run.
    """
    rng = random.Random(20260806)

    for _ in range(320):
        scarcity = round(rng.random(), 6)
        fear = round(rng.random(), 6)
        trust = round(rng.random(), 6)
        previous = round(rng.random(), 6)
        weights = [rng.choice([0.0, 0.25, 1.0, 9.5, 1e6]) for _ in range(3)]
        if all(weight == 0.0 for weight in weights):
            continue
        response_rate = rng.choice([0.0, 0.05, 0.2, 0.5, 1.0])

        district = build_district(
            "a",
            population=rng.choice([1, 10, 4321]),
            scarcity=scarcity,
            fear=fear,
            trust=trust,
            institutional_pressure=previous,
        )
        world = build_world([district], tick=1)
        rng_before = world.rng.get_state()
        system = InstitutionalPressureSystem(
            scarcity_weight=weights[0],
            fear_weight=weights[1],
            distrust_weight=weights[2],
            response_rate=response_rate,
        )
        log = run_pressure(world, system)

        distrust = 1.0 - trust
        assert math.isfinite(distrust)
        assert 0.0 <= distrust <= 1.0
        assert math.isfinite(district.institutional_pressure)
        assert 0.0 <= district.institutional_pressure <= 1.0

        assert world.rng.get_state() == rng_before
        assert world.tick == 1
        assert district.scarcity == scarcity
        assert district.fear == fear
        assert district.trust == trust
        if response_rate == 0.0:
            assert district.institutional_pressure == previous
            assert len(log) == 0

        for event in log:
            payload = event.payload_as_dict()
            for value in payload.values():
                if isinstance(value, float):
                    assert math.isfinite(value)
            assert 0.0 <= float(payload["target_institutional_pressure"]) <= 1.0


def test_generated_cases_are_reproducible() -> None:
    """The same generated case run twice gives the same answer twice."""
    rng = random.Random(31337)

    for _ in range(60):
        spec = {
            "scarcity": round(rng.random(), 4),
            "fear": round(rng.random(), 4),
            "trust": round(rng.random(), 4),
            "institutional_pressure": round(rng.random(), 4),
        }
        outcomes = []
        for _ in range(2):
            district = build_district("a", population=10, **spec)  # type: ignore[arg-type]
            world = build_world([district], tick=1)
            run_pressure(world)
            outcomes.append(district.institutional_pressure)
        assert outcomes[0] == outcomes[1]


def test_generated_pairs_are_order_invariant() -> None:
    """Reordering two generated districts never changes either one's outcome."""
    rng = random.Random(4242)

    for _ in range(60):
        specs = [
            {
                "scarcity": round(rng.random(), 4),
                "fear": round(rng.random(), 4),
                "trust": round(rng.random(), 4),
                "institutional_pressure": round(rng.random(), 4),
            }
            for _ in range(2)
        ]

        outcomes = []
        for order in itertools.permutations(range(2)):
            districts = [
                build_district(f"d{index}", population=10, **specs[index])  # type: ignore[arg-type]
                for index in order
            ]
            world = build_world(districts, tick=1)
            run_pressure(world)
            outcomes.append(
                {key: world.districts[key].institutional_pressure for key in ("d0", "d1")}
            )
        assert outcomes[0] == outcomes[1]
