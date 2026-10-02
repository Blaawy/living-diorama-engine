"""The bridge, against a recording fake TraCI.

`ldyf/agent_sumo.py` shipped with no unit tests at all, which is how four real
defects reached a live run before being found (the origin dropped, successors
for one edge only, the via search re-run every tick, and an avoidance that was
asked for and never achieved). Every test here pins one of those, or one of the
cost properties that made a larger population possible, and none of them needs
SUMO: the connection is a fake that records what it was told.
"""
from __future__ import annotations

import pytest

from ldyf import agent_sumo as BR
from ldyf.agents import make_agent_id


class Stage:
    def __init__(self, edges):
        self.edges = list(edges)


class FakePerson:
    def __init__(self, owner):
        self.owner = owner
        self.added: list[tuple] = []
        self.walks: list[tuple[str, list[str]]] = []
        self.arrivals: list[float] = []
        self.removed: list[str] = []
        self.road: dict[str, str] = {}

    def add(self, pid, edge, pos, depart, vtype):
        self.added.append((pid, edge, pos, depart, vtype))
        self.road[pid] = edge

    def appendWalkingStage(self, pid, edges, arrival):  # noqa: N802
        self.walks.append((pid, list(edges)))
        self.arrivals.append(arrival)

    def getIDList(self):  # noqa: N802
        return [p for p, e in self.road.items() if e]

    def removeStages(self, pid):  # noqa: N802
        self.removed.append(pid)

    def getRoadID(self, pid):  # noqa: N802
        return self.road.get(pid, "")


class FakeSim:
    """A router over a fixed adjacency, counting every query it is asked."""

    def __init__(self, owner):
        self.owner = owner
        self.calls: list[tuple[str, str]] = []

    def findIntermodalRoute(self, a, b, modes=""):  # noqa: N802
        self.calls.append((a, b))
        path = self.owner.paths.get((a, b))
        if path is None:
            return []
        return [Stage(path)]


class FakeEdge:
    def __init__(self, owner):
        self.owner = owner

    def getIDList(self):  # noqa: N802
        return list(self.owner.edges)


class FakeConn:
    def __init__(self, paths, edges):
        self.paths = dict(paths)
        self.edges = list(edges)
        self.person = FakePerson(self)
        self.simulation = FakeSim(self)
        self.edge = FakeEdge(self)


#: Every direct route runs through B, and D is the only way round it. The
#: shape matters: an avoidance test on a network with no detour proves nothing
#: about avoiding, and one with no through-route proves nothing about failing.
PATHS = {
    ("A", "C"): ["A", "B", "C"],
    ("A", "E"): ["A", "B", "C", "E"],
    ("A", "B"): ["A", "B"],
    ("A", "D"): ["A", "D"],
    ("B", "C"): ["B", "C"],
    ("B", "E"): ["B", "C", "E"],
    ("C", "E"): ["C", "E"],
    ("D", "C"): ["D", "C"],
    ("D", "E"): ["D", "E"],
}
EDGES = ["A", "B", "C", "D", "E"]


@pytest.fixture(autouse=True)
def _clean_cache():
    BR.clear_route_cache()
    yield
    BR.clear_route_cache()


def conn() -> FakeConn:
    return FakeConn(PATHS, EDGES)


# -- translation -----------------------------------------------------------

def test_tokens_round_trip_and_never_double_prefix():
    assert BR.tok("A") == "edge:A"
    assert BR.tok("edge:A") == "edge:A"
    assert BR.bare("edge:A") == "A"
    assert BR.bare("A") == "A"


# -- routing ---------------------------------------------------------------

def test_sumo_is_the_router():
    c = conn()
    assert BR.sumo_walk(c, "A", "C") == ("A", "B", "C")
    assert c.simulation.calls == [("A", "C")]


def test_no_route_is_empty_not_an_exception():
    c = FakeConn({}, EDGES)
    assert BR.sumo_walk(c, "A", "C") == ()


def test_avoidance_routes_around_via_a_waypoint():
    c = conn()
    route = BR.walking_route(c, "A", "C", avoid=["B"])
    assert "B" not in route
    assert route == ("A", "D", "C")


