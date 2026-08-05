"""Integration tests for the full Phase 5 pipeline.

Production -> Consumption -> ResourceFlow -> Migration -> Scarcity.

The point of the order is that each stage sees what the one before it did, and
the scarcity recorded at the end describes the district as it actually stands:
after it has produced, eaten, been helped by a neighbour, and lost or gained
people. These tests check that chain end to end rather than each link alone.
"""

import pytest
from systems_builders import (
    EVEN_ALLOCATION,
    LAW_ID,
    build_district,
    build_law,
    build_wall,
    build_world,
)

from living_diorama.entities import ResourceType
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.simulation import SimulationLoop
from living_diorama.systems import (
    ConsumptionSystem,
    MigrationSystem,
    ProductionSystem,
    ResourceFlowSystem,
    ScarcitySystem,
)
from living_diorama.systems._pressure import shortfall_ratio
from living_diorama.systems._resource_config import FLOAT_TOLERANCE


def build_pipeline(*, migration_rate: float = 0.2, reserve_ticks: float = 1.0) -> list:
    """Build the Phase 5 pipeline in its required causal order."""
    return [
        ProductionSystem(allocation=EVEN_ALLOCATION),
        ConsumptionSystem(allocation=EVEN_ALLOCATION),
        ResourceFlowSystem(
            law_id=LAW_ID,
            consumption_allocation=EVEN_ALLOCATION,
            reserve_ticks=reserve_ticks,
        ),
        MigrationSystem(
            law_id=LAW_ID,
            consumption_allocation=EVEN_ALLOCATION,
            migration_rate=migration_rate,
            min_pressure_gap=0.05,
            partial_isolation_factor=0.5,
        ),
        ScarcitySystem(consumption_allocation=EVEN_ALLOCATION),
    ]


def run_pipeline(world, ticks: int = 1, **kwargs) -> EventLog:
    """Run the full pipeline through SimulationLoop and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    SimulationLoop(build_pipeline(**kwargs), bus).run(world, ticks)
    return log


def build_scenario(*, tick: int = 0, walled: bool = False):
    """A productive district beside a barren one, joined by a boundary."""
    world = build_world(
        [
            build_district("rich", population=10, production_rate=200.0, consumption_rate=1.0),
            build_district("poor", population=100, production_rate=0.0, consumption_rate=1.0),
        ],
        boundaries=[("bound", "poor", "rich")],
        law=build_law(),
        tick=tick,
    )
    if walled:
        world.add_wall(build_wall("wall", "bound", active=True))
    return world


def build_overwhelmed_scenario(*, tick: int = 0):
    """A barren district too large for its neighbour's surplus to rescue.

    Sharing helps but cannot cover the shortfall, so every stage of the
    pipeline does something: resources are produced, eaten, shared, people
    leave, and the scarcity that remains is recorded.
    """
    return build_world(
        [
            build_district("rich", population=10, production_rate=200.0, consumption_rate=1.0),
            build_district("poor", population=1000, production_rate=0.0, consumption_rate=1.0),
        ],
        boundaries=[("bound", "poor", "rich")],
        law=build_law(),
        tick=tick,
    )


def test_pipeline_runs_all_five_stages_in_order() -> None:
    """The event log tells the tick's story in causal sequence."""
    log = run_pipeline(build_overwhelmed_scenario())
    order = [event.type for event in log]

    assert set(order) == {
        EventType.RESOURCE_PRODUCED,
        EventType.RESOURCE_CONSUMED,
        EventType.RESOURCE_TRANSFERRED,
        EventType.POPULATION_MIGRATED,
        EventType.SCARCITY_CHANGED,
    }

    def last(kind: EventType) -> int:
        """Index of the final event of a kind."""
        return max(index for index, value in enumerate(order) if value is kind)

    def first(kind: EventType) -> int:
        """Index of the first event of a kind."""
        return order.index(kind)

    assert last(EventType.RESOURCE_PRODUCED) < first(EventType.RESOURCE_CONSUMED)
    assert last(EventType.RESOURCE_CONSUMED) < first(EventType.RESOURCE_TRANSFERRED)
    assert last(EventType.RESOURCE_TRANSFERRED) < first(EventType.POPULATION_MIGRATED)
    assert last(EventType.POPULATION_MIGRATED) < first(EventType.SCARCITY_CHANGED)


