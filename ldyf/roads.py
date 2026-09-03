"""Phase-2 lane L1 -- ``road_spec_v1``: the SUMO network as Unreal geometry.

DNA laws honoured in this module (lane brief):
  1. One transform authority. Every SUMO->Unreal coordinate here is produced by
     ``ldyf.coords.sumo_to_unreal``. The only scale constant used is the one
     imported from ``coords`` (``METRES_TO_UNREAL_UNITS``); it is never
     re-derived as a literal. No axis negation and no angle offset appear here.
  2. The visible road is the simulated road. ``source`` records the net payload
     sha256 via ``ldyf.sumo_record._sha256_payload`` and the net file name.
  3. No invented numbers. Lane width/speed/length, edge priority and the
     allow/disallow class lists are read from the net file attributes; an
     attribute that is absent becomes ``null`` in the spec, never a guessed
     default. Attribute *presence* is therefore decided on the XML attributes
     (sumolib may substitute defaults such as a lane width), while the object
     graph and all geometry come from ``sumolib`` objects parsed from the same
     file.
  4. Deterministic output. Edges and lanes are sorted by id, every float is
     rounded to 3 decimals (``_f3``, which also normalises ``-0.0``), and
     ``json.dumps(spec, indent=2, sort_keys=True)`` is used for serialising.
  5. Pure Python + sumolib. ``import sumolib`` happens lazily inside
     ``build_road_spec`` only, so this module imports without sumolib.

Coordinate conventions
----------------------
The spec's coordinates are Unreal centimetres (X east, Y south, Z up). Lane
shapes, junction positions and junction polygons are read in SUMO metres and
converted point-by-point with ``sumo_to_unreal``; ``lane.getShape()`` may
return 2D or 3D tuples (SUMO lane z is 0 in plain net files), and the default
``z_m=0.0`` used for 2D geometry is the declared default of
``lane_polyline_unreal``. Widths are metres converted to centimetres with the
imported scale constant; speeds and lengths stay in SUMO units (m/s, m), like
the simulation record keeps speed unconverted.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .coords import METRES_TO_UNREAL_UNITS, SumoPose, sumo_to_unreal
from .sumo_record import _sha256_payload

ROAD_SPEC_VERSION = "road_spec_v1"


# --- small deterministic helpers ------------------------------------------


def _f3(v: float) -> float:
    """Round to 3 decimals (cm resolution) and kill ``-0.0``.

    ``round(x, 3)`` can produce ``-0.0``; ``+ 0.0`` normalises it to ``0.0``
    so two builds of the same net are byte-identical in JSON.
    """
    return round(float(v), 3) + 0.0


def _int_or_none(s: str | None) -> int | None:
    if s is None or s == "":
        return None
    return int(s)


def _float_or_none(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    return _f3(float(s))


def _tokens(s: str | None) -> list[str] | None:
    """Split a space-separated class list; ``None`` attribute -> ``None``."""
    if s is None:
        return None
    return s.split()


def _call(obj: Any, name: str, default: Any = None) -> Any:
    """Call a zero-arg method if it exists; otherwise return ``default``.

    Guards against sumolib accessor surface differences across versions while
    staying deterministic: on failure the caller falls back to the raw XML
    attribute read from the same file, so the value is never invented.
    """
    fn = getattr(obj, name, None)
    if fn is None:
        return default
    try:
        return fn()
    except Exception:
        return default


def _point_xyz(p: Any, default_z: float) -> tuple[float, float, float]:
    """Normalise one SUMO shape point to (x, y, z) metres.

    sumolib shape entries may be 2-tuples, 3-tuples or complex numbers; a 2D
    entry takes the declared default z.
    """
    if isinstance(p, complex):
        return p.real, p.imag, default_z
    vals = tuple(float(v) for v in p)
    if len(vals) == 2:
        return vals[0], vals[1], default_z
    return vals[0], vals[1], vals[2]


# --- geometry helpers -----------------------------------------------------


def lane_polyline_unreal(
    shape_m: list[tuple[float, float]], z_m: float = 0.0
) -> list[dict]:
    """Convert a SUMO shape (metres) to an Unreal-centimetre point list.

    Every point goes through ``ldyf.coords.sumo_to_unreal`` -- the single
    transform authority. ``z_m`` is the metre z applied to 2D shape entries.
    """
    out: list[dict] = []
    for p in shape_m:
        x, y, z = _point_xyz(p, z_m)
        u = sumo_to_unreal(SumoPose(x=x, y=y, z=z, angle=0.0))
        out.append({"x": _f3(u.x), "y": _f3(u.y), "z": _f3(u.z)})
    return out


def _lerp(a: dict, b: dict, f: float) -> dict:
    """Linear interpolation between two centimetre points (x, y, z)."""
    return {
        "x": _f3(a["x"] + (b["x"] - a["x"]) * f),
        "y": _f3(a["y"] + (b["y"] - a["y"]) * f),
        "z": _f3(a["z"] + (b["z"] - a["z"]) * f),
    }


def resample_polyline(points_cm: list[dict], step_cm: float) -> list[dict]:
    """Arc-length resample of a polyline at ``step_cm`` spacing (2D x/y).

    Endpoints are preserved exactly. Interior points are placed at cumulative
    arc distance ``k * step_cm`` (a vertex that exactly coincides with a target
    distance is placed like any other point, unless it would duplicate the
    previously placed point), so consecutive interior spacing is ``step_cm`` to
    within floating point error; the final appended endpoint may sit closer
    than ``step_cm`` to the last interior point, by construction.
    """
    pts = [dict(p) for p in points_cm]
    if len(pts) < 2 or step_cm <= 0.0:
        return pts

    out: list[dict] = [dict(pts[0])]
    travelled = 0.0
    target = step_cm
    for a, b in zip(pts, pts[1:]):
        seg = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
        if seg <= 0.0:
            continue
        lo, hi = travelled, travelled + seg
        while target < hi - 1e-9:
            cand = _lerp(a, b, (target - lo) / seg)
            last = out[-1]
            if math.hypot(cand["x"] - last["x"], cand["y"] - last["y"]) > 1e-6:
                out.append(cand)
            target += step_cm
        travelled = hi
    out.append(dict(pts[-1]))
    return out


def _dist_point_segment_cm(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Perpendicular (clamped) distance from a point to a segment, 2D cm."""
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    if l2 <= 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / l2
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def centreline_error_cm(spec_polyline: list[dict], measured: list[dict]) -> dict:
    """Per-measured-point distance to the spec polyline, 2D x/y.

    Each measured point is projected onto every segment of the spec polyline
    (clamped to the segment) and the nearest distance is kept. Returns
    ``{"n", "max_cm", "mean_cm", "worst_index"}``; with no measured points
    ``worst_index`` is ``-1`` and the distances are ``0.0``.
    """
    segs = list(zip(spec_polyline, spec_polyline[1:]))
    errs: list[float] = []
    for m in measured:
        mx, my = m["x"], m["y"]
        if segs:
            d = min(
                _dist_point_segment_cm(
                    mx, my, a["x"], a["y"], b["x"], b["y"]
                )
                for a, b in segs
            )
        else:
            d = min(
                (math.hypot(mx - p["x"], my - p["y"]) for p in spec_polyline),
                default=0.0,
            )
        errs.append(d)
    if not errs:
        return {"n": 0, "max_cm": 0.0, "mean_cm": 0.0, "worst_index": -1}
    worst = max(errs)
    return {
        "n": len(errs),
        "max_cm": _f3(worst),
        "mean_cm": _f3(sum(errs) / len(errs)),
        "worst_index": errs.index(worst),
    }


