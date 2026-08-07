"""Tests for memory lineage: what a later episode may and may not do to history.

World-state lineage proves an episode descends from its parent's *state*. It
says nothing about the parent's *history* — so without these rules a child could
drop every inherited fact, quietly rewrite one, or invent a fact no event
supports, and every hash and lineage check would still pass.

The rule is exact: a child's memory must begin with its parent's facts, in
order, unchanged, and may then append only what its own events require.
"""

import pytest

from living_diorama.events import Event, EventLog, EventType
from living_diorama.memory import MemoryFactType, MemorySignificance, WorldMemory
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
    wall_persisted_fact,
    world_with_wall,
)


def episode_zero() -> tuple[object, EventLog, WorldMemory]:
    """Return an episode zero in which one wall was genuinely built."""
    world = world_with_wall(tick=120)
    log = log_of(wall_built_event(tick=120))
    memory = MemorySignificance().distill_episode(
        world=world, event_log=log, previous_memory=WorldMemory.empty()
    )
    return world, log, memory


def quiet_episode_one() -> object:
    """Return an episode one world in which nothing happened."""
    return world_with_wall(episode=1, tick=250, built_tick=120)


def check(previous, current, world, event_log) -> None:
    """Run the transition validator with the usual keyword shape."""
    validate_memory_transition(
        previous_memory=previous, current_memory=current, world=world, event_log=event_log
    )


# --- Parent-prefix integrity ------------------------------------------------


def test_a_quiet_child_carrying_the_parent_history_unchanged_is_accepted() -> None:
    """The control case: nothing happened, and nothing was forgotten."""
    _, _, parent = episode_zero()
    world = quiet_episode_one()
    check(parent, parent.advance(episode=1, tick=250), world, EventLog())


def test_a_child_that_drops_every_parent_fact_is_refused() -> None:
    """Forgetting the whole inherited history is the starkest form of the defect."""
    _, _, parent = episode_zero()
    world = quiet_episode_one()
    forgetful = WorldMemory((), through_episode=1, through_tick=250)

    with pytest.raises(ValueError):
        check(parent, forgetful, world, EventLog())


def test_a_child_that_drops_one_parent_fact_is_refused() -> None:
    """Losing part of the history is no more acceptable than losing all of it."""
    world = build_world(
        episode=0,
        tick=300,
        districts=("district_a", "district_b", "district_c"),
        boundaries=(
            ("boundary_ab", "district_a", "district_b"),
            ("boundary_bc", "district_b", "district_c"),
        ),
    )
    world.add_wall(build_wall("wall_ab", "boundary_ab", built_tick=10))
    world.add_wall(build_wall("wall_bc", "boundary_bc", built_tick=20))
    log = log_of(
        wall_built_event(tick=10, wall_id="wall_ab"),
        wall_built_event(tick=20, wall_id="wall_bc"),
    )
    parent = MemorySignificance().distill_episode(
        world=world, event_log=log, previous_memory=WorldMemory.empty()
    )
    assert len(parent) == 2

    child_world = build_world(
        episode=1,
        tick=400,
        districts=("district_a", "district_b", "district_c"),
        boundaries=(
            ("boundary_ab", "district_a", "district_b"),
            ("boundary_bc", "district_b", "district_c"),
        ),
    )
    child_world.add_wall(build_wall("wall_ab", "boundary_ab", built_tick=10))
    child_world.add_wall(build_wall("wall_bc", "boundary_bc", built_tick=20))
    truncated = WorldMemory(parent.facts[:1], through_episode=1, through_tick=400)

    with pytest.raises(ValueError):
        check(parent, truncated, child_world, EventLog())


def test_a_child_that_rewrites_parent_details_is_refused() -> None:
    """An inherited fact is not editable, even into something plausible."""
    _, _, parent = episode_zero()
    world = quiet_episode_one()
    rewritten = WorldMemory(
        (wall_built_fact(tick=120, payload={"wall_id": WALL_ID, "injected": True}),),
        through_episode=1,
        through_tick=250,
    )

    with pytest.raises(ValueError):
        check(parent, rewritten, world, EventLog())


