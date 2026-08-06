"""Tests for SocialStabilitySystem.

Fear and trust are the district state a later institutional phase will act on,
so they have to be bounded, path-dependent, and derived from nothing but the
district's own settled position for the tick. Most of these tests are about
what the system refuses to do: jump, oscillate, overshoot, touch anything it
does not own, or let a district's name affect how it feels.
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
from living_diorama.systems import SocialStabilitySystem
from living_diorama.systems._resource_config import FLOAT_TOLERANCE
from living_diorama.systems.social_stability_system import (
    _clamp_unit,
    housing_pressure,
    social_stability_of,
)


def run_social(world, system=None) -> EventLog:
    """Run one social stability update and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    (system or SocialStabilitySystem()).update(world, bus)
    return log


def score_one(district, system=None) -> tuple[float, float]:
    """Score a lone district and return its resulting fear and trust."""
    world = build_world([district], tick=1)
    run_social(world, system)
    return district.fear, district.trust


# --- 15.1 Constructor validation -------------------------------------------


def test_default_configuration_is_accepted() -> None:
    """The documented defaults are usable without argument."""
    system = SocialStabilitySystem()
    assert system.scarcity_weight == 1.0
    assert system.housing_pressure_weight == 1.0
    assert system.response_rate == 0.25


def test_a_single_zero_weight_is_accepted() -> None:
    """Ignoring one pressure entirely is a legitimate experiment."""
    assert SocialStabilitySystem(scarcity_weight=0.0, housing_pressure_weight=1.0) is not None
    assert SocialStabilitySystem(scarcity_weight=1.0, housing_pressure_weight=0.0) is not None


def test_both_weights_zero_is_rejected() -> None:
    """With nothing weighted, social pressure would have nothing to measure."""
    with pytest.raises(ValueError):
        SocialStabilitySystem(scarcity_weight=0.0, housing_pressure_weight=0.0)


def test_negative_weights_are_rejected() -> None:
    """A negative weight would make hardship reduce fear."""
    with pytest.raises(ValueError):
        SocialStabilitySystem(scarcity_weight=-0.1)
    with pytest.raises(ValueError):
        SocialStabilitySystem(housing_pressure_weight=-1.0)


