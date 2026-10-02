"""Deterministic agents: INTENT, bounded memory, no pose, no model, no clock.

What lives here
---------------
SUMO moves bodies. An agent decides *intent* -- which edge it wants to enter
next, or that it wants to hold still -- and never writes a pose. There is no
model inference anywhere in this module: no model call per agent, per tick or
anywhere else, no network, no file reads, and no ``unreal`` import. Everything
an agent knows about the world arrives in one ``Observation`` argument, so a
whole episode is testable with synthetic observations and no SUMO.

The pipeline, and the function that owns each stage::

    state -> perceive -> decide -> act -> (SUMO executes) -> replan -> remember

``perceive``
    Reads ``state`` and ``observation`` only. Reports the world (reachable,
    blocked and self-avoided edges, the current edge, the neighbours inside
    ``PERCEPTION_RADIUS_M``, the signal state) plus whether the plan already in
    ``state`` still fits that world, and why it does not.
``decide``
    Chooses the intent for this tick and the plan the agent should now carry.
``act``
    Turns a decision into an ``AgentAction`` -- an intent SUMO can execute, with
    no position in it -- and writes the memory that intent implies.
``replan``
    Repairs a plan perception has marked invalid, carrying a REASON CODE from
    the closed set ``REPLAN_REASONS``, or sets ``status`` to ``blocked``.
``remember``
    Appends one ``MemoryRecord`` and evicts the oldest past ``MEMORY_CAPACITY``,
    so an agent's memory is BOUNDED and cannot grow with episode length.
``step_agent``
    Composes one tick and issues that tick's record sequence.

The laws this module keeps
--------------------------
1. **Deterministic.** Every observable is a pure function of the inputs. The
   only tie-break is a seeded ``random.Random`` derived from
   ``agent_id`` + ``episode_id`` + ``str(tick)`` and nothing else: not the wall
   clock, not ``id()``, not dict or set iteration order (every iteration here is
   over a sorted tuple). The global ``random`` module state is never read or
   consumed.
2. **Intent, never pose.** ``AgentAction`` names an ``edge_id`` and an action
   kind. It has no x/y/z/yaw/speed field, and neither does any state: where the
   body actually is arrives in the next ``Observation``.
3. **Bounded, structured memory.** ``MemoryRecord`` is exactly
   ``{event_id, kind, t_sim, subject_id, value}``. ``kind`` comes from the
   closed set ``MEMORY_KINDS``; ``value`` is a number or a namespaced ID -- there
   is no free-text field and nothing a language model could fill in.
4. **Multi-stage trips.** ``goal_stack[0]`` is the current stage and the stack
   is consumed front to back: ``home -> errand -> work`` is three ``travel_to``
   goals, and each pops when it completes (a ``goal_completed`` record, in
   order). An ``avoid`` goal is a standing constraint, not a stage: it filters
   every plan while it sits in the stack and leaves the stack when its deadline
   passes.
5. **Terminal states exist.** A replan is bounded by
   ``REPLAN_ATTEMPT_LIMIT``; an agent that cannot be replanned becomes
   ``blocked`` and then emits nothing at all, so a permanently blocked edge can
   never make it spin or churn its own memory. Returning a plan that still
   enters a blocked element is a DEFECT and raises ``AgentDefect``.

Canonical serialisation
-----------------------
``canonical_bytes`` is ``json.dumps(doc, sort_keys=True,
separators=(",", ":"), ensure_ascii=True, allow_nan=False)`` -- the same pin
used by ``ldyf.world_state``. Every float in a record has already been rounded
to 6 decimals by ``_f6`` (which also kills ``-0.0``) and every numeric memory
value is normalised to ``float``, so ``3`` and ``3.0`` cannot serialise
differently. Two runs over the same observations therefore produce
byte-identical state and record sequences.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from dataclasses import dataclass, replace
from typing import Any, Iterable, Sequence

AGENT_STATE_VERSION = "agent_state_v1"

# --- closed sets ------------------------------------------------------------
# Every one of these is a hard whitelist enforced in __post_init__; there is no
# code path that writes a member from outside its set.

AGENT_KINDS = ("animal", "pedestrian", "vehicle_occupant")
AGENT_STATUSES = ("active", "blocked", "done")
GOAL_KINDS = ("avoid", "travel_to", "wait_until")
STEP_ACTIONS = ("traverse", "wait")
ACTION_KINDS = ("hold", "traverse", "wait")
SIGNAL_STATES = ("green", "none", "red", "yellow")

#: Memory is structured, never free text. ``goal_completed`` covers any goal
#: that leaves the stack (a stage finished, or an expired constraint released).
MEMORY_KINDS = (
    "agent_planned",
    "agent_replanned",
    "blocked_edge_seen",
    "goal_completed",
    "intent_issued",
    "status_changed",
)

#: Why a plan was invalid and had to be repaired. ``edge_cleared`` is the
#: reverse direction: a blocked agent retrying after the world reopened.
REPLAN_REASONS = ("deadline_passed", "edge_blocked", "edge_cleared", "goal_unreachable")

#: Why the plan the agent carries does not fit the current stage or position.
#: These are *self* observations, not world failures, so they are repaired
#: silently by ``decide`` rather than announced as an ``agent_replanned`` event.
PLAN_STALE_REASONS = ("avoid_goal", "no_plan", "plan_position_mismatch", "plan_stage_mismatch")

DECISION_REASONS = (
    "blocked",
    "goal_active",
    "goal_unreachable",
    "no_goals",
    "signal_stop",
    "yield_neighbour",
)

#: Only these three can be a ``wait_until`` target: a token from SIGNAL_STATES
#: in the ID namespace, so a wait target is a name and not a sentence.
WAIT_SIGNAL_TARGETS = ("signal:green", "signal:red", "signal:yellow")

#: Who yields to whom. An animal yields to a pedestrian; a pedestrian yields to
#: the occupant of a vehicle; nothing yields to an animal.
KIND_PRIORITY = {"animal": 0, "pedestrian": 1, "vehicle_occupant": 2}
KIND_TAG = {"animal": "ani", "pedestrian": "ped", "vehicle_occupant": "veh"}

#: How many records one agent may hold. Chosen so an agent's whole memory
#: serialises in a few kilobytes and still covers the tail of a multi-stage
#: trip; oldest records are evicted first by ``remember``.
MEMORY_CAPACITY = 32

#: Neighbours further away than this are not in the observation's report.
PERCEPTION_RADIUS_M = 12.0
#: A lower-priority agent waits before entering an edge another agent occupies
#: inside this radius.
YIELD_RADIUS_M = 6.0
#: Nominal per-edge traversal estimate, used only to order plan steps. SUMO owns
#: real time; this number is never a claim about the world.
SECONDS_PER_EDGE = 5.0
#: A tick may replan at most this many times before the agent is declared
#: ``blocked``. This is the bound that makes a replan loop terminate.
REPLAN_ATTEMPT_LIMIT = 3

#: Namespaced IDs only: ``tag:payload``, lowercase tag, no whitespace anywhere.
#: This is what makes "value is an ID" a checkable claim rather than a promise.
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,7}:[A-Za-z0-9_.:-]{1,63}$")
#: Agent ids are stricter still, and ``make_agent_id`` is the only producer.
_AGENT_ID_RE = re.compile(r"^(?:ani|ped|veh):[0-9]{6}$")


class AgentError(RuntimeError):
    """Raised when an agent input or a contract is violated."""


class AgentDefect(AgentError):
    """Raised when the module itself would break one of its laws.

    The measured case: a replan that hands back a plan still entering a blocked
    edge -- i.e. the repair did nothing. That is never downgraded to a warning.
    """


# --- small deterministic helpers -------------------------------------------


def _f6(value: float) -> float:
    """Round to 6 decimals (byte determinism) and kill ``-0.0``."""
    return round(float(value), 6) + 0.0


def _require_number(value: Any, what: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AgentError(f"{what} must be a number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise AgentError(f"{what} must be finite, got {value!r}")
    if minimum is not None and number < minimum:
        raise AgentError(f"{what} must be >= {minimum}, got {value!r}")
    return _f6(number)


def validate_token_id(value: Any, *, what: str) -> str:
    """A namespaced ID (``edge:E1``, ``reason:edge_blocked``) or raise.

    Any string that is not of that shape is refused, which is how free text is
    kept out of the structured fields.
    """
    if not isinstance(value, str):
        raise AgentError(f"{what} must be a string ID, got {type(value).__name__}")
    if not _ID_RE.match(value):
        raise AgentError(
            f"{what} {value!r} is not a namespaced ID (tag:payload, no whitespace, "
            f"payload at most 63 characters)"
        )
    return value


def validate_agent_id(agent_id: Any) -> str:
    """Agent ids are ``ani|ped|veh`` + 6 digits, e.g. ``ped:000001``."""
    if not isinstance(agent_id, str):
        raise AgentError(f"agent_id must be a string, got {type(agent_id).__name__}")
    if not _AGENT_ID_RE.match(agent_id):
        raise AgentError(
            f"agent_id {agent_id!r} is not of the form (ani|ped|veh):NNNNNN -- "
            f"use make_agent_id(kind, index)"
        )
    return agent_id


def make_agent_id(kind: str, index: int) -> str:
    """The only producer of an agent id: a stable, kind-tagged index."""
    if kind not in AGENT_KINDS:
        raise AgentError(f"kind {kind!r} not in {AGENT_KINDS}")
    if isinstance(index, bool) or not isinstance(index, int):
        raise AgentError(f"agent index must be an int, got {type(index).__name__}")
    if not 0 <= index < 10 ** 6:
        raise AgentError(f"agent index must be in [0, 1000000), got {index}")
    return f"{KIND_TAG[kind]}:{index:06d}"


def _id_tuple(values: Iterable[str], what: str) -> tuple[str, ...]:
    """Sorted, de-duplicated tuple of IDs -- iteration order never leaks."""
    seen = {validate_token_id(v, what=what) for v in values}
    return tuple(sorted(seen))


def _successor_pairs(pairs: Iterable[Any]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Normalise ``((edge, (successors...)), ...)`` into a sorted pair tuple."""
    table: dict[str, set[str]] = {}
    for pair in pairs:
        try:
            edge, succs = pair
        except (TypeError, ValueError):
            raise AgentError(f"successor entry {pair!r} is not an (edge, successors) pair")
        edge = validate_token_id(edge, what="successor edge")
        table.setdefault(edge, set())
        for succ in succs:
            table[edge].add(validate_token_id(succ, what=f"successor of {edge}"))
    return tuple((edge, tuple(sorted(table[edge]))) for edge in sorted(table))


