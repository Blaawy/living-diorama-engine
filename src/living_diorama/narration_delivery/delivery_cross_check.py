"""Cross-validation of an Episode Narration Delivery Plan against its sources.

:func:`living_diorama.narration_delivery.delivery_schema_v1.validate_episode_narration_delivery_plan`
proves everything a delivery plan can prove about itself, the restated clock's
arithmetic and the slot ordering included. What it cannot prove is that the
plan's claims are *true of its sources*: that the two digests it carries name
the documents actually offered, that those documents name each other, that the
clock it restates is the clock the shot plan was cut against, that every slot
schedules its positional narration unit under the placement that unit's
visibility demands, and that every anchored slot lies inside the segment of the
shot that actually frames its beat. A plan whose SHA fields are syntactically
digests is not thereby source-verified.

This module closes that gap. Given the plan and the two documents it claims to
schedule, it verifies every binding and every per-record agreement, and then
seals the whole question by re-deriving the plan from those sources: the
delivery contract is a deterministic single-output function of its inputs, so
the one valid plan for a given narration plan and direction is the plan the
planner derives. Anything else is refused, named check by named check first so
a failure says which claim stopped being true.
"""

from typing import cast

from living_diorama.cinematic import (
    CANONICAL_MOTION_TIME_SHA256,
    validate_shot_direction_plan,
)
from living_diorama.narration.narration_schema_v1 import validate_episode_narration_plan
from living_diorama.narration.narration_spec import VISIBILITY_SHOWN
from living_diorama.narration_delivery.delivery_planner import (
    build_episode_narration_delivery_plan_bytes,
)
from living_diorama.narration_delivery.delivery_schema_v1 import (
    DELIVERY_TIMELINE_KEYS,
    JsonValue,
    validate_episode_narration_delivery_plan,
)
from living_diorama.narration_delivery.delivery_spec import (
    PLACEMENT_ALLOCATED_UNSHOWN,
    PLACEMENT_SHOT_ANCHORED,
    playback_domain,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex

__all__ = ["validate_narration_delivery_plan_against_sources"]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], value)


def _check_bindings(
    source: dict[str, JsonValue],
    narration: dict[str, JsonValue],
    shots: dict[str, JsonValue],
) -> None:
    """Verify the plan names the exact documents offered, and that they join."""
    narration_digest = sha256_hex(dumps_canonical(narration, "episode narration plan"))
    shot_digest = sha256_hex(dumps_canonical(shots, "shot direction plan"))

    for field, offered, label in (
        ("narration_plan_sha256", narration_digest, "narration plan"),
        ("shot_plan_sha256", shot_digest, "shot direction plan"),
    ):
        if source[field] != offered:
            raise ValueError(
                f"narration delivery plan binds {label} {source[field]!r}, but the offered "
                f"{label}'s canonical bytes hash to {offered!r}; this plan does not "
                f"schedule that document"
            )

    narration_source = _document(narration["source"], "episode narration plan source")
    if narration_source["shot_plan_sha256"] != source["shot_plan_sha256"]:
        raise ValueError(
            f"narration delivery plan schedules narration reported from shot plan "
            f"{narration_source['shot_plan_sha256']!r} under shot plan "
            f"{source['shot_plan_sha256']!r}; the narration and the direction are not the "
            "same episode's"
        )

    if source["narration_schema_version"] != narration["schema_version"]:
        raise ValueError(
            f"narration delivery plan records narration schema version "
            f"{source['narration_schema_version']}, but the narration plan declares "
            f"{narration['schema_version']}"
        )
    if source["shot_schema_version"] != shots["schema_version"]:
        raise ValueError(
            f"narration delivery plan records shot schema version "
            f"{source['shot_schema_version']}, but the shot plan declares "
            f"{shots['schema_version']}"
        )

    for field in ("mode", "episode", "previous_episode"):
        if source[field] != narration_source[field]:
            raise ValueError(
                f"narration delivery plan declares {field} {source[field]!r}, but the "
                f"narration plan it schedules declares {narration_source[field]!r}"
            )

    shot_source = _document(shots["source"], "shot direction plan source")
    if source["motion_time_sha256"] != shot_source["motion_time_sha256"]:
        raise ValueError(
            f"narration delivery plan pins Motion & Time source "
            f"{source['motion_time_sha256']!r}, but the shot plan was cut against "
            f"{shot_source['motion_time_sha256']!r}; a restated clock names the exact "
            "source it resolves from"
        )
    if source["motion_time_sha256"] != CANONICAL_MOTION_TIME_SHA256:
        raise ValueError(
            f"narration delivery plan pins Motion & Time source "
            f"{source['motion_time_sha256']!r}, which is not the canonical locked clock "
            f"({CANONICAL_MOTION_TIME_SHA256}); Phase 17 owns the clock and this layer "
            "schedules on no other"
        )


