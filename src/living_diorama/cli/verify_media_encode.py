r"""Audit one published final-media directory, self-contained and tool-free.

    python -m living_diorama.cli.verify_media_encode \
        --final-dir final_media/episode_0000_to_0001

The independent, TOOL-FREE half of Phase 35, as a command: it re-reads every byte on
disk, re-validates both provenance copies under their locked upstream schemas, re-hashes
every bound digest and every owned file, re-proves the identity, clock and lineage joins
and the directory-name law, rebuilds the logical invocation, and refuses any unaccounted
entry. It trusts nothing the executor recorded, needs no upstream document and no tool,
and succeeds after every source location has disappeared.

Correction E, honored in the command surface itself: this verifier never probes and never
decodes -- the recorded stream facts remain tool-attested, and their re-proof against the
actual bitstream belongs to the tool-bearing executor no-op and the runtime acceptance.
There is no ``--ffprobe`` flag and no ``--assembly-dir`` flag: the audit is self-contained
by design and accepts exactly one directory.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from living_diorama.media_encode import audit_media_encode_directory
from living_diorama.media_encode.media_encode_staging import _is_path_indirection


def main(argv: Sequence[str] | None = None) -> int:
    """Audit one final-media directory and report the outcome.

    Returns:
        0 when the build is complete and byte-truthful, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.cli.verify_media_encode",
        description="Audit a published final-media directory against its own manifest.",
    )
    parser.add_argument(
        "--final-dir", required=True, help="the directory one final-media build owns"
    )
    arguments = parser.parse_args(None if argv is None else list(argv))

    final_dir = Path(arguments.final_dir)
    # ---- indirection is refused before any query that would follow it ----
    if _is_path_indirection(final_dir):
        print(
            f"media encode audit refused: {final_dir} is a symlink or junction",
            file=sys.stderr,
        )
        return 1
    if not final_dir.is_dir():
        print(f"media encode audit refused: {final_dir} is not a directory", file=sys.stderr)
        return 1
    problems = audit_media_encode_directory(final_dir)
    if problems:
        for problem in problems:
            print(f"  PROBLEM {problem}", file=sys.stderr)
        print(f"media encode audit failed: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"media encode audit passed: {final_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