def test_a_child_that_reorders_parent_facts_is_refused() -> None:
    """Order is part of what the history says happened first."""
    world = build_world(
        episode=0,
        tick=300,
        districts=("district_a", "district_b", "district_c"),
        boundaries=(
            ("boundary_ab", "district_a", "district_b"),
            ("boundary_bc", "district_b", "district_c"),
        ),
    )
    world.add_wall(build_wall("wall_ab", "boundary_ab", built_tick=10))
    world.add_wall(build_wall("wall_bc", "boundary_bc", built_tick=20))
    parent = MemorySignificance().distill_episode(
        world=world,
        event_log=log_of(
            wall_built_event(tick=10, wall_id="wall_ab"),
            wall_built_event(tick=20, wall_id="wall_bc"),
        ),
        previous_memory=WorldMemory.empty(),
    )

    with pytest.raises(ValueError):
        WorldMemory(tuple(reversed(parent.facts)), through_episode=1, through_tick=400)


def test_a_child_that_inserts_a_fact_inside_the_inherited_prefix_is_refused() -> None:
    """New facts go after the inherited history, never among it."""
    _, _, parent = episode_zero()
    world = world_with_wall(episode=1, tick=250, built_tick=120)
    world.add_law(build_law(changed_episode=1, restored_tick=250))
    log = log_of(law_restored_event(tick=250))
    valid = MemorySignificance().distill_episode(world=world, event_log=log, previous_memory=parent)
    assert len(valid) == 2

    # The same two facts, with the new one placed first.
    with pytest.raises(ValueError):
        WorldMemory((valid.facts[1], valid.facts[0]), through_episode=1, through_tick=250)


def test_a_valid_prefix_plus_suffix_is_accepted() -> None:
    """The ordinary case: inherit everything, append what this episode produced."""
    _, _, parent = episode_zero()
    world = world_with_wall(episode=1, tick=250, built_tick=120)
    world.add_law(build_law(changed_episode=1, restored_tick=250))
    log = log_of(law_restored_event(tick=250))
    child = MemorySignificance().distill_episode(world=world, event_log=log, previous_memory=parent)

    check(parent, child, world, log)
    assert child.facts[: len(parent)] == parent.facts
    assert child.facts[len(parent)].fact_type is MemoryFactType.LAW_RESTORED_WALL_PERSISTED


def test_episode_zero_must_begin_from_an_unprocessed_memory() -> None:
    """A world's history starts where the world does."""
    world, log, memory = episode_zero()
    with pytest.raises(ValueError):
        check(memory, memory, world, log)


def test_a_child_must_continue_from_the_immediately_previous_episode() -> None:
    """A memory from two episodes back is not this episode's parent."""
    _, _, parent = episode_zero()
    world = world_with_wall(episode=2, tick=400, built_tick=120)
    child = parent.advance(episode=1, tick=250).advance(episode=2, tick=400)

    with pytest.raises(ValueError):
        check(parent, child, world, EventLog())


@pytest.mark.parametrize("episode,tick", [(0, 250), (1, 249), (2, 250)])
def test_a_checkpoint_disagreeing_with_the_world_is_refused(episode: int, tick: int) -> None:
    """The memory and the world must describe the same moment."""
    _, _, parent = episode_zero()
    world = quiet_episode_one()
    child = WorldMemory(parent.facts, through_episode=episode, through_tick=tick)

    with pytest.raises(ValueError):
        check(parent, child, world, EventLog())


# --- Current-episode event coverage -----------------------------------------


def test_a_wall_built_event_with_no_fact_is_refused() -> None:
    """An episode that raised a wall must remember having raised it."""
    world, log, _ = episode_zero()
    with pytest.raises(ValueError):
        check(None, WorldMemory((), through_episode=0, through_tick=120), world, log)


def test_a_wall_built_event_with_two_facts_is_refused() -> None:
    """A wall is built once, so one event produces one fact."""
    _, _, memory = episode_zero()
    with pytest.raises(ValueError):
        WorldMemory((memory.facts[0], memory.facts[0]), through_episode=0, through_tick=120)