# --- data model -------------------------------------------------------------


@dataclass(frozen=True)
class Goal:
    """One stage of a trip, a bounded wait, or a standing constraint.

    ``travel_to``  ``target`` is an edge id; the stage completes when the agent
                   is standing on that edge.
    ``wait_until`` ``target`` is a signal token (``signal:green``); the stage
                   completes when the observation reports it, or when
                   ``deadline_s`` passes, so a wait can never hang forever.
    ``avoid``      ``target`` is an edge id the agent's own plans must not
                   enter while this goal is in the stack. It is not a stage.
    """

    goal_id: str
    kind: str
    target: str
    deadline_s: float | None = None

    def __post_init__(self) -> None:
        validate_token_id(self.goal_id, what="goal_id")
        if self.kind not in GOAL_KINDS:
            raise AgentError(f"goal kind {self.kind!r} not in {GOAL_KINDS}")
        validate_token_id(self.target, what="goal target")
        if self.kind == "wait_until" and self.target not in WAIT_SIGNAL_TARGETS:
            raise AgentError(
                f"wait_until target must be one of {WAIT_SIGNAL_TARGETS}, got {self.target!r}"
            )
        if self.deadline_s is not None:
            object.__setattr__(
                self, "deadline_s", _require_number(self.deadline_s, "deadline_s", minimum=0.0)
            )

    def as_doc(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "kind": self.kind,
            "target": self.target,
            "deadline_s": self.deadline_s,
        }


@dataclass(frozen=True)
class PlanStep:
    """One edge the agent intends to enter (``traverse``) or to wait on."""

    goal_id: str
    edge_id: str
    action: str
    eta_s: float

    def __post_init__(self) -> None:
        validate_token_id(self.goal_id, what="plan step goal_id")
        validate_token_id(self.edge_id, what="plan step edge_id")
        if self.action not in STEP_ACTIONS:
            raise AgentError(f"plan step action {self.action!r} not in {STEP_ACTIONS}")
        object.__setattr__(self, "eta_s", _require_number(self.eta_s, "eta_s", minimum=0.0))

    def as_doc(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "edge_id": self.edge_id,
            "action": self.action,
            "eta_s": self.eta_s,
        }


@dataclass(frozen=True)
class MemoryRecord:
    """One structured memory event. Five fields, no free-text field.

    ``value`` is a number or a namespaced ID. A string is validated exactly like
    any other ID, so "the agent wrote a sentence" is unrepresentable.
    """

    event_id: str
    kind: str
    t_sim: float
    subject_id: str
    value: float | str

    def __post_init__(self) -> None:
        validate_token_id(self.event_id, what="event_id")
        if self.kind not in MEMORY_KINDS:
            raise AgentError(f"memory kind {self.kind!r} not in {MEMORY_KINDS}")
        object.__setattr__(self, "t_sim", _require_number(self.t_sim, "t_sim", minimum=0.0))
        validate_token_id(self.subject_id, what="subject_id")
        value = self.value
        if isinstance(value, str):
            validate_token_id(value, what="memory value")
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise AgentError(
                f"memory value must be a number or a namespaced ID, got {type(value).__name__}"
            )
        else:
            # Normalising to float means 3 and 3.0 cannot serialise differently.
            object.__setattr__(self, "value", _require_number(value, "memory value"))

    def as_doc(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "t_sim": self.t_sim,
            "subject_id": self.subject_id,
            "value": self.value,
        }


