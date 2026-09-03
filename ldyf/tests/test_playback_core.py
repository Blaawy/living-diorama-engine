"""Unit tests for ldyf/playback_core.py (Phase-2 lane L6 pure arithmetic, L7 persons).

The in-editor player cannot be unit-tested (it imports `unreal`), so every
number it computes lives here and is pinned to the frozen authorities:
record_interp.frame_index_bounds / pose_at, vehicle_kinematics.wheel_angle_deg,
world_inventory.inventory (actor_dump_v1 acceptance). L7 adds the pure
walk/idle state machine, the play-rate scaling and the person yaw offset.

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
