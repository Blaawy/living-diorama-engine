"""Tests for event and event-log serialization."""

import pytest

from living_diorama.events import Event, EventLog, EventType
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.serializers.event_serializer import (
    deserialize_event_log,
    serialize_event,
    serialize_event_log,
)
from persistence.conftest import rich_event_log


def round_trip(log: EventLog, *, world_tick: int = 100, episode: int = 0) -> EventLog:
    """Serialize a log through real save bytes and rebuild it."""
    document = loads_canonical(dumps_canonical(serialize_event_log(log, episode, world_tick)))
    return deserialize_event_log(document, world_tick, episode)


def test_the_document_carries_exactly_the_expected_keys() -> None:
    """A fixed shape makes an unexpected key detectable."""
    document = serialize_event_log(rich_event_log(), 0, 100)
    assert sorted(document) == ["episode", "events", "schema_version"]
    assert document["schema_version"] == 1


def test_append_order_is_preserved_exactly() -> None:
    """The order is the history; sorting it would rewrite what happened."""
    original = rich_event_log()
    restored = round_trip(original)
    assert [event.tick for event in restored.events()] == [
        event.tick for event in original.events()
    ]
    assert restored.events() == original.events()


def test_events_are_not_sorted_even_when_ticks_are_out_of_order() -> None:
    """A log recorded out of tick order stays exactly as recorded."""
    log = EventLog()
    log.append(Event(tick=9, type=EventType.SCARCITY_CHANGED, payload={}))
    log.append(Event(tick=2, type=EventType.SCARCITY_CHANGED, payload={}))
    assert [event.tick for event in round_trip(log).events()] == [9, 2]


def test_equal_events_are_neither_merged_nor_deduplicated() -> None:
    """Two identical occurrences are two occurrences."""
    log = EventLog()
    event = Event(tick=1, type=EventType.RESOURCE_PRODUCED, payload={"n": 1})
    log.append(event)
    log.append(event)
    assert len(round_trip(log).events()) == 2


@pytest.mark.parametrize("event_type", list(EventType))
def test_every_event_type_round_trips(event_type: EventType) -> None:
    """Serialized by stable value so a reload cannot rename an occurrence."""
    log = EventLog()
    log.append(Event(tick=1, type=event_type, payload={}))
    document = serialize_event_log(log, 0, 100)
    assert document["events"][0]["type"] == event_type.value
    assert round_trip(log).events()[0].type is event_type


def test_nested_payloads_survive_with_exact_types_and_order() -> None:
    """List order and scalar types inside a payload are part of the record."""
    payload = {
        "list": [1, 2.5, "three", True, False, None],
        "nested": {"inner": {"deep": [{"k": []}]}},
        "empty_list": [],
        "empty_object": {},
    }
    log = EventLog()
    log.append(Event(tick=1, type=EventType.RESOURCE_PRODUCED, payload=payload))
    restored = round_trip(log).events()[0].payload_as_dict()

    assert restored == payload
    assert restored["list"][0] is not True
    assert type(restored["list"][0]) is int
    assert restored["list"][3] is True


def test_an_empty_payload_and_absent_source_round_trip() -> None:
    """Both are ordinary states, recorded explicitly rather than by omission."""
    log = EventLog()
    log.append(Event(tick=4, type=EventType.WALL_BUILT, payload={}, source_id=None))
    document = serialize_event_log(log, 0, 100)
    assert document["events"][0]["payload"] == {}
    assert document["events"][0]["source_id"] is None

    restored = round_trip(log).events()[0]
    assert restored.payload_as_dict() == {}
    assert restored.source_id is None


def test_an_empty_log_round_trips() -> None:
    """An episode where nothing happened is still an episode."""
    assert len(round_trip(EventLog()).events()) == 0


def test_an_unknown_event_type_is_refused() -> None:
    """The log knows something this build does not; inventing a meaning corrupts it."""
    document = serialize_event_log(rich_event_log(), 0, 100)
    document["events"][0]["type"] = "MOON_LANDING"
    with pytest.raises(ValueError):
        deserialize_event_log(document, 100, 0)


