"""The bridge between the pure agent layer and a live SUMO through TraCI.

The project's law is unchanged and this module is written to keep it visible:
**SUMO moves every body; an agent only chooses intent.** Nothing here writes a
pose, a speed or a yaw. What it does is translate in both directions:

* TraCI state  -> `agents.Observation`  (what the agent is allowed to know)
* `agents.AgentAction` -> TraCI calls   (the intent, executed by the simulator)

The agent layer stays pure and testable: it never imports `traci`, and every
function here takes an already-open connection so the whole bridge can be
exercised against a recording fake.

Why a pedestrian replan is an AGENT decision and not a physics one
------------------------------------------------------------------
A road closure in this project bars the carriageway and leaves the footway
open -- that is a hard rule in `ldyf/closure.py` and it is not being weakened.
So a pedestrian is never physically prevented from walking through a closed
street. What changes is what a person *chooses* to do: an agent that perceives
the closure adds the shut edge to its own `avoid` set and replans a walking
route around it. SUMO then walks the body along whatever route the agent
chose, and the two arms' sealed records differ because the chosen routes
differ. That is a decision, recorded as an event, and it is exactly the kind of
adaptation Phase 3 is supposed to demonstrate.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from .agents import AgentState, Goal, Observation, step_agent

def tok(edge_id: str) -> str:
    """SUMO edge id -> the agent layer's namespaced token.

    The agent layer refuses a bare id on purpose: every id it handles is
    `tag:payload`, so a token can never be mistaken for a different kind of
    thing. SUMO has no such convention, so the translation lives here, at the
    boundary, and nowhere else.
    """
    return edge_id if ":" in edge_id else f"edge:{edge_id}"


def bare(token: str) -> str:
    """The agent layer's token -> the SUMO edge id."""
    return token.split(":", 1)[1] if token.startswith("edge:") else token


__all__ = [
    "PedestrianBridge",
    "bare",
    "build_observation",
    "clear_route_cache",
    "three_stage_walk",
    "tok",
    "sumo_walk",
    "walking_route",
]


def sumo_walk(conn: Any, from_edge: str, to_edge: str) -> tuple[str, ...]:
    """The walking route SUMO itself returns. SUMO is the router, not this file.

    sumolib's edge-level `getShortestPath` cannot route a pedestrian on this
    network -- it returns cost `inf`, because walking uses crossings and
    walking-areas that the edge graph does not model. `findIntermodalRoute` is
    SUMO's own pedestrian router and is what mobility truth means here.
    """
    try:
        stages = conn.simulation.findIntermodalRoute(from_edge, to_edge, modes="")
    except Exception:
        return ()
    return tuple(e for st in stages for e in st.edges)


#: Routes already computed this episode, keyed by (from, to, avoid). The
#: via-point search costs up to two routing queries per candidate edge, and
#: without this it re-ran on EVERY observation of EVERY agent once the avoid
#: set was non-empty -- about a hundred thousand routing calls in a 300 s run,
#: which made the episode appear to hang. The result is a pure function of the
#: key within one episode, so caching it changes nothing but the cost.
_ROUTE_CACHE: dict[tuple[str, str, tuple[str, ...]], tuple[str, ...]] = {}


def clear_route_cache() -> None:
    """Drop the memoised routes. Call between episodes, never inside one."""
    _ROUTE_CACHE.clear()


def walking_route(conn: Any, from_edge: str, to_edge: str,
                  avoid: Sequence[str] = (),
                  *, candidates: Sequence[str] = ()) -> tuple[str, ...]:
    """A walking route, avoiding `avoid` if the agent can find a way around.

    The direct route comes straight from SUMO. If it crosses something the
    agent wants to avoid, the agent picks a VIA-POINT and asks SUMO to route
    each leg; the choice of waypoint is the agent's decision, and every metre
    of the result is still SUMO's routing.

    `adaptTraveltime` is deliberately not used: it steers the vehicle router,
    not the pedestrian one, so it would look like avoidance while changing
    nothing. Measured on this network before this function was written.

    Returns () when there is no route at all, and the DIRECT route when no
    way round exists -- the caller can tell those apart by checking whether the
    result still contains the avoided edge.
    """
    blocked = {e for e in avoid if e}
    key = (from_edge, to_edge, tuple(sorted(blocked)))
    hit = _ROUTE_CACHE.get(key)
    if hit is not None:
        return hit
    direct = sumo_walk(conn, from_edge, to_edge)
    if not direct or not blocked or not (blocked & set(direct)):
        _ROUTE_CACHE[key] = direct
        return direct

    for via in sorted(candidates) or sorted(_edge_ids(conn)):
        if via in blocked or via in (from_edge, to_edge):
            continue
        first = sumo_walk(conn, from_edge, via)
        if not first or blocked & set(first):
            continue
        second = sumo_walk(conn, via, to_edge)
        if not second or blocked & set(second):
            continue
        joined = first + (second[1:] if first[-1] == second[0] else second)
        if not blocked & set(joined):
            _ROUTE_CACHE[key] = joined
            return joined
    _ROUTE_CACHE[key] = direct
    return direct


