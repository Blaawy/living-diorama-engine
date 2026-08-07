"""Shared builders for the Phase 10 persistence tests.

These are plain functions rather than fixtures so that every test constructs
its own world explicitly. Persistence tests care about exact stored values, and
a shared mutable fixture would make it easy for one test to change what another
one is asserting about.
"""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from living_diorama.entities import (
    Boundary,
    District,
    Infrastructure,
    InfrastructureType,
    IsolationState,
    Law,
    ResourcePool,
    ResourceType,
    Wall,
)
from living_diorama.events import Event, EventLog, EventType
from living_diorama.memory import MemorySignificance, WorldMemory
from living_diorama.simulation.rng import DeterministicRNG
from living_diorama.simulation.world import World


@contextmanager
def temporary_save_root() -> Iterator[Path]:
    """Yield a fresh empty directory that is removed afterwards."""
    with tempfile.TemporaryDirectory() as directory:
        yield Path(directory)


def consumed_rng(seed: int = 20260806, draws: int = 9) -> DeterministicRNG:
    """Return a generator that has already been used.

    Saving an untouched generator would prove only that a seed round-trips. The
    interesting case is a generator partway through its sequence, because that
    is what every episode after the first actually holds.
    """
    rng = DeterministicRNG(seed)
    for _ in range(draws):
        rng.random()
    return rng


def build_district(
    district_id: str,
    *,
    population: int = 100,
    food: float = 0.0,
    materials: float = 0.0,
    energy: float = 0.0,
    production_rate: float = 0.0,
    consumption_rate: float = 0.0,
    scarcity: float = 0.0,
    fear: float = 0.0,
    trust: float = 1.0,
    institutional_pressure: float = 0.0,
    housing_capacity: int = 1000,
    isolation_state: IsolationState = IsolationState.OPEN,
    created_tick: int = 0,
) -> District:
    """Build a district with fully specified stored state."""
    return District(
        id=district_id,
        created_tick=created_tick,
        population=population,
        resources=ResourcePool(
            stock={
                ResourceType.FOOD: food,
                ResourceType.MATERIALS: materials,
                ResourceType.ENERGY: energy,
            }
        ),
        production_rate=production_rate,
        consumption_rate=consumption_rate,
        scarcity=scarcity,
        fear=fear,
        trust=trust,
        institutional_pressure=institutional_pressure,
        housing_capacity=housing_capacity,
        isolation_state=isolation_state,
    )


def build_wall(
    wall_id: str,
    boundary_id: str,
    *,
    active: bool = True,
    permanent: bool = True,
    integrity: float = 1.0,
    dependency_score: float = 0.0,
    transport_dependency: float = 0.0,
    resource_dependency: float = 0.0,
    created_tick: int = 0,
    built_tick: int = 0,
) -> Wall:
    """Build a wall with fully specified stored state."""
    return Wall(
        id=wall_id,
        created_tick=created_tick,
        boundary_id=boundary_id,
        built_tick=built_tick,
        integrity=integrity,
        active=active,
        permanent=permanent,
        dependency_score=dependency_score,
        transport_dependency=transport_dependency,
        resource_dependency=resource_dependency,
    )


def build_infrastructure(
    infrastructure_id: str,
    boundary_id: str,
    *,
    kind: InfrastructureType = InfrastructureType.TRANSIT_ROUTE,
    capacity: float = 100.0,
    dependency_score: float = 0.0,
    degraded: bool = False,
    created_tick: int = 0,
) -> Infrastructure:
    """Build an infrastructure entity with fully specified stored state."""
    return Infrastructure(
        id=infrastructure_id,
        created_tick=created_tick,
        boundary_id=boundary_id,
        infrastructure_type=kind,
        capacity=capacity,
        dependency_score=dependency_score,
        degraded=degraded,
    )


def build_law(
    law_id: str,
    *,
    name: str = "Some Law",
    active: bool = True,
    previous_value: object = None,
    current_value: object = True,
    changed_episode: int = 0,
    restored_tick: int | None = None,
    created_tick: int = 0,
) -> Law:
    """Build a law with fully specified stored state."""
    return Law(
        id=law_id,
        created_tick=created_tick,
        name=name,
        active=active,
        previous_value=previous_value,  # type: ignore[arg-type]
        current_value=current_value,  # type: ignore[arg-type]
        changed_episode=changed_episode,
        restored_tick=restored_tick,
    )


def minimal_world(*, episode: int = 0, tick: int = 0) -> World:
    """Build the smallest world worth saving: two districts and a boundary."""
    world = World(rng=consumed_rng(), tick=tick, episode=episode)
    world.add_district(build_district("district_a"))
    world.add_district(build_district("district_b"))
    world.add_boundary(
        Boundary(
            id="boundary_ab",
            created_tick=0,
            district_a_id="district_a",
            district_b_id="district_b",
        )
    )
    return world


