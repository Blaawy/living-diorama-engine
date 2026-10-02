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
    "join_legs",
    "plan_trip",
    "three_stage_walk",
    "tok",
    "sumo_walk",
    "walking_route",
]


#: Every routing query this process has put to SUMO. A list so the count is
#: shared by reference; the bridge reports the difference since it was created.
#: An earlier counter watched the plan cache grow instead, and so missed spawn
#: routing, every replan and every waypoint probe -- it was reported as the
#: cost of the run and was not a count of anything SUMO had been asked.
ROUTER_QUERIES = [0]


def sumo_walk(conn: Any, from_edge: str, to_edge: str) -> tuple[str, ...]:
    """The walking route SUMO itself returns. SUMO is the router, not this file.

    sumolib's edge-level `getShortestPath` cannot route a pedestrian on this
    network -- it returns cost `inf`, because walking uses crossings and
    walking-areas that the edge graph does not model. `findIntermodalRoute` is
    SUMO's own pedestrian router and is what mobility truth means here.
    """
    ROUTER_QUERIES[0] += 1
    try:
        stages = conn.simulation.findIntermodalRoute(from_edge, to_edge, modes="")
    except Exception:
        return ()
    return tuple(e for st in stages for e in st.edges)


#: Routes already computed this episode, keyed by (from, to, avoid). The result
#: is a pure function of the key within one episode, so caching it changes
#: nothing but the cost.
_ROUTE_CACHE: dict[tuple[str, str, tuple[str, ...]], tuple[str, ...]] = {}

#: The via-point that worked for a (destination, avoid set), without the origin.
#: A waypoint is a fact about the NETWORK and the closure, not about who is
#: walking, so the first agent to find one pays the scan and later agents try
#: it FIRST. It is a preference and not a verdict: if it does not work from
#: where a later agent stands, that agent searches on within its own budget.
#: Trying it exclusively forced an agent through the closed edge when a
#: different detour existed for it.
_VIA_CHOICE: dict[tuple[str, tuple[str, ...]], str] = {}

#: Where on its last edge a walking stage ends. 0.0 is the START of that edge,
#: so a body "arrived" the instant it set foot on its goal edge. A negative
#: position counts back from the END of the edge.
STAGE_ARRIVAL_POS = -1.0

#: How many waypoints an agent will try before it gives up and walks the direct
#: route. Two routing queries per candidate, so an unbounded scan is
#: indefensible. Giving up is not faking anything: the closure bars the
#: carriageway and leaves the footway open, so the direct walk is a legal
#: outcome, and the reroute event records `still_crossing`.
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

    Returns () when there is no route at all, and the DIRECT route when no way
    round was FOUND WITHIN THE SEARCH BUDGET -- which is not the same as none
    existing. The caller tells the cases apart by checking whether the result
    still contains an avoided edge.
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
        pool = [known] + [e for e in pool if e != known]

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
            _VIA_CHOICE.setdefault(via_key, via)
            return joined
    _ROUTE_CACHE[key] = direct
    return direct


def _edge_ids(conn: Any) -> list[str]:
    try:
        return [e for e in conn.edge.getIDList() if not e.startswith(":")]
    except Exception:
        return []


def plan_trip(conn: Any, from_edge: str, targets: Sequence[str],
              avoid: Sequence[str] = ()) -> list[tuple[str, tuple[str, ...]]]:
    """One routed leg per travel target, in order: ``[(target, route), ...]``.

    A leg whose target has no route at all comes back with an empty route and
    the next leg is planned from the last place the trip actually reaches, so
    the caller can see exactly which legs exist and which do not.
    """
    legs: list[tuple[str, tuple[str, ...]]] = []
    here = from_edge
    for target in targets:
        route = walking_route(conn, here, target, avoid=avoid)
        legs.append((target, tuple(route)))
        if route:
            here = target
    return legs


