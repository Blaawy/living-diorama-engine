"""The Phase 17 local gate: engine story, pure plan, structure, motion proof.

Plain Python -- never imports ``bpy``. Orchestrates the real engine and
Blender subprocesses to verify, end to end:

1. Blender 4.5.x LTS is available and refuses nothing silently.
2. The real three-episode story generates through the LOCKED engine, and both
   of its transitions parse: episode 0 -> 1 (the law is suspended and the wall
   rises) and episode 1 -> 2 (the law returns and the wall remains).
3. Both MotionPlans are valid PURE DATA before any Blender exists: they are
   deterministic, order-independent, minimal, and the persistence leg emits no
   wall directive at all.
4. Every structural Blender test passes, in phase order -- the LOCKED Phase 15
   suite, then the LOCKED Phase 16 suite, then the Phase 17 motion suite.
5. The persistence proof and the transition proof pack render, along with the
   contact sheet, the semantic verification frame, the manifests, and BOTH
   animated ``.blend`` files -- every artifact any manifest names is packaged.
6. Nothing under the save chain or the export files changed one byte.
7. Both manifests are plain UTF-8 JSON with no BOM and their own recorded
   verdicts are true: objects AND materials equivalent at both endpoints, at
   least one material channel actually animated so the check is not vacuous,
   and a city that never moved.
8. The proof package inventories itself completely -- every member enumerated
   with size and SHA-256, nothing missing, nothing unenumerated, and no
   manifest pointing at an artifact the package does not carry.

Exit code is nonzero on any failure. Usage::

    python visual/blender/run_phase17_checks.py --workspace <fresh dir> \
        [--blender <blender.exe>] [--preview] [--base-sha <sha>]
"""

import argparse
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
STORY_TOOLS_DIR = BLENDER_DIR.parent.parent / "tools" / "phase17_motion"

sys.path.insert(0, str(STORY_TOOLS_DIR))

EXPORT_NAMES = ("render_export_before.json", "render_export_mid.json", "render_export_after.json")

STRUCTURAL_RESULTS = "phase17_structural_results.txt"

PERSISTENCE_BLEND = "phase17_persistence_motion_time.blend"

TRANSITION_BLEND = "living_diorama_phase17_motion_time.blend"

STRUCTURAL_PHASES = ("PHASE15", "PHASE16", "PHASE17")

REQUIRED_MEMBERS = (
    STRUCTURAL_RESULTS,
    PERSISTENCE_BLEND,
    TRANSITION_BLEND,
    "phase17_start.png",
    "phase17_transition_25.png",
    "phase17_transition_50.png",
    "phase17_transition_75.png",
    "phase17_end.png",
    "phase17_world_start.png",
    "phase17_world_end.png",
    "phase17_motion_contact_sheet.png",
    "phase17_semantic_motion_verify.png",
    "phase17_persistence_start.png",
    "phase17_persistence_end.png",
    "motion_manifest.json",
    "motion_persistence_manifest.json",
)


