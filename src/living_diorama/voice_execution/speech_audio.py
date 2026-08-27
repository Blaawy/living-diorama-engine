"""Read and write one voice unit's speech, using the standard library alone.

The independent audit says it trusts nothing the executor recorded, and that
has to include the executor's own claim about how many samples a unit's
speech holds. Recomputing that count means parsing the WAV file, and the
audit cannot ask the executor to do it: that module imports Kokoro and Torch
and this one may not.

Only the exact canonical profile this phase writes is understood: PCM16
little-endian, mono or the request's own declared channel count, no
ancillary chunk, no trailing byte. Anything else is refused rather than
half-decoded, because a comparison built on a half-understood file would be
worse than no comparison.

There is no `wave` import anywhere in this module, or anywhere in this
phase. The standard library's own WAV reader is permissive about exactly the
things this phase must not be permissive about -- extra chunks, extension
fields, trailing bytes -- so the closed parser here is hand-rolled, the same
choice ``frame_image.py`` makes for PNG one layer up.
"""

import math
import struct
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from living_diorama.voice_execution.voice_execution_spec import MAX_SPEECH_SAMPLES

RIFF_MAGIC: Final = b"RIFF"
WAVE_MAGIC: Final = b"WAVE"
FMT_CHUNK_ID: Final = b"fmt "
DATA_CHUNK_ID: Final = b"data"
FMT_CHUNK_SIZE: Final = 16
PCM_FORMAT_CODE: Final = 1
BITS_PER_SAMPLE: Final = 16
PCM_BYTES_PER_SAMPLE: Final = 2
WAV_HEADER_BYTES: Final = 44
PCM_SCALE: Final = 32767.0
PCM_MINIMUM: Final = -32768
PCM_MAXIMUM: Final = 32767
"""The canonical WAV profile this phase writes and reads, and nothing else.

No ``SAMPLE_RATE_HZ`` or channel-count literal is declared here: the rate and
channel count are data, read from the gate-verified Phase 28 voice request
and passed as parameters -- the same doctrine by which Phase 28 itself
refuses to hold a literal 24 for fps.
"""


class SpeechAudioProblem(ValueError):
    """A file that is not a unit of speech this phase wrote.

    Every way of being unreadable arrives here: a bad magic, a chunk out of
    the fixed order, a declared size that disagrees with the file's own
    length, a trailing byte. It exists so the audit can *report* a malformed
    unit, not die on one -- a single corrupt file must not stop the audit
    from reaching the rest of the episode.
    """


def pcm16_bytes(samples: Sequence[float], description: str) -> bytes:
    """Return the canonical PCM16 little-endian bytes for these float samples.

    Args:
        samples: One waveform's samples, each an exact built-in ``float`` in
            the conceptual range [-1.0, 1.0]. Never a ``numpy`` array and
            never ``numpy.float32`` elements -- this module reads only
            Python's own numeric types, and the executor's bridge is the one
            place that produces them (see
            :mod:`audio.kokoro.scripts.synthesize_episode`).
        description: What is being converted, used in error messages.

    Returns:
        ``len(samples) * PCM_BYTES_PER_SAMPLE`` bytes, little-endian signed
        16-bit, one sample at a time, in the order given. Conversion is 1:1
        in sample count.

    Raises:
        TypeError: If ``samples`` is not a sequence (excluding ``str`` and
            ``bytes``), or any element is not an exact ``float``.
        ValueError: If ``samples`` is empty, exceeds ``MAX_SPEECH_SAMPLES``,
            or any element is not finite.
    """
    if isinstance(samples, str | bytes) or not isinstance(samples, Sequence):
        raise TypeError(f"{description} must be a sequence of float, got {type(samples).__name__}")
    count = len(samples)
    if count == 0:
        raise ValueError(f"{description} carries zero samples; an empty utterance is not narration")
    if count > MAX_SPEECH_SAMPLES:
        raise ValueError(
            f"{description} carries {count} samples, beyond the {MAX_SPEECH_SAMPLES} "
            "plausibility rail"
        )
    values: list[int] = []
    for index, sample in enumerate(samples):
        if type(sample) is not float:
            raise TypeError(
                f"{description}[{index}] must be an exact float, got {type(sample).__name__}"
            )
        if not math.isfinite(sample):
            raise ValueError(f"{description}[{index}] must be finite, got {sample!r}")
        value = round(sample * PCM_SCALE)
        if value < PCM_MINIMUM:
            value = PCM_MINIMUM
        elif value > PCM_MAXIMUM:
            value = PCM_MAXIMUM
        values.append(value)
    return struct.pack(f"<{count}h", *values)


