"""Cross-validation of an Episode Presentation Plan against its actual sources.

:func:`living_diorama.presentation.presentation_schema_v1.validate_episode_presentation_plan`
proves everything a presentation plan can prove about itself: its restated
clock's arithmetic, its segment tiling, and its own presentation cursor's
arithmetic. What it cannot prove is that the plan's claims are *true of its
sources* -- and, more than any other proof in this chain, it cannot prove that
the values it consumed from those sources were themselves proven true of
*their* sources. A presentation plan whose ``text_source`` classification was
never checked against the actual story beat, or whose bound realization plan
was never checked against the actual realized wording, would be syntactically
perfect and semantically worthless.

This module closes both gaps by reusing, in full and unweakened, the two
upstream source-verification gates that already own those proofs. The first
is
:func:`living_diorama.narration_delivery.delivery_cross_check.validate_narration_delivery_plan_against_sources`,
which proves the delivery plan's slots are true of the actual narration plan
and shot direction plan it schedules. The second is
:func:`living_diorama.language_realization.realization_cross_check.validate_language_realization_plan_against_sources`,
which proves the realization plan's sentences -- and, load-bearing for this
layer, the narration plan's ``kind`` and therefore its ``text_source``
classification -- are true of the actual story plan and render export.

Neither gate is reimplemented here. This layer supplies whatever documents
each locked gate needs and treats a passing gate as license to trust the
values it consumed from the documents that gate covers. Story Plan, Shot
Direction Plan and Render Export travel through this module only as arguments
to those two gates: no presentation module ever imports
``living_diorama.story``, ``living_diorama.render`` or
``living_diorama.render_execution``, and no presentation-plan field ever
restates a digest of any of the three.

Once both gates pass, this module verifies the presentation plan's own
bindings and every per-record agreement, and then seals the whole question by
re-deriving the plan from its three bound sources: the presentation contract
is a deterministic single-output function of its inputs, so the one valid
plan for a given delivery plan, narration plan and realization plan is the
plan the planner derives. Anything else is refused, named check by named
check first so a failure says which claim stopped being true.
"""

from typing import cast

from living_diorama.cinematic import CANONICAL_MOTION_TIME_SHA256
from living_diorama.language_realization.realization_cross_check import (
    validate_language_realization_plan_against_sources,
)
from living_diorama.language_realization.realization_schema_v1 import (
    validate_episode_language_realization_plan,
)
from living_diorama.narration.narration_schema_v1 import validate_episode_narration_plan
from living_diorama.narration_delivery.delivery_cross_check import (
    validate_narration_delivery_plan_against_sources,
)
from living_diorama.narration_delivery.delivery_schema_v1 import (
    DELIVERY_TIMELINE_KEYS,
    validate_episode_narration_delivery_plan,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation.presentation_planner import build_episode_presentation_plan_bytes
from living_diorama.presentation.presentation_schema_v1 import (
    JsonValue,
    validate_episode_presentation_plan,
)

__all__ = ["validate_episode_presentation_plan_against_sources"]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], value)


