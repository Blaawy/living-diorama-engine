"""StateResponsePlan V1: what the world's authoritative condition is, and what shows it.

Pure Python by design -- this module never imports ``bpy`` and never imports the
engine. Given one authoritative Render Export, the Master Scene Spec and the
Phase 20 presentation contract, it derives a deterministic, sorted,
source-traceable list of visual responses that can be inspected, hashed, diffed
and fully tested without Blender installed.

Three rules govern everything here:

    PRESENTATION READS, IT NEVER WRITES. Every response exists because an
    authoritative field says so, and carries the dotted path and the raw value it
    was read from, so a reader can open the export and check it.

    ONE FIELD, ONE CHANNEL. A response maps exactly one authoritative field. It
    never blends several into an index: the engine deliberately refuses to store
    the mean of fear and trust because "a stored average would be a third thing
    that could fall out of step with them", and a presentation layer inventing
    that same average one storey down would be the same mistake wearing a costume.

    READ THE FIELD, NEVER RECOMPUTE IT. ``district.scarcity`` is authoritative
    even where it disagrees with what recomputing it from the same world would
    give -- episode 0 of the canonical chain is hand-seeded, and a layer that
    recomputed would disagree with the engine on the frame that opens the series.

The envelope validator upstream is deliberately shallow: it accepts NaN, values
outside their declared domain, duplicate district identifiers and unsorted
arrays, because its scope is the envelope and the nested documents are governed
by the serializers that produced them. A file read off disk carries none of that
producer-side guarantee, so this module re-validates every district field it
reads and indexes by identity rather than trusting array order.
"""

import hashlib
import json
import math

from scene_spec import (
    SceneContractError,
    load_master_scene_spec,
    load_render_export,
    require_topology_agreement,
)
from state_response_spec import (
    DISTRICT_SCALARS,
    require_channel,
    response_value,
)

STATE_RESPONSE_PLAN_FORMAT = "living_diorama_state_response_plan"
STATE_RESPONSE_PLAN_SCHEMA_VERSION = 1

REPRESENTATION_STATEMENT = (
    "A response is a reading of authoritative world state, not a claim about a person. "
    "District air is that district's aggregate condition as the simulation recorded it; "
    "a record stone is one durable fact the engine itself decided to remember. Nothing here "
    "describes an individual, a household, a journey or a motive, and nothing here is read "
    "back into the simulation."
)

AIR_MATERIAL_PREFIX = "LD_SR_MAT__air_"
AIR_DENSITY_NODE = "LD_AirDensity"
AIR_DENSITY_SOCKET = "output:0"
RECORD_OBJECT_PREFIX = "LD_SR__record_stone_"

_DISTRICT_KEYS = frozenset(
    {
        "consumption_rate",
        "created_tick",
        "fear",
        "housing_capacity",
        "id",
        "institutional_pressure",
        "isolation_state",
        "population",
        "production_rate",
        "resources",
        "scarcity",
        "trust",
    }
)
_ISOLATION_STATES = frozenset({"OPEN", "PARTIAL", "ISOLATED"})
_RESOURCE_KINDS = frozenset({"ENERGY", "FOOD", "MATERIALS"})
_FACT_KEYS = ("episode", "fact_id", "fact_type", "tick")


class StateResponsePlanError(ValueError):
    """A Phase 20 plan-logic violation.

    Raised when an export cannot support a response the spec asks for, when a
    district document is malformed, and when a response would be empty or
    ambiguous. Always a refusal, never a repair.
    """


def _finite(value: object, description: str) -> float:
    """Return a finite real reading or refuse.

    Booleans are refused because ``True`` is not a magnitude, and non-finite
    values are refused because the envelope validator upstream lets ``NaN``
    through and a silent ``NaN`` would propagate into a hashed plan.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StateResponsePlanError(f"{description} must be a real number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise StateResponsePlanError(f"{description} must be finite, got {value!r}")
    return number


def _unit_reading(value: object, description: str) -> float:
    """Return a finite reading inside ``[0, 1]`` or refuse."""
    number = _finite(value, description)
    if not 0.0 <= number <= 1.0:
        raise StateResponsePlanError(
            f"{description} must lie in [0, 1], got {number!r}; the persistence layer "
            "validates it into that domain, so a reading outside it is a corrupted document"
        )
    return number


def _exact_int(value: object, description: str) -> int:
    """Return an exact non-negative integer or refuse."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise StateResponsePlanError(f"{description} must be an integer, got {value!r}")
    if value < 0:
        raise StateResponsePlanError(f"{description} must not be negative, got {value!r}")
    return value


