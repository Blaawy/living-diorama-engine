"""Episode Narration Plan format V1: the restatement contract.

A narration plan is presentation text bound to authoritative record identity. It
says, for every beat the story layer emphasised, one sentence restating that
beat, which record the sentence came from, and whether the directed episode
frames it. It asserts nothing about the world that the world did not already
assert about itself, and nothing about what the viewer sees that Phase 22 did
not already decide.

The document shape is exact at every level this module governs. A key that is
missing means the plan is incomplete; a key that is extra means it was written
by something this contract does not describe. Both are refused, never repaired.

This validator is deliberately self-contained: it proves everything the plan can
prove about itself, and nothing that needs the source documents. Whether the
plan's claims are true *of* the story plan, the shot plan and the render export
it names is proven by
:func:`living_diorama.narration.narration_cross_check.validate_narration_plan_against_sources`,
which takes those sources as arguments.
"""

from typing import Final, cast

from living_diorama.narration.narration_spec import (
    TEXT_SOURCE_MEMORY_FACT_SUMMARY,
    TEXT_SOURCES,
    UNSHOWN_REASONS,
    VISIBILITY_SHOWN,
    VISIBILITY_STATES,
    forbidden_wording_hit,
    text_source_for_kind,
)
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_identifier,
    require_text,
)
from living_diorama.story import BEAT_KINDS, EMPHASIS_LEVELS

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in.

Declared here rather than imported from the story layer for the same reason
Phase 21 declares its own: a shared alias is not worth a hole in a boundary.
"""

NARRATION_PLAN_FORMAT: Final = "living_diorama_episode_narration_plan"
"""The format tag every episode narration plan declares."""

NARRATION_SCHEMA_VERSION: Final = 1
"""The narration plan schema version this build reads and writes.

Independent from the story, cinematic, render and persistence schema versions.
The wording table in ``narration_spec`` is part of this version: changing a
template changes what a plan of this version says, so it is a reviewed version
change, never a quiet edit.
"""

SUPPORTED_STORY_SCHEMA_VERSION: Final = 1
SUPPORTED_SHOT_SCHEMA_VERSION: Final = 1
"""The upstream contract versions this build narrates."""

MODE_BASELINE: Final = "baseline"
MODE_TRANSITION: Final = "transition"
PLAN_MODES: Final = (MODE_BASELINE, MODE_TRANSITION)
"""A plan narrates either one export (baseline) or one transition."""

UNIT_ID_FORM: Final = "unit_%04d"
"""A narration unit identifier is positional and nothing else, so it is derivable."""

BEAT_ID_FORM: Final = "beat_%04d"
"""Phase 21's beat identifier form, restated so position can be checked here.

A unit sits at the position of the beat it restates, so the two identifiers are
derivable from one index. That single rule carries the whole V1 accounting
contract: one unit per beat, in beat order, none missing, none repeated, none
invented.
"""

SHOT_ID_FORM: Final = "shot_%04d"
"""Phase 22's shot identifier form, restated to check a citation's shape."""

TOP_LEVEL_KEYS: Final = frozenset({"accounting", "format", "schema_version", "source", "units"})
"""Exactly the top-level keys an episode narration plan carries."""

SOURCE_KEYS: Final = frozenset(
    {
        "current_export_sha256",
        "episode",
        "mode",
        "previous_episode",
        "shot_plan_sha256",
        "shot_schema_version",
        "story_plan_sha256",
        "story_schema_version",
    }
)
"""Exactly the keys binding a plan to the documents it narrates.

Three digests, because narration joins three documents that must be the same
episode's: the story plan it restates, the shot plan whose visibility it
reports, and the render export whose recorded sentences it carries. Naming an
episode is not enough -- a plan names the exact documents, and the cross-check
proves the three belong together.

