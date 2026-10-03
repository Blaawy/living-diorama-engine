"""Stage 1: brief -> two sealed simulation arms.

One controlled experiment. The two arms run the SAME locked network, the SAME
demand, the SAME agents and the SAME seed; the only difference is the brief's
ONE rule, applied to the ruled arm at its declared second. SUMO moves every
body. This module unifies the two Phase 3 runners without changing either:

* the agent episode (`ldyf.agent_sumo.PedestrianBridge`): multi-stage
  pedestrian agents that perceive a closure and replan;
* the rule episode: any `ldyf.rules.RuleSpec`, and -- when the world says
  drivers reroute -- vehicles re-routed by current travel time off a closure.

With `drivers_reroute` false the ruled arm is, step for step, the Phase 3 agent
episode; the factory reproduces that sealed record byte for byte, which is the
proof it runs the locked world and not a lookalike.

What is written is what SUMO produced and what the agents logged. Nothing here
decides what a consequence IS; `ldyf.factory.facts` does that, from the sealed
artefacts, afterwards.

Nothing wall-clock enters a sealed document. Timings go to `run_timing.json`,
which nothing downstream hashes.
"""
from __future__ import annotations

import re
import shutil
import socket
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

from .. import agent_sumo as BR
from .. import consequence as _consequence  # noqa: F401  (registers the Phase 3 extractors)
from .. import persistent_changes as pc
from .. import rules as R
from .. import sumo_record
from ..agents import make_agent_id
from ..closure import output_is_complete
from ..evidence import artifact_sha256, seal_simulation_result
from . import FactoryError
from .brief import brief_hash, build_rule, build_rule_manifest
from .util import sha256_file, write_json
from .world import twin_edge

SIM_SCHEMA = "factory_simulation_v1"
ARMS = ("baseline", "ruled")
_SUMO_DEFAULT = r"C:\Program Files (x86)\Eclipse\Sumo\bin\sumo.exe"

#: The registered extractor for each rule class. The factory adds none: the
#: closed, approved set from Phase 3 is the only thing allowed to write a
#: measured effect into the ledger.
EXTRACTOR_FOR = {
    "edge_closure": "closure_effect_v1",
    "speed_limit": "speed_limit_effect_v1",
    "traffic_light_program": "traffic_light_effect_v1",
    "demand_flow": "demand_flow_effect_v1",
}
PED_EXTRACTOR = "pedestrian_effect_v1"


class SimulationError(FactoryError):
    stage = "simulate"


def find_sumo() -> str:
    exe = shutil.which("sumo") or _SUMO_DEFAULT
    if not Path(exe).is_file():
        raise SimulationError("no_sumo", "the SUMO executable was not found")
    return exe


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def agent_plan(world: dict[str, Any]) -> list[dict[str, Any]]:
    """The world's agent population: router-verified trip patterns, staggered."""
    ag = world["agents"]
    trips = [tuple(t) for t in ag["trips"]]
    out = []
    for i in range(int(ag["count"])):
        wave = i // len(trips)
        out.append({"i": i, "stages": list(trips[i % len(trips)]),
                    "depart": float(ag["first_depart_s"]) + float(ag["wave_stagger_s"]) * wave})
    return out


def _reroute(traci: Any, vid: str, closed: set[str], counts: dict[str, int]) -> None:
    """Re-route one vehicle off the closed edges. Measured, not assumed."""
    try:
        route = traci.vehicle.getRoute(vid)
        idx = traci.vehicle.getRouteIndex(vid)
    except Exception:  # noqa: BLE001 - the vehicle left between the list and the query
        return
    if not any(e in closed for e in route[max(idx, 0):]):
        return
    counts["attempted"] += 1
    changed = False
    try:
        traci.vehicle.rerouteTraveltime(vid, currentTravelTimes=True)
        changed = tuple(traci.vehicle.getRoute(vid)) != tuple(route)
    except Exception:  # noqa: BLE001
        pass
    if changed:
        counts["changed"] += 1
    # WHICH vehicles, not only how many: a count cannot be put in front of a camera
    counts["changed_ids" if changed else "unchanged_ids"].append(vid)


