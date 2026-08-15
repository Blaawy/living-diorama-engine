"""The Phase 19 local gate: engine story, pure plan, structure, mobility proof.

Plain Python -- never imports ``bpy``. Orchestrates the real engine and Blender
subprocesses to verify, end to end:

1. Blender 4.5.x LTS is available and refuses nothing silently.
2. The real three-episode story generates through the LOCKED engine, so the
   population Phase 19 moves is the one the simulation actually holds.
3. The mobility plan is valid PURE DATA before any Blender exists: every route
   is proven clear of the city, every pair of moving things is proven apart on
   every frame of the canonical timeline, the plan re-derives identically, and
   the route offer is measured so geographic coverage is a number rather than
   an impression.
4. Every structural Blender test passes, in phase order -- the LOCKED Phase 15,
   16, 17 and 18 suites, then Phase 19 -- and each suite actually ran the tests
   it carries, so a suite that never collected cannot pass by reporting nothing.
5. The mobility proof pack renders: the daily-life hero cycle, the gait verify,
   the vehicle-motion verify, the route-validity frame, the loop endpoints, the
   contact sheet, the manifest, the plan and the ``.blend``.
6. Nothing under the save chain or the export files changed one byte.
7. The manifest is plain UTF-8 JSON with no BOM, and its own recorded verdict is
   true: the traffic in the scene is the traffic the plan declares, the loop
   closes, no duplicate-named datablock appeared, and every vehicle archetype's
   components sit inside the envelope the lane network reserved for them.
8. The proof package inventories itself completely -- every member enumerated
   with size and SHA-256, nothing missing, nothing unenumerated, and no manifest
   pointing at an artifact the package does not carry.

Exit code is nonzero on any failure. Usage::

    python visual/blender/run_phase19_checks.py --workspace <fresh dir> \
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
STORY_TOOLS_DIR = BLENDER_DIR.parent.parent / "tools" / "phase17_motion"

sys.path.insert(0, str(STORY_TOOLS_DIR))

EXPORT_NAMES = ("render_export_before.json", "render_export_mid.json", "render_export_after.json")

STRUCTURAL_RESULTS = "phase19_structural_results.txt"
MOBILITY_BLEND = "living_diorama_phase19_daily_life.blend"
MOBILITY_PLAN = "phase19_mobility_plan.json"
MOBILITY_MANIFEST_ARTIFACT = "living_diorama_phase19_daily_life_mobility"
MOBILITY_MANIFEST_SCHEMA_VERSION = 1
VEHICLE_ARCHETYPES = frozenset(("compact", "sedan", "suv", "van", "coupe"))

STRUCTURAL_PHASES = ("PHASE15", "PHASE16", "PHASE17", "PHASE18", "PHASE19")

MINIMUM_STRUCTURAL_TESTS = {
    "PHASE15": 23,
    "PHASE16": 14,
    "PHASE17": 23,
    "PHASE18": 37,
    "PHASE19": 26,
    "P19": 123,
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
    MOBILITY_BLEND,
    MOBILITY_PLAN,
    "phase19_daily_life_cycle.mp4",
    "phase19_pedestrian_gait_verify.mp4",
    "phase19_vehicle_motion_verify.mp4",
    "phase19_start.png",
    "phase19_mid.png",
    "phase19_end.png",
    "phase19_city_context.png",
    "phase19_route_validity.png",
    "phase19_gait_context.png",
    "phase19_traffic_context.png",
    "phase19_contact_sheet.png",
    "phase19_mobility_manifest.json",
    EXPORT_NAMES[0],
)
"""Every member a Phase 19 proof package must carry.

The render export and the MOBILITY PLAN are both here. The export is the
authoritative input the population claim rests on; the plan is the document
every route, speed, wheel revolution and collision verdict is derived from. A
reviewer has to be able to recompute the claim from what was delivered rather
than take a manifest's word for a file that lives somewhere else.

