"""Tests for SaveManager: directories, atomicity, immutability, and corruption.

A published episode is the only thing standing between one episode and the
next. Most of these tests are about what must *not* happen: a partial directory
appearing, an earlier episode changing, or a tampered file loading as though it
were intact.
"""

import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path
from types import MappingProxyType

import pytest

from living_diorama.entities import Boundary, Law, Wall
from living_diorama.events import Event, EventLog, EventType
from living_diorama.memory import MemoryFact, MemorySignificance, WorldMemory
from living_diorama.persistence import (
    EpisodeManifest,
    FileMetadata,
    LoadedEpisode,
    SaveManager,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    ENTITY_COUNT_KEYS,
    EVENT_LOG_FILE,
    MANIFEST_FILE,
    WORLD_MEMORY_FILE,
    WORLD_STATE_FILE,
    episode_directory_name,
)
from living_diorama.persistence.serializers.world_serializer import serialize_world
from living_diorama.simulation.world import World
from persistence.conftest import (
    build_district,
    build_law,
    build_wall,
    consumed_rng,
    empty_memory,
    memory_for,
    minimal_world,
    quiet_log,
    rich_event_log,
    rich_world,
    save_episode,
    structural_state,
    temporary_save_root,
)

PAYLOADS = (EVENT_LOG_FILE, WORLD_MEMORY_FILE, WORLD_STATE_FILE)
"""The three hashed files, which every corruption test walks over."""


def require_symlink_support(
    root: Path,
    *,
    target_is_directory: bool = False,
) -> None:
    """Skip a symlink test when the host cannot create symbolic links."""
    target = root / ".symlink_probe_target"
    link = root / ".symlink_probe"

    if target_is_directory:
        target.mkdir()
    else:
        target.write_bytes(b"symlink probe")

    try:
        link.symlink_to(
            target,
            target_is_directory=target_is_directory,
        )
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is unavailable on this host: {exc}")
    finally:
        link.unlink(missing_ok=True)

        if target_is_directory:
            target.rmdir()
        else:
            target.unlink(missing_ok=True)


def symlink_target(link: Path) -> str:
    r"""Return a symlink's stored target, normalized for comparison.

    On Windows ``os.readlink`` may report the substitute name, which carries
    the ``\\?\`` extended-length prefix. The assertions below compare against
    the path the test created the link with, and the prefix is representation,
    not meaning: the link still points at exactly the same target.
    """
    return os.readlink(link).removeprefix("\\\\?\\")


def directory_fingerprint(directory: Path) -> dict[str, bytes]:
    """Return every file in a directory keyed by name, for byte comparison."""
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


def save_rich(manager: SaveManager, *, episode: int = 0, tick: int = 20):
    """Save a rich world at the given episode and return its manifest."""
    log = rich_event_log() if episode == 0 else quiet_log()
    return save_episode(manager, rich_world(episode=episode, tick=tick), log)


# --- Directory contract -----------------------------------------------------


@pytest.mark.parametrize(
    "episode,expected",
    [(0, "episode_000"), (1, "episode_001"), (42, "episode_042"), (1000, "episode_1000")],
)
def test_episode_directories_are_zero_padded(episode: int, expected: str) -> None:
    """Three-digit padding that simply grows past a thousand."""
    assert episode_directory_name(episode) == expected


@pytest.mark.parametrize("bad", [True, False, 1.0, "0", None])
def test_a_non_integer_episode_number_is_refused(bad: object) -> None:
    """``bool`` is not an episode number, however neatly it formats."""
    with pytest.raises(TypeError):
        episode_directory_name(bad)  # type: ignore[arg-type]


def test_a_negative_episode_number_is_refused() -> None:
    """There is no episode before the first one."""
    with pytest.raises(ValueError):
        episode_directory_name(-1)


def test_a_saved_episode_holds_exactly_four_files() -> None:
    """No staging leftovers, no backups, no nested directories."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        assert sorted(path.name for path in directory.iterdir()) == [
            EVENT_LOG_FILE,
            MANIFEST_FILE,
            WORLD_MEMORY_FILE,
            WORLD_STATE_FILE,
        ]
        assert all(path.is_file() for path in directory.iterdir())
        assert sorted(entry.name for entry in root.iterdir()) == ["episode_000"]


def test_the_save_root_is_created_if_absent() -> None:
    """A first save should not require the caller to prepare the directory."""
    with temporary_save_root() as root:
        nested = root / "deeply" / "nested" / "saves"
        save_episode(SaveManager(nested), minimal_world(), EventLog())
        assert (nested / "episode_000").is_dir()


@pytest.mark.parametrize("bad", [1, None, b"path", ["saves"]])
def test_a_non_path_save_root_is_refused(bad: object) -> None:
    """The root is a filesystem location, not anything convertible to one."""
    with pytest.raises(TypeError):
        SaveManager(bad)  # type: ignore[arg-type]


# --- Manifest ---------------------------------------------------------------


def test_the_manifest_records_the_expected_shape() -> None:
    """Every field a reader needs, and no timestamp anywhere."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifest = save_rich(manager)
        document = loads_canonical((root / "episode_000" / MANIFEST_FILE).read_bytes())

        assert sorted(document) == [
            "engine_version",
            "entity_counts",
            "episode",
            "event_count",
            "files",
            "format",
            "parent_state_hash",
            "python_version",
            "schema_version",
            "state_hash",
            "tick",
        ]
        assert document["format"] == "living_diorama_episode"
        assert document["schema_version"] == 1
        assert document["episode"] == 0
        assert document["tick"] == 20
        assert document["parent_state_hash"] is None
        assert sorted(document["files"]) == sorted(PAYLOADS)
        assert manifest.state_hash == document["state_hash"]

        text = json.dumps(document)
        for forbidden in ("timestamp", "created_at", "saved_at", "time"):
            assert forbidden not in text


def test_the_state_hash_is_the_world_state_file_hash() -> None:
    """One canonical definition, so nothing can disagree about what was saved."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifest = save_rich(manager)
        data = (root / "episode_000" / WORLD_STATE_FILE).read_bytes()

        assert manifest.state_hash == sha256_hex(data)
        assert manifest.state_hash == manifest.files[WORLD_STATE_FILE].sha256


def test_every_payload_hash_and_length_is_recorded_correctly() -> None:
    """Verification on load has something exact to compare against."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifest = save_rich(manager)
        for name in PAYLOADS:
            data = (root / "episode_000" / name).read_bytes()
            assert manifest.files[name].sha256 == sha256_hex(data)
            assert manifest.files[name].bytes == len(data)


def test_the_manifest_counts_match_the_world() -> None:
    """Counts are a cheap cross-check that the payload is the one described."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        world = rich_world()
        manifest = save_episode(manager, world, rich_event_log())
        assert manifest.entity_counts["districts"] == len(world.districts)
        assert manifest.entity_counts["walls"] == len(world.walls)
        assert manifest.event_count == 3


def test_manifest_mappings_are_read_only() -> None:
    """Returned metadata cannot be edited into disagreeing with the disk."""
    with temporary_save_root() as root:
        manifest = save_rich(SaveManager(root))
        with pytest.raises(TypeError):
            manifest.entity_counts["districts"] = 99  # type: ignore[index]
        with pytest.raises(TypeError):
            manifest.files[WORLD_STATE_FILE] = None  # type: ignore[index]


# --- Round trip -------------------------------------------------------------


def test_a_saved_episode_loads_back() -> None:
    """The minimum success chain, end to end."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifest = save_rich(manager)
        loaded = manager.load_episode(0)

        assert loaded.world.tick == 20
        assert loaded.world.episode == 0
        assert len(loaded.event_log.events()) == 3
        assert loaded.manifest.state_hash == manifest.state_hash
        assert len(loaded.world_memory) == 1
        assert loaded.world_memory.through_episode == 0
        assert loaded.world_memory.through_tick == 20


def test_loading_writes_nothing() -> None:
    """A read must leave the episode byte-for-byte as it was."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        before = directory_fingerprint(directory)

        manager.load_episode(0)
        manager.load_episode(0)

        assert directory_fingerprint(directory) == before


def test_loading_an_absent_episode_reports_it_as_missing() -> None:
    """A missing episode is a missing file, not a malformed one."""
    with temporary_save_root() as root, pytest.raises(FileNotFoundError):
        SaveManager(root).load_episode(3)


# --- Immutability -----------------------------------------------------------


def test_saving_over_an_existing_episode_is_refused() -> None:
    """Published episodes are never merged into, repaired, or overwritten."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        before = directory_fingerprint(root / "episode_000")

        with pytest.raises(FileExistsError):
            save_rich(manager)

        assert directory_fingerprint(root / "episode_000") == before


def test_saving_a_later_episode_leaves_the_earlier_one_untouched() -> None:
    """The parent's bytes are what the child's lineage claim rests on."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager, episode=0)
        before = directory_fingerprint(root / "episode_000")

        save_rich(manager, episode=1, tick=25)

        assert directory_fingerprint(root / "episode_000") == before


def test_a_failed_save_leaves_no_directory_and_no_staging_behind() -> None:
    """Validation failure must not publish anything, not even an empty folder."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        broken = rich_world()
        broken.districts["district_a"].scarcity = 1.5

        with pytest.raises(ValueError):
            save_episode(manager, broken, rich_event_log())

        assert not (root / "episode_000").exists()
        assert list(root.iterdir()) == []


def test_a_failed_later_save_leaves_earlier_episodes_intact() -> None:
    """One bad episode cannot damage the history behind it."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager, episode=0)
        before = directory_fingerprint(root / "episode_000")

        broken = rich_world(episode=1, tick=21)
        broken.districts["district_a"].population = True
        with pytest.raises((TypeError, ValueError)):
            save_episode(manager, broken, quiet_log())

        assert directory_fingerprint(root / "episode_000") == before
        assert not (root / "episode_001").exists()
        assert sorted(entry.name for entry in root.iterdir()) == ["episode_000"]


def test_a_destination_that_appears_mid_save_is_not_overwritten() -> None:
    """The staged directory is discarded rather than published over a rival.

    Simulated by pre-creating a non-empty destination, which is what a
    completed episode always is.
    """
    with temporary_save_root() as root:
        manager = SaveManager(root)
        destination = root / "episode_000"
        destination.mkdir(parents=True)
        (destination / "already_here.json").write_bytes(b"{}\n")

        with pytest.raises(FileExistsError):
            save_rich(manager)

        assert sorted(path.name for path in destination.iterdir()) == ["already_here.json"]


def test_a_filesystem_failure_publishes_nothing() -> None:
    """A save root that cannot hold directories fails without leaving anything.

    Injected by pointing the root at a regular file, which is deterministic
    everywhere -- unlike permission tricks, which do nothing when the tests run
    as a user the filesystem does not restrict.
    """
    with temporary_save_root() as root:
        blocked = root / "not_a_directory"
        blocked.write_text("{}", encoding="utf-8")

        with pytest.raises(OSError):
            save_episode(SaveManager(blocked), rich_world(), rich_event_log())

        assert blocked.read_text(encoding="utf-8") == "{}"


def test_a_failure_after_staging_removes_the_staging_directory() -> None:
    """Files are written before publication, and a late failure must clean up.

    The failure is injected at the staged-file verification step, which is the
    last thing that happens while a partly written directory exists.
    """
    with temporary_save_root() as root:
        manager = SaveManager(root)
        original = SaveManager.__dict__["_verify_staged"]

        def explode(staging: Path, documents: object) -> None:
            """Stand in for verification and fail once files exist on disk."""
            assert sorted(path.name for path in staging.iterdir()) == [
                EVENT_LOG_FILE,
                MANIFEST_FILE,
                WORLD_MEMORY_FILE,
                WORLD_STATE_FILE,
            ], "the failure must be injected after every file was written"
            raise ValueError("injected staging failure")

        SaveManager._verify_staged = staticmethod(explode)  # type: ignore[method-assign]
        try:
            with pytest.raises(ValueError):
                save_rich(manager)
        finally:
            # Restored as the staticmethod object it was; assigning the plain
            # function back would rebind it as an instance method.
            SaveManager._verify_staged = original  # type: ignore[method-assign]

        assert not (root / "episode_000").exists()
        assert list(root.iterdir()) == [], "no staging directory may survive"


def test_a_publication_failure_preserves_the_original_cause() -> None:
    """Cleanup must not replace the error that actually stopped the save."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        module = sys.modules[SaveManager.__module__]
        original = module._rename_no_replace

        def refuse(source: object, destination: object) -> None:
            """Stand in for the publication step and fail."""
            raise OSError("injected publication failure")

        module._rename_no_replace = refuse
        try:
            with pytest.raises(OSError, match="injected publication failure"):
                save_rich(manager)
        finally:
            module._rename_no_replace = original

        assert not (root / "episode_000").exists()
        assert list(root.iterdir()) == [], "no staging directory may survive"