def _require_districts(export: dict) -> dict:
    """Index the export's districts by identity, validating every field read.

    Returns:
        A mapping of district id to the district document.

    Raises:
        StateResponsePlanError: If a district is malformed, duplicated, or
            carries a field outside the domain the persistence layer enforces.
    """
    world = export.get("world")
    if not isinstance(world, dict):
        raise StateResponsePlanError("render export world must be a JSON object")
    entries = world.get("districts")
    if not isinstance(entries, list):
        raise StateResponsePlanError("render export world.districts must be a JSON array")
    if not entries:
        raise StateResponsePlanError(
            "render export declares no districts; an empty world has no condition to show"
        )
    districts: dict[str, dict] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise StateResponsePlanError(
                f"render export district [{index}] must be a JSON object, "
                f"got {type(entry).__name__}"
            )
        present = set(entry)
        missing = sorted(_DISTRICT_KEYS - present)
        if missing:
            raise StateResponsePlanError(f"render export district [{index}] is missing {missing}")
        unexpected = sorted(present - _DISTRICT_KEYS)
        if unexpected:
            raise StateResponsePlanError(
                f"render export district [{index}] declares unexpected keys {unexpected}; "
                "an unrecognised field is refused, never ignored"
            )
        district_id = entry["id"]
        if (
            not isinstance(district_id, str)
            or not district_id
            or district_id.strip() != district_id
        ):
            raise StateResponsePlanError(
                f"render export district [{index}] declares an unusable id {district_id!r}"
            )
        if district_id in districts:
            raise StateResponsePlanError(
                f"render export declares district {district_id!r} twice; "
                "identity is indexed, never taken from array order"
            )
        for field in DISTRICT_SCALARS:
            _unit_reading(entry[field], f"district {district_id!r} {field}")
        for field in ("created_tick", "housing_capacity", "population"):
            _exact_int(entry[field], f"district {district_id!r} {field}")
        for field in ("consumption_rate", "production_rate"):
            if _finite(entry[field], f"district {district_id!r} {field}") < 0.0:
                raise StateResponsePlanError(
                    f"district {district_id!r} {field} must not be negative"
                )
        if entry["isolation_state"] not in _ISOLATION_STATES:
            raise StateResponsePlanError(
                f"district {district_id!r} declares isolation_state "
                f"{entry['isolation_state']!r}; expected one of {sorted(_ISOLATION_STATES)}"
            )
        resources = entry["resources"]
        if not isinstance(resources, dict) or set(resources) != _RESOURCE_KINDS:
            carried = sorted(resources) if isinstance(resources, dict) else resources
            raise StateResponsePlanError(
                f"district {district_id!r} resources must carry exactly "
                f"{sorted(_RESOURCE_KINDS)}, got {carried!r}"
            )
        for kind, amount in sorted(resources.items()):
            if _finite(amount, f"district {district_id!r} resources[{kind}]") < 0.0:
                raise StateResponsePlanError(
                    f"district {district_id!r} resources[{kind}] must not be negative"
                )
        districts[district_id] = entry
    return districts


