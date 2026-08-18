"""The Phase 20 local gate: engine story, pure plans, structure, state-response proof.

Plain Python -- never imports ``bpy``. Orchestrates the real engine and Blender
subprocesses to verify, end to end:

1. Blender 4.5.x LTS is available and refuses nothing silently.
2. The real three-episode story generates through the LOCKED engine, so the
   world condition Phase 20 shows is the one the simulation actually holds.
3. Every Phase 20 plan is valid PURE DATA before any Blender exists: all three
   episode plans and both transition plans re-derive identically, each says only
   true things about itself, and leg 1 genuinely carries directives -- a proof of
   a world that never changed would be a proof of nothing.
4. Every structural Blender test passes, in phase order -- the LOCKED Phase 15,
   16, 17, 18 and 19 suites, then Phase 20 -- and each suite actually ran the
   tests it carries, so a suite that never collected cannot pass by reporting
   nothing.
5. The state-response proof pack renders: the whole-city before/after pair on
   ONE camera, the district-scale pair on ONE camera, the Seal detail carrying
   the record stones, the mid-transition frame, the two plan documents, the
   manifest and the ``.blend``.
6. Nothing under the save chain or the export files changed one byte.
7. The manifest is plain UTF-8 JSON with no BOM, its plan hashes are the hashes
   the pure derivation just computed, the scene holds what the plan declares,
   both legs land on their own static endpoints -- and the animation that landed
   there was not empty, because an animation that moves nothing satisfies both
   endpoints for the wrong reason.
8. The proof package inventories itself completely -- every member enumerated
   with size and SHA-256, nothing missing, nothing unenumerated, and no manifest
   pointing at an artifact the package does not carry.

Exit code is nonzero on any failure. Usage::

    python visual/blender/run_phase20_checks.py --workspace <fresh dir> \
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
PRESENCE_PATH = CONFIG_DIR / "population_presence_v1.json"
MOBILITY_PATH = CONFIG_DIR / "daily_life_mobility_v1.json"
STATE_RESPONSE_PATH = CONFIG_DIR / "state_response_v1.json"
STORY_TOOLS_DIR = BLENDER_DIR.parent.parent / "tools" / "phase17_motion"

sys.path.insert(0, str(STORY_TOOLS_DIR))

EXPORT_NAMES = ("render_export_before.json", "render_export_mid.json", "render_export_after.json")
EPISODES = ("before", "mid", "after")
LEGS = (("leg1", "before", "mid"), ("leg2", "mid", "after"))

STRUCTURAL_RESULTS = "phase20_structural_results.txt"
STATE_RESPONSE_BLEND = "living_diorama_phase20_state_response.blend"
STATE_RESPONSE_MANIFEST = "phase20_state_response_manifest.json"
STATE_RESPONSE_PLANS = "phase20_state_response_plans.json"
STATE_RESPONSE_MOTION_PLANS = "phase20_state_response_motion_plans.json"
MANIFEST_ARTIFACT = "living_diorama_phase20_state_response"
MANIFEST_SCHEMA_VERSION = 1

STILLS = (
    "phase20_world_before.png",
    "phase20_world_after.png",
    "phase20_district_pair_before.png",
    "phase20_district_pair_after.png",
    "phase20_seal_records.png",
    "phase20_transition_mid.png",
)

DENSITY_RELATIVE_TOLERANCE = 1.0e-5
"""How far a scene-measured density may sit from the planned one.

RELATIVE, because air densities are thousandths: an absolute tolerance sized for
ordinary scene units would swallow the whole signal and wave through a stratum
carrying another district's reading. A double planned here and stored in a
32-bit socket comes back around 1e-7 relative, so this is two orders of
magnitude looser than the storage and four tighter than the smallest difference
between two districts in the canonical chain."""

STRUCTURAL_PHASES = ("PHASE15", "PHASE16", "PHASE17", "PHASE18", "PHASE19", "PHASE20")

MINIMUM_STRUCTURAL_TESTS = {
    "PHASE15": 28,
    "PHASE16": 15,
    "PHASE17": 23,
    "PHASE18": 37,
    "PHASE19": 26,
    "PHASE20": 10,
    "P20": 139,
}
"""The fewest structural tests each suite may execute before the gate disbelieves it.

