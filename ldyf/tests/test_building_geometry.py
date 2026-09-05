"""Tests for ``ldyf.building_geometry`` (schema ``building_geometry_v1``).

Covers: determinism, index/range and length invariants, slot assignment
(upward faces are roof/parapet, never wall), plinth proud of the wall,
setback insets, the per-building triangle budget, every ``validate_geometry``
failure the module claims, every documented ``ValueError``, and the landmark's
stepped silhouette.
"""

from __future__ import annotations

import copy

import pytest

from ldyf.building_geometry import (
    MAT_GROUND,
    MAT_PARAPET,
    MAT_ROOF,
    MAT_WALL,
    MATERIAL_SLOTS,
    PLINTH_PROUD_CM,
    PRISM_SIDES,
    SCHEMA_VERSION,
    building_mesh,
    landmark_mesh,
    validate_geometry,
)

# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

# 1200 x 900 cm convex quad footprint (the shape city_layout emits per slot).
FOOTPRINT = [
    {"x": 0.0, "y": 0.0},
    {"x": 1200.0, "y": 0.0},
    {"x": 1200.0, "y": 900.0},
    {"x": 0.0, "y": 900.0},
]

MASSING_STEPPED = {
    "height_cm": 1500.0,
    "setback_cm": 150.0,        # 2 * 150 = 300 < 1160 x 860 wall ring
    "setback_start_cm": 900.0,  # above ground band of 360 cm
}
GROUND = {"height_cm": 360.0}
ROOF_WITH_PARAPET = {"parapet_height_cm": 90.0}
ROOF_FLAT = {"parapet_height_cm": 0.0}

LANDMARK_SPEC = {
    "kind": "civic_clock_tower",
    "parts": [
        {"name": "podium", "kind": "box", "size_cm": [1000, 800, 600],
         "offset_cm": [0, 0, 300]},
        {"name": "hall", "kind": "box", "size_cm": [600, 500, 600],
         "offset_cm": [0, 0, 900]},
        {"name": "tower_shaft", "kind": "box", "size_cm": [200, 200, 800],
         "offset_cm": [0, 0, 1600]},
        {"name": "crown", "kind": "box", "size_cm": [240, 240, 200],
         "offset_cm": [0, 0, 2100]},
        {"name": "lantern", "kind": "cylinder", "radius_cm": 90,
         "height_cm": 200, "offset_cm": [0, 0, 2300]},
    ],
}


def bbox2(ring):
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (min(xs), min(ys), max(xs), max(ys))


def tri_normal_z(verts, t):
    a, b, c = verts[t[0]], verts[t[1]], verts[t[2]]
    ux = b[0] - a[0]
    uy = b[1] - a[1]
    uz = b[2] - a[2]
    vx = c[0] - a[0]
    vy = c[1] - a[1]
    vz = c[2] - a[2]
    return (uy * vz - uz * vy,
            uz * vx - ux * vz,
            ux * vy - uy * vx)


# --------------------------------------------------------------------------
# determinism and document shape
# --------------------------------------------------------------------------

def test_deterministic():
    a = building_mesh(FOOTPRINT, MASSING_STEPPED, GROUND, ROOF_WITH_PARAPET,
                      seed=7)
    b = building_mesh(FOOTPRINT, MASSING_STEPPED, GROUND, ROOF_WITH_PARAPET,
                      seed=7)
    assert a == b


def test_schema_and_shape_keys():
    doc = building_mesh(FOOTPRINT, MASSING_STEPPED, GROUND, ROOF_WITH_PARAPET,
                        seed=1)
    assert doc["schema_version"] == SCHEMA_VERSION
    assert set(doc) == {"schema_version", "kind", "vertices", "triangles",
                        "uvs", "material_slot_per_triangle", "counts",
                        "bounds"}
    assert doc["kind"] == "building"


# --------------------------------------------------------------------------
# budget: stated and met (252 buildings will be instanced)
# --------------------------------------------------------------------------

