"""V2 temporal collision evidence CLI (thin shell over the shared core).

This file is the command-line shell for the V2 temporal collision verifier. It
composes the real V2 world exactly the way ``verify_traffic_runtime.py`` (and
``test_mobility_traffic_v2.py::_prepare``) does, then runs the collision sweep
-- but ALL collision mathematics lives in ONE shared module,
``visual/blender/scripts/collision_core_v2.py``, which this shell re-exports
and the tests import directly. No collision maths is defined in this file: the
sweep, the open/loop sampling and the distance profile are
``collision_core_v2``'s, and the names below are re-exported so any existing
importer of this module keeps working unchanged.

This tool is READ-ONLY: it never asserts, coerces or repairs -- a real
collision is a finding to report, not something to fix by moving things.

bpy-freedom
-----------
The shell imports only pure-Python planning modules; the shared core never
imports ``bpy`` (or ``living_diorama``). The script runs under the repo venv
WITHOUT Blender installed.

Usage::

    python visual/blender/tools/verify_traffic_collisions_v2.py \
        --export /path/to/render_export_before.json \
        --motion-time visual/blender/config/motion_time_director_v4.json \
        --out collisions_v2.json --rows-out collisions_v2_rows.json

``--export`` is REQUIRED (the same real Phase 19/20 render export the sibling
tool and the test require). ``--motion-time`` defaults to ``motion_time_v1.json``
and should be ``motion_time_director_v4.json`` to run under the Director V4
clock. ``--out`` writes the main evidence JSON, ``--rows-out`` writes the full
per-row detail JSON. Nothing else is written and nothing is mutated.
"""

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TOOLS_DIR.parent / "scripts"
CONFIG_DIR = TOOLS_DIR.parent / "config"

# The pure-Python planner package lives in scripts/, and the shared collision
# core (collision_core_v2.py) sits beside it, importing its siblings by plain
# name. This module-level insertion makes that import work, exactly as
# verify_traffic_runtime.py:103-104 does for its own imports.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# The shared collision core: the ONE implementation of the V2 temporal
# collision mathematics. The names are re-exported so existing importers of
# this module keep working; the core itself never imports bpy.
from collision_core_v2 import (  # noqa: E402
    verify_v2_collisions,
)

_CONFIG_FILES = (
    "master_scene_v1.json",
    "production_world_v1.json",
    "population_presence_v1.json",
    "daily_life_mobility_v1.json",
)


