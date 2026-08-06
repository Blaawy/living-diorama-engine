"""Integration tests for the full Phase 6 pipeline.

Production -> Consumption -> ResourceFlow -> Migration -> Scarcity ->
SocialStability.

The social layer sits at the end of the chain on purpose: it reads what the
economic and demographic systems finally settled on, not what the tick started
with. These tests prove that reading is genuinely of the final state, and that
the systems above it reach the social layer only through that state -- never by
the social layer inspecting a law or a wall for itself.
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
    MigrationSystem,
    ProductionSystem,
    ResourceFlowSystem,
    ScarcitySystem,
    SocialStabilitySystem,
)
from living_diorama.systems._resource_config import FLOAT_TOLERANCE
from living_diorama.systems.social_stability_system import housing_pressure


def build_pipeline(
    *,
    migration_rate: float = 0.2,
    reserve_ticks: float = 1.0,
    response_rate: float = 0.25,
    scarcity_weight: float = 1.0,
    housing_pressure_weight: float = 1.0,
) -> list:
    """Build the Phase 6 pipeline in its intended causal order."""
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
        SocialStabilitySystem(
            scarcity_weight=scarcity_weight,
            housing_pressure_weight=housing_pressure_weight,
            response_rate=response_rate,
        ),
    ]


def run_pipeline(world, ticks: int = 1, **kwargs) -> EventLog:
    """Run the full pipeline through SimulationLoop and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    SimulationLoop(build_pipeline(**kwargs), bus).run(world, ticks)
    return log


def expected_fear(previous: float, pressure: float, rate: float = 0.25) -> float:
    """Return the fear a district should reach from one gradual step."""
    return previous + rate * (pressure - previous)


# --- Scenario A: scarcity reaches the social layer in the same tick ---------


def test_scarcity_computed_this_tick_drives_this_tick_social_update() -> None:
    """The social layer reads the scarcity ScarcitySystem just wrote.

    The district eats its entire stock, so its forward scarcity is total, and
    its fear must move by exactly one gradual step toward the pressure that
    scarcity implies -- computed from the value recorded this tick, not from
    the zero it carried in.
    """
    district = build_district(
        "solo",
        population=10,
        consumption_rate=1.0,
        food=5.0,
        materials=3.0,
        energy=2.0,
        housing_capacity=1000,
        fear=0.0,
        trust=1.0,
    )
    world = build_world([district], law=build_law(), tick=0)
    log = run_pipeline(world, scarcity_weight=1.0, housing_pressure_weight=0.0)

    assert district.scarcity == 1.0
    assert district.fear == pytest.approx(expected_fear(0.0, 1.0))
    assert district.trust == pytest.approx(1.0 + 0.25 * (0.0 - 1.0))

    social = log.query(event_type=EventType.SOCIAL_STABILITY_CHANGED)[0]
    assert social.payload["scarcity_pressure"] == 1.0


def test_the_social_event_follows_the_scarcity_event() -> None:
    """Supplied system order shows up as event order in the recorded history."""
    world = build_world(
        [
            build_district(
                "solo",
                population=10,
                consumption_rate=1.0,
                food=5.0,
                materials=3.0,
                energy=2.0,
                housing_capacity=1000,
            )
        ],
        law=build_law(),
        tick=0,
    )
    log = run_pipeline(world)
    order = [event.type for event in log]

    last_scarcity = max(
        index for index, kind in enumerate(order) if kind is EventType.SCARCITY_CHANGED
    )
    first_social = order.index(EventType.SOCIAL_STABILITY_CHANGED)
    assert last_scarcity < first_social


# --- Scenario B: migration changes housing pressure before the social read --


def test_social_pressure_uses_post_migration_population() -> None:
    """Housing pressure is measured against the population migration left behind.

    The crowded district loses people this tick, so the housing pressure the
    social layer sees is the one implied by its final population. Recomputing
    it from the population the tick started with gives a different number, and
    the assertion below would fail against it.
    """
    crowded = build_district(
        "crowded",
        population=1000,
        consumption_rate=1.0,
        housing_capacity=500,
        fear=0.0,
        trust=1.0,
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

    social = log.query(event_type=EventType.SOCIAL_STABILITY_CHANGED, source_id="crowded")[0]
    final_pressure = housing_pressure(crowded.population, crowded.housing_capacity)
    starting_pressure = housing_pressure(starting_population, crowded.housing_capacity)

    assert social.payload["housing_pressure"] == pytest.approx(final_pressure)
    assert final_pressure != pytest.approx(starting_pressure)


# --- Scenario C: relief through resource flow softens social pressure -------


def build_relief_scenario(*, sharing: bool):
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
            ),
        ],
        boundaries=[("bound", "poor", "rich")],
        law=build_law(active=True, current_value=sharing),
        tick=0,
    )


def test_resource_relief_lowers_the_social_pressure_that_is_read() -> None:
    """The social layer sees improved final scarcity, not the pre-flow shortage."""
    shared = build_relief_scenario(sharing=True)
    isolated = build_relief_scenario(sharing=False)

    run_pipeline(shared)
    run_pipeline(isolated)

    assert shared.districts["poor"].scarcity < isolated.districts["poor"].scarcity
    assert shared.districts["poor"].fear < isolated.districts["poor"].fear
    assert shared.districts["poor"].trust > isolated.districts["poor"].trust


# --- Scenario D: walls and laws reach Phase 6 only through world state ------


