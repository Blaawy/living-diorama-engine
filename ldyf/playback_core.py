"""Pure, unit-testable arithmetic for the in-editor playback lane (Phase 2 L6/L7).

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
"""

from __future__ import annotations

import hashlib

from .coords import normalise_deg
from .record_interp import frame_index_bounds
from .vehicle_kinematics import wheel_angle_deg

MAX_STEER_DEG = 35.0
DUMP_SCHEMA_VERSION = "actor_dump_v1"


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
