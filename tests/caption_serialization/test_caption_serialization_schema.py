"""Standalone shape validation for the Episode Caption Serialization Manifest V1.

Every test works from a valid manifest built by the real builder over a
synthetic valid Phase 32 caption plan and the real serialized sidecar bytes,
so a mutation proves something about a document the engine could actually
have written, never a hand-typed fixture nobody's code would produce.
"""

import copy
from typing import Any

import pytest

from living_diorama.caption_serialization.caption_serialization_manifest import (
    build_episode_caption_serialization_manifest_document,
)
from living_diorama.caption_serialization.caption_serialization_schema_v1 import (
    SOURCE_KEYS,
    TOP_LEVEL_KEYS,
    validate_episode_caption_serialization_manifest,
)
from living_diorama.caption_serialization.srt_writer import serialize_srt_bytes
from living_diorama.caption_serialization.vtt_writer import serialize_vtt_bytes
from living_diorama.persistence.json_codec import dumps_canonical


def _build_caption_plan(*, mode: str, episode: int, previous_episode: int | None) -> dict[str, Any]:
    """Build one synthetic valid Phase 32 caption plan (three cues, fps 24)."""
    total_frames = 130
    captions: list[dict[str, Any]] = []
    for position, (start, end) in enumerate(((1, 40), (41, 80), (81, 120)), start=1):
        captions.append(
            {
                "caption_id": f"caption_{position:04d}",
                "caption_text": f"Sentence number {position}.",
                "presentation_end_frame": end,
                "presentation_start_frame": start,
                "realization_id": f"realization_{position:04d}",
                "unit_id": f"unit_{position:04d}",
                "window_id": f"window_{position:04d}",
            }
        )
    return {
        "accounting": {
            "caption_frames_total": 120,
            "captions_total": 3,
            "uncaptioned_frames_total": total_frames - 120,
        },
        "captions": captions,
        "clock": {"fps": 24, "presentation_frames_total": total_frames},
        "format": "living_diorama_episode_caption_plan",
        "policy": "caption_policy_v1",
        "schema_version": 1,
        "source": {
            "episode": episode,
            "mode": mode,
            "previous_episode": previous_episode,
            "presentation_plan_sha256": "a" * 64,
            "presentation_schema_version": 1,
            "realization_plan_sha256": "b" * 64,
            "realization_schema_version": 1,
        },
    }


def _build_manifest(
    *, mode: str = "baseline", episode: int = 0, previous_episode: int | None = None
) -> dict[str, Any]:
    """Build one valid Episode Caption Serialization Manifest document."""
    plan = _build_caption_plan(mode=mode, episode=episode, previous_episode=previous_episode)
    return build_episode_caption_serialization_manifest_document(
        caption_plan=plan,
        caption_plan_bytes=dumps_canonical(plan, "p"),
        srt_bytes=serialize_srt_bytes(plan),
        vtt_bytes=serialize_vtt_bytes(plan),
    )


@pytest.fixture
def manifest() -> dict[str, Any]:
    """A valid baseline manifest, rebuilt fresh for every test."""
    return _build_manifest()


@pytest.mark.parametrize(
    ("mode", "episode", "previous"),
    [("baseline", 0, None), ("transition", 1, 0)],
    ids=["baseline-ep0", "transition-ep1"],
)
def test_a_real_manifest_validates(mode: str, episode: int, previous: int | None) -> None:
    """A real manifest validates and returns the same dict."""
    document = _build_manifest(mode=mode, episode=episode, previous_episode=previous)
    assert validate_episode_caption_serialization_manifest(copy.deepcopy(document)) == document


# ---------------------------------------------------------------------------
# Top-level missing / extra keys
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(TOP_LEVEL_KEYS))
def test_top_level_missing_key_refused(manifest: dict[str, Any], key: str) -> None:
    """Top level missing key refused."""
    broken = copy.deepcopy(manifest)
    del broken[key]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_caption_serialization_manifest(broken)


