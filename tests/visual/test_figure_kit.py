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
    "child/short/average/unspecified": (1.0695, 0.240637, 0.2139, 0.219247),
    "child/tall/broad/masculine": (1.242, 0.356578, 0.2484, 0.276405),
    "teen/average/slim/feminine": (1.6, 0.297792, 0.2576, 0.311904),
    "adult/average/average/unspecified": (1.75, 0.42875, 0.259, 0.3325),
    "adult/tall/athletic/masculine": (1.89, 0.580665, 0.27972, 0.303942),
    "adult/short/broad/feminine": (1.6275, 0.416282, 0.24087, 0.415969),
    "elder/average/slim/masculine": (1.68, 0.377288, 0.25872, 0.275426),
    "elder/tall/average/feminine": (1.8144, 0.378847, 0.279418, 0.409546),
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
which.

RE-BAKED for Visual DNA v2, deliberately and once. Every ``height`` is
bit-identical to the shipped candidate's -- height buckets the signature and
drives every Phase 19 speed and route, so moving it would reshuffle the
population. The other three ARE the v2 redesign: the remediation authorised a
drawn-body overhaul, the per-age head fractions, build spreads and
presentation biases all changed by design, and the precondition audit proved
nothing derives a position or a route from them. These tuples were measured
from the v2 kit on 2026-08-16 and frozen again; the next drift is once more a
bug until argued otherwise.
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


def test_the_torso_is_one_hull_with_six_real_cross_sections() -> None:
    """Seat, pelvic crest, waist, chest, clavicle, shoulder. Not a stack of slabs.

    The v2 hull carries six designed rings, bottom to top, and a garment hem
    makes seven. Widths are measured from the emitted rings, so a torso that
    merely DECLARED a waist would produce vertices that fail here. The pelvic
    crest is the ring the hips are read from -- it is the fullest of the two
    seat rings -- and the waist has to pinch against both it and the chest.
    """
    for build in kit.BUILDS:
        torso = parts(identity(build=build))["torso"]
        assert torso["kind"] == "torso_hull"
        rings = kit.ring_sections(torso, kit.TORSO_SIDES)
        assert len(rings) >= 6, f"a {build} torso has {len(rings)} cross-sections"
        hip, waist, chest, shoulder = rings[1], rings[2], rings[3], rings[-1]
        assert hip["z"] < waist["z"] < chest["z"] < shoulder["z"]
        assert waist["width"] < hip["width"] * 0.98, f"{build} has no waist against its hip"
        assert waist["width"] < chest["width"] * 0.98, f"{build} has no waist against its chest"
        assert shoulder["width"] < chest["width"] * 0.95, (
            f"{build} chest runs straight into its shoulder line"
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
            "waist": rings[2]["width"],
            "chest": rings[3]["width"],
            "depth": max(ring["depth"] for ring in rings),
        }
    taper = {build: value["chest"] / value["waist"] for build, value in measured.items()}
    assert taper["athletic"] > taper["average"] > taper["broad"], taper
    assert measured["broad"]["depth"] > measured["slim"]["depth"] * 1.3
    assert measured["broad"]["waist"] > measured["slim"]["waist"]


ARM_MEMBER_RINGS = {"upper_arm": 3, "forearm": 2, "hand": 4}
"""How many lofted rings each member of one arm is built from.

The hand carries FOUR -- wrist, knuckle, fingers, tip -- and that is the
whole of it costing 40 triangles rather than 16. At two rings it was a
tapered stub cut off square, which a blind review read exactly as built:
"amputated at the wrist ... a flat one-sided flap with no thickness". The
four rings give it a knuckle that swells wider and much deeper than the
wrist, a finger section that holds that depth, and a tip that closes to
about half the previous ring's width instead of ending on a full-width
face. A hand reads as a hand because it is rounded off, not because it is
detailed.

The upper arm carries THREE: a socket tucked up inside the shoulder, the
deltoid that carries the silhouette out to the full shoulder width, and the
elbow. The socket closes the armpit -- an upper arm that began at its own
deltoid left a gap between the widest part of the arm and the torso it hangs
from -- and it rides articulation level 0 with the deltoid, so it stays
welded into the body while the arm swings.

There was briefly a fourth ring, a collar above the socket, and it is worth
recording why it went. It existed only to hold the deltoid hinge's rest
dihedral under Blender's 40-degree bevel angle limit, and once the figure
bevel stopped consulting angles at all it bought nothing -- while measurably
costing the shoulder pad a reviewer reported: a 51.8-degree convex ridge
standing at the full published shoulder width, with a 28mm overhanging wall
beneath it. Removing it restores a single straight 42-degree run from the
neck to the arm. See the budget docstring in the Blender-side population
suite for the bevel dependency this removal rests on.
"""


