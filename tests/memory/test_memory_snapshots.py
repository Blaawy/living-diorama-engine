"""Tests for reading each mutable input exactly once.

A mapping and an event log are both objects the caller owns and may change. A
check performed on one reading proves nothing about a later reading, so the fix
is not a stricter check but a single read: validation and use must be looking at
the same thing.

The failure this prevents is not theoretical. Candidate V4 read an episode's log
five times during one distillation, and a log that answered differently each time
could make an episode remember a fact its own chronology never saw -- or let
SaveManager publish an episode that the same implementation could not reload.
"""

import tempfile
from collections.abc import Mapping
from pathlib import Path

import pytest

from living_diorama.events import Event, EventLog, EventType
from living_diorama.memory import MemoryFact, MemorySignificance, WorldMemory
from living_diorama.memory._integrity import (
    snapshot_event_log,
    snapshot_memory_fact,
    snapshot_world_memory,
    validate_memory_transition,
    validate_memory_transition_events,
)
from living_diorama.persistence import SaveManager
from living_diorama.persistence.json_codec import loads_canonical
from living_diorama.persistence.schema.world_schema_v1 import (
    EVENT_LOG_FILE,
    MANIFEST_FILE,
)
from memory.conftest import (
    WALL_ID,
    log_of,
    wall_built_event,
    wall_built_fact,
    world_with_wall,
)

EMPTY: tuple[Event, ...] = ()
"""A snapshot in which nothing happened."""


class StringSubclass(str):
    """A ``str`` subclass: equal to a plain string, and not one."""


class CountingMapping(Mapping):
    """A mapping that records how many times it has been iterated.

    Lookups always behave normally. Only iteration is instrumented, because
    iteration is what reveals a document's actual shape.
    """

    def __init__(self, base: Mapping, *, disguise_after: int | None = None) -> None:
        """Wrap a document, optionally disguising keys after a chosen pass."""
        self._base = dict(base)
        self.iterations = 0
        self._disguise_after = disguise_after

    def __getitem__(self, key: object) -> object:
        """Answer lookups exactly as the underlying document would."""
        return self._base[key]

    def __len__(self) -> int:
        """Report the underlying document's size."""
        return len(self._base)

    def __iter__(self):
        """Expose ordinary keys, then subclass keys once the pass count is past."""
        self.iterations += 1
        disguised = self._disguise_after is not None and self.iterations > self._disguise_after
        for key in self._base:
            yield StringSubclass(key) if disguised else key


class RepeatingKeyMapping(Mapping):
    """A mapping that exposes one key twice while iterating."""

    def __init__(self, base: Mapping, *, repeated: str) -> None:
        """Wrap a document, repeating one of its keys on iteration."""
        self._base = dict(base)
        self._repeated = repeated

    def __getitem__(self, key: object) -> object:
        """Answer lookups exactly as the underlying document would."""
        return self._base[key]

    def __len__(self) -> int:
        """Report one more than the underlying size, matching what is yielded."""
        return len(self._base) + 1

    def __iter__(self):
        """Yield every key, and the chosen one a second time."""
        yield from self._base
        yield self._repeated


class ScriptedLog(EventLog):
    """An EventLog that answers with a scripted history and counts the asking.

    A legitimate subclass. The point is not that a subclass is suspicious but
    that ``EventLog`` is mutable at all: an ordinary one could change between two
    readings just as easily, and the guarantee has to be one snapshot rather than
    a ban on subclasses.
    """

    __slots__ = ("_script", "calls")

    def __init__(self, script) -> None:
        """Prepare the sequence of histories this log will hand out."""
        super().__init__()
        self._script = list(script)
        self.calls = 0

    def events(self) -> tuple[Event, ...]:
        """Return the next scripted history, repeating the last one forever."""
        snapshot = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        return tuple(snapshot)


def built_event() -> Event:
    """Return the wall-construction event episode zero publishes."""
    return wall_built_event(tick=120)


