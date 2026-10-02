"""Tests for ``ldyf.agents``: deterministic intent, bounded memory, no pose.

Every observation in this file is synthetic -- there is no SUMO, no Unreal, no
model and no network anywhere in the module under test, so a whole multi-stage
trip can be driven by a Python loop that plays the part of the simulator: it
reads the agent's INTENT and reports the new ``current_edge`` back. The agent
never writes a position, which is why the harness has to be the one that moves
the body.

The determinism claims are asserted as BYTE equality on the canonical
serialisations (``canonical_state_bytes`` / ``canonical_records_bytes``), never
as similarity.
"""

from __future__ import annotations

import ast
import random
import re
from dataclasses import fields, is_dataclass, replace
from pathlib import Path

import pytest

from ldyf import agents
from ldyf.agents import (
    ACTION_KINDS,
    AGENT_KINDS,
    AGENT_STATUSES,
    DECISION_REASONS,
    GOAL_KINDS,
    MEMORY_CAPACITY,
    MEMORY_KINDS,
    PLAN_STALE_REASONS,
    REPLAN_ATTEMPT_LIMIT,
    REPLAN_REASONS,
    SIGNAL_STATES,
    STEP_ACTIONS,
    AgentAction,
    AgentDefect,
    AgentError,
    AgentState,
    Goal,
    MemoryRecord,
    Neighbour,
    Observation,
    PlanStep,
    act,
    assert_replan_avoids,
    canonical_bytes,
    canonical_decision_bytes,
    canonical_perception_bytes,
    canonical_records_bytes,
    canonical_state_bytes,
    decide,
    make_agent_id,
    perceive,
    remember,
    replan,
    state_doc,
    step_agent,
    tiebreak_rng,
    tiebreak_seed,
    validate_agent_id,
)

EP = "ep:0007"
PED = "ped:000001"
PED2 = "ped:000002"
ANI = "ani:000003"
VEH = "veh:000004"

# A small one-way network: E0 -> E1 -> E2 -> E3 -> E4 -> E5 -> E6, with E0 also
# offering E3 (which cannot reach E2 or E4, so it is never a shortcut).
TRIP = (
    ("edge:E0", ("edge:E1", "edge:E3")),
    ("edge:E1", ("edge:E2",)),
    ("edge:E2", ("edge:E3",)),
    ("edge:E3", ("edge:E4",)),
    ("edge:E4", ("edge:E5",)),
    ("edge:E5", ("edge:E6",)),
    ("edge:E6", ()),
)

# A fork with two equally short alternatives, for the repair tests.
FORK = (
    ("edge:A0", ("edge:A1", "edge:A2")),
    ("edge:A1", ("edge:A3",)),
    ("edge:A2", ("edge:A3",)),
    ("edge:A3", ()),
)

# A wider fork: six equally short alternatives, used to show that two agent ids
# never collapse onto the same choices.
FAN = (
    ("edge:L0", ("edge:L1", "edge:L2", "edge:L3", "edge:L4", "edge:L5", "edge:L6")),
    ("edge:L1", ("edge:GOAL",)),
    ("edge:L2", ("edge:GOAL",)),
    ("edge:L3", ("edge:GOAL",)),
    ("edge:L4", ("edge:GOAL",)),
    ("edge:L5", ("edge:GOAL",)),
    ("edge:L6", ("edge:GOAL",)),
    ("edge:GOAL", ()),
)


def edges(successors) -> tuple[str, ...]:
    return tuple(edge for edge, _ in successors)


def obs(
    agent_id: str = PED,
    current: str = "edge:E0",
    *,
    succ=TRIP,
    reachable=None,
    blocked=(),
    signal: str = "none",
    t: float = 0.0,
    neighbours=(),
) -> Observation:
    """One synthetic look at the world. The observation is the whole interface."""
    return Observation(
        agent_id=agent_id,
        current_edge=current,
        reachable_edges=edges(succ) if reachable is None else tuple(reachable),
        blocked_edges=tuple(blocked),
        successors=succ,
        neighbours=tuple(neighbours),
        signal_state=signal,
        t_sim=t,
    )


def state(*goals, agent_id: str = PED, kind: str = "pedestrian", plan=(), memory=(), status="active"):
    return AgentState(
        agent_id=agent_id,
        kind=kind,
        goal_stack=tuple(goals),
        plan=tuple(plan),
        memory=tuple(memory),
        status=status,
    )


def trip_state(agent_id: str = PED, **kw) -> AgentState:
    """home -> errand -> work: a THREE-stage trip, oldest stage first."""
    return state(
        Goal("goal:home", "travel_to", "edge:E2", 900.0),
        Goal("goal:errand", "travel_to", "edge:E4", None),
        Goal("goal:work", "travel_to", "edge:E6", None),
        agent_id=agent_id,
        **kw,
    )


