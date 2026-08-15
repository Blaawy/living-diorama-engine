"""Contract tests for the Phase 19 vehicle kit.

Pure pytest -- no Blender. Every claim here is measured off the vertices the kit
ACTUALLY EMITS. Nothing below reads a shape back out of :data:`PROPORTIONS`, and
nothing below trusts a primitive's NAME to tell it what that primitive is: a
table can be edited without the geometry following it, and a lump called
``windscreen`` is only a windscreen if it is glass, in front of the cabin, and
visible from outside. Components are therefore recovered by material plus
measured shape, and names appear only inside failure messages.

Two rules are load-bearing enough to deserve saying out loud.

THE ENVELOPE IS A RESERVATION. The lane network sized every lane, headway and
turning fillet from :data:`RESERVED_PLANNING_ENVELOPE` before this kit was reshaped, so
:func:`vehicle_dimensions` deliberately reports that reservation rather than the
sculpture. The kit is then obliged to build INSIDE it, which is what
:func:`measured_visual_bounds` reports and what these tests enforce per archetype per
axis. Both halves are pinned here: the planners must keep reading the box, and
the geometry must keep fitting it.

FIVE ARCHETYPES MUST BE FIVE SHAPES. A reviewer has to be able to tell a van
from a coupe from the silhouette alone, so the differences are asserted as
measured ratios rather than as declared intent.

There is also a guard that no archetype is named after anything real.
"""

import importlib
import math
import re
import sys
from itertools import combinations
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


vehicle_kit = _load("vehicle_kit")

AXES = ("length", "width", "height")
THREE_BOX = ("sedan", "coupe")
TWO_BOX = ("compact", "suv", "van")
TOLERANCE = 1.0e-6

PER_VEHICLE_TRIANGLES = 2500
LAYER_TRIANGLES = 35000
CANONICAL_VEHICLES = 14


# ---------------------------------------------------------------------------
# Measuring primitives
# ---------------------------------------------------------------------------


def _box(vertices: list) -> dict:
    """The axis-aligned box a run of vertices occupies."""
    xs = [vertex[0] for vertex in vertices]
    ys = [vertex[1] for vertex in vertices]
    zs = [vertex[2] for vertex in vertices]
    return {
        "x": (min(xs), max(xs)),
        "y": (min(ys), max(ys)),
        "z": (min(zs), max(zs)),
        "dx": max(xs) - min(xs),
        "dy": max(ys) - min(ys),
        "dz": max(zs) - min(zs),
    }


def _bounds(part: dict) -> dict:
    """The box one primitive occupies."""
    return _box(part["vertices"])


def _span(parts: list) -> dict:
    """The box a whole run of primitives occupies."""
    return _box([vertex for part in parts for vertex in part["vertices"]])


def _centre(part: dict, axis: int) -> float:
    """The midpoint of one primitive on one axis."""
    values = [vertex[axis] for vertex in part["vertices"]]
    return (min(values) + max(values)) / 2.0


def _flank(part: dict) -> int:
    """Which flank a part sits on: +1 left, -1 right, 0 straddling the centreline."""
    low, high = _bounds(part)["y"]
    if low >= 0.0:
        return 1
    if high <= 0.0:
        return -1
    return 0


def _of(parts: list, material: int) -> list:
    """Every primitive wearing one material slot."""
    return [part for part in parts if part["material"] == material]


# ---------------------------------------------------------------------------
# Recovering components from geometry alone
# ---------------------------------------------------------------------------


def _cabin_half_at(greenhouse: dict, x: float) -> float:
    """The cabin's own half width at station ``x``, recovered from its vertices.

    The greenhouse is a loft, so its emitted vertices fall on a handful of
    stations. Grouping them by X and taking the widest point of each recovers
    the skin a window has to stand outside of, without consulting the private
    station table that built it.
    """
    stations: dict = {}
    for vertex in greenhouse["vertices"]:
        key = round(vertex[0], 9)
        stations[key] = max(stations.get(key, 0.0), abs(vertex[1]))
    ordered = sorted(stations.items())
    if x <= ordered[0][0]:
        return ordered[0][1]
    if x >= ordered[-1][0]:
        return ordered[-1][1]
    for (x0, half0), (x1, half1) in zip(ordered, ordered[1:], strict=False):
        if x0 <= x <= x1:
            fraction = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            return half0 + fraction * (half1 - half0)
    return ordered[-1][1]


def _hull_profile(hull: dict) -> list:
    """The hull's per-station bands, recovered from its emitted vertices.

    A loft's vertices fall on a handful of stations, and between them the
    surface is the chord joining corresponding corners, so anything asserted
    against "the hull's side" has to be asserted against these bands rather
    than against the aggregate box the whole hull occupies. Per station:
    ``floor`` and ``ceiling`` are the body's own bottom and top, and the
    ``flank`` band is where the side is actually flat -- the vertices at or
    near the station's full half width. NEAR means within ten per cent,
    which admits both corners of a leaning flank (the coupe's rocker sits a
    little inboard of its shoulder) while excluding the chamfer points that
    have already turned toward the floor.
    """
    stations: dict = {}
    for x, y, z in hull["vertices"]:
        stations.setdefault(round(x, 9), []).append((abs(y), z))
    profile = []
    for x, points in sorted(stations.items()):
        widest = max(reach for reach, _ in points)
        flank = [z for reach, z in points if reach >= widest * 0.9]
        profile.append(
            {
                "x": x,
                "floor": min(z for _, z in points),
                "ceiling": max(z for _, z in points),
                "flank_low": min(flank),
                "flank_high": max(flank),
            }
        )
    return profile


def _station_value(profile: list, key: str, x: float) -> float:
    """One recovered profile value at ``x``, interpolated the way the loft chords run."""
    if x <= profile[0]["x"]:
        return profile[0][key]
    if x >= profile[-1]["x"]:
        return profile[-1][key]
    for first, second in zip(profile, profile[1:], strict=False):
        if first["x"] <= x <= second["x"]:
            reach = second["x"] - first["x"]
            fraction = 0.0 if reach <= 0.0 else (x - first["x"]) / reach
            return first[key] + fraction * (second[key] - first[key])
    return profile[-1][key]


