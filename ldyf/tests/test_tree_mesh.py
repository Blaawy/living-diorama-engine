"""Tests for ``ldyf.tree_mesh`` - determinism, closure, budget, validation.

Pure stdlib geometry is tested without the editor: every assertion runs on the
raw mesh arrays the module returns.
"""

from __future__ import annotations

import json
import math
from collections import Counter

import pytest

from ldyf.tree_mesh import (
    SCHEMA_VERSION,
    TREE_VARIANTS,
    branch_geometry,
    leaf_cards,
    tree_mesh,
    trunk_geometry,
    validate_mesh,
)


def _pos_key(p) -> tuple[float, float, float]:
    """Rounded position key, mirroring how validate_mesh compares corners."""
    return (round(float(p[0]), 3), round(float(p[1]), 3), round(float(p[2]), 3))


def _edge_keys(geo: dict) -> Counter:
    """Every triangle edge as a sorted pair of rounded position keys."""
    verts = geo["vertices"]
    counts: Counter = Counter()
    for t in geo["triangles"]:
        corners = [_pos_key(verts[i]) for i in t]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            key = tuple(sorted((corners[a], corners[b])))
            counts[key] += 1
    return counts


def _trunk_geometry_args():
    return dict(height_cm=300.0, base_radius_cm=20.0, top_radius_cm=12.0,
                sides=10, segments=3, lean_deg=2.5, seed="trunk-test-seed")


def _leaf_geometry_args():
    return dict(crown_centre_z_cm=480.0, crown_radius_cm=260.0,
                card_count=60, card_w_cm=140.0, card_h_cm=95.0,
                seed="leaf-test-seed")


def _maple_leaf_args(**overrides) -> dict:
    """The real maple crown parameters, for canopy-shape tests."""
    p = TREE_VARIANTS["maple"]
    args = dict(crown_centre_z_cm=float(p["crown_centre_z_cm"]),
                crown_radius_cm=float(p["crown_radius_cm"]),
                crown_radius_v_cm=float(p["crown_radius_v_cm"]),
                card_count=int(p["card_count"]),
                card_w_cm=float(p["card_w_cm"]),
                card_h_cm=float(p["card_h_cm"]),
                seed="maple-leaf-seed")
    args.update(overrides)
    return args


def _mini_doc(**overrides) -> dict:
    """One valid triangle so a single mutation isolates one failure path."""
    doc = {
        "schema_version": SCHEMA_VERSION,
        "vertices": [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [0.0, 10.0, 0.0]],
        "triangles": [[0, 1, 2]],
        "normals": [[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]],
        "uvs": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
        "material_slot_per_triangle": [0],
    }
    doc.update(overrides)
    return doc


# --------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------

@pytest.mark.parametrize("variant", sorted(TREE_VARIANTS))
def test_tree_mesh_deterministic_byte_identical(variant):
    a = tree_mesh(variant, seed="seed-A")
    b = tree_mesh(variant, seed="seed-A")
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_leaf_cards_different_seeds_different_crown_same_count():
    a = leaf_cards(**{**_leaf_geometry_args(), "seed": "seed-1"})
    b = leaf_cards(**{**_leaf_geometry_args(), "seed": "seed-2"})
    assert len(a["triangles"]) == len(b["triangles"])
    assert len(a["vertices"]) == len(b["vertices"])
    ka = {_pos_key(v) for v in a["vertices"]}
    kb = {_pos_key(v) for v in b["vertices"]}
    assert ka != kb, "different seeds must move leaf positions"


def test_trunk_geometry_deterministic():
    a = trunk_geometry(**_trunk_geometry_args())
    b = trunk_geometry(**_trunk_geometry_args())
    assert a["vertices"] == b["vertices"]
    assert a["triangles"] == b["triangles"]


# --------------------------------------------------------------------------
# trunk closure and counts
# --------------------------------------------------------------------------