def test_an_arm_has_an_upper_arm_a_forearm_and_an_elbow() -> None:
    """Three members whose seams are the same circle, thinning joint to joint.

    The v2 arm is the chain contract's arm: an upper arm of three rings, a
    forearm of two and a hand of four, with the elbow and wrist seams built
    COINCIDENT so no articulation can pull a sleeve off the arm inside it.

    The taper is measured at the JOINTS -- deltoid over elbow, elbow over
    wrist -- because those are the radii a silhouette reads. The socket ring
    above the deltoid is deliberately the narrowest of the three and is
    excluded from the taper: it is a junction buried in the shoulder, not a
    cross-section of the visible arm, and asserting a monotonic taper from the
    top would refuse the very ring that closes the armpit.
    """
    for pose in POSES:
        limbs = parts(identity(pose=pose))
        for side in ("left", "right"):
            members = {name: limbs[f"{side}_{name}"] for name in ARM_MEMBER_RINGS}
            for name, member in sorted(members.items()):
                assert member["kind"] == "tapered_segment"
                assert len(kit.ring_sections(member, kit.ARM_SIDES)) == ARM_MEMBER_RINGS[name], (
                    f"{member['name']} does not hold {ARM_MEMBER_RINGS[name]} rings"
                )
            upper = kit.ring_sections(members["upper_arm"], kit.ARM_SIDES)
            fore = kit.ring_sections(members["forearm"], kit.ARM_SIDES)
            # Built order, top down: socket, deltoid, elbow. The DELTOID is
            # the chain's root joint -- CHAIN_SPEC publishes it as
            # ("upper_arm", 1) -- and the socket above it is the narrower
            # band that tucks up into the shoulder.
            socket, deltoid, elbow = upper
            root, middle, _tip = kit.CHAIN_SPEC["arm"]["joints"]
            assert root == ("upper_arm", 1) and middle == ("upper_arm", 2), (
                "the arm's joints moved; this test is reading the wrong rings"
            )
            wrist = fore[1]
            assert (
                members["upper_arm"]["vertices"][-kit.ARM_SIDES :]
                == (members["forearm"]["vertices"][: kit.ARM_SIDES])
            ), f"the {side} elbow seam is not one circle of vertices"
            assert (
                members["forearm"]["vertices"][-kit.ARM_SIDES :]
                == (members["hand"]["vertices"][: kit.ARM_SIDES])
            ), f"the {side} wrist seam is not one circle of vertices"
            assert socket["z"] > deltoid["z"] > elbow["z"] > wrist["z"]
            assert socket["radius"] < deltoid["radius"], (
                f"the {side} socket is not tucked inside its own deltoid"
            )
            assert deltoid["radius"] > elbow["radius"] * 1.10, "the upper arm is not thicker"
            assert elbow["radius"] > wrist["radius"] * 1.10, "the forearm does not taper"


def test_the_arm_chain_contract_describes_the_arm_that_is_built() -> None:
    """Phase 19 reads the table; the table has to describe the geometry.

    ``CHAIN_SPEC`` is the ONE published account of what a limb is made of, and
    mobility rebuilds every walker's arm from it without looking at the kit.
    So the declared ring counts are checked against the rings actually
    recovered from the emitted vertices, and the declared joints are checked
    to be the deltoid, the elbow and the wrist -- a table that drifted from
    the build would articulate a body nobody drew.
    """
    spec = kit.CHAIN_SPEC["arm"]
    assert spec["sides"] == kit.ARM_SIDES
    assert {name: len(levels) for name, levels in spec["members"].items()} == ARM_MEMBER_RINGS
    assert spec["joints"] == (("upper_arm", 1), ("upper_arm", 2), ("forearm", 1))
    assert spec["foot"] is None
    limbs = parts(identity())
    for name, levels in sorted(spec["members"].items()):
        rings = kit.ring_sections(limbs[f"left_{name}"], spec["sides"])
        assert len(rings) == len(levels), (
            f"{name} builds {len(rings)} rings, declares {len(levels)}"
        )
    # The socket shares the deltoid's articulation level, which is what keeps
    # it welded into the shoulder while the arm swings about the deltoid.
    assert spec["members"]["upper_arm"][0] == spec["members"]["upper_arm"][1] == 0


