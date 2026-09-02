r"""Build an Episode Audio Track Plan from an audited voice execution and a presentation plan.

    python -m living_diorama.cli.build_audio_track_plan \
        --voice-dir voice/episode_0000_to_0001 \
        --presentation episode_presentation_plan_v1.json \
        --realization episode_language_realization_plan_v1.json \
        --delivery episode_narration_delivery_plan_v1.json \
        --narration episode_narration_plan_v1.json \
        --shots shot_direction_plan_v1.json \
        --story episode_story_plan_v1.json \
        --export render_export_ep1.json \
        --output episode_audio_track_plan_v1.json

There is no flag accepting a detached, unaudited manifest file. ``--voice-dir``
names a Phase 29 execution directory, and the very first thing this command
does with it is run the reused Phase 29 directory audit -- the artifact-truth
precondition -- before a single document is parsed. Only once that audit
returns no problems are the voice manifest and voice plan read from inside
that same directory.

The seven remaining inputs must all be canonical bytes, because the plan
binds the digest of two of them and those claims have to be true. Five exist
only so the one locked upstream source-verification gate this command runs
can prove what the bound documents consume.

There is no audio parsing here, and no model dependency. An audio track plan
is placement arithmetic over an already-measured, already-audited execution,
settled without ever opening a WAV file.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from living_diorama.audio_track import (
    build_episode_audio_track_plan_bytes,
    validate_episode_audio_track_plan,
    validate_episode_audio_track_plan_against_sources,
)
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
            f"{description} at {path} is not canonical bytes. The audio track plan binds the "
            "digest of the documents it reads, so each file must be exactly what its writer "
            "emitted -- sorted keys, no spacing, one trailing newline. Rebuild it rather than "
            "reformatting it."
        )
    return document


def build(
    voice_dir: Path,
    presentation_path: Path,
    realization_path: Path,
    delivery_path: Path,
    narration_path: Path,
    shots_path: Path,
    story_path: Path,
    export_path: Path,
    output_path: Path,
    *,
    presentation_profile: str | None = None,
) -> int:
    """Write the audio track plan for the given sources and return its byte length.

    Args:
        voice_dir: The audited Phase 29 execution directory whose manifest and
            voice plan the plan places.
        presentation_path: The Episode Presentation Plan the plan speaks to.
        realization_path: The Episode Language Realization Plan the plan speaks.
        delivery_path: The Episode Narration Delivery Plan the presentation
            plan images. Verification-only.
        narration_path: The Episode Narration Plan the presentation presents.
            Verification-only.
        shots_path: The Shot Direction Plan the delivery plan was cut against.
            Verification-only.
        story_path: The Episode Story Plan the realization plan was proven
            against. Verification-only.
        export_path: The render export the story and realization were derived
            from. Verification-only.
        output_path: Where to write the audio track plan; refused if it already
            exists.
        presentation_profile: The presentation profile the reused Phase 28
            gate verifies the presentation plan under. ``None`` (the default)
            preserves today's exact behavior: a presentation plan carrying
            ``motion_windows`` is verified as V2, any other plan as V1. Pass
            ``"v1"``, ``"v2"`` or ``"v3"`` to pin the profile explicitly --
            ``"v3"`` is required for the frozen, content-sized V3
            presentation plan, which carries no ``motion_windows`` and would
            otherwise be re-derived as V1 and refused.
    """
    if output_path.exists():
        raise FileExistsError(
            f"audio track plan destination {output_path} already exists; plans are never "
            "overwritten"
        )

    # The artifact-truth precondition: this is the only invocation of the
    # audit, and it happens before any document is parsed at all.
    problems = audit_voice_directory(voice_dir)
    if problems:
        raise ValueError(
            f"the voice directory {voice_dir} is not a truthful, complete execution: {problems}"
        )

    voice_manifest = _read_canonical(voice_dir / VOICE_MANIFEST_FILENAME, "voice manifest")
    voice_plan = _read_canonical(voice_dir / VOICE_PLAN_FILENAME, "voice plan")
    presentation = _read_canonical(presentation_path, "presentation plan")
    realization = _read_canonical(realization_path, "language realization plan")
    delivery = _read_canonical(delivery_path, "narration delivery plan")
    narration = _read_canonical(narration_path, "episode narration plan")
    shots = _read_canonical(shots_path, "shot direction plan")
    story = _read_canonical(story_path, "episode story plan")
    export = _read_canonical(export_path, "render export")

    payload = build_episode_audio_track_plan_bytes(voice_manifest, presentation)
    document = loads_canonical(payload, "audio track plan")
    validate_episode_audio_track_plan_against_sources(
        document,
        voice_manifest,
        presentation,
        voice_plan,
        realization,
        delivery,
        narration,
        shots,
        story,
        export,
        presentation_profile=presentation_profile,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return len(payload)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, write the plan, and report what was placed."""
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.cli.build_audio_track_plan",
        description=(
            "Derive an Episode Audio Track Plan from an audited voice execution directory and "
            "a presentation plan, verified against the voice plan, realization plan, delivery "
            "plan, narration plan, shot plan, story plan and render export."
        ),
    )
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
    parser.add_argument("--output", required=True, help="where to write the audio track plan")
    parser.add_argument(
        "--presentation-profile",
        choices=("v1", "v2", "v3", "v4"),
        default=None,
        help=(
            "the presentation profile the reused Phase 28 gate verifies the presentation "
            "plan under; v1 reproduces today's bytes exactly, v2 verifies the additive "
            "motion-window plan, v3 verifies the frozen, content-sized plan with no motion "
            "windows; when the flag is omitted today's exact behavior is preserved"
        ),
    )
    namespace = parser.parse_args(argv)

    try:
        written = build(
            Path(namespace.voice_dir),
            Path(namespace.presentation),
            Path(namespace.realization),
            Path(namespace.delivery),
            Path(namespace.narration),
            Path(namespace.shots),
            Path(namespace.story),
            Path(namespace.export),
            Path(namespace.output),
            presentation_profile=namespace.presentation_profile,
        )
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    # Reporting only: re-read what was actually written, validate it
    # standalone, and derive the summary from that -- this creates no new
    # planning truth.
    written_document = _read_canonical(Path(namespace.output), "audio track plan")
    document = cast(dict[str, Any], validate_episode_audio_track_plan(written_document))
    counts = {
        "bytes": written,
        "episode": document["source"]["episode"],
        "mode": document["source"]["mode"],
        "speech_total": document["accounting"]["speech_total"],
        "speech_samples_total": document["accounting"]["speech_samples_total"],
        "silence_samples_total": document["accounting"]["silence_samples_total"],
        "audio_samples_total": document["clock"]["audio_samples_total"],
    }
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
