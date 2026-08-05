"""Tests for Law construction and validation."""

import pytest
from conftest import build_law


def test_constructs_with_valid_values() -> None:
    """A well-formed law records its current and previous values."""
    law = build_law(name="movement_resource_sharing", current_value=True, previous_value=False)
    assert law.name == "movement_resource_sharing"
    assert law.current_value is True
    assert law.previous_value is False


def test_accepts_the_full_range_of_law_values() -> None:
    """LawValue admits JSON scalars, which covers switches and thresholds."""
    for value in ("inactive", 3, 0.05, True, None):
        assert build_law(current_value=value).current_value == value


def test_strips_and_rejects_blank_name() -> None:
    """A law must be nameable; blank or whitespace-only names are rejected."""
    assert build_law(name="  curfew  ").name == "curfew"
    with pytest.raises(ValueError):
        build_law(name="")
    with pytest.raises(ValueError):
        build_law(name="   ")


def test_rejects_negative_changed_episode() -> None:
    """Episodes are numbered from zero."""
    with pytest.raises(ValueError):
        build_law(changed_episode=-1)


def test_rejects_negative_restored_tick() -> None:
    """A restoration cannot happen before the world began."""
    with pytest.raises(ValueError):
        build_law(restored_tick=-1)


def test_accepts_none_restored_tick() -> None:
    """A law that has never been restored records None, not a sentinel number."""
    assert build_law(restored_tick=None).restored_tick is None


def test_accepts_zero_restored_tick() -> None:
    """Tick zero is a valid restoration time, distinct from None."""
    assert build_law(restored_tick=0).restored_tick == 0
