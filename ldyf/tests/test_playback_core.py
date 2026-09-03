"""Unit tests for ldyf/playback_core.py (Phase-2 lane L6 pure arithmetic, L7 persons,
P: contact law C1, frame authority C3, profile buckets, paint variant, snapshots).

The in-editor player cannot be unit-tested (it imports `unreal`), so every
number it computes lives here and is pinned to the frozen authorities:
record_interp.frame_index_bounds / pose_at, vehicle_kinematics.wheel_angle_deg,
world_inventory.inventory (actor_dump_v1 acceptance). L7 adds the pure
walk/idle state machine, the play-rate scaling and the person yaw offset.
Lane P adds the C1 contact law arithmetic (ground truth
EVIDENCE_contact_probe.json), the C3 frame->sim mapping, the profiling bucket
accounting, the deterministic paint-variant digest and the snapshot assembly.

Run: pytest ldyf/tests/test_playback_core.py from the repo root.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from ldyf import playback_core as pc
from ldyf import record_interp as ri
from ldyf import vehicle_kinematics as vk
from ldyf.coords import normalise_deg
from ldyf.sumo_record import COUNT_STRUCT, SAMPLE_STRUCT
from ldyf.world_inventory import INVENTORY_VERSION, inventory

ACTORS = [
    {"uid": "vehicle:0", "id": "0", "kind": "vehicle"},
    {"uid": "person:1", "id": "1", "kind": "person"},
]


# --- helpers --------------------------------------------------------------


def _write_frames(path, frame_rows):
    out = bytearray()
    for rows in frame_rows:
        out += COUNT_STRUCT.pack(len(rows))
        for r in rows:
            out += SAMPLE_STRUCT.pack(*r)
    path.write_bytes(bytes(out))


def _manifest(n_frames, actors=ACTORS, step=0.1, t_begin=0.0):
    return {
        "clock": {"t_begin": t_begin, "step_seconds": step, "frame_count": n_frames},
        "binary": {"file": "frames.bin", "sha256": "unused-in-tests"},
        "actors": actors,
    }


def _frames_by_index(rows_per_frame):
    return {i: rows for i, rows in enumerate(rows_per_frame)}


# --- mesh choice ----------------------------------------------------------


def test_pick_mesh_is_deterministic_and_sha256_based():
    paths = ["a", "b", "c"]
    for uid in ("vehicle:0", "person:9", "vehicle:vehCar_vehicle02"):
        got = pc.pick_mesh(paths, uid)
        assert got == pc.pick_mesh(paths, uid)
        assert got in paths
        digest = hashlib.sha256(uid.encode("utf-8")).digest()
        assert got == paths[int.from_bytes(digest[:8], "little") % len(paths)]


def test_pick_mesh_empty_list_raises():
    with pytest.raises(ValueError):
        pc.pick_mesh([], "vehicle:0")


def test_pick_mesh_covers_all_meshes_given_uid_space():
    paths = ["m0", "m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10", "m11", "m12", "m13"]
    picked = {pc.pick_mesh(paths, f"vehicle:{i}") for i in range(0, 400, 3)}
    assert picked <= set(paths)
    assert len(picked) > 1  # choice is not constant


# --- frame addressing -----------------------------------------------------


@pytest.mark.parametrize("t", [-1.0, 0.0, 0.1234, 0.25, 1.5, 4.999, 5.0, 9.0, 50.0])
def test_frame_bounds_delegates_to_record_interp(t):
    m = _manifest(10, step=0.25, t_begin=0.5)
    assert pc.frame_bounds(m, t) == ri.frame_index_bounds(m, t)


# --- interpolation --------------------------------------------------------


def test_interpolated_pose_matches_record_interp_pose_at(tmp_path):
    rows0 = [(0, 100.0, 200.0, 0.0, 10.0, 5.0), (1, 300.0, 400.0, 0.0, 20.0, 2.0)]
    rows1 = [(0, 110.0, 215.0, 0.0, 13.0, 6.0), (1, 290.0, 380.0, 0.0, 18.0, 1.5)]
    rows2 = [(0, 120.0, 230.0, 0.0, 16.0, 7.0), (1, 280.0, 360.0, 0.0, 16.0, 1.0)]
    p = tmp_path / "frames.bin"
    _write_frames(p, [rows0, rows1, rows2])
    m = _manifest(3)
    fbi = _frames_by_index([rows0, rows1, rows2])
    for t in (0.05, 0.15, 0.25, 1.33):
        got = pc.interpolated_poses(fbi, m, t)
        for uid, idx in (("vehicle:0", 0), ("person:1", 1)):
            exp = ri.pose_at(p, m, uid, t)
            if exp is None:
                assert idx not in got
            else:
                assert idx in got
                assert got[idx] == exp


def test_exact_frame_time_pose_equals_record_sample():
    """Pin contract: at an exact frame time the pose is the record sample."""
    rows0 = [(0, 100.0, 200.0, 5.0, 10.0, 5.0)]
    rows1 = [(0, 110.0, 215.0, 6.0, 13.0, 6.0)]
    m = _manifest(2, step=0.1, t_begin=0.0)
    fbi = _frames_by_index([rows0, rows1])
    pose = pc.interpolated_poses(fbi, m, 0.1)[0]
    s = rows1[0]
    assert pose == {"x": s[1], "y": s[2], "z": s[3], "yaw": s[4], "speed": s[5]}


def test_visible_window_is_first_to_last_present_frame(tmp_path):
    """Spawn at first present frame boundary, despawn at first absent boundary."""
    rows = [
        [],
        [(0, 0.0, 0.0, 0.0, 0.0, 1.0)],
        [(0, 1.0, 1.0, 0.0, 0.0, 1.0)],
        [],
    ]
    p = tmp_path / "frames.bin"
    _write_frames(p, rows)
    m = _manifest(4, step=1.0, t_begin=0.0)
    fbi = _frames_by_index(rows)
    assert 0 not in pc.interpolated_poses(fbi, m, 0.0)   # absent before spawn
    assert 0 not in pc.interpolated_poses(fbi, m, 0.5)   # absent from i0
    assert 0 in pc.interpolated_poses(fbi, m, 1.0)       # exact first frame
    assert 0 in pc.interpolated_poses(fbi, m, 1.5)
    assert 0 in pc.interpolated_poses(fbi, m, 2.0)       # exact last frame
    assert 0 not in pc.interpolated_poses(fbi, m, 2.5)   # absent from i1
    assert 0 not in pc.interpolated_poses(fbi, m, 3.0)   # absent after despawn


def test_pose_never_interpolated_across_an_absence(tmp_path):
    """An actor present in i1 but absent in i0 is not extrapolated backwards."""
    rows = [
        [(1, 300.0, 400.0, 0.0, 20.0, 2.0)],
        [(0, 110.0, 215.0, 0.0, 13.0, 6.0), (1, 290.0, 380.0, 0.0, 18.0, 1.5)],
    ]
    p = tmp_path / "frames.bin"
    _write_frames(p, rows)
    m = _manifest(2)
    fbi = _frames_by_index(rows)
    mid = pc.interpolated_poses(fbi, m, 0.05)
    assert 0 not in mid   # actor 0 not present in frame 0 -> no pose at t=0.05


# --- wheel spin / steer ---------------------------------------------------


@pytest.mark.parametrize(
    "prev,speed,r,dt",
    [
        (0.0, 5.0, 35.0, 0.016),
        (179.0, 20.0, 40.0, 0.1),
        (-170.0, 0.0, 30.0, 1.0),
        (0.0, 33.3, 50.0, 0.016),
        (-180.0, 12.0, 35.0, 0.05),
    ],
)
def test_accumulate_spin_matches_wheel_angle_deg(prev, speed, r, dt):
    deg, spun = pc.accumulate_spin(prev, speed, r, dt)
    assert spun is True
    assert deg == vk.wheel_angle_deg(prev, speed, r, dt)


def test_accumulate_spin_none_or_zero_radius_is_not_spun():
    assert pc.accumulate_spin(0.0, 5.0, None, 0.1) == (None, False)
    assert pc.accumulate_spin(0.0, 5.0, 0.0, 0.1) == (None, False)


def test_accumulate_spin_long_run_equals_repeated_wheel_angle_deg():
    expected = 0.0
    for _ in range(200):
        expected = vk.wheel_angle_deg(expected, 13.2, 35.0, 0.05)
    deg, spun = 0.0, True
    for _ in range(200):
        deg, spun = pc.accumulate_spin(deg, 13.2, 35.0, 0.05)
    assert spun is True
    assert deg == expected


def test_steer_yaw_clamps_and_uses_shortest_arc():
    assert pc.steer_yaw(0.0, 10.0) == 10.0
    assert pc.steer_yaw(0.0, 90.0) == pc.MAX_STEER_DEG
    assert pc.steer_yaw(0.0, -40.0) == -pc.MAX_STEER_DEG
    assert pc.steer_yaw(170.0, -160.0) == 30.0  # shortest arc +30, not -330
    assert pc.steer_yaw(10.0, 10.0) == 0.0
    assert pc.steer_yaw(0.0, 90.0, max_deg=10.0) == 10.0


# --- persons: walk/idle state, play rate, yaw offset (Phase-2 L7) ---------


def test_person_anim_state_walks_when_moving_and_idles_when_stopped():
    # Until idle_below is set: any speed > 0 walks, speed == 0 idles.
    assert pc.person_anim_state(1.4, None, None, "idle") == "walk"
    assert pc.person_anim_state(0.0, None, None, "walk") == "idle"


def test_person_anim_state_unset_params_still_walk_at_tiny_speed():
    # "until set, always-walk when speed > 0": no idle threshold is invented.
    assert pc.person_anim_state(1e-9, None, None, "idle") == "walk"


def test_person_anim_state_idle_below_threshold_even_while_moving():
    # speed 0.3 < idle_below 0.5 -> idle although the record keeps moving;
    # at the boundary (0.5) the person walks.
    assert pc.person_anim_state(0.3, 1.5, 0.5, "walk") == "idle"
    assert pc.person_anim_state(0.5, 1.5, 0.5, "walk") == "walk"


def test_person_anim_state_is_hysteresis_free():
    # prev_state never influences the outcome (no hysteresis by construction).
    for speed in (0.0, 0.3, 0.5, 1.2):
        a = pc.person_anim_state(speed, 1.5, 0.5, "idle")
        b = pc.person_anim_state(speed, 1.5, 0.5, "walk")
        assert a == b
        assert a in ("walk", "idle")


def test_person_play_rate_scales_speed_by_walk_ref():
    assert pc.person_play_rate(1.5, 1.5) == 1.0
    assert pc.person_play_rate(3.0, 1.5) == 2.0
    assert pc.person_play_rate(0.75, 1.5) == 0.5


def test_person_play_rate_defaults_to_one_until_walk_ref_set():
    # walk_ref None / non-positive and a standing person all play at 1.0.
    assert pc.person_play_rate(2.0, None) == 1.0
    assert pc.person_play_rate(2.0, 0.0) == 1.0
    assert pc.person_play_rate(2.0, -1.0) == 1.0
    assert pc.person_play_rate(0.0, 1.5) == 1.0


def test_person_yaw_applies_offset_via_normalise_deg():
    assert pc.person_yaw(10.0, 0.0) == 10.0
    assert pc.person_yaw(10.0, 5.0) == 15.0
    assert pc.person_yaw(179.0, 5.0) == -176.0   # wraps through +180
    assert pc.person_yaw(-170.0, -20.0) == 170.0  # wraps through -180
    assert pc.person_yaw(33.0) == 33.0            # default offset 0.0
    assert pc.person_yaw(100.0, 0.0) == normalise_deg(100.0)


# --- spawn / despawn diff -------------------------------------------------


def test_spawn_despawn_diff():
    spawned, despawned = pc.spawn_despawn_diff({1, 2, 3}, {2, 3, 4})
    assert spawned == [4] and despawned == [1]
    spawned, despawned = pc.spawn_despawn_diff(set(), {0, 1})
    assert spawned == [0, 1] and despawned == []
    spawned, despawned = pc.spawn_despawn_diff({0, 1}, set())
    assert spawned == [] and despawned == [0, 1]


# --- actor_dump_v1 --------------------------------------------------------


def _comp(name, cls, asset, wheel_bones=None, steer_bones=None):
    c = {
        "name": name,
        "class": cls,
        "asset": asset,
        "instance_count": None,
        "anim_class": None,
        "skeleton": None,
    }
    if wheel_bones is not None:
        c["wheel_bones"] = wheel_bones
    if steer_bones is not None:
        c["steer_bones"] = steer_bones
    return c


def _vehicle_actor(name="LD_vehicle_12"):
    return {
        "name": name,
        "class": "Actor",
        "label": name,
        "tags": ["ldyf_playback", "uid:vehicle:12"],
        "location": {"x": 1.0, "y": 2.0, "z": 3.0},
        "rotation": {"roll": 0.0, "pitch": 0.0, "yaw": 4.0},
        "components": [
            _comp(
                "PoseableMesh0",
                "PoseableMeshComponent",
                "/Game/Vehicle/vehCar_vehicle02/Mesh/SKM_vehCar_vehicle02",
                wheel_bones=["wheel_front_l", "wheel_front_r", "wheel_rear_l", "wheel_rear_r"],
                steer_bones=["wheel_front_turn_l", "wheel_front_turn_r"],
            )
        ],
    }


def _person_actor(name="LD_person_1"):
    # Shape written by ldyf_playback.dump_actors since lane L7: a mannequin
    # SkeletalMeshComponent whose component carries the current sequence path
    # under the extra "animation" key (anim_class stays None in this module).
    comp = {
        "name": "SkeletalMeshComponent0",
        "class": "SkeletalMeshComponent",
        "asset": "/Engine/Tutorial/SubEditors/TutorialAssets/Character/TutorialTPP",
        "instance_count": None,
        "anim_class": None,
        "skeleton": None,
        "animation": "/Engine/Tutorial/SubEditors/TutorialAssets/Character/Tutorial_Walk_Fwd",
    }
    return {
        "name": name,
        "class": "SkeletalMeshActor",
        "label": name,
        "tags": ["ldyf_playback"],
        "location": {"x": 0.0, "y": 0.0, "z": 0.0},
        "rotation": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
        "components": [comp],
    }


def test_make_actor_dump_accepted_by_world_inventory():
    dump = pc.make_actor_dump(
        [_vehicle_actor(), _person_actor()], level=None, captured_utc="2026-09-03T00:00:00Z"
    )
    assert dump["schema_version"] == "actor_dump_v1"
    result = inventory(dump)  # world_inventory accepts the shape without raising
    assert result["schema_version"] == INVENTORY_VERSION
    assert result["level"] is None
    # L7 classifier: a PoseableMeshComponent under /Game/Vehicle/ counts as a
    # skeletal vehicle whose wheel count comes from wheel_bones (4), and the
    # mannequin person (skeletal + "animation" key) is an animated pedestrian.
    assert result["counts_by_role"]["vehicle"] == 1
    assert result["counts_by_role"]["pedestrian"] == 1
    assert result["counts_by_role"]["prop"] == 0
    assert result["vehicles"] == {"count": 1, "with_min_wheels": 1, "pass": True}
    assert result["pedestrians"] == {"count": 1, "skeletal_animated": 1, "pass": True}
    assert result["blockout_count"] == 0
    # No buildings in this dump, so building_kits.pass is False and the overall
    # world_inventory pass is False -- only the per-role passes can be True.
    assert result["pass"] is False
    for a in dump["actors"]:
        for c in a["components"]:
            assert {"name", "class", "asset", "instance_count", "anim_class", "skeleton"} <= set(c)


def test_make_actor_dump_sorts_and_is_deterministic():
    a1, a2 = _person_actor("B_person"), _vehicle_actor("A_vehicle")
    d1 = pc.make_actor_dump([a1, a2], level="/Game/Riverside", captured_utc="2026-09-03T00:00:00Z")
    d2 = pc.make_actor_dump([a2, a1], level="/Game/Riverside", captured_utc="2026-09-03T00:00:00Z")
    assert [x["name"] for x in d1["actors"]] == ["A_vehicle", "B_person"]
    assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)


# --- contact law, C1 (Phase-2 lane P) -------------------------------------
# EVIDENCE_contact_probe.json is the in-editor ground truth: a vehicle at KNOWN
# root 0 has bounds_bottom 23.339940661173188 (extent_z 76.56318646968349);
# at root 5000 bounds_bottom is 5023.339940661173 (identical offset -23.3399);
# a person at root 300 has bounds_bottom 277.2750034718102 -> offset +22.725.


def test_bounds_bottom_is_origin_z_minus_extent_z():
    # vehicle_root_0 probe: bottom = origin.z - extent.z = 23.339940661173188
    bottom = pc.bounds_bottom_z(99.90312713085668, 76.56318646968349)
    assert bottom == pytest.approx(23.339940661173188, abs=1e-6)


def test_contact_offset_matches_probe_values_at_known_roots():
    # contact_offset = root_z - bottom, invariant under translation.
    off0 = pc.contact_offset_cm(0.0, 99.90312713085668, 76.56318646968349)
    off5k = pc.contact_offset_cm(5000.0, 5099.903127130857, 76.56318646968349)
    assert off0 == pytest.approx(-23.339940661173188, abs=1e-6)
    assert off5k == pytest.approx(-23.339940661173387, abs=1e-6)
    assert off0 == pytest.approx(off5k, abs=1e-6)
    # person_root_300 probe -> offset +22.72499652818982
    offp = pc.contact_offset_cm(300.0, 386.6543091366325, 109.37930561482239)
    assert offp == pytest.approx(22.72499652818982, abs=1e-6)


def test_placed_root_z_puts_bottom_on_surface_and_contact_error_is_zero():
    # root_z = record_z + surface_z + offset => bottom lands exactly at
    # record_z + surface_z, so contact_error_cm == 0 (the C1 verification law).
    record_z, surface_z = 0.0, 20.0
    offset = -23.339940661173188
    root = pc.placed_root_z(record_z, surface_z, offset)
    bottom = root - offset                     # bottom = root_z - contact_offset
    assert bottom == pytest.approx(record_z + surface_z, abs=1e-9)
    assert pc.contact_error_cm(bottom, record_z, surface_z) == pytest.approx(0.0, abs=1e-9)


def test_contact_error_is_absolute_difference_from_ground_plane():
    assert pc.contact_error_cm(100.0, 0.0, 20.0) == 80.0
    assert pc.contact_error_cm(19.0, 0.0, 20.0) == 1.0
    assert pc.contact_error_cm(21.0, 0.0, 20.0) == 1.0


# --- frame player authority, C3 (Phase-2 lane P) --------------------------


def test_frame_presentation_time_is_frame_over_fps():
    # C2 sample frames at fps 10: 1000 -> 100 s, 1500 -> 150 s, 3000 -> 300 s.
    assert pc.frame_presentation_time(1000, 10.0) == 100.0
    assert pc.frame_presentation_time(1500, 10.0) == 150.0
    assert pc.frame_presentation_time(3000, 10.0) == 300.0
    assert pc.frame_presentation_time(24, 24.0) == 1.0
    assert pc.frame_presentation_time(0, 24.0) == 0.0


def test_frame_presentation_time_rejects_bad_arguments():
    with pytest.raises(ValueError):
        pc.frame_presentation_time(-1, 10.0)
    with pytest.raises(ValueError):
        pc.frame_presentation_time(0, 0.0)
    with pytest.raises(ValueError):
        pc.frame_presentation_time(1.5, 10.0)   # frame must be an int


def test_frame_to_sim_time_is_t_begin_plus_presentation_times_rate():
    # C3 authority: sim_time = t_begin + presentation_time * rate.
    assert pc.frame_to_sim_time(1000, 10.0, 1.0, 0.0) == 100.0
    assert pc.frame_to_sim_time(1500, 10.0, 1.0, 0.0) == 150.0
    assert pc.frame_to_sim_time(3000, 10.0, 1.0, 0.0) == 300.0
    assert pc.frame_to_sim_time(1500, 10.0, 2.0, 0.0) == 300.0   # rate 2
    assert pc.frame_to_sim_time(100, 10.0, 1.0, 40.0) == 50.0    # t_start 40 s
    assert pc.frame_to_sim_time(0, 10.0, 1.0, 7.0) == 7.0        # frame 0 = t_start


def test_frame_to_sim_time_rejects_nonpositive_rate():
    with pytest.raises(ValueError):
        pc.frame_to_sim_time(10, 10.0, 0.0)
    with pytest.raises(ValueError):
        pc.frame_to_sim_time(10, 10.0, -1.0)


# --- profiling buckets (Phase-2 lane P) -----------------------------------


def test_new_profile_buckets_has_exactly_the_frozen_names():
    b = pc.new_profile_buckets()
    assert set(b) == set(pc.PROFILE_BUCKETS)
    assert set(pc.PROFILE_BUCKETS) == {"lookup", "transforms", "wheels", "anim", "spawn", "other"}
    assert all(v == 0.0 for v in b.values())


def test_profile_add_accumulates_and_rejects_unknown_buckets():
    b = pc.new_profile_buckets()
    pc.profile_add(b, "lookup", 1.0)
    pc.profile_add(b, "lookup", 0.5)
    pc.profile_add(b, "other", 0.25)
    assert b["lookup"] == 1.5 and b["other"] == 0.25
    with pytest.raises(ValueError):
        pc.profile_add(b, "unknown", 1.0)


def test_profile_summary_totals_and_per_tick_averages():
    b = {"lookup": 0.12, "transforms": 0.06, "wheels": 0.0,
         "anim": 0.02, "spawn": 0.0, "other": 0.0}
    s = pc.profile_summary(b, 60)
    assert s["ticks"] == 60
    assert s["total_s"] == pytest.approx(0.2)
    assert s["totals_s"] == b
    assert s["per_tick_avg_s"]["lookup"] == pytest.approx(0.002)
    assert s["per_tick_avg_s"]["wheels"] == 0.0
    # every bucket appears in both totals and averages
    assert set(s["per_tick_avg_s"]) == set(pc.PROFILE_BUCKETS)
    assert set(s["totals_s"]) == set(pc.PROFILE_BUCKETS)


def test_profile_summary_with_zero_ticks_is_zero_not_error():
    s = pc.profile_summary(pc.new_profile_buckets(), 0)
    assert s["ticks"] == 0 and s["total_s"] == 0.0
    assert all(v == 0.0 for v in s["per_tick_avg_s"].values())


# --- deterministic paint variant (Phase-2 lane P) -------------------------


def test_pick_variant_index_is_deterministic_sha256_and_in_range():
    for uid in ("vehicle:0", "vehicle:vehBus_vehicle10", "person:7"):
        v = pc.pick_variant_index(uid, 5)
        assert v == pc.pick_variant_index(uid, 5)
        assert 0 <= v < 5
        digest = hashlib.sha256(uid.encode("utf-8")).digest()
        assert v == int.from_bytes(digest[:8], "little") % 5


def test_pick_variant_index_spreads_over_uids_and_rejects_bad_counts():
    picked = {pc.pick_variant_index(f"vehicle:{i}", 5) for i in range(200)}
    assert len(picked) > 1          # not constant
    assert picked <= set(range(5))
    with pytest.raises(ValueError):
        pc.pick_variant_index("vehicle:0", 0)
    with pytest.raises(ValueError):
        pc.pick_variant_index("vehicle:0", 2.5)


# --- placed-actor snapshot, C2 shape (Phase-2 lane P) ---------------------


def test_build_placed_snapshot_sorts_by_label_and_carries_c2_fields():
    rows = [
        {"label": "LD_b", "uid": "vehicle:2", "x": 10.0, "y": 20.0,
         "root_z": 30.0, "bottom_z": 25.0, "yaw": 90.0},
        {"label": "LD_a", "uid": "vehicle:1", "x": 1.0, "y": 2.0,
         "root_z": 3.0, "bottom_z": 1.0, "yaw": 0.0},
    ]
    doc = pc.build_placed_snapshot(rows, surface_z_cm=20.0)
    assert doc["schema_version"] == "snapshot_placed_v1"
    assert doc["surface_z_cm"] == 20.0 and doc["count"] == 2
    assert [a["label"] for a in doc["actors"]] == ["LD_a", "LD_b"]
    for a in doc["actors"]:
        # every row the verifier compares is present for every actor
        assert {"label", "uid", "x", "y", "root_z", "bottom_z", "yaw"} <= set(a)


def test_build_placed_snapshot_is_byte_deterministic():
    rows = [
        {"label": "LD_a", "uid": "u1", "x": 1.0, "y": 1.0, "root_z": 1.0,
         "bottom_z": 1.0, "yaw": 0.0},
        {"label": "LD_b", "uid": "u2", "x": 2.0, "y": 2.0, "root_z": 2.0,
         "bottom_z": 2.0, "yaw": 10.0},
    ]
    d1 = pc.build_placed_snapshot(list(reversed(rows)), surface_z_cm=20.0)
    d2 = pc.build_placed_snapshot(rows, surface_z_cm=20.0)
    assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)
    assert d1["actors"] == d2["actors"]
