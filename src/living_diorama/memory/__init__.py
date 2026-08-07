"""Durable, cumulative world history distilled from events.

WorldMemory carries the complete significant-fact history forward across
episodes, so that every episode's save is self-contained and reloadable
without requiring earlier episode folders. See ``docs/architecture.md``
section 13 for the (not-yet-implemented) Post-MVP compaction decision.

This package decides what is worth remembering. It reads entities, events, and
the world aggregate; it must never import persistence, systems, rendering,
narration, or the CLI. Persistence depends on this package, not the reverse:
storage serializes memory, it does not judge significance.
"""

from living_diorama.memory.memory_query import MemoryQuery
from living_diorama.memory.memory_significance import MemorySignificance
from living_diorama.memory.world_memory import MemoryFact, MemoryFactType, WorldMemory

# The five domain classes a consumer needs. The significance vocabulary and the
# transition validator are deliberately absent: they are how the rules are
# enforced, not choices a caller makes, and exporting them would invite
# dependence on internals that exist in order to change. Persistence reaches the
# validator through ``living_diorama.memory._integrity``, private by name and by
# intent.
__all__ = [
    "MemoryFact",
    "MemoryFactType",
    "MemoryQuery",
    "MemorySignificance",
    "WorldMemory",
]
