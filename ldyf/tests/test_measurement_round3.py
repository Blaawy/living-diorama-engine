"""Regression tests for the round-3 attacker's findings on the MEASUREMENT code.

Each test names the finding it locks. Integration tests need real SUMO and skip
cleanly without it.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from ldyf.closure import (
    ClosureError,
    ClosureSpec,
    count_post_closure_entries,
    output_is_complete,
    run_simulation,
    select_closable_lanes,
)
from ldyf.coords import normalise_deg
from ldyf.sumo_record import (
    FLOAT32_EXACT_CM_EXTENT,
    RecordError,
    _sha256_payload,
    build_record,
    payload_hash_mode,
    payload_span,
)

HEADER = ('<?xml version="1.0" encoding="UTF-8"?>\n\n'
          "<!-- generated on 2026-09-03T00:00:00+00:00 by Eclipse SUMO sumo 1.27.1\n"
          "<sumoConfiguration>cfg</sumoConfiguration>\n-->\n\n")


def fcd(timesteps):
    """timesteps: [(t, [(vid, lane, x, y), ...]), ...]"""
    s = HEADER + "<fcd-export>\n"
    for t, rows in timesteps:
        s += f'    <timestep time="{t:.2f}">\n'
        for vid, lane, x, y in rows:
            s += (f'        <vehicle id="{vid}" x="{x:.2f}" y="{y:.2f}" angle="90.00" type="T" '
                  f'speed="1.00" pos="0.00" lane="{lane}" slope="0.00"/>\n')
        s += "    </timestep>\n"
    return s + "</fcd-export>\n"


# --- finding 8: coords -----------------------------------------------------

def test_normalise_deg_zero_sign_is_canonical():
    for v in (-0.0, 0.0, 360.0, -360.0, 720.0):
        r = normalise_deg(v)
        assert r == 0.0
        assert struct.pack("<f", r) == struct.pack("<f", 0.0), f"{v} packed as negative zero"


@pytest.mark.parametrize("v", [1e6, -1e6, 1e9 + 45.0, -180.0, 180.0, 540.0])
def test_normalise_deg_huge_and_edge_values_stay_in_range(v):
    r = normalise_deg(v)
    assert -180.0 < r <= 180.0


# --- finding 3: output completeness ---------------------------------------

def test_output_is_complete_rejects_hand_closed_trimmed_file(tmp_path):
    full = fcd([(0.0, [("a", "E1_0", 1, 1)]), (0.1, [("a", "E1_0", 2, 1)]),
                (0.2, [("a", "E1_0", 3, 1)]), (0.3, [("a", "E1_0", 4, 1)]),
                (0.4, [("a", "E1_0", 5, 1)])])
    p = tmp_path / "full.xml"; p.write_text(full)
    assert output_is_complete(p, "fcd-export", expected_last_time=0.4)

    # cut at an element boundary (drop the last two whole timesteps) and hand-close
    cut = full[: full.index('    <timestep time="0.30"')] + "</fcd-export>\n"
    q = tmp_path / "cut.xml"; q.write_text(cut)
    assert output_is_complete(q, "fcd-export") is True, "structurally it looks complete..."
    assert output_is_complete(q, "fcd-export", expected_last_time=0.4) is False, \
        "...but the time span exposes the trim"


def test_output_is_complete_requires_closing_tag_to_be_last_token(tmp_path):
    p = tmp_path / "t.xml"
    p.write_text('<?xml version="1.0"?>\n<tripinfos>\n</tripinfos>\n<!-- </tripinfos> -->\n')
    assert output_is_complete(p, "tripinfos") is False


# --- finding 7: payload hashing --------------------------------------------

def test_payload_span_finds_only_a_leading_comment(tmp_path):
    a = tmp_path / "a.xml"; a.write_text(fcd([(0.0, [("a", "E1_0", 1, 1)])]))
    start, mode = payload_span(a.read_bytes())
    assert mode == "after_leading_comment"
    assert a.read_bytes()[start:].lstrip().startswith(b"<fcd-export>")


def test_payload_hash_mode_whole_file_when_header_absent(tmp_path):
    body = "<fcd-export>\n</fcd-export>\n"
    a = tmp_path / "a.xml"; a.write_text('<?xml version="1.0"?>\n' + body)
    assert payload_hash_mode(a) == "whole_file"


def test_payload_hash_ignores_only_the_leading_comment(tmp_path):
    base = fcd([(0.0, [("a", "E1_0", 1, 1)])])
    a = tmp_path / "a.xml"; a.write_text(base)
    b = tmp_path / "b.xml"; b.write_text(base.replace("2026-09-03T00:00:00", "2099-01-01T00:00:00"))
    assert _sha256_payload(a) == _sha256_payload(b)
    # a comment INSIDE the payload is content and must change the hash
    c = tmp_path / "c.xml"; c.write_text(base.replace("<fcd-export>\n", "<fcd-export>\n<!-- x -->\n"))
    assert _sha256_payload(a) != _sha256_payload(c)


# --- finding 6: float32 extent ---------------------------------------------

def test_float32_extent_guard(tmp_path):
    far = FLOAT32_EXACT_CM_EXTENT / 100.0 + 10.0        # metres, just past the limit
    p = tmp_path / "far.xml"; p.write_text(fcd([(0.0, [("a", "E1_0", far, 1)])]))
    with pytest.raises(RecordError, match="net offset"):
        build_record(p, tmp_path / "rec", step_seconds=0.1)


def test_float32_extent_recorded_in_manifest(tmp_path):
    p = tmp_path / "ok.xml"; p.write_text(fcd([(0.0, [("a", "E1_0", 600.0, 600.0)])]))
    build_record(p, tmp_path / "rec", step_seconds=0.1)
    man = json.loads((tmp_path / "rec" / "record_manifest.json").read_text())
    assert man["coordinate_system"]["float32_exact_cm_extent"] == FLOAT32_EXACT_CM_EXTENT
    assert man["source"]["fcd_payload_hash_mode"] == "after_leading_comment"


# --- finding 1: last_seen_time -----------------------------------------------

def test_manifest_records_last_seen_time(tmp_path):
    p = tmp_path / "t.xml"
    p.write_text(fcd([(0.0, [("a", "E1_0", 1, 1), ("b", "E1_0", 2, 2)]),
                      (0.1, [("b", "E1_0", 3, 2)]),
                      (0.2, [("b", "E1_0", 4, 2)])]))
    build_record(p, tmp_path / "rec", step_seconds=0.1)
    man = json.loads((tmp_path / "rec" / "record_manifest.json").read_text())
    by = {a["uid"]: a for a in man["actors"]}
    assert by["vehicle:a"]["last_seen_time"] == 0.0
    assert by["vehicle:b"]["last_seen_time"] == 0.2


# --- finding 2: post-closure entries measured from the FCD --------------------

def test_post_closure_entries_counter(tmp_path):
    p = tmp_path / "t.xml"
    p.write_text(fcd([
        (0.0, [("early", "B1C1_1", 1, 1), ("late", "A1B1_1", 5, 5)]),   # early is ON the closed edge before closure
        (1.0, [("early", "B1C1_1", 2, 1), ("late", "A1B1_1", 6, 5)]),   # closure fires at t=1.0
        (2.0, [("early", "C1D1_1", 3, 1), ("late", "B1C1_1", 7, 5)]),   # late ENTERS after closure -> 1
        (3.0, [("late", "B1C1_2", 8, 5)]),                               # still on it: not a new entry
    ]))
    entries, present = count_post_closure_entries(p, {"B1C1"}, fire_time=1.0)
    assert entries == 1
    assert present == 1          # 'early' was on the edge at the closure instant


def test_post_closure_entries_ignores_internal_lanes(tmp_path):
    p = tmp_path / "t.xml"
    p.write_text(fcd([(0.0, [("v", "A1B1_1", 1, 1)]), (2.0, [("v", ":B1_3_0", 2, 1)]),
                      (3.0, [("v", "B1C1_1", 3, 1)])]))
    entries, _ = count_post_closure_entries(p, {"B1C1"}, fire_time=1.0)
    assert entries == 1


# --- finding 5: shared lanes -------------------------------------------------

class _Lane:
    def __init__(self, lid, allowed):
        self._id, self._allowed = lid, set(allowed)
    def getID(self): return self._id
    def allows(self, c): return c in self._allowed


class _Edge:
    def __init__(self, eid, lanes):
        self._id, self._lanes = eid, lanes
    def getID(self): return self._id
    def getLanes(self): return self._lanes
    def getFunction(self): return ""


class _Net:
    def __init__(self, edges):
        self._edges = {e.getID(): e for e in edges}
    def getEdges(self): return list(self._edges.values())
    def getEdge(self, eid): return self._edges[eid]


def test_shared_lane_closure_is_refused_not_partial(monkeypatch):
    import ldyf.closure as cl
    net = _Net([_Edge("E", [_Lane("E_0", {"pedestrian"}),
                            _Lane("E_1", {"passenger", "pedestrian"}),   # shared
                            _Lane("E_2", {"passenger"})])])
    monkeypatch.setattr(cl.sumolib.net, "readNet", lambda *_a, **_k: net)
    with pytest.raises(ClosureError, match="shared"):
        select_closable_lanes("fake.net.xml", ["E"], ("passenger",))


def test_footway_and_carriageway_split_is_closed_correctly(monkeypatch):
    import ldyf.closure as cl
    net = _Net([_Edge("E", [_Lane("E_0", {"pedestrian"}), _Lane("E_1", {"passenger"}),
                            _Lane("E_2", {"passenger", "bus"})])])
    monkeypatch.setattr(cl.sumolib.net, "readNet", lambda *_a, **_k: net)
    assert select_closable_lanes("fake.net.xml", ["E"], ("passenger",)) == ["E_1", "E_2"]


# --- integration: the real closure holds ------------------------------------

PROOF_CANDIDATES = [
    Path(__file__).resolve().parents[3] / "evidence" / "simulation",
    Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY\PHASE_01\proof\sumo"),
]
PROOF = next((c for c in PROOF_CANDIDATES if (c / "grid.net.xml").exists()), PROOF_CANDIDATES[-1])
SUMO_BIN = Path(r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe")
needs_sumo = pytest.mark.skipif(not SUMO_BIN.exists() or not (PROOF / "grid.net.xml").exists(),
                                reason="SUMO or fixtures not present")


@needs_sumo
def test_real_closure_has_zero_post_closure_entries_and_records_teleports(tmp_path):
    spec = ClosureSpec(edge_ids=("B1C1", "C1B1"), at_second=60.0)
    r = run_simulation(sumo_binary=str(SUMO_BIN), net_path=PROOF / "grid.net.xml",
                       route_files=[PROOF / "veh.rou.xml", PROOF / "ped.rou.xml"],
                       out_dir=tmp_path, prefix="r3", seed=20260903, end_seconds=240.0,
                       closure=spec, port=55581)
    assert r.clean
    assert r.post_closure_entries_onto_closed_edges == 0, "a vehicle entered a closed edge"
    assert r.teleports >= 0
    assert r.reroute_requests == r.reroute_successes + r.reroute_failures
    assert r.routes_actually_changed + r.routes_unchanged == r.reroute_successes
