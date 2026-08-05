"""The shared topology helper must agree with ResourceFlowSystem exactly.

Migration and resource flow both have to answer "can anything cross here?", and
they must answer identically: a wall that stops food cannot let people through.
Rather than have one system reach into the other -- which the architecture
forbids -- the rule is stated once in a shared private helper, and this test
holds the two implementations to the same answer on randomly built worlds so
they cannot drift apart unnoticed.
"""

import itertools
import random

import pytest
from systems_builders import build_district, build_wall, build_world

from living_diorama.entities import Boundary
from living_diorama.systems._topology import boundary_between, eligible_graph
from living_diorama.systems.resource_flow_system import ResourceFlowSystem


def build_random_world(rng: random.Random):
    """Build a small world with random boundaries, duplicates, and walls."""
    names = [f"d{index}" for index in range(rng.randint(2, 5))]
    world = build_world([build_district(name) for name in names], tick=1)

    counter = 0
    for first, second in itertools.combinations(names, 2):
        for _ in range(rng.randint(0, 2)):
            counter += 1
            boundary_id = f"b{counter:03d}"
            world.add_boundary(
                Boundary(
                    id=boundary_id,
                    created_tick=0,
                    district_a_id=first,
                    district_b_id=second,
                )
            )
            if rng.random() < 0.4:
                world.add_wall(
                    build_wall(f"w{counter:03d}", boundary_id, active=rng.random() < 0.6)
                )
    return world


def test_shared_helper_matches_resource_flow_on_random_worlds() -> None:
    """Both graphs must be identical, edge for edge and boundary for boundary."""
    rng = random.Random(20260805)

    for _ in range(150):
        world = build_random_world(rng)
        mine = eligible_graph(world)
        theirs = ResourceFlowSystem._eligible_graph(world)
        assert mine == theirs


def test_shared_helper_matches_on_a_fully_walled_world() -> None:
    """Where every boundary is sealed, both agree there is no graph at all."""
    world = build_world(
        [build_district("a"), build_district("b")],
        boundaries=[("bound", "a", "b")],
        tick=1,
    )
    world.add_wall(build_wall("wall", "bound", active=True))

    assert eligible_graph(world) == ResourceFlowSystem._eligible_graph(world)
    assert eligible_graph(world)[0] == {}


def test_duplicate_boundaries_resolve_to_the_smallest_identifier() -> None:
    """One connection, one name, chosen the same way flow chooses it."""
    world = build_world(
        [build_district("a"), build_district("b")],
        boundaries=[("zzz", "a", "b"), ("aaa", "a", "b")],
        tick=1,
    )
    _adjacency, pairs = eligible_graph(world)

    assert boundary_between(pairs, "a", "b") == "aaa"
    assert boundary_between(pairs, "b", "a") == "aaa"


def test_migration_and_resource_flow_read_the_same_law_the_same_way() -> None:
    """Both systems gate on ``movement_resource_sharing`` with identical rules.

    The law governs the movement of people and of goods alike, so the two
    systems must agree about when it permits anything. Neither may call the
    other, so this holds their independent readings to the same answer --
    including the malformed cases, which must fail identically.
    """
    from systems_builders import EVEN_ALLOCATION, LAW_ID, build_law  # noqa: PLC0415

    from living_diorama.systems import MigrationSystem  # noqa: PLC0415

    migration = MigrationSystem(
        law_id=LAW_ID,
        consumption_allocation=EVEN_ALLOCATION,
        migration_rate=0.2,
        min_pressure_gap=0.05,
        partial_isolation_factor=0.5,
    )
    flow = ResourceFlowSystem(
        law_id=LAW_ID, consumption_allocation=EVEN_ALLOCATION, reserve_ticks=1.0
    )

    for active in (True, False):
        for value in (True, False):
            world = build_world(
                [build_district("a"), build_district("b")],
                boundaries=[("bound", "a", "b")],
                law=build_law(active=active, current_value=value),
                tick=1,
            )
            assert migration._movement_permitted(world) == flow._sharing_enabled(world)

    for bad_value in (1, "true", None):
        world = build_world(
            [build_district("a"), build_district("b")],
            boundaries=[("bound", "a", "b")],
            law=build_law(active=True, current_value=bad_value),
            tick=1,
        )
        with pytest.raises(TypeError):
            migration._movement_permitted(world)
        with pytest.raises(TypeError):
            flow._sharing_enabled(world)
