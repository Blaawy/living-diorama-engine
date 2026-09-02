r"""Build an Episode Voice Plan from a realization and a presentation plan.

    python -m living_diorama.cli.build_voice_plan \
        --realization episode_language_realization_plan_v1.json \
        --presentation episode_presentation_plan_v1.json \
        --delivery episode_narration_delivery_plan_v1.json \
        --narration episode_narration_plan_v1.json \
        --shots shot_direction_plan_v1.json \
        --story episode_story_plan_v1.json \
        --export render_export_ep2.json \
        --output episode_voice_plan_v1.json

All seven input documents must be **canonical** bytes, exactly what their
writers emitted, because the plan binds the digest of two of them and those
claims have to be true. A file whose bytes are not their own canonical
encoding is refused rather than quietly re-serialized.

Seven inputs, not two, because this plan's own capacity depends on one fact
this command must prove before trusting it: that the presentation plan's
windows -- and the realization plan's sentences they name -- are true of the
actual delivery, narration, shot, story and render-export chain. The
delivery plan, narration plan, shot plan, story plan and render export are
never bound in the voice plan itself; they exist only so the one locked
upstream source-verification gate this command runs can prove what this plan
consumes.

The command is a thin shell around ``living_diorama.voice``: it holds no
narrator request of its own beyond the package's pinned constants, and every
refusal comes from the contract rather than from here. Before anything is
written, the freshly built plan is cross-validated against all seven inputs
-- the reused upstream gate included -- so a voice plan file can never exist
without every one of its bindings having been proven against the actual
sources at least once.

There is no synthesis here, and no model dependency. A voice plan is
narrator-request identity and integer audio capacity, settled before a
single sample of audio is ever produced; synthesizing speech and proving it
actually fits is the later voice execution layer's work.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.voice import (
    build_episode_voice_plan_bytes,
    validate_episode_voice_plan_against_sources,
)


def _read_canonical(path: Path, description: str) -> object:
    """Load a document, refusing any file that is not canonical bytes.

    Decoding goes through the repository's one strict decoder rather than a
    second implementation of the same rules: ``loads_canonical`` already
    refuses malformed UTF-8, malformed JSON, a duplicate object key, and the
    non-standard constants (``NaN``, ``Infinity``, ``-Infinity``, and an
    overflowing literal such as ``1e999``) that plain ``json.loads`` would
    otherwise accept. The canonical-bytes comparison below is a second,
    independent claim -- not merely valid JSON, but *this file's own writer's*
    encoding of it.

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
            f"{description} at {path} is not canonical bytes. The voice plan binds the "
            "digest of every document it reads, so each file must be exactly what its "
            "writer emitted -- sorted keys, no spacing, one trailing newline. Rebuild it "
            "rather than reformatting it."
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
    """Write the voice plan for the given sources and return its byte length.

    Args:
        realization_path: The Episode Language Realization Plan the plan speaks.
        presentation_path: The Episode Presentation Plan the plan speaks to.
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
        output_path: Where to write the voice plan; refused if it already exists.
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
            f"voice plan destination {output_path} already exists; plans are never overwritten"
        )
    realization = _read_canonical(realization_path, "language realization plan")
    presentation = _read_canonical(presentation_path, "presentation plan")
    delivery = _read_canonical(delivery_path, "narration delivery plan")
    narration = _read_canonical(narration_path, "episode narration plan")
    shots = _read_canonical(shots_path, "shot direction plan")
    story = _read_canonical(story_path, "episode story plan")
    export = _read_canonical(export_path, "render export")

    payload = build_episode_voice_plan_bytes(realization, presentation)
    # The plan file must never exist without every one of its bindings having
    # been proven -- the reused upstream gate included. This re-derives the
    # plan from its two bound sources and separately re-runs the Phase 27
    # source proof against the five verification-only documents, so this is
    # a genuine end-to-end verification, not a re-run of the same code
    # path's assumptions. Decoded through the same strict reader as every
    # other document this command touches, rather than a plain json.loads of
    # bytes this process itself just emitted.
    validate_episode_voice_plan_against_sources(
        loads_canonical(payload, "voice plan"),
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
    """Parse arguments, write the plan, and report what was spoken."""
    parser = argparse.ArgumentParser(
        prog="build_voice_plan",
        description=(
            "Derive an Episode Voice Plan from a realization and a presentation plan, "
            "verified against the delivery plan, narration plan, shot plan, story plan "
            "and render export."
        ),
    )
    parser.add_argument(
        "--realization", required=True, help="the Episode Language Realization Plan"
    )
    parser.add_argument("--presentation", required=True, help="the Episode Presentation Plan")
    parser.add_argument(
        "--delivery",
        required=True,
        help="the Episode Narration Delivery Plan the presentation plan images",
    )
    parser.add_argument(
        "--narration", required=True, help="the Episode Narration Plan the presentation presents"
    )
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
    parser.add_argument("--output", required=True, help="where to write the voice plan")
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
        # OSError covers the deliberate FileExistsError/FileNotFoundError
        # refusals as well as generic filesystem failures (permissions, disk
        # full), so every anticipated failure reports cleanly instead of
        # crashing with a traceback.
        print(f"error: {error}", file=sys.stderr)
        return 1

    document = cast(
        dict[str, Any],
        loads_canonical(Path(namespace.output).read_bytes(), "voice plan"),
    )
    counts = {
        "bytes": written,
        "episode": document["source"]["episode"],
        "mode": document["source"]["mode"],
        "voice_units_total": document["accounting"]["voice_units_total"],
        "capacity_samples_total": document["accounting"]["capacity_samples_total"],
    }
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
