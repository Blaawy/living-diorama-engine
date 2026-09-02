r"""Build an Episode Narration Delivery Plan from a narration plan and a shot plan.

    python -m living_diorama.cli.build_narration_delivery_plan \
        --narration episode_narration_plan_v1.json \
        --shots shot_direction_plan_v1.json \
        --output episode_narration_delivery_plan_v1.json

Both inputs must be **canonical** bytes, exactly what their writers emitted,
because the plan binds the digest of each document it read and those claims
have to be true. A file whose bytes are not their own canonical encoding is
refused rather than quietly re-serialized.

The command is a thin shell around ``living_diorama.narration_delivery``: it
cuts no slot of its own, and every refusal comes from the contract rather than
from here. Before anything is written, the freshly built plan is
cross-validated against both inputs, so a delivery plan file can never exist
without its bindings having been proven against the actual sources at least
once.

``--delivery-profile`` selects which slot-allocation policy the plan is cut to.
``v1`` (the default) writes the historical equal-partition plan exactly as this
command always has. ``v4`` writes the content-proportional plan: a host
interval shared by several units is partitioned in proportion to each unit's
required speech frames. The cross-check re-derives the plan under the same
profile, so a v4 plan closes every degree of freedom a v1 plan closes.

There is no render plan and no render manifest input. A delivery slot is
semantic presentation time, settled once the story is narrated and the episode
directed; joining slots and sentences to the frames a render actually produced
is the later realization layers' work.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from living_diorama.narration_delivery import (
    build_episode_narration_delivery_plan_bytes,
    validate_narration_delivery_plan_against_sources,
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
            f"{description} at {path} is not canonical bytes. The delivery plan binds the "
            "digest of every document it read, so each file must be exactly what its "
            "writer emitted -- sorted keys, no spacing, one trailing newline. Rebuild it "
            "rather than reformatting it."
        )
    return document


def build(
    narration_path: Path,
    shots_path: Path,
    output_path: Path,
    delivery_profile: str = "v1",
) -> int:
    """Write the delivery plan for the given sources and return its byte length.

    Under ``delivery_profile="v1"`` the builder call is exactly the historical
    one, byte for byte. Under ``"v4"`` the plan is built with the
    content-proportional partition and carries the v4 policy identifier.
    """
    if output_path.exists():
        raise FileExistsError(
            f"narration delivery plan destination {output_path} already exists; "
            "plans are never overwritten"
        )
    narration = _read_canonical(narration_path, "episode narration plan")
    shots = _read_canonical(shots_path, "shot direction plan")
    payload = build_episode_narration_delivery_plan_bytes(
        narration, shots, delivery_profile=delivery_profile
    )
    # The plan file must never exist without its source bindings having been
    # proven; the cross-check re-derives the plan from both inputs under the
    # same profile and compares byte for byte, so this is a genuine end-to-end
    # verification, not a re-run of the same code path's assumptions. Decoded
    # through the same strict reader as every other document this command
    # touches, rather than a plain json.loads of bytes this process itself just
    # emitted.
    validate_narration_delivery_plan_against_sources(
        loads_canonical(payload, "narration delivery plan"),
        narration,
        shots,
        delivery_profile=delivery_profile,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)
    return len(payload)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, write the plan, and report what was scheduled."""
    parser = argparse.ArgumentParser(
        prog="build_narration_delivery_plan",
        description="Derive an Episode Narration Delivery Plan from a narration and a direction.",
    )
    parser.add_argument("--narration", required=True, help="the Episode Narration Plan to schedule")
    parser.add_argument(
        "--shots", required=True, help="the Shot Direction Plan whose segments host the slots"
    )
    parser.add_argument(
        "--delivery-profile",
        choices=("v1", "v4"),
        default="v1",
        help="delivery profile: v1 (equal partition, the historical output) or "
        "v4 (content-proportional partition by required speech frames)",
    )
    parser.add_argument("--output", required=True, help="where to write the delivery plan")
    namespace = parser.parse_args(argv)

    try:
        written = build(
            Path(namespace.narration),
            Path(namespace.shots),
            Path(namespace.output),
            delivery_profile=namespace.delivery_profile,
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
        loads_canonical(Path(namespace.output).read_bytes(), "narration delivery plan"),
    )
    counts = {
        "allocated_unshown": document["accounting"]["allocated_unshown"],
        "bytes": written,
        "deliveries": document["accounting"]["deliveries_total"],
        "episode": document["source"]["episode"],
        "mode": document["source"]["mode"],
        "shot_anchored": document["accounting"]["shot_anchored"],
    }
    print(json.dumps(counts, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
