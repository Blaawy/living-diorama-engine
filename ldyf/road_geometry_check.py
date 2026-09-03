"""C4 road geometry proof -- pure checker over a component snapshot.

Consumes the snapshot the in-editor sampler (``ldyf/unreal/ldyf_road_sampler.py``)
produces from SPAWNED components and compares it against the independent SUMO
input ``road_spec_v1`` (``ldyf/roads.py``), exactly as C4 (
``docs_CONTRACTS_P2_CLOSURE.md`` lines 55-62) demands: centreline error via
``roads.centreline_error_cm``, width ``|scale_y * mesh_width - width_cm_effective|``,
junction slab bbox coverage + ``|slab_top - strip_top|`` z continuity, ground
coverage, all under the 5 cm law (tolerances are arguments).

Snapshot schema (draft, written by the in-editor sampler)
----------------------------------------------------------
``strips``: lane strips. ``lane_id`` may be null (PCG tags absent) and is then
recovered by ``match_strip_to_lane`` (midpoint, 2-D). ``mesh_width_cm`` is the
MEASURED cross-section width of the mesh (a measured asset property, never
typed here); ``start_scale_y``/``end_scale_y`` are the cross-section spline-mesh
scales read from the spawned component.
``slabs``: junction fill dynamic meshes (bbox + top z).
``ground``: the base surface under the roads (bbox + top z).

Determinism laws
----------------
Pure stdlib; outputs rounded (3 decimals for cm, 6 for fractions, ``+0.0`` to
kill ``-0.0``) and ``json.dumps(indent=2, sort_keys=True)`` on write, so two
runs over one snapshot are byte-identical. Lanes are iterated sorted by id.
Only 2-D (x/y) geometry is compared for centreline/coverage/bbox checks: z is
a placement fact compared only as ``top_z`` continuity (``|slab_top-strip_top|``,
``ground top below strip top``).

Scope
-----
Lane rows cover edges whose ``function`` is absent or ``normal`` -- the lanes
the road graph actually builds as strips (``ldyf_roads_editor.py:93-101``);
junction-internal lanes are covered by slabs and are checked by
``check_junctions``. A strip carrying a ``lane_id`` that is not a normal spec
lane raises ``KeyError`` (roads.py:232-233 law: an unknown lane must never pass
silently). A strip whose midpoint is further than ``match_max_cm`` from every
lane is *unmatched* and fails the checks: it is spawned geometry the proof
cannot attribute to the SUMO input. The match bound defaults to 50 cm: lanes
are at least ~3.2 m (SUMO width default) apart centre-to-centre, and 50 cm
keeps a strip that breaks the 5 cm law by 6 cm still attributable to its lane
(so it FAILS on centreline error instead of vanishing into "unmatched").
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .roads import centreline_error_cm

ROAD_GEOMETRY_VERSION = "road_geometry_v1"

# Midpoint-to-lane match bound (cm); see module docstring. Lanes are >= ~320 cm
# apart, so 50 cm never attributes across lanes.
_MATCH_MAX_CM = 50.0


def _r3(v: float) -> float:
    """Round to 3 decimals (cm resolution) and normalise ``-0.0``."""
    return round(float(v), 3) + 0.0


def _r6(v: float) -> float:
    """Round a fraction to 6 decimals and normalise ``-0.0``."""
    return round(float(v), 6) + 0.0


# --- spec helpers ----------------------------------------------------------


def _normal_lanes(spec: dict) -> dict[str, dict]:
    """Sorted id -> lane record for edges with function absent or "normal"."""
    out: dict[str, dict] = {}
    for e in spec.get("edges") or []:
        if (e.get("function") or "normal") != "normal":
            continue
        for ln in e.get("lanes") or []:
            poly = ln.get("polyline")
            if poly and len(poly) >= 2:
                out[str(ln["id"])] = ln
    return dict(sorted(out.items()))


def _polyline_length(poly: list[dict]) -> float:
    """2-D arc length of a polyline in cm."""
    return sum(
        math.hypot(b["x"] - a["x"], b["y"] - a["y"]) for a, b in zip(poly, poly[1:])
    )


def _arc_table(poly: list[dict]) -> tuple[list[float], float]:
    """Per-vertex cumulative arc length; total arc length last."""
    pref = [0.0]
    for a, b in zip(poly, poly[1:]):
        pref.append(pref[-1] + math.hypot(b["x"] - a["x"], b["y"] - a["y"]))
    return pref, pref[-1]


def _project_arc(px: float, py: float, poly: list[dict], pref: list[float]):
    """Nearest point on the polyline: (distance_cm, arc_position_cm).

    Clamped per segment (the same projection roads.py uses); ties break on the
    smaller arc position so the result is deterministic.
    """
    best_d: float | None = None
    best_s: float | None = None
    for i in range(len(poly) - 1):
        a, b = poly[i], poly[i + 1]
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        l2 = dx * dx + dy * dy
        if l2 <= 0.0:
            t = 0.0
        else:
            t = ((px - a["x"]) * dx + (py - a["y"]) * dy) / l2
            t = min(1.0, max(0.0, t))
        cx, cy = a["x"] + t * dx, a["y"] + t * dy
        d = math.hypot(px - cx, py - cy)
        s = pref[i] + t * math.hypot(dx, dy)
        if best_d is None or d < best_d - 1e-9 or (abs(d - best_d) <= 1e-9 and s < best_s):
            best_d, best_s = d, s
    return best_d, best_s


def _merge_intervals(ivs: list[tuple[float, float]]) -> list[list[float]]:
    merged: list[list[float]] = []
    for lo, hi in sorted(ivs):
        if not merged or lo > merged[-1][1] + 1e-6:
            merged.append([lo, hi])
        else:
            merged[-1][1] = max(merged[-1][1], hi)
    return merged


# --- public strip / matching helpers ---------------------------------------


def strip_centreline(strip: dict) -> list[dict]:
    """The strip's centreline as a segment: ``[start, end]`` (copies)."""
    return [dict(strip["start"]), dict(strip["end"])]