def corrupt_event() -> Event:
    """Return an event whose stored type is a string rather than an EventType."""
    event = wall_built_event(tick=120)
    object.__setattr__(event, "type", "WALL_BUILT")
    return event


def built_memory() -> WorldMemory:
    """Return the memory a genuine wall-building episode produces."""
    return MemorySignificance().distill_episode(
        world=world_with_wall(tick=120),
        event_log=log_of(built_event()),
        previous_memory=WorldMemory.empty(),
    )


# --- Defect A: one validated snapshot of a fact document --------------------


def test_the_shifting_mapping_really_does_change_between_passes() -> None:
    """Guards the technique: without the shift the tests below prove nothing."""
    document = wall_built_fact().to_document()
    shifting = CountingMapping(document, disguise_after=1)

    first = list(shifting)
    second = list(shifting)
    assert all(type(key) is str for key in first)
    assert all(type(key) is StringSubclass for key in second)
    assert first == second, "the two passes are indistinguishable by comparison"


def test_a_document_is_read_exactly_once() -> None:
    """One read is what makes the validation and the reconstruction agree."""
    document = wall_built_fact().to_document()
    counting = CountingMapping(document)

    assert MemoryFact.from_document(counting) == wall_built_fact()
    assert counting.iterations == 1


def test_a_mapping_that_shifts_after_validation_cannot_smuggle_subclass_keys() -> None:
    """Candidate V4 validated one shape and then reconstructed from another."""
    document = wall_built_fact().to_document()
    shifting = CountingMapping(document, disguise_after=1)

    fact = MemoryFact.from_document(shifting)

    assert shifting.iterations == 1, "the later, disguised passes never happen"
    assert fact == wall_built_fact()
    assert all(type(key) is str for key in fact.to_document())


def test_a_mapping_disguised_on_its_very_first_pass_is_refused() -> None:
    """The single read is the authoritative one, so it is the one checked."""
    document = wall_built_fact().to_document()
    disguised = CountingMapping(document, disguise_after=0)

    with pytest.raises(TypeError):
        MemoryFact.from_document(disguised)
    assert disguised.iterations == 1


def test_a_rejected_mapping_is_read_once_and_left_alone() -> None:
    """Refusal reads no more than acceptance does, and repairs nothing."""
    document = wall_built_fact().to_document()
    disguised = CountingMapping(document, disguise_after=0)
    before = list(disguised._base)

    with pytest.raises(TypeError):
        MemoryFact.from_document(disguised)

    assert disguised.iterations == 1
    assert list(disguised._base) == before
    assert all(type(key) is str for key in disguised._base)


def test_a_mapping_exposing_a_duplicate_key_is_refused() -> None:
    """A document cannot carry one key twice, whatever its size claims."""
    document = wall_built_fact().to_document()
    with pytest.raises(ValueError):
        MemoryFact.from_document(RepeatingKeyMapping(document, repeated="fact_id"))


def test_a_stable_mapping_with_one_subclass_key_still_raises() -> None:
    """The Candidate V4 correction is unchanged."""
    document = wall_built_fact().to_document()
    disguised = {key: value for key, value in document.items() if key != "fact_id"}
    disguised[StringSubclass("fact_id")] = document["fact_id"]

    with pytest.raises(TypeError):
        MemoryFact.from_document(disguised)


def test_an_ordinary_dict_still_loads() -> None:
    """The control case."""
    fact = wall_built_fact()
    assert MemoryFact.from_document(fact.to_document()) == fact


def test_no_key_is_coerced() -> None:
    """Nothing is passed through ``str()`` to make it acceptable."""
    document = wall_built_fact().to_document()
    document[StringSubclass("summary")] = document.pop("summary")

    with pytest.raises(TypeError):
        MemoryFact.from_document(document)
    assert any(type(key) is StringSubclass for key in document)


# --- Defect B: one snapshot of the episode log ------------------------------


def test_distillation_reads_the_event_log_exactly_once() -> None:
    """Five readings were five opportunities to disagree."""
    log = ScriptedLog([(built_event(),)])
    memory = MemorySignificance().distill_episode(
        world=world_with_wall(tick=120), event_log=log, previous_memory=WorldMemory.empty()
    )

    assert log.calls == 1
    assert len(memory) == 1


