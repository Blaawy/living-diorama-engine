"""Apply a validated Shot Direction Plan to the built scene, as camera cuts.

Blender-side realization of Phase 22. It reads a plan the pure layer already
validated and binds each shot's camera anchor to the timeline with a marker, so
playback and rendering cut between fixed cameras exactly where the plan says.

What it does **not** do is the point of the phase. It never creates a camera,
never moves, rotates, re-lenses or animates one, never touches world geometry,
materials, or any animation Phases 17 to 20 authored. Before binding anything it
proves every anchor the plan names is still the locked viewpoint the catalogue
records -- present, unique, a camera, unanimated, standing at the locked
location, aimed at the locked look-at point, carrying the locked lens, far clip
and depth-of-field state -- and that no foreign camera-bound marker competes for
the directed frames. Anything less fails closed: a drifted anchor is REFUSED,
never repaired, because repairing it would mean this layer moved a camera.

Only markers this phase owns are ever removed. Anything else on the timeline
belongs to somebody else and is left exactly as found, so applying a plan twice
converges instead of accumulating.

The orientation check replicates the builders' own derivation
(``look_at_rotation``: ``(target - location).to_track_quat("-Z", "Y")``) in pure
Python from the stored XYZ euler, so it runs identically under real Blender and
under the fake ``bpy`` the ordinary pytest suite uses. The reconstruction was
measured against real ``mathutils`` for all fourteen canonical anchors: worst
disagreement 2.6e-8, and worst float32 storage drift 2.3e-7, both orders of
magnitude inside the tolerances below.
"""

import hashlib
import json
import math
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MARKER_PREFIX = "P22_SHOT_"
"""Every timeline marker this phase owns starts here, and nothing else does."""

CANONICAL_MOTION_TIME_SHA256 = "bfcbfcfd8d2b33f0ca8a0bc51655a1028babc601a73cdd42ca3c8caf3f9da673"
"""The one canonical Phase 17 Motion & Time Spec this build directs.

Restated from the engine's ``cinematic_schema_v1`` as data (this module imports
nothing from the engine); a pure test asserts the two constants are equal, so
they cannot drift apart. A plan binding any other clock digest is refused here
too, closing the gate-side path the same way the pure layer closes its own.
"""

APPROVED_CATALOGUE_SHA256 = "d9110cfcbb51aeec40ae55e461298ecf7668a81e31945ed7d41fd843a9c0f82d"
"""The canonical digest of the approved fourteen-anchor catalogue.

Restated from the engine's ``catalogue_sha256()`` as data; a pure test asserts
the two agree, so they cannot drift apart. Without this the gate-side closure
was only MUTUAL -- plan-versus-supplied-catalogue -- and the wave-2 audit
demonstrated a hand-written plan/catalogue pair that satisfied every mutual
check while describing a re-lensed camera. The applier now refuses any plan
whose catalogue binding is not the approved identity, before comparing the
supplied data against it.
"""

CANONICAL_TIMELINE = {
    "end_frame": 193,
    "end_hold_frames": 48,
    "fps": 24,
    "start_frame": 1,
    "start_hold_frames": 24,
    "transition_end": 145,
    "transition_frames": 120,
    "transition_start": 25,
}
"""The canonical resolved clock, restated as data beside its source digest.

Every value is what ``motion_time_v1.json`` resolves to under Phase 17's own
arithmetic; a pure test proves this dict equals the engine's resolved binding
of the pinned bytes. The applier holds plans as data and cannot run the pure
validators, so a plan whose timeline section was hand-edited after binding the
canonical digest is refused here by direct comparison -- source identity AND
resolved values, never one as a substitute for the other.
"""

DELTA_TOLERANCE = 1e-6
"""Slack for delta transforms and scale, which the builders leave at factory
identity exactly."""

MATRIX_TOLERANCE = 1e-3
"""Slack per cell for the evaluated world matrix against the canonical pose.

A redundant seal over the per-field checks: parents, constraints, delta
transforms and drivers all land in the evaluated matrix, so whatever novel
mechanism re-poses the camera, the matrix disagrees with the canonical
location-plus-look-at transform and the apply refuses.
"""

LENS_TOLERANCE = 1e-4
"""Floating-point slack when comparing a lens against its locked value."""

