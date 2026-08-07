"""Tests for MemoryQuery: filtering remembered facts without changing them."""

import pytest

from living_diorama.events import EventType
from living_diorama.memory import MemoryFactType, MemoryQuery, WorldMemory
from memory.conftest import BOUNDARY_ID, LAW_ID, WALL_ID, wall_built_fact, wall_persisted_fact


def sample_memory() -> WorldMemory:
    """Return a two-episode memory holding three facts."""
    first = wall_built_fact(
        tick=10, source_event_index=0, wall_id="wall_one", boundary_id="boundary_one"
    )
    second = wall_built_fact(
        tick=20, source_event_index=1, wall_id="wall_two", boundary_id="boundary_two"
    )
    third = wall_persisted_fact(
        episode=1, tick=250, wall_id="wall_one", boundary_id="boundary_one", wall_built_tick=10
    )
    return (
        WorldMemory.empty()
        .advance(episode=0, tick=100, new_facts=(first, second))
        .advance(episode=1, tick=250, new_facts=(third,))
    )


def test_with_no_filters_every_fact_comes_back() -> None:
    """A query with nothing to narrow returns the whole history, in order."""
    memory = sample_memory()
    assert MemoryQuery(memory).facts() == memory.facts


def test_filtering_by_fact_type() -> None:
    """The commonest question: what did the world build?"""
    facts = MemoryQuery(sample_memory()).facts(fact_type=MemoryFactType.WALL_BUILT)
    assert len(facts) == 2
    assert all(fact.fact_type is MemoryFactType.WALL_BUILT for fact in facts)


def test_filtering_by_episode() -> None:
    """What happened in one chapter of the world's life."""
    assert len(MemoryQuery(sample_memory()).facts(episode=0)) == 2
    assert len(MemoryQuery(sample_memory()).facts(episode=1)) == 1
    assert MemoryQuery(sample_memory()).facts(episode=9) == ()


def test_filtering_by_an_inclusive_tick_range() -> None:
    """Both bounds count, so a single-tick window is expressible."""
    query = MemoryQuery(sample_memory())
    assert len(query.facts(tick_start=10, tick_end=20)) == 2
    assert len(query.facts(tick_start=10, tick_end=10)) == 1
    assert len(query.facts(tick_start=21)) == 1
    assert len(query.facts(tick_end=19)) == 1


def test_filtering_by_source_event_type() -> None:
    """Which kind of occurrence produced the fact."""
    query = MemoryQuery(sample_memory())
    assert len(query.facts(source_event_type=EventType.WALL_BUILT)) == 2
    assert len(query.facts(source_event_type=EventType.LAW_RESTORED)) == 1
    assert query.facts(source_event_type=EventType.SCARCITY_CHANGED) == ()


def test_filtering_by_source_id() -> None:
    """The entity whose event produced the fact."""
    assert len(MemoryQuery(sample_memory()).facts(source_id="wall_one")) == 1
    assert len(MemoryQuery(sample_memory()).facts(source_id=LAW_ID)) == 1


def test_filtering_by_subject_id_finds_every_role() -> None:
    """Sorted subjects are what make this total: a district is found too."""
    query = MemoryQuery(sample_memory())
    assert len(query.facts(subject_id="wall_one")) == 2, "built, then persisted"
    assert len(query.facts(subject_id="district_a")) == 2
    assert len(query.facts(subject_id=LAW_ID)) == 1


def test_an_unknown_subject_returns_nothing() -> None:
    """An empty tuple, not an error: the world simply never mentions it."""
    assert MemoryQuery(sample_memory()).facts(subject_id="nobody") == ()


def test_filters_combine_with_and() -> None:
    """Every supplied filter must hold."""
    query = MemoryQuery(sample_memory())
    assert len(query.facts(fact_type=MemoryFactType.WALL_BUILT, episode=0)) == 2
    assert query.facts(fact_type=MemoryFactType.WALL_BUILT, episode=1) == ()
    assert len(query.facts(subject_id="wall_one", tick_start=200)) == 1


def test_results_keep_canonical_order() -> None:
    """A filtered view still reads forwards through the history."""
    facts = MemoryQuery(sample_memory()).facts(subject_id="wall_one")
    assert [fact.tick for fact in facts] == [10, 250]


def test_results_are_immutable_tuples() -> None:
    """A caller holding a result cannot reach into the memory through it."""
    facts = MemoryQuery(sample_memory()).facts()
    assert isinstance(facts, tuple)
    with pytest.raises(TypeError):
        facts[0] = facts[1]  # type: ignore[index]


def test_querying_does_not_change_the_memory() -> None:
    """A query is a read."""
    memory = sample_memory()
    before = (memory.facts, memory.through_episode, memory.through_tick)
    query = MemoryQuery(memory)
    query.facts(subject_id="wall_one")
    query.narration_context(limit=1)
    assert (memory.facts, memory.through_episode, memory.through_tick) == before


