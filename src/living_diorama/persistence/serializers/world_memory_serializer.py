"""Persistence-only handling of the opaque world-memory document.

Phase 10 carries this document; it does not understand it. Deciding which facts
matter, how they are worded, or what they imply belongs to a later phase, and
doing any of it here would put interpretation inside the save layer where no
test could distinguish a recorded fact from an invented one.
"""

import copy
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from living_diorama.events.event import JsonValue
from living_diorama.persistence.json_codec import require_document, require_json_value
from living_diorama.persistence.schema.world_schema_v1 import (
    SCHEMA_VERSION,
    require_exact_keys,
    require_schema_version,
)

_KEYS: Final = frozenset({"facts", "schema_version"})
"""Exactly the keys the world-memory document carries."""


def empty_world_memory() -> dict[str, JsonValue]:
    """Return the placeholder document written when no memory is supplied."""
    return {"facts": [], "schema_version": SCHEMA_VERSION}


def serialize_world_memory(
    world_memory: object | None, description: str = "world_memory"
) -> dict[str, JsonValue]:
    """Return a validated, independent copy of the world-memory document.

    Facts are checked for JSON safety and copied in order. Nothing is filtered,
    summarized, deduplicated, reordered, or generated: what the caller supplied
    is exactly what lands on disk.

    Args:
        world_memory: The document to persist, or ``None`` for the placeholder.
        description: What is being checked, used in error messages.

    Returns:
        A new document safe to encode.

    Raises:
        TypeError: If the document or a fact is not JSON-compatible, or
            ``facts`` is not a list.
        ValueError: If keys are missing or extra, or the schema version is
            unsupported.
    """
    if world_memory is None:
        return empty_world_memory()

    if not isinstance(world_memory, Mapping):
        raise TypeError(f"{description} must be a mapping, got {type(world_memory).__name__}")
    document = require_document(require_json_value(dict(world_memory), description), description)
    require_exact_keys(document, _KEYS, description)
    require_schema_version(document, description)

    facts = document["facts"]
    if type(facts) is not list:
        raise TypeError(f"{description} facts must be a list, got {type(facts).__name__}")
    return {
        "facts": [
            require_json_value(fact, f"{description} facts[{index}]")
            for index, fact in enumerate(facts)
        ],
        "schema_version": SCHEMA_VERSION,
    }


def deserialize_world_memory(
    value: JsonValue, description: str = "world_memory"
) -> "MappingProxyType[str, JsonValue]":
    """Return the loaded world-memory document, detached and read-only.

    Raises:
        TypeError: If the value is not a JSON object or ``facts`` is not a list.
        ValueError: If keys are missing or extra, or the schema version is
            unsupported.
    """
    document = require_document(value, description)
    require_exact_keys(document, _KEYS, description)
    require_schema_version(document, description)

    facts = document["facts"]
    if type(facts) is not list:
        raise TypeError(f"{description} facts must be a list, got {type(facts).__name__}")
    return MappingProxyType({"facts": copy.deepcopy(facts), "schema_version": SCHEMA_VERSION})
