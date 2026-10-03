"""Stage 4: plan a camera for every beat, FROM THE RECORD, and measure what it holds.

A beat says what must be seen: which arm, which actors (its SUBJECTS), on which
street, in which stretch of simulated time. This module turns that into a
window and a fixed camera, and then measures -- sample by sample, from the
sealed record -- how many of the subjects that camera actually holds:

* inside the picture's safe area (horizontally and vertically, not merely
  "near the street");
* large enough to be a figure rather than a dot (projected height in pixels);
* not behind a city block: the sight line from the lens to the body must not
  cross any block of buildings in `city_layout.json`;
* where the beat says they are (`on_street`: the street's corridor, or only the
  closed edge's own lanes) and, when the beat says so, standing still.

A beat's requirement is checked against those measurements and the planner
FAILS CLOSED when no candidate camera meets it. A shot whose claim is an
absence ("nobody we follow is on this street now") reuses the camera and the
window of the shot that showed the presence, in the other arm, and requires the
measured count to be zero -- so the absence is of the subjects, not of the
camera's attention. An EVENT beat (a car the simulator removes) requires the
subject to be held up to the event second and gone after it.

Cameras are fixed and stand on a street's own centre line, aimed at the
subjects' median position. Keeping the lens over the street keeps every sight
line inside the street corridor, which is what lets the block test above be
conservative without refusing everything.

No stretch of footage is used twice: two shots of the same arm from the same
camera may not overlap in simulated time.

NOT measured here: occlusion by trees, street furniture and other actors. The
render stage measures that in the engine, by line trace, at sampled frames.

Everything is a pure function of the record, the facts and the story, so the
same inputs give byte-identical shots.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from . import FactoryError
from .record import (Record, Track, dist_to_segments, edge_half_width_cm, edge_segments,
                     trim_segments)
from .util import read_json, seal, verify_seal

SHOTS_SCHEMA = "episode_shots_v1"

#: Presentation geometry. Stated, written into shots.json, never tuned per shot.
PARAMS = {
    "sample_seconds": 0.5,
    "safe_area": 0.92,                 # fraction of the half-angle a subject must sit inside
    "min_person_px": 22.0,             # projected height at the output resolution
    "min_vehicle_px": 14.0,
    "person_height_cm": 170.0,
    "vehicle_height_cm": 150.0,
    "near_cm": 250.0,
    "street_corridor_half_width_cm": 1500.0,
    "street_end_trim_cm": 1500.0,
    "stopped_speed_mps": 0.1,
    "level_min_cm": -1000.0,
    "level_max_cm": 61000.0,
    # coloured balls hung over named actors so a viewer can tell them apart
    "marks": {"yellow": {"colour": [1.0, 0.82, 0.0], "z_cm": 215.0, "scale": 0.4},
              "red": {"colour": [1.0, 0.04, 0.04], "z_cm": 265.0, "scale": 0.55}},
    "styles": {
        "eye": {"heights_cm": [300.0, 450.0, 700.0], "standoffs_cm": [1200.0, 2000.0, 3200.0],
                "fovs_deg": [42.0, 58.0]},
        "high": {"heights_cm": [1400.0, 2400.0, 3600.0], "standoffs_cm": [2500.0, 4500.0, 7000.0],
                 "fovs_deg": [50.0, 66.0]},
    },
}


class CameraError(FactoryError):
    stage = "camera"


# --- geometry ------------------------------------------------------------------

def look_rot(frm: list[float], to: list[float]) -> list[float]:
    dx, dy, dz = to[0] - frm[0], to[1] - frm[1], to[2] - frm[2]
    return [round(math.degrees(math.atan2(dz, math.hypot(dx, dy))), 3),
            round(math.degrees(math.atan2(dy, dx)), 3), 0.0]


class Lens:
    """A fixed camera: location, rotation, horizontal field of view, output size."""

    def __init__(self, loc: list[float], rot: list[float], fov_deg: float, res: list[int]) -> None:
        self.loc, self.rot, self.fov, self.res = loc, rot, fov_deg, res
        p, y = math.radians(rot[0]), math.radians(rot[1])
        self.f = (math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p))
        self.r = (-math.sin(y), math.cos(y), 0.0)
        self.u = (-math.sin(p) * math.cos(y), -math.sin(p) * math.sin(y), math.cos(p))
        self.tan_h = math.tan(math.radians(fov_deg) / 2.0)
        self.tan_v = self.tan_h * res[1] / res[0]

    def project(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        """(depth cm, horizontal fraction of half-width, vertical fraction of half-height)."""
        d = (x - self.loc[0], y - self.loc[1], z - self.loc[2])
        depth = d[0] * self.f[0] + d[1] * self.f[1] + d[2] * self.f[2]
        if depth <= 0:
            return depth, float("inf"), float("inf")
        xc = d[0] * self.r[0] + d[1] * self.r[1]
        yc = d[0] * self.u[0] + d[1] * self.u[1] + d[2] * self.u[2]
        return depth, xc / (depth * self.tan_h), yc / (depth * self.tan_v)

    def height_px(self, depth: float, height_cm: float) -> float:
        return height_cm / (2.0 * depth * self.tan_v) * self.res[1]


def _seg_hits_rect(ax: float, ay: float, bx: float, by: float, r: dict[str, float]) -> bool:
    """Does the segment a-b pass through the axis-aligned rectangle r? (Liang-Barsky)"""
    dx, dy = bx - ax, by - ay
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, ax - r["x_min"]), (dx, r["x_max"] - ax),
                 (-dy, ay - r["y_min"]), (dy, r["y_max"] - ay)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return False
            t0 = max(t0, t)
        else:
            if t < t0:
                return False
            t1 = min(t1, t)
    return t0 <= t1


def load_blocks(layout_path: str | Path) -> list[dict[str, float]]:
    doc = read_json(layout_path, "city layout", error=CameraError)
    try:
        return [dict(b["bbox"]) for b in doc["blocks"]]
    except (KeyError, TypeError) as e:
        raise CameraError("corrupt", f"city layout carries no block boxes: {e!r}")


def sees(lens: Lens, x: float, y: float, kind: str, blocks: list[dict[str, float]]) -> str:
    """"visible", or the reason the lens does not hold a body standing at (x, y)."""
    height = PARAMS["person_height_cm"] if kind == "person" else PARAMS["vehicle_height_cm"]
    depth, h, v = lens.project(x, y, height / 2.0)
    if depth < PARAMS["near_cm"]:
        return "behind_or_too_near"
    if abs(h) > PARAMS["safe_area"] or abs(v) > PARAMS["safe_area"]:
        return "out_of_frame"
    need = PARAMS["min_person_px"] if kind == "person" else PARAMS["min_vehicle_px"]
    if lens.height_px(depth, height) < need:
        return "too_small"
    for b in blocks:
        if _seg_hits_rect(lens.loc[0], lens.loc[1], x, y, b):
            return "behind_a_block"
    return "visible"


# --- subjects --------------------------------------------------------------------

def resolve_subjects(spec: dict[str, Any], facts: dict[str, Any], rec: Record) -> list[str]:
    group = spec["group"]
    groups = facts.get("groups") or {}
    if group in groups:
        uids = list(groups[group])
    elif group == "vehicles":
        uids = sorted(t.uid for t in rec.of_kind("vehicle"))
    elif group == "people":
        uids = sorted(t.uid for t in rec.of_kind("person"))
    elif group == "all":
        uids = sorted(rec.tracks)
    else:
        raise CameraError("unknown_subjects", f"no subject group {group!r} in the facts")
    if "uids" in spec:
        stray = sorted(set(spec["uids"]) - set(uids))
        if stray:
            raise CameraError("unknown_subjects", f"{stray} are not in the measured group {group!r}")
        uids = list(spec["uids"])
    if not uids:
        raise CameraError("no_subjects", f"subject group {group!r} is empty: there is no measured "
                                         "event for this beat to show")
    return uids


def _street_edge(spec: dict[str, Any], facts: dict[str, Any]) -> str | None:
    s = spec.get("street")
    if s is None:
        return None
    streets = facts.get("streets") or {}
    if s in streets:
        return streets[s]["edges"][0]
    return s


def _corridor(net: Any, edge_id: str, mode: Any):
    """Where a subject must BE to count: the street (both pavements) or the edge's own lanes."""
    if not mode:
        return None
    segs = trim_segments(edge_segments(net, edge_id), PARAMS["street_end_trim_cm"])
    if mode == "lanes":
        return segs, edge_half_width_cm(net, edge_id)
    if mode in (True, "street"):
        return segs, PARAMS["street_corridor_half_width_cm"]
    raise CameraError("bad_visual", f"unknown on_street mode {mode!r}")


