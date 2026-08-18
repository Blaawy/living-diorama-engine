"""Structural tests for the Phase 20 state-response layer.

Runs INSIDE Blender, against the real scene, because the claims that matter
here cannot be checked anywhere else: that four district strata and one stone
per remembered fact really stand in the file, that each district's air really
carries THAT district's own scarcity, that the animated ends of a transition
really are the two ordinary static applications, and that clearing the layer
really gives Phase 19's world back untouched.

Every measurement is taken from the scene or from the F-curves, never from the
plan that is under test. A suite that compared the plan with itself would agree
with a layer that built nothing at all.
"""

import apply_state_response as sr
import apply_state_response_motion as srm
import bpy
import build_master_scene
import build_production_world
from mathutils import Vector
from motion_time_spec import load_motion_time_spec
from scene_spec import load_master_scene_spec, load_render_export
from state_response_motion_plan import plan_state_response_motion
from state_response_plan import AIR_MATERIAL_PREFIX, plan_state_response
from state_response_spec import load_state_response_spec, resolve_state_response_timeline

STYLE = "dna"

_STATE: dict = {}

LARGE_BOUND_METRES = 4.0
"""What counts as a big object in this layer.

A district stratum is tens of metres across; a record stone is well under one.
Nothing Phase 20 builds lands between the two, so any threshold in the gap
separates them, and this one is nowhere near either edge.
"""

DENSITY_TOLERANCE = 1.0e-6
"""RELATIVE tolerance for a planned density against the float32 socket.

Air densities are thousandths, so an absolute tolerance sized for ordinary
scene units would swallow the entire signal and pass a socket that carried the
wrong district's reading. The comparison is scaled by the expected magnitude
instead, which leaves it about four orders of magnitude tighter than the
smallest difference between two districts in the canonical chain.
"""


def _ld_material_names() -> set[str]:
    """Every locked ``LD_MAT__`` material name currently in the file."""
    return {
        material.name for material in bpy.data.materials if material.name.startswith("LD_MAT__")
    }


def _object_snapshot() -> list[tuple]:
    """Identity and transform of every object in the file, in name order."""
    return sorted(
        (
            obj.name,
            tuple(round(value, 6) for value in obj.location),
            tuple(round(value, 6) for value in obj.rotation_euler),
            tuple(round(value, 6) for value in obj.scale),
        )
        for obj in bpy.data.objects
    )


def _layer_snapshot() -> list[tuple]:
    """Everything about the Phase 20 layer that a rebuild could get wrong."""
    entries = []
    for obj in sr.state_response_objects():
        entries.append(
            (
                obj.name,
                obj.data.name if obj.data is not None else "",
                len(obj.data.vertices) if obj.data is not None else 0,
                len(obj.data.polygons) if obj.data is not None else 0,
                tuple(round(value, 6) for value in obj.location),
                tuple(round(value, 6) for value in obj.rotation_euler),
                tuple(round(value, 6) for value in obj.dimensions),
                obj.display_type,
                tuple(
                    slot.material.name for slot in obj.material_slots if slot.material is not None
                ),
                tuple(sorted(collection.name for collection in obj.users_collection)),
            )
        )
    return sorted(entries)


def _duplicate_named(prefix: str, datablocks) -> list[str]:
    """Every Phase 20 datablock whose name carries Blender's ``.001`` twin suffix."""
    return sorted(
        block.name
        for block in datablocks
        if block.name.startswith(prefix) and block.name.rpartition(".")[2].isdigit()
    )


def _air_ids(plan: dict) -> list[str]:
    """The districts one plan carries an air response for, in name order."""
    return sorted(
        response["semantic_id"]
        for response in plan["responses"]
        if response["channel"] == "district_air"
    )