def test_when_no_way_round_exists_the_direct_route_comes_back():
    """The caller must be able to tell avoided from could-not-avoid."""
    c = FakeConn({("A", "C"): ["A", "B", "C"], ("A", "B"): ["A", "B"],
                  ("B", "C"): ["B", "C"]}, ["A", "B", "C"])
    route = BR.walking_route(c, "A", "C", avoid=["B"])
    assert route == ("A", "B", "C")          # not () and not a lie
    assert "B" in route                      # the caller can see it failed




def test_the_waypoint_search_is_bounded():
    """An agent does not enumerate every street before deciding on a detour.

    Unbounded, this scan cost two routing queries per edge in the network per
    agent per tick, and a 24-agent run stalled for twenty minutes inside it.
    """
    many = [chr(ord("a") + i) for i in range(60)]
    # a through-route that crosses B, and no detour anywhere
    c = FakeConn({("A", "C"): ["A", "B", "C"]}, ["A", "B", "C"] + many)
    route = BR.walking_route(c, "A", "C", avoid=["B"])
    assert route == ("A", "B", "C")               # gave up, honestly
    assert len(c.simulation.calls) <= 2 * BR.VIA_SEARCH_BUDGET + 1


def test_giving_up_is_recorded_as_still_crossing():
    many = [chr(ord("a") + i) for i in range(60)]
    c = FakeConn({("A", "C"): ["A", "B", "C"], ("A", "B"): ["A", "B"],
                  ("B", "C"): ["B", "C"]}, ["A", "B", "C"] + many)
    st = _state(("A", "C"))
    b = BR.PedestrianBridge(c, None, "ep:" + "a3" * 8)
    assert b.spawn(st, "p0", "A", depart=1.0)
    c.person.road["p0"] = "A"
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0)
    p = [e for e in b.events if e["kind"] == "agent_rerouted"][0]["payload"]
    assert p["still_crossing"] == ["B"]
    assert p["avoidance_succeeded"] is False


# -- observation -----------------------------------------------------------

def _state(stages):
    """The first element is the ORIGIN, not a goal: see three_stage_walk."""
    return BR.three_stage_walk(make_agent_id("pedestrian", 0), stages)


def test_the_first_stage_is_the_origin_and_not_a_goal():
    """Three listed edges are an origin and TWO destinations, not three goals.

    Worth a test of its own because the name says "three stage" and the
    arithmetic does not: an episode report that counts these as three goals
    would read a trip as a third finished when it had not started.
    """
    st = _state(("A", "C", "E"))
    assert [g.target for g in st.goal_stack] == ["edge:C", "edge:E"]


def test_successors_cover_the_whole_route_not_just_the_current_edge():
    """One entry made every goal unreachable after one hop."""
    c = conn()
    st = _state(("C", "E"))
    c.person.road["p0"] = "A"
    obs = BR.build_observation(c, None, st, "p0")
    assert len(obs.successors) >= 3
    assert obs.successors[0] == ("edge:A", ("edge:B",))
    assert obs.reachable_edges[0] == "edge:A"


def test_an_absent_person_yields_no_observation():
    c = conn()
    st = _state(("C", "E"))
    assert BR.build_observation(c, None, st, "nobody") is None


def test_an_internal_junction_edge_yields_no_observation():
    c = conn()
    st = _state(("C", "E"))
    c.person.road["p0"] = ":junction_0"
    assert BR.build_observation(c, None, st, "p0") is None


def test_the_plan_is_not_re_derived_every_tick():
    """The cost property that made a population possible."""
    c = conn()
    st = _state(("C", "E"))
    c.person.road["p0"] = "A"
    cache: dict = {}
    BR.build_observation(c, None, st, "p0", plan_cache=cache)
    first = len(c.simulation.calls)
    assert first >= 1
    c.person.road["p0"] = "B"          # the body walked on, still on plan
    BR.build_observation(c, None, st, "p0", plan_cache=cache)
    assert len(c.simulation.calls) == first      # no new routing query
    assert len(cache) == 1


