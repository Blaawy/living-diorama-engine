"""Normalize one ffprobe report into the frozen 21-key streams block, and its laws.

Every fact here is TOOL-ATTESTED: it records what the selected build reported about the
one captured MP4 observation, plus the decisive decoded sample count measured over those
same bytes. Normalization is exact -- integers are exact ints, rationals are reduced
``[numerator, denominator]`` pairs, decimal strings are parsed digit-by-digit over a power
of ten -- and ``float()`` appears nowhere. ``format.filename`` (``"pipe:0"``) is
path-derived and is never copied anywhere.

:func:`require_stream_facts` is the closure half: the exact video duration law
(``duration_ts x time_base == presentation_frames_total / fps``, no tolerance -- a build
that cannot satisfy it on the known preflight geometry is refused before any real encode),
the DESCRIPTIVE audio priming observations (a container-metadata plausibility window,
never an integrity closure), and the decisive exact decode-count law
(``audio_samples_decoded == audio_samples_total``): sample-exact, so even a single
missing or surplus sample -- and a fortiori one presentation frame's worth -- refuses.
"""

from math import gcd
from typing import Final, cast

from living_diorama.media_encode.media_encode_spec import (
    AUDIO_CODEC,
    PIX_FMT,
    MediaEncodeRefused,
)

_H264_CODEC_NAME: Final = "h264"
"""The probe-reported bitstream name the reviewed libx264 encoder produces."""

_CONTAINER_REQUIRED_MEMBER: Final = "mp4"
"""The one member the comma-split container format list must carry -- membership, never
equality, because the tag list varies by build."""

_PRIMING_TOLERANCE_SAMPLES: Final = 2048
"""The descriptive AAC priming window: encoder delay 1024 + final-frame padding, rounded
up to a power of two. A plausibility observation only -- it is wider than one
presentation frame of samples, so it closes nothing; the decode count does."""

Rational = tuple[int, int]
"""An exact non-negative-denominator rational as ``(numerator, denominator)``."""