@dataclass(frozen=True)
class Neighbour:
    """Another agent inside the perception radius, as SUMO reports it."""

    agent_id: str
    kind: str
    edge_id: str
    distance_m: float

    def __post_init__(self) -> None:
        validate_agent_id(self.agent_id)
        if self.kind not in AGENT_KINDS:
            raise AgentError(f"neighbour kind {self.kind!r} not in {AGENT_KINDS}")
        validate_token_id(self.edge_id, what="neighbour edge_id")
        object.__setattr__(
            self, "distance_m", _require_number(self.distance_m, "distance_m", minimum=0.0)
        )

    def as_doc(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "kind": self.kind,
            "edge_id": self.edge_id,
            "distance_m": self.distance_m,
        }


@dataclass(frozen=True)
class Observation:
    """Everything an agent may know about the world this tick -- and no more.

    This is the whole interface to SUMO: ``current_edge`` is where the executed
    simulation put the body, ``reachable_edges`` / ``blocked_edges`` are the
    network's answer, ``successors`` is the local topology, ``neighbours`` are
    other agents in radius and ``signal_state`` is the signal. There is no pose
    field because an agent has no business carrying one.
    """

    agent_id: str
    current_edge: str
    reachable_edges: tuple[str, ...] = ()
    blocked_edges: tuple[str, ...] = ()
    successors: tuple[tuple[str, tuple[str, ...]], ...] = ()
    neighbours: tuple[Neighbour, ...] = ()
    signal_state: str = "none"
    t_sim: float = 0.0

    def __post_init__(self) -> None:
        validate_agent_id(self.agent_id)
        validate_token_id(self.current_edge, what="current_edge")
        object.__setattr__(self, "reachable_edges", _id_tuple(self.reachable_edges, "reachable edge"))
        object.__setattr__(self, "blocked_edges", _id_tuple(self.blocked_edges, "blocked edge"))
        object.__setattr__(self, "successors", _successor_pairs(self.successors))
        neighbours = tuple(self.neighbours)
        for neighbour in neighbours:
            if not isinstance(neighbour, Neighbour):
                raise AgentError("observation neighbours must be Neighbour instances")
        object.__setattr__(
            self,
            "neighbours",
            tuple(sorted(neighbours, key=lambda n: (n.distance_m, n.agent_id))),
        )
        if self.signal_state not in SIGNAL_STATES:
            raise AgentError(f"signal_state {self.signal_state!r} not in {SIGNAL_STATES}")
        object.__setattr__(self, "t_sim", _require_number(self.t_sim, "t_sim", minimum=0.0))

    def as_doc(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "current_edge": self.current_edge,
            "reachable_edges": list(self.reachable_edges),
            "blocked_edges": list(self.blocked_edges),
            "successors": [[edge, list(succs)] for edge, succs in self.successors],
            "neighbours": [n.as_doc() for n in self.neighbours],
            "signal_state": self.signal_state,
            "t_sim": self.t_sim,
        }


@dataclass(frozen=True)
class AgentState:
    """The agent. No pose, no clock, no free text -- a goal stack and a plan."""

    agent_id: str
    kind: str
    goal_stack: tuple[Goal, ...] = ()
    plan: tuple[PlanStep, ...] = ()
    memory: tuple[MemoryRecord, ...] = ()
    status: str = "active"

    def __post_init__(self) -> None:
        validate_agent_id(self.agent_id)
        if self.kind not in AGENT_KINDS:
            raise AgentError(f"agent kind {self.kind!r} not in {AGENT_KINDS}")
        if self.status not in AGENT_STATUSES:
            raise AgentError(f"status {self.status!r} not in {AGENT_STATUSES}")

        goals = _as_tuple(self.goal_stack, Goal, "goal_stack")
        goal_ids = [g.goal_id for g in goals]
        if len(set(goal_ids)) != len(goal_ids):
            raise AgentError("goal_stack must not contain a duplicated goal_id")
        object.__setattr__(self, "goal_stack", goals)

        object.__setattr__(self, "plan", _as_tuple(self.plan, PlanStep, "plan"))

        memory = _as_tuple(self.memory, MemoryRecord, "memory")
        if len(memory) > MEMORY_CAPACITY:
            raise AgentError(
                f"memory holds {len(memory)} records, capacity is {MEMORY_CAPACITY}; "
                f"use remember() which evicts the oldest first"
            )
        object.__setattr__(self, "memory", memory)

    def as_doc(self) -> dict[str, Any]:
        return {
            "schema": AGENT_STATE_VERSION,
            "agent_id": self.agent_id,
            "kind": self.kind,
            "status": self.status,
            "goal_stack": [g.as_doc() for g in self.goal_stack],
            "plan": [s.as_doc() for s in self.plan],
            "memory": [r.as_doc() for r in self.memory],
        }


def _as_tuple(values: Any, item_type: type, what: str) -> tuple[Any, ...]:
    if not isinstance(values, (tuple, list)):
        raise AgentError(f"{what} must be a tuple or list, got {type(values).__name__}")
    out = tuple(values)
    for item in out:
        if not isinstance(item, item_type):
            raise AgentError(f"{what} may only contain {item_type.__name__}, got {item!r}")
    return out


@dataclass(frozen=True)
class Perception:
    """What the agent believes about the world after one tick's look.

    ``plan_valid`` is exactly ``invalidation is None and stale_reason is None``:
    an invalid plan is either broken by the world (``invalidation``, one of
    ``REPLAN_REASONS``) or stale by the agent's own books (``stale_reason``).
    """

    agent_id: str
    t_sim: float
    current_edge: str
    reachable_edges: tuple[str, ...]
    blocked_edges: tuple[str, ...]
    open_edges: tuple[str, ...]
    avoided_edges: tuple[str, ...]
    successors: tuple[tuple[str, tuple[str, ...]], ...]
    neighbours: tuple[Neighbour, ...]
    signal_state: str
    active_goal_id: str
    goal_target: str
    goal_reachable: bool
    blocked_step_edge: str
    deadline_passed: bool
    invalidation: str | None
    stale_reason: str | None
    plan_valid: bool

    def __post_init__(self) -> None:
        validate_agent_id(self.agent_id)
        object.__setattr__(self, "t_sim", _require_number(self.t_sim, "t_sim", minimum=0.0))
        if self.invalidation is not None and self.invalidation not in REPLAN_REASONS:
            raise AgentError(f"invalidation {self.invalidation!r} not in {REPLAN_REASONS}")
        if self.stale_reason is not None and self.stale_reason not in PLAN_STALE_REASONS:
            raise AgentError(f"stale_reason {self.stale_reason!r} not in {PLAN_STALE_REASONS}")
        expected_valid = self.invalidation is None and self.stale_reason is None
        if self.plan_valid != expected_valid:
            raise AgentError(
                "plan_valid must be exactly 'no invalidation and no stale reason' "
                f"({self.plan_valid!r} != {expected_valid!r})"
            )

    def as_doc(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "t_sim": self.t_sim,
            "current_edge": self.current_edge,
            "reachable_edges": list(self.reachable_edges),
            "blocked_edges": list(self.blocked_edges),
            "open_edges": list(self.open_edges),
            "avoided_edges": list(self.avoided_edges),
            "successors": [[edge, list(succs)] for edge, succs in self.successors],
            "neighbours": [n.as_doc() for n in self.neighbours],
            "signal_state": self.signal_state,
            "active_goal_id": self.active_goal_id,
            "goal_target": self.goal_target,
            "goal_reachable": self.goal_reachable,
            "blocked_step_edge": self.blocked_step_edge,
            "deadline_passed": self.deadline_passed,
            "invalidation": self.invalidation,
            "stale_reason": self.stale_reason,
            "plan_valid": self.plan_valid,
        }


