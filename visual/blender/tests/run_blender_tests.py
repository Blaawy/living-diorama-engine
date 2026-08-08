"""In-Blender structural test runner for the Phase 15 master scene.

Runs inside ``blender --background --factory-startup`` where ``bpy`` exists;
ordinary pytest never imports this. The runner builds the master scene once,
then executes every ``test_*`` function from the Phase 15 test modules in
definition order, passing a shared context. Any failure prints the traceback
and the process exits nonzero -- Blender failures are never hidden.

Usage::

    blender --background --factory-startup --python run_blender_tests.py -- \
        --spec master_scene_v1.json --before before.json --after after.json \
        --workdir <scratch dir>
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
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--workdir", required=True)
    arguments = parser.parse_args(argv)

    require_supported_blender()
    context = {
        "spec_path": Path(arguments.spec),
        "before_path": Path(arguments.before),
        "after_path": Path(arguments.after),
        "workdir": Path(arguments.workdir),
    }
    # Test 1 of the structural contract: the master scene builds without
    # exception. Everything else runs against this build.
    context["spec"] = build_master_scene.build_master_scene(context["spec_path"])

    failures = 0
    executed = 0
    for module in (test_master_scene, test_apply_render_export):
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
    print(f"LD_BLENDER_TESTS: {executed - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
