"""Serialization for :class:`Wall`."""

from living_diorama.entities import Wall
from living_diorama.events.event import JsonValue
from living_diorama.persistence.json_codec import require_document
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_flag,
    require_identifier,
    require_unit_interval,
)
from living_diorama.persistence.serializers._runtime_types import is_runtime_instance

_KEYS = frozenset(
    {
        "active",
        "boundary_id",
        "built_tick",
        "created_tick",
        "dependency_score",
        "id",
        "integrity",
        "permanent",
        "resource_dependency",
        "transport_dependency",
    }
)
"""Exactly the keys a serialized wall carries."""


def serialize_wall(wall: Wall) -> dict[str, JsonValue]:
    """Return a wall's stored state as a JSON object.

    The accumulated dependency fields are written verbatim. Persistence neither
    decays nor recomputes them: a wall the world has organized itself around
    must come back exactly as load-bearing as it was, or the consequence stops
    being permanent.

    Raises:
        TypeError: If the argument is not a Wall or a field is mistyped.
        ValueError: If a field carries an invalid value, or the wall claims to
            have been built before it was created.
    """
    if not is_runtime_instance(wall, Wall):
        raise TypeError(f"wall must be a Wall, got {type(wall).__name__}")
    label = require_identifier(wall.id, "wall id")
    created = require_exact_int(wall.created_tick, f"created_tick of wall {label!r}")
    built = require_exact_int(wall.built_tick, f"built_tick of wall {label!r}")
    if built < created:
        raise ValueError(
            f"wall {label!r} was built on tick {built} before it was created on tick {created}"
        )
    return {
        "active": require_flag(wall.active, f"active of wall {label!r}"),
        "boundary_id": require_identifier(wall.boundary_id, f"boundary_id of wall {label!r}"),
        "built_tick": built,
        "created_tick": created,
        "dependency_score": require_unit_interval(
            wall.dependency_score, f"dependency_score of wall {label!r}"
        ),
        "id": label,
        "integrity": require_unit_interval(wall.integrity, f"integrity of wall {label!r}"),
        "permanent": require_flag(wall.permanent, f"permanent of wall {label!r}"),
        "resource_dependency": require_unit_interval(
            wall.resource_dependency, f"resource_dependency of wall {label!r}"
        ),
        "transport_dependency": require_unit_interval(
            wall.transport_dependency, f"transport_dependency of wall {label!r}"
        ),
    }


def deserialize_wall(value: JsonValue, description: str) -> Wall:
    """Rebuild a wall from a JSON object.

    Raises:
        TypeError: If the value is not a JSON object or a field is mistyped.
        ValueError: If keys are missing or extra, or a field is invalid.
    """
    document = require_document(value, description)
    require_exact_keys(document, _KEYS, description)
    return Wall(
        id=require_identifier(document["id"], f"{description} id"),
        created_tick=require_exact_int(document["created_tick"], f"{description} created_tick"),
        boundary_id=require_identifier(document["boundary_id"], f"{description} boundary_id"),
        built_tick=require_exact_int(document["built_tick"], f"{description} built_tick"),
        integrity=require_unit_interval(document["integrity"], f"{description} integrity"),
        active=require_flag(document["active"], f"{description} active"),
        permanent=require_flag(document["permanent"], f"{description} permanent"),
        dependency_score=require_unit_interval(
            document["dependency_score"], f"{description} dependency_score"
        ),
        transport_dependency=require_unit_interval(
            document["transport_dependency"], f"{description} transport_dependency"
        ),
        resource_dependency=require_unit_interval(
            document["resource_dependency"], f"{description} resource_dependency"
        ),
    )
