"""Standalone shape validation for the Episode Media Assembly Manifest V1.

Every test here works from a real, published manifest -- built by the real
publisher against real fixture sources -- so a mutation test proves something
about a document the engine could actually have written, never a hand-typed
fixture nobody's code would produce.
"""

import copy
from pathlib import Path
from typing import Any

import pytest

from living_diorama.media_assembly.media_assembly_schema_v1 import (
    AUDIO_KEYS,
    CLOCK_KEYS,
    COMPLETENESS_KEYS,
    FRAME_KEYS,
    SOURCE_KEYS,
    TOP_LEVEL_KEYS,
    validate_episode_media_assembly_manifest,
)
from living_diorama.media_assembly.media_assembly_spec import MEDIA_ASSEMBLY_MANIFEST_FILENAME
from living_diorama.persistence.json_codec import loads_canonical


@pytest.fixture
def manifest(assembly_dir_ep1: Path) -> dict[str, Any]:
    """A real, valid, published Phase 33 manifest document."""
    raw = (assembly_dir_ep1 / MEDIA_ASSEMBLY_MANIFEST_FILENAME).read_bytes()
    return loads_canonical(raw, "episode media assembly manifest")  # type: ignore[return-value]


def test_a_real_manifest_validates(manifest: dict[str, Any]) -> None:
    """A real manifest validates."""
    assert validate_episode_media_assembly_manifest(copy.deepcopy(manifest)) == manifest


# ---------------------------------------------------------------------------
# Exact key-set sizes
# ---------------------------------------------------------------------------


def test_top_level_keys_has_seven_members() -> None:
    """Top level keys has seven members."""
    assert len(TOP_LEVEL_KEYS) == 7


def test_source_keys_has_twelve_members() -> None:
    """Source keys has twelve members."""
    assert len(SOURCE_KEYS) == 12


def test_clock_keys_has_eight_members() -> None:
    """Clock keys has eight members."""
    assert len(CLOCK_KEYS) == 8


def test_frame_keys_has_five_members() -> None:
    """Frame keys has five members."""
    assert len(FRAME_KEYS) == 5


def test_audio_keys_has_six_members() -> None:
    """Audio keys has six members."""
    assert len(AUDIO_KEYS) == 6


def test_completeness_keys_has_four_members() -> None:
    """Completeness keys has four members."""
    assert len(COMPLETENESS_KEYS) == 4


def test_completeness_keys_includes_unique_semantic_frames_used() -> None:
    """Completeness keys includes unique semantic frames used."""
    assert "unique_semantic_frames_used" in COMPLETENESS_KEYS


@pytest.mark.parametrize(
    "keyset", [TOP_LEVEL_KEYS, SOURCE_KEYS, CLOCK_KEYS, FRAME_KEYS, AUDIO_KEYS, COMPLETENESS_KEYS]
)
def test_no_block_carries_a_link_count_key(keyset: frozenset[str]) -> None:
    """``st_nlink`` is a filesystem property measured at audit time, never a document claim."""
    for key in keyset:
        assert "link" not in key.lower()
        assert "nlink" not in key.lower()


# ---------------------------------------------------------------------------
# Missing / extra key refusal, at every block
# ---------------------------------------------------------------------------


def test_missing_top_level_key_refused(manifest: dict[str, Any]) -> None:
    """Missing top level key refused."""
    broken = copy.deepcopy(manifest)
    del broken["clock"]
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(broken)


def test_extra_top_level_key_refused(manifest: dict[str, Any]) -> None:
    """Extra top level key refused."""
    broken = copy.deepcopy(manifest)
    broken["policy"] = "v1"
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(broken)


def test_missing_source_key_refused(manifest: dict[str, Any]) -> None:
    """Missing source key refused."""
    broken = copy.deepcopy(manifest)
    del broken["source"]["shot_plan_sha256"]
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(broken)


def test_extra_source_key_refused(manifest: dict[str, Any]) -> None:
    """Extra source key refused."""
    broken = copy.deepcopy(manifest)
    broken["source"]["caption_plan_sha256"] = "0" * 64
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(broken)


def test_missing_clock_key_refused(manifest: dict[str, Any]) -> None:
    """Missing clock key refused."""
    broken = copy.deepcopy(manifest)
    del broken["clock"]["witness_frame"]
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(broken)


def test_extra_clock_key_refused(manifest: dict[str, Any]) -> None:
    """Extra clock key refused."""
    broken = copy.deepcopy(manifest)
    broken["clock"]["frame_rate"] = 24
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(broken)


def test_missing_frame_key_refused(manifest: dict[str, Any]) -> None:
    """Missing frame key refused."""
    broken = copy.deepcopy(manifest)
    del broken["frames"][0]["sha256"]
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(broken)


