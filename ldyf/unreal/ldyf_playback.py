"""Simulation Record playback -- runs INSIDE the Unreal Editor's Python.

Loaded via remote execution (see ldyf/unreal_remote.py) or `py ldyf_playback.py`
from the editor console. Deliberately self-contained: it does not import `ldyf`,
because the editor's Python has neither our package nor our venv on its path.
The binary layout mirrors `ldyf.sumo_record` exactly and is re-stated here.

Authority
---------
This module is presentation only. It reads a sealed record and moves actors.
Nothing here writes simulation truth, and there is no code path by which what
it draws feeds back into what the simulation decided.

Record layout (little-endian), from `ldyf.sumo_record`:
    per frame:  uint32 count, then count x  <Ifffff>
                actor_index, x_cm, y_cm, z_cm, yaw_deg, speed_mps
"""

from __future__ import annotations

import json
import math
import struct
import time
from pathlib import Path

import unreal  # type: ignore[import-not-found]

_SAMPLE = struct.Struct("<Ifffff")
_COUNT = struct.Struct("<I")

# One global session so repeated `play()` calls replace the previous one
# instead of stacking tick callbacks.
_SESSION: dict | None = None

# Placeholder representation until Phase 2 supplies real meshes. Kept in one
# table so the swap is one edit.
_REPRESENTATION = {
    "vehicle": {"mesh": "/Engine/BasicShapes/Cube.Cube", "scale": (4.5, 1.8, 1.5), "z": 75.0},
    "person":  {"mesh": "/Engine/BasicShapes/Cylinder.Cylinder", "scale": (0.5, 0.5, 1.75), "z": 87.5},
}


def _load_frames(frames_path: Path) -> list[list[tuple]]:
    """Read every frame into memory once. 23 MB for 600 s -- trivial in-editor."""
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


def _spawn_actor(kind: str, label: str) -> "unreal.Actor":
    rep = _REPRESENTATION[kind]
    mesh = unreal.EditorAssetLibrary.load_asset(rep["mesh"])
    actor = unreal.EditorLevelLibrary.spawn_actor_from_object(
        mesh, unreal.Vector(0, 0, -100000), unreal.Rotator(0, 0, 0)
    )
    actor.set_actor_label(label)
    actor.set_actor_scale3d(unreal.Vector(*rep["scale"]))
    actor.set_actor_hidden_in_game(False)
    return actor


def stop() -> dict:
    """Tear down the current session. Idempotent."""
    global _SESSION
    if _SESSION is None:
        return {"stopped": False, "reason": "no session"}
    s = _SESSION
    if s.get("tick_handle") is not None:
        unreal.unregister_slate_post_tick_callback(s["tick_handle"])
    for a in s["actors"].values():
        try:
            if a is not None:
                a.destroy_actor()
        except Exception:
            pass
    _SESSION = None
    return {"stopped": True, "frames_played": s["frame"], "actors_destroyed": len(s["actors"])}


def status() -> dict:
    if _SESSION is None:
        return {"active": False}
    s = _SESSION
    return {
        "active": True,
        "frame": s["frame"],
        "frame_count": s["frame_count"],
        "sim_time_s": round(s["t_begin"] + s["frame"] * s["step"], 2),
        "actors_spawned": len(s["actors"]),
        "visible_now": s["visible_now"],
        "ticks": s["ticks"],
        "wall_elapsed_s": round(time.time() - s["started"], 2),
        "record_sha256": s["record_sha256"],
    }


def play(record_dir: str, playback_rate: float = 1.0, max_frames: int | None = None) -> dict:
    """Start playing a Simulation Record. Replaces any running session."""
    global _SESSION
    stop()

    rd = Path(record_dir)
    manifest = json.loads((rd / "record_manifest.json").read_text(encoding="utf-8"))
    frames = _load_frames(rd / manifest["binary"]["file"])
    step = float(manifest["clock"]["step_seconds"])
    t_begin = float(manifest["clock"]["t_begin"])

    actors_meta = manifest["actors"]
    s = {
        "frames": frames,
        "frame_count": len(frames),
        "frame": 0,
        "step": step,
        "t_begin": t_begin,
        "rate": playback_rate,
        "actors": {},           # actor_index -> unreal.Actor (lazy)
        "kinds": [a["kind"] for a in actors_meta],
        "labels": [f"LD_{a['uid'].replace(':', '_')}" for a in actors_meta],
        "visible_now": 0,
        "ticks": 0,
        "accum": 0.0,
        "started": time.time(),
        "record_sha256": manifest["binary"]["sha256"],
        "max_frames": max_frames if max_frames is not None else len(frames),
        "tick_handle": None,
    }

    def on_tick(delta_seconds: float) -> None:
        if _SESSION is not s:
            return
        s["ticks"] += 1
        s["accum"] += delta_seconds * s["rate"]
        advanced = False
        while s["accum"] >= s["step"] and s["frame"] < s["max_frames"] - 1:
            s["accum"] -= s["step"]
            s["frame"] += 1
            advanced = True
        if not advanced and s["ticks"] > 1:
            return
        rows = s["frames"][s["frame"]]
        present = set()
        for idx, x, y, z, yaw, _speed in rows:
            present.add(idx)
            a = s["actors"].get(idx)
            if a is None:
                a = _spawn_actor(s["kinds"][idx], s["labels"][idx])
                s["actors"][idx] = a
            zz = z + _REPRESENTATION[s["kinds"][idx]]["z"]
            a.set_actor_location_and_rotation(
                unreal.Vector(x, y, zz),
                # unreal.Rotator(roll, pitch, yaw): yaw is the THIRD argument.
                # The verifier caught yaw landing in the pitch slot (RT-14).
                unreal.Rotator(0.0, 0.0, yaw), False, False
            )
            a.set_actor_hidden_in_game(False)
        # actors not in this frame have not entered yet, or have arrived: park them
        for idx, a in s["actors"].items():
            if idx not in present:
                a.set_actor_location(unreal.Vector(0, 0, -100000), False, False)
        s["visible_now"] = len(present)
        if s["frame"] >= s["max_frames"] - 1:
            unreal.unregister_slate_post_tick_callback(s["tick_handle"])
            s["tick_handle"] = None

    s["tick_handle"] = unreal.register_slate_post_tick_callback(on_tick)
    _SESSION = s
    return {
        "started": True,
        "frame_count": len(frames),
        "actors_in_record": len(actors_meta),
        "step_seconds": step,
        "record_sha256": s["record_sha256"],
    }


def verify_frame(record_dir: str, frame_index: int, sample: int = 5) -> dict:
    """Read one frame from disk and report the transforms the record demands.

    Used by the out-of-process verifier: it compares these against what the
    editor actually placed, so playback correctness is measured, not assumed.
    """
    rd = Path(record_dir)
    manifest = json.loads((rd / "record_manifest.json").read_text(encoding="utf-8"))
    frames = _load_frames(rd / manifest["binary"]["file"])
    rows = frames[frame_index][:sample]
    out = []
    for idx, x, y, z, yaw, speed in rows:
        a = _SESSION["actors"].get(idx) if _SESSION else None
        placed = None
        if a is not None:
            loc = a.get_actor_location()
            rot = a.get_actor_rotation()
            placed = {"x": loc.x, "y": loc.y, "yaw": rot.yaw}
        out.append({"actor_index": idx, "uid": manifest["actors"][idx]["uid"],
                    "expected": {"x": x, "y": y, "yaw": yaw}, "placed": placed})
    return {"frame": frame_index, "samples": out}
