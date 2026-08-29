r"""Serialize one locked Episode Caption Plan into exact SRT bytes.

The frozen grammar, whole: for cues ``i = 1..N`` in plan order, one block is
``f"{i}\\n{start} --> {end}\\n{text}\\n"`` with comma-millisecond fixed-width
timestamps, and the file is the blocks joined by one ``"\\n"`` -- a single blank
line BETWEEN blocks, never before the first and never after the last -- encoded
UTF-8 with no BOM, LF only, exactly one terminal LF (the final block's own).
Cue numbers are 1-based and sequential, a restatement of the plan's own strict
cue order. Cue text is carried verbatim on exactly one physical line, or the
whole serialization is refused -- nothing is rewritten, wrapped, styled or
escaped here.
"""

from typing import cast

from living_diorama.caption.caption_schema_v1 import validate_episode_caption_plan
from living_diorama.caption_serialization.caption_serialization_spec import (
    require_carriable_caption_text,
)
from living_diorama.caption_serialization.caption_timestamp import (
    derive_cue_spans,
    format_timestamp,
)


def serialize_srt_bytes(caption_plan: object) -> bytes:
    """Return the exact SRT bytes for one Episode Caption Plan.

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
    for position, (cue, (start_ms, end_ms)) in enumerate(zip(captions, spans, strict=True), 1):
        text = require_carriable_caption_text(
            cast(str, cue["caption_text"]), f"caption {cue['caption_id']!r} text"
        )
        start = format_timestamp(start_ms, ",")
        end = format_timestamp(end_ms, ",")
        blocks.append(f"{position}\n{start} --> {end}\n{text}\n")
    return "\n".join(blocks).encode("utf-8")


__all__ = ["serialize_srt_bytes"]
