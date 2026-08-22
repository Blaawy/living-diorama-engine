"""In-Blender structural tests for Phase 22 cinematic direction.

Runs inside ``blender --background --factory-startup`` where ``bpy`` exists;
ordinary pytest never imports this. It asserts the things only a real Blender
scene can settle: that the catalogued anchors actually exist as cameras standing
at their locked locations, aimed by the builders' own look-at derivation,
carrying their locked lens, far clip and depth of field; that the applier's
pure-Python pose mathematics agrees with real ``mathutils``; that markers bind
to the anchors and Blender's own frame evaluation selects the planned camera at
every cut; that applying twice converges; that a drifted anchor or a competing
foreign camera-bound marker fails closed; and above all that nothing outside
Phase 22's ownership moved.

The world under test is the real animated one: the locked Phase 15 founding
scene, the Phase 16 production city, and the Phase 17 motion plan for the first
canonical transition, built by ``apply_motion_plan.build_motion_scene`` exactly
as the locked Phase 17 suite builds it -- so the F-curve immutability assertions
here are made against genuine Phase 17 animation, not an empty action list.

The negative tests mutate a camera, prove the refusal, and restore the exact
prior values before the next assertion; the applier itself never writes any of
it, and ``test_applying_changes_no_camera`` holds the final word on that.

The applier's decision logic is covered without Blender in
``tests/cinematic/test_cinematic_applier.py`` against a fake ``bpy``; what lives
here is everything that fake cannot honestly model.
"""

import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
for directory in (str(TESTS_DIR), str(SCRIPTS_DIR)):
    if directory not in sys.path:
        sys.path.insert(0, directory)

import apply_cinematic_direction as applier  # noqa: E402
import apply_motion_plan as motion  # noqa: E402
from motion_time_spec import load_motion_time_spec  # noqa: E402

STYLE = "dna"

POSE_TOLERANCE = 1e-4
"""Slack for float32 storage of locations and reconstructed view axes.

Measured worst drift across all fourteen anchors: 2.3e-7. Three orders of
magnitude of margin, while any real move or re-aim is many orders larger.
"""

_STATE: dict = {}


def _prepare(context: dict) -> dict:
    """Build the animated canonical world once, and cache what the suite needs.

    The scene is the Phase 17 motion scene for the first canonical transition
    (before -> mid), which carries every camera anchor, the locked frame range,
    and genuine Phase 17 F-curves for the immutability assertions to bite on.
    """
    if _STATE:
        return _STATE
    motion.build_motion_scene(
        context["spec_path"],
        context["production_path"],
        context["before_path"],
        context["mid_path"],
        context["motion_path"],
        style=STYLE,
    )
    _STATE.update(
        {
            "plans": context["shot_plans"],
            "catalogue": context["catalogue"],
            "motion_bytes": Path(context["motion_path"]).read_bytes(),
        }
    )
    return _STATE


def _cameras() -> dict:
    return {obj.name: obj for obj in bpy.data.objects if obj.type == "CAMERA"}


def _camera_state() -> dict:
    """A snapshot of everything about every camera that must not change."""
    state = {}
    for name, obj in _cameras().items():
        state[name] = (
            tuple(round(value, 6) for value in obj.location),
            tuple(round(value, 6) for value in obj.rotation_euler),
            tuple(round(value, 6) for value in obj.scale),
            obj.rotation_mode,
            obj.data.type,
            round(obj.data.lens, 6),
            round(obj.data.sensor_width, 6),
            round(obj.data.sensor_height, 6),
            obj.data.sensor_fit,
            round(obj.data.shift_x, 6),
            round(obj.data.shift_y, 6),
            round(obj.data.clip_start, 6),
            round(obj.data.clip_end, 6),
            bool(obj.data.dof.use_dof),
            round(obj.data.dof.focus_distance, 6),
            round(obj.data.dof.aperture_fstop, 6),
            round(obj.data.dof.aperture_ratio, 6),
            obj.data.dof.aperture_blades,
            round(obj.data.dof.aperture_rotation, 6),
            obj.animation_data is not None,
        )
    return state


def _object_state() -> dict:
    """Object count and mesh vertex totals, to prove geometry is untouched."""
    return {
        "objects": len(bpy.data.objects),
        "meshes": len(bpy.data.meshes),
        "materials": len(bpy.data.materials),
        "vertices": sum(len(mesh.vertices) for mesh in bpy.data.meshes),
        "cameras": len(bpy.data.cameras),
    }


