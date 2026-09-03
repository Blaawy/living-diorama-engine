"""Regression tests for RISK-1: road closure in a world containing pedestrians.

SUMO 1.27.1 crashes when `<closingReroute>` is active and pedestrians are
present. These tests lock in the replacement architecture: a TraCI-authoritative
lane-level closure that structurally cannot touch a footway.

The integration tests run real SUMO. They are the point of the file -- a unit
test alone cannot prove the simulator does not crash.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ldyf.closure import (
    DEFAULT_DISALLOW,
    ClosureError,
    ClosureSpec,
    assert_pedestrian_access_preserved,
    output_is_complete,
    run_simulation,
    select_closable_lanes,
    summarise_tripinfo,
)

PROOF = Path(
    r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY\PHASE_01\proof\sumo"
)
NET = PROOF / "grid.net.xml"
VEH = PROOF / "veh.rou.xml"
PED = PROOF / "ped.rou.xml"
SUMO_BIN = r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe"

needs_net = pytest.mark.skipif(not NET.exists(), reason="proof network not present")
needs_sumo = pytest.mark.skipif(
    not Path(SUMO_BIN).exists() or not NET.exists(), reason="SUMO or network not present"
)


# --- the structural guarantee --------------------------------------------

def test_a_closure_may_never_bar_pedestrians():
    """The bug class, made unrepresentable."""
    with pytest.raises(ClosureError, match="footway"):
        ClosureSpec(edge_ids=("B1C1",), disallow=("passenger", "pedestrian"))


def test_closure_requires_at_least_one_edge():
    with pytest.raises(ClosureError):
        ClosureSpec(edge_ids=())


def test_negative_time_refused():
    with pytest.raises(ClosureError):
        ClosureSpec(edge_ids=("B1C1",), at_second=-1.0)


@needs_net
def test_selected_lanes_are_never_footways():
    lanes = select_closable_lanes(NET, ("B1C1", "C1B1"), DEFAULT_DISALLOW)
    assert lanes, "expected some closable carriageway lanes"
    # lane _0 on each edge is the sidewalk and must be absent
    assert "B1C1_0" not in lanes
    assert "C1B1_0" not in lanes
    assert_pedestrian_access_preserved(NET, lanes)


@needs_net
def test_selected_lanes_are_sorted_and_stable():
    a = select_closable_lanes(NET, ("C1B1", "B1C1"), DEFAULT_DISALLOW)
    b = select_closable_lanes(NET, ("B1C1", "C1B1"), DEFAULT_DISALLOW)
    assert a == b == sorted(a), "lane order must not depend on argument order"


@needs_net
def test_pedestrian_guard_rejects_a_footway():
    """Guard against the guard being vacuous."""
    with pytest.raises(ClosureError):
        assert_pedestrian_access_preserved(NET, ["B1C1_0"])


@needs_net
def test_unknown_edge_is_refused():
    with pytest.raises(ClosureError, match="not in network"):
        select_closable_lanes(NET, ("NO_SUCH_EDGE",), DEFAULT_DISALLOW)


# --- output integrity (the red team's law) --------------------------------

def test_truncated_output_is_detected(tmp_path):
    """A crashed SUMO leaves a truncated file and an empty stderr."""
    good = tmp_path / "good.xml"
    good.write_text('<?xml version="1.0"?>\n<tripinfos>\n  <tripinfo id="1"/>\n</tripinfos>\n')
    assert output_is_complete(good, "tripinfos")

    bad = tmp_path / "bad.xml"
    bad.write_text('<?xml version="1.0"?>\n<tripinfos>\n  <tripinfo id="1"/>\n')
    assert not output_is_complete(bad, "tripinfos")

    empty = tmp_path / "empty.xml"
    empty.write_text("")
    assert not output_is_complete(empty, "tripinfos")

    assert not output_is_complete(tmp_path / "missing.xml", "tripinfos")


def test_the_real_crash_artifact_is_rejected():
    """The actual truncated file left by the RISK-1 crash must fail the check."""
    artifact = PROOF / "risk1_repro.tripinfo.xml"
    if not artifact.exists():
        pytest.skip("crash artifact not retained")
    assert not output_is_complete(artifact, "tripinfos")


# --- integration: the crash must not come back ----------------------------

@needs_sumo
def test_closure_with_pedestrians_exits_cleanly(tmp_path):
    """RISK-1 regression. 500 vehicles + 200 pedestrians + a real closure.

    This is the test that would have caught the original architecture: with
    `<closingReroute>` SUMO exits 0xC0000005 and leaves a truncated file.
    """
    spec = ClosureSpec(edge_ids=("B1C1", "C1B1"), at_second=60.0)
    r = run_simulation(
        sumo_binary=SUMO_BIN, net_path=NET, route_files=[VEH, PED],
        out_dir=tmp_path, prefix="reg", seed=20260903,
        end_seconds=240.0, closure=spec, port=55571,
    )
    assert r.exit_code == 0, f"SUMO did not exit cleanly: {r.exit_code}"
    assert all(r.outputs_valid.values()), f"truncated outputs: {r.outputs_valid}"
    assert r.closure_applied_at_step == 600
    assert r.lanes_closed, "no lanes were actually closed"
    assert r.reroute_failures == 0


@needs_sumo
def test_pedestrians_still_walk_after_the_closure(tmp_path):
    """Closing the carriageway must not strand people on the footway."""
    spec = ClosureSpec(edge_ids=("B1C1", "C1B1"), at_second=60.0)
    r = run_simulation(
        sumo_binary=SUMO_BIN, net_path=NET, route_files=[VEH, PED],
        out_dir=tmp_path, prefix="ped", seed=20260903,
        end_seconds=240.0, closure=spec, port=55572,
    )
    assert r.exit_code == 0
    m = summarise_tripinfo(tmp_path / "ped.tripinfo.xml")
    assert m["walks_completed"] > 0, "pedestrians stopped completing walks"
    assert m["avg_walk_length_m"] > 0, "walk distances lost (attribute stripping bug)"


@needs_sumo
def test_closure_actually_reroutes_traffic(tmp_path):
    """A closure that changes nothing is not a closure."""
    spec = ClosureSpec(edge_ids=("B1C1", "C1B1"), at_second=60.0)
    r = run_simulation(
        sumo_binary=SUMO_BIN, net_path=NET, route_files=[VEH, PED],
        out_dir=tmp_path, prefix="rr", seed=20260903,
        end_seconds=240.0, closure=spec, port=55573,
    )
    assert r.vehicles_rerouted > 0, "no vehicle was rerouted by the closure"


@needs_sumo
def test_closure_run_is_deterministic(tmp_path):
    """Same seed, same closure, byte-identical trajectory payload."""
    import hashlib

    def payload(p: Path) -> str:
        d = p.read_bytes()
        i = d.find(b"-->")
        return hashlib.sha256(d[i + 3 :] if i != -1 else d).hexdigest()

    spec = ClosureSpec(edge_ids=("B1C1", "C1B1"), at_second=60.0)
    common = dict(
        sumo_binary=SUMO_BIN, net_path=NET, route_files=[VEH, PED],
        out_dir=tmp_path, seed=20260903, end_seconds=180.0, closure=spec,
    )
    a = run_simulation(prefix="d1", port=55574, **common)
    b = run_simulation(prefix="d2", port=55575, **common)
    assert a.exit_code == 0 and b.exit_code == 0
    assert a.vehicles_rerouted == b.vehicles_rerouted
    assert payload(tmp_path / "d1.fcd.xml") == payload(tmp_path / "d2.fcd.xml")


@needs_sumo
def test_baseline_arm_applies_no_closure(tmp_path):
    r = run_simulation(
        sumo_binary=SUMO_BIN, net_path=NET, route_files=[VEH, PED],
        out_dir=tmp_path, prefix="base", seed=20260903,
        end_seconds=180.0, closure=None, port=55576,
    )
    assert r.exit_code == 0
    assert r.closure_applied_at_step is None
    assert r.lanes_closed == ()
    assert r.vehicles_rerouted == 0


# --- summariser -----------------------------------------------------------

def test_summarise_keeps_walk_attributes(tmp_path):
    """Regression: ElementTree clear() strips attributes off children.

    Clearing a <walk> on its own end event blanked it before its parent
    <personinfo> was read, so every walk length reported as 0.0.
    """
    p = tmp_path / "t.xml"
    p.write_text(
        '<?xml version="1.0"?>\n<tripinfos>\n'
        '  <tripinfo id="v1" duration="10" routeLength="100" waitingTime="1" timeLoss="2"/>\n'
        '  <personinfo id="p1">\n'
        '    <walk depart="0" arrival="50" duration="50" routeLength="250"/>\n'
        "  </personinfo>\n"
        "</tripinfos>\n"
    )
    m = summarise_tripinfo(p)
    assert m["trips_completed"] == 1
    assert m["walks_completed"] == 1
    assert m["avg_walk_length_m"] == 250.0
    assert m["avg_walk_duration_s"] == 50.0
