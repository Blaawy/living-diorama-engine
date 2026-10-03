"""The locked world a factory episode runs against.

A world is a directory under `ldyf/factory/worlds/` holding the SUMO inputs and
a `world.json` that pins each of them by sha256. `load_world` refuses a world
whose files do not match their pins: "the locked Phase 3 world" is a claim
about bytes, so it is checked as one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import FactoryError
from .util import read_json, sha256_file

WORLD_SCHEMA = "factory_world_v1"
WORLDS_DIR = Path(__file__).resolve().parent / "worlds"
REPO_ROOT = Path(__file__).resolve().parents[2]


class WorldError(FactoryError):
    stage = "world"


def load_world(name: str, *, worlds_dir: str | Path | None = None) -> dict[str, Any]:
    """Load and VERIFY a world. Returns the document plus resolved paths."""
    if not isinstance(name, str) or not name.isidentifier():
        raise WorldError("bad_name", f"world name must be a plain identifier, got {name!r}")
    base = Path(worlds_dir or WORLDS_DIR) / name
    doc = read_json(base / "world.json", f"world {name!r}", error=WorldError)
    if not isinstance(doc, dict):
        raise WorldError("corrupt", f"world {name!r}: world.json is not a JSON object")
    if doc.get("schema_version") != WORLD_SCHEMA:
        raise WorldError("bad_version", f"world {name!r} declares {doc.get('schema_version')!r}, "
                                        f"this factory reads {WORLD_SCHEMA}")
    if doc.get("name") != name:
        raise WorldError("name_mismatch", f"world.json in {name!r} names itself {doc.get('name')!r}")
    out = dict(doc)
    try:
        pinned = [("net", doc["net"])] + [("route", r) for r in doc["routes"]]
        for _what, pin in pinned:
            if not isinstance(pin["file"], str) or not isinstance(pin["sha256"], str) \
                    or Path(pin["file"]).name != pin["file"]:
                raise TypeError("a pin is {file: <plain file name>, sha256}")
        for key in ("sumo", "agents", "unreal"):
            if not isinstance(doc[key], dict):
                raise TypeError(f"{key} must be an object")
    except (KeyError, TypeError) as e:
        raise WorldError("corrupt", f"world {name!r}: world.json does not pin its inputs: {e!r}")
    for what, pin in pinned:
        p = base / pin["file"]
        if not p.is_file():
            raise WorldError("missing_input", f"world {name!r}: {what} file {pin['file']} is missing")
        have = sha256_file(p)
        if have != pin["sha256"]:
            raise WorldError(
                "world_not_locked",
                f"world {name!r}: {pin['file']} hashes to {have[:16]}.. but the locked world "
                f"pins {pin['sha256'][:16]}..; refusing to simulate an unlocked world")
    out["_dir"] = str(base)
    out["_net_path"] = str(base / doc["net"]["file"])
    out["_route_paths"] = [str(base / r["file"]) for r in doc["routes"]]
    return out


def twin_edge(edge_id: str, net: Any) -> str | None:
    """The opposite direction of the same street, read from the NETWORK.

    Not string surgery on the id: the twin is the edge that runs between the
    same two junctions the other way, whatever it is called.
    """
    e = net.getEdge(edge_id)
    a, b = e.getFromNode().getID(), e.getToNode().getID()
    for cand in net.getEdges():
        if cand.getFromNode().getID() == b and cand.getToNode().getID() == a:
            return cand.getID()
    return None


def street_name(edge_id: str, world: dict[str, Any], net: Any) -> dict[str, str]:
    """A sayable name for an edge: the street it lies on and the two it runs between.

    PRESENTATION ONLY -- see `street_names.note` in world.json. Returns
    `{"street": .., "from": .., "to": ..}`; refuses an edge the naming table
    cannot name rather than inventing one.
    """
    names = world.get("street_names") or {}
    cols, rows = names.get("columns") or {}, names.get("rows") or {}
    e = net.getEdge(edge_id)
    a, b = e.getFromNode().getID(), e.getToNode().getID()
    if len(a) != 2 or len(b) != 2:
        raise WorldError("unnameable", f"edge {edge_id!r} runs between junctions {a!r}, {b!r} "
                                       "which the naming table cannot name")
    try:
        if a[0] == b[0]:          # same column: along an avenue, between two streets
            return {"street": cols[a[0]], "from": rows[a[1]], "to": rows[b[1]]}
        if a[1] == b[1]:          # same row: along a street, between two avenues
            return {"street": rows[a[1]], "from": cols[a[0]], "to": cols[b[0]]}
    except KeyError as k:
        raise WorldError("unnameable", f"edge {edge_id!r}: no name for {k}")
    raise WorldError("unnameable", f"edge {edge_id!r} is neither along a column nor a row")