@pytest.mark.parametrize("key", ["captions", "extra"])
def test_top_level_extra_key_refused(manifest: dict[str, Any], key: str) -> None:
    """Top level extra key refused."""
    broken = copy.deepcopy(manifest)
    broken[key] = [] if key == "captions" else 1
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_caption_serialization_manifest(broken)


# ---------------------------------------------------------------------------
# format / schema_version / policy pinned
# ---------------------------------------------------------------------------


def test_wrong_format_literal_refused(manifest: dict[str, Any]) -> None:
    """Wrong format literal refused."""
    broken = copy.deepcopy(manifest)
    broken["format"] = "living_diorama_episode_audio_composition_manifest"
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


def test_wrong_schema_version_refused(manifest: dict[str, Any]) -> None:
    """Wrong schema version refused."""
    broken = copy.deepcopy(manifest)
    broken["schema_version"] = 2
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


def test_wrong_policy_string_refused(manifest: dict[str, Any]) -> None:
    """Wrong policy string refused."""
    broken = copy.deepcopy(manifest)
    broken["policy"] = "caption_timestamp_policy_v2"
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


# ---------------------------------------------------------------------------
# Source block
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(SOURCE_KEYS))
def test_source_missing_key_refused(manifest: dict[str, Any], key: str) -> None:
    """Source missing key refused."""
    broken = copy.deepcopy(manifest)
    del broken["source"][key]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_caption_serialization_manifest(broken)


@pytest.mark.parametrize("key", ["caption_text", "extra"])
def test_source_extra_key_refused(manifest: dict[str, Any], key: str) -> None:
    """Source extra key refused."""
    broken = copy.deepcopy(manifest)
    broken["source"][key] = "x" if key == "caption_text" else 1
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_caption_serialization_manifest(broken)


def test_source_episode_bool_refused(manifest: dict[str, Any]) -> None:
    """Source episode bool refused."""
    broken = copy.deepcopy(manifest)
    broken["source"]["episode"] = True
    with pytest.raises(TypeError):
        validate_episode_caption_serialization_manifest(broken)


def test_caption_schema_version_two_refused(manifest: dict[str, Any]) -> None:
    """Caption schema version two refused."""
    broken = copy.deepcopy(manifest)
    broken["source"]["caption_schema_version"] = 2
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


@pytest.mark.parametrize("key", ["presentation_schema_version", "realization_schema_version"])
def test_upstream_schema_version_two_refused(manifest: dict[str, Any], key: str) -> None:
    """Upstream schema version two refused."""
    broken = copy.deepcopy(manifest)
    broken["source"][key] = 2
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


def test_non_hex_caption_plan_sha256_refused(manifest: dict[str, Any]) -> None:
    """Non hex caption plan sha256 refused."""
    broken = copy.deepcopy(manifest)
    broken["source"]["caption_plan_sha256"] = "not-a-digest"
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


def test_unknown_mode_refused(manifest: dict[str, Any]) -> None:
    """Unknown mode refused."""
    broken = copy.deepcopy(manifest)
    broken["source"]["mode"] = "x"
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


def test_baseline_with_previous_episode_refused(manifest: dict[str, Any]) -> None:
    """Baseline with previous episode refused."""
    broken = copy.deepcopy(manifest)
    broken["source"]["previous_episode"] = 0
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


def test_baseline_with_nonzero_episode_refused(manifest: dict[str, Any]) -> None:
    """Baseline with nonzero episode refused."""
    broken = copy.deepcopy(manifest)
    broken["source"]["episode"] = 3
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


def test_transition_non_succession_refused() -> None:
    """Transition episode not following previous plus one refused."""
    broken = _build_manifest(mode="transition", episode=1, previous_episode=0)
    broken["source"]["previous_episode"] = 5
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


# ---------------------------------------------------------------------------
# Clock block
# ---------------------------------------------------------------------------


