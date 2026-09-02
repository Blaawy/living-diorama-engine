"""Assigning OPTIONAL ``camera_movement`` blocks to shots of a V1 shot plan.

V2 direction is an edit layer over an already-locked V1 plan. This module takes
a validated Shot Direction Plan V1 document and returns a deep copy of it in
which SOME shots carry a ``camera_movement`` block and the rest stay exactly as
V1 wrote them. It never re-validates the envelope (the input is already
validated upstream, exactly as ``render_planner`` consumes an already-validated
shot plan) and it never invents a beat, a reason, or an anchor.

Every movement decision is derived from the shot's own real fields -- its
``kind``, its real ``reason_code``, its real ``source_beat_ids``, its real
anchor, its real emphasis and its real frame window -- through a fixed,
positional rule table. There is no randomness, no wall clock, no set or dict
iteration that could vary, and no tie that is not broken by shot position, so
the same plan always yields the same assignment.

The movement endpoints are derived from the LOCKED pose of the anchor the shot
already names (``cinematic_spec.CAMERA_ANCHORS``), so a movement camera starts
exactly where the fixed anchor stands and never invents a coordinate
convention. The ``reason_for_move`` strings are built to contain the shot's own
``reason_code``, satisfying the mechanical binding the V2 validator enforces.

The Director-revision camera grammar
------------------------------------

``plan_camera_movements`` accepts a ``camera_grammar`` keyword: ``"v1"`` (the
default, byte-for-byte today's behavior) or ``"v2"`` (the Director-revision
grammar, context-first movement for EP1). The two lanes deliberately do NOT
collide with the existing ``camera_profile`` keyword, which gates something
else -- whether movement exists at all (``camera_profile="v1"`` produces no
movement, ``"v2"`` produces movement). ``camera_grammar`` gates HOW movement
is assigned once it exists: the ``"v2"`` lane replaces every gratuitous
``PUSH_IN`` with a context-building move, and for the wall-consequence shot
derives an ADDITIVE alternate end pose -- the camera pulls back along the
anchor's own line of sight until it stands at the exact minimum distance at
which the whole wall fits inside the corrected (width-governed) field of view
(``_wall_context_target_distance``: ~55.7 units for the real 28 mm lens at the
wall shot's elevated end altitude 24.0, derived from the real wall geometry
and sensor, not guessed), so the whole wall and the city around it sit inside
one frame. The lane then proves every movement pose against the real wall
geometry (see ``camera_clearance.validate_plan_clearance``) and refuses any
pose that enters the wall's avenue corridor.
"""

import copy
import math
from typing import Final, cast

from living_diorama.cinematic.camera_clearance import (
    WALL_HEIGHT,
    camera_half_fov_tangents,
    validate_plan_clearance,
    wall_segment_2d,
)
from living_diorama.cinematic.cinematic_schema_v1 import JsonValue
from living_diorama.cinematic.cinematic_schema_v2 import reason_for_move_is_bound
from living_diorama.cinematic.cinematic_spec import (
    CAMERA_ANCHORS,
    REASON_ADJACENT_SAME_ANCHOR_MERGED,
    REASON_BEAT_KIND_RULE,
    SHOT_BEAT,
    SHOT_ESTABLISHING,
)

# Anchors whose beats are law: a push-in toward the seal guides attention.
ATTENTION_ANCHORS: Final = frozenset({"CAM_SEAL_DETAIL"})
# Anchors whose beats are wall consequence: a push-in reframes the change.
CONSEQUENCE_ANCHORS: Final = frozenset({"CAM_HERO_SCAR", "CAM_SCAR_DETAIL", "CAM_P16_SCAR_CONTEXT"})
# The population-movement anchor: a track follows the flow.
FOLLOW_ANCHOR: Final = "CAM_P16_URBAN"

WALL_SHOT_ANCHOR: Final = "CAM_SCAR_DETAIL"
"""The one CONSEQUENCE_ANCHORS member that actually pulls back in EP1 today.

The other two (``CAM_HERO_SCAR``, ``CAM_P16_SCAR_CONTEXT``) already stand at
or beyond the required context distance and fall back to STATIC (see
``_consequence_context_end_pose``'s docstring), so this is the only anchor
``WALL_SHOT_BEARING_CORRECTION_DEG`` below is verified against.
"""

WALL_SHOT_END_ALTITUDE: Final = 24.0
"""The wall shot's end-pose altitude (z), in world units.

The wall-consequence pull-back ends 24.0 units up instead of copying the
anchor's own locked height (3.2): 6.7 units above the tallest catalogued real
roofline (17.3, ``LD_P16_BLDG__eastgate__blk_eastgate_business__m1``), so the
elevated end pose clears every real obstacle in the corridor by altitude even
where the ground-plane footprint check is tightest. It matches
``CAM_P16_SCAR_CONTEXT``'s z=24.0 as a scale reference only -- that anchor and
its assignment are untouched. ``_consequence_context_end_pose`` solves the
end (x, y) and the target distance from this altitude.
"""

