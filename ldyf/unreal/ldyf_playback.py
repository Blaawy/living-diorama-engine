"""Simulation Record playback v2 -- runs INSIDE the Unreal Editor's Python.

Loaded via remote execution (ldyf/unreal_remote.py) or `py ldyf_playback.py`
from the editor console. v2 (Phase-2 lane L6): interpolated kinematic playback
from an in-memory record, real City Sample vehicles on PoseableMeshComponents
with wheel spin / steer, strict spawn-despawn (never parked off-screen), status
/evidence counters and an actor_dump_v1 writer. Persons keep the Phase-1
cylinder placeholder behind ``_REPRESENTATION`` (Phase-2 human mesh decision
pending; the swap is one edit of that row -- see ``set_person_mesh``).

Authority
---------
Presentation only. It reads a sealed record and moves actors kinematically.
Nothing writes simulation truth and nothing it draws feeds back into the
simulation. All pose/spin/mesh/dump arithmetic lives in the pure
``ldyf.playback_core`` (unit-tested). Importing the ldyf package in-editor
needs WORKSPACE on the editor's sys.path (probe #3); the previous version's
docstring said that precondition does NOT hold today, so byte-identical local
replicas of the pure helpers are kept here and ``status()`` reports which
source was used (``interp_core``).

Interpolation
-------------
Each tick advances sim time ``t = t_begin + elapsed * rate`` and computes the
pose with record_interp ``frame_index_bounds`` + ``pose_at`` semantics
(record_interp.py:39-65, 135-158) over the record held in memory -- never per
actor per tick file re-reads. ``status()["frame"]`` stays the bracket floor i0
so the Phase-1 pin/verify contract holds (playback_verify.py:85 pins with
``max_frames = frame + 1`` and checks ``status()["frame"] == check_frame``,
line 117); at an exact frame time alpha == 0 so the pose equals the record
exactly.

Spawn/despawn
-------------
An actor exists only while the pose semantics give it a pose: drawable iff
``t in [t(first_present_frame), t(last_present_frame)]`` (spawn at the first
present frame boundary, despawn at the first absent frame boundary -- the
player and the verifier share this one definition). Hidden-but-alive is NOT
used; despawn destroys the actor and respawn recreates it. (Pooling with
``set_actor_hidden_in_game`` + ``set_is_temporarily_hidden_in_editor`` was
allowed by the lane; destroy/spawn was chosen because the actor_dump can then
tell every spawned actor apart and there is no parked state to audit.)

Ground offset
-------------
The asset ``SkeletalMesh.get_bounds()`` is degenerate (EVIDENCE_editor_api_
probe.json lines 115-124), so the ground offset is measured once per mesh from
the SPAWNED actor: ``unreal.SystemLibrary.get_actor_bounds(actor)``
returns (origin, extent); offset_z = extent.z - origin.z is cached per mesh
path in ``_GROUND_CACHE`` and reported in ``status()``.

Record layout (little-endian), from ldyf.sumo_record: per frame uint32 count,
then count x <Ifffff>: actor_index, x_cm, y_cm, z_cm, yaw_deg, speed_mps.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import struct
import time
from pathlib import Path

import unreal  # type: ignore[import-not-found]

_SAMPLE = struct.Struct("<Ifffff")
_COUNT = struct.Struct("<I")

# Pure arithmetic source: package ldyf.playback_core when WORKSPACE is on the
# editor's sys.path, else the byte-identical local replicas further below.
try:  # pragma: no cover - exercised only in the live editor
    from ldyf import playback_core as _PCORE  # type: ignore[import-not-found]
    from ldyf.record_interp import frame_index_bounds as _PKG_BOUNDS  # type: ignore[import-not-found]
    _CORE_SOURCE = "ldyf.playback_core"
except Exception:  # WORKSPACE not on sys.path (probe #3): stay self-contained
    _PCORE = None
    _PKG_BOUNDS = None
    _CORE_SOURCE = "local-replica"

# One global session so repeated `play()` calls replace the previous one.
_SESSION: dict | None = None

# mesh path -> ground offset cm, measured once per mesh from the SPAWNED actor's
# bounds (never from the degenerate asset bounds). Persists across sessions.
_GROUND_CACHE: dict[str, float] = {}

# Representation table. Persons keep the Phase-1 cylinder placeholder; the swap
# is one edit of the "person" row (set_person_mesh writes the same row).
_REPRESENTATION = {
    "vehicle": {"spawn": "poseable_mesh"},
    "person": {
        "mesh": "/Engine/BasicShapes/Cylinder.Cylinder",
        "scale": (0.5, 0.5, 1.75),
        "z": 87.5,
    },
}

# Imported City Sample vehicle meshes (fixed order -> deterministic choice;
# pick uses sha256(uid), never builtin hash() which is salted per process).
_VEHICLE_NAMES = (
    "vehCar_vehicle02", "vehCar_vehicle03", "vehCar_vehicle05", "vehCar_vehicle06",
    "vehCar_vehicle07", "vehCar_vehicle12", "vehCar_vehicle13",
    "vehVan_vehicle01", "vehVan_vehicle09",
    "vehTruck_vehicle04", "vehTruck_vehicle08", "vehTruck_vehicle11",
    "vehBus_vehicle10",
)
_VEHICLE_MESHES = ["/Game/Vehicle/{0}/Mesh/SKM_{0}".format(n) for n in _VEHICLE_NAMES]

# Per-mesh wheel radius in Unreal cm. NOT measured in-editor yet, so every
# entry is None (TODO: measure once per mesh in-editor). While None, spin is
# skipped and counted as wheels_unspun. Radii are never invented here.
_WHEEL_RADIUS_CM: dict[str, float | None] = {p: None for p in _VEHICLE_MESHES}


def load_wheel_radii(path: str) -> dict:
    """Load per-mesh wheel radii MEASURED in-editor (EVIDENCE/PHASE_02/wheel_radii.json:
    bone height above the mesh's local bounds floor). Nothing here is typed."""
    import json as _json
    doc = _json.loads(Path(path).read_text(encoding="utf-8"))
    n = 0
    for mesh, rec in doc.get("wheel_radii", {}).items():
        r = rec.get("wheel_radius_cm")
        if r is not None and r > 0:
            _WHEEL_RADIUS_CM[mesh] = float(r); n += 1
    return {"loaded": n, "meshes": len(_WHEEL_RADIUS_CM), "source": str(path)}


def set_wheel_radii(radii: dict) -> dict:
    for mesh, r in radii.items():
        _WHEEL_RADIUS_CM[mesh] = (float(r) if r is not None else None)
    return {"set": len(radii)}

_METRES_TO_UNREAL_UNITS = 100.0  # ldyf/coords.py:32 METRES_TO_UNREAL_UNITS


# --- local replicas of the pure core (only used when ldyf is not importable) --
# Each is a byte-identical copy of the named authority so in-editor arithmetic
# matches the unit-tested ldyf/playback_core / record_interp / vehicle_kinematics.


def _local_normalise_deg(a: float) -> float:
    """Replica of ldyf.coords.normalise_deg (coords.py:35-46)."""
    a = a % 360.0
    if a > 180.0:
        a -= 360.0
    return a + 0.0


def _local_frame_bounds(manifest: dict, t_seconds: float):
    """Replica of record_interp.frame_index_bounds (record_interp.py:39-65)."""
    clock = manifest["clock"]
    n = clock["frame_count"]
    if n <= 1:
        return (0, 0, 0.0)
    f = (t_seconds - clock["t_begin"]) / clock["step_seconds"]
    r = round(f)
    if abs(f - r) < 1e-9:
        f = float(r)
    if f <= 0.0:
        return (0, 0, 0.0)
    if f >= n - 1:
        return (n - 1, n - 1, 0.0)
    i = int(f)
    if i == f:
        return (i, i, 0.0)
    return (i, i + 1, f - i)


def _local_sample_to_pose(s: tuple) -> dict:
    """Replica of record_interp._sample_to_pose (record_interp.py:119-120)."""
    return {"x": s[1], "y": s[2], "z": s[3], "yaw": s[4], "speed": s[5]}


def _local_lerp_pose(s0: tuple, s1: tuple, alpha: float) -> dict:
    """Replica of record_interp._lerp_pose (record_interp.py:123-132)."""
    d = _local_normalise_deg(s1[4] - s0[4])
    return {
        "x": s0[1] + alpha * (s1[1] - s0[1]),
        "y": s0[2] + alpha * (s1[2] - s0[2]),
        "z": s0[3] + alpha * (s1[3] - s0[3]),
        "yaw": _local_normalise_deg(s0[4] + alpha * d),
        "speed": s0[5] + alpha * (s1[5] - s0[5]),
    }


def _local_interp_poses(frames_by_index: dict, manifest: dict, t_seconds: float) -> dict:
    """Replica of playback_core.interpolated_poses (playback_core.py)."""
    clock = manifest["clock"]
    if clock["frame_count"] == 0:
        return {}
    i0, i1, alpha = _local_frame_bounds(manifest, t_seconds)
    out: dict = {}
    if i1 == i0:
        for s in frames_by_index.get(i0, ()):
            out[s[0]] = _local_sample_to_pose(s)
        return out
    f0 = {s[0]: s for s in frames_by_index.get(i0, ())}
    f1 = {s[0]: s for s in frames_by_index.get(i1, ())}
    for idx in sorted(f0.keys() & f1.keys()):
        out[idx] = _local_lerp_pose(f0[idx], f1[idx], alpha)
    return out


def _local_pick_mesh(mesh_paths: list, uid: str) -> str:
    """Replica of playback_core.pick_mesh (playback_core.py)."""
    digest = hashlib.sha256(uid.encode("utf-8")).digest()
    return mesh_paths[int.from_bytes(digest[:8], "little") % len(mesh_paths)]


def _local_accumulate_spin(prev_angle_deg: float, speed_mps: float,
                           wheel_radius_cm: float | None, dt_s: float):
    """Replica of playback_core.accumulate_spin / wheel_angle_deg semantics."""
    if wheel_radius_cm is None or wheel_radius_cm <= 0.0:
        return (None, False)
    rate = 360.0 * speed_mps * _METRES_TO_UNREAL_UNITS / (2.0 * math.pi * wheel_radius_cm)
    return (_local_normalise_deg(prev_angle_deg + rate * dt_s), True)


def _local_steer_yaw(prev_yaw_deg: float, current_yaw_deg: float, max_deg: float = 35.0) -> float:
    """Replica of playback_core.steer_yaw (playback_core.py)."""
    d = _local_normalise_deg(current_yaw_deg - prev_yaw_deg)
    return max(-max_deg, min(max_deg, d))


def _local_make_dump(actors: list, level, captured_utc: str) -> dict:
    """Replica of playback_core.make_actor_dump (actor_dump_v1)."""
    ordered = sorted(actors, key=lambda a: (a.get("name") or ""))
    return {"schema_version": "actor_dump_v1", "level": level,
            "captured_utc": captured_utc, "actors": ordered}


# --- dispatch wrappers: package core when importable, local replica otherwise --

def _frame_bounds(manifest: dict, t_seconds: float):
    if _PKG_BOUNDS is not None:
        return _PKG_BOUNDS(manifest, t_seconds)
    return _local_frame_bounds(manifest, t_seconds)


def _interp_poses(frames_by_index: dict, manifest: dict, t_seconds: float) -> dict:
    if _PCORE is not None:
        return _PCORE.interpolated_poses(frames_by_index, manifest, t_seconds)
    return _local_interp_poses(frames_by_index, manifest, t_seconds)


def _pick_mesh(uid: str) -> str:
    if _PCORE is not None:
        return _PCORE.pick_mesh(_VEHICLE_MESHES, uid)
    return _local_pick_mesh(_VEHICLE_MESHES, uid)


def _accumulate_spin(prev_angle_deg: float, speed_mps: float,
                     wheel_radius_cm: float | None, dt_s: float):
    if _PCORE is not None:
        return _PCORE.accumulate_spin(prev_angle_deg, speed_mps, wheel_radius_cm, dt_s)
    return _local_accumulate_spin(prev_angle_deg, speed_mps, wheel_radius_cm, dt_s)


def _steer_yaw(prev_yaw_deg: float, current_yaw_deg: float) -> float:
    if _PCORE is not None:
        return _PCORE.steer_yaw(prev_yaw_deg, current_yaw_deg)
    return _local_steer_yaw(prev_yaw_deg, current_yaw_deg)


def _make_dump(actors: list, level, captured_utc: str) -> dict:
    if _PCORE is not None:
        return _PCORE.make_actor_dump(actors, level=level, captured_utc=captured_utc)
    return _local_make_dump(actors, level, captured_utc)


# --- record reading (unchanged from v1) ------------------------------------


def _load_frames(frames_path: Path) -> list[list[tuple]]:
    """Read every frame into memory once; 23 MB for 600 s -- trivial in-editor."""
    data = frames_path.read_bytes()
    frames: list[list[tuple]] = []
    off = 0
    n_total = len(data)
    while off + _COUNT.size <= n_total:
        (n,) = _COUNT.unpack_from(data, off)
        off += _COUNT.size
        rows = []
        for _ in range(n):
            rows.append(_SAMPLE.unpack_from(data, off))
            off += _SAMPLE.size
        frames.append(rows)
    return frames


def _resolve_frames_path(rd: Path, manifest: dict) -> Path:
    """The manifest names its binary; never let that name escape the record dir."""
    rel = str(manifest["binary"]["file"])
    if rel.startswith(("/", "\\")) or ".." in Path(rel).parts or ":" in rel:
        raise ValueError(f"record binary path is not a safe relative path: {rel!r}")
    p = (rd / rel).resolve()
    if rd.resolve() not in p.parents:
        raise ValueError(f"record binary path escapes the record directory: {rel!r}")
    return p


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- spawning ---------------------------------------------------------------


def _add_component(actor, cls):
    """Proven UE 5.8 route (ldyf/unreal/ldyf_roads_editor.py:38-50, editor probe):
    AActor has no add_component_by_class in Python; the Subobject Data Subsystem
    creates the subobject and get_associated_object resolves the instance."""
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    handles = sub.k2_gather_subobject_data_for_instance(actor)
    params = unreal.AddNewSubobjectParams(parent_handle=handles[0], new_class=cls, blueprint_context=None)
    handle, fail = sub.add_new_subobject(params)
    data = sub.k2_find_subobject_data_from_handle(handle)
    obj = unreal.SubobjectDataBlueprintFunctionLibrary.get_associated_object(data)
    if obj is None:
        raise RuntimeError(f"add_new_subobject({cls}) gave no object: {fail}")
    return obj


def _spawn_vehicle(uid: str, label: str, tags: list) -> dict:
    """Spawn an empty Actor + PoseableMeshComponent wearing a deterministic mesh."""
    mesh = _pick_mesh(uid)
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.Actor, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0)
    )
    if actor is None:
        raise RuntimeError(f"spawn_actor_from_class(unreal.Actor) returned None for {label}")
    actor.set_actor_label(label)
    comp = _add_component(actor, unreal.PoseableMeshComponent)
    sk = unreal.EditorAssetLibrary.load_asset(mesh)
    if sk is None:
        raise RuntimeError(f"could not load vehicle mesh asset {mesh!r}")
    try:
        comp.set_skinned_asset_and_update(sk)          # verified editor probe
    except AttributeError:
        comp.set_skeletal_mesh(sk)                      # fallback (unverified name)
    n_bones = comp.get_num_bones()
    bones = [str(comp.get_bone_name(i)) for i in range(n_bones)]
    # Wheel bone names of the other 13 meshes are NOT verified: discover at spawn
    # by scanning for "wheel", excluding "turn" / "no_spin" (verified on
    # vehCar_vehicle02, EVIDENCE lines 72-82). None found -> spin nothing.
    spin = sorted(b for b in bones if "wheel" in b and "turn" not in b and "no_spin" not in b)
    steer = sorted(b for b in bones if "wheel" in b and "turn" in b)
    # Ground offset from the SPAWNED component's bounds, measured at origin with
    # identity rotation, cached per mesh path (asset bounds are degenerate).
    g = _GROUND_CACHE.get(mesh)
    if g is None:
        origin, extent = unreal.SystemLibrary.get_actor_bounds(actor)
        g = float(extent.z - origin.z)
        _GROUND_CACHE[mesh] = g
    actor.set_actor_hidden_in_game(False)
    comp_name = None
    try:
        comp_name = str(comp.get_name())                # unreal.Object.get_name (unverified)
    except Exception:
        comp_name = None
    rec = {
        "actor": actor,
        "comp": comp,
        "comp_name": comp_name,
        "class": "Actor",
        "kind": "vehicle",
        "uid": uid,
        "label": label,
        "tags": tags,
        "mesh": mesh,
        "spin_bones": spin,
        "steer_bones": steer,
        "wheel_radius_cm": _WHEEL_RADIUS_CM.get(mesh),
        "spin_deg": 0.0,
        "steer_deg": 0.0,
        "last_bracket": None,
        "last_pose": {"location": {"x": 0.0, "y": 0.0, "z": 0.0},
                      "rotation": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}},
        "destroyed": False,
    }
    return rec


