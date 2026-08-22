"""Structural validation of a memory fact and the event it says it came from.

A durable fact carries ``source_event_index``, the position of the event it was
derived from **in the event array of the episode that recorded it**. That index
is episode-scoped, and this is the trap: in the canonical chain the episode-1
``WALL_BUILT`` fact is still carried in episode 2's cumulative memory, still
pointing at index 61 -- which in episode 2's array is an unrelated
``SOCIAL_STABILITY_CHANGED`` event about a different district at a different
tick.

Carried facts are prefix history and are never new, so the question never arises
for them. A fact that *is* new was appended by the episode being described, and
must therefore declare that episode: a newly appended fact claiming any other
episode is malformed, and is refused rather than promoted without its evidence.
That refusal is what stops a mutated ``episode`` field from being used to slip
past the source-event checks below.

Nothing here repairs anything. A malformed subject list is refused, not filtered;
an unsorted one is refused, not sorted. The authoritative memory contract already
guarantees these properties, so an input that lacks them did not come from the
engine, and quietly making it look as though it did is how a plan ends up citing
something that was never true.
"""

from typing import Final, cast

from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_identifier,
    require_text,
)
from living_diorama.story.story_schema_v1 import JsonValue
from living_diorama.story.story_spec import FACT_SOURCE_EVENT_TYPES

FACT_KEYS: Final = frozenset(
    {
        "details",
        "episode",
        "fact_id",
        "fact_type",
        "source_event_index",
        "source_event_type",
        "source_id",
        "subject_ids",
        "tick",
    }
)
"""The fact fields this layer relies on.

Deliberately not the fact's whole key set: the export also carries a free-form
prose field, and this layer does not name it, require it, or read it. Selection
is driven by types and identifiers only.
"""

__all__ = [
    "FACT_KEYS",
    "FACT_SOURCE_EVENT_TYPES",
    "require_fact_shape",
    "require_new_fact_episode",
    "require_source_event_type_agrees",
    "require_subject_ids",
    "resolve_source_event",
]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def require_subject_ids(value: object, description: str) -> list[str]:
    """Return the fact's subjects, refusing anything the memory contract forbids.

    Durable memory guarantees subjects are canonical identifiers, unique, and
    sorted. All three are checked here and none is repaired: dropping a
    non-string, de-duplicating a repeat, or sorting an unsorted list would each
    turn input the engine could not have produced into something that looks like
    it did.

    Raises:
        TypeError: If the list, or any member, is not the right type.
        ValueError: If a member is not canonical, repeats, or is out of order.
    """
    if type(value) is not list:
        raise TypeError(f"{description} must be a list, got {type(value).__name__}")
    subjects: list[str] = []
    for position, entry in enumerate(value):
        subjects.append(require_identifier(entry, f"{description}[{position}]"))
    if len(set(subjects)) != len(subjects):
        repeated = sorted({s for s in subjects if subjects.count(s) > 1})
        raise ValueError(f"{description} repeats {repeated}")
    if subjects != sorted(subjects):
        raise ValueError(f"{description} must be sorted, got {subjects}")
    return subjects


def require_fact_shape(value: object, description: str) -> dict[str, JsonValue]:
    """Verify a memory fact carries the fields this layer relies on, and return it.

    Raises:
        TypeError: If any field has the wrong Python type.
        ValueError: If a key is missing, an identifier is blank, an integer is
            negative, or the subject list breaks the memory contract.
    """
    fact = _document(value, description)
    missing = sorted(FACT_KEYS - set(fact))
    if missing:
        raise ValueError(f"{description} is missing required keys: {missing}")
    require_identifier(fact.get("fact_id"), f"{description} fact_id")
    require_text(fact.get("fact_type"), f"{description} fact_type")
    require_text(fact.get("source_event_type"), f"{description} source_event_type")
    require_identifier(fact.get("source_id"), f"{description} source_id")
    require_exact_int(fact.get("episode"), f"{description} episode")
    require_exact_int(fact.get("tick"), f"{description} tick")
    require_exact_int(fact.get("source_event_index"), f"{description} source_event_index")
    require_subject_ids(fact.get("subject_ids"), f"{description} subject_ids")
    return fact


