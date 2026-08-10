"""Contract tests for the pure figure kit.

Pure pytest -- no Blender. The kit turns a visual identity into a body with
arithmetic alone, so the questions a Director asks of a crowd can be asked of
the code: is that a child or a short adult, is that one broader than that one,
do two bodies actually differ, and does the same identity always build the
same person.

Since the geometry rebuild these tests also answer a blunter question -- IS
THAT A BOX? -- and they answer it by measuring the vertices the kit emitted.
A body used to be a list of axis-aligned boxes, and every test of it could
only compare one declaration against another. Nothing below reads a constant
back out of the module. Widths are computed from coordinates, tapers from
recovered cross-sections, and the head's roundness from the normals of the
faces that will actually be built.

The kit is a library of VISUAL PRESENTATION ARCHETYPES. Nothing here is a
demographic claim, and nothing here is written into world state.
"""

import importlib
import itertools
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"


def _load(name: str):
    """Import one pure visual module the same way Blender does: by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


kit = _load("figure_kit")

BASE = {
    "age_presentation": "adult",
    "presentation": "unspecified",
    "stature": "average",
    "build": "average",
    "hair": "short",
    "facial_hair": "none",
    "face": "a",
    "clothing": "shirt",
    "palette": "slate",
    "complexion": "c1",
    "hair_tone": "h1",
    "pose": "idle",
}

POSES = ("idle", "observe", "stroll", "rest")


def identity(**overrides) -> dict:
    """One visual identity, defaulting to an unremarkable adult."""
    return {**BASE, **overrides}


def parts(entry: dict) -> dict:
    """One body's primitives, keyed by name."""
    return {item["name"]: item for item in kit.figure_geometry(entry)}


def every_vertex(entry: dict) -> list[tuple[float, float, float]]:
    """Every point of one body, in body space."""
    return [vertex for item in kit.figure_geometry(entry) for vertex in item["vertices"]]


# ---------------------------------------------------------------------------
# Proportions
# ---------------------------------------------------------------------------


def test_every_age_band_sums_to_the_whole_body() -> None:
    """Legs, torso, neck and head account for the entire height, exactly."""
    for age, proportions in sorted(kit.PROPORTIONS.items()):
        total = (
            proportions["leg"] + proportions["torso"] + proportions["neck"] + proportions["head"]
        )
        assert abs(total - 1.0) < 1.0e-9, f"{age} bands sum to {total}"


def test_a_child_is_not_a_scaled_adult() -> None:
    """The head-to-height ratio is the cue, and it is a real difference.

    A uniformly scaled adult keeps its adult head ratio and reads as a distant
    adult. The child's head is one in five and a half; the adult's is one in
    seven and a half.
    """
    child = kit.figure_dimensions(identity(age_presentation="child"))
    adult = kit.figure_dimensions(identity(age_presentation="adult"))
    child_ratio = child["head_height"] / child["height"]
    adult_ratio = adult["head_height"] / adult["height"]
    assert child_ratio > adult_ratio * 1.3, f"{child_ratio} vs {adult_ratio}"
    assert child["leg_top"] / child["height"] < adult["leg_top"] / adult["height"]
    assert child["shoulder_width"] < adult["shoulder_width"] * 0.85


def test_the_tallest_child_is_shorter_than_the_shortest_adult() -> None:
    """No stature combination can blur the two apart."""
    tallest_child = max(
        kit.figure_dimensions(identity(age_presentation="child", stature=stature))["height"]
        for stature in kit.STATURES
    )
    shortest_adult = min(
        kit.figure_dimensions(identity(age_presentation="adult", stature=stature))["height"]
        for stature in kit.STATURES
    )
    assert tallest_child < shortest_adult


def test_stature_changes_height_and_build_does_not() -> None:
    """The two axes are independent, so a tall slim figure is possible."""
    heights = {
        stature: kit.figure_dimensions(identity(stature=stature))["height"]
        for stature in kit.STATURES
    }
    assert heights["short"] < heights["average"] < heights["tall"]
    for build in kit.BUILDS:
        assert kit.figure_dimensions(identity(build=build))["height"] == heights["average"], (
            "build must not change stature"
        )