def _classify(archetype: str) -> dict:
    """Sort one body's primitives into components by material and measured shape.

    This is the heart of the suite. Everything downstream asks "is there a
    windscreen" by asking for a glass panel that spans the centreline and sits
    ahead of the cabin's midpoint, never by asking for a primitive called
    ``windscreen``, so renaming a part cannot make a missing part look present.
    """
    parts = vehicle_kit.vehicle_geometry(archetype)
    paint = _of(parts, vehicle_kit.PAINT)
    glass = _of(parts, vehicle_kit.GLASS)
    trim = _of(parts, vehicle_kit.TRIM)
    body = _span(parts)

    # The hull is the paint volume that runs the length of the car; the
    # greenhouse is the paint volume that reaches the roof.
    hull = max(paint, key=lambda part: _bounds(part)["dx"])
    # The tallest PAINT volume, not the tallest volume outright: glazing stands
    # a few millimetres proud of the roofline it lies on, so the topmost part of
    # the whole body is a screen rather than the cabin that carries it.
    greenhouse = max(paint, key=lambda part: _bounds(part)["z"][1])

    # An arch is a thin paint strip on one flank, centred over an axle and
    # rising above the wheel centre. Its Y may vary so the strip can follow a
    # waisted or tapering body instead of floating beside it as a flat ribbon.
    axles = {offset[0] for offset in vehicle_kit.wheel_offsets(archetype).values()}
    wheel_radius = vehicle_kit.PROPORTIONS[archetype]["wheel_radius"]
    arches = [
        part
        for part in paint
        if _flank(part) != 0
        and _bounds(part)["dy"] < 0.10
        and _bounds(part)["dx"] > wheel_radius
        and _bounds(part)["z"][1] > wheel_radius
        and any(abs(_centre(part, 0) - axle) <= 0.05 for axle in axles)
    ]

    # What is left of the paint above the beltline is bonnet and boot: ahead of
    # the cabin it is a hood, behind it a deck, and a deck is what makes a car
    # three-box.
    reserved = {id(hull), id(greenhouse)} | {id(part) for part in arches}
    cabin_floor = _bounds(greenhouse)["z"][0]
    upper = [
        part
        for part in paint
        if id(part) not in reserved and _bounds(part)["z"][0] >= cabin_floor - TOLERANCE
    ]
    cabin_x = _centre(greenhouse, 0)

    # Door furniture is a shallow strip on one flank. The coupe's surface is
    # waisted and its door cuts are raked, so forcing every vertex onto one Y
    # plane would make the test demand the detached graphics it exists to catch.
    surface_trim = [part for part in trim if _flank(part) != 0 and _bounds(part)["dy"] < 0.13]
    seams = [
        part
        for part in surface_trim
        if _bounds(part)["dx"] < 0.12 and _bounds(part)["dy"] < 0.05 and _bounds(part)["dz"] > 0.10
    ]
    beltline = max(_bounds(part)["z"][1] for part in seams)
    solid_trim = [
        part for part in trim if min(_bounds(part)[axis] for axis in ("dx", "dy", "dz")) > 0.0
    ]

    return {
        "parts": parts,
        "body": body,
        "hull": hull,
        "greenhouse": greenhouse,
        "arches": arches,
        "hoods": [part for part in upper if _centre(part, 0) > cabin_x],
        "decks": [part for part in upper if _centre(part, 0) < cabin_x],
        # Glass splits by where it lives, not by how it lies: a screen spans
        # the centreline, a side light sits wholly on one flank. Flatness in Y
        # is not the discriminator, because a side pane may lean in plan to
        # follow a waisted canopy -- the coupe's do.
        "side_panes": [part for part in glass if _flank(part) != 0],
        "screens": [part for part in glass if _flank(part) == 0],
        "seams": seams,
        "door_parts": [part for part in surface_trim if _bounds(part)["z"][0] <= beltline],
        "mirrors": [part for part in solid_trim if _bounds(part)["z"][0] > beltline],
        "front_lights": _of(parts, vehicle_kit.LAMP),
        "rear_lights": _of(parts, vehicle_kit.TAIL),
        "beltline": beltline,
    }


def _tyre(archetype: str) -> dict:
    """The one wheel primitive with real width: the tyre band itself."""
    return next(part for part in vehicle_kit.wheel_geometry(archetype) if _bounds(part)["dy"] > 0.0)


def _wheel_radius(archetype: str) -> float:
    """The tyre's radius, measured off its own vertices."""
    return max(math.hypot(vertex[0], vertex[2]) for vertex in _tyre(archetype)["vertices"])


def _wheel_cloud(archetype: str) -> list:
    """Every wheel vertex, moved to the four corners it is actually built at."""
    wheel = vehicle_kit.wheel_geometry(archetype)
    return [
        (offset[0] + vertex[0], offset[1] + vertex[1], offset[2] + vertex[2])
        for offset in vehicle_kit.wheel_offsets(archetype).values()
        for part in wheel
        for vertex in part["vertices"]
    ]