def require_new_fact_episode(
    fact: dict[str, JsonValue], current_episode: int, description: str
) -> None:
    """Verify a newly appended fact was recorded by the episode being described.

    Durable memory only grows, so a fact appended during episode N declares
    episode N. One claiming anything else did not come from this episode's run,
    and its ``source_event_index`` therefore addresses an array this export does
    not carry.

    Refusing here is what keeps the source-event checks unbypassable: without it,
    editing one integer would excuse a fact from proving its own provenance.

    Raises:
        ValueError: If the fact does not declare the current episode.
    """
    episode = cast(int, fact["episode"])
    if episode != current_episode:
        raise ValueError(
            f"{description} is new in episode {current_episode} but declares "
            f"episode {episode}; a newly remembered fact belongs to the episode "
            "that recorded it, and its source event reference addresses that "
            "episode's event array"
        )


def require_source_event_type_agrees(fact: dict[str, JsonValue], description: str) -> None:
    """Verify a known fact type names the event type it must have come from.

    A fact type this build does not recognise is left alone: it degrades
    neutrally elsewhere and is never given a guessed provenance rule here.

    Raises:
        ValueError: If a known fact type names the wrong source event type.
    """
    fact_type = cast(str, fact["fact_type"])
    expected = FACT_SOURCE_EVENT_TYPES.get(fact_type)
    if expected is None:
        return
    declared = cast(str, fact["source_event_type"])
    if declared != expected:
        raise ValueError(
            f"{description} is a {fact_type} fact, which must derive from a "
            f"{expected} event, but it declares {declared}"
        )


def resolve_source_event(
    fact: dict[str, JsonValue],
    events: list[JsonValue],
    description: str,
) -> tuple[int, dict[str, JsonValue]]:
    """Return the event a fact was derived from, proven to agree with it.

    The caller has already established that this fact is new in the episode whose
    events are supplied, so the reference must resolve. Every one of these is a
    refusal, never a shrug:

    * the index is out of range for this episode's events
    * any of the event's type, ``source_id`` or tick is not itself canonical
    * the referenced event's type is not the fact's ``source_event_type``
    * the referenced event's ``source_id`` is not the fact's ``source_id``
    * the referenced event's tick is not the fact's tick

    The event's own fields are validated before any comparison, so equality is
    never asked to do a type check on our behalf.

    Raises:
        TypeError: If the referenced event has the wrong shape.
        ValueError: If the reference is out of range or disagrees with the fact.
    """
    require_source_event_type_agrees(fact, description)
    index = cast(int, fact["source_event_index"])
    if index >= len(events):
        raise ValueError(
            f"{description} points at event {index}, but this episode's export "
            f"carries only {len(events)} events"
        )

    label = f"{description} source event[{index}]"
    event = _document(events[index], label)
    for field in ("type", "source_id", "tick"):
        if field not in event:
            raise ValueError(f"{label} is missing {field}")

    # Validate before comparing. Python's scalar equality would otherwise do the
    # comparing for us and get it wrong: ``True == 1`` is true, so a boolean tick
    # would satisfy an integer tick. Where both the fact type and the event type
    # are unrecognised, neither value becomes evidence, so nothing downstream
    # would catch it either -- this is the only place it can be caught.
    event_type = require_text(event["type"], f"{label} type")
    event_source_id = require_identifier(event["source_id"], f"{label} source_id")
    event_tick = require_exact_int(event["tick"], f"{label} tick")

    declared_type = cast(str, fact["source_event_type"])
    if event_type != declared_type:
        raise ValueError(
            f"{description} says it came from a {declared_type} event, but event "
            f"{index} is a {event_type!r} event; this reference does not "
            "identify the moment the fact records"
        )
    if event_source_id != fact["source_id"]:
        raise ValueError(
            f"{description} names subject {fact['source_id']!r}, but event {index} "
            f"was published by {event_source_id!r}"
        )
    if event_tick != fact["tick"]:
        raise ValueError(
            f"{description} is recorded at tick {fact['tick']}, but event {index} "
            f"happened at tick {event_tick}; a fact and the event it derives "
            "from share a tick"
        )
    return index, event