def test_the_first_snapshot_is_authoritative_when_the_log_empties() -> None:
    """What the log said when it was asked is what the episode remembers."""
    log = ScriptedLog([(built_event(),), EMPTY, EMPTY, EMPTY, EMPTY])
    memory = MemorySignificance().distill_episode(
        world=world_with_wall(tick=120), event_log=log, previous_memory=WorldMemory.empty()
    )

    assert len(memory) == 1
    assert log.calls == 1


def test_the_first_snapshot_is_authoritative_when_the_log_fills() -> None:
    """And the reverse: a later arrival is not retroactively remembered."""
    log = ScriptedLog([EMPTY, (built_event(),), (built_event(),), (built_event(),)])
    memory = MemorySignificance().distill_episode(
        world=world_with_wall(tick=120), event_log=log, previous_memory=WorldMemory.empty()
    )

    assert memory.facts == ()
    assert memory.through_episode == 0
    assert log.calls == 1


def test_a_corrupt_type_in_the_first_snapshot_is_refused() -> None:
    """Candidate V4 let this through as an episode that remembered nothing.

    The corrupt event was visible to fact generation and invisible to chronology,
    so the type check never ran and the malformed value was classified as
    nonsignificant.
    """
    log = ScriptedLog([(corrupt_event(),), EMPTY, EMPTY, EMPTY, EMPTY])

    with pytest.raises(TypeError):
        MemorySignificance().distill_episode(
            world=world_with_wall(tick=120),
            event_log=log,
            previous_memory=WorldMemory.empty(),
        )
    assert log.calls == 1


def test_a_corrupt_type_appearing_only_later_is_never_seen() -> None:
    """One snapshot means an event either counts for everything or for nothing."""
    log = ScriptedLog([EMPTY, (corrupt_event(),), (corrupt_event(),)])
    memory = MemorySignificance().distill_episode(
        world=world_with_wall(tick=120), event_log=log, previous_memory=WorldMemory.empty()
    )

    assert memory.facts == ()
    assert log.calls == 1


def test_the_transition_validator_reads_the_log_exactly_once() -> None:
    """The public wrapper takes one snapshot and delegates."""
    log = ScriptedLog([(built_event(),)])
    validate_memory_transition(
        previous_memory=None,
        current_memory=built_memory(),
        world=world_with_wall(tick=120),
        event_log=log,
    )
    assert log.calls == 1


def test_the_transition_validator_uses_its_first_snapshot() -> None:
    """A log that empties afterwards cannot invalidate what was validated."""
    log = ScriptedLog([(built_event(),), EMPTY, EMPTY])
    validate_memory_transition(
        previous_memory=None,
        current_memory=built_memory(),
        world=world_with_wall(tick=120),
        event_log=log,
    )
    assert log.calls == 1


def test_the_snapshot_validator_requires_a_tuple() -> None:
    """The internal path takes a captured history, not something to ask again."""
    with pytest.raises(TypeError):
        validate_memory_transition_events(
            previous_memory=None,
            current_memory=built_memory(),
            world=world_with_wall(tick=120),
            events=[built_event()],
        )


# --- SaveManager saves the snapshot it validated ----------------------------


def read_document(directory: Path, name: str) -> dict:
    """Return one parsed payload from an episode directory."""
    return loads_canonical((directory / name).read_bytes())


def test_save_uses_one_snapshot_and_the_episode_reloads() -> None:
    """Validation, serialization, and the manifest count all agree.

    Candidate V4 validated a log holding one event, serialized an empty one, and
    counted zero -- publishing an episode it could not itself reload.
    """
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        manager = SaveManager(root)
        world = world_with_wall(tick=120)
        memory = built_memory()
        log = ScriptedLog([(built_event(),), EMPTY, EMPTY, EMPTY, EMPTY])

        manager.save_episode(world, log, world_memory=memory)

        assert log.calls == 1
        episode = root / "episode_000"
        assert len(read_document(episode, EVENT_LOG_FILE)["events"]) == 1
        assert read_document(episode, MANIFEST_FILE)["event_count"] == 1

        loaded = manager.load_episode(0)
        assert loaded.world_memory == memory
        assert len(loaded.event_log.events()) == 1