# --- Lineage ----------------------------------------------------------------


def test_episode_zero_has_no_parent() -> None:
    """The first episode begins the lineage."""
    with temporary_save_root() as root:
        assert save_rich(SaveManager(root)).parent_state_hash is None


def test_each_episode_points_at_its_verified_parent() -> None:
    """The parent hash is taken from a verified load, never from the caller."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        first = save_rich(manager, episode=0)
        second = save_rich(manager, episode=1, tick=25)
        third = save_rich(manager, episode=2, tick=30)

        assert second.parent_state_hash == first.state_hash
        assert third.parent_state_hash == second.state_hash
        manager.verify_lineage(0, 1)
        manager.verify_lineage(1, 2)


def test_saving_an_episode_without_its_parent_is_refused() -> None:
    """A lineage with a hole in it proves nothing about where the world came from."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        with pytest.raises(FileNotFoundError):
            save_rich(manager, episode=1)
        assert list(root.iterdir()) == []


def test_non_consecutive_lineage_is_refused() -> None:
    """Episode two does not directly follow episode zero."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager, episode=0)
        save_rich(manager, episode=1, tick=25)
        save_rich(manager, episode=2, tick=30)
        with pytest.raises(ValueError):
            manager.verify_lineage(0, 2)


def test_a_mismatched_parent_hash_is_refused_without_touching_the_files() -> None:
    """A tampered lineage claim fails and changes nothing on disk."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager, episode=0)
        save_rich(manager, episode=1, tick=25)

        child = root / "episode_001"
        document = loads_canonical((child / MANIFEST_FILE).read_bytes())
        document["parent_state_hash"] = "0" * 64
        (child / MANIFEST_FILE).write_bytes(dumps_canonical(document))
        before = directory_fingerprint(child)

        with pytest.raises(ValueError):
            manager.verify_lineage(0, 1)
        assert directory_fingerprint(child) == before


def test_a_malformed_parent_hash_is_refused() -> None:
    """A parent hash must look like a digest before it can be compared."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager, episode=0)
        save_rich(manager, episode=1, tick=25)

        child = root / "episode_001"
        document = loads_canonical((child / MANIFEST_FILE).read_bytes())
        document["parent_state_hash"] = "not-a-hash"
        (child / MANIFEST_FILE).write_bytes(dumps_canonical(document))

        with pytest.raises(ValueError):
            manager.load_episode(1)


@pytest.mark.parametrize("bad", [True, 1.0, "1", None])
def test_lineage_requires_integer_episode_numbers(bad: object) -> None:
    """Episode numbers are exact ints on this path too."""
    with temporary_save_root() as root, pytest.raises(TypeError):
        SaveManager(root).verify_lineage(bad, 1)  # type: ignore[arg-type]


# --- Corruption detection ---------------------------------------------------


@pytest.mark.parametrize("name", PAYLOADS)
def test_a_tampered_payload_is_detected(name: str) -> None:
    """Any edit to a hashed file breaks its digest."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        path = root / "episode_000" / name
        path.write_bytes(path.read_bytes().replace(b"1", b"2", 1))

        with pytest.raises(ValueError):
            manager.load_episode(0)


@pytest.mark.parametrize("name", PAYLOADS)
def test_a_reformatted_payload_is_detected(name: str) -> None:
    """Semantically identical is not byte-identical, and the hash knows."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        path = root / "episode_000" / name
        document = loads_canonical(path.read_bytes())
        path.write_bytes(json.dumps(document, indent=2).encode("utf-8") + b"\n")

        with pytest.raises(ValueError):
            manager.load_episode(0)


@pytest.mark.parametrize("name", PAYLOADS)
def test_a_truncated_payload_is_detected(name: str) -> None:
    """A short read fails on length before it can fail on parsing."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        path = root / "episode_000" / name
        path.write_bytes(path.read_bytes()[:-5])

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_an_incorrect_recorded_length_is_detected() -> None:
    """The manifest's own claim is checked, not trusted."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        document = loads_canonical((directory / MANIFEST_FILE).read_bytes())
        document["files"][WORLD_STATE_FILE]["bytes"] += 1
        (directory / MANIFEST_FILE).write_bytes(dumps_canonical(document))

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_an_incorrect_state_hash_is_detected() -> None:
    """A manifest whose two views of the state disagree is refused."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        document = loads_canonical((directory / MANIFEST_FILE).read_bytes())
        document["state_hash"] = "0" * 64
        (directory / MANIFEST_FILE).write_bytes(dumps_canonical(document))

        with pytest.raises(ValueError):
            manager.load_episode(0)


@pytest.mark.parametrize("field,value", [("episode", 5), ("tick", 999)])
def test_manifest_metadata_disagreeing_with_the_world_is_detected(field: str, value: int) -> None:
    """Cross-checks catch a manifest describing a different world."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        document = loads_canonical((directory / MANIFEST_FILE).read_bytes())
        document[field] = value
        (directory / MANIFEST_FILE).write_bytes(dumps_canonical(document))

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_an_incorrect_entity_count_is_detected() -> None:
    """A count that disagrees with the payload means one of them is wrong."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        document = loads_canonical((directory / MANIFEST_FILE).read_bytes())
        document["entity_counts"]["districts"] += 1
        (directory / MANIFEST_FILE).write_bytes(dumps_canonical(document))

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_an_incorrect_event_count_is_detected() -> None:
    """The same cross-check for the history."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        document = loads_canonical((directory / MANIFEST_FILE).read_bytes())
        document["event_count"] = 99
        (directory / MANIFEST_FILE).write_bytes(dumps_canonical(document))

        with pytest.raises(ValueError):
            manager.load_episode(0)


@pytest.mark.parametrize("field,value", [("format", "something_else"), ("schema_version", 2)])
def test_an_unsupported_format_or_version_is_refused(field: str, value: object) -> None:
    """Neither is guessed at; both fail explicitly."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        document = loads_canonical((directory / MANIFEST_FILE).read_bytes())
        document[field] = value
        (directory / MANIFEST_FILE).write_bytes(dumps_canonical(document))

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_a_manifest_with_an_unexpected_key_is_refused() -> None:
    """An unknown key may carry meaning this build would ignore."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        document = loads_canonical((directory / MANIFEST_FILE).read_bytes())
        document["surprise"] = True
        (directory / MANIFEST_FILE).write_bytes(dumps_canonical(document))

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_duplicate_json_keys_in_a_save_file_are_refused() -> None:
    """Python would keep the last one and silently drop the first."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        path = root / "episode_000" / MANIFEST_FILE
        path.write_bytes(b'{"episode":0,"episode":1}\n')

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_a_missing_file_is_detected() -> None:
    """An incomplete directory is never completed by assumption."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        (root / "episode_000" / EVENT_LOG_FILE).unlink()

        with pytest.raises(FileNotFoundError):
            manager.load_episode(0)


def test_an_extra_file_is_detected() -> None:
    """Something else has been in the directory, which is worth refusing over."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        (root / "episode_000" / "notes.txt").write_text("hello", encoding="utf-8")

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_a_subdirectory_is_detected() -> None:
    """An episode directory holds files only."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        (root / "episode_000" / "backup").mkdir()

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_a_symlinked_required_file_is_refused() -> None:
    """A link can point anywhere, including outside the save root."""
    with temporary_save_root() as root:
        require_symlink_support(root)
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        target = root / "elsewhere.json"
        target.write_bytes((directory / EVENT_LOG_FILE).read_bytes())
        (directory / EVENT_LOG_FILE).unlink()
        (directory / EVENT_LOG_FILE).symlink_to(target)

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_a_symlinked_episode_directory_is_refused() -> None:
    """The directory itself gets the same treatment.

    Built as a real chain so the walk actually reaches the symlinked episode.
    Pointing a far-off episode number at an existing directory would fail
    earlier, on the ancestors that do not exist.
    """
    with temporary_save_root() as root:
        require_symlink_support(root, target_is_directory=True)
        manager = SaveManager(root)
        save_episode(manager, minimal_world(episode=0, tick=1), EventLog())
        save_episode(manager, minimal_world(episode=1, tick=2), EventLog())
        shutil.rmtree(root / "episode_001")
        (root / "episode_001").symlink_to(root / "episode_000", target_is_directory=True)

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_an_episode_path_that_is_a_file_is_refused() -> None:
    """A file where a directory belongs is not an episode."""
    with temporary_save_root() as root:
        (root).mkdir(parents=True, exist_ok=True)
        (root / "episode_000").write_text("{}", encoding="utf-8")

        with pytest.raises(ValueError):
            SaveManager(root).load_episode(0)


# --- Correction 1: an event may not postdate the world being saved ----------
#
# Candidate V1 wrote such an episode happily and then refused to load it. A
# writer and a reader that disagree produce a save whose only symptom appears
# when the next episode tries to resume from it.


def snapshot_inputs(world: object, event_log: EventLog, memory: object) -> tuple:
    """Capture everything a save is forbidden to touch."""
    from persistence.conftest import structural_state  # noqa: PLC0415

    return (
        structural_state(world),  # type: ignore[arg-type]
        event_log.events(),
        world.rng.get_state(),  # type: ignore[attr-defined]
        memory,
    )


def test_an_event_exactly_at_the_world_tick_saves() -> None:
    """The wall built this tick belongs to this tick's history."""
    with temporary_save_root() as root:
        world = minimal_world(tick=7)
        log = EventLog()
        # A non-significant event: this test is about the tick boundary, and a
        # WALL_BUILT event would now also have to name a wall the world holds.
        log.append(Event(tick=7, type=EventType.SCARCITY_CHANGED, payload={}))

        manifest = save_episode(SaveManager(root), world, log)
        assert manifest.event_count == 1
        assert SaveManager(root).load_episode(0).event_log.events()[0].tick == 7


