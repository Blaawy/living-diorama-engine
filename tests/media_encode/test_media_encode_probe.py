"""P35 probe normalization and stream-law tests (the V25-V44 normalization side).

These tests attack :mod:`living_diorama.media_encode.media_encode_probe` alone: the
exact rational and integer parsers, the 21-key normalization of one ffprobe report,
and every refusal of :func:`require_stream_facts` against the golden authorities.
No tool, file or subprocess is involved; the probe documents are hand-shaped from the
frozen reviewed observation (``368640 * 1/12288 == 30 == 720/24`` exactly).
"""

import copy
from math import gcd
from typing import Any

import pytest

from living_diorama.media_encode.media_encode_probe import (
    normalize_probe_document,
    parse_decimal_to_rational,
    parse_probe_int,
    parse_rational,
    require_stream_facts,
)
from living_diorama.media_encode.media_encode_schema_v1 import STREAMS_KEYS
from living_diorama.media_encode.media_encode_spec import MediaEncodeRefused


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


def make_streams(
    *,
    fps: int = 24,
    frames: int = 720,
    rate: int = 24000,
    channels: int = 1,
    width: int = 1280,
    height: int = 720,
    audio_samples_decoded: int = 720000,
) -> dict[str, Any]:
    """Return the normalized 21-key streams block for the golden observation."""
    return normalize_probe_document(
        make_probe_json(
            fps=fps, frames=frames, rate=rate, channels=channels, width=width, height=height
        ),
        audio_samples_decoded=audio_samples_decoded,
    )


def golden_authorities() -> dict[str, int]:
    """Return the frozen authorities the golden observation must satisfy."""
    return {
        "fps": 24,
        "presentation_frames_total": 720,
        "audio_sample_rate_hz": 24000,
        "audio_channels": 1,
        "audio_samples_total": 720000,
        "width": 1280,
        "height": 720,
    }


# ---------------------------------------------------------------------------
# parse_rational
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("24/1", (24, 1)), ("48/2", (24, 1)), ("0/1", (0, 1))],
)
def test_parse_rational_accepts(text: str, expected: tuple[int, int]) -> None:
    """A valid ``a/b`` string parses to an exact reduced rational."""
    assert parse_rational(text, "value") == expected


@pytest.mark.parametrize(
    ("value", "match"),
    [
        ("24", "expected 'numerator/denominator'"),
        ("a/b", "expected two decimal integers"),
        ("24/0", "denominator must be >= 1"),
        (24, "must be an ffprobe rational string"),
    ],
)
def test_parse_rational_refuses(value: object, match: str) -> None:
    """Malformed rationals refuse: no slash, non-integers, zero denominator, non-str."""
    with pytest.raises(MediaEncodeRefused, match=match):
        parse_rational(value, "value")


# ---------------------------------------------------------------------------
# parse_decimal_to_rational
# ---------------------------------------------------------------------------


def test_parse_decimal_zero_parses_reduced() -> None:
    """``'0.000000'`` parses to the exact reduced ``(0, 1)``."""
    assert parse_decimal_to_rational("0.000000", "value") == (0, 1)


def test_parse_decimal_negative_parses_reduced() -> None:
    """``'-0.042667'`` parses digit-by-digit to the exact reduced rational."""
    result = parse_decimal_to_rational("-0.042667", "value")
    assert result == (-42667, 1000000)
    assert gcd(abs(result[0]), result[1]) == 1


def test_parse_decimal_whole_number_parses() -> None:
    """A plain whole-number string parses over a power-of-ten of zero."""
    assert parse_decimal_to_rational("30", "value") == (30, 1)


@pytest.mark.parametrize("text", ["x", ""])
def test_parse_decimal_refuses(text: str) -> None:
    """Non-decimal strings refuse."""
    with pytest.raises(MediaEncodeRefused, match="expected a decimal number"):
        parse_decimal_to_rational(text, "value")


# ---------------------------------------------------------------------------
# parse_probe_int
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "expected"), [(5, 5), ("720", 720)])
def test_parse_probe_int_accepts(value: object, expected: int) -> None:
    """Exact ints and decimal-digit strings parse to exact ints."""
    assert parse_probe_int(value, "value") == expected


