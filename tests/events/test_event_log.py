"""Tests for EventLog: ordering, snapshot isolation, querying, and append-only-ness."""

from living_diorama.events import Event, EventLog, EventType


def _event(tick: int, event_type: EventType, source_id: str | None = None) -> Event:
    """Build a small event for log tests."""
    return Event(tick=tick, type=event_type, payload={"n": tick}, source_id=source_id)


def test_append_preserves_exact_order() -> None:
    """The log is a record of sequence, so insertion order is the whole point."""
    log = EventLog()
    events = [_event(tick, EventType.RESOURCE_PRODUCED) for tick in range(5)]
    for event in events:
        log.append(event)
    assert list(log.events()) == events


def test_len_and_iteration_work() -> None:
    """A log behaves like the ordered collection it is."""
    log = EventLog()
    assert len(log) == 0
    log.append(_event(1, EventType.WALL_BUILT))
    log.append(_event(2, EventType.WALL_CHANGED))
    assert len(log) == 2
    assert [event.tick for event in log] == [1, 2]


def test_events_returns_an_immutable_snapshot() -> None:
    """Reads never hand out the internal list."""
    log = EventLog()
    log.append(_event(1, EventType.WALL_BUILT))
    snapshot = log.events()
    assert isinstance(snapshot, tuple)


def test_snapshot_does_not_change_when_the_log_grows() -> None:
    """A snapshot already handed out must stay as it was when taken."""
    log = EventLog()
    log.append(_event(1, EventType.WALL_BUILT))
    snapshot = log.events()
    log.append(_event(2, EventType.WALL_CHANGED))
    assert len(snapshot) == 1
    assert len(log) == 2


def test_query_by_type() -> None:
    """Filtering by type selects only that kind of occurrence."""
    log = EventLog()
    log.append(_event(1, EventType.WALL_BUILT))
    log.append(_event(2, EventType.RESOURCE_CONSUMED))
    log.append(_event(3, EventType.WALL_BUILT))
    assert [event.tick for event in log.query(event_type=EventType.WALL_BUILT)] == [1, 3]


def test_query_by_tick_range_is_inclusive() -> None:
    """Both bounds are inclusive, so a single tick is selectable."""
    log = EventLog()
    for tick in range(1, 6):
        log.append(_event(tick, EventType.SCARCITY_CHANGED))
    assert [e.tick for e in log.query(tick_start=2, tick_end=4)] == [2, 3, 4]
    assert [e.tick for e in log.query(tick_start=3, tick_end=3)] == [3]


def test_query_with_open_ended_tick_bounds() -> None:
    """Omitting a bound places no constraint on that side."""
    log = EventLog()
    for tick in range(1, 6):
        log.append(_event(tick, EventType.SCARCITY_CHANGED))
    assert [e.tick for e in log.query(tick_start=4)] == [4, 5]
    assert [e.tick for e in log.query(tick_end=2)] == [1, 2]


def test_query_by_source_id() -> None:
    """Filtering by source selects the history of one entity."""
    log = EventLog()
    log.append(_event(1, EventType.WALL_CHANGED, source_id="wall_1"))
    log.append(_event(2, EventType.WALL_CHANGED, source_id="wall_2"))
    log.append(_event(3, EventType.WALL_CHANGED, source_id="wall_1"))
    assert [e.tick for e in log.query(source_id="wall_1")] == [1, 3]


def test_combined_filters_apply_together() -> None:
    """Filters combine with AND, not OR."""
    log = EventLog()
    log.append(_event(1, EventType.WALL_BUILT, source_id="wall_1"))
    log.append(_event(2, EventType.WALL_BUILT, source_id="wall_2"))
    log.append(_event(3, EventType.WALL_CHANGED, source_id="wall_1"))
    log.append(_event(9, EventType.WALL_BUILT, source_id="wall_1"))

    matches = log.query(event_type=EventType.WALL_BUILT, source_id="wall_1", tick_end=5)
    assert [event.tick for event in matches] == [1]


def test_query_returns_results_in_log_order() -> None:
    """Query output preserves insertion order, not tick order or match order."""
    log = EventLog()
    log.append(_event(9, EventType.WALL_BUILT))
    log.append(_event(2, EventType.WALL_BUILT))
    assert [event.tick for event in log.query(event_type=EventType.WALL_BUILT)] == [9, 2]


def test_query_with_no_filters_returns_everything() -> None:
    """An unfiltered query is a full snapshot."""
    log = EventLog()
    log.append(_event(1, EventType.WALL_BUILT))
    log.append(_event(2, EventType.WALL_CHANGED))
    assert log.query() == log.events()


def test_no_mutation_api_exists() -> None:
    """History is append-only: there is deliberately no way to unwrite an event."""
    log = EventLog()
    for forbidden in ("clear", "remove", "pop", "insert", "replace", "extend", "__setitem__"):
        assert not hasattr(log, forbidden), f"EventLog must not expose {forbidden}"


def test_log_does_not_expose_internal_storage_as_an_attribute() -> None:
    """The internal list is private and slotted, so it cannot be swapped out."""
    log = EventLog()
    assert not hasattr(log, "__dict__")
    public_names = [name for name in dir(log) if not name.startswith("_")]
    assert set(public_names) == {"append", "events", "query"}
