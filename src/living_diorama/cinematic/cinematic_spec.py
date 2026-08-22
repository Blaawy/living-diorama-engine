"""Phase 22 direction policy: the closed, reviewable camera rule table.

Cinematic direction is presentation metadata, not world truth. Nothing in this
module decides what *happened*; it decides only which already-existing camera
anchor should be looking while Phase 21 says a given beat mattered.

The tables are keyed on the Phase 21 beat vocabulary. They never inspect prose,
never re-read the render export, and never reclassify a beat: a BACKGROUND beat
stays BACKGROUND here, and an event Phase 21 excluded is invisible to this layer
entirely. Phase 21 owns meaning; this layer owns viewpoint.

A beat kind this module does not know is never given a guessed viewpoint. It
falls back to the neutral establishing anchor and carries a reason code saying
so.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex

# --------------------------------------------------------------------------
# The camera anchor catalogue
# --------------------------------------------------------------------------

ANCHOR_PHASE15: Final = "master_scene_v1"
ANCHOR_PHASE16: Final = "production_world_v1"

ANCHOR_CLIP_END: Final = 1200.0
"""The far clip both world builders assign to every camera anchor they create."""

ANCHOR_PROJECTION: Final = "PERSP"
"""Every anchor is a perspective camera.

The builders never touch the projection type, so it is the factory default of
the supported Blender — inherited deterministically by every camera the locked
build produces. An anchor flipped to orthographic or panoramic renders a
different image through the same lens, so the applier proves this too.
"""

ANCHOR_SENSOR_WIDTH: Final = 36.0
"""The sensor width (mm) of every anchor: the supported Blender's default.

Never set by the builders, therefore inherited from the factory camera data —
and a mutated sensor changes the field of view without touching ``lens_mm``,
which is exactly the kind of silent re-framing the applier must refuse. The
in-Blender suite proves this value against the actually built scene, so the
restated default cannot drift from the supported Blender unnoticed.
"""

ANCHOR_CLIP_START: Final = 0.1
"""The near clip of every anchor: the supported Blender's default, unset by
the builders and proven against the built scene like the sensor width."""

ANCHOR_SHIFT: Final = 0.0
"""Lens shift (both axes) of every anchor: zero, the factory default.

A shifted lens re-frames the image while location, rotation and focal length
all stay locked, so the applier proves both axes are still zero.
"""

ANCHOR_SENSOR_FIT: Final = "AUTO"
"""Sensor fit mode of every anchor: the factory default.

Flipping this to VERTICAL makes the (otherwise idle) sensor height govern the
field of view -- a visibly different framing through the identical lens and
sensor width, found live by the wave-2 adversarial audit. Proven alongside the
width.
"""

ANCHOR_SENSOR_HEIGHT: Final = 24.0
"""Sensor height (mm) of every anchor: the factory default.

