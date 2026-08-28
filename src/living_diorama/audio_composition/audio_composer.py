"""Pure composition of one episode's audio track from placed source payloads.

The derivation is a pure function of its inputs. It reads no clock, draws no
randomness, consults no filesystem path, and depends on no iteration order
that Python is free to vary. Given the same sealed placements and the same
source payload bytes, it always produces the same composed bytes.

This module performs the one new decision Phase 31 makes: proving that a
sealed plan's speech spans are contained and non-overlapping, by integer
arithmetic alone -- never by inspecting PCM sample values, which are audio
content and were never timing authority. It then splices exactly the payload
bytes it is handed into a pre-zeroed buffer at exactly the offsets the plan
already sealed, and wraps the result in the one locked canonical WAV
serializer, imported from Phase 29 and never reimplemented here.
"""

from collections.abc import Mapping, Sequence
from typing import cast

from living_diorama.voice_execution.speech_audio import (
    PCM_BYTES_PER_SAMPLE,
    WAV_HEADER_BYTES,
    canonical_wav_bytes,
)

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in, declared locally per every locked phase."""


class CompositionRefused(ValueError):
    """The plan's geometry, a source payload, or the composed track refuses composition."""


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def require_placement_geometry(audio_track_plan: object) -> tuple[tuple[int, int], ...]:
    """Prove a sealed plan's speech spans are contained and non-overlapping.

    Evaluated over the plan's own records, in narration order, before any
    payload is ever written: this is the independent Phase 31
    containment/non-overlap proof, distinct from -- and never substituted
    by -- whether a destination byte happens to be zero. The whole Phase 30
    cross-check remains mandatory and unweakened elsewhere in the pipeline;
    this proof is defence in depth, run again here.

    Args:
        audio_track_plan: The sealed Episode Audio Track Plan V1 document.

    Returns:
        ``((start_sample, speech_samples), ...)`` in plan order.

    Raises:
        TypeError: If the plan's shape is wrong, or a span's ``start_sample``
            or ``speech_samples`` is not an exact ``int`` (``bool`` is
            refused because it subclasses ``int``).
        CompositionRefused: If any span is not contained within the plan's
            own ``audio_samples_total``, or if any span overlaps or
            precedes the one before it.
    """
    plan = _document(audio_track_plan, "audio track plan")
    clock = _document(plan.get("clock"), "audio track plan clock")
    audio_samples_total = clock.get("audio_samples_total")
    if type(audio_samples_total) is not int:
        raise TypeError(
            f"audio track plan clock audio_samples_total must be an int, got "
            f"{type(audio_samples_total).__name__}"
        )

    speech = plan.get("speech")
    if type(speech) is not list:
        raise TypeError(f"audio track plan speech must be a list, got {type(speech).__name__}")

    placements: list[tuple[int, int]] = []
    previous_end = 0
    for position, record in enumerate(speech, start=1):
        span = _document(record, f"audio track plan speech[{position - 1}]")
        start = span.get("start_sample")
        count = span.get("speech_samples")
        if type(start) is not int:
            raise TypeError(
                f"audio track plan speech[{position - 1}] start_sample must be an exact int, "
                f"got {type(start).__name__}"
            )
        if type(count) is not int:
            raise TypeError(
                f"audio track plan speech[{position - 1}] speech_samples must be an exact int, "
                f"got {type(count).__name__}"
            )
        if start < 0:
            raise CompositionRefused(
                f"audio track plan speech[{position - 1}] start_sample must be >= 0, got {start}"
            )
        if count < 1:
            raise CompositionRefused(
                f"audio track plan speech[{position - 1}] speech_samples must be >= 1, got {count}"
            )
        end = start + count
        if end > audio_samples_total:
            raise CompositionRefused(
                f"audio track plan speech[{position - 1}] spans [{start}, {end}), beyond the "
                f"plan's own {audio_samples_total} total samples"
            )
        if start < previous_end:
            raise CompositionRefused(
                f"audio track plan speech[{position - 1}] starts at {start}, before the "
                f"previous span ends at {previous_end}; spans never overlap and always follow "
                "narration order -- this is proven by interval arithmetic alone, never by "
                "inspecting whether the destination happens to be zero"
            )
        placements.append((start, count))
        previous_end = end
    return tuple(placements)


def pcm_payload_of(wav_bytes: bytes, *, expected_samples: int) -> bytes:
    """Return the exact PCM payload of one canonical WAV, after proving its total length.

    The slice is licensed by the closed canonical parser's own totality
    check -- a canonical WAV is exactly ``WAV_HEADER_BYTES`` plus
    ``speech_samples * PCM_BYTES_PER_SAMPLE`` bytes, with no trailing byte --
    never by an independent assumption about WAV layout.

    Raises:
        TypeError: If either argument is of the wrong exact type.
        CompositionRefused: If ``expected_samples`` is not positive, or the
            byte length does not equal the header plus that many samples.
    """
    if type(wav_bytes) is not bytes:
        raise TypeError(f"wav_bytes must be bytes, got {type(wav_bytes).__name__}")
    if type(expected_samples) is not int:
        raise TypeError(f"expected_samples must be an int, got {type(expected_samples).__name__}")
    if expected_samples < 1:
        raise CompositionRefused(f"expected_samples must be >= 1, got {expected_samples}")
    expected_length = WAV_HEADER_BYTES + expected_samples * PCM_BYTES_PER_SAMPLE
    if len(wav_bytes) != expected_length:
        raise CompositionRefused(
            f"source WAV is {len(wav_bytes)} bytes, but {expected_samples} samples at "
            f"{PCM_BYTES_PER_SAMPLE} bytes each plus the {WAV_HEADER_BYTES}-byte header is "
            f"{expected_length}"
        )
    return wav_bytes[WAV_HEADER_BYTES:]


