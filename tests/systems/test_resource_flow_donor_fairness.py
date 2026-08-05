"""Regression tests for proportional fairness among donors sharing a receiver.

The defect these cover: donors used to be processed sequentially by identifier,
so the lexicographically first donor could satisfy a shared receiver's entire
need while an equivalent donor beside it contributed nothing. That was
deterministic but arbitrary -- which donor bore the whole cost depended on how
its identifier happened to sort.

Fairness now has to hold on both sides at once, and it must not cost throughput,
so these tests check the split, the caps, and the total moved.
"""

from living_diorama.entities import ResourceType
from living_diorama.events import EventBus, EventLog, EventType
from living_diorama.systems import ResourceFlowSystem
from living_diorama.systems._flow_allocation import allocate
from living_diorama.systems._resource_config import FLOAT_TOLERANCE
from systems_builders import (
    FOOD_ONLY_ALLOCATION,
    LAW_ID,
    build_district,
    build_law,
    build_world,
    stocks,
    total_of,
)


def build_flow(reserve_ticks: float = 1.0) -> ResourceFlowSystem:
    """Build a flow system that reserves food only, to keep arithmetic legible."""
    return ResourceFlowSystem(
        law_id=LAW_ID,
        consumption_allocation=FOOD_ONLY_ALLOCATION,
        reserve_ticks=reserve_ticks,
    )


