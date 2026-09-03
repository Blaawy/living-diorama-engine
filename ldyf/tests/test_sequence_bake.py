"""Unit tests for ldyf/sequence_bake.py (Phase-2 closure lane S, C3).

Pure deterministic key baking pinned to the frozen authorities:
record_interp.pose_at / playback_core.interpolated_poses (pose semantics),
vehicle_kinematics.wheel_angle_deg (wheel spin), playback_core.person_anim_state
/ person_play_rate (persons), and the C1 z law (record_z + surface + offset).

Run: pytest ldyf/tests/test_sequence_bake.py from the repo root.
"""

from __future__ import annotations

import json

import pytest

from ldyf import playback_core as pc
from ldyf import record_interp as ri
from ldyf import sequence_bake as sb
from ldyf import vehicle_kinematics as vk
from ldyf.sumo_record import COUNT_STRUCT, SAMPLE_STRUCT

# --- fixtures -------------------------------------------------------------

VEH_MESHES = ["m_veh_a", "m_veh_b", "m_veh_c"]
PERSON_MESH = "m_person_tutorial"
SURFACE = 20.0
OFF = {
    "m_veh_a": 45.0,
    "m_veh_b": 51.0,
    "m_veh_c": 60.0,
    PERSON_MESH: 2.5,
}
RADII = {
    "m_veh_a": 100.0,
    "m_veh_b": None,      # unmeasured mesh -> spin skipped
    "m_veh_c": 80.0,
    PERSON_MESH: None,
}


def mesh_for_uid(uid: str) -> str:
    if uid.startswith("vehicle:"):
        return pc.pick_mesh(VEH_MESHES, uid)
    return PERSON_MESH


def _frames_bin(path, frame_rows):
    buf = bytearray()
    for rows in frame_rows:
        buf += COUNT_STRUCT.pack(len(rows))
        for r in rows:
            buf += SAMPLE_STRUCT.pack(*r)
    path.write_bytes(bytes(buf))


def _manifest(n_frames, actors, step=0.25, t_begin=0.0):
    return {
        "format": "simulation_record_v1",
        "clock": {
            "t_begin": t_begin,
            "step_seconds": step,
            "frame_count": n_frames,
            "t_end": t_begin + step * (n_frames - 1),
        },
        "binary": {"file": "frames.bin", "sha256": "unused-in-tests"},
        "actors": actors,
    }


def _canonical(tmp_path, step=0.25, t_begin=0.0):
    """6 record frames (times t_begin + k*step).

    vehicle:a (idx 0): present 0,1,3,4,5 (absent frame 2 -> presence gap),
        x = 100*record_frame, z = 5, yaw 10, speed 8.
    person:p   (idx 1): present every frame, z = 0, yaw 90; speed 0,0,2,2,0,0
        (idle -> walk -> idle).
    """
    actors = [
        {"uid": "vehicle:a", "id": "a", "kind": "vehicle"},
        {"uid": "person:p", "id": "p", "kind": "person"},
    ]
    rows = [
        [(0, 0.0, 0.0, 5.0, 10.0, 8.0), (1, 100.0, 50.0, 0.0, 90.0, 0.0)],
        [(0, 100.0, 0.0, 5.0, 10.0, 8.0), (1, 110.0, 50.0, 0.0, 90.0, 0.0)],
        [(1, 120.0, 50.0, 0.0, 90.0, 2.0)],  # vehicle:a absent
        [(0, 200.0, 0.0, 5.0, 10.0, 8.0), (1, 130.0, 50.0, 0.0, 90.0, 2.0)],
        [(0, 300.0, 0.0, 5.0, 10.0, 8.0), (1, 140.0, 50.0, 0.0, 90.0, 0.0)],
        [(0, 400.0, 0.0, 5.0, 10.0, 8.0), (1, 150.0, 50.0, 0.0, 90.0, 0.0)],
    ]
    path = tmp_path / "frames.bin"
    _frames_bin(path, rows)
    man = _manifest(len(rows), actors, step=step, t_begin=t_begin)
    return path, man


