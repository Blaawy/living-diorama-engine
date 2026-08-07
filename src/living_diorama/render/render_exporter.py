"""Build deterministic Render Export documents from verified persisted episodes.

The exporter is a translation layer, not a simulation participant. Its one
source of truth is :meth:`SaveManager.load_episode`, which verifies the
requested episode and its complete ancestry -- hashes, canonical bytes,
lineage, semantic reconstruction, and memory history -- before anything here
runs. A corrupted episode is not exportable merely because its JSON parses.

After loading, the verified domain objects are captured exactly once, through
the locked persistence serializers, and the export document is built from
those captured JSON documents alone. Nothing rereads live runtime objects
while assembling output, nothing draws randomness, and nothing mutates a
domain object, a save file, or the save root. The projection keeps the
authoritative world meaning and drops persistence-only continuation state:
``rng_state`` never appears in a render export.

Writing is downstream of building: the complete canonical bytes exist in
memory before any destination is created, an existing destination is refused
rather than overwritten, and the destination may never resolve into the save
root -- the authoritative episode chain must not be contaminated with derived
media artifacts.
"""

import os
from pathlib import Path
from typing import cast

from living_diorama.persistence import (
    LoadedEpisode,
    SaveManager,
    dumps_canonical,
    sha256_hex,
)
from living_diorama.persistence.serializers.event_serializer import serialize_event_log
from living_diorama.persistence.serializers.world_memory_serializer import (
    serialize_world_memory,
)
from living_diorama.persistence.serializers.world_serializer import serialize_world
from living_diorama.render.render_schema_v1 import (
    ENTITY_COUNT_KEYS,
    RENDER_EXPORT_FORMAT,
    RENDER_SCHEMA_VERSION,
    WORLD_KEYS,
    require_render_array,
    validate_render_export,
)


def _project_loaded_episode(loaded: LoadedEpisode) -> dict[str, object]:
    """Project one loaded episode after proving it still matches its manifest.

    Private by design: the public trust boundary begins at
    :meth:`SaveManager.load_episode`, never at a caller-supplied
    ``LoadedEpisode``. Even a genuinely loaded episode holds a mutable
    ``World``, so this helper does not blindly combine a load-time manifest
    with whatever the world says now. The world, event log, and memory are
    each captured exactly once through the locked persistence serializers,
    and the captured world document must hash to exactly the manifest's
    verified ``state_hash`` -- computed with the same canonical encoder and
    digest persistence uses -- before anything is projected. A world that
    changed after verification therefore cannot ride out under its original
    provenance. The captured documents are also cross-checked against the
    manifest's episode, tick, entity counts, and event count, and the
    memory's checkpoint against the manifest's moment.

    The world section carries the five entity arrays exactly as persistence
    serializes them, in their canonical identifier order. The persistence-only
    top-level fields -- ``episode``, ``tick``, ``schema_version``, and
    ``rng_state`` -- are deliberately not projected: episode and tick live
    under ``source``, and continuation internals are not visual state.

    Args:
        loaded: An episode as returned by :meth:`SaveManager.load_episode`.

    Returns:
        The validated Render Export V1 document.

    Raises:
        TypeError: If ``loaded`` is not exactly a ``LoadedEpisode``, or a
            captured value is of the wrong type.
        ValueError: If the captured state disagrees with the manifest's
            verified provenance, or a captured value breaks the render
            export contract.
    """
    if type(loaded) is not LoadedEpisode:
        raise TypeError(f"loaded must be a LoadedEpisode, got {type(loaded).__name__}")

    manifest = loaded.manifest
    world_document = serialize_world(loaded.world)
    event_document = serialize_event_log(loaded.event_log, manifest.episode, manifest.tick)
    memory_document = serialize_world_memory(loaded.world_memory)
    through_episode = loaded.world_memory.through_episode
    through_tick = loaded.world_memory.through_tick

    # The provenance gate: the export is built from this captured document,
    # so this captured document -- not any earlier state -- must be exactly
    # what the verified manifest describes.
    captured_state_hash = sha256_hex(dumps_canonical(world_document, "captured world state"))
    if captured_state_hash != manifest.state_hash:
        raise ValueError(
            f"the captured world serializes to state hash {captured_state_hash} but the "
            f"manifest records {manifest.state_hash}; the loaded world no longer agrees "
            "with its persisted provenance and cannot be exported"
        )
    if world_document["episode"] != manifest.episode:
        raise ValueError(
            f"the captured world records episode {world_document['episode']!r} but the "
            f"manifest records {manifest.episode}"
        )
    if world_document["tick"] != manifest.tick:
        raise ValueError(
            f"the captured world records tick {world_document['tick']!r} but the "
            f"manifest records {manifest.tick}"
        )
    for kind in ENTITY_COUNT_KEYS:
        entities = require_render_array(world_document[kind], f"captured world {kind}")
        if len(entities) != manifest.entity_counts[kind]:
            raise ValueError(
                f"the captured world holds {len(entities)} {kind} but the manifest "
                f"records {manifest.entity_counts[kind]}"
            )
    captured_events = require_render_array(event_document["events"], "captured events")
    if len(captured_events) != manifest.event_count:
        raise ValueError(
            f"the captured event log holds {len(captured_events)} events but the "
            f"manifest records {manifest.event_count}"
        )
    if through_episode != manifest.episode or through_tick != manifest.tick:
        raise ValueError(
            f"the loaded memory is checkpointed through episode {through_episode} tick "
            f"{through_tick} but the manifest records episode {manifest.episode} tick "
            f"{manifest.tick}"
        )

    document: dict[str, object] = {
        "format": RENDER_EXPORT_FORMAT,
        "schema_version": RENDER_SCHEMA_VERSION,
        "source": {
            "engine_version": manifest.engine_version,
            "entity_counts": dict(manifest.entity_counts),
            "episode": manifest.episode,
            "event_count": manifest.event_count,
            "parent_state_hash": manifest.parent_state_hash,
            "state_hash": manifest.state_hash,
            "tick": manifest.tick,
        },
        "world": {key: world_document[key] for key in sorted(WORLD_KEYS)},
        "events": event_document["events"],
        "memory": {
            "facts": memory_document["facts"],
            "through_episode": through_episode,
            "through_tick": through_tick,
        },
    }
    return validate_render_export(document)


