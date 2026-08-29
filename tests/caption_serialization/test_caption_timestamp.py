"""Unit tests for the Phase 34 caption timestamp law and its representation rail.

Covers ``boundary_ms``, ``cue_span_ms``, ``format_timestamp`` and
``derive_cue_spans``: derivation is total over the integer domain, and the
serializer refuses only at the frozen 100-hour rail, never at derivation time.
"""

import pytest

from living_diorama.caption.caption_spec import MAX_CAPTION_FRAME
from living_diorama.caption_serialization.caption_serialization_spec import (
    MAX_TIMESTAMP_MS,
    CaptionSerializationRefused,
)
from living_diorama.caption_serialization.caption_timestamp import (
    boundary_ms,
    cue_span_ms,
    derive_cue_spans,
    format_timestamp,
)


def _synthetic_cue(position: int, start_frame: int, end_frame: int) -> dict:
    """Synthetic cue."""
    return {
        "caption_id": f"caption_{position:04d}",
        "unit_id": f"unit_{position:04d}",
        "realization_id": f"realization_{position:04d}",
        "window_id": f"window_{position:04d}",
        "presentation_start_frame": start_frame,
        "presentation_end_frame": end_frame,
        "caption_text": "the north gate holds.",
    }


def _synthetic_plan(
    *,
    episode: int,
    mode: str,
    previous_episode: int | None,
    fps: int,
    presentation_frames_total: int,
    windows: tuple[tuple[int, int], ...],
) -> dict:
    """Synthetic valid episode caption plan."""
    captions = [
        _synthetic_cue(position, start_frame, end_frame)
        for position, (start_frame, end_frame) in enumerate(windows, start=1)
    ]
    caption_frames_total = sum(end - start + 1 for start, end in windows)
    return {
        "format": "living_diorama_episode_caption_plan",
        "schema_version": 1,
        "policy": "caption_policy_v1",
        "source": {
            "episode": episode,
            "mode": mode,
            "previous_episode": previous_episode,
            "presentation_plan_sha256": "a" * 64,
            "presentation_schema_version": 1,
            "realization_plan_sha256": "b" * 64,
            "realization_schema_version": 1,
        },
        "clock": {"fps": fps, "presentation_frames_total": presentation_frames_total},
        "captions": captions,
        "accounting": {
            "captions_total": len(captions),
            "caption_frames_total": caption_frames_total,
            "uncaptioned_frames_total": presentation_frames_total - caption_frames_total,
        },
    }


@pytest.mark.parametrize(
    ("offset", "fps", "expected"),
    (
        (24, 24, 1000),
        (168, 24, 7000),
        (528, 24, 22000),
        (672, 24, 28000),
        (720, 24, 30000),
    ),
)
def test_boundary_ms_positives(offset: int, fps: int, expected: int) -> None:
    """Boundary ms returns the exact positives."""
    assert boundary_ms(offset, fps) == expected


@pytest.mark.parametrize(
    ("offset", "fps", "expected"),
    (
        (1, 24, 41),
        (2, 24, 83),
        (25, 24, 1041),
    ),
)
def test_boundary_ms_floors_non_exact_offsets(offset: int, fps: int, expected: int) -> None:
    """Boundary ms floors the non exact offsets."""
    assert boundary_ms(offset, fps) == expected


@pytest.mark.parametrize("offset", range(25))
def test_boundary_ms_exact_iff_offset_divisible_by_three(offset: int) -> None:
    """Boundary ms exact iff offset divisible by three at 24 fps."""
    assert boundary_ms(offset, 24) == offset * 1000 // 24
    assert (offset * 1000 % 24 == 0) == (offset % 3 == 0)


def test_boundary_ms_zero_offset() -> None:
    """Boundary ms zero offset."""
    assert boundary_ms(0, 24) == 0


