r"""Audit an executed episode against its own voice manifest.

    python -m living_diorama.cli.verify_voice --voice-dir voice/episode_0000_to_0001

This is the independent half of Phase 29. The executor writes the speech and
the manifest; this command re-reads every byte on disk and decides whether
the manifest told the truth. It trusts nothing the executor recorded: each
unit is re-hashed and re-parsed, its sample count is recomputed from the
file, every planned unit is required to be present, and any file anywhere in
the voice directory that nothing accounts for is a refusal rather than a
shrug.

It writes nothing, repairs nothing, synthesizes nothing, downloads nothing,
and imports no Kokoro or Torch stack.
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from living_diorama.voice_execution import audit_voice_directory


def main(argv: Sequence[str] | None = None) -> int:
    """Audit one voice directory and report the outcome.

    Returns:
        0 when the execution is complete and truthful, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.cli.verify_voice",
        description="Audit an executed episode against its own voice manifest.",
    )
    parser.add_argument("--voice-dir", required=True, help="the directory one execution owns")
    arguments = parser.parse_args(None if argv is None else list(argv))

    voice_dir = Path(arguments.voice_dir)
    if not voice_dir.is_dir():
        print(f"voice audit refused: {voice_dir} is not a directory", file=sys.stderr)
        return 1
    problems = audit_voice_directory(voice_dir)
    if problems:
        for problem in problems:
            print(f"  PROBLEM {problem}", file=sys.stderr)
        print(f"voice audit failed: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"voice audit passed: {voice_dir}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module execution entry
    raise SystemExit(main())
