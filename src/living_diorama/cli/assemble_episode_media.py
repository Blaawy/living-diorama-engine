r"""Assemble an Episode Media Assembly from a sealed presentation and an audited composition.

    python -m living_diorama.cli.assemble_episode_media \
        --render-dir renders/episode_0000_to_0001 \
        --composition-dir audio_tracks/episode_0000_to_0001 \
        --presentation episode_presentation_plan_v1.json \
        --delivery episode_narration_delivery_plan_v1.json \
        --shots shot_direction_plan_v1.json \
        --narration episode_narration_plan_v1.json \
        --realization episode_language_realization_plan_v1.json \
        --story episode_story_plan_v1.json \
        --export render_export_ep1.json \
        --output-root media_assembly/

The command is a thin shell around ``living_diorama.media_assembly``: it holds no
filesystem-safety decision of its own beyond the very first one -- proving
``--output-root`` is not a symlink or a Windows junction, before any other operation
touches it, including the existence preflight below.

No filesystem query that follows ``--output-root`` occurs before that check. An indirect
or dangling output root refuses here, at command entry, even when a valid, complete
assembly sits behind it: no-op authority exists only under a direct output root.

This command calls no upstream directory audit: neither Phase 23's nor Phase 31's. Each
upstream phase owns the correctness of its own artifacts; this phase consumes each one's
published, digest-bound interface. The whole locked Phase 27 source-verification gate runs
before a single byte is copied, so an assembly can never exist without every one of its
bindings -- and that gate -- having been proven.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from living_diorama.audio_composition.audio_composition_spec import (
    AUDIO_COMPOSITION_MANIFEST_FILENAME,
    AUDIO_DIRECTORY,
    EPISODE_AUDIO_FILENAME,
)
from living_diorama.media_assembly import (
    MediaAssemblyDirectoryRefused,
    publish_episode_media_assembly,
    validate_episode_media_assembly_manifest,
)
from living_diorama.media_assembly.media_assembly_spec import MEDIA_ASSEMBLY_MANIFEST_FILENAME
from living_diorama.media_assembly.media_assembly_staging import _require_direct_parent
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.presentation.presentation_cross_check import (
    validate_episode_presentation_plan_against_sources,
)
from living_diorama.render_execution.render_execution_spec import RENDER_MANIFEST_FILENAME


def _read_canonical_with_bytes(path: Path, description: str) -> tuple[object, bytes]:
    """Load a document and its exact bytes from a single read, refusing non-canonical bytes.

    The single authoritative read: every caller that needs both the parsed document and its
    raw bytes gets both from this one call, never from a second, independent ``read_bytes()``
    -- reopening the same path a second time is exactly the TOCTOU seam the single-capture
    law exists to close.

    Raises:
        FileNotFoundError: If the file is absent.
        TypeError: If the decoded document contains a value a canonical document may not
            carry.
        ValueError: If the bytes are not valid UTF-8, are not valid JSON, repeat an object
            key, contain a non-standard JSON constant or a non-finite number, or are not the
            canonical encoding of the document they contain.
    """
    if not path.is_file():
        raise FileNotFoundError(f"{description} not found: {path}")
    raw = path.read_bytes()
    document = loads_canonical(raw, description)
    if raw != dumps_canonical(document, description):
        raise ValueError(
            f"{description} at {path} is not canonical bytes. The media assembly binds the "
            "digest of the documents it reads, so each file must be exactly what its writer "
            "emitted -- sorted keys, no spacing, one trailing newline. Rebuild it rather than "
            "reformatting it."
        )
    return document, raw


def _read_canonical(path: Path, description: str) -> object:
    """Load a document, refusing any file that is not canonical bytes.

    For the four verification-only documents (narration, realization, story, export): the
    P27 gate consumes the parsed document only, so no second, byte-capturing read is ever
    needed for them.

    Raises:
        FileNotFoundError: If the file is absent.
        TypeError: If the decoded document contains a value a canonical document may not
            carry.
        ValueError: If the bytes are not valid UTF-8, are not valid JSON, repeat an object
            key, contain a non-standard JSON constant or a non-finite number, or are not the
            canonical encoding of the document they contain.
    """
    document, _raw = _read_canonical_with_bytes(path, description)
    return document


def assemble(
    render_dir: Path,
    composition_dir: Path,
    presentation_path: Path,
    delivery_path: Path,
    shots_path: Path,
    narration_path: Path,
    realization_path: Path,
    story_path: Path,
    export_path: Path,
    output_root: Path,
) -> Path:
    """Assemble one episode's media and return its published assembly directory."""
    # 0. THE FIRST STATEMENT: no filesystem query below output_root precedes this.
    _require_direct_parent(output_root)

    if output_root.exists() and not output_root.is_dir():
        raise OSError(f"{output_root} exists and is not a directory")

    # ---- THE RENDER MANIFEST IS OBSERVED EXACTLY ONCE ----
    render_manifest_path = render_dir / RENDER_MANIFEST_FILENAME
    render_manifest, render_manifest_bytes = _read_canonical_with_bytes(
        render_manifest_path, "render manifest"
    )

    # ---- THE PRESENTATION PLAN IS OBSERVED EXACTLY ONCE ----
    presentation_plan, presentation_plan_bytes = _read_canonical_with_bytes(
        presentation_path, "presentation plan"
    )

    # ---- THE COMPOSITION MANIFEST IS OBSERVED EXACTLY ONCE ----
    composition_manifest_path = composition_dir / AUDIO_COMPOSITION_MANIFEST_FILENAME
    audio_composition_manifest, audio_composition_manifest_bytes = _read_canonical_with_bytes(
        composition_manifest_path, "audio composition manifest"
    )

    # ---- THE TWO WITNESS DOCUMENTS, EACH OBSERVED EXACTLY ONCE ----
    delivery_plan, delivery_plan_bytes = _read_canonical_with_bytes(
        delivery_path, "narration delivery plan"
    )

    shot_plan_document, shot_plan_bytes = _read_canonical_with_bytes(
        shots_path, "shot direction plan"
    )

    # ---- THE FOUR VERIFICATION-ONLY DOCUMENTS: P27 GATE ARGUMENTS ONLY ----
    narration = _read_canonical(narration_path, "episode narration plan")
    realization = _read_canonical(realization_path, "episode language realization plan")
    story = _read_canonical(story_path, "episode story plan")
    export = _read_canonical(export_path, "render export")

    # ---- THE LOCKED PHASE 27 SOURCE GATE, IN FULL, UNWEAKENED ----
    validate_episode_presentation_plan_against_sources(
        presentation_plan,
        delivery_plan,
        narration,
        shot_plan_document,
        realization,
        story,
        export,
    )

    # ---- THE CARRIED EPISODE AUDIO IS OBSERVED EXACTLY ONCE ----
    wav_path = composition_dir / AUDIO_DIRECTORY / EPISODE_AUDIO_FILENAME
    if not wav_path.is_file():
        raise FileNotFoundError(f"episode audio not found: {wav_path}")
    wav_bytes = wav_path.read_bytes()

    return publish_episode_media_assembly(
        render_manifest=cast(dict[str, Any], render_manifest),
        render_manifest_bytes=render_manifest_bytes,
        presentation_plan=cast(dict[str, Any], presentation_plan),
        presentation_plan_bytes=presentation_plan_bytes,
        audio_composition_manifest=cast(dict[str, Any], audio_composition_manifest),
        audio_composition_manifest_bytes=audio_composition_manifest_bytes,
        delivery_plan=cast(dict[str, Any], delivery_plan),
        delivery_plan_bytes=delivery_plan_bytes,
        shot_plan_bytes=shot_plan_bytes,
        wav_bytes=wav_bytes,
        render_dir=render_dir,
        output_root=output_root,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, assemble the episode media, and report what was published."""
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.cli.assemble_episode_media",
        description=(
            "Assemble an Episode Media Assembly from a sealed presentation plan and an "
            "audited audio composition, verified against the whole Phase 27 source gate."
        ),
    )
    parser.add_argument("--render-dir", required=True, help="the Phase 23 render directory")
    parser.add_argument(
        "--composition-dir", required=True, help="the Phase 31 audio composition directory"
    )
    parser.add_argument("--presentation", required=True, help="the Episode Presentation Plan")
    parser.add_argument("--delivery", required=True, help="the Episode Narration Delivery Plan")
    parser.add_argument("--shots", required=True, help="the Shot Direction Plan")
    parser.add_argument("--narration", required=True, help="the Episode Narration Plan")
    parser.add_argument(
        "--realization", required=True, help="the Episode Language Realization Plan"
    )
    parser.add_argument("--story", required=True, help="the Episode Story Plan")
    parser.add_argument(
        "--export",
        required=True,
        help="the render export the story and realization were derived from",
    )
    parser.add_argument(
        "--output-root", required=True, help="where to publish the assembly directory"
    )
    namespace = parser.parse_args(argv)

    try:
        final_dir = assemble(
            Path(namespace.render_dir),
            Path(namespace.composition_dir),
            Path(namespace.presentation),
            Path(namespace.delivery),
            Path(namespace.shots),
            Path(namespace.narration),
            Path(namespace.realization),
            Path(namespace.story),
            Path(namespace.export),
            Path(namespace.output_root),
        )
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except MediaAssemblyDirectoryRefused as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    # Reporting only: re-read what was actually published, validate it standalone, and
    # derive the summary from that -- this creates no new authority and assembles nothing.
    manifest = validate_episode_media_assembly_manifest(
        cast(
            dict[str, Any],
            _read_canonical(
                final_dir / MEDIA_ASSEMBLY_MANIFEST_FILENAME, "episode media assembly manifest"
            ),
        )
    )
    source = cast(dict[str, Any], manifest["source"])
    clock = cast(dict[str, Any], manifest["clock"])
    audio = cast(dict[str, Any], manifest["audio"])
    completeness = cast(dict[str, Any], manifest["completeness"])
    summary = {
        "assembly_dir": str(final_dir),
        "audio_samples_total": clock["audio_samples_total"],
        "episode": source["episode"],
        "fps": clock["fps"],
        "mode": source["mode"],
        "presentation_frames_total": clock["presentation_frames_total"],
        "shot_plan_sha256": source["shot_plan_sha256"],
        "track_sha256": audio["sha256"],
        "unique_semantic_frames_used": completeness["unique_semantic_frames_used"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