def test_an_event_after_the_world_tick_is_refused_before_anything_is_written() -> None:
    """The save fails, and leaves nothing at all behind."""
    with temporary_save_root() as root:
        world = minimal_world(tick=0)
        log = EventLog()
        log.append(Event(tick=1, type=EventType.WALL_BUILT, payload={}))
        memory = empty_memory(world)
        before = snapshot_inputs(world, log, memory)

        with pytest.raises(ValueError):
            save_episode(SaveManager(root), world, log, world_memory=memory)

        assert not (root / "episode_000").exists()
        assert list(root.iterdir()) == [], "no staging directory may survive"
        assert snapshot_inputs(world, log, memory) == before


def test_a_future_event_among_valid_ones_still_stops_the_save() -> None:
    """One bad event anywhere aborts the whole episode."""
    with temporary_save_root() as root:
        world = minimal_world(tick=5)
        log = EventLog()
        log.append(Event(tick=1, type=EventType.SCARCITY_CHANGED, payload={}))
        log.append(Event(tick=99, type=EventType.SCARCITY_CHANGED, payload={}))
        log.append(Event(tick=5, type=EventType.WALL_BUILT, payload={}))

        with pytest.raises(ValueError):
            save_episode(SaveManager(root), world, log)
        assert list(root.iterdir()) == []


def test_a_future_event_does_not_disturb_an_earlier_episode() -> None:
    """A rejected later save cannot damage the history behind it."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_episode(manager, minimal_world(episode=0, tick=1), EventLog())
        before = directory_fingerprint(root / "episode_000")

        log = EventLog()
        log.append(Event(tick=50, type=EventType.WALL_BUILT, payload={}))
        with pytest.raises(ValueError):
            save_episode(manager, minimal_world(episode=1, tick=2), log)

        assert directory_fingerprint(root / "episode_000") == before
        assert sorted(entry.name for entry in root.iterdir()) == ["episode_000"]


# --- Correction 2: load_episode verifies direct parent lineage --------------


def build_chain(manager: SaveManager, episodes: int = 3) -> list:
    """Save a valid chain of episodes and return their manifests."""
    return [
        save_episode(
            manager,
            rich_world(episode=number, tick=20 + number),
            rich_event_log() if number == 0 else quiet_log(),
        )
        for number in range(episodes)
    ]


def rewrite_manifest(directory: Path, **changes: object) -> None:
    """Rewrite a manifest with changed fields, rehashing nothing.

    The manifest is not covered by any digest, which is exactly why loading
    cannot take its word for the lineage.
    """
    document = loads_canonical((directory / MANIFEST_FILE).read_bytes())
    document.update(changes)  # type: ignore[union-attr]
    (directory / MANIFEST_FILE).write_bytes(dumps_canonical(document))


def test_a_valid_three_episode_chain_loads() -> None:
    """The control case: lineage verification must not reject a sound chain."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifests = build_chain(manager)
        for number in range(3):
            assert manager.load_episode(number).manifest.episode == number
        assert manifests[2].parent_state_hash == manifests[1].state_hash


def test_loading_rejects_a_missing_parent_folder() -> None:
    """An episode whose parent is gone describes a world from nowhere."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        build_chain(manager, 2)
        shutil.rmtree(root / "episode_000")

        with pytest.raises(FileNotFoundError):
            manager.load_episode(1)


def test_loading_rejects_a_null_parent_hash_after_episode_zero() -> None:
    """Only episode zero begins a lineage."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        build_chain(manager, 2)
        rewrite_manifest(root / "episode_001", parent_state_hash=None)

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_loading_rejects_a_non_null_parent_hash_on_episode_zero() -> None:
    """Episode zero claiming descent is equally wrong."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        build_chain(manager, 1)
        rewrite_manifest(root / "episode_000", parent_state_hash="b" * 64)

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_loading_rejects_a_wrong_but_well_formed_parent_hash() -> None:
    """The reported defect: a plausible hash is not a verified one."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        build_chain(manager, 2)
        rewrite_manifest(root / "episode_001", parent_state_hash="a" * 64)

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_loading_rejects_a_child_linked_to_its_grandparent() -> None:
    """Descent is from the episode directly before, not any earlier one."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifests = build_chain(manager, 3)
        rewrite_manifest(root / "episode_002", parent_state_hash=manifests[0].state_hash)

        with pytest.raises(ValueError):
            manager.load_episode(2)


def test_loading_rejects_a_child_whose_parent_payload_is_corrupt() -> None:
    """A parent that cannot be verified cannot vouch for anything."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        build_chain(manager, 2)
        path = root / "episode_000" / WORLD_STATE_FILE
        path.write_bytes(path.read_bytes().replace(b"0.0", b"0.5", 1))

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_loading_rejects_a_child_whose_parent_manifest_state_hash_is_wrong() -> None:
    """The parent's own claim about itself is checked before it is believed."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        build_chain(manager, 2)
        rewrite_manifest(root / "episode_000", state_hash="c" * 64)

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_a_failed_lineage_load_changes_nothing_on_disk() -> None:
    """Verification is a read, including when it fails."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        build_chain(manager, 2)
        rewrite_manifest(root / "episode_001", parent_state_hash="a" * 64)
        before = {
            name: directory_fingerprint(root / name) for name in ("episode_000", "episode_001")
        }

        with pytest.raises(ValueError):
            manager.load_episode(1)

        assert {
            name: directory_fingerprint(root / name) for name in ("episode_000", "episode_001")
        } == before


# --- Correction 4 and 5: atomic no-replace publication ----------------------


def stage_then_create(root: Path, create: object) -> None:
    """Run a save while a destination appears just before publication.

    The destination is created inside the publication primitive itself, which
    is the exact instant Candidate V1's check-then-rename could not cover.
    """
    manager = SaveManager(root)
    module = sys.modules[SaveManager.__module__]
    original = module._rename_no_replace

    def racing(source: Path, destination: Path) -> None:
        """Create the rival destination, then publish for real."""
        create(destination)  # type: ignore[operator]
        original(source, destination)

    module._rename_no_replace = racing
    try:
        with pytest.raises(FileExistsError):
            save_episode(manager, rich_world(), rich_event_log())
    finally:
        module._rename_no_replace = original


def test_a_destination_appearing_during_publication_is_not_replaced() -> None:
    """An empty directory is the case a plain rename would silently replace."""
    with temporary_save_root() as root:
        stage_then_create(root, lambda destination: destination.mkdir())

        assert (root / "episode_000").is_dir()
        assert list((root / "episode_000").iterdir()) == [], "the rival is untouched"
        assert sorted(entry.name for entry in root.iterdir()) == ["episode_000"], (
            "the staging directory must have been cleaned up"
        )


def test_a_non_empty_destination_appearing_during_publication_is_untouched() -> None:
    """Nothing inside a rival episode may be disturbed."""

    def create(destination: Path) -> None:
        """Create a rival directory holding a file."""
        destination.mkdir()
        (destination / "already_here.json").write_bytes(b"{}\n")

    with temporary_save_root() as root:
        stage_then_create(root, create)

        assert sorted(path.name for path in (root / "episode_000").iterdir()) == [
            "already_here.json"
        ]
        assert (root / "episode_000" / "already_here.json").read_bytes() == b"{}\n"


def test_a_file_appearing_at_the_destination_is_untouched() -> None:
    """A regular file where a directory belongs still blocks publication."""
    with temporary_save_root() as root:
        stage_then_create(root, lambda destination: destination.write_bytes(b"not an episode\n"))

        assert (root / "episode_000").is_file()
        assert (root / "episode_000").read_bytes() == b"not an episode\n"


def test_a_symlink_appearing_at_the_destination_is_untouched() -> None:
    """Including one pointing somewhere entirely outside the save root."""
    with temporary_save_root() as root:
        require_symlink_support(root, target_is_directory=True)
        target = root / "elsewhere"
        target.mkdir()
        stage_then_create(
            root,
            lambda destination: destination.symlink_to(
                target,
                target_is_directory=True,
            ),
        )

        assert (root / "episode_000").is_symlink()
        assert symlink_target(root / "episode_000") == str(target)


def test_a_broken_symlink_destination_is_refused_up_front() -> None:
    """``Path.exists`` reports a broken symlink as absent; ``lexists`` does not.

    Candidate V1 missed it here and leaked an unrelated filesystem error later.
    """
    with temporary_save_root() as root:
        require_symlink_support(root)
        destination = root / "episode_000"
        destination.symlink_to(root / "no_such_target")

        with pytest.raises(FileExistsError):
            save_episode(SaveManager(root), rich_world(), rich_event_log())

        assert destination.is_symlink()
        assert symlink_target(destination) == str(root / "no_such_target")
        assert not destination.exists(), "still broken, still untouched"
        assert sorted(entry.name for entry in root.iterdir()) == ["episode_000"]


def test_a_broken_symlink_appearing_during_publication_is_untouched() -> None:
    """The same case, arriving in the race window instead."""
    with temporary_save_root() as root:
        require_symlink_support(root)
        stage_then_create(root, lambda destination: destination.symlink_to(root / "no_such_target"))

        assert (root / "episode_000").is_symlink()
        assert symlink_target(root / "episode_000") == str(root / "no_such_target")


def test_the_publication_primitive_refuses_every_kind_of_existing_entry() -> None:
    """Exercised directly, since some cases cannot be reached through a save."""
    module = sys.modules[SaveManager.__module__]
    with temporary_save_root() as root:
        require_symlink_support(root)
        for index, create in enumerate(
            (
                lambda path: path.mkdir(),
                lambda path: path.write_bytes(b"x"),
                lambda path: path.symlink_to(root / "missing"),
            )
        ):
            source = root / f"staging_{index}"
            source.mkdir()
            destination = root / f"destination_{index}"
            create(destination)

            with pytest.raises(FileExistsError):
                module._rename_no_replace(source, destination)
            assert source.is_dir(), "the staged directory is left for cleanup"