def test_trunk_is_closed_every_edge_shared_exactly_twice():
    trunk = trunk_geometry(**_trunk_geometry_args())
    counts = _edge_keys(trunk)
    assert len(counts) > 0
    bad = {k: n for k, n in counts.items() if n != 2}
    assert not bad, f"edges not shared exactly twice: {bad}"


def test_trunk_expected_triangle_count():
    trunk = trunk_geometry(**_trunk_geometry_args())
    sides, segments = 10, 3
    assert len(trunk["triangles"]) == sides * (2 * segments + 2)
    assert len(trunk["vertices"]) == 3 * len(trunk["triangles"])
    assert len(trunk["normals"]) == len(trunk["vertices"])
    assert len(trunk["uvs"]) == len(trunk["vertices"])


def test_trunk_base_rests_on_grade():
    trunk = trunk_geometry(**_trunk_geometry_args())
    assert min(v[2] for v in trunk["vertices"]) == 0.0
    assert max(v[2] for v in trunk["vertices"]) == pytest.approx(300.0)


def test_branch_geometry_closed():
    branch = branch_geometry(origin_z_cm=150.0, length_cm=180.0,
                             base_radius_cm=8.0, top_radius_cm=2.5,
                             sides=8, segments=2, incline_deg=30.0,
                             seed="branch-seed")
    counts = _edge_keys(branch)
    assert all(n == 2 for n in counts.values())
    assert len(branch["triangles"]) == 8 * (2 * 2 + 2)


# --------------------------------------------------------------------------
# whole-tree document invariants
# --------------------------------------------------------------------------

@pytest.mark.parametrize("variant", sorted(TREE_VARIANTS))
def test_tree_mesh_indices_and_array_lengths(variant):
    doc = tree_mesh(variant, seed="seed-X")
    nv = len(doc["vertices"])
    for t in doc["triangles"]:
        for i in t:
            assert 0 <= i < nv
    assert len(doc["normals"]) == nv
    assert len(doc["uvs"]) == nv
    assert len(doc["up_bias"]) == nv
    assert len(doc["material_slot_per_triangle"]) == len(doc["triangles"])
    assert all(s in (0, 1) for s in doc["material_slot_per_triangle"])


@pytest.mark.parametrize("variant", sorted(TREE_VARIANTS))
def test_tree_mesh_slots_ordered_bark_then_leaf(variant):
    doc = tree_mesh(variant, seed="seed-X")
    slots = doc["material_slot_per_triangle"]
    first_leaf = slots.index(1) if 1 in slots else len(slots)
    assert all(s == 0 for s in slots[:first_leaf])
    assert all(s == 1 for s in slots[first_leaf:])


@pytest.mark.parametrize("variant", sorted(TREE_VARIANTS))
def test_tree_mesh_bounds_are_exact(variant):
    """Bounds come from the real vertices: base on grade, top inside the
    crown ellipsoid (the larger of horizontal/vertical radius) plus at most
    one card half-height of poke."""
    doc = tree_mesh(variant, seed="seed-X")
    p = TREE_VARIANTS[variant]
    verts = doc["vertices"]
    assert doc["bounds"]["min_x"] == min(v[0] for v in verts)
    assert doc["bounds"]["min_y"] == min(v[1] for v in verts)
    assert doc["bounds"]["min_z"] == min(v[2] for v in verts)
    assert doc["bounds"]["max_x"] == max(v[0] for v in verts)
    assert doc["bounds"]["max_y"] == max(v[1] for v in verts)
    assert doc["bounds"]["max_z"] == max(v[2] for v in verts)
    # the trunk's own top is inside the tree ...
    assert doc["bounds"]["max_z"] >= p["trunk_height_cm"]
    # ... and nothing can sit above crown centre + the larger crown radius
    # + half a card height
    assert doc["bounds"]["max_z"] <= (p["crown_centre_z_cm"]
                                      + max(p["crown_radius_cm"],
                                            p["crown_radius_v_cm"])
                                      + p["card_h_cm"] / 2.0)
    assert doc["bounds"]["min_z"] == 0.0


