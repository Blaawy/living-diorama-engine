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
        self.removed: list[str] = []
        self.road: dict[str, str] = {}

    def add(self, pid, edge, pos, depart, vtype):
        self.added.append((pid, edge, pos, depart, vtype))
        self.road[pid] = edge

    def appendWalkingStage(self, pid, edges, arrival):  # noqa: N802
        self.walks.append((pid, list(edges)))

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


def test_the_via_point_is_shared_across_agents():
    """A waypoint is a fact about the network, not about who is walking."""
    c = conn()
    BR.walking_route(c, "A", "C", avoid=["B"])
    scan_calls = len(c.simulation.calls)
    c.simulation.calls.clear()
    # a second agent, a different origin, the same destination and closure
    c.paths[("E", "D")] = ["E", "D"]
    BR.walking_route(c, "E", "C", avoid=["B"])
    # it tries the known waypoint first, so it costs the two legs plus the
    # direct probe -- never another scan of the whole network
    assert len(c.simulation.calls) < scan_calls
    assert len(c.simulation.calls) <= 3


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


def test_a_failed_traci_call_is_recorded_not_swallowed():
    c, b, st = _spawned_bridge()

    def boom(*a, **k):
        raise RuntimeError("person gone")

    c.person.appendWalkingStage = boom
    obs = BR.build_observation(c, None, st, "p0", blocked_edges=["B"])
    b._execute_replan(st, "p0", obs, 30.0)
    kinds = [e["kind"] for e in b.events]
    assert "agent_reroute_failed" in kinds
    assert "agent_rerouted" not in kinds


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
