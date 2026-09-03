"""Simulation Record playback v3 -- runs INSIDE the Unreal Editor's Python.

Loaded via remote execution (ldyf/unreal_remote.py) or `py ldyf_playback.py`
from the editor console. v2 (Phase-2 lane L6): interpolated kinematic playback
from an in-memory record, real City Sample vehicles on PoseableMeshComponents
with wheel spin / steer, strict spawn-despawn, status/evidence counters and an
actor_dump_v1 writer. Phase-2 lane L7 swapped persons to the Tutorial mannequin
(SkeletalMeshActor, single-node animation mode) whose idle/walk AnimSequences
are chosen per tick from the record speed, and fixed the ground-offset probe to
the 1-argument ``get_actor_bounds``.

Closure lane P (v3) changes:
  * Contact law (C1): every ground offset is MEASURED at spawn with the mesh at
    a KNOWN root z: ``unreal.SystemLibrary.get_component_bounds(comp)`` returns
    (origin, extent); ``bottom = origin.z - extent.z``;
    ``contact_offset = root_z - bottom``; cached per mesh path
    (``_CONTACT_CACHE``). Placement is ``root_z = record_z + surface_z +
    contact_offset`` where ``surface_z`` is an explicit argument the driver
    sets via ``set_surface_z(cm)`` (loaded from road_mesh_bounds.json). Until a
    caller sets it, placement errors -- surface_z is NEVER a typed default.
    Ground truth for the formula and API name: EVIDENCE_contact_probe.json (a
    vehicle at KNOWN root 0 -> bounds_bottom 23.3399, offset -23.3399; root
    5000 -> 5023.3399, same offset; person at root 300 -> offset +22.725).
    ``contact_offsets()`` reports the cache; ``measure_contact(label)`` reads
    the CURRENT world bottom of a placed actor for the 3D verifier.
  * Pooling: actors are never destroy/spawned per tick. A pool is kept per mesh
    path; on despawn the actor is hidden (``set_actor_hidden_in_game(True)`` +
    ``set_is_temporarily_hidden_in_editor(True)``), moved to z = -1e6 and
    tagged ``ld_pooled``; on respawn it is retagged/unhidden from the pool.
    Pool sizes are reported by ``status()``; the level dump lists pooled actors
    with the ``ld_pooled`` tag so the inventory can tell them apart.
  * Profiling: each placement pass accumulates wall time in the frozen buckets
    lookup/transforms/wheels/anim/spawn/other (pure accounting lives in
    ``ldyf.playback_core``); ``status()`` reports totals and per-tick averages;
    ``profile_reset()`` zeroes them.
  * Deterministic frame player (C3): ``frame_player_begin(fps, rate, t_start_s)``
    / ``frame_player_place(frame)`` / ``frame_player_end()`` place every visible
    actor exactly as the interactive player would at sim time
    ``t_begin + presentation_time * rate`` with presentation_time = frame / fps.
    No slate tick is registered and no wall clock feeds the pose path.
  * Snapshots for the 3D verifier: ``snapshot_placed(surface_z_cm)`` returns a
    snapshot_placed_v1 document (label, uid, x, y, root_z, bottom_z, yaw) for
    every visible actor, bottom measured from ``get_component_bounds`` NOW.
  * Deterministic visuals: the vehicle mesh and the paint variant come from a
    sha256 digest of the uid (playback_core.pick_mesh / pick_variant_index --
    never salted builtin hash()). ``set_vehicle_paint_fn(fn)`` registers the
    integrator's colour hook, called with (component, uid, variant_index) after
    every activation; the default hook body is empty.
  * All v2 public functions keep working: play, status, stop, verify_frame,
    dump_actors, set_person_params, set_person_mesh, load_wheel_radii.

Authority
---------
Presentation only. It reads a sealed record and moves actors kinematically.
Nothing writes simulation truth and nothing it draws feeds back into the
simulation. All pose/spin/mesh/dump/contact/frame arithmetic lives in the pure
``ldyf.playback_core`` (unit-tested). Importing the ldyf package in-editor
needs WORKSPACE on the editor's sys.path (probe #3); when that precondition
does NOT hold, byte-identical local replicas of the pure helpers are kept here
and ``status()`` reports which source was used (``interp_core``).

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

Spawn/despawn and pooling
-------------------------
An actor exists only while the pose semantics give it a pose: drawable iff
``t in [t(first_present_frame), t(last_present_frame)]`` (spawn at the first
present frame boundary, despawn at the first absent frame boundary -- the
player, the frame player and the verifier share this one definition). Despawn
never destroys: the actor is hidden, parked at z = -1e6 and tagged ``ld_pooled``
into the per-mesh pool; a later spawn of the same mesh reactivates a pooled
actor (retagged with the new uid, relabelled). ``stop()`` destroys everything
still alive.

Contact law
-----------
The asset ``SkeletalMesh.get_bounds()`` is degenerate (EVIDENCE_editor_api_
probe.json lines 115-124), so the contact offset is measured once per mesh from
the SPAWNED component: ``unreal.SystemLibrary.get_component_bounds(comp)``
returns (origin, extent); bottom = origin.z - extent.z;
contact_offset = root_z - bottom, cached per mesh path in ``_CONTACT_CACHE``.
The measured offset is invariant under vertical translation
(EVIDENCE_contact_probe.json: root 0 and root 5000 give the same offset), so a
cache entry measured at the spawn root stays valid for every later placement.

Record layout (little-endian), from ldyf.sumo_record: per frame uint32 count,
then count x <Ifffff>: actor_index, x_cm, y_cm, z_cm, yaw_deg, speed_mps.

Unreal API names used here and NOT yet probed in the live editor (one-line
probes for the integrator):
  * ``actor.set_is_temporarily_hidden_in_editor(True/False)`` -- lane-L7 named;
    probe: spawn any actor, hide, assert it is hidden in the editor viewport.
  * ``unreal.SystemLibrary.get_component_bounds(comp)`` -- C1/lane named
    (contact probe measured its results); probe: print the returned tuple type.
  * ``actor.set_tags(list)`` / ``actor.set_actor_label(str)`` -- in use since
    v1/v2; probe: read back ``actor.tags`` / ``actor.get_actor_label()``.
  * ``unreal.Actor.set_actor_hidden_in_game(bool)`` -- lane named; probe:
    assert the viewport no longer shows the actor.
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

# mesh path -> contact offset cm (root_z - bottom), measured once per mesh from
# the SPAWNED component's bounds at a KNOWN root z (C1; see EVIDENCE_contact_
# probe.json). Persists across sessions.
_CONTACT_CACHE: dict[str, float] = {}

# C1 surface argument: measured top of the road strip mesh (road_mesh_bounds.
# json, 20 cm) -- set by the driver via set_surface_z(cm). None until set and
# NEVER a typed number: placement errors while None.
_SURFACE_Z_CM: float | None = None
_SURFACE_Z_SOURCE: str | None = None

# Integrator paint hook (default empty). Called with (component, uid,
# variant_index) after every pool activation; the paint mechanism itself is
# verified separately by the integrator, so failures here never break playback.
_PAINT_FN = None
# Paint variant count -- explicit presentation argument for the colour hook.
_VEHICLE_PAINT_VARIANTS = 5

# Pool parking depth (far below the world) and pooled marker tag.
_POOLED_Z = -1000000.0
_LD_POOLED_TAG = "ld_pooled"

# Person presentation arguments (Phase-2 L7). No typed numbers in the
# representation row: walk_ref_speed_mps (the speed at which the walk cycle
# plays at rate 1.0), idle_below_mps (speeds strictly below it idle) and the
# Tutorial-mesh facing correction person_yaw_offset_deg are all set via
# set_person_params(); until walk_ref / idle_below are set persons play the
# walk cycle at rate 1.0 and walk at ANY speed > 0 (person_params_unset=True).
_PERSON_PARAMS: dict = {
    "walk_ref_speed_mps": None,
    "idle_below_mps": None,
    "person_yaw_offset_deg": 0.0,
}

# Representation table. The "person" row (L7): Tutorial mannequin mesh + the
# walk/idle AnimSequences the editor probe verified load and play
# (EVIDENCE_human_fallback_probe.json). walk_ref_speed_mps / idle_below_mps
# stay None here (arguments, see _PERSON_PARAMS / set_person_params) and "z"
# is None because the contact offset is measured per mesh from the spawned
# component's bounds (C1), never typed.
_REPRESENTATION = {
    "vehicle": {"spawn": "poseable_mesh"},
    "person": {
        "mesh": "/Engine/Tutorial/SubEditors/TutorialAssets/Character/TutorialTPP",
        "walk": "/Engine/Tutorial/SubEditors/TutorialAssets/Character/Tutorial_Walk_Fwd",
        "idle": "/Engine/Tutorial/SubEditors/TutorialAssets/Character/Tutorial_Idle",
        "walk_ref_speed_mps": None,
        "idle_below_mps": None,
        "z": None,
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
    spin-bone height above the mesh origin plane). Nothing here is typed."""
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