def test_the_manifest_count_matches_the_log_and_the_validated_snapshot() -> None:
    """Three numbers that must never disagree."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        manager = SaveManager(root)
        log = ScriptedLog([(built_event(),), EMPTY, EMPTY, EMPTY, EMPTY])
        manager.save_episode(world_with_wall(tick=120), log, world_memory=built_memory())

        episode = root / "episode_000"
        manifest = read_document(episode, MANIFEST_FILE)
        serialized = read_document(episode, EVENT_LOG_FILE)["events"]

        assert manifest["event_count"] == len(serialized) == 1
        assert manager.load_episode(0).manifest.event_count == 1


def test_a_save_whose_authoritative_snapshot_is_empty_is_refused() -> None:
    """A memory holding a fact no snapshot event supports cannot be saved."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        manager = SaveManager(root)
        world = world_with_wall(tick=120)
        memory = built_memory()
        log = ScriptedLog([EMPTY, (built_event(),), (built_event(),), (built_event(),)])

        rng_before = world.rng.get_state()
        memory_before = (memory.facts, memory.through_episode, memory.through_tick)

        with pytest.raises(ValueError):
            manager.save_episode(world, log, world_memory=memory)

        assert log.calls == 1
        assert not (root / "episode_000").exists()
        assert list(root.iterdir()) == [], "no staging residue"
        assert world.rng.get_state() == rng_before
        assert (memory.facts, memory.through_episode, memory.through_tick) == memory_before


def test_a_rejected_save_leaves_an_earlier_episode_untouched() -> None:
    """One bad save cannot damage the history behind it."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        manager = SaveManager(root)
        manager.save_episode(
            world_with_wall(tick=120), log_of(built_event()), world_memory=built_memory()
        )
        before = {path.name: path.read_bytes() for path in sorted((root / "episode_000").iterdir())}

        child = world_with_wall(episode=1, tick=250, built_tick=120)
        parent_memory = manager.load_episode(0).world_memory
        log = ScriptedLog([EMPTY, (built_event(),)])
        with pytest.raises(ValueError):
            manager.save_episode(
                child,
                log,
                world_memory=parent_memory.advance(
                    episode=1, tick=250, new_facts=(wall_built_fact(tick=200),)
                ),
            )

        assert not (root / "episode_001").exists()
        assert sorted(entry.name for entry in root.iterdir()) == ["episode_000"]
        assert {
            path.name: path.read_bytes() for path in sorted((root / "episode_000").iterdir())
        } == before


def test_the_callers_event_log_is_never_modified() -> None:
    """The detached copy is ours; the caller's log stays exactly as it was."""
    with tempfile.TemporaryDirectory() as directory:
        manager = SaveManager(Path(directory))
        event = built_event()
        log = log_of(event)
        before = log.events()

        manager.save_episode(world_with_wall(tick=120), log, world_memory=built_memory())

        assert log.events() == before
        assert log.events()[0] is event, "the same Event object, not a copy"


