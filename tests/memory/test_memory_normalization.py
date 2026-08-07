"""Tests for normalizing caller-owned objects into exact base-domain snapshots.

Capturing a tuple of references freezes *which* objects are involved. It does not
freeze what those objects say. An ``Event``, ``WorldMemory``, or ``MemoryFact``
subclass can answer one way while a save is being validated and another way while
it is being written -- and the episode that results is one the same implementation
refuses to load.

The fix is to read each semantic field once and rebuild a plain domain object from
it. After that, only the rebuilt object is consulted, so validation and
serialization are guaranteed to be describing the same thing.
"""

import tempfile
from pathlib import Path

import pytest

from living_diorama.events import Event, EventLog, EventType
from living_diorama.memory import MemoryFact, MemoryQuery, MemorySignificance, WorldMemory
from living_diorama.memory._integrity import (
    snapshot_event_log,
    snapshot_memory_fact,
    snapshot_world_memory,
)
from living_diorama.persistence import SaveManager
from living_diorama.persistence.json_codec import loads_canonical
from living_diorama.persistence.schema.world_schema_v1 import (
    EVENT_LOG_FILE,
    MANIFEST_FILE,
    WORLD_MEMORY_FILE,
)
from living_diorama.persistence.serializers.world_memory_serializer import (
    serialize_world_memory,
)
from memory.conftest import (
    BOUNDARY_ID,
    WALL_ID,
    log_of,
    wall_built_event,
    world_with_wall,
)

PAYLOAD = {"wall_id": WALL_ID}
"""The payload episode zero's wall-construction event genuinely carries."""


def base_episode() -> tuple[object, WorldMemory]:
    """Return a world and the memory a genuine wall-building episode produces."""
    world = world_with_wall(tick=120)
    memory = MemorySignificance().distill_episode(
        world=world,
        event_log=log_of(wall_built_event(tick=120)),
        previous_memory=WorldMemory.empty(),
    )
    return world, memory


def read(directory: Path, name: str) -> dict:
    """Return one parsed payload from an episode directory."""
    return loads_canonical((directory / name).read_bytes())


# --- Stateful Event subclasses ----------------------------------------------


class ShiftingPayloadEvent(Event):
    """Reports a tampered payload from its third semantic read onward."""

    __slots__ = ()
    reads: dict[int, int] = {}

    def payload_as_dict(self) -> dict:
        """Return the real payload twice, then a tampered one."""
        count = ShiftingPayloadEvent.reads.get(id(self), 0) + 1
        ShiftingPayloadEvent.reads[id(self)] = count
        payload = super().payload_as_dict()
        return payload if count < 3 else {**payload, "tampered": True}


class ShiftingFieldEvent(Event):
    """Base for adversaries that report one field differently on later reads.

    Intercepted through ``__getattribute__`` rather than a property: ``Event`` is
    a frozen slotted dataclass, so a property named after a field would leave the
    constructor with nowhere to store it.

    The shift stays disarmed until construction is finished. ``Event.__post_init__``
    validates its own fields and writes the validated values back, so an
    adversary that started shifting immediately would corrupt its own stored
    state and never present the honest value to anyone.
    """

    __slots__ = ()
    field: str = ""
    later: object = None
    reads: dict[int, int] = {}
    armed = False

    def __getattribute__(self, name: str) -> object:
        """Return the stored value on the first armed read, then the other one."""
        cls = type(self)
        if cls.armed and name == cls.field:
            count = cls.reads.get(id(self), 0) + 1
            cls.reads[id(self)] = count
            if count > 1:
                return cls.later
        return object.__getattribute__(self, name)


class ShiftingTypeEvent(ShiftingFieldEvent):
    """Reports WALL_BUILT once, then something else."""

    __slots__ = ()
    field = "type"
    later = EventType.SCARCITY_CHANGED
    reads: dict[int, int] = {}


class ShiftingSourceEvent(ShiftingFieldEvent):
    """Reports the real wall once, then a different entity."""

    __slots__ = ()
    field = "source_id"
    later = "district_a"
    reads: dict[int, int] = {}


class ShiftingTickEvent(ShiftingFieldEvent):
    """Reports the real tick once, then a different one."""

    __slots__ = ()
    field = "tick"
    later = 7
    reads: dict[int, int] = {}


def shifting_log(cls) -> tuple[EventLog, Event]:
    """Return a log holding one instance of a stateful Event subclass.

    The shift is armed only after construction, so the read under test is the
    first one a caller makes rather than one the constructor's own validation
    consumed.
    """
    cls.armed = False
    event = cls(tick=120, type=EventType.WALL_BUILT, payload=dict(PAYLOAD), source_id=WALL_ID)
    log = EventLog()
    log.append(event)
    cls.reads.clear()
    cls.armed = True
    return log, event