def test_non_finite_weights_are_rejected() -> None:
    """NaN and the infinities cannot describe a relative importance."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            SocialStabilitySystem(scarcity_weight=bad)
        with pytest.raises(ValueError):
            SocialStabilitySystem(housing_pressure_weight=bad)


def test_non_numeric_and_boolean_weights_are_rejected() -> None:
    """Bool subclasses int, so True would silently mean a weight of 1.0."""
    for bad in (True, "1.0", None):
        with pytest.raises(TypeError):
            SocialStabilitySystem(scarcity_weight=bad)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            SocialStabilitySystem(housing_pressure_weight=bad)  # type: ignore[arg-type]


def test_response_rate_boundaries_are_accepted() -> None:
    """Zero and one are both meaningful settings, not edge-case failures."""
    assert SocialStabilitySystem(response_rate=0.0).response_rate == 0.0
    assert SocialStabilitySystem(response_rate=1.0).response_rate == 1.0


def test_response_rate_outside_the_unit_interval_is_rejected() -> None:
    """A rate is a share of a gap, so it cannot exceed the whole gap."""
    for bad in (-0.1, 1.1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            SocialStabilitySystem(response_rate=bad)


def test_non_numeric_and_boolean_response_rate_is_rejected() -> None:
    """The rate must be a real number, not a bool or a string."""
    for bad in (True, "0.25", None):
        with pytest.raises(TypeError):
            SocialStabilitySystem(response_rate=bad)  # type: ignore[arg-type]


# --- 15.2 Housing pressure --------------------------------------------------


def test_housing_pressure_is_zero_while_everybody_fits() -> None:
    """Room to spare, or an exact fit, is not overcrowding."""
    assert housing_pressure(50, 100) == 0.0
    assert housing_pressure(100, 100) == 0.0


def test_housing_pressure_is_the_unhoused_share() -> None:
    """Half the district unhoused is a pressure of one half."""
    assert housing_pressure(100, 50) == pytest.approx(0.5)
    assert housing_pressure(100, 90) == pytest.approx(0.1)


def test_housing_pressure_saturates_at_one() -> None:
    """No capacity at all is total overcrowding, however large the district."""
    assert housing_pressure(100, 0) == 1.0
    assert housing_pressure(1_000_000, 0) == 1.0


def test_housing_pressure_rises_with_over_capacity_population() -> None:
    """More people against fixed housing is monotonically more pressure."""
    scores = [housing_pressure(population, 50) for population in (50, 60, 80, 100, 500)]
    assert scores == sorted(scores)
    assert scores[0] == 0.0
    assert scores[-1] > scores[1]


def test_housing_pressure_of_an_empty_district_is_zero() -> None:
    """An empty district is not overcrowded, and must not divide by zero."""
    assert housing_pressure(0, 0) == 0.0
    assert housing_pressure(0, 100) == 0.0


# --- 15.3 Zero population ---------------------------------------------------


def test_zero_population_preserves_social_state_and_emits_nothing() -> None:
    """An empty district keeps the social history it had; nobody is left to feel."""
    district = build_district(
        "empty", population=0, housing_capacity=0, scarcity=1.0, fear=0.4, trust=0.6
    )
    world = build_world([district], tick=1)
    log = run_social(world)

    assert district.fear == 0.4
    assert district.trust == 0.6
    assert len(log) == 0


# --- 15.4 / 15.5 Each pressure has real throughput --------------------------


def test_scarcity_alone_drives_pressure_upward() -> None:
    """With housing comfortable, worse scarcity means more fear and less trust."""
    results = []
    for scarcity in (0.0, 0.25, 0.5, 0.75, 1.0):
        district = build_district(
            "a", population=10, housing_capacity=1000, scarcity=scarcity, fear=0.0, trust=1.0
        )
        results.append(score_one(district))

    fears = [fear for fear, _ in results]
    trusts = [trust for _, trust in results]
    assert fears == sorted(fears)
    assert trusts == sorted(trusts, reverse=True)
    assert fears[0] == 0.0


def test_housing_pressure_alone_drives_pressure_upward() -> None:
    """Overcrowding must reach the formula, not vanish through normalization.

    This is the Phase 5 lesson applied: a factor folded into a normalized
    weight cancels itself. Housing pressure is a term in the weighted average,
    so with scarcity held at zero it is the only thing moving the result, and
    it must visibly move it.
    """
    results = []
    for capacity in (1000, 100, 80, 50, 0):
        district = build_district(
            "a", population=100, housing_capacity=capacity, scarcity=0.0, fear=0.0, trust=1.0
        )
        results.append(score_one(district))

    fears = [fear for fear, _ in results]
    trusts = [trust for _, trust in results]
    assert fears == sorted(fears)
    assert trusts == sorted(trusts, reverse=True)
    assert fears[0] == 0.0
    assert fears[-1] > 0.0


def test_both_pressures_combine() -> None:
    """Full scarcity with half the district unhoused averages to 0.75."""
    district = build_district(
        "a", population=100, housing_capacity=50, scarcity=1.0, fear=0.0, trust=1.0
    )
    fear, trust = score_one(district)

    assert fear == pytest.approx(0.25 * 0.75)
    assert trust == pytest.approx(1.0 + 0.25 * (0.25 - 1.0))


# --- 15.6 Weighting ---------------------------------------------------------


def build_mixed_district(**kwargs):
    """A district with full scarcity and no overcrowding, for weighting tests."""
    return build_district(
        "a", population=100, housing_capacity=1000, scarcity=1.0, fear=0.0, trust=1.0, **kwargs
    )


def test_scarcity_only_weighting_ignores_housing() -> None:
    """A zero housing weight makes overcrowding irrelevant."""
    system = SocialStabilitySystem(scarcity_weight=1.0, housing_pressure_weight=0.0)
    crowded = build_district(
        "a", population=100, housing_capacity=0, scarcity=1.0, fear=0.0, trust=1.0
    )
    roomy = build_mixed_district()

    assert score_one(crowded, system) == score_one(roomy, system)


def test_housing_only_weighting_ignores_scarcity() -> None:
    """A zero scarcity weight makes unmet need irrelevant."""
    system = SocialStabilitySystem(scarcity_weight=0.0, housing_pressure_weight=1.0)
    starving = build_district(
        "a", population=100, housing_capacity=1000, scarcity=1.0, fear=0.0, trust=1.0
    )
    comfortable = build_district(
        "a", population=100, housing_capacity=1000, scarcity=0.0, fear=0.0, trust=1.0
    )

    assert score_one(starving, system) == score_one(comfortable, system)


def test_only_the_ratio_of_weights_matters() -> None:
    """Weights of 1 and 1 must mean exactly what weights of 10 and 10 mean."""

    def score(scarcity_weight: float, housing_weight: float) -> tuple[float, float]:
        """Score the same district under one weighting."""
        district = build_district(
            "a", population=100, housing_capacity=50, scarcity=0.8, fear=0.2, trust=0.7
        )
        return score_one(
            district,
            SocialStabilitySystem(
                scarcity_weight=scarcity_weight, housing_pressure_weight=housing_weight
            ),
        )

    assert score(1.0, 1.0) == score(10.0, 10.0)
    assert score(2.0, 6.0) == score(0.5, 1.5)


def test_unequal_weights_shift_the_result_between_the_two_pressures() -> None:
    """Leaning on scarcity gives a different answer from leaning on housing."""

    def score(scarcity_weight: float, housing_weight: float) -> float:
        """Return the resulting fear under one weighting."""
        district = build_district(
            "a", population=100, housing_capacity=50, scarcity=1.0, fear=0.0, trust=1.0
        )
        return score_one(
            district,
            SocialStabilitySystem(
                scarcity_weight=scarcity_weight, housing_pressure_weight=housing_weight
            ),
        )[0]

    # scarcity is 1.0 and housing pressure is 0.5, so leaning on scarcity hurts more
    assert score(3.0, 1.0) > score(1.0, 1.0) > score(1.0, 3.0)


# --- 15.7 Response rate -----------------------------------------------------


def test_response_rate_zero_changes_nothing_and_emits_nothing() -> None:
    """A frozen social layer is a valid configuration, not an absent one."""
    district = build_district(
        "a", population=100, housing_capacity=0, scarcity=1.0, fear=0.1, trust=0.9
    )
    world = build_world([district], tick=1)
    log = run_social(world, SocialStabilitySystem(response_rate=0.0))

    assert district.fear == 0.1
    assert district.trust == 0.9
    assert len(log) == 0


def test_response_rate_one_reaches_the_target_immediately() -> None:
    """The only setting under which social state may jump.

    Weighted on scarcity alone so the target is exactly 1.0; under the default
    equal weighting a comfortably housed district facing total scarcity has a
    combined pressure of 0.5, which would obscure what this test is checking.
    """
    district = build_district(
        "a", population=100, housing_capacity=1000, scarcity=1.0, fear=0.0, trust=1.0
    )
    system = SocialStabilitySystem(
        scarcity_weight=1.0, housing_pressure_weight=0.0, response_rate=1.0
    )
    fear, trust = score_one(district, system)

    assert fear == pytest.approx(1.0)
    assert trust == pytest.approx(0.0)


def test_default_rate_closes_exactly_one_quarter_of_the_gap_upward() -> None:
    """Rising fear moves a quarter of the way, not all of it.

    Weighted on scarcity alone so the target is exactly 1.0, which makes the
    quarter-gap arithmetic legible.
    """
    district = build_district(
        "a", population=100, housing_capacity=1000, scarcity=1.0, fear=0.2, trust=0.8
    )
    system = SocialStabilitySystem(scarcity_weight=1.0, housing_pressure_weight=0.0)
    fear, trust = score_one(district, system)

    assert fear == pytest.approx(0.2 + 0.25 * (1.0 - 0.2))
    assert trust == pytest.approx(0.8 + 0.25 * (0.0 - 0.8))


def test_default_rate_closes_exactly_one_quarter_of_the_gap_downward() -> None:
    """Falling fear is governed by the same rule as rising fear."""
    district = build_district(
        "a", population=100, housing_capacity=1000, scarcity=0.0, fear=0.8, trust=0.2
    )
    fear, trust = score_one(district)

    assert fear == pytest.approx(0.8 + 0.25 * (0.0 - 0.8))
    assert trust == pytest.approx(0.2 + 0.25 * (1.0 - 0.2))


# --- 15.8 / 15.9 Recovery and deterioration ---------------------------------


def test_a_relieved_district_recovers() -> None:
    """Relief must be able to undo fear, or collapse would be permanent."""
    district = build_district(
        "a", population=10, housing_capacity=1000, scarcity=0.0, fear=0.9, trust=0.1
    )
    fear, trust = score_one(district)

    assert fear < 0.9
    assert trust > 0.1
    assert 0.0 <= fear <= 1.0
    assert 0.0 <= trust <= 1.0


def test_a_pressured_district_deteriorates_gradually() -> None:
    """Hardship raises fear, but one bad tick does not collapse a secure district."""
    district = build_district(
        "a", population=100, housing_capacity=0, scarcity=1.0, fear=0.05, trust=0.95
    )
    fear, trust = score_one(district)

    assert fear > 0.05
    assert trust < 0.95
    assert fear < 0.5, "the default rate must not permit near-total collapse in one tick"
    assert 0.0 <= fear <= 1.0
    assert 0.0 <= trust <= 1.0


# --- 15.10 / 15.11 Convergence and equilibrium ------------------------------


def test_repeated_ticks_converge_without_overshoot_or_oscillation() -> None:
    """Under constant pressure the approach is monotone and never passes the target."""
    district = build_district(
        "a", population=100, housing_capacity=1000, scarcity=1.0, fear=0.0, trust=1.0
    )
    world = build_world([district], tick=1)
    system = SocialStabilitySystem(scarcity_weight=1.0, housing_pressure_weight=0.0)

    fears, trusts = [district.fear], [district.trust]
    for _ in range(30):
        run_social(world, system)
        fears.append(district.fear)
        trusts.append(district.trust)

    assert fears == sorted(fears)
    assert trusts == sorted(trusts, reverse=True)
    assert all(value <= 1.0 + FLOAT_TOLERANCE for value in fears)
    assert all(value >= -FLOAT_TOLERANCE for value in trusts)
    assert fears[-1] == pytest.approx(1.0, abs=1e-3)
    assert trusts[-1] == pytest.approx(0.0, abs=1e-3)
    assert all(math.isfinite(value) for value in fears + trusts)


def test_a_district_already_at_its_target_is_left_alone() -> None:
    """Equilibrium means no mutation and no event, not a zero-sized event."""
    district = build_district(
        "a", population=100, housing_capacity=50, scarcity=1.0, fear=0.75, trust=0.25
    )
    world = build_world([district], tick=1)
    log = run_social(world)

    assert district.fear == 0.75
    assert district.trust == 0.25
    assert len(log) == 0


# --- 15.12 Events -----------------------------------------------------------


def build_two_pressured_districts():
    """Two districts that will both move this tick."""
    return build_world(
        [
            build_district(
                "a", population=100, housing_capacity=0, scarcity=1.0, fear=0.0, trust=1.0
            ),
            build_district(
                "b", population=50, housing_capacity=1000, scarcity=0.5, fear=0.0, trust=1.0
            ),
        ],
        tick=4,
    )


def test_one_event_per_changed_district() -> None:
    """Each district that moves reports once, in sorted identifier order."""
    log = run_social(build_two_pressured_districts())

    assert len(log) == 2
    assert [event.source_id for event in log] == ["a", "b"]
    for event in log:
        assert event.type is EventType.SOCIAL_STABILITY_CHANGED
        assert event.tick == 4


def test_unchanged_and_empty_districts_produce_no_events() -> None:
    """Only real movement is recorded."""
    world = build_world(
        [
            build_district(
                "moves", population=100, housing_capacity=1000, scarcity=1.0, fear=0.0, trust=1.0
            ),
            # scarcity 1.0 with no overcrowding averages to a pressure of 0.5,
            # so a district already at 0.5/0.5 has nowhere left to move
            build_district(
                "settled", population=100, housing_capacity=1000, scarcity=1.0, fear=0.5, trust=0.5
            ),
            build_district("empty", population=0, scarcity=1.0, fear=0.3, trust=0.3),
        ],
        tick=1,
    )
    log = run_social(world)

    assert [event.source_id for event in log] == ["moves"]


def test_event_payload_matches_the_calculation_and_is_json_safe() -> None:
    """Every reported number is the one that was actually used."""
    district = build_district(
        "a", population=100, housing_capacity=50, scarcity=1.0, fear=0.0, trust=1.0
    )
    world = build_world([district], tick=2)
    payload = run_social(world).events()[0].payload_as_dict()

    assert payload["district_id"] == "a"
    assert payload["scarcity_pressure"] == pytest.approx(1.0)
    assert payload["housing_pressure"] == pytest.approx(0.5)
    assert payload["social_pressure"] == pytest.approx(0.75)
    assert payload["previous_fear"] == 0.0
    assert payload["target_fear"] == pytest.approx(0.75)
    assert payload["new_fear"] == pytest.approx(0.1875)
    assert payload["previous_trust"] == 1.0
    assert payload["target_trust"] == pytest.approx(0.25)
    assert payload["new_trust"] == pytest.approx(0.8125)
    assert payload["previous_social_stability"] == pytest.approx(1.0)
    assert payload["new_social_stability"] == pytest.approx(0.8125)
    assert payload["previous_social_strain"] == pytest.approx(0.0)
    assert payload["new_social_strain"] == pytest.approx(0.1875)
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


def test_event_payload_is_immutable_after_construction() -> None:
    """A published social reading is history and cannot be edited."""
    payload = run_social(build_two_pressured_districts()).events()[0].payload

    with pytest.raises(TypeError):
        payload["new_fear"] = 0.0  # type: ignore[index]


def test_event_payload_contains_only_primitives() -> None:
    """No enums, entities, sets, or dataclasses reach the recorded history."""
    for event in run_social(build_two_pressured_districts()):
        for key, value in event.payload_as_dict().items():
            assert isinstance(key, str)
            assert isinstance(value, str | int | float)
            if isinstance(value, float):
                assert math.isfinite(value)


# --- 15.13 Derived stability and strain -------------------------------------


def test_derived_stability_and_strain_at_the_extremes() -> None:
    """No fear with full trust is total stability, and the reverse is total strain."""
    assert social_stability_of(0.0, 1.0) == 1.0
    assert 1.0 - social_stability_of(0.0, 1.0) == 0.0
    assert social_stability_of(1.0, 0.0) == 0.0
    assert 1.0 - social_stability_of(1.0, 0.0) == 1.0


def test_stability_and_strain_always_sum_to_one() -> None:
    """They are two views of the same value, so they must complement exactly."""
    for fear in (0.0, 0.1, 0.37, 0.5, 0.9, 1.0):
        for trust in (0.0, 0.2, 0.45, 0.8, 1.0):
            stability = social_stability_of(fear, trust)
            strain = 1.0 - stability
            assert 0.0 <= stability <= 1.0
            assert 0.0 <= strain <= 1.0
            assert abs((stability + strain) - 1.0) <= FLOAT_TOLERANCE


def test_intermediate_stability_is_the_mean_of_trust_and_calm() -> None:
    """Half-afraid and half-trusting is exactly half stable."""
    assert social_stability_of(0.5, 0.5) == pytest.approx(0.5)
    assert social_stability_of(0.25, 0.75) == pytest.approx(0.75)


# --- 15.14 Mutation isolation ----------------------------------------------


def test_only_fear_and_trust_are_ever_written() -> None:
    """Everything else in the world is read-only to this system."""
    district = build_district(
        "a",
        population=100,
        housing_capacity=50,
        production_rate=3.0,
        consumption_rate=2.0,
        food=7.0,
        scarcity=1.0,
        fear=0.0,
        trust=1.0,
        institutional_pressure=0.3,
    )
    world = build_world(
        [district, build_district("b")],
        boundaries=[("bound", "a", "b")],
        law=build_law(),
        tick=5,
    )
    world.add_wall(build_wall("wall", "bound", active=True))
    world.add_infrastructure(build_infrastructure("infra", "bound"))

    before_stock = {resource: district.resources.amount_of(resource) for resource in ResourceType}
    before_pool = district.resources
    rng_before = world.rng.get_state()

    run_social(world)

    assert district.population == 100
    assert district.housing_capacity == 50
    assert district.production_rate == 3.0
    assert district.consumption_rate == 2.0
    assert district.scarcity == 1.0
    assert district.institutional_pressure == 0.3
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


def test_the_system_does_not_advance_the_tick() -> None:
    """Tick progression belongs to SimulationLoop alone."""
    world = build_two_pressured_districts()
    run_social(world)
    assert world.tick == 4


# --- 15.15 to 15.18 Determinism and invariance ------------------------------


def test_repeated_runs_on_identical_worlds_agree_exactly() -> None:
    """The same inputs give the same social state, every time."""
    results = []
    for _ in range(3):
        world = build_two_pressured_districts()
        log = run_social(world)
        results.append(
            (
                {
                    key: (world.districts[key].fear, world.districts[key].trust)
                    for key in ("a", "b")
                },
                [event.payload_as_dict() for event in log],
            )
        )
    assert results[0] == results[1] == results[2]


def test_rng_state_is_untouched() -> None:
    """This system decides nothing by chance."""
    world = build_two_pressured_districts()
    before = world.rng.get_state()
    run_social(world)
    assert world.rng.get_state() == before


def test_registration_order_does_not_change_the_result() -> None:
    """Insertion order is not part of the simulation's meaning."""

    def build(reverse: bool):
        """Build the same districts in a chosen registration order."""
        districts = [
            build_district(
                "a", population=100, housing_capacity=40, scarcity=0.6, fear=0.1, trust=0.9
            ),
            build_district(
                "b", population=20, housing_capacity=1000, scarcity=0.2, fear=0.8, trust=0.2
            ),
            build_district(
                "c", population=70, housing_capacity=70, scarcity=1.0, fear=0.5, trust=0.5
            ),
        ]
        return build_world(list(reversed(districts)) if reverse else districts, tick=1)

    forward, backward = build(False), build(True)
    run_social(forward)
    run_social(backward)

    for district_id in ("a", "b", "c"):
        assert forward.districts[district_id].fear == backward.districts[district_id].fear
        assert forward.districts[district_id].trust == backward.districts[district_id].trust


