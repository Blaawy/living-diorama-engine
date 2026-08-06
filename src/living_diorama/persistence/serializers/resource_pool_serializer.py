"""Serialization for :class:`ResourcePool`."""

from collections.abc import Mapping

from living_diorama.entities import ResourcePool, ResourceType
from living_diorama.events.event import JsonValue
from living_diorama.persistence.json_codec import require_document
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_keys,
    require_non_negative_real,
)

_RESOURCE_KEYS = frozenset(resource.value for resource in ResourceType)
"""Every resource name, all of which must always be present."""


def serialize_resource_pool(pool: ResourcePool, description: str) -> dict[str, JsonValue]:
    """Return a pool's stock as a JSON object keyed by resource name.

    Every resource is written even when its amount is zero. A save that omitted
    empty stocks would depend on which resources happened to be non-zero, and
    two worlds holding the same thing would produce different bytes.

    Raises:
        TypeError: If the argument is not a ResourcePool or an amount is not a
            real number.
        ValueError: If an amount is not finite or is negative.
    """
    if not isinstance(pool, ResourcePool):
        raise TypeError(f"{description} must be a ResourcePool, got {type(pool).__name__}")

    # The constructor normalizes the mapping, but the pool stays reachable and
    # its stock can be replaced afterwards. Serializing only the keys this build
    # recognizes would quietly drop a corrupted entry and write a repaired
    # subset, so the stored key set is checked instead of trusted.
    stock = pool.stock
    if not isinstance(stock, Mapping):
        raise TypeError(f"{description} stock must be a mapping, got {type(stock).__name__}")
    unknown = sorted(repr(key) for key in stock if type(key) is not ResourceType)
    if unknown:
        raise ValueError(f"{description} carries keys that are not ResourceType members: {unknown}")
    missing = sorted(resource.value for resource in ResourceType if resource not in stock)
    if missing:
        raise ValueError(f"{description} is missing resources: {missing}")

    return {
        resource.value: require_non_negative_real(
            stock[resource], f"{description}[{resource.value}]"
        )
        for resource in ResourceType
    }


def deserialize_resource_pool(value: JsonValue, description: str) -> ResourcePool:
    """Rebuild a pool from a JSON object.

    Raises:
        TypeError: If the value is not a JSON object or an amount is mistyped.
        ValueError: If a resource is missing, unknown, negative, or non-finite.
    """
    document = require_document(value, description)
    require_exact_keys(document, _RESOURCE_KEYS, description)
    return ResourcePool(
        stock={
            resource: require_non_negative_real(
                document[resource.value], f"{description}[{resource.value}]"
            )
            for resource in ResourceType
        }
    )
