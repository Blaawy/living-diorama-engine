"""The contract every simulation system implements.

A system is one causal concern: it reads world state, mutates the part of it
that concern owns, and publishes events describing what it did. Systems never
call one another and never know where they sit in the tick. Execution order is
held solely by ``SimulationLoop``, which is what keeps the order a single
deliberate decision rather than an emergent property of who imports whom.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from living_diorama.events import EventBus

if TYPE_CHECKING:  # pragma: no cover - import exists for typing only
    from living_diorama.simulation.world import World


class BaseSystem(ABC):
    """Abstract base for every system in the simulation pipeline.

    Subclasses implement :meth:`update` and nothing else is required of them.
    A system is stateless by default: everything it needs arrives as arguments,
    and everything it changes lives on the world. A system that genuinely needs
    to carry state across ticks -- hysteresis for a sustained-pressure decision,
    for instance -- may hold it, but that is an explicit choice for that system
    to justify, not the default posture.

    Note:
        ``World`` is imported under ``TYPE_CHECKING`` only. A runtime import
        would make ``systems`` depend on ``simulation``, while ``simulation``
        already depends on ``systems`` for the loop -- a cycle the architecture
        forbids. Deferring the import keeps the runtime dependency graph
        acyclic without giving up a precise type signature.
    """

    __slots__ = ()

    @abstractmethod
    def update(self, world: "World", bus: EventBus) -> None:
        """Advance this system's concern by one tick.

        Called once per tick by ``SimulationLoop``, which supplies the same
        world and bus to every system in the pipeline. The world's tick has
        already been advanced when this runs, so ``world.tick`` is the tick
        being simulated.

        Implementations must not call other systems, read or write files, or
        create their own randomness -- draw from ``world.rng`` so the run stays
        reproducible.

        Args:
            world: The mutable world aggregate to read and update.
            bus: The bus on which to publish events describing what changed.
        """