def test_renaming_districts_does_not_change_how_they_feel() -> None:
    """Identifiers are labels, never social priority."""

    def build(names: tuple[str, str]):
        """Build two districts under a chosen pair of names."""
        first, second = names
        return build_world(
            [
                build_district(
                    first, population=100, housing_capacity=40, scarcity=0.6, fear=0.1, trust=0.9
                ),
                build_district(
                    second, population=20, housing_capacity=1000, scarcity=0.2, fear=0.8, trust=0.2
                ),
            ],
            tick=1,
        )

    original = build(("aaa", "zzz"))
    renamed = build(("zzz", "aaa"))
    run_social(original)
    run_social(renamed)

    assert original.districts["aaa"].fear == renamed.districts["zzz"].fear
    assert original.districts["aaa"].trust == renamed.districts["zzz"].trust
    assert original.districts["zzz"].fear == renamed.districts["aaa"].fear
    assert original.districts["zzz"].trust == renamed.districts["aaa"].trust


# --- 15.19 Independence -----------------------------------------------------


def test_one_district_does_not_influence_another() -> None:
    """There is no social contagion between neighbours in this phase."""

    def score_b(neighbour_scarcity: float) -> tuple[float, float]:
        """Score district 'b' beside a neighbour under a chosen scarcity."""
        world = build_world(
            [
                build_district(
                    "a",
                    population=100,
                    housing_capacity=0,
                    scarcity=neighbour_scarcity,
                    fear=0.0,
                    trust=1.0,
                ),
                build_district(
                    "b", population=50, housing_capacity=1000, scarcity=0.4, fear=0.3, trust=0.7
                ),
            ],
            boundaries=[("bound", "a", "b")],
            tick=1,
        )
        run_social(world)
        return world.districts["b"].fear, world.districts["b"].trust

    assert score_b(0.0) == score_b(1.0)


