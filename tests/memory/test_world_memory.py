"""Tests for WorldMemory: append-only accumulation and canonical ordering.

Memory is the mechanism behind the series' promise that a consequence outlives
the episode that caused it. Most of these tests are about what it refuses to
do: drop a fact, reorder one, accept a second claim that the same wall was
built, or let a checkpoint skip an episode.
"""

from enum import IntEnum, StrEnum
from types import MappingProxyType

import pytest

from living_diorama.events import EventType
from living_diorama.memory import MemoryFact, MemoryFactType, WorldMemory
from living_diorama.memory.world_memory import _freeze, require_law_value, require_unit_interval
from memory.conftest import wall_built_fact, wall_persisted_fact


def test_an_empty_memory_has_processed_nothing() -> None:
    """Nothing remembered, and no episode claimed as processed."""
    memory = WorldMemory.empty()

    assert memory.facts == ()
    assert memory.through_episode is None
    assert memory.through_tick is None
    assert len(memory) == 0
    assert list(memory) == []


def test_an_unprocessed_memory_cannot_already_hold_facts() -> None:
    """A fact exists only because an episode was distilled."""
    with pytest.raises(ValueError):
        WorldMemory((wall_built_fact(),))


def test_a_checkpoint_needs_both_halves() -> None:
    """An episode without a tick describes no moment at all."""
    with pytest.raises(ValueError):
        WorldMemory((), through_episode=0)
    with pytest.raises(ValueError):
        WorldMemory((), through_tick=0)


def test_the_first_processed_episode_must_be_zero() -> None:
    """A world's history starts where the world does."""
    with pytest.raises(ValueError):
        WorldMemory.empty().advance(episode=1, tick=10)


def test_advancing_records_the_checkpoint_even_with_no_facts() -> None:
    """An uneventful episode is still an episode that was processed.

    Leaving the checkpoint behind would make the next episode look like a gap.
    """
    memory = WorldMemory.empty().advance(episode=0, tick=40)

    assert memory.facts == ()
    assert memory.through_episode == 0
    assert memory.through_tick == 40


def test_episodes_advance_one_at_a_time() -> None:
    """Each episode follows the one before it."""
    memory = WorldMemory.empty().advance(episode=0, tick=10)
    memory = memory.advance(episode=1, tick=20)
    memory = memory.advance(episode=2, tick=30)

    assert memory.through_episode == 2
    assert memory.through_tick == 30


def test_an_episode_gap_is_refused() -> None:
    """Skipping an episode would silently lose whatever happened in it."""
    memory = WorldMemory.empty().advance(episode=0, tick=10)
    with pytest.raises(ValueError):
        memory.advance(episode=2, tick=20)


def test_an_episode_rewind_is_refused() -> None:
    """History does not run backwards."""
    memory = WorldMemory.empty().advance(episode=0, tick=10).advance(episode=1, tick=20)
    with pytest.raises(ValueError):
        memory.advance(episode=1, tick=30)


def test_a_tick_rewind_is_refused() -> None:
    """World time accumulates across episodes; it never goes back."""
    memory = WorldMemory.empty().advance(episode=0, tick=100)
    with pytest.raises(ValueError):
        memory.advance(episode=1, tick=99)


def test_the_same_tick_is_allowed_when_nothing_happened() -> None:
    """An episode that advanced no ticks is unusual but not contradictory."""
    memory = WorldMemory.empty().advance(episode=0, tick=100).advance(episode=1, tick=100)
    assert memory.through_tick == 100


def test_earlier_facts_are_preserved_exactly() -> None:
    """Nothing is rewritten, summarized away, or compacted."""
    first = wall_built_fact(tick=10, wall_id="wall_one", boundary_id="boundary_one")
    memory = WorldMemory.empty().advance(episode=0, tick=100, new_facts=(first,))
    later = wall_persisted_fact(
        episode=1, tick=250, wall_id="wall_one", boundary_id="boundary_one", wall_built_tick=10
    )
    grown = memory.advance(episode=1, tick=250, new_facts=(later,))

    assert grown.facts[0] is first
    assert grown.facts == (first, later)
    assert len(grown) == 2