def fan_state(agent_id: str = PED) -> AgentState:
    """One goal, six equally short first hops: the tie-break's proving ground."""
    return state(Goal("goal:end", "travel_to", "edge:GOAL"), agent_id=agent_id)


def drive(state, start_edge, *, succ=TRIP, ticks=200, blocked=(), signal="none", agent_id=None):
    """Play SUMO: follow the agent's INTENT and report where the body lands."""
    edge = start_edge
    steps = []
    for tick in range(ticks):
        observation = obs(
            agent_id or state.agent_id,
            edge,
            succ=succ,
            blocked=blocked,
            signal=signal,
            t=float(tick),
        )
        step = step_agent(state, observation, tick, EP)
        steps.append(step)
        state = step.state
        if step.action.action == "traverse":
            edge = step.action.edge_id
        if state.status != "active":
            break
    return steps, edge


# --- multi-stage trips -----------------------------------------------------


def test_three_stage_trip_completes_each_stage_in_order():
    steps, edge = drive(trip_state(), "edge:E0")

    assert edge == "edge:E6", "the harness followed the intents to the final stage"
    assert steps[-1].state.status == "done"
    assert steps[-1].state.goal_stack == ()
    assert steps[-1].state.plan == ()

    completed = [r.subject_id for s in steps for r in s.records if r.kind == "goal_completed"]
    assert completed == ["goal:home", "goal:errand", "goal:work"], "stages pop in stack order"


def test_a_later_stage_is_never_planned_before_its_turn():
    steps, _edge = drive(trip_state(), "edge:E0")
    order = ["goal:home", "goal:errand", "goal:work"]
    finished: list[str] = []
    for step in steps:
        for record in step.records:
            if record.kind != "goal_completed":
                continue
            # A stage may only complete once every stage BEFORE it already has:
            # what has finished so far is always a prefix of the stack order.
            # The original assertion named the later stages literally, so it
            # fired on the very completion it was meant to allow and could not
            # pass once "goal:errand" legitimately finished.
            assert finished == order[:len(finished)], finished
            assert record.subject_id == order[len(finished)], record.subject_id
            finished.append(record.subject_id)
        if step.state.plan:
            assert step.state.plan[-1].goal_id == step.perception.active_goal_id
    assert finished == ["goal:home", "goal:errand", "goal:work"]


def test_plan_targets_the_active_stage_target():
    step = step_agent(trip_state(), obs(PED, "edge:E0"), 0, EP)
    assert step.state.plan[-1].edge_id == "edge:E2"
    assert step.state.plan[-1].goal_id == "goal:home"
    assert step.decision.reason == "goal_active"
    assert step.action.action == "traverse"


def test_goal_stack_of_depth_two_is_enough_for_a_two_stage_trip():
    steps, edge = drive(
        state(
            Goal("goal:home", "travel_to", "edge:E2"),
            Goal("goal:work", "travel_to", "edge:E6"),
        ),
        "edge:E0",
    )
    assert edge == "edge:E6"
    assert [r.subject_id for s in steps for r in s.records if r.kind == "goal_completed"] == [
        "goal:home",
        "goal:work",
    ]


# --- determinism -----------------------------------------------------------


def test_same_inputs_give_byte_identical_state_and_records():
    first, _ = drive(trip_state(), "edge:E0")
    second, _ = drive(trip_state(), "edge:E0")

    a_state = canonical_state_bytes(first[-1].state)
    b_state = canonical_state_bytes(second[-1].state)
    assert isinstance(a_state, bytes)
    assert a_state == b_state, "state bytes must be identical, not merely similar"

    a_records = canonical_records_bytes([r for s in first for r in s.records])
    b_records = canonical_records_bytes([r for s in second for r in s.records])
    assert a_records == b_records, "record sequence bytes must be identical"

    # Event ids too: they are the tick-local sequence, not a random value.
    assert [r.event_id for s in first for r in s.records] == [
        r.event_id for s in second for r in s.records
    ]


def test_identical_calls_produce_identical_decisions():
    st = trip_state()
    o = obs(PED, "edge:E0")
    a = canonical_decision_bytes(step_agent(st, o, 3, EP).decision)
    b = canonical_decision_bytes(step_agent(st, o, 3, EP).decision)
    assert a == b