def test_a_leg_has_a_thigh_a_lower_leg_and_a_knee() -> None:
    """The same proof for the legs, which also have to beat the arms.

    Five rings now -- hip, thigh, knee, calf, ankle -- and the taper is
    asserted at the JOINTS only, because the calf ring below the knee is
    DELIBERATELY fuller than the knee's pinch: a knee that is a real waist
    between a thigh and a calf is what lets a bent leg read as bent. A
    monotonic-taper assertion here would refuse the designed calf.
    """
    for pose in POSES:
        entry = identity(pose=pose)
        limbs = parts(entry)
        for side in ("left", "right"):
            rings = kit.ring_sections(limbs[f"{side}_leg"], kit.LEG_SIDES)
            assert len(rings) == 5, f"{side} leg has {len(rings)} sections"
            hip, knee, ankle = rings[0], rings[2], rings[4]
            assert hip["z"] > knee["z"] > ankle["z"]
            assert hip["radius"] > knee["radius"] * 1.15, "the thigh is not thicker than the knee"
            assert knee["radius"] > ankle["radius"] * 1.15, "the shin does not narrow to an ankle"
            for below in (3,):
                assert rings[below]["radius"] > knee["radius"], (
                    f"{side} ring {below} does not swell below the knee, so the knee is not a "
                    "pinch and a bent leg will not read as bent"
                )
            arm = kit.ring_sections(limbs[f"{side}_upper_arm"], kit.ARM_SIDES)
            assert hip["radius"] > arm[0]["radius"], "a thigh must be thicker than an upper arm"


def test_a_stride_actually_bends_the_limbs() -> None:
    """A pose has to move geometry, not just a label.

    Stroll puts one ankle in front of its own hip and swings the opposite arm
    the other way, both read off the recovered joint centres. Idle no longer
    stands plumb: the v2 stance gives every idle knee a small DESIGNED forward
    set, because a body of dead-vertical dowels reads as a mannequin -- so the
    idle knee is asserted into a positive band rather than onto zero.
    """
    idle = parts(identity(pose="idle"))
    stroll = parts(identity(pose="stroll"))
    height = kit.figure_dimensions(identity())["height"]
    idle_knee = kit.ring_sections(idle["left_leg"], kit.LEG_SIDES)[2]["center"][0]
    stroll_rings = kit.ring_sections(stroll["left_leg"], kit.LEG_SIDES)
    assert 0.0 < idle_knee <= 0.02 * height, (
        f"an idle knee should carry a small designed set, not {idle_knee}"
    )
    assert stroll_rings[4]["center"][0] > stroll_rings[0]["center"][0] + 0.05, (
        "a stride does not put the leading ankle in front of its hip"
    )
    right = kit.ring_sections(stroll["right_leg"], kit.LEG_SIDES)
    assert right[4]["center"][0] < right[0]["center"][0] - 0.05, "both legs lead"
    left_wrist = kit.ring_sections(stroll["left_forearm"], kit.ARM_SIDES)[1]["center"][0]
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
            # The TIP joint, which CHAIN_SPEC["leg"]["joints"] publishes as
            # ("leg", 4). Reading the ankle from the calf ring instead put it
            # at z=0.29 against a foot topping out at 0.06, so the foot check
            # silently measured the wrong joint entirely -- which is why the
            # index is taken from the contract rather than counted by hand.
            ankle = kit.ring_sections(limbs[f"{side}_leg"], kit.LEG_SIDES)[4]
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
# v2 bands: the redesign is held inside declared limits, not trusted to taste
# ---------------------------------------------------------------------------


