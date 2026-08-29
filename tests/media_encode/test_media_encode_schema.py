"""P35 Episode Media Encode Manifest V1 shape validation (V45-V46, V75/V76, V62/V77).

The valid document is transcribed BY HAND from the frozen reviewed shape -- top-level
10 keys, source 7, clock 8 (episode-1 transition: semantic first 1, final 192, witness
193, 1000 samples per frame, 720000 total samples), the 1280x720 render authority, the
produced episode file and the two sidecar records with their derived filenames, a
path-neutral invocation whose logical argv is built by the REAL command builder, the
21-key tool-attested streams block, and the internally closed completeness verdict.
Each mutation below is refused tool-free by the locked validator: an edited, missing,
duplicated or misplaced ``-threads:v``, or a resolved placeholder, all break the
rebuild-equality law (``logical_argv`` is re-derived, never trusted).
"""

from collections.abc import Callable
from typing import Any

import pytest

from living_diorama.media_encode.media_encode_command import build_media_encode_command
from living_diorama.media_encode.media_encode_probe import normalize_probe_document
from living_diorama.media_encode.media_encode_schema_v1 import (
    validate_episode_media_encode_manifest,
)
from living_diorama.media_encode.media_encode_spec import (
    MEDIA_ENCODE_MANIFEST_FORMAT,
    MEDIA_ENCODE_PROFILE_V1,
    MEDIA_ENCODE_SCHEMA_VERSION,
    media_encode_id,
    media_temp_filename,
)

EPISODE_ID: str = media_encode_id(mode="transition", episode=1, previous_episode=0)
"""The deterministic episode id the valid manifest binds (``episode_0000_to_0001``)."""


def make_probe_json(
    *,
    fps: int = 24,
    frames: int = 720,
    rate: int = 24000,
    channels: int = 1,
    width: int = 1280,
    height: int = 720,
) -> dict[str, Any]:
    """Return the ffprobe-shaped document for the one captured MP4 observation."""
    return {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "filename": "pipe:0"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "pix_fmt": "yuv420p",
                "width": width,
                "height": height,
                "avg_frame_rate": f"{fps}/1",
                "r_frame_rate": f"{fps}/1",
                "time_base": "1/12288",
                "duration_ts": 368640,
                "start_pts": 0,
                "nb_read_frames": str(frames),
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": str(rate),
                "channels": channels,
                "time_base": "1/24000",
                "duration_ts": 720000,
                "start_pts": 0,
            },
        ],
    }


def make_streams() -> dict[str, Any]:
    """Return the normalized 21-key streams block for the golden observation."""
    return normalize_probe_document(make_probe_json(), audio_samples_decoded=720000)


def make_valid_manifest() -> dict[str, Any]:
    """Return a fully schema-valid episode media encode manifest for episode 1."""
    return {
        "captions": {
            "srt": {"bytes": 10, "file": f"{EPISODE_ID}.srt", "sha256": "c" * 64},
            "vtt": {"bytes": 12, "file": f"{EPISODE_ID}.vtt", "sha256": "c" * 64},
        },
        "clock": {
            "audio_sample_rate_hz": 24000,
            "audio_samples_total": 720000,
            "fps": 24,
            "presentation_frames_total": 720,
            "samples_per_presentation_frame": 1000,
            "semantic_final_frame": 192,
            "semantic_first_frame": 1,
            "witness_frame": 193,
        },
        "completeness": {
            "complete": True,
            "video_frames_counted": 720,
            "video_frames_expected": 720,
        },
        "format": MEDIA_ENCODE_MANIFEST_FORMAT,
        "invocation": {
            "ffmpeg_version": "ffmpeg version 9.0.1 Copyright",
            "ffprobe_version": "ffprobe version 9.0.1 Copyright",
            "logical_argv": list(
                build_media_encode_command(
                    fps=24,
                    presentation_frames_total=720,
                    audio_sample_rate_hz=24000,
                    audio_channels=1,
                    media_temp_filename=media_temp_filename(EPISODE_ID),
                )
            ),
            "profile_id": MEDIA_ENCODE_PROFILE_V1,
        },
        "render": {"height": 720, "width": 1280},
        "schema_version": MEDIA_ENCODE_SCHEMA_VERSION,
        "source": {
            "caption_serialization_manifest_sha256": "b" * 64,
            "caption_serialization_schema_version": 1,
            "episode": 1,
            "media_assembly_manifest_sha256": "a" * 64,
            "media_assembly_schema_version": 1,
            "mode": "transition",
            "previous_episode": 0,
        },
        "streams": make_streams(),
        "video": {"bytes": 5, "file": f"{EPISODE_ID}.mp4", "sha256": "c" * 64},
    }


def test_valid_manifest_validates() -> None:
    """The hand-transcribed episode-1 transition manifest validates whole."""
    document = make_valid_manifest()
    assert validate_episode_media_encode_manifest(document) is document


# ---------------------------------------------------------------------------
# mutation helpers
# ---------------------------------------------------------------------------


