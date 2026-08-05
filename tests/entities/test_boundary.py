"""Tests for Boundary endpoint validation."""

import pytest
from conftest import build_boundary


def test_constructs_between_two_distinct_districts() -> None:
    """A boundary joins exactly two districts and starts with no wall."""
    boundary = build_boundary(district_a_id="district_north", district_b_id="district_east")
    assert boundary.district_a_id == "district_north"
    assert boundary.district_b_id == "district_east"
    assert boundary.wall_id is None


def test_rejects_identical_district_endpoints() -> None:
    """A district cannot share a boundary with itself."""
    with pytest.raises(ValueError):
        build_boundary(district_a_id="district_north", district_b_id="district_north")


def test_rejects_identical_endpoints_after_stripping() -> None:
    """Endpoint comparison happens after normalization, so padding cannot slip past."""
    with pytest.raises(ValueError):
        build_boundary(district_a_id="district_north", district_b_id="  district_north  ")


def test_rejects_empty_district_ids() -> None:
    """Both endpoints must name a district."""
    with pytest.raises(ValueError):
        build_boundary(district_a_id="")
    with pytest.raises(ValueError):
        build_boundary(district_b_id="   ")


def test_accepts_optional_wall_id() -> None:
    """A boundary may record the wall standing on it."""
    assert build_boundary(wall_id="wall_0001").wall_id == "wall_0001"


def test_does_not_verify_that_referenced_districts_exist() -> None:
    """Referential integrity is the World's job, deliberately not the entity's.

    This is an architectural boundary, not an oversight: checking existence here
    would require the entity layer to know about a registry it must not import.
    """
    boundary = build_boundary(district_a_id="does_not_exist_a", district_b_id="does_not_exist_b")
    assert boundary.district_a_id == "does_not_exist_a"
