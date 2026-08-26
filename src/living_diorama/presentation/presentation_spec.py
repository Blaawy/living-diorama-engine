"""Phase 27 presentation policy: the closed, reviewable capacity and hold rules.

An episode presentation plan decides one thing: for how many presentation
frames may the viewer see each locked semantic playback frame, so that every
narration unit's Phase 25 delivery slot receives sufficient deterministic
viewer-facing capacity? Nothing here reads a sentence, measures a voice, or
moves a slot. The policy is pure structure -- the slot's own length and the
unit's already-story-proven ``text_source`` classification -- and it carries
exactly two tunable constants, so the whole of it is the small set of rules
below and the arithmetic they name.

The policy identifier is part of this contract's schema version exactly as the
Phase 25 allocation policy is part of its own: changing how a window is sized,
or where a hold sits, changes what a plan of this version presents, so it is a
reviewed version change, never a quiet edit.

Two vocabulary decisions are deliberate. A **hold** is a single semantic frame
shown for more than one presentation frame -- never a run of frames dilated
together, which would be indistinguishable from uninterpolated slow motion of
real motion Phase 19 and Phase 23 already rendered at their own true rate. And
there is no rate, duration-in-seconds, or speech vocabulary anywhere: a window
is presentation frames, and whether a synthesized voice fits it is a later
layer's measured question, never this layer's guess.
"""

from typing import Final

PRESENTATION_PLAN_FORMAT: Final = "living_diorama_episode_presentation_plan"
"""The format tag every episode presentation plan declares."""

PRESENTATION_SCHEMA_VERSION: Final = 1
"""The presentation plan schema version this build reads and writes.

Independent from the narration, delivery, realization and persistence schema
versions. The window-sizing and hold policy in this module is part of this
version.
"""

PRESENTATION_POLICY_V1: Final = "presentation_policy_v1"
"""The one presentation policy this build derives and validates.

Declared in the document rather than merely implied, so a future plan written
under a revised policy can never be mistaken for this one. The validator
requires the field to equal this constant exactly.
"""

SEGMENT_ID_FORM: Final = "segment_%04d"
"""A segment identifier is positional and nothing else, so it is derivable.

A segment sits at the position of the maximal dwell run it tiles, in ascending
semantic-frame order. One index carries the whole tiling-accounting contract:
none missing, none repeated, none invented, none reordered.
"""

WINDOW_ID_FORM: Final = "window_%04d"
"""A window identifier is positional and nothing else, so it is derivable.

A record sits at the position of the narration unit -- and therefore the
delivery slot and the realization -- it presents. One index carries the whole
one-window-per-unit accounting contract.
"""

WINDOW_PRESENTATION_FRAMES_TEMPLATE: Final = 144
"""The reviewed window floor for a ``NARRATION_TEMPLATE`` unit: 6.0 seconds at
the pinned 24 fps.

A single-clause composed sentence, drawn from the closed, review-bounded
``EVENT_REALIZATION_TEMPLATES`` table. This value is a Director-reviewed
pacing judgment, sanity-checked against but never derived from measured voice
duration -- the architectural evidence that exposed the historical Phase 25
slots as infeasible for real speech is not this layer's timing authority.
"""

WINDOW_PRESENTATION_FRAMES_FACT: Final = 360
"""The reviewed window floor for a ``MEMORY_FACT_SUMMARY`` unit: 15.0 seconds
at the pinned 24 fps.

A compound restatement of a persisted memory fact, drawn from the closed
``FACT_REALIZATION_TEMPLATES`` table. Corroborating, not authoritative,
evidence: the only two canonical narration kinds ever classified
``MEMORY_FACT_SUMMARY`` -- ``DURABLE_CONSEQUENCE`` and
``CONSEQUENCE_PERSISTED`` -- are exactly the two canonical units whose real
measured speech most severely overflowed the historical Phase 25 slot.
"""

MAX_PRESENTATION_FRAME: Final = 1_000_000
"""This layer's own structural rail on a presentation coordinate, dwell or total.

Deliberately not a reuse of Phase 17's ``MAX_TIMELINE_FRAME``: that bound rails
a *semantic*-frame plausibility, and Phase 27 introduces a second, independent
clock with its own plausible range. At the pinned 24 fps this is roughly 11.6
hours of presentation time -- orders of magnitude above any real episode, and
small enough to refuse an absurd forgery outright.
"""

WINDOW_FRAMES_BY_TEXT_SOURCE: Final = {
    "NARRATION_TEMPLATE": WINDOW_PRESENTATION_FRAMES_TEMPLATE,
    "MEMORY_FACT_SUMMARY": WINDOW_PRESENTATION_FRAMES_FACT,
}
"""The closed, total map from a unit's story-proven wording family to its
window floor.

Keyed on the exact two ``TEXT_SOURCES`` string values Phase 24 already closes
and totals over every beat kind; restated here as string keys rather than
imported identifiers so this module carries no import of
``living_diorama.narration.narration_spec`` beyond what
:func:`window_frames_for_text_source` needs to validate membership. Emphasis
is deliberately not a weight here, exactly as Phase 25 refused to weight it a
second time: ``text_source`` has never been spent on a timing decision by any
layer before this one.
"""


def window_frames_for_text_source(text_source: str) -> int:
    """Return the reviewed window floor for one unit's wording family.

    Args:
        text_source: The unit's ``text_source`` field, already proven by
            upstream contracts to be one of the two closed values.

    Returns:
        The window floor in presentation frames.

    Raises:
        ValueError: If ``text_source`` is not one of the two closed values
            this policy classifies.
    """
    floor = WINDOW_FRAMES_BY_TEXT_SOURCE.get(text_source)
    if floor is None:
        raise ValueError(
            f"text_source {text_source!r} is not one of the closed wording families "
            f"{sorted(WINDOW_FRAMES_BY_TEXT_SOURCE)}; presentation capacity is total over "
            "exactly those two, never a free label"
        )
    return floor


def window_and_hold(slot_start: int, slot_end: int, text_source: str) -> tuple[int, int]:
    """Return the ``(window_frames, hold_frames)`` pair for one delivery slot.

    The whole capacity policy in one arithmetic step: a slot's window is the
    greater of its own semantic length and its wording family's reviewed
    floor, and every frame of the difference -- if any -- is held on the
    slot's own onset frame. No frame outside a slot's own span is ever held,
    and no slot frame other than its onset ever carries a hold: distributed
    dilation of moving footage is not this policy's mechanism.

    Args:
        slot_start: The delivery slot's first semantic frame, inclusive.
        slot_end: The delivery slot's final semantic frame, inclusive.
        text_source: The unit's story-proven wording family.

    Returns:
        ``(window_frames, hold_frames)``, both non-negative integers with
        ``window_frames == (slot_end - slot_start + 1) + hold_frames``.

    Raises:
        ValueError: If the slot is empty or inverted, or if ``text_source`` is
            not one of the two closed wording families.
    """
    if slot_end < slot_start:
        raise ValueError(f"delivery slot [{slot_start}, {slot_end}] is empty or inverted")
    length = slot_end - slot_start + 1
    floor = window_frames_for_text_source(text_source)
    window_frames = max(length, floor)
    return window_frames, window_frames - length
