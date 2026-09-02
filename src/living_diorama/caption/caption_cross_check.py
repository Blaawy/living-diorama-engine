"""Cross-validation of an Episode Caption Plan against its actual sources.

:func:`living_diorama.caption.caption_schema_v1.validate_episode_caption_plan`
proves everything a caption plan can prove about itself: its cues are
positional, never overlap, and sit inside this layer's own plausibility
rail. What it cannot prove is that the plan's claims are *true of its
sources* -- and, more than any other proof in this chain, it cannot prove
that the values it consumed from those sources were themselves proven true
of *their* sources. A caption plan whose frames were never checked against
the actual Phase 27 window, or whose carried text was never checked against
the actual Phase 26 sentence, would be syntactically perfect and
semantically worthless.

This module closes both gaps by reusing, in full and unweakened, the one
upstream source-verification gate that already owns those proofs:
:func:`living_diorama.presentation.presentation_cross_check.validate_episode_presentation_plan_against_sources`,
which itself reruns the locked Phase 25 and Phase 26 gates in full. Once
that gate passes, this module verifies the caption plan's own bindings and
every per-cue agreement -- including the one approved identity comparison
that proves a carried sentence equals its bound source -- then seals the
whole question by re-deriving the plan from its two bound sources: the
caption contract is a deterministic single-output function of its inputs,
so the one valid plan for a given realization plan and presentation plan is
the plan the planner derives.

Delivery Plan, Narration Plan, Shot Direction Plan, Story Plan and Render
Export travel through this module only as arguments to the reused gate: no
caption module treats any of the five as derivation authority, and no
caption-plan field ever restates a digest of any of them.
"""

from typing import cast

