"""Tests for how ResourceFlowSystem divides surplus among competing districts.

Fairness here is not an aesthetic preference: if allocation depended on which
boundary sorted first, the same world would evolve differently for reasons no
viewer could ever be shown. These tests fix the outcome against topology and
inputs alone.
"""

from living_diorama.entities import ResourceType
from living_diorama.events import EventBus, EventLog
from living_diorama.systems import ResourceFlowSystem
from living_diorama.systems._resource_config import FLOAT_TOLERANCE
from systems_builders import (
    EVEN_ALLOCATION,
    FOOD_ONLY_ALLOCATION,
    LAW_ID,
    build_district,
    build_law,
    build_world,
    stocks,
    total_of,
)


def build_flow(reserve_ticks: float = 1.0, allocation=FOOD_ONLY_ALLOCATION):
    """Build a flow system that reserves food only, to keep arithmetic legible."""
    return ResourceFlowSystem(
        law_id=LAW_ID, consumption_allocation=allocation, reserve_ticks=reserve_ticks
    )


def run_flow(world, flow=None) -> EventLog:
    """Run one flow update and return the event log."""
    bus, log = EventBus(), EventLog()
    bus.subscribe(log.append)
    (flow or build_flow()).update(world, bus)
    return log


def test_one_donor_one_receiver() -> None:
    """The simplest case: surplus meets need across a single boundary."""
    world = build_world(
        [
            build_district("a", population=0, consumption_rate=1.0, food=30.0),
            build_district("b", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("ab", "a", "b")],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    assert stocks(world, ResourceType.FOOD) == {"a": 20.0, "b": 10.0}


def test_one_donor_splits_proportionally_between_receivers() -> None:
    """A donor short of total demand splits in proportion to each need."""
    world = build_world(
        [
            build_district("donor", population=0, consumption_rate=1.0, food=30.0),
            build_district("r_big", population=60, consumption_rate=1.0, food=0.0),
            build_district("r_small", population=20, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("d_big", "donor", "r_big"), ("d_small", "donor", "r_small")],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    result = stocks(world, ResourceType.FOOD)

    # Needs are 60 and 20; the donor's 30 splits 3:1.
    assert abs(result["r_big"] - 22.5) <= FLOAT_TOLERANCE
    assert abs(result["r_small"] - 7.5) <= FLOAT_TOLERANCE
    assert abs(result["donor"]) <= FLOAT_TOLERANCE


def test_receiver_ordering_does_not_bias_allocation() -> None:
    """The lexicographically first receiver must not simply take everything."""
    world = build_world(
        [
            build_district("donor", population=0, consumption_rate=1.0, food=30.0),
            build_district("aaa", population=60, consumption_rate=1.0, food=0.0),
            build_district("zzz", population=20, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("d_a", "donor", "aaa"), ("d_z", "donor", "zzz")],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    result = stocks(world, ResourceType.FOOD)

    assert abs(result["aaa"] - 22.5) <= FLOAT_TOLERANCE
    assert abs(result["zzz"] - 7.5) <= FLOAT_TOLERANCE


def test_shared_receiver_is_never_overfilled() -> None:
    """Two donors feeding one receiver must not push it past its original need."""
    world = build_world(
        [
            build_district("d1", population=0, consumption_rate=1.0, food=100.0),
            build_district("d2", population=0, consumption_rate=1.0, food=100.0),
            build_district("r", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("d1r", "d1", "r"), ("d2r", "d2", "r")],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    result = stocks(world, ResourceType.FOOD)

    assert abs(result["r"] - 10.0) <= FLOAT_TOLERANCE
    assert abs(total_of(world, ResourceType.FOOD) - 200.0) <= FLOAT_TOLERANCE


def test_multiple_donors_and_receivers_stay_deterministic() -> None:
    """A denser graph must still produce one fixed answer."""

    def make_world():
        """Build the scenario world fresh for each run."""
        return build_world(
            [
                build_district("d1", population=0, consumption_rate=1.0, food=40.0),
                build_district("d2", population=0, consumption_rate=1.0, food=40.0),
                build_district("r1", population=30, consumption_rate=1.0, food=0.0),
                build_district("r2", population=50, consumption_rate=1.0, food=0.0),
            ],
            boundaries=[
                ("d1r1", "d1", "r1"),
                ("d1r2", "d1", "r2"),
                ("d2r1", "d2", "r1"),
                ("d2r2", "d2", "r2"),
            ],
            law=build_law(),
            tick=1,
        )

    first, second = make_world(), make_world()
    first_log = run_flow(first)
    second_log = run_flow(second)

    assert stocks(first, ResourceType.FOOD) == stocks(second, ResourceType.FOOD)
    assert [event.payload_as_dict() for event in first_log] == [
        event.payload_as_dict() for event in second_log
    ]
    assert abs(total_of(first, ResourceType.FOOD) - 80.0) <= FLOAT_TOLERANCE


def test_district_insertion_order_does_not_change_results() -> None:
    """Every traversal is sorted, so registration order is irrelevant."""
    districts = [
        build_district("d1", population=0, consumption_rate=1.0, food=40.0),
        build_district("r1", population=30, consumption_rate=1.0, food=0.0),
        build_district("r2", population=50, consumption_rate=1.0, food=0.0),
    ]
    boundaries = [("d1r1", "d1", "r1"), ("d1r2", "d1", "r2")]

    forward = build_world(districts, boundaries=boundaries, law=build_law(), tick=1)
    reversed_districts = [
        build_district("r2", population=50, consumption_rate=1.0, food=0.0),
        build_district("r1", population=30, consumption_rate=1.0, food=0.0),
        build_district("d1", population=0, consumption_rate=1.0, food=40.0),
    ]
    backward = build_world(
        reversed_districts, boundaries=list(reversed(boundaries)), law=build_law(), tick=1
    )

    run_flow(forward)
    run_flow(backward)
    assert stocks(forward, ResourceType.FOOD) == stocks(backward, ResourceType.FOOD)


def test_donor_never_exceeds_original_surplus_across_many_receivers() -> None:
    """Caps are absolute: a donor cannot give away more than it had spare."""
    world = build_world(
        [
            build_district("donor", population=10, consumption_rate=1.0, food=30.0),
            build_district("r1", population=40, consumption_rate=1.0, food=0.0),
            build_district("r2", population=40, consumption_rate=1.0, food=0.0),
            build_district("r3", population=40, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("b1", "donor", "r1"), ("b2", "donor", "r2"), ("b3", "donor", "r3")],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    result = stocks(world, ResourceType.FOOD)

    # The donor reserves 10 and shares the remaining 20, split evenly three ways.
    assert abs(result["donor"] - 10.0) <= FLOAT_TOLERANCE
    for receiver in ("r1", "r2", "r3"):
        assert abs(result[receiver] - 20.0 / 3.0) <= FLOAT_TOLERANCE
    assert abs(total_of(world, ResourceType.FOOD) - 30.0) <= FLOAT_TOLERANCE


def test_a_district_may_donate_one_resource_while_needing_another() -> None:
    """Roles are decided per resource, not per district."""
    world = build_world(
        [
            build_district("a", population=10, consumption_rate=1.0, food=100.0,
                           materials=0.0),
            build_district("b", population=10, consumption_rate=1.0, food=0.0,
                           materials=100.0),
        ],
        boundaries=[("ab", "a", "b")],
        law=build_law(),
        tick=1,
    )
    run_flow(world, build_flow(allocation=EVEN_ALLOCATION))

    # Food weight 0.5 -> reserve 5 each; materials weight 0.3 -> reserve 3 each.
    assert stocks(world, ResourceType.FOOD)["b"] == 5.0
    assert stocks(world, ResourceType.MATERIALS)["a"] == 3.0


def test_newly_received_stock_is_not_forwarded_in_the_same_tick() -> None:
    """A ↔ B ↔ C: what B receives this tick cannot reach C until the next one."""
    world = build_world(
        [
            build_district("a", population=0, consumption_rate=1.0, food=100.0),
            build_district("b", population=10, consumption_rate=1.0, food=0.0),
            build_district("c", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("ab", "a", "b"), ("bc", "b", "c")],
        law=build_law(),
        tick=1,
    )
    log = run_flow(world)
    result = stocks(world, ResourceType.FOOD)

    assert result["b"] == 10.0
    assert result["c"] == 0.0
    assert all(event.payload["from_district_id"] == "a" for event in log)


def test_multi_hop_flow_emerges_over_successive_ticks() -> None:
    """Multi-hop movement is a consequence of time passing, not of one update."""
    world = build_world(
        [
            build_district("a", population=0, consumption_rate=1.0, food=100.0),
            build_district("b", population=10, consumption_rate=1.0, food=0.0),
            build_district("c", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("ab", "a", "b"), ("bc", "b", "c")],
        law=build_law(),
        tick=1,
    )
    flow = build_flow()
    run_flow(world, flow)
    assert stocks(world, ResourceType.FOOD)["c"] == 0.0

    # b now sits at its reserve, so it still has nothing spare for c: the chain
    # only moves once b is pushed above its own reserve.
    world.advance_tick()
    run_flow(world, flow)
    assert stocks(world, ResourceType.FOOD)["c"] == 0.0
    assert abs(total_of(world, ResourceType.FOOD) - 100.0) <= FLOAT_TOLERANCE


def test_identical_topology_and_inputs_yield_identical_transfers() -> None:
    """The determinism guarantee, stated directly."""

    def make_world():
        """Build the scenario world fresh for each run."""
        return build_world(
            [
                build_district("alpha", population=0, consumption_rate=1.0, food=17.0),
                build_district("bravo", population=13, consumption_rate=1.0, food=1.0),
                build_district("delta", population=7, consumption_rate=1.0, food=0.0),
            ],
            boundaries=[("ab", "alpha", "bravo"), ("ad", "alpha", "delta")],
            law=build_law(),
            tick=1,
        )

    runs = []
    for _ in range(3):
        world = make_world()
        log = run_flow(world)
        runs.append(
            (stocks(world, ResourceType.FOOD),
             [event.payload_as_dict() for event in log])
        )

    assert runs[0] == runs[1] == runs[2]


def test_duplicate_donor_receiver_connections_do_not_increase_allocation() -> None:
    """Extra parallel boundaries describe the same connection, not more capacity."""
    def make_world(boundaries):
        """Build the scenario with a chosen set of boundaries."""
        return build_world(
            [
                build_district("a", population=0, consumption_rate=1.0, food=100.0),
                build_district("b", population=10, consumption_rate=1.0, food=0.0),
                build_district("c", population=10, consumption_rate=1.0, food=0.0),
            ],
            boundaries=boundaries,
            law=build_law(),
            tick=1,
        )

    single = make_world([("ab", "a", "b"), ("ac", "a", "c")])
    doubled = make_world(
        [("ab", "a", "b"), ("ab2", "a", "b"), ("ac", "a", "c"), ("ac2", "a", "c")]
    )
    run_flow(single)
    run_flow(doubled)

    assert stocks(single, ResourceType.FOOD) == stocks(doubled, ResourceType.FOOD)


def test_donor_with_more_surplus_than_total_need_fills_everyone_and_keeps_the_rest() -> None:
    """When surplus exceeds total demand, every cap binds and the donor keeps the remainder."""
    world = build_world(
        [
            build_district("donor", population=0, consumption_rate=1.0, food=30.0),
            build_district("small", population=1, consumption_rate=1.0, food=0.0),
            build_district("large", population=2, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("ds", "donor", "small"), ("dl", "donor", "large")],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    result = stocks(world, ResourceType.FOOD)

    assert abs(result["small"] - 1.0) <= FLOAT_TOLERANCE
    assert abs(result["large"] - 2.0) <= FLOAT_TOLERANCE
    assert abs(result["donor"] - 27.0) <= FLOAT_TOLERANCE


def test_proportional_split_is_not_capped_when_surplus_is_scarce() -> None:
    """With demand exceeding surplus, each receiver gets its exact proportional share."""
    world = build_world(
        [
            build_district("donor", population=0, consumption_rate=1.0, food=30.0),
            build_district("small", population=1, consumption_rate=1.0, food=0.0),
            build_district("large", population=100, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[("ds", "donor", "small"), ("dl", "donor", "large")],
        law=build_law(),
        tick=1,
    )
    run_flow(world)
    result = stocks(world, ResourceType.FOOD)

    assert abs(result["small"] - 30.0 * 1.0 / 101.0) <= FLOAT_TOLERANCE
    assert abs(result["large"] - 30.0 * 100.0 / 101.0) <= FLOAT_TOLERANCE
    assert abs(result["donor"]) <= FLOAT_TOLERANCE


def test_staging_terminates_and_a_second_update_moves_nothing_further() -> None:
    """The round loop must settle: once allocated, an immediate rerun is a no-op."""
    world = build_world(
        [
            build_district("d1", population=0, consumption_rate=1.0, food=5.0),
            build_district("d2", population=0, consumption_rate=1.0, food=100.0),
            build_district("r1", population=10, consumption_rate=1.0, food=0.0),
            build_district("r2", population=10, consumption_rate=1.0, food=0.0),
        ],
        boundaries=[
            ("d1r1", "d1", "r1"),
            ("d2r1", "d2", "r1"),
            ("d2r2", "d2", "r2"),
        ],
        law=build_law(),
        tick=1,
    )
    flow = build_flow()
    run_flow(world, flow)
    settled = stocks(world, ResourceType.FOOD)

    assert abs(settled["r1"] - 10.0) <= FLOAT_TOLERANCE
    assert abs(settled["r2"] - 10.0) <= FLOAT_TOLERANCE

    world.advance_tick()
    second_log = run_flow(world, flow)
    assert len(second_log) == 0
    assert stocks(world, ResourceType.FOOD) == settled