def run_flow(world, flow=None) -> EventLog:
    """Run one flow update and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    (flow or build_flow()).update(world, bus)
    return log


def transfer_amounts(log: EventLog) -> dict[tuple[str, str], float]:
    """Collapse a log into the amount moved per donor-receiver pair."""
    return {
        (str(event.payload["from_district_id"]), str(event.payload["to_district_id"])): float(
            event.payload["amount"]  # type: ignore[arg-type]
        )
        for event in log.query(event_type=EventType.RESOURCE_TRANSFERRED)
    }


def shared_receiver_world(*, d1_food: float, d2_food: float, receiver_population: int):
    """Build two donors that both connect to one shared receiver."""
    return build_world(
        [
            build_district("d1", population=0, consumption_rate=1.0, food=d1_food),
            build_district("d2", population=0, consumption_rate=1.0, food=d2_food),
            build_district("r", population=receiver_population, consumption_rate=1.0,
                           food=0.0),
        ],
        boundaries=[("d1r", "d1", "r"), ("d2r", "d2", "r")],
        law=build_law(),
        tick=1,
    )


def test_symmetric_donors_contribute_equally_to_a_shared_receiver() -> None:
    """The headline defect: equivalent donors must bear equivalent shares."""
    world = shared_receiver_world(d1_food=100.0, d2_food=100.0, receiver_population=10)
    log = run_flow(world)
    result = stocks(world, ResourceType.FOOD)
    amounts = transfer_amounts(log)

    assert abs(amounts[("d1", "r")] - 5.0) <= FLOAT_TOLERANCE
    assert abs(amounts[("d2", "r")] - 5.0) <= FLOAT_TOLERANCE
    assert len(amounts) == 2

    assert abs(result["d1"] - 95.0) <= FLOAT_TOLERANCE
    assert abs(result["d2"] - 95.0) <= FLOAT_TOLERANCE
    assert abs(result["r"] - 10.0) <= FLOAT_TOLERANCE
    assert abs(total_of(world, ResourceType.FOOD) - 200.0) <= FLOAT_TOLERANCE


def test_unequal_donors_contribute_in_proportion_to_their_surplus() -> None:
    """A donor with 30 spare and one with 70 split a need of 20 as 6 and 14."""
    world = shared_receiver_world(d1_food=30.0, d2_food=70.0, receiver_population=20)
    amounts = transfer_amounts(run_flow(world))

    assert abs(amounts[("d1", "r")] - 6.0) <= FLOAT_TOLERANCE
    assert abs(amounts[("d2", "r")] - 14.0) <= FLOAT_TOLERANCE
    assert abs(total_of(world, ResourceType.FOOD) - 100.0) <= FLOAT_TOLERANCE


def test_a_small_donor_is_never_assigned_more_than_it_holds() -> None:
    """Donor capacity binds absolutely once demand outruns the donors' combined stock.

    A donor's offers are its whole surplus and no more, so it can never be
    assigned beyond what it holds. Here demand exceeds the pair's combined
    surplus, so both give everything and the receiver stays short.
    """
    world = shared_receiver_world(d1_food=2.0, d2_food=100.0, receiver_population=200)
    amounts = transfer_amounts(run_flow(world))
    result = stocks(world, ResourceType.FOOD)

    assert abs(amounts[("d1", "r")] - 2.0) <= FLOAT_TOLERANCE
    assert abs(amounts[("d2", "r")] - 100.0) <= FLOAT_TOLERANCE
    assert abs(result["d1"]) <= FLOAT_TOLERANCE
    assert abs(result["d2"]) <= FLOAT_TOLERANCE
    assert abs(result["r"] - 102.0) <= FLOAT_TOLERANCE


def test_a_small_donor_carries_only_its_proportional_share() -> None:
    """A donor holding little bears little; the larger donor carries the rest.

    This is the mirror of the corrected defect. Under the old algorithm 'd1'
    sorted first and would have been drained for the receiver's whole need
    despite holding a fiftieth of the available surplus.
    """
    world = shared_receiver_world(d1_food=2.0, d2_food=100.0, receiver_population=20)
    amounts = transfer_amounts(run_flow(world))

    assert abs(amounts[("d1", "r")] - 20.0 * 2.0 / 102.0) <= FLOAT_TOLERANCE
    assert abs(amounts[("d2", "r")] - 20.0 * 100.0 / 102.0) <= FLOAT_TOLERANCE
    assert abs(stocks(world, ResourceType.FOOD)["r"] - 20.0) <= FLOAT_TOLERANCE


def test_exhausted_small_donor_leaves_the_rest_to_a_reachable_donor() -> None:
    """When a small donor runs dry, remaining need is met by whoever can still reach it."""
    world = build_world(
        [
            build_district("d1", population=0, consumption_rate=1.0, food=2.0),
            build_district("d2", population=0, consumption_rate=1.0, food=10.0),
            build_district("r1", population=6, consumption_rate=1.0, food=0.0),
            build_district("r2", population=6, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("b1", "d1", "r1"), ("b2", "d2", "r1"), ("b3", "d2", "r2")],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    result = stocks(world, ResourceType.FOOD)

    assert abs(result["d1"]) <= FLOAT_TOLERANCE
    assert abs(result["d2"]) <= FLOAT_TOLERANCE
    assert abs(result["r1"] - 6.0) <= FLOAT_TOLERANCE
    assert abs(result["r2"] - 6.0) <= FLOAT_TOLERANCE
    assert abs(total_of(world, ResourceType.FOOD) - 12.0) <= FLOAT_TOLERANCE


def test_receiver_capacity_cap_holds_across_many_donors() -> None:
    """Four donors fill a receiver to exactly its need, in equal shares."""
    world = build_world(
        [
            build_district("d1", population=0, consumption_rate=1.0, food=100.0),
            build_district("d2", population=0, consumption_rate=1.0, food=100.0),
            build_district("d3", population=0, consumption_rate=1.0, food=100.0),
            build_district("d4", population=0, consumption_rate=1.0, food=100.0),
            build_district("r", population=20, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("b1", "d1", "r"), ("b2", "d2", "r"), ("b3", "d3", "r"),
                    ("b4", "d4", "r")],
        law=build_law(),
        tick=1,
    )
    amounts = transfer_amounts(run_flow(world))

    assert abs(stocks(world, ResourceType.FOOD)["r"] - 20.0) <= FLOAT_TOLERANCE
    for donor in ("d1", "d2", "d3", "d4"):
        assert abs(amounts[(donor, "r")] - 5.0) <= FLOAT_TOLERANCE


def test_renaming_donors_does_not_change_who_bears_the_cost() -> None:
    """The defect made the outcome depend on identifier order; it must not.

    Two structurally identical worlds where the donor holding 30 is called 'aaa'
    in one and 'zzz' in the other. Mapped back by surplus, the contributions
    must match.
    """
    def build(small_donor_id: str, large_donor_id: str) -> dict[str, float]:
        """Run the scenario with the two donors named as given."""
        world = build_world(
            [
                build_district(small_donor_id, population=0, consumption_rate=1.0,
                               food=30.0),
                build_district(large_donor_id, population=0, consumption_rate=1.0,
                               food=70.0),
                build_district("receiver", population=20, consumption_rate=1.0, food=0.0),
            ],
            boundaries=[
                (f"b_{small_donor_id}", small_donor_id, "receiver"),
                (f"b_{large_donor_id}", large_donor_id, "receiver"),
            ],
            law=build_law(),
            tick=1,
        )
        amounts = transfer_amounts(run_flow(world))
        return {
            "small": amounts[(small_donor_id, "receiver")],
            "large": amounts[(large_donor_id, "receiver")],
        }

    small_sorts_first = build("aaa", "zzz")
    small_sorts_last = build("zzz", "aaa")

    assert abs(small_sorts_first["small"] - small_sorts_last["small"]) <= FLOAT_TOLERANCE
    assert abs(small_sorts_first["large"] - small_sorts_last["large"]) <= FLOAT_TOLERANCE
    assert abs(small_sorts_first["small"] - 6.0) <= FLOAT_TOLERANCE
    assert abs(small_sorts_first["large"] - 14.0) <= FLOAT_TOLERANCE


def test_registration_order_does_not_change_the_fair_split() -> None:
    """Reversing donor, receiver, and boundary registration changes nothing."""
    def build(reverse: bool):
        """Build the scenario, optionally reversing all registration orders."""
        districts = [
            build_district("d1", population=0, consumption_rate=1.0, food=40.0),
            build_district("d2", population=0, consumption_rate=1.0, food=60.0),
            build_district("r1", population=30, consumption_rate=1.0, food=0.0),
            build_district("r2", population=50, consumption_rate=1.0, food=0.0),
        ]
        boundaries = [
            ("b1", "d1", "r1"), ("b2", "d1", "r2"),
            ("b3", "d2", "r1"), ("b4", "d2", "r2"),
        ]
        if reverse:
            districts = list(reversed(districts))
            boundaries = list(reversed(boundaries))
        return build_world(districts, boundaries=boundaries, law=build_law(), tick=1)

    forward, backward = build(False), build(True)
    forward_log = run_flow(forward)
    backward_log = run_flow(backward)

    assert stocks(forward, ResourceType.FOOD) == stocks(backward, ResourceType.FOOD)
    assert [event.payload_as_dict() for event in forward_log] == [
        event.payload_as_dict() for event in backward_log
    ]


def test_constrained_graph_reaches_the_full_feasible_transfer() -> None:
    """d1-r1, d2-r1, d2-r2: fairness must not strand d1's surplus.

    A purely proportional split sends part of d2's surplus to r1, where d1 could
    have covered it alone, leaving d2 short for r2 -- which only d2 can reach --
    and stranding d1's remainder behind a receiver that is already full. The
    augmentation pass reroutes so that all 20 units of feasible demand are met.
    """
    world = build_world(
        [
            build_district("d1", population=0, consumption_rate=1.0, food=10.0),
            build_district("d2", population=0, consumption_rate=1.0, food=10.0),
            build_district("r1", population=10, consumption_rate=1.0, food=0.0),
            build_district("r2", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("b1", "d1", "r1"), ("b2", "d2", "r1"), ("b3", "d2", "r2")],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    result = stocks(world, ResourceType.FOOD)

    assert abs(result["r1"] - 10.0) <= FLOAT_TOLERANCE
    assert abs(result["r2"] - 10.0) <= FLOAT_TOLERANCE
    assert abs(result["d1"]) <= FLOAT_TOLERANCE
    assert abs(result["d2"]) <= FLOAT_TOLERANCE
    assert abs(total_of(world, ResourceType.FOOD) - 20.0) <= FLOAT_TOLERANCE


def test_dense_graph_respects_every_cap_and_strands_nothing() -> None:
    """Unequal donors, unequal receivers, several binding caps at once."""
    world = build_world(
        [
            build_district("d1", population=0, consumption_rate=1.0, food=15.0),
            build_district("d2", population=0, consumption_rate=1.0, food=45.0),
            build_district("d3", population=0, consumption_rate=1.0, food=5.0),
            build_district("r1", population=20, consumption_rate=1.0, food=0.0),
            build_district("r2", population=40, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[
            ("b1", "d1", "r1"), ("b2", "d1", "r2"),
            ("b3", "d2", "r1"), ("b4", "d2", "r2"),
            ("b5", "d3", "r1"), ("b6", "d3", "r2"),
        ],
        law=build_law(),
        tick=1,
    )
    log = run_flow(world)
    result = stocks(world, ResourceType.FOOD)
    amounts = transfer_amounts(log)

    # Total surplus 65 against total need 60: every receiver is satisfied.
    assert abs(result["r1"] - 20.0) <= FLOAT_TOLERANCE
    assert abs(result["r2"] - 40.0) <= FLOAT_TOLERANCE
    assert abs(total_of(world, ResourceType.FOOD) - 65.0) <= FLOAT_TOLERANCE

    for donor, surplus in (("d1", 15.0), ("d2", 45.0), ("d3", 5.0)):
        sent = sum(value for (source, _), value in amounts.items() if source == donor)
        assert sent <= surplus + FLOAT_TOLERANCE
    assert all(value >= 0.0 for value in result.values())

    ordering = [
        (str(event.payload["from_district_id"]), str(event.payload["to_district_id"]))
        for event in log.query(event_type=EventType.RESOURCE_TRANSFERRED)
    ]
    assert ordering == sorted(ordering)


def test_dense_graph_is_reproducible() -> None:
    """The dense case must give the same answer every time it is run."""
    def build():
        """Build the dense scenario fresh for each run."""
        return build_world(
            [
                build_district("d1", population=0, consumption_rate=1.0, food=15.0),
                build_district("d2", population=0, consumption_rate=1.0, food=45.0),
                build_district("r1", population=20, consumption_rate=1.0, food=0.0),
                build_district("r2", population=40, consumption_rate=1.0, food=0.0),
            ],
            boundaries=[("b1", "d1", "r1"), ("b2", "d1", "r2"),
                        ("b3", "d2", "r1"), ("b4", "d2", "r2")],
            law=build_law(),
            tick=1,
        )

    runs = []
    for _ in range(3):
        world = build()
        log = run_flow(world)
        runs.append((stocks(world, ResourceType.FOOD),
                     [event.payload_as_dict() for event in log]))
    assert runs[0] == runs[1] == runs[2]


def test_allocation_never_exceeds_donor_or_receiver_capacity() -> None:
    """The allocation module's caps, exercised directly across many shapes."""
    cases = [
        ({"d1": 100.0, "d2": 100.0}, {"r": 10.0},
         {"d1": {"r"}, "d2": {"r"}, "r": {"d1", "d2"}}),
        ({"d1": 1.0, "d2": 2.0, "d3": 3.0}, {"r1": 4.0, "r2": 4.0},
         {"d1": {"r1"}, "d2": {"r1", "r2"}, "d3": {"r2"},
          "r1": {"d1", "d2"}, "r2": {"d2", "d3"}}),
        ({"d1": 50.0}, {"r1": 10.0, "r2": 20.0, "r3": 30.0},
         {"d1": {"r1", "r2", "r3"}, "r1": {"d1"}, "r2": {"d1"}, "r3": {"d1"}}),
    ]

    for surplus, need, adjacency in cases:
        staged = allocate(surplus, need, adjacency)

        for donor, capacity in surplus.items():
            sent = sum(v for (source, _), v in staged.items() if source == donor)
            assert sent <= capacity + FLOAT_TOLERANCE

        for receiver, capacity in need.items():
            got = sum(v for (_, target), v in staged.items() if target == receiver)
            assert got <= capacity + FLOAT_TOLERANCE

        for (donor, receiver), amount in staged.items():
            assert amount > FLOAT_TOLERANCE
            assert receiver in adjacency[donor]


