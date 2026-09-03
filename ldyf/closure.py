"""Road closure that does not kill the simulation.

Why this module exists
----------------------
SUMO 1.27.1 **crashes** (0xC0000409 stack buffer overrun / 0xC0000005 access
violation) when a `<closingReroute>` is active and pedestrians are present. It
leaves a truncated output file and writes nothing to stderr, so an unchecked
run looks like it succeeded. That is RISK-1 from the Phase 1 red team, and it
sits directly on the Director's example episode ("close the bridge") in a world
that must contain people.

The fix is not to remove pedestrians. It is to stop using `closingReroute` and
close the road the way a road actually closes: **the carriageway is barred to
motor traffic and the footway stays open.**

Method
------
TraCI is authoritative. At the closure instant we set lane permissions on the
*vehicle-carrying lanes only*, then reroute the vehicles that needed that edge.
`closingReroute` is never used anywhere in this module, which is what makes the
crash unreachable. Pedestrian infrastructure is additionally never modified, for
the separate semantic reason given below.

What actually fixes the crash, stated precisely
-----------------------------------------------
Measured, not assumed. An adversarial test closed the footway lanes too, through
TraCI, and SUMO exited 0 with complete output. So:

  * The crash belongs to the `<closingReroute>` rerouter mechanism combined with
    pedestrians -- **not** to barring pedestrians as such.
  * This module avoids the crash because it never uses `closingReroute` at all,
    not because it spares footways.

The pedestrian guard below is therefore a **semantic** guarantee, not the
crash fix. It is still load-bearing for correctness, for two reasons measured in
Phase 1: a statically unscoped closure makes SUMO refuse the run outright
("Error: Disconnected walk for person '0'. Quitting (on error)."), and closing a
footway changes pedestrian behaviour in a way that is simply not what "the road
is closed" means.

The structural guarantee (DNA-03)
---------------------------------
`select_closable_lanes` refuses to return any lane that permits pedestrians, so
there is no code path in this module through which a road closure can touch a
footway. Pedestrian access is preserved by construction, not by discipline.

Determinism
-----------
Every iteration over SUMO ids is sorted before use, and the closure fires on an
integer step index rather than a float comparison, so two runs with the same
seed issue byte-identical command sequences.
"""

from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import sumolib
import traci

PEDESTRIAN_VCLASS = "pedestrian"
DEFAULT_DISALLOW = ("passenger", "truck", "bus", "motorcycle", "trailer", "coach", "delivery")


class ClosureError(RuntimeError):
    """Raised when a closure would be unsafe or a run did not complete cleanly."""


@dataclass(frozen=True)
class ClosureSpec:
    """One road closure. The independent variable of a ONE RULE episode."""

    edge_ids: tuple[str, ...]
    at_second: float = 0.0
    disallow: tuple[str, ...] = DEFAULT_DISALLOW

    def __post_init__(self) -> None:
        if not self.edge_ids:
            raise ClosureError("a closure must name at least one edge")
        if PEDESTRIAN_VCLASS in self.disallow:
            raise ClosureError(
                "refusing to disallow pedestrians: a road closure closes the "
                "carriageway, not the footway. (Measured: barring pedestrians "
                "through TraCI does NOT itself crash SUMO -- the 1.27.1 crash "
                "belongs to the <closingReroute> mechanism, which this module "
                "never uses. This guard exists for semantic correctness.)"
            )
        if self.at_second < 0:
            raise ClosureError("at_second must not be negative")


@dataclass
class RunResult:
    exit_code: int | None = None
    steps: int = 0
    sim_seconds: float = 0.0
    wall_seconds: float = 0.0
    vehicles_arrived: int = 0
    persons_loaded: int = 0
    closure_applied_at_step: int | None = None
    lanes_closed: tuple[str, ...] = ()

    # Reroute accounting. These are deliberately separate: a TraCI call that
    # returns without raising proves only that the COMMAND succeeded, not that
    # the vehicle changed its route. Routes are captured before and after and
    # compared edge-for-edge, so "rerouted" means the route actually changed.
    reroute_requests: int = 0
    reroute_successes: int = 0
    routes_actually_changed: int = 0
    routes_unchanged: int = 0
    reroute_failures: int = 0
    # Vehicles physically on a closed lane at the closure instant cannot be
    # rerouted off it; they must exit. They are counted here, NOT as requests.
    vehicles_on_closed_lane_at_closure: int = 0
    # Measured from the FCD after the run: entries onto a closed edge after the
    # closure instant. The closure's own effect, artefact-derived. Must be 0.
    post_closure_entries_onto_closed_edges: int | None = None
    # SUMO's own teleport count, parsed from its statistics output.
    teleports: int = 0

    outputs_valid: dict[str, bool] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return self.exit_code == 0 and all(self.outputs_valid.values())

    @property
    def vehicles_rerouted(self) -> int:
        """The honest figure: vehicles whose route genuinely changed.

        Kept as a read-only alias so no caller can set it to a command count.
        """
        return self.routes_actually_changed