def compose_episode_audio_bytes(
    *,
    audio_track_plan: object,
    payloads: Mapping[int, bytes],
    sample_rate_hz: int,
    channels: int,
) -> bytes:
    """Return the deterministic composed episode-length WAV bytes.

    Allocates a buffer of exactly the plan's own ``audio_samples_total``,
    zero-filled -- silence, by construction -- then splices each unit's
    payload verbatim at its sealed offset. No gain, no normalization, no
    trim, no resampling, no dither, no channel conversion, no mixing.

    Args:
        audio_track_plan: The sealed Episode Audio Track Plan V1 document.
        payloads: The exact PCM payload bytes for each unit, keyed by
            1-based plan position.
        sample_rate_hz: The profile this composition writes under.
        channels: The profile this composition writes under.

    Raises:
        TypeError: If any value is of the wrong exact type.
        CompositionRefused: If the geometry is unsound, a payload is
            missing or the wrong length, or a destination region is not
            currently zero (defence in depth; never the overlap proof --
            see :func:`require_placement_geometry`).
    """
    plan = _document(audio_track_plan, "audio track plan")
    clock = _document(plan.get("clock"), "audio track plan clock")
    audio_samples_total = clock.get("audio_samples_total")
    if type(audio_samples_total) is not int:
        raise TypeError("audio track plan clock audio_samples_total must be an int")

    placements = require_placement_geometry(plan)
    speech = cast(list[object], plan.get("speech"))

    track = bytearray(audio_samples_total * PCM_BYTES_PER_SAMPLE)
    for position, ((start, count), _record) in enumerate(
        zip(placements, speech, strict=True), start=1
    ):
        payload = payloads.get(position)
        if payload is None:
            raise CompositionRefused(f"no source payload was captured for voice unit {position}")
        if type(payload) is not bytes:
            raise TypeError(
                f"voice unit {position} payload must be bytes, got {type(payload).__name__}"
            )
        expected_length = count * PCM_BYTES_PER_SAMPLE
        if len(payload) != expected_length:
            raise CompositionRefused(
                f"voice unit {position} payload is {len(payload)} bytes, but its own "
                f"speech_samples of {count} at {PCM_BYTES_PER_SAMPLE} bytes each is "
                f"{expected_length}"
            )
        at = start * PCM_BYTES_PER_SAMPLE
        region = track[at : at + expected_length]
        if any(region):
            raise CompositionRefused(
                f"voice unit {position} would land on unexpected non-zero destination content "
                f"at byte offset {at}; this is defence in depth, never the overlap proof"
            )
        track[at : at + expected_length] = payload

    return canonical_wav_bytes(bytes(track), sample_rate_hz=sample_rate_hz, channels=channels)


def span_pcm(track_pcm: bytes, *, start_sample: int, speech_samples: int) -> bytes:
    """Return the exact PCM slice one placed span occupies in a composed track's payload.

    Raises:
        TypeError: If any argument is of the wrong exact type.
        CompositionRefused: If the requested interval escapes the track.
    """
    if type(track_pcm) is not bytes:
        raise TypeError(f"track_pcm must be bytes, got {type(track_pcm).__name__}")
    if type(start_sample) is not int:
        raise TypeError(f"start_sample must be an int, got {type(start_sample).__name__}")
    if type(speech_samples) is not int:
        raise TypeError(f"speech_samples must be an int, got {type(speech_samples).__name__}")
    if start_sample < 0 or speech_samples < 1:
        raise CompositionRefused(
            f"span [{start_sample}, {start_sample + speech_samples}) is not a valid interval"
        )
    at = start_sample * PCM_BYTES_PER_SAMPLE
    length = speech_samples * PCM_BYTES_PER_SAMPLE
    if at + length > len(track_pcm):
        raise CompositionRefused(
            f"span [{start_sample}, {start_sample + speech_samples}) escapes the composed "
            f"track's own {len(track_pcm) // PCM_BYTES_PER_SAMPLE} total samples"
        )
    return track_pcm[at : at + length]


def require_silence_complement(track_pcm: bytes, placements: Sequence[tuple[int, int]]) -> None:
    """Prove every sample outside every placed span is zero.

    This proves silence is a materialised fact, never a promise. It is not,
    and never substitutes for, the interval non-overlap proof in
    :func:`require_placement_geometry`.

    Raises:
        TypeError: If ``track_pcm`` is not ``bytes``.
        CompositionRefused: If any sample outside every placement is
            non-zero.
    """
    if type(track_pcm) is not bytes:
        raise TypeError(f"track_pcm must be bytes, got {type(track_pcm).__name__}")
    total_samples = len(track_pcm) // PCM_BYTES_PER_SAMPLE
    covered = bytearray(total_samples)
    for start, count in placements:
        for index in range(start, start + count):
            covered[index] = 1
    for index in range(total_samples):
        if covered[index]:
            continue
        at = index * PCM_BYTES_PER_SAMPLE
        if any(track_pcm[at : at + PCM_BYTES_PER_SAMPLE]):
            raise CompositionRefused(
                f"sample {index} lies outside every placed span, but is not zero; silence must "
                "be a materialised fact, never a promise"
            )


__all__ = [
    "CompositionRefused",
    "JsonValue",
    "compose_episode_audio_bytes",
    "pcm_payload_of",
    "require_placement_geometry",
    "require_silence_complement",
    "span_pcm",
]
