"""The Phase 18 figure kit: how one visual identity becomes a body.

Pure Python by design -- no ``bpy``. Every proportion, every limb and every
feature is arithmetic over a visual identity, returned as explicit
PRIMITIVES: named lumps of geometry carrying their own vertices and faces.
The Blender builder welds them into one mesh; it decides nothing. A reviewer
can therefore check that a child is child-shaped, that a thigh is thicker
than a shin, or that a head is not a cube, on a machine with no Blender at
all -- by measuring the vertices the kit actually emitted.

    THIS KIT EMITS GEOMETRY, NOT BOXES.

That sentence is the whole point of this file's second life. The first
version described a body as a list of axis-aligned boxes and handed them to a
box builder, so however carefully the proportions were tuned the result was a
stack of rectangles: a cuboid skull, a peg neck, slab torso sections,
rectangular stick arms and rectangular column legs. It read as a voxel
character. Renaming that function would have changed nothing, so the boxes
are gone and the vocabulary below took their place:

    faceted_head       a low-poly skull hull: radial facets, a crown and a
                       chin pole, a widest cheek ring and a narrowing jaw
    torso_hull         one lofted body from hip, waist, chest and shoulder
                       cross-sections -- not a pile of slabs
    tapered_segment    a limb chain: rings threaded along shoulder-elbow-wrist
                       or hip-knee-ankle, thick end to thin end
    foot_wedge         a real foot with a heel, a toe and a direction
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
    2  hair            hair and facial hair
    3  accent          eyes, brow, and dark garment detail

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
deliberate: a body that could be described as boxes is the defect this file
exists to remove."""

PROPORTIONS = {
    "child": {
        "height": 1.15,
        "leg": 0.470,
        "torso": 0.310,
        "neck": 0.035,
        "head": 0.185,
        "shoulder": 0.228,
        "hip": 0.200,
        "depth": 0.135,
        "limb": 0.070,
        "arm": 0.300,
        "lean": 0.0,
    },
    "teen": {
        "height": 1.60,
        "leg": 0.505,
        "torso": 0.303,
        "neck": 0.040,
        "head": 0.152,
        "shoulder": 0.226,
        "hip": 0.190,
        "depth": 0.122,
        "limb": 0.056,
        "arm": 0.320,
        "lean": 0.0,
    },
    "adult": {
        "height": 1.75,
        "leg": 0.520,
        "torso": 0.302,
        "neck": 0.045,
        "head": 0.133,
        "shoulder": 0.235,
        "hip": 0.192,
        "depth": 0.130,
        "limb": 0.060,
        "arm": 0.325,
        "lean": 0.0,
    },
    "elder": {
        "height": 1.68,
        "leg": 0.505,
        "torso": 0.312,
        "neck": 0.043,
        "head": 0.140,
        "shoulder": 0.220,
        "hip": 0.200,
        "depth": 0.132,
        "limb": 0.056,
        "arm": 0.315,
        "lean": 0.030,
    },
}
"""Body proportions per age presentation, as FRACTIONS of total height.

``leg``, ``torso``, ``neck`` and ``head`` are the four stacked bands and sum
to exactly 1.0. The rest are widths and lengths, also relative to height, so
a figure scales as one coherent body rather than as a stretched adult.

The child is not a small adult and the numbers say so. Its head is 0.185 of
its height against an adult's 0.133 -- one head in five and a half rather
than one in seven and a half -- its legs are 0.470 against 0.520, and its
shoulders are narrow while its limbs are proportionally thicker. Uniformly
scaling an adult would have produced a 1.15m adult, which reads as a distant
adult and not as a child.

``lean`` tilts the upper body forward. Only the elder carries any, and it is
posture, not infirmity.

``shoulder`` is the OUTER width of the upper body, arms included, not the
width of the torso between them. The first version treated it as the torso
and hung the arms outside it, which made every figure a quarter too wide and
read as a slab on two sticks.

These numbers are UNCHANGED by the geometry rebuild, on purpose. They and
:func:`silhouette_signature` decide which identity lands in which slot, so
touching them would have reshuffled the population while claiming to have
only changed how a body is drawn.
"""

STATURE_SCALE = {"short": 0.93, "average": 1.00, "tall": 1.08}

BUILD_SHAPE = {
    "slim": {"shoulder": 0.90, "hip": 0.90, "depth": 0.85, "limb": 0.85, "waist": 0.88},
    "average": {"shoulder": 1.00, "hip": 1.00, "depth": 1.00, "limb": 1.00, "waist": 1.00},
    "athletic": {"shoulder": 1.11, "hip": 0.93, "depth": 1.01, "limb": 1.06, "waist": 0.89},
    "broad": {"shoulder": 1.15, "hip": 1.20, "depth": 1.24, "limb": 1.20, "waist": 1.02},
}
"""Build changes the SHAPE, not just the scale.

Athletic widens the shoulders while narrowing the hips; broad widens both and
deepens the torso; slim narrows everything. A single uniform multiplier would
have produced the same body at different sizes, which is what the population
looked like before.

``waist`` is new, and it is the axis that makes the difference visible now
that the torso is a lofted hull rather than a stack of slabs: an athletic
figure gets a hard shoulder-to-waist taper, a broad one carries its width all
the way down, and a slim one is narrow throughout.
"""

