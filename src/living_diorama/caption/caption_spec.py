"""Phase 32 caption policy: the one span law and its structural rail.

An episode caption plan decides exactly one new fact per narration unit: for
how many presentation frames its locked realized sentence is legible. Nothing
here reads a sentence's content, measures speech, or reads a sample -- the
policy is pure arithmetic over one already-proven interval: a unit's Phase 27
presentation window.

THE CAPTION PLAN MAKES LOCKED WORDING LEGIBLE ON THE PRESENTATION CLOCK. IT
REWORDS NOTHING.
"""

from typing import Final

CAPTION_PLAN_FORMAT: Final = "living_diorama_episode_caption_plan"
"""The format tag every episode caption plan declares."""

CAPTION_SCHEMA_VERSION: Final = 1
"""The caption plan schema version this build reads and writes."""

CAPTION_POLICY_V1: Final = "caption_policy_v1"
"""The one caption policy this build derives and validates.

Declared in the document rather than merely implied, so a plan written
under a revised policy can never be mistaken for this one.
"""

CAPTION_ID_FORM: Final = "caption_%04d"
"""A caption identifier is positional and nothing else, so it is derivable."""

MAX_CAPTION_FRAME: Final = 1_000_000
"""This layer's own structural rail on a caption cue's presentation frame.

Deliberately an independent literal, never computed at import time, for the
same reason ``MAX_PRESENTATION_FRAME`` is independent: standalone validation
of a caption plan document never opens a second document, so at that point
there is no proven presentation total to compare against. This is a
plausibility ceiling only, never timing authority -- the one authoritative
presentation total is recomputed, in the cross-check, from the actual
verified Phase 27 presentation total.

There is deliberately no ``MAX_CAPTION_TEXT_BYTES`` alongside it: Phase 26
owns realized wording validity and defines no downstream byte-length
restriction, and a rail here would let this layer reject a sentence Phase 26
itself considers valid. This layer does not own sentence length.
"""


def caption_frames_for_window(
    presentation_start_frame: int, presentation_end_frame: int
) -> tuple[int, int]:
    """Return the caption span for one unit's presentation window.

    The whole of ``caption_policy_v1``: under V1, a cue is legible for
    exactly its unit's presentation window, copied, never re-derived from a
    slot, a ``text_source`` floor, or a hold.

    Args:
        presentation_start_frame: The window's own start frame, 1-based.
        presentation_end_frame: The window's own end frame.

    Returns:
        ``(presentation_start_frame, presentation_end_frame)``, unchanged.

    Raises:
        TypeError: If either bound is not an exact ``int`` (``bool`` is
            refused because it subclasses ``int``).
        ValueError: If the start frame is not positive, if the end frame
            precedes the start frame, or if the end frame exceeds
            ``MAX_CAPTION_FRAME``.
    """
    if type(presentation_start_frame) is not int:
        got = type(presentation_start_frame).__name__
        raise TypeError(f"presentation_start_frame must be an int, got {got}")
    if type(presentation_end_frame) is not int:
        got = type(presentation_end_frame).__name__
        raise TypeError(f"presentation_end_frame must be an int, got {got}")
    if presentation_start_frame < 1:
        raise ValueError(f"presentation_start_frame must be >= 1, got {presentation_start_frame}")
    if presentation_end_frame < presentation_start_frame:
        raise ValueError(
            f"presentation_end_frame {presentation_end_frame} precedes "
            f"presentation_start_frame {presentation_start_frame}"
        )
    if presentation_end_frame > MAX_CAPTION_FRAME:
        raise ValueError(
            f"presentation_end_frame must be within [1, {MAX_CAPTION_FRAME}], got "
            f"{presentation_end_frame}"
        )
    return presentation_start_frame, presentation_end_frame


__all__ = [
    "CAPTION_ID_FORM",
    "CAPTION_PLAN_FORMAT",
    "CAPTION_POLICY_V1",
    "CAPTION_SCHEMA_VERSION",
    "MAX_CAPTION_FRAME",
    "caption_frames_for_window",
]
