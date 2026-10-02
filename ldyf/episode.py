"""EPISODES HAVE NAMES -- stable identity, a typed event log, and lineage.

This module is the layer between the world state (``ldyf.world_state``) and the
rest of the pipeline. It answers three questions, and only those:

1. **Who is this?** Every world, episode, event and agent gets an identity that
   is *derived from its content*, never assigned by a counter or a clock. The
   same net hash, the same route hashes, the same seed and the same rule order
   must give the same string on any machine, in any process, forever. A
   content-derived id is the structural fix for "the manifest on disk is not the
   manifest that was reviewed": change one byte of the identity inputs and the
   id changes with it.

2. **What happened?** An episode carries an append-only, *typed* event log. The
   set of event kinds is closed, and every payload is a fixed-shape record of
   identifiers, hashes, closed-set codes and finite numbers. **There is no
   free-text field anywhere in an event** -- prose belongs in a claim or a
   limitation, both of which are auditable, and never in the machine record that
   the lineage is hashed over.

3. **Did this descend from that?** ``verify_episode_lineage`` walks an ordered
   chain of sealed manifests and refuses a reordered chain, a gap, a broken
   parent pointer, a foreign world, or a manifest whose ``state_hash`` no longer
   matches its own bytes.

Single serialisation
--------------------
The bytes hashed here are exactly ``ldyf.world_state.canonical_bytes`` -- the
one canonical form. This module does **not** define a second serialisation: a
seed document is passed through ``canonical_bytes`` and the digest truncated to
16 hex, matching the id style of ``ldyf.persistent_changes.make_change_id``.
Sealing a manifest is delegated to ``ldyf.world_state.seal``.

The outputs of an episode are bound to it by sha256 of their bytes, but those
bytes live on disk and are *not* inside the manifest that hashes itself. That is
deliberate: ``verify_outputs`` is the separate step that catches a file edited
after the manifest was sealed.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any

from .world_state import ChainError, canonical_bytes, seal, verify_or_raise

__all__ = [
    "EpisodeError",
    "SCHEMA_VERSION",
    "EPISODE_EVENTS_SCHEMA_VERSION",
    "EVENT_KINDS",
    "BLOCK_REASON_CODES",
    "make_world_id",
    "make_episode_id",
    "make_event_id",
    "make_agent_id",
    "episode_inputs",
    "episode_inputs_digest",
    "new_episode_manifest",
    "new_event_log",
    "append_event",
    "verify_outputs",
    "verify_episode_lineage",
]

SCHEMA_VERSION = "episode_v1"
EPISODE_EVENTS_SCHEMA_VERSION = "episode_events_v1"
ID_HEX_CHARS = 16

# The closed set of event kinds. Nothing outside this tuple is an event.
EVENT_KINDS = (
    "rule_applied",
    "agent_replanned",
    "agent_goal_reached",
    "agent_blocked",
    "vehicle_rerouted",
    "simulation_started",
    "simulation_ended",
)

# Closed code sets: an event explains WHY with a code, never with free prose.
BLOCK_REASON_CODES = (
    "closed_edge",
    "traffic",
    "incident",
    "signal",
    "crowd_pressure",
)

class EpisodeError(ChainError):
    """Raised when an episode's identity, events or lineage are invalid.

    Subclasses ``ldyf.world_state.ChainError`` so a caller may catch either the
    general chain failure or the episode-specific one.
    """


# --- field grammars -------------------------------------------------------

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_WORLD_ID = re.compile(r"^wld_[0-9a-f]{16}$")
_EPISODE_ID = re.compile(r"^ep_[0-9a-f]{16}$")
_EVENT_ID = re.compile(r"^evt_[0-9a-f]{16}$")
_AGENT_ID = re.compile(r"^agt_[0-9a-f]{16}$")
# Identifiers: net/edge/route/agent/rule/vehicle keys. No whitespace, no prose.
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

# Per-kind payload shape. Every key is required, nothing else is permitted,
# and each value is checked against one of the typed grammars in _check_field.
_EVENT_SCHEMAS: dict[str, dict[str, str]] = {
    "rule_applied": {"rule_id": "identifier", "change_id": "identifier"},
    "agent_replanned": {"agent_id": "identifier", "destination_edge": "identifier"},
    "agent_goal_reached": {"agent_id": "identifier", "destination_edge": "identifier"},
    "agent_blocked": {
        "agent_id": "identifier",
        "edge_id": "identifier",
        "reason_code": "block_reason",
    },
    "vehicle_rerouted": {
        "vehicle_id": "identifier",
        "from_route_sha256": "hex64",
        "to_route_sha256": "hex64",
    },
    "simulation_started": {"seed": "int", "end_seconds": "positive", "step_length": "positive"},
    "simulation_ended": {"sim_seconds": "non_negative", "steps_completed": "int"},
}

_REQUIRED_INPUT_FIELDS = (
    "net_sha256",
    "route_sha256",
    "seed",
    "end_seconds",
    "step_length",
    "rule_ids",
)


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _require_hex64(x: Any, what: str) -> str:
    if not isinstance(x, str) or not _HEX64.match(x):
        raise EpisodeError(f"{what} must be a 64-character lowercase hex sha256, got {x!r}")
    return x


def _require_hex64_list(x: Any, what: str) -> list[str]:
    if not isinstance(x, (list, tuple)):
        raise EpisodeError(f"{what} must be a list of sha256, got {type(x).__name__}")
    return [_require_hex64(v, f"{what}[{i}]") for i, v in enumerate(x)]


def _require_identifier(x: Any, what: str) -> str:
    if not isinstance(x, str) or not _IDENTIFIER.match(x):
        raise EpisodeError(f"{what} must be an identifier string, got {x!r}")
    return x


def _require_identifier_list(x: Any, what: str) -> list[str]:
    if not isinstance(x, (list, tuple)):
        raise EpisodeError(f"{what} must be a list of identifiers, got {type(x).__name__}")
    return [_require_identifier(v, f"{what}[{i}]") for i, v in enumerate(x)]


def _require_world_id(x: Any, what: str = "world_id") -> str:
    if not isinstance(x, str) or not _WORLD_ID.match(x):
        raise EpisodeError(f"{what} must be 'wld_' + 16 lowercase hex chars, got {x!r}")
    return x


def _require_episode_id(x: Any, what: str = "episode_id") -> str:
    if not isinstance(x, str) or not _EPISODE_ID.match(x):
        raise EpisodeError(f"{what} must be 'ep_' + 16 lowercase hex chars, got {x!r}")
    return x


def _require_event_kind(kind: Any) -> str:
    if kind not in EVENT_KINDS:
        raise EpisodeError(f"unknown event kind {kind!r}; allowed kinds are {list(EVENT_KINDS)}")
    return kind


# --- identity -------------------------------------------------------------


def _id_from_bytes(prefix: str, payload: bytes) -> str:
    """prefix + first 16 hex of sha256(payload). The convention, in one place."""
    return prefix + hashlib.sha256(payload).hexdigest()[:ID_HEX_CHARS]


def _make_id(prefix: str, seed: dict[str, Any]) -> str:
    """prefix + first 16 hex of sha256 over the ONE canonical serialisation."""
    return _id_from_bytes(prefix, canonical_bytes(seed))


def make_world_id(name: str) -> str:
    """The identity of a world, derived only from its name."""
    if not isinstance(name, str) or not name:
        raise EpisodeError(f"world name must be a non-empty string, got {name!r}")
    return _make_id("wld_", {"name": name})


def _validate_inputs(inputs: Any) -> None:
    if not isinstance(inputs, dict):
        raise EpisodeError(f"inputs must be an object, got {type(inputs).__name__}")
    missing = [f for f in _REQUIRED_INPUT_FIELDS if f not in inputs]
    if missing:
        raise EpisodeError(f"inputs is missing required field(s) {missing}")
    _require_hex64(inputs["net_sha256"], "inputs.net_sha256")
    _require_hex64_list(inputs["route_sha256"], "inputs.route_sha256")
    if not _is_int(inputs["seed"]):
        raise EpisodeError(f"inputs.seed must be an integer, got {inputs['seed']!r}")
    if not _is_num(inputs["end_seconds"]) or inputs["end_seconds"] <= 0:
        raise EpisodeError(f"inputs.end_seconds must be a finite positive number, got {inputs['end_seconds']!r}")
    if not _is_num(inputs["step_length"]) or inputs["step_length"] <= 0:
        raise EpisodeError(f"inputs.step_length must be a finite positive number, got {inputs['step_length']!r}")
    _require_identifier_list(inputs["rule_ids"], "inputs.rule_ids")


def episode_inputs_digest(
    *,
    net_sha256: str,
    route_sha256: list[str],
    seed: int,
    end_seconds: float,
    step_length: float,
    rule_ids: list[str],
) -> str:
    """The 64-hex digest over every experiment input, order included.

    Covers the net hash, the ORDERED route hashes, the seed, end_seconds,
    step_length, and the ORDERED rule ids. Reordering a route or a rule changes
    the digest; that is the point -- two experiments that differ only in order
    are not the same experiment.
    """
    _require_hex64(net_sha256, "net_sha256")
    routes = _require_hex64_list(route_sha256, "route_sha256")
    if not _is_int(seed):
        raise EpisodeError(f"seed must be an integer, got {seed!r}")
    if not _is_num(end_seconds) or end_seconds <= 0:
        raise EpisodeError(f"end_seconds must be a finite positive number, got {end_seconds!r}")
    if not _is_num(step_length) or step_length <= 0:
        raise EpisodeError(f"step_length must be a finite positive number, got {step_length!r}")
    rules = _require_identifier_list(rule_ids, "rule_ids")
    return hashlib.sha256(
        canonical_bytes(
            {
                "net_sha256": net_sha256,
                "route_sha256": routes,
                "seed": seed,
                "end_seconds": end_seconds,
                "step_length": step_length,
                "rule_ids": rules,
            }
        )
    ).hexdigest()


def episode_inputs(
    *,
    net_sha256: str,
    route_sha256: list[str],
    seed: int,
    end_seconds: float,
    step_length: float,
    rule_ids: list[str],
) -> dict[str, Any]:
    """Build the ``inputs`` block, digest included."""
    digest = episode_inputs_digest(
        net_sha256=net_sha256,
        route_sha256=route_sha256,
        seed=seed,
        end_seconds=end_seconds,
        step_length=step_length,
        rule_ids=rule_ids,
    )
    return {
        "net_sha256": net_sha256,
        "route_sha256": list(route_sha256),
        "seed": seed,
        "end_seconds": end_seconds,
        "step_length": step_length,
        "rule_ids": list(rule_ids),
        "inputs_digest": digest,
    }


def make_episode_id(world_id: str, episode_number: int, inputs: dict[str, Any]) -> str:
    """The identity of an episode: its world, its number and its inputs."""
    _require_world_id(world_id)
    if not _is_int(episode_number) or episode_number < 0:
        raise EpisodeError(f"episode_number must be a non-negative integer, got {episode_number!r}")
    _validate_inputs(inputs)
    return _make_id(
        "ep_",
        {"world_id": world_id, "episode_number": episode_number, "inputs": inputs},
    )


def make_event_id(episode_id: str, kind: str, seq: int, payload: dict[str, Any]) -> str:
    """The identity of an event: its episode, its kind, its seq and its payload."""
    _require_episode_id(episode_id)
    _require_event_kind(kind)
    if not _is_int(seq) or seq < 0:
        raise EpisodeError(f"seq must be a non-negative integer, got {seq!r}")
    _validate_event_payload(kind, payload)
    return _make_id(
        "evt_",
        {"episode_id": episode_id, "kind": kind, "seq": seq, "payload": payload},
    )


def make_agent_id(world_id: str, kind: str, key: str) -> str:
    """The identity of an agent within a world: its kind and its natural key."""
    _require_world_id(world_id)
    _require_identifier(kind, "kind")
    _require_identifier(key, "key")
    return _make_id("agt_", {"world_id": world_id, "kind": kind, "key": key})


# --- the typed event log --------------------------------------------------


def _check_field(kind: str, field: str, spec: str, value: Any) -> None:
    where = f"event {kind!r} payload field {field!r}"
    if spec == "identifier":
        _require_identifier(value, where)
    elif spec == "hex64":
        _require_hex64(value, where)
    elif spec == "int":
        if not _is_int(value) or value < 0:
            raise EpisodeError(f"{where} must be a non-negative integer, got {value!r}")
    elif spec == "positive":
        if not _is_num(value) or value <= 0:
            raise EpisodeError(f"{where} must be a finite positive number, got {value!r}")
    elif spec == "non_negative":
        if not _is_num(value) or value < 0:
            raise EpisodeError(f"{where} must be a finite non-negative number, got {value!r}")
    elif spec == "block_reason":
        if value not in BLOCK_REASON_CODES:
            raise EpisodeError(f"{where} must be one of {list(BLOCK_REASON_CODES)}, got {value!r}")
    else:  # pragma: no cover - a schema typo, not a caller error
        raise AssertionError(f"unknown field spec {spec!r}")


def _validate_event_payload(kind: str, payload: Any) -> None:
    """A payload is a closed record. Extra keys are free text by another name."""
    schema = _EVENT_SCHEMAS[kind]
    if not isinstance(payload, dict):
        raise EpisodeError(
            f"event {kind!r} payload must be an object, got {type(payload).__name__}"
        )
    keys = set(payload)
    expected = set(schema)
    if keys != expected:
        raise EpisodeError(
            f"event {kind!r} payload must have exactly the fields {sorted(expected)}; "
            f"missing={sorted(expected - keys)} unexpected={sorted(keys - expected)}"
        )
    for field, spec in schema.items():
        _check_field(kind, field, spec, payload[field])


def new_event_log(episode_id: str) -> dict[str, Any]:
    """An empty append-only event log for one episode."""
    _require_episode_id(episode_id)
    return {
        "schema_version": EPISODE_EVENTS_SCHEMA_VERSION,
        "episode_id": episode_id,
        "events": [],
    }


def _make_event(episode_id: str, kind: str, seq: int, payload: dict[str, Any]) -> dict[str, Any]:
    _require_event_kind(kind)
    _validate_event_payload(kind, payload)
    return {
        "event_id": make_event_id(episode_id, kind, seq, payload),
        "kind": kind,
        "seq": seq,
        "payload": payload,
    }


def append_event(
    log: dict[str, Any], *, kind: str, seq: int, payload: dict[str, Any]
) -> dict[str, Any]:
    """Return a NEW log with one event appended. The input log is not mutated.

    There is no edit path and no delete path: the only way to change a log is to
    append to it. ``seq`` must strictly increase, so a duplicate or an
    out-of-order append is refused rather than silently reordered.
    """
    if not isinstance(log, dict):
        raise EpisodeError(f"event log must be an object, got {type(log).__name__}")
    episode_id = _require_episode_id(log.get("episode_id"), "log.episode_id")
    events = log.get("events")
    if not isinstance(events, list):
        raise EpisodeError("event log must carry an 'events' list")
    if not _is_int(seq) or seq < 0:
        raise EpisodeError(f"seq must be a non-negative integer, got {seq!r}")
    if events:
        last_seq = events[-1].get("seq") if isinstance(events[-1], dict) else None
        if not _is_int(last_seq):
            raise EpisodeError("the last event in the log has a malformed seq")
        if seq == last_seq:
            raise EpisodeError(f"duplicate seq {seq}: an event with this seq is already in the log")
        if seq < last_seq:
            raise EpisodeError(f"seq must strictly increase within an episode: {last_seq} -> {seq}")

    event = _make_event(episode_id, kind, seq, payload)
    if any(isinstance(e, dict) and e.get("event_id") == event["event_id"] for e in events):
        raise EpisodeError(f"duplicate event {event['event_id']}")

    out = dict(log)
    out["events"] = list(events) + [event]
    return out


def _normalise_event_list(episode_id: str, events: Any) -> list[dict[str, Any]]:
    """Validate a manifest's events and re-derive every event id."""
    if not isinstance(events, (list, tuple)):
        raise EpisodeError(f"events must be a list, got {type(events).__name__}")
    out: list[dict[str, Any]] = []
    last_seq: int | None = None
    for e in events:
        if not isinstance(e, dict) or set(e) != {"event_id", "kind", "seq", "payload"}:
            raise EpisodeError(
                "every event must be exactly {event_id, kind, seq, payload}"
            )
        _require_event_kind(e["kind"])
        if not _is_int(e["seq"]) or e["seq"] < 0:
            raise EpisodeError(f"event seq must be a non-negative integer, got {e['seq']!r}")
        if last_seq is not None and e["seq"] <= last_seq:
            raise EpisodeError(f"event seq must strictly increase: {last_seq} -> {e['seq']}")
        _validate_event_payload(e["kind"], e["payload"])
        expected = make_event_id(episode_id, e["kind"], e["seq"], e["payload"])
        if e["event_id"] != expected:
            raise EpisodeError(
                f"event {e['seq']} id {e['event_id']!r} does not match its content ({expected})"
            )
        last_seq = e["seq"]
        out.append(dict(e))
    return out