def rich_world(*, episode: int = 0, tick: int = 20) -> World:
    """Build a world exercising every shape Phase 10 has to carry.

    Deliberately awkward: an empty district, a boundary with no wall, an
    inactive permanent wall, every infrastructure kind including a degraded and
    a zero-capacity one, laws holding four different scalar types, and a
    generator already partway through its sequence.
    """
    world = World(rng=consumed_rng(), tick=tick, episode=episode)

    world.add_district(
        build_district(
            "district_a",
            population=120,
            food=5.5,
            materials=2.0,
            energy=0.25,
            production_rate=3.0,
            consumption_rate=1.5,
            scarcity=0.25,
            fear=0.4,
            trust=0.6,
            institutional_pressure=0.8,
            housing_capacity=300,
            isolation_state=IsolationState.PARTIAL,
        )
    )
    world.add_district(
        build_district(
            "district_b",
            population=0,
            trust=1.0,
            scarcity=1.0,
            housing_capacity=0,
            isolation_state=IsolationState.ISOLATED,
        )
    )
    world.add_district(build_district("district_c", population=7, created_tick=3))

    world.add_boundary(
        Boundary(
            id="boundary_ab",
            created_tick=0,
            district_a_id="district_a",
            district_b_id="district_b",
        )
    )
    world.add_boundary(
        Boundary(
            id="boundary_bc",
            created_tick=1,
            district_a_id="district_b",
            district_b_id="district_c",
        )
    )
    world.add_boundary(
        Boundary(
            id="boundary_open",
            created_tick=2,
            district_a_id="district_c",
            district_b_id="district_a",
        )
    )

    world.add_law(build_law("resource_sharing", name="Resource Sharing", current_value=True))
    world.add_law(
        build_law(
            "tariff",
            name="Tariff",
            active=False,
            previous_value=1,
            current_value=2.5,
            changed_episode=1,
            restored_tick=4,
        )
    )
    world.add_law(build_law("motto", name="Motto", previous_value="old", current_value="new"))
    world.add_law(build_law("quota", name="Quota", previous_value=False, current_value=None))

    world.add_wall(
        build_wall(
            "wall_boundary_ab",
            "boundary_ab",
            active=True,
            permanent=True,
            dependency_score=0.55,
            transport_dependency=0.55,
            resource_dependency=0.4,
            created_tick=20,
            built_tick=20,
        )
    )
    world.add_wall(
        build_wall(
            "wall_boundary_bc",
            "boundary_bc",
            active=False,
            permanent=True,
            integrity=0.75,
            dependency_score=1.0,
            transport_dependency=0.0,
            resource_dependency=1.0,
            created_tick=5,
            built_tick=6,
        )
    )

    for index, kind in enumerate(InfrastructureType):
        world.add_infrastructure(
            build_infrastructure(
                f"infra_{index}",
                "boundary_ab",
                kind=kind,
                capacity=0.0 if index == 2 else 100.0,
                dependency_score=round(0.2 * index, 4),
                degraded=index == 1,
            )
        )
    world.add_infrastructure(
        build_infrastructure("infra_bc", "boundary_bc", kind=InfrastructureType.HOUSING)
    )
    return world


def rich_event_log() -> EventLog:
    """Build an event history with nested payloads and mixed scalar types."""
    log = EventLog()
    log.append(
        Event(
            tick=1,
            type=EventType.RESOURCE_PRODUCED,
            payload={
                "amounts": [1, 2.5, "three", True, None],
                "nested": {"inner": {"deep": [0.0, -0.5]}, "flag": False},
                "empty_list": [],
                "empty_object": {},
            },
            source_id="district_a",
        )
    )
    log.append(Event(tick=3, type=EventType.SCARCITY_CHANGED, payload={}, source_id=None))
    log.append(
        Event(
            tick=20,
            type=EventType.WALL_BUILT,
            payload={"wall_id": "wall_boundary_ab", "boundary_pressure": 0.9},
            source_id="wall_boundary_ab",
        )
    )
    return log