def test_going_off_the_plan_forces_a_real_replan():
    c = conn()
    st = _state(("C", "E"))
    c.person.road["p0"] = "A"
    cache: dict = {}
    BR.build_observation(c, None, st, "p0", plan_cache=cache)
    before = len(c.simulation.calls)
    c.paths[("D", "C")] = ["D", "C"]
    c.person.road["p0"] = "D"          # not on the cached route
    BR.build_observation(c, None, st, "p0", plan_cache=cache)
    assert len(c.simulation.calls) > before


def test_the_remaining_plan_is_the_suffix_from_here():
    c = conn()
    st = _state(("C", "E"))
    c.person.road["p0"] = "A"
    cache: dict = {}
    BR.build_observation(c, None, st, "p0", plan_cache=cache)
    c.person.road["p0"] = "B"
    obs = BR.build_observation(c, None, st, "p0", plan_cache=cache)
    assert obs.reachable_edges[0] == "edge:B"
    assert "edge:A" not in obs.reachable_edges


# -- spawning --------------------------------------------------------------

def test_the_origin_is_where_the_body_starts_not_the_first_goal():
    """The defect that turned every three-stage walk into one leg."""
    c = conn()
    st = _state(("A", "C", "E"))
    b = BR.PedestrianBridge(c, None, "ep:" + "a3" * 8)
    assert b.spawn(st, "p0", "A", depart=1.0) is True
    assert c.person.added[0][1] == "A"        # the body starts at the origin
    assert len(c.person.walks) == 2           # one walking stage per goal
    assert c.person.walks[0][1][0] == "A"     # and the first leg starts there
    assert c.person.walks[1][1][0] == "C"     # the second from the first goal


def test_a_walk_needs_at_least_two_stages():
    with pytest.raises(ValueError):
        BR.three_stage_walk(make_agent_id("pedestrian", 0), ("C",))


def test_a_spawn_that_sumo_refuses_is_not_recorded():
    c = conn()

    def boom(*a, **k):
        raise RuntimeError("no such edge")

    c.person.add = boom
    st = _state(("C", "E"))
    b = BR.PedestrianBridge(c, None, "ep:" + "a3" * 8)
    assert b.spawn(st, "p0", "A", depart=1.0) is False
    assert b.person_of == {}
    assert b.events == []


# -- the replan, and what it is allowed to claim ---------------------------

def _spawned_bridge():
    c = conn()
    st = _state(("C", "E"))
    b = BR.PedestrianBridge(c, None, "ep:" + "a3" * 8)
    assert b.spawn(st, "p0", "A", depart=1.0)
    c.person.road["p0"] = "A"
    return c, b, st


def test_a_replan_records_the_route_and_whether_avoidance_achieved_it():
    c, b, st = _spawned_bridge()
    b._execute_replan(st, "p0", BR.build_observation(
        c, None, st, "p0", blocked_edges=["B"]), 30.0)
    ev = [e for e in b.events if e["kind"] == "agent_rerouted"]
    assert len(ev) == 1
    p = ev[0]["payload"]
    assert p["avoidance_succeeded"] is True
    assert p["still_crossing"] == []
    assert "B" not in p["route"]
    assert p["route_changed"] is True


def test_an_avoidance_that_could_not_be_achieved_says_so():
    """An avoid set must never stand in for a route that honoured it."""
    c = FakeConn({("A", "C"): ["A", "B", "C"], ("A", "B"): ["A", "B"],
                  ("B", "C"): ["B", "C"]}, ["A", "B", "C"])
    st = _state(("A", "C"))
    b = BR.PedestrianBridge(c, None, "ep:" + "a3" * 8)
    assert b.spawn(st, "p0", "A", depart=1.0)
    c.person.road["p0"] = "A"
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0)
    p = [e for e in b.events if e["kind"] == "agent_rerouted"][0]["payload"]
    assert p["avoidance_succeeded"] is False
    assert p["still_crossing"] == ["B"]