# --------------------------------------------------------------------------
# leaf cards
# --------------------------------------------------------------------------

def test_leaf_card_triangles_share_exactly_two_vertices():
    leaves = leaf_cards(**_leaf_geometry_args())
    tris = leaves["triangles"]
    assert len(tris) % 2 == 0
    for k in range(0, len(tris), 2):
        t1, t2 = tris[k], tris[k + 1]
        corners1 = {_pos_key(leaves["vertices"][i]) for i in t1}
        corners2 = {_pos_key(leaves["vertices"][i]) for i in t2}
        assert len(corners1) == 3 and len(corners2) == 3
        shared = corners1 & corners2
        assert len(shared) == 2, f"card {k // 2} does not share an edge"


def test_leaf_card_uvs_span_full_range_per_card():
    leaves = leaf_cards(crown_centre_z_cm=270.0, crown_radius_cm=130.0,
                        card_count=4, card_w_cm=95.0, card_h_cm=75.0,
                        seed="uv-seed")
    tris = leaves["triangles"]
    for k in range(0, len(tris), 2):
        uvs = [tuple(leaves["uvs"][i]) for t in tris[k:k + 2] for i in t]
        assert (0.0, 0.0) in uvs and (1.0, 1.0) in uvs
        for u, v in uvs:
            assert 0.0 <= u <= 1.0 and 0.0 <= v <= 1.0


def test_leaf_card_normals_point_away_from_crown_centre():
    leaves = leaf_cards(**_leaf_geometry_args())
    centre = (0.0, 0.0, 480.0)
    for idx in range(len(leaves["vertices"])):
        n = leaves["normals"][idx]
        p = leaves["vertices"][idx]
        dot = (n[0] * (p[0] - centre[0])
               + n[1] * (p[1] - centre[1])
               + n[2] * (p[2] - centre[2]))
        assert dot > 0.0, f"vertex {idx} normal not outward: dot {dot}"


def test_leaf_cards_outward_directions_vary():
    """60 cards on one crown give many distinct outward normals, so the
    crown reads as a volume, not one flat billboard."""
    leaves = leaf_cards(**_leaf_geometry_args())
    distinct = {tuple(leaves["normals"][i])
                for i in range(0, len(leaves["vertices"]), 3)}
    assert len(distinct) >= 10


def test_leaf_cards_sit_on_the_crown_not_arbitrarily_far():
    """Every card corner is at most (radius + half card diagonal) from the
    crown centre - cards belong to the crown, nowhere else."""
    leaves = leaf_cards(**_leaf_geometry_args())
    centre = (0.0, 0.0, 480.0)
    bound = 260.0 + 70.0 + 47.5  # crown radius + card half-width + half-height
    for v in leaves["vertices"]:
        dist = math.hypot(v[0] - centre[0], v[1] - centre[1], v[2] - centre[2])
        # 1e-2 slack: coordinates are rounded to 3 decimals in the document
        assert dist <= bound + 1e-2


def test_broad_variant_crown_is_wider_than_tall():
    """The broad (maple) crown: the horizontal semi-axis is the larger one
    and the emitted card cloud spreads further sideways than up/down from the
    crown centre."""
    p = TREE_VARIANTS["maple"]
    assert p["crown_radius_cm"] > p["crown_radius_v_cm"]
    leaves = leaf_cards(**{**_maple_leaf_args(), "seed": "wider-than-tall"})
    centre_z = float(p["crown_centre_z_cm"])
    tris = leaves["triangles"]
    horiz, vert = [], []
    for k in range(0, len(tris), 2):
        rows = [leaves["vertices"][i] for t in tris[k:k + 2] for i in t]
        # the mean of a card's six corner rows is its frame origin
        horiz.append(math.hypot(sum(r[0] for r in rows) / 6.0,
                                sum(r[1] for r in rows) / 6.0))
        vert.append(abs(sum(r[2] for r in rows) / 6.0 - centre_z))
    # mean extents are ~ rx*0.85*(pi/4) vs rz*0.85*0.5 over uniform
    # directions (260 vs 200 cm): a > 2:1 margin on the means.
    assert sum(horiz) / len(horiz) > sum(vert) / len(vert)