HEAD_RATIO_BANDS = {
    "child": (0.16, 0.21),
    "teen": (0.14, 0.17),
    "adult": (0.13, 0.16),
    "elder": (0.13, 0.17),
}
"""How much of a body's height its head may claim, per age presentation.

The v2 kit measures child 0.200, teen 0.161, adult 0.148 and elder 0.154, and
the bands hold those with real headroom on both sides. The limits are the
point: the ceiling near 0.21 is the BOBBLEHEAD line, past which a figure reads
as a toy, and the floor at 0.13 is the PINHEAD line, past which it reads as a
mannequin. A redesign may move a head fraction inside its band without a test
edit; moving one outside is a claim about the whole silhouette language and
has to arrive as a band change a reviewer can see.
"""


def test_every_head_stays_inside_its_age_band() -> None:
    """Neither bobblehead nor pinhead, for any stature or build."""
    assert set(HEAD_RATIO_BANDS) == set(kit.AGE_PRESENTATIONS)
    for age, (low, high) in sorted(HEAD_RATIO_BANDS.items()):
        for stature, build in itertools.product(kit.STATURES, kit.BUILDS):
            size = kit.figure_dimensions(
                identity(age_presentation=age, stature=stature, build=build)
            )
            ratio = size["head_height"] / size["height"]
            assert low <= ratio <= high, (
                f"a {stature} {build} {age} carries a head ratio of {ratio:.4f}, "
                f"outside ({low}, {high})"
            )


def test_the_drawn_skull_obeys_the_measurements_it_declares() -> None:
    """The published head numbers describe the geometry that gets built.

    ``head_height`` and ``head_width`` leave this module in the presence plan,
    so a skull drawn larger than it declares would be a body lying about its
    own silhouette. The width allowance is the faceting chord: a twelve-sided
    ring inscribes its declared circle, so the drawn width sits a few per cent
    under the declared one and must never stand above it.
    """
    for age, face in itertools.product(kit.AGE_PRESENTATIONS, kit.FACE_VARIANTS):
        entry = identity(age_presentation=age, face=face)
        size = kit.figure_dimensions(entry)
        bounds = kit.primitive_bounds(parts(entry)["skull"])
        drawn_height = bounds["z"][1] - bounds["z"][0]
        drawn_width = bounds["y"][1] - bounds["y"][0]
        assert drawn_height <= size["head_height"] * 1.001, f"{age}/{face} skull is too tall"
        assert drawn_height >= size["head_height"] * 0.999, f"{age}/{face} skull is squashed"
        assert drawn_width <= size["head_width"] * 1.05, f"{age}/{face} skull is too wide"
        assert drawn_width >= size["head_width"] * 0.90, f"{age}/{face} skull is pinched"


SHOULDER_BANDS = {
    "slim": (0.195, 0.235),
    "average": (0.225, 0.265),
    "athletic": (0.260, 0.300),
    "broad": (0.265, 0.305),
}
"""How much of a body's height its shoulders may span, per build.

Measured on the canonical average adult, the v2 kit builds slim 0.2156,
average 0.2450, athletic 0.2793 and broad 0.2842. The bands hold each build
apart from its neighbours' MEASURED values while allowing tuning inside them,
and the strict ordering below is asserted separately -- a build vocabulary
whose widest figure is not its broadest would be a silhouette language that
stopped meaning anything.
"""


def test_every_build_wears_its_own_shoulders() -> None:
    """Each build's shoulder span sits in its band, and the order is strict."""
    assert set(SHOULDER_BANDS) == set(kit.BUILDS)
    measured = {}
    for build, (low, high) in sorted(SHOULDER_BANDS.items()):
        size = kit.figure_dimensions(identity(build=build))
        ratio = size["shoulder_width"] / size["height"]
        measured[build] = ratio
        assert low <= ratio <= high, (
            f"a {build} adult carries {ratio:.4f} of its height in shoulders, "
            f"outside ({low}, {high})"
        )
    assert measured["slim"] < measured["average"] < measured["athletic"] < measured["broad"]


