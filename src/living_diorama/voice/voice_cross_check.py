"""Cross-validation of an Episode Voice Plan against its actual sources.

:func:`living_diorama.voice.voice_schema_v1.validate_episode_voice_plan`
proves everything a voice plan can prove about itself: its narrator request
equals the one reviewed policy, and every voice unit is positional and sits
inside this layer's own plausibility rail. What it cannot prove is that the
plan's claims are *true of its sources* -- and, more than any other proof in
this chain, it cannot prove that the values it consumed from those sources
were themselves proven true of *their* sources. A voice plan whose
``capacity_samples`` was never checked against the actual Phase 27 window, or
whose bound realization plan was never checked against the actual realized
wording, would be syntactically perfect and semantically worthless.

This module closes both gaps by reusing, in full and unweakened, the one
upstream source-verification gate that already owns those proofs:
:func:`living_diorama.presentation.presentation_cross_check.validate_episode_presentation_plan_against_sources`,
which itself reruns the locked Phase 25 and Phase 26 gates in full. Once that
gate passes, this module verifies the voice plan's own bindings and every
per-record agreement, then seals the whole question by re-deriving the plan
from its two bound sources: the voice contract is a deterministic
single-output function of its inputs and the one pinned narrator request, so
the one valid plan for a given realization plan and presentation plan is the
plan the planner derives. Anything else is refused, named check by named
check first so a failure says which claim stopped being true.

Delivery Plan, Narration Plan, Shot Direction Plan, Story Plan and Render
Export travel through this module only as arguments to the reused gate: no
voice module treats any of the five as derivation authority, and no
voice-plan field ever restates a digest of any of them. This is narrower
than a blanket import ban -- the standalone schema legitimately imports
``living_diorama.narration.narration_schema_v1`` for its closed mode and ID
vocabulary (``MODE_BASELINE``, ``PLAN_MODES``, ``UNIT_ID_FORM``), the exact
precedent Phase 27 itself already set for the same three names. What stays
banned outright is the Narration Plan's own *content* as a source of truth,
and every one of ``living_diorama.narration_delivery``,
``living_diorama.story``, ``living_diorama.render`` and
``living_diorama.render_execution`` in full: the Narration Plan itself
travels through this module only as a verification-only argument to the
reused gate, never imported or opened directly here.
"""

from typing import cast

from living_diorama.language_realization.realization_schema_v1 import (
    validate_episode_language_realization_plan,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation.presentation_cross_check import (
    validate_episode_presentation_plan_against_sources,
)
from living_diorama.presentation.presentation_schema_v1 import validate_episode_presentation_plan
from living_diorama.voice.voice_planner import build_episode_voice_plan_bytes
from living_diorama.voice.voice_schema_v1 import JsonValue, validate_episode_voice_plan
from living_diorama.voice.voice_spec import VOICE_BLOCK, samples_per_presentation_frame

__all__ = ["validate_episode_voice_plan_against_sources"]


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
                f"voice plan binds {label} {source[field]!r}, but the offered {label}'s "
                f"canonical bytes hash to {offered!r}; this plan does not speak that document"
            )

    presentation_source = _document(presentation["source"], "presentation plan source")
    if presentation_source["realization_plan_sha256"] != realization_digest:
        raise ValueError(
            f"voice plan presents a presentation plan built from realization "
            f"{presentation_source['realization_plan_sha256']!r} against a realization plan "
            f"that hashes to {realization_digest!r}; the presentation plan and the "
            "realization plan are not the same episode's"
        )

    if source["realization_schema_version"] != realization["schema_version"]:
        raise ValueError(
            f"voice plan records realization schema version "
            f"{source['realization_schema_version']}, but the realization plan declares "
            f"{realization['schema_version']}"
        )
    if source["presentation_schema_version"] != presentation["schema_version"]:
        raise ValueError(
            f"voice plan records presentation schema version "
            f"{source['presentation_schema_version']}, but the presentation plan declares "
            f"{presentation['schema_version']}"
        )

    for field in ("episode", "mode", "previous_episode"):
        if source[field] != presentation_source[field]:
            raise ValueError(
                f"voice plan declares {field} {source[field]!r}, but the presentation plan "
                f"it speaks declares {presentation_source[field]!r}"
            )


