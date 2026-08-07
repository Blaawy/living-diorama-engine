"""Deciding which events become permanent history.

Significance is a fixed rule, not a judgement. An event becomes a durable fact
only when its type is one of the two the MVP remembers *and* the final state of
the episode still corroborates it. That second half matters: an event says
something was published, not that the world ended the episode agreeing with it.

Processing runs once, after the episode has finished. A live subscriber would
see a restoration the instant it was published -- before the systems that run
later in the same tick had finished -- and would record a claim about a world
state that did not exist yet.

The rule itself lives in :mod:`living_diorama.memory._integrity`, shared with the
validators that check a memory offered for saving or read back from disk. One
definition, enforced everywhere.
"""

from living_diorama.events import EventLog
from living_diorama.memory._integrity import (
    expected_episode_facts,
    snapshot_event_log,
    snapshot_world_memory,
    validate_memory_transition_events,
)
from living_diorama.memory.world_memory import WorldMemory, _is_runtime_instance, require_exact_int
from living_diorama.simulation.world import World

__all__ = ["MemorySignificance"]


class MemorySignificance:
    """Turns one finished episode into new durable facts.

    Holds no state between calls and reads nothing but what it is given: the
    final world, the complete ordered log, and the memory carried in from the
    previous episode. Every fact is computed before any is returned, so an
    inconsistency anywhere aborts the whole distillation rather than yielding a
    partial history that would then be saved as though it were complete.
    """

    __slots__ = ()

    def distill_episode(
        self, *, world: World, event_log: EventLog, previous_memory: WorldMemory | None
    ) -> WorldMemory:
        """Return the cumulative memory after processing this episode.

        The result is validated as a transition before it is returned. That is
        deliberately redundant with the rules used to build it: if distillation
        and validation ever disagreed, the disagreement would surface here rather
        than later, when a save built by one and checked by the other failed for
        reasons neither explained.

        Args:
            world: The world as the episode left it. Not modified.
            event_log: The episode's complete history, in order. Read exactly
                once and not modified.
            previous_memory: Memory carried in from the previous episode.
                ``None`` is accepted only as a spelling of an unprocessed memory.

        Returns:
            A new cumulative memory, checkpointed to this episode.

        Raises:
            TypeError: If an argument is of the wrong type, or a stored value is.
            ValueError: If the episode does not follow the memory's checkpoint,
                the log is inconsistent with the world, or a significant event is
                contradicted by the final state.
        """
        if not _is_runtime_instance(world, World):
            raise TypeError(f"world must be a World, got {type(world).__name__}")
        if not _is_runtime_instance(event_log, EventLog):
            raise TypeError(f"event_log must be an EventLog, got {type(event_log).__name__}")
        # Normalized before anything is read from it twice: a WorldMemory
        # subclass could otherwise report one history to the chronology checks
        # and another to the prefix comparison.
        memory = (
            WorldMemory.empty()
            if previous_memory is None
            else snapshot_world_memory(previous_memory, "previous_memory")
        )

        episode = require_exact_int(world.episode, "world.episode")
        tick = require_exact_int(world.tick, "world.tick")

        # Read once, and normalized. Capturing the sequence freezes which events
        # are in the log; rebuilding each one as an exact base Event freezes what
        # they say. Without the second half, a stateful Event subclass could be
        # classified against one payload and validated against another.
        events = snapshot_event_log(event_log)

        new_facts = expected_episode_facts(world=world, events=events, previous_memory=memory)
        distilled = memory.advance(episode=episode, tick=tick, new_facts=new_facts)

        validate_memory_transition_events(
            previous_memory=memory,
            current_memory=distilled,
            world=world,
            events=events,
        )
        return distilled