WALL_SHOT_BEARING_CORRECTION_DEG: Final = 26.0
"""Counter-clockwise bearing correction for the wall shot's real EP1 pull-back.

The wall-consequence pull-back for ``CAM_SCAR_DETAIL``, derived along the
anchor's own straight line of sight (the un-corrected direction), drives
directly through REAL buildings in the composed scene. This was found in
two stages, both against the real, composed Blender scene, not assumed:

1. A real Blender raycast sweep along the un-corrected path found the
   camera 0.024 units from ``LD_P16_BLDG__eastgate__blk_eastgate_business__m1``
   (AABB x:[28.79,35.39] y:[21.14,27.44] z:[0.4,17.32]) -- the straight
   segment intersects it with 0.0 units of ground-plane clearance.
2. A clockwise rotation that clears THAT box (originally -55.0 degrees)
   was real-rendered and still produced a dark, low-detail dip in the
   rendered frames -- a second real raycast sweep along the ROTATED path
   found it grazing a SECOND real building,
   ``LD_P16_BLDG__eastgate__blk_eastgate_business__m0`` (a separate mesh of
   the same building complex) and then driving through a THIRD,
   ``LD_P16_BLDG__quay_north__blk_quay_office__m0``. This urban block is
   genuinely dense; checking one obstacle at a time and re-rendering to
   find the next one does not converge.

An exhaustive search was then run against EVERY real solid obstacle in the
corridor (every ``LD_P16_BLDG__*`` and ``LD_TREE__*`` object whose real
z-range -- read directly from the composed Blender scene -- includes the
camera's z=3.2; district "air" zones, street furniture, population slots,
ground/flood decals and the EP1 wall itself, already checked separately,
were excluded as not being solid collidable geometry), searching bearing
rotations in 0.1-degree steps from -90 to +90 degrees (a rotation beyond
that swings the pull-back to the opposite side of the look-at point --
cinematically a different shot, not a "pull out", and outside the region
this search's obstacle catalogue even covers). Finding: **no rotation in
that range clears every real obstacle by 2.0 units AND keeps the wall's
full height (including its near-top corner) and the Golden Seal inside the
frustum at the same time.** The building density and the frame-containment
requirement are genuinely in conflict for this anchor at its fixed height;
this is not a bug in the search, it was checked from both directions (zero
candidates clear every obstacle when full framing is required; zero
candidates achieve full framing when every obstacle is cleared).

Given that real conflict, this constant resolves it by PRIORITY, per the
Director revision's own explicit, unconditional requirement: "camera must
never enter/clip scene geometry" is a hard rule with no stated exception;
"the wall's full 16-unit height, including its topmost corner, and the
Golden Seal must both be inside the frame" was this revision's OWN earlier
target (chosen when 49.0 units was derived, to definitively fix the
one-wall-length pose's crop) -- a precision goal, not a separate hard
Director rule, and the one that yields. At 26.0 degrees (counter-clockwise):

* every cataloged real obstacle clears by >= 2.14 units along the ENTIRE
  swept segment (verified against this exact function's real output, not a
  simplified model of it; the smallest-magnitude valid rotation is 24.7
  degrees for a bare 2.0-unit margin -- 26.0 is chosen with a small extra
  margin, not the bare minimum);
* the avenue road and district_a stay inside the frustum, and the wall
  centerline clearance is comfortably exceeded (>= 26.0 units, well above
  the 4.9-unit gate);
* the wall's near-top corner is cropped by approximately 1.06 units out of
  the frame's top edge (its base and mid-height, and the wall's far-top
  corner, stay in frame) and the Golden Seal is no longer in frame -- both
  regressions from the 49.0-unit derivation's original ambition, both
  smaller in severity than a camera physically inside a building, and both
  clearly flagged here (and in the real test suite) for a creative reviewer
  to accept or revisit, rather than silently absorbed.

Scoped to ``CAM_SCAR_DETAIL`` (``WALL_SHOT_ANCHOR``) specifically: applying
an unverified rotation to a hypothetical future consequence anchor's own,
different real geometry would be a guess, not a derivation. If a future
episode ever routes a consequence beat through ``CAM_HERO_SCAR`` or
``CAM_P16_SCAR_CONTEXT`` with a pull-back that no longer falls back to
STATIC, this correction does NOT apply to them and their own real geometry
would need the same real-render verification this constant received.

Verified against every real obstacle the search catalogued, using pure 2D
ground-plane geometry (every included obstacle's z-range contains the
camera's z=3.2, so a 2D check is not merely sufficient but conservative)
AND against a real re-render of the full episode: the commander re-rendered
the real scene after this fix and confirmed the witness-closure gate still
passes (0.01866, comfortably under the 1.0 tolerance) and that the render's
per-frame pixel statistics across the wall shot's full frame range no
longer show the earlier hard blank-frame signature (std ~0.04, camera
embedded in a wall face) -- see the commit message and the Director
Revision checkpoint memory for the real render evidence and the residual
open question (a smaller, real, disclosed brightness dip remains at the
corrected bearing's closest approach to the nearest building, at real
~2-unit clearance; it reads as a real but comparatively minor depth-of-field
effect, not a clip, and is called out for a creative reviewer's eyes rather
than silently accepted).

At the elevated end altitude (``WALL_SHOT_END_ALTITUDE`` = 24.0, 6.7 units
above the tallest catalogued roofline 17.3) the same 26.0-degree bearing is
kept: the horizontal sweep's ground-plane projection is unchanged by the
altitude (the pull-back direction is horizontal), so the identical footprint
clearance evidence above carries over, and the added altitude clears every
obstacle's real z-range outright. The elevated pose's horizontal sweep
(x from 25.0 to ~25.66) never enters any catalogued obstacle's 2D footprint,
verified against ``REAL_NEARBY_OBSTACLES_XY`` in
``test_camera_grammar_revision.py``.
"""

MIN_TARGET_MOVEMENTS: Final = 5
MAX_TARGET_MOVEMENTS: Final = 7
PUSH_IN_FACTOR: Final = 0.85
PULL_OUT_FACTOR: Final = 0.15
TRACK_DISTANCE: Final = 6.0
PAN_YAW_RADIANS: Final = 0.20
TILT_PITCH_RADIANS: Final = 0.12
REVEAL_YAW_RADIANS: Final = 0.30
"""The deterministic movement magnitudes, in metres and radians.

Deliberately modest: a push-in travels 15% of the view distance, a pull-out
15% further back, a track six metres, a pan about eleven degrees, a reveal
about seventeen degrees. At 24 fps over a minimum six-frame shot the largest
per-frame delta stays far below the motion-quality bound the tests enforce.
"""

