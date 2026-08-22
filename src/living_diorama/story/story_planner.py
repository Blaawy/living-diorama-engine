"""Deriving an Episode Story Plan from verified render exports.

The derivation is a pure function of its inputs. It reads no clock, draws no
randomness, consults no filesystem path, and depends on no iteration order that
Python is free to vary. The same two exports always produce the same bytes.

What it decides is emphasis: which authoritative records downstream presentation
should pay attention to, and in what order. What it never decides is truth. Every
beat carries structural references back to the event index or fact identifier it
came from, so a reviewer can check any claim against the export that produced it.

Prose is never read. A memory fact's ``summary`` is free-form text written for
humans; this module never inspects it and never branches on it.
"""

from typing import Final, cast

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.render.render_schema_v1 import (
    RENDER_SCHEMA_VERSION,
    validate_render_export,
)
from living_diorama.story.story_facts import (
    require_fact_shape,
    require_new_fact_episode,
    require_subject_ids,
    resolve_source_event,
)
from living_diorama.story.story_lineage import (
    require_consecutive_exports,
    require_memory_progression,
)
from living_diorama.story.story_schema_v1 import (
    EVIDENCE_EVENT,
    EVIDENCE_MEMORY_FACT,
    MODE_BASELINE,
    MODE_TRANSITION,
    STORY_PLAN_FORMAT,
    STORY_SCHEMA_VERSION,
    UNCLASSIFIED_EVENT,
    UNCLASSIFIED_FACT,
    JsonValue,
    validate_episode_story_plan,
)
from living_diorama.story.story_spec import (
    BEAT_NO_EMPHASIZED_BEATS,
    EMPHASIS_BACKGROUND,
    EMPHASIS_ORDER,
    POLICY_FIRST_PER_SUBJECT,
    REASON_NO_BEATS_DERIVED,
    REASON_REPEAT_SUPPRESSED,
    REASON_UNKNOWN_EVENT_TYPE,
    REASON_UNKNOWN_FACT_TYPE,
    classify_event,
    classify_fact,
    event_exclusion_reason,
)

BEAT_ID_TEMPLATE: Final = "beat_%04d"
"""Beat identifiers are positional, assigned after the final ordering is fixed."""


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def _events(export: dict[str, JsonValue]) -> list[JsonValue]:
    entries = export.get("events")
    if type(entries) is not list:
        raise TypeError("render export events must be a list")
    return entries


def _facts(export: dict[str, JsonValue]) -> list[JsonValue]:
    memory = _document(export.get("memory"), "render export memory")
    entries = memory.get("facts")
    if type(entries) is not list:
        raise TypeError("render export memory facts must be a list")
    return entries


