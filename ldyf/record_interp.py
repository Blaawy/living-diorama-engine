"""Interpolated truth between record frames (Phase 2 lane L2).

A record holds one sample per 0.1 s, but the editor ticks faster and plays
interpolated poses. This module answers "what pose *should* an actor have at
arbitrary editor time t?" purely from the sealed record, so the verifier
(`playback_verify`) can compare expected vs measured poses.

Laws (frozen, from the Phase 2 gate):
1. Time is `t(i) = t_begin + i * step_seconds` from the manifest clock block.
   Never assume 0.1.
2. Yaw interpolates along the shortest arc and the result goes through
   `ldyf.coords.normalise_deg`. No other angle code lives here: the signed
   shortest difference is `normalise_deg(y1 - y0)` and the absolute yaw error
   is `abs(normalise_deg(measured - expected))`.
3. An actor absent from a frame has no pose there (spawn/despawn); it is never
   extrapolated from a neighbour. Interpolating across an absence returns None.
4. Pure stdlib, deterministic, no invented tolerances (tolerances are
   arguments).
"""

from __future__ import annotations

import math
from pathlib import Path

from .coords import normalise_deg
from .sumo_record import COUNT_STRUCT, SAMPLE_STRUCT


# --- frame addressing ------------------------------------------------------


def frame_time(manifest: dict, frame_index: int) -> float:
    """Simulation time of one frame: t(i) = t_begin + i * step_seconds."""
    clock = manifest["clock"]
    return clock["t_begin"] + frame_index * clock["step_seconds"]


def frame_index_bounds(manifest: dict, t_seconds: float) -> tuple[int, int, float]:
    """(i0, i1, alpha) bracketing an arbitrary time, clamped at record ends.

    When t falls between two consecutive frames the result is (i, i+1, alpha)
    with 0 < alpha < 1. At an exact frame time, and beyond either record end
    (clamping), i0 == i1 and alpha == 0.0, so the pose is the exact recorded
    sample of that single frame -- an actor present in exactly that frame is
    never penalised for being absent from a neighbour.
    """
    clock = manifest["clock"]
    n = clock["frame_count"]
    if n <= 1:
        return (0, 0, 0.0)
    f = (t_seconds - clock["t_begin"]) / clock["step_seconds"]
    # Snap float noise at exact frame boundaries so an exact frame time (or an
    # editor time computed from frame_time()) lands on (i, i, 0.0).
    r = round(f)
    if abs(f - r) < 1e-9:
        f = float(r)
    if f <= 0.0:
        return (0, 0, 0.0)
    if f >= n - 1:
        return (n - 1, n - 1, 0.0)
    i = int(f)  # f in (0, n-1): truncation == floor
    if i == f:
        return (i, i, 0.0)
    return (i, i + 1, f - i)


# --- reading ---------------------------------------------------------------


def read_frames(frames_path: str | Path, indices: tuple[int, ...]) -> dict[int, list[tuple]]:
    """Read the requested frames in ONE sequential pass.

    Returns {frame_index: [sample, ...]} where each sample is the raw tuple
    (actor_index, x, y, z, yaw, speed). Raises IndexError if the file ends
    before the last requested frame (same contract as sumo_record.read_frame).
    """
    want = sorted(set(indices))
    if not want:
        return {}
    out: dict[int, list[tuple]] = {}
    frame = 0
    with Path(frames_path).open("rb") as f:
        while True:
            raw = f.read(COUNT_STRUCT.size)
            if len(raw) < COUNT_STRUCT.size:
                raise IndexError(f"frame {frame} beyond end of record")
            (n,) = COUNT_STRUCT.unpack(raw)
            payload = f.read(n * SAMPLE_STRUCT.size)
            if frame in want:
                out[frame] = [
                    SAMPLE_STRUCT.unpack_from(payload, k * SAMPLE_STRUCT.size)
                    for k in range(n)
                ]
            frame += 1
            if frame > want[-1]:
                return out


def _actor_index(manifest: dict, actor_uid: str) -> int:
    """Actor-table index for a uid ("vehicle:12"); a bare id is accepted when
    the uid itself does not match, mirroring sumo_record.iter_actor_track."""
    for i, a in enumerate(manifest["actors"]):
        if a["uid"] == actor_uid or a["id"] == actor_uid:
            return i
    raise KeyError(f"actor {actor_uid!r} not in record")


def _find_sample(samples: list[tuple], idx: int) -> tuple | None:
    for s in samples:
        if s[0] == idx:
            return s
    return None


# --- pose interpolation ----------------------------------------------------


def _sample_to_pose(s: tuple) -> dict:
    return {"x": s[1], "y": s[2], "z": s[3], "yaw": s[4], "speed": s[5]}


def _lerp_pose(s0: tuple, s1: tuple, alpha: float) -> dict:
    # Position and speed: linear. Yaw: shortest arc, result normalised.
    d = normalise_deg(s1[4] - s0[4])
    return {
        "x": s0[1] + alpha * (s1[1] - s0[1]),
        "y": s0[2] + alpha * (s1[2] - s0[2]),
        "z": s0[3] + alpha * (s1[3] - s0[3]),
        "yaw": normalise_deg(s0[4] + alpha * d),
        "speed": s0[5] + alpha * (s1[5] - s0[5]),
    }


