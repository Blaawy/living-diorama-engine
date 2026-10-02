"""Tests for PHASE 3 LANE 2: the four rule classes in ``ldyf/rules.py``.

Two layers:

* Offline tests run against a small hand-written SUMO net file and a recording
  fake TraCI connection. They need no live SUMO and no netconvert, only the
  ``sumolib`` parser that ``ldyf.closure`` already depends on.
* Net tests prove ``validate()`` and ``payload()`` against the REAL proof
  network. They are skipped cleanly when that file is absent.

``apply()`` is never allowed to start or configure SUMO: it is handed an
already-open connection. Here that connection is a recorder that captures the
calls, so the tests assert the exact TraCI command sequence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import sumolib

from ldyf.closure import DEFAULT_DISALLOW, ClosureError, select_closable_lanes
from ldyf.persistent_changes import CHANGE_TYPES, _validate_payload
from ldyf.rules import (
    EPISODE_END_SECONDS,
    ClosureRule,
    DemandFlowRule,
    RuleError,
    SpeedLimitRule,
    TrafficLightRule,
    _edge_reachable,
    _tls_programs,
    validate_rule_set,
)


# --------------------------------------------------------------------------
# Fixtures: the proof network (real) and a hand-written synthetic net (offline)
# --------------------------------------------------------------------------


def _find_proof_dir() -> Path:
    candidates = []
    env = os.environ.get("LDYF_PROOF_DIR")
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    # extracted MASTER: <root>/artifacts/ldyf/tests -> <root>/evidence/simulation
    candidates.append(here.parents[3] / "evidence" / "simulation")
    candidates.append(
        Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
        / "PHASE_01" / "proof" / "sumo"
    )
    for c in candidates:
        if (c / "grid.net.xml").exists():
            return c
    return candidates[-1]


PROOF = _find_proof_dir()
NET = PROOF / "grid.net.xml"
needs_net = pytest.mark.skipif(not NET.exists(), reason="proof network not present")


# A tiny network with a footway lane, a carriageway lane, one traffic light
# carrying two programmes, and one edge (E3) with no route to/from the others.
# Hand-written; never passes through netconvert.
SYNTH_NET = """<?xml version="1.0" encoding="UTF-8"?>
<!-- synthetic fixture for ldyf.rules tests: hand-written, never netconvert -->
<net version="1.20">
    <location netOffset="0.00,0.00" convBoundary="0.00,0.00,300.00,100.00" origBoundary="-10000000000.00,-10000000000.00,10000000000.00,10000000000.00" projParameter="!"/>
    <edge id="E1" from="J0" to="J1" priority="3">
        <lane id="E1_0" index="0" speed="13.89" length="100.00" width="2.00" allow="pedestrian" shape="0.00,6.40 100.00,6.40"/>
        <lane id="E1_1" index="1" speed="13.89" length="100.00" width="3.20" disallow="pedestrian" shape="0.00,0.00 100.00,0.00"/>
    </edge>
    <edge id="E2" from="J1" to="J0" priority="3">
        <lane id="E2_0" index="0" speed="13.89" length="100.00" width="2.00" allow="pedestrian" shape="100.00,9.60 0.00,9.60"/>
        <lane id="E2_1" index="1" speed="13.89" length="100.00" width="3.20" disallow="pedestrian" shape="100.00,3.20 0.00,3.20"/>
    </edge>
    <edge id="E3" from="J2" to="J2" priority="3">
        <lane id="E3_0" index="0" speed="13.89" length="10.00" width="3.20" disallow="pedestrian" shape="200.00,0.00 210.00,0.00"/>
    </edge>
    <tlLogic id="J1" type="static" programID="0" offset="0">
        <phase duration="30" state="GG"/>
        <phase duration="30" state="yy"/>
        <phase duration="30" state="rr"/>
    </tlLogic>
    <tlLogic id="J1" type="static" programID="rush" offset="0">
        <phase duration="20" state="GG"/>
    </tlLogic>
    <junction id="J0" type="priority" x="0.00" y="0.00" incLanes="E2_0 E2_1" intLanes="" shape="0.00,-2.00 2.00,-2.00 2.00,14.00 0.00,14.00"/>
    <junction id="J1" type="traffic_light" x="100.00" y="0.00" incLanes="E1_0 E1_1" intLanes="" shape="100.00,-2.00 102.00,-2.00 102.00,14.00 100.00,14.00"/>
    <junction id="J2" type="priority" x="200.00" y="0.00" incLanes="E3_0" intLanes=""/>
    <!-- sumolib's net parser reads attrs["state"] on a connection without a
         default, so omitting it raises KeyError before any rule is reached. -->
    <connection from="E1" to="E2" fromLane="1" toLane="1" dir="s" state="M"/>