def _midpoint(strip: dict) -> dict:
    a, b = strip["start"], strip["end"]
    return {
        "x": (a["x"] + b["x"]) / 2.0,
        "y": (a["y"] + b["y"]) / 2.0,
        "z": (a["z"] + b["z"]) / 2.0,
    }


def match_strip_to_lane(strip: dict, spec: dict, *, max_cm: float) -> str | None:
    """Nearest normal lane polyline (2-D) to the strip midpoint within max_cm."""
    mid = _midpoint(strip)
    best_id: str | None = None
    best_d: float | None = None
    for lid, ln in _normal_lanes(spec).items():
        d = centreline_error_cm(ln["polyline"], [mid])["max_cm"]
        if best_d is None or d < best_d:
            best_d, best_id = d, lid
    if best_id is None or best_d is None or best_d > max_cm:
        return None
    return best_id


def _strip_lane(strip: dict, spec: dict, *, match_max_cm: float = _MATCH_MAX_CM) -> str | None:
    """Attribution: declared lane_id wins; else midpoint match. Unknown lane id
    raises KeyError (a lane that exists nowhere must not pass silently)."""
    lanes = _normal_lanes(spec)
    lid = strip.get("lane_id")
    if lid is not None:
        lid = str(lid)
        if lid not in lanes:
            raise KeyError(f"strip lane_id {lid!r} is not a normal lane of the road spec")
        return lid
    return match_strip_to_lane(strip, spec, max_cm=match_max_cm)


# --- checks ----------------------------------------------------------------


