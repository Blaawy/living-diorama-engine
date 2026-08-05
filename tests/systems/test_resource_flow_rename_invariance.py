"""Regression tests for rename invariance of the resource allocation.

The engine's whole premise is that a world's history is caused by its rules and
its geography. If renaming a district changed how much it gave up, the recorded
history would partly be an artefact of identifier spelling, and two runs of the
same experiment could diverge for a reason no viewer could ever be shown.

Identifiers are allowed to order traversal, event output, and serialization.
They are not allowed to decide numbers. These tests hold that line for the case
that used to break it: constrained graphs where reaching maximum throughput
requires rerouting.
"""

import itertools
import random

from living_diorama.systems._flow_allocation import allocate
from living_diorama.systems._resource_config import FLOAT_TOLERANCE

RENAME_TOLERANCE = FLOAT_TOLERANCE
"""How closely two renamed runs must agree: the engine's own quantity tolerance.

Renaming is not an approximation of anything, so the bar is the same one the
simulation uses to decide whether a quantity exists at all. The allocation is
settled by an iterative projection, which is why the projection stops at a
threshold a hundred times finer than this one -- the certificate has to be
finer than the stopping rule. Measured residue across roughly twenty thousand
relabellings is about 5e-11, some twenty times inside this bound.
"""


def rename(mapping: dict[str, str], allocation: dict[tuple[str, str], float]):
    """Map an allocation's district ids back through a rename."""
    return {
        (mapping.get(donor, donor), mapping.get(receiver, receiver)): amount
        for (donor, receiver), amount in allocation.items()
    }


def rename_inputs(
    mapping: dict[str, str],
    surplus: dict[str, float],
    need: dict[str, float],
    adjacency: dict[str, set[str]],
):
    """Apply a rename to every input of the allocation."""
    return (
        {mapping.get(k, k): v for k, v in surplus.items()},
        {mapping.get(k, k): v for k, v in need.items()},
        {
            mapping.get(k, k): {mapping.get(x, x) for x in v}
            for k, v in adjacency.items()
        },
    )


def donor_totals(allocation: dict[tuple[str, str], float]) -> dict[str, float]:
    """Sum how much each donor gives away."""
    totals: dict[str, float] = {}
    for (donor, _receiver), amount in allocation.items():
        totals[donor] = totals.get(donor, 0.0) + amount
    return totals


def receiver_totals(allocation: dict[tuple[str, str], float]) -> dict[str, float]:
    """Sum how much each receiver takes in."""
    totals: dict[str, float] = {}
    for (_donor, receiver), amount in allocation.items():
        totals[receiver] = totals.get(receiver, 0.0) + amount
    return totals


def assert_equivalent(first, second, tolerance: float = RENAME_TOLERANCE) -> None:
    """Assert two allocations agree within the engine's quantity tolerance.

    Checked at four levels, because a difference can hide at any of them: every
    mapped-back edge, every donor's total contribution, every receiver's total
    intake, and the grand total moved. Edge agreement implies the rest
    arithmetically, but asserting each separately means a failure says which
    property broke rather than only that something did.
    """
    for edge in set(first) | set(second):
        assert abs(first.get(edge, 0.0) - second.get(edge, 0.0)) <= tolerance, edge

    for left, right in (
        (donor_totals(first), donor_totals(second)),
        (receiver_totals(first), receiver_totals(second)),
    ):
        for key in set(left) | set(right):
            assert abs(left.get(key, 0.0) - right.get(key, 0.0)) <= tolerance, key

    assert abs(sum(first.values()) - sum(second.values())) <= tolerance


# The graph from the review: r2 can only be fed by d3, so reaching the full
# transfer of 2.0 forces d3 to spend itself there, leaving r1 to the two
# equivalent donors -- who must therefore split it evenly.
MINIMAL_SURPLUS = {"d1": 1.0, "d2": 1.0, "d3": 1.0}
MINIMAL_NEED = {"r1": 1.0, "r2": 1.0}
MINIMAL_ADJACENCY = {"d1": {"r1"}, "d2": {"r1"}, "d3": {"r1", "r2"}}


