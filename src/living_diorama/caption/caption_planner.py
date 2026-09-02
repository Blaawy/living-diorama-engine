"""Deriving an Episode Caption Plan from a realization and a presentation plan.

The derivation is a pure function of its inputs. It reads no clock, draws no
randomness, consults no filesystem path, and depends on no iteration order
that Python is free to vary. The same two documents always produce the same
bytes.

What it decides is for how many presentation frames each locked realized
sentence is legible -- and only from structure: a window's own presentation
frames, copied, never re-derived from a slot, a ``text_source`` floor or a
hold. What it never decides is what is said (never read here except to
carry it forward unchanged) or when a viewer's device renders it.

This module performs the same lightweight join every upstream planner
performs: it proves the two documents it receives actually name each other,
so a realization plan and a presentation plan built for different episodes
can never be joined into one caption plan. It does **not** re-run the deep
source-verification chain that proves the presentation plan's windows are
true of a delivery, narration, shot, story and export chain -- that locked
gate is
:func:`living_diorama.presentation.presentation_cross_check.validate_episode_presentation_plan_against_sources`,
and this layer's own cross-check runs it, in full, before this planner's
derivation may be trusted with any upstream window or realization truth.
"""

from collections.abc import Mapping
from typing import cast

from living_diorama.caption.caption_schema_v1 import JsonValue, validate_episode_caption_plan
from living_diorama.caption.caption_spec import (
    CAPTION_ID_FORM,
    CAPTION_PLAN_FORMAT,
    CAPTION_POLICY_V1,
    CAPTION_SCHEMA_VERSION,
    caption_frames_for_window,
)
from living_diorama.language_realization.realization_schema_v1 import (
    validate_episode_language_realization_plan,
)
from living_diorama.language_realization.realization_spec import REALIZATION_ID_FORM
from living_diorama.narration.narration_schema_v1 import UNIT_ID_FORM
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.presentation.presentation_schema_v2 import validate_presentation_plan

__all__ = [
    "build_episode_caption_plan_bytes",
    "build_episode_caption_plan_document",
    "caption_texts",
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
    recorded which realization plan it presents, so this layer never has to
    decide whether two files "look like" the same episode.

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
                f"the presentation plan declares {field} {presentation_source[field]!r}, but "
                f"the realization plan it presents declares {realization_source[field]!r}"
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


def caption_texts(realization_plan: Mapping[str, object]) -> list[str]:
    """Return each unit's exact verified realized sentence, in plan order.

    THE SINGLE EXEMPT FUNCTION, and the only keyed read of ``realized_text``
    anywhere in this phase. It speaks the exact bytes a gate-verified
    realization plan proved: no normalization, no punctuation rewrite, no
    case change, no comparison, no inspection -- the exact analogue of
    Phase 29's ``unit_texts``.
    """
    realizations = cast(list[Mapping[str, object]], realization_plan["realizations"])
    return [cast(str, realization["realized_text"]) for realization in realizations]


def build_episode_caption_plan_document(
    realization_plan: object, presentation_plan: object
) -> dict[str, JsonValue]:
    """Return the Episode Caption Plan document for one realized, presented episode.

    Args:
        realization_plan: The Episode Language Realization Plan V1 whose
            sentences this plan's cues carry verbatim.
        presentation_plan: The Episode Presentation Plan V1 whose windows
            this plan's cues draw their frames from.

    Returns:
        A validated Episode Caption Plan V1 document.

    Raises:
        TypeError: If either input has the wrong shape.
        ValueError: If either input fails its own contract, if the two do
            not join, or if the unit and window counts disagree.
    """
    realization = validate_episode_language_realization_plan(realization_plan)
    presentation = validate_presentation_plan(presentation_plan)

    source = _require_join(realization, presentation)

    realizations = cast(list[dict[str, JsonValue]], realization["realizations"])
    windows = cast(list[dict[str, JsonValue]], presentation["windows"])
    if len(realizations) != len(windows):
        raise ValueError(
            f"the realization plan realizes {len(realizations)} units, but the presentation "
            f"plan presents {len(windows)}; every unit is captioned exactly once"
        )

    texts = caption_texts(realization)  # THE ONE EXEMPT KEYED READ

    timeline = _document(presentation["timeline"], "presentation plan timeline")
    fps = timeline["fps"]
    presentation_accounting = _document(presentation["accounting"], "presentation plan accounting")
    presentation_frames_total = presentation_accounting["presentation_frames_total"]

    captions: list[JsonValue] = []
    caption_frames_total = 0
    for position, (window, text) in enumerate(zip(windows, texts, strict=True), start=1):
        expected_unit = UNIT_ID_FORM % position
        expected_realization = REALIZATION_ID_FORM % position
        if window["unit_id"] != expected_unit:
            raise ValueError(
                f"presentation plan windows[{position - 1}] presents unit "
                f"{window['unit_id']!r}, not the positional {expected_unit!r}"
            )
        if window["realization_id"] != expected_realization:
            raise ValueError(
                f"presentation plan windows[{position - 1}] names realization "
                f"{window['realization_id']!r}, but the realization plan holds "
                f"{expected_realization!r} at that position"
            )
        if realizations[position - 1]["unit_id"] != expected_unit:
            raise ValueError(
                f"language realization plan realizations[{position - 1}] presents unit "
                f"{realizations[position - 1]['unit_id']!r}, not the positional "
                f"{expected_unit!r}"
            )

        start_frame, end_frame = caption_frames_for_window(
            cast(int, window["presentation_start_frame"]),
            cast(int, window["presentation_end_frame"]),
        )
        caption_frames_total += end_frame - start_frame + 1

        captions.append(
            {
                "caption_id": CAPTION_ID_FORM % position,
                "caption_text": text,  # DIRECT ASSIGNMENT -- no operation performed on it
                "presentation_end_frame": end_frame,
                "presentation_start_frame": start_frame,
                "realization_id": expected_realization,
                "unit_id": expected_unit,
                "window_id": window["window_id"],
            }
        )

    document: dict[str, JsonValue] = {
        "accounting": {
            "caption_frames_total": caption_frames_total,
            "captions_total": len(captions),
            "uncaptioned_frames_total": cast(int, presentation_frames_total) - caption_frames_total,
        },
        "captions": captions,
        "clock": {"fps": fps, "presentation_frames_total": presentation_frames_total},
        "format": CAPTION_PLAN_FORMAT,
        "policy": CAPTION_POLICY_V1,
        "schema_version": CAPTION_SCHEMA_VERSION,
        "source": source,
    }
    return validate_episode_caption_plan(document)


def build_episode_caption_plan_bytes(realization_plan: object, presentation_plan: object) -> bytes:
    """Return the canonical Episode Caption Plan bytes for the given sources.

    The returned bytes are the one canonical encoding of the plan: sorted
    keys, tight separators, no non-finite floats, and exactly one trailing
    newline.
    """
    document = build_episode_caption_plan_document(realization_plan, presentation_plan)
    return dumps_canonical(document, "caption plan")
