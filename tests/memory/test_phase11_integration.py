"""The Phase 11 promise, end to end: the world remembers.

A wall is built in one episode. A law is restored in the next, and the wall is
still standing. Both facts survive being saved, reloaded, and queried -- and the
second one says only that the wall remained, never that the law had anything to
do with it.

Both episodes are genuine engine output: Phase 8's boundary system builds the
wall, and Phase 12's ``RuleSystem`` restores the law through a real
``SimulationLoop`` tick, publishing ``LAW_RESTORED`` through a real
``EventBus`` into a real ``EventLog``.
"""

import pytest

from living_diorama.entities import Boundary
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.memory import (
    MemoryFactType,
    MemoryQuery,
    MemorySignificance,
    WorldMemory,
)
from living_diorama.persistence import SaveManager
from living_diorama.persistence.json_codec import loads_canonical
from living_diorama.persistence.schema.world_schema_v1 import (
    MANIFEST_FILE,
    WORLD_MEMORY_FILE,
)
from living_diorama.persistence.serializers.world_memory_serializer import (
    deserialize_world_memory,
)
from living_diorama.simulation import SimulationLoop
from living_diorama.simulation.world import World
from living_diorama.systems import BoundaryDecisionSystem, RuleSystem, ScheduledLawRestore
from memory.conftest import (
    BOUNDARY_ID,
    LAW_ID,
    build_district,
    build_law,
    build_wall,
    consumed_rng,
)
from persistence.conftest import temporary_save_root

EPISODE_ZERO_TICK = 120
"""The tick at which episode zero closes, and at which the wall is built."""

RESTORATION_TICK = 250
"""The tick at which the law is restored in episode one."""


def pressured_world(*, episode: int, tick: int, pressure: float) -> World:
    """Build a two-district world whose districts carry a chosen pressure."""
    world = World(rng=consumed_rng(), tick=tick, episode=episode)
    for name in ("district_a", "district_b"):
        district = build_district(name)
        district.institutional_pressure = pressure
        world.add_district(district)
    world.add_boundary(
        Boundary(
            id=BOUNDARY_ID,
            created_tick=0,
            district_a_id="district_a",
            district_b_id="district_b",
        )
    )
    return world


def run_episode_zero() -> tuple[World, EventLog]:
    """Run the real boundary system until it raises a wall, and return the result.

    The ``WALL_BUILT`` event is genuine engine output, not a fixture: the world's
    institutional pressure is above the build threshold, and Phase 8 decides.
    """
    world = pressured_world(episode=0, tick=EPISODE_ZERO_TICK, pressure=0.95)
    world.add_law(
        build_law(active=False, previous_value=True, current_value=False, changed_episode=0)
    )

    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    BoundaryDecisionSystem().update(world, bus)
    return world, log


def episode_one(previous_world: World) -> tuple[World, EventLog]:
    """Advance to episode one and let the real RuleSystem restore the law.

    The restoration is genuine Phase 12 output: a scheduled ``RuleSystem`` runs
    first -- and here, alone -- in a real ``SimulationLoop`` tick, mutating the
    law and publishing the ``LAW_RESTORED`` event this file's memory tests
    distill.
    """
    world = pressured_world(episode=1, tick=RESTORATION_TICK - 1, pressure=0.95)
    built = previous_world.walls[f"wall_{BOUNDARY_ID}"]
    world.add_wall(
        build_wall(
            built.id,
            built.boundary_id,
            built_tick=built.built_tick,
            active=True,
            permanent=True,
            dependency_score=0.78,
            transport_dependency=0.78,
            resource_dependency=0.65,
        )
    )
    world.add_law(
        build_law(active=False, previous_value=True, current_value=False, changed_episode=0)
    )

    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    rule = RuleSystem((ScheduledLawRestore(episode=1, tick=RESTORATION_TICK, law_id=LAW_ID),))
    SimulationLoop((rule,), bus).run(world, 1)
    return world, log


def test_the_boundary_system_really_builds_the_wall() -> None:
    """Guards the fixture: episode zero's event is genuine engine output."""
    world, log = run_episode_zero()

    built = log.query(event_type=EventType.WALL_BUILT)
    assert len(built) == 1
    assert built[0].tick == EPISODE_ZERO_TICK
    assert world.walls[f"wall_{BOUNDARY_ID}"].permanent is True


