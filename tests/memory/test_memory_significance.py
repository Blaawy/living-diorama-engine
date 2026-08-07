"""Tests for MemorySignificance: which events become permanent history.

Significance is a fixed rule, and the rule has two halves: the event type must
be one of the two the MVP remembers, and the final state of the episode must
still corroborate it. Most of these tests exercise the second half, because an
event says something was published -- not that the world ended the episode
agreeing with it.
"""

import pytest

from living_diorama.entities import Boundary, Wall
from living_diorama.events import Event, EventLog, EventType
from living_diorama.memory import MemoryFactType, MemorySignificance, WorldMemory
from living_diorama.memory._integrity import SIGNIFICANT_EVENT_TYPES
from living_diorama.simulation.world import World
from memory.conftest import (
    BOUNDARY_ID,
    LAW_ID,
    WALL_ID,
    build_district,
    build_law,
    build_wall,
    build_world,
    consumed_rng,
    law_restored_event,
    log_of,
    wall_built_event,
    world_with_wall,
)

NON_SIGNIFICANT_TYPES = [
    EventType.LAW_CHANGED,
    EventType.RESOURCE_PRODUCED,
    EventType.RESOURCE_CONSUMED,
    EventType.RESOURCE_TRANSFERRED,
    EventType.POPULATION_MIGRATED,
    EventType.SCARCITY_CHANGED,
    EventType.SOCIAL_STABILITY_CHANGED,
    EventType.INSTITUTIONAL_PRESSURE_CHANGED,
    EventType.WALL_CHANGED,
    EventType.INFRASTRUCTURE_ADAPTED,
]
"""Everything that stays in the log without becoming durable history."""


def distill(world, event_log, previous=None) -> WorldMemory:
    """Distil one episode, defaulting to an unprocessed previous memory."""
    return MemorySignificance().distill_episode(
        world=world,
        event_log=event_log,
        previous_memory=WorldMemory.empty() if previous is None else previous,
    )


def restored_world(*, episode: int = 1, tick: int = 250, built_tick: int = 120, **wall):
    """Build a world whose law has just been restored and whose wall still stands."""
    world = build_world(episode=episode, tick=tick)
    world.add_law(build_law(changed_episode=episode, restored_tick=tick))
    world.add_wall(build_wall(built_tick=built_tick, **wall))
    return world


def episode_zero_memory(*, tick: int = 120) -> WorldMemory:
    """Return the memory produced by an episode zero in which a wall was built."""
    world = world_with_wall(tick=tick, built_tick=tick)
    return distill(world, log_of(wall_built_event(tick=tick)))


# --- Non-significant events -------------------------------------------------


@pytest.mark.parametrize("event_type", NON_SIGNIFICANT_TYPES)
def test_a_non_significant_event_creates_no_fact(event_type: EventType) -> None:
    """It stays in the log, which is persisted in full; it just is not history.

    The checkpoint still advances: the episode was processed, and nothing about
    it was significant.
    """
    world = build_world(tick=40)
    memory = distill(world, log_of(Event(tick=10, type=event_type, payload={}, source_id="x")))

    assert memory.facts == ()
    assert memory.through_episode == 0
    assert memory.through_tick == 40


def test_only_two_event_types_are_significant() -> None:
    """Pinned, so widening the vocabulary has to be deliberate.

    Read from the private module: the constant is machinery, not something a
    caller picks from, so it is not part of the package's public surface.
    """
    assert frozenset({EventType.WALL_BUILT, EventType.LAW_RESTORED}) == SIGNIFICANT_EVENT_TYPES
    assert set(EventType) - SIGNIFICANT_EVENT_TYPES == set(NON_SIGNIFICANT_TYPES)


def test_an_empty_episode_advances_the_checkpoint() -> None:
    """An episode in which nothing at all happened is still processed."""
    memory = distill(build_world(tick=5), EventLog())
    assert memory.through_episode == 0
    assert memory.through_tick == 5