PRESENTATION_SHAPE = {
    "masculine": {"shoulder": 1.06, "hip": 0.94, "waist": 1.02},
    "feminine": {"shoulder": 0.93, "hip": 1.08, "waist": 0.90},
    "unspecified": {"shoulder": 1.00, "hip": 1.00, "waist": 1.00},
}
"""Shoulder-to-hip relationship and waist taper only. This is silhouette, and
it is all it is."""

FACE_SHAPE = {
    "a": {"width": 1.00, "brow": 1.00, "eye_gap": 1.00, "nose": 1.00},
    "b": {"width": 1.06, "brow": 1.15, "eye_gap": 1.06, "nose": 0.90},
    "c": {"width": 0.94, "brow": 0.85, "eye_gap": 0.94, "nose": 1.12},
    "d": {"width": 1.02, "brow": 1.05, "eye_gap": 0.90, "nose": 1.05},
}
"""Four restrained facial proportions. Enough that two heads differ; far
short of anything that could be called a likeness."""

CLOTHING = 0
COMPLEXION = 1
HAIR = 2
ACCENT = 3


# ---------------------------------------------------------------------------
# Resolution: how many facets each part of the body is allowed
# ---------------------------------------------------------------------------

HEAD_SIDES = 8
TORSO_SIDES = 6
ARM_SIDES = 5
LEG_SIDES = 5
NECK_SIDES = 5
HAIR_SIDES = 8
HAIR_VOLUME_SIDES = 5
"""Radial facet counts, one per body part.

These are the cost dials, and they were set by measurement rather than by
taste. Eighty bodies have to fit inside a declared triangle budget for the
proof scene, so each number is the smallest that still reads as a curved
surface rather than as a slab, and the budget was spent where a reviewer
actually looks.

The head keeps eight because the head is what gets inspected: it carries the
face QA plate, and a skull is the one part a viewer will call a cube if it is
one. A torso is a metre of clothed volume seen from ten to thirty metres and
six facets is indistinguishable from eight there; a limb is a few centimetres
across and five is enough for it to read as a tapered tube instead of a
stick. Eight everywhere was measured at 30,908 triangles against a 30,000
ceiling, which is the honest reason these are not all eight.

Odd counts are mirror-symmetric about the body's centreline for free, which
is why the limbs use five.
"""


def _facet_phase(sides: int) -> float:
    """Half a facet of rotation, so a FACE is centred dead ahead.

    Without it an even-sided ring puts a VERTEX on the centreline, which runs
    a vertical crease straight down the middle of the face. With it, a flat
    facet is centred dead ahead -- a cheek plane to mount a face on -- and the
    ring is still exactly symmetric left to right.
    """
    return math.pi / sides


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

    Everything above the divider returns exactly what it returned before the
    geometry rebuild, to the last bit. Those numbers reach the published plan
    and :func:`silhouette_signature`, so changing one would have reshuffled who
    stands where while claiming to have only changed how a body is drawn.

    The torso cross-sections below the divider are new, and the waist is
    pinched BY CONSTRUCTION rather than by tuning: it is a fraction of
    whichever of the hip and the chest is already narrower, and the largest
    product of a build waist factor and a presentation waist factor is
    1.02 * 1.02 = 1.0404, which times 0.84 is 0.874. Under one, for every
    combination in the vocabulary, with no search and nothing to re-tune when a
    build is added -- so no figure can ever be built barrel-sided.
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
    shoulder = base["shoulder"] * height * shape["shoulder"] * bias["shoulder"]
    hip = base["hip"] * height * shape["hip"] * bias["hip"]
    limb = base["limb"] * height * shape["limb"]
    leg_thickness = limb * 1.58
    return {
        "height": height,
        "leg_top": leg_top,
        "torso_top": torso_top,
        "neck_top": neck_top,
        "head_height": head_height,
        "head_width": head_height * 0.78,
        "head_depth": head_height * 0.84,
        "shoulder_width": shoulder,
        "hip_width": hip,
        "waist_width": hip * 0.62 + shoulder * 0.38,
        "torso_depth": base["depth"] * height * shape["depth"],
        "limb": limb,
        "leg_thickness": leg_thickness,
        "arm_thickness": limb * 0.95,
        "arm_length": base["arm"] * height,
        "lean": base["lean"] * height,
        # --- added by the geometry rebuild; nothing above changed value ---
        "waist_taper": shape["waist"] * bias["waist"],
        "torso_chest_width": shoulder * 0.64,
        "torso_shoulder_width": shoulder * 0.60,
        "torso_waist_width": min(hip, shoulder * 0.64) * shape["waist"] * bias["waist"] * 0.84,
        "neck_width": limb * 1.22,
        "foot_length": height * 0.148,
        "foot_height": height * 0.040,
        "foot_width": leg_thickness * 0.94,
    }