Idle while the fit is AUTO on a wide render, but proving it locked closes the
sensor pair completely instead of leaving a dormant dial.
"""

ANCHOR_APERTURE_RATIO: Final = 1.0
"""Depth-of-field bokeh anamorphic ratio: the factory default (round)."""

ANCHOR_APERTURE_BLADES: Final = 0
"""Depth-of-field bokeh blade count: the factory default (perfect circle)."""

ANCHOR_APERTURE_ROTATION: Final = 0.0
"""Depth-of-field bokeh rotation: the factory default."""


def _anchor(
    source: str,
    location: tuple[float, float, float],
    look_at: tuple[float, float, float],
    lens_mm: float,
    f_stop: float,
    *,
    dof: bool,
    focus: tuple[float, float, float] | None = None,
) -> Mapping[str, object]:
    """Freeze one catalogue record.

    ``focus`` defaults to ``look_at``, which is exactly the builders' own
    default: Phase 15 focuses every depth-of-field camera on its look-at point,
    and Phase 16 falls back to it when a config declares no explicit focus.
    """
    return MappingProxyType(
        {
            "source": source,
            "location": location,
            "look_at": look_at,
            "focus": look_at if focus is None else focus,
            "lens_mm": lens_mm,
            "f_stop": f_stop,
            "dof": dof,
            "clip_end": ANCHOR_CLIP_END,
            "clip_start": ANCHOR_CLIP_START,
            "projection": ANCHOR_PROJECTION,
            "sensor_width_mm": ANCHOR_SENSOR_WIDTH,
            "sensor_height_mm": ANCHOR_SENSOR_HEIGHT,
            "sensor_fit": ANCHOR_SENSOR_FIT,
            "shift_x": ANCHOR_SHIFT,
            "shift_y": ANCHOR_SHIFT,
            "aperture_ratio": ANCHOR_APERTURE_RATIO,
            "aperture_blades": ANCHOR_APERTURE_BLADES,
            "aperture_rotation": ANCHOR_APERTURE_ROTATION,
        }
    )


CAMERA_ANCHORS: Final[Mapping[str, Mapping[str, object]]] = MappingProxyType(
    {
        # Phase 15 — created by build_master_scene.py from master_scene_v1.json
        "CAM_HERO_SCAR": _anchor(
            ANCHOR_PHASE15, (72.0, -15.0, 8.5), (14.0, 0.5, 8.5), 35.0, 5.6, dof=True
        ),
        "CAM_HERO_WORLD": _anchor(
            ANCHOR_PHASE15, (86.0, -66.0, 34.0), (-10.0, 6.0, 4.0), 42.0, 8.0, dof=True
        ),
        "CAM_SCAR_DETAIL": _anchor(
            ANCHOR_PHASE15, (25.0, 16.5, 3.2), (14.2, -4.5, 7.6), 28.0, 4.0, dof=True
        ),
        "CAM_SEAL_DETAIL": _anchor(
            ANCHOR_PHASE15, (-2.0, 9.0, 6.2), (-17.0, 3.8, 5.2), 30.0, 4.0, dof=True
        ),
        # The builder disables depth of field on the orthographic-style survey
        # anchor, so its declared f-stop is recorded but never reaches the lens.
        "CAM_VERIFY_TOPOLOGY": _anchor(
            ANCHOR_PHASE15, (4.0, -30.0, 150.0), (-2.0, 4.0, 0.0), 38.0, 11.0, dof=False
        ),
        # Phase 16 — created by build_production_world.py from production_world_v1.json
        "CAM_P16_COMPOSITION": _anchor(
            ANCHOR_PHASE16,
            (-124.0, -88.0, 112.0),
            (4.0, 0.0, 0.0),
            38.0,
            11.0,
            dof=True,
            focus=(-6.0, -8.0, 2.0),
        ),
        "CAM_P16_CORE_CONTEXT": _anchor(
            ANCHOR_PHASE16,
            (84.0, -58.0, 46.0),
            (-20.0, 8.0, 0.0),
            36.0,
            9.0,
            dof=True,
            focus=(-16.0, 6.0, 3.0),
        ),
        "CAM_P16_DENSITY": _anchor(
            ANCHOR_PHASE16,
            (-98.0, -86.0, 72.0),
            (6.0, 6.0, 0.0),
            36.0,
            9.0,
            dof=True,
            focus=(0.0, 0.0, 4.0),
        ),
        # Straight-down survey anchors; the builder disables depth of field on both.
        "CAM_P16_ROADS": _anchor(
            ANCHOR_PHASE16,
            (2.0, -2.0, 272.0),
            (2.0, -2.0, 0.0),
            39.0,
            11.0,
            dof=False,
            focus=(2.0, -2.0, 0.0),
        ),
        "CAM_P16_SCAR_CONTEXT": _anchor(
            ANCHOR_PHASE16,
            (70.0, -36.0, 24.0),
            (14.0, 0.0, 7.0),
            38.0,
            8.0,
            dof=True,
            focus=(17.0, -1.0, 8.0),
        ),
        "CAM_P16_SYSTEM": _anchor(
            ANCHOR_PHASE16,
            (96.0, -96.0, 118.0),
            (-4.0, 0.0, 0.0),
            38.0,
            11.0,
            dof=True,
            focus=(0.0, 0.0, 2.0),
        ),
        "CAM_P16_URBAN": _anchor(
            ANCHOR_PHASE16,
            (-52.0, -118.0, 64.0),
            (10.0, -28.0, 0.0),
            38.0,
            9.0,
            dof=True,
            focus=(8.0, -50.0, 2.0),
        ),
        "CAM_P16_VALIDITY": _anchor(
            ANCHOR_PHASE16,
            (8.0, -100.0, 168.0),
            (2.0, 0.0, 0.0),
            42.0,
            11.0,
            dof=False,
            focus=(2.0, 0.0, 0.0),
        ),
        "CAM_P16_WORLD_HERO": _anchor(
            ANCHOR_PHASE16,
            (140.0, -116.0, 79.0),
            (-6.0, 2.0, -4.0),
            34.0,
            8.0,
            dof=True,
            focus=(12.0, -2.0, 4.0),
        ),
    }
)
"""Every camera this layer may select, and nothing else.

