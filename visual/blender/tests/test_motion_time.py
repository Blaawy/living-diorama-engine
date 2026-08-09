"""Structural tests for the Phase 17 motion and cinematic-time system.

Executed by ``run_blender_tests_p17.py`` inside background Blender, AFTER
every Phase 15 and Phase 16 structural test has passed unchanged. These tests
own the motion half of the contract, and they are deliberately the hardest
ones to satisfy:

* the pure planner's replicas of the locked decoration samplers ARE the real
  objects, so a plan can never animate a fiction;
* the first semantic frame is the ordinary static application of the before
  export, and the last one is the ordinary static application of the after
  export -- object for object, transform for transform;
* the transition genuinely moves, and only the authorised channels move;
* the persistent city does not shift by a millimetre on any frame;
* applying the same plan twice is the same animation, not twice as much;
* rebuilding without motion still reproduces the canonical static Phase 16
  world, so the motion layer is additive and reversible by rebuild.
"""

import json
import sys
from pathlib import Path

import bpy

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import apply_motion_plan as motion  # noqa: E402
import apply_render_export  # noqa: E402
import build_master_scene  # noqa: E402
import build_production_world  # noqa: E402
import motion_plan  # noqa: E402
from motion_time_spec import load_motion_time_spec  # noqa: E402
from scene_spec import load_master_scene_spec, load_render_export  # noqa: E402

STYLE = "dna"

MAX_KEYFRAMES = 4000
"""A generous ceiling that still refuses per-frame baking. Phase 17 uses a
small number of semantic F-curves; if this is ever approached, the timing
abstraction has been bypassed."""


def _build(context, leg: str) -> dict:
    """Build (once per leg) the animated scene and cache the whole report."""
    cache = context.setdefault("motion_scenes", {})
    if leg not in cache:
        before, after = (
            (context["before_path"], context["mid_path"])
            if leg == "leg1"
            else (context["mid_path"], context["after_path"])
        )
        cache[leg] = motion.build_motion_scene(
            context["spec_path"],
            context["production_path"],
            before,
            after,
            context["motion_path"],
            style=STYLE,
        )
        cache[leg]["leg"] = leg
        cache[leg]["current"] = leg
    if context.get("built_leg") != leg:
        context["built_leg"] = leg
    return cache[leg]


def _ensure_scene(context, leg: str) -> dict:
    """Return the report for a leg, rebuilding it if another leg took the scene."""
    cache = context.setdefault("motion_scenes", {})
    if context.get("built_leg") == leg and leg in cache:
        return cache[leg]
    cache.pop(leg, None)
    context["built_leg"] = None
    report = _build(context, leg)
    context["built_leg"] = leg
    return report


def test_the_pure_depot_replica_matches_the_real_containers(context) -> None:
    """The planner's yard replica IS the locked sampler, not a guess.

    Phase 17 has to know which containers a given export would produce before
    Blender produces them. It replays ``apply_districts``' own RNG identity;
    this test proves the replay against the real meshes, so any future drift
    in the locked builder fails loudly instead of animating a wrong yard.
    """
    master_spec = load_master_scene_spec(context["spec_path"])
    build_master_scene.build_master_scene(context["spec_path"], style=STYLE)
    for label in ("before_path", "mid_path", "after_path"):
        export = load_render_export(context[label])
        apply_render_export.apply_render_export_file(
            context["spec_path"], context[label], style=STYLE
        )
        expected: dict[str, float] = {}
        for district in export["world"]["districts"]:
            expected.update(
                motion_plan.depot_slot_placements(
                    district,
                    master_spec["districts"][district["id"]],
                    master_spec["visual_seed"],
                )
            )
        real = {
            obj.name: obj.rotation_euler[2]
            for obj in bpy.data.objects
            if obj.name.startswith(motion_plan.DEPOT_PREFIX)
        }
        assert set(real) == set(expected), f"{label}: the replica named the wrong containers"
        for name, rotation in sorted(expected.items()):
            assert abs(real[name] - rotation) < 1.0e-6, f"{label}: {name} sits differently"