CAMERA_GRAMMARS: Final = ("v1", "v2")
"""The closed camera-grammar vocabulary.

``"v1"`` (default) is exactly today's role-to-movement table, byte for byte.
``"v2"`` is the Director-revision, context-first lane: zero default push-ins
and clearance-proven movement poses. ``camera_grammar`` is a different axis
from ``camera_profile``: the latter decides whether movement exists at all.
"""

GRAMMAR_V2_MOVEMENT_TYPES: Final = {
    "establishing_wide": "REVEAL",
    "closing_wider": "PAN",
    "attention": "REVEAL",
    "consequence": "PULL_OUT",
    "follow": "TRACK",
    "beat_emphasis": "PAN",
    "deliberate_hold": "STATIC",
}
"""The Director-revision role-to-movement table (``camera_grammar="v2"``).

* ``establishing_wide`` -> ``REVEAL`` -- already context-building, unchanged.
* ``closing_wider`` -> ``PAN`` -- the closing shot follows the wall shot's
  pull-out, so a second pull-out would chain into the exact oscillation the
  Director banned; a slow pan across the fixed world-hero vista reveals the
  city instead.
* ``attention`` -> ``REVEAL`` -- the Seal anchor's look-at is 14.3 units away
  and the seal fills the frame; a 0.30-rad sweep keeps the seal while opening
  the plaza around it.
* ``consequence`` -> ``PULL_OUT`` -- the wall shot pulls back to the additive
  context pose (the corrected-FOV distance derived from the real wall
  geometry, never closer to the wall). An anchor that already stands at or
  beyond that distance cannot pull out without violating the PULL_OUT
  contract; the planner falls back to a deliberate STATIC hold instead.
* ``follow`` -> ``TRACK`` -- already a real spatial travel, unchanged.
* ``beat_emphasis`` -> ``PAN`` -- a modest sweep, never a gratuitous push.
* ``deliberate_hold`` -> ``STATIC`` -- unchanged.
"""

SETTLE_MARGIN_FRAMES: Final = 24
"""The closing shot's settle margin, in frames.

The closing shot is the last thing the audience sees, and the render
pipeline's closure proof compares the shot's final playback frame
(``end_frame - 1``) with an independent witness frame (``end_frame``). Those
two frames must observe the camera FULLY at rest, or the ease-out tail of the
pan leaks real rigid motion into the measured ``png_mean_abs_difference``
(which a real render measured at 1.14-1.74 against the 1.0 tolerance, growing
as atmospheric fog was reduced -- the signature of a structural pose gap, not
sampling noise). The movement therefore completes ``SETTLE_MARGIN_FRAMES``
frames before the shot's declared end and holds flat from there to the
witness frame.

24 frames is exactly one second on the canonical 24 fps clock
(``motion_time_v1.json``), the top of the deliberate 12-24 range: it leaves
both boundary frames deep inside a one-second settled hold -- so the measured
witness difference is pure Monte-Carlo noise (~0.08 levels), far below the
1.0 tolerance even under the crisper daylight lane -- while keeping the pan
itself a comfortable one-second sweep (peak look-at angular rate under
0.8 degrees per frame, no whip). Only the ``closing_wider`` role earns a
``settle_frame``, and only under ``camera_grammar="v2"``; every other
movement block and the whole V1 lane keep today's byte-for-byte behavior.
"""


# --------------------------------------------------------------------------
# Easing and transform sampling (pure, shared with the Blender applier)
# --------------------------------------------------------------------------


def eased(t: float, easing: str) -> float:
    """Map a linear parameter in [0, 1] through an easing curve.

    ``LINEAR`` is identity; ``EASE_IN_OUT`` is smoothstep (``3t^2 - 2t^3``),
    which starts and stops at rest, so a keyframed camera never jerks at the
    cut. Any other name is a programming error and raises rather than guessing.
    """
    if easing == "LINEAR":
        return t
    if easing == "EASE_IN_OUT":
        return t * t * (3.0 - 2.0 * t)
    raise ValueError(f"unknown easing {easing!r}; expected LINEAR or EASE_IN_OUT")


def sample_transform(
    start: dict[str, object], end: dict[str, object], easing: str, t: float
) -> dict[str, object]:
    """Return the interpolated pose at parameter ``t`` in [0, 1].

    Location and look_at are component-wise convex combinations of the two
    endpoints under the easing curve; the lens is constant (a movement camera
    keeps the anchor's locked lens -- V2 never re-lenses). Because the
    interpolation is a convex combination along a straight segment, the sampled
    path is monotonic by construction; the tests prove it.
    """
    if not 0.0 <= t <= 1.0:
        raise ValueError(f"sample parameter t must be within [0, 1], got {t}")
    factor = eased(t, easing)
    location = [
        float(cast("int | float", a))
        + (float(cast("int | float", b)) - float(cast("int | float", a))) * factor
        for a, b in zip(
            cast(list[object], start["location"]),
            cast(list[object], end["location"]),
            strict=True,
        )
    ]
    look_at = [
        float(cast("int | float", a))
        + (float(cast("int | float", b)) - float(cast("int | float", a))) * factor
        for a, b in zip(
            cast(list[object], start["look_at"]),
            cast(list[object], end["look_at"]),
            strict=True,
        )
    ]
    return {
        "location": location,
        "look_at": look_at,
        "lens_mm": start["lens_mm"],
    }


