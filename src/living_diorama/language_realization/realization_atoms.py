"""Structured semantic-atom extraction for the language realization layer.

Everything a realized sentence says is proven here first, from structure: the
story beat's own evidence entries, the actual event those entries claim inside
the bound render export, the exported durable fact's structured details, and
the world entities a label speaks about. Prose is never an input -- no function
in this module reads a narration sentence or a memory summary, and the source
event payload is never opened, because a wording layer that mined payload for
richer detail would be asserting things no upstream contract proved.

The render export's envelope validator deliberately does not re-judge nested
entity, event, or fact contents, so every referential claim this layer relies
on is proven locally: an evidence entry must match the actual event it points
at, an entity lookup must resolve exactly once, a wall and its boundary must
claim each other, and a fact's restated relationships must agree with the
world's own records. Every disagreement is a refusal, never a repair.
"""

from typing import Final, cast

from living_diorama.language_realization.realization_schema_v1 import JsonValue
from living_diorama.language_realization.realization_spec import (
    ABSENCE_KIND,
    ENTITY_CLASS_DISTRICT,
    ENTITY_CLASS_LAW,
    ENTITY_CLASS_WALL,
    FACT_REALIZATION_TEMPLATES,
    REQUIRED_FACT_DETAILS,
    SUBJECT_ENTITY_CLASS_BY_KIND,
    boundary_phrase,
    district_label,
    law_label,
    render_event_realization,
    render_law_restored_wall_persisted,
    render_wall_built,
    wall_phrase,
)
from living_diorama.narration.narration_facts import EVIDENCE_AGREEMENT_FIELDS, resolve_fact
from living_diorama.narration.narration_spec import (
    TEXT_SOURCE_MEMORY_FACT_SUMMARY,
    text_source_for_kind,
)
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_identifier,
    require_text,
)

EVIDENCE_EVENT: Final = "event"
EVIDENCE_MEMORY_FACT: Final = "memory_fact"
"""Phase 21's evidence kinds, restated to select without importing its internals."""

FACT_TYPE_WALL_BUILT: Final = "WALL_BUILT"
FACT_TYPE_LAW_RESTORED_WALL_PERSISTED: Final = "LAW_RESTORED_WALL_PERSISTED"
"""The memory layer's fact-type tags, restated for the same reason."""

__all__ = [
    "EVIDENCE_EVENT",
    "EVIDENCE_MEMORY_FACT",
    "fact_for_beat",
    "realized_text_for_beat",
    "resolve_boundary",
    "resolve_district",
    "resolve_event",
    "resolve_law",
    "resolve_wall",
]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def _evidence_of_kind(beat: dict[str, JsonValue], kind: str) -> list[dict[str, JsonValue]]:
    evidence = cast(list[dict[str, JsonValue]], beat["evidence"])
    return [entry for entry in evidence if entry["kind"] == kind]


def _world_entries(
    export: dict[str, JsonValue], collection: str, description: str
) -> list[JsonValue]:
    world = _document(export["world"], f"{description} world")
    entries = world[collection]
    if type(entries) is not list:
        raise TypeError(
            f"{description} world {collection} must be a list, got {type(entries).__name__}"
        )
    return entries


def _resolve_entity(
    export: dict[str, JsonValue],
    collection: str,
    entity_id: str,
    description: str,
) -> dict[str, JsonValue]:
    """Return the one world entity a label may speak about, or refuse.

    Raises:
        ValueError: If the export carries no such entity, or more than one --
            world identifiers are unique, so a duplicate means this export did
            not come from the engine.
    """
    matches = [
        _document(entry, f"{description} candidate")
        for entry in _world_entries(export, collection, description)
        if type(entry) is dict and entry.get("id") == entity_id
    ]
    if not matches:
        raise ValueError(
            f"{description} names {collection[:-1]} {entity_id!r}, which the bound render "
            "export does not carry; a label is never written for an entity the world "
            "cannot produce"
        )
    if len(matches) > 1:
        raise ValueError(
            f"{description} names {collection[:-1]} {entity_id!r}, which the bound render "
            f"export carries {len(matches)} times; world identifiers are unique, so this "
            "export did not come from the engine"
        )
    return matches[0]