def test_the_stateful_event_really_does_shift() -> None:
    """Guards the technique: without the shift the tests below prove nothing."""
    _, event = shifting_log(ShiftingPayloadEvent)

    assert isinstance(event, Event)
    assert event.payload_as_dict() == PAYLOAD
    assert event.payload_as_dict() == PAYLOAD
    assert event.payload_as_dict() == {**PAYLOAD, "tampered": True}


def test_an_event_snapshot_returns_exact_base_events() -> None:
    """No caller-owned object survives into the snapshot."""
    log, event = shifting_log(ShiftingPayloadEvent)
    snapshot = snapshot_event_log(log)

    assert len(snapshot) == 1
    assert type(snapshot[0]) is Event, "an exact base Event, not the subclass"
    assert snapshot[0] is not event
    assert snapshot[0].payload_as_dict() == PAYLOAD


def test_each_event_field_is_read_once() -> None:
    """Re-reading is what let one phase disagree with another."""
    log, event = shifting_log(ShiftingPayloadEvent)
    snapshot_event_log(log)

    assert ShiftingPayloadEvent.reads[id(event)] == 1


def test_the_snapshot_leaves_the_callers_log_and_events_alone() -> None:
    """Normalization copies; it does not reach back."""
    log, event = shifting_log(ShiftingPayloadEvent)
    before = log.events()

    snapshot_event_log(log)

    assert log.events() == before
    assert log.events()[0] is event


@pytest.mark.parametrize(
    "cls,attribute,expected",
    [
        (ShiftingTypeEvent, "type", EventType.WALL_BUILT),
        (ShiftingSourceEvent, "source_id", WALL_ID),
        (ShiftingTickEvent, "tick", 120),
    ],
)
def test_the_first_semantic_read_of_each_field_is_authoritative(
    cls, attribute: str, expected: object
) -> None:
    """Whatever the event said when it was asked is what the save records."""
    log, _ = shifting_log(cls)
    snapshot = snapshot_event_log(log)

    assert getattr(snapshot[0], attribute) == expected


def test_duplicate_occurrences_become_separate_snapshots() -> None:
    """The same instance twice is two occurrences, and stays two."""
    event = wall_built_event(tick=120)
    log = EventLog()
    log.append(event)
    log.append(event)

    snapshot = snapshot_event_log(log)

    assert len(snapshot) == 2
    assert snapshot[0] is not snapshot[1]
    assert snapshot[0] == snapshot[1]
    assert all(type(item) is Event for item in snapshot)


def test_a_stateful_event_produces_a_loadable_save() -> None:
    """The reported defect: V5 published a save its own loader rejected.

    The event's payload changed after validation, so ``event_log.json`` recorded
    something the memory's fact provenance contradicted.
    """
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        world, memory = base_episode()
        log, event = shifting_log(ShiftingPayloadEvent)
        manager = SaveManager(root)

        manager.save_episode(world, log, world_memory=memory)

        episode = root / "episode_000"
        saved_payload = read(episode, EVENT_LOG_FILE)["events"][0]["payload"]
        fact_payload = read(episode, WORLD_MEMORY_FILE)["facts"][0]["details"][
            "source_event_payload"
        ]
        assert saved_payload == PAYLOAD
        assert fact_payload == PAYLOAD
        assert read(episode, MANIFEST_FILE)["event_count"] == 1
        assert ShiftingPayloadEvent.reads[id(event)] == 1

        loaded = manager.load_episode(0)
        assert loaded.world_memory == memory
        assert loaded.event_log.events()[0].payload_as_dict() == PAYLOAD


def test_a_base_event_keeps_all_its_existing_behaviour() -> None:
    """The control case."""
    log = log_of(wall_built_event(tick=120))
    snapshot = snapshot_event_log(log)

    assert len(snapshot) == 1
    assert snapshot[0].tick == 120
    assert snapshot[0].type is EventType.WALL_BUILT
    assert snapshot[0].source_id == WALL_ID
    assert snapshot[0].payload_as_dict() == PAYLOAD


@pytest.mark.parametrize("bad", [None, "log", [], 0])
def test_a_non_event_log_is_refused(bad: object) -> None:
    """The snapshot helper takes a real log."""
    with pytest.raises(TypeError):
        snapshot_event_log(bad)


# --- Stateful WorldMemory subclasses ----------------------------------------


