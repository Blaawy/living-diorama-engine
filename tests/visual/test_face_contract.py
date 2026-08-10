"""Machine-verified face invariants for the Phase 18 figure kit.

Pure pytest -- no Blender. Every assertion recomputes a feature's position from
the GENERATED geometry and compares it against the skull that was actually
built. Nothing reads a constant back out of the module and checks it against
itself.

That distinction is why this file exists. An earlier suite asked "are there at
least four boxes above the neck with a positive X offset?", which was true of a
face whose eyes were sealed three millimetres inside the skull and whose
features did not turn with the head. Both defects shipped. Every invariant
below would have caught them.

The contract, in one sentence: every ordinary face has exactly two eyes,
mirrored about the centreline at equal height and equal forward offset, with a
centred nose below them and above the mouth, all of it standing proud of the
head's own curved surface, none of it occluded by hair, and all of it carried
into body space by the head's single transform.

WHAT CHANGED WITH THE GEOMETRY REBUILD
--------------------------------------
The head is no longer a box, so "proud of the front face" no longer names a
plane. There is no plane. A feature now has to stand clear of a CURVED skull
whose surface falls away towards the temples, the chin and the crown -- and
clear of it at every point of the feature, not merely at its centre, because
the failure mode of a flat plate on a curved head is that its middle sinks in
while both of its ends stand proud.

So the clearance tests sample. :func:`figure_kit.plate_clearance` walks a grid
over a feature's own front surface and returns the smallest gap to the skull
underneath it, and the invariant is that this minimum is positive. That is a
strictly stronger statement than the old one, and it is the only one that
means anything on a head with a cheek.
"""

import importlib
import itertools
import math
import sys
from pathlib import Path

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

EYE_NAMES = ("left_eye", "right_eye")

FACE_PARTS = ("brow", "left_eye", "right_eye", "nose", "mouth")

POSES = ("idle", "observe", "stroll", "rest")

TOLERANCE = 1.0e-9


def identity(**overrides) -> dict:
    """One visual identity, defaulting to an unremarkable adult."""
    return {**BASE, **overrides}


def every_head() -> list[dict]:
    """Every head combination the contract has to hold for.

    Age bands times hair variants times facial hair times face variants times
    poses -- the whole space, not a sample, because it is small enough to
    enumerate and a sample is how a broken combination survives.
    """
    return [
        identity(age_presentation=age, hair=hair, facial_hair=growth, face=face, pose=pose)
        for age, hair, growth, face, pose in itertools.product(
            kit.AGE_PRESENTATIONS, kit.HAIR_VARIANTS, kit.FACIAL_HAIR, kit.FACE_VARIANTS, POSES
        )
    ]


def head_local(entry: dict) -> tuple[dict, dict]:
    """The head frame and its features, keyed by name, in head-local space."""
    return kit.head_probe(entry)


def bounds(feature: dict) -> dict:
    """The head-local extent of one feature, measured from its vertices."""
    return kit.primitive_bounds(feature)


def centroid(feature: dict) -> tuple[float, float, float]:
    """The mean of one feature's vertices."""
    points = feature["vertices"]
    return (
        math.fsum(point[0] for point in points) / len(points),
        math.fsum(point[1] for point in points) / len(points),
        math.fsum(point[2] for point in points) / len(points),
    )


def overlaps(first: tuple[float, float], second: tuple[float, float]) -> bool:
    """True when two closed intervals share any extent."""
    return first[0] < second[1] and second[0] < first[1]


# ---------------------------------------------------------------------------
# 1-5: the two-eye contract
# ---------------------------------------------------------------------------


def test_every_face_generates_exactly_two_eyes() -> None:
    """Invariant 1. No cyclops, no face that quietly lost one."""
    for entry in every_head():
        _frame, features = head_local(entry)
        eyes = [name for name in features if name.endswith("_eye")]
        assert sorted(eyes) == ["left_eye", "right_eye"], (
            f"{entry['age_presentation']}/{entry['face']} generated {sorted(eyes)}"
        )


