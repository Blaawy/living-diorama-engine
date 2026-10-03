"""Phase-5 Gate B focused hard-kill proof for late production stages.

Clones an already verified real package, forces exactly one late stage to run,
TerminateProcess-kills produce inside it, then resumes with the same command.
Writes machine-readable evidence after every scenario.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

from ldyf.factory import faultlab as FL
from ldyf.factory import pipeline as P
from ldyf.factory import production as PR
from ldyf.factory.util import sha256_file


def digest_finished(pkg: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for rel in (
        "sim/simulation_result.json", "facts.json", "story.json", "shots.json",
        "narration.json", "voice/voice.json", "timeline.json",
        "audio/audio.json", "assembly.json",
    ):
        p = pkg / rel
        if p.is_file():
            rows[rel] = sha256_file(p)
    for p in sorted((pkg / "render").glob("*/shot_render.json")):
        rows[p.relative_to(pkg).as_posix()] = sha256_file(p)
    return rows

def write_evidence(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def force_voice(pkg: Path) -> None:
    wav = sorted((pkg / "voice").glob("*.wav"))[0]
    FL.corrupt_file(wav, mode="empty")


def force_audio(pkg: Path) -> None:
    FL.corrupt_file(pkg / "audio" / "audio.json", mode="truncate")


def force_assembly(pkg: Path) -> None:
    FL.corrupt_file(pkg / "episode.mp4", mode="truncate")


def force_audit(pkg: Path) -> None:
    (pkg / "truth_audit.json").unlink()


SCENARIOS = [
    ("voice", force_voice, FL.delayed(FL.line_contains("[narration] ran"), 0.5)),
    ("audio", force_audio, FL.delayed(FL.line_contains("[timeline] ran"), 1.0)),
    ("assembly", force_assembly, FL.delayed(FL.line_contains("[audio] "), 15.0)),
    ("audit", force_audit, FL.delayed(FL.line_contains("[assemble] "), 3.0)),
]

def main() -> int:
    brief, src, work, ev = (Path(x) for x in sys.argv[1:5])
    pkg = work.resolve()
    if pkg.exists():
        shutil.rmtree(pkg)
    shutil.rmtree(PR.state_dir_for(pkg), ignore_errors=True)
    shutil.copytree(src, pkg)
    initial = P.verify_package(pkg)
    baseline = digest_finished(pkg)
    rows: list[dict] = []
    failures: list[str] = []
    started = time.perf_counter()

    doc = {"in_progress": True, "source_verify": initial, "rows": rows, "failures": failures}
    write_evidence(ev, doc)

    for name, perturb, trigger in SCENARIOS:
        perturb(pkg)
        before = digest_finished(pkg)
        run = FL.run_produce(brief, pkg, kill_when=trigger, timeout_s=1800)
        row = {
            "stage": name, "killed": run["killed"],
            "seconds_until_kill": run["seconds"],
            "trigger": (run["trigger_line"] or "")[:180],
            "returncode_after_kill": run["returncode"],
            "package_json_present_after_kill": (pkg / "package.json").is_file(),
            "tmp_files_after_kill": sorted(p.relative_to(pkg).as_posix() for p in pkg.rglob("*.tmp")),
        }
        if not run["killed"]:
            failures.append(f"{name}: trigger did not kill the process; tail={run['stdout_tail'][-300:]}")
        if row["package_json_present_after_kill"]:
            failures.append(f"{name}: killed run left package.json present")
        time.sleep(2)
        resume = FL.run_produce(brief, pkg, timeout_s=2400)
        status = FL.status_of(pkg)
        row["resume_returncode"] = resume["returncode"]
        row["resume_seconds"] = resume["seconds"]
        row["resume_outcome"] = status.get("outcome")
        row["resume_flags"] = status.get("resumed")
        try:
            row["verify"] = P.verify_package(pkg)
        except Exception as exc:
            row["verify_error"] = repr(exc)
            failures.append(f"{name}: verify after resume failed: {exc}")
        after = digest_finished(pkg)
        row["baseline_drift"] = sorted(k for k, v in baseline.items() if after.get(k) != v)
        row["finished_before_kill_changed_after_resume"] = sorted(
            k for k, v in before.items() if k in after and after[k] != v)
        if status.get("outcome") != "complete":
            failures.append(f"{name}: resume outcome {status.get('outcome')} code {status.get('code')}")
        # The deliberately damaged artifact is expected to change back during recovery.
        # The invariant is that every deterministic artifact returns to the verified baseline.
        if row["baseline_drift"]:
            failures.append(f"{name}: deterministic artifacts drifted from baseline: {row['baseline_drift']}")
        rows.append(row)
        doc = {"in_progress": True, "source_verify": initial, "rows": rows, "failures": failures}
        write_evidence(ev, doc)
        print(f"[{name}] killed={row['killed']} resume={row['resume_outcome']} {row['resume_seconds']}s", flush=True)

    doc.update(in_progress=False, wall_seconds=round(time.perf_counter() - started, 1),
               verdict="PASS" if not failures else "FAIL", final_verify=P.verify_package(pkg))
    write_evidence(ev, doc)
    print(doc["verdict"], len(rows), "late-stage hard kills", len(failures), "failures")
    return 0 if not failures else 1

if __name__ == "__main__":
    raise SystemExit(main())