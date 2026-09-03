"""Phase 2 lane L2: interpolated truth between record frames.

Every test builds a tiny synthetic record by writing SAMPLE_STRUCT /
COUNT_STRUCT rows into tmp_path directly (no SUMO involved) with a
hand-written manifest whose `clock` uses step_seconds=0.25 and t_begin=10.0
-- deliberately NOT 0.1/0.0, so any code that assumes the default fails.

Canonical scenario (4 frames at 10.0, 10.25, 10.5, 10.75):
    vehicle:a present 0,1,2,3   (yaw crosses the 170 -> -170 seam 0->1)
    vehicle:b present 0,1,3     (absent in the middle frame 2)
    vehicle:c present 2,3       (late spawn)
"""

from __future__ import annotations

import pytest

from ldyf import record_interp as ri
from ldyf.coords import normalise_deg
from ldyf.sumo_record import COUNT_STRUCT, SAMPLE_STRUCT

A, B, C = "vehicle:a", "vehicle:b", "vehicle:c"


def make_record(tmp_path, actors, frames, *, step=0.25, t_begin=10.0):
    """frames: list of frames; a frame is a list of (uid, x, y, z, yaw, speed)."""
    uid_to_idx = {a["uid"]: i for i, a in enumerate(actors)}
    path = tmp_path / "frames.bin"
    with path.open("wb") as f:
        for frame in frames:
            f.write(COUNT_STRUCT.pack(len(frame)))
            for uid, x, y, z, yaw, speed in frame:
                f.write(SAMPLE_STRUCT.pack(uid_to_idx[uid], x, y, z, yaw, speed))
    manifest = {
        "format": "simulation_record_v1",
        "clock": {
            "step_seconds": step,
            "frame_count": len(frames),
            "t_begin": t_begin,
            "t_end": t_begin + step * (len(frames) - 1),
            "frame_time_rule": "t(i) = t_begin + i * step_seconds",
        },
        "actors": actors,
    }
    return path, manifest


def canonical(tmp_path):
    actors = [
        {"uid": A, "id": "a", "kind": "vehicle"},
        {"uid": B, "id": "b", "kind": "vehicle"},
        {"uid": C, "id": "c", "kind": "vehicle"},
    ]
    frames = [
        [(A, 0.0, 0.0, 0.0, 170.0, 2.0), (B, 0.0, 500.0, 10.0, 0.0, 1.0)],
        [(A, 100.0, 0.0, 0.0, -170.0, 4.0), (B, 100.0, 500.0, 10.0, 0.0, 1.0)],
        [(A, 200.0, 0.0, 0.0, -170.0, 4.0), (C, 0.0, 1000.0, 0.0, 90.0, 0.5)],
        [(A, 300.0, 0.0, 0.0, -170.0, 6.0), (B, 300.0, 500.0, 10.0, 0.0, 1.0),
         (C, 100.0, 1000.0, 0.0, 90.0, 0.5)],
    ]
    return make_record(tmp_path, actors, frames)


# --- clock ----------------------------------------------------------------


def test_frame_time_follows_manifest_clock(tmp_path):
    _, man = canonical(tmp_path)
    # step is 0.25 and t_begin is 10.0: a hardcoded 0.1/0.0 base fails here.
    assert ri.frame_time(man, 0) == 10.0
    assert ri.frame_time(man, 1) == 10.25
    assert ri.frame_time(man, 3) == 10.75
    assert man["clock"]["t_end"] == ri.frame_time(man, man["clock"]["frame_count"] - 1)


def test_frame_index_bounds_midpoint(tmp_path):
    _, man = canonical(tmp_path)
    assert ri.frame_index_bounds(man, 10.125) == (0, 1, 0.5)


def test_frame_index_bounds_exact_frame_is_single_index(tmp_path):
    _, man = canonical(tmp_path)
    assert ri.frame_index_bounds(man, 10.25) == (1, 1, 0.0)
    assert ri.frame_index_bounds(man, 10.75) == (3, 3, 0.0)


def test_frame_index_bounds_clamps_before_first_frame(tmp_path):
    _, man = canonical(tmp_path)
    assert ri.frame_index_bounds(man, 0.0) == (0, 0, 0.0)
    assert ri.frame_index_bounds(man, 5.0) == (0, 0, 0.0)


