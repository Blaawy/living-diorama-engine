"""Episode Caption Plan format V1: locked wording made legible on the presentation clock.

A caption plan says, for a finished language realization and the
presentation plan whose windows already name it, for how many presentation
frames each locked realized sentence is legible -- one cue per narration
unit, carrying that sentence's exact string value. It asserts nothing about
audio, nothing about measured speech, and nothing about how a viewer's
device renders text -- those live in other layers, or nowhere at all.

The document shape is exact at every level this module governs. A key that
is missing means the plan is incomplete; a key that is extra means it was
written by something this contract does not describe. Both are refused,
never repaired.

This validator is deliberately self-contained: it proves everything the
plan can prove about itself, including that its cues never overlap and
always follow narration order, and that its own accounting closes on the
records present. It cannot prove a cue's frames are true of an actual Phase
27 window, or that its carried text is true of an actual Phase 26 sentence:
those facts are proven by
:func:`living_diorama.caption.caption_cross_check.validate_episode_caption_plan_against_sources`,
which takes the bound sources as arguments.
"""

from typing import Final, cast

from living_diorama.caption.caption_spec import (
    CAPTION_ID_FORM,
    CAPTION_PLAN_FORMAT,
    CAPTION_POLICY_V1,
    CAPTION_SCHEMA_VERSION,
    MAX_CAPTION_FRAME,
)
from living_diorama.language_realization.realization_spec import REALIZATION_ID_FORM
from living_diorama.narration.narration_schema_v1 import MODE_BASELINE, PLAN_MODES, UNIT_ID_FORM
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_identifier,
    require_text,
)
from living_diorama.presentation.presentation_spec import WINDOW_ID_FORM

SUPPORTED_PRESENTATION_SCHEMA_VERSION: Final = 1
SUPPORTED_REALIZATION_SCHEMA_VERSION: Final = 1
"""The upstream contract versions this build speaks."""

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in.

Declared here rather than imported from an upstream layer for the same
reason every locked phase declares its own: a shared alias is not worth a
hole in a boundary.
"""

TOP_LEVEL_KEYS: Final = frozenset(
    {"accounting", "captions", "clock", "format", "policy", "schema_version", "source"}
)
"""Exactly the top-level keys an episode caption plan carries."""

SOURCE_KEYS: Final = frozenset(
    {
        "episode",
        "mode",
        "previous_episode",
        "presentation_plan_sha256",
        "presentation_schema_version",
        "realization_plan_sha256",
        "realization_schema_version",
    }
)
"""Exactly the keys binding a plan to the two documents it presents.

Byte-for-byte Phase 28's own seven source keys: the same two bound
documents, the same reasoning. The delivery plan, narration plan, shot
plan, story plan and render export are never bound here; every one of
those relationships is proven by the reused Phase 27 gate this plan's own
cross-check runs in full.
"""

CLOCK_KEYS: Final = frozenset({"fps", "presentation_frames_total"})
"""Exactly the keys the restated, gate-verified clock block carries."""

CAPTION_KEYS: Final = frozenset(
    {
        "caption_id",
        "caption_text",
        "presentation_end_frame",
        "presentation_start_frame",
        "realization_id",
        "unit_id",
        "window_id",
    }
)
"""Exactly the keys one caption cue carries.

Deliberately no semantic frames, no dwell, no segment citation, no shot
citation, no speech reference, no sample offset, no duration in seconds,
no line count, no character count and no style: a cue names its unit by
identity, states the frames on which it is legible, and carries the
sentence.
"""

ACCOUNTING_KEYS: Final = frozenset(
    {"caption_frames_total", "captions_total", "uncaptioned_frames_total"}
)
"""Exactly the keys the accounting block carries.