def test_an_event_after_the_world_tick_is_refused_on_load() -> None:
    """History cannot contain something that has not happened yet."""
    log = EventLog()
    log.append(Event(tick=50, type=EventType.SCARCITY_CHANGED, payload={}))
    document = serialize_event_log(log, 0, 100)
    with pytest.raises(ValueError):
        deserialize_event_log(document, 10, 0)


def test_an_event_after_the_world_tick_is_refused_on_save() -> None:
    """The same rule on the way out, so an unloadable save cannot be written.

    Without this the writer and the reader disagree, and the disagreement only
    surfaces when the next episode tries to resume from a save that cannot be
    opened.
    """
    log = EventLog()
    log.append(Event(tick=50, type=EventType.SCARCITY_CHANGED, payload={}))
    with pytest.raises(ValueError):
        serialize_event_log(log, 0, 10)


def test_an_event_exactly_at_the_world_tick_is_accepted() -> None:
    """The wall built this tick is part of this tick's history."""
    log = EventLog()
    log.append(Event(tick=10, type=EventType.WALL_BUILT, payload={}))
    assert len(deserialize_event_log(serialize_event_log(log, 0, 10), 10, 0).events()) == 1


@pytest.mark.parametrize("bad", [True, 1.5, "3", -1])
def test_a_corrupt_persisted_event_tick_is_refused(bad: object) -> None:
    """A tick is an exact non-negative int, and ``bool`` is not one."""
    document = serialize_event_log(rich_event_log(), 0, 100)
    document["events"][0]["tick"] = bad
    with pytest.raises((TypeError, ValueError)):
        deserialize_event_log(document, 100, 0)


def test_an_episode_mismatch_between_log_and_world_is_refused() -> None:
    """A log from another episode is not this episode's history."""
    document = serialize_event_log(rich_event_log(), 0, 100)
    document["episode"] = 3
    with pytest.raises(ValueError):
        deserialize_event_log(document, 100, 0)


def test_unexpected_and_missing_event_keys_are_refused() -> None:
    """The event shape is fixed in both directions."""
    document = serialize_event_log(rich_event_log(), 0, 100)
    document["events"][0]["surprise"] = 1
    with pytest.raises(ValueError):
        deserialize_event_log(document, 100, 0)

    reduced = serialize_event_log(rich_event_log(), 0, 100)
    del reduced["events"][0]["payload"]
    with pytest.raises(ValueError):
        deserialize_event_log(reduced, 100, 0)


def test_a_non_list_events_value_is_refused() -> None:
    """The history is a sequence, not a mapping."""
    document = serialize_event_log(rich_event_log(), 0, 100)
    document["events"] = {"0": document["events"][0]}
    with pytest.raises(TypeError):
        deserialize_event_log(document, 100, 0)


def test_a_source_id_need_not_resolve_to_a_current_entity() -> None:
    """History may name something that no longer exists.

    Requiring every source to resolve would make the log unloadable the moment
    an entity could be removed, and would quietly rewrite the past to match the
    present.
    """
    log = EventLog()
    log.append(Event(tick=1, type=EventType.WALL_BUILT, payload={}, source_id="long_gone"))
    assert round_trip(log).events()[0].source_id == "long_gone"


@pytest.mark.parametrize("bad", ["district ", " district", ""])
def test_a_noncanonical_persisted_source_id_is_refused(bad: str) -> None:
    """A reference carrying whitespace names nothing."""
    document = serialize_event_log(rich_event_log(), 0, 100)
    document["events"][0]["source_id"] = bad
    with pytest.raises((TypeError, ValueError)):
        deserialize_event_log(document, 100, 0)


def test_serializing_requires_a_real_event() -> None:
    """A mapping shaped like an event is not an event."""
    with pytest.raises(TypeError):
        serialize_event({"tick": 1}, "event 0", 10)  # type: ignore[arg-type]


def test_loaded_events_are_appended_not_published() -> None:
    """Loading returns a plain log; nothing subscribes to history.

    Re-publishing loaded events would let subscribers react to the past as
    though it were news, which is how a load would start changing the world.
    """
    restored = round_trip(rich_event_log())
    assert isinstance(restored, EventLog)
    assert len(restored.events()) == 3
