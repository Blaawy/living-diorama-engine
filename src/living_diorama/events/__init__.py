"""The vocabulary of "what happened": Event, EventBus, and EventLog.

EventLog is scoped to the current episode only -- it starts empty at the top of
every episode. See ``living_diorama.memory`` for how events later become
durable, cumulative facts that persist across episodes.

The bus does not know the log exists. A log subscribes like any other handler,
which is what lets systems publish to one place without knowing who records it.
"""

from living_diorama.events.event import Event, EventType, JsonValue
from living_diorama.events.event_bus import EventBus, EventHandler, SubscriptionToken
from living_diorama.events.event_log import EventLog

__all__ = [
    "Event",
    "EventBus",
    "EventHandler",
    "EventLog",
    "EventType",
    "JsonValue",
    "SubscriptionToken",
]