def _axis(net: Any, edge_id: str) -> tuple[tuple[float, float], tuple[float, float], float]:
    """A street's centre line: junction to junction, in Unreal cm. (origin, unit, length)."""
    from ..coords import SumoPose, sumo_to_unreal
    try:
        e = net.getEdge(edge_id)
    except KeyError:
        raise CameraError("bad_street", f"the network has no edge {edge_id!r}")
    pts = []
    for node in (e.getFromNode(), e.getToNode()):
        x, y = node.getCoord()[:2]
        up = sumo_to_unreal(SumoPose(x=x, y=y, z=0.0, angle=0.0))
        pts.append((up.x, up.y))
    (ax, ay), (bx, by) = pts
    ln = math.hypot(bx - ax, by - ay)
    if ln <= 0:
        raise CameraError("bad_street", f"edge {edge_id!r} has no length")
    return (ax, ay), ((bx - ax) / ln, (by - ay) / ln), ln


def _nearest_edge(net: Any, x: float, y: float) -> str:
    best, best_d = None, float("inf")
    for e in sorted(net.getEdges(), key=lambda e: e.getID()):
        if e.getID().startswith(":"):
            continue
        d = dist_to_segments(x, y, edge_segments(net, e.getID()))
        if d < best_d:
            best, best_d = e.getID(), d
    if best is None:
        raise CameraError("bad_street", "the network has no edges")
    return best


