"""Build the Phase 3 MASTER: one reviewable archive of the whole phase.

Modelled on build_master_p2.py and keeping its two hard-won properties:

* a FIXED member timestamp, so two builds from the same tree are byte-identical
  and the verifier's rebuild check means something;
* every omission leaves a STUB that enters SHA256_MANIFEST.txt, so a reviewer
  audits what is missing instead of having to notice an absence.

What is deliberately NOT shipped: the raw `*.fcd.xml` simulator output, ~49 MB
each and ~490 MB in total. The sealed record (`record_manifest.json` +
`frames.bin`) is the canonical replayable truth and IS shipped; the FCD is the
intermediate it was built from. Each omitted file leaves a stub naming its size
and its sha256, so its identity is still in the archive.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
WS = YF / "WORKSPACE"
P3 = YF / "PHASE_03"
EV = YF / "EVIDENCE" / "PHASE_03"
CACHE = YF / "CACHE"
STAGE = CACHE / "master_stage_p3"
ZIP = CACHE / "LIVING_DIORAMA_YF_PHASE_3_MASTER.zip"
FIXED_DATE = (2026, 10, 2, 0, 0, 0)

TEXT_SUFFIXES = (".md", ".json", ".txt", ".csv")

#: A document that states the MASTER's own sha256 cannot live inside the MASTER:
#: it would be stale the moment the archive is written, and the Phase 2 rev 7
#: build shipped exactly that and failed its own verifier. The review request is
#: addressed TO the reviewer and stays beside the archive, never in it.
EV_NEVER_SHIP = {"CLAUDE_PHASE3_LOCK_REVIEW_REQUEST.txt"}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def stage() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    for d in ("reports", "evidence", "identity", "artifacts"):
        (STAGE / d).mkdir(parents=True)

    # --- reports -----------------------------------------------------------
    shipped_reports = 0
    for f in sorted(P3.glob("PHASE_3_*.md")):
        shutil.copy2(f, STAGE / "reports" / f.name)
        shipped_reports += 1
    readme = P3 / "README_FOR_CHATGPT_P3.md"
    if readme.is_file():
        shutil.copy2(readme, STAGE / "README_FOR_CHATGPT.md")

    # --- evidence ----------------------------------------------------------
    ev = STAGE / "evidence"
    omitted: list[tuple[str, int, str]] = []
    for f in sorted(EV.iterdir()):
        if f.name in EV_NEVER_SHIP:
            continue
        if f.is_file() and f.suffix.lower() in TEXT_SUFFIXES:
            shutil.copy2(f, ev / f.name)

    for epdir in sorted(d for d in EV.iterdir() if d.is_dir()):
        dst = ev / epdir.name
        dst.mkdir(parents=True, exist_ok=True)
        for f in sorted(epdir.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(epdir)
            if f.suffix.lower() == ".xml" and f.name.endswith(".fcd.xml"):
                omitted.append((f"{epdir.name}/{rel.as_posix()}",
                                f.stat().st_size, sha256_file(f)))
                continue
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)

    if omitted:
        lines = [
            "These files are NOT in this MASTER. Each is raw SUMO FCD output,",
            "the intermediate the sealed record was built from; the sealed",
            "record (record_manifest.json + frames.bin) IS shipped and is the",
            "canonical replayable truth. Their identity is preserved here so a",
            "reviewer can check any copy they are given.",
            "",
            "%-56s %12s  %s" % ("file", "bytes", "sha256"),
        ]
        for name, size, digest in omitted:
            lines.append("%-56s %12d  %s" % (name, size, digest))
        (ev / "OMITTED_FCD_OUTPUT.txt").write_text("\n".join(lines) + "\n",
                                                   encoding="utf-8")

    # --- artifacts ---------------------------------------------------------
    art = STAGE / "artifacts"
    shutil.copytree(WS / "ldyf", art / "ldyf",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # pytest.ini plus every repo-root data file the suite reads. The tests
    # resolve these through REPO_ROOT, so the extraction must carry them or the
    # suite cannot even be COLLECTED from the MASTER alone -- which is exactly
    # what the first Phase 3 build did.
    for name in ("pytest.ini", "build_master_p3.py", "city_layout.json",
                 "asset_probe_v3.json", "pcg_building_kits.json",
                 "pcg_building_rules.json"):
        if (WS / name).is_file():
            shutil.copy2(WS / name, art / name)
    for f in sorted(CACHE.glob("p3_*.py")):
        shutil.copy2(f, art / f.name)

    # --- identity ----------------------------------------------------------
    ident = STAGE / "identity"
    for name in ("FREE_DEPENDENCY_LOCK.json",):
        if (WS / name).is_file():
            shutil.copy2(WS / name, ident / name)
    head = subprocess.run(["git", "-C", str(WS), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(WS), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    tracked = subprocess.run(["git", "-C", str(WS), "ls-files"],
                             capture_output=True, text=True).stdout.splitlines()
    (ident / "WORKSPACE_REPO_STATE.json").write_text(json.dumps({
        "head": head, "tracked_files": len(tracked),
        "dirty_files_at_build": len([d for d in dirty.splitlines() if d.strip()]),
    }, indent=2) + "\n", encoding="utf-8")

    canonical = Path(r"C:\Users\BLaAw\Desktop\main\p20install")
    if canonical.is_dir():
        c_head = subprocess.run(["git", "-C", str(canonical), "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
        c_tree = subprocess.run(["git", "-C", str(canonical), "rev-parse", "HEAD^{tree}"],
                                capture_output=True, text=True).stdout.strip()
        c_dirty = subprocess.run(["git", "-C", str(canonical), "status", "--porcelain"],
                                 capture_output=True, text=True).stdout.strip()
        (ident / "CANONICAL_IDENTITY.json").write_text(json.dumps({
            "repo": "Blaawy/living-diorama-engine",
            "head": c_head, "tree": c_tree,
            "porcelain_empty": c_dirty == "",
            "law": "the canonical historical repo must never be mutated",
        }, indent=2) + "\n", encoding="utf-8")

    # --- manifest ----------------------------------------------------------
    files = sorted(p for p in STAGE.rglob("*") if p.is_file())
    lines = []
    for p in files:
        rel = p.relative_to(STAGE).as_posix()
        if rel == "identity/SHA256_MANIFEST.txt":
            continue
        lines.append(f"{sha256_file(p)}  {rel}")
    (ident / "SHA256_MANIFEST.txt").write_text("\n".join(lines) + "\n",
                                               encoding="utf-8")
    print("reports shipped   :", shipped_reports)
    print("fcd files omitted :", len(omitted))


def build() -> None:
    stage()
    files = sorted(p for p in STAGE.rglob("*") if p.is_file())
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            info = zipfile.ZipInfo(p.relative_to(STAGE).as_posix(), FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            z.writestr(info, p.read_bytes())
    print("files staged :", len(files))
    print("zip bytes    :", ZIP.stat().st_size)
    print("zip sha256   :", sha256_file(ZIP))
    print("path         :", ZIP)


if __name__ == "__main__":
    build()
