"""Tests for exact derived strings and exact source identifiers in snapshots.

``MemoryFact.from_document`` already refuses a persisted document whose
``fact_id`` or ``summary`` is anything but an exact plain string. Candidate V6
regressed that standard inside :func:`snapshot_memory_fact`, which compared the
claimed values by equality alone -- so a ``str`` subclass, a ``StrEnum`` member,
or an object whose ``__eq__`` simply agrees could all pass as derived fields.
The same candidate captured an Event's ``source_id`` and handed it to the base
constructor, which strips whitespace and admits ``str`` subclasses: a corrupted
identifier was quietly repaired instead of refused.

A semantic snapshot records what the caller's object reported. It never
launders, never repairs, and never substitutes the normalized value for a
malformed claim.
"""

import tempfile
from enum import StrEnum
from pathlib import Path

import pytest

from living_diorama.events import Event, EventType
from living_diorama.memory import MemoryFact, MemorySignificance, WorldMemory
from living_diorama.memory._integrity import (
    snapshot_event_log,
    snapshot_memory_fact,
    snapshot_world_memory,
)
from living_diorama.persistence import SaveManager
from living_diorama.persistence.serializers.world_memory_serializer import (
    serialize_world_memory,
)
from memory.conftest import (
    WALL_ID,
    log_of,
    wall_built_event,
    wall_built_fact,
    world_with_wall,
)


class StringSubclass(str):
    """A ``str`` subclass: equal to a plain string, and not one."""


class Agreeable:
    """An object whose equality agrees with anything it is compared against."""

    def __eq__(self, other: object) -> bool:
        """Agree."""
        return True

    def __hash__(self) -> int:
        """Hash consistently with the indiscriminate equality above."""
        return 0


class WallSource(StrEnum):
    """A ``StrEnum`` member equal to the canonical wall identifier."""

    MEMBER = WALL_ID


class ReportingFact(MemoryFact):
    """Fact whose derived fields report chosen values after construction.

    The honest derived values are recorded when the base constructor assigns
    them; installing a report afterwards makes every later read answer with the
    doctored value instead. Equality with the honest value is exactly what the
    doctored shapes are chosen to preserve.
    """

    @property
    def fact_id(self) -> object:
        """Answer the doctored identifier once installed, the real one before."""
        if "reported_fact_id" in self.__dict__:
            return self.__dict__["reported_fact_id"]
        return self.__dict__.get("derived_fact_id")

    @fact_id.setter
    def fact_id(self, value: object) -> None:
        """Record the identifier the fact honestly derived."""
        self.__dict__["derived_fact_id"] = value

    @property
    def summary(self) -> object:
        """Answer the doctored summary once installed, the real one before."""
        if "reported_summary" in self.__dict__:
            return self.__dict__["reported_summary"]
        return self.__dict__.get("derived_summary")

    @summary.setter
    def summary(self, value: object) -> None:
        """Record the summary the fact honestly derived."""
        self.__dict__["derived_summary"] = value


class ReportingSourceEvent(Event):
    """Event whose ``source_id`` reports a chosen value after construction."""

    @property
    def source_id(self) -> object:
        """Answer the doctored value once installed, the stored one before."""
        if "reported" in self.__dict__:
            return self.__dict__["reported"]
        return self.__dict__.get("constructed")

    @source_id.setter
    def source_id(self, value: object) -> None:
        """Record the honest value the constructor assigned."""
        self.__dict__["constructed"] = value


def doctored_fact(**reports: object) -> ReportingFact:
    """Return a valid wall fact whose named derived fields answer doctored values."""
    base = wall_built_fact()
    fact = ReportingFact(
        fact_type=base.fact_type,
        episode=base.episode,
        tick=base.tick,
        source_event_index=base.source_event_index,
        source_event_type=base.source_event_type,
        source_id=base.source_id,
        subject_ids=base.subject_ids,
        details=base.details_as_dict(),
    )
    for field, value in reports.items():
        fact.__dict__[f"reported_{field}"] = value
    return fact


def doctored_source_event(reported: object) -> ReportingSourceEvent:
    """Return a valid construction event whose ``source_id`` answers a doctored value."""
    event = ReportingSourceEvent(
        tick=120,
        type=EventType.WALL_BUILT,
        payload={"wall_id": WALL_ID},
        source_id=WALL_ID,
    )
    event.__dict__["reported"] = reported
    return event