def test_the_eyes_sit_on_opposite_sides_of_the_centreline() -> None:
    """Invariants 2 and 3, computed from geometry rather than from names."""
    for entry in every_head():
        _frame, features = head_local(entry)
        left = bounds(features["left_eye"])
        right = bounds(features["right_eye"])
        assert left["y"][0] > 0.0, f"left_eye crosses the centreline: {left['y']}"
        assert right["y"][1] < 0.0, f"right_eye crosses the centreline: {right['y']}"


def test_the_eyes_are_mirrored_about_the_centreline() -> None:
    """Invariant 4. Equal and opposite lateral offset, and equal width."""
    for entry in every_head():
        _frame, features = head_local(entry)
        left, right = bounds(features["left_eye"]), bounds(features["right_eye"])
        assert abs((left["y"][0] + left["y"][1]) + (right["y"][0] + right["y"][1])) < TOLERANCE, (
            "the eyes are not mirrored about the centreline"
        )
        left_width = left["y"][1] - left["y"][0]
        right_width = right["y"][1] - right["y"][0]
        assert abs(left_width - right_width) < TOLERANCE


def test_the_eyes_share_a_height_and_a_forward_offset() -> None:
    """Invariants 5 and part of 9: level eyes, equally proud of the face."""
    for entry in every_head():
        _frame, features = head_local(entry)
        left, right = bounds(features["left_eye"]), bounds(features["right_eye"])
        assert abs(left["z"][0] - right["z"][0]) < TOLERANCE
        assert abs(left["z"][1] - right["z"][1]) < TOLERANCE
        assert abs(left["x"][1] - right["x"][1]) < TOLERANCE, (
            "one eye stands further forward than the other"
        )


# ---------------------------------------------------------------------------
# 6-9: the nose contract, and the forward projection contract
# ---------------------------------------------------------------------------


def test_the_nose_sits_between_the_eyes_laterally() -> None:
    """Invariant 6, against the eyes' real inner edges."""
    for entry in every_head():
        _frame, features = head_local(entry)
        nose = bounds(features["nose"])
        left = bounds(features["left_eye"])
        right = bounds(features["right_eye"])
        assert nose["y"][1] <= left["y"][0] + TOLERANCE, "the nose reaches into the left eye"
        assert nose["y"][0] >= right["y"][1] - TOLERANCE, "the nose reaches into the right eye"
        assert abs(nose["y"][0] + nose["y"][1]) < TOLERANCE, "the nose is off the centreline"


def test_the_nose_is_below_the_eyes_and_above_the_mouth() -> None:
    """Invariant 7, plus the mouth ordering the directive asks for."""
    for entry in every_head():
        _frame, features = head_local(entry)
        nose = bounds(features["nose"])
        eye = bounds(features["left_eye"])
        mouth = bounds(features["mouth"])
        assert nose["z"][1] <= eye["z"][0] + TOLERANCE, "the nose reaches the eye line"
        assert nose["z"][0] >= mouth["z"][1] - TOLERANCE, "the nose reaches the mouth"


def test_the_nose_is_the_most_forward_thing_on_a_face() -> None:
    """A profile has to read. The nose leads; the eyes and brow sit behind it."""
    for entry in every_head():
        _frame, features = head_local(entry)
        nose = bounds(features["nose"])["x"][1]
        for name in ("brow", "left_eye", "right_eye", "mouth"):
            assert bounds(features[name])["x"][1] < nose, f"{name} projects past the nose"


def test_every_facial_feature_stands_proud_of_the_curved_face() -> None:
    """Invariants 8, 9 and 10, and the defect that actually shipped.

    Sampled across each feature's whole front surface against the skull built
    beneath it. The first version authored the eyes and the brow a few
    millimetres behind a flat face plane, so they were sealed inside the skull
    and only the nose rendered -- which is exactly what the Director saw.

    The curved head made this stricter rather than easier: a plate can now be
    proud at both ends and buried in the middle, and that is what this catches.
    """
    for entry in every_head():
        frame, features = head_local(entry)
        for name in FACE_PARTS:
            clearance = kit.plate_clearance(frame, features[name])
            assert clearance > 0.0, (
                f"{name} on {entry['age_presentation']}/{entry['face']} is buried "
                f"{-clearance:.5f}m inside the head"
            )