def test_extra_frame_key_refused(manifest: dict[str, Any]) -> None:
    """Extra frame key refused."""
    broken = copy.deepcopy(manifest)
    broken["frames"][0]["image_sha256"] = "0" * 64
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(broken)


def test_missing_audio_key_refused(manifest: dict[str, Any]) -> None:
    """Missing audio key refused."""
    broken = copy.deepcopy(manifest)
    del broken["audio"]["channels"]
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(broken)


def test_extra_audio_key_refused(manifest: dict[str, Any]) -> None:
    """Extra audio key refused."""
    broken = copy.deepcopy(manifest)
    broken["audio"]["duration_seconds"] = 30.0
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(broken)


def test_missing_completeness_key_refused(manifest: dict[str, Any]) -> None:
    """Missing completeness key refused."""
    broken = copy.deepcopy(manifest)
    del broken["completeness"]["complete"]
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(broken)


def test_extra_completeness_key_refused(manifest: dict[str, Any]) -> None:
    """Extra completeness key refused."""
    broken = copy.deepcopy(manifest)
    broken["completeness"]["dropped_frames"] = 0
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(broken)


# ---------------------------------------------------------------------------
# format / schema_version pinned
# ---------------------------------------------------------------------------


def test_wrong_format_refused(manifest: dict[str, Any]) -> None:
    """Wrong format refused."""
    broken = copy.deepcopy(manifest)
    broken["format"] = "living_diorama_episode_audio_composition_manifest"
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_wrong_schema_version_refused(manifest: dict[str, Any]) -> None:
    """Wrong schema version refused."""
    broken = copy.deepcopy(manifest)
    broken["schema_version"] = 2
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


# ---------------------------------------------------------------------------
# Strict types
# ---------------------------------------------------------------------------


def test_manifest_must_be_a_dict() -> None:
    """Manifest must be a dict."""
    with pytest.raises(TypeError):
        validate_episode_media_assembly_manifest(["not", "a", "dict"])


def test_frames_must_be_a_list(manifest: dict[str, Any]) -> None:
    """Frames must be a list."""
    broken = copy.deepcopy(manifest)
    broken["frames"] = {}
    with pytest.raises(TypeError):
        validate_episode_media_assembly_manifest(broken)


def test_source_episode_bool_refused(manifest: dict[str, Any]) -> None:
    """Source episode bool refused."""
    broken = copy.deepcopy(manifest)
    broken["source"]["episode"] = True
    with pytest.raises(TypeError):
        validate_episode_media_assembly_manifest(broken)


def test_completeness_complete_non_bool_refused(manifest: dict[str, Any]) -> None:
    """Completeness complete non bool refused."""
    broken = copy.deepcopy(manifest)
    broken["completeness"]["complete"] = 1
    with pytest.raises(TypeError):
        validate_episode_media_assembly_manifest(broken)


# ---------------------------------------------------------------------------
# Positional laws
# ---------------------------------------------------------------------------


def test_frame_out_of_position_refused(manifest: dict[str, Any]) -> None:
    """Frame out of position refused."""
    broken = copy.deepcopy(manifest)
    broken["frames"][0]["presentation_frame"] = 999
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_frame_count_disagreeing_with_clock_refused(manifest: dict[str, Any]) -> None:
    """Frame count disagreeing with clock refused."""
    broken = copy.deepcopy(manifest)
    broken["frames"].pop()
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_frame_file_disagreeing_with_position_refused(manifest: dict[str, Any]) -> None:
    """Frame file disagreeing with position refused."""
    broken = copy.deepcopy(manifest)
    broken["frames"][0]["file"] = "presentation/frame_9999999.png"
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


# ---------------------------------------------------------------------------
# semantic_frame range and witness exclusion
# ---------------------------------------------------------------------------


def test_semantic_frame_below_range_refused(manifest: dict[str, Any]) -> None:
    """Semantic frame below range refused."""
    broken = copy.deepcopy(manifest)
    broken["frames"][0]["semantic_frame"] = 0
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_semantic_frame_above_range_refused(manifest: dict[str, Any]) -> None:
    """Semantic frame above range refused."""
    broken = copy.deepcopy(manifest)
    witness = broken["clock"]["witness_frame"]
    broken["frames"][0]["semantic_frame"] = witness + 1
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_witness_frame_never_a_semantic_frame(manifest: dict[str, Any]) -> None:
    """Witness frame never a semantic frame."""
    broken = copy.deepcopy(manifest)
    broken["frames"][0]["semantic_frame"] = broken["clock"]["witness_frame"]
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


# ---------------------------------------------------------------------------
# Hash fields via require_hash_hex
# ---------------------------------------------------------------------------


