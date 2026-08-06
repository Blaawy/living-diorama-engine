"""End-to-end persistence: save, verify, load, continue, and prove nothing moved.

The chain these tests exist to prove is the one the whole series depends on:
an episode can be put down and picked up again as exactly the same world, with
the same generator, the same history, and a verified link back to where it came
from.
"""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from living_diorama.entities import InfrastructureType, IsolationState, ResourceType
from living_diorama.events import EventLog
from living_diorama.persistence import SaveManager
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.world_schema_v1 import (
    EVENT_LOG_FILE,
    MANIFEST_FILE,
    WORLD_MEMORY_FILE,
    WORLD_STATE_FILE,
)
from living_diorama.persistence.serializers.world_serializer import serialize_world
from living_diorama.simulation.rng import DeterministicRNG
from persistence.conftest import (
    minimal_world,
    rich_event_log,
    rich_world,
    rng_sequence,
    structural_state,
    temporary_save_root,
)


def test_the_rich_world_actually_covers_every_awkward_shape() -> None:
    """Guards the fixture itself, so later proofs are not quietly narrow."""
    world = rich_world()

    assert any(district.population == 0 for district in world.districts.values())
    assert any(
        district.isolation_state is IsolationState.PARTIAL for district in world.districts.values()
    )
    assert any(boundary.wall_id is None for boundary in world.boundaries.values())
    assert any(wall.active and wall.permanent for wall in world.walls.values())
    assert any(not wall.active and wall.permanent for wall in world.walls.values())
    assert any(wall.dependency_score > 0.0 for wall in world.walls.values())

    kinds = {entity.infrastructure_type for entity in world.infrastructure.values()}
    assert kinds == set(InfrastructureType)
    assert any(entity.degraded for entity in world.infrastructure.values())
    assert any(entity.capacity == 0.0 for entity in world.infrastructure.values())

    law_types = {type(law.current_value).__name__ for law in world.laws.values()}
    assert law_types == {"bool", "float", "str", "NoneType"}

    assert world.tick > 0
    assert world.rng.get_state() != DeterministicRNG(20260806).get_state()


def test_the_full_chain_save_verify_load_continue() -> None:
    """The minimum success chain, proven in one place."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        original = rich_world()
        original_log = rich_event_log()
        before = structural_state(original)

        manifest = manager.save_episode(original, original_log)
        loaded = manager.load_episode(0)

        assert structural_state(loaded.world) == before
        assert loaded.event_log.events() == original_log.events()
        assert loaded.manifest.state_hash == manifest.state_hash

        reference = DeterministicRNG(0)
        reference.set_state(original.rng.get_state())
        assert rng_sequence(loaded.world.rng) == rng_sequence(reference)


def test_reserialization_after_a_load_is_byte_identical() -> None:
    """The stronger proof: a reload must hash to exactly what was saved.

    Compared at the serializer level so nothing has to be written over an
    episode that is supposed to be immutable.
    """
    with temporary_save_root() as root:
        manager = SaveManager(root)
        original = rich_world()
        manifest = manager.save_episode(original, rich_event_log())

        loaded = manager.load_episode(0)
        rewritten = dumps_canonical(serialize_world(loaded.world))

        assert rewritten == (root / "episode_000" / WORLD_STATE_FILE).read_bytes()
        from living_diorama.persistence import sha256_hex  # noqa: PLC0415

        assert sha256_hex(rewritten) == manifest.state_hash


def test_saving_the_same_world_twice_produces_identical_payloads() -> None:
    """Two independent saves of one state agree byte for byte."""
    with temporary_save_root() as first_root, temporary_save_root() as second_root:
        first = SaveManager(first_root).save_episode(rich_world(), rich_event_log())
        second = SaveManager(second_root).save_episode(rich_world(), rich_event_log())

        assert first.state_hash == second.state_hash
        for name in (EVENT_LOG_FILE, WORLD_MEMORY_FILE, WORLD_STATE_FILE):
            assert (first_root / "episode_000" / name).read_bytes() == (
                second_root / "episode_000" / name
            ).read_bytes()


def test_a_second_load_returns_independent_objects() -> None:
    """Two loads must not share entities, or editing one would alter the other."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manager.save_episode(rich_world(), rich_event_log())

        first = manager.load_episode(0)
        second = manager.load_episode(0)

        assert first.world is not second.world
        assert first.world.districts["district_a"] is not second.world.districts["district_a"]
        first.world.districts["district_a"].population = 999
        assert second.world.districts["district_a"].population == 120