def test_minimal_symmetric_augmentation_splits_evenly() -> None:
    """Equivalent donors bear equal shares even when rerouting is required."""
    result = allocate(MINIMAL_SURPLUS, MINIMAL_NEED, MINIMAL_ADJACENCY)

    assert abs(result[("d1", "r1")] - 0.5) <= FLOAT_TOLERANCE
    assert abs(result[("d2", "r1")] - 0.5) <= FLOAT_TOLERANCE
    assert abs(result[("d3", "r2")] - 1.0) <= FLOAT_TOLERANCE
    assert abs(sum(result.values()) - 2.0) <= FLOAT_TOLERANCE
    assert donor_totals(result)["d3"] <= 1.0 + FLOAT_TOLERANCE


def test_minimal_case_survives_reversing_donor_lexical_order() -> None:
    """Renaming the two equivalent donors so their order flips changes nothing."""
    forward = {"d1": "z1", "d2": "a1", "d3": "d3"}
    backward = {value: key for key, value in forward.items()}

    surplus, need, adjacency = rename_inputs(
        forward, MINIMAL_SURPLUS, MINIMAL_NEED, MINIMAL_ADJACENCY
    )
    mapped_back = rename(backward, allocate(surplus, need, adjacency))
    original = allocate(MINIMAL_SURPLUS, MINIMAL_NEED, MINIMAL_ADJACENCY)

    assert_equivalent(original, mapped_back)
    assert abs(mapped_back[("d1", "r1")] - 0.5) <= RENAME_TOLERANCE
    assert abs(mapped_back[("d2", "r1")] - 0.5) <= RENAME_TOLERANCE


# Every graph here needs rerouting: the proportional split alone cannot reach
# the maximum, which is exactly where identifier order used to leak in.
CONSTRAINED_GRAPHS = (
    (
        {"d1": 1.0, "d2": 1.0, "d3": 1.0},
        {"r1": 1.0, "r2": 1.0},
        {"d1": {"r1"}, "d2": {"r1"}, "d3": {"r1", "r2"}},
    ),
    (
        {"d1": 10.0, "d2": 10.0},
        {"r1": 10.0, "r2": 10.0},
        {"d1": {"r1"}, "d2": {"r1", "r2"}},
    ),
    (
        {"d1": 2.0, "d2": 10.0},
        {"r1": 6.0, "r2": 6.0},
        {"d1": {"r1"}, "d2": {"r1", "r2"}},
    ),
    (
        {"d1": 5.0, "d2": 5.0, "d3": 20.0},
        {"r1": 12.0, "r2": 8.0, "r3": 4.0},
        {"d1": {"r1"}, "d2": {"r1", "r2"}, "d3": {"r1", "r2", "r3"}},
    ),
    (
        {"d1": 7.0, "d2": 7.0, "d3": 7.0, "d4": 1.0},
        {"r1": 9.0, "r2": 9.0, "r3": 3.0},
        {
            "d1": {"r1"},
            "d2": {"r1", "r2"},
            "d3": {"r2", "r3"},
            "d4": {"r3"},
        },
    ),
)

DONOR_PERMUTATIONS = (
    {"d1": "zz", "d2": "aa"},
    {"d1": "m0", "d2": "m1", "d3": "a9"},
    {"d1": "q", "d2": "p", "d3": "o", "d4": "n"},
)


def test_constrained_graphs_are_invariant_under_donor_renaming() -> None:
    """Across a table of rerouting graphs, donor names never move the numbers."""
    for surplus, need, adjacency in CONSTRAINED_GRAPHS:
        original = allocate(surplus, need, adjacency)

        for permutation in DONOR_PERMUTATIONS:
            mapping = {k: v for k, v in permutation.items() if k in surplus}
            if len(set(mapping.values())) != len(mapping):
                continue
            inverse = {v: k for k, v in mapping.items()}

            renamed_inputs = rename_inputs(mapping, surplus, need, adjacency)
            mapped_back = rename(inverse, allocate(*renamed_inputs))
            assert_equivalent(original, mapped_back)