def _positions(tracks: list[Track], frame: int) -> list[tuple[str, float, float]]:
    out = []
    for t in tracks:
        i = t.index_at(frame)
        if i >= 0:
            out.append((t.uid, t.x[i], t.y[i]))
    return out


# --- window ----------------------------------------------------------------------

def choose_window(spec: dict[str, Any], rec: Record, tracks: list[Track], corridor,
                  seconds: float) -> float:
    """The start second of the shot. `fixed` is taken as given; `best` maximises
    the smallest number of subjects in the corridor at any whole second of the window."""
    w = spec["window"]
    last_start = rec.time_of(rec.frame_count - 1) - seconds
    if w["mode"] == "fixed":
        t0 = float(w["start"])
        if t0 < rec.t_begin or t0 > last_start:
            raise CameraError("window_outside_record",
                              f"a {seconds:.0f} s shot starting at {t0:.0f} s does not fit in the record")
        return t0
    if w["mode"] != "best":
        raise CameraError("bad_window", f"unknown window mode {w['mode']!r}")
    lo = max(float(w.get("t_min", rec.t_begin)), rec.t_begin)
    hi = min(float(w.get("t_max", last_start + seconds)) - seconds, last_start)
    if hi < lo:
        raise CameraError("window_outside_record", "the allowed window is shorter than the shot")
    seconds_i = int(math.ceil(seconds))
    t_first, t_last = int(math.ceil(lo)), int(math.floor(hi)) + seconds_i
    counts = []
    for t in range(t_first, t_last + 1):
        pos = _positions(tracks, rec.frame_of(float(t)))
        counts.append(len(pos) if corridor is None else
                      sum(1 for _u, x, y in pos if dist_to_segments(x, y, corridor[0]) <= corridor[1]))
    best_t, best = None, (-1, -1.0)
    for k in range(0, int(math.floor(hi)) - t_first + 1):
        win = counts[k:k + seconds_i + 1]
        score = (min(win), sum(win) / len(win))
        if score > best:
            best, best_t = score, float(t_first + k)
    if best_t is None or best[0] < 0:
        raise CameraError("window_outside_record", "no window could be evaluated")
    return best_t


# --- measurement -----------------------------------------------------------------

