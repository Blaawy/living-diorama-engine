"""Deriving an Episode Voice Plan from a realization and a presentation plan.

The derivation is a pure function of its inputs. It reads no clock, draws no
randomness, consults no filesystem path, calls no model, opens no socket, and
depends on no iteration order that Python is free to vary. The same two
documents and the one pinned narrator request always produce the same bytes.

What it decides is which reviewed narrator request speaks each locked
realized sentence, and how many audio samples its Phase 27 window offers --
and only from structure: the window's own presentation-frame length and the
proven presentation fps. What it never decides is what is said, when the
viewer sees it, or whether real speech actually fits. Wording stays in the
realization plan and is never read here -- not carried, not measured, not
counted, not even for its length; only a sentence's identity and position are
named. Whole-document canonical serialization of the offered realization
plan is required, to bind its exact bytes by digest; nothing in that
serialization is a semantic read of any one field inside it.

This module performs the same lightweight join every upstream planner
performs: it proves the two documents it receives actually name each other,
so a realization plan and a presentation plan built for different episodes
can never be joined into one voice plan. It does **not** re-run the deep
source-verification gate that proves the presentation plan's windows are
true of a delivery, narration, shot, story and export chain -- that locked
gate is
:func:`living_diorama.presentation.presentation_cross_check.validate_episode_presentation_plan_against_sources`,
and this voice layer's own cross-check runs it, in full, before this
planner's derivation may be trusted with any upstream window or realization
truth. A caller that skips that gate and calls this planner directly gets a
plan that is only as trustworthy as the documents it was handed.
"""

from typing import cast

from living_diorama.language_realization.realization_schema_v1 import (
    validate_episode_language_realization_plan,
)
from living_diorama.language_realization.realization_spec import REALIZATION_ID_FORM
from living_diorama.narration.narration_schema_v1 import UNIT_ID_FORM
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation.presentation_schema_v2 import validate_presentation_plan
from living_diorama.presentation.presentation_spec import WINDOW_ID_FORM
from living_diorama.voice.voice_schema_v1 import JsonValue, validate_episode_voice_plan
from living_diorama.voice.voice_spec import (
    VOICE_BLOCK,
    VOICE_PLAN_FORMAT,
    VOICE_PLAN_SCHEMA_VERSION,
    VOICE_POLICY_V1,
    VOICE_UNIT_ID_FORM,
    capacity_samples_for_window,
)