def _prepare(context: dict) -> dict:
    """Build the city once, and derive every Phase 20 plan this suite needs.

    Cached because rebuilding a whole production city per test would make the
    suite cost minutes rather than seconds. The plans are derived BEFORE the
    scene is touched, so nothing in the file can influence what they say.
    """
    if _STATE:
        return _STATE
    master = load_master_scene_spec(context["spec_path"])
    spec = load_state_response_spec(context["state_response_path"])
    timeline = resolve_state_response_timeline(
        spec, load_motion_time_spec(context["motion_path"])["timeline"]
    )
    plans = {
        episode: plan_state_response(load_render_export(context[f"{episode}_path"]), master, spec)
        for episode in ("before", "mid", "after")
    }

    build_master_scene.build_master_scene(context["spec_path"], style=STYLE)
    build_production_world.add_production_world(
        context["spec_path"], context["production_path"], style=STYLE
    )
    _STATE.update(
        {
            "spec": spec,
            "timeline": timeline,
            "plans": plans,
            "motions": {
                "leg1": plan_state_response_motion(plans["before"], plans["mid"], spec, timeline),
                "leg2": plan_state_response_motion(plans["mid"], plans["after"], spec, timeline),
            },
            "ld_materials": _ld_material_names(),
            "pre_phase20": _object_snapshot(),
            "leg": None,
            "verdicts": {},
        }
    )
    return _STATE


def _canonical(context: dict) -> dict:
    """Stand the canonical STATIC layer up: the after-export's own plan, applied."""
    state = _prepare(context)
    sr.apply_state_response(state["plans"]["after"], state["spec"])
    state["leg"] = None
    return state


def _canonical_animated(context: dict) -> dict:
    """Stand the canonical layer up and animate it with leg one's transition.

    Leg one is the leg that moves both channels, so a scene built this way
    carries a curve on every district's air and on a record stone as well.
    """
    state = _canonical(context)
    srm.apply_state_response_motion(state["motions"]["leg1"], state["timeline"])
    return state


def _leg(context: dict, name: str) -> dict:
    """Return one leg's endpoint verdict, rebuilding its scene if another took over."""
    state = _prepare(context)
    if state["leg"] != name:
        earlier, later = ("before", "mid") if name == "leg1" else ("mid", "after")
        state["verdicts"][name] = srm.endpoint_equivalence(
            state["plans"][earlier],
            state["plans"][later],
            state["motions"][name],
            state["spec"],
            state["timeline"],
        )
        state["leg"] = name
    return state["verdicts"][name]


def _measured_endpoint(frame: int) -> dict:
    """The animated scene's own air and visibility on one frame, read off the curves."""
    return {"air": srm.air_state_at(frame), "visible": srm.visible_state_at(frame)}


# ---------------------------------------------------------------------------
# The layer exists, and is exactly what the plan asked for
# ---------------------------------------------------------------------------


def test_the_state_response_layer_builds_the_planned_air_and_stones(context: dict) -> None:
    """One stratum per district, one stone per remembered fact, and nothing loose.

    The counts come from the plan's own channel tally, so an applier that built
    nothing, that built a single stratum for the whole city, or that left its
    objects linked into the scene collection as well as its own would all fail.
    """
    state = _canonical(context)
    plan = state["plans"]["after"]
    wanted = plan["summary"]["responses_by_channel"]
    summary = sr.state_response_summary()
    assert summary["air_volumes"] == wanted["district_air"]
    assert summary["record_stones"] == wanted["memory_record"]
    assert summary["objects"] == plan["summary"]["responses"]

    for response in plan["responses"]:
        target = response["target"]
        if target["kind"] == "object_presence":
            assert bpy.data.objects.get(target["object"]) is not None, target
        else:
            assert bpy.data.materials.get(target["material"]) is not None, target

    collection = bpy.data.collections.get(sr.STATE_RESPONSE_ROOT)
    assert collection is not None, "the layer must own a collection of its own"
    assert sorted(obj.name for obj in collection.objects) == [
        obj.name for obj in sr.state_response_objects()
    ]
    for obj in sr.state_response_objects():
        assert [linked.name for linked in obj.users_collection] == [sr.STATE_RESPONSE_ROOT], (
            obj.name
        )
    world = bpy.data.collections[sr.WORLD_ROOT]
    assert sr.STATE_RESPONSE_ROOT in {child.name for child in world.children}


