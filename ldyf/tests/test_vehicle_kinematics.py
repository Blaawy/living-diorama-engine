"""Tests for ldyf.vehicle_kinematics: wheel maths, spawn/despawn windows and
heading-from-motion checks (Phase 2 gate item 4: "believable vehicles").

Unit conversions in these tests go through ldyf.coords.METRES_TO_UNREAL_UNITS
-- no calculator literal is typed anywhere. Synthetic records are written to
tmp_path with the same SAMPLE_STRUCT/COUNT_STRUCT layout sumo_record declares,
so these tests exercise the real binary format.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ldyf.coords import METRES_TO_UNREAL_UNITS, normalise_deg
from ldyf.sumo_record import COUNT_STRUCT, SAMPLE_STRUCT
from ldyf.vehicle_kinematics import (
    check_wheel_rate,
    heading_from_motion,
    spawn_windows,
    visibility_plan,
    wheel_angle_deg,
    wheel_rate_deg_per_s,
    yaw_consistency,
)


# --- wheel rate ------------------------------------------------------------

def test_wheel_rate_matches_formula_computed_with_constant():
    """r = 30 cm at 10 m/s, expected value computed here, not typed."""
    v, r = 10.0, 30.0
    expected = 360.0 * (v * METRES_TO_UNREAL_UNITS) / (2.0 * math.pi * r)
    assert wheel_rate_deg_per_s(v, r) == pytest.approx(expected)


def test_wheel_rate_zero_speed_is_zero():
    assert wheel_rate_deg_per_s(0.0, 30.0) == 0.0


def test_wheel_rate_rejects_non_positive_radius():
    with pytest.raises(ValueError):
        wheel_rate_deg_per_s(10.0, 0.0)
    with pytest.raises(ValueError):
        wheel_rate_deg_per_s(10.0, -30.0)


def test_check_wheel_rate_passes_at_four_percent_error():
    v, r = 10.0, 30.0
    expected = 360.0 * (v * METRES_TO_UNREAL_UNITS) / (2.0 * math.pi * r)
    res = check_wheel_rate(expected * 1.04, v, r)  # rel_tol default 0.05
    assert res["pass"] is True
    assert res["rel_error"] == pytest.approx(0.04)
    assert res["expected"] == pytest.approx(expected)


def test_check_wheel_rate_fails_at_six_percent_error():
    v, r = 10.0, 30.0
    expected = 360.0 * (v * METRES_TO_UNREAL_UNITS) / (2.0 * math.pi * r)
    res = check_wheel_rate(expected * 1.06, v, r)
    assert res["pass"] is False
    assert res["rel_error"] == pytest.approx(0.06)


def test_wheel_angle_accumulates_and_wraps_through_normalise():
    """prev 170 deg + ~191 deg of wheel travel must wrap back through 0."""
    v, r, dt = 10.0, 30.0, 0.1
    rate = wheel_rate_deg_per_s(v, r)
    assert 170.0 + rate * dt > 180.0, "this test must actually wrap"

    a1 = wheel_angle_deg(170.0, v, r, dt)
    assert a1 == pytest.approx(normalise_deg(170.0 + rate * dt))
    assert -180.0 < a1 <= 180.0

    acc = 170.0
    for _ in range(10):
        acc = wheel_angle_deg(acc, v, r, dt)
    assert acc == pytest.approx(normalise_deg(170.0 + 10.0 * rate * dt))


# --- heading from motion ---------------------------------------------------

def test_heading_from_motion_plus_x_is_zero():
    """Unreal convention: 0 = +X (east); see ldyf/coords.py lines 14-18."""
    p0 = {"x": 0.0, "y": 0.0}
    p1 = {"x": 100.0, "y": 0.0}
    assert heading_from_motion(p0, p1) == pytest.approx(0.0)


def test_heading_from_motion_plus_y_is_ninety():
    """Unreal yaw increases toward +Y; see ldyf/coords.py lines 14-18."""
    p0 = {"x": 0.0, "y": 0.0}
    p1 = {"x": 0.0, "y": 100.0}
    assert heading_from_motion(p0, p1) == pytest.approx(90.0)


def test_heading_from_motion_stationary_is_none():
    p0 = {"x": 5.0, "y": 7.0}
    assert heading_from_motion(p0, dict(p0)) is None


# --- synthetic record helpers -----------------------------------------------

def _write_record(tmp_path, actor_table, frames, step_seconds=0.1, t_begin=10.0):
    """frames.bin in the real layout; manifest dict like sumo_record's.

    actor_table: list of {"uid", "id", "kind"} in actor-index order.
    frames: list of frames; each frame a list of
            {"uid","x","y","z","yaw","speed"} dicts (order-insensitive).
    """
    index = {a["uid"]: i for i, a in enumerate(actor_table)}
    frames_path = tmp_path / "frames.bin"
    with frames_path.open("wb") as f:
        for frame in frames:
            rows = sorted(frame, key=lambda s: index[s["uid"]])
            f.write(COUNT_STRUCT.pack(len(rows)))
            for s in rows:
                f.write(
                    SAMPLE_STRUCT.pack(
                        index[s["uid"]], s["x"], s["y"], s["z"], s["yaw"], s["speed"]
                    )
                )
    manifest = {
        "format": "simulation_record_v1",
        "clock": {
            "step_seconds": step_seconds,
            "t_begin": t_begin,
            "frame_count": len(frames),
            "frame_time_rule": "t(i) = t_begin + i * step_seconds",
        },
        "actors": actor_table,
    }
    return frames_path, manifest


def _veh(uid):
    return {"uid": uid, "id": uid.split(":", 1)[1], "kind": "vehicle"}


def _s(uid, x, y, yaw=0.0, speed=10.0):
    return {"uid": uid, "x": x, "y": y, "z": 0.0, "yaw": yaw, "speed": speed}


# --- spawn windows ----------------------------------------------------------

def test_spawn_windows_first_last_count_gaps_and_times(tmp_path):
    """Vehicle A: present 0,1,3 -> gap at frame 2; times follow the clock rule."""
    actors = [_veh("vehicle:A"), _veh("vehicle:B")]
    frames = [
        [_s("vehicle:A", 0.0, 0.0), _s("vehicle:B", 0.0, 100.0)],
        [_s("vehicle:A", 100.0, 0.0), _s("vehicle:B", 0.0, 100.0)],
        [],  # nobody present
        [_s("vehicle:A", 200.0, 0.0), _s("vehicle:B", 0.0, 100.0)],
    ]
    frames_path, manifest = _write_record(tmp_path, actors, frames)
    win = spawn_windows(frames_path, manifest)

    assert set(win) == {"vehicle:A", "vehicle:B"}
    for uid in win:
        assert win[uid]["first_frame"] == 0
        assert win[uid]["last_frame"] == 3
        assert win[uid]["present_frames"] == 3
        assert win[uid]["gaps"] == [(2, 2)]
        assert win[uid]["first_time"] == pytest.approx(10.0)      # t_begin
        assert win[uid]["last_time"] == pytest.approx(10.3)       # t_begin + 3*0.1


def test_spawn_windows_excludes_persons_and_never_spawned_actors(tmp_path):
    actors = [
        _veh("vehicle:A"),
        _veh("vehicle:B"),                       # declared, never appears
        {"uid": "person:P", "id": "P", "kind": "person"},
    ]
    frames = [[_s("vehicle:A", 0.0, 0.0), {"uid": "person:P", "x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "speed": 1.0}]]
    frames_path, manifest = _write_record(tmp_path, actors, frames)
    win = spawn_windows(frames_path, manifest)
    assert set(win) == {"vehicle:A"}


# --- visibility plan --------------------------------------------------------

def _visibility_scenario(tmp_path):
    actors = [_veh("vehicle:A"), _veh("vehicle:B"), _veh("vehicle:C")]
    frames = [
        [_s("vehicle:A", 0.0, 0.0), _s("vehicle:B", 0.0, 100.0)],          # f0
        [_s("vehicle:A", 100.0, 0.0), _s("vehicle:B", 0.0, 100.0),         # f1
         _s("vehicle:C", 0.0, 200.0)],
        [_s("vehicle:A", 200.0, 0.0), _s("vehicle:C", 100.0, 200.0)],      # f2
    ]
    return _write_record(tmp_path, actors, frames)


def test_visibility_plan_spawn_and_despawn_at_a_frame(tmp_path):
    frames_path, manifest = _visibility_scenario(tmp_path)
    at1 = visibility_plan(frames_path, manifest, 1)
    assert at1["visible"] == ["vehicle:A", "vehicle:B", "vehicle:C"]
    assert at1["spawn"] == ["vehicle:C"]
    assert at1["despawn"] == []

    at2 = visibility_plan(frames_path, manifest, 2)
    assert at2["visible"] == ["vehicle:A", "vehicle:C"]
    assert at2["spawn"] == []
    assert at2["despawn"] == ["vehicle:B"]


def test_visibility_plan_frame_zero_counts_everything_as_spawn(tmp_path):
    frames_path, manifest = _visibility_scenario(tmp_path)
    at0 = visibility_plan(frames_path, manifest, 0)
    assert at0["visible"] == ["vehicle:A", "vehicle:B"]
    assert at0["spawn"] == ["vehicle:A", "vehicle:B"]
    assert at0["despawn"] == []


def test_visibility_plan_beyond_record_raises(tmp_path):
    frames_path, manifest = _visibility_scenario(tmp_path)
    with pytest.raises(IndexError):
        visibility_plan(frames_path, manifest, 99)


# --- yaw consistency --------------------------------------------------------

def _eastbound_record(tmp_path, yaw, n_frames=5):
    """Straight eastbound (+X in Unreal, east in SUMO) at 10 m/s, fixed yaw."""
    actors = [_veh("vehicle:V")]
    frames = [
        [_s("vehicle:V", 100.0 * i, 0.0, yaw=yaw, speed=10.0)]
        for i in range(n_frames)
    ]
    return _write_record(tmp_path, actors, frames)


def test_yaw_consistency_straight_eastbound_yaw_zero_passes(tmp_path):
    frames_path, manifest = _eastbound_record(tmp_path, yaw=0.0)
    res = yaw_consistency(frames_path, manifest, "vehicle:V")
    assert res["n"] == 4                       # 5 present frames -> 4 pairs
    assert res["max_deg"] == pytest.approx(0.0, abs=1e-6)
    assert res["mean_deg"] == pytest.approx(0.0, abs=1e-6)
    assert res["pass"] is True


def test_yaw_consistency_constant_wrong_yaw_fails(tmp_path):
    """Record yaw 40 while motion is +X (yaw 0): 40 deg off -> fail."""
    frames_path, manifest = _eastbound_record(tmp_path, yaw=40.0)
    res = yaw_consistency(frames_path, manifest, "vehicle:V")
    assert res["n"] == 4
    assert res["max_deg"] == pytest.approx(40.0, abs=1e-6)
    assert res["pass"] is False


# --- real proof record (skips when not present) ------------------------------

def _find_proof_dir() -> Path:
    """Locate the SUMO fixtures as test_closure.py does."""
    import os

    candidates = []
    env = os.environ.get("LDYF_PROOF_DIR")
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    # extracted MASTER: <root>/artifacts/ldyf/tests -> <root>/evidence/simulation
    candidates.append(here.parents[3] / "evidence" / "simulation")
    # development repo
    candidates.append(
        Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
        / "PHASE_01" / "proof" / "sumo"
    )
    for c in candidates:
        if (c / "grid.net.xml").exists():
            return c
    return candidates[-1]


RECORD_DIR = _find_proof_dir() / "closure_v2" / "record_ruled"

needs_record = pytest.mark.skipif(
    not (RECORD_DIR / "record_manifest.json").exists()
    or not (RECORD_DIR / "frames.bin").exists(),
    reason="real proof record not present",
)


@needs_record
def test_real_record_yaw_consistency_first_vehicle():
    """First vehicle uid: only n > 0 and finite numbers are asserted here.

    The real value is unknown ahead of time, so `pass` is deliberately not
    asserted; the measured numbers are surfaced in the worker's final report.
    """
    manifest = json.loads((RECORD_DIR / "record_manifest.json").read_text(encoding="utf-8"))
    first = next(a for a in manifest["actors"] if a["kind"] == "vehicle")
    res = yaw_consistency(RECORD_DIR / "frames.bin", manifest, first["uid"])
    print(f"real-record yaw_consistency {first['uid']}: {res}")
    assert res["n"] > 0
    assert math.isfinite(res["max_deg"])
    assert math.isfinite(res["mean_deg"])