def test_build_changes_shape_not_only_size() -> None:
    """Athletic is shoulders-over-hips; broad is both; slim is neither."""
    slim = kit.figure_dimensions(identity(build="slim"))
    average = kit.figure_dimensions(identity(build="average"))
    athletic = kit.figure_dimensions(identity(build="athletic"))
    broad = kit.figure_dimensions(identity(build="broad"))
    assert slim["shoulder_width"] < average["shoulder_width"] < broad["shoulder_width"]
    assert broad["torso_depth"] > slim["torso_depth"] * 1.3
    assert athletic["shoulder_width"] / athletic["hip_width"] > (
        broad["shoulder_width"] / broad["hip_width"]
    )
    assert slim["limb"] < broad["limb"]


def test_presentation_changes_only_the_shoulder_to_hip_ratio() -> None:
    """Silhouette, and nothing else -- height and depth are untouched."""
    masculine = kit.figure_dimensions(identity(presentation="masculine"))
    feminine = kit.figure_dimensions(identity(presentation="feminine"))
    assert masculine["height"] == feminine["height"]
    assert masculine["torso_depth"] == feminine["torso_depth"]
    assert masculine["shoulder_width"] > feminine["shoulder_width"]
    assert masculine["hip_width"] < feminine["hip_width"]
    assert (masculine["shoulder_width"] / masculine["hip_width"]) > (
        feminine["shoulder_width"] / feminine["hip_width"]
    )


def test_only_the_elder_leans() -> None:
    """A forward tilt is posture, and only one presentation carries it."""
    for age in kit.AGE_PRESENTATIONS:
        lean = kit.figure_dimensions(identity(age_presentation=age))["lean"]
        assert (lean > 0.0) == (age == "elder")


PUBLISHED_MEASUREMENTS = {
    "child/short/average/unspecified": (1.0695, 0.243846, 0.197857, 0.2139),
    "child/tall/broad/masculine": (1.242, 0.345192, 0.22977, 0.280195),
    "teen/average/slim/feminine": (1.6, 0.302659, 0.2432, 0.295488),
    "adult/average/average/unspecified": (1.75, 0.41125, 0.23275, 0.336),
    "adult/tall/athletic/masculine": (1.89, 0.522587, 0.25137, 0.31723),
    "adult/short/broad/feminine": (1.6275, 0.409044, 0.216458, 0.404974),
    "elder/average/slim/masculine": (1.68, 0.352598, 0.2352, 0.284256),
    "elder/tall/average/feminine": (1.8144, 0.371226, 0.254016, 0.39191),
}
"""GOLDEN values of the four measurements that leave this module, in metres.

``(height, shoulder_width, head_height, hip_width)`` for a spread across every
age band, both stature extremes, every build and every presentation.

These are literals on purpose. The obvious version of this test recomputes the
expected number from ``PROPORTIONS`` and ``BUILD_SHAPE`` and asserts the
function agrees -- which is a tautology: edit a constant and the test edits its
own expectation with it. Only a value frozen OUTSIDE the module can prove the
number did not move.

It matters because ``height``, ``shoulder_width`` and ``head_height`` are
published into the presence plan and hashed, and ``height`` feeds
:func:`silhouette_signature`, which decides which identity may stand next to
which. The geometry rebuild was allowed to change how a body is DRAWN and
nothing about who is standing where; if one of these drifts, the population has
been reshuffled by a change that claimed not to touch it.
"""


def test_the_published_measurements_survived_the_geometry_rebuild() -> None:
    """The four numbers that leave this module are frozen, to the micrometre."""
    for case, expected in sorted(PUBLISHED_MEASUREMENTS.items()):
        age, stature, build, presentation = case.split("/")
        size = kit.figure_dimensions(
            identity(age_presentation=age, stature=stature, build=build, presentation=presentation)
        )
        actual = (
            round(size["height"], 6),
            round(size["shoulder_width"], 6),
            round(size["head_height"], 6),
            round(size["hip_width"], 6),
        )
        assert actual == expected, (
            f"{case} published {actual}, the reviewed candidate had {expected}"
        )


def test_the_golden_measurements_cover_the_whole_vocabulary() -> None:
    """The pin is only worth as much as its coverage."""
    cases = [case.split("/") for case in PUBLISHED_MEASUREMENTS]
    assert {case[0] for case in cases} == set(kit.AGE_PRESENTATIONS)
    assert {case[2] for case in cases} == set(kit.BUILDS)
    assert {case[3] for case in cases} == set(kit.PRESENTATIONS)
    assert {case[1] for case in cases} >= {"short", "tall"}