# --- WALL_BUILT -------------------------------------------------------------


def test_a_wall_construction_becomes_one_durable_fact() -> None:
    """The central case, verified against the wall the world actually holds."""
    world = world_with_wall(tick=120)
    memory = distill(world, log_of(wall_built_event(tick=120)))

    assert len(memory) == 1
    fact = memory.facts[0]
    assert fact.fact_type is MemoryFactType.WALL_BUILT
    assert fact.source_id == WALL_ID
    assert fact.tick == 120
    assert fact.source_event_index == 0
    assert fact.details["boundary_id"] == BOUNDARY_ID
    assert fact.details["district_a_id"] == "district_a"
    assert fact.details["district_b_id"] == "district_b"
    assert fact.details["permanent"] is True


def test_several_walls_become_facts_in_event_order() -> None:
    """Event position is provenance, so the log's order is the facts' order."""
    world = build_world(
        tick=40,
        districts=("district_a", "district_b", "district_c"),
        boundaries=(
            ("boundary_ab", "district_a", "district_b"),
            ("boundary_bc", "district_b", "district_c"),
        ),
    )
    world.add_wall(build_wall("wall_ab", "boundary_ab", built_tick=10))
    world.add_wall(build_wall("wall_bc", "boundary_bc", built_tick=20))
    memory = distill(
        world,
        log_of(
            wall_built_event(tick=10, wall_id="wall_ab"),
            wall_built_event(tick=20, wall_id="wall_bc"),
        ),
    )

    assert [fact.details["wall_id"] for fact in memory] == ["wall_ab", "wall_bc"]
    assert [fact.source_event_index for fact in memory] == [0, 1]


def test_the_source_event_payload_is_preserved_exactly() -> None:
    """Unfamiliar payload keys are carried, not dropped or reinterpreted."""
    payload = {"wall_id": WALL_ID, "boundary_pressure": 0.9, "extra": {"nested": [1, 2]}}
    world = world_with_wall(tick=120)
    memory = distill(world, log_of(wall_built_event(tick=120, payload=payload)))

    assert memory.facts[0].details_as_dict()["source_event_payload"] == payload


def test_the_wall_fact_summary_is_exact() -> None:
    """Structured prose, derived from the fact's own content."""
    memory = episode_zero_memory()
    assert memory.facts[0].summary == (
        'Wall "wall_boundary_ab" was built on boundary "boundary_ab" between districts '
        '"district_a" and "district_b" at tick 120; it was marked permanent.'
    )


def test_the_wall_fact_id_is_deterministic() -> None:
    """Two distillations of the same episode agree on the identifier."""
    assert episode_zero_memory().facts[0].fact_id == episode_zero_memory().facts[0].fact_id


def test_an_event_naming_no_wall_is_refused() -> None:
    """A construction with no subject cannot be verified against anything."""
    world = world_with_wall(tick=120)
    event = Event(tick=120, type=EventType.WALL_BUILT, payload={}, source_id=None)
    with pytest.raises(ValueError):
        distill(world, log_of(event))


def test_an_event_naming_an_unknown_wall_is_refused() -> None:
    """The final state must still corroborate the claim."""
    world = build_world(tick=120)
    with pytest.raises(ValueError):
        distill(world, log_of(wall_built_event(tick=120)))


def test_a_wall_whose_build_tick_disagrees_is_refused() -> None:
    """The wall and its event must describe the same moment."""
    world = world_with_wall(tick=120, built_tick=119)
    with pytest.raises(ValueError):
        distill(world, log_of(wall_built_event(tick=120)))


def test_a_non_permanent_wall_is_refused() -> None:
    """Only a permanent wall is remembered; a temporary one is not a scar."""
    world = world_with_wall(tick=120, permanent=False)
    with pytest.raises(ValueError):
        distill(world, log_of(wall_built_event(tick=120)))


