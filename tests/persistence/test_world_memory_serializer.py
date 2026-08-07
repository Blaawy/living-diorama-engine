"""Tests for persisting and reloading WorldMemory.

Persistence stores the durable history; it never decides what belongs in it.
These tests cover the round trip and, more importantly, the strict validation on
the way back in: a memory payload whose hashes are perfectly correct can still
be semantically impossible, and hashes agreeing must not make it loadable.
"""

import json
from pathlib import Path

import pytest

from living_diorama.events import EventLog
from living_diorama.memory import MemoryFactType, MemorySignificance, WorldMemory
from living_diorama.persistence import SaveManager
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    MANIFEST_FILE,
    WORLD_MEMORY_FILE,
)
from living_diorama.persistence.serializers.world_memory_serializer import (
    deserialize_world_memory,
    empty_world_memory,
    serialize_world_memory,
)
from memory.conftest import (
    WALL_ID,
    build_wall,
    build_world,
    wall_built_event,
    wall_built_fact,
    wall_persisted_fact,
)
from persistence.conftest import temporary_save_root


def memory_of(*facts, episode: int = 0, tick: int = 300) -> WorldMemory:
    """Return a memory holding these facts at the given checkpoint.

    Built directly, for tests about the serializer alone. Anything that goes
    through ``SaveManager`` uses a distilled memory instead, because a save now
    has to carry a history matching its own events.
    """
    return WorldMemory(facts, through_episode=episode, through_tick=tick)


def sample_memory() -> WorldMemory:
    """Return a two-episode memory holding one fact of each type."""
    built = wall_built_fact(tick=120, source_event_index=0)
    persisted = wall_persisted_fact(episode=1, tick=250, source_event_index=0)
    return (
        WorldMemory.empty()
        .advance(episode=0, tick=200, new_facts=(built,))
        .advance(episode=1, tick=300, new_facts=(persisted,))
    )


def round_trip(memory: WorldMemory) -> WorldMemory:
    """Serialize a memory through real save bytes and rebuild it."""
    document = loads_canonical(dumps_canonical(serialize_world_memory(memory)))
    return deserialize_world_memory(
        document,
        through_episode=memory.through_episode or 0,
        through_tick=memory.through_tick or 0,
    )


def saved_episode(root: Path, *, walls: tuple[str, ...] = (WALL_ID,)) -> SaveManager:
    """Save one real episode in which each named wall was genuinely built.

    Distilled from actual events, so the saved memory is exactly what the episode
    produced. Hand-built facts about walls the world does not hold are refused --
    correctly -- which is why these tests start from a real episode and tamper
    with the file afterwards.
    """
    world = build_world(
        episode=0,
        tick=300,
        districts=("district_a", "district_b", "district_c"),
        boundaries=tuple(
            (f"boundary_{index}", "district_a", "district_b" if index == 0 else "district_c")
            for index in range(len(walls))
        ),
    )
    log = EventLog()
    for index, wall_id in enumerate(walls):
        world.add_wall(build_wall(wall_id, f"boundary_{index}", built_tick=10 + index))
        log.append(wall_built_event(tick=10 + index, wall_id=wall_id))

    manager = SaveManager(root)
    memory = MemorySignificance().distill_episode(
        world=world, event_log=log, previous_memory=WorldMemory.empty()
    )
    manager.save_episode(world, log, world_memory=memory)
    return manager


# --- Serialization ----------------------------------------------------------


def test_an_empty_memory_writes_the_reserved_placeholder() -> None:
    """The Phase 10 shape is unchanged, which keeps old saves loadable."""
    assert serialize_world_memory(memory_of()) == {"facts": [], "schema_version": 1}
    assert empty_world_memory() == {"facts": [], "schema_version": 1}


def test_a_memory_round_trips_with_every_fact_intact() -> None:
    """Facts, identifiers, wording, and checkpoint all survive."""
    memory = sample_memory()
    restored = round_trip(memory)

    assert restored == memory
    assert [fact.fact_id for fact in restored] == [fact.fact_id for fact in memory]
    assert [fact.summary for fact in restored] == [fact.summary for fact in memory]
    assert restored.through_episode == 1
    assert restored.through_tick == 300