def _check_bindings(
    source: dict[str, JsonValue],
    delivery: dict[str, JsonValue],
    narration: dict[str, JsonValue],
    realization: dict[str, JsonValue],
) -> None:
    """Verify the plan names the exact documents offered, and that they join."""
    delivery_digest = sha256_hex(dumps_canonical(delivery, "narration delivery plan"))
    narration_digest = sha256_hex(dumps_canonical(narration, "episode narration plan"))
    realization_digest = sha256_hex(dumps_canonical(realization, "language realization plan"))

    for field, offered, label in (
        ("delivery_plan_sha256", delivery_digest, "narration delivery plan"),
        ("narration_plan_sha256", narration_digest, "narration plan"),
        ("realization_plan_sha256", realization_digest, "language realization plan"),
    ):
        if source[field] != offered:
            raise ValueError(
                f"presentation plan binds {label} {source[field]!r}, but the offered "
                f"{label}'s canonical bytes hash to {offered!r}; this plan does not "
                f"present that document"
            )

    delivery_source = _document(delivery["source"], "narration delivery plan source")
    realization_source = _document(realization["source"], "language realization plan source")
    if delivery_source["narration_plan_sha256"] != narration_digest:
        raise ValueError(
            f"presentation plan presents a delivery plan scheduled from narration "
            f"{delivery_source['narration_plan_sha256']!r} against a narration plan that "
            f"hashes to {narration_digest!r}; the delivery plan and the narration plan "
            "are not the same episode's"
        )
    if realization_source["narration_plan_sha256"] != narration_digest:
        raise ValueError(
            f"presentation plan presents a realization plan built from narration "
            f"{realization_source['narration_plan_sha256']!r} against a narration plan "
            f"that hashes to {narration_digest!r}; the realization plan and the "
            "narration plan are not the same episode's"
        )

    if source["delivery_schema_version"] != delivery["schema_version"]:
        raise ValueError(
            f"presentation plan records delivery schema version "
            f"{source['delivery_schema_version']}, but the delivery plan declares "
            f"{delivery['schema_version']}"
        )
    if source["narration_schema_version"] != narration["schema_version"]:
        raise ValueError(
            f"presentation plan records narration schema version "
            f"{source['narration_schema_version']}, but the narration plan declares "
            f"{narration['schema_version']}"
        )
    if source["realization_schema_version"] != realization["schema_version"]:
        raise ValueError(
            f"presentation plan records realization schema version "
            f"{source['realization_schema_version']}, but the realization plan declares "
            f"{realization['schema_version']}"
        )

    for other_label, other_source in (
        ("narration delivery plan", delivery_source),
        ("language realization plan", realization_source),
    ):
        for field in ("mode", "episode", "previous_episode"):
            if source[field] != other_source[field]:
                raise ValueError(
                    f"presentation plan declares {field} {source[field]!r}, but the "
                    f"{other_label} it presents declares {other_source[field]!r}"
                )

    if source["motion_time_sha256"] != delivery_source["motion_time_sha256"]:
        raise ValueError(
            f"presentation plan pins Motion & Time source {source['motion_time_sha256']!r}, "
            f"but the delivery plan it presents was scheduled against "
            f"{delivery_source['motion_time_sha256']!r}; a restated clock names the exact "
            "source it resolves from"
        )
    if source["motion_time_sha256"] != CANONICAL_MOTION_TIME_SHA256:
        raise ValueError(
            f"presentation plan pins Motion & Time source {source['motion_time_sha256']!r}, "
            f"which is not the canonical locked clock ({CANONICAL_MOTION_TIME_SHA256}); "
            "Phase 17 owns the clock and this layer presents no other"
        )


def _check_timeline(presentation: dict[str, JsonValue], delivery: dict[str, JsonValue]) -> None:
    """Verify the restated clock is the delivery plan's, key for key."""
    restated = _document(presentation["timeline"], "presentation plan timeline")
    granted = _document(delivery["timeline"], "narration delivery plan timeline")
    for key in sorted(DELIVERY_TIMELINE_KEYS):
        if restated[key] != granted[key]:
            raise ValueError(
                f"presentation plan timeline declares {key} {restated[key]!r}, but the "
                f"delivery plan it presents was scheduled on {granted[key]!r}; the clock "
                "is restated provenance, never arithmetic of this layer's own"
            )