def test_a_fact_citing_the_wrong_event_index_is_refused() -> None:
    """Provenance is by position; the bus may publish equal events twice."""
    world = world_with_wall(tick=120)
    log = log_of(
        Event(tick=5, type=EventType.SCARCITY_CHANGED, payload={}),
        wall_built_event(tick=120),
    )
    wrong = WorldMemory(
        (wall_built_fact(tick=120, source_event_index=0),),
        through_episode=0,
        through_tick=120,
    )
    with pytest.raises(ValueError):
        check(None, wrong, world, log)


def test_a_fact_citing_an_index_beyond_the_log_is_refused() -> None:
    """A fact cannot come from an event that is not there."""
    world, log, _ = episode_zero()
    beyond = WorldMemory(
        (wall_built_fact(tick=120, source_event_index=99),),
        through_episode=0,
        through_tick=120,
    )
    with pytest.raises(ValueError):
        check(None, beyond, world, log)


def test_a_fact_resolving_to_a_non_significant_event_is_refused() -> None:
    """A scarcity change does not produce durable history."""
    world = world_with_wall(tick=120)
    log = log_of(Event(tick=120, type=EventType.SCARCITY_CHANGED, payload={}))
    wrong = WorldMemory(
        (wall_built_fact(tick=120, source_event_index=0),),
        through_episode=0,
        through_tick=120,
    )
    with pytest.raises(ValueError):
        check(None, wrong, world, log)


def test_a_fact_disagreeing_with_its_event_tick_is_refused() -> None:
    """The fact records the moment its event happened."""
    world = world_with_wall(tick=200, built_tick=119)
    log = log_of(wall_built_event(tick=119))
    wrong = WorldMemory(
        (wall_built_fact(tick=120, source_event_index=0),),
        through_episode=0,
        through_tick=200,
    )
    with pytest.raises(ValueError):
        check(None, wrong, world, log)


def test_a_fact_naming_a_different_entity_than_its_event_is_refused() -> None:
    """The fact's subject is the event's subject."""
    world = world_with_wall(tick=120)
    log = log_of(wall_built_event(tick=120, wall_id="wall_other"))
    wrong = WorldMemory(
        (wall_built_fact(tick=120, source_event_index=0),),
        through_episode=0,
        through_tick=120,
    )
    with pytest.raises(ValueError):
        check(None, wrong, world, log)


def test_a_fact_carrying_a_false_source_payload_is_refused() -> None:
    """The recorded payload is evidence, so it must be what was published."""
    world = world_with_wall(tick=120)
    log = log_of(wall_built_event(tick=120, payload={"wall_id": WALL_ID, "real": 1}))
    forged = WorldMemory(
        (wall_built_fact(tick=120, payload={"wall_id": WALL_ID, "forged": True}),),
        through_episode=0,
        through_tick=120,
    )
    with pytest.raises(ValueError):
        check(None, forged, world, log)


def test_an_extra_unsupported_fact_is_refused() -> None:
    """Nothing may be remembered that no event produced."""
    world = world_with_wall(episode=1, tick=250, built_tick=120)
    world.add_law(build_law(changed_episode=1, restored_tick=250))
    _, _, parent = episode_zero()
    invented = parent.advance(
        episode=1, tick=250, new_facts=(wall_persisted_fact(episode=1, tick=250),)
    )
    with pytest.raises(ValueError):
        check(parent, invented, world, EventLog())


def test_a_non_significant_event_requires_no_fact() -> None:
    """The checkpoint still advances, and nothing is remembered."""
    world = build_world(tick=40)
    log = log_of(Event(tick=10, type=EventType.SCARCITY_CHANGED, payload={}))
    check(None, WorldMemory((), through_episode=0, through_tick=40), world, log)


# --- Cross-fact provenance --------------------------------------------------


def test_a_persistence_fact_without_a_build_fact_is_refused() -> None:
    """A wall cannot have survived a restoration it was never built before."""
    with pytest.raises(ValueError):
        WorldMemory(
            (wall_persisted_fact(episode=0, tick=250, wall_built_tick=120),),
            through_episode=0,
            through_tick=250,
        )


