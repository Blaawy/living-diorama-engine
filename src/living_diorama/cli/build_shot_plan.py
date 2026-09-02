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

``--camera-profile`` selects which direction contract the plan is cut to.
``v1`` (the default) writes the fixed-anchor Shot Direction Plan V1 exactly as
this command always has. ``v2`` builds the same V1 document first and then adds
the deterministic optional ``camera_movement`` blocks through the cinematic V2
assembly chain (``build -> plan_camera_movements -> validate_v2 ->
dumps_canonical``), which the cross-check re-derives the same way, so a V2 plan
closes every degree of freedom a V1 plan closes.

``--camera-grammar`` selects which movement-assignment lane the V2 chain uses
under ``camera_profile=v2``: ``v1`` (the default) is the original role table,
``v2`` is the Director Revision's context-first grammar, and ``v4`` is the
elevated drone-camera lane (additive elevated-anchor rebinding; only
STATIC/REVEAL/TRACK are ever emitted), and ``v5`` is the absolutely-static
drone lane (one locked pose for the whole episode; the camera never moves).
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from living_diorama.cinematic import (
    build_shot_direction_plan_bytes,
    build_shot_direction_plan_v2_bytes,
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


def build(
    story_path: Path,
    motion_time_path: Path,
    output_path: Path,
    camera_profile: str = "v1",
    camera_grammar: str = "v1",
) -> int:
    """Write the shot plan for the given inputs and return its byte length.

    Under ``camera_profile="v1"`` the builder call is exactly the historical
    one, byte for byte. Under ``"v2"`` the V1 document is built first (unchanged
    call) and then carried through the deterministic V2 chain
    (``plan_camera_movements`` -> ``validate_shot_direction_plan_v2`` ->
    ``dumps_canonical``). ``camera_grammar`` selects which movement-assignment
    lane the chain uses under ``camera_profile="v2"``: ``"v1"`` (the default) is
    the original role table; ``"v2"`` is the Director Revision's context-first
    grammar; ``"v4"`` is the elevated drone-camera lane (additive elevated
    anchor rebinding, STATIC/REVEAL/TRACK only). Ignored under
    ``camera_profile="v1"``.
    """
    if output_path.exists():
        raise FileExistsError(
            f"shot direction plan destination {output_path} already exists; "
            "plans are never overwritten"
        )
    story = _read_canonical(story_path, "episode story plan")
    motion_time = _read_bytes(motion_time_path, "motion time spec")
    if camera_profile == "v2":
        payload = build_shot_direction_plan_v2_bytes(
            story, motion_time, camera_grammar=camera_grammar
        )
    else:
        payload = build_shot_direction_plan_bytes(story, motion_time)
    # The plan file must never exist without its source bindings having been
    # proven; the cross-check re-derives the plan from both inputs and compares
    # byte for byte, so this is a genuine end-to-end verification, not a re-run
    # of the same code path's assumptions.
    validate_shot_direction_plan_against_story(
        json.loads(payload.decode("utf-8")),
        story,
        motion_time,
        camera_profile=camera_profile,
        camera_grammar=camera_grammar,
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
    parser.add_argument(
        "--camera-profile",
        choices=("v1", "v2"),
        default="v1",
        help="direction profile: v1 (fixed anchors, the historical output) or "
        "v2 (adds the deterministic optional camera_movement blocks)",
    )
    parser.add_argument(
        "--camera-grammar",
        choices=("v1", "v2", "v4", "v5"),
        default="v1",
        help="movement-assignment lane under camera_profile=v2: v1 (the "
        "original role table), v2 (the Director Revision's context-first, "
        "zero-push-in grammar) or v4 (the elevated drone-camera lane: additive "
        "elevated anchor rebinding, STATIC/REVEAL/TRACK only). Ignored under "
        "camera_profile=v1.",
    )
    parser.add_argument("--output", required=True, help="where to write the shot plan")
    namespace = parser.parse_args(argv)

    try:
        written = build(
            Path(namespace.story),
            Path(namespace.motion_time),
            Path(namespace.output),
            camera_profile=namespace.camera_profile,
            camera_grammar=namespace.camera_grammar,
        )
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