The structural mirror of Phase 30's own three: the aggregate verdict,
stated in a way a truncated plan cannot fake, with ``uncaptioned_frames_total``
never a record of its own -- only the structural complement of the frames
that are captioned.
"""


def _require_document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    for key in value:
        if type(key) is not str:
            raise TypeError(f"{description} keys must be str, got {type(key).__name__}")
    return cast(dict[str, JsonValue], value)


def _require_list(value: object, description: str) -> list[JsonValue]:
    if type(value) is not list:
        raise TypeError(f"{description} must be a list, got {type(value).__name__}")
    return cast(list[JsonValue], value)


def _require_member(value: object, allowed: tuple[str, ...], description: str) -> str:
    text = require_text(value, description)
    if text not in allowed:
        raise ValueError(f"{description} is {text!r}; expected one of {list(allowed)}")
    return text


def _require_null(value: object, description: str, because: str) -> None:
    if value is not None:
        raise ValueError(f"{description} is {value!r}, but {because}")


def _require_presentation_frame(value: object, description: str) -> int:
    """Return the value if it is a valid presentation-clock coordinate, else raise.

    Bounded by this layer's own ``MAX_CAPTION_FRAME`` rail -- never by Phase
    27's ``MAX_PRESENTATION_FRAME``, which rails a different document.
    """
    number = require_exact_int(value, description)
    if not 1 <= number <= MAX_CAPTION_FRAME:
        raise ValueError(f"{description} must be within [1, {MAX_CAPTION_FRAME}], got {number}")
    return number


def _validate_clock(value: object) -> dict[str, JsonValue]:
    """Verify the restated clock block."""
    description = "caption plan clock"
    clock = _require_document(value, description)
    require_exact_keys(clock, CLOCK_KEYS, description)

    fps = require_exact_int(clock.get("fps"), f"{description} fps")
    if fps < 1:
        raise ValueError(f"{description} fps must be >= 1, got {fps}")
    presentation_frames_total = _require_presentation_frame(
        clock.get("presentation_frames_total"), f"{description} presentation_frames_total"
    )
    return {**clock, "presentation_frames_total": presentation_frames_total}


def _validate_caption(
    value: object,
    description: str,
    position: int,
    *,
    presentation_frames_total: int,
    previous_end_frame: int,
) -> tuple[int, int]:
    """Verify one caption cue, and return ``(presentation_start_frame, presentation_end_frame)``."""
    record = _require_document(value, description)
    require_exact_keys(record, CAPTION_KEYS, description)

    caption_id = require_identifier(record.get("caption_id"), f"{description} caption_id")
    expected_caption = CAPTION_ID_FORM % position
    if caption_id != expected_caption:
        raise ValueError(
            f"{description} declares caption_id {caption_id!r} but sits at position "
            f"{position}, where the identifier is {expected_caption!r}; a caption id is "
            "positional, not a free label"
        )
    unit_id = require_identifier(record.get("unit_id"), f"{description} unit_id")
    expected_unit = UNIT_ID_FORM % position
    if unit_id != expected_unit:
        raise ValueError(
            f"{description} captions unit {unit_id!r} but sits at position {position}, where "
            f"the narration plan's unit is {expected_unit!r}"
        )
    realization_id = require_identifier(
        record.get("realization_id"), f"{description} realization_id"
    )
    expected_realization = REALIZATION_ID_FORM % position
    if realization_id != expected_realization:
        raise ValueError(
            f"{description} names realization {realization_id!r} but sits at position "
            f"{position}, where the realization plan's record is {expected_realization!r}"
        )
    window_id = require_identifier(record.get("window_id"), f"{description} window_id")
    expected_window = WINDOW_ID_FORM % position
    if window_id != expected_window:
        raise ValueError(
            f"{description} names window {window_id!r} but sits at position {position}, where "
            f"the presentation plan's window is {expected_window!r}"
        )

    start_frame = _require_presentation_frame(
        record.get("presentation_start_frame"), f"{description} presentation_start_frame"
    )
    end_frame = _require_presentation_frame(
        record.get("presentation_end_frame"), f"{description} presentation_end_frame"
    )
    if end_frame < start_frame:
        raise ValueError(
            f"{description} presentation_end_frame {end_frame} precedes "
            f"presentation_start_frame {start_frame}"
        )
    if end_frame > presentation_frames_total:
        raise ValueError(
            f"{description} presentation_end_frame {end_frame} exceeds the clock's own "
            f"{presentation_frames_total} presentation_frames_total"
        )
    if start_frame <= previous_end_frame:
        raise ValueError(
            f"{description} presentation_start_frame {start_frame} does not follow the "
            f"previous cue's end frame {previous_end_frame}; cues never overlap and always "
            "follow narration order"
        )

    # Standalone validation is intentionally minimal: require_text only.
    # Truth about the sentence is proven by exact equality against the
    # sealed Phase 26 plan in the cross-check -- validity is not truthfulness.
    require_text(record.get("caption_text"), f"{description} caption_text")

    return start_frame, end_frame


def validate_episode_caption_plan(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Caption Plan V1 envelope, and return it.

    This validator is deliberately self-contained: it proves everything the
    plan can prove about itself, and nothing that needs the two bound
    sources. See the module docstring for what it cannot prove and which
    function proves those facts instead.

    Raises:
        TypeError: If any value has the wrong exact type.
        ValueError: If any key set, vocabulary member, ordering, bound or
            internal agreement is violated.
    """
    document = _require_document(value, "caption plan")
    require_exact_keys(document, TOP_LEVEL_KEYS, "caption plan")

    tag = require_text(document.get("format"), "caption plan format")
    if tag != CAPTION_PLAN_FORMAT:
        raise ValueError(
            f"caption plan declares format {tag!r}; this build reads {CAPTION_PLAN_FORMAT!r} only"
        )
    version = require_exact_int(document.get("schema_version"), "caption plan schema_version")
    if version != CAPTION_SCHEMA_VERSION:
        raise ValueError(
            f"caption plan declares unsupported schema version {version}; this build reads "
            f"version {CAPTION_SCHEMA_VERSION} only"
        )
    policy = require_text(document.get("policy"), "caption plan policy")
    if policy != CAPTION_POLICY_V1:
        raise ValueError(
            f"caption plan declares policy {policy!r}; this build derives and validates "
            f"{CAPTION_POLICY_V1!r} only"
        )

    source = _require_document(document.get("source"), "caption plan source")
    require_exact_keys(source, SOURCE_KEYS, "caption plan source")
    mode = _require_member(source.get("mode"), PLAN_MODES, "caption plan source mode")
    episode = require_exact_int(source.get("episode"), "caption plan source episode")

    presentation_version = require_exact_int(
        source.get("presentation_schema_version"), "caption plan source presentation_schema_version"
    )
    if presentation_version != SUPPORTED_PRESENTATION_SCHEMA_VERSION:
        raise ValueError(
            f"caption plan was derived from presentation schema version {presentation_version}; "
            f"this build speaks version {SUPPORTED_PRESENTATION_SCHEMA_VERSION} only"
        )
    realization_version = require_exact_int(
        source.get("realization_schema_version"), "caption plan source realization_schema_version"
    )
    if realization_version != SUPPORTED_REALIZATION_SCHEMA_VERSION:
        raise ValueError(
            f"caption plan was derived from realization schema version {realization_version}; "
            f"this build speaks version {SUPPORTED_REALIZATION_SCHEMA_VERSION} only"
        )
    for field in ("presentation_plan_sha256", "realization_plan_sha256"):
        require_hash_hex(source.get(field), f"caption plan source {field}")

    previous = source.get("previous_episode")
    if mode == MODE_BASELINE:
        _require_null(
            previous,
            "caption plan source previous_episode",
            "a baseline plan captions one export's realization and follows no episode",
        )
        if episode != 0:
            raise ValueError(
                f"caption plan source declares mode 'baseline' with episode {episode}; a "
                "baseline is always episode 0"
            )
    else:
        previous_episode = require_exact_int(previous, "caption plan source previous_episode")
        if episode != previous_episode + 1:
            raise ValueError(
                f"caption plan source declares episode {episode} following {previous_episode}; "
                "a transition's episode always directly follows its previous episode"
            )

    clock = _validate_clock(document.get("clock"))
    presentation_frames_total = cast(int, clock["presentation_frames_total"])

    captions = _require_list(document.get("captions"), "caption plan captions")
    if not captions:
        raise ValueError("caption plan captions must not be empty")

    caption_frames_total = 0
    previous_end_frame = 0
    for position, record in enumerate(captions, start=1):
        start_frame, end_frame = _validate_caption(
            record,
            f"caption plan captions[{position - 1}]",
            position,
            presentation_frames_total=presentation_frames_total,
            previous_end_frame=previous_end_frame,
        )
        caption_frames_total += end_frame - start_frame + 1
        previous_end_frame = end_frame

    accounting = _require_document(document.get("accounting"), "caption plan accounting")
    require_exact_keys(accounting, ACCOUNTING_KEYS, "caption plan accounting")
    captions_total = require_exact_int(
        accounting.get("captions_total"), "caption plan accounting captions_total"
    )
    if captions_total != len(captions):
        raise ValueError(
            f"caption plan accounting captions_total is {captions_total}, but the plan carries "
            f"{len(captions)} caption records"
        )
    recorded_caption_frames = require_exact_int(
        accounting.get("caption_frames_total"), "caption plan accounting caption_frames_total"
    )
    if recorded_caption_frames != caption_frames_total:
        raise ValueError(
            f"caption plan accounting caption_frames_total is {recorded_caption_frames}, but "
            f"the records present sum to {caption_frames_total}"
        )
    uncaptioned = require_exact_int(
        accounting.get("uncaptioned_frames_total"),
        "caption plan accounting uncaptioned_frames_total",
    )
    expected_uncaptioned = presentation_frames_total - caption_frames_total
    if uncaptioned != expected_uncaptioned:
        raise ValueError(
            f"caption plan accounting uncaptioned_frames_total is {uncaptioned}, but "
            f"{presentation_frames_total} total frames minus {caption_frames_total} captioned "
            f"frames is {expected_uncaptioned}"
        )

    return document


__all__ = [
    "ACCOUNTING_KEYS",
    "CAPTION_KEYS",
    "CLOCK_KEYS",
    "SOURCE_KEYS",
    "SUPPORTED_PRESENTATION_SCHEMA_VERSION",
    "SUPPORTED_REALIZATION_SCHEMA_VERSION",
    "TOP_LEVEL_KEYS",
    "JsonValue",
    "validate_episode_caption_plan",
]
