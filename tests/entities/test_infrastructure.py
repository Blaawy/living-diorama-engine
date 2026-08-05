"""Tests for Infrastructure construction and validation."""

import pytest
from conftest import build_infrastructure
from living_diorama.entities import InfrastructureType


def test_constructs_with_valid_values() -> None:
    """A well-formed infrastructure entity keeps the state it was given."""
    infra = build_infrastructure(capacity=2.5, dependency_score=0.4, degraded=True)
    assert infra.capacity == 2.5
    assert infra.dependency_score == 0.4
    assert infra.degraded is True


def test_accepts_every_infrastructure_type() -> None:
    """All four infrastructure kinds are constructible values."""
    for infra_type in InfrastructureType:
        infra = build_infrastructure(infrastructure_type=infra_type)
        assert infra.infrastructure_type is infra_type


def test_rejects_negative_capacity() -> None:
    """Capacity is a magnitude and cannot be negative."""
    with pytest.raises(ValueError):
        build_infrastructure(capacity=-0.1)


def test_rejects_dependency_score_outside_unit_interval() -> None:
    """Dependency is a normalized score bounded to 0.0-1.0."""
    with pytest.raises(ValueError):
        build_infrastructure(dependency_score=1.1)
    with pytest.raises(ValueError):
        build_infrastructure(dependency_score=-0.1)


def test_rejects_empty_boundary_id() -> None:
    """Infrastructure must serve a named boundary."""
    with pytest.raises(ValueError):
        build_infrastructure(boundary_id="")