# ---------------------------------------------------------------------------
# The geometry is geometry
# ---------------------------------------------------------------------------


def test_the_kit_has_no_box_in_its_vocabulary() -> None:
    """The architectural change is real, not a rename.

    Every primitive a body is made of has to be one of the declared geometry
    kinds. There is no box kind to fall back to, so a future edit cannot
    quietly reintroduce the shape this rebuild removed.
    """
    assert "box" not in kit.PRIMITIVE_KINDS
    for age, hair, clothing, pose in itertools.product(
        kit.AGE_PRESENTATIONS, kit.HAIR_VARIANTS, kit.CLOTHING_SILHOUETTES, POSES
    ):
        entry = identity(age_presentation=age, hair=hair, clothing=clothing, pose=pose)
        cuboid = 0
        for item in kit.figure_geometry(entry):
            assert item["kind"] in kit.PRIMITIVE_KINDS
            assert item["vertices"], f"{item['name']} has no geometry"
            assert item["faces"], f"{item['name']} has no faces"
            # MEASURED, not declared: eight vertices and six faces whose normals
            # are all axis-aligned is a box whatever the primitive calls itself.
            normals = kit.face_normals(item)
            axis_aligned = all(
                any(abs(abs(component) - 1.0) < 1.0e-6 for component in normal)
                for normal in normals
            )
            if len(item["vertices"]) == 8 and len(item["faces"]) == 6 and axis_aligned:
                cuboid += 1
        # The formal placket is a flat garment panel, not anatomy, and is the
        # only axis-aligned six-sided piece the vocabulary is allowed to build.
        assert cuboid <= (1 if clothing == "formal" else 0), (
            f"{age}/{clothing} built {cuboid} axis-aligned cuboid primitive(s)"
        )


def test_a_body_reaches_exactly_its_own_height() -> None:
    """Whatever the hair, the tallest geometry is the top of the figure."""
    for age, hair in itertools.product(kit.AGE_PRESENTATIONS, kit.HAIR_VARIANTS):
        entry = identity(age_presentation=age, hair=hair)
        size = kit.figure_dimensions(entry)
        top = max(vertex[2] for vertex in every_vertex(entry))
        assert size["height"] - 1.0e-9 <= top <= size["height"] * 1.10, (
            f"{age}/{hair} reaches {top} against a height of {size['height']}"
        )


def test_every_body_stands_on_the_ground() -> None:
    """No vertex dips below the origin, which is where the soles are."""
    for age, pose in itertools.product(kit.AGE_PRESENTATIONS, POSES):
        entry = identity(age_presentation=age, pose=pose)
        lowest = min(vertex[2] for vertex in every_vertex(entry))
        assert lowest >= -1.0e-9, f"{age}/{pose} has geometry {lowest}m below the feet"
        assert lowest < 1.0e-9, f"{age}/{pose} hovers {lowest}m above the ground"


# ---------------------------------------------------------------------------
# 34: machine-proved anatomy. None of this can be satisfied by a box.
# ---------------------------------------------------------------------------


def test_the_head_is_not_a_cuboid() -> None:
    """Measured three ways, because this is the defect that shipped.

    A cuboid has six faces and six distinct normals, every one of them
    axis-aligned, and one constant cross-section from bottom to top. The skull
    has to fail all three descriptions for every figure the kit can build.
    """
    for age, face in itertools.product(kit.AGE_PRESENTATIONS, kit.FACE_VARIANTS):
        skull = parts(identity(age_presentation=age, face=face))["skull"]
        normals = kit.face_normals(skull)
        distinct = {tuple(round(component, 4) for component in normal) for normal in normals}
        assert len(skull["faces"]) > 6, f"a {age} skull has {len(skull['faces'])} faces"
        assert len(distinct) > 6, f"a {age} skull has only {len(distinct)} distinct normals"
        off_axis = [
            normal
            for normal in normals
            if sum(1 for component in normal if abs(abs(component) - 1.0) < 1.0e-6) == 0
        ]
        assert len(off_axis) >= len(normals) * 0.5, "most of a skull's faces are axis-aligned"


