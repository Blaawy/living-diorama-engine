"""Deriving an Episode Presentation Plan from a delivery, a narration and a realization.

The derivation is a pure function of its inputs. It reads no clock, draws no
randomness, consults no filesystem path, calls no model, opens no socket, and
depends on no iteration order that Python is free to vary. The same three
documents always produce the same bytes.

What it decides is how many presentation frames the viewer sees each locked
semantic playback frame for, and only from structure: each unit's already
story-proven ``text_source`` classification, and the length of the delivery
slot the unit already owns. What it never decides is what is said, when in
*semantic* time a unit belongs, or what mattered. Wording stays in the
realization plan and is never read here -- not carried, not measured, not
counted; only its identity and position are named. The delivery plan's slots
are never moved, resized or re-cut -- only imaged onto a second, longer clock.

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
"""

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
from living_diorama.presentation.presentation_spec import (
    PRESENTATION_PLAN_FORMAT,
    PRESENTATION_POLICY_V1,
    PRESENTATION_SCHEMA_VERSION,
    SEGMENT_ID_FORM,
    WINDOW_ID_FORM,
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


def build_episode_presentation_plan_document(
    delivery_plan: object, narration_plan: object, realization_plan: object
) -> dict[str, JsonValue]:
    """Return the Episode Presentation Plan document for one directed episode.

    Args:
        delivery_plan: The Episode Narration Delivery Plan V1 whose slots this
            plan images onto the presentation clock.
        narration_plan: The Episode Narration Plan V1 whose units are
            presented, and whose ``text_source`` classification selects each
            unit's window floor.
        realization_plan: The Episode Language Realization Plan V1 whose
            sentences this plan's windows name by identity, never by content.

    Returns:
        A validated Episode Presentation Plan V1 document.

    Raises:
        TypeError: If any input has the wrong shape.
        ValueError: If any input fails its own contract, if the three do not
            join, or if the unit and slot counts disagree.
    """
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
    # every other playback frame's dwell is exactly 1.
    holds_by_frame: dict[int, int] = {}
    windows_geometry: list[tuple[int, int, int]] = []  # (unit index, slot_start, window_frames)
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
        window_frames, hold_frames = window_and_hold(slot_start, slot_end, text_source)
        if hold_frames > 0:
            holds_by_frame[slot_start] = hold_frames
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
    return validate_episode_presentation_plan(document)


def build_episode_presentation_plan_bytes(
    delivery_plan: object, narration_plan: object, realization_plan: object
) -> bytes:
    """Return the canonical Episode Presentation Plan bytes for the given sources.

    The returned bytes are the one canonical encoding of the plan: sorted
    keys, tight separators, no non-finite floats, and exactly one trailing
    newline.
    """
    document = build_episode_presentation_plan_document(
        delivery_plan, narration_plan, realization_plan
    )
    return dumps_canonical(document, "presentation plan")
