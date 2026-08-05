"""Deterministic, rename-invariant allocation of one resource across a donor graph.

Pure arithmetic: this module knows about identifiers, quantities, and who is
connected to whom. It has no notion of a world, a district, a tick, or an event,
which is what makes the allocation rules testable on their own.

The problem is a small bipartite transportation problem. Donors hold surplus,
receivers hold unmet need, and only directly connected pairs may trade. Three
properties are required at once:

* **Maximal transfer** -- no quantity may be stranded that a valid direct edge
  could have carried.
* **Proportional fairness** -- a donor short of total demand spreads across its
  receivers in proportion to their need, and a receiver short of total supply
  draws from its donors in proportion to their surplus.
* **Rename invariance** -- renaming districts must permute the answer and change
  nothing else. Identifiers may order traversal, output, and serialization. They
  must never decide which district gives up more.

The naive way to get the first two conflicts with the third, because reaching
maximum throughput on a constrained graph requires *choosing* a reroute, and
choosing by identifier order is exactly what rename invariance forbids. The
resolution is to stop choosing. Allocation runs in three phases:

1. A proportional seed, which is fair and rename-invariant but may not reach
   maximum throughput on constrained graphs.
2. Augmentation to maximum throughput. The choice of reroute here *is*
   identifier-dependent, and that is tolerated because of phase 3.
3. A projection that moves the allocation to the unique feasible point closest
   to the seed, measured as the sum of squared per-edge deviations.

Phase 3 is what makes the whole thing invariant. The set of maximum flows and
the seed are both rename-equivariant, and squared deviation is strictly convex
and indifferent to names, so it has exactly one minimiser over that set. Any
starting point inside the set converges to the same answer, which means phase
2's arbitrary choice is erased rather than merely made tidier.
"""

import math
from collections import deque
from collections.abc import Mapping

from living_diorama.entities import EntityId
from living_diorama.systems._resource_config import (
    FLOAT_TOLERANCE,
    PROJECTION_TOLERANCE,
    fsum_ordered,
)

type _Edge = tuple[EntityId, EntityId]
type _Staged = dict[_Edge, float]
type _Adjacency = Mapping[EntityId, set[EntityId]]
type _Node = tuple[str, EntityId]

_DONOR = "D"
_RECEIVER = "R"
_SOURCE: _Node = ("S", "")
_SINK: _Node = ("T", "")


def allocate(
    surplus: Mapping[EntityId, float],
    need: Mapping[EntityId, float],
    adjacency: _Adjacency,
) -> _Staged:
    """Decide how much each donor sends each receiver for one resource.

    Args:
        surplus: Shareable quantity per donor, from the pre-flow snapshot.
        need: Unmet quantity per receiver, from the pre-flow snapshot.
        adjacency: Directly connected districts, keyed by district id.

    Returns:
        The amount to move for each donor-receiver pair carrying a meaningful
        quantity. Pairs that end at zero are omitted entirely.

    Raises:
        ValueError: If either refinement phase fails to settle within its
            iteration bound, which would mean returning an allocation that is
            not provably maximal or not provably the fair one.
    """
    remaining_surplus = {
        donor: amount for donor, amount in sorted(surplus.items()) if amount > FLOAT_TOLERANCE
    }
    remaining_need = {
        receiver: amount for receiver, amount in sorted(need.items()) if amount > FLOAT_TOLERANCE
    }
    if not remaining_surplus or not remaining_need:
        return {}

    edges = _eligible_edges(remaining_surplus, remaining_need, adjacency)
    if not edges:
        return {}

    staged: _Staged = dict.fromkeys(edges, 0.0)
    _run_proportional_rounds(staged, remaining_surplus, remaining_need, adjacency)
    seed = dict(staged)

    _augment_to_maximum(staged, remaining_surplus, remaining_need, adjacency)
    _project_towards_seed(staged, seed, surplus, need, edges)

    return {edge: amount for edge, amount in staged.items() if amount > FLOAT_TOLERANCE}


def _eligible_edges(
    surplus: Mapping[EntityId, float],
    need: Mapping[EntityId, float],
    adjacency: _Adjacency,
) -> list[_Edge]:
    """List every donor-receiver pair that may trade, in a fixed order."""
    return [
        (donor, receiver)
        for donor in sorted(surplus)
        for receiver in sorted(adjacency.get(donor, set()))
        if receiver in need
    ]


# --------------------------------------------------------------------------
# Phase 1: the proportional seed
# --------------------------------------------------------------------------