def _edge_ids(conn: Any) -> list[str]:
    try:
        return [e for e in conn.edge.getIDList() if not e.startswith(":")]
    except Exception:
        return []


def _has_edge(net: Any, edge_id: str) -> bool:
    try:
        net.getEdge(edge_id)
        return True
    except Exception:
        return False


def build_observation(
    conn: Any,
    net: Any,
    state: AgentState,
    person_id: str,
    *,
    blocked_edges: Sequence[str] = (),
    t_sim: float = 0.0,
    neighbour_radius_m: float = 25.0,
) -> Observation | None:
    """What this agent may know this tick, read from the live simulation.

    Returns None when the person is not in the simulation (not yet departed, or
    already arrived): there is no observation to make, and inventing one would
    be inventing a world.
    """
    try:
        current = str(conn.person.getRoadID(person_id))
    except Exception:
        return None
    if not current or current.startswith(":"):
        # on an internal junction edge: the agent has no decision to make here
        return None

    goal = state.goal_stack[0] if state.goal_stack else None
    target = bare(goal.target) if goal is not None else current
    avoid = tuple(sorted({bare(e) for e in blocked_edges} | {
        bare(g.target) for g in state.goal_stack if g.kind == "avoid"}))
    route = walking_route(conn, current, target, avoid=avoid)
    reachable = tuple(tok(e) for e in route) if route else ()

    # The agent checks reachability by walking a SUCCESSORS graph, so it must be
    # given the topology ALONG the route, not just the current edge's outgoing
    # set. Supplying one entry made every goal look unreachable after a single
    # hop, and every agent blocked on its first tick.
    successors: list[tuple[str, tuple[str, ...]]] = []
    for i, edge in enumerate(route):
        nxt = (tok(route[i + 1]),) if i + 1 < len(route) else ()
        successors.append((tok(edge), nxt))

    return Observation(
        agent_id=state.agent_id,
        current_edge=tok(current),
        reachable_edges=reachable,
        blocked_edges=tuple(sorted(tok(e) for e in blocked_edges)),
        successors=tuple(successors),
        signal_state="none",
        t_sim=float(t_sim),
    )