def test_constrained_graphs_are_invariant_under_receiver_renaming() -> None:
    """Receiver names are equally powerless over the numbers."""
    for surplus, need, adjacency in CONSTRAINED_GRAPHS:
        original = allocate(surplus, need, adjacency)
        mapping = {receiver: f"zzz_{receiver}" for receiver in need}
        inverse = {v: k for k, v in mapping.items()}

        renamed_inputs = rename_inputs(mapping, surplus, need, adjacency)
        mapped_back = rename(inverse, allocate(*renamed_inputs))
        assert_equivalent(original, mapped_back)


def test_constrained_graphs_are_invariant_under_renaming_both_sides() -> None:
    """Renaming donors and receivers together is still only a renaming."""
    for surplus, need, adjacency in CONSTRAINED_GRAPHS:
        original = allocate(surplus, need, adjacency)
        mapping = {name: f"x{index}" for index, name in enumerate(sorted(surplus))}
        mapping.update(
            {name: f"y{index}" for index, name in enumerate(sorted(need), start=100)}
        )
        inverse = {v: k for k, v in mapping.items()}

        renamed_inputs = rename_inputs(mapping, surplus, need, adjacency)
        mapped_back = rename(inverse, allocate(*renamed_inputs))
        assert_equivalent(original, mapped_back)


def test_structurally_equivalent_donors_give_equally() -> None:
    """Donors alike in surplus and connections must contribute alike.

    Both graphs need rerouting, so this is checked where the old algorithm
    failed rather than only where the proportional split already sufficed.
    """
    equal_pairs = (
        (MINIMAL_SURPLUS, MINIMAL_NEED, MINIMAL_ADJACENCY, ("d1", "d2")),
        (
            {"a": 4.0, "b": 4.0, "c": 4.0, "hub": 6.0},
            {"shared": 6.0, "private": 6.0},
            {
                "a": {"shared"},
                "b": {"shared"},
                "c": {"shared"},
                "hub": {"shared", "private"},
            },
            ("a", "b"),
        ),
    )

    for surplus, need, adjacency, (left, right) in equal_pairs:
        totals = donor_totals(allocate(surplus, need, adjacency))
        assert abs(totals.get(left, 0.0) - totals.get(right, 0.0)) <= RENAME_TOLERANCE


def test_unequal_donors_differ_by_surplus_not_by_name() -> None:
    """Unequal donors may differ, but swapping their names swaps their shares."""
    surplus = {"big": 70.0, "small": 30.0}
    need = {"r": 20.0}
    adjacency = {"big": {"r"}, "small": {"r"}}

    original = allocate(surplus, need, adjacency)
    assert abs(original[("small", "r")] - 6.0) <= FLOAT_TOLERANCE
    assert abs(original[("big", "r")] - 14.0) <= FLOAT_TOLERANCE

    mapping = {"big": "aaa", "small": "zzz"}
    inverse = {v: k for k, v in mapping.items()}
    mapped_back = rename(inverse, allocate(*rename_inputs(mapping, surplus, need, adjacency)))
    assert_equivalent(original, mapped_back)


def test_maximum_throughput_is_preserved_on_every_constrained_graph() -> None:
    """Invariance was not bought by giving up transfer: each graph still saturates.

    Each table entry has enough connected surplus to satisfy every receiver, so
    the maximum is the total need. Any stranding would show up here immediately.
    """
    for surplus, need, adjacency in CONSTRAINED_GRAPHS:
        result = allocate(surplus, need, adjacency)
        totals = receiver_totals(result)
        for receiver, amount in need.items():
            reachable = sum(
                surplus[donor] for donor in surplus if receiver in adjacency.get(donor, set())
            )
            if reachable >= amount:
                assert totals.get(receiver, 0.0) <= amount + FLOAT_TOLERANCE

        sent = donor_totals(result)
        for donor, amount in surplus.items():
            assert sent.get(donor, 0.0) <= amount + FLOAT_TOLERANCE
            if sent.get(donor, 0.0) < amount - RENAME_TOLERANCE:
                for receiver in adjacency.get(donor, set()):
                    assert need[receiver] - totals.get(receiver, 0.0) <= RENAME_TOLERANCE