@dataclass(frozen=True)
class Decision:
    """The tick's choice: an intent, a reason code, and the plan to carry."""

    agent_id: str
    tick: int
    episode_id: str
    t_sim: float
    goal_id: str
    action: str
    edge_id: str
    reason: str
    candidates: tuple[str, ...]
    plan: tuple[PlanStep, ...]
    plan_installed: bool

    def __post_init__(self) -> None:
        validate_agent_id(self.agent_id)
        validate_token_id(self.episode_id, what="episode_id")
        if isinstance(self.tick, bool) or not isinstance(self.tick, int) or self.tick < 0:
            raise AgentError(f"tick must be a non-negative int, got {self.tick!r}")
        object.__setattr__(self, "t_sim", _require_number(self.t_sim, "t_sim", minimum=0.0))
        if self.action not in ACTION_KINDS:
            raise AgentError(f"decision action {self.action!r} not in {ACTION_KINDS}")
        if self.reason not in DECISION_REASONS:
            raise AgentError(f"decision reason {self.reason!r} not in {DECISION_REASONS}")
        if self.action == "hold":
            if self.edge_id != "":
                raise AgentError("a hold decision names no edge")
        else:
            validate_token_id(self.edge_id, what="decision edge_id")
        if self.goal_id != "":
            validate_token_id(self.goal_id, what="decision goal_id")
        object.__setattr__(self, "candidates", _id_tuple(self.candidates, "decision candidate"))
        object.__setattr__(self, "plan", _as_tuple(self.plan, PlanStep, "decision plan"))
        if self.plan_installed and not self.plan:
            raise AgentError("plan_installed is only meaningful with a plan to install")

    def as_doc(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "tick": self.tick,
            "episode_id": self.episode_id,
            "t_sim": self.t_sim,
            "goal_id": self.goal_id,
            "action": self.action,
            "edge_id": self.edge_id,
            "reason": self.reason,
            "candidates": list(self.candidates),
            "plan": [s.as_doc() for s in self.plan],
            "plan_installed": self.plan_installed,
        }


@dataclass(frozen=True)
class AgentAction:
    """An INTENT for SUMO to execute. No position, no speed, no yaw."""

    agent_id: str
    tick: int
    episode_id: str
    action: str
    edge_id: str
    goal_id: str
    t_sim: float

    def __post_init__(self) -> None:
        validate_agent_id(self.agent_id)
        validate_token_id(self.episode_id, what="episode_id")
        if isinstance(self.tick, bool) or not isinstance(self.tick, int) or self.tick < 0:
            raise AgentError(f"tick must be a non-negative int, got {self.tick!r}")
        if self.action not in ACTION_KINDS:
            raise AgentError(f"action {self.action!r} not in {ACTION_KINDS}")
        if self.action == "hold":
            if self.edge_id != "":
                raise AgentError("a hold intent names no edge")
        else:
            validate_token_id(self.edge_id, what="action edge_id")
        if self.goal_id != "":
            validate_token_id(self.goal_id, what="action goal_id")
        object.__setattr__(self, "t_sim", _require_number(self.t_sim, "t_sim", minimum=0.0))

    def as_doc(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "tick": self.tick,
            "episode_id": self.episode_id,
            "action": self.action,
            "edge_id": self.edge_id,
            "goal_id": self.goal_id,
            "t_sim": self.t_sim,
        }


@dataclass(frozen=True)
class ActionResult:
    """The intent, the state it leaves behind, and the records it wrote."""

    action: AgentAction
    state: AgentState
    records: tuple[MemoryRecord, ...]


@dataclass(frozen=True)
class ReplanResult:
    """The repaired state, the reason code used, and whether it settled."""

    state: AgentState
    reason: str
    resolved: bool
    records: tuple[MemoryRecord, ...]


@dataclass(frozen=True)
class AgentStep:
    """One whole tick: world in, intent and records out."""

    tick: int
    episode_id: str
    state: AgentState
    records: tuple[MemoryRecord, ...]
    action: AgentAction
    perception: Perception
    decision: Decision
    replanned: bool
    replan_reason: str | None
    attempts: int


# --- tie-breaking -----------------------------------------------------------


def tiebreak_seed(agent_id: str, episode_id: str, tick: int) -> int:
    """The only source of choice in this module.

    The seed is ``sha256("<agent_id>:<episode_id>:<tick>")`` truncated to 64
    bits, so it is built from exactly those three inputs: no wall clock, no
    ``id()``, no dict or set ordering, and no dependence on the global
    ``random`` module state (which is never touched).
    """
    validate_agent_id(agent_id)
    validate_token_id(episode_id, what="episode_id")
    if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
        raise AgentError(f"tick must be a non-negative int, got {tick!r}")
    key = f"{agent_id}:{episode_id}:{int(tick)}"
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big")


def tiebreak_rng(agent_id: str, episode_id: str, tick: int) -> random.Random:
    """A local, seeded ``random.Random`` -- never the module-level one."""
    return random.Random(tiebreak_seed(agent_id, episode_id, tick))


def _choose(candidates: Sequence[str], agent_id: str, episode_id: str, tick: int) -> str:
    """One edge out of a sorted, equally good candidate set. At most one draw."""
    ordered = tuple(sorted(candidates))
    if not ordered:
        return ""
    if len(ordered) == 1:
        return ordered[0]
    rng = tiebreak_rng(agent_id, episode_id, tick)
    return ordered[rng.randrange(len(ordered))]


# --- graph and planning -----------------------------------------------------


def _as_map(successors: Iterable[tuple[str, tuple[str, ...]]]) -> dict[str, tuple[str, ...]]:
    return {edge: tuple(succs) for edge, succs in successors}