def _run_blender_capturing(blender: Path, script: Path, script_args: list[str]) -> str:
    """Run one headless Blender script and RETURN its output.

    The locked Phase 15 helper surfaces Blender's output only on failure,
    which is right for a build step but not for the structural suite: its
    per-phase pass counts are evidence the proof package has to carry, so
    Phase 17 keeps them instead of discarding them on success.
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
    for phase in (*STRUCTURAL_PHASES, "P17"):
        match = re.search(
            rf"^LD_BLENDER_TESTS_{phase}: (\d+) passed, (\d+) failed$", output, re.MULTILINE
        )
        if match is None:
            raise RuntimeError(f"the structural runner reported no result for {phase}")
        counts[phase] = {"passed": int(match.group(1)), "failed": int(match.group(2))}
        if counts[phase]["failed"]:
            raise RuntimeError(f"{phase} structural tests failed: {counts[phase]}")
    total = sum(counts[phase]["passed"] for phase in STRUCTURAL_PHASES)
    if total != counts["P17"]["passed"]:
        raise RuntimeError(
            f"structural phase counts {total} disagree with the total {counts['P17']['passed']}"
        )
    return counts


def _write_structural_results(path: Path, output: str) -> None:
    """Keep the structural suite's own per-test lines as a package member.

    Evidence the reviewer can read without re-running Blender: one line per
    structural test, in execution order, followed by the per-phase totals.
    """
    kept = [
        line
        for line in output.splitlines()
        if line.startswith(("ok   ", "FAIL ", "LD_BLENDER_TESTS_"))
    ]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")


def _load_phase15_gate():
    """Import the Phase 15 gate module for its Blender-resolution helpers.

    The resolution contract (--blender, then BLENDER_EXECUTABLE, then PATH) is
    Phase 15 canon; reusing the same functions keeps one single source of
    truth for how a Blender executable may be located.
    """
    spec = importlib.util.spec_from_file_location(
        "phase15_checks_for_p17", BLENDER_DIR / "run_phase15_checks.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["phase15_checks_for_p17"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules["phase15_checks_for_p17"]
    return module


def _validate_pure_plans(workspace: Path) -> dict:
    """Derive and interrogate both MotionPlans with no Blender in sight."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        from motion_plan import describe, plan_hash, plan_motion
        from motion_time_spec import load_motion_time_spec
        from scene_spec import load_master_scene_spec, load_render_export

        master_spec = load_master_scene_spec(SPEC_PATH)
        motion_spec = load_motion_time_spec(MOTION_PATH)
        exports = {name: load_render_export(workspace / name) for name in EXPORT_NAMES}
        legs = {
            "transition": (EXPORT_NAMES[0], EXPORT_NAMES[1]),
            "persistence": (EXPORT_NAMES[1], EXPORT_NAMES[2]),
        }
        summaries: dict[str, dict] = {}
        for leg, (before, after) in legs.items():
            plan = plan_motion(exports[before], exports[after], master_spec, motion_spec)
            repeat = plan_motion(exports[before], exports[after], master_spec, motion_spec)
            if plan_hash(plan) != plan_hash(repeat):
                raise RuntimeError(f"{leg}: the same inputs produced two different plans")
            if not plan["directives"]:
                raise RuntimeError(f"{leg}: the two exports describe no visual change")
            summaries[leg] = {
                "hash": plan_hash(plan),
                "summary": plan["summary"],
                "description": describe(plan),
            }
        if "wall_presence" not in summaries["transition"]["summary"]["by_channel"]:
            raise RuntimeError("the transition leg must raise the engine-built wall")
        if "wall_presence" in summaries["persistence"]["summary"]["by_channel"]:
            raise RuntimeError(
                "the persistence leg must leave the standing wall completely untouched"
            )
        if summaries["persistence"]["summary"]["by_channel"].get("law_seal_glow") != 1:
            raise RuntimeError("the persistence leg must show the law returning")
        return summaries
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