def test_the_head_narrows_to_a_jaw_and_closes_over_a_crown() -> None:
    """A real profile, recovered from the built rings.

    The widest section must sit above the jaw and below the crown, and both
    ends must come to a point -- which is what separates a head from a barrel.
    """
    for age in kit.AGE_PRESENTATIONS:
        entry = identity(age_presentation=age)
        size = kit.figure_dimensions(entry)
        frame = kit.head_frame(size, 0.0)
        skull = parts(entry)["skull"]
        rings = kit.ring_sections(skull, kit.HEAD_SIDES)
        assert len(rings) >= 3, "a skull needs several cross-sections"
        widths = [ring["width"] for ring in rings]
        widest = widths.index(max(widths))
        assert widest > 0, f"a {age} skull is widest at its lowest ring"
        assert widest < len(widths) - 1, f"a {age} skull is widest at its highest ring"
        assert widths[0] < max(widths) * 0.75, "the jaw does not narrow"
        assert widths[-1] < max(widths), "the crown does not close over"
        bounds = kit.primitive_bounds(skull)
        assert bounds["z"][0] <= frame["origin"][2] + 1.0e-9
        assert abs(bounds["z"][1] - (frame["origin"][2] + frame["height"])) < 1.0e-9


def test_the_head_reads_differently_front_and_back() -> None:
    """A face is flatter than an occiput, so a silhouette carries a heading."""
    for age in kit.AGE_PRESENTATIONS:
        entry = identity(age_presentation=age)
        size = kit.figure_dimensions(entry)
        frame = kit.head_frame(size, 0.0)
        skull = parts(entry)["skull"]
        forward = max(vertex[0] for vertex in skull["vertices"]) - frame["origin"][0]
        backward = frame["origin"][0] - min(vertex[0] for vertex in skull["vertices"])
        assert backward > forward * 1.05, (
            f"a {age} head is symmetric front to back: {forward} vs {backward}"
        )


def test_the_torso_is_one_hull_with_four_real_cross_sections() -> None:
    """Hip out, waist in, chest out. Not a stack of slabs.

    Widths are measured from the emitted rings, so a torso that merely
    DECLARED a waist would produce vertices that fail here.
    """
    for build in kit.BUILDS:
        torso = parts(identity(build=build))["torso"]
        assert torso["kind"] == "torso_hull"
        rings = kit.ring_sections(torso, kit.TORSO_SIDES)
        assert len(rings) >= 4, f"a {build} torso has {len(rings)} cross-sections"
        hip, waist, chest, shoulder = rings[0], rings[1], rings[2], rings[-1]
        assert hip["z"] < waist["z"] < chest["z"] < shoulder["z"]
        assert waist["width"] < hip["width"] * 0.98, f"{build} has no waist against its hip"
        assert waist["width"] < chest["width"] * 0.98, f"{build} has no waist against its chest"
        assert abs(shoulder["width"] - waist["width"]) > waist["width"] * 0.05, (
            f"{build} shoulders and waist are the same width"
        )
        assert len({round(ring["width"], 4) for ring in rings}) >= 3, (
            f"a {build} torso repeats its cross-section"
        )


def test_build_drives_the_built_torso_and_not_only_a_number() -> None:
    """Athletic tapers hardest; broad tapers least and is deepest."""
    measured = {}
    for build in kit.BUILDS:
        entry = identity(build=build)
        rings = kit.ring_sections(parts(entry)["torso"], kit.TORSO_SIDES)
        measured[build] = {
            "waist": rings[1]["width"],
            "chest": rings[2]["width"],
            "depth": max(ring["depth"] for ring in rings),
        }
    taper = {build: value["chest"] / value["waist"] for build, value in measured.items()}
    assert taper["athletic"] > taper["average"] > taper["broad"], taper
    assert measured["broad"]["depth"] > measured["slim"]["depth"] * 1.3
    assert measured["broad"]["waist"] > measured["slim"]["waist"]