</net>
"""


@pytest.fixture
def synth_net(tmp_path: Path) -> Path:
    p = tmp_path / "synth.net.xml"
    p.write_text(SYNTH_NET, encoding="utf-8")
    return p


# --------------------------------------------------------------------------
# A recording fake connection: apply() must only issue TraCI commands
# --------------------------------------------------------------------------


class _Domain:
    """A TraCI command domain that records every call made on it."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list = []

    def __getattr__(self, attr: str):
        def _call(*args, **kwargs):
            self.calls.append((f"{self.name}.{attr}", args, kwargs))
            return None

        return _call


class FakeConn:
    """Stands in for an object returned by ``traci`` after ``traci.init``."""

    def __init__(self) -> None:
        self.lane = _Domain("lane")
        self.edge = _Domain("edge")
        self.trafficlight = _Domain("trafficlight")
        self.route = _Domain("route")
        self.vehicle = _Domain("vehicle")

    def all_calls(self) -> list:
        out: list = []
        for d in (self.lane, self.edge, self.trafficlight, self.route, self.vehicle):
            out.extend(d.calls)
        return out


@dataclass
class RecordingResult:
    """A run result willing to keep a note of what was applied."""

    applied_changes: list = field(default_factory=list)
    lanes_closed: tuple = ()


# --------------------------------------------------------------------------
# Synthetic net sanity, and the closure rule's delegation to closure.py
# --------------------------------------------------------------------------


def test_synth_net_parses_and_has_a_carriageway_lane(synth_net):
    net = sumolib.net.readNet(str(synth_net))
    assert {e.getID() for e in net.getEdges()} >= {"E1", "E2", "E3"}
    # closure.py selects the carriageway lane and never the footway lane.
    assert select_closable_lanes(synth_net, ("E1",), DEFAULT_DISALLOW) == ["E1_1"]


def test_closure_rule_refuses_to_bar_pedestrians():
    """Delegation: closure.py's pedestrian guard is what raises, not a copy."""
    with pytest.raises(ClosureError):
        ClosureRule(rule_id="close_bridge", edge_ids=("E1",), disallow=("passenger", "pedestrian"))


def test_closure_rule_requires_at_least_one_edge():
    with pytest.raises(ClosureError):
        ClosureRule(rule_id="close_bridge", edge_ids=())


def test_closure_rule_validates_and_applies(synth_net):
    rule = ClosureRule(rule_id="close_bridge", edge_ids=("E1",), at_second=10.0)
    rule.validate(synth_net)
    assert rule.lanes() == ("E1_1",)

    conn = FakeConn()
    result = RecordingResult()
    rule.apply(conn, result)

    assert conn.lane.calls == [("lane.setDisallowed", ("E1_1", list(DEFAULT_DISALLOW)), {})]
    assert result.lanes_closed == ("E1_1",)
    assert result.applied_changes[0]["change_type"] == "edge_closure"
    assert result.applied_changes[0]["rule_id"] == "close_bridge"


def test_closure_rule_refuses_unknown_edge(synth_net):
    rule = ClosureRule(rule_id="close_bridge", edge_ids=("NO_SUCH_EDGE",))
    with pytest.raises(ClosureError):
        rule.validate(synth_net)


def test_closure_rule_apply_before_validate_is_refused():
    rule = ClosureRule(rule_id="close_bridge", edge_ids=("E1",))
    with pytest.raises(RuleError, match="validate"):
        rule.apply(FakeConn(), RecordingResult())


# --------------------------------------------------------------------------
# Speed limit
# --------------------------------------------------------------------------


