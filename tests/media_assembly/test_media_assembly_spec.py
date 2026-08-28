"""Naming law, frame-filename grammar, and directory-shape vocabulary for Phase 33.

This module owns no filesystem behaviour and no cross-document proof -- only
the deterministic vocabulary every other Phase 33 module shares. These tests
prove that vocabulary matches its two real upstream owners exactly where one
exists (``render_id`` for directory identity, the two genuine upstream
filename constants), and is pinned exactly where none exists.
"""

import pytest

from living_diorama.audio_composition.audio_composition_spec import (
    AUDIO_COMPOSITION_MANIFEST_FILENAME,
)
from living_diorama.media_assembly import media_assembly_spec as spec
from living_diorama.render_execution.render_execution_spec import (
    RENDER_MANIFEST_FILENAME,
    render_id,
)
from living_diorama.voice_execution import voice_execution_id

# ---------------------------------------------------------------------------
# media_assembly_id -- delegates whole to render_id
# ---------------------------------------------------------------------------


def test_media_assembly_id_agrees_with_render_id_baseline() -> None:
    """Media assembly ID agrees with render ID baseline."""
    got = spec.media_assembly_id(mode="baseline", episode=0, previous_episode=None)
    assert got == render_id(mode="baseline", episode=0, previous_episode=None)
    assert got == "episode_0000_baseline"


def test_media_assembly_id_agrees_with_render_id_transition() -> None:
    """Media assembly ID agrees with render ID transition."""
    got = spec.media_assembly_id(mode="transition", episode=1, previous_episode=0)
    assert got == render_id(mode="transition", episode=1, previous_episode=0)
    assert got == "episode_0000_to_0001"


def test_media_assembly_id_does_not_reimplement_voice_execution_id_by_coincidence() -> None:
    """It agrees with ``render_id``, not merely with any plausible naming law."""
    got = spec.media_assembly_id(mode="baseline", episode=0, previous_episode=None)
    assert got == voice_execution_id(mode="baseline", episode=0, previous_episode=None)


def test_media_assembly_id_refuses_a_baseline_with_a_previous_episode() -> None:
    """Media assembly ID refuses a baseline with a previous episode."""
    with pytest.raises(ValueError):
        spec.media_assembly_id(mode="baseline", episode=0, previous_episode=0)


def test_media_assembly_id_refuses_non_succession() -> None:
    """Media assembly ID refuses non succession."""
    with pytest.raises(ValueError):
        spec.media_assembly_id(mode="transition", episode=5, previous_episode=1)


def test_media_assembly_id_refuses_a_negative_episode() -> None:
    """Media assembly ID refuses a negative episode."""
    with pytest.raises(ValueError):
        spec.media_assembly_id(mode="baseline", episode=-1, previous_episode=None)


def test_media_assembly_id_refuses_a_bool_episode() -> None:
    """Media assembly ID refuses a bool episode."""
    with pytest.raises(TypeError):
        spec.media_assembly_id(mode="baseline", episode=True, previous_episode=None)  # type: ignore[arg-type]


def test_media_assembly_id_refuses_an_unknown_mode() -> None:
    """Media assembly ID refuses an unknown mode."""
    with pytest.raises(ValueError):
        spec.media_assembly_id(mode="remix", episode=0, previous_episode=None)


# ---------------------------------------------------------------------------
# presentation_frame_filename -- the seven-digit grammar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (1, "frame_0000001.png"),
        (999_999, "frame_0999999.png"),
        (1_000_000, "frame_1000000.png"),
    ],
)
def test_presentation_frame_filename_at_the_boundaries(frame: int, expected: str) -> None:
    """Presentation frame filename at the boundaries."""
    assert spec.presentation_frame_filename(frame) == expected


@pytest.mark.parametrize("bad", [0, -1, 1_000_001])
def test_presentation_frame_filename_refuses_out_of_range(bad: int) -> None:
    """Presentation frame filename refuses out of range."""
    with pytest.raises(ValueError):
        spec.presentation_frame_filename(bad)


def test_presentation_frame_filename_refuses_bool() -> None:
    """Presentation frame filename refuses bool."""
    with pytest.raises(TypeError):
        spec.presentation_frame_filename(True)  # type: ignore[arg-type]


def test_presentation_frame_filename_refuses_float() -> None:
    """Presentation frame filename refuses float."""
    with pytest.raises(TypeError):
        spec.presentation_frame_filename(1.0)  # type: ignore[arg-type]


def test_presentation_frame_filename_refuses_str() -> None:
    """Presentation frame filename refuses str."""
    with pytest.raises(TypeError):
        spec.presentation_frame_filename("1")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# is_presentation_frame_filename
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "frame_0000001.png",
        "frame_0999999.png",
        "frame_1000000.png",
    ],
)
def test_is_presentation_frame_filename_accepts_legal_names(name: str) -> None:
    """Is presentation frame filename accepts legal names."""
    assert spec.is_presentation_frame_filename(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "frame_000001.png",  # wrong length: six digits
        "frame_00000001.png",  # wrong length: eight digits
        "franme_0000001.png",  # wrong prefix
        "frame_0000001.jpg",  # wrong suffix
        "frame_0000000.png",  # zero, out of range
        "frame_1000001.png",  # one past the ceiling
        "frame_-000001.png",  # sign character, not a digit
        "",
        "frame_.png",
    ],
)
def test_is_presentation_frame_filename_refuses_structural_defects(name: str) -> None:
    """Is presentation frame filename refuses structural defects."""
    assert spec.is_presentation_frame_filename(name) is False


