"""The V2 camera-movement applier: new camera identity, keyframed, never the anchors.

These tests prove the applier's mechanics against a faithful minimal fake
``bpy`` and its pure math against both the sibling Phase 22 applier and the
engine's own movement planner. They also pin what the applier may never do:
touch, animate, reuse or collide with a fixed anchor camera.

The render path is integrated: the executor and the engine validator admit the
derived ``CAM_MOVEMENT_`` identity for a movement shot's frames under V2, and
this suite pins the applier's own side of that contract -- the derived name,
the marker prefix, and the keyframes the executor's F-curves interpolate.
"""

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.cinematic.camera_movement_planner import plan_camera_movements
from living_diorama.cinematic.cinematic_spec import CAMERA_ANCHORS, catalogue_document

SCRIPTS = Path(__file__).resolve().parents[2] / "visual" / "blender" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import apply_camera_movement as movement_applier  # noqa: E402
import apply_cinematic_direction as direction_applier  # noqa: E402

# ------------------------------------------------------------- the fake bpy


class FakeCameraData:
    """The camera datablock, reduced to what the applier touches."""

    def __init__(self, name: str) -> None:
        """Record the datablock's name."""
        self.name = name


class FakeFCurve:
    """One F-curve record: data path, first keyframe, extrapolation mode."""

    def __init__(self, data_path: str, frame: int) -> None:
        """Record the curve's data path and keyframe; extrapolation starts unset."""
        self.data_path = data_path
        self.frame = frame
        self.extrapolation = None


class FakeAction:
    """The action an object earns once it holds F-curves."""

    def __init__(self) -> None:
        """Start with no curves."""
        self.fcurves: list[FakeFCurve] = []


class FakeAnimationData:
    """The animation-data block Blender creates at the first ``keyframe_insert``."""

    def __init__(self) -> None:
        """Bind one action, mirroring what real Blender auto-creates."""
        self.action = FakeAction()


class FakeObject:
    """A scene object: name, type, transform and a keyframe log."""

    def __init__(self, name: str, data: FakeCameraData | None = None) -> None:
        """Start at the origin, unrotated, with no keyframes yet."""
        self.name = name
        self.type = "CAMERA" if data is not None else "EMPTY"
        self.data = data
        self.location = (0.0, 0.0, 0.0)
        self.rotation_euler = (0.0, 0.0, 0.0)
        self.keyframes: list[tuple[str, int]] = []
        self.animation_data = FakeAnimationData()

    def keyframe_insert(self, field: str, frame: int | None = None) -> None:
        """Record one keyframe insertion for a later assertion to inspect."""
        self.keyframes.append((field, frame))
        self.animation_data.action.fcurves.append(FakeFCurve(field, frame))


class FakeCameras:
    """The camera datablock factory: ``bpy.data.cameras``."""

    def __init__(self, owner: "FakeData") -> None:
        """Bind back to the owning ``FakeData`` so new datablocks are recorded."""
        self.owner = owner

    def new(self, name: str) -> FakeCameraData:
        """Create and record one new camera datablock."""
        data = FakeCameraData(name)
        self.owner.camera_data.append(data)
        return data


class FakeObjects:
    """The scene-object factory: ``bpy.data.objects``."""

    def __init__(self, owner: "FakeData") -> None:
        """Bind back to the owning ``FakeData`` so new objects are recorded."""
        self.owner = owner

    def new(self, name: str, data: FakeCameraData | None) -> FakeObject:
        """Create and record one new scene object."""
        obj = FakeObject(name, data)
        self.owner.objects_flat.append(obj)
        return obj

    def __iter__(self):
        """Iterate every recorded object, fixed anchors included."""
        return iter(self.owner.objects_flat)


class FakeMarker:
    """A timeline marker binding a frame to a camera."""

    def __init__(self, name: str, frame: int) -> None:
        """Record the marker's name and frame; unbound until a camera is set."""
        self.name = name
        self.frame = frame
        self.camera = None


class FakeTimelineMarkers:
    """The marker factory: ``scene.timeline_markers``."""

    def __init__(self) -> None:
        """Start with no markers."""
        self.markers: list[FakeMarker] = []

    def new(self, name: str, frame: int) -> FakeMarker:
        """Create and record one new marker."""
        marker = FakeMarker(name, frame)
        self.markers.append(marker)
        return marker


class FakeScene:
    """The scene: its frame range and marker factory."""

    def __init__(self) -> None:
        """Pin the locked EP1 193-frame timeline."""
        self.frame_start = 1
        self.frame_end = 193
        self.timeline_markers = FakeTimelineMarkers()