def test_fact_order_is_preserved_exactly() -> None:
    """The memory decides canonical order; storage does not re-derive it."""
    memory = sample_memory()
    document = serialize_world_memory(memory)
    assert [entry["fact_type"] for entry in document["facts"]] == [
        MemoryFactType.WALL_BUILT.value,
        MemoryFactType.LAW_RESTORED_WALL_PERSISTED.value,
    ]


def test_canonical_bytes_are_stable() -> None:
    """Two serializations of one memory agree byte for byte."""
    memory = sample_memory()
    assert dumps_canonical(serialize_world_memory(memory)) == dumps_canonical(
        serialize_world_memory(memory)
    )


def test_payload_insertion_order_does_not_change_the_bytes() -> None:
    """A fact's identity ignores mapping order, and so must its stored form."""
    forward = memory_of(
        wall_built_fact(tick=120, payload={"a": 1, "b": {"x": 1, "y": 2}}), tick=120
    )
    backward = memory_of(
        wall_built_fact(tick=120, payload={"b": {"y": 2, "x": 1}, "a": 1}), tick=120
    )
    assert dumps_canonical(serialize_world_memory(forward)) == dumps_canonical(
        serialize_world_memory(backward)
    )


def test_loaded_facts_and_details_are_immutable() -> None:
    """A reader cannot rewrite history through what a load returned."""
    restored = round_trip(sample_memory())
    fact = restored.facts[0]

    assert isinstance(restored.facts, tuple)
    with pytest.raises(TypeError):
        fact.details["wall_id"] = "other"  # type: ignore[index]
    with pytest.raises(TypeError):
        fact.details["source_event_payload"]["injected"] = 1  # type: ignore[index]


@pytest.mark.parametrize("bad", [None, {}, {"facts": []}, [], "memory", 0])
def test_serializing_something_that_is_not_a_memory_is_refused(bad: object) -> None:
    """Storage takes the domain object, not a document it never validated."""
    with pytest.raises(TypeError):
        serialize_world_memory(bad)


# --- Strict load validation -------------------------------------------------


def rehash_memory(directory: Path) -> None:
    """Recompute the memory payload's digest and length, as a tamperer would.

    This is the interesting kind of tampering: every hash is correct afterwards,
    so only semantic validation can tell the memory is impossible.
    """
    data = (directory / WORLD_MEMORY_FILE).read_bytes()
    manifest = loads_canonical((directory / MANIFEST_FILE).read_bytes())
    manifest["files"][WORLD_MEMORY_FILE] = {"bytes": len(data), "sha256": sha256_hex(data)}
    (directory / MANIFEST_FILE).write_bytes(dumps_canonical(manifest, MANIFEST_FILE))


def tamper(root: Path, mutate) -> SaveManager:
    """Save a valid episode, then rewrite its memory payload canonically."""
    manager = saved_episode(root)
    directory = root / "episode_000"
    document = loads_canonical((directory / WORLD_MEMORY_FILE).read_bytes())
    mutate(document)
    (directory / WORLD_MEMORY_FILE).write_bytes(dumps_canonical(document, WORLD_MEMORY_FILE))
    rehash_memory(directory)
    return manager


def test_the_control_case_still_loads() -> None:
    """A valid rehashed payload must survive, or the tests below prove nothing."""
    with temporary_save_root() as root:
        manager = tamper(root, lambda document: None)
        assert len(manager.load_episode(0).world_memory) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda document: document.update(surprise=1),
        lambda document: document.pop("facts"),
        lambda document: document.update(schema_version=2),
        lambda document: document.update(facts={}),
        lambda document: document["facts"].__setitem__(0, "not an object"),
    ],
)
def test_a_malformed_memory_document_is_refused(mutate) -> None:
    """The top-level shape is fixed in both directions."""
    with temporary_save_root() as root:
        manager = tamper(root, mutate)
        with pytest.raises((TypeError, ValueError)):
            manager.load_episode(0)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda document: document["facts"][0].update(surprise=1),
        lambda document: document["facts"][0].pop("summary"),
        lambda document: document["facts"][0].update(fact_type="MOON_LANDING"),
        lambda document: document["facts"][0].update(source_event_type="LAW_RESTORED"),
        lambda document: document["facts"][0].update(summary="Something else happened."),
        lambda document: document["facts"][0].update(fact_id="fact_" + "0" * 64),
        lambda document: document["facts"][0]["details"].update(surprise=1),
        lambda document: document["facts"][0]["details"].pop("permanent"),
        lambda document: document["facts"][0].update(subject_ids=["only_one"]),
        lambda document: document["facts"][0].update(
            subject_ids=["wall_boundary_ab", "district_b", "district_a", "boundary_ab"]
        ),
        lambda document: document["facts"][0].update(
            subject_ids=["boundary_ab", "boundary_ab", "district_a", "district_b"]
        ),
        lambda document: document["facts"][0].update(episode=True),
        lambda document: document["facts"][0].update(tick=-1),
        lambda document: document["facts"][0]["details"].update(permanent=1),
    ],
)
def test_a_semantically_invalid_fact_is_refused(mutate) -> None:
    """Correct hashes do not make an impossible fact loadable."""
    with temporary_save_root() as root:
        manager = tamper(root, mutate)
        with pytest.raises((TypeError, ValueError)):
            manager.load_episode(0)


