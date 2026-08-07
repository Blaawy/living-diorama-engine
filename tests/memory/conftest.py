"""Shared builders for the Phase 11 world-memory tests.

Plain functions rather than fixtures, so every test states the world it is
talking about. Memory tests turn on exact stored values, and a shared mutable
fixture would make it easy for one test to change what another is asserting.
"""

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
from living_diorama.memory import MemoryFact, MemoryFactType, WorldMemory
from living_diorama.simulation.rng import DeterministicRNG
from living_diorama.simulation.world import World

BOUNDARY_ID = "boundary_ab"
"""The boundary most tests build a wall on."""

WALL_ID = "wall_boundary_ab"
"""The wall most tests build."""

LAW_ID = "resource_sharing"
"""The law most tests restore."""


def consumed_rng(seed: int = 20260806, draws: int = 5) -> DeterministicRNG:
    """Return a generator that has already been used."""
    rng = DeterministicRNG(seed)
    for _ in range(draws):
        rng.random()
    return rng


def build_district(district_id: str, *, created_tick: int = 0) -> District:
    """Build an ordinary populated district."""
    return District(
        id=district_id,
        created_tick=created_tick,
        population=100,
        resources=ResourcePool(stock={resource: 1.0 for resource in ResourceType}),
        production_rate=1.0,
        consumption_rate=1.0,
        scarcity=0.0,
        fear=0.0,
        trust=1.0,
        institutional_pressure=0.0,
        housing_capacity=1000,
        isolation_state=IsolationState.OPEN,
    )


def build_wall(
    wall_id: str = WALL_ID,
    boundary_id: str = BOUNDARY_ID,
    *,
    built_tick: int = 120,
    active: bool = True,
    permanent: bool = True,
    dependency_score: float = 0.0,
    transport_dependency: float = 0.0,
    resource_dependency: float = 0.0,
) -> Wall:
    """Build a wall with fully specified stored state."""
    return Wall(
        id=wall_id,
        created_tick=built_tick,
        boundary_id=boundary_id,
        built_tick=built_tick,
        integrity=1.0,
        active=active,
        permanent=permanent,
        dependency_score=dependency_score,
        transport_dependency=transport_dependency,
        resource_dependency=resource_dependency,
    )


def build_law(
    law_id: str = LAW_ID,
    *,
    name: str = "Resource Sharing",
    active: bool = True,
    previous_value: object = False,
    current_value: object = True,
    changed_episode: int = 0,
    restored_tick: int | None = None,
) -> Law:
    """Build a law with fully specified stored state."""
    return Law(
        id=law_id,
        created_tick=0,
        name=name,
        active=active,
        previous_value=previous_value,  # type: ignore[arg-type]
        current_value=current_value,  # type: ignore[arg-type]
        changed_episode=changed_episode,
        restored_tick=restored_tick,
    )


def build_infrastructure(infrastructure_id: str, boundary_id: str = BOUNDARY_ID) -> Infrastructure:
    """Build an ordinary transit route on a boundary."""
    return Infrastructure(
        id=infrastructure_id,
        created_tick=0,
        boundary_id=boundary_id,
        infrastructure_type=InfrastructureType.TRANSIT_ROUTE,
        capacity=100.0,
        dependency_score=0.0,
        degraded=False,
    )


def build_world(
    *,
    episode: int = 0,
    tick: int = 120,
    districts: tuple[str, ...] = ("district_a", "district_b"),
    boundaries: tuple[tuple[str, str, str], ...] = ((BOUNDARY_ID, "district_a", "district_b"),),
) -> World:
    """Build a world with districts and boundaries but no walls or laws."""
    world = World(rng=consumed_rng(), tick=tick, episode=episode)
    for district_id in districts:
        world.add_district(build_district(district_id))
    for boundary_id, first, second in boundaries:
        world.add_boundary(
            Boundary(id=boundary_id, created_tick=0, district_a_id=first, district_b_id=second)
        )
    return world