These are exactly the anchors the world builders create: five from Phase 15's
``master_scene_v1.json`` and nine from Phase 16's ``production_world_v1.json``.
Restated here rather than read from those files, because the planner is pure and
touches no filesystem; a test asserts this catalogue still agrees with both
configs field for field, so the two cannot drift.

Each record carries the anchor's whole locked visual identity, not just its
name: ``location``, the ``look_at`` point its orientation is derived from,
``lens_mm``, ``f_stop``, its depth-of-field ``focus`` point, whether the builder
enables depth of field at all (``dof``), the builder's uniform far clip
(``clip_end``), and the projection-geometry state the locked build inherits from
the supported Blender's factory camera (``projection``, ``sensor_width_mm``,
``shift_x``/``shift_y``, ``clip_start``) -- any of which would silently re-frame
the image if mutated, lens untouched. The Blender applier proves every one of
these against the actual scene object before it binds a single marker, so a
moved, rotated, re-lensed or
re-apertured anchor fails closed instead of being silently accepted as "the"
anchor. Three anchors -- ``CAM_VERIFY_TOPOLOGY``, ``CAM_P16_ROADS`` and
``CAM_P16_VALIDITY`` -- are built with depth of field disabled; their declared
f-stop exists in the configs but never reaches the camera data, and the applier
therefore proves ``dof`` is off for them rather than comparing an aperture the
builder never set.

Deliberately **excluded**: the ``CAM_P18_*`` and ``CAM_P19_*`` names. Those are
created by proof producers at proof time, not by the world builders, so they are
not present in the built scene this layer directs.

Phase 22 never creates, moves, rotates, or re-lenses any of these.
"""

ANCHOR_NAMES: Final = tuple(sorted(CAMERA_ANCHORS))
"""Every legal anchor identifier, sorted."""


def catalogue_document() -> dict[str, dict[str, object]]:
    """Return the catalogue as a JSON-ready document (tuples become lists).

    This is the single serialization form the catalogue digest is computed
    over, and the form the Blender gate ships to the applier -- so the digest
    the plan binds, the digest the validators recompute, and the digest the
    applier derives from the supplied data are all over identical structure.
    """
    return {
        name: {
            key: (list(value) if isinstance(value, tuple) else value)
            for key, value in record.items()
        }
        for name, record in CAMERA_ANCHORS.items()
    }


def catalogue_sha256() -> str:
    """Return the SHA-256 of the canonical catalogue serialization.

    Canonical bytes via :func:`dumps_canonical` -- sorted keys, tight
    separators, one trailing newline -- so key order and whitespace in any
    on-disk copy are immaterial while every VALUE is load-bearing: one moved
    anchor, one changed lens, one extra or missing camera changes the digest.
    A Shot Direction Plan binds this digest, the validators refuse any other,
    and the applier refuses a supplied catalogue whose canonical
    re-serialization does not hash to it -- which closes the trust boundary
    the independent review demonstrated: a scene mutated to match a mutated
    catalogue now fails on the catalogue's own identity, before any camera is
    even inspected.
    """
    return sha256_hex(dumps_canonical(catalogue_document(), "camera anchor catalogue"))


ESTABLISHING_ANCHOR: Final = "CAM_HERO_WORLD"
"""The neutral anchor that opens and closes every episode.

