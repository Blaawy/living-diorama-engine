"""In-Blender structural test runner for Phase 19 (superset of Phase 18).

Runs inside ``blender --background --factory-startup`` where ``bpy`` exists;
ordinary pytest never imports this. The order is the contract: the LOCKED
Phase 15 suite runs first against the freshly rebuilt founding scene, then the
LOCKED Phase 16 production suite over the city it builds, then the LOCKED
Phase 17 motion suite, then the LOCKED Phase 18 population suite, and only then
the Phase 19 mobility suite. Movement can therefore never be made to pass by
weakening anything that came before it.

Usage::

    blender --background --factory-startup --python run_blender_tests_p19.py \
        -- --spec master_scene_v1.json --production production_world_v1.json \
        --motion motion_time_v1.json --presence population_presence_v1.json \
        --mobility daily_life_mobility_v1.json \
        --before before.json --mid mid.json --after after.json --workdir <scratch dir>
"""

import argparse
import sys
import traceback
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
for directory in (str(TESTS_DIR), str(SCRIPTS_DIR)):
    if directory not in sys.path:
        sys.path.insert(0, directory)

import build_master_scene  # noqa: E402
import test_apply_render_export  # noqa: E402
import test_master_scene  # noqa: E402
import test_mobility  # noqa: E402
import test_motion_time  # noqa: E402
import test_population_presence  # noqa: E402
import test_production_world  # noqa: E402
from blender_runtime import require_supported_blender  # noqa: E402

SUITES = (
    ("phase15", (test_master_scene, test_apply_render_export)),
    ("phase16", (test_production_world,)),
    ("phase17", (test_motion_time,)),
    ("phase18", (test_population_presence,)),
    ("phase19", (test_mobility,)),
)


def collect(module) -> list:
    """Return the module's test functions in definition order."""
    functions = [
        value
        for name, value in vars(module).items()
        if name.startswith("test_") and callable(value)
    ]
    functions.sort(key=lambda function: function.__code__.co_firstlineno)
    return functions


def main() -> int:
    """Build the scene, run every structural test in phase order, and exit."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--production", required=True)
    parser.add_argument("--motion", required=True)
    parser.add_argument("--presence", required=True)
    parser.add_argument("--mobility", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--mid", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--workdir", required=True)
    arguments = parser.parse_args(argv)

    require_supported_blender()
    context = {
        "spec_path": Path(arguments.spec),
        "production_path": Path(arguments.production),
        "motion_path": Path(arguments.motion),
        "presence_path": Path(arguments.presence),
        "mobility_path": Path(arguments.mobility),
        "before_path": Path(arguments.before),
        "mid_path": Path(arguments.mid),
        "after_path": Path(arguments.after),
        "workdir": Path(arguments.workdir),
    }
    context["workdir"].mkdir(parents=True, exist_ok=True)
    context["spec"] = build_master_scene.build_master_scene(context["spec_path"])

    failures = 0
    executed = 0
    per_phase: dict[str, list[int]] = {}
    for phase, modules in SUITES:
        counts = per_phase.setdefault(phase, [0, 0])
        for module in modules:
            for function in collect(module):
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
    for phase, (ran, failed) in per_phase.items():
        print(f"LD_BLENDER_TESTS_{phase.upper()}: {ran - failed} passed, {failed} failed")
    print(f"LD_BLENDER_TESTS_P19: {executed - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