# --- outputs --------------------------------------------------------------


def _check_output_path(path: Any, where: str) -> str:
    if not isinstance(path, str) or not path:
        raise EpisodeError(f"{where} must be a non-empty relative path, got {path!r}")
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts:
        raise EpisodeError(f"{where} must be relative and traversal-free, got {path!r}")
    return path


def _normalise_outputs(outputs: Any) -> list[dict[str, Any]]:
    if not isinstance(outputs, (list, tuple)):
        raise EpisodeError(f"outputs must be a list, got {type(outputs).__name__}")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for o in outputs:
        if not isinstance(o, dict) or set(o) != {"path", "sha256"}:
            raise EpisodeError("every output must be exactly {path, sha256}")
        path = _check_output_path(o["path"], "outputs[].path")
        digest = _require_hex64(o["sha256"], f"outputs[{path}].sha256")
        if path in seen:
            raise EpisodeError(f"duplicate output path {path!r}")
        seen.add(path)
        out.append({"path": path, "sha256": digest})
    return out


def verify_outputs(manifest: dict[str, Any], base_dir: str | Path) -> bool:
    """Re-open every file the manifest claims and check its bytes.

    The manifest's own ``state_hash`` covers the *recorded* sha256, not the
    bytes on disk. This is the step that catches a file edited after sealing.
    """
    if not isinstance(manifest, dict):
        raise EpisodeError("manifest must be an object")
    outputs = _normalise_outputs(manifest.get("outputs"))
    base = Path(base_dir)
    for o in outputs:
        target = base / o["path"]
        if not target.is_file():
            raise EpisodeError(f"recorded output {o['path']!r} is missing under {base}")
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != o["sha256"]:
            raise EpisodeError(
                f"output {o['path']!r} does not match the manifest: "
                f"on disk {actual}, sealed {o['sha256']}"
            )
    return True