def check_centrelines(
    spec: dict,
    measured_by_lane: dict[str, list[dict]],
    tolerance_cm: float = 5.0,
) -> dict:
    """Compare measured centreline points with the spec, lane by lane.

    A lane fails when any measured point is more than ``tolerance_cm`` from its
    spec polyline. Unknown lane ids raise ``KeyError`` rather than passing
    silently (a vacuous pass is not a pass).
    """
    lane_polylines: dict[str, list[dict]] = {}
    for e in spec["edges"]:
        for ln in e["lanes"]:
            lane_polylines[ln["id"]] = ln["polyline"]

    failed: list[str] = []
    worst = 0.0
    for lid in sorted(measured_by_lane):
        if lid not in lane_polylines:
            raise KeyError(f"lane {lid!r} not present in the road spec")
        err = centreline_error_cm(lane_polylines[lid], measured_by_lane[lid])
        if err["max_cm"] > tolerance_cm:
            failed.append(lid)
        worst = max(worst, err["max_cm"])
    return {
        "lanes_checked": len(measured_by_lane),
        "lanes_failed": sorted(failed),
        "worst_cm": _f3(worst),
        "pass": not failed,
    }


# --- raw net attributes (presence semantics + class tokens) ---------------


def _read_raw(path: Path) -> dict:
    """Read net-file attributes that decide ``null`` vs value and carry class
    tokens. Geometry stays with sumolib; this only mirrors presence so an
    absent attribute is never filled with a sumolib default."""
    root = ET.parse(path).getroot()
    edges: dict[str, dict] = {}
    junctions: dict[str, dict] = {}
    for e in root.findall("edge"):
        eid = e.get("id")
        lane_recs: dict[str, dict] = {}
        for l in e.findall("lane"):
            la = l.attrib
            lane_recs[la["id"]] = {
                "index": _int_or_none(la.get("index")),
                "width": _float_or_none(la.get("width")),
                "speed": _float_or_none(la.get("speed")),
                "length": _float_or_none(la.get("length")),
                "allow": _tokens(la.get("allow")),
                "disallow": _tokens(la.get("disallow")),
            }
        edges[eid] = {
            "from": e.get("from"),
            "to": e.get("to"),
            "function": e.get("function"),
            "priority": _int_or_none(e.get("priority")),
            "lanes": lane_recs,
        }
    for j in root.findall("junction"):
        ja = j.attrib
        junctions[ja["id"]] = {
            "type": ja.get("type"),
            "x": _float_or_none(ja.get("x")),
            "y": _float_or_none(ja.get("y")),
        }
    return {"edges": edges, "junctions": junctions}