def _require_non_blank_path(value: str | Path, description: str) -> None:
    """Refuse an empty or whitespace-only path in either spelling.

    A blank ``str`` would be normalized by ``Path`` into the current
    directory, and a whitespace-only ``Path`` names nothing an operator
    intended; both are refused rather than repaired. (``Path("")`` itself is
    normalized to ``"."`` by ``pathlib`` at construction, before any API can
    see it -- the empty-string hazard is a string-input hazard.)

    Raises:
        ValueError: If the path text is empty or whitespace-only.
    """
    text = value if type(value) is str else str(value)
    if not text.strip():
        raise ValueError(f"{description} must not be empty or whitespace")


def build_render_export_document(save_root: str | Path, episode: int) -> dict[str, object]:
    """Load one verified episode and return its Render Export V1 document.

    Every public render export path begins here: the verified persisted
    episode is the only source of truth, loading goes through the real
    :class:`SaveManager` -- which verifies the complete ancestry -- and the
    projection additionally proves the captured state still hashes to the
    manifest's verified provenance. There is no public door that accepts a
    caller-supplied loaded episode.

    Args:
        save_root: Directory holding the episode chain.
        episode: The episode number to export.

    Returns:
        The validated Render Export V1 document.

    Raises:
        TypeError: If an argument is of the wrong type.
        ValueError: If ``save_root`` is blank, or anything in the chain fails
            verification.
        FileNotFoundError: If the episode, or any ancestor, is absent.
    """
    _require_non_blank_path(save_root, "save_root")
    return _project_loaded_episode(SaveManager(save_root).load_episode(episode))