def test_a_wall_on_a_missing_boundary_is_refused() -> None:
    """A wall standing nowhere cannot have its endpoints recorded."""
    world = world_with_wall(tick=120)
    world.walls[WALL_ID].boundary_id = "nowhere"
    with pytest.raises(ValueError):
        distill(world, log_of(wall_built_event(tick=120)))


def test_a_broken_wall_boundary_back_reference_is_refused() -> None:
    """References must agree in both directions."""
    world = world_with_wall(tick=120)
    world.boundaries[BOUNDARY_ID].wall_id = None
    with pytest.raises(ValueError):
        distill(world, log_of(wall_built_event(tick=120)))


def test_a_boundary_with_a_missing_district_is_refused() -> None:
    """Endpoints are part of the fact, so they have to resolve."""
    world = world_with_wall(tick=120)
    world.boundaries[BOUNDARY_ID].district_b_id = "nowhere"
    with pytest.raises(ValueError):
        distill(world, log_of(wall_built_event(tick=120)))


def test_a_boundary_joining_a_district_to_itself_is_refused() -> None:
    """The constructor forbids it, but the entity stays mutable afterwards."""
    world = world_with_wall(tick=120)
    world.boundaries[BOUNDARY_ID].district_b_id = "district_a"
    with pytest.raises(ValueError):
        distill(world, log_of(wall_built_event(tick=120)))


def test_a_registry_key_disagreeing_with_its_wall_is_refused() -> None:
    """The key and the entity must be talking about the same thing."""
    world = world_with_wall(tick=120)
    world.walls[WALL_ID].id = "renamed"
    with pytest.raises(ValueError):
        distill(world, log_of(wall_built_event(tick=120)))


def test_the_same_wall_built_twice_in_one_episode_is_refused() -> None:
    """A wall is built once; a repeated claim means the log is wrong."""
    world = world_with_wall(tick=120)
    with pytest.raises(ValueError):
        distill(world, log_of(wall_built_event(tick=120), wall_built_event(tick=120)))


def test_a_wall_already_remembered_as_built_cannot_be_built_again() -> None:
    """Including when the earlier claim came from a previous episode."""
    previous = episode_zero_memory()
    world = world_with_wall(episode=1, tick=300, built_tick=300)
    with pytest.raises(ValueError):
        distill(world, log_of(wall_built_event(tick=300)), previous)


# --- LAW_RESTORED -----------------------------------------------------------


def test_a_restoration_with_no_prior_wall_creates_nothing() -> None:
    """Nothing persisted, so there is nothing to say. Not an error."""
    world = build_world(episode=1, tick=250)
    world.add_law(build_law(changed_episode=1, restored_tick=250))
    memory = distill(
        world,
        log_of(law_restored_event(tick=250)),
        WorldMemory.empty().advance(episode=0, tick=100),
    )
    assert memory.facts == ()
    assert memory.through_episode == 1


def test_a_restoration_with_one_prior_wall_creates_one_fact() -> None:
    """The claim the whole phase exists to produce."""
    previous = episode_zero_memory()
    world = restored_world(
        dependency_score=0.78, transport_dependency=0.78, resource_dependency=0.65
    )
    memory = distill(world, log_of(law_restored_event(tick=250)), previous)

    assert len(memory) == 2
    fact = memory.facts[1]
    assert fact.fact_type is MemoryFactType.LAW_RESTORED_WALL_PERSISTED
    assert fact.source_id == LAW_ID
    assert fact.details["wall_id"] == WALL_ID
    assert fact.details["wall_built_tick"] == 120
    assert fact.details["restored_tick"] == 250
    assert fact.details["wall_dependency_score_at_episode_close"] == 0.78
    assert fact.details["law_previous_value"] is False
    assert fact.details["law_current_value"] is True