def measure(lens: Lens, rec: Record, tracks: list[Track], t0: float, seconds: float,
            blocks: list[dict[str, float]], *, corridor=None, stopped_only: bool = False) -> dict[str, Any]:
    """What the lens holds, sample by sample. Counts only; no judgement.

    A subject COUNTS at a sample when the record has it there, the lens holds
    it (`sees`), it is inside `corridor` when one is given, and -- with
    `stopped_only` -- the record has it standing still.
    """
    n = int(round(seconds / PARAMS["sample_seconds"]))
    per, per_stopped, reasons = [], [], {}
    px_sum, px_n = 0.0, 0
    speed_max = 0.0
    stop = PARAMS["stopped_speed_mps"]
    for k in range(n + 1):
        f = rec.frame_of(t0 + k * PARAMS["sample_seconds"])
        c = cs = 0
        for t in tracks:
            i = t.index_at(f)
            if i < 0:
                reasons["absent"] = reasons.get("absent", 0) + 1
                continue
            if corridor is not None and dist_to_segments(t.x[i], t.y[i], corridor[0]) > corridor[1]:
                reasons["off_street"] = reasons.get("off_street", 0) + 1
                continue
            why = sees(lens, t.x[i], t.y[i], t.kind, blocks)
            if why != "visible":
                reasons[why] = reasons.get(why, 0) + 1
                continue
            still = t.speed[i] < stop
            if still:
                cs += 1
            if stopped_only and not still:
                reasons["moving"] = reasons.get("moving", 0) + 1
                continue
            c += 1
            depth = lens.project(t.x[i], t.y[i], 85.0)[0]
            px_sum += lens.height_px(depth, PARAMS["person_height_cm"] if t.kind == "person"
                                     else PARAMS["vehicle_height_cm"])
            px_n += 1
            if t.speed[i] > speed_max:
                speed_max = float(t.speed[i])
        per.append(c)
        per_stopped.append(cs)
    return {"samples": len(per), "visible_min": min(per), "visible_max": max(per),
            "visible_mean": round(sum(per) / len(per), 3), "per_sample": per,
            "stopped_min": min(per_stopped), "stopped_max": max(per_stopped),
            "speed_max_mps": round(speed_max, 3),
            "mean_height_px": round(px_sum / px_n, 1) if px_n else 0.0,
            "not_visible_reasons": dict(sorted(reasons.items()))}


def counted(lens: Lens, rec: Record, track: Track, frame: int, x: float, y: float,
            blocks: list[dict[str, float]], corridor, stopped_only: bool) -> bool:
    """Does ONE subject count at a position (x, y)? The rule `measure` applies, exposed
    so the render stage can apply it to the position the ENGINE reports."""
    if corridor is not None and dist_to_segments(x, y, corridor[0]) > corridor[1]:
        return False
    if sees(lens, x, y, track.kind, blocks) != "visible":
        return False
    if stopped_only:
        i = track.index_at(frame)
        if i < 0 or track.speed[i] >= PARAMS["stopped_speed_mps"]:
            return False
    return True


def check_requirement(require: dict[str, Any], m: dict[str, Any], t0: float,
                      times: list[float] | None = None) -> tuple[bool, float]:
    """(met, fraction of samples that individually meet it)."""
    per = m["per_sample"]
    if not per:
        return False, 0.0
    if "max_visible" in require:
        ok = [c <= int(require["max_visible"]) for c in per]
        return all(ok), sum(ok) / len(ok)
    need = int(require["min_visible"])
    if "until" in require:
        # an EVENT: the subject is held up to it and -- when the beat says so --
        # is no longer there after it. Half a second either side is not judged.
        ev = float(require["until"])
        if times is None:
            times = [t0 + k * PARAMS["sample_seconds"] for k in range(len(per))]
        before = [c >= need for c, t in zip(per, times) if t <= ev - 0.5]
        after = [c == 0 for c, t in zip(per, times) if t >= ev + 0.5] \
            if require.get("then_absent") else []
        ok = before + after
        met = bool(before) and all(before) and all(after) and \
            (bool(after) or not require.get("then_absent"))
        return met, (sum(ok) / len(ok) if ok else 0.0)
    ok = [c >= need for c in per]
    frac = sum(ok) / len(ok)
    return frac >= float(require.get("fraction", 1.0)), frac