# --- Corrupted state fails fast --------------------------------------------


def test_corrupted_scarcity_fails_fast() -> None:
    """A scarcity outside its contract can only mean the field was overwritten."""
    for bad in (1.5, -0.5, float("nan"), float("inf")):
        district = build_district("a", population=10, housing_capacity=100)
        district.scarcity = bad
        world = build_world([district], tick=1)
        with pytest.raises(ValueError):
            run_social(world)


def test_system_holds_no_per_tick_state() -> None:
    """Configuration only; nothing from one tick survives into the next."""
    assert not hasattr(SocialStabilitySystem(), "__dict__")


def test_empty_world_scores_nothing_and_emits_nothing() -> None:
    """A world with no districts is valid and simply has no social state."""
    assert len(run_social(build_world([], tick=1))) == 0


# --- 18. Deterministic adversarial sweep ------------------------------------


def test_generated_combinations_stay_bounded_and_finite() -> None:
    """A bounded seeded sweep over the whole valid input space.

    Deliberately small enough for the ordinary test run. Every combination must
    keep every derived quantity finite and inside its interval, whatever the
    starting social position and configuration.
    """
    rng = random.Random(20260806)

    for _ in range(300):
        population = rng.choice([0, 1, 10, 137, 5000])
        capacity = rng.choice([0, 1, 50, 137, 10_000])
        scarcity = round(rng.random(), 6)
        previous_fear = round(rng.random(), 6)
        previous_trust = round(rng.random(), 6)
        scarcity_weight = rng.choice([0.0, 0.5, 1.0, 7.5])
        housing_weight = rng.choice([0.0, 0.5, 1.0, 7.5])
        if scarcity_weight + housing_weight <= 0.0:
            continue
        response_rate = rng.choice([0.0, 0.1, 0.25, 0.5, 1.0])

        district = build_district(
            "a",
            population=population,
            housing_capacity=capacity,
            scarcity=scarcity,
            fear=previous_fear,
            trust=previous_trust,
        )
        world = build_world([district], tick=1)
        rng_before = world.rng.get_state()
        log = run_social(
            world,
            SocialStabilitySystem(
                scarcity_weight=scarcity_weight,
                housing_pressure_weight=housing_weight,
                response_rate=response_rate,
            ),
        )

        assert 0.0 <= housing_pressure(population, capacity) <= 1.0
        assert 0.0 <= district.fear <= 1.0
        assert 0.0 <= district.trust <= 1.0
        assert math.isfinite(district.fear)
        assert math.isfinite(district.trust)

        stability = social_stability_of(district.fear, district.trust)
        assert 0.0 <= stability <= 1.0
        assert 0.0 <= 1.0 - stability <= 1.0

        assert world.rng.get_state() == rng_before
        assert world.tick == 1
        if population == 0 or response_rate == 0.0:
            assert len(log) == 0

        for event in log:
            for value in event.payload_as_dict().values():
                if isinstance(value, float):
                    assert math.isfinite(value)