def test_a_duplicate_fact_is_refused() -> None:
    """One identifier names one fact."""
    with temporary_save_root() as root:
        manager = tamper(root, lambda document: document["facts"].append(document["facts"][0]))
        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_a_second_claim_that_a_wall_was_built_is_refused() -> None:
    """A wall is built once, however the file spells the two claims."""
    with temporary_save_root() as root:
        manager = saved_episode(root)
        directory = root / "episode_000"
        document = loads_canonical((directory / WORLD_MEMORY_FILE).read_bytes())
        document["facts"].append(document["facts"][0])
        (directory / WORLD_MEMORY_FILE).write_bytes(dumps_canonical(document, WORLD_MEMORY_FILE))
        rehash_memory(directory)

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_out_of_order_facts_are_refused() -> None:
    """Canonical order is required, never imposed by silently sorting."""
    with temporary_save_root() as root:
        manager = saved_episode(root, walls=("wall_one", "wall_two"))
        directory = root / "episode_000"
        document = loads_canonical((directory / WORLD_MEMORY_FILE).read_bytes())
        document["facts"].reverse()
        (directory / WORLD_MEMORY_FILE).write_bytes(dumps_canonical(document, WORLD_MEMORY_FILE))
        rehash_memory(directory)

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_a_fact_beyond_the_manifest_checkpoint_is_refused() -> None:
    """The manifest is authoritative about how far the episode got."""
    with temporary_save_root() as root:
        manager = saved_episode(root)
        directory = root / "episode_000"
        document = loads_canonical((directory / WORLD_MEMORY_FILE).read_bytes())
        document["facts"] = [wall_built_fact(tick=999).to_document()]
        (directory / WORLD_MEMORY_FILE).write_bytes(dumps_canonical(document, WORLD_MEMORY_FILE))
        rehash_memory(directory)

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_a_fact_from_a_later_episode_is_refused() -> None:
    """A memory cannot remember an episode that has not been saved yet."""
    with temporary_save_root() as root:
        manager = saved_episode(root)
        directory = root / "episode_000"
        document = loads_canonical((directory / WORLD_MEMORY_FILE).read_bytes())
        document["facts"] = [wall_built_fact(episode=5, tick=120).to_document()]
        (directory / WORLD_MEMORY_FILE).write_bytes(dumps_canonical(document, WORLD_MEMORY_FILE))
        rehash_memory(directory)

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_a_non_finite_number_in_a_fact_is_refused() -> None:
    """A save may not carry a value JSON cannot represent."""
    with temporary_save_root() as root:
        manager = saved_episode(root)
        directory = root / "episode_000"
        raw = (directory / WORLD_MEMORY_FILE).read_bytes().decode("utf-8")
        raw = raw.replace('"built_tick":10', '"built_tick":1e999', 1)
        (directory / WORLD_MEMORY_FILE).write_bytes(raw.encode("utf-8"))
        rehash_memory(directory)

        with pytest.raises(ValueError):
            manager.load_episode(0)


@pytest.mark.parametrize("bad", [True, 1.0, "0", -1])
def test_a_mistyped_checkpoint_is_refused(bad: object) -> None:
    """The checkpoint comes from the manifest and is validated like everything."""
    document = serialize_world_memory(memory_of())
    with pytest.raises((TypeError, ValueError)):
        deserialize_world_memory(document, through_episode=bad, through_tick=0)
    with pytest.raises((TypeError, ValueError)):
        deserialize_world_memory(document, through_episode=0, through_tick=bad)


