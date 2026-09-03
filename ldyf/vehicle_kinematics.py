"""Kinematic arithmetic for believable vehicles (Phase 2 gate item 4).

This module owns the *measurement* maths so the in-editor code and the
off-line verifier use ONE definition:

  * wheel rotation rate  ==  speed / wheel_radius  (within 5 % on sampled
    vehicles), and
  * vehicles appear/disappear exactly when the record says (spawn/despawn,
    not parking off-screen).

Laws (frozen)
--------------
1. Units: `speed` from the record is metres/second (SUMO units, unconverted);
   `wheel_radius` is in Unreal centimetres; angular rates are degrees/second.
   The centimetres-per-metre factor is taken from
   `ldyf.coords.METRES_TO_UNREAL_UNITS` -- never typed here.
2. Pure stdlib. Deterministic. All tolerances are arguments.
3. No physics: this is kinematic follow. Nothing in this module alters a pose.

Record access
-------------
The frames.bin layout and manifest schema live in `ldyf.sumo_record`
(frames.bin: `COUNT_STRUCT` frame header then `SAMPLE_STRUCT` samples;
manifest `clock` holds `t_begin`/`step_seconds`, `actors` holds uid/kind).
This module reads through `ldyf.sumo_record`'s structs so the binary layout
is defined once. Times follow the manifest rule
`t(i) = t_begin + i * step_seconds` (frames are written with no gaps, so
frame index is a pure function of time).

Scope: every actor with `kind == "vehicle"` (the Phase 2 gate is about
vehicles; persons are handled elsewhere).
"""

from __future__ import annotations

import math

from .coords import METRES_TO_UNREAL_UNITS, normalise_deg
from .sumo_record import COUNT_STRUCT, SAMPLE_STRUCT, iter_actor_track


def wheel_rate_deg_per_s(speed_mps: float, wheel_radius_cm: float) -> float:
    """Angular wheel rate: 360 * speed_cm_per_s / (2 * pi * r).

    speed_cm_per_s = speed_mps * METRES_TO_UNREAL_UNITS. Zero speed yields 0.
    """
    if wheel_radius_cm <= 0.0:
        raise ValueError(f"wheel_radius_cm must be positive, got {wheel_radius_cm!r}")
    speed_cm_per_s = speed_mps * METRES_TO_UNREAL_UNITS
    return 360.0 * speed_cm_per_s / (2.0 * math.pi * wheel_radius_cm)


def wheel_angle_deg(
    prev_angle_deg: float, speed_mps: float, wheel_radius_cm: float, dt_s: float
) -> float:
    """Accumulate one wheel-angle step, normalised via ldyf.coords.normalise_deg."""
    rate = wheel_rate_deg_per_s(speed_mps, wheel_radius_cm)
    return normalise_deg(prev_angle_deg + rate * dt_s)


def check_wheel_rate(
    measured_deg_per_s: float,
    speed_mps: float,
    wheel_radius_cm: float,
    *,
    rel_tol: float = 0.05,
) -> dict:
    """Compare a measured wheel rate against speed / wheel_radius.

    Returns {"expected", "measured", "rel_error", "pass"}. rel_error is
    |measured - expected| / expected; at expected == 0 it is 0 only for a
    measured 0, else infinite (a moving wheel at zero speed can never pass).
    """
    expected = wheel_rate_deg_per_s(speed_mps, wheel_radius_cm)
    if expected == 0.0:
        rel_error = 0.0 if measured_deg_per_s == 0.0 else float("inf")
    else:
        rel_error = abs(measured_deg_per_s - expected) / abs(expected)
    return {
        "expected": expected,
        "measured": measured_deg_per_s,
        "rel_error": rel_error,
        "pass": rel_error <= rel_tol,
    }


# --- record streaming ------------------------------------------------------


def _iter_frames(frames_path, manifest):
    """Yield (frame_index, {uid: sample}) for every frame, in ascending order.

    A frame with no vehicles yields an empty dict but is still yielded, so
    frame index never drifts from time (mirrors sumo_record.read_frame and the
    "empty frames are still written" guarantee).
    """
    actors = manifest["actors"]
    with open(frames_path, "rb") as f:
        frame = 0
        while True:
            raw = f.read(COUNT_STRUCT.size)
            if len(raw) < COUNT_STRUCT.size:
                return
            (n,) = COUNT_STRUCT.unpack(raw)
            payload = f.read(n * SAMPLE_STRUCT.size)
            by_uid = {}
            for k in range(n):
                idx, x, y, z, yaw, speed = SAMPLE_STRUCT.unpack_from(
                    payload, k * SAMPLE_STRUCT.size
                )
                actor = actors[idx]
                by_uid[actor["uid"]] = {
                    "x": x, "y": y, "z": z, "yaw": yaw, "speed": speed,
                }
            yield frame, by_uid
            frame += 1


def _vehicle_uid(actor: dict) -> bool:
    """Vehicle-kind actors only; the Phase 2 gate is about vehicles."""
    return actor.get("kind") == "vehicle"