# --- lane selection: the structural guarantee -----------------------------


def select_closable_lanes(
    net_path: str | Path, edge_ids: Sequence[str], disallow: Sequence[str]
) -> list[str]:
    """Return the lanes on `edge_ids` that may be closed to motor traffic.

    A lane qualifies only if it carries at least one of the `disallow` classes
    **and** does not permit pedestrians. Footways therefore can never be
    returned, which is what keeps walks connected and the simulator alive.
    """
    net = sumolib.net.readNet(str(net_path))
    known = {e.getID() for e in net.getEdges()}
    missing = [e for e in edge_ids if e not in known]
    if missing:
        raise ClosureError(f"edges not in network: {missing}")

    chosen: list[str] = []
    for eid in sorted(edge_ids):
        for lane in net.getEdge(eid).getLanes():
            allows_pedestrians = lane.allows(PEDESTRIAN_VCLASS)
            carries_traffic = any(lane.allows(c) for c in disallow)
            if allows_pedestrians and carries_traffic:
                # A shared lane cannot be closed to traffic without closing the
                # footway. Refuse outright rather than report a closure that
                # leaves the road open (round-3 finding 5).
                raise ClosureError(
                    f"lane {lane.getID()} on {eid} is shared by pedestrians and "
                    f"{[c for c in disallow if lane.allows(c)]}; refusing a partial closure"
                )
            if allows_pedestrians:
                continue  # footway: never touched
            if carries_traffic:
                chosen.append(lane.getID())
    if not chosen:
        raise ClosureError(
            f"no closable vehicle lanes found on {list(edge_ids)}; refusing to "
            "pretend a closure happened"
        )
    return sorted(chosen)


def assert_pedestrian_access_preserved(net_path: str | Path, lanes: Sequence[str]) -> None:
    """Independent re-check that no selected lane is a footway."""
    net = sumolib.net.readNet(str(net_path))
    by_id = {ln.getID(): ln for e in net.getEdges() for ln in e.getLanes()}
    offenders = [l for l in lanes if l in by_id and by_id[l].allows(PEDESTRIAN_VCLASS)]
    if offenders:
        raise ClosureError(f"closure would bar pedestrians on {offenders}")


# --- output integrity: the red team's law ---------------------------------


def output_is_complete(
    path: str | Path,
    root_tag: str,
    *,
    expected_last_time: float | None = None,
    step_length: float = 0.1,
) -> bool:
    """True when an output file was fully written.

    RT-01 established that a crashed SUMO leaves a truncated XML file and an
    empty stderr. Round-3 finding 3 established that a file cut at an element
    boundary and hand-closed passes a naive "closing tag near the end" test.
    So: the closing tag must be the document's FINAL non-whitespace token, and
    for FCD output the last recorded timestep must reach the expected end.
    """
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return False
    data = p.read_bytes()
    if not data.rstrip().endswith(f"</{root_tag}>".encode()):
        return False
    try:
        ET.parse(str(p))
    except ET.ParseError:
        return False
    if expected_last_time is not None and root_tag == "fcd-export":
        last = None
        for m in re.finditer(rb'<timestep time="([0-9.]+)"', data):
            last = float(m.group(1))
        if last is None or last < expected_last_time - step_length * 0.5:
            return False
    return True