# --- Legacy placeholder -----------------------------------------------------


def test_the_phase_ten_placeholder_loads_as_an_empty_checkpointed_memory() -> None:
    """Old saves stay readable, and become a memory that remembers nothing."""
    placeholder = json.loads('{"facts": [], "schema_version": 1}')
    memory = deserialize_world_memory(placeholder, through_episode=3, through_tick=42)

    assert memory.facts == ()
    assert memory.through_episode == 3
    assert memory.through_tick == 42
    assert len(memory) == 0


# --- Memory lineage across saved episodes -----------------------------------
#
# World-state lineage proves an episode descends from its parent's state. It says
# nothing about the parent's history, so a child could forget or rewrite
# everything the world remembered and every hash would still agree.


def two_episode_chain(root: Path) -> tuple[SaveManager, WorldMemory, WorldMemory]:
    """Save a wall-building episode followed by a quiet one."""
    manager = saved_episode(root)
    parent = manager.load_episode(0).world_memory

    child_world = build_world(
        episode=1,
        tick=400,
        districts=("district_a", "district_b", "district_c"),
        boundaries=(("boundary_0", "district_a", "district_b"),),
    )
    child_world.add_wall(build_wall(WALL_ID, "boundary_0", built_tick=10))
    child_memory = MemorySignificance().distill_episode(
        world=child_world, event_log=EventLog(), previous_memory=parent
    )
    manager.save_episode(child_world, EventLog(), world_memory=child_memory)
    return manager, parent, child_memory


def rewrite_child_memory(root: Path, facts: list) -> None:
    """Replace episode one's memory payload canonically and rehash its manifest."""
    directory = root / "episode_001"
    document = loads_canonical((directory / WORLD_MEMORY_FILE).read_bytes())
    document["facts"] = facts
    (directory / WORLD_MEMORY_FILE).write_bytes(dumps_canonical(document, WORLD_MEMORY_FILE))
    rehash_memory(directory)


def test_a_valid_two_episode_memory_chain_loads() -> None:
    """The control case: the child inherits its parent's history intact."""
    with temporary_save_root() as root:
        manager, parent, child = two_episode_chain(root)

        loaded = manager.load_episode(1).world_memory
        assert loaded == child
        assert loaded.facts[: len(parent)] == parent.facts


def test_a_child_that_forgot_its_parent_history_fails_to_load() -> None:
    """Hash-correct files can still record a history that never happened."""
    with temporary_save_root() as root:
        manager, _, _ = two_episode_chain(root)
        rewrite_child_memory(root, [])

        with pytest.raises(ValueError):
            manager.load_episode(1)
        assert manager.load_episode(0) is not None, "episode 0 is unaffected"


def test_a_child_that_rewrote_a_parent_fact_fails_to_load() -> None:
    """An inherited fact is not editable, even into something well-formed."""
    with temporary_save_root() as root:
        manager, parent, _ = two_episode_chain(root)
        tampered = wall_built_fact(
            tick=10,
            source_event_index=0,
            wall_id=WALL_ID,
            boundary_id="boundary_0",
            payload={"wall_id": WALL_ID, "injected": True},
        )
        rewrite_child_memory(root, [tampered.to_document()])

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_a_child_carrying_an_unsupported_extra_fact_fails_to_load() -> None:
    """Nothing may be remembered that no event in that episode produced."""
    with temporary_save_root() as root:
        manager, parent, _ = two_episode_chain(root)
        invented = wall_persisted_fact(
            episode=1,
            tick=400,
            wall_id=WALL_ID,
            boundary_id="boundary_0",
            wall_built_tick=10,
        )
        rewrite_child_memory(
            root, [fact.to_document() for fact in parent.facts] + [invented.to_document()]
        )

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_a_failed_memory_lineage_load_changes_nothing_on_disk() -> None:
    """Verification is a read, including when it rejects."""
    with temporary_save_root() as root:
        manager, _, _ = two_episode_chain(root)
        rewrite_child_memory(root, [])
        before = {
            str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }

        with pytest.raises(ValueError):
            manager.load_episode(1)

        after = {
            str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }
        assert after == before


