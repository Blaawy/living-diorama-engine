r"""Audit a composed episode against its own audio composition manifest.

    python -m living_diorama.cli.verify_audio_composition \
        --composition-dir audio_tracks/episode_0000_to_0001

This is the independent half of Phase 31. The composer writes the track and
the manifest; this command re-reads every byte on disk and decides whether
the manifest told the truth. It is self-contained: it reads only the four
entries inside the directory it is handed, and succeeds after the original
Phase 29 voice directory the composition was built from is no longer
available. There is no ``--voice-dir`` flag, and no detached, unaudited
manifest is ever accepted.

It writes nothing, repairs nothing, composes nothing, synthesizes nothing,
and imports no third-party dependency of any kind.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from living_diorama.audio_composition import audit_audio_composition_directory
from living_diorama.audio_composition.audio_composition_staging import _is_path_indirection


def main(argv: Sequence[str] | None = None) -> int:
    """Audit one composition directory and report the outcome.

    Returns:
        0 when the composition is complete and truthful, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.cli.verify_audio_composition",
        description="Audit a composed episode against its own audio composition manifest.",
    )
    parser.add_argument(
        "--composition-dir", required=True, help="the directory one composition owns"
    )
    arguments = parser.parse_args(None if argv is None else list(argv))

    composition_dir = Path(arguments.composition_dir)
    # ---- indirection is refused before any query that would follow it ----
    if _is_path_indirection(composition_dir):
        print(
            f"audio composition audit refused: {composition_dir} is a symlink or junction",
            file=sys.stderr,
        )
        return 1
    if not composition_dir.is_dir():
        print(
            f"audio composition audit refused: {composition_dir} is not a directory",
            file=sys.stderr,
        )
        return 1
    problems = audit_audio_composition_directory(composition_dir)
    if problems:
        for problem in problems:
            print(f"  PROBLEM {problem}", file=sys.stderr)
        print(f"audio composition audit failed: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"audio composition audit passed: {composition_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module execution entry
    raise SystemExit(main())
