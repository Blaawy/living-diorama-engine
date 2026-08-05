"""Tests for ScarcitySystem.

Scarcity is the number every later phase reads to decide whether a district is
in trouble, so it has to be bounded, monotonic, and derived from nothing but
the district's own final state.
"""

import json

import pytest
from systems_builders import (
    EVEN_ALLOCATION,
    FOOD_ONLY_ALLOCATION,
    build_district,
    build_infrastructure,
    build_law,
    build_wall,
    build_world,
)

from living_diorama.entities import IsolationState, ResourceType
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.systems import ScarcitySystem


def run_scarcity(world, allocation=EVEN_ALLOCATION) -> EventLog:
    """Run one scarcity update and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    ScarcitySystem(consumption_allocation=allocation).update(world, bus)
    return log


def scarcities(world) -> dict[str, float]:
    """Read every district's scarcity, keyed by id."""
    return {
        district_id: world.districts[district_id].scarcity
        for district_id in sorted(world.districts)
    }


def single(district) -> float:
    """Score one district on its own and return its scarcity."""
    world = build_world([district], tick=1)
    run_scarcity(world)
    return world.districts[district.id].scarcity


def test_adequate_resources_produce_zero_scarcity() -> None:
    """A district holding everything it needs is not short of anything."""
    district = build_district(
        "a", population=10, consumption_rate=1.0, food=100.0, materials=100.0, energy=100.0
    )
    assert single(district) == 0.0


def test_exactly_sufficient_resources_produce_zero_scarcity() -> None:
    """Meeting demand precisely is sufficiency, not scarcity."""
    district = build_district(
        "a", population=10, consumption_rate=1.0, food=5.0, materials=3.0, energy=2.0
    )
    assert single(district) == 0.0


def test_complete_shortage_produces_maximum_scarcity() -> None:
    """Nothing at all against real demand is total scarcity."""
    district = build_district("a", population=10, consumption_rate=1.0)
    assert single(district) == 1.0


def test_partial_shortage_produces_intermediate_scarcity() -> None:
    """Half the demand met is half the scarcity."""
    district = build_district(
        "a", population=10, consumption_rate=1.0, food=2.5, materials=1.5, energy=1.0
    )
    assert single(district) == pytest.approx(0.5)


def test_scarcity_increases_as_shortage_deepens() -> None:
    """More missing resource means more scarcity, all else equal."""
    scores = [
        single(
            build_district(
                "a", population=10, consumption_rate=1.0, food=food, materials=3.0, energy=2.0
            )
        )
        for food in (5.0, 4.0, 3.0, 2.0, 1.0, 0.0)
    ]
    assert scores == sorted(scores)
    assert scores[0] == 0.0
    assert scores[-1] > scores[0]


def test_scarcity_falls_as_supply_improves() -> None:
    """Improving stock against fixed demand can only relieve scarcity."""
    scores = [
        single(build_district("a", population=10, consumption_rate=1.0, food=food))
        for food in (0.0, 1.0, 2.0, 3.0, 4.0, 5.0)
    ]
    assert scores == sorted(scores, reverse=True)


def test_surplus_of_one_resource_does_not_mask_famine_in_another() -> None:
    """Scarcity is measured per resource kind, then summed."""
    district = build_district(
        "a", population=10, consumption_rate=1.0, food=0.0, materials=1000.0, energy=1000.0
    )
    assert single(district) == pytest.approx(0.5)


def test_zero_population_produces_no_scarcity() -> None:
    """An empty district is empty, not suffering."""
    district = build_district("a", population=0, consumption_rate=5.0)
    assert single(district) == 0.0


def test_zero_consumption_rate_produces_no_scarcity() -> None:
    """A district that needs nothing cannot fall short."""
    district = build_district("a", population=100, consumption_rate=0.0)
    assert single(district) == 0.0


def test_scarcity_is_always_finite_and_within_the_unit_interval() -> None:
    """The bound holds across a wide spread of populations and stock."""
    for population in (0, 1, 7, 100, 5000):
        for food in (0.0, 0.5, 5.0, 1e6):
            score = single(
                build_district("a", population=population, consumption_rate=1.5, food=food)
            )
            assert 0.0 <= score <= 1.0