EVERY still the producer renders is here too. The gait and traffic context
frames were produced by the render loop and named in the manifest but left off
this list, so losing either one cost the reviewer the two close-up frames that
exist to make sliding feet and crabbing wheels findable -- and cost the gate
nothing, because a member nobody required is a member nobody misses."""

PRODUCER_SUCCESS_MARKER = "phase 19 proof written to"
"""The last line the proof producer prints, and it prints it AFTER the manifest.

The gate demands this line in the captured output because an exit code alone
has already lied once. Blender in background mode exits 0 when a ``--python``
script dies on an uncaught exception unless ``--python-exit-code`` says
otherwise, so every refusal the producer raised -- the entire refusal-first
design -- looked exactly like success. In a REUSED workspace the artifacts of
an earlier completed run were still sitting in the proof directory, every
downstream check re-derived them deterministically, and the gate printed PASS
over work this run never did. The exit code is now held to the truth as well,
but the marker stays: two independent signals, both required."""


def _both_ends(text: str, keep: int = 8000) -> str:
    """The head and the tail of one long transcript, with the elision marked.

    A failing Blender run usually opens with the traceback that explains it and
    closes with whatever noise followed. Keeping only the tail, as this gate
    once did, could truncate away the one part worth reading.
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

    A zero exit is necessary but not sufficient: the marker is printed after
    the manifest lands on disk, so its absence means the run ended somewhere
    short of a delivered proof, whatever the proof directory happens to hold.
    """
    if PRODUCER_SUCCESS_MARKER not in output:
        raise RuntimeError(
            f"the proof producer never reported {PRODUCER_SUCCESS_MARKER!r}; the run ended "
            "short of a delivered proof, so nothing in the proof directory may be certified"
        )


def _structural_summary(output: str) -> dict[str, dict[str, int]]:
    """Parse the per-phase pass/fail counts, and refuse a suite that ran nothing.

    Reporting no failures is not the same as passing. A phase whose tests never
    collected prints ``0 passed, 0 failed``, which used to satisfy this function
    completely: the failure check saw nothing failed, the total cross-check
    compared zero against zero, and the gate went on to print how many phases
    had "passed in phase order". Every phase could report zero and the whole
    step still succeeded. Each suite is now held to the floor in
    :data:`MINIMUM_STRUCTURAL_TESTS`, so a suite that shrank or never ran is a
    refusal.
    """
    counts: dict[str, dict[str, int]] = {}
    for phase in (*STRUCTURAL_PHASES, "P19"):
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
    if total != counts["P19"]["passed"]:
        raise RuntimeError(
            f"structural phase counts {total} disagree with the total {counts['P19']['passed']}"
        )
    return counts


def _require_contained_envelopes(manifest: dict) -> dict[str, dict]:
    """Refuse a manifest whose vehicle bodies escape their reserved envelopes.

    The kit measures every component against the envelope the lane network
    reserved and records the verdict per archetype. Nothing read it. Containment
    was therefore decoration: a mirror or a wheel arch could grow outside the
    reservation the routes, lane widths and headways were planned from, the
    manifest would say ``contained: false`` in plain sight, and the gate would
    print PASS underneath it.

    A missing or empty contract block is refused as well, because a check that
    quietly has nothing to read is the same defect wearing a different hat.
    """
    contracts = manifest.get("vehicles", {}).get("envelope_contracts")
    if not isinstance(contracts, dict) or not contracts:
        raise RuntimeError("the manifest declares no vehicle envelope contracts")
    actual = set(contracts)
    if actual != VEHICLE_ARCHETYPES:
        raise RuntimeError(
            "the vehicle envelope contracts must cover exactly the five archetypes; "
            f"missing {sorted(VEHICLE_ARCHETYPES - actual)}, "
            f"unexpected {sorted(actual - VEHICLE_ARCHETYPES)}"
        )
    escaped: dict[str, list] = {}
    for archetype, contract in sorted(contracts.items()):
        if not isinstance(contract, dict):
            raise RuntimeError(f"the envelope contract for {archetype} is malformed")
        parts = contract.get("escaped")
        if not isinstance(parts, list):
            raise RuntimeError(f"the envelope contract for {archetype} is malformed")
        if contract.get("contained") is not True or parts:
            escaped[archetype] = sorted(parts)
    if escaped:
        raise RuntimeError(f"vehicle components escape their reserved planning envelope: {escaped}")
    return contracts


def _require_manifest_identity(manifest: dict) -> None:
    """Require the exact Phase 19 mobility artifact and schema this gate owns."""
    artifact = manifest.get("artifact")
    if artifact != MOBILITY_MANIFEST_ARTIFACT:
        raise RuntimeError(
            f"the mobility manifest declares artifact {artifact!r}, "
            f"expected {MOBILITY_MANIFEST_ARTIFACT!r}"
        )
    schema = manifest.get("schema_version")
    if schema != MOBILITY_MANIFEST_SCHEMA_VERSION:
        raise RuntimeError(
            f"the mobility manifest schema_version must be {MOBILITY_MANIFEST_SCHEMA_VERSION}, "
            f"got {schema!r}"
        )


def _require_presentation_statement(manifest: dict, expected: str) -> str:
    """Require the rendered manifest to carry the independently derived statement."""
    semantics = manifest.get("semantics")
    if not isinstance(semantics, dict) or semantics.get("statement") != expected:
        raise RuntimeError("the manifest does not carry the presentation-mobility statement")
    return semantics["statement"]


def _write_structural_results(path: Path, output: str) -> None:
    """Keep the structural suite's own per-test lines as a package member."""
    kept = [
        line
        for line in output.splitlines()
        if line.startswith(("ok   ", "FAIL ", "LD_BLENDER_TESTS_"))
    ]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")