LOCATION_TOLERANCE = 1e-4
"""Slack per axis for a stored camera location.

Blender stores float32; the measured worst drift across the fourteen canonical
anchors is 1.9e-7, so this still catches any real move by three orders of
magnitude.
"""

DIRECTION_TOLERANCE = 1e-4
"""Slack per component for the reconstructed view axes (measured worst 2.3e-7)."""

FSTOP_TOLERANCE = 1e-4
"""Slack for a stored aperture f-stop (5.6 stores as float32 within 1e-7)."""

FOCUS_DISTANCE_TOLERANCE = 1e-3
"""Slack for a stored focus distance (float32 at the farthest anchor: ~2e-5)."""

CLIP_TOLERANCE = 1e-3
"""Slack for the builders' uniform far clip."""


class CinematicApplyError(RuntimeError):
    """Raised when the scene cannot honour the plan exactly."""


def _view_axes_from_euler(euler):
    """Return (forward, up) unit vectors for a Blender 'XYZ' euler rotation.

    ``R = Rz @ Ry @ Rx`` is Blender's XYZ euler composition; a camera looks
    along its local ``-Z`` (the negated third matrix column) and its up is local
    ``+Y`` (the second column). Proven against ``mathutils`` for every canonical
    anchor by direct measurement.
    """
    ex, ey, ez = (float(component) for component in euler)
    cx, sx = math.cos(ex), math.sin(ex)
    cy, sy = math.cos(ey), math.sin(ey)
    cz, sz = math.cos(ez), math.sin(ez)
    forward = (
        -(cz * sy * cx + sz * sx),
        -(sz * sy * cx - cz * sx),
        -(cy * cx),
    )
    up = (
        cz * sy * sx - sz * cx,
        sz * sy * sx + cz * cx,
        cy * sx,
    )
    return forward, up


def _expected_view_axes(location, look_at):
    """Return the (forward, up) the builders' look-at derivation produces.

    ``to_track_quat("-Z", "Y")`` aims the camera's ``-Z`` along the view
    direction and rolls its ``+Y`` as close to world ``+Z`` as possible. For the
    one degenerate anchor that looks straight down (``CAM_P16_ROADS``) Blender
    resolves the roll to the identity rotation, whose up is world ``+Y`` --
    verified by direct measurement, not assumed.
    """
    direction = tuple(float(a) - float(b) for a, b in zip(look_at, location, strict=True))
    length = math.sqrt(sum(component * component for component in direction))
    if length == 0.0:
        raise CinematicApplyError("camera anchor look_at coincides with its location")
    forward = tuple(component / length for component in direction)
    projected = (
        -forward[2] * forward[0],
        -forward[2] * forward[1],
        1.0 - forward[2] * forward[2],
    )
    magnitude = math.sqrt(sum(component * component for component in projected))
    if magnitude < 1e-6:
        return forward, (0.0, 1.0, 0.0)
    return forward, tuple(component / magnitude for component in projected)


def _require_close(anchor_id, quantity, actual, expected, tolerance):
    """Refuse unless a stored scalar still equals its locked value."""
    if abs(float(actual) - float(expected)) > tolerance:
        raise CinematicApplyError(
            f"camera anchor {anchor_id!r} has {quantity} {float(actual)!r} but the "
            f"catalogue locks it at {float(expected)!r}; the anchor has been mutated"
        )


