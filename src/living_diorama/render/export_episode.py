"""Command-line render export: one verified episode into one JSON artifact.

Usage::

    python -m living_diorama.render.export_episode
        --save-root <path> --episode <N> --output <render-export.json>

The command is a thin face over :func:`write_render_export`: the source
episode and its complete ancestry are verified through the real
:class:`SaveManager` before anything is projected, the canonical bytes are
fully built before the destination is created, an existing destination is
refused rather than overwritten, and the destination may never resolve inside
the save root. There are no other knobs -- no seed, no renderer, no style:
a render export is a deterministic projection of verified history, and two
invocations against the same source produce byte-identical output.
"""

import argparse
import re
import sys
from collections.abc import Sequence
from typing import Final

from living_diorama.persistence import loads_canonical, sha256_hex
from living_diorama.persistence.json_codec import require_document
from living_diorama.render.render_exporter import write_render_export

_EPISODE_TEXT: Final = re.compile(r"\A(?:0|[1-9][0-9]*)\Z")
"""Exactly a canonical non-negative integer: no sign, no padding, no dot."""


def _build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the render export entry point."""
    parser = argparse.ArgumentParser(
        prog="python -m living_diorama.render.export_episode",
        description=(
            "Export one verified Living Diorama episode as deterministic, "
            "consumer-neutral Render Export JSON."
        ),
    )
    parser.add_argument(
        "--save-root",
        required=True,
        help="directory holding the verified episode chain",
    )
    parser.add_argument(
        "--episode",
        required=True,
        help="episode number to export (non-negative integer)",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="destination file for the render export; must not exist",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one render export from the command line and report the outcome.

    Args:
        argv: Argument list to parse, or ``None`` for ``sys.argv``.

    Returns:
        0 on verified success, 1 on any refused or failed export.
    """
    arguments = _build_parser().parse_args(None if argv is None else list(argv))
    # ``Path("")`` silently normalizes to the current directory; blank
    # operator input is refused, never repaired.
    if not arguments.save_root.strip():
        print("render export failed: --save-root must not be empty", file=sys.stderr)
        return 1
    if not arguments.output.strip():
        print("render export failed: --output must not be empty", file=sys.stderr)
        return 1
    if _EPISODE_TEXT.match(arguments.episode) is None:
        print(
            f"render export failed: --episode must be a non-negative integer, "
            f"got {arguments.episode!r}",
            file=sys.stderr,
        )
        return 1

    try:
        data = write_render_export(
            save_root=arguments.save_root,
            episode=int(arguments.episode),
            output_path=arguments.output,
        )
    except (OSError, TypeError, ValueError) as error:
        print(f"render export failed: {error}", file=sys.stderr)
        return 1

    # Reported from the exact bytes that were written and read back, not from
    # any intermediate state.
    document = require_document(loads_canonical(data, "render export"), "render export")
    source = require_document(document["source"], "render export source")
    print("render export verified")
    print(f"episode: {source['episode']}")
    print(f"tick: {source['tick']}")
    print(f"source state hash: {source['state_hash']}")
    print(f"render sha256: {sha256_hex(data)}")
    print(f"bytes: {len(data)}")
    print(f"output: {arguments.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - module execution entry
    raise SystemExit(main())