There is deliberately no render manifest binding. Narration authoring is a
semantic layer: Phase 21 owns what mattered and Phase 22 owns what is framed,
and both are settled before a single pixel exists. A manifest is execution
proof, whose per-frame image identities may legitimately differ across two
renders of the same directed episode; binding narration identity to it would
tie a semantic document's stability to render execution for nothing it needs.
The manifest belongs to the later realization layer, which joins this plan to
the frames that were actually produced.
"""

UNIT_KEYS: Final = frozenset(
    {
        "beat_id",
        "emphasis",
        "end_frame",
        "fact_id",
        "kind",
        "shot_id",
        "start_frame",
        "subject_ids",
        "text",
        "text_source",
        "unit_id",
        "unshown_reason",
        "visibility",
    }
)
"""Exactly the keys a narration unit carries.

Every key is present on every unit, including the ones a given unit must leave
null. An absent key and a null key are different claims: null says "this layer
considered the question and the answer is nothing", while absent would leave a
reader guessing whether the writer knew the field existed.
"""

ACCOUNTING_KEYS: Final = frozenset({"beats_total", "units_shown", "units_unshown"})
"""Exactly the keys the accounting block carries.

The aggregate verdict, stated in a way a truncated plan cannot fake.
"""

EMPTY_RESULT_KIND: Final = "NO_EMPHASIZED_BEATS"
REASON_NOTHING_TO_EMPHASIZE: Final = "NOTHING_TO_EMPHASIZE"
"""Phase 21's empty-result beat and the only reason it can go unshown.

A beat that reports the emphasis policy selected nothing is never framed: there
is nothing for a camera to point at, and Phase 22 records it unshown for exactly
that reason.
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


def _validate_text(unit: dict[str, JsonValue], kind: str, description: str) -> None:
    """Verify the sentence is present, sourced honestly, and makes no banned claim."""
    text = require_text(unit.get("text"), f"{description} text")
    declared = _require_member(unit.get("text_source"), TEXT_SOURCES, f"{description} text_source")
    expected = text_source_for_kind(kind)
    if declared != expected:
        raise ValueError(
            f"{description} is a {kind} beat carrying text_source {declared!r}; that kind "
            f"is narrated from {expected!r} -- a carried summary and a composed sentence "
            "are different claims about where the wording came from"
        )
    hit = forbidden_wording_hit(text)
    if hit is not None:
        raise ValueError(
            f"{description} text uses {hit!r}, which this layer does not publish: a "
            "narration sentence asserts neither causation the evidence never proved nor "
            "visibility the shot plan never granted"
        )


def _validate_visibility(unit: dict[str, JsonValue], kind: str, description: str) -> str:
    """Verify the shown/unshown pairing contract, and return the state."""
    visibility = _require_member(
        unit.get("visibility"), VISIBILITY_STATES, f"{description} visibility"
    )
    if visibility == VISIBILITY_SHOWN:
        shot_id = require_identifier(unit.get("shot_id"), f"{description} shot_id")
        start = require_exact_int(unit.get("start_frame"), f"{description} start_frame")
        end = require_exact_int(unit.get("end_frame"), f"{description} end_frame")
        if end < start:
            raise ValueError(f"{description} ends at frame {end} before it starts at {start}")
        try:
            position = int(shot_id.removeprefix("shot_"))
        except ValueError:
            position = -1
        if position < 1 or shot_id != SHOT_ID_FORM % position:
            raise ValueError(
                f"{description} cites shot {shot_id!r}, which is not a Phase 22 shot "
                f"identifier of the form {SHOT_ID_FORM % 1!r}"
            )
        _require_null(
            unit.get("unshown_reason"),
            f"{description} unshown_reason",
            "a shown beat was not left unshown and carries no reason for having been",
        )
        return visibility

    _require_member(unit.get("unshown_reason"), UNSHOWN_REASONS, f"{description} unshown_reason")
    for field, because in (
        ("shot_id", "an unshown beat is framed by no shot"),
        ("start_frame", "an unshown beat occupies no frames"),
        ("end_frame", "an unshown beat occupies no frames"),
    ):
        _require_null(unit.get(field), f"{description} {field}", because)
    if kind == EMPTY_RESULT_KIND and unit["unshown_reason"] != REASON_NOTHING_TO_EMPHASIZE:
        raise ValueError(
            f"{description} reports that nothing was emphasized but goes unshown as "
            f"{unit['unshown_reason']!r}; that beat is unshown as "
            f"{REASON_NOTHING_TO_EMPHASIZE!r} -- there was nothing to point a camera at"
        )
    return visibility