def test_no_facial_feature_floats_away_from_the_head() -> None:
    """Invariant 11. Proud is not the same as detached."""
    for entry in every_head():
        frame, features = head_local(entry)
        limit = frame["depth"] * 0.30
        for name in FACE_PARTS:
            clearance = kit.plate_clearance(frame, features[name])
            assert clearance <= limit, f"{name} floats {clearance:.4f}m off the face"
            assert bounds(features[name])["x"][0] < frame["front"], (
                f"{name} has left the head entirely"
            )


def test_every_facial_feature_stays_within_the_head_silhouette() -> None:
    """Invariant 11 laterally and vertically: nothing hangs off the side."""
    for entry in every_head():
        frame, features = head_local(entry)
        half_width = frame["width"] / 2.0
        base = frame["origin"][2]
        for name in FACE_PARTS:
            extent = bounds(features[name])
            assert extent["y"][0] >= -half_width and extent["y"][1] <= half_width, (
                f"{name} hangs off the side of the head"
            )
            assert extent["z"][0] >= base and extent["z"][1] <= base + frame["height"], (
                f"{name} is above or below the head"
            )


def test_a_feature_follows_the_cheek_instead_of_hovering_over_it() -> None:
    """The conforming contract, stated as a measurement.

    A feature's outer columns must sit FURTHER BACK than its inner ones,
    because the skull does. A flat plate laid across a curved face would have
    equal depth all the way across, which is how a brow ends up detached at
    the temples.
    """
    checked = 0
    for entry in every_head():
        _frame, features = head_local(entry)
        for name in ("brow", "left_eye", "right_eye"):
            feature = features[name]
            front = [feature["vertices"][index] for index in feature["front"]]
            outer = max(front, key=lambda point: abs(point[1]))
            inner = min(front, key=lambda point: abs(point[1]))
            assert abs(abs(outer[1]) - abs(inner[1])) > 1.0e-6, (
                f"{name} has no lateral spread to conform across"
            )
            assert outer[0] <= inner[0] + 1.0e-9, (
                f"{name} is flat across a curved face: outer {outer[0]} vs inner {inner[0]}"
            )
            checked += 1
    assert checked > 0, "the conformance rule checked nothing"


# ---------------------------------------------------------------------------
# 12: hair may frame a face, never erase it
# ---------------------------------------------------------------------------


def test_no_hair_variant_occludes_an_eye() -> None:
    """Invariant 12, tested as real occlusion rather than as a height rule.

    Hair hides an eye when it stands in FRONT of that eye while overlapping it
    both laterally and vertically. Every hair variant is checked against every
    face variant and every age band.
    """
    for entry in every_head():
        _frame, features = head_local(entry)
        hair = [bounds(feature) for name, feature in features.items() if name.startswith("hair_")]
        for eye_name in EYE_NAMES:
            eye = bounds(features[eye_name])
            for cover in hair:
                occludes = (
                    cover["x"][1] > eye["x"][1]
                    and overlaps(cover["y"], eye["y"])
                    and overlaps(cover["z"], eye["z"])
                )
                assert not occludes, (
                    f"{entry['hair']} hair occludes the {eye_name} on a {entry['age_presentation']}"
                )


def test_no_hair_variant_occludes_the_nose() -> None:
    """The same rule for the nose, which the directive names explicitly."""
    for entry in every_head():
        _frame, features = head_local(entry)
        nose = bounds(features["nose"])
        for name, feature in features.items():
            if not name.startswith("hair_"):
                continue
            cover = bounds(feature)
            assert not (
                cover["x"][1] > nose["x"][1]
                and overlaps(cover["y"], nose["y"])
                and overlaps(cover["z"], nose["z"])
            ), f"{entry['hair']} hair occludes the nose"