def check_centrelines(snapshot: dict, spec: dict, *, tol_cm: float = 5.0,
                      match_max_cm: float = _MATCH_MAX_CM) -> dict:
    """Per normal lane: max distance of strip endpoints/midpoint to the lane
    polyline (``roads.centreline_error_cm``, 2-D) and coverage = fraction of
    the lane's arc length covered by its strips (union of projected intervals).
    A lane fails when its centreline error exceeds tol_cm or its strips leave
    more than tol_cm of arc uncovered. Unattributable strips fail too.
    """
    lanes = _normal_lanes(spec)
    measured: dict[str, list[dict]] = {lid: [] for lid in lanes}
    intervals: dict[str, list[tuple[float, float]]] = {lid: [] for lid in lanes}
    strip_count: dict[str, int] = {lid: 0 for lid in lanes}
    unmatched: list[int] = []
    for i, strip in enumerate(snapshot.get("strips") or []):
        lid = _strip_lane(strip, spec, match_max_cm=match_max_cm)
        if lid is None:
            unmatched.append(i)
            continue
        poly = lanes[lid]["polyline"]
        measured[lid] += [dict(strip["start"]), dict(_midpoint(strip)), dict(strip["end"])]
        strip_count[lid] += 1
        pref, length = _arc_table(poly)
        if length > 0.0:
            sa = _project_arc(strip["start"]["x"], strip["start"]["y"], poly, pref)[1]
            sb = _project_arc(strip["end"]["x"], strip["end"]["y"], poly, pref)[1]
            intervals[lid].append((min(sa, sb), max(sa, sb)))

    per_lane: dict[str, dict] = {}
    failed: list[str] = []
    uncovered: list[str] = []
    worst_cm = 0.0
    worst_lane: str | None = None
    for lid in sorted(lanes):
        poly = lanes[lid]["polyline"]
        err = centreline_error_cm(poly, measured[lid])
        pref, length = _arc_table(poly)
        if length > 0.0:
            covered_len = sum(hi - lo for lo, hi in _merge_intervals(intervals[lid]))
            coverage = min(1.0, covered_len / length)
            gap_cm = max(0.0, length - covered_len)
        else:
            coverage = 1.0 if strip_count[lid] else 0.0
            gap_cm = 0.0
        is_covered = gap_cm <= tol_cm + 1e-6
        centreline_ok = err["max_cm"] <= tol_cm + 1e-6
        if not is_covered:
            uncovered.append(lid)
        if not (is_covered and centreline_ok):
            failed.append(lid)
        if err["n"] > 0 and err["max_cm"] > worst_cm:
            worst_cm = err["max_cm"]
            worst_lane = lid
        per_lane[lid] = {
            "strips": strip_count[lid],
            "measured_points": err["n"],
            "centreline_max_cm": _r3(err["max_cm"]),
            "centreline_mean_cm": _r3(err["mean_cm"]),
            "coverage": _r6(coverage),
            "uncovered_gap_cm": _r3(gap_cm),
            "centreline_pass": centreline_ok,
            "covered": is_covered,
            "pass": is_covered and centreline_ok,
        }
    return {
        "lanes_scope": len(lanes),
        "lanes_with_strips": sum(1 for n in strip_count.values() if n > 0),
        "lanes_failed": sorted(failed),
        "lanes_uncovered": sorted(uncovered),
        "strips": len(snapshot.get("strips") or []),
        "strips_unmatched": unmatched,
        "worst_cm": _r3(worst_cm),
        "worst_lane": worst_lane,
        "per_lane": per_lane,
        "pass": not failed and not unmatched,
    }


def check_widths(snapshot: dict, spec: dict, *, tol_cm: float = 5.0,
                 match_max_cm: float = _MATCH_MAX_CM) -> dict:
    """Per strip: |scale_y * mesh_width_cm - width_cm_effective| for the start
    and the end cross-section (error = the larger of the two)."""
    widths = {lid: ln.get("width_cm_effective") for lid, ln in _normal_lanes(spec).items()}
    per_strip: list[dict] = []
    failed: list[int] = []
    unmatched: list[int] = []
    worst_err = 0.0
    worst_row: int | None = None
    for i, strip in enumerate(snapshot.get("strips") or []):
        lid = _strip_lane(strip, spec, match_max_cm=match_max_cm)
        mw = float(strip.get("mesh_width_cm") or 0.0)
        w_start = float(strip.get("start_scale_y") or 0.0) * mw
        w_end = float(strip.get("end_scale_y") or 0.0) * mw
        if lid is None:
            unmatched.append(i)
            failed.append(i)
            per_strip.append({"strip_index": i, "lane_id": None, "matched": False,
                              "measured_width_start_cm": _r3(w_start),
                              "measured_width_end_cm": _r3(w_end),
                              "spec_width_cm_effective": None, "error_cm": None,
                              "pass": False})
            continue
        w_spec = widths.get(lid)
        if w_spec is None:
            per_strip.append({"strip_index": i, "lane_id": lid, "matched": True,
                              "measured_width_start_cm": _r3(w_start),
                              "measured_width_end_cm": _r3(w_end),
                              "spec_width_cm_effective": None, "error_cm": None,
                              "pass": True, "note": "spec lane has no width_cm_effective"})
            continue
        err = max(abs(w_start - w_spec), abs(w_end - w_spec))
        ok = err <= tol_cm + 1e-6
        if not ok:
            failed.append(i)
        if err > worst_err:
            worst_err = err
            worst_row = i
        per_strip.append({"strip_index": i, "lane_id": lid, "matched": True,
                          "mesh_width_cm": _r3(mw),
                          "start_scale_y": _r6(float(strip.get("start_scale_y") or 0.0)),
                          "end_scale_y": _r6(float(strip.get("end_scale_y") or 0.0)),
                          "measured_width_start_cm": _r3(w_start),
                          "measured_width_end_cm": _r3(w_end),
                          "spec_width_cm_effective": _r3(w_spec),
                          "error_cm": _r3(err), "pass": ok})
    return {
        "rows": len(per_strip),
        "per_strip": per_strip,
        "failed": sorted(failed),
        "strips_unmatched": unmatched,
        "worst_cm": _r3(worst_err),
        "worst_strip_index": worst_row,
        "pass": not failed,
    }