def _spawn_person(uid: str, label: str, tags: list) -> dict:
    """Phase-1 cylinder placeholder, behind the representation table (swap one edit)."""
    rep = _REPRESENTATION["person"]
    mesh = unreal.EditorAssetLibrary.load_asset(rep["mesh"])
    actor = unreal.EditorLevelLibrary.spawn_actor_from_object(
        mesh, unreal.Vector(0.0, 0.0, -100000.0), unreal.Rotator(0.0, 0.0, 0.0)
    )
    actor.set_actor_label(label)
    actor.set_actor_scale3d(unreal.Vector(*rep["scale"]))
    actor.set_actor_hidden_in_game(False)
    rec = {
        "actor": actor,
        "comp": None,
        "comp_name": None,
        "class": "StaticMeshActor",
        "kind": "person",
        "uid": uid,
        "label": label,
        "tags": tags,
        "mesh": rep["mesh"],
        "spin_bones": [],
        "steer_bones": [],
        "wheel_radius_cm": None,
        "spin_deg": 0.0,
        "steer_deg": 0.0,
        "last_bracket": None,
        "z_off": rep["z"],
        "last_pose": {"location": {"x": 0.0, "y": 0.0, "z": 0.0},
                      "rotation": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}},
        "destroyed": False,
    }
    return rec


