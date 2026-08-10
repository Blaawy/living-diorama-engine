"""The Phase 18 local gate: engine story, pure plan, structure, presence proof.

Plain Python -- never imports ``bpy``. Orchestrates the real engine and Blender
subprocesses to verify, end to end:

1. Blender 4.5.x LTS is available and refuses nothing silently.
2. The real three-episode story generates through the LOCKED engine, so the
   populations Phase 18 renders are the ones the simulation actually holds.
3. The pedestrian topology and the presence plan are valid PURE DATA before any
   Blender exists: every candidate is clear of the city, the plan re-derives
   identically, the visible counts follow from authoritative population, a
   district emptied of residents shows nobody, and a district that grows keeps
   the people already standing in it exactly where they were.
4. Every structural Blender test passes, in phase order -- the LOCKED Phase 15
   suite, the LOCKED Phase 16 suite, the LOCKED Phase 17 suite, then Phase 18.
5. The presence proof pack renders: the same camera before and after the layer
   exists, the context frames, the validity frame, the contact sheet, the
   manifest, and the ``.blend``.
6. Nothing under the save chain or the export files changed one byte.
7. The manifest is plain UTF-8 JSON with no BOM, and its own recorded verdict
   is true: the proxies in the scene are the proxies the plan declares, and no
   duplicate-named datablock appeared.
8. The proof package inventories itself completely -- every member enumerated
   with size and SHA-256, nothing missing, nothing unenumerated, and no
   manifest pointing at an artifact the package does not carry.

Exit code is nonzero on any failure. Usage::

    python visual/blender/run_phase18_checks.py --workspace <fresh dir> \
        [--blender <blender.exe>] [--preview] [--base-sha <sha>]
"""

import argparse
import copy
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

BLENDER_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = BLENDER_DIR / "scripts"
TESTS_DIR = BLENDER_DIR / "tests"
CONFIG_DIR = BLENDER_DIR / "config"
SPEC_PATH = CONFIG_DIR / "master_scene_v1.json"
PRODUCTION_PATH = CONFIG_DIR / "production_world_v1.json"
MOTION_PATH = CONFIG_DIR / "motion_time_v1.json"
PRESENCE_PATH = CONFIG_DIR / "population_presence_v1.json"
STORY_TOOLS_DIR = BLENDER_DIR.parent.parent / "tools" / "phase17_motion"

sys.path.insert(0, str(STORY_TOOLS_DIR))

EXPORT_NAMES = ("render_export_before.json", "render_export_mid.json", "render_export_after.json")

STRUCTURAL_RESULTS = "phase18_structural_results.txt"

PRESENCE_BLEND = "living_diorama_phase18_population_presence.blend"

STRUCTURAL_PHASES = ("PHASE15", "PHASE16", "PHASE17", "PHASE18")

REQUIRED_MEMBERS = (
    STRUCTURAL_RESULTS,
    PRESENCE_BLEND,
    "phase18_world_before_population_reference.png",
    "phase18_world_with_population.png",
    "phase18_quarter_before_population_reference.png",
    "phase18_quarter_with_population.png",
    "phase18_population_street_context.png",
    "phase18_population_plaza_context.png",
    "phase18_population_civic_context.png",
    "phase18_population_park_context.png",
    "phase18_population_group_context.png",
    "phase18_population_human_style_verify.png",
    "phase18_population_face_verify.png",
    "phase18_population_body_geometry_verify.png",
    "phase18_population_silhouette_verify.png",
    "phase18_population_validity_verify.png",
    "phase18_population_contact_sheet.png",
    "population_presence_manifest.json",
    EXPORT_NAMES[0],
)
"""Every member a Phase 18 proof package must carry.

The render export is one of them. It is the authoritative input the entire
population claim rests on, so a reviewer has to be able to recompute the plan
from what was delivered rather than take the manifest's word for a file that
lives somewhere else."""