def _local_pick_variant_index(uid: str, n_variants: int) -> int:
    """Replica of playback_core.pick_variant_index (playback_core.py)."""
    digest = hashlib.sha256(uid.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little") % n_variants


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


def _local_person_anim_state(speed: float, walk_ref, idle_below, prev_state: str = "idle") -> str:
    """Replica of playback_core.person_anim_state (playback_core.py)."""
    if idle_below is not None and speed < idle_below:
        return "idle"
    if speed > 0.0:
        return "walk"
    return "idle"


def _local_person_play_rate(speed: float, walk_ref) -> float:
    """Replica of playback_core.person_play_rate (playback_core.py)."""
    if walk_ref is None or walk_ref <= 0.0 or speed <= 0.0:
        return 1.0
    return speed / walk_ref


def _local_person_yaw(record_yaw_deg: float, offset_deg: float = 0.0) -> float:
    """Replica of playback_core.person_yaw (playback_core.py)."""
    return _local_normalise_deg(record_yaw_deg + offset_deg)


def _local_make_dump(actors: list, level, captured_utc: str) -> dict:
    """Replica of playback_core.make_actor_dump (actor_dump_v1)."""
    ordered = sorted(actors, key=lambda a: (a.get("name") or ""))
    return {"schema_version": "actor_dump_v1", "level": level,
            "captured_utc": captured_utc, "actors": ordered}


def _local_frame_presentation_time(frame: int, fps: float) -> float:
    """Replica of playback_core.frame_presentation_time (C3: frame / fps)."""
    if fps is None or fps <= 0.0:
        raise ValueError(f"frame_presentation_time: fps must be > 0, got {fps!r}")
    if not isinstance(frame, int) or frame < 0:
        raise ValueError(f"frame_presentation_time: frame must be an int >= 0, got {frame!r}")
    return frame / float(fps)


def _local_frame_to_sim_time(frame: int, fps: float, rate: float = 1.0,
                             t_start_s: float = 0.0) -> float:
    """Replica of playback_core.frame_to_sim_time (C3: t_start + (frame/fps)*rate)."""
    if rate is None or rate <= 0.0:
        raise ValueError(f"frame_to_sim_time: rate must be > 0, got {rate!r}")
    return float(t_start_s) + _local_frame_presentation_time(frame, fps) * float(rate)


_LOCAL_PROFILE_BUCKETS = ("lookup", "transforms", "wheels", "anim", "spawn", "other")


def _local_new_profile_buckets() -> dict:
    """Replica of playback_core.new_profile_buckets."""
    return {name: 0.0 for name in _LOCAL_PROFILE_BUCKETS}


def _local_profile_add(buckets: dict, name: str, seconds: float) -> None:
    """Replica of playback_core.profile_add."""
    if name not in _LOCAL_PROFILE_BUCKETS:
        raise ValueError(
            f"profile_add: unknown bucket {name!r}; expected one of {_LOCAL_PROFILE_BUCKETS}"
        )
    buckets[name] += seconds


def _local_profile_summary(buckets: dict, ticks: int) -> dict:
    """Replica of playback_core.profile_summary."""
    totals = {name: buckets.get(name, 0.0) for name in _LOCAL_PROFILE_BUCKETS}
    total_s = sum(totals.values())
    return {
        "ticks": ticks,
        "total_s": total_s,
        "totals_s": totals,
        "per_tick_avg_s": {
            name: (totals[name] / ticks if ticks > 0 else 0.0) for name in _LOCAL_PROFILE_BUCKETS
        },
    }


def _local_build_placed_snapshot(rows: list, surface_z_cm: float) -> dict:
    """Replica of playback_core.build_placed_snapshot (snapshot_placed_v1)."""
    actors = sorted((dict(r) for r in rows), key=lambda r: (r.get("label") or ""))
    return {
        "schema_version": "snapshot_placed_v1",
        "surface_z_cm": surface_z_cm,
        "count": len(actors),
        "actors": actors,
    }


def _local_spawn_despawn_diff(prev_visible, curr_visible) -> tuple[list, list]:
    """Replica of playback_core.spawn_despawn_diff."""
    prev_visible = set(prev_visible)
    curr_visible = set(curr_visible)
    return (sorted(curr_visible - prev_visible), sorted(prev_visible - curr_visible))


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


def _pick_variant_index(uid: str, n_variants: int) -> int:
    if _PCORE is not None:
        return _PCORE.pick_variant_index(uid, n_variants)
    return _local_pick_variant_index(uid, n_variants)


def _accumulate_spin(prev_angle_deg: float, speed_mps: float,
                     wheel_radius_cm: float | None, dt_s: float):
    if _PCORE is not None:
        return _PCORE.accumulate_spin(prev_angle_deg, speed_mps, wheel_radius_cm, dt_s)
    return _local_accumulate_spin(prev_angle_deg, speed_mps, wheel_radius_cm, dt_s)


def _steer_yaw(prev_yaw_deg: float, current_yaw_deg: float) -> float:
    if _PCORE is not None:
        return _PCORE.steer_yaw(prev_yaw_deg, current_yaw_deg)
    return _local_steer_yaw(prev_yaw_deg, current_yaw_deg)


def _person_anim_state(speed: float, walk_ref, idle_below, prev_state: str = "idle") -> str:
    if _PCORE is not None:
        return _PCORE.person_anim_state(speed, walk_ref, idle_below, prev_state)
    return _local_person_anim_state(speed, walk_ref, idle_below, prev_state)


def _person_play_rate(speed: float, walk_ref) -> float:
    if _PCORE is not None:
        return _PCORE.person_play_rate(speed, walk_ref)
    return _local_person_play_rate(speed, walk_ref)


def _person_yaw(record_yaw_deg: float, offset_deg: float = 0.0) -> float:
    if _PCORE is not None:
        return _PCORE.person_yaw(record_yaw_deg, offset_deg)
    return _local_person_yaw(record_yaw_deg, offset_deg)


def _make_dump(actors: list, level, captured_utc: str) -> dict:
    if _PCORE is not None:
        return _PCORE.make_actor_dump(actors, level=level, captured_utc=captured_utc)
    return _local_make_dump(actors, level, captured_utc)


def _frame_presentation_time(frame: int, fps: float) -> float:
    if _PCORE is not None:
        return _PCORE.frame_presentation_time(frame, fps)
    return _local_frame_presentation_time(frame, fps)


def _frame_to_sim_time(frame: int, fps: float, rate: float = 1.0,
                       t_start_s: float = 0.0) -> float:
    if _PCORE is not None:
        return _PCORE.frame_to_sim_time(frame, fps, rate, t_start_s)
    return _local_frame_to_sim_time(frame, fps, rate, t_start_s)


def _new_profile_buckets() -> dict:
    if _PCORE is not None:
        return _PCORE.new_profile_buckets()
    return _local_new_profile_buckets()


def _profile_add(buckets: dict, name: str, seconds: float) -> None:
    if _PCORE is not None:
        return _PCORE.profile_add(buckets, name, seconds)
    return _local_profile_add(buckets, name, seconds)


def _profile_summary(buckets: dict, ticks: int) -> dict:
    if _PCORE is not None:
        return _PCORE.profile_summary(buckets, ticks)
    return _local_profile_summary(buckets, ticks)


def _build_placed_snapshot(rows: list, surface_z_cm: float) -> dict:
    if _PCORE is not None:
        return _PCORE.build_placed_snapshot(rows, surface_z_cm)
    return _local_build_placed_snapshot(rows, surface_z_cm)


def _spawn_despawn_diff(prev_visible, curr_visible) -> tuple[list, list]:
    if _PCORE is not None:
        return _PCORE.spawn_despawn_diff(prev_visible, curr_visible)
    return _local_spawn_despawn_diff(prev_visible, curr_visible)


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


# --- spawning / contact measurement / pooling -------------------------------


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


def _measure_contact_cm(mesh_path: str, comp, root_z: float = 0.0) -> float:
    """C1: contact_offset = root_z - bottom, bottom from get_component_bounds.

    Bounds come from unreal.SystemLibrary.get_component_bounds(comp) ->
    (origin, extent); bottom = origin.z - extent.z. The actor is at the KNOWN
    root z given by the caller at measurement time (C1: never subtract an
    absolute bounds origin as if it were local). Cached per mesh path; the
    probe proves the offset is invariant under vertical translation.
    """
    cached = _CONTACT_CACHE.get(mesh_path)
    if cached is not None:
        return cached
    origin, extent = unreal.SystemLibrary.get_component_bounds(comp)
    bottom = float(origin.z) - float(extent.z)
    offset = float(root_z) - bottom
    _CONTACT_CACHE[mesh_path] = offset
    return offset


def _park_actor(actor, comp, x: float, y: float, pooled: bool = True) -> None:
    """Hide an actor and move it far below the world (z = -1e6) for pooling."""
    try:
        actor.set_actor_hidden_in_game(True)
    except Exception:
        pass
    try:
        actor.set_is_temporarily_hidden_in_editor(True)
    except Exception:
        pass
    try:
        actor.set_actor_location_and_rotation(
            unreal.Vector(float(x), float(y), _POOLED_Z),
            unreal.Rotator(0.0, 0.0, 0.0), False, False
        )
    except Exception:
        pass


def _unpark_actor(actor, comp) -> None:
    """Restore a pooled actor to visibility (pool activation, lane P)."""
    try:
        actor.set_actor_hidden_in_game(False)
    except Exception:
        pass
    try:
        actor.set_is_temporarily_hidden_in_editor(False)
    except Exception:
        pass


def _spawn_vehicle(uid: str, label: str, tags: list) -> dict:
    """Create an empty Actor + PoseableMeshComponent wearing a deterministic
    mesh, measure the C1 contact offset at the KNOWN spawn root z = 0, then
    park it in the per-mesh pool (hidden, z = -1e6). Returns the pooled rec."""
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
    # C1 contact law: measure at the KNOWN root z = 0 from the SPAWNED mesh
    # component's bounds (get_component_bounds), never the degenerate asset
    # bounds (EVIDENCE_editor_api_probe.json lines 115-124). See
    # EVIDENCE_contact_probe.json for the formula's ground truth.
    _measure_contact_cm(mesh, comp, root_z=0.0)
    _park_actor(actor, comp, 0.0, 0.0, pooled=True)
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
        "tags": list(tags),
        "mesh": mesh,
        "spin_bones": spin,
        "steer_bones": steer,
        "wheel_radius_cm": _WHEEL_RADIUS_CM.get(mesh),
        "spin_deg": 0.0,
        "steer_deg": 0.0,
        "last_bracket": None,
        "last_pose": {"location": {"x": 0.0, "y": 0.0, "z": _POOLED_Z},
                      "rotation": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}},
        "pooled": True,
        "paint_variant": None,
    }
    return rec


