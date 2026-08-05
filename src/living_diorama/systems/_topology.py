"""Which boundaries a district may reach across, shared by movement systems.

Private to the systems package. ResourceFlowSystem already decides what an
open connection means: a boundary is passable unless an active wall stands on
it, several boundaries between the same pair count once, and the smallest
boundary identifier names that pair. Migration has to answer the same question
and must answer it the same way -- a wall that stops food cannot let people
through.

Rather than reach into another system, which the architecture forbids, this
module states the rule once for movement systems to share. A test asserts it
agrees with ResourceFlowSystem's own graph on randomly generated worlds, so
the two cannot drift apart unnoticed.
"""

from typing import TYPE_CHECKING

from living_diorama.entities import EntityId

if TYPE_CHECKING:  # pragma: no cover - import exists for typing only
    from living_diorama.simulation.world import World

type Adjacency = dict[EntityId, set[EntityId]]
type PairBoundary = dict[tuple[EntityId, EntityId], EntityId]


def eligible_graph(world: "World") -> tuple[Adjacency, PairBoundary]:
    """Build the undirected graph of boundaries that may currently be crossed.

    A boundary is eligible unless an active wall stands on it. An inactive
    wall -- including a permanent one that has been deactivated -- remains part
    of the world's history but obstructs nothing.

    When several eligible boundaries connect the same two districts, the
    smallest boundary identifier is kept for that pair. The pair is one
    connection however many boundaries describe it, so duplicated edges never
    multiply what can cross them.

    Args:
        world: The world whose boundaries are being read.

    Returns:
        A pair of (adjacency, boundary identifier per district pair). Pair keys
        are ordered so that the smaller district identifier comes first.

    Raises:
        ValueError: If a boundary names a wall that cannot be resolved.
    """
    adjacency: Adjacency = {}
    pair_boundaries: PairBoundary = {}

    for boundary_id in sorted(world.boundaries):
        boundary = world.boundaries[boundary_id]
        if boundary.wall_id is not None:
            wall = world.walls.get(boundary.wall_id)
            if wall is None:
                raise ValueError(
                    f"boundary {boundary_id!r} references unresolvable wall {boundary.wall_id!r}"
                )
            if wall.active:
                continue

        first, second = sorted((boundary.district_a_id, boundary.district_b_id))
        adjacency.setdefault(first, set()).add(second)
        adjacency.setdefault(second, set()).add(first)
        pair_boundaries.setdefault((first, second), boundary_id)

    return adjacency, pair_boundaries


def boundary_between(pair_boundaries: PairBoundary, first: EntityId, second: EntityId) -> EntityId:
    """Return the identifier naming the connection between two districts.

    Args:
        pair_boundaries: The mapping produced by :func:`eligible_graph`.
        first: One district identifier.
        second: The other district identifier.

    Returns:
        The smallest eligible boundary identifier joining them.

    Raises:
        KeyError: If the two districts are not connected by an eligible
            boundary, which means a caller has strayed outside the graph.
    """
    key = (first, second) if first < second else (second, first)
    return pair_boundaries[key]
