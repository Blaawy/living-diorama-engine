r"""Build an Episode Story Plan from render export files.

Reads one export for a baseline plan, or two consecutive exports for a
transition plan, and writes the canonical plan bytes.

    python -m living_diorama.cli.build_story_plan \\
        --current render_export_ep2.json \\
        --previous render_export_ep1.json \\
        --output episode_story_plan_v1.json

The command is a thin shell around ``living_diorama.story``: it does no
selection of its own, and every refusal comes from the contract rather than from
here. Like the render exporter, it never overwrites an existing output file.

Input files must be **canonical** render export bytes -- exactly what
``living_diorama.render.write_render_export`` produces. A file whose bytes are
not their own canonical encoding is refused rather than accepted and quietly
re-serialized, because the plan's ``document_sha256`` is then also the digest of
the source file itself, and that claim has to be true.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.story import build_episode_story_plan_bytes


def _read_document(path: Path, description: str) -> object:
    """Load a render export, refusing any file that is not canonical bytes.

    Raises:
        FileNotFoundError: If the file is absent.
        ValueError: If the file is not valid JSON, or if its bytes are not the
            canonical encoding of the document they contain.
    """
    if not path.is_file():
        raise FileNotFoundError(f"{description} not found: {path}")
    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{description} is not valid UTF-8 JSON: {error}") from None
    canonical = dumps_canonical(document, description)
    if raw != canonical:
        raise ValueError(
            f"{description} at {path} is not canonical render export bytes. "
            "The story plan binds the digest of the source document, so the file "
            "must be exactly what write_render_export produced -- sorted keys, "
            "no spacing, one trailing newline. Re-export it rather than "
            "reformatting it."
        )
    return document


def build(current_path: Path, previous_path: Path | None, output_path: Path) -> int:
    """Write the plan for the given exports and return its byte length."""
    if output_path.exists():
        raise FileExistsError(
            f"story plan destination {output_path} already exists; "
            "plans are never overwritten"
        )
    current = _read_document(current_path, "current render export")
    previous = (
        _read_document(previous_path, "previous render export")
        if previous_path is not None
        else None
    )
    payload = build_episode_story_plan_bytes(current, previous)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return len(payload)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, write the plan, and report what was produced."""
    parser = argparse.ArgumentParser(
        prog="build_story_plan",
        description="Derive an Episode Story Plan from verified render exports.",
    )
    parser.add_argument("--current", required=True, help="the render export to describe")
    parser.add_argument(
        "--previous",
        default=None,
        help="the export of the episode before it; omit for a baseline plan",
    )
    parser.add_argument("--output", required=True, help="where to write the plan")
    namespace = parser.parse_args(argv)

    current_path = Path(namespace.current)
    previous_path = Path(namespace.previous) if namespace.previous else None
    output_path = Path(namespace.output)

    try:
        written = build(current_path, previous_path, output_path)
    except (FileExistsError, FileNotFoundError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    document = json.loads(output_path.read_text(encoding="utf-8"))
    counts = {
        "beats": len(document["beats"]),
        "bytes": written,
        "episode": document["source"]["current"]["episode"],
        "mode": document["source"]["mode"],
        "unclassified": len(document["unclassified"]),
    }
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
