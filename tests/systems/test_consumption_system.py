"""Tests for ConsumptionSystem."""

import json

from living_diorama.entities import ResourceType
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.systems import ConsumptionSystem
from living_diorama.systems._resource_config import FLOAT_TOLERANCE
from systems_builders import (
    EVEN_ALLOCATION,
    build_district,
    build_infrastructure,
    build_law,
    build_wall,
    build_world,
)


def run_consumption(world, allocation=EVEN_ALLOCATION) -> EventLog:
    """Run one consumption update against a world and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    ConsumptionSystem(allocation=allocation).update(world, bus)
    return log


def test_requested_total_is_population_times_rate() -> None:
    """Demand is the population's aggregate draw for this tick."""
    world = build_world(
        [build_district("a", population=10, consumption_rate=2.0, food=100.0)], tick=1
    )
    payload = run_consumption(world).events()[0].payload_as_dict()
    assert payload["requested_total"] == 20.0


def test_demand_is_split_by_allocation_and_consumed_from_stock() -> None:
    """Each resource is drawn down by its configured share of total demand."""
    world = build_world(
        [
            build_district(
                "a", population=10, consumption_rate=2.0, food=100.0, materials=100.0,
                energy=100.0,
            )
        ],
        tick=1,
    )
    run_consumption(world)
    pool = world.districts["a"].resources
    assert pool.amount_of(ResourceType.FOOD) == 90.0
    assert pool.amount_of(ResourceType.MATERIALS) == 94.0
    assert pool.amount_of(ResourceType.ENERGY) == 96.0


def test_consumption_is_capped_by_available_stock() -> None:
    """A district cannot eat what it does not have."""
    world = build_world(
        [build_district("a", population=10, consumption_rate=2.0, food=3.0)], tick=1
    )
    payload = run_consumption(world).events()[0].payload_as_dict()

    assert world.districts["a"].resources.amount_of(ResourceType.FOOD) == 0.0
    assert payload["consumed"]["FOOD"] == 3.0
    assert payload["unmet"]["FOOD"] == 7.0


def test_stock_never_becomes_negative() -> None:
    """Unmet demand is reported, never borrowed against future stock."""
    world = build_world(
        [build_district("a", population=100, consumption_rate=5.0, food=1.0)], tick=1
    )
    run_consumption(world)
    pool = world.districts["a"].resources
    assert all(pool.amount_of(resource) >= 0.0 for resource in ResourceType)


def test_event_totals_match_their_parts_within_tolerance() -> None:
    """The reported totals must agree with the per-resource breakdown."""
    world = build_world(
        [build_district("a", population=7, consumption_rate=1.3, food=4.0, materials=1.0)],
        tick=1,
    )
    payload = run_consumption(world).events()[0].payload_as_dict()

    consumed = payload["consumed"]
    unmet = payload["unmet"]
    assert isinstance(consumed, dict)
    assert isinstance(unmet, dict)

    consumed_sum = sum(float(value) for value in consumed.values())
    unmet_sum = sum(float(value) for value in unmet.values())

    assert abs(float(payload["consumed_total"]) - consumed_sum) <= FLOAT_TOLERANCE
    assert abs(float(payload["unmet_total"]) - unmet_sum) <= FLOAT_TOLERANCE
    assert (
        abs(
            float(payload["requested_total"])
            - (float(payload["consumed_total"]) + float(payload["unmet_total"]))
        )
        <= FLOAT_TOLERANCE
    )


def test_replaces_the_resource_pool_without_mutating_the_previous_one() -> None:
    """Consumption replaces the value object rather than editing it."""
    world = build_world(
        [build_district("a", population=1, consumption_rate=1.0, food=10.0)], tick=1
    )
    original = world.districts["a"].resources
    run_consumption(world)
    assert world.districts["a"].resources is not original
    assert original.amount_of(ResourceType.FOOD) == 10.0


