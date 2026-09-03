"""Phase 2 closure lane V: pure 3-D playback verification.

Synthetic records are written directly with SAMPLE_STRUCT / COUNT_STRUCT (the
same trick as test_record_interp.py) with hand-written manifests whose clock
blocks deliberately avoid 0.1/0.0 defaults where the feature under test would
otherwise smuggle them in. The placed snapshots are built from the record
poses plus explicit perturbations -- never from the Unreal editor, which this
lane cannot touch (the module under test is pure; it must never import
`unreal`).

Scenario map
------------
big record: 60 vehicles, step 0.1 from t_begin 0.0, x advances 100 cm per
frame, straight yaw -- the scale the C2 sample floor (>= 50) needs.
Tiny one-actor records isolate the Z fallback and the yaw seam.
"""

from __future__ import annotations

import json

import pytest

from ldyf import playback_verify3d as pv3
from ldyf import record_interp as ri
from ldyf.coords import normalise_deg
from ldyf.sumo_record import COUNT_STRUCT, SAMPLE_STRUCT

U0 = "vehicle:0"
U1 = "vehicle:1"


# --- synthetic-record helpers ---------------------------------------------


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


def big_actors(n=60):
    return [
        {"uid": f"vehicle:{i}", "id": str(i), "kind": "vehicle"} for i in range(n)
    ]


def big_record(tmp_path, n=60, frames=3, *, step=0.1, t_begin=0.0, yaw=30.0):
    """n vehicles on straight eastward tracks; frames at the given step/begin."""
    actors = big_actors(n)
    seq = []
    for f in range(frames):
        seq.append(
            [
                (f"vehicle:{i}", 100.0 * f + float(i), float(i) * 10.0, 0.0, yaw, 5.0)
                for i in range(n)
            ]
        )
    return make_record(tmp_path, actors, seq, step=step, t_begin=t_begin)


def placed_snapshot(exp, *, frame=0, t=0.0, surface_z=20.0, move=None,
                    omit=(), unplaced=(), extras=()):
    """Build a placed snapshot from expected poses (uid -> record pose).

    move:     {uid: {"dx","dy","dz","dyaw"}} additive perturbations (cm/deg).
    omit:     uids left out of the snapshot entirely (no entry at all).
    unplaced: uids whose entry stays in the list with present=false.
    extras:   [(label, uid)] actors the record never had, present=true.
    Default placement obeys C1: root_z = record_z + surface_z + 25 cm offset,
    bottom_z = root_z - 25 cm = record_z + surface_z (contact error zero).
    """
    actors = []
    for uid in sorted(exp):
        if uid in omit:
            continue
        e = exp[uid]
        m = (move or {}).get(uid, {})
        actors.append(
            {
                "label": uid,
                "uid": uid,
                "x": e["x"] + m.get("dx", 0.0),
                "y": e["y"] + m.get("dy", 0.0),
                "root_z": e["z"] + surface_z + 25.0,
                "bottom_z": e["z"] + surface_z + m.get("dz", 0.0),
                "yaw": e["yaw"] + m.get("dyaw", 0.0),
                "present": uid not in unplaced,
            }
        )
    for label, uid in extras:
        actors.append(
            {
                "label": label, "uid": uid, "x": 0.0, "y": 0.0,
                "root_z": 0.0, "bottom_z": 0.0, "yaw": 0.0, "present": True,
            }
        )
    return {"frame": frame, "t": t, "surface_z_cm": surface_z, "actors": actors}


def interp_snapshot(path, man, t, uids, move=None):
    """Placed actors taken verbatim from pose_at at t (plus optional moves)."""
    actors = []
    for uid in uids:
        p = ri.pose_at(path, man, uid, t)
        assert p is not None, f"{uid} not interpolable at {t}"
        m = (move or {}).get(uid, {})
        actors.append(
            {
                "label": uid, "uid": uid,
                "x": p["x"] + m.get("dx", 0.0),
                "y": p["y"] + m.get("dy", 0.0),
                "root_z": p["z"], "bottom_z": p["z"],
                "yaw": p["yaw"] + m.get("dyaw", 0.0),
                "present": True,
            }
        )
    return {"t": t, "actors": actors}


