"""Episode Story Plan format V1: the emphasis contract.

A story plan is presentation metadata. It says which authoritative things
downstream presentation should pay attention to, and it proves, for every one of
them, exactly which authoritative record it came from. It asserts nothing about
the world that the world did not already assert about itself.

The document shape is exact at every level this module governs. A key that is
missing means the plan is incomplete; a key that is extra means it was written
by something this contract does not describe. Both are refused, never repaired --
the same discipline the render and save schemas hold.

This module imports only the standard library and the ``living_diorama``
persistence validation vocabulary. Story is a read-only consumer of a verified
render export and must never reach into live simulation.
"""

from typing import Final, cast

from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_identifier,
    require_text,
)
from living_diorama.render.render_schema_v1 import RENDER_SCHEMA_VERSION
from living_diorama.story.story_spec import (
    BEAT_EMPHASIS_LEVELS,
    BEAT_EVENT_TYPES,
    BEAT_FACT_TYPES,
    BEAT_KINDS,
    BEAT_NO_EMPHASIZED_BEATS,
    BEAT_REASON_CODES,
    EMPHASIS_LEVELS,
    EMPHASIS_ORDER,
    FACT_SOURCE_EVENT_TYPES,
    KNOWN_EVENT_TYPES,
    KNOWN_FACT_TYPES,
    REASON_CODES,
    REASON_EVENT_TYPE_RULE,
    REASON_MEMORY_FACT_NEW,
    REASON_UNKNOWN_EVENT_TYPE,
    REASON_UNKNOWN_FACT_TYPE,
    allowed_exclusion_reasons,
)

BEAT_ID_FORM: Final = "beat_%04d"
"""A beat identifier is positional and nothing else, so it is derivable."""

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in.

Declared here rather than imported from ``living_diorama.events``: the story
layer is forbidden to reach into the event package, and a shared type alias is
not worth a hole in that boundary.
"""

STORY_PLAN_FORMAT: Final = "living_diorama_episode_story_plan"
"""The format tag every episode story plan declares."""

STORY_SCHEMA_VERSION: Final = 1
"""The story plan schema version this build reads and writes.

Independent from the render and persistence schema versions: the three formats
evolve on their own timelines and must never be conflated.
"""

MODE_BASELINE: Final = "baseline"
MODE_TRANSITION: Final = "transition"
PLAN_MODES: Final = (MODE_BASELINE, MODE_TRANSITION)
"""A plan is derived either from one export (baseline) or from a verified pair."""

TOP_LEVEL_KEYS: Final = frozenset(
    {"beats", "excluded", "format", "schema_version", "source", "unclassified"}
)
"""Exactly the top-level keys an episode story plan carries."""

SOURCE_KEYS: Final = frozenset(
    {
        "current",
        "mode",
        "previous",
        "render_schema_version",
    }
)
"""Exactly the keys the source binding section carries."""

EXPORT_BINDING_KEYS: Final = frozenset(
    {"document_sha256", "episode", "event_count", "parent_state_hash", "state_hash", "tick"}
)
"""Exactly the keys binding one render export to this plan.

``document_sha256`` is the digest of the export's own canonical bytes, so a plan
names not merely the episode it describes but the exact document it read.
"""

BEAT_KEYS: Final = frozenset(
    {"beat_id", "emphasis", "evidence", "kind", "rank", "reason_code", "subject_ids"}
)
"""Exactly the keys a story beat carries."""

EVENT_EVIDENCE_KEYS: Final = frozenset({"index", "kind", "source_id", "tick", "type"})
"""Exactly the keys an event evidence reference carries."""

FACT_EVIDENCE_KEYS: Final = frozenset(
    {"episode", "fact_id", "fact_type", "kind", "source_id", "tick"}
)
"""Exactly the keys a memory fact evidence reference carries."""

UNCLASSIFIED_KEYS: Final = frozenset({"kind", "reason_code", "type"})
"""Exactly the keys an unclassified entry carries."""

EXCLUDED_KEYS: Final = frozenset({"count", "reason_code"})
"""Exactly the keys an exclusion tally carries.

