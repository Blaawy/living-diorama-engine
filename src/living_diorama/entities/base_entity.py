"""Shared entity primitives for the district-level MVP world model.

Defines the identifier type aliases used across the entity layer, the local
validation helpers those entities share, and the abstract ``BaseEntity`` all
entities extend.

Entities in this package hold data and perform local validation only. They do
not run simulation behavior, publish events, read or write files, consult a
clock, or draw randomness. Nothing here may import any other
``living_diorama`` package.
"""

from abc import ABC
from dataclasses import dataclass

type EntityId = str
"""Stable identifier for an entity.

Identifiers are supplied by the caller. The entity layer deliberately does not
generate them: ID allocation is a world-construction concern that belongs
outside this layer.
"""

type Tick = int
"""A discrete simulation time step, counted from zero."""


def require_non_empty_id(value: str, field_name: str) -> str:
    """Normalize and validate an identifier-like string.

    Args:
        value: The raw identifier to check.
        field_name: Name of the field, used in the error message.

    Returns:
        The identifier with surrounding whitespace stripped.

    Raises:
        ValueError: If the identifier is empty or contains only whitespace.
    """
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must be a non-empty string")
    return stripped


def require_non_negative(value: float, field_name: str) -> None:
    """Validate that a numeric field is zero or greater.

    Args:
        value: The value to check.
        field_name: Name of the field, used in the error message.

    Raises:
        ValueError: If the value is negative.
    """
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0, got {value}")


def require_unit_interval(value: float, field_name: str) -> None:
    """Validate that a normalized score lies within the closed range 0.0-1.0.

    Args:
        value: The value to check.
        field_name: Name of the field, used in the error message.

    Raises:
        ValueError: If the value falls outside 0.0-1.0 inclusive.
    """
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be within 0.0-1.0, got {value}")


@dataclass(slots=True)
class BaseEntity(ABC):
    """Abstract base for every identified entity in the world model.

    Entities compare by value (all fields), not by identity or by ``id`` alone.
    This is deliberate: later save/load round-trip tests assert that a reloaded
    world equals the world that was saved, and that assertion is only meaningful
    if equality inspects every field. Compare ``entity.id`` explicitly when
    identity is what you actually mean.

    Because entities are mutable dataclasses with value equality, they are
    unhashable. Entities are held in ``dict`` values keyed by their ``id``, so
    this costs nothing and prevents accidental use of a mutable object as a key.

    Attributes:
        id: Caller-supplied stable identifier. Stored stripped of surrounding
            whitespace.
        created_tick: Tick at which this entity came into existence.
    """

    id: EntityId
    created_tick: Tick

    def __post_init__(self) -> None:
        """Validate and normalize the shared entity fields.

        Raises:
            TypeError: If ``BaseEntity`` is instantiated directly.
            ValueError: If ``id`` is blank or ``created_tick`` is negative.
        """
        if type(self) is BaseEntity:
            raise TypeError("BaseEntity is abstract and must not be instantiated directly")
        self.id = require_non_empty_id(self.id, "id")
        require_non_negative(self.created_tick, "created_tick")
