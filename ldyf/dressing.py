"""``dressing_v1`` — the road furniture a real street has, derived from the SUMO
network and nothing else.

Everything here is pure stdlib Python and deterministic: no randomness, no
wall clock, no editor. The editor module ``ldyf.unreal.ldyf_dressing_editor``
consumes this document and spawns meshes; the road-geometry checker can
re-measure what was spawned against this same document.

What is derived, and from what
------------------------------
``lane_markings``      From each ``function == "normal"`` edge's car lanes
                       (a car lane is one that disallows ``pedestrian``).
                       The lateral direction ``n`` is **measured** from the
                       lane geometry — the vector from the lowest-index car
                       lane to the highest-index one, projected onto the
                       segment normal — never assumed from an axis. Then:

                       * ``edge_line``   solid white on the kerb side of the
                         lowest-index car lane (its outer boundary).
                       * ``lane_divider`` dashed white on every boundary
                         between two adjacent car lanes.
                       * ``centre_line`` solid yellow just inside the
                         highest-index car lane's inner boundary, pulled back
                         by ``double_gap_cm / 2`` so that this edge's line and
                         its reverse edge's line form one double yellow line
                         instead of two coincident lines that z-fight.

``crosswalk_stripes``  From ``function == "crossing"`` edges. The crossing's
                       own axis (its polyline) spans the carriageway; stripes
                       run perpendicular to it, i.e. along the direction cars
                       travel, which is what a zebra crossing looks like.

``signal_placements``  One traffic light per incoming normal edge at every
                       junction whose SUMO ``type`` is ``traffic_light``.
                       Placed on the kerb side, set back from the junction,
                       facing back down the approach so drivers see the face.
                       Junctions typed ``priority`` get a stop sign instead —
                       that is what SUMO says is there.

``tree_slots``         Along each sidewalk lane, offset to the back of the
                       pavement, at a spacing and phase distinct from the
                       ``city_layout`` furniture slots so trees and lamp posts
                       do not land on the same spot.

``closure_props``      Barricades and cones across the car lanes of the edges
                       the sealed rule manifest closes, at the junction end of
                       each. This is what makes the closure *visible* rather
                       than only inferable from traffic behaviour.

Determinism laws (same as ``ldyf.roads`` / ``ldyf.city_layout``): every float
is rounded through ``_f3`` (which also removes ``-0.0``), iteration is over
ids sorted lexicographically, and JSON is written with
``json.dumps(..., indent=2, sort_keys=True)``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

DRESSING_VERSION = "dressing_v1"

# Defaults are ordinary road-marking dimensions in centimetres. They are
# arguments, not constants of the world: every caller may override them and
# the values used are written into the document's ``params`` block.
DEFAULT_LINE_WIDTH_CM = 12.0
DEFAULT_DASH_LEN_CM = 300.0
DEFAULT_DASH_GAP_CM = 500.0
DEFAULT_DOUBLE_GAP_CM = 20.0
DEFAULT_STRIPE_WIDTH_CM = 45.0
DEFAULT_STRIPE_GAP_CM = 45.0
DEFAULT_SIGNAL_SETBACK_CM = 250.0
DEFAULT_TREE_SPACING_CM = 4000.0
DEFAULT_TREE_PHASE_CM = 1250.0


def _f3(v: float) -> float:
    """Round to 3 decimals and normalise ``-0.0`` to ``0.0``."""
    r = round(float(v), 3)
    return 0.0 if r == 0.0 else r


def _unit(dx: float, dy: float) -> tuple[float, float]:
    n = math.hypot(dx, dy)
    if n == 0.0:
        return (0.0, 0.0)
    return (dx / n, dy / n)


def _yaw_deg(dx: float, dy: float) -> float:
    return _f3(math.degrees(math.atan2(dy, dx)))


def _pts(lane: dict) -> list[tuple[float, float]]:
    return [(float(p["x"]), float(p["y"])) for p in lane["polyline"]]


def _polyline_length(pts: Sequence[tuple[float, float]]) -> float:
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def _point_at(pts: Sequence[tuple[float, float]], s: float) -> tuple[float, float, float, float]:
    """Point and unit direction at arc length ``s`` along a polyline."""
    if len(pts) < 2:
        return (pts[0][0], pts[0][1], 1.0, 0.0)
    acc = 0.0
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        seg = math.dist(a, b)
        if seg <= 0.0:
            continue
        if acc + seg >= s or i == len(pts) - 2:
            t = (s - acc) / seg
            t = max(0.0, min(1.0, t))
            ux, uy = _unit(b[0] - a[0], b[1] - a[1])
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, ux, uy)
        acc += seg
    last = pts[-1]
    ux, uy = _unit(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
    return (last[0], last[1], ux, uy)


def _mid(pts: Sequence[tuple[float, float]]) -> tuple[float, float]:
    x, y, _ux, _uy = _point_at(pts, _polyline_length(pts) / 2.0)
    return (x, y)


def is_car_lane(lane: dict) -> bool:
    """A lane cars drive on: it explicitly disallows pedestrians.

    This is how the SUMO network distinguishes a carriageway lane from the
    sidewalk lane the same edge carries; ``ldyf.roads`` preserves the raw
    ``allow``/``disallow`` lists precisely so this stays a read, not a guess.
    """
    dis = lane.get("disallow") or []
    return "pedestrian" in dis


def is_sidewalk_lane(lane: dict) -> bool:
    allow = lane.get("allow") or []
    return "pedestrian" in allow


def normal_edges(spec: dict) -> list[dict]:
    return sorted((e for e in spec["edges"] if e.get("function") == "normal"),
                  key=lambda e: str(e["id"]))


def _car_lanes(edge: dict) -> list[dict]:
    return sorted((ln for ln in edge["lanes"] if is_car_lane(ln)), key=lambda ln: int(ln["index"]))


def _sidewalk_lanes(edge: dict) -> list[dict]:
    return sorted((ln for ln in edge["lanes"] if is_sidewalk_lane(ln)), key=lambda ln: int(ln["index"]))


def lateral_normal(edge: dict) -> tuple[float, float] | None:
    """The unit vector along which a car lane's *index increases*.

    Measured, not assumed. The direction is the segment normal of the edge,
    with its sign taken from where the lanes actually are: the vector from the
    lowest-index car lane's midpoint to the highest-index one's must have a
    positive component along it. With a single car lane the sidewalk lane
    supplies the sign (car lanes are inboard of the pavement). Returns
    ``None`` when neither is available, and the caller skips the edge rather
    than inventing a side.
    """
    cars = _car_lanes(edge)
    if not cars:
        return None
    pts = _pts(cars[0])
    if len(pts) < 2:
        return None
    ux, uy = _unit(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
    if (ux, uy) == (0.0, 0.0):
        return None
    n = (uy, -ux)                      # one of the two perpendiculars
    if len(cars) >= 2:
        a, b = _mid(_pts(cars[0])), _mid(_pts(cars[-1]))
        ref = (b[0] - a[0], b[1] - a[1])
    else:
        walks = _sidewalk_lanes(edge)
        if not walks:
            return None
        a, b = _mid(_pts(walks[0])), _mid(_pts(cars[0]))
        ref = (b[0] - a[0], b[1] - a[1])
    dot = ref[0] * n[0] + ref[1] * n[1]
    if dot == 0.0:
        return None
    return n if dot > 0 else (-n[0], -n[1])


def _offset_polyline(pts: Sequence[tuple[float, float]], n: tuple[float, float],
                     d: float) -> list[tuple[float, float]]:
    return [(p[0] + n[0] * d, p[1] + n[1] * d) for p in pts]


def _dash(pts: Sequence[tuple[float, float]], dash_len: float, gap: float
          ) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Split a polyline into dashes of ``dash_len`` separated by ``gap``.

    The pattern starts at ``s = 0``; a final dash is truncated rather than
    dropped only when at least a quarter of it fits, so a short lane still
    reads as dashed instead of blank.
    """
    total = _polyline_length(pts)
    out: list[tuple[tuple[float, float], tuple[float, float]]] = []
    if total <= 0.0 or dash_len <= 0.0:
        return out
    s = 0.0
    while s < total:
        e = min(s + dash_len, total)
        if e - s >= dash_len * 0.25:
            x0, y0, _a, _b = _point_at(pts, s)
            x1, y1, _c, _d = _point_at(pts, e)
            out.append(((x0, y0), (x1, y1)))
        s = e + gap
    return out


