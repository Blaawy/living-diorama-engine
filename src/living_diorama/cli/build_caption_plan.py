r"""Build an Episode Caption Plan from a realization and a presentation plan.

    python -m living_diorama.cli.build_caption_plan \
        --realization episode_language_realization_plan_v1.json \
        --presentation episode_presentation_plan_v1.json \
        --delivery episode_narration_delivery_plan_v1.json \
        --narration episode_narration_plan_v1.json \
        --shots shot_direction_plan_v1.json \
        --story episode_story_plan_v1.json \
        --export render_export_ep1.json \
        --output episode_caption_plan_v1.json

All seven inputs must be **canonical** bytes, exactly what their writers
emitted, because the plan binds the digest of two of them and those claims
have to be true. A file whose bytes are not their own canonical encoding is
refused rather than quietly re-serialized.

Seven inputs, not two, because this plan's own legibility windows depend on
facts this command must prove before trusting them: that the presentation
plan's windows are true of the actual delivery, narration and shot chain,
and that the realization plan's sentences are true of the actual story plan
and render export. The delivery plan, narration plan, shot plan, story plan
and render export are never bound in the caption plan itself; they exist
only so the one locked upstream source-verification gate this command runs
can prove what this plan consumes.

The command is a thin shell around ``living_diorama.caption``: it holds no
frame and no sentence of its own, and every refusal comes from the contract
rather than from here. Before anything is written, the freshly built plan is
cross-validated against all seven inputs -- the reused Phase 27 gate
included -- so a caption plan file can never exist without every one of its
bindings having been proven against the actual sources at least once.

There is no audio input of any kind: no voice plan, no voice manifest, no
audio track plan. A caption's legibility window is the presentation plan's
own window, settled without ever measuring a sample of speech.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from living_diorama.caption import (
    build_episode_caption_plan_bytes,
    validate_episode_caption_plan_against_sources,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical


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
            f"{description} at {path} is not canonical bytes. The caption plan binds the "
            "digest of the documents it reads, so each file must be exactly what its writer "
            "emitted -- sorted keys, no spacing, one trailing newline. Rebuild it rather than "
            "reformatting it."
        )
    return document


def build(
    realization_path: Path,
    presentation_path: Path,
    delivery_path: Path,
    narration_path: Path,
    shots_path: Path,
    story_path: Path,
    export_path: Path,
    output_path: Path,
    *,
    presentation_profile: str | None = None,
) -> int:
    """Write the caption plan for the given sources and return its byte length.

    Args:
        realization_path: The Episode Language Realization Plan the plan carries.
        presentation_path: The Episode Presentation Plan the plan captions.
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
        output_path: Where to write the caption plan; refused if it already exists.
        presentation_profile: The presentation profile the reused Phase 27
            gate verifies the presentation plan under. ``None`` (the default)
            preserves today's exact behavior: a presentation plan carrying
            ``motion_windows`` is verified as V2, any other plan as V1. Pass
            ``"v1"``, ``"v2"`` or ``"v3"`` to pin the profile explicitly --
            ``"v3"`` is required for the frozen, content-sized V3
            presentation plan, which carries no ``motion_windows`` and would
            otherwise be re-derived as V1 and refused by the gate.
    """
    if output_path.exists():
        raise FileExistsError(
            f"caption plan destination {output_path} already exists; plans are never overwritten"
        )
    realization = _read_canonical(realization_path, "language realization plan")
    presentation = _read_canonical(presentation_path, "presentation plan")
    delivery = _read_canonical(delivery_path, "narration delivery plan")
    narration = _read_canonical(narration_path, "episode narration plan")
    shots = _read_canonical(shots_path, "shot direction plan")
    story = _read_canonical(story_path, "episode story plan")
    export = _read_canonical(export_path, "render export")

    payload = build_episode_caption_plan_bytes(realization, presentation)
    # The plan file must never exist without every one of its bindings
    # having been proven -- the reused Phase 27 gate included. This
    # re-derives the plan from its two bound sources and separately re-runs
    # the Phase 27 (and, through it, the Phase 25/26) source proofs against
    # the five verification-only documents, so this is a genuine end-to-end
    # verification, not a re-run of the same code path's assumptions.
    validate_episode_caption_plan_against_sources(
        loads_canonical(payload, "caption plan"),
        realization,
        presentation,
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
    """Parse arguments, write the plan, and report what was captioned."""
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.cli.build_caption_plan",
        description=(
            "Derive an Episode Caption Plan from a realization and a presentation plan, "
            "verified against the delivery plan, narration plan, shot plan, story plan and "
            "render export."
        ),
    )
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
    parser.add_argument("--output", required=True, help="where to write the caption plan")
    parser.add_argument(
        "--presentation-profile",
        choices=("v1", "v2", "v3", "v4"),
        default=None,
        help=(
            "the presentation profile the reused Phase 27 gate verifies the presentation "
            "plan under; v1 reproduces today's bytes exactly, v2 verifies the additive "
            "motion-window plan, v3 verifies the frozen, content-sized plan with no motion "
            "windows; when the flag is omitted today's exact behavior is preserved"
        ),
    )
    namespace = parser.parse_args(argv)

    try:
        written = build(
            Path(namespace.realization),
            Path(namespace.presentation),
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

    document = cast(
        dict[str, Any],
        loads_canonical(Path(namespace.output).read_bytes(), "caption plan"),
    )
    counts = {
        "bytes": written,
        "caption_frames_total": document["accounting"]["caption_frames_total"],
        "captions_total": document["accounting"]["captions_total"],
        "episode": document["source"]["episode"],
        "mode": document["source"]["mode"],
        "presentation_frames_total": document["clock"]["presentation_frames_total"],
        "uncaptioned_frames_total": document["accounting"]["uncaptioned_frames_total"],
    }
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
