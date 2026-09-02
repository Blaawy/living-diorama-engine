"""Deriving an Episode Presentation Plan from a delivery, a narration and a realization.

The derivation is a pure function of its inputs. It reads no clock, draws no
randomness, consults no filesystem path, calls no model, opens no socket, and
depends on no iteration order that Python is free to vary. The same three
documents always produce the same bytes.

What it decides is how many presentation frames the viewer sees each locked
semantic playback frame for, and only from structure: each unit's already
story-proven ``text_source`` classification and the length of the delivery
slot the unit already owns (V1 and V2), or, under the V3 profile, the unit's
own realized text length plus the same slot length. What it never decides is
what is said, when in *semantic* time a unit belongs, or what mattered. For
V1 and V2, wording stays in the realization plan and is never read here --
not carried, not measured, not counted; only its identity and position are
named. V3 is the one reviewed exception to that ban: it reads a unit's
``realized_text`` only to count its whitespace-separated tokens, feeding the
per-unit content-sized window floor the Director's absolute no-reverse-time
rule requires. The delivery plan's slots are never moved, resized or re-cut
-- only imaged onto a second, longer clock.

This module performs the same lightweight join every upstream planner
performs: it proves the three documents it receives actually name each other,
so a delivery plan and a realization plan built for different narration
documents can never be joined into one presentation plan. It does **not**
re-run the deep source-verification gates that prove the delivery plan's slots
are true of a narration and a shot plan, or that the realization plan's
sentences are true of a narration, a story and an export -- those two locked
gates are
:func:`living_diorama.narration_delivery.delivery_cross_check.validate_narration_delivery_plan_against_sources`
and
:func:`living_diorama.language_realization.realization_cross_check.validate_language_realization_plan_against_sources`,
and this presentation layer's own cross-check runs both, in full, before this
planner's derivation may be trusted with any upstream timing or classification
truth. A caller that skips those two gates and calls this planner directly
gets a plan that is only as trustworthy as the documents it was handed.

Four presentation profiles are derived here. ``presentation_profile="v1"``
(default) reproduces today's exact hold behavior byte for byte: every extra
presentation position of a hold repeats the onset frame's identity.
``presentation_profile="v2"`` derives the identical geometry -- same windows,
same segments, same dwells, same total -- and additionally names, per held
position, the already-rendered semantic frame to show: a deterministic
ping-pong across the unit's own slot span (see ``motion_window_for_hold`` in
``presentation_spec``). Nothing is re-rendered, and nothing outside a unit's
own slot is ever shown: V2 changes only which locked, already-rendered frame a
held position displays. ``presentation_profile="v3"`` replaces the fixed
per-text-source window floors with a per-unit content-sized floor derived from
the unit's own realized text (see :func:`_content_sized_window_and_hold`) and
never emits ``motion_windows`` at all: every hold is the unchanged V1 frozen
repeat of the onset frame -- a constant-value run, trivially non-decreasing,
so presentation time never runs backward anywhere under V3, the Director's
absolute rule. ``presentation_profile="v4"`` is the additive strict 1:1
profile: a unit's window is exactly its delivery slot's own length,
``hold_frames`` is always 0 and every ``dwell_frames`` is 1, so presentation
frame N shows rendered frame N and ``presentation_frames_total`` equals the
rendered playback count. V4 never stretches, holds, bounces or repeats, and
refuses loudly when a unit's realized narration cannot fit its own slot (see
:func:`_v4_require_content_fits_slot`) rather than papering over a world that
is too short for the story.
"""

import math
from typing import Final, cast

