"""Tests for EventBus dispatch order, subscription lifecycle, and failure policy.

The bus is where determinism could quietly leak away: if dispatch order ever
depended on hashing, or if mutating the subscriber list mid-dispatch behaved
differently run to run, episodes would stop replaying identically. These tests
pin down the exact semantics rather than the happy path alone.
"""

import pytest

from living_diorama.events import Event, EventBus, EventLog, EventType


def _event(tick: int = 1) -> Event:
    """Build a small event for bus tests."""
    return Event(tick=tick, type=EventType.WALL_BUILT, payload={"n": tick})


def test_handlers_run_in_subscription_order() -> None:
    """Dispatch order equals subscription order, never hash or set order."""
    calls: list[str] = []
    bus = EventBus()
    for name in ("first", "second", "third", "fourth"):
        bus.subscribe(lambda _event, name=name: calls.append(name))  # type: ignore[misc]
    bus.publish(_event())
    assert calls == ["first", "second", "third", "fourth"]


def test_handler_receives_the_published_event() -> None:
    """The handler gets the exact instance that was published."""
    received: list[Event] = []
    bus = EventBus()
    bus.subscribe(received.append)
    event = _event()
    bus.publish(event)
    assert received == [event]
    assert received[0] is event


def test_publish_with_no_subscribers_is_a_no_op() -> None:
    """An event with nobody listening is not an error."""
    EventBus().publish(_event())


def test_unsubscribe_stops_future_delivery() -> None:
    """A cancelled subscription receives nothing further."""
    calls: list[Event] = []
    bus = EventBus()
    token = bus.subscribe(calls.append)
    bus.publish(_event(1))
    assert bus.unsubscribe(token) is True
    bus.publish(_event(2))
    assert [event.tick for event in calls] == [1]


def test_unsubscribe_returns_false_for_unknown_or_repeated_tokens() -> None:
    """Cancelling twice reports honestly instead of raising."""
    bus = EventBus()
    token = bus.subscribe(lambda _event: None)
    assert bus.unsubscribe(token) is True
    assert bus.unsubscribe(token) is False


def test_handler_can_unsubscribe_itself_during_dispatch() -> None:
    """Self-cancellation mid-dispatch must not corrupt the iteration."""
    calls: list[int] = []
    bus = EventBus()

    def once(event: Event) -> None:
        """Record the tick, then cancel this subscription."""
        calls.append(event.tick)
        bus.unsubscribe(token)

    token = bus.subscribe(once)
    bus.publish(_event(1))
    bus.publish(_event(2))
    assert calls == [1]


def test_handler_unsubscribing_a_later_handler_takes_effect_immediately() -> None:
    """Cancellation is honoured within the current dispatch, not only the next one."""
    calls: list[str] = []
    bus = EventBus()

    def first(_event: Event) -> None:
        """Record a call, then cancel the handler queued after this one."""
        calls.append("first")
        bus.unsubscribe(second_token)

    bus.subscribe(first)
    second_token = bus.subscribe(lambda _event: calls.append("second"))
    bus.publish(_event())
    assert calls == ["first"]


def test_subscribing_during_dispatch_does_not_deliver_the_current_event() -> None:
    """A handler added mid-dispatch starts from the next event, not this one."""
    calls: list[str] = []
    bus = EventBus()

    def adder(_event: Event) -> None:
        """Record a call, then subscribe an additional handler mid-dispatch."""
        calls.append("adder")
        bus.subscribe(lambda _e: calls.append("late"))

    bus.subscribe(adder)
    bus.publish(_event(1))
    assert calls == ["adder"]

    bus.publish(_event(2))
    assert calls == ["adder", "adder", "late"]


def test_duplicate_subscription_of_the_same_callable_is_independent() -> None:
    """Subscribing twice means being called twice, with separately cancellable tokens."""
    calls: list[Event] = []
    bus = EventBus()
    first_token = bus.subscribe(calls.append)
    bus.subscribe(calls.append)

    bus.publish(_event(1))
    assert len(calls) == 2

    assert bus.unsubscribe(first_token) is True
    bus.publish(_event(2))
    assert len(calls) == 3


def test_handler_exception_propagates_and_stops_dispatch() -> None:
    """Fail-fast: a broken handler aborts the run rather than silently losing history."""
    calls: list[str] = []
    bus = EventBus()

    def boom(_event: Event) -> None:
        """Record a call, then fail, to exercise the fail-fast policy."""
        calls.append("boom")
        raise RuntimeError("handler failed")

    bus.subscribe(lambda _event: calls.append("before"))
    bus.subscribe(boom)
    bus.subscribe(lambda _event: calls.append("after"))

    with pytest.raises(RuntimeError):
        bus.publish(_event())

    assert calls == ["before", "boom"]


def test_bus_remains_usable_after_a_handler_raises() -> None:
    """The bus keeps no broken internal state after a failed dispatch."""
    bus = EventBus()

    def always_fails(_event: Event) -> None:
        """Always raise, to leave the bus mid-dispatch."""
        raise RuntimeError("handler failed")

    failing = bus.subscribe(always_fails)
    with pytest.raises(RuntimeError):
        bus.publish(_event())

    bus.unsubscribe(failing)
    calls: list[Event] = []
    bus.subscribe(calls.append)
    bus.publish(_event(2))
    assert len(calls) == 1


def test_event_log_subscribes_like_any_other_handler() -> None:
    """The log is not wired into the bus; it subscribes as an ordinary handler."""
    bus = EventBus()
    log = EventLog()
    bus.subscribe(log.append)

    published = [_event(tick) for tick in (1, 2, 3)]
    for event in published:
        bus.publish(event)

    assert list(log.events()) == published


def test_multiple_logs_can_subscribe_independently() -> None:
    """Nothing about the bus assumes a single recorder."""
    bus = EventBus()
    first, second = EventLog(), EventLog()
    bus.subscribe(first.append)
    bus.subscribe(second.append)
    bus.publish(_event())
    assert len(first) == 1
    assert len(second) == 1


def test_publishing_the_same_instance_twice_is_two_dispatches() -> None:
    """The bus does no deduplication: each publication is its own occurrence."""
    bus = EventBus()
    log = EventLog()
    bus.subscribe(log.append)

    event = _event()
    bus.publish(event)
    bus.publish(event)

    assert len(log) == 2
    assert log.events()[0] is log.events()[1]


def test_bus_does_not_mutate_event_payloads() -> None:
    """Delivery is read-only; the event a handler receives is untouched."""
    bus = EventBus()
    bus.subscribe(lambda _event: None)
    event = Event(tick=1, type=EventType.LAW_CHANGED, payload={"a": [1, 2]})
    before = event.payload_as_dict()
    bus.publish(event)
    assert event.payload_as_dict() == before


def test_bus_exposes_only_its_intended_api() -> None:
    """No flush, no queue: this bus dispatches immediately and says so."""
    bus = EventBus()
    public_names = {name for name in dir(bus) if not name.startswith("_")}
    assert public_names == {"subscribe", "unsubscribe", "publish"}