def test_an_arm_has_an_upper_arm_a_forearm_and_an_elbow() -> None:
    """Three cross-sections, thinning downward, with a real change of direction."""
    for pose in POSES:
        limbs = parts(identity(pose=pose))
        for side in ("left", "right"):
            arm = limbs[f"{side}_arm"]
            assert arm["kind"] == "tapered_segment"
            rings = kit.ring_sections(arm, kit.ARM_SIDES)
            assert len(rings) == 3, f"{side} arm has {len(rings)} sections"
            shoulder, elbow, wrist = rings
            assert shoulder["z"] > elbow["z"] > wrist["z"]
            assert shoulder["radius"] > elbow["radius"] * 1.10, "the upper arm is not thicker"
            assert elbow["radius"] > wrist["radius"] * 1.10, "the forearm does not taper"


def test_a_leg_has_a_thigh_a_lower_leg_and_a_knee() -> None:
    """The same proof for the legs, which also have to beat the arms."""
    for pose in POSES:
        entry = identity(pose=pose)
        limbs = parts(entry)
        for side in ("left", "right"):
            rings = kit.ring_sections(limbs[f"{side}_leg"], kit.LEG_SIDES)
            assert len(rings) == 3, f"{side} leg has {len(rings)} sections"
            hip, knee, ankle = rings
            assert hip["z"] > knee["z"] > ankle["z"]
            assert hip["radius"] > knee["radius"] * 1.15, "the thigh is not thicker than the shin"
            assert knee["radius"] > ankle["radius"] * 1.15, "the shin does not narrow to an ankle"
            arm = kit.ring_sections(limbs[f"{side}_arm"], kit.ARM_SIDES)
            assert hip["radius"] > arm[0]["radius"], "a thigh must be thicker than an upper arm"


def test_a_stride_actually_bends_the_limbs() -> None:
    """A pose has to move geometry, not just a label.

    Idle stands square; stroll puts one knee in front of its own hip and
    swings the opposite arm the other way. Both are read off the recovered
    joint centres.
    """
    idle = parts(identity(pose="idle"))
    stroll = parts(identity(pose="stroll"))
    idle_knee = kit.ring_sections(idle["left_leg"], kit.LEG_SIDES)[1]["center"][0]
    stroll_rings = kit.ring_sections(stroll["left_leg"], kit.LEG_SIDES)
    assert abs(idle_knee) < 1.0e-9, "an idle knee should sit under its hip"
    assert stroll_rings[2]["center"][0] > stroll_rings[0]["center"][0] + 0.05, (
        "a stride does not put the leading ankle in front of its hip"
    )
    right = kit.ring_sections(stroll["right_leg"], kit.LEG_SIDES)
    assert right[2]["center"][0] < right[0]["center"][0] - 0.05, "both legs lead"
    left_wrist = kit.ring_sections(stroll["left_arm"], kit.ARM_SIDES)[2]["center"][0]
    assert left_wrist < 0.0, "the arm opposite the leading leg does not counter-swing"


def test_every_body_has_two_feet_that_point_forward() -> None:
    """Feet exist, reach in front of the ankle, and stand on the ground."""
    for age, pose in itertools.product(kit.AGE_PRESENTATIONS, POSES):
        entry = identity(age_presentation=age, pose=pose)
        limbs = parts(entry)
        for side in ("left", "right"):
            foot = limbs[f"{side}_foot"]
            assert foot["kind"] == "foot_wedge"
            bounds = kit.primitive_bounds(foot)
            ankle = kit.ring_sections(limbs[f"{side}_leg"], kit.LEG_SIDES)[2]
            assert abs(bounds["z"][0]) < 1.0e-9, f"{side} foot is not on the ground"
            assert bounds["z"][1] > 0.0
            forward = bounds["x"][1] - ankle["center"][0]
            behind = ankle["center"][0] - bounds["x"][0]
            assert forward > behind * 1.4, (
                f"a {age} {side} foot does not project forward: {forward} vs {behind}"
            )
            # Against the foot's top surface UNDER THE ANKLE, not against its
            # bounding box. A foot's top slopes down from heel to toe, and its
            # AABB maximum is the heel corner -- a value the ankle equalled by
            # construction, so the box comparison passed while every ankle
            # floated five to eight millimetres above its own foot.
            heel = min(point[0] for point in foot["vertices"])
            toe = max(point[0] for point in foot["vertices"])
            heel_top = max(p[2] for p in foot["vertices"] if abs(p[0] - heel) < 1.0e-9)
            toe_top = max(p[2] for p in foot["vertices"] if abs(p[0] - toe) < 1.0e-9)
            along = (ankle["center"][0] - heel) / (toe - heel)
            surface = heel_top + (toe_top - heel_top) * along
            assert ankle["z"] < surface, (
                f"a {age} {side} ankle floats {ankle['z'] - surface:.4f}m above its own foot"
            )