class PedestrianBridge:
    """Drives a set of pedestrian agents against a live SUMO.

    One instance per episode. It owns the mapping agent_id -> SUMO person id,
    the events it emitted, and nothing else; the agent states are passed in and
    returned so the caller keeps authority over them.
    """

    def __init__(self, conn: Any, net: Any, episode_id: str) -> None:
        self.conn = conn
        self.net = net
        self.episode_id = episode_id
        self.person_of: dict[str, str] = {}
        self.events: list[dict[str, Any]] = []
        self.applied_routes: dict[str, tuple[str, ...]] = {}
        self.seq = 0

    # -- spawning ----------------------------------------------------------
    def spawn(self, state: AgentState, person_id: str, origin: str, *,
              depart: float, vtype: str = "DEFAULT_PEDTYPE") -> bool:
        """Create the SUMO person for a multi-stage agent, stage by stage.

        `origin` is where the body starts; the goal stack is where it is going.
        They are separate on purpose: an earlier version used the first GOAL as
        the origin, which put every person down on the middle edge of its own
        trip, completed that stage instantly, and turned a three-stage walk into
        a one-leg one. Every goal becomes a walking stage, so the person SUMO
        carries is the agent's whole trip.
        """
        stages = [g for g in state.goal_stack if g.kind == "travel_to"]
        if not stages:
            return False
        try:
            self.conn.person.add(person_id, bare(origin), 0.0, depart, vtype)
        except Exception:
            return False

        here = bare(origin)
        ok = False
        for goal in stages:
            route = walking_route(self.conn, here, bare(goal.target))
            if not route:
                continue
            try:
                self.conn.person.appendWalkingStage(person_id, list(route), 0.0)
                self.applied_routes.setdefault(person_id, ())
                self.applied_routes[person_id] += tuple(route)
                here = bare(goal.target)
                ok = True
            except Exception:
                continue
        if ok:
            self.person_of[state.agent_id] = person_id
            self._event("agent_spawned", state.agent_id, depart,
                        {"person_id": person_id, "origin": bare(origin),
                         "stages": [bare(g.target) for g in stages]})
        return ok

    # -- the tick ----------------------------------------------------------
    def step(self, state: AgentState, tick: int, *, t_sim: float,
             blocked_edges: Sequence[str] = ()) -> AgentState:
        """One tick for one agent: observe, decide, and execute the intent."""
        person_id = self.person_of.get(state.agent_id)
        if person_id is None:
            return state
        obs = build_observation(self.conn, self.net, state, person_id,
                                blocked_edges=blocked_edges, t_sim=t_sim)
        if obs is None:
            return state

        step = step_agent(state, obs, tick, self.episode_id)
        for record in step.records:
            self._event(str(record.kind), state.agent_id, t_sim,
                        {"value": record.value})

        if step.replanned:
            self._execute_replan(step.state, person_id, obs, t_sim)
        return step.state

    def _execute_replan(self, state: AgentState, person_id: str,
                        obs: Observation, t_sim: float) -> None:
        """Rewrite the person's remaining walk to the route the agent chose.

        This is the one place intent becomes a TraCI call. It replaces the
        remaining stages rather than nudging a position: SUMO still walks the
        body, along a route the agent picked.
        """
        goal = state.goal_stack[0] if state.goal_stack else None
        if goal is None or goal.kind != "travel_to":
            return
        avoid = tuple(sorted({bare(e) for e in obs.blocked_edges} | {
            bare(g.target) for g in state.goal_stack if g.kind == "avoid"}))
        route = walking_route(self.conn, bare(obs.current_edge),
                              bare(goal.target), avoid=avoid)
        if not route:
            return
        try:
            # removeStages drops EVERY stage; SUMO removes a person with no
            # stages on the next step, so the replacement walk is appended
            # immediately and any failure is recorded rather than swallowed.
            self.conn.person.removeStages(person_id)
            self.conn.person.appendWalkingStage(person_id, list(route), 0.0)
        except Exception as exc:
            self._event("agent_reroute_failed", state.agent_id, t_sim,
                        {"person_id": person_id, "error": repr(exc)[:160]})
            return
        self.applied_routes[person_id] = tuple(route)
        # Record the ROUTE and whether the avoidance actually succeeded.
        # walking_route returns the direct route when no way round exists, so
        # "avoided: [B1B2]" alone proves only what was ASKED for, not what was
        # achieved -- and a reroute that still crosses the avoided edge is a
        # fact worth having in the log rather than a claim worth hiding.
        still_crossing = sorted(set(avoid) & set(route))
        self._event("agent_rerouted", state.agent_id, t_sim,
                    {"person_id": person_id, "route": list(route),
                     "route_len": len(route), "avoided": list(avoid),
                     "avoidance_succeeded": not still_crossing,
                     "still_crossing": still_crossing})

    # -- events ------------------------------------------------------------
    def _event(self, kind: str, agent_id: str, t_sim: float,
               payload: dict[str, Any]) -> None:
        self.seq += 1
        self.events.append({
            "seq": self.seq,
            "episode_id": self.episode_id,
            "kind": kind,
            "agent_id": agent_id,
            "t_sim": round(float(t_sim), 3),
            "payload": payload,
        })


def three_stage_walk(agent_id: str, stages: Iterable[str],
                     *, deadline_s: float | None = None) -> AgentState:
    """A multi-stage pedestrian agent: one travel_to goal per stage, in order."""
    targets = list(stages)
    if len(targets) < 2:
        raise ValueError("a multi-stage walk needs at least two stages")
    goals = tuple(
        Goal(goal_id=f"goal:{i}", kind="travel_to", target=tok(t),
             deadline_s=deadline_s)
        for i, t in enumerate(targets[1:], start=1)
    )
    # No plan is built here on purpose: step_agent plans on its first tick from
    # the agent's own perception, and a plan invented before the world has been
    # observed would be a guess this layer is not entitled to make.
    return AgentState(agent_id=agent_id, kind="pedestrian", goal_stack=goals)
