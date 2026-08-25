"""Phase 25 delivery policy: the closed, reviewable slot-allocation rules.

A narration delivery plan decides one thing: when each already-written narration
unit may be delivered, as an inclusive span of playback frames on the locked
Phase 17 clock. Nothing here reads a sentence, weighs an emphasis, or moves a
shot. The policy is pure structure -- unit order, visibility, shot spans and the
clock -- and it carries zero tunable constants, so the whole of it is the small
set of rules below and the arithmetic they name.

The policy identifier is part of this contract's schema version exactly as the
Phase 24 wording table is part of its own: changing how a slot is derived
changes what a plan of this version schedules, so it is a reviewed version
change, never a quiet edit.

Two vocabulary decisions are deliberate. ``playback`` here is presentation
arithmetic on the shared clock -- which frames a viewer is ever shown -- not a
claim on Phase 23's execution vocabulary; the witness boundary frame is
excluded for the same reason Phase 23 never emits it. And there is no rate,
duration-in-seconds, or speech vocabulary anywhere: a slot is frames, and
whether a synthesized voice fits those frames is a later layer's measured
question, never this layer's guess.
"""

from typing import Final

DELIVERY_PLAN_FORMAT: Final = "living_diorama_episode_narration_delivery_plan"
"""The format tag every episode narration delivery plan declares."""

DELIVERY_SCHEMA_VERSION: Final = 1
"""The delivery plan schema version this build reads and writes.

Independent from the narration, cinematic, render and persistence schema
versions. The allocation policy in this module is part of this version.
"""

DELIVERY_POLICY_V1: Final = "narration_delivery_policy_v1"
"""The one allocation policy this build derives and validates.

Declared in the document rather than merely implied, so a future plan written
under a revised policy can never be mistaken for this one. The validator
requires the field to equal this constant exactly.
"""

PLACEMENT_SHOT_ANCHORED: Final = "SHOT_ANCHORED"
"""A slot derived from the exact shot Phase 22 used to frame the unit's beat.

The unit is SHOWN, its citing shot's playback segment hosts it, and its slot
lies entirely inside that segment: narration about a beat is scheduled only
while that beat's own footage is on screen.
"""

PLACEMENT_ALLOCATED_UNSHOWN: Final = "ALLOCATED_UNSHOWN"
"""A slot allocated to a unit whose beat no approved camera framed.

The unit stays UNSHOWN in the narration plan -- this layer never changes
visibility, and the Phase 24 wording ban already makes a sentence unable to
claim the viewer saw anything. What is allocated here is presentation time
only: a span of playback frames in which the words may be delivered.
"""

PLACEMENT_CLASSES: Final = (PLACEMENT_ALLOCATED_UNSHOWN, PLACEMENT_SHOT_ANCHORED)
"""Exactly the two ways a V1 delivery slot may come to exist."""

DELIVERY_ID_FORM: Final = "delivery_%04d"
"""A delivery identifier is positional and nothing else, so it is derivable.

A record sits at the position of the narration unit it schedules, which is the
position of the beat that unit restates. One index carries the whole
one-slot-per-unit accounting contract: none missing, none repeated, none
invented, none reordered.
"""

MIN_SLOT_FRAMES: Final = 1
"""The structural floor on a slot: it exists, or it is refused.

Deliberately not a speech-plausibility minimum. Any larger floor would smuggle
a speaking-rate opinion into a layer that owns none; whether one frame is
enough time to say anything is a question for the later voice layer's measured
fit validation, not for this one's arithmetic.
"""


def playback_domain(start_frame: int, end_frame: int) -> tuple[int, int]:
    """Return the inclusive playback span of a timeline, excluding the witness.

    Phase 17 declares its timeline as ``start_frame`` plus three phase lengths
    closing on ``end_frame``, and Phase 22's shots tile every frame of it --
    including the terminal boundary frame, which Phase 23 renders once as a
    closure witness and never plays back. Presentation time is playback time,
    so delivery slots live in ``[start_frame, end_frame - 1]`` and the witness
    frame can never carry narration. This is a derivation of the presentation
    domain, not a repair of any input.

    Args:
        start_frame: The timeline's first frame.
        end_frame: The timeline's terminal boundary frame.

    Returns:
        The inclusive ``(first, final)`` playback frame pair.

    Raises:
        ValueError: If the domain would be empty, which means the timeline has
            no playback frame to schedule anything on.
    """
    final = end_frame - 1
    if final < start_frame:
        raise ValueError(
            f"timeline runs from frame {start_frame} to boundary {end_frame}, leaving no "
            "playback frame; a delivery plan schedules presentation time and there is none"
        )
    return start_frame, final


def partition_equally(first: int, last: int, claimants: int) -> list[tuple[int, int]]:
    """Split an inclusive frame span into contiguous equal slots, in order.

    Every claimant receives at least ``MIN_SLOT_FRAMES``; the remainder after
    floor division goes one frame each to the earliest claimants. With equal
    weights this is exactly the shape of Phase 22's largest-remainder
    allocation -- every fractional part ties, so the index breaks the tie --
    restated here as this layer's own arithmetic rather than a reach into the
    shot planner's private helper. The slices tile the span exactly: no frame
    is dropped, none is counted twice, and order is preserved.

    Args:
        first: The span's first frame, inclusive.
        last: The span's final frame, inclusive.
        claimants: How many slots to cut the span into.

    Returns:
        One inclusive ``(start, end)`` pair per claimant, in claimant order.

    Raises:
        ValueError: If there are no claimants, the span is empty or inverted,
            or the span holds fewer frames than claimants -- a slot below the
            structural floor is refused, never shrunk to fit.
    """
    if claimants < 1:
        raise ValueError(f"cannot partition frames [{first}, {last}] among {claimants} claimants")
    length = last - first + 1
    if length < 1:
        raise ValueError(
            f"cannot partition empty frame span [{first}, {last}]; a slot is at least "
            f"{MIN_SLOT_FRAMES} frame"
        )
    if length < claimants * MIN_SLOT_FRAMES:
        raise ValueError(
            f"cannot fit {claimants} delivery slots of at least {MIN_SLOT_FRAMES} frame "
            f"into the {length} frames of [{first}, {last}]"
        )
    base = length // claimants
    extra = length % claimants
    slots: list[tuple[int, int]] = []
    cursor = first
    for index in range(claimants):
        size = base + (1 if index < extra else 0)
        slots.append((cursor, cursor + size - 1))
        cursor += size
    return slots