def _require_facts(export: dict) -> list[dict]:
    """Return the export's durable memory facts, validating the members read.

    Only structured members are read. ``summary`` is prose, and a layer that
    parsed it would be authoring meaning rather than reading it.
    """
    memory = export.get("memory")
    if not isinstance(memory, dict):
        raise StateResponsePlanError("render export memory must be a JSON object")
    entries = memory.get("facts")
    if not isinstance(entries, list):
        raise StateResponsePlanError("render export memory.facts must be a JSON array")
    facts: list[dict] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise StateResponsePlanError(
                f"memory fact [{index}] must be a JSON object, got {type(entry).__name__}"
            )
        for field in _FACT_KEYS:
            if field not in entry:
                raise StateResponsePlanError(f"memory fact [{index}] is missing {field!r}")
        fact_id = entry["fact_id"]
        fact_type = entry["fact_type"]
        for label, value in (("fact_id", fact_id), ("fact_type", fact_type)):
            if not isinstance(value, str) or not value.strip():
                raise StateResponsePlanError(
                    f"memory fact [{index}] declares an unusable {label} {value!r}"
                )
        if fact_id in seen:
            raise StateResponsePlanError(
                f"render export declares memory fact {fact_id!r} twice; a fact is remembered once"
            )
        seen.add(fact_id)
        facts.append(
            {
                "episode": _exact_int(entry["episode"], f"memory fact {fact_id!r} episode"),
                "fact_id": fact_id,
                "fact_type": fact_type,
                "tick": _exact_int(entry["tick"], f"memory fact {fact_id!r} tick"),
            }
        )
    return facts


def _provenance(export: dict) -> dict:
    """Record which verified episode a plan was derived from."""
    source = export.get("source")
    if not isinstance(source, dict):
        raise StateResponsePlanError("render export source must be a JSON object")
    return {
        "episode": source.get("episode"),
        "state_hash": source.get("state_hash"),
        "tick": source.get("tick"),
    }


def _air_response(
    policy: dict, district_id: str, district: dict, definition: dict, air: dict
) -> dict:
    """Build one district's air response from one authoritative field."""
    field = policy["source_field"]
    reading = _unit_reading(district[field], f"district {district_id!r} {field}")
    scale = response_value(policy, reading)
    density = round(air["base_density"] * scale, 9)
    centre = definition["center"]
    radius = round(float(definition["radius"]) + air["rim_margin_metres"], 6)
    return {
        "channel": policy["channel"],
        "semantic_id": district_id,
        "source_kind": policy["source_kind"],
        "source_field": field,
        "source_path": f"world.districts[{district_id}].{field}",
        "source_value": reading,
        "response_scale": scale,
        "value": density,
        "target": {
            "kind": "material_node_value",
            "material": f"{AIR_MATERIAL_PREFIX}{district_id}",
            "node": AIR_DENSITY_NODE,
            "socket": AIR_DENSITY_SOCKET,
        },
        "field": {
            "centre": [round(float(centre[0]), 6), round(float(centre[1]), 6)],
            "radius": radius,
            # The soft rim, as a fraction of the volume's own width, so the
            # shader stays correct however the box is scaled.
            "rim_fraction": round(air["rim_margin_metres"] / (2.0 * radius), 6),
            "floor": round(float(definition["elevation"]), 6),
            "ceiling": round(float(definition["elevation"]) + air["ceiling_metres"], 6),
        },
    }


def _record_response(policy: dict, fact: dict, slot: int, record: dict) -> dict:
    """Build one memory record stone from one durable fact."""
    angle = record["arc_start_degrees"] + record["arc_step_degrees"] * slot
    radians = math.radians(angle)
    origin = record["origin"]
    return {
        "channel": policy["channel"],
        "semantic_id": fact["fact_id"],
        "source_kind": policy["source_kind"],
        "source_field": policy["source_field"],
        "source_path": f"memory.facts[{fact['fact_id']}].{policy['source_field']}",
        "source_value": fact["fact_type"],
        "response_scale": 1.0,
        "value": 1.0,
        "target": {
            "kind": "object_presence",
            "object": f"{RECORD_OBJECT_PREFIX}{slot:03d}",
        },
        "field": {
            "slot": slot,
            "episode": fact["episode"],
            "tick": fact["tick"],
            "x": round(origin[0] + record["arc_radius_metres"] * math.cos(radians), 6),
            "y": round(origin[1] + record["arc_radius_metres"] * math.sin(radians), 6),
            "z": round(record["plaza_level_metres"] + record["lift_metres"], 6),
            "heading": round(radians, 6),
        },
    }