def _spawn_person(uid: str, label: str, tags: list) -> dict:
    """Create the Tutorial mannequin as a SkeletalMeshActor (Phase-2 L7) and
    park it pooled. Verified editor facts (EVIDENCE_human_fallback_probe.json):
    ``spawn_actor_from_object(mesh, loc)`` yields a SkeletalMeshActor whose
    ``skeletal_mesh_component`` accepts ``set_animation_mode(SINGLE_NODE)`` and
    ``play_animation(seq, True)``. The C1 contact offset is measured once per
    mesh from the spawned component's bounds at the KNOWN root z = 0 (C1)."""
    rep = _REPRESENTATION["person"]
    mesh = unreal.EditorAssetLibrary.load_asset(rep["mesh"])
    if mesh is None:
        raise RuntimeError(f"could not load person mesh asset {rep['mesh']!r}")
    actor = unreal.EditorLevelLibrary.spawn_actor_from_object(
        mesh, unreal.Vector(0.0, 0.0, 0.0), unreal.Rotator(0.0, 0.0, 0.0)
    )
    if actor is None:
        raise RuntimeError(f"spawn_actor_from_object gave None for {label}")
    actor.set_actor_label(label)
    comp = actor.skeletal_mesh_component          # verified: SkeletalMeshActor attr
    comp.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
    idle = unreal.EditorAssetLibrary.load_asset(rep["idle"])
    if idle is None:
        raise RuntimeError(f"could not load person idle asset {rep['idle']!r}")
    comp.play_animation(idle, True)               # verified probe: loops (True)
    # C1 contact law: measured once per mesh from the SPAWNED component bounds
    # at the KNOWN root z = 0 (see EVIDENCE_contact_probe.json ground truth).
    _measure_contact_cm(rep["mesh"], comp, root_z=0.0)
    _park_actor(actor, comp, 0.0, 0.0, pooled=True)
    comp_name = None
    try:
        comp_name = str(comp.get_name())          # unreal.Object.get_name (unverified)
    except Exception:
        comp_name = None
    rec = {
        "actor": actor,
        "comp": comp,
        "comp_name": comp_name,
        "class": "SkeletalMeshActor",
        "kind": "person",
        "uid": uid,
        "label": label,
        "tags": list(tags),
        "mesh": rep["mesh"],
        "spin_bones": [],
        "steer_bones": [],
        "wheel_radius_cm": None,
        "spin_deg": 0.0,
        "steer_deg": 0.0,
        "anim_state": "idle",     # current walk/idle choice (pure state machine)
        "anim_seq": rep["idle"],  # current sequence path (dump_actors reports it)
        "last_bracket": None,
        "last_pose": {"location": {"x": 0.0, "y": 0.0, "z": _POOLED_Z},
                      "rotation": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0}},
        "pooled": True,
    }
    return rec