def test_several_prior_walls_produce_one_fact_each_sorted_by_wall() -> None:
    """One fact per wall, in a deterministic order independent of registration."""
    world = build_world(
        episode=1,
        tick=250,
        districts=("district_a", "district_b", "district_c"),
        boundaries=(
            ("boundary_ab", "district_a", "district_b"),
            ("boundary_bc", "district_b", "district_c"),
        ),
    )
    world.add_law(build_law(changed_episode=1, restored_tick=250))
    world.add_wall(build_wall("wall_zulu", "boundary_bc", built_tick=20))
    world.add_wall(build_wall("wall_alpha", "boundary_ab", built_tick=10))

    previous = WorldMemory.empty().advance(
        episode=0,
        tick=100,
        new_facts=(
            _built_fact_for("wall_alpha", "boundary_ab", "district_a", "district_b", 10, 0),
            _built_fact_for("wall_zulu", "boundary_bc", "district_b", "district_c", 20, 1),
        ),
    )
    memory = distill(world, log_of(law_restored_event(tick=250)), previous)
    new_facts = [f for f in memory if f.fact_type is MemoryFactType.LAW_RESTORED_WALL_PERSISTED]

    assert [fact.details["wall_id"] for fact in new_facts] == ["wall_alpha", "wall_zulu"]


def _built_fact_for(wall_id, boundary_id, district_a, district_b, tick, index):
    """Build a wall-construction fact for a specific boundary."""
    from memory.conftest import wall_built_fact  # noqa: PLC0415

    return wall_built_fact(
        tick=tick,
        source_event_index=index,
        wall_id=wall_id,
        boundary_id=boundary_id,
        district_a_id=district_a,
        district_b_id=district_b,
    )


def test_a_wall_built_earlier_in_the_same_episode_qualifies() -> None:
    """Provenance may come from this episode's own log."""
    world = build_world(episode=0, tick=250)
    world.add_law(build_law(changed_episode=0, restored_tick=250))
    world.add_wall(build_wall(built_tick=120))
    memory = distill(world, log_of(wall_built_event(tick=120), law_restored_event(tick=250)))

    assert [fact.fact_type for fact in memory] == [
        MemoryFactType.WALL_BUILT,
        MemoryFactType.LAW_RESTORED_WALL_PERSISTED,
    ]


@pytest.mark.parametrize("built_tick", [250, 260])
def test_a_wall_not_already_standing_at_the_restoration_does_not_qualify(
    built_tick: int,
) -> None:
    """The comparison is strict, and the boundary case matters.

    A future rule system publishes restoration first in the tick. A wall raised
    later in that same tick was not standing when the law was restored, so it
    did not persist through it.
    """
    world = build_world(episode=0, tick=300)
    world.add_law(build_law(changed_episode=0, restored_tick=250))
    world.add_wall(build_wall(built_tick=built_tick))
    memory = distill(
        world,
        log_of(law_restored_event(tick=250), wall_built_event(tick=built_tick)),
    )

    assert [fact.fact_type for fact in memory] == [MemoryFactType.WALL_BUILT]


def test_a_wall_built_one_tick_before_the_restoration_qualifies() -> None:
    """The boundary case on the permitted side."""
    previous = episode_zero_memory(tick=249)
    world = restored_world(built_tick=249)
    memory = distill(world, log_of(law_restored_event(tick=250)), previous)
    assert len(memory) == 2


def test_a_restoration_naming_an_unknown_law_is_refused() -> None:
    """The final state must corroborate the restoration."""
    previous = episode_zero_memory()
    world = build_world(episode=1, tick=250)
    world.add_wall(build_wall(built_tick=120))
    with pytest.raises(ValueError):
        distill(world, log_of(law_restored_event(tick=250)), previous)


def test_a_law_whose_restored_tick_disagrees_is_refused() -> None:
    """The law and its event must describe the same moment."""
    previous = episode_zero_memory()
    world = restored_world()
    world.laws[LAW_ID].restored_tick = 249
    with pytest.raises(ValueError):
        distill(world, log_of(law_restored_event(tick=250)), previous)


