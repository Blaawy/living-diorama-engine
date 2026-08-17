"""The drawn road surface never runs through founding architecture.

Pure pytest -- no Blender. Phase 15 laid its avenues, sidewalks, curbs,
markings and spurs as unbroken ribbons, and seven founding rectangles ended
up standing in carriageway space. On the plate rings a building merely sits on
the asphalt, but the avenue and spur decks are drawn ABOVE the founding
bases, so their slabs passed clean through the podiums. The lane network
already refused to drive those sectors; the remediation stopped DRAWING
them, from the same footprints, so the picture and the traffic agree.

This suite makes that permanent. It reconstructs the faces the builders will
emit -- through the same :func:`strip_edges` mitre the ribbon builder uses,
not an approximation of it -- and requires that none of them overlaps a
founding footprint, under the same convex-polygon test the trim is gated on.

    THE TRIM IS PROVED ON THE FACES, NOT ON THE INTENT.

Reconstructing rather than importing is deliberate. ``_trimmed_ribbon`` needs
``bpy`` to build anything, so a pure suite cannot call it; what it CAN do is
lay down the same vertices from the same helpers and the same call-site
constants. The mutation tests below bypass the trim and require the overlaps
to reappear, which is what stops this from being a test that would pass
against a builder that had never been fixed.
"""

import importlib
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"
CONFIG_DIR = REPO_ROOT / "visual" / "blender" / "config"


def _load(name: str):
    """Import one pure visual module the same way Blender does: by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


occupancy = _load("spatial_occupancy")
scene_spec = _load("scene_spec")

MASTER = scene_spec.load_master_scene_spec(CONFIG_DIR / "master_scene_v1.json")
FOOTPRINTS = occupancy.founding_building_footprints(MASTER)
FOUNDING_PARTS = [entry["shape"] for lot in FOOTPRINTS for entry in lot["parts"]]

RING_DISC_SEGMENTS = 72
"""How many wedges a plate's ring disc is drawn as. Mirrors
``build_master_scene.RING_DISC_SEGMENTS``; a disc drawn at a different
resolution would shadow a different set of sectors."""

BOUNDARY_LAYERS = (
    ("LD_ROAD__{boundary}", 7.0, 0.0),
    ("LD_SIDEWALK__{boundary}__north", 2.0, 4.7),
    ("LD_SIDEWALK__{boundary}__south", 2.0, -4.7),
    ("LD_CURB__{boundary}__north", 0.4, 4.7 * 0.775),
    ("LD_CURB__{boundary}__south", 0.4, -4.7 * 0.775),
    ("LD_MARKING__{boundary}__edge_n", 0.14, 3.1),
    ("LD_MARKING__{boundary}__edge_s", 0.14, -3.1),
)
"""The seven co-located strips every boundary corridor draws, as
``(name, width, lateral offset)``.

These mirror the ``_trimmed_ribbon`` call sites in
``build_master_scene.build_avenues`` exactly. They are co-located on purpose:
seven ribbons share one polyline, so a founding part standing on the corridor
is met by up to seven different strips at seven different offsets, and a trim
that handled only the carriageway would leave a sidewalk running through the
building beside it.
"""

OVERLAPS_WITHOUT_THE_TRIM = 10
"""How many drawn faces stood inside founding architecture before the trim.

Four on ``boundary_ab``'s southern half, three on ``boundary_ac``'s northern
half, and three spur faces. Pinned so the mutation test below is measuring a
known quantity rather than merely "more than zero" -- if the untrimmed count
moves, the city's architecture has moved onto or off its own roads and that
is a composition change, not a test detail.
"""

WORST_SURVIVING_CLEARANCE = 0.0762
"""How close the nearest surviving road face comes to founding architecture.

Just under eight centimetres, on ``LD_SPUR__boundary_ab__district_a``. The
trim's job is to reach zero overlaps, not to open a comfortable margin, so
this is recorded as the measurement it is: a positive number, and a small
one. It is asserted to stay positive rather than to stay 0.0762 exactly,
because the pad the trim leaves is a rounding of a scan step and pinning it
to the micrometre would be pinning the scan, not the contract.
"""

TRIMMED_RING_WEDGES = 20
"""How many of ``district_a``'s 72 ring-disc wedges its towers stand on.