def test_a_persistence_fact_pointing_at_another_walls_build_is_refused() -> None:
    """The two facts must agree about which boundary the wall stands on."""
    build = wall_built_fact(tick=10, wall_id="wall_one", boundary_id="boundary_one")
    persisted = wall_persisted_fact(
        episode=0,
        tick=250,
        wall_id="wall_one",
        boundary_id="boundary_other",
        wall_built_tick=10,
    )
    with pytest.raises(ValueError):
        WorldMemory((build, persisted), through_episode=0, through_tick=250)


def test_a_persistence_fact_disagreeing_about_the_build_tick_is_refused() -> None:
    """When the wall was built is part of what both facts record."""
    build = wall_built_fact(tick=10)
    persisted = wall_persisted_fact(episode=0, tick=250, wall_built_tick=11)
    with pytest.raises(ValueError):
        WorldMemory((build, persisted), through_episode=0, through_tick=250)


def test_a_build_fact_after_the_restoration_it_supports_is_refused() -> None:
    """A wall built later cannot have persisted through an earlier restoration.

    Refused twice over. A fact claiming its wall was built at or after the
    restoration is rejected on construction, and a memory pairing a persistence
    fact with a construction recorded at a different tick is rejected as well --
    which is the only shape the first check leaves reachable.
    """
    with pytest.raises(ValueError):
        wall_persisted_fact(episode=0, tick=250, wall_built_tick=300)

    build = wall_built_fact(tick=300)
    persisted = wall_persisted_fact(episode=0, tick=400, wall_built_tick=249)
    with pytest.raises(ValueError):
        WorldMemory((build, persisted), through_episode=0, through_tick=400)


def test_provenance_from_the_previous_episode_is_accepted() -> None:
    """The build fact may be inherited rather than made this episode."""
    _, _, parent = episode_zero()
    world = world_with_wall(episode=1, tick=250, built_tick=120)
    world.add_law(build_law(changed_episode=1, restored_tick=250))
    log = log_of(law_restored_event(tick=250))
    child = MemorySignificance().distill_episode(world=world, event_log=log, previous_memory=parent)
    check(parent, child, world, log)
    assert len(child) == 2


def test_provenance_from_earlier_in_the_same_episode_is_accepted() -> None:
    """Or made moments earlier, in this episode's own log."""
    world = build_world(episode=0, tick=250)
    world.add_law(build_law(changed_episode=0, restored_tick=250))
    world.add_wall(build_wall(built_tick=120))
    log = log_of(wall_built_event(tick=120), law_restored_event(tick=250))
    memory = MemorySignificance().distill_episode(
        world=world, event_log=log, previous_memory=WorldMemory.empty()
    )
    check(None, memory, world, log)
    assert [fact.fact_type for fact in memory] == [
        MemoryFactType.WALL_BUILT,
        MemoryFactType.LAW_RESTORED_WALL_PERSISTED,
    ]


# --- Quiet-episode historical topology --------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda world: world._walls.pop(WALL_ID),
        lambda world: world._boundaries.pop(BOUNDARY_ID),
        lambda world: setattr(world.boundaries[BOUNDARY_ID], "wall_id", None),
        lambda world: setattr(world.walls[WALL_ID], "boundary_id", "nowhere"),
        lambda world: world._districts.pop("district_a"),
        lambda world: world._districts.pop("district_b"),
        lambda world: setattr(world.boundaries[BOUNDARY_ID], "district_b_id", "district_a"),
        lambda world: setattr(world.walls[WALL_ID], "permanent", False),
        lambda world: setattr(world.walls[WALL_ID], "built_tick", 121),
        lambda world: setattr(world.walls[WALL_ID], "id", "renamed"),
        lambda world: setattr(world.boundaries[BOUNDARY_ID], "id", "renamed"),
    ],
)
def test_a_quiet_episode_still_validates_remembered_walls(mutate) -> None:
    """A quiet episode does not suspend history.

    Nothing happened, so nothing new is remembered -- but a permanent wall that
    has quietly vanished or lost its boundary means the world and the memory
    disagree, and saving on top of that would make the disagreement permanent.
    """
    _, _, parent = episode_zero()
    world = quiet_episode_one()
    mutate(world)

    with pytest.raises((TypeError, ValueError)):
        check(parent, parent.advance(episode=1, tick=250), world, EventLog())