def _sort_key(response: dict) -> tuple:
    """Return a total order that no mapping's iteration order can disturb."""
    return (
        response["channel"],
        response["semantic_id"],
        json.dumps(response["target"], sort_keys=True),
    )


def plan_state_response(export: dict, master_spec: dict, spec: dict) -> dict:
    """Derive one State Response Plan from one authoritative export.

    Args:
        export: A validated Render Export V1 document.
        master_spec: The Master Scene Spec the export must agree with.
        spec: A resolved state response spec.

    Returns:
        The plan: format, schema_version, representation statement, provenance,
        the responses in total order, any published refusals, and a summary
        derived from the finished body.

    Raises:
        StateResponsePlanError: If the export cannot support a declared channel.
        SceneContractError: If the export and the master scene disagree.
    """
    # This layer's own validation runs FIRST. The shared topology check subscripts
    # export documents directly, so a malformed district reaches it as a raw
    # TypeError or KeyError -- an error, but not a refusal, and not one that says
    # which field was wrong. Validating here first means every malformed document
    # is refused by name before anything else touches it.
    districts = _require_districts(export)
    facts = _require_facts(export)
    require_topology_agreement(master_spec, export)

    responses: list[dict] = []
    refused: dict[str, str] = {}

    air_policy = require_channel(spec, "district_air")
    for district_id in sorted(districts):
        definition = master_spec["districts"].get(district_id)
        if definition is None:
            raise StateResponsePlanError(
                f"render export district {district_id!r} has no master scene definition; "
                "unknown districts are refused, never given a default field"
            )
        responses.append(
            _air_response(air_policy, district_id, districts[district_id], definition, spec["air"])
        )

    record_policy = require_channel(spec, "memory_record")
    capacity = spec["record"]["capacity"]
    for slot, fact in enumerate(facts):
        if slot >= capacity:
            refused[fact["fact_id"]] = (
                f"the record arc holds {capacity} stones and this is fact {slot + 1}; "
                "the arc is not extended silently"
            )
            continue
        responses.append(_record_response(record_policy, fact, slot, spec["record"]))

    responses.sort(key=_sort_key)
    by_channel: dict[str, int] = {}
    for response in responses:
        by_channel[response["channel"]] = by_channel.get(response["channel"], 0) + 1

    return {
        "format": STATE_RESPONSE_PLAN_FORMAT,
        "schema_version": STATE_RESPONSE_PLAN_SCHEMA_VERSION,
        "representation": REPRESENTATION_STATEMENT,
        "source": _provenance(export),
        "responses": responses,
        "refused": dict(sorted(refused.items())),
        "summary": {
            "districts": len(districts),
            "memory_facts": len(facts),
            "refused": len(refused),
            "responses": len(responses),
            "responses_by_channel": dict(sorted(by_channel.items())),
            "signals": sorted({response["source_field"] for response in responses}),
        },
    }


def plan_state_response_files(spec_path: str, export_path: str, response_spec: dict) -> dict:
    """Derive a plan from a master scene spec and a render export on disk."""
    master_spec = load_master_scene_spec(spec_path)
    export = load_render_export(export_path)
    return plan_state_response(export, master_spec, response_spec)