def _bbox(points: list[dict]) -> dict:
    xs = [p["x"] for p in points]
    ys = [p["y"] for p in points]
    return {"min_x": min(xs), "min_y": min(ys), "max_x": max(xs), "max_y": max(ys)}


def _bbox_deficit(outer: dict, inner: dict) -> float:
    """How far (cm) bbox ``outer`` falls short of covering bbox ``inner``."""
    return (max(0.0, inner["min_x"] - outer["min_x"])
            + max(0.0, inner["min_y"] - outer["min_y"])
            + max(0.0, outer["max_x"] - inner["max_x"])
            + max(0.0, outer["max_y"] - inner["max_y"]))


def check_junctions(snapshot: dict, spec: dict, *, tol_cm: float = 5.0) -> dict:
    """Per spec junction WITH a polygon: a slab bbox must cover the polygon
    bbox (2-D) and |slab_top - strip_top| must be <= tol_cm for the strips of
    the junction's incoming lanes (z continuity between fill slab and road)."""
    slabs = snapshot.get("slabs") or []
    junction_polys = [j for j in (spec.get("junctions") or []) if j.get("polygon")]
    lanes = _normal_lanes(spec)
    edge_lanes: dict[str, set[str]] = {}
    for e in spec.get("edges") or []:
        ids = {str(ln["id"]) for ln in (e.get("lanes") or []) if ln["id"] in lanes}
        edge_lanes[str(e.get("id"))] = ids
    incoming_lanes: dict[str, set[str]] = {}
    for j in junction_polys:
        ids: set[str] = set()
        for eid in (j.get("incoming_edge_ids") or []):
            ids |= edge_lanes.get(str(eid), set())
        incoming_lanes[str(j["id"])] = ids

    # strip top per attributed lane
    top_by_lane: dict[str, list[float]] = {}
    for strip in snapshot.get("strips") or []:
        lid = _strip_lane(strip, spec, match_max_cm=_MATCH_MAX_CM)
        if lid is not None:
            top_by_lane.setdefault(lid, []).append(float(strip.get("top_z") or 0.0))

    rows: dict[str, dict] = {}
    failed: list[str] = []
    worst_z = 0.0
    worst_z_junction: str | None = None
    for j in sorted(junction_polys, key=lambda x: str(x["id"])):
        jid = str(j["id"])
        poly_bbox = _bbox(j["polygon"])
        covering = []
        for sl in slabs:
            sl_bbox = _bbox([sl["bounds_min"], sl["bounds_max"]])
            if _bbox_deficit(sl_bbox, poly_bbox) <= 1e-6:
                covering.append(sl)
        covering.sort(key=lambda s: str(s.get("id") or ""))
        if covering:
            slab = covering[0]
            covered = True
            slab_id = str(slab.get("id") or "")
            slab_top = float(slab.get("top_z") or 0.0)
            tops = [t for lid in sorted(incoming_lanes.get(jid, set()))
                    for t in top_by_lane.get(lid, [])]
            if tops:
                z_err = max(abs(slab_top - t) for t in tops)
                z_checked = True
            else:
                z_err = None
                z_checked = False  # nothing adjacent measured; coverage only
        else:
            covered = False
            slab_id = None
            slab_top = None
            z_err = None
            z_checked = False
        z_ok = z_err is not None and z_err <= tol_cm + 1e-6
        ok = covered and (not z_checked or z_ok)
        if not ok:
            failed.append(jid)
        if z_err is not None and z_err > worst_z:
            worst_z = z_err
            worst_z_junction = jid
        rows[jid] = {
            "covered": covered, "slab_id": slab_id,
            "slab_top_cm": _r3(slab_top) if slab_top is not None else None,
            "polygon_bbox": {k: _r3(v) for k, v in poly_bbox.items()},
            "z_checked": z_checked,
            "z_error_cm": _r3(z_err) if z_err is not None else None,
            "pass": ok,
        }
    return {
        "junctions_checked": len(junction_polys),
        "covered": sum(1 for r in rows.values() if r["covered"]),
        "failed": sorted(failed),
        "worst_z_cm": _r3(worst_z),
        "worst_z_junction": worst_z_junction,
        "rows": rows,
        "pass": not failed,
    }