def test_an_inactive_law_is_refused() -> None:
    """A restored law is in force; anything else contradicts the event."""
    previous = episode_zero_memory()
    world = restored_world()
    world.laws[LAW_ID].active = False
    with pytest.raises(ValueError):
        distill(world, log_of(law_restored_event(tick=250)), previous)


def test_a_law_changed_in_another_episode_is_refused() -> None:
    """A restoration recorded elsewhere is not this episode's restoration."""
    previous = episode_zero_memory()
    world = restored_world()
    world.laws[LAW_ID].changed_episode = 0
    with pytest.raises(ValueError):
        distill(world, log_of(law_restored_event(tick=250)), previous)


def test_a_law_registry_key_disagreeing_with_its_law_is_refused() -> None:
    """The key and the entity must agree."""
    previous = episode_zero_memory()
    world = restored_world()
    world.laws[LAW_ID].id = "renamed"
    with pytest.raises(ValueError):
        distill(world, log_of(law_restored_event(tick=250)), previous)


def test_a_wall_with_no_recorded_provenance_does_not_qualify() -> None:
    """Persistence is claimed only for a wall the memory saw being built."""
    world = restored_world()
    memory = distill(
        world,
        log_of(law_restored_event(tick=250)),
        WorldMemory.empty().advance(episode=0, tick=100),
    )
    assert memory.facts == ()


def test_a_remembered_wall_that_has_vanished_is_refused() -> None:
    """A permanent wall does not leave the world."""
    previous = episode_zero_memory()
    world = build_world(episode=1, tick=250)
    world.add_law(build_law(changed_episode=1, restored_tick=250))
    with pytest.raises(ValueError):
        distill(world, log_of(law_restored_event(tick=250)), previous)


def test_a_remembered_wall_that_lost_its_permanence_is_refused() -> None:
    """The world and the memory would then disagree about what happened."""
    previous = episode_zero_memory()
    world = restored_world(permanent=False)
    with pytest.raises(ValueError):
        distill(world, log_of(law_restored_event(tick=250)), previous)


def test_a_remembered_wall_that_moved_boundary_is_refused() -> None:
    """Provenance must still match the world it describes."""
    previous = episode_zero_memory()
    world = restored_world()
    world.add_boundary(
        Boundary(
            id="boundary_other",
            created_tick=0,
            district_a_id="district_a",
            district_b_id="district_b",
        )
    )
    world.walls[WALL_ID].boundary_id = "boundary_other"
    with pytest.raises(ValueError):
        distill(world, log_of(law_restored_event(tick=250)), previous)


def test_a_remembered_wall_whose_build_tick_changed_is_refused() -> None:
    """When a wall was built is part of what the memory recorded."""
    previous = episode_zero_memory()
    world = restored_world(built_tick=121)
    with pytest.raises(ValueError):
        distill(world, log_of(law_restored_event(tick=250)), previous)


@pytest.mark.parametrize(
    "field", ["dependency_score", "transport_dependency", "resource_dependency"]
)
@pytest.mark.parametrize("bad", [1.5, -0.1, float("nan"), float("inf"), True, "0.5"])
def test_an_invalid_dependency_value_is_refused(field: str, bad: object) -> None:
    """A dependency recorded in a fact must be a real score."""
    previous = episode_zero_memory()
    world = restored_world()
    setattr(world.walls[WALL_ID], field, bad)
    with pytest.raises((TypeError, ValueError)):
        distill(world, log_of(law_restored_event(tick=250)), previous)


def test_an_inactive_wall_still_persisted_and_is_recorded_as_inactive() -> None:
    """Activity is recorded exactly as found and is never read as permanence."""
    previous = episode_zero_memory()
    world = restored_world(active=False)
    memory = distill(world, log_of(law_restored_event(tick=250)), previous)

    fact = memory.facts[1]
    assert fact.details["wall_active_at_episode_close"] is False
    assert fact.details["wall_permanent"] is True