def test_publication_does_not_use_a_replacing_rename() -> None:
    """Read from the source, so the guarantee cannot quietly regress.

    ``os.rename`` replaces an empty destination directory on POSIX, which is
    the behaviour this phase forbids. The only ``os.rename`` left in the module
    is the Windows branch, where the call is natively no-replace.
    """
    import ast  # noqa: PLC0415

    source = Path(sys.modules[SaveManager.__module__].__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    publish = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_publish"
    )
    calls = {
        node.func.attr
        for node in ast.walk(publish)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "rename" not in calls, "_publish must not call os.rename directly"
    assert "_rename_no_replace" in source


# --- Correction 7: the manifest validates exact types, not just equality ----


def build_manifest(**changes: object) -> EpisodeManifest:
    """Build a manifest with one or more fields replaced."""
    metadata = FileMetadata(sha256="0" * 64, bytes=1)
    fields: dict = {
        "format": "living_diorama_episode",
        "schema_version": 1,
        "engine_version": "0.0.1",
        "python_version": "3.13.0",
        "episode": 0,
        "tick": 0,
        "state_hash": "0" * 64,
        "parent_state_hash": None,
        "event_count": 0,
        "entity_counts": MappingProxyType(dict.fromkeys(ENTITY_COUNT_KEYS, 0)),
        "files": MappingProxyType(dict.fromkeys(PAYLOADS, metadata)),
    }
    fields.update(changes)
    return EpisodeManifest(**fields)


def test_a_valid_manifest_is_accepted() -> None:
    """The control case for the exact-type checks below."""
    manifest = build_manifest()
    assert manifest.schema_version == 1
    assert type(manifest.schema_version) is int


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", None])
def test_a_mistyped_schema_version_is_refused(bad: object) -> None:
    """``True == 1``, so an equality-only check would have accepted a bool.

    Candidate V1 did exactly that and would then have written ``true`` back out
    as the schema version.
    """
    with pytest.raises(TypeError):
        build_manifest(schema_version=bad)


@pytest.mark.parametrize("bad", [0, 2, 99])
def test_an_unsupported_exact_schema_version_is_refused(bad: int) -> None:
    """A real integer this build does not understand still fails."""
    with pytest.raises(ValueError):
        build_manifest(schema_version=bad)


def test_episode_zero_may_not_record_a_parent() -> None:
    """The first episode begins the lineage; it descends from nothing."""
    with pytest.raises(ValueError):
        build_manifest(episode=0, parent_state_hash="a" * 64)


def test_a_later_episode_must_record_a_parent() -> None:
    """A null parent past episode zero is a lineage with a hole in it."""
    with pytest.raises(ValueError):
        build_manifest(episode=1, parent_state_hash=None)


def test_a_later_episode_with_a_malformed_parent_hash_is_refused() -> None:
    """The recorded hash has to look like a digest before it can be compared."""
    with pytest.raises(ValueError):
        build_manifest(episode=1, parent_state_hash="not-a-hash")


def test_a_later_episode_with_a_valid_parent_hash_is_accepted() -> None:
    """The control case for the lineage field."""
    manifest = build_manifest(episode=1, parent_state_hash="b" * 64)
    assert manifest.parent_state_hash == "b" * 64


@pytest.mark.parametrize("field", ["episode", "tick", "event_count"])
@pytest.mark.parametrize("bad", [True, False, 1.0, "1"])
def test_mistyped_manifest_counters_are_refused(field: str, bad: object) -> None:
    """Every integer field is checked for exact type, not merely compared."""
    with pytest.raises(TypeError):
        build_manifest(**{field: bad})


@pytest.mark.parametrize("bad", [True, 1.0, "0"])
def test_a_mistyped_entity_count_is_refused(bad: object) -> None:
    """Including the counts nested inside the manifest."""
    counts = dict.fromkeys(ENTITY_COUNT_KEYS, 0)
    counts["districts"] = bad  # type: ignore[assignment]
    with pytest.raises(TypeError):
        build_manifest(entity_counts=MappingProxyType(counts))


@pytest.mark.parametrize("bad", [True, 1.0, "1", None])
def test_a_mistyped_file_length_is_refused(bad: object) -> None:
    """A recorded byte length is an exact integer too."""
    with pytest.raises(TypeError):
        FileMetadata(sha256="0" * 64, bytes=bad)  # type: ignore[arg-type]


def test_a_manifest_document_with_a_boolean_schema_version_is_refused() -> None:
    """The same rule when the value arrives from a file rather than in memory."""
    document = build_manifest().to_document()
    document["schema_version"] = True
    with pytest.raises(TypeError):
        EpisodeManifest.from_document(document)


# --- Canonical-byte hardening -----------------------------------------------
#
# Hashes catch a payload that was reformatted and left with its old digest, but
# not one that was reformatted and had the manifest updated to match. Nothing
# authenticates the manifest, so the loader re-encodes every parsed document and
# requires the same bytes back.


def rehash_manifest(directory: Path) -> None:
    """Recompute every payload digest and length, as a tamperer would."""
    document = loads_canonical((directory / MANIFEST_FILE).read_bytes())
    for name in PAYLOADS:
        data = (directory / name).read_bytes()
        document["files"][name] = {"bytes": len(data), "sha256": sha256_hex(data)}
    document["state_hash"] = sha256_hex((directory / WORLD_STATE_FILE).read_bytes())
    (directory / MANIFEST_FILE).write_bytes(dumps_canonical(document))


@pytest.mark.parametrize("name", PAYLOADS)
def test_a_rehashed_pretty_printed_payload_is_refused(name: str) -> None:
    """Updating the digests does not make noncanonical bytes acceptable."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        document = loads_canonical((directory / name).read_bytes())
        (directory / name).write_bytes(json.dumps(document, indent=2).encode("utf-8") + b"\n")
        rehash_manifest(directory)

        with pytest.raises(ValueError):
            manager.load_episode(0)


@pytest.mark.parametrize("name", PAYLOADS)
def test_a_rehashed_payload_with_noncanonical_key_order_is_refused(name: str) -> None:
    """Sorted keys are part of the format, not a formatting preference."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        document = loads_canonical((directory / name).read_bytes())
        reordered = json.dumps(document, sort_keys=False, ensure_ascii=False, separators=(",", ":"))
        shuffled = json.dumps(
            dict(reversed(list(document.items()))),  # type: ignore[union-attr]
            ensure_ascii=False,
            separators=(",", ":"),
        )
        chosen = shuffled if shuffled != reordered else reordered
        (directory / name).write_bytes(chosen.encode("utf-8") + b"\n")
        rehash_manifest(directory)

        if (directory / name).read_bytes() == dumps_canonical(document, name):
            return  # a single-key document has only one ordering
        with pytest.raises(ValueError):
            manager.load_episode(0)


@pytest.mark.parametrize("name", PAYLOADS)
def test_a_rehashed_payload_missing_its_trailing_newline_is_refused(name: str) -> None:
    """One trailing newline is part of the canonical encoding."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        (directory / name).write_bytes((directory / name).read_bytes().rstrip(b"\n"))
        rehash_manifest(directory)

        with pytest.raises(ValueError):
            manager.load_episode(0)


@pytest.mark.parametrize("name", PAYLOADS)
def test_a_rehashed_payload_with_two_trailing_newlines_is_refused(name: str) -> None:
    """And exactly one, not merely at least one."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        directory = root / "episode_000"
        (directory / name).write_bytes((directory / name).read_bytes() + b"\n")
        rehash_manifest(directory)

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_a_noncanonical_manifest_is_refused() -> None:
    """The manifest is checked too, though nothing hashes it."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        path = root / "episode_000" / MANIFEST_FILE
        document = loads_canonical(path.read_bytes())
        path.write_bytes(json.dumps(document, indent=2).encode("utf-8") + b"\n")

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_a_manifest_without_its_trailing_newline_is_refused() -> None:
    """A one-byte difference is still a difference."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager)
        path = root / "episode_000" / MANIFEST_FILE
        path.write_bytes(path.read_bytes().rstrip(b"\n"))

        with pytest.raises(ValueError):
            manager.load_episode(0)


def test_a_canonical_save_still_loads() -> None:
    """The control case: the writer's own output must satisfy the check."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifest = save_rich(manager)
        assert manager.load_episode(0).manifest.state_hash == manifest.state_hash


# --- Correction: the whole ancestry is verified, not just the direct parent --
#
# Candidate V2 checked a parent's files and state hash and called that "fully
# verified". It was not. The parent's envelope being intact says nothing about
# whether the parent is a loadable episode -- its world could fail topology
# validation, its log could belong to another episode -- and a parent whose own
# parent link is broken is itself unloadable. Every test below fails under V2.


def save_chain(manager: SaveManager, episodes: int) -> list:
    """Save a valid chain of rich episodes and return their manifests."""
    return [
        save_episode(
            manager,
            rich_world(episode=number, tick=20 + number),
            rich_event_log() if number == 0 else quiet_log(),
        )
        for number in range(episodes)
    ]


def repoint_payload(directory: Path, name: str, document: dict) -> str:
    """Rewrite a payload canonically and correctly update its manifest entry.

    This is the interesting kind of tampering: the bytes stay canonical and every
    digest and length is corrected, so nothing at the envelope level is wrong.
    Only full semantic reconstruction can tell that the episode is broken.
    """
    data = dumps_canonical(document, name)
    (directory / name).write_bytes(data)
    manifest = loads_canonical((directory / MANIFEST_FILE).read_bytes())
    manifest["files"][name] = {"bytes": len(data), "sha256": sha256_hex(data)}
    if name == WORLD_STATE_FILE:
        manifest["state_hash"] = sha256_hex(data)
    (directory / MANIFEST_FILE).write_bytes(dumps_canonical(manifest, MANIFEST_FILE))
    return sha256_hex(data)


def read_payload(directory: Path, name: str) -> dict:
    """Return one payload document from an episode directory."""
    return loads_canonical((directory / name).read_bytes())  # type: ignore[return-value]


def break_ancestor_payload(
    root: Path, ancestor: int, name: str, document: dict, *, relink_child: bool = False
) -> None:
    """Corrupt an ancestor payload, optionally keeping the child's link correct.

    Relinking matters for the world state: without it the child would fail on a
    stale parent hash, which proves nothing about semantic verification.
    """
    new_hash = repoint_payload(root / episode_directory_name(ancestor), name, document)
    if relink_child:
        child = root / episode_directory_name(ancestor + 1)
        manifest = loads_canonical((child / MANIFEST_FILE).read_bytes())
        manifest["parent_state_hash"] = new_hash
        (child / MANIFEST_FILE).write_bytes(dumps_canonical(manifest, MANIFEST_FILE))


def tree_fingerprint(root: Path) -> dict[str, object]:
    """Capture every path under a save root, with file bytes and link targets."""
    captured: dict[str, object] = {}
    for path in sorted(root.rglob("*")):
        key = str(path.relative_to(root))
        if path.is_symlink():
            captured[key] = ("symlink", os.readlink(path))
        elif path.is_dir():
            captured[key] = ("dir", None)
        else:
            captured[key] = ("file", path.read_bytes())
    return captured


# --- Complete lineage -------------------------------------------------------


def test_episode_zero_alone_loads() -> None:
    """The shortest possible chain still has to pass the walk."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 1)
        assert manager.load_episode(0).manifest.episode == 0


def test_a_three_episode_chain_loads() -> None:
    """Every episode in a sound chain remains loadable."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 3)
        for number in range(3):
            assert manager.load_episode(number).manifest.episode == number


def test_a_longer_chain_loads() -> None:
    """Length alone must not make a valid chain fail."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifests = [
            save_episode(manager, minimal_world(episode=number, tick=number), EventLog())
            for number in range(8)
        ]
        loaded = manager.load_episode(7)

        assert loaded.manifest.episode == 7
        assert loaded.manifest.parent_state_hash == manifests[6].state_hash


def test_a_wrong_parent_hash_fails_at_that_episode() -> None:
    """The direct link is still checked, as before."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 2)
        rewrite_manifest(root / "episode_001", parent_state_hash="a" * 64)

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_a_child_fails_when_its_parents_own_link_is_wrong() -> None:
    """Failure A: the child's own link is perfect, and it must still fail.

    A parent that cannot itself be loaded cannot vouch for anything, so descent
    from it is descent from nothing this save root can account for.
    """
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifests = save_chain(manager, 3)
        rewrite_manifest(root / "episode_001", parent_state_hash="a" * 64)

        child_manifest = loads_canonical((root / "episode_002" / MANIFEST_FILE).read_bytes())
        assert child_manifest["parent_state_hash"] == manifests[1].state_hash, (
            "episode 2's direct link must remain correct for this to prove anything"
        )

        with pytest.raises(ValueError):
            manager.load_episode(2)


def test_a_grandchild_fails_when_an_early_ancestor_is_broken() -> None:
    """The whole chain is walked, not the last edge or two."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 4)
        rewrite_manifest(root / "episode_001", parent_state_hash="b" * 64)

        with pytest.raises(ValueError):
            manager.load_episode(3)
        assert manager.load_episode(0).manifest.episode == 0, "episode 0 is unaffected"


