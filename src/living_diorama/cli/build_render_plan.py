r"""Build an Episode Render Plan from a validated Shot Direction Plan.

    python -m living_diorama.cli.build_render_plan \
        --shot-plan shot_direction_plan_v1.json \
        --story-plan episode_story_plan_v1.json \
        --output episode_render_plan.json

Both inputs must be **canonical** bytes, exactly what their writers emitted,
because the render plan binds their digests and those claims have to be true.
The story plan is required because it is the only document that names the
render exports this episode was derived from -- binding them is what lets the
renderer refuse a correct plan pointed at the wrong world -- and it is accepted
only if its digest is the one the shot plan already bound. Everything else is
derived: the frames come from Phase 17's clock through Phase 22's tiling, the
cameras come from the shots, and the profile is this build's pinned profile.

Nothing is written unless the freshly built plan validates, so a render plan
file can never exist without having been proven at least once.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.render_execution import build_episode_render_plan_bytes


def _read_canonical(path: Path, description: str) -> object:
    """Load a document, refusing any file that is not canonical bytes.

    The same rule Phase 22 holds its inputs to, for the same reason: the render
    plan binds the digest of the shot plan it read, so the file has to be
    exactly what its writer emitted rather than a re-formatted copy that
    happens to carry the same data.

    Raises:
        FileNotFoundError: If the file is absent.
        ValueError: If the bytes are not valid UTF-8 JSON, or not canonical.
    """
    if not path.is_file():
        raise FileNotFoundError(f"{description} not found: {path}")
    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{description} is not valid UTF-8 JSON: {error}") from None
    if raw != dumps_canonical(document, description):
        raise ValueError(
            f"{description} at {path} is not canonical bytes. The render plan binds the "
            "digest of the shot direction plan it read, so the file must be exactly what "
            "its writer emitted -- sorted keys, no spacing, one trailing newline."
        )
    return document


def main(argv: Sequence[str] | None = None) -> int:
    """Build one render plan from the command line and report the outcome.

    Args:
        argv: Argument list to parse, or ``None`` for ``sys.argv``.

    Returns:
        0 on success, 1 on any refused input or refused write.
    """
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.cli.build_render_plan",
        description="Derive an Episode Render Plan from a directed episode.",
    )
    parser.add_argument("--shot-plan", required=True, help="the Shot Direction Plan to render")
    parser.add_argument(
        "--story-plan", required=True, help="the Episode Story Plan it was cut from"
    )
    parser.add_argument("--output", required=True, help="where to write the render plan")
    parser.add_argument(
        "--camera-profile",
        choices=("v1", "v2"),
        default="v1",
        help=(
            "the camera profile to derive under; v1 (the default) reproduces today's "
            "bytes exactly, v2 additionally binds the movement catalogue and derives "
            "movement camera identities"
        ),
    )
    arguments = parser.parse_args(None if argv is None else list(argv))

    shot_path = Path(arguments.shot_plan)
    story_path = Path(arguments.story_plan)
    output_path = Path(arguments.output)
    try:
        shot_plan = _read_canonical(shot_path, "shot direction plan")
        story_plan = _read_canonical(story_path, "episode story plan")
        payload = build_episode_render_plan_bytes(
            shot_plan, story_plan, camera_profile=arguments.camera_profile
        )
    except (OSError, TypeError, ValueError) as error:
        print(f"render plan refused: {error}", file=sys.stderr)
        return 1

    if output_path.exists():
        print(f"render plan refused: {output_path} already exists", file=sys.stderr)
        return 1
    try:
        output_path.write_bytes(payload)
    except OSError as error:
        print(f"render plan refused: {error}", file=sys.stderr)
        return 1

    print(f"episode render plan written to {output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module execution entry
    raise SystemExit(main())