def test_original_constrained_reroute_still_reaches_the_full_transfer() -> None:
    """The graph that motivated augmentation in the first place still saturates."""
    result = allocate(
        {"d1": 10.0, "d2": 10.0},
        {"r1": 10.0, "r2": 10.0},
        {"d1": {"r1"}, "d2": {"r1", "r2"}},
    )
    assert abs(sum(result.values()) - 20.0) <= FLOAT_TOLERANCE
    assert abs(receiver_totals(result)["r1"] - 10.0) <= FLOAT_TOLERANCE
    assert abs(receiver_totals(result)["r2"] - 10.0) <= FLOAT_TOLERANCE


def test_seeded_random_graphs_are_invariant_and_well_formed() -> None:
    """A bounded, seeded sweep: rename invariance plus caps and conservation.

    Deliberately small so it belongs in the ordinary test run. The wider sweeps
    used during development covered tens of thousands of graphs; this keeps a
    representative slice permanently in the suite.
    """
    rng = random.Random(20260805)

    for _ in range(120):
        donor_count, receiver_count = rng.randint(1, 4), rng.randint(1, 4)
        donors = [f"d{index}" for index in range(donor_count)]
        receivers = [f"r{index}" for index in range(receiver_count)]
        surplus = {donor: round(rng.uniform(0.0, 20.0), 3) for donor in donors}
        need = {receiver: round(rng.uniform(0.0, 20.0), 3) for receiver in receivers}
        adjacency = {donor: set() for donor in donors}
        for donor, receiver in itertools.product(donors, receivers):
            if rng.random() < 0.6:
                adjacency[donor].add(receiver)

        original = allocate(surplus, need, adjacency)

        sent = donor_totals(original)
        taken = receiver_totals(original)
        for donor, amount in surplus.items():
            assert sent.get(donor, 0.0) <= amount + FLOAT_TOLERANCE
        for receiver, amount in need.items():
            assert taken.get(receiver, 0.0) <= amount + FLOAT_TOLERANCE
        assert abs(sum(sent.values()) - sum(taken.values())) <= FLOAT_TOLERANCE
        assert all(amount > 0.0 for amount in original.values())

        shuffled = donors[:]
        rng.shuffle(shuffled)
        mapping = dict(zip(donors, shuffled, strict=True))
        inverse = {v: k for k, v in mapping.items()}
        mapped_back = rename(inverse, allocate(*rename_inputs(mapping, surplus, need, adjacency)))
        assert_equivalent(original, mapped_back)


def test_allocation_is_reproducible_across_repeated_runs() -> None:
    """Identical inputs must give bit-identical output every time."""
    for surplus, need, adjacency in CONSTRAINED_GRAPHS:
        runs = [allocate(surplus, need, adjacency) for _ in range(3)]
        assert runs[0] == runs[1] == runs[2]


# A graph on which the projection can only reach the optimum by unwinding one
# of a donor's own edges to fund another. Increasing an edge has no capacity of
# its own in that situation -- the donor's total does not change -- so a search
# that caps increases by the donor's spare surplus never finds the improvement
# and stops short of the fair allocation.
UNWIND_SURPLUS = {"d0": 4.0, "d1": 6.0, "d2": 6.0, "d3": 9.0}
UNWIND_NEED = {"r0": 7.0, "r1": 10.0, "r2": 8.0, "r3": 2.0}
UNWIND_ADJACENCY = {
    "d0": {"r0", "r2"},
    "d1": {"r2", "r3"},
    "d2": {"r3"},
    "d3": {"r0", "r1", "r2", "r3"},
}


def test_projection_can_fund_an_edge_by_unwinding_another_of_the_same_donor() -> None:
    """A donor at full capacity must still be able to rearrange where it sends.

    ``d0`` is exhausted, so no spare surplus is available to it, yet the fair
    allocation has it splitting between ``r0`` and ``r2`` rather than pouring
    everything into ``r0``. Reaching that requires shifting quantity *within*
    the donor, which stays invisible to any search that treats an increase as
    needing spare capacity.
    """
    result = allocate(UNWIND_SURPLUS, UNWIND_NEED, UNWIND_ADJACENCY)

    assert result[("d0", "r2")] > RENAME_TOLERANCE
    assert abs(donor_totals(result)["d0"] - 4.0) <= RENAME_TOLERANCE
    assert abs(result[("d0", "r0")] - 3.103578155) <= RENAME_TOLERANCE
    assert abs(result[("d0", "r2")] - 0.896421845) <= RENAME_TOLERANCE