def run_arm(*, world: dict[str, Any], rule: R.RuleSpec | None, out_dir: Path, prefix: str,
            seed: int, end_seconds: float, port: int, agent_episode_token: str,
            drivers_reroute: bool, policy_twins: tuple[str, ...],
            log: Callable[[str], None] = print) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run ONE arm. Returns (deterministic report, wall-clock timing)."""
    import traci

    out_dir.mkdir(parents=True, exist_ok=True)
    step_length = float(world["sumo"]["step_length"])
    fcd = out_dir / f"{prefix}.fcd.xml"
    trip = out_dir / f"{prefix}.tripinfo.xml"
    cmd = [
        find_sumo(), "--net-file", world["_net_path"],
        "--route-files", ",".join(world["_route_paths"]),
        "--begin", "0", "--end", str(end_seconds),
        "--step-length", str(step_length), "--seed", str(seed),
        "--time-to-teleport", str(world["sumo"]["time_to_teleport"]),
        "--pedestrian.model", world["sumo"]["pedestrian_model"],
        "--fcd-output", str(fcd), "--tripinfo-output", str(trip),
        "--no-step-log", "true", "--no-warnings", "true",
        "--duration-log.statistics", "true", "--ignore-route-errors",
        "--remote-port", str(port),
    ]
    if not _port_free(port):
        raise SimulationError("port_busy", f"TraCI port {port} is already in use")

    closed_edges: set[str] = set(rule.edge_ids) if isinstance(rule, R.ClosureRule) else set()
    report: dict[str, Any] = {"arm": prefix, "rules_applied": [], "seed": seed}
    reroutes: dict[str, Any] = {"attempted": 0, "changed": 0, "changed_ids": [], "unchanged_ids": []}
    t0 = time.perf_counter()
    # SUMO's output goes to a FILE, never to a pipe nobody reads: an unread
    # pipe fills when --time-to-teleport starts reporting and SUMO then blocks
    # on the write forever (Phase 3, withdrawn conclusion).
    log_path = out_dir / f"{prefix}.sumo.log"
    with log_path.open("wb") as log_f:
        proc = subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT)
        try:
            traci.init(port)
            BR.clear_route_cache()
            bridge = BR.PedestrianBridge(traci, None, agent_episode_token)
            states: dict[str, Any] = {}
            plan = agent_plan(world)
            for row in plan:
                aid = make_agent_id("pedestrian", row["i"])
                st = BR.three_stage_walk(aid, row["stages"])
                if bridge.spawn(st, f"agent{row['i']}", row["stages"][0], depart=row["depart"]):
                    states[aid] = st
            report["agents_requested"] = len(plan)
            report["agents_spawned"] = len(states)

            max_steps = int(round(end_seconds / step_length))
            agent_every = int(round(1.0 / step_length))
            applied = False
            blocked: tuple[str, ...] = ()
            policy: tuple[str, ...] = ()
            step = 0
            while step < max_steps and traci.simulation.getMinExpectedNumber() > 0:
                traci.simulationStep()
                step += 1
                now = step * step_length

                if rule is not None and not applied and now >= rule.at_second:
                    rule.apply(traci, None)
                    applied = True
                    detail: dict[str, Any] = {"rule_id": rule.rule_id,
                                              "change_type": rule.change_type(),
                                              "at_second": round(now, 3), "at_step": step}
                    if closed_edges:
                        blocked = tuple(sorted(closed_edges))
                        policy = policy_twins
                        detail["lanes"] = list(rule.lanes())
                        if drivers_reroute:
                            for vid in sorted(traci.vehicle.getIDList()):
                                _reroute(traci, vid, closed_edges, reroutes)
                    report["rules_applied"].append(detail)

                if applied and closed_edges and drivers_reroute:
                    for vid in sorted(traci.simulation.getDepartedIDList()):
                        _reroute(traci, vid, closed_edges, reroutes)
                if applied:
                    tick = getattr(rule, "tick", None)
                    if tick is not None:
                        tick(traci, now, None)

                if step % (agent_every * 100) == 0:
                    log("      %s t=%.0fs events=%d wall=%.1fs"
                        % (prefix, now, len(bridge.events), time.perf_counter() - t0))
                if step % agent_every == 0:
                    for aid in sorted(states):
                        states[aid] = bridge.step(states[aid], step, t_sim=now,
                                                  blocked_edges=blocked, avoid_also=policy)

            events = bridge.events
            report["intent_events"] = sum(1 for e in events if e["kind"] == "intent_issued")
            # the per-second intents are 99.9 % of the log and say nothing a
            # record does not; every other event is kept, in order
            report["events"] = [e for e in events if e["kind"] != "intent_issued"]
            report["agent_final"] = {
                aid: {"status": st.status, "goals_left": len(st.goal_stack)}
                for aid, st in sorted(states.items())}
            report["initial_routes"] = {
                pid: list(r) for pid, r in sorted(bridge.initial_routes.items())}
            report["routes_applied"] = {
                pid: list(r) for pid, r in sorted(bridge.applied_routes.items())}
            report["router_calls"] = bridge.router_calls
            report["steps"] = step
            report["sim_seconds"] = round(step * step_length, 3)
            report["vehicle_reroutes_attempted"] = reroutes["attempted"]
            report["vehicle_reroutes_changed"] = reroutes["changed"]
            report["vehicles_rerouted"] = sorted(reroutes["changed_ids"])
            report["vehicles_not_rerouted"] = sorted(reroutes["unchanged_ids"])
            traci.close()
        finally:
            try:
                report["exit_code"] = proc.wait(timeout=180)
            except subprocess.TimeoutExpired:
                proc.kill()
                report["exit_code"] = None
            try:
                traci.close()
            except Exception:  # noqa: BLE001 - already closed on the normal path
                pass
    wall = time.perf_counter() - t0

    out_b = log_path.read_bytes()
    m = re.search(rb"Teleports:\s*(\d+)", out_b)
    report["teleports"] = int(m.group(1)) if m else 0
    report["outputs_valid"] = {
        fcd.name: output_is_complete(fcd, "fcd-export",
                                     expected_last_time=report.get("sim_seconds", 0.0) - step_length,
                                     step_length=step_length),
        trip.name: output_is_complete(trip, "tripinfos"),
    }
    if report.get("exit_code") != 0:
        raise SimulationError("sumo_failed", f"{prefix} arm: SUMO exited with {report.get('exit_code')}")
    bad = [k for k, ok in report["outputs_valid"].items() if not ok]
    if bad:
        raise SimulationError("incomplete_output", f"{prefix} arm: incomplete simulator output {bad}")
    if report["agents_spawned"] != report["agents_requested"]:
        raise SimulationError("agents_not_spawned",
                              f"{prefix} arm: {report['agents_spawned']} of "
                              f"{report['agents_requested']} agents spawned")
    return report, {"wall_seconds": round(wall, 3)}


def _write_demand_manifests(sim_dir: Path, world: dict[str, Any], *, seed: int,
                            end_seconds: float, rule: R.RuleSpec, n_agents: int) -> None:
    """One `demand_manifest_v1` per arm, naming the demand DEFINITION.

    Counted from the route files (what departs inside the window) plus the
    world's declared agent population -- never from the record, or the
    extractor's cross-check would compare the record against itself.
    """
    declared = {"vehicle": 0, "person": 0}
    files = []
    for rp in world["_route_paths"]:
        rp = Path(rp)
        files.append({"file": rp.name, "sha256": artifact_sha256(rp)})
        for el in ET.parse(rp).getroot():
            try:
                depart = float(el.get("depart", "0"))
            except ValueError:
                depart = 0.0
            if depart >= end_seconds:
                continue
            if el.tag in ("vehicle", "trip", "flow"):
                declared["vehicle"] += 1
            elif el.tag == "person":
                declared["person"] += 1
    declared["person"] += n_agents
    for arm in ARMS:
        injected = dict(declared)
        if arm == "ruled" and isinstance(rule, R.DemandFlowRule):
            injected["vehicle"] += rule.vehicle_count()
        write_json(sim_dir / f"{arm}_demand.json", {
            "schema_version": "demand_manifest_v1", "arm": arm, "route_files": files,
            "seed": int(seed), "injected": injected, "scale": 1.0})


def _artifacts(sim_dir: Path) -> dict[str, dict[str, str]]:
    want = {
        "baseline_tripinfo": "baseline.tripinfo.xml",
        "ruled_tripinfo": "ruled.tripinfo.xml",
        "baseline_record_manifest": "record_baseline/record_manifest.json",
        "baseline_record_frames": "record_baseline/frames.bin",
        "ruled_record_manifest": "record_ruled/record_manifest.json",
        "ruled_record_frames": "record_ruled/frames.bin",
        "baseline_demand": "baseline_demand.json",
        "ruled_demand": "ruled_demand.json",
        "baseline_agents": "agents_baseline.json",
        "ruled_agents": "agents_ruled.json",
    }
    if (sim_dir / "tls_junction.json").is_file():
        want["tls_junction"] = "tls_junction.json"
    out = {}
    for name, rel in want.items():
        p = sim_dir / rel
        if not p.is_file():
            raise SimulationError("missing_artifact", f"simulation artefact {rel} was not produced")
        out[name] = {"file": rel, "sha256": artifact_sha256(p)}
    return out


def run_episode(brief: dict[str, Any], world: dict[str, Any], sim_dir: str | Path, *,
                drivers_reroute: bool | None = None, ports: tuple[int, int] = (55911, 55912),
                keep_fcd: bool = False, log: Callable[[str], None] = print) -> dict[str, Any]:
    """Run both arms, seal them, and let the registered extractors measure.

    Returns the simulation document (also written to `sim_dir/simulation.json`).
    """
    import sumolib

    sim_dir = Path(sim_dir)
    sim_dir.mkdir(parents=True, exist_ok=True)
    reroute = bool(world.get("drivers_reroute")) if drivers_reroute is None else bool(drivers_reroute)
    end = float(brief["end_seconds"])
    seed = int(brief["seed"])
    step_length = float(world["sumo"]["step_length"])

    rule = build_rule(brief)
    try:
        rule.validate(world["_net_path"], episode_end_seconds=end)
        R.validate_rule_set([rule])
    except Exception as e:  # noqa: BLE001 - every refusal from the rule layer is a brief error
        raise SimulationError("rule_refused", f"the rule is refused by the locked world: {e}")
    manifest = build_rule_manifest(brief, rule)
    write_json(sim_dir / "rule_manifest.json", manifest)

    net = sumolib.net.readNet(world["_net_path"])
    twins: tuple[str, ...] = ()
    if isinstance(rule, R.ClosureRule) and world["agents"].get("policy") == "avoid_whole_street":
        twins = tuple(sorted(t for t in (twin_edge(e, net) for e in rule.edge_ids)
                             if t and t not in rule.edge_ids))

    token = "ep:" + brief_hash(brief)[:16]
    timing: dict[str, Any] = {}
    reports: dict[str, Any] = {}
    for arm, the_rule, port in (("baseline", None, ports[0]), ("ruled", rule, ports[1])):
        log(f"--- simulate: {arm} arm")
        rep, tm = run_arm(world=world, rule=the_rule, out_dir=sim_dir, prefix=arm, seed=seed,
                          end_seconds=end, port=port, agent_episode_token=token,
                          drivers_reroute=reroute, policy_twins=twins, log=log)
        t0 = time.perf_counter()
        stats = sumo_record.build_record(
            sim_dir / f"{arm}.fcd.xml", sim_dir / f"record_{arm}", step_seconds=step_length,
            net_path=world["_net_path"], seed=seed, sumo_version=world["sumo"]["version"])
        tm["record_seconds"] = round(time.perf_counter() - t0, 3)
        rep["record"] = {"frames": stats.frames, "actors": stats.actors}
        rep["fcd_payload_sha256"] = artifact_sha256(sim_dir / f"{arm}.fcd.xml")
        write_json(sim_dir / f"agents_{arm}.json", {
            "schema_version": "factory_agent_report_v1", "arm": arm,
            "perceived_blocked": sorted(rule.edge_ids) if (arm == "ruled" and isinstance(rule, R.ClosureRule)) else [],
            "avoided_by_agent_policy": list(twins) if arm == "ruled" else [],
            "agent_plan": agent_plan(world), **rep})
        reports[arm] = {k: v for k, v in rep.items()
                        if k not in ("events", "agent_final", "initial_routes", "routes_applied",
                                     "vehicles_rerouted", "vehicles_not_rerouted")}
        timing[arm] = tm
        if not keep_fcd:
            (sim_dir / f"{arm}.fcd.xml").unlink()
        log(f"    sealed {arm}: {rep['record']} wall={tm['wall_seconds']}s")

    _write_demand_manifests(sim_dir, world, seed=seed, end_seconds=end, rule=rule,
                            n_agents=int(world["agents"]["count"]))
    if isinstance(rule, R.TrafficLightRule):
        from ..coords import SumoPose, sumo_to_unreal
        x, y = net.getNode(rule.tls_id).getCoord()[:2]
        up = sumo_to_unreal(SumoPose(x=x, y=y, z=0.0, angle=0.0))
        write_json(sim_dir / "tls_junction.json", {
            "schema_version": "tls_junction_v1", "junction_id": rule.tls_id,
            "centre_unreal_cm": [round(up.x, 3), round(up.y, 3)], "approach_radius_cm": 5000.0})

    result = seal_simulation_result({
        "schema_version": "simulation_result_v1",
        "run_id": "factory_" + brief_hash(brief)[:16],
        "episode_number": int(brief["episode_number"]),
        "arm": "ruled",
        "seed": seed,
        "sumo_version": world["sumo"]["version"],
        "applied_at_sim_second": float(rule.at_second),
        "artifacts": _artifacts(sim_dir),
        "result_hash": "",
        "run_report": reports,
    })
    write_json(sim_dir / "simulation_result.json", result)

    # The ledger records the director's rule: the persistent change this episode
    # makes to the world, which a later episode inherits.
    #
    # MEASURED EFFECTS and the registered extractors. In a world with no agent
    # population the Phase 3 extractors run here and their effects enter the
    # ledger, exactly as in Phase 3. In a world WITH multi-stage agents they
    # are not run, and that is decided by the world, before anything is
    # measured -- not by trying and falling back. Every Phase 3 extractor
    # cross-checks tripinfo `walks_completed` (one per walking STAGE) against
    # person arrivals in the record (one per PERSON); a two-goal agent has two
    # stages, so the locked extractors refuse this world by construction.
    # Phase 3 is locked and is not edited to make them pass. The factory's
    # fact extractor measures the same trip statistics with the same locked
    # summariser (`ldyf.closure.summarise_tripinfo`), cross-checked per person,
    # and seals them in facts.json instead of the ledger.
    ledger = pc.new_ledger(world["name"])
    ledger, _ = pc.append_director_rule(ledger, rule_manifest=manifest)
    extractors: list[str] = []
    skipped: dict[str, str] = {}
    if int(world["agents"]["count"]) > 0:
        skipped["*"] = ("world has multi-stage agents: the Phase 3 extractors count walking "
                        "stages against person arrivals and refuse it by construction; trip "
                        "statistics are measured by ldyf.factory.facts with the same summariser")
    else:
        extractors.append(EXTRACTOR_FOR[rule.change_type()])
        if rule.change_type() != "demand_flow":
            extractors.append(PED_EXTRACTOR)
        else:
            skipped[PED_EXTRACTOR] = "demand is the rule, so the arms' demand manifests differ by design"
    for name in extractors:
        try:
            ledger, _ids = pc.append_simulation_consequence(
                ledger, simulation_result=result, extractor_name=name,
                evidence_dir=sim_dir, rule_id=rule.rule_id)
        except Exception as e:  # noqa: BLE001
            raise SimulationError("extractor_refused",
                                  f"registered extractor {name!r} refused the sealed arms: {e}")
    pc.verify_ledger(ledger, evidence_dir=sim_dir)
    pc.save(ledger, sim_dir / "persistent_changes.json")

    doc = {
        "schema_version": SIM_SCHEMA,
        "brief_sha256": brief_hash(brief),
        "world": world["name"],
        "world_inputs": {"net": world["net"], "routes": world["routes"]},
        "drivers_reroute": reroute,
        "agent_episode_token": token,
        "rule_id": rule.rule_id,
        "rule_change_type": rule.change_type(),
        "rule_manifest_hash": manifest["manifest_hash"],
        "simulation_result_hash": result["result_hash"],
        "ledger_hash": ledger["ledger_hash"],
        "extractors_run": extractors,
        "extractors_skipped": skipped,
        "seed": seed, "end_seconds": end, "step_length": step_length,
        "records": {arm: {
            "manifest_sha256": sha256_file(sim_dir / f"record_{arm}" / "record_manifest.json"),
            "frames_sha256": sha256_file(sim_dir / f"record_{arm}" / "frames.bin")} for arm in ARMS},
        "fcd_kept": keep_fcd,
    }
    write_json(sim_dir / "simulation.json", doc)
    write_json(sim_dir / "run_timing.json", timing)
    return doc