def resolve_law(
    export: dict[str, JsonValue], law_id: str, description: str
) -> dict[str, JsonValue]:
    """Return the one law entity behind an identifier, with its name proven text."""
    law = _resolve_entity(export, "laws", law_id, description)
    require_identifier(law.get("id"), f"{description} law id")
    require_text(law.get("name"), f"{description} name of law {law_id!r}")
    return law


def resolve_district(
    export: dict[str, JsonValue], district_id: str, description: str
) -> dict[str, JsonValue]:
    """Return the one district entity behind an identifier."""
    district = _resolve_entity(export, "districts", district_id, description)
    require_identifier(district.get("id"), f"{description} district id")
    return district


def resolve_boundary(
    export: dict[str, JsonValue], boundary_id: str, description: str
) -> dict[str, JsonValue]:
    """Return the one boundary behind an identifier, with both endpoints proven.

    Raises:
        ValueError: If the boundary is absent or duplicated, joins a district
            to itself, or names an endpoint district the export cannot
            resolve exactly once.
    """
    boundary = _resolve_entity(export, "boundaries", boundary_id, description)
    district_a_id = require_identifier(
        boundary.get("district_a_id"), f"{description} boundary {boundary_id!r} district_a_id"
    )
    district_b_id = require_identifier(
        boundary.get("district_b_id"), f"{description} boundary {boundary_id!r} district_b_id"
    )
    if district_a_id == district_b_id:
        raise ValueError(
            f"{description} boundary {boundary_id!r} joins district {district_a_id!r} to "
            "itself; a boundary joins two different districts"
        )
    resolve_district(export, district_a_id, description)
    resolve_district(export, district_b_id, description)
    return boundary


def resolve_wall(
    export: dict[str, JsonValue], wall_id: str, description: str
) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    """Return a wall and its boundary, with the reciprocal relation proven.

    A human-facing wall phrase is built from the boundary the wall stands on,
    so the relation is proven in both directions before a word is composed: the
    wall names its boundary, and that boundary must claim the wall back.

    Raises:
        ValueError: If the wall or its boundary does not resolve exactly once,
            or the boundary does not claim this wall back.
    """
    wall = _resolve_entity(export, "walls", wall_id, description)
    require_identifier(wall.get("id"), f"{description} wall id")
    boundary_id = require_identifier(
        wall.get("boundary_id"), f"{description} wall {wall_id!r} boundary_id"
    )
    boundary = resolve_boundary(export, boundary_id, description)
    claimed = boundary.get("wall_id")
    if claimed is None:
        raise ValueError(
            f"{description} wall {wall_id!r} stands on boundary {boundary_id!r}, but that "
            "boundary carries no wall; a wall phrase is never built from a relation the "
            "other side denies"
        )
    if claimed != wall_id:
        raise ValueError(
            f"{description} wall {wall_id!r} stands on boundary {boundary_id!r}, but that "
            f"boundary carries wall {claimed!r}; a wall phrase is never built from a "
            "relation the other side contradicts"
        )
    return wall, boundary


def _boundary_labels(
    export: dict[str, JsonValue], boundary: dict[str, JsonValue], description: str
) -> tuple[str, str]:
    """Return the display labels for a resolved boundary's two endpoints."""
    label_a = district_label(cast(str, boundary["district_a_id"]), description)
    label_b = district_label(cast(str, boundary["district_b_id"]), description)
    return label_a, label_b


