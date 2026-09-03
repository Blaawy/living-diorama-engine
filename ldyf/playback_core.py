"""Pure, unit-testable arithmetic for the in-editor playback lane (Phase 2 L6/L7 + P).

The in-editor player (ldyf/unreal/ldyf_playback.py) keeps its numbers honest:
a pose is either read from the sealed record, measured from a spawned mesh, or
an explicit argument. This module owns the pure arithmetic so it is testable
off-line (ldyf/tests/test_playback_core.py) with no `unreal` import anywhere.

Single authorities -- reused, never re-derived:
  * frame addressing -- ldyf.record_interp.frame_index_bounds (frame_bounds)
  * pose lerp        -- exact replica of record_interp._lerp_pose / _sample_to_pose
                        (those two are private upstream; the replicas are pinned
                        to record_interp.pose_at by unit tests)
  * wheel spin       -- ldyf.vehicle_kinematics.wheel_angle_deg (accumulate_spin)
  * angles           -- ldyf.coords.normalise_deg (lerp yaw, steer_yaw, person_yaw)
  * persons (L7)     -- person_anim_state / person_play_rate / person_yaw: the
                        walk-vs-idle choice, the play-rate scaling and the yaw
                        offset correction are pure functions of the record speed
                        and explicit arguments (never typed numbers).
  * contact law (P)  -- contact_offset_cm = root_z - (origin.z - extent.z), with
                        the actor at a KNOWN root z (contract C1; ground truth
                        EVIDENCE_contact_probe.json); root_z = record_z +
                        surface_z + contact_offset.
  * frame authority  -- presentation_time = frame / fps and
                        sim_time = t_begin + presentation_time * rate (C3).
  * profiling (P)    -- named wall-time buckets; totals + per-tick averages.
  * paint variant    -- deterministic per-uid choice by sha256 digest (never the
                        salted builtin hash()).

Laws
----
1. Pure Python: stdlib + the pure ldyf modules above. No `unreal`, no file I/O
   (the caller has already loaded the record into memory).
2. Deterministic. Mesh choice digests the uid with sha256 -- builtin hash() is
   salted per process, so it cannot be "stable across runs".
3. Nothing here alters a pose; these functions only compute what to draw.
4. Absence semantics mirror record_interp.pose_at: an actor is interpolated
   only between two frames that BOTH contain it; at an exact frame time the
   single deciding frame wins. An actor is therefore drawable exactly while
   t in [t(first_present_frame), t(last_present_frame)]: it spawns at the first
   present frame boundary and despawns at the first absent frame boundary.
5. `surface_z` is NEVER a typed number: the pure placement law takes it as an
   argument; the in-editor player errors until a caller sets it (C1).
"""

from __future__ import annotations

import hashlib

from .coords import normalise_deg
from .record_interp import frame_index_bounds
from .vehicle_kinematics import wheel_angle_deg

MAX_STEER_DEG = 35.0
DUMP_SCHEMA_VERSION = "actor_dump_v1"

# Per-placement wall-time buckets (Phase-2 lane P profiling). Names are frozen
# so status()/evidence and the in-editor player share one vocabulary.
PROFILE_BUCKETS = ("lookup", "transforms", "wheels", "anim", "spawn", "other")


# --- deterministic mesh choice -------------------------------------------


def pick_mesh(mesh_paths: list[str], uid: str) -> str:
    """Stable per-uid choice from a fixed list (sha256, not salted hash())."""
    if not mesh_paths:
        raise ValueError("pick_mesh: empty mesh list")
    digest = hashlib.sha256(uid.encode("utf-8")).digest()
    return mesh_paths[int.from_bytes(digest[:8], "little") % len(mesh_paths)]


# --- frame addressing -----------------------------------------------------


def frame_bounds(manifest: dict, t_seconds: float) -> tuple[int, int, float]:
    """(i0, i1, alpha) -- delegated to record_interp.frame_index_bounds."""
    return frame_index_bounds(manifest, t_seconds)


# --- in-memory pose interpolation (mirrors record_interp) ----------------


def find_sample(rows, actor_index: int):
    """First sample tuple whose actor_index matches, else None."""
    for s in rows:
        if s[0] == actor_index:
            return s
    return None


def sample_to_pose(s: tuple) -> dict:
    """(idx, x, y, z, yaw, speed) -> pose dict, as record_interp._sample_to_pose."""
    return {"x": s[1], "y": s[2], "z": s[3], "yaw": s[4], "speed": s[5]}


def lerp_pose(s0: tuple, s1: tuple, alpha: float) -> dict:
    """Exact replica of record_interp._lerp_pose (private upstream)."""
    d = normalise_deg(s1[4] - s0[4])
    return {
        "x": s0[1] + alpha * (s1[1] - s0[1]),
        "y": s0[2] + alpha * (s1[2] - s0[2]),
        "z": s0[3] + alpha * (s1[3] - s0[3]),
        "yaw": normalise_deg(s0[4] + alpha * d),
        "speed": s0[5] + alpha * (s1[5] - s0[5]),
    }