Phase 15's world hero. It carries no claim about what mattered, which is exactly
what an establishing and closing shot should carry, and using one anchor for both
ends is how loop closure is guaranteed rather than hoped for.
"""

# --------------------------------------------------------------------------
# Shot kinds and reason codes
# --------------------------------------------------------------------------

SHOT_ESTABLISHING: Final = "ESTABLISHING"
SHOT_BEAT: Final = "BEAT"
SHOT_KINDS: Final = (SHOT_ESTABLISHING, SHOT_BEAT)
"""A shot either frames a Phase 21 beat, or neutrally opens and closes."""

REASON_BEAT_KIND_RULE: Final = "BEAT_KIND_RULE"
REASON_NEUTRAL_ESTABLISHING: Final = "NEUTRAL_ESTABLISHING"
REASON_UNKNOWN_BEAT_KIND: Final = "UNKNOWN_BEAT_KIND"
REASON_ADJACENT_SAME_ANCHOR_MERGED: Final = "ADJACENT_SAME_ANCHOR_MERGED"
REASON_TRANSITION_BUDGET_EXHAUSTED: Final = "TRANSITION_BUDGET_EXHAUSTED"
REASON_NOTHING_TO_EMPHASIZE: Final = "NOTHING_TO_EMPHASIZE"
REASON_NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE: Final = "NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE"

REASON_CODES: Final = (
    REASON_BEAT_KIND_RULE,
    REASON_NEUTRAL_ESTABLISHING,
    REASON_UNKNOWN_BEAT_KIND,
    REASON_ADJACENT_SAME_ANCHOR_MERGED,
    REASON_TRANSITION_BUDGET_EXHAUSTED,
    REASON_NOTHING_TO_EMPHASIZE,
    REASON_NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE,
)
"""Exactly the reason codes this build emits."""

BEAT_SHOT_REASONS: Final = (
    REASON_BEAT_KIND_RULE,
    REASON_UNKNOWN_BEAT_KIND,
    REASON_ADJACENT_SAME_ANCHOR_MERGED,
)
"""The reason codes a beat shot may carry.

A beat shot exists because a Phase 21 beat asked for it, so its reason is the
rule that answered (``BEAT_KIND_RULE``), the honest fallback for a kind the table
does not know (``UNKNOWN_BEAT_KIND``), or the merge of adjacent beats that
resolved to one anchor (``ADJACENT_SAME_ANCHOR_MERGED``). The neutral and
unshown codes belong to other shapes and are refused on a beat shot.
"""

UNSHOWN_REASONS: Final = (
    REASON_NOTHING_TO_EMPHASIZE,
    REASON_TRANSITION_BUDGET_EXHAUSTED,
    REASON_NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE,
)
"""The reason codes an unshown-beat entry may carry.

A beat goes unshown for exactly three causes: it was Phase 21's empty-result
statement (``NOTHING_TO_EMPHASIZE``); the transition could not hold another
minimum-length shot (``TRANSITION_BUDGET_EXHAUSTED``); or no approved fixed
anchor has visual evidence of the beat's Phase 20 response within any derived
shot window (``NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE``). Any other code on an
unshown entry would claim a cause this layer cannot produce.
"""

# --------------------------------------------------------------------------
# The beat-kind rule table
# --------------------------------------------------------------------------

BEAT_ANCHORS: Final[Mapping[str, str]] = MappingProxyType(
    {
        # The law is sealed on the Golden Seal plaza, and Phase 17 animates its
        # glow there, so a law beat is shown where the law is.
        "LAW_CHANGE": "CAM_SEAL_DETAIL",
        "LAW_RESTORATION": "CAM_SEAL_DETAIL",
        # The wall stands on the scar. The hero framing shows it in the world;
        # the detail framing shows the wall itself changing.
        "WALL_RAISED": "CAM_HERO_SCAR",
        "WALL_STATE_CHANGE": "CAM_SCAR_DETAIL",
        # Durable memory has NO entry here: both durable beat kinds live in
        # UNSHOWN_BEAT_KINDS, on measured evidence -- see that table's comments.
        # Movement reads in the urban fabric rather than at a monument.
        "POPULATION_MOVEMENT": "CAM_P16_URBAN",
        # NO_EMPHASIZED_BEATS and DURABLE_CONSEQUENCE are deliberately absent:
        # they live in UNSHOWN_BEAT_KINDS, each with its stated reason.
    }
)
"""Which anchor frames each Phase 21 beat kind.

