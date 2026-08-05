"""Tests for ProductionSystem."""

import json

import pytest
from living_diorama.entities import ResourceType
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.systems import ProductionSystem
from systems_builders import (
    EVEN_ALLOCATION,
    build_district,
    build_infrastructure,
    build_law,
    build_wall,
    build_world,
)


def run_production(world, allocation=EVEN_ALLOCATION) -> EventLog:
    """Run one production update against a world and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    ProductionSystem(allocation=allocation).update(world, bus)
    return log


def test_produces_the_configured_aggregate_total() -> None:
    """The district's production_rate is the total split across resources."""
    world = build_world([build_district("a", production_rate=10.0)], tick=1)
    run_production(world)
    pool = world.districts["a"].resources
    assert pool.amount_of(ResourceType.FOOD) == 5.0
    assert pool.amount_of(ResourceType.MATERIALS) == 3.0
    assert pool.amount_of(ResourceType.ENERGY) == 2.0


def test_production_adds_to_existing_stock() -> None:
    """Production accumulates rather than replacing what a district holds."""
    world = build_world([build_district("a", production_rate=10.0, food=1.0)], tick=1)
    run_production(world)
    assert world.districts["a"].resources.amount_of(ResourceType.FOOD) == 6.0


def test_replaces_the_resource_pool_without_mutating_the_previous_one() -> None:
    """Pools are immutable value objects, so a change is a replacement."""
    world = build_world([build_district("a", production_rate=10.0, food=1.0)], tick=1)
    original = world.districts["a"].resources

    run_production(world)

    assert world.districts["a"].resources is not original
    assert original.amount_of(ResourceType.FOOD) == 1.0


def test_districts_are_processed_in_sorted_id_order() -> None:
    """Event order follows sorted district ids, not insertion order."""
    world = build_world(
        [
            build_district("zulu", production_rate=1.0),
            build_district("alpha", production_rate=1.0),
            build_district("mike", production_rate=1.0),
        ],
        tick=1,
    )
    log = run_production(world)
    assert [event.source_id for event in log] == ["alpha", "mike", "zulu"]


def test_emits_exactly_one_correct_event_per_district() -> None:
    """One event per district per tick, of the right type, tick, and source."""
    world = build_world(
        [build_district("a", production_rate=10.0), build_district("b", production_rate=2.0)],
        tick=7,
    )
    log = run_production(world)

    assert len(log) == 2
    for event in log:
        assert event.type is EventType.RESOURCE_PRODUCED
        assert event.tick == 7
    assert log.events()[0].source_id == "a"


def test_event_payload_uses_resource_string_values() -> None:
    """Payloads carry JSON-compatible strings, never enum objects."""
    world = build_world([build_district("a", production_rate=10.0)], tick=1)
    payload = run_production(world).events()[0].payload_as_dict()

    assert payload["district_id"] == "a"
    assert payload["total_produced"] == 10.0
    assert payload["resources"] == {"FOOD": 5.0, "MATERIALS": 3.0, "ENERGY": 2.0}


def test_event_payload_is_strict_json_compatible() -> None:
    """A production event must survive RFC-compliant serialization."""
    world = build_world([build_district("a", production_rate=10.0)], tick=1)
    payload = run_production(world).events()[0].payload_as_dict()
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


def test_zero_production_still_emits_an_event_and_changes_nothing() -> None:
    """A silent tick would be indistinguishable from a system that failed to run."""
    world = build_world([build_district("a", production_rate=0.0, food=4.0)], tick=1)
    log = run_production(world)

    assert len(log) == 1
    assert log.events()[0].payload["total_produced"] == 0.0
    assert world.districts["a"].resources.amount_of(ResourceType.FOOD) == 4.0


def test_production_does_not_consume_rng() -> None:
    """Production is fully deterministic and must not touch the generator."""
    world = build_world([build_district("a", production_rate=10.0)], tick=1)
    before = world.rng.get_state()
    run_production(world)
    assert world.rng.get_state() == before


def test_production_leaves_unrelated_state_untouched() -> None:
    """Only resource stock changes; every other field is preserved exactly."""
    district = build_district("a", population=42, production_rate=10.0, consumption_rate=3.0)
    world = build_world(
        [district, build_district("b")],
        boundaries=[("bound", "a", "b")],
        law=build_law(),
        tick=1,
    )
    world.add_wall(build_wall("wall", "bound", active=True))
    world.add_infrastructure(build_infrastructure("infra", "bound"))

    law_before = (world.laws["law_movement_sharing"].active,
                  world.laws["law_movement_sharing"].current_value)
    wall_before = (world.walls["wall"].active, world.walls["wall"].integrity)
    boundary_before = world.boundaries["bound"].wall_id
    infra_before = (world.infrastructure["infra"].capacity,
                    world.infrastructure["infra"].dependency_score)

    run_production(world)

    assert district.population == 42
    assert district.production_rate == 10.0
    assert district.consumption_rate == 3.0
    assert (world.laws["law_movement_sharing"].active,
            world.laws["law_movement_sharing"].current_value) == law_before
    assert (world.walls["wall"].active, world.walls["wall"].integrity) == wall_before
    assert world.boundaries["bound"].wall_id == boundary_before
    assert (world.infrastructure["infra"].capacity,
            world.infrastructure["infra"].dependency_score) == infra_before


def test_repeated_ticks_apply_production_once_each() -> None:
    """Two updates produce exactly twice, never more."""
    world = build_world([build_district("a", production_rate=10.0)], tick=1)
    system = ProductionSystem(allocation=EVEN_ALLOCATION)
    bus = EventBus()
    system.update(world, bus)
    world.advance_tick()
    system.update(world, bus)
    assert world.districts["a"].resources.amount_of(ResourceType.FOOD) == 10.0


def test_all_three_resource_types_are_produced() -> None:
    """Every configured resource kind receives its share."""
    world = build_world([build_district("a", production_rate=100.0)], tick=1)
    run_production(world)
    pool = world.districts["a"].resources
    assert (pool.amount_of(ResourceType.FOOD),
            pool.amount_of(ResourceType.MATERIALS),
            pool.amount_of(ResourceType.ENERGY)) == (50.0, 30.0, 20.0)


def test_system_holds_no_per_tick_state() -> None:
    """Configuration only; nothing from a tick may survive into the next one."""
    system = ProductionSystem(allocation=EVEN_ALLOCATION)
    assert not hasattr(system, "__dict__")


def test_empty_world_produces_nothing_and_emits_nothing() -> None:
    """A world with no districts is valid and simply has no production."""
    assert len(run_production(build_world([], tick=1))) == 0


def test_zero_weight_resource_receives_nothing() -> None:
    """A zero weight is a legitimate configuration, not an error."""
    world = build_world([build_district("a", production_rate=10.0)], tick=1)
    run_production(world, allocation={ResourceType.FOOD: 1.0,
                                      ResourceType.MATERIALS: 0.0,
                                      ResourceType.ENERGY: 0.0})
    pool = world.districts["a"].resources
    assert pool.amount_of(ResourceType.FOOD) == 10.0
    assert pool.amount_of(ResourceType.MATERIALS) == 0.0


def test_non_finite_production_rate_fails_clearly() -> None:
    """An impossible rate must raise rather than poison the world with NaN."""
    district = build_district("a", production_rate=0.0)
    district.production_rate = float("inf")
    world = build_world([district], tick=1)
    with pytest.raises(ValueError):
        run_production(world)