def world_with_wall(*, episode: int = 0, tick: int = 120, built_tick: int = 120, **kwargs) -> World:
    """Build a world whose single boundary carries one permanent wall."""
    world = build_world(episode=episode, tick=tick)
    world.add_wall(build_wall(built_tick=built_tick, **kwargs))
    return world


def wall_built_event(
    *, tick: int = 120, wall_id: str = WALL_ID, payload: dict | None = None
) -> Event:
    """Build the event a boundary decision publishes when it raises a wall."""
    return Event(
        tick=tick,
        type=EventType.WALL_BUILT,
        payload={"wall_id": wall_id} if payload is None else payload,
        source_id=wall_id,
    )


def law_restored_event(
    *, tick: int = 250, law_id: str = LAW_ID, payload: dict | None = None
) -> Event:
    """Build the event a future rule system will publish on restoring a law.

    A fixture standing in for Phase 12's output contract. No rule system exists
    yet, and none is implemented here.
    """
    return Event(
        tick=tick,
        type=EventType.LAW_RESTORED,
        payload={} if payload is None else payload,
        source_id=law_id,
    )


def log_of(*events: Event) -> EventLog:
    """Return an event log holding these events in order."""
    log = EventLog()
    for event in events:
        log.append(event)
    return log


def wall_built_fact(
    *,
    episode: int = 0,
    tick: int = 120,
    source_event_index: int = 0,
    wall_id: str = WALL_ID,
    boundary_id: str = BOUNDARY_ID,
    district_a_id: str = "district_a",
    district_b_id: str = "district_b",
    permanent: bool = True,
    payload: dict | None = None,
) -> MemoryFact:
    """Build a wall-construction fact directly, bypassing distillation."""
    return MemoryFact(
        fact_type=MemoryFactType.WALL_BUILT,
        episode=episode,
        tick=tick,
        source_event_index=source_event_index,
        source_event_type=EventType.WALL_BUILT,
        source_id=wall_id,
        subject_ids=tuple(sorted({boundary_id, district_a_id, district_b_id, wall_id})),
        details={
            "boundary_id": boundary_id,
            "built_tick": tick,
            "district_a_id": district_a_id,
            "district_b_id": district_b_id,
            "permanent": permanent,
            "source_event_payload": {"wall_id": wall_id} if payload is None else payload,
            "wall_id": wall_id,
        },
    )


def wall_persisted_fact(
    *,
    episode: int = 1,
    tick: int = 250,
    source_event_index: int = 0,
    wall_id: str = WALL_ID,
    boundary_id: str = BOUNDARY_ID,
    law_id: str = LAW_ID,
    wall_built_tick: int = 120,
    payload: dict | None = None,
) -> MemoryFact:
    """Build a wall-persistence fact directly, bypassing distillation."""
    return MemoryFact(
        fact_type=MemoryFactType.LAW_RESTORED_WALL_PERSISTED,
        episode=episode,
        tick=tick,
        source_event_index=source_event_index,
        source_event_type=EventType.LAW_RESTORED,
        source_id=law_id,
        subject_ids=tuple(sorted({boundary_id, law_id, wall_id})),
        details={
            "boundary_id": boundary_id,
            "law_current_value": True,
            "law_id": law_id,
            "law_name": "Resource Sharing",
            "law_previous_value": False,
            "restored_tick": tick,
            "source_event_payload": {} if payload is None else payload,
            "wall_active_at_episode_close": True,
            "wall_built_tick": wall_built_tick,
            "wall_dependency_score_at_episode_close": 0.78,
            "wall_id": wall_id,
            "wall_permanent": True,
            "wall_resource_dependency_at_episode_close": 0.65,
            "wall_transport_dependency_at_episode_close": 0.78,
        },
    )


def memory_with(*facts: MemoryFact, episode: int = 0, tick: int = 120) -> WorldMemory:
    """Return a memory holding these facts, checkpointed as given."""
    return WorldMemory(facts, through_episode=episode, through_tick=tick)