def _load_phase15_gate():
    """Import the Phase 15 gate module for its Blender-resolution helpers."""
    spec = importlib.util.spec_from_file_location(
        "phase15_checks_for_p19", BLENDER_DIR / "run_phase15_checks.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["phase15_checks_for_p19"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules["phase15_checks_for_p19"]
    return module


def _derive_mobility(workspace: Path) -> dict:
    """Derive and interrogate the whole mobility layer with no Blender in sight."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import mobility_plan as mp
        import pedestrian_topology as topo
        import population_presence_plan as pres
        from mobility_spec import load_daily_life_mobility_spec, resolve_mobility_timeline
        from motion_time_spec import load_motion_time_spec
        from population_presence_spec import load_population_presence_spec
        from production_spec import load_production_world_spec
        from road_graph import build_road_graph
        from scene_spec import load_master_scene_spec, load_render_export
        from urban_fabric import plan_urban_fabric

        master = load_master_scene_spec(SPEC_PATH)
        production = load_production_world_spec(PRODUCTION_PATH)
        presence_spec = load_population_presence_spec(PRESENCE_PATH)
        mobility_spec = load_daily_life_mobility_spec(MOBILITY_PATH)
        timeline = resolve_mobility_timeline(
            mobility_spec, load_motion_time_spec(MOTION_PATH)["timeline"]
        )
        graph = build_road_graph(master, production)
        fabric = plan_urban_fabric(master, production, graph)
        topology = topo.plan_pedestrian_topology(master, production, graph, fabric, presence_spec)
        export = load_render_export(workspace / EXPORT_NAMES[0])
        presence = pres.plan_population_presence(export, master, presence_spec, topology)

        plan = mp.plan_daily_life_mobility(
            presence, presence_spec, mobility_spec, timeline, master, production, graph, fabric
        )
        again = mp.plan_daily_life_mobility(
            presence, presence_spec, mobility_spec, timeline, master, production, graph, fabric
        )
        if mp.mobility_plan_hash(plan) != mp.mobility_plan_hash(again):
            raise RuntimeError("the same inputs produced two different mobility plans")
        errors = mp.validate_mobility_plan(plan, presence, mobility_spec)
        if errors:
            raise RuntimeError("the mobility plan is invalid:\n- " + "\n- ".join(errors[:10]))
        if not plan["collision"]["safe"]:
            raise RuntimeError("the mobility plan is not collision free")
        if plan["vehicles"]["count"] != plan["vehicles"]["target_count"]:
            raise RuntimeError(
                f"the plan ships {plan['vehicles']['count']} vehicles against a target of "
                f"{plan['vehicles']['target_count']}"
            )
        moving = {entry["slot"] for entry in plan["pedestrians"]["walkers"]}
        known = {proxy["slot"] for proxy in presence["proxies"]}
        if not moving <= known:
            raise RuntimeError("the mobility plan walks somebody Phase 18 never placed")
        if len(known) != plan["pedestrians"]["total_proxies"]:
            raise RuntimeError("the mobility plan changed the size of the population")
        (workspace / MOBILITY_PLAN).write_text(
            json.dumps(plan, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        return {
            "plan_hash": mp.mobility_plan_hash(plan),
            "statement": plan["statement"],
            "presence_hash": pres.plan_hash(presence),
            "topology_hash": topo.topology_hash(topology),
            "summary": plan["summary"],
            "collision": plan["collision"]["closest"],
            "coverage": plan["vehicles"]["coverage"],
            "route_offer": plan["vehicles"]["route_offer"],
            "refused_walkers": len(plan["pedestrians"]["refused"]),
        }
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


def _mobility_package():
    """Import the pure Phase 19 proof-package contract module."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        import mobility_proof_package

        return mobility_proof_package
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
    """Run the complete Phase 19 local verification gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="fresh output directory")
    parser.add_argument("--blender", default=None)
    parser.add_argument("--preview", action="store_true", help="fast low-quality renders")
    parser.add_argument("--base-sha", default="", help="canonical commit this candidate targets")
    arguments = parser.parse_args(argv)
    if not arguments.workspace.strip():
        print("phase 19 checks failed: --workspace must not be empty", file=sys.stderr)
        return 1
    workspace = Path(arguments.workspace)
    proof_dir = workspace / "mobility_proof"
    if proof_dir.exists() and (not proof_dir.is_dir() or any(proof_dir.iterdir())):
        # The docstring demands a fresh directory; this makes the demand
        # executable. A producer that dies over a previous run's proof leaves
        # artifacts every downstream check re-derives deterministically, so a
        # PASS printed here would be certifying work this run never did.
        print(
            f"phase 19 checks failed: {proof_dir} already holds artifacts from an "
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
        print("[2/8] real engine story generated; the population Phase 19 moves is the world's")

        mobility = _derive_mobility(workspace)
        summary = mobility["summary"]
        coverage = mobility["coverage"]
        print(
            f"      {summary['moving_pedestrians']} of {summary['total_population_proxies']} "
            f"proxies walk, {summary['stationary_pedestrians']} stand; "
            f"{summary['moving_vehicles']} vehicles on {summary['circuits']} route(s); "
            f"{summary['total_moving_root_objects']} moving root objects in total"
        )
        print(
            f"      closest approach: {json.dumps(mobility['collision'], sort_keys=True)} "
            f"over {summary['frames_sampled']} frames"
        )
        print(
            f"      route offer: {mobility['route_offer']['candidates_offered']}, "
            f"{mobility['route_offer']['candidates_viable']} viable, "
            f"{mobility['route_offer']['legal_turnarounds']} legal turnaround(s)"
        )
        segments = len(coverage["segments_carrying_traffic"])
        every = segments + len(coverage["segments_without_traffic"])
        print(
            f"      traffic covers x{coverage['traffic_extent_x']} "
            f"y{coverage['traffic_extent_y']}, {segments} of {every} road segments, "
            f"regions {coverage['regions_with_traffic']}"
        )
        print("[3/8] mobility plan valid, deterministic, collision free, and measured")

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
            TESTS_DIR / "run_blender_tests_p19.py",
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
            + f" ({structural['P19']['passed']} total)"
        )

        # Deliberately NOT the locked gate's run_blender, which neither passes
        # --python-exit-code nor returns the output. The producer's refusals
        # are uncaught exceptions by design, and this is the step where an
        # exit code of 0 over a crashed script once meant PASS over a stale
        # proof directory.
        blend_path = proof_dir / MOBILITY_BLEND
        producer_output = _run_blender_capturing(
            blender,
            SCRIPTS_DIR / "produce_mobility_proof.py",
            [
                "--spec",
                str(SPEC_PATH),
                "--production",
                str(PRODUCTION_PATH),
                "--presence",
                str(PRESENCE_PATH),
                "--mobility",
                str(MOBILITY_PATH),
                "--motion",
                str(MOTION_PATH),
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
        _require_producer_success(producer_output)
        print("[5/8] mobility proof rendered: hero cycle, gait verify, traffic verify, validity")

        if gate.tree_hashes(save_root) != saves_before:
            raise RuntimeError("the save chain changed during verification")
        for name, digest in exports_before.items():
            if hashlib.sha256(exports[name].read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"{name} changed during verification")
        print("[6/8] the engine's saves and exports are byte-identical")

        manifest = _require_clean_manifest(proof_dir / "phase19_mobility_manifest.json")
        _require_manifest_identity(manifest)
        if manifest["plan_hash"] != mobility["plan_hash"]:
            raise RuntimeError(
                "the rendered plan is not the plan the pure planner derived: "
                f"{manifest['plan_hash']} vs {mobility['plan_hash']}"
            )
        scene = manifest["scene_mobility"]
        if scene["vehicle_bodies"] != summary["moving_vehicles"]:
            raise RuntimeError(
                f"the scene holds {scene['vehicle_bodies']} vehicles, the plan declares "
                f"{summary['moving_vehicles']}"
            )
        if scene["walking_proxies"] != summary["moving_pedestrians"]:
            raise RuntimeError(
                f"the scene walks {scene['walking_proxies']} proxies, the plan declares "
                f"{summary['moving_pedestrians']}"
            )
        if scene["duplicate_named_objects"]:
            raise RuntimeError("the mobility layer produced duplicate-named datablocks")
        if scene["linked_elsewhere"]:
            raise RuntimeError("a mobility object is linked outside its own collection")
        loop = manifest["loop_closure"]
        if not loop["closed"]:
            raise RuntimeError(
                f"the mobility loop does not close: worst drift {loop['worst_drift']}"
            )
        _require_presentation_statement(manifest, mobility["statement"])
        envelopes = _require_contained_envelopes(manifest)
        print(
            f"[7/8] manifest verdict true: {scene['vehicle_bodies']} vehicles, "
            f"{scene['walking_proxies']} walkers, loop drift {loop['worst_drift']}, "
            f"plan hash matches, {len(envelopes)} archetype(s) inside their envelope"
        )

        package = _mobility_package()
        package.write_mobility_inventory(proof_dir)
        inventory = package.verify_mobility_inventory(
            proof_dir,
            required=REQUIRED_MEMBERS,
            exact_required=True,
        )
        print(
            f"[8/8] proof package inventory verified: {inventory['member_count']} members, "
            f"{inventory['total_bytes']} bytes, "
            f"{len(inventory['artifact_references'])} artifact reference(s) resolved"
        )
        (workspace / "phase19_gate_summary.json").write_text(
            json.dumps(
                {"mobility": mobility, "structural": structural, "package": inventory},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except Exception as error:  # noqa: BLE001 - the gate reports, then fails loudly
        print(f"phase 19 checks failed: {error}", file=sys.stderr)
        return 1
    print("PHASE 19 LOCAL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
