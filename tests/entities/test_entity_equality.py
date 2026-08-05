"""Tests pinning down the deliberate equality semantics of the entity layer.

Entities compare by value across every field, not by ``id`` alone. This is an
architectural decision, not a dataclass default left unexamined: later
save/load round-trip tests assert that a reloaded world equals the world that
was saved, and that assertion only has teeth if equality inspects every field.
"""

from conftest import build_district, build_wall


def test_entities_with_identical_field_values_are_equal() -> None:
    """Value equality is what makes future save/load round-trip tests meaningful."""
    assert build_district() == build_district()


def test_entities_differing_in_any_field_are_not_equal() -> None:
    """A single differing field is enough to make two entities unequal."""
    assert build_district(scarcity=0.1) != build_district(scarcity=0.2)


def test_same_id_with_different_state_is_not_equal() -> None:
    """Equality is not id-based; a mutated entity no longer equals its old value."""
    before = build_wall(id="wall_0001", dependency_score=0.0)
    after = build_wall(id="wall_0001", dependency_score=0.6)
    assert before != after


def test_entities_of_different_types_are_not_equal() -> None:
    """Dataclass equality is type-sensitive, so entity kinds never collide."""
    assert build_district() != build_wall()


def test_entities_are_unhashable() -> None:
    """Mutable entities must not be usable as dict keys or set members.

    Entities are stored as dict *values* keyed by their id, so this costs
    nothing and prevents a mutable object being used as a key by accident.
    """
    assert type(build_district()).__hash__ is None
