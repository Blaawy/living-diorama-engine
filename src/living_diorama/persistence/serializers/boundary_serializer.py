"""Serialization for :class:`Boundary`."""

from living_diorama.entities import Boundary, EntityId
from living_diorama.events.event import JsonValue
from living_diorama.persistence.json_codec import require_document
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_identifier,
)

_KEYS = frozenset({"created_tick", "district_a_id", "district_b_id", "id", "wall_id"})
"""Exactly the keys a serialized boundary carries."""


def serialize_boundary(boundary: Boundary) -> dict[str, JsonValue]:
    """Return a boundary's stored state as a JSON object.

    Endpoint roles are written exactly as stored. They are not normalized into
    alphabetical order: which district is A and which is B is part of the
    world's identity, and swapping them would silently rewrite it.

    Raises:
        TypeError: If the argument is not a Boundary or a field is mistyped.
        ValueError: If an identifier is noncanonical, a tick is negative, or the
            boundary joins a district to itself.
    """
    if not isinstance(boundary, Boundary):
        raise TypeError(f"boundary must be a Boundary, got {type(boundary).__name__}")
    label = require_identifier(boundary.id, "boundary id")
    district_a = require_identifier(boundary.district_a_id, f"district_a_id of boundary {label!r}")
    district_b = require_identifier(boundary.district_b_id, f"district_b_id of boundary {label!r}")
    if district_a == district_b:
        raise ValueError(
            f"boundary {label!r} joins district {district_a!r} to itself; a boundary "
            "must separate two distinct districts"
        )
    stored_wall_id = boundary.wall_id
    wall_id: EntityId | None = (
        None
        if stored_wall_id is None
        else require_identifier(stored_wall_id, f"wall_id of boundary {label!r}")
    )
    return {
        "created_tick": require_exact_int(
            boundary.created_tick, f"created_tick of boundary {label!r}"
        ),
        "district_a_id": district_a,
        "district_b_id": district_b,
        "id": label,
        "wall_id": wall_id,
    }


def deserialize_boundary(value: JsonValue, description: str) -> tuple[Boundary, str | None]:
    """Rebuild a boundary, returning it detached from its wall reference.

    The boundary comes back with ``wall_id`` set to ``None`` and the serialized
    value returned alongside it. A wall cannot be registered before its
    boundary exists, and the aggregate sets the back-reference itself when the
    wall is added, so reconstruction adds the boundary in this valid
    intermediate form and afterwards checks that the link the aggregate built
    matches the one that was saved.

    Raises:
        TypeError: If the value is not a JSON object or a field is mistyped.
        ValueError: If keys are missing or extra, or a field is invalid.
    """
    document = require_document(value, description)
    require_exact_keys(document, _KEYS, description)
    label = require_identifier(document["id"], f"{description} id")
    district_a = require_identifier(document["district_a_id"], f"{description} district_a_id")
    district_b = require_identifier(document["district_b_id"], f"{description} district_b_id")
    if district_a == district_b:
        raise ValueError(f"{description} joins district {district_a!r} to itself")

    stored_wall_id = document["wall_id"]
    expected_wall: EntityId | None = (
        None
        if stored_wall_id is None
        else require_identifier(stored_wall_id, f"{description} wall_id")
    )

    boundary = Boundary(
        id=label,
        created_tick=require_exact_int(document["created_tick"], f"{description} created_tick"),
        district_a_id=district_a,
        district_b_id=district_b,
        wall_id=None,
    )
    return boundary, expected_wall