def test_leaf_card_sizes_vary():
    """Per-card digest scale gives more than one lobe size on one crown:
    the silhouette carries small and large clusters, not one stamp."""
    leaves = leaf_cards(**_leaf_geometry_args())
    tris = leaves["triangles"]
    widths = set()
    for k in range(0, len(tris), 2):
        a = leaves["vertices"][tris[k][0]]
        b = leaves["vertices"][tris[k][1]]
        # c00..c10 is one card width edge: length = 2 * half-width * scale
        widths.add(round(math.hypot(a[0] - b[0], a[1] - b[1],
                                    a[2] - b[2]), 2))
    assert len(widths) > 5


def test_leaf_cards_ellipsoid_normals_stay_outward():
    """Oblate crown: stored normals (unit ellipsoid gradient) still point
    away from the crown centre for every vertex."""
    leaves = leaf_cards(**{**_maple_leaf_args(), "seed": "ellipsoid-normals"})
    centre = (0.0, 0.0, float(TREE_VARIANTS["maple"]["crown_centre_z_cm"]))
    for idx in range(len(leaves["vertices"])):
        n = leaves["normals"][idx]
        p = leaves["vertices"][idx]
        dot = (n[0] * (p[0] - centre[0])
               + n[1] * (p[1] - centre[1])
               + n[2] * (p[2] - centre[2]))
        assert dot > 0.0, f"vertex {idx} normal not outward: dot {dot}"


def test_leaf_cards_emit_up_bias_in_range_higher_at_top():
    """``up_bias`` is present per vertex (six equal copies per card), lies in
    [0, 1], and is larger on cards above the crown centre than below it."""
    leaves = leaf_cards(**{**_maple_leaf_args(), "seed": "up-bias-seed"})
    tris = leaves["triangles"]
    up = leaves["up_bias"]
    assert len(up) == len(leaves["vertices"])
    n_cards = len(tris) // 2
    assert len(up) == 6 * n_cards
    above, below = [], []
    for ci in range(n_cards):
        b = up[6 * ci]
        assert 0.0 <= b <= 1.0
        assert all(up[6 * ci + j] == b for j in range(6))
        rows = [leaves["vertices"][i] for t in tris[2 * ci:2 * ci + 2]
                for i in t]
        centre_z = sum(r[2] for r in rows) / 6.0
        # a card above the centre has cos(z) > 0, so its normal z is > 0 and
        # the bias is > 0.5; below the centre it is < 0.5 - strict split.
        (above if centre_z >= 480.0 else below).append(b)
    assert above and below
    assert sum(above) / len(above) > sum(below) / len(below)


def test_tree_mesh_doc_emits_up_bias_per_vertex():
    """The assembled document carries up_bias alongside the vertices: 0.0 on
    the bark run, the per-card sky-facing scalar on every leaf row."""
    doc = tree_mesh("maple", seed="doc-up-bias")
    up = doc["up_bias"]
    assert len(up) == len(doc["vertices"])
    assert all(0.0 <= float(b) <= 1.0 for b in up)
    bark_rows = 3 * (doc["counts"]["trunk_triangles"]
                     + doc["counts"]["branch_triangles"])
    assert all(b == 0.0 for b in up[:bark_rows])
    leaves = up[bark_rows:]
    assert len(leaves) == 3 * doc["counts"]["leaf_triangles"]
    assert max(leaves) > 0.5  # some card on or near the crown top
    assert validate_mesh(doc) == []


