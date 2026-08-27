"""Unit tests for the Phase 29 PCM law, the canonical WAV writer and the closed parser.

The malformed corpus is driven through every reader, exactly as the render
execution suite's PNG corpus is driven through every PNG reader -- the
precedent this suite mirrors one layer down.
"""

import math
import struct
from pathlib import Path
from typing import Any

import pytest

from living_diorama.voice_execution.speech_audio import (
    PCM_BYTES_PER_SAMPLE,
    SpeechAudioProblem,
    canonical_wav_bytes,
    pcm16_bytes,
    read_wav_facts,
    speech_sample_count,
    verify_speech_audio,
)

# ---------------------------------------------------------------- PCM law


def test_zero_maps_to_zero() -> None:
    """Zero maps to zero."""
    assert pcm16_bytes([0.0], "x") == struct.pack("<h", 0)


def test_positive_one_maps_to_the_maximum() -> None:
    """+1.0 maps to the maximum positive PCM16 value."""
    assert pcm16_bytes([1.0], "x") == struct.pack("<h", 32767)


def test_negative_one_maps_to_negative_max_scale() -> None:
    """-1.0 maps to -32767: the scale is 32767, symmetric with +1.0, not the wider minimum."""
    assert pcm16_bytes([-1.0], "x") == struct.pack("<h", -32767)


def test_a_value_beyond_unit_range_clamps() -> None:
    """A value beyond the conceptual unit range clamps rather than wraps."""
    assert pcm16_bytes([2.0], "x") == struct.pack("<h", 32767)
    assert pcm16_bytes([-2.0], "x") == struct.pack("<h", -32768)


@pytest.mark.parametrize(
    ("numerator", "expected"),
    [
        (1, 0),  # x * 32767.0 == 0.5 exactly -> rounds to even (0)
        (3, 2),  # x * 32767.0 == 1.5 exactly -> rounds to even (2)
        (5, 2),  # x * 32767.0 == 2.5 exactly -> rounds to even (2)
        (7, 4),  # x * 32767.0 == 3.5 exactly -> rounds to even (4)
    ],
)
def test_round_half_even_boundaries(numerator: int, expected: int) -> None:
    """The .5 boundary rounds half to even, exactly as Python's built-in round does.

    ``numerator / 65534.0`` is chosen, rather than ``k / 32767.0``, because
    only this form's product with ``PCM_SCALE`` (32767.0) lands on an exact
    ``.5`` in IEEE-754 double precision -- verified empirically, since
    ``0.5 / 32767.0`` and ``1 / 65534.0`` are mathematically equal but not
    bit-identical floats.
    """
    value = numerator / 65534.0
    (result,) = struct.unpack("<h", pcm16_bytes([value], "x"))
    assert result == expected


def test_a_bool_where_a_float_is_required_is_refused() -> None:
    """A bool where a float is required is refused."""
    with pytest.raises(TypeError):
        pcm16_bytes([True], "x")  # type: ignore[list-item]


def test_an_int_where_a_float_is_required_is_refused() -> None:
    """An int where a float is required is refused."""
    with pytest.raises(TypeError):
        pcm16_bytes([0], "x")  # type: ignore[list-item]


def test_nan_is_refused() -> None:
    """NaN is refused."""
    with pytest.raises(ValueError, match="finite"):
        pcm16_bytes([math.nan], "x")


def test_positive_infinity_is_refused() -> None:
    """+Inf is refused."""
    with pytest.raises(ValueError, match="finite"):
        pcm16_bytes([math.inf], "x")


def test_negative_infinity_is_refused() -> None:
    """-Inf is refused."""
    with pytest.raises(ValueError, match="finite"):
        pcm16_bytes([-math.inf], "x")


def test_an_empty_sequence_is_refused() -> None:
    """An empty sequence is refused."""
    with pytest.raises(ValueError, match="zero samples"):
        pcm16_bytes([], "x")


def test_a_non_sequence_is_refused() -> None:
    """A non-sequence is refused."""
    with pytest.raises(TypeError):
        pcm16_bytes(3.0, "x")  # type: ignore[arg-type]


def test_a_string_is_refused_even_though_it_is_a_sequence() -> None:
    """A string is refused even though it is technically a sequence."""
    with pytest.raises(TypeError):
        pcm16_bytes("0.5", "x")  # type: ignore[arg-type]


