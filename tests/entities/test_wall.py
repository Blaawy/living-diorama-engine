"""Tests for Wall construction and validation."""

import pytest
from conftest import build_wall


def test_constructs_with_valid_values() -> None:
    """A well-formed wall keeps exactly the state it was given."""
    wall = build_wall(built_tick=120, created_tick=100, integrity=0.9)
    assert wall.built_tick == 120
    assert wall.integrity == 0.9
    assert wall.permanent is True


def test_rejects_built_tick_before_created_tick() -> None:
    """A wall cannot finish construction before it began to exist."""
    with pytest.raises(ValueError):
        build_wall(created_tick=100, built_tick=99)


def test_accepts_built_tick_equal_to_created_tick() -> None:
    """Same-tick creation and construction is valid, not an off-by-one failure."""
    assert build_wall(created_tick=100, built_tick=100).built_tick == 100


def test_rejects_integrity_outside_unit_interval() -> None:
    """Integrity is a normalized score bounded to 0.0-1.0."""
    with pytest.raises(ValueError):
        build_wall(integrity=1.1)
    with pytest.raises(ValueError):
        build_wall(integrity=-0.1)


def test_rejects_dependency_values_outside_unit_interval() -> None:
    """All three dependency scores are normalized and bounded to 0.0-1.0."""
    with pytest.raises(ValueError):
        build_wall(dependency_score=1.1)
    with pytest.raises(ValueError):
        build_wall(transport_dependency=-0.1)
    with pytest.raises(ValueError):
        build_wall(resource_dependency=1.5)


def test_accepts_dependency_boundaries() -> None:
    """0.0 and 1.0 are valid saturation points for dependency scores."""
    saturated = build_wall(dependency_score=1.0, transport_dependency=1.0, resource_dependency=1.0)
    assert saturated.dependency_score == 1.0


def test_rejects_empty_boundary_id() -> None:
    """A wall must stand on a named boundary."""
    with pytest.raises(ValueError):
        build_wall(boundary_id="  ")
