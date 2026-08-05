"""Tests for BaseEntity: abstractness, identifier normalization, tick validation."""

import pytest
from conftest import build_district

from living_diorama.entities import BaseEntity


def test_base_entity_cannot_be_instantiated_directly() -> None:
    """BaseEntity is abstract; only concrete entities may be constructed."""
    with pytest.raises(TypeError):
        BaseEntity(id="anything", created_tick=0)


def test_rejects_empty_id() -> None:
    """An empty identifier is not a usable identity."""
    with pytest.raises(ValueError):
        build_district(id="")


def test_rejects_whitespace_only_id() -> None:
    """A whitespace-only identifier is empty once stripped, so it is rejected."""
    with pytest.raises(ValueError):
        build_district(id="   ")


def test_strips_surrounding_whitespace_from_id() -> None:
    """Identifiers are normalized on construction so lookups stay consistent."""
    district = build_district(id="  district_north  ")
    assert district.id == "district_north"


def test_rejects_negative_created_tick() -> None:
    """Time starts at zero; nothing can be created before it."""
    with pytest.raises(ValueError):
        build_district(created_tick=-1)


def test_accepts_created_tick_of_zero() -> None:
    """Tick zero is the valid start of the world, not an edge-case failure."""
    assert build_district(created_tick=0).created_tick == 0


def test_entities_are_slotted() -> None:
    """Entities use slots, so a typo'd attribute fails loudly instead of silently."""
    district = build_district()
    with pytest.raises(AttributeError):
        district.populaton = 5  # type: ignore[attr-defined]