# --- Save-time memory lineage ----------------------------------------------


def child_inputs(root: Path):
    """Return the world and log for a quiet episode one over a saved episode zero."""
    world = build_world(
        episode=1,
        tick=400,
        districts=("district_a", "district_b", "district_c"),
        boundaries=(("boundary_0", "district_a", "district_b"),),
    )
    world.add_wall(build_wall(WALL_ID, "boundary_0", built_tick=10))
    return world, EventLog()


def assert_nothing_published(root: Path) -> None:
    """Assert a rejected save left episode one absent and staged nothing."""
    assert not (root / "episode_001").exists()
    assert sorted(entry.name for entry in root.iterdir()) == ["episode_000"]


def test_a_child_save_that_forgets_the_parent_history_is_refused() -> None:
    """Rejected before anything reaches the filesystem."""
    with temporary_save_root() as root:
        manager = saved_episode(root)
        world, log = child_inputs(root)
        parent_before = (root / "episode_000" / WORLD_MEMORY_FILE).read_bytes()

        with pytest.raises(ValueError):
            manager.save_episode(
                world, log, world_memory=WorldMemory((), through_episode=1, through_tick=400)
            )

        assert_nothing_published(root)
        assert (root / "episode_000" / WORLD_MEMORY_FILE).read_bytes() == parent_before


def test_a_child_save_that_rewrites_a_parent_fact_is_refused() -> None:
    """The inherited prefix must be exact."""
    with temporary_save_root() as root:
        manager = saved_episode(root)
        world, log = child_inputs(root)
        tampered = wall_built_fact(
            tick=10,
            source_event_index=0,
            wall_id=WALL_ID,
            boundary_id="boundary_0",
            payload={"wall_id": WALL_ID, "injected": True},
        )

        with pytest.raises(ValueError):
            manager.save_episode(
                world,
                log,
                world_memory=WorldMemory((tampered,), through_episode=1, through_tick=400),
            )
        assert_nothing_published(root)


def test_a_child_save_carrying_an_unsupported_fact_is_refused() -> None:
    """A quiet episode produced nothing, so nothing may be appended."""
    with temporary_save_root() as root:
        manager = saved_episode(root)
        parent = manager.load_episode(0).world_memory
        world, log = child_inputs(root)
        invented = wall_persisted_fact(
            episode=1, tick=400, wall_id=WALL_ID, boundary_id="boundary_0", wall_built_tick=10
        )

        with pytest.raises(ValueError):
            manager.save_episode(
                world, log, world_memory=parent.advance(episode=1, tick=400, new_facts=(invented,))
            )
        assert_nothing_published(root)


def test_a_valid_child_save_succeeds_and_keeps_the_parent_untouched() -> None:
    """The control case for the save-time checks above."""
    with temporary_save_root() as root:
        manager = saved_episode(root)
        parent_before = (root / "episode_000" / WORLD_MEMORY_FILE).read_bytes()
        world, log = child_inputs(root)
        manager = SaveManager(root)
        parent_memory = manager.load_episode(0).world_memory
        memory = MemorySignificance().distill_episode(
            world=world, event_log=log, previous_memory=parent_memory
        )
        manager.save_episode(world, log, world_memory=memory)

        assert manager.load_episode(1).world_memory == memory
        assert (root / "episode_000" / WORLD_MEMORY_FILE).read_bytes() == parent_before


def test_a_rejected_child_save_leaves_every_input_unchanged() -> None:
    """World, log, both memories, and the generator are all left as they were."""
    with temporary_save_root() as root:
        manager = saved_episode(root)
        parent = manager.load_episode(0).world_memory
        world, log = child_inputs(root)
        bad = WorldMemory((), through_episode=1, through_tick=400)

        rng_before = world.rng.get_state()
        parent_before = (parent.facts, parent.through_episode, parent.through_tick)
        bad_before = (bad.facts, bad.through_episode, bad.through_tick)

        with pytest.raises(ValueError):
            manager.save_episode(world, log, world_memory=bad)

        assert world.rng.get_state() == rng_before
        assert (parent.facts, parent.through_episode, parent.through_tick) == parent_before
        assert (bad.facts, bad.through_episode, bad.through_tick) == bad_before
        assert log.events() == ()
        assert_nothing_published(root)