def interpolated_poses(frames_by_index: dict, manifest: dict, t_seconds: float) -> dict:
    """actor_index -> pose for every actor drawable at t (pose_at semantics).

    frames_by_index maps frame index -> list of sample tuples already in memory.
    i0 == i1: the single deciding frame wins. i0 < i1: the actor must be in BOTH
    bounding frames (never extrapolated across an absence).
    """
    clock = manifest["clock"]
    if clock["frame_count"] == 0:
        return {}
    i0, i1, alpha = frame_index_bounds(manifest, t_seconds)
    out: dict[int, dict] = {}
    if i1 == i0:
        for s in frames_by_index.get(i0, ()):
            out[s[0]] = sample_to_pose(s)
        return out
    f0 = {s[0]: s for s in frames_by_index.get(i0, ())}
    f1 = {s[0]: s for s in frames_by_index.get(i1, ())}
    for idx in sorted(f0.keys() & f1.keys()):
        out[idx] = lerp_pose(f0[idx], f1[idx], alpha)
    return out


# --- wheels ---------------------------------------------------------------


def accumulate_spin(prev_angle_deg: float, speed_mps: float,
                    wheel_radius_cm: float | None, dt_s: float) -> tuple:
    """(angle, spun). radius None/<=0 -> (None, False); else wheel_angle_deg."""
    if wheel_radius_cm is None or wheel_radius_cm <= 0.0:
        return (None, False)
    return (wheel_angle_deg(prev_angle_deg, speed_mps, wheel_radius_cm, dt_s), True)


def steer_yaw(prev_yaw_deg: float, current_yaw_deg: float,
              max_deg: float = MAX_STEER_DEG) -> float:
    """Signed heading change (shortest arc) clamped to +-max_deg.

    The value applied to the front turn bones is this clamped, record-derived
    heading change. The sign/axis convention of the turn bones against the
    vehicle is NOT verified in-editor yet (editor probe #1).
    """
    d = normalise_deg(current_yaw_deg - prev_yaw_deg)
    return max(-max_deg, min(max_deg, d))


# --- persons: walk/idle animation state (Phase-2 L7) ----------------------


def person_anim_state(speed: float, walk_ref: float | None = None,
                      idle_below: float | None = None,
                      prev_state: str = "idle") -> str:
    """Walk/idle choice for an animated person: "walk" or "idle".

    Hysteresis-free: the choice is a pure function of the current record speed
    and the explicit arguments -- ``prev_state`` never influences the result,
    it exists so the in-editor caller can switch the looped sequence only when
    the state actually changes (no restart every tick).

    Until ``idle_below`` is set (None) a person walks at any speed > 0 and
    idles at speed == 0. Once ``idle_below`` is set, speeds strictly below it
    idle even while the record keeps moving the body (presentation only).
    """
    if idle_below is not None and speed < idle_below:
        return "idle"
    if speed > 0.0:
        return "walk"
    return "idle"


def person_play_rate(speed: float, walk_ref: float | None = None) -> float:
    """Play rate for the walk cycle: speed / walk_ref.

    ``walk_ref`` is the speed (m/s) at which the walk cycle plays at rate 1.0.
    Until a caller sets it -- or while it is non-positive / the person stands
    still -- the rate is 1.0 (the animation asset default; no numbers invented).
    """
    if walk_ref is None or walk_ref <= 0.0 or speed <= 0.0:
        return 1.0
    return speed / walk_ref


def person_yaw(record_yaw_deg: float, offset_deg: float = 0.0) -> float:
    """Yaw an animated person should face: normalise_deg(record_yaw + offset).

    The Tutorial mannequin's facing convention (+X or not) is NOT verified
    in-editor, so the correction is an explicit argument (default 0.0) and the
    sum is normalised exactly like every other angle in the pipeline.
    """
    return normalise_deg(record_yaw_deg + offset_deg)


# --- lifetimes ------------------------------------------------------------


def spawn_despawn_diff(prev_visible, curr_visible) -> tuple[list, list]:
    """(spawned, despawned) sorted actor indices between two visible sets."""
    prev_visible = set(prev_visible)
    curr_visible = set(curr_visible)
    return (sorted(curr_visible - prev_visible), sorted(prev_visible - curr_visible))


# --- contact law, C1 (Phase-2 lane P) -------------------------------------
# Ground truth for the formula and API names: EVIDENCE_contact_probe.json --
# in the live editor a vehicle at KNOWN root 0 gave bounds_bottom 23.3399 and
# root 5000 gave 5023.3399 (contact_offset identical: -23.3399), a person at
# root 300 gave bounds_bottom 277.275 (contact_offset +22.725). The offset is
# invariant under vertical translation, so it may be cached per mesh path.


def bounds_bottom_z(origin_z: float, extent_z: float) -> float:
    """C1: bottom = origin.z - extent.z for the world bounds of a component."""
    return origin_z - extent_z


def contact_offset_cm(root_z: float, origin_z: float, extent_z: float) -> float:
    """C1: contact_offset = root_z - bottom, measured at a KNOWN root z."""
    return root_z - bounds_bottom_z(origin_z, extent_z)