def validate_episode_presentation_plan_against_sources(
    presentation_plan: object,
    delivery_plan: object,
    narration_plan: object,
    shot_plan: object,
    realization_plan: object,
    story_plan: object,
    current_export: object,
) -> dict[str, JsonValue]:
    """Verify an Episode Presentation Plan against its actual sources.

    Args:
        presentation_plan: The Episode Presentation Plan V1 document to verify.
        delivery_plan: The Episode Narration Delivery Plan V1 whose slots this
            plan images. Bound in this plan's source block.
        narration_plan: The Episode Narration Plan V1 whose units this plan
            presents. Bound in this plan's source block.
        shot_plan: The Shot Direction Plan V1 the delivery plan was scheduled
            against. Verification-only: an argument to the locked Phase 25
            gate, never bound or restated in this plan's own source block.
        realization_plan: The Episode Language Realization Plan V1 whose
            sentences this plan's windows name. Bound in this plan's source
            block.
        story_plan: The Episode Story Plan V1 the realization plan's wording
            was proven against. Verification-only: an argument to the locked
            Phase 26 gate.
        current_export: The Render Export V1 the story and realization plans
            were derived from. Verification-only: an argument to the locked
            Phase 26 gate.

    The named checks, in order:

    * the locked Phase 25 gate passes in full: the delivery plan's slots,
      placements and clock are true of the actual narration and shot plans
    * the locked Phase 26 gate passes in full: the realization plan's
      sentences -- and the narration plan's ``kind`` and therefore its
      ``text_source`` classification -- are true of the actual story plan and
      render export
    * the presentation plan validates under its own contract
    * the plan's three digests name exactly the delivery, narration and
      realization documents offered, and those documents name each other
    * schema versions, mode, episode and previous episode agree across all
      four documents this plan is built from
    * the pinned Motion & Time digest is the delivery plan's own, and is the
      canonical locked clock
    * the restated timeline equals the delivery plan's, key for key
    * every window presents its positional narration unit and its positional
      realization: one window per unit, in the narration plan's own order

    Finally the plan is re-derived from its three bound sources and must
    equal it byte for byte, which closes every remaining degree of freedom --
    the hold placement and window geometry themselves included.

    Returns:
        The verified presentation plan.

    Raises:
        TypeError: If any input has the wrong Python type.
        ValueError: If either upstream gate refuses, or if any binding,
            identity, agreement or derivation check fails.
    """
    # No delivery slot, and no unit's text_source classification, becomes
    # authoritative before the two documents that prove them true of their
    # own sources have both been verified in full.
    validate_narration_delivery_plan_against_sources(delivery_plan, narration_plan, shot_plan)
    validate_language_realization_plan_against_sources(
        realization_plan, narration_plan, story_plan, current_export
    )

    presentation = validate_episode_presentation_plan(presentation_plan)
    delivery = validate_episode_narration_delivery_plan(delivery_plan)
    narration = validate_episode_narration_plan(narration_plan)
    realization = validate_episode_language_realization_plan(realization_plan)

    source = _document(presentation["source"], "presentation plan source")
    _check_bindings(source, delivery, narration, realization)
    _check_timeline(presentation, delivery)

    units = cast(list[dict[str, JsonValue]], narration["units"])
    deliveries = cast(list[dict[str, JsonValue]], delivery["deliveries"])
    realizations = cast(list[dict[str, JsonValue]], realization["realizations"])
    windows = cast(list[dict[str, JsonValue]], presentation["windows"])
    if not (len(windows) == len(deliveries) == len(units) == len(realizations)):
        raise ValueError(
            f"presentation plan carries {len(windows)} windows for a narration plan "
            f"holding {len(units)} units, a delivery plan scheduling {len(deliveries)}, "
            f"and a realization plan realizing {len(realizations)}; every unit is "
            "presented exactly once"
        )

    for position, (window, record, unit, realized) in enumerate(
        zip(windows, deliveries, units, realizations, strict=True)
    ):
        label = f"presentation plan windows[{position}]"
        if window["unit_id"] != record["unit_id"]:
            raise ValueError(
                f"{label} presents unit {window['unit_id']!r}, but the delivery plan "
                f"schedules {record['unit_id']!r} at that position"
            )
        if window["unit_id"] != unit["unit_id"]:
            raise ValueError(
                f"{label} presents unit {window['unit_id']!r}, but the narration plan "
                f"holds {unit['unit_id']!r} at that position; presentation follows the "
                "narration plan's own order"
            )
        if window["realization_id"] != realized["realization_id"]:
            raise ValueError(
                f"{label} names realization {window['realization_id']!r}, but the "
                f"realization plan holds {realized['realization_id']!r} at that position"
            )
        if realized["unit_id"] != unit["unit_id"]:
            raise ValueError(
                f"{label} presents unit {unit['unit_id']!r}, whose realization "
                f"{realized['realization_id']!r} names unit {realized['unit_id']!r}; the "
                "realization plan and the narration plan disagree about their own order"
            )

    accounting = _document(presentation["accounting"], "presentation plan accounting")
    if accounting["windows_total"] != len(windows):
        raise ValueError(
            f"presentation plan accounts {accounting['windows_total']!r} windows but "
            f"carries {len(windows)}"
        )

    # The contract is a deterministic single-output function of its three
    # bound sources, so the one valid plan for this delivery plan, this
    # narration plan and this realization plan is the one the planner
    # derives. Byte equality closes every degree of freedom the named checks
    # above leave open -- the hold placement and the window geometry
    # themselves included. The shot plan, story plan and render export never
    # enter this derivation: they are the two upstream gates' arguments, not
    # this layer's own.
    derived = build_episode_presentation_plan_bytes(delivery, narration, realization)
    offered = dumps_canonical(presentation, "presentation plan")
    if offered != derived:
        raise ValueError(
            "presentation plan does not equal the deterministic derivation from the "
            "delivery plan, narration plan and realization plan it binds; a plan is "
            "source-verified only when it is the plan those three documents produce"
        )

    return presentation