A FLOOR, set at the counts the suites carry today, rather than an equality. A
suite that fails to COLLECT -- a syntax error in a test module, a rename that
empties a suite list -- reports ``0 passed, 0 failed``, which the failure check
below waves through because nothing failed, and which then drags the total
cross-check down to ``0 == 0``. A phase that ran nothing was therefore
indistinguishable from a phase that passed.

Exact counts would catch that too, but they refuse every honest run that ADDS a
test, so the number would be edited on most green commits and would soon be
edited to whatever made the run pass. A floor is only ever tripped by a suite
that SHRANK, which is precisely the event worth stopping, and raising it is the
deliberate act of someone who has just counted."""

REQUIRED_MEMBERS = (
    STRUCTURAL_RESULTS,
    STATE_RESPONSE_BLEND,
    STATE_RESPONSE_MANIFEST,
    STATE_RESPONSE_PLANS,
    STATE_RESPONSE_MOTION_PLANS,
    *EXPORT_NAMES,
    *STILLS,
)
"""Every member a Phase 20 proof package must carry.

ALL THREE render exports are here. Phase 20's claim is a comparison across the
chain rather than a reading of one state, and the leg that matters most -- the
one where the air does not move and the world remembers anyway -- is invisible
without the middle episode. Both plan documents are here for the same reason
Phase 19 packaged its mobility plan: a reviewer who cannot open them cannot
recompute a single reading, response, directive or frame window the manifest
claims.

EVERY still the producer renders is here too. A frame nobody required is a frame
nobody misses, and the two pairs are the entire evidentiary content of this
phase: losing one half of a pair costs the reviewer the comparison and costs the
gate nothing."""

PRODUCER_SUCCESS_MARKER = "phase 20 proof written to"
"""The last line the proof producer prints, and it prints it AFTER the manifest.