class ShiftingFactsMemory(WorldMemory):
    """Reports its facts three times, then reports none."""

    def __init__(self, base: WorldMemory) -> None:
        """Copy a real memory and start counting reads."""
        super().__init__(
            base.facts,
            through_episode=base.through_episode,
            through_tick=base.through_tick,
        )
        self.reads = 0

    @property
    def facts(self) -> tuple[MemoryFact, ...]:
        """Return the real facts for three reads, then an empty tuple."""
        self.reads += 1
        return super().facts if self.reads < 4 else ()


class ShiftingCheckpointMemory(WorldMemory):
    """Reports its checkpoint once, then reports a different one."""

    def __init__(self, base: WorldMemory) -> None:
        """Copy a real memory and start counting reads."""
        super().__init__(
            base.facts,
            through_episode=base.through_episode,
            through_tick=base.through_tick,
        )
        self.episode_reads = 0
        self.tick_reads = 0

    @property
    def through_episode(self) -> int | None:
        """Return the real episode once, then a later one."""
        self.episode_reads += 1
        return super().through_episode if self.episode_reads == 1 else 99

    @property
    def through_tick(self) -> int | None:
        """Return the real tick once, then a later one."""
        self.tick_reads += 1
        return super().through_tick if self.tick_reads == 1 else 9999


def test_the_stateful_memory_really_does_shift() -> None:
    """Guards the technique."""
    _, memory = base_episode()
    shifting = ShiftingFactsMemory(memory)

    assert len(shifting.facts) == 1
    assert len(shifting.facts) == 1
    assert len(shifting.facts) == 1
    assert shifting.facts == ()


def test_a_memory_snapshot_returns_exact_base_objects() -> None:
    """Both the container and everything in it."""
    _, memory = base_episode()
    snapshot = snapshot_world_memory(ShiftingFactsMemory(memory), "memory")

    assert type(snapshot) is WorldMemory
    assert all(type(fact) is MemoryFact for fact in snapshot.facts)
    assert snapshot == memory


def test_each_memory_field_is_read_once() -> None:
    """One read of facts, one of each checkpoint half."""
    _, memory = base_episode()
    shifting_facts = ShiftingFactsMemory(memory)
    snapshot_world_memory(shifting_facts, "memory")
    assert shifting_facts.reads == 1

    shifting_checkpoint = ShiftingCheckpointMemory(memory)
    snapshot_world_memory(shifting_checkpoint, "memory")
    assert shifting_checkpoint.episode_reads == 1
    assert shifting_checkpoint.tick_reads == 1


def test_the_first_checkpoint_read_is_authoritative() -> None:
    """A later, larger checkpoint cannot replace the one that was validated."""
    _, memory = base_episode()
    snapshot = snapshot_world_memory(ShiftingCheckpointMemory(memory), "memory")

    assert snapshot.through_episode == memory.through_episode
    assert snapshot.through_tick == memory.through_tick