def test_triangle_budget_stated_and_met():
    # Module docstring: stepped + parapet = 60, stepped flat = 36,
    # single mass + parapet = 48, single flat = 24 (4-corner footprint).
    stepped_para = building_mesh(FOOTPRINT, MASSING_STEPPED, GROUND,
                                 ROOF_WITH_PARAPET, seed=2)
    stepped_flat = building_mesh(FOOTPRINT, MASSING_STEPPED, GROUND,
                                 ROOF_FLAT, seed=2)
    single = dict(MASSING_STEPPED, setback_cm=0.0, setback_start_cm=0.0)
    single_para = building_mesh(FOOTPRINT, single, GROUND,
                                ROOF_WITH_PARAPET, seed=2)
    single_flat = building_mesh(FOOTPRINT, single, GROUND, ROOF_FLAT, seed=2)

    assert stepped_para["counts"]["triangles"] == 60
    assert stepped_flat["counts"]["triangles"] == 36
    assert single_para["counts"]["triangles"] == 48
    assert single_flat["counts"]["triangles"] == 24

    for doc in (stepped_para, stepped_flat, single_para, single_flat):
        assert doc["counts"]["budget_triangles"] == 60
        assert doc["counts"]["triangles"] <= 60
        # every triangle owns three private vertex rows (tree_mesh pattern)
        assert len(doc["vertices"]) == 3 * len(doc["triangles"])
    # 252 instanced buildings worst case
    assert 252 * stepped_para["counts"]["triangles"] <= 252 * 60


# --------------------------------------------------------------------------
# index / length / slot invariants
# --------------------------------------------------------------------------

def test_indices_and_lengths_in_range():
    doc = building_mesh(FOOTPRINT, MASSING_STEPPED, GROUND, ROOF_WITH_PARAPET,
                        seed=3)
    verts, tris, slots, uvs = (doc["vertices"], doc["triangles"],
                               doc["material_slot_per_triangle"], doc["uvs"])
    assert len(slots) == len(tris)
    assert len(uvs) == len(verts)
    nv = len(verts)
    for t in tris:
        assert len(t) == 3
        for i in t:
            assert 0 <= i < nv
    for s in slots:
        assert s in (MAT_WALL, MAT_ROOF, MAT_GROUND, MAT_PARAPET)
    tally = {MAT_WALL: 0, MAT_ROOF: 0, MAT_GROUND: 0, MAT_PARAPET: 0}
    for s in slots:
        tally[s] += 1
    assert sum(tally.values()) == len(tris)
    assert tally[MAT_GROUND] == 8     # plinth sides only (slot 2 never roofs)
    assert tally[MAT_PARAPET] == 24   # 2n outer + 2n inner + 2n top
    assert tally[MAT_ROOF] == 12      # plinth cap + tread + roof deck
    assert tally[MAT_WALL] == 16      # lower shaft + upper mass sides


# --------------------------------------------------------------------------
# material roles: upward faces must be roof or parapet, never wall
# --------------------------------------------------------------------------

def test_upward_faces_are_roof_or_parapet_never_wall():
    doc = building_mesh(FOOTPRINT, MASSING_STEPPED, GROUND, ROOF_WITH_PARAPET,
                        seed=5)
    verts, tris, slots = (doc["vertices"], doc["triangles"],
                          doc["material_slot_per_triangle"])
    up_count = 0
    for t, s in zip(tris, slots):
        _, _, nz = tri_normal_z(verts, t)
        if nz > 0.0:
            up_count += 1
            assert s in (MAT_ROOF, MAT_PARAPET), (
                f"upward triangle {t} has wall/ground slot {s}")
    # upward = 12 roof caps (plinth cap 4 + tread 4 + roof deck 4)
    #         + 8 parapet-top annulus triangles (2 per side of 4 corners)
    assert up_count == 20


