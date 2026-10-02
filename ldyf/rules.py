"""PHASE 3 LANE 2 -- four rule classes over an already-open TraCI connection.

What this module is
-------------------
A `RuleSpec` names one durable change to the world and knows how to: validate
itself against the real SUMO net file, describe itself as a ledger payload, and
apply itself through TraCI. Four rule classes are provided -- a road closure, a
speed limit, a traffic-light programme and an inserted demand flow.

It does not run a simulation. `apply()` is handed an ALREADY-OPEN connection and
must not start, stop, seed or otherwise configure SUMO; that is the caller's
business (see `ldyf.closure.run_simulation`, which owns the process). Validation
is a pure net-file read: it refuses bad rules WITHOUT a simulation.

The SUMO 1.27.1 crash (RISK-1)
------------------------------
SUMO 1.27.1 crashes (0xC0000409 / 0xC0000005) when a `<closingReroute>` is
active and pedestrians are present. That mechanism is therefore **never used in
this project, and is never introduced here in any form.** `ClosureRule`
delegates lane selection to `ldyf.closure.select_closable_lanes`, which refuses
to return any lane that permits pedestrians, so a closure physically cannot
touch a footway. See `ldyf/closure.py` for the measured account.

Determinism
-----------
`DemandFlowRule` derives its vehicle ids and departure times arithmetically from
the declared rate and window -- `flow_id + "." + index` -- so they are never
random and never read a clock.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import sumolib

from .closure import (
    DEFAULT_DISALLOW,
    PEDESTRIAN_VCLASS,
    ClosureSpec,
    assert_pedestrian_access_preserved,
    select_closable_lanes,
)

__all__ = [
    "EPISODE_END_SECONDS",
    "PEDESTRIAN_VCLASS",   # re-exported from closure.py: the protected vclass
    "RuleError",
    "RuleSpec",
    "ClosureRule",
    "SpeedLimitRule",
    "TrafficLightRule",
    "DemandFlowRule",
    "validate_rule_set",
]

# The declared episode horizon. A rule that fires after this second could never
# take effect, so validate() refuses it. The caller may pass a different horizon
# to validate(); this is only the default.
EPISODE_END_SECONDS = 300.0

_SPEED_TARGET_KINDS = ("edge", "lane")


class RuleError(RuntimeError):
    """Raised when a rule is malformed, or cannot be validated against the net."""


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _known_ids(net: Any, target_kind: str) -> set[str]:
    if target_kind == "edge":
        return {e.getID() for e in net.getEdges()}
    return {ln.getID() for e in net.getEdges() for ln in e.getLanes()}


def _tls_programs(net_path: str | Path) -> dict[str, set[str]]:
    """Map every SUMO traffic-light id to the set of programme ids it declares.

    Read from the net file's own top-level `<tlLogic id=... programID=...>`
    elements rather than from sumolib's traffic-light objects: those objects
    changed shape across sumolib versions, while the net file's `<tlLogic>`
    element is the stable authority.
    """
    root = ET.parse(str(net_path)).getroot()
    out: dict[str, set[str]] = {}
    for tl in root.findall("tlLogic"):
        tid = tl.get("id")
        if tid is None:
            continue
        out.setdefault(tid, set()).add(tl.get("programID") or "0")
    return out


def _edge_reachable(net: Any, from_edge: str, to_edge: str) -> bool:
    """True if a route from `from_edge` to `to_edge` exists in the net graph.

    A BFS over `edge.getOutgoing()`, which sumolib derives from the net file's
    `<connection>` elements. A flow whose endpoints are unconnected has no route
    and must be refused.
    """
    if from_edge == to_edge:
        # Only reachable from itself if the edge can be re-entered from itself.
        return any(o.getID() == from_edge for o in net.getEdge(from_edge).getOutgoing())
    seen = {from_edge}
    queue = [from_edge]
    while queue:
        current = queue.pop(0)
        for out in sorted(net.getEdge(current).getOutgoing(), key=lambda e: e.getID()):
            oid = out.getID()
            if oid == to_edge:
                return True
            if oid not in seen:
                seen.add(oid)
                queue.append(oid)
    return False


def _lane_edge_id(lane_id: str) -> str:
    """The edge an ordinary SUMO lane id belongs to ('B1C1_1' -> 'B1C1')."""
    return lane_id.rsplit("_", 1)[0]


def _record_applied(result: Any, rule: "RuleSpec", detail: dict[str, Any]) -> None:
    """Append a note to a run result, when that result is willing to keep one."""
    if result is None:
        return
    applied = getattr(result, "applied_changes", None)
    if isinstance(applied, list):
        applied.append(
            {
                "rule_id": rule.rule_id,
                "change_type": rule.change_type(),
                "at_second": rule.at_second,
                **detail,
            }
        )


# --- the base contract ----------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class RuleSpec:
    """One durable change. Frozen: a validated rule can never mutate underfoot."""

    rule_id: str
    at_second: float = 0.0

    # Net-derived data cached by validate() for apply() to reuse. Excluded from
    # equality/hash so two rules with the same declaration compare equal.
    _validation: dict = field(default_factory=dict, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not self.rule_id:
            raise RuleError("rule_id must be a non-empty string")
        if not _finite(self.at_second):
            raise RuleError(f"rule {self.rule_id!r}: at_second must be finite, got {self.at_second!r}")
        if self.at_second < 0:
            raise RuleError(f"rule {self.rule_id!r}: at_second must not be negative")

    # --- subclass contract ---

    def change_type(self) -> str:
        """The ledger change_type this rule produces."""
        raise NotImplementedError

    def payload(self) -> dict[str, Any]:
        """The ledger payload for this rule (kind + fields)."""
        raise NotImplementedError

    def validate(self, net_path: str | Path, *, episode_end_seconds: float = EPISODE_END_SECONDS) -> None:
        """Refuse the rule against the real net WITHOUT running a simulation."""
        p = Path(net_path)
        if not p.exists():
            raise RuleError(f"net file not found: {p}")
        if self.at_second > episode_end_seconds:
            raise RuleError(
                f"rule {self.rule_id!r} fires at {self.at_second:g}s, beyond the episode "
                f"end ({episode_end_seconds:g}s): it could never take effect"
            )

    def apply(self, conn: Any, result: Any = None) -> None:
        """Apply this rule through an ALREADY-OPEN TraCI connection."""
        raise NotImplementedError


# --- the four rules -------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class ClosureRule(RuleSpec):
    """Close the carriageway of one or more edges, leaving the footway usable."""

    edge_ids: tuple[str, ...] = ()
    disallow: tuple[str, ...] = DEFAULT_DISALLOW

    def __post_init__(self) -> None:
        super().__post_init__()
        # Delegate the safety guard to closure.py: it refuses an empty edge set,
        # a negative at_second, and -- critically -- any disallow that names
        # pedestrians. We never reimplement those checks.
        ClosureSpec(edge_ids=self.edge_ids, at_second=self.at_second, disallow=self.disallow)

    def change_type(self) -> str:
        return "edge_closure"

    def payload(self) -> dict[str, Any]:
        return {
            "kind": "edge_closure",
            "edge_ids": list(self.edge_ids),
            "disallow": list(self.disallow),
        }

    def validate(self, net_path: str | Path, *, episode_end_seconds: float = EPISODE_END_SECONDS) -> None:
        super().validate(net_path, episode_end_seconds=episode_end_seconds)
        # Delegation, not reimplementation: closure.py decides which lanes may be
        # closed and refuses shared footway/carriageway lanes outright.
        lanes = select_closable_lanes(net_path, self.edge_ids, self.disallow)
        assert_pedestrian_access_preserved(net_path, lanes)
        self._validation["net_path"] = str(net_path)
        self._validation["lanes"] = tuple(lanes)

    def lanes(self) -> tuple[str, ...]:
        """The carriageway lanes selected by the last validate() call."""
        lanes = self._validation.get("lanes")
        if lanes is None:
            raise RuleError(
                f"rule {self.rule_id!r}: validate(net_path) must be called before the "
                "closable lanes are known"
            )
        return tuple(lanes)

    def apply(self, conn: Any, result: Any = None) -> None:
        lanes = self.lanes()
        for lane in lanes:
            conn.lane.setDisallowed(lane, list(self.disallow))
        if hasattr(result, "lanes_closed"):
            result.lanes_closed = tuple(lanes)
        _record_applied(result, self, {"lanes": list(lanes)})


@dataclass(frozen=True, kw_only=True)
class SpeedLimitRule(RuleSpec):
    """Set a maximum speed on one or more edges or lanes."""

    target_kind: str = "edge"
    target_ids: tuple[str, ...] = ()
    mps: float = 0.0

    def change_type(self) -> str:
        return "speed_limit"

    def payload(self) -> dict[str, Any]:
        return {
            "kind": "speed_limit",
            "target_kind": self.target_kind,
            "target_ids": list(self.target_ids),
            "mps": self.mps,
        }

    def validate(self, net_path: str | Path, *, episode_end_seconds: float = EPISODE_END_SECONDS) -> None:
        if self.target_kind not in _SPEED_TARGET_KINDS:
            raise RuleError(
                f"rule {self.rule_id!r}: target_kind must be one of {_SPEED_TARGET_KINDS}, "
                f"got {self.target_kind!r}"
            )
        if not self.target_ids:
            raise RuleError(f"rule {self.rule_id!r}: a speed limit must name at least one target")
        if not _finite(self.mps):
            raise RuleError(f"rule {self.rule_id!r}: speed must be a finite number, got {self.mps!r}")
        if self.mps <= 0:
            raise RuleError(f"rule {self.rule_id!r}: speed must be positive, got {self.mps!r}")
        super().validate(net_path, episode_end_seconds=episode_end_seconds)
        net = sumolib.net.readNet(str(net_path))
        known = _known_ids(net, self.target_kind)
        missing = sorted(t for t in self.target_ids if t not in known)
        if missing:
            raise RuleError(
                f"rule {self.rule_id!r}: unknown {self.target_kind} id(s) {missing} in "
                f"{Path(net_path).name}"
            )

    def apply(self, conn: Any, result: Any = None) -> None:
        for target in sorted(self.target_ids):
            if self.target_kind == "edge":
                conn.edge.setMaxSpeed(target, self.mps)
            else:
                conn.lane.setMaxSpeed(target, self.mps)
        _record_applied(result, self, {"target_kind": self.target_kind, "mps": self.mps})


@dataclass(frozen=True, kw_only=True)
class TrafficLightRule(RuleSpec):
    """Install a named traffic-light programme (optionally at a given phase)."""

    tls_id: str = ""
    program_id: str = ""
    phase_index: int | None = None

    def change_type(self) -> str:
        return "traffic_light_program"

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "kind": "traffic_light_program",
            "tls_id": self.tls_id,
            "program_id": self.program_id,
        }
        if self.phase_index is not None:
            payload["phase_index"] = self.phase_index
        return payload

    def validate(self, net_path: str | Path, *, episode_end_seconds: float = EPISODE_END_SECONDS) -> None:
        if not self.tls_id:
            raise RuleError(f"rule {self.rule_id!r}: a traffic-light rule must name a tls_id")
        if not self.program_id:
            raise RuleError(f"rule {self.rule_id!r}: a traffic-light rule must name a program_id")
        if self.phase_index is not None and (
            not isinstance(self.phase_index, int)
            or isinstance(self.phase_index, bool)
            or self.phase_index < 0
        ):
            raise RuleError(
                f"rule {self.rule_id!r}: phase_index must be a non-negative integer or None, "
                f"got {self.phase_index!r}"
            )
        super().validate(net_path, episode_end_seconds=episode_end_seconds)
        programs = _tls_programs(net_path)
        if self.tls_id not in programs:
            raise RuleError(f"rule {self.rule_id!r}: unknown traffic light id {self.tls_id!r}")
        if self.program_id not in programs[self.tls_id]:
            raise RuleError(
                f"rule {self.rule_id!r}: traffic light {self.tls_id!r} has no program "
                f"{self.program_id!r} (it declares {sorted(programs[self.tls_id])})"
            )

    def apply(self, conn: Any, result: Any = None) -> None:
        conn.trafficlight.setProgram(self.tls_id, self.program_id)
        if self.phase_index is not None:
            conn.trafficlight.setPhase(self.tls_id, self.phase_index)
        _record_applied(result, self, {"tls_id": self.tls_id, "program_id": self.program_id})


@dataclass(frozen=True, kw_only=True)
class DemandFlowRule(RuleSpec):
    """Insert a metered flow of vehicles from a source edge to a destination edge."""

    flow_id: str = ""
    from_edge: str = ""
    to_edge: str = ""
    vehicles_per_hour: float = 0.0
    depart_begin: float = 0.0
    depart_end: float = 0.0
    vtype: str = ""

    def change_type(self) -> str:
        return "demand_flow"

    def payload(self) -> dict[str, Any]:
        return {
            "kind": "demand_flow",
            "flow_id": self.flow_id,
            "from_edge": self.from_edge,
            "to_edge": self.to_edge,
            "vehicles_per_hour": self.vehicles_per_hour,
            "depart_begin": self.depart_begin,
            "depart_end": self.depart_end,
            "vtype": self.vtype,
        }

    def validate(self, net_path: str | Path, *, episode_end_seconds: float = EPISODE_END_SECONDS) -> None:
        if not self.flow_id:
            raise RuleError(f"rule {self.rule_id!r}: a flow must name a flow_id")
        if not self.vtype:
            raise RuleError(f"rule {self.rule_id!r}: a flow must name a vtype")
        for name, value in (
            ("vehicles_per_hour", self.vehicles_per_hour),
            ("depart_begin", self.depart_begin),
            ("depart_end", self.depart_end),
        ):
            if not _finite(value):
                raise RuleError(f"rule {self.rule_id!r}: {name} must be finite, got {value!r}")
        if self.vehicles_per_hour <= 0:
            raise RuleError(
                f"rule {self.rule_id!r}: vehicles_per_hour must be positive, got {self.vehicles_per_hour!r}"
            )
        if self.depart_begin < 0:
            raise RuleError(f"rule {self.rule_id!r}: depart_begin must not be negative")
        if self.depart_end < self.depart_begin:
            raise RuleError(
                f"rule {self.rule_id!r}: depart_end ({self.depart_end:g}s) is before "
                f"depart_begin ({self.depart_begin:g}s)"
            )
        super().validate(net_path, episode_end_seconds=episode_end_seconds)
        net = sumolib.net.readNet(str(net_path))
        known = {e.getID() for e in net.getEdges()}
        for which, eid in (("from_edge", self.from_edge), ("to_edge", self.to_edge)):
            if not eid or eid not in known:
                raise RuleError(f"rule {self.rule_id!r}: unknown {which} {eid!r}")
        if not _edge_reachable(net, self.from_edge, self.to_edge):
            raise RuleError(
                f"rule {self.rule_id!r}: no route from {self.from_edge!r} to {self.to_edge!r} "
                f"in {Path(net_path).name}"
            )

    # --- deterministic schedule (never random, never clock-dependent) ---

    def period_seconds(self) -> float:
        """The even-spacing interval implied by the declared rate."""
        if not _finite(self.vehicles_per_hour) or self.vehicles_per_hour <= 0:
            raise RuleError(
                f"rule {self.rule_id!r}: vehicles_per_hour must be positive and finite to "
                "derive a schedule"
            )
        return 3600.0 / self.vehicles_per_hour

    def vehicle_count(self) -> int:
        """How many vehicles the rate and window admit. Arithmetic, nothing else."""
        span = self.depart_end - self.depart_begin
        if span <= 0:
            return 0
        return int(math.floor(span / self.period_seconds()))

    def vehicle_ids(self) -> tuple[str, ...]:
        """`flow_id + '.' + index`, indexed from zero, in departure order."""
        return tuple(f"{self.flow_id}.{i}" for i in range(self.vehicle_count()))

    def departures(self) -> tuple[tuple[str, float], ...]:
        """(vehicle id, departure second) pairs, evenly spaced from depart_begin."""
        period = self.period_seconds()
        return tuple(
            (f"{self.flow_id}.{i}", self.depart_begin + i * period)
            for i in range(self.vehicle_count())
        )

    def apply(self, conn: Any, result: Any = None) -> None:
        conn.route.add(self.flow_id, [self.from_edge, self.to_edge])
        scheduled = self.departures()
        for veh_id, depart in scheduled:
            conn.vehicle.add(veh_id, self.flow_id, typeID=self.vtype, depart=depart)
        _record_applied(
            result, self, {"flow_id": self.flow_id, "vehicles": [v for v, _ in scheduled]}
        )


# --- set-level consistency ------------------------------------------------


def _check_closure_speed(closure: ClosureRule, speed: SpeedLimitRule) -> None:
    if speed.target_kind == "edge":
        speed_edges = set(speed.target_ids)
    else:
        speed_edges = {_lane_edge_id(t) for t in speed.target_ids}
    shared = sorted(set(closure.edge_ids) & speed_edges)
    if shared:
        raise RuleError(
            f"contradictory rules: {closure.rule_id!r} closes edge(s) {shared} while "
            f"{speed.rule_id!r} sets a speed limit on the same edge(s)"
        )


def _check_speed_speed(a: SpeedLimitRule, b: SpeedLimitRule) -> None:
    if a.target_kind != b.target_kind:
        return
    shared = sorted(set(a.target_ids) & set(b.target_ids))
    if shared:
        raise RuleError(
            f"contradictory rules: {a.rule_id!r} and {b.rule_id!r} both set a speed limit "
            f"on {a.target_kind}(s) {shared}"
        )


def _check_tls_tls(a: TrafficLightRule, b: TrafficLightRule) -> None:
    if a.tls_id == b.tls_id and a.at_second == b.at_second:
        raise RuleError(
            f"contradictory rules: {a.rule_id!r} and {b.rule_id!r} both install a program on "
            f"traffic light {a.tls_id!r} at {a.at_second:g}s"
        )


def validate_rule_set(rules: Iterable[RuleSpec]) -> None:
    """Refuse a set of rules that contradict each other. Names BOTH rule ids.

    Compatible rules (different targets, or sequential programmes on one light)
    pass. This is a set-level check only; it never reads a net file and never
    runs a simulation -- call each rule's `validate(net_path)` for that.
    """
    items = list(rules)
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if isinstance(a, ClosureRule) and isinstance(b, SpeedLimitRule):
                _check_closure_speed(a, b)
            elif isinstance(b, ClosureRule) and isinstance(a, SpeedLimitRule):
                _check_closure_speed(b, a)
            if isinstance(a, SpeedLimitRule) and isinstance(b, SpeedLimitRule):
                _check_speed_speed(a, b)
            if isinstance(a, TrafficLightRule) and isinstance(b, TrafficLightRule):
                _check_tls_tls(a, b)