def canonical_plan_bytes(plan: dict) -> bytes:
    """Return the plan's canonical encoding: sorted keys, compact, UTF-8, one newline."""
    payload = json.dumps(
        plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return (payload + "\n").encode("utf-8")


def plan_hash(plan: dict) -> str:
    """Return the SHA-256 of the plan's canonical encoding."""
    return hashlib.sha256(canonical_plan_bytes(plan)).hexdigest()


def validate_state_response_plan(plan: dict) -> list[str]:
    """Re-derive every claim the plan makes about itself.

    The planner is not trusted to describe its own output: this walks the
    published body and rebuilds the summary, the ordering and the response
    invariants from what the document actually says.

    Args:
        plan: A state response plan.

    Returns:
        Every problem found, in the order found. An empty list means the plan
        says only true things about itself.
    """
    problems: list[str] = []
    if plan.get("format") != STATE_RESPONSE_PLAN_FORMAT:
        problems.append(
            f"format must be {STATE_RESPONSE_PLAN_FORMAT!r}, got {plan.get('format')!r}"
        )
    if plan.get("schema_version") != STATE_RESPONSE_PLAN_SCHEMA_VERSION:
        problems.append(
            f"schema_version must be {STATE_RESPONSE_PLAN_SCHEMA_VERSION}, "
            f"got {plan.get('schema_version')!r}"
        )
    responses = plan.get("responses")
    if not isinstance(responses, list):
        return [*problems, "responses must be a JSON array"]

    keys = [_sort_key(response) for response in responses]
    if keys != sorted(keys):
        problems.append("responses are not in their own total order")
    targets: dict[str, str] = {}
    for response in responses:
        target = json.dumps(response["target"], sort_keys=True)
        owner = targets.get(target)
        if owner is not None:
            problems.append(
                f"responses {owner!r} and {response['semantic_id']!r} drive the same target "
                f"{target}; one property cannot carry two readings"
            )
        targets[target] = response["semantic_id"]
        if not str(response.get("source_path", "")).strip():
            problems.append(f"response {response['semantic_id']!r} carries no source path")
        if response["channel"] == "district_air":
            expected = f"world.districts[{response['semantic_id']}].{response['source_field']}"
            if response.get("source_path") != expected:
                problems.append(
                    f"response {response['semantic_id']!r} claims source "
                    f"{response.get('source_path')!r}, which does not name its own "
                    f"district and field ({expected!r})"
                )
            if not isinstance(response.get("source_value"), float):
                problems.append(
                    f"response {response['semantic_id']!r} carries a non-real reading "
                    f"{response.get('source_value')!r}"
                )
            elif not 0.0 <= response["source_value"] <= 1.0:
                problems.append(
                    f"response {response['semantic_id']!r} read "
                    f"{response['source_value']!r}, outside the field's own domain"
                )
        value = response.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            problems.append(
                f"response {response['semantic_id']!r} carries a non-real value {value!r}"
            )
        elif not math.isfinite(float(value)):
            problems.append(
                f"response {response['semantic_id']!r} carries a non-finite value {value!r}"
            )

    summary = plan.get("summary")
    if not isinstance(summary, dict):
        return [*problems, "summary must be a JSON object"]
    if summary.get("responses") != len(responses):
        problems.append(
            f"summary claims {summary.get('responses')!r} responses, "
            f"the body carries {len(responses)}"
        )
    by_channel: dict[str, int] = {}
    for response in responses:
        by_channel[response["channel"]] = by_channel.get(response["channel"], 0) + 1
    if summary.get("responses_by_channel") != dict(sorted(by_channel.items())):
        problems.append(
            f"summary claims {summary.get('responses_by_channel')!r} per channel, "
            f"the body carries {dict(sorted(by_channel.items()))}"
        )
    signals = sorted({response["source_field"] for response in responses})
    if summary.get("signals") != signals:
        problems.append(
            f"summary claims signals {summary.get('signals')!r}, the body reads {signals}"
        )
    refused = plan.get("refused")
    if not isinstance(refused, dict):
        problems.append("refused must be a JSON object")
    elif summary.get("refused") != len(refused):
        problems.append(
            f"summary claims {summary.get('refused')!r} refusals, the body carries {len(refused)}"
        )
    return problems


__all__ = [
    "AIR_DENSITY_NODE",
    "AIR_DENSITY_SOCKET",
    "AIR_MATERIAL_PREFIX",
    "RECORD_OBJECT_PREFIX",
    "REPRESENTATION_STATEMENT",
    "STATE_RESPONSE_PLAN_FORMAT",
    "STATE_RESPONSE_PLAN_SCHEMA_VERSION",
    "SceneContractError",
    "StateResponsePlanError",
    "canonical_plan_bytes",
    "plan_hash",
    "plan_state_response",
    "plan_state_response_files",
    "validate_state_response_plan",
]