def test_a_reroute_onto_the_same_route_is_not_a_changed_route():
    """avoidance_succeeded is necessary and not sufficient."""
    c, b, st = _spawned_bridge()
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["D"])
    b._execute_replan(st, "p0", obs, 30.0)
    p = [e for e in b.events if e["kind"] == "agent_rerouted"][0]["payload"]
    assert p["avoidance_succeeded"] is True      # D was never on the route
    assert p["route_changed"] is False           # and nothing actually changed




def test_a_replan_voids_only_this_agents_cached_plan():
    c, b, st = _spawned_bridge()
    other = BR.three_stage_walk(make_agent_id("pedestrian", 1), ("C", "E"))
    b.plan_cache[(other.agent_id, "C", ())] = ("A", "B", "C")
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"],
                               plan_cache=b.plan_cache)
    b._execute_replan(st, "p0", obs, 30.0)
    assert any(k[0] == other.agent_id for k in b.plan_cache)
    mine = [v for k, v in b.plan_cache.items() if k[0] == st.agent_id]
    assert mine and all("B" not in v for v in mine)


def test_the_bridge_never_writes_a_pose():
    """SUMO moves every body. The bridge is not allowed to help."""
    src = BR.__file__.replace(".pyc", ".py")
    with open(src, encoding="utf-8") as f:
        text = f.read()
    for forbidden in ("moveTo", "moveToXY", "setSpeed", "setAngle",
                      "setPosition"):
        assert forbidden not in text, forbidden


def test_the_agent_layer_never_imports_traci():
    from ldyf import agents
    with open(agents.__file__, encoding="utf-8") as f:
        text = f.read()
    assert "traci" not in text


# -- the trip survives a replan, and the body's exit is recorded -----------

def test_a_replan_keeps_the_legs_after_the_one_it_replanned():
    """removeStages drops the whole trip; only re-adding one leg strands it.

    Measured over 900 s before this was fixed: every rerouted person walked its
    detour, was removed by SUMO at the end of that single leg, and no rerouted
    agent ever reached a goal.
    """
    c = conn()
    st = _state(("A", "C", "E"))
    b = BR.PedestrianBridge(c, None, "ep:" + "a3" * 8)
    assert b.spawn(st, "p0", "A", depart=1.0)
    c.person.road["p0"] = "A"
    c.person.walks.clear()
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0)
    assert c.person.removed == ["p0"]
    assert len(c.person.walks) == 2                   # the detour AND the next leg
    assert c.person.walks[0][1][-1] == "C"
    assert c.person.walks[1][1][0] == "C" and c.person.walks[1][1][-1] == "E"




def test_a_body_leaving_the_simulation_is_recorded_once():
    c = conn()
    st = _state(("A", "C", "E"))
    b = BR.PedestrianBridge(c, None, "ep:" + "a3" * 8)
    assert b.spawn(st, "p0", "A", depart=1.0)
    c.person.road["p0"] = "A"
    st = b.step(st, 1, t_sim=1.0)
    c.person.road["p0"] = ""                          # SUMO removed the person
    b.step(st, 2, t_sim=2.0)
    b.step(st, 3, t_sim=3.0)
    left = [e for e in b.events if e["kind"] == "agent_body_left"]
    assert len(left) == 1
    assert left[0]["payload"]["last_edge"] == "A"


def test_a_body_not_yet_departed_is_not_reported_as_left():
    c = conn()
    st = _state(("A", "C", "E"))
    b = BR.PedestrianBridge(c, None, "ep:" + "a3" * 8)
    assert b.spawn(st, "p0", "A", depart=50.0)
    c.person.road["p0"] = ""
    b.step(st, 1, t_sim=1.0)
    assert not [e for e in b.events if e["kind"] == "agent_body_left"]


# ==========================================================================
# Round 2: every item below was a finding of the independent read-only review
# of this module. Each test reproduces the reviewer's own attack.
# ==========================================================================