def test_a_rejected_save_into_a_missing_root_creates_no_root() -> None:
    """Validation happens before the save root itself is created."""
    with temporary_save_root() as root:
        absent = root / "not_yet"
        with pytest.raises((TypeError, ValueError)):
            SaveManager(absent).save_episode(
                build_world(tick=5), EventLog(), world_memory=WorldMemory.empty()
            )
        assert not absent.exists()


# --- World time never moves backward across saved episodes ------------------


def test_a_child_save_closing_earlier_than_its_parent_is_refused() -> None:
    """A quiet episode appends nothing, so only the transition rule catches this.

    Every byte, length, hash, and state-lineage edge of such a save would be
    correct; the world's clock would simply have run backwards.
    """
    with temporary_save_root() as root:
        manager = saved_episode(root)
        parent = manager.load_episode(0).world_memory
        assert parent.through_tick == 300

        world = build_world(
            episode=1,
            tick=200,
            districts=("district_a", "district_b", "district_c"),
            boundaries=(("boundary_0", "district_a", "district_b"),),
        )
        world.add_wall(build_wall(WALL_ID, "boundary_0", built_tick=10))
        rolled_back = WorldMemory(parent.facts, through_episode=1, through_tick=200)

        with pytest.raises(ValueError):
            manager.save_episode(world, EventLog(), world_memory=rolled_back)

        assert not (root / "episode_001").exists()
        assert sorted(entry.name for entry in root.iterdir()) == ["episode_000"]


def test_a_child_save_closing_at_the_same_tick_is_accepted() -> None:
    """An episode that advanced no ticks is unusual, not contradictory."""
    with temporary_save_root() as root:
        manager = saved_episode(root)
        parent = manager.load_episode(0).world_memory

        world = build_world(
            episode=1,
            tick=parent.through_tick,
            districts=("district_a", "district_b", "district_c"),
            boundaries=(("boundary_0", "district_a", "district_b"),),
        )
        world.add_wall(build_wall(WALL_ID, "boundary_0", built_tick=10))
        memory = MemorySignificance().distill_episode(
            world=world, event_log=EventLog(), previous_memory=parent
        )
        manager.save_episode(world, EventLog(), world_memory=memory)

        assert manager.load_episode(1).world_memory == memory


def test_a_rolled_back_episode_already_on_disk_fails_to_load() -> None:
    """Written by another build, it must not be readable by this one.

    The child's memory payload is left exactly as a legitimate quiet episode
    would write it; only its world closes earlier than its parent's.
    """
    with temporary_save_root() as root:
        manager = saved_episode(root)
        parent = manager.load_episode(0).world_memory

        world = build_world(
            episode=1,
            tick=parent.through_tick,
            districts=("district_a", "district_b", "district_c"),
            boundaries=(("boundary_0", "district_a", "district_b"),),
        )
        world.add_wall(build_wall(WALL_ID, "boundary_0", built_tick=10))
        memory = MemorySignificance().distill_episode(
            world=world, event_log=EventLog(), previous_memory=parent
        )
        manager.save_episode(world, EventLog(), world_memory=memory)

        # Roll the saved world back below its parent, keeping every digest correct.
        directory = root / "episode_001"
        document = loads_canonical((directory / "world_state.json").read_bytes())
        document["tick"] = 200
        data = dumps_canonical(document, "world_state.json")
        (directory / "world_state.json").write_bytes(data)
        manifest = loads_canonical((directory / MANIFEST_FILE).read_bytes())
        manifest["tick"] = 200
        manifest["files"]["world_state.json"] = {
            "bytes": len(data),
            "sha256": sha256_hex(data),
        }
        manifest["state_hash"] = sha256_hex(data)
        (directory / MANIFEST_FILE).write_bytes(dumps_canonical(manifest, MANIFEST_FILE))

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_a_hostile_object_is_refused_by_the_serializer() -> None:
    """The memory's true runtime type decides, not its ``__class__`` property."""

    class HostileClass:
        """Raises from ``__class__`` instead of answering."""

        @property
        def __class__(self) -> type:
            """Raise instead of revealing a type."""
            raise RuntimeError("boom")

    with pytest.raises(TypeError, match="world_memory must be a WorldMemory, got HostileClass"):
        serialize_world_memory(HostileClass())