def test_the_pure_strut_replica_matches_the_real_anchors(context) -> None:
    """The planner's anchoring replica IS the locked layout, not a guess."""
    master_spec = load_master_scene_spec(context["spec_path"])
    build_master_scene.build_master_scene(context["spec_path"], style=STYLE)
    for label in ("before_path", "mid_path", "after_path"):
        export = load_render_export(context[label])
        apply_render_export.apply_render_export_file(
            context["spec_path"], context[label], style=STYLE
        )
        walls = {wall["boundary_id"] for wall in export["world"]["walls"]}
        expected: dict[str, tuple[float, float]] = {}
        for infrastructure in export["world"]["infrastructure"]:
            expected.update(
                motion_plan.strut_placements(
                    infrastructure,
                    master_spec["boundaries"][infrastructure["boundary_id"]],
                    infrastructure["boundary_id"] in walls,
                )
            )
        real = {
            obj.name: (obj.location[0], obj.location[1])
            for obj in bpy.data.objects
            if "__wallstrut" in obj.name
        }
        assert set(real) == set(expected), f"{label}: the replica named the wrong struts"
        for name, (x, y) in sorted(expected.items()):
            assert abs(real[name][0] - x) < 1.0e-4 and abs(real[name][1] - y) < 1.0e-4


def test_the_pure_visual_values_match_the_locked_state_mapping(context) -> None:
    """Seal glow and window glazing are the Phase 15 formulas, unchanged."""
    master_spec = load_master_scene_spec(context["spec_path"])
    build_master_scene.build_master_scene(context["spec_path"], style=STYLE)
    for label in ("before_path", "mid_path", "after_path"):
        export = load_render_export(context[label])
        apply_render_export.apply_render_export_file(
            context["spec_path"], context[label], style=STYLE
        )
        measured = motion.capture_material_values(master_spec)
        law = next(
            entry for entry in export["world"]["laws"] if entry["id"] == motion_plan.MOVEMENT_LAW_ID
        )
        seal = measured[
            (
                motion_plan.SEAL_GLOW_MATERIAL,
                motion_plan.SEAL_GLOW_NODE,
                motion_plan.SEAL_GLOW_SOCKET,
            )
        ]
        assert abs(seal - motion_plan.seal_glow_value(law)) < 1.0e-6, f"{label}: seal glow"
        for district in export["world"]["districts"]:
            character = master_spec["districts"][district["id"]]["character"]
            key = (
                f"LD_MAT__glass_{character}",
                motion_plan.GLAZING_NODE,
                motion_plan.GLAZING_SOCKET,
            )
            expected = motion_plan.glazing_value(district)
            assert abs(measured[key] - expected) < 1.0e-6, f"{label}: {district['id']} glazing"


def _material_endpoints(report: dict) -> dict:
    """Both endpoints' full equivalence verdict for one animated scene."""
    return motion.endpoint_equivalence(
        report["scene"],
        report["geography"],
        report["scene"]["master_spec"],
        report["plan"]["timeline"],
    )


def _seal_channel() -> tuple[str, str, str]:
    """The Golden Seal's law-indication material channel."""
    return (
        motion_plan.SEAL_GLOW_MATERIAL,
        motion_plan.SEAL_GLOW_NODE,
        motion_plan.SEAL_GLOW_SOCKET,
    )


def test_the_first_frame_is_the_static_before_world(context) -> None:
    """ENDPOINT A. Not similar to it -- it."""
    report = _ensure_scene(context, "leg1")
    timeline = report["plan"]["timeline"]
    animated = motion.scene_state_at(timeline["start_frame"])
    static = motion.canonical_state(report["scene"], report["geography"], "before")
    assert animated == static


def test_the_last_frame_is_the_static_after_world(context) -> None:
    """ENDPOINT B. No animation may produce a prettier but false final state."""
    report = _ensure_scene(context, "leg1")
    timeline = report["plan"]["timeline"]
    animated = motion.scene_state_at(timeline["end_frame"])
    static = motion.canonical_state(report["scene"], report["geography"], "after")
    assert animated == static


def test_the_holds_actually_hold(context) -> None:
    """Nothing moves before the transition opens or after it closes."""
    report = _ensure_scene(context, "leg1")
    timeline = report["plan"]["timeline"]
    assert motion.scene_state_at(timeline["start_frame"]) == motion.scene_state_at(
        timeline["transition_start"]
    )
    assert motion.scene_state_at(timeline["transition_end"]) == motion.scene_state_at(
        timeline["end_frame"]
    )


