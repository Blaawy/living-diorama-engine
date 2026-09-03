"""Build LIVING_DIORAMA_YF_PHASE_1_MASTER.zip deterministically.

Deterministic means: fixed member order (sorted), fixed timestamps, fixed
external attributes and compression. Two builds from the same inputs produce
byte-identical archives, so the MASTER's own hash is meaningful.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
P1 = YF / "PHASE_01"
EV = YF / "EVIDENCE" / "PHASE_01"
WS = YF / "WORKSPACE"
SUMO = P1 / "proof" / "sumo"
STAGE = YF / "CACHE" / "master_stage_p1"
FIXED_DATE = (2026, 9, 3, 0, 0, 0)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def stage() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    for d in ("preview", "reports", "evidence", "identity", "artifacts"):
        (STAGE / d).mkdir(parents=True)

    # --- root ---
    shutil.copy2(P1 / "README_FOR_CHATGPT.md", STAGE / "README_FOR_CHATGPT.md")

    # --- reports ---
    for name, src in [
        ("PHASE_1_REPORT.md", P1 / "PHASE_1_REPORT.md"),
        ("ARCHITECTURE_DECISION_SUMO_UNREAL.md", P1 / "research" / "ARCHITECTURE_DECISION_SUMO_UNREAL.md"),
        ("CONCEPTUAL_DNA_EXTRACTION.md", P1 / "dna" / "CONCEPTUAL_DNA_EXTRACTION.md"),
        ("RED_TEAM_PHASE_1.md", P1 / "redteam" / "RED_TEAM_PHASE_1.md"),
        ("CITY_SAMPLE_PCG_COMPATIBILITY.md", P1 / "research" / "CITY_SAMPLE_PCG_COMPATIBILITY.md"),
        ("REPRODUCIBILITY.md", P1 / "REPRODUCIBILITY.md"),
    ]:
        shutil.copy2(src, STAGE / "reports" / name)

    # --- preview (honest: screenshots, no video) ---
    for png in sorted(EV.glob("*.png")):
        shutil.copy2(png, STAGE / "preview" / png.name)
    (STAGE / "preview" / "NOTE_NO_VIDEO.md").write_text(
        "# There is no preview video in this MASTER\n\n"
        "Phase 1 produced **no MP4 and no rendered frames outside the editor "
        "viewport**. That is deliberate: Phase 1's objective is a technical "
        "proof, and Phase 2 is the phase that produces a watchable living-world "
        "preview.\n\n"
        "The PNGs in this folder are Unreal Editor viewport captures showing 143 "
        "actors from simulation frame 1500 (t = 150.0 s) of the Phase 1 proof "
        "run, placed at their exact SUMO positions.\n\n"
        "**They show grey placeholder boxes on Unreal's default landscape.** "
        "They are evidence that SUMO truth reaches Unreal correctly. They are "
        "**not** a sample of the intended visual quality, and no road, building, "
        "vehicle or character asset exists in the project yet.\n\n"
        "- `unreal_sumo_frame1500_topdown.png` — the SUMO road grid is legible in "
        "the arrangement of the vehicles.\n"
        "- `unreal_sumo_frame1500_wide.png` — oblique view.\n"
        "- `unreal_sumo_frame1500_street.png` — near-ground view.\n"
        "- `unreal_pcg_grid_3600_points.png` — the PCG volume in the level. Note "
        "that **no geometry is visible in this shot**: the graph generates 3,600 "
        "points (proven by reading the node data, not by this picture), but the "
        "Static Mesh Spawner has no mesh assigned yet. Instancing meshes from "
        "those points is Phase 2 work.\n\n"
        "**The Director has watched nothing. No video exists.**\n",
        encoding="utf-8",
    )

    # --- evidence ---
    ev = STAGE / "evidence"
    shutil.copy2(EV / "test_results.txt", ev / "test_results.txt")
    for png in sorted(EV.glob("*.png")):
        shutil.copy2(png, ev / png.name)
    simdir = ev / "simulation"
    simdir.mkdir()
    for f in ("grid.net.xml", "grid.sumocfg", "veh.rou.xml", "ped.rou.xml",
              "close.add.xml", "grid_closed_novped.sumocfg",
              "grid_baseline_novped.sumocfg", "runA.tripinfo.xml",
              "ruled_noped.tripinfo.xml", "baseline_noped.tripinfo.xml"):
        src = SUMO / f
        if src.exists():
            shutil.copy2(src, simdir / f)
    rec = ev / "simulation" / "record_v1"
    rec.mkdir()
    shutil.copy2(SUMO / "record_v1" / "record_manifest.json", rec / "record_manifest.json")

    # RISK-1 closure evidence: 500 vehicles + 200 pedestrians, clean exit.
    cl = ev / "simulation" / "closure_v2"
    cl.mkdir()
    for f in ("baseline.tripinfo.xml", "ruled.tripinfo.xml",
              "ruled_repeat.tripinfo.xml", "closure_metrics.json",
              "persistent_changes.json"):
        src = SUMO / "closure_v2" / f
        if src.exists():
            shutil.copy2(src, cl / f)
    clrec = cl / "record_ruled"
    clrec.mkdir()
    shutil.copy2(SUMO / "closure_v2" / "record_ruled" / "record_manifest.json",
                 clrec / "record_manifest.json")
    shutil.copy2(SUMO / "closure_v2" / "record_ruled" / "frames.bin",
                 clrec / "frames.bin")

    # --- identity ---
    idd = STAGE / "identity"
    shutil.copy2(WS / "FREE_DEPENDENCY_LOCK.json", idd / "FREE_DEPENDENCY_LOCK.json")
    (idd / "CANONICAL_IDENTITY.json").write_text(
        json.dumps(
            {
                "role": "historically locked reference; NOT modified by this project",
                "repository": "Blaawy/living-diorama-engine",
                "commit": "d6ba9a8bc96a15b6aa7b8108160b821215645e3a",
                "tree": "8eb32592d35fd0bdb761f63014be4aff39d16ddf",
                "verified_checkout": r"C:\Users\BLaAw\Desktop\main\p20install",
                "verification": {
                    "commit_matches_contract": True,
                    "tree_matches_contract": True,
                    "working_tree_clean": True,
                    "git_fsck_clean": True,
                    "on_origin_main": True,
                    "commit_count": 36,
                    "re_verified_unchanged_at_phase_end": True,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (idd / "SOFTWARE_VERSIONS.json").write_text(
        json.dumps(
            {
                "unreal_engine": "5.8.2 (++UE5+Release-5.8, CL 56702186, promoted build)",
                "unreal_mcp_plugin": "1.0 Experimental (bundled with UE 5.8)",
                "eclipse_sumo": "1.27.1",
                "python": "3.13.15",
                "git": "2.55.0.windows.4",
                "ffmpeg": "9.0.1-full_build (gyan.dev)",
                "epic_games_launcher": "20.2.6-0+UE5",
                "os": "Windows 11 Pro 10.0.26200",
                "gpu": "NVIDIA GeForce RTX 5070 (12227 MiB) + RTX 4060 (8188 MiB), driver 610.88",
                "cpu": "Intel Core i9-14900KF, 24C/32T",
                "ram_gb": 31.79,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # --- artifacts ---
    art = STAGE / "artifacts"
    (art / "ldyf").mkdir()
    for py in sorted((WS / "ldyf").glob("*.py")):
        shutil.copy2(py, art / "ldyf" / py.name)
    (art / "ldyf" / "tests").mkdir()
    for py in sorted((WS / "ldyf" / "tests").glob("*.py")):
        shutil.copy2(py, art / "ldyf" / "tests" / py.name)
    (art / "schemas").mkdir()
    for js in sorted((WS / "ldyf" / "schemas").glob("*.json")):
        shutil.copy2(js, art / "schemas" / js.name)
    (art / "unreal_project").mkdir()
    proj = WS / "LivingDioramaYF"
    shutil.copy2(proj / "LivingDioramaYF.uproject", art / "unreal_project" / "LivingDioramaYF.uproject")
    shutil.copy2(proj / ".mcp.json", art / "unreal_project" / "mcp.json")
    pcg_asset = proj / "Content" / "PCG" / "PCG_LivingDiorama_Probe.uasset"
    if pcg_asset.exists():
        shutil.copy2(pcg_asset, art / "unreal_project" / "PCG_LivingDiorama_Probe.uasset")
    shutil.copy2(
        YF.parent / "MANIFESTS" / "YOUTUBE_FACTORY_CLEANUP_MANIFEST.json",
        art / "CLEANUP_MANIFEST.json",
    )


def write_sha_manifest() -> None:
    files = sorted(p for p in STAGE.rglob("*") if p.is_file())
    lines = [f"{sha256_file(p)}  {p.relative_to(STAGE).as_posix()}" for p in files]
    (STAGE / "identity" / "SHA256_MANIFEST.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def build_zip(out: Path) -> str:
    files = sorted(p for p in STAGE.rglob("*") if p.is_file())
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            zi = zipfile.ZipInfo(p.relative_to(STAGE).as_posix(), date_time=FIXED_DATE)
            zi.external_attr = 0o644 << 16
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.create_system = 0
            z.writestr(zi, p.read_bytes())
    return sha256_file(out)


if __name__ == "__main__":
    stage()
    write_sha_manifest()
    out = YF / "CACHE" / "LIVING_DIORAMA_YF_PHASE_1_MASTER.zip"
    digest = build_zip(out)
    n = len(list(STAGE.rglob("*")))
    print("files staged :", sum(1 for p in STAGE.rglob("*") if p.is_file()))
    print("zip bytes    :", out.stat().st_size)
    print("zip sha256   :", digest)
    print("path         :", out)