def test_advancing_leaves_the_previous_memory_untouched() -> None:
    """Memory is a value; growing it produces a new one."""
    memory = WorldMemory.empty().advance(episode=0, tick=100, new_facts=(wall_built_fact(tick=10),))
    grown = memory.advance(
        episode=1, tick=250, new_facts=(wall_persisted_fact(wall_built_tick=10),)
    )

    assert len(memory) == 1
    assert memory.through_episode == 0
    assert grown is not memory
    assert len(grown) == 2


def test_a_fact_from_another_episode_is_refused() -> None:
    """Facts belong to the episode being processed."""
    with pytest.raises(ValueError):
        WorldMemory.empty().advance(
            episode=0, tick=100, new_facts=(wall_built_fact(episode=1, tick=10),)
        )


def test_a_fact_after_the_episode_closed_is_refused() -> None:
    """Nothing happens after the episode's last tick."""
    with pytest.raises(ValueError):
        WorldMemory.empty().advance(episode=0, tick=50, new_facts=(wall_built_fact(tick=51),))


def test_a_fact_inside_an_already_processed_window_is_refused() -> None:
    """A later episode cannot add facts to a tick already accounted for."""
    memory = WorldMemory.empty().advance(episode=0, tick=100, new_facts=(wall_built_fact(tick=10),))
    with pytest.raises(ValueError):
        memory.advance(
            episode=1, tick=250, new_facts=(wall_persisted_fact(tick=100, wall_built_tick=10),)
        )


def test_out_of_order_facts_are_refused() -> None:
    """Canonical order is required, never imposed by silent sorting."""
    later = wall_built_fact(
        tick=20, source_event_index=1, wall_id="wall_two", boundary_id="boundary_two"
    )
    earlier = wall_built_fact(
        tick=10, source_event_index=0, wall_id="wall_one", boundary_id="boundary_one"
    )
    with pytest.raises(ValueError):
        WorldMemory.empty().advance(episode=0, tick=100, new_facts=(later, earlier))


def test_facts_are_ordered_by_episode_then_tick_then_event_position() -> None:
    """Two facts from one tick replay in the order the engine emitted them."""
    first = wall_built_fact(
        tick=10, source_event_index=2, wall_id="wall_one", boundary_id="boundary_one"
    )
    second = wall_built_fact(
        tick=10, source_event_index=5, wall_id="wall_two", boundary_id="boundary_two"
    )
    memory = WorldMemory.empty().advance(episode=0, tick=100, new_facts=(first, second))
    assert [fact.source_event_index for fact in memory] == [2, 5]


def test_a_duplicate_fact_id_is_refused() -> None:
    """One identifier names one fact."""
    fact = wall_built_fact()
    with pytest.raises(ValueError):
        WorldMemory.empty().advance(episode=0, tick=120, new_facts=(fact, fact))


def test_a_second_claim_that_a_wall_was_built_is_refused() -> None:
    """A wall is built once; a second claim means the history is wrong."""
    first = wall_built_fact(tick=10, source_event_index=0)
    second = wall_built_fact(tick=20, source_event_index=1)
    with pytest.raises(ValueError):
        WorldMemory.empty().advance(episode=0, tick=100, new_facts=(first, second))


def test_a_wall_rebuilt_in_a_later_episode_is_refused() -> None:
    """Including across the episode boundary, where the first fact was inherited."""
    memory = WorldMemory.empty().advance(episode=0, tick=100, new_facts=(wall_built_fact(tick=10),))
    with pytest.raises(ValueError):
        memory.advance(episode=1, tick=250, new_facts=(wall_built_fact(episode=1, tick=200),))


def test_a_fact_beyond_the_checkpoint_is_refused_at_construction() -> None:
    """A loaded memory cannot hold a fact from after the episode it records."""
    with pytest.raises(ValueError):
        WorldMemory((wall_built_fact(tick=120),), through_episode=0, through_tick=100)
    with pytest.raises(ValueError):
        WorldMemory((wall_built_fact(episode=1, tick=10),), through_episode=0, through_tick=100)


