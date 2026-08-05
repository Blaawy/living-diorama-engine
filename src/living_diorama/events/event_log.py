"""Append-only record of the events published during the current episode.

The log is scoped to one episode. It starts empty at the top of every episode
and is written out as that episode's raw record. There is deliberately no way
to remove, replace, or clear an entry: history that could be edited would not
be history.
"""

from collections.abc import Iterator

from living_diorama.entities import EntityId, Tick
from living_diorama.events.event import Event, EventType


class EventLog:
    """An ordered, append-only collection of events for one episode.

    The log itself is mutable -- appending is its whole job -- but every event
    inside it is immutable, and the internal list is never handed out. Reads go
    through :meth:`events` or :meth:`query`, both of which return detached
    tuples.

    This class is not wired into the EventBus. It subscribes to the bus like any
    other handler (``bus.subscribe(log.append)``), which keeps the bus unaware
    of who is listening.
    """

    __slots__ = ("_events",)

    def __init__(self) -> None:
        """Create an empty log for a new episode."""
        self._events: list[Event] = []

    def append(self, event: Event) -> None:
        """Record one event at the end of the log.

        Args:
            event: The event to record.
        """
        self._events.append(event)

    def events(self) -> tuple[Event, ...]:
        """Return an immutable snapshot of the log in insertion order.

        Returns:
            A tuple detached from internal storage, so later appends do not
            change a snapshot already handed out.
        """
        return tuple(self._events)

    def query(
        self,
        *,
        event_type: EventType | None = None,
        tick_start: Tick | None = None,
        tick_end: Tick | None = None,
        source_id: EntityId | None = None,
    ) -> tuple[Event, ...]:
        """Return the events matching every filter supplied, in log order.

        Filters combine with AND. Omitted filters place no constraint. The tick
        range is inclusive at both ends, so a single tick is selected by passing
        the same value for both bounds.

        Args:
            event_type: Keep only events of this type.
            tick_start: Keep only events at or after this tick.
            tick_end: Keep only events at or before this tick.
            source_id: Keep only events carrying this source identifier.

        Returns:
            A tuple of matching events in insertion order.
        """
        matches: list[Event] = []
        for event in self._events:
            if event_type is not None and event.type is not event_type:
                continue
            if tick_start is not None and event.tick < tick_start:
                continue
            if tick_end is not None and event.tick > tick_end:
                continue
            if source_id is not None and event.source_id != source_id:
                continue
            matches.append(event)
        return tuple(matches)

    def __iter__(self) -> Iterator[Event]:
        """Iterate the log in insertion order over a detached snapshot."""
        return iter(self.events())

    def __len__(self) -> int:
        """Return how many events have been recorded."""
        return len(self._events)