def _validate_unit(value: object, description: str, position: int) -> str:
    """Verify one narration unit, and return its visibility state."""
    unit = _require_document(value, description)
    require_exact_keys(unit, UNIT_KEYS, description)

    unit_id = require_identifier(unit.get("unit_id"), f"{description} unit_id")
    expected_unit = UNIT_ID_FORM % position
    if unit_id != expected_unit:
        raise ValueError(
            f"{description} declares unit_id {unit_id!r} but sits at position {position}, "
            f"where the identifier is {expected_unit!r}; a unit id is positional, not a "
            "free label"
        )
    beat_id = require_identifier(unit.get("beat_id"), f"{description} beat_id")
    expected_beat = BEAT_ID_FORM % position
    if beat_id != expected_beat:
        raise ValueError(
            f"{description} restates beat {beat_id!r} but sits at position {position}, "
            f"where the story plan's beat is {expected_beat!r}; narration follows the "
            "story's own order, one unit per beat"
        )

    kind = _require_member(unit.get("kind"), BEAT_KINDS, f"{description} kind")
    _require_member(unit.get("emphasis"), EMPHASIS_LEVELS, f"{description} emphasis")

    subjects = _require_list(unit.get("subject_ids"), f"{description} subject_ids")
    identifiers: list[str] = []
    for index, subject in enumerate(subjects):
        identifiers.append(require_identifier(subject, f"{description} subject_ids[{index}]"))
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{description} repeats a subject id")
    if identifiers != sorted(identifiers):
        raise ValueError(f"{description} subject_ids must be sorted")
    if kind == EMPTY_RESULT_KIND and identifiers:
        raise ValueError(
            f"{description} reports that nothing was emphasized but names subjects "
            f"{identifiers}; it is a statement about the story layer's output, not about "
            "any entity"
        )

    fact_id = unit.get("fact_id")
    if text_source_for_kind(kind) == TEXT_SOURCE_MEMORY_FACT_SUMMARY:
        require_identifier(fact_id, f"{description} fact_id")
    else:
        _require_null(
            fact_id,
            f"{description} fact_id",
            "this beat's sentence is composed from the template table, so no memory fact wrote it",
        )

    _validate_text(unit, kind, description)
    return _validate_visibility(unit, kind, description)


