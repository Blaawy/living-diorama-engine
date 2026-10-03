"""Stage 2: sealed simulation -> facts. Evidence in, numbers out.

A FACT is a value this module computed by re-reading sealed artefacts, together
with the names of the artefacts it was computed from and one sentence saying
how. Nothing else in the factory may introduce a number: the story selector
chooses among facts, the narrator fills templates from facts, and the truth
audit resolves every stated number back to `facts.json` (or to a measured shot).

Before anything is computed the evidence is re-verified from disk -- the sealed
simulation result, every artefact it names, the rule manifest, the ledger
(re-derived by its registered extractors) and both records. A missing artefact,
a broken seal, a record that does not hash to its manifest, or a simulation
that belongs to a different brief is a refusal, not a smaller fact sheet.

Facts measured two independent ways are CROSS-CHECKED, and a disagreement is a
refusal too (`conflicting_consequence`): the agent event log says who replanned
and the record says whose path moved; the event log says who left and the
record says whose body is gone. The log is never evidence on its own.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .. import persistent_changes as pc
from ..closure import summarise_tripinfo
from ..evidence import verify_artifact_on_disk, verify_rule_manifest, verify_simulation_result
from . import FactoryError
from .brief import brief_hash
from .record import (Record, dist_to_segments, edge_half_width_cm, edge_segments, load_record,
                     trim_segments)
from .util import read_json, seal, sha256_file, verify_seal
from .world import street_name, twin_edge

FACTS_SCHEMA = "episode_facts_v1"

#: Measurement parameters. Stated here, written into facts.json, and identical
#: to the Phase 3 instruments they continue.
PARAMS = {
    "street_corridor_half_width_cm": 1500.0,   # both pavements of a street, from its edge line
    "street_end_trim_cm": 3000.0,              # the junction zone cut from each end of a street
    "carriageway_end_trim_cm": 1500.0,
    "divergence_threshold_cm": 100.0,          # two arms' paths "differ" beyond 1 m
    "stopped_speed_mps": 0.1,
}


class FactsError(FactoryError):
    stage = "facts"


def _fact(value: Any, unit: str, sources: list[str], how: str) -> dict[str, Any]:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FactsError("non_finite", f"a measurement came out non-finite ({how})")
        value = round(value, 3)
    return {"value": value, "unit": unit, "from": sorted(sources), "how": how}


def load_verified_simulation(sim_dir: Path, brief: dict[str, Any] | None) -> dict[str, Any]:
    """Re-verify a simulation directory from disk and return its documents."""
    sim = read_json(sim_dir / "simulation.json", "simulation.json", error=FactsError)
    result = read_json(sim_dir / "simulation_result.json", "simulation_result.json", error=FactsError)
    manifest = read_json(sim_dir / "rule_manifest.json", "rule_manifest.json", error=FactsError)
    try:
        verify_simulation_result(result)
        verify_rule_manifest(manifest)
    except Exception as e:  # noqa: BLE001
        raise FactsError("seal_broken", f"sealed simulation evidence does not verify: {e}")
    if brief is not None and sim.get("brief_sha256") != brief_hash(brief):
        raise FactsError("stale_lineage", "this simulation was run from a different brief "
                         f"({str(sim.get('brief_sha256'))[:12]}.. != {brief_hash(brief)[:12]}..)")
    if sim.get("simulation_result_hash") != result.get("result_hash"):
        raise FactsError("stale_lineage", "simulation.json does not name this simulation_result")
    if sim.get("rule_manifest_hash") != manifest.get("manifest_hash"):
        raise FactsError("stale_lineage", "simulation.json does not name this rule manifest")
    for name in sorted(result["artifacts"]):
        try:
            verify_artifact_on_disk(result, name, sim_dir)
        except Exception as e:  # noqa: BLE001
            code = "missing_evidence" if "not found" in str(e) else "corrupt_evidence"
            raise FactsError(code, f"sealed artefact {name!r}: {e}")
    try:
        ledger = pc.load(sim_dir / "persistent_changes.json", evidence_dir=sim_dir)
    except FileNotFoundError:
        raise FactsError("missing_evidence", "the consequence ledger is missing")
    except Exception as e:  # noqa: BLE001
        raise FactsError("corrupt_evidence", f"the consequence ledger does not verify against "
                                             f"its evidence: {e}")
    if ledger.get("ledger_hash") != sim.get("ledger_hash"):
        raise FactsError("stale_lineage", "simulation.json does not name this ledger")
    return {"sim": sim, "result": result, "manifest": manifest, "ledger": ledger}


def ledger_effects(ledger: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """metric -> {baseline, ruled, delta, unit, extractor}; refuses a contradiction."""
    out: dict[str, dict[str, Any]] = {}
    for e in ledger["entries"]:
        if e.get("change_type") != "measured_effect":
            continue
        p = e["payload"]
        row = {"baseline": p["baseline_value"], "ruled": p["ruled_value"], "delta": p["delta"],
               "unit": p["unit"], "extractor": e["provenance"]["extractor"]}
        prev = out.get(p["metric"])
        if prev is not None and any(prev[k] != row[k] for k in ("baseline", "ruled", "delta")):
            raise FactsError(
                "conflicting_consequence",
                f"two extractors measured {p['metric']!r} differently: {prev['extractor']} says "
                f"{prev['baseline']} -> {prev['ruled']}, {row['extractor']} says "
                f"{row['baseline']} -> {row['ruled']}")
        if prev is None:
            out[p["metric"]] = row
    return out


#: Vehicle-trip metrics the locked summariser reports. The walk metrics it also
#: reports are per walking STAGE, and a replan re-lays an agent's stages, so in
#: a world with agents they count stages rather than people and are not used.
TRIP_METRICS = ("trips_completed", "avg_duration_s", "avg_route_length_m",
                "avg_waiting_time_s", "avg_time_loss_s")


def _arrived(rec: Record, kind: str) -> int:
    """Actors of `kind` whose last sample precedes the record's final frame."""
    last = rec.frame_count - 1
    return sum(1 for t in rec.of_kind(kind) if len(t) and t.frames[-1] < last)


#: Per-trip agreement between tripinfo and the record, measured on the real episode
#: and both repeats (worst seen: route length 25 m / 1.6 %, waiting 1.1 s).
TRIP_ROUTE_TOL_M, TRIP_ROUTE_TOL_SHARE, TRIP_WAIT_TOL_S = 30.0, 0.03, 2.0
#: A teleported car leaves the record when it is lifted off the street and is
#: written to tripinfo when the teleport ends; that gap is bounded by this
#: (measured: 13.1 s at most).
TELEPORT_GAP_TOL_S = 30.0
#: The per-trip tolerances leave room for a SYSTEMATIC lie (every trip pushed to
#: the edge of its band). So the means are bound too. Measured on all three
#: runs: mean(route - track length) over cars that arrived: -2.6 .. -2.2 m in
#: every arm, so it may differ between the arms by at most ROUTE_OFFSET_DELTA_M;
#: mean(waiting - standing still): 0.06 .. 0.10 s.
ROUTE_OFFSET_MAX_M, ROUTE_OFFSET_DELTA_M, WAIT_OFFSET_MAX_S = 4.0, 1.0, 0.3
#: A repeat with another seed is another run: most trips end at another moment
#: (measured: see `repeat_runs` cross-checks). A copy re-encoded to look new does not.
REPEAT_MIN_SHARE_DIFFERENT = 0.25


