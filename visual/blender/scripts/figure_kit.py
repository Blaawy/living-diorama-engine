"""The Visual DNA v2 figure kit: how one visual identity becomes a body.

Pure Python by design -- no ``bpy``. Every proportion, every limb and every
feature is arithmetic over a visual identity, returned as explicit
PRIMITIVES: named lumps of geometry carrying their own vertices and faces.
The Blender builder welds them into one mesh; it decides nothing. A reviewer
can therefore check that a child is child-shaped, that a thigh is thicker
than a shin, or that a head is not a cube, on a machine with no Blender at
all -- by measuring the vertices the kit actually emitted.

    THIS KIT EMITS GEOMETRY, NOT BOXES.

That sentence survived from the first rebuild, and this file is the second.
The first rebuild removed the boxes; the render review then showed what the
un-boxed bodies still got wrong, and every one of those findings is now a
design decision here rather than a tuning accident: a brow that no longer
fuses with the eyes into sunglasses, hair that connects to the head it sits
on, a neck that is a neck and not a pedestal, an idle stance with two legs
instead of one bowling pin, feet that read as footwear, and knees that a
walk can visibly bend. The vocabulary is unchanged:

    faceted_head       a low-poly skull hull: radial facets, a crown and a
                       chin pole, a widest cheek ring and a narrowing jaw
    torso_hull         one lofted body from seat, pelvis, waist, chest,
                       clavicle and shoulder cross-sections
    tapered_segment    a limb chain: rings threaded along real joints,
                       thick end to thin end, with a calf and a knee
    foot_wedge         a real foot with a heel, an instep and a toe box
    hair_shell         a faceted covering that follows the round skull
    face_feature       a plate that CONFORMS to the curved face beneath it
    accessory          garment geometry that sits on a valid body

The kit is MODULAR, not a sculpt library. A body is assembled from five
independent choices -- an age presentation, a stature, a build, a head (hair
and face), and a clothing silhouette -- so a large visible variety costs a
small amount of geometry and no per-person artwork.

    LOCAL +X IS THE DIRECTION THE BODY FACES.

The object's Z rotation turns that into a world heading, so the face, the
lapel and the stride all point the same way as the proxy's orientation.

Material slots, in order:

    0  clothing        the garment palette
    1  complexion      skin
    2  hair            hair, brows and facial hair
    3  accent          eyes, mouth, footwear and dark garment detail

WHAT THIS IS NOT
----------------
These are VISUAL PRESENTATION ARCHETYPES. A masculine-presenting silhouette
is a silhouette; it is not a claim that a resident is male. An adult standing
near a child is composition; it is not a claim that anyone is anyone's parent.
The simulation holds an aggregate population count per district and nothing
else, so nothing here may be read back as a demographic fact -- and nothing
here is written into world state.
"""

import math

AGE_PRESENTATIONS = ("child", "teen", "adult", "elder")
STATURES = ("short", "average", "tall")
BUILDS = ("slim", "average", "athletic", "broad")
PRESENTATIONS = ("masculine", "feminine", "unspecified")
HAIR_VARIANTS = ("bald", "short", "medium", "long", "tied", "cap")
FACIAL_HAIR = ("none", "beard", "moustache")
FACE_VARIANTS = ("a", "b", "c", "d")
CLOTHING_SILHOUETTES = ("shirt", "short_sleeve", "jacket", "coat", "dress", "formal")

PRIMITIVE_KINDS = (
    "faceted_head",
    "torso_hull",
    "tapered_segment",
    "foot_wedge",
    "hair_shell",
    "face_feature",
    "accessory",
)
"""The complete geometry vocabulary. There is no box kind, and that is
deliberate: a body that could be described as boxes is the defect the first
rebuild existed to remove."""

PROPORTIONS = {
    "child": {
        "height": 1.15,
        "leg": 0.455,
        "torso": 0.305,
        "neck": 0.040,
        "head": 0.200,
        "shoulder": 0.225,
        "hip": 0.205,
        "depth": 0.130,
        "limb": 0.068,
        "upper_arm": 0.150,
        "forearm": 0.145,
        "hand": 0.066,
        "head_width": 0.82,
        "head_depth": 0.88,
        "lean": 0.0,
    },
    "teen": {
        "height": 1.60,
        "leg": 0.500,
        "torso": 0.301,
        "neck": 0.038,
        "head": 0.161,
        "shoulder": 0.235,
        "hip": 0.190,
        "depth": 0.118,
        "limb": 0.055,
        "upper_arm": 0.150,
        "forearm": 0.145,
        "hand": 0.062,
        "head_width": 0.74,
        "head_depth": 0.86,
        "lean": 0.0,
    },
    "adult": {
        "height": 1.75,
        "leg": 0.510,
        "torso": 0.304,
        "neck": 0.038,
        "head": 0.148,
        "shoulder": 0.245,
        "hip": 0.190,
        "depth": 0.124,
        "limb": 0.057,
        "upper_arm": 0.150,
        "forearm": 0.145,
        "hand": 0.062,
        "head_width": 0.74,
        "head_depth": 0.86,
        "lean": 0.0,
    },
    "elder": {
        "height": 1.68,
        "leg": 0.498,
        "torso": 0.310,
        "neck": 0.038,
        "head": 0.154,
        "shoulder": 0.232,
        "hip": 0.198,
        "depth": 0.128,
        "limb": 0.053,
        "upper_arm": 0.150,
        "forearm": 0.145,
        "hand": 0.060,
        "head_width": 0.74,
        "head_depth": 0.86,
        "lean": 0.030,
    },
}
"""Body proportions per age presentation, as FRACTIONS of total height.

``leg``, ``torso``, ``neck`` and ``head`` are the four stacked bands and sum
to exactly 1.0. The rest are widths and lengths, also relative to height, so
a figure scales as one coherent body rather than as a stretched adult.

The child is not a small adult and the numbers say so. Its head is 0.200 of
its height against an adult's 0.148 -- one head in five rather than one in
six and three-quarters -- its legs are 0.455 against 0.510, its shoulders are
narrow and its limbs are proportionally thicker. Uniformly scaling an adult
would have produced a 1.15m adult, which reads as a distant adult and not as
a child.

``height`` per age is UNCHANGED from the shipped candidate, on purpose, and
so is :data:`STATURE_SCALE`: height is published into the presence plan,
buckets :func:`silhouette_signature`, and sizes every walking speed and route
in Phase 19, so moving it would reshuffle the population while claiming to
have only redrawn a body. The BANDS below the height are the Visual DNA v2
redesign: legs are longer, the neck band is shorter, and each age owns its
head fraction, because those are what a silhouette is read from.

``upper_arm``, ``forearm`` and ``hand`` are the arm's real segment lengths;
the hand is new in v2 and slightly larger on a child and smaller on an elder.

``lean`` tilts the upper body forward. Only the elder carries any, and it is
posture, not infirmity.

``shoulder`` is the OUTER width of the upper body, arms included, not the
width of the torso between them.
"""

STATURE_SCALE = {"short": 0.93, "average": 1.00, "tall": 1.08}

BUILD_SHAPE = {
    "slim": {"shoulder": 0.88, "hip": 0.90, "depth": 0.84, "limb": 0.82, "waist": 0.92},
    "average": {"shoulder": 1.00, "hip": 1.00, "depth": 1.00, "limb": 1.00, "waist": 1.00},
    "athletic": {"shoulder": 1.14, "hip": 0.92, "depth": 1.02, "limb": 1.08, "waist": 0.84},
    "broad": {"shoulder": 1.16, "hip": 1.18, "depth": 1.24, "limb": 1.22, "waist": 1.06},
}
"""Build changes the SHAPE, not just the scale.

Athletic widens the shoulders while narrowing the hips and cutting the waist
hard; broad widens everything and deepens the torso; slim narrows throughout.
The v2 spreads are wider than the first rebuild's on purpose: a broad figure
is now more than 1.2 times a slim one at the shoulder, which is the point at
which the difference survives thirty metres of distance.

``waist`` feeds the waist pinch in :func:`figure_dimensions`, where it is
clamped so that no combination of build and presentation can ever produce a
barrel-sided torso.
"""

PRESENTATION_SHAPE = {
    "masculine": {"shoulder": 1.10, "hip": 0.92, "waist": 1.04, "chest_reach": 1.00},
    "feminine": {"shoulder": 0.90, "hip": 1.14, "waist": 0.82, "chest_reach": 1.06},
    "unspecified": {"shoulder": 1.00, "hip": 1.00, "waist": 1.00, "chest_reach": 1.00},
}
"""Shoulder-to-hip relationship, waist taper, and one forward chest reach.

This is silhouette, and it is all it is. ``chest_reach`` extends only the
FRONT half of the chest cross-section, which changes a profile without
touching a width that any plan or signature reads.
"""

FACE_SHAPE = {
    "a": {"width": 1.00, "brow": 1.00, "eye_gap": 1.00, "nose": 1.00, "jaw": 1.00, "chin": 1.00},
    "b": {"width": 1.06, "brow": 1.15, "eye_gap": 1.06, "nose": 0.90, "jaw": 1.08, "chin": 0.85},
    "c": {"width": 0.94, "brow": 0.85, "eye_gap": 0.94, "nose": 1.12, "jaw": 0.94, "chin": 1.15},
    "d": {"width": 1.02, "brow": 1.05, "eye_gap": 0.90, "nose": 1.05, "jaw": 1.04, "chin": 0.92},
}
"""Four restrained facial proportions. Enough that two heads differ; far
short of anything that could be called a likeness.

``jaw`` and ``chin`` are new in v2 and reach the SKULL, not only the plates:
jaw scales the width of the jaw ring, chin scales how far forward the chin
pole sits. A face variant therefore changes the head's silhouette, and it
also selects between each hair variant's two sub-silhouettes, which doubles
the visible hair variety at no vocabulary cost.
"""

CLOTHING = 0
COMPLEXION = 1
HAIR = 2
ACCENT = 3

FOOTWEAR = {
    "shirt": ACCENT,
    "short_sleeve": ACCENT,
    "jacket": ACCENT,
    "coat": ACCENT,
    "dress": CLOTHING,
    "formal": ACCENT,
}
"""Which material slot a silhouette's FEET are drawn in.

The render review's finding was blunt: complexion-coloured feet read as bare
feet, and a coat-wearing elder in beige slippers is a costume error, not a
person. Feet are footwear now -- accent-dark shoes for every silhouette
except the dress, whose lighter palette-toned treatment reads as part of the
garment. Deterministic per silhouette, so a proxy's shoes cannot flicker
between builds.
"""

FOOTWEAR_SHAPE = {
    "shirt": (1.00, 0.96, 1.00),
    "short_sleeve": (0.94, 0.94, 0.86),
    "jacket": (1.02, 0.90, 1.12),
    "coat": (1.06, 0.98, 1.22),
    "dress": (0.90, 0.86, 0.82),
    "formal": (1.08, 0.86, 1.28),
}
"""Each silhouette's own shoe: ``(length, width, instep height)`` multipliers
on the published foot dimensions.

The art review found one shoe on every figure and called it a flipper, which
is what a single wide low slab is. A shoe is the smallest thing on a body and
the most repeated, so the whole fleet wearing one pair is a costume error
that scales. These are the difference between a dress shoe, a work shoe and
a summer one, at no geometric cost: the published ``foot_length``,
``foot_width`` and ``foot_height`` are untouched, and every multiplier keeps
the built width inside the 0.055-of-height clamp the foot guard asserts.
"""


# ---------------------------------------------------------------------------
# Resolution: how many facets each part of the body is allowed
# ---------------------------------------------------------------------------

HEAD_SIDES = 12
TORSO_SIDES = 8
LEG_SIDES = 6
ARM_SIDES = 6
NECK_SIDES = 6
HAIR_SIDES = 12
HAIR_VOLUME_SIDES = 5
"""Radial facet counts, one per body part.

These are the cost dials, and v2 turned them UP under a raised budget: the
directive's ceiling is now 950 triangles a figure and 68,000 for the
canonical eighty, and the extra spend went where the first rebuild was
visibly coarse. The head takes twelve facets because the head is what gets
inspected -- at eight, the skull's silhouette still read as a nut. The torso
takes eight so a lapel and a waist survive a three-quarter view. Legs take
six -- enough to read as round in a walk cycle, and mirror-symmetric about the
centreline by construction -- and carry five rings instead of three, because a
knee and a calf are the difference between a leg and a table leg. Hair matches
the head, as it must:
a shell with fewer sides than the skull it covers passes inside the skull's
vertices, which is the bare-crown defect the first rebuild shipped.
"""

SKIRT_STEP = 0.17
"""The most head-height one stage of a hair skirt may span.

A skirt descends in stages, and the number of them is DERIVED from how far
the skirt falls rather than fixed, because the defect they exist to prevent
scales with the span. Every stage is a straight loft band, every straight
band across a curved skull is a chord, and a chord long enough sags inside
the surface it crosses -- which is bare scalp. Three stages were enough for
a short cut and not for a long one: the deep skirts sagged five millimetres
inside the occiput between their own rings, under the bevel, in exactly the
place the earlier single-ring skirt had failed. Capping the span of a stage
fixes it at every depth and needs no per-treatment tuning.
"""

DELTOID_FLARE = 1.45
"""How much fuller the deltoid ring is than the arm's published thickness.

A deltoid is the widest part of an arm, and it has to be: the ring's INNER
edge is what overlaps the torso, so a ring sized to the forearm's parent
radius leaves the arm hanging beside the body with daylight between them on
exactly the builds that combine wide shoulders with slim limbs. Flaring it
moves the inner edge inboard while the outer edge still lands precisely on
the published shoulder width. This is not the flare that produced the
pauldron -- that one sat up under the shoulder line with a flat top over it;
this one sits at the bottom of a forty-two degree slope, which is where a
deltoid belongs.
"""

SHOULDER_YOKE = 0.875
"""How much of the published shoulder ring the hull's TOP cross-section keeps.

The blind art review's first complaint was the shoulder: hard shards flaring
sideways and forward past the arm, reading as armour rather than as a body.
Measured, that was not the arm at all. The hull's top ring carried the full
published ``torso_shoulder_width`` and was closed with a FLAT horizontal
n-gon, so every figure wore a level plate across the top of its shoulders --
a third of the shoulder half-width deep, standing five centimetres further
forward than the arm beneath it -- and the arm emerged from under its rim
through an eighty-four degree drop.

Two things fix it together and neither works alone. The cap is replaced by
the trapezius rings below, and the rim is pulled IN to this fraction so that
it lands on the line the arm's own outer surface is already travelling: the
socket is seated against the narrowed ring (see :func:`_pose_frame`), the
deltoid still reaches the published shoulder width, and the run between them
still falls at :data:`SHOULDER_SLOPE`, so the arm now takes the silhouette
over within a couple of centimetres of the rim instead of hanging inside it.

The published ``torso_shoulder_width`` is untouched: it is a measurement of
the body, and this is how much of it the top-most SECTION draws.
"""

SHOULDER_SLOPE = math.radians(42.0)
"""How steeply the arm's outer surface must fall from the socket to the deltoid.

A shoulder whose outer surface slopes 25 degrees from horizontal is a shelf,
and a shelf on a jacket is a shoulder pad -- which is what replaced the
pauldron the flare had produced. Above forty degrees the same span reads as
the slope off a deltoid. Because the whole run is ONE straight segment from
the socket to the deltoid, the average IS the minimum: no part of it can be
flatter than this, and there is no intermediate ring to break the run into a
slope and a ledge. A four-ring upper arm was tried and withdrawn -- see
:data:`CHAIN_SPEC` -- precisely because the extra ring put a horizontal
crease across the middle of this span.
"""

NAPE_TOP = 0.660
"""Where a hair shell hands over from its crown to its nape, as a head-height
fraction.

This exists because of how the occlusion contract is MEASURED. The built
structural gate asks whether any hair primitive's axis-aligned bounds, in
BODY space with the head turned, reach further forward than an eye's while
overlapping it sideways and vertically. Axis-aligned bounds conflate a
primitive's extremes: a single shell that touches the hairline at the front
AND falls past the ear at the back reports the front's reach together with
the nape's depth, and on a turned head that rectangle swallows the far eye --
which is exactly the regression the gate caught. Nothing was actually in
front of an eye; the shell simply became one object spanning both.

So the covering is emitted as two: a CROWN that reaches the face but stops
above the eye line, and a NAPE that falls past the ear but never comes
forward of the temple. Neither can trip the rule, and the two share their
boundary vertices exactly, so the mesh is welded and the seam is invisible.
The split level sits above the eyes with room to spare.
"""

NAPE_FRONT_LIMIT = 0.30
"""How far forward the nape is allowed to wrap, as a facet cosine.

Only facets at or behind this are given to the nape, which keeps its forward
reach near the temple rather than the brow -- the property that lets it hang
below the eye line without ever reporting bounds in front of an eye.
"""

HAIR_LIFT_FLOOR = 0.006
"""The least a hair shell may stand off the skull, in metres.

A ratio-based lift alone is not a guarantee: 1.028 of a narrowing crown is
under three millimetres, which is less than the bevel the proxy build rounds
its edges by, so the skull rendered THROUGH its own hair as pale slots. Every
shell ring therefore carries at least this much absolute clearance on top of
whatever the ratio gives.
"""

