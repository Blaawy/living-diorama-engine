"""Integration tests for Production -> Consumption -> Flow through SimulationLoop.

Phase 4's three systems only mean something in sequence: a district produces,
its population eats, and whatever is left above its reserve can travel. These
tests check the sequence as a whole, including that the event log tells the
story in the order it happened.
"""

from living_diorama.entities import ResourceType
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.simulation import SimulationLoop
from living_diorama.systems import ConsumptionSystem, ProductionSystem, ResourceFlowSystem
from living_diorama.systems._resource_config import FLOAT_TOLERANCE
from systems_builders import (
    FOOD_ONLY_ALLOCATION,
    LAW_ID,
    build_district,
    build_law,
    build_wall,
    build_world,
    stocks,
    total_of,
)


def build_pipeline(reserve_ticks: float = 1.0) -> list:
    """Build the Phase 4 pipeline in its intended runtime order."""
    return [
        ProductionSystem(allocation=FOOD_ONLY_ALLOCATION),
        ConsumptionSystem(allocation=FOOD_ONLY_ALLOCATION),
        ResourceFlowSystem(
            law_id=LAW_ID,
            consumption_allocation=FOOD_ONLY_ALLOCATION,
            reserve_ticks=reserve_ticks,
        ),
    ]


def build_scenario(*, law=None, tick=0):
    """Build a rich district that feeds a poor one across an open boundary."""
    return build_world(
        [
            build_district("rich", population=1, production_rate=100.0,
                           consumption_rate=1.0, food=0.0),
            build_district("poor", population=10, production_rate=0.0,
                           consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("bound", "rich", "poor")],
        law=law if law is not None else build_law(),
        tick=tick,
    )


def run_pipeline(world, ticks: int = 1, reserve_ticks: float = 1.0) -> EventLog:
    """Run the full pipeline through SimulationLoop and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    SimulationLoop(build_pipeline(reserve_ticks), bus).run(world, ticks)
    return log


def test_full_pipeline_produces_expected_final_stock() -> None:
    """Produce 100, eat 1, reserve 1, share the rest with a neighbour that needs 10."""
    world = build_scenario()
    run_pipeline(world)
    result = stocks(world, ResourceType.FOOD)

    assert abs(result["poor"] - 10.0) <= FLOAT_TOLERANCE
    assert abs(result["rich"] - 89.0) <= FLOAT_TOLERANCE
    assert abs(total_of(world, ResourceType.FOOD) - 99.0) <= FLOAT_TOLERANCE


def test_event_log_records_the_three_stages_in_order() -> None:
    """Production, then consumption, then transfers: the story in sequence."""
    world = build_scenario()
    log = run_pipeline(world)
    types = [event.type for event in log]

    first_consumed = types.index(EventType.RESOURCE_CONSUMED)
    first_transfer = types.index(EventType.RESOURCE_TRANSFERRED)
    last_produced = max(
        index for index, kind in enumerate(types) if kind is EventType.RESOURCE_PRODUCED
    )
    last_consumed = max(
        index for index, kind in enumerate(types) if kind is EventType.RESOURCE_CONSUMED
    )

    assert last_produced < first_consumed
    assert last_consumed < first_transfer


def test_production_and_consumption_events_are_sorted_by_district_id() -> None:
    """Within each stage, districts are reported in sorted identifier order."""
    world = build_world(
        [
            build_district("zulu", population=1, production_rate=10.0,
                           consumption_rate=1.0),
            build_district("alpha", population=1, production_rate=10.0,
                           consumption_rate=1.0),
            build_district("mike", population=1, production_rate=10.0,
                           consumption_rate=1.0),
        ],
        law=build_law(),
    )
    log = run_pipeline(world)

    produced = [e.source_id for e in log.query(event_type=EventType.RESOURCE_PRODUCED)]
    consumed = [e.source_id for e in log.query(event_type=EventType.RESOURCE_CONSUMED)]
    assert produced == ["alpha", "mike", "zulu"]
    assert consumed == ["alpha", "mike", "zulu"]


def test_event_ticks_match_simulation_loop_semantics() -> None:
    """The loop advances first, so a world starting at 0 reports tick 1."""
    world = build_scenario(tick=0)
    log = run_pipeline(world)
    assert {event.tick for event in log} == {1}


def test_two_ticks_apply_all_three_systems_exactly_twice() -> None:
    """Nothing is skipped and nothing runs twice within a tick."""
    world = build_scenario(tick=0)
    log = run_pipeline(world, ticks=2)

    assert len(log.query(event_type=EventType.RESOURCE_PRODUCED)) == 4
    assert len(log.query(event_type=EventType.RESOURCE_CONSUMED)) == 4
    assert {event.tick for event in log} == {1, 2}


def test_identical_inputs_produce_identical_state_and_events() -> None:
    """The determinism guarantee, end to end."""
    first_world, second_world = build_scenario(), build_scenario()
    first_log = run_pipeline(first_world, ticks=3)
    second_log = run_pipeline(second_world, ticks=3)

    assert stocks(first_world, ResourceType.FOOD) == stocks(second_world, ResourceType.FOOD)
    assert [
        (event.tick, event.type, event.source_id, event.payload_as_dict())
        for event in first_log
    ] == [
        (event.tick, event.type, event.source_id, event.payload_as_dict())
        for event in second_log
    ]


def test_rng_state_is_unchanged_across_the_whole_pipeline() -> None:
    """No Phase 4 system may consume randomness, individually or together."""
    world = build_scenario()
    before = world.rng.get_state()
    run_pipeline(world, ticks=5)
    assert world.rng.get_state() == before


def test_newly_produced_stock_can_be_consumed_and_shared_in_the_same_tick() -> None:
    """The pipeline order is what makes production immediately useful."""
    world = build_scenario()
    log = run_pipeline(world)
    consumption = log.query(event_type=EventType.RESOURCE_CONSUMED, source_id="rich")[0]

    assert consumption.payload["consumed_total"] == 1.0
    assert consumption.payload["unmet_total"] == 0.0
    assert len(log.query(event_type=EventType.RESOURCE_TRANSFERRED)) == 1


def test_flow_uses_post_consumption_stock() -> None:
    """A district that eats its whole harvest has nothing left to share."""
    world = build_world(
        [
            build_district("rich", population=100, production_rate=100.0,
                           consumption_rate=1.0, food=0.0),
            build_district("poor", population=10, production_rate=0.0,
                           consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("bound", "rich", "poor")],
        law=build_law(),
    )
    log = run_pipeline(world)

    assert len(log.query(event_type=EventType.RESOURCE_TRANSFERRED)) == 0
    assert stocks(world, ResourceType.FOOD)["poor"] == 0.0


def test_received_stock_is_not_forwarded_within_the_same_tick() -> None:
    """A ↔ B ↔ C over one tick: C is reached only in a later tick, if at all."""
    world = build_world(
        [
            build_district("a", population=0, production_rate=100.0,
                           consumption_rate=1.0),
            build_district("b", population=10, production_rate=0.0,
                           consumption_rate=1.0),
            build_district("c", population=10, production_rate=0.0,
                           consumption_rate=1.0),
        ],
        boundaries=[("ab", "a", "b"), ("bc", "b", "c")],
        law=build_law(),
    )
    log = run_pipeline(world)

    transfers = log.query(event_type=EventType.RESOURCE_TRANSFERRED)
    assert all(event.payload["from_district_id"] == "a" for event in transfers)
    assert stocks(world, ResourceType.FOOD)["c"] == 0.0


def test_an_active_wall_changes_flow_without_touching_production_or_consumption() -> None:
    """The wall is a barrier to sharing only; districts still live their own lives."""
    open_world = build_scenario()
    walled_world = build_scenario()
    walled_world.add_wall(build_wall("wall", "bound", active=True))

    open_log = run_pipeline(open_world)
    walled_log = run_pipeline(walled_world)

    for kind in (EventType.RESOURCE_PRODUCED, EventType.RESOURCE_CONSUMED):
        assert [event.payload_as_dict() for event in open_log.query(event_type=kind)] == [
            event.payload_as_dict() for event in walled_log.query(event_type=kind)
        ]

    assert len(open_log.query(event_type=EventType.RESOURCE_TRANSFERRED)) == 1
    assert len(walled_log.query(event_type=EventType.RESOURCE_TRANSFERRED)) == 0
    assert stocks(walled_world, ResourceType.FOOD)["poor"] == 0.0


def test_a_disabled_law_changes_flow_without_touching_production_or_consumption() -> None:
    """Repealing sharing isolates districts without altering what they make or eat."""
    sharing = build_scenario()
    repealed = build_scenario(law=build_law(active=True, current_value=False))

    sharing_log = run_pipeline(sharing)
    repealed_log = run_pipeline(repealed)

    for kind in (EventType.RESOURCE_PRODUCED, EventType.RESOURCE_CONSUMED):
        assert [event.payload_as_dict() for event in sharing_log.query(event_type=kind)] == [
            event.payload_as_dict() for event in repealed_log.query(event_type=kind)
        ]

    assert len(repealed_log.query(event_type=EventType.RESOURCE_TRANSFERRED)) == 0
    assert stocks(repealed, ResourceType.FOOD)["poor"] == 0.0


def test_world_state_remains_valid_after_every_tick() -> None:
    """No stock goes negative and no pool becomes malformed over a long run."""
    world = build_scenario()
    bus = EventBus()
    loop = SimulationLoop(build_pipeline(), bus)

    for _ in range(20):
        loop.run(world, 1)
        for district_id in sorted(world.districts):
            pool = world.districts[district_id].resources
            for resource in ResourceType:
                assert pool.amount_of(resource) >= 0.0


def test_conservation_holds_across_the_flow_stage_of_a_long_run() -> None:
    """Production and consumption change totals; flow alone must not."""
    world = build_scenario()
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    loop = SimulationLoop(build_pipeline(), bus)

    for _ in range(10):
        before_flow = total_of(world, ResourceType.FOOD)
        transfers_before = len(log.query(event_type=EventType.RESOURCE_TRANSFERRED))
        loop.run(world, 1)
        transfers_after = len(log.query(event_type=EventType.RESOURCE_TRANSFERRED))
        after = total_of(world, ResourceType.FOOD)

        produced = sum(
            float(event.payload["total_produced"])
            for event in log.query(event_type=EventType.RESOURCE_PRODUCED, tick_start=world.tick)
        )
        consumed = sum(
            float(event.payload["consumed_total"])
            for event in log.query(event_type=EventType.RESOURCE_CONSUMED, tick_start=world.tick)
        )
        assert abs(after - (before_flow + produced - consumed)) <= FLOAT_TOLERANCE
        assert transfers_after >= transfers_before
