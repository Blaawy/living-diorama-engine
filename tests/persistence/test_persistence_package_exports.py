"""Tests for the persistence package's public surface."""

import inspect

import pytest

import living_diorama.persistence as persistence
from living_diorama.persistence import (
    EpisodeManifest,
    FileMetadata,
    LoadedEpisode,
    SaveManager,
)

EXPECTED_EXPORTS = [
    "EPISODE_FORMAT",
    "EVENT_LOG_FILE",
    "MANIFEST_FILE",
    "SCHEMA_VERSION",
    "WORLD_MEMORY_FILE",
    "WORLD_STATE_FILE",
    "EpisodeManifest",
    "FileMetadata",
    "LoadedEpisode",
    "SaveManager",
    "dumps_canonical",
    "episode_directory_name",
    "loads_canonical",
    "sha256_hex",
]
"""The intended public surface, listed here so a change has to be deliberate."""


def test_the_public_surface_is_exactly_as_declared() -> None:
    """An accidental export is as much a defect as a missing one."""
    assert sorted(persistence.__all__) == sorted(EXPECTED_EXPORTS)
    for name in EXPECTED_EXPORTS:
        assert hasattr(persistence, name), name


def test_no_private_helper_is_exported() -> None:
    """Internals stay internal."""
    assert not any(name.startswith("_") for name in persistence.__all__)


def test_the_schema_version_is_one() -> None:
    """Version 1 is the only shape this build reads or writes."""
    assert persistence.SCHEMA_VERSION == 1
    assert type(persistence.SCHEMA_VERSION) is int


def test_the_documented_file_names() -> None:
    """The four names an episode directory is allowed to contain."""
    assert persistence.MANIFEST_FILE == "manifest.json"
    assert persistence.WORLD_STATE_FILE == "world_state.json"
    assert persistence.EVENT_LOG_FILE == "event_log.json"
    assert persistence.WORLD_MEMORY_FILE == "world_memory.json"
    assert persistence.EPISODE_FORMAT == "living_diorama_episode"


def test_the_save_manager_exposes_the_agreed_api() -> None:
    """The three methods callers depend on, with the agreed signatures."""
    save = inspect.signature(SaveManager.save_episode)
    assert list(save.parameters) == ["self", "world", "event_log", "world_memory"]
    assert save.parameters["world_memory"].kind is inspect.Parameter.KEYWORD_ONLY
    assert save.parameters["world_memory"].default is inspect.Parameter.empty, (
        "memory is required: an episode saved without its history would silently "
        "discard everything the world remembers"
    )

    load = inspect.signature(SaveManager.load_episode)
    assert list(load.parameters) == ["self", "episode"]

    lineage = inspect.signature(SaveManager.verify_lineage)
    assert list(lineage.parameters) == ["self", "parent_episode", "child_episode"]


@pytest.mark.parametrize("cls", [EpisodeManifest, FileMetadata, LoadedEpisode])
def test_persistence_metadata_is_frozen_and_slotted(cls: type) -> None:
    """Metadata describing a save must not be editable after it is handed out."""
    assert cls.__dataclass_params__.frozen is True  # type: ignore[attr-defined]
    assert hasattr(cls, "__slots__")


def test_every_public_symbol_is_documented() -> None:
    """A public name without a docstring is a name nobody has to explain."""
    for name in persistence.__all__:
        symbol = getattr(persistence, name)
        if inspect.isclass(symbol) or inspect.isfunction(symbol):
            assert inspect.getdoc(symbol), name


def test_the_package_module_is_documented() -> None:
    """Including the dependency direction, which is the load-bearing rule."""
    documentation = inspect.getdoc(persistence)
    assert documentation
    assert "persistence" in documentation.lower()