def _spawn_actor_for(s, idx: int) -> dict:
    """Spawn whatever kind manifest actor `idx` is; record it in the session."""
    kind = s["kinds"][idx]
    uid = s["uids"][idx]
    label = s["labels"][idx]
    tags = ["ldyf_playback", f"uid:{uid}"]
    if kind == "vehicle":
        rec = _spawn_vehicle(uid, label, tags)
    elif kind == "person":
        rec = _spawn_person(uid, label, tags)
    else:
        raise ValueError(f"record actor {idx} has unsupported kind {kind!r}")
    try:
        rec["actor"].set_tags(tags)   # unreal.Actor.set_tags (unverified name)
    except Exception:
        pass
    s["spawned_records"][idx] = rec
    return rec


# --- per-tick placement -----------------------------------------------------


def _place_actor(s, idx: int, rec: dict, pose: dict, dt_sim: float, i0: int, i1: int) -> None:
    """Move the actor to the interpolated pose; drive spin and steer bones."""
    if rec["kind"] == "vehicle":
        z = pose["z"] + _GROUND_CACHE[rec["mesh"]]
    else:
        z = pose["z"] + _REPRESENTATION["person"]["z"]
    rec["actor"].set_actor_location_and_rotation(
        unreal.Vector(pose["x"], pose["y"], z),
        # unreal.Rotator(roll, pitch, yaw): yaw is the THIRD argument (v1 RT-14).
        unreal.Rotator(0.0, 0.0, pose["yaw"]), False, False
    )
    if rec["kind"] == "vehicle":
        radius = rec["wheel_radius_cm"]
        if rec["spin_bones"] and radius is not None:
            deg, _ = _accumulate_spin(rec["spin_deg"], pose["speed"], radius, dt_sim)
            rec["spin_deg"] = deg
            for b in rec["spin_bones"]:
                try:
                    rec["comp"].set_bone_rotation_by_name(
                        b, unreal.Rotator(0.0, deg, 0.0), unreal.BoneSpaces.COMPONENT_SPACE
                    )
                except Exception:
                    pass
            s["wheels_spun"] += 1
        else:
            s["wheels_unspun"] += 1
            if rec["spin_bones"] and rec["mesh"] not in s["no_spin_meshes"]:
                s["no_spin_meshes"].append(rec["mesh"])  # radius None: TODO measure
        # Steering: heading change between the two bounding record samples,
        # recomputed when the bracket changes, held while crossing it, clamped
        # +-35 deg (documented in playback_core.steer_yaw). Steer-bone yaw axis
        # is unverified (editor probe #1).
        if rec["steer_bones"] and (i0, i1) != rec["last_bracket"]:
            rec["last_bracket"] = (i0, i1)
            steer = rec["steer_deg"]
            if i1 > i0:
                y0 = _yaw_at(s["frames_by_index"], i0, idx)
                y1 = _yaw_at(s["frames_by_index"], i1, idx)
                if y0 is not None and y1 is not None:
                    steer = _steer_yaw(y0, y1)
            rec["steer_deg"] = steer
            for b in rec["steer_bones"]:
                try:
                    rec["comp"].set_bone_rotation_by_name(
                        b, unreal.Rotator(0.0, 0.0, steer), unreal.BoneSpaces.COMPONENT_SPACE
                    )
                except Exception:
                    pass
    rec["last_pose"] = {
        "location": {"x": pose["x"], "y": pose["y"], "z": z},
        "rotation": {"roll": 0.0, "pitch": 0.0, "yaw": pose["yaw"]},
    }