def spawn_windows(frames_path, manifest) -> dict:
    """Per-vehicle presence windows over the whole record.

    Returns {uid: {"first_frame", "last_frame", "first_time", "last_time",
                   "present_frames": n, "gaps": [(a, b), ...]}} for every
    vehicle-kind actor that appears at least once.

    first/last_frame are frame indices of the first/last presence; times follow
    the manifest rule t(i) = t_begin + i * step_seconds; gaps are the maximal
    runs of *absent* frames strictly between first and last, each an inclusive
    (first_absent_frame, last_absent_frame) pair.
    """
    clock = manifest["clock"]
    step = clock["step_seconds"]
    t0 = clock["t_begin"]
    present: dict = {}
    for actor in manifest["actors"]:
        if _vehicle_uid(actor):
            present[actor["uid"]] = []

    for _frame, by_uid in _iter_frames(frames_path, manifest):
        for uid in by_uid:
            if uid in present:
                present[uid].append(_frame)

    out: dict = {}
    for uid in present:
        frames = present[uid]
        if not frames:
            continue  # never spawned; no window to report
        first, last = frames[0], frames[-1]
        pset = set(frames)
        gaps = []
        run_start = None
        for fr in range(first + 1, last):
            if fr not in pset:
                if run_start is None:
                    run_start = fr
            elif run_start is not None:
                gaps.append((run_start, fr - 1))
                run_start = None
        if run_start is not None:
            gaps.append((run_start, last - 1))
        out[uid] = {
            "first_frame": first,
            "last_frame": last,
            "first_time": t0 + first * step,
            "last_time": t0 + last * step,
            "present_frames": len(frames),
            "gaps": gaps,
        }
    return out


def visibility_plan(frames_path, manifest, frame_index) -> dict:
    """Who is on screen at frame_index, relative to frame_index - 1.

    Returns {"visible": [...], "spawn": [...], "despawn": [...]} of vehicle
    uids: visible = present in frame_index; spawn = present now, absent one
    frame earlier; despawn = absent now, present one frame earlier. Frame 0 has
    no predecessor, so everything present there counts as a spawn. A frame_index
    past the end of the record raises IndexError.
    """
    if frame_index < 0:
        raise ValueError(f"frame_index must be >= 0, got {frame_index!r}")
    vehicle_uids = {a["uid"] for a in manifest["actors"] if _vehicle_uid(a)}
    prev_uids = set()
    cur_uids = None
    for frame, by_uid in _iter_frames(frames_path, manifest):
        present_now = {u for u in by_uid if u in vehicle_uids}
        if frame == frame_index - 1:
            prev_uids = present_now
        if frame == frame_index:
            cur_uids = present_now
            break
    if cur_uids is None:
        raise IndexError(f"frame {frame_index} beyond end of record")
    return {
        "visible": sorted(cur_uids),
        "spawn": sorted(cur_uids - prev_uids),
        "despawn": sorted(prev_uids - cur_uids),
    }


# --- heading from motion ---------------------------------------------------


def heading_from_motion(p0: dict, p1: dict) -> float | None:
    """Yaw (deg, Unreal convention: 0 = +X, increasing toward +Y) of p0 -> p1.

    Positions are Unreal centimetres. Returns None when the displacement is
    < 1e-6 cm (no direction to measure). Uses math.atan2 on the raw Unreal
    delta, then normalise_deg -- the space is already Unreal, so there is no
    90-degree or sign correction to apply here.
    """
    dx = p1["x"] - p0["x"]
    dy = p1["y"] - p0["y"]
    if math.hypot(dx, dy) < 1e-6:
        return None
    return normalise_deg(math.degrees(math.atan2(dy, dx)))


def yaw_consistency(
    frames_path,
    manifest,
    uid: str,
    *,
    min_speed_mps: float = 1.0,
    max_deg: float = 15.0,
) -> dict:
    """Compare the record's own yaw with the heading implied by motion.

    For consecutive *present* frames of `uid` whose samples both report
    speed >= min_speed_mps, compares the yaw recorded at the later frame with
    heading_from_motion(earlier, later) -- SUMO's angle is the direction of
    travel into the reported position. Returns
    {"n", "max_deg", "mean_deg", "pass"} where max_deg/mean_deg are over the
    shortest absolute angular differences and pass = n > 0 and max <= max_deg.
    """
    diffs: list = []
    prev = None
    for _frame, s in iter_actor_track(frames_path, manifest, uid):
        if prev is None:
            prev = s
            continue
        if prev["speed"] >= min_speed_mps and s["speed"] >= min_speed_mps:
            h = heading_from_motion(prev, s)
            if h is not None:
                diffs.append(abs(normalise_deg(s["yaw"] - h)))
        prev = s
    n = len(diffs)
    max_deg_out = max(diffs) if n else 0.0
    mean_deg = sum(diffs) / n if n else 0.0
    return {
        "n": n,
        "max_deg": max_deg_out,
        "mean_deg": mean_deg,
        "pass": n > 0 and max_deg_out <= max_deg,
    }