def test_landmark_upward_faces_are_roof_or_parapet():
    doc = landmark_mesh(LANDMARK_SPEC, seed=5)
    verts, tris, slots = (doc["vertices"], doc["triangles"],
                          doc["material_slot_per_triangle"])
    for t, s in zip(tris, slots):
        _, _, nz = tri_normal_z(verts, t)
        if nz > 0.0:
            assert s in (MAT_ROOF, MAT_PARAPET)


# --------------------------------------------------------------------------
# geometry assertions: plinth proud, setback insets
# --------------------------------------------------------------------------

def test_setback_insets_upper_mass():
    doc = building_mesh(FOOTPRINT, MASSING_STEPPED, GROUND, ROOF_WITH_PARAPET,
                        seed=6)
    rings = doc["counts"]["rings"]
    lower = bbox2(rings["lower"])
    upper = bbox2(rings["upper"])
    margin = 150.0
    assert upper[0] > lower[0] + margin * 0.99   # strictly inside, x min
    assert upper[1] > lower[1] + margin * 0.99   # y min
    assert upper[2] < lower[2] - margin * 0.99   # x max
    assert upper[3] < lower[3] - margin * 0.99   # y max
    # exact walk: wall ring is footprint inset 20; upper inset a further 150
    assert lower == (20.0, 20.0, 1180.0, 880.0)
    assert upper == (170.0, 170.0, 1030.0, 730.0)


def test_plinth_proud_of_wall():
    doc = building_mesh(FOOTPRINT, MASSING_STEPPED, GROUND, ROOF_WITH_PARAPET,
                        seed=8)
    rings = doc["counts"]["rings"]
    plinth = bbox2(rings["plinth"])
    lower = bbox2(rings["lower"])
    lip = PLINTH_PROUD_CM
    assert plinth == (0.0, 0.0, 1200.0, 900.0)
    assert lower == (lip, lip, 1200.0 - lip, 900.0 - lip)
    for side in range(4):
        assert plinth[side] < lower[side] if side < 2 else \
            plinth[side] > lower[side]


# --------------------------------------------------------------------------
# validate_geometry: clean documents pass
# --------------------------------------------------------------------------

def test_validate_clean_building_and_landmark():
    for doc in (building_mesh(FOOTPRINT, MASSING_STEPPED, GROUND,
                              ROOF_WITH_PARAPET, seed=9),
                building_mesh(FOOTPRINT, MASSING_STEPPED, GROUND,
                              ROOF_FLAT, seed=9),
                landmark_mesh(LANDMARK_SPEC, seed=9)):
        assert validate_geometry(doc) == []


def test_validate_catches_every_claimed_failure():
    doc = building_mesh(FOOTPRINT, MASSING_STEPPED, GROUND, ROOF_WITH_PARAPET,
                        seed=10)

    bad_index = copy.deepcopy(doc)
    bad_index["triangles"][0][0] = 10 ** 9
    assert any("out of range" in p for p in validate_geometry(bad_index))

    bad_len = copy.deepcopy(doc)
    bad_len["material_slot_per_triangle"] = \
        bad_len["material_slot_per_triangle"][:-1]
    assert any("material_slot_per_triangle length" in p
               for p in validate_geometry(bad_len))

    degenerate = copy.deepcopy(doc)
    degenerate["triangles"][0] = [0, 0, 0]
    assert any("degenerate" in p for p in validate_geometry(degenerate))

    up_wall = copy.deepcopy(doc)
    verts, tris, slots = up_wall["vertices"], up_wall["triangles"], \
        up_wall["material_slot_per_triangle"]
    up_tri = next(t for t, s in zip(tris, slots)
                  if tri_normal_z(verts, t)[2] > 0.0 and s == MAT_ROOF)
    slots[tris.index(up_tri)] = MAT_WALL
    assert any("faces up" in p for p in validate_geometry(up_wall))

    nan_doc = copy.deepcopy(doc)
    nan_doc["vertices"][0][0] = float("nan")
    assert any("NaN/inf" in p for p in validate_geometry(nan_doc))

    not_enclosing = copy.deepcopy(doc)
    not_enclosing["counts"]["rings"]["roof_deck"][0] = [999999.0, 999999.0]
    assert any("does not enclose the roof deck" in p
               for p in validate_geometry(not_enclosing))