def test_generated_pairs_are_order_invariant() -> None:
    """Reordering two generated districts never changes either one's outcome."""
    rng = random.Random(4242)

    for _ in range(80):
        specs = [
            {
                "population": rng.choice([1, 25, 400]),
                "housing_capacity": rng.choice([0, 25, 1000]),
                "scarcity": round(rng.random(), 4),
                "fear": round(rng.random(), 4),
                "trust": round(rng.random(), 4),
            }
            for _ in range(2)
        ]

        outcomes = []
        for order in itertools.permutations(range(2)):
            districts = [
                build_district(f"d{index}", **specs[index])  # type: ignore[arg-type]
                for index in order
            ]
            world = build_world(districts, tick=1)
            run_social(world)
            outcomes.append(
                {
                    key: (world.districts[key].fear, world.districts[key].trust)
                    for key in ("d0", "d1")
                }
            )

        assert outcomes[0] == outcomes[1]


# --- Defect 1: the weighted average must survive any finite weight scale ----


def score_under_weights(
    scarcity_weight: float,
    housing_pressure_weight: float,
    *,
    scarcity: float = 1.0,
    housing_capacity: int = 1000,
    population: int = 10,
    response_rate: float = 1.0,
) -> tuple[float, float, int]:
    """Score one district under a given weighting and report fear, trust, events."""
    district = build_district(
        "a",
        population=population,
        housing_capacity=housing_capacity,
        scarcity=scarcity,
        fear=0.0,
        trust=1.0,
    )
    world = build_world([district], tick=1)
    log = run_social(
        world,
        SocialStabilitySystem(
            scarcity_weight=scarcity_weight,
            housing_pressure_weight=housing_pressure_weight,
            response_rate=response_rate,
        ),
    )
    return district.fear, district.trust, len(log)