def _bake(path, man, **kw):
    args = {
        "fps": 4,
        "rate": 1.0,
        "t_start_s": 0.0,
        "t_end_s": 1.5,
        "surface_z_cm": SURFACE,
        "contact_offsets": OFF,
        "mesh_for_uid": mesh_for_uid,
        "wheel_radius_for_mesh": RADII,
        "walk_ref_speed_mps": None,
    }
    args.update(kw)
    return sb.bake_keys(path, man, **args)


def _vehicle_mesh(doc, uid="vehicle:a"):
    return doc["actors"][uid]["mesh"]


# --- frame <-> time (C3) --------------------------------------------------


def test_presentation_time_is_frame_over_fps():
    assert sb.presentation_time_s(240, 24) == 10.0
    assert sb.presentation_time_s(0, 24) == 0.0
    assert sb.presentation_time_s(12, 24) == 0.5
    assert sb.presentation_time_s(3, 4) == 0.75


def test_presentation_time_no_accumulation_drift():
    # 7/24 must be computed directly as frame/fps, never accumulated per frame.
    assert sb.presentation_time_s(7, 24) == pytest.approx(7 / 24)
    assert sb.presentation_time_s(49, 24) == pytest.approx(49 / 24)
    assert abs(sb.presentation_time_s(24, 24) * 24 - 24) < 1e-12


def test_sim_time_default_rate_adds_t_begin():
    assert sb.sim_time_s(240, 24, 0.0) == 10.0
    assert sb.sim_time_s(240, 24, 12.5) == 22.5
    assert sb.sim_time_s(0, 24, 7.0) == 7.0


def test_sim_time_rate_2_doubles_presentation():
    assert sb.sim_time_s(240, 24, 0.0, rate=2.0) == 20.0
    assert sb.sim_time_s(10, 4, 0.0, rate=2.0) == 5.0
    assert sb.sim_time_s(240, 24, 3.0, rate=2.0) == 23.0


# --- schema / window ------------------------------------------------------


def test_output_schema_version_and_skeleton(tmp_path):
    path, man = _canonical(tmp_path)
    doc = _bake(path, man)
    assert doc["schema_version"] == "sequence_bake_v1"
    assert set(doc) >= {
        "schema_version", "fps", "rate", "t_begin", "frames", "actors",
        "counts", "missing_contact_offsets",
    }
    assert doc["fps"] == 4
    assert doc["rate"] == 1.0
    assert doc["t_begin"] == 0.0
    assert doc["frames"] == [0, 5]
    assert set(doc["actors"]) == {"vehicle:a", "person:p"}


def test_frames_range_from_requested_sim_window(tmp_path):
    path, man = _canonical(tmp_path)
    doc = _bake(path, man, t_start_s=0.25, t_end_s=1.0)
    assert doc["frames"] == [1, 3]
    keys_a = [k["f"] for k in doc["actors"]["vehicle:a"]["keys"]]
    assert keys_a == [1, 3]  # frame 2 is the absent record frame


def test_counts_actors_and_keys(tmp_path):
    path, man = _canonical(tmp_path)
    doc = _bake(path, man)
    # A: keys f0,f1,f3,f4,f5 = 5 ; P: keys f0..f5 = 6.
    assert doc["counts"] == {"actors": 2, "keys": 11}


# --- pose semantics -------------------------------------------------------


def test_keys_equal_record_at_exact_record_frames(tmp_path):
    path, man = _canonical(tmp_path)
    doc = _bake(path, man)  # fps 4, rate 1, step 0.25: output f == record f
    mesh_a = _vehicle_mesh(doc)
    ka = {k["f"]: k for k in doc["actors"]["vehicle:a"]["keys"]}
    for f, x in ((0, 0.0), (1, 100.0), (3, 200.0), (4, 300.0), (5, 400.0)):
        k = ka[f]
        assert k["x"] == x
        assert k["y"] == 0.0
        assert k["yaw"] == 10.0
        assert k["z"] == 5.0 + SURFACE + OFF[mesh_a]
    kp = {k["f"]: k for k in doc["actors"]["person:p"]["keys"]}
    assert kp[0]["x"] == 100.0
    assert kp[0]["z"] == 0.0 + SURFACE + OFF[PERSON_MESH]