def test_clock_fps_zero_refused(manifest: dict[str, Any]) -> None:
    """Clock fps zero refused."""
    broken = copy.deepcopy(manifest)
    broken["clock"]["fps"] = 0
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


def test_clock_total_zero_refused(manifest: dict[str, Any]) -> None:
    """Clock total zero refused."""
    broken = copy.deepcopy(manifest)
    broken["clock"]["presentation_frames_total"] = 0
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


def test_clock_total_above_max_refused(manifest: dict[str, Any]) -> None:
    """Clock total above max refused."""
    broken = copy.deepcopy(manifest)
    broken["clock"]["presentation_frames_total"] = 1_000_001
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


# ---------------------------------------------------------------------------
# Accounting block
# ---------------------------------------------------------------------------


def test_accounting_captions_total_zero_refused(manifest: dict[str, Any]) -> None:
    """Accounting captions total zero refused."""
    broken = copy.deepcopy(manifest)
    broken["accounting"]["captions_total"] = 0
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


def test_accounting_caption_frames_total_exceeding_clock_refused(
    manifest: dict[str, Any],
) -> None:
    """Accounting caption frames total exceeding the clock refused."""
    broken = copy.deepcopy(manifest)
    broken["accounting"]["caption_frames_total"] = 131
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


def test_accounting_uncaptioned_mismatch_quotes_the_subtraction() -> None:
    """Accounting uncaptioned mismatch refused with the subtraction quoted."""
    broken = _build_manifest()
    broken["accounting"]["uncaptioned_frames_total"] = 11
    with pytest.raises(ValueError, match="130 total frames minus 120 captioned frames is 10"):
        validate_episode_caption_serialization_manifest(broken)


# ---------------------------------------------------------------------------
# Sidecar block
# ---------------------------------------------------------------------------


def test_sidecars_missing_vtt_key_refused(manifest: dict[str, Any]) -> None:
    """Sidecars missing vtt key refused."""
    broken = copy.deepcopy(manifest)
    del broken["sidecars"]["vtt"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_caption_serialization_manifest(broken)


def test_sidecar_record_missing_sha256_refused(manifest: dict[str, Any]) -> None:
    """Sidecar record missing sha256 refused."""
    broken = copy.deepcopy(manifest)
    del broken["sidecars"]["srt"]["sha256"]
    with pytest.raises(ValueError, match="missing required keys"):
        validate_episode_caption_serialization_manifest(broken)


def test_sidecar_record_extra_key_refused(manifest: dict[str, Any]) -> None:
    """Sidecar record extra key refused."""
    broken = copy.deepcopy(manifest)
    broken["sidecars"]["vtt"]["duration_ms"] = 0
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_caption_serialization_manifest(broken)


def test_sidecar_record_bytes_zero_refused(manifest: dict[str, Any]) -> None:
    """Sidecar record bytes zero refused."""
    broken = copy.deepcopy(manifest)
    broken["sidecars"]["vtt"]["bytes"] = 0
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


def test_sidecar_record_wrong_file_name_refused(manifest: dict[str, Any]) -> None:
    """Sidecar record wrong file name refused with the expected name."""
    broken = copy.deepcopy(manifest)
    broken["sidecars"]["srt"]["file"] = "episode_0000_baseline.txt"
    with pytest.raises(ValueError, match="expected"):
        validate_episode_caption_serialization_manifest(broken)


def test_sidecar_record_wrong_format_value_refused(manifest: dict[str, Any]) -> None:
    """Sidecar record wrong format value refused."""
    broken = copy.deepcopy(manifest)
    broken["sidecars"]["srt"]["format"] = "webvtt"
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)


def test_sidecar_record_non_hex_sha_refused(manifest: dict[str, Any]) -> None:
    """Sidecar record non hex sha refused."""
    broken = copy.deepcopy(manifest)
    broken["sidecars"]["srt"]["sha256"] = "zz" * 32
    with pytest.raises(ValueError):
        validate_episode_caption_serialization_manifest(broken)