def validate_episode_narration_plan(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Narration Plan V1 envelope, and return it.

    Checks the exact key sets at every governed level, the format tag and schema
    version, the source binding (episode, mode, the three digests, and the rule
    that only a baseline has no previous episode), and every unit: that its
    identifiers agree with its position, that its kind and emphasis come from
    Phase 21's closed vocabularies, that its subjects are sorted and unique,
    that its sentence is sourced the way its kind is narrated and makes no
    causal or visual claim, and that its visibility fields obey the shown /
    unshown pairing exactly.

    Two whole-document rules are enforced too, because they are what make the
    plan honest rather than merely well formed:

    * the empty-result beat is the whole plan or it is not true
    * the accounting block agrees with the units actually present

    Raises:
        TypeError: If any value has the wrong Python type.
        ValueError: If any key set, vocabulary member, ordering, pairing or
            internal agreement is violated.
    """
    document = _require_document(value, "episode narration plan")
    require_exact_keys(document, TOP_LEVEL_KEYS, "episode narration plan")

    tag = require_text(document.get("format"), "episode narration plan format")
    if tag != NARRATION_PLAN_FORMAT:
        raise ValueError(
            f"episode narration plan declares format {tag!r}; this build reads "
            f"{NARRATION_PLAN_FORMAT!r} only"
        )
    version = require_exact_int(
        document.get("schema_version"), "episode narration plan schema_version"
    )
    if version != NARRATION_SCHEMA_VERSION:
        raise ValueError(
            f"episode narration plan declares unsupported schema version {version}; "
            f"this build reads version {NARRATION_SCHEMA_VERSION} only"
        )

    source = _require_document(document.get("source"), "episode narration plan source")
    require_exact_keys(source, SOURCE_KEYS, "episode narration plan source")
    mode = _require_member(source.get("mode"), PLAN_MODES, "episode narration plan source mode")
    episode = require_exact_int(source.get("episode"), "episode narration plan source episode")
    story_version = require_exact_int(
        source.get("story_schema_version"), "episode narration plan source story_schema_version"
    )
    if story_version != SUPPORTED_STORY_SCHEMA_VERSION:
        raise ValueError(
            f"episode narration plan was derived from story schema version {story_version}; "
            f"this build narrates version {SUPPORTED_STORY_SCHEMA_VERSION} only"
        )
    shot_version = require_exact_int(
        source.get("shot_schema_version"), "episode narration plan source shot_schema_version"
    )
    if shot_version != SUPPORTED_SHOT_SCHEMA_VERSION:
        raise ValueError(
            f"episode narration plan was derived from shot schema version {shot_version}; "
            f"this build narrates version {SUPPORTED_SHOT_SCHEMA_VERSION} only"
        )
    for field in ("current_export_sha256", "shot_plan_sha256", "story_plan_sha256"):
        require_hash_hex(source.get(field), f"episode narration plan source {field}")

    previous = source.get("previous_episode")
    if mode == MODE_BASELINE:
        _require_null(
            previous,
            "episode narration plan source previous_episode",
            "a baseline narrates one export and follows no episode",
        )
        if episode != 0:
            raise ValueError(
                f"episode narration plan is baseline mode but describes episode {episode}; "
                "a baseline describes episode 0 only"
            )
    else:
        previous_episode = require_exact_int(
            previous, "episode narration plan source previous_episode"
        )
        if episode != previous_episode + 1:
            raise ValueError(
                f"episode narration plan binds episode {previous_episode} then episode "
                f"{episode}; a transition joins consecutive episodes"
            )

    units = _require_list(document.get("units"), "episode narration plan units")
    if not units:
        raise ValueError(
            "episode narration plan carries no units; a story that emphasised nothing is "
            f"still narrated, by the unit restating its {EMPTY_RESULT_KIND} beat"
        )

    shown = 0
    unshown = 0
    for position, unit in enumerate(units, start=1):
        state = _validate_unit(unit, f"episode narration plan units[{position - 1}]", position)
        if state == VISIBILITY_SHOWN:
            shown += 1
        else:
            unshown += 1

    kinds = [cast(str, cast(dict[str, JsonValue], unit)["kind"]) for unit in units]
    if EMPTY_RESULT_KIND in kinds and len(kinds) > 1:
        others = sorted(set(kinds) - {EMPTY_RESULT_KIND})
        raise ValueError(
            f"episode narration plan restates a {EMPTY_RESULT_KIND} beat while also "
            f"carrying {others}; the empty result is the whole story or it is not true"
        )

    accounting = _require_document(document.get("accounting"), "episode narration plan accounting")
    require_exact_keys(accounting, ACCOUNTING_KEYS, "episode narration plan accounting")
    declared = {
        field: require_exact_int(
            accounting.get(field), f"episode narration plan accounting {field}"
        )
        for field in sorted(ACCOUNTING_KEYS)
    }
    measured = {
        "beats_total": len(units),
        "units_shown": shown,
        "units_unshown": unshown,
    }
    if declared != measured:
        raise ValueError(
            f"episode narration plan declares accounting {declared} but carries {measured}; "
            "every beat is narrated exactly once, and the verdict is measured from the "
            "units present rather than asserted beside them"
        )
    if declared["units_shown"] + declared["units_unshown"] != declared["beats_total"]:
        raise ValueError(
            f"episode narration plan accounts for {declared['units_shown']} shown and "
            f"{declared['units_unshown']} unshown units against {declared['beats_total']} "
            "beats; every narrated beat is in exactly one visibility state"
        )

    return document