# --- spec builder ---------------------------------------------------------


def build_road_spec(net_path: str | Path) -> dict:
    """Build the ``road_spec_v1`` dict from a SUMO net file.

    Requires sumolib (imported lazily, so this module imports without it).
    Internal edges are included and tagged ``function == "internal"``.
    """
    import sumolib  # the only place sumolib is required

    path = Path(net_path)
    net = sumolib.net.readNet(str(path), withInternal=True)
    raw = _read_raw(path)

    edges_out: list[dict] = []
    lane_total = 0
    point_total = 0

    edge_list = sorted(net.getEdges(withInternal=True), key=lambda e: e.getID())
    for edge in edge_list:
        eid = edge.getID()
        raw_e = raw["edges"].get(eid, {})
        raw_lanes = raw_e.get("lanes", {})
        from_node = _call(edge, "getFromNode")
        to_node = _call(edge, "getToNode")

        lanes_out: list[dict] = []
        lane_list = sorted(edge.getLanes(), key=lambda l: l.getID())
        for lane in lane_list:
            lid = lane.getID()
            rl = raw_lanes.get(lid, {})
            shape = _call(lane, "getShape", default=()) or ()
            polyline = lane_polyline_unreal(list(shape), z_m=0.0)
            width_cm = None
            if rl.get("width") is not None:
                width_cm = _f3(rl["width"] * METRES_TO_UNREAL_UNITS)
            lanes_out.append(
                {
                    "id": lid,
                    "index": rl.get("index"),
                    "width_cm": width_cm,
                    "speed_mps": rl.get("speed"),
                    "length_m": rl.get("length"),
                    "allow": rl.get("allow"),
                    "disallow": rl.get("disallow"),
                    "polyline": polyline,
                }
            )
            lane_total += 1
            point_total += len(polyline)

        edges_out.append(
            {
                "id": eid,
                "from_junction": (
                    from_node.getID() if from_node is not None else raw_e.get("from")
                ),
                "to_junction": (
                    to_node.getID() if to_node is not None else raw_e.get("to")
                ),
                "function": raw_e.get("function") or "normal",
                "priority": raw_e.get("priority"),
                "lanes": lanes_out,
            }
        )

    junctions_out: list[dict] = []
    raw_j = raw["junctions"]
    node_list = sorted(net.getNodes(), key=lambda n: n.getID())
    for node in node_list:
        jid = node.getID()
        rj = raw_j.get(jid, {})
        coord = _call(node, "getCoord")
        if coord is None:
            if rj.get("x") is not None and rj.get("y") is not None:
                coord = (rj["x"], rj["y"])
        position = None
        if coord is not None:
            position = lane_polyline_unreal([coord], z_m=0.0)[0]
        shape = _call(node, "getShape") or ()
        polygon = lane_polyline_unreal(list(shape), z_m=0.0) if shape else None
        jtype = _call(node, "getType") or rj.get("type")
        incoming = _call(node, "getIncoming", default=()) or ()
        junctions_out.append(
            {
                "id": jid,
                "type": jtype,
                "position": position,
                "polygon": polygon,
                "incoming_edge_ids": sorted(e.getID() for e in incoming),
            }
        )

    spec = {
        "schema_version": ROAD_SPEC_VERSION,
        "source": {
            "net_file": path.name,
            "net_payload_sha256": _sha256_payload(path),
            "transform_authority": "ldyf.coords",
        },
        "units": {"linear": "centimetres", "angular": "degrees"},
        "edges": edges_out,
        "junctions": junctions_out,
        "counts": {
            "edges": len(edges_out),
            "lanes": lane_total,
            "junctions": len(junctions_out),
            "polyline_points": point_total,
        },
    }
    return spec


def write_road_spec(net_path: str | Path, out_path: str | Path) -> dict:
    """Build the spec, write it as sorted, indented JSON, and return it."""
    spec = build_road_spec(net_path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2, sort_keys=True), encoding="utf-8")
    return spec