def test_speed_limit_on_an_edge_validates_and_applies(synth_net):
    rule = SpeedLimitRule(rule_id="slow_edge", target_kind="edge", target_ids=("E1",), mps=8.33)
    rule.validate(synth_net)
    conn = FakeConn()
    rule.apply(conn, RecordingResult())
    assert conn.edge.calls == [("edge.setMaxSpeed", ("E1", 8.33), {})]


def test_speed_limit_on_a_lane_validates_and_applies(synth_net):
    rule = SpeedLimitRule(rule_id="slow_lane", target_kind="lane", target_ids=("E1_1",), mps=5.0)
    rule.validate(synth_net)
    conn = FakeConn()
    rule.apply(conn, RecordingResult())
    assert conn.lane.calls == [("lane.setMaxSpeed", ("E1_1", 5.0), {})]


def test_speed_limit_refuses_an_unknown_edge(synth_net):
    rule = SpeedLimitRule(rule_id="slow_edge", target_kind="edge", target_ids=("NO_SUCH_EDGE",), mps=5.0)
    with pytest.raises(RuleError, match="unknown edge"):
        rule.validate(synth_net)


def test_speed_limit_refuses_an_unknown_lane(synth_net):
    rule = SpeedLimitRule(rule_id="slow_lane", target_kind="lane", target_ids=("NO_SUCH_LANE",), mps=5.0)
    with pytest.raises(RuleError, match="unknown lane"):
        rule.validate(synth_net)


@pytest.mark.parametrize("mps", [-1.0, 0.0, float("nan"), float("inf"), float("-inf")])
def test_speed_limit_refuses_non_positive_or_non_finite_speeds(synth_net, mps):
    rule = SpeedLimitRule(rule_id="slow_edge", target_kind="edge", target_ids=("E1",), mps=mps)
    with pytest.raises(RuleError):
        rule.validate(synth_net)


def test_speed_limit_refuses_an_unknown_target_kind(synth_net):
    rule = SpeedLimitRule(rule_id="slow", target_kind="polygon", target_ids=("E1",), mps=5.0)
    with pytest.raises(RuleError, match="target_kind"):
        rule.validate(synth_net)


def test_speed_limit_requires_at_least_one_target(synth_net):
    rule = SpeedLimitRule(rule_id="slow", target_kind="edge", target_ids=(), mps=5.0)
    with pytest.raises(RuleError):
        rule.validate(synth_net)


# --------------------------------------------------------------------------
# Traffic-light programme
# --------------------------------------------------------------------------


def test_traffic_light_rule_validates_and_applies(synth_net):
    rule = TrafficLightRule(rule_id="rush_hour", tls_id="J1", program_id="rush")
    rule.validate(synth_net)
    conn = FakeConn()
    rule.apply(conn, RecordingResult())
    assert conn.trafficlight.calls == [("trafficlight.setProgram", ("J1", "rush"), {})]


def test_traffic_light_rule_applies_an_optional_phase(synth_net):
    rule = TrafficLightRule(rule_id="phase_two", tls_id="J1", program_id="0", phase_index=2)
    rule.validate(synth_net)
    conn = FakeConn()
    rule.apply(conn, RecordingResult())
    assert conn.trafficlight.calls == [
        ("trafficlight.setProgram", ("J1", "0"), {}),
        ("trafficlight.setPhase", ("J1", 2), {}),
    ]
    assert rule.payload()["phase_index"] == 2


def test_traffic_light_rule_refuses_an_unknown_tls(synth_net):
    rule = TrafficLightRule(rule_id="rush_hour", tls_id="NO_SUCH_TLS", program_id="0")
    with pytest.raises(RuleError, match="unknown traffic light"):
        rule.validate(synth_net)


def test_traffic_light_rule_refuses_a_program_the_tls_does_not_have(synth_net):
    rule = TrafficLightRule(rule_id="rush_hour", tls_id="J1", program_id="NO_SUCH_PROGRAM")
    with pytest.raises(RuleError, match="no program"):
        rule.validate(synth_net)


def test_traffic_light_rule_refuses_a_bad_phase_index(synth_net):
    rule = TrafficLightRule(rule_id="phase", tls_id="J1", program_id="0", phase_index=-1)
    with pytest.raises(RuleError, match="phase_index"):
        rule.validate(synth_net)


# --------------------------------------------------------------------------
# Demand flow
# --------------------------------------------------------------------------


