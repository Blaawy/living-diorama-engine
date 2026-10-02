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

#: The via-point that worked for a (destination, avoid set), without the origin.
#: _ROUTE_CACHE is keyed on the origin too, so a population of agents walking to
#: the same place around the same closure shared nothing: each one re-scanned
#: every edge in the network at two routing queries a candidate. Measured: the
#: ruled arm of a 24-agent run had not reached t = 500 s after six minutes of
#: wall clock, while the baseline, whose avoid set is empty, finished 900 s in
#: seconds. A waypoint is a fact about the NETWORK and the closure, not about
#: who is walking, so the first agent to find one pays the scan and the rest
#: route their own two legs through it.
_VIA_CHOICE: dict[tuple[str, tuple[str, ...]], str] = {}

#: Where on its last edge a walking stage ends. 0.0 -- the value this module
#: used first -- is the START of that edge, so a person "arrived" the instant it
#: set foot on its goal edge, usually between two one-second agent ticks, and
#: the agent never observed itself standing where it was going. Measured over
#: 900 s: every agent that had been rerouted left the simulation with its goal
#: still open. A negative position counts back from the END of the edge, so the
#: body walks the goal edge and the agent has time to see that it is there.
STAGE_ARRIVAL_POS = -1.0

#: How many waypoints an agent will try before it gives up and walks the direct
#: route. A person does not enumerate every street in the city before deciding
#: a detour exists, and neither can this: the scan costs two routing queries per
#: candidate, so an unbounded one over a 100-edge network costs ~200 queries per
#: agent per tick. Measured, that is what it costs: a 24-agent ruled arm spent
#: more than twenty minutes of wall clock between t = 300 s and t = 350 s, while
#: the same arm with the budget runs the whole horizon in seconds.
#:
#: Giving up is not faking anything. The closure bars the carriageway and leaves
#: the footway open, so walking the direct route is a legal outcome, and the
#: reroute event records `still_crossing`, so a walk that did not avoid what it
#: was asked to avoid says so in the record.
VIA_SEARCH_BUDGET = 16