def built_memory() -> WorldMemory:
    """Return the memory a genuine wall-building episode produces."""
    return MemorySignificance().distill_episode(
        world=world_with_wall(tick=120),
        event_log=log_of(wall_built_event(tick=120)),
        previous_memory=WorldMemory.empty(),
    )


def honest_values() -> tuple[str, str]:
    """Return the derived identifier and summary the doctored fact copies."""
    base = wall_built_fact()
    return base.fact_id, base.summary


# --- Derived fact strings must be exact plain strings ------------------------


def _subclassed(value: str) -> object:
    """Disguise a derived value as a ``str`` subclass."""
    return StringSubclass(value)


def _enum_member(value: str) -> object:
    """Disguise a derived value as a ``StrEnum`` member."""
    return StrEnum("DoctoredValue", {"MEMBER": value}).MEMBER


def _agreeable(value: str) -> object:
    """Replace a derived value with an object that merely agrees when asked."""
    return Agreeable()


DOCTORED_SHAPES = {
    "agreeable_object": _agreeable,
    "str_enum": _enum_member,
    "str_subclass": _subclassed,
}
"""Every shape that equals the honest derived value without being a ``str``."""


@pytest.mark.parametrize("shape", sorted(DOCTORED_SHAPES))
@pytest.mark.parametrize("field", ["fact_id", "summary"])
def test_a_doctored_derived_field_is_refused(field: str, shape: str) -> None:
    """Equality with the derived value is not enough; the claim must be a str."""
    fact_id, summary = honest_values()
    honest = fact_id if field == "fact_id" else summary
    fact = doctored_fact(**{field: DOCTORED_SHAPES[shape](honest)})

    with pytest.raises(TypeError, match=field):
        snapshot_memory_fact(fact, "fact")


@pytest.mark.parametrize("bad", [True, 0, 1.5, None])
@pytest.mark.parametrize("field", ["fact_id", "summary"])
def test_a_mistyped_derived_field_is_refused_as_a_type_error(field: str, bad: object) -> None:
    """A non-string derived claim is a type mistake, not a content mismatch."""
    fact = doctored_fact(**{field: bad})

    with pytest.raises(TypeError, match=field):
        snapshot_memory_fact(fact, "fact")


def test_both_derived_fields_doctored_together_are_refused() -> None:
    """The reviewer's exact adversary: subclassed id and subclassed summary."""
    fact_id, summary = honest_values()
    fact = doctored_fact(fact_id=StringSubclass(fact_id), summary=StringSubclass(summary))

    with pytest.raises(TypeError, match="fact_id"):
        snapshot_memory_fact(fact, "fact")


def test_a_malformed_derived_field_is_never_replaced_with_the_normalized_one() -> None:
    """Refusal, not repair: the doctored fact is left exactly as it was."""
    fact_id, _ = honest_values()
    fact = doctored_fact(fact_id=StringSubclass(fact_id))

    with pytest.raises(TypeError):
        snapshot_memory_fact(fact, "fact")

    assert type(fact.fact_id) is StringSubclass
    assert fact.fact_id == fact_id


def test_an_honest_fact_still_snapshots_to_exact_strings() -> None:
    """The control case: exact plain derived strings pass and stay plain."""
    snapshot = snapshot_memory_fact(wall_built_fact(), "fact")

    assert type(snapshot) is MemoryFact
    assert snapshot == wall_built_fact()
    assert type(snapshot.fact_id) is str
    assert type(snapshot.summary) is str


def test_an_honest_subclassed_fact_with_exact_strings_still_snapshots() -> None:
    """A fact subclass is fine as long as its derived claims are exact strings."""
    snapshot = snapshot_memory_fact(doctored_fact(), "fact")

    assert type(snapshot) is MemoryFact
    assert snapshot == wall_built_fact()


def memory_holding(fact: MemoryFact) -> WorldMemory:
    """Return a processed memory carrying the given fact."""
    return WorldMemory((fact,), through_episode=0, through_tick=120)


