"""The Phase 16 local gate: engine story, pure plan, Blender structure, proof.

Plain Python -- never imports ``bpy``. Orchestrates the real engine and
Blender subprocesses to verify, end to end:

1. Blender 4.5.x LTS is available and refuses nothing silently.
2. The real three-episode proof story generates through the locked engine,
   and its Render Exports parse.
3. The production plan itself is valid PURE DATA: spec agreement, road-graph
   connectivity contract, and fabric placement rules all hold before any
   geometry exists.
4. The master scene plus production world build headlessly and every
   structural Blender test passes -- all Phase 15 tests unchanged, then the
   Phase 16 production contract.
5. The Phase 16 proof frames, the small-screen sheet, the manifest, and the
   production ``.blend`` render and save headlessly.
6. Nothing under the save chain or the export files changed one byte.
7. The manifest is plain UTF-8 JSON with no BOM.

Exit code is nonzero on any failure. Usage::

    python visual/blender/run_phase16_checks.py --workspace <fresh dir> \
        [--blender <blender.exe>] [--preview]
"""

import argparse
import hashlib
import importlib.util
import sys
from pathlib import Path

BLENDER_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = BLENDER_DIR / "scripts"
TESTS_DIR = BLENDER_DIR / "tests"
SPEC_PATH = BLENDER_DIR / "config" / "master_scene_v1.json"
PRODUCTION_PATH = BLENDER_DIR / "config" / "production_world_v1.json"
PROOF_TOOLS_DIR = BLENDER_DIR.parent.parent / "tools" / "phase15_proof"

sys.path.insert(0, str(PROOF_TOOLS_DIR))

REQUIRED_FRAMES = (
    "phase16_before_expansion_reference.png",
    "phase16_before_composition_reference.png",
    "phase16_world_hero.png",
    "phase16_system_view.png",
    "phase16_city_composition_verify.png",
    "phase16_historic_core_context.png",
    "phase16_scar_context.png",
    "phase16_road_network_verify.png",
    "phase16_density_verify.png",
    "phase16_spatial_validity_verify.png",
    "phase16_urbanization_verify.png",
    "phase16_clean_roads_verify.png",
    "phase16_small_screen_sheet.png",
    "phase16_composition_comparison.png",
)