def resolve_event(
    export: dict[str, JsonValue],
    evidence: dict[str, JsonValue],
    description: str,
) -> dict[str, JsonValue]:
    """Return the actual export event an evidence entry claims, proven to agree.

    Story validation proves an evidence entry's internal shape and its
    agreement with the beat's own kind, but not that the entry matches the
    actual event inside the bound export. This is the only place that gap can
    close, so every one of these is a refusal, never a shrug:

    * the index is out of range for the export's events
    * the referenced event's type, ``source_id`` or tick is not itself canonical
    * any of those three disagrees with what the evidence claims

    The event's own fields are validated before any comparison, so equality is
    never asked to do a type check on our behalf.

    Raises:
        TypeError: If the referenced event has the wrong shape.
        ValueError: If the reference is out of range or disagrees with the
            evidence that claims it.
    """
    events = export["events"]
    if type(events) is not list:
        raise TypeError(f"{description} export events must be a list, got {type(events).__name__}")
    index = cast(int, evidence["index"])
    if index >= len(events):
        raise ValueError(
            f"{description} points at event {index}, but this export carries only "
            f"{len(events)} events"
        )

    label = f"{description} export event[{index}]"
    event = _document(events[index], label)
    for field in ("type", "source_id", "tick"):
        if field not in event:
            raise ValueError(f"{label} is missing {field}")

    event_type = require_text(event["type"], f"{label} type")
    event_source_id = require_identifier(event["source_id"], f"{label} source_id")
    event_tick = require_exact_int(event["tick"], f"{label} tick")

    if event_type != evidence["type"]:
        raise ValueError(
            f"{description} cites a {evidence['type']!r} event, but event {index} is a "
            f"{event_type!r} event; this evidence does not identify the moment it claims"
        )
    if event_source_id != evidence["source_id"]:
        raise ValueError(
            f"{description} cites an event published by {evidence['source_id']!r}, but "
            f"event {index} was published by {event_source_id!r}"
        )
    if event_tick != evidence["tick"]:
        raise ValueError(
            f"{description} cites an event at tick {evidence['tick']!r}, but event "
            f"{index} happened at tick {event_tick}; evidence and its event share a tick"
        )
    return event


def _event_tick(
    beat: dict[str, JsonValue],
    export: dict[str, JsonValue],
    kind: str,
    description: str,
) -> int:
    """Return the authoritative tick of an event-derived beat's single event."""
    events = _evidence_of_kind(beat, EVIDENCE_EVENT)
    if len(events) != 1:
        raise ValueError(
            f"{description} is a {kind} beat whose sentence records the tick of the event "
            f"that raised it, so it cites exactly one event; it cites {len(events)}"
        )
    resolve_event(export, events[0], description)
    return cast(int, events[0]["tick"])


def _subject_label(
    kind: str,
    subject_id: str,
    export: dict[str, JsonValue],
    description: str,
) -> str:
    """Return the human-facing label for an event-derived beat's subject.

    The beat kind decides the entity class, so the identifier is resolved in
    exactly one world collection and can never be labeled as something it is
    not.
    """
    entity_class = SUBJECT_ENTITY_CLASS_BY_KIND.get(kind)
    if entity_class is None:
        raise ValueError(
            f"{description} is a {kind} beat, for which no reviewed subject class exists; "
            "an unreviewed kind is refused, never paraphrased"
        )
    if entity_class == ENTITY_CLASS_LAW:
        law = resolve_law(export, subject_id, description)
        return law_label(cast(str, law["name"]), description)
    if entity_class == ENTITY_CLASS_WALL:
        _wall, boundary = resolve_wall(export, subject_id, description)
        label_a, label_b = _boundary_labels(export, boundary, description)
        return wall_phrase(label_a, label_b)
    if entity_class == ENTITY_CLASS_DISTRICT:
        resolve_district(export, subject_id, description)
        return district_label(subject_id, description)
    raise ValueError(
        f"{description} names entity class {entity_class!r}, which this build does not "
        "resolve; a label source is reviewed or it is refused"
    )


