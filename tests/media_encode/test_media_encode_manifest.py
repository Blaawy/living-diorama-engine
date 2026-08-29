"""P35 manifest builder and source-join tests, with upstream validators monkeypatched.

The two LOCKED upstream validators (``validate_episode_media_assembly_manifest`` and
``validate_episode_caption_serialization_manifest``) are monkeypatched to identity
functions (``lambda d: d``) for every test in this module. The rationale: their own
truth is proven upstream by the Phase 33/34 lanes, and building a MINIMAL VALID
upstream manifest here would require the full frame-record assembly shape or real
fixture directories. These tests target the P35 joins and the P35 builder -- the keys
``require_encode_sources_join`` and the builder actually read -- so the hand-shaped
dicts carry only those keys. The FULL-validator path is covered by executor and
integration tests in other lanes.

The builder's terminal call to the REAL ``validate_episode_media_encode_manifest`` is
NOT patched: the hand-shaped upstream dicts must therefore produce a fully
schema-valid result (episode-1 transition clock, the real command builder's argv,
the golden 21-key streams block, plausible sidecar bytes and digests).
"""

from typing import Any

import pytest

from living_diorama.media_encode import media_encode_manifest
from living_diorama.media_encode.media_encode_manifest import (
    build_episode_media_encode_manifest_document,
    require_encode_sources_join,
)
from living_diorama.media_encode.media_encode_probe import normalize_probe_document
from living_diorama.media_encode.media_encode_spec import MediaEncodeRefused
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex

EPISODE_ID: str = "episode_0000_to_0001"
"""The deterministic episode id both hand-shaped upstream manifests bind."""

CLOCK: dict[str, int] = {
    "audio_sample_rate_hz": 24000,
    "audio_samples_total": 720000,
    "fps": 24,
    "presentation_frames_total": 720,
    "samples_per_presentation_frame": 1000,
    "semantic_final_frame": 192,
    "semantic_first_frame": 1,
    "witness_frame": 193,
}
"""The frozen episode-1 transition clock both manifests share."""

FFMPEG_VERSION: str = "ffmpeg version 9.0.1 Copyright"
FFPROBE_VERSION: str = "ffprobe version 9.0.1 Copyright"
"""The recorded, gated first version lines the builder carries."""


@pytest.fixture
def identity_upstream_validators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the two locked upstream validators with identity functions."""
    monkeypatch.setattr(
        media_encode_manifest,
        "validate_episode_media_assembly_manifest",
        lambda document: document,
    )
    monkeypatch.setattr(
        media_encode_manifest,
        "validate_episode_caption_serialization_manifest",
        lambda document: document,
    )


def make_assembly_manifest() -> dict[str, Any]:
    """Return the hand-shaped Phase 33 manifest carrying only the keys P35 reads."""
    return {
        "source": {
            "episode": 1,
            "mode": "transition",
            "previous_episode": 0,
            "presentation_plan_sha256": "a" * 64,
        },
        "clock": dict(CLOCK),
        "schema_version": 1,
    }


def make_captions_manifest() -> dict[str, Any]:
    """Return the hand-shaped Phase 34 manifest carrying only the keys P35 reads."""
    return {
        "source": {
            "episode": 1,
            "mode": "transition",
            "previous_episode": 0,
            "presentation_plan_sha256": "a" * 64,
        },
        "clock": {"fps": 24, "presentation_frames_total": 720},
        "schema_version": 1,
        "sidecars": {
            "srt": {
                "bytes": 10,
                "file": f"{EPISODE_ID}.srt",
                "format": "srt",
                "sha256": "d" * 64,
            },
            "vtt": {
                "bytes": 12,
                "file": f"{EPISODE_ID}.vtt",
                "format": "webvtt",
                "sha256": "d" * 64,
            },
        },
    }


def make_streams() -> dict[str, Any]:
    """Return the normalized 21-key streams block for the golden observation."""
    return normalize_probe_document(
        {
            "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "filename": "pipe:0"},
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "codec_name": "h264",
                    "pix_fmt": "yuv420p",
                    "width": 1280,
                    "height": 720,
                    "avg_frame_rate": "24/1",
                    "r_frame_rate": "24/1",
                    "time_base": "1/12288",
                    "duration_ts": 368640,
                    "start_pts": 0,
                    "nb_read_frames": "720",
                },
                {
                    "index": 1,
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "24000",
                    "channels": 1,
                    "time_base": "1/24000",
                    "duration_ts": 720000,
                    "start_pts": 0,
                },
            ],
        },
        audio_samples_decoded=720000,
    )


def builder_kwargs(**overrides: Any) -> dict[str, Any]:
    """Return the builder keyword arguments for the agreeing, byte-exact manifests."""
    assembly = make_assembly_manifest()
    captions = make_captions_manifest()
    kwargs: dict[str, Any] = {
        "assembly_manifest": assembly,
        "assembly_manifest_bytes": dumps_canonical(assembly, "episode media assembly manifest"),
        "captions_manifest": captions,
        "captions_manifest_bytes": dumps_canonical(
            captions, "episode caption serialization manifest"
        ),
        "video_bytes": 5,
        "video_sha256": "c" * 64,
        "streams": make_streams(),
        "ffmpeg_version": FFMPEG_VERSION,
        "ffprobe_version": FFPROBE_VERSION,
    }
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# require_encode_sources_join
# ---------------------------------------------------------------------------


def test_join_passes_on_agreeing_docs(identity_upstream_validators: None) -> None:
    """Agreeing episode identity, clock and presentation plan join cleanly."""
    assembly, captions = require_encode_sources_join(
        make_assembly_manifest(), make_captions_manifest()
    )
    assert assembly["source"]["episode"] == captions["source"]["episode"] == 1


def test_join_episode_mismatch_refused(identity_upstream_validators: None) -> None:
    """A differing episode identity refuses: one episode has one identity."""
    captions = make_captions_manifest()
    captions["source"]["episode"] = 2
    with pytest.raises(MediaEncodeRefused, match="one episode has one identity"):
        require_encode_sources_join(make_assembly_manifest(), captions)


def test_join_fps_mismatch_refused(identity_upstream_validators: None) -> None:
    """A differing fps refuses: both inputs descend from one presentation."""
    captions = make_captions_manifest()
    captions["clock"]["fps"] = 25
    with pytest.raises(MediaEncodeRefused, match="both descend from one presentation"):
        require_encode_sources_join(make_assembly_manifest(), captions)


def test_join_frames_mismatch_refused(identity_upstream_validators: None) -> None:
    """A differing frame total refuses: both inputs descend from one presentation."""
    captions = make_captions_manifest()
    captions["clock"]["presentation_frames_total"] = 721
    with pytest.raises(MediaEncodeRefused, match="both descend from one presentation"):
        require_encode_sources_join(make_assembly_manifest(), captions)


def test_join_presentation_plan_mismatch_refused(identity_upstream_validators: None) -> None:
    """Differing presentation_plan_sha256 refuses: the two inputs never join."""
    captions = make_captions_manifest()
    captions["source"]["presentation_plan_sha256"] = "b" * 64
    with pytest.raises(MediaEncodeRefused, match="descend from different presentations"):
        require_encode_sources_join(make_assembly_manifest(), captions)


# ---------------------------------------------------------------------------
# build_episode_media_encode_manifest_document
# ---------------------------------------------------------------------------


def test_builder_source_carries_sha256_of_given_bytes(
    identity_upstream_validators: None,
) -> None:
    """The source block binds the exact bytes handed to the builder."""
    document = build_episode_media_encode_manifest_document(**builder_kwargs())
    assert document["source"]["media_assembly_manifest_sha256"] == sha256_hex(
        dumps_canonical(make_assembly_manifest(), "episode media assembly manifest")
    )
    assert document["source"]["caption_serialization_manifest_sha256"] == sha256_hex(
        dumps_canonical(make_captions_manifest(), "episode caption serialization manifest")
    )


def test_builder_clock_copied_from_assembly(identity_upstream_validators: None) -> None:
    """The manifest's clock block is the assembly clock, byte-for-byte."""
    document = build_episode_media_encode_manifest_document(**builder_kwargs())
    assert document["clock"] == CLOCK