def count_post_closure_entries(
    fcd_path: str | Path, closed_edges: set[str], fire_time: float
) -> tuple[int, int]:
    """Measure the closure's effect on the closed edges from the FCD itself.

    Returns (entries_after_closure, vehicles_present_on_closed_edge_at_closure).
    An "entry" is a vehicle whose lane's edge is a closed edge at time t but was
    not at the previous sample, with t > fire_time. Vehicles already on the edge
    at the closure instant are expected to leave and are reported separately.
    This is the counter round-3 finding 2 said was missing.
    """
    prev_on: dict[str, bool] = {}
    entries = 0
    present_at_fire: set[str] = set()
    seen_fire = False
    for _ev, el in ET.iterparse(str(fcd_path), events=("end",)):
        if el.tag != "timestep":
            continue
        t = float(el.get("time", "0"))
        for v in el:
            if v.tag != "vehicle":
                continue
            lane = v.get("lane", "")
            edge = lane.rsplit("_", 1)[0] if lane and not lane.startswith(":") else None
            on = edge in closed_edges
            vid = v.get("id")
            if t > fire_time and on and not prev_on.get(vid, False):
                if vid in present_at_fire:
                    pass  # it was already there; leaving, not entering
                else:
                    entries += 1
            if not seen_fire and t >= fire_time and on:
                present_at_fire.add(vid)
            prev_on[vid] = on
        if t >= fire_time:
            seen_fire = True
        el.clear()
    return entries, len(present_at_fire)


# --- rerouting, measured honestly -----------------------------------------


def _reroute_and_measure(vid: str, closed_edges: set[str], result: RunResult) -> None:
    """Reroute one vehicle and record whether its route ACTUALLY changed.

    `rerouteTraveltime` returning without raising proves the command was
    accepted -- nothing more. A vehicle can be asked to reroute and keep exactly
    the route it had (no alternative exists, or the alternative is worse). Calling
    that "rerouted" overstates the effect of a closure, so the route is captured
    before and after and compared edge-for-edge.
    """
    route_before = tuple(traci.vehicle.getRoute(vid))
    if not closed_edges.intersection(route_before):
        return

    # A vehicle already on a closed lane cannot be rerouted off it; SUMO's
    # setDisallowed bars entry, not presence. It must exit, so it is neither a
    # request nor a success (round-3 finding 2).
    lane_now = traci.vehicle.getLaneID(vid)
    if lane_now and not lane_now.startswith(":") and lane_now.rsplit("_", 1)[0] in closed_edges:
        result.vehicles_on_closed_lane_at_closure += 1
        return

    result.reroute_requests += 1
    try:
        traci.vehicle.rerouteTraveltime(vid, currentTravelTimes=True)
    except traci.TraCIException:
        result.reroute_failures += 1
        return

    result.reroute_successes += 1
    route_after = tuple(traci.vehicle.getRoute(vid))
    if route_after != route_before:
        result.routes_actually_changed += 1
    else:
        result.routes_unchanged += 1


# --- the run --------------------------------------------------------------


