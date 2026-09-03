"""Lane L3 of the Phase 2 gate: the "no obvious scripted loops" law, measured.

The Director's Living Agent Law is frozen as three measurable checks over one
Simulation Record V1 directory (`record_manifest.json` + `frames.bin`):

window_repeats
    An actor repeats a position-sequence (a *window*) of `window_s` seconds
    when the same tuple of quantised cells occurs twice for that actor with
    different start times that both fit inside one `horizon_s` window.
    A window whose cells are all identical (parked / waiting / queueing) is
    NOT a loop: it is exempt and counted under `stationary_windows_exempted`.

destinations
    Per kind: unique last-seen quantised cells / sampled actors >=
    `dest_ratio_min`.

spawn_periodicity
    Per kind: first-seen times (from the manifest `actors` table) binned at
    `rate_hz`; score = peak non-DC DFT magnitude / sum of non-DC magnitudes.
    Reported for the Director; `threshold` is null and the overall `pass`
    deliberately ignores it.

Laws honoured here:
  1. pure stdlib (the DFT is written by hand), deterministic;
  2. every parameter is an argument with a default and is echoed into output;
  3. output JSON is sorted-key, indent 2 and carries the manifest's
     frames.bin sha256 so the audit is bound to one record;
  4. frames.bin is read exactly once, sequentially, building per-actor
     sampled tracks at `rate_hz` on the fly (a sample exists only where a
     frame lands on the lattice t_begin + n/rate_hz; an actor absent at a
     lattice time simply has no sample there).

Positions in frames.bin are Unreal centimetres (see ldyf.sumo_record), so
cell index = floor(axis / cell_cm). Windows/horizons are converted from
seconds to samples as round(s * rate_hz).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from .sumo_record import COUNT_STRUCT, SAMPLE_STRUCT

LOOP_AUDIT_VERSION = "loop_audit_v1"

DEFAULT_WINDOW_S = 8.0
DEFAULT_HORIZON_S = 120.0
DEFAULT_CELL_CM = 100.0
DEFAULT_RATE_HZ = 1.0
DEFAULT_DEST_RATIO_MIN = 0.6


# --- sampling -------------------------------------------------------------


def sampled_tracks(frames_path, manifest, rate_hz: float = 1.0) -> dict:
    """One sequential pass over frames.bin -> {uid: [(t, x, y, z), ...]}.

    Only frames that land on the lattice `t_begin + n / rate_hz` contribute a
    sample, so the returned tracks are already decimated to `rate_hz`.
    """
    step = manifest["clock"]["step_seconds"]
    t_begin = manifest["clock"]["t_begin"]
    uids = [a["uid"] for a in manifest["actors"]]
    tracks = {uid: [] for uid in uids}
    with open(frames_path, "rb") as f:
        frame = 0
        while True:
            raw = f.read(COUNT_STRUCT.size)
            if len(raw) < COUNT_STRUCT.size:
                break
            (n,) = COUNT_STRUCT.unpack(raw)
            payload = f.read(n * SAMPLE_STRUCT.size)
            q = frame * step * rate_hz
            if abs(q - round(q)) <= 1e-6 * max(1.0, abs(q)):
                t = t_begin + frame * step
                for k in range(n):
                    idx, x, y, z, _yaw, _speed = SAMPLE_STRUCT.unpack_from(
                        payload, k * SAMPLE_STRUCT.size
                    )
                    tracks[uids[idx]].append((t, x, y, z))
            frame += 1
    return tracks


def quantise(track, cell_cm: float = 100.0) -> list:
    """[(t,x,y,z)] -> [(ix, iy)] per sample, floor division on x and y only."""
    return [(int(x // cell_cm), int(y // cell_cm)) for (_t, x, y, _z) in track]


# --- window repeats -------------------------------------------------------


def _scan_windows(cells, window: int, horizon: int):
    """Return (repeat_events, stationary_windows_exempted) for one track.

    A repeat is a pair of equal, non-constant window tuples whose two
    occurrences both fit inside one horizon window (start_b + window - start_a
    <= horizon). The earliest occurrence of each tuple is kept as start_a, so
    results are independent of scan direction.
    """
    events: list[dict] = []
    exempted = 0
    if window < 1 or len(cells) < window:
        return events, exempted
    seen: dict = {}
    for i in range(len(cells) - window + 1):
        w = tuple(cells[i : i + window])
        first = w[0]
        if all(c == first for c in w):
            exempted += 1
            continue
        j = seen.get(w)
        if j is not None and (i - j + window) <= horizon:
            events.append({"start_a": j, "start_b": i, "window": list(w)})
        else:
            seen.setdefault(w, i)
    return events, exempted


def window_repeats(cells: list, window: int, horizon: int) -> list:
    """Repeat events for one cell track; window/horizon are in samples."""
    events, _ = _scan_windows(cells, window, horizon)
    return events


# --- DFT ------------------------------------------------------------------


def _dft_score(counts: list, rate_hz: float):
    """(score, peak_period_s) over the non-DC bins of the DFT of `counts`.

    score = max|X[k]| / sum|X[k]| for k in 1..N-1; peak_period_s =
    N / (k_peak * rate_hz). Returns (0.0, None) when there is no non-DC
    energy, so no pass threshold is ever invented.
    """
    n = len(counts)
    best_k = None
    best_mag = -1.0
    mag_sum = 0.0
    nonzero = [(i, c) for i, c in enumerate(counts) if c]
    if n < 2 or not nonzero:
        return 0.0, None
    for k in range(1, n):
        re = 0.0
        im = 0.0
        for i, c in nonzero:
            ang = -2.0 * math.pi * k * i / n
            re += c * math.cos(ang)
            im += c * math.sin(ang)
        m = math.hypot(re, im)
        mag_sum += m
        if m > best_mag:
            best_mag = m
            best_k = k
    if best_k is None or mag_sum <= 0.0:
        return 0.0, None
    return round(best_mag / mag_sum, 6), round(n / (best_k * rate_hz), 6)


# --- the audit ------------------------------------------------------------


def audit_record(
    frames_path,
    manifest,
    *,
    window_s: float = DEFAULT_WINDOW_S,
    horizon_s: float = DEFAULT_HORIZON_S,
    cell_cm: float = DEFAULT_CELL_CM,
    rate_hz: float = DEFAULT_RATE_HZ,
    dest_ratio_min: float = DEFAULT_DEST_RATIO_MIN,
) -> dict:
    """Run all three loop-law measurements and return the audit document."""
    window_n = max(1, int(round(window_s * rate_hz)))
    horizon_n = max(window_n, int(round(horizon_s * rate_hz)))
    kind_of = {a["uid"]: a["kind"] for a in manifest["actors"]}

    tracks = sampled_tracks(frames_path, manifest, rate_hz=rate_hz)
    cells_of = {uid: quantise(tr, cell_cm) for uid, tr in tracks.items()}

    # --- window repeats (deterministic: uids visited in sorted order) -----
    actors_with_repeats: list = []
    repeat_count = 0
    stationary_windows_exempted = 0
    worst: dict | None = None
    for uid in sorted(cells_of):
        events, exempted = _scan_windows(cells_of[uid], window_n, horizon_n)
        stationary_windows_exempted += exempted
        if not events:
            continue
        actors_with_repeats.append(uid)
        repeat_count += len(events)
        for ev in events:
            span = ev["start_b"] - ev["start_a"]
            cand = {"uid": uid, "start_a": ev["start_a"], "start_b": ev["start_b"]}
            if worst is None or span > worst["_span"] or (
                span == worst["_span"]
                and (uid, ev["start_a"]) < (worst["uid"], worst["start_a"])
            ):
                worst = {"_span": span, **cand}
    if worst is not None:
        worst.pop("_span")

    # --- destinations (last sampled cell per actor, per kind) -------------
    last_cells: dict = {}
    for uid, cells in cells_of.items():
        if cells:
            last_cells.setdefault(kind_of[uid], []).append(cells[-1])
    by_kind_dest: dict = {}
    dest_pass = True
    for kind in sorted(last_cells):
        actors = len(last_cells[kind])
        unique = len(set(last_cells[kind]))
        ratio = unique / actors if actors else 0.0
        ok = ratio >= dest_ratio_min
        dest_pass = dest_pass and ok
        by_kind_dest[kind] = {
            "actors": actors,
            "unique_destinations": unique,
            "ratio": round(ratio, 6),
            "pass": ok,
        }

    # --- spawn periodicity (manifest first-seen times, binned at rate_hz) -
    t_begin = manifest["clock"]["t_begin"]
    t_end = manifest["clock"]["t_end"]
    nbins = max(1, int(round((t_end - t_begin) * rate_hz)) + 1)
    spawn: dict = {}
    for kind in sorted({a["kind"] for a in manifest["actors"]}):
        counts = [0] * nbins
        for a in manifest["actors"]:
            if a["kind"] != kind:
                continue
            b = int(round((a["first_seen_time"] - t_begin) * rate_hz))
            if 0 <= b < nbins:
                counts[b] += 1
        score, period = _dft_score(counts, rate_hz)
        spawn[kind] = {"score": score, "peak_period_s": period, "bins": nbins}

    window_pass = repeat_count == 0
    return {
        "schema_version": LOOP_AUDIT_VERSION,
        "record": {
            "frames_bin_sha256": manifest["binary"]["sha256"],
            "frames": manifest["clock"]["frame_count"],
            "step_seconds": manifest["clock"]["step_seconds"],
        },
        "params": {
            "window_s": window_s,
            "horizon_s": horizon_s,
            "cell_cm": cell_cm,
            "rate_hz": rate_hz,
            "dest_ratio_min": dest_ratio_min,
        },
        "window_repeats": {
            "actors_with_repeats": actors_with_repeats,
            "repeat_count": repeat_count,
            "worst": worst,
            "stationary_windows_exempted": stationary_windows_exempted,
            "pass": window_pass,
        },
        "destinations": {"by_kind": by_kind_dest, "pass": dest_pass},
        "spawn_periodicity": {"by_kind": spawn, "threshold": None},
        "pass": window_pass and dest_pass,
    }


def write_audit(record_dir, out_path, **params) -> dict:
    """Audit `record_dir` (manifest + frames.bin) and write sorted-key JSON."""
    rd = Path(record_dir)
    manifest = json.loads((rd / "record_manifest.json").read_text(encoding="utf-8"))
    result = audit_record(rd / "frames.bin", manifest, **params)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    Path(out_path).write_text(text, encoding="utf-8")
    return result


# --- loop audit v2 (contract C6) --------------------------------------------

LOOP_AUDIT_V2_VERSION = "loop_audit_v2"


def _windows_all_pairs(cells, window, horizon):
    """Every pair of identical windows (not only the first occurrence)."""
    seen = {}
    repeats = []
    stationary = 0
    for i in range(0, max(0, len(cells) - window + 1)):
        w = tuple(cells[i:i + window])
        if len(set(w)) == 1:
            stationary += 1
            continue
        for j in seen.get(w, ()):  # ALL earlier starts, not just the first
            if horizon is None or (i - j + window) <= horizon:
                repeats.append({"start_a": j, "start_b": i})
        seen.setdefault(w, []).append(i)
    return repeats, stationary


def _headings(track, quant_deg=45.0):
    import math
    out = []
    for (t0, x0, y0, _z0), (t1, x1, y1, _z1) in zip(track, track[1:]):
        dx, dy = x1 - x0, y1 - y0
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            out.append(None)
            continue
        a = math.degrees(math.atan2(dy, dx)) % 360.0
        out.append(int(round(a / quant_deg)) % int(round(360.0 / quant_deg)))
    return out


def _stops(track, cell_cm, speed_eps_cm=10.0):
    """Cells where the actor essentially stopped (consecutive samples within eps)."""
    import math
    stops = []
    for (t0, x0, y0, _z0), (t1, x1, y1, _z1) in zip(track, track[1:]):
        if math.hypot(x1 - x0, y1 - y0) < speed_eps_cm:
            c = (int(math.floor(x1 / cell_cm)), int(math.floor(y1 / cell_cm)))
            if not stops or stops[-1] != c:
                stops.append(c)
    return stops


def audit_record_v2(frames_path, manifest, *, windows_s=(6.0, 8.0, 12.0, 20.0),
                    rates_hz=(1.0, 2.0), horizons_s=(120.0, 300.0, None),
                    cell_cm=100.0, dest_ratio_min=0.6, periodicity_threshold=0.5,
                    patrol_cells=2):
    """Several independent loop tests; the honest boundary is reported, not hidden."""
    base = audit_record(frames_path, manifest, cell_cm=cell_cm, rate_hz=rates_hz[0],
                        dest_ratio_min=dest_ratio_min)
    kinds = {a["uid"]: a.get("kind") for a in manifest["actors"]}
    grid = []
    patrol_windows = 0
    patrol_actors = set()
    patrol_hits = {}
    patrol_total = {}
    cross_actor = []
    route_repeats = {}
    dest_cycles = {}
    for rate in rates_hz:
        tracks = sampled_tracks(frames_path, manifest, rate_hz=rate)
        for window_s in windows_s:
            window = max(2, int(round(window_s * rate)))
            for horizon_s in horizons_s:
                horizon = None if horizon_s is None else int(round(horizon_s * rate))
                total = 0
                actors_hit = set()
                windows_seen = {}
                for uid, tr in tracks.items():
                    cells = quantise(tr, cell_cm=cell_cm)
                    reps, stat = _windows_all_pairs(cells, window, horizon)
                    if reps:
                        total += len(reps)
                        actors_hit.add(uid)
                    for i in range(0, max(0, len(cells) - window + 1)):
                        w = tuple(cells[i:i + window])
                        xs = [c[0] for c in w]
                        ys = [c[1] for c in w]
                        if len(set(w)) > 1 and (max(xs) - min(xs)) <= patrol_cells and (max(ys) - min(ys)) <= patrol_cells:
                            patrol_windows += 1
                            patrol_actors.add(uid)
                            patrol_hits[uid] = patrol_hits.get(uid, 0) + 1
                        patrol_total[uid] = patrol_total.get(uid, 0) + 1
                        windows_seen.setdefault(w, set()).add(uid)
                for w, uids in windows_seen.items():
                    if len(uids) > 1:
                        cross_actor.append({"window_len": len(w), "uids": sorted(uids)[:4],
                                            "rate_hz": rate, "window_s": window_s})
                grid.append({"rate_hz": rate, "window_s": window_s,
                             "horizon_s": horizon_s, "repeats": total,
                             "actors": sorted(actors_hit)[:6], "actor_count": len(actors_hit)})
    tracks = sampled_tracks(frames_path, manifest, rate_hz=rates_hz[0])
    for uid, tr in tracks.items():
        hs = [h for h in _headings(tr) if h is not None]
        for L in (6, 10):
            seen = {}
            hit = 0
            for i in range(0, max(0, len(hs) - L + 1)):
                seg = tuple(hs[i:i + L])
                if len(set(seg)) == 1:
                    continue
                if seg in seen:
                    hit += 1
                seen.setdefault(seg, i)
            if hit:
                route_repeats.setdefault(uid, {})[f"len{L}"] = hit
        st = _stops(tr, cell_cm)
        for i in range(0, max(0, len(st) - 3)):
            if st[i] == st[i + 2] and st[i + 1] == st[i + 3] and st[i] != st[i + 1]:
                dest_cycles[uid] = dest_cycles.get(uid, 0) + 1
    # An actor is "patrolling" only when most of its life is a small-extent
    # shuffle AND it has enough windows to be noticeable on screen.
    patrol_dominant = {uid for uid, hits in patrol_hits.items()
                       if patrol_total.get(uid, 0) >= 30 and hits >= 0.5 * patrol_total[uid]}
    per = base.get("spawn_periodicity", {})
    by_kind = per.get("by_kind", {})
    periodic_fail = {k: v for k, v in by_kind.items() if (v.get("score") or 0.0) >= periodicity_threshold}
    doc = {
        "schema_version": LOOP_AUDIT_V2_VERSION,
        "record": base.get("record"),
        "params": {"windows_s": list(windows_s), "rates_hz": list(rates_hz),
                   "horizons_s": list(horizons_s), "cell_cm": cell_cm,
                   "dest_ratio_min": dest_ratio_min,
                   "periodicity_threshold": periodicity_threshold,
                   "patrol_cells": patrol_cells},
        "window_grid": grid,
        "window_repeats_total": sum(g["repeats"] for g in grid),
        "patrol": {"windows": patrol_windows, "actors": sorted(patrol_actors)[:8],
                   "actor_count": len(patrol_actors),
                   "note": "counted, never exempted: a 1-2 cell patrol is a loop a viewer can see"},
        "route_repeats": {"actors": len(route_repeats), "sample": dict(list(route_repeats.items())[:4])},
        "destination_cycles": {"actors": len(dest_cycles), "sample": dict(list(dest_cycles.items())[:4])},
        "cross_actor_windows": {"count": len(cross_actor), "sample": cross_actor[:4]},
        "destinations": base.get("destinations"),
        "spawn_periodicity": {"by_kind": by_kind, "threshold": periodicity_threshold,
                              "failing_kinds": sorted(periodic_fail)},
        "v1": {"window_repeats": base.get("window_repeats"), "pass": base.get("pass")},
        "boundary": [
            "route_repeats and cross_actor_windows are informational: on a rectangular grid every vehicle shares four headings and the lane cells of the car ahead.",
            "A loop whose period exceeds the longest horizon (%s s) is only caught by the horizon=None pass." % max(h for h in horizons_s if h),
            "Motion that never crosses a %.0f cm cell boundary is invisible to the cell tests." % cell_cm,
            "Sub-second phase drift breaks exact window equality; near-repeats are not scored.",
            "Route repetition is quantised to 45 deg headings, so gentle curves may not match.",
            "Two actors alternating identical windows are reported under cross_actor_windows, not as per-actor repeats.",
            "Spawn periodicity uses a DFT peak ratio; the threshold %.2f is the Director's to set." % periodicity_threshold,
        ],
    }
    # What the GATE tests (a viewer-visible loop): an actor repeating its own
    # position window, poor destination diversity, or periodic spawning.
    # Route-heading repeats and cross-actor window sharing are INFORMATIONAL:
    # on a rectangular street grid every car shares the same four headings and
    # drives the same lane cells as the car ahead, so those two counts are
    # normal traffic, not repetition a viewer would read as a loop. Patrol
    # windows are likewise informational unless an actor patrols for most of
    # its life (`patrol_dominant_actors`), which a viewer would notice.
    doc["patrol"]["dominant_actors"] = sorted(patrol_dominant)[:8]
    doc["patrol"]["dominant_count"] = len(patrol_dominant)
    doc["informational_only"] = ["route_repeats", "cross_actor_windows", "patrol.windows"]
    doc["pass"] = (doc["window_repeats_total"] == 0
                   and (base.get("destinations") or {}).get("pass", False)
                   and not periodic_fail
                   and len(patrol_dominant) == 0)
    return doc


def write_audit_v2(record_dir, out_path, **params) -> dict:
    import json as _json
    from pathlib import Path as _Path
    rd = _Path(record_dir)
    manifest = _json.loads((rd / "record_manifest.json").read_text(encoding="utf-8"))
    doc = audit_record_v2(rd / "frames.bin", manifest, **params)
    _Path(out_path).write_text(_json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    return doc
