"""The Phase 16 spatial occupancy contract (pure Python).

Shapes, gaps, the policy table, the validator's refusal mechanics, and the
pure re-derivation of the locked founding forest. The Blender structural
suite separately pins the tree replica against the real meshes; here the
mathematics itself is proven.
"""

import math

import pytest


def test_circle_gaps(spatial_occupancy):
    """Disc-to-disc gaps: separate, touching, overlapping."""
    so = spatial_occupancy
    assert so.shape_gap(so.circle(0, 0, 2), so.circle(10, 0, 3)) == pytest.approx(5.0)
    assert so.shape_gap(so.circle(0, 0, 2), so.circle(5, 0, 3)) == 0.0
    assert so.shape_gap(so.circle(0, 0, 2), so.circle(1, 0, 3)) == 0.0


def test_capsule_gaps(spatial_occupancy):
    """A street capsule keeps its buffered width along its whole length."""
    so = spatial_occupancy
    road = so.capsule(-10, 0, 10, 0, 3.5)
    assert so.shape_gap(so.circle(0, 9.5, 2), road) == pytest.approx(4.0)
    assert so.shape_gap(so.circle(0, 5.0, 2), road) == 0.0
    assert so.shape_gap(so.circle(16, 0, 1), road) == pytest.approx(1.5)


def test_rect_gaps_are_oriented(spatial_occupancy):
    """Oriented rectangles measure real separation, not bounding circles."""
    so = spatial_occupancy
    first = so.rect(0, 0, 4, 2, 0.0)
    second = so.rect(10, 0, 4, 2, 0.0)
    assert so.shape_gap(first, second) == pytest.approx(2.0)
    rotated = so.rect(10, 0, 4, 2, math.pi / 2)
    assert so.shape_gap(first, rotated) == pytest.approx(4.0)
    overlapping = so.rect(7, 0, 4, 2, 0.0)
    assert so.shape_gap(first, overlapping) == 0.0


def test_rect_capsule_gap(spatial_occupancy):
    """A building footprint against a street capsule: exact, not padded."""
    so = spatial_occupancy
    road = so.capsule(-20, 0, 20, 0, 3.5)
    building = so.rect(0, 8.0, 3, 2, 0.0)
    assert so.shape_gap(building, road) == pytest.approx(2.5)
    inside = so.rect(0, 4.0, 3, 2, 0.0)
    assert so.shape_gap(inside, road) == 0.0


def test_policy_forbids_building_in_road(spatial_occupancy):
    """BUILDING may never overlap ROAD; the refusal names the road."""
    so = spatial_occupancy
    validator = so.PlacementValidator()
    validator.register("road_main", "ROAD", [so.capsule(-20, 0, 20, 0, 3.5)])
    conflicts = validator.place("lot_bad", "BUILDING", [so.rect(0, 3.0, 3, 2, 0.0)])
    assert conflicts and conflicts[0]["conflict_with"] == "road_main"
    assert validator.rejections and validator.rejections[0]["candidate"] == "lot_bad"


def test_policy_forbids_tree_in_building(spatial_occupancy):
    """VEGETATION may never intersect a BUILDING envelope."""
    so = spatial_occupancy
    validator = so.PlacementValidator()
    validator.register("lot_home", "BUILDING", [so.rect(0, 0, 4, 3, 0.3)])
    conflicts = validator.place("green_bad", "VEGETATION", [so.circle(2, 1, 2.0)])
    assert conflicts and conflicts[0]["their_category"] == "BUILDING"


def test_policy_allows_paving_under_buildings(spatial_occupancy):
    """PAVING is walkable ground: buildings may stand on it."""
    so = spatial_occupancy
    validator = so.PlacementValidator()
    validator.register("walk", "PAVING", [so.rect(0, 0, 6, 6, 0.0)])
    assert validator.place("lot_on_walk", "BUILDING", [so.rect(0, 0, 3, 2, 0.0)]) == []


def test_clean_placement_registers(spatial_occupancy):
    """An accepted candidate occupies its ground for the next candidate."""
    so = spatial_occupancy
    validator = so.PlacementValidator()
    assert validator.place("lot_a", "BUILDING", [so.rect(0, 0, 3, 2, 0.0)]) == []
    conflicts = validator.place("lot_b", "BUILDING", [so.rect(1, 0, 3, 2, 0.0)])
    assert conflicts and conflicts[0]["conflict_with"] == "lot_a"
    summary = validator.rejection_summary()
    assert summary.get("building-building") == 1


def test_fixed_truth_is_never_a_candidate(spatial_occupancy):
    """ROAD, WALL, HISTORY, WATER are registered truth, never placed."""
    so = spatial_occupancy
    validator = so.PlacementValidator()
    with pytest.raises(ValueError, match="fixed truth"):
        validator.conflicts("ROAD", [so.circle(0, 0, 1)])


def test_founding_forest_replica_shape(spatial_module_trees):
    """The pure replica reproduces the locked forest's structure."""
    assert len({tree["cluster"] for tree in spatial_module_trees}) == 40
    assert 80 <= len(spatial_module_trees) <= 200
    for tree in spatial_module_trees:
        assert 1.0 <= tree["r"] <= 2.7


def test_founding_forest_replica_is_deterministic(spatial_occupancy, master_document):
    """Two derivations of the forest are identical."""
    first = spatial_occupancy.founding_trees(master_document)
    second = spatial_occupancy.founding_trees(master_document)
    assert first == second


def test_priority_classes_cover_every_category(spatial_occupancy):
    """The obstacle priority model is total and consistent.

    Class A is immutable semantic history, Class B chosen city structure,
    Class C flexible architecture, Class D decoration. Every occupancy
    category belongs to exactly one class.
    """
    classes = spatial_occupancy.PRIORITY_CLASSES
    assert tuple(sorted(classes)) == ("A", "B", "C", "D")
    members = [category for group in classes.values() for category in group]
    assert sorted(members) == sorted(set(members)), "a category may not serve two classes"
    assert set(members) == set(spatial_occupancy.CATEGORIES)
    assert "WALL" in classes["A"] and "PLATE" in classes["A"]
    assert "ROAD" in classes["B"] and "GROVE" in classes["B"]
    assert "VEGETATION" in classes["D"]


def test_designed_planting_may_stand_on_a_plate(spatial_occupancy):
    """PLATE ground accepts landscaping while refusing buildings."""
    so = spatial_occupancy
    validator = so.PlacementValidator()
    validator.register("plate_a", "PLATE", [so.circle(0, 0, 20)])
    assert validator.place("garden_tree", "VEGETATION", [so.circle(4, 3, 1.6)]) == []
    conflicts = validator.place("lot_on_plate", "BUILDING", [so.rect(2, 2, 3, 2, 0.0)])
    assert conflicts and conflicts[0]["their_category"] == "PLATE"


def test_preserved_groves_hold_their_ground(spatial_occupancy):
    """A building may not crowd a preserved grove; new planting may join it."""
    so = spatial_occupancy
    validator = so.PlacementValidator()
    validator.register("grove_07", "GROVE", [so.circle(10, 10, 2.4)])
    conflicts = validator.place("lot_bad", "BUILDING", [so.rect(12, 10, 2.5, 2.0, 0.0)])
    assert conflicts and conflicts[0]["their_category"] == "GROVE"
    assert validator.place("park_group", "VEGETATION", [so.circle(13.5, 10, 1.6)]) == []