def sumo_seed(tripinfo: Path) -> int | None:
    """The random seed SUMO wrote into the configuration header of its own output."""
    with Path(tripinfo).open("r", encoding="utf-8", errors="replace") as f:
        head = f.read(16384)
    m = re.search(r'<seed value="(-?\d+)"', head)
    return int(m.group(1)) if m else None


def _tripinfo_against_record(path: Path, rec: Record, teleport_s: float) -> dict[str, Any]:
    """Every vehicle trip in tripinfo against its own track in the record.

    The trip statistics come from tripinfo; the record is the trajectory itself.
    Every trip must match its own track: departure at the first sample, arrival
    at the last, duration = arrival - departure, route length = the distance the
    track covers, waiting time = the time the track stands still.

    A trip marked teleported (taken off the street by SUMO) must BE one: its track
    ends standing still for the whole teleport limit. Its arrival lies between its
    last sample and a bounded gap after it, and its route stops where it was lifted,
    so its length may only be longer than the track. The number of such trips is
    returned, to be held against the run report.

    Returns trips, disagreements, the first one, the teleported count, the mean
    offsets over the cars that arrived, and each trip's arrival second.
    """
    trips = bad = teleported = 0
    first = ""
    eps = rec.step + 1e-6
    seen: set[str] = set()
    route_off: list[float] = []
    wait_off: list[float] = []
    arrivals: dict[str, float] = {}
    for _e, el in ET.iterparse(str(path), events=("end",)):
        if el.tag != "tripinfo":
            continue
        trips += 1
        vid = el.get("id")
        why = ""
        tr = rec.tracks.get("vehicle:" + str(vid))
        try:
            dep, arr = float(el.get("depart")), float(el.get("arrival"))
            dur, rl = float(el.get("duration")), float(el.get("routeLength"))
            wait = float(el.get("waitingTime"))
        except (TypeError, ValueError):
            dep = arr = dur = rl = wait = float("nan")
        if vid in seen:
            why = "listed twice"
        elif tr is None or not len(tr):
            why = "no track in the record"
        elif not all(math.isfinite(v) for v in (dep, arr, dur, rl, wait)):
            why = "a field is missing or not a number"
        else:
            arrivals[str(vid)] = arr
            t0, t1 = rec.time_of(tr.frames[0]), rec.time_of(tr.frames[-1])
            path_m = sum(math.hypot(tr.x[i] - tr.x[i - 1], tr.y[i] - tr.y[i - 1])
                         for i in range(1, len(tr))) / 100.0
            still = sum(1 for s in tr.speed if s < 0.1) * rec.step
            tol_len = TRIP_ROUTE_TOL_M + TRIP_ROUTE_TOL_SHARE * rl
            if abs(t0 - dep) > eps:
                why = f"departs at {dep} s, the record at {t0:.1f} s"
            elif abs(dur - (arr - dep)) > 0.011:
                why = f"duration {dur} s is not arrival - departure ({arr - dep:.2f} s)"
            elif abs(still - wait) > TRIP_WAIT_TOL_S:
                why = f"waits {wait} s, the record stands still {still:.1f} s"
            elif el.get("vaporized") == "teleport":
                teleported += 1
                k = len(tr) - 1
                while k >= 0 and tr.speed[k] < 0.1:
                    k -= 1
                stand = (len(tr) - 1 - k) * rec.step
                if stand < teleport_s - 1.0:
                    why = (f"marked teleported, but its track ends standing still for {stand:.1f} s, "
                           f"not the {teleport_s:.0f} s teleport limit")
                elif not (t1 - eps <= arr <= t1 + TELEPORT_GAP_TOL_S):
                    why = f"teleported at {arr} s, the record ends at {t1:.1f} s"
                elif path_m > rl + tol_len:
                    why = f"route {rl} m, the record covers {path_m:.1f} m"
            elif abs(t1 - arr) > eps:
                why = f"arrives at {arr} s, the record at {t1:.1f} s"
            elif abs(path_m - rl) > tol_len:
                why = f"route {rl} m, the record covers {path_m:.1f} m"
            else:
                route_off.append(rl - path_m)
                wait_off.append(wait - still)
        seen.add(vid)
        if why:
            bad += 1
            first = first or f"vehicle {vid}: {why}"
        el.clear()

    def mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0
    return {"trips": trips, "bad": bad, "first": first, "teleported": teleported,
            "route_offset_m": mean(route_off), "wait_offset_s": mean(wait_off), "arrivals": arrivals}


def traffic_effects(sim_dir: Path, result: dict[str, Any], recs: dict[str, Record],
                    checks: list, seed_declared: int | None = None, teleport_s: float = 300.0,
                    trip_arrivals: dict[str, dict[str, float]] | None = None) -> dict[str, dict[str, Any]]:
    """Trip statistics per arm from the sealed tripinfo, with the record as referee.

    The summariser is Phase 1's locked `summarise_tripinfo` -- the function the
    registered closure extractor itself uses. The cross-checks are the one that
    extractor makes for vehicles (completed trips == vehicle arrivals in the
    record), the per-PERSON form of it (persons with a tripinfo entry == person
    arrivals in the record), every vehicle trip against its own track
    (`_tripinfo_against_record`), the teleported trips against the run report,
    the MEANS against the record (a systematic lie inside the per-trip bands),
    and the seed SUMO itself wrote into the file against the declared one.
    `trip_arrivals`, when given, receives each arm's per-trip arrival seconds.
    """
    summ: dict[str, dict[str, Any]] = {}
    tri: dict[str, dict[str, Any]] = {}
    for arm in ("baseline", "ruled"):
        try:
            path = verify_artifact_on_disk(result, f"{arm}_tripinfo", sim_dir)
            summ[arm] = summarise_tripinfo(path)
            persons = sum(1 for _e, el in ET.iterparse(str(path), events=("end",))
                          if el.tag == "personinfo")
        except ET.ParseError as e:
            raise FactsError("corrupt_evidence", f"{arm} tripinfo does not parse: {e}")
        except Exception as e:  # noqa: BLE001
            raise FactsError("corrupt_evidence", f"{arm} tripinfo: {e}")
        for what, logged, kind in (("vehicle trips completed", int(summ[arm]["trips_completed"]), "vehicle"),
                                   ("persons finished", persons, "person")):
            seen = _arrived(recs[arm], kind)
            checks.append({"name": f"{what} ({arm}): tripinfo vs record arrivals",
                           "event_log": logged, "record": seen, "agree": logged == seen})
        t = tri[arm] = _tripinfo_against_record(path, recs[arm], teleport_s)
        if trip_arrivals is not None:
            trip_arrivals[arm] = t["arrivals"]
        checks.append({"name": f"vehicle trips ({arm}): tripinfo depart, arrival, duration, route "
                               "length and waiting time vs the record, trip by trip "
                               "(trips / trips that agree)" + (f"; first disagreement: {t['first']}"
                                                               if t["first"] else ""),
                       "event_log": t["trips"], "record": t["trips"] - t["bad"], "agree": t["bad"] == 0})
        logged_tp = (result.get("run_report") or {}).get(arm, {}).get("teleports")
        checks.append({"name": f"teleported trips ({arm}): marked in tripinfo vs the sealed run report",
                       "event_log": t["teleported"], "record": logged_tp,
                       "agree": t["teleported"] == logged_tp})
        checks.append({"name": f"mean route length ({arm}): tripinfo minus the distance the record's "
                               f"tracks cover, cars that arrived (m; within {ROUTE_OFFSET_MAX_M})",
                       "event_log": round(t["route_offset_m"], 3), "record": 0.0,
                       "agree": abs(t["route_offset_m"]) <= ROUTE_OFFSET_MAX_M})
        checks.append({"name": f"mean waiting time ({arm}): tripinfo minus the time the record's "
                               f"tracks stand still, cars that arrived (s; within {WAIT_OFFSET_MAX_S})",
                       "event_log": round(t["wait_offset_s"], 3), "record": 0.0,
                       "agree": abs(t["wait_offset_s"]) <= WAIT_OFFSET_MAX_S})
        seed = sumo_seed(path)
        checks.append({"name": f"random seed ({arm}): the simulator's own configuration, as written "
                               "into its tripinfo, vs the seed this simulation declares",
                       "event_log": seed, "record": seed_declared, "agree": seed == seed_declared})
    d_off = tri["ruled"]["route_offset_m"] - tri["baseline"]["route_offset_m"]
    checks.append({"name": "change in mean route length: tripinfo vs the record's tracks, the two "
                           f"arms' offsets may differ by at most {ROUTE_OFFSET_DELTA_M} m",
                   "event_log": round(d_off, 3), "record": 0.0, "agree": abs(d_off) <= ROUTE_OFFSET_DELTA_M})
    out = {}
    for metric in TRIP_METRICS:
        b, r = summ["baseline"][metric], summ["ruled"][metric]
        out[metric] = {"baseline": b, "ruled": r, "delta": round(r - b, 4),
                       "unit": pc._EFFECT_UNITS[metric]}
    return out