def _reduce(numerator: int, denominator: int, description: str) -> Rational:
    if denominator < 1:
        raise MediaEncodeRefused(f"{description} denominator must be >= 1, got {denominator}")
    divisor = gcd(abs(numerator), denominator)
    if divisor == 0:
        return (0, 1)
    return (numerator // divisor, denominator // divisor)


def parse_rational(value: object, description: str) -> Rational:
    """Return an exact reduced rational parsed from an ffprobe ``"a/b"`` string.

    Raises:
        MediaEncodeRefused: If the value is not a string of two decimal integers joined
            by one ``/``, or the denominator is not positive.
    """
    if type(value) is not str:
        raise MediaEncodeRefused(
            f"{description} must be an ffprobe rational string, got {type(value).__name__}"
        )
    parts = value.split("/")
    if len(parts) != 2:
        raise MediaEncodeRefused(f"{description} is {value!r}, expected 'numerator/denominator'")
    try:
        numerator = int(parts[0])
        denominator = int(parts[1])
    except ValueError:
        raise MediaEncodeRefused(
            f"{description} is {value!r}, expected two decimal integers"
        ) from None
    return _reduce(numerator, denominator, description)


def parse_decimal_to_rational(value: object, description: str) -> Rational:
    """Return an exact reduced rational parsed from an ffprobe decimal string.

    Sign, integer part and fraction digits over a power of ten -- never ``float()``, so
    the parse is exact for every string the tool can emit.

    Raises:
        MediaEncodeRefused: If the value is not a plain decimal string.
    """
    if type(value) is not str:
        raise MediaEncodeRefused(
            f"{description} must be an ffprobe decimal string, got {type(value).__name__}"
        )
    text = value
    sign = 1
    if text.startswith("-"):
        sign = -1
        text = text[1:]
    whole, _, fraction = text.partition(".")
    if not whole and not fraction:
        raise MediaEncodeRefused(f"{description} is {value!r}, expected a decimal number")
    digits = (whole or "0") + fraction
    if not digits.isascii() or not digits.isdigit():
        raise MediaEncodeRefused(f"{description} is {value!r}, expected a decimal number")
    return _reduce(sign * int(digits), 10 ** len(fraction), description)


def parse_probe_int(value: object, description: str) -> int:
    """Return an exact int parsed from an ffprobe integer field (int or decimal string).

    Raises:
        MediaEncodeRefused: If the value is neither an exact int nor a string of ASCII
            decimal digits.
    """
    if type(value) is int:
        return value
    if type(value) is str and value.isascii() and value.isdigit():
        return int(value)
    raise MediaEncodeRefused(
        f"{description} must be an integer or decimal-digit string, got {value!r}"
    )


def _rational_pair(value: Rational) -> list[int]:
    return [value[0], value[1]]


def _stream_start(stream: dict[str, object], time_base: Rational, description: str) -> Rational:
    """Return one stream's exact start as a rational, from ``start_pts`` or ``start_time``.

    ``start_pts`` -- an exact integer in the stream's own time base -- is preferred;
    the decimal ``start_time`` string is the fallback. At least one must be present:
    the preflight proves presence on the selected build before any real encode.
    """
    start_pts = stream.get("start_pts")
    if start_pts is not None:
        ticks = parse_probe_int(start_pts, f"{description} start_pts")
        return _reduce(ticks * time_base[0], time_base[1], f"{description} start")
    start_time = stream.get("start_time")
    if start_time is not None:
        return parse_decimal_to_rational(start_time, f"{description} start_time")
    raise MediaEncodeRefused(
        f"{description} carries neither start_pts nor start_time; the selected build must "
        "report a stream start"
    )


def normalize_probe_document(probe: object, *, audio_samples_decoded: int) -> dict[str, object]:
    """Return the frozen 21-key streams block for one probe report.

    Args:
        probe: The parsed ffprobe JSON document for the one captured MP4 observation.
        audio_samples_decoded: The decisive sample count measured by decoding the SAME
            captured bytes (never a probe field): ``len(pcm) // (2 * channels)`` after
            the divisibility law.

    Raises:
        MediaEncodeRefused: If the report does not carry exactly one video stream at
            index 0 and one audio stream at index 1, or any required field is absent or
            malformed.
        TypeError: If ``audio_samples_decoded`` is not an exact ``int``.
    """
    if type(audio_samples_decoded) is not int:
        raise TypeError(
            f"audio_samples_decoded must be an int, got {type(audio_samples_decoded).__name__}"
        )
    if type(probe) is not dict:
        raise MediaEncodeRefused(
            f"the probe report must be a JSON object, got {type(probe).__name__}"
        )
    document = cast(dict[str, object], probe)
    streams_value = document.get("streams")
    if type(streams_value) is not list:
        raise MediaEncodeRefused("the probe report carries no streams list")
    streams = cast(list[object], streams_value)
    if len(streams) != 2:
        raise MediaEncodeRefused(
            f"the probe reports {len(streams)} streams, but the reviewed profile produces "
            "exactly 2: one video and one audio"
        )
    format_value = document.get("format")
    if type(format_value) is not dict:
        raise MediaEncodeRefused("the probe report carries no format object")
    format_document = cast(dict[str, object], format_value)
    format_name = format_document.get("format_name")
    if type(format_name) is not str or not format_name:
        raise MediaEncodeRefused("the probe report carries no format_name")

    def stream_at(position: int, expected_type: str) -> dict[str, object]:
        value = streams[position]
        if type(value) is not dict:
            raise MediaEncodeRefused(f"probe stream {position} is not an object")
        stream = cast(dict[str, object], value)
        codec_type = stream.get("codec_type")
        if codec_type != expected_type:
            raise MediaEncodeRefused(
                f"probe stream {position} is {codec_type!r}, but the reviewed profile maps "
                f"the {expected_type} stream there"
            )
        index = parse_probe_int(stream.get("index"), f"probe stream {position} index")
        if index != position:
            raise MediaEncodeRefused(
                f"probe stream {position} declares index {index}, expected {position}"
            )
        return stream

    video = stream_at(0, "video")
    audio = stream_at(1, "audio")

    video_time_base = parse_rational(video.get("time_base"), "video stream time_base")
    audio_time_base = parse_rational(audio.get("time_base"), "audio stream time_base")

    def required(stream: dict[str, object], key: str, description: str) -> object:
        value = stream.get(key)
        if value is None:
            raise MediaEncodeRefused(
                f"{description} carries no {key}; the selected build must report it"
            )
        return value

    video_codec = required(video, "codec_name", "the video stream")
    if type(video_codec) is not str:
        raise MediaEncodeRefused(f"video codec_name must be a str, got {video_codec!r}")
    pix_fmt = required(video, "pix_fmt", "the video stream")
    if type(pix_fmt) is not str:
        raise MediaEncodeRefused(f"video pix_fmt must be a str, got {pix_fmt!r}")
    audio_codec = required(audio, "codec_name", "the audio stream")
    if type(audio_codec) is not str:
        raise MediaEncodeRefused(f"audio codec_name must be a str, got {audio_codec!r}")

    return {
        "audio_channels": parse_probe_int(
            required(audio, "channels", "the audio stream"), "audio channels"
        ),
        "audio_codec": audio_codec,
        "audio_duration_ts": parse_probe_int(
            required(audio, "duration_ts", "the audio stream"), "audio duration_ts"
        ),
        "audio_index": 1,
        "audio_sample_rate": parse_probe_int(
            required(audio, "sample_rate", "the audio stream"), "audio sample_rate"
        ),
        "audio_samples_decoded": audio_samples_decoded,
        "audio_start_time": _rational_pair(
            _stream_start(audio, audio_time_base, "the audio stream")
        ),
        "audio_time_base": _rational_pair(audio_time_base),
        "container_formats": [member for member in format_name.split(",")],
        "nb_streams": 2,
        "video_avg_frame_rate": _rational_pair(
            parse_rational(video.get("avg_frame_rate"), "video avg_frame_rate")
        ),
        "video_codec": video_codec,
        "video_duration_ts": parse_probe_int(
            required(video, "duration_ts", "the video stream"), "video duration_ts"
        ),
        "video_frames_counted": parse_probe_int(
            required(video, "nb_read_frames", "the video stream"), "video nb_read_frames"
        ),
        "video_height": parse_probe_int(
            required(video, "height", "the video stream"), "video height"
        ),
        "video_index": 0,
        "video_pix_fmt": pix_fmt,
        "video_r_frame_rate": _rational_pair(
            parse_rational(video.get("r_frame_rate"), "video r_frame_rate")
        ),
        "video_start_time": _rational_pair(
            _stream_start(video, video_time_base, "the video stream")
        ),
        "video_time_base": _rational_pair(video_time_base),
        "video_width": parse_probe_int(required(video, "width", "the video stream"), "video width"),
    }


def require_stream_facts(
    streams: dict[str, object],
    *,
    fps: int,
    presentation_frames_total: int,
    audio_sample_rate_hz: int,
    audio_channels: int,
    audio_samples_total: int,
    width: int,
    height: int,
) -> None:
    """Refuse unless every frozen stream law holds against the current authorities.

    The laws, whole: 2 streams at the mapped indexes; h264 + aac; the reviewed pixel
    format; the authoritative dimensions; both frame-rate rationals exactly ``fps/1``;
    counted frames exactly ``presentation_frames_total``; the EXACT video duration law
    (``duration_ts x time_base == presentation_frames_total / fps`` as a rational, no
    tolerance); video start exactly zero; the audio rate and channel authorities; the
    container membership law; the DESCRIPTIVE audio priming window (duration within 2048
    samples of the target, start within ``[-2048/rate, 0]``); and the DECISIVE exact
    decode-count law ``audio_samples_decoded == audio_samples_total`` -- sample-exact,
    with no tolerance fallback, so a presentation frame's worth of missing audio can
    never pass.

    Raises:
        MediaEncodeRefused: On the first law the attested facts violate.
    """

    def fact(key: str) -> object:
        if key not in streams:
            raise MediaEncodeRefused(f"the streams block carries no {key}")
        return streams[key]

    def int_fact(key: str) -> int:
        value = fact(key)
        if type(value) is not int:
            raise MediaEncodeRefused(f"streams {key} must be an int, got {value!r}")
        return value

    def rational_fact(key: str) -> Rational:
        value = fact(key)
        if (
            type(value) is not list
            or len(cast(list[object], value)) != 2
            or any(type(member) is not int for member in cast(list[object], value))
        ):
            raise MediaEncodeRefused(f"streams {key} must be a two-int rational, got {value!r}")
        pair = cast(list[int], value)
        return (pair[0], pair[1])

    if int_fact("nb_streams") != 2:
        raise MediaEncodeRefused(
            f"the probe reports {streams['nb_streams']!r} streams, but the reviewed profile "
            "requires exactly 2"
        )
    if int_fact("video_index") != 0 or int_fact("audio_index") != 1:
        raise MediaEncodeRefused("the reviewed profile maps video to index 0 and audio to 1")
    if fact("video_codec") != _H264_CODEC_NAME:
        raise MediaEncodeRefused(
            f"the probe reports video codec {streams['video_codec']!r}, but the reviewed "
            f"profile requires {_H264_CODEC_NAME!r}"
        )
    if fact("video_pix_fmt") != PIX_FMT:
        raise MediaEncodeRefused(
            f"the probe reports pixel format {streams['video_pix_fmt']!r}, but the reviewed "
            f"profile requires {PIX_FMT!r}"
        )
    if fact("audio_codec") != AUDIO_CODEC:
        raise MediaEncodeRefused(
            f"the probe reports audio codec {streams['audio_codec']!r}, but the reviewed "
            f"profile requires {AUDIO_CODEC!r}"
        )
    if int_fact("video_width") != width or int_fact("video_height") != height:
        raise MediaEncodeRefused(
            f"the probe reports {streams['video_width']!r}x{streams['video_height']!r}, but "
            f"the authoritative render dimensions are {width}x{height}"
        )
    for key in ("video_avg_frame_rate", "video_r_frame_rate"):
        if rational_fact(key) != (fps, 1):
            raise MediaEncodeRefused(
                f"the probe reports {key} {streams[key]!r}, but the authoritative clock is "
                f"[{fps}, 1]"
            )
    if int_fact("video_frames_counted") != presentation_frames_total:
        raise MediaEncodeRefused(
            f"the probe counts {streams['video_frames_counted']!r} video frames, but the "
            f"authoritative clock carries {presentation_frames_total}; a viewing projection "
            "never changes the episode's length"
        )

    video_duration_ts = int_fact("video_duration_ts")
    video_time_base = rational_fact("video_time_base")
    if video_duration_ts * video_time_base[0] * fps != (
        presentation_frames_total * video_time_base[1]
    ):
        raise MediaEncodeRefused(
            f"the video stream's duration_ts {video_duration_ts} x time_base "
            f"{streams['video_time_base']!r} does not equal the exact "
            f"{presentation_frames_total}/{fps} s presentation duration; the exact video "
            "duration law admits no tolerance"
        )
    if rational_fact("video_start_time") != (0, 1):
        raise MediaEncodeRefused(
            f"the video stream starts at {streams['video_start_time']!r}, but the reviewed "
            "profile requires exactly zero"
        )

    if int_fact("audio_sample_rate") != audio_sample_rate_hz:
        raise MediaEncodeRefused(
            f"the probe reports audio sample rate {streams['audio_sample_rate']!r}, but the "
            f"authoritative rate is {audio_sample_rate_hz}"
        )
    if int_fact("audio_channels") != audio_channels:
        raise MediaEncodeRefused(
            f"the probe reports {streams['audio_channels']!r} audio channels, but the "
            f"authoritative count is {audio_channels}"
        )

    container = fact("container_formats")
    if type(container) is not list or any(
        type(member) is not str for member in cast(list[object], container)
    ):
        raise MediaEncodeRefused(
            f"streams container_formats must be a list of strings, got {container!r}"
        )
    if _CONTAINER_REQUIRED_MEMBER not in cast(list[str], container):
        raise MediaEncodeRefused(
            f"the probe reports container formats {container!r}, which never name "
            f"{_CONTAINER_REQUIRED_MEMBER!r}"
        )

    # ---- DESCRIPTIVE priming observations: plausibility, never an integrity closure ----
    audio_duration_ts = int_fact("audio_duration_ts")
    audio_time_base = rational_fact("audio_time_base")
    if audio_time_base[1] != audio_sample_rate_hz or audio_time_base[0] != 1:
        raise MediaEncodeRefused(
            f"the audio stream's time_base is {streams['audio_time_base']!r}, but the "
            f"reviewed container carries AAC on a 1/{audio_sample_rate_hz} base"
        )
    target_samples = audio_samples_total
    deviation_samples = audio_duration_ts - target_samples
    if abs(deviation_samples) > _PRIMING_TOLERANCE_SAMPLES:
        raise MediaEncodeRefused(
            f"the audio stream's duration_ts {audio_duration_ts} deviates from the "
            f"{target_samples}-sample target by {deviation_samples} samples, outside the "
            f"descriptive {_PRIMING_TOLERANCE_SAMPLES}-sample priming window"
        )
    audio_start = rational_fact("audio_start_time")
    # start in [-2048/rate, 0]: -2048 * den_rate <= num * rate... compare via cross terms.
    start_numerator, start_denominator = audio_start
    if start_numerator > 0:
        raise MediaEncodeRefused(
            f"the audio stream starts at {streams['audio_start_time']!r}, after zero"
        )
    if start_numerator * audio_sample_rate_hz < -_PRIMING_TOLERANCE_SAMPLES * start_denominator:
        raise MediaEncodeRefused(
            f"the audio stream starts at {streams['audio_start_time']!r}, before the "
            f"descriptive -{_PRIMING_TOLERANCE_SAMPLES}/{audio_sample_rate_hz} s priming "
            "window"
        )

    # ---- THE DECISIVE EXACT CLOSURE: decoded length equals the locked clock total ----
    decoded = int_fact("audio_samples_decoded")
    if decoded != audio_samples_total:
        raise MediaEncodeRefused(
            f"the captured media decodes to {decoded} audio samples, but the locked clock "
            f"carries {audio_samples_total}; a viewing projection never changes the "
            "episode's length"
        )


__all__ = [
    "Rational",
    "normalize_probe_document",
    "parse_decimal_to_rational",
    "parse_probe_int",
    "parse_rational",
    "require_stream_facts",
]
