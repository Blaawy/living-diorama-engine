r"""In-Blender structural test runner for Phase 23 (superset of Phase 22).

Runs inside ``blender --background --factory-startup`` where ``bpy`` exists;
ordinary pytest never imports this. The order is the contract: every LOCKED
prior suite runs first, in phase order, against the freshly composed world, and
only then the Phase 23 render suite. Rendering can therefore never be made to
pass by weakening anything that came before it.

The world these suites run against is composed by the PRODUCTION composer --
the same ``episode_scene`` module the production renderer uses -- so a suite
that passes here passes against the scene a real render photographs, not
against a test-only reconstruction.

Usage::

    blender --background --factory-startup --python run_blender_tests_p23.py \\
        -- --spec master_scene_v1.json --production production_world_v1.json \\
        --motion motion_time_v1.json --presence population_presence_v1.json \\
        --mobility daily_life_mobility_v1.json \\
        --state-response state_response_v1.json \\
        --before before.json --mid mid.json --after after.json \\
        --shot-plan-baseline plan0.json --shot-plan-leg1 plan01.json \\
        --shot-plan-leg2 plan12.json --catalogue catalogue.json \\
        --beat-kinds beat_kinds.json --render-plan-leg1 render_plan.json \\
        --workdir <scratch dir>
"""

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
for directory in (str(TESTS_DIR), str(SCRIPTS_DIR)):
    if directory not in sys.path:
        sys.path.insert(0, directory)

import build_master_scene  # noqa: E402
import episode_scene  # noqa: E402
import render_episode  # noqa: E402
import run_blender_tests_p22 as p22  # noqa: E402
import test_apply_render_export  # noqa: E402
import test_cinematic_direction  # noqa: E402
import test_episode_render  # noqa: E402
import test_master_scene  # noqa: E402
import test_mobility  # noqa: E402
import test_motion_time  # noqa: E402
import test_population_presence  # noqa: E402
import test_production_world  # noqa: E402
import test_state_response  # noqa: E402
from apply_cinematic_direction import (  # noqa: E402
    APPROVED_CATALOGUE_SHA256,
    CANONICAL_MOTION_TIME_SHA256,
    _catalogue_digest,
)
from blender_runtime import require_supported_blender  # noqa: E402

LOCKED_SUITES = (
    ("phase15", (test_master_scene, test_apply_render_export)),
    ("phase16", (test_production_world,)),
    ("phase17", (test_motion_time,)),
    ("phase18", (test_population_presence,)),
    ("phase19", (test_mobility,)),
    ("phase20", (test_state_response,)),
    ("phase22", (test_cinematic_direction,)),
)
"""Every locked suite, in phase order. Phase 23's own runs after these pass."""


def run_suites(suites: tuple, context: dict, per_phase: dict) -> tuple[int, int]:
    """Run each suite's tests in definition order, reporting per phase."""
    executed = 0
    failures = 0
    for phase, modules in suites:
        counts = per_phase.setdefault(phase, [0, 0])
        for module in modules:
            for function in p22.collect(module):
                executed += 1
                counts[0] += 1
                label = f"{module.__name__}.{function.__name__}"
                try:
                    function(context)
                except Exception:
                    failures += 1
                    counts[1] += 1
                    print(f"FAIL {label}")
                    traceback.print_exc()
                else:
                    print(f"ok   {label}")
    return executed, failures