#: A wider network for the round-2 attacks. Direct A->C and C->E both run
#: through B; D and G are ways round; F reaches D only THROUGH B.
R2_PATHS = {
    ("A", "C"): ["A", "B", "C"], ("A", "D"): ["A", "D"], ("D", "C"): ["D", "C"],
    ("C", "E"): ["C", "B", "E"], ("C", "D"): ["C", "D"], ("D", "E"): ["D", "E"],
    ("A", "E"): ["A", "B", "E"],
    ("F", "C"): ["F", "B", "C"], ("F", "D"): ["F", "B", "D"],
    ("F", "G"): ["F", "G"], ("G", "C"): ["G", "C"],
}
R2_EDGES = ["A", "B", "C", "D", "E", "F", "G"]


def r2() -> FakeConn:
    return FakeConn(R2_PATHS, R2_EDGES)


def _bridge(c, stages=("A", "C", "E"), pid="p0"):
    st = BR.three_stage_walk(make_agent_id("pedestrian", 0), stages)
    b = BR.PedestrianBridge(c, None, "ep:" + "a3" * 8)
    assert b.spawn(st, pid, stages[0], depart=1.0)
    c.person.road[pid] = stages[0]
    return b, st


def _rerouted(b):
    return [e["payload"] for e in b.events if e["kind"] == "agent_rerouted"]


# -- B5: completing a goal must not block the agent or touch its walk -------

def test_reaching_the_first_goal_does_not_tear_out_the_walk():
    """The observation offered only the FIRST goal's route.

    When the agent completed that goal, its next goal was missing from what it
    could reach, so it was declared blocked and its walk was removed and
    re-laid -- for every agent, in both arms, including the control. A real
    900 s baseline run with no rule at all logged 48 reroutes.
    """
    c = conn()
    b, st = _bridge(c)
    walks_after_spawn = len(c.person.walks)
    for tick, edge in enumerate(("A", "B", "C", "C", "E", "E"), start=1):
        c.person.road["p0"] = edge
        st = b.step(st, tick, t_sim=float(tick))
    assert c.person.removed == []                       # nothing was torn out
    assert len(c.person.walks) == walks_after_spawn     # nothing was re-laid
    assert _rerouted(b) == []
    kinds = [e["kind"] for e in b.events]
    assert kinds.count("goal_completed") == 2
    assert st.status == "done"


def test_the_observation_covers_every_remaining_goal():
    c = conn()
    st = _state(("A", "C", "E"))
    c.person.road["p0"] = "A"
    obs = BR.build_observation(c, None, st, "p0")
    assert obs.reachable_edges == ("edge:A", "edge:B", "edge:C", "edge:E")


# -- B1: still_crossing must read the WHOLE walk, not its first leg ---------

def test_a_later_leg_through_the_avoided_edge_is_reported():
    """Leg one detours round B; leg two has no way round and goes through it."""
    paths = dict(R2_PATHS)
    del paths[("C", "D")]                                # no detour for leg two
    c = FakeConn(paths, R2_EDGES)
    b, st = _bridge(c)
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0, blocked_edges=["B"])
    p = _rerouted(b)[0]
    assert [leg["target"] for leg in p["legs"]] == ["C", "E"]
    assert "B" not in p["legs"][0]["route"] and "B" in p["legs"][1]["route"]
    assert p["still_crossing"] == ["B"]
    assert p["avoidance_succeeded"] is False
    assert b.applied_routes["p0"] == tuple(p["route"])   # all legs, not one


# -- B2: a leg with no route is named, never dropped in silence -------------

def test_a_later_leg_with_no_route_is_named_in_the_event():
    paths = {k: v for k, v in R2_PATHS.items() if k[1] != "E"}
    c = FakeConn(paths, R2_EDGES)
    st = BR.three_stage_walk(make_agent_id("pedestrian", 0), ("A", "C", "E"))
    b = BR.PedestrianBridge(c, None, "ep:" + "a3" * 8)
    assert b.spawn(st, "p0", "A", depart=1.0)
    spawned = [e["payload"] for e in b.events if e["kind"] == "agent_spawned"][0]
    assert spawned["stages_without_route"] == ["E"]
    c.person.road["p0"] = "A"
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0, blocked_edges=["B"])
    p = _rerouted(b)[0]
    assert p["legs_without_route"] == ["E"]
    assert p["complete"] is False


