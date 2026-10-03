"""Gate B/D/E driver: a COLD production run killed (TerminateProcess) at every representative
stage, resumed each time, then finished. Writes machine-readable evidence.

    python tools_gateb.py <brief> <out dir> <evidence json> [--ports 55941]
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ldyf.factory import faultlab as FL
from ldyf.factory.production import state_dir_for
from ldyf.factory.util import sha256_file
from ldyf.factory import winproc


def sumo_count(pkg):
    needle = str(pkg).lower().replace("\\", "/")
    return sum(1 for r in winproc.find_processes("sumo.exe") if needle in r["command_line"].lower().replace("\\", "/"))


def snapshot(pkg):
    """Everything FINISHED right now, with the hash it must still have after a resume."""
    out = {}
    for p in sorted(pkg.glob("render/*/shot_render.json")):
        out[p.relative_to(pkg).as_posix()] = sha256_file(p)
    for p in ("sim/simulation_result.json", "replicates/20260904/simulation_result.json",
              "replicates/20260905/simulation_result.json", "voice/voice.json", "audio/audio.json",
              "assembly.json"):
        if (pkg / p).is_file():
            out[p] = sha256_file(pkg / p)
    return out


def main() -> int:
    brief, out, ev = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), Path(sys.argv[3])
    steps = []
    plan = [
        ("simulation (ruled arm, mid-run)", FL.line_contains("ruled t=600s")),
        ("render (mid shot, 12 frames on disk)", FL.frames_in("hook", 12)),
        ("render (between shots: 'hook' sealed)", FL.delayed(FL.path_exists("render/promise/frames"), 3.0)),
        ("voice (speech engine running)", FL.line_contains("[narration] ran")),
        ("audio (mix running)", FL.line_contains("[timeline] ran")),
        ("assembly (ffmpeg encoding)", FL.delayed(FL.line_contains("[audio] "), 25.0)),
        ("audit (re-deriving every sentence)", FL.delayed(FL.line_contains("[assemble] "), 5.0)),
        ("package (manifest/contact sheet)", FL.line_contains("[audit] ran")),
    ]
    t_all = time.perf_counter()
    for name, trig in plan[int(__import__("os").environ.get("GATEB_SKIP", "0")):]:
        before = snapshot(out) if out.exists() else {}
        r = FL.run_produce(brief, out, kill_when=trig, timeout_s=5400)
        row = {"kill_point": name, "killed": r["killed"], "trigger": (r["trigger_line"] or "")[:160],
               "seconds_until_kill": r["seconds"], "child_returncode": r["returncode"]}
        time.sleep(2)
        row["package_json_present_after_kill"] = (out / "package.json").is_file()
        row["tmp_files_after_kill"] = sorted(p.relative_to(out).as_posix() for p in out.rglob("*.tmp"))
        row["sumo_orphans_after_kill"] = sumo_count(out)
        if not r["killed"]:
            row["note"] = "finished before the trigger fired"
            row["final_status"] = FL.status_of(out).get("outcome")
            steps.append(row)
            if row["final_status"] == "complete":
                break
            continue
        # resume to the NEXT kill point is the next loop iteration; verify nothing finished was lost
        after = snapshot(out)
        row["finished_artifacts_before_kill"] = len(before)
        row["finished_artifacts_after_kill"] = len(after)
        row["finished_changed_by_kill"] = sorted(k for k in before if k in after and before[k] != after[k])
        steps.append(row)
    # final resume to completion
    t0 = time.perf_counter()
    before = snapshot(out)
    r = FL.run_produce(brief, out, timeout_s=7200)
    st = FL.status_of(out)
    after = snapshot(out)
    final = {"returncode": r["returncode"], "seconds": r["seconds"], "outcome": st.get("outcome"),
             "package_hash": st.get("package", {}).get("package_hash"),
             "resumed": st.get("resumed"), "performance": st.get("performance"),
             "finished_artifacts_downgraded": sorted(k for k in before if k in after and before[k] != after[k]),
             "verify": st.get("verify")}
    doc = {"brief": str(brief), "out": str(out), "steps": steps, "final_resume": final,
           "total_wall_seconds": round(time.perf_counter() - t_all, 1),
           "sumo_orphans_at_end": sumo_count(out)}
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"outcome": final["outcome"], "steps": len(steps), "wall": doc["total_wall_seconds"]}))
    return 0 if final["outcome"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())