def _export_binding(export: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Bind a plan to the exact export document it read.

    The digest is taken over the export's own canonical bytes, so the binding
    survives the file being moved or renamed and breaks if a single byte of the
    document changes.
    """
    source = _document(export.get("source"), "render export source")
    return {
        "document_sha256": sha256_hex(dumps_canonical(export, "render export")),
        "episode": source["episode"],
        "event_count": source["event_count"],
        "parent_state_hash": source["parent_state_hash"],
        "state_hash": source["state_hash"],
        "tick": source["tick"],
    }


def _event_evidence(index: int, event: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Reference an event by its canonical array position.

    The index *is* the reference. Render Export V1 defines the events array as
    append-order history, so position carries meaning that a sort would destroy;
    two events sharing a tick are still distinguishable by where they sit.
    """
    return {
        "index": index,
        "kind": EVIDENCE_EVENT,
        "source_id": event["source_id"],
        "tick": event["tick"],
        "type": event["type"],
    }


def _fact_evidence(fact: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "episode": fact["episode"],
        "fact_id": fact["fact_id"],
        "fact_type": fact["fact_type"],
        "kind": EVIDENCE_MEMORY_FACT,
        "source_id": fact["source_id"],
        "tick": fact["tick"],
    }


def _count(bucket: dict[str, dict[str, JsonValue]], key: str, reason: str) -> None:
    entry = bucket.get(key)
    if entry is None:
        bucket[key] = {"count": 1, "reason_code": reason}
        return
    entry["count"] = cast(int, entry["count"]) + 1


def _order_key(beat: dict[str, JsonValue]) -> tuple[int, int, int, str, str]:
    """Total order over beats: emphasis, then history position, then names.

    Every component is derived from the beat itself, so the ordering is stable
    under any input iteration order and there are no ties left to chance.
    """
    emphasis = EMPHASIS_ORDER[cast(str, beat["emphasis"])]
    evidence = cast(list[dict[str, JsonValue]], beat["evidence"])
    ticks = [cast(int, entry["tick"]) for entry in evidence]
    indices = [
        cast(int, entry["index"]) for entry in evidence if entry["kind"] == EVIDENCE_EVENT
    ]
    subjects = cast(list[str], beat["subject_ids"])
    return (
        emphasis,
        min(ticks) if ticks else 0,
        min(indices) if indices else 0,
        cast(str, beat["kind"]),
        subjects[0] if subjects else "",
    )


def build_episode_story_plan_document(
    current_export: object, previous_export: object | None = None
) -> dict[str, JsonValue]:
    """Return the Episode Story Plan document for one episode or one transition.

    With ``previous_export`` omitted the plan is a baseline, and a baseline
    describes **episode 0 only**. Durable memory is cumulative, so a later
    episode carries every earlier episode's facts; treating those as new would
    report old history as if it had just happened, and is refused.

    With a previous export supplied the pair is proven consecutive first, and
    only genuinely new memory facts contribute beats.

    Args:
        current_export: The render export being described.
        previous_export: The episode before it, for a transition plan.

    Returns:
        A validated Episode Story Plan V1 document.

    Raises:
        TypeError: If either document has the wrong shape.
        ValueError: If either fails the Render Export V1 contract, if a
            baseline is requested for an episode after 0, if the pair is not
            consecutive canonical history, if durable memory did not legally
            progress between them, or if a memory fact's source event reference
            does not resolve and agree with the fact.
    """
    if previous_export is None:
        current = cast(dict[str, JsonValue], validate_render_export(current_export))
        current_source = _document(current.get("source"), "render export source")
        episode = cast(int, current_source["episode"])
        if episode != 0:
            raise ValueError(
                f"a baseline plan describes episode 0 only, but this export is "
                f"episode {episode}; supply the previous export instead. Durable "
                "memory is cumulative, so treating a later episode's carried "
                "history as new would report facts from earlier episodes as if "
                "they had just happened"
            )
        previous: dict[str, JsonValue] | None = None
        new_facts = require_memory_progression([], _facts(current))
        mode = MODE_BASELINE
    else:
        previous, current = require_consecutive_exports(previous_export, current_export)
        new_facts = require_memory_progression(_facts(previous), _facts(current))
        mode = MODE_TRANSITION

    events = _events(current)
    beats: list[dict[str, JsonValue]] = []
    unclassified: list[dict[str, JsonValue]] = []
    excluded: dict[str, dict[str, JsonValue]] = {}
    absorbed: set[int] = set()

    # Durable facts first: they are the strongest evidence the engine offers,
    # and a fact that names its source event absorbs that event's beat rather
    # than letting the same moment be reported twice.
    current_episode = cast(int, _document(current["source"], "source")["episode"])
    for position, fact in enumerate(new_facts):
        label = f"memory fact[{position}]"
        # Structural validation comes first, for every new fact without
        # exception. Doing it after classification would let an unrecognised
        # fact type walk past these checks simply by being unrecognised, and
        # "we do not know what this is" is not a reason to stop asking whether
        # it is well formed.
        record = require_fact_shape(fact, label)
        require_new_fact_episode(record, current_episode, label)
        index, event = resolve_source_event(record, events, label)

        fact_type = cast(str, record["fact_type"])
        fact_rule = classify_fact(fact_type)
        if fact_rule is None:
            # Proven sound, still unrecognised. It degrades neutrally, and its
            # source event is left to the event pass rather than absorbed --
            # nothing absorbs an event on behalf of a beat that does not exist.
            unclassified.append(
                {
                    "kind": UNCLASSIFIED_FACT,
                    "reason_code": REASON_UNKNOWN_FACT_TYPE,
                    "type": fact_type,
                }
            )
            continue
        kind, emphasis, reason = fact_rule
        evidence: list[dict[str, JsonValue]] = [
            _fact_evidence(record),
            _event_evidence(index, event),
        ]
        if classify_event(cast(str, event["type"])) is not None:
            absorbed.add(index)
        beats.append(
            {
                "emphasis": emphasis,
                "evidence": cast(JsonValue, evidence),
                "kind": kind,
                "reason_code": reason,
                "subject_ids": cast(
                    JsonValue,
                    require_subject_ids(record["subject_ids"], f"{label} subject_ids"),
                ),
            }
        )

    # Then the event log, in its canonical append order. The array is never
    # sorted or filtered in place; only the derived beat list is ordered.
    seen_first: set[tuple[str, str]] = set()
    for index, entry in enumerate(events):
        event = _document(entry, f"event[{index}]")
        event_type = event.get("type")
        if type(event_type) is not str:
            raise TypeError(f"event[{index}] type must be a str")
        event_rule = classify_event(event_type)
        if event_rule is None:
            reason = event_exclusion_reason(event_type)
            if reason == REASON_UNKNOWN_EVENT_TYPE:
                unclassified.append(
                    {
                        "kind": UNCLASSIFIED_EVENT,
                        "reason_code": REASON_UNKNOWN_EVENT_TYPE,
                        "type": event_type,
                    }
                )
            else:
                _count(excluded, event_type, reason)
            continue
        if index in absorbed:
            # Already cited as evidence on the fact's beat. It is represented,
            # so it is not excluded -- counting it in both buckets would make
            # the plan's own arithmetic wrong.
            continue
        kind, emphasis, reason, policy = event_rule
        source_id = event.get("source_id")
        if type(source_id) is not str:
            raise TypeError(f"event[{index}] source_id must be a str")
        if policy == POLICY_FIRST_PER_SUBJECT:
            token = (event_type, source_id)
            if token in seen_first:
                _count(excluded, event_type, REASON_REPEAT_SUPPRESSED)
                continue
            seen_first.add(token)
        beats.append(
            {
                "emphasis": emphasis,
                "evidence": cast(JsonValue, [_event_evidence(index, event)]),
                "kind": kind,
                "reason_code": reason,
                "subject_ids": cast(JsonValue, [source_id]),
            }
        )

    # Nothing was selected for emphasis. This says only that -- it is a
    # statement about this layer's own output, never a claim that the world was
    # still. Hundreds of authoritative telemetry events may have been excluded
    # above, and the excluded tally reports exactly how many.
    if not beats:
        beats.append(
            {
                "emphasis": EMPHASIS_BACKGROUND,
                "evidence": cast(JsonValue, []),
                "kind": BEAT_NO_EMPHASIZED_BEATS,
                "reason_code": REASON_NO_BEATS_DERIVED,
                "subject_ids": cast(JsonValue, []),
            }
        )

    beats.sort(key=_order_key)
    for position, beat in enumerate(beats):
        beat["beat_id"] = BEAT_ID_TEMPLATE % (position + 1)
        beat["rank"] = position + 1

    document: dict[str, JsonValue] = {
        "beats": cast(JsonValue, beats),
        "excluded": cast(JsonValue, excluded),
        "format": STORY_PLAN_FORMAT,
        "schema_version": STORY_SCHEMA_VERSION,
        "source": cast(
            JsonValue,
            {
                "current": cast(JsonValue, _export_binding(current)),
                "mode": mode,
                "previous": (
                    cast(JsonValue, _export_binding(previous))
                    if previous is not None
                    else None
                ),
                "render_schema_version": RENDER_SCHEMA_VERSION,
            },
        ),
        "unclassified": cast(JsonValue, unclassified),
    }
    return validate_episode_story_plan(document)


def build_episode_story_plan_bytes(
    current_export: object, previous_export: object | None = None
) -> bytes:
    """Return the canonical Episode Story Plan bytes for the given exports.

    The returned bytes are the one canonical encoding of the plan: sorted keys,
    tight separators, no non-finite floats, and exactly one trailing newline.
    """
    document = build_episode_story_plan_document(current_export, previous_export)
    return dumps_canonical(document, "episode story plan")