class FakeCollectionObjects:
    """The linkable object set: ``collection.objects``."""

    def __init__(self) -> None:
        """Start with nothing linked."""
        self.linked: list[FakeObject] = []

    def link(self, obj: FakeObject) -> None:
        """Link one object into the collection."""
        self.linked.append(obj)


class FakeCollection:
    """The active collection new objects are linked into."""

    def __init__(self) -> None:
        """Start with an empty linkable object set."""
        self.objects = FakeCollectionObjects()


class FakeViewLayer:
    """The view layer the applier refreshes after linking a camera."""

    def update(self) -> None:
        """Do nothing: a fake scene needs no dependency-graph refresh."""


class FakeContext:
    """``bpy.context``, reduced to what the applier touches."""

    def __init__(self, scene: FakeScene) -> None:
        """Bind the given scene and start with a fresh collection and view layer."""
        self.scene = scene
        self.collection = FakeCollection()
        self.view_layer = FakeViewLayer()


class FakeData:
    """``bpy.data``, reduced to what the applier touches."""

    def __init__(self) -> None:
        """Start with no cameras or objects; factories bound back to self."""
        self.objects = FakeObjects(self)
        self.cameras = FakeCameras(self)
        self.camera_data: list[FakeCameraData] = []
        self.objects_flat: list[FakeObject] = []


class FakeBpy:
    """The parts of ``bpy`` the applier touches, wired together."""

    def __init__(self) -> None:
        """Seed the scene with the real fixed anchor cameras, unanimated."""
        self.data = FakeData()
        self.context = FakeContext(FakeScene())
        for name in sorted(CAMERA_ANCHORS):
            self.data.objects_flat.append(FakeObject(name, FakeCameraData(name)))