def test_a_second_wall_claiming_the_remembered_boundary_is_refused() -> None:
    """At most one wall may stand on a boundary."""
    _, _, parent = episode_zero()
    world = quiet_episode_one()
    intruder = build_wall("wall_intruder", BOUNDARY_ID, built_tick=200)
    world._walls["wall_intruder"] = intruder
    world._entities["wall_intruder"] = intruder

    with pytest.raises(ValueError):
        check(parent, parent.advance(episode=1, tick=250), world, EventLog())


# --- Exact law state --------------------------------------------------------


def restoration_world(**law_overrides):
    """Return an episode-one world whose law was restored at tick 250."""
    world = world_with_wall(episode=1, tick=250, built_tick=120)
    world.add_law(build_law(changed_episode=1, restored_tick=250))
    for field, value in law_overrides.items():
        setattr(world.laws[LAW_ID], field, value)
    return world


@pytest.mark.parametrize(
    "field,value",
    [
        ("active", 1),
        ("active", "true"),
        ("changed_episode", True),
        ("changed_episode", 1.0),
        ("changed_episode", "1"),
        ("restored_tick", True),
        ("restored_tick", 1.0),
        ("restored_tick", "250"),
        ("restored_tick", None),
        ("name", "  "),
        ("previous_value", [1, 2]),
        ("current_value", float("nan")),
    ],
)
def test_a_law_field_of_the_wrong_exact_type_is_refused(field: str, value: object) -> None:
    """``True == 1``, so equality alone would accept a bool as an episode or tick."""
    _, _, parent = episode_zero()
    world = restoration_world(**{field: value})

    with pytest.raises((TypeError, ValueError)):
        MemorySignificance().distill_episode(
            world=world,
            event_log=log_of(law_restored_event(tick=250)),
            previous_memory=parent,
        )


def test_a_correctly_restored_law_is_accepted() -> None:
    """The control case for the exact-type checks above."""
    _, _, parent = episode_zero()
    world = restoration_world()
    memory = MemorySignificance().distill_episode(
        world=world, event_log=log_of(law_restored_event(tick=250)), previous_memory=parent
    )
    assert len(memory) == 2


# --- Argument validation ----------------------------------------------------


@pytest.mark.parametrize("bad", [None, "world", 0])
def test_a_non_world_argument_is_refused(bad: object) -> None:
    """The aggregate is required, not something shaped like it."""
    with pytest.raises(TypeError):
        check(None, WorldMemory.empty(), bad, EventLog())


@pytest.mark.parametrize("bad", [None, "log", []])
def test_a_non_event_log_argument_is_refused(bad: object) -> None:
    """The real log is required."""
    with pytest.raises(TypeError):
        check(None, WorldMemory((), through_episode=0, through_tick=0), build_world(tick=0), bad)


@pytest.mark.parametrize("bad", ["memory", 0, {"facts": []}])
def test_a_non_memory_argument_is_refused(bad: object) -> None:
    """Both memories must be the domain object."""
    world = build_world(tick=0)
    with pytest.raises(TypeError):
        check(None, bad, world, EventLog())
    with pytest.raises(TypeError):
        check(bad, WorldMemory((), through_episode=0, through_tick=0), world, EventLog())


def test_validation_mutates_nothing() -> None:
    """A check is a read: world, log, and both memories are left as they were."""
    _, _, parent = episode_zero()
    world = quiet_episode_one()
    log = EventLog()
    child = parent.advance(episode=1, tick=250)

    rng_before = world.rng.get_state()
    parent_before = (parent.facts, parent.through_episode, parent.through_tick)
    child_before = (child.facts, child.through_episode, child.through_tick)

    check(parent, child, world, log)

    assert world.rng.get_state() == rng_before
    assert (parent.facts, parent.through_episode, parent.through_tick) == parent_before
    assert (child.facts, child.through_episode, child.through_tick) == child_before
    assert log.events() == ()