def test_a_saved_episode_preserves_exact_event_order_and_identity() -> None:
    """The detached log holds the same occurrences in the same order."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        manager = SaveManager(root)
        world = world_with_wall(tick=200)
        first = Event(tick=10, type=EventType.SCARCITY_CHANGED, payload={}, source_id=None)
        second = wall_built_event(tick=120)
        third = Event(tick=130, type=EventType.SCARCITY_CHANGED, payload={}, source_id=None)
        log = log_of(first, second, third)
        memory = MemorySignificance().distill_episode(
            world=world, event_log=log, previous_memory=WorldMemory.empty()
        )

        manager.save_episode(world, log, world_memory=memory)
        restored = manager.load_episode(0).event_log.events()

        assert [event.tick for event in restored] == [10, 120, 130]
        assert [event.type for event in restored] == [
            EventType.SCARCITY_CHANGED,
            EventType.WALL_BUILT,
            EventType.SCARCITY_CHANGED,
        ]
        assert restored[1].source_id == WALL_ID


# --- hostile __class__ at the snapshot boundaries ----------------------------


class HostileClass:
    """Raises from ``__class__`` instead of answering."""

    @property
    def __class__(self) -> type:
        """Raise instead of revealing a type."""
        raise RuntimeError("boom")


class ReadOnlyDetails(Mapping):
    """A legitimate, well-behaved Mapping subclass carrying details."""

    def __init__(self, data: Mapping) -> None:
        """Copy the given entries."""
        self._data = dict(data)

    def __getitem__(self, key: str) -> object:
        """Answer from the copied entries."""
        return self._data[key]

    def __iter__(self):
        """Iterate the copied keys."""
        return iter(self._data)

    def __len__(self) -> int:
        """Count the copied entries."""
        return len(self._data)


def test_a_hostile_log_is_refused_by_the_event_snapshot() -> None:
    """The log's true runtime type decides, not its ``__class__`` property."""
    with pytest.raises(TypeError, match="event_log must be an EventLog, got HostileClass"):
        snapshot_event_log(HostileClass())


def test_a_hostile_entry_is_refused_by_the_event_snapshot() -> None:
    """A legitimate subclass log whose history holds a non-Event."""
    with pytest.raises(TypeError, match="event_log entry 0 must be an Event, got HostileClass"):
        snapshot_event_log(ScriptedLog([(HostileClass(),)]))


def test_a_hostile_object_is_refused_by_the_fact_snapshot() -> None:
    """The fact's true runtime type decides, not its ``__class__`` property."""
    with pytest.raises(TypeError, match="fact must be a MemoryFact, got HostileClass"):
        snapshot_memory_fact(HostileClass(), "fact")


def test_a_hostile_object_is_refused_by_the_memory_snapshot() -> None:
    """The memory's true runtime type decides, not its ``__class__`` property."""
    with pytest.raises(TypeError, match="memory must be a WorldMemory, got HostileClass"):
        snapshot_world_memory(HostileClass(), "memory")


def test_hostile_details_reported_by_a_fact_subclass_are_refused() -> None:
    """The lie is refused as a non-mapping, never leaked out of ``_thaw``."""
    lie = {"armed": False}

    class LyingDetailsFact(MemoryFact):
        """Reports hostile details once armed, after honest construction."""

        def __getattribute__(self, name: str) -> object:
            """Answer honestly for everything except armed ``details`` reads."""
            if name == "details" and lie["armed"]:
                return HostileClass()
            return super().__getattribute__(name)

    base = wall_built_fact()
    fact = LyingDetailsFact(
        fact_type=base.fact_type,
        episode=base.episode,
        tick=base.tick,
        source_event_index=base.source_event_index,
        source_event_type=base.source_event_type,
        source_id=base.source_id,
        subject_ids=base.subject_ids,
        details=base.details_as_dict(),
    )
    lie["armed"] = True
    with pytest.raises(TypeError, match="details must be a mapping, got HostileClass"):
        snapshot_memory_fact(fact, "fact")


def test_a_legitimate_mapping_subclass_still_carries_details() -> None:
    """Exact dicts are not required where the contract says Mapping."""
    base = wall_built_fact()
    fact = MemoryFact(
        fact_type=base.fact_type,
        episode=base.episode,
        tick=base.tick,
        source_event_index=base.source_event_index,
        source_event_type=base.source_event_type,
        source_id=base.source_id,
        subject_ids=base.subject_ids,
        details=ReadOnlyDetails(base.details_as_dict()),
    )
    assert fact == base
    assert fact.fact_id == base.fact_id

    rebuilt = MemoryFact.from_document(ReadOnlyDetails(base.to_document()))
    assert rebuilt == base