def _flow(**overrides) -> DemandFlowRule:
    kwargs = dict(
        rule_id="rush", flow_id="f", from_edge="E1", to_edge="E2",
        vehicles_per_hour=3600.0, depart_begin=0.0, depart_end=10.0, vtype="car",
    )
    kwargs.update(overrides)
    return DemandFlowRule(**kwargs)


def test_demand_flow_validates_a_connected_route(synth_net):
    _flow().validate(synth_net)   # must not raise


def test_demand_flow_refuses_unknown_endpoints(synth_net):
    with pytest.raises(RuleError, match="from_edge"):
        _flow(from_edge="NO_SUCH_EDGE").validate(synth_net)
    with pytest.raises(RuleError, match="to_edge"):
        _flow(to_edge="NO_SUCH_EDGE").validate(synth_net)


def test_demand_flow_refuses_unconnected_endpoints(synth_net):
    # E3 is an isolated loop: no route from E1 to E3.
    with pytest.raises(RuleError, match="no route"):
        _flow(to_edge="E3").validate(synth_net)


def test_demand_flow_refuses_an_inverted_window(synth_net):
    with pytest.raises(RuleError, match="depart_end"):
        _flow(depart_begin=20.0, depart_end=10.0).validate(synth_net)


@pytest.mark.parametrize("rate", [-1.0, 0.0, float("nan"), float("inf")])
def test_demand_flow_refuses_a_bad_rate(synth_net, rate):
    with pytest.raises(RuleError):
        _flow(vehicles_per_hour=rate).validate(synth_net)


def test_demand_flow_vehicle_ids_are_flow_id_dot_index(synth_net):
    rule = _flow(vehicles_per_hour=3600.0, depart_begin=0.0, depart_end=5.0)
    rule.validate(synth_net)
    assert rule.vehicle_ids() == ("f.0", "f.1", "f.2", "f.3", "f.4")
    assert rule.departures() == (("f.0", 0.0), ("f.1", 1.0), ("f.2", 2.0),
                                 ("f.3", 3.0), ("f.4", 4.0))


def test_demand_flow_schedule_is_deterministic_and_not_clock_dependent(synth_net):
    a = _flow(vehicles_per_hour=1800.0, depart_begin=5.0, depart_end=15.0)
    b = _flow(vehicles_per_hour=1800.0, depart_begin=5.0, depart_end=15.0)
    # No reference to any clock: the same declaration always yields the same ids.
    assert a.vehicle_ids() == b.vehicle_ids()
    assert a.departures() == b.departures()
    assert all(vid.startswith("f.") for vid in a.vehicle_ids())


def test_demand_flow_applies_route_and_vehicles(synth_net):
    rule = _flow(vehicles_per_hour=3600.0, depart_begin=0.0, depart_end=3.0)
    rule.validate(synth_net)
    conn = FakeConn()
    result = RecordingResult()
    rule.apply(conn, result)
    assert conn.route.calls == [("route.add", ("f", ["E1", "E2"]), {})]
    assert conn.vehicle.calls == [
        ("vehicle.add", ("f.0", "f"), {"typeID": "car", "depart": 0.0}),
        ("vehicle.add", ("f.1", "f"), {"typeID": "car", "depart": 1.0}),
        ("vehicle.add", ("f.2", "f"), {"typeID": "car", "depart": 2.0}),
    ]
    assert result.applied_changes[0]["change_type"] == "demand_flow"


# --------------------------------------------------------------------------
# The episode horizon, and the ledger contract
# --------------------------------------------------------------------------


def test_a_rule_after_the_episode_end_is_refused(synth_net):
    rule = ClosureRule(rule_id="too_late", edge_ids=("E1",), at_second=EPISODE_END_SECONDS + 1.0)
    with pytest.raises(RuleError, match="episode end"):
        rule.validate(synth_net)


def test_change_types_are_admitted_by_the_ledger():
    assert ClosureRule(rule_id="c", edge_ids=("E1",)).change_type() == "edge_closure"
    assert SpeedLimitRule(rule_id="s", target_ids=("E1",), mps=5.0).change_type() == "speed_limit"
    assert TrafficLightRule(rule_id="t", tls_id="J1", program_id="0").change_type() == "traffic_light_program"
    assert _flow().change_type() == "demand_flow"
    for ct in ("edge_closure", "speed_limit", "traffic_light_program", "demand_flow"):
        assert ct in CHANGE_TYPES