_LIMB_REFERENCE = 0.057 * 1.75
"""The average adult's limb dimension in metres, the anchor for limb radii.

Every ring radius in :data:`LEG_LOFT`, :data:`ARM_LOFT` and the hand paddle
is authored in metres ON THAT BODY and scaled by ``limb / _LIMB_REFERENCE``
for everyone else. The scale therefore carries height, build AND the per-age
limb column together -- which is what keeps a child's limbs proportionally
chunky and an elder's spare, instead of every age wearing adult limbs at a
different height.
"""

LEG_LOFT = (
    ("hip", 0.082, 1.04, 0.000),
    ("thigh", 0.0660, 1.02, -0.0005),
    ("knee", 0.0470, 1.00, 0.0022),
    ("calf", 0.0540, 1.08, -0.0012),
    ("ankle", 0.026, 1.00, 0.000),
)
"""The leg's five cross-sections: ``(name, radius, depth factor, forward shift)``.

Radii are metres on the reference adult (see :data:`_LIMB_REFERENCE`); the
depth factor deepens a ring front-to-back and the shift slides its centre
along the facing axis. Read together they are a leg rather than a cone: a
thigh that is fuller behind than the knee line, a knee that is a real pinch
nudged forward where a kneecap sits, a calf that swells BELOW the knee and
sits back,
and an ankle a third of the thigh. The knee pinch is also what makes a
walking leg read as bending -- a straight taper hides its own knee, which the
renders called "compass-legged".

A sixth ring, a ``kneecap`` sitting just below the knee at the same radius,
was carried here for a while and has been withdrawn. Its purpose was never
the pinch: it was to make the band across the knee vertical, so that the
hinge where a rigidly-rotating thigh meets a DEFORMING shin measured only a
few degrees instead of the joint's whole travel. That mattered while the
proxy build selected bevel edges by dihedral angle, because a hinge crossing
the limit over a stride changed the evaluated vertex count between frames of
a walk. The applier now bevels by topology, so the angle is nobody's
business, and the ring was twelve triangles a leg spent on a threshold that
no longer exists. The pinch it was mistaken for lives in the radii, where it
always did: the thigh and the calf are both fuller than the knee between
them, and dropping the extra ring leaves that reading untouched while the
calf's swell becomes one continuous run instead of two.
"""

ARM_LOFT = (
    ("deltoid", 0.049, 0.000),
    ("elbow", 0.0315, 0.000),
    ("wrist", 0.020, 0.000),
)
"""The arm's three cross-sections: ``(name, radius, forward shift)``, metres
on the reference adult. The deltoid is the junction that carries the shoulder
silhouette out to the full shoulder width; the wrist is where the hand rides."""

GARMENT_HEM = {
    "jacket": (0.8785, 1.02, 0.96, 0.05),
    "formal": (0.8785, 1.02, 0.96, 0.05),
    "coat": (0.620, 0.82, 1.15, 0.02),
    "dress": (0.660, 0.84, 1.15, 0.02),
}
"""The extra bottom ring a garment lengthens the body with:
``(level as a fraction of leg top, hip flare, depth reach, lean share)``.

The flares are far smaller than the ones this replaces, and the long hems
sit higher, because of what the wide ones did to the HANDS. A coat flaring
1.12 of the hip at mid-shin and a dress flaring 1.25 both reached out past
the point an idle hand hangs, so the hand either speared the skirt -- the
"two small triangular flaps sticking out at hip height" the art review read
as unclosed pocket geometry -- or ran a hundred millimetres down it four
millimetres clear, which is a slit of daylight and reads as a split seam.
A coat is a coat at 1.04; nothing about the silhouette needed a crinoline.

The DEPTH reach is untouched, because it is not what was in the way: a hem
has to stand far enough forward of the hip for a swinging thigh to pass
inside it, and that clearance is a front-to-back measurement. Only the
lateral flare crowded the hands.

The jacket's level is authored the same way as the rest rather than as a
height offset, and lands within a centimetre of where
``leg_top - 0.062 * height`` used to on every age band.
"""

HIP_SECTIONS = (0.98, 1.03)
"""The seat and the pelvic crest, as multiples of the published hip width.

Named rather than buried in :func:`_torso_hull` because :data:`GARMENT_WIDEST`
has to know how far the widest ring of a hip reaches sideways, and a copy of
1.03 living in two places is the kind of drift that reopens a closed defect.
"""

GARMENT_WIDEST = max(
    max(HIP_SECTIONS) * 1.06,
    *(
        flare * (1.0 if name == "dress" else 1.06)
        for name, (_level, flare, _reach, _tilt) in GARMENT_HEM.items()
    ),
)
"""The widest anything below the waist can be, as a multiple of the hip.

Derived from the hip rings and :data:`GARMENT_HEM` including the jacket
family's 1.06 hull bonus, because :func:`_pose_frame` places an arm before it
knows what the body is wearing -- and an arm placed for a shirt and then
dressed in a coat is the flap the art review saw sticking out of the pink
dress.
"""

COLLAR_LIFT = 0.0015
"""How far a lapel stands off the garment it is sewn to, in metres.

A collar is CLOTH ON CLOTH. Standing it off by four millimetres and then
letting the proxy bevel round its free edges gave it a thickness of its own,
which is the whole difference between a lapel and something laid across a
chest. A millimetre and a half is enough to beat coplanar z-fighting and
nothing like enough to read as a separate object.
"""

HAND_CLEARANCE = 0.009
"""The least daylight between a hanging arm and the garment beside it, as a
fraction of the body's height.

Bigger than the bevel the proxy build rounds every edge by, and deliberately
so: a gap under that reads as a crack in one surface rather than as the space
between two, which is exactly how a hundred-millimetre run of four-millimetre
daylight down a coat presented itself."""

ARM_HANG = (1.00, 1.08, 1.16)
"""Where an idle elbow, wrist and hand sit across the body, as fractions of
the arm's own root offset -- a FLOOR, not the answer.

The answer is solved in :func:`_pose_frame` against the hip, because these
fractions cannot survive the vocabulary on their own. A published shoulder
half-width less its deltoid reach lands within a couple of millimetres of a
published hip's own half-width on most builds, so an arm hung as a fraction
of the first runs down the second at a distance no dial can control: the
measured result was a hundred and sixteen millimetres of daylight between
two and six millimetres wide, from the waist to the hip, on an ordinary
adult in a jacket. That is a slit rather than a gap. It reads as a model
that failed to close, and it is what the art review saw through.

Sweeping these three numbers cannot fix it. Every value tried put SOME build
back into a near-parallel run, because the two surfaces are near-parallel by
construction and the dial only chooses which body it happens to.
"""

HAND_LOFT = (
    ("knuckle", 0.40, 0.0238, 0.0430),
    ("fingers", 0.80, 0.0214, 0.0462),
    ("tip", 1.00, 0.0116, 0.0258),
)
"""The hand's cross-sections: ``(name, along, lateral, deep)``.

``along`` is the fraction of the hand's own length below the wrist; the two
half-extents are metres on the reference adult, scaled like every other limb
radius (see :data:`_LIMB_REFERENCE`).

A HAND USED TO BE TWO RINGS, and the blind art review's verdict on it was
that there were no hands at all: "sleeves end, a short flesh cone appears,
then nothing -- amputated at the wrist", "a flat one-sided flap with no
thickness". It was reading exactly what was built. One band ran from the
wrist's own circle to a single paddle and a flat n-gon closed it off, so a
hand was a truncated cone with a lid, and the lid was the largest face on
it.

Four rings make it a mitt. The knuckle swells past the wrist in BOTH
horizontal axes -- that step out of the sleeve is the thing that reads as a
wrist, and a taper alone can never produce it -- the fingers carry the mass
on and slightly narrower, and the tip pulls in to under half the width at
both ends, so the hand closes as a rounded end rather than a cut one. What
remains of the flat cap is 12mm by 26mm on an adult, aimed at the ground,
behind the bevel that rounds it.
"""

HAND_PADDLE = (
    max(lateral for _name, _along, lateral, _deep in HAND_LOFT),
    max(deep for _name, _along, _lateral, deep in HAND_LOFT),
)
"""The hand's widest cross-section: lateral and deep half-extents.

Derived from :data:`HAND_LOFT` rather than authored beside it, so the
published summary of a hand's bulk cannot drift away from the hand that is
actually built."""


def _facet_phase(sides: int) -> float:
    """Half a facet of rotation, so a FACE is centred dead ahead.

    Without it an even-sided ring puts a VERTEX on the centreline, which runs
    a vertical crease straight down the middle of the face. With it, a flat
    facet is centred dead ahead -- a cheek plane to mount a face on -- and the
    ring is still exactly symmetric left to right.
    """
    return math.pi / sides


CHAIN_SPEC = {
    "leg": {
        "sides": LEG_SIDES,
        "members": {"leg": (0, 1, 1, 2, 2)},
        "joints": (("leg", 0), ("leg", 2), ("leg", 4)),
        "foot": "foot",
    },
    "arm": {
        "sides": ARM_SIDES,
        "members": {"upper_arm": (0, 0, 1), "forearm": (1, 2), "hand": (2, 2, 2, 2)},
        "joints": (("upper_arm", 1), ("upper_arm", 2), ("forearm", 1)),
        "foot": None,
    },
}
"""THE articulation contract between this kit and Phase 19 mobility.

Phase 19 owns how a body WALKS; this kit owns how a body IS. The border
between them is this table, and it is published here so that only one module
ever describes a limb's structure. For each chain, per side:

``members``
    every primitive the chain is drawn from, in emission order, mapping the
    primitive's name suffix to the articulation LEVEL of each of its lofted
    rings -- 0 rides the body, 1 swings about the root joint, 2 swings about
    the middle joint and then the root with it. The leg is one five-ring
    loft; the arm is three members whose seam rings are built COINCIDENT, so
    the sleeve's elbow and the forearm's elbow are the same circle of
    vertices and no articulation can open a seam. The hand's rings are all
    level 2: it is a rigid rider on the wrist, and it carries FOUR of them --
    the wrist seam it shares with the forearm, a knuckle, the fingers and a
    closing tip -- because a two-ring hand is a cone with a lid and renders
    as an amputation. See :data:`HAND_LOFT`.

    The upper arm carries THREE rings, root to tip: a socket tucked up inside
    the torso hull -- the narrower of the two static bands, which is what lets
    it hide there -- then the deltoid, which is the WIDEST band and carries
    the shoulder silhouette out to the published width, then the elbow.
    Socket and deltoid are both level 0: the deltoid is the shoulder pivot,
    and rotating a ring about itself is the identity, so declaring it level 0
    costs nothing and keeps the shoulder welded into the body while the arm
    swings beneath it.

    A FOURTH ring once sat between them -- a collar at the deltoid's own
    radius, a little above it -- and it is worth recording why it is gone. It
    was never shape. It existed so that the last static band would be
    vertical and the hinge at the deltoid would measure a couple of degrees
    instead of forty, because the proxy build then selected bevel edges by
    the angle between adjacent faces, and a hinge that crossed the limit over
    a stride was beveled on some frames of a walk and not on others, which
    changed the evaluated vertex count between frames. The applier no longer
    asks that question -- it bevels by topology, so the beveled set follows
    the identity and not the pose -- and the ring's whole justification went
    with it. What it cost was the thing a viewer actually reads: sitting at
    the published shoulder width a hand's breadth above the deltoid, it laid
    a horizontal yoke across the shoulders with a hard step down onto the
    chest, and left the arm a flat-topped block overhanging that step. The
    socket-to-deltoid run is one straight segment again, and a shoulder is a
    continuous slope from the neck to the arm.
``joints``
    which member's ring the root, middle and tip joints are measured from.
    A joint is the CENTROID of a built ring, never a number from a table.
``foot``
    the name suffix of the solid that rides the tip joint, or ``None``.

Chain members are pole-less lofts: their vertex counts are exact multiples
of their ``sides``, root ring first, so mobility can cut them back into the
rings they were built from without guessing.
"""


class FigureKitError(ValueError):
    """A visual identity the kit cannot build.

    Raised for an unknown archetype, stature, build, hair, face or clothing
    silhouette. Always a refusal: a body assembled from a value nobody
    defined would be a body nobody designed.
    """


def _require(value: str, allowed: tuple[str, ...], field: str) -> str:
    """Return one of a closed vocabulary, else refuse."""
    if value not in allowed:
        raise FigureKitError(f"unknown {field} {value!r}; expected one of {allowed}")
    return value


def figure_dimensions(identity: dict) -> dict:
    """Every measurement one body is built from, in metres.

    Pure arithmetic over the identity, exposed separately from the geometry
    so the proportions can be interrogated -- is this child shorter than every
    adult, is this broad figure wider than this slim one -- without building
    anything.

    Only the four shape axes are read, so the presence plan can measure a
    figure before it has chosen a haircut.

    ``height`` returns exactly what it returned before the v2 redesign, to
    the last bit: it reaches the published plan, buckets
    :func:`silhouette_signature`, and drives every Phase 19 walking speed and
    route length, so moving it would reshuffle who stands where and how fast
    they walk. Every other dimension is the v2 design. The published
    ``shoulder_width``, ``head_height`` and ``hip_width`` change with it --
    they are measurements a plan may display, and the precondition audit
    proved nothing derives a position or a route from them.

    The waist is pinched BY CONSTRUCTION rather than by tuning: it is a
    fraction of whichever of the hip and the chest is already narrower, and
    that fraction is clamped to [0.62, 0.92] whatever the build and
    presentation multiply out to -- the largest product the vocabulary can
    produce is 0.80 * 1.06 * 1.04 = 0.882. Under one, for every combination,
    with no search and nothing to re-tune when a build is added -- so no
    figure can ever be built barrel-sided.
    """
    age = _require(identity["age_presentation"], AGE_PRESENTATIONS, "age presentation")
    stature = _require(identity["stature"], STATURES, "stature")
    build = _require(identity["build"], BUILDS, "build")
    presentation = _require(identity["presentation"], PRESENTATIONS, "presentation")
    base = PROPORTIONS[age]
    shape = BUILD_SHAPE[build]
    bias = PRESENTATION_SHAPE[presentation]

    height = base["height"] * STATURE_SCALE[stature]
    leg_top = base["leg"] * height
    torso_top = leg_top + base["torso"] * height
    neck_top = torso_top + base["neck"] * height
    head_height = base["head"] * height
    head_width = head_height * base["head_width"]
    shoulder = base["shoulder"] * height * shape["shoulder"] * bias["shoulder"]
    hip = base["hip"] * height * shape["hip"] * bias["hip"]
    limb = base["limb"] * height * shape["limb"]
    chest = shoulder * 0.64
    pinch = min(max(0.80 * shape["waist"] * bias["waist"], 0.62), 0.92)
    waist = min(hip, chest) * pinch
    scale = limb / _LIMB_REFERENCE
    return {
        "height": height,
        "leg_top": leg_top,
        "torso_top": torso_top,
        "neck_top": neck_top,
        "head_height": head_height,
        "head_width": head_width,
        "head_depth": head_height * base["head_depth"],
        "shoulder_width": shoulder,
        "hip_width": hip,
        "waist_width": waist,
        "torso_depth": base["depth"] * height * shape["depth"],
        "limb": limb,
        "leg_thickness": 2.0 * LEG_LOFT[0][1] * scale,
        "arm_thickness": 2.0 * ARM_LOFT[0][1] * scale,
        "arm_length": (base["upper_arm"] + base["forearm"]) * height,
        "upper_arm_length": base["upper_arm"] * height,
        "forearm_length": base["forearm"] * height,
        "hand_length": base["hand"] * height,
        "lean": base["lean"] * height,
        "waist_taper": shape["waist"] * bias["waist"],
        "torso_chest_width": chest,
        "torso_shoulder_width": shoulder * 0.56,
        "torso_waist_width": waist,
        "neck_width": head_width * 0.42,
        "foot_length": height * 0.130,
        "foot_height": height * 0.036,
        "foot_width": min(height * 0.049 * shape["limb"], height * 0.055),
    }


# ---------------------------------------------------------------------------
# The primitive layer: rings, lofts and hulls
# ---------------------------------------------------------------------------


def _ring_trig(sides: int, phase: float) -> list[tuple[float, float]]:
    """The cosines and sines of one ring's facets, mirrored rather than resampled.

    ``sin`` of two angles that ought to be equal and opposite is not exactly
    equal and opposite in floating point, and the v2 contract demands
    bit-exact left-right symmetry: an idle body must be its own mirror image,
    and a left eye must stand exactly as far forward as the right one.
    Computing HALF the ring and negating makes symmetry a property of
    construction instead of a hope about rounding. The mirror partner of
    facet ``k`` is the facet whose angle is ``-angle(k)``, which exists for
    the two phases this kit uses (0 and half a facet); a facet on the
    centreline gets its lateral term forced to exactly 0.0.
    """
    trig: list[tuple[float, float] | None] = [None] * sides
    for index in range(sides):
        if trig[index] is not None:
            continue
        partner = (sides - index) % sides if phase == 0.0 else sides - 1 - index
        angle = phase + 2.0 * math.pi * index / sides
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        if partner == index:
            sin_a = 0.0
        trig[index] = (cos_a, sin_a)
        trig[partner] = (cos_a, -sin_a)
    return [entry for entry in trig if entry is not None]


