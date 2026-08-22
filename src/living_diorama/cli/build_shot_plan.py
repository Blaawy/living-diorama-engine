r"""Build a Shot Direction Plan from a story plan and the Phase 17 Motion & Time Spec.

    python -m living_diorama.cli.build_shot_plan \
        --story episode_story_plan_v1.json \
        --motion-time visual/blender/config/motion_time_v1.json \
        --output shot_direction_plan_v1.json

The clock is supplied as the Motion & Time Spec document itself, byte for byte.
Phase 17 owns that document; this command never imports Phase 17's modules and
never resolves a frame of its own -- it hands the exact bytes to the cinematic
layer, which binds their SHA-256 into the plan and derives the phase boundaries
with Phase 17's own arithmetic. A hand-written five-integer "timeline" file can
therefore no longer stand in for the locked clock: the plan names the document
it was cut against, and anything else fails the binding.

The story input must be **canonical** bytes, exactly what the writer that
produced it emitted, because the plan binds the digest of the story plan it read
and that claim has to be true. The Motion & Time Spec is bound as its raw source
bytes -- pretty-printed exactly as Phase 17 ships it -- so no re-encoding
requirement is imposed on a document another phase owns.

Before anything is written, the freshly built plan is cross-validated against
both inputs, so a plan file can never exist without its bindings having been
proven against the actual sources at least once.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from living_diorama.cinematic import (
    build_shot_direction_plan_bytes,
    validate_shot_direction_plan_against_story,
)
from living_diorama.persistence.json_codec import dumps_canonical


def _read_canonical(path: Path, description: str) -> object:
    """Load a document, refusing any file that is not canonical bytes."""
    if not path.is_file():
        raise FileNotFoundError(f"{description} not found: {path}")
    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{description} is not valid UTF-8 JSON: {error}") from None
    if raw != dumps_canonical(document, description):
        raise ValueError(
            f"{description} at {path} is not canonical bytes. The shot plan binds "
            "the digest of the story plan it read, so the file must be exactly what "
            "its writer emitted -- sorted keys, no spacing, one trailing newline."
        )
    return document


def _read_bytes(path: Path, description: str) -> bytes:
    """Read a source document's exact bytes, refusing an absent or empty file."""
    if not path.is_file():
        raise FileNotFoundError(f"{description} not found: {path}")
    raw = path.read_bytes()
    if not raw:
        raise ValueError(f"{description} at {path} is empty")
    return raw


def build(story_path: Path, motion_time_path: Path, output_path: Path) -> int:
    """Write the shot plan for the given inputs and return its byte length."""
    if output_path.exists():
        raise FileExistsError(
            f"shot direction plan destination {output_path} already exists; "
            "plans are never overwritten"
        )
    story = _read_canonical(story_path, "episode story plan")
    motion_time = _read_bytes(motion_time_path, "motion time spec")
    payload = build_shot_direction_plan_bytes(story, motion_time)
    # The plan file must never exist without its source bindings having been
    # proven; the cross-check re-derives the plan from both inputs and compares
    # byte for byte, so this is a genuine end-to-end verification, not a re-run
    # of the same code path's assumptions.
    validate_shot_direction_plan_against_story(
        json.loads(payload.decode("utf-8")), story, motion_time
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return len(payload)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, write the plan, and report what was directed."""
    parser = argparse.ArgumentParser(
        prog="build_shot_plan",
        description="Derive a Shot Direction Plan from a verified story plan.",
    )
    parser.add_argument("--story", required=True, help="the Episode Story Plan to direct")
    parser.add_argument(
        "--motion-time",
        required=True,
        help="the Phase 17 Motion & Time Spec document the plan is cut against",
    )
    parser.add_argument("--output", required=True, help="where to write the shot plan")
    namespace = parser.parse_args(argv)

    try:
        written = build(Path(namespace.story), Path(namespace.motion_time), Path(namespace.output))
    except (OSError, TypeError, ValueError) as error:
        # OSError covers the deliberate FileExistsError/FileNotFoundError
        # refusals as well as generic filesystem failures (permissions, disk
        # full), so every anticipated failure reports cleanly instead of
        # crashing with a traceback.
        print(f"error: {error}", file=sys.stderr)
        return 1

    document = json.loads(Path(namespace.output).read_text(encoding="utf-8"))
    counts = {
        "bytes": written,
        "episode": document["source"]["episode"],
        "mode": document["source"]["mode"],
        "motion_time_sha256": document["source"]["motion_time_sha256"],
        "shots": len(document["shots"]),
        "unshown": len(document["unshown"]),
    }
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