def build_render_export_bytes(save_root: str | Path, episode: int) -> bytes:
    """Load one verified episode and return its canonical Render Export bytes.

    The returned bytes are the one canonical encoding of the export document
    -- sorted keys, compact separators, UTF-8, one trailing newline -- so the
    same source episode always produces the same bytes.

    Args:
        save_root: Directory holding the episode chain.
        episode: The episode number to export.

    Returns:
        The canonical Render Export V1 bytes.

    Raises:
        TypeError: If an argument is of the wrong type.
        ValueError: If ``save_root`` is blank, or anything in the chain fails
            verification.
        FileNotFoundError: If the episode, or any ancestor, is absent.
    """
    return dumps_canonical(build_render_export_document(save_root, episode), "render export")


def _require_output_destination(save_root: str | Path, output_path: str | Path) -> Path:
    """Validate where an export may be written, and return the destination.

    The destination must be a fresh location outside the save root. Resolution
    follows symlinks, so an alias that points back into the save root is
    refused the same as a direct path -- the immutable episode chain may never
    be contaminated with derived artifacts.

    Raises:
        TypeError: If ``output_path`` is not a ``str`` or ``Path``.
        ValueError: If the path is blank, or resolves to or into the save
            root.
        FileExistsError: If the destination already exists in any form.
        FileNotFoundError: If the destination's parent directory is absent.
    """
    if type(output_path) is str:
        _require_non_blank_path(output_path, "output_path")
        destination = Path(output_path)
    elif issubclass(type(output_path), Path):
        _require_non_blank_path(output_path, "output_path")
        # The true-type check has already proven this; the cast only bridges
        # the narrowing mypy cannot perform on ``issubclass(type(...), ...)``.
        destination = cast(Path, output_path)
    else:
        raise TypeError(f"output_path must be a str or Path, got {type(output_path).__name__}")

    root = Path(save_root).resolve()
    resolved = destination.resolve()
    if resolved == root or root in resolved.parents:
        raise ValueError(
            f"render export destination {destination} resolves inside the save root "
            f"{root}; the episode chain is immutable and holds no derived artifacts"
        )

    # ``lexists`` rather than ``exists``: a broken symlink is an existing
    # directory entry, and writing through it would land somewhere this
    # validation never saw.
    if os.path.lexists(destination):
        raise FileExistsError(
            f"render export destination {destination} already exists; exports are never overwritten"
        )
    if not destination.parent.exists():
        raise FileNotFoundError(
            f"render export destination directory {destination.parent} does not exist"
        )
    return destination


def write_render_export(save_root: str | Path, episode: int, output_path: str | Path) -> bytes:
    """Export one verified episode to a file and return the written bytes.

    The complete canonical bytes are built -- source verified, projection
    validated, encoding finished -- before the destination is even checked,
    so no output file can exist for an export that failed. The destination is
    then validated, written exclusively (never over anything that exists),
    read back, and required to hold exactly the intended bytes. A failure
    after the file was created removes the partial export before the error
    propagates.

    Render exports are reproducible derived artifacts, so this write is a
    plain exclusive create rather than a staged atomic publication -- but it
    never overwrites, and it never touches the save tree.

    Args:
        save_root: Directory holding the episode chain.
        episode: The episode number to export.
        output_path: Where to write the export. Must not exist, and must not
            resolve inside the save root.

    Returns:
        The exact bytes written and read back.

    Raises:
        TypeError: If an argument is of the wrong type.
        ValueError: If verification fails, a path is blank, the destination
            resolves into the save root, or the read-back disagrees.
        FileExistsError: If the destination already exists.
        FileNotFoundError: If the episode chain or the destination's parent
            directory is absent.
        OSError: If the filesystem refuses the write.
    """
    data = build_render_export_bytes(save_root, episode)
    destination = _require_output_destination(save_root, output_path)

    created = False
    try:
        # "xb" closes the race the earlier existence check cannot: if a rival
        # destination appeared meanwhile, creation fails rather than replaces.
        with open(destination, "xb") as handle:
            created = True
            handle.write(data)
    except FileExistsError as error:
        raise FileExistsError(
            f"render export destination {destination} already exists; exports are never overwritten"
        ) from error
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise

    written = destination.read_bytes()
    if written != data:
        destination.unlink(missing_ok=True)
        raise ValueError(
            f"render export at {destination} read back differently than written; "
            "the partial export has been removed"
        )
    return written