@pytest.mark.parametrize("value", ["7.2", True, "-3"])
def test_parse_probe_int_refuses(value: object) -> None:
    """Floats, bools (not exact ints) and signed strings refuse."""
    with pytest.raises(MediaEncodeRefused, match="must be an integer or decimal-digit string"):
        parse_probe_int(value, "value")


# ---------------------------------------------------------------------------
# normalize_probe_document
# ---------------------------------------------------------------------------


def test_normalize_golden_carries_exactly_the_21_stream_keys() -> None:
    """The golden report normalizes to exactly the frozen 21-key streams block."""
    streams = make_streams()
    assert set(streams) == set(STREAMS_KEYS)
    assert streams["video_duration_ts"] == 368640
    assert streams["audio_duration_ts"] == 720000
    assert streams["video_frames_counted"] == 720


def test_normalize_audio_samples_decoded_passed_through() -> None:
    """The decoded sample count is carried through untouched."""
    streams = make_streams(audio_samples_decoded=720000)
    assert streams["audio_samples_decoded"] == 720000


def test_normalize_container_formats_split() -> None:
    """The comma-separated format name splits into its member list."""
    assert make_streams()["container_formats"] == ["mov", "mp4", "m4a", "3gp", "3g2", "mj2"]


def test_normalize_start_prefers_start_pts() -> None:
    """``start_pts`` in the stream time base yields the exact zero start."""
    streams = make_streams()
    assert streams["video_start_time"] == [0, 1]
    assert streams["audio_start_time"] == [0, 1]


def test_normalize_start_time_fallback_works() -> None:
    """Without ``start_pts``, the decimal ``start_time`` string is used instead."""
    probe = make_probe_json()
    for stream in probe["streams"]:
        stream.pop("start_pts")
        stream["start_time"] = "0.000000"
    streams = normalize_probe_document(probe, audio_samples_decoded=720000)
    assert streams["video_start_time"] == [0, 1]
    assert streams["audio_start_time"] == [0, 1]


def test_normalize_no_stream_start_refused() -> None:
    """A stream carrying neither start_pts nor start_time is refused."""
    probe = make_probe_json()
    for stream in probe["streams"]:
        stream.pop("start_pts")
    with pytest.raises(MediaEncodeRefused, match="neither start_pts nor start_time"):
        normalize_probe_document(probe, audio_samples_decoded=720000)


@pytest.mark.parametrize("count", [1, 3])
def test_normalize_wrong_stream_count_refused(count: int) -> None:
    """Any report that is not exactly one video plus one audio stream is refused."""
    probe = make_probe_json()
    if count == 1:
        probe["streams"] = probe["streams"][:1]
    else:
        probe["streams"] = probe["streams"] + [dict(probe["streams"][1])]
    with pytest.raises(MediaEncodeRefused, match="exactly 2"):
        normalize_probe_document(probe, audio_samples_decoded=720000)


def test_normalize_swapped_codec_order_refused() -> None:
    """A report mapping the video stream to position 1 is refused."""
    probe = make_probe_json()
    probe["streams"][0]["codec_type"] = "audio"
    with pytest.raises(MediaEncodeRefused, match="maps the video stream"):
        normalize_probe_document(probe, audio_samples_decoded=720000)


def test_normalize_wrong_index_refused() -> None:
    """A stream declaring an index other than its position is refused."""
    probe = make_probe_json()
    probe["streams"][0]["index"] = 1
    with pytest.raises(MediaEncodeRefused, match="expected 0"):
        normalize_probe_document(probe, audio_samples_decoded=720000)


def test_normalize_missing_duration_ts_refused() -> None:
    """A video stream that must report duration_ts but does not is refused."""
    probe = make_probe_json()
    probe["streams"][0].pop("duration_ts")
    with pytest.raises(MediaEncodeRefused, match="must report it"):
        normalize_probe_document(probe, audio_samples_decoded=720000)