def test_a_stateful_memory_produces_a_loadable_save() -> None:
    """The reported defect: validation saw one fact, serialization saw none."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        world, memory = base_episode()
        shifting = ShiftingFactsMemory(memory)
        manager = SaveManager(root)

        manager.save_episode(world, log_of(wall_built_event(tick=120)), world_memory=shifting)

        episode = root / "episode_000"
        assert len(read(episode, WORLD_MEMORY_FILE)["facts"]) == 1
        assert len(read(episode, EVENT_LOG_FILE)["events"]) == 1
        assert shifting.reads == 1

        loaded = manager.load_episode(0)
        assert loaded.world_memory == memory


def test_a_query_answers_from_one_fixed_history() -> None:
    """A memory that empties later cannot change what a query already reported."""
    _, memory = base_episode()
    shifting = ShiftingFactsMemory(memory)
    query = MemoryQuery(shifting)

    assert len(query.facts()) == 1
    assert len(query.facts()) == 1
    assert len(query.narration_context()) == 1
    assert shifting.reads == 1


def test_a_base_memory_keeps_all_its_existing_behaviour() -> None:
    """The control case."""
    _, memory = base_episode()
    snapshot = snapshot_world_memory(memory, "memory")

    assert snapshot == memory
    assert snapshot.through_episode == 0
    assert snapshot.through_tick == 120
    assert len(snapshot) == 1


@pytest.mark.parametrize("bad", [None, "memory", 0, []])
def test_a_non_memory_is_refused(bad: object) -> None:
    """The snapshot helper takes a real memory."""
    with pytest.raises(TypeError):
        snapshot_world_memory(bad, "memory")


# --- Rewriting MemoryFact subclasses ----------------------------------------


class TamperingFact(MemoryFact):
    """Compares equal to anything, and serializes a summary of its own.

    Only the serialization is dishonest. Its stored content is the real fact's,
    so it passes every equality check validation performs and then writes
    something else -- which is exactly what made Candidate V5 publish a save its
    own loader refused.
    """

    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        """Claim equality so validation accepts this fact."""
        return True

    def __hash__(self) -> int:
        """Hash by derived identifier, as the base class does."""
        return hash(self.fact_id)

    def to_document(self) -> dict:
        """Return a document whose summary the content does not imply."""
        document = super().to_document()
        document["summary"] = "tampered summary"
        return document


def tampering_memory() -> tuple[object, WorldMemory, WorldMemory]:
    """Return a world plus the honest memory and a tampering equivalent."""
    world, memory = base_episode()
    honest = memory.facts[0]
    tampered = TamperingFact(
        fact_type=honest.fact_type,
        episode=honest.episode,
        tick=honest.tick,
        source_event_index=honest.source_event_index,
        source_event_type=honest.source_event_type,
        source_id=honest.source_id,
        subject_ids=honest.subject_ids,
        details=honest.details_as_dict(),
    )
    rigged = WorldMemory(
        (tampered,),
        through_episode=memory.through_episode,
        through_tick=memory.through_tick,
    )
    return world, memory, rigged


def test_the_tampering_fact_really_does_rewrite_its_document() -> None:
    """Guards the technique: it compares equal and still serializes differently."""
    _, memory, rigged = tampering_memory()
    tampered = rigged.facts[0]

    assert tampered == memory.facts[0]
    assert tampered.to_document()["summary"] == "tampered summary"


def test_a_fact_snapshot_returns_an_exact_base_fact() -> None:
    """The overrides are left behind with the object that carried them."""
    _, memory, rigged = tampering_memory()
    snapshot = snapshot_memory_fact(rigged.facts[0], "fact")

    assert type(snapshot) is MemoryFact
    assert snapshot.summary == memory.facts[0].summary
    assert snapshot.to_document()["summary"] == memory.facts[0].summary


def test_a_fact_claiming_a_summary_its_content_denies_is_refused() -> None:
    """Derived values are recomputed and compared, never taken on trust."""
    _, memory = base_episode()
    honest = memory.facts[0]

    class LyingFact(MemoryFact):
        """Reports a summary that its own content does not imply."""

        __slots__ = ()

        def __getattribute__(self, name: str) -> object:
            """Return unsupported wording when the summary is asked for."""
            if name == "summary":
                return "invented summary"
            return object.__getattribute__(self, name)

    lying = LyingFact(
        fact_type=honest.fact_type,
        episode=honest.episode,
        tick=honest.tick,
        source_event_index=honest.source_event_index,
        source_event_type=honest.source_event_type,
        source_id=honest.source_id,
        subject_ids=honest.subject_ids,
        details=honest.details_as_dict(),
    )
    with pytest.raises(ValueError):
        snapshot_memory_fact(lying, "fact")


def test_a_fact_claiming_a_foreign_identifier_is_refused() -> None:
    """The same rule for the derived identifier."""
    _, memory = base_episode()
    honest = memory.facts[0]

    class RelabelledFact(MemoryFact):
        """Reports an identifier that its own content does not imply."""

        __slots__ = ()

        def __getattribute__(self, name: str) -> object:
            """Return an identifier belonging to nothing."""
            if name == "fact_id":
                return "fact_" + "0" * 64
            return object.__getattribute__(self, name)

    relabelled = RelabelledFact(
        fact_type=honest.fact_type,
        episode=honest.episode,
        tick=honest.tick,
        source_event_index=honest.source_event_index,
        source_event_type=honest.source_event_type,
        source_id=honest.source_id,
        subject_ids=honest.subject_ids,
        details=honest.details_as_dict(),
    )
    with pytest.raises(ValueError):
        snapshot_memory_fact(relabelled, "fact")


def test_a_tampering_fact_produces_a_loadable_save() -> None:
    """The reported defect: the saved summary was not what the content implied."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        world, memory, rigged = tampering_memory()
        manager = SaveManager(root)

        manager.save_episode(world, log_of(wall_built_event(tick=120)), world_memory=rigged)

        saved = read(root / "episode_000", WORLD_MEMORY_FILE)["facts"][0]
        assert saved["summary"] == memory.facts[0].summary
        assert saved["details"] == memory.facts[0].details_as_dict()

        loaded = manager.load_episode(0)
        assert loaded.world_memory == memory


