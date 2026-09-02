r"""Build the canonical camera-anchor catalogue document.

Writes the approved camera anchor catalogue as canonical JSON bytes -- the same
``dumps_canonical`` form every digest in this project is computed over -- to the
file named by ``--output``, and refuses to overwrite an existing file. The
command is a thin shell around ``living_diorama.cinematic.cinematic_spec``: it
does no selection of its own.

    python -m living_diorama.cli.build_camera_catalogue --output catalogue.json

The written file's digest is ``catalogue_sha256()`` -- the digest every Shot
Direction Plan binds and every Phase 22 validator and the Phase 23 executor
refuse to see drift from -- so the file this command ships is the file the
pipelines were planned against.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from living_diorama.cinematic.cinematic_spec import catalogue_document, catalogue_sha256
from living_diorama.persistence.json_codec import dumps_canonical


def build(output_path: Path) -> int:
    """Write the canonical camera catalogue and return its byte length.

    Raises:
        FileExistsError: If the destination already exists. A catalogue is
            evidence; silently replacing one loses history.
    """
    if output_path.exists():
        raise FileExistsError(
            f"camera catalogue destination {output_path} already exists; "
            "a catalogue is never overwritten"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dumps_canonical(catalogue_document(), "camera anchor catalogue")
    output_path.write_bytes(payload)
    return len(payload)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, write the catalogue, and report what was produced."""
    parser = argparse.ArgumentParser(
        prog="build_camera_catalogue",
        description="Write the canonical camera-anchor catalogue document.",
    )
    parser.add_argument("--output", required=True, help="where to write the catalogue")
    namespace = parser.parse_args(argv)
    output_path = Path(namespace.output)

    try:
        written = build(output_path)
    except FileExistsError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "anchors": len(catalogue_document()),
                "bytes": written,
                "catalogue_sha256": catalogue_sha256(),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