def fact_for_beat(
    beat: dict[str, JsonValue],
    export: dict[str, JsonValue],
    description: str,
) -> dict[str, JsonValue]:
    """Return the durable fact a fact-backed beat restates, proven to agree.

    The beat's memory evidence names the fact; the fact must resolve exactly
    once in the export, agree with the evidence field for field, agree with
    the beat about its subjects, and derive from an actual export event the
    beat's event evidence also identifies. The event evidence must identify
    the very source event the fact itself declares -- index and type -- so
    two events sharing a type, publisher and tick can never be swapped.

    The declared index addresses the bound current export's events: the
    locked story layer only grants a fact-backed beat to a fact new in the
    story's own episode (``require_new_fact_episode`` and the story schema's
    only-facts-new-in-this-episode rule), and this layer's joins bind that
    story to the very export offered here.

    Raises:
        TypeError: If any document has the wrong shape.
        ValueError: If the evidence, the fact, the beat and the export do not
            all describe one recorded moment.
    """
    facts = _evidence_of_kind(beat, EVIDENCE_MEMORY_FACT)
    if len(facts) != 1:
        raise ValueError(
            f"{description} is realized from a recorded fact, so it cites exactly one "
            f"memory fact; it cites {len(facts)}"
        )
    evidence = facts[0]
    fact = resolve_fact(export, cast(str, evidence["fact_id"]), description)
    for field in EVIDENCE_AGREEMENT_FIELDS:
        cited = evidence[field]
        recorded = fact[field]
        if cited != recorded or type(cited) is not type(recorded):
            raise ValueError(
                f"{description} cites memory fact {evidence['fact_id']!r} with {field} "
                f"{cited!r}, but the exported fact records {recorded!r}; the wording this "
                "beat would carry belongs to a different record than the one it names"
            )

    if beat["subject_ids"] != fact["subject_ids"]:
        raise ValueError(
            f"{description} names subjects {beat['subject_ids']!r}, but memory fact "
            f"{evidence['fact_id']!r} names {fact['subject_ids']!r}; a fact-backed beat "
            "is about the fact's own subjects and no other"
        )

    events = _evidence_of_kind(beat, EVIDENCE_EVENT)
    if len(events) != 1:
        raise ValueError(
            f"{description} is realized from a recorded fact, so it also cites the one "
            f"event that fact derives from; it cites {len(events)} events"
        )
    entry = events[0]
    cited_index = require_exact_int(entry["index"], f"{description} event evidence index")
    if cited_index != fact["source_event_index"]:
        raise ValueError(
            f"{description} cites the event at index {cited_index}, but memory fact "
            f"{evidence['fact_id']!r} derives from the event at index "
            f"{fact['source_event_index']}; the story's evidence and the fact name one "
            "source event"
        )
    cited_type = require_text(entry["type"], f"{description} event evidence type")
    if cited_type != fact["source_event_type"]:
        raise ValueError(
            f"{description} cites a {cited_type!r} event, but memory fact "
            f"{evidence['fact_id']!r} derives from a {fact['source_event_type']!r} "
            "event; the story's evidence and the fact name one source event"
        )
    actual = resolve_event(export, entry, description)
    if actual["tick"] != fact["tick"]:
        raise ValueError(
            f"{description} cites an event at tick {actual['tick']!r}, but memory fact "
            f"{evidence['fact_id']!r} is recorded at tick {fact['tick']!r}; a fact and "
            "the event it derives from share a tick"
        )
    return fact


def _require_details(
    fact: dict[str, JsonValue], fact_type: str, description: str
) -> dict[str, JsonValue]:
    """Return a fact's structured details, with every field this layer reads present.

    Deliberately not an exact-key check: the details block is the memory
    layer's document, and it records fields this layer never reads. Only the
    reviewed presentation atoms are required, typed, and used.
    """
    details = _document(fact["details"], f"{description} details")
    missing = sorted(set(REQUIRED_FACT_DETAILS[fact_type]) - set(details))
    if missing:
        raise ValueError(f"{description} details are missing required fields: {missing}")
    return details