# --- Multi-wall canonical ordering ------------------------------------------
#
# Every canonical sort field before ``fact_id`` is equal for facts produced by
# one restoration event, so the tie falls to a SHA-256 digest. A digest has no
# reason to agree with an alphabetical list of wall identifiers, and Candidate V1
# assumed it would.


def find_inverted_wall_pair() -> tuple[str, str]:
    """Return two wall ids whose lexical order is the reverse of their fact order.

    Found rather than hard-coded, so the property is proven for the identifiers
    actually used instead of assumed from a lucky pair.
    """
    for first in range(40):
        for second in range(first + 1, 40):
            left, right = f"wall_{first:02d}", f"wall_{second:02d}"
            left_fact = wall_persisted_fact(
                episode=0, tick=250, wall_id=left, boundary_id=f"boundary_{first:02d}"
            )
            right_fact = wall_persisted_fact(
                episode=0, tick=250, wall_id=right, boundary_id=f"boundary_{second:02d}"
            )
            if left_fact.fact_id > right_fact.fact_id:
                return left, right
    raise AssertionError("no inverted pair found; widen the search")


def two_wall_restoration(*, reverse_registration: bool = False):
    """Build an episode restoring a law with two prior walls still standing."""
    left, right = find_inverted_wall_pair()
    world = build_world(
        episode=0,
        tick=250,
        districts=("district_a", "district_b", "district_c"),
        boundaries=(
            (f"boundary_{left}", "district_a", "district_b"),
            (f"boundary_{right}", "district_b", "district_c"),
        ),
    )
    world.add_law(build_law(changed_episode=0, restored_tick=250))
    walls = [
        build_wall(left, f"boundary_{left}", built_tick=10),
        build_wall(right, f"boundary_{right}", built_tick=20),
    ]
    for wall in reversed(walls) if reverse_registration else walls:
        world.add_wall(wall)
    log = log_of(
        wall_built_event(tick=10, wall_id=left),
        wall_built_event(tick=20, wall_id=right),
        law_restored_event(tick=250),
    )
    return world, log, left, right


def test_the_chosen_wall_pair_really_inverts_the_two_orders() -> None:
    """Guards the fixture: without inversion the test below proves nothing."""
    left, right = find_inverted_wall_pair()
    assert left < right
    left_fact = wall_persisted_fact(
        episode=0, tick=250, wall_id=left, boundary_id=f"boundary_{left}"
    )
    right_fact = wall_persisted_fact(
        episode=0, tick=250, wall_id=right, boundary_id=f"boundary_{right}"
    )
    assert left_fact.fact_id > right_fact.fact_id


def test_two_walls_persisting_through_one_restoration_are_ordered_canonically() -> None:
    """Distillation succeeds, and the facts come back in canonical order."""
    world, log, left, right = two_wall_restoration()
    memory = MemorySignificance().distill_episode(
        world=world, event_log=log, previous_memory=WorldMemory.empty()
    )

    assert len(memory) == 4
    persistence = [
        fact for fact in memory if fact.fact_type is MemoryFactType.LAW_RESTORED_WALL_PERSISTED
    ]
    assert len(persistence) == 2
    assert {str(fact.details["wall_id"]) for fact in persistence} == {left, right}

    keys = [fact.sort_key() for fact in memory]
    assert keys == sorted(keys), "the whole memory is in canonical order"
    assert [fact.fact_id for fact in persistence] == sorted(fact.fact_id for fact in persistence)


def test_the_multi_wall_result_is_stable_and_order_independent() -> None:
    """Repeating it, and registering the walls the other way, changes nothing."""

    def run(reverse: bool) -> list[tuple[str, str]]:
        """Distil the two-wall episode under a chosen registration order."""
        world, log, _, _ = two_wall_restoration(reverse_registration=reverse)
        memory = MemorySignificance().distill_episode(
            world=world, event_log=log, previous_memory=WorldMemory.empty()
        )
        return [(fact.fact_id, fact.summary) for fact in memory]

    assert run(False) == run(False)
    assert run(False) == run(True)


# --- Hash semantics ---------------------------------------------------------