def test_keys_between_record_frames_match_pose_at(tmp_path):
    """fps 24 vs step 0.1: output frames land BETWEEN record frames."""
    actors = [{"uid": "vehicle:a", "id": "a", "kind": "vehicle"}]
    rows = [
        [(0, 0.0, 0.0, 0.0, 0.0, 5.0)],
        [(0, 100.0, 0.0, 0.0, 0.0, 5.0)],
    ]
    path = tmp_path / "frames.bin"
    _frames_bin(path, rows)
    man = _manifest(len(rows), actors, step=0.1, t_begin=0.0)
    doc = _bake(path, man, fps=24, t_start_s=0.0, t_end_s=0.1)
    assert doc["frames"] == [0, 2]  # frames at 0/24, 1/24 and 2/24 s
    k1 = doc["actors"]["vehicle:a"]["keys"][1]
    assert k1["f"] == 1
    t1 = sb.sim_time_s(1, 24, 0.0, rate=1.0)  # 1/24 s: between record frames
    expected = ri.pose_at(path, man, "vehicle:a", t1)
    assert expected is not None
    assert k1["x"] == pytest.approx(expected["x"])
    assert k1["y"] == pytest.approx(expected["y"])
    assert k1["yaw"] == pytest.approx(expected["yaw"])
    assert k1["z"] == pytest.approx(expected["z"] + SURFACE + OFF[_vehicle_mesh(doc)])


def test_actor_absent_at_frame_has_no_key(tmp_path):
    path, man = _canonical(tmp_path)
    doc = _bake(path, man)
    keys_a = {k["f"] for k in doc["actors"]["vehicle:a"]["keys"]}
    assert keys_a == {0, 1, 3, 4, 5}  # record frame 2 is an absence -> no key


def test_actor_never_present_is_not_in_output(tmp_path):
    actors = [
        {"uid": "vehicle:a", "id": "a", "kind": "vehicle"},
        {"uid": "vehicle:never", "id": "never", "kind": "vehicle"},
    ]
    rows = [
        [(0, 0.0, 0.0, 0.0, 0.0, 1.0)],
        [(0, 10.0, 0.0, 0.0, 0.0, 1.0)],
    ]
    path = tmp_path / "frames.bin"
    _frames_bin(path, rows)
    man = _manifest(len(rows), actors, step=0.25, t_begin=0.0)
    doc = _bake(path, man, t_end_s=0.5)
    assert set(doc["actors"]) == {"vehicle:a"}
    assert doc["missing_contact_offsets"] == []


# --- presence -------------------------------------------------------------


def test_presence_segments_open_and_close_on_absence(tmp_path):
    path, man = _canonical(tmp_path)
    doc = _bake(path, man)
    # A: keyed 0,1 then absent at 2, then 3,4,5.
    assert doc["actors"]["vehicle:a"]["presence"] == [[0, 1], [3, 5]]
    # P: present every frame of the window.
    assert doc["actors"]["person:p"]["presence"] == [[0, 5]]


# --- z law (C1) -----------------------------------------------------------


def test_z_includes_surface_and_contact_offset(tmp_path):
    path, man = _canonical(tmp_path)
    doc = _bake(path, man)
    kp = doc["actors"]["person:p"]["keys"][0]
    assert kp["z"] == pytest.approx(0.0 + SURFACE + OFF[PERSON_MESH])
    # Two different vehicle meshes get two different offsets.
    mesh_c = "m_veh_c"
    doc2 = _bake(path, man, mesh_for_uid=lambda uid: mesh_c)
    assert doc2["actors"]["vehicle:a"]["keys"][0]["z"] == pytest.approx(
        5.0 + SURFACE + OFF[mesh_c]
    )


def test_missing_contact_offset_omits_keys_and_counts(tmp_path):
    actors = [{"uid": "vehicle:m", "id": "m", "kind": "vehicle"}]
    rows = [
        [(0, 0.0, 0.0, 0.0, 0.0, 1.0)],
        [(0, 10.0, 0.0, 0.0, 0.0, 1.0)],
    ]
    path = tmp_path / "frames.bin"
    _frames_bin(path, rows)
    man = _manifest(len(rows), actors, step=0.25, t_begin=0.0)

    def mesh_unknown(uid):
        return "m_veh_unmeasured"  # absent from OFF

    doc = _bake(path, man, mesh_for_uid=mesh_unknown, t_end_s=0.5)
    assert doc["actors"] == {}
    assert doc["counts"] == {"actors": 0, "keys": 0}
    assert doc["missing_contact_offsets"] == ["vehicle:m"]