def test_a_base_fact_keeps_all_its_existing_behaviour() -> None:
    """The control case."""
    _, memory = base_episode()
    honest = memory.facts[0]
    snapshot = snapshot_memory_fact(honest, "fact")

    assert type(snapshot) is MemoryFact
    assert snapshot == honest
    assert snapshot.fact_id == honest.fact_id
    assert snapshot.summary == honest.summary
    assert snapshot.to_document() == honest.to_document()


@pytest.mark.parametrize("bad", [None, "fact", 0, {}])
def test_a_non_fact_is_refused(bad: object) -> None:
    """The snapshot helper takes a real fact."""
    with pytest.raises(TypeError):
        snapshot_memory_fact(bad, "fact")


# --- The direct serializer --------------------------------------------------


def test_the_serializer_cannot_be_tricked_by_a_shifting_memory() -> None:
    """It is public, so it normalizes for itself rather than trusting a caller."""
    _, memory = base_episode()
    document = serialize_world_memory(ShiftingFactsMemory(memory))

    assert len(document["facts"]) == 1
    assert document["facts"][0]["summary"] == memory.facts[0].summary


def test_the_serializer_cannot_be_tricked_by_a_rewriting_fact() -> None:
    """An overridden ``to_document()`` never decides what lands on disk."""
    _, memory, rigged = tampering_memory()
    document = serialize_world_memory(rigged)

    assert document["facts"][0]["summary"] == memory.facts[0].summary
    assert document["facts"][0]["details"] == memory.facts[0].details_as_dict()


def test_the_serializer_still_writes_a_base_memory_unchanged() -> None:
    """The control case."""
    _, memory = base_episode()
    document = serialize_world_memory(memory)

    assert document == {
        "facts": [memory.facts[0].to_document()],
        "schema_version": 1,
    }


# --- Atomicity when normalization rejects -----------------------------------


def test_a_rejected_normalization_writes_nothing() -> None:
    """A save refused during normalization leaves the filesystem untouched."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        world, memory = base_episode()
        honest = memory.facts[0]

        class LyingFact(MemoryFact):
            """Reports a summary its content does not imply."""

            __slots__ = ()

            def __getattribute__(self, name: str) -> object:
                """Return unsupported wording when the summary is asked for."""
                if name == "summary":
                    return "invented summary"
                return object.__getattribute__(self, name)

        rigged = WorldMemory(
            (
                LyingFact(
                    fact_type=honest.fact_type,
                    episode=honest.episode,
                    tick=honest.tick,
                    source_event_index=honest.source_event_index,
                    source_event_type=honest.source_event_type,
                    source_id=honest.source_id,
                    subject_ids=honest.subject_ids,
                    details=honest.details_as_dict(),
                ),
            ),
            through_episode=memory.through_episode,
            through_tick=memory.through_tick,
        )
        log = log_of(wall_built_event(tick=120))
        rng_before = world.rng.get_state()
        events_before = log.events()

        with pytest.raises(ValueError):
            SaveManager(root).save_episode(world, log, world_memory=rigged)

        assert not (root / "episode_000").exists()
        assert list(root.iterdir()) == [], "no staging residue"
        assert world.rng.get_state() == rng_before
        assert log.events() == events_before


def test_an_earlier_episode_survives_a_rejected_normalization() -> None:
    """One refused save cannot damage the history behind it."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        world, memory = base_episode()
        manager = SaveManager(root)
        manager.save_episode(world, log_of(wall_built_event(tick=120)), world_memory=memory)
        before = {path.name: path.read_bytes() for path in sorted((root / "episode_000").iterdir())}

        child = world_with_wall(episode=1, tick=250, built_tick=120)
        with pytest.raises(TypeError):
            manager.save_episode(child, EventLog(), world_memory="not a memory")

        assert not (root / "episode_001").exists()
        assert {
            path.name: path.read_bytes() for path in sorted((root / "episode_000").iterdir())
        } == before


def test_the_full_two_episode_integration_still_works() -> None:
    """The ordinary path, unchanged: a wall is built and remembered."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        world, memory = base_episode()
        manager = SaveManager(root)
        manager.save_episode(world, log_of(wall_built_event(tick=120)), world_memory=memory)

        child = world_with_wall(episode=1, tick=250, built_tick=120)
        parent_memory = manager.load_episode(0).world_memory
        child_memory = MemorySignificance().distill_episode(
            world=child, event_log=EventLog(), previous_memory=parent_memory
        )
        manager.save_episode(child, EventLog(), world_memory=child_memory)

        loaded = manager.load_episode(1)
        assert loaded.world_memory == child_memory
        assert loaded.world_memory.facts[0].details["wall_id"] == WALL_ID
        assert loaded.world_memory.facts[0].details["boundary_id"] == BOUNDARY_ID
