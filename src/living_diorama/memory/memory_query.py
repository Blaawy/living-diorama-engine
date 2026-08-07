"""Read-only questions about what the world remembers.

A query never changes memory, never reaches the filesystem, and never draws a
random number. It filters and it orders; everything it returns is a tuple, so a
caller holding a result cannot reach back into the history through it.
"""

from living_diorama.entities import EntityId
from living_diorama.events import EventType
from living_diorama.memory._integrity import snapshot_world_memory
from living_diorama.memory.world_memory import (
    MemoryFact,
    MemoryFactType,
    WorldMemory,
    require_exact_int,
    require_identifier,
)


class MemoryQuery:
    """Filters a world's remembered facts without altering them.

    Filters combine with AND, and results always come back in the memory's own
    canonical order. That matters for the narration phase this exists to feed:
    a caller asking for the most recent facts still wants to read them forwards,
    in the order the world actually lived them.
    """

    __slots__ = ("_memory",)

    def __init__(self, memory: WorldMemory) -> None:
        """Create a query over one memory.

        The memory is normalized into exact base objects on the way in, so a
        query answers from one fixed history rather than from whatever the caller
        happens to report at the moment each question is asked.

        Args:
            memory: The memory to read. Never modified.

        Raises:
            TypeError: If the argument is not a ``WorldMemory``, or a fact is not
                a ``MemoryFact``.
            ValueError: If a fact's claimed identifier or summary is not what its
                content implies.
        """
        self._memory = snapshot_world_memory(memory, "memory")

    @property
    def memory(self) -> WorldMemory:
        """The memory this query reads."""
        return self._memory

    def facts(
        self,
        *,
        fact_type: MemoryFactType | None = None,
        episode: int | None = None,
        tick_start: int | None = None,
        tick_end: int | None = None,
        source_event_type: EventType | None = None,
        source_id: EntityId | None = None,
        subject_id: EntityId | None = None,
    ) -> tuple[MemoryFact, ...]:
        """Return every remembered fact matching all supplied filters.

        Args:
            fact_type: Keep only facts of this kind.
            episode: Keep only facts from this episode.
            tick_start: Keep only facts at or after this tick.
            tick_end: Keep only facts at or before this tick.
            source_event_type: Keep only facts derived from this event type.
            source_id: Keep only facts whose source event named this entity.
            subject_id: Keep only facts concerning this entity in any role.

        Returns:
            Matching facts, in canonical order.

        Raises:
            TypeError: If a filter is of the wrong type.
            ValueError: If a bound is negative or the range is inverted.
        """
        if fact_type is not None and type(fact_type) is not MemoryFactType:
            raise TypeError(f"fact_type must be a MemoryFactType, got {type(fact_type).__name__}")
        if source_event_type is not None and type(source_event_type) is not EventType:
            raise TypeError(
                f"source_event_type must be an EventType, got {type(source_event_type).__name__}"
            )
        if episode is not None:
            require_exact_int(episode, "episode")
        if tick_start is not None:
            require_exact_int(tick_start, "tick_start")
        if tick_end is not None:
            require_exact_int(tick_end, "tick_end")
        if tick_start is not None and tick_end is not None and tick_start > tick_end:
            raise ValueError(
                f"tick_start {tick_start} is after tick_end {tick_end}; the range is inclusive"
            )
        if source_id is not None:
            require_identifier(source_id, "source_id")
        if subject_id is not None:
            require_identifier(subject_id, "subject_id")

        return tuple(
            fact
            for fact in self._memory.facts
            if (fact_type is None or fact.fact_type is fact_type)
            and (episode is None or fact.episode == episode)
            and (tick_start is None or fact.tick >= tick_start)
            and (tick_end is None or fact.tick <= tick_end)
            and (source_event_type is None or fact.source_event_type is source_event_type)
            and (source_id is None or fact.source_id == source_id)
            and (subject_id is None or subject_id in fact.subject_ids)
        )

    def narration_context(
        self,
        *,
        limit: int | None = None,
        fact_type: MemoryFactType | None = None,
        subject_id: EntityId | None = None,
    ) -> tuple[str, ...]:
        """Return matching fact summaries, ready for a later narration phase.

        The summaries are the deterministic sentences stored on each fact. None
        of them is generated here, reworded, or ranked -- this returns what the
        world already recorded about itself.

        Args:
            limit: At most this many summaries, taken from the most recent
                matching facts. ``None`` returns all of them; ``0`` returns none.
            fact_type: Keep only facts of this kind.
            subject_id: Keep only facts concerning this entity.

        Returns:
            Summaries in chronological order. A limit selects the latest facts
            and then reads them forwards, because a recap is still told in the
            order things happened.

        Raises:
            TypeError: If a filter or the limit is of the wrong type.
            ValueError: If the limit is negative.
        """
        matching = self.facts(fact_type=fact_type, subject_id=subject_id)
        if limit is not None:
            require_exact_int(limit, "limit")
            if limit == 0:
                return ()
            matching = matching[-limit:]
        return tuple(fact.summary for fact in matching)