# -- B3: a failure AFTER the walk was replaced is not "nothing happened" ----

def test_a_failure_part_way_reports_the_walk_the_body_actually_has():
    c = r2()
    b, st = _bridge(c)
    calls = {"n": 0}
    real = c.person.appendWalkingStage

    def second_one_fails(pid, edges, arrival):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("stage refused")
        real(pid, edges, arrival)

    c.person.appendWalkingStage = second_one_fails
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0, blocked_edges=["B"])
    kinds = [e["kind"] for e in b.events]
    assert "agent_reroute_failed" not in kinds          # the walk DID change
    p = _rerouted(b)[0]
    assert p["complete"] is False and "stage refused" in p["error"]
    assert p["legs_not_applied"] == ["E"]
    assert [leg["target"] for leg in p["legs"]] == ["C"]
    assert b.applied_routes["p0"] == tuple(p["route"]) == ("A", "D", "C")


def test_a_failure_before_anything_changed_says_the_walk_is_unchanged():
    c = r2()
    b, st = _bridge(c)
    before = b.applied_routes["p0"]

    def boom(pid):
        raise RuntimeError("person gone")

    c.person.removeStages = boom
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0, blocked_edges=["B"])
    failed = [e["payload"] for e in b.events if e["kind"] == "agent_reroute_failed"]
    assert len(failed) == 1 and failed[0]["walk_changed"] is False
    assert _rerouted(b) == []
    assert b.applied_routes["p0"] == before


# -- B4: a shared waypoint is a preference, not a verdict -------------------

def test_the_via_point_is_shared_across_agents():
    """The second agent must actually REACH the shared-waypoint branch."""
    c = conn()
    c.paths[("E", "C")] = ["E", "B", "C"]
    c.paths[("E", "D")] = ["E", "D"]
    assert BR.walking_route(c, "A", "C", avoid=["B"]) == ("A", "D", "C")
    c.simulation.calls.clear()
    assert BR.walking_route(c, "E", "C", avoid=["B"]) == ("E", "D", "C")
    # the direct probe, then the two legs through the known waypoint: no scan
    assert c.simulation.calls == [("E", "C"), ("E", "D"), ("D", "C")]


def test_a_waypoint_that_does_not_work_from_here_does_not_end_the_search():
    """F reaches the shared waypoint D only THROUGH the closed edge; G works."""
    c = r2()
    assert BR.walking_route(c, "A", "C", avoid=["B"]) == ("A", "D", "C")
    route = BR.walking_route(c, "F", "C", avoid=["B"])
    assert route == ("F", "G", "C")
    assert "B" not in route


def test_a_detour_beyond_the_budget_is_not_found_and_says_so():
    many = ["a%02d" % i for i in range(BR.VIA_SEARCH_BUDGET + 4)]
    paths = {("A", "C"): ["A", "B", "C"], ("A", "z"): ["A", "z"], ("z", "C"): ["z", "C"]}
    c = FakeConn(paths, ["A", "B", "C"] + many + ["z"])
    route = BR.walking_route(c, "A", "C", avoid=["B"])
    assert route == ("A", "B", "C")                      # a detour EXISTS, unfound
    assert len(c.simulation.calls) <= 2 * BR.VIA_SEARCH_BUDGET + 1


# -- B6: route_changed compares like with like ------------------------------

def test_an_irrelevant_avoid_on_a_multi_leg_trip_is_not_a_changed_route():
    """It used to be true by construction: one new leg against all old legs."""
    c = conn()
    b, st = _bridge(c)
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["D"])
    b._execute_replan(st, "p0", obs, 30.0, blocked_edges=["D"])
    p = _rerouted(b)[0]
    assert p["route"] == ["A", "B", "C", "E"] == p["previous_route"]
    assert p["route_changed"] is False