The civic plate's disc runs straight under two founding towers. A wedge is
omitted only when its footprint ALSO occupies that ring's carriageway --
the same test the lane network refuses a run with -- so the sectors that
stop being drawn are exactly the sectors that stopped carrying traffic.
"""

ROAD_SWALLOWED_WHOLE = "LD_SPUR__boundary_cd__district_c"
"""The one road object the city cannot draw at all.

Its entire 5.65 m run lies inside ``LD_BLDG__district_c__001``, so every
span of it is trimmed away and it draws zero faces. It still EXISTS as a
named, empty object: a road the city cannot show is stated honestly rather
than deleted, and nothing that looks the name up is left holding a
reference to something that vanished. A test asserting "every road object
has faces" would be wrong, and this constant is why.
"""


def _spur_runs() -> list[tuple[str, list[tuple[float, float]]]]:
    """Every spur's name and its two-point run, as ``build_spurs`` derives it."""
    runs = []
    for boundary_id, boundary in MASTER["boundaries"].items():
        path = [tuple(point) for point in boundary["path"]]
        endpoints = (path[0], path[-1])
        for district_id in boundary["districts"]:
            district = MASTER["districts"][district_id]
            center = district["center"]
            best = min(
                endpoints,
                key=lambda point: math.hypot(point[0] - center[0], point[1] - center[1]),
            )
            dx, dy = best[0] - center[0], best[1] - center[1]
            distance = math.hypot(dx, dy) or 1.0
            edge = (
                center[0] + dx / distance * district["radius"] * 0.55,
                center[1] + dy / distance * district["radius"] * 0.55,
            )
            runs.append((f"LD_SPUR__{boundary_id}__{district_id}", [edge, best]))
    return runs


def _strips() -> list[tuple[str, list[tuple[float, float]], float, float]]:
    """Every road strip the city draws, as ``(name, path, width, offset)``."""
    strips: list[tuple[str, list[tuple[float, float]], float, float]] = []
    for boundary_id, boundary in MASTER["boundaries"].items():
        path = [tuple(point) for point in boundary["path"]]
        for template, width, offset in BOUNDARY_LAYERS:
            strips.append((template.format(boundary=boundary_id), path, width, offset))
    strips.extend((name, run, 5.0, 0.0) for name, run in _spur_runs())
    return strips


STRIPS = _strips()


def _strip_faces(
    path: list[tuple[float, float]], offset: float, width: float
) -> list[list[tuple[float, float]]]:
    """The quads a ribbon builder lays along one path, mitred as it mitres.

    One quad per segment, its four corners taken from the two lateral edges
    ``strip_edges`` produces -- which is the same vertex-by-vertex mitre
    ``_trimmed_ribbon`` walks when it emits faces. Degenerate segments are
    skipped, exactly as a zero-length span would emit no face.
    """
    left, right = occupancy.strip_edges(path, offset, width / 2.0)
    return [
        [left[index], left[index + 1], right[index + 1], right[index]]
        for index in range(len(path) - 1)
        if math.dist(path[index], path[index + 1]) > 1.0e-9
    ]


def _drawn_faces(
    path: list[tuple[float, float]], offset: float, width: float
) -> list[list[tuple[float, float]]]:
    """The faces that actually survive the trim for one strip."""
    spans = occupancy.founding_clear_spans(path, FOOTPRINTS, offset=offset, half_width=width / 2.0)
    return [face for span in spans for face in _strip_faces(span, offset, width)]