def _load_phase15_gate():
    """Import the Phase 15 gate module for its Blender-resolution helpers.

    The resolution contract (--blender, then BLENDER_EXECUTABLE, then PATH)
    is Phase 15 canon; reusing the same functions keeps one single source of
    truth for how a Blender executable may be located.
    """
    spec = importlib.util.spec_from_file_location(
        "phase15_checks_for_p16", BLENDER_DIR / "run_phase15_checks.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["phase15_checks_for_p16"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules["phase15_checks_for_p16"]
    return module


def _validate_pure_plan() -> dict:
    """Run the whole pure Phase 16 pipeline and return its summaries."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from production_spec import (
            load_production_world_spec,
            require_production_agreement,
        )
        from road_graph import build_road_graph, graph_summary
        from scene_spec import load_master_scene_spec
        from urban_fabric import fabric_totals, plan_urban_fabric, validate_urban_fabric

        master_spec = load_master_scene_spec(SPEC_PATH)
        production_spec = load_production_world_spec(PRODUCTION_PATH)
        require_production_agreement(master_spec, production_spec)
        graph = build_road_graph(master_spec, production_spec)
        plan = plan_urban_fabric(master_spec, production_spec, graph)
        errors = validate_urban_fabric(plan, master_spec, production_spec, graph)
        if errors:
            raise RuntimeError("fabric plan violations:\n- " + "\n- ".join(errors))
        return {
            "streets": graph_summary(graph),
            "fabric": fabric_totals(plan),
            "spatial": plan["spatial"],
            "ground": plan["ground"]["summary"],
        }
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


def main(argv: list[str] | None = None) -> int:
    """Run the complete Phase 16 local verification gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="fresh output directory")
    parser.add_argument("--blender", default=None)
    parser.add_argument("--preview", action="store_true", help="fast low-quality renders")
    arguments = parser.parse_args(argv)
    if not arguments.workspace.strip():
        print("phase 16 checks failed: --workspace must not be empty", file=sys.stderr)
        return 1
    workspace = Path(arguments.workspace)

    try:
        gate = _load_phase15_gate()
        blender = gate.locate_blender(arguments.blender)
        blender_version = gate.require_blender_45(blender)
        print(f"[1/7] {blender_version} at {blender}")

        from generate_proof_exports import generate

        summary = generate(workspace)
        walls = summary["after_walls"]
        if not isinstance(walls, list) or len(walls) != 1:
            raise RuntimeError("proof story did not produce exactly one engine-built wall")
        print("[2/7] proof story generated: one engine-built wall, law restored")

        plan_summary = _validate_pure_plan()
        streets = plan_summary["streets"]
        fabric = plan_summary["fabric"]
        spatial = plan_summary["spatial"]
        collisions = sum(
            value
            for key, value in spatial.items()
            if key.endswith(("collisions", "overlaps", "violations"))
        )
        if collisions:
            raise RuntimeError(f"spatial contract violated: {collisions} collisions")
        ground = plan_summary["ground"]
        print(
            f"[3/7] pure plan valid: {streets['production_segments']} production "
            f"streets, {fabric['lots']} lots ({fabric['midrise_masses']} mid-rise "
            f"masses), {fabric['production_trees']} new trees, "
            f"{fabric['legacy_clusters_kept']} groves preserved / "
            f"{fabric['legacy_clusters_removed']} cleared, 0 spatial collisions "
            f"across {spatial['audited_objects']} audited objects"
        )
        print(
            f"      composition: {ground['plate_panels']} plate panels, "
            f"{ground['ground_cells']} ground cells, "
            f"{ground['buried_ring_arcs']} ring arcs buried / "
            f"{ground['kept_ring_arcs']} kept, worst rim exposure "
            f"{ground['worst_rim_exposure_deg']:.1f} degrees"
        )

        save_root = workspace / "saves"
        before_export = workspace / "render_export_before.json"
        after_export = workspace / "render_export_after.json"
        saves_before = gate.tree_hashes(save_root)
        exports_before = (
            hashlib.sha256(before_export.read_bytes()).hexdigest(),
            hashlib.sha256(after_export.read_bytes()).hexdigest(),
        )

        blender_workdir = workspace / "blender_work"
        blender_workdir.mkdir(exist_ok=True)
        gate.run_blender(
            blender,
            TESTS_DIR / "run_blender_tests_p16.py",
            [
                "--spec",
                str(SPEC_PATH),
                "--production",
                str(PRODUCTION_PATH),
                "--before",
                str(before_export),
                "--after",
                str(after_export),
                "--workdir",
                str(blender_workdir),
            ],
        )
        print("[4/7] Blender structural tests passed (Phase 15 suite + production world)")

        proof_dir = workspace / "production_proof"
        blend_path = proof_dir / "living_diorama_phase16_production_world.blend"
        proof_args = [
            "--spec",
            str(SPEC_PATH),
            "--production",
            str(PRODUCTION_PATH),
            "--export",
            str(after_export),
            "--outdir",
            str(proof_dir),
            "--blend",
            str(blend_path),
        ]
        if arguments.preview:
            proof_args.append("--preview")
        gate.run_blender(blender, SCRIPTS_DIR / "produce_production_world_proof.py", proof_args)
        for name in REQUIRED_FRAMES:
            frame = proof_dir / name
            if not frame.exists() or frame.stat().st_size == 0:
                raise RuntimeError(f"proof frame missing or empty: {name}")
        if not blend_path.exists():
            raise RuntimeError("the production .blend was not saved")
        print("[5/7] production proof frames, sheet, and .blend produced")

        saves_after = gate.tree_hashes(save_root)
        exports_after = (
            hashlib.sha256(before_export.read_bytes()).hexdigest(),
            hashlib.sha256(after_export.read_bytes()).hexdigest(),
        )
        if saves_before != saves_after:
            raise RuntimeError("the save chain changed during Blender generation")
        if exports_before != exports_after:
            raise RuntimeError("a render export changed during Blender generation")
        print("[6/7] read-only guarantee holds: saves and exports untouched")

        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            from manifest_io import require_clean_utf8_json

            manifest = require_clean_utf8_json(proof_dir / "phase16_production_world_manifest.json")
        finally:
            sys.path.remove(str(SCRIPTS_DIR))
        if manifest.get("artifact") != "living_diorama_phase16_production_world_proof":
            raise RuntimeError("the manifest does not identify the Phase 16 proof artifact")
        print("[7/7] manifest verified: plain UTF-8 JSON, no BOM")
    except Exception as error:  # noqa: BLE001 - the gate reports, then fails loudly
        print(f"phase 16 checks failed: {error}", file=sys.stderr)
        return 1
    print("PHASE 16 LOCAL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