__all__ = [
    "build_episode_voice_plan_bytes",
    "build_episode_voice_plan_document",
]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def _require_join(
    realization: dict[str, JsonValue], presentation: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """Prove the two documents present one directed, realized, presented episode.

    Digest equality is the load-bearing check: the presentation plan already
    recorded which realization plan it presents, so a voice layer never has
    to decide whether two files "look like" the same episode. It asks the
    presentation plan what it bound and compares against the realization plan
    actually offered -- the same document offered here, which is what proves
    the two share one realized lineage rather than merely each claiming a
    plausible one.

    Raises:
        ValueError: If any binding or identity does not hold.
    """
    realization_source = _document(realization["source"], "language realization plan source")
    presentation_source = _document(presentation["source"], "presentation plan source")

    realization_digest = sha256_hex(dumps_canonical(realization, "language realization plan"))
    presentation_digest = sha256_hex(dumps_canonical(presentation, "presentation plan"))

    if presentation_source["realization_plan_sha256"] != realization_digest:
        raise ValueError(
            f"the presentation plan presents realization "
            f"{presentation_source['realization_plan_sha256']}, but the offered realization "
            f"plan hashes to {realization_digest}; the presentation plan and the realization "
            "plan are not the same episode's"
        )
    for field in ("mode", "episode", "previous_episode"):
        if presentation_source[field] != realization_source[field]:
            raise ValueError(
                f"the presentation plan declares {field} {presentation_source[field]!r}, "
                f"but the realization plan it presents declares "
                f"{realization_source[field]!r}"
            )

    return {
        "episode": realization_source["episode"],
        "mode": realization_source["mode"],
        "previous_episode": realization_source["previous_episode"],
        "presentation_plan_sha256": presentation_digest,
        "presentation_schema_version": presentation["schema_version"],
        "realization_plan_sha256": realization_digest,
        "realization_schema_version": realization["schema_version"],
    }


def build_episode_voice_plan_document(
    realization_plan: object, presentation_plan: object
) -> dict[str, JsonValue]:
    """Return the Episode Voice Plan document for one directed, realized episode.

    Args:
        realization_plan: The Episode Language Realization Plan V1 whose
            sentences this plan's voice units name by identity, never by
            content.
        presentation_plan: The Episode Presentation Plan V1 whose windows
            this plan's voice units draw their audio capacity from.

    Returns:
        A validated Episode Voice Plan V1 document.

    Raises:
        TypeError: If either input has the wrong shape.
        ValueError: If either input fails its own contract, if the two do not
            join, or if the unit and window counts disagree.
    """
    realization = validate_episode_language_realization_plan(realization_plan)
    presentation = validate_presentation_plan(presentation_plan)

    source = _require_join(realization, presentation)

    realizations = cast(list[dict[str, JsonValue]], realization["realizations"])
    windows = cast(list[dict[str, JsonValue]], presentation["windows"])
    if len(realizations) != len(windows):
        raise ValueError(
            f"the realization plan realizes {len(realizations)} units, but the "
            f"presentation plan presents {len(windows)}; every unit is spoken exactly once"
        )

    timeline = _document(presentation["timeline"], "presentation plan timeline")
    fps = cast(int, timeline["fps"])

    voice_units: list[JsonValue] = []
    total_capacity = 0
    for position, (realized, window) in enumerate(zip(realizations, windows, strict=True), start=1):
        expected_unit = UNIT_ID_FORM % position
        expected_realization = REALIZATION_ID_FORM % position
        expected_window = WINDOW_ID_FORM % position
        if realized["unit_id"] != expected_unit:
            raise ValueError(
                f"language realization plan realizations[{position - 1}] presents unit "
                f"{realized['unit_id']!r}, not the positional {expected_unit!r}"
            )
        if window["unit_id"] != expected_unit:
            raise ValueError(
                f"presentation plan windows[{position - 1}] presents unit "
                f"{window['unit_id']!r}, not the positional {expected_unit!r}"
            )
        if realized["realization_id"] != expected_realization:
            raise ValueError(
                f"language realization plan realizations[{position - 1}] carries id "
                f"{realized['realization_id']!r}, not the positional "
                f"{expected_realization!r}"
            )
        if window["realization_id"] != expected_realization:
            raise ValueError(
                f"presentation plan windows[{position - 1}] names realization "
                f"{window['realization_id']!r}, but the realization plan holds "
                f"{expected_realization!r} at that position"
            )
        if window["window_id"] != expected_window:
            raise ValueError(
                f"presentation plan windows[{position - 1}] carries id "
                f"{window['window_id']!r}, not the positional {expected_window!r}"
            )

        window_frames = (
            cast(int, window["presentation_end_frame"])
            - cast(int, window["presentation_start_frame"])
            + 1
        )
        capacity = capacity_samples_for_window(window_frames, fps)
        total_capacity += capacity

        voice_units.append(
            {
                "voice_unit_id": VOICE_UNIT_ID_FORM % position,
                "unit_id": expected_unit,
                "realization_id": expected_realization,
                "window_id": expected_window,
                "capacity_samples": capacity,
            }
        )

    document: dict[str, JsonValue] = {
        "accounting": {
            "voice_units_total": len(voice_units),
            "capacity_samples_total": total_capacity,
        },
        "format": VOICE_PLAN_FORMAT,
        "policy": VOICE_POLICY_V1,
        "schema_version": VOICE_PLAN_SCHEMA_VERSION,
        "source": source,
        "voice": cast(JsonValue, dict(VOICE_BLOCK)),
        "voice_units": voice_units,
    }
    return validate_episode_voice_plan(document)


def build_episode_voice_plan_bytes(realization_plan: object, presentation_plan: object) -> bytes:
    """Return the canonical Episode Voice Plan bytes for the given sources.

    The returned bytes are the one canonical encoding of the plan: sorted
    keys, tight separators, no non-finite floats, and exactly one trailing
    newline.
    """
    document = build_episode_voice_plan_document(realization_plan, presentation_plan)
    return dumps_canonical(document, "voice plan")
