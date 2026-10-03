"""Build the Phase 5 MASTER: one reviewable archive of the whole phase.

Modelled on build_master_p3.py and keeping its two hard-won properties:

* a FIXED member timestamp, so two builds from the same tree are byte-identical
  and the verifier's rebuild check means something;
* nothing is dropped silently: what is not shipped is listed, with size and
  sha256, in a stub that enters SHA256_MANIFEST.txt.

Layout of the archive:

    README_FOR_CHATGPT.md
    reports/      PHASE_5_REPORT.md, PHASE_5_ARCHITECTURE.md
    evidence/     episode/<name>/   the COMPLETE episode package the factory built:
                                    brief, both sealed arms and the repeat seeds,
                                    facts, story, shots, render (every segment),
                                    narration, voice, timeline, sound, episode.mp4,
                                    truth_audit.json, lineage.json, package.json
                  redteam/          the independent review and what came of it
                  proof/            gate matrix, determinism and resume evidence
    artifacts/    ldyf/ (code + tests) and the repo-root data the suite reads
    identity/     dependency lock, repo state, SHA256_MANIFEST.txt

The package is shipped WHOLE, so that from a fresh extraction

    python -m ldyf.factory verify --package ../evidence/episode/<name>

re-derives the episode from its evidence and the test suite attacks the real
thing rather than a fixture.

A document that states this archive's own sha256 cannot live inside it; the
Director review request stays beside the archive, never in it.
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
P5 = YF / "PHASE_05"
EV = YF / "EVIDENCE" / "PHASE_05"
CACHE = YF / "CACHE"
STAGE = CACHE / "master_stage_p5"
ZIP = CACHE / "LIVING_DIORAMA_YF_PHASE_5_MASTER.zip"
FIXED_DATE = (2026, 10, 3, 0, 0, 0)
EPISODES = ("close_baker_avenue", "close_baker_avenue_contrarian")
#: where each shipped package was built (the finished, verified one)
EPISODE_SRC = {"close_baker_avenue": "cold_baker", "close_baker_avenue_contrarian": "contrarian"}

PHASE1_PROOF_FILES = (
    "grid.net.xml", "risk1_repro.tripinfo.xml", "closure_v2/baseline.tripinfo.xml",
    "closure_v2/persistent_changes.json", "closure_v2/record_baseline/frames.bin",
    "closure_v2/record_baseline/record_manifest.json", "closure_v2/record_ruled/frames.bin",
    "closure_v2/record_ruled/record_manifest.json", "closure_v2/rule_manifest.json",
    "closure_v2/rule_manifest_reopen.json", "closure_v2/ruled.tripinfo.xml",
    "closure_v2/simulation_result.json")

EV_NEVER_SHIP = {"CLAUDE_PHASE5_LOCK_REVIEW_REQUEST.txt"}
#: Wall-clock scratch the package manifest itself excludes. Listed, not shipped.
PACKAGE_SKIP_SUFFIXES = (".tmp",)
#: Already-compressed media: stored, not deflated (deflating H.264 buys nothing).
STORED_SUFFIXES = (".mp4", ".jpg", ".png")


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
    for f in sorted(P5.glob("PHASE_5_*.md")):
        shutil.copy2(f, STAGE / "reports" / f.name)
        shipped_reports += 1
    readme = P5 / "README_FOR_CHATGPT_P5.md"
    if readme.is_file():
        shutil.copy2(readme, STAGE / "README_FOR_CHATGPT.md")

    # --- evidence: the episode package, whole ------------------------------
    ev = STAGE / "evidence"
    omitted: list[tuple[str, int, str]] = []
    for name in EPISODES:
        src = P5 / "work" / EPISODE_SRC[name]
        if not (src / "package.json").is_file():
            raise SystemExit(f"episode {name} is not a finished package; refusing to build a MASTER "
                             "around an unfinished episode")
        for f in sorted(src.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(src).as_posix()
            if rel.endswith(PACKAGE_SKIP_SUFFIXES):
                omitted.append((f"episode/{name}/{rel}", f.stat().st_size, sha256_file(f)))
                continue
            target = ev / "episode" / name / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
    if EV.is_dir():
        for f in sorted(EV.rglob("*")):
            if not f.is_file() or f.name in EV_NEVER_SHIP:
                continue
            target = ev / f.relative_to(EV)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
    lines = ["Files that exist in the episode package on the build machine and are NOT in this",
             "MASTER. (Rendered PNG frames are never kept by the factory: each shot's",
             "shot_render.json carries a digest over the sha256 of every frame, and the",
             "segment encoded from them IS shipped.)", "",
             "%-64s %12s  %s" % ("file", "bytes", "sha256")]
    for name, size, digest in omitted:
        lines.append("%-64s %12d  %s" % (name, size, digest))
    if not omitted:
        lines.append("(none)")
    (ev / "OMITTED_FROM_MASTER.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- the Phase 1 proof files the suite reads (earlier-phase tests look for them FIRST at
    # <extraction>/evidence/simulation and fall back to the live workspace; shipping them makes the
    # extraction self-contained, which the verifier enforces with an audit hook) ------------------
    proof = YF / "PHASE_01" / "proof" / "sumo"
    for rel in PHASE1_PROOF_FILES:
        target = ev / "simulation" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(proof / rel, target)

    # --- artifacts ---------------------------------------------------------
    art = STAGE / "artifacts"
    shutil.copytree(WS / "ldyf", art / "ldyf",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # every repo-root file the suite or the factory reads through REPO_ROOT, so
    # the suite can be collected and run from the MASTER alone
    for name in ("pytest.ini", "build_master_p5.py", "tools_gateb.py", "tools_gateb_late.py", "tools_soak.py", "tools_visual_audit.py", "city_layout.json", "asset_probe_v3.json",
                 "pcg_building_kits.json", "pcg_building_rules.json",
                 "EVIDENCE_vehicle_assembly.json"):
        if (WS / name).is_file():
            shutil.copy2(WS / name, art / name)
    # The locked level the shots were drawn in. Every shot's identity holds its
    # sha256 (render.scene_hashes), so the audit cannot re-seal the render from
    # an extraction without it. Our own authored asset, tracked in git.
    level = Path("LivingDioramaYF") / "Content" / "LD" / "L_LivingDiorama.umap"
    (art / level).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(WS / level, art / level)
    if (CACHE / "verify_master_p5.py").is_file():
        shutil.copy2(CACHE / "verify_master_p5.py", art / "verify_master_p5.py")

    # --- identity ----------------------------------------------------------
    ident = STAGE / "identity"
    if (WS / "FREE_DEPENDENCY_LOCK.json").is_file():
        shutil.copy2(WS / "FREE_DEPENDENCY_LOCK.json", ident / "FREE_DEPENDENCY_LOCK.json")
    head = subprocess.run(["git", "-C", str(WS), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(WS), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    tracked = subprocess.run(["git", "-C", str(WS), "ls-files"],
                             capture_output=True, text=True).stdout.splitlines()
    (ident / "WORKSPACE_REPO_STATE.json").write_text(json.dumps({
        "head": head, "tracked_files": len(tracked),
        "dirty_files_at_build": len([d for d in dirty.splitlines() if d.strip()]),
        "phase_2_lock": "rev10 e455dac3 (not reopened)",
        "phase_3_lock": "rev4 494d9458 at f361a59 (not reopened)",
        "phase_4_lock": "rev1 778231f1 at 526cb41 (not reopened)",
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
    out = []
    for p in files:
        rel = p.relative_to(STAGE).as_posix()
        if rel == "identity/SHA256_MANIFEST.txt":
            continue
        out.append(f"{sha256_file(p)}  {rel}")
    (ident / "SHA256_MANIFEST.txt").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("reports shipped :", shipped_reports)
    print("files omitted   :", len(omitted))


def build() -> None:
    stage()
    files = sorted(p for p in STAGE.rglob("*") if p.is_file())
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            info = zipfile.ZipInfo(p.relative_to(STAGE).as_posix(), FIXED_DATE)
            info.compress_type = (zipfile.ZIP_STORED if p.suffix.lower() in STORED_SUFFIXES
                                  else zipfile.ZIP_DEFLATED)
            info.external_attr = 0o600 << 16
            with z.open(info, "w", force_zip64=True) as dst, p.open("rb") as src:
                shutil.copyfileobj(src, dst, 1 << 20)
    print("files staged :", len(files))
    print("zip bytes    :", ZIP.stat().st_size)
    print("zip sha256   :", sha256_file(ZIP))
    print("path         :", ZIP)


if __name__ == "__main__":
    build()