def _backward_distances(successors: dict[str, tuple[str, ...]], target: str) -> dict[str, int]:
    """Unit-cost BFS over reversed edges: every edge's hop count to target."""
    reverse: dict[str, list[str]] = {}
    for edge in sorted(successors):
        for nxt in successors[edge]:
            reverse.setdefault(nxt, []).append(edge)
    distance = {target: 0}
    frontier = [target]
    while frontier:
        next_frontier: list[str] = []
        for node in frontier:
            for previous in sorted(reverse.get(node, ())):
                if previous not in distance:
                    distance[previous] = distance[node] + 1
                    next_frontier.append(previous)
        frontier = next_frontier
    return distance


def _first_hop_candidates(
    current_edge: str, successors: dict[str, tuple[str, ...]], allowed: Iterable[str], target: str
) -> tuple[str, ...]:
    """The equally-shortest first hops from here to ``target``, sorted by edge id."""
    if current_edge == target:
        return ()
    distance = _backward_distances(successors, target)
    allowed_set = set(allowed)
    options = [
        succ
        for succ in successors.get(current_edge, ())
        if succ in allowed_set and succ in distance
    ]
    options.sort(key=lambda edge: (distance[edge], edge))
    if not options:
        return ()
    best = distance[options[0]]
    return tuple(edge for edge in options if distance[edge] == best)


def _open_route(
    successors: dict[str, tuple[str, ...]], allowed: Iterable[str], start: str, target: str
) -> tuple[str, ...]:
    """A deterministic open-edge path from ``start`` to ``target``, or ``()``.

    Greedy descent on exact BFS distance, so the walk strictly decreases and
    cannot cycle; ties are broken by edge id, never by the rng, so a plan tail
    is a pure function of the graph.
    """
    if start == target:
        return ()
    distance = _backward_distances(successors, target)
    if start not in distance:
        return ()
    allowed_set = set(allowed)
    path: list[str] = []
    current = start
    for _ in range(len(successors) + 2):
        options = [s for s in successors.get(current, ()) if s in allowed_set and s in distance]
        if not options:
            return ()
        options.sort(key=lambda edge: (distance[edge], edge))
        current = options[0]
        path.append(current)
        if current == target:
            return tuple(path)
    return ()


def _plan_route(
    goal: Goal,
    current_edge: str,
    successors: dict[str, tuple[str, ...]],
    allowed: Iterable[str],
    agent_id: str,
    episode_id: str,
    tick: int,
) -> tuple[PlanStep, ...]:
    """The plan for one goal. Never returns a step on a disallowed edge.

    A ``travel_to`` plan is the remaining route: its last step is the goal's
    target edge. The rng is drawn at most once, at the first hop, and only among
    equally short alternatives. A ``wait_until`` plan is a single wait step on
    the edge the agent is already standing on.
    """
    if goal.kind == "wait_until":
        return (
            PlanStep(
                goal_id=goal.goal_id,
                edge_id=current_edge,
                action="wait",
                eta_s=SECONDS_PER_EDGE,
            ),
        )
    if goal.kind != "travel_to" or current_edge == goal.target:
        return ()
    ties = _first_hop_candidates(current_edge, successors, allowed, goal.target)
    if not ties:
        return ()
    chosen = _choose(ties, agent_id, episode_id, tick)
    rest = _open_route(successors, allowed, chosen, goal.target)
    if chosen != goal.target and not rest:
        return ()
    path = (chosen,) + rest
    if path[-1] != goal.target:
        return ()
    return tuple(
        PlanStep(
            goal_id=goal.goal_id,
            edge_id=edge_id,
            action="traverse",
            eta_s=_f6(SECONDS_PER_EDGE * (index + 1)),
        )
        for index, edge_id in enumerate(path)
    )


def _consume_plan(plan: tuple[PlanStep, ...], current_edge: str) -> tuple[PlanStep, ...]:
    """Drop leading traverse steps the agent has already executed.

    Where the body actually is comes from SUMO via the observation, so a step
    whose edge is the current edge is finished. Wait steps are never consumed --
    a waiting agent stays where it is.
    """
    remaining = plan
    while remaining and remaining[0].action == "traverse" and remaining[0].edge_id == current_edge:
        remaining = remaining[1:]
    return remaining


def active_goal(state: AgentState) -> Goal | None:
    """The current stage: the first goal that is not an ``avoid`` constraint."""
    for goal in state.goal_stack:
        if goal.kind != "avoid":
            return goal
    return None


def constraint_edges(state: AgentState) -> tuple[str, ...]:
    """Edges the agent's own ``avoid`` goals forbid, sorted."""
    return tuple(sorted({g.target for g in state.goal_stack if g.kind == "avoid"}))


def _goal_finished(goal: Goal, perception: Perception) -> bool:
    if goal.kind == "avoid":
        return goal.deadline_s is not None and perception.t_sim >= goal.deadline_s
    if goal.kind == "travel_to":
        return perception.current_edge == goal.target
    if goal.kind == "wait_until":
        if goal.target == f"signal:{perception.signal_state}":
            return True
        return goal.deadline_s is not None and perception.t_sim >= goal.deadline_s
    return False


def _plan_matches_stage(plan: tuple[PlanStep, ...], goal: Goal, current_edge: str) -> bool:
    if not plan:
        return False
    if any(step.goal_id != goal.goal_id for step in plan):
        return False
    if goal.kind == "travel_to":
        return plan[-1].action == "traverse" and plan[-1].edge_id == goal.target
    if goal.kind == "wait_until":
        return len(plan) == 1 and plan[0].action == "wait" and plan[0].edge_id == current_edge
    return False


# --- the pipeline -----------------------------------------------------------