def _founding_overlaps(faces: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Every face that meets a founding footprint, by the trim's own test."""
    return [
        face
        for face in faces
        if any(
            occupancy.convex_polygons_intersect(face, occupancy._rect_corners(shape))
            for shape in FOUNDING_PARTS
        )
    ]


def _ring_wedges(district_id: str, omit: set[int]) -> list[list[tuple[float, float]]]:
    """The wedges a district's ring disc actually draws."""
    district = MASTER["districts"][district_id]
    center = (float(district["center"][0]), float(district["center"][1]))
    radius = float(district["radius"]) * 0.985
    wedges = []
    for index in range(RING_DISC_SEGMENTS):
        if index in omit:
            continue
        first = 2.0 * math.pi * index / RING_DISC_SEGMENTS
        second = 2.0 * math.pi * (index + 1) / RING_DISC_SEGMENTS
        wedges.append(
            [
                center,
                (center[0] + radius * math.cos(first), center[1] + radius * math.sin(first)),
                (center[0] + radius * math.cos(second), center[1] + radius * math.sin(second)),
            ]
        )
    return wedges


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_no_drawn_road_face_stands_in_founding_architecture() -> None:
    """The whole point: every road layer, every face, clear of every building."""
    offenders: list[str] = []
    for name, path, width, offset in STRIPS:
        overlapping = _founding_overlaps(_drawn_faces(path, offset, width))
        if overlapping:
            offenders.append(f"{name} draws {len(overlapping)} face(s) inside a founding building")
    assert not offenders, "; ".join(offenders)


def _carriageway_shadowing_shapes(district_id: str) -> list[dict]:
    """Founding parts that stand on one district's ring CARRIAGEWAY.

    Derived here rather than taken from :func:`founding_ring_shadow`, so the
    disc test checks the shadow against an independently computed answer
    instead of against the function that produced it. This is the same
    condition ``vehicle_lane_network`` refuses a run with: the part has to
    reach within the ring's own half-width of the ring's own path.
    """
    ring = next(
        (
            way
            for way in occupancy.founding_carriageways(MASTER)
            if way["id"] == f"ring_{district_id}"
        ),
        None,
    )
    if ring is None:
        return []
    return [
        entry["shape"]
        for lot in FOOTPRINTS
        for entry in lot["parts"]
        if any(
            occupancy._rect_segment_distance(entry["shape"], a[0], a[1], b[0], b[1]) <= ring["half"]
            for a, b in zip(ring["path"], ring["path"][1:], strict=False)
        )
    ]


def test_no_drawn_ring_disc_wedge_stands_in_founding_architecture() -> None:
    """The same claim for the plate discs, which are fans rather than ribbons.

    A wedge may legitimately touch a building that does NOT reach the ring's
    carriageway: that building stands on its own plate rather than in
    traffic, and Phase 15 always drew the asphalt under it. What must never
    survive is a wedge under architecture the lane network refused a run
    for -- so the shadowing set is recomputed here from the carriageway
    condition and the drawn wedges are checked against that.
    """
    for district_id in sorted(MASTER["districts"]):
        shadowing = _carriageway_shadowing_shapes(district_id)
        omit = occupancy.founding_ring_shadow(
            MASTER,
            district_id,
            FOOTPRINTS,
            segments=RING_DISC_SEGMENTS,
            disc_radius=float(MASTER["districts"][district_id]["radius"]) * 0.985,
        )
        for wedge in _ring_wedges(district_id, omit):
            for shape in shadowing:
                assert not occupancy.convex_polygons_intersect(
                    wedge, occupancy._rect_corners(shape)
                ), f"{district_id} draws a disc wedge under architecture that blocks its ring"


def test_the_civic_plate_trims_the_wedges_its_towers_stand_on() -> None:
    """Twenty of seventy-two, and the rest of the disc survives."""
    omit = occupancy.founding_ring_shadow(
        MASTER,
        "district_a",
        FOOTPRINTS,
        segments=RING_DISC_SEGMENTS,
        disc_radius=float(MASTER["districts"]["district_a"]["radius"]) * 0.985,
    )
    assert len(omit) == TRIMMED_RING_WEDGES, (
        f"district_a trims {len(omit)} of {RING_DISC_SEGMENTS} wedges, pinned at "
        f"{TRIMMED_RING_WEDGES}"
    )
    assert len(omit) < RING_DISC_SEGMENTS, "the whole disc was trimmed away"


def test_a_road_nothing_covers_is_left_byte_identical() -> None:
    """An untouched strip returns its own path, so the builder can delegate.

    This is what keeps the remediation additive. ``_trimmed_ribbon`` compares
    the spans against ``[list(path)]`` and hands that case to the untrimmed
    Phase 15 builder, so a road no building stands on is drawn by exactly the
    code that always drew it. If this identity ever stopped holding, every
    road in the city would silently switch to the trimming path.
    """
    untouched = 0
    for _name, path, width, offset in STRIPS:
        spans = occupancy.founding_clear_spans(
            path, FOOTPRINTS, offset=offset, half_width=width / 2.0
        )
        if spans == [list(path)]:
            untouched += 1
    assert untouched, "no road in the city is untouched, which cannot be right"
    assert untouched < len(STRIPS), "no road was trimmed, so the trim is not being exercised"


def test_an_empty_footprint_list_never_trims_anything() -> None:
    """With nothing to avoid, every strip is returned unchanged.

    The degenerate case matters because it is the one a caller hits when the
    founding layer is absent, and quietly returning [] there would erase
    every road in the city rather than draw them all.
    """
    for _name, path, width, offset in STRIPS:
        spans = occupancy.founding_clear_spans(path, [], offset=offset, half_width=width / 2.0)
        assert spans == [list(path)]


def test_the_one_road_the_city_cannot_draw_is_named_and_empty() -> None:
    """A spur swallowed whole draws nothing, and that is the correct answer.

    Recorded explicitly so nobody later "fixes" it by asserting that every
    road object carries faces. Its run is entirely inside a founding
    building; drawing any part of it would be drawing asphalt through a
    podium.
    """
    swallowed = [
        (name, path, width, offset)
        for name, path, width, offset in STRIPS
        if name == ROAD_SWALLOWED_WHOLE
    ]
    assert len(swallowed) == 1, f"{ROAD_SWALLOWED_WHOLE} is no longer a road the city plans"
    name, path, width, offset = swallowed[0]
    assert (
        occupancy.founding_clear_spans(path, FOOTPRINTS, offset=offset, half_width=width / 2.0)
        == []
    ), f"{name} is no longer swallowed whole"
    assert _drawn_faces(path, offset, width) == []
    assert math.dist(path[0], path[1]) == pytest.approx(5.65, abs=0.01)
    # Every other road still draws something, or the trim has eaten the city.
    drawing = [
        name
        for name, path, width, offset in STRIPS
        if name != ROAD_SWALLOWED_WHOLE and _drawn_faces(path, offset, width)
    ]
    assert len(drawing) == len(STRIPS) - 1, "a second road stopped drawing entirely"


def test_the_surviving_road_keeps_a_positive_clearance() -> None:
    """Zero overlaps is the contract; the margin is reported, not assumed."""
    worst = math.inf
    where = ""
    for name, path, width, offset in STRIPS:
        for face in _drawn_faces(path, offset, width):
            for index in range(len(face)):
                start, end = face[index], face[(index + 1) % len(face)]
                for shape in FOUNDING_PARTS:
                    gap = occupancy._rect_segment_distance(
                        shape, start[0], start[1], end[0], end[1]
                    )
                    if gap < worst:
                        worst, where = gap, name
    assert worst > 0.0, f"{where} touches founding architecture at {worst}"
    assert worst == pytest.approx(WORST_SURVIVING_CLEARANCE, abs=5.0e-3), (
        f"the worst surviving clearance is {worst:.4f} on {where}, recorded at "
        f"{WORST_SURVIVING_CLEARANCE}"
    )


# ---------------------------------------------------------------------------
# The guards have teeth
# ---------------------------------------------------------------------------


def test_bypassing_the_trim_puts_the_road_back_through_the_buildings() -> None:
    """The mutation that proves the contract above is not vacuous.

    Drawing every strip along its whole path -- which is exactly what Phase
    15 did -- must put ten faces back inside founding architecture. A test
    that only ever saw zero would pass just as happily against a builder
    that had never been fixed.
    """
    offenders: dict[str, int] = {}
    for name, path, width, offset in STRIPS:
        overlapping = _founding_overlaps(_strip_faces(path, offset, width))
        if overlapping:
            offenders[name] = len(overlapping)
    assert sum(offenders.values()) == OVERLAPS_WITHOUT_THE_TRIM, (
        f"the untrimmed city overlaps {sum(offenders.values())} face(s), recorded at "
        f"{OVERLAPS_WITHOUT_THE_TRIM}: {dict(sorted(offenders.items()))}"
    )
    assert ROAD_SWALLOWED_WHOLE in offenders


def test_feeding_the_trim_no_footprints_puts_the_road_back_too() -> None:
    """The same mutation through the helper's own argument.

    Blinding the trim to the buildings must reproduce the untrimmed city
    exactly, which proves the overlaps are removed BY the footprints rather
    than by some incidental property of the spans.
    """
    total = 0
    for _name, path, width, offset in STRIPS:
        spans = occupancy.founding_clear_spans(path, [], offset=offset, half_width=width / 2.0)
        faces = [face for span in spans for face in _strip_faces(span, offset, width)]
        total += len(_founding_overlaps(faces))
    assert total == OVERLAPS_WITHOUT_THE_TRIM, (
        f"a trim blinded to the footprints overlaps {total} face(s), and the untrimmed "
        f"city overlaps {OVERLAPS_WITHOUT_THE_TRIM}"
    )


def test_a_ring_disc_drawn_whole_stands_in_its_own_towers() -> None:
    """The disc mutation: omit nothing and the civic plate is back under its towers."""
    drawn = _ring_wedges("district_a", set())
    hit = [
        wedge
        for wedge in drawn
        if any(
            occupancy.convex_polygons_intersect(wedge, occupancy._rect_corners(shape))
            for shape in FOUNDING_PARTS
        )
    ]
    assert hit, "an untrimmed civic disc met no founding architecture at all"
    assert len(drawn) == RING_DISC_SEGMENTS


def test_the_mitre_catches_a_building_outside_a_bend() -> None:
    """The bug that produced a false pass, pinned as a regression.

    A ribbon is mitred vertex by vertex, so at a bend its outer edge reaches
    into the wedge beyond the corner. Testing coverage with a PER-LEG
    perpendicular instead -- one rectangle per segment -- leaves that wedge
    uncovered, and a building standing in it is missed: the first attempt at
    this proof reported a clean city while the founding wing on the
    boundary_cd elbow was still being drawn through.

    Synthetic geometry, deliberately: this pins the mitre's behaviour rather
    than one accident of the canonical city, so the guard survives the
    architecture moving.
    """
    bend = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    half_width = 3.5
    shape = occupancy.rect(12.0, -2.0, 0.6, 0.6, 0.0)
    footprints = [{"parts": [{"shape": shape}]}]

    spans = occupancy.founding_clear_spans(bend, footprints, offset=0.0, half_width=half_width)
    assert spans != [list(bend)], "the mitred strip missed a building outside its own bend"

    # The WRONG implementation, built here so the difference is visible: one
    # perpendicular rectangle per leg, which is what a reader would write.
    naive = False
    for start, end in zip(bend, bend[1:], strict=False):
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy)
        nx, ny = -dy / length, dx / length
        quad = [
            (start[0] + nx * half_width, start[1] + ny * half_width),
            (end[0] + nx * half_width, end[1] + ny * half_width),
            (end[0] - nx * half_width, end[1] - ny * half_width),
            (start[0] - nx * half_width, start[1] - ny * half_width),
        ]
        if occupancy.convex_polygons_intersect(quad, occupancy._rect_corners(shape)):
            naive = True
    assert not naive, (
        "the per-leg counterexample no longer misses this building, so it has "
        "stopped demonstrating the bug it was written for"
    )


def test_the_convex_test_agrees_with_itself_on_obvious_cases() -> None:
    """A separating-axis routine everything else trusts, checked directly."""
    unit = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert occupancy.convex_polygons_intersect(unit, [(0.5, 0.5), (1.5, 0.5), (1.5, 1.5)])
    assert occupancy.convex_polygons_intersect(unit, unit)
    assert not occupancy.convex_polygons_intersect(
        unit, [(2.0, 2.0), (3.0, 2.0), (3.0, 3.0), (2.0, 3.0)]
    )
    # Sharing only an edge is not an overlap the trim needs to act on.
    assert not occupancy.convex_polygons_intersect(
        unit, [(1.001, 0.0), (2.0, 0.0), (2.0, 1.0), (1.001, 1.0)]
    )