# --- Mutation ownership -----------------------------------------------------


def test_saving_mutates_nothing_it_was_given() -> None:
    """Every input is snapshotted and compared after the save."""
    with temporary_save_root() as root:
        world = rich_world()
        event_log = rich_event_log()
        memory = {"facts": [{"kind": "note", "text": "kept"}], "schema_version": 1}

        world_before = structural_state(world)
        events_before = event_log.events()
        rng_before = world.rng.get_state()
        memory_before = copy.deepcopy(memory)

        SaveManager(root).save_episode(world, event_log, world_memory=memory)

        assert structural_state(world) == world_before
        assert event_log.events() == events_before
        assert world.rng.get_state() == rng_before
        assert memory == memory_before


def test_saving_does_not_advance_the_tick_or_episode() -> None:
    """Persistence records the world; it never moves it forward."""
    with temporary_save_root() as root:
        world = rich_world(episode=0, tick=20)
        SaveManager(root).save_episode(world, rich_event_log())
        assert world.tick == 20
        assert world.episode == 0


def test_loading_consumes_no_randomness() -> None:
    """A restored generator must be exactly where it was, not one draw later."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        world = rich_world()
        expected = world.rng.get_state()
        manager.save_episode(world, rich_event_log())

        assert manager.load_episode(0).world.rng.get_state() == expected


# --- World memory -----------------------------------------------------------


def test_the_default_memory_document_is_the_empty_placeholder() -> None:
    """Phase 10 writes the reserved shape and nothing else."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manager.save_episode(minimal_world(), EventLog())
        document = loads_canonical((root / "episode_000" / WORLD_MEMORY_FILE).read_bytes())

        assert document == {"facts": [], "schema_version": 1}
        assert dict(manager.load_episode(0).world_memory) == document


def test_supplied_facts_are_preserved_in_order_and_untouched() -> None:
    """Persistence carries the document; it does not understand it.

    Nothing is filtered, summarized, deduplicated, reordered, or invented --
    deciding which facts matter belongs to a later phase.
    """
    facts = [
        {"kind": "wall_built", "tick": 20, "detail": {"nested": [1, 2]}},
        {"kind": "wall_built", "tick": 20, "detail": {"nested": [1, 2]}},
        "a bare string fact",
        [1, 2, 3],
        None,
    ]
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manager.save_episode(
            minimal_world(), EventLog(), world_memory={"facts": facts, "schema_version": 1}
        )
        loaded = manager.load_episode(0)

        assert list(loaded.world_memory["facts"]) == facts
        assert len(loaded.world_memory["facts"]) == 5, "duplicates are kept, not merged"