def test_an_idle_body_is_its_own_mirror_image() -> None:
    """Bit-level left-right symmetry, the contract the ring builder promises.

    Every limb member and both feet of an idle body must mirror across the
    centreline to numerical zero. The kit builds the right side by negating
    the left's numbers rather than by re-evaluating trigonometry, so anything
    beyond 1.0e-9 here is not rounding -- it is a limb built from a different
    opinion of where the body's middle is.
    """
    for age in kit.AGE_PRESENTATIONS:
        limbs = parts(identity(age_presentation=age))
        for part in ("leg", "upper_arm", "forearm", "hand", "foot"):
            left = limbs[f"left_{part}"]["vertices"]
            right = limbs[f"right_{part}"]["vertices"]
            mirrored = sorted((x, -y, z) for x, y, z in left)
            for expected, built in zip(mirrored, sorted(right), strict=True):
                assert math.dist(expected, built) <= 1.0e-9, (
                    f"a {age} {part} is not its own mirror image"
                )


def test_the_brow_never_fuses_with_the_eyes() -> None:
    """The sunglasses regression, held as a measured band of bare complexion.

    The shipped defect was two dark plates close enough to read as one visor.
    The cure is geometry, not colour: at least 0.06 of the head's height must
    separate the brow's underside from the eyes' tops, measured on the emitted
    plates rather than recomputed from the level table that authored them.
    """
    assert kit.BROW_EYE_GAP >= 0.06
    for age, face in itertools.product(kit.AGE_PRESENTATIONS, kit.FACE_VARIANTS):
        frame, features = kit.head_probe(identity(age_presentation=age, face=face))
        brow_low = kit.primitive_bounds(features["brow"])["z"][0]
        eyes_top = max(
            kit.primitive_bounds(features[eye])["z"][1] for eye in ("left_eye", "right_eye")
        )
        gap = (brow_low - eyes_top) / frame["height"]
        assert gap >= 0.06, f"{age}/{face} keeps only {gap:.4f} of head height above the eyes"


def test_no_foot_outgrows_its_body() -> None:
    """A foot is footwear, not a clown shoe: its width is capped by height.

    The kit clamps ``foot_width`` at 0.055 of height so the broad build's limb
    multiplier cannot widen a shoe past what a body could plausibly wear, and
    the cap is proved on the built wedge's vertices rather than on the number
    that claimed it.
    """
    for age, stature, build in itertools.product(kit.AGE_PRESENTATIONS, kit.STATURES, kit.BUILDS):
        entry = identity(age_presentation=age, stature=stature, build=build)
        size = kit.figure_dimensions(entry)
        bounds = kit.primitive_bounds(parts(entry)["left_foot"])
        width = bounds["y"][1] - bounds["y"][0]
        assert width <= size["height"] * 0.055 + 1.0e-9, (
            f"a {stature} {build} {age} foot is {width:.4f}m wide on a {size['height']:.4f}m body"
        )


def _face_area(points: list[tuple[float, float, float]]) -> float:
    """The area of one polygon face, summed over its triangle fan."""
    origin = points[0]
    total = 0.0
    for first, second in zip(points[1:], points[2:], strict=False):
        edge_a = (first[0] - origin[0], first[1] - origin[1], first[2] - origin[2])
        edge_b = (second[0] - origin[0], second[1] - origin[1], second[2] - origin[2])
        cross = (
            edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
            edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
            edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
        )
        total += math.sqrt(cross[0] ** 2 + cross[1] ** 2 + cross[2] ** 2) / 2.0
    return total


