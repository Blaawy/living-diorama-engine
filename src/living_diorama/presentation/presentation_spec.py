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

The V2 presentation profile adds a second, additive reading of the same hold:
instead of repeating the onset frame's PNG for every held position, the
mapping may ping-pong across the unit's own slot span, showing already-rendered
frames in their true temporal order. The capacity arithmetic, the window
geometry and the segment shape are unchanged -- only the per-position choice
inside a hold differs, and the pure functions at the bottom of this module are
the whole of that choice. They read no clock and draw no randomness.
"""

from typing import Final

PRESENTATION_PLAN_FORMAT: Final = "living_diorama_episode_presentation_plan"
"""The format tag every episode presentation plan declares."""

PRESENTATION_SCHEMA_VERSION: Final = 1
"""The presentation plan schema version this build reads and writes.

Independent from the narration, delivery, realization and persistence schema
versions. The window-sizing and hold policy in this module is part of this
version. V2 plans stay on this same version: a V2 plan is the V1 document plus
one additive top-level ``motion_windows`` block, exactly the strict-superset
pattern the cinematic V2 schema already uses, and a plan without that block is
validated by the unchanged V1 path.
"""

PRESENTATION_POLICY_V1: Final = "presentation_policy_v1"
"""The one presentation policy this build derives and validates.

Declared in the document rather than merely implied, so a future plan written
under a revised policy can never be mistaken for this one. The validator
requires the field to equal this constant exactly. The V2 profile keeps the
same policy identity: it changes how a hold's already-scheduled capacity is
mapped onto rendered frames, never how that capacity is sized.
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


def bounce_window(lo: int, hi: int, length: int) -> tuple[int, ...]:
    """Return the first ``length`` values of the infinite bounce over ``[lo, hi]``.

    The bounce is the standard forward-then-backward oscillation
    ``lo, lo + 1, ..., hi, hi - 1, ..., lo, lo + 1, ...`` -- a triangle wave of
    period ``2 * (hi - lo)``. It is pure arithmetic over its three integer
    arguments: no randomness, no wall clock, no state, and the same arguments
    always produce the same tuple, so a plan that names a bounce names one
    concrete sequence forever.

    Consecutive values differ by exactly one everywhere, so no two adjacent
    held positions ever repeat a PNG under the V2 mapping.

    Args:
        lo: The window's first semantic frame, inclusive.
        hi: The window's final semantic frame, inclusive, with ``hi > lo``.
        length: How many values to take, a positive integer.

    Returns:
        A tuple of exactly ``length`` integers, each within ``[lo, hi]``.

    Raises:
        ValueError: If the window is empty, inverted, or a single frame (a
            one-frame window is not a bounce and would freeze), or if
            ``length`` is not positive.
    """
    if hi <= lo:
        raise ValueError(
            f"bounce window [{lo}, {hi}] must span at least two semantic frames; a "
            "one-frame window cannot bounce and is refused rather than frozen"
        )
    if length < 1:
        raise ValueError(f"bounce length must be positive, got {length}")
    span = hi - lo
    period = 2 * span
    return tuple(
        lo + (step if step <= span else period - step)
        for step in (index % period for index in range(length))
    )


def motion_window_for_hold(onset: int, slot_end: int, length: int) -> tuple[int, ...]:
    """Return the V2 ping-pong sequence for one hold, within the unit's own slot.

    The safe local window is the holding unit's own delivery slot
    ``[onset, slot_end]`` -- never a frame of a neighbouring unit's slot and
    never a frame of a different animation phase. This function chooses, from
    the largest prefix of that slot, the bounce whose final value lands closest
    to the onset, so the hold re-enters the natural footage flow without a
    visible jump; the first held value is always the onset itself (the shot's
    cut and the voice onset), because requirement three -- continuity *into*
    the hold -- is the binding one, and the exit is then brought as close to
    the onset as the pure bounce allows rather than ever breaking the
    deterministic triangle shape with a hand-edited tail.

    The choice is made once here and documented once: entry continuity wins,
    exit continuity is approximated to within one frame where the slot permits
    it (``exit in {onset, onset + 1}``), and the pure, deterministic bounce is
    never mutated. A slot that offers only its onset frame offers no safe
    motion, and this function says so honestly by refusing rather than by
    freezing a fake bounce.

    Args:
        onset: The hold's semantic onset frame -- the slot's own ``start_frame``.
        slot_end: The holding unit's slot's final semantic frame, inclusive.
        length: The hold's dwell in presentation frames (its required length).

    Returns:
        Exactly ``length`` semantic indices: the canonical bounce over
        ``[onset, onset + span]`` for the chosen span.

    Raises:
        ValueError: If the slot offers fewer than two frames of safe motion, or
            if ``length`` is not positive.
    """
    if slot_end < onset:
        raise ValueError(f"delivery slot [{onset}, {slot_end}] is empty or inverted")
    max_span = slot_end - onset
    if max_span < 1:
        raise ValueError(
            f"slot [{onset}, {slot_end}] offers no second frame of safe motion; "
            "no V2 ping-pong window exists, and motion is not forced where none is safe"
        )
    if length < 1:
        raise ValueError(f"hold length must be positive, got {length}")
    best_span = max_span
    best_gap: int | None = None
    for span in range(max_span, 0, -1):
        period = 2 * span
        remainder = (length - 1) % period
        gap = remainder if remainder <= span else period - remainder
        if best_gap is None or gap < best_gap:
            best_gap = gap
            best_span = span
            if gap == 0:
                break
    return bounce_window(onset, onset + best_span, length)