def test_hair_never_sits_flush_with_the_skull() -> None:
    """Coplanar faces z-fight, and a candidate shipped with speckled hair.

    A covering shell is pushed out along the head's own profile, so it closes
    ABOVE the crown rather than on it. Rear volumes are held clear a different
    way: they sit behind the skull's own widest forward reach, which is also
    why no amount of hair mass can wrap around onto a brow.
    """
    for entry in every_head():
        if entry["hair"] == "bald":
            continue
        frame, features = head_local(entry)
        skull = kit.primitive_bounds(features["skull"])
        covering = [name for name in features if name in ("hair_crown", "hair_cap")]
        assert covering, f"{entry['hair']} has no covering shell"
        for name, feature in features.items():
            if not name.startswith("hair_"):
                continue
            extent = bounds(feature)
            if name in ("hair_crown", "hair_cap"):
                assert extent["z"][1] > skull["z"][1], f"{name} sits flush with the crown"
            elif name != "hair_brim":
                assert extent["x"][1] < frame["front"], f"{name} reaches around onto the face"


def test_hair_actually_covers_the_skull_it_sits_on() -> None:
    """The guard that was missing, and the defect it would have caught.

    A covering shell has to CONTAIN the skull above the hairline, not merely
    reach higher than it. The version that shipped compared the tops of two
    bounding boxes, which the crown pole satisfies on its own -- and underneath
    it eight of the nine skull vertices above the hairline stood outside the
    hair on every haired figure at every age, so each one rendered with a band
    of bare complexion-coloured skull ringing its head.

    Two causes, both invisible to a bounding box: the shell straddled the
    skull's own profile ring instead of following it, and a six-sided shell
    inscribed in an eight-sided skull passes inside its vertices.
    """
    for entry in every_head():
        if entry["hair"] == "bald":
            continue
        frame, features = head_local(entry)
        base, height = frame["origin"][2], frame["height"]
        shells = [
            feature for name, feature in features.items() if name in ("hair_crown", "hair_cap")
        ]
        assert shells, f"{entry['hair']} builds no covering shell"
        for vertex in features["skull"]["vertices"]:
            if (vertex[2] - base) / height < kit.HAIRLINE - 1.0e-9:
                continue
            covered = False
            for shell in shells:
                section = kit.section_at_height(shell, kit.HAIR_SIDES, vertex[2])
                if section and kit.encloses(section, (vertex[0], vertex[1])):
                    covered = True
                    break
            assert covered, (
                f"{entry['age_presentation']}/{entry['hair']} leaves bare skull at "
                f"{tuple(round(axis, 4) for axis in vertex)}"
            )


def test_the_coverage_check_would_catch_a_shrunken_shell() -> None:
    """Proven, not assumed: shrink the shell and the rule bites."""
    entry = identity(hair="short")
    frame, features = head_local(entry)
    shell = features["hair_crown"]
    origin = frame["origin"]
    shrunk = {
        **shell,
        "vertices": tuple(
            (origin[0] + (x - origin[0]) * 0.5, y * 0.5, z) for x, y, z in shell["vertices"]
        ),
    }
    base, height = origin[2], frame["height"]
    exposed = 0
    for vertex in features["skull"]["vertices"]:
        if (vertex[2] - base) / height < kit.HAIRLINE - 1.0e-9:
            continue
        section = kit.section_at_height(shrunk, kit.HAIR_SIDES, vertex[2])
        if not (section and kit.encloses(section, (vertex[0], vertex[1]))):
            exposed += 1
    assert exposed > 0, "a halved shell must leave skull exposed for the rule to be real"


def test_facial_hair_never_reaches_the_eyes_or_the_nose() -> None:
    """The facial-hair contract: below the nose, always."""
    for entry in every_head():
        _frame, features = head_local(entry)
        nose = bounds(features["nose"])
        for name in ("beard", "moustache"):
            if name not in features:
                continue
            growth = bounds(features[name])
            assert growth["z"][1] <= nose["z"][0] + TOLERANCE, (
                f"{name} reaches the nose on a {entry['age_presentation']}"
            )
            for eye_name in EYE_NAMES:
                assert not overlaps(growth["z"], bounds(features[eye_name])["z"])