# --- expected_at_frame -----------------------------------------------------


def test_expected_at_frame_keys_by_uid_and_matches_record(tmp_path):
    path, man = big_record(tmp_path)
    exp = pv3.expected_at_frame(path, man, 1)
    assert set(exp) == {f"vehicle:{i}" for i in range(60)}
    assert exp[U0] == {"x": 100.0, "y": 0.0, "z": 0.0, "yaw": 30.0, "speed": 5.0}
    assert exp[U1] == {"x": 101.0, "y": 10.0, "z": 0.0, "yaw": 30.0, "speed": 5.0}


def test_expected_at_frame_only_present_actors_are_keyed(tmp_path):
    actors = big_actors(3)
    path, man = make_record(
        tmp_path, actors,
        [
            [(U0, 0.0, 0.0, 0.0, 0.0, 1.0), (U1, 1.0, 1.0, 0.0, 0.0, 1.0)],
            [(U1, 2.0, 1.0, 0.0, 0.0, 1.0), ("vehicle:2", 0.0, 5.0, 0.0, 0.0, 1.0)],
        ],
        step=0.25, t_begin=10.0,
    )
    exp1 = pv3.expected_at_frame(path, man, 1)
    assert set(exp1) == {U1, "vehicle:2"}
    assert U0 not in exp1


def test_expected_at_frame_beyond_record_end_raises(tmp_path):
    path, man = big_record(tmp_path, frames=2)
    with pytest.raises(IndexError):
        pv3.expected_at_frame(path, man, 5)


# --- compare_frame ---------------------------------------------------------


def test_compare_frame_exact_match_passes(tmp_path):
    path, man = big_record(tmp_path)
    exp = pv3.expected_at_frame(path, man, 0)
    snap = placed_snapshot(exp, frame=0, t=0.0)
    fr = pv3.compare_frame(
        snap, exp, surface_z_cm=20.0, xy_tol_cm=0.0, z_tol_cm=0.0, yaw_tol_deg=0.0
    )
    assert fr["pass"] is True
    assert fr["actors_expected"] == fr["actors_placed"] == fr["compared"] == 60
    assert fr["missing"] == [] and fr["extra"] == []
    assert fr["xy"] == {"max": 0.0, "mean": 0.0}
    assert fr["contact_z"]["max"] == fr["contact_z"]["mean"] == 0.0
    assert fr["contact_z"]["surface_z_used"] == 20.0
    assert fr["yaw"] == {"max": 0.0, "mean": 0.0}


def test_compare_frame_1km_z_displacement_fails_rt_p2_01(tmp_path):
    # RT-P2-01: a verifier that ignores z is forbidden (C1). A 1 km (100000 cm)
    # vertical displacement must fail and the report must show contact_z ~ 1e5.
    path, man = big_record(tmp_path)
    exp = pv3.expected_at_frame(path, man, 0)
    snap = placed_snapshot(exp, frame=0, t=0.0, move={U0: {"dz": 100000.0}})
    fr = pv3.compare_frame(
        snap, exp, surface_z_cm=20.0, xy_tol_cm=1.0, z_tol_cm=1.0, yaw_tol_deg=1.0
    )
    assert fr["pass"] is False
    assert fr["contact_z"]["max"] == pytest.approx(100000.0)
    assert fr["xy"]["max"] == pytest.approx(0.0)
    report = pv3.build_report(
        [fr],
        [{"t": 0.0, "compared": 60, "xy_max": 0.0, "yaw_max": 0.0, "pass": True}],
        record_sha256="deadbeef",
        tolerances={"xy_tol_cm": 1.0, "z_tol_cm": 1.0, "yaw_tol_deg": 1.0,
                    "min_actors": 50},
    )
    assert report["pass"] is False
    assert report["frames"][0]["contact_z"]["max"] == pytest.approx(100000.0)


