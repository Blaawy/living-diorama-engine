"""Pure document construction: turning measured facts into an Episode Media Assembly Manifest.

No frozen test-matrix section names this module explicitly; its own docstring
states its contract exactly -- pure, filesystem-free, refuses a frame or
audio result whose keys are not exactly the schema's own key sets -- and
these tests attack that contract directly, against real bound sources.
"""

import copy
from typing import Any

import pytest

from living_diorama.media_assembly.media_assembly_manifest import (
    build_episode_media_assembly_manifest_bytes,
    build_episode_media_assembly_manifest_document,
)
from living_diorama.media_assembly.media_assembly_mapping import (
    presentation_frame_map,
    require_clock_closure,
    require_playback_lookup,
)
from living_diorama.media_assembly.media_assembly_schema_v1 import (
    validate_episode_media_assembly_manifest,
)
from living_diorama.media_assembly.media_assembly_spec import presentation_frame_relative_path
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.render_execution.render_execution_spec import FRAMES_DIRECTORY


def _real_geometry(
    inputs: dict[str, Any],
) -> tuple[dict[str, int], list[dict[str, Any]], dict[str, Any]]:
    """Return (clock, frames, audio) measured from real sources -- the publisher's own recipe."""
    clock = require_clock_closure(
        inputs["presentation_plan"], inputs["render_manifest"], inputs["audio_composition_manifest"]
    )
    mapping = presentation_frame_map(inputs["presentation_plan"])
    lookup = require_playback_lookup(inputs["render_manifest"])
    frames: list[dict[str, Any]] = []
    for position, semantic in enumerate(mapping, start=1):
        record = lookup[semantic]
        payload = (inputs["render_dir"] / FRAMES_DIRECTORY / record["file"]).read_bytes()
        frames.append(
            {
                "bytes": len(payload),
                "file": presentation_frame_relative_path(position),
                "presentation_frame": position,
                "semantic_frame": semantic,
                "sha256": sha256_hex(payload),
            }
        )
    composition_audio = inputs["audio_composition_manifest"]["audio"]
    audio = {
        "audio_samples": composition_audio["audio_samples"],
        "bytes": composition_audio["bytes"],
        "channels": composition_audio["channels"],
        "file": "audio/episode_audio.wav",
        "sample_rate_hz": composition_audio["sample_rate_hz"],
        "sha256": composition_audio["sha256"],
    }
    return clock, frames, audio


def _build_kwargs(inputs: dict[str, Any]) -> dict[str, Any]:
    clock, frames, audio = _real_geometry(inputs)
    return {
        "render_manifest": inputs["render_manifest"],
        "presentation_plan": inputs["presentation_plan"],
        "audio_composition_manifest": inputs["audio_composition_manifest"],
        "delivery_plan": inputs["delivery_plan"],
        "shot_plan_sha256": sha256_hex(inputs["shot_plan_bytes"]),
        "clock": clock,
        "frames": tuple(frames),
        "audio": audio,
    }


def test_a_real_manifest_document_validates(assembly_inputs_ep1: dict[str, Any]) -> None:
    """A real manifest document validates."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    document = build_episode_media_assembly_manifest_document(**kwargs)
    assert validate_episode_media_assembly_manifest(copy.deepcopy(document)) == document


def test_build_bytes_equals_dumps_canonical_of_the_document(
    assembly_inputs_ep1: dict[str, Any],
) -> None:
    """Build bytes equals dumps canonical of the document."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    document = build_episode_media_assembly_manifest_document(**kwargs)
    payload = build_episode_media_assembly_manifest_bytes(**kwargs)
    assert payload == dumps_canonical(document, "episode media assembly manifest")