def test_boundary_ms_total_over_declared_domain() -> None:
    """Boundary ms total over declared domain."""
    for offset in range(0, 60):
        for fps in range(1, 30):
            assert boundary_ms(offset, fps) == offset * 1000 // fps


@pytest.mark.parametrize("bad", (True, 1.5, "1"))
def test_boundary_ms_refuses_bad_offset_type(bad: object) -> None:
    """Boundary ms refuses bad offset type."""
    with pytest.raises(TypeError, match="offset must be an int"):
        boundary_ms(bad, 24)


@pytest.mark.parametrize("bad", (True, 1.5, "24"))
def test_boundary_ms_refuses_bad_fps_type(bad: object) -> None:
    """Boundary ms refuses bad fps type."""
    with pytest.raises(TypeError, match="fps must be an int"):
        boundary_ms(24, bad)


def test_boundary_ms_refuses_negative_offset() -> None:
    """Boundary ms refuses negative offset."""
    with pytest.raises(ValueError, match="offset must be >= 0"):
        boundary_ms(-1, 24)


@pytest.mark.parametrize("fps", (0, -1))
def test_boundary_ms_refuses_non_positive_fps(fps: int) -> None:
    """Boundary ms refuses non positive fps."""
    with pytest.raises(ValueError, match="fps must be >= 1"):
        boundary_ms(24, fps)


def test_cue_span_ms_derives_half_open_span() -> None:
    """Cue span ms derives half open span."""
    cue = {"presentation_start_frame": 25, "presentation_end_frame": 168}
    assert cue_span_ms(cue, 24) == (1000, 7000)


def test_cue_span_ms_one_frame_cue_at_24_fps_is_positive() -> None:
    """Cue span ms one frame cue at 24 fps is positive."""
    cue = {"presentation_start_frame": 1, "presentation_end_frame": 1}
    assert cue_span_ms(cue, 24) == (0, 41)


def test_cue_span_ms_refuses_zero_length_span_at_forged_fps() -> None:
    """Cue span ms refuses zero length span at forged fps."""
    cue = {"presentation_start_frame": 3, "presentation_end_frame": 3}
    with pytest.raises(CaptionSerializationRefused, match="zero-length span"):
        cue_span_ms(cue, 2000)


def test_cue_span_ms_refuses_non_dict_cue() -> None:
    """Cue span ms refuses non dict cue."""
    with pytest.raises(TypeError, match="cue must be a dict"):
        cue_span_ms("cue", 24)


@pytest.mark.parametrize(
    ("start", "end"),
    (
        (True, 3),
        (3, True),
        ("1", 3),
        (3, "3"),
    ),
)
def test_cue_span_ms_refuses_non_int_frames(start: object, end: object) -> None:
    """Cue span ms refuses non int frames."""
    cue = {"presentation_start_frame": start, "presentation_end_frame": end}
    with pytest.raises(TypeError, match="must be an int"):
        cue_span_ms(cue, 24)


@pytest.mark.parametrize(
    ("start", "end"),
    (
        (0, 5),
        (MAX_CAPTION_FRAME + 1, MAX_CAPTION_FRAME + 1),
        (5, 4),
    ),
)
def test_cue_span_ms_refuses_invalid_frames(start: int, end: int) -> None:
    """Cue span ms refuses invalid frames."""
    cue = {"presentation_start_frame": start, "presentation_end_frame": end}
    with pytest.raises(ValueError):
        cue_span_ms(cue, 24)


@pytest.mark.parametrize(
    ("ms", "separator", "expected"),
    (
        (0, ",", "00:00:00,000"),
        (1000, ",", "00:00:01,000"),
        (28000, ".", "00:00:28.000"),
        (3_599_999, ",", "00:59:59,999"),
        (359_999_999, ",", "99:59:59,999"),
    ),
)
def test_format_timestamp_fixed_widths(ms: int, separator: str, expected: str) -> None:
    """Format timestamp fixed widths."""
    assert format_timestamp(ms, separator) == expected


