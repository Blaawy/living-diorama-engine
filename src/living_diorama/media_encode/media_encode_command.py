"""Pure construction of every Phase 35 tool invocation, and the preflight WAV law.

The executor never assembles an ffmpeg or ffprobe argv inline: every command is built
here, as a tuple of exact strings, from authoritative integers alone. The ONLY
non-literal path material is the two placeholder tokens -- ``{ASSEMBLY_DIR}`` for the
frames input and ``{STAGING}`` for the audio snapshot input and the output temporary --
and :func:`substitute_paths` resolves them for the spawn only; the canonical manifest
records the placeholder form verbatim.

Deliberately ABSENT from the encode profile, each absence decision-bearing: ``-r`` (the
input ``-framerate`` is the sole rate authority), ``-shortest`` (both streams are exactly
``presentation_frames_total / fps`` seconds by upstream law), ``-vsync`` (removed in
modern FFmpeg; would hard-error), ``-t``/``-ss``/filters/scaling (no trimming, no
resampling, no pixel mutation), ``-y`` (a fresh staging temp never pre-exists), and any
pre-input thread option (FFmpeg option scoping is file-sensitive; the one thread option is
the output-scoped ``-threads:v 0``, automatic, with no determinism claim).
"""

import struct
from typing import Final

from living_diorama.media_encode.media_encode_spec import (
    AAC_BITRATE,
    ASSEMBLY_DIR_TOKEN,
    AUDIO_CODEC,
    PIX_FMT,
    PREFLIGHT_AUDIO_FILENAME,
    PREFLIGHT_MEDIA_FILENAME,
    SNAPSHOT_AUDIO_FILENAME,
    STAGING_TOKEN,
    VIDEO_CODEC,
    VIDEO_THREADS,
    X264_CRF,
    X264_PRESET,
)

_PREFLIGHT_VIDEO_SIZE: Final = "64x64"
"""The self-test's tiny video dimensions: real geometry lives in the counts, not pixels."""

_WAV_HEADER_BYTES: Final = 44
_PCM_BYTES_PER_SAMPLE: Final = 2
_MAX_CHUNK_BYTES: Final = 2**32 - 1


def _require_positive_int(value: int, description: str) -> int:
    """Return the value if it is a positive exact ``int``, else raise."""
    if type(value) is not int:
        raise TypeError(f"{description} must be an int, got {type(value).__name__}")
    if value < 1:
        raise ValueError(f"{description} must be >= 1, got {value}")
    return value


def build_media_encode_command(
    *,
    fps: int,
    presentation_frames_total: int,
    audio_sample_rate_hz: int,
    audio_channels: int,
    media_temp_filename: str,
) -> tuple[str, ...]:
    """Return the logical real-encode argv of ``media_encode_profile_v1``, exactly.

    Every integer is an authoritative derived value rendered as its exact decimal string;
    the two placeholder tokens are the only path material. ``-f mp4`` is explicit because
    the output temporary's name never ends in ``.mp4`` -- container inference from a
    filename is never relied on.

    Raises:
        TypeError: If a value has the wrong exact type.
        ValueError: If an integer is not positive or the temp filename is empty.
    """
    _require_positive_int(fps, "fps")
    _require_positive_int(presentation_frames_total, "presentation_frames_total")
    _require_positive_int(audio_sample_rate_hz, "audio_sample_rate_hz")
    _require_positive_int(audio_channels, "audio_channels")
    if type(media_temp_filename) is not str:
        raise TypeError(
            f"media_temp_filename must be a str, got {type(media_temp_filename).__name__}"
        )
    if not media_temp_filename:
        raise ValueError("media_temp_filename must not be empty")
    return (
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "image2",
        "-framerate",
        str(fps),
        "-start_number",
        "1",
        "-i",
        f"{ASSEMBLY_DIR_TOKEN}/presentation/frame_%07d.png",
        "-i",
        f"{STAGING_TOKEN}/{SNAPSHOT_AUDIO_FILENAME}",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        VIDEO_CODEC,
        "-preset",
        X264_PRESET,
        "-crf",
        str(X264_CRF),
        "-pix_fmt",
        PIX_FMT,
        "-threads:v",
        str(VIDEO_THREADS),
        "-frames:v",
        str(presentation_frames_total),
        "-fps_mode:v",
        "passthrough",
        "-c:a",
        AUDIO_CODEC,
        "-b:a",
        AAC_BITRATE,
        "-ar",
        str(audio_sample_rate_hz),
        "-ac",
        str(audio_channels),
        "-map_metadata",
        "-1",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        f"{STAGING_TOKEN}/{media_temp_filename}",
    )


def build_preflight_command(
    *,
    fps: int,
    presentation_frames_total: int,
    audio_sample_rate_hz: int,
    audio_channels: int,
) -> tuple[str, ...]:
    """Return the real-geometry self-test argv: the full output profile over tiny video.

    Byte-identical output-side flags to the real encode -- same codecs, preset, CRF,
    pixel format, ``-threads:v 0``, bitexact trio, faststart and explicit ``-f mp4`` --
    so a preflight pass proves the exact encode code path the real run will take; only the
    inputs and the video dimensions differ.
    """
    _require_positive_int(fps, "fps")
    _require_positive_int(presentation_frames_total, "presentation_frames_total")
    _require_positive_int(audio_sample_rate_hz, "audio_sample_rate_hz")
    _require_positive_int(audio_channels, "audio_channels")
    return (
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={_PREFLIGHT_VIDEO_SIZE}:rate={fps}",
        "-i",
        f"{STAGING_TOKEN}/{PREFLIGHT_AUDIO_FILENAME}",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        VIDEO_CODEC,
        "-preset",
        X264_PRESET,
        "-crf",
        str(X264_CRF),
        "-pix_fmt",
        PIX_FMT,
        "-threads:v",
        str(VIDEO_THREADS),
        "-frames:v",
        str(presentation_frames_total),
        "-fps_mode:v",
        "passthrough",
        "-c:a",
        AUDIO_CODEC,
        "-b:a",
        AAC_BITRATE,
        "-ar",
        str(audio_sample_rate_hz),
        "-ac",
        str(audio_channels),
        "-map_metadata",
        "-1",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        f"{STAGING_TOKEN}/{PREFLIGHT_MEDIA_FILENAME}",
    )


