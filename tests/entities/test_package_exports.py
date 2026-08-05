"""Tests that the entities package exposes its intended public API."""

import living_diorama.entities as entities

EXPECTED_EXPORTS = {
    "BaseEntity",
    "Boundary",
    "District",
    "EntityId",
    "Infrastructure",
    "InfrastructureType",
    "IsolationState",
    "Law",
    "LawValue",
    "ResourcePool",
    "ResourceType",
    "Tick",
    "Wall",
}


def test_all_matches_the_intended_public_api() -> None:
    """__all__ is the deliberate contract, not an accident of import order."""
    assert set(entities.__all__) == EXPECTED_EXPORTS


def test_every_exported_name_is_importable() -> None:
    """Everything promised by __all__ must actually resolve on the package."""
    for name in entities.__all__:
        assert hasattr(entities, name), f"{name} is exported but missing"
