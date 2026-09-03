"""Build LIVING_DIORAMA_YF_PHASE_2_MASTER.zip deterministically (same laws as
build_master.py: sorted members, fixed timestamps, fixed attributes, deflate 9).

Ships: Phase 2 reports, every EVIDENCE/PHASE_02 file (JSON, PNG captures, logs
excerpts), the ldyf package with tests, our OWN authored Unreal assets (level,
PCG graph, material instances, project config) -- never the imported City
Sample / Megascans content (licensed; reproduced by CACHE/import_city_sample_subset.py
from evidence/import_manifest.json), DeepSeek worker reports verbatim, identity.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
P2 = YF / "PHASE_02"
EV = YF / "EVIDENCE" / "PHASE_02"
WS = YF / "WORKSPACE"
STAGE = YF / "CACHE" / "master_stage_p2"
FIXED_DATE = (2026, 9, 3, 0, 0, 0)
RUNS = Path(r"C:\Users\BLaAw\Desktop\main\_LIVING_DIORAMA_TOOLS\flash_bridge\runs")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _git(*a: str) -> str:
    return subprocess.run(["git", "-C", str(WS), *a], capture_output=True, text=True).stdout.strip()


def stage() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    for d in ("preview", "reports", "evidence", "identity", "artifacts"):
        (STAGE / d).mkdir(parents=True)
    shutil.copy2(P2 / "README_FOR_CHATGPT_P2.md", STAGE / "README_FOR_CHATGPT.md")
    for name in ("PHASE_2_REPORT.md", "PHASE_2_DECISIONS.md", "PHASE_2_GATE_PLAN.md", "PHASE_2_DESIGN_INPUTS.md", "RED_TEAM_PHASE_2.md"):
        src = P2 / name
        if src.exists():
            shutil.copy2(src, STAGE / "reports" / name)
    # preview: honest -- viewport captures only unless an MP4 exists
    for png in sorted(EV.glob("*.png")):
        shutil.copy2(png, STAGE / "preview" / png.name)
    mp4 = sorted(EV.glob("*.mp4"))
    for m in mp4:
        shutil.copy2(m, STAGE / "preview" / m.name)
    (STAGE / "preview" / ("NOTE_PREVIEW.md")).write_text(
        ("# Preview\n\n" + ("An MP4 preview is included; see reports/PHASE_2_REPORT.md for its ffprobe record.\n" if mp4 else
         "**There is no MP4 preview in this MASTER.** The PNGs are Unreal Editor viewport captures of the\n"
         "Phase 2 world (SUMO-derived road network, City Sample lane meshes, junction slabs, playback of the\n"
         "sealed closure record with City Sample vehicles). Movie Render Queue rendering was NOT done in the\n"
         "unattended session; the report says so plainly.\n")), encoding="utf-8")
    # evidence: everything machine-written under EVIDENCE/PHASE_02
    ev = STAGE / "evidence"
    for f in sorted(EV.iterdir()):
        if f.is_file() and f.suffix.lower() in (".json", ".txt", ".png", ".log", ".md", ".csv"):
            if f.suffix.lower() == ".log" and f.stat().st_size > 2_000_000:
                continue  # full editor logs are too large; excerpts are shipped
            shutil.copy2(f, ev / f.name)
    dumps = EV / "pcg_graph_dumps"
    if dumps.exists():
        (ev / "pcg_graph_dumps").mkdir()
        for f in sorted(dumps.glob("*.json")):
            shutil.copy2(f, ev / "pcg_graph_dumps" / f.name)
    # proof: road spec (from the same grid.net.xml as Phase 1) and test results
    (ev / "proof").mkdir()
    for f in ("road_spec.json",):
        if (P2 / "proof" / f).exists():
            shutil.copy2(P2 / "proof" / f, ev / "proof" / f)
    # worker reports verbatim
    rt = ev / "deepseek_workers"
    rt.mkdir()
    for run, task, name in (("yf_p2_build1", "roads", "build_roads.md"), ("yf_p2_build1", "interp", "build_record_interp.md"),
                            ("yf_p2_build1", "inventory", "build_world_inventory.md"), ("yf_p2_build1", "vehicle_kin", "build_vehicle_kinematics.md"),
                            ("yf_p2_build2", "loop_audit", "build_loop_audit.md"), ("yf_p2_fix1", "roads_fix", "fix_roads.md"),
                            ("yf_p2_analysts", "pcg_plan", "analysis_pcg_roads_plan.md"), ("yf_p2_analysts", "spline_actors", "analysis_spline_actors.md"),
                            ("yf_p2_build4", "playback_v2", "build_playback_v2.md"), ("yf_p2_build5", "humans", "build_humans.md"),
                            ("yf_p2_redteam", "attack_truth", "redteam_attacker_A_truth.md"), ("yf_p2_redteam", "attack_world", "redteam_attacker_B_world.md")):
        src = RUNS / run / task / "report.md"
        if src.exists():
            shutil.copy2(src, rt / name)
    # identity
    idd = STAGE / "identity"
    shutil.copy2(WS / "FREE_DEPENDENCY_LOCK.json", idd / "FREE_DEPENDENCY_LOCK.json")
    (idd / "WORKSPACE_REPO_STATE.json").write_text(json.dumps({
        "head": _git("rev-parse", "HEAD"), "tracked_files": len(_git("ls-files").splitlines()),
        "dirty_files_at_build": len(_git("status", "--porcelain").splitlines())}, indent=2), encoding="utf-8")
    can = Path(r"C:\Users\BLaAw\Desktop\main\p20install")
    (idd / "CANONICAL_IDENTITY.json").write_text(json.dumps({
        "repository": "Blaawy/living-diorama-engine", "commit": subprocess.run(["git", "-C", str(can), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "tree": subprocess.run(["git", "-C", str(can), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True).stdout.strip(),
        "porcelain_lines": len(subprocess.run(["git", "-C", str(can), "status", "--porcelain"], capture_output=True, text=True).stdout.splitlines()),
        "role": "historically locked reference; NOT modified by this project"}, indent=2), encoding="utf-8")
    # artifacts: package + tests + our own authored assets + config
    art = STAGE / "artifacts"
    (art / "ldyf").mkdir()
    for sub in ("", "unreal", "tests", "schemas"):
        d = WS / "ldyf" / sub if sub else WS / "ldyf"
        (art / "ldyf" / sub).mkdir(exist_ok=True) if sub else None
        for f in sorted(d.glob("*.py")) + sorted(d.glob("*.json")):
            shutil.copy2(f, art / "ldyf" / sub / f.name if sub else art / "ldyf" / f.name)
    (art / "pytest.ini").write_text("[pytest]\ntestpaths = ldyf/tests\n", encoding="utf-8")
    proj = WS / "LivingDioramaYF"
    up = art / "unreal_project"
    up.mkdir()
    shutil.copy2(proj / "LivingDioramaYF.uproject", up / "LivingDioramaYF.uproject")
    shutil.copy2(proj / "Config" / "DefaultEngine.ini", up / "DefaultEngine.ini")
    for rel in ("Content/LD/L_LivingDiorama.umap", "Content/PCG/PCG_LD_Roads.uasset", "Content/LD/Materials/MI_LD_Ground.uasset", "Content/LD/Materials/MI_LD_Sidewalk.uasset",
                "Plugins/CitySamplePCG/CitySamplePCG.uplugin", "Plugins/Traffic/Traffic.uplugin"):
        src = proj / rel
        if src.exists():
            dst = up / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    for tool in ("tools_author_pcg_roads.py", "build_master_p2.py"):
        if (WS / tool).exists():
            shutil.copy2(WS / tool, art / tool)
    for tool in ("import_city_sample_subset.py", "update_pcg_ground.py", "probe_vehicle_mesh.py", "inspect_city_sample_fast.py"):
        if (YF / "CACHE" / tool).exists():
            shutil.copy2(YF / "CACHE" / tool, art / tool)


def write_sha_manifest() -> None:
    files = sorted(p for p in STAGE.rglob("*") if p.is_file())
    (STAGE / "identity" / "SHA256_MANIFEST.txt").write_text(
        "\n".join(f"{sha256_file(p)}  {p.relative_to(STAGE).as_posix()}" for p in files) + "\n", encoding="utf-8")


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
    out = YF / "CACHE" / "LIVING_DIORAMA_YF_PHASE_2_MASTER.zip"
    digest = build_zip(out)
    print("files staged :", sum(1 for p in STAGE.rglob("*") if p.is_file()))
    print("zip bytes    :", out.stat().st_size)
    print("zip sha256   :", digest)
    print("path         :", out)
