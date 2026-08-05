"""Tests for District construction and range validation."""

import pytest
from conftest import build_district

from living_diorama.entities import IsolationState, ResourceType


def test_constructs_with_valid_values() -> None:
    """A well-formed district keeps exactly the state it was given."""
    district = build_district(population=120, housing_capacity=200)
    assert district.population == 120
    assert district.housing_capacity == 200
    assert district.isolation_state is IsolationState.OPEN
    assert district.resources.amount_of(ResourceType.FOOD) == 10.0


def test_accepts_every_isolation_state() -> None:
    """All three isolation states are constructible values, not just OPEN."""
    for state in IsolationState:
        assert build_district(isolation_state=state).isolation_state is state


def test_rejects_negative_population() -> None:
    """A district cannot contain a negative number of people."""
    with pytest.raises(ValueError):
        build_district(population=-1)


def test_rejects_negative_housing_capacity() -> None:
    """Housing capacity is a physical quantity and cannot be negative."""
    with pytest.raises(ValueError):
        build_district(housing_capacity=-1)


def test_rejects_negative_rates() -> None:
    """Production and consumption rates are magnitudes, never negative."""
    with pytest.raises(ValueError):
        build_district(production_rate=-0.1)
    with pytest.raises(ValueError):
        build_district(consumption_rate=-0.1)


def test_rejects_normalized_scores_above_one() -> None:
    """Every social score is normalized; above 1.0 is out of range."""
    with pytest.raises(ValueError):
        build_district(scarcity=1.1)
    with pytest.raises(ValueError):
        build_district(fear=1.1)
    with pytest.raises(ValueError):
        build_district(trust=1.1)
    with pytest.raises(ValueError):
        build_district(institutional_pressure=1.1)


def test_rejects_normalized_scores_below_zero() -> None:
    """Every social score is normalized; below 0.0 is out of range."""
    with pytest.raises(ValueError):
        build_district(scarcity=-0.1)
    with pytest.raises(ValueError):
        build_district(fear=-0.1)
    with pytest.raises(ValueError):
        build_district(trust=-0.1)
    with pytest.raises(ValueError):
        build_district(institutional_pressure=-0.1)


def test_accepts_normalized_score_boundaries() -> None:
    """0.0 and 1.0 are valid saturation points, not off-by-one failures."""
    low = build_district(scarcity=0.0, fear=0.0, trust=0.0, institutional_pressure=0.0)
    high = build_district(scarcity=1.0, fear=1.0, trust=1.0, institutional_pressure=1.0)
    assert low.scarcity == 0.0
    assert high.institutional_pressure == 1.0