def _sha256(path: Path) -> str:
    """SHA-256 of one input file, so the evidence is traceable to exact bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_record(path: Path) -> dict:
    return {"path": str(path), "sha256": _sha256(path)}


# ---------------------------------------------------------------------------
# World composition (mirrors verify_traffic_runtime.py, lines 103-162)
# ---------------------------------------------------------------------------


def compose_and_verify(
    config_dir: Path,
    scripts_dir: Path,
    motion_time_path: Path,
    export_path: Path,
) -> dict:
    """Compose the real V2 world and run the shared V2 temporal collision sweep."""
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

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

    config_dir = Path(config_dir)
    motion_time_path = Path(motion_time_path)
    export_path = Path(export_path)
    if not export_path.is_file():
        raise FileNotFoundError(
            f"the real render export {export_path} is required (run the Phase "
            "19/20 pipeline first, or pass --export <path>)"
        )

    # --- Step 1: configs + resolved timeline -------------------------------
    master = load_master_scene_spec(config_dir / "master_scene_v1.json")
    production = load_production_world_spec(config_dir / "production_world_v1.json")
    presence_spec = load_population_presence_spec(config_dir / "population_presence_v1.json")
    spec = load_daily_life_mobility_spec(config_dir / "daily_life_mobility_v1.json")
    motion_time = load_motion_time_spec(motion_time_path)
    timeline = resolve_mobility_timeline(spec, motion_time["timeline"])

    # --- Steps 2-3: world graph, fabric, presence ---------------------------
    graph = build_road_graph(master, production)
    fabric = plan_urban_fabric(master, production, graph)
    topology = topo.plan_pedestrian_topology(master, production, graph, fabric, presence_spec)
    export = load_render_export(export_path)
    presence = pres.plan_population_presence(export, master, presence_spec, topology)

    # --- Steps 4-5: the shipped V2 world ------------------------------------
    # The final render runs --mobility-profile v2 (the v1 pedestrian planner
    # refuses this crowd) and traffic_profile="v2"; compose exactly that.
    plan_default = mp.plan_daily_life_mobility(
        presence,
        presence_spec,
        spec,
        timeline,
        master,
        production,
        graph,
        fabric,
        mobility_profile="v2",
    )
    vehicles_v2 = mp.plan_vehicle_mobility(
        spec, timeline, master, graph, fabric, traffic_profile="v2"
    )
    plan_v2 = {**plan_default, "vehicles": vehicles_v2}

    # --- Step 6: the V2 temporal collision sweep (no mobility_collisions --
    # --- that proof is V1-shaped and cannot run on open V2 pedestrians) -----
    result = verify_v2_collisions(plan_v2, timeline, presence, spec)
    collision = result["collision"]
    rows = result["rows"]
    summary = result["summary"]

    evidence = {
        "verifier": {
            "name": "verify_traffic_collisions_v2",
            "read_only": True,
            "bpy_free": True,
            "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "mirrors_world_composition": "verify_traffic_runtime.py lines 103-162",
            "mirrors_collision_contract": "mobility_plan.mobility_collisions (lines 768-921)",
            "trajectory_laws": "v2",
            "collision_core": "visual/blender/scripts/collision_core_v2.py",
        },
        "inputs": {
            "config_dir": str(config_dir),
            "config_files": [_digest_record(config_dir / name) for name in _CONFIG_FILES],
            "motion_time": _digest_record(motion_time_path),
            "motion_time_timeline": dict(sorted(motion_time["timeline"].items())),
            "resolved_mobility_timeline": dict(sorted(timeline.items())),
            "render_export": _digest_record(export_path),
        },
        "collision": collision,
        "summary": summary,
        "rows": rows,
        "conclusion": {
            "collision_safe": collision["safe"],
            "collision_violation_count": summary["collision_violation_count"],
            "frames_sampled": collision["frames_sampled"],
            "closest": collision["closest"],
            "required": collision["required"],
        },
    }
    return evidence


def main(argv: list[str] | None = None) -> int:
    """Compose the real V2 world, sweep it temporally, and emit the evidence."""
    parser = argparse.ArgumentParser(
        description=(
            "Read-only V2 temporal collision verifier: real world in, V2 "
            "collision evidence out (no bpy, no mutation of the world)."
        )
    )
    parser.add_argument("--config-dir", type=Path, default=CONFIG_DIR)
    parser.add_argument("--scripts-dir", type=Path, default=SCRIPTS_DIR)
    parser.add_argument(
        "--motion-time",
        type=Path,
        default=CONFIG_DIR / "motion_time_v1.json",
        help="motion-time spec file; default motion_time_v1.json, or pass "
        "motion_time_director_v4.json for the Director V4 clock",
    )
    parser.add_argument(
        "--export",
        type=Path,
        default=Path.cwd() / "render_export_before.json",
        help="the real render export (required; default ./render_export_before.json)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="optional path to write the main evidence JSON; stdout by default",
    )
    parser.add_argument(
        "--rows-out",
        type=Path,
        default=None,
        help="optional path to write the full per-row detail JSON",
    )
    args = parser.parse_args(argv)

    motion_time_path = Path(args.motion_time)
    if not motion_time_path.is_absolute() and not motion_time_path.is_file():
        motion_time_path = Path(args.config_dir) / motion_time_path

    evidence = compose_and_verify(
        config_dir=args.config_dir,
        scripts_dir=args.scripts_dir,
        motion_time_path=motion_time_path,
        export_path=args.export,
    )

    text = json.dumps(evidence, indent=2, sort_keys=True)
    print(text)
    if args.out is not None:
        out = Path(args.out)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"evidence written to {out}", file=sys.stderr)
    if args.rows_out is not None:
        rows_path = Path(args.rows_out)
        rows_text = json.dumps(
            {"rows": evidence["rows"], "summary": evidence["summary"]}, indent=2, sort_keys=True
        )
        rows_path.write_text(rows_text + "\n", encoding="utf-8")
        print(f"rows written to {rows_path}", file=sys.stderr)

    conclusion = evidence["conclusion"]
    print(
        f"LD_TRAFFIC_COLLISIONS_V2: collision_safe={conclusion['collision_safe']} "
        f"violations={conclusion['collision_violation_count']} "
        f"frames={conclusion['frames_sampled']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