def test_global_random_module_state_is_never_consumed():
    random.seed(20240903)
    before = [random.random() for _ in range(4)]

    random.seed(20240903)
    for tick in range(8):
        tiebreak_rng(PED, EP, tick).randrange(6)
        tiebreak_seed(PED, EP, tick)
    drive(fan_state(), "edge:L0", succ=FAN)
    after = [random.random() for _ in range(4)]

    assert before == after, "the seeded tie-break must not touch the global rng"


def test_tiebreak_seed_depends_only_on_id_episode_and_tick():
    assert tiebreak_seed(PED, EP, 0) == tiebreak_seed(PED, EP, 0)
    assert tiebreak_seed(PED, EP, 0) != tiebreak_seed(PED, EP, 1)
    assert tiebreak_seed(PED, EP, 0) != tiebreak_seed(PED2, EP, 0)
    assert tiebreak_seed(PED, EP, 0) != tiebreak_seed(PED, "ep:0008", 0)


def test_two_agents_with_the_same_episode_and_tick_do_not_collapse():
    """The seed carries the agent id, so ids are not interchangeable.

    Both agents see the same world, in the same episode, at the same ticks, so
    the only thing that differs is the id -- the rest of the seed. With six
    equally short first hops, identical choices at every one of 24 ticks would
    mean the id was being ignored.
    """
    same = 0
    for tick in range(24):
        a = step_agent(fan_state(PED), obs(PED, "edge:L0", succ=FAN), tick, EP)
        b = step_agent(fan_state(PED2), obs(PED2, "edge:L0", succ=FAN), tick, EP)
        assert tiebreak_seed(PED, EP, tick) != tiebreak_seed(PED2, EP, tick)
        assert a.decision.edge_id and b.decision.edge_id
        if a.decision.edge_id == b.decision.edge_id:
            same += 1
    assert same < 24, f"two ids made identical choices at all 24 ticks (same={same})"


def test_same_agent_id_repeated_calls_stay_identical():
    o = obs(PED, "edge:L0", succ=FAN)
    assert canonical_decision_bytes(step_agent(fan_state(), o, 5, EP).decision) == (
        canonical_decision_bytes(step_agent(fan_state(), o, 5, EP).decision)
    )


# --- perception ------------------------------------------------------------


def test_perception_depends_only_on_state_and_observation():
    st = trip_state()
    o = obs(PED, "edge:E0")

    first = canonical_perception_bytes(perceive(st, o))
    assert first == canonical_perception_bytes(perceive(st, o))

    # Memory is not part of perception: a state differing only in memory sees
    # exactly the same world.
    noisy = replace(
        st,
        memory=(
            MemoryRecord(f"{PED}:{EP}:000000:00", "intent_issued", 0.0, "edge:E1", 0.0),
        ),
    )
    assert canonical_perception_bytes(perceive(noisy, o)) == first

    # The observation IS the world: closing an edge changes what is perceived.
    blocked = perceive(st, obs(PED, "edge:E0", blocked=("edge:E1",)))
    assert canonical_perception_bytes(blocked) != first
    assert blocked.open_edges == ("edge:E0", "edge:E2", "edge:E3", "edge:E4", "edge:E5", "edge:E6")


def test_observation_for_another_agent_is_refused():
    with pytest.raises(AgentError):
        perceive(trip_state(PED), obs(PED2, "edge:E0"))


def test_neighbours_outside_the_perception_radius_are_dropped():
    near = Neighbour(VEH, "vehicle_occupant", "edge:E1", 3.0)
    far = Neighbour(PED2, "pedestrian", "edge:E1", agents.PERCEPTION_RADIUS_M + 1.0)
    percept = perceive(trip_state(), obs(PED, "edge:E0", neighbours=(far, near)))
    assert [n.agent_id for n in percept.neighbours] == [VEH]


def test_perception_reports_a_stale_plan_as_stale_not_as_a_world_failure():
    wrong_stage = state(
        Goal("goal:home", "travel_to", "edge:E2"),
        plan=(PlanStep("goal:errand", "edge:E1", "traverse", 5.0),),
    )
    percept = perceive(wrong_stage, obs(PED, "edge:E0"))
    assert percept.stale_reason == "plan_stage_mismatch"
    assert percept.invalidation is None
    assert percept.plan_valid is False


# --- replanning ------------------------------------------------------------