def _movement_settle_frame(movement: dict[str, JsonValue], start_frame: int, end_frame: int) -> int:
    """Return the frame at which a movement's camera first reaches its settled pose.

    The movement block's optional ``settle_frame`` names the frame of the
    movement's second (fully-settled) keyframe. When the field is absent --
    every V1 movement and every non-closing-wider V2 movement -- the camera
    settles exactly at ``end_frame``, preserving today's behavior. The field
    is clamped into ``[start_frame, end_frame]`` by construction at assignment
    time (a shot too short to hold the margin falls back to ``end_frame``);
    this helper only reads it.
    """
    raw = movement.get("settle_frame")
    if raw is None:
        return end_frame
    return int(cast("int | float", raw))


def sample_movement_path(shot: dict[str, JsonValue]) -> list[tuple[int, dict[str, object]]]:
    """Sample the movement's poses per frame across the shot's window.

    Returns ``(frame, pose)`` pairs for every frame from ``start_frame`` to
    ``end_frame`` inclusive. Used by the motion-quality tests to prove
    monotonic progression and the per-frame delta bound without needing Blender.
    Returns an empty list for a shot without a ``camera_movement`` block.

    A movement carrying ``settle_frame`` completes its travel by that frame
    (the interpolation spans ``[start_frame, settle_frame]``, exactly as the
    Blender applier's two keyframes do) and every frame from ``settle_frame``
    on samples the fully-settled ``end_transform`` at ``t=1.0`` -- matching
    the applier's constant-hold extrapolation past its second keyframe. When
    ``settle_frame`` is absent it defaults to ``end_frame`` and the sampling
    is byte-for-byte today's.
    """
    raw_movement = shot.get("camera_movement")
    if raw_movement is None:
        return []
    movement = cast(dict[str, JsonValue], raw_movement)
    start_frame = int(cast("int | float", shot["start_frame"]))
    end_frame = int(cast("int | float", shot["end_frame"]))
    start = cast(dict[str, object], movement["start_transform"])
    end = cast(dict[str, object], movement["end_transform"])
    easing = cast(str, movement["easing"])
    settle_frame = _movement_settle_frame(movement, start_frame, end_frame)
    span = settle_frame - start_frame
    return [
        (
            frame,
            sample_transform(
                start,
                end,
                easing,
                1.0 if frame >= settle_frame else ((frame - start_frame) / span if span else 0.0),
            ),
        )
        for frame in range(start_frame, end_frame + 1)
    ]


def per_frame_delta_bound(shot: dict[str, JsonValue]) -> float:
    """Return the motion-quality bound: the largest legal per-frame location move.

    The eased path's maximum slope is 1.5 times the linear slope for
    ``EASE_IN_OUT`` (smoothstep's derivative peaks at 3/2 of the chord slope)
    and 1.0 for ``LINEAR``. The bound is therefore
    ``1.6 * |end - start| / (frames - 1)`` -- the worst-case eased slope plus
    a 6.7% margin -- so a compliant camera glides and never whips. A shot of
    one frame has no steps and is trivially within bound.

    The step count is the movement's EFFECTIVE span: ``settle_frame -
    start_frame`` when the block carries a settle frame (the travel completes
    there), ``end_frame - start_frame`` otherwise. A settle margin shortens
    that span, which raises the per-frame bound exactly as it raises peak
    velocity -- the 1.6/1.5 margin is what keeps the guarantee intact.
    """
    raw_movement = shot.get("camera_movement")
    if raw_movement is None:
        return 0.0
    movement = cast(dict[str, JsonValue], raw_movement)
    start = cast(dict[str, object], movement["start_transform"])
    end = cast(dict[str, object], movement["end_transform"])
    total = math.sqrt(
        sum(
            (float(cast("int | float", b)) - float(cast("int | float", a))) ** 2
            for a, b in zip(
                cast(list[object], start["location"]),
                cast(list[object], end["location"]),
                strict=True,
            )
        )
    )
    start_frame = int(cast("int | float", shot["start_frame"]))
    end_frame = int(cast("int | float", shot["end_frame"]))
    settle_frame = _movement_settle_frame(movement, start_frame, end_frame)
    steps = settle_frame - start_frame
    if steps < 1:
        return 0.0
    return 1.6 * total / steps


# --------------------------------------------------------------------------
# Movement derivation from each shot's real fields
# --------------------------------------------------------------------------


