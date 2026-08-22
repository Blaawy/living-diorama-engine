"""In-Blender structural test runner for Phase 22 (superset of Phase 20).

Runs inside ``blender --background --factory-startup`` where ``bpy`` exists;
ordinary pytest never imports this. The order is the contract: the LOCKED
Phase 15 suite runs first against the freshly rebuilt founding scene, then the
LOCKED Phase 16 production suite over the city it builds, then the LOCKED
Phase 17 motion suite, then the LOCKED Phase 18 population suite, then the
LOCKED Phase 19 mobility suite, then the LOCKED Phase 20 state-response suite,
and only then the Phase 22 cinematic suite. Direction can therefore never be
made to pass by weakening anything that came before it.

After a fully passing run, ``--proof-dir`` renders real Cycles proof frames
through the marker-driven camera cuts: the scene is stepped to each shot's
frames, Blender's own active camera is asserted against the plan, and the frame
is rendered through it -- so the proof images are what the direction actually
produces, not an illustration of it.

Usage::

    blender --background --factory-startup --python run_blender_tests_p22.py \
        -- --spec master_scene_v1.json --production production_world_v1.json \
        --motion motion_time_v1.json --presence population_presence_v1.json \
        --mobility daily_life_mobility_v1.json \
        --state-response state_response_v1.json \
        --before before.json --mid mid.json --after after.json \
        --shot-plan-baseline plan0.json --shot-plan-leg1 plan01.json \
        --shot-plan-leg2 plan12.json --catalogue catalogue.json \
        --beat-kinds beat_kinds.json \
        --workdir <scratch dir> [--proof-dir <proof dir>]
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
import test_apply_render_export  # noqa: E402
import test_cinematic_direction  # noqa: E402
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

SUITES = (
    ("phase15", (test_master_scene, test_apply_render_export)),
    ("phase16", (test_production_world,)),
    ("phase17", (test_motion_time,)),
    ("phase18", (test_population_presence,)),
    ("phase19", (test_mobility,)),
    ("phase20", (test_state_response,)),
    ("phase22", (test_cinematic_direction,)),
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


def camera_for_frame(plan: dict, frame: int) -> str:
    """The planned anchor for one frame, straight from the shot table."""
    for shot in plan["shots"]:
        if shot["start_frame"] <= frame <= shot["end_frame"]:
            return shot["camera_anchor_id"]
    raise RuntimeError(f"frame {frame} lies outside the plan's shots")


def proof_frames(plan: dict) -> list:
    """The frames one plan's visual proof renders: both ends, each shot's middle."""
    timeline = plan["timeline"]
    frames = {timeline["start_frame"], timeline["end_frame"]}
    for shot in plan["shots"]:
        frames.add((shot["start_frame"] + shot["end_frame"]) // 2)
    return sorted(frames)


def compose_full_world(context: dict, before_path: Path, after_path: Path) -> dict:
    """Stand every locked prior layer on one transition world, in phase order.

    ``build_motion_scene`` wipes and rebuilds Phases 15-17 (it calls
    ``build_master_scene``, which clears the LD collections), so it runs first
    and exactly once; Phases 18, 19 and 20 are additive -- each clears only its
    own prefix -- and are applied with their own locked planners and appliers,
    with the same arguments their own structural suites use. Nothing here
    reimplements a prior layer's logic; every call below is quoted from the
    locked suites' own preparation code.

    The Phase 20 static layer is applied from the leg's AFTER export -- memory
    only grows, so the after state is the superset every motion endpoint needs
    -- and the Phase 20 transition curves are then written over it.
    """
    import apply_mobility as mobility
    import apply_motion_plan as motion
    import apply_population_presence as population
    import apply_state_response as state_response
    import apply_state_response_motion as state_response_motion
    import mobility_plan as mobility_planner
    import pedestrian_topology as topology_planner
    import population_presence_plan as presence_planner
    import road_graph
    import state_response_motion_plan
    import state_response_plan
    import urban_fabric
    from mobility_spec import load_daily_life_mobility_spec, resolve_mobility_timeline
    from motion_time_spec import load_motion_time_spec
    from population_presence_spec import load_population_presence_spec
    from production_spec import load_production_world_spec
    from scene_spec import load_master_scene_spec, load_render_export
    from state_response_spec import load_state_response_spec, resolve_state_response_timeline

    style = test_cinematic_direction.STYLE
    master = load_master_scene_spec(context["spec_path"])
    production = load_production_world_spec(context["production_path"])
    motion_timeline = load_motion_time_spec(context["motion_path"])["timeline"]

    graph = road_graph.build_road_graph(master, production)
    fabric = urban_fabric.plan_urban_fabric(master, production, graph)
    presence_spec = load_population_presence_spec(context["presence_path"])
    topology = topology_planner.plan_pedestrian_topology(
        master, production, graph, fabric, presence_spec
    )
    export_before = load_render_export(before_path)
    export_after = load_render_export(after_path)
    presence = presence_planner.plan_population_presence(
        export_before, master, presence_spec, topology
    )

    mobility_spec = load_daily_life_mobility_spec(context["mobility_path"])
    mobility_timeline = resolve_mobility_timeline(mobility_spec, motion_timeline)
    daily_life = mobility_planner.plan_daily_life_mobility(
        presence,
        presence_spec,
        mobility_spec,
        mobility_timeline,
        master,
        production,
        graph,
        fabric,
    )

    sr_spec = load_state_response_spec(context["state_response_path"])
    sr_timeline = resolve_state_response_timeline(sr_spec, motion_timeline)
    sr_before = state_response_plan.plan_state_response(export_before, master, sr_spec)
    sr_after = state_response_plan.plan_state_response(export_after, master, sr_spec)
    sr_motion = state_response_motion_plan.plan_state_response_motion(
        sr_before, sr_after, sr_spec, sr_timeline
    )

    motion.build_motion_scene(
        context["spec_path"],
        context["production_path"],
        before_path,
        after_path,
        context["motion_path"],
        style=style,
    )
    population.apply_population_presence(presence, presence_spec)
    mobility.apply_mobility(daily_life, mobility_spec)
    state_response.apply_state_response(sr_after, sr_spec)
    state_response_motion.apply_state_response_motion(sr_motion, sr_timeline)
    responses = sr_after["responses"]
    return {
        "expected_proxies": len(presence["proxies"]),
        "expected_vehicles": daily_life["vehicles"]["count"],
        "expected_air": sum(1 for entry in responses if entry["channel"] == "district_air"),
        "expected_stones": sum(1 for entry in responses if entry["channel"] == "memory_record"),
    }


def verify_composition(bpy, label: str, expected: dict) -> dict:
    """Prove the prior layers actually stand in the proof scene, by exact census.

    The expectations come from the very plans the composition applied -- so
    many proxies, so many vehicles, so many strata and stones -- and the scene
    must hold exactly those counts. A half-built world (five of eighty proxies,
    one of fourteen vehicles) is refused, not merely a missing one; a frame of
    the wrong world can never exist.
    """
    names = [obj.name for obj in bpy.data.objects]
    proxies = sum(1 for name in names if name.startswith("LD_POP__"))
    vehicles = sum(1 for name in names if name.startswith("LD_VEH__") and "__wheel_" not in name)
    air = sum(1 for name in names if name.startswith("LD_SR__air_"))
    stones = sum(1 for name in names if name.startswith("LD_SR__record_stone_"))
    mobility_actions = sum(
        1 for action in bpy.data.actions if action.name.startswith("LD_MOBILITY__")
    )
    response_actions = sum(
        1 for action in bpy.data.actions if action.name.startswith("LD_STATE_RESPONSE__")
    )
    census = {
        "population_proxies": proxies,
        "mobility_vehicle_bodies": vehicles,
        "mobility_actions": mobility_actions,
        "state_response_air_strata": air,
        "state_response_record_stones": stones,
        "state_response_actions": response_actions,
        "expected": dict(expected),
    }
    problems = []
    if proxies != expected["expected_proxies"]:
        problems.append(f"{proxies} Phase 18 proxies, plan placed {expected['expected_proxies']}")
    if vehicles != expected["expected_vehicles"]:
        problems.append(
            f"{vehicles} Phase 19 vehicle bodies, plan drives {expected['expected_vehicles']}"
        )
    if mobility_actions < 1:
        problems.append("Phase 19 mobility curves absent")
    if air != expected["expected_air"]:
        problems.append(f"{air} Phase 20 air strata, plan carries {expected['expected_air']}")
    if stones != expected["expected_stones"]:
        problems.append(
            f"{stones} Phase 20 record stones, plan carries {expected['expected_stones']}"
        )
    if response_actions < 1:
        problems.append("Phase 20 transition curves absent")
    if problems:
        raise RuntimeError(f"{label}: composed world incomplete: {problems}")
    return census


def verify_beat_targets(bpy, plan: dict, beat_kinds: dict, frame: int, camera_name: str) -> list:
    """Name what each beat shot is supposed to reveal, and prove it is there.

    For the frame's shot, every cited beat kind maps to a concrete prior-layer
    target; presence in the scene, presence inside the active camera's view
    cone, and an unoccluded ray from the camera are checked where the target is
    a discrete object. Symbolic framing is never accepted as proof of the
    response itself -- the record stones are verified as stones, not inferred
    from the Seal being in shot.
    """
    import math

    shot = next(s for s in plan["shots"] if s["start_frame"] <= frame <= s["end_frame"])
    targets = []
    camera = bpy.data.objects[camera_name]
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    origin = camera.matrix_world.translation
    matrix = camera.matrix_world
    forward = tuple(-matrix.col[2][i] for i in range(3))
    right = tuple(matrix.col[0][i] for i in range(3))
    upward = tuple(matrix.col[1][i] for i in range(3))
    half_h = math.atan(camera.data.sensor_width / (2.0 * camera.data.lens))
    render_aspect = scene.render.resolution_y / scene.render.resolution_x
    half_v = math.atan(camera.data.sensor_width * render_aspect / (2.0 * camera.data.lens))

    def frustum_and_ray(target_object) -> dict:
        """The full test: rendered at this frame, inside the FRAME, unoccluded.

        The wave-2 audit broke the first cut of this twice: a horizontal-only
        cone passed targets above the frame, and the ray never asked whether
        Phase 20's animated hide had the stone hidden at this very frame. Both
        axes of the real frustum are checked now, and a hidden target can never
        count as shown.
        """
        hidden = bool(target_object.hide_render) or bool(target_object.hide_viewport)
        centre = target_object.matrix_world.translation
        offset = centre - origin
        depth = sum(offset[i] * forward[i] for i in range(3))
        in_frame = False
        if depth > 0.0:
            side = math.atan2(sum(offset[i] * right[i] for i in range(3)), depth)
            rise = math.atan2(sum(offset[i] * upward[i] for i in range(3)), depth)
            in_frame = abs(side) < half_h and abs(rise) < half_v
        direction = offset.normalized()
        hit, _location, _normal, _index, struck, _matrix = scene.ray_cast(
            depsgraph, origin + direction * 0.1, direction
        )
        unoccluded = bool(hit) and struck is not None and struck.name == target_object.name
        return {
            "rendered_at_frame": not hidden,
            "in_frame": in_frame,
            "first_ray_hit": struck.name if struck else None,
            "unoccluded": unoccluded,
        }

    kind_targets = {
        "DURABLE_CONSEQUENCE": "LD_SR__record_stone_",
        "CONSEQUENCE_PERSISTED": "LD_SR__record_stone_",
        "LAW_CHANGE": "LD_SEAL__",
        "LAW_RESTORATION": "LD_SEAL__",
        "WALL_RAISED": "LD_WALL__",
        "WALL_STATE_CHANGE": "LD_WALL__",
        "POPULATION_MOVEMENT": "LD_POP__",
    }
    for beat_id in shot["source_beat_ids"]:
        kind = beat_kinds.get(beat_id, "UNKNOWN")
        prefix = kind_targets.get(kind)
        entry = {"beat_id": beat_id, "beat_kind": kind, "target_prefix": prefix}
        if prefix is not None:
            matching = [obj for obj in bpy.data.objects if obj.name.startswith(prefix)]
            entry["target_count"] = len(matching)
            if not matching:
                raise RuntimeError(
                    f"beat {beat_id} ({kind}) expects {prefix}* objects and the "
                    "composed world holds none"
                )
            if prefix == "LD_SR__record_stone_":
                entry["stones"] = {
                    obj.name: frustum_and_ray(obj) for obj in sorted(matching, key=lambda o: o.name)
                }
                visible = [
                    name
                    for name, verdict in entry["stones"].items()
                    if verdict["rendered_at_frame"]
                    and verdict["in_frame"]
                    and verdict["unoccluded"]
                ]
                entry["visible_stones"] = visible
                if not visible:
                    raise RuntimeError(
                        f"beat {beat_id} ({kind}): no record stone is both inside "
                        f"{camera_name}'s view cone and unoccluded; the shot does not "
                        "reveal its target"
                    )
        targets.append(entry)
    return targets


def render_proof(context: dict, proof_dir: Path) -> dict:
    """Render the real cinematic proof frames after a fully passing run.

    Each transition plan is rendered on its own FULLY COMPOSED world -- the
    locked Phases 15 through 20 stood up in phase order, then the Phase 22
    cuts -- and the baseline's neutral hold on the leg1 world's first held
    frame, which Phase 17's endpoint equivalence and Phase 20's
    motion-endpoint contract make the exact episode-0 state. Before every
    render the composed layers are censused, the scene is stepped to the
    frame, Blender's actual active camera is asserted against the plan, and
    each cited beat's expected visual target is verified in scene and in view.
    """
    import apply_cinematic_direction as applier
    import bpy
    from render_visual_proof import configure_cycles_device, configure_sampling

    proof_dir.mkdir(parents=True, exist_ok=True)
    plans = context["shot_plans"]
    catalogue = context["catalogue"]
    report = {
        "blender": bpy.app.version_string,
        "style": test_cinematic_direction.STYLE,
        "plans": {},
    }

    worlds = (
        # The baseline's world is the held episode-0 state: frame 1 of the
        # before->mid composed world, per Phase 17's proven endpoint
        # equivalence and Phase 20's before-endpoint contract.
        ("ep0_baseline", "baseline", context["before_path"], context["mid_path"], [1]),
        ("ep0_to_ep1", "leg1", context["before_path"], context["mid_path"], None),
        ("ep1_to_ep2", "leg2", context["mid_path"], context["after_path"], None),
    )
    backend = None
    for label, plan_name, before_path, after_path, only_frames in worlds:
        plan = plans[plan_name]
        expected = compose_full_world(context, before_path, after_path)
        census = verify_composition(bpy, label, expected)
        print(f"LD_P22_PROOF_COMPOSITION {label} {json.dumps(census, sort_keys=True)}")
        applier.apply_shot_direction_plan(bpy, plan, catalogue)
        scene = bpy.context.scene
        if backend is None:
            backend = configure_cycles_device()
            report["cycles_backend"] = backend
        configure_sampling(preview=True)
        scene.render.resolution_x = 1280
        scene.render.resolution_y = 720
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.image_settings.color_depth = "8"

        rendered = []
        for frame in only_frames or proof_frames(plan):
            expected = camera_for_frame(plan, frame)
            scene.frame_set(frame)
            actual = scene.camera.name if scene.camera else None
            if actual != expected:
                raise RuntimeError(
                    f"{label} frame {frame}: Blender selected {actual!r}, "
                    f"the plan says {expected!r}"
                )
            targets = verify_beat_targets(
                bpy, plan, context["beat_kinds"][plan_name], frame, expected
            )
            output = (proof_dir / f"{label}_f{frame:03d}_{expected}.png").resolve()
            # Absolute, like render_visual_proof does: Blender resolves a
            # relative render path against the blend file (the drive root for
            # an unsaved factory scene), not the process working directory.
            scene.render.filepath = str(output)
            bpy.ops.render.render(write_still=True)
            payload = output.read_bytes()
            rendered.append(
                {
                    "frame": frame,
                    "camera": expected,
                    "file": output.name,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "beat_targets": targets,
                }
            )
            print(f"LD_P22_PROOF_FRAME {label} f{frame:03d} {expected} {output.name}")
        report["plans"][label] = {
            "mode": plan["source"]["mode"],
            "episode": plan["source"]["episode"],
            "story_plan_sha256": plan["source"]["story_plan_sha256"],
            "motion_time_sha256": plan["source"]["motion_time_sha256"],
            "catalogue_sha256": plan["source"]["catalogue_sha256"],
            "composition_census": census,
            "frames": rendered,
        }

    (proof_dir / "cinematic_blender_proof.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    """Build the scene, run every structural test in phase order, and exit."""
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--production", required=True)
    parser.add_argument("--motion", required=True)
    parser.add_argument("--presence", required=True)
    parser.add_argument("--mobility", required=True)
    parser.add_argument("--state-response", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--mid", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--shot-plan-baseline", required=True)
    parser.add_argument("--shot-plan-leg1", required=True)
    parser.add_argument("--shot-plan-leg2", required=True)
    parser.add_argument("--catalogue", required=True)
    parser.add_argument("--beat-kinds", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--proof-dir", default=None)
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
        "catalogue": json.loads(Path(arguments.catalogue).read_text(encoding="utf-8")),
        "beat_kinds": json.loads(Path(arguments.beat_kinds).read_text(encoding="utf-8")),
    }
    context["workdir"].mkdir(parents=True, exist_ok=True)

    # The gate's own clock checks would otherwise all be RELATIVE -- the same
    # --motion file feeding the prior suites, the plans and the comparisons.
    # The pinned digest makes them absolute: a wrong file refuses here, before
    # a single suite runs, and every plan must bind exactly this source.
    motion_digest = hashlib.sha256(context["motion_path"].read_bytes()).hexdigest()
    if motion_digest != CANONICAL_MOTION_TIME_SHA256:
        print(
            f"REFUSED: --motion hashes to {motion_digest}, not the canonical "
            f"Phase 17 source {CANONICAL_MOTION_TIME_SHA256}"
        )
        return 1
    for name, plan in context["shot_plans"].items():
        bound = plan["source"]["motion_time_sha256"]
        if bound != CANONICAL_MOTION_TIME_SHA256:
            print(
                f"REFUSED: shot plan {name!r} binds clock {bound}, not the "
                "canonical Phase 17 source"
            )
            return 1
        bound_catalogue = plan["source"]["catalogue_sha256"]
        if bound_catalogue != APPROVED_CATALOGUE_SHA256:
            print(
                f"REFUSED: shot plan {name!r} binds catalogue {bound_catalogue}, "
                "not the approved canonical catalogue"
            )
            return 1
    supplied_catalogue = _catalogue_digest(context["catalogue"])
    if supplied_catalogue != APPROVED_CATALOGUE_SHA256:
        print(
            f"REFUSED: --catalogue hashes to {supplied_catalogue}, not the approved "
            f"canonical catalogue {APPROVED_CATALOGUE_SHA256}"
        )
        return 1

    context["spec"] = build_master_scene.build_master_scene(context["spec_path"])

    failures = 0
    executed = 0
    per_phase: dict = {}
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
    print(f"LD_BLENDER_TESTS_P22: {executed - failures} passed, {failures} failed")

    if failures == 0 and arguments.proof_dir:
        render_proof(context, Path(arguments.proof_dir))
        print("LD_P22_PROOF: rendered")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