@pytest.mark.parametrize(
    "name",
    [
        "frame_０１２３４５６.png",  # fullwidth digits
        "frame_٠١٢٣٤٥٦.png",  # Arabic-Indic digits
    ],
)
def test_is_presentation_frame_filename_refuses_non_ascii_digits(name: str) -> None:
    """Is presentation frame filename refuses non ascii digits."""
    assert spec.is_presentation_frame_filename(name) is False


# ---------------------------------------------------------------------------
# The five *_COPY_FILENAME drift tests
# ---------------------------------------------------------------------------


def test_render_manifest_copy_filename_agrees_with_render_execution() -> None:
    """Render manifest copy filename agrees with render execution."""
    assert spec.RENDER_MANIFEST_COPY_FILENAME == RENDER_MANIFEST_FILENAME


def test_audio_composition_manifest_copy_filename_agrees_with_audio_composition() -> None:
    """Audio composition manifest copy filename agrees with audio composition."""
    assert spec.AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME == AUDIO_COMPOSITION_MANIFEST_FILENAME


def test_presentation_plan_copy_filename_is_pinned() -> None:
    """No upstream Phase 27 filename constant exists; this is Phase 33's own name, pinned."""
    assert spec.PRESENTATION_PLAN_COPY_FILENAME == "episode_presentation_plan.json"


def test_delivery_plan_copy_filename_is_pinned() -> None:
    """No upstream Phase 25 filename constant exists; this is Phase 33's own name, pinned."""
    assert spec.DELIVERY_PLAN_COPY_FILENAME == "episode_narration_delivery_plan.json"


def test_shot_plan_copy_filename_is_pinned() -> None:
    """No upstream Phase 22 filename constant exists; this is Phase 33's own name, pinned."""
    assert spec.SHOT_PLAN_COPY_FILENAME == "shot_direction_plan.json"


# ---------------------------------------------------------------------------
# ROLE_PLAYBACK drift test
# ---------------------------------------------------------------------------


def test_role_playback_agrees_with_render_execution() -> None:
    """Role playback agrees with render execution."""
    from living_diorama.render_execution.render_execution_spec import ROLE_PLAYBACK

    assert spec.ROLE_PLAYBACK == ROLE_PLAYBACK


# ---------------------------------------------------------------------------
# Directory-entry sets
# ---------------------------------------------------------------------------


def test_assembly_directory_entries_has_exactly_seven_members() -> None:
    """Assembly directory entries has exactly seven members."""
    assert len(spec.ASSEMBLY_DIRECTORY_ENTRIES) == 7


def test_provenance_directory_entries_has_exactly_two_members() -> None:
    """Provenance directory entries has exactly two members."""
    assert len(spec.PROVENANCE_DIRECTORY_ENTRIES) == 2


# ---------------------------------------------------------------------------
# Relative-path helpers
# ---------------------------------------------------------------------------


def test_presentation_frame_relative_path() -> None:
    """Presentation frame relative path."""
    assert spec.presentation_frame_relative_path(3) == "presentation/frame_0000003.png"


def test_episode_audio_relative_path() -> None:
    """Episode audio relative path."""
    assert spec.episode_audio_relative_path() == "audio/episode_audio.wav"


def test_delivery_plan_relative_path() -> None:
    """Delivery plan relative path."""
    assert spec.delivery_plan_relative_path() == "provenance/episode_narration_delivery_plan.json"


def test_shot_plan_relative_path() -> None:
    """Shot plan relative path."""
    assert spec.shot_plan_relative_path() == "provenance/shot_direction_plan.json"


# ---------------------------------------------------------------------------
# classify_media_assembly_directory_entry / classify_provenance_directory_entry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(spec.ASSEMBLY_DIRECTORY_ENTRIES))
def test_classify_media_assembly_directory_entry_owned(name: str) -> None:
    """Classify media assembly directory entry owned."""
    is_dir = name in {spec.PRESENTATION_DIRECTORY, spec.AUDIO_DIRECTORY, spec.PROVENANCE_DIRECTORY}
    assert spec.classify_media_assembly_directory_entry(name, is_directory=is_dir) == "owned"


def test_classify_media_assembly_directory_entry_partial() -> None:
    """Classify media assembly directory entry partial."""
    name = spec.MEDIA_ASSEMBLY_MANIFEST_FILENAME + spec.WRITING_SUFFIX
    assert spec.classify_media_assembly_directory_entry(name) == "partial"


def test_classify_media_assembly_directory_entry_writing_directory_is_foreign() -> None:
    """Classify media assembly directory entry writing directory is foreign."""
    name = spec.MEDIA_ASSEMBLY_MANIFEST_FILENAME + spec.WRITING_SUFFIX
    assert spec.classify_media_assembly_directory_entry(name, is_directory=True) == "foreign"


def test_classify_media_assembly_directory_entry_foreign() -> None:
    """Classify media assembly directory entry foreign."""
    assert spec.classify_media_assembly_directory_entry("intruder.txt") == "foreign"


@pytest.mark.parametrize("name", list(spec.PROVENANCE_DIRECTORY_ENTRIES))
def test_classify_provenance_directory_entry_owned(name: str) -> None:
    """Classify provenance directory entry owned."""
    assert spec.classify_provenance_directory_entry(name) == "owned"


def test_classify_provenance_directory_entry_partial() -> None:
    """Classify provenance directory entry partial."""
    name = spec.SHOT_PLAN_COPY_FILENAME + spec.WRITING_SUFFIX
    assert spec.classify_provenance_directory_entry(name) == "partial"


def test_classify_provenance_directory_entry_foreign() -> None:
    """Classify provenance directory entry foreign."""
    assert spec.classify_provenance_directory_entry("intruder.txt") == "foreign"
