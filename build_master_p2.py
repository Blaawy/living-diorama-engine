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

# Files that are WRITTEN BESIDE the zip after it is built, and must never be
# swept into it. The review request asks the Director to review this MASTER;
# an archive can no more contain the request to review itself than it can
# contain the result of verifying itself. Sweeping it in also destroys the
# byte-identical rebuild the verifier requires, because it does not exist at
# first build and does at the second.
EV_NEVER_SHIP = {"CLAUDE_PHASE2_LOCK_REVIEW_REQUEST.txt"}
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
    for name in ("PHASE_2_SGD_CITY.md", "RED_TEAM_PHASE_2_SGD.md",
                 "PHASE_2_REPORT.md", "PHASE_2_DECISIONS.md", "PHASE_2_GATE_PLAN.md", "PHASE_2_DESIGN_INPUTS.md", "RED_TEAM_PHASE_2.md"):
        src = P2 / name
        if src.exists():
            shutil.copy2(src, STAGE / "reports" / name)
    # preview: the MP4, a still per shot, and the named viewport captures.
    # The 2,160 rendered PNGs (about 7 GB) are NEVER shipped; the report cites
    # their ffprobe record and the stills are drawn from them.
    for sub in ("preview_stills",):
        d = EV / sub
        if d.exists():
            (STAGE / "preview" / sub).mkdir(exist_ok=True)
            for f in sorted(d.glob("*.png")):
                shutil.copy2(f, STAGE / "preview" / sub / f.name)
    # Only the preview of the city that ships. phase2_preview_timelapse.mp4 is
    # a September render of the LEGACY massing city; presenting it beside the
    # current preview would show buildings that no longer exist.
    mp4 = [m for m in sorted(EV.glob("*.mp4")) if m.name == "phase2_preview.mp4"]
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
        if f.name in EV_NEVER_SHIP:
            continue
        if f.is_file() and f.suffix.lower() in (".json", ".txt", ".png", ".log", ".md", ".csv"):
            if f.suffix.lower() == ".log" and f.stat().st_size > 2_000_000:
                # A silent skip is what a reviewer cannot audit: the file is
                # simply absent and nothing in the zip says so. Leave a stub,
                # which then enters SHA256_MANIFEST.txt like any other member.
                (ev / (f.name + ".OMITTED.txt")).write_text(
                    "%s was omitted from this MASTER: %d bytes of editor log, "
                    "too large to review.\nThe excerpts that matter are quoted "
                    "in reports/, and the full log stays in the working tree at "
                    "EVIDENCE/PHASE_02/%s.\n" % (f.name, f.stat().st_size,
                                                 f.name),
                    encoding="utf-8")
                continue
            if f.stat().st_size > 8_000_000:
                # e.g. sequence_bake.json is ~49 MB of baked keys. Ship a
                # stub naming it and its counts rather than silently dropping
                # it or bloating the MASTER past reviewability.
                (ev / (f.name + ".OMITTED.txt")).write_text(
                    "%s was omitted from this MASTER: %d bytes, too large "
                    "to review.\nIts counts block is quoted in "
                    "reports/PHASE_2_REPORT.md and in "
                    "evidence/sequence_bake_counts.json, and it is "
                    "reproducible by ldyf.sequence_bake.bake_keys from the "
                    "sealed record.\n"
                    % (f.name, f.stat().st_size), encoding="utf-8")
                continue
            shutil.copy2(f, ev / f.name)
    # renders of the SGD city, including the ones that FAILED and the one a
    # false "visual pass" was reported on -- shipped under names that say so
    (ev / "renders").mkdir()
    for src_name, dst_name in (
            ("look_fullcity_sfd", "look_fullcity_sfd"),
            ("look_shots_sfd", "look_shots_sfd"),
            ("look_fullcity", "look_fullcity_NYA_FAILED"),
            ("look_v2final", "look_v2final_RETRACTED")):
        d = EV / src_name
        if d.exists():
            (ev / "renders" / dst_name).mkdir()
            for f in sorted(d.glob("*.png")):
                shutil.copy2(f, ev / "renders" / dst_name / f.name)
    # Evidence subdirectories. The builder used to copy only top-level files,
    # so anything written into a subfolder could not reach the zip at all and
    # nothing recorded that. Text evidence from every subfolder is small, so it
    # all ships; image folders are curated (preview_mrq alone holds 2160 PNGs),
    # and every curated-out folder leaves a stub naming it, its file count and
    # its bytes, so the omission is in the manifest rather than invisible.
    shipped_render_dirs = {"look_fullcity_varied", "look_shots_varied",
                           "look_fullcity_sfd", "look_shots_sfd",
                           "look_fullcity", "look_v2final", "preview_stills",
                           "pcg_graph_dumps", "proof"}
    text_suffixes = (".md", ".json", ".txt", ".csv")
    sub_text = 0
    omitted_dirs = []
    for d in sorted(x for x in EV.iterdir() if x.is_dir()):
        if d.name in shipped_render_dirs:
            continue
        texts = [f for f in sorted(d.iterdir())
                 if f.is_file() and f.suffix.lower() in text_suffixes
                 and f.stat().st_size <= 2_000_000]
        if texts:
            (ev / d.name).mkdir(exist_ok=True)
            for f in texts:
                shutil.copy2(f, ev / d.name / f.name)
                sub_text += 1
        others = [f for f in d.iterdir() if f.is_file() and f not in texts]
        if others:
            size = sum(f.stat().st_size for f in others)
            omitted_dirs.append((d.name, len(others), size))
            (ev / (d.name + ".NOT_SHIPPED.txt")).write_text(
                "EVIDENCE/PHASE_02/%s holds %d file(s) not shipped in this "
                "MASTER (%d bytes): captures and frames, kept in the working "
                "tree.\nThe text evidence from this folder IS shipped, under "
                "evidence/%s/.\n" % (d.name, len(others), size, d.name),
                encoding="utf-8")
    print("evidence subfolders: %d text files shipped, %d folders stubbed"
          % (sub_text, len(omitted_dirs)))

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
    for run, task, name in (
            ("yf_p2_build1", "roads", "p2_build_roads.md"),
            ("yf_p2_build1", "interp", "p2_build_record_interp.md"),
            ("yf_p2_build1", "inventory", "p2_build_world_inventory.md"),
            ("yf_p2_build1", "vehicle_kin", "p2_build_vehicle_kinematics.md"),
            ("yf_p2_build2", "loop_audit", "p2_build_loop_audit.md"),
            ("yf_p2_fix1", "roads_fix", "p2_fix_roads.md"),
            ("yf_p2_build4", "playback_v2", "p2_build_playback_v2.md"),
            ("yf_p2_build5", "humans", "p2_build_humans.md"),
            ("yf_p2_redteam", "attack_truth", "p2_redteam_A_truth.md"),
            ("yf_p2_redteam", "attack_world", "p2_redteam_B_world.md"),
            # closure pass
            ("yf_p2c_w1", "verify3d", "closure_build_verify3d.md"),
            ("yf_p2c_w1", "sequence", "closure_build_sequence_bake.md"),
            ("yf_p2c_w2", "roadgeom", "closure_build_road_geometry.md"),
            ("yf_p2c_w3", "lots", "closure_build_city_layout.md"),
            ("yf_p2d_w1", "facade", "closure_build_facade_spec.md"),
            ("yf_p2d_w1", "dressing_tests", "closure_build_dressing_tests.md"),
            ("yf_p2d_w1", "shot_planner", "closure_build_shot_planner.md"),
            ("yf_p2d_w1", "dressing_check", "closure_dressing_check_NO_WRITE_run.md"),
            ("yf_p2d_w3", "dressing_check", "closure_build_dressing_check.md"),
            ("yf_p2e_rt", "measure", "closure_redteam_A_measurements.md"),
            ("yf_p2e_rt", "claims", "closure_redteam_B_claim_table.md"),
            ("yf_p2e_rt", "render", "closure_redteam_C_render_and_loops.md"),
            # unattended session
            ("yf_p2f_w1", "ground", "unattended_build_ground_plan_REMOVED.md"),
            ("yf_p2f_w1", "facade2", "unattended_build_facade_v2.md"),
            ("yf_p2f_w1", "foliage", "unattended_build_foliage_plan.md"),
            ("yf_p2f_w1", "perf", "unattended_build_perf_report.md"),
            ("yf_p2f_w1", "roadcheck2", "unattended_roadcheck_NO_WRITE_run.md"),
            ("yf_p2f_w1", "horizon", "unattended_horizon_NO_WRITE_run.md"),
            ("yf_p2g_w2", "ground_fix", "unattended_fix_ground_plan.md"),
            ("yf_p2g_w2", "foliage_fix", "unattended_fix_foliage_plan.md"),
            ("yf_p2g_w2", "roadcheck2", "unattended_roadcheck_REIMPL_REVERTED.md"),
            ("yf_p2g_w2", "horizon", "unattended_build_horizon_REMOVED.md"),
            ("yf_p2h_w3", "horizon_fix", "unattended_fix_horizon.md"),
            # final integration pass
            ("p2f_atk", "attack", "p2f_technical_attacker.md"),
            ("p2f_w1", "buildgeom", "p2f_buildgeom.md"),
            ("p2f_w1", "slinputs", "p2f_slinputs.md"),
            ("p2f_w1", "asphalt", "p2f_asphalt.md"),
            ("p2f_w1", "backdropvar", "p2f_backdropvar.md"),
            ("p2f_w1", "shotplan", "p2f_shotplan.md"),
            ("p2f_w1", "perf", "p2f_perf.md"),
            ("p2f_w1", "treepolish", "p2f_treepolish.md"),
            ("p2g_w1", "bldgint", "p2g_bldgint.md"),
            ("p2g_w1", "slint", "p2g_slint.md"),
            ("p2g_w1", "atkfix", "p2g_atkfix.md"),
            # City Sample PCG building architecture
            ("p2h_w1", "stylemap", "p2h_stylemap.md"),
            ("p2h_w1", "pcgspec", "p2h_pcgspec.md"),
            # SGD buildings: grammar driver, grouping, palette
            ("p2i_sgd", "sgd", "p2i_sgd.md"),
            ("p2j_grp", "grp", "p2j_grouping.md"),
            ("p2k_grp", "grp", "p2k_grouping.md"),
            ("p2l_grp", "grp", "p2l_grouping.md"),
            ("p2m_fix", "fix", "p2m_fix.md"),
            ("p2n_pal", "pal", "p2n_palette_REFUSED_dirty_repo.md"),
            ("p2n_pal2", "pal", "p2n_palette.md")):
        src = RUNS / run / task / "report.md"
        if not src.exists() and (RUNS / run).is_dir():
            found = sorted((RUNS / run).glob("*/report.md"))
            src = found[0] if len(found) == 1 else src
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
    for rel in ("Content/LD/L_LivingDiorama.umap", "Content/PCG/PCG_LD_Roads.uasset",
                "Content/LD/LS_Preview.uasset",
                "Content/LD/Materials/MI_LD_Ground.uasset",
                "Content/LD/Materials/MI_LD_Sidewalk.uasset",
                # authored in this pass: road paint and the procedural facade
                "Content/LD/Materials/M_LD_Paint.uasset",
                "Content/LD/Materials/MI_LD_Paint_White.uasset",
                "Content/LD/Materials/MI_LD_Paint_Yellow.uasset",
                "Content/LD/Materials/M_LD_Facade.uasset",
                "Content/LD/Materials/MI_LD_Facade_CHA.uasset",
                "Content/LD/Materials/MI_LD_Facade_NYA.uasset",
                "Content/LD/Materials/MI_LD_Facade_SFA.uasset",
                "Plugins/CitySamplePCG/CitySamplePCG.uplugin", "Plugins/Traffic/Traffic.uplugin"):
        src = proj / rel
        if src.exists():
            dst = up / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    for tool in sorted(WS.glob("tools_*.py")):
        shutil.copy2(tool, art / tool.name)
    for tool in ("build_master_p2.py", "FREE_DEPENDENCY_LOCK.json"):
        if (WS / tool).exists():
            shutil.copy2(WS / tool, art / tool)
    for tool in ("import_city_sample_subset.py", "update_pcg_ground.py", "probe_vehicle_mesh.py", "inspect_city_sample_fast.py",
                 # the SGD city: build, gate, street life, lighting, guarded save, probes
                 "step40_fullcity.py", "step41_streetlife_sgd.py", "step42_lighting_nosave.py",
                 "step43_sfd_height.py", "step44_city_gate.py", "step45_save_city.py",
                 "probe_render_truth.py", "probe_wall_inventory.py", "tools_look.py",
                 "verify_master_p2.py",
                 "sgd_orders_fullcity.json"):
        if (YF / "CACHE" / tool).exists():
            shutil.copy2(YF / "CACHE" / tool, art / tool)
    # The building-kit tests resolve their ground-truth probe as
    # ``Path(__file__).resolve().parents[2] / "asset_probe_v3.json"``
    # (ldyf/tests/test_building_kits.py:35-36).  In this staged tree the test
    # lives at artifacts/ldyf/tests/, so parents[2] is the artifacts root and
    # the probe has to land beside pytest.ini -- not at the repo root, which is
    # a different place from the archive reviewer's point of view.
    #
    # It used to be staged nowhere at all, so a fresh extraction of the MASTER
    # failed several building-kit tests with FileNotFoundError while the gate
    # plan promised the full suite green from that extraction.
    #
    # Copied unconditionally rather than behind an exists() guard: if the source
    # probe is missing, the build must fail loudly here instead of shipping an
    # archive whose tests cannot open their own ground truth.
    shutil.copy2(WS / "asset_probe_v3.json", art / "asset_probe_v3.json")
    # Same law for the grouping tests: test_sgd_grouping.py opens the real
    # layout at parents[2] / "city_layout.json" and its known-bad regression
    # fixture under ldyf/tests/data/. Neither was staged, so a fresh
    # extraction could not even COLLECT that test file. Unconditional, so a
    # missing input fails the build rather than the reviewer.
    shutil.copy2(WS / "city_layout.json", art / "city_layout.json")
    # ...and for test_building_styles.py, which opens these two at parents[2].
    # Sixteen tests failed from a fresh extraction for want of them.
    for name in ("pcg_building_kits.json", "pcg_building_rules.json"):
        shutil.copy2(WS / name, art / name)
    (art / "ldyf" / "tests" / "data").mkdir(exist_ok=True)
    data = sorted((WS / "ldyf" / "tests" / "data").glob("*"))
    if not data:
        raise SystemExit("ldyf/tests/data is empty: the grouping regression fixture is missing")
    for f in data:
        shutil.copy2(f, art / "ldyf" / "tests" / "data" / f.name)


def write_sha_manifest() -> None:
    """Write the manifest with LF endings so ``sha256sum -c`` can consume it.

    Written through the default text mode on Windows it came out CRLF, and the
    trailing CR became part of every filename: a reviewer on any POSIX box saw
    282 "No such file or directory" failures on an archive that was in fact
    intact. The bytes were never wrong; the manifest was simply unusable by the
    one tool a reviewer would reach for.
    """
    files = sorted(p for p in STAGE.rglob("*") if p.is_file())
    body = "\n".join(f"{sha256_file(p)}  {p.relative_to(STAGE).as_posix()}"
                     for p in files) + "\n"
    with open(STAGE / "identity" / "SHA256_MANIFEST.txt", "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(body)


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