def _ring(
    sides: int,
    half_width: float,
    half_depth: float,
    center: tuple[float, float, float],
    *,
    phase: float = 0.0,
    front: float = 1.0,
    back: float = 1.0,
) -> tuple[tuple[float, float, float], ...]:
    """One closed horizontal cross-section, counter-clockwise seen from above.

    ``half_width`` is the half-extent across the body (Y, the left-right axis)
    and ``half_depth`` the half-extent along the facing axis (X). They differ
    for every real body part -- a torso is far wider than it is deep -- which
    is precisely what a box could not express.

    ``front`` and ``back`` reach the section unevenly. A head is flatter at
    the face and fuller at the occiput, and that asymmetry is what lets a
    viewer tell which way a head is turned even in silhouette.

    The trigonometry comes from :func:`_ring_trig`, which mirrors rather than
    resamples, so a ring is exactly symmetric left to right.
    """
    points = []
    for cos_a, sin_a in _ring_trig(sides, phase):
        reach = front if cos_a >= 0.0 else back
        points.append(
            (
                center[0] + half_depth * cos_a * reach,
                center[1] + half_width * sin_a,
                center[2],
            )
        )
    return tuple(points)


def _primitive(
    name: str,
    kind: str,
    material: int,
    vertices: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
) -> dict:
    """One named lump of geometry, ready for the Blender builder."""
    if kind not in PRIMITIVE_KINDS:
        raise FigureKitError(f"unknown primitive kind {kind!r}")
    return {
        "name": name,
        "kind": kind,
        "material": material,
        "vertices": tuple(vertices),
        "faces": tuple(faces),
    }


def _loft(
    name: str,
    kind: str,
    material: int,
    rings: list[tuple[tuple[float, float, float], ...]],
    *,
    start_pole: tuple[float, float, float] | None = None,
    end_pole: tuple[float, float, float] | None = None,
    start_cap: bool = True,
    end_cap: bool = True,
) -> dict:
    """Skin a stack of rings into one faceted solid.

    Consecutive rings are joined band by band; each end is closed with a flat
    n-gon, closed with a triangle fan when a pole is given, or LEFT OPEN when
    its cap flag is false. The fan is what gives a head a crown and a chin
    instead of a flat lid. The open end is new in v2 and exists for the chain
    contract: a limb member whose end ring is a SEAM -- an elbow met by a
    forearm, a wrist met by a hand -- must not hide a cap inside the joint,
    so caps are spent only on free ends a viewer could actually see into.
    """
    sides = len(rings[0])
    vertices: list[tuple[float, float, float]] = []
    for ring in rings:
        if len(ring) != sides:
            raise FigureKitError(f"{name} mixes ring widths {sides} and {len(ring)}")
        vertices.extend(ring)
    faces: list[tuple[int, ...]] = []
    for band in range(len(rings) - 1):
        low, high = band * sides, (band + 1) * sides
        for index in range(sides):
            following = (index + 1) % sides
            faces.append((low + index, low + following, high + following, high + index))
    if start_pole is not None:
        pole = len(vertices)
        vertices.append(start_pole)
        for index in range(sides):
            faces.append((pole, (index + 1) % sides, index))
    elif start_cap:
        faces.append(tuple(range(sides - 1, -1, -1)))
    top = (len(rings) - 1) * sides
    if end_pole is not None:
        pole = len(vertices)
        vertices.append(end_pole)
        for index in range(sides):
            faces.append((pole, top + index, top + (index + 1) % sides))
    elif end_cap:
        faces.append(tuple(range(top, top + sides)))
    return _primitive(name, kind, material, vertices, faces)


def triangle_count(primitive: dict) -> int:
    """How many triangles one primitive costs once triangulated."""
    return sum(len(face) - 2 for face in primitive["faces"])


def primitive_bounds(primitive: dict) -> dict:
    """The axis-aligned extent of one primitive, measured from its vertices.

    Measured, never declared. Every geometric contract in the test suites is
    computed through this function, so a primitive cannot pass by describing
    itself correctly while being built wrong.
    """
    xs = [vertex[0] for vertex in primitive["vertices"]]
    ys = [vertex[1] for vertex in primitive["vertices"]]
    zs = [vertex[2] for vertex in primitive["vertices"]]
    return {"x": (min(xs), max(xs)), "y": (min(ys), max(ys)), "z": (min(zs), max(zs))}