def structural_state(world: World) -> dict[str, object]:
    """Capture a world as comparable values.

    ``World`` compares by identity, so a round trip can only be judged by
    describing both sides explicitly. Every stored field appears here; anything
    left out would be a field the fidelity tests silently stop checking.
    """
    return {
        "tick": world.tick,
        "episode": world.episode,
        "rng": world.rng.get_state(),
        "districts": {
            key: (
                world.districts[key].created_tick,
                world.districts[key].population,
                {r.value: world.districts[key].resources.amount_of(r) for r in ResourceType},
                world.districts[key].production_rate,
                world.districts[key].consumption_rate,
                world.districts[key].scarcity,
                world.districts[key].fear,
                world.districts[key].trust,
                world.districts[key].institutional_pressure,
                world.districts[key].housing_capacity,
                world.districts[key].isolation_state,
            )
            for key in sorted(world.districts)
        },
        "boundaries": {
            key: (
                world.boundaries[key].created_tick,
                world.boundaries[key].district_a_id,
                world.boundaries[key].district_b_id,
                world.boundaries[key].wall_id,
            )
            for key in sorted(world.boundaries)
        },
        "walls": {
            key: (
                world.walls[key].created_tick,
                world.walls[key].boundary_id,
                world.walls[key].built_tick,
                world.walls[key].integrity,
                world.walls[key].active,
                world.walls[key].permanent,
                world.walls[key].dependency_score,
                world.walls[key].transport_dependency,
                world.walls[key].resource_dependency,
            )
            for key in sorted(world.walls)
        },
        "laws": {
            key: (
                world.laws[key].created_tick,
                world.laws[key].name,
                world.laws[key].active,
                world.laws[key].previous_value,
                type(world.laws[key].previous_value).__name__,
                world.laws[key].current_value,
                type(world.laws[key].current_value).__name__,
                world.laws[key].changed_episode,
                world.laws[key].restored_tick,
            )
            for key in sorted(world.laws)
        },
        "infrastructure": {
            key: (
                world.infrastructure[key].created_tick,
                world.infrastructure[key].boundary_id,
                world.infrastructure[key].infrastructure_type,
                world.infrastructure[key].capacity,
                world.infrastructure[key].dependency_score,
                world.infrastructure[key].degraded,
            )
            for key in sorted(world.infrastructure)
        },
    }


def rng_sequence(rng: DeterministicRNG, rounds: int = 6) -> list[object]:
    """Draw a mixed sequence from a generator and return what it produced.

    Several operations are used because they consume the underlying stream
    differently. Comparing only ``random()`` would pass even if the restored
    generator were subtly out of step.
    """
    drawn: list[object] = []
    for _ in range(rounds):
        drawn.append(rng.random())
        drawn.append(rng.randint(0, 1000))
        drawn.append(rng.uniform(-5.0, 5.0))
        drawn.append(rng.chance(0.5))
        drawn.append(rng.choice(["a", "b", "c", "d"]))
        deck = [1, 2, 3, 4, 5]
        rng.shuffle(deck)
        drawn.append(tuple(deck))
    return drawn


def empty_memory(world: World) -> WorldMemory:
    """Return a memory holding nothing, checkpointed to this world.

    Only valid for a world whose episode produced no significant events; the save
    API now checks that a memory is exactly what the episode's events require.
    """
    return WorldMemory((), through_episode=world.episode, through_tick=world.tick)


def quiet_log() -> EventLog:
    """Return an empty log, for an episode in which nothing happened.

    Later episodes in the persistence chain fixtures use this. Replaying episode
    zero's log would re-report ticks the previous episode already covered and
    claim a second construction of the same wall -- both correctly refused now
    that memory lineage is enforced.
    """
    return EventLog()


def memory_for(manager: object, world: World, event_log: EventLog) -> WorldMemory:
    """Return the memory this episode's events actually require.

    Distilled rather than fabricated, continuing from whatever the parent episode
    left on disk. Persistence tests are about files and hashes, but a save now
    has to carry a history that matches its own events, so the fixtures build a
    real one.
    """
    previous = WorldMemory.empty()
    if world.episode > 0:
        parent = manager.episode_directory(world.episode - 1)  # type: ignore[attr-defined]
        if parent.exists():
            loaded = manager.load_episode(world.episode - 1)  # type: ignore[attr-defined]
            previous = loaded.world_memory
        else:
            previous = WorldMemory((), through_episode=world.episode - 1, through_tick=0)
    return MemorySignificance().distill_episode(
        world=world, event_log=event_log, previous_memory=previous
    )


def save_episode(
    manager: object, world: World, event_log: EventLog, *, world_memory: object = None
) -> object:
    """Save an episode, defaulting to the memory its events require.

    The save API requires a memory whose checkpoint and content match the world
    and its log exactly, so a test that is not about memory would otherwise have
    to distil one at every call site.
    """
    memory = memory_for(manager, world, event_log) if world_memory is None else world_memory
    return manager.save_episode(world, event_log, world_memory=memory)  # type: ignore[attr-defined]
