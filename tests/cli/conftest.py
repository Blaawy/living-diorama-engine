"""Shared builders for the Phase 13 continuation tests.

Everything here goes through real engine components: worlds are built through
public constructors, episode 0 is published through the real
:class:`SaveManager`, and its memory is distilled by the real
:class:`MemorySignificance`. The builders return fresh objects on every call so
no test can leak state into another.
"""

import json
from pathlib import Path
from typing import Any

from living_diorama.entities import (
    Boundary,
    District,
    Infrastructure,
    InfrastructureType,
    IsolationState,
    Law,
    LawValue,
    ResourcePool,
    ResourceType,
    Wall,
)
from living_diorama.events import Event, EventLog, EventType
from living_diorama.memory import MemorySignificance, WorldMemory
from living_diorama.persistence import SaveManager
from living_diorama.simulation import DeterministicRNG, World

MOVEMENT_LAW_ID = "law_movement_sharing"
"""The movement/resource-sharing law every fixture world carries."""

BOUNDARY_ID = "boundary_ab"
"""The single boundary joining the two fixture districts."""

WALL_ID = "wall_boundary_ab"
"""The permanent wall the scar fixtures raise on the boundary."""

INFRASTRUCTURE_ID = "infra_transit_ab"
"""The transit infrastructure attached to the boundary."""

PARENT_TICK = 4
"""Absolute tick where the default episode 0 fixture ends."""

SCAR_PARENT_TICK = 8
"""Absolute tick where the scar episode 0 fixture ends."""

WALL_BUILT_TICK = 5
"""Absolute tick the scar fixture's wall was built, inside episode 0."""


def consumed_rng(seed: int = 20260807, draws: int = 7) -> DeterministicRNG:
    """Return a generator that is mid-sequence, like any real saved episode."""
    rng = DeterministicRNG(seed)
    for _ in range(draws):
        rng.random()
    return rng


def build_district(
    district_id: str,
    *,
    population: int,
    production_rate: float,
    consumption_rate: float,
    food: float,
    materials: float,
    energy: float,
    fear: float,
    trust: float,
    scarcity: float,
    institutional_pressure: float,
    housing_capacity: int,
) -> District:
    """Build one district with explicit dynamics and stock."""
    return District(
        id=district_id,
        created_tick=0,
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
        isolation_state=IsolationState.OPEN,
    )


def build_movement_law(
    *,
    active: bool = True,
    previous_value: LawValue = None,
    current_value: LawValue = True,
    changed_episode: int = 0,
    restored_tick: int | None = None,
) -> Law:
    """Build the movement/resource-sharing law the causal systems consult."""
    return Law(
        id=MOVEMENT_LAW_ID,
        created_tick=0,
        name="movement_resource_sharing",
        active=active,
        previous_value=previous_value,
        current_value=current_value,
        changed_episode=changed_episode,
        restored_tick=restored_tick,
    )


def build_parent_world(
    *,
    episode: int = 0,
    tick: int = PARENT_TICK,
    law_active: bool = True,
    law_previous: LawValue = None,
    law_current: LawValue = True,
    with_wall: bool = False,
    seed: int = 20260807,
) -> World:
    """Build the two-district episode 0 world every continuation test starts from.

    The districts are deliberately comfortable -- production covers demand --
    so the run's dynamics stay far from the wall-building threshold unless a
    test asks for pressure. With ``with_wall`` the world carries a permanent
    wall raised at :data:`WALL_BUILT_TICK`, which must then be paired with the
    matching ``WALL_BUILT`` event so memory distillation accepts the history.
    """
    world = World(rng=consumed_rng(seed), tick=tick, episode=episode)
    world.add_district(
        build_district(
            "district_a",
            population=80,
            production_rate=6.0,
            consumption_rate=0.05,
            food=30.0,
            materials=20.0,
            energy=10.0,
            fear=0.2,
            trust=0.7,
            scarcity=0.1,
            institutional_pressure=0.2,
            housing_capacity=500,
        )
    )
    world.add_district(
        build_district(
            "district_b",
            population=40,
            production_rate=1.0,
            consumption_rate=0.05,
            food=2.0,
            materials=1.0,
            energy=1.0,
            fear=0.3,
            trust=0.6,
            scarcity=0.3,
            institutional_pressure=0.3,
            housing_capacity=300,
        )
    )
    world.add_boundary(
        Boundary(
            id=BOUNDARY_ID,
            created_tick=0,
            district_a_id="district_a",
            district_b_id="district_b",
        )
    )
    world.add_law(
        build_movement_law(
            active=law_active, previous_value=law_previous, current_value=law_current
        )
    )
    if with_wall:
        world.add_wall(
            Wall(
                id=WALL_ID,
                created_tick=WALL_BUILT_TICK,
                boundary_id=BOUNDARY_ID,
                built_tick=WALL_BUILT_TICK,
                integrity=1.0,
                active=True,
                permanent=True,
                dependency_score=0.0,
                transport_dependency=0.0,
                resource_dependency=0.0,
            )
        )
    world.add_infrastructure(
        Infrastructure(
            id=INFRASTRUCTURE_ID,
            created_tick=0,
            boundary_id=BOUNDARY_ID,
            infrastructure_type=InfrastructureType.TRANSIT_ROUTE,
            capacity=100.0,
            dependency_score=0.0,
            degraded=False,
        )
    )
    return world