def test_the_neck_is_narrower_than_the_head_and_the_shoulders() -> None:
    """A neck, not a peg, and not a pillar wider than what it carries."""
    for age in kit.AGE_PRESENTATIONS:
        entry = identity(age_presentation=age)
        size = kit.figure_dimensions(entry)
        neck = parts(entry)["neck"]
        assert neck["kind"] == "tapered_segment"
        bounds = kit.primitive_bounds(neck)
        width = bounds["y"][1] - bounds["y"][0]
        assert width < size["head_width"], "the neck is wider than the head"
        assert width < size["shoulder_width"] * 0.6, "the neck is not narrower than the shoulders"
        rings = kit.ring_sections(neck, kit.NECK_SIDES)
        assert rings[0]["radius"] > rings[-1]["radius"], "the neck does not taper into the head"


def test_the_anatomy_guards_would_reject_a_box_body() -> None:
    """Proven, not assumed: the new checks bite on the shape they replaced.

    Builds the geometry the old kit produced -- an axis-aligned cuboid skull
    and a straight column limb -- and requires the same arithmetic the tests
    above use to reject both.
    """
    cuboid = {
        "name": "skull",
        "kind": "faceted_head",
        "material": kit.COMPLEXION,
        "vertices": (
            (-0.1, -0.1, 0.0),
            (0.1, -0.1, 0.0),
            (0.1, 0.1, 0.0),
            (-0.1, 0.1, 0.0),
            (-0.1, -0.1, 0.2),
            (0.1, -0.1, 0.2),
            (0.1, 0.1, 0.2),
            (-0.1, 0.1, 0.2),
        ),
        "faces": (
            (3, 2, 1, 0),
            (4, 5, 6, 7),
            (0, 1, 5, 4),
            (1, 2, 6, 5),
            (2, 3, 7, 6),
            (3, 0, 4, 7),
        ),
    }
    normals = kit.face_normals(cuboid)
    distinct = {tuple(round(component, 4) for component in normal) for normal in normals}
    assert len(cuboid["faces"]) == 6 and len(distinct) == 6, "the fixture is not a cuboid"
    off_axis = [
        normal
        for normal in normals
        if sum(1 for component in normal if abs(abs(component) - 1.0) < 1.0e-6) == 0
    ]
    assert not off_axis, "a cuboid must have no off-axis faces to be rejected by"

    column = kit._tapered_chain(
        "column", kit.CLOTHING, kit.LEG_SIDES, [((0.0, 0.0, 1.0), 0.05), ((0.0, 0.0, 0.0), 0.05)]
    )
    rings = kit.ring_sections(column, kit.LEG_SIDES)
    assert not rings[0]["radius"] > rings[-1]["radius"] * 1.15, (
        "an untapered column must fail the limb taper check"
    )


# ---------------------------------------------------------------------------
# Variety
# ---------------------------------------------------------------------------


def test_every_body_carries_a_face() -> None:
    """Brow, both eyes, a nose and a mouth, named and standing proud.

    Deliberately NOT a primitive count. The version of this test that counted
    boxes above the neck passed for every figure in a candidate whose eyes were
    sealed inside the skull; the face contract is verified by name and by
    measured clearance in ``test_face_contract.py``, and this is its summary.
    """
    for age, face in itertools.product(kit.AGE_PRESENTATIONS, kit.FACE_VARIANTS):
        entry = identity(age_presentation=age, face=face)
        frame, features = kit.head_probe(entry)
        for required in ("brow", "left_eye", "right_eye", "nose", "mouth"):
            assert required in features, f"{age}/{face} has no {required}"
            assert kit.plate_clearance(frame, features[required]) > 0.0, (
                f"{age}/{face} {required} is buried inside the head"
            )


def test_faces_actually_differ() -> None:
    """Four variants must not be four copies."""
    built = {face: kit.figure_mesh(identity(face=face))["vertices"] for face in kit.FACE_VARIANTS}
    for first, second in itertools.combinations(kit.FACE_VARIANTS, 2):
        assert built[first] != built[second], f"faces {first} and {second} are identical"