def test_payloads_satisfy_the_ledger_payload_contract():
    # _validate_payload is exactly what the ledger runs on append and verify.
    _validate_payload("edge_closure", ClosureRule(rule_id="c", edge_ids=("E1",)).payload())
    _validate_payload("speed_limit", SpeedLimitRule(rule_id="s", target_ids=("E1",), mps=5.0).payload())
    _validate_payload("traffic_light_program",
                      TrafficLightRule(rule_id="t", tls_id="J1", program_id="0").payload())
    _validate_payload("demand_flow", _flow().payload())


# --------------------------------------------------------------------------
# validate_rule_set: contradictions must name BOTH rule ids
# --------------------------------------------------------------------------


def test_closure_and_speed_limit_on_one_edge_contradict():
    a = ClosureRule(rule_id="close_bridge", edge_ids=("E1",))
    b = SpeedLimitRule(rule_id="slow_bridge", target_kind="edge", target_ids=("E1",), mps=8.33)
    with pytest.raises(RuleError) as excinfo:
        validate_rule_set([a, b])
    message = str(excinfo.value)
    assert "close_bridge" in message and "slow_bridge" in message


def test_closure_and_a_lane_speed_limit_on_its_edge_contradict():
    a = ClosureRule(rule_id="close_bridge", edge_ids=("E1",))
    b = SpeedLimitRule(rule_id="slow_lane", target_kind="lane", target_ids=("E1_1",), mps=8.33)
    with pytest.raises(RuleError) as excinfo:
        validate_rule_set([a, b])
    assert "close_bridge" in str(excinfo.value) and "slow_lane" in str(excinfo.value)


def test_two_speed_limits_on_one_target_contradict():
    a = SpeedLimitRule(rule_id="slow_a", target_kind="edge", target_ids=("E1",), mps=8.33)
    b = SpeedLimitRule(rule_id="slow_b", target_kind="edge", target_ids=("E1",), mps=5.0)
    with pytest.raises(RuleError) as excinfo:
        validate_rule_set([a, b])
    assert "slow_a" in str(excinfo.value) and "slow_b" in str(excinfo.value)


def test_two_programs_for_one_tls_at_the_same_second_contradict():
    a = TrafficLightRule(rule_id="prog_a", tls_id="J1", program_id="0", at_second=10.0)
    b = TrafficLightRule(rule_id="prog_b", tls_id="J1", program_id="rush", at_second=10.0)
    with pytest.raises(RuleError) as excinfo:
        validate_rule_set([a, b])
    assert "prog_a" in str(excinfo.value) and "prog_b" in str(excinfo.value)


def test_two_programs_for_one_tls_at_different_seconds_are_compatible():
    a = TrafficLightRule(rule_id="prog_a", tls_id="J1", program_id="0", at_second=10.0)
    b = TrafficLightRule(rule_id="prog_b", tls_id="J1", program_id="rush", at_second=20.0)
    validate_rule_set([a, b])   # must not raise


def test_three_simultaneous_compatible_rules_pass(synth_net):
    closure = ClosureRule(rule_id="close_bridge", edge_ids=("E1",), at_second=10.0)
    speed = SpeedLimitRule(rule_id="slow_other", target_kind="edge", target_ids=("E2",), mps=8.33)
    light = TrafficLightRule(rule_id="rush_hour", tls_id="J1", program_id="0", at_second=10.0)
    validate_rule_set([closure, speed, light])   # must not raise
    for rule in (closure, speed, light):
        rule.validate(synth_net)


def test_every_apply_only_touches_its_own_traci_domain(synth_net):
    """apply() must not start, stop or configure SUMO -- only issue the change."""
    conn = FakeConn()
    rules = [
        ClosureRule(rule_id="close_bridge", edge_ids=("E1",)),
        SpeedLimitRule(rule_id="slow", target_kind="edge", target_ids=("E2",), mps=8.33),
        TrafficLightRule(rule_id="rush_hour", tls_id="J1", program_id="0"),
        _flow(vehicles_per_hour=3600.0, depart_begin=0.0, depart_end=2.0),
    ]
    for rule in rules:
        rule.validate(synth_net)
        rule.apply(conn, RecordingResult())
    names = [name for name, _, _ in conn.all_calls()]
    assert names, "apply recorded no commands"
    forbidden = ("simulation", "start", "close", "init", "step", "load", "setConfig")
    assert not [n for n in names for f in forbidden if f in n]