def run_simulation(
    *,
    sumo_binary: str,
    net_path: str | Path,
    route_files: Sequence[str | Path],
    out_dir: str | Path,
    prefix: str,
    seed: int,
    end_seconds: float,
    step_length: float = 0.1,
    closure: ClosureSpec | None = None,
    port: int = 55531,
    extra_args: Sequence[str] = (),
) -> RunResult:
    """Run one arm of an experiment, optionally applying a closure mid-run."""
    import time

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fcd = out_dir / f"{prefix}.fcd.xml"
    trip = out_dir / f"{prefix}.tripinfo.xml"

    lanes: list[str] = []
    if closure is not None:
        lanes = select_closable_lanes(net_path, closure.edge_ids, closure.disallow)
        assert_pedestrian_access_preserved(net_path, lanes)

    cmd = [
        sumo_binary,
        "--net-file", str(net_path),
        "--route-files", ",".join(str(r) for r in route_files),
        "--begin", "0",
        "--end", str(end_seconds),
        "--step-length", str(step_length),
        "--seed", str(seed),
        "--time-to-teleport", "300",
        "--pedestrian.model", "striping",
        "--fcd-output", str(fcd),
        "--tripinfo-output", str(trip),
        "--no-step-log", "true",
        "--no-warnings", "true",
        "--duration-log.statistics", "true",
        "--ignore-route-errors",
        "--remote-port", str(port),
        *extra_args,
    ]

    result = RunResult(lanes_closed=tuple(lanes))
    closed_edges = set(closure.edge_ids) if closure else set()
    fire_at = round(closure.at_second / step_length) if closure else None

    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        traci.init(port)
        max_steps = int(round(end_seconds / step_length))
        step = 0
        applied = False
        while step < max_steps and traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
            step += 1

            if fire_at is not None and not applied and step >= fire_at:
                for lane in lanes:                      # already sorted
                    traci.lane.setDisallowed(lane, list(closure.disallow))
                applied = True
                result.closure_applied_at_step = step
                # everyone currently running who needs the closed edge
                for vid in sorted(traci.vehicle.getIDList()):
                    _reroute_and_measure(vid, closed_edges, result)

            elif applied:
                # vehicles inserted after the closure still carry pre-planned routes
                for vid in sorted(traci.simulation.getDepartedIDList()):
                    _reroute_and_measure(vid, closed_edges, result)

        result.steps = step
        result.sim_seconds = step * step_length
        traci.close()
    finally:
        try:
            result.exit_code = proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            result.exit_code = None
        result.wall_seconds = time.perf_counter() - t0

    # SUMO's own statistics (teleports) from its stdout.
    try:
        out_bytes, _err = proc.communicate(timeout=5)
        m = re.search(rb"Teleports:\s*(\d+)", out_bytes or b"")
        result.teleports = int(m.group(1)) if m else 0
    except Exception:
        result.teleports = 0

    result.outputs_valid = {
        fcd.name: output_is_complete(
            fcd, "fcd-export",
            expected_last_time=result.sim_seconds - step_length, step_length=step_length),
        trip.name: output_is_complete(trip, "tripinfos"),
    }
    if closure is not None and result.outputs_valid.get(fcd.name):
        entries, _present = count_post_closure_entries(
            fcd, closed_edges, closure.at_second)
        result.post_closure_entries_onto_closed_edges = entries
    return result