def _require_true_flag(value: JsonValue, description: str, because: str) -> None:
    """Verify a permanence flag is a genuine ``True``, or refuse."""
    if type(value) is not bool:
        raise TypeError(f"{description} must be a bool, got {type(value).__name__}")
    if value is not True:
        raise ValueError(f"{description} is {value!r}; {because}")


def _wall_built_parameters(
    fact: dict[str, JsonValue],
    export: dict[str, JsonValue],
    description: str,
) -> tuple[int, str]:
    """Return the reviewed template parameters for a WALL_BUILT fact."""
    details = _require_details(fact, FACT_TYPE_WALL_BUILT, description)
    wall_id = require_identifier(details["wall_id"], f"{description} details wall_id")
    boundary_id = require_identifier(details["boundary_id"], f"{description} details boundary_id")
    district_a_id = require_identifier(
        details["district_a_id"], f"{description} details district_a_id"
    )
    district_b_id = require_identifier(
        details["district_b_id"], f"{description} details district_b_id"
    )
    built_tick = require_exact_int(details["built_tick"], f"{description} details built_tick")
    _require_true_flag(
        details["permanent"],
        f"{description} details permanent",
        "only a permanent wall is remembered as built",
    )
    if built_tick != fact["tick"]:
        raise ValueError(
            f"{description} is recorded at tick {fact['tick']!r}, but its details say the "
            f"wall was built at tick {built_tick}; a built fact and its wall share a tick"
        )
    if wall_id != fact["source_id"]:
        raise ValueError(
            f"{description} was published by {fact['source_id']!r}, but its details name "
            f"wall {wall_id!r}; a realized fact speaks about its own subject and no other"
        )

    wall, boundary = resolve_wall(export, wall_id, description)
    if boundary_id != wall["boundary_id"]:
        raise ValueError(
            f"{description} says the wall stands on boundary {boundary_id!r}, but the "
            f"world's wall stands on {wall['boundary_id']!r}; a realized relation follows "
            "the world's own record"
        )
    world_built = require_exact_int(wall["built_tick"], f"{description} world wall built_tick")
    if built_tick != world_built:
        raise ValueError(
            f"{description} says the wall was built at tick {built_tick}, but the world's "
            f"wall records tick {world_built}; a realized relation follows the world's "
            "own record"
        )
    if district_a_id != boundary["district_a_id"] or district_b_id != boundary["district_b_id"]:
        raise ValueError(
            f"{description} says the boundary joins {district_a_id!r} and "
            f"{district_b_id!r}, but the world's boundary {boundary_id!r} joins "
            f"{boundary['district_a_id']!r} and {boundary['district_b_id']!r}; endpoints "
            "are the world's own and are never swapped or substituted"
        )
    label_a, label_b = _boundary_labels(export, boundary, description)
    return built_tick, boundary_phrase(label_a, label_b)