# ---------------------------------------------------------------------------
# The primitive layer: rings, lofts and hulls
# ---------------------------------------------------------------------------


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
    """
    points = []
    for index in range(sides):
        angle = phase + 2.0 * math.pi * index / sides
        cos_a, sin_a = math.cos(angle), math.sin(angle)
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
) -> dict:
    """Skin a stack of rings into one closed faceted solid.

    Consecutive rings are joined band by band; the two ends are closed either
    with a flat n-gon or, when a pole is given, with a triangle fan that comes
    to a point. The fan is what gives a head a crown and a chin instead of a
    flat lid and a flat underside.
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
    if start_pole is None:
        faces.append(tuple(range(sides - 1, -1, -1)))
    else:
        pole = len(vertices)
        vertices.append(start_pole)
        for index in range(sides):
            faces.append((pole, (index + 1) % sides, index))
    top = (len(rings) - 1) * sides
    if end_pole is None:
        faces.append(tuple(range(top, top + sides)))
    else:
        pole = len(vertices)
        vertices.append(end_pole)
        for index in range(sides):
            faces.append((pole, top + index, top + (index + 1) % sides))
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

This exists because the first version did infer it, twice over, and got it
wrong both times: the eye and brow plates were authored BEHIND the head's front
face and so were sealed inside the skull, and the head turn was handed to each
feature as its own spin instead of orbiting the features around the head, so a
turned head kept its face pointing where the body pointed.
"""

HEAD_PROFILE = (
    (0.000, 0.00, 0.00, 0.020),
    (0.130, 0.60, 0.62, 0.055),
    (0.340, 0.86, 0.88, 0.022),
    (0.590, 1.00, 1.00, 0.000),
    (0.830, 0.93, 0.92, -0.024),
    (1.000, 0.00, 0.00, -0.050),
)
"""The skull's silhouette, as ``(height fraction, width, depth, forward shift)``.

Widths and depths are fractions of ``head_width`` and ``head_depth``; the
forward shift is a fraction of ``head_depth``. The first and last entries have
zero radius: they are the CHIN POLE and the CROWN POLE, the two points that
turn a barrel into a head.

Read from the bottom: a chin that comes to a point and sits forward of the
axis, a jaw that widens quickly, the widest section at the cheek, a slight
narrowing at the temple, and a crown that closes over and sits back. Four
rings and two poles at eight facets each is the smallest arrangement that
still delivers everything the correction asked for -- crown, cheek, jaw
narrowing, chin, and front-to-back readability.
"""

HEAD_FRONT_REACH = 0.94
HEAD_BACK_REACH = 1.09
"""A face is flatter than a sphere and the back of a skull is fuller.

Without this the head is rotationally symmetric and a viewer cannot tell a
turned head from a straight one until they find the eyes. With it, the
silhouette alone carries the heading -- which is the test the correction
directive actually set.
"""

EYE_PROUD = 0.0090
BROW_PROUD = 0.0095
NOSE_PROUD = 0.0165
MOUTH_PROUD = 0.0065
"""How far each feature stands PROUD of the head's curved surface, in metres.

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
    "mouth": 0.220,
    "moustache": 0.305,
    "nose": 0.440,
    "eye": 0.620,
    "brow": 0.735,
}
"""Feature heights as fractions of head height, measured from the head base.

Ordered and non-overlapping by construction: mouth, moustache, nose, eyes,
brow, and then the hairline above all of them. The structural contract that
the nose sits below the eyes and above the mouth is this table, and the tests
re-derive it from the built geometry rather than reading it back from here.
"""

HAIRLINE = 0.780
"""The lowest a hair variant may reach on the FACE. Below this it would cover
the brow, and shortly after that the eyes.

A cap's shell starts a centimetre lower, because a cap sits down over the skull
rather than growing out of it -- and it is still well clear of the brow at
0.735. The rule the tests enforce is the one that matters: no hair geometry may
stand in front of a brow, an eye or a nose, checked as real occlusion over
every combination rather than as a height threshold."""


def head_frame(size: dict, head_turn: float) -> dict:
    """The one authoritative head coordinate system for one figure."""
    half_depth = size["head_depth"] / 2.0
    front = max(
        shift * size["head_depth"] + depth * half_depth * HEAD_FRONT_REACH
        for _t, _width, depth, shift in HEAD_PROFILE
    )
    return {
        "origin": (size["lean"], 0.0, size["neck_top"]),
        "turn": float(head_turn),
        "width": size["head_width"],
        "depth": size["head_depth"],
        "height": size["head_height"],
        "front": front,
    }


def head_surface_x(frame: dict, height_fraction: float, lateral: float) -> float:
    """Where the skull's front surface actually is, at one height and offset.

    THE function the whole face contract now rests on. The old head was a box,
    so its face was the plane ``x = depth / 2`` and every feature could be
    placed against that one number. A faceted skull has no such plane: the
    surface falls away towards the temples, towards the chin and towards the
    crown, and a feature placed against a single number would be buried at one
    end of its own width and floating at the other.

    So this reproduces the built polygon exactly. It interpolates
    :data:`HEAD_PROFILE` to the requested height -- which is precisely what the
    lofted band between two rings does, because both the ring radii and the
    forward shift vary linearly along a band -- rebuilds that cross-section,
    and intersects it with the requested lateral offset. The answer is a point
    ON the mesh, not an approximation of it.

    A lateral offset beyond the skull's width at that height is CLAMPED to the
    silhouette edge, which is the nearest real surface. An earlier version
    returned the head's centre axis instead, which reports a surface far behind
    the true one: a caller sampling near the chin, where the skull narrows to a
    point, would then place a feature deep inside it and read a comfortable
    clearance while doing so.
    """
    fraction = min(max(height_fraction, 0.0), 1.0)
    lower = HEAD_PROFILE[0]
    upper = HEAD_PROFILE[-1]
    for index in range(len(HEAD_PROFILE) - 1):
        if HEAD_PROFILE[index][0] <= fraction <= HEAD_PROFILE[index + 1][0]:
            lower, upper = HEAD_PROFILE[index], HEAD_PROFILE[index + 1]
            break
    span = upper[0] - lower[0]
    blend = 0.0 if span <= 0.0 else (fraction - lower[0]) / span
    width = (lower[1] + (upper[1] - lower[1]) * blend) * frame["width"] / 2.0
    depth = (lower[2] + (upper[2] - lower[2]) * blend) * frame["depth"] / 2.0
    shift = (lower[3] + (upper[3] - lower[3]) * blend) * frame["depth"]
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