def _share_different(a: dict[str, float], b: dict[str, float]) -> float:
    """Share of the trips both runs hold that end at a different second."""
    common = set(a) & set(b)
    if not common:
        return 1.0
    return sum(1 for k in common if abs(a[k] - b[k]) > 1e-6) / len(common)


def _check_seed_fields(sim: dict[str, Any], result: dict[str, Any], arm_docs: dict[str, Any],
                       checks: list, prefix: str) -> None:
    """The declared seed against the sealed result and each arm's own run report."""
    want = int(sim["seed"])
    rows = [("sealed simulation result", result.get("seed"))]
    rows += [(f"{arm} run report", (result.get("run_report") or {}).get(arm, {}).get("seed"))
             for arm in ("baseline", "ruled")]
    rows += [(f"{arm} agent log", arm_docs[arm].get("seed")) for arm in ("baseline", "ruled")]
    for what, got in rows:
        checks.append({"name": f"{prefix}random seed: {what} vs the seed simulation.json declares",
                       "event_log": got, "record": want, "agree": got == want})


def _seconds_in_corridor(rec: Record, uid: str, segs, half_cm: float, f_from: int) -> float:
    tr = rec.tracks.get(uid)
    if tr is None:
        return 0.0
    n = 0
    for i in tr.slice(f_from, rec.frame_count):
        if dist_to_segments(tr.x[i], tr.y[i], segs) <= half_cm:
            n += 1
    return n * rec.step


def _max_gap_cm(a: Record, b: Record, uid: str) -> float:
    ta, tb = a.tracks.get(uid), b.tracks.get(uid)
    if ta is None or tb is None:
        return 0.0
    worst, j, nb = 0.0, 0, len(tb)
    for i in range(len(ta)):
        f = ta.frames[i]
        while j < nb and tb.frames[j] < f:
            j += 1
        if j < nb and tb.frames[j] == f:
            d = math.hypot(ta.x[i] - tb.x[j], ta.y[i] - tb.y[j])
            if d > worst:
                worst = d
    return worst


#: Path-to-path distance is measured on samples this many seconds apart (a walker
#: covers ~0.7 m in 0.5 s, so the error is well under the metre the narration states).
PATH_SAMPLE_S = 0.5
_CELL_CM = 2000.0