def _mesh_path_for(s: dict, idx: int) -> str:
    """Deterministic mesh path the record actor `idx` presents with."""
    kind = s["kinds"][idx]
    if kind == "vehicle":
        return _pick_mesh(s["uids"][idx])
    return _REPRESENTATION["person"]["mesh"]


def _ensure_pool_rec(s: dict, idx: int, mesh: str) -> dict:
    """Create (parked) and register one rec for actor idx into the mesh pool."""
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
        rec["actor"].set_tags(list(tags) + [_LD_POOLED_TAG])   # set_tags (unverified name)
    except Exception:
        pass
    s["pools"].setdefault(mesh, []).append(rec)
    return rec


def _activate_rec(s: dict, idx: int, rec: dict) -> None:
    """Bring a (possibly reused) pooled actor live for record actor `idx`.

    Pool reuse retargets the actor: new label/tags/uid/paint, kinematic state
    reset to a fresh spawn (spin 0, steer 0, person back to the idle loop).
    """
    actor = rec["actor"]
    label = s["labels"][idx]
    uid = s["uids"][idx]
    tags = ["ldyf_playback", f"uid:{uid}"]
    try:
        actor.set_actor_label(label)               # set_actor_label (in use since v1)
    except Exception:
        pass
    try:
        actor.set_tags(tags)                       # set_tags (unverified name)
    except Exception:
        pass
    _unpark_actor(actor, rec["comp"])
    rec["uid"] = uid
    rec["label"] = label
    rec["tags"] = list(tags)
    rec["pooled"] = False
    rec["spin_deg"] = 0.0
    rec["steer_deg"] = 0.0
    rec["last_bracket"] = None
    if rec["kind"] == "person":
        rec["anim_state"] = "idle"
        idle_path = _REPRESENTATION["person"]["idle"]
        rec["anim_seq"] = idle_path
        idle = unreal.EditorAssetLibrary.load_asset(idle_path)
        if idle is not None:
            try:
                rec["comp"].play_animation(idle, True)
            except Exception:
                pass
    _apply_paint(rec)