def _run_blender_capturing(blender: Path, script: Path, script_args: list[str]) -> str:
    """Run one headless Blender script and RETURN its output.

    The structural suite's per-phase pass counts are evidence the proof
    package has to carry, so they are kept rather than discarded on success.
    """
    completed = subprocess.run(
        [
            str(blender),
            "--background",
            "--factory-startup",
            "--python",
            str(script),
            "--",
            *script_args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout[-6000:])
        sys.stderr.write(completed.stderr[-6000:])
        raise RuntimeError(f"Blender step failed: {script.name}")
    return completed.stdout


def _structural_summary(output: str) -> dict[str, dict[str, int]]:
    """Parse the per-phase pass/fail counts the structural runner prints.

    Raises:
        RuntimeError: If a phase is missing or anything failed.
    """
    counts: dict[str, dict[str, int]] = {}
    for phase in (*STRUCTURAL_PHASES, "P18"):
        match = re.search(
            rf"^LD_BLENDER_TESTS_{phase}: (\d+) passed, (\d+) failed$", output, re.MULTILINE
        )
        if match is None:
            raise RuntimeError(f"the structural runner reported no result for {phase}")
        counts[phase] = {"passed": int(match.group(1)), "failed": int(match.group(2))}
        if counts[phase]["failed"]:
            raise RuntimeError(f"{phase} structural tests failed: {counts[phase]}")
    total = sum(counts[phase]["passed"] for phase in STRUCTURAL_PHASES)
    if total != counts["P18"]["passed"]:
        raise RuntimeError(
            f"structural phase counts {total} disagree with the total {counts['P18']['passed']}"
        )
    return counts


def _write_structural_results(path: Path, output: str) -> None:
    """Keep the structural suite's own per-test lines as a package member."""
    kept = [
        line
        for line in output.splitlines()
        if line.startswith(("ok   ", "FAIL ", "LD_BLENDER_TESTS_"))
    ]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")


def _load_phase15_gate():
    """Import the Phase 15 gate module for its Blender-resolution helpers.

    The resolution contract (--blender, then BLENDER_EXECUTABLE, then PATH) is
    Phase 15 canon; reusing the same functions keeps one single source of truth
    for how a Blender executable may be located.
    """
    spec = importlib.util.spec_from_file_location(
        "phase15_checks_for_p18", BLENDER_DIR / "run_phase15_checks.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["phase15_checks_for_p18"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules["phase15_checks_for_p18"]
    return module


def _with_populations(export: dict, populations: dict[str, int]) -> dict:
    """A copy of one export with some district populations replaced.

    A clearly-labelled COUNTERFACTUAL. The real story holds population
    constant across all three episodes, so the only honest way to interrogate
    the growth and emptiness contracts is to state the alternative explicitly
    and never render it.
    """
    changed = copy.deepcopy(export)
    for district in changed["world"]["districts"]:
        if district["id"] in populations:
            district["population"] = populations[district["id"]]
    return changed


def _validate_pure_presence(workspace: Path) -> dict:
    """Derive and interrogate the whole presence layer with no Blender in sight."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import pedestrian_topology as topology
        import population_presence_plan as presence
        from population_presence_spec import load_population_presence_spec, visible_proxy_count
        from production_spec import load_production_world_spec
        from road_graph import build_road_graph
        from scene_spec import load_master_scene_spec, load_render_export
        from urban_fabric import plan_urban_fabric

        master_spec = load_master_scene_spec(SPEC_PATH)
        production = load_production_world_spec(PRODUCTION_PATH)
        presence_spec = load_population_presence_spec(PRESENCE_PATH)
        graph = build_road_graph(master_spec, production)
        fabric = plan_urban_fabric(master_spec, production, graph)

        plan_topology = topology.plan_pedestrian_topology(
            master_spec, production, graph, fabric, presence_spec
        )
        errors = topology.validate_pedestrian_topology(
            plan_topology, master_spec, production, graph, fabric
        )
        if errors:
            raise RuntimeError("the pedestrian topology is invalid:\n- " + "\n- ".join(errors[:10]))
        repeat = topology.plan_pedestrian_topology(
            master_spec, production, graph, fabric, presence_spec
        )
        if repeat != plan_topology:
            raise RuntimeError("the same world produced two different pedestrian topologies")

        export = load_render_export(workspace / EXPORT_NAMES[0])
        plan = presence.plan_population_presence(export, master_spec, presence_spec, plan_topology)
        again = presence.plan_population_presence(export, master_spec, presence_spec, plan_topology)
        if presence.plan_hash(plan) != presence.plan_hash(again):
            raise RuntimeError("the same inputs produced two different presence plans")
        plan_errors = presence.validate_population_presence_plan(
            plan, export, master_spec, presence_spec, plan_topology
        )
        if plan_errors:
            raise RuntimeError("the presence plan is invalid:\n- " + "\n- ".join(plan_errors[:10]))
        if not plan["proxies"]:
            raise RuntimeError("the authoritative populations produced nobody at all")

        for district_id, entry in sorted(plan["districts"].items()):
            earned = visible_proxy_count(entry["population"], presence_spec)
            if entry["earned_proxies"] != earned:
                raise RuntimeError(
                    f"{district_id} claims {entry['earned_proxies']} proxies, the declared "
                    f"mapping gives {earned}"
                )

        emptied = _with_populations(export, {"district_b": 0})
        empty_plan = presence.plan_population_presence(
            emptied, master_spec, presence_spec, plan_topology
        )
        if empty_plan["districts"]["district_b"]["active_proxies"]:
            raise RuntimeError("a district with no residents still showed people")

        grown = _with_populations(export, {"district_a": 320})
        grown_plan = presence.plan_population_presence(
            grown, master_spec, presence_spec, plan_topology
        )
        before = [p for p in plan["proxies"] if p["district"] == "district_a"]
        after = [p for p in grown_plan["proxies"] if p["district"] == "district_a"]
        if len(after) <= len(before):
            raise RuntimeError("a larger population produced no additional presence")
        if after[: len(before)] != before:
            raise RuntimeError("growth reshuffled the people who were already standing there")

        return {
            "plan_hash": presence.plan_hash(plan),
            "topology_hash": topology.topology_hash(plan_topology),
            "active_proxies": plan["summary"]["active_proxies"],
            "by_zone": plan["summary"]["proxies_by_zone"],
            "by_district": plan["summary"]["proxies_by_district"],
            "topology": plan_topology["summary"],
            "refusals": plan_topology["refused"],
            "growth": {"before": len(before), "after": len(after)},
        }
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


def _population_package():
    """Import the pure Phase 18 proof-package contract module."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import population_proof_package

        return population_proof_package
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


def _require_clean_manifest(path: Path) -> dict:
    """Load one manifest through the project's strict encoding guard."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from manifest_io import require_clean_utf8_json

        return require_clean_utf8_json(path)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


def main(argv: list[str] | None = None) -> int:
    """Run the complete Phase 18 local verification gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="fresh output directory")
    parser.add_argument("--blender", default=None)
    parser.add_argument("--preview", action="store_true", help="fast low-quality renders")
    parser.add_argument("--base-sha", default="", help="canonical commit this candidate targets")
    arguments = parser.parse_args(argv)
    if not arguments.workspace.strip():
        print("phase 18 checks failed: --workspace must not be empty", file=sys.stderr)
        return 1
    workspace = Path(arguments.workspace)

    try:
        gate = _load_phase15_gate()
        blender = gate.locate_blender(arguments.blender)
        blender_version = gate.require_blender_45(blender)
        print(f"[1/8] {blender_version} at {blender}")

        from generate_motion_story import generate_motion_story

        generate_motion_story(workspace)
        print("[2/8] real engine story generated; populations come from the simulation")

        presence = _validate_pure_presence(workspace)
        print(
            f"      {presence['active_proxies']} proxies from "
            f"{presence['topology']['candidates_tested']} tested candidates "
            f"({presence['topology']['candidates_refused']} refused)"
        )
        print(f"      by zone: {presence['by_zone']}")
        print(
            f"      growth fixture: district_a {presence['growth']['before']} -> "
            f"{presence['growth']['after']} proxies, prefix unchanged"
        )
        print("[3/8] topology and presence plan valid, deterministic, and truthful")

        exports = {name: workspace / name for name in EXPORT_NAMES}
        save_root = workspace / "saves"
        saves_before = gate.tree_hashes(save_root)
        exports_before = {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in exports.items()
        }

        blender_workdir = workspace / "blender_work"
        blender_workdir.mkdir(parents=True, exist_ok=True)
        proof_dir = workspace / "population_proof"
        proof_dir.mkdir(parents=True, exist_ok=True)
        structural_output = _run_blender_capturing(
            blender,
            TESTS_DIR / "run_blender_tests_p18.py",
            [
                "--spec",
                str(SPEC_PATH),
                "--production",
                str(PRODUCTION_PATH),
                "--motion",
                str(MOTION_PATH),
                "--presence",
                str(PRESENCE_PATH),
                "--before",
                str(exports[EXPORT_NAMES[0]]),
                "--mid",
                str(exports[EXPORT_NAMES[1]]),
                "--after",
                str(exports[EXPORT_NAMES[2]]),
                "--workdir",
                str(blender_workdir),
            ],
        )
        structural = _structural_summary(structural_output)
        _write_structural_results(proof_dir / STRUCTURAL_RESULTS, structural_output)
        print(
            f"[4/8] structural tests passed in phase order: "
            f"Phase 15 {structural['PHASE15']['passed']}, "
            f"Phase 16 {structural['PHASE16']['passed']}, "
            f"Phase 17 {structural['PHASE17']['passed']}, "
            f"Phase 18 {structural['PHASE18']['passed']} "
            f"({structural['P18']['passed']} total)"
        )

        blend_path = proof_dir / PRESENCE_BLEND
        gate.run_blender(
            blender,
            SCRIPTS_DIR / "produce_population_presence_proof.py",
            [
                "--spec",
                str(SPEC_PATH),
                "--production",
                str(PRODUCTION_PATH),
                "--presence",
                str(PRESENCE_PATH),
                "--export",
                str(exports[EXPORT_NAMES[0]]),
                "--outdir",
                str(proof_dir),
                "--blend",
                str(blend_path),
                "--base-sha",
                arguments.base_sha,
                *(["--preview"] if arguments.preview else []),
            ],
        )
        gate.run_blender(
            blender,
            SCRIPTS_DIR / "produce_population_style_plate.py",
            [
                "--presence",
                str(PRESENCE_PATH),
                "--output",
                str(proof_dir / "phase18_population_human_style_verify.png"),
                "--face-output",
                str(proof_dir / "phase18_population_face_verify.png"),
                "--body-output",
                str(proof_dir / "phase18_population_body_geometry_verify.png"),
                "--silhouette-output",
                str(proof_dir / "phase18_population_silhouette_verify.png"),
                *(["--preview"] if arguments.preview else []),
            ],
        )
        print(
            "[5/8] presence proof rendered, plus four QA plates: the same camera before "
            "and after the layer exists, the whole figure vocabulary side by side, every "
            "face at one height, every body at full length, and the silhouette test"
        )

        if gate.tree_hashes(save_root) != saves_before:
            raise RuntimeError("the save chain changed during verification")
        for name, digest in exports_before.items():
            if hashlib.sha256(exports[name].read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"{name} changed during verification")
        print("[6/8] the engine's saves and exports are byte-identical")

        manifest = _require_clean_manifest(proof_dir / "population_presence_manifest.json")
        if manifest["topology"]["hash"] != presence["topology_hash"]:
            raise RuntimeError(
                "Blender derived a different pedestrian topology than the host did: "
                f"{manifest['topology']['hash']} vs {presence['topology_hash']}"
            )
        if manifest["plan_hash"] != presence["plan_hash"]:
            raise RuntimeError(
                "the rendered plan is not the plan the pure planner derived: "
                f"{manifest['plan_hash']} vs {presence['plan_hash']}"
            )
        scene = manifest["scene_population"]
        if scene["proxy_objects"] != presence["active_proxies"]:
            raise RuntimeError(
                f"the scene holds {scene['proxy_objects']} proxies, the plan declares "
                f"{presence['active_proxies']}"
            )
        if scene["duplicate_named_objects"]:
            raise RuntimeError("the population layer produced duplicate-named datablocks")
        if scene["linked_elsewhere"]:
            raise RuntimeError("a proxy is linked outside its own collection")
        diversity = manifest["figure_diversity"]
        if diversity["distinct_bodies"] != scene["proxy_objects"]:
            raise RuntimeError(
                f"{scene['proxy_objects']} people share only "
                f"{diversity['distinct_bodies']} distinct bodies"
            )
        if set(diversity["by_axis"]["age_presentation"]) != {"child", "teen", "adult", "elder"}:
            raise RuntimeError(
                "the city does not contain every age presentation: "
                f"{sorted(diversity['by_axis']['age_presentation'])}"
            )
        if diversity["tallest"] - diversity["shortest"] < 0.5:
            raise RuntimeError(
                "every visible person is nearly the same height "
                f"({diversity['shortest']} to {diversity['tallest']})"
            )
        reference = [entry for entry in manifest["renders"] if not entry["population"]]
        populated = [entry for entry in manifest["renders"] if entry["population"]]
        if len(reference) < 2 or not populated:
            raise RuntimeError("the proof lacks its before/after comparison pairs")
        populated_cameras = {entry["camera"] for entry in populated}
        for entry in reference:
            if entry["camera"] not in populated_cameras:
                raise RuntimeError(
                    f"{entry['file']} was rendered from {entry['camera']} but no populated "
                    "frame uses that camera; a before/after pair must be ONE camera twice"
                )
        for entry in reference:
            twin = next(
                item
                for item in populated
                if item["camera"] == entry["camera"] and item["file"] != entry["file"]
            )
            before = hashlib.sha256((proof_dir / entry["file"]).read_bytes()).hexdigest()
            after = hashlib.sha256((proof_dir / twin["file"]).read_bytes()).hexdigest()
            if before == after:
                raise RuntimeError(
                    f"{entry['file']} and {twin['file']} are byte-identical; the population "
                    "layer changed nothing a reviewer could see"
                )
        print(
            f"      before/after pairs differ from {sorted(entry['camera'] for entry in reference)}"
        )
        print(
            f"[7/8] manifest verdict true: {scene['proxy_objects']} proxies, "
            f"{diversity['distinct_bodies']} distinct bodies, "
            f"{diversity['shortest']}m to {diversity['tallest']}m, plan hash matches"
        )

        package = _population_package()
        package.write_population_inventory(proof_dir)
        inventory = package.verify_population_inventory(proof_dir, required=REQUIRED_MEMBERS)
        print(
            f"[8/8] proof package inventory verified: {inventory['member_count']} members, "
            f"{inventory['total_bytes']} bytes, "
            f"{len(inventory['artifact_references'])} artifact reference(s) resolved"
        )
        (workspace / "phase18_gate_summary.json").write_text(
            json.dumps(
                {
                    "presence": presence,
                    "structural": structural,
                    "package": inventory,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except Exception as error:  # noqa: BLE001 - the gate reports, then fails loudly
        print(f"phase 18 checks failed: {error}", file=sys.stderr)
        return 1
    print("PHASE 18 LOCAL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