def _build_plan(story_ep0_to_ep1: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """The genuine episode 0 -> 1 plan with camera movement assigned."""
    v1 = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    return plan_camera_movements(v1)


@pytest.fixture
def moved_plan(story_ep0_to_ep1: dict[str, Any], motion_time: bytes) -> dict[str, Any]:
    """A genuine V2 plan whose shots all carry movement."""
    return _build_plan(story_ep0_to_ep1, motion_time)


# --------------------------------------------------------- pure math parity


def test_the_restated_easing_matches_the_engine() -> None:
    """The Blender side restates the engine's easing, and a test pins it equal."""
    from living_diorama.cinematic.camera_movement_planner import eased as engine_eased

    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert movement_applier.eased(t, "LINEAR") == engine_eased(t, "LINEAR")
        assert movement_applier.eased(t, "EASE_IN_OUT") == engine_eased(t, "EASE_IN_OUT")
    assert movement_applier.eased(0.5, "EASE_IN_OUT") == 0.5
    assert movement_applier.eased(0.0, "EASE_IN_OUT") == 0.0
    assert movement_applier.eased(1.0, "EASE_IN_OUT") == 1.0


def test_the_restated_sampler_matches_the_engine(moved_plan: dict[str, Any]) -> None:
    """Both sides interpolate the same endpoints to the same poses."""
    from living_diorama.cinematic.camera_movement_planner import (
        sample_transform as engine_sample,
    )

    shot = moved_plan["shots"][1]
    movement = shot["camera_movement"]
    for t in (0.0, 0.3, 0.5, 0.8, 1.0):
        assert movement_applier.sample_transform(
            movement["start_transform"], movement["end_transform"], movement["easing"], t
        ) == engine_sample(
            movement["start_transform"], movement["end_transform"], movement["easing"], t
        )


def test_the_easing_curve_starts_and_ends_at_rest() -> None:
    """EASE_IN_OUT has zero slope at both ends: no jerk at the cut."""
    for easing in ("LINEAR", "EASE_IN_OUT"):
        for t in (0.0, 0.5, 1.0):
            eased = movement_applier.eased(t, easing)
            assert 0.0 <= eased <= 1.0
    # smoothstep derivative at the endpoints is zero by construction.
    assert movement_applier.eased(1e-9, "EASE_IN_OUT") < 1e-9
    assert 1.0 - movement_applier.eased(1.0 - 1e-9, "EASE_IN_OUT") < 1e-9


def test_the_movement_camera_name_is_disjoint_from_the_fixed_anchors() -> None:
    """A movement camera can never be mistaken for a world-built anchor."""
    name = movement_applier.movement_camera_name("shot_0003")
    assert name == "CAM_MOVEMENT_shot_0003"
    assert name not in movement_applier.APPROVED_ANCHOR_NAMES
    assert not name.startswith(("CAM_HERO_", "CAM_P16_", "CAM_SCAR_", "CAM_SEAL_"))


def test_keyframe_spec_places_two_keyframes_at_the_shot_edges(
    moved_plan: dict[str, Any],
) -> None:
    """A movement is keyframed at exactly its start and end frames."""
    shot = moved_plan["shots"][1]
    spec = movement_applier.keyframe_spec(shot)
    assert [entry["frame"] for entry in spec] == [shot["start_frame"], shot["end_frame"]]
    assert spec[0]["pose"]["location"] == shot["camera_movement"]["start_transform"]["location"]
    assert spec[1]["pose"]["location"] == shot["camera_movement"]["end_transform"]["location"]
    assert spec[0]["pose"]["look_at"] == shot["camera_movement"]["start_transform"]["look_at"]


def test_keyframe_spec_is_empty_for_a_static_hold(moved_plan: dict[str, Any]) -> None:
    """A STATIC block needs no new camera and no keyframes: the anchor holds."""
    static_shot = copy.deepcopy(moved_plan["shots"][1])
    static_shot["camera_movement"]["movement_type"] = "STATIC"
    static_shot["camera_movement"]["end_transform"] = copy.deepcopy(
        static_shot["camera_movement"]["start_transform"]
    )
    assert movement_applier.keyframe_spec(static_shot) == []


def test_keyframe_spec_lands_the_real_closing_shot_on_its_settle_frame(
    plan_ep1: dict[str, Any],
) -> None:
    """Real EP1 ``shot_0004`` under v2 keyframes at 145 (start) and 169 (settle), not 193."""
    planned = plan_camera_movements(plan_ep1, camera_grammar="v2")
    closing = next(shot for shot in planned["shots"] if shot["shot_id"] == "shot_0004")
    movement = closing["camera_movement"]
    assert closing["start_frame"] == 145
    assert closing["end_frame"] == 193
    assert movement["settle_frame"] == 169
    spec = movement_applier.keyframe_spec(closing)
    frames = [entry["frame"] for entry in spec]
    assert frames == [145, 169]
    assert 193 not in frames
    assert spec[0]["pose"] == movement["start_transform"]
    assert spec[1]["pose"] == movement["end_transform"]


def test_keyframe_spec_without_settle_frame_is_byte_for_byte_the_shot_edges(
    plan_ep1: dict[str, Any],
) -> None:
    """A movement with no ``settle_frame`` keeps keyframes at start and end frames.

    Proved on the real plan under BOTH lanes: the whole v1 lane (no movement
    carries the field) and every non-closing v2 movement.
    """
    from living_diorama.cinematic.cinematic_schema_v2 import CAMERA_MOVEMENT_KEYS

    for grammar in ("v1", "v2"):
        planned = plan_camera_movements(plan_ep1, camera_grammar=grammar)
        for shot in planned["shots"]:
            movement = shot.get("camera_movement")
            if movement is None or movement["movement_type"] == "STATIC":
                continue
            if "settle_frame" in movement:
                # The real closing shot (v2 only) deliberately carries one;
                # its own settle-frame behavior is proved separately above.
                continue
            spec = movement_applier.keyframe_spec(shot)
            assert [entry["frame"] for entry in spec] == [
                shot["start_frame"],
                shot["end_frame"],
            ], shot["shot_id"]
            assert set(movement) == set(CAMERA_MOVEMENT_KEYS), shot["shot_id"]


def test_keyframe_spec_agrees_with_the_engine_on_every_settle_frame(
    plan_ep1: dict[str, Any],
) -> None:
    """The applier's second keyframe lands where the engine's sampler settles.

    Drives the whole real v2 plan: a ``settle_frame`` shot lands its second
    keyframe exactly on the engine's settle frame, and every other movement
    lands it on the shot's end frame -- the two restatements agree everywhere.
    """
    planned = plan_camera_movements(plan_ep1, camera_grammar="v2")
    for shot in planned["shots"]:
        movement = shot.get("camera_movement")
        if movement is None or movement["movement_type"] == "STATIC":
            continue
        engine_settle = movement.get("settle_frame", shot["end_frame"])
        spec = movement_applier.keyframe_spec(shot)
        assert [entry["frame"] for entry in spec] == [
            shot["start_frame"],
            engine_settle,
        ], shot["shot_id"]
        assert spec[1]["pose"] == movement["end_transform"], shot["shot_id"]


def test_the_rotation_derivation_reproduces_the_sibling_look_at_pose() -> None:
    """The applier's euler for a look-at pose matches Phase 22's own derivation."""
    for anchor_id, record in CAMERA_ANCHORS.items():
        euler = movement_applier._rotation_euler_from_view(record["location"], record["look_at"])
        forward, up = direction_applier._view_axes_from_euler(euler)
        expected_forward, expected_up = direction_applier._expected_view_axes(
            record["location"], record["look_at"]
        )
        for actual, locked in zip(forward + up, expected_forward + expected_up, strict=True):
            assert abs(actual - locked) < 1e-6, anchor_id


# ------------------------------------------------------------- fake-bpy apply


def test_apply_creates_one_new_camera_per_movement_shot(
    moved_plan: dict[str, Any],
) -> None:
    """Each movement shot earns exactly one new camera; fixed anchors are untouched."""
    bpy = FakeBpy()
    fixed_names = {obj.name for obj in bpy.data.objects}
    report = movement_applier.apply_camera_movements(bpy, moved_plan, catalogue_document())
    movement_shots = [s for s in moved_plan["shots"] if s.get("camera_movement") is not None]
    assert report["count"] == len(movement_shots) == len(report["cameras_created"])
    created_names = [entry["camera"] for entry in report["cameras_created"]]
    assert len(set(created_names)) == len(created_names)
    for name in created_names:
        assert name.startswith("CAM_MOVEMENT_")
        assert name not in fixed_names
        assert name not in movement_applier.APPROVED_ANCHOR_NAMES
    # The scene holds exactly the fixed anchors plus the newly created cameras.
    assert {obj.name for obj in bpy.data.objects} == fixed_names | set(created_names)
    # Fixed anchors remain exactly as they were: no keyframes written to them.
    for obj in bpy.data.objects:
        if obj.name in fixed_names:
            assert obj.keyframes == []
    # One marker per movement shot, bound to the new camera, at the shot start.
    assert len(bpy.context.scene.timeline_markers.markers) == len(movement_shots)
    for marker in bpy.context.scene.timeline_markers.markers:
        assert marker.camera is not None
        assert marker.camera.name.startswith("CAM_MOVEMENT_")


def test_apply_writes_four_keyframes_per_created_camera(
    moved_plan: dict[str, Any],
) -> None:
    """Location and rotation are keyframed at the shot's start and end frames."""
    bpy = FakeBpy()
    movement_applier.apply_camera_movements(bpy, moved_plan, catalogue_document())
    for obj in bpy.data.objects:
        if obj.name.startswith("CAM_MOVEMENT_"):
            assert len(obj.keyframes) == 4  # location + rotation at two frames
            frames = sorted({frame for _, frame in obj.keyframes})
            assert len(frames) == 2


def test_apply_sets_constant_extrapolation_on_every_movement_fcurve(
    moved_plan: dict[str, Any],
) -> None:
    """Every F-curve a movement camera earns holds flat past its last keyframe.

    A LINEAR extrapolation would let the ease-out tail run past the second
    keyframe and re-open the closure gap ``settle_frame`` closes; the applier
    pins CONSTANT explicitly rather than trusting Blender's default.
    """
    bpy = FakeBpy()
    movement_applier.apply_camera_movements(bpy, moved_plan, catalogue_document())
    movement_objects = [obj for obj in bpy.data.objects if obj.name.startswith("CAM_MOVEMENT_")]
    assert movement_objects
    for obj in movement_objects:
        curves = obj.animation_data.action.fcurves
        assert curves, obj.name
        assert len(curves) == len(obj.keyframes), obj.name
        for curve in curves:
            assert curve.extrapolation == "CONSTANT", (obj.name, curve.data_path)


def test_apply_refuses_a_camera_name_that_already_exists(
    moved_plan: dict[str, Any],
) -> None:
    """A second camera with the same identity is refused: never reuse."""
    bpy = FakeBpy()
    first = movement_applier.apply_camera_movements(bpy, moved_plan, catalogue_document())
    with pytest.raises(movement_applier.CameraMovementApplyError, match="already exists"):
        movement_applier.apply_camera_movements(bpy, moved_plan, catalogue_document())
    assert first["count"] >= 1


def test_apply_refuses_a_plan_bound_to_a_foreign_catalogue(
    moved_plan: dict[str, Any],
) -> None:
    """A plan whose catalogue binding is not the approved one is refused."""
    foreign = copy.deepcopy(moved_plan)
    foreign["source"]["catalogue_sha256"] = "0" * 64
    with pytest.raises(movement_applier.CameraMovementApplyError, match="not the approved"):
        movement_applier.apply_camera_movements(FakeBpy(), foreign, catalogue_document())


def test_the_applier_restates_the_same_constants_as_phase_22() -> None:
    """Both appliers pin the same clock and the same catalogue identity."""
    assert movement_applier.CANONICAL_TIMELINE == direction_applier.CANONICAL_TIMELINE
    assert (
        movement_applier.CANONICAL_MOTION_TIME_SHA256
        == direction_applier.CANONICAL_MOTION_TIME_SHA256
    )
    assert movement_applier.APPROVED_CATALOGUE_SHA256 == direction_applier.APPROVED_CATALOGUE_SHA256
    assert frozenset(CAMERA_ANCHORS) == movement_applier.APPROVED_ANCHOR_NAMES
