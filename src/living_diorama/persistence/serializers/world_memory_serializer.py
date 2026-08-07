"""Serialization of :class:`WorldMemory` into the world-memory payload.

Persistence stores memory; it does not judge it. Nothing here decides what is
significant, writes a summary, invents a fact, or drops one. It converts a
memory the caller already distilled into strict documents, and converts strict
documents back into a memory -- rejecting anything that does not survive the
domain object's own validation.

The checkpoint deliberately does not appear in the file. The episode manifest
already states the authoritative episode and tick, and writing them twice would
create two sources of truth that could drift apart.
"""

from typing import Final

from living_diorama.events.event import JsonValue
from living_diorama.memory import MemoryFact, WorldMemory
from living_diorama.memory._integrity import snapshot_world_memory
from living_diorama.persistence.json_codec import require_document
from living_diorama.persistence.schema.world_schema_v1 import (
    SCHEMA_VERSION,
    require_exact_int,
    require_exact_keys,
    require_schema_version,
)

_KEYS: Final = frozenset({"facts", "schema_version"})
"""Exactly the keys the world-memory document carries."""


def empty_world_memory() -> dict[str, JsonValue]:
    """Return the document written for a memory holding nothing."""
    return {"facts": [], "schema_version": SCHEMA_VERSION}


def serialize_world_memory(
    world_memory: object, description: str = "world_memory"
) -> dict[str, JsonValue]:
    """Return the document for a memory, in its own canonical fact order.

    Facts are written exactly as the memory holds them. They are not sorted
    here: the memory has already established canonical order and re-deriving it
    at the storage layer would give two places the power to decide what the
    history says came first.

    Args:
        world_memory: The memory to persist. Normalized into exact base objects
            before anything is written.
        description: What is being written, used in error messages.

    Returns:
        A new document safe to encode.

    Raises:
        TypeError: If the argument is not a ``WorldMemory``, or a fact is not a
            ``MemoryFact``.
        ValueError: If a fact's claimed identifier or summary is not what its own
            content implies.
    """
    # Normalized first. ``to_document()`` is overridable, so serializing the
    # caller's facts directly would let a subclass decide what lands on disk --
    # including a summary the fact's own content does not imply, which the loader
    # would then correctly refuse. The normalized base objects are the only ones
    # asked for a document.
    snapshot = snapshot_world_memory(world_memory, description)
    return {
        "facts": [fact.to_document() for fact in snapshot.facts],
        "schema_version": SCHEMA_VERSION,
    }


def deserialize_world_memory(
    value: JsonValue,
    description: str = "world_memory",
    *,
    through_episode: int,
    through_tick: int,
) -> WorldMemory:
    """Rebuild a memory from a document, checkpointed to the verified manifest.

    Every fact is reconstructed through the domain object, which recomputes its
    identifier and summary and refuses a document whose recorded values disagree
    with what its own content implies. Canonical order, duplicate identifiers,
    repeated wall-build claims, and facts lying beyond the checkpoint are all
    rejected by ``WorldMemory`` itself rather than re-checked here.

    The empty Phase 10 placeholder loads as a memory holding nothing, checkpointed
    to the episode it was saved in.

    Args:
        value: The parsed world-memory document.
        description: What is being read, used in error messages.
        through_episode: Episode the verified manifest records.
        through_tick: Tick the verified manifest records.

    Returns:
        A fully detached, immutable memory.

    Raises:
        TypeError: If the document, ``facts``, or a fact is of the wrong type.
        ValueError: If keys are missing or extra, the schema version is
            unsupported, or any fact fails validation.
    """
    document = require_document(value, description)
    require_exact_keys(document, _KEYS, description)
    require_schema_version(document, description)
    require_exact_int(through_episode, "through_episode")
    require_exact_int(through_tick, "through_tick")

    facts = document["facts"]
    if type(facts) is not list:
        raise TypeError(f"{description} facts must be a list, got {type(facts).__name__}")

    return WorldMemory(
        [
            MemoryFact.from_document(entry, f"{description} facts[{index}]")
            for index, entry in enumerate(facts)
        ],
        through_episode=through_episode,
        through_tick=through_tick,
    )
