"""Adversarial tests for what memory will accept as stored state.

Three ways a corrupt world can look correct to a check that compares rather than
inspects: an object that carries the right attribute names without being the
right class, an event whose type is a string that spells a real one, and a
document whose keys are subclasses that hash and compare like the keys they copy.

None of them is exotic. Each survives every equality test the surrounding code
performs, and each would put state into permanent history that the engine never
agreed to.
"""

import enum
import tempfile
from collections.abc import Mapping
from pathlib import Path

import pytest

from living_diorama.entities import Boundary, District, Law, Wall
from living_diorama.events import Event, EventBus, EventLog, EventType
from living_diorama.memory import (
    MemoryFact,
    MemoryFactType,
    MemorySignificance,
    WorldMemory,
)
from living_diorama.memory._integrity import validate_memory_transition
from memory.conftest import (
    BOUNDARY_ID,
    LAW_ID,
    WALL_ID,
    build_law,
    build_wall,
    build_world,
    law_restored_event,
    log_of,
    wall_built_event,
    wall_built_fact,
    world_with_wall,
)


class StringSubclass(str):
    """A ``str`` subclass: equal to a plain string, and not one."""


class SpoofedEventType(enum.StrEnum):
    """A different enum whose members spell real event type names."""

    WALL_BUILT = "WALL_BUILT"
    SCARCITY_CHANGED = "SCARCITY_CHANGED"


class SpoofedKey(enum.StrEnum):
    """A different enum whose member spells a required document key."""

    FACT_ID = "fact_id"


class Arbitrary:
    """An object with no relationship to anything the engine defines."""


class FakeWall:
    """Carries every field the memory layer reads from a wall, and is not one."""

    def __init__(self, wall_id: str = WALL_ID, boundary_id: str = BOUNDARY_ID) -> None:
        """Populate the attributes a real wall would expose."""
        self.id = wall_id
        self.boundary_id = boundary_id
        self.built_tick = 120
        self.permanent = True
        self.active = True
        self.dependency_score = 0.0
        self.resource_dependency = 0.0
        self.transport_dependency = 0.0


class FakeBoundary:
    """Carries every field the memory layer reads from a boundary."""

    def __init__(self) -> None:
        """Populate the attributes a real boundary would expose."""
        self.id = BOUNDARY_ID
        self.wall_id = WALL_ID
        self.district_a_id = "district_a"
        self.district_b_id = "district_b"


class FakeDistrict:
    """Carries the only field the memory layer reads from a district."""

    def __init__(self, district_id: str) -> None:
        """Populate the attribute a real district would expose."""
        self.id = district_id


class FakeLaw:
    """Carries every field the memory layer reads from a law."""

    def __init__(self) -> None:
        """Populate the attributes a real law would expose."""
        self.id = LAW_ID
        self.name = "Resource Sharing"
        self.active = True
        self.previous_value = False
        self.current_value = True
        self.changed_episode = 1
        self.restored_tick = 250


def episode_zero_memory() -> WorldMemory:
    """Return the memory of an episode in which one wall was genuinely built."""
    return MemorySignificance().distill_episode(
        world=world_with_wall(tick=120),
        event_log=log_of(wall_built_event(tick=120)),
        previous_memory=WorldMemory.empty(),
    )


def install(world: object, registry: str, key: str, replacement: object) -> None:
    """Put an object into a typed registry and mirror it into the aggregate index.

    Both views are updated, so every check that compares the two still agrees.
    What is left is the question those checks cannot answer: whether the object is
    the entity the registry is supposed to hold.
    """
    getattr(world, f"_{registry}")[key] = replacement
    world._entities[key] = replacement


def quiet_world(mutate=None) -> object:
    """Return an episode-one world in which nothing happened."""
    world = world_with_wall(episode=1, tick=250, built_tick=120)
    if mutate is not None:
        mutate(world)
    return world


def restoration_world(mutate=None) -> object:
    """Return an episode-one world whose law was restored at tick 250."""
    world = world_with_wall(episode=1, tick=250, built_tick=120)
    world.add_law(build_law(changed_episode=1, restored_tick=250))
    if mutate is not None:
        mutate(world)
    return world


def world_snapshot(world: object) -> dict:
    """Capture everything a rejected distillation must leave untouched."""
    return {
        "tick": world.tick,
        "episode": world.episode,
        "rng": world.rng.get_state(),
        "walls": {key: id(value) for key, value in sorted(world.walls.items())},
        "boundaries": {key: id(value) for key, value in sorted(world.boundaries.items())},
        "districts": {key: id(value) for key, value in sorted(world.districts.items())},
        "laws": {key: id(value) for key, value in sorted(world.laws.items())},
    }