def test_all_resource_types_contribute() -> None:
    """Every MVP resource kind is considered, weighted by its allocation."""
    missing_energy = build_district(
        "a", population=10, consumption_rate=1.0, food=5.0, materials=3.0, energy=0.0
    )
    assert single(missing_energy) == pytest.approx(0.2)


def test_allocation_choice_changes_what_counts_as_scarce() -> None:
    """Demand follows the configured allocation, not a fixed assumption."""
    world = build_world(
        [build_district("a", population=10, consumption_rate=1.0, food=10.0)], tick=1
    )
    run_scarcity(world, allocation=FOOD_ONLY_ALLOCATION)
    assert world.districts["a"].scarcity == 0.0


def test_previous_scarcity_is_overwritten_not_accumulated() -> None:
    """Scarcity is a reading of now, not a running tally."""
    district = build_district(
        "a", population=10, consumption_rate=1.0, food=100.0, materials=100.0, energy=100.0
    )
    district.scarcity = 0.9
    world = build_world([district], tick=1)
    run_scarcity(world)
    assert world.districts["a"].scarcity == 0.0


def test_insertion_order_does_not_change_scarcity() -> None:
    """Registration order is irrelevant to every district's score."""

    def build(reverse: bool):
        """Build the same districts in a chosen registration order."""
        districts = [
            build_district("a", population=10, consumption_rate=1.0, food=1.0),
            build_district("b", population=20, consumption_rate=1.0, food=8.0),
            build_district("c", population=5, consumption_rate=2.0),
        ]
        return build_world(list(reversed(districts)) if reverse else districts, tick=1)

    forward, backward = build(False), build(True)
    run_scarcity(forward)
    run_scarcity(backward)
    assert scarcities(forward) == scarcities(backward)


def test_renaming_districts_does_not_change_their_scarcity() -> None:
    """A district's score depends on its state, never on its name."""
    original = build_world(
        [
            build_district("a", population=10, consumption_rate=1.0, food=1.0),
            build_district("b", population=20, consumption_rate=1.0, food=8.0),
        ],
        tick=1,
    )
    renamed = build_world(
        [
            build_district("zzz", population=10, consumption_rate=1.0, food=1.0),
            build_district("aaa", population=20, consumption_rate=1.0, food=8.0),
        ],
        tick=1,
    )
    run_scarcity(original)
    run_scarcity(renamed)

    assert original.districts["a"].scarcity == renamed.districts["zzz"].scarcity
    assert original.districts["b"].scarcity == renamed.districts["aaa"].scarcity


def test_emits_one_correct_event_per_district() -> None:
    """Every district reports every tick, including one that has not changed."""
    world = build_world(
        [
            build_district("a", population=10, consumption_rate=1.0),
            build_district("b", population=0, consumption_rate=1.0),
        ],
        tick=6,
    )
    log = run_scarcity(world)

    assert len(log) == 2
    assert [event.source_id for event in log] == ["a", "b"]
    for event in log:
        assert event.type is EventType.SCARCITY_CHANGED
        assert event.tick == 6

    unchanged = log.events()[1].payload_as_dict()
    assert unchanged["previous_scarcity"] == 0.0
    assert unchanged["new_scarcity"] == 0.0


def test_event_payload_is_complete_and_json_safe() -> None:
    """The payload explains the score using strict JSON primitives."""
    world = build_world(
        [build_district("a", population=10, consumption_rate=1.0, food=2.5)], tick=1
    )
    payload = run_scarcity(world).events()[0].payload_as_dict()

    assert payload["district_id"] == "a"
    assert payload["previous_scarcity"] == 0.0
    assert payload["new_scarcity"] == pytest.approx(0.75)
    assert payload["projected_required_total"] == pytest.approx(10.0)
    assert payload["projected_shortfall_total"] == pytest.approx(7.5)
    assert payload["population"] == 10
    breakdown = payload["projected_shortfall"]
    assert isinstance(breakdown, dict)
    assert set(breakdown) == {"FOOD", "MATERIALS", "ENERGY"}
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