@pytest.mark.parametrize("separator", (":", ";", ""))
def test_format_timestamp_refuses_bad_separator(separator: str) -> None:
    """Format timestamp refuses bad separator."""
    with pytest.raises(ValueError, match="separator must be ',' or '.'"):
        format_timestamp(0, separator)


@pytest.mark.parametrize("separator", (1, None))
def test_format_timestamp_refuses_non_str_separator(separator: object) -> None:
    """Format timestamp refuses non str separator."""
    with pytest.raises(TypeError, match="separator must be a str"):
        format_timestamp(0, separator)


@pytest.mark.parametrize("ms", ("1000", 1.5, True))
def test_format_timestamp_refuses_non_int_ms(ms: object) -> None:
    """Format timestamp refuses non int ms."""
    with pytest.raises(TypeError, match="ms must be an int"):
        format_timestamp(ms, ",")


def test_format_timestamp_refuses_negative_ms() -> None:
    """Format timestamp refuses negative ms."""
    with pytest.raises(CaptionSerializationRefused, match="cannot be negative"):
        format_timestamp(-1, ",")


@pytest.mark.parametrize("ms", (MAX_TIMESTAMP_MS, MAX_TIMESTAMP_MS + 1))
def test_format_timestamp_refuses_at_or_beyond_rail(ms: int) -> None:
    """Format timestamp refuses at or beyond rail."""
    with pytest.raises(CaptionSerializationRefused, match="representation"):
        format_timestamp(ms, ",")


def test_rail_reachability_arithmetic_pinned() -> None:
    """Rail reachability arithmetic pinned."""
    assert boundary_ms(1_000_000, 2) == 500_000_000
    assert boundary_ms(1_000_000, 2) >= MAX_TIMESTAMP_MS
    assert boundary_ms(1_000_000, 3) == 333_333_333
    assert boundary_ms(1_000_000, 3) < MAX_TIMESTAMP_MS
    assert boundary_ms(1_000_000, 1) == 1_000_000_000
    with pytest.raises(CaptionSerializationRefused, match="representation"):
        format_timestamp(boundary_ms(1_000_000, 2), ",")


def test_derive_cue_spans_single_cue_valid_plan() -> None:
    """Derive cue spans single cue valid plan."""
    plan = _synthetic_plan(
        episode=0,
        mode="baseline",
        previous_episode=None,
        fps=24,
        presentation_frames_total=192,
        windows=((25, 168),),
    )
    assert derive_cue_spans(plan) == ((1000, 7000),)


def test_derive_cue_spans_three_cue_tight_plan_adjacent_share_boundary() -> None:
    """Derive cue spans three cue tight plan adjacent share boundary."""
    plan = _synthetic_plan(
        episode=1,
        mode="transition",
        previous_episode=0,
        fps=24,
        presentation_frames_total=720,
        windows=((25, 168), (169, 528), (529, 672)),
    )
    assert derive_cue_spans(plan) == (
        (1000, 7000),
        (7000, 22000),
        (22000, 28000),
    )


def test_derive_cue_spans_refuses_non_dict_plan() -> None:
    """Derive cue spans refuses non dict plan."""
    with pytest.raises(TypeError):
        derive_cue_spans("not a plan")


@pytest.mark.parametrize("plan", ({}, {"format": "wrong"}))
def test_derive_cue_spans_refuses_malformed_plan_dict(plan: dict) -> None:
    """Derive cue spans refuses malformed plan dict."""
    with pytest.raises(ValueError):
        derive_cue_spans(plan)


def test_derive_cue_spans_refuses_overlapping_plan_via_schema() -> None:
    """Derive cue spans refuses overlapping plan via schema."""
    plan = _synthetic_plan(
        episode=0,
        mode="baseline",
        previous_episode=None,
        fps=24,
        presentation_frames_total=720,
        windows=((25, 168), (100, 200)),
    )
    with pytest.raises(ValueError, match="never overlap"):
        derive_cue_spans(plan)
