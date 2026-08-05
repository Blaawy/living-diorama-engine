"""The tick loop: the one place that knows system execution order.

The loop is a generic orchestrator. It holds no domain knowledge, makes no
decisions about what should happen, and never inspects what a system did. It
advances time and runs the pipeline it was handed, in the order it was handed
it -- which is precisely why the order is reviewable as a single decision
rather than scattered across the systems themselves.
"""

from collections.abc import Sequence

from living_diorama.events import EventBus
from living_diorama.simulation.world import World
from living_diorama.systems import BaseSystem


class SimulationLoop:
    """Runs a fixed, ordered pipeline of systems for a number of ticks.

    **Tick ordering: advance first, then run systems.** Each iteration
    increments ``world.tick`` and only then calls the systems, so every system
    observes the tick it is simulating. The alternative -- run systems, then
    advance -- would mean a system scheduled to act "at tick T" acts while the
    world still reads T-1, and its effects would land a tick late. That matters
    directly for the later RuleSystem: a law scheduled for tick T must take
    effect while ``world.tick == T``, so that every downstream system in the
    same tick already sees the new law state.

    **Order is exactly what was supplied.** The sequence is defensively copied
    into a tuple at construction, so a caller mutating their original list
    afterwards cannot change the pipeline mid-run. The loop never sorts,
    reorders, infers order from names, discovers systems, or stores them in any
    unordered container.

    **Duplicates are permitted.** A system appearing twice runs twice per tick.
    The loop executes exactly the pipeline it receives; deciding that a
    repetition is a mistake would require domain knowledge the loop does not
    have, and there are legitimate pipelines where a stage genuinely runs twice.

    **Failures stop everything.** See :meth:`run`.

    The loop never creates, reseeds, replaces, or draws from the world's RNG.
    Randomness belongs to the world, and systems consume it through
    ``world.rng``.
    """

    __slots__ = ("_event_bus", "_systems")

    def __init__(self, systems: Sequence[BaseSystem], event_bus: EventBus) -> None:
        """Create a loop over an ordered pipeline.

        The bus is injected rather than created internally so tests and the
        future composition root can decide what is subscribed to it. The loop
        deliberately subscribes nothing itself -- wiring an EventLog is the
        composition root's job.

        Args:
            systems: The pipeline, in execution order. May be empty, which is
                useful for proving time advancement independently of behavior.
            event_bus: The bus handed to every system on every tick.

        Raises:
            TypeError: If the bus is not an EventBus, or if any element of the
                pipeline is not a BaseSystem.
        """
        if not isinstance(event_bus, EventBus):
            raise TypeError(f"event_bus must be an EventBus, got {type(event_bus).__name__}")

        ordered = tuple(systems)
        for index, system in enumerate(ordered):
            if not isinstance(system, BaseSystem):
                raise TypeError(
                    f"systems[{index}] must be a BaseSystem, got {type(system).__name__}"
                )

        self._systems: tuple[BaseSystem, ...] = ordered
        self._event_bus = event_bus

    @property
    def systems(self) -> tuple[BaseSystem, ...]:
        """The pipeline in execution order, as an immutable tuple."""
        return self._systems

    @property
    def event_bus(self) -> EventBus:
        """The bus handed to every system on every tick."""
        return self._event_bus

    def run(self, world: World, ticks: int) -> None:
        """Advance the world by the given number of ticks.

        Each tick advances ``world.tick`` exactly once, then calls every system
        exactly once in pipeline order, passing the same world and the same bus
        to each.

        **Failure semantics.** If a system raises, the exception propagates
        unchanged: remaining systems in the current tick do not run, no further
        ticks are attempted, and nothing already mutated is rolled back. The
        loop keeps no undo log and does not try to repair a partially-updated
        world -- a half-finished tick is not a state the engine can reason
        about, so the run stops and the episode is abandoned before anything is
        written to disk. Swallowing the error would be worse: the run would
        continue from a world missing part of a tick, and the resulting save
        would look well-formed while being quietly wrong.

        Args:
            world: The world to advance. Mutated in place.
            ticks: How many ticks to run. Zero is valid and does nothing.

        Raises:
            TypeError: If ``world`` is not a World, or ``ticks`` is not an int.
            ValueError: If ``ticks`` is negative.
            Exception: Whatever a system raises, propagated unchanged.
        """
        if not isinstance(world, World):
            raise TypeError(f"world must be a World, got {type(world).__name__}")
        if type(ticks) is not int:
            raise TypeError(f"ticks must be an int, got {type(ticks).__name__}")
        if ticks < 0:
            raise ValueError(f"ticks must be >= 0, got {ticks}")

        for _ in range(ticks):
            world.advance_tick()
            for system in self._systems:
                system.update(world, self._event_bus)
