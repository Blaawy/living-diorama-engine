r"""Audit one published caption serialization directory, self-contained.

    python -m living_diorama.cli.verify_caption_serialization \
        --caption-dir captions/episode_0000_to_0001

The independent half of Phase 34, as a command: it re-reads every byte on disk,
re-validates the copied plan under the locked Phase 32 schema, re-derives the
frame-authoritative accounting and every timestamp, re-serializes BOTH sidecars
from the copied plan and requires exact byte equality, re-hashes every owned
file, and refuses any unaccounted entry. It trusts nothing the serializer
recorded, needs no upstream document, and succeeds after every source location
has disappeared.

There is no ``--caption-plan``, ``--realization`` or ``--presentation`` flag:
the audit is self-contained by design and accepts exactly one directory.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from living_diorama.caption_serialization import audit_caption_serialization_directory
from living_diorama.caption_serialization.caption_serialization_staging import (
    _is_path_indirection,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Audit one caption serialization directory and report the outcome.

    Returns:
        0 when the serialization is complete and truthful, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.cli.verify_caption_serialization",
        description="Audit a published episode caption serialization against its own manifest.",
    )
    parser.add_argument(
        "--caption-dir", required=True, help="the directory one caption serialization owns"
    )
    arguments = parser.parse_args(None if argv is None else list(argv))

    caption_dir = Path(arguments.caption_dir)
    # ---- indirection is refused before any query that would follow it ----
    if _is_path_indirection(caption_dir):
        print(
            f"caption serialization audit refused: {caption_dir} is a symlink or junction",
            file=sys.stderr,
        )
        return 1
    if not caption_dir.is_dir():
        print(
            f"caption serialization audit refused: {caption_dir} is not a directory",
            file=sys.stderr,
        )
        return 1
    problems = audit_caption_serialization_directory(caption_dir)
    if problems:
        for problem in problems:
            print(f"  PROBLEM {problem}", file=sys.stderr)
        print(f"caption serialization audit failed: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"caption serialization audit passed: {caption_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