def _proof_package():
    """Import the pure proof-package contract module."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import proof_package

        return proof_package
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
    """Run the complete Phase 17 local verification gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="fresh output directory")
    parser.add_argument("--blender", default=None)
    parser.add_argument("--preview", action="store_true", help="fast low-quality renders")
    parser.add_argument("--base-sha", default="", help="canonical commit this candidate targets")
    arguments = parser.parse_args(argv)
    if not arguments.workspace.strip():
        print("phase 17 checks failed: --workspace must not be empty", file=sys.stderr)
        return 1
    workspace = Path(arguments.workspace)

    try:
        gate = _load_phase15_gate()
        blender = gate.locate_blender(arguments.blender)
        blender_version = gate.require_blender_45(blender)
        print(f"[1/8] {blender_version} at {blender}")

        from generate_motion_story import generate_motion_story

        story = generate_motion_story(workspace)
        first = story["legs"]["leg1_law_suspended_wall_rises"]["changed"]
        second = story["legs"]["leg2_law_restored_wall_remains"]["changed"]
        if "walls" not in first:
            raise RuntimeError("the engine story did not build the wall in leg 1")
        if "walls" in second:
            raise RuntimeError("the engine story lost the wall in leg 2")
        print(
            "[2/8] real engine story generated: the law is suspended and the wall "
            "rises, then the law returns and the wall remains"
        )

        plans = _validate_pure_plans(workspace)
        for leg, entry in sorted(plans.items()):
            print(f"      {leg}: {entry['description']}")
        print("[3/8] both MotionPlans valid, deterministic, and minimal")

        exports = {name: workspace / name for name in EXPORT_NAMES}
        save_root = workspace / "saves"
        saves_before = gate.tree_hashes(save_root)
        exports_before = {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in exports.items()
        }

        blender_workdir = workspace / "blender_work"
        blender_workdir.mkdir(parents=True, exist_ok=True)
        proof_dir = workspace / "motion_proof"
        proof_dir.mkdir(parents=True, exist_ok=True)
        structural_output = _run_blender_capturing(
            blender,
            TESTS_DIR / "run_blender_tests_p17.py",
            [
                "--spec",
                str(SPEC_PATH),
                "--production",
                str(PRODUCTION_PATH),
                "--motion",
                str(MOTION_PATH),
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
            f"Phase 17 {structural['PHASE17']['passed']} "
            f"({structural['P17']['passed']} total)"
        )

        blend_path = proof_dir / TRANSITION_BLEND
        common = [
            "--spec",
            str(SPEC_PATH),
            "--production",
            str(PRODUCTION_PATH),
            "--motion",
            str(MOTION_PATH),
            "--base-sha",
            arguments.base_sha,
        ]
        preview = ["--preview"] if arguments.preview else []
        gate.run_blender(
            blender,
            SCRIPTS_DIR / "produce_motion_proof.py",
            [
                *common,
                "--profile",
                "persistence",
                "--label",
                "phase17_persistence",
                "--before",
                str(exports[EXPORT_NAMES[1]]),
                "--after",
                str(exports[EXPORT_NAMES[2]]),
                "--outdir",
                str(proof_dir),
                "--blend",
                str(proof_dir / PERSISTENCE_BLEND),
                *preview,
            ],
        )
        gate.run_blender(
            blender,
            SCRIPTS_DIR / "produce_motion_proof.py",
            [
                *common,
                "--profile",
                "transition",
                "--label",
                "phase17",
                "--before",
                str(exports[EXPORT_NAMES[0]]),
                "--after",
                str(exports[EXPORT_NAMES[1]]),
                "--outdir",
                str(proof_dir),
                "--blend",
                str(blend_path),
                *preview,
            ],
        )
        for name in REQUIRED_MEMBERS:
            member = proof_dir / name
            if not member.exists() or member.stat().st_size == 0:
                raise RuntimeError(f"proof member missing or empty: {name}")
        print(
            "[5/8] motion proof frames, contact sheet, manifests, and both animated "
            ".blend files produced"
        )

        saves_after = gate.tree_hashes(save_root)
        exports_after = {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in exports.items()
        }
        if saves_before != saves_after:
            raise RuntimeError("the save chain changed during Blender generation")
        if exports_before != exports_after:
            raise RuntimeError("a render export changed during Blender generation")
        print("[6/8] read-only guarantee holds: saves and exports untouched")

        manifest = _require_clean_manifest(proof_dir / "motion_manifest.json")
        if manifest.get("artifact") != "living_diorama_phase17_motion_time_proof":
            raise RuntimeError("the manifest does not identify the Phase 17 proof artifact")
        if manifest["motion_plan"]["sha256"] != plans["transition"]["hash"]:
            raise RuntimeError("the rendered plan is not the plan this gate validated")
        persistence = _require_clean_manifest(proof_dir / "motion_persistence_manifest.json")
        for label, document in (("transition", manifest), ("persistence", persistence)):
            for which, endpoint in sorted(document["endpoint_equivalence"].items()):
                for field in ("objects_equivalent", "materials_equivalent", "equivalent"):
                    if not endpoint.get(field):
                        raise RuntimeError(
                            f"{label} {which} endpoint fails {field}: "
                            f"objects={endpoint.get('objects_equivalent')}, "
                            f"materials={endpoint.get('materials_equivalent')}, "
                            f"mismatches={endpoint.get('material_mismatches')}"
                        )
            if not document["endpoint_equivalence"]["before"]["animated_material_channels"]:
                raise RuntimeError(
                    f"the {label} proof animates no material channel, so its material "
                    "endpoint equivalence would be vacuously true"
                )
        if not manifest["static_geography_invariance"]["invariant"]:
            raise RuntimeError("the manifest records the persistent city moving")
        metrics = manifest["motion_metrics"]
        animated_channels = manifest["endpoint_equivalence"]["before"]["animated_material_channels"]
        print(
            f"[7/8] manifests verified: plain UTF-8, no BOM; objects AND materials "
            f"equivalent at both endpoints ({len(animated_channels)} animated material "
            f"channel(s)); {metrics['animated_objects']} objects, "
            f"{metrics['fcurves']} F-curves, {metrics['keyframes']} keyframes; "
            f"{manifest['static_geography_invariance']['pinned_objects']} objects pinned "
            f"across {len(manifest['static_geography_invariance']['frames_checked'])} frames"
        )

        package = _proof_package()
        package.write_package_inventory(proof_dir)
        inventory = package.verify_package_inventory(proof_dir, required=REQUIRED_MEMBERS)
        print(
            f"[8/8] proof package inventory verified: {inventory['member_count']} members, "
            f"{inventory['total_bytes']} bytes, "
            f"{len(inventory['artifact_references'])} artifact reference(s) resolved"
        )
        (workspace / "phase17_gate_summary.json").write_text(
            json.dumps(
                {
                    "plans": plans,
                    "story": story["legs"],
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
        print(f"phase 17 checks failed: {error}", file=sys.stderr)
        return 1
    print("PHASE 17 LOCAL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
