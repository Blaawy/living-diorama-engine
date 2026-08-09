"""Produce the Phase 17 motion inputs with the real engine, end to end.

Engine-side tooling, not Blender code. Phase 15 already generates the
authoritative three-episode proof chain; Phase 17 needs one more view of that
SAME chain, so this module runs the locked generator unchanged and then
exports the episode it did not export.

The chain the engine actually produced:

    Episode 0   four districts, movement law in force, no wall.
    Episode 1   the rule turns sharing OFF; the eastern annex starves behind
                its only boundary and BoundaryDecisionSystem raises a
                permanent wall. The Seal goes dark.
    Episode 2   the rule is RESTORED -- and the wall remains, with the
                conduits visibly anchored into it.

That gives two real transitions rather than one, and between them they cover
every visual channel the world's current state mapping can express:

    LEG 1  episode 0 -> episode 1   THE LAW IS SUSPENDED AND THE WALL RISES
    LEG 2  episode 1 -> episode 2   THE LAW RETURNS AND THE WALL REMAINS

Leg 2 is the important one for the project's promise: the law goes back to
exactly what it was, and the scar does not. A truthful planner emits no wall
directive at all for it, because nothing about the wall changed.

Nothing here is hand-written. Every export is produced by the locked Phase 14
exporter from a verified episode of the locked Phase 15 save chain.

Outputs, under the given workspace directory::

    saves/                       the real three-episode chain
    render_export_before.json    episode 0
    render_export_mid.json       episode 1
    render_export_after.json     episode 2
    proof_inputs_manifest.json   the Phase 15 input manifest
    motion_story_manifest.json   the two legs, with hashes and what changed
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

PROOF_TOOLS_DIR = Path(__file__).resolve().parent.parent / "phase15_proof"
if str(PROOF_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(PROOF_TOOLS_DIR))

from generate_proof_exports import MOVEMENT_LAW_ID, generate  # noqa: E402

from living_diorama.persistence import sha256_hex  # noqa: E402
from living_diorama.render import write_render_export  # noqa: E402

MID_EPISODE = 1

LEGS = (
    ("leg1_law_suspended_wall_rises", "render_export_before.json", "render_export_mid.json"),
    ("leg2_law_restored_wall_remains", "render_export_mid.json", "render_export_after.json"),
)


def _visual_state(export: dict) -> dict:
    """The authoritative fields the Phase 15 visual mapping actually reads."""
    return {
        "episode": export["source"]["episode"],
        "tick": export["source"]["tick"],
        "state_hash": export["source"]["state_hash"],
        "law_active": {entry["id"]: entry["active"] for entry in export["world"]["laws"]},
        "walls": sorted(entry["id"] for entry in export["world"]["walls"]),
        "population": {entry["id"]: entry["population"] for entry in export["world"]["districts"]},
        "stock": {
            entry["id"]: round(sum(entry["resources"].values()), 6)
            for entry in export["world"]["districts"]
        },
        "dependency": {
            entry["id"]: entry["dependency_score"] for entry in export["world"]["infrastructure"]
        },
        "degraded": sorted(
            entry["id"] for entry in export["world"]["infrastructure"] if entry["degraded"]
        ),
    }


def _changed(before: dict, after: dict) -> dict:
    """Which authoritative visual facts genuinely differ across one leg."""
    changes: dict[str, object] = {}
    for key in ("law_active", "walls", "population", "stock", "dependency", "degraded"):
        if before[key] != after[key]:
            changes[key] = {"before": before[key], "after": after[key]}
    return changes


def generate_motion_story(workspace: Path) -> dict:
    """Run the locked proof story, add the middle export, and describe both legs."""
    workspace = Path(workspace)
    inputs = generate(workspace)
    mid_path = workspace / "render_export_mid.json"
    mid_bytes = write_render_export(workspace / "saves", MID_EPISODE, mid_path)

    documents = {
        name: json.loads((workspace / name).read_text(encoding="utf-8"))
        for _, before, after in LEGS
        for name in (before, after)
    }
    states = {name: _visual_state(document) for name, document in documents.items()}
    manifest = {
        "artifact": "living_diorama_phase17_motion_story",
        "mid_export": {
            "path": mid_path.name,
            "sha256": sha256_hex(mid_bytes),
            "episode": MID_EPISODE,
            "state_hash": documents[mid_path.name]["source"]["state_hash"],
        },
        "exports": {
            name: {
                "sha256": sha256_hex((workspace / name).read_bytes()),
                "episode": state["episode"],
                "tick": state["tick"],
                "state_hash": state["state_hash"],
            }
            for name, state in sorted(states.items())
        },
        "legs": {
            leg: {
                "before": before,
                "after": after,
                "changed": _changed(states[before], states[after]),
            }
            for leg, before, after in LEGS
        },
        "phase15_inputs": inputs,
    }
    (workspace / "motion_story_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the motion story and print what actually changed in each leg."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="fresh output directory")
    arguments = parser.parse_args(None if argv is None else list(argv))
    if not arguments.workspace.strip():
        print("motion story generation failed: --workspace must not be empty", file=sys.stderr)
        return 1
    manifest = generate_motion_story(Path(arguments.workspace))
    print(json.dumps(manifest["legs"], indent=2, sort_keys=True))
    leg_one = manifest["legs"]["leg1_law_suspended_wall_rises"]["changed"]
    leg_two = manifest["legs"]["leg2_law_restored_wall_remains"]["changed"]
    if "walls" not in leg_one:
        print("motion story failed: leg 1 did not build the wall", file=sys.stderr)
        return 1
    if "walls" in leg_two:
        print("motion story failed: leg 2 must leave the wall standing", file=sys.stderr)
        return 1
    if leg_two.get("law_active", {}).get("after", {}).get(MOVEMENT_LAW_ID) is not True:
        print("motion story failed: leg 2 must restore the movement law", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