def test_the_loaded_memory_document_is_detached_and_read_only() -> None:
    """Editing what a load returned must not reach the save or a later load."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manager.save_episode(
            minimal_world(), EventLog(), world_memory={"facts": [{"k": 1}], "schema_version": 1}
        )
        loaded = manager.load_episode(0)

        with pytest.raises(TypeError):
            loaded.world_memory["facts"] = []  # type: ignore[index]

        loaded.world_memory["facts"][0]["k"] = 99  # type: ignore[index]
        assert manager.load_episode(0).world_memory["facts"][0]["k"] == 1  # type: ignore[index]


@pytest.mark.parametrize(
    "bad",
    [
        {"facts": []},
        {"schema_version": 1},
        {"facts": [], "schema_version": 2},
        {"facts": [], "schema_version": 1, "extra": True},
        {"facts": {}, "schema_version": 1},
        {"facts": [{1, 2}], "schema_version": 1},
        {"facts": [float("nan")], "schema_version": 1},
    ],
)
def test_an_invalid_memory_document_is_refused(bad: dict) -> None:
    """The reserved shape is exact, and nothing is repaired into it."""
    with temporary_save_root() as root:
        with pytest.raises((TypeError, ValueError)):
            SaveManager(root).save_episode(minimal_world(), EventLog(), world_memory=bad)
        assert not (root / "episode_000").exists()


# --- Lineage across three episodes ------------------------------------------


def test_three_episodes_form_a_verified_chain() -> None:
    """Each link is established from a verified parent, not a claimed one."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifests = [
            manager.save_episode(rich_world(episode=number, tick=20 + number), rich_event_log())
            for number in range(3)
        ]

        assert manifests[0].parent_state_hash is None
        assert manifests[1].parent_state_hash == manifests[0].state_hash
        assert manifests[2].parent_state_hash == manifests[1].state_hash
        manager.verify_lineage(0, 1)
        manager.verify_lineage(1, 2)


def test_earlier_episodes_are_byte_identical_after_later_saves() -> None:
    """Hashed before and after, because the lineage claim depends on it."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manager.save_episode(rich_world(episode=0), rich_event_log())
        first = {path.name: path.read_bytes() for path in sorted((root / "episode_000").iterdir())}

        manager.save_episode(rich_world(episode=1, tick=21), rich_event_log())
        manager.save_episode(rich_world(episode=2, tick=22), rich_event_log())

        after = {path.name: path.read_bytes() for path in sorted((root / "episode_000").iterdir())}
        assert after == first


def test_a_child_pointing_at_the_wrong_parent_is_detected() -> None:
    """A rewritten lineage claim does not survive verification."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manager.save_episode(rich_world(episode=0), rich_event_log())
        manager.save_episode(rich_world(episode=1, tick=21), rich_event_log())
        manager.save_episode(rich_world(episode=2, tick=22), rich_event_log())

        with pytest.raises(ValueError):
            manager.verify_lineage(0, 2)


# --- Determinism across interpreters ----------------------------------------

_HASH_SEED_SCRIPT = """
import sys
sys.path.insert(0, {src!r})
sys.path.insert(0, {tests!r})
from persistence.conftest import rich_event_log, rich_world
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.persistence.serializers.event_serializer import serialize_event_log
from living_diorama.persistence.serializers.world_serializer import serialize_world

world = rich_world()
print(sha256_hex(dumps_canonical(serialize_world(world))))
print(sha256_hex(dumps_canonical(serialize_event_log(rich_event_log(), 0, world.tick))))
"""
"""Recomputes both payload hashes in a fresh interpreter."""


def _hashes_under_seed(seed: str, repository: Path) -> tuple[str, str]:
    """Return the two payload hashes computed under one PYTHONHASHSEED."""
    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = seed
    script = _HASH_SEED_SCRIPT.format(src=str(repository / "src"), tests=str(repository / "tests"))
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=environment,
        check=True,
    )
    first, second = completed.stdout.split()
    return first, second


def test_hashes_are_identical_under_several_hash_seeds() -> None:
    """Randomized string hashing must not reach the bytes on disk.

    Each seed runs in its own interpreter, because ``PYTHONHASHSEED`` is fixed
    at startup and cannot be changed from inside a running process.
    """
    repository = Path(__file__).resolve().parents[2]
    results = {seed: _hashes_under_seed(seed, repository) for seed in ("0", "1", "42", "123456")}
    assert len(set(results.values())) == 1, results