def _apply_paint(rec: dict) -> None:
    """Deterministic paint variant per uid; default hook body is empty.

    The paint mechanism is verified separately by the integrator, so a failing
    hook never breaks playback: it is called with (component, uid,
    variant_index) after every activation and its errors are swallowed here.
    """
    rec["paint_variant"] = _pick_variant_index(rec["uid"], _VEHICLE_PAINT_VARIANTS)
    fn = _PAINT_FN
    if fn is None:
        return
    try:
        fn(rec["comp"], rec["uid"], rec["paint_variant"])
    except Exception:
        pass


def _activate_index(s: dict, idx: int) -> dict:
    """Activate record actor idx: reuse a pooled actor of its mesh if one is
    parked, otherwise create one. Returns (rec, created_bool)."""
    mesh = _mesh_path_for(s, idx)
    pool = s["pools"].setdefault(mesh, [])
    if pool:
        rec = pool.pop()
        created = False
    else:
        rec = _ensure_pool_rec(s, idx, mesh)
        created = True
    _activate_rec(s, idx, rec)
    s["spawned_records"][idx] = rec
    if created:
        s["spawned_session"] += 1
    else:
        s["pool_reactivations"] += 1
    return rec


def _pool_actor(s: dict, idx: int) -> bool:
    """Despawn without destroying: hide, park at z = -1e6, tag ld_pooled, into
    the per-mesh pool. Returns True when an active actor was pooled."""
    rec = s["spawned_records"].pop(idx, None)
    if rec is None:
        return False
    actor = rec["actor"]
    if actor is None:
        return False
    last = rec["last_pose"]["location"]
    _park_actor(actor, rec["comp"], last["x"], last["y"], pooled=True)
    try:
        actor.set_tags(list(rec["tags"]) + [_LD_POOLED_TAG])   # set_tags (unverified name)
    except Exception:
        pass
    rec["pooled"] = True
    rec["last_pose"]["location"]["z"] = _POOLED_Z
    mesh = rec["mesh"]
    s["pools"].setdefault(mesh, []).append(rec)
    s["despawned_session"] += 1
    return True