# --- wheels ---------------------------------------------------------------


def _bake_veh_a_on_m_veh_a(path, man, **kw):
    """Force vehicle:a onto m_veh_a, the only measured-radius mesh used here."""
    return _bake(path, man, mesh_for_uid=lambda uid: "m_veh_a", **kw)


def test_wheel_angle_matches_vehicle_kinematics_accumulation(tmp_path):
    path, man = _canonical(tmp_path)
    doc = _bake_veh_a_on_m_veh_a(path, man)
    mesh = _vehicle_mesh(doc)
    radius = RADII[mesh]
    assert radius == 100.0
    wheels = doc["actors"]["vehicle:a"]["wheel_angle_deg"]
    # Runs [0,1] and [3,5]; spin resets at each run start; speed is 8.0.
    expected = []
    prev = None
    deg = 0.0
    for f in (0, 1, 3, 4, 5):
        if prev is None or f > prev + 1:
            deg = 0.0
        else:
            deg = vk.wheel_angle_deg(deg, 8.0, radius, 0.25)
        expected.append({"f": f, "deg": deg})
        prev = f
    assert [w["f"] for w in wheels] == [e["f"] for e in expected]
    assert [w["deg"] for w in wheels] == pytest.approx([e["deg"] for e in expected])


def test_wheel_angle_uses_rate_scaled_dt(tmp_path):
    """rate 2: one output frame advances sim by 2 x (1/fps) seconds."""
    actors = [{"uid": "vehicle:a", "id": "a", "kind": "vehicle"}]
    rows = [
        [(0, 0.0, 0.0, 5.0, 0.0, 8.0)],
        [(0, 100.0, 0.0, 5.0, 0.0, 8.0)],
        [(0, 200.0, 0.0, 5.0, 0.0, 8.0)],
        [(0, 300.0, 0.0, 5.0, 0.0, 8.0)],
    ]
    path = tmp_path / "frames.bin"
    _frames_bin(path, rows)
    man = _manifest(len(rows), actors, step=0.25, t_begin=0.0)
    doc = _bake_veh_a_on_m_veh_a(path, man, rate=2.0, t_end_s=0.75)
    assert doc["frames"] == [0, 1]
    radius = RADII["m_veh_a"]
    wheels = doc["actors"]["vehicle:a"]["wheel_angle_deg"]
    # frame 1 sits at sim t = 0.5 s -> record frame 2 (x = 200).
    assert doc["actors"]["vehicle:a"]["keys"][1]["x"] == 200.0
    assert wheels[0] == {"f": 0, "deg": 0.0}
    assert wheels[1]["deg"] == pytest.approx(
        vk.wheel_angle_deg(0.0, 8.0, radius, 2.0 / 4.0)
    )


def test_wheel_angle_resets_after_presence_gap(tmp_path):
    path, man = _canonical(tmp_path)
    doc = _bake_veh_a_on_m_veh_a(path, man)
    wheels = doc["actors"]["vehicle:a"]["wheel_angle_deg"]
    by_f = {w["f"]: w["deg"] for w in wheels}
    assert by_f[0] == 0.0
    assert by_f[1] != 0.0
    assert by_f[3] == 0.0  # respawn resets spin
    assert by_f[4] != 0.0
    assert by_f[5] != 0.0


def test_wheel_radius_none_yields_empty_wheel_list(tmp_path):
    actors = [{"uid": "vehicle:n", "id": "n", "kind": "vehicle"}]
    rows = [
        [(0, 0.0, 0.0, 5.0, 0.0, 4.0)],
        [(0, 10.0, 0.0, 5.0, 0.0, 4.0)],
    ]
    path = tmp_path / "frames.bin"
    _frames_bin(path, rows)
    man = _manifest(len(rows), actors, step=0.25, t_begin=0.0)

    def mesh_unmeasured(uid):
        return "m_veh_b"  # RADII says None -> spin skipped

    doc = _bake(path, man, mesh_for_uid=mesh_unmeasured, t_end_s=0.5)
    assert doc["actors"]["vehicle:n"]["wheel_angle_deg"] == []


# --- persons --------------------------------------------------------------


