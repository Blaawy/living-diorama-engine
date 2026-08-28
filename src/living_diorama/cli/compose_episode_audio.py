r"""Compose an Episode Audio Composition from a sealed placement and an audited execution.

    python -m living_diorama.cli.compose_episode_audio \
        --audio-track episode_audio_track_plan_v1.json \
        --voice-dir voice/episode_0000_to_0001 \
        --presentation episode_presentation_plan_v1.json \
        --realization episode_language_realization_plan_v1.json \
        --delivery episode_narration_delivery_plan_v1.json \
        --narration episode_narration_plan_v1.json \
        --shots shot_direction_plan_v1.json \
        --story episode_story_plan_v1.json \
        --export render_export_ep1.json \
        --output-root audio_tracks/

The command is a thin shell around ``living_diorama.audio_composition``: it
holds no filesystem-safety decision of its own beyond the very first one --
proving ``--output-root`` is not a symlink or a Windows junction, before any
other operation touches it, including the existence preflight below.

No filesystem query that follows ``--output-root`` occurs before that check.
An indirect or dangling output root refuses here, at command entry, even
when a valid, complete composition sits behind it: no-op authority exists
only under a direct output root.

The reused Phase 29 directory audit is the first thing this command does
with ``--voice-dir``, before any offered document is parsed. The whole
Phase 30 source gate then runs before a single byte is composed, so a
composition can never exist without every one of its bindings -- and both
upstream source-verification gates -- having been proven.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from living_diorama.audio_composition import (
    publish_episode_audio,
    validate_episode_audio_composition_manifest,
)
from living_diorama.audio_composition.audio_composition_binding import require_voice_manifest_bytes
from living_diorama.audio_composition.audio_composition_spec import (
    AUDIO_COMPOSITION_MANIFEST_FILENAME,
)
from living_diorama.audio_composition.audio_composition_staging import (
    CompositionDirectoryRefused,
    _require_direct_parent,
)
from living_diorama.audio_track import validate_episode_audio_track_plan_against_sources
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.voice_execution import audit_voice_directory
from living_diorama.voice_execution.voice_execution_spec import (
    VOICE_MANIFEST_FILENAME,
    VOICE_PLAN_FILENAME,
)


def _read_canonical(path: Path, description: str) -> object:
    """Load a document, refusing any file that is not canonical bytes.

    Raises:
        FileNotFoundError: If the file is absent.
        TypeError: If the decoded document contains a value a canonical
            document may not carry.
        ValueError: If the bytes are not valid UTF-8, are not valid JSON,
            repeat an object key, contain a non-standard JSON constant or a
            non-finite number, or are not the canonical encoding of the
            document they contain.
    """
    if not path.is_file():
        raise FileNotFoundError(f"{description} not found: {path}")
    raw = path.read_bytes()
    document = loads_canonical(raw, description)
    if raw != dumps_canonical(document, description):
        raise ValueError(
            f"{description} at {path} is not canonical bytes. The audio composition binds the "
            "digest of the documents it reads, so each file must be exactly what its writer "
            "emitted -- sorted keys, no spacing, one trailing newline. Rebuild it rather than "
            "reformatting it."
        )
    return document


def compose(
    audio_track_path: Path,
    voice_dir: Path,
    presentation_path: Path,
    realization_path: Path,
    delivery_path: Path,
    narration_path: Path,
    shots_path: Path,
    story_path: Path,
    export_path: Path,
    output_root: Path,
) -> Path:
    """Compose one episode's audio track and return its published composition directory."""
    # 0. THE FIRST STATEMENT: no filesystem query below output_root precedes this.
    _require_direct_parent(output_root)

    if output_root.exists() and not output_root.is_dir():
        raise OSError(f"{output_root} exists and is not a directory")

    # The artifact-truth precondition: this is the only invocation of the
    # audit, and it happens before any offered document is parsed at all.
    problems = audit_voice_directory(voice_dir)
    if problems:
        raise ValueError(
            f"the voice directory {voice_dir} is not a truthful, complete execution: {problems}"
        )

    # ---- THE AUDIO TRACK PLAN IS OBSERVED EXACTLY ONCE ----
    # The same captured bytes govern parse, canonical-form, the whole Phase 30
    # gate, the copied plan witness, its SHA-256 identity and the
    # existing-final no-op -- never a second, independent read of this path's
    # content, so no external mutation between two reads can ever divide what
    # the gate proves from what the digest authorizes.
    if not audio_track_path.is_file():
        raise FileNotFoundError(f"audio track plan not found: {audio_track_path}")
    audio_track_plan_bytes = audio_track_path.read_bytes()
    audio_track_plan = loads_canonical(audio_track_plan_bytes, "audio track plan")
    if audio_track_plan_bytes != dumps_canonical(audio_track_plan, "audio track plan"):
        raise ValueError(
            f"audio track plan at {audio_track_path} is not canonical bytes. The audio "
            "composition binds the digest of the documents it reads, so each file must be "
            "exactly what its writer emitted -- sorted keys, no spacing, one trailing newline. "
            "Rebuild it rather than reformatting it."
        )

    voice_manifest_bytes = (voice_dir / VOICE_MANIFEST_FILENAME).read_bytes()
    voice_manifest = cast(
        dict[str, Any], require_voice_manifest_bytes(audio_track_plan, voice_manifest_bytes)
    )
    voice_plan = _read_canonical(voice_dir / VOICE_PLAN_FILENAME, "voice plan")

    presentation = _read_canonical(presentation_path, "presentation plan")
    realization = _read_canonical(realization_path, "language realization plan")
    delivery = _read_canonical(delivery_path, "narration delivery plan")
    narration = _read_canonical(narration_path, "episode narration plan")
    shots = _read_canonical(shots_path, "shot direction plan")
    story = _read_canonical(story_path, "episode story plan")
    export = _read_canonical(export_path, "render export")

    validate_episode_audio_track_plan_against_sources(
        audio_track_plan,
        voice_manifest,
        presentation,
        voice_plan,
        realization,
        delivery,
        narration,
        shots,
        story,
        export,
    )

    return publish_episode_audio(
        audio_track_plan=cast(dict[str, Any], audio_track_plan),
        audio_track_plan_bytes=audio_track_plan_bytes,
        voice_manifest=voice_manifest,
        voice_manifest_bytes=voice_manifest_bytes,
        voice_dir=voice_dir,
        output_root=output_root,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, compose the track, and report what was placed."""
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.cli.compose_episode_audio",
        description=(
            "Compose an Episode Audio Composition from a sealed audio track plan and an "
            "audited voice execution directory, verified against the whole Phase 30 source "
            "gate."
        ),
    )
    parser.add_argument("--audio-track", required=True, help="the Episode Audio Track Plan")
    parser.add_argument(
        "--voice-dir", required=True, help="the audited directory one voice execution owns"
    )
    parser.add_argument("--presentation", required=True, help="the Episode Presentation Plan")
    parser.add_argument(
        "--realization", required=True, help="the Episode Language Realization Plan"
    )
    parser.add_argument("--delivery", required=True, help="the Episode Narration Delivery Plan")
    parser.add_argument("--narration", required=True, help="the Episode Narration Plan")
    parser.add_argument("--shots", required=True, help="the Shot Direction Plan")
    parser.add_argument("--story", required=True, help="the Episode Story Plan")
    parser.add_argument(
        "--export",
        required=True,
        help="the render export the story and realization were derived from",
    )
    parser.add_argument(
        "--output-root", required=True, help="where to publish the composed directory"
    )
    namespace = parser.parse_args(argv)

    try:
        final_dir = compose(
            Path(namespace.audio_track),
            Path(namespace.voice_dir),
            Path(namespace.presentation),
            Path(namespace.realization),
            Path(namespace.delivery),
            Path(namespace.narration),
            Path(namespace.shots),
            Path(namespace.story),
            Path(namespace.export),
            Path(namespace.output_root),
        )
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except CompositionDirectoryRefused as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    # Reporting only: re-read what was actually published, validate it
    # standalone, and derive the summary from that -- this creates no new
    # authority and performs no composition.
    manifest = validate_episode_audio_composition_manifest(
        cast(
            dict[str, Any],
            _read_canonical(
                final_dir / AUDIO_COMPOSITION_MANIFEST_FILENAME, "audio composition manifest"
            ),
        )
    )
    source = cast(dict[str, Any], manifest["source"])
    audio = cast(dict[str, Any], manifest["audio"])
    completeness = cast(dict[str, Any], manifest["completeness"])
    counts = {
        "audio_samples_total": audio["audio_samples"],
        "composition_dir": str(final_dir),
        "episode": source["episode"],
        "mode": source["mode"],
        "silence_samples_total": completeness["silence_samples_total"],
        "speech_spans_total": completeness["speech_spans_composed"],
        "track_bytes": audio["bytes"],
        "track_sha256": audio["sha256"],
    }
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