# --------------------------------------------------------------------------
# stated triangle budget is met
# --------------------------------------------------------------------------

@pytest.mark.parametrize("variant", sorted(TREE_VARIANTS))
def test_stated_triangle_budget_met(variant):
    doc = tree_mesh(variant, seed="seed-Y")
    p = TREE_VARIANTS[variant]
    assert doc["counts"]["triangles"] == len(doc["triangles"])
    assert doc["counts"]["budget_triangles"] == p["budget_triangles"]
    assert len(doc["triangles"]) == p["budget_triangles"]
    # re-derive from construction parameters, not from the stored constant
    expect = 80 + int(p["branch_count"]) * 48 + 2 * int(p["card_count"])
    assert p["budget_triangles"] == expect
    assert doc["counts"]["material_slot_0_triangles"] == \
        80 + int(p["branch_count"]) * 48
    assert doc["counts"]["material_slot_1_triangles"] == 2 * int(p["card_count"])


def test_240_instanced_trees_within_ism_budget():
    worst = max(TREE_VARIANTS[v]["budget_triangles"] for v in TREE_VARIANTS)
    assert worst * 240 < 250_000


# --------------------------------------------------------------------------
# validate_mesh catches every failure it claims to
# --------------------------------------------------------------------------

@pytest.mark.parametrize("variant", sorted(TREE_VARIANTS))
def test_validate_passes_generated_documents(variant):
    assert validate_mesh(tree_mesh(variant, seed="seed-Z")) == []


def test_validate_catches_triangle_index_out_of_range():
    doc = _mini_doc(triangles=[[0, 1, 9]])
    assert any("out of range" in p for p in validate_mesh(doc))


def test_validate_catches_normals_length_mismatch():
    doc = _mini_doc(normals=[[0.0, 0.0, 1.0], [0.0, 0.0, 1.0]])
    assert any("normals length" in p for p in validate_mesh(doc))


def test_validate_catches_uvs_length_mismatch():
    doc = _mini_doc(uvs=[[0.0, 0.0], [1.0, 0.0]])
    assert any("uvs length" in p for p in validate_mesh(doc))


def test_validate_catches_up_bias_length_mismatch():
    doc = _mini_doc(up_bias=[0.0, 1.0])
    assert any("up_bias length" in p for p in validate_mesh(doc))


def test_validate_catches_up_bias_out_of_range():
    doc = _mini_doc(up_bias=[0.0, 1.5, 0.0])
    assert any("not in [0, 1]" in p for p in validate_mesh(doc))


def test_validate_catches_slot_length_mismatch():
    doc = _mini_doc(material_slot_per_triangle=[0, 0])
    assert any("material_slot_per_triangle length" in p
               for p in validate_mesh(doc))


def test_validate_catches_degenerate_triangle():
    doc = _mini_doc(triangles=[[0, 1, 1]])
    assert any("degenerate" in p for p in validate_mesh(doc))


def test_validate_catches_nan_coordinate():
    doc = _mini_doc(vertices=[[0.0, 0.0, float("nan")],
                              [10.0, 0.0, 0.0], [0.0, 10.0, 0.0]])
    assert any("not finite" in p for p in validate_mesh(doc))


def test_validate_catches_infinity_coordinate():
    doc = _mini_doc(vertices=[[0.0, 0.0, float("inf")],
                              [10.0, 0.0, 0.0], [0.0, 10.0, 0.0]])
    assert any("not finite" in p for p in validate_mesh(doc))