def test_a_plan_step_on_a_blocked_edge_is_repaired_around_it():
    plan = (
        PlanStep("goal:end", "edge:A1", "traverse", 5.0),
        PlanStep("goal:end", "edge:A3", "traverse", 10.0),
    )
    st = state(Goal("goal:end", "travel_to", "edge:A3"), plan=plan)
    o = obs(PED, "edge:A0", succ=FORK, blocked=("edge:A1",))

    percept = perceive(st, o)
    assert percept.blocked_step_edge == "edge:A1"
    assert percept.invalidation == "edge_blocked"

    result = replan(st, percept, 0, EP)
    assert result.reason == "edge_blocked"
    assert result.state.status == "active"
    assert [s.edge_id for s in result.state.plan] == ["edge:A2", "edge:A3"]
    assert all(s.edge_id != "edge:A1" for s in result.state.plan), "the blocked edge is avoided"

    assert [r.kind for r in result.records] == ["blocked_edge_seen", "agent_replanned"]
    assert result.records[0].subject_id == "edge:A1"
    assert result.records[1].value == "reason:edge_blocked"


def test_blocked_edge_repair_reaches_the_intent():
    plan = (
        PlanStep("goal:end", "edge:A1", "traverse", 5.0),
        PlanStep("goal:end", "edge:A3", "traverse", 10.0),
    )
    st = state(Goal("goal:end", "travel_to", "edge:A3"), plan=plan)
    step = step_agent(st, obs(PED, "edge:A0", succ=FORK, blocked=("edge:A1",)), 0, EP)
    assert step.replanned is True
    assert step.replan_reason == "edge_blocked"
    assert step.action.action == "traverse"
    assert step.action.edge_id == "edge:A2"
    assert [s.edge_id for s in step.state.plan] == ["edge:A2", "edge:A3"]


def test_an_unavoidable_block_sets_status_blocked():
    step = step_agent(trip_state(), obs(PED, "edge:E0", blocked=("edge:E1",)), 0, EP)
    assert step.state.status == "blocked"
    assert step.state.plan == ()
    assert step.action.action == "hold"
    assert any(
        r.kind == "agent_replanned" and r.value == "reason:goal_unreachable" for r in step.records
    )
    assert any(r.kind == "status_changed" and r.value == "status:blocked" for r in step.records)


def test_replan_without_a_reason_is_refused():
    st = trip_state()
    percept = perceive(st, obs(PED, "edge:E0"))
    assert percept.invalidation is None
    with pytest.raises(AgentError):
        replan(st, percept, 0, EP)
    with pytest.raises(AgentError):
        replan(st, percept, 0, EP, reason="because_i_said_so")


def test_replan_loops_terminate_when_the_same_blocked_edge_is_offered_forever():
    """The adversarial replan loop: it must settle, not spin."""
    st = trip_state()
    steps = []
    for tick in range(12):
        step = step_agent(st, obs(PED, "edge:E0", blocked=("edge:E1",), t=float(tick)), tick, EP)
        steps.append(step)
        st = step.state

    assert st.status == "blocked"
    assert all(s.attempts <= REPLAN_ATTEMPT_LIMIT for s in steps)
    assert steps[0].attempts == 1, "one repair attempt was enough to know there is no way through"

    records = [r for s in steps for r in s.records]
    assert [r.kind for r in records].count("agent_replanned") == 1
    assert len(records) <= 4, "a block is reported once, not once per tick"

    # A blocked agent holds, and a hold is not an intent: it emits nothing.
    assert all(s.action.action == "hold" for s in steps[1:])
    assert all(s.records == () for s in steps[1:])


def test_replan_attempt_bound_is_enforced(monkeypatch):
    """Even a planner that never improves is stopped at the bound."""
    st = state(Goal("goal:home", "travel_to", "edge:E2"))
    stuck = (
        PlanStep("goal:home", "edge:E1", "traverse", 5.0),
        PlanStep("goal:home", "edge:E2", "traverse", 10.0),
    )

    def stubborn(state, perception, tick, episode_id, *, reason=None):
        return agents.ReplanResult(
            state=replace(state, plan=stuck, status="active"),
            reason=reason or "edge_blocked",
            resolved=False,
            records=(),
        )

    monkeypatch.setattr(agents, "replan", stubborn)
    step = step_agent(st, obs(PED, "edge:E0", blocked=("edge:E1",)), 0, EP)

    assert step.attempts == REPLAN_ATTEMPT_LIMIT
    assert step.state.status == "blocked"


def test_returning_the_same_invalid_plan_is_a_defect(monkeypatch):
    plan = (
        PlanStep("goal:home", "edge:E1", "traverse", 5.0),
        PlanStep("goal:home", "edge:E2", "traverse", 10.0),
    )
    st = state(Goal("goal:home", "travel_to", "edge:E2"), plan=plan)
    o = obs(PED, "edge:E0", blocked=("edge:E1",))
    percept = perceive(st, o)
    assert percept.invalidation == "edge_blocked"

    # A planner that hands back exactly the invalid plan it was given.
    monkeypatch.setattr(agents, "_plan_route", lambda *a, **k: plan)
    with pytest.raises(AgentDefect):
        replan(st, percept, 0, EP)

    # ... and the guard itself, called directly.
    with pytest.raises(AgentDefect):
        assert_replan_avoids(plan, plan, ("edge:E1",))
    assert_replan_avoids(plan, plan, ("edge:E9",))  # nothing blocked -> no defect
    with pytest.raises(AgentDefect):
        assert_replan_avoids(plan, plan, (), forbidden=("edge:E1",))