def _yaw_at(frames_by_index: dict, frame_index: int, actor_index: int):
    rows = frames_by_index.get(frame_index, ())
    for s in rows:
        if s[0] == actor_index:
            return s[4]
    return None


# --- public API ------------------------------------------------------------


def play(record_dir: str, playback_rate: float = 1.0, max_frames: int | None = None,
         expected_sha256: str | None = None) -> dict:
    """Start interpolated playback of a Simulation Record. Replaces any session.

    `expected_sha256`, when given by the caller (who got it from the sealed
    ledger/result), must match the binary on disk. The manifest's own
    self-declared hash is also checked; a manifest may not vouch for itself.
    """
    global _SESSION
    stop()

    rd = Path(record_dir)
    manifest = json.loads((rd / "record_manifest.json").read_text(encoding="utf-8"))
    frames_path = _resolve_frames_path(rd, manifest)
    actual = _sha256_file(frames_path)
    if actual != manifest["binary"]["sha256"]:
        raise ValueError("frames.bin does not match the manifest's declared sha256")
    if expected_sha256 is not None and actual != expected_sha256:
        raise ValueError("frames.bin does not match the ledger-bound sha256 the caller expected")
    frames = _load_frames(frames_path)
    step = float(manifest["clock"]["step_seconds"])
    t_begin = float(manifest["clock"]["t_begin"])
    frame_count = len(frames)
    if frame_count == 0:
        raise ValueError("record has no frames")
    if max_frames is not None and max_frames <= 0:
        raise ValueError("max_frames must be > 0")
    max_end = frame_count - 1 if max_frames is None or max_frames > frame_count else max_frames - 1

    actors_meta = manifest["actors"]
    kinds = [a["kind"] for a in actors_meta]
    unknown = sorted({k for k in kinds if k not in _REPRESENTATION})
    if unknown:
        raise ValueError(f"record kinds not in representation table: {unknown}")

    s = {
        "frames": frames,
        "frames_by_index": {i: rows for i, rows in enumerate(frames)},
        "frame_count": frame_count,
        "frame": 0,
        "i0": 0,
        "i1": 0,
        "alpha": 0.0,
        "step": step,
        "t_begin": t_begin,
        "rate": playback_rate,
        "max_end": max_end,
        "manifest": manifest,
        "uids": [a["uid"] for a in actors_meta],
        "labels": [f"LD_{a['uid'].replace(':', '_')}" for a in actors_meta],
        "kinds": kinds,
        "spawned_records": {},          # actor_index -> rec (kept after despawn)
        "visible": set(),
        "visible_now": 0,
        "spawned_session": 0,
        "despawned_session": 0,
        "wheels_spun": 0,
        "wheels_unspun": 0,
        "no_spin_meshes": [],
        "sim_t": t_begin,
        "done": False,
        "ticks": 0,
        "started": time.time(),
        "record_sha256": manifest["binary"]["sha256"],
        "tick_handle": None,
    }

    def on_tick(delta_seconds: float) -> None:
        if _SESSION is not s:
            return
        s["ticks"] += 1
        end_t = s["t_begin"] + s["max_end"] * s["step"]
        if s["sim_t"] < end_t:
            s["sim_t"] = min(s["sim_t"] + delta_seconds * s["rate"], end_t)
        i0, i1, alpha = _frame_bounds(s["manifest"], s["sim_t"])
        s["frame"], s["i0"], s["i1"], s["alpha"] = i0, i0, i1, alpha
        poses = _interp_poses(s["frames_by_index"], s["manifest"], s["sim_t"])
        cur_visible = set(poses)
        dt_sim = delta_seconds * s["rate"]
        spawned, despawned = (
            sorted(cur_visible - s["visible"]),
            sorted(s["visible"] - cur_visible),
        )
        for idx in despawned:
            rec = s["spawned_records"].get(idx)
            if rec is not None and rec["actor"] is not None and not rec["destroyed"]:
                try:
                    rec["actor"].destroy_actor()
                except Exception:
                    pass
                rec["destroyed"] = True
            s["despawned_session"] += 1
        for idx in spawned:
            _spawn_actor_for(s, idx)
            s["spawned_session"] += 1
        for idx, pose in poses.items():
            rec = s["spawned_records"].get(idx)
            if rec is not None and not rec["destroyed"]:
                _place_actor(s, idx, rec, pose, dt_sim, i0, i1)
        s["visible"] = cur_visible
        s["visible_now"] = len(cur_visible)
        if s["sim_t"] >= end_t and not s["done"]:
            s["done"] = True
            if s["tick_handle"] is not None:
                unreal.unregister_slate_post_tick_callback(s["tick_handle"])
                s["tick_handle"] = None

    s["tick_handle"] = unreal.register_slate_post_tick_callback(on_tick)
    _SESSION = s
    return {
        "started": True,
        "frame_count": frame_count,
        "actors_in_record": len(actors_meta),
        "step_seconds": step,
        "record_sha256": s["record_sha256"],
        "interpolation": True,
        "interp_core": _CORE_SOURCE,
        "vehicle_meshes": len(_VEHICLE_MESHES),
    }


