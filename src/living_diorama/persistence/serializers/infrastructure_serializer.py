"""Serialization for :class:`Infrastructure`."""

from living_diorama.entities import Infrastructure, InfrastructureType
from living_diorama.events.event import JsonValue
from living_diorama.persistence.json_codec import require_document
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_flag,
    require_identifier,
    require_non_negative_real,
    require_unit_interval,
)
from living_diorama.persistence.serializers._runtime_types import is_runtime_instance

_KEYS = frozenset(
    {
        "boundary_id",
        "capacity",
        "created_tick",
        "degraded",
        "dependency_score",
        "id",
        "infrastructure_type",
    }
)
"""Exactly the keys a serialized infrastructure entity carries."""


def _infrastructure_type(value: JsonValue, description: str) -> InfrastructureType:
    """Return the infrastructure kind named by a stable enum value.

    Raises:
        TypeError: If the value is not a ``str``.
        ValueError: If it names no known infrastructure kind.
    """
    if type(value) is not str:
        raise TypeError(f"{description} must be a str, got {type(value).__name__}")
    try:
        return InfrastructureType(value)
    except ValueError as error:
        known = sorted(kind.value for kind in InfrastructureType)
        raise ValueError(f"{description} must be one of {known}, got {value!r}") from error


def serialize_infrastructure(infrastructure: Infrastructure) -> dict[str, JsonValue]:
    """Return an infrastructure entity's stored state as a JSON object.

    Raises:
        TypeError: If the argument is not Infrastructure or a field is mistyped.
        ValueError: If a field carries an invalid value.
    """
    if not is_runtime_instance(infrastructure, Infrastructure):
        raise TypeError(
            f"infrastructure must be an Infrastructure, got {type(infrastructure).__name__}"
        )
    label = require_identifier(infrastructure.id, "infrastructure id")
    if type(infrastructure.infrastructure_type) is not InfrastructureType:
        raise TypeError(
            f"infrastructure_type of infrastructure {label!r} must be an "
            f"InfrastructureType, got {type(infrastructure.infrastructure_type).__name__}"
        )
    return {
        "boundary_id": require_identifier(
            infrastructure.boundary_id, f"boundary_id of infrastructure {label!r}"
        ),
        "capacity": require_non_negative_real(
            infrastructure.capacity, f"capacity of infrastructure {label!r}"
        ),
        "created_tick": require_exact_int(
            infrastructure.created_tick, f"created_tick of infrastructure {label!r}"
        ),
        "degraded": require_flag(infrastructure.degraded, f"degraded of infrastructure {label!r}"),
        "dependency_score": require_unit_interval(
            infrastructure.dependency_score, f"dependency_score of infrastructure {label!r}"
        ),
        "id": label,
        "infrastructure_type": infrastructure.infrastructure_type.value,
    }


def deserialize_infrastructure(value: JsonValue, description: str) -> Infrastructure:
    """Rebuild an infrastructure entity from a JSON object.

    Raises:
        TypeError: If the value is not a JSON object or a field is mistyped.
        ValueError: If keys are missing or extra, or a field is invalid.
    """
    document = require_document(value, description)
    require_exact_keys(document, _KEYS, description)
    return Infrastructure(
        id=require_identifier(document["id"], f"{description} id"),
        created_tick=require_exact_int(document["created_tick"], f"{description} created_tick"),
        boundary_id=require_identifier(document["boundary_id"], f"{description} boundary_id"),
        infrastructure_type=_infrastructure_type(
            document["infrastructure_type"], f"{description} infrastructure_type"
        ),
        capacity=require_non_negative_real(document["capacity"], f"{description} capacity"),
        dependency_score=require_unit_interval(
            document["dependency_score"], f"{description} dependency_score"
        ),
        degraded=require_flag(document["degraded"], f"{description} degraded"),
    )