def test_compare_frame_xy_off_2cm_fails_at_tol_1(tmp_path):
    path, man = big_record(tmp_path)
    exp = pv3.expected_at_frame(path, man, 0)
    snap = placed_snapshot(exp, frame=0, t=0.0, move={U0: {"dx": 2.0}})
    strict = pv3.compare_frame(
        snap, exp, surface_z_cm=20.0, xy_tol_cm=1.0, z_tol_cm=10.0, yaw_tol_deg=1.0
    )
    assert strict["pass"] is False
    assert strict["xy"]["max"] == pytest.approx(2.0)
    lax = pv3.compare_frame(
        snap, exp, surface_z_cm=20.0, xy_tol_cm=3.0, z_tol_cm=10.0, yaw_tol_deg=1.0
    )
    assert lax["pass"] is True


def test_compare_frame_contact_z_tolerance_governs_pass(tmp_path):
    path, man = big_record(tmp_path)
    exp = pv3.expected_at_frame(path, man, 0)
    snap = placed_snapshot(exp, frame=0, t=0.0, move={U0: {"dz": 5.0}})
    fr = pv3.compare_frame(
        snap, exp, surface_z_cm=20.0, xy_tol_cm=1.0, z_tol_cm=1.0, yaw_tol_deg=1.0
    )
    assert fr["pass"] is False
    assert fr["contact_z"]["max"] == pytest.approx(5.0)
    ok = pv3.compare_frame(
        snap, exp, surface_z_cm=20.0, xy_tol_cm=1.0, z_tol_cm=10.0, yaw_tol_deg=1.0
    )
    assert ok["pass"] is True


