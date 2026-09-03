"""Drive in-editor playback of a Simulation Record and MEASURE that it is right.

The standing law of this project is *read the output, never trust the status*.
So this does not stop at "playback started". It asks the editor, mid-playback,
where it actually placed a sample of actors, reads the same frame from the
sealed record out-of-process, and compares the two. Playback is correct when
the editor's actor transforms equal the record's, not when a function returned.

Flow
----
1. Connect over Python remote execution (`ldyf.unreal_remote`).
2. Load `ldyf/unreal/ldyf_playback.py` into the editor's interpreter by source.
3. `play(record_dir)` and let the editor tick for a while.
4. `status()` -- frames advanced, actors visible, wall time.
5. Pin playback at a chosen frame by stopping and re-playing with
   `max_frames = frame + 1`, then `verify_frame` inside the editor to fetch
   placed transforms; compare against the record read here.
"""

from __future__ import annotations

import json
import math
import struct
import time
from pathlib import Path
from typing import Any

from .unreal_remote import UnrealRemote

_SAMPLE = struct.Struct("<Ifffff")
_COUNT = struct.Struct("<I")
_HERE = Path(__file__).resolve().parent
PLAYBACK_SRC = _HERE / "unreal" / "ldyf_playback.py"


def _read_frame_local(record_dir: Path, frame_index: int) -> list[tuple]:
    manifest = json.loads((record_dir / "record_manifest.json").read_text(encoding="utf-8"))
    data = (record_dir / manifest["binary"]["file"]).read_bytes()
    off = 0
    for i in range(frame_index + 1):
        (n,) = _COUNT.unpack_from(data, off)
        off += _COUNT.size
        if i == frame_index:
            return [_SAMPLE.unpack_from(data, off + k * _SAMPLE.size) for k in range(n)]
        off += n * _SAMPLE.size
    raise IndexError(frame_index)


def _win(p: Path) -> str:
    return str(p).replace("\\", "/")


def run(record_dir: str | Path, *, play_seconds: float = 8.0, check_frame: int = 300,
        sample: int = 8, rate: float = 1.0) -> dict[str, Any]:
    record_dir = Path(record_dir).resolve()
    src = PLAYBACK_SRC.read_text(encoding="utf-8")
    report: dict[str, Any] = {"record_dir": str(record_dir)}

    with UnrealRemote(discover_timeout=30.0) as ue:
        report["node_id"] = ue.node_id

        # Load the playback module into the editor's interpreter as a module
        # object named ldyf_playback, so its globals persist between commands.
        bootstrap = (
            "import types, sys\n"
            "_m = types.ModuleType('ldyf_playback')\n"
            f"exec(compile({src!r}, 'ldyf_playback.py', 'exec'), _m.__dict__)\n"
            "sys.modules['ldyf_playback'] = _m\n"
            "print('ldyf_playback loaded')\n"
        )
        ue.exec_file(bootstrap)

        t0 = time.time()
        started = ue.eval(f"__import__('ldyf_playback').play({_win(record_dir)!r}, {rate})")
        report["play"] = started
        time.sleep(play_seconds)
        st = ue.eval("__import__('ldyf_playback').status()")
        report["status_after_play"] = st
        report["measured_frames_per_wall_second"] = (
            round(st["frame"] / max(1e-6, time.time() - t0), 1) if isinstance(st, dict) else None
        )

        # Pin at check_frame and measure placement against the sealed record.
        ue.eval(f"__import__('ldyf_playback').play({_win(record_dir)!r}, 1000.0, {check_frame + 1})")
        time.sleep(2.0)
        pinned = ue.eval("__import__('ldyf_playback').status()")
        report["pinned_status"] = pinned
        placed = ue.eval(
            f"__import__('ldyf_playback').verify_frame({_win(record_dir)!r}, {check_frame}, {sample})"
        )
        report["verify_frame_raw"] = placed

        expected = {r[0]: r for r in _read_frame_local(record_dir, check_frame)}
        worst_pos = 0.0
        worst_yaw = 0.0
        compared = 0
        missing = 0
        for s in placed.get("samples", []):
            idx = s["actor_index"]
            exp = expected.get(idx)
            if exp is None or s.get("placed") is None:
                missing += 1
                continue
            _, ex, ey, _ez, eyaw, _ = exp
            px, py, pyaw = s["placed"]["x"], s["placed"]["y"], s["placed"]["yaw"]
            worst_pos = max(worst_pos, math.hypot(px - ex, py - ey))
            worst_yaw = max(worst_yaw, abs((pyaw - eyaw + 180.0) % 360.0 - 180.0))
            compared += 1

        report["verdict"] = {
            "frame": check_frame,
            "actors_compared": compared,
            "actors_missing": missing,
            "worst_position_error_cm": round(worst_pos, 4),
            "worst_yaw_error_deg": round(worst_yaw, 4),
            "pinned_at_expected_frame": isinstance(pinned, dict) and pinned.get("frame") == check_frame,
            "pass": compared > 0 and missing == 0 and worst_pos < 0.5 and worst_yaw < 0.01
            and isinstance(pinned, dict) and pinned.get("frame") == check_frame,
        }
        report["stop"] = ue.eval("__import__('ldyf_playback').stop()")
    return report


if __name__ == "__main__":
    import sys

    rd = sys.argv[1] if len(sys.argv) > 1 else (
        r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY"
        r"\PHASE_01\proof\sumo\closure_v2\record_ruled"
    )
    print(json.dumps(run(rd), indent=2, default=str))
