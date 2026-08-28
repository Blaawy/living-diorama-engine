"""Unit tests for the Phase 31 audio composition policy: naming and directory shape."""

import pytest

from living_diorama.audio_composition.audio_composition_spec import (
    AUDIO_COMPOSITION_MANIFEST_FILENAME,
    AUDIO_DIRECTORY,
    AUDIO_TRACK_PLAN_FILENAME,
    COMPOSITION_DIRECTORY_ENTRIES,
    EPISODE_AUDIO_FILENAME,
    VOICE_MANIFEST_FILENAME,
    audio_composition_id,
    classify_audio_composition_directory_entry,
    episode_audio_relative_path,
)


def test_composition_directory_entries_is_exactly_four() -> None:
    """Composition directory entries is exactly four."""
    assert (
        frozenset(
            {
                AUDIO_TRACK_PLAN_FILENAME,
                VOICE_MANIFEST_FILENAME,
                AUDIO_DIRECTORY,
                AUDIO_COMPOSITION_MANIFEST_FILENAME,
            }
        )
        == COMPOSITION_DIRECTORY_ENTRIES
    )
    assert len(COMPOSITION_DIRECTORY_ENTRIES) == 4


def test_episode_audio_relative_path_is_positional() -> None:
    """Episode audio relative path is positional."""
    assert episode_audio_relative_path() == f"{AUDIO_DIRECTORY}/{EPISODE_AUDIO_FILENAME}"


def test_audio_composition_id_matches_voice_execution_id_baseline() -> None:
    """Audio composition ID matches voice execution ID baseline."""
    assert audio_composition_id(mode="baseline", episode=0, previous_episode=None) == (
        "episode_0000_baseline"
    )


def test_audio_composition_id_matches_voice_execution_id_transition() -> None:
    """Audio composition ID matches voice execution ID transition."""
    assert audio_composition_id(mode="transition", episode=1, previous_episode=0) == (
        "episode_0000_to_0001"
    )


def test_audio_composition_id_refuses_baseline_with_previous() -> None:
    """Audio composition ID refuses baseline with previous."""
    with pytest.raises(ValueError):
        audio_composition_id(mode="baseline", episode=0, previous_episode=0)


def test_audio_composition_id_refuses_non_successive_transition() -> None:
    """Audio composition ID refuses non successive transition."""
    with pytest.raises(ValueError):
        audio_composition_id(mode="transition", episode=5, previous_episode=1)


def test_audio_composition_id_refuses_unknown_mode() -> None:
    """Audio composition ID refuses unknown mode."""
    with pytest.raises(ValueError):
        audio_composition_id(mode="weird", episode=0, previous_episode=None)


def test_audio_composition_id_refuses_wrong_type() -> None:
    """Audio composition ID refuses wrong type."""
    with pytest.raises(TypeError):
        audio_composition_id(mode="baseline", episode=True, previous_episode=None)


def test_classify_owned_entries() -> None:
    """Classify owned entries."""
    for name in COMPOSITION_DIRECTORY_ENTRIES:
        assert (
            classify_audio_composition_directory_entry(name, is_directory=(name == AUDIO_DIRECTORY))
            == "owned"
        )


def test_classify_partial_writing_forms() -> None:
    """Classify partial writing forms."""
    for name in (
        AUDIO_TRACK_PLAN_FILENAME,
        VOICE_MANIFEST_FILENAME,
        AUDIO_COMPOSITION_MANIFEST_FILENAME,
    ):
        assert classify_audio_composition_directory_entry(f"{name}.writing") == "partial"


def test_classify_foreign_entries() -> None:
    """Classify foreign entries."""
    assert classify_audio_composition_directory_entry("stray.txt") == "foreign"
    assert classify_audio_composition_directory_entry("speech") == "foreign"
    assert classify_audio_composition_directory_entry("episode_voice_plan.json") == "foreign"


def test_classify_directory_writing_form_is_foreign() -> None:
    # A directory named "<name>.writing" is not the documented partial shape
    # (documents get .writing siblings; directories do not).
    """Classify directory writing form is foreign."""
    assert (
        classify_audio_composition_directory_entry(f"{AUDIO_DIRECTORY}.writing", is_directory=True)
        == "foreign"
    )