def validate_episode_voice_plan_against_sources(
    voice_plan: object,
    realization_plan: object,
    presentation_plan: object,
    delivery_plan: object,
    narration_plan: object,
    shot_plan: object,
    story_plan: object,
    current_export: object,
) -> dict[str, JsonValue]:
    """Verify an Episode Voice Plan against its actual sources.

    Args:
        voice_plan: The Episode Voice Plan V1 document to verify.
        realization_plan: The Episode Language Realization Plan V1 whose
            sentences this plan's voice units name. Bound in this plan's
            source block.
        presentation_plan: The Episode Presentation Plan V1 whose windows
            this plan's voice units draw capacity from. Bound in this plan's
            source block.
        delivery_plan: The Episode Narration Delivery Plan V1 the
            presentation plan images. Verification-only: an argument to the
            reused Phase 27 gate.
        narration_plan: The Episode Narration Plan V1 the presentation plan
            presents. Verification-only: an argument to the reused gate.
        shot_plan: The Shot Direction Plan V1 the delivery plan was scheduled
            against. Verification-only: an argument to the reused gate.
        story_plan: The Episode Story Plan V1 the realization plan's wording
            was proven against. Verification-only: an argument to the reused
            gate.
        current_export: The Render Export V1 the story and realization plans
            were derived from. Verification-only: an argument to the reused
            gate.

    The named checks, in order:

    * the locked Phase 27 gate passes in full -- which itself reruns the
      locked Phase 25 and Phase 26 gates -- proving the presentation plan's
      windows and the realization plan's sentences are true of the actual
      delivery, narration, shot, story and render-export chain
    * the voice plan validates under its own contract
    * the two bound documents validate under their own contracts
    * the plan's two digests name exactly the realization and presentation
      documents offered, and those documents name each other
    * schema versions, mode, episode and previous episode agree across the
      voice plan and the presentation plan it speaks
    * the plan's narrator request equals the one reviewed policy block
    * the proven presentation fps crosses the pinned sample rate exactly
    * every voice unit speaks its positional narration unit, names its
      positional realization and its positional window: one voice unit per
      unit, in the realization plan's own order
    * every voice unit's ``capacity_samples`` equals the exact capacity of
      its actual, verified Phase 27 window

    Finally the plan is re-derived from its two bound sources and must equal
    it byte for byte, which closes every remaining degree of freedom -- every
    ``capacity_samples`` value itself included.

    Returns:
        The verified voice plan.

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
    )

    voice = validate_episode_voice_plan(voice_plan)
    realization = validate_episode_language_realization_plan(realization_plan)
    presentation = validate_episode_presentation_plan(presentation_plan)

    source = _document(voice["source"], "voice plan source")
    _check_bindings(source, realization, presentation)

    plan_voice = _document(voice["voice"], "voice plan voice")
    if dict(plan_voice) != dict(VOICE_BLOCK):
        raise ValueError(
            "voice plan voice block does not equal the one reviewed narrator request; a "
            "voice plan speaks under the pinned policy or not at all"
        )

    timeline = _document(presentation["timeline"], "presentation plan timeline")
    fps = cast(int, timeline["fps"])
    rate = samples_per_presentation_frame(fps)

    realizations = cast(list[dict[str, JsonValue]], realization["realizations"])
    windows = cast(list[dict[str, JsonValue]], presentation["windows"])
    voice_units = cast(list[dict[str, JsonValue]], voice["voice_units"])
    if not (len(voice_units) == len(windows) == len(realizations)):
        raise ValueError(
            f"voice plan carries {len(voice_units)} voice units for a presentation plan "
            f"presenting {len(windows)} windows and a realization plan realizing "
            f"{len(realizations)}; every unit is spoken exactly once"
        )

    for position, (unit, window, realized) in enumerate(
        zip(voice_units, windows, realizations, strict=True)
    ):
        label = f"voice plan voice_units[{position}]"
        if unit["unit_id"] != window["unit_id"]:
            raise ValueError(
                f"{label} speaks unit {unit['unit_id']!r}, but the presentation plan "
                f"presents {window['unit_id']!r} at that position"
            )
        if unit["unit_id"] != realized["unit_id"]:
            raise ValueError(
                f"{label} speaks unit {unit['unit_id']!r}, but the realization plan "
                f"realizes {realized['unit_id']!r} at that position; voice follows the "
                "realization plan's own order"
            )
        if unit["realization_id"] != realized["realization_id"]:
            raise ValueError(
                f"{label} names realization {unit['realization_id']!r}, but the "
                f"realization plan holds {realized['realization_id']!r} at that position"
            )
        if unit["window_id"] != window["window_id"]:
            raise ValueError(
                f"{label} names window {unit['window_id']!r}, but the presentation plan "
                f"holds {window['window_id']!r} at that position"
            )

        window_frames = (
            cast(int, window["presentation_end_frame"])
            - cast(int, window["presentation_start_frame"])
            + 1
        )
        expected_capacity = window_frames * rate
        if unit["capacity_samples"] != expected_capacity:
            raise ValueError(
                f"{label} declares capacity_samples {unit['capacity_samples']!r}, but its "
                f"actual window spans {window_frames} presentation frame(s) at {rate} "
                f"samples per frame, which resolves to {expected_capacity}; capacity is "
                "proven true of the real window, never merely plausible"
            )

    accounting = _document(voice["accounting"], "voice plan accounting")
    if accounting["voice_units_total"] != len(voice_units):
        raise ValueError(
            f"voice plan accounts {accounting['voice_units_total']!r} voice units but "
            f"carries {len(voice_units)}"
        )

    # The contract is a deterministic single-output function of its two bound
    # sources and the one pinned narrator request, so the one valid plan for
    # this realization plan and this presentation plan is the one the
    # planner derives. Byte equality closes every remaining degree of
    # freedom -- every capacity_samples value itself included. The delivery
    # plan, narration plan, shot plan, story plan and render export never
    # enter this derivation: they are the reused gate's arguments, not this
    # layer's own.
    derived = build_episode_voice_plan_bytes(realization, presentation)
    offered = dumps_canonical(voice, "voice plan")
    if offered != derived:
        raise ValueError(
            "voice plan does not equal the deterministic derivation from the realization "
            "plan and presentation plan it binds; a plan is source-verified only when it "
            "is the plan those two documents produce"
        )

    return voice
