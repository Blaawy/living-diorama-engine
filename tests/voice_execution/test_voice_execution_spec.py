"""Unit tests for the Phase 29 voice execution policy: naming and directory shape."""

import pytest

from living_diorama.voice_execution.voice_execution_spec import (
    MAX_SPEECH_SAMPLES,
    UNIT_RESULT_FIELDS,
    classify_voice_directory_entry,
    unit_audio_filename,
    voice_execution_id,
)


def test_a_baseline_id_is_zero_padded() -> None:
    """A baseline id is zero-padded."""
    assert voice_execution_id(mode="baseline", episode=0, previous_episode=None) == (
        "episode_0000_baseline"
    )
    assert voice_execution_id(mode="baseline", episode=7, previous_episode=None) == (
        "episode_0007_baseline"
    )


def test_a_transition_id_names_both_episodes() -> None:
    """A transition id names both episodes."""
    assert voice_execution_id(mode="transition", episode=1, previous_episode=0) == (
        "episode_0000_to_0001"
    )
    assert voice_execution_id(mode="transition", episode=2, previous_episode=1) == (
        "episode_0001_to_0002"
    )


def test_a_baseline_with_a_previous_episode_is_refused() -> None:
    """A baseline with a previous episode is refused."""
    with pytest.raises(ValueError, match="no previous episode"):
        voice_execution_id(mode="baseline", episode=0, previous_episode=0)


def test_a_transition_with_no_previous_episode_is_refused() -> None:
    """A transition with no previous episode is refused."""
    with pytest.raises(TypeError):
        voice_execution_id(mode="transition", episode=1, previous_episode=None)


def test_a_transition_joining_nonconsecutive_episodes_is_refused() -> None:
    """A transition joining nonconsecutive episodes is refused."""
    with pytest.raises(ValueError, match="does not directly follow"):
        voice_execution_id(mode="transition", episode=5, previous_episode=1)


def test_a_bool_episode_is_refused() -> None:
    """A bool episode is refused."""
    with pytest.raises(TypeError):
        voice_execution_id(mode="baseline", episode=True, previous_episode=None)


def test_a_negative_episode_is_refused() -> None:
    """A negative episode is refused."""
    with pytest.raises(ValueError, match="not be negative"):
        voice_execution_id(mode="baseline", episode=-1, previous_episode=None)


def test_a_bool_previous_episode_is_refused() -> None:
    """A bool previous_episode is refused."""
    with pytest.raises(TypeError):
        voice_execution_id(mode="transition", episode=1, previous_episode=True)


def test_a_negative_previous_episode_is_refused() -> None:
    """A negative previous_episode is refused."""
    with pytest.raises(ValueError, match="not be negative"):
        voice_execution_id(mode="transition", episode=0, previous_episode=-1)


def test_an_unknown_mode_is_refused() -> None:
    """An unknown mode is refused."""
    with pytest.raises(ValueError, match="unknown episode mode"):
        voice_execution_id(mode="sequel", episode=0, previous_episode=None)


def test_a_non_str_mode_is_refused() -> None:
    """A non-str mode is refused."""
    with pytest.raises(TypeError):
        voice_execution_id(mode=1, episode=0, previous_episode=None)  # type: ignore[arg-type]


def test_unit_audio_filename_is_zero_padded_and_positional() -> None:
    """unit_audio_filename is zero-padded and positional."""
    assert unit_audio_filename(1) == "voice_unit_0001.wav"
    assert unit_audio_filename(42) == "voice_unit_0042.wav"


def test_unit_audio_filename_refuses_non_positive() -> None:
    """unit_audio_filename refuses non-positive positions."""
    with pytest.raises(ValueError, match="positive"):
        unit_audio_filename(0)
    with pytest.raises(ValueError, match="positive"):
        unit_audio_filename(-1)


def test_unit_audio_filename_refuses_a_bool() -> None:
    """unit_audio_filename refuses a bool position."""
    with pytest.raises(TypeError):
        unit_audio_filename(True)  # type: ignore[arg-type]


def test_unit_audio_filename_refuses_beyond_the_naming_field() -> None:
    """unit_audio_filename refuses a position beyond the four-digit field."""
    with pytest.raises(ValueError, match="four-digit"):
        unit_audio_filename(10000)


@pytest.mark.parametrize(
    ("name", "is_directory", "expected"),
    [
        ("episode_voice_plan.json", False, "owned"),
        ("episode_voice_manifest.json", False, "owned"),
        ("speech", True, "owned"),
        ("episode_voice_plan.json.writing", False, "partial"),
        ("episode_voice_manifest.json.writing", False, "partial"),
        ("episode_voice_plan.json.writing", True, "foreign"),
        ("random_file.txt", False, "foreign"),
        # Classification is by name alone, exactly as the Phase 23 precedent
        # (`classify_render_directory_entry`) also decides "owned" by name
        # membership without itself checking type -- a file masquerading as
        # the owned directory name is still caught, just by the caller's own
        # later `.is_dir()` / `.iterdir()` structural checks, not by this
        # classifier.
        ("speech", False, "owned"),
        ("evil.writing", False, "foreign"),
    ],
)
def test_classify_voice_directory_entry_matches_the_reviewed_table(
    name: str, is_directory: bool, expected: str
) -> None:
    """classify_voice_directory_entry matches the reviewed owned/partial/foreign table."""
    assert classify_voice_directory_entry(name, is_directory=is_directory) == expected


def test_max_speech_samples_is_the_frozen_phase29_constant() -> None:
    """MAX_SPEECH_SAMPLES is the frozen Phase 29 constant."""
    assert MAX_SPEECH_SAMPLES == 1_000_000_000


def test_unit_result_fields_is_exactly_the_three_measured_facts() -> None:
    """UNIT_RESULT_FIELDS is exactly the three measured facts."""
    assert UNIT_RESULT_FIELDS == ("bytes", "sha256", "speech_samples")