def test_each_districts_air_carries_that_districts_own_reading(context: dict) -> None:
    """The socket holds the plan's value for THAT district, in two canonical states.

    Checked against two different exports over the same four districts. The
    before-state gives three distinct densities and the after-state two, so an
    applier that wrote one constant everywhere, that reused the first district's
    reading, or that never wrote the socket at all cannot survive both passes.
    """
    state = _prepare(context)
    for episode in ("before", "after"):
        plan = state["plans"][episode]
        sr.apply_state_response(plan, state["spec"])
        state["leg"] = None
        for response in plan["responses"]:
            if response["channel"] != "district_air":
                continue
            measured = sr.air_density_of(response["semantic_id"])
            expected = response["value"]
            assert abs(measured - expected) <= DENSITY_TOLERANCE * abs(expected), (
                episode,
                response["semantic_id"],
                measured,
                expected,
            )


def test_applying_the_same_plan_twice_is_the_same_scene(context: dict) -> None:
    """IDEMPOTENCY, measured: the second apply replaces the layer, never grows it.

    An applier that appended rather than replaced would leave ``LD_SR__....001``
    twins behind; one that rebuilt differently would move an object, change a
    mesh, swap a material or relink a collection. Both are in the snapshot.
    """
    state = _canonical(context)
    first = _layer_snapshot()
    sr.apply_state_response(state["plans"]["after"], state["spec"])
    state["leg"] = None
    assert _layer_snapshot() == first
    assert _duplicate_named(sr.OBJECT_PREFIX, bpy.data.objects) == []
    assert _duplicate_named(sr.MESH_PREFIX, bpy.data.meshes) == []
    assert _duplicate_named(sr.MATERIAL_PREFIX, bpy.data.materials) == []


def test_the_stones_stand_on_the_plaza_and_only_the_air_is_large(context: dict) -> None:
    """GEOMETRY SANITY: a stone on the plaza, and nothing solid big enough to occlude.

    A stone's base is measured off its own bounding box in world space rather
    than read from its origin, so an applier that placed the box by its centre
    would show as half a stone sunk into the plaza. The size partition is an
    equality: if a stone ever grew to district scale, or a stratum shrank to
    stone scale, the two sets stop matching. The strata are the only large
    things and they are wire, so nothing Phase 20 adds can hide the city.
    """
    state = _canonical(context)
    for response in state["plans"]["after"]["responses"]:
        if response["channel"] != "memory_record":
            continue
        obj = bpy.data.objects[response["target"]["object"]]
        base = min((obj.matrix_world @ Vector(corner)).z for corner in obj.bound_box)
        assert abs(base - response["field"]["z"]) < 1.0e-6, (obj.name, base, response["field"]["z"])

    air = {
        obj.name for obj in sr.state_response_objects() if obj.name.startswith(sr.AIR_OBJECT_PREFIX)
    }
    large = {
        obj.name for obj in sr.state_response_objects() if max(obj.dimensions) > LARGE_BOUND_METRES
    }
    assert large == air, sorted(large ^ air)
    for obj in sr.state_response_objects():
        expected = "WIRE" if obj.name in air else "TEXTURED"
        assert obj.display_type == expected, (obj.name, obj.display_type)


def test_each_stratum_stands_on_the_ground_it_is_the_air_of(context: dict) -> None:
    """REGRESSION: the air must span its district's own floor-to-ceiling band.

    ``make_box`` origins at the base centre, not the centre. An applier that
    passed a centre-of-box z lifted every stratum by half its own height -- a
    seventeen-metre gap between a district and its own air -- and, worse, mapped
    the shader's floor-to-ceiling falloff over a band the district does not
    occupy. Nothing in a plan or a hash could show that; only the geometry can.

    The tolerance is scaled by magnitude because vertices are stored as float32:
    at a ceiling of 34 metres the representable step is already larger than a
    fixed 1e-6, so an absolute threshold here would fail a correct scene.
    """
    state = _canonical(context)
    for response in state["plans"]["after"]["responses"]:
        if response["channel"] != "district_air":
            continue
        obj = bpy.data.objects[f"{sr.AIR_OBJECT_PREFIX}{response['semantic_id']}"]
        corners = [(obj.matrix_world @ Vector(corner)).z for corner in obj.bound_box]
        floor = response["field"]["floor"]
        ceiling = response["field"]["ceiling"]
        for measured, expected in ((min(corners), floor), (max(corners), ceiling)):
            tolerance = 1.0e-6 * max(1.0, abs(expected))
            assert abs(measured - expected) <= tolerance, (
                obj.name,
                measured,
                expected,
            )