def test_no_primitive_emits_a_degenerate_face() -> None:
    """Every face Blender will be handed is a face Blender can build.

    Indices in range, at least three distinct corners, real area, and no face
    stated twice. ``bmesh`` quietly repairs some of these and renders artefacts
    for the rest, so the pure suite has to refuse them before the weld does --
    a zero-area face is invisible in every count and only visible as shading
    noise on a finished body. Swept across a spread of the vocabulary with
    every hair, clothing, facial-hair, face and pose value represented.
    """
    spread = itertools.product(kit.AGE_PRESENTATIONS, kit.HAIR_VARIANTS, kit.CLOTHING_SILHOUETTES)
    for index, (age, hair, clothing) in enumerate(spread):
        entry = identity(
            age_presentation=age,
            hair=hair,
            clothing=clothing,
            facial_hair=kit.FACIAL_HAIR[index % len(kit.FACIAL_HAIR)],
            face=kit.FACE_VARIANTS[index % len(kit.FACE_VARIANTS)],
            pose=POSES[index % len(POSES)],
        )
        for item in kit.figure_geometry(entry):
            label = f"{age}/{hair}/{clothing} {item['name']}"
            stated: set[frozenset] = set()
            for face in item["faces"]:
                assert all(0 <= corner < len(item["vertices"]) for corner in face), (
                    f"{label} face indexes a vertex that does not exist"
                )
                corners = [item["vertices"][corner] for corner in face]
                assert len(set(corners)) >= 3, f"{label} face has fewer than three corners"
                assert _face_area(corners) > 1.0e-10, f"{label} face has no area"
                key = frozenset(face)
                assert key not in stated, f"{label} states one face twice"
                stated.add(key)


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
    """Every haircut must alter geometry; a recoloured shell is not a variant.

    Byte-inequality only, and that is deliberately WEAK -- it proves the
    variants are not literally the same mesh and nothing more. Two haircuts
    differing by two millimetres satisfy it while reading as one haircut at
    thirty metres, which is exactly what happened once. The tests below are
    the ones that defend visible variety; this one only defends identity.
    """
    built = {hair: kit.figure_geometry(identity(hair=hair)) for hair in kit.HAIR_VARIANTS}
    assert len(built["bald"]) < len(built["short"]), "bald must remove geometry"
    for first, second in itertools.combinations(kit.HAIR_VARIANTS, 2):
        assert built[first] != built[second], f"hair {first} and {second} are identical"


# ---------------------------------------------------------------------------
# Hair silhouettes: visible variety, measured rather than assumed
# ---------------------------------------------------------------------------

HAIRED_VARIANTS = ("short", "medium", "long", "tied")
"""The four haircuts that are neither bald nor a cap.

A cap is headwear rather than a haircut -- its silhouette is the cap's -- so
the length and mass promises below are asked of these four, which are the
ones a viewer reads as different people.
"""

MIN_LEVEL_SEPARATION = 0.05
"""How far apart two haircuts' lowest reach must be, in head-heights.

The pair that has to clear this by the smallest margin is the cropped one
against the gathered one, which the shipped design separated by 0.09. Half
of that is the floor: comfortably below the real design and far above the
0.010 that a collapsed vocabulary produced.
"""

MIN_REAR_SPREAD = 0.04
"""How much the vocabulary's rear extents must vary, in head-depths.

THE ANTI-COLLAPSE GUARD, and the reason this section exists. A gathered
bun, a ponytail and a long fall all carry mass BEHIND the skull that a crop
does not, so a healthy vocabulary spreads its rear extents; the shipped
design spanned 0.08 head-depths. A vocabulary that has quietly become one
shell at one radius spans almost nothing -- the collapse this guard was
written against measured 0.012, under a third of this floor.

Rear extent is the discriminator that a bounding-box or byte-difference
check cannot fake: it is the mass a viewer actually reads in profile.
"""

MIN_GATHER_PROJECTION = 0.03
"""How far a gathered style must reach behind a cropped one, in head-depths.

A bun or a ponytail is mass ADDED behind what a crop already has, so the
comparison is against ``short`` rather than against the skull -- every
covering shell already stands proud of the skull, so measuring against the
skull would pass a vocabulary with no gather at all.

CALIBRATED, because the baseline moved. The nape strip that fixed the
eye-occlusion artefact also carried the crop's own rear extent out from
about 0.58 to 0.60 head-depths, so a gather sized against the OLD crown is
now swallowed by the new one: a bun reaching 0.62 -- the shipped figure --
clears the crop by 0.017, which is under four millimetres on an adult and
invisible at proof distance. A bun reaching 0.66 clears it by 0.057 and
satisfies this floor on every age band. That is the target, and it is the
interaction this guard exists to keep visible: fixing the occlusion made
the gather harder to see, and nothing else would have said so.
"""


