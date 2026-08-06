"""Integration tests for the full Phase 7 pipeline.

Production -> Consumption -> ResourceFlow -> Migration -> Scarcity ->
SocialStability -> InstitutionalPressure.

The institutional layer sits at the very end because it reads what everything
before it settled on: the scarcity the economy left, and the fear and trust the
social layer just wrote. These tests prove that reading is genuinely of the
same tick's final state, that the causal chain runs all the way through, and
that institutional pressure remembers a crisis after the crisis has passed.
"""

import math

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
    InstitutionalPressureSystem,
    MigrationSystem,
    ProductionSystem,
    ResourceFlowSystem,
    ScarcitySystem,
    SocialStabilitySystem,
)


def build_pipeline(
    *,
    migration_rate: float = 0.2,
    reserve_ticks: float = 1.0,
    social_response: float = 0.25,
    institutional_response: float = 0.20,
) -> list:
    """Build the Phase 7 pipeline in its required causal order."""
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
        SocialStabilitySystem(response_rate=social_response),
        InstitutionalPressureSystem(response_rate=institutional_response),
    ]


def run_pipeline(world, ticks: int = 1, **kwargs) -> EventLog:
    """Run the full pipeline through SimulationLoop and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    SimulationLoop(build_pipeline(**kwargs), bus).run(world, ticks)
    return log


def expected_target(scarcity: float, fear: float, trust: float) -> float:
    """Return the equally weighted institutional target for a final district state."""
    return (scarcity + fear + (1.0 - trust)) / 3.0


def build_starving_world(*, tick: int = 0):
    """A single district that eats its whole stock and has nowhere to turn."""
    return build_world(
        [
            build_district(
                "solo",
                population=10,
                consumption_rate=1.0,
                food=5.0,
                materials=3.0,
                energy=2.0,
                housing_capacity=1000,
                fear=0.0,
                trust=1.0,
                institutional_pressure=0.0,
            )
        ],
        law=build_law(),
        tick=tick,
    )


# --- Scenario A: the social state read is this tick's, not last tick's ------


def test_institutional_pressure_reads_the_social_state_written_this_tick() -> None:
    """Fear and trust move first, and the institutional target uses the new values.

    Computing the target from the district's final fear and trust reproduces
    exactly what was recorded. It could not if the institutional layer had read
    the values the tick began with, because the social layer changed them in
    between.
    """
    world = build_starving_world()
    log = run_pipeline(world)

    district = world.districts["solo"]
    assert district.fear > 0.0, "the social layer must have moved fear this tick"
    assert district.trust < 1.0

    reading = log.query(event_type=EventType.INSTITUTIONAL_PRESSURE_CHANGED)[0]
    payload = reading.payload_as_dict()

    assert payload["fear"] == district.fear
    assert payload["trust"] == district.trust
    assert payload["scarcity"] == district.scarcity
    assert payload["target_institutional_pressure"] == pytest.approx(
        expected_target(district.scarcity, district.fear, district.trust)
    )
    assert payload["target_institutional_pressure"] != pytest.approx(
        expected_target(district.scarcity, 0.0, 1.0)
    ), "the target must not have been computed from the tick's opening social state"


def test_the_institutional_event_follows_the_social_event() -> None:
    """Supplied system order shows up as event order in the recorded history."""
    log = run_pipeline(build_starving_world())
    order = [event.type for event in log]

    last_social = max(
        index for index, kind in enumerate(order) if kind is EventType.SOCIAL_STABILITY_CHANGED
    )
    first_institutional = order.index(EventType.INSTITUTIONAL_PRESSURE_CHANGED)
    assert last_social < first_institutional


# --- Scenario B: a resource crisis propagates the whole way through ---------


def test_a_resource_crisis_propagates_to_institutional_pressure_in_one_tick() -> None:
    """The full chain: stock runs out, scarcity rises, fear rises, pressure rises."""
    world = build_starving_world()
    log = run_pipeline(world)
    district = world.districts["solo"]

    assert district.scarcity == 1.0
    assert district.fear > 0.0
    assert district.trust < 1.0
    assert district.institutional_pressure > 0.0

    kinds = [event.type for event in log]
    for expected_kind in (
        EventType.RESOURCE_CONSUMED,
        EventType.SCARCITY_CHANGED,
        EventType.SOCIAL_STABILITY_CHANGED,
        EventType.INSTITUTIONAL_PRESSURE_CHANGED,
    ):
        assert expected_kind in kinds


# --- Scenario C: relief through resource flow softens the institutional target


def build_relief_world(*, sharing: bool):
    """A barren district beside a productive one, with sharing on or off."""
    return build_world(
        [
            build_district(
                "rich",
                population=10,
                production_rate=200.0,
                consumption_rate=1.0,
                housing_capacity=100_000,
            ),
            build_district(
                "poor",
                population=100,
                production_rate=0.0,
                consumption_rate=1.0,
                housing_capacity=100_000,
                fear=0.0,
                trust=1.0,
                institutional_pressure=0.0,
            ),
        ],
        boundaries=[("bound", "poor", "rich")],
        law=build_law(active=True, current_value=sharing),
        tick=0,
    )


def test_resource_relief_lowers_the_institutional_target() -> None:
    """The institutional layer sees improved post-flow scarcity, not the shortage."""
    shared = build_relief_world(sharing=True)
    isolated = build_relief_world(sharing=False)

    run_pipeline(shared)
    run_pipeline(isolated)

    assert shared.districts["poor"].scarcity < isolated.districts["poor"].scarcity
    assert (
        shared.districts["poor"].institutional_pressure
        < isolated.districts["poor"].institutional_pressure
    )


# --- Scenario D: migration changes the state the institutional layer reads --


def test_migration_changes_the_state_institutional_pressure_reads() -> None:
    """People leaving changes scarcity and social state, and pressure follows."""
    crowded = build_district(
        "crowded",
        population=1000,
        consumption_rate=1.0,
        housing_capacity=500,
        fear=0.0,
        trust=1.0,
        institutional_pressure=0.0,
    )
    relief = build_district(
        "relief",
        population=10,
        production_rate=200.0,
        consumption_rate=1.0,
        housing_capacity=100_000,
    )
    world = build_world(
        [crowded, relief],
        boundaries=[("bound", "crowded", "relief")],
        law=build_law(),
        tick=0,
    )
    starting_population = crowded.population
    log = run_pipeline(world)

    assert crowded.population < starting_population

    reading = log.query(event_type=EventType.INSTITUTIONAL_PRESSURE_CHANGED, source_id="crowded")[0]
    payload = reading.payload_as_dict()
    assert payload["scarcity"] == crowded.scarcity
    assert payload["fear"] == crowded.fear
    assert payload["target_institutional_pressure"] == pytest.approx(
        expected_target(crowded.scarcity, crowded.fear, crowded.trust)
    )


# --- Scenario E: recovery lags -----------------------------------------------


def test_institutional_pressure_lags_behind_recovery() -> None:
    """A crisis leaves institutional pressure elevated after conditions improve.

    This is what makes the world remember: the stored pressure carries the
    crisis forward, without any hidden history inside the system.
    """
    world = build_starving_world()
    bus = EventBus()
    loop = SimulationLoop(build_pipeline(), bus)

    for _ in range(15):
        loop.run(world, 1)
    district = world.districts["solo"]
    crisis_pressure = district.institutional_pressure
    assert crisis_pressure > 0.5

    # The district becomes self-sufficient: plenty produced, little needed.
    district.production_rate = 500.0
    district.consumption_rate = 0.1

    loop.run(world, 1)
    assert district.scarcity == 0.0
    assert district.institutional_pressure < crisis_pressure
    assert district.institutional_pressure > 0.4, (
        "one good tick must not erase the institutional memory of the crisis"
    )

    for _ in range(60):
        loop.run(world, 1)
    assert district.institutional_pressure < 0.1, "sustained relief must eventually recover"


# --- Scenario F: the whole chain is deterministic ---------------------------


def build_full_scenario():
    """A world exercising every stage of the chain."""
    return build_world(
        [
            build_district(
                "rich",
                population=10,
                production_rate=200.0,
                consumption_rate=1.0,
                housing_capacity=100_000,
                fear=0.1,
                trust=0.9,
                institutional_pressure=0.05,
            ),
            build_district(
                "poor",
                population=1000,
                production_rate=0.0,
                consumption_rate=1.0,
                housing_capacity=400,
                fear=0.2,
                trust=0.8,
                institutional_pressure=0.15,
            ),
        ],
        boundaries=[("bound", "poor", "rich")],
        law=build_law(),
        tick=0,
    )


def test_the_full_chain_is_deterministic() -> None:
    """Two equivalent worlds through seven systems agree on everything."""
    first, second = build_full_scenario(), build_full_scenario()
    first_log = run_pipeline(first, ticks=4)
    second_log = run_pipeline(second, ticks=4)

    for district_id in sorted(first.districts):
        left, right = first.districts[district_id], second.districts[district_id]
        assert left.population == right.population
        assert left.scarcity == right.scarcity
        assert left.fear == right.fear
        assert left.trust == right.trust
        assert left.institutional_pressure == right.institutional_pressure
        for resource in ResourceType:
            assert left.resources.amount_of(resource) == right.resources.amount_of(resource)

    assert [
        (event.tick, event.type, event.source_id, event.payload_as_dict()) for event in first_log
    ] == [
        (event.tick, event.type, event.source_id, event.payload_as_dict()) for event in second_log
    ]


def test_the_full_chain_consumes_no_randomness() -> None:
    """No system in the chain, Phase 7 included, may touch the generator."""
    world = build_full_scenario()
    before = world.rng.get_state()
    run_pipeline(world, ticks=5)
    assert world.rng.get_state() == before


def test_no_wall_or_boundary_decision_occurs() -> None:
    """Phase 7 records pressure and decides nothing with it.

    Institutional pressure climbs across the run and the topology is exactly as
    it began: no wall built, none activated, no boundary altered, no law
    touched. Turning pressure into a decision belongs to a later phase.
    """
    world = build_full_scenario()
    world.add_wall(build_wall("wall", "bound", active=False))
    before_walls = {
        wall_id: (world.walls[wall_id].active, world.walls[wall_id].integrity)
        for wall_id in world.walls
    }
    before_boundary = world.boundaries["bound"].wall_id
    before_law = (world.laws[LAW_ID].active, world.laws[LAW_ID].current_value)

    log = run_pipeline(world, ticks=10)

    assert world.districts["poor"].institutional_pressure > 0.15
    assert {
        wall_id: (world.walls[wall_id].active, world.walls[wall_id].integrity)
        for wall_id in world.walls
    } == before_walls
    assert world.boundaries["bound"].wall_id == before_boundary
    assert (world.laws[LAW_ID].active, world.laws[LAW_ID].current_value) == before_law
    assert len(log.query(event_type=EventType.WALL_BUILT)) == 0
    assert len(log.query(event_type=EventType.WALL_CHANGED)) == 0


def test_institutional_pressure_stays_bounded_over_a_long_run() -> None:
    """Every district, every tick, inside the unit interval."""
    world = build_full_scenario()
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    loop = SimulationLoop(build_pipeline(), bus)

    for _ in range(25):
        loop.run(world, 1)
        for district_id in sorted(world.districts):
            pressure = world.districts[district_id].institutional_pressure
            assert 0.0 <= pressure <= 1.0
            assert math.isfinite(pressure)

    for event in log.query(event_type=EventType.INSTITUTIONAL_PRESSURE_CHANGED):
        payload = event.payload_as_dict()
        for key in (
            "scarcity",
            "fear",
            "trust",
            "distrust",
            "target_institutional_pressure",
            "new_institutional_pressure",
        ):
            value = float(payload[key])  # type: ignore[arg-type]
            assert 0.0 <= value <= 1.0
            assert math.isfinite(value)


def test_institutional_state_persists_across_ticks_rather_than_being_recomputed() -> None:
    """Two districts under identical pressure but different histories stay different."""
    calm = build_district(
        "calm",
        population=100,
        consumption_rate=1.0,
        housing_capacity=1000,
        fear=0.0,
        trust=1.0,
        institutional_pressure=0.0,
    )
    scarred = build_district(
        "scarred",
        population=100,
        consumption_rate=1.0,
        housing_capacity=1000,
        fear=0.0,
        trust=1.0,
        institutional_pressure=0.9,
    )
    world = build_world([calm, scarred], law=build_law(), tick=0)
    run_pipeline(world)

    assert calm.scarcity == scarred.scarcity
    assert calm.fear == scarred.fear
    assert calm.institutional_pressure < scarred.institutional_pressure


def test_every_changed_district_reports_once_per_tick() -> None:
    """Two ticks over two moving districts is four institutional readings."""
    world = build_full_scenario()
    log = run_pipeline(world, ticks=2)
    readings = log.query(event_type=EventType.INSTITUTIONAL_PRESSURE_CHANGED)

    assert len(readings) == 4
    assert [event.source_id for event in readings] == ["poor", "rich", "poor", "rich"]
    assert {event.tick for event in readings} == {1, 2}