def test_a_missing_intermediate_ancestor_fails() -> None:
    """A hole in the middle of a lineage is still a hole."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 3)
        shutil.rmtree(root / "episode_001")

        with pytest.raises(FileNotFoundError):
            manager.load_episode(2)


def test_a_symlinked_intermediate_ancestor_fails() -> None:
    """An ancestor that is a link, not a directory, breaks the chain."""
    with temporary_save_root() as root:
        require_symlink_support(root, target_is_directory=True)
        manager = SaveManager(root)
        save_chain(manager, 3)
        shutil.rmtree(root / "episode_001")
        (root / "episode_001").symlink_to(root / "episode_000", target_is_directory=True)

        with pytest.raises(ValueError):
            manager.load_episode(2)


def test_an_extra_file_in_an_intermediate_ancestor_fails() -> None:
    """Directory-shape rules apply to every episode in the chain."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 3)
        (root / "episode_001" / "notes.txt").write_text("hello", encoding="utf-8")

        with pytest.raises(ValueError):
            manager.load_episode(2)


def test_a_tampered_ancestor_payload_fails_for_the_child() -> None:
    """Envelope-level corruption in an ancestor also stops the child."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 3)
        path = root / "episode_001" / EVENT_LOG_FILE
        path.write_bytes(path.read_bytes().replace(b"1", b"2", 1))

        with pytest.raises(ValueError):
            manager.load_episode(2)


# --- Ancestor semantic verification -----------------------------------------


def test_a_child_fails_when_an_ancestor_log_records_another_episode() -> None:
    """Failure B: canonical bytes, correct digests, wrong episode."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 2)
        break_ancestor_payload(
            root, 0, EVENT_LOG_FILE, {"episode": 99, "events": [], "schema_version": 1}
        )

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_a_child_fails_when_an_ancestor_event_postdates_its_world() -> None:
    """An ancestor holding a future event is not a loadable episode."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 2)
        document = read_payload(root / "episode_000", EVENT_LOG_FILE)
        document["events"].append(
            {"payload": {}, "source_id": None, "tick": 9999, "type": "WALL_BUILT"}
        )
        break_ancestor_payload(root, 0, EVENT_LOG_FILE, document)

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_a_child_fails_when_an_ancestor_event_count_disagrees() -> None:
    """Cross-checks inside an ancestor are the child's business too."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 2)
        document = read_payload(root / "episode_000", EVENT_LOG_FILE)
        document["events"] = document["events"][:-1]
        break_ancestor_payload(root, 0, EVENT_LOG_FILE, document)

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_a_child_fails_when_an_ancestor_memory_document_is_invalid() -> None:
    """Failure C: ``facts`` as an object rather than a list."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 2)
        break_ancestor_payload(root, 0, WORLD_MEMORY_FILE, {"facts": {}, "schema_version": 1})

        with pytest.raises(TypeError):
            manager.load_episode(1)


def test_a_child_fails_when_an_ancestor_world_has_broken_topology() -> None:
    """The child's link is repointed, so only semantic verification can catch it."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 2)
        document = read_payload(root / "episode_000", WORLD_STATE_FILE)
        document["boundaries"][0]["district_b_id"] = document["boundaries"][0]["district_a_id"]
        break_ancestor_payload(root, 0, WORLD_STATE_FILE, document, relink_child=True)

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_a_child_fails_when_an_ancestor_rng_state_is_invalid() -> None:
    """A generator that cannot be restored makes the ancestor unloadable."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 2)
        document = read_payload(root / "episode_000", WORLD_STATE_FILE)
        document["rng_state"] = {"state_format": 1, "random_state": [3, [1, 2], None]}
        break_ancestor_payload(root, 0, WORLD_STATE_FILE, document, relink_child=True)

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_a_child_fails_when_an_ancestor_world_records_another_episode() -> None:
    """The world's own episode must agree with the directory it sits in."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 2)
        document = read_payload(root / "episode_000", WORLD_STATE_FILE)
        document["episode"] = 5
        break_ancestor_payload(root, 0, WORLD_STATE_FILE, document, relink_child=True)

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_a_child_fails_when_an_ancestor_world_tick_disagrees() -> None:
    """And with the tick its own manifest records."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 2)
        document = read_payload(root / "episode_000", WORLD_STATE_FILE)
        document["tick"] = document["tick"] + 1
        break_ancestor_payload(root, 0, WORLD_STATE_FILE, document, relink_child=True)

        with pytest.raises(ValueError):
            manager.load_episode(1)


def test_a_child_fails_when_ancestor_entity_counts_disagree() -> None:
    """An ancestor manifest miscounting its own world stops the child."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 2)
        directory = root / "episode_000"
        manifest = loads_canonical((directory / MANIFEST_FILE).read_bytes())
        manifest["entity_counts"]["districts"] += 1
        (directory / MANIFEST_FILE).write_bytes(dumps_canonical(manifest, MANIFEST_FILE))

        with pytest.raises(ValueError):
            manager.load_episode(1)


# --- Mutation safety --------------------------------------------------------


def test_a_failed_chain_load_writes_nothing_at_all() -> None:
    """Verification is a read, including when it walks several episodes.

    Every path, every byte, and every link target under the save root is
    compared, so a stray temporary directory would show up as a new entry.
    """
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 3)
        rewrite_manifest(root / "episode_001", parent_state_hash="a" * 64)
        before = tree_fingerprint(root)

        with pytest.raises(ValueError):
            manager.load_episode(2)

        assert tree_fingerprint(root) == before


def test_a_successful_chain_load_writes_nothing_either() -> None:
    """Walking ancestors must not touch them."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 3)
        before = tree_fingerprint(root)

        manager.load_episode(2)
        manager.load_episode(2)

        assert tree_fingerprint(root) == before


def test_a_chain_load_publishes_no_events_and_consumes_no_randomness() -> None:
    """Loading history must not replay it, and must not draw from a generator."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 3)

        loaded = manager.load_episode(2)
        expected = read_payload(root / "episode_002", WORLD_STATE_FILE)["rng_state"]

        assert loaded.world.rng.get_state() == expected, "the generator is where it was saved"
        assert loaded.world.tick == 22, "no tick was advanced"
        assert loaded.event_log.events() == ()


def test_a_chain_load_returns_only_the_requested_episode() -> None:
    """Ancestors are verified and released, not accumulated."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 3)
        loaded = manager.load_episode(2)

        assert isinstance(loaded, LoadedEpisode)
        assert loaded.manifest.episode == 2
        assert loaded.world.episode == 2
        assert loaded.world.tick == 22


# --- Implementation shape ---------------------------------------------------


def test_the_chain_walk_is_iterative_and_not_publicly_recursive() -> None:
    """Read from the source, because a recursive walk would work until it did not.

    Episode numbering has no ceiling, so a design that recursed once per ancestor
    would fail on a long-running world at whatever depth Python happens to allow.
    """
    import ast  # noqa: PLC0415

    module = sys.modules[SaveManager.__module__]
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    walker = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_load_verified_chain"
    )

    called = {
        node.func.attr
        for node in ast.walk(walker)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "load_episode" not in called, "the walk must not re-enter the public entry point"
    assert "_load_verified_chain" not in called, "the walk must not recurse into itself"
    assert any(isinstance(node, ast.For) for node in ast.walk(walker)), (
        "the ancestry must be walked with a loop"
    )


def test_each_ancestor_is_verified_exactly_once_per_load() -> None:
    """Re-verifying an ancestor per edge would make a long chain quadratic."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_chain(manager, 4)

        visited: list[int] = []
        original = SaveManager._verified_documents

        def counting(self: SaveManager, episode: int):
            """Record which episodes the walk opens."""
            visited.append(episode)
            return original(self, episode)

        SaveManager._verified_documents = counting  # type: ignore[method-assign]
        try:
            manager.load_episode(3)
        finally:
            SaveManager._verified_documents = original  # type: ignore[method-assign]

        assert visited == [0, 1, 2, 3], "ascending order, each episode opened once"


# --- Phase 11: the memory must describe the same moment as the world --------


def memory_at(episode: int, tick: int) -> WorldMemory:
    """Return an empty memory checkpointed to a chosen episode and tick."""
    return WorldMemory((), through_episode=episode, through_tick=tick)


def assert_nothing_was_written(root: Path) -> None:
    """Assert a rejected save left no directory and no staging behind."""
    assert not (root / "episode_000").exists()
    assert list(root.iterdir()) == []


def test_a_matching_memory_saves() -> None:
    """The control case for the checkpoint preflight."""
    with temporary_save_root() as root:
        world = rich_world(episode=0, tick=20)
        log = rich_event_log()
        memory = memory_for(SaveManager(root), world, log)
        manifest = SaveManager(root).save_episode(world, log, world_memory=memory)
        assert manifest.episode == 0
        assert len(memory) == 1, "the episode's WALL_BUILT event must be remembered"


@pytest.mark.parametrize("bad", [None, {}, {"facts": [], "schema_version": 1}, "memory", 0])
def test_a_non_memory_is_refused_before_anything_is_written(bad: object) -> None:
    """The save API takes the domain object, not a document it never validated."""
    with temporary_save_root() as root:
        with pytest.raises((TypeError, ValueError)):
            SaveManager(root).save_episode(rich_world(), rich_event_log(), world_memory=bad)
        assert_nothing_was_written(root)


def test_an_unprocessed_memory_is_refused() -> None:
    """An episode saved with a memory that never saw it would lose its history."""
    with temporary_save_root() as root:
        with pytest.raises(ValueError):
            SaveManager(root).save_episode(
                rich_world(), rich_event_log(), world_memory=WorldMemory.empty()
            )
        assert_nothing_was_written(root)


@pytest.mark.parametrize("episode", [1, 5])
def test_a_memory_checkpointed_to_another_episode_is_refused(episode: int) -> None:
    """A save whose two halves describe different episodes is not one episode.

    Nothing downstream could catch it: both files would be internally valid, and
    every hash and lineage check would pass.
    """
    with temporary_save_root() as root:
        with pytest.raises(ValueError):
            SaveManager(root).save_episode(
                rich_world(episode=0, tick=20),
                rich_event_log(),
                world_memory=memory_at(episode, 20),
            )
        assert_nothing_was_written(root)


@pytest.mark.parametrize("tick", [19, 21, 0])
def test_a_memory_checkpointed_to_another_tick_is_refused(tick: int) -> None:
    """The same argument for the moment within the episode."""
    with temporary_save_root() as root:
        with pytest.raises(ValueError):
            SaveManager(root).save_episode(
                rich_world(episode=0, tick=20),
                rich_event_log(),
                world_memory=memory_at(0, tick),
            )
        assert_nothing_was_written(root)


def test_a_rejected_memory_leaves_every_input_untouched() -> None:
    """Preflight happens before anything is read, written, or drawn."""
    with temporary_save_root() as root:
        world = rich_world(episode=0, tick=20)
        log = rich_event_log()
        memory = memory_at(1, 20)
        before = snapshot_inputs(world, log, memory)

        with pytest.raises(ValueError):
            SaveManager(root).save_episode(world, log, world_memory=memory)

        assert snapshot_inputs(world, log, memory) == before
        assert_nothing_was_written(root)