def test_a_blocked_agent_resumes_when_the_world_reopens():
    first = step_agent(trip_state(), obs(PED, "edge:E0", blocked=("edge:E1",)), 0, EP)
    assert first.state.status == "blocked"

    second = step_agent(first.state, obs(PED, "edge:E0", t=1.0), 1, EP)
    assert second.state.status == "active"
    assert second.replan_reason == "edge_cleared"
    assert second.action.action == "traverse"
    assert any(r.value == "reason:edge_cleared" for r in second.records)
    assert any(r.value == "status:active" for r in second.records)


def test_goal_unreachable_in_the_observation_blocks_and_then_stays_quiet():
    missing = "edge:NOPE"
    st = state(Goal("goal:home", "travel_to", missing))
    o = obs(PED, "edge:E0")

    percept = perceive(st, o)
    assert missing not in percept.reachable_edges
    assert percept.goal_reachable is False
    assert percept.invalidation == "goal_unreachable"

    step = step_agent(st, o, 0, EP)
    assert step.state.status == "blocked"
    assert any(r.value == "reason:goal_unreachable" for r in step.records)

    again = step_agent(step.state, o, 1, EP)
    assert again.records == ()
    assert again.state.status == "blocked"


def test_deadline_passed_blocks_a_trip_stage():
    st = state(Goal("goal:home", "travel_to", "edge:E2", 5.0))
    o = obs(PED, "edge:E0", t=6.0)
    percept = perceive(st, o)
    assert percept.deadline_passed is True
    assert percept.invalidation == "deadline_passed"

    step = step_agent(st, o, 0, EP)
    assert step.replan_reason == "deadline_passed"
    assert step.state.status == "blocked"
    assert any(r.value == "reason:deadline_passed" for r in step.records)


def test_deadline_passed_ends_a_bounded_wait_and_the_trip_continues():
    st = state(
        Goal("goal:cross", "wait_until", "signal:green", 5.0),
        Goal("goal:work", "travel_to", "edge:E6", None),
    )
    o = obs(PED, "edge:E0", t=6.0)

    # replan answers a deadline on a wait by completing the stage ...
    direct = replan(st, perceive(st, o), 0, EP)
    assert direct.reason == "deadline_passed"
    assert direct.state.status == "active"
    assert [g.goal_id for g in direct.state.goal_stack] == ["goal:work"]

    # ... and a whole tick does the same thing, then plans the next stage.
    step = step_agent(st, o, 0, EP)
    assert [r.subject_id for r in step.records if r.kind == "goal_completed"] == ["goal:cross"]
    assert step.state.status == "active"
    assert step.state.plan[-1].edge_id == "edge:E6"


def test_a_wait_stage_waits_for_its_signal_and_then_lets_the_trip_continue():
    st = state(
        Goal("goal:cross", "wait_until", "signal:green", 100.0),
        Goal("goal:work", "travel_to", "edge:E6", None),
    )
    waiting = step_agent(st, obs(PED, "edge:E0", signal="red"), 0, EP)
    assert waiting.state.status == "active"
    assert waiting.action.action == "wait"
    assert waiting.decision.edge_id == "edge:E0", "a wait names the edge it stands on"
    assert [s.action for s in waiting.state.plan] == ["wait"]

    resumed = step_agent(waiting.state, obs(PED, "edge:E0", signal="green", t=1.0), 1, EP)
    assert [r.subject_id for r in resumed.records if r.kind == "goal_completed"] == ["goal:cross"]
    assert resumed.decision.reason == "goal_active"
    assert resumed.action.action == "traverse"


def test_an_avoid_goal_routes_the_plan_around_its_edge():
    st = state(
        Goal("goal:end", "travel_to", "edge:A3"),
        Goal("goal:quiet", "avoid", "edge:A1", 100.0),
    )
    step = step_agent(st, obs(PED, "edge:A0", succ=FORK), 0, EP)
    assert step.perception.avoided_edges == ("edge:A1",)
    assert [s.edge_id for s in step.state.plan] == ["edge:A2", "edge:A3"]
    assert step.state.status == "active"