from living_diorama.language_realization.realization_schema_v1 import (
    validate_episode_language_realization_plan,
)
from living_diorama.language_realization.realization_spec import REALIZATION_ID_FORM
from living_diorama.narration.narration_schema_v1 import (
    UNIT_ID_FORM,
    validate_episode_narration_plan,
)
from living_diorama.narration_delivery.delivery_schema_v1 import (
    DELIVERY_TIMELINE_KEYS,
    validate_episode_narration_delivery_plan,
)
from living_diorama.narration_delivery.delivery_spec import playback_domain
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation.presentation_schema_v1 import (
    JsonValue,
    validate_episode_presentation_plan,
)
from living_diorama.presentation.presentation_schema_v2 import (
    validate_episode_presentation_plan_v2,
)
from living_diorama.presentation.presentation_spec import (
    PRESENTATION_PLAN_FORMAT,
    PRESENTATION_POLICY_V1,
    PRESENTATION_SCHEMA_VERSION,
    SEGMENT_ID_FORM,
    WINDOW_ID_FORM,
    motion_window_for_hold,
    window_and_hold,
)

__all__ = [
    "build_episode_presentation_plan_bytes",
    "build_episode_presentation_plan_document",
]

_PRESENTATION_TIMELINE_KEYS_MATCH_DELIVERY: Final = DELIVERY_TIMELINE_KEYS
"""Restated for the drift test only -- the planner still declares its own keys.

``presentation_schema_v1.PRESENTATION_TIMELINE_KEYS`` is this contract's own
frozenset, restated key-for-key rather than imported; this module borrows the
delivery plan's key set only long enough to copy the eight values across.
"""

_PRESENTATION_PROFILES: Final = ("v1", "v2", "v3", "v4")
"""The closed set of presentation profiles this build derives."""

V3_FRAMES_PER_WORD: Final = 12
"""The V3 per-word speech allowance: 12 presentation frames per word.

At the pinned 24 fps that is 0.5 s per word, i.e. 2.0 words per second. The
commander-chosen rate, deliberately slower than every real measured EP1 Kokoro
rate (2.70, 3.46 and 2.94 words/sec for the three real lines), so a V3 window
always contains the real speech it must present with headroom. Calibrated, not
guessed; do not change without the commander. V4's overflow refusal reuses the
same rate on the unit's real realized text: the closest real quantity this
layer may read.
"""

V3_COMPREHENSION_BUFFER_FRAMES: Final = 18
"""The V3 fixed comprehension buffer: 18 presentation frames, 0.75 s at 24 fps.

Added to every unit's content-sized window floor after the speech estimate, so
a unit whose speech exactly fills its estimate still keeps a beat of breathing
room before the next unit's slot begins. V4's refusal does not add this
buffer: it compares the speech allowance itself, the "speech length in
presentation frames" the no-stretch rule must refuse on.
"""

V4_OVERHEAD_FRAMES: Final = 24
"""The V4 fixed speech lead-in/trail overhead: 24 presentation frames (1.0 s at 24 fps).

V4's overflow refusal sizes a unit's speech allowance with the reviewed
affine model ``V4_OVERHEAD_FRAMES + V4_FRAMES_PER_WORD * words``, because a
pure per-word constant cannot fit the real measured Kokoro speech for the real
EP1 realized text. The three Director-measured points, in presentation
frame-equivalents (measured samples / 1000):

* unit_0001 ``"We changed one rule."`` -- 4 words, 44.4 frames (11.10 fr/word);
* unit_0002 ``"We built the wall between this side ..."`` -- 15 words,
  111.0 frames (7.40 fr/word);
* unit_0003 ``"The wall between this side ... changed."`` -- 10 words,
  81.6 frames (8.16 fr/word).

Every line carries a fixed lead-in/trail overhead, so a short utterance costs
far more per word than a long one -- the per-word cost falls from 11.10 to
7.40 fr/word across these three lines -- and a pure frames-per-word constant
cannot fit both ends: at the old 12 frames/word the estimate over-shoots the
long lines by ~1.6x (180 vs a real 111). The least-squares affine fit over
the three points is ``frames = 20.4 + 6.06 * words``, predicting
44.6 / 111.3 / 81.0 against the real 44.4 / 111.0 / 81.6 (residuals
+0.2 / +0.3 / -0.6). Rounded up with margin, the reviewed model is
``24 + 6 * words``, predicting 48 / 114 / 84 against the real
44.4 / 111.0 / 81.6 -- an over-estimate of 1.03x to 1.08x.

The estimate must OVER-estimate real speech: this gate refuses a unit whose
speech allowance exceeds its delivery slot, and V4 never stretches, so an
under-estimate would let a too-long utterance through as silent dead-air
corruption. The margin can be modest because the downstream audio-track layer
independently verifies the real speech fits its window and refuses loudly
otherwise (``voice_execution`` publishes nothing for an episode holding an
unfit unit) -- so an under-estimate surfaces as a loud build error, never
silent corruption.
"""