def placed_root_z(record_z: float, surface_z: float, offset_cm: float) -> float:
    """C1 placement: root_z = record_z + surface_z + contact_offset."""
    return record_z + surface_z + offset_cm


def contact_error_cm(bottom_z: float, record_z: float, surface_z: float) -> float:
    """C1 verification: |world_bounds_bottom_z - (record_z + surface_z)|."""
    return abs(bottom_z - (record_z + surface_z))


# --- frame player authority, C3 (Phase-2 lane P) --------------------------


def frame_presentation_time(frame: int, fps: float) -> float:
    """C3: presentation_time(frame, fps) = frame / fps. No wall clock involved."""
    if fps is None or fps <= 0.0:
        raise ValueError(f"frame_presentation_time: fps must be > 0, got {fps!r}")
    if not isinstance(frame, int) or frame < 0:
        raise ValueError(f"frame_presentation_time: frame must be an int >= 0, got {frame!r}")
    return frame / float(fps)


def frame_to_sim_time(frame: int, fps: float, rate: float = 1.0,
                      t_start_s: float = 0.0) -> float:
    """C3: sim_time = t_start_s + presentation_time(frame, fps) * rate.

    t_start_s is the record sim time at presentation frame 0 (default 0.0);
    the in-editor player passes the record clock's t_begin when the driver did
    not give an explicit t_start_s.
    """
    if rate is None or rate <= 0.0:
        raise ValueError(f"frame_to_sim_time: rate must be > 0, got {rate!r}")
    return float(t_start_s) + frame_presentation_time(frame, fps) * float(rate)


# --- profiling buckets (Phase-2 lane P) -----------------------------------


def new_profile_buckets() -> dict:
    """Fresh zeroed wall-time buckets: lookup/transforms/wheels/anim/spawn/other."""
    return {name: 0.0 for name in PROFILE_BUCKETS}


def profile_add(buckets: dict, name: str, seconds: float) -> None:
    """Accumulate `seconds` into one named bucket; unknown names are a bug."""
    if name not in PROFILE_BUCKETS:
        raise ValueError(
            f"profile_add: unknown bucket {name!r}; expected one of {PROFILE_BUCKETS}"
        )
    buckets[name] += seconds


def profile_summary(buckets: dict, ticks: int) -> dict:
    """Totals and per-tick averages for the named buckets.

    per-tick averages are totals / ticks; with no recorded ticks they are 0.0
    (an honest "nothing measured yet", not a fabricated number).
    """
    totals = {name: buckets.get(name, 0.0) for name in PROFILE_BUCKETS}
    total_s = sum(totals.values())
    return {
        "ticks": ticks,
        "total_s": total_s,
        "totals_s": totals,
        "per_tick_avg_s": {
            name: (totals[name] / ticks if ticks > 0 else 0.0) for name in PROFILE_BUCKETS
        },
    }


# --- deterministic paint variant (Phase-2 lane P) -------------------------


def pick_variant_index(uid: str, n_variants: int) -> int:
    """Stable per-uid paint variant in [0, n_variants) from the uid digest.

    Same sha256 convention as pick_mesh; builtin hash() is salted per process
    and must never feed a visual choice.
    """
    if not isinstance(n_variants, int) or n_variants < 1:
        raise ValueError(f"pick_variant_index: n_variants must be an int >= 1, got {n_variants!r}")
    digest = hashlib.sha256(uid.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little") % n_variants


# --- placed-actor snapshot, C2 shape (Phase-2 lane P) ---------------------


def build_placed_snapshot(rows: list, surface_z_cm: float) -> dict:
    """Assemble a sorted snapshot_placed_v1 document for the 3D verifier.

    rows: one dict per visible actor with the keys the verifier compares --
    label, uid, x, y, root_z, bottom_z, yaw (bottom measured in-editor from
    get_component_bounds at snapshot time). Sorted by label so repeated
    snapshots are byte-identical for the same level state.
    """
    actors = sorted((dict(r) for r in rows), key=lambda r: (r.get("label") or ""))
    return {
        "schema_version": "snapshot_placed_v1",
        "surface_z_cm": surface_z_cm,
        "count": len(actors),
        "actors": actors,
    }


# --- actor dump (actor_dump_v1) ------------------------------------------


def make_actor_dump(actors: list[dict], level=None, captured_utc: str = "") -> dict:
    """Assemble an actor_dump_v1 document (schema: ldyf.world_inventory docstring).

    world_inventory reads actors' class/components (class, name, asset,
    skeleton, anim_class) and level; extra per-component keys such as
    wheel_bones/steer_bones/animation are tolerated and keep the dump truthful.
    Actors are sorted by name so repeated writes are byte-identical.
    """
    ordered = sorted(actors, key=lambda a: (a.get("name") or ""))
    return {
        "schema_version": DUMP_SCHEMA_VERSION,
        "level": level,
        "captured_utc": captured_utc,
        "actors": ordered,
    }
