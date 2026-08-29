"""The Phase 34 timestamp law: one pure-integer floor derivation and its formatting.

``caption_timestamp_policy_v1``, whole: a presentation boundary offset ``n`` on a
clock of ``fps`` frames per second derives the millisecond ``n * 1000 // fps``.
A cue legible on the 1-based inclusive frames ``[start, end]`` occupies the
half-open wall-clock interval ``[boundary_ms(start - 1), boundary_ms(end))`` --
consecutive tight cues therefore SHARE one boundary instant exactly, because the
next cue's start offset is the previous cue's end offset, the same integer fed
to the same function. Floor is the reviewed V1 representation law: where the
exact rational is not a whole millisecond the derived value never overstates a
boundary. No float, no ``Decimal``, no wall clock, no locale and no host-
dependent rounding appears anywhere in this module.

``boundary_ms`` is total over its declared integer domain (``offset >= 0``,
``fps >= 1``) -- the derivation never refuses. The formatting rail below is the
serializer's own representation limit, a different law: two-digit hours.
"""

from typing import Final, cast

from living_diorama.caption.caption_schema_v1 import validate_episode_caption_plan
from living_diorama.caption.caption_spec import MAX_CAPTION_FRAME
from living_diorama.caption_serialization.caption_serialization_spec import (
    MAX_TIMESTAMP_MS,
    CaptionSerializationRefused,
)

_MS_PER_HOUR: Final = 3_600_000
_MS_PER_MINUTE: Final = 60_000
_MS_PER_SECOND: Final = 1_000


def boundary_ms(offset: int, fps: int) -> int:
    """Return the derived millisecond of one presentation boundary offset.

    Args:
        offset: The boundary's frame offset on the presentation clock -- a
            cue's start uses ``presentation_start_frame - 1`` and its end uses
            ``presentation_end_frame``, so the cue's wall-clock image is the
            half-open interval between the two derived values.
        fps: The plan's gate-verified presentation frames per second.

    Returns:
        ``offset * 1000 // fps``, exact where ``offset * 1000`` divides by
        ``fps`` and floored where it does not.

    Raises:
        TypeError: If either value is not an exact ``int`` (``bool`` is
            refused because it subclasses ``int``).
        ValueError: If ``offset`` is negative or ``fps`` is not positive.
    """
    if type(offset) is not int:
        raise TypeError(f"offset must be an int, got {type(offset).__name__}")
    if type(fps) is not int:
        raise TypeError(f"fps must be an int, got {type(fps).__name__}")
    if offset < 0:
        raise ValueError(f"offset must be >= 0, got {offset}")
    if fps < 1:
        raise ValueError(f"fps must be >= 1, got {fps}")
    return offset * 1000 // fps


def cue_span_ms(cue: object, fps: int) -> tuple[int, int]:
    """Return one cue's derived ``(start_ms, end_ms)`` half-open wall-clock span.

    The cue's frames are read exactly as the Phase 32 schema defines them:
    1-based inclusive ``presentation_start_frame`` and ``presentation_end_frame``.
    The span is required to be strictly positive -- WebVTT requires an end time
    greater than its start, and a zero-length span is reachable only from a
    forged standalone plan at fps >= 1000, never from the canonical chain.

    Raises:
        TypeError: If the cue is not a dict or a frame is not an exact ``int``.
        ValueError: If a frame is out of its 1-based domain or the frames invert.
        CaptionSerializationRefused: If the derived span is not strictly
            positive.
    """
    if type(cue) is not dict:
        raise TypeError(f"cue must be a dict, got {type(cue).__name__}")
    record = cast(dict[str, object], cue)
    start_frame = record.get("presentation_start_frame")
    end_frame = record.get("presentation_end_frame")
    if type(start_frame) is not int:
        raise TypeError(
            f"cue presentation_start_frame must be an int, got {type(start_frame).__name__}"
        )
    if type(end_frame) is not int:
        raise TypeError(
            f"cue presentation_end_frame must be an int, got {type(end_frame).__name__}"
        )
    if not 1 <= start_frame <= MAX_CAPTION_FRAME:
        raise ValueError(
            f"cue presentation_start_frame must be within [1, {MAX_CAPTION_FRAME}], got "
            f"{start_frame}"
        )
    if end_frame < start_frame:
        raise ValueError(
            f"cue presentation_end_frame {end_frame} precedes presentation_start_frame "
            f"{start_frame}"
        )
    start_ms = boundary_ms(start_frame - 1, fps)
    end_ms = boundary_ms(end_frame, fps)
    if end_ms <= start_ms:
        raise CaptionSerializationRefused(
            f"cue frames [{start_frame}, {end_frame}] derive the zero-length span "
            f"[{start_ms}, {end_ms}) at {fps} fps; the target formats require a cue's end "
            "to follow its start"
        )
    return start_ms, end_ms