def _fcurve_signature() -> list:
    signature = []
    for action in bpy.data.actions:
        for curve in action.fcurves:
            signature.append(
                (action.name, curve.data_path, curve.array_index, len(curve.keyframe_points))
            )
    return sorted(signature)


def _apply(state: dict, plan_name: str = "leg1") -> dict:
    return applier.apply_shot_direction_plan(bpy, state["plans"][plan_name], state["catalogue"])


# ----------------------------------------------------- the anchors are locked


def test_the_catalogue_matches_the_locked_configs(context: dict) -> None:
    """The mechanical cross-check, run against the shipped configs in-gate."""
    state = _prepare(context)
    configs = {
        "master_scene_v1": json.loads(Path(context["spec_path"]).read_text(encoding="utf-8"))[
            "cameras"
        ],
        "production_world_v1": json.loads(
            Path(context["production_path"]).read_text(encoding="utf-8")
        )["cameras"],
    }
    built = set(configs["master_scene_v1"]) | set(configs["production_world_v1"])
    assert set(state["catalogue"]) == built, "catalogue names differ from the configs"
    for anchor, record in state["catalogue"].items():
        locked = configs[record["source"]][anchor]
        assert list(record["location"]) == locked["location"], anchor
        assert list(record["look_at"]) == locked["look_at"], anchor
        assert record["lens_mm"] == locked["lens_mm"], anchor
        assert record["f_stop"] == locked["f_stop"], anchor
        assert list(record["focus"]) == locked.get("focus", locked["look_at"]), anchor


def test_every_catalogued_anchor_exists_as_a_camera(context: dict) -> None:
    """The catalogue is a claim about the built scene; here it is checked."""
    state = _prepare(context)
    cameras = _cameras()
    for anchor in state["catalogue"]:
        assert anchor in cameras, f"catalogued anchor {anchor} is absent from the scene"


def test_every_anchor_stands_at_its_locked_location(context: dict) -> None:
    """The review's central defect: V1 never proved where a camera stood."""
    state = _prepare(context)
    cameras = _cameras()
    for anchor, record in state["catalogue"].items():
        actual = tuple(cameras[anchor].location)
        for axis, (measured, locked) in enumerate(zip(actual, record["location"], strict=True)):
            assert abs(measured - locked) < POSE_TOLERANCE, (
                f"{anchor} axis {axis}: stands at {measured}, locked at {locked}"
            )


def test_every_anchor_aims_along_its_locked_look_at(context: dict) -> None:
    """Orientation is proven against the builders' own derivation, in Blender.

    The expectation is recomputed with real ``mathutils`` -- the identical
    ``to_track_quat("-Z", "Y")`` call the builders make -- and compared as a
    rotation difference, so no euler-wrapping ambiguity can hide a re-aim.
    """
    state = _prepare(context)
    cameras = _cameras()
    for anchor, record in state["catalogue"].items():
        camera = cameras[anchor]
        direction = Vector(record["look_at"]) - Vector(record["location"])
        expected = direction.to_track_quat("-Z", "Y")
        actual = camera.rotation_euler.to_quaternion()
        angle = actual.rotation_difference(expected).angle
        assert angle < 1e-3, f"{anchor} is re-aimed by {angle} radians"


def test_the_appliers_pure_pose_math_agrees_with_mathutils(context: dict) -> None:
    """The fake-bpy suite leans on this math; here it meets real mathutils."""
    state = _prepare(context)
    cameras = _cameras()
    for anchor, record in state["catalogue"].items():
        camera = cameras[anchor]
        pure_forward, pure_up = applier._view_axes_from_euler(tuple(camera.rotation_euler))
        matrix = camera.rotation_euler.to_matrix()
        real_forward = tuple(-matrix.col[2][i] for i in range(3))
        real_up = tuple(matrix.col[1][i] for i in range(3))
        for mine, real in ((pure_forward, real_forward), (pure_up, real_up)):
            for a, b in zip(mine, real, strict=True):
                assert abs(a - b) < 1e-6, f"{anchor}: pure math diverges from mathutils"
        expected_forward, expected_up = applier._expected_view_axes(
            record["location"], record["look_at"]
        )
        for mine, real in ((expected_forward, real_forward), (expected_up, real_up)):
            for a, b in zip(mine, real, strict=True):
                assert abs(a - b) < POSE_TOLERANCE, (
                    f"{anchor}: expected axes diverge from the built camera"
                )


