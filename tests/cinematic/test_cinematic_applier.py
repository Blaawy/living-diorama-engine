"""The Blender applier, exercised against a faithful fake ``bpy``.

Blender itself is not importable in ordinary pytest, and the in-Blender suite
under ``visual/blender/tests/`` only runs inside
``blender --background --factory-startup``. That would leave the applier's actual
decisions — which marker, bound to which camera, at which frame, and what it
refuses — untested by the ordinary suite.

So the parts of Blender the applier touches are modelled here: objects with a
name, a type, a transform and camera data carrying lens, clip, depth of field
and animation state, plus a timeline marker collection that behaves like
Blender's. Each fake camera is built with the builders' own recipe — the locked
location, and a rotation derived from the locked look-at point — using an
independent matrix construction, so the applier's euler reconstruction is met by
an implementation it does not share. The fake is deliberately small; anything it
cannot model faithfully belongs in the in-Blender suite instead, and is asserted
there against real ``mathutils`` and real float32 storage.

What these tests prove is the applier's logic: it refuses a missing, ambiguous,
non-camera, moved, rotated, re-lensed, re-apertured, re-focused, re-clipped or
animated anchor and any foreign camera-bound marker competing for the directed
frames; it binds one marker per shot; it removes only its own markers; and
applying the same plan twice converges rather than accumulating.
"""

import math
import sys
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cinematic import CAMERA_ANCHORS, build_shot_direction_plan_document

SCRIPTS = Path(__file__).resolve().parents[2] / "visual" / "blender" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import apply_cinematic_direction as applier  # noqa: E402

# ------------------------------------------------------------- the fake bpy


def _euler_for_view(location: tuple, look_at: tuple) -> tuple:
    """The XYZ euler a look-at camera stores, derived independently.

    Builds the rotation matrix column by column — camera ``-Z`` along the view
    direction, camera ``+Y`` rolled toward world ``+Z`` (world ``+Y`` when
    looking straight down, Blender's own degenerate convention, measured) — and
    extracts the XYZ euler from it. The applier reconstructs view axes *from*
    an euler; this goes the other way, so the two meeting in the middle is a
    genuine check rather than an identity.
    """
    direction = tuple(a - b for a, b in zip(look_at, location, strict=True))
    length = math.sqrt(sum(component**2 for component in direction))
    forward = tuple(component / length for component in direction)
    projected = (
        -forward[2] * forward[0],
        -forward[2] * forward[1],
        1.0 - forward[2] * forward[2],
    )
    magnitude = math.sqrt(sum(component**2 for component in projected))
    up = (0.0, 1.0, 0.0) if magnitude < 1e-6 else tuple(c / magnitude for c in projected)
    z_axis = tuple(-component for component in forward)
    x_axis = (
        up[1] * z_axis[2] - up[2] * z_axis[1],
        up[2] * z_axis[0] - up[0] * z_axis[2],
        up[0] * z_axis[1] - up[1] * z_axis[0],
    )
    rotation = [
        [x_axis[0], up[0], z_axis[0]],
        [x_axis[1], up[1], z_axis[1]],
        [x_axis[2], up[2], z_axis[2]],
    ]
    ey = math.asin(max(-1.0, min(1.0, -rotation[2][0])))
    ex = math.atan2(rotation[2][1], rotation[2][2])
    ez = math.atan2(rotation[1][0], rotation[0][0])
    return (ex, ey, ez)


def _rows_from_location_euler(location: tuple, euler: tuple) -> tuple:
    """Build the 4x4 world-matrix rows a transform-free object would carry.

    ``R = Rz @ Ry @ Rx`` (Blender XYZ euler), translation from the location,
    unit scale -- the same independent construction the fake cameras use for
    their rotation, extended to the full matrix so the applier's evaluated
    world-matrix seal can be met (and broken) by the fakes.
    """
    ex, ey, ez = euler
    cx, sx = math.cos(ex), math.sin(ex)
    cy, sy = math.cos(ey), math.sin(ey)
    cz, sz = math.cos(ez), math.sin(ez)
    rotation = (
        (cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx),
        (sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx),
        (-sy, cy * sx, cy * cx),
    )
    return (
        (*rotation[0], location[0]),
        (*rotation[1], location[1]),
        (*rotation[2], location[2]),
        (0.0, 0.0, 0.0, 1.0),
    )


class FakeDof:
    """The depth-of-field block, reduced to the fields the applier proves."""

    def __init__(self, use_dof: bool, focus_distance: float, aperture_fstop: float) -> None:
        """Hold a depth-of-field state, bokeh factory defaults included."""
        self.use_dof = use_dof
        self.focus_distance = focus_distance
        self.aperture_fstop = aperture_fstop
        self.aperture_ratio = 1.0
        self.aperture_blades = 0
        self.aperture_rotation = 0.0
        self.focus_object = None


class FakeCameraData:
    """The camera datablock: lens, clips, projection, sensor, depth of field."""

    def __init__(self, lens: float, clip_end: float, dof: FakeDof) -> None:
        """Hold the lensed identity of one camera, factory defaults included."""
        self.lens = lens
        self.clip_end = clip_end
        self.clip_start = 0.1
        self.type = "PERSP"
        self.sensor_width = 36.0
        self.sensor_height = 24.0
        self.sensor_fit = "AUTO"
        self.shift_x = 0.0
        self.shift_y = 0.0
        self.dof = dof
        self.animation_data = None


