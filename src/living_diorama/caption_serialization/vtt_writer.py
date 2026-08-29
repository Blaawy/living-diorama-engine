r"""Serialize one locked Episode Caption Plan into exact WebVTT bytes.

The frozen grammar, whole: the header is exactly ``"WEBVTT\\n\\n"`` -- no BOM, no
header text, no NOTE, STYLE or REGION block -- followed by cue blocks
``f"{start} --> {end}\\n{text}\\n"`` with period-millisecond fixed-width
timestamps, joined by one ``"\\n"``. There are deliberately NO cue identifiers:
each block is one timing line plus one verbatim text line, and the SRT artifact
carries the numeric restatement of order. Always the long timestamp form with
two-digit hours -- never the short ``MM:SS.mmm`` abbreviation. UTF-8, LF only,
exactly one terminal LF. Cue text is carried verbatim on one physical line or
the whole serialization is refused; the ``-->`` refusal is a WebVTT structural
requirement, not a style choice.
"""

from typing import Final, cast

from living_diorama.caption.caption_schema_v1 import validate_episode_caption_plan
from living_diorama.caption_serialization.caption_serialization_spec import (
    require_carriable_caption_text,
)
from living_diorama.caption_serialization.caption_timestamp import (
    derive_cue_spans,
    format_timestamp,
)

_VTT_HEADER: Final = "WEBVTT\n\n"
"""The exact header bytes every artifact opens with: the magic, its LF, one blank line."""


def serialize_vtt_bytes(caption_plan: object) -> bytes:
    """Return the exact WebVTT bytes for one Episode Caption Plan.

    Self-defending: the plan is validated through the locked Phase 32 schema
    and every span is re-derived under ``caption_timestamp_policy_v1`` before a
    single byte is produced, so a forged document can never serialize.

    Raises:
        TypeError: If the plan carries a wrongly typed value.
        ValueError: If the plan is not a valid Episode Caption Plan.
        CaptionSerializationRefused: If a sentence cannot be carried verbatim,
            or a derived span violates the target format's ordering or
            representation rails.
    """
    plan = validate_episode_caption_plan(caption_plan)
    spans = derive_cue_spans(plan)
    captions = cast(list[dict[str, object]], plan["captions"])

    blocks: list[str] = []
    for cue, (start_ms, end_ms) in zip(captions, spans, strict=True):
        text = require_carriable_caption_text(
            cast(str, cue["caption_text"]), f"caption {cue['caption_id']!r} text"
        )
        start = format_timestamp(start_ms, ".")
        end = format_timestamp(end_ms, ".")
        blocks.append(f"{start} --> {end}\n{text}\n")
    return (_VTT_HEADER + "\n".join(blocks)).encode("utf-8")


__all__ = ["serialize_vtt_bytes"]
