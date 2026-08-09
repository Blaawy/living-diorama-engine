"""In-Blender structural test runner for Phase 16 (superset of Phase 15).

Runs inside ``blender --background --factory-startup`` where ``bpy`` exists;
ordinary pytest never imports this. The runner builds the master scene once,
executes every Phase 15 structural test unchanged (proving V1 compatibility
in the presence of the Phase 16 code), then executes the production-world
tests, which add the production city onto the freshly rebuilt founding scene
and prove it changes nothing it must not change.

Usage::

    blender --background --factory-startup --python run_blender_tests_p16.py \
        -- --spec master_scene_v1.json --production production_world_v1.json \
        --before before.json --after after.json --workdir <scratch dir>
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
import test_production_world  # noqa: E402
from blender_runtime import require_supported_blender  # noqa: E402


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
    """Build the scene, run every structural test, report, and exit."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--production", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--workdir", required=True)
    arguments = parser.parse_args(argv)

    require_supported_blender()
    context = {
        "spec_path": Path(arguments.spec),
        "production_path": Path(arguments.production),
        "before_path": Path(arguments.before),
        "after_path": Path(arguments.after),
        "workdir": Path(arguments.workdir),
    }
    context["workdir"].mkdir(parents=True, exist_ok=True)
    context["spec"] = build_master_scene.build_master_scene(context["spec_path"])

    failures = 0
    executed = 0
    for module in (test_master_scene, test_apply_render_export, test_production_world):
        for function in collect(module):
            executed += 1
            label = f"{module.__name__}.{function.__name__}"
            try:
                function(context)
            except Exception:
                failures += 1
                print(f"FAIL {label}")
                traceback.print_exc()
            else:
                print(f"ok   {label}")
    print(f"LD_BLENDER_TESTS_P16: {executed - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