def _run_proportional_rounds(
    staged: _Staged,
    remaining_surplus: dict[EntityId, float],
    remaining_need: dict[EntityId, float],
    adjacency: _Adjacency,
) -> None:
    """Settle the fair split by repeated simultaneous offer-and-accept rounds.

    Each round has two halves, and the pair of them is what makes the result
    proportional on both sides at once:

    1. **Offers.** Every donor offers its entire remaining surplus, divided
       across its still-needy neighbours in proportion to their remaining need.
       A donor's offers therefore sum to exactly its surplus, which keeps
       one-donor-to-many-receivers proportional.
    2. **Acceptance.** Every receiver whose incoming offers exceed its remaining
       need scales all of them by one common factor. Because each donor's offer
       is proportional to that donor's own surplus, scaling them uniformly
       divides the receiver's capacity between donors in proportion to surplus.

    Offers are computed for the whole graph before any are accepted, so no
    donor's position depends on where its identifier sorts.
    """
    max_rounds = 2 * (len(remaining_surplus) + len(remaining_need)) + 2

    for _ in range(max_rounds):
        offers = _collect_offers(remaining_surplus, remaining_need, adjacency)
        if not offers:
            return
        accepted = _scale_offers_to_receiver_capacity(offers, remaining_need)
        if _apply_round(staged, accepted, remaining_surplus, remaining_need) <= FLOAT_TOLERANCE:
            return


def _collect_offers(
    remaining_surplus: Mapping[EntityId, float],
    remaining_need: Mapping[EntityId, float],
    adjacency: _Adjacency,
) -> _Staged:
    """Offer each donor's whole surplus, split across neighbours by their need."""
    offers: _Staged = {}
    for donor in sorted(remaining_surplus):
        available = remaining_surplus[donor]
        if available <= FLOAT_TOLERANCE:
            continue

        receivers = sorted(
            receiver
            for receiver in adjacency.get(donor, set())
            if remaining_need.get(receiver, 0.0) > FLOAT_TOLERANCE
        )
        if not receivers:
            continue

        total_need = fsum_ordered(remaining_need[receiver] for receiver in receivers)
        if total_need <= FLOAT_TOLERANCE:
            continue

        for receiver in receivers:
            offers[(donor, receiver)] = available * remaining_need[receiver] / total_need
    return offers


def _scale_offers_to_receiver_capacity(
    offers: _Staged, remaining_need: Mapping[EntityId, float]
) -> _Staged:
    """Shrink every offer into an over-subscribed receiver by one common factor."""
    incoming: dict[EntityId, float] = {}
    for (_donor, receiver), amount in sorted(offers.items()):
        incoming[receiver] = incoming.get(receiver, 0.0) + amount

    accepted: _Staged = {}
    for edge in sorted(offers):
        receiver = edge[1]
        capacity = remaining_need[receiver]
        total_incoming = incoming[receiver]
        scale = capacity / total_incoming if total_incoming > capacity else 1.0
        accepted[edge] = offers[edge] * scale
    return accepted


def _apply_round(
    staged: _Staged,
    accepted: _Staged,
    remaining_surplus: dict[EntityId, float],
    remaining_need: dict[EntityId, float],
) -> float:
    """Book one round's accepted amounts and report how much moved.

    The per-edge caps can only bind on floating-point residue: a donor's offers
    sum to exactly its surplus and a receiver's accepted offers to at most its
    need. They are applied in sorted edge order so residue lands identically on
    every run.
    """
    moved = 0.0
    for edge in sorted(accepted):
        donor, receiver = edge
        amount = min(accepted[edge], remaining_surplus[donor], remaining_need[receiver])
        if amount <= FLOAT_TOLERANCE:
            continue
        staged[edge] = staged.get(edge, 0.0) + amount
        remaining_surplus[donor] -= amount
        remaining_need[receiver] -= amount
        moved += amount
    return moved


# --------------------------------------------------------------------------
# Phase 2: reach maximum throughput
# --------------------------------------------------------------------------