def perceive(state: AgentState, observation: Observation) -> Perception:
    """Read the world from ``observation`` and test the plan against it.

    Nothing else is consulted: no global, no clock, no file, no SUMO. The only
    other input is the agent's own ``state`` (its plan, its goals), which is what
    makes this a pure function of two arguments.
    """
    if observation.agent_id != state.agent_id:
        raise AgentError(
            f"observation for {observation.agent_id!r} offered to agent {state.agent_id!r}"
        )

    reachable = tuple(sorted(set(observation.reachable_edges)))
    blocked = tuple(sorted(set(observation.blocked_edges)))
    reachable_set = set(reachable)
    blocked_set = set(blocked)
    open_edges = tuple(sorted(reachable_set - blocked_set))
    successors = _as_map(observation.successors)
    neighbours = tuple(
        n for n in observation.neighbours if n.distance_m <= PERCEPTION_RADIUS_M
    )

    goal = active_goal(state)
    avoided = constraint_edges(state)

    remaining = _consume_plan(state.plan, observation.current_edge)
    blocked_step_edge = ""
    for step in remaining:
        if step.action != "traverse":
            continue
        # An edge the world no longer offers is as unusable as a closed one.
        if step.edge_id in blocked_set or step.edge_id not in reachable_set:
            blocked_step_edge = step.edge_id
            break

    deadline_passed = bool(
        goal is not None
        and goal.deadline_s is not None
        and observation.t_sim > goal.deadline_s
    )
    goal_reachable = goal is None or _goal_reachable(
        goal, observation.current_edge, open_edges, successors
    )

    invalidation: str | None = None
    if goal is not None:
        if deadline_passed:
            invalidation = "deadline_passed"
        elif blocked_step_edge:
            invalidation = "edge_blocked"
        elif not goal_reachable:
            invalidation = "goal_unreachable"

    stale_reason: str | None = None
    if goal is None:
        if remaining:
            stale_reason = "plan_stage_mismatch"
    elif not remaining:
        stale_reason = "no_plan"
    elif not _plan_matches_stage(remaining, goal, observation.current_edge):
        stale_reason = "plan_stage_mismatch"
    elif any(step.action == "traverse" and step.edge_id in set(avoided) for step in remaining):
        stale_reason = "avoid_goal"
    elif remaining[0].action == "traverse" and remaining[0].edge_id not in successors.get(
        observation.current_edge, ()
    ):
        stale_reason = "plan_position_mismatch"

    return Perception(
        agent_id=state.agent_id,
        t_sim=observation.t_sim,
        current_edge=observation.current_edge,
        reachable_edges=reachable,
        blocked_edges=blocked,
        open_edges=open_edges,
        avoided_edges=avoided,
        successors=observation.successors,
        neighbours=neighbours,
        signal_state=observation.signal_state,
        active_goal_id="" if goal is None else goal.goal_id,
        goal_target="" if goal is None else goal.target,
        goal_reachable=goal_reachable,
        blocked_step_edge=blocked_step_edge,
        deadline_passed=deadline_passed,
        invalidation=invalidation,
        stale_reason=stale_reason,
        plan_valid=invalidation is None and stale_reason is None,
    )


def _goal_reachable(
    goal: Goal,
    current_edge: str,
    open_edges: tuple[str, ...],
    successors: dict[str, tuple[str, ...]],
) -> bool:
    """Only a ``travel_to`` target can be out of reach; a wait needs no route."""
    if goal.kind != "travel_to":
        return True
    if current_edge == goal.target:
        return True
    return bool(_open_route(successors, open_edges, current_edge, goal.target))


def _decision(
    state: AgentState,
    perception: Perception,
    tick: int,
    episode_id: str,
    *,
    action: str,
    edge_id: str,
    goal_id: str,
    reason: str,
    candidates: Sequence[str],
    plan: tuple[PlanStep, ...],
    plan_installed: bool,
) -> Decision:
    return Decision(
        agent_id=state.agent_id,
        tick=tick,
        episode_id=episode_id,
        t_sim=perception.t_sim,
        goal_id=goal_id,
        action=action,
        edge_id=edge_id,
        reason=reason,
        candidates=tuple(candidates),
        plan=plan,
        plan_installed=plan_installed,
    )


def _yielding_neighbour(
    kind: str, next_edge: str, neighbours: tuple[Neighbour, ...]
) -> Neighbour | None:
    """The highest-priority agent (nearest first) that owns the edge we want."""
    mine = KIND_PRIORITY[kind]
    for neighbour in neighbours:
        if (
            neighbour.edge_id == next_edge
            and neighbour.distance_m <= YIELD_RADIUS_M
            and KIND_PRIORITY[neighbour.kind] > mine
        ):
            return neighbour
    return None


def decide(state: AgentState, perception: Perception, tick: int, episode_id: str) -> Decision:
    """Choose this tick's intent and the plan the agent should now carry.

    Precedence is fixed and documented: a non-active status holds; no stage
    holds; an unbuildable plan holds as ``goal_unreachable`` (which ``act``
    turns into ``blocked``); a red signal waits; a higher-priority neighbour
    waits; otherwise the agent traverses the first step of its plan.
    """
    if state.status == "blocked":
        return _decision(
            state,
            perception,
            tick,
            episode_id,
            action="hold",
            edge_id="",
            goal_id="",
            reason="blocked",
            candidates=(),
            plan=(),
            plan_installed=False,
        )
    if state.status == "done":
        return _decision(
            state,
            perception,
            tick,
            episode_id,
            action="hold",
            edge_id="",
            goal_id="",
            reason="no_goals",
            candidates=(),
            plan=(),
            plan_installed=False,
        )

    goal = active_goal(state)
    if goal is None:
        return _decision(
            state,
            perception,
            tick,
            episode_id,
            action="hold",
            edge_id="",
            goal_id="",
            reason="no_goals",
            candidates=(),
            plan=(),
            plan_installed=False,
        )

    allowed = set(perception.open_edges) - set(perception.avoided_edges)
    successors = _as_map(perception.successors)
    if perception.plan_valid:
        plan = _consume_plan(state.plan, perception.current_edge)
        plan_installed = False
    else:
        plan = _plan_route(
            goal, perception.current_edge, successors, allowed, state.agent_id, episode_id, tick
        )
        plan_installed = bool(plan) and perception.stale_reason is not None

    if goal.kind == "wait_until":
        return _decision(
            state,
            perception,
            tick,
            episode_id,
            action="wait",
            edge_id=perception.current_edge,
            goal_id=goal.goal_id,
            reason="goal_active",
            candidates=(),
            plan=plan,
            plan_installed=plan_installed,
        )

    if perception.current_edge == goal.target:
        # The stage is complete; it is popped by advance_stages before decide in
        # a whole tick, so this branch only answers a direct call.
        return _decision(
            state,
            perception,
            tick,
            episode_id,
            action="wait",
            edge_id=perception.current_edge,
            goal_id=goal.goal_id,
            reason="goal_active",
            candidates=(),
            plan=(),
            plan_installed=False,
        )

    if not plan:
        return _decision(
            state,
            perception,
            tick,
            episode_id,
            action="hold",
            edge_id="",
            goal_id=goal.goal_id,
            reason="goal_unreachable",
            candidates=(),
            plan=(),
            plan_installed=False,
        )

    candidates = _first_hop_candidates(perception.current_edge, successors, allowed, goal.target)
    next_edge = plan[0].edge_id

    if perception.signal_state == "red":
        return _decision(
            state,
            perception,
            tick,
            episode_id,
            action="wait",
            edge_id=perception.current_edge,
            goal_id=goal.goal_id,
            reason="signal_stop",
            candidates=candidates,
            plan=plan,
            plan_installed=plan_installed,
        )

    if _yielding_neighbour(state.kind, next_edge, perception.neighbours) is not None:
        return _decision(
            state,
            perception,
            tick,
            episode_id,
            action="wait",
            edge_id=perception.current_edge,
            goal_id=goal.goal_id,
            reason="yield_neighbour",
            candidates=candidates,
            plan=plan,
            plan_installed=plan_installed,
        )

    return _decision(
        state,
        perception,
        tick,
        episode_id,
        action="traverse",
        edge_id=next_edge,
        goal_id=goal.goal_id,
        reason="goal_active",
        candidates=candidates,
        plan=plan,
        plan_installed=plan_installed,
    )