# --------------------------------------------------------------------------
# ValueError guards
# --------------------------------------------------------------------------

def test_value_error_guards():
    with pytest.raises(ValueError):
        building_mesh(FOOTPRINT, {"height_cm": 0.0}, GROUND, ROOF_FLAT, seed=1)
    with pytest.raises(ValueError):
        building_mesh(FOOTPRINT, {"height_cm": -5.0}, GROUND, ROOF_FLAT, seed=1)
    with pytest.raises(ValueError):
        # ground floor not shorter than the building
        building_mesh(FOOTPRINT, {"height_cm": 400.0},
                      {"height_cm": 500.0}, ROOF_FLAT, seed=1)
    with pytest.raises(ValueError):
        building_mesh(FOOTPRINT, {"height_cm": 400.0},
                      {"height_cm": 400.0}, ROOF_FLAT, seed=1)
    with pytest.raises(ValueError):
        # setback wider than the (wall-ring) footprint: 2*700 >= 860
        building_mesh(FOOTPRINT,
                      {"height_cm": 1500.0, "setback_cm": 700.0,
                       "setback_start_cm": 900.0},
                      GROUND, ROOF_FLAT, seed=1)
    with pytest.raises(ValueError):
        building_mesh([{"x": 0.0, "y": 0.0}, {"x": 100.0, "y": 0.0}],
                      {"height_cm": 1500.0}, GROUND, ROOF_FLAT, seed=1)
    with pytest.raises(ValueError):
        building_mesh([{"x": 0.0, "y": 0.0}, {"x": 0.0, "y": 0.0},
                       {"x": 0.0, "y": 0.0}],
                      {"height_cm": 1500.0}, GROUND, ROOF_FLAT, seed=1)
    with pytest.raises(ValueError):
        landmark_mesh({"parts": []}, seed=1)
    with pytest.raises(ValueError):
        landmark_mesh({"parts": [{"kind": "bogus"}]}, seed=1)
    with pytest.raises(ValueError):
        landmark_mesh({"parts": [{"kind": "cylinder", "radius_cm": 0.0,
                                  "height_cm": 100.0,
                                  "offset_cm": [0, 0, 100]}]}, seed=1)


# --------------------------------------------------------------------------
# landmark: stepped silhouette with a tower, prisms stated
# --------------------------------------------------------------------------

def test_landmark_stepped_with_tower():
    doc = landmark_mesh(LANDMARK_SPEC, seed=11)
    assert doc["kind"] == "landmark"
    assert doc["counts"]["prism_sides"] == PRISM_SIDES == 10
    assert doc["counts"]["boxes"] == 4
    assert doc["counts"]["cylinders"] == 1
    # 4 boxes: podium 12 tris (no bottom at grade) + 3 * 16 = 60;
    # 1 prism cylinder: 20 sides + 10 top + 10 bottom = 40  -> 100 total
    assert doc["counts"]["triangles"] == 100

    verts = doc["vertices"]
    # vertices only exist at part boundary z levels; the podium base is at
    # z == 0 and the crown (over the tower shaft) occupies z 2000..2200.
    podium_x = max(abs(v[0]) for v in verts if v[2] == 0.0)
    crown_x = max(abs(v[0]) for v in verts if 2000.0 <= v[2] <= 2200.0)
    assert podium_x == pytest.approx(500.0)
    assert crown_x == pytest.approx(120.0)      # crown is 240 wide
    assert crown_x < 0.5 * podium_x             # visibly distinct silhouette
    assert doc["bounds"]["max_z"] == pytest.approx(2400.0)


def test_slots_constant_documented():
    assert MATERIAL_SLOTS == {"wall": MAT_WALL, "roof": MAT_ROOF,
                              "ground": MAT_GROUND, "parapet": MAT_PARAPET}