def test_a_fact_is_hashable_by_its_derived_identifier() -> None:
    """Chosen contract: hashable.

    The generated implementation could not be used -- it would traverse the
    read-only mappings inside ``details`` and fail the moment a caller put a fact
    in a set.
    """
    first = wall_built_fact()
    second = wall_built_fact()

    assert first == second
    assert hash(first) == hash(second)
    assert hash(first) == hash(first.fact_id)
    assert len({first, second}) == 1
    assert {first: "value"}[second] == "value"


def test_a_different_fact_hashes_differently() -> None:
    """Distinct content, distinct identifier, distinct hash."""
    assert hash(wall_built_fact()) != hash(wall_built_fact(tick=121))


def test_a_memory_is_hashable_by_checkpoint_and_fact_identifiers() -> None:
    """Equal memories hash equally, as ``__eq__`` requires."""
    fact = wall_built_fact()
    left = WorldMemory((fact,), through_episode=0, through_tick=120)
    right = WorldMemory((fact,), through_episode=0, through_tick=120)
    other = WorldMemory((fact,), through_episode=0, through_tick=121)

    assert left == right
    assert hash(left) == hash(right)
    assert hash(left) != hash(other)
    assert len({left, right}) == 1
    assert len({left, other}) == 2


def test_an_empty_memory_is_hashable() -> None:
    """Including the state a world starts in."""
    assert hash(WorldMemory.empty()) == hash(WorldMemory.empty())


# --- World time never moves backward -----------------------------------------
#
# ``WorldMemory.advance`` already refused a rollback, so distillation was safe.
# The transition validator did not, and that is the path persistence uses -- so a
# quiet episode, which appends nothing for ``advance`` to inspect, could roll the
# world's clock back through a save whose every byte, hash, and state-lineage
# edge was correct.


def rollback_worlds(child_tick: int):
    """Return a parent memory at tick 100 and a child world at the given tick."""
    parent = WorldMemory((), through_episode=0, through_tick=100)
    world = build_world(episode=1, tick=child_tick)
    child = WorldMemory((), through_episode=1, through_tick=child_tick)
    return parent, world, child


@pytest.mark.parametrize("child_tick", [0, 1, 50, 99])
def test_a_child_episode_closing_earlier_than_its_parent_is_refused(child_tick: int) -> None:
    """World time accumulates across episodes; it never runs back."""
    parent, world, child = rollback_worlds(child_tick)
    with pytest.raises(ValueError):
        check(parent, child, world, EventLog())


@pytest.mark.parametrize("child_tick", [100, 101, 500])
def test_a_child_episode_closing_at_or_after_its_parent_is_accepted(child_tick: int) -> None:
    """Equal is allowed: an episode may advance no ticks at all."""
    parent, world, child = rollback_worlds(child_tick)
    check(parent, child, world, EventLog())


def test_a_rollback_is_refused_even_when_the_child_inherits_facts() -> None:
    """The prefix being intact does not excuse the clock running backwards.

    The inherited fact sits at tick 120, comfortably inside the child's window,
    so the only thing wrong with this transition is that episode two closes
    earlier than episode one did.
    """
    _, _, built = episode_zero()
    parent = built.advance(episode=1, tick=300)
    world = world_with_wall(episode=2, tick=200, built_tick=120)
    child = WorldMemory(parent.facts, through_episode=2, through_tick=200)

    assert child.facts[0].tick == 120, "the inherited fact is inside the child's window"
    with pytest.raises(ValueError):
        check(parent, child, world, EventLog())


def test_distillation_refuses_a_rollback_too() -> None:
    """The two paths agree, as they must."""
    parent = WorldMemory((), through_episode=0, through_tick=100)
    with pytest.raises(ValueError):
        MemorySignificance().distill_episode(
            world=build_world(episode=1, tick=99),
            event_log=EventLog(),
            previous_memory=parent,
        )


# --- Exact identifier types --------------------------------------------------
#
# A ``str`` subclass hashes and compares like the string it copies, so a registry
# lookup finds it and an equality check accepts it. Both would then travel into a
# fact and into a save as something that is not the ``str`` the engine's
# stored-state contract requires.


class StringSubclass(str):
    """A ``str`` subclass: equal to a plain string, and not one."""