def test_final_scarcity_matches_the_tick_final_state() -> None:
    """Scarcity is recomputable from the world the tick ends in.

    This is the Phase 5 exit criterion: the recorded score is not a leftover
    from an earlier stage but a reading of the final population and stock.
    """
    world = build_scenario()
    run_pipeline(world)

    for district_id in sorted(world.districts):
        district = world.districts[district_id]
        expected = shortfall_ratio(district, EVEN_ALLOCATION)
        assert abs(district.scarcity - expected) <= FLOAT_TOLERANCE
        assert 0.0 <= district.scarcity <= 1.0


def test_migration_uses_post_flow_state_so_relief_prevents_departure() -> None:
    """A district rescued by its neighbour keeps its people.

    With sharing enabled the poor district is fed and nobody leaves. With the
    same world walled off, it is not fed and people go -- except the wall also
    blocks them, which is the scar the whole series is about.
    """
    shared = build_scenario()
    walled = build_scenario(walled=True)

    shared_log = run_pipeline(shared)
    walled_log = run_pipeline(walled)

    assert len(shared_log.query(event_type=EventType.POPULATION_MIGRATED)) == 0
    assert shared.districts["poor"].population == 100
    assert shared.districts["poor"].scarcity == 0.0

    assert len(walled_log.query(event_type=EventType.POPULATION_MIGRATED)) == 0
    assert walled.districts["poor"].population == 100
    assert walled.districts["poor"].scarcity == 1.0


def test_migration_relieves_scarcity_in_the_same_tick() -> None:
    """Fewer mouths against the same stock is a lower score, immediately.

    Sharing is permitted here but cannot cover a district this large, so people
    leave, and the scarcity recorded afterwards reflects the smaller population
    they left behind rather than the one the tick began with.
    """
    world = build_overwhelmed_scenario()
    run_pipeline(world)

    poor = world.districts["poor"]
    assert poor.population < 1000
    assert poor.scarcity == shortfall_ratio(poor, EVEN_ALLOCATION)

    heavier = shortfall_ratio(
        build_district(
            "shadow",
            population=1000,
            consumption_rate=1.0,
            food=poor.resources.amount_of(ResourceType.FOOD),
            materials=poor.resources.amount_of(ResourceType.MATERIALS),
            energy=poor.resources.amount_of(ResourceType.ENERGY),
        ),
        EVEN_ALLOCATION,
    )
    assert poor.scarcity <= heavier


def test_population_and_resources_are_conserved_across_the_pipeline() -> None:
    """Migration moves no resources and flow moves no people."""
    world = build_scenario()
    before_population = sum(
        world.districts[district_id].population for district_id in world.districts
    )
    log = run_pipeline(world)

    after_population = sum(
        world.districts[district_id].population for district_id in world.districts
    )
    assert after_population == before_population

    produced = sum(
        float(event.payload["total_produced"])
        for event in log.query(event_type=EventType.RESOURCE_PRODUCED)
    )
    consumed = sum(
        float(event.payload["consumed_total"])
        for event in log.query(event_type=EventType.RESOURCE_CONSUMED)
    )
    stock = sum(
        world.districts[district_id].resources.amount_of(resource)
        for district_id in world.districts
        for resource in ResourceType
    )
    assert abs(stock - (produced - consumed)) <= FLOAT_TOLERANCE


def test_identical_worlds_produce_identical_state_and_events() -> None:
    """The determinism guarantee, across all five systems."""
    first_world, second_world = build_scenario(), build_scenario()
    first_log = run_pipeline(first_world, ticks=3)
    second_log = run_pipeline(second_world, ticks=3)

    for district_id in sorted(first_world.districts):
        first = first_world.districts[district_id]
        second = second_world.districts[district_id]
        assert first.population == second.population
        assert first.scarcity == second.scarcity

    assert [
        (event.tick, event.type, event.source_id, event.payload_as_dict()) for event in first_log
    ] == [
        (event.tick, event.type, event.source_id, event.payload_as_dict()) for event in second_log
    ]


def test_rng_is_untouched_by_the_whole_pipeline() -> None:
    """No Phase 4 or Phase 5 system may consume randomness."""
    world = build_scenario()
    before = world.rng.get_state()
    run_pipeline(world, ticks=5)
    assert world.rng.get_state() == before