def _line_row(seg_id: str, kind: str, colour: str, a: tuple[float, float],
              b: tuple[float, float], width_cm: float, edge_id: str) -> dict:
    dx, dy = b[0] - a[0], b[1] - a[1]
    return {
        "id": seg_id,
        "kind": kind,
        "colour": colour,
        "edge_id": edge_id,
        "x0": _f3(a[0]), "y0": _f3(a[1]),
        "x1": _f3(b[0]), "y1": _f3(b[1]),
        "centre_x": _f3((a[0] + b[0]) / 2.0),
        "centre_y": _f3((a[1] + b[1]) / 2.0),
        "length_cm": _f3(math.hypot(dx, dy)),
        "width_cm": _f3(width_cm),
        "yaw": _yaw_deg(dx, dy),
    }


def lane_markings(spec: dict, *,
                  line_width_cm: float = DEFAULT_LINE_WIDTH_CM,
                  dash_len_cm: float = DEFAULT_DASH_LEN_CM,
                  dash_gap_cm: float = DEFAULT_DASH_GAP_CM,
                  double_gap_cm: float = DEFAULT_DOUBLE_GAP_CM) -> list[dict]:
    """Every painted line on the carriageway, derived from the lane geometry."""
    rows: list[dict] = []
    for edge in normal_edges(spec):
        cars = _car_lanes(edge)
        n = lateral_normal(edge)
        if not cars or n is None:
            continue
        eid = str(edge["id"])
        # kerb-side edge line: outer boundary of the lowest-index car lane
        w0 = float(cars[0]["width_cm_effective"])
        outer = _offset_polyline(_pts(cars[0]), n, -w0 / 2.0)
        for i in range(len(outer) - 1):
            rows.append(_line_row(f"{eid}|edge|{i}", "edge_line", "white",
                                  outer[i], outer[i + 1], line_width_cm, eid))
        # dashed dividers between adjacent car lanes
        for k in range(len(cars) - 1):
            wk = float(cars[k]["width_cm_effective"])
            bound = _offset_polyline(_pts(cars[k]), n, wk / 2.0)
            for i, (a, b) in enumerate(_dash(bound, dash_len_cm, dash_gap_cm)):
                rows.append(_line_row(f"{eid}|divider{k}|{i}", "lane_divider", "white",
                                      a, b, line_width_cm, eid))
        # centre line: inner boundary of the highest-index car lane, pulled
        # back by half the double-line gap so this edge and its reverse make
        # one double yellow line rather than two coincident lines.
        wl = float(cars[-1]["width_cm_effective"])
        inner = _offset_polyline(_pts(cars[-1]), n, wl / 2.0 - double_gap_cm / 2.0)
        for i in range(len(inner) - 1):
            rows.append(_line_row(f"{eid}|centre|{i}", "centre_line", "yellow",
                                  inner[i], inner[i + 1], line_width_cm, eid))
    return sorted(rows, key=lambda r: r["id"])