# --------------------------------------------------------------------------
# Against the REAL proof network (read-only)
# --------------------------------------------------------------------------


def _real_net():
    return sumolib.net.readNet(str(NET))


def _first_closable_edge() -> str | None:
    net = _real_net()
    for eid in sorted(e.getID() for e in net.getEdges()):
        try:
            select_closable_lanes(NET, (eid,), DEFAULT_DISALLOW)
            return eid
        except Exception:
            continue
    return None


def _first_connected_pair():
    net = _real_net()
    for a in sorted(e.getID() for e in net.getEdges()):
        outs = sorted(o.getID() for o in net.getEdge(a).getOutgoing())
        if outs:
            return a, outs[0]
    return None


def _first_unconnected_pair():
    net = _real_net()
    edges = sorted(e.getID() for e in net.getEdges())
    for a in edges:
        for b in edges:
            if a != b and not _edge_reachable(net, a, b):
                return a, b
    return None


@needs_net
def test_real_net_closure_rule_validates_and_refuses_unknown_edge():
    edge = _first_closable_edge()
    if edge is None:
        pytest.skip("proof network has no closable carriageway edge")
    rule = ClosureRule(rule_id="close", edge_ids=(edge,), at_second=60.0)
    rule.validate(NET)
    assert rule.payload() == {
        "kind": "edge_closure", "edge_ids": [edge], "disallow": list(DEFAULT_DISALLOW)
    }
    with pytest.raises(ClosureError):
        ClosureRule(rule_id="close", edge_ids=("NO_SUCH_EDGE_XYZ",)).validate(NET)


@needs_net
def test_real_net_speed_limit_validates_and_refuses_unknown_target():
    net = _real_net()
    edge = sorted(e.getID() for e in net.getEdges())[0]
    rule = SpeedLimitRule(rule_id="slow", target_kind="edge", target_ids=(edge,), mps=8.33)
    rule.validate(NET)
    assert rule.payload()["target_ids"] == [edge]
    with pytest.raises(RuleError, match="unknown edge"):
        SpeedLimitRule(rule_id="slow", target_kind="edge",
                       target_ids=("NO_SUCH_EDGE_XYZ",), mps=8.33).validate(NET)


@needs_net
def test_real_net_traffic_light_programme_is_checked_against_the_tls():
    programs = _tls_programs(NET)
    if programs:
        tls_id = sorted(programs)[0]
        program_id = sorted(programs[tls_id])[0]
        rule = TrafficLightRule(rule_id="tls", tls_id=tls_id, program_id=program_id)
        rule.validate(NET)
        assert rule.payload()["program_id"] == program_id
        with pytest.raises(RuleError, match="no program"):
            TrafficLightRule(rule_id="tls", tls_id=tls_id, program_id="NO_SUCH_PROGRAM").validate(NET)
    with pytest.raises(RuleError, match="unknown traffic light"):
        TrafficLightRule(rule_id="tls", tls_id="NO_SUCH_TLS", program_id="0").validate(NET)


@needs_net
def test_real_net_demand_flow_route_is_checked():
    pair = _first_connected_pair()
    if pair is None:
        pytest.skip("proof network has no connected edge pair")
    a, b = pair
    _flow(from_edge=a, to_edge=b).validate(NET)
    unconnected = _first_unconnected_pair()
    if unconnected is not None:
        ua, ub = unconnected
        with pytest.raises(RuleError, match="no route"):
            _flow(from_edge=ua, to_edge=ub).validate(NET)


@needs_net
def test_real_net_refuses_a_rule_after_the_episode_end():
    edge = _first_closable_edge()
    if edge is None:
        pytest.skip("proof network has no closable carriageway edge")
    rule = ClosureRule(rule_id="too_late", edge_ids=(edge,), at_second=EPISODE_END_SECONDS + 1.0)
    with pytest.raises(RuleError, match="episode end"):
        rule.validate(NET)