def memory_snapshot(memory: WorldMemory) -> tuple:
    """Capture a memory as comparable values."""
    return (memory.facts, memory.through_episode, memory.through_tick)


def assert_rejected_cleanly(world, event_log, previous, error=TypeError) -> None:
    """Run a distillation expecting rejection, and prove nothing at all happened.

    Also runs the transition validator over a memory that merely advances the
    checkpoint, because persistence reaches the same rules by that path. A fresh
    empty directory stands in as the place any stray file would land: the memory
    layer touches no filesystem at all, so it must still be empty afterwards.
    """
    before_world = world_snapshot(world)
    before_events = event_log.events()
    before_previous = memory_snapshot(previous)
    current = WorldMemory(previous.facts, through_episode=world.episode, through_tick=world.tick)
    before_current = memory_snapshot(current)
    published: list[object] = []
    bus = EventBus()
    bus.subscribe(published.append)

    with tempfile.TemporaryDirectory() as directory:
        watched = Path(directory)
        with pytest.raises(error):
            MemorySignificance().distill_episode(
                world=world, event_log=event_log, previous_memory=previous
            )
        with pytest.raises(error):
            validate_memory_transition(
                previous_memory=previous,
                current_memory=current,
                world=world,
                event_log=event_log,
            )
        assert list(watched.iterdir()) == [], "the memory layer writes no files"

    assert world_snapshot(world) == before_world
    assert event_log.events() == before_events
    assert memory_snapshot(previous) == before_previous
    assert memory_snapshot(current) == before_current
    assert published == [], "the memory layer publishes no events"


# --- Defect A: typed registries must hold real domain entities --------------


def test_the_fakes_really_do_satisfy_every_attribute_check() -> None:
    """Guards the technique: without this the tests below prove nothing.

    Each fake answers every attribute the memory layer reads, and each is stored
    under the correct identifier in both the typed registry and the aggregate
    index. Only the runtime type distinguishes it from the real entity.
    """
    fake_wall = FakeWall()
    assert fake_wall.id == WALL_ID
    assert not isinstance(fake_wall, Wall)
    assert not isinstance(FakeBoundary(), Boundary)
    assert not isinstance(FakeDistrict("district_a"), District)
    assert not isinstance(FakeLaw(), Law)

    world = quiet_world(lambda world: install(world, "walls", WALL_ID, fake_wall))
    assert world.walls[WALL_ID] is fake_wall
    assert world.has_entity(WALL_ID)
    assert world.get_entity(WALL_ID) is fake_wall


def test_a_fake_wall_is_refused() -> None:
    """A quiet episode still re-checks its remembered walls, and this is not one."""
    assert_rejected_cleanly(
        quiet_world(lambda world: install(world, "walls", WALL_ID, FakeWall())),
        EventLog(),
        episode_zero_memory(),
    )


def test_a_fake_boundary_is_refused() -> None:
    """The boundary a remembered wall stands on must be a real boundary."""
    assert_rejected_cleanly(
        quiet_world(lambda world: install(world, "boundaries", BOUNDARY_ID, FakeBoundary())),
        EventLog(),
        episode_zero_memory(),
    )


@pytest.mark.parametrize("district_id", ["district_a", "district_b"])
def test_a_fake_district_endpoint_is_refused(district_id: str) -> None:
    """Both endpoints are recorded in a fact, so both must be real districts."""
    assert_rejected_cleanly(
        quiet_world(
            lambda world: install(world, "districts", district_id, FakeDistrict(district_id))
        ),
        EventLog(),
        episode_zero_memory(),
    )


def test_a_fake_law_is_refused() -> None:
    """A restoration is only believed when the law that records it is a Law."""
    assert_rejected_cleanly(
        restoration_world(lambda world: install(world, "laws", LAW_ID, FakeLaw())),
        log_of(law_restored_event(tick=250)),
        episode_zero_memory(),
    )


def test_a_fake_wall_is_refused_when_the_wall_is_first_built() -> None:
    """Not only on the remembered path: construction checks the type too."""
    world = build_world(tick=120)
    install(world, "walls", WALL_ID, FakeWall())

    with pytest.raises(TypeError):
        MemorySignificance().distill_episode(
            world=world,
            event_log=log_of(wall_built_event(tick=120)),
            previous_memory=WorldMemory.empty(),
        )


def test_real_entities_continue_to_work() -> None:
    """The control case for every type check above."""
    previous = episode_zero_memory()
    world = restoration_world()

    assert isinstance(world.walls[WALL_ID], Wall)
    assert isinstance(world.boundaries[BOUNDARY_ID], Boundary)
    assert isinstance(world.districts["district_a"], District)
    assert isinstance(world.laws[LAW_ID], Law)

    memory = MemorySignificance().distill_episode(
        world=world, event_log=log_of(law_restored_event(tick=250)), previous_memory=previous
    )
    assert len(memory) == 2
    assert memory.facts[1].fact_type is MemoryFactType.LAW_RESTORED_WALL_PERSISTED