# --- placement (shared by the interactive player and the frame player) -------


def _yaw_at(frames_by_index: dict, frame_index: int, actor_index: int):
    rows = frames_by_index.get(frame_index, ())
    for s in rows:
        if s[0] == actor_index:
            return s[4]
    return None


def _place_visible(s: dict, idx: int, rec: dict, pose: dict, dt_sim: float,
                   i0: int, i1: int, prof: dict, acc: dict) -> None:
    """Move one active actor to the interpolated pose; drive spin/steer and
    person anim. Wall time is accumulated into the profiling buckets
    transforms/wheels/anim (acc carries the running totals for the pass)."""
    surface_z = _SURFACE_Z_CM
    if surface_z is None:
        raise RuntimeError(
            "C1: surface_z is not set; call set_surface_z(cm) before placement "
            "(never a typed default)"
        )
    # C1 placement law: root_z = record_z + surface_z + contact_offset. The
    # offset was measured from this mesh's spawned bounds at a KNOWN root.
    offset = _CONTACT_CACHE[rec["mesh"]]
    z = pose["z"] + surface_z + offset
    if rec["kind"] == "person":
        # The Tutorial mannequin's facing convention (+X or not) is NOT
        # verified; record yaw gets person_yaw_offset_deg (an argument,
        # default 0.0) added and normalised via coords.normalise_deg semantics.
        yaw = _person_yaw(pose["yaw"], _PERSON_PARAMS["person_yaw_offset_deg"])
    else:
        yaw = pose["yaw"]
    _t0 = time.perf_counter()
    rec["actor"].set_actor_location_and_rotation(
        unreal.Vector(pose["x"], pose["y"], z),
        # unreal.Rotator(roll, pitch, yaw): yaw is the THIRD argument (v1 RT-14).
        unreal.Rotator(0.0, 0.0, yaw), False, False
    )
    acc["transforms"] += time.perf_counter() - _t0
    rec["last_pose"] = {
        "location": {"x": pose["x"], "y": pose["y"], "z": z},
        "rotation": {"roll": 0.0, "pitch": 0.0, "yaw": yaw},
    }
    if rec["kind"] == "person":
        _t0 = time.perf_counter()
        walk_ref = _PERSON_PARAMS["walk_ref_speed_mps"]
        state = _person_anim_state(
            pose["speed"], walk_ref, _PERSON_PARAMS["idle_below_mps"],
            rec.get("anim_state", "idle"),
        )
        # Switch the looped sequence ONLY when the state changes; a person who
        # keeps walking never restarts the cycle every tick.
        if state != rec.get("anim_state"):
            seq_path = (_REPRESENTATION["person"]["walk"] if state == "walk"
                        else _REPRESENTATION["person"]["idle"])
            seq = unreal.EditorAssetLibrary.load_asset(seq_path)
            if seq is not None:
                try:
                    rec["comp"].play_animation(seq, True)
                except Exception:
                    pass
            rec["anim_state"] = state
            rec["anim_seq"] = seq_path
        # play rate = speed / walk_ref while walking (1.0 until walk_ref is set
        # and for the idle loop) -- playback_core.person_play_rate semantics.
        rate = _person_play_rate(pose["speed"] if state == "walk" else 0.0, walk_ref)
        try:
            rec["comp"].set_play_rate(rate)
        except Exception:
            pass
        acc["anim"] += time.perf_counter() - _t0
        return
    # vehicle wheels
    _t0 = time.perf_counter()
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
    acc["wheels"] += time.perf_counter() - _t0