def test_facts_is_an_immutable_tuple() -> None:
    """A caller holding the facts cannot reach back into the history."""
    memory = WorldMemory.empty().advance(episode=0, tick=120, new_facts=(wall_built_fact(),))
    assert isinstance(memory.facts, tuple)
    with pytest.raises(TypeError):
        memory.facts[0] = wall_built_fact(tick=1)  # type: ignore[index]


def test_iteration_preserves_canonical_order() -> None:
    """Iterating is reading the history forwards."""
    first = wall_built_fact(
        tick=10, source_event_index=0, wall_id="wall_one", boundary_id="boundary_one"
    )
    second = wall_built_fact(
        tick=20, source_event_index=1, wall_id="wall_two", boundary_id="boundary_two"
    )
    memory = WorldMemory.empty().advance(episode=0, tick=100, new_facts=(first, second))
    assert list(memory) == [first, second]
    assert len(memory) == 2


def test_equality_covers_facts_and_checkpoint() -> None:
    """Two memories agree only if they remember the same things at the same point."""
    built = wall_built_fact()
    left = WorldMemory.empty().advance(episode=0, tick=120, new_facts=(built,))
    right = WorldMemory.empty().advance(episode=0, tick=120, new_facts=(built,))
    other_checkpoint = WorldMemory.empty().advance(episode=0, tick=121, new_facts=(built,))

    assert left == right
    assert left != other_checkpoint
    assert left != WorldMemory.empty()
    assert left != "not a memory"


@pytest.mark.parametrize("bad", [True, 1.0, "0", None])
def test_a_mistyped_checkpoint_is_refused(bad: object) -> None:
    """``True == 0`` is false but ``True == 1`` is not; exact types only."""
    with pytest.raises(TypeError):
        WorldMemory.empty().advance(episode=bad, tick=10)
    with pytest.raises(TypeError):
        WorldMemory.empty().advance(episode=0, tick=bad)


def test_a_non_fact_is_refused() -> None:
    """Memory holds facts, not things shaped like them."""
    with pytest.raises(TypeError):
        WorldMemory.empty().advance(episode=0, tick=10, new_facts=({"fact": True},))
    with pytest.raises(TypeError):
        WorldMemory(({"fact": True},), through_episode=0, through_tick=10)


# --- require_unit_interval ---------------------------------------------------


class ExactnessEnum(IntEnum):
    """An in-range value carried by an ``int`` subclass, refused by exactness."""

    ZERO = 0


class IntSubclass(int):
    """Equal to an ``int``, but not exactly one."""


class FloatSubclass(float):
    """Equal to a ``float``, but not exactly one."""


@pytest.mark.parametrize("value", [0, 1, 0.0, 1.0, 0.5])
def test_a_unit_interval_accepts_exact_ints_and_floats(value: float) -> None:
    """Exactly-typed real numbers inside 0.0-1.0 come back as plain floats."""
    result = require_unit_interval(value, "value")
    assert type(result) is float
    assert result == float(value)


@pytest.mark.parametrize(
    "value",
    [True, False, ExactnessEnum.ZERO, IntSubclass(0), FloatSubclass(0.5), "0.5", None, object()],
)
def test_a_unit_interval_refuses_inexact_and_non_numeric_types(value: object) -> None:
    """Bools, number subclasses, and non-numbers raise the standard TypeError."""
    with pytest.raises(TypeError, match=f"value must be a real number, got {type(value).__name__}"):
        require_unit_interval(value, "value")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -0.1, 1.1, -1, 2])
def test_a_unit_interval_refuses_non_finite_and_out_of_range_numbers(value: float) -> None:
    """A real number that is not a finite value inside 0.0-1.0 is refused."""
    with pytest.raises(ValueError):
        require_unit_interval(value, "value")


def test_a_hostile_class_property_cannot_preempt_exact_validation() -> None:
    """``type()`` decides before anything can consult ``__class__``.

    Candidate V8's isinstance-first guard handed control to a caller-defined
    ``__class__`` override before the value was validated, letting the
    override's own exception replace the standard TypeError.
    """

    class HostileClass:
        """Raises from ``__class__`` instead of answering."""

        @property
        def __class__(self) -> type:
            """Raise instead of revealing a type."""
            raise RuntimeError("boom")

    with pytest.raises(TypeError, match="value must be a real number, got HostileClass"):
        require_unit_interval(HostileClass(), "value")