def _world_attributes_read_by_the_social_system() -> set[str]:
    """Return every attribute the social system actually reads off ``world``.

    Parsed from the code rather than matched in the text, so that a docstring
    explaining what the system does *not* consult cannot be mistaken for the
    system consulting it.
    """
    import ast  # noqa: PLC0415
    import pathlib  # noqa: PLC0415

    import living_diorama.systems.social_stability_system as module  # noqa: PLC0415

    tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "world"
    }


def test_a_wall_changes_social_outcome_without_the_social_system_reading_it() -> None:
    """Topology reaches the social layer only as scarcity and population.

    The walled world develops more fear because its districts end the tick
    worse off, not because SocialStabilitySystem consulted the wall. The source
    check below is what holds that line: the system never mentions walls, laws,
    or boundaries at all.
    """
    open_world = build_relief_scenario(sharing=True)
    walled = build_relief_scenario(sharing=True)
    walled.add_wall(build_wall("wall", "bound", active=True))

    run_pipeline(open_world)
    run_pipeline(walled)

    assert walled.districts["poor"].fear > open_world.districts["poor"].fear
    assert walled.walls["wall"].active is True
    assert walled.boundaries["bound"].wall_id == "wall"
    assert walled.laws[LAW_ID].current_value is True

    assert _world_attributes_read_by_the_social_system() <= {"districts", "tick"}


def test_a_disabled_law_changes_social_outcome_only_through_final_state() -> None:
    """Repealing sharing worsens scarcity, and only then worsens fear."""
    shared = build_relief_scenario(sharing=True)
    repealed = build_relief_scenario(sharing=False)

    run_pipeline(shared)
    run_pipeline(repealed)

    assert repealed.districts["poor"].scarcity > shared.districts["poor"].scarcity
    assert repealed.districts["poor"].fear > shared.districts["poor"].fear
    assert repealed.laws[LAW_ID].active is True
    assert repealed.laws[LAW_ID].current_value is False


# --- Scenario E: the whole chain is deterministic ---------------------------


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
            ),
            build_district(
                "poor",
                population=1000,
                production_rate=0.0,
                consumption_rate=1.0,
                housing_capacity=400,
                fear=0.2,
                trust=0.8,
            ),
        ],
        boundaries=[("bound", "poor", "rich")],
        law=build_law(),
        tick=0,
    )


def test_the_full_chain_is_deterministic() -> None:
    """Two equivalent worlds through six systems agree on everything."""
    first, second = build_full_scenario(), build_full_scenario()
    first_log = run_pipeline(first, ticks=4)
    second_log = run_pipeline(second, ticks=4)

    for district_id in sorted(first.districts):
        left = first.districts[district_id]
        right = second.districts[district_id]
        assert left.population == right.population
        assert left.scarcity == right.scarcity
        assert left.fear == right.fear
        assert left.trust == right.trust
        for resource in ResourceType:
            assert left.resources.amount_of(resource) == right.resources.amount_of(resource)

    assert [
        (event.tick, event.type, event.source_id, event.payload_as_dict()) for event in first_log
    ] == [
        (event.tick, event.type, event.source_id, event.payload_as_dict()) for event in second_log
    ]


def test_the_full_chain_consumes_no_randomness() -> None:
    """No system in the chain, Phase 6 included, may touch the generator."""
    world = build_full_scenario()
    before = world.rng.get_state()
    run_pipeline(world, ticks=5)
    assert world.rng.get_state() == before


def test_social_state_stays_bounded_and_finite_over_a_long_run() -> None:
    """Every district, every tick, inside the unit interval."""
    world = build_full_scenario()
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    loop = SimulationLoop(build_pipeline(), bus)

    for _ in range(20):
        loop.run(world, 1)
        for district_id in sorted(world.districts):
            district = world.districts[district_id]
            assert 0.0 <= district.fear <= 1.0
            assert 0.0 <= district.trust <= 1.0
            assert math.isfinite(district.fear)
            assert math.isfinite(district.trust)

    for event in log.query(event_type=EventType.SOCIAL_STABILITY_CHANGED):
        payload = event.payload_as_dict()
        for key in ("social_pressure", "new_fear", "new_trust", "new_social_stability"):
            value = float(payload[key])  # type: ignore[arg-type]
            assert 0.0 <= value <= 1.0
        stability = float(payload["new_social_stability"])  # type: ignore[arg-type]
        strain = float(payload["new_social_strain"])  # type: ignore[arg-type]
        assert abs((stability + strain) - 1.0) <= FLOAT_TOLERANCE


def test_social_state_persists_across_ticks_rather_than_being_recomputed() -> None:
    """Where a district ends up depends on the path it took to get there.

    Two identical districts under identical pressure but different social
    histories must remain different after a tick: the update moves from where
    each one already was.
    """
    calm = build_district(
        "calm", population=100, consumption_rate=1.0, housing_capacity=1000, fear=0.0, trust=1.0
    )
    frightened = build_district(
        "frightened",
        population=100,
        consumption_rate=1.0,
        housing_capacity=1000,
        fear=0.9,
        trust=0.1,
    )
    world = build_world([calm, frightened], law=build_law(), tick=0)
    run_pipeline(world)

    assert calm.scarcity == frightened.scarcity
    assert calm.fear < frightened.fear
    assert calm.trust > frightened.trust


def test_every_changed_district_reports_once_per_tick() -> None:
    """Two ticks over two moving districts is four social readings."""
    world = build_full_scenario()
    log = run_pipeline(world, ticks=2)
    readings = log.query(event_type=EventType.SOCIAL_STABILITY_CHANGED)

    assert len(readings) == 4
    assert [event.source_id for event in readings] == ["poor", "rich", "poor", "rich"]
    assert {event.tick for event in readings} == {1, 2}
