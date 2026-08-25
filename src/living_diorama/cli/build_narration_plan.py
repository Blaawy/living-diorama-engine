r"""Build an Episode Narration Plan from a story plan, a shot plan and an export.

    python -m living_diorama.cli.build_narration_plan \
        --story episode_story_plan_v1.json \
        --shots shot_direction_plan_v1.json \
        --export render_export_ep2.json \
        --output episode_narration_plan_v1.json

All three inputs must be **canonical** bytes, exactly what their writers
emitted, because the plan binds the digest of each document it read and those
claims have to be true. A file whose bytes are not their own canonical encoding
is refused rather than quietly re-serialized.

The command is a thin shell around ``living_diorama.narration``: it composes no
sentence of its own, and every refusal comes from the contract rather than from
here. Before anything is written, the freshly built plan is cross-validated
against all three inputs, so a narration plan file can never exist without its
bindings having been proven against the actual sources at least once.

There is no render manifest input. Narration authoring is settled once the story
is emphasised and the episode directed; joining these sentences to the frames a
render actually produced is the later realization layer's work.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from living_diorama.narration import (
    build_episode_narration_plan_bytes,
    validate_narration_plan_against_sources,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical


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
            f"{description} at {path} is not canonical bytes. The narration plan binds the "
            "digest of every document it read, so each file must be exactly what its writer "
            "emitted -- sorted keys, no spacing, one trailing newline. Rebuild it rather "
            "than reformatting it."
        )
    return document


def build(story_path: Path, shots_path: Path, export_path: Path, output_path: Path) -> int:
    """Write the narration plan for the given sources and return its byte length."""
    if output_path.exists():
        raise FileExistsError(
            f"episode narration plan destination {output_path} already exists; "
            "plans are never overwritten"
        )
    story = _read_canonical(story_path, "episode story plan")
    shots = _read_canonical(shots_path, "shot direction plan")
    export = _read_canonical(export_path, "render export")
    payload = build_episode_narration_plan_bytes(story, shots, export)
    # The plan file must never exist without its source bindings having been
    # proven; the cross-check re-derives the plan from all three inputs and
    # compares byte for byte, so this is a genuine end-to-end verification, not
    # a re-run of the same code path's assumptions. Decoded through the same
    # strict reader as every other document this command touches, rather than
    # a plain json.loads of bytes this process itself just emitted.
    validate_narration_plan_against_sources(
        loads_canonical(payload, "episode narration plan"), story, shots, export
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return len(payload)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, write the plan, and report what was narrated."""
    parser = argparse.ArgumentParser(
        prog="build_narration_plan",
        description="Derive an Episode Narration Plan from a verified story, direction and export.",
    )
    parser.add_argument("--story", required=True, help="the Episode Story Plan to restate")
    parser.add_argument("--shots", required=True, help="the Shot Direction Plan that directed it")
    parser.add_argument(
        "--export",
        required=True,
        help="the render export the story plan was derived from",
    )
    parser.add_argument("--output", required=True, help="where to write the narration plan")
    namespace = parser.parse_args(argv)

    try:
        written = build(
            Path(namespace.story),
            Path(namespace.shots),
            Path(namespace.export),
            Path(namespace.output),
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
        loads_canonical(Path(namespace.output).read_bytes(), "episode narration plan"),
    )
    counts = {
        "bytes": written,
        "episode": document["source"]["episode"],
        "mode": document["source"]["mode"],
        "units": document["accounting"]["beats_total"],
        "units_shown": document["accounting"]["units_shown"],
        "units_unshown": document["accounting"]["units_unshown"],
    }
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