V4_FRAMES_PER_WORD: Final = 6
"""The V4 per-word speech slope: 6 presentation frames per word after the overhead.

The affine slope of the reviewed V4 speech model. See
:data:`V4_OVERHEAD_FRAMES` for the three real measured EP1 points, the
least-squares fit (``20.4 + 6.06 * words``) and why a pure per-word constant
cannot fit both ends of the measured range. Paired with
:data:`V4_OVERHEAD_FRAMES` the reviewed model always over-estimates the real
measured speech (48 > 44.4, 114 > 111.0, 84 > 81.6); the margin is modest by
design, because the downstream audio-track layer independently verifies the
real speech fits its window and refuses loudly, so an under-estimate can
never become silent corruption.
"""


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def _require_join(
    delivery: dict[str, JsonValue],
    narration: dict[str, JsonValue],
    realization: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Prove the three documents present one directed, narrated, realized episode.

    Digest equality is the load-bearing check, in both directions: the
    delivery plan and the realization plan each already recorded which
    narration plan they were built from, so a presentation layer never has to
    decide whether three files "look like" the same episode. It asks each
    document what it bound and compares against the narration plan actually
    offered -- the same document offered to both, which is what proves
    delivery and realization share one narration lineage rather than merely
    each claiming a plausible one.

    Raises:
        ValueError: If any binding or identity does not hold.
    """
    delivery_source = _document(delivery["source"], "narration delivery plan source")
    narration_source = _document(narration["source"], "episode narration plan source")
    realization_source = _document(realization["source"], "language realization plan source")

    delivery_digest = sha256_hex(dumps_canonical(delivery, "narration delivery plan"))
    narration_digest = sha256_hex(dumps_canonical(narration, "episode narration plan"))
    realization_digest = sha256_hex(dumps_canonical(realization, "language realization plan"))

    if delivery_source["narration_plan_sha256"] != narration_digest:
        raise ValueError(
            f"the narration delivery plan schedules narration "
            f"{delivery_source['narration_plan_sha256']}, but the offered narration plan "
            f"hashes to {narration_digest}; the delivery plan and the narration plan are "
            "not the same episode's"
        )
    if realization_source["narration_plan_sha256"] != narration_digest:
        raise ValueError(
            f"the language realization plan realizes narration "
            f"{realization_source['narration_plan_sha256']}, but the offered narration "
            f"plan hashes to {narration_digest}; the realization plan and the narration "
            "plan are not the same episode's"
        )

    for other_label, other_source in (
        ("narration delivery plan", delivery_source),
        ("language realization plan", realization_source),
    ):
        for field in ("mode", "episode", "previous_episode"):
            if other_source[field] != narration_source[field]:
                raise ValueError(
                    f"the {other_label} declares {field} {other_source[field]!r}, but the "
                    f"narration plan it presents declares {narration_source[field]!r}"
                )

    return {
        "delivery_plan_sha256": delivery_digest,
        "delivery_schema_version": delivery["schema_version"],
        "episode": narration_source["episode"],
        "mode": narration_source["mode"],
        "motion_time_sha256": delivery_source["motion_time_sha256"],
        "narration_plan_sha256": narration_digest,
        "narration_schema_version": narration["schema_version"],
        "previous_episode": narration_source["previous_episode"],
        "realization_plan_sha256": realization_digest,
        "realization_schema_version": realization["schema_version"],
    }


def _content_sized_window_and_hold(
    slot_start: int, slot_end: int, realized_text: str
) -> tuple[int, int]:
    """Return the V3 ``(window_frames, hold_frames)`` pair for one delivery slot.

    The V3 content-sized floor replaces the fixed per-text-source floors
    (:data:`presentation_spec.WINDOW_PRESENTATION_FRAMES_TEMPLATE` and
    :data:`presentation_spec.WINDOW_PRESENTATION_FRAMES_FACT`) with a per-unit
    floor derived from the unit's own realized text: its whitespace-separated
    token count at a commander-chosen 2.0 words/sec (12 frames per word), plus
    a fixed 0.75 s comprehension buffer (18 frames), plus the slot's own
    semantic length. The window is the greater of the slot length and that
    floor; because the floor already contains the slot length, the window
    always resolves to the floor -- the ``max`` is kept for defensive symmetry
    with :func:`window_and_hold`'s formula shape. The hold is every frame of
    the difference, on the slot's own onset frame, filled by the unchanged V1
    frozen repeat -- a constant-value run, trivially non-decreasing, so V3
    never reverses presentation time by construction.

    Args:
        slot_start: The delivery slot's first semantic frame, inclusive.
        slot_end: The delivery slot's final semantic frame, inclusive.
        realized_text: The unit's already-validated realized sentence. Only its
            whitespace-separated token count is read -- length, never content.

    Returns:
        ``(window_frames, hold_frames)``, both non-negative integers with
        ``window_frames == (slot_end - slot_start + 1) + hold_frames``.

    Raises:
        ValueError: If the slot is empty or inverted.
    """
    if slot_end < slot_start:
        raise ValueError(f"delivery slot [{slot_start}, {slot_end}] is empty or inverted")
    length = slot_end - slot_start + 1
    word_count = len(realized_text.split())
    content_estimate_frames = math.ceil(word_count * V3_FRAMES_PER_WORD)
    floor = length + content_estimate_frames + V3_COMPREHENSION_BUFFER_FRAMES
    window_frames = max(length, floor)
    return window_frames, window_frames - length


def _v4_identity_window_and_hold(slot_start: int, slot_end: int) -> tuple[int, int]:
    """Return the V4 ``(window_frames, hold_frames)`` pair for one delivery slot.

    V4 is the strict 1:1 presentation profile: a unit's window is exactly its
    delivery slot's own inclusive length, and there is never a hold, so every
    dwell is 1 and presentation frame N shows rendered frame N. No per-text-
    source floor, no content-sized floor, no bounce and no ``motion_windows``
    key exist under V4; the plan simply is the rendered timeline.

    Args:
        slot_start: The delivery slot's first semantic frame, inclusive.
        slot_end: The delivery slot's final semantic frame, inclusive.

    Returns:
        ``(window_frames, hold_frames)`` with ``window_frames`` equal to the
        slot's own length and ``hold_frames`` always 0.

    Raises:
        ValueError: If the slot is empty or inverted.
    """
    if slot_end < slot_start:
        raise ValueError(f"delivery slot [{slot_start}, {slot_end}] is empty or inverted")
    return slot_end - slot_start + 1, 0


def _v4_require_content_fits_slot(
    unit_id: str, slot_start: int, slot_end: int, realized_text: str
) -> None:
    """Refuse a V4 unit whose realized narration cannot fit its own delivery slot.

    V4 never stretches, holds or repeats, so a unit whose content need exceeds
    its slot is a loud build failure, never a papered-over freeze. The content
    need is the unit's real realized sentence read at the calibrated affine
    speech model -- a fixed lead-in/trail overhead
    (:data:`V4_OVERHEAD_FRAMES`) plus a per-word slope
    (:data:`V4_FRAMES_PER_WORD`) -- the closest real quantity this layer may
    read; a measured voice duration exists only downstream in the voice layer
    and is not available here. The available quantity is the delivery plan's
    own inclusive slot span, exactly as V1-V3 read it.

    Args:
        unit_id: The narration unit's own identifier.
        slot_start: The delivery slot's first semantic frame, inclusive.
        slot_end: The delivery slot's final semantic frame, inclusive.
        realized_text: The unit's already-validated realized sentence; only
            its whitespace-separated token count is read.

    Raises:
        ValueError: If the unit's content need exceeds its slot, naming the
            unit, its required frames, its available slot frames and the
            shortfall.
    """
    if slot_end < slot_start:
        raise ValueError(f"delivery slot [{slot_start}, {slot_end}] is empty or inverted")
    slot_frames = slot_end - slot_start + 1
    required_frames = V4_OVERHEAD_FRAMES + len(realized_text.split()) * V4_FRAMES_PER_WORD
    if required_frames > slot_frames:
        shortfall = required_frames - slot_frames
        raise ValueError(
            f"presentation_profile v4 refuses to stretch: unit {unit_id!r} requires "
            f"{required_frames} presentation frames for its realized narration, but its "
            f"delivery slot [{slot_start}, {slot_end}] offers only {slot_frames}; "
            f"shortfall {shortfall} frames -- the rendered world is too short for this "
            "unit, and v4 presents a strict 1:1 mapping rather than holding or freezing"
        )


def build_episode_presentation_plan_document(
    delivery_plan: object,
    narration_plan: object,
    realization_plan: object,
    *,
    presentation_profile: str = "v1",
) -> dict[str, JsonValue]:
    """Return the Episode Presentation Plan document for one directed episode.

    Args:
        delivery_plan: The Episode Narration Delivery Plan V1 whose slots this
            plan images onto the presentation clock.
        narration_plan: The Episode Narration Plan V1 whose units are
            presented, and whose ``text_source`` classification selects each
            unit's window floor under V1 and V2.
        realization_plan: The Episode Language Realization Plan V1 whose
            sentences this plan's windows name by identity, never by content
            -- except under V3 and V4, whose per-unit fit checks count the
            whitespace tokens of each ``realized_text``.
        presentation_profile: ``"v1"`` (default) derives today's exact plan --
            every extra position of a hold repeats the onset frame's identity.
            ``"v2"`` derives the identical geometry plus the additive
            ``motion_windows`` block naming one already-rendered semantic frame
            per held position (see :func:`motion_window_for_hold`). ``"v3"``
            sizes each window from the unit's own realized text and never
            emits ``motion_windows``; its holds are frozen repeats of the onset
            frame (see :func:`_content_sized_window_and_hold`). ``"v4"``
            presents the rendered timeline strictly 1:1 -- window equals slot,
            hold 0, dwell 1 -- and refuses loudly when a unit's realized
            narration cannot fit its own slot (see
            :func:`_v4_require_content_fits_slot`).

    Returns:
        A validated Episode Presentation Plan document: V1 under the default
        profile, V2 under ``"v2"``, and the plain V1 shape under ``"v3"`` and
        ``"v4"`` (a V3 or V4 plan carries no ``motion_windows`` key, so it
        validates under the unchanged V1 validator).

    Raises:
        TypeError: If any input has the wrong shape.
        ValueError: If any input fails its own contract, if the three do not
            join, if the unit and slot counts disagree, if
            ``presentation_profile`` is not one of the closed profiles, if
            a V2 hold's slot offers no safe motion, or if a V4 unit's realized
            narration exceeds its delivery slot.
    """
    if presentation_profile not in _PRESENTATION_PROFILES:
        raise ValueError(
            f"presentation_profile {presentation_profile!r} is not one of the closed "
            f"profiles {list(_PRESENTATION_PROFILES)}"
        )
    delivery = validate_episode_narration_delivery_plan(delivery_plan)
    narration = validate_episode_narration_plan(narration_plan)
    realization = validate_episode_language_realization_plan(realization_plan)

    source = _require_join(delivery, narration, realization)

    units = cast(list[dict[str, JsonValue]], narration["units"])
    deliveries = cast(list[dict[str, JsonValue]], delivery["deliveries"])
    realizations = cast(list[dict[str, JsonValue]], realization["realizations"])
    if not (len(units) == len(deliveries) == len(realizations)):
        raise ValueError(
            f"the narration plan holds {len(units)} units, the delivery plan schedules "
            f"{len(deliveries)}, and the realization plan realizes {len(realizations)}; "
            "every unit is presented exactly once"
        )

    timeline = dict(_document(delivery["timeline"], "narration delivery plan timeline"))
    playback_first, playback_final = playback_domain(
        cast(int, timeline["start_frame"]), cast(int, timeline["end_frame"])
    )

    # One hold value per semantic playback frame, keyed by the frame number.
    # A slot's own onset frame is the only frame that may ever carry a hold --
    # every other playback frame's dwell is exactly 1. Under the V2 profile
    # each hold additionally names the ping-pong sequence that selects which
    # already-rendered frame each held position shows; under V1 and V3 every
    # held position repeats the onset frame itself (the frozen repeat), so a
    # V3 hold is a constant-value run and can never run time backward. Under
    # V4 no unit ever holds, so ``holds_by_frame`` stays empty and every dwell
    # is exactly 1.
    holds_by_frame: dict[int, int] = {}
    windows_geometry: list[tuple[int, int, int]] = []  # (unit index, slot_start, window_frames)
    motion_windows: list[JsonValue] = []
    for position, (unit, record) in enumerate(zip(units, deliveries, strict=True)):
        if record["unit_id"] != unit["unit_id"]:
            raise ValueError(
                f"narration delivery plan deliveries[{position}] schedules unit "
                f"{record['unit_id']!r}, but the narration plan holds "
                f"{unit['unit_id']!r} at that position; presentation follows the "
                "narration plan's own order"
            )
        slot_start = cast(int, record["start_frame"])
        slot_end = cast(int, record["end_frame"])
        text_source = cast(str, unit["text_source"])
        if presentation_profile == "v3":
            window_frames, hold_frames = _content_sized_window_and_hold(
                slot_start,
                slot_end,
                cast(str, realizations[position]["realized_text"]),
            )
        elif presentation_profile == "v4":
            window_frames, hold_frames = _v4_identity_window_and_hold(slot_start, slot_end)
            _v4_require_content_fits_slot(
                cast(str, unit["unit_id"]),
                slot_start,
                slot_end,
                cast(str, realizations[position]["realized_text"]),
            )
        else:
            window_frames, hold_frames = window_and_hold(slot_start, slot_end, text_source)
        if hold_frames > 0:
            holds_by_frame[slot_start] = hold_frames
            if presentation_profile == "v2":
                motion_windows.append(
                    {
                        "onset_frame": slot_start,
                        "semantic_frames": list(
                            motion_window_for_hold(slot_start, slot_end, 1 + hold_frames)
                        ),
                        "window_id": WINDOW_ID_FORM % (position + 1),
                    }
                )
        windows_geometry.append((position, slot_start, window_frames))

    # Build the dwell-run segments left to right over the playback domain, and
    # the presentation-frame prefix sum needed to image both segments and
    # windows onto the presentation clock in one pass.
    segments: list[JsonValue] = []
    presentation_start_of: dict[int, int] = {}
    presentation_end_of: dict[int, int] = {}
    presentation_cursor = 1
    semantic_cursor = playback_first
    while semantic_cursor <= playback_final:
        dwell = 1 + holds_by_frame.get(semantic_cursor, 0)
        run_start = semantic_cursor
        # A held frame is always alone in its run: its own dwell already
        # differs from the frame immediately before and after it, since every
        # other playback frame's dwell is 1 and a hold is strictly positive.
        run_end = semantic_cursor
        if dwell == 1:
            while run_end + 1 <= playback_final and holds_by_frame.get(run_end + 1, 0) == 0:
                run_end += 1
        length = run_end - run_start + 1
        span = length * dwell
        presentation_end = presentation_cursor + span - 1
        for frame in range(run_start, run_end + 1):
            offset = frame - run_start
            presentation_start_of[frame] = presentation_cursor + offset * dwell
            presentation_end_of[frame] = presentation_start_of[frame] + dwell - 1
        segments.append(
            {
                "dwell_frames": dwell,
                "presentation_end_frame": presentation_end,
                "presentation_start_frame": presentation_cursor,
                "segment_id": SEGMENT_ID_FORM % (len(segments) + 1),
                "semantic_end_frame": run_end,
                "semantic_start_frame": run_start,
            }
        )
        presentation_cursor = presentation_end + 1
        semantic_cursor = run_end + 1
    presentation_frames_total = presentation_cursor - 1

    windows: list[JsonValue] = []
    for position, slot_start, window_frames in windows_geometry:
        start = presentation_start_of[slot_start]
        end = start + window_frames - 1
        windows.append(
            {
                "presentation_end_frame": end,
                "presentation_start_frame": start,
                "realization_id": realizations[position]["realization_id"],
                "unit_id": units[position]["unit_id"],
                "window_id": WINDOW_ID_FORM % (position + 1),
            }
        )
        expected_unit = UNIT_ID_FORM % (position + 1)
        expected_realization = REALIZATION_ID_FORM % (position + 1)
        if units[position]["unit_id"] != expected_unit:
            raise ValueError(
                f"episode narration plan units[{position}] carries id "
                f"{units[position]['unit_id']!r}, not the positional {expected_unit!r}"
            )
        if realizations[position]["unit_id"] != expected_unit:
            raise ValueError(
                f"language realization plan realizations[{position}] presents unit "
                f"{realizations[position]['unit_id']!r}, but the narration plan holds "
                f"{expected_unit!r} at that position"
            )
        if realizations[position]["realization_id"] != expected_realization:
            raise ValueError(
                f"language realization plan realizations[{position}] carries id "
                f"{realizations[position]['realization_id']!r}, not the positional "
                f"{expected_realization!r}"
            )

    document: dict[str, JsonValue] = {
        "accounting": {
            "presentation_frames_total": presentation_frames_total,
            "segments_total": len(segments),
            "windows_total": len(windows),
        },
        "format": PRESENTATION_PLAN_FORMAT,
        "policy": PRESENTATION_POLICY_V1,
        "schema_version": PRESENTATION_SCHEMA_VERSION,
        "segments": segments,
        "source": source,
        "timeline": cast(JsonValue, timeline),
        "windows": windows,
    }
    if presentation_profile == "v2":
        document["motion_windows"] = motion_windows
        return validate_episode_presentation_plan_v2(document)
    return validate_episode_presentation_plan(document)


def build_episode_presentation_plan_bytes(
    delivery_plan: object,
    narration_plan: object,
    realization_plan: object,
    *,
    presentation_profile: str = "v1",
) -> bytes:
    """Return the canonical Episode Presentation Plan bytes for the given sources.

    The returned bytes are the one canonical encoding of the plan: sorted
    keys, tight separators, no non-finite floats, and exactly one trailing
    newline.

    Args:
        delivery_plan: The Episode Narration Delivery Plan V1.
        narration_plan: The Episode Narration Plan V1.
        realization_plan: The Episode Language Realization Plan V1.
        presentation_profile: ``"v1"`` (default) reproduces today's plan bytes
            exactly; ``"v2"`` derives the additive motion-window plan;
            ``"v3"`` derives the frozen, content-sized plan (no
            ``motion_windows``); ``"v4"`` derives the strict 1:1 plan (no
            ``motion_windows``), refusing any unit that cannot fit its slot.

    Raises:
        TypeError, ValueError: As :func:`build_episode_presentation_plan_document`.
    """
    document = build_episode_presentation_plan_document(
        delivery_plan, narration_plan, realization_plan, presentation_profile=presentation_profile
    )
    return dumps_canonical(document, "presentation plan")
