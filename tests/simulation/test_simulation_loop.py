"""Tests for SimulationLoop: tick ordering, pipeline fidelity, and failure semantics.

The loop is the single place execution order lives, so these tests are mostly
about proving it runs exactly the pipeline it was handed, exactly once each,
in exactly the supplied order -- and that when something breaks, it breaks
loudly and stops.
"""

import pytest
from simulation_builders import FailingSystem, RecordingSystem, build_world
from living_diorama.events import EventBus
from living_diorama.simulation import SimulationLoop, World


def test_run_zero_ticks_does_nothing() -> None:
    """Zero is a valid request that performs no work."""
    world = build_world(tick=7)
    journal: list[str] = []
    system = RecordingSystem("only", journal)
    SimulationLoop([system], EventBus()).run(world, 0)

    assert world.tick == 7
    assert system.calls == 0


def test_rejects_negative_tick_count() -> None:
    """Time does not run backwards."""
    with pytest.raises(ValueError):
        SimulationLoop([], EventBus()).run(build_world(), -1)


def test_rejects_bool_tick_count() -> None:
    """bool subclasses int, so True would silently run exactly one tick."""
    with pytest.raises(TypeError):
        SimulationLoop([], EventBus()).run(build_world(), True)  # type: ignore[arg-type]


def test_rejects_non_world_argument() -> None:
    """The loop advances a World, not an arbitrary object."""
    with pytest.raises(TypeError):
        SimulationLoop([], EventBus()).run("not-a-world", 1)  # type: ignore[arg-type]


def test_zero_systems_still_advances_time() -> None:
    """Time advancement is proven independently of any domain behavior."""
    world = build_world()
    SimulationLoop([], EventBus()).run(world, 10)
    assert world.tick == 10


def test_tick_advances_before_systems_run() -> None:
    """A system scheduled for tick T observes world.tick == T while it runs.

    This is what will let the future RuleSystem apply a law change at tick T and
    have every downstream system in the same tick see the new law state.
    """
    world = build_world(tick=0)
    journal: list[str] = []
    system = RecordingSystem("observer", journal)
    SimulationLoop([system], EventBus()).run(world, 3)

    assert system.seen_ticks == [1, 2, 3]


def test_systems_execute_in_the_exact_supplied_order() -> None:
    """Pipeline order is the order given, never sorted or inferred."""
    journal: list[str] = []
    systems = [RecordingSystem(name, journal) for name in ("first", "second", "third")]
    SimulationLoop(systems, EventBus()).run(build_world(), 2)

    assert journal == ["first", "second", "third", "first", "second", "third"]


def test_each_system_runs_exactly_once_per_tick() -> None:
    """No system is skipped and none runs twice by accident."""
    journal: list[str] = []
    systems = [RecordingSystem(name, journal) for name in ("a", "b")]
    SimulationLoop(systems, EventBus()).run(build_world(), 4)

    assert [system.calls for system in systems] == [4, 4]


def test_same_world_instance_is_passed_to_every_system() -> None:
    """Systems share one world; nothing is copied between them."""
    world = build_world()
    journal: list[str] = []
    systems = [RecordingSystem(name, journal) for name in ("a", "b")]
    SimulationLoop(systems, EventBus()).run(world, 2)

    for system in systems:
        assert all(seen is world for seen in system.seen_worlds)


def test_same_event_bus_instance_is_passed_to_every_system() -> None:
    """Systems publish to one shared bus, which is the loop's injected bus."""
    bus = EventBus()
    journal: list[str] = []
    systems = [RecordingSystem(name, journal) for name in ("a", "b")]
    loop = SimulationLoop(systems, bus)
    loop.run(build_world(), 2)

    assert loop.event_bus is bus
    for system in systems:
        assert all(seen is bus for seen in system.seen_buses)


def test_duplicate_system_entries_execute_twice_per_tick() -> None:
    """The loop runs exactly the pipeline it receives, repetitions included.

    Treating a repeat as a mistake would require domain knowledge the loop does
    not have, so duplicates are honoured deliberately.
    """
    journal: list[str] = []
    system = RecordingSystem("repeated", journal)
    SimulationLoop([system, system], EventBus()).run(build_world(), 1)

    assert journal == ["repeated", "repeated"]
    assert system.calls == 2


def test_system_sequence_is_defensively_copied() -> None:
    """Mutating the caller's list after construction cannot change the pipeline."""
    journal: list[str] = []
    first = RecordingSystem("first", journal)
    supplied = [first]
    loop = SimulationLoop(supplied, EventBus())

    supplied.append(RecordingSystem("smuggled", journal))
    supplied.clear()

    loop.run(build_world(), 1)
    assert journal == ["first"]