def test_allocation_leaves_no_usable_edge_unused() -> None:
    """No donor may hold surplus while a district it can reach still needs some."""
    surplus = {"d1": 12.0, "d2": 8.0, "d3": 30.0}
    need = {"r1": 15.0, "r2": 25.0, "r3": 5.0}
    adjacency = {
        "d1": {"r1", "r2"}, "d2": {"r2"}, "d3": {"r1", "r3"},
        "r1": {"d1", "d3"}, "r2": {"d1", "d2"}, "r3": {"d3"},
    }
    staged = allocate(surplus, need, adjacency)

    sent = {donor: 0.0 for donor in surplus}
    received = {receiver: 0.0 for receiver in need}
    for (donor, receiver), amount in staged.items():
        sent[donor] += amount
        received[receiver] += amount

    for donor in surplus:
        left = surplus[donor] - sent[donor]
        if left <= FLOAT_TOLERANCE:
            continue
        for receiver in adjacency[donor]:
            assert need[receiver] - received[receiver] <= FLOAT_TOLERANCE


def test_allocation_is_empty_when_either_side_is_missing() -> None:
    """No donors or no receivers means nothing to decide."""
    assert allocate({}, {"r": 5.0}, {"r": set()}) == {}
    assert allocate({"d": 5.0}, {}, {"d": set()}) == {}
    assert allocate({"d": 5.0}, {"r": 5.0}, {"d": set(), "r": set()}) == {}
