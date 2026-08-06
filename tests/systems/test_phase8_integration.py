"""Integration tests for the full Phase 8 pipeline.

Production -> Consumption -> ResourceFlow -> Migration -> Scarcity ->
SocialStability -> InstitutionalPressure -> BoundaryDecision.

Phase 8 sits at the very end, and what it does there is permanent. These tests
are about whether the wall is genuinely *earned*: that a shortage has to
propagate through scarcity, fear, trust, and institutional pressure over
several ticks before anything gets built, that a passing crisis never builds
anything, and that the wall changes the world only from the following tick
onward.
"""

from systems_builders import (
    EVEN_ALLOCATION,
    LAW_ID,
    build_district,
    build_law,
    build_wall,
    build_world,
)

from living_diorama.entities import ResourcePool, ResourceType
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.simulation import SimulationLoop
from living_diorama.systems import (
    BoundaryDecisionSystem,
    ConsumptionSystem,
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
near one half, which holds the institutional target around two thirds, so
stored pressure converges below the 0.75 default. Choosing a threshold the
modelled dynamics can actually reach is the point: the wall has to be reached
by simulation rather than by assignment. The threshold is configuration, and
the tests that pin the default's exact arithmetic use the default.
"""


def build_pipeline(*, build_threshold: float = CRISIS_THRESHOLD) -> list:
    """Build the Phase 8 pipeline in its required causal order."""
    return [
        ProductionSystem(allocation=EVEN_ALLOCATION),
        ConsumptionSystem(allocation=EVEN_ALLOCATION),
        ResourceFlowSystem(
            law_id=LAW_ID,
            consumption_allocation=EVEN_ALLOCATION,
            reserve_ticks=1.0,
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
    ]


def start_run(world, *, build_threshold: float = CRISIS_THRESHOLD):
    """Return a loop and its event log, ready to advance one tick at a time."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    return SimulationLoop(build_pipeline(build_threshold=build_threshold), bus), log


def build_famine_world(*, tick: int = 0):
    """Two neighbouring districts that both eat everything and have nothing spare."""
    return build_world(
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


def relieve(world, amount: float = 60.0) -> None:
    """Refill every district's stores, ending the shortage.

    A pool is immutable, so relief means handing the district a new one rather
    than topping up the old one in place.
    """
    for district in world.districts.values():
        district.resources = ResourcePool(stock={resource: amount for resource in ResourceType})


# --- Scenario A: the wall is earned over ticks, not scripted -----------------


def test_a_sustained_shortage_eventually_builds_a_wall() -> None:
    """The whole causal chain, running unaided from a resource deficit.

    Nothing here sets scarcity, fear, trust, or institutional pressure. The
    districts simply run out of food, and every downstream value is produced by
    the system that owns it. The wall appears only once that chain has pushed
    stored institutional pressure over the threshold.
    """
    world = build_famine_world()
    loop, log = start_run(world)
    north = world.districts["north"]

    history = []
    for _ in range(14):
        loop.run(world, 1)
        history.append((north.institutional_pressure, len(world.walls)))

    assert north.scarcity == 1.0, "the shortage must have produced scarcity"
    assert north.fear > 0.0, "scarcity must have produced fear"
    assert north.trust < 1.0, "scarcity must have damaged trust"

    pressures = [pressure for pressure, _ in history]
    assert pressures == sorted(pressures), "pressure must accumulate, not jump around"
    assert pressures[0] < CRISIS_THRESHOLD, "one bad tick must not be enough"

    built = [index for index, (_, walls) in enumerate(history) if walls == 1]
    assert built, "a sustained crisis must eventually build a wall"
    first_built = built[0]
    assert first_built > 0, "the wall must not appear on the very first tick"
    assert pressures[first_built - 1] < CRISIS_THRESHOLD
    assert pressures[first_built] >= CRISIS_THRESHOLD

    kinds = [event.type for event in log]
    for expected in (
        EventType.RESOURCE_CONSUMED,
        EventType.SCARCITY_CHANGED,
        EventType.SOCIAL_STABILITY_CHANGED,
        EventType.INSTITUTIONAL_PRESSURE_CHANGED,
        EventType.WALL_BUILT,
    ):
        assert expected in kinds, expected


def test_the_wall_is_built_exactly_once_and_stays() -> None:
    """Continued crisis after the build changes nothing further."""
    world = build_famine_world()
    loop, log = start_run(world)
    loop.run(world, 20)

    assert len(log.query(event_type=EventType.WALL_BUILT)) == 1
    assert len(world.walls) == 1
    wall = next(iter(world.walls.values()))
    assert wall.active is True
    assert wall.permanent is True
    assert wall.integrity == 1.0


# --- Scenario B: a passing crisis builds nothing -----------------------------


def test_a_temporary_shortage_never_builds_a_wall() -> None:
    """Social and institutional values react, but the pressure never gets there.

    This is the property the whole design rests on: because institutional
    pressure only ever moves a fraction of the way toward its target, a brief
    crisis lifts it a little and recovery lowers it again. Without that, every
    momentary shortage would leave a permanent scar.
    """
    world = build_famine_world()
    loop, log = start_run(world)
    north = world.districts["north"]

    loop.run(world, 2)
    peak_during_crisis = north.institutional_pressure
    assert peak_during_crisis > 0.0, "the crisis must have registered at all"
    assert north.fear > 0.0
    assert north.trust < 1.0
    assert peak_during_crisis < CRISIS_THRESHOLD

    highest = peak_during_crisis
    for _ in range(12):
        relieve(world)
        loop.run(world, 1)
        highest = max(highest, north.institutional_pressure)

    assert north.scarcity == 0.0, "relief must have ended the shortage"
    assert north.institutional_pressure < peak_during_crisis, "pressure must recede"
    assert highest < CRISIS_THRESHOLD
    assert len(world.walls) == 0
    assert len(log.query(event_type=EventType.WALL_BUILT)) == 0


# --- Scenario C: one side is enough ------------------------------------------


def test_one_strained_district_walls_off_a_calm_neighbour() -> None:
    """A comfortable neighbour cannot veto a desperate district's decision."""
    # Sharing is switched off, so the strained district gets no relief from its
    # neighbour and its own pressure keeps climbing while the neighbour's stays low.
    world = build_world(
        [
            build_district(
                "strained",
                population=10,
                consumption_rate=1.0,
                scarcity=1.0,
                fear=1.0,
                trust=0.0,
                institutional_pressure=0.80,
            ),
            build_district(
                "calm",
                population=10,
                food=90.0,
                materials=90.0,
                energy=90.0,
                scarcity=0.0,
                fear=0.0,
                trust=1.0,
                institutional_pressure=0.05,
            ),
        ],
        boundaries=[("bnd", "strained", "calm")],
        law=build_law(active=False, current_value=False),
        tick=0,
    )
    loop, log = start_run(world, build_threshold=0.75)
    loop.run(world, 1)

    assert len(world.walls) == 1
    built = log.query(event_type=EventType.WALL_BUILT)
    assert len(built) == 1

    payload = built[0].payload_as_dict()
    assert payload["decision_mode"] == "UNILATERAL_MAX"
    assert payload["active_endpoint_count"] == 2
    strained = world.districts["strained"]
    calm = world.districts["calm"]
    assert payload["district_a_institutional_pressure"] == strained.institutional_pressure
    assert payload["district_b_institutional_pressure"] == calm.institutional_pressure
    assert payload["boundary_pressure"] == strained.institutional_pressure
    assert payload["boundary_pressure"] > payload["build_threshold"]


# --- Scenario D: same-tick causal order --------------------------------------


def test_the_pressure_reading_precedes_the_wall_on_the_same_tick() -> None:
    """The wall is a consequence of this tick's pressure, and the log shows it."""
    world = build_famine_world()
    loop, log = start_run(world)
    loop.run(world, 20)

    kinds = [event.type for event in log]
    first_wall = kinds.index(EventType.WALL_BUILT)
    build_tick = log.events()[first_wall].tick

    same_tick = [event.type for event in log if event.tick == build_tick]
    assert EventType.INSTITUTIONAL_PRESSURE_CHANGED in same_tick
    assert same_tick.index(EventType.INSTITUTIONAL_PRESSURE_CHANGED) < same_tick.index(
        EventType.WALL_BUILT
    )


# --- Scenario E: the wall takes effect from the next tick --------------------


def build_donor_receiver_world(*, receiver_pressure: float):
    """A well-stocked district beside an empty one, sharing a boundary."""
    return build_world(
        [
            build_district(
                "donor",
                population=10,
                consumption_rate=1.0,
                food=200.0,
                materials=200.0,
                energy=200.0,
                scarcity=0.0,
                fear=0.0,
                trust=1.0,
                institutional_pressure=0.0,
            ),
            build_district(
                "receiver",
                population=10,
                consumption_rate=1.0,
                scarcity=1.0,
                fear=1.0,
                trust=0.0,
                institutional_pressure=receiver_pressure,
            ),
        ],
        boundaries=[("bnd", "donor", "receiver")],
        law=build_law(),
        tick=0,
    )


def test_the_build_tick_does_not_undo_its_own_transfers() -> None:
    """Flow ran before the decision, and the wall does not reach back for it."""
    world = build_donor_receiver_world(receiver_pressure=0.95)
    loop, log = start_run(world, build_threshold=0.75)
    receiver = world.districts["receiver"]

    loop.run(world, 1)

    assert len(world.walls) == 1, "the wall must have been built on this tick"
    assert log.query(event_type=EventType.RESOURCE_TRANSFERRED), (
        "the transfer must have happened before the decision"
    )
    assert receiver.resources.amount_of(ResourceType.FOOD) > 0.0, (
        "resources that arrived this tick must not be taken back"
    )


def test_the_wall_blocks_the_boundary_from_the_following_tick() -> None:
    """From the next tick the wall is standing, and nothing crosses it."""
    world = build_donor_receiver_world(receiver_pressure=0.95)
    loop, log = start_run(world, build_threshold=0.75)
    receiver = world.districts["receiver"]

    loop.run(world, 1)
    transfers_after_first = len(log.query(event_type=EventType.RESOURCE_TRANSFERRED))
    assert transfers_after_first > 0

    received_before = receiver.resources.amount_of(ResourceType.FOOD)
    loop.run(world, 1)

    assert len(log.query(event_type=EventType.RESOURCE_TRANSFERRED)) == transfers_after_first, (
        "the standing wall must stop further transfers across the boundary"
    )
    assert receiver.resources.amount_of(ResourceType.FOOD) <= received_before


def test_migration_also_respects_the_new_wall() -> None:
    """The barrier applies to people as well as goods, from the next tick on."""
    world = build_donor_receiver_world(receiver_pressure=0.95)
    loop, log = start_run(world, build_threshold=0.75)

    loop.run(world, 1)
    assert len(world.walls) == 1
    migrations_before = len(log.query(event_type=EventType.POPULATION_MIGRATED))

    loop.run(world, 3)

    assert len(log.query(event_type=EventType.POPULATION_MIGRATED)) == migrations_before


# --- Scenario F: an existing wall is left alone ------------------------------


def test_an_existing_wall_is_neither_duplicated_nor_modified() -> None:
    """A boundary that already carries a wall is untouched by the full pipeline."""
    world = build_famine_world()
    world.add_wall(build_wall("w_existing", "bnd", active=False, permanent=False))
    before = (
        world.walls["w_existing"].active,
        world.walls["w_existing"].permanent,
        world.walls["w_existing"].integrity,
        world.walls["w_existing"].built_tick,
        world.walls["w_existing"].dependency_score,
    )

    loop, log = start_run(world)
    loop.run(world, 20)

    assert set(world.walls) == {"w_existing"}
    assert (
        world.walls["w_existing"].active,
        world.walls["w_existing"].permanent,
        world.walls["w_existing"].integrity,
        world.walls["w_existing"].built_tick,
        world.walls["w_existing"].dependency_score,
    ) == before
    assert world.boundaries["bnd"].wall_id == "w_existing"
    assert len(log.query(event_type=EventType.WALL_BUILT)) == 0
    assert len(log.query(event_type=EventType.WALL_CHANGED)) == 0


# --- Scenario G: the whole chain is deterministic ----------------------------


def snapshot(world) -> dict:
    """Capture everything the pipeline is allowed to change."""
    return {
        "tick": world.tick,
        "districts": {
            district_id: (
                world.districts[district_id].population,
                {
                    resource.value: world.districts[district_id].resources.amount_of(resource)
                    for resource in ResourceType
                },
                world.districts[district_id].scarcity,
                world.districts[district_id].fear,
                world.districts[district_id].trust,
                world.districts[district_id].institutional_pressure,
            )
            for district_id in sorted(world.districts)
        },
        "walls": {
            wall_id: (
                world.walls[wall_id].boundary_id,
                world.walls[wall_id].built_tick,
                world.walls[wall_id].active,
                world.walls[wall_id].permanent,
                world.walls[wall_id].integrity,
            )
            for wall_id in sorted(world.walls)
        },
        "boundaries": {
            boundary_id: world.boundaries[boundary_id].wall_id
            for boundary_id in sorted(world.boundaries)
        },
        "rng": world.rng.get_state(),
    }


def test_two_equivalent_worlds_end_identically() -> None:
    """Same inputs, same twenty ticks, same world down to the RNG state."""
    results = []
    for _ in range(2):
        world = build_famine_world()
        loop, log = start_run(world)
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


def test_registration_order_does_not_change_the_full_chain() -> None:
    """Which district was registered first is not part of the world's meaning."""

    def run(reverse: bool):
        """Run the famine world with registration order optionally reversed."""
        world = build_famine_world()
        if reverse:
            world = build_world(
                [world.districts["south"], world.districts["north"]],
                boundaries=[("bnd", "north", "south")],
                law=build_law(),
                tick=0,
            )
        loop, _ = start_run(world)
        loop.run(world, 20)
        return snapshot(world)

    assert run(False) == run(True)


# --- 38. Sustained pressure, using the real institutional system --------------


def build_pinned_crisis_world(*, pressure: float = 0.0):
    """Two districts whose institutional target stays pinned at 1.0.

    Scarcity, fear, and trust are held at their extremes and no system in this
    reduced pipeline rewrites them, so the target stays at 1.0 and the only
    thing that moves is the stored pressure itself. That isolates exactly the
    property under test: how long accumulation takes.
    """
    return build_world(
        [
            build_district(
                name,
                population=10,
                scarcity=1.0,
                fear=1.0,
                trust=0.0,
                institutional_pressure=pressure,
            )
            for name in ("east", "west")
        ],
        boundaries=[("bnd", "east", "west")],
        law=build_law(),
        tick=0,
    )


def run_pressure_only(world, ticks: int, *, build_threshold: float = 0.75):
    """Run only the institutional and boundary layers, one tick at a time."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    loop = SimulationLoop(
        [
            InstitutionalPressureSystem(response_rate=0.20),
            BoundaryDecisionSystem(build_threshold=build_threshold),
        ],
        bus,
    )
    history = []
    for _ in range(ticks):
        loop.run(world, 1)
        history.append((world.districts["east"].institutional_pressure, len(world.walls)))
    return history, log


def test_pressure_accumulates_gradually_before_any_wall_appears() -> None:
    """A target of 1.0 still takes several ticks to cross a threshold of 0.75."""
    world = build_pinned_crisis_world()
    history, _ = run_pressure_only(world, 9)

    pressures = [pressure for pressure, _ in history]
    assert pressures[0] < 0.75, "the first high-target tick must not build"
    assert pressures == sorted(pressures)
    assert pressures[-1] >= 0.75, "sustained pressure must eventually cross"


def test_the_wall_appears_on_the_first_tick_that_crosses_the_threshold() -> None:
    """Not a tick early, not a tick late, and only once."""
    world = build_pinned_crisis_world()
    history, log = run_pressure_only(world, 9)

    built_ticks = [index for index, (_, walls) in enumerate(history) if walls == 1]
    assert built_ticks, "the wall must be built"
    first = built_ticks[0]

    for index, (pressure, walls) in enumerate(history):
        crossed = pressure >= 0.75
        assert (walls == 1) is (index >= first)
        if index < first:
            assert not crossed, "no tick before the build may have crossed"
    assert history[first][0] >= 0.75
    assert len(log.query(event_type=EventType.WALL_BUILT)) == 1


def test_no_streak_counter_is_needed_because_pressure_is_already_the_memory() -> None:
    """A world starting above the threshold builds at once, and that is correct.

    The stored value already represents pressure accumulated before this update,
    so requiring a fresh streak would be double-counting the same history.
    """
    world = build_pinned_crisis_world(pressure=0.9)
    history, log = run_pressure_only(world, 1)

    assert history[0][1] == 1
    assert len(log.query(event_type=EventType.WALL_BUILT)) == 1


# --- 39. A short spike must leave no scar ------------------------------------


def test_a_single_high_target_tick_followed_by_recovery_builds_nothing() -> None:
    """The negative case, proven through real pressure progression.

    One severe tick, then genuine recovery. Pressure rises partway, turns
    around, and decays. Nothing is ever built, because a wall requires the
    crisis to persist rather than merely to have happened.
    """
    world = build_pinned_crisis_world()
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    loop = SimulationLoop(
        [
            InstitutionalPressureSystem(response_rate=0.20),
            BoundaryDecisionSystem(build_threshold=0.75),
        ],
        bus,
    )

    loop.run(world, 1)
    spike = world.districts["east"].institutional_pressure
    assert 0.0 < spike < 0.75, "one tick must lift pressure partway only"

    for district in world.districts.values():
        district.scarcity = 0.0
        district.fear = 0.0
        district.trust = 1.0

    trail = []
    for _ in range(10):
        loop.run(world, 1)
        trail.append(world.districts["east"].institutional_pressure)

    assert max(trail) < spike, "recovery must lower pressure, not raise it"
    assert trail == sorted(trail, reverse=True), "the decay must be monotonic"
    assert max([spike, *trail]) < 0.75
    assert len(world.walls) == 0
    assert len(log.query(event_type=EventType.WALL_BUILT)) == 0