def test_weight_scale_invariance_survives_large_finite_scaling() -> None:
    """Weights of 1e308 each must mean what weights of 1 each mean.

    Summing them overflows to infinity, which drove the whole result to zero
    and reported a district in total scarcity as entirely untroubled. Only the
    ratio is meaningful, so the pair is normalized before any arithmetic.
    """
    ordinary = score_under_weights(1.0, 1.0)
    scaled = score_under_weights(1e308, 1e308)

    assert scaled[0] == pytest.approx(ordinary[0])
    assert scaled[1] == pytest.approx(ordinary[1])
    assert scaled[2] == ordinary[2] == 1
    assert ordinary[0] == pytest.approx(0.5)


def test_weight_scale_invariance_survives_tiny_finite_scaling() -> None:
    """Weights at the smallest representable float must not underflow to nothing."""
    ordinary = score_under_weights(1.0, 1.0, scarcity=0.5)
    scaled = score_under_weights(5e-324, 5e-324, scarcity=0.5)

    assert scaled[0] == pytest.approx(ordinary[0])
    assert scaled[1] == pytest.approx(ordinary[1])
    assert scaled[2] == ordinary[2] == 1
    assert ordinary[0] == pytest.approx(0.25)


def test_weight_scale_invariance_holds_across_a_range_of_scales() -> None:
    """The same ratio at any representable scale gives the same answer."""
    reference = score_under_weights(1.0, 1.0)
    for scale in (10.0, 1e-8, 1e8, 1e150, 1e308, 5e-324):
        assert score_under_weights(scale, scale) == pytest.approx(reference)


def test_unequal_ratios_survive_large_finite_scaling() -> None:
    """A 2:1 weighting means the same whether written small or enormous."""
    ordinary = score_under_weights(1.0, 0.5)
    scaled = score_under_weights(1e308, 5e307)

    assert scaled[0] == pytest.approx(ordinary[0])
    assert scaled[1] == pytest.approx(ordinary[1])
    # scarcity 1.0 and housing 0.0 weighted 2:1 gives a pressure of two thirds
    assert ordinary[0] == pytest.approx(2.0 / 3.0)


def test_extreme_weights_are_accepted_by_the_constructor() -> None:
    """A finite non-negative weight is valid however large or small it is."""
    for weight in (1e308, 5e-324, 0.0):
        assert (
            SocialStabilitySystem(scarcity_weight=weight, housing_pressure_weight=1.0) is not None
        )
        assert (
            SocialStabilitySystem(scarcity_weight=1.0, housing_pressure_weight=weight) is not None
        )


def test_two_huge_weights_are_not_rejected_for_summing_to_infinity() -> None:
    """The both-zero check must not overflow on the way to its answer."""
    system = SocialStabilitySystem(scarcity_weight=1e308, housing_pressure_weight=1e308)
    assert system.scarcity_weight == 1e308
    assert system.housing_pressure_weight == 1e308


# --- Defect 2: a positive response rate must never behave as zero -----------


def test_positive_response_rate_is_not_implicitly_zero() -> None:
    """A rate of 1e-10 moves the district, and the movement is recorded.

    Suppressing a change this small would silently reconfigure the system to a
    zero rate, freezing the district forever while appearing to be set up to
    move. Change is therefore judged by exact float inequality, not a threshold.
    """
    district = build_district(
        "a", population=10, housing_capacity=1000, scarcity=1.0, fear=0.0, trust=1.0
    )
    world = build_world([district], tick=1)
    log = run_social(
        world,
        SocialStabilitySystem(
            scarcity_weight=1.0, housing_pressure_weight=0.0, response_rate=1e-10
        ),
    )

    assert district.fear == pytest.approx(1e-10)
    assert district.trust == pytest.approx(1.0 - 1e-10)
    assert len(log) == 1


def test_a_tiny_response_rate_still_makes_monotonic_progress() -> None:
    """Repeated ticks at a tiny rate accumulate rather than freezing."""
    district = build_district(
        "a", population=10, housing_capacity=1000, scarcity=1.0, fear=0.0, trust=1.0
    )
    world = build_world([district], tick=1)
    system = SocialStabilitySystem(
        scarcity_weight=1.0, housing_pressure_weight=0.0, response_rate=1e-6
    )

    fears = [district.fear]
    for _ in range(10):
        run_social(world, system)
        fears.append(district.fear)

    assert fears == sorted(fears)
    assert fears[-1] > fears[0]
    assert all(0.0 <= value <= 1.0 for value in fears)


def test_a_district_exactly_at_target_still_emits_nothing() -> None:
    """Exact comparison must not turn every district into a perpetual emitter."""
    district = build_district(
        "a", population=100, housing_capacity=50, scarcity=1.0, fear=0.75, trust=0.25
    )
    world = build_world([district], tick=1)
    log = run_social(world)

    assert district.fear == 0.75
    assert district.trust == 0.25
    assert len(log) == 0


# --- Defect 3: out-of-range results must fail, not be silently squashed -----