def _hair_silhouette(entry: dict) -> dict:
    """What a viewer reads of one haircut, in head-relative units.

    ``level`` is the lowest hair vertex measured from the head BASE in
    head-heights: positive sits up on the skull, zero is the chin line,
    negative falls past it onto the neck and shoulders. ``rear`` is how far
    the hair reaches behind the head's own axis in head-depths, and
    ``lowest`` is the same reach as a raw body-space height, for comparing
    against the shoulder.

    Normalised on purpose: a child's head is larger relative to its body
    than an adult's, so a promise stated in metres would mean a different
    haircut on every age band.
    """
    size = kit.figure_dimensions(entry)
    base, height = size["neck_top"], size["head_height"]
    axis, depth = size["lean"], size["head_depth"]
    pieces = [
        piece for name, piece in kit.placed_head_features(entry).items() if name.startswith("hair_")
    ]
    assert pieces, f"{entry['hair']} built no hair at all"
    lowest = min(kit.feature_bounds(piece)["z"][0] for piece in pieces)
    rear = max(axis - kit.feature_bounds(piece)["x"][0] for piece in pieces)
    return {
        "level": (lowest - base) / height,
        "rear": rear / depth,
        "lowest": lowest,
        "shoulder": size["torso_top"],
    }


def _variant_silhouette(hair: str, age: str = "adult") -> dict:
    """One haircut's reach across every face sub-silhouette it can take.

    A face variant selects between each haircut's two sub-silhouettes, so a
    promise about "long hair" is a promise about the longest thing long hair
    can be, and about the furthest back it ever reaches.
    """
    measured = [
        _hair_silhouette(identity(hair=hair, face=face, age_presentation=age))
        for face in kit.FACE_VARIANTS
    ]
    return {
        "level": min(entry["level"] for entry in measured),
        "rear": max(entry["rear"] for entry in measured),
        "lowest": min(entry["lowest"] for entry in measured),
        "shoulder": measured[0]["shoulder"],
    }


def test_the_hair_vocabulary_carries_real_mass_behind_the_head() -> None:
    """Haircuts must differ in PROFILE, not merely in their vertex bytes.

    The defect this exists for: every haircut collapsed onto one crown-and-
    nape shell at one radius, so the whole vocabulary's rear extents spanned
    2.7mm on an adult head. Every other hair test still passed -- the meshes
    differed, so byte-inequality held, and local diversity keys on the hair
    NAME rather than on its geometry, so the crowd's diversity rule held too
    -- while eighty people were quietly wearing the same haircut.

    Nothing else in the suite was watching the thing the Director actually
    asked for, which is that eighty people read as eighty people.
    """
    for age in kit.AGE_PRESENTATIONS:
        rears = {hair: _variant_silhouette(hair, age)["rear"] for hair in HAIRED_VARIANTS}
        spread = max(rears.values()) - min(rears.values())
        assert spread >= MIN_REAR_SPREAD, (
            f"the {age} hair vocabulary spans only {spread:.4f} head-depths of rear extent "
            f"({ {name: round(value, 4) for name, value in sorted(rears.items())} }); every "
            "haircut is the same shell at the same radius"
        )


def test_every_haircut_is_a_different_length() -> None:
    """Four haircuts, four lengths, separated by something a viewer can see."""
    for age in kit.AGE_PRESENTATIONS:
        levels = {hair: _variant_silhouette(hair, age)["level"] for hair in HAIRED_VARIANTS}
        for first, second in itertools.combinations(sorted(levels), 2):
            gap = abs(levels[first] - levels[second])
            assert gap >= MIN_LEVEL_SEPARATION, (
                f"a {age}'s {first} and {second} hair reach within {gap:.4f} head-heights of "
                "each other, which is the same haircut twice"
            )


def test_long_hair_reaches_the_shoulder_line() -> None:
    """Long hair that stops at the jaw is medium hair with a different name."""
    for age in kit.AGE_PRESENTATIONS:
        measured = _variant_silhouette("long", age)
        assert measured["lowest"] <= measured["shoulder"], (
            f"a {age}'s long hair stops at {measured['lowest']:.4f}, above its own shoulder "
            f"line at {measured['shoulder']:.4f}"
        )


def test_tied_hair_carries_a_gather() -> None:
    """A tie is a bun or a tail: mass behind the head a crop does not have.

    Measured against ``short`` rather than against the skull. Every covering
    shell already stands proud of the skull by construction, so a
    skull-relative check passes for a vocabulary with no gather anywhere in
    it -- which is precisely the state that shipped.
    """
    for age in kit.AGE_PRESENTATIONS:
        tied = _variant_silhouette("tied", age)["rear"]
        cropped = _variant_silhouette("short", age)["rear"]
        assert tied - cropped >= MIN_GATHER_PROJECTION, (
            f"a {age}'s tied hair reaches {tied - cropped:+.4f} head-depths behind its own "
            "cropped hair, so it carries no gather"
        )