def _wall_context_target_distance(
    location: list[float], look_at: list[float], lens_mm: float
) -> float:
    """Return the exact minimum camera-to-look_at distance framing the whole wall.

    Closed form, solved from the real geometry -- no scan, no guessed margin.
    The camera pulls back along the horizontal unit vector ``u`` from the
    look-at point toward the anchor, so the end pose is ``location + delta * u``
    and the camera's horizontal distance from the look-at point is
    ``s_c = s0 + delta`` with ``s0`` the anchor's own horizontal distance.
    Each of the wall's eight real corners (the ``boundary_ab`` slab:
    ``wall_segment_2d()`` endpoints at base and full height) is expressed in
    the (u, v, z) frame anchored at the look-at point; its projected depth and
    vertical offset are

        depth_i = [s_c*(s_c - s_i) - z_c*z_i + z_c**2] / D
        up_i    = [s_c*z_i - z_c*s_i] / D

    with ``D = sqrt(s_c**2 + z_c**2)`` the camera-to-look-at distance and
    ``z_c = location[2] - look_at[2]`` -- so the caller controls the altitude
    the pull-back is solved at purely by the ``location`` it passes. The wall
    shot's caller passes an ELEVATED location (``WALL_SHOT_END_ALTITUDE`` =
    24.0, not the anchor's locked 3.2), which raises ``z_c`` from -4.4 to 16.4
    and moves the binding corner from a top corner to the wall's near-BASE
    corner. The wall's FULL HEIGHT is in frame exactly when
    ``|up_i| <= depth_i * v_tan``, i.e.

        |s_c*z_i - z_c*s_i| <= v_tan * (s_c**2 - s_c*s_i - z_c*z_i + z_c**2)

    which is a quadratic in ``s_c`` per corner; the smallest satisfying ``s_c``
    is its larger real root (a corner with a negative discriminant never crops
    at any distance). The required pull-back is the maximum of those roots --
    ``s_c`` grows monotonically with the pull-back. The caller rounds the
    returned distance UP to one decimal for the actual pull-back target, so the
    binding corner clears the frame edge with floating-point headroom instead
    of sitting exactly on it. The corners' fixed perpendicular offsets (the
    pull-back does not change them) and the surrounding-context points are
    proven against the real frustum function in the tests.

    Args:
        location: The camera's location, as a three-number list (its [2] is
            the altitude the pull-back is solved at).
        look_at: The camera's look-at point, as a three-number list.
        lens_mm: The camera's locked lens.

    Returns:
        The exact minimum camera-to-look_at distance (unrounded).

    Raises:
        ValueError: If the horizontal view direction degenerates.
    """
    hx = location[0] - look_at[0]
    hy = location[1] - look_at[1]
    horizontal = math.hypot(hx, hy)
    if horizontal < 1e-9:
        raise ValueError(
            "cannot derive the wall-context pose for a camera looking straight "
            "up or down; the wall shot needs a horizontal line of sight"
        )
    ux, uy = hx / horizontal, hy / horizontal
    z_c = location[2] - look_at[2]
    _h_tan, v_tan = camera_half_fov_tangents(lens_mm)

    # The wall's corners in the (u, v, z) frame anchored at the look-at point:
    # (along, height-relative). The perpendicular offset is constant under the
    # pull-back and is verified against the real frustum function in the tests.
    corners: list[tuple[float, float]] = []
    for ex, ey in wall_segment_2d():
        along = (ex - look_at[0]) * ux + (ey - look_at[1]) * uy
        for height in (0.0, WALL_HEIGHT):
            corners.append((along, height - look_at[2]))

    required_s = horizontal
    for s_i, z_i in corners:
        constant = v_tan * (z_c * z_c - z_c * z_i)
        # The two sign branches of |s_c*z_i - z_c*s_i| <= v_tan * B.
        for b, c in (
            (-(v_tan * s_i + z_i), constant + z_c * s_i),
            (-(v_tan * s_i - z_i), constant - z_c * s_i),
        ):
            discriminant = b * b - 4.0 * v_tan * c
            if discriminant < 0.0:
                continue  # quadratic is positive everywhere: corner never crops
            root = (-b + math.sqrt(discriminant)) / (2.0 * v_tan)
            required_s = max(required_s, root)
    return math.sqrt(required_s * required_s + z_c * z_c)