def test_frame_index_bounds_clamps_after_last_frame(tmp_path):
    _, man = canonical(tmp_path)
    assert ri.frame_index_bounds(man, 99.0) == (3, 3, 0.0)


# --- pose_at --------------------------------------------------------------


def test_pose_at_exact_frame_time_matches_record(tmp_path):
    path, man = canonical(tmp_path)
    assert ri.pose_at(path, man, A, 10.25) == pytest.approx(
        {"x": 100.0, "y": 0.0, "z": 0.0, "yaw": -170.0, "speed": 4.0}
    )


def test_pose_at_interpolates_position_and_speed_at_midpoint(tmp_path):
    path, man = canonical(tmp_path)
    # alpha 0.5 between frame 0 (x=0, speed=2) and frame 1 (x=100, speed=4).
    pose = ri.pose_at(path, man, A, 10.125)
    assert pose == pytest.approx(
        {"x": 50.0, "y": 0.0, "z": 0.0, "yaw": 180.0, "speed": 3.0}
    )


def test_pose_at_yaw_shortest_arc_across_seam(tmp_path):
    path, man = canonical(tmp_path)
    # 170 -> -170 at alpha 0.5 must go the short way THROUGH 180, not through 0.
    got = ri.pose_at(path, man, A, 10.125)["yaw"]
    assert normalise_deg(got) == got  # result is already normalised
    assert got == pytest.approx(180.0)
    assert abs(abs(got) - 180.0) < 1e-6  # the seam midpoint, asserted via the
    #  module's own normalised value rather than a hand-derived literal
    assert got != pytest.approx(0.0)  # the naive wrap-around midpoint


def test_pose_at_none_when_actor_absent_from_bounding_frame(tmp_path):
    path, man = canonical(tmp_path)
    # t=10.375 brackets frames 1 and 2; vehicle:b is absent in frame 2.
    assert ri.pose_at(path, man, B, 10.375) is None
    # vehicle:a present in both frames is not affected.
    assert ri.pose_at(path, man, A, 10.375) == pytest.approx(
        {"x": 150.0, "y": 0.0, "z": 0.0, "yaw": -170.0, "speed": 4.0}
    )


def test_pose_at_none_before_late_spawn(tmp_path):
    path, man = canonical(tmp_path)
    # vehicle:c first appears at frame 2 (t=10.5); earlier times are None.
    assert ri.pose_at(path, man, C, 10.0) is None
    assert ri.pose_at(path, man, C, 10.25) is None
    assert ri.pose_at(path, man, C, 10.5) is not None


def test_pose_at_clamps_before_first_record_time(tmp_path):
    path, man = canonical(tmp_path)
    # Clamped to frame 0: exact recorded pose, nothing extrapolated backwards.
    assert ri.pose_at(path, man, A, 0.0) == pytest.approx(
        {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 170.0, "speed": 2.0}
    )


def test_pose_at_clamps_after_last_record_time(tmp_path):
    path, man = canonical(tmp_path)
    # Clamped to frame 3: exact recorded pose, nothing extrapolated forwards.
    assert ri.pose_at(path, man, A, 999.0) == pytest.approx(
        {"x": 300.0, "y": 0.0, "z": 0.0, "yaw": -170.0, "speed": 6.0}
    )


def test_pose_at_unknown_actor_raises(tmp_path):
    path, man = canonical(tmp_path)
    with pytest.raises(KeyError):
        ri.pose_at(path, man, "vehicle:nope", 10.0)


# --- poses_at -------------------------------------------------------------


def test_poses_at_includes_only_actors_in_both_bounding_frames(tmp_path):
    path, man = canonical(tmp_path)
    # t=10.375 brackets frames 1 (A,B) and 2 (A,C): only A is in both.
    got = ri.poses_at(path, man, 10.375)
    assert set(got) == {A}
    assert got[A] == pytest.approx(
        {"x": 150.0, "y": 0.0, "z": 0.0, "yaw": -170.0, "speed": 4.0}
    )


def test_poses_at_exact_frame_time_returns_that_frame(tmp_path):
    path, man = canonical(tmp_path)
    got = ri.poses_at(path, man, 10.5)  # frame 2 holds A and C
    assert set(got) == {A, C}
    assert got[C] == pytest.approx(
        {"x": 0.0, "y": 1000.0, "z": 0.0, "yaw": 90.0, "speed": 0.5}
    )