def test_a_rejected_memory_leaves_an_earlier_episode_untouched() -> None:
    """One bad save cannot damage the history behind it."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        save_rich(manager, episode=0)
        before = directory_fingerprint(root / "episode_000")

        with pytest.raises(ValueError):
            manager.save_episode(
                rich_world(episode=1, tick=21), rich_event_log(), world_memory=memory_at(1, 99)
            )

        assert directory_fingerprint(root / "episode_000") == before
        assert sorted(entry.name for entry in root.iterdir()) == ["episode_000"]


# --- Phase 11 Candidate V7: the authoritative world snapshot -----------------
#
# Event, MemoryFact, and WorldMemory snapshots are not sufficient while the
# World itself remains live. SaveManager therefore captures one world-state
# document up front, strictly reconstructs it, and runs every remaining phase
# against the reconstruction. These tests install stateful World and entity
# subclasses whose read budgets are tuned to the exact read sequence Candidate
# V6 performed, so each one either published an episode V6's own loader refused
# or silently rewrote the caller's memory checkpoint. Under the snapshot, every
# adversary collapses to one of two honest outcomes: a clean refusal before the
# filesystem is touched, or a coherent episode that immediately reloads.

SNAPSHOT_WALL = "wall_boundary_ab"
"""The wall the snapshot scenarios build."""

SNAPSHOT_BOUNDARY = "boundary_ab"
"""The boundary that wall stands on."""

SNAPSHOT_LAW = "resource_sharing"
"""The law the restoration scenario restores."""


def _shifting_field(name: str) -> property:
    """Return a property answering its stored field until a read budget is spent.

    Reads within the budget return whatever the entity stores; every read after
    it returns the configured shifted value. Writes always land in the backing
    store, so the ordinary dataclass constructor works unchanged.
    """

    def read(self: object) -> object:
        """Count the read and answer from the store or the shift."""
        self.__dict__["reads"] += 1
        if self.__dict__["reads"] > self.__dict__["stable_reads"]:
            return self.__dict__["shifted"]
        return self.__dict__[f"stored_{name}"]

    def write(self: object, value: object) -> None:
        """Record the honest value the constructor assigned."""
        self.__dict__[f"stored_{name}"] = value

    return property(read, write)


class _ShiftingReader:
    """Mixin arming a read-budgeted field before the object initializes."""

    def __init__(self, *args: object, stable_reads: int, shifted: object, **kwargs: object) -> None:
        """Record the read budget and shifted value, then initialize normally."""
        self.__dict__.update(stable_reads=stable_reads, shifted=shifted, reads=0)
        super().__init__(*args, **kwargs)


class ShiftingPermanentWall(_ShiftingReader, Wall):
    """Wall whose ``permanent`` stops being what it stored once its budget is spent.

    With a budget of three this is exactly the reviewer's adversary: Candidate
    V6 read ``permanent`` three times while validating memory and once more
    while serializing, so reads 1-3 said True and the published file said false.
    """

    permanent = _shifting_field("permanent")


class ShiftingBuiltTickWall(_ShiftingReader, Wall):
    """Wall whose ``built_tick`` shifts once its read budget is spent.

    Candidate V6 read ``built_tick`` five times before serialization -- once at
    construction and four times across memory validation -- and twice while
    serializing, so a budget of five validated one tick and published another.
    """

    built_tick = _shifting_field("built_tick")


class ShiftingBoundary(_ShiftingReader, Boundary):
    """Boundary whose ``wall_id`` shifts once its read budget is spent.

    Candidate V6 read ``wall_id`` thirteen times across construction,
    registration, and validation, and once more while serializing, so a budget
    of thirteen validated a carried wall and published a boundary without one.
    """

    wall_id = _shifting_field("wall_id")


class ShiftingLaw(_ShiftingReader, Law):
    """Law whose ``restored_tick`` shifts once its read budget is spent.

    Candidate V6 read ``restored_tick`` four times before serialization -- twice
    at construction and twice while validating the restoration -- and once while
    serializing, so a budget of four validated one tick and published another.
    """

    restored_tick = _shifting_field("restored_tick")


class ShiftingTickWorld(_ShiftingReader, World):
    """World whose ``tick`` shifts once its read budget is spent.

    Candidate V6 read ``tick`` three times while validating and four more times
    while serializing and building the manifest, so a budget of three matched
    the memory checkpoint and then recorded a different tick everywhere else.
    """

    @property
    def tick(self) -> int:
        """Answer the stored tick within the budget, the shifted one after it."""
        self.__dict__["reads"] += 1
        if self.__dict__["reads"] > self.__dict__["stable_reads"]:
            return self.__dict__["shifted"]  # type: ignore[return-value]
        return self._tick


class ShiftingEpisodeWorld(_ShiftingReader, World):
    """World whose ``episode`` shifts once its read budget is spent.

    Candidate V6 read ``episode`` three times while resolving the destination
    and validating, and twice more while serializing, so a budget of three
    validated one episode and wrote another into the world state.
    """

    @property
    def episode(self) -> int:
        """Answer the stored episode within the budget, the shifted one after."""
        self.__dict__["reads"] += 1
        if self.__dict__["reads"] > self.__dict__["stable_reads"]:
            return self.__dict__["shifted"]  # type: ignore[return-value]
        return self._episode


class ShiftingMemory(WorldMemory):
    """Memory whose ``through_tick`` shifts after its first read."""

    @property
    def through_tick(self) -> int | None:
        """Answer the stored checkpoint once, then one tick later forever."""
        reads = self.__dict__["tick_reads"] = self.__dict__.get("tick_reads", 0) + 1
        if reads > 1 and self._through_tick is not None:
            return self._through_tick + 1
        return self._through_tick


class RecordingWorld(World):
    """World that tallies every public read, to pin where reading stops."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Start an empty tally, then build the world normally."""
        self.__dict__["reads"] = Counter()
        super().__init__(*args, **kwargs)

    def _tally(self, name: str) -> None:
        """Record one read of a public accessor."""
        self.__dict__["reads"][name] += 1

    @property
    def tick(self) -> int:
        """Count the read, then answer normally."""
        self._tally("tick")
        return self._tick

    @property
    def episode(self) -> int:
        """Count the read, then answer normally."""
        self._tally("episode")
        return self._episode

    @property
    def rng(self) -> object:
        """Count the read, then answer normally."""
        self._tally("rng")
        return self._rng

    @property
    def districts(self) -> object:
        """Count the read, then answer normally."""
        self._tally("districts")
        return MappingProxyType(self._districts)

    @property
    def boundaries(self) -> object:
        """Count the read, then answer normally."""
        self._tally("boundaries")
        return MappingProxyType(self._boundaries)

    @property
    def walls(self) -> object:
        """Count the read, then answer normally."""
        self._tally("walls")
        return MappingProxyType(self._walls)

    @property
    def laws(self) -> object:
        """Count the read, then answer normally."""
        self._tally("laws")
        return MappingProxyType(self._laws)

    @property
    def infrastructure(self) -> object:
        """Count the read, then answer normally."""
        self._tally("infrastructure")
        return MappingProxyType(self._infrastructure)

    def has_entity(self, entity_id: str) -> bool:
        """Count the read, then answer normally."""
        self._tally("has_entity")
        return super().has_entity(entity_id)

    def get_entity(self, entity_id: str) -> object:
        """Count the read, then answer normally."""
        self._tally("get_entity")
        return super().get_entity(entity_id)


class LoyalWall(Wall):
    """A legitimate Wall subclass whose every read is coherent."""


class LoyalBoundary(Boundary):
    """A legitimate Boundary subclass whose every read is coherent."""


class LoyalLaw(Law):
    """A legitimate Law subclass whose every read is coherent."""


class LoyalWorld(World):
    """A legitimate World subclass whose every read is coherent."""


def snapshot_wall(**overrides: object) -> Wall:
    """Build the permanent wall the snapshot scenarios stand on."""
    values: dict[str, object] = {"created_tick": 120, "built_tick": 120}
    values.update(overrides)
    return build_wall(SNAPSHOT_WALL, SNAPSHOT_BOUNDARY, **values)  # type: ignore[arg-type]


def wall_world(
    wall: Wall,
    *,
    boundary: Boundary | None = None,
    world_cls: type[World] = World,
    tick: int = 120,
    episode: int = 0,
    **world_extra: object,
) -> World:
    """Build the two-district world every stateful-entity scenario uses."""
    world = world_cls(rng=consumed_rng(), tick=tick, episode=episode, **world_extra)
    world.add_district(build_district("district_a"))
    world.add_district(build_district("district_b"))
    world.add_boundary(
        boundary
        if boundary is not None
        else Boundary(
            id=SNAPSHOT_BOUNDARY,
            created_tick=0,
            district_a_id="district_a",
            district_b_id="district_b",
        )
    )
    world.add_wall(wall)
    return world


def wall_event(tick: int = 120) -> Event:
    """Return the construction event the snapshot wall answers to."""
    return Event(
        tick=tick,
        type=EventType.WALL_BUILT,
        payload={"wall_id": SNAPSHOT_WALL},
        source_id=SNAPSHOT_WALL,
    )


def log_holding(*events: Event) -> EventLog:
    """Return a log holding these events in order."""
    log = EventLog()
    for event in events:
        log.append(event)
    return log


def built_wall_memory() -> WorldMemory:
    """Distil the memory the wall-building episode actually requires."""
    return MemorySignificance().distill_episode(
        world=wall_world(snapshot_wall()),
        event_log=log_holding(wall_event()),
        previous_memory=WorldMemory.empty(),
    )


def restored_law(**overrides: object) -> Law:
    """Build the restored law the persistence scenario stands on."""
    values: dict[str, object] = {
        "name": "Resource Sharing",
        "active": True,
        "previous_value": False,
        "current_value": True,
        "changed_episode": 0,
        "restored_tick": 250,
    }
    values.update(overrides)
    return build_law(SNAPSHOT_LAW, **values)  # type: ignore[arg-type]


def restored_law_world(law: Law, *, wall: Wall | None = None) -> World:
    """Build the world in which a law was restored after the wall was built."""
    world = World(rng=consumed_rng(), tick=250, episode=0)
    world.add_district(build_district("district_a"))
    world.add_district(build_district("district_b"))
    world.add_boundary(
        Boundary(
            id=SNAPSHOT_BOUNDARY,
            created_tick=0,
            district_a_id="district_a",
            district_b_id="district_b",
        )
    )
    world.add_law(law)
    world.add_wall(wall if wall is not None else snapshot_wall())
    return world


def law_restored_event(tick: int = 250) -> Event:
    """Return the restoration event the persistence scenario answers to."""
    return Event(tick=tick, type=EventType.LAW_RESTORED, payload={}, source_id=SNAPSHOT_LAW)


def restored_law_memory() -> WorldMemory:
    """Distil the memory the wall-then-restoration episode actually requires."""
    return MemorySignificance().distill_episode(
        world=restored_law_world(restored_law()),
        event_log=log_holding(wall_event(), law_restored_event()),
        previous_memory=WorldMemory.empty(),
    )