def test_narration_context_returns_the_stored_summaries() -> None:
    """Exactly what each fact already says about itself; nothing is generated."""
    memory = sample_memory()
    assert MemoryQuery(memory).narration_context() == tuple(fact.summary for fact in memory.facts)


def test_a_limit_selects_the_latest_facts_but_reads_them_forwards() -> None:
    """A recap covers the recent past, and is still told in order."""
    memory = sample_memory()
    context = MemoryQuery(memory).narration_context(limit=2)

    assert context == (memory.facts[1].summary, memory.facts[2].summary)


def test_a_limit_of_zero_returns_nothing() -> None:
    """Asking for no context is a legitimate request, not an error."""
    assert MemoryQuery(sample_memory()).narration_context(limit=0) == ()


def test_a_limit_larger_than_the_history_returns_everything() -> None:
    """Nothing is invented to fill the gap."""
    assert len(MemoryQuery(sample_memory()).narration_context(limit=99)) == 3


def test_narration_context_filters_the_same_way() -> None:
    """Type and subject narrow the recap too."""
    query = MemoryQuery(sample_memory())
    assert len(query.narration_context(fact_type=MemoryFactType.WALL_BUILT)) == 2
    assert len(query.narration_context(subject_id=LAW_ID)) == 1


@pytest.mark.parametrize("bad", [True, -1, 1.0, "1"])
def test_an_invalid_limit_is_refused(bad: object) -> None:
    """``True`` is not a count, and neither is a negative number."""
    with pytest.raises((TypeError, ValueError)):
        MemoryQuery(sample_memory()).narration_context(limit=bad)


@pytest.mark.parametrize("bad", [True, 1.0, "0", -1])
def test_an_invalid_episode_filter_is_refused(bad: object) -> None:
    """Exact non-negative ints, as everywhere else."""
    with pytest.raises((TypeError, ValueError)):
        MemoryQuery(sample_memory()).facts(episode=bad)


@pytest.mark.parametrize("field", ["tick_start", "tick_end"])
@pytest.mark.parametrize("bad", [True, 1.0, "0", -1])
def test_an_invalid_tick_bound_is_refused(field: str, bad: object) -> None:
    """Both bounds get the same treatment."""
    with pytest.raises((TypeError, ValueError)):
        MemoryQuery(sample_memory()).facts(**{field: bad})


def test_an_inverted_tick_range_is_refused() -> None:
    """An empty window is almost certainly a mistake, so it is reported."""
    with pytest.raises(ValueError):
        MemoryQuery(sample_memory()).facts(tick_start=100, tick_end=99)


def test_an_equal_tick_range_is_accepted() -> None:
    """The boundary case on the permitted side."""
    assert len(MemoryQuery(sample_memory()).facts(tick_start=10, tick_end=10)) == 1


@pytest.mark.parametrize("bad", ["WALL_BUILT", EventType.WALL_BUILT, 0])
def test_a_mistyped_fact_type_filter_is_refused(bad: object) -> None:
    """A string naming the type is not the type."""
    with pytest.raises(TypeError):
        MemoryQuery(sample_memory()).facts(fact_type=bad)


@pytest.mark.parametrize("bad", ["WALL_BUILT", MemoryFactType.WALL_BUILT, 0])
def test_a_mistyped_source_event_type_filter_is_refused(bad: object) -> None:
    """The same rule for the event vocabulary."""
    with pytest.raises(TypeError):
        MemoryQuery(sample_memory()).facts(source_event_type=bad)


@pytest.mark.parametrize("bad", ["", " wall", "wall ", 1, True])
def test_a_noncanonical_identifier_filter_is_refused(bad: object) -> None:
    """A filter that could never match anything is a mistake worth reporting."""
    with pytest.raises((TypeError, ValueError)):
        MemoryQuery(sample_memory()).facts(source_id=bad)
    with pytest.raises((TypeError, ValueError)):
        MemoryQuery(sample_memory()).facts(subject_id=bad)


@pytest.mark.parametrize("bad", [None, "memory", 0, []])
def test_a_query_over_a_non_memory_is_refused(bad: object) -> None:
    """The domain object is required."""
    with pytest.raises(TypeError):
        MemoryQuery(bad)


def test_an_empty_memory_answers_every_query_with_nothing() -> None:
    """A world at its very beginning remembers nothing, and says so."""
    query = MemoryQuery(WorldMemory.empty())
    assert query.facts() == ()
    assert query.narration_context() == ()
    assert query.facts(subject_id=WALL_ID, fact_type=MemoryFactType.WALL_BUILT) == ()
    assert query.memory is not None
    assert BOUNDARY_ID not in {subject for fact in query.facts() for subject in fact.subject_ids}


def test_a_hostile_object_is_refused_as_a_memory() -> None:
    """The memory's true runtime type decides, not its ``__class__`` property."""

    class HostileClass:
        """Raises from ``__class__`` instead of answering."""

        @property
        def __class__(self) -> type:
            """Raise instead of revealing a type."""
            raise RuntimeError("boom")

    with pytest.raises(TypeError, match="memory must be a WorldMemory, got HostileClass"):
        MemoryQuery(HostileClass())