Every value must be a member of :data:`CAMERA_ANCHORS`; a test enforces that.
The table is deliberately small enough to read in one sitting, and every entry
has a stated reason in the comments above -- a reviewer can disagree with a
choice, which is the point of writing it down rather than computing it.
"""

# --------------------------------------------------------------------------
# Duration policy
# --------------------------------------------------------------------------

EMPHASIS_WEIGHTS: Final[Mapping[str, int]] = MappingProxyType(
    {"PRIMARY": 3, "SECONDARY": 2, "BACKGROUND": 1}
)
"""How much of the transition each emphasis level earns, relatively.

Phase 21 ranks; this turns its ranking into screen time. The weights are coarse
on purpose: a finer scale would imply a precision the emphasis levels do not
have. Phase 22 never reorders or re-ranks -- it only allocates.
"""

MIN_SHOT_FRAMES: Final = 6
"""No shot shorter than a quarter-second at 24 fps.

A cut the viewer cannot register is not direction, it is flicker.
"""

EMPTY_RESULT_BEAT_KIND: Final = "NO_EMPHASIZED_BEATS"
"""The Phase 21 beat that reports its own emptiness.

It earns no shot of its own: it is a statement about Phase 21's output, not about
the world, and framing it would be framing nothing. The episode still gets a
neutral establishing shot, and the beat is recorded as unshown so the plan
accounts for every beat it was given.
"""

UNSHOWN_BEAT_KINDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        EMPTY_RESULT_BEAT_KIND: REASON_NOTHING_TO_EMPHASIZE,
        # A NEW durable fact's stone does not exist yet while its beat is on
        # screen. Phase 20's locked memory_record channel is STEP interpolation
        # over window [0.35, 0.95] of the transition -- the stone appears at a
        # step at the window's END, frame 25 + round(0.95 * 120) = 139 on the
        # canonical clock -- and this layer's derived shot windows (rank order,
        # emphasis-weighted durations, holds fixed) place every possible
        # durable-consequence shot before that step. Framing an empty register
        # while narrating a new record would be fabricated visibility.
        "DURABLE_CONSEQUENCE": REASON_NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE,
        # A PERSISTED fact's stone does stand through its whole transition --
        # but the full-world gate measured that CAM_SEAL_DETAIL cannot see it:
        # nine of nine sample rays from the lens to the standing stone
        # terminate on LD_SEAL__disc, the monument's own raised drum, which
        # wholly occludes the record arc behind it. Phase 20's own record
        # already said the register is not legible at the hero cameras and
        # that its blind reviewer never saw the stones at the Seal framing --
        # which is why Phase 20 built the proof-only CAM_P20_RECORD_ARC. No
        # approved world-built anchor shows the register, no camera may be
        # created or promoted in V1, and pointing at the monument while
        # claiming to show the record would be symbolism sold as proof. Both
        # durable beats are therefore honestly unshown; the Story Plan remains
        # authoritative, and making the register visible is exactly the kind
        # of change that must arrive as a reviewed world-building decision,
        # not as this layer's improvisation.
        "CONSEQUENCE_PERSISTED": REASON_NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE,
    }
)
"""Beat kinds this layer deliberately leaves unshown, with their reasons.

Disjoint from :data:`BEAT_ANCHORS`; together the two tables cover every
Phase 21 beat kind, so the policy has an explicit, reviewable opinion about
each -- an anchor, or a stated reason there is none.
"""


def anchor_for_beat(beat_kind: str) -> tuple[str, str]:
    """Return (anchor, reason code) for a beat kind.

    An unrecognised kind is never given a guessed viewpoint: it falls back to the
    neutral establishing anchor and says so in its reason code, so a future
    Phase 21 beat kind produces an honest, slightly-flatter plan rather than a
    confidently wrong one.
    """
    anchor = BEAT_ANCHORS.get(beat_kind)
    if anchor is None:
        return ESTABLISHING_ANCHOR, REASON_UNKNOWN_BEAT_KIND
    return anchor, REASON_BEAT_KIND_RULE


def weight_for_emphasis(emphasis: str) -> int:
    """Return the relative screen-time weight of an emphasis level.

    An unrecognised level weighs the least rather than raising: Phase 21's
    vocabulary is closed and validated upstream, and if it ever grows, an unknown
    level should quietly get the smallest share rather than break direction.
    """
    return EMPHASIS_WEIGHTS.get(emphasis, 1)
