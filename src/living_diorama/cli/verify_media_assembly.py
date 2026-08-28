r"""Audit a published episode media assembly against its own manifest.

    python -m living_diorama.cli.verify_media_assembly \
        --assembly-dir media_assembly/episode_0000_to_0001

This is the independent half of Phase 33. The assembler writes the copies and the
manifest; this command re-reads every byte on disk and decides whether the manifest told
the truth. It is self-contained: it reads only the entries inside the directory it is
handed, and succeeds after the Phase 23 render directory, the Phase 31 composition
directory, and the presentation, delivery and shot plan files this assembly was built from
are no longer available. There is no ``--render-dir``, ``--composition-dir``,
``--presentation``, ``--delivery`` or ``--shots`` flag, and no detached, unaudited manifest
is ever accepted.

It writes nothing, repairs nothing, assembles nothing, and imports no rendering or
synthesis engine of any kind.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from living_diorama.media_assembly import audit_media_assembly_directory
from living_diorama.media_assembly.media_assembly_staging import _is_path_indirection


def main(argv: Sequence[str] | None = None) -> int:
    """Audit one media assembly directory and report the outcome.

    Returns:
        0 when the assembly is complete and truthful, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.cli.verify_media_assembly",
        description="Audit a published episode media assembly against its own manifest.",
    )
    parser.add_argument("--assembly-dir", required=True, help="the directory one assembly owns")
    arguments = parser.parse_args(None if argv is None else list(argv))

    assembly_dir = Path(arguments.assembly_dir)
    # ---- indirection is refused before any query that would follow it ----
    if _is_path_indirection(assembly_dir):
        print(
            f"media assembly audit refused: {assembly_dir} is a symlink or junction",
            file=sys.stderr,
        )
        return 1
    if not assembly_dir.is_dir():
        print(
            f"media assembly audit refused: {assembly_dir} is not a directory",
            file=sys.stderr,
        )
        return 1
    problems = audit_media_assembly_directory(assembly_dir)
    if problems:
        for problem in problems:
            print(f"  PROBLEM {problem}", file=sys.stderr)
        print(f"media assembly audit failed: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"media assembly audit passed: {assembly_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module execution entry
    raise SystemExit(main())