# --- the manifest ---------------------------------------------------------


def _require_subsequence(sub: list[str], full: list[str], what: str) -> None:
    it = iter(full)
    for x in sub:
        for y in it:
            if y == x:
                break
        else:
            raise EpisodeError(
                f"{what} contains {x!r}, which is not among the episode's input rule ids"
            )


def new_episode_manifest(
    *,
    world_id: str,
    episode_number: int,
    parent_episode_id: str | None = None,
    net_sha256: str,
    route_sha256: list[str],
    seed: int,
    end_seconds: float,
    step_length: float,
    rule_ids: list[str],
    rules_applied: list[str] | None = None,
    events: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a SEALED episode manifest.

    ``parent_episode_id`` is null only for episode 0; every later episode must
    name the episode it inherited from. ``events`` and ``outputs`` are validated
    and re-derived, so a manifest cannot be constructed already carrying a
    forged event id or a duplicate output.
    """
    _require_world_id(world_id)
    if not _is_int(episode_number) or episode_number < 0:
        raise EpisodeError(f"episode_number must be a non-negative integer, got {episode_number!r}")
    if episode_number == 0:
        if parent_episode_id is not None:
            raise EpisodeError(
                "episode 0 is the root: parent_episode_id must be null, "
                f"got {parent_episode_id!r}"
            )
    else:
        _require_episode_id(parent_episode_id, "parent_episode_id")

    inputs = episode_inputs(
        net_sha256=net_sha256,
        route_sha256=route_sha256,
        seed=seed,
        end_seconds=end_seconds,
        step_length=step_length,
        rule_ids=rule_ids,
    )
    episode_id = make_episode_id(world_id, episode_number, inputs)

    if rules_applied is None:
        rules_applied = list(inputs["rule_ids"])
    rules_applied = _require_identifier_list(rules_applied, "rules_applied")
    _require_subsequence(rules_applied, inputs["rule_ids"], "rules_applied")

    doc = {
        "schema_version": SCHEMA_VERSION,
        "world_id": world_id,
        "episode_id": episode_id,
        "episode_number": episode_number,
        "parent_episode_id": parent_episode_id,
        "inputs": inputs,
        "rules_applied": rules_applied,
        "events": _normalise_event_list(episode_id, events if events is not None else []),
        "outputs": _normalise_outputs(outputs if outputs is not None else []),
        "state_hash": "",
    }
    return seal(doc)


# --- lineage --------------------------------------------------------------


def verify_episode_lineage(chain: list[dict[str, Any]]) -> None:
    """Verify a whole episode lineage, oldest first. Raises on any break.

    Refuses: an empty chain; a manifest whose ``state_hash`` no longer matches
    its bytes; a chain that does not start at episode 0; a gap in episode
    numbers; a reordered chain; a broken parent pointer; a foreign world.
    """
    if not isinstance(chain, (list, tuple)) or len(chain) == 0:
        raise EpisodeError("empty episode lineage")

    prev: dict[str, Any] | None = None
    for i, m in enumerate(chain):
        if not isinstance(m, dict):
            raise EpisodeError(f"episode {i} in the lineage is not a manifest object")
        number = m.get("episode_number")
        verify_or_raise(m, what=f"episode {number!r} manifest")
        if m.get("schema_version") != SCHEMA_VERSION:
            raise EpisodeError(
                f"episode {number!r} has schema_version {m.get('schema_version')!r}, "
                f"expected {SCHEMA_VERSION!r}"
            )
        world_id = _require_world_id(m.get("world_id"), "world_id")
        if not _is_int(number) or number < 0:
            raise EpisodeError(f"episode_number must be a non-negative integer, got {number!r}")
        expected_id = make_episode_id(world_id, number, m.get("inputs"))
        if m.get("episode_id") != expected_id:
            raise EpisodeError(
                f"episode {number} id {m.get('episode_id')!r} does not match its content "
                f"({expected_id})"
            )

        parent = m.get("parent_episode_id")
        if i == 0:
            if number != 0:
                raise EpisodeError(
                    f"an episode lineage must start at episode 0, not {number!r}"
                )
            if parent is not None:
                raise EpisodeError(
                    f"episode 0 must not name a parent episode, got {parent!r}"
                )
        else:
            assert prev is not None
            if number != prev["episode_number"] + 1:
                raise EpisodeError(
                    "episode numbers must increase by exactly one with no gaps: "
                    f"{prev['episode_number']} -> {number}"
                )
            if parent != prev.get("episode_id"):
                raise EpisodeError(
                    f"episode {number} names parent {parent!r}, but the preceding episode "
                    f"is {prev.get('episode_id')!r}"
                )
            if world_id != prev.get("world_id"):
                raise EpisodeError(
                    f"episode {number} belongs to world {world_id!r}, but its parent belongs "
                    f"to {prev.get('world_id')!r}"
                )
        prev = m