def _set(document: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """Set a nested value by key path."""
    target: Any = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _pop(document: dict[str, Any], path: tuple[str, ...]) -> None:
    """Remove a nested key by key path."""
    target: Any = document
    for key in path[:-1]:
        target = target[key]
    target.pop(path[-1])


def _edit_threads_value(document: dict[str, Any]) -> None:
    """Change the recorded ``-threads:v`` value from 0 to 1."""
    argv = document["invocation"]["logical_argv"]
    index = argv.index("-threads:v")
    argv[index + 1] = "1"


def _duplicate_threads(document: dict[str, Any]) -> None:
    """Insert a second ``-threads:v 0`` pair into the recorded argv."""
    argv = document["invocation"]["logical_argv"]
    index = argv.index("-threads:v")
    argv[index + 1 : index + 1] = ["-threads:v", "0"]


def _resolve_staging_token(document: dict[str, Any]) -> None:
    """Resolve the ``{STAGING}`` placeholder to a real path in the recorded argv."""
    argv = document["invocation"]["logical_argv"]
    document["invocation"]["logical_argv"] = [
        token.replace("{STAGING}", "C:/tmp/x") for token in argv
    ]


MUTATIONS: list[tuple[str, Callable[[dict[str, Any]], None], type[Exception], str | None]] = [
    (
        "missing top-level key",
        lambda d: _pop(d, ("streams",)),
        ValueError,
        "missing required keys",
    ),
    ("extra top-level key", lambda d: _set(d, ("surprise",), 1), ValueError, "unexpected keys"),
    ("wrong format", lambda d: _set(d, ("format",), "bogus"), ValueError, "this build reads"),
    (
        "wrong schema version",
        lambda d: _set(d, ("schema_version",), 2),
        ValueError,
        "unsupported schema version",
    ),
    (
        "missing source key",
        lambda d: _pop(d, ("source", "episode")),
        ValueError,
        "missing required keys",
    ),
    (
        "assembly schema version 2",
        lambda d: _set(d, ("source", "media_assembly_schema_version"), 2),
        ValueError,
        "speaks version 1 only",
    ),
    (
        "caption schema version 2",
        lambda d: _set(d, ("source", "caption_serialization_schema_version"), 2),
        ValueError,
        "speaks version 1 only",
    ),
    (
        "clock spf breaks",
        lambda d: _set(d, ("clock", "samples_per_presentation_frame"), 999),
        ValueError,
        "derive 1000",
    ),
    (
        "clock samples break",
        lambda d: _set(d, ("clock", "audio_samples_total"), 719000),
        ValueError,
        "720 frames at 1000",
    ),
    (
        "clock witness breaks",
        lambda d: _set(d, ("clock", "witness_frame"), 194),
        ValueError,
        "must equal semantic_final_frame",
    ),
    (
        "clock rate non-divisible",
        lambda d: _set(d, ("clock", "audio_sample_rate_hz"), 24001),
        ValueError,
        "not evenly divisible",
    ),
    (
        "render width invented",
        lambda d: _set(d, ("render", "width"), 1281),
        ValueError,
        "derived, never invented",
    ),
    (
        "video file wrong",
        lambda d: _set(d, ("video", "file"), "wrong.mp4"),
        ValueError,
        "expected 'episode_0000_to_0001.mp4'",
    ),
    (
        "captions srt file wrong",
        lambda d: _set(d, ("captions", "srt", "file"), "wrong.srt"),
        ValueError,
        "expected 'episode_0000_to_0001.srt'",
    ),
    (
        "invocation profile wrong",
        lambda d: _set(d, ("invocation", "profile_id"), "x"),
        ValueError,
        "constructs",
    ),
    (
        "ffmpeg version ungated",
        lambda d: _set(d, ("invocation", "ffmpeg_version"), "ffmpeg version n9.0"),
        ValueError,
        "ungated tool",
    ),
    ("logical_argv threads value edited", _edit_threads_value, ValueError, "never trusted"),
    ("logical_argv threads duplicated", _duplicate_threads, ValueError, "never trusted"),
    ("logical_argv staging token resolved", _resolve_staging_token, ValueError, "never trusted"),
    (
        "streams decoded breaks law",
        lambda d: _set(d, ("streams", "audio_samples_decoded"), 719000),
        ValueError,
        "violate a recorded law",
    ),
    (
        "completeness counted mismatch",
        lambda d: _set(d, ("completeness", "video_frames_counted"), 719),
        ValueError,
        "but the streams block records",
    ),
    (
        "complete false with equal counts",
        lambda d: _set(d, ("completeness", "complete"), False),
        ValueError,
        "disagrees with its own counts",
    ),
    (
        "complete non-bool",
        lambda d: _set(d, ("completeness", "complete"), 1),
        TypeError,
        "must be a bool",
    ),
]


@pytest.mark.parametrize(
    ("label", "mutate", "exc", "match"),
    MUTATIONS,
    ids=[label for label, _, _, _ in MUTATIONS],
)
def test_mutations_refused(
    label: str,
    mutate: Callable[[dict[str, Any]], None],
    exc: type[Exception],
    match: str | None,
) -> None:
    """Each single mutation of the valid document is refused by the validator."""
    document = make_valid_manifest()
    mutate(document)
    with pytest.raises(exc, match=match):
        validate_episode_media_encode_manifest(document)