def build_probe_command() -> tuple[str, ...]:
    """Return the ffprobe argv that consumes the captured MP4 bytes through stdin.

    ``pipe:0`` is the whole input law: the probe receives the one captured observation and
    can never reopen a path -- reopening is exactly the TOCTOU seam the single-capture law
    exists to close. ``-count_frames`` forces the full-stream decode pass the frame-count
    closure needs.
    """
    return (
        "ffprobe",
        "-hide_banner",
        "-loglevel",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-count_frames",
        "-i",
        "pipe:0",
    )


def build_decode_command() -> tuple[str, ...]:
    """Return the decisive audio decode-count argv over the same captured bytes.

    Deliberately NO ``-ar`` and NO ``-ac``: the already-proven encoded stream's own sample
    rate and channel count remain authoritative, and the decode re-expresses exactly what
    the container carries -- raw interleaved PCM S16LE on stdout, headerless, so the
    decoded sample count is ``len(pcm) // (2 * channels)`` by the locked PCM16 law.
    """
    return (
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-map",
        "0:a:0",
        "-vn",
        "-c:a",
        "pcm_s16le",
        "-f",
        "s16le",
        "pipe:1",
    )


def substitute_paths(
    logical_argv: tuple[str, ...], *, assembly_dir: str, staging_dir: str
) -> list[str]:
    """Return the spawnable argv, with the two placeholder tokens resolved uniformly.

    The resolved argv exists only for the spawn and the runtime logs; canonical output
    records the placeholder form. Every element is substituted with the same two values,
    so the recorded and the spawned commands differ in exactly the declared tokens.

    Raises:
        TypeError: If a value has the wrong exact type.
    """
    if type(logical_argv) is not tuple:
        raise TypeError(f"logical_argv must be a tuple, got {type(logical_argv).__name__}")
    if type(assembly_dir) is not str:
        raise TypeError(f"assembly_dir must be a str, got {type(assembly_dir).__name__}")
    if type(staging_dir) is not str:
        raise TypeError(f"staging_dir must be a str, got {type(staging_dir).__name__}")
    resolved: list[str] = []
    for element in logical_argv:
        if type(element) is not str:
            raise TypeError(f"logical_argv elements must be str, got {type(element).__name__}")
        resolved.append(
            element.replace(ASSEMBLY_DIR_TOKEN, assembly_dir).replace(STAGING_TOKEN, staging_dir)
        )
    return resolved


def preflight_wav_bytes(sample_rate_hz: int, channels: int, samples: int) -> bytes:
    """Return a canonical 44-byte-header PCM16 WAV of exactly this many zero samples.

    The exact locked layout, field for field: ``"RIFF"`` + u32 riff_size (36 + data_size)
    + ``"WAVE"`` + ``"fmt "`` + u32 16 + u16 format 1 (PCM) + u16 channels + u32 sample
    rate + u32 byte rate (rate x block align) + u16 block align (channels x 2) + u16 bits
    16 + ``"data"`` + u32 data_size -- all little-endian -- followed by silence. A unit
    test proves this builder byte-equal to the locked Phase 29 serializer for the same
    silence; production deliberately does not import that serializer, preserving the
    phase boundary while the oracle test closes the header-drift risk.

    Raises:
        TypeError: If a value is not an exact ``int``.
        ValueError: If a value is not positive, or a chunk size exceeds the 32-bit field.
    """
    _require_positive_int(sample_rate_hz, "sample_rate_hz")
    _require_positive_int(channels, "channels")
    _require_positive_int(samples, "samples")
    data_size = samples * channels * _PCM_BYTES_PER_SAMPLE
    riff_size = 36 + data_size
    if riff_size > _MAX_CHUNK_BYTES:
        raise ValueError(
            f"a {samples}-sample, {channels}-channel WAV overflows the 32-bit RIFF size field"
        )
    block_align = channels * _PCM_BYTES_PER_SAMPLE
    byte_rate = sample_rate_hz * block_align
    header = (
        b"RIFF"
        + struct.pack("<I", riff_size)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", 16)
        + struct.pack("<H", 1)
        + struct.pack("<H", channels)
        + struct.pack("<I", sample_rate_hz)
        + struct.pack("<I", byte_rate)
        + struct.pack("<H", block_align)
        + struct.pack("<H", 16)
        + b"data"
        + struct.pack("<I", data_size)
    )
    if len(header) != _WAV_HEADER_BYTES:
        raise ValueError(f"the WAV header must be {_WAV_HEADER_BYTES} bytes, built {len(header)}")
    return header + bytes(data_size)


__all__ = [
    "build_decode_command",
    "build_media_encode_command",
    "build_preflight_command",
    "build_probe_command",
    "preflight_wav_bytes",
    "substitute_paths",
]
