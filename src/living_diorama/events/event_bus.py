"""Deterministic synchronous dispatch of events to subscribed handlers.

The bus is a courier, not an interpreter. It knows nothing about what an event
means, which events matter, or who ought to care -- it delivers to whoever
subscribed, in the order they subscribed, and stops there.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import count

from living_diorama.events.event import Event

type EventHandler = Callable[[Event], None]
"""A callable that receives one published event."""


@dataclass(frozen=True, slots=True)
class SubscriptionToken:
    """An opaque handle identifying one subscription.

    Returned by :meth:`EventBus.subscribe` and required by
    :meth:`EventBus.unsubscribe`. Tokens are unique per subscription, so
    subscribing the same callable twice yields two distinct tokens that can be
    cancelled independently.
    """

    _id: int = field(compare=True)


class EventBus:
    """Publishes events to handlers immediately, in subscription order.

    **Dispatch model: immediate synchronous.** ``publish`` delivers to every
    current handler before returning; there is no queue and no ``flush``. The
    alternative -- queueing until an explicit flush -- was rejected because it
    adds a second piece of ordering state that would itself need to be
    deterministic, reasoned about at tick boundaries, and serialized into save
    files. Immediate dispatch keeps "what happened" and "when it was recorded"
    the same moment, which is exactly what an append-only history wants.

    **Ordering.** Handlers run in the order they subscribed. Subscriptions live
    in a list, never a set or dict, so dispatch order never depends on hash
    iteration order.

    **Mutation during dispatch.** ``publish`` iterates a snapshot taken when
    dispatch begins, so a handler that subscribes another handler does not cause
    that new handler to see the current event. Cancellation is checked as
    dispatch proceeds, so a handler that unsubscribes itself -- or another
    handler that has not run yet -- takes effect immediately for the current
    event.

    **Exception policy: fail fast.** If a handler raises, the exception
    propagates and dispatch stops; later handlers do not run. This is
    deliberate. In a deterministic engine a handler failure means the recorded
    history is now incomplete, and continuing would produce a save file that
    looks well-formed while quietly missing part of what happened. A loud stop
    aborts the episode before anything is written. The accepted consequence is
    that handlers earlier in the order have already run and are not rolled back.
    """

    __slots__ = ("_subscriptions", "_token_ids")

    def __init__(self) -> None:
        """Create a bus with no subscribers."""
        self._subscriptions: list[tuple[SubscriptionToken, EventHandler]] = []
        self._token_ids = count()

    def subscribe(self, handler: EventHandler) -> SubscriptionToken:
        """Register a handler to receive every subsequently published event.

        Subscribing the same callable more than once is allowed and meaningful:
        each subscription is independent, gets its own token, and causes one
        additional call per published event.

        Args:
            handler: Callable invoked with each published event.

        Returns:
            A token identifying this subscription.
        """
        token = SubscriptionToken(next(self._token_ids))
        self._subscriptions.append((token, handler))
        return token

    def unsubscribe(self, token: SubscriptionToken) -> bool:
        """Cancel a subscription.

        Args:
            token: The token returned when the handler subscribed.

        Returns:
            True if a subscription was cancelled, False if the token was
            unknown or already cancelled.
        """
        for index, (existing, _) in enumerate(self._subscriptions):
            if existing == token:
                del self._subscriptions[index]
                return True
        return False

    def publish(self, event: Event) -> None:
        """Deliver an event to every current handler, in subscription order.

        Publishing the same event instance twice is permitted and counts as two
        distinct dispatch occurrences; the bus does no deduplication.

        Args:
            event: The event to deliver. Never modified by the bus.

        Raises:
            Exception: Whatever a handler raises, propagated unchanged. Dispatch
                stops at that handler.
        """
        for token, handler in tuple(self._subscriptions):
            if not self._is_subscribed(token):
                continue
            handler(event)

    def _is_subscribed(self, token: SubscriptionToken) -> bool:
        """Return whether a token still identifies a live subscription."""
        return any(existing == token for existing, _ in self._subscriptions)