def _catalogue_digest(catalogue) -> str:
    """Return the SHA-256 of the supplied catalogue's canonical serialization.

    The identical byte form the engine's ``catalogue_sha256`` computes -- sorted
    keys, compact separators, no ASCII escaping, one trailing newline -- restated
    here because this module imports nothing from the engine. A pure test proves
    the two implementations agree on the approved catalogue, so a supplied
    catalogue passes only when its VALUES are the approved ones; key order and
    on-disk formatting are immaterial by construction.
    """
    text = json.dumps(
        catalogue,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8") + b"\n").hexdigest()


def _expected_world_matrix(expected):
    """Return the canonical 4x4 world matrix rows for one anchor record.

    Translation from the locked location, rotation columns from the look-at
    derivation (camera X = up x view-Z), unit scale -- exactly what the locked
    builders produce for an unparented, unconstrained, delta-free camera.
    """
    forward, up = _expected_view_axes(expected["location"], expected["look_at"])
    z_axis = tuple(-component for component in forward)
    x_axis = (
        up[1] * z_axis[2] - up[2] * z_axis[1],
        up[2] * z_axis[0] - up[0] * z_axis[2],
        up[0] * z_axis[1] - up[1] * z_axis[0],
    )
    location = tuple(float(component) for component in expected["location"])
    return (
        (x_axis[0], up[0], z_axis[0], location[0]),
        (x_axis[1], up[1], z_axis[1], location[1]),
        (x_axis[2], up[2], z_axis[2], location[2]),
        (0.0, 0.0, 0.0, 1.0),
    )


def _require_effective_transform(camera, anchor_id: str, expected: dict) -> None:
    """Refuse unless the camera's EFFECTIVE pose is still the canonical one.

    The independent review demonstrated that local fields alone are not the
    rendered truth: a parent, a constraint or a delta transform re-poses the
    camera while every local value stays canonical. The builders create every
    anchor unparented, unconstrained and delta-free, so anything else is a
    mutation -- refused, never repaired -- and the evaluated world matrix is
    then proven against the canonical location-plus-look-at transform as the
    seal over mechanisms this list does not name.
    """
    if getattr(camera, "parent", None) is not None:
        raise CinematicApplyError(
            f"camera anchor {anchor_id!r} is parented to "
            f"{camera.parent.name!r}; a fixed anchor is unparented"
        )
    constraints = getattr(camera, "constraints", ())
    if len(constraints) != 0:
        names = ", ".join(repr(entry.name) for entry in constraints)
        raise CinematicApplyError(
            f"camera anchor {anchor_id!r} carries constraints ({names}); a fixed "
            "anchor is unconstrained"
        )
    for axis, actual in zip("xyz", getattr(camera, "delta_location", (0.0, 0.0, 0.0)), strict=True):
        if abs(float(actual)) > DELTA_TOLERANCE:
            raise CinematicApplyError(
                f"camera anchor {anchor_id!r} carries delta location {axis}={actual!r}; "
                "a fixed anchor has no delta transform"
            )
    for axis, actual in zip(
        "xyz", getattr(camera, "delta_rotation_euler", (0.0, 0.0, 0.0)), strict=True
    ):
        if abs(float(actual)) > DELTA_TOLERANCE:
            raise CinematicApplyError(
                f"camera anchor {anchor_id!r} carries delta rotation {axis}={actual!r}; "
                "a fixed anchor has no delta transform"
            )
    quaternion = tuple(getattr(camera, "delta_rotation_quaternion", (1.0, 0.0, 0.0, 0.0)))
    for actual, identity in zip(quaternion, (1.0, 0.0, 0.0, 0.0), strict=True):
        if abs(float(actual) - identity) > DELTA_TOLERANCE:
            raise CinematicApplyError(
                f"camera anchor {anchor_id!r} carries delta quaternion {quaternion!r}; "
                "a fixed anchor has no delta transform"
            )
    for label, vector in (
        ("scale", getattr(camera, "scale", (1.0, 1.0, 1.0))),
        ("delta scale", getattr(camera, "delta_scale", (1.0, 1.0, 1.0))),
    ):
        for axis, actual in zip("xyz", vector, strict=True):
            if abs(float(actual) - 1.0) > DELTA_TOLERANCE:
                raise CinematicApplyError(
                    f"camera anchor {anchor_id!r} has {label} {axis}={actual!r}; a "
                    "fixed anchor keeps unit scale"
                )


def _require_world_matrix(camera, anchor_id: str, expected: dict) -> None:
    """The seal: the EVALUATED world matrix must be the canonical pose.

    Runs after every per-field check so a plain move or re-aim earns its
    precise refusal first; whatever re-poses a camera through a mechanism the
    field checks do not name still lands here, because everything lands in the
    evaluated matrix.
    """
    expected_matrix = _expected_world_matrix(expected)
    world = camera.matrix_world
    for row in range(3):
        for column in range(4):
            actual = float(world[row][column])
            locked = expected_matrix[row][column]
            if abs(actual - locked) > MATRIX_TOLERANCE:
                raise CinematicApplyError(
                    f"camera anchor {anchor_id!r} has evaluated world matrix cell "
                    f"[{row}][{column}] = {actual!r} but the canonical pose gives "
                    f"{locked!r}; something re-poses this camera beyond its local "
                    "values, and a fixed anchor is refused, never repaired"
                )


def _require_camera_object(bpy, anchor_id: str, expected: dict) -> object:
    """Return the scene object for one anchor, proven to be the locked camera.

    Every check reads the scene; nothing is ever written back. A failed check is
    a refusal, never a repair.
    """
    matches = [obj for obj in bpy.data.objects if obj.name == anchor_id]
    if not matches:
        raise CinematicApplyError(
            f"camera anchor {anchor_id!r} is named by the plan but absent from the "
            "scene; Phase 22 never substitutes another camera"
        )
    if len(matches) > 1:
        raise CinematicApplyError(
            f"camera anchor {anchor_id!r} resolves to {len(matches)} objects; an "
            "anchor must be unambiguous"
        )
    camera = matches[0]
    if camera.type != "CAMERA":
        raise CinematicApplyError(f"object {anchor_id!r} is a {camera.type}, not a CAMERA")

    if getattr(camera, "animation_data", None) is not None:
        raise CinematicApplyError(
            f"camera anchor {anchor_id!r} carries object animation data; V1 forbids "
            "camera animation outright"
        )
    if getattr(camera.data, "animation_data", None) is not None:
        raise CinematicApplyError(
            f"camera anchor {anchor_id!r} carries camera-data animation; V1 forbids "
            "camera animation outright"
        )

    mode = getattr(camera, "rotation_mode", "XYZ")
    if mode != "XYZ":
        raise CinematicApplyError(
            f"camera anchor {anchor_id!r} uses rotation mode {mode!r}; the builders "
            "leave every anchor on 'XYZ', so this anchor has been mutated"
        )

    _require_effective_transform(camera, anchor_id, expected)

    stored_location = tuple(float(component) for component in camera.location)
    for axis, actual, locked in zip("xyz", stored_location, expected["location"], strict=True):
        if abs(actual - float(locked)) > LOCATION_TOLERANCE:
            raise CinematicApplyError(
                f"camera anchor {anchor_id!r} stands at {axis}={actual!r} but the "
                f"catalogue locks it at {axis}={float(locked)!r}; the anchor has moved"
            )

    forward, up = _view_axes_from_euler(camera.rotation_euler)
    expected_forward, expected_up = _expected_view_axes(expected["location"], expected["look_at"])
    for label, actual_axis, locked_axis in (
        ("view direction", forward, expected_forward),
        ("up axis", up, expected_up),
    ):
        for actual, locked in zip(actual_axis, locked_axis, strict=True):
            if abs(actual - locked) > DIRECTION_TOLERANCE:
                raise CinematicApplyError(
                    f"camera anchor {anchor_id!r} has {label} {actual_axis!r} but its "
                    f"locked look-at derivation gives {locked_axis!r}; the anchor has "
                    "been rotated"
                )

    lens = getattr(camera.data, "lens", None)
    if lens is None:
        raise CinematicApplyError(f"camera anchor {anchor_id!r} exposes no lens")
    if abs(float(lens) - float(expected["lens_mm"])) > LENS_TOLERANCE:
        raise CinematicApplyError(
            f"camera anchor {anchor_id!r} has lens {lens}mm but the catalogue locks "
            f"it at {expected['lens_mm']}mm; the anchor has been mutated"
        )

    _require_close(
        anchor_id,
        "far clip",
        getattr(camera.data, "clip_end", 0.0),
        expected["clip_end"],
        CLIP_TOLERANCE,
    )
    _require_close(
        anchor_id,
        "near clip",
        getattr(camera.data, "clip_start", 0.0),
        expected["clip_start"],
        CLIP_TOLERANCE,
    )

    projection = getattr(camera.data, "type", None)
    if projection != expected["projection"]:
        raise CinematicApplyError(
            f"camera anchor {anchor_id!r} is a {projection!r} camera but the locked "
            f"build produces {expected['projection']!r}; the anchor has been mutated"
        )
    _require_close(
        anchor_id,
        "sensor width",
        getattr(camera.data, "sensor_width", 0.0),
        expected["sensor_width_mm"],
        LENS_TOLERANCE,
    )
    _require_close(
        anchor_id,
        "sensor height",
        getattr(camera.data, "sensor_height", 0.0),
        expected["sensor_height_mm"],
        LENS_TOLERANCE,
    )
    fit = getattr(camera.data, "sensor_fit", None)
    if fit != expected["sensor_fit"]:
        raise CinematicApplyError(
            f"camera anchor {anchor_id!r} uses sensor fit {fit!r} but the locked build "
            f"produces {expected['sensor_fit']!r}; a re-fitted sensor re-frames the image "
            "through the identical lens"
        )
    for shift_field, shift_key in (("shift_x", "shift_x"), ("shift_y", "shift_y")):
        _require_close(
            anchor_id,
            f"lens {shift_field}",
            getattr(camera.data, shift_field, 0.0),
            expected[shift_key],
            LENS_TOLERANCE,
        )

    dof = getattr(camera.data, "dof", None)
    if dof is None:
        raise CinematicApplyError(f"camera anchor {anchor_id!r} exposes no depth of field")
    focus_target = getattr(dof, "focus_object", None)
    if focus_target is not None:
        raise CinematicApplyError(
            f"camera anchor {anchor_id!r} focuses on object {focus_target.name!r}; the "
            "builders set a fixed focus distance and never a focus object, so this "
            "anchor's rendered focus no longer follows its locked value"
        )
    enabled = bool(dof.use_dof)
    if enabled != bool(expected["dof"]):
        state = "enabled" if enabled else "disabled"
        locked_state = "enabled" if expected["dof"] else "disabled"
        raise CinematicApplyError(
            f"camera anchor {anchor_id!r} has depth of field {state} but the builder "
            f"leaves it {locked_state}; the anchor has been mutated"
        )
    if enabled:
        _require_close(
            anchor_id,
            "aperture f-stop",
            dof.aperture_fstop,
            expected["f_stop"],
            FSTOP_TOLERANCE,
        )
        focus_distance = math.sqrt(
            sum(
                (float(a) - float(b)) ** 2
                for a, b in zip(expected["focus"], expected["location"], strict=True)
            )
        )
        _require_close(
            anchor_id,
            "focus distance",
            dof.focus_distance,
            focus_distance,
            FOCUS_DISTANCE_TOLERANCE,
        )
        _require_close(
            anchor_id,
            "bokeh ratio",
            getattr(dof, "aperture_ratio", 0.0),
            expected["aperture_ratio"],
            FSTOP_TOLERANCE,
        )
        blades = getattr(dof, "aperture_blades", None)
        if blades != expected["aperture_blades"]:
            raise CinematicApplyError(
                f"camera anchor {anchor_id!r} has {blades!r} bokeh blades but the locked "
                f"build produces {expected['aperture_blades']!r}; the anchor has been "
                "mutated"
            )
        _require_close(
            anchor_id,
            "bokeh rotation",
            getattr(dof, "aperture_rotation", 0.0),
            expected["aperture_rotation"],
            FSTOP_TOLERANCE,
        )

    _require_world_matrix(camera, anchor_id, expected)
    return camera


def clear_owned_markers(scene) -> int:
    """Remove only the markers this phase owns. Returns how many were removed."""
    owned = [m for m in scene.timeline_markers if m.name.startswith(MARKER_PREFIX)]
    for marker in owned:
        scene.timeline_markers.remove(marker)
    return len(owned)


def _require_no_foreign_camera_markers(scene, timeline: dict) -> None:
    """Refuse if a foreign camera-bound marker competes for the directed frames.

    Blender binds the active camera from a camera-carrying marker onward, so any
    foreign marker with a camera at or before the directed range's last frame
    can override what this plan directs -- including one placed before the range,
    which governs the opening frames until a later marker supersedes it. Such a
    marker is somebody else's claim on the same mechanism this phase uses, and
    the two cannot both hold. The foreign marker is never touched: the plan is
    refused, and resolving the conflict is its owner's decision.
    """
    conflicting = [
        marker
        for marker in scene.timeline_markers
        if not marker.name.startswith(MARKER_PREFIX)
        and getattr(marker, "camera", None) is not None
        and marker.frame <= timeline["end_frame"]
    ]
    if conflicting:
        described = ", ".join(
            f"{marker.name!r} at frame {marker.frame} binding {marker.camera.name!r}"
            for marker in conflicting
        )
        raise CinematicApplyError(
            f"foreign camera-bound timeline markers compete with the plan: {described}; "
            "Phase 22 owns no foreign marker and refuses rather than fight over the "
            "active camera"
        )


def apply_shot_direction_plan(bpy, plan: dict, catalogue: dict) -> dict:
    """Bind every shot in a validated plan to the scene timeline.

    Args:
        bpy: The Blender Python module.
        plan: A Shot Direction Plan V1 document, already validated by the pure
            layer. This function re-checks only what the scene can contradict.
        catalogue: The Phase 22 camera anchor catalogue, passed as data so this
            module imports nothing from the engine package.

    Returns:
        A report of what was bound, for the structural tests to assert against.

    Raises:
        CinematicApplyError: If an anchor is missing, ambiguous, not a camera,
            moved, rotated, re-lensed, re-apertured, animated or otherwise
            mutated; if a foreign camera-bound marker competes for the directed
            frames; or if a shot falls outside the scene's frame range.
    """
    scene = bpy.context.scene
    shots = plan["shots"]
    timeline = plan["timeline"]

    # The plan itself must be one this build was reviewed against: cut on the
    # canonical Phase 17 clock and for the approved camera catalogue. The
    # supplied catalogue's own canonical digest must then match what the plan
    # binds -- so a scene mutated to agree with a mutated catalogue is refused
    # on the catalogue's identity before any camera is even inspected.
    bound_clock = plan["source"]["motion_time_sha256"]
    if bound_clock != CANONICAL_MOTION_TIME_SHA256:
        raise CinematicApplyError(
            f"plan binds motion time spec {bound_clock}, which is not the canonical "
            f"Phase 17 source this build directs ({CANONICAL_MOTION_TIME_SHA256})"
        )
    if dict(timeline) != CANONICAL_TIMELINE:
        raise CinematicApplyError(
            f"plan restates timeline {dict(timeline)!r}, which is not what the "
            "canonical Phase 17 source resolves to; a hand-edited clock under the "
            "canonical digest is refused"
        )
    bound_catalogue = plan["source"]["catalogue_sha256"]
    if bound_catalogue != APPROVED_CATALOGUE_SHA256:
        raise CinematicApplyError(
            f"plan binds camera catalogue {bound_catalogue}, which is not the approved "
            f"canonical catalogue ({APPROVED_CATALOGUE_SHA256}); a matching forged "
            "catalogue cannot help it"
        )
    supplied_catalogue = _catalogue_digest(catalogue)
    if supplied_catalogue != bound_catalogue:
        raise CinematicApplyError(
            f"the supplied camera catalogue hashes to {supplied_catalogue}, but the "
            f"plan was cut for catalogue {bound_catalogue}; an anchor set that is not "
            "the approved one is refused whatever the scene looks like"
        )

    if scene.frame_start != timeline["start_frame"] or scene.frame_end != timeline["end_frame"]:
        raise CinematicApplyError(
            f"scene frame range {scene.frame_start}..{scene.frame_end} disagrees with "
            f"the plan's locked timeline {timeline['start_frame']}..{timeline['end_frame']}"
        )

    # The scene must also RUN on the plan's clock. Frame numbers alone are not
    # time: a 60 fps scene plays the same 193 frames in a third of the locked
    # duration, and Blender's time remapping or frame stepping would resample
    # them. The locked Phase 17/19 appliers set the render fps from the
    # canonical timeline and never touch the remap or step dials, so anything
    # non-neutral here is a mutation of the execution clock.
    render = scene.render
    if int(getattr(render, "fps", 0)) != timeline["fps"]:
        raise CinematicApplyError(
            f"scene renders at {getattr(render, 'fps', None)!r} fps but the plan's "
            f"locked clock is {timeline['fps']} fps; the cinematic duration would "
            "change with the frame numbers untouched"
        )
    fps_base = float(getattr(render, "fps_base", 1.0))
    if abs(fps_base - 1.0) > 1e-9:
        raise CinematicApplyError(
            f"scene fps_base is {fps_base!r}; the canonical clock uses base 1.0"
        )
    map_old = int(getattr(render, "frame_map_old", 100))
    map_new = int(getattr(render, "frame_map_new", 100))
    if map_old != map_new:
        raise CinematicApplyError(
            f"scene time remapping is {map_old}:{map_new}; the locked timeline is never remapped"
        )
    step = int(getattr(scene, "frame_step", 1))
    if step != 1:
        raise CinematicApplyError(
            f"scene frame step is {step}; the locked timeline plays every frame"
        )
    # ``use_sequencer`` is factory-TRUE in Blender and inert without strips --
    # measured in the real gate, where refusing the bare flag rejected the
    # locked canonical scene itself. The honest hazard is an actual strip:
    # sequencer post-processing with content composites arbitrary media over
    # the locked world.
    editor = getattr(scene, "sequence_editor", None)
    if bool(getattr(render, "use_sequencer", False)) and editor is not None:
        strips = getattr(editor, "sequences_all", ())
        if len(strips) > 0:
            raise CinematicApplyError(
                f"scene renders through a sequencer holding {len(strips)} strip(s); "
                "the locked build composites nothing over the 3D world"
            )
    if bool(getattr(render, "use_multiview", False)):
        raise CinematicApplyError(
            "scene renders in multiview/stereo mode; the locked build renders one "
            "view through one fixed anchor"
        )
    for aspect_field in ("pixel_aspect_x", "pixel_aspect_y"):
        aspect = float(getattr(render, aspect_field, 1.0))
        if abs(aspect - 1.0) > 1e-9:
            raise CinematicApplyError(
                f"scene {aspect_field} is {aspect!r}; non-square pixels re-frame "
                "every shot through an untouched camera"
            )

    # Constraint, parent and driver effects land in evaluated state, so the
    # dependency graph must be current before any world matrix is trusted --
    # matrix_world is lazy in background Blender.
    bpy.context.view_layer.update()

    resolved = {}
    for shot in shots:
        anchor_id = shot["camera_anchor_id"]
        if anchor_id not in catalogue:
            raise CinematicApplyError(
                f"plan names camera anchor {anchor_id!r}, which is not in the approved catalogue"
            )
        if anchor_id not in resolved:
            resolved[anchor_id] = _require_camera_object(bpy, anchor_id, catalogue[anchor_id])
        # Checked here, before anything is mutated, so a refusal can never leave
        # a partial bind behind -- even for a plan that somehow bypassed the pure
        # validator this check is redundant with.
        frame = shot["start_frame"]
        if frame < scene.frame_start or frame > scene.frame_end:
            raise CinematicApplyError(
                f"{shot['shot_id']} starts at frame {frame}, outside the scene range"
            )

    _require_no_foreign_camera_markers(scene, timeline)

    removed = clear_owned_markers(scene)

    bound = []
    for shot in shots:
        frame = shot["start_frame"]
        marker = scene.timeline_markers.new(f"{MARKER_PREFIX}{shot['shot_id']}", frame=frame)
        marker.camera = resolved[shot["camera_anchor_id"]]
        bound.append(
            {
                "shot_id": shot["shot_id"],
                "frame": frame,
                "camera": shot["camera_anchor_id"],
                "marker": marker.name,
            }
        )

    # The scene's own camera is set to the opening shot so a still render without
    # marker evaluation still shows the intended first frame.
    scene.camera = resolved[shots[0]["camera_anchor_id"]]

    return {
        "markers_removed": removed,
        "markers_bound": len(bound),
        "bound": bound,
        "anchors_verified": sorted(resolved),
        "opening_camera": shots[0]["camera_anchor_id"],
        "closing_camera": shots[-1]["camera_anchor_id"],
    }


def camera_at_frame(scene, frame: int) -> str:
    """Return the anchor name active at a frame, per this phase's markers.

    Blender binds a camera from a marker onward, so the active camera at any
    frame is the one on the latest owned marker at or before it. This is a
    convenience for reasoning about the plan; the structural suite additionally
    proves the claim against Blender's own evaluation by setting real frames and
    reading the scene's actual active camera.
    """
    owned = [
        marker
        for marker in scene.timeline_markers
        if marker.name.startswith(MARKER_PREFIX) and marker.camera is not None
    ]
    if not owned:
        raise CinematicApplyError("no Phase 22 markers are bound")
    applicable = [marker for marker in owned if marker.frame <= frame]
    if not applicable:
        raise CinematicApplyError(f"no Phase 22 marker covers frame {frame}")
    latest = max(applicable, key=lambda marker: marker.frame)
    return latest.camera.name