def test_manifest_bytes_are_stable_apart_from_the_recorded_python_version() -> None:
    """Everything except the recorded interpreter version is state-determined."""
    with temporary_save_root() as first_root, temporary_save_root() as second_root:
        SaveManager(first_root).save_episode(rich_world(), rich_event_log())
        SaveManager(second_root).save_episode(rich_world(), rich_event_log())

        first = loads_canonical((first_root / "episode_000" / MANIFEST_FILE).read_bytes())
        second = loads_canonical((second_root / "episode_000" / MANIFEST_FILE).read_bytes())
        assert first == second

        del first["python_version"]  # type: ignore[union-attr]
        assert "python_version" not in json.dumps(first)


def test_no_platform_specific_path_appears_inside_a_save() -> None:
    """A save must not record where it happened to be written."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manager.save_episode(rich_world(), rich_event_log())
        for path in sorted((root / "episode_000").iterdir()):
            text = path.read_text(encoding="utf-8")
            assert str(root) not in text
            assert "/tmp" not in text
            assert "\\\\" not in text


def test_no_generated_save_is_left_in_the_repository() -> None:
    """Tests write to temporary roots only; the tracked saves stay empty."""
    repository = Path(__file__).resolve().parents[2]
    saves = repository / "saves"
    if saves.exists():
        assert sorted(path.name for path in saves.iterdir()) == [".gitkeep"]


# --- Edge cases -------------------------------------------------------------


def test_an_empty_world_and_empty_log_round_trip() -> None:
    """Episode zero of a world that has not started yet is still a save."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        world = minimal_world()
        manifest = manager.save_episode(world, EventLog())
        loaded = manager.load_episode(0)

        assert manifest.event_count == 0
        assert structural_state(loaded.world) == structural_state(world)


def test_large_but_valid_values_round_trip() -> None:
    """Extreme representable numbers are state, not corruption."""
    with temporary_save_root() as root:
        world = minimal_world()
        district = world.districts["district_a"]
        district.population = 2**62
        district.housing_capacity = 2**62
        district.production_rate = 1e308
        district.consumption_rate = 5e-324

        manager = SaveManager(root)
        manager.save_episode(world, EventLog())
        restored = manager.load_episode(0).world.districts["district_a"]

        assert restored.population == 2**62
        assert restored.production_rate == 1e308
        assert restored.consumption_rate == 5e-324


def test_a_high_episode_number_requires_its_parent_like_any_other() -> None:
    """Episode 1000 is not special: it still cannot exist without episode 999."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        with pytest.raises(FileNotFoundError):
            manager.save_episode(minimal_world(episode=1000), EventLog())
        assert not (root / "episode_1000").exists()
        assert list(root.iterdir()) == []


def test_the_parent_requirement_holds_for_every_episode_number() -> None:
    """There is no shortcut into the middle of a lineage.

    Episode 1000 requires 999, which requires 998, and so on. That is the point:
    a save cannot claim descent from history that was never written down.
    """
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manager.save_episode(minimal_world(episode=0, tick=1), EventLog())
        manager.save_episode(minimal_world(episode=1, tick=2), EventLog())

        with pytest.raises(FileNotFoundError):
            manager.save_episode(minimal_world(episode=3, tick=4), EventLog())

        assert sorted(entry.name for entry in root.iterdir()) == [
            "episode_000",
            "episode_001",
        ]


def test_resource_amounts_survive_at_full_precision() -> None:
    """A float that is written must load back bit-for-bit."""
    with temporary_save_root() as root:
        from living_diorama.entities import ResourcePool  # noqa: PLC0415

        world = minimal_world()
        world.districts["district_a"].resources = ResourcePool(
            stock={
                ResourceType.FOOD: 0.1 + 0.2,
                ResourceType.MATERIALS: 1e-300,
                ResourceType.ENERGY: 12345.678901234567,
            }
        )
        expected = {
            resource: world.districts["district_a"].resources.amount_of(resource)
            for resource in ResourceType
        }

        manager = SaveManager(root)
        manager.save_episode(world, EventLog())
        restored = manager.load_episode(0).world.districts["district_a"].resources

        for resource, amount in expected.items():
            assert restored.amount_of(resource) == amount