class FakeObject:
    """A scene object: name, type, transform, and camera data when lensed."""

    def __init__(
        self,
        name: str,
        kind: str = "CAMERA",
        data: FakeCameraData | None = None,
        location: tuple = (0.0, 0.0, 0.0),
        rotation_euler: tuple = (0.0, 0.0, 0.0),
    ):
        """Build an object of the given type, factory transform state included."""
        self.name = name
        self.type = kind
        self.data = data
        self.location = location
        self.rotation_euler = rotation_euler
        self.rotation_mode = "XYZ"
        self.scale = (1.0, 1.0, 1.0)
        self.animation_data = None
        self.parent = None
        self.constraints: list = []
        self.delta_location = (0.0, 0.0, 0.0)
        self.delta_rotation_euler = (0.0, 0.0, 0.0)
        self.delta_rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
        self.delta_scale = (1.0, 1.0, 1.0)
        self.matrix_world_override: tuple | None = None

    @property
    def matrix_world(self) -> tuple:
        """The evaluated world matrix, derived from the local transform.

        Real Blender folds parents, constraints and deltas into this; the fake
        derives it from location and rotation alone, which is exactly the
        unparented, unconstrained, delta-free case -- so the field-level
        refusals are exercised by mutating those fields directly, and the
        matrix seal itself is exercised through ``matrix_world_override``.
        """
        if self.matrix_world_override is not None:
            return self.matrix_world_override
        return _rows_from_location_euler(self.location, self.rotation_euler)


def _camera_from_record(name: str, record: dict) -> FakeObject:
    """Build one fake anchor exactly as the world builders would."""
    focus_distance = math.sqrt(
        sum((a - b) ** 2 for a, b in zip(record["focus"], record["location"], strict=True))
    )
    dof = FakeDof(bool(record["dof"]), focus_distance, float(record["f_stop"]))
    data = FakeCameraData(float(record["lens_mm"]), float(record["clip_end"]), dof)
    return FakeObject(
        name,
        "CAMERA",
        data,
        location=tuple(record["location"]),
        rotation_euler=_euler_for_view(record["location"], record["look_at"]),
    )


class FakeMarker:
    """A timeline marker, which may bind a camera from its frame onward."""

    def __init__(self, name: str, frame: int) -> None:
        """Build an unbound marker at a frame."""
        self.name = name
        self.frame = frame
        self.camera: FakeObject | None = None


class FakeMarkers:
    """Blender's marker collection: appendable, removable, iterable."""

    def __init__(self) -> None:
        """Start with an empty timeline."""
        self._markers: list[FakeMarker] = []

    def new(self, name: str, frame: int) -> FakeMarker:
        """Create and register a marker, as Blender does."""
        marker = FakeMarker(name, frame)
        self._markers.append(marker)
        return marker

    def remove(self, marker: FakeMarker) -> None:
        """Remove one marker, as Blender does."""
        self._markers.remove(marker)

    def __iter__(self):
        """Iterate over a snapshot, so removal during iteration is safe."""
        return iter(list(self._markers))

    def __len__(self) -> int:
        """How many markers the timeline holds."""
        return len(self._markers)


class FakeRender:
    """The render settings the applier's execution-clock gate reads."""

    def __init__(self) -> None:
        """Start at the supported Blender's factory clock and framing."""
        self.fps = 24
        self.fps_base = 1.0
        self.frame_map_old = 100
        self.frame_map_new = 100
        self.use_sequencer = True  # Blender's factory default; inert without strips
        self.use_multiview = False
        self.pixel_aspect_x = 1.0
        self.pixel_aspect_y = 1.0


class FakeViewLayer:
    """The view layer, reduced to the update call the applier makes."""

    def update(self) -> None:
        """A no-op: the fake world matrix is always current."""


class FakeScene:
    """A scene with a frame range, a marker collection, and an active camera."""

    def __init__(self, start: int, end: int) -> None:
        """Build a scene spanning the given frame range, on the factory clock."""
        self.frame_start = start
        self.frame_end = end
        self.frame_step = 1
        self.render = FakeRender()
        self.sequence_editor = None
        self.timeline_markers = FakeMarkers()
        self.camera: FakeObject | None = None


class FakeBpy:
    """The three attributes of ``bpy`` the applier actually touches."""

    def __init__(self, objects: list[FakeObject], scene: FakeScene) -> None:
        """Expose ``data.objects``, ``context.scene`` and ``context.view_layer``."""
        self.data = type("Data", (), {"objects": objects})()
        self.context = type("Context", (), {"scene": scene, "view_layer": FakeViewLayer()})()


@pytest.fixture
def scene() -> FakeScene:
    """A scene whose frame range is the locked Phase 17 timeline."""
    return FakeScene(1, 193)


@pytest.fixture
def objects() -> list[FakeObject]:
    """One correct camera object per catalogued anchor, plus some scenery."""
    built = [_camera_from_record(name, dict(record)) for name, record in CAMERA_ANCHORS.items()]
    built.append(FakeObject("WALL_boundary_ab", "MESH"))
    built.append(FakeObject("GROUND", "MESH"))
    return built


@pytest.fixture
def bpy(objects: list[FakeObject], scene: FakeScene) -> FakeBpy:
    """A fake Blender exposing exactly what the applier touches."""
    return FakeBpy(objects, scene)


@pytest.fixture
def plan(story_ep0_to_ep1: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """The real four-shot plan for the first canonical transition."""
    return build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)