def canonical_wav_bytes(pcm: bytes, *, sample_rate_hz: int, channels: int) -> bytes:
    """Return the canonical WAV bytes for this PCM16 payload.

    Exactly forty-four header bytes, then the payload -- no ancillary chunk,
    no trailing byte. Because the serialization is total, ``sha256`` over the
    whole file is the one authoritative artifact digest; there is
    deliberately no second stream digest.

    Args:
        pcm: The exact PCM16 little-endian payload, e.g. from
            :func:`pcm16_bytes`.
        sample_rate_hz: The gate-verified request's sample rate, in Hz.
        channels: The gate-verified request's channel count.

    Raises:
        TypeError: If ``pcm`` is not ``bytes``, or ``sample_rate_hz`` /
            ``channels`` is not an exact ``int``.
        ValueError: If ``pcm`` is empty, its length is not a whole number of
            samples, or ``sample_rate_hz`` / ``channels`` is not positive, or
            the payload is too large for a 32-bit WAV size field.
    """
    if type(pcm) is not bytes:
        raise TypeError(f"pcm must be bytes, got {type(pcm).__name__}")
    if type(sample_rate_hz) is not int:
        raise TypeError(f"sample_rate_hz must be an int, got {type(sample_rate_hz).__name__}")
    if type(channels) is not int:
        raise TypeError(f"channels must be an int, got {type(channels).__name__}")
    if sample_rate_hz < 1:
        raise ValueError(f"sample_rate_hz must be >= 1, got {sample_rate_hz}")
    if channels < 1:
        raise ValueError(f"channels must be >= 1, got {channels}")

    data_size = len(pcm)
    if data_size == 0:
        raise ValueError("pcm must not be empty")
    if data_size % PCM_BYTES_PER_SAMPLE != 0:
        raise ValueError(
            f"pcm is {data_size} bytes, not a whole number of {PCM_BYTES_PER_SAMPLE}-byte samples"
        )
    block_align = channels * PCM_BYTES_PER_SAMPLE
    byte_rate = sample_rate_hz * block_align
    riff_size = 36 + data_size
    if riff_size > 0xFFFFFFFF or byte_rate > 0xFFFFFFFF:
        raise ValueError("pcm payload is too large for a 32-bit canonical WAV size field")

    header = (
        RIFF_MAGIC
        + struct.pack("<I", riff_size)
        + WAVE_MAGIC
        + FMT_CHUNK_ID
        + struct.pack("<I", FMT_CHUNK_SIZE)
        + struct.pack("<H", PCM_FORMAT_CODE)
        + struct.pack("<H", channels)
        + struct.pack("<I", sample_rate_hz)
        + struct.pack("<I", byte_rate)
        + struct.pack("<H", block_align)
        + struct.pack("<H", BITS_PER_SAMPLE)
        + DATA_CHUNK_ID
        + struct.pack("<I", data_size)
    )
    if len(header) != WAV_HEADER_BYTES:
        raise ValueError(
            f"internal error: header is {len(header)} bytes, expected {WAV_HEADER_BYTES}"
        )
    return header + pcm