def test_a_subclass_of_a_domain_entity_is_accepted() -> None:
    """Subclassing a domain entity is not forbidden by any existing contract.

    An exact type check would invent that prohibition, so the rule is
    ``isinstance`` -- the same thing the Phase 10 serializers require.
    """

    class SpecialWall(Wall):
        """An ordinary Wall with nothing added."""

    world = build_world(episode=1, tick=250)
    template = build_wall(built_tick=120)
    world.add_wall(
        SpecialWall(
            id=template.id,
            created_tick=template.created_tick,
            boundary_id=template.boundary_id,
            built_tick=template.built_tick,
            integrity=template.integrity,
            active=template.active,
            permanent=template.permanent,
            dependency_score=template.dependency_score,
            transport_dependency=template.transport_dependency,
            resource_dependency=template.resource_dependency,
        )
    )

    memory = MemorySignificance().distill_episode(
        world=world, event_log=EventLog(), previous_memory=episode_zero_memory()
    )
    assert memory.through_episode == 1


# --- Defect B: an event type must be a real EventType -----------------------

CORRUPT_EVENT_TYPES = [
    "WALL_BUILT",
    StringSubclass("WALL_BUILT"),
    SpoofedEventType.WALL_BUILT,
    "SCARCITY_CHANGED",
    StringSubclass("SCARCITY_CHANGED"),
    SpoofedEventType.SCARCITY_CHANGED,
    None,
    True,
    1,
    1.0,
    MemoryFactType.WALL_BUILT,
    Arbitrary(),
]
"""Values that spell, resemble, or simply are not an event type.

Both shapes are covered deliberately: one that looks significant and one that
looks nonsignificant. A malformed type must be an error either way, because
classifying it as nonsignificant would let a corrupt log read as an uneventful
episode.
"""


def corrupted_event(value: object, *, tick: int = 120) -> Event:
    """Return a real frozen Event whose stored type has been replaced."""
    event = wall_built_event(tick=tick)
    object.__setattr__(event, "type", value)
    return event


def test_a_corrupted_event_still_looks_like_an_event() -> None:
    """Guards the technique: the Event is real and only its type was replaced."""
    event = corrupted_event("WALL_BUILT")

    assert isinstance(event, Event)
    assert event.tick == 120
    assert event.source_id == WALL_ID
    assert type(event.type) is not EventType


@pytest.mark.parametrize("value", CORRUPT_EVENT_TYPES)
def test_a_corrupt_event_type_is_refused(value: object) -> None:
    """Never silently ignored, whichever significance it appears to claim."""
    with pytest.raises(TypeError):
        MemorySignificance().distill_episode(
            world=world_with_wall(tick=120),
            event_log=log_of(corrupted_event(value)),
            previous_memory=WorldMemory.empty(),
        )


@pytest.mark.parametrize("value", CORRUPT_EVENT_TYPES)
def test_a_corrupt_event_type_is_refused_by_the_transition_validator(value: object) -> None:
    """Persistence reaches the same rule by a different path."""
    world = world_with_wall(tick=120)
    with pytest.raises(TypeError):
        validate_memory_transition(
            previous_memory=None,
            current_memory=WorldMemory((), through_episode=0, through_tick=120),
            world=world,
            event_log=log_of(corrupted_event(value)),
        )


def test_a_corrupt_event_type_elsewhere_in_the_log_is_still_refused() -> None:
    """The whole log is walked, not only the events a fact happens to cite."""
    world = world_with_wall(tick=200)
    log = log_of(
        Event(tick=10, type=EventType.SCARCITY_CHANGED, payload={}),
        corrupted_event("WALL_BUILT", tick=20),
    )
    with pytest.raises(TypeError):
        MemorySignificance().distill_episode(
            world=world, event_log=log, previous_memory=WorldMemory.empty()
        )


def test_a_corrupt_event_type_is_refused_before_it_can_be_classified() -> None:
    """A string spelling a nonsignificant type is an error, not a quiet episode.

    Candidate V3 produced a memory here -- an episode that recorded nothing at
    all, from a log it could not read.
    """
    world = build_world(tick=40)
    with pytest.raises(TypeError):
        MemorySignificance().distill_episode(
            world=world,
            event_log=log_of(corrupted_event("SCARCITY_CHANGED", tick=10)),
            previous_memory=WorldMemory.empty(),
        )