@pytest.fixture
def catalogue() -> dict[str, Any]:
    """The anchor catalogue, passed to the applier as data."""
    return {name: dict(record) for name, record in CAMERA_ANCHORS.items()}


def _mutate(objects: list[FakeObject], name: str) -> FakeObject:
    """Return the named fake camera for a test to mutate."""
    return next(obj for obj in objects if obj.name == name)


# ------------------------------------------------------------------- applying


def test_it_binds_one_marker_per_shot(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """It binds one marker per shot."""
    report = applier.apply_shot_direction_plan(bpy, plan, catalogue)
    assert report["markers_bound"] == len(plan["shots"])
    assert len(bpy.context.scene.timeline_markers) == len(plan["shots"])


def test_every_marker_is_bound_to_the_planned_camera(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Every marker is bound to the planned camera."""
    applier.apply_shot_direction_plan(bpy, plan, catalogue)
    by_frame = {m.frame: m.camera.name for m in bpy.context.scene.timeline_markers}
    for shot in plan["shots"]:
        assert by_frame[shot["start_frame"]] == shot["camera_anchor_id"]


def test_every_marker_carries_the_phase22_prefix(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Ownership must be legible, or reconciliation would touch other state."""
    applier.apply_shot_direction_plan(bpy, plan, catalogue)
    for marker in bpy.context.scene.timeline_markers:
        assert marker.name.startswith(applier.MARKER_PREFIX)


def test_the_report_names_every_verified_anchor(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The report says which anchors were proven, for the gate log."""
    report = applier.apply_shot_direction_plan(bpy, plan, catalogue)
    assert report["anchors_verified"] == sorted({s["camera_anchor_id"] for s in plan["shots"]})


def test_the_scene_camera_is_the_opening_shot(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The scene camera is the opening shot."""
    applier.apply_shot_direction_plan(bpy, plan, catalogue)
    assert bpy.context.scene.camera.name == plan["shots"][0]["camera_anchor_id"]


def test_the_camera_at_frame_one_equals_the_camera_at_frame_193(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Loop closure, proven on the applied scene rather than only on the plan."""
    applier.apply_shot_direction_plan(bpy, plan, catalogue)
    scene = bpy.context.scene
    assert applier.camera_at_frame(scene, 1) == applier.camera_at_frame(scene, 193)


def test_the_baseline_plan_binds_a_single_marker(
    bpy: FakeBpy,
    story_ep0: dict[str, Any],
    motion_time: bytes,
    catalogue: dict[str, Any],
) -> None:
    """The baseline plan binds a single marker."""
    baseline = build_shot_direction_plan_document(story_ep0, motion_time)
    report = applier.apply_shot_direction_plan(bpy, baseline, catalogue)
    assert report["markers_bound"] == 1
    assert applier.camera_at_frame(bpy.context.scene, 193) == "CAM_HERO_WORLD"


# ---------------------------------------------------------------- idempotence


def test_applying_twice_does_not_accumulate_markers(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The reconcile rule, stated as a test."""
    applier.apply_shot_direction_plan(bpy, plan, catalogue)
    first = [(m.name, m.frame, m.camera.name) for m in bpy.context.scene.timeline_markers]
    report = applier.apply_shot_direction_plan(bpy, plan, catalogue)
    second = [(m.name, m.frame, m.camera.name) for m in bpy.context.scene.timeline_markers]
    assert report["markers_removed"] == len(plan["shots"])
    assert sorted(first) == sorted(second)
    assert len(bpy.context.scene.timeline_markers) == len(plan["shots"])


def test_it_never_removes_a_marker_it_does_not_own(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Somebody else's timeline state is left exactly as found."""
    scene = bpy.context.scene
    foreign = scene.timeline_markers.new("SOMEBODY_ELSES_MARKER", frame=50)
    applier.apply_shot_direction_plan(bpy, plan, catalogue)
    names = [m.name for m in scene.timeline_markers]
    assert foreign.name in names


def test_reapplying_a_different_plan_replaces_only_owned_markers(
    bpy: FakeBpy,
    plan: dict[str, Any],
    story_ep0: dict[str, Any],
    motion_time: bytes,
    catalogue: dict[str, Any],
) -> None:
    """Reapplying a different plan replaces only owned markers."""
    scene = bpy.context.scene
    scene.timeline_markers.new("FOREIGN", frame=7)
    applier.apply_shot_direction_plan(bpy, plan, catalogue)
    baseline = build_shot_direction_plan_document(story_ep0, motion_time)
    applier.apply_shot_direction_plan(bpy, baseline, catalogue)
    owned = [m for m in scene.timeline_markers if m.name.startswith(applier.MARKER_PREFIX)]
    assert len(owned) == 1
    assert any(m.name == "FOREIGN" for m in scene.timeline_markers)


# ------------------------------------------------------- camera immutability


def test_no_camera_transform_or_lens_is_touched(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The phase selects cameras; it never edits one."""

    def snapshot() -> dict:
        return {
            obj.name: (
                obj.type,
                tuple(obj.location),
                tuple(obj.rotation_euler),
                getattr(obj.data, "lens", None),
                getattr(obj.data, "clip_start", None),
                getattr(obj.data, "clip_end", None),
                getattr(obj.data, "type", None),
                getattr(obj.data, "sensor_width", None),
                getattr(obj.data, "sensor_height", None),
                getattr(obj.data, "sensor_fit", None),
                getattr(obj.data, "shift_x", None),
                getattr(obj.data, "shift_y", None),
            )
            for obj in bpy.data.objects
        }

    before = snapshot()
    applier.apply_shot_direction_plan(bpy, plan, catalogue)
    assert snapshot() == before


def test_the_applier_source_never_writes_a_camera_attribute() -> None:
    """A structural guard over the source itself, not just this fake run."""
    source = (SCRIPTS / "apply_cinematic_direction.py").read_text(encoding="utf-8")
    for forbidden in (
        ".location =",
        ".rotation_euler =",
        ".scale =",
        ".data.lens =",
        ".lens =",
        ".angle =",
        ".sensor_width =",
        ".sensor_height =",
        ".sensor_fit =",
        ".shift_x =",
        ".shift_y =",
        ".dof.use_dof =",
        ".dof.focus_distance =",
        ".dof.aperture_fstop =",
        ".dof.aperture_ratio =",
        ".dof.aperture_blades =",
        ".dof.aperture_rotation =",
        ".clip_start =",
        ".clip_end =",
        "matrix_world =",
        "keyframe_insert",
        "animation_data_create",
    ):
        assert forbidden not in source, forbidden


# ---------------------------------------------------------------- refusals


def test_a_missing_camera_object_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Phase 22 never substitutes another camera."""
    remaining = [obj for obj in objects if obj.name != "CAM_SEAL_DETAIL"]
    with pytest.raises(applier.CinematicApplyError, match="absent from the scene"):
        applier.apply_shot_direction_plan(FakeBpy(remaining, scene), plan, catalogue)


def test_a_duplicate_camera_object_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A duplicate camera object is refused."""
    objects.append(_camera_from_record("CAM_SEAL_DETAIL", dict(CAMERA_ANCHORS["CAM_SEAL_DETAIL"])))
    with pytest.raises(applier.CinematicApplyError, match="unambiguous"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_non_camera_under_a_camera_name_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A non camera under a camera name is refused."""
    swapped = [obj for obj in objects if obj.name != "CAM_SEAL_DETAIL"]
    swapped.append(FakeObject("CAM_SEAL_DETAIL", "MESH"))
    with pytest.raises(applier.CinematicApplyError, match="not a CAMERA"):
        applier.apply_shot_direction_plan(FakeBpy(swapped, scene), plan, catalogue)


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_a_moved_camera_is_refused_on_every_axis(
    axis: int,
    objects: list[FakeObject],
    scene: FakeScene,
    plan: dict[str, Any],
    catalogue: dict[str, Any],
) -> None:
    """The independent review's central mutation: a relocated anchor.

    V1 accepted a CAM_HERO_WORLD standing anywhere; every axis of drift must
    now fail closed.
    """
    camera = _mutate(objects, "CAM_HERO_WORLD")
    moved = list(camera.location)
    moved[axis] += 5.0
    camera.location = tuple(moved)
    with pytest.raises(applier.CinematicApplyError, match="has moved"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_subtly_moved_camera_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Even a millimetre of drift is a different viewpoint."""
    camera = _mutate(objects, "CAM_SEAL_DETAIL")
    camera.location = (camera.location[0] + 0.001, camera.location[1], camera.location[2])
    with pytest.raises(applier.CinematicApplyError, match="has moved"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_rotated_camera_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The review's second mutation: a re-aimed anchor with the right lens."""
    camera = _mutate(objects, "CAM_HERO_WORLD")
    ex, ey, ez = camera.rotation_euler
    camera.rotation_euler = (ex, ey, ez + 0.01)
    with pytest.raises(applier.CinematicApplyError, match="rotated"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_completely_wrong_pose_with_the_right_lens_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The review's exact reproduction: wrong location, wrong rotation, lens intact."""
    camera = _mutate(objects, "CAM_HERO_WORLD")
    camera.location = (0.0, 0.0, 999.0)
    camera.rotation_euler = (1.0, 2.0, 3.0)
    with pytest.raises(applier.CinematicApplyError):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_mutated_lens_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The anchor must still be the anchor the catalogue describes."""
    _mutate(objects, "CAM_SEAL_DETAIL").data.lens = 50.0
    with pytest.raises(applier.CinematicApplyError, match="has been mutated"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_mutated_f_stop_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The review's third mutation: f-stop 999 was accepted by V1."""
    _mutate(objects, "CAM_HERO_WORLD").data.dof.aperture_fstop = 999.0
    with pytest.raises(applier.CinematicApplyError, match="aperture f-stop"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_mutated_focus_distance_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A refocused anchor renders a different image."""
    _mutate(objects, "CAM_SCAR_DETAIL").data.dof.focus_distance = 3.0
    with pytest.raises(applier.CinematicApplyError, match="focus distance"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_disabled_depth_of_field_on_a_focused_anchor_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The builder enables depth of field here; a flat lens is a mutation."""
    _mutate(objects, "CAM_SEAL_DETAIL").data.dof.use_dof = False
    with pytest.raises(applier.CinematicApplyError, match="depth of field"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_enabled_depth_of_field_on_a_survey_anchor_is_refused() -> None:
    """The three survey anchors are locked with depth of field off.

    None of them can appear in a real plan (no beat kind selects them), so the
    check is exercised directly at the verification seam the applier uses for
    every anchor it does bind.
    """
    record = dict(CAMERA_ANCHORS["CAM_P16_ROADS"])
    camera = _camera_from_record("CAM_P16_ROADS", record)
    good = FakeBpy([camera], FakeScene(1, 193))
    assert applier._require_camera_object(good, "CAM_P16_ROADS", record) is camera
    camera.data.dof.use_dof = True
    with pytest.raises(applier.CinematicApplyError, match="depth of field"):
        applier._require_camera_object(good, "CAM_P16_ROADS", record)


def test_a_mutated_far_clip_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A shortened clip hides the world the shot is supposed to show."""
    _mutate(objects, "CAM_HERO_WORLD").data.clip_end = 500.0
    with pytest.raises(applier.CinematicApplyError, match="far clip"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_mutated_near_clip_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A pushed-out near clip cuts away foreground the locked build shows."""
    _mutate(objects, "CAM_SEAL_DETAIL").data.clip_start = 5.0
    with pytest.raises(applier.CinematicApplyError, match="near clip"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_mutated_sensor_width_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A re-sensored camera changes the field of view with the lens untouched."""
    _mutate(objects, "CAM_HERO_WORLD").data.sensor_width = 50.0
    with pytest.raises(applier.CinematicApplyError, match="sensor width"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_shifted_lens_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A lens shift re-frames the image while every locked transform holds."""
    _mutate(objects, "CAM_SCAR_DETAIL").data.shift_x = 0.2
    with pytest.raises(applier.CinematicApplyError, match="shift_x"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_changed_projection_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """An orthographic anchor is a different picture through the same lens."""
    _mutate(objects, "CAM_HERO_WORLD").data.type = "ORTHO"
    with pytest.raises(applier.CinematicApplyError, match="PERSP"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_refitted_sensor_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The wave-2 adversarial find: VERTICAL fit re-frames past every V2 check."""
    _mutate(objects, "CAM_HERO_WORLD").data.sensor_fit = "VERTICAL"
    with pytest.raises(applier.CinematicApplyError, match="sensor fit"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_mutated_sensor_height_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The dormant half of the sensor pair is locked too."""
    _mutate(objects, "CAM_SEAL_DETAIL").data.sensor_height = 50.0
    with pytest.raises(applier.CinematicApplyError, match="sensor height"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_an_anamorphic_bokeh_ratio_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Bokeh shape is part of the image on a depth-of-field anchor."""
    _mutate(objects, "CAM_SCAR_DETAIL").data.dof.aperture_ratio = 2.0
    with pytest.raises(applier.CinematicApplyError, match="bokeh ratio"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_bladed_bokeh_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A bladed bokeh is refused."""
    _mutate(objects, "CAM_SEAL_DETAIL").data.dof.aperture_blades = 6
    with pytest.raises(applier.CinematicApplyError, match="bokeh blades"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_camera_exposing_no_lens_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A datablock without a lens is not a camera this layer can prove."""
    _mutate(objects, "CAM_HERO_WORLD").data.lens = None
    with pytest.raises(applier.CinematicApplyError, match="exposes no lens"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_camera_exposing_no_depth_of_field_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A datablock without a dof block cannot prove its locked aperture."""
    _mutate(objects, "CAM_SEAL_DETAIL").data.dof = None
    with pytest.raises(applier.CinematicApplyError, match="exposes no depth of field"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_refocused_p16_anchor_with_a_distinct_focus_point_is_refused() -> None:
    """The Phase 16 focus formula path, exercised where focus differs from look_at.

    CAM_P16_WORLD_HERO focuses at (12,-2,4) while looking at (-6,2,-4); no beat
    kind selects it, so the check is exercised at the verification seam the
    applier uses for every anchor it binds.
    """
    record = dict(CAMERA_ANCHORS["CAM_P16_WORLD_HERO"])
    camera = _camera_from_record("CAM_P16_WORLD_HERO", record)
    good = FakeBpy([camera], FakeScene(1, 193))
    assert applier._require_camera_object(good, "CAM_P16_WORLD_HERO", record) is camera
    camera.data.dof.focus_distance = 10.0
    with pytest.raises(applier.CinematicApplyError, match="focus distance"):
        applier._require_camera_object(good, "CAM_P16_WORLD_HERO", record)


def test_a_rolled_straight_down_anchor_is_refused() -> None:
    """The degenerate anchor's roll convention is enforced, not just assumed.

    CAM_P16_ROADS looks straight down, where the forward axis cannot betray a
    yaw: only the measured identity-up convention can. A rolled camera keeps
    forward exactly and must still be refused through the up axis.
    """
    record = dict(CAMERA_ANCHORS["CAM_P16_ROADS"])
    camera = _camera_from_record("CAM_P16_ROADS", record)
    good = FakeBpy([camera], FakeScene(1, 193))
    assert applier._require_camera_object(good, "CAM_P16_ROADS", record) is camera
    camera.rotation_euler = (0.0, 0.0, 0.5)
    with pytest.raises(applier.CinematicApplyError, match="rotated"):
        applier._require_camera_object(good, "CAM_P16_ROADS", record)


def test_a_look_at_coinciding_with_the_location_is_refused() -> None:
    """A record whose look-at equals its location defines no view direction."""
    record = dict(CAMERA_ANCHORS["CAM_HERO_WORLD"])
    record["look_at"] = record["location"]
    camera = _camera_from_record("CAM_HERO_WORLD", dict(CAMERA_ANCHORS["CAM_HERO_WORLD"]))
    broken = FakeBpy([camera], FakeScene(1, 193))
    with pytest.raises(applier.CinematicApplyError, match="coincides"):
        applier._require_camera_object(broken, "CAM_HERO_WORLD", record)


def test_an_animated_camera_object_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """V1 forbids camera animation outright; an animated anchor fails closed."""
    _mutate(objects, "CAM_HERO_WORLD").animation_data = object()
    with pytest.raises(applier.CinematicApplyError, match="animation"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_animated_camera_data_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """An animated lens is camera animation too."""
    _mutate(objects, "CAM_SEAL_DETAIL").data.animation_data = object()
    with pytest.raises(applier.CinematicApplyError, match="animation"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_foreign_rotation_mode_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The builders leave every anchor on XYZ; anything else is a mutation."""
    _mutate(objects, "CAM_HERO_WORLD").rotation_mode = "QUATERNION"
    with pytest.raises(applier.CinematicApplyError, match="rotation mode"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_catalogue_missing_a_camera_is_refused_by_its_digest(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A catalogue with a camera removed is not the approved catalogue."""
    del catalogue["CAM_SEAL_DETAIL"]
    with pytest.raises(applier.CinematicApplyError, match="not the approved one"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_an_empty_catalogue_is_refused_by_its_digest(bpy: FakeBpy, plan: dict[str, Any]) -> None:
    """An empty catalogue is refused before any camera is even inspected."""
    with pytest.raises(applier.CinematicApplyError, match="not the approved one"):
        applier.apply_shot_direction_plan(bpy, plan, {})


def test_a_scene_whose_frame_range_disagrees_is_refused(
    objects: list[FakeObject], plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Phase 22 directs the locked timeline, not whatever the scene happens to be."""
    wrong = FakeScene(1, 240)
    with pytest.raises(applier.CinematicApplyError, match="disagrees with"):
        applier.apply_shot_direction_plan(FakeBpy(objects, wrong), plan, catalogue)


# --------------------------------------------- foreign camera-bound markers


def test_a_foreign_camera_bound_marker_in_the_range_is_refused(
    bpy: FakeBpy, objects: list[FakeObject], plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A foreign marker binding a camera competes for the directed frames."""
    scene = bpy.context.scene
    foreign = scene.timeline_markers.new("SOMEONE_ELSES_CUT", frame=60)
    foreign.camera = _mutate(objects, "CAM_P16_ROADS")
    with pytest.raises(applier.CinematicApplyError, match="compete"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_a_foreign_camera_bound_marker_before_the_range_is_refused(
    bpy: FakeBpy, objects: list[FakeObject], plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A camera-bound marker before the window still governs its opening frames."""
    scene = bpy.context.scene
    foreign = scene.timeline_markers.new("EARLY_CUT", frame=1)
    foreign.camera = _mutate(objects, "CAM_P16_ROADS")
    with pytest.raises(applier.CinematicApplyError, match="compete"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_the_refusal_deletes_no_foreign_marker_and_binds_nothing(
    bpy: FakeBpy, objects: list[FakeObject], plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Fail closed means the timeline is left exactly as found."""
    scene = bpy.context.scene
    foreign = scene.timeline_markers.new("SOMEONE_ELSES_CUT", frame=60)
    foreign.camera = _mutate(objects, "CAM_P16_ROADS")
    with pytest.raises(applier.CinematicApplyError):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)
    names = [m.name for m in scene.timeline_markers]
    assert names == ["SOMEONE_ELSES_CUT"]


def test_a_foreign_camera_bound_marker_at_the_last_frame_is_refused(
    bpy: FakeBpy, objects: list[FakeObject], plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The boundary is inclusive: frame 193 is still a directed frame."""
    scene = bpy.context.scene
    edge = scene.timeline_markers.new("EDGE_CUT", frame=193)
    edge.camera = _mutate(objects, "CAM_P16_ROADS")
    with pytest.raises(applier.CinematicApplyError, match="compete"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_a_foreign_camera_bound_marker_after_the_range_is_tolerated(
    bpy: FakeBpy, objects: list[FakeObject], plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Beyond the directed range there is nothing to compete for."""
    scene = bpy.context.scene
    late = scene.timeline_markers.new("LATE_CUT", frame=194)
    late.camera = _mutate(objects, "CAM_P16_ROADS")
    report = applier.apply_shot_direction_plan(bpy, plan, catalogue)
    assert report["markers_bound"] == len(plan["shots"])
    assert any(m.name == "LATE_CUT" for m in scene.timeline_markers)


# ------------------------------------------- effective transform (wave A/V3)


def test_a_parented_anchor_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The independent reviewer's mutation: a parent re-poses the camera.

    The fake's derived matrix still matches the canonical pose, which is the
    hard case: the parent must be refused on its own existence, not only
    through its transform effect.
    """
    _mutate(objects, "CAM_HERO_WORLD").parent = FakeObject("RIG", "EMPTY")
    with pytest.raises(applier.CinematicApplyError, match="parented"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_constrained_anchor_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A constraint claims the pose; a fixed anchor carries none."""
    constraint = type("FakeConstraint", (), {"name": "Track To"})()
    _mutate(objects, "CAM_SEAL_DETAIL").constraints.append(constraint)
    with pytest.raises(applier.CinematicApplyError, match="constraint"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_delta_location_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The reviewer's delta_location=(5,0,0) mutation fails closed."""
    _mutate(objects, "CAM_HERO_WORLD").delta_location = (5.0, 0.0, 0.0)
    with pytest.raises(applier.CinematicApplyError, match="delta location"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_delta_rotation_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A delta rotation is refused."""
    _mutate(objects, "CAM_SCAR_DETAIL").delta_rotation_euler = (0.0, 0.0, 0.2)
    with pytest.raises(applier.CinematicApplyError, match="delta rotation"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_delta_quaternion_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A delta quaternion is refused."""
    _mutate(objects, "CAM_HERO_WORLD").delta_rotation_quaternion = (0.99, 0.1, 0.0, 0.0)
    with pytest.raises(applier.CinematicApplyError, match="delta quaternion"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_scaled_anchor_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Non-unit scale is non-canonical state, mirrored or not."""
    _mutate(objects, "CAM_SEAL_DETAIL").scale = (-1.0, 1.0, 1.0)
    with pytest.raises(applier.CinematicApplyError, match="unit scale"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_delta_scaled_anchor_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A delta scaled anchor is refused."""
    _mutate(objects, "CAM_HERO_WORLD").delta_scale = (1.0, 1.0, 2.0)
    with pytest.raises(applier.CinematicApplyError, match="unit scale"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_a_focus_object_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The reviewer's dof.focus_object mutation: focus no longer locked."""
    _mutate(objects, "CAM_SEAL_DETAIL").data.dof.focus_object = FakeObject("TARGET", "EMPTY")
    with pytest.raises(applier.CinematicApplyError, match="focus"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


def test_an_evaluated_matrix_mismatch_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The seal: a re-posed evaluated matrix is refused whatever caused it."""
    camera = _mutate(objects, "CAM_HERO_WORLD")
    shifted = [list(row) for row in camera.matrix_world]
    shifted[0][3] += 2.0
    camera.matrix_world_override = tuple(tuple(row) for row in shifted)
    with pytest.raises(applier.CinematicApplyError, match="world matrix"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


# ----------------------------------------------- execution clock (wave E/V3)


def test_a_60fps_scene_is_refused(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The reviewer's fps=60 mutation: same frames, a third of the duration."""
    bpy.context.scene.render.fps = 60
    with pytest.raises(applier.CinematicApplyError, match="fps"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_a_30fps_scene_is_refused(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A 30fps scene is refused."""
    bpy.context.scene.render.fps = 30
    with pytest.raises(applier.CinematicApplyError, match="fps"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_a_non_neutral_fps_base_is_refused(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """An NTSC-style base silently stretches the locked duration."""
    bpy.context.scene.render.fps_base = 1.001
    with pytest.raises(applier.CinematicApplyError, match="fps_base"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_time_remapping_is_refused(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Frame-map remapping resamples which source frame renders when."""
    bpy.context.scene.render.frame_map_new = 50
    with pytest.raises(applier.CinematicApplyError, match="remapping"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_a_frame_step_is_refused(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A frame step skips locked frames."""
    bpy.context.scene.frame_step = 2
    with pytest.raises(applier.CinematicApplyError, match="frame step"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_a_populated_sequencer_is_refused(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A sequencer HOLDING STRIPS could composite anything over the world.

    The bare ``use_sequencer`` flag is Blender's factory default and inert --
    the first real-gate run proved that refusing it rejects the canonical
    scene itself -- so the refusal keys on actual strips.
    """
    editor = type("FakeSequenceEditor", (), {"sequences_all": [object()]})()
    bpy.context.scene.sequence_editor = editor
    with pytest.raises(applier.CinematicApplyError, match="strip"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_an_empty_sequencer_flag_is_tolerated(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The factory-default flag with no editor composites nothing."""
    assert bpy.context.scene.render.use_sequencer is True
    report = applier.apply_shot_direction_plan(bpy, plan, catalogue)
    assert report["markers_bound"] == len(plan["shots"])


def test_a_multiview_scene_is_refused(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The wave-2 find: stereo rendering changes the image, cameras untouched."""
    bpy.context.scene.render.use_multiview = True
    with pytest.raises(applier.CinematicApplyError, match="multiview"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_non_square_pixels_are_refused(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The wave-2 find: a 2:1 pixel aspect re-frames every still."""
    bpy.context.scene.render.pixel_aspect_x = 2.0
    with pytest.raises(applier.CinematicApplyError, match="pixel_aspect_x"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_a_forged_plan_and_catalogue_pair_is_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The wave-2 construction: mutual consistency without approved identity.

    A hand-written catalogue with a re-lensed CAM_SEAL_DETAIL, a plan whose
    catalogue binding is that forged catalogue's OWN digest, and a scene
    mutated to match -- every mutual comparison agrees, and the applier still
    refuses, because the plan's binding is not the approved canonical
    catalogue.
    """
    record = dict(catalogue["CAM_SEAL_DETAIL"])
    record["lens_mm"] = 50.0
    catalogue["CAM_SEAL_DETAIL"] = record
    plan["source"] = dict(plan["source"])
    plan["source"]["catalogue_sha256"] = applier._catalogue_digest(catalogue)
    for obj in objects:
        if obj.name == "CAM_SEAL_DETAIL":
            obj.data.lens = 50.0
    with pytest.raises(applier.CinematicApplyError, match="forged catalogue cannot help"):
        applier.apply_shot_direction_plan(FakeBpy(objects, scene), plan, catalogue)


# --------------------------------------- source bindings at the gate (V3)


def test_a_plan_binding_a_foreign_clock_is_refused_by_the_applier(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The applier holds its own pin; a foreign clock digest never applies."""
    plan["source"]["motion_time_sha256"] = "e" * 64
    with pytest.raises(applier.CinematicApplyError, match="not the canonical"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_a_hand_edited_timeline_under_the_canonical_digest_is_refused(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Source identity AND resolved values: neither substitutes for the other."""
    plan["timeline"] = dict(plan["timeline"])
    plan["timeline"]["transition_start"] = 26
    with pytest.raises(applier.CinematicApplyError, match="hand-edited"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_the_appliers_pinned_constants_match_the_engine() -> None:
    """The restated digests and clock cannot drift from the engine's own."""
    from living_diorama.cinematic import (
        CANONICAL_MOTION_TIME_SHA256,
        catalogue_sha256,
        resolve_motion_time_binding,
    )

    assert applier.CANONICAL_MOTION_TIME_SHA256 == CANONICAL_MOTION_TIME_SHA256
    assert catalogue_sha256() == applier.APPROVED_CATALOGUE_SHA256
    root = Path(__file__).resolve().parents[2]
    motion = (root / "visual" / "blender" / "config" / "motion_time_v1.json").read_bytes()
    assert resolve_motion_time_binding(motion)["timeline"] == applier.CANONICAL_TIMELINE


def test_a_mutated_catalogue_with_a_matching_scene_is_still_refused(
    objects: list[FakeObject], scene: FakeScene, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """The independent reviewer's exact reproduction, now closed.

    The catalogue's CAM_HERO_WORLD is moved AND the scene camera is rebuilt to
    match the mutated record, so every camera-versus-catalogue comparison would
    agree -- and the apply is still refused, because the catalogue itself no
    longer hashes to the approved identity the plan binds.
    """
    record = dict(catalogue["CAM_HERO_WORLD"])
    record["location"] = (0.0, 0.0, 50.0)
    record["look_at"] = (10.0, 0.0, 0.0)
    catalogue["CAM_HERO_WORLD"] = record
    remaining = [obj for obj in objects if obj.name != "CAM_HERO_WORLD"]
    remaining.append(_camera_from_record("CAM_HERO_WORLD", record))
    with pytest.raises(applier.CinematicApplyError, match="not the approved one"):
        applier.apply_shot_direction_plan(FakeBpy(remaining, scene), plan, catalogue)


def test_a_single_altered_catalogue_value_is_refused(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """One changed lens in the supplied catalogue changes its identity."""
    record = dict(catalogue["CAM_SEAL_DETAIL"])
    record["lens_mm"] = 31.0
    catalogue["CAM_SEAL_DETAIL"] = record
    with pytest.raises(applier.CinematicApplyError, match="not the approved one"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_an_extra_catalogue_camera_is_refused(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """A proof-only camera cannot be smuggled into the approved set."""
    catalogue["CAM_P20_RECORD_ARC"] = dict(catalogue["CAM_SEAL_DETAIL"])
    with pytest.raises(applier.CinematicApplyError, match="not the approved one"):
        applier.apply_shot_direction_plan(bpy, plan, catalogue)


def test_a_reordered_catalogue_is_accepted(
    bpy: FakeBpy, plan: dict[str, Any], catalogue: dict[str, Any]
) -> None:
    """Key order is not identity: the digest is over canonical serialization."""
    reordered = {name: catalogue[name] for name in reversed(sorted(catalogue))}
    report = applier.apply_shot_direction_plan(bpy, plan, reordered)
    assert report["markers_bound"] == len(plan["shots"])


def test_the_appliers_catalogue_digest_matches_the_engines() -> None:
    """The restated canonical encoder byte-matches ``dumps_canonical``."""
    from living_diorama.cinematic import CAMERA_ANCHORS, catalogue_document, catalogue_sha256

    engine_digest = catalogue_sha256()
    assert applier._catalogue_digest(catalogue_document()) == engine_digest
    # Tuples serialize as lists, so the raw catalogue records digest identically.
    raw = {name: dict(record) for name, record in CAMERA_ANCHORS.items()}
    assert applier._catalogue_digest(raw) == engine_digest


def test_an_int_for_float_catalogue_value_changes_the_digest() -> None:
    """42 and 42.0 are different canonical bytes; the digest must notice."""
    from living_diorama.cinematic import catalogue_document, catalogue_sha256

    document = catalogue_document()
    document["CAM_HERO_WORLD"] = dict(document["CAM_HERO_WORLD"])
    assert document["CAM_HERO_WORLD"]["lens_mm"] == 42.0
    document["CAM_HERO_WORLD"]["lens_mm"] = 42
    assert applier._catalogue_digest(document) != catalogue_sha256()


def test_camera_at_frame_refuses_an_unbound_scene(scene: FakeScene) -> None:
    """Camera at frame refuses an unbound scene."""
    with pytest.raises(applier.CinematicApplyError, match="no Phase 22 markers"):
        applier.camera_at_frame(scene, 1)


def test_camera_at_frame_refuses_a_frame_before_every_owned_marker(
    bpy: FakeBpy, objects: list[FakeObject]
) -> None:
    """A frame no owned marker covers has no answer, and says so."""
    scene = bpy.context.scene
    marker = scene.timeline_markers.new(f"{applier.MARKER_PREFIX}shot_0001", frame=50)
    marker.camera = _mutate(objects, "CAM_HERO_WORLD")
    with pytest.raises(applier.CinematicApplyError, match="covers frame"):
        applier.camera_at_frame(scene, 10)


def test_the_applier_imports_no_engine_package() -> None:
    """The catalogue arrives as data, so the Blender side imports nothing."""
    source = (SCRIPTS / "apply_cinematic_direction.py").read_text(encoding="utf-8")
    assert "living_diorama" not in source