def test_the_restoration_payload_is_preserved_exactly() -> None:
    """Whatever a future rule system publishes is carried as evidence."""
    previous = episode_zero_memory()
    payload = {"law_id": LAW_ID, "restored_from": {"value": False}, "notes": [1, 2]}
    world = restored_world()
    memory = distill(world, log_of(law_restored_event(tick=250, payload=payload)), previous)

    assert memory.facts[1].details_as_dict()["source_event_payload"] == payload


def test_the_persistence_summary_makes_no_causal_claim() -> None:
    """It says two things were true, not that one produced the other."""
    previous = episode_zero_memory()
    world = restored_world()
    summary = distill(world, log_of(law_restored_event(tick=250)), previous).facts[1].summary

    for banned in ("caused", "because of", "therefore", "responsible for", "forced", "led to"):
        assert banned not in summary
    assert "remained in the world" in summary


# --- Episode chronology -----------------------------------------------------


def test_a_decreasing_event_tick_is_refused() -> None:
    """An episode log is chronological."""
    world = build_world(tick=40)
    log = log_of(
        Event(tick=20, type=EventType.SCARCITY_CHANGED, payload={}),
        Event(tick=10, type=EventType.SCARCITY_CHANGED, payload={}),
    )
    with pytest.raises(ValueError):
        distill(world, log)


def test_an_event_after_the_world_tick_is_refused() -> None:
    """History cannot contain something that has not happened yet."""
    world = build_world(tick=10)
    with pytest.raises(ValueError):
        distill(world, log_of(Event(tick=11, type=EventType.SCARCITY_CHANGED, payload={})))


def test_an_event_at_the_world_tick_is_accepted() -> None:
    """The wall built this tick belongs to this tick."""
    world = world_with_wall(tick=120)
    assert len(distill(world, log_of(wall_built_event(tick=120)))) == 1


def test_an_event_inside_an_already_processed_window_is_refused() -> None:
    """A later episode cannot re-report ticks the previous one already covered."""
    previous = WorldMemory.empty().advance(episode=0, tick=100)
    world = build_world(episode=1, tick=250)
    with pytest.raises(ValueError):
        distill(
            world,
            log_of(Event(tick=100, type=EventType.SCARCITY_CHANGED, payload={})),
            previous,
        )


def test_an_episode_gap_is_refused() -> None:
    """Distillation cannot skip an episode."""
    previous = WorldMemory.empty().advance(episode=0, tick=100)
    world = build_world(episode=2, tick=250)
    with pytest.raises(ValueError):
        distill(world, EventLog(), previous)


def test_world_time_moving_backward_is_refused() -> None:
    """Ticks accumulate across episodes."""
    previous = WorldMemory.empty().advance(episode=0, tick=100)
    world = build_world(episode=1, tick=99)
    with pytest.raises(ValueError):
        distill(world, EventLog(), previous)


@pytest.mark.parametrize("bad", [True, 1.0, "0", -1])
def test_a_mistyped_world_episode_or_tick_is_refused(bad: object) -> None:
    """Exact non-negative ints, as everywhere else in the engine."""
    world = build_world(tick=40)
    world._episode = bad
    with pytest.raises((TypeError, ValueError)):
        distill(world, EventLog())


# --- Arguments and mutation -------------------------------------------------


@pytest.mark.parametrize("bad", [None, "world", 0, EventLog()])
def test_a_non_world_argument_is_refused(bad: object) -> None:
    """The aggregate is required, not something shaped like it."""
    with pytest.raises(TypeError):
        MemorySignificance().distill_episode(
            world=bad, event_log=EventLog(), previous_memory=WorldMemory.empty()
        )


@pytest.mark.parametrize("bad", [None, "log", [], 0])
def test_a_non_event_log_argument_is_refused(bad: object) -> None:
    """The real log is required; a list of events is not one."""
    with pytest.raises(TypeError):
        MemorySignificance().distill_episode(
            world=build_world(), event_log=bad, previous_memory=WorldMemory.empty()
        )