def act(state: AgentState, decision: Decision) -> ActionResult:
    """Turn a decision into an intent and write the memory it implies.

    A ``hold`` writes no record at all: it is the absence of an intent, so an
    agent that is blocked or out of goals cannot flush its own memory by
    waiting. Record order is fixed: plan install, status change, intent.
    """
    if decision.agent_id != state.agent_id:
        raise AgentError(
            f"decision for {decision.agent_id!r} offered to agent {state.agent_id!r}"
        )

    records: list[MemoryRecord] = []
    plan = state.plan
    status = state.status
    if decision.plan_installed:
        plan = decision.plan
        records.append(
            _record(
                state.agent_id,
                decision.episode_id,
                decision.tick,
                "agent_planned",
                decision.t_sim,
                decision.goal_id,
                float(len(plan)),
            )
        )
    elif plan != decision.plan:
        # Consuming the step just executed is not an event.
        plan = decision.plan

    if decision.reason == "no_goals" and state.status == "active" and active_goal(state) is None:
        status = "done"
        records.append(
            _record(
                state.agent_id,
                decision.episode_id,
                decision.tick,
                "status_changed",
                decision.t_sim,
                state.agent_id,
                "status:done",
            )
        )
    elif decision.reason == "goal_unreachable" and state.status == "active":
        status = "blocked"
        records.append(
            _record(
                state.agent_id,
                decision.episode_id,
                decision.tick,
                "status_changed",
                decision.t_sim,
                state.agent_id,
                "status:blocked",
            )
        )

    if decision.action != "hold":
        records.append(
            _record(
                state.agent_id,
                decision.episode_id,
                decision.tick,
                "intent_issued",
                decision.t_sim,
                decision.edge_id,
                decision.t_sim,
            )
        )

    action = AgentAction(
        agent_id=state.agent_id,
        tick=decision.tick,
        episode_id=decision.episode_id,
        action=decision.action,
        edge_id=decision.edge_id,
        goal_id=decision.goal_id,
        t_sim=decision.t_sim,
    )
    new_state = replace(state, plan=plan, status=status)
    return ActionResult(action=action, state=new_state, records=tuple(records))


def assert_replan_avoids(
    old_plan: Sequence[PlanStep],
    new_plan: Sequence[PlanStep],
    blocked_edges: Iterable[str],
    *,
    forbidden: Iterable[str] = (),
) -> None:
    """Hard rule: a replan may never hand back the same invalid plan.

    Raises ``AgentDefect`` when the returned plan is non-empty and still enters
    an edge that is blocked or forbidden -- which includes the case
    ``new_plan == old_plan`` (the repair did nothing, and the caller would loop).
    An empty plan is not a defect: that is the deliberate "no way through" answer
    which sets ``status`` to ``blocked``. A ``wait`` step on the current edge is
    never a defect either: the agent is already standing there.
    """
    unavailable = {validate_token_id(e, what="blocked edge") for e in blocked_edges}
    unavailable |= {validate_token_id(e, what="forbidden edge") for e in forbidden}
    for step in new_plan:
        if step.action == "traverse" and step.edge_id in unavailable:
            raise AgentDefect(
                f"replan returned a plan that still enters {step.edge_id!r}; "
                f"new plan identical to the invalid one: {tuple(new_plan) == tuple(old_plan)}"
            )


def replan(
    state: AgentState,
    perception: Perception,
    tick: int,
    episode_id: str,
    *,
    reason: str | None = None,
) -> ReplanResult:
    """Repair an invalid plan, or declare the agent ``blocked``.

    ``reason`` defaults to ``perception.invalidation``; ``edge_cleared`` is
    passed explicitly by ``step_agent`` when a blocked agent retries and the
    world has reopened. The returned plan avoids the blocked element, or the
    result is an empty plan with ``status == "blocked"``.
    """
    if reason is None:
        reason = perception.invalidation
    if reason is None:
        raise AgentError("replan needs a reason: perception reports no invalidation")
    if reason not in REPLAN_REASONS:
        raise AgentError(f"replan reason {reason!r} not in {REPLAN_REASONS}")

    t_sim = perception.t_sim
    goal = active_goal(state)
    records: list[MemoryRecord] = []

    def rec(kind: str, subject_id: str, value: float | str) -> MemoryRecord:
        return _record(state.agent_id, episode_id, tick, kind, t_sim, subject_id, value)

    if goal is None:
        # Nothing to repair when no stage is active.
        return ReplanResult(state=state, reason=reason, resolved=True, records=())

    if reason == "deadline_passed":
        if goal.kind == "wait_until":
            # A bounded wait ends at its deadline: the stage completes rather
            # than blocking the trip.
            records.append(rec("goal_completed", goal.goal_id, _f6(t_sim)))
            new_state = replace(
                state,
                goal_stack=tuple(g for g in state.goal_stack if g.goal_id != goal.goal_id),
                plan=tuple(s for s in state.plan if s.goal_id != goal.goal_id),
            )
            return ReplanResult(
                state=new_state, reason=reason, resolved=True, records=tuple(records)
            )
        records.append(rec("agent_replanned", goal.goal_id, f"reason:{reason}"))
        records.append(rec("status_changed", state.agent_id, "status:blocked"))
        return ReplanResult(
            state=replace(state, status="blocked", plan=()),
            reason=reason,
            resolved=True,
            records=tuple(records),
        )

    if reason in ("edge_blocked", "goal_unreachable", "edge_cleared"):
        if perception.blocked_step_edge:
            records.append(rec("blocked_edge_seen", perception.blocked_step_edge, _f6(t_sim)))
        allowed = set(perception.open_edges) - set(perception.avoided_edges)
        plan = _plan_route(
            goal,
            perception.current_edge,
            _as_map(perception.successors),
            allowed,
            state.agent_id,
            episode_id,
            tick,
        )
        if plan:
            assert_replan_avoids(
                state.plan, plan, perception.blocked_edges, forbidden=perception.avoided_edges
            )
            records.append(rec("agent_replanned", goal.goal_id, f"reason:{reason}"))
            if state.status != "active":
                records.append(rec("status_changed", state.agent_id, "status:active"))
            return ReplanResult(
                state=replace(state, plan=plan, status="active"),
                reason=reason,
                resolved=True,
                records=tuple(records),
            )
        if reason == "edge_cleared":
            # The retry found nothing; the agent stays blocked and says nothing.
            return ReplanResult(state=state, reason=reason, resolved=True, records=tuple(records))
        records.append(rec("agent_replanned", goal.goal_id, f"reason:{reason}"))
        records.append(rec("status_changed", state.agent_id, "status:blocked"))
        return ReplanResult(
            state=replace(state, plan=(), status="blocked"),
            reason=reason,
            resolved=True,
            records=tuple(records),
        )

    raise AgentError(f"unhandled replan reason {reason!r}")


