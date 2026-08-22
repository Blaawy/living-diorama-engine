"""Proving that two render exports are genuinely consecutive canonical history.

A story plan that spans a transition makes a claim about *this* episode
following *that* one. The claim is only worth as much as the check behind it, so
lineage is proven from authoritative provenance -- episode numbers, state
hashes, and the memory checkpoint -- and never from filenames or argument order.

Mismatched exports are refused, never repaired. Reordering a pair to make it fit
would produce a plan that describes a transition the world never took.
"""

from typing import Final, cast

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.world_schema_v1 import require_identifier
from living_diorama.render.render_schema_v1 import validate_render_export
from living_diorama.story.story_schema_v1 import JsonValue

WORLD_IDENTITY_ARRAYS: Final = ("boundaries", "districts")
"""Entity arrays whose identifier set must be identical across a transition.

Districts and boundaries are the world's fixed geography: the simulation moves
population and resources between them and raises walls on them, but it does not
create or destroy them mid-chain. Walls are deliberately excluded -- a wall
appearing is exactly the kind of history a story plan exists to notice.
"""


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def _identifier_set(export: dict[str, JsonValue], array: str, description: str) -> set[str]:
    """Return the identifier set of one world array, refusing malformed input.

    Render Export V1's envelope validator is deliberately shallow for nested
    entity documents, so the identifiers Phase 21 actually consumes are checked
    here. Building a set straight from the raw values would collapse duplicates
    silently: two exports each listing ``district_a`` twice would compare equal
    and pass continuity, having quietly agreed about a world neither describes.

    Whitespace is not stripped either. A noncanonical identifier is refused, not
    repaired, exactly as the persistence layer refuses one.

    Raises:
        TypeError: If the array, an entry, or an id is the wrong type.
        ValueError: If an id is not canonical, or repeats within the array.
    """
    world = _document(export.get("world"), f"{description} world")
    entries = world.get(array)
    if type(entries) is not list:
        raise TypeError(f"{description} world {array} must be a list")
    identifiers: list[str] = []
    for position, entry in enumerate(entries):
        record = _document(entry, f"{description} world {array}[{position}]")
        identifiers.append(
            require_identifier(record.get("id"), f"{description} world {array}[{position}] id")
        )
    if len(set(identifiers)) != len(identifiers):
        repeated = sorted({i for i in identifiers if identifiers.count(i) > 1})
        raise ValueError(
            f"{description} world {array} lists {repeated} more than once; "
            "an entity registry never holds the same identifier twice"
        )
    return set(identifiers)


def require_consecutive_exports(
    previous: object, current: object
) -> tuple[dict[str, JsonValue], dict[str, JsonValue]]:
    """Verify two render exports are genuinely consecutive, and return them.

    Both documents are validated against the Render Export V1 envelope first --
    Phase 21 reuses that contract rather than implementing a second, weaker
    opinion about what an export is.

    The lineage checks are:

    * both declare the same render schema version
    * ``current.episode == previous.episode + 1``
    * ``current.parent_state_hash == previous.state_hash``
    * the memory checkpoint does not go backwards
    * the world keeps its identity: the district and boundary identifier sets
      are unchanged

    Raises:
        TypeError: If either document has the wrong shape.
        ValueError: If either fails the render export contract, or if any
            lineage check fails.
    """
    previous_export = cast(dict[str, JsonValue], validate_render_export(previous))
    current_export = cast(dict[str, JsonValue], validate_render_export(current))

    previous_version = previous_export.get("schema_version")
    current_version = current_export.get("schema_version")
    if previous_version != current_version:
        raise ValueError(
            f"render exports declare different schema versions "
            f"({previous_version!r} then {current_version!r}); "
            "a transition is only meaningful within one format"
        )

    previous_source = _document(previous_export.get("source"), "previous export source")
    current_source = _document(current_export.get("source"), "current export source")

    previous_episode = cast(int, previous_source.get("episode"))
    current_episode = cast(int, current_source.get("episode"))
    if current_episode != previous_episode + 1:
        raise ValueError(
            f"render exports are not consecutive: episode {previous_episode} "
            f"is followed by episode {current_episode}"
        )

    parent = current_source.get("parent_state_hash")
    previous_hash = previous_source.get("state_hash")
    if parent != previous_hash:
        raise ValueError(
            f"episode {current_episode} declares parent state hash {parent!r}, "
            f"which is not episode {previous_episode}'s state hash {previous_hash!r}; "
            "these two exports are not the same line of history"
        )

    previous_memory = _document(previous_export.get("memory"), "previous export memory")
    current_memory = _document(current_export.get("memory"), "current export memory")
    previous_through = cast(int, previous_memory.get("through_episode"))
    current_through = cast(int, current_memory.get("through_episode"))
    if current_through < previous_through:
        raise ValueError(
            f"memory checkpoint goes backwards: through episode {previous_through} "
            f"then through episode {current_through}"
        )

    for array in WORLD_IDENTITY_ARRAYS:
        before = _identifier_set(previous_export, array, "previous export")
        after = _identifier_set(current_export, array, "current export")
        if before != after:
            added = sorted(after - before)
            removed = sorted(before - after)
            raise ValueError(
                f"world identity changed across the transition: {array} added "
                f"{added} and removed {removed}; these exports do not describe "
                "the same world"
            )

    return previous_export, current_export


def require_memory_progression(
    previous_facts: list[JsonValue], current_facts: list[JsonValue]
) -> list[JsonValue]:
    """Return the facts new in ``current_facts``, proving memory only grew.

    Durable memory is cumulative and append-only: the current episode's fact
    list must begin with the previous episode's list, byte for byte under the
    canonical encoder. A fact that vanished or was edited means the two
    documents are not consecutive states of one world, and is refused rather
    than reconciled.

    Raises:
        ValueError: If memory shrank, if a historical fact changed, or if a
            fact identifier repeats.
    """
    if len(current_facts) < len(previous_facts):
        raise ValueError(
            f"durable memory shrank from {len(previous_facts)} facts to "
            f"{len(current_facts)}; remembered history is never removed"
        )
    for position, (before, after) in enumerate(zip(previous_facts, current_facts, strict=False)):
        if dumps_canonical(before, "previous fact") != dumps_canonical(after, "current fact"):
            raise ValueError(
                f"durable memory fact at position {position} changed between "
                "episodes; remembered history is never rewritten"
            )
    new_facts = current_facts[len(previous_facts) :]

    seen: set[str] = set()
    for position, fact in enumerate(current_facts):
        record = _document(fact, f"memory fact[{position}]")
        identifier = record.get("fact_id")
        if type(identifier) is not str:
            raise TypeError(
                f"memory fact[{position}] fact_id must be a str, got {type(identifier).__name__}"
            )
        if identifier in seen:
            raise ValueError(f"durable memory repeats fact_id {identifier!r}")
        seen.add(identifier)

    return new_facts