def test_an_avoid_goal_that_squeezes_out_the_route_blocks_rather_than_loops():
    # From E2 the only successor is E3, and the agent itself forbids E3.
    st = state(
        Goal("goal:work", "travel_to", "edge:E6"),
        Goal("goal:quiet", "avoid", "edge:E3", 100.0),
    )
    step = step_agent(st, obs(PED, "edge:E2"), 0, EP)
    assert step.perception.goal_reachable is True, "the world still offers a route"
    assert step.state.status == "blocked", "but not one the agent's own rule allows"
    assert step.state.plan == ()
    assert any(r.value == "status:blocked" for r in step.records)

    quiet = step_agent(step.state, obs(PED, "edge:E2", t=1.0), 1, EP)
    assert quiet.records == ()


def test_an_expired_avoid_constraint_leaves_the_stack():
    st = state(
        Goal("goal:work", "travel_to", "edge:E6"),
        Goal("goal:quiet", "avoid", "edge:E3", 2.0),
    )
    released = step_agent(st, obs(PED, "edge:E0", t=3.0), 0, EP)
    assert [g.goal_id for g in released.state.goal_stack] == ["goal:work"]
    assert [r.subject_id for r in released.records if r.kind == "goal_completed"] == ["goal:quiet"]
    assert "edge:E3" in [s.edge_id for s in released.state.plan]


# --- deciding --------------------------------------------------------------


def test_red_signal_stops_the_agent_before_the_next_edge():
    step = step_agent(trip_state(), obs(PED, "edge:E0", signal="red"), 0, EP)
    assert step.decision.reason == "signal_stop"
    assert step.action.action == "wait"
    assert step.action.edge_id == "edge:E0", "a wait names the edge it stands on"
    assert step.perception.current_edge == "edge:E0"


def test_an_animal_yields_to_a_vehicle_but_a_pedestrian_does_not_yield_to_a_pedestrian():
    vehicle = Neighbour(VEH, "vehicle_occupant", "edge:E1", 3.0)
    animal = step_agent(
        state(Goal("goal:home", "travel_to", "edge:E2"), agent_id=ANI, kind="animal"),
        obs(ANI, "edge:E0", neighbours=(vehicle,)),
        0,
        EP,
    )
    assert animal.decision.reason == "yield_neighbour"
    assert animal.action.action == "wait"

    pedestrian = Neighbour(PED2, "pedestrian", "edge:E1", 2.0)
    equal_rank = step_agent(trip_state(), obs(PED, "edge:E0", neighbours=(pedestrian,)), 0, EP)
    assert equal_rank.decision.reason == "goal_active"
    assert equal_rank.action.action == "traverse"


def test_decide_holds_when_the_agent_is_blocked_or_done():
    blocked_state = state(Goal("goal:home", "travel_to", "edge:E2"), status="blocked")
    blocked = decide(blocked_state, perceive(blocked_state, obs(PED, "edge:E0")), 0, EP)
    assert (blocked.action, blocked.reason, blocked.edge_id) == ("hold", "blocked", "")

    done_state = state(status="done")
    done = decide(done_state, perceive(done_state, obs(PED, "edge:E0")), 0, EP)
    assert (done.action, done.reason) == ("hold", "no_goals")


def test_empty_goal_stack_finishes_and_then_stays_quiet():
    st = state()
    o = obs(PED, "edge:E0")
    percept = perceive(st, o)
    assert percept.active_goal_id == ""
    assert percept.plan_valid is True

    step = step_agent(st, o, 0, EP)
    assert step.state.status == "done"
    assert step.action.action == "hold"
    assert [r.kind for r in step.records] == ["status_changed"]
    assert step.records[0].value == "status:done"

    again = step_agent(step.state, o, 1, EP)
    assert again.records == ()
    assert again.state.status == "done"


def test_act_refuses_a_decision_for_another_agent():
    st = trip_state()
    step = step_agent(st, obs(PED, "edge:E0"), 0, EP)
    other = replace(step.decision, agent_id=PED2)
    with pytest.raises(AgentError):
        act(st, other)


# --- bounded structured memory --------------------------------------------


def test_memory_capacity_evicts_the_oldest_first():
    st = state(Goal("goal:home", "travel_to", "edge:E2"))
    event_ids = []
    for index in range(MEMORY_CAPACITY * 3):
        record = MemoryRecord(
            event_id=f"{PED}:{EP}:{index:06d}:intent_issued",
            kind="intent_issued",
            t_sim=float(index),
            subject_id="edge:E1",
            value=float(index),
        )
        event_ids.append(record.event_id)
        st = remember(st, record)

    assert len(st.memory) == MEMORY_CAPACITY
    assert [r.event_id for r in st.memory] == event_ids[-MEMORY_CAPACITY:]
    assert st.memory[0].event_id == event_ids[-MEMORY_CAPACITY], "the oldest survivors are kept"
    assert event_ids[0] not in {r.event_id for r in st.memory}