def test_normalize_missing_nb_read_frames_refused() -> None:
    """A video stream without nb_read_frames is refused."""
    probe = make_probe_json()
    probe["streams"][0].pop("nb_read_frames")
    with pytest.raises(MediaEncodeRefused, match="must report it"):
        normalize_probe_document(probe, audio_samples_decoded=720000)


def test_normalize_filename_never_copied() -> None:
    """The path-derived ``pipe:0`` filename is never copied into the streams block."""
    streams = make_streams()

    def values_contain(item: object, needle: str) -> bool:
        if item == needle:
            return True
        if isinstance(item, dict):
            return any(values_contain(v, needle) for v in item.values())
        if isinstance(item, list):
            return any(values_contain(v, needle) for v in item)
        return False

    assert not values_contain(streams, "pipe:0")
    assert "pipe:0" not in repr(streams)


def test_normalize_bool_audio_samples_decoded_typeerror() -> None:
    """A bool decoded count is not an exact int and raises TypeError."""
    with pytest.raises(TypeError, match="audio_samples_decoded must be an int"):
        normalize_probe_document(make_probe_json(), audio_samples_decoded=True)


# ---------------------------------------------------------------------------
# require_stream_facts
# ---------------------------------------------------------------------------


def test_require_stream_facts_golden_passes() -> None:
    """The golden streams block satisfies every law against the golden authorities."""
    require_stream_facts(make_streams(), **golden_authorities())


def _mutated(key: str, value: object) -> dict[str, Any]:
    """Return a deep copy of the golden streams block with one fact replaced."""
    streams = make_streams()
    streams[key] = copy.deepcopy(value)
    return streams


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("nb_streams", 3, "requires exactly 2"),
        ("video_codec", "mpeg4", "requires 'h264'"),
        ("video_pix_fmt", "yuv444p", "requires 'yuv420p'"),
        ("audio_codec", "mp3", "requires 'aac'"),
        ("video_width", 1281, "authoritative render dimensions"),
        ("video_height", 719, "authoritative render dimensions"),
        ("video_avg_frame_rate", [25, 1], "authoritative clock"),
        ("video_r_frame_rate", [25, 1], "authoritative clock"),
        ("video_frames_counted", 719, "never changes the episode's length"),
        ("video_frames_counted", 721, "never changes the episode's length"),
        ("video_duration_ts", 368639, "no tolerance"),
        ("video_start_time", [1, 24], "requires exactly zero"),
        ("audio_sample_rate", 48000, "authoritative rate"),
        ("audio_channels", 2, "authoritative count"),
        ("container_formats", ["mov", "m4a"], "never name 'mp4'"),
        ("audio_time_base", [1, 48000], "1/24000 base"),
        ("audio_duration_ts", 722049, "priming window"),
        ("audio_start_time", [1, 24000], "after zero"),
        ("audio_start_time", [-2049, 24000], "priming window"),
        ("audio_samples_decoded", 719000, "never changes the episode's length"),
        ("audio_samples_decoded", 719999, "never changes the episode's length"),
        ("audio_samples_decoded", 720001, "never changes the episode's length"),
    ],
)
def test_require_stream_facts_single_fact_mutations_refused(
    key: str, value: object, match: str
) -> None:
    """Each single-fact deviation from the golden observation refuses with its law."""
    with pytest.raises(MediaEncodeRefused, match=match):
        require_stream_facts(_mutated(key, value), **golden_authorities())


def test_require_stream_facts_priming_window_is_inclusive() -> None:
    """An audio duration exactly 2048 samples past the target still passes."""
    streams = _mutated("audio_duration_ts", 720000 + 2048)
    require_stream_facts(streams, **golden_authorities())


@pytest.mark.parametrize("decoded", [719999, 720001])
def test_require_stream_facts_decoded_edge_refused(decoded: int) -> None:
    """A single missing or surplus decoded sample refuses: the closure is sample-exact."""
    with pytest.raises(MediaEncodeRefused, match="never changes the episode's length"):
        require_stream_facts(_mutated("audio_samples_decoded", decoded), **golden_authorities())
