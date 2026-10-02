"""Loop detection on a sealed Simulation Record V1 -- measured, not asserted.

Three questions the Director's "living world" law needs answered from the record
itself (`record_manifest.json` + `frames.bin`, see `ldyf.sumo_record`), never
from prose:

`detect_state_cycles`
    Does any actor RETURN to a state it had left, again and again, inside one
    time window? An actor that never leaves a cell is parked, not cycling; an
    actor whose cells never repeat is progressing. Both are reported as "no
    cycle".

`position_divergence`
    How far apart are two records, actor by actor and frame by frame? Exactly
    0.0 only when every compared position is identical.

`actor_progress`
    Per actor: path length, net displacement, efficiency (displacement /
    distance), stall time and progress rate. This is the measurement that says
    a record PROGRESSES rather than shuffles in place.

Positions in `frames.bin` are Unreal centimetres (see `ldyf.sumo_record`), so a
cell index is `floor(axis / cell_cm)` and every distance here is in centimetres.

Laws honoured: pure stdlib; deterministic; every parameter is an argument with a
default and is echoed into the output; nothing is read from `frames.bin` except
by one sequential pass; every structural defect (empty record, truncated frame,
actor index outside the manifest's actor table) is refused rather than
mis-counted.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .sumo_record import COUNT_STRUCT, SAMPLE_STRUCT

STATE_CYCLES_VERSION = "state_cycles_v1"
ACTOR_PROGRESS_VERSION = "actor_progress_v1"
DEFAULT_CELL_CM = 100.0
DEFAULT_STALL_CM = 1.0


class LoopDetectError(RuntimeError):
    """Raised when a record cannot be read, or a measurement is undefined."""


# --- record handling ------------------------------------------------------


def load_record(record) -> tuple[dict, Path]:
    """Resolve a record handle to `(manifest, frames_path)`.

    A handle is either a record DIRECTORY (holding `record_manifest.json` and
    `frames.bin`) or a `(manifest_dict, frames_path)` pair. Nothing else is
    guessed at: a bare manifest alone cannot say where its frames live.
    """
    if isinstance(record, (str, Path)):
        directory = Path(record)
        if not directory.is_dir():
            raise LoopDetectError(
                f"record {directory} is not a directory; pass the record directory "
                "(record_manifest.json + frames.bin) or a (manifest, frames_path) pair"
            )
        manifest_path = directory / "record_manifest.json"
        frames_path = directory / "frames.bin"
        if not manifest_path.is_file():
            raise LoopDetectError(f"record {directory} has no record_manifest.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise LoopDetectError(f"{manifest_path} is not parseable JSON: {e}") from e
        if not isinstance(manifest, dict):
            raise LoopDetectError(f"{manifest_path} is not a JSON object")
        if not frames_path.is_file():
            raise LoopDetectError(f"record {directory} has no frames.bin")
        return manifest, frames_path
    if isinstance(record, (tuple, list)) and len(record) == 2:
        manifest, frames_path = record
        if not isinstance(manifest, dict):
            raise LoopDetectError("the first element of a record handle must be the manifest object")
        frames_path = Path(frames_path)
        if not frames_path.is_file():
            raise LoopDetectError(f"record frames {frames_path} does not exist")
        return manifest, frames_path
    raise LoopDetectError(
        "a record handle is a record directory or a (manifest, frames_path) pair, got "
        f"{type(record).__name__}"
    )


def _actors(manifest: dict) -> list:
    actors = manifest.get("actors")
    if not isinstance(actors, list) or not actors:
        raise LoopDetectError("the record manifest names no actors")
    return actors


def _uid_of(actors: list, index: int) -> str:
    a = actors[index]
    if not isinstance(a, dict):
        raise LoopDetectError(f"record actor {index} is not an object")
    uid = a.get("uid")
    if isinstance(uid, str) and uid:
        return uid
    aid = a.get("id")
    if isinstance(aid, str) and aid:
        return aid
    raise LoopDetectError(f"record actor {index} has neither a uid nor an id")


def _kind_of(actors: list, index: int) -> str:
    a = actors[index]
    kind = a.get("kind") if isinstance(a, dict) else None
    return kind if isinstance(kind, str) and kind else "unknown"


def _clock(manifest: dict) -> tuple[float, float]:
    clock = manifest.get("clock") or {}
    step = clock.get("step_seconds")
    t_begin = clock.get("t_begin", 0.0)
    if not isinstance(step, (int, float)) or isinstance(step, bool) or step <= 0:
        raise LoopDetectError(f"the record manifest clock.step_seconds is not a positive number: {step!r}")
    if not isinstance(t_begin, (int, float)) or isinstance(t_begin, bool):
        raise LoopDetectError(f"the record manifest clock.t_begin is not a number: {t_begin!r}")
    return float(step), float(t_begin)


def _require_frames(frames_path: Path) -> None:
    if Path(frames_path).stat().st_size == 0:
        raise LoopDetectError(
            f"{Path(frames_path).name} is an empty record (0 bytes); an empty record carries no "
            "positions and is not evidence of anything"
        )


def _frames(manifest: dict, frames_path: Path):
    """Yield `(frame_index, {uid: (x, y, z, yaw, speed)})`, one frame at a time."""
    actors = _actors(manifest)
    with Path(frames_path).open("rb") as f:
        frame = 0
        while True:
            raw = f.read(COUNT_STRUCT.size)
            if not raw:
                return
            if len(raw) < COUNT_STRUCT.size:
                raise LoopDetectError(
                    f"{Path(frames_path).name} ends with a partial frame header (truncated record)"
                )
            (n,) = COUNT_STRUCT.unpack(raw)
            payload = f.read(n * SAMPLE_STRUCT.size)
            if len(payload) < n * SAMPLE_STRUCT.size:
                raise LoopDetectError(
                    f"{Path(frames_path).name} ends with a partial frame body (frame {frame} "
                    f"declares {n} samples, {len(payload)} bytes present): truncated record"
                )
            row = {}
            for k in range(n):
                idx, x, y, z, yaw, speed = SAMPLE_STRUCT.unpack_from(payload, k * SAMPLE_STRUCT.size)
                if idx >= len(actors):
                    raise LoopDetectError(
                        f"{Path(frames_path).name} frame {frame} names actor index {idx}, which the "
                        f"actor table ({len(actors)} actors) does not have"
                    )
                row[_uid_of(actors, idx)] = (x, y, z, yaw, speed)
            yield frame, row
            frame += 1


# --- 1. state cycles ------------------------------------------------------


def detect_state_cycles(record, window_s, min_repeats, *, cell_cm: float = DEFAULT_CELL_CM) -> dict:
    """Fire when an actor RETURNS to a state it had left, repeatedly, in one window.

    The state of an actor in a frame is its quantised cell
    `(floor(x / cell_cm), floor(y / cell_cm))` -- position only; heading is not
    part of the state. Consecutive frames in the same cell are one *visit*. An
    actor cycles on a cell when that cell has at least `min_repeats` visits and
    the whole run of them fits inside `window_s` seconds, measured from the first
    arrival to the last departure.

    So a single visit is never a cycle, a parked actor is never a cycle (it
    never left), and a record whose actors only ever move on to new cells does
    not fire. `fires` is the verdict; `cycles` is the evidence for it.

    Boundary, stated rather than hidden: a state is a cell, so an actor jittering
    across one cell boundary (A,B,A,B) IS a cycle by this definition, while an
    actor circling inside a single cell without crossing a boundary is not. Sub-
    cell motion needs a smaller `cell_cm`.
    """
    if not isinstance(window_s, (int, float)) or isinstance(window_s, bool) or not math.isfinite(window_s) or window_s <= 0:
        raise ValueError("window_s must be a positive, finite number of seconds")
    if not isinstance(min_repeats, int) or isinstance(min_repeats, bool) or min_repeats < 2:
        raise ValueError("min_repeats must be an integer >= 2: a cycle needs the state to be left and returned to")
    if not isinstance(cell_cm, (int, float)) or isinstance(cell_cm, bool) or not math.isfinite(cell_cm) or cell_cm <= 0:
        raise ValueError("cell_cm must be a positive, finite number of centimetres")

    manifest, frames_path = load_record(record)
    _require_frames(frames_path)
    step, t_begin = _clock(manifest)

    visits: dict[str, list] = {}
    n_frames = 0
    for frame, row in _frames(manifest, frames_path):
        n_frames += 1
        t = t_begin + frame * step
        for uid, (x, y, _z, _yaw, _speed) in row.items():
            cell = (int(math.floor(x / cell_cm)), int(math.floor(y / cell_cm)))
            seen = visits.get(uid)
            if seen is None:
                visits[uid] = [(cell, t, t)]
            elif seen[-1][0] == cell:
                seen[-1] = (cell, seen[-1][1], t)
            else:
                seen.append((cell, t, t))
    if n_frames == 0:
        raise LoopDetectError(f"{frames_path.name} holds no frames")

    cycles: list[dict] = []
    for uid in sorted(visits):
        seen = visits[uid]
        by_cell: dict[tuple[int, int], list[int]] = {}
        for i, (cell, _t0, _t1) in enumerate(seen):
            by_cell.setdefault(cell, []).append(i)
        for cell in sorted(by_cell):
            idxs = by_cell[cell]
            n = len(idxs)
            for a in range(n):
                first = seen[idxs[a]][1]
                b = a
                while b + 1 < n and (seen[idxs[b + 1]][2] - first) <= window_s:
                    b += 1
                count = b - a + 1
                if count < min_repeats:
                    continue
                i, j = idxs[a], idxs[b]
                if not any(seen[m][0] != cell for m in range(i, j + 1)):
                    continue                      # never left the cell: parked, not a cycle
                cycles.append(
                    {
                        "uid": uid,
                        "cell": [cell[0], cell[1]],
                        "occurrences": count,
                        "first_t": round(seen[i][1], 6),
                        "last_t": round(seen[j][2], 6),
                        "span_s": round(seen[j][2] - seen[i][1], 6),
                    }
                )
                break
    return {
        "schema_version": STATE_CYCLES_VERSION,
        "record": {
            "frames": n_frames,
            "step_seconds": step,
            "frames_bin_sha256": (manifest.get("binary") or {}).get("sha256"),
            "actors": len(_actors(manifest)),
        },
        "params": {"window_s": float(window_s), "min_repeats": int(min_repeats), "cell_cm": float(cell_cm)},
        "cycles": cycles,
        "actors_in_cycle": sorted({c["uid"] for c in cycles}),
        "cycle_count": len(cycles),
        "fires": bool(cycles),
        "boundary": [
            "A state is a quantised cell; an actor circling inside one cell without crossing a "
            "boundary is invisible until cell_cm is reduced.",
            "A return whose occurrences do not all fit inside window_s is not reported.",
        ],
    }


# --- 2. position divergence ----------------------------------------------


def position_divergence(record_a, record_b) -> float:
    """Maximum XY distance (cm) between two records, over actors they share.

    Frame by frame, only the frames both records have (the common prefix when
    their lengths differ), and within a frame only the actors present in BOTH --
    matched by uid, never by actor index, because the two records need not share
    an actor table. The result is the MAXIMUM such distance, so it is exactly
    0.0 if and only if every compared position is identical; comparing a record
    with itself is therefore exactly 0.0, by construction.

    Boundary, stated rather than hidden: an actor present in only one record at
    a frame contributes no comparison, because there is no counterpart position
    to measure. Presence divergence is a different question (`actor_progress`
    reports presence per record). If the records share no frame, or no actor in
    those frames, the divergence is undefined and `LoopDetectError` is raised
    rather than 0.0 reported. Z is not compared here: this is XY only.
    """
    manifest_a, frames_a = load_record(record_a)
    manifest_b, frames_b = load_record(record_b)
    _require_frames(frames_a)
    _require_frames(frames_b)

    worst = 0.0
    compared = 0
    frames_compared = 0
    for (_ia, row_a), (_ib, row_b) in zip(_frames(manifest_a, frames_a), _frames(manifest_b, frames_b)):
        frames_compared += 1
        for uid in row_a.keys() & row_b.keys():
            dx = row_a[uid][0] - row_b[uid][0]
            dy = row_a[uid][1] - row_b[uid][1]
            d = math.hypot(dx, dy)
            if d > worst:
                worst = d
            compared += 1
    if frames_compared == 0 or compared == 0:
        raise LoopDetectError(
            "the two records share no actor at any common frame; positional divergence is "
            "undefined and is refusing to report 0.0"
        )
    return worst


# --- 3. actor progress ---------------------------------------------------


def actor_progress(record, *, stall_cm: float = DEFAULT_STALL_CM) -> dict:
    """Per actor: path length, net displacement, efficiency, stall, progress rate.

    Path length is the sum of the frame-to-frame XY distances; net displacement
    is the straight line from the actor's first to its last recorded position.
    Efficiency is the ratio, so a shuttle that returns where it started has
    efficiency 0.0 however far it drove, while a straight run has 1.0. A step
    shorter than `stall_cm` counts as stalled time.
    """
    if not isinstance(stall_cm, (int, float)) or isinstance(stall_cm, bool) or not math.isfinite(stall_cm) or stall_cm < 0:
        raise ValueError("stall_cm must be a non-negative, finite number of centimetres")

    manifest, frames_path = load_record(record)
    _require_frames(frames_path)
    actors = _actors(manifest)
    step, t_begin = _clock(manifest)

    state: dict[str, dict] = {}
    n_frames = 0
    for frame, row in _frames(manifest, frames_path):
        n_frames += 1
        t = t_begin + frame * step
        for uid, (x, y, _z, _yaw, _speed) in row.items():
            st = state.get(uid)
            if st is None:
                state[uid] = {
                    "kind": _kind_of(actors, _index_of(actors, uid)),
                    "samples": 1,
                    "first_t": t,
                    "last_t": t,
                    "x0": x,
                    "y0": y,
                    "x1": x,
                    "y1": y,
                    "distance_cm": 0.0,
                    "stalled_s": 0.0,
                    "prev": (x, y),
                }
                continue
            prev_x, prev_y = st["prev"]
            movement = math.hypot(x - prev_x, y - prev_y)
            st["distance_cm"] += movement
            dt = t - st["last_t"]
            if dt > 0 and movement < stall_cm:
                st["stalled_s"] += dt
            st["prev"] = (x, y)
            st["x1"] = x
            st["y1"] = y
            st["samples"] += 1
            st["last_t"] = t
    if n_frames == 0:
        raise LoopDetectError(f"{frames_path.name} holds no frames")

    rows: list[dict] = []
    for uid in sorted(state):
        st = state[uid]
        distance = round(st["distance_cm"], 6)
        displacement = round(math.hypot(st["x1"] - st["x0"], st["y1"] - st["y0"]), 6)
        duration = round(st["last_t"] - st["first_t"], 6)
        stalls = round(st["stalled_s"], 6)
        rows.append(
            {
                "uid": uid,
                "kind": st["kind"],
                "samples": st["samples"],
                "first_t": round(st["first_t"], 6),
                "last_t": round(st["last_t"], 6),
                "duration_s": duration,
                "distance_cm": distance,
                "displacement_cm": displacement,
                "efficiency": round(displacement / distance, 6) if distance > 0 else 0.0,
                "progress_rate_cm_s": round(displacement / duration, 6) if duration > 0 else 0.0,
                "stalled_s": stalls,
                "stalled_fraction": round(stalls / duration, 6) if duration > 0 else 0.0,
                "zero_progress": displacement == 0.0,
            }
        )

    by_kind: dict[str, dict] = {}
    for row in rows:
        bucket = by_kind.setdefault(
            row["kind"], {"actors": 0, "distance_cm": 0.0, "displacement_cm": 0.0, "efficiency": 0.0,
                          "stalled_fraction": 0.0, "zero_progress_actors": 0}
        )
        bucket["actors"] += 1
        bucket["distance_cm"] += row["distance_cm"]
        bucket["displacement_cm"] += row["displacement_cm"]
        bucket["efficiency"] += row["efficiency"]
        bucket["stalled_fraction"] += row["stalled_fraction"]
        bucket["zero_progress_actors"] += 1 if row["zero_progress"] else 0
    for bucket in by_kind.values():
        n = bucket["actors"]
        bucket["mean_distance_cm"] = round(bucket["distance_cm"] / n, 6)
        bucket["mean_displacement_cm"] = round(bucket["displacement_cm"] / n, 6)
        bucket["mean_efficiency"] = round(bucket["efficiency"] / n, 6)
        bucket["mean_stalled_fraction"] = round(bucket["stalled_fraction"] / n, 6)

    return {
        "schema_version": ACTOR_PROGRESS_VERSION,
        "record": {
            "frames": n_frames,
            "step_seconds": step,
            "frames_bin_sha256": (manifest.get("binary") or {}).get("sha256"),
            "actors": len(actors),
        },
        "params": {"stall_cm": float(stall_cm)},
        "actors": rows,
        "by_kind": by_kind,
        "zero_progress_actors": [r["uid"] for r in rows if r["zero_progress"]],
        "progressing_actors": [r["uid"] for r in rows if not r["zero_progress"]],
    }


def _index_of(actors: list, uid: str) -> int:
    for i, a in enumerate(actors):
        if isinstance(a, dict) and (a.get("uid") == uid or a.get("id") == uid):
            return i
    raise LoopDetectError(f"actor {uid!r} is not in the record manifest")