def test_compare_frame_yaw_seam_shortest_arc(tmp_path):
    # -179 vs 179 differ by 2 deg across the seam, never by 358.
    exp = {U0: {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": -179.0, "speed": 0.0}}
    snap = placed_snapshot(exp, surface_z=0.0, move={U0: {"dyaw": 358.0}})
    assert snap["actors"][0]["yaw"] == pytest.approx(179.0)
    fr = pv3.compare_frame(
        snap, exp, surface_z_cm=0.0, xy_tol_cm=1.0, z_tol_cm=1.0, yaw_tol_deg=1.0
    )
    assert fr["pass"] is False
    assert fr["yaw"]["max"] == pytest.approx(2.0)
    ok = pv3.compare_frame(
        snap, exp, surface_z_cm=0.0, xy_tol_cm=1.0, z_tol_cm=1.0, yaw_tol_deg=3.0
    )
    assert ok["pass"] is True


def test_compare_frame_missing_uid_detected(tmp_path):
    path, man = big_record(tmp_path)
    exp = pv3.expected_at_frame(path, man, 0)
    snap = placed_snapshot(exp, frame=0, t=0.0, omit={U0, U1})
    fr = pv3.compare_frame(
        snap, exp, surface_z_cm=20.0, xy_tol_cm=1.0, z_tol_cm=1.0, yaw_tol_deg=1.0
    )
    assert fr["pass"] is False
    assert fr["missing"] == [U0, U1]
    assert fr["compared"] == 58


def test_compare_frame_extra_actor_detected_by_label(tmp_path):
    path, man = big_record(tmp_path)
    exp = pv3.expected_at_frame(path, man, 0)
    snap = placed_snapshot(exp, frame=0, t=0.0,
                           extras=[("ghost_car", "vehicle:999")])
    fr = pv3.compare_frame(
        snap, exp, surface_z_cm=20.0, xy_tol_cm=1.0, z_tol_cm=1.0, yaw_tol_deg=1.0
    )
    assert fr["pass"] is False
    assert fr["extra"] == ["ghost_car"]
    assert fr["actors_placed"] == 61


def test_compare_frame_present_false_counts_as_missing(tmp_path):
    path, man = big_record(tmp_path)
    exp = pv3.expected_at_frame(path, man, 0)
    snap = placed_snapshot(exp, frame=0, t=0.0, unplaced={U0})
    # the entry is still listed, but present=false: not a placed actor.
    assert len(snap["actors"]) == 60
    fr = pv3.compare_frame(
        snap, exp, surface_z_cm=20.0, xy_tol_cm=1.0, z_tol_cm=1.0, yaw_tol_deg=1.0
    )
    assert fr["pass"] is False
    assert fr["missing"] == [U0]
    assert fr["actors_placed"] == 59


def test_compare_frame_present_false_extra_ignored(tmp_path):
    path, man = big_record(tmp_path)
    exp = pv3.expected_at_frame(path, man, 0)
    snap = placed_snapshot(exp, frame=0, t=0.0,
                           extras=[("ghost_car", "vehicle:999")])
    snap["actors"][-1]["present"] = False  # never spawned -> not an extra
    fr = pv3.compare_frame(
        snap, exp, surface_z_cm=20.0, xy_tol_cm=1.0, z_tol_cm=1.0, yaw_tol_deg=1.0
    )
    assert fr["pass"] is True
    assert fr["extra"] == [] and fr["missing"] == []


def test_compare_frame_contact_offset_fallback_when_bottom_missing(tmp_path):
    # No bounds bottom in the snapshot: bottom = root_z - contact_offset (C1)
    # keeps the Z check alive. Root is 5 cm too high -> contact error 5 cm.
    exp = {U0: {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "speed": 1.0}}
    surface = 20.0
    offset = 25.0
    snap = {
        "frame": 0, "t": 0.0, "surface_z_cm": surface,
        "actors": [
            {"label": U0, "uid": U0, "x": 0.0, "y": 0.0,
             "root_z": 0.0 + surface + offset + 5.0,  # bottom_z key absent
             "yaw": 0.0, "present": True},
        ],
    }
    strict = pv3.compare_frame(
        snap, exp, surface_z_cm=surface, contact_offsets={U0: offset},
        xy_tol_cm=1.0, z_tol_cm=1.0, yaw_tol_deg=1.0,
    )
    assert strict["pass"] is False
    assert strict["contact_z"]["max"] == pytest.approx(5.0)
    ok = pv3.compare_frame(
        snap, exp, surface_z_cm=surface, contact_offsets={U0: offset},
        xy_tol_cm=1.0, z_tol_cm=10.0, yaw_tol_deg=1.0,
    )
    assert ok["pass"] is True


def test_compare_frame_missing_bottom_without_offset_fails_z_check(tmp_path):
    # C1: a verifier that ignores z is forbidden -- an actor with no bottom z
    # and no offset cannot be Z-verified, so the frame must not pass.
    exp = {U0: {"x": 0.0, "y": 0.0, "z": 0.0, "yaw": 0.0, "speed": 1.0}}
    snap = {
        "frame": 0, "t": 0.0, "surface_z_cm": 20.0,
        "actors": [
            {"label": U0, "uid": U0, "x": 0.0, "y": 0.0, "root_z": 45.0,
             "yaw": 0.0, "present": True},
        ],
    }
    fr = pv3.compare_frame(
        snap, exp, surface_z_cm=20.0, xy_tol_cm=1.0, z_tol_cm=1.0, yaw_tol_deg=1.0
    )
    assert fr["pass"] is False


# --- choose_frames ---------------------------------------------------------


def _clock_manifest(step, t_begin, frame_count):
    return {
        "clock": {
            "step_seconds": step,
            "frame_count": frame_count,
            "t_begin": t_begin,
            "t_end": t_begin + step * (frame_count - 1),
        },
        "actors": [],
    }


def test_choose_frames_from_non_01_step_clock(tmp_path):
    # step 0.25 / t_begin 10.0: any hardcoded 0.1 s / frame-1000 logic fails.
    man = _clock_manifest(0.25, 10.0, 5000)
    got = pv3.choose_frames(man, 1000.0)  # defaults before=50, after=150
    assert got == [3760, 3960, 4560]  # t = 950 / 1000 / 1150


def test_choose_frames_c2_before_around_post_example(tmp_path):
    # C2: closure at 150 s, step 0.1 from 0 -> frames 1000 / 1500 / 3000.
    man = _clock_manifest(0.1, 0.0, 4000)
    assert pv3.choose_frames(man, 150.0) == [1000, 1500, 3000]


def test_choose_frames_clamps_and_dedupes(tmp_path):
    man = _clock_manifest(0.25, 10.0, 4)  # frames only at t = 10 .. 10.75
    # around = 10.5 (frame 2); before and post clamp to 0 and 3.
    assert pv3.choose_frames(man, 10.5) == [0, 2, 3]
    # around 10.0 == before 10.0 target: the duplicate collapses to one frame.
    assert pv3.choose_frames(man, 10.0) == [0, 3]
    # empty record -> nothing to verify.
    empty = _clock_manifest(0.1, 0.0, 0)
    assert pv3.choose_frames(empty, 150.0) == []


# --- compare_interpolated --------------------------------------------------


def test_compare_interpolated_half_step_equals_pose_at(tmp_path):
    path, man = big_record(tmp_path, frames=2)
    # half step between frames 0 and 1 of the 0.1 s clock: t = 0.05.
    half = ri.frame_time(man, 0) + man["clock"]["step_seconds"] / 2.0
    assert half == pytest.approx(0.05)
    # Build the placed snapshot FROM pose_at: an exact placement must pass and
    # must agree with the record's own interpolation authority.
    snap = interp_snapshot(path, man, half, [f"vehicle:{i}" for i in range(60)])
    got = pv3.compare_interpolated(snap, path, man, xy_tol_cm=0.0, yaw_tol_deg=0.0)
    assert got["pass"] is True
    assert got["compared"] == 60
    assert got["xy_max"] == pytest.approx(0.0)
    assert got["yaw_max"] == pytest.approx(0.0)
    # spot-check one uid against the manual midpoint: frame0 x=i, frame1 x=100+i.
    assert got["t"] == pytest.approx(0.05)
    assert ri.pose_at(path, man, U0, half)["x"] == pytest.approx(50.0)


def test_compare_interpolated_xy_displacement_fails(tmp_path):
    path, man = big_record(tmp_path, frames=2)
    half = 0.05
    snap = interp_snapshot(path, man, half, [f"vehicle:{i}" for i in range(60)],
                           move={U0: {"dx": 2.5}})
    got = pv3.compare_interpolated(snap, path, man,
                                   xy_tol_cm=1.0, yaw_tol_deg=1.0)
    assert got["pass"] is False
    assert got["xy_max"] == pytest.approx(2.5)
    ok = pv3.compare_interpolated(snap, path, man,
                                  xy_tol_cm=3.0, yaw_tol_deg=1.0)
    assert ok["pass"] is True


def test_compare_interpolated_yaw_seam_shortest_arc(tmp_path):
    # 170 -> -170 across one 0.25 s step: the seam midpoint is yaw 180 (the
    # short way through the seam), so a placed -179 is only 1 deg off.
    path, man = make_record(
        tmp_path,
        [{"uid": U0, "id": "0", "kind": "vehicle"}],
        [[(U0, 0.0, 0.0, 0.0, 170.0, 2.0)], [(U0, 100.0, 0.0, 0.0, -170.0, 4.0)]],
        step=0.25, t_begin=10.0,
    )
    half = ri.frame_time(man, 0) + 0.25 / 2.0  # 10.125
    exp = ri.pose_at(path, man, U0, half)
    assert exp is not None
    assert normalise_deg(exp["yaw"]) == pytest.approx(180.0)
    snap = interp_snapshot(path, man, half, [U0], move={U0: {"dyaw": 1.0}})
    # pose_at yaw is 180; placing -179 means dyaw applied to 180 gives -179...
    snap["actors"][0]["yaw"] = -179.0
    strict = pv3.compare_interpolated(snap, path, man,
                                      xy_tol_cm=1.0, yaw_tol_deg=0.5)
    assert strict["pass"] is False
    assert strict["yaw_max"] == pytest.approx(1.0)
    ok = pv3.compare_interpolated(snap, path, man,
                                  xy_tol_cm=1.0, yaw_tol_deg=2.0)
    assert ok["pass"] is True


def test_compare_interpolated_skips_actor_absent_at_half_step(tmp_path):
    # pose_at returns None for an actor absent from the bounding frames; the
    # check never invents a pose for it (record_interp law 3).
    path, man = make_record(
        tmp_path,
        big_actors(2),
        [
            [(U0, 0.0, 0.0, 0.0, 0.0, 1.0), (U1, 0.0, 0.0, 0.0, 0.0, 1.0)],
            [(U1, 5.0, 0.0, 0.0, 0.0, 1.0)],  # vehicle:0 despawns here
        ],
        step=0.25, t_begin=10.0,
    )
    half = 10.125  # brackets frames 0 and 1
    assert ri.pose_at(path, man, U0, half) is None
    assert ri.pose_at(path, man, U1, half) is not None
    snap = {"t": half, "actors": [
        {"label": U0, "uid": U0, "x": 0.0, "y": 0.0, "root_z": 0.0,
         "bottom_z": 0.0, "yaw": 0.0, "present": True},
        {"label": U1, "uid": U1, "x": 2.5, "y": 0.0, "root_z": 0.0,
         "bottom_z": 0.0, "yaw": 0.0, "present": True},
    ]}
    got = pv3.compare_interpolated(snap, path, man)
    assert got["compared"] == 1
    assert got["pass"] is True


# --- build_report / write_report -------------------------------------------


def _exact_pipeline(tmp_path, n=60):
    """(frame_result, interp_result) that both pass exactly."""
    path, man = big_record(tmp_path, n=n, frames=2)
    exp = pv3.expected_at_frame(path, man, 0)
    fr = pv3.compare_frame(
        placed_snapshot(exp, frame=0, t=0.0), exp,
        surface_z_cm=20.0, xy_tol_cm=0.0, z_tol_cm=0.0, yaw_tol_deg=0.0,
    )
    half = ri.frame_time(man, 0) + man["clock"]["step_seconds"] / 2.0
    interp = pv3.compare_interpolated(
        interp_snapshot(path, man, half, [f"vehicle:{i}" for i in range(n)]),
        path, man, xy_tol_cm=0.0, yaw_tol_deg=0.0,
    )
    return fr, interp


def test_build_report_insufficient_sample_flagged(tmp_path):
    path, man = big_record(tmp_path)  # 60 expected
    exp = pv3.expected_at_frame(path, man, 0)
    omit = {f"vehicle:{i}" for i in range(20)}  # only 40 placed -> compared 40
    fr = pv3.compare_frame(
        placed_snapshot(exp, frame=0, t=0.0, omit=omit), exp,
        surface_z_cm=20.0, xy_tol_cm=1.0, z_tol_cm=1.0, yaw_tol_deg=1.0,
    )
    assert fr["compared"] == 40
    report = pv3.build_report(
        [fr],
        [{"t": 0.0, "compared": 40, "xy_max": 0.0, "yaw_max": 0.0, "pass": True}],
        record_sha256="sha",
        tolerances={"xy_tol_cm": 1.0, "z_tol_cm": 1.0, "yaw_tol_deg": 1.0,
                    "min_actors": 50},
    )
    assert report["frames"][0]["insufficient_sample"] is True
    assert report["insufficient_sample"] is True
    assert report["frames"][0]["pass"] is False
    assert report["pass"] is False


def test_build_report_fewer_expected_is_not_insufficient(tmp_path):
    # 5 expected, all placed: min(50, 5) = 5, compared 5 -> not insufficient.
    path, man = big_record(tmp_path, n=5, frames=2)
    exp = pv3.expected_at_frame(path, man, 0)
    fr = pv3.compare_frame(
        placed_snapshot(exp, frame=0, t=0.0), exp,
        surface_z_cm=20.0, xy_tol_cm=0.0, z_tol_cm=0.0, yaw_tol_deg=0.0,
    )
    half = ri.frame_time(man, 0) + man["clock"]["step_seconds"] / 2.0
    interp = pv3.compare_interpolated(
        interp_snapshot(path, man, half, [f"vehicle:{i}" for i in range(5)]),
        path, man, xy_tol_cm=0.0, yaw_tol_deg=0.0,
    )
    report = pv3.build_report(
        [fr], [interp], record_sha256="sha",
        tolerances={"xy_tol_cm": 0.0, "z_tol_cm": 0.0, "yaw_tol_deg": 0.0,
                    "interp_tol_cm": 0.0, "interp_tol_deg": 0.0, "min_actors": 50},
    )
    assert report["insufficient_sample"] is False
    assert report["frames"][0]["insufficient_sample"] is False
    assert report["pass"] is True


def test_build_report_pass_requires_every_frame_and_interp(tmp_path):
    fr, interp = _exact_pipeline(tmp_path)
    tol = {"xy_tol_cm": 0.0, "z_tol_cm": 0.0, "yaw_tol_deg": 0.0,
           "interp_tol_cm": 0.0, "interp_tol_deg": 0.0, "min_actors": 50}
    good = pv3.build_report([fr], [interp], record_sha256="sha", tolerances=tol)
    assert good["pass"] is True
    bad_interp = dict(interp)
    bad_interp["pass"] = False
    bad = pv3.build_report([fr], [bad_interp], record_sha256="sha", tolerances=tol)
    assert bad["pass"] is False
    # no frames at all -> nothing was verified -> pass must be False.
    none = pv3.build_report([], [interp], record_sha256="sha", tolerances=tol)
    assert none["pass"] is False


def test_build_report_echoes_tolerances_and_schema(tmp_path):
    fr, interp = _exact_pipeline(tmp_path)
    tolerances = {
        "xy_tol_cm": 1.0, "z_tol_cm": 1.0, "yaw_tol_deg": 1.0,
        "interp_tol_cm": 1.0, "interp_tol_deg": 1.0, "min_actors": 50,
    }
    report = pv3.build_report([fr], [interp], record_sha256="abc123",
                              tolerances=tolerances)
    assert report["schema_version"] == "playback_verify3d_v1"
    assert report["record_sha256"] == "abc123"
    assert report["tolerances"] == tolerances
    for key in ("frames", "interpolation", "tolerances", "pass"):
        assert key in report


def test_report_and_write_are_deterministic(tmp_path):
    fr, interp = _exact_pipeline(tmp_path)
    tolerances = {
        "xy_tol_cm": 1.0, "z_tol_cm": 1.0, "yaw_tol_deg": 1.0,
        "interp_tol_cm": 1.0, "interp_tol_deg": 1.0, "min_actors": 50,
    }
    r1 = pv3.build_report([fr], [interp], record_sha256="sha", tolerances=tolerances)
    r2 = pv3.build_report([fr], [interp], record_sha256="sha", tolerances=tolerances)
    p1 = pv3.write_report(r1, tmp_path / "a.json")
    p2 = pv3.write_report(r2, tmp_path / "b.json")
    assert p1 == tmp_path / "a.json" and p1.exists()
    assert p2 == tmp_path / "b.json" and p2.exists()
    assert p1.read_bytes() == p2.read_bytes()
    assert json.loads(p1.read_text(encoding="utf-8")) == json.loads(
        p2.read_text(encoding="utf-8")
    )


def test_write_report_sorted_keys_indent_2(tmp_path):
    fr, interp = _exact_pipeline(tmp_path, n=5)
    report = pv3.build_report([fr], [interp], record_sha256="sha",
                              tolerances={"min_actors": 50})
    out = pv3.write_report(report, tmp_path / "report.json")
    text = out.read_text(encoding="utf-8")
    loaded = json.loads(text)
    assert text.startswith('{\n  "frames"')
    assert list(loaded.keys()) == sorted(loaded.keys())
    # a byte-stable round trip: the written document equals the in-memory one.
    assert loaded == report