def _augment_to_maximum(
    staged: _Staged,
    remaining_surplus: dict[EntityId, float],
    remaining_need: dict[EntityId, float],
    adjacency: _Adjacency,
) -> None:
    """Push the allocation up to the maximum the graph allows.

    The proportional seed settles where no *direct* edge still joins a donor
    holding surplus to a receiver holding need. That is maximal but not always
    maximum: recovering the rest needs rerouting, so this searches the residual
    graph for an alternating path -- forward along an eligible edge, backward
    along quantity already promised elsewhere -- and pushes along it.

    Which reroute this finds depends on identifier order. That is deliberate and
    harmless: phase 3 projects whatever maximum flow lands here onto the unique
    fair one, so the choice made here cannot survive into the result.

    Paths are found breadth-first, so each augmentation takes a shortest path.
    Shortest-path augmentation is the Edmonds-Karp rule, under which the number
    of augmentations is bounded by O(V*E) independently of the capacity values --
    the property that matters here, because capacities are floats and arbitrary
    augmenting-path selection has no such bound.

    Raises:
        ValueError: If the bound is exhausted, rather than silently returning an
            allocation that might not be maximal.
    """
    node_count = len(remaining_surplus) + len(remaining_need) + 2
    edge_count = max(len(staged), 1)
    max_augmentations = node_count * edge_count + node_count + 4

    for _ in range(max_augmentations):
        path = _find_augmenting_path(staged, remaining_surplus, remaining_need, adjacency)
        if path is None:
            return

        bottleneck = _path_bottleneck(path, staged, remaining_surplus, remaining_need)
        if bottleneck <= FLOAT_TOLERANCE:
            return

        _push_along_path(path, staged, remaining_surplus, remaining_need, bottleneck)

    raise ValueError(
        "resource flow could not reach maximum throughput within its augmentation bound"
    )


def _find_augmenting_path(
    staged: _Staged,
    remaining_surplus: Mapping[EntityId, float],
    remaining_need: Mapping[EntityId, float],
    adjacency: _Adjacency,
) -> list[_Node] | None:
    """Breadth-first search for a shortest donor-to-receiver residual path."""
    parents: dict[_Node, _Node | None] = {}
    queue: deque[_Node] = deque()

    for donor in sorted(remaining_surplus):
        if remaining_surplus[donor] > FLOAT_TOLERANCE:
            node: _Node = (_DONOR, donor)
            parents[node] = None
            queue.append(node)

    while queue:
        kind, name = queue.popleft()
        if kind == _DONOR:
            for receiver in sorted(adjacency.get(name, set())):
                if receiver not in remaining_need:
                    continue
                node = (_RECEIVER, receiver)
                if node in parents:
                    continue
                parents[node] = (_DONOR, name)
                if remaining_need[receiver] > FLOAT_TOLERANCE:
                    return _rebuild_path(parents, node)
                queue.append(node)
        else:
            for donor, receiver in sorted(staged):
                if receiver != name or staged[(donor, receiver)] <= FLOAT_TOLERANCE:
                    continue
                node = (_DONOR, donor)
                if node in parents:
                    continue
                parents[node] = (_RECEIVER, name)
                queue.append(node)

    return None


def _rebuild_path(parents: Mapping[_Node, _Node | None], end: _Node) -> list[_Node]:
    """Walk parent links back to the starting donor and return the path forwards."""
    path: list[_Node] = []
    cursor: _Node | None = end
    while cursor is not None:
        path.append(cursor)
        cursor = parents[cursor]
    path.reverse()
    return path


def _path_bottleneck(
    path: list[_Node],
    staged: _Staged,
    remaining_surplus: Mapping[EntityId, float],
    remaining_need: Mapping[EntityId, float],
) -> float:
    """Return the largest quantity the whole path can carry."""
    limits = [remaining_surplus[path[0][1]], remaining_need[path[-1][1]]]
    for first, second in zip(path, path[1:], strict=False):
        if first[0] == _RECEIVER and second[0] == _DONOR:
            limits.append(staged[(second[1], first[1])])
    return min(limits)


def _push_along_path(
    path: list[_Node],
    staged: _Staged,
    remaining_surplus: dict[EntityId, float],
    remaining_need: dict[EntityId, float],
    amount: float,
) -> None:
    """Move a quantity along the path, adding forwards and unwinding backwards."""
    remaining_surplus[path[0][1]] -= amount
    remaining_need[path[-1][1]] -= amount

    for first, second in zip(path, path[1:], strict=False):
        if first[0] == _DONOR:
            edge = (first[1], second[1])
            staged[edge] = staged.get(edge, 0.0) + amount
        else:
            edge = (second[1], first[1])
            staged[edge] -= amount


# --------------------------------------------------------------------------
# Phase 3: the rename-invariant projection
# --------------------------------------------------------------------------


class _ResidualArc:
    """One direction of change available at the current allocation.

    An arc says: this much quantity may still be shifted this way, and shifting
    a unit changes the squared-deviation objective at this rate.
    """

    __slots__ = ("capacity", "delta", "edge", "head", "tail", "weight")

    def __init__(
        self,
        tail: _Node,
        head: _Node,
        capacity: float,
        weight: float,
        edge: _Edge | None,
        delta: int,
    ) -> None:
        """Record one residual arc."""
        self.tail = tail
        self.head = head
        self.capacity = capacity
        self.weight = weight
        self.edge = edge
        self.delta = delta