from living_diorama.caption.caption_planner import build_episode_caption_plan_bytes
from living_diorama.caption.caption_schema_v1 import JsonValue, validate_episode_caption_plan
from living_diorama.language_realization.realization_schema_v1 import (
    validate_episode_language_realization_plan,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation.presentation_cross_check import (
    validate_episode_presentation_plan_against_sources,
)
from living_diorama.presentation.presentation_schema_v2 import validate_presentation_plan

__all__ = ["validate_episode_caption_plan_against_sources"]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def _check_bindings(
    source: dict[str, JsonValue],
    realization: dict[str, JsonValue],
    presentation: dict[str, JsonValue],
) -> None:
    """Verify the plan names the exact documents offered, and that they agree."""
    realization_digest = sha256_hex(dumps_canonical(realization, "language realization plan"))
    presentation_digest = sha256_hex(dumps_canonical(presentation, "presentation plan"))

    for field, offered, label in (
        ("realization_plan_sha256", realization_digest, "language realization plan"),
        ("presentation_plan_sha256", presentation_digest, "presentation plan"),
    ):
        if source[field] != offered:
            raise ValueError(
                f"caption plan binds {label} {source[field]!r}, but the offered {label}'s "
                f"canonical bytes hash to {offered!r}; this plan does not caption that document"
            )

    presentation_source = _document(presentation["source"], "presentation plan source")
    if presentation_source["realization_plan_sha256"] != realization_digest:
        raise ValueError(
            f"caption plan presents a presentation plan built from realization "
            f"{presentation_source['realization_plan_sha256']!r} against a realization plan "
            f"that hashes to {realization_digest!r}; the presentation plan and the realization "
            "plan are not the same episode's"
        )

    if source["realization_schema_version"] != realization["schema_version"]:
        raise ValueError(
            f"caption plan records realization schema version "
            f"{source['realization_schema_version']}, but the realization plan declares "
            f"{realization['schema_version']}"
        )
    if source["presentation_schema_version"] != presentation["schema_version"]:
        raise ValueError(
            f"caption plan records presentation schema version "
            f"{source['presentation_schema_version']}, but the presentation plan declares "
            f"{presentation['schema_version']}"
        )

    for field in ("episode", "mode", "previous_episode"):
        if source[field] != presentation_source[field]:
            raise ValueError(
                f"caption plan declares {field} {source[field]!r}, but the presentation plan "
                f"it captions declares {presentation_source[field]!r}"
            )


def _require_carried_text(
    caption: dict[str, JsonValue], realized: dict[str, JsonValue], description: str
) -> None:
    """Refuse unless this cue's text equals its bound realization's, by exact string value.

    THE SINGLE IDENTITY-COMPARISON EXEMPTION in this phase. One keyed read
    of ``caption_text``, one keyed read of ``realized_text``, and exactly
    one comparison, used solely to accept equality or refuse mismatch.

    "Prose may be carried, never branched on" means no derived behaviour may
    depend on the lexical or semantic content of the prose. It does not
    prohibit an exact equality check whose only purpose is proving that a
    downstream restatement equals its bound upstream authority -- the same
    shape every locked cross-check already uses to compare a restated
    digest or a restated integer against its source. No frame, identifier,
    order or accounting fact is ever chosen from what either string says;
    the outcome here depends only on whether the two values are the same
    value, never on what either one contains.
    """
    caption_text = caption["caption_text"]
    realized_text = realized["realized_text"]
    if caption_text != realized_text:
        raise ValueError(
            f"{description} caption_text does not equal the bound realization's realized_text; "
            "a carried sentence is proven true of its source by exact string-value equality"
        )


def validate_episode_caption_plan_against_sources(
    caption_plan: object,
    realization_plan: object,
    presentation_plan: object,
    delivery_plan: object,
    narration_plan: object,
    shot_plan: object,
    story_plan: object,
    current_export: object,
    *,
    presentation_profile: str | None = None,
) -> dict[str, JsonValue]:
    """Verify an Episode Caption Plan against its actual sources.

    Args:
        caption_plan: The Episode Caption Plan V1 document to verify.
        realization_plan: The Episode Language Realization Plan V1 whose
            sentences this plan's cues carry. Bound in this plan's source
            block.
        presentation_plan: The Episode Presentation Plan V1 whose windows
            this plan's cues draw their frames from. Bound in this plan's
            source block.
        delivery_plan: The Episode Narration Delivery Plan V1 the
            presentation plan images. Verification-only: an argument to the
            reused Phase 27 gate.
        narration_plan: The Episode Narration Plan V1 the presentation plan
            presents. Verification-only: an argument to the reused gate.
        shot_plan: The Shot Direction Plan V1 the delivery plan was
            scheduled against. Verification-only: an argument to the reused
            gate.
        story_plan: The Episode Story Plan V1 the realization plan's
            wording was proven against. Verification-only: an argument to
            the reused gate.
        current_export: The Render Export V1 the story and realization
            plans were derived from. Verification-only: an argument to the
            reused gate.
        presentation_profile: The presentation profile the reused Phase 27
            gate re-derives the presentation plan under. ``None`` (the
            default) preserves today's exact behavior: a plan carrying
            ``motion_windows`` is verified as V2, any other plan as V1. Pass
            ``"v1"``, ``"v2"`` or ``"v3"`` to pin the profile explicitly --
            ``"v3"`` is required for the frozen, content-sized V3
            presentation plan, which carries no ``motion_windows`` and would
            otherwise be re-derived as V1 and refused.

    The named checks, in order:

    * the locked Phase 27 gate passes in full -- which itself reruns the
      locked Phase 25 and Phase 26 gates -- proving the presentation plan's
      windows and the realization plan's sentences true of the actual
      delivery, narration, shot, story and render-export chain
    * the caption plan validates under its own contract
    * the two bound documents validate under their own contracts
    * the plan's two digests name exactly the realization and presentation
      documents offered, and those documents name each other
    * schema versions, mode, episode and previous episode agree across the
      caption plan and the presentation plan it captions
    * the restated clock (fps, presentation frame total) agrees with the
      presentation plan's own proven values
    * every cue names its positional unit, realization and window; its
      frames equal that actual window's own frames; and its carried text
      equals that positional realization's sentence, by exact string-value
      equality
    * accounting is recomputed from the records present

    Finally the plan is re-derived from its two bound sources and must
    equal it byte for byte, which closes every remaining degree of freedom.

    Returns:
        The verified caption plan.

    Raises:
        TypeError: If any input has the wrong Python type.
        ValueError: If the reused gate refuses, or if any binding, identity,
            agreement or derivation check fails.
    """
    # No presentation window, and no realization plan's identity, becomes
    # authoritative before the one document that proves them both true of
    # their own sources has been verified in full.
    validate_episode_presentation_plan_against_sources(
        presentation_plan,
        delivery_plan,
        narration_plan,
        shot_plan,
        realization_plan,
        story_plan,
        current_export,
        presentation_profile=(
            (
                "v2"
                if isinstance(presentation_plan, dict) and "motion_windows" in presentation_plan
                else "v1"
            )
            if presentation_profile is None
            else presentation_profile
        ),
    )

    plan = validate_episode_caption_plan(caption_plan)
    realization = validate_episode_language_realization_plan(realization_plan)
    presentation = validate_presentation_plan(presentation_plan)

    source = _document(plan["source"], "caption plan source")
    _check_bindings(source, realization, presentation)

    timeline = _document(presentation["timeline"], "presentation plan timeline")
    fps = cast(int, timeline["fps"])
    clock = _document(plan["clock"], "caption plan clock")
    if clock["fps"] != fps:
        raise ValueError(
            f"caption plan clock fps is {clock['fps']!r}, but the presentation plan's actual "
            f"timeline fps is {fps!r}"
        )
    presentation_accounting = _document(presentation["accounting"], "presentation plan accounting")
    presentation_frames_total = cast(int, presentation_accounting["presentation_frames_total"])
    if clock["presentation_frames_total"] != presentation_frames_total:
        raise ValueError(
            f"caption plan clock presentation_frames_total is "
            f"{clock['presentation_frames_total']!r}, but the presentation plan's actual total "
            f"is {presentation_frames_total!r}"
        )

    captions = cast(list[dict[str, JsonValue]], plan["captions"])
    windows = cast(list[dict[str, JsonValue]], presentation["windows"])
    realizations = cast(list[dict[str, JsonValue]], realization["realizations"])
    if not (len(captions) == len(windows) == len(realizations)):
        raise ValueError(
            f"caption plan carries {len(captions)} captions for a presentation plan presenting "
            f"{len(windows)} windows and a realization plan realizing {len(realizations)}; "
            "every unit is captioned exactly once"
        )

    for position, (caption, window, realized) in enumerate(
        zip(captions, windows, realizations, strict=True)
    ):
        label = f"caption plan captions[{position}]"
        if caption["unit_id"] != window["unit_id"]:
            raise ValueError(
                f"{label} captions unit {caption['unit_id']!r}, but the presentation plan "
                f"presents {window['unit_id']!r} at that position"
            )
        if caption["realization_id"] != window["realization_id"]:
            raise ValueError(
                f"{label} names realization {caption['realization_id']!r}, but the "
                f"presentation plan's window at that position names "
                f"{window['realization_id']!r}"
            )
        if caption["window_id"] != window["window_id"]:
            raise ValueError(
                f"{label} names window {caption['window_id']!r}, but the presentation plan "
                f"holds {window['window_id']!r} at that position"
            )
        if caption["presentation_start_frame"] != window["presentation_start_frame"]:
            raise ValueError(
                f"{label} declares presentation_start_frame "
                f"{caption['presentation_start_frame']!r}, but its actual window's start frame "
                f"resolves to {window['presentation_start_frame']!r}"
            )
        if caption["presentation_end_frame"] != window["presentation_end_frame"]:
            raise ValueError(
                f"{label} declares presentation_end_frame "
                f"{caption['presentation_end_frame']!r}, but its actual window's end frame "
                f"resolves to {window['presentation_end_frame']!r}"
            )
        _require_carried_text(caption, realized, label)  # THE ONE APPROVED COMPARISON

    accounting = _document(plan["accounting"], "caption plan accounting")
    if accounting["captions_total"] != len(captions):
        raise ValueError(
            f"caption plan accounts {accounting['captions_total']!r} captions but carries "
            f"{len(captions)}"
        )

    # The contract is a deterministic single-output function of its two
    # bound sources, so the one valid plan for this realization plan and
    # this presentation plan is the one the planner derives. Byte equality
    # closes every remaining degree of freedom. The delivery plan,
    # narration plan, shot plan, story plan and render export never enter
    # this derivation: they are the reused gate's arguments, not this
    # layer's own.
    derived = build_episode_caption_plan_bytes(realization, presentation)
    offered = dumps_canonical(plan, "caption plan")
    if offered != derived:
        raise ValueError(
            "caption plan does not equal the deterministic derivation from the realization "
            "plan and presentation plan it binds; a plan is source-verified only when it is "
            "the plan those two documents produce"
        )

    return plan