def test_systems_property_is_an_immutable_tuple() -> None:
    """The pipeline is exposed as a tuple, so it cannot be reordered in place."""
    journal: list[str] = []
    loop = SimulationLoop([RecordingSystem("only", journal)], EventBus())
    assert isinstance(loop.systems, tuple)


def test_constructor_rejects_non_systems() -> None:
    """Only BaseSystem implementations may enter the pipeline."""
    with pytest.raises(TypeError):
        SimulationLoop(["not-a-system"], EventBus())  # type: ignore[list-item]


def test_constructor_rejects_a_non_bus() -> None:
    """The loop needs a real bus to hand to its systems."""
    with pytest.raises(TypeError):
        SimulationLoop([], "not-a-bus")  # type: ignore[arg-type]


def test_system_exception_stops_remaining_systems_in_the_current_tick() -> None:
    """Fail fast: later systems in the failing tick do not run."""
    journal: list[str] = []
    systems = [
        RecordingSystem("before", journal),
        FailingSystem(journal, RuntimeError("system failed")),
        RecordingSystem("after", journal),
    ]
    with pytest.raises(RuntimeError):
        SimulationLoop(systems, EventBus()).run(build_world(), 1)

    assert journal == ["before", "failing"]


def test_system_exception_prevents_later_ticks() -> None:
    """A failed tick ends the run; the loop does not carry on to the next tick."""
    world = build_world(tick=0)
    journal: list[str] = []
    systems = [
        RecordingSystem("before", journal),
        FailingSystem(journal, RuntimeError("system failed")),
    ]
    with pytest.raises(RuntimeError):
        SimulationLoop(systems, EventBus()).run(world, 100)

    assert world.tick == 1
    assert journal == ["before", "failing"]


def test_completed_mutations_are_not_rolled_back() -> None:
    """The loop keeps no undo log; a partial tick is abandoned, not repaired."""
    world = build_world(tick=0)
    journal: list[str] = []
    systems = [
        RecordingSystem("before", journal),
        FailingSystem(journal, RuntimeError("system failed")),
    ]
    with pytest.raises(RuntimeError):
        SimulationLoop(systems, EventBus()).run(world, 3)

    assert world.tick == 1
    assert systems[0].calls == 1  # type: ignore[union-attr]


def test_exceptions_propagate_unchanged() -> None:
    """The original exception object reaches the caller, not a wrapped substitute."""
    journal: list[str] = []
    error = ValueError("a very specific failure")
    with pytest.raises(ValueError) as caught:
        SimulationLoop([FailingSystem(journal, error)], EventBus()).run(build_world(), 1)

    assert caught.value is error


def test_loop_does_not_consume_or_replace_the_world_rng() -> None:
    """Randomness belongs to the world; the loop never touches it."""
    world = build_world(seed=1234)
    rng_before = world.rng
    state_before = world.rng.get_state()

    SimulationLoop([], EventBus()).run(world, 25)

    assert world.rng is rng_before
    assert world.rng.get_state() == state_before


def test_loop_subscribes_nothing_to_the_bus() -> None:
    """Wiring an EventLog is the composition root's job, not the loop's."""
    bus = EventBus()
    SimulationLoop([], bus).run(build_world(), 3)

    received: list[object] = []
    bus.subscribe(received.append)
    assert received == []


def test_running_the_same_world_twice_continues_from_where_it_stopped() -> None:
    """Ticks accumulate on the world, so a run resumes rather than restarting."""
    world = build_world()
    loop = SimulationLoop([], EventBus())
    loop.run(world, 5)
    loop.run(world, 5)
    assert world.tick == 10


def test_loop_exposes_only_its_intended_api() -> None:
    """The loop is a narrow orchestrator with nothing else bolted on."""
    loop = SimulationLoop([], EventBus())
    public_names = {name for name in dir(loop) if not name.startswith("_")}
    assert public_names == {"run", "systems", "event_bus"}


def test_world_argument_is_the_only_state_the_loop_touches() -> None:
    """Two worlds can be advanced by one loop without interfering."""
    loop = SimulationLoop([], EventBus())
    first, second = build_world(), build_world()
    loop.run(first, 3)
    loop.run(second, 7)
    assert (first.tick, second.tick) == (3, 7)


def test_world_type_is_exported_for_systems_to_annotate() -> None:
    """Systems annotate against the exported World, which must be the real class."""
    assert isinstance(build_world(), World)