def _consequence_context_end_pose(
    location: list[float], look_at: list[float], lens_mm: float, anchor_id: str
) -> dict[str, object]:
    """Derive the Director-revision wall shot's additive context end pose.

    The Director's rule for the wall-consequence shot: never move the camera
    CLOSER to the wall, and end wide enough that the wall and the city around
    it share one frame. The additive pose is derived from the wall's REAL
    geometry and the corrected (width-governed) FOV model -- nothing guessed:

    * ``_wall_context_target_distance`` solves, in closed form, the minimum
      camera-to-look-at distance at which the wall's full height (both
      endpoints, base and full 16-unit height) fits inside the vertical
      half-FOV under Blender's AUTO sensor fit (16:9 render against the 3:2
      sensor, so the sensor WIDTH governs and the vertical tangent follows the
      render aspect). For the real 28 mm lens the exact minimum at the
      ELEVATED end altitude (``WALL_SHOT_END_ALTITUDE`` = 24.0, giving
      ``z_c = 24.0 - 7.6 = 16.4``) is 55.63 units, binding on the wall's
      near-BASE corner (s ~= 53.16); the target is rounded up one decimal to
      55.7 so the binding corner clears the frame edge with floating-point
      headroom. (At the anchor's own locked 3.2 the old derivation bound on a
      top corner at 48.94 -> 49.0.)
    * the camera retreats along the anchor's own horizontal line of sight
      (the horizontal pull-back unit vector from the wall toward the anchor)
      -- ROTATED by ``WALL_SHOT_BEARING_CORRECTION_DEG`` when ``anchor_id``
      is ``WALL_SHOT_ANCHOR``, since the un-rotated line drives straight
      through a real building (see that constant's docstring for the full
      real-geometry evidence) -- so the wall stays dead-centre in frame
      while the frame widens;
    * the wall shot's END ALTITUDE is ``WALL_SHOT_END_ALTITUDE`` (24.0) --
      6.7 units above the tallest catalogued real roofline (17.3,
      ``LD_P16_BLDG__eastgate__blk_eastgate_business__m1``) -- instead of
      copying the anchor's own locked 3.2, so the elevated end pose clears
      every real obstacle's z-range outright. Any other anchor keeps the
      historical copy-through of its own locked height. The camera keeps the
      anchor's locked lens -- no new lens, no lens animation.

    The pull-back ``delta`` solves ``|L0 + delta * u - look_at| == target``
    exactly (quadratic in ``delta``, positive root), where ``L0`` is the
    start pose at the END altitude (x, y unchanged; z = 24.0 for the wall
    shot) and ``u`` is the (possibly bearing-corrected) horizontal unit
    direction -- so the end pose's 3D distance from the look-at point lands
    exactly on ``target``: for the real wall shot,
    ``(25.0, 16.5, 3.2) -> (25.66, 47.48, 24.0)`` at 55.7 units. The
    derivation is a deterministic closed form, not a scan.

    Raises:
        ValueError: If the anchor is already at least as far from its look-at
            point as the exact minimum context distance (a pull-back would not
            increase distance, which would contradict the PULL_OUT contract),
            or if the horizontal view direction degenerates. The v2 planner
            treats the first case as "the anchor already frames the wall wide"
            and falls back to a deliberate STATIC hold.
    """
    hx = location[0] - look_at[0]
    hy = location[1] - look_at[1]
    horizontal = math.hypot(hx, hy)
    if horizontal < 1e-9:
        raise ValueError(
            "cannot derive the wall-context pose for a camera looking straight "
            "up or down; the wall shot needs a horizontal line of sight"
        )
    ux, uy = hx / horizontal, hy / horizontal
    if anchor_id == WALL_SHOT_ANCHOR:
        theta = math.radians(WALL_SHOT_BEARING_CORRECTION_DEG)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        ux, uy = ux * cos_t - uy * sin_t, ux * sin_t + uy * cos_t
    # The wall shot's end pose stands at the elevated altitude
    # (WALL_SHOT_END_ALTITUDE, 24.0 -- 6.7 units above the tallest real
    # roofline, 17.3) instead of copying the anchor's own locked 3.2. The
    # target distance AND the pull-back quadratic are both solved from that
    # elevated start, so the end pose lands exactly at the corrected target
    # distance D from the look-at point in 3D. Other anchors keep the
    # historical copy-through of their own locked height.
    end_altitude = WALL_SHOT_END_ALTITUDE if anchor_id == WALL_SHOT_ANCHOR else location[2]
    wx, wy, wz = (
        location[0] - look_at[0],
        location[1] - look_at[1],
        end_altitude - look_at[2],
    )
    start_distance = math.sqrt(wx * wx + wy * wy + wz * wz)
    distance_location = [location[0], location[1], end_altitude]
    exact = _wall_context_target_distance(distance_location, look_at, lens_mm)
    target = math.ceil(exact * 10.0) / 10.0
    if exact <= start_distance + 1e-9:
        raise ValueError(
            f"wall-context pose requires pulling back to {target} units from "
            f"the look-at point, but the anchor already stands {start_distance:.3f} "
            "units away; the pull-back would not increase distance"
        )
    along = wx * ux + wy * uy
    discriminant = along * along - start_distance * start_distance + target * target
    delta = -along + math.sqrt(discriminant)
    end_location = [
        location[0] + delta * ux,
        location[1] + delta * uy,
        end_altitude,
    ]
    return {
        "location": end_location,
        "look_at": list(look_at),
        "lens_mm": lens_mm,
    }