def stop() -> dict:
    """Tear down the current session: destroy everything it spawned. Idempotent."""
    global _SESSION
    if _SESSION is None:
        return {"stopped": False, "reason": "no session"}
    s = _SESSION
    if s.get("tick_handle") is not None:
        try:
            unreal.unregister_slate_post_tick_callback(s["tick_handle"])
        except Exception:
            pass
    destroyed = 0
    for rec in s["spawned_records"].values():
        a = rec.get("actor")
        if a is not None and not rec.get("destroyed", False):
            try:
                a.destroy_actor()
                destroyed += 1
                rec["destroyed"] = True
            except Exception:
                pass
    _SESSION = None
    return {
        "stopped": True,
        "frames_played": s["frame"],
        "actors_destroyed": destroyed,
        "spawned_session": s["spawned_session"],
        "despawned_session": s["despawned_session"],
    }


def status() -> dict:
    """Playback evidence: gate counters, current t, frame bounds, sha256 guard."""
    if _SESSION is None:
        return {"active": False}
    s = _SESSION
    alive = sum(1 for r in s["spawned_records"].values() if not r.get("destroyed", False))
    return {
        "active": True,
        "interpolation": True,
        "interp_core": _CORE_SOURCE,
        "frame": s["frame"],
        "frame_lo": s["i0"],
        "frame_hi": s["i1"],
        "alpha": round(s["alpha"], 6),
        "frame_count": s["frame_count"],
        "sim_time_s": round(s["sim_t"], 2),
        "visible_now": s["visible_now"],
        "actors_alive": alive,
        "actors_spawned": len(s["spawned_records"]),
        "spawned_session": s["spawned_session"],
        "despawned_session": s["despawned_session"],
        "wheels_spun": s["wheels_spun"],
        "wheels_unspun": s["wheels_unspun"],
        "wheels_radius_measured": sorted(
            p for p, r in _WHEEL_RADIUS_CM.items() if r is not None
        ),
        "no_spin_meshes": list(s["no_spin_meshes"]),
        "ground_offsets_cm": {p: round(g, 4) for p, g in _GROUND_CACHE.items()},
        "person_mesh": _REPRESENTATION["person"]["mesh"],
        "ticks": s["ticks"],
        "done": s["done"],
        "wall_elapsed_s": round(time.time() - s["started"], 2),
        "record_sha256": s["record_sha256"],
    }