def plan_camera(spec: dict[str, Any], rec: Record, tracks: list[Track], net: Any, edge_id: str,
                t0: float, seconds: float, res: list[int], blocks: list[dict[str, float]],
                corridor) -> tuple[Lens, dict[str, Any], dict[str, Any]]:
    """The best fixed camera on the street's centre line for these subjects."""
    (ax, ay), (ux, uy), _ln = _axis(net, edge_id)
    style = PARAMS["styles"][spec.get("style", "eye")]
    half = PARAMS["street_corridor_half_width_cm"]
    segs = edge_segments(net, edge_id)
    f0, f1 = rec.frame_of(t0), rec.frame_of(t0 + seconds)
    along: list[float] = []
    xs: list[float] = []
    ys: list[float] = []
    for t in tracks:
        for i in t.slice(f0, f1):
            if corridor is not None:
                if dist_to_segments(t.x[i], t.y[i], corridor[0]) > corridor[1]:
                    continue
            elif spec["kind"] == "street" and dist_to_segments(t.x[i], t.y[i], segs) > half * 2.0:
                continue
            along.append((t.x[i] - ax) * ux + (t.y[i] - ay) * uy)
            xs.append(t.x[i])
            ys.append(t.y[i])
    if not along:
        raise CameraError("event_not_visible",
                          f"none of the subjects is recorded near {edge_id} during the window")
    along.sort()
    xs.sort()
    ys.sort()
    # the stretch the subjects sweep during the shot, without a lone straggler
    lo = along[int(0.05 * (len(along) - 1))]
    hi = along[int(0.95 * (len(along) - 1))]
    # aimed at where the subjects ARE (their median position), not at the axis
    look = [round(xs[len(xs) // 2], 1), round(ys[len(ys) // 2], 1), 110.0]
    best = None
    index = 0
    lo_b, hi_b = PARAMS["level_min_cm"], PARAMS["level_max_cm"]
    stopped_only = bool(spec["require"].get("stopped"))
    for standoff in style["standoffs_cm"]:
        for height in style["heights_cm"]:
            for fov in style["fovs_deg"]:
                for side in (1.0, -1.0):
                    index += 1
                    s_cam = hi + standoff if side > 0 else lo - standoff
                    loc = [round(ax + ux * s_cam, 1), round(ay + uy * s_cam, 1), height]
                    if not (lo_b <= loc[0] <= hi_b and -hi_b <= loc[1] <= -lo_b):
                        continue
                    if any(b["x_min"] <= loc[0] <= b["x_max"] and b["y_min"] <= loc[1] <= b["y_max"]
                           for b in blocks):
                        continue
                    lens = Lens(loc, look_rot(loc, look), fov, res)
                    m = measure(lens, rec, tracks, t0, seconds, blocks, corridor=corridor,
                                stopped_only=stopped_only)
                    met, frac = check_requirement(spec["require"], m, t0)
                    score = (met, round(frac, 6), m["visible_min"], m["mean_height_px"],
                             m["visible_mean"], -index)
                    if best is None or score > best[0]:
                        best = (score, lens, m, {"candidate": index, "standoff_cm": standoff,
                                                 "side": "ahead" if side > 0 else "behind",
                                                 "look_at": look, "street_edge": edge_id,
                                                 "subject_stretch_cm": [round(lo, 1), round(hi, 1)]})
    if best is None:
        raise CameraError("event_not_visible", f"no camera position on {edge_id} is inside the level")
    return best[1], best[2], best[3]


# --- the stage -------------------------------------------------------------------

def _census(lens: Lens, rec: Record, t0: float, seconds: float, blocks) -> dict[str, Any]:
    out = {}
    for kind, key in (("person", "people"), ("vehicle", "cars")):
        m = measure(lens, rec, rec.of_kind(kind), t0, seconds, blocks)
        out[f"{key}_visible_min"] = m["visible_min"]
        out[f"{key}_visible_max"] = m["visible_max"]
    return out


def plan_shots(story: dict[str, Any], facts: dict[str, Any], recs: dict[str, Record], net: Any,
               blocks: list[dict[str, float]], res: list[int]) -> dict[str, Any]:
    """One measured shot per beat, or a refusal naming the beat that cannot be shown."""
    if story.get("facts_hash") != facts.get("facts_hash"):
        raise CameraError("stale_lineage", "the story was selected from a different fact sheet")
    for arm, rec in recs.items():
        if (facts.get("records") or {}).get(arm) != rec.frames_sha256:
            raise CameraError("stale_lineage", f"the {arm} record is not the one the facts were "
                                               "extracted from")
    shots: dict[str, dict[str, Any]] = {}
    order = [b for b in story["beats"] if b["visual"].get("kind") != "same_as"] + \
            [b for b in story["beats"] if b["visual"].get("kind") == "same_as"]
    for beat in order:
        spec, bid = beat["visual"], beat["id"]
        seconds = float(beat["seconds"])
        arm = spec["arm"]
        if arm not in recs:
            raise CameraError("bad_arm", f"beat {bid!r} asks for arm {arm!r}")
        rec = recs[arm]
        uids = resolve_subjects(spec["subjects"], facts, rec)
        tracks = rec.select(uids)
        stopped_only = bool(spec["require"].get("stopped"))
        if spec["kind"] == "same_as":
            src = shots.get(spec["same_as"])
            if src is None:
                raise CameraError("bad_reference", f"beat {bid!r} reuses the camera of "
                                                   f"{spec['same_as']!r}, which has no shot")
            if src["arm"] == arm:
                raise CameraError("footage_reused", f"beat {bid!r} would replay the footage of "
                                                    f"{spec['same_as']!r}")
            t0, edge_id = src["sim_start"], src["camera"]["street_edge"]
            if t0 + seconds > rec.time_of(rec.frame_count - 1):
                raise CameraError("window_outside_record", f"beat {bid!r}: the {arm} record ends "
                                                           "before the compared window does")
            corridor = _corridor(net, edge_id, spec.get("on_street"))
            lens = Lens(src["camera"]["loc"], src["camera"]["rot"], src["camera"]["fov_deg"], res)
            m = measure(lens, rec, tracks, t0, seconds, blocks, corridor=corridor,
                        stopped_only=stopped_only)
            how = {k: src["camera"][k] for k in ("candidate", "standoff_cm", "side", "look_at",
                                                 "street_edge", "subject_stretch_cm")}
            how["same_camera_as"] = spec["same_as"]
        elif spec["kind"] in ("street", "group"):
            edge_id = _street_edge(spec, facts)
            if spec["kind"] == "street" and edge_id is None:
                raise CameraError("bad_street", f"beat {bid!r} names no street")
            if edge_id is None:
                # the street the subjects are on at the middle of a fixed window
                w = spec["window"]
                if w["mode"] != "fixed":
                    raise CameraError("bad_window", f"beat {bid!r}: a shot with no street needs a "
                                                    "fixed window")
                pos = _positions(tracks, rec.frame_of(float(w["start"]) + seconds / 2.0))
                if not pos:
                    raise CameraError("event_not_visible",
                                      f"beat {bid!r}: no subject exists in the record at the middle "
                                      "of its window")
                xs, ys = sorted(p[1] for p in pos), sorted(p[2] for p in pos)
                edge_id = _nearest_edge(net, xs[len(xs) // 2], ys[len(ys) // 2])
            else:
                _axis(net, edge_id)
            corridor = _corridor(net, edge_id, spec.get("on_street"))
            t0 = choose_window(spec, rec, tracks, corridor or _corridor(net, edge_id, "street"), seconds)
            lens, m, how = plan_camera(spec, rec, tracks, net, edge_id, t0, seconds, res, blocks,
                                       corridor)
        else:
            raise CameraError("bad_visual", f"beat {bid!r} has unknown visual kind {spec['kind']!r}")

        met, frac = check_requirement(spec["require"], m, t0)
        if not met:
            raise CameraError(
                "event_not_visible",
                f"beat {bid!r}: the camera does not hold what the beat claims. Required "
                f"{spec['require']}, measured visible {m['visible_min']}..{m['visible_max']} of "
                f"{len(tracks)} subjects ({frac:.0%} of samples meet it); reasons "
                f"{m['not_visible_reasons']}")
        # SIGNALING: the followed walkers carry a yellow ball in every shot; a beat
        # may ask for its own subjects to carry a red one
        marks = {}
        followed = sorted((facts.get("groups") or {}).get("walkers") or [])
        if followed:
            marks["yellow"] = {"group": "walkers", "count": len(followed), "uids": followed,
                               **PARAMS["marks"]["yellow"]}
        if spec.get("mark_subjects"):
            marks["red"] = {"group": spec["subjects"]["group"], "count": len(uids), "uids": list(uids),
                            **PARAMS["marks"]["red"]}
        ev = beat.get("event")
        if ev is not None and not (t0 < float(ev["second"]) < t0 + seconds):
            raise CameraError("event_not_visible",
                              f"beat {bid!r}: its event at {ev['second']} s is outside the shot "
                              f"({t0}..{t0 + seconds} s)")
        shots[bid] = {
            "beat": bid, "arm": arm, "sim_start": round(t0, 3), "seconds": seconds,
            "sim_end": round(t0 + seconds, 3),
            "camera": {"loc": lens.loc, "rot": lens.rot, "fov_deg": lens.fov, **how},
            "subjects": {"group": spec["subjects"]["group"], "count": len(uids), "uids": uids},
            "counted_where": spec.get("on_street") or "anywhere in frame",
            "counted_stopped_only": stopped_only,
            "require": spec["require"], "samples_meeting_requirement": round(frac, 4),
            "subjects_visible_min": m["visible_min"], "subjects_visible_max": m["visible_max"],
            "subjects_visible_mean": m["visible_mean"],
            "subjects_visible_last": m["per_sample"][-1],
            "subjects_visible_per_sample": m["per_sample"],
            "subjects_stopped_min": m["stopped_min"], "subjects_stopped_max": m["stopped_max"],
            "subjects_speed_max_mps": m["speed_max_mps"],
            "subjects_mean_height_px": m["mean_height_px"],
            "not_visible_reasons": m["not_visible_reasons"],
            "marks": marks,
            **({"event": {"second": float(ev["second"]), "what": ev["what"],
                          "offset_seconds": float(ev["offset_seconds"])}} if ev else {}),
            **_census(lens, rec, t0, seconds, blocks),
            "record_frames_sha256": rec.frames_sha256,
            "verdict": "pass",
        }
    # no stretch of footage is shown twice: same arm, same camera, overlapping time
    rows = sorted(shots.values(), key=lambda s: s["beat"])
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if (a["arm"] == b["arm"] and a["camera"]["loc"] == b["camera"]["loc"]
                    and a["camera"]["rot"] == b["camera"]["rot"]
                    and a["sim_start"] < b["sim_end"] and b["sim_start"] < a["sim_end"]):
                raise CameraError("footage_reused", f"beats {a['beat']!r} and {b['beat']!r} would "
                                                    "show the same footage")
    doc = {
        "schema_version": SHOTS_SCHEMA,
        "facts_hash": facts["facts_hash"],
        "story_hash": story["story_hash"],
        "resolution": list(res),
        "parameters": PARAMS,
        "not_measured_here": "occlusion by trees, street furniture and other actors "
                             "(measured in the engine at render time)",
        "shots": {b["id"]: shots[b["id"]] for b in story["beats"]},
        "shots_hash": "",
    }
    return seal(doc, "shots_hash")


def shot_corridor(shot: dict[str, Any], net: Any):
    """The corridor a planned shot counted its subjects in (None: anywhere in frame)."""
    mode = shot.get("counted_where")
    return _corridor(net, shot["camera"]["street_edge"], None if mode == "anywhere in frame" else mode)


def remeasure(shot: dict[str, Any], rec: Record, net: Any, blocks: list[dict[str, float]],
              res: list[int]) -> dict[str, Any]:
    """Measure a planned shot again from the record: what an auditor runs."""
    lens = Lens(shot["camera"]["loc"], shot["camera"]["rot"], shot["camera"]["fov_deg"], res)
    return measure(lens, rec, rec.select(shot["subjects"]["uids"]), shot["sim_start"], shot["seconds"],
                   blocks, corridor=shot_corridor(shot, net),
                   stopped_only=bool(shot.get("counted_stopped_only")))


def load_shots(path: str | Path) -> dict[str, Any]:
    doc = read_json(path, "shots.json", error=CameraError)
    if doc.get("schema_version") != SHOTS_SCHEMA:
        raise CameraError("bad_version", f"shots.json declares {doc.get('schema_version')!r}")
    try:
        verify_seal(doc, "shots_hash", "shots.json")
    except FactoryError as e:
        raise CameraError("corrupt", e.message)
    return doc