The gate demands this line in the captured output because an exit code alone has
already lied once. Blender in background mode exits 0 when a ``--python`` script
dies on an uncaught exception unless ``--python-exit-code`` says otherwise, so
every refusal the producer raised -- the entire refusal-first design -- looked
exactly like success. In a REUSED workspace the artifacts of an earlier
completed run were still sitting in the proof directory, every downstream check
re-derived them deterministically, and the gate printed PASS over work this run
never did. The exit code is now held to the truth as well, but the marker stays:
two independent signals, both required."""


def _both_ends(text: str, keep: int = 8000) -> str:
    """The head and the tail of one long transcript, with the elision marked.

    A failing Blender run usually opens with the traceback that explains it and
    closes with whatever noise followed. Keeping only the tail could truncate
    away the one part worth reading.
    """
    if len(text) <= 2 * keep:
        return text
    elided = len(text) - 2 * keep
    return f"{text[:keep]}\n... [{elided} characters elided] ...\n{text[-keep:]}"


def _run_blender_capturing(blender: Path, script: Path, script_args: list[str]) -> str:
    """Run one headless Blender script, hold it to its exceptions, and RETURN its output.

    ``--python-exit-code 1`` is the load-bearing flag. Without it, background
    Blender exits 0 when the script dies on an uncaught exception, so a crashed
    or refusing script was indistinguishable from one that finished. Output is
    decoded as UTF-8 with replacement rather than the platform's locale codec,
    because on Windows a single non-ASCII byte in a Blender traceback would
    otherwise raise ``UnicodeDecodeError`` and fail the gate for reporting.
    """
    completed = subprocess.run(
        [
            str(blender),
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(script),
            "--",
            *script_args,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        sys.stderr.write(_both_ends(completed.stdout))
        sys.stderr.write(_both_ends(completed.stderr))
        raise RuntimeError(f"Blender step failed: {script.name}")
    return completed.stdout


def _require_producer_success(output: str) -> None:
    """Refuse a producer run that never said it finished.

    A zero exit is necessary but not sufficient: the marker is printed after the
    manifest lands on disk, so its absence means the run ended somewhere short of
    a delivered proof, whatever the proof directory happens to hold.
    """
    if PRODUCER_SUCCESS_MARKER not in output:
        raise RuntimeError(
            f"the proof producer never reported {PRODUCER_SUCCESS_MARKER!r}; the run ended "
            "short of a delivered proof, so nothing in the proof directory may be certified"
        )


def _structural_summary(output: str) -> dict[str, dict[str, int]]:
    """Parse the per-phase pass/fail counts, and refuse a suite that ran nothing.

    Reporting no failures is not the same as passing. A phase whose tests never
    collected prints ``0 passed, 0 failed``, which would otherwise satisfy this
    function completely: the failure check sees nothing failed and the total
    cross-check compares zero against zero. Each suite is held to the floor in
    :data:`MINIMUM_STRUCTURAL_TESTS`, so a suite that shrank or never ran is a
    refusal.
    """
    counts: dict[str, dict[str, int]] = {}
    for phase in (*STRUCTURAL_PHASES, "P20"):
        match = re.search(
            rf"^LD_BLENDER_TESTS_{phase}: (\d+) passed, (\d+) failed$", output, re.MULTILINE
        )
        if match is None:
            raise RuntimeError(f"the structural runner reported no result for {phase}")
        counts[phase] = {"passed": int(match.group(1)), "failed": int(match.group(2))}
        if counts[phase]["failed"]:
            raise RuntimeError(f"{phase} structural tests failed: {counts[phase]}")
        executed = counts[phase]["passed"] + counts[phase]["failed"]
        floor = MINIMUM_STRUCTURAL_TESTS[phase]
        if executed < floor:
            raise RuntimeError(
                f"{phase} executed {executed} structural tests, fewer than the {floor} the "
                "suite carries; a suite that never collected reports no failures either"
            )
    total = sum(counts[phase]["passed"] for phase in STRUCTURAL_PHASES)
    if total != counts["P20"]["passed"]:
        raise RuntimeError(
            f"structural phase counts {total} disagree with the total {counts['P20']['passed']}"
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

    Never a copied path. The locator refuses to guess a machine's installation,
    and a second copy of it here would be a second thing to keep true.
    """
    spec = importlib.util.spec_from_file_location(
        "phase15_checks_for_p20", BLENDER_DIR / "run_phase15_checks.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["phase15_checks_for_p20"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules["phase15_checks_for_p20"]
    return module


def _derive_state_response(workspace: Path) -> dict:
    """Derive and interrogate the whole Phase 20 layer with no Blender in sight.

    Every plan is derived TWICE from the same inputs and refused on hash
    divergence, because a plan whose hash depends on the run is not a plan the
    gate can hold a render to.

    Args:
        workspace: The directory the engine story was generated into.

    Returns:
        The plan hashes, the per-episode and per-leg summaries, and the
        authoritative readings the manifest will be held to.

    Raises:
        RuntimeError: On any divergence, invalidity, or an empty leg 1.
    """
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import state_response_motion_plan as motion_plan
        import state_response_plan as response_plan
        from motion_time_spec import load_motion_time_spec
        from scene_spec import load_master_scene_spec, load_render_export
        from state_response_spec import load_state_response_spec, resolve_state_response_timeline

        master = load_master_scene_spec(SPEC_PATH)
        spec = load_state_response_spec(STATE_RESPONSE_PATH)
        timeline = resolve_state_response_timeline(
            spec, load_motion_time_spec(MOTION_PATH)["timeline"]
        )
        exports = {
            label: load_render_export(workspace / name)
            for label, name in zip(EPISODES, EXPORT_NAMES, strict=True)
        }

        plans: dict[str, dict] = {}
        hashes: dict[str, str] = {}
        for label in EPISODES:
            plan = response_plan.plan_state_response(exports[label], master, spec)
            again = response_plan.plan_state_response(exports[label], master, spec)
            if response_plan.plan_hash(plan) != response_plan.plan_hash(again):
                raise RuntimeError(f"the same inputs produced two different {label} plans")
            problems = response_plan.validate_state_response_plan(plan)
            if problems:
                raise RuntimeError(
                    f"the {label} state response plan is invalid:\n- " + "\n- ".join(problems[:10])
                )
            plans[label] = plan
            hashes[label] = response_plan.plan_hash(plan)

        motions: dict[str, dict] = {}
        for leg, earlier, later in LEGS:
            transition = motion_plan.plan_state_response_motion(
                plans[earlier], plans[later], spec, timeline
            )
            again = motion_plan.plan_state_response_motion(
                plans[earlier], plans[later], spec, timeline
            )
            if motion_plan.plan_hash(transition) != motion_plan.plan_hash(again):
                raise RuntimeError(f"the same inputs produced two different {leg} plans")
            problems = motion_plan.validate_state_response_motion_plan(transition)
            if problems:
                raise RuntimeError(
                    f"the {leg} transition plan is invalid:\n- " + "\n- ".join(problems[:10])
                )
            motions[leg] = transition
            hashes[leg] = motion_plan.plan_hash(transition)

        if not motions["leg1"]["directives"]:
            raise RuntimeError(
                "leg 1 carries no directive; the canonical chain's first transition is the one "
                "that moves every channel, so an empty leg 1 means the proof would show a world "
                "that never changed"
            )

        air = {
            response["semantic_id"]: response
            for response in plans["after"]["responses"]
            if response["channel"] == "district_air"
        }
        return {
            "plan_hashes": hashes,
            "representation": response_plan.REPRESENTATION_STATEMENT,
            "timeline": dict(sorted(timeline.items())),
            "episodes": {label: plans[label]["summary"] for label in EPISODES},
            "legs": {leg: motions[leg]["summary"] for leg, _, _ in LEGS},
            "after_densities": {district: air[district]["value"] for district in sorted(air)},
            "after_readings": {district: air[district]["source_value"] for district in sorted(air)},
            "after_responses": len(plans["after"]["responses"]),
            "after_records": plans["after"]["summary"]["responses_by_channel"].get(
                "memory_record", 0
            ),
            "signals": plans["after"]["summary"]["signals"],
        }
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


def _state_response_package():
    """Import the pure Phase 20 proof-package contract module."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import state_response_proof_package

        return state_response_proof_package
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


def _require_manifest_identity(manifest: dict) -> None:
    """Require the exact Phase 20 artifact and schema this gate owns.

    Raises:
        RuntimeError: If the manifest is some other phase's document, or a
            schema this gate does not know how to read.
    """
    artifact = manifest.get("artifact")
    if artifact != MANIFEST_ARTIFACT:
        raise RuntimeError(
            f"the state response manifest declares artifact {artifact!r}, "
            f"expected {MANIFEST_ARTIFACT!r}"
        )
    schema = manifest.get("schema_version")
    if schema != MANIFEST_SCHEMA_VERSION:
        raise RuntimeError(
            f"the state response manifest schema_version must be {MANIFEST_SCHEMA_VERSION}, "
            f"got {schema!r}"
        )


def _require_plan_hashes(manifest: dict, expected: dict[str, str]) -> None:
    """Require the rendered plans to be the plans the pure derivation produced.

    Raises:
        RuntimeError: If any of the five hashes is absent or different.
    """
    declared = manifest.get("plan_hashes")
    if not isinstance(declared, dict):
        raise RuntimeError("the manifest declares no plan hashes")
    disagreements = sorted(
        f"{name}: {declared.get(name)!r} vs {digest!r}"
        for name, digest in expected.items()
        if declared.get(name) != digest
    )
    if disagreements:
        raise RuntimeError(
            "the rendered plans are not the plans the pure derivation produced: "
            + "; ".join(disagreements)
        )
    unexpected = sorted(set(declared) - set(expected))
    if unexpected:
        raise RuntimeError(f"the manifest declares plan hashes nobody derived: {unexpected}")


def _require_scene_counts(manifest: dict, derived: dict) -> dict:
    """Require the scene to hold what the plan declares, district by district.

    The counts alone would pass a scene that built the right number of strata
    carrying the wrong district's readings, so every measured density is checked
    against the value the pure planner computed for THAT district.

    Raises:
        RuntimeError: On any disagreement between the measured scene and the plan.
    """
    scene = manifest.get("scene")
    if not isinstance(scene, dict) or not isinstance(scene.get("static"), dict):
        raise RuntimeError("the manifest carries no measured static scene")
    static = scene["static"]
    expected_air = len(derived["after_densities"])
    if static.get("air_volumes") != expected_air:
        raise RuntimeError(
            f"the scene holds {static.get('air_volumes')!r} district strata, "
            f"the plan declares {expected_air}"
        )
    if static.get("record_stones") != derived["after_records"]:
        raise RuntimeError(
            f"the scene holds {static.get('record_stones')!r} record stones, "
            f"the plan declares {derived['after_records']}"
        )
    if static.get("objects") != derived["after_responses"]:
        raise RuntimeError(
            f"the scene holds {static.get('objects')!r} state-response objects, "
            f"the plan declares {derived['after_responses']} responses"
        )
    densities = static.get("densities")
    if not isinstance(densities, dict) or set(densities) != set(derived["after_densities"]):
        raise RuntimeError(
            f"the scene measures densities for {sorted(densities or [])}, "
            f"the plan declares {sorted(derived['after_densities'])}"
        )
    wrong = sorted(
        f"{district}: {densities[district]!r} vs {expected!r}"
        for district, expected in derived["after_densities"].items()
        if abs(float(densities[district]) - expected)
        > DENSITY_RELATIVE_TOLERANCE * max(abs(expected), 1.0e-12)
    )
    if wrong:
        raise RuntimeError(
            "a district's air carries a density the plan never asked for: " + "; ".join(wrong)
        )
    return static


def _require_endpoint_equivalence(manifest: dict, derived: dict) -> dict:
    """Require both legs to land on their own static endpoints, non-vacuously.

    Two independent claims, and the second one is the load-bearing one. Endpoint
    equivalence alone is satisfied perfectly by an animation that wrote NO curves
    at all: the scene then sits at the static application of whichever plan was
    applied last, both measured endpoints equal it, and both comparisons return
    true for the one reason that proves nothing. So the gate also requires that
    each leg animated exactly the channels its own directives name, and that the
    scene really carries actions, F-curves and keys.

    Raises:
        RuntimeError: If a verdict is missing or false, or the animation behind
            it was empty.
    """
    block = manifest.get("endpoint_equivalence")
    if not isinstance(block, dict):
        raise RuntimeError("the manifest carries no endpoint-equivalence verdict")
    legs = block.get("legs")
    if not isinstance(legs, dict) or set(legs) != {leg for leg, _, _ in LEGS}:
        raise RuntimeError(
            f"the manifest reports endpoints for {sorted(legs or [])}, "
            f"expected {sorted(leg for leg, _, _ in LEGS)}"
        )
    if block.get("equivalent") is not True:
        raise RuntimeError("the manifest's own endpoint-equivalence verdict is not true")

    motion = manifest.get("scene", {}).get("motion")
    if not isinstance(motion, dict) or set(motion) != set(legs):
        raise RuntimeError("the manifest carries no measured animation for both legs")

    for leg in sorted(legs):
        verdict = legs[leg]
        if not isinstance(verdict, dict):
            raise RuntimeError(f"the {leg} endpoint verdict is malformed")
        for end in ("before", "after"):
            endpoint = verdict.get(end)
            if not isinstance(endpoint, dict) or endpoint.get("equivalent") is not True:
                raise RuntimeError(
                    f"the {leg} animation's {end} end is not the static application of its "
                    f"own export: {endpoint!r}"
                )
        if verdict.get("equivalent") is not True:
            raise RuntimeError(f"the {leg} endpoint verdict is not true")
        animated = verdict.get("animated_channels")
        expected = sorted(derived["legs"][leg]["directives_by_channel"])
        if not animated:
            raise RuntimeError(
                f"the {leg} animation moved no channel at all; both its endpoints then equal "
                "the same standing static layer and the verdict is true for the one reason "
                "that proves nothing"
            )
        if sorted(animated) != expected:
            raise RuntimeError(
                f"the {leg} animation moved {sorted(animated)}, its directives name {expected}"
            )
        measured = motion[leg]
        if not isinstance(measured, dict):
            raise RuntimeError(f"the {leg} measured animation is malformed")
        empty = sorted(
            field for field in ("actions", "fcurves", "keyframes") if not measured.get(field)
        )
        if empty:
            raise RuntimeError(
                f"the {leg} scene carries no {empty}; the endpoints were compared against an "
                "animation that does not exist"
            )
    return block


def _require_representation(manifest: dict, expected: str) -> str:
    """Require the rendered manifest to carry the independently derived statement.

    Raises:
        RuntimeError: If the semantics block is absent or says something else.
    """
    semantics = manifest.get("semantics")
    if not isinstance(semantics, dict) or semantics.get("statement") != expected:
        raise RuntimeError("the manifest does not carry the Phase 20 representation statement")
    return semantics["statement"]


def main(argv: list[str] | None = None) -> int:
    """Run the complete Phase 20 local verification gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="fresh output directory")
    parser.add_argument("--blender", default=None)
    parser.add_argument("--preview", action="store_true", help="fast low-quality renders")
    parser.add_argument("--base-sha", default="", help="canonical commit this candidate targets")
    arguments = parser.parse_args(argv)
    if not arguments.workspace.strip():
        print("phase 20 checks failed: --workspace must not be empty", file=sys.stderr)
        return 1
    workspace = Path(arguments.workspace)
    proof_dir = workspace / "state_response_proof"
    if proof_dir.exists() and (not proof_dir.is_dir() or any(proof_dir.iterdir())):
        # The docstring demands a fresh directory; this makes the demand
        # executable. A producer that dies over a previous run's proof leaves
        # artifacts every downstream check re-derives deterministically, so a
        # PASS printed here would be certifying work this run never did.
        print(
            f"phase 20 checks failed: {proof_dir} already holds artifacts from an "
            "earlier run; this gate refuses to certify a proof it may not have "
            "produced, so run it in a fresh workspace",
            file=sys.stderr,
        )
        return 1

    try:
        gate = _load_phase15_gate()
        blender = gate.locate_blender(arguments.blender)
        blender_version = gate.require_blender_45(blender)
        print(f"[1/8] {blender_version} at {blender}")

        from generate_motion_story import generate_motion_story

        generate_motion_story(workspace)
        print("[2/8] real engine story generated; the condition Phase 20 shows is the world's")

        derived = _derive_state_response(workspace)
        for label in EPISODES:
            summary = derived["episodes"][label]
            print(
                f"      {label}: {summary['districts']} district(s), "
                f"{summary['memory_facts']} remembered fact(s), "
                f"{summary['responses']} response(s), signals {summary['signals']}"
            )
        for leg, earlier, later in LEGS:
            summary = derived["legs"][leg]
            print(
                f"      {leg} {earlier}->{later}: {summary['directives']} directive(s) "
                f"{summary['directives_by_channel']}, unchanged "
                f"{summary['unchanged_channels']}"
            )
        print(
            "      authoritative readings at the end of the chain: "
            + json.dumps(derived["after_readings"], sort_keys=True)
        )
        print("[3/8] every Phase 20 plan valid, deterministic, and leg 1 genuinely moves")

        exports = {name: workspace / name for name in EXPORT_NAMES}
        save_root = workspace / "saves"
        saves_before = gate.tree_hashes(save_root)
        exports_before = {
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in exports.items()
        }

        blender_workdir = workspace / "blender_work"
        blender_workdir.mkdir(parents=True, exist_ok=True)
        proof_dir.mkdir(parents=True, exist_ok=True)
        structural_output = _run_blender_capturing(
            blender,
            TESTS_DIR / "run_blender_tests_p20.py",
            [
                "--spec",
                str(SPEC_PATH),
                "--production",
                str(PRODUCTION_PATH),
                "--motion",
                str(MOTION_PATH),
                "--presence",
                str(PRESENCE_PATH),
                "--mobility",
                str(MOBILITY_PATH),
                "--state-response",
                str(STATE_RESPONSE_PATH),
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
            "[4/8] structural tests passed in phase order: "
            + ", ".join(
                f"Phase {phase[5:]} {structural[phase]['passed']}" for phase in STRUCTURAL_PHASES
            )
            + f" ({structural['P20']['passed']} total)"
        )

        # Deliberately NOT the locked gate's run_blender, which neither passes
        # --python-exit-code nor returns the output. The producer's refusals are
        # uncaught exceptions by design, and this is the step where an exit code
        # of 0 over a crashed script once meant PASS over a stale proof directory.
        blend_path = proof_dir / STATE_RESPONSE_BLEND
        producer_output = _run_blender_capturing(
            blender,
            SCRIPTS_DIR / "produce_state_response_proof.py",
            [
                "--spec",
                str(SPEC_PATH),
                "--production",
                str(PRODUCTION_PATH),
                "--state-response",
                str(STATE_RESPONSE_PATH),
                "--motion",
                str(MOTION_PATH),
                "--before",
                str(exports[EXPORT_NAMES[0]]),
                "--mid",
                str(exports[EXPORT_NAMES[1]]),
                "--after",
                str(exports[EXPORT_NAMES[2]]),
                "--outdir",
                str(proof_dir),
                "--blend",
                str(blend_path),
                "--base-sha",
                arguments.base_sha,
                *(["--preview"] if arguments.preview else []),
            ],
        )
        _require_producer_success(producer_output)
        print("[5/8] state response proof rendered: world pair, district pair, seal, transition")

        if gate.tree_hashes(save_root) != saves_before:
            raise RuntimeError("the save chain changed during verification")
        for name, digest in exports_before.items():
            if hashlib.sha256(exports[name].read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"{name} changed during verification")
        print("[6/8] the engine's saves and exports are byte-identical")

        package = _state_response_package()
        manifest = _require_clean_manifest(proof_dir / STATE_RESPONSE_MANIFEST)
        _require_manifest_identity(manifest)
        _require_plan_hashes(manifest, derived["plan_hashes"])
        static = _require_scene_counts(manifest, derived)
        equivalence = _require_endpoint_equivalence(manifest, derived)
        cameras = package.require_identical_comparison_cameras(manifest.get("renders") or [])
        _require_representation(manifest, derived["representation"])
        print(
            f"[7/8] manifest verdict true: {static['air_volumes']} strata, "
            f"{static['record_stones']} record stone(s), plan hashes match, both legs land "
            f"on their own static endpoints moving {equivalence['animated_channels']}, "
            f"comparison pairs share one camera each ({sorted(set(cameras.values()))})"
        )

        package.write_state_response_inventory(proof_dir)
        inventory = package.verify_state_response_inventory(
            proof_dir,
            required=REQUIRED_MEMBERS,
            exact_required=True,
        )
        print(
            f"[8/8] proof package inventory verified: {inventory['member_count']} members, "
            f"{inventory['total_bytes']} bytes, "
            f"{len(inventory['artifact_references'])} artifact reference(s) resolved"
        )
        (workspace / "phase20_gate_summary.json").write_text(
            json.dumps(
                {"derived": derived, "structural": structural, "package": inventory},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except Exception as error:  # noqa: BLE001 - the gate reports, then fails loudly
        print(f"phase 20 checks failed: {error}", file=sys.stderr)
        return 1
    print("PHASE 20 LOCAL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