def format_timestamp(ms: int, separator: str) -> str:
    """Return one derived millisecond as a fixed-width ``HH:MM:SS?mmm`` timestamp.

    Always the long form -- two-digit zero-padded hours, minutes and seconds and
    three-digit milliseconds -- by pure integer ``divmod``. The separator is the
    target format's decimal mark: a comma for SRT, a period for WebVTT.

    Raises:
        TypeError: If ``ms`` is not an exact ``int`` or ``separator`` not a str.
        ValueError: If the separator is not ``","`` or ``"."``.
        CaptionSerializationRefused: If ``ms`` is negative or at or beyond the
            frozen 100-hour representation rail.
    """
    if type(ms) is not int:
        raise TypeError(f"ms must be an int, got {type(ms).__name__}")
    if type(separator) is not str:
        raise TypeError(f"separator must be a str, got {type(separator).__name__}")
    if separator not in (",", "."):
        raise ValueError(f"separator must be ',' or '.', got {separator!r}")
    if ms < 0:
        raise CaptionSerializationRefused(f"a timestamp cannot be negative, got {ms} ms")
    if ms >= MAX_TIMESTAMP_MS:
        raise CaptionSerializationRefused(
            f"the derived timestamp {ms} ms is at or beyond the {MAX_TIMESTAMP_MS} ms "
            "representation rail; two-digit hours are the frozen width, a representation "
            "limit of the target file formats and never a re-validation of upstream truth"
        )
    hours, rest = divmod(ms, _MS_PER_HOUR)
    minutes, rest = divmod(rest, _MS_PER_MINUTE)
    seconds, millis = divmod(rest, _MS_PER_SECOND)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}"


def derive_cue_spans(caption_plan: object) -> tuple[tuple[int, int], ...]:
    """Return every cue's derived span for one validated caption plan, in plan order.

    Validates the plan through the locked Phase 32 schema first, then derives
    each span under the one policy and asserts the derived sequence is monotone:
    each cue's end follows its start strictly, and no cue's start precedes the
    previous cue's end. Both properties hold by construction for every
    gate-valid plan -- the assertions exist so a forged standalone document can
    never serialize an inverted or overlapping timeline.

    Raises:
        TypeError: If the plan has a wrongly typed value.
        ValueError: If the plan is not a valid Episode Caption Plan.
        CaptionSerializationRefused: If any derived span violates the target
            formats' ordering laws.
    """
    plan = validate_episode_caption_plan(caption_plan)
    clock = cast(dict[str, object], plan["clock"])
    fps = cast(int, clock["fps"])
    captions = cast(list[object], plan["captions"])

    spans: list[tuple[int, int]] = []
    previous_end_ms = 0
    for position, cue in enumerate(captions, start=1):
        start_ms, end_ms = cue_span_ms(cue, fps)
        if start_ms < previous_end_ms:
            raise CaptionSerializationRefused(
                f"cue {position} derives start {start_ms} ms before the previous cue's end "
                f"{previous_end_ms} ms; the target formats never rewind a timeline"
            )
        spans.append((start_ms, end_ms))
        previous_end_ms = end_ms
    return tuple(spans)


__all__ = ["boundary_ms", "cue_span_ms", "derive_cue_spans", "format_timestamp"]