def test_meaningful_out_of_range_unit_result_is_rejected() -> None:
    """A value far outside the interval is a defect, not a value to tidy away."""
    for bad in (2.0, -1.0, 1.5, -0.5, 100.0):
        with pytest.raises(ValueError):
            _clamp_unit(bad, "test")


def test_non_finite_unit_result_is_rejected() -> None:
    """NaN and the infinities can never be residue."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            _clamp_unit(bad, "test")


def test_one_ulp_residue_is_flattened() -> None:
    """The single bit a division can lose is exactly what may be tidied."""
    assert _clamp_unit(math.nextafter(0.0, -math.inf), "test") == 0.0
    assert _clamp_unit(math.nextafter(1.0, math.inf), "test") == 1.0


def test_values_inside_the_interval_pass_through_untouched() -> None:
    """Legitimate values are returned exactly as they came in."""
    for value in (0.0, 1e-12, 0.5, 1.0 - 1e-12, 1.0):
        assert _clamp_unit(value, "test") == value


def test_just_beyond_one_ulp_is_rejected() -> None:
    """The residue window is exactly one ULP wide, not a soft tolerance."""
    just_below = math.nextafter(math.nextafter(0.0, -math.inf), -math.inf)
    just_above = math.nextafter(math.nextafter(1.0, math.inf), math.inf)

    with pytest.raises(ValueError):
        _clamp_unit(just_below, "test")
    with pytest.raises(ValueError):
        _clamp_unit(just_above, "test")


def test_corrupted_stored_fear_or_trust_fails_fast() -> None:
    """District fields stay mutable, so what they hold is checked before use."""
    for field, bad in (
        ("fear", 100.0),
        ("fear", -5.0),
        ("fear", float("nan")),
        ("fear", float("inf")),
        ("trust", 100.0),
        ("trust", -5.0),
        ("trust", float("nan")),
        ("trust", float("-inf")),
    ):
        district = build_district("a", population=10, housing_capacity=1000, scarcity=0.5)
        setattr(district, field, bad)
        world = build_world([district], tick=1)

        with pytest.raises(ValueError):
            run_social(world)


def test_corrupted_state_is_not_silently_squashed_into_range() -> None:
    """A fear of 100.0 must raise rather than quietly becoming a plausible 1.0."""
    district = build_district("a", population=10, housing_capacity=1000, scarcity=0.5)
    district.fear = 100.0
    world = build_world([district], tick=1)

    with pytest.raises(ValueError):
        run_social(world)
    assert district.fear == 100.0, "the corrupted value must survive untouched for diagnosis"


# --- Atomic failure across districts ----------------------------------------


def test_a_corrupted_district_aborts_the_whole_update() -> None:
    """Staging means one bad district leaves every other district untouched.

    Compute happens for all districts before any is written, so a failure
    anywhere aborts before the first mutation. A partially applied tick would
    be worse than no tick at all: half the world would have moved and nothing
    would record which half.
    """
    healthy = build_district(
        "healthy", population=100, housing_capacity=50, scarcity=1.0, fear=0.1, trust=0.9
    )
    corrupted = build_district(
        "zcorrupted", population=100, housing_capacity=50, scarcity=1.0, fear=0.1, trust=0.9
    )
    corrupted.fear = 100.0
    world = build_world([healthy, corrupted], tick=1)

    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    with pytest.raises(ValueError):
        SocialStabilitySystem().update(world, bus)

    assert healthy.fear == 0.1
    assert healthy.trust == 0.9
    assert corrupted.fear == 100.0
    assert corrupted.trust == 0.9
    assert len(log) == 0


def test_a_corrupted_district_sorting_first_also_aborts_cleanly() -> None:
    """The abort holds whichever district is reached first."""
    corrupted = build_district(
        "acorrupted", population=100, housing_capacity=50, scarcity=1.0, fear=0.1, trust=0.9
    )
    corrupted.trust = -5.0
    healthy = build_district(
        "healthy", population=100, housing_capacity=50, scarcity=1.0, fear=0.1, trust=0.9
    )
    world = build_world([corrupted, healthy], tick=1)

    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    with pytest.raises(ValueError):
        SocialStabilitySystem().update(world, bus)

    assert healthy.fear == 0.1
    assert healthy.trust == 0.9
    assert len(log) == 0


def test_a_corrupted_scarcity_also_aborts_before_any_mutation() -> None:
    """Whatever the corrupted field, nothing is written and nothing announced."""
    healthy = build_district(
        "healthy", population=100, housing_capacity=50, scarcity=1.0, fear=0.1, trust=0.9
    )
    corrupted = build_district("zbad", population=100, housing_capacity=50)
    corrupted.scarcity = 7.0
    world = build_world([healthy, corrupted], tick=1)

    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    with pytest.raises(ValueError):
        SocialStabilitySystem().update(world, bus)

    assert healthy.fear == 0.1
    assert healthy.trust == 0.9
    assert len(log) == 0


def test_corruption_is_caught_even_when_the_update_would_map_it_back_in_range() -> None:
    """Stored values are checked before use, not merely after the arithmetic.

    At a response rate of one, a corrupted fear of 1.5 lands exactly on its
    target and the result is a perfectly ordinary number. Relying on the
    output bound alone would launder the corruption into a plausible value and
    lose the evidence that anything was ever wrong, so the previous state is
    validated on the way in.
    """
    district = build_district("a", population=10, housing_capacity=1000, scarcity=0.5)
    district.fear = 1.5
    world = build_world([district], tick=1)

    with pytest.raises(ValueError):
        run_social(world, SocialStabilitySystem(response_rate=1.0))
    assert district.fear == 1.5


def test_corrupted_trust_is_caught_when_the_update_would_map_it_back_in_range() -> None:
    """The same protection applies to trust."""
    district = build_district("a", population=10, housing_capacity=1000, scarcity=0.5)
    district.trust = -0.5
    world = build_world([district], tick=1)

    with pytest.raises(ValueError):
        run_social(world, SocialStabilitySystem(response_rate=1.0))
    assert district.trust == -0.5


# --- Corrupted stored *types*, not just corrupted stored numbers ------------

CORRUPTED_SCALARS = [
    ("fear", True),
    ("trust", False),
    ("scarcity", True),
    ("fear", "0.5"),
    ("trust", "0.5"),
    ("scarcity", "0.5"),
]
"""Stored values whose *type* is wrong rather than whose magnitude is wrong.