def test_memory_overflow_well_past_capacity():
    st = state()
    for index in range(500):
        st = remember(
            st,
            MemoryRecord(
                event_id=f"{PED}:{EP}:{index:06d}:intent_issued",
                kind="intent_issued",
                t_sim=float(index),
                subject_id="edge:E1",
                value=float(index),
            ),
        )
        assert len(st.memory) <= MEMORY_CAPACITY
    assert len(st.memory) == MEMORY_CAPACITY
    values = [r.value for r in st.memory]
    assert values == sorted(values), "order is preserved by eviction"
    assert values[0] == 500 - MEMORY_CAPACITY


def test_memory_is_capped_through_a_whole_trip():
    st = trip_state()
    edge = "edge:E0"
    for tick in range(60):
        step = step_agent(st, obs(PED, edge, t=float(tick)), tick, EP)
        st = step.state
        assert len(st.memory) <= MEMORY_CAPACITY
        if step.action.action == "traverse":
            edge = step.action.edge_id
        if st.status != "active":
            break


def test_constructing_an_agent_with_too_much_memory_is_refused():
    records = tuple(
        MemoryRecord(f"{PED}:{EP}:{i:06d}:intent_issued", "intent_issued", float(i), "edge:E1", 0.0)
        for i in range(MEMORY_CAPACITY + 1)
    )
    with pytest.raises(AgentError):
        state(memory=records)


def test_memory_record_is_exactly_five_structured_fields():
    assert {f.name for f in fields(MemoryRecord)} == {
        "event_id",
        "kind",
        "t_sim",
        "subject_id",
        "value",
    }
    numeric = MemoryRecord(f"{PED}:{EP}:000000:00", "agent_planned", 0.0, "goal:home", 2)
    assert isinstance(numeric.value, float), "numbers normalise to float, so 3 and 3.0 cannot differ"
    assert numeric.value == 2.0

    for bad in ("the road ahead was closed", "why I turned left", "free text", ""):
        with pytest.raises(AgentError):
            MemoryRecord(f"{PED}:{EP}:000000:00", "intent_issued", 0.0, "edge:E1", bad)
    with pytest.raises(AgentError):
        MemoryRecord(f"{PED}:{EP}:000000:00", "intent_issued", 0.0, "edge:E1", None)
    with pytest.raises(AgentError):
        MemoryRecord(f"{PED}:{EP}:000000:00", "thought", 0.0, "edge:E1", 0.0)


def test_no_dataclass_field_in_the_module_smells_like_free_text():
    forbidden = re.compile(r"(text|prompt|note|message|description|summary|blurb)")
    for name, obj in vars(agents).items():
        if is_dataclass(obj) and isinstance(obj, type):
            for field in fields(obj):
                assert not forbidden.search(field.name), f"{name}.{field.name}"


def test_reason_codes_are_closed_sets():
    assert REPLAN_REASONS == ("deadline_passed", "edge_blocked", "edge_cleared", "goal_unreachable")
    assert PLAN_STALE_REASONS == (
        "avoid_goal",
        "no_plan",
        "plan_position_mismatch",
        "plan_stage_mismatch",
    )
    for name, members in (
        ("AGENT_KINDS", AGENT_KINDS),
        ("AGENT_STATUSES", AGENT_STATUSES),
        ("GOAL_KINDS", GOAL_KINDS),
        ("STEP_ACTIONS", STEP_ACTIONS),
        ("ACTION_KINDS", ACTION_KINDS),
        ("SIGNAL_STATES", SIGNAL_STATES),
        ("MEMORY_KINDS", MEMORY_KINDS),
        ("DECISION_REASONS", DECISION_REASONS),
    ):
        assert isinstance(members, tuple) and members
        assert len(set(members)) == len(members), f"{name} has duplicates"

    # Every code actually emitted by a whole trip is inside its closed set.
    steps, _ = drive(trip_state(), "edge:E0")
    for step in steps:
        assert step.decision.reason in DECISION_REASONS
        if step.replan_reason is not None:
            assert step.replan_reason in REPLAN_REASONS
        for record in step.records:
            assert record.kind in MEMORY_KINDS
        assert step.perception.invalidation in REPLAN_REASONS + (None,)
        assert step.perception.stale_reason in PLAN_STALE_REASONS + (None,)


# --- adversarial: ids, closed sets, observation gaps -----------------------


