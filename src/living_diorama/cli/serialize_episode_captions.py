r"""Serialize an Episode Caption Plan into its published SRT and WebVTT sidecars.

    python -m living_diorama.cli.serialize_episode_captions \
        --caption-plan episode_caption_plan_v1.json \
        --realization episode_language_realization_plan_v1.json \
        --presentation episode_presentation_plan_v1.json \
        --delivery episode_narration_delivery_plan_v1.json \
        --narration episode_narration_plan_v1.json \
        --shots shot_direction_plan_v1.json \
        --story episode_story_plan_v1.json \
        --export render_export_ep1.json \
        --output-root captions/

All eight inputs must be **canonical** bytes, exactly what their writers
emitted, because the manifest binds the caption plan's digest and restates two
more, and those claims have to be true. A file whose bytes are not their own
canonical encoding is refused rather than quietly re-serialized.

Eight inputs, not one, because a caption serialization must never exist without
its plan's own bindings having been proven: before a single span is derived,
the locked Phase 32 source-verification gate runs in full and unweakened
against the realization plan, the presentation plan and the five documents that
gate itself requires. None of the seven verification documents is bound in the
serialization manifest; they exist only so the one locked gate can prove what
this serialization consumes.

The command is a thin shell around ``living_diorama.caption_serialization``:
it holds no timestamp and no sentence of its own, and every refusal comes from
the contract rather than from here. Each input is read exactly once -- parse,
gate, digest and the published plan copy all share that one observation.

There is no audio input, no tool input and no display decision of any kind: a
sidecar's timing is the plan's own frames under one pinned integer law, and
how a viewer's player renders the result belongs to no phase of this project.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from living_diorama.caption_serialization import (
    CaptionSerializationDirectoryRefused,
    publish_episode_caption_serialization,
)
from living_diorama.caption_serialization.caption_serialization_spec import (
    CAPTION_SERIALIZATION_MANIFEST_FILENAME,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical


def _read_canonical_with_bytes(path: Path, description: str) -> tuple[object, bytes]:
    """Load a document and its exact bytes, refusing any file that is not canonical.

    The single authoritative read: every caller that needs both the parsed document and its
    raw bytes gets both from this one call, never from a second, independent
    ``read_bytes()`` -- reopening the same path a second time is exactly the TOCTOU seam
    the single-capture law exists to close.

    Raises:
        FileNotFoundError: If the file is absent.
        TypeError: If the decoded document contains a value a canonical document may not
            carry.
        ValueError: If the bytes are not valid UTF-8, are not valid JSON, repeat an object
            key, contain a non-standard JSON constant or a non-finite number, or are not
            the canonical encoding of the document they contain.
    """
    if not path.is_file():
        raise FileNotFoundError(f"{description} not found: {path}")
    raw = path.read_bytes()
    document = loads_canonical(raw, description)
    if raw != dumps_canonical(document, description):
        raise ValueError(
            f"{description} at {path} is not canonical bytes. The serialization manifest "
            "binds the digest of the plan it copies, so each file must be exactly what its "
            "writer emitted -- sorted keys, no spacing, one trailing newline. Rebuild it "
            "rather than reformatting it."
        )
    return document, raw


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, publish the captions directory, and report what was serialized."""
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.cli.serialize_episode_captions",
        description=(
            "Serialize an Episode Caption Plan into published SRT and WebVTT sidecars, "
            "verified against the realization plan, presentation plan, delivery plan, "
            "narration plan, shot plan, story plan and render export."
        ),
    )
    parser.add_argument("--caption-plan", required=True, help="the Episode Caption Plan")
    parser.add_argument(
        "--realization", required=True, help="the Episode Language Realization Plan"
    )
    parser.add_argument("--presentation", required=True, help="the Episode Presentation Plan")
    parser.add_argument("--delivery", required=True, help="the Episode Narration Delivery Plan")
    parser.add_argument("--narration", required=True, help="the Episode Narration Plan")
    parser.add_argument(
        "--shots", required=True, help="the Shot Direction Plan the delivery plan was cut against"
    )
    parser.add_argument(
        "--story",
        required=True,
        help="the Episode Story Plan the realization plan was proven against",
    )
    parser.add_argument(
        "--export",
        required=True,
        help="the render export the story and realization were derived from",
    )
    parser.add_argument(
        "--output-root", required=True, help="where to publish the captions directory"
    )
    namespace = parser.parse_args(argv)

    try:
        caption_plan, caption_plan_bytes = _read_canonical_with_bytes(
            Path(namespace.caption_plan), "caption plan"
        )
        realization, _ = _read_canonical_with_bytes(
            Path(namespace.realization), "language realization plan"
        )
        presentation, _ = _read_canonical_with_bytes(
            Path(namespace.presentation), "presentation plan"
        )
        delivery, _ = _read_canonical_with_bytes(
            Path(namespace.delivery), "narration delivery plan"
        )
        narration, _ = _read_canonical_with_bytes(
            Path(namespace.narration), "episode narration plan"
        )
        shots, _ = _read_canonical_with_bytes(Path(namespace.shots), "shot direction plan")
        story, _ = _read_canonical_with_bytes(Path(namespace.story), "episode story plan")
        export, _ = _read_canonical_with_bytes(Path(namespace.export), "render export")

        final_dir = publish_episode_caption_serialization(
            caption_plan=caption_plan,
            caption_plan_bytes=caption_plan_bytes,
            realization_plan=realization,
            presentation_plan=presentation,
            delivery_plan=delivery,
            narration_plan=narration,
            shot_plan=shots,
            story_plan=story,
            current_export=export,
            output_root=Path(namespace.output_root),
        )
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except CaptionSerializationDirectoryRefused as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    # Reporting only: re-read what was actually published, validate it standalone, and
    # derive the summary from that -- this creates no new authority and serializes nothing.
    manifest = cast(
        dict[str, Any],
        loads_canonical(
            (final_dir / CAPTION_SERIALIZATION_MANIFEST_FILENAME).read_bytes(),
            "episode caption serialization manifest",
        ),
    )
    summary = {
        "caption_frames_total": manifest["accounting"]["caption_frames_total"],
        "captions_dir": str(final_dir),
        "captions_total": manifest["accounting"]["captions_total"],
        "episode": manifest["source"]["episode"],
        "fps": manifest["clock"]["fps"],
        "mode": manifest["source"]["mode"],
        "presentation_frames_total": manifest["clock"]["presentation_frames_total"],
        "srt_sha256": manifest["sidecars"]["srt"]["sha256"],
        "vtt_sha256": manifest["sidecars"]["vtt"]["sha256"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