def test_every_anchor_carries_its_locked_lens_clip_and_aperture(context: dict) -> None:
    """Lens, clips, projection, sensor, shift, depth of field: all proven.

    The projection-geometry fields (sensor width, shifts, near clip, camera
    type) are the supported Blender's factory defaults, inherited by every
    camera the locked build produces -- this test is where those restated
    defaults meet the actually built scene, so a Blender whose defaults differ
    fails loudly here instead of silently re-framing every shot.
    """
    state = _prepare(context)
    cameras = _cameras()
    for anchor, record in state["catalogue"].items():
        data = cameras[anchor].data
        assert abs(data.lens - record["lens_mm"]) < 1e-3, anchor
        assert abs(data.clip_end - record["clip_end"]) < 1e-3, anchor
        assert abs(data.clip_start - record["clip_start"]) < 1e-3, anchor
        assert data.type == record["projection"], anchor
        assert abs(data.sensor_width - record["sensor_width_mm"]) < 1e-3, anchor
        assert abs(data.sensor_height - record["sensor_height_mm"]) < 1e-3, anchor
        assert data.sensor_fit == record["sensor_fit"], anchor
        assert abs(data.shift_x - record["shift_x"]) < 1e-4, anchor
        assert abs(data.shift_y - record["shift_y"]) < 1e-4, anchor
        assert bool(data.dof.use_dof) == bool(record["dof"]), anchor
        if record["dof"]:
            assert abs(data.dof.aperture_fstop - record["f_stop"]) < 1e-3, anchor
            assert abs(data.dof.aperture_ratio - record["aperture_ratio"]) < 1e-4, anchor
            assert data.dof.aperture_blades == record["aperture_blades"], anchor
            assert abs(data.dof.aperture_rotation - record["aperture_rotation"]) < 1e-4, anchor
            focus_distance = math.sqrt(
                sum((a - b) ** 2 for a, b in zip(record["focus"], record["location"], strict=True))
            )
            assert abs(data.dof.focus_distance - focus_distance) < 1e-3, anchor


def test_no_catalogued_anchor_is_animated(context: dict) -> None:
    """V1 forbids camera animation outright."""
    state = _prepare(context)
    cameras = _cameras()
    for anchor in state["catalogue"]:
        assert cameras[anchor].animation_data is None, f"{anchor} carries animation data"
        assert cameras[anchor].data.animation_data is None, f"{anchor} lens is animated"


# --------------------------------------------------- the clock binding holds


def test_every_plan_binds_the_shipped_motion_time_document(context: dict) -> None:
    """The digest each plan carries is the canonical pin, absolutely.

    The V2 form of this test was relative -- plan digest versus the digest of
    whatever ``--motion`` file the gate was handed, which a wrong file would
    satisfy wholesale. The comparison now goes through the applier's PINNED
    constant, so the gate proves the plans bind THE canonical Phase 17 source,
    and separately that the file the prior suites consumed is that source too.
    """
    state = _prepare(context)
    digest = hashlib.sha256(state["motion_bytes"]).hexdigest()
    assert digest == applier.CANONICAL_MOTION_TIME_SHA256, (
        "the --motion file handed to this gate is not the canonical Phase 17 source"
    )
    for name, plan in state["plans"].items():
        assert plan["source"]["motion_time_sha256"] == applier.CANONICAL_MOTION_TIME_SHA256, name
        assert plan["source"]["motion_time_format"] == "living_diorama_motion_time", name
        assert plan["source"]["motion_time_schema_version"] == 1, name


def test_every_plan_binds_the_approved_catalogue(context: dict) -> None:
    """Every catalogue binding is ABSOLUTE: the approved pinned identity.

    The relative form (plan versus supplied file) would be satisfied by a
    forged pair; the comparison goes through the applier's pinned constant, and
    the supplied catalogue must hash to the same identity.
    """
    state = _prepare(context)
    supplied = applier._catalogue_digest(state["catalogue"])
    assert supplied == applier.APPROVED_CATALOGUE_SHA256, (
        "the --catalogue file handed to this gate is not the approved catalogue"
    )
    for name, plan in state["plans"].items():
        assert plan["source"]["catalogue_sha256"] == applier.APPROVED_CATALOGUE_SHA256, name


def test_every_plan_timeline_matches_phase17s_own_resolver(context: dict) -> None:
    """The restated arithmetic is proven against ``motion_time_spec`` itself.

    Phase 22 never imports Phase 17, so its planner restates the timeline
    derivation as data. This test is where the restatement meets the owner: the
    resolver's numbers and the plan's numbers must be identical.
    """
    state = _prepare(context)
    resolved = load_motion_time_spec(context["motion_path"])["timeline"]
    for name, plan in state["plans"].items():
        timeline = plan["timeline"]
        for field in (
            "fps",
            "start_frame",
            "start_hold_frames",
            "transition_frames",
            "end_hold_frames",
            "transition_start",
            "transition_end",
            "end_frame",
        ):
            assert timeline[field] == resolved[field], (name, field)