# --- require_law_value -------------------------------------------------------


class ExactnessStrEnum(StrEnum):
    """An in-range value carried by a ``str`` subclass through the enum machinery."""

    LABEL = "label"


class StrSubclass(str):
    """Equal to a ``str``, but not exactly one."""


class ListSubclass(list):
    """Equal to a ``list``, but not exactly one."""


class DictSubclass(dict):
    """Equal to a ``dict``, but not exactly one."""


class HostileClassProperty:
    """Raises from ``__class__`` instead of answering."""

    @property
    def __class__(self) -> type:
        """Raise instead of revealing a type."""
        raise RuntimeError("boom")


def test_a_law_value_accepts_exact_json_scalars() -> None:
    """Exactly-typed scalars come back as the very same object."""
    for value in (None, True, False, 0, 7, 0.5, -2.5, "", "speed limit"):
        assert require_law_value(value, "value") is value


@pytest.mark.parametrize(
    "value",
    [
        ExactnessEnum.ZERO,
        ExactnessStrEnum.LABEL,
        IntSubclass(0),
        FloatSubclass(0.5),
        StrSubclass("x"),
        [1],
        {"a": 1},
        (1,),
        object(),
    ],
)
def test_a_law_value_refuses_inexact_and_non_scalar_types(value: object) -> None:
    """Subclassed primitives, containers, and foreign objects are refused."""
    with pytest.raises(
        TypeError,
        match=(
            f"value must be null, a bool, an int, a finite float, or a str, "
            f"got {type(value).__name__}"
        ),
    ):
        require_law_value(value, "value")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_law_value_refuses_non_finite_floats(value: float) -> None:
    """A law's numeric setting must be a finite number."""
    with pytest.raises(ValueError):
        require_law_value(value, "value")


def test_a_hostile_class_property_cannot_preempt_law_value_validation() -> None:
    """``type()`` decides before anything can consult ``__class__``.

    Candidate V9's guard ran ``isinstance`` first, handing control to a
    caller-defined ``__class__`` override whose own exception then replaced
    the documented TypeError.
    """

    class HostileClass:
        """Raises from ``__class__`` instead of answering."""

        @property
        def __class__(self) -> type:
            """Raise instead of revealing a type."""
            raise RuntimeError("boom")

    with pytest.raises(
        TypeError,
        match="value must be null, a bool, an int, a finite float, or a str, got HostileClass",
    ):
        require_law_value(HostileClass(), "value")


# --- _freeze -----------------------------------------------------------------


def test_freeze_returns_deeply_immutable_exact_copies() -> None:
    """Exact JSON freezes to tuples and read-only mappings at every depth."""
    document = {
        "empty": None,
        "flag": True,
        "count": 3,
        "score": 0.5,
        "name": "x",
        "items": [1, "two", {"nested": [0.0]}],
    }
    frozen = _freeze(document, "details")

    assert type(frozen) is MappingProxyType
    assert frozen["empty"] is None
    assert frozen["flag"] is True
    assert frozen["count"] == 3
    assert frozen["score"] == 0.5
    assert frozen["name"] == "x"
    items = frozen["items"]
    assert type(items) is tuple
    assert items[0] == 1
    assert items[1] == "two"
    assert type(items[2]) is MappingProxyType
    assert items[2]["nested"] == (0.0,)
    # The caller's document was read, never rewritten.
    assert document == {
        "empty": None,
        "flag": True,
        "count": 3,
        "score": 0.5,
        "name": "x",
        "items": [1, "two", {"nested": [0.0]}],
    }
    assert type(document["items"]) is list


@pytest.mark.parametrize(
    "value",
    [
        ExactnessEnum.ZERO,
        ExactnessStrEnum.LABEL,
        IntSubclass(0),
        FloatSubclass(0.5),
        StrSubclass("x"),
        ListSubclass(),
        DictSubclass(),
        (1,),
        {1, 2},
        object(),
    ],
)
def test_freeze_refuses_inexact_containers_and_foreign_types(value: object) -> None:
    """Subclassed primitives and containers, tuples, sets, and objects are refused."""
    with pytest.raises(
        TypeError, match=f"value must be JSON-compatible, got {type(value).__name__}"
    ):
        _freeze(value, "value")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_freeze_refuses_non_finite_numbers(value: float) -> None:
    """A fact may not carry a number JSON cannot represent, at any depth."""
    with pytest.raises(ValueError):
        _freeze(value, "value")
    with pytest.raises(ValueError):
        _freeze([value], "value")