def test_validate_catches_leaf_pair_not_sharing_edge():
    # adjacent slot-1 triangles whose quad corners meet at only ONE vertex
    # are not a card: v1 is the only shared corner.
    doc = _mini_doc(
        vertices=[[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [0.0, 10.0, 0.0],
                  [10.0, 10.0, 0.0], [20.0, 10.0, 0.0]],
        triangles=[[0, 1, 2], [1, 3, 4]],
        material_slot_per_triangle=[1, 1],
    )
    problems = validate_mesh(doc)
    assert any("exactly two vertices" in p for p in problems)


def test_validate_accepts_proper_leaf_card_pair():
    # quad split across a shared diagonal is a valid card
    doc = {
        "schema_version": SCHEMA_VERSION,
        "vertices": [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [10.0, 10.0, 0.0],
                     [0.0, 10.0, 0.0]],
        "triangles": [[0, 1, 2], [0, 2, 3]],
        "normals": [[0.0, 0.0, 1.0]] * 4,
        "uvs": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        "material_slot_per_triangle": [1, 1],
    }
    assert validate_mesh(doc) == []


def test_validate_catches_odd_leaf_triangle_count():
    doc = _mini_doc(material_slot_per_triangle=[1])
    assert any("cannot be paired" in p for p in validate_mesh(doc))


# --------------------------------------------------------------------------
# every ValueError path
# --------------------------------------------------------------------------

def test_trunk_geometry_value_errors():
    with pytest.raises(ValueError):
        trunk_geometry(**{**_trunk_geometry_args(), "height_cm": 0.0})
    with pytest.raises(ValueError):
        trunk_geometry(**{**_trunk_geometry_args(), "height_cm": -5.0})
    with pytest.raises(ValueError):
        trunk_geometry(**{**_trunk_geometry_args(), "base_radius_cm": 0.0})
    with pytest.raises(ValueError):
        trunk_geometry(**{**_trunk_geometry_args(), "top_radius_cm": -1.0})
    with pytest.raises(ValueError):
        trunk_geometry(**{**_trunk_geometry_args(), "sides": 2})
    with pytest.raises(ValueError):
        trunk_geometry(**{**_trunk_geometry_args(), "segments": 0})
    with pytest.raises(ValueError):
        trunk_geometry(**{**_trunk_geometry_args(), "lean_deg": -0.1})


def test_branch_geometry_value_errors():
    base = dict(origin_z_cm=150.0, length_cm=180.0, base_radius_cm=8.0,
                top_radius_cm=2.5, sides=8, segments=2, incline_deg=30.0,
                seed="seed")
    with pytest.raises(ValueError):
        branch_geometry(**{**base, "length_cm": 0.0})
    with pytest.raises(ValueError):
        branch_geometry(**{**base, "base_radius_cm": -2.0})
    with pytest.raises(ValueError):
        branch_geometry(**{**base, "sides": 2})
    with pytest.raises(ValueError):
        branch_geometry(**{**base, "segments": 0})
    with pytest.raises(ValueError):
        branch_geometry(**{**base, "incline_deg": 90.0})
    with pytest.raises(ValueError):
        branch_geometry(**{**base, "incline_deg": -1.0})


def test_leaf_cards_value_errors():
    base = dict(crown_centre_z_cm=480.0, crown_radius_cm=260.0,
                card_count=60, card_w_cm=140.0, card_h_cm=95.0, seed="s")
    with pytest.raises(ValueError):
        leaf_cards(**{**base, "crown_radius_cm": 0.0})
    with pytest.raises(ValueError):
        leaf_cards(**{**base, "card_w_cm": -10.0})
    with pytest.raises(ValueError):
        leaf_cards(**{**base, "card_h_cm": 0.0})
    with pytest.raises(ValueError):
        leaf_cards(**{**base, "card_count": 0})
    with pytest.raises(ValueError):
        leaf_cards(**{**base, "card_count": -3})
    with pytest.raises(ValueError):
        leaf_cards(**{**base, "crown_radius_v_cm": 0.0})
    with pytest.raises(ValueError):
        leaf_cards(**{**base, "crown_radius_v_cm": -4.0})


def test_tree_mesh_unknown_variant_value_error():
    with pytest.raises(ValueError):
        tree_mesh("oak", seed="s")
    with pytest.raises(ValueError):
        tree_mesh("", seed="s")