def set_person_mesh(mesh_path: str) -> dict:
    """Swap the person placeholder mesh (one edit behind _REPRESENTATION).

    Phase-2 human mesh decision is pending, so persons keep the cylinder until
    then; this records the intended mesh for future sessions.
    """
    if not isinstance(mesh_path, str) or not mesh_path:
        raise ValueError("set_person_mesh: mesh_path must be a non-empty asset path")
    _REPRESENTATION["person"]["mesh"] = mesh_path
    return {"person_mesh": mesh_path,
            "note": "Phase-2 human mesh pending; person spawn route unchanged"}


def verify_frame(record_dir: str, frame_index: int, sample: int = 5) -> dict:
    """Read one frame from disk and report the transforms the record demands.

    Used by the out-of-process verifier (playback_verify.py): it compares these
    against what the editor actually placed, so playback correctness is
    measured, not assumed. Actors despawned by the pose semantics report
    placed=None (the verifier's pin flow replays up to the pinned frame, where
    every sampled actor is alive).
    """
    rd = Path(record_dir)
    manifest = json.loads((rd / "record_manifest.json").read_text(encoding="utf-8"))
    frames = _load_frames(rd / manifest["binary"]["file"])
    rows = frames[frame_index][:sample]
    out = []
    for idx, x, y, z, yaw, speed in rows:
        rec = _SESSION["spawned_records"].get(idx) if _SESSION else None
        placed = None
        if rec is not None and not rec.get("destroyed", False) and rec["actor"] is not None:
            loc = rec["actor"].get_actor_location()
            rot = rec["actor"].get_actor_rotation()
            placed = {"x": loc.x, "y": loc.y, "yaw": rot.yaw}
        out.append({"actor_index": idx, "uid": manifest["actors"][idx]["uid"],
                    "expected": {"x": x, "y": y, "yaw": yaw}, "placed": placed})
    return {"frame": frame_index, "samples": out}