def test_a_wall_reporting_permanence_only_to_validation_cannot_poison_a_save() -> None:
    """The reviewer's stateful wall: Candidate V6 published an episode it refused to load.

    Under the authoritative snapshot the wall is read once, while the world
    document is captured; whatever it said then is what every later phase
    validates and what lands on disk, so the save stays loadable.
    """
    wall = ShiftingPermanentWall(
        id=SNAPSHOT_WALL,
        created_tick=120,
        boundary_id=SNAPSHOT_BOUNDARY,
        built_tick=120,
        integrity=1.0,
        active=True,
        permanent=True,
        dependency_score=0.0,
        transport_dependency=0.0,
        resource_dependency=0.0,
        stable_reads=3,
        shifted=False,
    )
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifest = manager.save_episode(
            wall_world(wall), log_holding(wall_event()), world_memory=built_wall_memory()
        )

        loaded = manager.load_episode(manifest.episode)
        assert loaded.world.walls[SNAPSHOT_WALL].permanent is True
        assert loaded.world_memory == built_wall_memory()


def test_a_wall_serialized_as_impermanent_while_remembered_permanent_is_refused() -> None:
    """The preferred outcome: a captured document disagreeing with the memory rejects.

    This wall answers False to every read, so the captured world document says
    the wall is not permanent while the supplied memory remembers that it is.
    The save must refuse before anything touches the filesystem.
    """
    wall = ShiftingPermanentWall(
        id=SNAPSHOT_WALL,
        created_tick=120,
        boundary_id=SNAPSHOT_BOUNDARY,
        built_tick=120,
        integrity=1.0,
        active=True,
        permanent=True,
        dependency_score=0.0,
        transport_dependency=0.0,
        resource_dependency=0.0,
        stable_reads=0,
        shifted=False,
    )
    world = wall_world(wall)
    memory = built_wall_memory()
    memory_before = (memory.facts, memory.through_episode, memory.through_tick)
    with temporary_save_root() as root:
        rng_before = world.rng.get_state()

        with pytest.raises(ValueError, match="not permanent"):
            SaveManager(root).save_episode(world, log_holding(wall_event()), world_memory=memory)

        assert_nothing_was_written(root)
        assert world.rng.get_state() == rng_before
        assert (memory.facts, memory.through_episode, memory.through_tick) == memory_before


def test_a_tick_shifting_world_cannot_rewrite_the_memory_checkpoint() -> None:
    """The reviewer's stateful world: a memory supplied at tick 120 must stay at 120.

    Candidate V6 matched the checkpoint against early reads and built the
    manifest from later ones, so the loaded memory came back checkpointed to a
    tick the caller never processed. The snapshot leaves one tick in the world
    document, and the checkpoint must match exactly that.
    """
    world = ShiftingTickWorld(rng=consumed_rng(), tick=120, episode=0, stable_reads=3, shifted=121)
    world.add_district(build_district("district_a"))
    world.add_district(build_district("district_b"))
    world.add_boundary(
        Boundary(
            id=SNAPSHOT_BOUNDARY,
            created_tick=0,
            district_a_id="district_a",
            district_b_id="district_b",
        )
    )
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifest = manager.save_episode(world, EventLog(), world_memory=memory_at(0, 120))

        assert manifest.tick == 120
        loaded = manager.load_episode(0)
        assert loaded.manifest.tick == 120
        assert loaded.world_memory.through_tick == 120
        assert loaded.world.tick == 120


def test_a_tick_captured_beyond_the_checkpoint_is_refused_before_publication() -> None:
    """A world document captured at tick 121 cannot save a memory processed to 120."""
    world = ShiftingTickWorld(rng=consumed_rng(), tick=120, episode=0, stable_reads=1, shifted=121)
    world.add_district(build_district("district_a"))
    world.add_district(build_district("district_b"))
    with temporary_save_root() as root:
        rng_before = world.rng.get_state()

        with pytest.raises(ValueError, match=r"tick 120.*121"):
            SaveManager(root).save_episode(world, EventLog(), world_memory=memory_at(0, 120))

        assert_nothing_was_written(root)
        assert world.rng.get_state() == rng_before


def test_an_episode_shifting_world_cannot_publish_across_episodes() -> None:
    """One captured episode number names the directory, the parent, and the manifest.

    Candidate V6 resolved the destination from an early read and serialized a
    later one, publishing a directory whose world state named another episode --
    an episode its own loader refused.
    """
    world = ShiftingEpisodeWorld(rng=consumed_rng(), tick=120, episode=0, stable_reads=3, shifted=1)
    world.add_district(build_district("district_a"))
    world.add_district(build_district("district_b"))
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifest = manager.save_episode(world, EventLog(), world_memory=memory_at(0, 120))

        assert manifest.episode == 0
        assert sorted(entry.name for entry in root.iterdir()) == ["episode_000"]
        loaded = manager.load_episode(0)
        assert loaded.world.episode == 0
        assert loaded.manifest.episode == 0


def test_an_episode_captured_disagreeing_with_the_memory_is_refused() -> None:
    """A world document captured at episode 1 cannot save episode 0's memory."""
    world = ShiftingEpisodeWorld(rng=consumed_rng(), tick=120, episode=0, stable_reads=1, shifted=1)
    world.add_district(build_district("district_a"))
    world.add_district(build_district("district_b"))
    with temporary_save_root() as root:
        rng_before = world.rng.get_state()

        with pytest.raises(ValueError, match=r"episode 0.*episode 1|episode 1.*episode 0"):
            SaveManager(root).save_episode(world, EventLog(), world_memory=memory_at(0, 120))

        assert list(root.iterdir()) == []
        assert world.rng.get_state() == rng_before


def test_a_wall_shifting_built_tick_after_validation_still_saves_a_loadable_episode() -> None:
    """A built_tick that shifts after validation cannot reach the published file."""
    wall = ShiftingBuiltTickWall(
        id=SNAPSHOT_WALL,
        created_tick=120,
        boundary_id=SNAPSHOT_BOUNDARY,
        built_tick=120,
        integrity=1.0,
        active=True,
        permanent=True,
        dependency_score=0.0,
        transport_dependency=0.0,
        resource_dependency=0.0,
        stable_reads=5,
        shifted=121,
    )
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifest = manager.save_episode(
            wall_world(wall), log_holding(wall_event()), world_memory=built_wall_memory()
        )

        loaded = manager.load_episode(manifest.episode)
        assert loaded.world.walls[SNAPSHOT_WALL].built_tick == 120
        assert loaded.world_memory == built_wall_memory()


def test_a_boundary_shifting_its_wall_reference_still_saves_a_loadable_episode() -> None:
    """A wall reference that shifts after validation cannot reach the published file."""
    boundary = ShiftingBoundary(
        id=SNAPSHOT_BOUNDARY,
        created_tick=0,
        district_a_id="district_a",
        district_b_id="district_b",
        stable_reads=13,
        shifted=None,
    )
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifest = manager.save_episode(
            wall_world(snapshot_wall(), boundary=boundary),
            log_holding(wall_event()),
            world_memory=built_wall_memory(),
        )

        loaded = manager.load_episode(manifest.episode)
        assert loaded.world.boundaries[SNAPSHOT_BOUNDARY].wall_id == SNAPSHOT_WALL
        assert loaded.world_memory == built_wall_memory()


def test_a_law_shifting_restored_tick_after_validation_still_saves_a_loadable_episode() -> None:
    """A restored_tick that shifts after validation cannot reach the published file."""
    law = ShiftingLaw(
        id=SNAPSHOT_LAW,
        created_tick=0,
        name="Resource Sharing",
        active=True,
        previous_value=False,
        current_value=True,
        changed_episode=0,
        restored_tick=250,
        stable_reads=4,
        shifted=251,
    )
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifest = manager.save_episode(
            restored_law_world(law),
            log_holding(wall_event(), law_restored_event()),
            world_memory=restored_law_memory(),
        )

        loaded = manager.load_episode(manifest.episode)
        assert loaded.world.laws[SNAPSHOT_LAW].restored_tick == 250
        assert loaded.world_memory == restored_law_memory()


def test_a_stable_subclass_family_still_saves_and_reloads() -> None:
    """The control case: coherent subclasses of World and every entity still work."""
    world = LoyalWorld(rng=consumed_rng(), tick=250, episode=0)
    world.add_district(build_district("district_a"))
    world.add_district(build_district("district_b"))
    world.add_boundary(
        LoyalBoundary(
            id=SNAPSHOT_BOUNDARY,
            created_tick=0,
            district_a_id="district_a",
            district_b_id="district_b",
        )
    )
    world.add_law(
        LoyalLaw(
            id=SNAPSHOT_LAW,
            created_tick=0,
            name="Resource Sharing",
            active=True,
            previous_value=False,
            current_value=True,
            changed_episode=0,
            restored_tick=250,
        )
    )
    world.add_wall(
        LoyalWall(
            id=SNAPSHOT_WALL,
            created_tick=120,
            boundary_id=SNAPSHOT_BOUNDARY,
            built_tick=120,
            integrity=1.0,
            active=True,
            permanent=True,
            dependency_score=0.0,
            transport_dependency=0.0,
            resource_dependency=0.0,
        )
    )
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manifest = manager.save_episode(
            world,
            log_holding(wall_event(), law_restored_event()),
            world_memory=restored_law_memory(),
        )

        loaded = manager.load_episode(manifest.episode)
        assert structural_state(loaded.world) == structural_state(world)
        assert loaded.world_memory == restored_law_memory()


def test_the_caller_world_is_not_read_after_the_document_is_captured() -> None:
    """The counting subclass pins the boundary: a save reads what serialization reads.

    Two identical recording worlds, one handed to ``serialize_world`` alone and
    one to a full save. If the save consulted the caller world anywhere after
    capturing the authoritative document -- checkpoint matching, transition
    validation, the event log, entity counts, the manifest -- its tally would
    exceed the serializer's.
    """

    def recording_world() -> World:
        """Build one of the twin recording worlds."""
        return wall_world(snapshot_wall(), world_cls=RecordingWorld)

    serialized_only = recording_world()
    serialize_world(serialized_only)

    saved = recording_world()
    with temporary_save_root() as root:
        SaveManager(root).save_episode(
            saved, log_holding(wall_event()), world_memory=built_wall_memory()
        )

    assert dict(saved.__dict__["reads"]) == dict(serialized_only.__dict__["reads"])


class ReportingSourceEvent(Event):
    """Event whose ``source_id`` reports a chosen value after construction."""

    @property
    def source_id(self) -> object:
        """Answer the doctored value once installed, the stored one before."""
        if "reported" in self.__dict__:
            return self.__dict__["reported"]
        return self.__dict__.get("constructed")

    @source_id.setter
    def source_id(self, value: object) -> None:
        """Record the honest value the constructor assigned."""
        self.__dict__["constructed"] = value


class ReportingFact(MemoryFact):
    """Fact whose derived fields report chosen values after construction."""

    @property
    def fact_id(self) -> object:
        """Answer the doctored identifier once installed, the real one before."""
        if "reported_id" in self.__dict__:
            return self.__dict__["reported_id"]
        return self.__dict__.get("derived_id")

    @fact_id.setter
    def fact_id(self, value: object) -> None:
        """Record the identifier the fact honestly derived."""
        self.__dict__["derived_id"] = value

    @property
    def summary(self) -> object:
        """Answer the doctored summary once installed, the real one before."""
        if "reported_summary" in self.__dict__:
            return self.__dict__["reported_summary"]
        return self.__dict__.get("derived_summary")

    @summary.setter
    def summary(self, value: object) -> None:
        """Record the summary the fact honestly derived."""
        self.__dict__["derived_summary"] = value