def test_the_memory_snapshot_refuses_a_doctored_fact() -> None:
    """``snapshot_world_memory`` normalizes every fact through the same gate."""
    fact_id, _ = honest_values()
    memory = memory_holding(doctored_fact(fact_id=StringSubclass(fact_id)))

    with pytest.raises(TypeError, match="fact_id"):
        snapshot_world_memory(memory, "memory")


def test_the_memory_serializer_refuses_a_doctored_fact() -> None:
    """``serialize_world_memory`` cannot write a fact whose claims are not strings."""
    _, summary = honest_values()
    memory = memory_holding(doctored_fact(summary=StringSubclass(summary)))

    with pytest.raises(TypeError, match="summary"):
        serialize_world_memory(memory)


def test_a_save_holding_a_doctored_fact_is_refused_without_residue() -> None:
    """``save_episode`` refuses the doctored fact and touches nothing on disk."""
    fact_id, summary = honest_values()
    memory = memory_holding(
        doctored_fact(fact_id=StringSubclass(fact_id), summary=StringSubclass(summary))
    )
    world = world_with_wall(tick=120)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        rng_before = world.rng.get_state()

        with pytest.raises(TypeError, match="fact_id"):
            SaveManager(root).save_episode(
                world, log_of(wall_built_event(tick=120)), world_memory=memory
            )

        assert list(root.iterdir()) == [], "a rejected save must leave no residue"
        assert world.rng.get_state() == rng_before


# --- Event source identifiers are validated, never laundered -----------------


REJECTED_SOURCE_IDS = {
    "blank": ("", ValueError),
    "padded": (f" {WALL_ID} ", ValueError),
    "padded_subclass": (StringSubclass(f" {WALL_ID} "), TypeError),
    "str_enum": (WallSource.MEMBER, TypeError),
    "str_subclass": (StringSubclass(WALL_ID), TypeError),
    "whitespace_only": ("   ", ValueError),
}
"""Every reported source shape the snapshot must refuse, and how."""


@pytest.mark.parametrize("case", sorted(REJECTED_SOURCE_IDS))
def test_a_doctored_source_id_is_refused(case: str) -> None:
    """The snapshot records what the event reported; a corrupt report is refused."""
    reported, expected = REJECTED_SOURCE_IDS[case]
    log = log_of(doctored_source_event(reported))

    with pytest.raises(expected, match="source_id"):
        snapshot_event_log(log)


def test_a_padded_source_id_is_not_repaired_by_stripping() -> None:
    """Refusal, not repair: the padded report survives the refusal unchanged."""
    padded = f" {WALL_ID} "
    event = doctored_source_event(padded)

    with pytest.raises(ValueError, match="surrounding whitespace"):
        snapshot_event_log(log_of(event))

    assert event.source_id == padded


def test_a_none_source_id_is_still_accepted() -> None:
    """``None`` remains legitimate for events that carry no source."""
    log = log_of(Event(tick=3, type=EventType.SCARCITY_CHANGED, payload={}, source_id=None))

    events = snapshot_event_log(log)

    assert events[0].source_id is None


def test_an_exact_canonical_source_id_is_still_accepted() -> None:
    """The control case: an exact plain identifier passes through unchanged."""
    events = snapshot_event_log(log_of(wall_built_event(tick=120)))

    assert events[0].source_id == WALL_ID
    assert type(events[0].source_id) is str


def test_an_exact_source_id_with_internal_whitespace_is_still_accepted() -> None:
    """Internal whitespace is legal; only the surroundings are constrained."""
    spaced = "wall boundary ab"
    log = log_of(Event(tick=3, type=EventType.WALL_BUILT, payload={}, source_id=spaced))

    events = snapshot_event_log(log)

    assert events[0].source_id == spaced
    assert type(events[0].source_id) is str


def test_a_save_holding_a_doctored_source_id_is_refused_without_residue() -> None:
    """``save_episode`` refuses the doctored event and touches nothing on disk."""
    world = world_with_wall(tick=120)
    log = log_of(doctored_source_event(StringSubclass(WALL_ID)))
    memory = built_memory()

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        rng_before = world.rng.get_state()

        with pytest.raises(TypeError, match="source_id"):
            SaveManager(root).save_episode(world, log, world_memory=memory)

        assert list(root.iterdir()) == [], "a rejected save must leave no residue"
        assert world.rng.get_state() == rng_before