def check_ground(snapshot: dict, spec: dict) -> dict:
    """Ground bbox must cover the extent of the spec's normal lanes (2-D) and
    ground top must sit below the strips (z law: the road sits ON the ground)."""
    lanes = _normal_lanes(spec)
    pts = [p for ln in lanes.values() for p in ln["polyline"]]
    extent = _bbox(pts) if pts else None
    ground = snapshot.get("ground")
    strips = snapshot.get("strips") or []
    reasons: list[str] = []
    covered = False
    top_gap_cm: float | None = None
    top_below = False
    if ground is None:
        reasons.append("no ground in snapshot")
    elif extent is None:
        reasons.append("spec has no normal lanes")
    else:
        g_bbox = _bbox([ground["bounds_min"], ground["bounds_max"]])
        covered = _bbox_deficit(g_bbox, extent) <= 1e-6
        if not covered:
            reasons.append("ground bbox does not cover the lane extent")
        strip_tops = [float(s.get("top_z") or 0.0) for s in strips]
        g_top = float(ground.get("top_z") or 0.0)
        if strip_tops:
            top_gap_cm = min(strip_tops) - g_top
            top_below = top_gap_cm > 0.0
            if not top_below:
                reasons.append("ground top not below the lowest strip top")
        else:
            reasons.append("no strips to compare ground top against")
    return {
        "ground_present": ground is not None,
        "lane_extent": {k: _r3(v) for k, v in extent.items()} if extent else None,
        "extent_covered": covered,
        "ground_top_cm": _r3(float(ground.get("top_z") or 0.0)) if ground is not None else None,
        "top_gap_cm": _r3(top_gap_cm) if top_gap_cm is not None else None,
        "ground_below_strips": top_below,
        "reasons": reasons,
        "pass": covered and top_below,
    }


# --- report ----------------------------------------------------------------


def build_report(snapshot: dict, spec: dict, *, tol_cm: float = 5.0,
                 match_max_cm: float = _MATCH_MAX_CM) -> dict:
    """Aggregate the four checks into a ``road_geometry_v1`` report: per-check
    pass, totals, worst rows, tolerances echoed; overall pass = all checks."""
    cl = check_centrelines(snapshot, spec, tol_cm=tol_cm, match_max_cm=match_max_cm)
    wd = check_widths(snapshot, spec, tol_cm=tol_cm, match_max_cm=match_max_cm)
    jn = check_junctions(snapshot, spec, tol_cm=tol_cm)
    gr = check_ground(snapshot, spec)
    checks = {"centrelines": cl, "widths": wd, "junctions": jn, "ground": gr}
    totals = {
        "lanes_scope": cl["lanes_scope"],
        "lanes_failed": len(cl["lanes_failed"]),
        "lanes_uncovered": len(cl["lanes_uncovered"]),
        "strips": len(snapshot.get("strips") or []),
        "strips_unmatched": len(cl["strips_unmatched"]),
        "slabs": len(snapshot.get("slabs") or []),
        "junctions_checked": jn["junctions_checked"],
        "junction_failures": len(jn["failed"]),
        "width_rows": wd["rows"],
        "width_failures": len(wd["failed"]),
        "ground_pass": gr["pass"],
    }
    worst = {
        "centreline_cm": {"lane_id": cl["worst_lane"], "max_cm": cl["worst_cm"]},
        "width_cm": {"strip_index": wd["worst_strip_index"], "error_cm": wd["worst_cm"]},
        "junction_z_cm": {"junction_id": jn["worst_z_junction"], "error_cm": jn["worst_z_cm"]},
        "ground_top_gap_cm": gr["top_gap_cm"],
    }
    return {
        "schema_version": ROAD_GEOMETRY_VERSION,
        "tolerances": {"centreline_cm": tol_cm, "width_cm": tol_cm, "junction_cm": tol_cm,
                       "coverage_gap_cm": tol_cm, "match_max_cm": match_max_cm},
        "checks": checks,
        "totals": totals,
        "worst": worst,
        "pass": bool(cl["pass"] and wd["pass"] and jn["pass"] and gr["pass"]),
    }


def write_report(report: dict, path: str | Path) -> dict:
    """Write the report as sorted, indented JSON; return it unchanged."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
