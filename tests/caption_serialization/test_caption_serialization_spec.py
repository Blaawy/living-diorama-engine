"""Phase 34 caption serialization vocabulary: naming law, suffixes and the carriage law.

This module owns no serialization behaviour and no cross-document proof -- only
the deterministic vocabulary every other Phase 34 module shares. These tests
prove that vocabulary matches its real upstream owner exactly where one exists
(``render_id`` for directory identity), and is pinned exactly where none exists.
The carriage-law refusals themselves are owned by W02; this suite carries one
smoke test per refusal class.
"""

import pytest

from living_diorama.caption_serialization import caption_serialization_spec as spec
from living_diorama.render_execution.render_execution_spec import render_id

# ---------------------------------------------------------------------------
# Pinned constants
# ---------------------------------------------------------------------------


def test_manifest_format_literal_is_pinned() -> None:
    """Manifest format literal is pinned."""
    assert spec.CAPTION_SERIALIZATION_MANIFEST_FORMAT == (
        "living_diorama_episode_caption_serialization_manifest"
    )


def test_schema_version_is_one() -> None:
    """Schema version is one."""
    assert spec.CAPTION_SERIALIZATION_SCHEMA_VERSION == 1


def test_timestamp_policy_literal_is_pinned() -> None:
    """Timestamp policy literal is pinned."""
    assert spec.CAPTION_TIMESTAMP_POLICY_V1 == "caption_timestamp_policy_v1"


def test_max_timestamp_ms_is_360_million() -> None:
    """Max timestamp ms is 360 million."""
    assert spec.MAX_TIMESTAMP_MS == 360_000_000


def test_sidecar_suffixes_are_pinned() -> None:
    """Sidecar suffixes are pinned."""
    assert spec.SRT_SUFFIX == ".srt"
    assert spec.VTT_SUFFIX == ".vtt"


def test_sidecar_format_names_are_pinned() -> None:
    """Sidecar format names are pinned."""
    assert spec.SRT_FORMAT_NAME == "srt"
    assert spec.VTT_FORMAT_NAME == "webvtt"


def test_partial_and_writing_suffixes_are_pinned() -> None:
    """Partial and writing suffixes are pinned."""
    assert spec.PARTIAL_SUFFIX == ".partial"
    assert spec.WRITING_SUFFIX == ".writing"


# ---------------------------------------------------------------------------
# caption_serialization_id -- delegates whole to render_id
# ---------------------------------------------------------------------------


def test_caption_serialization_id_baseline_agrees_with_render_id() -> None:
    """Caption serialization id baseline agrees with render id."""
    got = spec.caption_serialization_id(mode="baseline", episode=0, previous_episode=None)
    assert got == render_id(mode="baseline", episode=0, previous_episode=None)
    assert got == "episode_0000_baseline"


def test_caption_serialization_id_transition_agrees_with_render_id() -> None:
    """Caption serialization id transition agrees with render id."""
    got = spec.caption_serialization_id(mode="transition", episode=1, previous_episode=0)
    assert got == render_id(mode="transition", episode=1, previous_episode=0)
    assert got == "episode_0000_to_0001"


def test_caption_serialization_id_refuses_non_succession() -> None:
    """Caption serialization id refuses non succession."""
    with pytest.raises(ValueError):
        spec.caption_serialization_id(mode="transition", episode=5, previous_episode=1)


def test_caption_serialization_id_refuses_baseline_with_previous() -> None:
    """Caption serialization id refuses a baseline with a previous episode."""
    with pytest.raises(ValueError):
        spec.caption_serialization_id(mode="baseline", episode=0, previous_episode=0)


def test_caption_serialization_id_refuses_bool_episode() -> None:
    """Caption serialization id refuses a bool episode."""
    with pytest.raises(TypeError):
        spec.caption_serialization_id(
            mode="baseline",
            episode=True,
            previous_episode=None,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# sidecar_filename
# ---------------------------------------------------------------------------


def test_sidecar_filename_appends_the_suffix() -> None:
    """Sidecar filename appends the suffix."""
    episode_id = "episode_0000_to_0001"
    assert spec.sidecar_filename(episode_id, ".srt") == f"{episode_id}.srt"
    assert spec.sidecar_filename(episode_id, ".vtt") == f"{episode_id}.vtt"


def test_sidecar_filename_refuses_unknown_suffix() -> None:
    """Sidecar filename refuses an unknown suffix."""
    with pytest.raises(ValueError):
        spec.sidecar_filename("episode_0000_baseline", ".txt")


def test_sidecar_filename_refuses_non_str() -> None:
    """Sidecar filename refuses non str."""
    with pytest.raises(TypeError):
        spec.sidecar_filename(7, ".srt")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        spec.sidecar_filename("episode_0000_baseline", 7)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# require_carriable_caption_text -- W02 owns the refusals; one smoke each
# ---------------------------------------------------------------------------


def test_require_carriable_caption_text_returns_plain_prose() -> None:
    """Require carriable caption text returns plain prose unchanged."""
    text = "The wind carried the gate's message across the field."
    assert spec.require_carriable_caption_text(text, "caption 1 text") == text


def test_require_carriable_caption_text_refuses_empty_text() -> None:
    """Require carriable caption text refuses empty text."""
    with pytest.raises(spec.CaptionSerializationRefused):
        spec.require_carriable_caption_text("", "caption 1 text")


def test_require_carriable_caption_text_refuses_a_control_character() -> None:
    """Require carriable caption text refuses a control character."""
    with pytest.raises(spec.CaptionSerializationRefused):
        spec.require_carriable_caption_text("line one\nline two", "caption 1 text")


def test_require_carriable_caption_text_refuses_the_cue_timing_arrow() -> None:
    """Require carriable caption text refuses the cue timing arrow."""
    with pytest.raises(spec.CaptionSerializationRefused):
        spec.require_carriable_caption_text("a --> b", "caption 1 text")


def test_require_carriable_caption_text_refuses_a_line_separator() -> None:
    """Require carriable caption text refuses a line separator."""
    with pytest.raises(spec.CaptionSerializationRefused):
        spec.require_carriable_caption_text("one\u2028two", "caption 1 text")