def _present(s: dict, sim_t: float, dt_sim: float) -> dict:
    """Place every visible actor exactly as the interactive player would at sim
    time `sim_t` (shared by the slate-tick player and the frame player).

    Buckets: lookup (bracket + interpolation), spawn (pool activation /
    deactivation), transforms, wheels, anim; everything else -> other. Returns
    placement counts for the caller's report. When surface_z is unset the pass
    is skipped and s["surface_z_error"] carries the C1 message (the caller --
    frame_player_place / snapshot_placed -- turns that into a raised error).
    """
    prof = s["profile"]
    _t0 = time.perf_counter()
    i0, i1, alpha = _frame_bounds(s["manifest"], sim_t)
    poses = _interp_poses(s["frames_by_index"], s["manifest"], sim_t)
    s["frame"], s["i0"], s["i1"], s["alpha"] = i0, i0, i1, alpha
    _profile_add(prof, "lookup", time.perf_counter() - _t0)

    surface_z = _SURFACE_Z_CM
    if surface_z is None:
        msg = ("C1: surface_z is not set; call set_surface_z(cm) before placement "
               "(never a typed default); placement skipped")
        s["surface_z_error"] = msg
        return {"visible": 0, "actors_placed": 0, "spawned": [], "despawned": [],
                "surface_z_error": msg, "sim_time_s": sim_t}

    cur_visible = set(poses)
    _t0 = time.perf_counter()
    spawned, despawned = _spawn_despawn_diff(s["visible"], cur_visible)
    for idx in despawned:
        _pool_actor(s, idx)
    for idx in spawned:
        _activate_index(s, idx)
    s["visible"] = cur_visible
    _profile_add(prof, "spawn", time.perf_counter() - _t0)

    acc = {"transforms": 0.0, "wheels": 0.0, "anim": 0.0}
    for idx, pose in poses.items():
        rec = s["spawned_records"].get(idx)
        if rec is None:
            continue
        _place_visible(s, idx, rec, pose, dt_sim, i0, i1, prof, acc)
    for name in ("transforms", "wheels", "anim"):
        _profile_add(prof, name, acc[name])

    s["visible_now"] = len(cur_visible)
    s["profile_ticks"] += 1
    s["surface_z_error"] = None
    return {
        "visible": len(cur_visible),
        "actors_placed": len(cur_visible),
        "spawned": spawned,
        "despawned": despawned,
        "sim_time_s": sim_t,
        "surface_z_cm": surface_z,
    }


def _mesh_from_index(s: dict, idx: int, rec: dict) -> str:
    """Mesh path the pooled/active rec presents (its own record, ground truth)."""
    return rec["mesh"]