@pytest.mark.parametrize(
    "bad",
    [
        "ped:1",
        "ped:00001",
        "pedestrian:000001",
        "PED:000001",
        "ped:000001 ",
        "",
        "robot:000001",
        "ped:00000a",
        "ped:0000001",
    ],
)
def test_invalid_agent_id_format_is_refused(bad):
    with pytest.raises(AgentError):
        validate_agent_id(bad)
    with pytest.raises(AgentError):
        AgentState(agent_id=bad, kind="pedestrian")
    with pytest.raises(AgentError):
        Observation(agent_id=bad, current_edge="edge:E0")
    with pytest.raises(AgentError):
        tiebreak_seed(bad, EP, 0)


def test_agent_ids_are_produced_by_one_validated_factory():
    assert make_agent_id("pedestrian", 1) == PED
    assert make_agent_id("vehicle_occupant", 4) == VEH
    assert make_agent_id("animal", 3) == ANI
    validate_agent_id(make_agent_id("pedestrian", 999999))
    for bad_call in (
        ("robot", 1),
        ("pedestrian", -1),
        ("pedestrian", 10 ** 6),
        ("pedestrian", "1"),
        ("pedestrian", True),
    ):
        with pytest.raises(AgentError):
            make_agent_id(*bad_call)


def test_closed_sets_are_enforced_at_construction():
    with pytest.raises(AgentError):
        Goal("goal:x", "fly_to", "edge:E1")
    with pytest.raises(AgentError):
        Goal("goal:x", "wait_until", "edge:E1")  # a wait target is a signal token
    with pytest.raises(AgentError):
        Goal("goal:x", "travel_to", "edge:E1", -1.0)
    with pytest.raises(AgentError):
        PlanStep("goal:x", "edge:E1", "sprint", 1.0)
    with pytest.raises(AgentError):
        Neighbour(PED2, "robot", "edge:E1", 1.0)
    with pytest.raises(AgentError):
        AgentState(agent_id=PED, kind="robot")
    with pytest.raises(AgentError):
        AgentState(agent_id=PED, kind="pedestrian", status="sleeping")
    with pytest.raises(AgentError):
        AgentState(
            agent_id=PED,
            kind="pedestrian",
            goal_stack=(
                Goal("goal:x", "travel_to", "edge:E1"),
                Goal("goal:x", "travel_to", "edge:E2"),
            ),
        )
    with pytest.raises(AgentError):
        Observation(agent_id=PED, current_edge="edge:E0", signal_state="purple")
    with pytest.raises(AgentError):
        Observation(agent_id=PED, current_edge="edge:E0", t_sim=-1.0)
    with pytest.raises(AgentError):
        Observation(agent_id=PED, current_edge="not an edge")


def test_a_target_that_is_absent_from_the_observation_blocks():
    missing = "edge:NOPE"
    st = state(Goal("goal:home", "travel_to", missing))
    step = step_agent(st, obs(PED, "edge:E0"), 0, EP)
    assert step.state.status == "blocked"
    assert step.perception.goal_reachable is False


# --- no model, no network, no clock, no pose ------------------------------


def test_module_is_stdlib_only_and_imports_no_model_network_or_clock():
    source = Path(agents.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= {
        "__future__",
        "dataclasses",
        "hashlib",
        "json",
        "math",
        "random",
        "re",
        "typing",
    }
    forbidden = {
        "unreal",
        "time",
        "datetime",
        "uuid",
        "secrets",
        "socket",
        "subprocess",
        "urllib",
        "http",
        "requests",
        "openai",
        "os",
        "sys",
        "pathlib",
        "logging",
    }
    assert not (imported & forbidden), f"forbidden imports: {sorted(imported & forbidden)}"


def test_the_intent_carries_no_position():
    step = step_agent(trip_state(), obs(PED, "edge:E0"), 0, EP)
    doc = agents.action_doc(step.action)
    assert set(doc) == {"agent_id", "tick", "episode_id", "action", "edge_id", "goal_id", "t_sim"}
    for forbidden in ("x", "y", "z", "yaw", "pose", "position", "speed", "location"):
        assert forbidden not in doc
        assert forbidden not in state_doc(step.state)
    assert {f.name for f in fields(AgentAction)} == set(doc)
    assert "unreal" not in vars(agents), "no unreal binding may exist in this module"


def test_canonical_encoding_is_the_pinned_form():
    st = trip_state(plan=(PlanStep("goal:home", "edge:E1", "traverse", 5.0),))
    assert canonical_bytes(state_doc(st)) == canonical_state_bytes(st)

    text = canonical_state_bytes(st).decode("utf-8")
    assert " " not in text, "separators are pinned to (, :) so no space survives"
    assert canonical_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'

    with pytest.raises(ValueError):
        canonical_bytes({"nan": float("nan")})