def test_builder_captions_copied_minus_format(identity_upstream_validators: None) -> None:
    """Sidecar records are copied without the upstream-only ``format`` key."""
    document = build_episode_media_encode_manifest_document(**builder_kwargs())
    assert document["captions"]["srt"] == {
        "bytes": 10,
        "file": f"{EPISODE_ID}.srt",
        "sha256": "d" * 64,
    }
    assert document["captions"]["vtt"] == {
        "bytes": 12,
        "file": f"{EPISODE_ID}.vtt",
        "sha256": "d" * 64,
    }


def test_builder_video_block_from_args(identity_upstream_validators: None) -> None:
    """The produced episode file block comes from the passed capture facts."""
    document = build_episode_media_encode_manifest_document(**builder_kwargs())
    assert document["video"] == {
        "bytes": 5,
        "file": f"{EPISODE_ID}.mp4",
        "sha256": "c" * 64,
    }


def test_builder_completeness_derived(identity_upstream_validators: None) -> None:
    """The completeness verdict is derived from streams and clock, never asserted."""
    document = build_episode_media_encode_manifest_document(**builder_kwargs())
    assert document["completeness"] == {
        "complete": True,
        "video_frames_counted": 720,
        "video_frames_expected": 720,
    }


def test_builder_result_validates_under_the_real_schema(
    identity_upstream_validators: None,
) -> None:
    """The built document passes the REAL terminal validator unchanged."""
    from living_diorama.media_encode.media_encode_schema_v1 import (
        validate_episode_media_encode_manifest,
    )

    document = build_episode_media_encode_manifest_document(**builder_kwargs())
    assert validate_episode_media_encode_manifest(document) is document


def test_builder_noncanonical_assembly_bytes_refused(
    identity_upstream_validators: None,
) -> None:
    """Byte strings that are not the document's own canonical encoding refuse."""
    kwargs = builder_kwargs(assembly_manifest_bytes=b"not the canonical bytes")
    with pytest.raises(ValueError, match="canonical encoding"):
        build_episode_media_encode_manifest_document(**kwargs)


@pytest.mark.parametrize("field", ["assembly_manifest_bytes", "captions_manifest_bytes"])
def test_builder_wrong_byte_type_refused(identity_upstream_validators: None, field: str) -> None:
    """A non-bytes captured manifest string raises TypeError."""
    kwargs = builder_kwargs(**{field: "not bytes"})
    with pytest.raises(TypeError):
        build_episode_media_encode_manifest_document(**kwargs)