def _check_timeline(delivery: dict[str, JsonValue], shots: dict[str, JsonValue]) -> None:
    """Verify the restated clock is the shot plan's, key for key.

    The schema validator already proved the block closes on its own arithmetic;
    what only the sources can prove is that it is the *same* clock, not merely
    a self-consistent one -- the render layers learned that lesson first, and
    the check is the same here.
    """
    restated = _document(delivery["timeline"], "narration delivery plan timeline")
    granted = _document(shots["timeline"], "shot direction plan timeline")
    for key in sorted(DELIVERY_TIMELINE_KEYS):
        if restated[key] != granted[key]:
            raise ValueError(
                f"narration delivery plan timeline declares {key} {restated[key]!r}, but "
                f"the shot plan it schedules was cut on {granted[key]!r}; the clock is "
                "restated provenance, never arithmetic of this layer's own"
            )


def validate_narration_delivery_plan_against_sources(
    delivery_plan: object, narration_plan: object, shot_plan: object
) -> dict[str, JsonValue]:
    """Verify an Episode Narration Delivery Plan against its actual sources.

    Args:
        delivery_plan: The Episode Narration Delivery Plan V1 document to verify.
        narration_plan: The Episode Narration Plan V1 it claims to schedule.
        shot_plan: The Shot Direction Plan V1 whose segments host the slots.

    The named checks, in order:

    * all three documents validate under their own contracts -- which alone
      proves the delivery plan's slot ordering, playback bounds and restated
      clock arithmetic
    * the plan's two digests name exactly these documents, and the narration
      plan itself reports visibility from exactly this shot plan
    * schema versions, mode, episode and previous episode agree across all
      three documents
    * the pinned Motion & Time digest is the shot plan's own, and is the
      canonical locked clock
    * the restated timeline equals the shot plan's, key for key
    * every slot schedules its positional narration unit: one delivery per
      unit, in the narration plan's own order
    * every slot's placement is the one its unit's visibility demands
    * every anchored slot lies inside the playback segment of the exact shot
      the narration plan says frames its beat
    * the accounting block agrees with the narration plan's own

    Finally the plan is re-derived from the two sources and must equal it byte
    for byte, which closes every remaining degree of freedom -- the slot
    arithmetic itself included. A narration plan whose units misreport the
    direction's framing is refused by that derivation, with the derivation's
    own diagnostic.

    Returns:
        The verified delivery plan.

    Raises:
        TypeError: If any input has the wrong Python type.
        ValueError: If any binding, identity, agreement or derivation check
            fails.
    """
    delivery = validate_episode_narration_delivery_plan(delivery_plan)
    narration = validate_episode_narration_plan(narration_plan)
    shots = validate_shot_direction_plan(shot_plan)

    source = _document(delivery["source"], "narration delivery plan source")
    _check_bindings(source, narration, shots)
    _check_timeline(delivery, shots)

    units = cast(list[dict[str, JsonValue]], narration["units"])
    deliveries = cast(list[dict[str, JsonValue]], delivery["deliveries"])
    if len(deliveries) != len(units):
        raise ValueError(
            f"narration delivery plan carries {len(deliveries)} slots for a narration plan "
            f"holding {len(units)} units; every unit is scheduled exactly once"
        )

    timeline = _document(delivery["timeline"], "narration delivery plan timeline")
    _, playback_final = playback_domain(
        cast(int, timeline["start_frame"]), cast(int, timeline["end_frame"])
    )
    # The clamp is the planner's, repeated exactly: a shot that spans only the
    # witness boundary offers no playback segment at all. Two definitions of a
    # valid host would be no definition, so a shot the planner would drop is
    # absent here too.
    segments: dict[str, tuple[int, int]] = {}
    for shot in cast(list[dict[str, JsonValue]], shots["shots"]):
        first = cast(int, shot["start_frame"])
        last = min(cast(int, shot["end_frame"]), playback_final)
        if last >= first:
            segments[cast(str, shot["shot_id"])] = (first, last)

    for position, (record, unit) in enumerate(zip(deliveries, units, strict=True)):
        label = f"narration delivery plan deliveries[{position}]"
        if record["unit_id"] != unit["unit_id"]:
            raise ValueError(
                f"{label} schedules unit {record['unit_id']!r}, but the narration plan "
                f"holds {unit['unit_id']!r} at that position; delivery follows the "
                "narration plan's own order"
            )
        shown = unit["visibility"] == VISIBILITY_SHOWN
        expected = PLACEMENT_SHOT_ANCHORED if shown else PLACEMENT_ALLOCATED_UNSHOWN
        if record["placement"] != expected:
            raise ValueError(
                f"{label} declares placement {record['placement']!r} for a unit whose "
                f"visibility is {unit['visibility']!r}; placement is the delivery-side "
                "projection of Phase 22's visibility decision, never a re-judgement of it"
            )
        if shown:
            shot_id = cast(str, unit["shot_id"])
            segment = segments.get(shot_id)
            if segment is None:
                raise ValueError(
                    f"{label} anchors to shot {shot_id!r}, which the shot direction plan "
                    "does not hold or which offers no playback frame"
                )
            start = cast(int, record["start_frame"])
            end = cast(int, record["end_frame"])
            if start < segment[0] or end > segment[1]:
                raise ValueError(
                    f"{label} occupies frames [{start}, {end}], outside the playback "
                    f"segment [{segment[0]}, {segment[1]}] of shot {shot_id!r}; anchored "
                    "narration is scheduled only while its own beat's footage is on screen"
                )

    # Defense in depth: with the length check and the per-record placement
    # loop above both passed, these three ledger equalities already hold --
    # equal counts of equal per-position facts cannot disagree. The comparison
    # stays anyway, exactly as the schema keeps its own sum re-check: the day a
    # check above is loosened, this one still stands behind it.
    narration_accounting = _document(narration["accounting"], "episode narration plan accounting")
    delivery_accounting = _document(delivery["accounting"], "narration delivery plan accounting")
    for delivery_field, narration_field in (
        ("deliveries_total", "beats_total"),
        ("shot_anchored", "units_shown"),
        ("allocated_unshown", "units_unshown"),
    ):
        if delivery_accounting[delivery_field] != narration_accounting[narration_field]:
            raise ValueError(
                f"narration delivery plan accounts {delivery_field} "
                f"{delivery_accounting[delivery_field]!r}, but the narration plan accounts "
                f"{narration_field} {narration_accounting[narration_field]!r}; the two "
                "documents describe one schedule"
            )

    # The contract is a deterministic single-output function of its sources, so
    # the one valid plan for this narration plan and direction is the one the
    # planner derives. Byte equality closes every degree of freedom the named
    # checks above leave open -- the slot arithmetic itself included.
    derived = build_episode_narration_delivery_plan_bytes(narration, shots)
    offered = dumps_canonical(delivery, "narration delivery plan")
    if offered != derived:
        raise ValueError(
            "narration delivery plan does not equal the deterministic derivation from the "
            "narration plan and shot direction plan it binds; a plan is source-verified "
            "only when it is the plan those sources produce"
        )

    return delivery