class _SubclassedString(str):
    """A ``str`` subclass: equal to a plain string, and not one."""


def _stateful_event_scenario() -> tuple[World, EventLog, WorldMemory]:
    """Return a save whose log holds an Event subclass with a doctored source."""
    event = ReportingSourceEvent(
        tick=120,
        type=EventType.WALL_BUILT,
        payload={"wall_id": SNAPSHOT_WALL},
        source_id=SNAPSHOT_WALL,
    )
    event.__dict__["reported"] = _SubclassedString(SNAPSHOT_WALL)
    return wall_world(snapshot_wall()), log_holding(event), built_wall_memory()


def _stateful_fact_scenario() -> tuple[World, EventLog, WorldMemory]:
    """Return a save whose memory holds a MemoryFact subclass with doctored strings."""
    base = built_wall_memory().facts[0]
    fact = ReportingFact(
        fact_type=base.fact_type,
        episode=base.episode,
        tick=base.tick,
        source_event_index=base.source_event_index,
        source_event_type=base.source_event_type,
        source_id=base.source_id,
        subject_ids=base.subject_ids,
        details=base.details_as_dict(),
    )
    fact.__dict__["reported_id"] = _SubclassedString(base.fact_id)
    fact.__dict__["reported_summary"] = _SubclassedString(base.summary)
    memory = WorldMemory((fact,), through_episode=0, through_tick=120)
    return wall_world(snapshot_wall()), log_holding(wall_event()), memory


def _stateful_memory_scenario() -> tuple[World, EventLog, WorldMemory]:
    """Return a save whose WorldMemory subclass shifts its checkpoint between reads."""
    memory = ShiftingMemory((), through_episode=0, through_tick=120)
    world = World(rng=consumed_rng(), tick=120, episode=0)
    world.add_district(build_district("district_a"))
    world.add_district(build_district("district_b"))
    return world, EventLog(), memory


def _stateful_world_scenario() -> tuple[World, EventLog, WorldMemory]:
    """Return a save whose World subclass shifts its tick between reads."""
    world = ShiftingTickWorld(rng=consumed_rng(), tick=120, episode=0, stable_reads=3, shifted=121)
    world.add_district(build_district("district_a"))
    world.add_district(build_district("district_b"))
    return world, EventLog(), memory_at(0, 120)


def _stateful_wall_scenario() -> tuple[World, EventLog, WorldMemory]:
    """Return a save whose Wall subclass shifts ``permanent`` between reads."""
    wall = ShiftingPermanentWall(
        id=SNAPSHOT_WALL,
        created_tick=120,
        boundary_id=SNAPSHOT_BOUNDARY,
        built_tick=120,
        integrity=1.0,
        active=True,
        permanent=True,
        dependency_score=0.0,
        transport_dependency=0.0,
        resource_dependency=0.0,
        stable_reads=3,
        shifted=False,
    )
    return wall_world(wall), log_holding(wall_event()), built_wall_memory()


def _stateful_boundary_scenario() -> tuple[World, EventLog, WorldMemory]:
    """Return a save whose Boundary subclass shifts its wall reference between reads."""
    boundary = ShiftingBoundary(
        id=SNAPSHOT_BOUNDARY,
        created_tick=0,
        district_a_id="district_a",
        district_b_id="district_b",
        stable_reads=13,
        shifted=None,
    )
    world = wall_world(snapshot_wall(), boundary=boundary)
    return world, log_holding(wall_event()), built_wall_memory()


def _stateful_law_scenario() -> tuple[World, EventLog, WorldMemory]:
    """Return a save whose Law subclass shifts ``restored_tick`` between reads."""
    law = ShiftingLaw(
        id=SNAPSHOT_LAW,
        created_tick=0,
        name="Resource Sharing",
        active=True,
        previous_value=False,
        current_value=True,
        changed_episode=0,
        restored_tick=250,
        stable_reads=4,
        shifted=251,
    )
    world = restored_law_world(law)
    return world, log_holding(wall_event(), law_restored_event()), restored_law_memory()


STATEFUL_ADVERSARIES = {
    "event_subclass": _stateful_event_scenario,
    "memory_fact_subclass": _stateful_fact_scenario,
    "world_memory_subclass": _stateful_memory_scenario,
    "world_subclass": _stateful_world_scenario,
    "wall_subclass": _stateful_wall_scenario,
    "boundary_subclass": _stateful_boundary_scenario,
    "law_subclass": _stateful_law_scenario,
}
"""Every stateful adversary the successful-save invariant is tested against."""


@pytest.mark.parametrize("adversary", sorted(STATEFUL_ADVERSARIES))
def test_every_successful_save_immediately_reloads(adversary: str) -> None:
    """The Candidate V7 invariant, against every stateful adversary.

    Rejecting an adversary before the filesystem is touched is valid. Publishing
    an episode this same implementation cannot immediately reload -- or one whose
    memory comes back checkpointed to a different moment -- is not.
    """
    world, log, memory = STATEFUL_ADVERSARIES[adversary]()
    with temporary_save_root() as root:
        manager = SaveManager(root)
        rng_before = world.rng.get_state()
        try:
            manifest = manager.save_episode(world, log, world_memory=memory)
        except (TypeError, ValueError):
            assert list(root.iterdir()) == [], "a rejected save must leave no residue"
            assert world.rng.get_state() == rng_before
            return

        loaded = manager.load_episode(manifest.episode)
        assert loaded.manifest.state_hash == manifest.state_hash
        assert loaded.manifest.tick == manifest.tick
        assert loaded.world_memory.through_episode == manifest.episode
        assert loaded.world_memory.through_tick == manifest.tick


def test_a_rejected_stateful_save_leaves_the_parent_episode_untouched() -> None:
    """One stateful adversary cannot damage the history behind it."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        manager.save_episode(
            wall_world(snapshot_wall()),
            log_holding(wall_event()),
            world_memory=built_wall_memory(),
        )
        before = directory_fingerprint(root / "episode_000")
        parent_memory = manager.load_episode(0).world_memory

        impermanent = ShiftingPermanentWall(
            id=SNAPSHOT_WALL,
            created_tick=120,
            boundary_id=SNAPSHOT_BOUNDARY,
            built_tick=120,
            integrity=1.0,
            active=True,
            permanent=True,
            dependency_score=0.0,
            transport_dependency=0.0,
            resource_dependency=0.0,
            stable_reads=0,
            shifted=False,
        )
        child = wall_world(impermanent, tick=250, episode=1)
        rng_before = child.rng.get_state()

        with pytest.raises(ValueError, match="permanent"):
            manager.save_episode(
                child,
                quiet_log(),
                world_memory=parent_memory.advance(episode=1, tick=250, new_facts=()),
            )

        assert not (root / "episode_001").exists()
        assert sorted(entry.name for entry in root.iterdir()) == ["episode_000"]
        assert directory_fingerprint(root / "episode_000") == before
        assert child.rng.get_state() == rng_before


# --- hostile __class__ at the save boundary ----------------------------------


class HostileClass:
    """Raises from ``__class__`` instead of answering."""

    @property
    def __class__(self) -> type:
        """Raise instead of revealing a type."""
        raise RuntimeError("boom")


def test_a_hostile_save_root_is_refused() -> None:
    """The root's true runtime type decides, not its ``__class__`` property."""
    with pytest.raises(TypeError, match="save_root must be a str or Path, got HostileClass"):
        SaveManager(HostileClass())


def test_a_hostile_world_is_refused_before_anything_is_written() -> None:
    """A fake world is refused without executing its ``__class__`` property."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        log = rich_event_log()
        events_before = log.events()
        memory = empty_memory(rich_world())
        checkpoint_before = (memory.through_episode, memory.through_tick, memory.facts)

        with pytest.raises(TypeError, match="world must be a World, got HostileClass"):
            manager.save_episode(world=HostileClass(), event_log=log, world_memory=memory)

        assert list(root.iterdir()) == []
        assert log.events() == events_before
        assert (memory.through_episode, memory.through_tick, memory.facts) == checkpoint_before


def test_a_hostile_event_log_is_refused_before_anything_is_written() -> None:
    """A fake log is refused without executing its ``__class__`` property."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        world = rich_world()
        world_before = structural_state(world)
        rng_before = world.rng.get_state()
        memory = empty_memory(world)
        checkpoint_before = (memory.through_episode, memory.through_tick, memory.facts)

        with pytest.raises(TypeError, match="event_log must be an EventLog, got HostileClass"):
            manager.save_episode(world=world, event_log=HostileClass(), world_memory=memory)

        assert structural_state(world) == world_before
        assert world.rng.get_state() == rng_before
        assert (memory.through_episode, memory.through_tick, memory.facts) == checkpoint_before
        assert list(root.iterdir()) == []


def test_a_hostile_memory_is_refused_before_anything_is_written() -> None:
    """A fake memory is refused without executing its ``__class__`` property."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        world = rich_world()
        log = rich_event_log()
        world_before = structural_state(world)
        events_before = log.events()
        rng_before = world.rng.get_state()

        with pytest.raises(TypeError, match="world_memory must be a WorldMemory, got HostileClass"):
            manager.save_episode(world=world, event_log=log, world_memory=HostileClass())

        assert structural_state(world) == world_before
        assert log.events() == events_before
        assert world.rng.get_state() == rng_before
        assert list(root.iterdir()) == []


@pytest.mark.parametrize(
    ("registry_attr", "message"),
    [
        ("_districts", "district must be a District, got HostileClass"),
        ("_boundaries", "boundary must be a Boundary, got HostileClass"),
        ("_walls", "wall must be a Wall, got HostileClass"),
        ("_laws", "law must be a Law, got HostileClass"),
        ("_infrastructure", "infrastructure must be an Infrastructure, got HostileClass"),
    ],
)
def test_a_hostile_entity_inside_the_world_aborts_the_save_cleanly(
    registry_attr: str, message: str
) -> None:
    """The Phase 10 serializers refuse a fake entity before anything is written."""
    with temporary_save_root() as root:
        manager = SaveManager(root)
        world = rich_world()
        registry = getattr(world, registry_attr)
        key = sorted(registry)[0]
        fake = HostileClass()
        for klass in type(registry[key]).__mro__:
            for name in getattr(klass, "__slots__", ()):
                setattr(fake, name, getattr(registry[key], name))
        registry[key] = fake
        world._entities[key] = fake

        log = rich_event_log()
        memory = empty_memory(world)
        events_before = log.events()
        rng_before = world.rng.get_state()
        checkpoint_before = (memory.through_episode, memory.through_tick, memory.facts)
        keys_before = {
            attr: sorted(getattr(world, attr))
            for attr in ("_districts", "_boundaries", "_walls", "_laws", "_infrastructure")
        }

        with pytest.raises(TypeError, match=message):
            manager.save_episode(world=world, event_log=log, world_memory=memory)

        assert list(root.iterdir()) == []
        assert log.events() == events_before
        assert world.rng.get_state() == rng_before
        assert (memory.through_episode, memory.through_tick, memory.facts) == checkpoint_before
        assert (world.tick, world.episode) == (20, 0)
        assert {
            attr: sorted(getattr(world, attr))
            for attr in ("_districts", "_boundaries", "_walls", "_laws", "_infrastructure")
        } == keys_before
        assert getattr(world, registry_attr)[key] is fake
