"""Unit tests for the Phase 32 caption policy: the one span law and its rail."""

import pytest

from living_diorama.caption.caption_spec import (
    CAPTION_ID_FORM,
    CAPTION_PLAN_FORMAT,
    CAPTION_POLICY_V1,
    CAPTION_SCHEMA_VERSION,
    MAX_CAPTION_FRAME,
    caption_frames_for_window,
)


def test_constants_frozen() -> None:
    """Constants frozen."""
    assert CAPTION_PLAN_FORMAT == "living_diorama_episode_caption_plan"
    assert CAPTION_SCHEMA_VERSION == 1
    assert CAPTION_POLICY_V1 == "caption_policy_v1"
    assert CAPTION_ID_FORM == "caption_%04d"
    assert MAX_CAPTION_FRAME == 1_000_000


def test_caption_frames_for_window_returns_unchanged() -> None:
    """Caption frames for window returns unchanged."""
    assert caption_frames_for_window(25, 168) == (25, 168)


def test_caption_frames_for_window_single_frame() -> None:
    """Caption frames for window single frame."""
    assert caption_frames_for_window(1, 1) == (1, 1)


def test_caption_frames_for_window_refuses_start_below_one() -> None:
    """Caption frames for window refuses start below one."""
    with pytest.raises(ValueError):
        caption_frames_for_window(0, 5)


def test_caption_frames_for_window_refuses_end_before_start() -> None:
    """Caption frames for window refuses end before start."""
    with pytest.raises(ValueError):
        caption_frames_for_window(10, 5)


def test_caption_frames_for_window_refuses_end_beyond_max() -> None:
    """Caption frames for window refuses end beyond max."""
    with pytest.raises(ValueError):
        caption_frames_for_window(1, MAX_CAPTION_FRAME + 1)


def test_caption_frames_for_window_accepts_max_boundary() -> None:
    """Caption frames for window accepts max boundary."""
    assert caption_frames_for_window(1, MAX_CAPTION_FRAME) == (1, MAX_CAPTION_FRAME)


def test_caption_frames_for_window_refuses_bool_start() -> None:
    """Caption frames for window refuses bool start."""
    with pytest.raises(TypeError):
        caption_frames_for_window(True, 5)


def test_caption_frames_for_window_refuses_bool_end() -> None:
    """Caption frames for window refuses bool end."""
    with pytest.raises(TypeError):
        caption_frames_for_window(1, True)


def test_caption_frames_for_window_refuses_non_int() -> None:
    """Caption frames for window refuses non int."""
    with pytest.raises(TypeError):
        caption_frames_for_window("1", 5)


def test_caption_id_form_positional() -> None:
    """Caption ID form positional."""
    assert CAPTION_ID_FORM % 1 == "caption_0001"
    assert CAPTION_ID_FORM % 42 == "caption_0042"