def test_person_anim_segments_switch_on_speed(tmp_path):
    path, man = _canonical(tmp_path)
    doc = _bake(path, man)
    anim = doc["actors"]["person:p"]["anim"]
    # P speeds 0,0,2,2,0,0 -> idle, idle, walk, walk, idle, idle.
    assert [(a["f_on"], a["f_off"], a["state"]) for a in anim] == [
        (0, 1, "idle"), (2, 3, "walk"), (4, 5, "idle"),
    ]


def test_person_walk_rate_scales_with_walk_ref(tmp_path):
    path, man = _canonical(tmp_path)
    doc = _bake(path, man, walk_ref_speed_mps=1.0)  # P walks at 2 m/s
    anim = doc["actors"]["person:p"]["anim"]
    assert anim[1]["state"] == "walk"
    assert anim[1]["rate"] == pytest.approx(2.0)  # speed / walk_ref
    assert anim[0]["rate"] == 1.0  # idle loop plays at the asset default


def test_person_walk_rate_1_when_walk_ref_none(tmp_path):
    path, man = _canonical(tmp_path)
    doc = _bake(path, man, walk_ref_speed_mps=None)
    anim = doc["actors"]["person:p"]["anim"]
    assert all(a["rate"] == 1.0 for a in anim)


def test_person_anim_segment_breaks_across_presence_gap(tmp_path):
    actors = [{"uid": "person:q", "id": "q", "kind": "person"}]
    rows = [
        [(0, 0.0, 0.0, 0.0, 0.0, 0.0)],
        [(0, 10.0, 0.0, 0.0, 0.0, 0.0)],
        [],  # absent
        [(0, 20.0, 0.0, 0.0, 0.0, 0.0)],
    ]
    path = tmp_path / "frames.bin"
    _frames_bin(path, rows)
    man = _manifest(len(rows), actors, step=0.25, t_begin=0.0)
    doc = _bake(path, man, t_end_s=1.0)
    anim = doc["actors"]["person:q"]["anim"]
    assert [(a["f_on"], a["f_off"], a["state"]) for a in anim] == [
        (0, 1, "idle"), (3, 3, "idle"),
    ]


# --- determinism ----------------------------------------------------------


def test_determinism_two_bakes_byte_identical(tmp_path):
    path, man = _canonical(tmp_path)
    d1 = _bake(path, man)
    d2 = _bake(path, man)
    j1 = json.dumps(d1, sort_keys=True, ensure_ascii=True)
    j2 = json.dumps(d2, sort_keys=True, ensure_ascii=True)
    assert j1 == j2
    assert list(d2["actors"].keys()) == sorted(d2["actors"].keys())
    for uid, rec in d2["actors"].items():
        fs = [k["f"] for k in rec["keys"]]
        assert fs == sorted(fs)


def test_determinism_sample_order_inside_frame_irrelevant(tmp_path):
    # Sample order within a frame must not leak into the output: bake indexes
    # actors by actor_index and emits actors sorted by uid.
    path, man = _canonical(tmp_path)
    doc_a = _bake(path, man)
    # Rewrite the same frames with every frame's sample rows reversed.
    raw = path.read_bytes()
    path2 = tmp_path / "frames_reversed.bin"
    out = bytearray()
    off = 0
    while off < len(raw):
        (n,) = COUNT_STRUCT.unpack_from(raw, off)
        off += COUNT_STRUCT.size
        rows = []
        for _ in range(n):
            rows.append(SAMPLE_STRUCT.unpack_from(raw, off))
            off += SAMPLE_STRUCT.size
        out += COUNT_STRUCT.pack(n)
        for r in reversed(rows):
            out += SAMPLE_STRUCT.pack(*r)
    path2.write_bytes(bytes(out))
    doc_b = _bake(path2, man)
    assert json.dumps(doc_a, sort_keys=True) == json.dumps(doc_b, sort_keys=True)


def test_validation_fps_and_kinds(tmp_path):
    path, man = _canonical(tmp_path)
    with pytest.raises(ValueError):
        _bake(path, man, fps=0)
    with pytest.raises(ValueError):
        _bake(path, man, rate=0.0)
    bad = dict(man)
    bad["actors"] = [{"uid": "bike:1", "id": "1", "kind": "bike"}]
    with pytest.raises(ValueError):
        _bake(path, bad)