def test_event_payload_is_immutable() -> None:
    """A published reading is history and cannot be edited afterwards."""
    world = build_world([build_district("a", population=10, consumption_rate=1.0)], tick=1)
    payload = run_scarcity(world).events()[0].payload

    with pytest.raises(TypeError):
        payload["new_scarcity"] = 0.0  # type: ignore[index]


def test_scarcity_changes_nothing_but_scarcity() -> None:
    """Only one field is written; everything else is read-only to this system."""
    district = build_district(
        "a", population=10, consumption_rate=1.0, production_rate=3.0, food=1.0
    )
    world = build_world(
        [district, build_district("b")],
        boundaries=[("bound", "a", "b")],
        law=build_law(),
        tick=1,
    )
    world.add_wall(build_wall("wall", "bound", active=False))
    world.add_infrastructure(build_infrastructure("infra", "bound"))

    before_stock = {resource: district.resources.amount_of(resource) for resource in ResourceType}
    run_scarcity(world)

    assert district.population == 10
    assert district.consumption_rate == 1.0
    assert district.production_rate == 3.0
    assert district.fear == 0.0
    assert district.trust == 0.5
    assert district.institutional_pressure == 0.0
    assert district.isolation_state is IsolationState.OPEN
    assert district.housing_capacity == 9999
    for resource, amount in before_stock.items():
        assert district.resources.amount_of(resource) == amount
    assert world.walls["wall"].active is False
    assert world.boundaries["bound"].wall_id == "wall"
    assert world.infrastructure["infra"].dependency_score == 0.0
    assert world.laws["law_movement_sharing"].current_value is True


def test_scarcity_consumes_no_randomness() -> None:
    """The score is arithmetic; the generator is never touched."""
    world = build_world([build_district("a", population=10, consumption_rate=1.0)], tick=1)
    before = world.rng.get_state()
    run_scarcity(world)
    assert world.rng.get_state() == before


def test_repeated_runs_are_stable() -> None:
    """Running twice on an unchanged world gives the same score twice."""
    world = build_world(
        [build_district("a", population=10, consumption_rate=1.0, food=2.0)], tick=1
    )
    run_scarcity(world)
    first = world.districts["a"].scarcity
    run_scarcity(world)
    assert world.districts["a"].scarcity == first


def test_invalid_allocation_is_rejected_at_construction() -> None:
    """The allocation follows the same rules as every other resource system."""
    with pytest.raises(ValueError):
        ScarcitySystem(consumption_allocation={ResourceType.FOOD: 1.0})
    with pytest.raises(TypeError):
        ScarcitySystem(
            consumption_allocation=dict(EVEN_ALLOCATION) | {"FOOD": 0.0}  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError):
        ScarcitySystem(
            consumption_allocation={
                ResourceType.FOOD: 0.5,
                ResourceType.MATERIALS: 0.3,
                ResourceType.ENERGY: 0.3,
            }
        )


def test_configuration_is_defensively_copied_and_read_only() -> None:
    """The caller's mapping is not retained and cannot be edited through us."""
    supplied = dict(EVEN_ALLOCATION)
    system = ScarcitySystem(consumption_allocation=supplied)
    supplied[ResourceType.FOOD] = 99.0

    assert system.consumption_allocation[ResourceType.FOOD] == 0.5
    with pytest.raises(TypeError):
        system.consumption_allocation[ResourceType.FOOD] = 99.0  # type: ignore[index]


def test_system_holds_no_per_tick_state() -> None:
    """Configuration only; nothing from one tick survives into the next."""
    assert not hasattr(ScarcitySystem(consumption_allocation=EVEN_ALLOCATION), "__dict__")


def test_empty_world_scores_nothing_and_emits_nothing() -> None:
    """A world with no districts is valid and simply has no scarcity."""
    assert len(run_scarcity(build_world([], tick=1))) == 0