def test_facial_hair_stays_attached_to_the_head() -> None:
    """No detached floating blocks, and none buried either."""
    for entry in every_head():
        frame, features = head_local(entry)
        for name in ("beard", "moustache"):
            if name not in features:
                continue
            clearance = kit.plate_clearance(frame, features[name])
            assert clearance > 0.0, f"{name} is buried {-clearance:.5f}m in the jaw"
            assert clearance <= frame["depth"] * 0.30, f"{name} floats off the face"


# ---------------------------------------------------------------------------
# 13: the face survives the body transform
# ---------------------------------------------------------------------------


def test_the_face_turns_with_the_head() -> None:
    """Invariant 13, and the second defect that shipped.

    Every head feature must ORBIT the head's axis by the head turn. The first
    version handed the turn to each box as its own spin, so the skull rotated
    while the face stayed pointing where the body pointed. Checked on the
    vertices themselves: every point of every feature has to land exactly where
    one rigid rotation about the head origin would put it.
    """
    for pose in POSES:
        entry = identity(pose=pose)
        size = kit.figure_dimensions(entry)
        turn = kit._pose_frame(pose, size)["head_turn"]
        frame = kit.head_frame(size, turn)
        origin_x, origin_y, _ = frame["origin"]
        reference = kit.head_frame(size, 0.0)
        placed = kit.placed_head_features(entry)
        for feature in kit.head_features(entry, reference):
            name = feature["name"]
            built = placed[name]["vertices"]
            assert len(built) == len(feature["vertices"])
            for local, actual in zip(feature["vertices"], built, strict=True):
                expected_x = origin_x + local[0] * math.cos(turn) - local[1] * math.sin(turn)
                expected_y = origin_y + local[0] * math.sin(turn) + local[1] * math.cos(turn)
                assert abs(actual[0] - expected_x) < 1.0e-9, f"{name} did not orbit in {pose}"
                assert abs(actual[1] - expected_y) < 1.0e-9, f"{name} did not orbit in {pose}"
                assert abs(actual[2] - local[2]) < 1.0e-9, f"{name} changed height in {pose}"


def test_a_turned_face_still_points_where_the_head_points() -> None:
    """The whole point, stated as a bearing.

    The vector from the head centre to the nose must lie along the head's
    forward axis after the turn, for every pose.
    """
    for pose in POSES:
        entry = identity(pose=pose)
        size = kit.figure_dimensions(entry)
        turn = kit._pose_frame(pose, size)["head_turn"]
        placed = kit.placed_head_features(entry)
        origin_x, origin_y, _ = kit.head_frame(size, turn)["origin"]
        nose_x, nose_y, _z = centroid(placed["nose"])
        bearing = math.atan2(nose_y - origin_y, nose_x - origin_x)
        assert abs(math.atan2(math.sin(bearing - turn), math.cos(bearing - turn))) < 1.0e-9, (
            f"the nose points {bearing} while the head faces {turn} in {pose}"
        )


def test_both_eyes_stay_symmetric_after_the_turn() -> None:
    """A rotation must not favour one eye over the other."""
    for pose in POSES:
        entry = identity(pose=pose)
        size = kit.figure_dimensions(entry)
        turn = kit._pose_frame(pose, size)["head_turn"]
        origin_x, origin_y, _ = kit.head_frame(size, turn)["origin"]
        placed = kit.placed_head_features(entry)
        distances = []
        for name in EYE_NAMES:
            x, y, _z = centroid(placed[name])
            distances.append(math.hypot(x - origin_x, y - origin_y))
        assert abs(distances[0] - distances[1]) < 1.0e-9