An excluded type is reported with the reason it was set aside, never as a bare
number: a reviewer can see both how much was left out and on what grounds.
"""

EVIDENCE_EVENT: Final = "event"
EVIDENCE_MEMORY_FACT: Final = "memory_fact"
EVIDENCE_KINDS: Final = (EVIDENCE_EVENT, EVIDENCE_MEMORY_FACT)
"""Every evidence kind a beat may cite. Both are structural references."""

UNCLASSIFIED_EVENT: Final = "event"
UNCLASSIFIED_FACT: Final = "memory_fact"


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


def _validate_export_binding(value: object, description: str) -> None:
    binding = _require_document(value, description)
    require_exact_keys(binding, EXPORT_BINDING_KEYS, description)
    episode = require_exact_int(binding.get("episode"), f"{description} episode")
    require_exact_int(binding.get("tick"), f"{description} tick")
    require_exact_int(binding.get("event_count"), f"{description} event_count")
    require_hash_hex(binding.get("state_hash"), f"{description} state_hash")
    require_hash_hex(binding.get("document_sha256"), f"{description} document_sha256")
    parent = binding.get("parent_state_hash")
    if parent is None:
        if episode != 0:
            raise ValueError(
                f"{description} carries no parent_state_hash but is episode {episode}; "
                "only episode 0 has no parent"
            )
    else:
        require_hash_hex(parent, f"{description} parent_state_hash")
        if episode == 0:
            raise ValueError(f"{description} is episode 0 but carries a parent_state_hash")


def _validate_evidence(value: object, description: str) -> None:
    entry = _require_document(value, description)
    kind = _require_member(entry.get("kind"), EVIDENCE_KINDS, f"{description} kind")
    if kind == EVIDENCE_EVENT:
        require_exact_keys(entry, EVENT_EVIDENCE_KEYS, description)
        require_exact_int(entry.get("index"), f"{description} index")
        require_exact_int(entry.get("tick"), f"{description} tick")
        require_text(entry.get("type"), f"{description} type")
        require_identifier(entry.get("source_id"), f"{description} source_id")
        return
    require_exact_keys(entry, FACT_EVIDENCE_KEYS, description)
    require_exact_int(entry.get("episode"), f"{description} episode")
    require_exact_int(entry.get("tick"), f"{description} tick")
    require_identifier(entry.get("fact_id"), f"{description} fact_id")
    require_text(entry.get("fact_type"), f"{description} fact_type")
    require_identifier(entry.get("source_id"), f"{description} source_id")


def _validate_beat(
    value: object,
    description: str,
    expected_rank: int,
    context: dict[str, int],
) -> tuple[str, list[int]]:
    beat = _require_document(value, description)
    require_exact_keys(beat, BEAT_KEYS, description)
    beat_id = require_identifier(beat.get("beat_id"), f"{description} beat_id")
    expected_id = BEAT_ID_FORM % expected_rank
    if beat_id != expected_id:
        raise ValueError(
            f"{description} declares beat_id {beat_id!r} but sits at position "
            f"{expected_rank}, where the identifier is {expected_id!r}; a beat id "
            "is positional, not a free label"
        )
    kind = _require_member(beat.get("kind"), BEAT_KINDS, f"{description} kind")
    emphasis = _require_member(beat.get("emphasis"), EMPHASIS_LEVELS, f"{description} emphasis")
    reason = _require_member(beat.get("reason_code"), REASON_CODES, f"{description} reason_code")
    permitted_reasons = BEAT_REASON_CODES[kind]
    if reason not in permitted_reasons:
        raise ValueError(
            f"{description} is a {kind} beat carrying reason code {reason!r}; "
            f"that kind may only be justified by {sorted(permitted_reasons)}"
        )
    permitted_emphasis = BEAT_EMPHASIS_LEVELS[kind]
    if emphasis not in permitted_emphasis:
        raise ValueError(
            f"{description} is a {kind} beat carrying emphasis {emphasis!r}; "
            f"that kind is always {sorted(permitted_emphasis)}"
        )
    rank = require_exact_int(beat.get("rank"), f"{description} rank")
    if rank != expected_rank:
        raise ValueError(
            f"{description} declares rank {rank} but is at position {expected_rank}; "
            "ranks are the plan's own ordering and must agree with it"
        )
    subjects = _require_list(beat.get("subject_ids"), f"{description} subject_ids")
    seen: set[str] = set()
    for position, subject in enumerate(subjects):
        identifier = require_identifier(subject, f"{description} subject_ids[{position}]")
        if identifier in seen:
            raise ValueError(f"{description} repeats subject id {identifier!r}")
        seen.add(identifier)
    if sorted(seen) != [str(subject) for subject in subjects]:
        raise ValueError(f"{description} subject_ids must be sorted")
    if kind == BEAT_NO_EMPHASIZED_BEATS and subjects:
        raise ValueError(
            f"{description} reports that nothing was emphasized but names subjects "
            f"{subjects}; it is a statement about this layer's output, not about "
            "any entity"
        )
    evidence = _require_list(beat.get("evidence"), f"{description} evidence")
    if kind == BEAT_NO_EMPHASIZED_BEATS:
        # This beat asserts an absence. Citing a record would contradict it.
        if evidence:
            raise ValueError(
                f"{description} is a {BEAT_NO_EMPHASIZED_BEATS} beat but cites "
                "evidence; it reports that nothing was selected"
            )
    elif not evidence:
        raise ValueError(
            f"{description} cites no evidence; every beat must be traceable to an "
            "authoritative record"
        )
    for position, entry in enumerate(evidence):
        _validate_evidence(entry, f"{description} evidence[{position}]")

    entries = [cast(dict[str, JsonValue], entry) for entry in evidence]
    event_entries = [e for e in entries if e["kind"] == EVIDENCE_EVENT]
    fact_entries = [e for e in entries if e["kind"] == EVIDENCE_MEMORY_FACT]

    # An event reference must address an event this episode actually carries,
    # and cannot post-date the episode's close.
    indices: list[int] = []
    for entry in event_entries:
        index = cast(int, entry["index"])
        if index >= context["event_count"]:
            raise ValueError(
                f"{description} cites event {index}, but the episode carries "
                f"{context['event_count']} events, so the last index is "
                f"{context['event_count'] - 1}"
            )
        if cast(int, entry["tick"]) > context["tick"]:
            raise ValueError(
                f"{description} cites an event at tick {entry['tick']}, after the "
                f"episode closed at tick {context['tick']}"
            )
        indices.append(index)

    if reason == REASON_EVENT_TYPE_RULE:
        if len(entries) != 1 or not event_entries:
            raise ValueError(
                f"{description} was derived from an event rule, so it cites exactly "
                f"one event and nothing else; it cites {len(entries)} entries"
            )
        expected_event = BEAT_EVENT_TYPES[kind]
        if event_entries[0]["type"] != expected_event:
            raise ValueError(
                f"{description} is a {kind} beat, which is raised by a "
                f"{expected_event} event, but it cites a "
                f"{event_entries[0]['type']!r} event"
            )
        # The beat is about whoever published the event. Naming anyone else
        # would point downstream presentation at the wrong entity while the
        # citation underneath still looked sound.
        event_subject = [cast(str, event_entries[0]["source_id"])]
        if subjects != event_subject:
            raise ValueError(
                f"{description} names subjects {subjects}, but its event came from "
                f"{event_subject[0]!r}; an event-derived beat is about the entity "
                "the event came from and no other"
            )
    elif reason == REASON_MEMORY_FACT_NEW:
        if len(entries) != 2 or len(fact_entries) != 1 or len(event_entries) != 1:
            raise ValueError(
                f"{description} was derived from a durable fact, so it cites exactly "
                "one fact and the one event that fact names; it cites "
                f"{len(fact_entries)} fact(s) and {len(event_entries)} event(s)"
            )
        fact, event = fact_entries[0], event_entries[0]
        expected_fact = BEAT_FACT_TYPES[kind]
        if fact["fact_type"] != expected_fact:
            raise ValueError(
                f"{description} is a {kind} beat, which is raised by a "
                f"{expected_fact} fact, but it cites a {fact['fact_type']!r} fact"
            )
        expected_source = FACT_SOURCE_EVENT_TYPES[expected_fact]
        if event["type"] != expected_source:
            raise ValueError(
                f"{description} cites a {fact['fact_type']} fact, which derives from "
                f"a {expected_source} event, but the cited event is "
                f"{event['type']!r}"
            )
        if fact["source_id"] != event["source_id"]:
            raise ValueError(
                f"{description} cites a fact about {fact['source_id']!r} alongside an "
                f"event published by {event['source_id']!r}"
            )
        if fact["tick"] != event["tick"]:
            raise ValueError(
                f"{description} cites a fact at tick {fact['tick']} alongside an event "
                f"at tick {event['tick']}; a fact and its source event share a tick"
            )
        if fact["episode"] != context["episode"]:
            raise ValueError(
                f"{description} cites a fact from episode {fact['episode']} in a plan "
                f"describing episode {context['episode']}; only facts new in this "
                "episode earn a beat"
            )
    return emphasis, indices


UNCLASSIFIED_REASONS: Final = {
    UNCLASSIFIED_EVENT: REASON_UNKNOWN_EVENT_TYPE,
    UNCLASSIFIED_FACT: REASON_UNKNOWN_FACT_TYPE,
}
"""An unclassified entry exists for exactly one reason: its type was unknown."""


def _validate_unclassified(value: object, description: str) -> None:
    entry = _require_document(value, description)
    require_exact_keys(entry, UNCLASSIFIED_KEYS, description)
    kind = _require_member(
        entry.get("kind"), (UNCLASSIFIED_EVENT, UNCLASSIFIED_FACT), f"{description} kind"
    )
    require_text(entry.get("type"), f"{description} type")
    reason = _require_member(entry.get("reason_code"), REASON_CODES, f"{description} reason_code")
    expected = UNCLASSIFIED_REASONS[kind]
    if reason != expected:
        raise ValueError(
            f"{description} is an unclassified {kind} carrying reason {reason!r}; "
            f"an unclassified entry is always {expected!r} -- anything else means "
            "it was classified after all"
        )
    # And the type must actually be one the policy does not know. Labelling a
    # type the rule tables cover as unknown would let a known event or fact be
    # quietly set aside without the rule that governs it ever being applied.
    known = KNOWN_EVENT_TYPES if kind == UNCLASSIFIED_EVENT else KNOWN_FACT_TYPES
    declared = cast(str, entry["type"])
    if declared in known:
        raise ValueError(
            f"{description} lists {declared!r} as unknown, but the policy has an "
            f"explicit rule for it; a known {kind} type is classified by that rule, "
            "never set aside as unrecognised"
        )


def validate_episode_story_plan(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Story Plan V1 envelope, and return it.

    Checks the exact key sets at every governed level, the format tag and schema
    version, the source binding (episode numbers, ticks, hashes, and the rule
    that only episode 0 carries no parent hash), and every beat: that its kind,
    emphasis and reason code come from the closed vocabularies, that its declared
    rank agrees with its position, that its subject ids are sorted and unique,
    and that it cites at least one structural piece of evidence.

    Emphasis ordering is checked too: a plan must be sorted strongest-first, so
    a consumer can take the first N beats and know it has the N most emphasised.

    Raises:
        TypeError: If any value has the wrong Python type.
        ValueError: If any key set, vocabulary member, ordering, or internal
            agreement is violated.
    """
    document = _require_document(value, "episode story plan")
    require_exact_keys(document, TOP_LEVEL_KEYS, "episode story plan")

    tag = require_text(document.get("format"), "episode story plan format")
    if tag != STORY_PLAN_FORMAT:
        raise ValueError(
            f"episode story plan declares format {tag!r}; "
            f"this build reads {STORY_PLAN_FORMAT!r} only"
        )
    version = require_exact_int(document.get("schema_version"), "episode story plan schema_version")
    if version != STORY_SCHEMA_VERSION:
        raise ValueError(
            f"episode story plan declares unsupported schema version {version}; "
            f"this build reads version {STORY_SCHEMA_VERSION} only"
        )

    source = _require_document(document.get("source"), "episode story plan source")
    require_exact_keys(source, SOURCE_KEYS, "episode story plan source")
    mode = _require_member(source.get("mode"), PLAN_MODES, "episode story plan source mode")
    declared_render_version = require_exact_int(
        source.get("render_schema_version"),
        "episode story plan source render_schema_version",
    )
    if declared_render_version != RENDER_SCHEMA_VERSION:
        raise ValueError(
            f"episode story plan was derived from render schema version "
            f"{declared_render_version}; this build reads version "
            f"{RENDER_SCHEMA_VERSION} only"
        )
    _validate_export_binding(source.get("current"), "episode story plan source current")
    current_binding = cast(dict[str, JsonValue], source["current"])
    previous = source.get("previous")
    if mode == MODE_BASELINE:
        if previous is not None:
            raise ValueError("episode story plan is baseline mode but binds a previous export")
        if current_binding["episode"] != 0:
            raise ValueError(
                f"episode story plan is baseline mode but describes episode "
                f"{current_binding['episode']}; a baseline describes episode 0 only"
            )
    else:
        if previous is None:
            raise ValueError("episode story plan is transition mode but binds no previous export")
        _validate_export_binding(previous, "episode story plan source previous")
        previous_binding = cast(dict[str, JsonValue], previous)
        previous_episode = cast(int, previous_binding["episode"])
        current_episode = cast(int, current_binding["episode"])
        if current_episode != previous_episode + 1:
            raise ValueError(
                f"episode story plan binds episode {previous_episode} then episode "
                f"{current_episode}; a transition joins consecutive episodes"
            )
        if current_binding["parent_state_hash"] != previous_binding["state_hash"]:
            raise ValueError(
                "episode story plan binds a current export whose parent state hash "
                "is not the previous export's state hash; these two exports are not "
                "the same line of history"
            )

    beats = _require_list(document.get("beats"), "episode story plan beats")
    if not beats:
        raise ValueError(
            "episode story plan carries no beats; a plan that selected nothing says "
            f"so with a {BEAT_NO_EMPHASIZED_BEATS} beat rather than by being empty"
        )
    context = {
        "episode": cast(int, current_binding["episode"]),
        "event_count": cast(int, current_binding["event_count"]),
        "tick": cast(int, current_binding["tick"]),
    }
    previous_weight = -1
    identifiers: set[str] = set()
    cited_events: dict[int, str] = {}
    for position, beat in enumerate(beats):
        label = f"episode story plan beats[{position}]"
        emphasis, indices = _validate_beat(beat, label, position + 1, context)
        weight = EMPHASIS_ORDER[emphasis]
        if weight < previous_weight:
            raise ValueError(
                f"{label} is emphasised more strongly than the beat before it; "
                "a plan is ordered strongest-first"
            )
        previous_weight = weight
        beat_id = cast(dict[str, JsonValue], beat)["beat_id"]
        identifier = cast(str, beat_id)
        if identifier in identifiers:
            raise ValueError(f"episode story plan repeats beat_id {identifier!r}")
        identifiers.add(identifier)
        for index in indices:
            # One event is one moment. Two beats citing it would be the same
            # moment reported twice, and would break the plan's own accounting.
            if index in cited_events:
                raise ValueError(
                    f"{label} cites event {index}, which {cited_events[index]} "
                    "already cites; an event is emphasised once or not at all"
                )
            cited_events[index] = label

    kinds = [cast(str, cast(dict[str, JsonValue], beat)["kind"]) for beat in beats]
    if BEAT_NO_EMPHASIZED_BEATS in kinds and len(kinds) > 1:
        others = sorted(set(kinds) - {BEAT_NO_EMPHASIZED_BEATS})
        raise ValueError(
            f"episode story plan reports that nothing was emphasized while also "
            f"carrying {others}; the empty result is the whole plan or it is not "
            "true"
        )

    excluded = _require_document(document.get("excluded"), "episode story plan excluded")
    for key in sorted(excluded):
        require_text(key, "episode story plan excluded key")
        label = f"episode story plan excluded[{key!r}]"
        tally = _require_document(excluded[key], label)
        require_exact_keys(tally, EXCLUDED_KEYS, label)
        count = require_exact_int(tally.get("count"), f"{label} count")
        if count < 1:
            raise ValueError(
                f"{label} count is {count}; an excluded type is recorded only "
                "when it actually occurred"
            )
        reason = _require_member(tally.get("reason_code"), REASON_CODES, f"{label} reason_code")
        permitted = allowed_exclusion_reasons(key)
        if reason not in permitted:
            raise ValueError(
                f"{label} gives reason {reason!r}, which this policy cannot give "
                f"for {key!r}"
                + (
                    f"; only {sorted(permitted)}"
                    if permitted
                    else "; that type is "
                    "not one this build has an opinion about, so it belongs in "
                    "unclassified rather than excluded"
                )
            )

    unclassified = _require_list(document.get("unclassified"), "episode story plan unclassified")
    for position, entry in enumerate(unclassified):
        _validate_unclassified(entry, f"episode story plan unclassified[{position}]")

    # Every event in the episode is emphasised, set aside, or unrecognised --
    # exactly once. The plan carries enough to prove this about itself, without
    # reopening the render export.
    unclassified_events = sum(
        1
        for entry in unclassified
        if cast(dict[str, JsonValue], entry)["kind"] == UNCLASSIFIED_EVENT
    )
    excluded_total = sum(
        cast(int, cast(dict[str, JsonValue], tally)["count"]) for tally in excluded.values()
    )
    accounted = len(cited_events) + excluded_total + unclassified_events
    if accounted != context["event_count"]:
        raise ValueError(
            f"episode story plan accounts for {accounted} events "
            f"({len(cited_events)} cited + {excluded_total} excluded + "
            f"{unclassified_events} unclassified) but the episode carries "
            f"{context['event_count']}; every event is emphasised, set aside, or "
            "unrecognised, exactly once"
        )

    return document