def path_distance_cm(a: Record, b: Record, uid: str) -> float:
    """How far the path in `b` ever gets from the path in `a`, WHATEVER THE TIME.

    For every sampled point of the body's path in `b`, the distance to the
    nearest sampled point of its path in `a`; the largest of those. Unlike the
    same-instant gap this does not mix timing into geometry: a body that walks
    the same street a minute later has moved 0 m from its path.
    """
    ta, tb = a.tracks.get(uid), b.tracks.get(uid)
    if ta is None or tb is None or not len(ta) or not len(tb):
        return 0.0
    k = max(1, int(round(PATH_SAMPLE_S / a.step)))
    grid: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for i in list(range(0, len(ta), k)) + [len(ta) - 1]:
        x, y = ta.x[i], ta.y[i]
        grid.setdefault((int(x // _CELL_CM), int(y // _CELL_CM)), []).append((x, y))
    worst = 0.0
    for i in list(range(0, len(tb), k)) + [len(tb) - 1]:
        x, y = tb.x[i], tb.y[i]
        cx, cy = int(x // _CELL_CM), int(y // _CELL_CM)
        best, ring = float("inf"), 0
        # rings of cells outwards until no unexamined cell can hold a nearer point
        while best > max(0, ring - 1) * _CELL_CM:
            for gx in range(cx - ring, cx + ring + 1):
                for gy in range(cy - ring, cy + ring + 1):
                    if max(abs(gx - cx), abs(gy - cy)) != ring:
                        continue
                    for px, py in grid.get((gx, gy), ()):
                        d = math.hypot(px - x, py - y)
                        if d < best:
                            best = d
            ring += 1
        worst = max(worst, best)
    return worst


def longest_stops(rec: Record, kind: str, f_from: int, stopped: float) -> dict[str, tuple[int, int]]:
    """uid -> (frames, first frame) of each actor's longest unbroken standstill."""
    out: dict[str, tuple[int, int]] = {}
    for tr in rec.of_kind(kind):
        run, prev, start, best, best_start = 0, -2, -1, 0, -1
        for i in tr.slice(f_from, rec.frame_count):
            f = tr.frames[i]
            if tr.speed[i] < stopped:
                if f == prev + 1 and run:
                    run += 1
                else:
                    run, start = 1, f
                if run > best:
                    best, best_start = run, start
            else:
                run = 0
            prev = f
        if best:
            out[tr.uid] = (best, best_start)
    return out


def _longest_stop_s(rec: Record, kind: str, f_from: int, stopped: float) -> float:
    stops = longest_stops(rec, kind, f_from, stopped)
    return max((n for n, _ in stops.values()), default=0) * rec.step


def _vehicles_in_corridor(rec: Record, segs, half_cm: float, f_from: int) -> tuple[set[str], int]:
    """(vehicles ever inside the corridor from f_from on, last frame any was inside)."""
    seen: set[str] = set()
    last = -1
    xs = [s[0] for s in segs] + [s[2] for s in segs]
    ys = [s[1] for s in segs] + [s[3] for s in segs]
    x0, x1, y0, y1 = min(xs) - half_cm, max(xs) + half_cm, min(ys) - half_cm, max(ys) + half_cm
    for tr in rec.of_kind("vehicle"):
        for i in tr.slice(f_from, rec.frame_count):
            x, y = tr.x[i], tr.y[i]
            if x0 <= x <= x1 and y0 <= y <= y1 and dist_to_segments(x, y, segs) <= half_cm:
                seen.add(tr.uid)
                if tr.frames[i] > last:
                    last = tr.frames[i]
    return seen, last


def _agent_uid(i: int) -> str:
    return f"person:agent{i}"


def _closure_facts(facts: dict, docs: dict, recs: dict[str, Record], world: dict, net: Any,
                   sim_dir: Path, checks: list, extra: dict) -> None:
    sim, manifest = docs["sim"], docs["manifest"]
    at = float(manifest["applies_at_sim_second"])
    closed = list(manifest["change"]["close_edges"]["edge_ids"])
    base_ag = read_json(sim_dir / "agents_baseline.json", "agents_baseline.json", error=FactsError)
    ruled_ag = read_json(sim_dir / "agents_ruled.json", "agents_ruled.json", error=FactsError)
    twins = sorted(t for t in (twin_edge(e, net) for e in closed) if t and t not in closed)
    street = set(closed) | set(twins)
    f_at = recs["ruled"].frame_of(at)
    P = PARAMS
    REC = ["baseline_record_frames", "ruled_record_frames"]

    plan = ruled_ag["agent_plan"]
    if plan != base_ag["agent_plan"]:
        raise FactsError("uncontrolled_arms", "the two arms were given different agent plans")
    uids = [_agent_uid(r["i"]) for r in plan]
    for arm in ("baseline", "ruled"):
        absent = [u for u in uids if u not in recs[arm].tracks or not len(recs[arm].tracks[u])]
        if absent:
            raise FactsError("missing_evidence", f"{arm} record has no body for {absent[:4]}")

    # who planned to use the street: decided by the route SUMO gave the BASELINE
    # arm, never by what an agent later did
    routes0 = base_ag["initial_routes"]
    treatment = sorted(u for u in uids if street & set(routes0.get(u.split(":", 1)[1], ())))
    control = sorted(set(uids) - set(treatment))
    extra["groups"] = {"walkers": sorted(uids), "treatment": treatment, "control": control}
    extra["groups"]["other_people"] = sorted(t.uid for t in recs["baseline"].of_kind("person")
                                             if t.uid not in set(uids))

    closed_segs_full = [s for e in closed for s in edge_segments(net, e)]
    closed_mid = trim_segments(closed_segs_full, P["street_end_trim_cm"])
    name = street_name(closed[0], world, net)
    extra["streets"] = {"closed": {"edges": closed, "twins": twins, **name}}

    facts["walkers_followed"] = _fact(len(uids), "people", ["ruled_agents"],
                                      "agents in the world's declared agent plan")
    facts["other_people"] = _fact(
        len(recs["ruled"].of_kind("person")) - len(uids), "people", ["ruled_record_manifest", "ruled_agents"],
        "persons in the record that are not agents: they walk a fixed route and cannot replan")
    facts["blocks_closed"] = _fact(len(closed), "blocks", ["rule_manifest"],
                                   "edges the sealed rule manifest closes")
    facts["walkers_planned_through"] = _fact(
        len(treatment), "people", ["baseline_agents"],
        "agents whose first route in the baseline arm uses the street that the rule closes")
    facts["walkers_not_through"] = _fact(
        len(control), "people", ["baseline_agents"],
        "agents whose first route in the baseline arm does not use that street")

    # --- replans: the event log, cross-checked against the record ------------
    def reroutes(doc: dict) -> set[str]:
        out: set[str] = set()
        first_done: dict[str, float] = {}
        for e in doc["events"]:
            if e["kind"] == "goal_completed":
                first_done.setdefault(e["agent_id"], e["t_sim"])
        for e in doc["events"]:
            if (e["kind"] == "agent_rerouted" and e["payload"].get("avoided")
                    and e["payload"].get("route_changed")
                    and e["t_sim"] < first_done.get(e["agent_id"], float("inf"))):
                out.add(e["agent_id"])
        return out

    aid_to_uid = {"ped:%06d" % r["i"]: _agent_uid(r["i"]) for r in plan}
    rer_ruled = sorted(aid_to_uid[a] for a in reroutes(ruled_ag))
    rer_base = [e for e in base_ag["events"] if e["kind"] == "agent_rerouted"]
    if rer_base:
        raise FactsError("uncontrolled_arms", f"the baseline arm logged {len(rer_base)} reroute(s) "
                                              "with no rule in force; it is not a control")
    gap = {u: _max_gap_cm(recs["baseline"], recs["ruled"], u) for u in uids}
    moved = sorted(u for u in treatment if gap[u] > P["divergence_threshold_cm"])
    checks.append({"name": "walkers_changed_route: event log vs record",
                   "event_log": len(rer_ruled), "record": len(moved),
                   "agree": rer_ruled == moved})
    facts["walkers_changed_route"] = _fact(
        len(rer_ruled), "people", ["ruled_agents"] + REC,
        "agents that replanned around the closed street before reaching anything, and whose "
        "recorded path then differs from the baseline arm's by more than 1 m")
    facts["walkers_changed_route_without_rule"] = _fact(
        0, "people", ["baseline_agents"], "reroute events in the baseline arm")
    rer_t = sorted(e["t_sim"] for e in ruled_ag["events"]
                   if e["kind"] == "agent_rerouted" and e["payload"].get("route_changed"))
    if rer_t:
        facts["first_route_change_second"] = _fact(
            rer_t[0], "s", ["ruled_agents"], "simulation second of the first replan")
        facts["last_route_change_second"] = _fact(
            rer_t[-1], "s", ["ruled_agents"], "simulation second of the last replan")
        extra["reroute_times"] = {aid_to_uid[e["agent_id"]]: e["t_sim"] for e in ruled_ag["events"]
                                  if e["kind"] == "agent_rerouted" and e["payload"].get("route_changed")}

    # --- time on the closed street -------------------------------------------
    def mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    dwell = {arm: {u: _seconds_in_corridor(recs[arm], u, closed_mid,
                                           P["street_corridor_half_width_cm"], f_at)
                   for u in uids} for arm in ("baseline", "ruled")}
    for arm, tag in (("baseline", "without_rule"), ("ruled", "with_rule")):
        if treatment:
            facts[f"seconds_on_closed_street_{tag}"] = _fact(
                mean([dwell[arm][u] for u in treatment]), "s", [f"{arm}_record_frames"],
                "mean seconds each street-using agent's recorded body spent within 15 m of the "
                "closed street's line (junction ends cut), after the rule second")
        facts[f"walkers_seen_on_closed_street_{tag}"] = _fact(
            sum(1 for u in uids if dwell[arm][u] > 0), "people", [f"{arm}_record_frames"],
            "agents whose recorded body was ever on the closed street after the rule second")
    # what the narration states as "how far the path moved" is path to path, not the
    # same-instant gap above (which mixes timing into geometry and only decides
    # WHETHER a body diverged)
    shift = {u: path_distance_cm(recs["baseline"], recs["ruled"], u) for u in uids}
    if control:
        facts["control_path_shift_m"] = _fact(
            max(shift[u] for u in control) / 100.0, "m", REC,
            "largest distance, whatever the time, from any point of the ruled-arm path to the "
            "baseline path, over the agents whose route never used the closed street")
    if treatment:
        facts["path_shift_min_m"] = _fact(
            min(shift[u] for u in treatment) / 100.0, "m", REC,
            "smallest per-agent path-to-path distance (ruled path to baseline path)")
        facts["path_shift_max_m"] = _fact(
            max(shift[u] for u in treatment) / 100.0, "m", REC,
            "largest per-agent path-to-path distance: how far any point of an agent's new path "
            "is from the nearest point of its old path")

    # --- the detour street: where the street-using agents' time WENT ---------
    if treatment:
        best = None
        seen_pairs: set[frozenset] = set()
        for e in sorted(net.getEdges(), key=lambda e: e.getID()):
            eid = e.getID()
            pair = frozenset((e.getFromNode().getID(), e.getToNode().getID()))
            if eid in street or pair in seen_pairs or eid.startswith(":"):
                continue
            seen_pairs.add(pair)
            mid = trim_segments(edge_segments(net, eid), P["street_end_trim_cm"])
            if not mid:
                continue
            b = mean([_seconds_in_corridor(recs["baseline"], u, mid,
                                           P["street_corridor_half_width_cm"], f_at) for u in treatment])
            r = mean([_seconds_in_corridor(recs["ruled"], u, mid,
                                           P["street_corridor_half_width_cm"], f_at) for u in treatment])
            if best is None or (r - b) > best[0]:
                best = (r - b, eid, b, r)
        if best is not None and best[0] > 0:
            _gain, eid, b, r = best
            extra["streets"]["detour"] = {"edges": [eid], "twins": [t for t in [twin_edge(eid, net)] if t],
                                          **street_name(eid, world, net)}
            facts["seconds_on_detour_street_without_rule"] = _fact(
                b, "s", ["baseline_record_frames"],
                "mean seconds per street-using agent on the street that gained most of their time")
            facts["seconds_on_detour_street_with_rule"] = _fact(
                r, "s", ["ruled_record_frames"],
                "mean seconds per street-using agent on the street that gained most of their time")

    # --- arrivals -------------------------------------------------------------
    for arm, doc, tag in (("baseline", base_ag, "without_rule"), ("ruled", ruled_ag, "with_rule")):
        gone = sorted(u for u in uids
                      if recs[arm].tracks[u].frames[-1] < recs[arm].frame_count - 1)
        left_events = sorted({aid_to_uid[e["agent_id"]] for e in doc["events"]
                              if e["kind"] == "agent_body_left"})
        done_all = sorted(aid_to_uid[a] for a, st in doc["agent_final"].items()
                          if st["goals_left"] == 0)
        # A body's departure is logged on the agent tick AFTER it leaves. When
        # the last body's departure is what ends the simulation there is no
        # such tick, so the log may hold fewer departures than the record --
        # never one the record does not show.
        checks.append({"name": f"walkers_finished ({arm}): every logged departure is in the record",
                       "event_log": len(left_events), "record": len(gone),
                       "agree": set(left_events) <= set(gone)})
        checks.append({"name": f"walkers_finished ({arm}): goals completed vs record",
                       "event_log": len(done_all), "record": len(gone), "agree": done_all == gone})
        facts[f"walkers_finished_{tag}"] = _fact(
            len(gone), "people", [f"{arm}_record_frames", f"{arm}_agents"],
            "agents that completed every goal and whose body then left the simulation")
    if treatment:
        end = {arm: {u: recs[arm].time_of(recs[arm].tracks[u].frames[-1]) for u in treatment}
               for arm in ("baseline", "ruled")}
        deltas = [end["ruled"][u] - end["baseline"][u] for u in treatment]
        facts["trip_time_change_mean_s"] = _fact(
            mean(deltas), "s", REC, "mean over street-using agents of (last recorded second "
            "with the rule) minus (last recorded second without it)")
        facts["walkers_arrived_later"] = _fact(sum(1 for d in deltas if d > 0), "people", REC,
                                               "street-using agents whose trip ended later with the rule")
        facts["walkers_arrived_earlier"] = _fact(sum(1 for d in deltas if d < 0), "people", REC,
                                                 "street-using agents whose trip ended earlier with the rule")
        facts["trip_time_change_max_later_s"] = _fact(max(max(deltas), 0.0), "s", REC,
                                                      "largest delay of any street-using agent")
        facts["trip_time_change_max_earlier_s"] = _fact(max(-min(deltas), 0.0), "s", REC,
                                                        "largest time saved by any street-using agent")
        extra["trip_end_seconds"] = end
        extra["groups"]["walkers_later"] = sorted(u for u in treatment
                                                   if end["ruled"][u] > end["baseline"][u])
        extra["groups"]["walkers_earlier"] = sorted(u for u in treatment
                                                     if end["ruled"][u] < end["baseline"][u])

    # --- cars on the closed block ----------------------------------------------
    half = max(edge_half_width_cm(net, e) for e in closed)
    road = trim_segments(closed_segs_full, P["carriageway_end_trim_cm"])
    used = {}
    for arm, tag in (("baseline", "without_rule"), ("ruled", "with_rule")):
        seen, last = _vehicles_in_corridor(recs[arm], road, half, f_at + 1)
        used[arm] = (seen, last)
        facts[f"cars_on_closed_block_{tag}"] = _fact(
            len(seen), "cars", [f"{arm}_record_frames"],
            "distinct vehicles recorded on the closed block's own carriageway after the rule second")
    extra["groups"]["cars_on_closed_block"] = sorted(used["baseline"][0])
    facts["opposite_direction_open"] = _fact(
        bool(twins), "flag", ["rule_manifest"],
        "the same street's other direction is a separate edge the rule does not close")
    if twins:
        t_half = max(edge_half_width_cm(net, e) for e in twins)
        t_road = trim_segments([s_ for e in twins for s_ in edge_segments(net, e)],
                               P["carriageway_end_trim_cm"])
        for arm, tag in (("baseline", "without_rule"), ("ruled", "with_rule")):
            seen_t, _last = _vehicles_in_corridor(recs[arm], t_road, t_half, f_at + 1)
            facts[f"cars_on_open_side_{tag}"] = _fact(
                len(seen_t), "cars", [f"{arm}_record_frames"],
                "distinct vehicles recorded on the other direction of the same block after the rule second")
    if used["ruled"][1] >= 0:
        facts["last_car_on_closed_block_second"] = _fact(
            recs["ruled"].time_of(used["ruled"][1]), "s", ["ruled_record_frames"],
            "last simulation second any vehicle was recorded on the closed block, with the rule")
    rr = docs["result"]["run_report"]["ruled"]
    if int(rr.get("vehicle_reroutes_changed", 0)) > int(rr.get("vehicle_reroutes_attempted", 0)):
        raise FactsError("conflicting_consequence", "more vehicle routes changed than were attempted")
    facts["cars_rerouted"] = _fact(int(rr.get("vehicle_reroutes_changed", 0)), "cars", ["ruled_agents"],
                                   "vehicles whose route was changed by a travel-time reroute off the closed block")
    facts["cars_asked_to_reroute"] = _fact(
        int(rr.get("vehicle_reroutes_attempted", 0)), "cars", ["ruled_agents"],
        "vehicles whose remaining route crossed the closed block when the rule applied or when they departed")
    rerouted = sorted("vehicle:" + v for v in ruled_ag.get("vehicles_rerouted") or [])
    not_rerouted = sorted("vehicle:" + v for v in ruled_ag.get("vehicles_not_rerouted") or [])
    checks.append({"name": "rerouted vehicles: listed ids vs the run report's count",
                   "event_log": len(rerouted), "record": int(rr.get("vehicle_reroutes_changed", 0)),
                   "agree": len(rerouted) == int(rr.get("vehicle_reroutes_changed", 0))
                   and len(rerouted) + len(not_rerouted) == int(rr.get("vehicle_reroutes_attempted", 0))})
    extra["groups"]["cars_rerouted"] = rerouted
    facts["cars_found_no_other_way"] = _fact(
        len(not_rerouted), "cars", ["ruled_agents"],
        "vehicles whose route still crossed the closed block after the router was asked for another")
    # --- cars whose trip BEGINS on the closed block ---------------------------
    base_v = {t.uid for t in recs["baseline"].of_kind("vehicle")}
    ruled_v = {t.uid for t in recs["ruled"].of_kind("vehicle")}
    absent = sorted(base_v - ruled_v)
    starts: dict[str, tuple[float, str]] = {}
    for rp in world["_route_paths"]:
        for el in ET.parse(rp).getroot():
            if el.tag == "vehicle":
                r = el.find("route")
                edges = (r.get("edges") if r is not None else "").split()
                if edges:
                    starts["vehicle:" + el.get("id", "")] = (float(el.get("depart", "0")), edges[0])
    never = sorted(v for v in absent if v in starts and starts[v][1] in closed and starts[v][0] >= at)
    extra["groups"]["cars_never_started"] = never
    checks.append({"name": "cars absent from the ruled record are exactly those that depart on "
                           "the closed block after the rule",
                   "event_log": len(never), "record": len(absent), "agree": never == absent})
    facts["cars_never_started"] = _fact(
        len(never), "cars", REC + ["route_files"],
        "vehicles whose route begins on the closed block after the rule second; the simulator "
        "never inserted them, so they are in the baseline record and absent from the ruled one")

    # --- cars the SIMULATOR had to move ---------------------------------------
    limit = float(world["sumo"]["time_to_teleport"])
    stops = longest_stops(recs["ruled"], "vehicle", f_at, P["stopped_speed_mps"])
    stuck = {u: (n, s) for u, (n, s) in stops.items() if n * recs["ruled"].step >= limit}
    facts["cars_stood_until_moved"] = _fact(
        len(stuck), "cars", ["ruled_record_frames"],
        "vehicles recorded standing still for the simulator's whole teleport limit, with the rule")
    facts["teleport_limit_s"] = _fact(limit, "s", ["world"],
                                      "seconds a vehicle may stand before SUMO moves it itself")
    facts["teleport_limit_minutes"] = _fact(limit / 60.0, "min", ["world"],
                                            "the same limit in minutes")
    checks.append({"name": "cars that stood for the whole teleport limit are exactly those the "
                           "router could not move off the closed block",
                   "event_log": len(not_rerouted), "record": len(stuck),
                   "agree": sorted(stuck) == not_rerouted})
    checks.append({"name": "cars that stood for the whole teleport limit vs teleports SUMO reports",
                   "event_log": int(rr.get("teleports", 0)), "record": len(stuck),
                   "agree": int(rr.get("teleports", 0)) == len(stuck)})
    stuck_doc = {}
    for u, (n, s0) in sorted(stuck.items(), key=lambda kv: (kv[1][1], kv[0])):
        tr = recs["ruled"].tracks[u]
        i_last = tr.index_at(s0 + n - 1)
        row = {"from_s": round(recs["ruled"].time_of(s0), 3),
               "to_s": round(recs["ruled"].time_of(s0 + n - 1), 3),
               "at_cm": [round(tr.x[i_last], 1), round(tr.y[i_last], 1)]}
        if i_last + 1 < len(tr):
            row["next_seen_s"] = round(recs["ruled"].time_of(tr.frames[i_last + 1]), 3)
            row["jump_m"] = round(math.hypot(tr.x[i_last + 1] - tr.x[i_last],
                                             tr.y[i_last + 1] - tr.y[i_last]) / 100.0, 2)
        stuck_doc[u] = row
    extra["stuck_cars"] = stuck_doc
    plain = [e for e in sorted(net.getEdges(), key=lambda e: e.getID())
             if not e.getID().startswith(":")]
    geom = {e.getID(): edge_segments(net, e.getID()) for e in plain}

    def street_of(x: float, y: float) -> str:
        return min(geom, key=lambda eid: (dist_to_segments(x, y, geom[eid]), eid))

    def named(eid: str) -> dict:
        return {"edges": [eid], "twins": [t for t in [twin_edge(eid, net)] if t],
                **street_name(eid, world, net)}

    for u, row in stuck_doc.items():
        row["edge"] = street_of(*row["at_cm"])
    if stuck_doc:
        extra["streets"]["jam"] = named(next(iter(stuck_doc.values()))["edge"])
    goal = plan[[_agent_uid(r["i"]) for r in plan].index(treatment[0])]["stages"][1] if treatment else None
    if goal:
        extra["streets"]["destination"] = named(goal)
    c_goal = plan[[_agent_uid(r["i"]) for r in plan].index(control[0])]["stages"][1] if control else None
    if c_goal:
        extra["streets"]["control_path"] = named(c_goal)
    taken = {frozenset((net.getEdge(eid).getFromNode().getID(), net.getEdge(eid).getToNode().getID()))
             for st in extra["streets"].values() for eid in st["edges"]}
    load: dict[str, int] = {}
    pair_edge: dict[frozenset, str] = {}
    for e in plain:
        pair = frozenset((e.getFromNode().getID(), e.getToNode().getID()))
        pair_edge.setdefault(pair, e.getID())
    mids = {eid: trim_segments(geom[eid], P["street_end_trim_cm"]) for eid in pair_edge.values()}
    for tr in recs["baseline"].of_kind("vehicle"):
        for i in range(0, len(tr), 20):
            for eid, mid in mids.items():
                if mid and dist_to_segments(tr.x[i], tr.y[i], mid) <= P["street_corridor_half_width_cm"]:
                    load[eid] = load.get(eid, 0) + 1
                    break
    free = sorted((-n, eid) for eid, n in load.items()
                  if frozenset((net.getEdge(eid).getFromNode().getID(),
                                net.getEdge(eid).getToNode().getID())) not in taken)
    if free:
        extra["streets"]["main"] = named(free[0][1])
    extra["groups"]["stuck_cars"] = list(stuck_doc)
    jumps = [r["jump_m"] for r in stuck_doc.values() if "jump_m" in r]
    if jumps:
        facts["moved_car_jump_min_m"] = _fact(
            min(jumps), "m", ["ruled_record_frames"],
            "smallest distance between a stuck vehicle's last standing position and where the "
            "record next shows it")
    extra["agent_policy"] = {"policy": world["agents"].get("policy"),
                             "perceived_blocked": closed, "avoided_by_policy": twins}
    facts["rule_second"] = _fact(at, "s", ["ruled_agents"], "simulation second the rule took effect")
    applied = ruled_ag.get("rules_applied") or []
    checks.append({"name": "rule applied once, at its declared second, in the ruled arm only",
                   "event_log": [a.get("at_second") for a in applied], "record": at,
                   "agree": len(applied) == 1 and abs(applied[0]["at_second"] - at) <= recs["ruled"].step
                   and not base_ag.get("rules_applied")})
    _ = sim


def extract_facts(sim_dir: str | Path, brief: dict[str, Any], world: dict[str, Any], *,
                  replicate_dirs: list[Path] | None = None) -> dict[str, Any]:
    """Compute the sealed fact sheet for one simulated episode."""
    import sumolib

    sim_dir = Path(sim_dir)
    docs = load_verified_simulation(sim_dir, brief)
    sim, result, manifest, ledger = docs["sim"], docs["result"], docs["manifest"], docs["ledger"]
    recs: dict[str, Record] = {}
    for arm in ("baseline", "ruled"):
        try:
            recs[arm] = load_record(sim_dir / f"record_{arm}")
        except FactoryError as e:
            raise FactsError("corrupt_evidence" if e.code != "missing" else "missing_evidence",
                             f"{arm} record: {e.message}")
        if recs[arm].frames_sha256 != result["artifacts"][f"{arm}_record_frames"]["sha256"]:
            raise FactsError("stale_lineage", f"{arm} record is not the one the sealed result names")
    net = sumolib.net.readNet(world["_net_path"])

    facts: dict[str, Any] = {}
    checks: list[dict[str, Any]] = []
    extra: dict[str, Any] = {}
    at = float(manifest["applies_at_sim_second"])
    f_at = recs["ruled"].frame_of(at)

    # --- the world, as recorded ------------------------------------------------
    for arm, tag in (("baseline", "without_rule"), ("ruled", "with_rule")):
        by_kind = recs[arm].manifest["counts"]["by_kind"]
        facts[f"people_recorded_{tag}"] = _fact(int(by_kind.get("person", 0)), "people",
                                                [f"{arm}_record_manifest"], "persons in the record")
        facts[f"cars_recorded_{tag}"] = _fact(int(by_kind.get("vehicle", 0)), "cars",
                                              [f"{arm}_record_manifest"], "vehicles in the record")
        facts[f"longest_car_stop_{tag}_s"] = _fact(
            _longest_stop_s(recs[arm], "vehicle", f_at, PARAMS["stopped_speed_mps"]), "s",
            [f"{arm}_record_frames"],
            "longest unbroken time any one vehicle was recorded standing still, after the rule second")
        facts[f"cars_teleported_{tag}"] = _fact(
            int(result["run_report"][arm].get("teleports", 0)), "cars", [f"{arm}_agents"],
            "vehicles the simulator itself moved because they were stuck (SUMO teleports)")
    facts["time_limit_seconds"] = _fact(float(sim["end_seconds"]), "s", ["rule_manifest"],
                                        "the longest either arm was allowed to run")
    for arm, tag in (("baseline", "without_rule"), ("ruled", "with_rule")):
        secs = recs[arm].frame_count * recs[arm].step
        facts[f"city_busy_seconds_{tag}"] = _fact(
            secs, "s", [f"{arm}_record_manifest"],
            "simulated seconds until the last car and the last person had finished")
        facts[f"city_busy_minutes_{tag}"] = _fact(
            secs / 60.0, "min", [f"{arm}_record_manifest"],
            "simulated minutes until the last car and the last person had finished")
    facts["arms_run"] = _fact(len(result["run_report"]), "runs", ["simulation_result"],
                              "arms in the sealed simulation result: one without the rule, one with it")
    facts["random_seed"] = _fact(int(sim["seed"]), "seed", ["simulation_result"],
                                 "the one random seed both arms were run with")
    arm_docs = {arm: read_json(sim_dir / f"agents_{arm}.json", f"agents_{arm}.json", error=FactsError)
                for arm in ("baseline", "ruled")}
    facts["seeds_used"] = _fact(len({int(d.get("seed", -1)) for d in arm_docs.values()}), "seeds",
                                ["baseline_agents", "ruled_agents"],
                                "distinct random seeds across the two arms' own run reports")
    if facts["seeds_used"]["value"] != 1 or int(arm_docs["ruled"].get("seed", -1)) != int(sim["seed"]):
        raise FactsError("uncontrolled_arms", "the two arms were not run with the one declared seed")
    _check_seed_fields(sim, result, arm_docs, checks, "")
    for arm in ("baseline", "ruled"):
        rr_arm = result["run_report"].get(arm) or {}
        for key in ("teleports", "vehicle_reroutes_attempted", "vehicle_reroutes_changed",
                    "agents_spawned", "steps"):
            checks.append({"name": f"{key} ({arm}): sealed run report vs the arm's own agent log",
                           "event_log": arm_docs[arm].get(key), "record": rr_arm.get(key),
                           "agree": key in rr_arm and arm_docs[arm].get(key) == rr_arm.get(key)})
    facts["rules_applied_without_rule"] = _fact(
        len(arm_docs["baseline"].get("rules_applied") or []), "rules", ["baseline_agents"],
        "rules applied in the baseline arm")
    facts["rules_applied_with_rule"] = _fact(
        len(arm_docs["ruled"].get("rules_applied") or []), "rules", ["ruled_agents"],
        "rules applied in the ruled arm")

    # --- trip statistics: the locked summariser, the record as referee ---------
    teleport_s = float(world["sumo"]["time_to_teleport"])
    episode_arrivals: dict[str, dict[str, float]] = {}
    effects = traffic_effects(sim_dir, result, recs, checks, int(sim["seed"]), teleport_s,
                              episode_arrivals)
    for metric, row in sorted(ledger_effects(ledger).items()):
        mine = effects.get(metric)
        if mine is not None and any(abs(float(mine[k]) - float(row[k])) > 1e-6
                                    for k in ("baseline", "ruled")):
            raise FactsError(
                "conflicting_consequence",
                f"the ledger's registered extractor measured {metric!r} as {row['baseline']} -> "
                f"{row['ruled']}, the fact extractor as {mine['baseline']} -> {mine['ruled']}")
    for arm, tag in (("baseline", "without_rule"), ("ruled", "with_rule")):
        facts[f"cars_not_finished_{tag}"] = _fact(
            facts[f"cars_recorded_{tag}"]["value"] - int(effects["trips_completed"][arm]), "cars",
            [f"{arm}_record_manifest", f"{arm}_tripinfo"],
            "vehicles in the record that had not finished their trip when the simulated time ran out")
    for metric, row in sorted(effects.items()):
        src = ["baseline_tripinfo", "ruled_tripinfo"]
        how = "ldyf.closure.summarise_tripinfo over the sealed tripinfo of each arm"
        facts[f"{metric}_without_rule"] = _fact(float(row["baseline"]), row["unit"], src, how)
        facts[f"{metric}_with_rule"] = _fact(float(row["ruled"]), row["unit"], src, how)
        facts[f"{metric}_change"] = _fact(abs(float(row["delta"])), row["unit"], src,
                                          how + " (size of the change)")
        facts[f"{metric}_direction"] = _fact(
            "increase" if row["delta"] > 0 else "decrease" if row["delta"] < 0 else "no_change",
            "direction", src, how + " (sign of the change)")
        if float(row["baseline"]) > 0:
            facts[f"{metric}_change_percent"] = _fact(
                abs(float(row["delta"])) / float(row["baseline"]) * 100.0, "%", src,
                how + " (size of the change as a share of the value without the rule)")
    if float(effects["avg_duration_s"]["delta"]) > 0 and float(effects["avg_waiting_time_s"]["delta"]) > 0:
        facts["waiting_share_of_extra_time_percent"] = _fact(
            float(effects["avg_waiting_time_s"]["delta"]) / float(effects["avg_duration_s"]["delta"]) * 100.0,
            "%", ["baseline_tripinfo", "ruled_tripinfo"],
            "the rise in mean waiting time as a share of the rise in mean trip time")

    # --- the prediction, declared before the run -------------------------------
    pred = manifest["prediction"]
    metric = pred.get("metric")
    if metric not in effects:
        raise FactsError("prediction_unmeasured",
                         f"the brief predicted {metric!r}, which no extractor measured for this rule "
                         f"(measured: {sorted(effects)})")
    measured_dir = facts[f"{metric}_direction"]["value"]
    facts["prediction_direction"] = _fact(pred["direction"], "direction", ["rule_manifest"],
                                          "declared in the sealed rule manifest before the run")
    facts["prediction_declared_before_run"] = _fact(
        bool(pred.get("declared_before_run")), "flag", ["rule_manifest"],
        "the sealed rule manifest, hashed before the simulator started, carries the prediction")
    facts["prediction_outcome"] = _fact(
        "confirmed" if measured_dir == pred["direction"] else "contradicted", "outcome",
        ["rule_manifest", "baseline_tripinfo", "ruled_tripinfo"],
        "the declared direction compared with the sign of the measured change")
    extra["prediction"] = {"metric": metric, "text": pred["text"], "declared": pred["direction"],
                           "measured": measured_dir}

    if sim["rule_change_type"] == "edge_closure":
        _closure_facts(facts, docs, recs, world, net, sim_dir, checks, extra)

    # --- repeats with other random seeds ---------------------------------------
    reps = []
    # A repeat counts only if it is a DIFFERENT run: its own sealed result, its own
    # records, and a seed that the simulator itself (not only simulation.json,
    # which carries no seal) says it used.
    seen_results = {result["result_hash"]}
    seen_runs: list[tuple[str, dict[str, dict[str, float]]]] = []
    seen_records = {recs[a].frames_sha256 for a in ("baseline", "ruled")}
    for rd in replicate_dirs or []:
        rdocs = load_verified_simulation(Path(rd), None)
        name = Path(rd).name
        if rdocs["manifest"]["manifest_hash"] != manifest["manifest_hash"]:
            raise FactsError("uncontrolled_arms", f"replicate {name} ran a different rule")
        if rdocs["sim"]["seed"] == sim["seed"]:
            raise FactsError("uncontrolled_arms", f"replicate {name} reuses the episode's seed")
        if rdocs["result"]["result_hash"] in seen_results:
            raise FactsError("uncontrolled_arms", f"replicate {name} is a run already counted "
                                                  "(its sealed result is not a new one)")
        seen_results.add(rdocs["result"]["result_hash"])
        rarm_docs = {arm: read_json(Path(rd) / f"agents_{arm}.json", f"replicate {name} agents_{arm}.json",
                                    error=FactsError) for arm in ("baseline", "ruled")}
        _check_seed_fields(rdocs["sim"], rdocs["result"], rarm_docs, checks, f"replicate {name} ")
        rrecs = {}
        for arm in ("baseline", "ruled"):
            try:
                rrecs[arm] = load_record(Path(rd) / f"record_{arm}")
            except FactoryError as e:
                raise FactsError("corrupt_evidence",
                                 f"replicate {name} {arm} record: {e.message}")
            if rrecs[arm].frames_sha256 in seen_records:
                raise FactsError("uncontrolled_arms", f"replicate {name} {arm} record is a record "
                                                      "already counted")
            seen_records.add(rrecs[arm].frames_sha256)
        rarr: dict[str, dict[str, float]] = {}
        reff = traffic_effects(Path(rd), rdocs["result"], rrecs, checks, int(rdocs["sim"]["seed"]),
                               teleport_s, rarr)
        for other_name, other in [("the episode", episode_arrivals)] + seen_runs:
            for arm in ("baseline", "ruled"):
                share = _share_different(rarr[arm], other[arm])
                checks.append({"name": f"replicate {name} {arm}: share of trips ending at another "
                                       f"second than in {other_name} (at least "
                                       f"{REPEAT_MIN_SHARE_DIFFERENT}: another seed is another run)",
                               "event_log": round(share, 4), "record": REPEAT_MIN_SHARE_DIFFERENT,
                               "agree": share >= REPEAT_MIN_SHARE_DIFFERENT})
        seen_runs.append((f"replicate {name}", rarr))
        d = float(reff[metric]["delta"])
        reps.append({"seed": rdocs["sim"]["seed"], "delta": d,
                     "direction": "increase" if d > 0 else "decrease" if d < 0 else "no_change",
                     "simulation_result_hash": rdocs["result"]["result_hash"]})
    if reps:
        facts["repeat_runs"] = _fact(len(reps), "runs", ["replicates"],
                                     "further episodes run with other seeds and the same rule")
        facts["repeat_runs_same_direction"] = _fact(
            sum(1 for r in reps if r["direction"] == measured_dir), "runs", ["replicates"],
            "repeats in which the predicted metric moved the same way as in this episode")
        facts["all_runs"] = _fact(len(reps) + 1, "runs", ["replicates"],
                                  "this episode plus its repeats")
        facts["all_runs_same_direction"] = _fact(
            sum(1 for r in reps if r["direction"] == measured_dir) + 1, "runs", ["replicates"],
            "runs, this episode included, in which the predicted metric moved the way it did here")
        extra["replicates"] = sorted(reps, key=lambda r: r["seed"])

    bad = [c for c in checks if not c["agree"]]
    if bad:
        raise FactsError("conflicting_consequence",
                         "two independent measurements disagree: " + "; ".join(
                             f"{c['name']} ({c['event_log']} vs {c['record']})" for c in bad))

    doc = {
        "schema_version": FACTS_SCHEMA,
        "brief_sha256": brief_hash(brief),
        "simulation_result_hash": result["result_hash"],
        "rule_manifest_hash": manifest["manifest_hash"],
        "ledger_hash": ledger["ledger_hash"],
        "rule_change_type": sim["rule_change_type"],
        "records": {arm: recs[arm].frames_sha256 for arm in ("baseline", "ruled")},
        "artifacts": {k: v["sha256"] for k, v in sorted(result["artifacts"].items())},
        "parameters": PARAMS,
        "facts": dict(sorted(facts.items())),
        "cross_checks": checks,
        **extra,
        "facts_hash": "",
    }
    return seal(doc, "facts_hash")


def load_facts(path: str | Path) -> dict[str, Any]:
    doc = read_json(path, "facts.json", error=FactsError)
    if doc.get("schema_version") != FACTS_SCHEMA:
        raise FactsError("bad_version", f"facts.json declares {doc.get('schema_version')!r}")
    try:
        verify_seal(doc, "facts_hash", "facts.json")
    except FactoryError as e:
        raise FactsError("corrupt_evidence", e.message)
    return doc


_ = sha256_file  # re-exported for callers that hash fact inputs