def _faceted_head(frame: dict) -> dict:
    """The skull: eight facets around, four rings and two poles tall."""
    half_width = frame["width"] / 2.0
    half_depth = frame["depth"] / 2.0
    base = frame["origin"][2]
    height = frame["height"]
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
        for level, width, depth, shift in HEAD_PROFILE[1:-1]
    ]
    chin = HEAD_PROFILE[0]
    crown = HEAD_PROFILE[-1]
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

    ``proud_low`` and ``proud_high`` differ only for the nose, which leans out
    from the bridge to the tip and would otherwise be a slab.
    """
    base = frame["origin"][2]
    height = frame["height"]
    low_z = base + level_low * height
    high_z = base + level_high * height
    levels = (level_low, (level_low + level_high) / 2.0, level_high)
    laterals = [
        lateral_center - half_span + 2.0 * half_span * column / (columns - 1)
        for column in range(columns)
    ]
    vertices: list[tuple[float, float, float]] = []
    for column, lateral in enumerate(laterals):
        low = lateral if column == 0 else (laterals[column - 1] + lateral) / 2.0
        high = lateral if column == columns - 1 else (lateral + laterals[column + 1]) / 2.0
        surface = max(
            head_surface_x(frame, level, low + (high - low) * step / 8.0)
            for level in levels
            for step in range(9)
        )
        front_low = surface + proud_low
        front_high = surface + proud_high
        back = surface + min(proud_low, proud_high) - thickness
        vertices.extend(
            [
                (front_low, lateral, low_z),
                (front_high, lateral, high_z),
                (back, lateral, low_z),
                (back, lateral, high_z),
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
    """
    face = _require(identity["face"], FACE_VARIANTS, "face variant")
    shape = FACE_SHAPE[face]
    width = frame["width"]
    features: list[dict] = []

    brow_half = width * 0.250 * shape["brow"]
    features.append(
        _conforming_plate(
            "brow",
            frame,
            level_low=FACE_LEVELS["brow"] - 0.028,
            level_high=FACE_LEVELS["brow"] + 0.028,
            lateral_center=0.0,
            half_span=brow_half,
            proud_low=BROW_PROUD,
            proud_high=BROW_PROUD,
            thickness=0.020,
            columns=3,
            material=ACCENT,
        )
    )

    eye_offset = width * 0.225 * shape["eye_gap"]
    eye_half = width * 0.100
    for name, side in (("left_eye", 1.0), ("right_eye", -1.0)):
        features.append(
            _conforming_plate(
                name,
                frame,
                level_low=FACE_LEVELS["eye"] - 0.050,
                level_high=FACE_LEVELS["eye"] + 0.050,
                lateral_center=side * eye_offset,
                half_span=eye_half,
                proud_low=EYE_PROUD,
                proud_high=EYE_PROUD,
                thickness=0.024,
                columns=2,
                material=ACCENT,
            )
        )

    features.append(
        _conforming_plate(
            "nose",
            frame,
            level_low=FACE_LEVELS["nose"] - 0.100,
            level_high=FACE_LEVELS["nose"] + 0.100,
            lateral_center=0.0,
            half_span=width * 0.080 * shape["nose"],
            proud_low=NOSE_PROUD * shape["nose"],
            proud_high=NOSE_PROUD * 0.38,
            thickness=0.026,
            columns=2,
            material=COMPLEXION,
        )
    )

    features.append(
        _conforming_plate(
            "mouth",
            frame,
            level_low=FACE_LEVELS["mouth"] - 0.017,
            level_high=FACE_LEVELS["mouth"] + 0.017,
            lateral_center=0.0,
            half_span=width * 0.120,
            proud_low=MOUTH_PROUD,
            proud_high=MOUTH_PROUD * 0.55,
            thickness=0.018,
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
                half_span=width * 0.200,
                proud_low=MOUTH_PROUD + 0.0045,
                proud_high=MOUTH_PROUD + 0.0045,
                thickness=0.022,
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


def _hair_shell(name: str, frame: dict, lift: float, start: float, stop: float) -> dict:
    """A faceted covering that follows the round skull instead of boxing it.

    Built from the SAME profile as the head and pushed out along it, so the
    hair sits on the crown as a shell rather than as a crate balanced on a
    sphere. The lift also keeps every hair face clear of the skull face beneath
    it: coplanar surfaces z-fight, and the first version rendered its hair as
    speckle for exactly that reason.

    The shell has to CONTAIN the skull, and two things conspired to stop it:

    * it took rings at the start and the midpoint, which straddled the skull's
      own ring at level 0.830 -- so the shell's straight band cut inside the
      bulge it was supposed to cover. It now places a ring at every profile
      level the skull itself has inside the covered span, so the two follow the
      same curve;
    * a six-sided shell around an eight-sided skull is a hexagon inscribed in
      an octagon, and a hexagon's edges pass INSIDE an octagon's vertices at
      the same radius. Clearing that needs a radius ratio of at least
      1/cos(30 degrees) = 1.155 to clear, and a shell standing that far out
      reads as a conical hat rather than as hair. The shell therefore carries
      the SAME facet count as the skull. Two similar octagons need only a lift
      above one to contain, so 1.028 both covers the skull completely and still
      sits on it like hair.

    Measured before the fix, eight of the nine skull vertices above the
    hairline stood outside the hair on every haired figure, at every age --
    bare complexion-coloured skull ringing the head where hair should be. The
    old check only compared the tops of two bounding boxes, so it saw nothing.
    """
    half_width = frame["width"] / 2.0
    half_depth = frame["depth"] / 2.0
    base = frame["origin"][2]
    height = frame["height"]
    levels = [start]
    levels.extend(entry[0] for entry in HEAD_PROFILE if start < entry[0] < stop - 1.0e-9)
    rings = []
    for level in levels:
        lower, upper = HEAD_PROFILE[0], HEAD_PROFILE[-1]
        for index in range(len(HEAD_PROFILE) - 1):
            if HEAD_PROFILE[index][0] <= level <= HEAD_PROFILE[index + 1][0]:
                lower, upper = HEAD_PROFILE[index], HEAD_PROFILE[index + 1]
                break
        span = upper[0] - lower[0]
        blend = 0.0 if span <= 0.0 else (level - lower[0]) / span
        width = lower[1] + (upper[1] - lower[1]) * blend
        depth = lower[2] + (upper[2] - lower[2]) * blend
        shift = lower[3] + (upper[3] - lower[3]) * blend
        rings.append(
            _ring(
                HAIR_SIDES,
                width * half_width * lift + 0.004,
                depth * half_depth * lift + 0.004,
                (shift * frame["depth"], 0.0, base + level * height),
                phase=_facet_phase(HAIR_SIDES),
                front=HEAD_FRONT_REACH,
                back=HEAD_BACK_REACH,
            )
        )
    crown = HEAD_PROFILE[-1]
    return _loft(
        name,
        "hair_shell",
        HAIR,
        rings,
        end_pole=(crown[3] * frame["depth"], 0.0, base + stop * height + 0.006),
    )


def _hair_volume(
    name: str,
    frame: dict,
    *,
    back: float,
    depth: float,
    half_width: float,
    low: float,
    high: float,
) -> dict:
    """Hair mass behind the head: a faceted lump, never a rectangular slab.

    Volume that reads at distance is added BEHIND the head, where it costs
    nothing a reviewer needs to see and cannot reach around to a brow.
    """
    base = frame["origin"][2]
    height = frame["height"]
    rings = [
        _ring(
            HAIR_VOLUME_SIDES,
            half_width * taper,
            depth * taper / 2.0,
            (-back, 0.0, base + level * height),
            phase=_facet_phase(HAIR_VOLUME_SIDES),
        )
        for level, taper in ((low, 0.82), (high, 1.0))
    ]
    return _loft(name, "hair_shell", HAIR, rings)


def _hair_features(identity: dict, frame: dict) -> list[dict]:
    """The head covering, which must change the silhouette AND spare the face.

    Every variant is authored above :data:`HAIRLINE` at the front, so no
    haircut can descend over a brow, an eye or a nose.
    """
    hair = _require(identity["hair"], HAIR_VARIANTS, "hair variant")
    if hair == "bald":
        return []
    width, depth = frame["width"], frame["depth"]
    features: list[dict] = []
    if hair == "cap":
        features.append(_hair_shell("hair_cap", frame, 1.045, HAIRLINE - 0.010, 1.0))
        features.append(
            _conforming_plate(
                "hair_brim",
                frame,
                level_low=HAIRLINE + 0.030,
                level_high=HAIRLINE + 0.075,
                lateral_center=0.0,
                half_span=width * 0.360,
                proud_low=0.052,
                proud_high=0.030,
                thickness=0.058,
                columns=3,
                material=HAIR,
            )
        )
        return features
    features.append(_hair_shell("hair_crown", frame, 1.028, HAIRLINE, 1.0))
    if hair == "medium":
        features.append(
            _hair_volume(
                "hair_back",
                frame,
                back=depth * 0.30,
                depth=depth * 0.62,
                half_width=width * 0.50,
                low=0.30,
                high=0.86,
            )
        )
    elif hair == "long":
        features.append(
            _hair_volume(
                "hair_back",
                frame,
                back=depth * 0.32,
                depth=depth * 0.62,
                half_width=width * 0.54,
                low=-0.42,
                high=0.86,
            )
        )
    elif hair == "tied":
        features.append(
            _hair_volume(
                "hair_back",
                frame,
                back=depth * 0.28,
                depth=depth * 0.54,
                half_width=width * 0.44,
                low=0.44,
                high=0.86,
            )
        )
        features.append(
            _hair_volume(
                "hair_tail",
                frame,
                back=depth * 0.56,
                depth=depth * 0.42,
                half_width=width * 0.17,
                low=0.06,
                high=0.56,
            )
        )
    return features


def head_features(identity: dict, frame: dict) -> list[dict]:
    """Every piece of the head, named, in HEAD-LOCAL space.

    The skull first, then the face, then facial hair, then hair. Named so the
    contract can be machine-verified by feature rather than by counting
    geometry: a test asks for ``left_eye`` and ``right_eye`` and measures them
    against the skull the kit actually built, instead of assuming which lump is
    which.
    """
    return [
        _faceted_head(frame),
        *_face_features(identity, frame),
        *_facial_hair_features(identity, frame),
        *_hair_features(identity, frame),
    ]


def place_head_feature(frame: dict, primitive: dict) -> dict:
    """Carry one head-local primitive into body space.

    ONE rigid transform, applied to every vertex: the head-local ``(x, y)`` is
    rotated about the head's own axis by the head turn and offset by the head
    origin. Height is untouched because the turn is about Z.

    Rotating the VERTICES is what makes the contract hold now. The first
    version emitted a box plus a rotation angle and let the builder spin each
    box about its own centre, so a turned head kept its face pointing where the
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
    """One lofted upper body: hip, waist, chest and shoulder in a single skin.

    The defect this replaces was three stacked rectangular slabs, which read
    as a chest of drawers however carefully the widths were chosen. A hull
    threaded through four real cross-sections reads as a torso: it narrows at
    the waist, swells at the chest, and carries the shoulders outward at the
    top instead of balancing a separate beam on them.

    A coat or a dress adds a FIFTH ring below the hip rather than a second
    solid, so a garment lengthens the same body instead of hiding it inside
    another box.
    """
    silhouette = _require(identity["clothing"], CLOTHING_SILHOUETTES, "clothing silhouette")
    leg_top, torso_top = size["leg_top"], size["torso_top"]
    lean = size["lean"]
    span = torso_top - leg_top
    depth = size["torso_depth"]
    jacket = 1.06 if silhouette in ("jacket", "coat", "formal") else 1.0

    # Hip out, waist in, chest out, shoulders widest. The waist has to be the
    # narrowest of the four or the hull is a barrel, and the shoulder ring is
    # the span BETWEEN the arms -- the arms themselves carry the silhouette out
    # to the full shoulder width, so the deltoid is a junction and not a beam
    # laid across the top.
    sections = [
        (leg_top - span * 0.10, size["hip_width"], depth * 0.95, 0.30),
        (leg_top + span * 0.34, size["torso_waist_width"], depth * 0.86 * jacket, 0.55),
        (leg_top + span * 0.70, size["torso_chest_width"] * jacket, depth * jacket, 0.85),
        (torso_top, size["torso_shoulder_width"] * jacket, depth * 0.93 * jacket, 1.0),
    ]
    hem = {"coat": (0.46, 1.10), "dress": (0.40, 1.22)}.get(silhouette)
    if hem is not None:
        reach, flare = hem
        sections.insert(
            0,
            (leg_top * (1.0 - reach), size["hip_width"] * flare, depth * 0.98, 0.10),
        )
    rings = [
        _ring(
            TORSO_SIDES,
            width / 2.0,
            section_depth / 2.0,
            (lean * tilt, 0.0, height),
            phase=_facet_phase(TORSO_SIDES),
        )
        for height, width, section_depth, tilt in sections
    ]
    return _loft("torso", "torso_hull", CLOTHING, rings)


def _neck(size: dict) -> dict:
    """A tapered faceted column, narrower than the head and the shoulders."""
    lean, torso_top, neck_top = size["lean"], size["torso_top"], size["neck_top"]
    width = size["neck_width"]
    rings = [
        _ring(NECK_SIDES, width / 2.0, width * 0.46, (lean * 0.88, 0.0, torso_top - width * 0.30)),
        _ring(NECK_SIDES, width * 0.42, width * 0.40, (lean, 0.0, neck_top + width * 0.10)),
    ]
    return _loft("neck", "tapered_segment", COMPLEXION, rings)


def _tapered_chain(
    name: str,
    material: int,
    sides: int,
    joints: list[tuple[tuple[float, float, float], float]],
) -> dict:
    """A limb: rings threaded along a chain of joints, thick end to thin end.

    Each joint contributes one ring at its own height, its own centre and its
    own radius, so the segment between two joints is a real tapered tube and
    the joint between two segments is a real change of direction. An arm bent
    at the elbow bends; a leg mid-stride puts its knee somewhere its hip is
    not.

    The rings are cross-sections of the limb, and a test can recover every one
    of them from the emitted vertices, which is how "the upper arm is thicker
    than the forearm" stops being a comment and becomes a measurement.
    """
    rings = [_ring(sides, radius, radius * 0.92, center) for center, radius in joints]
    return _loft(name, "tapered_segment", material, rings)


def _foot_wedge(name: str, size: dict, ankle: tuple[float, float], toe_lift: float) -> dict:
    """A foot: a heel behind the ankle, a toe in front, flat on the ground.

    A leg that simply stopped at the floor was the last thing keeping these
    figures in the uncanny middle between a person and a post. A foot costs six
    faces and tells a viewer instantly which way somebody is facing.
    """
    length, tall, wide = size["foot_length"], size["foot_height"], size["foot_width"]
    heel = ankle[0] - length * 0.30
    toe = ankle[0] + length * 0.70
    back_half, front_half = wide / 2.0, wide * 0.40
    lateral = ankle[1]
    vertices = [
        (heel, lateral - back_half, 0.0),
        (heel, lateral + back_half, 0.0),
        (toe, lateral + front_half, 0.0),
        (toe, lateral - front_half, 0.0),
        (heel, lateral - back_half, tall),
        (heel, lateral + back_half, tall),
        (toe, lateral + front_half, tall * toe_lift),
        (toe, lateral - front_half, tall * toe_lift),
    ]
    faces = [
        (3, 2, 1, 0),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return _primitive(name, "foot_wedge", COMPLEXION, vertices, faces)


def _pose_frame(pose: str, size: dict) -> dict:
    """Where the limbs and the head sit for one standing attitude.

    Every pose is STANDING. Phase 18 ships no walk cycle, no seating geometry
    and no animation, so a pose is a fixed arrangement of limbs and nothing
    more. What changed with segmented limbs is that the arrangement is now
    VISIBLE: a stride puts one knee forward and swings the opposite arm back,
    and a rest shifts weight onto one leg, where the old rectangular columns
    could only slide sideways.
    """
    hip = size["hip_width"]
    leg_top, torso_top = size["leg_top"], size["torso_top"]
    # The ankle ring sits INSIDE the foot, not on top of it. A foot's upper
    # surface slopes down from heel to toe, so a leg planted at the heel height
    # ends five to eight millimetres above the foot at the point it is supposed
    # to meet it -- a visible gap between the shin and the shoe.
    ankle_z = size["foot_height"] * 0.55
    knee_z = ankle_z + (leg_top - ankle_z) * 0.52
    stance = hip * 0.24
    arm_side = size["shoulder_width"] / 2.0 - size["arm_thickness"] * 0.58
    shoulder_z = torso_top - size["arm_thickness"] * 0.85
    arm = size["arm_length"]
    elbow_z = shoulder_z - arm * 0.46
    wrist_z = shoulder_z - arm * 0.95
    lean = size["lean"]

    frame = {
        "head_turn": 0.0,
        "legs": {
            "left": [(0.0, stance), (0.0, stance * 0.96), (0.0, stance * 0.92)],
            "right": [(0.0, -stance), (0.0, -stance * 0.96), (0.0, -stance * 0.92)],
        },
        "arms": {
            "left": [
                (lean * 0.9, arm_side),
                (lean * 0.5, arm_side * 1.02),
                (lean * 0.2, arm_side * 1.00),
            ],
            "right": [
                (lean * 0.9, -arm_side),
                (lean * 0.5, -arm_side * 1.02),
                (lean * 0.2, -arm_side * 1.00),
            ],
        },
        "leg_levels": (leg_top + size["leg_thickness"] * 0.18, knee_z, ankle_z),
        "arm_levels": (shoulder_z, elbow_z, wrist_z),
        "toe_lift": {"left": 0.62, "right": 0.62},
    }

    stride = leg_top * 0.20
    swing = arm * 0.20
    if pose == "observe":
        frame["head_turn"] = 0.42
        frame["arms"]["left"] = [
            (lean * 0.9, arm_side),
            (lean * 0.5 + size["limb"] * 0.55, arm_side * 1.08),
            (lean * 0.2 + size["limb"] * 1.35, arm_side * 0.82),
        ]
        frame["legs"]["right"] = [(0.0, -stance), (0.0, -stance * 1.04), (0.0, -stance * 1.08)]
    elif pose == "stroll":
        frame["legs"]["left"] = [
            (0.0, stance * 0.86),
            (stride * 0.55, stance * 0.84),
            (stride, stance * 0.80),
        ]
        frame["legs"]["right"] = [
            (0.0, -stance * 0.86),
            (-stride * 0.42, -stance * 0.84),
            (-stride * 0.86, -stance * 0.80),
        ]
        frame["arms"]["left"] = [
            (lean * 0.9, arm_side),
            (lean * 0.5 - swing * 0.55, arm_side * 1.02),
            (lean * 0.2 - swing, arm_side * 0.98),
        ]
        frame["arms"]["right"] = [
            (lean * 0.9, -arm_side),
            (lean * 0.5 + swing * 0.55, -arm_side * 1.02),
            (lean * 0.2 + swing, -arm_side * 0.98),
        ]
        frame["toe_lift"] = {"left": 0.48, "right": 0.78}
    elif pose == "rest":
        frame["head_turn"] = -0.22
        frame["legs"]["left"] = [
            (0.0, stance * 0.94),
            (0.0, stance * 0.88),
            (0.0, stance * 0.84),
        ]
        frame["legs"]["right"] = [
            (0.0, -stance * 1.02),
            (size["limb"] * 0.22, -stance * 1.55),
            (size["limb"] * 0.34, -stance * 1.92),
        ]
        frame["arms"]["right"] = [
            (lean * 0.9, -arm_side),
            (lean * 0.5 + size["limb"] * 0.50, -arm_side * 1.06),
            (lean * 0.2 + size["limb"] * 0.86, -arm_side * 1.10),
        ]
    elif pose != "idle":
        raise FigureKitError(f"unknown pose {pose!r}")
    return frame


def _limbs(identity: dict, size: dict, frame: dict) -> list[dict]:
    """Both arms, both legs and both feet, as tapered chains and wedges."""
    silhouette = _require(identity["clothing"], CLOTHING_SILHOUETTES, "clothing silhouette")
    bare_forearm = silhouette in ("short_sleeve", "dress")
    bare_legs = silhouette in ("short_sleeve", "dress") and identity["age_presentation"] == "child"
    arm_thickness = size["arm_thickness"]
    leg_thickness = size["leg_thickness"]
    primitives: list[dict] = []

    shoulder_z, elbow_z, wrist_z = frame["arm_levels"]
    arm_radii = (arm_thickness * 0.60, arm_thickness * 0.40, arm_thickness * 0.30)
    for side in ("left", "right"):
        points = frame["arms"][side]
        joints = [
            ((points[0][0], points[0][1], shoulder_z), arm_radii[0]),
            ((points[1][0], points[1][1], elbow_z), arm_radii[1]),
            ((points[2][0], points[2][1], wrist_z), arm_radii[2]),
        ]
        if bare_forearm:
            # A short sleeve is a real seam, not a recolour: the sleeve and the
            # bare arm below it are two segments, so the garment reads at
            # distance as a different garment rather than a different shade.
            primitives.append(_tapered_chain(f"{side}_upper_arm", CLOTHING, ARM_SIDES, joints[:2]))
            primitives.append(_tapered_chain(f"{side}_forearm", COMPLEXION, ARM_SIDES, joints[1:]))
        else:
            primitives.append(_tapered_chain(f"{side}_arm", CLOTHING, ARM_SIDES, joints))

    hip_z, knee_z, ankle_z = frame["leg_levels"]
    leg_material = COMPLEXION if bare_legs else CLOTHING
    leg_radii = (leg_thickness * 0.55, leg_thickness * 0.34, leg_thickness * 0.26)
    for side in ("left", "right"):
        points = frame["legs"][side]
        joints = [
            ((points[0][0], points[0][1], hip_z), leg_radii[0]),
            ((points[1][0], points[1][1], knee_z), leg_radii[1]),
            ((points[2][0], points[2][1], ankle_z), leg_radii[2]),
        ]
        primitives.append(_tapered_chain(f"{side}_leg", leg_material, LEG_SIDES, joints))
        primitives.append(_foot_wedge(f"{side}_foot", size, points[2], frame["toe_lift"][side]))
    return primitives


def _accessories(identity: dict, size: dict) -> list[dict]:
    """Garment geometry that sits ON a valid body, never instead of one."""
    silhouette = _require(identity["clothing"], CLOTHING_SILHOUETTES, "clothing silhouette")
    if silhouette != "formal":
        return []
    leg_top, torso_top = size["leg_top"], size["torso_top"]
    span = torso_top - leg_top
    depth = size["torso_depth"]
    lean = size["lean"]
    low = leg_top + span * 0.18
    high = leg_top + span * 0.86
    half = size["waist_width"] * 0.11
    front = lean + depth / 2.0 * 1.02
    vertices = [
        (front, -half, low),
        (front, half, low),
        (front, half, high),
        (front, -half, high),
        (front - 0.030, -half, low),
        (front - 0.030, half, low),
        (front - 0.030, half, high),
        (front - 0.030, -half, high),
    ]
    faces = [
        (0, 1, 2, 3),
        (7, 6, 5, 4),
        (4, 5, 1, 0),
        (5, 6, 2, 1),
        (6, 7, 3, 2),
        (7, 4, 0, 3),
    ]
    return [_primitive("placket", "accessory", ACCENT, vertices, faces)]


def figure_geometry(identity: dict) -> list[dict]:
    """One complete body, as named primitives in body space.

    THE entry point, and the replacement for the box list that made every
    resident look like a voxel character. Assembled from the five independent
    choices in the identity: the skeleton of the call is a torso hull, a neck,
    four tapered limb chains, two feet, a faceted head with its face, and
    whatever hair and garment the identity asked for.
    """
    size = figure_dimensions(identity)
    frame = _pose_frame(identity["pose"], size)
    primitives: list[dict] = [_torso_hull(identity, size), _neck(size)]
    primitives.extend(_limbs(identity, size, frame))
    head = head_frame(size, frame["head_turn"])
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
    frame = head_frame(size, _pose_frame(identity["pose"], size)["head_turn"])
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
    frame = head_frame(size, _pose_frame(identity["pose"], size)["head_turn"])
    return frame, {feature["name"]: feature for feature in head_features(identity, frame)}


def geometry_key(identity: dict) -> tuple:
    """Everything about an identity that changes its MESH.

    Palette and complexion are materials, so two figures that differ only in
    colour share one mesh datablock. Everything else is geometry.
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