def test_a_real_detour_on_a_multi_leg_trip_is_a_changed_route():
    c = r2()
    b, st = _bridge(c)
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0, blocked_edges=["B"])
    p = _rerouted(b)[0]
    assert p["route"] == ["A", "D", "C", "D", "E"]
    assert p["route_changed"] is True and p["still_crossing"] == []
    assert p["complete"] is True


def test_route_changed_is_measured_from_where_the_body_is():
    c = conn()
    b, st = _bridge(c)
    c.person.road["p0"] = "B"                            # one edge along
    st = b.step(st, 1, t_sim=1.0)
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["D"])
    c.paths[("B", "C")] = ["B", "C"]
    b._execute_replan(st, "p0", obs, 30.0, blocked_edges=["D"])
    p = _rerouted(b)[0]
    assert p["previous_route"] == ["B", "C", "E"]        # the REMAINDER
    assert p["route_changed"] is False


# -- B7: an exception is not evidence that a body has gone ------------------

def test_a_raising_id_list_does_not_record_a_present_body_as_gone():
    c = conn()
    b, st = _bridge(c)
    st = b.step(st, 1, t_sim=1.0)
    c.person.road["p0"] = ":junction_0"                  # present, no observation
    real = c.person.getIDList

    def boom():
        raise RuntimeError("traci hiccup")

    c.person.getIDList = boom
    b.step(st, 2, t_sim=2.0)
    assert not [e for e in b.events if e["kind"] == "agent_body_left"]
    c.person.getIDList = real
    c.person.road["p0"] = ""                             # now it really leaves
    b.step(st, 3, t_sim=3.0)
    left = [e for e in b.events if e["kind"] == "agent_body_left"]
    assert len(left) == 1 and left[0]["t_sim"] == 3.0


def test_a_body_already_recorded_as_gone_costs_no_more_queries():
    c = conn()
    b, st = _bridge(c)
    st = b.step(st, 1, t_sim=1.0)
    c.person.road["p0"] = ""
    b.step(st, 2, t_sim=2.0)
    asked = {"n": 0}
    real = c.person.getIDList

    def counting():
        asked["n"] += 1
        return real()

    c.person.getIDList = counting
    for tick in range(3, 103):
        b.step(st, tick, t_sim=float(tick))
    assert asked["n"] == 0


# -- B8: router_calls counts routing queries, all of them -------------------

def test_router_calls_is_the_number_of_queries_sumo_was_asked():
    c = r2()
    st = BR.three_stage_walk(make_agent_id("pedestrian", 0), ("A", "C", "E"))
    b = BR.PedestrianBridge(c, None, "ep:" + "a3" * 8)
    assert b.router_calls == 0
    assert b.spawn(st, "p0", "A", depart=1.0)
    assert b.router_calls == len(c.simulation.calls) > 0     # spawn is counted
    c.person.road["p0"] = "A"
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0, blocked_edges=["B"])
    assert b.router_calls == len(c.simulation.calls)         # so is the replan


# -- B9: a route may visit an edge twice ------------------------------------

def test_the_plan_pointer_moves_forward_past_a_repeated_edge():
    c = FakeConn({("A", "C"): ["A", "B", "X", "B", "C"]}, ["A", "B", "C", "X"])
    st = BR.three_stage_walk(make_agent_id("pedestrian", 0), ("A", "C"))
    cache: dict = {}
    seen = []
    for edge in ("A", "B", "X", "B", "C"):
        c.person.road["p0"] = edge
        obs = BR.build_observation(c, None, st, "p0", plan_cache=cache)
        seen.append(obs.reachable_edges)
    # (the Observation sorts what it is given, so compare as sets)
    assert set(seen[1]) == {"edge:B", "edge:X", "edge:C"}    # first visit to B
    assert set(seen[3]) == {"edge:B", "edge:C"}              # second: X is behind it
    assert len(c.simulation.calls) == 1                  # and no re-routing


# -- B10: a world fact and an agent policy are different things -------------