def test_the_world_remembers_across_two_saved_episodes() -> None:
    """The whole Phase 11 chain, from a real wall to a queryable recap."""
    with temporary_save_root() as root:
        manager = SaveManager(root)

        # --- Episode 0: a wall is built and remembered ---
        world_zero, log_zero = run_episode_zero()
        memory_zero = MemorySignificance().distill_episode(
            world=world_zero, event_log=log_zero, previous_memory=WorldMemory.empty()
        )

        assert len(memory_zero) == 1
        wall_fact = memory_zero.facts[0]
        assert wall_fact.fact_type is MemoryFactType.WALL_BUILT
        assert wall_fact.tick == EPISODE_ZERO_TICK

        manager.save_episode(world_zero, log_zero, world_memory=memory_zero)
        loaded_zero = manager.load_episode(0)
        assert loaded_zero.world_memory == memory_zero

        # --- Episode 1: the law is restored and the wall is still there ---
        world_one, log_one = episode_one(world_zero)
        memory_one = MemorySignificance().distill_episode(
            world=world_one, event_log=log_one, previous_memory=loaded_zero.world_memory
        )

        assert len(memory_one) == 2
        assert memory_one.facts[0] == wall_fact, "the earlier fact is unchanged"
        persistence_fact = memory_one.facts[1]
        assert persistence_fact.fact_type is MemoryFactType.LAW_RESTORED_WALL_PERSISTED
        assert persistence_fact.details["wall_id"] == wall_fact.details["wall_id"]
        assert persistence_fact.details["wall_built_tick"] == EPISODE_ZERO_TICK
        for banned in ("caused", "because of", "therefore", "responsible for", "led to"):
            assert banned not in persistence_fact.summary

        manager.save_episode(world_one, log_one, world_memory=memory_one)
        loaded_one = manager.load_episode(1)
        assert loaded_one.world_memory == memory_one

        # --- Both facts remain queryable and read forwards ---
        query = MemoryQuery(loaded_one.world_memory)
        assert len(query.facts(fact_type=MemoryFactType.WALL_BUILT)) == 1
        assert len(query.facts(fact_type=MemoryFactType.LAW_RESTORED_WALL_PERSISTED)) == 1
        assert len(query.facts(subject_id=wall_fact.details["wall_id"])) == 2
        assert query.narration_context() == (wall_fact.summary, persistence_fact.summary)
        assert [fact.tick for fact in loaded_one.world_memory] == [
            EPISODE_ZERO_TICK,
            RESTORATION_TICK,
        ]


def test_the_cumulative_memory_is_self_contained_in_the_latest_episode() -> None:
    """Episode 1's own payload carries the whole history, episode 0 included.

    Read from that episode's two files alone. Lineage still requires the full
    ancestry to *load* an episode through SaveManager -- that is Phase 10's
    contract and is not weakened here -- but the memory payload itself needs no
    earlier folder to be complete.
    """
    with temporary_save_root() as root:
        manager = SaveManager(root)
        world_zero, log_zero = run_episode_zero()
        memory_zero = MemorySignificance().distill_episode(
            world=world_zero, event_log=log_zero, previous_memory=WorldMemory.empty()
        )
        manager.save_episode(world_zero, log_zero, world_memory=memory_zero)

        world_one, log_one = episode_one(world_zero)
        memory_one = MemorySignificance().distill_episode(
            world=world_one, event_log=log_one, previous_memory=memory_zero
        )
        manager.save_episode(world_one, log_one, world_memory=memory_one)

        directory = root / "episode_001"
        manifest = loads_canonical((directory / MANIFEST_FILE).read_bytes())
        document = loads_canonical((directory / WORLD_MEMORY_FILE).read_bytes())
        rebuilt = deserialize_world_memory(
            document,
            through_episode=manifest["episode"],
            through_tick=manifest["tick"],
        )

        assert rebuilt == memory_one
        assert len(rebuilt) == 2
        assert MemoryQuery(rebuilt).narration_context() == tuple(
            fact.summary for fact in memory_one
        )


def test_the_saved_episodes_agree_on_the_history_they_carry() -> None:
    """Episode 1 holds everything episode 0 held, plus what episode 1 added."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        world_zero, log_zero = run_episode_zero()
        memory_zero = MemorySignificance().distill_episode(
            world=world_zero, event_log=log_zero, previous_memory=WorldMemory.empty()
        )
        manager.save_episode(world_zero, log_zero, world_memory=memory_zero)

        world_one, log_one = episode_one(world_zero)
        memory_one = MemorySignificance().distill_episode(
            world=world_one, event_log=log_one, previous_memory=memory_zero
        )
        manager.save_episode(world_one, log_one, world_memory=memory_one)

        earlier = manager.load_episode(0).world_memory
        later = manager.load_episode(1).world_memory

        assert later.facts[: len(earlier)] == earlier.facts
        assert later.through_episode == 1
        assert earlier.through_episode == 0
        manager.verify_lineage(0, 1)


def test_distilling_the_second_episode_leaves_the_first_memory_alone() -> None:
    """Memory is a value: growing it never edits what came before."""
    world_zero, log_zero = run_episode_zero()
    memory_zero = MemorySignificance().distill_episode(
        world=world_zero, event_log=log_zero, previous_memory=WorldMemory.empty()
    )
    snapshot = (memory_zero.facts, memory_zero.through_episode, memory_zero.through_tick)

    world_one, log_one = episode_one(world_zero)
    MemorySignificance().distill_episode(
        world=world_one, event_log=log_one, previous_memory=memory_zero
    )

    assert (memory_zero.facts, memory_zero.through_episode, memory_zero.through_tick) == snapshot
    assert len(memory_zero) == 1


def test_an_episode_saved_with_a_mismatched_memory_is_refused() -> None:
    """The two halves of a save must describe the same moment."""
    with temporary_save_root() as root:
        world_zero, log_zero = run_episode_zero()
        memory_zero = MemorySignificance().distill_episode(
            world=world_zero, event_log=log_zero, previous_memory=WorldMemory.empty()
        )
        world_one, _ = episode_one(world_zero)

        with pytest.raises(ValueError):
            SaveManager(root).save_episode(world_one, EventLog(), world_memory=memory_zero)
        assert list(root.iterdir()) == []