def test_freeze_refuses_non_string_object_keys() -> None:
    """JSON object keys are strings; anything else is refused, not coerced."""
    with pytest.raises(TypeError, match="has a non-string key"):
        _freeze({1: "x"}, "value")


def test_a_hostile_class_property_cannot_preempt_freeze_validation() -> None:
    """``type()`` decides at every depth before anything consults ``__class__``.

    Candidate V9's ``_freeze`` ran ``isinstance`` first, so a hostile value at
    any nesting level could replace the documented TypeError with its own
    exception.
    """
    with pytest.raises(TypeError, match="value must be JSON-compatible, got HostileClassProperty"):
        _freeze(HostileClassProperty(), "value")
    with pytest.raises(
        TypeError, match=r"value\[0\] must be JSON-compatible, got HostileClassProperty"
    ):
        _freeze([HostileClassProperty()], "value")
    with pytest.raises(
        TypeError, match=r"value\['hostile'\] must be JSON-compatible, got HostileClassProperty"
    ):
        _freeze({"hostile": HostileClassProperty()}, "value")


def test_a_hostile_detail_is_refused_as_json_incompatible() -> None:
    """A fact's own validation refuses a hostile detail with the documented error."""

    class HostileClass:
        """Raises from ``__class__`` instead of answering."""

        @property
        def __class__(self) -> type:
            """Raise instead of revealing a type."""
            raise RuntimeError("boom")

    with pytest.raises(
        TypeError, match=r"details\['hostile'\] must be JSON-compatible, got HostileClass"
    ):
        MemoryFact(
            fact_type=MemoryFactType.WALL_BUILT,
            episode=0,
            tick=1,
            source_event_index=0,
            source_event_type=EventType.WALL_BUILT,
            source_id="wall_a",
            subject_ids=("wall_a",),
            details={"hostile": HostileClass()},
        )


# --- hostile __class__ at the object boundaries ------------------------------


class HostileClass:
    """Raises from ``__class__`` instead of answering."""

    @property
    def __class__(self) -> type:
        """Raise instead of revealing a type."""
        raise RuntimeError("boom")


def test_a_hostile_document_is_refused_at_the_fact_boundary() -> None:
    """``from_document`` refuses a non-mapping from its true runtime type."""
    with pytest.raises(TypeError, match="fact must be a mapping, got HostileClass"):
        MemoryFact.from_document(HostileClass())


def test_a_hostile_details_object_is_refused_as_a_non_mapping() -> None:
    """The details boundary decides from the true runtime type."""
    with pytest.raises(TypeError, match="details must be a mapping, got HostileClass"):
        MemoryFact(
            fact_type=MemoryFactType.WALL_BUILT,
            episode=0,
            tick=1,
            source_event_index=0,
            source_event_type=EventType.WALL_BUILT,
            source_id="wall_a",
            subject_ids=("wall_a",),
            details=HostileClass(),
        )


def test_a_hostile_fact_is_refused_by_the_memory_constructor() -> None:
    """A non-fact entry is refused from its true runtime type."""
    with pytest.raises(TypeError, match=r"facts\[0\] must be a MemoryFact, got HostileClass"):
        WorldMemory((HostileClass(),), through_episode=0, through_tick=1)


def test_a_hostile_fact_is_refused_by_advance() -> None:
    """A non-fact appended later is refused from its true runtime type."""
    with pytest.raises(TypeError, match=r"new_facts\[0\] must be a MemoryFact, got HostileClass"):
        WorldMemory.empty().advance(episode=0, tick=1, new_facts=(HostileClass(),))


def test_a_hostile_object_compares_unequal_without_being_consulted() -> None:
    """``__eq__`` answers from the true runtime type, never the object itself."""
    assert (WorldMemory.empty() == HostileClass()) is False
    assert (WorldMemory.empty() != HostileClass()) is True