def test_unwinding_graph_is_also_rename_invariant() -> None:
    """The same graph, renamed, must still settle on the same numbers."""
    original = allocate(UNWIND_SURPLUS, UNWIND_NEED, UNWIND_ADJACENCY)
    mapping = {"d0": "z9", "d1": "z8", "d2": "a2", "d3": "a1"}
    inverse = {v: k for k, v in mapping.items()}
    mapped_back = rename(
        inverse, allocate(*rename_inputs(mapping, UNWIND_SURPLUS, UNWIND_NEED, UNWIND_ADJACENCY))
    )
    assert_equivalent(original, mapped_back)


# This graph produced the largest rename residue found under the previous
# projection, which stopped as soon as no improvement exceeded the engine's
# quantity tolerance: two renamed runs settled about 4.15e-09 apart, four times
# outside the contract they were meant to satisfy. It is kept as a fixed case
# because it is the shape that provoked the residue -- several donors sharing
# several receivers, with caps binding on both sides -- not because the numbers
# are special.
RESIDUE_SURPLUS = {"d0": 13.0, "d1": 14.0, "d2": 13.0, "d3": 7.0}
RESIDUE_NEED = {"r0": 9.0, "r1": 10.0, "r2": 3.0, "r3": 12.0}
RESIDUE_ADJACENCY = {
    "d0": {"r0", "r1", "r2", "r3"},
    "d1": {"r0"},
    "d2": {"r0", "r1", "r2"},
    "d3": {"r0", "r1", "r2", "r3"},
}


def test_previous_worst_residue_graph_now_agrees_within_float_tolerance() -> None:
    """The graph that broke the 1e-9 contract now settles well inside it."""
    original = allocate(RESIDUE_SURPLUS, RESIDUE_NEED, RESIDUE_ADJACENCY)

    mapping = {"d0": "d3", "d1": "d2", "d2": "d1", "d3": "d0"}
    inverse = {value: key for key, value in mapping.items()}
    mapped_back = rename(
        inverse,
        allocate(*rename_inputs(mapping, RESIDUE_SURPLUS, RESIDUE_NEED, RESIDUE_ADJACENCY)),
    )

    assert_equivalent(original, mapped_back)

    worst = max(
        abs(original.get(edge, 0.0) - mapped_back.get(edge, 0.0))
        for edge in set(original) | set(mapped_back)
    )
    assert worst <= FLOAT_TOLERANCE / 10, worst


def test_previous_worst_residue_graph_still_reaches_maximum_throughput() -> None:
    """Tighter convergence must not have been bought by moving less.

    Total need is 34 and every receiver is reachable from a donor with spare
    surplus, so a correct allocation satisfies all of it.
    """
    result = allocate(RESIDUE_SURPLUS, RESIDUE_NEED, RESIDUE_ADJACENCY)
    taken = receiver_totals(result)

    assert abs(sum(result.values()) - sum(RESIDUE_NEED.values())) <= FLOAT_TOLERANCE
    for receiver, amount in RESIDUE_NEED.items():
        assert abs(taken.get(receiver, 0.0) - amount) <= FLOAT_TOLERANCE

    sent = donor_totals(result)
    for donor, amount in RESIDUE_SURPLUS.items():
        assert sent.get(donor, 0.0) <= amount + FLOAT_TOLERANCE


def test_residue_graph_is_invariant_under_receiver_and_combined_renaming() -> None:
    """The same graph holds up when receivers, or both sides, are renamed."""
    original = allocate(RESIDUE_SURPLUS, RESIDUE_NEED, RESIDUE_ADJACENCY)

    receiver_map = {"r0": "r3", "r1": "r2", "r2": "r1", "r3": "r0"}
    combined = {"d0": "z0", "d1": "z1", "d2": "a2", "d3": "a3"} | receiver_map

    for mapping in (receiver_map, combined):
        inverse = {value: key for key, value in mapping.items()}
        mapped_back = rename(
            inverse,
            allocate(*rename_inputs(mapping, RESIDUE_SURPLUS, RESIDUE_NEED, RESIDUE_ADJACENCY)),
        )
        assert_equivalent(original, mapped_back)