def test_beyond_the_plausibility_rail_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Beyond the plausibility rail is refused."""
    monkeypatch.setattr("living_diorama.voice_execution.speech_audio.MAX_SPEECH_SAMPLES", 2)
    with pytest.raises(ValueError, match="plausibility rail"):
        pcm16_bytes([0.0, 0.0, 0.0], "x")


def test_count_is_preserved_one_to_one() -> None:
    """Conversion is 1:1 in sample count."""
    samples = [float(i) / 100 for i in range(-5, 5)]
    result = pcm16_bytes(samples, "x")
    assert len(result) == len(samples) * PCM_BYTES_PER_SAMPLE


# ---------------------------------------------------------------- canonical WAV writer


def test_the_header_is_exactly_44_bytes_with_the_right_magics() -> None:
    """The header is exactly 44 bytes, with the right magics at the right offsets."""
    pcm = pcm16_bytes([0.0], "x")
    wav = canonical_wav_bytes(pcm, sample_rate_hz=24000, channels=1)
    assert len(wav) == 44 + len(pcm)
    assert wav[0:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav[12:16] == b"fmt "
    assert wav[36:40] == b"data"


def test_the_byte_rate_and_block_align_are_exact() -> None:
    """The byte rate and block align are exact arithmetic over rate and channels."""
    pcm = pcm16_bytes([0.0, 0.0], "x")
    wav = canonical_wav_bytes(pcm, sample_rate_hz=24000, channels=1)
    assert struct.unpack("<I", wav[28:32])[0] == 48000
    assert struct.unpack("<H", wav[32:34])[0] == 2


def test_canonical_wav_bytes_refuses_empty_pcm() -> None:
    """canonical_wav_bytes refuses an empty payload."""
    with pytest.raises(ValueError, match="empty"):
        canonical_wav_bytes(b"", sample_rate_hz=24000, channels=1)


def test_canonical_wav_bytes_refuses_odd_length_pcm() -> None:
    """canonical_wav_bytes refuses a payload that is not a whole number of samples."""
    with pytest.raises(ValueError, match="whole number"):
        canonical_wav_bytes(b"\x00", sample_rate_hz=24000, channels=1)


def test_canonical_wav_bytes_refuses_non_bytes() -> None:
    """canonical_wav_bytes refuses a non-bytes payload."""
    with pytest.raises(TypeError):
        canonical_wav_bytes("not bytes", sample_rate_hz=24000, channels=1)  # type: ignore[arg-type]


def test_canonical_wav_bytes_refuses_non_positive_rate() -> None:
    """canonical_wav_bytes refuses a non-positive sample rate."""
    with pytest.raises(ValueError, match=">= 1"):
        canonical_wav_bytes(pcm16_bytes([0.0], "x"), sample_rate_hz=0, channels=1)


def test_canonical_wav_bytes_refuses_non_positive_channels() -> None:
    """canonical_wav_bytes refuses a non-positive channel count."""
    with pytest.raises(ValueError, match=">= 1"):
        canonical_wav_bytes(pcm16_bytes([0.0], "x"), sample_rate_hz=24000, channels=0)


def test_writer_and_parser_round_trip(tmp_path: Path) -> None:
    """The writer and the parser round-trip exactly."""
    samples = [0.0, 0.25, -0.25, 0.999]
    pcm = pcm16_bytes(samples, "x")
    wav = canonical_wav_bytes(pcm, sample_rate_hz=24000, channels=1)
    path = tmp_path / "unit.wav"
    path.write_bytes(wav)
    rate, channels, count = read_wav_facts(path)
    assert (rate, channels, count) == (24000, 1, len(samples))
    assert speech_sample_count(path) == len(samples)
    assert verify_speech_audio(path, expected_sample_rate_hz=24000, expected_channels=1) == []


# ---------------------------------------------------------------- malformed corpus


def _valid_wav(*, samples: int = 4, sample_rate_hz: int = 24000, channels: int = 1) -> bytes:
    pcm = pcm16_bytes([0.0] * samples, "x")
    return canonical_wav_bytes(pcm, sample_rate_hz=sample_rate_hz, channels=channels)


def _short_file() -> bytes:
    return _valid_wav()[:10]


def _bad_riff_magic() -> bytes:
    return b"XIFF" + _valid_wav()[4:]


def _bad_wave_magic() -> bytes:
    data = bytearray(_valid_wav())
    data[8:12] = b"WAVX"
    return bytes(data)


def _missing_fmt_chunk() -> bytes:
    data = bytearray(_valid_wav())
    data[12:16] = b"xxxx"
    return bytes(data)


def _fmt_after_data() -> bytes:
    data = bytearray(_valid_wav())
    data[12:16] = b"data"
    data[36:40] = b"fmt "
    return bytes(data)


def _extra_list_chunk() -> bytes:
    return _valid_wav() + b"LIST" + struct.pack("<I", 4) + b"xxxx"


def _unknown_chunk() -> bytes:
    return _valid_wav() + b"JUNK" + struct.pack("<I", 4) + b"\x01\x02\x03\x04"


def _fmt_size_not_16() -> bytes:
    data = bytearray(_valid_wav())
    data[16:20] = struct.pack("<I", 18)
    return bytes(data)


def _format_code_not_1() -> bytes:
    data = bytearray(_valid_wav())
    data[20:22] = struct.pack("<H", 3)  # IEEE float, not PCM
    return bytes(data)


def _bits_not_16() -> bytes:
    data = bytearray(_valid_wav())
    data[34:36] = struct.pack("<H", 8)
    return bytes(data)


def _channels_field_without_matching_rate_fields() -> bytes:
    data = bytearray(_valid_wav())
    data[22:24] = struct.pack("<H", 2)  # block_align/byte_rate now inconsistent
    return bytes(data)


def _wrong_block_align() -> bytes:
    data = bytearray(_valid_wav())
    data[32:34] = struct.pack("<H", 4)
    return bytes(data)


def _wrong_byte_rate() -> bytes:
    data = bytearray(_valid_wav())
    data[28:32] = struct.pack("<I", 1)
    return bytes(data)


def _riff_size_disagreeing() -> bytes:
    data = bytearray(_valid_wav())
    data[4:8] = struct.pack("<I", 999998)
    return bytes(data)


def _data_size_disagreeing() -> bytes:
    data = bytearray(_valid_wav())
    data[40:44] = struct.pack("<I", 100000)
    return bytes(data)


def _odd_data_size() -> bytes:
    data = bytearray(_valid_wav())
    data[40:44] = struct.pack("<I", 7)
    return bytes(data[:-1])


def _zero_length_data() -> bytes:
    data = bytearray(_valid_wav())
    data[4:8] = struct.pack("<I", 36)
    data[40:44] = struct.pack("<I", 0)
    return bytes(data[:44])


def _trailing_bytes_after_data() -> bytes:
    return _valid_wav() + b"\x00\x00"


STRUCTURAL_WAVS: dict[str, Any] = {
    "short file": _short_file,
    "bad RIFF magic": _bad_riff_magic,
    "bad WAVE magic": _bad_wave_magic,
    "missing fmt chunk": _missing_fmt_chunk,
    "fmt after data": _fmt_after_data,
    "extra LIST chunk": _extra_list_chunk,
    "unknown chunk": _unknown_chunk,
    "fmt size not 16": _fmt_size_not_16,
    "format code not 1": _format_code_not_1,
    "bits not 16": _bits_not_16,
    "channels field without matching rate fields": _channels_field_without_matching_rate_fields,
    "wrong block align": _wrong_block_align,
    "wrong byte rate": _wrong_byte_rate,
    "RIFF size disagreeing": _riff_size_disagreeing,
    "data size disagreeing": _data_size_disagreeing,
    "odd data size": _odd_data_size,
    "zero-length data": _zero_length_data,
    "trailing bytes after data": _trailing_bytes_after_data,
}


def _wrong_sample_rate() -> bytes:
    return _valid_wav(sample_rate_hz=8000)


def _wrong_channel_count() -> bytes:
    return _valid_wav(channels=2)


def _rate_and_channels_both_disagreeing() -> bytes:
    return _valid_wav(sample_rate_hz=8000, channels=2)


PROFILE_WAVS: dict[str, Any] = {
    "wrong sample rate": _wrong_sample_rate,
    "wrong channel count": _wrong_channel_count,
    "rate and channels both disagreeing": _rate_and_channels_both_disagreeing,
}

MALFORMED_WAVS: dict[str, Any] = {**STRUCTURAL_WAVS, **PROFILE_WAVS}

READERS = (read_wav_facts, speech_sample_count)


def test_the_corpus_is_at_least_twenty_one_cases() -> None:
    """The malformed corpus carries at least twenty-one cases."""
    assert len(MALFORMED_WAVS) >= 21


@pytest.mark.parametrize("label", sorted(STRUCTURAL_WAVS))
def test_every_structural_case_is_refused_by_every_reader(label: str, tmp_path: Path) -> None:
    """Every structural malformation is refused by every reader."""
    path = tmp_path / "bad.wav"
    path.write_bytes(STRUCTURAL_WAVS[label]())
    for reader in READERS:
        with pytest.raises(SpeechAudioProblem):
            reader(path)
    assert verify_speech_audio(path, expected_sample_rate_hz=24000, expected_channels=1) != []


@pytest.mark.parametrize("label", sorted(PROFILE_WAVS))
def test_every_profile_case_is_structurally_valid_but_fails_verification(
    label: str, tmp_path: Path
) -> None:
    """Every profile mismatch is structurally valid but fails verification against the plan."""
    path = tmp_path / "profile.wav"
    path.write_bytes(PROFILE_WAVS[label]())
    read_wav_facts(path)  # does not raise: structurally a complete, valid WAV
    problems = verify_speech_audio(path, expected_sample_rate_hz=24000, expected_channels=1)
    assert problems != []