def test_the_locked_material_family_survives_phase20_untouched(context: dict) -> None:
    """Phase 16 pins ``LD_MAT__`` by NAME SET; Phase 20 must not be what breaks it.

    The family is snapshotted off the freshly built city, before this phase has
    touched anything, and compared once the whole layer stands and is animated.
    An applier that put its air materials in the shared family, that renamed one,
    or that let a rebuild orphan and re-create one would change the set.
    """
    state = _canonical_animated(context)
    assert _ld_material_names() == state["ld_materials"], sorted(
        _ld_material_names() ^ state["ld_materials"]
    )


def test_phase20_animates_nothing_it_does_not_own(context: dict) -> None:
    """Two animation systems, two namespaces -- and no camera in either.

    ``require_no_stray_animation`` refuses a Phase 20 action on a foreign
    datablock and a Phase 20 material curve on a material Phase 20 did not
    build. The camera clause is the one it cannot see: a lens keyed by accident
    would move the picture itself while every Phase 20 count stayed right. The
    curve counts come from the transition plan, so a layer that animated nothing
    cannot pass this by having nothing to complain about.
    """
    state = _canonical_animated(context)
    srm.require_no_stray_animation()
    for obj in bpy.data.objects:
        if obj.type != "CAMERA":
            continue
        assert obj.animation_data is None, obj.name
        assert getattr(obj.data, "animation_data", None) is None, obj.name

    planned = state["motions"]["leg1"]["summary"]["directives_by_channel"]
    summary = srm.motion_summary()
    assert summary["air_volumes_animated"] == planned["district_air"]
    assert summary["stones_animated"] == planned["memory_record"]


# ---------------------------------------------------------------------------
# The endpoint contract, over the real canonical chain
# ---------------------------------------------------------------------------


def test_both_legs_land_on_their_own_static_endpoints(context: dict) -> None:
    """ENDPOINT EQUIVALENCE for episode 0 to 1 and episode 1 to 2.

    Frame one is the ordinary static application of the earlier export and the
    last frame the static application of the later one. Both sides are MEASURED
    scenes, so an animation that eased towards a plausible-looking value rather
    than towards the value the static layer actually writes is caught, and so is
    a stone that appeared on the wrong side of its own window.
    """
    for name in ("leg1", "leg2"):
        verdict = _leg(context, name)
        assert verdict["before"]["equivalent"], (name, verdict["before"])
        assert verdict["after"]["equivalent"], (name, verdict["after"])
        assert verdict["equivalent"], (name, verdict)


def test_the_transition_genuinely_moves_between_its_endpoints(context: dict) -> None:
    """NON-VACUITY. Two identical endpoints and no motion would satisfy the check too.

    The set of districts whose air is animated is pinned against the districts
    the plan describes, so this is a leg where scarcity really moved in every
    one of them; then the mid-transition reading is required to differ from BOTH
    ends. A layer that keyed only the endpoints, or that wrote a flat curve,
    would pass endpoint equivalence and fail here.
    """
    state = _prepare(context)
    verdict = _leg(context, "leg1")
    motion = state["motions"]["leg1"]
    assert verdict["animated_channels"] == sorted(motion["summary"]["directives_by_channel"])
    assert verdict["animated_channels"] == ["district_air", "memory_record"]

    changed = sorted(
        directive["semantic_id"]
        for directive in motion["directives"]
        if directive["channel"] == "district_air"
    )
    assert changed == _air_ids(state["plans"]["mid"])

    timeline = state["timeline"]
    middle = (timeline["transition_start"] + timeline["transition_end"]) // 2
    start = srm.air_state_at(timeline["start_frame"])
    during = srm.air_state_at(middle)
    end = srm.air_state_at(timeline["end_frame"])
    for district in changed:
        assert abs(start[district] - end[district]) > 1.0e-6, district
        assert abs(during[district] - start[district]) > 1.0e-6, district
        assert abs(during[district] - end[district]) > 1.0e-6, district