def test_the_probe_helpers_agree_with_the_built_geometry() -> None:
    """The Blender suite ray-casts along these; they have to be right.

    ``head_forward`` and ``feature_front`` are what the structural tests aim a
    ray with. If they disagreed with the mesh, an in-Blender face check would be
    probing empty air and passing. So this compares the helper's answer against
    the feature's own placed vertices rather than merely checking it is finite.
    """
    for pose in POSES:
        entry = identity(pose=pose)
        frame, features = head_local(entry)
        forward = kit.head_forward(frame)
        assert abs(math.hypot(forward[0], forward[1]) - 1.0) < 1.0e-12
        assert forward[2] == 0.0
        placed = kit.placed_head_features(entry)
        for name in FACE_PARTS:
            feature = features[name]
            front = kit.feature_front(frame, feature)
            # The helper must return the mean of the feature's OWN front-face
            # vertices, carried through the head transform -- the same points
            # the placed primitive holds.
            indices = feature["front"]
            built = placed[name]["vertices"]
            expected = (
                math.fsum(built[index][0] for index in indices) / len(indices),
                math.fsum(built[index][1] for index in indices) / len(indices),
                math.fsum(built[index][2] for index in indices) / len(indices),
            )
            for axis in range(3):
                assert abs(front[axis] - expected[axis]) < 1.0e-9, (
                    f"{name} front disagrees with the built geometry on axis {axis}"
                )
            # And it must lie in front of the head origin along the head's axis.
            origin = frame["origin"]
            projected = (front[0] - origin[0]) * forward[0] + (front[1] - origin[1]) * forward[1]
            assert projected > 0.0, f"{name} front is behind the head origin"


# ---------------------------------------------------------------------------
# The guard is itself guarded
# ---------------------------------------------------------------------------


def test_the_clearance_check_would_catch_a_buried_eye() -> None:
    """Proven, not assumed: the invariant that shipped broken now bites.

    Rebuilds the exact defect -- an eye pushed back behind the skull's surface
    -- and requires the same arithmetic the contract test uses to reject it.
    """
    entry = identity()
    frame, features = head_local(entry)
    eye = features["left_eye"]
    assert kit.plate_clearance(frame, eye) > 0.0
    buried = {
        **eye,
        "vertices": tuple((x - 0.020, y, z) for x, y, z in eye["vertices"]),
    }
    assert kit.plate_clearance(frame, buried) < 0.0, "a buried eye must fail the clearance check"


def test_the_clearance_check_would_catch_a_plate_that_sags_in_the_middle() -> None:
    """The curved-head failure mode, rebuilt and rejected.

    A wide feature whose ENDS are on the surface but whose middle is a straight
    chord across it dips inside the skull between them. Sampling only the
    corners would pass it; sampling the surface does not.
    """
    entry = identity()
    frame, _features = head_local(entry)
    half = frame["width"] * 0.42
    level = kit.FACE_LEVELS["brow"]
    surface = kit.head_surface_x(frame, level, half)
    base = frame["origin"][2]
    low = base + (level - 0.02) * frame["height"]
    high = base + (level + 0.02) * frame["height"]
    flat = {
        "name": "flat_brow",
        "kind": "face_feature",
        "material": kit.ACCENT,
        "vertices": tuple(
            (surface + 0.001, lateral, height)
            for lateral in (-half, half)
            for height in (low, high)
        ),
        "faces": ((0, 1, 3, 2),),
    }
    assert kit.head_surface_x(frame, level, 0.0) > surface, "the fixture is not on a curve"
    assert kit.plate_clearance(frame, flat) < 0.0, "a sagging plate must fail the clearance check"


def test_the_occlusion_check_would_catch_a_fringe_over_the_eyes() -> None:
    """And so does the hair rule, given hair that really does cover an eye."""
    entry = identity()
    _frame, features = head_local(entry)
    eye = bounds(features["left_eye"])
    fringe = {
        "name": "hair_fringe",
        "kind": "hair_shell",
        "material": kit.HAIR,
        "vertices": tuple(
            (eye["x"][1] + 0.02 + dx, y, z)
            for dx in (0.0, 0.05)
            for y in (eye["y"][0] - 0.02, eye["y"][1] + 0.02)
            for z in (eye["z"][0] - 0.01, eye["z"][1] + 0.01)
        ),
        "faces": ((0, 1, 3, 2),),
    }
    cover = bounds(fringe)
    assert cover["x"][1] > eye["x"][1]
    assert overlaps(cover["y"], eye["y"])
    assert overlaps(cover["z"], eye["z"])