def _project_towards_seed(
    staged: _Staged,
    seed: _Staged,
    surplus: Mapping[EntityId, float],
    need: Mapping[EntityId, float],
    edges: list[_Edge],
) -> None:
    """Move the allocation to the unique fair point of the maximum-flow set.

    Phase 2 leaves *a* maximum flow, chosen partly by identifier order. This
    replaces it with *the* maximum flow that sits closest to the proportional
    seed, closeness being the sum over edges of squared deviation from the seed.

    That objective is strictly convex and takes no notice of names, and the set
    of maximum flows is itself unchanged by renaming, so the minimiser is unique
    and renaming permutes it exactly. Reaching it therefore erases whatever
    arbitrary choice phase 2 made.

    The minimiser is characterised by the absence of an improving circulation:
    for convex edge costs, a feasible flow is optimal exactly when no residual
    cycle has negative total cost. This repeatedly finds such a cycle and shifts
    the amount along it that minimises the objective, which is available in
    closed form because the cost is quadratic.

    Raises:
        ValueError: If no improving cycle can be eliminated within the bound,
            rather than silently returning an allocation that is not the fair one.
    """
    max_iterations = 64 * (len(edges) + len(surplus) + len(need)) + 64

    for _ in range(max_iterations):
        arcs = _residual_arcs(staged, seed, surplus, need, edges)
        cycle = _find_minimum_mean_cycle(arcs)
        if cycle is None or not _shift_along_cycle(cycle, staged):
            _clean_residue(staged)
            return

    raise ValueError("resource flow could not settle on a fair allocation within its bound")


def _residual_arcs(
    staged: _Staged,
    seed: _Staged,
    surplus: Mapping[EntityId, float],
    need: Mapping[EntityId, float],
    edges: list[_Edge],
) -> list[_ResidualArc]:
    """Build every way the current allocation could still be adjusted.

    Arcs through the source and sink carry no cost: they let a cycle move a
    donor's total contribution or a receiver's total intake without changing the
    grand total, which is what keeps every adjustment inside the maximum-flow
    set. Only the edge arcs carry cost, and their cost is the current deviation
    from the seed, which is the derivative of the squared-deviation objective.
    """
    sent: dict[EntityId, float] = {}
    received: dict[EntityId, float] = {}
    for (donor, receiver), amount in sorted(staged.items()):
        sent[donor] = sent.get(donor, 0.0) + amount
        received[receiver] = received.get(receiver, 0.0) + amount

    arcs: list[_ResidualArc] = []

    for donor in sorted(surplus):
        used = sent.get(donor, 0.0)
        spare = surplus[donor] - used
        if spare > PROJECTION_TOLERANCE:
            arcs.append(_ResidualArc(_SOURCE, (_DONOR, donor), spare, 0.0, None, 0))
        if used > PROJECTION_TOLERANCE:
            arcs.append(_ResidualArc((_DONOR, donor), _SOURCE, used, 0.0, None, 0))

    for receiver in sorted(need):
        taken = received.get(receiver, 0.0)
        spare = need[receiver] - taken
        if spare > PROJECTION_TOLERANCE:
            arcs.append(_ResidualArc((_RECEIVER, receiver), _SINK, spare, 0.0, None, 0))
        if taken > PROJECTION_TOLERANCE:
            arcs.append(_ResidualArc(_SINK, (_RECEIVER, receiver), taken, 0.0, None, 0))

    for edge in edges:
        donor, receiver = edge
        deviation = staged.get(edge, 0.0) - seed.get(edge, 0.0)

        # Increasing an edge carries no capacity of its own. Whether there is
        # room comes from the rest of the cycle: either it also enters this
        # donor through the source arc, which is limited by the donor's spare
        # surplus, or it enters by unwinding another of this donor's edges,
        # which leaves the donor's total untouched and needs no spare at all.
        # Capping the edge here would hide improving cycles of the second kind.
        arcs.append(
            _ResidualArc((_DONOR, donor), (_RECEIVER, receiver), math.inf, deviation, edge, 1)
        )

        carried = staged.get(edge, 0.0)
        if carried > PROJECTION_TOLERANCE:
            arcs.append(
                _ResidualArc((_RECEIVER, receiver), (_DONOR, donor), carried, -deviation, edge, -1)
            )

    return arcs