def test_world_stays_valid_over_a_long_run() -> None:
    """Populations, stock, and scarcity all stay in range tick after tick."""
    world = build_scenario()
    bus = EventBus()
    loop = SimulationLoop(build_pipeline(), bus)
    before = sum(world.districts[district_id].population for district_id in world.districts)

    for _ in range(25):
        loop.run(world, 1)
        for district_id in sorted(world.districts):
            district = world.districts[district_id]
            assert district.population >= 0
            assert district.population <= district.housing_capacity
            assert 0.0 <= district.scarcity <= 1.0
            for resource in ResourceType:
                assert district.resources.amount_of(resource) >= 0.0
        assert (
            sum(world.districts[district_id].population for district_id in world.districts)
            == before
        )


def test_every_district_reports_scarcity_every_tick() -> None:
    """Two ticks over two districts is four readings, in sorted order."""
    log = run_pipeline(build_scenario(), ticks=2)
    readings = log.query(event_type=EventType.SCARCITY_CHANGED)

    assert len(readings) == 4
    assert [event.source_id for event in readings] == ["poor", "rich", "poor", "rich"]
    assert {event.tick for event in readings} == {1, 2}


# --- The forward-scarcity contract, demonstrated end to end -----------------


def test_exactly_one_tick_of_supply_is_met_in_full_yet_scores_maximum_scarcity() -> None:
    """The case that makes the contract concrete.

    A district holding exactly one tick of supply eats all of it. Nothing went
    unmet while it ate, so ConsumptionSystem reports ``unmet_total`` of zero.
    It now holds nothing against an undiminished projected demand, so its
    forward scarcity is one. Both readings are correct and they describe
    different things: hunger suffered, and exposure ahead.
    """
    world = build_world(
        [
            build_district(
                "solo", population=10, consumption_rate=1.0, food=5.0, materials=3.0, energy=2.0
            )
        ],
        law=build_law(),
        tick=0,
    )
    log = run_pipeline(world)

    consumption = log.query(event_type=EventType.RESOURCE_CONSUMED)[0]
    assert consumption.payload["unmet_total"] == 0.0
    assert consumption.payload["consumed_total"] == 10.0

    assert world.districts["solo"].scarcity == 1.0
    scarcity = log.query(event_type=EventType.SCARCITY_CHANGED)[0].payload_as_dict()
    assert scarcity["projected_required_total"] == 10.0
    assert scarcity["projected_shortfall_total"] == 10.0


def test_a_full_further_tick_of_supply_scores_zero_forward_scarcity() -> None:
    """Two ticks of supply, one tick eaten: one tick left, and no exposure."""
    world = build_world(
        [
            build_district(
                "solo", population=10, consumption_rate=1.0, food=10.0, materials=6.0, energy=4.0
            )
        ],
        law=build_law(),
        tick=0,
    )
    log = run_pipeline(world)

    assert log.query(event_type=EventType.RESOURCE_CONSUMED)[0].payload["unmet_total"] == 0.0
    assert world.districts["solo"].scarcity == 0.0


def test_post_migration_population_changes_projected_demand_in_the_same_tick() -> None:
    """Scarcity is scored against the population the district ends the tick with.

    Recomputing the score from the district's final state reproduces exactly
    what was recorded, which it could not if the score had been taken before
    people left.
    """
    world = build_overwhelmed_scenario()
    log = run_pipeline(world)

    poor = world.districts["poor"]
    migrated = log.query(event_type=EventType.POPULATION_MIGRATED)
    assert migrated
    assert poor.population < 1000

    reading = log.query(event_type=EventType.SCARCITY_CHANGED, source_id="poor")[0]
    assert reading.payload["population"] == poor.population
    assert reading.payload["projected_required_total"] == pytest.approx(
        poor.population * poor.consumption_rate
    )
    assert poor.scarcity == shortfall_ratio(poor, EVEN_ALLOCATION)


def test_forward_scarcity_stays_finite_and_bounded_over_a_long_run() -> None:
    """Every reading, every tick, inside the unit interval."""
    world = build_overwhelmed_scenario()
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    loop = SimulationLoop(build_pipeline(), bus)

    for _ in range(15):
        loop.run(world, 1)
        for district_id in sorted(world.districts):
            assert 0.0 <= world.districts[district_id].scarcity <= 1.0

    for event in log.query(event_type=EventType.SCARCITY_CHANGED):
        payload = event.payload_as_dict()
        assert 0.0 <= float(payload["new_scarcity"]) <= 1.0  # type: ignore[arg-type]
        assert float(payload["projected_shortfall_total"]) >= 0.0  # type: ignore[arg-type]
        assert float(payload["projected_required_total"]) >= 0.0  # type: ignore[arg-type]