def test_districts_are_processed_in_sorted_id_order() -> None:
    """Event order follows sorted district ids, not insertion order."""
    world = build_world(
        [
            build_district("zulu", population=1, consumption_rate=1.0),
            build_district("alpha", population=1, consumption_rate=1.0),
        ],
        tick=1,
    )
    log = run_consumption(world)
    assert [event.source_id for event in log] == ["alpha", "zulu"]


def test_emits_exactly_one_correct_event_per_district() -> None:
    """One event per district per tick, with the right type and tick."""
    world = build_world(
        [build_district("a", population=1, consumption_rate=1.0),
         build_district("b", population=1, consumption_rate=1.0)],
        tick=9,
    )
    log = run_consumption(world)
    assert len(log) == 2
    for event in log:
        assert event.type is EventType.RESOURCE_CONSUMED
        assert event.tick == 9


def test_event_payload_uses_resource_string_values_and_is_json_safe() -> None:
    """Payloads carry JSON-compatible strings, never enum objects."""
    world = build_world(
        [build_district("a", population=10, consumption_rate=2.0, food=100.0)], tick=1
    )
    payload = run_consumption(world).events()[0].payload_as_dict()

    assert set(payload) == {
        "district_id", "requested_total", "consumed_total", "unmet_total", "consumed", "unmet",
    }
    assert set(payload["consumed"]) == {"FOOD", "MATERIALS", "ENERGY"}  # type: ignore[arg-type]
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


def test_zero_population_still_emits_an_event_and_changes_nothing() -> None:
    """An empty district consumes nothing but is still part of the record."""
    world = build_world([build_district("a", population=0, consumption_rate=5.0, food=4.0)],
                        tick=1)
    log = run_consumption(world)
    assert len(log) == 1
    assert log.events()[0].payload["requested_total"] == 0.0
    assert world.districts["a"].resources.amount_of(ResourceType.FOOD) == 4.0


def test_zero_consumption_rate_still_emits_an_event() -> None:
    """A zero rate is a valid configuration, not an absence of the district."""
    world = build_world([build_district("a", population=50, consumption_rate=0.0, food=4.0)],
                        tick=1)
    log = run_consumption(world)
    assert len(log) == 1
    assert world.districts["a"].resources.amount_of(ResourceType.FOOD) == 4.0


def test_consumption_does_not_consume_rng() -> None:
    """Consumption is fully deterministic and must not touch the generator."""
    world = build_world(
        [build_district("a", population=10, consumption_rate=1.0, food=100.0)], tick=1
    )
    before = world.rng.get_state()
    run_consumption(world)
    assert world.rng.get_state() == before


def test_consumption_leaves_unrelated_state_untouched() -> None:
    """Only resource stock changes; every other field is preserved exactly."""
    district = build_district("a", population=10, consumption_rate=1.0, food=100.0)
    world = build_world(
        [district, build_district("b")],
        boundaries=[("bound", "a", "b")],
        law=build_law(),
        tick=1,
    )
    world.add_wall(build_wall("wall", "bound", active=True))
    world.add_infrastructure(build_infrastructure("infra", "bound"))

    run_consumption(world)

    assert district.population == 10
    assert district.consumption_rate == 1.0
    assert district.production_rate == 0.0
    assert world.walls["wall"].active is True
    assert world.boundaries["bound"].wall_id == "wall"
    assert world.infrastructure["infra"].dependency_score == 0.0
    assert world.laws["law_movement_sharing"].current_value is True


def test_repeated_ticks_apply_consumption_once_each() -> None:
    """Two updates consume exactly twice, never more."""
    world = build_world(
        [build_district("a", population=1, consumption_rate=10.0, food=100.0)], tick=1
    )
    system = ConsumptionSystem(allocation=EVEN_ALLOCATION)
    bus = EventBus()
    system.update(world, bus)
    world.advance_tick()
    system.update(world, bus)
    assert world.districts["a"].resources.amount_of(ResourceType.FOOD) == 90.0


def test_system_holds_no_per_tick_state() -> None:
    """Configuration only; nothing from a tick may survive into the next one."""
    assert not hasattr(ConsumptionSystem(allocation=EVEN_ALLOCATION), "__dict__")