def seal_run_result(
    *,
    baseline: RunResult,
    ruled: RunResult,
    out_dir: str | Path,
    episode_number: int,
    seed: int,
    sumo_version: str,
    applied_at_sim_second: float,
    baseline_prefix: str = "baseline",
    ruled_prefix: str = "ruled",
    baseline_record_dir: str = "record_baseline",
    ruled_record_dir: str = "record_ruled",
) -> dict[str, Any]:
    """Seal a `simulation_result` MACHINE-SIDE, from the runs that produced it.

    The ledger's `measured_effect` numbers are derived by the extractor from the
    six sealed artefacts and re-derived on evidence-aware verification; this
    function contributes only artefact byte identities and run identity to
    that path.

    It ALSO seals a `run_report`: the simulator-side `RunResult` figures
    (reroute accounting, lanes closed, teleports, post-closure entries). These
    are the run's own report, sealed for audit, and they are NOT re-derived by
    the extractor -- except `post_closure_entries_onto_closed_edges`, which is
    measured from the FCD after the run and must be 0 for the seal to proceed.
    Round-3 finding 4 was that the previous docstring claimed no claims were
    sealed; that was false, and this docstring says exactly what is.
    """
    import json

    from .evidence import seal_simulation_result, sha256_file

    # `clean` is `exit_code == 0 and all(outputs_valid.values())`; an empty
    # outputs_valid would make all([]) True. A run that validated no outputs
    # is not a run this function will vouch for.
    for name, rr in (("baseline", baseline), ("ruled", ruled)):
        if not rr.outputs_valid:
            raise ClosureError(f"refusing to seal: {name} run validated no output files")
        if rr.exit_code != 0 or not rr.clean:
            raise ClosureError(
                f"refusing to seal a result over an unclean {name} run: "
                f"exit_code={rr.exit_code} outputs_valid={rr.outputs_valid}"
            )
        if rr.steps <= 0:
            raise ClosureError(f"refusing to seal: {name} run advanced zero steps")
    if ruled.post_closure_entries_onto_closed_edges is None:
        raise ClosureError(
            "refusing to seal: the ruled run did not measure post-closure entries onto "
            "the closed edges (was it run with a closure and a valid FCD?)"
        )
    if ruled.post_closure_entries_onto_closed_edges != 0:
        raise ClosureError(
            f"refusing to seal: {ruled.post_closure_entries_onto_closed_edges} vehicle(s) "
            "entered a closed edge after the closure -- the closure did not hold"
        )
    out = Path(out_dir)
    paths = {
        "baseline_tripinfo": f"{baseline_prefix}.tripinfo.xml",
        "ruled_tripinfo": f"{ruled_prefix}.tripinfo.xml",
        "baseline_record_manifest": f"{baseline_record_dir}/record_manifest.json",
        "baseline_record_frames": f"{baseline_record_dir}/frames.bin",
        "ruled_record_manifest": f"{ruled_record_dir}/record_manifest.json",
        "ruled_record_frames": f"{ruled_record_dir}/frames.bin",
    }
    artifacts = {}
    for name, rel in paths.items():
        p = out / rel
        if not p.exists():
            raise ClosureError(f"cannot seal: artefact {name!r} missing at {p}")
        artifacts[name] = {"file": rel, "sha256": sha256_file(p)}

    doc = {
        "schema_version": "simulation_result_v1",
        "run_id": ruled_prefix,
        "episode_number": int(episode_number),
        "arm": "ruled",
        "seed": int(seed),
        "sumo_version": sumo_version,
        "applied_at_sim_second": float(applied_at_sim_second),
        "run_report": {
            "note": ("Simulator-side RunResult figures, sealed for audit. Not re-derived by "
                     "the extractor except post_closure_entries_onto_closed_edges, which is "
                     "measured from the FCD and must be 0."),
            "baseline": {"exit_code": baseline.exit_code, "steps": baseline.steps,
                         "outputs_valid": baseline.outputs_valid,
                         "teleports": baseline.teleports},
            "ruled": {"exit_code": ruled.exit_code, "steps": ruled.steps,
                      "outputs_valid": ruled.outputs_valid,
                      "teleports": ruled.teleports,
                      "reroute_requests": ruled.reroute_requests,
                      "reroute_successes": ruled.reroute_successes,
                      "routes_actually_changed": ruled.routes_actually_changed,
                      "routes_unchanged": ruled.routes_unchanged,
                      "reroute_failures": ruled.reroute_failures,
                      "vehicles_on_closed_lane_at_closure": ruled.vehicles_on_closed_lane_at_closure,
                      "post_closure_entries_onto_closed_edges": ruled.post_closure_entries_onto_closed_edges,
                      "lanes_closed": list(ruled.lanes_closed)},
            "sumo_flags": {"time_to_teleport": 300, "time_to_teleport_remove": False,
                           "ignore_route_errors": True},
        },
        "artifacts": artifacts,
        "result_hash": "",
    }
    sealed = seal_simulation_result(doc)
    (out / "simulation_result.json").write_text(
        json.dumps(sealed, indent=2, sort_keys=True), encoding="utf-8"
    )
    return sealed


def summarise_tripinfo(path: str | Path) -> dict[str, Any]:
    """Aggregate a tripinfo file. Every value is a SUMO measurement."""
    trips: list[tuple[float, float, float, float]] = []
    walks: list[tuple[float, float]] = []
    for _ev, el in ET.iterparse(str(path), events=("end",)):
        if el.tag == "tripinfo":
            trips.append(
                (
                    float(el.get("duration", 0)),
                    float(el.get("routeLength", 0)),
                    float(el.get("waitingTime", 0)),
                    float(el.get("timeLoss", 0)),
                )
            )
        elif el.tag == "personinfo":
            for w in el:
                if w.tag == "walk":
                    walks.append(
                        (float(w.get("routeLength", 0)), float(w.get("duration", 0)))
                    )
        else:
            # ElementTree's clear() drops attributes as well as children, so a
            # <walk> cleared on its own end event would be stripped bare before
            # its parent <personinfo> is ever read. Only clear the top-level
            # records; never their children.
            continue
        el.clear()

    def avg(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    return {
        "trips_completed": len(trips),
        "avg_duration_s": round(avg([t[0] for t in trips]), 2),
        "avg_route_length_m": round(avg([t[1] for t in trips]), 2),
        "avg_waiting_time_s": round(avg([t[2] for t in trips]), 2),
        "avg_time_loss_s": round(avg([t[3] for t in trips]), 2),
        "walks_completed": len(walks),
        "avg_walk_length_m": round(avg([w[0] for w in walks]), 2),
        "avg_walk_duration_s": round(avg([w[1] for w in walks]), 2),
    }