def test_policy_avoidance_is_not_reported_as_a_blocked_edge():
    c = r2()
    b, st = _bridge(c)
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"],
                               avoid_also=["G"])
    assert obs.blocked_edges == ("edge:B",)              # G was not closed
    b._execute_replan(st, "p0", obs, 30.0, blocked_edges=["B"], avoid_also=["G"])
    p = _rerouted(b)[0]
    assert p["perceived_blocked"] == ["B"]
    assert p["avoided_by_policy"] == ["G"]
    assert p["avoided"] == ["B", "G"]


def test_policy_avoidance_still_shapes_the_route():
    c = r2()
    st = BR.three_stage_walk(make_agent_id("pedestrian", 0), ("F", "C"))
    c.person.road["p0"] = "F"
    c.paths[("F", "C")] = ["F", "G", "C"]
    c.paths[("F", "D")] = ["F", "D"]
    obs = BR.build_observation(c, None, st, "p0", avoid_also=["G"])
    assert "edge:G" not in obs.reachable_edges
    assert obs.blocked_edges == ()


def test_memory_events_carry_their_subject():
    c = r2()
    b, st = _bridge(c)
    st = b.step(st, 1, t_sim=1.0)                        # a plan through B
    st = b.step(st, 2, t_sim=2.0, blocked_edges=["B"])   # then B closes
    seen = [e for e in b.events if e["kind"] == "blocked_edge_seen"]
    assert seen and all(e["payload"]["subject"] == "edge:B" for e in seen)
    # and the closure produced exactly one real reroute, round B
    p = _rerouted(b)
    assert len(p) == 1 and p[0]["route_changed"] and p[0]["still_crossing"] == []


# -- B11: tests that now assert what their names say ------------------------

def test_every_stage_ends_at_the_declared_arrival_position():
    c = r2()
    b, st = _bridge(c)
    assert c.person.arrivals and set(c.person.arrivals) == {BR.STAGE_ARRIVAL_POS}
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0, blocked_edges=["B"])
    assert set(c.person.arrivals) == {BR.STAGE_ARRIVAL_POS}     # after a replan too


def test_the_later_legs_of_a_replan_honour_the_avoid_set():
    c = r2()
    b, st = _bridge(c)
    c.person.walks.clear()
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0, blocked_edges=["B"])
    assert len(c.person.walks) == 2
    assert all("B" not in edges for _, edges in c.person.walks)


def test_initial_routes_is_never_overwritten():
    c = r2()
    b, st = _bridge(c)
    first = b.initial_routes["p0"]
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0, blocked_edges=["B"])
    assert b.initial_routes["p0"] == first != b.applied_routes["p0"]
    assert b.spawn(st, "p0", "A", depart=5.0) is False   # a second spawn is refused
    assert b.initial_routes["p0"] == first


def test_giving_up_within_budget_when_a_detour_exists_is_still_recorded():
    many = ["a%02d" % i for i in range(BR.VIA_SEARCH_BUDGET + 4)]
    paths = {("A", "C"): ["A", "B", "C"], ("A", "z"): ["A", "z"], ("z", "C"): ["z", "C"]}
    c = FakeConn(paths, ["A", "B", "C"] + many + ["z"])
    st = BR.three_stage_walk(make_agent_id("pedestrian", 0), ("A", "C"))
    b = BR.PedestrianBridge(c, None, "ep:" + "a3" * 8)
    assert b.spawn(st, "p0", "A", depart=1.0)
    c.person.road["p0"] = "A"
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0, blocked_edges=["B"])
    p = _rerouted(b)[0]
    assert p["still_crossing"] == ["B"] and p["avoidance_succeeded"] is False


def test_the_bridge_changes_a_body_only_through_three_calls():
    """A substring scan for moveTo proved little. This lists EVERY TraCI write.

    The bridge may add a person, append a walking stage and remove stages.
    Anything else that writes to `conn.person` or `conn.vehicle` is a new way
    to move a body and must be argued for here.
    """
    import re

    with open(BR.__file__.replace(".pyc", ".py"), encoding="utf-8") as f:
        text = f.read()
    writes = set(re.findall(r"conn\.(?:person|vehicle)\.(\w+)\(", text))
    reads = {"getRoadID", "getIDList"}
    assert writes - reads == {"add", "appendWalkingStage", "removeStages"}
