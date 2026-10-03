"""Gate E: soak. Many production runs in ONE long-lived process (so a leaked handle, a growing
cache or a stale module-level state shows up), each after a seeded perturbation, with a real
process-death cycle every few iterations. No manual repair between iterations.

    python tools_soak.py <brief> <finished package dir to clone> <work dir> <evidence json> [cycles] [seed]

Deterministic documents (facts, story, shots, narration, timeline, audio.json, voice.json) must
hash identically after every cycle; the episode is compared and REPORTED, never assumed.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import sys
import time
from pathlib import Path

from ldyf.factory import faultlab as FL
from ldyf.factory import production as PR
from ldyf.factory import winproc
from ldyf.factory.util import sha256_file

#: CONTENT must never change, whatever was repaired: simulation, facts, story, shots, captions, the audio
#: waveform. The HASH CHAIN documents bind the rendered pixels (Movie Render Queue frames are NOT byte-
#: reproducible), so they may change in a cycle that re-rendered a shot and in no other.
DETERMINISTIC = ("facts.json", "story.json", "shots.json", "captions.srt", "captions.vtt",
                 "audio/episode.wav", "sim/simulation_result.json")
CHAIN = ("narration.json", "timeline.json", "voice/voice.json", "audio/audio.json", "lineage.json",
         "truth_audit.json")


def _released(state: Path) -> bool:
    from ldyf.factory.production import lock_is_held
    return not lock_is_held(state)


def hashes(pkg: Path) -> dict[str, str]:
    h = {r: sha256_file(pkg / r) for r in DETERMINISTIC if (pkg / r).is_file()}
    n = json.loads((pkg / "narration.json").read_text(encoding="utf-8"))
    h["narration_texts"] = __import__("hashlib").sha256(
        json.dumps([[l["id"], l["text"]] for l in n["lines"]]).encode()).hexdigest()
    return h


def chain(pkg: Path) -> dict[str, str]:
    return {r: sha256_file(pkg / r) for r in CHAIN if (pkg / r).is_file()}


def shots_digest(pkg: Path) -> str:
    return __import__("hashlib").sha256(json.dumps(sorted(
        sha256_file(p) for p in (pkg / "render").glob("*/shot_render.json"))).encode()).hexdigest()


def perturb(kind: str, pkg: Path, rng: random.Random) -> str:
    if kind == "none":
        return "nothing"
    if kind == "voice_wav_empty":
        w = rng.choice(sorted((pkg / "voice").glob("*.wav")))
        FL.corrupt_file(w, mode="empty")
        return w.name
    if kind == "audio_json_truncate":
        FL.corrupt_file(pkg / "audio" / "audio.json", mode="truncate")
        return "audio.json"
    if kind == "manifest_truncate":
        FL.corrupt_file(pkg / "package.json", mode="truncate")
        return "package.json"
    if kind == "manifest_removed_plus_tmp":
        (pkg / "package.json").unlink()
        (pkg / "facts.json.tmp").write_bytes(b"{")
        (pkg / "render" / "hook" / "shot_render.json.tmp").write_bytes(b"{")
        return "package.json + 2 .tmp"
    if kind == "voice_lineage_stale":
        from ldyf.factory.util import seal
        d = json.loads((pkg / "voice" / "voice.json").read_text())
        d["narration_hash"] = "e" * 64
        (pkg / "voice" / "voice.json").write_text(json.dumps(seal(d, "voice_hash"), indent=1))
        return "voice.json narration_hash"
    if kind == "episode_flip":
        FL.corrupt_file(pkg / "episode.mp4")
        return "episode.mp4"
    if kind == "segment_flip":
        beat = rng.choice(["limits", "close", "moved"])
        FL.corrupt_file(pkg / "render" / beat / "segment.mp4", mode="truncate")
        return f"render/{beat}/segment.mp4"
    raise ValueError(kind)


KINDS = ["none", "voice_wav_empty", "audio_json_truncate", "manifest_truncate", "manifest_removed_plus_tmp",
         "voice_lineage_stale", "episode_flip", "segment_flip"]
KILLS = [FL.line_contains("[facts] "), FL.line_contains("[timeline] "), FL.line_contains("[assemble] "),
         FL.line_contains("[audit] ")]


def main() -> int:
    brief, src, work, ev = (Path(a) for a in sys.argv[1:5])
    cycles = int(sys.argv[5]) if len(sys.argv) > 5 else 30
    seed = int(sys.argv[6]) if len(sys.argv) > 6 else 20261003
    pkg = (work / "soak_pkg").resolve()
    if pkg.exists():
        shutil.rmtree(pkg)
    shutil.rmtree(PR.state_dir_for(pkg), ignore_errors=True)
    shutil.copytree(src, pkg)
    rng = random.Random(seed)
    base = hashes(pkg)
    chain_base, shots_base = chain(pkg), shots_digest(pkg)
    base_pkg = json.loads((pkg / "package.json").read_text())["package_hash"]
    base_episode = sha256_file(pkg / "episode.mp4")
    rows, failures = [], []
    t_all = time.perf_counter()
    h0 = winproc.process_memory()["handles"]
    for i in range(cycles):
        kind = "none" if i == 0 else rng.choice(KINDS)
        row = {"cycle": i, "perturbation": kind, "kill": None}
        t0 = time.perf_counter()
        try:
            row["target"] = perturb(kind, pkg, rng)
            if i > 0 and i % 6 == 0:                        # a real process death every sixth cycle
                trig = rng.choice(KILLS)
                if kind == "none":
                    row["target"] = perturb("episode_flip", pkg, rng)     # something to rebuild
                r = FL.run_produce(brief, pkg, kill_when=trig, timeout_s=3600)
                row["kill"] = {"killed": r["killed"], "trigger": (r["trigger_line"] or "")[:60],
                               "package_json_after_kill": (pkg / "package.json").is_file()}
                if r["killed"] and (pkg / "package.json").is_file():
                    failures.append(f"cycle {i}: killed run left package.json")
            st = PR.produce(brief, pkg, log=lambda s: None)
        except Exception as e:  # noqa: BLE001 - a soak records everything
            failures.append(f"cycle {i}: {type(e).__name__}: {e}")
            row["exception"] = repr(e)
            rows.append(row)
            continue
        h = hashes(pkg)
        drift = sorted(k for k in base if h.get(k) != base[k])
        c, sd = chain(pkg), shots_digest(pkg)
        rerendered = sd != shots_base
        chain_changed = sorted(k for k in chain_base if c.get(k) != chain_base[k])
        if chain_changed and not rerendered:
            drift += [f"chain:{k}" for k in chain_changed]      # a hash-chain change with no re-render
        chain_base, shots_base = c, sd
        mem = winproc.process_memory()
        state = PR.state_dir_for(pkg)
        row.update({
            "outcome": st["outcome"], "exit_code": st["exit_code"], "seconds": round(time.perf_counter() - t0, 1),
            "package_state_at_start": st["package"].get("state_at_start"),
            "package_hash_equal": st["package"].get("package_hash") == base_pkg,
            "episode_hash_equal": sha256_file(pkg / "episode.mp4") == base_episode if (pkg / "episode.mp4").is_file() else None,
            "deterministic_drift": drift, "shot_rerendered_this_cycle": rerendered,
            "chain_documents_changed": chain_changed,
            "handles": mem["handles"], "peak_working_set_mb": round((mem["peak_working_set_bytes"] or 0) / 2**20, 1),
            "tmp_files_in_package": len(list(pkg.rglob("*.tmp"))),
            "package_files": sum(1 for _ in pkg.rglob("*") if _.is_file()),
            "quarantine_files": len(list((state / "quarantine").glob("*"))) if (state / "quarantine").is_dir() else 0,
            "journal_bytes": (state / "journal.jsonl").stat().st_size,
            "stages_ran": st.get("performance", {}).get("stages_ran"),
            "lock_left": not _released(state)})
        if st["exit_code"] != 0:
            failures.append(f"cycle {i} ({kind}): exit {st['exit_code']} {st.get('code')}: {st.get('message')}")
        if drift:
            failures.append(f"cycle {i} ({kind}): deterministic drift {drift}")
        if row["lock_left"]:
            failures.append(f"cycle {i}: lock left behind")
        rows.append(row)
        ev.parent.mkdir(parents=True, exist_ok=True)
        ev.write_text(json.dumps({"in_progress": True, "rows": rows, "failures": failures}, indent=1), encoding="utf-8")
        print(f"[{i + 1}/{cycles}] {kind}: {row['outcome']} {row['seconds']} s handles={row['handles']}", flush=True)
    handles = [r["handles"] for r in rows if r.get("handles")]
    doc = {
        "brief": str(brief), "seed": seed, "cycles": cycles, "completed_cycles": len(rows),
        "wall_seconds": round(time.perf_counter() - t_all, 1),
        "process_kills": sum(1 for r in rows if r.get("kill") and r["kill"]["killed"]),
        "failures": failures, "rows": rows,
        "baseline_package_hash": base_pkg, "baseline_episode_sha256": base_episode,
        "baseline_deterministic_hashes": base,
        "handles_first_to_last": [handles[0], handles[-1]] if handles else None,
        "handles_start": h0, "handles_max": max(handles) if handles else None,
        "peak_working_set_mb_max": max((r.get("peak_working_set_mb") or 0) for r in rows),
        "episode_hash_changed_cycles": [r["cycle"] for r in rows if r.get("episode_hash_equal") is False],
        "verdict": "PASS" if not failures and len(rows) == cycles else "FAIL",
    }
    ev.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    print(doc["verdict"], len(failures), "failures")
    return 0 if doc["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