# ------------------------------------------------------------ applying binds


def test_applying_binds_one_marker_per_shot(context: dict) -> None:
    """Applying binds one marker per shot."""
    state = _prepare(context)
    report = _apply(state)
    plan = state["plans"]["leg1"]
    assert report["markers_bound"] == len(plan["shots"])
    owned = [
        m for m in bpy.context.scene.timeline_markers if m.name.startswith(applier.MARKER_PREFIX)
    ]
    assert len(owned) == len(plan["shots"])


def test_each_marker_binds_the_planned_camera(context: dict) -> None:
    """Each marker binds the planned camera."""
    state = _prepare(context)
    _apply(state)
    by_frame = {
        m.frame: m.camera.name
        for m in bpy.context.scene.timeline_markers
        if m.name.startswith(applier.MARKER_PREFIX)
    }
    for shot in state["plans"]["leg1"]["shots"]:
        assert by_frame[shot["start_frame"]] == shot["camera_anchor_id"]


def test_blender_itself_selects_the_planned_camera_at_every_cut(context: dict) -> None:
    """Frame evaluation, not the helper: Blender's active camera at real frames.

    For every plan, the scene is stepped to each shot's first, middle and last
    frame and the scene's actual active camera -- the one Blender would render
    through -- must be the planned anchor.
    """
    state = _prepare(context)
    scene = bpy.context.scene
    for name, plan in state["plans"].items():
        applier.apply_shot_direction_plan(bpy, plan, state["catalogue"])
        for shot in plan["shots"]:
            middle = (shot["start_frame"] + shot["end_frame"]) // 2
            for frame in (shot["start_frame"], middle, shot["end_frame"]):
                scene.frame_set(frame)
                actual = scene.camera.name if scene.camera else None
                assert actual == shot["camera_anchor_id"], (
                    f"{name} {shot['shot_id']}: Blender renders through {actual} at frame "
                    f"{frame}, the plan says {shot['camera_anchor_id']}"
                )


def test_the_actual_camera_at_frame_one_equals_frame_193(context: dict) -> None:
    """Loop closure proven on Blender's own evaluation, for every plan."""
    state = _prepare(context)
    scene = bpy.context.scene
    for name, plan in state["plans"].items():
        applier.apply_shot_direction_plan(bpy, plan, state["catalogue"])
        scene.frame_set(plan["timeline"]["start_frame"])
        first = scene.camera.name
        scene.frame_set(plan["timeline"]["end_frame"])
        last = scene.camera.name
        assert first == last, f"{name}: loop jumps from {first} to {last}"


def test_every_frame_of_the_timeline_has_an_active_camera(context: dict) -> None:
    """The shots tile the timeline, so no frame is left undirected."""
    state = _prepare(context)
    _apply(state)
    scene = bpy.context.scene
    timeline = state["plans"]["leg1"]["timeline"]
    for frame in range(timeline["start_frame"], timeline["end_frame"] + 1):
        assert applier.camera_at_frame(scene, frame) in state["catalogue"]


def test_applying_twice_is_idempotent(context: dict) -> None:
    """Applying twice is idempotent."""
    state = _prepare(context)
    _apply(state)
    first = sorted(
        (m.name, m.frame, m.camera.name)
        for m in bpy.context.scene.timeline_markers
        if m.name.startswith(applier.MARKER_PREFIX)
    )
    _apply(state)
    second = sorted(
        (m.name, m.frame, m.camera.name)
        for m in bpy.context.scene.timeline_markers
        if m.name.startswith(applier.MARKER_PREFIX)
    )
    assert first == second


# ------------------------------------------------------- nothing else moved


def test_applying_changes_no_camera(context: dict) -> None:
    """The whole point of V1: cameras are selected, never touched."""
    state = _prepare(context)
    before = _camera_state()
    for plan in state["plans"].values():
        applier.apply_shot_direction_plan(bpy, plan, state["catalogue"])
    assert _camera_state() == before


def test_applying_changes_no_geometry_or_material(context: dict) -> None:
    """Applying changes no geometry or material."""
    state = _prepare(context)
    before = _object_state()
    _apply(state)
    assert _object_state() == before


def test_applying_changes_no_phase17_animation(context: dict) -> None:
    """Phase 17's F-curves are locked and must survive direction untouched."""
    state = _prepare(context)
    before = _fcurve_signature()
    assert before, "the motion scene must carry genuine Phase 17 F-curves"
    _apply(state)
    assert _fcurve_signature() == before