def _derive_movement(
    shot: dict[str, JsonValue], movement_type: str, camera_grammar: str = "v1"
) -> dict[str, JsonValue]:
    """Build a camera_movement block for one shot, from its anchor's locked pose.

    The start pose is exactly the anchor's locked catalogue pose; the end pose
    is a deterministic function of that pose and the movement type. The
    ``reason_for_move`` is built to contain the shot's own ``reason_code``, so
    the mechanical binding in ``cinematic_schema_v2`` accepts it.

    Under ``camera_grammar="v2"`` the ONLY ``PULL_OUT`` the table produces is
    the wall-consequence move, so a v2 ``PULL_OUT`` takes the additive context
    end pose above instead of the v1 fractional step. When the anchor already
    stands at or beyond the required context distance -- true of two of the
    three consequence anchors, ``CAM_HERO_SCAR`` (~60 units from its look-at)
    and ``CAM_P16_SCAR_CONTEXT`` (~69 units) -- no pull-back exists that
    increases distance, so the movement falls back to a deliberate STATIC
    hold: the anchor already frames the wall wide, and a pull-back would be
    meaningless there. The v1 ``PULL_OUT`` path is untouched, so the default
    lane stays byte-for-byte identical.
    """
    anchor_id = cast(str, shot["camera_anchor_id"])
    pose = CAMERA_ANCHORS[anchor_id]
    location = [float(cast("int | float", v)) for v in cast(list[object], pose["location"])]
    look_at = [float(cast("int | float", v)) for v in cast(list[object], pose["look_at"])]
    lens_mm = float(cast("int | float", pose["lens_mm"]))
    start: dict[str, object] = {
        "location": list(location),
        "look_at": list(look_at),
        "lens_mm": lens_mm,
    }

    reason_code = cast(str, shot["reason_code"])
    if movement_type == "STATIC":
        end = copy.deepcopy(start)
    elif movement_type == "PUSH_IN":
        end = {
            "location": [
                location[axis] + (look_at[axis] - location[axis]) * (1.0 - PUSH_IN_FACTOR)
                for axis in range(3)
            ],
            "look_at": list(look_at),
            "lens_mm": lens_mm,
        }
    elif movement_type == "PULL_OUT":
        if camera_grammar == "v2":
            try:
                end = _consequence_context_end_pose(location, look_at, lens_mm, anchor_id)
            except ValueError:
                # The anchor already stands at or beyond the exact minimum
                # context distance (or looks straight up/down), so no pull-back
                # exists that increases distance -- a PULL_OUT contract would
                # be violated. The anchor already frames the wall wide, so the
                # consequence beat falls back to a deliberate static hold.
                movement_type = "STATIC"
                end = copy.deepcopy(start)
        else:
            end = {
                "location": [
                    location[axis] + (location[axis] - look_at[axis]) * PULL_OUT_FACTOR
                    for axis in range(3)
                ],
                "look_at": list(look_at),
                "lens_mm": lens_mm,
            }
    elif movement_type == "TRACK":
        direction = [look_at[axis] - location[axis] for axis in range(3)]
        horizontal = math.sqrt(direction[0] ** 2 + direction[1] ** 2)
        if horizontal < 1e-9:
            step = (TRACK_DISTANCE, 0.0, 0.0)
        else:
            step = (
                direction[0] / horizontal * TRACK_DISTANCE,
                direction[1] / horizontal * TRACK_DISTANCE,
                0.0,
            )
        end = {
            "location": [location[axis] + step[axis] for axis in range(3)],
            "look_at": [look_at[axis] + step[axis] for axis in range(3)],
            "lens_mm": lens_mm,
        }
    elif movement_type in ("PAN", "REVEAL"):
        angle = PAN_YAW_RADIANS if movement_type == "PAN" else REVEAL_YAW_RADIANS
        direction = [look_at[axis] - location[axis] for axis in range(3)]
        cosine, sine = math.cos(angle), math.sin(angle)
        rotated = (
            direction[0] * cosine - direction[1] * sine,
            direction[0] * sine + direction[1] * cosine,
            direction[2],
        )
        end = {
            "location": list(location),
            "look_at": [location[axis] + rotated[axis] for axis in range(3)],
            "lens_mm": lens_mm,
        }
    elif movement_type == "TILT":
        direction = [look_at[axis] - location[axis] for axis in range(3)]
        horizontal = math.sqrt(direction[0] ** 2 + direction[1] ** 2)
        if horizontal < 1e-9:
            raise ValueError(f"cannot tilt a camera looking straight down on {anchor_id!r}")
        cosine, sine = math.cos(TILT_PITCH_RADIANS), math.sin(TILT_PITCH_RADIANS)
        pitched = (
            direction[0] * cosine - direction[0] * direction[2] * sine / horizontal,
            direction[1] * cosine - direction[1] * direction[2] * sine / horizontal,
            direction[2] * cosine + horizontal * sine,
        )
        end = {
            "location": list(location),
            "look_at": [location[axis] + pitched[axis] for axis in range(3)],
            "lens_mm": lens_mm,
        }
    else:
        raise ValueError(f"unknown movement type {movement_type!r}")

    return cast(
        dict[str, JsonValue],
        {
            "movement_type": movement_type,
            "start_transform": start,
            "end_transform": end,
            "easing": "EASE_IN_OUT",
            "reason_for_move": f"{reason_code} {_movement_purpose(movement_type)}",
        },
    )


def _movement_purpose(movement_type: str) -> str:
    """The fixed purpose phrase appended to a shot's own reason code."""
    return {
        "STATIC": "deliberate static hold",
        "PAN": "pan across the composition",
        "TILT": "tilt across the composition",
        "TRACK": "track with the movement",
        "PUSH_IN": "push in toward the subject",
        "PULL_OUT": "pull out to a wider view",
        "REVEAL": "reveal the wider world",
    }[movement_type]


def _role_for_shot(shot: dict[str, JsonValue], position: int, shot_count: int) -> str | None:
    """Return the movement role a shot earns from its real fields, or None.

    The role table is positional and closed: the first establishing shot is the
    establishing wide, the last is the closing wider view, and each beat role is
    keyed on the shot's real anchor and reason code. Nothing here inspects prose
    or invents meaning -- it maps the fields V1 already locked.
    """
    kind = cast(str, shot["kind"])
    reason = cast(str, shot["reason_code"])
    anchor = cast(str, shot["camera_anchor_id"])
    if kind == SHOT_ESTABLISHING:
        if position == 0:
            return "establishing_wide"
        if position == shot_count - 1:
            return "closing_wider"
        return None
    if kind == SHOT_BEAT and reason == REASON_BEAT_KIND_RULE:
        if anchor in ATTENTION_ANCHORS:
            return "attention"
        if anchor in CONSEQUENCE_ANCHORS:
            return "consequence"
        if anchor == FOLLOW_ANCHOR:
            return "follow"
        return "beat_emphasis"
    if reason == REASON_ADJACENT_SAME_ANCHOR_MERGED:
        return "deliberate_hold"
    return None


def _movement_type_for_role(role: str, camera_grammar: str = "v1") -> str:
    """Return the movement type one role earns under the chosen grammar lane."""
    if camera_grammar == "v1":
        return {
            "establishing_wide": "REVEAL",
            "closing_wider": "PULL_OUT",
            "attention": "PUSH_IN",
            "consequence": "PUSH_IN",
            "follow": "TRACK",
            "beat_emphasis": "PUSH_IN",
            "deliberate_hold": "STATIC",
        }[role]
    if camera_grammar == "v2":
        return GRAMMAR_V2_MOVEMENT_TYPES[role]
    raise ValueError(f"unknown camera grammar {camera_grammar!r}; expected 'v1' or 'v2'")


