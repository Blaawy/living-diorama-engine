"""The episode brief: the ONE thing a person gives the factory.

    {"schema_version": "episode_brief_v1",
     "episode_number": 1,
     "title": "What happens when one street closes?",
     "world": "riverside",
     "statement": "Close one block of Baker Avenue to cars.",
     "rule": {"kind": "close_street", "edge": "B1B2", "at_second": 30},
     "prediction": {"text": "Car trips will take longer.",
                    "metric": "avg_duration_s", "direction": "increase"},
     "seed": 20260903, "end_seconds": 1500,
     "declared_utc": "2026-10-03T00:00:00Z"}

Everything else has a default. The brief is closed: an unknown key is refused,
because a brief that silently ignores a misspelt field runs a different episode
from the one that was asked for.

A brief becomes a sealed `rule_manifest_v2` (the Phase 3 contract, unchanged)
and a `ldyf.rules.RuleSpec`. The prediction is carried into the manifest with
`declared_before_run: true`, which is what makes the later "we expected X, the
city did Y" honest: the expectation is hashed before the simulator starts.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .. import rules as R
from ..evidence import seal_rule_manifest
from . import FactoryError
from .util import canonical_bytes, sha256_bytes

BRIEF_SCHEMA = "episode_brief_v1"

_DEFAULTS: dict[str, Any] = {
    "episode_number": 1,
    "seed": 20260903,
    "end_seconds": 1500.0,
    "target_seconds": [480.0, 600.0],
    "fps": 24,
    "resolution": [1920, 1080],
    "voice": "Microsoft Zira Desktop",
    "voice_rate": -1,
    "replicate_seeds": [],
    "declared_utc": "2026-10-03T00:00:00Z",
}
_REQUIRED = ("schema_version", "title", "world", "statement", "rule", "prediction")
_ALLOWED = set(_REQUIRED) | set(_DEFAULTS)

#: brief rule kind -> (rule_manifest change block, required fields)
RULE_KINDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "close_street": ("close_edges", ("edge", "at_second")),
    "speed_limit": ("speed_limit", ("edge", "mps", "at_second")),
    "traffic_light": ("tls_program", ("tls_id", "program_id", "at_second")),
    "demand_flow": ("demand_flow", ("from_edge", "to_edge", "vehicles_per_hour",
                                    "depart_begin", "depart_end", "at_second")),
}
_OPTIONAL_RULE_FIELDS = {"traffic_light": ("phase_index",), "demand_flow": ("flow_id", "vtype")}
PREDICTION_DIRECTIONS = ("increase", "decrease", "no_change")


class BriefError(FactoryError):
    stage = "brief"


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def normalise_brief(raw: Any) -> dict[str, Any]:
    """Validate a brief and fill its defaults. Deterministic; refuses, never guesses."""
    if not isinstance(raw, dict):
        raise BriefError("not_an_object", "a brief is a JSON object")
    if raw.get("schema_version") != BRIEF_SCHEMA:
        raise BriefError("bad_version", f"brief declares {raw.get('schema_version')!r}, "
                                        f"this factory reads {BRIEF_SCHEMA}")
    unknown = sorted(set(raw) - _ALLOWED)
    if unknown:
        raise BriefError("unknown_field", f"brief carries unknown field(s) {unknown}")
    missing = [k for k in _REQUIRED if k not in raw]
    if missing:
        raise BriefError("missing_field", f"brief is missing {missing}")
    b = {**_DEFAULTS, **raw}

    for k in ("title", "world", "statement"):
        if not isinstance(b[k], str) or not b[k].strip():
            raise BriefError("bad_field", f"brief.{k} must be a non-empty string")
    if not (3 <= len(b["title"]) <= 200):
        raise BriefError("bad_field", "brief.title must be 3..200 characters")
    for k in ("title", "statement", "world"):
        if any(ord(c) < 32 or ord(c) == 127 for c in b[k]):
            raise BriefError("bad_field", f"brief.{k} must not contain control characters")
    if not (3 <= len(b["statement"]) <= 240):
        raise BriefError("bad_field", "brief.statement must be 3..240 characters")
    if not isinstance(b["episode_number"], int) or isinstance(b["episode_number"], bool) \
            or b["episode_number"] < 0:
        raise BriefError("bad_field", "brief.episode_number must be a non-negative integer")
    if not isinstance(b["seed"], int) or isinstance(b["seed"], bool):
        raise BriefError("bad_field", "brief.seed must be an integer")
    if not _num(b["end_seconds"]) or b["end_seconds"] <= 0:
        raise BriefError("bad_field", "brief.end_seconds must be a positive number")
    b["end_seconds"] = float(b["end_seconds"])
    ts = b["target_seconds"]
    if (not isinstance(ts, list) or len(ts) != 2 or not all(_num(x) for x in ts)
            or not 0 < ts[0] <= ts[1]):
        raise BriefError("bad_field", "brief.target_seconds must be [min, max], 0 < min <= max")
    b["target_seconds"] = [float(ts[0]), float(ts[1])]
    if not isinstance(b["fps"], int) or isinstance(b["fps"], bool) or not 1 <= b["fps"] <= 120:
        raise BriefError("bad_field", "brief.fps must be an integer 1..120")
    res = b["resolution"]
    if (not isinstance(res, list) or len(res) != 2
            or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 16 for x in res)):
        raise BriefError("bad_field", "brief.resolution must be [width, height] integers")
    if not isinstance(b["voice"], str) or not b["voice"].strip():
        raise BriefError("bad_field", "brief.voice must be a non-empty string")
    if not isinstance(b["voice_rate"], int) or isinstance(b["voice_rate"], bool) \
            or not -10 <= b["voice_rate"] <= 10:
        raise BriefError("bad_field", "brief.voice_rate must be an integer -10..10")
    rs = b["replicate_seeds"]
    if not isinstance(rs, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in rs):
        raise BriefError("bad_field", "brief.replicate_seeds must be a list of integers")
    if len(set(rs)) != len(rs) or b["seed"] in rs:
        raise BriefError("bad_field", "brief.replicate_seeds must be distinct and differ from seed")
    try:
        if not isinstance(b["declared_utc"], str) or len(b["declared_utc"]) != 20:
            raise ValueError
        datetime.strptime(b["declared_utc"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise BriefError("bad_field", "brief.declared_utc must be a UTC time like 2026-10-03T00:00:00Z")

    rule = b["rule"]
    if not isinstance(rule, dict) or not isinstance(rule.get("kind"), str) \
            or rule["kind"] not in RULE_KINDS:
        raise BriefError("bad_rule", f"brief.rule.kind must be one of {sorted(RULE_KINDS)}")
    kind = rule["kind"]
    need = RULE_KINDS[kind][1]
    allowed = set(need) | {"kind"} | set(_OPTIONAL_RULE_FIELDS.get(kind, ()))
    extra = sorted(set(rule) - allowed)
    if extra:
        raise BriefError("bad_rule", f"brief.rule ({kind}) carries unknown field(s) {extra}")
    lacking = [k for k in need if k not in rule]
    if lacking:
        raise BriefError("bad_rule", f"brief.rule ({kind}) is missing {lacking}")
    if not _num(rule["at_second"]) or rule["at_second"] < 0:
        raise BriefError("bad_rule", "brief.rule.at_second must be a non-negative number")
    if rule["at_second"] >= b["end_seconds"]:
        raise BriefError("bad_rule", "brief.rule.at_second is not before end_seconds: "
                                     "the rule would never take effect")
    b["rule"] = dict(rule)

    pred = b["prediction"]
    if not isinstance(pred, dict) or set(pred) != {"text", "metric", "direction"}:
        raise BriefError("bad_prediction", "brief.prediction must be exactly {text, metric, direction}")
    if not isinstance(pred["text"], str) or not 3 <= len(pred["text"]) <= 500:
        raise BriefError("bad_prediction", "brief.prediction.text must be 3..500 characters")
    if pred["direction"] not in PREDICTION_DIRECTIONS:
        raise BriefError("bad_prediction",
                         f"brief.prediction.direction must be one of {PREDICTION_DIRECTIONS}")
    if not isinstance(pred["metric"], str) or not pred["metric"]:
        raise BriefError("bad_prediction", "brief.prediction.metric must name a measured metric")
    _check_prediction_text(pred["text"], pred["direction"])
    b["prediction"] = dict(pred)
    return b


#: The prediction text is SPOKEN twice ("we wrote down a guess") and then judged right or wrong from
#: `direction` alone, so it must be exactly the guess that direction states and nothing else. Any free
#: text is a channel past the narration lint (a prediction line carries a check, which waives claim
#: words) and can name a different quantity than the one that is measured (a COUNT of trips, a walker's
#: time). So the text is chosen from a CLOSED set of sentences about the one measured quantity, the
#: average car trip time; a variant adds " on average". Anything else is refused rather than guessed at.
_PREDICTION_TEMPLATES: dict[str, tuple[str, ...]] = {
    "increase": ("Car trips will take longer.", "Car trips will take more time.", "Car trips will be longer.",
                 "Car trips will be slower."),
    "decrease": ("Car trips will take less time.", "Car trips will be shorter.", "Car trips will be faster."),
    "no_change": ("Car trips will stay the same.", "Car trips will take the same time.",
                  "There will be no change in car trips.", "No change in car trips."),
}


def prediction_sentences(direction: str) -> tuple[str, ...]:
    base = _PREDICTION_TEMPLATES.get(direction, ())
    return base + tuple(t[:-1] + " on average." for t in base)


def _check_prediction_text(text: str, direction: str) -> None:
    allowed = prediction_sentences(direction)
    if text not in allowed:
        others = [d for d in _PREDICTION_TEMPLATES if text in prediction_sentences(d)]
        why = (f"says {others[0]!r}, but brief.prediction.direction is {direction!r}" if others
               else "is not one of the guesses the factory can judge")
        raise BriefError("bad_prediction", f"brief.prediction.text {why}; for {direction!r} write exactly "
                                           f"one of {list(allowed)[:4]}")


def brief_hash(brief: dict[str, Any]) -> str:
    """Identity of a NORMALISED brief."""
    return sha256_bytes(canonical_bytes(brief))


def rule_id_for(brief: dict[str, Any]) -> str:
    """Content-derived rule id: same brief rule, same id, on any machine."""
    seed = canonical_bytes({"world": brief["world"], "episode_number": brief["episode_number"],
                            "rule": brief["rule"]})
    return "chg_" + sha256_bytes(seed)[:16]


def build_rule(brief: dict[str, Any]) -> R.RuleSpec:
    """The `ldyf.rules.RuleSpec` this brief asks for (not yet validated on a net)."""
    rule, rid = brief["rule"], rule_id_for(brief)
    at = float(rule["at_second"])
    kind = rule["kind"]
    try:
        if kind == "close_street":
            return R.ClosureRule(rule_id=rid, at_second=at, edge_ids=(str(rule["edge"]),))
        if kind == "speed_limit":
            return R.SpeedLimitRule(rule_id=rid, at_second=at, target_kind="edge",
                                    target_ids=(str(rule["edge"]),), mps=float(rule["mps"]))
        if kind == "traffic_light":
            return R.TrafficLightRule(rule_id=rid, at_second=at, tls_id=str(rule["tls_id"]),
                                      program_id=str(rule["program_id"]),
                                      phase_index=rule.get("phase_index"))
        if kind == "demand_flow":
            return R.DemandFlowRule(
                rule_id=rid, at_second=at, flow_id=str(rule.get("flow_id", "factoryflow")),
                from_edge=str(rule["from_edge"]), to_edge=str(rule["to_edge"]),
                vehicles_per_hour=float(rule["vehicles_per_hour"]),
                depart_begin=float(rule["depart_begin"]), depart_end=float(rule["depart_end"]),
                vtype=str(rule.get("vtype", "DEFAULT_VEHTYPE")))
    except (R.RuleError, ValueError, TypeError) as e:
        raise BriefError("bad_rule", f"the rule cannot be built: {e}")
    raise BriefError("bad_rule", f"unknown rule kind {kind!r}")


def build_rule_manifest(brief: dict[str, Any], rule: R.RuleSpec) -> dict[str, Any]:
    """The sealed `rule_manifest_v2` for this brief's ONE rule."""
    block = RULE_KINDS[brief["rule"]["kind"]][0]
    payload = dict(rule.payload())
    payload.pop("kind", None)
    if block == "tls_program":
        payload.pop("phase_index", None)   # an apply-time detail the manifest does not carry
    doc = {
        "schema_version": "rule_manifest_v2",
        "rule_id": rule.rule_id,
        "episode_number": brief["episode_number"],
        "declared_utc": brief["declared_utc"],
        "statement": brief["statement"],
        "change": {block: payload},
        "applies_at_sim_second": float(rule.at_second),
        "baseline_required": True,
        "prediction": {"text": brief["prediction"]["text"], "declared_before_run": True,
                       "direction": brief["prediction"]["direction"],
                       "metric": brief["prediction"]["metric"]},
        "manifest_hash": "",
    }
    try:
        return seal_rule_manifest(doc)
    except Exception as e:  # noqa: BLE001
        raise BriefError("bad_rule", f"the rule manifest is refused by the Phase 3 contract: {e}")
