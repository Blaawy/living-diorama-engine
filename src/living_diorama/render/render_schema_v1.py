"""Render Export format V1: the consumer-neutral projection contract.

A render export is a downstream artifact, not a second save format. It carries
exactly what a future visual consumer needs -- the verified world state, the
episode's raw history, and the cumulative memory -- plus the provenance of the
verified source episode it was projected from. It deliberately omits engine
continuation internals: there is no ``rng_state``, no persistence schema
version, and no environment metadata, and its own ``schema_version`` is
independent of the save schema's.

The document shape is exact at every level this module governs. A key that is
missing means the export is incomplete; a key that is extra means it was
written by something this contract does not describe. Both are refused, never
repaired -- the same discipline the save schema holds.

This module imports only the standard library and ``living_diorama.persistence``
validation vocabulary: render is a read-only consumer of verified persistence
and must never reach into live simulation.
"""

from typing import Final, cast

from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_text,
)

RENDER_EXPORT_FORMAT: Final = "living_diorama_render_export"
"""The format tag every render export declares."""

RENDER_SCHEMA_VERSION: Final = 1
"""The render export schema version this build reads and writes.

Independent from the persistence schema version: the two formats evolve on
their own timelines and must never be conflated.
"""

TOP_LEVEL_KEYS: Final = frozenset(
    {"events", "format", "memory", "schema_version", "source", "world"}
)
"""Exactly the top-level keys a render export carries."""

SOURCE_KEYS: Final = frozenset(
    {
        "engine_version",
        "entity_counts",
        "episode",
        "event_count",
        "parent_state_hash",
        "state_hash",
        "tick",
    }
)
"""Exactly the keys the source provenance section carries."""

WORLD_KEYS: Final = frozenset({"boundaries", "districts", "infrastructure", "laws", "walls"})
"""Exactly the entity arrays the world section carries."""

MEMORY_KEYS: Final = frozenset({"facts", "through_episode", "through_tick"})
"""Exactly the keys the memory section carries."""

ENTITY_COUNT_KEYS: Final = ("boundaries", "districts", "infrastructure", "laws", "walls")
"""The per-kind count keys, in canonical order."""


def require_render_object(value: object, description: str) -> dict[str, object]:
    """Return the value if it is exactly a ``dict``, else raise.

    Raises:
        TypeError: If the value is not exactly a ``dict``.
    """
    if type(value) is not dict:
        raise TypeError(f"{description} must be a JSON object, got {type(value).__name__}")
    return cast("dict[str, object]", value)


def require_render_array(value: object, description: str) -> list[object]:
    """Return the value if it is exactly a ``list``, else raise.

    Raises:
        TypeError: If the value is not exactly a ``list``.
    """
    if type(value) is not list:
        raise TypeError(f"{description} must be a JSON array, got {type(value).__name__}")
    return cast("list[object]", value)


def require_render_keys(
    document: dict[str, object], expected: frozenset[str], description: str
) -> None:
    """Verify a section carries exactly the expected keys.

    Raises:
        ValueError: If any expected key is missing or any extra key is present.
    """
    present = set(document)
    missing = sorted(expected - present)
    unexpected = sorted(present - expected)
    if missing:
        raise ValueError(f"{description} is missing required keys: {missing}")
    if unexpected:
        raise ValueError(f"{description} carries unexpected keys: {unexpected}")


def validate_render_export(value: object) -> dict[str, object]:
    """Verify a document's Render Export V1 envelope, and return it.

    Checks the exact key sets at every governed level, the exact format tag
    and schema version, the provenance types (hashes, exact non-negative
    integers with ``bool`` refused), and the internal agreements the format
    promises: the event count equals the number of exported events, every
    entity count equals its exported array's length, the memory checkpoint
    equals the source episode and tick, and episode 0 alone carries no parent
    hash.

    The scope is deliberately the envelope. The nested entity, event, and
    fact documents are produced and governed by the locked persistence
    serializers, which the build path runs over loader-verified objects; this
    validator does not re-judge their contents, so it is not, by itself, a
    verifier for untrusted third-party export documents.

    Args:
        value: The document to verify.

    Returns:
        The validated document, unchanged.

    Raises:
        TypeError: If the document or a field is of the wrong exact type.
        ValueError: If keys are missing or extra anywhere, or a value breaks
            the contract.
    """
    document = require_render_object(value, "render export")
    require_render_keys(document, TOP_LEVEL_KEYS, "render export")

    declared_format = document["format"]
    if type(declared_format) is not str:
        raise TypeError(f"render export format must be a str, got {type(declared_format).__name__}")
    if declared_format != RENDER_EXPORT_FORMAT:
        raise ValueError(
            f"render export format must be {RENDER_EXPORT_FORMAT!r}, got {declared_format!r}"
        )

    version = require_exact_int(document["schema_version"], "render export schema_version")
    if version != RENDER_SCHEMA_VERSION:
        raise ValueError(
            f"render export declares unsupported schema version {version}; "
            f"this build reads version {RENDER_SCHEMA_VERSION} only"
        )

    source = require_render_object(document["source"], "render export source")
    require_render_keys(source, SOURCE_KEYS, "render export source")
    require_text(source["engine_version"], "render export source engine_version")
    episode = require_exact_int(source["episode"], "render export source episode")
    tick = require_exact_int(source["tick"], "render export source tick")
    event_count = require_exact_int(source["event_count"], "render export source event_count")
    require_hash_hex(source["state_hash"], "render export source state_hash")

    parent_state_hash = source["parent_state_hash"]
    if episode == 0:
        if parent_state_hash is not None:
            raise ValueError("render export of episode 0 must record a null parent_state_hash")
    elif parent_state_hash is None:
        raise ValueError(
            f"render export of episode {episode} must record its parent state hash; "
            "only episode 0 begins a lineage"
        )
    else:
        require_hash_hex(parent_state_hash, "render export source parent_state_hash")

    entity_counts = require_render_object(
        source["entity_counts"], "render export source entity_counts"
    )
    require_render_keys(
        entity_counts, frozenset(ENTITY_COUNT_KEYS), "render export source entity_counts"
    )

    world = require_render_object(document["world"], "render export world")
    require_render_keys(world, WORLD_KEYS, "render export world")
    for kind in ENTITY_COUNT_KEYS:
        entities = require_render_array(world[kind], f"render export world {kind}")
        count = require_exact_int(entity_counts[kind], f"render export source entity_counts {kind}")
        if count != len(entities):
            raise ValueError(
                f"render export source records {count} {kind} but the world section "
                f"holds {len(entities)}"
            )

    events = require_render_array(document["events"], "render export events")
    if event_count != len(events):
        raise ValueError(
            f"render export source records event_count {event_count} but the events "
            f"section holds {len(events)}"
        )

    memory = require_render_object(document["memory"], "render export memory")
    require_render_keys(memory, MEMORY_KEYS, "render export memory")
    require_render_array(memory["facts"], "render export memory facts")
    through_episode = require_exact_int(
        memory["through_episode"], "render export memory through_episode"
    )
    through_tick = require_exact_int(memory["through_tick"], "render export memory through_tick")
    if through_episode != episode:
        raise ValueError(
            f"render export memory is checkpointed through episode {through_episode} but "
            f"the source episode is {episode}"
        )
    if through_tick != tick:
        raise ValueError(
            f"render export memory is checkpointed through tick {through_tick} but the "
            f"source tick is {tick}"
        )

    return document