@pytest.mark.parametrize("bad", ["memory", 0, [], {"facts": []}])
def test_a_non_memory_previous_argument_is_refused(bad: object) -> None:
    """Only ``None`` is accepted as a spelling of an unprocessed memory."""
    with pytest.raises(TypeError):
        MemorySignificance().distill_episode(
            world=build_world(), event_log=EventLog(), previous_memory=bad
        )


def test_none_is_accepted_as_an_unprocessed_memory() -> None:
    """A convenience for episode zero, and nothing more."""
    memory = MemorySignificance().distill_episode(
        world=build_world(tick=5), event_log=EventLog(), previous_memory=None
    )
    assert memory == WorldMemory.empty().advance(episode=0, tick=5)


def test_distillation_mutates_nothing_it_was_given() -> None:
    """World, log, memory, and generator are all left exactly as they were."""
    previous = episode_zero_memory()
    world = restored_world()
    log = log_of(law_restored_event(tick=250))

    rng_before = world.rng.get_state()
    walls_before = {key: (w.built_tick, w.active, w.permanent) for key, w in world.walls.items()}
    law_before = (world.laws[LAW_ID].active, world.laws[LAW_ID].restored_tick)
    events_before = log.events()
    previous_before = previous

    distill(world, log, previous)

    assert world.rng.get_state() == rng_before
    walls_after = {key: (w.built_tick, w.active, w.permanent) for key, w in world.walls.items()}
    assert walls_after == walls_before
    assert (world.laws[LAW_ID].active, world.laws[LAW_ID].restored_tick) == law_before
    assert log.events() == events_before
    assert previous == previous_before
    assert previous.through_episode == 0


def test_a_failed_distillation_returns_nothing_at_all() -> None:
    """No partial history: an inconsistency aborts the whole episode."""
    previous = episode_zero_memory()
    world = build_world(
        episode=1,
        tick=300,
        districts=("district_a", "district_b", "district_c"),
        boundaries=(
            (BOUNDARY_ID, "district_a", "district_b"),
            ("boundary_bc", "district_b", "district_c"),
        ),
    )
    world.add_law(build_law(changed_episode=1, restored_tick=300))
    world.add_wall(build_wall(built_tick=120))
    world.add_wall(build_wall("wall_broken", "boundary_bc", built_tick=200))
    # Broken after registration: the aggregate refuses to accept it broken, and
    # the point is state that drifted afterwards.
    world.walls["wall_broken"].boundary_id = "nowhere"

    with pytest.raises(ValueError):
        distill(
            world,
            log_of(
                wall_built_event(tick=200, wall_id="wall_broken"),
                law_restored_event(tick=300),
            ),
            previous,
        )
    assert len(previous) == 1, "the previous memory is untouched"
    assert previous.through_episode == 0


def test_distillation_is_deterministic() -> None:
    """Two runs over the same episode agree on every fact and identifier."""
    results = []
    for _ in range(3):
        previous = episode_zero_memory()
        world = restored_world()
        memory = distill(world, log_of(law_restored_event(tick=250)), previous)
        results.append([(f.fact_id, f.summary, f.details_as_dict()) for f in memory])
    assert results[0] == results[1] == results[2]


def test_registry_insertion_order_does_not_change_the_facts() -> None:
    """Which wall was registered first is not part of the world's meaning."""

    def run(reverse: bool):
        """Distil the same world with walls registered in a chosen order."""
        world = build_world(
            episode=0,
            tick=40,
            districts=("district_a", "district_b", "district_c"),
            boundaries=(
                ("boundary_ab", "district_a", "district_b"),
                ("boundary_bc", "district_b", "district_c"),
            ),
        )
        walls = [
            build_wall("wall_ab", "boundary_ab", built_tick=10),
            build_wall("wall_bc", "boundary_bc", built_tick=20),
        ]
        for wall in reversed(walls) if reverse else walls:
            world.add_wall(wall)
        return [
            (f.fact_id, f.details_as_dict())
            for f in distill(
                world,
                log_of(
                    wall_built_event(tick=10, wall_id="wall_ab"),
                    wall_built_event(tick=20, wall_id="wall_bc"),
                ),
            )
        ]

    assert run(False) == run(True)