# --- lifetimes ------------------------------------------------------------


def test_lifetimes_first_last_and_gaps(tmp_path):
    path, man = canonical(tmp_path)
    lt = ri.lifetimes(path, man)
    assert lt[A] == {
        "first_frame": 0, "last_frame": 3,
        "first_time": 10.0, "last_time": 10.75, "gaps": [],
    }
    # vehicle:b absent only in frame 2, strictly inside its lifetime.
    assert lt[B]["gaps"] == [(2, 2)]
    assert lt[B]["first_frame"] == 0 and lt[B]["last_frame"] == 3
    # vehicle:c spawns late: absence before first_frame is not a gap.
    assert lt[C] == {
        "first_frame": 2, "last_frame": 3,
        "first_time": 10.5, "last_time": 10.75, "gaps": [],
    }


def test_lifetimes_reports_all_absence_runs(tmp_path):
    actors = [{"uid": "vehicle:d", "id": "d", "kind": "vehicle"}]
    D = "vehicle:d"
    frames = []
    for i in range(7):  # present at frames 0, 2, 5, 6 over a 7-frame record
        frames.append(
            [(D, float(i) * 100.0, 0.0, 0.0, 0.0, 1.0)] if i in (0, 2, 5, 6) else []
        )
    path, man = make_record(tmp_path, actors, frames, step=0.25, t_begin=10.0)
    lt = ri.lifetimes(path, man)
    assert lt[D]["first_frame"] == 0 and lt[D]["last_frame"] == 6
    assert lt[D]["first_time"] == 10.0 and lt[D]["last_time"] == 11.5
    assert lt[D]["gaps"] == [(1, 1), (3, 4)]


# --- compare_poses --------------------------------------------------------


def test_compare_poses_exact_at_pinned_frame_passes(tmp_path):
    path, man = canonical(tmp_path)
    # Gate: 0.0 cm / 0.0 deg at pinned frames. Identical poses, zero tolerance.
    exp = ri.poses_at(path, man, 10.25)
    got = ri.compare_poses(exp, exp, pos_tol_cm=0.0, yaw_tol_deg=0.0)
    assert got["pass"] is True
    assert got["n"] == 2
    assert got["failures"] == []
    assert got["max_pos_cm"] == 0.0 and got["max_yaw_deg"] == 0.0


def test_compare_poses_fails_and_reports_worst_uid(tmp_path):
    path, man = canonical(tmp_path)
    exp = ri.poses_at(path, man, 10.25)  # A, B exact frame-1 poses
    measured = {uid: dict(p) for uid, p in exp.items()}
    measured[A]["x"] += 300.0  # 300 cm off
    measured[A]["yaw"] += 5.0  # 5 deg off
    got = ri.compare_poses(exp, measured, pos_tol_cm=1.0, yaw_tol_deg=1.0)
    assert got["pass"] is False
    assert got["n"] == 2
    assert got["failures"] == [A]
    assert got["max_pos_cm"] == pytest.approx(300.0)
    assert got["max_yaw_deg"] == pytest.approx(5.0)
    # Generous tolerances flip it to pass; the loser uid disappears.
    ok = ri.compare_poses(exp, measured, pos_tol_cm=1000.0, yaw_tol_deg=10.0)
    assert ok["pass"] is True and ok["failures"] == []


def test_compare_poses_yaw_error_uses_shortest_arc(tmp_path):
    path, man = canonical(tmp_path)
    exp = ri.poses_at(path, man, 10.25)
    measured = {uid: dict(p) for uid, p in exp.items()}
    # A sits on the far side of the seam: -179 vs 179 is a 2 deg error, not 358.
    measured[A]["yaw"] = 179.0
    exp[A]["yaw"] = -179.0
    strict = ri.compare_poses(exp, measured, pos_tol_cm=1.0, yaw_tol_deg=1.0)
    assert strict["pass"] is False and strict["failures"] == [A]
    assert strict["max_yaw_deg"] == pytest.approx(2.0)
    lax = ri.compare_poses(exp, measured, pos_tol_cm=1.0, yaw_tol_deg=3.0)
    assert lax["pass"] is True and lax["failures"] == []
