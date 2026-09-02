r"""Build an Episode Presentation Plan from a delivery, a narration and a realization.

    python -m living_diorama.cli.build_presentation_plan \
        --delivery episode_narration_delivery_plan_v1.json \
        --narration episode_narration_plan_v1.json \
        --shots shot_direction_plan_v1.json \
        --realization episode_language_realization_plan_v1.json \
        --story episode_story_plan_v1.json \
        --export render_export_ep2.json \
        --output episode_presentation_plan_v1.json

All six inputs must be **canonical** bytes, exactly what their writers
emitted, because the plan binds the digest of three of them and those claims
have to be true. A file whose bytes are not their own canonical encoding is
refused rather than quietly re-serialized.

Six inputs, not three, because this plan's own geometry depends on two facts
this command must prove before trusting them: that the delivery plan's slots
are true of the actual narration and shot plans, and that the narration
plan's ``text_source`` classification -- which selects every window's floor
under the v1 and v2 profiles -- is true of the actual story plan and render
export. The shot plan, story plan and render export are never bound in the
presentation plan itself; they exist only so the two locked upstream
source-verification gates this command runs can prove what this plan consumes.

The command is a thin shell around ``living_diorama.presentation``: it holds
no frame of its own, and every refusal comes from the contract rather than
from here. Before anything is written, the freshly built plan is
cross-validated against all six inputs -- both upstream gates included -- so
a presentation plan file can never exist without every one of its bindings
having been proven against the actual sources at least once.

There is no render plan and no render manifest input. A presentation window
is viewer-facing timing on the semantic delivery slot's own clock, settled
before a single pixel of the presentation is assembled; joining windows to
the frames a render actually produced and repeating them physically is the
later media-assembly layer's work.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.presentation import (
    build_episode_presentation_plan_bytes,
    validate_episode_presentation_plan_against_sources,
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
            f"{description} at {path} is not canonical bytes. The presentation plan binds "
            "the digest of every document it reads, so each file must be exactly what its "
            "writer emitted -- sorted keys, no spacing, one trailing newline. Rebuild it "
            "rather than reformatting it."
        )
    return document


def build(
    delivery_path: Path,
    narration_path: Path,
    shots_path: Path,
    realization_path: Path,
    story_path: Path,
    export_path: Path,
    output_path: Path,
    *,
    presentation_profile: str = "v1",
) -> int:
    """Write the presentation plan for the given sources and return its byte length.

    Args:
        delivery_path: The Episode Narration Delivery Plan the presentation is timed to.
        narration_path: The Episode Narration Plan bound into the presentation.
        shots_path: The Shot Direction Plan the presentation frames are drawn from.
        realization_path: The Episode Language Realization Plan the delivery is bound to.
        story_path: The Episode Story Plan the whole chain is bound to.
        export_path: The render export the story plan is bound to.
        output_path: Where to write the presentation plan; refused if it already exists.
        presentation_profile: ``"v1"`` (the default) reproduces today's plan
            bytes exactly; ``"v2"`` derives the additive motion-window plan;
            ``"v3"`` derives the frozen, content-sized plan with no
            ``motion_windows``; ``"v4"`` derives the strict 1:1 plan with no
            ``motion_windows``, refusing any unit whose realized narration
            cannot fit its slot. Threaded into both the planner and the
            cross-check, so a V2 plan is byte-verified under the V2 validator
            before it is written and a V3 or V4 plan under the plain V1
            validator.
    """
    if output_path.exists():
        raise FileExistsError(
            f"presentation plan destination {output_path} already exists; plans are never "
            "overwritten"
        )
    delivery = _read_canonical(delivery_path, "narration delivery plan")
    narration = _read_canonical(narration_path, "episode narration plan")
    shots = _read_canonical(shots_path, "shot direction plan")
    realization = _read_canonical(realization_path, "language realization plan")
    story = _read_canonical(story_path, "episode story plan")
    export = _read_canonical(export_path, "render export")

    payload = build_episode_presentation_plan_bytes(
        delivery, narration, realization, presentation_profile=presentation_profile
    )
    # The plan file must never exist without every one of its bindings having
    # been proven -- the two locked upstream gates included. This re-derives
    # the plan from its three bound sources and separately re-runs the Phase
    # 25 and Phase 26 source proofs against the three verification-only
    # documents, so this is a genuine end-to-end verification, not a re-run
    # of the same code path's assumptions. Decoded through the same strict
    # reader as every other document this command touches, rather than a
    # plain json.loads of bytes this process itself just emitted.
    validate_episode_presentation_plan_against_sources(
        loads_canonical(payload, "presentation plan"),
        delivery,
        narration,
        shots,
        realization,
        story,
        export,
        presentation_profile=presentation_profile,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return len(payload)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, write the plan, and report what was presented."""
    parser = argparse.ArgumentParser(
        prog="build_presentation_plan",
        description=(
            "Derive an Episode Presentation Plan from a delivery, a narration and a "
            "realization, verified against the shot plan, story plan and render export."
        ),
    )
    parser.add_argument("--delivery", required=True, help="the Episode Narration Delivery Plan")
    parser.add_argument("--narration", required=True, help="the Episode Narration Plan")
    parser.add_argument(
        "--shots", required=True, help="the Shot Direction Plan the delivery plan was cut against"
    )
    parser.add_argument(
        "--realization", required=True, help="the Episode Language Realization Plan"
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
    parser.add_argument("--output", required=True, help="where to write the presentation plan")
    parser.add_argument(
        "--presentation-profile",
        choices=("v1", "v2", "v3", "v4"),
        default="v1",
        help=(
            "the presentation profile to derive under; v1 (the default) reproduces "
            "today's bytes exactly, v2 derives the additive motion-window plan, v3 "
            "derives the frozen, content-sized plan with no motion windows, v4 derives "
            "the strict 1:1 plan with no motion windows and refuses any unit that "
            "cannot fit its slot"
        ),
    )
    namespace = parser.parse_args(argv)

    try:
        written = build(
            Path(namespace.delivery),
            Path(namespace.narration),
            Path(namespace.shots),
            Path(namespace.realization),
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
        loads_canonical(Path(namespace.output).read_bytes(), "presentation plan"),
    )
    counts = {
        "bytes": written,
        "episode": document["source"]["episode"],
        "mode": document["source"]["mode"],
        "presentation_frames_total": document["accounting"]["presentation_frames_total"],
        "segments": document["accounting"]["segments_total"],
        "windows": document["accounting"]["windows_total"],
    }
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