def test_the_transition_genuinely_moves(context) -> None:
    """A motion system that produces two identical endpoints has done nothing."""
    report = _ensure_scene(context, "leg1")
    timeline = report["plan"]["timeline"]
    start = motion.scene_state_at(timeline["start_frame"])
    end = motion.scene_state_at(timeline["end_frame"])
    middle = motion.scene_state_at((timeline["transition_start"] + timeline["transition_end"]) // 2)
    assert start != end, "the two endpoints must differ or there is no story"
    assert middle != start and middle != end, "the middle must be a real intermediate world"
    assert len(start) < len(middle) < len(end), "the wall must be part-built in the middle"


def test_only_authorised_objects_ever_move(context) -> None:
    """Every difference across the whole timeline traces to a directive."""
    report = _ensure_scene(context, "leg1")
    authorised = set(report["metrics"]["animated_object_names"])
    frames = [sample["frame"] for sample in report["motion_spec"]["proof_samples"]]
    baseline = {name: state for name, *state in motion.scene_state_at(frames[0])}
    for frame in frames[1:]:
        current = {name: state for name, *state in motion.scene_state_at(frame)}
        for name in set(baseline) | set(current):
            if baseline.get(name) != current.get(name):
                assert name in authorised, f"{name} moved at frame {frame} with no directive"


def test_the_persistent_city_never_moves(context) -> None:
    """Plates, streets, blocks, harbour, Seal, groves and cameras stay put."""
    report = _ensure_scene(context, "leg1")
    episode = set(report["scene"]["union"])
    pinned = {name: state for name, *state in report["geography"]}
    assert pinned, "the persistent city must not be empty"
    assert not (set(pinned) & episode), "geography and episode layers must not overlap"
    for sample in report["motion_spec"]["proof_samples"]:
        current = {name: state for name, *state in motion.scene_state_at(sample["frame"])}
        for name, state in pinned.items():
            assert current.get(name) == state, f"{name} moved at frame {sample['frame']}"


def test_no_camera_carries_motion(context) -> None:
    """Phase 17 builds the timeline a shot system will later use, not the shots."""
    _ensure_scene(context, "leg1")
    for obj in bpy.data.objects:
        if obj.type != "CAMERA":
            continue
        assert obj.animation_data is None or obj.animation_data.action is None


def test_applying_the_same_plan_twice_changes_nothing(context) -> None:
    """Idempotency: the same animation, not two of it."""
    report = _ensure_scene(context, "leg1")

    def fingerprint() -> list[tuple]:
        """Every motion action with its curve and key counts."""
        return sorted(
            (
                action.name,
                len(action.fcurves),
                sum(len(curve.keyframe_points) for curve in action.fcurves),
                tuple(
                    sorted(
                        (curve.data_path, curve.array_index, len(curve.keyframe_points))
                        for curve in action.fcurves
                    )
                ),
            )
            for action in bpy.data.actions
            if action.name.startswith(motion.MOTION_ACTION_PREFIX)
        )

    first = fingerprint()
    first_state = motion.scene_state_at(report["plan"]["timeline"]["end_frame"])
    again = motion.apply_motion_plan(
        report["plan"], report["scene"]["union"], report["scene"]["static_before"]
    )
    assert fingerprint() == first
    assert again["fcurves"] == report["metrics"]["fcurves"]
    assert again["keyframes"] == report["metrics"]["keyframes"]
    assert again["cleared_actions"] == len(first)
    assert motion.scene_state_at(report["plan"]["timeline"]["end_frame"]) == first_state


def test_no_duplicate_objects_actions_or_materials_appear(context) -> None:
    """No ``.001`` growth anywhere, in any datablock Phase 17 can reach."""
    _ensure_scene(context, "leg1")
    for collection, label in (
        (bpy.data.objects, "object"),
        (bpy.data.actions, "action"),
        (bpy.data.materials, "material"),
        (bpy.data.node_groups, "node group"),
    ):
        duplicates = [entry.name for entry in collection if ".0" in entry.name]
        assert not duplicates, f"duplicate {label} datablocks: {duplicates[:5]}"


def test_every_motion_action_belongs_to_exactly_one_holder(context) -> None:
    """One action per animated datablock, deterministically named, no sharing."""
    report = _ensure_scene(context, "leg1")
    actions = [
        action for action in bpy.data.actions if action.name.startswith(motion.MOTION_ACTION_PREFIX)
    ]
    assert actions
    assert len({action.name for action in actions}) == len(actions)
    for action in actions:
        assert action.users == 1, f"{action.name} is shared between holders"
        assert len(action.name.encode("utf-8")) <= motion.MAX_ID_NAME_BYTES
    expected = report["metrics"]["animated_objects"] + report["metrics"]["animated_materials"]
    assert len(actions) == expected


def test_the_keyframe_budget_stays_semantic(context) -> None:
    """Small numbers of meaningful curves, never a per-frame bake."""
    report = _ensure_scene(context, "leg1")
    metrics = report["metrics"]
    timeline = report["plan"]["timeline"]
    frames = timeline["end_frame"] - timeline["start_frame"] + 1
    assert metrics["keyframes"] < MAX_KEYFRAMES
    assert metrics["keyframes"] < metrics["fcurves"] * frames / 4


def test_the_seal_material_endpoints_are_the_static_law_states(context) -> None:
    """LEG 1. The Seal's ACTUAL applied F-curve, not the plan's promise.

    ``verify_union`` already proves the plan agrees with the canonical static
    worlds. This proves the other half: that the animation Blender actually
    carries evaluates, at the first and last semantic frames, to exactly the
    emission the ordinary static application of each export produces. An
    animation can satisfy a plan and still key the wrong curve.
    """
    report = _ensure_scene(context, "leg1")
    timeline = report["plan"]["timeline"]
    master_spec = report["scene"]["master_spec"]
    channel = _seal_channel()

    before = load_render_export(context["before_path"])
    after = load_render_export(context["mid_path"])
    law_before = next(
        entry for entry in before["world"]["laws"] if entry["id"] == motion_plan.MOVEMENT_LAW_ID
    )
    law_after = next(
        entry for entry in after["world"]["laws"] if entry["id"] == motion_plan.MOVEMENT_LAW_ID
    )
    assert law_before["active"] is True and law_after["active"] is False, (
        "leg 1 must be the episode where the engine suspends the movement law"
    )

    start = motion.material_state_at(master_spec, timeline["start_frame"])
    end = motion.material_state_at(master_spec, timeline["end_frame"])
    assert abs(start[channel] - motion_plan.seal_glow_value(law_before)) < 1.0e-6
    assert abs(end[channel] - motion_plan.seal_glow_value(law_after)) < 1.0e-6
    assert abs(start[channel] - report["scene"]["materials_before"][channel]) < 1.0e-6
    assert abs(end[channel] - report["scene"]["materials_after"][channel]) < 1.0e-6
    assert start[channel] != end[channel], "the law's standing must actually change"


def test_every_material_channel_is_equivalent_at_both_endpoints(context) -> None:
    """LEG 1. Not just the Seal: every state-driven material, both ends."""
    report = _ensure_scene(context, "leg1")
    endpoints = _material_endpoints(report)
    for which, endpoint in sorted(endpoints.items()):
        assert endpoint["materials_equivalent"], (
            f"{which}: material mismatches {endpoint['material_mismatches']}"
        )
        assert endpoint["objects_equivalent"], f"{which}: objects differ"
        assert endpoint["equivalent"]
        assert endpoint["material_channels"] >= 5


def test_a_perturbed_material_endpoint_is_detected(context) -> None:
    """ATTACK. Move the Seal's final key and require the verdict to fail.

    Object transforms stay perfect throughout, so this fails only if material
    endpoints are genuinely part of the contract rather than assumed.
    """
    report = _ensure_scene(context, "leg1")
    node_tree, data_path = motion._socket_of(*_seal_channel())
    curve = motion.curve_of(node_tree, data_path)
    assert curve is not None, "the Seal must actually be animated in leg 1"

    try:
        last = curve.keyframe_points[-1]
        last.co[1] = last.co[1] + 1.25
        curve.update()
        endpoints = _material_endpoints(report)
        assert endpoints["after"]["objects_equivalent"], "objects must stay correct"
        assert not endpoints["after"]["materials_equivalent"], "the lie must be caught"
        assert not endpoints["after"]["equivalent"], "equivalent must mean BOTH halves"
        mismatch = endpoints["after"]["material_mismatches"][0]
        assert mismatch["material"] == motion_plan.SEAL_GLOW_MATERIAL
        assert mismatch["static"] == motion_plan.SEAL_GLOW_INACTIVE
        assert endpoints["before"]["equivalent"], "the untouched endpoint stays honest"
    finally:
        # Editing a keyframe's ``co`` in place does not reliably invalidate
        # Blender's evaluation, so the curve is rebuilt from the plan rather
        # than un-edited. Re-application is idempotent by contract, which
        # makes this both a clean restore and one more exercise of it.
        motion.apply_motion_plan(
            report["plan"], report["scene"]["union"], report["scene"]["static_before"]
        )
    for which, endpoint in sorted(_material_endpoints(report).items()):
        assert endpoint["equivalent"], f"rebuilding from the plan must heal {which}: {endpoint}"


def test_the_wall_at_the_final_frame_is_the_canonical_wall(context) -> None:
    """The scar Phase 15 designed, exactly, with no motion left on it."""
    report = _ensure_scene(context, "leg1")
    timeline = report["plan"]["timeline"]
    final = {name: state for name, *state in motion.scene_state_at(timeline["end_frame"])}
    canonical = report["scene"]["static_after"]
    wall_names = [name for name in canonical if name.startswith(motion_plan.WALL_PREFIX)]
    assert wall_names, "the after-world must hold the engine-built wall"
    for name in sorted(wall_names):
        assert tuple(final[name]) == canonical[name], f"{name} is not canonical at the final frame"


def test_a_wall_that_persists_produces_no_motion(context) -> None:
    """THE WORLD REMEMBERS.

    Leg 2 restores the law the engine suspended. The law's indication returns;
    the wall does not un-build, is not re-built, and is not touched at all. A
    truthful plan says so by emitting no wall directive whatsoever.
    """
    report = _ensure_scene(context, "leg2")
    plan = report["plan"]
    channels = plan["summary"]["by_channel"]
    assert "wall_presence" not in channels, "a standing wall must emit no motion"
    assert channels.get("law_seal_glow") == 1, "the law's return must be visible"
    assert motion.scene_state_at(plan["timeline"]["start_frame"]) == motion.canonical_state(
        report["scene"], report["geography"], "before"
    )
    assert motion.scene_state_at(plan["timeline"]["end_frame"]) == motion.canonical_state(
        report["scene"], report["geography"], "after"
    )
    wall_names = [
        name for name in report["scene"]["union"] if name.startswith(motion_plan.WALL_PREFIX)
    ]
    assert wall_names
    animated = set(report["metrics"]["animated_object_names"])
    assert not (set(wall_names) & animated), "no wall object may carry motion in leg 2"


def test_the_seal_returns_and_the_material_says_so(context) -> None:
    """LEG 2. The law comes back; the Seal's applied curve comes back with it."""
    report = _ensure_scene(context, "leg2")
    timeline = report["plan"]["timeline"]
    master_spec = report["scene"]["master_spec"]
    channel = _seal_channel()

    before = load_render_export(context["mid_path"])
    after = load_render_export(context["after_path"])
    law_before = next(
        entry for entry in before["world"]["laws"] if entry["id"] == motion_plan.MOVEMENT_LAW_ID
    )
    law_after = next(
        entry for entry in after["world"]["laws"] if entry["id"] == motion_plan.MOVEMENT_LAW_ID
    )
    assert law_before["active"] is False and law_after["active"] is True

    start = motion.material_state_at(master_spec, timeline["start_frame"])
    end = motion.material_state_at(master_spec, timeline["end_frame"])
    assert abs(start[channel] - motion_plan.SEAL_GLOW_INACTIVE) < 1.0e-6
    assert abs(end[channel] - motion_plan.SEAL_GLOW_ACTIVE) < 1.0e-6
    for which, endpoint in sorted(_material_endpoints(report).items()):
        assert endpoint["equivalent"], f"{which}: {endpoint}"


def test_the_planner_refuses_a_demolition_the_engine_never_recorded(context) -> None:
    """A hand-forged export that erases the scar is refused, not staged."""
    master_spec = load_master_scene_spec(context["spec_path"])
    motion_spec = load_motion_time_spec(context["motion_path"])
    standing = load_render_export(context["after_path"])
    forged = load_render_export(context["after_path"])
    forged["world"]["walls"] = []
    for boundary in forged["world"]["boundaries"]:
        boundary["wall_id"] = None
    try:
        motion_plan.plan_motion(standing, forged, master_spec, motion_spec)
    except motion_plan.MotionPlanError as error:
        assert "the world remembers" in str(error)
    else:
        raise AssertionError("a vanishing wall must be refused")


def test_rebuilding_without_motion_reproduces_the_static_world(context) -> None:
    """The motion layer is additive and reversible by rebuild.

    A plain Phase 16 build with the ordinary episode application must be the
    canonical static world again -- same objects, same transforms, and no
    Phase 17 animation data anywhere in the file.
    """
    report = _ensure_scene(context, "leg1")
    canonical = dict(report["scene"]["static_after"])
    geography = list(report["geography"])

    build_master_scene.build_master_scene(context["spec_path"], style=STYLE)
    build_production_world.add_production_world(
        context["spec_path"], context["production_path"], style=STYLE
    )
    apply_render_export.apply_render_export_file(
        context["spec_path"], context["mid_path"], style=STYLE
    )
    context["built_leg"] = None

    assert motion.capture_episode() == canonical
    assert motion.geography_snapshot() == geography
    for obj in bpy.data.objects:
        assert obj.animation_data is None or obj.animation_data.action is None
        assert not obj.hide_render and not obj.hide_viewport
    for material in bpy.data.materials:
        tree = material.node_tree
        if tree is not None and tree.animation_data is not None:
            assert tree.animation_data.action is None
    # A rebuild unlinks the motion actions rather than deleting the datablocks;
    # unused actions are dropped when the file is written, so what matters is
    # that nothing in the rebuilt world still references one.
    for action in bpy.data.actions:
        if action.name.startswith(motion.MOTION_ACTION_PREFIX):
            assert action.users == 0, f"{action.name} survived the rebuild in use"


def test_the_glazing_channel_animates_end_to_end(context) -> None:
    """SYNTHETIC STRUCTURAL FIXTURE -- not world history.

    The real three-episode story holds population constant, so it never
    exercises ``district_glazing``, and inventing a migration the engine did
    not run would be exactly the lie this phase exists to prevent. Instead
    this fixture takes the REAL episode-0 export and changes ONE authoritative
    number -- a district's population -- then drives the ordinary planner, the
    ordinary union build, and the ordinary Blender applier over the pair, and
    reads the material value the applied F-curve actually produces at the
    first and last frames.

    It proves the CODE PATH. It is never rendered, never packaged, and never
    presented as something the world did.
    """
    export = load_render_export(context["before_path"])
    district = next(entry for entry in export["world"]["districts"] if entry["id"] == "district_a")
    assert district["population"] == 140 and district["housing_capacity"] == 400

    fixture_dir = context["workdir"] / "synthetic_glazing_fixture"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    before_path = fixture_dir / "synthetic_glazing_before.json"
    after_path = fixture_dir / "synthetic_glazing_after.json"
    before_path.write_text(json.dumps(export, sort_keys=True), encoding="utf-8", newline="\n")
    crowded = json.loads(json.dumps(export))
    next(entry for entry in crowded["world"]["districts"] if entry["id"] == "district_a")[
        "population"
    ] = 320
    after_path.write_text(json.dumps(crowded, sort_keys=True), encoding="utf-8", newline="\n")

    report = motion.build_motion_scene(
        context["spec_path"],
        context["production_path"],
        before_path,
        after_path,
        context["motion_path"],
        style=STYLE,
    )
    context["built_leg"] = None
    context.setdefault("motion_scenes", {}).clear()

    plan = report["plan"]
    assert plan["summary"]["by_channel"] == {"district_glazing": 1}, (
        f"the fixture must isolate glazing, got {plan['summary']['by_channel']}"
    )
    directive = plan["directives"][0]
    assert directive["target"]["material"] == "LD_MAT__glass_civic"
    assert directive["target"]["node"] == motion_plan.GLAZING_NODE

    channel = (
        "LD_MAT__glass_civic",
        motion_plan.GLAZING_NODE,
        motion_plan.GLAZING_SOCKET,
    )
    master_spec = report["scene"]["master_spec"]
    timeline = plan["timeline"]
    node_tree, data_path = motion._socket_of(*channel)
    assert motion.curve_of(node_tree, data_path) is not None, "glazing must be keyed"

    start = motion.material_state_at(master_spec, timeline["start_frame"])[channel]
    end = motion.material_state_at(master_spec, timeline["end_frame"])[channel]
    expected_start = motion_plan.GLAZING_BASE + motion_plan.GLAZING_RANGE * (140 / 400)
    expected_end = motion_plan.GLAZING_BASE + motion_plan.GLAZING_RANGE * (320 / 400)
    assert abs(start - expected_start) < 1.0e-6, f"{start} != {expected_start}"
    assert abs(end - expected_end) < 1.0e-6, f"{end} != {expected_end}"
    assert abs(start - report["scene"]["materials_before"][channel]) < 1.0e-6
    assert abs(end - report["scene"]["materials_after"][channel]) < 1.0e-6

    middle = motion.material_state_at(
        master_spec, (timeline["transition_start"] + timeline["transition_end"]) // 2
    )[channel]
    assert start < middle < end, "glazing must genuinely travel, not jump"

    for which, endpoint in sorted(
        motion.endpoint_equivalence(
            report["scene"], report["geography"], master_spec, timeline
        ).items()
    ):
        assert endpoint["equivalent"], f"{which}: {endpoint}"
