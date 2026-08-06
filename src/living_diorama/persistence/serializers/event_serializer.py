"""Serialization for :class:`Event` and the episode-scoped :class:`EventLog`."""

from collections.abc import Mapping
from typing import cast

from living_diorama.entities import EntityId
from living_diorama.events import Event, EventLog, EventType
from living_diorama.events.event import FrozenJsonValue, JsonValue
from living_diorama.persistence.json_codec import require_document, require_json_value
from living_diorama.persistence.schema.world_schema_v1 import (
    SCHEMA_VERSION,
    require_exact_int,
    require_exact_keys,
    require_identifier,
    require_schema_version,
)

_EVENT_KEYS = frozenset({"payload", "source_id", "tick", "type"})
"""Exactly the keys a serialized event carries."""

_LOG_KEYS = frozenset({"episode", "events", "schema_version"})
"""Exactly the keys a serialized event log carries."""


def _event_type(value: JsonValue, description: str) -> EventType:
    """Return the event type named by a stable enum value.

    Raises:
        TypeError: If the value is not a ``str``.
        ValueError: If it names no known event type. An unknown type means the
            log was written by a build that knows something this one does not,
            and inventing a meaning for it would corrupt the history.
    """
    if type(value) is not str:
        raise TypeError(f"{description} must be a str, got {type(value).__name__}")
    try:
        return EventType(value)
    except ValueError as error:
        raise ValueError(f"{description} names an unknown event type: {value!r}") from error


def serialize_event(event: Event, description: str, world_tick: int) -> dict[str, JsonValue]:
    """Return one event as a JSON object.

    Args:
        event: The event to serialize.
        description: What is being written, used in error messages.
        world_tick: The tick of the world being saved. An event may not
            postdate it.

    Raises:
        TypeError: If the argument is not an Event or a field is mistyped.
        ValueError: If the tick is negative, the event postdates the world, or
            the payload is not JSON-safe.
    """
    if not isinstance(event, Event):
        raise TypeError(f"{description} must be an Event, got {type(event).__name__}")
    if not isinstance(event.type, EventType):
        raise TypeError(f"{description} type must be an EventType, got {type(event.type).__name__}")
    tick = require_exact_int(event.tick, f"{description} tick")
    if tick > world_tick:
        raise ValueError(
            f"{description} happened on tick {tick}, after the world tick {world_tick}; "
            "an episode cannot record something that has not happened yet"
        )
    stored_source_id = event.source_id
    source_id: EntityId | None = (
        None
        if stored_source_id is None
        else require_identifier(stored_source_id, f"{description} source_id")
    )
    return {
        "payload": require_json_value(event.payload_as_dict(), f"{description} payload"),
        "source_id": source_id,
        "tick": tick,
        "type": event.type.value,
    }


def deserialize_event(value: JsonValue, description: str, world_tick: int) -> Event:
    """Rebuild one immutable event from a JSON object.

    Args:
        value: The serialized event.
        description: What is being decoded, used in error messages.
        world_tick: The saved world tick, which no event may postdate.

    Raises:
        TypeError: If the value is not a JSON object or a field is mistyped.
        ValueError: If keys are missing or extra, a field is invalid, or the
            event claims to have happened after the world's own tick.
    """
    document = require_document(value, description)
    require_exact_keys(document, _EVENT_KEYS, description)
    tick = require_exact_int(document["tick"], f"{description} tick")
    if tick > world_tick:
        raise ValueError(
            f"{description} happened on tick {tick}, after the saved world tick {world_tick}"
        )
    stored_source_id = document["source_id"]
    source_id: EntityId | None = (
        None
        if stored_source_id is None
        else require_identifier(stored_source_id, f"{description} source_id")
    )
    payload = require_document(document["payload"], f"{description} payload")

    # Event freezes and validates mutable JSON input in __post_init__.
    # Its locked field annotation describes the post-construction shape,
    # so this cast bridges that intentionally stricter stored-state type.
    event_payload = cast(
        Mapping[str, FrozenJsonValue],
        payload,
    )

    return Event(
        tick=tick,
        type=_event_type(document["type"], f"{description} type"),
        payload=event_payload,
        source_id=source_id,
    )


def serialize_event_log(event_log: EventLog, episode: int, world_tick: int) -> dict[str, JsonValue]:
    """Return an episode's event history as a JSON object.

    Events are written in exactly the order they were appended. Unlike the
    entity arrays, the log is never sorted: its order *is* the history, and
    rearranging it would rewrite what happened.

    The world tick is required rather than optional because the loader refuses
    an event that postdates it. Without the same check here, a save could be
    written that this implementation could never read back.

    Args:
        event_log: The history to write.
        episode: The episode this history belongs to.
        world_tick: The tick of the world being saved.

    Raises:
        TypeError: If the argument is not an EventLog or an event is mistyped.
        ValueError: If an event carries an invalid value or postdates the world.
    """
    if not isinstance(event_log, EventLog):
        raise TypeError(f"event_log must be an EventLog, got {type(event_log).__name__}")
    checked_tick = require_exact_int(world_tick, "world_tick")
    return {
        "episode": require_exact_int(episode, "episode"),
        "events": [
            serialize_event(event, f"event {index}", checked_tick)
            for index, event in enumerate(event_log.events())
        ],
        "schema_version": SCHEMA_VERSION,
    }


def deserialize_event_log(value: JsonValue, world_tick: int, episode: int) -> EventLog:
    """Rebuild an event log from a JSON object, preserving append order.

    Loaded events are appended to a fresh log directly. They are deliberately
    not published through an ``EventBus``: they already happened, and
    re-publishing them would let subscribers react to history as though it were
    news.

    Raises:
        TypeError: If the value is not a JSON object or a field is mistyped.
        ValueError: If keys are missing or extra, the schema version is
            unsupported, the episode disagrees, or an event is invalid.
    """
    document = require_document(value, "event log")
    require_exact_keys(document, _LOG_KEYS, "event log")
    require_schema_version(document, "event log")

    recorded_episode = require_exact_int(document["episode"], "event log episode")
    if recorded_episode != episode:
        raise ValueError(
            f"event log records episode {recorded_episode}, but the world records {episode}"
        )

    events = document["events"]
    if type(events) is not list:
        raise TypeError(f"event log events must be a list, got {type(events).__name__}")

    log = EventLog()
    for index, entry in enumerate(events):
        log.append(deserialize_event(entry, f"event {index}", world_tick))
    return log