def test_hair_changes_the_silhouette_not_just_the_colour() -> None:
    """Every haircut must alter geometry; a recoloured shell is not a variant."""
    built = {hair: kit.figure_geometry(identity(hair=hair)) for hair in kit.HAIR_VARIANTS}
    assert len(built["bald"]) < len(built["short"]), "bald must remove geometry"
    for first, second in itertools.combinations(kit.HAIR_VARIANTS, 2):
        assert built[first] != built[second], f"hair {first} and {second} are identical"


def test_clothing_changes_the_silhouette_not_just_the_colour() -> None:
    """Every garment must alter geometry too."""
    built = {
        name: kit.figure_geometry(identity(clothing=name)) for name in kit.CLOTHING_SILHOUETTES
    }
    for first, second in itertools.combinations(kit.CLOTHING_SILHOUETTES, 2):
        assert built[first] != built[second], f"clothing {first} and {second} are identical"
    assert len(built["short_sleeve"]) > len(built["shirt"]), "a bare forearm is extra geometry"
    hem = kit.ring_sections(
        {item["name"]: item for item in built["coat"]}["torso"], kit.TORSO_SIDES
    )
    plain = kit.ring_sections(
        {item["name"]: item for item in built["shirt"]}["torso"], kit.TORSO_SIDES
    )
    assert len(hem) > len(plain), "a coat must lengthen the same body, not add another one"
    assert hem[0]["z"] < plain[0]["z"], "a coat hem must reach below a shirt"


def test_facial_hair_only_appears_when_asked_for() -> None:
    """And when it does, it adds geometry."""
    plain = kit.figure_geometry(identity(facial_hair="none"))
    for growth in ("beard", "moustache"):
        assert len(kit.figure_geometry(identity(facial_hair=growth))) > len(plain)


def test_poses_move_limbs_and_nothing_else_matters() -> None:
    """Four standing attitudes, each a different arrangement."""
    built = {pose: kit.figure_mesh(identity(pose=pose))["vertices"] for pose in POSES}
    for first, second in itertools.combinations(built, 2):
        assert built[first] != built[second], f"poses {first} and {second} are identical"


# ---------------------------------------------------------------------------
# Cost and determinism
# ---------------------------------------------------------------------------


MAX_TRIANGLES_PER_FIGURE = 430
"""The declared geometry budget for one body.

The correction directive set a ceiling of 30,000 triangles for the canonical
eighty-person scene and asked for roughly 250-350 a person. The heaviest body
the vocabulary can build -- a broad tall elder in a dress with tied hair and a
beard -- costs 426, the canonical eighty average 372, and the layer totals
29,728.

That is the honest number and it is above the directive's preferred band. The
budget went on the two things a reviewer inspects: eight facets around every
skull, and face features that follow the curve of it. The torso and the hair
were cut to six facets to pay for it, which is invisible at diorama distance
and is why the ceiling is met rather than argued with.
"""


def test_no_body_exceeds_the_geometry_budget() -> None:
    """Every combination the vocabulary permits, measured."""
    worst = 0
    heaviest = None
    for age, hair, growth, clothing, pose in itertools.product(
        kit.AGE_PRESENTATIONS, kit.HAIR_VARIANTS, kit.FACIAL_HAIR, kit.CLOTHING_SILHOUETTES, POSES
    ):
        entry = identity(
            age_presentation=age, hair=hair, facial_hair=growth, clothing=clothing, pose=pose
        )
        count = kit.figure_triangles(entry)
        if count > worst:
            worst, heaviest = count, (age, hair, growth, clothing, pose)
    assert worst <= MAX_TRIANGLES_PER_FIGURE, f"{heaviest} costs {worst} triangles"


def test_the_triangle_count_matches_the_faces_that_will_be_built() -> None:
    """The budget is counted the way Blender counts it, not estimated."""
    entry = identity(hair="tied", clothing="coat", facial_hair="beard")
    mesh = kit.figure_mesh(entry)
    assert kit.figure_triangles(entry) == sum(len(face) - 2 for face in mesh["faces"])
    assert len(mesh["faces"]) == len(mesh["materials"])
    assert max(index for face in mesh["faces"] for index in face) == len(mesh["vertices"]) - 1