def _shape(archetype: str, kit: dict) -> dict:
    """One archetype's silhouette, entirely in measured ratios.

    Every number is read off vertices. ``cabin_share`` and ``cabin_centre`` come
    from the greenhouse volume the kit emitted, not from the cabin fractions
    that positioned it.
    """
    body = kit["body"]
    cabin = _bounds(kit["greenhouse"])
    length = body["dx"]
    return {
        "length": length,
        "width": body["dy"],
        "height": body["z"][1],
        "roof_over_length": body["z"][1] / length,
        "width_over_length": body["dy"] / length,
        "cabin_share": cabin["dx"] / length,
        "cabin_centre": _centre(kit["greenhouse"], 0) / length,
        "wheel_over_length": _wheel_radius(archetype) / length,
        "three_box": bool(kit["decks"]),
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(name="kits", scope="module")
def kits_fixture() -> dict:
    """Every archetype's body, classified by measured geometry, built once."""
    return {name: _classify(name) for name in vehicle_kit.ARCHETYPES}


@pytest.fixture(name="shapes", scope="module")
def shapes_fixture(kits: dict) -> dict:
    """Every archetype's measured silhouette, computed once."""
    return {name: _shape(name, kit) for name, kit in kits.items()}


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------


def test_every_archetype_has_proportions_and_a_planned_envelope() -> None:
    """The vocabulary, the design table and the reservation are one set.

    Catches an archetype added to one of the three and forgotten in the others,
    which would either build an unplanned vehicle or reserve road space for a
    vehicle that cannot be built.
    """
    assert set(vehicle_kit.ARCHETYPES) == set(vehicle_kit.PROPORTIONS)
    assert set(vehicle_kit.ARCHETYPES) == set(vehicle_kit.RESERVED_PLANNING_ENVELOPE)
    assert len(vehicle_kit.MATERIAL_SLOTS) == 5


def test_an_unknown_archetype_is_refused() -> None:
    """A vehicle the kit cannot build is refused, never approximated.

    Catches a silent fallback to some default body, which would put a vehicle
    on the road that no planner ever reserved space for.
    """
    with pytest.raises(vehicle_kit.VehicleKitError):
        vehicle_kit.vehicle_geometry("hovercraft")


BRANDS = re.compile(
    r"\b(ferrari|mclaren|lamborghini|porsche|mercedes|bmw|audi|toyota|honda|ford|tesla|"
    r"volkswagen|nissan|bentley|rolls[\- ]?royce|jaguar|maserati|bugatti|aston[\- ]martin)\b",
    re.IGNORECASE,
)


def test_nothing_in_the_kit_names_a_real_manufacturer() -> None:
    """Familiar but not over-literal, enforced on the source itself.

    An archetype is a set of numbers. If a manufacturer's name appeared anywhere
    in this file it would mean somebody had started modelling a specific car,
    which is the one thing the visual direction forbids. The pattern is anchored
    on word boundaries so that ordinary English -- "affordable" -- is not
    mistaken for a badge.
    """
    source = (SCRIPTS_DIR / "vehicle_kit.py").read_text(encoding="utf-8")
    for match in BRANDS.finditer(source):
        line = source[: match.start()].count("\n") + 1
        raise AssertionError(f"vehicle_kit.py names {match.group(0)!r} on line {line}")


def test_the_archetype_names_stay_generic() -> None:
    """Five body styles, described by shape rather than by product.

    Catches an archetype renamed to something that reads as a specific car
    rather than as a category of car.
    """
    for name in vehicle_kit.ARCHETYPES:
        assert name.isalpha() and name.islower(), name
        assert not BRANDS.search(name), name


# ---------------------------------------------------------------------------
# The envelope -- the load-bearing invariant
# ---------------------------------------------------------------------------


def test_the_measured_geometry_fits_the_planned_envelope_on_every_axis() -> None:
    """Nothing the kit builds may grow out of the box the lane network planned in.

    This is THE test. Lane widths, headways and turning fillets were all derived
    from RESERVED_PLANNING_ENVELOPE before the body was reshaped, so a vehicle that
    measures larger than its reservation on any axis is a vehicle that
    physically overhangs a lane it is legally inside -- and nobody would re-run
    the plan, because nothing in the pipeline reads the sculpture.
    """
    failures = []
    for name in vehicle_kit.ARCHETYPES:
        planned = vehicle_kit.RESERVED_PLANNING_ENVELOPE[name]
        measured = vehicle_kit.measured_visual_bounds(name)
        for axis in AXES:
            if measured[axis] > planned[axis] + TOLERANCE:
                failures.append(
                    f"{name} {axis}: built {measured[axis]:.4f} > planned {planned[axis]:.4f} "
                    f"(over by {measured[axis] - planned[axis]:.4f} m)"
                )
    assert not failures, "geometry grew out of the planned envelope:\n" + "\n".join(failures)


def test_the_measured_visual_bounds_is_what_the_vertices_actually_occupy() -> None:
    """The reported measurement must be a measurement, wheels included.

    Catches ``measured_visual_bounds`` drifting into reporting the design table, or
    forgetting the four wheels -- which are separate objects, and are exactly
    the part of a vehicle a kerb would hit.
    """
    for name in vehicle_kit.ARCHETYPES:
        body = vehicle_kit.vehicle_geometry(name)
        cloud = [vertex for part in body for vertex in part["vertices"]]
        cloud.extend(_wheel_cloud(name))
        box = _box(cloud)
        measured = vehicle_kit.measured_visual_bounds(name)
        assert measured["length"] == pytest.approx(box["dx"], abs=1.0e-5), name
        assert measured["width"] == pytest.approx(box["dy"], abs=1.0e-5), name
        assert measured["height"] == pytest.approx(box["z"][1], abs=1.0e-5), name


def test_envelope_headroom_is_positive_on_every_axis() -> None:
    """Headroom is the same claim stated as a margin, and it must agree.

    Catches the reporting helper and the measurement disagreeing, which would
    let a reviewer read a comfortable margin off a vehicle that does not fit.
    """
    for name in vehicle_kit.ARCHETYPES:
        planned = vehicle_kit.RESERVED_PLANNING_ENVELOPE[name]
        measured = vehicle_kit.measured_visual_bounds(name)
        headroom = vehicle_kit.envelope_headroom(name)
        for axis in AXES:
            assert headroom[axis] == pytest.approx(planned[axis] - measured[axis], abs=1.0e-5)
            assert headroom[axis] >= 0.0, (name, axis, headroom)


def test_every_single_component_sits_inside_the_reservation() -> None:
    """Containment is proved part by part, not by a bounding box over the car.

    A whole-vehicle box is dominated by the body, so a mirror, a lamp or a
    fender lip can hang outside the reservation while every aggregate number
    still reads as comfortable. The lane network would not know that detail was
    there. This asks each emitted lump on its own, wheels moved to the corners
    they are actually fitted at.
    """
    failures = []
    for name in vehicle_kit.ARCHETYPES:
        for entry in vehicle_kit.component_containment(name):
            if not entry["contained"]:
                failures.append(f"{name} {entry['component']} ({entry['kind']}): {entry['slack']}")
    assert not failures, "components escaped the reservation:\n" + "\n".join(failures)


def test_the_envelope_contract_states_both_numbers_and_agrees_with_them() -> None:
    """The reservation and the measurement are reported separately, and honestly.

    Catches a contract that echoes one number twice -- which is precisely the
    confusion the rename exists to end -- and one that claims containment while
    naming escaped components.
    """
    for name in vehicle_kit.ARCHETYPES:
        contract = vehicle_kit.envelope_contract(name)
        assert contract["archetype"] == name
        reserved = vehicle_kit.RESERVED_PLANNING_ENVELOPE[name]
        assert contract["reserved_planning_envelope"] == reserved
        assert contract["measured_visual_bounds"] == vehicle_kit.measured_visual_bounds(name)
        assert contract["headroom"] == vehicle_kit.envelope_headroom(name)
        assert contract["components"] == len(vehicle_kit.component_containment(name))
        assert contract["escaped"] == []
        assert contract["contained"] is True
        for axis in AXES:
            assert (
                contract["measured_visual_bounds"][axis]
                <= contract["reserved_planning_envelope"][axis] + TOLERANCE
            ), (name, axis)


def test_the_contract_notices_a_component_that_escapes() -> None:
    """The containment proof must be capable of FAILING.

    A checker that cannot fail proves nothing, and this one is the only thing
    standing between a restyle and geometry the traffic plan does not know
    about. Shrink the reservation under a real archetype and the escape has to
    be named.
    """
    name = "coupe"
    real = vehicle_kit.RESERVED_PLANNING_ENVELOPE[name]
    vehicle_kit.RESERVED_PLANNING_ENVELOPE[name] = {
        "length": real["length"],
        "width": real["width"] * 0.5,
        "height": real["height"],
    }
    try:
        contract = vehicle_kit.envelope_contract(name)
        assert contract["contained"] is False
        assert contract["escaped"], "a halved reservation must name escaped components"
    finally:
        vehicle_kit.RESERVED_PLANNING_ENVELOPE[name] = real
    assert vehicle_kit.envelope_contract(name)["contained"] is True


def test_the_envelope_contracts_cover_every_archetype() -> None:
    """The manifest view is the per-archetype view, for all five."""
    contracts = vehicle_kit.envelope_contracts()
    assert set(contracts) == set(vehicle_kit.ARCHETYPES)
    for name, contract in contracts.items():
        assert contract == vehicle_kit.envelope_contract(name)


def test_the_planners_keep_reading_the_reservation_not_the_sculpture() -> None:
    """``vehicle_dimensions`` must report the reserved box, exactly.

    Catches somebody quietly re-pointing the planners at measured geometry. That
    would look like an improvement and would silently re-plan the city's
    traffic: reshaping a car -- even shrinking it -- would move lane widths,
    headways and fillets, and change which streets carry cars at all.
    """
    for name in vehicle_kit.ARCHETYPES:
        planned = vehicle_kit.RESERVED_PLANNING_ENVELOPE[name]
        reported = vehicle_kit.vehicle_dimensions(name)
        for axis in AXES:
            assert reported[axis] == planned[axis], (name, axis, reported[axis], planned[axis])
        measured = vehicle_kit.measured_visual_bounds(name)
        for axis in AXES:
            assert reported[f"measured_{axis}"] == measured[axis], (name, axis)
    assert vehicle_kit.widest_vehicle() == max(
        entry["width"] for entry in vehicle_kit.RESERVED_PLANNING_ENVELOPE.values()
    )
    assert vehicle_kit.longest_vehicle() == max(
        entry["length"] for entry in vehicle_kit.RESERVED_PLANNING_ENVELOPE.values()
    )


def test_no_wheel_stands_outside_the_planned_half_width() -> None:
    """A wheel proud of the reservation is an envelope the planner never sees.

    Arches expose the wheels now, so the temptation is to push them outboard
    until they read. That trades a visible wheel for a vehicle that clips a kerb
    the lane network believes it clears, on the exact part that would clip it.
    """
    for name in vehicle_kit.ARCHETYPES:
        planned_half = vehicle_kit.RESERVED_PLANNING_ENVELOPE[name]["width"] / 2.0
        outer = max(abs(vertex[1]) for vertex in _wheel_cloud(name))
        assert outer <= planned_half + TOLERANCE, (name, outer, planned_half)


def test_the_wheels_carry_the_car_and_the_body_never_touches_the_road() -> None:
    """A hull resting on the road would leave the wheels nothing to do.

    Also catches an axle placed at the wrong height: the four offsets sit at
    wheel radius precisely so the tyres reach the ground plane and the body
    does not.
    """
    for name in vehicle_kit.ARCHETYPES:
        radius = _wheel_radius(name)
        body_low = _span(vehicle_kit.vehicle_geometry(name))["z"][0]
        wheel_low = min(vertex[2] for vertex in _wheel_cloud(name))
        assert body_low > wheel_low, (name, body_low, wheel_low)
        assert wheel_low >= 0.0, (name, wheel_low)
        # A faceted tyre rests on a chord, so it clears the road by the sagitta
        # of one facet and no more.
        assert wheel_low < radius * 0.05, (name, wheel_low, radius)


# ---------------------------------------------------------------------------
# Required components, recovered by geometry and material
# ---------------------------------------------------------------------------


def test_every_archetype_carries_the_whole_required_component_set(kits: dict) -> None:
    """A car with no windows, no doors and no lights is a crate.

    Every component is recovered by material plus measured shape, so this
    catches a part that was deleted, collapsed to nothing, or renamed into
    invisibility -- none of which a name-based check would notice.
    """
    for name, kit in kits.items():
        assert _bounds(kit["hull"])["dx"] >= kit["body"]["dx"] * 0.95, name
        assert _bounds(kit["greenhouse"])["dz"] > 0.05, name
        assert len(kit["screens"]) >= 2, (name, len(kit["screens"]))
        assert len(kit["side_panes"]) >= 2, (name, len(kit["side_panes"]))
        assert len(kit["seams"]) >= 2, (name, len(kit["seams"]))
        assert len(kit["mirrors"]) == 2, (name, len(kit["mirrors"]))
        assert len(kit["front_lights"]) >= 2, (name, len(kit["front_lights"]))
        assert len(kit["rear_lights"]) >= 2, (name, len(kit["rear_lights"]))
        assert len(kit["arches"]) == 4, (name, len(kit["arches"]))


def test_the_cabin_sits_on_the_hull_rather_than_beside_it(kits: dict) -> None:
    """The greenhouse must start where the lower body stops.

    Catches a cabin floating above the hull or sunk into it, either of which
    leaves a seam of daylight or a doubled surface along the beltline.
    """
    for name, kit in kits.items():
        hull = _bounds(kit["hull"])
        cabin = _bounds(kit["greenhouse"])
        if name == "coupe":
            for entry in vehicle_kit.COUPE_CANOPY_PROFILE:
                x = float(entry["x"])
                base = vehicle_kit._coupe_hull_top_at(x)
                contact = [
                    vertex
                    for vertex in kit["greenhouse"]["vertices"]
                    if vertex[0] == pytest.approx(x, abs=1.0e-9)
                    and vertex[2] == pytest.approx(base, abs=1.0e-9)
                ]
                assert len(contact) >= 2, (name, x, base)
        else:
            assert cabin["z"][0] == pytest.approx(hull["z"][1], abs=1.0e-6), name
        assert cabin["y"][1] < hull["y"][1], (name, cabin["y"][1], hull["y"][1])
        assert cabin["dx"] < hull["dx"], name


def test_each_wheel_arch_frames_a_wheel(kits: dict) -> None:
    """Four arches, one per corner, each rising over the wheel it belongs to.

    Catches an arch drawn at the wrong station or flattened into the flank,
    which would leave a wheel emerging from a plain slab.
    """
    for name, kit in kits.items():
        radius = _wheel_radius(name)
        corners = set(vehicle_kit.wheel_offsets(name).values())
        for arch in kit["arches"]:
            box = _bounds(arch)
            assert box["z"][1] > radius, (name, box["z"][1], radius)
            assert box["dx"] > radius, (name, box["dx"], radius)
            matched = [
                corner
                for corner in corners
                if abs(_centre(arch, 0) - corner[0]) <= 0.05
                and corner[1] * (box["y"][0] + box["y"][1]) > 0.0
            ]
            assert len(matched) == 1, (name, matched)
        assert len({_flank(arch) for arch in kit["arches"]}) == 2, name


def test_the_coupe_arch_lips_follow_its_emitted_flank(kits: dict) -> None:
    """The exotic's arch may not be a flat ribbon detached from a tapered hull."""
    for arch in kits["coupe"]["arches"]:
        vertices = arch["vertices"]
        outer = vertices[len(vertices) // 2 :]
        standoff = [
            abs(vertex[1]) - vehicle_kit._coupe_side_y(vertex[0], vertex[2]) for vertex in outer
        ]
        assert standoff == pytest.approx([0.002] * len(outer), abs=1.0e-6), arch["name"]


def test_every_mesh_face_indexes_a_real_vertex() -> None:
    """A face pointing past the end of the vertex list is not geometry.

    Catches an off-by-one in the welder, which Blender would import as a
    corrupt mesh rather than as a car.
    """
    for name in vehicle_kit.ARCHETYPES:
        for mesh in (vehicle_kit.vehicle_mesh(name), vehicle_kit.wheel_mesh(name)):
            count = len(mesh["vertices"])
            assert len(mesh["faces"]) == len(mesh["materials"])
            for face in mesh["faces"]:
                assert len(face) >= 3
                assert len(set(face)) == len(face)
                assert all(0 <= index < count for index in face)


def test_every_face_uses_a_declared_material_slot() -> None:
    """Five slots, and nothing may reach past them.

    Catches a face assigned a slot the applier never creates, which renders as
    whatever material happens to sit at that index.
    """
    declared = set(range(len(vehicle_kit.MATERIAL_SLOTS)))
    for name in vehicle_kit.ARCHETYPES:
        for mesh in (vehicle_kit.vehicle_mesh(name), vehicle_kit.wheel_mesh(name)):
            assert set(mesh["materials"]) <= declared, (name, set(mesh["materials"]))


# ---------------------------------------------------------------------------
# Glazing: windows must be windows, and there must be more than one
# ---------------------------------------------------------------------------


def test_side_glazing_exists_on_both_flanks(kits: dict) -> None:
    """A car glazed down one side only is a car nobody can film from the left.

    Catches a mirroring loop that emitted one side, or that emitted both at the
    same Y.
    """
    for name, kit in kits.items():
        by_flank = {1: [], -1: []}
        for pane in kit["side_panes"]:
            by_flank[_flank(pane)].append(pane)
        assert len(by_flank[1]) >= 2, (name, len(by_flank[1]))
        assert len(by_flank[-1]) >= 2, (name, len(by_flank[-1]))
        # Both reaches of each pane, because a pane that follows a waisted
        # cabin spans a band of Y rather than a single plane of it.
        left = sorted(
            tuple(sorted(round(abs(value), 9) for value in _bounds(pane)["y"]))
            for pane in by_flank[1]
        )
        right = sorted(
            tuple(sorted(round(abs(value), 9) for value in _bounds(pane)["y"]))
            for pane in by_flank[-1]
        )
        assert left == right, name


def test_a_windscreen_and_a_rear_screen_face_opposite_ends(kits: dict) -> None:
    """One screen ahead of the cabin, one behind, and they must not be the same.

    Catches a rear screen built at the windscreen's station, which would leave
    the back of the car blind and the front doubled.
    """
    for name, kit in kits.items():
        screens = sorted(kit["screens"], key=lambda part: _centre(part, 0))
        assert len(screens) >= 2, (name, len(screens))
        rear, front = screens[0], screens[-1]
        cabin_x = _centre(kit["greenhouse"], 0)
        assert _centre(front, 0) > cabin_x, (name, _centre(front, 0), cabin_x)
        assert _centre(rear, 0) < cabin_x, (name, _centre(rear, 0), cabin_x)
        for screen in (front, rear):
            box = _bounds(screen)
            assert box["y"][0] < 0.0 < box["y"][1], name
            assert box["dz"] > 0.05, (name, box["dz"])


def test_every_archetype_splits_its_side_glazing_at_a_b_pillar(kits: dict) -> None:
    """One long black slab down the side is what makes a generated car read as a box.

    Every archetype must carry a front and a rear side pane per flank with a
    real gap between them in X. The gap is the B pillar, and it has to be
    geometry rather than a texture, or it disappears the moment the car is
    lit. The coupe is held to it like everyone else: its door light and
    quarter light break at a measured 60 mm buttress pillar.
    """
    for name in vehicle_kit.ARCHETYPES:
        kit = kits[name]
        for flank in (1, -1):
            panes = sorted(
                (pane for pane in kit["side_panes"] if _flank(pane) == flank),
                key=lambda part: _centre(part, 0),
            )
            assert len(panes) >= 2, (name, flank, len(panes))
            gaps = [
                _bounds(later)["x"][0] - _bounds(earlier)["x"][1]
                for earlier, later in zip(panes, panes[1:], strict=False)
            ]
            assert min(gaps) > 0.03, (name, flank, gaps)


def test_no_side_pane_spans_the_whole_cabin(kits: dict) -> None:
    """A single pane running the length of the cabin is the slab this split exists to avoid.

    Catches a split whose divider collapsed to nothing, leaving one pane doing
    the work of two.
    """
    for name, kit in kits.items():
        cabin = _bounds(kit["greenhouse"])["dx"]
        for pane in kit["side_panes"]:
            share = _bounds(pane)["dx"] / cabin
            assert share < 0.70, (name, share)


def _pane_standoffs(kit: dict, pane: dict) -> list:
    """The pane's measured standoff off the cabin skin, at every station that matters.

    A pane owns two stations and travels on a straight chord between them,
    while the cabin's half width may bend at any of ITS stations inside that
    span -- so the honest sample set is both families: the pane's own ends,
    and every cabin station the pane crosses.
    """
    ends: dict = {}
    for x, y, _z in pane["vertices"]:
        ends[round(x, 9)] = abs(y)
    (x0, reach0), (x1, reach1) = sorted(ends.items())

    def reach(x: float) -> float:
        fraction = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
        return reach0 + fraction * (reach1 - reach0)

    cabin_stations = sorted({round(vertex[0], 9) for vertex in kit["greenhouse"]["vertices"]})
    samples = [x0, x1] + [x for x in cabin_stations if x0 < x < x1]
    return [reach(x) - _cabin_half_at(kit["greenhouse"], x) for x in samples]


def test_glazing_is_visible_from_outside_the_cabin_it_sits_in(kits: dict) -> None:
    """Glass buried under paint is not a window, however correctly it is modelled.

    The kit declares GLASS_PROUD for exactly this: glass and body must not be
    coplanar or they z-fight, so the panel stands off the surface it sits in.
    Standing it off on the WRONG SIDE puts it inside a closed, opaque paint
    volume, where it renders as nothing at all -- and every other glazing test
    in this file still passes, because the panel is present, split, and
    correctly proportioned. It is merely invisible. Held station by station,
    because a pane that follows the cabin's own width must clear the skin at
    every station it crosses, not merely on the aggregate.
    """
    assert vehicle_kit.GLASS_PROUD > 0.005
    failures = []
    for name, kit in kits.items():
        for pane in kit["side_panes"]:
            worst = min(_pane_standoffs(kit, pane))
            if worst <= TOLERANCE:
                failures.append(
                    f"{name} {pane['name']}: glass sits {-worst:.4f} m INSIDE the cabin skin"
                )
    assert not failures, "glazing is buried inside the opaque cabin:\n" + "\n".join(failures)


def test_side_glazing_hugs_the_skin_it_stands_off(kits: dict) -> None:
    """A pane must stand off the paint, and only just.

    GLASS_PROUD is a floor and NEAR-ceiling at once. Below it, glass z-fights
    the paint or vanishes inside it; far above it, the pane reads as a dark
    sheet hanging beside the car -- which is what standing a pane off the
    widest station of a whole run produced over the coupe's widening canopy:
    43 mm of daylight under the quarter light's leading edge. The cabin may
    pull away a little from a pane's chord between the pane's own stations,
    so the ceiling is a small multiple of the declared standoff rather than
    the standoff itself.
    """
    for name, kit in kits.items():
        for pane in kit["side_panes"]:
            standoffs = _pane_standoffs(kit, pane)
            low, high = min(standoffs), max(standoffs)
            assert low >= vehicle_kit.GLASS_PROUD - TOLERANCE, (name, pane["name"], low)
            assert high <= 0.020, (name, pane["name"], high)


def test_glazing_never_reaches_outside_the_body_it_belongs_to(kits: dict) -> None:
    """A window may stand proud of its cabin; it may not float off the car.

    Catches an inset applied so generously that the glass clears the bodywork
    entirely and reads as a floating sheet.
    """
    for name, kit in kits.items():
        body = kit["body"]
        for pane in kit["side_panes"] + kit["screens"]:
            box = _bounds(pane)
            reach = max(abs(box["y"][0]), abs(box["y"][1]))
            assert box["z"][1] <= body["z"][1] + TOLERANCE, (name, pane["name"])
            assert reach <= body["dy"] / 2.0 + TOLERANCE, (name, pane["name"])
            assert box["z"][0] > kit["beltline"] - TOLERANCE, (name, pane["name"])


# ---------------------------------------------------------------------------
# Doors
# ---------------------------------------------------------------------------


def test_door_seams_sit_below_the_glazing_on_both_flanks(kits: dict) -> None:
    """Doors live under the windows, and a car has doors on both sides.

    Catches a seam drawn across a window, which reads as a crack in the glass,
    and a seam family emitted for one flank only.
    """
    for name, kit in kits.items():
        glass_low = min(_bounds(pane)["z"][0] for pane in kit["side_panes"])
        for flank in (1, -1):
            seams = [seam for seam in kit["seams"] if _flank(seam) == flank]
            assert len(seams) >= 2, (name, flank, len(seams))
            for seam in seams:
                assert _bounds(seam)["z"][1] <= glass_low + TOLERANCE, (name, seam["name"])


def test_door_seams_overlap_the_body_side_they_are_cut_into(kits: dict) -> None:
    """A seam floating above or below the flank is a stripe, not a door.

    Held at each seam's OWN stations, never against the hull's aggregate z
    band. The aggregate is dominated by the deepest part of the body, so a
    seam drawn across a wheel opening -- where the flank has lifted away for
    the tyre and survives only near the beltline -- still "overlapped the
    hull" while a 300 mm run of it hung in open air over the wheel. The local
    flank band at the seam's two x extremes is what the seam must live inside.
    """
    for name, kit in kits.items():
        profile = _hull_profile(kit["hull"])
        for seam in kit["seams"]:
            box = _bounds(seam)
            for x in box["x"]:
                floor = _station_value(profile, "flank_low", x)
                ceiling = _station_value(profile, "flank_high", x)
                assert box["z"][0] >= floor - TOLERANCE, (name, seam["name"], x, box["z"], floor)
                assert box["z"][1] <= ceiling + TOLERANCE, (
                    name,
                    seam["name"],
                    x,
                    box["z"],
                    ceiling,
                )


def test_no_door_part_floats_outside_the_body(kits: dict) -> None:
    """Door furniture hugs the flank, and stays inside the reservation.

    Catches a seam or handle drifting off the side of the car -- visible as
    detail hovering beside the bodywork -- and catches any of it growing out of
    the planned width, where the lane network would not know it was there.
    """
    for name, kit in kits.items():
        planned_half = vehicle_kit.RESERVED_PLANNING_ENVELOPE[name]["width"] / 2.0
        flank = _bounds(kit["hull"])["y"][1]
        for part in kit["door_parts"]:
            reach = max(abs(value) for value in _bounds(part)["y"])
            assert reach <= planned_half + TOLERANCE, (name, part["name"], reach, planned_half)
            assert reach >= flank * 0.90, (name, part["name"], reach, flank)


# ---------------------------------------------------------------------------
# Wheel wells
# ---------------------------------------------------------------------------


def test_every_wheel_well_is_backed_by_a_dark_liner(kits: dict) -> None:
    """A camera must never see straight through the body over a tyre.

    The arch is cut wider than the wheel on purpose -- a tyre that fouls its
    fender only while TURNING is the worst defect the kit can ship -- and both
    flanks cut the same opening at the same height. Without an occluder, a
    side-on view therefore reads a bright wedge of background clean through
    the car at the top of each arch: in one opening, across the hollow hull,
    out the other. So every wheel demands a dark part parked inboard of its
    tyre that spans the whole opening -- from the body's own floor line to the
    crest of the arch cut, across at least the tyre's diameter. Recovered by
    material and measured shape, never by name.
    """
    for name, kit in kits.items():
        profile = _hull_profile(kit["hull"])
        hull_floor = min(entry["floor"] for entry in profile)
        radius = _wheel_radius(name)
        tyre_half = _bounds(_tyre(name))["dy"] / 2.0
        dark = _of(kit["parts"], vehicle_kit.TRIM)
        for corner, offset in vehicle_kit.wheel_offsets(name).items():
            axle, track = offset[0], offset[1]
            inner_face = abs(track) - tyre_half
            crest = _station_value(profile, "floor", axle)
            liners = [
                part
                for part in dark
                if _flank(part) == (1 if track > 0 else -1)
                and max(abs(value) for value in _bounds(part)["y"]) < inner_face - TOLERANCE
                and _bounds(part)["x"][0] <= axle - radius + TOLERANCE
                and _bounds(part)["x"][1] >= axle + radius - TOLERANCE
                and _bounds(part)["z"][1] >= crest - TOLERANCE
                and _bounds(part)["z"][0] <= hull_floor + TOLERANCE
            ]
            assert liners, (name, corner, "no occluder spans this wheel opening")


def test_no_tyre_intersects_the_fender_it_turns_inside(kits: dict) -> None:
    """The arch opening must clear the tyre's swept circle at every station.

    The dangerous comparison is against the CIRCLE the tyre's vertices sweep
    when the wheel turns, not against the parked polygon: the arch cut is a
    run of chords, and a chord that dips inside the circle fouls a moving
    wheel on frames a still inspection never sees. Sampled densely across
    each wheel span, off the hull the kit actually emitted.
    """
    for name, kit in kits.items():
        profile = _hull_profile(kit["hull"])
        radius = _wheel_radius(name)
        for corner, offset in vehicle_kit.wheel_offsets(name).items():
            axle = offset[0]
            for step in range(-100, 101):
                span = radius * step / 100.0
                circle = radius + math.sqrt(max(radius * radius - span * span, 0.0))
                floor = _station_value(profile, "floor", axle + span)
                assert floor >= circle - TOLERANCE, (name, corner, axle + span, floor, circle)


# ---------------------------------------------------------------------------
# Lights
# ---------------------------------------------------------------------------


def test_the_two_light_families_use_different_materials(kits: dict) -> None:
    """A viewer must be able to tell which end of a distant car is the front.

    Warm lamps and red tails are the whole cue at diorama distance, so they may
    never collapse onto one slot.
    """
    assert vehicle_kit.LAMP != vehicle_kit.TAIL
    for name, kit in kits.items():
        assert {part["material"] for part in kit["front_lights"]} == {vehicle_kit.LAMP}, name
        assert {part["material"] for part in kit["rear_lights"]} == {vehicle_kit.TAIL}, name


def test_front_lights_face_forward_and_rear_lights_face_back(kits: dict) -> None:
    """Local +X is the direction the vehicle faces, so the lamps must respect it.

    Catches the light families swapped end for end, which would send a whole
    lane of traffic down the street showing red at the front.
    """
    for name, kit in kits.items():
        nose = kit["body"]["x"][1]
        tail = kit["body"]["x"][0]
        for lamp in kit["front_lights"]:
            box = _bounds(lamp)["x"]
            assert box[0] > 0.0, (name, lamp["name"], box)
            assert box[1] > nose - (nose - tail) * 0.15, (name, lamp["name"], box)
        for lamp in kit["rear_lights"]:
            box = _bounds(lamp)["x"]
            assert box[1] < 0.0, (name, lamp["name"], box)
            assert box[0] < tail + (nose - tail) * 0.15, (name, lamp["name"], box)


def test_the_lights_are_paired_across_the_centreline(kits: dict) -> None:
    """One headlight is a motorcycle; two make a car.

    Catches a light family that lost its mirror, which reads as a broken lamp
    rather than as a design.
    """
    for name, kit in kits.items():
        for family in ("front_lights", "rear_lights"):
            flanks = [_flank(lamp) for lamp in kit[family]]
            assert flanks.count(1) >= 1, (name, family)
            assert flanks.count(-1) >= 1, (name, family)


def test_every_lamp_stands_proud_of_the_body_it_is_let_into(kits: dict) -> None:
    """A lens inside the paint renders as nothing at all.

    The kit's own history says so: eight of ten light families once measured
    zero visible lens area because their faces sat behind the bodywork. The
    glazing carries a proudness test; the lamps -- the other family that
    failed exactly that way -- get one too. An end-mounted lamp must poke
    past the nose or tail cap it is let into. A lamp lying on the hull's top
    must clear that top along EVERY edge of every face, because a straight
    chord strung between two lifted corners can still dive through a crease
    in the surface between them -- measured at 2 mm inside the coupe's
    bonnet before its crease was pinned into the lamp rings.
    """
    for name, kit in kits.items():
        profile = _hull_profile(kit["hull"])
        hull = _bounds(kit["hull"])
        for lamp in kit["front_lights"] + kit["rear_lights"]:
            box = _bounds(lamp)
            if box["x"][1] > hull["x"][1]:
                assert box["x"][1] >= hull["x"][1] + 0.002, (name, lamp["name"], box["x"])
                continue
            if box["x"][0] < hull["x"][0]:
                assert box["x"][0] <= hull["x"][0] - 0.002, (name, lamp["name"], box["x"])
                continue
            for face in lamp["faces"]:
                for start, end in zip(face, face[1:] + face[:1], strict=True):
                    a = lamp["vertices"][start]
                    b = lamp["vertices"][end]
                    for step in range(65):
                        fraction = step / 64.0
                        x = a[0] + fraction * (b[0] - a[0])
                        z = a[2] + fraction * (b[2] - a[2])
                        top = _station_value(profile, "ceiling", x)
                        assert z >= top + 0.002 - TOLERANCE, (name, lamp["name"], x, z - top)


# ---------------------------------------------------------------------------
# Silhouette: five archetypes must be five shapes
# ---------------------------------------------------------------------------


def test_the_coupe_is_the_lowest_and_the_flattest(shapes: dict) -> None:
    """A sports coupe reads by being low, and it is measured, not asserted.

    Catches a coupe that has crept up towards the sedan, at which point the two
    are one shape at two sizes.
    """
    assert min(shapes, key=lambda name: shapes[name]["height"]) == "coupe", {
        name: round(shapes[name]["height"], 4) for name in shapes
    }
    assert min(shapes, key=lambda name: shapes[name]["roof_over_length"]) == "coupe", {
        name: round(shapes[name]["roof_over_length"], 4) for name in shapes
    }


def test_the_van_is_the_tallest(shapes: dict) -> None:
    """A van reads as a van by being a box.

    Catches a van that stopped towering over the traffic it shares a lane with.
    """
    assert max(shapes, key=lambda name: shapes[name]["height"]) == "van", {
        name: round(shapes[name]["height"], 4) for name in shapes
    }


def test_the_suv_stands_taller_than_the_sedan(shapes: dict) -> None:
    """Two similar-length bodies must still be told apart at a glance.

    Catches the SUV and the sedan converging, which is the easiest silhouette
    collision to introduce and the hardest to see in a wireframe.
    """
    assert shapes["suv"]["height"] > shapes["sedan"]["height"] + 0.2, (
        shapes["suv"]["height"],
        shapes["sedan"]["height"],
    )


def test_the_compact_is_the_shortest(shapes: dict) -> None:
    """A compact is compact.

    Catches a compact that grew until it needed the headway of a saloon.
    """
    assert min(shapes, key=lambda name: shapes[name]["length"]) == "compact", {
        name: round(shapes[name]["length"], 4) for name in shapes
    }


def test_three_box_archetypes_carry_a_measured_boot_deck(kits: dict, shapes: dict) -> None:
    """A saloon and a coupe have a boot; a hatch, an estate and a van do not.

    This is the difference between a two-box and a three-box car, and it is the
    clearest silhouette cue after height. The deck is looked for as PAINT
    geometry standing above the beltline BEHIND the cabin, so declaring a deck
    fraction in the proportions table is not enough -- the volume has to be
    emitted. Catches a deck whose builder bailed out on a length or height
    guard and left the archetype silently two-box.
    """
    built = {name: bool(kits[name]["decks"]) for name in vehicle_kit.ARCHETYPES}
    expected = {name: name in THREE_BOX for name in vehicle_kit.ARCHETYPES}
    assert built == expected, f"three-box geometry disagrees with intent: {built}"
    for name in THREE_BOX:
        deck = max(kits[name]["decks"], key=lambda part: _bounds(part)["dz"])
        assert _bounds(deck)["dz"] > 0.05, (name, _bounds(deck)["dz"])
        assert shapes[name]["three_box"] is True, name
    for name in TWO_BOX:
        assert shapes[name]["three_box"] is False, name


def test_no_two_archetypes_share_a_silhouette(shapes: dict) -> None:
    """Five archetypes must be five shapes, not one shape at five sizes.

    A uniform scale preserves every PROPORTION, so the comparison is a vector of
    ratios rather than any single dimension. That matters here: a compact and a
    small SUV really do share a height-to-length ratio, and demanding they
    differ in height alone would be demanding a distinction the real vehicles do
    not have. What they must not share is the whole shape.
    """
    keys = (
        "roof_over_length",
        "width_over_length",
        "cabin_share",
        "cabin_centre",
        "wheel_over_length",
    )
    for first, second in combinations(vehicle_kit.ARCHETYPES, 2):
        spread = max(abs(shapes[first][key] - shapes[second][key]) for key in keys)
        assert spread > 0.04, (first, second, spread)


def test_the_cabin_is_placed_differently_on_every_archetype(shapes: dict) -> None:
    """Where the cabin sits along the body is half of what makes a body style.

    Catches five bodies that differ only in scale, with the greenhouse parked at
    the same fraction of the length on all of them.
    """
    assert max(shapes, key=lambda name: shapes[name]["cabin_share"]) == "van", {
        name: round(shapes[name]["cabin_share"], 4) for name in shapes
    }
    # The exotic carries the most COMPACT cockpit of the five. Its cabin sits
    # forward, not aft: a mid-engined car puts the cabin over the front axle and
    # spends the rest of the body on a long rear deck, which is the opposite of
    # the fastback the first cut of this archetype drew.
    assert min(shapes, key=lambda name: shapes[name]["cabin_share"]) == "coupe", {
        name: round(shapes[name]["cabin_share"], 4) for name in shapes
    }
    centres = sorted(round(shapes[name]["cabin_centre"], 4) for name in shapes)
    assert all(b - a > 0.01 for a, b in zip(centres, centres[1:], strict=False)), centres


# ---------------------------------------------------------------------------
# Wheels
# ---------------------------------------------------------------------------


def test_a_wheel_is_emitted_in_its_own_axle_frame() -> None:
    """A wheel that cannot be given its own origin cannot be made to turn.

    Catches wheel geometry baked at a body station, which would make the
    applier's per-wheel rotation swing the tyre around the car.
    """
    for name in vehicle_kit.ARCHETYPES:
        radius = _wheel_radius(name)
        for part in vehicle_kit.wheel_geometry(name):
            for x, _y, z in part["vertices"]:
                assert math.hypot(x, z) <= radius + TOLERANCE, (name, part["name"])


def test_a_wheel_is_round_enough_to_read_as_a_wheel() -> None:
    """A tyre with too few facets reads as a cog at any distance worth filming.

    Catches the facet count being trimmed to save triangles, which is the first
    saving anyone reaches for and the most visible one.
    """
    for name in vehicle_kit.ARCHETYPES:
        tyre = _tyre(name)
        ring = {(round(vertex[0], 6), round(vertex[2], 6)) for vertex in tyre["vertices"]}
        assert len(ring) >= 16, (name, len(ring))
        radii = [math.hypot(x, z) for x, z in ring]
        assert max(radii) - min(radii) < 1.0e-6, (name, min(radii), max(radii))


def test_the_hub_sits_on_both_faces_of_the_tyre() -> None:
    """One wheel mesh is built once and parented at all four corners unmirrored.

    So a hub on the +Y face alone faces outboard on the left of the car and
    straight into the body on the right, and the two right-hand wheels render as
    bare tyres. Both faces have to carry the treatment. Catches that asymmetry,
    and catches a face emitted at the tyre's own width where it z-fights the
    sidewall, or inboard of it where the tyre hides it.
    """
    for name in vehicle_kit.ARCHETYPES:
        parts = vehicle_kit.wheel_geometry(name)
        tyre = _tyre(name)
        low, high = _bounds(tyre)["y"]
        outboard = [
            part for part in parts if part is not tyre and _bounds(part)["y"][0] > high + TOLERANCE
        ]
        inboard = [
            part for part in parts if part is not tyre and _bounds(part)["y"][1] < low - TOLERANCE
        ]
        for face in (outboard, inboard):
            assert face, name
            assert any(part["material"] == vehicle_kit.PAINT for part in face), name
        for part in outboard:
            assert _bounds(part)["y"][1] < high + 0.02, (name, part["name"])
        for part in inboard:
            assert _bounds(part)["y"][0] > low - 0.02, (name, part["name"])


def test_a_turning_wheel_cannot_be_mistaken_for_a_still_one() -> None:
    """A rotationally symmetric wheel renders identically spinning and frozen.

    This is the whole reason the hub carries an asymmetric witness. The test
    rotates the emitted wheel about its axle by every facet step and demands the
    result differ from where it started, which is the only definition of "the
    rotation is visible" that a still frame can be held to.

    What is compared is each vertex WITH ITS MATERIAL, because that is what the
    render resolves. The wheel face carries two witness sectors half a turn
    apart, so the vertex cloud alone maps onto itself at 180 degrees; the
    sectors wear different materials, so the frame does not. Catches a witness
    dropped, made symmetric, or repainted to match its opposite number.
    """
    for name in vehicle_kit.ARCHETYPES:
        cloud = [
            (vertex, part["material"])
            for part in vehicle_kit.wheel_geometry(name)
            for vertex in part["vertices"]
        ]
        base = sorted(
            (round(x, 6), round(y, 6), round(z, 6), material) for (x, y, z), material in cloud
        )
        sides = len({(round(v[0], 6), round(v[2], 6)) for v in _tyre(name)["vertices"]})
        for step in range(1, sides):
            angle = 2.0 * math.pi * step / sides
            cosine, sine = math.cos(angle), math.sin(angle)
            turned = sorted(
                (
                    round(x * cosine - z * sine, 6),
                    round(y, 6),
                    round(x * sine + z * cosine, 6),
                    material,
                )
                for (x, y, z), material in cloud
            )
            assert turned != base, (name, step)


def test_the_four_wheel_offsets_carry_the_right_signs() -> None:
    """Front is +X and left is +Y, on every corner, for every archetype.

    Catches a corner mislabelled or mirrored, which would put a wheel inside the
    cabin or leave two wheels stacked at one axle.
    """
    expected = {"fl": (1, 1), "fr": (1, -1), "rl": (-1, 1), "rr": (-1, -1)}
    for name in vehicle_kit.ARCHETYPES:
        offsets = vehicle_kit.wheel_offsets(name)
        assert set(offsets) == set(expected), (name, sorted(offsets))
        radius = _wheel_radius(name)
        for corner, (sign_x, sign_y) in expected.items():
            x, y, z = offsets[corner]
            assert math.copysign(1.0, x) == sign_x, (name, corner, x)
            assert math.copysign(1.0, y) == sign_y, (name, corner, y)
            assert z == pytest.approx(radius), (name, corner, z, radius)


# ---------------------------------------------------------------------------
# Cost and determinism
# ---------------------------------------------------------------------------


def test_every_archetype_fits_the_per_vehicle_triangle_budget() -> None:
    """Performance is a contract, so it is measured rather than hoped for.

    Catches a detail pass that quietly doubled the cost of every car in the
    city.
    """
    for name in vehicle_kit.ARCHETYPES:
        triangles = vehicle_kit.vehicle_triangles(name)
        assert triangles <= PER_VEHICLE_TRIANGLES, (name, triangles)


def test_fourteen_vehicles_fit_the_layer_triangle_budget() -> None:
    """The canonical traffic must fit inside the declared layer ceiling.

    Catches a per-vehicle budget that still passes on its own but no longer
    multiplies into the layer the Director signed off.
    """
    heaviest = max(vehicle_kit.vehicle_triangles(name) for name in vehicle_kit.ARCHETYPES)
    assert heaviest * CANONICAL_VEHICLES <= LAYER_TRIANGLES, heaviest


def test_the_kit_is_deterministic() -> None:
    """The same archetype always builds the same vehicle.

    Catches any dependence on iteration order, hashing or a stray random source.
    A vehicle that differs between two builds would differ between the proof
    render and the final one.
    """
    for name in vehicle_kit.ARCHETYPES:
        assert vehicle_kit.vehicle_mesh(name) == vehicle_kit.vehicle_mesh(name)
        assert vehicle_kit.wheel_mesh(name) == vehicle_kit.wheel_mesh(name)
        assert vehicle_kit.silhouette_profile(name) == vehicle_kit.silhouette_profile(name)
        assert vehicle_kit.measured_visual_bounds(name) == vehicle_kit.measured_visual_bounds(name)


def test_the_kit_summary_covers_every_archetype() -> None:
    """The manifest a reviewer reads must describe the whole vocabulary.

    Catches a summary that silently dropped an archetype, which would hide a
    regression from every report built on it.
    """
    summary = vehicle_kit.kit_summary()
    assert set(summary) == set(vehicle_kit.ARCHETYPES)
    for name, entry in summary.items():
        assert entry["triangles"] == vehicle_kit.vehicle_triangles(name), name
