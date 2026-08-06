"""Integration tests for the full Phase 9 pipeline.

Production -> Consumption -> ResourceFlow -> Migration -> Scarcity ->
SocialStability -> InstitutionalPressure -> BoundaryDecision ->
InfrastructureAdaptation.

Phase 9 sits at the very end and is where the show's premise finally closes:
the wall stops being a barrier someone put up and becomes something the world
has organized itself around. These tests are about whether that reliance is
genuinely earned tick by tick, starts the moment the wall goes up, and survives
the crisis that caused it.
"""

from systems_builders import (
    EVEN_ALLOCATION,
    LAW_ID,
    build_district,
    build_law,
    build_wall,
    build_world,
)

from living_diorama.entities import (
    Infrastructure,
    InfrastructureType,
    ResourcePool,
    ResourceType,
)
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.simulation import SimulationLoop
from living_diorama.systems import (
    BoundaryDecisionSystem,
    ConsumptionSystem,
    InfrastructureAdaptationSystem,
    InstitutionalPressureSystem,
    MigrationSystem,
    ProductionSystem,
    ResourceFlowSystem,
    ScarcitySystem,
    SocialStabilitySystem,
)

CRISIS_THRESHOLD = 0.50
"""The build threshold used for full-pipeline crisis scenarios.

Under a sustained total shortage the social layer settles with fear and trust
near one half, holding the institutional target around two thirds, so stored
pressure converges below the 0.75 default. Choosing a threshold the modelled
dynamics can actually reach is the point: the wall has to be reached by
simulation rather than by assignment. Scenarios that only need a wall to exist
use the default and supply the pressure directly.
"""


def make_infrastructure(
    infrastructure_id: str,
    boundary_id: str,
    *,
    kind: InfrastructureType = InfrastructureType.TRANSIT_ROUTE,
    dependency: float = 0.0,
) -> Infrastructure:
    """Build infrastructure of a chosen kind attached to a boundary."""
    return Infrastructure(
        id=infrastructure_id,
        created_tick=0,
        boundary_id=boundary_id,
        infrastructure_type=kind,
        capacity=1.0,
        dependency_score=dependency,
        degraded=False,
    )


def build_full_pipeline(*, build_threshold: float = CRISIS_THRESHOLD) -> list:
    """Build the whole implemented chain in its required causal order."""
    return [
        ProductionSystem(allocation=EVEN_ALLOCATION),
        ConsumptionSystem(allocation=EVEN_ALLOCATION),
        ResourceFlowSystem(
            law_id=LAW_ID, consumption_allocation=EVEN_ALLOCATION, reserve_ticks=1.0
        ),
        MigrationSystem(
            law_id=LAW_ID,
            consumption_allocation=EVEN_ALLOCATION,
            migration_rate=0.2,
            min_pressure_gap=0.05,
            partial_isolation_factor=0.5,
        ),
        ScarcitySystem(consumption_allocation=EVEN_ALLOCATION),
        SocialStabilitySystem(response_rate=0.25),
        InstitutionalPressureSystem(response_rate=0.20),
        BoundaryDecisionSystem(build_threshold=build_threshold),
        InfrastructureAdaptationSystem(),
    ]


def build_boundary_pipeline(*, build_threshold: float = 0.75) -> list:
    """Build only the two phases under test, for scenarios that isolate them."""
    return [
        BoundaryDecisionSystem(build_threshold=build_threshold),
        InfrastructureAdaptationSystem(),
    ]