def test_a_perturbed_air_curve_breaks_the_endpoint_check(context: dict) -> None:
    """The endpoint check BITES, and its two halves are genuinely independent.

    One district's final air key is moved and nothing else. ``air_equivalent``
    must go false while ``objects_equivalent`` stays true: if the verdict were
    one flag wearing two names, or if the air comparison read the plan rather
    than the curve, this would still pass and prove nothing.
    """
    state = _prepare(context)
    plans, spec, timeline = state["plans"], state["spec"], state["timeline"]
    motion = state["motions"]["leg1"]

    expected = srm.static_state(plans["mid"], spec)
    srm.apply_state_response_motion(motion, timeline)
    state["leg"] = None

    district = sorted(
        directive["semantic_id"]
        for directive in motion["directives"]
        if directive["channel"] == "district_air"
    )[0]
    tree = bpy.data.materials[f"{AIR_MATERIAL_PREFIX}{district}"].node_tree
    curve = next(
        entry
        for entry in tree.animation_data.action.fcurves
        if entry.data_path.endswith("default_value")
    )
    try:
        last = curve.keyframe_points[-1]
        last.co[1] = last.co[1] + 0.25
        curve.update()
        verdict = srm.compare_endpoint(_measured_endpoint(timeline["end_frame"]), expected)
        assert not verdict["air_equivalent"], "the lie must be caught"
        assert verdict["objects_equivalent"], "the objects were never touched"
        assert not verdict["equivalent"], "equivalent must mean BOTH halves"
    finally:
        # Editing a keyframe's ``co`` in place does not reliably invalidate
        # Blender's evaluation, so the layer is rebuilt from the plan rather
        # than un-edited. Re-application is idempotent by contract, which makes
        # this both a clean restore and one more exercise of it.
        sr.apply_state_response(plans["mid"], spec)
        srm.apply_state_response_motion(motion, timeline)
        state["leg"] = None
    healed = srm.compare_endpoint(_measured_endpoint(timeline["end_frame"]), expected)
    assert healed["equivalent"], f"rebuilding from the plan must heal the endpoint: {healed}"


# ---------------------------------------------------------------------------
# The Phase 19 recovery contract
# ---------------------------------------------------------------------------


def test_clearing_the_layer_restores_the_pre_phase20_scene(context: dict) -> None:
    """REMOVABILITY, proved by comparison with the scene Phase 20 was handed.

    Runs LAST on purpose -- it tears the layer down, so anything after it would
    be measuring an empty layer. The snapshot is required to DIFFER while the
    layer stands, which is what stops the comparison passing because there was
    never anything there to remove.
    """
    state = _prepare(context)
    _canonical_animated(context)
    assert _object_snapshot() != state["pre_phase20"], "the layer must be standing first"

    sr.clear_state_response_layer()
    bpy.context.view_layer.update()

    assert _object_snapshot() == state["pre_phase20"]
    assert [obj.name for obj in bpy.data.objects if obj.name.startswith(sr.OBJECT_PREFIX)] == []
    assert [
        material.name
        for material in bpy.data.materials
        if material.name.startswith(sr.MATERIAL_PREFIX)
    ] == []
    assert [mesh.name for mesh in bpy.data.meshes if mesh.name.startswith(sr.MESH_PREFIX)] == []
    assert [
        action.name for action in bpy.data.actions if action.name.startswith(sr.ACTION_PREFIX)
    ] == []
    assert bpy.data.collections.get("LD_STATE_RESPONSE") is None
    assert _ld_material_names() == state["ld_materials"]