def ring_sections(primitive: dict, sides: int) -> list[dict]:
    """Recover the cross-sections of a lofted primitive from its vertices.

    Walks the vertex list in ring-sized strides and reports what each ring
    actually measures: its height, its centre and its mean radius. Poles and
    any trailing vertices are ignored.

    This is how a limb proves it tapers. Nothing is read back from a table of
    intended radii; the numbers come from the coordinates that will be handed
    to Blender.
    """
    vertices = primitive["vertices"]
    sections: list[dict] = []
    for start in range(0, (len(vertices) // sides) * sides, sides):
        ring = vertices[start : start + sides]
        center_x = math.fsum(vertex[0] for vertex in ring) / sides
        center_y = math.fsum(vertex[1] for vertex in ring) / sides
        radius = (
            math.fsum(math.hypot(vertex[0] - center_x, vertex[1] - center_y) for vertex in ring)
            / sides
        )
        sections.append(
            {
                "z": ring[0][2],
                "center": (center_x, center_y),
                "radius": radius,
                "width": max(v[1] for v in ring) - min(v[1] for v in ring),
                "depth": max(v[0] for v in ring) - min(v[0] for v in ring),
            }
        )
    return sections


def section_at_height(primitive: dict, sides: int, height: float) -> list[tuple] | None:
    """One lofted primitive's cross-section at a height, from its own vertices.

    Interpolates between the two rings that bracket the height, and between the
    last ring and a pole if the solid closes with one. Returns ``None`` above or
    below the primitive.

    Exists so a test can ask a containment question -- is the skull inside the
    hair? -- against the geometry that will be built, rather than against the
    bounding boxes that let a bare-skull defect through once already.
    """
    vertices = primitive["vertices"]
    rings = [
        vertices[index * sides : (index + 1) * sides] for index in range(len(vertices) // sides)
    ]
    pole = vertices[-1] if len(vertices) % sides else None
    if not rings:
        return None
    levels = [ring[0][2] for ring in rings]
    for index in range(len(rings) - 1):
        low, high = levels[index], levels[index + 1]
        if min(low, high) - 1.0e-9 <= height <= max(low, high) + 1.0e-9:
            blend = 0.0 if high == low else (height - low) / (high - low)
            return [
                tuple(
                    rings[index][corner][axis]
                    + (rings[index + 1][corner][axis] - rings[index][corner][axis]) * blend
                    for axis in range(3)
                )
                for corner in range(sides)
            ]
    if pole is not None and levels[-1] <= height <= pole[2]:
        span = pole[2] - levels[-1]
        blend = 0.0 if span <= 0.0 else (height - levels[-1]) / span
        return [
            tuple(
                rings[-1][corner][axis] + (pole[axis] - rings[-1][corner][axis]) * blend
                for axis in range(3)
            )
            for corner in range(sides)
        ]
    return None


def encloses(section: list[tuple], point: tuple[float, float]) -> bool:
    """Whether one cross-section contains a point, in the horizontal plane."""
    inside = False
    count = len(section)
    for index in range(count):
        near, far = section[index], section[(index + 1) % count]
        if (near[1] > point[1]) != (far[1] > point[1]):
            crossing = near[0] + (point[1] - near[1]) * (far[0] - near[0]) / (far[1] - near[1])
            if point[0] < crossing:
                inside = not inside
    return inside


def face_normals(primitive: dict) -> list[tuple[float, float, float]]:
    """One unit normal per face, computed from the emitted vertices.

    Used to prove a head is not a box: a cuboid has six distinct normals and
    a faceted skull has many more, and neither claim depends on what the
    primitive calls itself.
    """
    normals: list[tuple[float, float, float]] = []
    for face in primitive["faces"]:
        origin = primitive["vertices"][face[0]]
        first = primitive["vertices"][face[1]]
        second = primitive["vertices"][face[-1]]
        edge_a = (first[0] - origin[0], first[1] - origin[1], first[2] - origin[2])
        edge_b = (second[0] - origin[0], second[1] - origin[1], second[2] - origin[2])
        cross = (
            edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
            edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
            edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
        )
        length = math.sqrt(cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2)
        if length > 1.0e-12:
            normals.append((cross[0] / length, cross[1] / length, cross[2] / length))
    return normals


# ---------------------------------------------------------------------------
# The head coordinate contract
# ---------------------------------------------------------------------------

FACE_FORWARD_AXIS = "+X"
"""THE authoritative face-forward convention, and the only one.

Every head is assembled in HEAD-LOCAL space::

    +X   the direction the face looks
    +Y   the head's left, and therefore the eye separation axis
    +Z   up

The head-local origin sits at the centre of the head in plan and at the head's
BASE in height. Features are authored there and the whole assembly is then
carried into body space by a single rigid transform -- a rotation about the
head's own axis followed by a translation. Nothing infers a facing direction
from a pose, a world rotation, or the orientation a primitive happened to be
emitted with.

This exists because the original kit did infer it, twice over, and got it
wrong both times: the eye and brow plates were authored BEHIND the head's front
face and so were sealed inside the skull, and the head turn was handed to each
feature as its own spin instead of orbiting the features around the head, so a
turned head kept its face pointing where the body pointed.
"""

HEAD_PROFILE = (
    (0.000, 0.00, 0.00, 0.036),
    (0.095, 0.50, 0.46, 0.030),
    (0.250, 0.76, 0.72, 0.016),
    (0.460, 0.96, 0.94, 0.000),
    (0.660, 1.00, 1.00, -0.006),
    (0.850, 0.92, 0.94, -0.020),
    (1.000, 0.00, 0.00, -0.048),
)
"""The skull's silhouette, as ``(height fraction, width, depth, forward shift)``.

Widths and depths are fractions of ``head_width`` and ``head_depth``; the
forward shift is a fraction of ``head_depth``. The first and last entries have
zero radius: they are the CHIN POLE and the CROWN POLE, the two points that
turn a barrel into a head.

Read from the bottom: a chin that comes to a point well forward of the axis,
a jaw ring, a mouth ring, the cheekbone, the widest section at the temple and
brow, a forehead that pulls back, and a crown that closes over behind the
axis. Five rings and two poles at twelve facets is the v2 spend, up from four
rings at eight: the extra ring and facets are what separate a skull with a
mouth line and a cheek from the faceted nut the render review called out.

This table is the NEUTRAL face. :func:`head_frame` folds the identity's
``jaw`` and ``chin`` factors into a per-figure copy, so every consumer of the
skull -- the loft, the surface probe, the hair -- reads one adjusted profile
and none can disagree about where the face is.
"""

HEAD_FRONT_REACH = 0.90
HEAD_BACK_REACH = 1.12
"""A face is flatter than a sphere and the back of a skull is fuller.

Without this the head is rotationally symmetric and a viewer cannot tell a
turned head from a straight one until they find the eyes. With it, the
silhouette alone carries the heading. v2 widens the split -- 0.90 against
1.12 -- because at twelve facets the flatter face reads as a face plane
rather than as a chamfer.
"""

EYE_PROUD = 0.0032
BROW_PROUD = 0.0034
NOSE_PROUD = 0.0125
MOUTH_PROUD = 0.0040
"""How far each feature stands PROUD of the head's curved surface, in metres.

THESE ARE A THIRD OF WHAT THEY WERE, and none of the reduction was won by
relaxing anything. Every one of them was sized to beat a chord sag -- a
plate spanning a ridge dips below the surface it crosses, so the clearance
had to exceed the dip at every sample -- and the sag is now gone at the
source: the eyes and the brow are laid BETWEEN the skull's own facet ridges
(see :func:`facet_ridges`) and each column follows the head's lean. With no
chord to beat, what is left is the proudness a viewer is meant to read, and
the art review's verdict on the previous figures is the reason it matters:
eyes as "protruding slabs" that "stick out PAST THE SILHOUETTE of the face",
a nose that "in profile detaches from the head outline entirely".

A nose still leads, and has to: it is the one feature whose whole job is to
break a profile. It keeps four times the eyes' projection and remains the
most forward thing on a face, which ``test_face_contract`` asserts.

The mouth carries the smallest value, deliberately: it sits on the flat
front facet where a plate has no chord sag to beat, and the render review
found the earlier, fatter mouth reading as a beak in pure profile. Five
millimetres keeps it a lip line -- proud enough to read, measured well clear
of the 1.5mm clearance floor, and always behind the nose.

Every one is positive, and that is the whole point. A feature is placed by its
front surface rather than by its centre, so it can never be authored inside the
head no matter how the head's depth changes.

The values are larger than a flat-faced head needed. A plate spanning a curved
surface is a chord across it, and a chord dips below the surface it spans; the
clearance has to beat that sag at every sample point, which
``test_face_contract`` checks by densely sampling the built plate against the
built skull rather than by trusting these numbers.
"""

FACE_LEVELS = {
    "mouth": 0.215,
    "moustache": 0.300,
    "nose": 0.440,
    "eye": 0.600,
    "brow": 0.725,
}
"""Feature heights as fractions of head height, measured from the head base.

Ordered and non-overlapping by construction: mouth, moustache, nose, eyes,
brow, and then the hairline above all of them. The structural contract that
the nose sits below the eyes and above the mouth is this table, and the tests
re-derive it from the built geometry rather than reading it back from here.

v2 pulled the eyes DOWN and the brow UP. The render review found that the
brow plate and the eye plates, both dark and nearly touching, fused into
wraparound sunglasses on every figure; the fix is not a colour, it is a band
of bare complexion between them, and it is enforced as geometry -- see
:data:`BROW_EYE_GAP`.
"""

BROW_EYE_GAP = 0.06
"""The minimum clear complexion between the brow's underside and the eyes'
tops, as a fraction of head height.

The sunglasses defect, stated as a number. The brow plate spans its level
plus or minus 0.022 and the eyes theirs plus or minus 0.038, so the built gap
is (0.735 - 0.022) - (0.600 + 0.038) = 0.075 of head height -- a quarter over
the floor, and the self-verification measures it from the emitted plates
rather than from this arithmetic. The brow also had to come DOWN from 0.750
to leave a forehead: with the hairline at 0.800 a higher brow bar sat
directly under the hair edge and the two dark bands read as a headband. The
eyes are also narrower than the brow and in a different material family, so
nothing above the cheekbone reads as one dark band any more.
"""

HAIRLINE = 0.820
"""Where a hair variant's covering shell meets the FACE, at the front.

Below this a shell would close on the brow, and shortly after that the eyes.
It rose from 0.780 with the v3 fix round to open a real forehead: the brow
bar tops out at 0.757, so there is a clear 0.043 of head height of complexion
between the two -- about eleven millimetres on an adult -- where the two dark
bands previously touched and read as a headband.

This is the FRONT of the hairline and only the front. A skirt drops the edge
at the temples and lower still down the occiput (see :func:`_hair_shell`), so
no haircut ends in the straight horizontal line that made every one of them
read as a cap. A cap's shell starts a centimetre lower, because a cap sits
down over the skull rather than growing out of it.

Hair BEHIND the head may fall as far as it likes; the rule the tests enforce
is the one that matters: no hair geometry may stand in front of a brow, an
eye or a nose, checked as real occlusion over every combination rather than
as a height threshold."""

EAR_HAIR = ("bald", "short", "tied", "medium")
"""The hair variants whose figures grow EARS.

Ears are two eight-triangle complexion wedges, and they exist because a bald
or short-haired skull without them reads as an egg. They are only built when
the haircut leaves them visible: long hair and the high-volume mass cover
them, and a cap's shell sits over them, so building them there would spend
triangles inside other geometry.
"""


def head_frame(size: dict, head_turn: float, face: str = "a") -> dict:
    """The one authoritative head coordinate system for one figure.

    v2 gives the frame the identity's FACE as well: the ``jaw`` and ``chin``
    factors of :data:`FACE_SHAPE` are folded into a per-figure copy of
    :data:`HEAD_PROFILE`, carried on the frame as ``profile``. Every consumer
    of the skull's shape -- the loft, :func:`head_surface_x`, the hair shells
    -- reads that one adjusted table, so a square-jawed skull and the plates
    conforming to it can never be built from two different opinions of the
    same head.
    """
    shape = FACE_SHAPE[_require(face, FACE_VARIANTS, "face variant")]
    profile = []
    for index, (level, width, depth, shift) in enumerate(HEAD_PROFILE):
        if index == 0:
            profile.append((level, width, depth, shift * shape["chin"]))
        elif index == 1:
            profile.append((level, width * shape["jaw"], depth, shift))
        else:
            profile.append((level, width, depth, shift))
    half_depth = size["head_depth"] / 2.0
    front = max(
        shift * size["head_depth"] + depth * half_depth * HEAD_FRONT_REACH
        for _level, _width, depth, shift in profile
    )
    return {
        "origin": (size["lean"], 0.0, size["neck_top"]),
        "turn": float(head_turn),
        "width": size["head_width"],
        "depth": size["head_depth"],
        "height": size["head_height"],
        "front": front,
        "profile": tuple(profile),
    }


def _profile_at(frame: dict, fraction: float) -> tuple[float, float, float]:
    """The skull profile interpolated to one height: ``(width, depth, shift)``.

    Fractions of the frame's own width and depth, read from the frame's
    ADJUSTED profile -- which is precisely what the lofted band between two
    rings does, because ring radii and forward shift both vary linearly along
    a band.
    """
    profile = frame.get("profile", HEAD_PROFILE)
    fraction = min(max(fraction, 0.0), 1.0)
    lower = profile[0]
    upper = profile[-1]
    for index in range(len(profile) - 1):
        if profile[index][0] <= fraction <= profile[index + 1][0]:
            lower, upper = profile[index], profile[index + 1]
            break
    span = upper[0] - lower[0]
    blend = 0.0 if span <= 0.0 else (fraction - lower[0]) / span
    return (
        lower[1] + (upper[1] - lower[1]) * blend,
        lower[2] + (upper[2] - lower[2]) * blend,
        lower[3] + (upper[3] - lower[3]) * blend,
    )


def head_surface_x(frame: dict, height_fraction: float, lateral: float) -> float:
    """Where the skull's front surface actually is, at one height and offset.

    THE function the whole face contract rests on. A faceted skull has no
    face plane: the surface falls away towards the temples, towards the chin
    and towards the crown, and a feature placed against a single number would
    be buried at one end of its own width and floating at the other.

    So this reproduces the built polygon exactly. It interpolates the frame's
    adjusted profile to the requested height, rebuilds that cross-section,
    and intersects it with the requested lateral offset. The answer is a
    point ON the mesh, not an approximation of it.

    A lateral offset beyond the skull's width at that height is CLAMPED to the
    silhouette edge, which is the nearest real surface. An earlier version
    returned the head's centre axis instead, which reports a surface far behind
    the true one: a caller sampling near the chin, where the skull narrows to a
    point, would then place a feature deep inside it and read a comfortable
    clearance while doing so.
    """
    width_f, depth_f, shift_f = _profile_at(frame, height_fraction)
    width = width_f * frame["width"] / 2.0
    depth = depth_f * frame["depth"] / 2.0
    shift = shift_f * frame["depth"]
    section = _ring(
        HEAD_SIDES,
        width,
        depth,
        (shift, 0.0, 0.0),
        phase=_facet_phase(HEAD_SIDES),
        front=HEAD_FRONT_REACH,
        back=HEAD_BACK_REACH,
    )
    reach = max(point[1] for point in section)
    clamped = min(max(lateral, -reach), reach)
    best: float | None = None
    for index in range(HEAD_SIDES):
        start = section[index]
        end = section[(index + 1) % HEAD_SIDES]
        if start[1] == end[1]:
            continue
        if (start[1] - clamped) * (end[1] - clamped) > 0.0:
            continue
        along = (clamped - start[1]) / (end[1] - start[1])
        crossing = start[0] + along * (end[0] - start[0])
        best = crossing if best is None else max(best, crossing)
    return shift if best is None else best


def facet_ridges(frame: dict, height_fraction: float) -> tuple[float, ...]:
    """Where the skull's own facet ridges fall, as lateral offsets at one height.

    A twelve-sided skull has no cheek: it has flat facets meeting at ridges,
    and every face plate that spans a ridge is a chord across it. The strip
    sampling in :func:`_conforming_plate` exists to keep such a plate from
    cutting through the ridge, and it does -- by standing the whole plate off
    the surface far enough to clear it. On the eyes, whose two columns
    straddled the first ridge, that lifted the outer end EIGHTEEN millimetres
    clear of the cheek it was supposed to be lying on, which is a slab on a
    stalk and is what the art review called an eye sticking out past the
    silhouette of the face.

    A plate laid BETWEEN two ridges spans one flat facet, so its front is
    exactly parallel to the surface under it: no chord, no sag, and no lift
    to pay for either. That is what these offsets are for. They are measured
    from the same adjusted profile the skull is lofted from, so a plate
    placed against them stays on its facet for every face variant and every
    age band rather than for the one head the numbers were tuned on.
    """
    width_f, _depth_f, _shift = _profile_at(frame, height_fraction)
    half = width_f * frame["width"] / 2.0
    return tuple(
        sorted(
            {
                abs(half * sin)
                for cos, sin in _ring_trig(HEAD_SIDES, _facet_phase(HEAD_SIDES))
                if cos > 0.0
            }
        )
    )


def _faceted_head(frame: dict) -> dict:
    """The skull: twelve facets around, five rings and two poles tall."""
    half_width = frame["width"] / 2.0
    half_depth = frame["depth"] / 2.0
    base = frame["origin"][2]
    height = frame["height"]
    profile = frame.get("profile", HEAD_PROFILE)
    rings = [
        _ring(
            HEAD_SIDES,
            width * half_width,
            depth * half_depth,
            (shift * frame["depth"], 0.0, base + level * height),
            phase=_facet_phase(HEAD_SIDES),
            front=HEAD_FRONT_REACH,
            back=HEAD_BACK_REACH,
        )
        for level, width, depth, shift in profile[1:-1]
    ]
    chin = profile[0]
    crown = profile[-1]
    return _loft(
        "skull",
        "faceted_head",
        COMPLEXION,
        rings,
        start_pole=(chin[3] * frame["depth"], 0.0, base + chin[0] * height),
        end_pole=(crown[3] * frame["depth"], 0.0, base + crown[0] * height),
    )


def _conforming_plate(
    name: str,
    frame: dict,
    *,
    level_low: float,
    level_high: float,
    lateral_center: float,
    half_span: float,
    proud_low: float,
    proud_high: float,
    thickness: float,
    columns: int,
    material: int,
    laterals: tuple[float, ...] | None = None,
    cant: float = 0.0,
    conform: float = 1.0,
) -> dict:
    """One face feature, moulded onto whatever curve the skull presents.

    Each column is pushed out to the skull's own surface and then stood
    ``proud`` of it, so a feature follows the cheek instead of hovering over it.

    A column is placed against the FURTHEST FORWARD point of the skull in the
    strip of face it is responsible for -- half way to each neighbour -- not
    against the single point directly beneath it. That distinction is the whole
    correctness of this function, and sampling the point alone was wrong:

    the skull is a POLYGON, so its surface has ridges where two facets meet. A
    plate whose columns straddle such a ridge is a chord across it, and a chord
    across a ridge passes THROUGH it. Measured on the real ruled surface, the
    point-sampled version buried the eyes 0.9mm, the brow 2.9mm and the beard
    10.6mm into the skull -- reintroducing, in a subtler form, exactly the
    defect the previous correction existed to remove. Covering the strip lifts
    every column clear of any ridge it spans, and costs no extra geometry.

    ``proud_low`` and ``proud_high`` differ only for the nose and the mouth,
    which lean out from their upper edge and would otherwise be slabs.
    """
    base = frame["origin"][2]
    height = frame["height"]
    low_z = base + level_low * height
    high_z = base + level_high * height
    # Laterals and strip samples are authored as CENTRE plus SIGNED OFFSET,
    # never as an accumulated sweep. Negating a float is exact and rounding is
    # sign-symmetric, so a plate and its mirror sample the skull at exactly
    # opposite laterals -- which is what keeps a left eye and a right eye
    # bit-for-bit mirrored instead of merely close. A caller may hand in its
    # own column laterals -- the brow does, to sit a column exactly on a
    # facet ridge -- and they obey the same rule.
    if laterals is None:
        laterals = [
            lateral_center + half_span * (2.0 * column / (columns - 1) - 1.0)
            for column in range(columns)
        ]
    else:
        laterals = [lateral_center + offset for offset in laterals]
        columns = len(laterals)
    inner_reach = min(abs(entry) for entry in laterals)
    outer_reach = max(max(abs(entry) for entry in laterals) - inner_reach, 1.0e-9)
    vertices: list[tuple[float, float, float]] = []
    for column, lateral in enumerate(laterals):
        near = lateral if column == 0 else (laterals[column - 1] + lateral) / 2.0
        far = lateral if column == columns - 1 else (lateral + laterals[column + 1]) / 2.0
        # The strip is always centred on the COLUMN and shrinks towards it,
        # never towards the gap: a strip that walked away from its own column
        # stopped answering for the surface directly beneath it.
        low = lateral + (near - lateral) * conform
        high = lateral + (far - lateral) * conform
        middle = (low + high) / 2.0
        # HOW MUCH OF THE STRIP a column answers for. A plate that spans a
        # facet ridge must cover the whole strip between its neighbours or
        # its chord cuts the ridge; a plate laid WITHIN one facet crosses no
        # ridge, and sampling the whole strip there only lifts its outer end
        # off the cheek for nothing -- twelve millimetres of nothing, on an
        # eye. So the plates that own a facet ask for a narrow strip.
        reach = (high - low) / 2.0
        # A canted plate drops its OUTER columns. A brow that runs dead level
        # is a horizontal bar, and on a grey-haired figure a horizontal bar in
        # the hair material stacks with the hairline above it into parallel
        # stripes across the forehead. Angling it makes it read as a pair of
        # eyebrows instead, and depends only on |lateral| so it stays mirrored.
        #
        # The cant is applied to the SAMPLED LEVELS as well as to the emitted
        # heights. A column that has been dropped sits over a different part
        # of the skull, and below the brow the skull comes forward towards the
        # cheek: sampling where the column WOULD have been and building it
        # where it now IS puts the outer end of the plate behind the surface
        # it is supposed to stand proud of.
        # The cant is measured OUTWARD FROM THE FACE, not outward from the
        # plate's own middle. Referenced to the middle it dropped both ends
        # and left the centre column standing, which is a chevron rather than
        # an eyebrow -- and a chevron over a smoothly curving skull has a
        # ruled surface between its columns that dips a millimetre inside the
        # head, which is how a brow with three millimetres of clearance
        # measured as buried. It still depends only on |lateral|, so it stays
        # exactly mirrored.
        fall = cant * (abs(lateral) - inner_reach) / outer_reach

        # A CANTED plate is sampled over its WHOLE cant, not over its own
        # column's drop. Its columns sit at different heights, so the ruled
        # surface between two of them passes over skull the columns never
        # stood on -- and on a brow, whose outer end drops four millimetres,
        # that is where a tightly fitted plate goes a millimetre under.
        falls = (fall,) if cant == 0.0 else (0.0, cant * 0.5, cant)

        def strip(
            level: float,
            falls: tuple[float, ...] = falls,
            middle: float = middle,
            reach: float = reach,
        ):
            return max(
                head_surface_x(frame, level - drop, middle + reach * ((step - 2) / 2.0))
                for drop in falls
                for step in range(5)
            )

        # THE COLUMN FOLLOWS THE HEAD'S LEAN, top to bottom. Taking one
        # surface for the whole column -- the MAXIMUM over its levels, which
        # is what this did -- builds a vertical slab against a face that is
        # not vertical, and the end that leans away is left standing in mid
        # air. On the nose, whose plate spans a fifth of the head's height
        # across the point where the face starts falling back towards the
        # mouth, that was nine millimetres of unasked-for projection on top
        # of the designed sixteen: twenty-five in total, which in profile is
        # the "juts out and detaches from the head outline entirely" the art
        # review reported. Sampling each end against its OWN level costs
        # nothing and puts the plate back on the face.
        lead = min(proud_low, proud_high)
        low_surface, high_surface = strip(level_low), strip(level_high)
        span = (low_surface + proud_low, high_surface + proud_high)
        # What the two-ended fit cannot see is a bulge BETWEEN the ends -- a
        # cheekbone under a nose -- so the straight run is lifted clear of it
        # rather than being allowed to cut through. This is the guarantee the
        # old maximum bought by brute force, kept, at the cost of the sag
        # alone instead of the whole lean.
        rise = 0.0
        for step in range(1, 4):
            blend = step / 4.0
            level = level_low + (level_high - level_low) * blend
            chord = span[0] + (span[1] - span[0]) * blend
            rise = max(rise, strip(level) + lead - chord)
        front_low = span[0] + rise
        front_high = span[1] + rise
        back = min(low_surface, high_surface) + lead - thickness
        drop = fall * height
        vertices.extend(
            [
                (front_low, lateral, low_z - drop),
                (front_high, lateral, high_z - drop),
                (back, lateral, low_z - drop),
                (back, lateral, high_z - drop),
            ]
        )
    faces: list[tuple[int, ...]] = []
    for column in range(columns - 1):
        near, far = column * 4, (column + 1) * 4
        faces.append((near + 0, far + 0, far + 1, near + 1))
        faces.append((near + 2, near + 3, far + 3, far + 2))
        faces.append((near + 1, far + 1, far + 3, near + 3))
        faces.append((near + 0, near + 2, far + 2, far + 0))
    last = (columns - 1) * 4
    faces.append((0, 1, 3, 2))
    faces.append((last + 0, last + 2, last + 3, last + 1))
    plate = _primitive(name, "face_feature", material, vertices, faces)
    # Which vertices are the OUTWARD face, recorded rather than guessed. A
    # plate that conforms to a strongly curved cheek can have its inner column
    # standing further forward than its outer column's BACK, so "the front is
    # whatever is in front of the midpoint" silently selects one column's front
    # and back instead of both columns' fronts -- which aimed the structural
    # ray probe at an eye's inner edge and reported a miss the geometry had not
    # committed.
    plate["front"] = tuple(column * 4 + row for column in range(columns) for row in (0, 1))
    return plate


def _section_front(section: list[tuple], lateral: float) -> float:
    """Where a lofted cross-section's FRONT surface is, at one lateral offset.

    The torso's answer to :func:`head_surface_x`, and it exists for the same
    reason: a hull with eight facets has no chest plane, so anything laid on
    it has to be placed against the polygon rather than against a number. An
    offset past the section's own width is clamped to its edge.
    """
    reach = max(point[1] for point in section)
    clamped = min(max(lateral, -reach), reach)
    best: float | None = None
    count = len(section)
    for index in range(count):
        start, end = section[index], section[(index + 1) % count]
        if start[1] == end[1]:
            continue
        if (start[1] - clamped) * (end[1] - clamped) > 0.0:
            continue
        along = (clamped - start[1]) / (end[1] - start[1])
        crossing = start[0] + along * (end[0] - start[0])
        best = crossing if best is None else max(best, crossing)
    return max(point[0] for point in section) if best is None else best


def _merge_plates(name: str, plates: list[dict]) -> dict:
    """Several conforming plates emitted as one named primitive.

    A feature the contract names is not obliged to be one connected surface.
    Two brows are still ``brow``: the tests ask for the name and measure what
    comes back, which is the whole point of naming features rather than
    counting lumps.

    The merged ``front`` record walks each plate from its OUTER column to its
    INNER one, so the two plates meet inner-to-inner in the middle of the
    list. :func:`plate_clearance` steps through consecutive pairs, so that
    ordering puts its one cross-plate span over the narrow gap between the
    inner ends -- the flattest, most forward part of the face -- rather than
    across the entire head.
    """
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    front: list[int] = []
    for position, plate in enumerate(plates):
        offset = len(vertices)
        vertices.extend(plate["vertices"])
        faces.extend(tuple(index + offset for index in face) for face in plate["faces"])
        columns = [
            (plate["front"][index] + offset, plate["front"][index + 1] + offset)
            for index in range(0, len(plate["front"]), 2)
        ]
        # The FIRST plate is walked outward-in and every later one inward-out,
        # so consecutive plates meet INNER to INNER. Testing each plate the
        # same way -- which is what this did -- put every plate outer-first,
        # so the one cross-plate span ran from one brow's inner end to the
        # other brow's TEMPLE, straight across the face. Nothing measured it
        # while the plates stood nine millimetres proud; at three the span
        # read as three quarters of a millimetre of brow buried in a forehead.
        outer_first = abs(vertices[columns[0][0]][1]) > abs(vertices[columns[-1][0]][1])
        if outer_first != (position == 0):
            columns.reverse()
        front.extend(index for column in columns for index in column)
    merged = _primitive(name, "face_feature", plates[0]["material"], vertices, faces)
    merged["front"] = tuple(front)
    return merged


def plate_clearance(frame: dict, primitive: dict, samples: int = 11) -> float:
    """The smallest gap between a face plate and the skull underneath it.

    Walks the plate's REAL front surface: the ruled quad between each pair of
    adjacent columns, sampled in both directions, each sample compared against
    the skull beneath that exact point. A negative result means part of the
    feature is inside the skull -- the defect the Director originally reported
    as "a nose but no eyes".

    The obvious cheaper version of this function is wrong, and shipped wrong
    once: taking the plate's single most-forward vertex and comparing that one
    plane against the skull. A conforming plate is not a plane. Its outer
    columns sit further back than its inner ones by design, so the flattering
    maximum hides the only failure this is looking for -- and the check passed
    while the eyes, the brow and the beard were all measurably buried.

    Falls back to the max-x plane only for primitives that declare no front
    face, which no conforming plate does.
    """
    base = frame["origin"][2]
    indices = primitive.get("front")
    if indices is None:
        bounds = primitive_bounds(primitive)
        front = bounds["x"][1]
        worst = float("inf")
        for column in range(samples):
            span = bounds["y"][1] - bounds["y"][0]
            lateral = bounds["y"][0] + span * column / (samples - 1)
            for row in range(samples):
                rise = bounds["z"][1] - bounds["z"][0]
                level = (bounds["z"][0] + rise * row / (samples - 1) - base) / frame["height"]
                worst = min(worst, front - head_surface_x(frame, level, lateral))
        return worst

    vertices = primitive["vertices"]
    columns = [
        (vertices[indices[index]], vertices[indices[index + 1]])
        for index in range(0, len(indices), 2)
    ]
    worst = float("inf")
    for column in range(len(columns) - 1):
        (near_low, near_high), (far_low, far_high) = columns[column], columns[column + 1]
        for step in range(samples):
            across = step / (samples - 1)
            low = tuple(
                near_low[axis] + (far_low[axis] - near_low[axis]) * across for axis in range(3)
            )
            high = tuple(
                near_high[axis] + (far_high[axis] - near_high[axis]) * across for axis in range(3)
            )
            for rise in range(samples):
                up = rise / (samples - 1)
                point = tuple(low[axis] + (high[axis] - low[axis]) * up for axis in range(3))
                level = (point[2] - base) / frame["height"]
                worst = min(worst, point[0] - head_surface_x(frame, level, point[1]))
    return worst


def _face_features(identity: dict, frame: dict) -> list[dict]:
    """Brow, both eyes, nose and mouth, in head-local space.

    Both eyes, always, mirrored about the facial centreline at equal height and
    equal forward offset. A face is never assembled with one.

    The v2 arrangement is the sunglasses fix. The brow sits higher, thinner
    and in the HAIR material -- it is eyebrows, not eyewear -- the eyes sit
    lower and smaller in accent, and the complexion band between them is at
    least :data:`BROW_EYE_GAP` of head height by construction. The nose keeps
    three columns so its centre column stands as a real septum ridge, and it
    leans from bridge to tip.
    """
    face = _require(identity["face"], FACE_VARIANTS, "face variant")
    shape = FACE_SHAPE[face]
    width = frame["width"]
    features: list[dict] = []

    # TWO brows, with real skin between them. One bar spanning the whole face
    # is a unibrow, and in the pale hair tones an elder wears it read as tape
    # across the forehead. They are emitted as one primitive called ``brow``
    # -- the contract is verified by that name -- holding two disconnected
    # plates, which is a thing a primitive is allowed to be.
    #
    # The gap is sized to stay inside the skull's front FACET. That facet is a
    # single flat plane, so the clearance walk between the two inner columns
    # crosses no ridge and cannot sag: the pair is exactly as proud as the
    # plates themselves. A wider gap would put the bridge of the nose between
    # them and reintroduce the sag this file has now removed twice.
    brow_ridge, brow_out, *_rest = facet_ridges(frame, FACE_LEVELS["brow"])
    brow_span = brow_out - brow_ridge
    brow_columns = (
        brow_ridge * 0.58,
        brow_ridge,
        brow_ridge + brow_span * 0.55 * shape["brow"],
    )
    brow_center = (brow_columns[0] + brow_columns[-1]) / 2.0
    plates = [
        _conforming_plate(
            "brow",
            frame,
            level_low=FACE_LEVELS["brow"] - 0.010,
            level_high=FACE_LEVELS["brow"] + 0.010,
            lateral_center=side * brow_center,
            half_span=(brow_columns[-1] - brow_columns[0]) / 2.0,
            proud_low=BROW_PROUD,
            proud_high=BROW_PROUD,
            thickness=0.016,
            columns=3,
            material=HAIR,
            laterals=tuple(side * (column - brow_center) for column in brow_columns),
            cant=0.016,
            conform=0.30,
        )
        for side in (1.0, -1.0)
    ]
    features.append(_merge_plates("brow", plates))

    # BOTH EYES LIE ON ONE FACET, between the skull's first two ridges, and
    # the identity's eye separation moves them ALONG it rather than across
    # it. The vocabulary's own spread is under four millimetres either way,
    # which is less room than the facet has, so nothing is lost -- and an eye
    # that never crosses a ridge never has to be lifted off the head to clear
    # one.
    eye_ridge, eye_out, *_rest = facet_ridges(frame, FACE_LEVELS["eye"])
    eye_span = eye_out - eye_ridge
    eye_shift = (shape["eye_gap"] - 1.0) * 0.60
    eye_inner = eye_ridge + eye_span * (0.12 + eye_shift)
    eye_outer = eye_ridge + eye_span * (0.86 + eye_shift)
    eye_center = (eye_inner + eye_outer) / 2.0
    for name, side in (("left_eye", 1.0), ("right_eye", -1.0)):
        features.append(
            _conforming_plate(
                name,
                frame,
                level_low=FACE_LEVELS["eye"] - 0.034,
                level_high=FACE_LEVELS["eye"] + 0.034,
                lateral_center=side * eye_center,
                half_span=(eye_outer - eye_inner) / 2.0,
                proud_low=EYE_PROUD,
                proud_high=EYE_PROUD,
                thickness=0.022,
                columns=2,
                material=ACCENT,
                conform=0.25,
            )
        )

    features.append(
        _conforming_plate(
            "nose",
            frame,
            level_low=FACE_LEVELS["nose"] - 0.060,
            level_high=FACE_LEVELS["nose"] + 0.085,
            lateral_center=0.0,
            half_span=width * 0.075 * shape["nose"],
            proud_low=NOSE_PROUD * shape["nose"],
            proud_high=NOSE_PROUD * 0.38,
            thickness=0.024,
            columns=3,
            material=COMPLEXION,
        )
    )

    features.append(
        _conforming_plate(
            "mouth",
            frame,
            level_low=FACE_LEVELS["mouth"] - 0.012,
            level_high=FACE_LEVELS["mouth"] + 0.012,
            lateral_center=0.0,
            half_span=width * 0.085,
            proud_low=MOUTH_PROUD,
            proud_high=MOUTH_PROUD * 0.60,
            thickness=0.014,
            columns=2,
            material=ACCENT,
        )
    )
    return features


def _facial_hair_features(identity: dict, frame: dict) -> list[dict]:
    """An optional beard or moustache, always below the nose."""
    growth = _require(identity["facial_hair"], FACIAL_HAIR, "facial hair")
    if growth == "none":
        return []
    width = frame["width"]
    if growth == "moustache":
        return [
            _conforming_plate(
                "moustache",
                frame,
                level_low=FACE_LEVELS["moustache"] - 0.025,
                level_high=FACE_LEVELS["moustache"] + 0.025,
                lateral_center=0.0,
                half_span=width * 0.185,
                proud_low=MOUTH_PROUD + 0.0060,
                proud_high=MOUTH_PROUD + 0.0060,
                thickness=0.020,
                columns=3,
                material=HAIR,
            )
        ]
    return [
        _conforming_plate(
            "beard",
            frame,
            level_low=0.055,
            level_high=FACE_LEVELS["nose"] - 0.105,
            lateral_center=0.0,
            half_span=width * 0.330,
            proud_low=0.0055,
            proud_high=0.0055,
            thickness=0.030,
            columns=3,
            material=HAIR,
        )
    ]


def _ears(identity: dict, frame: dict) -> list[dict]:
    """Two small complexion wedges, only where the haircut leaves them seen.

    Ten triangles each: an outer face and the four sides that carry it back to
    the skull, with the inner face left open because it is inside the head.
    They span the eye-to-nose band on the side of the head, centred half a
    head width out, which is where the skull's own silhouette carries them.

    THEY USED TO BE BLADES. Six vertices met at a single outer RIDGE, so an
    ear was a wedge thirteen millimetres deep front to back standing eleven
    millimetres out from the skull -- a fin, which is what the art review saw
    "poking through the hair" as a thin spike. An ear is a shallow, rounded
    LOBE, so the outer edge is a face rather than a line and the whole thing
    is two and a half times deeper than it is proud. The extra two triangles
    are the cheapest fix in this file.
    """
    if identity["hair"] not in EAR_HAIR:
        return []
    width, depth, height = frame["width"], frame["depth"], frame["height"]
    base = frame["origin"][2]
    inner, outer = width * 0.44, width * 0.525
    low, high = base + 0.44 * height, base + 0.63 * height
    front, back = 0.005 * depth, -0.205 * depth
    rim_front, rim_back = front - 0.045 * depth, back + 0.055 * depth
    rim_low, rim_high = low + 0.028 * height, high - 0.022 * height
    left_vertices = [
        (front, inner, low),
        (back, inner, low),
        (front, inner, high),
        (back, inner, high),
        (rim_front, outer, rim_low),
        (rim_back, outer, rim_low),
        (rim_front, outer, rim_high),
        (rim_back, outer, rim_high),
    ]
    left_faces = [
        (4, 5, 7, 6),
        (0, 4, 6, 2),
        (1, 3, 7, 5),
        (0, 1, 5, 4),
        (2, 6, 7, 3),
    ]
    right_vertices = [(x, -y, z) for x, y, z in left_vertices]
    right_faces = [tuple(reversed(face)) for face in left_faces]
    return [
        _primitive("left_ear", "face_feature", COMPLEXION, left_vertices, left_faces),
        _primitive("right_ear", "face_feature", COMPLEXION, right_vertices, right_faces),
    ]


def _hair_shell(
    name: str,
    frame: dict,
    lift: float,
    start: float,
    stop: float,
    pad: float = HAIR_LIFT_FLOOR,
    *,
    skirt: tuple[float, float, float] | None = None,
    dome: bool = False,
    guard: tuple[float, float] | None = None,
    extend: tuple[tuple[float, float, float, float, float, float], ...] = (),
) -> list[dict]:
    """A faceted covering that follows the round skull instead of boxing it.

    Built from the SAME profile as the head and pushed out along it, so the
    hair sits on the crown as a shell rather than as a crate balanced on a
    sphere. The lift also keeps every hair face clear of the skull face beneath
    it: coplanar surfaces z-fight, and the original kit rendered its hair as
    speckle for exactly that reason.

    The shell has to CONTAIN the skull, and two things once conspired to stop
    it: a shell that straddled the skull's own profile ring cut inside the
    bulge it was supposed to cover, so a ring is placed at every profile level
    the skull itself has inside the covered span; and a shell with fewer
    facets than the skull passes inside the skull's vertices at the same
    radius, so the shell carries the SAME facet count as the skull -- the
    HAIR_SIDES equals HEAD_SIDES law. Two similar polygons need only a lift
    above one to contain, so 1.028 both covers the skull completely and still
    sits on it like hair.

    Two refinements answer the render review's forage-cap finding, and both
    are OPTIONAL because a cap should still read as a cap:

    ``skirt``
        ``(front, side, back)`` drops, in head-height fractions, for one
        extra edge ring below the hairline whose height VARIES around the
        skull. This is the single most load-bearing shape in the hair system,
        because a flat lower edge is what made every haircut read as
        millinery: a straight horizontal band floating off the temples, a
        second dark band above the brow bar reading as a headband, and a bald
        lower occiput below it. A real hairline dips at the temples and runs
        low down the back of the head, so the edge ring is built vertex by
        vertex -- each facet takes its own level from its own angle and then
        samples the skull profile THERE, so the edge follows the head it is
        cut into instead of slicing through it. A deep enough side drop is
        also all a bob is, which is how a haircut gains a jaw-length fall
        with no second primitive to detach from the first.

        The containment law is untouched. It governs the skull ABOVE
        :data:`HAIRLINE`, every ring from the hairline up is still planar and
        still carries the full lift, and the edge ring only adds coverage
        below. The bottom is left OPEN: it closes against the skull, so a cap
        there would be hidden geometry.
    ``dome``
        one extra ring near the crown, fuller than the skull's own taper --
        the profile sampled lower down, placed higher up -- plus a slightly
        shorter pole overshoot. The top of the shell becomes a rounded mass
        instead of the cone the straight band-to-pole fan produced.
    ``extend``
        rings continuing DOWNWARD from the skirt's own bottom edge, each
        ``(front_dx, back_dx, front_dz, back_dz, front_scale, back_scale)``
        blended smoothly around the head by the facet's cosine. This is how a
        gathered nape and a cap's brim come back after the attached volumes
        were deleted, and the distinction matters: a bun bolted on beside a
        shell reads as a prop, whereas a bun that IS the shell -- continuing
        from its boundary vertices, in the same primitive, with no seam to
        find -- reads as hair that was gathered. Every parameter is a
        function of the cosine alone, so an extension is exactly as
        mirror-symmetric as the shell it grows from.
    """
    half_width = frame["width"] / 2.0
    half_depth = frame["depth"] / 2.0
    base = frame["origin"][2]
    height = frame["height"]
    profile = frame.get("profile", HEAD_PROFILE)
    clear = max(pad, HAIR_LIFT_FLOOR)
    phase = _facet_phase(HAIR_SIDES)
    trig = _ring_trig(HAIR_SIDES, phase)

    def ring_at(levels):
        """One ring whose every facet takes its own level off the profile."""
        points = []
        for (cos_a, sin_a), level in zip(trig, levels, strict=True):
            width, depth, shift = _profile_at(frame, level)
            reach = HEAD_FRONT_REACH if cos_a >= 0.0 else HEAD_BACK_REACH
            points.append(
                (
                    shift * frame["depth"] + (depth * half_depth * lift + clear) * cos_a * reach,
                    (width * half_width * lift + clear) * sin_a,
                    base + level * height,
                )
            )
        return tuple(points)

    plan = [(start, lift, clear)]
    plan.extend((entry[0], lift, clear) for entry in profile if start < entry[0] < stop - 1.0e-9)
    targets = [start] * HAIR_SIDES
    if skirt is not None:
        front_drop, side_drop, back_drop = skirt
        for index, (cos_a, sin_a) in enumerate(trig):
            near = front_drop if cos_a >= 0.0 else back_drop
            level = start - (side_drop + (near - side_drop) * abs(cos_a))
            if guard is not None and cos_a > 0.0 and level < guard[0]:
                width, _depth, _shift = _profile_at(frame, level)
                # Measured on the SKULL, not on the shell. The guard asks
                # whether this facet sits over the brow, and that is a
                # question about the head; reading the lifted shell's own
                # width made a high-volume treatment answer differently
                # from a close one about the same piece of face.
                if abs(width * half_width * sin_a) <= guard[1]:
                    level = guard[0]
            targets[index] = level

    # The CROWN never descends past the eye line; the NAPE carries everything
    # below it. See :data:`NAPE_TOP` for why the split exists at all.
    crown_targets = [max(level, NAPE_TOP) for level in targets]
    rings = []
    span = max(start - level for level in crown_targets)
    if span > 1.0e-9:
        stages = max(2, int(math.ceil(span / SKIRT_STEP)))
        for step in range(stages, 0, -1):
            reach_down = step / stages
            levels = [start - (start - level) * reach_down for level in crown_targets]
            rings.append(ring_at(levels))
    for level, ring_lift, ring_pad in plan:
        width, depth, shift = _profile_at(frame, level)
        rings.append(
            _ring(
                HAIR_SIDES,
                width * half_width * ring_lift + ring_pad,
                depth * half_depth * ring_lift + ring_pad,
                (shift * frame["depth"], 0.0, base + level * height),
                phase=phase,
                front=HEAD_FRONT_REACH,
                back=HEAD_BACK_REACH,
            )
        )
    if dome:
        width, depth, shift = _profile_at(frame, 0.875)
        rings.append(
            _ring(
                HAIR_SIDES,
                width * half_width * lift + clear,
                depth * half_depth * lift + clear,
                (shift * frame["depth"], 0.0, base + 0.935 * height),
                phase=phase,
                front=HEAD_FRONT_REACH,
                back=HEAD_BACK_REACH,
            )
        )
    crown = profile[-1]
    overshoot = 0.004 if dome else 0.006
    shell = _loft(
        name,
        "hair_shell",
        HAIR,
        rings,
        end_pole=(crown[3] * frame["depth"], 0.0, base + stop * height + overshoot),
        start_cap=False,
    )

    # The NAPE: a strip over the back and side facets only, hanging from the
    # crown's own bottom edge. It shares those vertices exactly, so the weld
    # closes the join and no seam survives into the render -- but it is its
    # own primitive, and its own axis-aligned bounds stay behind the temple,
    # which is what keeps a falling haircut from reporting itself in front of
    # an eye once the head turns.
    run = [index for index, (cos_a, _sin) in enumerate(trig) if cos_a <= NAPE_FRONT_LIMIT]
    deep = [index for index in run if targets[index] < NAPE_TOP - 1.0e-9]
    if not deep and not extend:
        return [shell]

    # The nape hangs from the crown's OWN bottom edge, facet by facet -- not
    # from a flat line at NAPE_TOP. Where the crown stops higher than the
    # split level, a flat nape top leaves a slot of bare scalp between them,
    # which is exactly what opened above the ear on the tied cuts.
    nape_targets = [min(targets[index], NAPE_TOP) for index in range(HAIR_SIDES)]
    fall = max(crown_targets[index] - nape_targets[index] for index in run)
    nape_rings = []
    if fall > 1.0e-9:
        stages = max(2, int(math.ceil(fall / SKIRT_STEP)))
        for step in range(stages, 0, -1):
            reach_down = step / stages
            nape_rings.append(
                ring_at(
                    [
                        crown_targets[index]
                        - (crown_targets[index] - nape_targets[index]) * reach_down
                        for index in range(HAIR_SIDES)
                    ]
                )
            )
    nape_rings.append(ring_at(crown_targets))

    grown = []
    base_ring = nape_rings[0]
    for front_dx, back_dx, front_dz, back_dz, front_scale, back_scale in extend:
        centre = math.fsum(v[0] for v in base_ring) / len(base_ring)
        grown_ring = []
        for (cos_a, _sin_a), vertex in zip(trig, base_ring, strict=True):
            # Weighted hard towards the BACK. A fall long enough to reach the
            # shoulders must reach them BEHIND the body: a linear blend drops
            # the side facets almost as far as the rear ones, and at shoulder
            # height the sides are exactly where the torso is, so the hair
            # ended up forty millimetres inside the chest. The quarter power
            # keeps the sides near the nape while the rear runs on down.
            blend = ((cos_a + 1.0) / 2.0) ** 0.25
            shift_x = back_dx + (front_dx - back_dx) * blend
            shift_z = back_dz + (front_dz - back_dz) * blend
            scale = back_scale + (front_scale - back_scale) * blend
            grown_ring.append(
                (
                    centre + (vertex[0] - centre) * scale + shift_x * frame["depth"],
                    vertex[1] * scale,
                    vertex[2] + shift_z * height,
                )
            )
        base_ring = tuple(grown_ring)
        grown.append(base_ring)
    nape_rings = list(reversed(grown)) + nape_rings

    vertices: list[tuple[float, float, float]] = []
    index_of: dict[tuple[int, int], int] = {}
    for row, ring in enumerate(nape_rings):
        for column in run:
            index_of[(row, column)] = len(vertices)
            vertices.append(ring[column])
    faces: list[tuple[int, ...]] = []
    for row in range(len(nape_rings) - 1):
        for position in range(len(run) - 1):
            near, far = run[position], run[position + 1]
            faces.append(
                (
                    index_of[(row, near)],
                    index_of[(row, far)],
                    index_of[(row + 1, far)],
                    index_of[(row + 1, near)],
                )
            )
    return [shell, _primitive(f"{name}_nape", "hair_shell", HAIR, vertices, faces)]


BRIM_STATIONS = (
    (0.00, 0.42, 0.806, 0.762),
    (0.15, 0.41, 0.800, 0.765),
    (0.27, 0.34, 0.791, 0.768),
    (0.36, 0.22, 0.782, 0.770),
)
"""The cap peak's cross-sections: ``(reach, half width, top, bottom)``.

Reach is a fraction of head depth forward of the crown's front surface;
the width is a fraction of head width; top and bottom are head-height
levels. Read along, it is a peak and not a plate: it keeps most of its
width for the first half of its run and then sweeps in to a rounded nose,
it is a centimetre thick at the root and tapers to a lip, and its whole
body droops slightly as it goes -- the top falls faster than the bottom
rises. The version this replaces was one flat quad, 11.7mm tall and 52mm
deep, which the render review correctly called a shelf.

The first station sits BEHIND the crown's own surface, so the peak is
seated inside the shell rather than butted against it and there is no
seam to find at the join.

Every level here is above :data:`FACE_LEVELS`' brow, and far above the
eyes: that is what lets a cap project forward over a face without ever
standing in front of an eye, and it is measured rather than assumed.
"""


def _cap_brim(frame: dict) -> dict:
    """The peak of a cap: a shaped solid seated into the crown's front."""
    width, depth, height = frame["width"], frame["depth"], frame["height"]
    base = frame["origin"][2]
    root = head_surface_x(frame, BRIM_STATIONS[0][2], 0.0) - 0.10 * depth
    vertices: list[tuple[float, float, float]] = []
    for reach, half, top, low in BRIM_STATIONS:
        forward = root + reach * depth
        vertices.extend(
            [
                (forward, half * width, base + top * height),
                (forward, -half * width, base + top * height),
                (forward, -half * width, base + low * height),
                (forward, half * width, base + low * height),
            ]
        )
    faces: list[tuple[int, ...]] = []
    for station in range(len(BRIM_STATIONS) - 1):
        near, far = station * 4, (station + 1) * 4
        faces.append((near + 0, near + 1, far + 1, far + 0))
        faces.append((near + 3, far + 3, far + 2, near + 2))
        faces.append((near + 0, far + 0, far + 3, near + 3))
        faces.append((near + 1, near + 2, far + 2, far + 1))
    last = (len(BRIM_STATIONS) - 1) * 4
    faces.append((0, 3, 2, 1))
    faces.append((last + 0, last + 1, last + 2, last + 3))
    return _primitive("hair_brim", "hair_shell", HAIR, vertices, faces)


def _hair_features(identity: dict, frame: dict) -> list[dict]:
    """The head covering, which must change the silhouette AND spare the face.

    Six variants, each with TWO sub-silhouettes keyed by the face axis (faces
    a and b take the first, c and d the second), for eleven hair treatments
    across the vocabulary at no new axis values. Every treatment obeys the
    render review's two prohibitions: no hair mass that fails to connect
    visually to the head it grew from, and nothing side-attached at ear
    height. Covering shells are authored above :data:`HAIRLINE` at the front,
    so no haircut can descend over a brow, an eye or a nose; back masses fall
    as far as they like, and each one overlaps the skull or the shell it
    hangs from.
    """
    hair = _require(identity["hair"], HAIR_VARIANTS, "hair variant")
    face = _require(identity["face"], FACE_VARIANTS, "face variant")
    if hair == "bald":
        return []
    sub = 0 if face in ("a", "b") else 1
    shape = FACE_SHAPE[face]
    # No hair may come forward of the brow. The guard is the brow's own span
    # with a margin, and it is enforced on the SHELL rather than left to a
    # test: a deep side skirt sweeping past the temple is exactly the shape
    # that reaches in front of an outer eyebrow, and on a wide-browed face it
    # did.
    guard = (FACE_LEVELS["brow"] + 0.030, frame["width"] * 0.200 * shape["brow"] * 1.30)
    # (lift, start, skirt, pad, extension rings)
    #
    # Skirt depth is CAPPED. The drop varies with the facet's cosine, twelve
    # facets means the cosine steps by as much as 0.45 between neighbours, and
    # the resulting vertical step between two columns of one ring was reaching
    # 80mm across a 55mm chord -- a tall thin near-edge-on quad that rendered
    # as a pale blade at the temple, worst on exactly the control plate built
    # to expose it. Length below the ear is bought with an EXTENSION instead,
    # which grows from the hem all the way round and so has no step to make.
    # (lift, start, skirt, pad, nape extension rings)
    #
    # LENGTH LIVES ON THE NAPE, not on the crown. The crown must stay above
    # the eye line or its body-space bounds swallow the far eye on a turned
    # head; the nape hangs off the back of the skull where its own bounds
    # stay behind the temple, so it can fall as far as a haircut needs. That
    # is what makes these eleven treatments read as different lengths rather
    # than as one shell with different numbers: short crops at the nape,
    # medium falls to the jaw, long falls past the shoulder line, tied
    # gathers into a knot, and the cap keeps its band.
    #
    # MASS IS A SECOND AXIS, and length alone does not supply it. Every one of
    # these treatments hangs off a crown of nearly the same radius, so a table
    # that varied only the drop produced four haircuts whose rear extents
    # agreed to within eleven thousandths of a head-depth: read from behind --
    # which is how most of a crowd is read -- eighty people wore one haircut at
    # four lengths. The back reach of the first extension ring is therefore
    # dialled into a deliberate ladder, crop below bob below fall below gather,
    # spanning about six hundredths of a head-depth from end to end. It costs
    # nothing: an extension ring already exists on every treatment that has
    # one, and pushing it back moves vertices rather than adding any.
    treatments = {
        # A CROP STILL HAS A NAPE. Both short treatments used to stop where
        # their skirt stopped, a third of a head-height above the head base,
        # and the rear renders read as a forage cap on a bald man: a pale band
        # a hundred millimetres deep between the hem and the neck, worst on
        # the maximum-contrast control plate. The extension ring that closes
        # it pushes nothing backwards -- ``back_dx`` is zero and the ring
        # tucks in slightly -- because ``short`` is the FLOOR of the rear
        # extent ladder, and a crop that gained mass behind the skull would
        # eat the margin the gather guard lives on.
        ("short", 0): (
            1.036,
            HAIRLINE,
            (0.02, 0.24, 0.46),
            HAIR_LIFT_FLOOR,
            ((0.0, 0.0, -0.05, -0.30, 0.99, 0.94),),
        ),
        ("short", 1): (
            1.042,
            HAIRLINE,
            (0.02, 0.20, 0.44),
            HAIR_LIFT_FLOOR,
            ((0.0, 0.0, -0.04, -0.32, 0.99, 0.93),),
        ),
        ("medium", 0): (
            1.058,
            HAIRLINE,
            (0.02, 0.30, 0.46),
            HAIR_LIFT_FLOOR,
            (
                (0.0, -0.190, -0.10, -0.22, 0.99, 0.99),
                (0.0, -0.020, -0.08, -0.18, 0.98, 0.98),
            ),
        ),
        # The two medium treatments are two BOBS, and they have to be. Sub 1
        # carried a single extension where sub 0 carried two, and the pair
        # measured 18mm and 107mm of bare nape: not one haircut in two styles
        # but a bob standing next to a crop, with nothing in the vocabulary
        # left to read as the difference between the two faces. Sub 1 gets
        # its own second ring, so the difference between them is the SHAPE of
        # the fall rather than the length of it: sub 0 sweeps its mass back
        # and under, a fifth of a head-depth clear of the nape, while sub 1
        # hangs straight down close behind the neck. Two bobs in profile,
        # both ending within a few millimetres of the head base.
        ("medium", 1): (
            1.190,
            HAIRLINE,
            (0.02, 0.26, 0.44),
            HAIR_LIFT_FLOOR,
            (
                (0.0, -0.100, -0.10, -0.24, 0.99, 0.96),
                (0.0, -0.020, -0.08, -0.19, 0.98, 0.94),
            ),
        ),
        ("long", 0): (
            1.096,
            HAIRLINE,
            (0.02, 0.30, 0.48),
            HAIR_LIFT_FLOOR,
            (
                (0.0, -0.170, -0.16, -0.42, 0.99, 1.00),
                (0.0, -0.050, -0.16, -0.42, 0.99, 1.00),
                (0.0, -0.040, -0.14, -0.38, 0.98, 0.99),
            ),
        ),
        ("long", 1): (
            1.255,
            HAIRLINE,
            (0.02, 0.28, 0.46),
            HAIR_LIFT_FLOOR,
            (
                (0.0, -0.162, -0.14, -0.36, 0.99, 1.02),
                (0.0, -0.045, -0.14, -0.36, 0.98, 1.01),
            ),
        ),
        # The bun, in THREE rings, because a knot needs something to be tied
        # out of. Built in two it was a knot and nothing else: the gather sat
        # straight on the crown's hem with 95mm of bare skull under it, which
        # from behind is a bowl balanced on a bald nape and reads as no
        # hairstyle at all. So the first ring now takes the hair DOWN the nape
        # and draws it in -- that is the gathering, and it is the part a
        # viewer reads as tied -- the second swings back and swells into the
        # knot proper, and only the third closes on it. The middle ring is
        # still the one that does not shrink: a gather that narrows all the
        # way down collapses onto the crown it grew from and the whole style
        # measures as a crop, which is the profile the vocabulary once lost.
        ("tied", 0): (
            1.038,
            HAIRLINE,
            (0.02, 0.16, 0.38),
            HAIR_LIFT_FLOOR,
            (
                (0.0, -0.020, -0.06, -0.26, 0.98, 0.92),
                (0.0, -0.170, -0.02, -0.05, 0.98, 1.10),
                (0.0, -0.045, -0.02, -0.10, 0.96, 0.55),
            ),
        ),
        # Sub 1 is the tail rather than the bun: the same gather, let down. It
        # carries the vocabulary's LENGTH promise for this variant, because the
        # guard reads a haircut's reach as the lowest thing it can be, and a
        # bun that sits up on the nape is otherwise indistinguishable in length
        # from the bob beside it.
        ("tied", 1): (
            1.030,
            HAIRLINE,
            (0.02, 0.18, 0.38),
            HAIR_LIFT_FLOOR,
            (
                (0.0, -0.185, -0.09, -0.35, 0.98, 1.00),
                (0.0, -0.050, -0.07, -0.42, 0.96, 0.60),
            ),
        ),
        ("cap", 0): (
            1.052,
            HAIRLINE - 0.010,
            (0.03, 0.24, 0.46),
            0.008,
            ((0.002, -0.030, -0.006, -0.060, 0.99, 1.05),),
        ),
        ("cap", 1): (
            1.056,
            HAIRLINE - 0.014,
            (0.03, 0.22, 0.44),
            0.008,
            ((0.002, -0.030, -0.006, -0.050, 0.99, 1.04),),
        ),
    }
    lift, start, skirt, pad, extend = treatments[(hair, sub)]
    features = list(
        _hair_shell(
            "hair_cap" if hair == "cap" else "hair_crown",
            frame,
            lift,
            start,
            1.0,
            pad=pad,
            skirt=skirt,
            dome=True,
            guard=guard,
            extend=extend,
        )
    )
    if hair == "cap":
        # THE one place this kit builds a second head covering, and it is not
        # the loophole the attached volumes were. A cap is genuinely a two
        # part object -- a crown and a peak -- and a peak projecting forward
        # above the eye band is what a cap IS. It cannot live on the shell:
        # the shell already reaches within two millimetres of the eye plates
        # front to back, and the occlusion contract compares whole-primitive
        # bounds, so any forward projection on that primitive would read as
        # hair in front of an eye. As its own primitive it carries its own
        # bounds, which sit entirely above the eyes, and the guard stays
        # exactly as strong as it was.
        features.append(_cap_brim(frame))
    return features


def head_features(identity: dict, frame: dict) -> list[dict]:
    """Every piece of the head, named, in HEAD-LOCAL space.

    The skull first, then the face, then facial hair, then ears, then hair.
    Named so the contract can be machine-verified by feature rather than by
    counting geometry: a test asks for ``left_eye`` and ``right_eye`` and
    measures them against the skull the kit actually built, instead of
    assuming which lump is which.
    """
    return [
        _faceted_head(frame),
        *_face_features(identity, frame),
        *_facial_hair_features(identity, frame),
        *_ears(identity, frame),
        *_hair_features(identity, frame),
    ]


def place_head_feature(frame: dict, primitive: dict) -> dict:
    """Carry one head-local primitive into body space.

    ONE rigid transform, applied to every vertex: the head-local ``(x, y)`` is
    rotated about the head's own axis by the head turn and offset by the head
    origin. Height is untouched because the turn is about Z.

    Rotating the VERTICES is what makes the contract hold. The original kit
    emitted a box plus a rotation angle and let the builder spin each box
    about its own centre, so a turned head kept its face pointing where the
    body pointed. A rotated vertex has nowhere to hide.
    """
    cos_turn, sin_turn = math.cos(frame["turn"]), math.sin(frame["turn"])
    origin_x, origin_y, _origin_z = frame["origin"]
    return {
        **primitive,
        "vertices": tuple(
            (
                origin_x + x * cos_turn - y * sin_turn,
                origin_y + x * sin_turn + y * cos_turn,
                z,
            )
            for x, y, z in primitive["vertices"]
        ),
    }


# ---------------------------------------------------------------------------
# The body
# ---------------------------------------------------------------------------


def _torso_hull(identity: dict, size: dict) -> dict:
    """One lofted upper body: eight designed cross-sections in a single skin.

    Seat, pelvic crest, waist, chest, clavicle, shoulder yoke, trapezius and
    a neck base, bottom to top. Six of them replaced the first rebuild's four
    because the render review read that hull as a tube with a dent: the seat
    and crest give the hips a real seat, the clavicle keeps the chest from
    running straight into the shoulder line, and the small forward shifts
    thread an S-curve through a profile view.

    THE TOP TWO ARE THE SHOULDER, and they exist because of what closed the
    hull before them: nothing did. The loft's default flat n-gon lidded the
    body with a level plate at ``torso_top``, a third of the shoulder
    half-width across and reaching five centimetres further forward than the
    arm below it, met by the hull's own wall through an eighty-four degree
    drop. That plate is what a blind art reviewer read as a pauldron -- a
    hard shard flaring sideways and forward past the arm -- and no change to
    the arm could have touched it.

    So the hull now CONTINUES upward instead of stopping: a trapezius band
    rising off the yoke, then a neck base sized off the neck's own width, and
    only there the flat cap -- which is now buried inside the neck column and
    can never be seen. The surface from the arm to the neck is one slope, the
    neck emerges from a shoulder rather than from a shelf, and the rim of the
    yoke lands on the arm's own line (see :data:`SHOULDER_YOKE`).

    A garment lengthens the SAME body rather than hiding it inside another
    box: a jacket adds a hip hem ring, a coat and a dress add a low hem ring,
    and all hem rings share the hull's facet phase with gentle flares -- the
    hard peplum corner spikes the review found at the hips were exactly a hem
    ring whose flare outran its facets.
    """
    silhouette = _require(identity["clothing"], CLOTHING_SILHOUETTES, "clothing silhouette")
    presentation = _require(identity["presentation"], PRESENTATIONS, "presentation")
    chest_reach = PRESENTATION_SHAPE[presentation]["chest_reach"]
    leg_top, torso_top = size["leg_top"], size["torso_top"]
    height = size["height"]
    lean = size["lean"]
    span = torso_top - leg_top
    depth = size["torso_depth"]
    hip = size["hip_width"]
    jacket = 1.06 if silhouette in ("jacket", "coat", "formal") else 1.0

    # (z, width, section depth, forward shift, lean share, front reach)
    sections = [
        (leg_top - 0.030 * height, hip * HIP_SECTIONS[0], depth * 0.92, 0.0, 0.10, 1.0),
        (leg_top + 0.028 * height, hip * HIP_SECTIONS[1], depth * 1.00, 0.0, 0.25, 1.0),
        (
            leg_top + 0.38 * span,
            size["torso_waist_width"],
            depth * 0.78,
            -0.006 * height,
            0.45,
            1.0,
        ),
        (
            leg_top + 0.72 * span,
            size["torso_chest_width"],
            depth * 1.00,
            0.006 * height,
            0.75,
            chest_reach,
        ),
        (
            leg_top + 0.90 * span,
            size["torso_chest_width"] * 0.97,
            depth * 0.94,
            0.008 * height,
            0.90,
            1.0,
        ),
        (
            torso_top,
            size["torso_shoulder_width"] * SHOULDER_YOKE,
            depth * 0.88,
            0.004 * height,
            1.0,
            1.0,
        ),
        (
            torso_top + 0.007 * height,
            size["torso_shoulder_width"] * SHOULDER_YOKE * 0.60,
            depth * 0.60,
            0.004 * height,
            1.0,
            1.0,
        ),
        (
            torso_top + 0.014 * height,
            size["neck_width"] * 0.74,
            size["neck_width"] * 0.70,
            0.002 * height,
            1.0,
            1.0,
        ),
    ]
    hem = GARMENT_HEM.get(silhouette)
    if hem is not None:
        level, flare, reach, tilt = hem
        sections.insert(0, (leg_top * level, hip * flare, depth * reach, 0.0, tilt, 1.0))
    rings = [
        _ring(
            TORSO_SIDES,
            width * jacket / 2.0,
            section_depth * jacket / 2.0,
            (lean * tilt + shift, 0.0, level),
            phase=_facet_phase(TORSO_SIDES),
            front=front,
        )
        for level, width, section_depth, shift, tilt, front in sections
    ]
    return _loft("torso", "torso_hull", CLOTHING, rings)


def _neck(size: dict) -> dict:
    """A short tapered column, tucked into the skull and the clavicle.

    The render review's finding was the pedestal: a neck as long as a forearm
    and nearly as wide as the head, with the skull balanced on top of it like
    an exhibit. The v2 neck is 0.42 of the head's width, its band is 0.038 of
    the body, and both of its ends are BURIED -- a hundredth of the body into
    the skull base above and the clavicle ring below -- so what remains
    visible is the short join a neck actually is. Both ends are open: their
    caps could never be seen.
    """
    lean, torso_top, neck_top = size["lean"], size["torso_top"], size["neck_top"]
    height = size["height"]
    width = size["neck_width"]
    rings = [
        _ring(
            NECK_SIDES,
            width * 0.53,
            width * 0.50,
            (lean * 0.92, 0.0, torso_top - 0.012 * height),
            phase=_facet_phase(NECK_SIDES),
        ),
        _ring(
            NECK_SIDES,
            width * 0.42,
            width * 0.40,
            (lean, 0.0, neck_top + 0.010 * height),
            phase=_facet_phase(NECK_SIDES),
        ),
    ]
    return _loft("neck", "tapered_segment", COMPLEXION, rings, start_cap=False, end_cap=False)


def _tapered_chain(
    name: str,
    material: int,
    sides: int,
    joints: list[tuple[tuple[float, float, float], float]],
) -> dict:
    """A plain limb: circular rings threaded along a chain of joints.

    Each joint contributes one ring at its own height, its own centre and its
    own radius. The designed limbs below author richer rings than this --
    depth factors and shifts per section -- but this remains the canonical
    minimal chain, and the anatomy guard tests build their counterexamples
    with it.
    """
    rings = [_ring(sides, radius, radius * 0.92, center) for center, radius in joints]
    return _loft(name, "tapered_segment", material, rings)


def _foot_wedge(
    name: str,
    size: dict,
    ankle: tuple[float, float],
    toe_lift: float,
    silhouette: str,
) -> dict:
    """A foot: heel, instep and toe box, flat on the ground, in footwear.

    Three cross-sections now instead of a single wedge: a heel at full instep
    height, a ball where the instep begins its drop, and a low toe box. Ten
    quads read as a shoe from every angle a proof camera uses, and the
    material comes from the clothing silhouette (see :data:`FOOTWEAR`), which
    is the render review's barefoot finding closed.

    ``toe_lift`` scales the toe box, so a mid-stride foot can roll without
    the sole ever leaving z = 0.0 exactly -- grounding is a contract, not a
    tendency.

    THE SHOE IS NOT THE SAME SHOE ON EVERY BODY any more. One near-black
    slab at one set of proportions under all six silhouettes read, correctly,
    as "diving flippers" to the art review: eighty people wearing one shoe is
    a costume error the way beige slippers under a coat were. The proportions
    now come from :data:`FOOTWEAR_SHAPE` -- a dress shoe is long, narrow and
    higher at the instep, a summer one is short and flat -- and the toe box
    tapers harder than it did, which is what takes the paddle out of the
    outline. Not one extra triangle: the same twelve vertices, moved.
    """
    long_shape, wide_shape, rise = FOOTWEAR_SHAPE[silhouette]
    length = size["foot_length"] * long_shape
    tall = size["foot_height"] * rise
    wide = size["foot_width"] * wide_shape
    ankle_x, ankle_y = ankle
    heel = ankle_x - length * 0.30
    toe = ankle_x + length * 0.70
    ball = heel + length * 0.62
    heel_top = tall
    ball_top = tall * 0.86
    toe_top = size["height"] * 0.016 * toe_lift * rise
    half = wide / 2.0
    toe_half = wide * 0.34
    vertices = [
        (heel, ankle_y - half, 0.0),
        (heel, ankle_y + half, 0.0),
        (heel, ankle_y + half, heel_top),
        (heel, ankle_y - half, heel_top),
        (ball, ankle_y - half, 0.0),
        (ball, ankle_y + half, 0.0),
        (ball, ankle_y + half, ball_top),
        (ball, ankle_y - half, ball_top),
        (toe, ankle_y - toe_half, 0.0),
        (toe, ankle_y + toe_half, 0.0),
        (toe, ankle_y + toe_half, toe_top),
        (toe, ankle_y - toe_half, toe_top),
    ]
    faces = [
        (0, 3, 2, 1),
        (8, 9, 10, 11),
        (0, 1, 5, 4),
        (4, 5, 9, 8),
        (3, 7, 6, 2),
        (7, 11, 10, 6),
        (0, 4, 7, 3),
        (4, 8, 11, 7),
        (1, 2, 6, 5),
        (5, 6, 10, 9),
    ]
    return _primitive(name, "foot_wedge", FOOTWEAR[silhouette], vertices, faces)


def _mirror_points(points: dict) -> dict:
    """The same joint targets on the other side of the body, exactly.

    Negating a float is exact, so building the right side as the mirror of the
    left is what makes idle symmetry a bit-level property instead of a
    tolerance.
    """
    return {name: (x, -y) for name, (x, y) in points.items()}


def _pose_frame(pose: str, size: dict) -> dict:
    """Where the limbs and the head sit for one standing attitude.

    Every pose is STANDING: a fixed arrangement of limbs, no animation. Two
    render findings are settled here rather than in any single pose. First,
    the stance: legs root at 0.28 of the hip width to each side of the
    centreline with the feet under them, because the review found idle legs
    planted so close together that a front view read as one bowling-pin
    column. Second, the set: idle elbows and knees carry a small natural
    bend, because a body of plumb-vertical dowels reads as a mannequin -- and
    idle keeps EXACT mirror symmetry, set and all, which the lateral offsets
    cannot disturb: gait articulation swings limbs in the X-Z plane about
    ring-centroid pivots, and a lateral separation is orthogonal to it.
    """
    height = size["height"]
    leg_top, torso_top = size["leg_top"], size["torso_top"]
    # The ankle ring sits INSIDE the foot, not on top of it. A foot's upper
    # surface slopes down from heel to toe, so a leg planted at the heel height
    # would end millimetres above the foot at the point it is supposed to meet
    # it -- a visible gap between the shin and the shoe.
    ankle_z = size["foot_height"] * 0.55
    knee_z = ankle_z + (leg_top - ankle_z) * 0.52
    hip_z = leg_top + 0.020 * height
    stance = size["hip_width"] * 0.28
    scale = size["limb"] / _LIMB_REFERENCE
    # The shoulder span is INHERENT and cannot be tuned away: the arm has to
    # reach the published shoulder width while the hull's shoulder ring is
    # 0.56 of it, so seventy to a hundred millimetres of arm always stands
    # outside the torso. What was wrong was the SHAPE of that span. A deltoid
    # tucked up under the shoulder line made a pointed pauldron; dropping it a
    # fixed amount replaced the point with a shelf sloping barely 25 degrees,
    # which reads as a square pad at lineup distance.
    #
    # So the drop is SOLVED, not chosen. The socket is seated as far out as
    # the hull allows and the deltoid is placed at whatever depth makes the
    # outer surface between them steeper than SHOULDER_SLOPE -- which means a
    # broad figure, whose span is longest, gets the deepest shoulder, and no
    # build can produce a shelf.
    # A ring's widest vertex is not its radius: a six-sided ring reaches
    # sin(60) of it. Both ends are placed by their REAL extent, so the arm's
    # outer surface lands exactly on the published shoulder width.
    spread = max(abs(sin) for _cos, sin in _ring_trig(ARM_SIDES, 0.0))
    spread8 = max(abs(sin) for _cos, sin in _ring_trig(TORSO_SIDES, _facet_phase(TORSO_SIDES)))
    deltoid_reach = ARM_LOFT[0][1] * scale * DELTOID_FLARE * spread
    arm_side = size["shoulder_width"] / 2.0 - deltoid_reach
    # The socket is seated against the hull's REAL boundary, in BOTH axes.
    # Sizing it off the ring's nominal half-width alone was wrong twice over:
    # an eight-sided ring's edge runs cos(pi/8) of the way out, not all of it,
    # and nothing at all constrained the front-to-back margin -- so on the
    # thin garments, which get no 1.06 hull bonus, a flat cap sat six tenths
    # of a millimetre inside a hull and the bevel surfaced it.
    # Seated against the YOKE rather than against the published shoulder ring:
    # the hull's top section keeps only SHOULDER_YOKE of that width, and a
    # socket sized on the published number would now hang outside the body it
    # is supposed to be buried in.
    inradius = math.cos(math.pi / TORSO_SIDES)
    allow_y = size["torso_shoulder_width"] * SHOULDER_YOKE / 2.0 * inradius - 0.006
    allow_x = size["torso_depth"] * 0.88 / 2.0 * inradius - 0.006
    socket_r = min(ARM_LOFT[0][1] * scale * DELTOID_FLARE * 0.70, allow_x / 0.92)
    socket_reach = allow_y
    socket_side = socket_reach - socket_r * spread
    # The SOLVED position is the deltoid's own, and nothing sits between the
    # two: the run the eye reads as the shoulder slope is the run that was
    # solved, end to end, with no intermediate ring to lay a crease across it.
    shoulder_z = (
        torso_top
        - 0.004 * height
        - math.tan(SHOULDER_SLOPE) * (size["shoulder_width"] / 2.0 - socket_reach)
    )
    elbow_z = shoulder_z - size["upper_arm_length"]
    wrist_z = elbow_z - size["forearm_length"]
    hand_z = wrist_z - size["hand_length"]
    lean = size["lean"]
    knee_set = 0.012 * height
    hand_forward = 0.012 * height

    left_leg = {
        "hip": (0.0, stance),
        "knee": (knee_set, stance * 0.99),
        "ankle": (0.0, stance * 0.97),
    }
    # EVERY JOINT BELOW THE DELTOID IS SOLVED AGAINST THE HIP, for the same
    # reason the shoulder's depth is solved against the shoulder: an authored
    # fraction cannot hold across a vocabulary whose widest hip is as broad as
    # its average shoulder. Each of the elbow, the wrist and the hand is swung
    # out to whichever is further -- its authored hang, or far enough that its
    # OWN ring clears the widest thing the body could be wearing below the
    # waist by HAND_CLEARANCE. Below the deltoid the arm is then guaranteed
    # clear of the torso on every build, so the only place a sleeve and a
    # garment can meet is up under the arm, where they overlap, and the run of
    # hairline daylight down the hip cannot form at all.
    hang_elbow, hang_wrist, hang_hand = ARM_HANG
    hip_reach = size["hip_width"] / 2.0 * GARMENT_WIDEST * spread8
    elbow_r, wrist_r = (entry[1] * scale * spread for entry in ARM_LOFT[1:])
    hand_half = HAND_PADDLE[0] * scale * spread

    def hangs(authored: float, half: float, share: float, floor: float = 0.0) -> float:
        """One joint's lateral offset: outside the hip, but never akimbo.

        The vocabulary lets a broad feminine hip reach the same half-width as
        the shoulder above it, and no arm can hang clear of a hip that wide
        without bowing out past its own deltoid. So the swing is capped at a
        share of the deltoid's reach -- the hand may go as far as the
        published shoulder line and no further -- and where the cap bites,
        the joint ends up INSIDE the hull instead, which is a limb resting
        against a hip rather than a limb with a slit behind it.
        """
        return max(
            min(
                max(authored, hip_reach + half + HAND_CLEARANCE * height),
                arm_side + deltoid_reach * share,
            ),
            floor,
        )

    elbow_side = hangs(arm_side * hang_elbow, elbow_r, 0.35)
    wrist_side = hangs(arm_side * hang_wrist, wrist_r, 1.15)
    hand_side = hangs(arm_side * hang_hand, hand_half, 1.20, floor=hip_reach)
    left_arm = {
        "shoulder": (lean * 0.95 + 0.004 * height, arm_side),
        "elbow": (lean * 0.55 + 0.006 * height, elbow_side),
        "wrist": (lean * 0.22 + 0.020 * height, wrist_side),
        "hand": (lean * 0.22 + 0.020 * height + hand_forward, hand_side),
    }
    frame = {
        "head_turn": 0.0,
        "legs": {"left": left_leg, "right": _mirror_points(left_leg)},
        "arms": {"left": left_arm, "right": _mirror_points(left_arm)},
        "leg_levels": (hip_z, knee_z, ankle_z),
        "arm_levels": (shoulder_z, elbow_z, wrist_z, hand_z),
        "toe_lift": {"left": 1.0, "right": 1.0},
        "socket_side": socket_side,
    }

    limb = size["limb"]
    stride = leg_top * 0.20
    swing = size["arm_length"] * 0.20
    if pose == "observe":
        frame["head_turn"] = 0.42
        frame["arms"]["left"] = {
            "shoulder": (lean * 0.95 + 0.004 * height, arm_side),
            "elbow": (lean * 0.55 + limb * 0.55, elbow_side * 1.06),
            "wrist": (lean * 0.22 + limb * 1.40, wrist_side * 0.78),
            "hand": (lean * 0.22 + limb * 1.70 + hand_forward, hand_side * 0.68),
        }
        frame["legs"]["right"] = {
            "hip": (0.0, -stance),
            "knee": (knee_set, -stance * 1.04),
            "ankle": (0.0, -stance * 1.10),
        }
    elif pose == "stroll":
        frame["legs"]["left"] = {
            "hip": (0.0, stance * 0.88),
            "knee": (stride * 0.55, stance * 0.86),
            "ankle": (stride, stance * 0.84),
        }
        frame["legs"]["right"] = {
            "hip": (0.0, -stance * 0.88),
            "knee": (-stride * 0.42, -stance * 0.86),
            "ankle": (-stride * 0.86, -stance * 0.84),
        }
        frame["arms"]["left"] = {
            "shoulder": (lean * 0.95 + 0.004 * height, arm_side),
            "elbow": (lean * 0.55 - swing * 0.55, elbow_side),
            "wrist": (lean * 0.22 - swing, wrist_side),
            "hand": (lean * 0.22 - swing * 1.30, hand_side),
        }
        frame["arms"]["right"] = {
            "shoulder": (lean * 0.95 + 0.004 * height, -arm_side),
            "elbow": (lean * 0.55 + swing * 0.55, -elbow_side),
            "wrist": (lean * 0.22 + swing, -wrist_side),
            "hand": (lean * 0.22 + swing * 1.30 + hand_forward, -hand_side),
        }
        frame["toe_lift"] = {"left": 0.78, "right": 1.28}
    elif pose == "rest":
        frame["head_turn"] = -0.22
        frame["legs"]["left"] = {
            "hip": (0.0, stance * 0.96),
            "knee": (knee_set, stance * 0.90),
            "ankle": (0.0, stance * 0.86),
        }
        frame["legs"]["right"] = {
            "hip": (0.0, -stance * 1.02),
            "knee": (knee_set + limb * 0.20, -stance * 1.50),
            "ankle": (limb * 0.32, -stance * 1.85),
        }
        frame["arms"]["right"] = {
            "shoulder": (lean * 0.95 + 0.004 * height, -arm_side),
            "elbow": (lean * 0.55 + limb * 0.45, -elbow_side * 1.02),
            "wrist": (lean * 0.22 + limb * 0.75, -wrist_side * 1.06),
            "hand": (lean * 0.22 + limb * 0.75 + hand_forward, -hand_side * 1.06),
        }
    elif pose != "idle":
        raise FigureKitError(f"unknown pose {pose!r}")
    return frame


def _leg_rings(size: dict, points: dict, levels: tuple) -> list[tuple]:
    """The five designed cross-sections of one leg, threaded through its pose.

    Hip, knee and ankle centres come from the pose; the thigh and calf rings
    sit on the straight segments between them -- the thigh 22 per cent down
    the leg, the calf 42 per cent below the knee -- with their own radii,
    depth factors and forward shifts from :data:`LEG_LOFT`. The knee is a
    real pinch between a fuller thigh and a fuller calf, which is what lets a
    bent leg read as BENT: a straight taper swallows its own knee however far
    the joint travels.
    """
    hip_z, knee_z, ankle_z = levels
    scale = size["limb"] / _LIMB_REFERENCE
    thigh_z = hip_z - 0.22 * (hip_z - ankle_z)
    calf_z = knee_z - 0.42 * (knee_z - ankle_z)
    hip, knee, ankle = points["hip"], points["knee"], points["ankle"]
    thigh_blend = (hip_z - thigh_z) / (hip_z - knee_z)
    calf_blend = (knee_z - calf_z) / (knee_z - ankle_z)
    centers = {
        "hip": (hip[0], hip[1], hip_z),
        "thigh": (
            hip[0] + (knee[0] - hip[0]) * thigh_blend,
            hip[1] + (knee[1] - hip[1]) * thigh_blend,
            thigh_z,
        ),
        "knee": (knee[0], knee[1], knee_z),
        "calf": (
            knee[0] + (ankle[0] - knee[0]) * calf_blend,
            knee[1] + (ankle[1] - knee[1]) * calf_blend,
            calf_z,
        ),
        "ankle": (ankle[0], ankle[1], ankle_z),
    }
    return [
        _ring(
            LEG_SIDES,
            radius * scale,
            radius * scale * 0.92 * depth_factor,
            (
                centers[name][0] + shift * scale,
                centers[name][1],
                centers[name][2],
            ),
        )
        for name, radius, depth_factor, shift in LEG_LOFT
    ]


def _limbs(identity: dict, size: dict, frame: dict) -> list[dict]:
    """Both arms with hands, both legs and both feet, as designed chains.

    Every arm is three members now -- upper arm, forearm, hand -- whatever the
    garment, because the chain contract (:data:`CHAIN_SPEC`) wants one
    structure for every body. The garment chooses MATERIALS: a short sleeve
    ends at the elbow seam and bares the forearm, a dress does the same, and
    the hand is always complexion. The seam rings are the SAME ring reused,
    so the elbow and wrist joints are coincident circles of vertices and no
    articulation can pull them apart.
    """
    silhouette = _require(identity["clothing"], CLOTHING_SILHOUETTES, "clothing silhouette")
    bare_forearm = silhouette in ("short_sleeve", "dress")
    bare_legs = silhouette == "dress"
    scale = size["limb"] / _LIMB_REFERENCE
    primitives: list[dict] = []

    shoulder_z, elbow_z, wrist_z, hand_z = frame["arm_levels"]
    socket_z = size["torso_top"] - 0.004 * size["height"]
    deltoid_r, elbow_r, wrist_r = (entry[1] * scale for entry in ARM_LOFT)
    for side in ("left", "right"):
        points = frame["arms"][side]
        # The SOCKET: a small ring lifted to the hull's own shoulder level and
        # pulled well inside its half-width, so the upper arm's only flat cap
        # is buried in the torso instead of presenting a horizontal disc to
        # camera. Flaring the deltoid alone did not fix that -- a wider flat
        # top is still a flat top, which is why the v2 arm still read as a
        # plank with an armpit open to the background. Running the surface up
        # and inward closes both.
        socket_r = deltoid_r * DELTOID_FLARE * 0.70
        socket_y = math.copysign(frame["socket_side"], points["shoulder"][1])
        socket = _ring(
            ARM_SIDES,
            socket_r,
            socket_r * 0.92,
            (points["shoulder"][0], socket_y, socket_z),
        )
        # The DELTOID is the widest ring, and it is the one that lands exactly
        # on the published shoulder width. It is also the only ring between
        # the socket and the elbow, so the surface off the socket falls to it
        # in one straight run at SHOULDER_SLOPE and then turns once, into the
        # arm. Any ring in between makes that turn twice, and a viewer reads
        # the upper of the two as a yoke laid across the shoulders.
        root_r = deltoid_r * DELTOID_FLARE
        deltoid = _ring(ARM_SIDES, root_r, root_r * 0.92, (*points["shoulder"], shoulder_z))
        elbow = _ring(ARM_SIDES, elbow_r, elbow_r * 0.92, (*points["elbow"], elbow_z))
        wrist = _ring(ARM_SIDES, wrist_r, wrist_r * 0.92, (*points["wrist"], wrist_z))
        # The HAND, threaded down the wrist-to-hand run rather than dropped at
        # the end of it. Every ring's centre is the same interpolation of two
        # mirrored points, so a right hand stays the exact mirror of a left.
        wrist_x, wrist_y = points["wrist"]
        hand_x, hand_y = points["hand"]
        hand_rings = [wrist]
        for _name, along, lateral, deep in HAND_LOFT:
            hand_rings.append(
                _ring(
                    ARM_SIDES,
                    lateral * scale,
                    deep * scale,
                    (
                        wrist_x + (hand_x - wrist_x) * along,
                        wrist_y + (hand_y - wrist_y) * along,
                        wrist_z + (hand_z - wrist_z) * along,
                    ),
                )
            )
        primitives.append(
            _loft(
                f"{side}_upper_arm",
                "tapered_segment",
                CLOTHING,
                [socket, deltoid, elbow],
                start_cap=False,
                end_cap=False,
            )
        )
        primitives.append(
            _loft(
                f"{side}_forearm",
                "tapered_segment",
                COMPLEXION if bare_forearm else CLOTHING,
                [elbow, wrist],
                start_cap=False,
                end_cap=False,
            )
        )
        primitives.append(
            _loft(
                f"{side}_hand",
                "tapered_segment",
                COMPLEXION,
                hand_rings,
                start_cap=False,
            )
        )

    leg_material = COMPLEXION if bare_legs else CLOTHING
    for side in ("left", "right"):
        points = frame["legs"][side]
        primitives.append(
            _loft(
                f"{side}_leg",
                "tapered_segment",
                leg_material,
                _leg_rings(size, points, frame["leg_levels"]),
                end_cap=False,
            )
        )
        primitives.append(
            _foot_wedge(f"{side}_foot", size, points["ankle"], frame["toe_lift"][side], silhouette)
        )
    return primitives


def _accessories(identity: dict, size: dict) -> list[dict]:
    """Garment geometry that sits ON a valid body, never instead of one.

    The jacket family -- jacket, coat, formal -- earns an accent V-collar:
    two angled lapel strips meeting at the sternum, eight triangles. Formal
    adds the placket, the one axis-aligned cuboid the vocabulary permits,
    standing proud of the jacket front.
    """
    silhouette = _require(identity["clothing"], CLOTHING_SILHOUETTES, "clothing silhouette")
    if silhouette not in ("jacket", "coat", "formal"):
        return []
    leg_top, torso_top = size["leg_top"], size["torso_top"]
    height = size["height"]
    span = torso_top - leg_top
    depth = size["torso_depth"]
    lean = size["lean"]
    chest = size["torso_chest_width"]
    primitives: list[dict] = []

    # A lapel STARTS ON THE SHOULDER. The v2 collar began in mid-chest and
    # ran down, which from any distance was a dark Y painted on a torso: a
    # strip whose top edge floats has no attachment to read, whatever its
    # proportions. This one begins at the hull's own shoulder ring, rises
    # over the trapezius towards the neck, and only then falls to the
    # sternum, so the eye can follow it onto the body.
    #
    # AND IT LIES ON THE GARMENT. Every one of these depths used to be
    # arithmetic -- a lean, a share of the hull's depth, a hem multiplier and
    # a four-millimetre standoff -- which is a strip built to a description of
    # the chest rather than to the chest. Where the description was generous
    # the strip stood off the body carrying its own thickness, and the art
    # review read the result exactly: "a dead bird draped over the chest".
    # Each point is now placed against the hull's OWN cross-section at its own
    # height and lateral (see :func:`_section_front`), a millimetre and a half
    # proud, so a lapel follows a broad chest and a slim one without being
    # told which it is on.
    hull = _torso_hull(identity, size)
    neck_half = size["neck_width"] * 0.53
    collar_z = torso_top - 0.006 * height
    nape_z = torso_top + 0.010 * height
    mid_z = leg_top + span * 0.84
    low_z = leg_top + span * 0.70

    def onto(level: float, lateral: float) -> tuple[float, float, float]:
        section = section_at_height(hull, TORSO_SIDES, level)
        front = _section_front(section, lateral) if section else lean
        return (front + COLLAR_LIFT, lateral, level)

    left = [
        onto(nape_z, neck_half * 1.20),
        onto(collar_z, size["torso_shoulder_width"] * SHOULDER_YOKE * 0.42),
        onto(mid_z, chest * 0.150),
        onto(mid_z, chest * 0.055),
        onto(low_z, chest * 0.036),
        onto(low_z, chest * 0.004),
    ]
    right = [(x, -y, z) for x, y, z in left]
    vertices = left + right
    left_faces = [(3, 2, 1, 0), (5, 4, 2, 3)]
    right_faces = [tuple(6 + index for index in reversed(face)) for face in left_faces]
    primitives.append(_primitive("collar", "accessory", ACCENT, vertices, left_faces + right_faces))

    if silhouette == "formal":
        # The placket RUNS OUT rather than stopping. Its top meets the collar
        # V where the lapels close, and its bottom tapers to a narrow tip
        # carried down to the jacket's own hem ring, so neither end is a
        # squared edge hanging in mid-air -- which is what made the v2 bar
        # read as a strap laid over a chest. Still one solid, and still the
        # only axis-aligned cuboid family the vocabulary permits.
        high = low_z + 0.004 * height
        low = leg_top - 0.030 * height
        half = size["waist_width"] * 0.070
        tip = half * 0.34
        front = lean * 0.70 + 0.006 * height + depth * 1.06 / 2.0 + 0.005
        back = front - 0.026
        # The tip is placed against the HULL's own surface at that height, not
        # against chest arithmetic. A jacket narrows towards its hem, so a
        # placket sized on the chest hangs its squared end in mid-air over the
        # trousers -- which is what the render review saw after the tip had
        # already been moved 200mm lower. Sinking it a millimetre behind the
        # real surface means there is no tip to see at all.
        hull = section_at_height(_torso_hull(identity, size), TORSO_SIDES, low)
        tip_x = (max(point[0] for point in hull) - 0.001) if hull else back
        placket_vertices = [
            (tip_x, -tip, low),
            (tip_x, tip, low),
            (front, half, high),
            (front, -half, high),
            (tip_x - 0.004, -tip, low),
            (tip_x - 0.004, tip, low),
            (back, half, high),
            (back, -half, high),
        ]
        placket_faces = [
            (0, 1, 2, 3),
            (7, 6, 5, 4),
            (4, 5, 1, 0),
            (5, 6, 2, 1),
            (6, 7, 3, 2),
            (7, 4, 0, 3),
        ]
        primitives.append(
            _primitive("placket", "accessory", ACCENT, placket_vertices, placket_faces)
        )
    return primitives


def figure_geometry(identity: dict) -> list[dict]:
    """One complete body, as named primitives in body space.

    THE entry point. Assembled from the five independent choices in the
    identity: a six-ring torso hull, a short neck, two three-member arm
    chains with hands, two five-ring legs with shoes, a faceted head with its
    face, ears and hair, and whatever garment detail the identity asked for.
    The emission order is the shape-key contract with Phase 19 and must stay
    stable for a given identity.
    """
    size = figure_dimensions(identity)
    frame = _pose_frame(identity["pose"], size)
    primitives: list[dict] = [_torso_hull(identity, size), _neck(size)]
    primitives.extend(_limbs(identity, size, frame))
    head = head_frame(size, frame["head_turn"], identity["face"])
    primitives.extend(
        place_head_feature(head, feature) for feature in head_features(identity, head)
    )
    primitives.extend(_accessories(identity, size))
    return primitives


def figure_mesh(identity: dict) -> dict:
    """One body welded into a single indexed mesh, ready for Blender.

    Vertices in one flat list, faces as index tuples, and one material index
    per face. The builder does nothing but hand these to ``bmesh``.
    """
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    materials: list[int] = []
    for primitive in figure_geometry(identity):
        offset = len(vertices)
        vertices.extend(primitive["vertices"])
        for face in primitive["faces"]:
            faces.append(tuple(index + offset for index in face))
            materials.append(primitive["material"])
    return {"vertices": vertices, "faces": faces, "materials": materials}


def figure_triangles(identity: dict) -> int:
    """The triangle cost of one body, counted the way Blender counts it."""
    return sum(triangle_count(primitive) for primitive in figure_geometry(identity))


def placed_head_features(identity: dict) -> dict[str, dict]:
    """Every head primitive in BODY space, by name.

    The named handle the contract is verified through. Tests and the Blender
    structural suite both ask for ``left_eye`` rather than guessing which lump
    of geometry an eye happened to be, so a reordering can never quietly turn a
    face check into a check of something else.
    """
    size = figure_dimensions(identity)
    frame = head_frame(size, _pose_frame(identity["pose"], size)["head_turn"], identity["face"])
    return {
        feature["name"]: place_head_feature(frame, feature)
        for feature in head_features(identity, frame)
    }


def feature_bounds(primitive: dict) -> dict:
    """The axis-aligned extent of one placed primitive."""
    return primitive_bounds(primitive)


def head_forward(frame: dict) -> tuple[float, float, float]:
    """The head's forward unit vector in body space."""
    return (math.cos(frame["turn"]), math.sin(frame["turn"]), 0.0)


def feature_front(frame: dict, primitive: dict) -> tuple[float, float, float]:
    """The centre of one feature's FRONT face, in body space.

    Measured along the head's own forward axis, which is the only measurement
    that stays correct when the head is turned. An axis-aligned bound is not:
    it describes a box that is square to the body, and a turned feature is not.

    The front vertices are found in head-local space and then carried through
    the head's transform, so the answer is a point on the built mesh.

    A conforming plate records WHICH of its vertices form the outward face, and
    that record is used when it exists. Inferring the front from depth alone
    does not survive a curved cheek: the plate's inner column can stand further
    forward than its outer column's back face, so any depth threshold either
    keeps a back vertex or drops a front one, and the answer lands on an edge
    of the feature rather than in the middle of it. Aiming a probe ray at an
    edge aims it at the corner the bevel modifier rounds off, which reads as a
    miss the geometry never committed.
    """
    local = primitive["vertices"]
    indices = primitive.get("front")
    if indices is None:
        reach = max(vertex[0] for vertex in local)
        front = [vertex for vertex in local if reach - vertex[0] < 1.0e-6]
    else:
        front = [local[index] for index in indices]
    center = (
        math.fsum(vertex[0] for vertex in front) / len(front),
        math.fsum(vertex[1] for vertex in front) / len(front),
        math.fsum(vertex[2] for vertex in front) / len(front),
    )
    cos_turn, sin_turn = math.cos(frame["turn"]), math.sin(frame["turn"])
    origin_x, origin_y, _origin_z = frame["origin"]
    return (
        origin_x + center[0] * cos_turn - center[1] * sin_turn,
        origin_y + center[0] * sin_turn + center[1] * cos_turn,
        center[2],
    )


def head_probe(identity: dict) -> tuple[dict, dict]:
    """The head frame and its head-local features, ready to probe."""
    size = figure_dimensions(identity)
    frame = head_frame(size, _pose_frame(identity["pose"], size)["head_turn"], identity["face"])
    return frame, {feature["name"]: feature for feature in head_features(identity, frame)}


def geometry_key(identity: dict) -> tuple:
    """Everything about an identity that changes its MESH.

    Palette and complexion are materials, so two figures that differ only in
    colour share one mesh datablock. Everything else is geometry -- including
    the face, which since v2 shapes the skull's jaw and chin and selects each
    hair variant's sub-silhouette.
    """
    return (
        identity["age_presentation"],
        identity["presentation"],
        identity["stature"],
        identity["build"],
        identity["hair"],
        identity["facial_hair"],
        identity["face"],
        identity["clothing"],
        identity["pose"],
    )


def silhouette_signature(identity: dict) -> tuple:
    """What a viewer at proof distance can actually tell apart.

    Used by the local-diversity rule: two bodies standing together must not
    share this, even if some detail elsewhere differs. Height is bucketed
    because a centimetre is not a visible difference.
    """
    size = figure_dimensions(identity)
    return (
        identity["age_presentation"],
        identity["build"],
        identity["hair"],
        identity["clothing"],
        identity["palette"],
        identity["pose"],
        int(math.floor(size["height"] * 8.0)),
    )