def test_payload_insertion_order_does_not_change_the_fact_id() -> None:
    """Two payloads holding the same data name the same fact."""

    def run(payload: dict) -> str:
        """Distil an episode whose event carries this payload."""
        world = world_with_wall(tick=120)
        return distill(world, log_of(wall_built_event(tick=120, payload=payload))).facts[0].fact_id

    assert run({"a": 1, "b": {"x": 1, "y": 2}}) == run({"b": {"y": 2, "x": 1}, "a": 1})


# --- hostile __class__ at the distillation boundary --------------------------


class HostileClass:
    """Raises from ``__class__`` instead of answering."""

    @property
    def __class__(self) -> type:
        """Raise instead of revealing a type."""
        raise RuntimeError("boom")


def test_a_hostile_world_is_refused_before_distillation() -> None:
    """The world's true runtime type decides, not its ``__class__`` property."""
    with pytest.raises(TypeError, match="world must be a World, got HostileClass"):
        MemorySignificance().distill_episode(
            world=HostileClass(), event_log=EventLog(), previous_memory=None
        )


def test_a_hostile_event_log_is_refused_before_distillation() -> None:
    """The log's true runtime type decides, not its ``__class__`` property."""
    with pytest.raises(TypeError, match="event_log must be an EventLog, got HostileClass"):
        MemorySignificance().distill_episode(
            world=build_world(tick=40), event_log=HostileClass(), previous_memory=None
        )


def test_a_fake_wall_in_the_typed_registry_is_refused() -> None:
    """Every Wall attribute, none of the validation, and a hostile type."""
    world = world_with_wall(tick=120, built_tick=120)
    real = world.walls[WALL_ID]
    fake = HostileClass()
    for name in (
        "id",
        "boundary_id",
        "built_tick",
        "permanent",
        "active",
        "dependency_score",
        "resource_dependency",
        "transport_dependency",
    ):
        setattr(fake, name, getattr(real, name))
    world._walls[WALL_ID] = fake
    world._entities[WALL_ID] = fake

    with pytest.raises(TypeError, match="must be a Wall, got HostileClass"):
        distill(world, log_of(wall_built_event(tick=120)))


def test_legitimate_domain_subclasses_still_distill() -> None:
    """World, EventLog, and Wall subclasses remain acceptable at the boundary."""

    class ObservantWorld(World):
        """A World subclass that changes nothing."""

    class ScriptableLog(EventLog):
        """An EventLog subclass answering with a fixed history."""

        def events(self) -> tuple[Event, ...]:
            """Return the scripted history."""
            return (wall_built_event(tick=120),)

    class SturdyWall(Wall):
        """A Wall subclass that changes nothing."""

    world = ObservantWorld(rng=consumed_rng(), tick=120, episode=0)
    for district_id in ("district_a", "district_b"):
        world.add_district(build_district(district_id))
    world.add_boundary(
        Boundary(
            id=BOUNDARY_ID, created_tick=0, district_a_id="district_a", district_b_id="district_b"
        )
    )
    world.add_wall(
        SturdyWall(
            id=WALL_ID,
            created_tick=120,
            boundary_id=BOUNDARY_ID,
            built_tick=120,
            integrity=1.0,
            active=True,
            permanent=True,
            dependency_score=0.0,
            transport_dependency=0.0,
            resource_dependency=0.0,
        )
    )

    memory = distill(world, ScriptableLog())
    assert [fact.fact_type for fact in memory] == [MemoryFactType.WALL_BUILT]