def _parse(data: bytes, description: str) -> tuple[int, int, int]:
    """Return ``(sample_rate_hz, channels, data_size)``, closed over the fixed layout.

    Raises:
        SpeechAudioProblem: If ``data`` is not exactly one canonical WAV:
            wrong magic, wrong chunk order, an extension field, a declared
            size that disagrees with the file's own length, or any trailing
            byte.
    """
    if len(data) < WAV_HEADER_BYTES:
        raise SpeechAudioProblem(
            f"{description} is {len(data)} bytes, shorter than the {WAV_HEADER_BYTES}-byte "
            "canonical WAV header"
        )
    if data[0:4] != RIFF_MAGIC:
        raise SpeechAudioProblem(f"{description} does not begin with the RIFF signature")
    riff_size = int.from_bytes(data[4:8], "little")
    if data[8:12] != WAVE_MAGIC:
        raise SpeechAudioProblem(f"{description} does not declare the WAVE format")
    if data[12:16] != FMT_CHUNK_ID:
        raise SpeechAudioProblem(
            f"{description} does not carry 'fmt ' immediately after 'WAVE'; the canonical WAV "
            "chunk order is fixed and admits no other chunk"
        )
    fmt_size = int.from_bytes(data[16:20], "little")
    if fmt_size != FMT_CHUNK_SIZE:
        raise SpeechAudioProblem(
            f"{description} declares a {fmt_size}-byte fmt chunk; the canonical WAV fmt chunk "
            f"is exactly {FMT_CHUNK_SIZE} bytes and carries no extension"
        )
    format_code = int.from_bytes(data[20:22], "little")
    if format_code != PCM_FORMAT_CODE:
        raise SpeechAudioProblem(
            f"{description} declares format code {format_code}; only PCM ({PCM_FORMAT_CODE}) "
            "is canonical"
        )
    channels = int.from_bytes(data[22:24], "little")
    sample_rate_hz = int.from_bytes(data[24:28], "little")
    byte_rate = int.from_bytes(data[28:32], "little")
    block_align = int.from_bytes(data[32:34], "little")
    bits_per_sample = int.from_bytes(data[34:36], "little")
    if bits_per_sample != BITS_PER_SAMPLE:
        raise SpeechAudioProblem(
            f"{description} declares {bits_per_sample} bits per sample; only "
            f"{BITS_PER_SAMPLE} is canonical"
        )
    if channels < 1:
        raise SpeechAudioProblem(
            f"{description} declares {channels} channels; at least 1 is required"
        )
    if sample_rate_hz < 1:
        raise SpeechAudioProblem(
            f"{description} declares sample rate {sample_rate_hz}; at least 1 Hz is required"
        )
    expected_block_align = channels * PCM_BYTES_PER_SAMPLE
    if block_align != expected_block_align:
        raise SpeechAudioProblem(
            f"{description} declares block align {block_align}, but {channels} channel(s) at "
            f"{PCM_BYTES_PER_SAMPLE} bytes each is {expected_block_align}"
        )
    expected_byte_rate = sample_rate_hz * expected_block_align
    if byte_rate != expected_byte_rate:
        raise SpeechAudioProblem(
            f"{description} declares byte rate {byte_rate}, but {sample_rate_hz} Hz at "
            f"{expected_block_align} bytes per frame is {expected_byte_rate}"
        )
    if data[36:40] != DATA_CHUNK_ID:
        raise SpeechAudioProblem(
            f"{description} does not carry 'data' immediately after 'fmt '; the canonical WAV "
            "carries no other chunk"
        )
    data_size = int.from_bytes(data[40:44], "little")
    if data_size == 0:
        raise SpeechAudioProblem(f"{description} declares zero bytes of sample data")
    if data_size % PCM_BYTES_PER_SAMPLE != 0:
        raise SpeechAudioProblem(
            f"{description} declares {data_size} bytes of sample data, not a whole number of "
            f"{PCM_BYTES_PER_SAMPLE}-byte samples"
        )
    expected_total = WAV_HEADER_BYTES + data_size
    if len(data) != expected_total:
        raise SpeechAudioProblem(
            f"{description} is {len(data)} bytes, but its own header declares {data_size} "
            f"bytes of sample data, which with the {WAV_HEADER_BYTES}-byte header is "
            f"{expected_total}; a canonical WAV carries no trailing byte and no truncation"
        )
    expected_riff_size = 36 + data_size
    if riff_size != expected_riff_size:
        raise SpeechAudioProblem(
            f"{description} declares RIFF size {riff_size}, but 36 + {data_size} bytes of "
            f"sample data is {expected_riff_size}"
        )
    return sample_rate_hz, channels, data_size


def read_wav_facts(path: str | Path) -> tuple[int, int, int]:
    """Return one unit's sample rate, channel count and recomputed sample count.

    Raises:
        SpeechAudioProblem: If the file is not a structurally complete
            canonical WAV.
    """
    data = Path(path).read_bytes()
    sample_rate_hz, channels, data_size = _parse(data, str(path))
    return sample_rate_hz, channels, data_size // PCM_BYTES_PER_SAMPLE


def speech_sample_count(path: str | Path) -> int:
    """Return the one authoritative sample count, recomputed from the file's own bytes.

    The manifest is never measurement authority; the WAV is. This is the
    single recomputation every other measured fact in this phase reduces to.

    Raises:
        SpeechAudioProblem: If the file is not a structurally complete
            canonical WAV.
    """
    _, _, speech_samples = read_wav_facts(path)
    return speech_samples


def verify_speech_audio(
    path: str | Path, *, expected_sample_rate_hz: int, expected_channels: int
) -> list[str]:
    """Return every way this file fails to be canonical speech of the expected profile.

    An empty list means the file parses completely under the closed
    canonical layout and its declared rate and channel count equal the
    caller's expectations -- which must come from the bound plan's own
    ``voice`` block, never from a literal.

    Problems are returned rather than raised, so one bad unit becomes a
    finding rather than an exception that stops the audit from reaching the
    rest of the episode.

    Args:
        path: The speech file to parse.
        expected_sample_rate_hz: The gate-verified request's sample rate.
        expected_channels: The gate-verified request's channel count.

    Returns:
        Human-readable problems, empty when the file is sound.
    """
    try:
        sample_rate_hz, channels, _ = read_wav_facts(path)
    except SpeechAudioProblem as problem:
        return [str(problem)]
    problems: list[str] = []
    if sample_rate_hz != expected_sample_rate_hz:
        problems.append(
            f"{path} is sampled at {sample_rate_hz} Hz, but this execution's voice request "
            f"pins {expected_sample_rate_hz} Hz"
        )
    if channels != expected_channels:
        problems.append(
            f"{path} carries {channels} channel(s), but this execution's voice request pins "
            f"{expected_channels}"
        )
    return problems