def pose_at(
    frames_path: str | Path, manifest: dict, actor_uid: str, t_seconds: float
) -> dict | None:
    """Interpolated pose {"x","y","z","yaw","speed"} at arbitrary time.

    None if the actor is absent from i0 or i1 (never extrapolated across an
    absence, law 3). At exact frame times and clamped ends i0 == i1 and only
    that single frame decides.
    """
    clock = manifest["clock"]
    if clock["frame_count"] == 0:
        return None
    i0, i1, alpha = frame_index_bounds(manifest, t_seconds)
    idx = _actor_index(manifest, actor_uid)
    frames = read_frames(frames_path, (i0, i1))
    s0 = _find_sample(frames.get(i0, ()), idx)
    if s0 is None:
        return None
    if i1 == i0:
        return _sample_to_pose(s0)
    s1 = _find_sample(frames.get(i1, ()), idx)
    if s1 is None:
        return None
    return _lerp_pose(s0, s1, alpha)


def poses_at(
    frames_path: str | Path, manifest: dict, t_seconds: float
) -> dict[str, dict]:
    """uid -> interpolated pose for every actor present in BOTH bounding frames.

    When i0 == i1 (exact frame time or clamped end) "both" means that single
    frame, so actors present exactly there are included.
    """
    clock = manifest["clock"]
    if clock["frame_count"] == 0:
        return {}
    i0, i1, alpha = frame_index_bounds(manifest, t_seconds)
    frames = read_frames(frames_path, (i0, i1))
    actors = manifest["actors"]
    if i1 == i0:
        present = {s[0]: s for s in frames.get(i0, ())}
        return {
            actors[idx]["uid"]: _sample_to_pose(s) for idx, s in present.items()
        }
    f0 = {s[0]: s for s in frames.get(i0, ())}
    f1 = {s[0]: s for s in frames.get(i1, ())}
    out: dict[str, dict] = {}
    for idx in sorted(f0.keys() & f1.keys()):
        out[actors[idx]["uid"]] = _lerp_pose(f0[idx], f1[idx], alpha)
    return out


# --- lifetimes -------------------------------------------------------------


def lifetimes(frames_path: str | Path, manifest: dict) -> dict[str, dict]:
    """uid -> {"first_frame","last_frame","first_time","last_time","gaps"}.

    gaps lists every maximal run of consecutive frames in which the actor is
    absent but which lies strictly INSIDE [first_frame, last_frame], as
    inclusive (first_absent, last_absent) index pairs. Absence before spawn or
    after despawn is the lifetime bound, not a gap.
    """
    n_actors = len(manifest["actors"])
    present: list[set[int]] = [set() for _ in range(n_actors)]
    frame = 0
    with Path(frames_path).open("rb") as f:
        while True:
            raw = f.read(COUNT_STRUCT.size)
            if len(raw) < COUNT_STRUCT.size:
                break
            (n,) = COUNT_STRUCT.unpack(raw)
            payload = f.read(n * SAMPLE_STRUCT.size)
            for k in range(n):
                idx = SAMPLE_STRUCT.unpack_from(payload, k * SAMPLE_STRUCT.size)[0]
                present[idx].add(frame)
            frame += 1

    out: dict[str, dict] = {}
    for i, a in enumerate(manifest["actors"]):
        uid = a["uid"]
        pres = sorted(present[i])
        if not pres:
            out[uid] = {
                "first_frame": None, "last_frame": None,
                "first_time": None, "last_time": None, "gaps": [],
            }
            continue
        gaps: list[tuple[int, int]] = []
        for p, q in zip(pres, pres[1:]):
            if q > p + 1:
                gaps.append((p + 1, q - 1))
        out[uid] = {
            "first_frame": pres[0],
            "last_frame": pres[-1],
            "first_time": frame_time(manifest, pres[0]),
            "last_time": frame_time(manifest, pres[-1]),
            "gaps": gaps,
        }
    return out


# --- verification ----------------------------------------------------------


def compare_poses(
    expected: dict,
    measured: dict,
    *,
    pos_tol_cm: float,
    yaw_tol_deg: float,
) -> dict:
    """Per-uid comparison of expected vs measured poses.

    Position error: 3D euclidean distance in centimetres. Yaw error: shortest
    arc magnitude in degrees, computed as abs(normalise_deg(measured - expected))
    so it routes through the single angle authority (law 2).

    Returns {"n", "max_pos_cm", "max_yaw_deg", "failures", "pass"}; only uids
    present in BOTH dicts are compared, failures are sorted for determinism,
    and pass is False unless n > 0 and no uid fails either tolerance.
    """
    max_pos = 0.0
    max_yaw = 0.0
    failures: list[str] = []
    compared = 0
    for uid in expected:
        if uid not in measured:
            continue
        e = expected[uid]
        m = measured[uid]
        dx = m["x"] - e["x"]
        dy = m["y"] - e["y"]
        dz = m["z"] - e["z"]
        pos = math.sqrt(dx * dx + dy * dy + dz * dz)
        yaw_err = abs(normalise_deg(m["yaw"] - e["yaw"]))
        compared += 1
        max_pos = max(max_pos, pos)
        max_yaw = max(max_yaw, yaw_err)
        if pos > pos_tol_cm or yaw_err > yaw_tol_deg:
            failures.append(uid)
    failures.sort()
    return {
        "n": compared,
        "max_pos_cm": max_pos,
        "max_yaw_deg": max_yaw,
        "failures": failures,
        "pass": compared > 0 and not failures,
    }