def test_short_hair_stays_up_on_the_skull() -> None:
    """A crop is a crop: it may not descend past the head it is cut on."""
    for age in kit.AGE_PRESENTATIONS:
        level = _variant_silhouette("short", age)["level"]
        assert level > 0.0, (
            f"a {age}'s short hair falls {-level:.4f} head-heights below the head base"
        )


def test_clothing_changes_the_silhouette_not_just_the_colour() -> None:
    """Every garment must alter the body it dresses.

    The one deliberate exception is the sleeve length: since the chain
    contract, every arm is the same three members whatever the garment, so a
    short sleeve is the SAME geometry with a complexion forearm rather than
    extra primitives -- a bare forearm is skin, not more arm.
    """
    built = {
        name: kit.figure_geometry(identity(clothing=name)) for name in kit.CLOTHING_SILHOUETTES
    }
    for first, second in itertools.combinations(kit.CLOTHING_SILHOUETTES, 2):
        assert built[first] != built[second], f"clothing {first} and {second} are identical"
    assert len(built["short_sleeve"]) == len(built["shirt"]), (
        "a sleeve length must not change the chain structure"
    )
    bare = {item["name"]: item for item in built["short_sleeve"]}
    sleeved = {item["name"]: item for item in built["shirt"]}
    for side in ("left", "right"):
        assert bare[f"{side}_forearm"]["material"] != sleeved[f"{side}_forearm"]["material"], (
            f"a short-sleeved {side} forearm is not bared"
        )
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


MAX_TRIANGLES_PER_FIGURE = 950
"""The declared geometry budget for one body.

The remediation raised the ceilings to 950 triangles a figure and 68,000 for
the canonical eighty, and Visual DNA v2 spent the raise on resolution: twelve
facets around every skull, five rings and two poles through it, an eight-sided
torso with six cross-sections, five-ring legs with a calf, hands, a socket
closing each armpit, and a shaped brim on the cap.

Measured against the FINAL kit on 2026-08-16, over all 6,912 combinations of
the six axes that change how many primitives a body is made of -- age, hair,
facial hair, face, clothing and pose; stature, build and presentation scale
the geometry without adding to it:

    heaviest body      902   a child with tied hair, a beard and formal
                             clothing
    vocabulary mean    830.3
    baseline adult     818   the unremarkable figure the rest are read against
    over the ceiling     0   of 6,912

The canonical eighty total 66,300 of the 68,000 layer ceiling -- 1,700 spare
-- at a FLEET mean of 828.8, a heaviest fielded proxy of 902 and a lightest
of 668. That fleet mean is not the vocabulary mean above, and multiplying the
vocabulary mean by eighty to get a fleet total is the arithmetic that put an
earlier hand-off some three hundred triangles adrift. The fleet is summed,
per proxy, by ``test_population_presence_plan``.

    THE LAYER CEILING IS NOW GENUINELY CLOSE. CHECK IT BEFORE ADDING
    GEOMETRY; DO NOT ASSUME THERE IS ROOM.

Two and a half per cent of the ceiling is left. Stated per body, the fleet
averages 828.8 against the 850 that eighty proxies may average, so there are
about twenty-one triangles a person in hand -- and the heaviest body the
vocabulary can build is 902, which at eighty proxies would come to 72,160.
The layer fits because the dressing draw happens to spread across light and
heavy identities, NOT because every identity fits. A change that shifts the
draw heavier can breach the ceiling without any single body growing at all,
which is why ``test_population_presence_plan`` sums the real eighty rather
than trusting a per-body maximum.

The gap between 902 and 950 is headroom, not vagueness: the ceiling is the
number the directive approved, and the test below re-measures every
combination the vocabulary permits, so a regression spends its budget loudly.
Every figure in this docstring is EVIDENCE, not contract -- only the 950 is
asserted -- so a polish round that moves them is a docstring re-bake rather
than a failure.
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