@pytest.mark.parametrize("event_type", list(EventType))
def test_every_real_event_type_is_still_handled_by_its_normal_rule(
    event_type: EventType,
) -> None:
    """Significant types produce their facts; the rest produce none, without error."""
    if event_type is EventType.WALL_BUILT:
        memory = MemorySignificance().distill_episode(
            world=world_with_wall(tick=120),
            event_log=log_of(wall_built_event(tick=120)),
            previous_memory=WorldMemory.empty(),
        )
        assert len(memory) == 1
        assert memory.facts[0].fact_type is MemoryFactType.WALL_BUILT
        return

    if event_type is EventType.LAW_RESTORED:
        memory = MemorySignificance().distill_episode(
            world=restoration_world(),
            event_log=log_of(law_restored_event(tick=250)),
            previous_memory=episode_zero_memory(),
        )
        assert len(memory) == 2
        assert memory.facts[1].fact_type is MemoryFactType.LAW_RESTORED_WALL_PERSISTED
        return

    memory = MemorySignificance().distill_episode(
        world=build_world(tick=40),
        event_log=log_of(Event(tick=10, type=event_type, payload={}, source_id="district_a")),
        previous_memory=WorldMemory.empty(),
    )
    assert memory.facts == ()
    assert memory.through_episode == 0
    assert memory.through_tick == 40


# --- Defect C: fact document keys must be exact ordinary strings ------------


class SneakyMapping(Mapping):
    """A mapping whose iteration exposes a key that is not the key it answers to.

    Nothing forbids this. It is what makes iteration rather than lookup the only
    honest way to learn a document's actual shape.
    """

    def __init__(self, base: Mapping, *, disguise: str) -> None:
        """Wrap a document, disguising one key when iterated."""
        self._base = dict(base)
        self._disguise = disguise

    def __getitem__(self, key: object) -> object:
        """Answer lookups exactly as the underlying document would."""
        return self._base[key]

    def __len__(self) -> int:
        """Report the underlying document's size."""
        return len(self._base)

    def __iter__(self):
        """Expose one key as a subclass while the rest stay ordinary."""
        for key in self._base:
            yield StringSubclass(key) if key == self._disguise else key


def test_the_disguised_keys_really_do_compare_equal() -> None:
    """Guards the technique used by every key test below."""
    document = wall_built_fact().to_document()
    subclass_keys = {StringSubclass(key): value for key, value in document.items()}

    assert set(subclass_keys) == set(document)
    assert subclass_keys["fact_id"] == document["fact_id"]
    assert SpoofedKey.FACT_ID == "fact_id"
    assert not any(type(key) is str for key in subclass_keys)


def test_a_document_whose_keys_are_all_subclasses_is_refused() -> None:
    """Set arithmetic cannot tell the difference, so the keys are inspected."""
    document = wall_built_fact().to_document()
    with pytest.raises(TypeError):
        MemoryFact.from_document({StringSubclass(key): value for key, value in document.items()})


def test_a_single_required_key_replaced_by_a_str_enum_is_refused() -> None:
    """One disguised key is enough; every key has to be an ordinary string."""
    document = wall_built_fact().to_document()
    disguised = {key: value for key, value in document.items() if key != "fact_id"}
    disguised[SpoofedKey.FACT_ID] = document["fact_id"]

    with pytest.raises(TypeError):
        MemoryFact.from_document(disguised)


@pytest.mark.parametrize("key", [7, True, 1.0, None, ("fact_id",), Arbitrary()])
def test_an_extra_non_string_key_is_refused_as_a_type_error(key: object) -> None:
    """The key type is what is wrong, so that is what the error must say.

    Candidate V3 reported this as an unexpected key -- true, but it described the
    lesser of the two problems and would have missed a disguised key entirely.
    """
    document = wall_built_fact().to_document()
    with pytest.raises(TypeError):
        MemoryFact.from_document({**document, key: "surprise"})


def test_a_mapping_that_hides_a_subclass_key_is_refused() -> None:
    """Iteration is the document's shape; lookups can say something else."""
    document = wall_built_fact().to_document()
    sneaky = SneakyMapping(document, disguise="fact_id")

    assert sneaky["fact_id"] == document["fact_id"], "lookups still behave normally"
    with pytest.raises(TypeError):
        MemoryFact.from_document(sneaky)


def test_an_ordinary_document_still_deserializes() -> None:
    """The control case for every key check above."""
    fact = wall_built_fact()
    document = fact.to_document()

    assert all(type(key) is str for key in document)
    assert MemoryFact.from_document(document) == fact


def test_nothing_is_coerced_or_rebuilt() -> None:
    """A refused document is left exactly as it was, not repaired into shape."""
    document = {
        StringSubclass(key): value for key, value in wall_built_fact().to_document().items()
    }
    before = list(document)

    with pytest.raises(TypeError):
        MemoryFact.from_document(document)

    assert list(document) == before
    assert all(type(key) is StringSubclass for key in document)