def main() -> int:
    """Compose the world, run every suite in phase order, and exit."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "spec",
        "production",
        "motion",
        "presence",
        "mobility",
        "state-response",
        "before",
        "mid",
        "after",
        "shot-plan-baseline",
        "shot-plan-leg1",
        "shot-plan-leg2",
        "catalogue",
        "beat-kinds",
        "render-plan-leg1",
        "render-plan-baseline",
        "workdir",
    ):
        parser.add_argument(f"--{name}", required=True)
    arguments = parser.parse_args(argv)

    require_supported_blender()
    context = {
        "spec_path": Path(arguments.spec),
        "production_path": Path(arguments.production),
        "motion_path": Path(arguments.motion),
        "presence_path": Path(arguments.presence),
        "mobility_path": Path(arguments.mobility),
        "state_response_path": Path(arguments.state_response),
        "before_path": Path(arguments.before),
        "mid_path": Path(arguments.mid),
        "after_path": Path(arguments.after),
        "workdir": Path(arguments.workdir),
        "shot_plans": {
            "baseline": json.loads(Path(arguments.shot_plan_baseline).read_text(encoding="utf-8")),
            "leg1": json.loads(Path(arguments.shot_plan_leg1).read_text(encoding="utf-8")),
            "leg2": json.loads(Path(arguments.shot_plan_leg2).read_text(encoding="utf-8")),
        },
        # The raw bytes as well as the parsed documents: the render plan binds a
        # digest of a file, and only the file can answer for it.
        "shot_plan_paths": {
            "baseline": Path(arguments.shot_plan_baseline),
            "leg1": Path(arguments.shot_plan_leg1),
            "leg2": Path(arguments.shot_plan_leg2),
        },
        "catalogue_path": Path(arguments.catalogue),
        "catalogue": json.loads(Path(arguments.catalogue).read_text(encoding="utf-8")),
        "beat_kinds": json.loads(Path(arguments.beat_kinds).read_text(encoding="utf-8")),
        "render_plan": json.loads(Path(arguments.render_plan_leg1).read_text(encoding="utf-8")),
        "baseline_render_plan": json.loads(
            Path(arguments.render_plan_baseline).read_text(encoding="utf-8")
        ),
    }
    context["workdir"].mkdir(parents=True, exist_ok=True)

    # Absolute pins, before a single suite runs: a wrong source file cannot be
    # smuggled in by supplying it consistently everywhere.
    motion_digest = hashlib.sha256(context["motion_path"].read_bytes()).hexdigest()
    if motion_digest != CANONICAL_MOTION_TIME_SHA256:
        print(
            f"REFUSED: --motion hashes to {motion_digest}, not the canonical "
            f"Phase 17 source {CANONICAL_MOTION_TIME_SHA256}"
        )
        return 1
    for name, plan in context["shot_plans"].items():
        if plan["source"]["motion_time_sha256"] != CANONICAL_MOTION_TIME_SHA256:
            print(f"REFUSED: shot plan {name!r} binds a clock that is not the canonical source")
            return 1
        if plan["source"]["catalogue_sha256"] != APPROVED_CATALOGUE_SHA256:
            print(f"REFUSED: shot plan {name!r} binds a catalogue that is not the approved one")
            return 1
    supplied_catalogue = _catalogue_digest(context["catalogue"])
    if supplied_catalogue != APPROVED_CATALOGUE_SHA256:
        print(
            f"REFUSED: --catalogue hashes to {supplied_catalogue}, not the approved "
            f"canonical catalogue {APPROVED_CATALOGUE_SHA256}"
        )
        return 1

    # Both plans are validated by the production validator before a suite runs:
    # a gate that composed a world for a plan it had not checked would be
    # proving something about a document nobody vetted.
    for label in ("render_plan", "baseline_render_plan"):
        try:
            render_episode.require_valid_render_plan(context[label])
        except render_episode.PlanRefused as error:
            print(f"REFUSED: {label} is not a valid Episode Render Plan: {error}")
            return 1

    # Every composition source is pinned by raw bytes before anything is built.
    composition_paths = {
        "master_scene_sha256": context["spec_path"],
        "production_world_sha256": context["production_path"],
        "motion_time_sha256": context["motion_path"],
        "population_presence_sha256": context["presence_path"],
        "daily_life_mobility_sha256": context["mobility_path"],
        "state_response_sha256": context["state_response_path"],
    }
    for key, path in sorted(composition_paths.items()):
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        expected = render_episode.APPROVED_COMPOSITION_SOURCES[key]
        if digest != expected:
            print(f"REFUSED: {key} hashes to {digest}, not the approved source {expected}")
            return 1

    render_plan = context["render_plan"]
    profile_digest = render_episode.sha256_hex(
        render_episode.canonical_bytes(render_plan.get("profile"))
    )
    if profile_digest != render_episode.RENDER_PROFILE_SHA256:
        print(
            f"REFUSED: the render plan carries profile {profile_digest}, not the approved "
            f"render profile {render_episode.RENDER_PROFILE_SHA256}"
        )
        return 1
    # The shot plan is identified by its EXACT bytes, and the render plan is then
    # compared against it field by field -- not merely paired with it by digest.
    try:
        render_episode.require_shot_plan_bytes(
            render_plan, context["shot_plan_paths"]["leg1"].read_bytes()
        )
        render_episode.require_plan_matches_shot_plan(render_plan, context["shot_plans"]["leg1"])
        render_episode.require_approved_catalogue(render_plan, context["catalogue"])
        render_episode.require_shot_plan_bytes(
            context["baseline_render_plan"], context["shot_plan_paths"]["baseline"].read_bytes()
        )
        render_episode.require_plan_matches_shot_plan(
            context["baseline_render_plan"], context["shot_plans"]["baseline"]
        )
    except render_episode.PlanRefused as error:
        print(f"REFUSED: {error}")
        return 1

    leg1_digest = render_episode.sha256_hex(
        render_episode.canonical_bytes(context["shot_plans"]["leg1"])
    )
    if render_plan["source"]["shot_plan_sha256"] != leg1_digest:
        print(
            "REFUSED: the render plan was built for a different shot direction plan than the "
            "one supplied"
        )
        return 1

    context["spec"] = build_master_scene.build_master_scene(context["spec_path"])

    per_phase: dict = {}
    executed, failures = run_suites(LOCKED_SUITES, context, per_phase)

    if failures == 0:
        # Phase 23's own suite needs the world a production render photographs:
        # composed by the production composer, directed by Phase 22's applier,
        # and censused before anything claims to have rendered it.
        import bpy

        expected = episode_scene.compose_episode_world(
            spec_path=context["spec_path"],
            production_path=context["production_path"],
            motion_path=context["motion_path"],
            presence_path=context["presence_path"],
            mobility_path=context["mobility_path"],
            state_response_path=context["state_response_path"],
            before_path=context["before_path"],
            after_path=context["mid_path"],
        )
        census = episode_scene.census_composed_world(bpy, expected)
        print(f"LD_P23_COMPOSITION {json.dumps(census, sort_keys=True)}")
        episode_scene.direct_episode_world(bpy, context["shot_plans"]["leg1"], context["catalogue"])
        ran, failed = run_suites((("phase23", (test_episode_render,)),), context, per_phase)
        executed += ran
        failures += failed

    for phase, (ran, failed) in per_phase.items():
        print(f"LD_BLENDER_TESTS_{phase.upper()}: {ran - failed} passed, {failed} failed")
    print(f"LD_BLENDER_TESTS_P23: {executed - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