def test_the_subclass_really_is_indistinguishable_by_comparison() -> None:
    """Guards the technique, so the tests below prove what they claim."""
    plain, subclass = WALL_ID, StringSubclass(WALL_ID)

    assert plain == subclass
    assert hash(plain) == hash(subclass)
    assert {plain: 1}[subclass] == 1
    assert type(subclass) is not str


def remembered_world(mutate) -> object:
    """Return a quiet episode-one world with one mutation applied."""
    world = world_with_wall(episode=1, tick=250, built_tick=120)
    mutate(world)
    return world


@pytest.mark.parametrize(
    "mutate",
    [
        lambda world: setattr(world.walls[WALL_ID], "id", StringSubclass(WALL_ID)),
        lambda world: setattr(world.boundaries[BOUNDARY_ID], "id", StringSubclass(BOUNDARY_ID)),
        lambda world: setattr(world.boundaries[BOUNDARY_ID], "wall_id", StringSubclass(WALL_ID)),
        lambda world: setattr(world.walls[WALL_ID], "boundary_id", StringSubclass(BOUNDARY_ID)),
        lambda world: setattr(
            world.boundaries[BOUNDARY_ID], "district_a_id", StringSubclass("district_a")
        ),
        lambda world: setattr(
            world.boundaries[BOUNDARY_ID], "district_b_id", StringSubclass("district_b")
        ),
        lambda world: setattr(world.districts["district_a"], "id", StringSubclass("district_a")),
        lambda world: world._walls.__setitem__(StringSubclass(WALL_ID), world._walls.pop(WALL_ID)),
        lambda world: world._boundaries.__setitem__(
            StringSubclass(BOUNDARY_ID), world._boundaries.pop(BOUNDARY_ID)
        ),
        lambda world: world._districts.__setitem__(
            StringSubclass("district_a"), world._districts.pop("district_a")
        ),
        lambda world: world._entities.__setitem__(
            StringSubclass(WALL_ID), world._entities.pop(WALL_ID)
        ),
    ],
)
def test_a_string_subclass_identifier_is_refused(mutate) -> None:
    """Every identifier a fact depends on is checked as itself, not by equality."""
    _, _, parent = episode_zero()
    with pytest.raises(TypeError):
        check(parent, parent.advance(episode=1, tick=250), remembered_world(mutate), EventLog())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda world: setattr(world.laws[LAW_ID], "id", StringSubclass(LAW_ID)),
        lambda world: world._laws.__setitem__(StringSubclass(LAW_ID), world._laws.pop(LAW_ID)),
    ],
)
def test_a_string_subclass_law_identifier_is_refused(mutate) -> None:
    """A restoration is only believed when its law resolves exactly."""
    _, _, parent = episode_zero()
    world = world_with_wall(episode=1, tick=250, built_tick=120)
    world.add_law(build_law(changed_episode=1, restored_tick=250))
    mutate(world)

    with pytest.raises(TypeError):
        MemorySignificance().distill_episode(
            world=world,
            event_log=log_of(law_restored_event(tick=250)),
            previous_memory=parent,
        )


def test_an_entity_missing_from_the_aggregate_index_is_refused() -> None:
    """A fact must not depend on an entity the world's two views disagree about."""
    _, _, parent = episode_zero()
    world = remembered_world(lambda world: world._entities.pop(WALL_ID))

    with pytest.raises(ValueError):
        check(parent, parent.advance(episode=1, tick=250), world, EventLog())


def test_an_aggregate_index_resolving_elsewhere_is_refused() -> None:
    """The index entry must be the very object the registry holds."""
    _, _, parent = episode_zero()
    world = remembered_world(
        lambda world: world._entities.__setitem__(WALL_ID, world._districts["district_a"])
    )

    with pytest.raises(ValueError):
        check(parent, parent.advance(episode=1, tick=250), world, EventLog())


def test_a_healthy_world_of_plain_strings_is_accepted() -> None:
    """The control case for every exactness check above."""
    _, _, parent = episode_zero()
    world = world_with_wall(episode=1, tick=250, built_tick=120)
    check(parent, parent.advance(episode=1, tick=250), world, EventLog())