def _find_minimum_mean_cycle(arcs: list[_ResidualArc]) -> list[_ResidualArc] | None:
    """Return the residual cycle with the lowest average cost, or None if none is negative.

    Karp's method. ``levels[k][v]`` is the cheapest walk of exactly ``k`` arcs
    ending at ``v``, starting anywhere. The minimum cycle mean is then the
    smallest over vertices of the largest ``(levels[n][v] - levels[k][v]) /
    (n - k)``, and the vertex achieving it lies on a cycle attaining that mean.

    Choosing the *minimum mean* cycle rather than any negative one matters here.
    A plain negative-cycle search reports only whether one exists; the cycle it
    hands back is whichever its predecessor chain happens to enter, which may be
    barely improving or not improving at all. Cancelling the minimum mean cycle
    always makes real progress, which is what lets the projection reach the
    optimum instead of stalling near it.
    """
    nodes = sorted({arc.tail for arc in arcs} | {arc.head for arc in arcs})
    count = len(nodes)
    if count == 0:
        return None

    index = {node: position for position, node in enumerate(nodes)}
    levels: list[list[float]] = [[math.inf] * count for _ in range(count + 1)]
    origins: list[list[_ResidualArc | None]] = [[None] * count for _ in range(count + 1)]
    levels[0] = [0.0] * count

    for step in range(1, count + 1):
        for arc in arcs:
            tail, head = index[arc.tail], index[arc.head]
            if levels[step - 1][tail] == math.inf:
                continue
            candidate = levels[step - 1][tail] + arc.weight
            if candidate < levels[step][head]:
                levels[step][head] = candidate
                origins[step][head] = arc

    best_mean = math.inf
    best_vertex: int | None = None
    for vertex in range(count):
        if levels[count][vertex] == math.inf:
            continue
        worst = -math.inf
        for step in range(count):
            if levels[step][vertex] == math.inf:
                continue
            worst = max(worst, (levels[count][vertex] - levels[step][vertex]) / (count - step))
        if worst > -math.inf and worst < best_mean:
            best_mean, best_vertex = worst, vertex

    if best_vertex is None or best_mean >= -PROJECTION_TOLERANCE:
        return None

    return _extract_cycle_from_levels(origins, best_vertex, count, index)


def _extract_cycle_from_levels(
    origins: list[list[_ResidualArc | None]],
    vertex: int,
    count: int,
    index: Mapping[_Node, int],
) -> list[_ResidualArc] | None:
    """Walk the optimal walk backwards until a vertex repeats, then return that cycle."""
    trail: list[_ResidualArc] = []
    seen: dict[int, int] = {}
    current, step = vertex, count

    while step > 0:
        if current in seen:
            cycle = trail[seen[current] :]
            cycle.reverse()
            return cycle or None
        seen[current] = len(trail)
        arc = origins[step][current]
        if arc is None:
            return None
        trail.append(arc)
        current = index[arc.tail]
        step -= 1

    if current in seen:
        cycle = trail[seen[current] :]
        cycle.reverse()
        return cycle or None
    return None


def _shift_along_cycle(cycle: list[_ResidualArc], staged: _Staged) -> bool:
    """Shift the objective-minimising amount around one improving cycle.

    Pushing an amount ``x`` changes each cost-bearing edge's deviation by
    ``±x``, so the objective becomes ``sum((deviation ± x)**2)``. That is a
    parabola in ``x`` whose minimum sits at ``-sum(weights) / count``, and the
    shift is capped by the residual capacity of every arc on the cycle.

    Returns:
        True if a meaningful shift was made, False if the improvement available
        is smaller than tolerance and the allocation should be treated as settled.
    """
    cost_arcs = [arc for arc in cycle if arc.delta != 0]
    if not cost_arcs:
        return False

    gradient = fsum_ordered(arc.weight for arc in cost_arcs)
    if gradient >= -PROJECTION_TOLERANCE:
        return False

    ideal = -gradient / len(cost_arcs)
    limit = min(arc.capacity for arc in cycle)
    shift = min(ideal, limit)
    if shift <= PROJECTION_TOLERANCE:
        return False

    for arc in cost_arcs:
        if arc.edge is None:
            continue
        staged[arc.edge] = staged.get(arc.edge, 0.0) + arc.delta * shift
    return True


def _clean_residue(staged: _Staged) -> None:
    """Flatten floating-point residue so tiny negatives never survive."""
    for edge in sorted(staged):
        if -FLOAT_TOLERANCE < staged[edge] < FLOAT_TOLERANCE:
            staged[edge] = 0.0