def test_the_same_identity_always_builds_the_same_body() -> None:
    """No randomness anywhere in the kit."""
    entry = identity(age_presentation="elder", hair="tied", clothing="coat", pose="stroll")
    assert kit.figure_geometry(entry) == kit.figure_geometry(entry)
    assert kit.figure_dimensions(entry) == kit.figure_dimensions(entry)


def test_the_geometry_key_ignores_colour_and_nothing_else() -> None:
    """Two figures differing only in palette share a mesh; anything else does not."""
    base = identity()
    assert kit.geometry_key(base) == kit.geometry_key(identity(palette="rust"))
    assert kit.geometry_key(base) == kit.geometry_key(identity(complexion="c4"))
    assert kit.geometry_key(base) == kit.geometry_key(identity(hair_tone="h3"))
    for axis, value in (
        ("age_presentation", "child"),
        ("stature", "tall"),
        ("build", "broad"),
        ("hair", "long"),
        ("clothing", "coat"),
        ("pose", "stroll"),
        ("face", "c"),
        ("presentation", "feminine"),
        ("facial_hair", "beard"),
    ):
        assert kit.geometry_key(base) != kit.geometry_key(identity(**{axis: value})), axis


def test_the_geometry_key_really_does_predict_the_mesh() -> None:
    """The sharing contract, checked against the geometry rather than assumed.

    Two identities with the same geometry key must build byte-identical
    vertices, or reusing a mesh datablock between them would silently reshape
    somebody.
    """
    base = identity()
    for axis, value in (("palette", "rust"), ("complexion", "c4"), ("hair_tone", "h3")):
        other = identity(**{axis: value})
        assert kit.geometry_key(base) == kit.geometry_key(other)
        assert kit.figure_mesh(base)["vertices"] == kit.figure_mesh(other)["vertices"]


def test_the_silhouette_signature_ignores_what_a_viewer_cannot_see() -> None:
    """Local diversity compares what reads at distance, not every last detail."""
    base = identity()
    assert kit.silhouette_signature(base) == kit.silhouette_signature(identity(face="d"))
    assert kit.silhouette_signature(base) == kit.silhouette_signature(identity(complexion="c5"))
    assert kit.silhouette_signature(base) != kit.silhouette_signature(identity(build="broad"))
    assert kit.silhouette_signature(base) != kit.silhouette_signature(identity(hair="long"))
    assert kit.silhouette_signature(base) != kit.silhouette_signature(identity(palette="rust"))
    assert kit.silhouette_signature(base) != kit.silhouette_signature(
        identity(age_presentation="child")
    )


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("axis", "value"),
    [
        ("age_presentation", "toddler"),
        ("stature", "enormous"),
        ("build", "muscular"),
        ("presentation", "other"),
        ("hair", "mohawk"),
        ("facial_hair", "sideburns"),
        ("face", "z"),
        ("clothing", "armour"),
        ("pose", "running"),
    ],
)
def test_an_unknown_value_is_refused(axis: str, value: str) -> None:
    """A body assembled from a value nobody defined is a body nobody designed."""
    with pytest.raises(kit.FigureKitError):
        kit.figure_geometry(identity(**{axis: value}))


def test_an_unknown_primitive_kind_is_refused() -> None:
    """The vocabulary is closed, so a box cannot be smuggled back in."""
    with pytest.raises(kit.FigureKitError):
        kit._primitive("smuggled", "box", kit.CLOTHING, [(0.0, 0.0, 0.0)], [(0,)])


def test_the_kit_never_claims_a_demographic_fact() -> None:
    """The vocabulary is presentation; no word in it asserts what someone IS."""
    forbidden = {"male", "female", "man", "woman", "boy", "girl", "father", "mother", "family"}
    vocabulary = {
        *kit.AGE_PRESENTATIONS,
        *kit.PRESENTATIONS,
        *kit.STATURES,
        *kit.BUILDS,
        *kit.HAIR_VARIANTS,
        *kit.FACIAL_HAIR,
        *kit.CLOTHING_SILHOUETTES,
        *kit.PRIMITIVE_KINDS,
    }
    assert not (vocabulary & forbidden), f"the vocabulary asserts {sorted(vocabulary & forbidden)}"
    assert math.isfinite(kit.HAIRLINE)