def test_applying_never_removes_a_foreign_marker(context: dict) -> None:
    """Somebody else's timeline state is left exactly as found."""
    state = _prepare(context)
    scene = bpy.context.scene
    foreign = scene.timeline_markers.new("FOREIGN_MARKER", frame=3)
    try:
        _apply(state)
        assert any(m.name == "FOREIGN_MARKER" for m in scene.timeline_markers)
    finally:
        scene.timeline_markers.remove(foreign)


# ------------------------------------------------------------- fail closed


def test_a_foreign_camera_bound_marker_fails_closed(context: dict) -> None:
    """A competing camera-bound marker is refused, and never deleted."""
    state = _prepare(context)
    scene = bpy.context.scene
    foreign = scene.timeline_markers.new("SOMEONE_ELSES_CUT", frame=40)
    foreign.camera = _cameras()["CAM_P16_ROADS"]
    try:
        try:
            _apply(state)
        except applier.CinematicApplyError:
            assert any(m.name == "SOMEONE_ELSES_CUT" for m in scene.timeline_markers)
        else:
            raise AssertionError("a foreign camera-bound marker was accepted")
    finally:
        scene.timeline_markers.remove(foreign)
    _apply(state)


def test_a_moved_anchor_fails_closed(context: dict) -> None:
    """The review's live mutation: a relocated camera under the right name."""
    state = _prepare(context)
    camera = _cameras()["CAM_SEAL_DETAIL"]
    original = tuple(camera.location)
    camera.location = (original[0] + 0.5, original[1], original[2])
    try:
        try:
            _apply(state)
        except applier.CinematicApplyError:
            pass
        else:
            raise AssertionError("a moved anchor was accepted")
    finally:
        camera.location = original
    _apply(state)


def test_a_rotated_anchor_fails_closed(context: dict) -> None:
    """A re-aimed camera under the right name is refused."""
    state = _prepare(context)
    camera = _cameras()["CAM_SEAL_DETAIL"]
    original = tuple(camera.rotation_euler)
    camera.rotation_euler = (original[0], original[1], original[2] + 0.02)
    try:
        try:
            _apply(state)
        except applier.CinematicApplyError:
            pass
        else:
            raise AssertionError("a rotated anchor was accepted")
    finally:
        camera.rotation_euler = original
    _apply(state)


def test_a_relensed_anchor_fails_closed(context: dict) -> None:
    """A renamed lens is a different shot; it must be caught here."""
    state = _prepare(context)
    camera = _cameras()["CAM_SEAL_DETAIL"]
    original = camera.data.lens
    camera.data.lens = 50.0
    try:
        try:
            _apply(state)
        except applier.CinematicApplyError:
            pass
        else:
            raise AssertionError("a re-lensed anchor was accepted")
    finally:
        camera.data.lens = original
    _apply(state)


def test_a_reapertured_anchor_fails_closed(context: dict) -> None:
    """The review's f-stop 999 mutation, against the real datablock."""
    state = _prepare(context)
    camera = _cameras()["CAM_SEAL_DETAIL"]
    original = camera.data.dof.aperture_fstop
    camera.data.dof.aperture_fstop = 999.0
    try:
        try:
            _apply(state)
        except applier.CinematicApplyError:
            pass
        else:
            raise AssertionError("a re-apertured anchor was accepted")
    finally:
        camera.data.dof.aperture_fstop = original
    _apply(state)


def test_a_missing_anchor_fails_closed(context: dict) -> None:
    """A renamed anchor must never be silently substituted."""
    state = _prepare(context)
    camera = _cameras()["CAM_SCAR_DETAIL"]
    camera.name = "CAM_SCAR_DETAIL_RENAMED"
    try:
        try:
            _apply(state)
        except applier.CinematicApplyError:
            pass
        else:
            raise AssertionError("a missing anchor was accepted")
    finally:
        camera.name = "CAM_SCAR_DETAIL"
    _apply(state)


def test_a_scene_frame_range_mismatch_fails_closed(context: dict) -> None:
    """Phase 22 directs the locked timeline, not whatever the scene happens to be."""
    state = _prepare(context)
    scene = bpy.context.scene
    original = scene.frame_end
    scene.frame_end = original + 10
    try:
        try:
            _apply(state)
        except applier.CinematicApplyError:
            return
        raise AssertionError("a mismatched frame range was accepted")
    finally:
        scene.frame_end = original