def test_source_block_is_bound_from_the_four_documents(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Source block is bound from the four documents."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    document = build_episode_media_assembly_manifest_document(**kwargs)
    render_source = kwargs["render_manifest"]["source"]
    assert document["source"]["episode"] == render_source["episode"]
    assert document["source"]["mode"] == render_source["mode"]
    assert document["source"]["previous_episode"] == render_source["previous_episode"]
    assert document["source"]["motion_time_sha256"] == render_source["motion_time_sha256"]
    assert document["source"]["shot_plan_sha256"] == kwargs["shot_plan_sha256"]


def test_shot_plan_sha256_is_restated_never_recomputed(
    assembly_inputs_ep1: dict[str, Any],
) -> None:
    """Shot plan sha256 is restated, never recomputed.

    Passing a syntactically-valid-looking but wrong digest is carried through unchecked --
    this function trusts its caller's already-proven digest; it parses no shot plan itself.
    """
    kwargs = _build_kwargs(assembly_inputs_ep1)
    kwargs["shot_plan_sha256"] = "0" * 64
    document = build_episode_media_assembly_manifest_document(**kwargs)
    assert document["source"]["shot_plan_sha256"] == "0" * 64


def test_completeness_is_measured_from_the_frames_given(
    assembly_inputs_ep1: dict[str, Any],
) -> None:
    """Completeness is measured from the frames given."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    document = build_episode_media_assembly_manifest_document(**kwargs)
    assert document["completeness"]["presentation_frames_assembled"] == len(kwargs["frames"])
    assert document["completeness"]["complete"] is True
    unique = len({frame["semantic_frame"] for frame in kwargs["frames"]})
    assert document["completeness"]["unique_semantic_frames_used"] == unique


def test_a_truncated_frame_set_produces_an_incomplete_manifest(
    assembly_inputs_ep1: dict[str, Any],
) -> None:
    """A truncated frame set produces an incomplete manifest."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    kwargs["frames"] = kwargs["frames"][:-1]
    with pytest.raises(ValueError):
        # a frame count that disagrees with the clock's own total is refused by the
        # standalone validator this builder calls as its terminal step
        build_episode_media_assembly_manifest_document(**kwargs)


# ---------------------------------------------------------------------------
# Frame-record key-set law
# ---------------------------------------------------------------------------


def test_a_frame_missing_a_key_is_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """A frame missing a key is refused."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    frames = list(kwargs["frames"])
    broken = dict(frames[0])
    del broken["sha256"]
    frames[0] = broken
    kwargs["frames"] = tuple(frames)
    with pytest.raises(ValueError):
        build_episode_media_assembly_manifest_document(**kwargs)


def test_a_frame_with_an_extra_key_is_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """A frame with an extra key is refused."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    frames = list(kwargs["frames"])
    broken = dict(frames[0])
    broken["image_sha256"] = "0" * 64
    frames[0] = broken
    kwargs["frames"] = tuple(frames)
    with pytest.raises(ValueError):
        build_episode_media_assembly_manifest_document(**kwargs)


def test_frames_must_be_a_tuple(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Frames must be a tuple."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    kwargs["frames"] = list(kwargs["frames"])
    with pytest.raises(TypeError):
        build_episode_media_assembly_manifest_document(**kwargs)


# ---------------------------------------------------------------------------
# Audio-block key-set law
# ---------------------------------------------------------------------------


def test_audio_missing_a_key_is_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Audio missing a key is refused."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    broken_audio = dict(kwargs["audio"])
    del broken_audio["channels"]
    kwargs["audio"] = broken_audio
    with pytest.raises(ValueError):
        build_episode_media_assembly_manifest_document(**kwargs)


def test_audio_with_an_extra_key_is_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Audio with an extra key is refused."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    broken_audio = dict(kwargs["audio"])
    broken_audio["duration_seconds"] = 30.0
    kwargs["audio"] = broken_audio
    with pytest.raises(ValueError):
        build_episode_media_assembly_manifest_document(**kwargs)


def test_audio_must_be_a_dict(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Audio must be a dict."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    kwargs["audio"] = ["not", "a", "dict"]
    with pytest.raises(TypeError):
        build_episode_media_assembly_manifest_document(**kwargs)


def test_clock_must_be_a_dict(assembly_inputs_ep1: dict[str, Any]) -> None:
    """Clock must be a dict."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    kwargs["clock"] = ["not", "a", "dict"]
    with pytest.raises(TypeError):
        build_episode_media_assembly_manifest_document(**kwargs)


# ---------------------------------------------------------------------------
# Bound-document validity
# ---------------------------------------------------------------------------


def test_an_invalid_render_manifest_is_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """An invalid render manifest is refused."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    kwargs["render_manifest"] = {"not": "a render manifest"}
    with pytest.raises((TypeError, ValueError)):
        build_episode_media_assembly_manifest_document(**kwargs)


def test_an_invalid_delivery_plan_is_refused(assembly_inputs_ep1: dict[str, Any]) -> None:
    """An invalid delivery plan is refused."""
    kwargs = _build_kwargs(assembly_inputs_ep1)
    kwargs["delivery_plan"] = {"not": "a delivery plan"}
    with pytest.raises((TypeError, ValueError)):
        build_episode_media_assembly_manifest_document(**kwargs)