def crossing_edges(spec: dict) -> list[dict]:
    return sorted((e for e in spec["edges"] if e.get("function") == "crossing"),
                  key=lambda e: str(e["id"]))


def crosswalk_stripes(spec: dict, *,
                      stripe_width_cm: float = DEFAULT_STRIPE_WIDTH_CM,
                      stripe_gap_cm: float = DEFAULT_STRIPE_GAP_CM) -> list[dict]:
    """Zebra stripes on every SUMO crossing.

    The crossing lane's polyline spans the carriageway; its own width (SUMO's
    ``width`` attribute, 4.0 m in the proof network) is how deep the crossing
    is along the direction cars travel. Stripes therefore run along that depth
    and repeat along the span, which is what a zebra crossing is.
    """
    rows: list[dict] = []
    for edge in crossing_edges(spec):
        eid = str(edge["id"])
        for lane in sorted(edge["lanes"], key=lambda ln: int(ln["index"])):
            pts = _pts(lane)
            if len(pts) < 2:
                continue
            span = _polyline_length(pts)
            depth = float(lane["width_cm_effective"])
            pitch = stripe_width_cm + stripe_gap_cm
            if pitch <= 0.0 or span <= 0.0:
                continue
            count = int(span // pitch)
            if count <= 0:
                continue
            used = count * pitch - stripe_gap_cm
            start = (span - used) / 2.0
            for i in range(count):
                s = start + i * pitch + stripe_width_cm / 2.0
                x, y, ux, uy = _point_at(pts, s)
                rows.append({
                    "id": f"{eid}|{lane['index']}|{i}",
                    "edge_id": eid,
                    "lane_id": str(lane["id"]),
                    "x": _f3(x), "y": _f3(y),
                    "yaw": _yaw_deg(ux, uy),
                    "size_along_cm": _f3(stripe_width_cm),
                    "size_across_cm": _f3(depth),
                })
    return sorted(rows, key=lambda r: r["id"])


def signal_placements(spec: dict, *,
                      setback_cm: float = DEFAULT_SIGNAL_SETBACK_CM) -> list[dict]:
    """A traffic light (or stop sign) for every approach into every junction.

    ``kind`` follows SUMO's junction ``type``: ``traffic_light`` junctions get
    ``traffic_light``, ``priority`` junctions get ``stop_sign``. Anything else
    is skipped and counted, never silently turned into a signal.
    """
    by_to: dict[str, list[dict]] = {}
    for edge in normal_edges(spec):
        by_to.setdefault(str(edge.get("to_junction")), []).append(edge)
    rows: list[dict] = []
    for j in sorted(spec["junctions"], key=lambda j: str(j["id"])):
        jid = str(j["id"])
        jtype = str(j.get("type"))
        if jtype == "traffic_light":
            kind = "traffic_light"
        elif jtype == "priority":
            kind = "stop_sign"
        else:
            continue
        for edge in sorted(by_to.get(jid, []), key=lambda e: str(e["id"])):
            cars = _car_lanes(edge)
            n = lateral_normal(edge)
            if not cars or n is None:
                continue
            pts = _pts(cars[0])
            total = _polyline_length(pts)
            s = max(0.0, total - setback_cm)
            x, y, ux, uy = _point_at(pts, s)
            w0 = float(cars[0]["width_cm_effective"])
            lat = -(w0 / 2.0 + 120.0)          # onto the kerb, clear of the lane
            rows.append({
                "id": f"{jid}|{edge['id']}",
                "junction_id": jid,
                "junction_type": jtype,
                "edge_id": str(edge["id"]),
                "kind": kind,
                "x": _f3(x + n[0] * lat),
                "y": _f3(y + n[1] * lat),
                # faces back down the approach, so a driver on this edge sees it
                "yaw": _yaw_deg(-ux, -uy),
            })
    return sorted(rows, key=lambda r: r["id"])


def tree_slots(spec: dict, *,
               spacing_cm: float = DEFAULT_TREE_SPACING_CM,
               phase_cm: float = DEFAULT_TREE_PHASE_CM,
               back_offset_cm: float = 70.0) -> list[dict]:
    """Street trees along the back of every sidewalk lane.

    The phase is deliberately different from ``city_layout.furniture_slots``
    (which starts at its own spacing) so a tree and a lamp post never occupy
    the same point on the pavement.
    """
    rows: list[dict] = []
    for edge in normal_edges(spec):
        n = lateral_normal(edge)
        if n is None:
            continue
        for lane in _sidewalk_lanes(edge):
            pts = _pts(lane)
            if len(pts) < 2:
                continue
            total = _polyline_length(pts)
            w = float(lane["width_cm_effective"])
            # the sidewalk is on the -n side of the carriageway, so its own
            # far edge (away from the road) is a further -n step
            lat = -(w / 2.0 - back_offset_cm)
            s = phase_cm
            i = 0
            while s < total:
                x, y, ux, uy = _point_at(pts, s)
                rows.append({
                    "id": f"{lane['id']}|tree|{i}",
                    "lane_id": str(lane["id"]),
                    "edge_id": str(edge["id"]),
                    "distance_cm": _f3(s),
                    "x": _f3(x + n[0] * lat),
                    "y": _f3(y + n[1] * lat),
                    "yaw": _yaw_deg(ux, uy),
                })
                s += spacing_cm
                i += 1
    return sorted(rows, key=lambda r: r["id"])


def closure_props(spec: dict, closed_edge_ids: Iterable[str], *,
                  setback_cm: float = 400.0,
                  cone_spacing_cm: float = 160.0) -> list[dict]:
    """Barricades and cones across each closed edge, at its junction end.

    One barricade spanning the carriageway plus a row of cones on the same
    line. Cone count follows the measured carriageway width, so a wider road
    gets more cones without anyone typing a number.
    """
    edges = {str(e["id"]): e for e in spec["edges"]}
    rows: list[dict] = []
    for eid in sorted({str(e) for e in closed_edge_ids}):
        edge = edges.get(eid)
        if edge is None or edge.get("function") != "normal":
            continue
        cars = _car_lanes(edge)
        n = lateral_normal(edge)
        if not cars or n is None:
            continue
        pts = _pts(cars[0])
        total = _polyline_length(pts)
        s = max(0.0, total - setback_cm)
        x, y, ux, uy = _point_at(pts, s)
        w0 = float(cars[0]["width_cm_effective"])
        # span from the outer boundary of lane 0 to the inner boundary of the last
        wl = float(cars[-1]["width_cm_effective"])
        a_off = -w0 / 2.0
        far = _point_at(_pts(cars[-1]), min(_polyline_length(_pts(cars[-1])), s))
        b_off = wl / 2.0
        ax, ay = x + n[0] * a_off, y + n[1] * a_off
        bx, by = far[0] + n[0] * b_off, far[1] + n[1] * b_off
        span = math.hypot(bx - ax, by - ay)
        rows.append({
            "id": f"{eid}|barricade",
            "edge_id": eid,
            "kind": "barricade",
            "x": _f3((ax + bx) / 2.0), "y": _f3((ay + by) / 2.0),
            "yaw": _yaw_deg(bx - ax, by - ay),
            "span_cm": _f3(span),
        })
        count = max(2, int(span // cone_spacing_cm) + 1)
        for i in range(count):
            t = i / (count - 1) if count > 1 else 0.5
            rows.append({
                "id": f"{eid}|cone|{i}",
                "edge_id": eid,
                "kind": "cone",
                "x": _f3(ax + (bx - ax) * t),
                "y": _f3(ay + (by - ay) * t),
                "yaw": _yaw_deg(-ux, -uy),
                "span_cm": _f3(span),
            })
    return sorted(rows, key=lambda r: r["id"])


def build_dressing(spec: dict, *, closed_edge_ids: Sequence[str] = (),
                   line_width_cm: float = DEFAULT_LINE_WIDTH_CM,
                   dash_len_cm: float = DEFAULT_DASH_LEN_CM,
                   dash_gap_cm: float = DEFAULT_DASH_GAP_CM,
                   double_gap_cm: float = DEFAULT_DOUBLE_GAP_CM,
                   stripe_width_cm: float = DEFAULT_STRIPE_WIDTH_CM,
                   stripe_gap_cm: float = DEFAULT_STRIPE_GAP_CM,
                   signal_setback_cm: float = DEFAULT_SIGNAL_SETBACK_CM,
                   tree_spacing_cm: float = DEFAULT_TREE_SPACING_CM,
                   tree_phase_cm: float = DEFAULT_TREE_PHASE_CM) -> dict[str, Any]:
    """The whole ``dressing_v1`` document."""
    markings = lane_markings(spec, line_width_cm=line_width_cm, dash_len_cm=dash_len_cm,
                             dash_gap_cm=dash_gap_cm, double_gap_cm=double_gap_cm)
    stripes = crosswalk_stripes(spec, stripe_width_cm=stripe_width_cm,
                                stripe_gap_cm=stripe_gap_cm)
    signals = signal_placements(spec, setback_cm=signal_setback_cm)
    trees = tree_slots(spec, spacing_cm=tree_spacing_cm, phase_cm=tree_phase_cm)
    closure = closure_props(spec, closed_edge_ids)
    kinds: dict[str, int] = {}
    for r in markings:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    sig_kinds: dict[str, int] = {}
    for r in signals:
        sig_kinds[r["kind"]] = sig_kinds.get(r["kind"], 0) + 1
    return {
        "schema_version": DRESSING_VERSION,
        "params": {
            "line_width_cm": _f3(line_width_cm),
            "dash_len_cm": _f3(dash_len_cm),
            "dash_gap_cm": _f3(dash_gap_cm),
            "double_gap_cm": _f3(double_gap_cm),
            "stripe_width_cm": _f3(stripe_width_cm),
            "stripe_gap_cm": _f3(stripe_gap_cm),
            "signal_setback_cm": _f3(signal_setback_cm),
            "tree_spacing_cm": _f3(tree_spacing_cm),
            "tree_phase_cm": _f3(tree_phase_cm),
            "closed_edge_ids": sorted({str(e) for e in closed_edge_ids}),
        },
        "counts": {
            "markings": len(markings),
            "markings_by_kind": kinds,
            "crosswalk_stripes": len(stripes),
            "signals": len(signals),
            "signals_by_kind": sig_kinds,
            "trees": len(trees),
            "closure_props": len(closure),
        },
        "lane_markings": markings,
        "crosswalk_stripes": stripes,
        "signals": signals,
        "trees": trees,
        "closure_props": closure,
    }


def write_dressing(doc: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    return p