def _law_restored_parameters(
    fact: dict[str, JsonValue],
    export: dict[str, JsonValue],
    description: str,
) -> tuple[int, str, str, int]:
    """Return the reviewed template parameters for a LAW_RESTORED_WALL_PERSISTED fact."""
    details = _require_details(fact, FACT_TYPE_LAW_RESTORED_WALL_PERSISTED, description)
    law_id = require_identifier(details["law_id"], f"{description} details law_id")
    law_name = require_text(details["law_name"], f"{description} details law_name")
    wall_id = require_identifier(details["wall_id"], f"{description} details wall_id")
    boundary_id = require_identifier(details["boundary_id"], f"{description} details boundary_id")
    restored_tick = require_exact_int(
        details["restored_tick"], f"{description} details restored_tick"
    )
    wall_built_tick = require_exact_int(
        details["wall_built_tick"], f"{description} details wall_built_tick"
    )
    _require_true_flag(
        details["wall_permanent"],
        f"{description} details wall_permanent",
        "only a permanent wall is remembered as persisting",
    )
    if restored_tick != fact["tick"]:
        raise ValueError(
            f"{description} is recorded at tick {fact['tick']!r}, but its details say the "
            f"law was restored at tick {restored_tick}; a restoration fact and its event "
            "share a tick"
        )
    if law_id != fact["source_id"]:
        raise ValueError(
            f"{description} was published by {fact['source_id']!r}, but its details name "
            f"law {law_id!r}; a realized fact speaks about its own subject and no other"
        )
    if wall_id not in cast(list[JsonValue], fact["subject_ids"]):
        raise ValueError(
            f"{description} says wall {wall_id!r} persisted, but the fact's own subjects "
            f"are {fact['subject_ids']!r}; a realized fact speaks about its own subject "
            "and no other"
        )

    law = resolve_law(export, law_id, description)
    if law_name != law["name"]:
        raise ValueError(
            f"{description} names the law {law_name!r}, but the world's law {law_id!r} is "
            f"named {law['name']!r}; a presentation label follows the world's own name"
        )
    wall, boundary = resolve_wall(export, wall_id, description)
    if boundary_id != wall["boundary_id"]:
        raise ValueError(
            f"{description} says the wall stands on boundary {boundary_id!r}, but the "
            f"world's wall stands on {wall['boundary_id']!r}; a realized relation follows "
            "the world's own record"
        )
    world_built = require_exact_int(wall["built_tick"], f"{description} world wall built_tick")
    if wall_built_tick != world_built:
        raise ValueError(
            f"{description} says the wall was built at tick {wall_built_tick}, but the "
            f"world's wall records tick {world_built}; a realized relation follows the "
            "world's own record"
        )
    label_a, label_b = _boundary_labels(export, boundary, description)
    return (
        restored_tick,
        law_label(law_name, description),
        boundary_phrase(label_a, label_b),
        wall_built_tick,
    )


def realized_text_for_beat(
    kind: str,
    beat: dict[str, JsonValue],
    export: dict[str, JsonValue],
    description: str,
) -> str:
    """Return the one realized sentence for a beat, derived from structure alone.

    Raises:
        TypeError: If any document has the wrong shape.
        ValueError: If the kind or fact type has no reviewed realization, or
            any structural claim behind the sentence fails to prove.
    """
    source = text_source_for_kind(kind)
    if source == TEXT_SOURCE_MEMORY_FACT_SUMMARY:
        fact = fact_for_beat(beat, export, description)
        fact_type = cast(str, fact["fact_type"])
        if fact_type not in FACT_REALIZATION_TEMPLATES:
            raise ValueError(
                f"{description} restates a {fact_type!r} fact, for which no reviewed "
                "realization exists; an unreviewed fact type is refused, never "
                "paraphrased"
            )
        if fact_type == FACT_TYPE_WALL_BUILT:
            built_tick, boundary_label = _wall_built_parameters(fact, export, description)
            return render_wall_built(built_tick, boundary_label)
        restored_tick, law_label_text, boundary_label, wall_built_tick = _law_restored_parameters(
            fact, export, description
        )
        return render_law_restored_wall_persisted(
            restored_tick, law_label_text, boundary_label, wall_built_tick
        )

    if kind == ABSENCE_KIND:
        if beat["evidence"]:
            raise ValueError(
                f"{description} is a {kind} beat whose sentence takes no parameters, but "
                "it cites evidence; that beat reports an absence and cites nothing"
            )
        return render_event_realization(kind, None, None)

    tick = _event_tick(beat, export, kind, description)
    subjects = cast(list[str], beat["subject_ids"])
    if len(subjects) != 1:
        raise ValueError(
            f"{description} is a {kind} beat naming {len(subjects)} subjects; an "
            "event-derived beat is about exactly one entity"
        )
    label = _subject_label(kind, subjects[0], export, description)
    return render_event_realization(kind, label, tick)