Every one of these converts silently into a perfectly ordinary float --
``True`` into 1.0, ``"0.5"`` into 0.5 -- so a validator shown the converted
value has nothing to object to. They are the cases that prove the stored value
is validated as found rather than after a repair.
"""


def build_corrupted_pair(field: str, bad: object, *, corrupted_first: bool):
    """Build one healthy district beside one whose stored ``field`` is corrupted.

    Identifiers are chosen so the corrupted district sorts either before or
    after the healthy one, which is what makes the atomicity claim independent
    of traversal position.
    """
    healthy_id = "m_healthy"
    corrupted_id = "a_corrupted" if corrupted_first else "z_corrupted"

    healthy = build_district(
        healthy_id, population=100, housing_capacity=50, scarcity=0.5, fear=0.2, trust=0.8
    )
    corrupted = build_district(
        corrupted_id, population=100, housing_capacity=50, scarcity=0.5, fear=0.2, trust=0.8
    )
    setattr(corrupted, field, bad)

    districts = [corrupted, healthy] if corrupted_first else [healthy, corrupted]
    return build_world(districts, tick=1), healthy, corrupted


def assert_aborted_without_trace(world, healthy, corrupted, field, bad) -> None:
    """Assert the update raised, changed nothing, and announced nothing."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)

    with pytest.raises(TypeError):
        SocialStabilitySystem().update(world, bus)

    assert healthy.fear == 0.2
    assert healthy.trust == 0.8
    assert getattr(corrupted, field) is bad or getattr(corrupted, field) == bad
    assert len(log) == 0


@pytest.mark.parametrize(("field", "bad"), CORRUPTED_SCALARS)
def test_corrupted_stored_scalar_type_fails_atomically(field: str, bad: object) -> None:
    """A stored value of the wrong type aborts the whole update, changing nothing.

    ``District`` stays mutable after construction, so its own validation speaks
    only for the moment it was built. Anything that overwrote a social field
    afterwards is exactly what this system has to catch, and a ``True`` reads
    as total fear while a ``"0.5"`` reads as moderate fear -- both entirely
    plausible, both wrong.
    """
    world, healthy, corrupted = build_corrupted_pair(field, bad, corrupted_first=False)
    assert_aborted_without_trace(world, healthy, corrupted, field, bad)


@pytest.mark.parametrize(("field", "bad"), CORRUPTED_SCALARS)
def test_corrupted_stored_scalar_type_fails_atomically_when_sorted_first(
    field: str, bad: object
) -> None:
    """The abort holds whether the corrupted district is reached first or last.

    Staging computes every district before writing any, so where the bad one
    sits in the traversal cannot decide whether the healthy one was already
    mutated by the time the failure arrived.
    """
    world, healthy, corrupted = build_corrupted_pair(field, bad, corrupted_first=True)
    assert_aborted_without_trace(world, healthy, corrupted, field, bad)


@pytest.mark.parametrize(("field", "bad"), CORRUPTED_SCALARS)
def test_corrupted_stored_scalar_type_is_reported_by_name(field: str, bad: object) -> None:
    """The error names the field and the type found, so the cause is diagnosable."""
    district = build_district(
        "solo", population=100, housing_capacity=50, scarcity=0.5, fear=0.2, trust=0.8
    )
    setattr(district, field, bad)
    world = build_world([district], tick=1)

    with pytest.raises(TypeError) as caught:
        run_social(world)

    message = str(caught.value)
    assert field in message
    assert type(bad).__name__ in message


def test_a_boolean_is_not_accepted_merely_because_it_converts_to_a_valid_float() -> None:
    """``True`` would read as total fear and ``False`` as none; neither is a number.

    Both convert to values squarely inside the permitted interval, so nothing
    downstream could ever notice them. This is the case that a conversion
    before validation hides most completely.
    """
    for value in (True, False):
        district = build_district(
            "solo", population=100, housing_capacity=50, scarcity=0.5, fear=0.2, trust=0.8
        )
        district.fear = value  # type: ignore[assignment]
        world = build_world([district], tick=1)

        with pytest.raises(TypeError):
            run_social(world)
        assert district.fear is value


def test_a_numeric_string_is_not_accepted_merely_because_it_parses() -> None:
    """``"0.5"`` is a plausible-looking value and still not a number."""
    district = build_district(
        "solo", population=100, housing_capacity=50, scarcity=0.5, fear=0.2, trust=0.8
    )
    district.trust = "0.5"  # type: ignore[assignment]
    world = build_world([district], tick=1)

    with pytest.raises(TypeError):
        run_social(world)
    assert district.trust == "0.5"


def test_valid_integer_stored_values_are_still_accepted() -> None:
    """Rejecting bool must not also reject an honest int of 0 or 1.

    ``int`` is a real number and a district legitimately storing 0 or 1 is at
    an interval boundary, not corrupted. Only ``bool`` is singled out, because
    it is the one int subclass that means something else entirely.
    """
    district = build_district(
        "solo", population=100, housing_capacity=1000, scarcity=0, fear=1, trust=0
    )
    world = build_world([district], tick=1)
    run_social(world)

    assert 0.0 <= district.fear <= 1.0
    assert 0.0 <= district.trust <= 1.0
    assert district.fear < 1.0, "zero pressure must pull fear down from one"