def start(world, systems):
    """Return a loop and its event log, ready to advance one tick at a time."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    return SimulationLoop(systems, bus), log


def pressured_world(
    *,
    pressure: float = 0.9,
    boundaries=(("bnd", "a", "b"),),
    districts=("a", "b"),
    tick: int = 0,
):
    """Build districts joined by boundaries, with a chosen institutional pressure."""
    return build_world(
        [
            build_district(name, population=100, institutional_pressure=pressure)
            for name in districts
        ],
        boundaries=list(boundaries),
        law=build_law(),
        tick=tick,
    )


# --- Scenario A: an existing active wall ------------------------------------


def test_an_existing_active_wall_drives_adaptation_and_aggregation() -> None:
    """The baseline case: a standing wall, and the world reorganizing around it."""
    world = pressured_world(pressure=0.0)
    world.add_wall(build_wall("w", "bnd", active=True))
    world.add_infrastructure(
        make_infrastructure("transit", "bnd", kind=InfrastructureType.TRANSIT_ROUTE)
    )
    world.add_infrastructure(
        make_infrastructure("supply", "bnd", kind=InfrastructureType.RESOURCE_ROUTE)
    )

    loop, log = start(world, build_boundary_pipeline())
    loop.run(world, 1)

    assert world.infrastructure["transit"].dependency_score > 0.0
    assert world.infrastructure["supply"].dependency_score > 0.0
    wall = world.walls["w"]
    assert wall.transport_dependency == world.infrastructure["transit"].dependency_score
    assert wall.resource_dependency == world.infrastructure["supply"].dependency_score
    assert wall.dependency_score == max(wall.transport_dependency, wall.resource_dependency)

    assert len(log.query(event_type=EventType.INFRASTRUCTURE_ADAPTED)) == 2
    assert len(log.query(event_type=EventType.WALL_CHANGED)) == 1
    assert len(log.query(event_type=EventType.WALL_BUILT)) == 0


# --- Scenario B: a wall built this very tick --------------------------------


def test_a_wall_built_this_tick_starts_earning_dependency_immediately() -> None:
    """No waiting period: the tick that raises a wall is the tick reliance begins.

    Phase 9 runs after the decision, so the wall is already standing when it
    looks. Requiring the wall to have existed at T-1 would be a delay nobody
    asked for.
    """
    world = pressured_world(pressure=0.9)
    world.add_infrastructure(make_infrastructure("route", "bnd"))

    loop, log = start(world, build_boundary_pipeline())
    loop.run(world, 1)

    assert set(world.walls) == {"wall_bnd"}
    assert world.infrastructure["route"].dependency_score == 0.10, "exactly one step"
    assert world.walls["wall_bnd"].dependency_score == 0.10
    assert world.walls["wall_bnd"].transport_dependency == 0.10


def test_the_same_tick_event_order_is_built_then_adapted_then_changed() -> None:
    """The causal story reads correctly straight off the recorded history."""
    world = pressured_world(pressure=0.9)
    world.add_infrastructure(make_infrastructure("route", "bnd"))

    loop, log = start(world, build_boundary_pipeline())
    loop.run(world, 1)

    kinds = [event.type for event in log]
    assert kinds == [
        EventType.WALL_BUILT,
        EventType.INFRASTRUCTURE_ADAPTED,
        EventType.WALL_CHANGED,
    ]
    assert len({event.tick for event in log}) == 1, "all on the same tick"


# --- Scenario C: a boundary that does not qualify ---------------------------


def test_a_boundary_below_the_threshold_produces_no_wall_and_no_adaptation() -> None:
    """No wall means nothing to organize around, so nothing accumulates."""
    world = pressured_world(pressure=0.10)
    world.add_infrastructure(make_infrastructure("route", "bnd", dependency=0.3))

    loop, log = start(world, build_boundary_pipeline())
    loop.run(world, 3)

    assert len(world.walls) == 0
    assert world.infrastructure["route"].dependency_score == 0.3
    assert len(log) == 0


# --- Scenario D: parallel boundaries ----------------------------------------


def test_only_infrastructure_on_the_walled_boundary_adapts() -> None:
    """Two boundaries joining the same pair are two separate places to depend on."""
    world = build_world(
        [
            build_district("a", population=100, institutional_pressure=0.0),
            build_district("b", population=100, institutional_pressure=0.0),
        ],
        boundaries=[("walled", "a", "b"), ("open", "a", "b")],
        law=build_law(),
        tick=0,
    )
    world.add_wall(build_wall("w", "walled", active=True))
    world.add_infrastructure(make_infrastructure("i_walled", "walled"))
    world.add_infrastructure(make_infrastructure("i_open", "open", dependency=0.4))

    loop, log = start(world, build_boundary_pipeline())
    loop.run(world, 1)

    assert world.infrastructure["i_walled"].dependency_score == 0.10
    assert world.infrastructure["i_open"].dependency_score == 0.4
    assert [
        event.source_id for event in log.query(event_type=EventType.INFRASTRUCTURE_ADAPTED)
    ] == ["i_walled"]


# --- Scenario E: several new walls in one tick ------------------------------


def test_multiple_new_walls_adapt_in_deterministic_order() -> None:
    """Both systems traverse by identifier, so the whole tick is reproducible."""
    world = pressured_world(
        pressure=0.9,
        districts=("a", "b", "c"),
        boundaries=(("b_aaa", "a", "b"), ("b_zzz", "b", "c")),
    )
    world.add_infrastructure(make_infrastructure("i_aaa", "b_aaa"))
    world.add_infrastructure(make_infrastructure("i_zzz", "b_zzz"))

    loop, log = start(world, build_boundary_pipeline())
    loop.run(world, 1)

    assert sorted(world.walls) == ["wall_b_aaa", "wall_b_zzz"]
    assert [event.source_id for event in log.query(event_type=EventType.WALL_BUILT)] == [
        "wall_b_aaa",
        "wall_b_zzz",
    ]
    assert [
        event.source_id for event in log.query(event_type=EventType.INFRASTRUCTURE_ADAPTED)
    ] == ["i_aaa", "i_zzz"]
    assert [event.source_id for event in log.query(event_type=EventType.WALL_CHANGED)] == [
        "wall_b_aaa",
        "wall_b_zzz",
    ]

    kinds = [event.type for event in log]
    assert max(i for i, k in enumerate(kinds) if k is EventType.WALL_BUILT) < kinds.index(
        EventType.INFRASTRUCTURE_ADAPTED
    )
    assert max(
        i for i, k in enumerate(kinds) if k is EventType.INFRASTRUCTURE_ADAPTED
    ) < kinds.index(EventType.WALL_CHANGED)


# --- Scenario F: an inactive wall -------------------------------------------


def test_an_inactive_wall_produces_no_adaptation_through_the_pipeline() -> None:
    """Standing is what matters, and this one is not."""
    world = pressured_world(pressure=0.0)
    wall = build_wall("w", "bnd", active=False)
    wall.dependency_score = 0.35
    wall.transport_dependency = 0.35
    world.add_wall(wall)
    world.add_infrastructure(make_infrastructure("route", "bnd", dependency=0.6))

    loop, log = start(world, build_boundary_pipeline())
    loop.run(world, 5)

    assert world.infrastructure["route"].dependency_score == 0.6
    assert world.walls["w"].dependency_score == 0.35
    assert world.walls["w"].transport_dependency == 0.35
    assert len(log) == 0


# --- Scenario G: determinism across the chain -------------------------------


def snapshot(world) -> dict:
    """Capture everything the pipeline is allowed to change."""
    return {
        "tick": world.tick,
        "districts": {
            key: (
                world.districts[key].population,
                {r.value: world.districts[key].resources.amount_of(r) for r in ResourceType},
                world.districts[key].scarcity,
                world.districts[key].fear,
                world.districts[key].trust,
                world.districts[key].institutional_pressure,
            )
            for key in sorted(world.districts)
        },
        "walls": {
            key: (
                world.walls[key].boundary_id,
                world.walls[key].built_tick,
                world.walls[key].active,
                world.walls[key].permanent,
                world.walls[key].integrity,
                world.walls[key].dependency_score,
                world.walls[key].transport_dependency,
                world.walls[key].resource_dependency,
            )
            for key in sorted(world.walls)
        },
        "infrastructure": {
            key: (
                world.infrastructure[key].boundary_id,
                world.infrastructure[key].dependency_score,
                world.infrastructure[key].capacity,
                world.infrastructure[key].degraded,
            )
            for key in sorted(world.infrastructure)
        },
        "boundaries": {key: world.boundaries[key].wall_id for key in sorted(world.boundaries)},
        "rng": world.rng.get_state(),
    }


def build_famine_world(*, tick: int = 0):
    """Two neighbours that both eat everything, joined by a supply route."""
    world = build_world(
        [
            build_district(
                name,
                population=10,
                consumption_rate=1.0,
                food=5.0,
                materials=3.0,
                energy=2.0,
                housing_capacity=1000,
                scarcity=0.0,
                fear=0.0,
                trust=1.0,
                institutional_pressure=0.0,
            )
            for name in ("north", "south")
        ],
        boundaries=[("bnd", "north", "south")],
        law=build_law(),
        tick=tick,
    )
    world.add_infrastructure(
        make_infrastructure("supply", "bnd", kind=InfrastructureType.RESOURCE_ROUTE)
    )
    world.add_infrastructure(
        make_infrastructure("transit", "bnd", kind=InfrastructureType.TRANSIT_ROUTE)
    )
    return world


def test_two_equivalent_worlds_end_identically() -> None:
    """Same inputs, same twenty ticks, same world down to the RNG state."""
    results = []
    for _ in range(2):
        world = build_famine_world()
        loop, log = start(world, build_full_pipeline())
        loop.run(world, 20)
        results.append(
            (
                snapshot(world),
                [
                    (event.tick, event.type.value, event.source_id, event.payload_as_dict())
                    for event in log
                ],
            )
        )

    assert results[0][0] == results[1][0]
    assert results[0][1] == results[1][1]
    assert results[0][0]["walls"], "the run must actually have built something to compare"
    assert any(state[5] > 0.0 for state in results[0][0]["walls"].values()), (
        "and must have accumulated dependency"
    )


# --- 41. The full causal chain ----------------------------------------------


def test_a_sustained_crisis_builds_a_wall_the_world_then_depends_on() -> None:
    """The whole premise, running unaided from a resource deficit.

    Nothing here assigns scarcity, fear, trust, institutional pressure, a wall,
    or a dependency score. The districts simply run out of food and every
    downstream value is produced by the system that owns it.
    """
    world = build_famine_world()
    loop, log = start(world, build_full_pipeline())
    north = world.districts["north"]

    history = []
    for _ in range(16):
        loop.run(world, 1)
        history.append(
            (
                north.institutional_pressure,
                len(world.walls),
                world.infrastructure["supply"].dependency_score,
            )
        )

    assert north.scarcity == 1.0, "the shortage must have produced scarcity"
    assert north.fear > 0.0 and north.trust < 1.0, "which must have damaged the social state"

    pressures = [pressure for pressure, _, _ in history]
    assert pressures == sorted(pressures), "pressure must accumulate, not jump"

    built = [index for index, (_, walls, _) in enumerate(history) if walls == 1]
    assert built, "a sustained crisis must eventually build a wall"
    first_built = built[0]
    assert first_built > 0, "the wall must not appear on the very first tick"
    assert pressures[first_built - 1] < CRISIS_THRESHOLD
    assert pressures[first_built] >= CRISIS_THRESHOLD

    assert history[first_built - 1][2] == 0.0, "no dependency before the wall existed"
    assert history[first_built][2] > 0.0, "dependency begins on the build tick"

    dependencies = [dependency for _, _, dependency in history[first_built:]]
    assert dependencies == sorted(dependencies), "reliance only ever grows"

    wall = next(iter(world.walls.values()))
    assert wall.resource_dependency == world.infrastructure["supply"].dependency_score
    assert wall.transport_dependency == world.infrastructure["transit"].dependency_score
    assert wall.dependency_score == max(wall.resource_dependency, wall.transport_dependency)

    kinds = [event.type for event in log]
    for expected in (
        EventType.RESOURCE_CONSUMED,
        EventType.SCARCITY_CHANGED,
        EventType.SOCIAL_STABILITY_CHANGED,
        EventType.INSTITUTIONAL_PRESSURE_CHANGED,
        EventType.WALL_BUILT,
        EventType.INFRASTRUCTURE_ADAPTED,
        EventType.WALL_CHANGED,
    ):
        assert expected in kinds, expected


def test_the_wall_and_its_dependency_survive_the_crisis_ending() -> None:
    """Relieve the shortage and the consequence stays; that is the whole promise.

    Institutional pressure recedes, scarcity returns to zero, and the wall is
    still standing with everything the world built around it intact.
    """
    world = build_famine_world()
    loop, log = start(world, build_full_pipeline())
    north = world.districts["north"]

    for _ in range(14):
        loop.run(world, 1)
    assert len(world.walls) == 1
    crisis_pressure = north.institutional_pressure
    dependency_at_relief = world.infrastructure["supply"].dependency_score
    assert dependency_at_relief > 0.0

    for _ in range(8):
        for district in world.districts.values():
            district.resources = ResourcePool(stock={r: 80.0 for r in ResourceType})
        loop.run(world, 1)

    assert north.scarcity == 0.0, "the shortage is over"
    assert north.institutional_pressure < crisis_pressure, "pressure recedes"

    assert len(world.walls) == 1, "the wall remains"
    assert world.infrastructure["supply"].dependency_score >= dependency_at_relief, (
        "no dependency is ever handed back"
    )
    assert next(iter(world.walls.values())).dependency_score > 0.0


def test_relief_never_reduces_any_dependency_score() -> None:
    """Checked every tick rather than only at the end."""
    world = build_famine_world()
    loop, _ = start(world, build_full_pipeline())

    previous = {"supply": 0.0, "transit": 0.0}
    previous_wall = 0.0
    for tick in range(24):
        if tick >= 14:
            for district in world.districts.values():
                district.resources = ResourcePool(stock={r: 80.0 for r in ResourceType})
        loop.run(world, 1)

        for key in previous:
            current = world.infrastructure[key].dependency_score
            assert current >= previous[key], f"{key} decayed on tick {tick + 1}"
            previous[key] = current
        if world.walls:
            wall_score = next(iter(world.walls.values())).dependency_score
            assert wall_score >= previous_wall
            previous_wall = wall_score


def test_the_full_chain_consumes_no_randomness() -> None:
    """No system in the chain, Phase 9 included, may touch the generator."""
    world = build_famine_world()
    before = world.rng.get_state()
    loop, _ = start(world, build_full_pipeline())
    loop.run(world, 20)
    assert world.rng.get_state() == before


def test_phase_nine_does_not_disturb_the_upstream_chain() -> None:
    """Adding adaptation must not change any earlier system's outcome.

    Running the same world with and without Phase 9 has to leave resources,
    population, scarcity, fear, trust, pressure, and the walls themselves
    identical -- adaptation observes the world, it does not steer it.
    """

    def run(with_adaptation: bool):
        """Run the chain with or without the adaptation stage."""
        world = build_famine_world()
        systems = build_full_pipeline()
        if not with_adaptation:
            systems = systems[:-1]
        loop, _ = start(world, systems)
        loop.run(world, 20)
        state = snapshot(world)
        del state["infrastructure"]
        state["walls"] = {key: value[:5] for key, value in state["walls"].items()}
        return state

    assert run(True) == run(False)


# --- A mixed world through the real two-phase pipeline ----------------------


def test_an_unattached_wall_is_untouched_while_a_neighbour_adapts() -> None:
    """Through the real pipeline: adaptation must not spread to an unattached wall.

    Candidate V1 aggregated every active wall, so a wall carrying divergent but
    perfectly valid historical scores had its overall figure pulled up to its
    highest category even with nothing attached to it. Here one boundary
    genuinely adapts while the other has nothing to adapt, and the two must not
    influence one another.
    """
    world = build_world(
        [
            build_district(name, population=100, institutional_pressure=0.0)
            for name in ("a", "b", "c")
        ],
        boundaries=[("b_busy", "a", "b"), ("b_lonely", "b", "c")],
        law=build_law(),
        tick=0,
    )
    lonely = build_wall("w_lonely", "b_lonely", active=True)
    lonely.dependency_score = 0.10
    lonely.transport_dependency = 0.80
    lonely.resource_dependency = 0.20
    world.add_wall(lonely)
    world.add_wall(build_wall("w_busy", "b_busy", active=True))
    world.add_infrastructure(
        make_infrastructure("i_busy", "b_busy", kind=InfrastructureType.TRANSIT_ROUTE)
    )

    loop, log = start(world, build_boundary_pipeline())
    loop.run(world, 6)

    assert world.infrastructure["i_busy"].dependency_score > 0.0
    assert world.walls["w_busy"].transport_dependency > 0.0

    assert (
        world.walls["w_lonely"].dependency_score,
        world.walls["w_lonely"].transport_dependency,
        world.walls["w_lonely"].resource_dependency,
    ) == (0.10, 0.80, 0.20)

    wall_events = log.query(event_type=EventType.WALL_CHANGED)
    assert {event.source_id for event in wall_events} == {"w_busy"}
    assert all(event.source_id != "w_lonely" for event in log)