def clear_route_cache() -> None:
    """Drop the memoised routes. Call between episodes, never inside one."""
    _ROUTE_CACHE.clear()
    _VIA_CHOICE.clear()


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

    via_key = (to_edge, tuple(sorted(blocked)))
    pool = sorted(candidates) or sorted(_edge_ids(conn))
    known = _VIA_CHOICE.get(via_key)
    if known is not None and known in pool:
        # A waypoint is already known for this destination and this closure, so
        # the search is OVER: route the two legs through it and, if that fails
        # from here, walk the direct route and let the record say so. Searching
        # again from every new position is what made this unaffordable -- an
        # agent that re-plans each second while it perceives a closure was
        # paying a fresh network scan every second, and 24 of them together
        # spent twenty minutes of wall clock inside one 50-second stretch.
        pool = [known]

    tried = 0
    for via in pool:
        if via in blocked or via in (from_edge, to_edge):
            continue
        if tried >= VIA_SEARCH_BUDGET:
            break
        tried += 1
        first = sumo_walk(conn, from_edge, via)
        if not first or blocked & set(first):
            continue
        second = sumo_walk(conn, via, to_edge)
        if not second or blocked & set(second):
            continue
        joined = first + (second[1:] if first[-1] == second[0] else second)
        if not blocked & set(joined):
            _ROUTE_CACHE[key] = joined
            _VIA_CHOICE[via_key] = via
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
    plan_cache: dict | None = None,
) -> Observation | None:
    """What this agent may know this tick, read from the live simulation.

    Returns None when the person is not in the simulation (not yet departed, or
    already arrived): there is no observation to make, and inventing one would
    be inventing a world.

    `plan_cache`, when given, holds the route each agent is CURRENTLY walking,
    keyed by agent, goal and avoid set. Without it this function asked SUMO for
    a fresh route on every tick of every agent -- the route from wherever the
    body had got to, which changes every tick, so the memo in `walking_route`
    missed every time. Measured: 24 agents over 900 simulated seconds spent
    about ten MINUTES of wall clock in the router, which is what made a larger
    population look impossible. A planner that re-derives its whole plan every
    second is also a poor model of a person: the plan is made once, and the
    agent re-plans when its goal changes, when what it avoids changes, or when
    it finds itself off the plan. All three force a real routing call.
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
    route: tuple[str, ...] = ()
    key = (state.agent_id, target, avoid)
    if plan_cache is not None:
        cached = plan_cache.get(key)
        if cached and current in cached:
            # still on the plan: the remainder of the route SUMO computed is
            # exactly what reachability needs, and no new route is invented
            route = tuple(cached[cached.index(current):])
    if not route:
        route = walking_route(conn, current, target, avoid=avoid)
        if plan_cache is not None and route:
            plan_cache[key] = tuple(route)
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
        #: the route each agent is currently walking, per goal and avoid set
        self.plan_cache: dict[tuple[str, str, tuple[str, ...]], tuple[str, ...]] = {}
        self.router_calls = 0
        #: the route each body was FIRST given; never overwritten by a replan
        self.initial_routes: dict[str, tuple[str, ...]] = {}
        self._present: set[str] = set()
        self._left: set[str] = set()
        self._last_edge: dict[str, str] = {}
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
                self.conn.person.appendWalkingStage(person_id, list(route),
                                                    STAGE_ARRIVAL_POS)
                self.applied_routes.setdefault(person_id, ())
                self.applied_routes[person_id] += tuple(route)
                here = bare(goal.target)
                ok = True
            except Exception:
                continue
        if ok:
            self.initial_routes[person_id] = self.applied_routes[person_id]
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
        before = len(self.plan_cache)
        obs = build_observation(self.conn, self.net, state, person_id,
                                blocked_edges=blocked_edges, t_sim=t_sim,
                                plan_cache=self.plan_cache)
        if len(self.plan_cache) > before:
            self.router_calls += 1
        if obs is None:
            self._note_absence(state, person_id, t_sim)
            return state
        self._present.add(person_id)
        self._last_edge[person_id] = bare(obs.current_edge)

        step = step_agent(state, obs, tick, self.episode_id)
        for record in step.records:
            self._event(str(record.kind), state.agent_id, t_sim,
                        {"value": record.value})

        if step.replanned:
            self._execute_replan(step.state, person_id, obs, t_sim)
        return step.state

    def _note_absence(self, state: AgentState, person_id: str,
                      t_sim: float) -> None:
        """Record, once, that a body which was in the simulation has left it.

        The agent layer cannot be stepped without an observation, so an agent
        whose body is gone simply stops. Without this event the log could not
        tell "still walking" from "SUMO removed the person", and a final
        `goals_left` read as an unfinished trip when the body had finished.
        """
        try:
            still_there = person_id in self.conn.person.getIDList()
        except Exception:
            still_there = False
        if still_there or person_id not in self._present or person_id in self._left:
            return
        self._left.add(person_id)
        self._event("agent_body_left", state.agent_id, t_sim,
                    {"person_id": person_id,
                     "last_edge": self._last_edge.get(person_id, ""),
                     "goals_left": len(state.goal_stack)})

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
            self.conn.person.appendWalkingStage(person_id, list(route),
                                                STAGE_ARRIVAL_POS)
            # removeStages dropped the WHOLE trip, not just the leg being
            # replanned. Appending only the new leg left a rerouted person with
            # nowhere to go after it: SUMO removed the body at the end of that
            # leg and the agent's later goals could never be reached. Every
            # remaining travel goal gets its stage back, routed round the same
            # avoid set.
            here = bare(goal.target)
            for later in state.goal_stack[1:]:
                if later.kind != "travel_to":
                    continue
                leg = walking_route(self.conn, here, bare(later.target),
                                    avoid=avoid)
                if not leg:
                    continue
                self.conn.person.appendWalkingStage(person_id, list(leg),
                                                    STAGE_ARRIVAL_POS)
                here = bare(later.target)
        except Exception as exc:
            self._event("agent_reroute_failed", state.agent_id, t_sim,
                        {"person_id": person_id, "error": repr(exc)[:160]})
            return
        previous = self.applied_routes.get(person_id)
        self.applied_routes[person_id] = tuple(route)
        # The agent is now walking THIS route, so the plan it was observing
        # against is void. Dropping only this agent's entries keeps the cache a
        # record of current plans rather than a record of old ones.
        for k in [k for k in self.plan_cache if k[0] == state.agent_id]:
            del self.plan_cache[k]
        self.plan_cache[(state.agent_id, bare(goal.target), avoid)] = tuple(route)
        # Record the ROUTE and whether the avoidance actually succeeded.
        # walking_route returns the direct route when no way round exists, so
        # "avoided: [B1B2]" alone proves only what was ASKED for, not what was
        # achieved -- and a reroute that still crosses the avoided edge is a
        # fact worth having in the log rather than a claim worth hiding.
        #
        # `avoidance_succeeded` is necessary and still not sufficient, which a
        # real run showed: a person already clear of the avoided edge reroutes,
        # the avoid set is honoured trivially, and the flag reads true while the
        # walk is byte-for-byte the one it already had. `route_changed` is the
        # claim that costs something, so it is recorded next to the other.
        still_crossing = sorted(set(avoid) & set(route))
        self._event("agent_rerouted", state.agent_id, t_sim,
                    {"person_id": person_id, "route": list(route),
                     "route_len": len(route), "avoided": list(avoid),
                     "avoidance_succeeded": not still_crossing,
                     "still_crossing": still_crossing,
                     "previous_route": list(previous) if previous else [],
                     "route_changed": previous is not None
                                      and tuple(route) != tuple(previous)})

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
    """A multi-stage pedestrian agent: one travel_to goal per stage, in order.

    The FIRST element of `stages` is the ORIGIN and does not become a goal, so
    three listed edges are an origin and TWO destinations -- a two-leg trip.
    The caller passes that same first edge to `spawn` as the origin. Spelled out
    because the arithmetic is easy to misread in the other direction, and an
    episode report that counted three goals here would read a trip as a third
    finished when it had not yet started.
    """
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