def build_scar_world(*, seed: int = 20260807) -> World:
    """Build the scar fixture: a permanent wall stands and the law is out.

    The movement law is inactive with its original value stored, so it is
    exactly eligible for a scheduled restoration; the wall was built inside
    episode 0 and must be remembered through the matching ``WALL_BUILT`` event.
    """
    return build_parent_world(
        tick=SCAR_PARENT_TICK,
        law_active=False,
        law_previous=True,
        law_current=False,
        with_wall=True,
        seed=seed,
    )


def wall_built_event() -> Event:
    """Return the ``WALL_BUILT`` event matching the scar fixture's wall."""
    return Event(
        tick=WALL_BUILT_TICK,
        type=EventType.WALL_BUILT,
        payload={"boundary_pressure": 0.9, "wall_id": WALL_ID},
        source_id=WALL_ID,
    )


def scar_event_log() -> EventLog:
    """Return the scar fixture's episode 0 history: one wall construction."""
    log = EventLog()
    log.append(wall_built_event())
    return log


def save_episode_zero(root: Path, world: World, event_log: EventLog | None = None) -> None:
    """Publish an episode 0 world through the real persistence layer.

    The memory is distilled by the real :class:`MemorySignificance`, so the
    published episode is exactly what a genuine run would have written.
    """
    log = EventLog() if event_log is None else event_log
    memory = MemorySignificance().distill_episode(
        world=world, event_log=log, previous_memory=WorldMemory.empty()
    )
    SaveManager(root).save_episode(world, log, world_memory=memory)


def systems_section() -> dict[str, Any]:
    """Return a fresh, fully explicit systems section for a run plan.

    Every value is deliberately distinct from every other -- the two
    allocations differ and no scalar repeats -- so a test asserting where a
    parameter landed can actually fail if two parameters were ever
    cross-wired. Aliased fixture values would make such a swap invisible.
    """
    return {
        "production_allocation": {"FOOD": 0.6, "MATERIALS": 0.3, "ENERGY": 0.1},
        "consumption_allocation": {"FOOD": 0.5, "MATERIALS": 0.3, "ENERGY": 0.2},
        "movement_law_id": MOVEMENT_LAW_ID,
        "resource_flow": {"reserve_ticks": 1.5},
        "migration": {
            "migration_rate": 0.2,
            "min_pressure_gap": 0.05,
            "partial_isolation_factor": 0.45,
        },
        "social_stability": {
            "scarcity_weight": 1.1,
            "housing_pressure_weight": 0.9,
            "response_rate": 0.25,
        },
        "institutional_pressure": {
            "scarcity_weight": 1.2,
            "fear_weight": 0.8,
            "distrust_weight": 0.7,
            "response_rate": 0.15,
        },
        "boundary_decision": {"build_threshold": 0.95},
        "infrastructure_adaptation": {"adaptation_rate": 0.1},
    }


def change_plan_document(
    *,
    parent_episode: int = 0,
    ticks: int = 6,
    tick: int = PARENT_TICK + 3,
    law_id: str = MOVEMENT_LAW_ID,
    new_value: object = False,
    active: object = False,
) -> dict[str, Any]:
    """Return a fresh, valid change-intervention plan document."""
    return {
        "parent_episode": parent_episode,
        "ticks": ticks,
        "intervention": {
            "kind": "change",
            "tick": tick,
            "law_id": law_id,
            "new_value": new_value,
            "active": active,
        },
        "systems": systems_section(),
    }


def restore_plan_document(
    *,
    parent_episode: int = 0,
    ticks: int = 6,
    tick: int = SCAR_PARENT_TICK + 3,
    law_id: str = MOVEMENT_LAW_ID,
) -> dict[str, Any]:
    """Return a fresh, valid restore-intervention plan document."""
    return {
        "parent_episode": parent_episode,
        "ticks": ticks,
        "intervention": {"kind": "restore", "tick": tick, "law_id": law_id},
        "systems": systems_section(),
    }


def plan_bytes(document: dict[str, Any]) -> bytes:
    """Encode a plan document the way an operator's editor would."""
    return json.dumps(document).encode("utf-8")


def write_plan(path: Path, document: dict[str, Any]) -> Path:
    """Write a plan document to disk and return its path."""
    path.write_bytes(plan_bytes(document))
    return path


def tree_bytes(root: Path) -> dict[str, bytes]:
    """Return every file under a save root, keyed by relative path."""
    return {
        str(entry.relative_to(root)): entry.read_bytes()
        for entry in sorted(root.rglob("*"))
        if entry.is_file()
    }