def test_source_digest_not_hex_refused(manifest: dict[str, Any]) -> None:
    """Source digest not hex refused."""
    broken = copy.deepcopy(manifest)
    broken["source"]["render_manifest_sha256"] = "not-a-digest"
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_source_digest_wrong_length_refused(manifest: dict[str, Any]) -> None:
    """Source digest wrong length refused."""
    broken = copy.deepcopy(manifest)
    broken["source"]["render_manifest_sha256"] = "abc123"
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_source_digest_uppercase_refused(manifest: dict[str, Any]) -> None:
    """Source digest uppercase refused."""
    broken = copy.deepcopy(manifest)
    broken["source"]["render_manifest_sha256"] = broken["source"]["render_manifest_sha256"].upper()
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_frame_sha256_not_hex_refused(manifest: dict[str, Any]) -> None:
    """Frame sha256 not hex refused."""
    broken = copy.deepcopy(manifest)
    broken["frames"][0]["sha256"] = "zz" * 32
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_audio_sha256_not_hex_refused(manifest: dict[str, Any]) -> None:
    """Audio sha256 not hex refused."""
    broken = copy.deepcopy(manifest)
    broken["audio"]["sha256"] = "zz" * 32
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


# ---------------------------------------------------------------------------
# Clock closure law
# ---------------------------------------------------------------------------


def test_clock_sample_rate_not_divisible_by_fps_refused(manifest: dict[str, Any]) -> None:
    """Clock sample rate not divisible by fps refused."""
    broken = copy.deepcopy(manifest)
    broken["clock"]["audio_sample_rate_hz"] = 44100
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_clock_samples_per_presentation_frame_wrong_refused(manifest: dict[str, Any]) -> None:
    """Clock samples per presentation frame wrong refused."""
    broken = copy.deepcopy(manifest)
    broken["clock"]["samples_per_presentation_frame"] += 1
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_clock_audio_samples_total_wrong_refused(manifest: dict[str, Any]) -> None:
    """Clock audio samples total wrong refused."""
    broken = copy.deepcopy(manifest)
    broken["clock"]["audio_samples_total"] += 1000
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_clock_witness_frame_disagreeing_with_semantic_final_refused(
    manifest: dict[str, Any],
) -> None:
    """Clock witness frame disagreeing with semantic final refused."""
    broken = copy.deepcopy(manifest)
    broken["clock"]["witness_frame"] += 5
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


# ---------------------------------------------------------------------------
# Completeness measured, not asserted
# ---------------------------------------------------------------------------


def test_completeness_assembled_count_disagreeing_with_records_refused(
    manifest: dict[str, Any],
) -> None:
    """Completeness assembled count disagreeing with records refused."""
    broken = copy.deepcopy(manifest)
    broken["completeness"]["presentation_frames_assembled"] -= 1
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_completeness_unique_semantic_frames_used_wrong_refused(manifest: dict[str, Any]) -> None:
    """Completeness unique semantic frames used wrong refused."""
    broken = copy.deepcopy(manifest)
    broken["completeness"]["unique_semantic_frames_used"] += 1
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_completeness_complete_disagreeing_with_measured_counts_refused(
    manifest: dict[str, Any],
) -> None:
    """Completeness complete disagreeing with measured counts refused."""
    broken = copy.deepcopy(manifest)
    broken["completeness"]["complete"] = not broken["completeness"]["complete"]
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


# ---------------------------------------------------------------------------
# Audio block
# ---------------------------------------------------------------------------


def test_audio_file_wrong_path_refused(manifest: dict[str, Any]) -> None:
    """Audio file wrong path refused."""
    broken = copy.deepcopy(manifest)
    broken["audio"]["file"] = "audio/track.wav"
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


def test_audio_bytes_zero_refused(manifest: dict[str, Any]) -> None:
    """Audio bytes zero refused."""
    broken = copy.deepcopy(manifest)
    broken["audio"]["bytes"] = 0
    with pytest.raises(ValueError):
        validate_episode_media_assembly_manifest(broken)


# ---------------------------------------------------------------------------
# C5 -- a frame record's `file` carrying `../` or a separator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "forged_file",
    [
        "presentation/../evil.png",
        "presentation/../../evil.png",
        "presentation/nested/frame_0000001.png",
        "/absolute/frame_0000001.png",
        "presentation\\frame_0000001.png",
        "../frame_0000001.png",
    ],
    ids=[
        "parent-traversal",
        "double-parent-traversal",
        "nested-separator",
        "absolute-path",
        "backslash-separator",
        "leading-traversal",
    ],
)
def test_c5_a_frame_file_carrying_traversal_or_a_separator_is_refused(
    manifest: dict[str, Any], forged_file: str
) -> None:
    """C5 manifest frame file carrying ../ or a separator is refused.

    ``file`` must equal the one deterministic relative path this phase's own naming
    law produces for that presentation coordinate, so no traversal, absolute path or
    extra separator can survive validation.
    """
    broken = copy.deepcopy(manifest)
    broken["frames"][0]["file"] = forged_file
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(broken)
