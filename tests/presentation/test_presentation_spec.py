"""Phase 27 presentation policy: closed constants and exact arithmetic."""

import pytest

from living_diorama.narration.narration_spec import (
    TEXT_SOURCE_MEMORY_FACT_SUMMARY,
    TEXT_SOURCE_NARRATION_TEMPLATE,
)
from living_diorama.narration_delivery.delivery_schema_v1 import DELIVERY_TIMELINE_KEYS
from living_diorama.presentation.presentation_schema_v1 import PRESENTATION_TIMELINE_KEYS
from living_diorama.presentation.presentation_spec import (
    MAX_PRESENTATION_FRAME,
    PRESENTATION_PLAN_FORMAT,
    PRESENTATION_POLICY_V1,
    PRESENTATION_SCHEMA_VERSION,
    SEGMENT_ID_FORM,
    WINDOW_FRAMES_BY_TEXT_SOURCE,
    WINDOW_ID_FORM,
    WINDOW_PRESENTATION_FRAMES_FACT,
    WINDOW_PRESENTATION_FRAMES_TEMPLATE,
    window_and_hold,
    window_frames_for_text_source,
)


def test_the_format_and_policy_tags_are_the_reviewed_strings() -> None:
    """The format and policy tags are the reviewed strings."""
    assert PRESENTATION_PLAN_FORMAT == "living_diorama_episode_presentation_plan"
    assert PRESENTATION_POLICY_V1 == "presentation_policy_v1"
    assert PRESENTATION_SCHEMA_VERSION == 1


def test_the_id_forms_are_positional_percent_forms() -> None:
    """The ID forms are positional percent forms."""
    assert SEGMENT_ID_FORM % 1 == "segment_0001"
    assert SEGMENT_ID_FORM % 42 == "segment_0042"
    assert WINDOW_ID_FORM % 1 == "window_0001"
    assert WINDOW_ID_FORM % 42 == "window_0042"


def test_the_two_window_floors_are_whole_seconds_at_the_pinned_clock() -> None:
    """6.0 s and 15.0 s at 24 fps -- both exact, both reviewed."""
    assert WINDOW_PRESENTATION_FRAMES_TEMPLATE == 144
    assert WINDOW_PRESENTATION_FRAMES_TEMPLATE / 24 == 6.0
    assert WINDOW_PRESENTATION_FRAMES_FACT == 360
    assert WINDOW_PRESENTATION_FRAMES_FACT / 24 == 15.0
    assert WINDOW_PRESENTATION_FRAMES_FACT > WINDOW_PRESENTATION_FRAMES_TEMPLATE


def test_the_fact_floor_exceeds_the_template_floor() -> None:
    """A compound persistence restatement gets more room than a single clause."""
    assert WINDOW_PRESENTATION_FRAMES_FACT > WINDOW_PRESENTATION_FRAMES_TEMPLATE


def test_the_max_presentation_frame_is_this_layers_own_rail() -> None:
    """The max presentation frame is this layers own rail."""
    assert MAX_PRESENTATION_FRAME == 1_000_000


def test_the_timeline_key_set_agrees_with_the_delivery_plans() -> None:
    """A restated clock's key set must never silently drift from its source."""
    assert PRESENTATION_TIMELINE_KEYS == DELIVERY_TIMELINE_KEYS


def test_the_window_floor_map_is_closed_and_total_over_the_two_text_sources() -> None:
    """The window floor map is closed and total over the two text sources."""
    assert set(WINDOW_FRAMES_BY_TEXT_SOURCE) == {
        TEXT_SOURCE_NARRATION_TEMPLATE,
        TEXT_SOURCE_MEMORY_FACT_SUMMARY,
    }
    assert WINDOW_FRAMES_BY_TEXT_SOURCE[TEXT_SOURCE_NARRATION_TEMPLATE] == (
        WINDOW_PRESENTATION_FRAMES_TEMPLATE
    )
    assert WINDOW_FRAMES_BY_TEXT_SOURCE[TEXT_SOURCE_MEMORY_FACT_SUMMARY] == (
        WINDOW_PRESENTATION_FRAMES_FACT
    )


@pytest.mark.parametrize(
    ("text_source", "expected"),
    [
        (TEXT_SOURCE_NARRATION_TEMPLATE, WINDOW_PRESENTATION_FRAMES_TEMPLATE),
        (TEXT_SOURCE_MEMORY_FACT_SUMMARY, WINDOW_PRESENTATION_FRAMES_FACT),
    ],
)
def test_window_frames_for_text_source_returns_the_closed_floor(
    text_source: str, expected: int
) -> None:
    """Window frames for text source returns the closed floor."""
    assert window_frames_for_text_source(text_source) == expected


def test_window_frames_for_text_source_refuses_an_unknown_family() -> None:
    """Window frames for text source refuses an unknown family."""
    with pytest.raises(ValueError, match="not one of the closed wording families"):
        window_frames_for_text_source("SOMETHING_ELSE")


def test_window_frames_for_text_source_refuses_the_realized_text_field_name() -> None:
    """A plausible-looking but wrong string is refused, not coerced."""
    with pytest.raises(ValueError):
        window_frames_for_text_source("realized_text")


@pytest.mark.parametrize(
    ("slot_start", "slot_end", "text_source", "window", "hold"),
    [
        (25, 60, TEXT_SOURCE_NARRATION_TEMPLATE, 144, 108),
        (61, 95, TEXT_SOURCE_MEMORY_FACT_SUMMARY, 360, 325),
        (96, 144, TEXT_SOURCE_NARRATION_TEMPLATE, 144, 95),
        (1, 24, TEXT_SOURCE_MEMORY_FACT_SUMMARY, 360, 336),
        (25, 144, TEXT_SOURCE_NARRATION_TEMPLATE, 144, 24),
        (1, 192, TEXT_SOURCE_NARRATION_TEMPLATE, 192, 0),
    ],
)
def test_window_and_hold_matches_the_reviewed_canonical_arithmetic(
    slot_start: int, slot_end: int, text_source: str, window: int, hold: int
) -> None:
    """Every canonical slot's window and hold, worked by hand and checked here."""
    assert window_and_hold(slot_start, slot_end, text_source) == (window, hold)


def test_window_and_hold_never_shrinks_a_slot() -> None:
    """window_frames is always >= the slot's own length."""
    window, hold = window_and_hold(10, 500, TEXT_SOURCE_NARRATION_TEMPLATE)
    length = 500 - 10 + 1
    assert window == length
    assert hold == 0


def test_window_and_hold_refuses_an_inverted_slot() -> None:
    """Window and hold refuses an inverted slot."""
    with pytest.raises(ValueError, match="empty or inverted"):
        window_and_hold(10, 5, TEXT_SOURCE_NARRATION_TEMPLATE)


def test_window_and_hold_accepts_a_single_frame_slot() -> None:
    """Window and hold accepts a single frame slot."""
    window, hold = window_and_hold(7, 7, TEXT_SOURCE_MEMORY_FACT_SUMMARY)
    assert window == 360
    assert hold == 359


def test_window_and_hold_never_returns_a_negative_hold() -> None:
    """Window and hold never returns a negative hold."""
    for length in range(1, 400):
        window, hold = window_and_hold(1, length, TEXT_SOURCE_NARRATION_TEMPLATE)
        assert hold >= 0
        assert window == length + hold
