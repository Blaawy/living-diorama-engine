"""Read-only traffic runtime verifier: real world in, real traffic evidence out.

A single, additive, READ-ONLY tool that composes the real EP1 world exactly the
way ``visual/blender/tests/test_mobility_traffic_v2.py::_prepare`` does and
emits the REAL traffic numbers as JSON. It exists to give the final handoff
evidence for claims like "14 vehicles / 2 routes" -- it never asserts, coerces
or hard-codes either figure; it reports what the plan actually holds.

The call sequence mirrors the test's ``_prepare`` helper (lines 79-157 of
``test_mobility_traffic_v2.py``), including the step whose absence crashed the
old evidence script: the caller must attach the collision proof itself

    plan_v2["collision"] = mp.mobility_collisions(plan_v2, timeline, presence, spec)

before handing the plan to ``mobility_traffic_v2.traffic_v2_metrics``, which
reads ``plan["collision"]["failures"]``. This script does exactly that; it does
NOT redesign or re-implement any planning, routing or rendering logic.

bpy-freedom: this script imports only pure-Python planning modules
(``mobility_plan``, ``mobility_traffic_v2``, ``mobility_spec``,
``motion_time_spec``, ``population_presence_spec``,
``population_presence_plan``, ``production_spec``, ``road_graph``,
``scene_spec``, ``urban_fabric``, ``pedestrian_topology`` -- plus their
transitive imports ``pedestrian_mobility``, ``pedestrian_mobility_v2``,
``vehicle_kit``, ``vehicle_lane_network``, ``spatial_occupancy``). None of
those modules imports ``bpy`` (the only modules in ``scripts/`` that import
``bpy`` are the ``apply_*``, ``build_*``, ``produce_*``, ``render_*`` and
``blender_runtime`` modules, which this script never touches). The script runs
under the repo venv WITHOUT Blender installed.

Usage::

    python visual/blender/tools/verify_traffic_runtime.py \
        --export /path/to/render_export_before.json \
        [--motion-time motion_time_director_v4.json] \
        [--config-dir visual/blender/config] \
        [--out traffic_runtime_evidence.json]

``--export`` is REQUIRED: it is the real Phase 19/20 render export that
``plan_population_presence`` needs (the same file the test requires).
``--motion-time`` defaults to ``motion_time_v1.json``; pass
``motion_time_director_v4.json`` to run under the Director V4 clock.

The evidence JSON is printed to stdout; pass ``--out PATH`` to also write it to
a file. Nothing else is written, and nothing in the world, the configs or the
plans is mutated.
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


def _sampled_frames(timeline: dict) -> list[int]:
    """The exact frame list the collision proof sweeps (see mobility_plan.py)."""
    start = int(timeline["start_frame"])
    end = int(timeline["end_frame"])
    stride = int(timeline["collision_frame_stride"])
    frames = list(range(start, end + 1, stride))
    if frames[-1] != end:
        frames.append(end)
    return frames


def verify_traffic_runtime(
    config_dir: Path,
    scripts_dir: Path,
    motion_time_path: Path,
    export_path: Path,
) -> dict:
    """Compose the real world and return the real traffic evidence document.

    Mirrors ``_prepare`` in ``visual/blender/tests/test_mobility_traffic_v2.py``
    (lines 79-157): same configs, same timeline resolution, same presence
    pipeline, same ``plan_daily_life_mobility`` -> ``plan_vehicle_mobility``
    (``traffic_profile="v2"``) -> ``mobility_collisions`` -> ``traffic_v2_metrics``
    chain. Read-only: every planner is a pure function of its inputs and nothing
    here writes to the world, the configs or the plans.
    """
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    # All of these are pure-Python planners; none imports ``bpy`` (see module
    # docstring for the verified list).
    import mobility_plan as mp
    import mobility_traffic_v2 as v2
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

    # --- Steps 4-6: default plan, V2 vehicles, V2 collision proof -----------
    # The final render runs --mobility-profile v2; the v1 pedestrian planner
    # refuses this crowd (13 of 24), so the verifier must compose the same
    # world the render actually composes.
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
    # THE step whose absence crashed the old evidence script: the metrics
    # function reads plan["collision"]["failures"], so the caller must attach
    # the REAL collision proof before calling it. No assertion -- the proof is
    # simply computed and reported as it comes out.
    # The collision proof is V1-shaped: _mover_tracks reads each pedestrian's
    # "cycles", which the V2 open-trajectory pedestrian document does not carry.
    # The shipped world runs V2 pedestrians, so for THIS world the proof cannot
    # be computed. That is reported honestly rather than faked with a zero.
    collision_proof: dict[str, object]
    try:
        plan_v2["collision"] = mp.mobility_collisions(plan_v2, timeline, presence, spec)
        collision_proof = {
            "available": True,
            "safe": bool(plan_v2["collision"].get("safe")),
            "failure_count": len(plan_v2["collision"]["failures"]),
        }
    except Exception as error:  # noqa: BLE001 -- the reason is the evidence
        plan_v2["collision"] = {"failures": []}
        collision_proof = {
            "available": False,
            "reason": f"{type(error).__name__}: {error}",
            "explanation": (
                "mobility_collisions() is V1-shaped (it reads each pedestrian's "
                "'cycles'); the shipped world uses the V2 open-trajectory "
                "pedestrian document, which has no cycles. Pre-existing "
                "limitation, unrelated to the camera/fog revision."
            ),
        }

    # --- Step 7: the full V2 metrics document --------------------------------
    metrics = v2.traffic_v2_metrics(plan_v2)
    if not collision_proof["available"]:
        # Every other metric reads plan["vehicles"] only and is real; this one
        # field would be a fabricated zero, so it is nulled out explicitly.
        metrics["collision_violation_count"] = None

    vehicles = plan_v2["vehicles"]["vehicles"]
    circuits = plan_v2["vehicles"]["circuits"]

    # --- Forward motion: speed > 0 and strictly increasing sampled arc -------
    # Sampled arc distance is the number the collision proof and the Blender
    # side actually use: arc_fraction * L * (frame - start) / span (see
    # test_v2_motion_is_continuous_and_strictly_forward and _mover_tracks).
    frames = _sampled_frames(timeline)
    span = float(timeline["frame_span"])
    start = int(timeline["start_frame"])
    forward_pass = 0
    forward_failures: list[dict] = []
    forward_per_vehicle: list[dict] = []
    for vehicle in vehicles:
        length = float(vehicle["route_length"])
        arc = float(vehicle["presentation_arc_fraction"])
        speed = float(vehicle["speed"])
        distances = [arc * length * (frame - start) / span for frame in frames]
        strictly_increasing = all(
            later > earlier for earlier, later in zip(distances, distances[1:], strict=True)
        )
        speed_positive = speed > 0.0
        steps = [later - earlier for earlier, later in zip(distances, distances[1:], strict=True)]
        record = {
            "slot": vehicle["slot"],
            "circuit": vehicle["circuit"],
            "speed": round(speed, 6),
            "speed_positive": speed_positive,
            "presentation_arc_fraction": arc,
            "arc_distance": float(vehicle["arc_distance"]),
            "route_length": length,
            "sampled_frames": len(distances),
            "first_arc_distance": round(distances[0], 6),
            "last_arc_distance": round(distances[-1], 6),
            "min_step": round(min(steps), 6) if steps else 0.0,
            "max_step": round(max(steps), 6) if steps else 0.0,
            "strictly_increasing": strictly_increasing,
            "forward_ok": speed_positive and strictly_increasing,
        }
        forward_per_vehicle.append(record)
        if record["forward_ok"]:
            forward_pass += 1
        else:
            forward_failures.append(
                {
                    "slot": vehicle["slot"],
                    "reason": "speed not positive"
                    if not speed_positive
                    else "arc distance not strictly increasing",
                }
            )

    # --- Visible loop status: bounded, non-repeating presentation ------------
    loop_pass = 0
    loop_failures: list[dict] = []
    loop_per_vehicle: list[dict] = []
    for vehicle in vehicles:
        fraction = float(vehicle["presentation_arc_fraction"])
        arc_distance = float(vehicle["arc_distance"])
        route_length = float(vehicle["route_length"])
        fraction_lt_one = fraction < 1.0
        arc_lt_route = arc_distance < route_length
        ok = fraction_lt_one and arc_lt_route
        loop_per_vehicle.append(
            {
                "slot": vehicle["slot"],
                "circuit": vehicle["circuit"],
                "presentation_arc_fraction": fraction,
                "fraction_lt_one": fraction_lt_one,
                "arc_distance": arc_distance,
                "route_length": route_length,
                "arc_lt_route_length": arc_lt_route,
                "visible_loop_ok": ok,
            }
        )
        if ok:
            loop_pass += 1
        else:
            loop_failures.append(
                {
                    "slot": vehicle["slot"],
                    "reason": "presentation_arc_fraction >= 1.0"
                    if not fraction_lt_one
                    else "arc_distance >= route_length",
                }
            )

    # --- Real numbers, reported as they come out -----------------------------
    vehicle_count = len(vehicles)
    route_count = len(circuits)
    collision = plan_v2["collision"]
    collision_failure_count = len(collision["failures"]) if collision_proof["available"] else None

    evidence = {
        "verifier": {
            "name": "verify_traffic_runtime",
            "read_only": True,
            "bpy_free": True,
            "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "mirrors": "test_mobility_traffic_v2.py::_prepare (lines 79-157)",
        },
        "inputs": {
            "config_dir": str(config_dir),
            "config_files": [_digest_record(config_dir / name) for name in _CONFIG_FILES],
            "motion_time": _digest_record(motion_time_path),
            "motion_time_timeline": dict(sorted(motion_time["timeline"].items())),
            "resolved_mobility_timeline": dict(sorted(timeline.items())),
            "render_export": _digest_record(export_path),
        },
        "traffic": {
            "vehicle_count": vehicle_count,
            "route_count": route_count,
            "declared_target_count": int(plan_v2["vehicles"]["target_count"]),
            "capacity": int(plan_v2["vehicles"]["capacity"]),
            "driving_side": plan_v2["vehicles"]["driving_side"],
            "circuits": [
                {
                    "circuit": entry["circuit"],
                    "direction": entry["direction"],
                    "length": entry["length"],
                    "speed": entry["speed"],
                    "capacity": entry["capacity"],
                }
                for entry in circuits
            ],
            "vehicles": [
                {
                    "slot": entry["slot"],
                    "circuit": entry["circuit"],
                    "circuit_index": entry["circuit_index"],
                    "phase": entry["phase"],
                    "archetype": entry["archetype"],
                    "speed": entry["speed"],
                    "route_length": entry["route_length"],
                    "presentation_arc_fraction": entry["presentation_arc_fraction"],
                    "arc_distance": entry["arc_distance"],
                }
                for entry in vehicles
            ],
        },
        "forward_motion": {
            "pass_count": forward_pass,
            "total_count": len(vehicles),
            "failures": forward_failures,
            "per_vehicle": forward_per_vehicle,
        },
        "collision_safe": collision.get("safe") if collision_proof["available"] else None,
        "collision_failure_count": collision_failure_count,
        "collision_proof": collision_proof,
        "visible_loop_status": {
            "pass_count": loop_pass,
            "total_count": len(vehicles),
            "failures": loop_failures,
            "per_vehicle": loop_per_vehicle,
        },
        "traffic_v2_metrics": metrics,
        "conclusion": {
            # The REAL runtime figures, reported without asserting either one.
            # "14 vehicles" is statically declared (target_count); "N routes" is
            # a runtime exact-search result and is only what the plan says.
            "reported_claim": f"{vehicle_count} vehicles / {route_count} routes",
            "vehicle_count": vehicle_count,
            "route_count": route_count,
            "collision_safe": collision.get("safe") if collision_proof["available"] else None,
            "collision_failure_count": collision_failure_count,
            "forward_motion_pass": f"{forward_pass}/{len(vehicles)}",
            "visible_loop_pass": f"{loop_pass}/{len(vehicles)}",
        },
    }
    return evidence


def main(argv: list[str] | None = None) -> int:
    """Compose the real world, verify traffic, and emit the evidence JSON."""
    parser = argparse.ArgumentParser(
        description=(
            "Read-only traffic runtime verifier: real world in, real traffic "
            "evidence JSON out (no bpy, no mutation of the world)."
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
        help="optional path to write the evidence JSON; stdout by default",
    )
    args = parser.parse_args(argv)

    motion_time_path = Path(args.motion_time)
    if not motion_time_path.is_absolute() and not motion_time_path.is_file():
        motion_time_path = Path(args.config_dir) / motion_time_path

    evidence = verify_traffic_runtime(
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

    conclusion = evidence["conclusion"]
    print(
        f"LD_TRAFFIC_RUNTIME: {conclusion['reported_claim']} "
        f"collision_safe={conclusion['collision_safe']} "
        f"collision_failure_count={conclusion['collision_failure_count']} "
        f"forward_motion={conclusion['forward_motion_pass']} "
        f"visible_loop={conclusion['visible_loop_pass']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