def advance_stages(
    state: AgentState, perception: Perception, episode_id: str, tick: int
) -> tuple[AgentState, tuple[MemoryRecord, ...]]:
    """Pop every goal that has finished, in stack order.

    A stage pops when the agent stands on a ``travel_to`` target or a
    ``wait_until`` condition is met (or its deadline passes); an ``avoid``
    constraint leaves the stack when its deadline passes. The plan belonging to
    a popped goal is discarded, so the next stage starts from a clean route.
    """
    kept: list[Goal] = []
    popped: list[Goal] = []
    for goal in state.goal_stack:
        if _goal_finished(goal, perception):
            popped.append(goal)
        else:
            kept.append(goal)
    if not popped:
        return state, ()

    records = tuple(
        _record(
            state.agent_id,
            episode_id,
            tick,
            "goal_completed",
            perception.t_sim,
            goal.goal_id,
            _f6(perception.t_sim),
        )
        for goal in popped
    )
    popped_ids = {goal.goal_id for goal in popped}
    plan = state.plan
    if any(step.goal_id in popped_ids for step in plan):
        plan = ()
    return replace(state, goal_stack=tuple(kept), plan=plan), records


def remember(state: AgentState, record: MemoryRecord) -> AgentState:
    """Append one record and evict the oldest first past ``MEMORY_CAPACITY``.

    Eviction itself is not recorded: a record of a dropped record would be an
    unbounded ledger growing inside a structure whose whole point is to be
    bounded.
    """
    if not isinstance(record, MemoryRecord):
        raise AgentError(f"remember expects a MemoryRecord, got {type(record).__name__}")
    memory = state.memory + (record,)
    if len(memory) > MEMORY_CAPACITY:
        memory = memory[-MEMORY_CAPACITY:]
    return replace(state, memory=memory)


def _record(
    agent_id: str,
    episode_id: str,
    tick: int,
    kind: str,
    t_sim: float,
    subject_id: str,
    value: float | str,
) -> MemoryRecord:
    """Provisional record id; ``step_agent`` renumbers the tick's records."""
    return MemoryRecord(
        event_id=f"{agent_id}:{episode_id}:{tick:06d}:{kind}",
        kind=kind,
        t_sim=t_sim,
        subject_id=subject_id,
        value=value,
    )


def step_agent(
    state: AgentState,
    observation: Observation,
    tick: int,
    episode_id: str,
    *,
    replan_attempt_limit: int = REPLAN_ATTEMPT_LIMIT,
) -> AgentStep:
    """One tick of the whole pipeline, in the documented order.

    1. ``perceive`` the world.
    2. If the agent is ``blocked`` and the world offers a route again, retry the
       replan with ``edge_cleared``.
    3. ``advance_stages``: pop finished stages, in order, with records.
    4. ``replan`` while perception still marks the plan invalid, bounded by
       ``replan_attempt_limit``. If the bound is reached the agent becomes
       ``blocked`` -- a replan loop cannot spin.
    5. ``decide`` then ``act``.
    6. ``remember`` every record in order, renumbered so event ids are unique
       and ordered inside the tick.

    The records a tick produced are the return value AND the memory the state
    carries afterwards.
    """
    if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
        raise AgentError(f"tick must be a non-negative int, got {tick!r}")
    validate_token_id(episode_id, what="episode_id")
    if isinstance(replan_attempt_limit, bool) or not isinstance(replan_attempt_limit, int):
        raise AgentError("replan_attempt_limit must be an int")
    if replan_attempt_limit < 1:
        raise AgentError("replan_attempt_limit must be at least 1")

    records: list[MemoryRecord] = []
    attempts = 0
    replan_reason: str | None = None

    perception = perceive(state, observation)

    if state.status == "blocked" and state.goal_stack and perception.goal_reachable:
        result = replan(state, perception, tick, episode_id, reason="edge_cleared")
        attempts += 1
        replan_reason = result.reason
        records.extend(result.records)
        state = result.state
        perception = perceive(state, observation)

    if state.status == "active":
        state, stage_records = advance_stages(state, perception, episode_id, tick)
        if stage_records:
            records.extend(stage_records)
            perception = perceive(state, observation)

    while (
        state.status == "active"
        and perception.invalidation is not None
        and attempts < replan_attempt_limit
    ):
        result = replan(state, perception, tick, episode_id, reason=perception.invalidation)
        attempts += 1
        if replan_reason is None:
            replan_reason = result.reason
        records.extend(result.records)
        state = result.state
        perception = perceive(state, observation)

    if state.status == "active" and perception.invalidation is not None:
        # The attempt bound is reached and the plan is still invalid: the agent
        # is blocked, and a blocked agent stops emitting.
        records.append(
            _record(
                state.agent_id,
                episode_id,
                tick,
                "status_changed",
                observation.t_sim,
                state.agent_id,
                "status:blocked",
            )
        )
        state = replace(state, status="blocked", plan=())
        perception = perceive(state, observation)

    decision = decide(state, perception, tick, episode_id)
    result = act(state, decision)
    records.extend(result.records)
    state = result.state

    records = [
        replace(record, event_id=f"{state.agent_id}:{episode_id}:{tick:06d}:{index:02d}")
        for index, record in enumerate(records)
    ]
    for record in records:
        state = remember(state, record)

    return AgentStep(
        tick=tick,
        episode_id=episode_id,
        state=state,
        records=tuple(records),
        action=result.action,
        perception=perception,
        decision=decision,
        replanned=bool(attempts),
        replan_reason=replan_reason,
        attempts=attempts,
    )


# --- canonical serialisation ------------------------------------------------


def canonical_bytes(doc: Any) -> bytes:
    """The pinned canonical form: sorted keys, no spaces, ASCII, no NaN."""
    return json.dumps(
        doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def goal_doc(goal: Goal) -> dict[str, Any]:
    return goal.as_doc()


def plan_doc(plan: Sequence[PlanStep]) -> list[dict[str, Any]]:
    return [step.as_doc() for step in plan]


def record_doc(record: MemoryRecord) -> dict[str, Any]:
    return record.as_doc()


def records_doc(records: Sequence[MemoryRecord]) -> list[dict[str, Any]]:
    return [record.as_doc() for record in records]


def state_doc(state: AgentState) -> dict[str, Any]:
    return state.as_doc()


def perception_doc(perception: Perception) -> dict[str, Any]:
    return perception.as_doc()


def decision_doc(decision: Decision) -> dict[str, Any]:
    return decision.as_doc()


def action_doc(action: AgentAction) -> dict[str, Any]:
    return action.as_doc()


def canonical_state_bytes(state: AgentState) -> bytes:
    return canonical_bytes(state_doc(state))


def canonical_records_bytes(records: Sequence[MemoryRecord]) -> bytes:
    return canonical_bytes(records_doc(records))


def canonical_perception_bytes(perception: Perception) -> bytes:
    return canonical_bytes(perception_doc(perception))


def canonical_decision_bytes(decision: Decision) -> bytes:
    return canonical_bytes(decision_doc(decision))


def canonical_action_bytes(action: AgentAction) -> bytes:
    return canonical_bytes(action_doc(action))