def join_legs(legs: Sequence[tuple[str, tuple[str, ...]]]) -> tuple[str, ...]:
    """The legs as ONE edge sequence, the shared edge at each seam kept once."""
    out: list[str] = []
    for _, route in legs:
        for i, edge in enumerate(route):
            if i == 0 and out and out[-1] == edge:
                continue
            out.append(edge)
    return tuple(out)


def _travel_targets(state: AgentState) -> tuple[str, ...]:
    return tuple(bare(g.target) for g in state.goal_stack if g.kind == "travel_to")


def _avoid_set(state: AgentState, blocked_edges: Sequence[str],
               avoid_also: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(
        {bare(e) for e in blocked_edges} | {bare(e) for e in avoid_also}
        | {bare(g.target) for g in state.goal_stack if g.kind == "avoid"}))


def build_observation(
    conn: Any,
    net: Any,
    state: AgentState,
    person_id: str,
    *,
    blocked_edges: Sequence[str] = (),
    avoid_also: Sequence[str] = (),
    t_sim: float = 0.0,
    neighbour_radius_m: float = 25.0,
    plan_cache: dict | None = None,
) -> Observation | None:
    """What this agent may know this tick, read from the live simulation.

    Returns None when the person is not in the simulation (not yet departed, or
    already arrived): there is no observation to make, and inventing one would
    be inventing a world.

    `blocked_edges` is what the WORLD says is closed and is passed to the agent
    as a fact. `avoid_also` is the agent's own policy -- edges it chooses to
    stay off although nothing closed them -- and shapes the route without being
    reported as a blocked edge.

    The route offered covers the WHOLE remaining trip, every travel goal in
    order, not just the first. Offering only the first goal's route meant that
    the moment the agent completed a goal, its next goal was absent from what
    it could reach: every agent in both arms was declared blocked at its first
    arrival and had its walk torn out and re-laid, including the control arm.

    `plan_cache`, when given, holds the plan each agent is CURRENTLY walking
    and how far along it the body has got. A planner that re-derives its plan
    every second is a poor model of a person and cost ten minutes of routing in
    a 900 s run; a plan is made once, and re-made when the goals change, when
    what is avoided changes, or when the body is found off the plan.
    """
    try:
        current = str(conn.person.getRoadID(person_id))
    except Exception:
        return None
    if not current or current.startswith(":"):
        # on an internal junction edge: the agent has no decision to make here
        return None

    targets = _travel_targets(state) or (current,)
    avoid = _avoid_set(state, blocked_edges, avoid_also)
    route: tuple[str, ...] = ()
    key = (state.agent_id, targets, avoid)
    if plan_cache is not None:
        cached = plan_cache.get(key)
        if cached:
            plan, at = cached
            # search FORWARD from where the body last was: a route may visit an
            # edge twice, and the first occurrence is not where it is now
            for i in range(at, len(plan)):
                if plan[i] == current:
                    plan_cache[key] = (plan, i)
                    route = plan[i:]
                    break
    if not route:
        route = join_legs(plan_trip(conn, current, targets, avoid))
        if plan_cache is not None and route:
            plan_cache[key] = (tuple(route), 0)
    reachable = tuple(dict.fromkeys(tok(e) for e in route)) if route else ()

    # The agent checks reachability by walking a SUCCESSORS graph, so it must be
    # given the topology ALONG the route, not just the current edge's outgoing
    # set. An edge visited twice contributes both of its onward steps.
    onward: dict[str, list[str]] = {}
    for i, edge in enumerate(route):
        nxt = onward.setdefault(tok(edge), [])
        if i + 1 < len(route) and tok(route[i + 1]) not in nxt:
            nxt.append(tok(route[i + 1]))
    successors = [(edge, tuple(nxt)) for edge, nxt in onward.items()]

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
        #: the whole route each body is currently laid on, every leg joined
        self.applied_routes: dict[str, tuple[str, ...]] = {}
        #: the route each body was FIRST given; never overwritten by a replan
        self.initial_routes: dict[str, tuple[str, ...]] = {}
        #: per (agent, goals, avoid): (plan, index the body has reached)
        self.plan_cache: dict[tuple, tuple[tuple[str, ...], int]] = {}
        self._queries_at_start = ROUTER_QUERIES[0]
        self._present: set[str] = set()
        self._left: set[str] = set()
        self._last_edge: dict[str, str] = {}
        self.seq = 0

    @property
    def router_calls(self) -> int:
        """Routing queries put to SUMO since this bridge was created. All of them."""
        return ROUTER_QUERIES[0] - self._queries_at_start

    # -- spawning ----------------------------------------------------------
    def spawn(self, state: AgentState, person_id: str, origin: str, *,
              depart: float, vtype: str = "DEFAULT_PEDTYPE") -> bool:
        """Create the SUMO person for a multi-stage agent, stage by stage.

        `origin` is where the body starts; the goal stack is where it is going.
        They are separate on purpose: an earlier version used the first GOAL as
        the origin, which put every person down on the middle edge of its own
        trip. Every goal becomes a walking stage, so the person SUMO carries is
        the agent's whole trip.
        """
        targets = _travel_targets(state)
        if not targets or person_id in self.initial_routes:
            return False
        legs = [(t, r) for t, r in plan_trip(self.conn, bare(origin), targets) if r]
        if not legs:
            return False
        try:
            self.conn.person.add(person_id, bare(origin), 0.0, depart, vtype)
            for _, route in legs:
                self.conn.person.appendWalkingStage(person_id, list(route),
                                                    STAGE_ARRIVAL_POS)
        except Exception:
            return False
        joined = join_legs(legs)
        self.applied_routes[person_id] = joined
        self.initial_routes[person_id] = joined
        self.person_of[state.agent_id] = person_id
        self._event("agent_spawned", state.agent_id, depart,
                    {"person_id": person_id, "origin": bare(origin),
                     "stages": [t for t, _ in legs],
                     "stages_without_route": [t for t in targets
                                              if t not in {x for x, _ in legs}]})
        return True

    # -- the tick ----------------------------------------------------------
    def step(self, state: AgentState, tick: int, *, t_sim: float,
             blocked_edges: Sequence[str] = (),
             avoid_also: Sequence[str] = ()) -> AgentState:
        """One tick for one agent: observe, decide, and execute the intent.

        `avoid_also` is agent POLICY, not a world fact: edges the agents stay
        off because of what they perceive, although the rule did not close
        them. It is never reported to the agent as blocked, and every reroute
        event names it separately from what was actually closed.
        """
        person_id = self.person_of.get(state.agent_id)
        if person_id is None:
            return state
        obs = build_observation(self.conn, self.net, state, person_id,
                                blocked_edges=blocked_edges, avoid_also=avoid_also,
                                t_sim=t_sim, plan_cache=self.plan_cache)
        if obs is None:
            self._note_absence(state, person_id, t_sim)
            return state
        self._present.add(person_id)
        self._last_edge[person_id] = bare(obs.current_edge)

        step = step_agent(state, obs, tick, self.episode_id)
        for record in step.records:
            self._event(str(record.kind), state.agent_id, t_sim,
                        {"value": record.value, "subject": record.subject_id})

        if step.replanned:
            self._execute_replan(step.state, person_id, obs, t_sim,
                                 blocked_edges=blocked_edges, avoid_also=avoid_also)
        return step.state

    def _note_absence(self, state: AgentState, person_id: str,
                      t_sim: float) -> None:
        """Record, once, that a body which was in the simulation has left it.

        The agent layer cannot be stepped without an observation, so an agent
        whose body is gone simply stops. Without this event the log could not
        tell "still walking" from "SUMO removed the person".

        If SUMO cannot be asked, NOTHING is recorded: an exception is not
        evidence that the body has gone, and recording it as such once marked a
        present body as departed and then swallowed its real departure.
        """
        if person_id in self._left or person_id not in self._present:
            return
        try:
            still_there = person_id in self.conn.person.getIDList()
        except Exception:
            return
        if still_there:
            return
        self._left.add(person_id)
        self._event("agent_body_left", state.agent_id, t_sim,
                    {"person_id": person_id,
                     "last_edge": self._last_edge.get(person_id, ""),
                     "goals_left": len(state.goal_stack)})

    def _execute_replan(self, state: AgentState, person_id: str,
                        obs: Observation, t_sim: float, *,
                        blocked_edges: Sequence[str] = (),
                        avoid_also: Sequence[str] = ()) -> None:
        """Rewrite the person's remaining walk to the route the agent chose.

        This is the one place intent becomes a TraCI call. It replaces the
        remaining stages rather than nudging a position: SUMO still walks the
        body, along a route the agent picked.

        Every leg is ROUTED before anything is changed, and the event describes
        the whole walk the body was actually given -- not just its first leg.
        """
        targets = _travel_targets(state)
        if not targets:
            return
        current = bare(obs.current_edge)
        avoid = _avoid_set(state, blocked_edges or [bare(e) for e in obs.blocked_edges],
                           avoid_also)
        planned = plan_trip(self.conn, current, targets, avoid)
        legs = [(t, r) for t, r in planned if r]
        without_route = [t for t, r in planned if not r]
        if not legs:
            self._event("agent_reroute_failed", state.agent_id, t_sim,
                        {"person_id": person_id, "error": "no leg has a route",
                         "walk_changed": False, "legs_without_route": without_route})
            return

        previous = self.applied_routes.get(person_id, ())
        # what was LEFT of the old walk from here, so the comparison is between
        # two walks from the same place rather than a suffix against a whole
        at = max((i for i, e in enumerate(previous) if e == current), default=None)
        previous_remaining = tuple(previous[at:]) if at is not None else tuple(previous)

        applied: list[tuple[str, tuple[str, ...]]] = []
        removed = False
        error = None
        try:
            # removeStages drops EVERY stage; SUMO removes a person with no
            # stages on the next step, so the replacement is appended at once
            self.conn.person.removeStages(person_id)
            removed = True
            for target, route in legs:
                self.conn.person.appendWalkingStage(person_id, list(route),
                                                    STAGE_ARRIVAL_POS)
                applied.append((target, route))
        except Exception as exc:
            error = repr(exc)[:160]

        if not removed:
            self._event("agent_reroute_failed", state.agent_id, t_sim,
                        {"person_id": person_id, "error": error,
                         "walk_changed": False})
            return

        joined = join_legs(applied)
        self.applied_routes[person_id] = joined
        # the plan the agent was observing against is void; only this agent's
        for k in [k for k in self.plan_cache if k[0] == state.agent_id]:
            del self.plan_cache[k]
        if joined and error is None and not without_route:
            self.plan_cache[(state.agent_id, targets, avoid)] = (joined, 0)

        # `avoided` alone proves only what was ASKED for. still_crossing is
        # read off the WHOLE walk the body now has, every leg; route_changed
        # compares it with what was left of the old walk from this same edge.
        still_crossing = sorted(set(avoid) & set(joined))
        self._event("agent_rerouted", state.agent_id, t_sim, {
            "person_id": person_id,
            "route": list(joined),
            "legs": [{"target": t, "route": list(r)} for t, r in applied],
            "route_len": len(joined),
            "avoided": list(avoid),
            "perceived_blocked": sorted(bare(e) for e in (
                blocked_edges or obs.blocked_edges)),
            "avoided_by_policy": sorted(bare(e) for e in avoid_also),
            "avoidance_succeeded": not still_crossing,
            "still_crossing": still_crossing,
            "previous_route": list(previous_remaining),
            "route_changed": joined != previous_remaining,
            "legs_without_route": without_route,
            "legs_not_applied": [t for t, _ in legs[len(applied):]],
            "complete": error is None and not without_route,
            "error": error,
        })

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