def dump_actors(out_path: str) -> dict:
    """Write an actor_dump_v1 document for every actor this module spawned.

    Schema matches ldyf.world_inventory (test_world_inventory.py:28-57): actors
    carry class/label/tags/location/rotation/components; components carry
    class/asset/skeleton/anim_class plus truthful extra keys wheel_bones and
    steer_bones. Despawned actors are included with their last placed transform
    and destroyed=True so the inventory can tell destroyed actors apart.
    """
    if _SESSION is None:
        return {"active": False, "reason": "no session"}
    s = _SESSION
    entries = []
    for idx in sorted(s["spawned_records"]):
        rec = s["spawned_records"][idx]
        alive = not rec.get("destroyed", False) and rec["actor"] is not None
        if alive:
            loc = rec["actor"].get_actor_location()
            rot = rec["actor"].get_actor_rotation()
            location = {"x": loc.x, "y": loc.y, "z": loc.z}
            rotation = {"roll": rot.roll, "pitch": rot.pitch, "yaw": rot.yaw}
        else:
            location = rec["last_pose"]["location"]
            rotation = rec["last_pose"]["rotation"]
        if rec["kind"] == "vehicle":
            comps = [{
                "name": rec["comp_name"],
                "class": "PoseableMeshComponent",
                "asset": rec["mesh"],
                "instance_count": None,
                "anim_class": None,
                "skeleton": None,
                "wheel_bones": rec["spin_bones"],
                "steer_bones": rec["steer_bones"],
            }]
        else:
            comps = [{
                "name": None,
                "class": "StaticMeshComponent",
                "asset": rec["mesh"],
                "instance_count": None,
                "anim_class": None,
                "skeleton": None,
            }]
        entry = {
            "name": rec["label"],
            "class": rec["class"],
            "label": rec["label"],
            "tags": list(rec["tags"]),
            "location": location,
            "rotation": rotation,
            "components": comps,
            "destroyed": not alive,
        }
        entries.append(entry)
    captured_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    doc = _make_dump(entries, level=None, captured_utc=captured_utc)
    Path(out_path).write_text(
        json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8"
    )
    return {"active": True, "path": str(out_path), "actors_dumped": len(entries),
            "schema_version": doc["schema_version"]}