def plan_camera_movements(plan: object, *, camera_grammar: str = "v1") -> dict[str, JsonValue]:
    """Return a deep copy of a validated V1 shot plan with movement assigned.

    Every shot with a role earns a ``camera_movement`` block (its purpose
    derived from the shot's own reason code and anchor); every other shot stays
    exactly as V1 wrote it -- no key added, no key removed. The input document
    is never mutated.

    Under ``camera_grammar="v2"`` the ``closing_wider`` movement additionally
    carries a ``settle_frame``: the frame at which its camera first reaches the
    fully-settled ``end_transform`` pose (``end_frame - SETTLE_MARGIN_FRAMES``,
    clamped so a shot too short to hold the margin keeps ``settle_frame ==
    end_frame``, i.e. today's behavior, never an error). The movement then
    completes its travel by that frame and holds flat to the witness frame, so
    the shot's final playback frame (``end_frame - 1``) and the closure
    witness (``end_frame``) sample one identical, fully-at-rest pose. No other
    role and no V1 movement carries the field.

    Args:
        plan: A validated Shot Direction Plan V1 document.
        camera_grammar: ``"v1"`` (default) assigns today's role table, byte
            for byte. ``"v2"`` assigns the Director-revision, context-first
            table (zero default push-ins; the wall shot pulls back to the
            additive context pose) and then proves every movement pose against
            the real wall geometry, refusing any pose inside the wall's avenue
            corridor. This is a different axis from ``camera_profile``, which
            decides whether movement exists at all.

    Returns:
        A structurally identical document (deep copy) with the optional
        ``camera_movement`` keys added to the selected shots.

    Raises:
        TypeError: If the plan is not a document carrying a shots list.
        ValueError: If a shot's anchor is absent from the locked catalogue, if
            ``camera_grammar`` is not ``"v1"`` or ``"v2"``, or (under the
            ``"v2"`` lane) if any movement pose fails camera-to-geometry
            clearance.
    """
    if camera_grammar not in CAMERA_GRAMMARS:
        raise ValueError(f"unknown camera grammar {camera_grammar!r}; expected 'v1' or 'v2'")
    if type(plan) is not dict or type(plan.get("shots")) is not list:
        raise TypeError("camera movement planning requires a shot direction plan document")
    result = copy.deepcopy(plan)
    result_shots = cast(list[dict[str, JsonValue]], result["shots"])
    shot_count = len(result_shots)

    # Roles are assigned positionally, first matching shot per role, so there is
    # never a tie to break and nothing for a hash seed to disturb.
    assigned: set[str] = set()
    for position, shot in enumerate(result_shots):
        role = _role_for_shot(shot, position, shot_count)
        if role is None:
            continue
        if role in assigned and role != "beat_emphasis":
            continue
        anchor_id = cast(str, shot["camera_anchor_id"])
        if anchor_id not in CAMERA_ANCHORS:
            raise ValueError(
                f"shot {shot['shot_id']!r} names anchor {anchor_id!r}, which is absent "
                "from the locked camera catalogue"
            )
        movement = _derive_movement(
            shot, _movement_type_for_role(role, camera_grammar), camera_grammar
        )
        # The closing shot is the last thing rendered and the two frames the
        # closure proof compares (end_frame - 1 and end_frame) must both see
        # the camera fully at rest. Only this role, only under the v2 lane.
        if role == "closing_wider" and camera_grammar == "v2":
            start_frame = int(cast("int | float", shot["start_frame"]))
            end_frame = int(cast("int | float", shot["end_frame"]))
            settle = end_frame - SETTLE_MARGIN_FRAMES
            if settle <= start_frame:
                # Too short to hold any margin: fall back to no change in
                # behavior (settle exactly at end_frame), never an error.
                settle = end_frame
            movement = dict(movement)
            movement["settle_frame"] = settle
        shot["camera_movement"] = movement
        assigned.add(role)

    # Cap the total at seven movement blocks; the realistic EP1-scale plan
    # produces six, so this is a guard, not a normal path.
    moving = [shot for shot in result_shots if shot.get("camera_movement") is not None]
    if len(moving) > MAX_TARGET_MOVEMENTS:
        for shot in moving[MAX_TARGET_MOVEMENTS:]:
            shot.pop("camera_movement", None)

    # The Director-revision lane refuses any movement pose that enters the
    # wall's avenue corridor, by construction of its own derived poses and of
    # every anchor pose it starts from.
    if camera_grammar == "v2":
        validate_plan_clearance(result)

    return result


# --------------------------------------------------------------------------
# Metrics (pure, no I/O)
# --------------------------------------------------------------------------


def movement_metrics(plan: object) -> dict[str, int | dict[str, int]]:
    """Return the movement metrics for a (V1 or V2) shot direction plan.

    Pure and side-effect free: shot_count, static_shot_count, moving_shot_count,
    movement_type_histogram, shots_with_valid_reason_count and
    unmotivated_movement_violation_count (which is 0 for any plan this module or
    the V2 validator produced, because an unmotivated block is refused before it
    can exist).
    """
    if type(plan) is not dict or type(plan.get("shots")) is not list:
        raise TypeError("movement metrics require a shot direction plan document")
    shots = cast(list[dict[str, JsonValue]], plan["shots"])
    histogram: dict[str, int] = {}
    moving = 0
    valid_reason = 0
    violations = 0
    for shot in shots:
        raw_movement = shot.get("camera_movement")
        if raw_movement is None:
            continue
        movement = cast(dict[str, JsonValue], raw_movement)
        movement_type = cast(str, movement["movement_type"])
        histogram[movement_type] = histogram.get(movement_type, 0) + 1
        if movement_type != "STATIC":
            moving += 1
        reason = movement.get("reason_for_move")
        if reason_for_move_is_bound(reason, shot):
            valid_reason += 1
        else:
            violations += 1
    return {
        "shot_count": len(shots),
        "static_shot_count": len(shots) - moving,
        "moving_shot_count": moving,
        "movement_type_histogram": dict(sorted(histogram.items())),
        "shots_with_valid_reason_count": valid_reason,
        "unmotivated_movement_violation_count": violations,
    }
