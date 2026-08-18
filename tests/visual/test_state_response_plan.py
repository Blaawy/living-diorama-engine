"""Contract tests for the pure State Response Plan V1 derivation.

Pure pytest -- no Blender, and no dependency on a generated story file: every
export here is built in-test from the canonical Master Scene Spec's own district
list, so the suite proves the DERIVATION RULES rather than one recorded episode.
The one test that reads the real proof chain is skipped where that chain is
absent, because a suite that only runs on the author's machine proves nothing on
anybody else's.

The rules under test are the ones that make "the city is showing you its own
state" a checkable claim rather than a slogan: every response names the field it
read and carries the raw number it read there, one authoritative field moves one
visual consequence and nothing else, a malformed or out-of-domain district is
refused with a reason instead of clamped into something plausible, what the arc
cannot hold is published as a refusal instead of dropped, and the same world
always produces the same bytes.

The centre of the file is the mutation sweep. A per-response SHA-256 fingerprint
turns "everything else is byte-identical" into a single assertion rather than a
field-by-field walk that silently stops checking whatever nobody thought of, and
the helper that compares those fingerprints is itself negatively controlled: it
must reject the empty plan, because a planner that emitted nothing would satisfy
set equality on the empty set for every mutation in the matrix.
"""

import copy
import hashlib
import importlib
import json
import math
import random
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"
CONFIG_DIR = REPO_ROOT / "visual" / "blender" / "config"
WORK_EXPORT = Path(r"C:\Users\BLaAw\Desktop\main\p19work\render_export_mid.json")


def _load(name: str):
    """Import one pure visual module the same way Blender does: by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


srp = _load("state_response_plan")
srs = _load("state_response_spec")
ss = _load("scene_spec")

MASTER = ss.load_master_scene_spec(CONFIG_DIR / "master_scene_v1.json")
SPEC = srs.load_state_response_spec(CONFIG_DIR / "state_response_v1.json")

DISTRICT_IDS = tuple(sorted(MASTER["districts"]))

DISTRICT_KEYS = (
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
)
"""Exactly the keys a Render Export V1 district document carries.

Restated here rather than imported from the planner's own frozenset, because the
point of this suite is that Phase 20 re-validates the district documents the
engine's envelope-only export check waves through. A test that imported the
planner's key set would prove only that the planner agrees with itself.
"""

MISSING_KEYS = tuple(key for key in DISTRICT_KEYS if key != "id")
"""Every district key whose absence Phase 20 gets to answer for.

``id`` is deliberately absent from this sweep: topology agreement is settled
before Phase 20 reads a field, and a district document with no ``id`` at all
never reaches the Phase 20 guard that would have named it. That gap belongs to
the module, not to this suite, and is reported rather than papered over.
"""

STORY_SCARCITY = {
    "district_a": 0.0,
    "district_b": 1.0,
    "district_c": 0.25,
    "district_d": 0.6,
}
"""Four distinct readings, so a planner emitting one constant cannot pass."""

CHANNEL_FOR_FIELD = {
    "fact_type": {"memory_record"},
    "scarcity": {"district_air"},
}
"""Which channel each authoritative field is allowed to move, and no other.

Written out here rather than read from the spec the planner also reads. A matrix
taken from the modules under test would prove only that they agree with
themselves; this is a second, independent statement of the coupling, and the
mutation sweep below is where the two are made to meet.
"""

UNREAD_DISTRICT_FIELDS = (
    ("consumption_rate", 3.25),
    ("created_tick", 41),
    ("fear", 0.97),
    ("housing_capacity", 999),
    ("institutional_pressure", 0.91),
    ("isolation_state", "ISOLATED"),
    ("population", 377),
    ("production_rate", 88.5),
    ("trust", 0.03),
)
"""Every district field Phase 20 validates but no declared channel reads.

Each pairs with a legal value far from the baseline. Phase 20 refuses a
malformed reading of all of them, which is the point: validating a field is not
the same as showing it, and a plan that moved when ``trust`` moved would be
showing something the contract never declared.
"""

ISOLATION_STATES = ("ISOLATED", "OPEN", "PARTIAL")
"""The world's three answers about a gate, and there is no fourth."""


def district(district_id: str, **overrides: object) -> dict:
    """One export district entry carrying every key the export format declares."""
    entry = {
        "id": district_id,
        "created_tick": 0,
        "population": 100,
        "housing_capacity": 400,
        "production_rate": 10.0,
        "consumption_rate": 0.1,
        "scarcity": STORY_SCARCITY[district_id],
        "fear": 0.1,
        "trust": 0.85,
        "institutional_pressure": 0.15,
        "isolation_state": "OPEN",
        "resources": {"FOOD": 60.0, "MATERIALS": 60.0, "ENERGY": 60.0},
    }
    entry.update(overrides)
    return entry


def fact(fact_id: str, *, fact_type: str = "WALL_BUILT", episode: int = 1, tick: int = 9) -> dict:
    """One durable memory fact, carrying the structured members Phase 20 reads."""
    return {"episode": episode, "fact_id": fact_id, "fact_type": fact_type, "tick": tick}


def export(
    *,
    facts: tuple[str, ...] = ("fact_alpha", "fact_beta"),
    ids: tuple[str, ...] = DISTRICT_IDS,
    episode: int = 0,
) -> dict:
    """A Render Export V1 document agreeing with the canonical master scene."""
    return {
        "format": "living_diorama_render_export",
        "schema_version": 1,
        "source": {
            "engine_version": "0.0.1",
            "episode": episode,
            "tick": episode * 10,
            "state_hash": f"{episode:064d}",
            "parent_state_hash": None,
            "event_count": 0,
            "entity_counts": {
                "districts": len(ids),
                "boundaries": 0,
                "walls": 0,
                "laws": 0,
                "infrastructure": 0,
            },
        },
        "world": {
            "districts": [district(district_id) for district_id in ids],
            "boundaries": [],
            "walls": [],
            "laws": [],
            "infrastructure": [],
        },
        "events": [],
        "memory": {
            "through_episode": episode,
            "through_tick": episode * 10,
            "facts": [fact(fact_id) for fact_id in facts],
        },
    }


def plan_for(document: dict) -> dict:
    """Derive one plan from one export against the canonical master scene and spec."""
    return srp.plan_state_response(document, MASTER, SPEC)


def refuses(document: dict, fragment: str) -> str:
    """Assert planning refuses this export for the stated reason, and return why."""
    with pytest.raises(srp.StateResponsePlanError) as error:
        plan_for(document)
    message = str(error.value)
    assert fragment in message, message
    return message


def response_fingerprints(plan: dict) -> dict[tuple[str, str], str]:
    """A SHA-256 per response, keyed by the channel and the thing it speaks for.

    Fingerprinting each response whole is what makes "every other response is
    byte-identical" one assertion instead of a field-by-field comparison that
    quietly stops checking whatever field was added last.
    """
    return {
        (entry["channel"], entry["semantic_id"]): hashlib.sha256(
            json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        for entry in plan["responses"]
    }


def moved_responses(baseline: dict, mutated: dict) -> set[tuple[str, str]]:
    """Every response whose bytes differ, INCLUDING ones that appeared or vanished.

    Taking the union of both key sets rather than walking the baseline is the
    whole point: a mutation that made a response disappear would be invisible to
    a loop over the baseline, and a response that appeared from nowhere is
    exactly the accidental coupling being hunted.
    """
    before, after = response_fingerprints(baseline), response_fingerprints(mutated)
    return {key for key in set(before) | set(after) if before.get(key) != after.get(key)}


def assert_exactly_these_responses_moved(
    baseline: dict, mutated: dict, expected: set[tuple[str, str]]
) -> None:
    """One field moved, so exactly its declared responses moved and nothing else.

    Three claims, and the third is the one that matters: a planner that emitted
    no responses at all would satisfy set equality on the empty set for every
    mutation in the matrix, so the expected responses must also be PRESENT in
    both plans before the comparison means anything.
    """
    assert expected, "a mutation with no declared consequence is not a test"
    moved = moved_responses(baseline, mutated)
    assert moved == expected, f"expected {sorted(expected)} to move, {sorted(moved)} did"
    for key in expected:
        assert key in response_fingerprints(baseline), f"{key} is absent from the baseline plan"
        assert key in response_fingerprints(mutated), f"{key} is absent from the mutated plan"


CANONICAL = plan_for(export())


# ---------------------------------------------------------------------------
# The control arm
# ---------------------------------------------------------------------------


def test_the_baseline_export_every_refusal_starts_from_is_accepted() -> None:
    """A module that refused everything would pass every refusal test below.

    Every refusal in this file is a one-field mutation of ``export()``, so each
    of them is only evidence in the presence of this: the unmutated document
    plans, produces real responses, and audits clean.
    """
    plan = plan_for(export())
    assert plan["responses"], "the baseline export must produce a real plan"
    assert plan["format"] == srp.STATE_RESPONSE_PLAN_FORMAT
    assert plan["schema_version"] == srp.STATE_RESPONSE_PLAN_SCHEMA_VERSION
    assert plan["representation"] == srp.REPRESENTATION_STATEMENT
    assert srp.validate_state_response_plan(plan) == []


def test_the_plan_speaks_for_every_district_and_every_remembered_fact() -> None:
    """A declared channel that never fires is a policy nobody applied."""
    plan = plan_for(export())
    air = {r["semantic_id"] for r in plan["responses"] if r["channel"] == "district_air"}
    records = {r["semantic_id"] for r in plan["responses"] if r["channel"] == "memory_record"}
    assert air == set(DISTRICT_IDS)
    assert records == {"fact_alpha", "fact_beta"}
    assert len(plan["responses"]) == len(DISTRICT_IDS) + 2
    assert plan["summary"]["responses_by_channel"] == {
        "district_air": len(DISTRICT_IDS),
        "memory_record": 2,
    }


@pytest.mark.parametrize("state", ISOLATION_STATES)
def test_every_legal_isolation_state_is_accepted(state: str) -> None:
    """The proof chain is OPEN everywhere, so only a synthetic world can prove this.

    A planner that refused every state but ``OPEN`` would pass the unknown-state
    refusal below and every test the real episodes can reach, and would then
    refuse the first sealed district the engine ever produces.
    """
    document = export()
    for entry in document["world"]["districts"]:
        entry["isolation_state"] = state
    assert srp.validate_state_response_plan(plan_for(document)) == []


# ---------------------------------------------------------------------------
# Malformed districts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", MISSING_KEYS)
def test_a_district_missing_a_key_is_refused(key: str) -> None:
    """A missing field is missing state, not an implied default."""
    document = export()
    document["world"]["districts"][1].pop(key)
    refuses(document, f"is missing ['{key}']")


def test_a_district_carrying_an_extra_key_is_refused() -> None:
    """A field this contract does not describe means the document came from elsewhere."""
    document = export()
    document["world"]["districts"][0]["morale"] = 0.4
    refuses(document, "declares unexpected keys ['morale']")


def test_a_duplicate_district_id_is_refused() -> None:
    """Two rows for one district means one of them would be read blind."""
    document = export()
    document["world"]["districts"].append(district("district_a"))
    refuses(document, "twice; identity is indexed, never taken from array order")


def test_an_empty_district_array_is_refused() -> None:
    """A city with no districts has no condition to show, and says so."""
    document = export()
    document["world"]["districts"] = []
    refuses(document, "declares no districts")


def test_a_district_array_that_is_not_an_array_is_refused() -> None:
    """A JSON object where an ordered array belongs is a malformed export."""
    document = export()
    document["world"]["districts"] = {}
    refuses(document, "world.districts must be a JSON array")


def test_a_district_the_master_scene_never_defined_is_refused() -> None:
    """A response in a place the city does not have is not a response.

    A usable identifier that names no district the master scene draws is settled
    by topology agreement, which is the precedent Phase 17 set.
    """
    document = export()
    document["world"]["districts"][0]["id"] = "district_z"
    with pytest.raises(ss.SceneContractError) as error:
        plan_for(document)
    assert "has no master scene definition" in str(error.value)


@pytest.mark.parametrize("district_id", ["", "  ", " district_a"])
def test_an_unusable_district_identifier_is_refused_by_name(district_id: str) -> None:
    """A blank or padded identifier is refused before anything reads a field.

    This layer validates its own documents first, precisely so a malformed
    identifier is refused by name rather than reaching the shared topology check
    as a bare ``TypeError`` or ``KeyError``. The distinction matters: a refusal
    says which field was wrong, and a crash does not.
    """
    document = export()
    document["world"]["districts"][0]["id"] = district_id
    with pytest.raises(srp.StateResponsePlanError) as error:
        plan_for(document)
    assert "declares an unusable id" in str(error.value)


def test_an_export_missing_a_district_the_master_scene_draws_is_still_planned() -> None:
    """Fewer districts is a smaller world, not a malformed one -- and only those speak.

    This is the counterfactual for the refusal above: the planner refuses names
    the master scene does not carry, and it must not also refuse a legal subset,
    because a planner that refused both would pass the refusal test for the
    wrong reason.
    """
    document = export(ids=DISTRICT_IDS[:2])
    plan = plan_for(document)
    air = {r["semantic_id"] for r in plan["responses"] if r["channel"] == "district_air"}
    assert air == set(DISTRICT_IDS[:2])
    assert plan["summary"]["districts"] == 2


@pytest.mark.parametrize("field", srs.DISTRICT_SCALARS)
@pytest.mark.parametrize("value", [-0.001, 1.001, 4.0, -3.0])
def test_a_scalar_outside_its_own_domain_is_refused(field: str, value: float) -> None:
    """Out of domain is refused, never clamped into something plausible."""
    document = export()
    document["world"]["districts"][2][field] = value
    refuses(document, f"{field} must lie in [0, 1]")


@pytest.mark.parametrize("field", srs.DISTRICT_SCALARS)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_scalar_is_refused(field: str, value: float) -> None:
    """A ``NaN`` passes every comparison it is checked against and hashes into the plan."""
    document = export()
    document["world"]["districts"][0][field] = value
    refuses(document, f"{field} must be finite")


@pytest.mark.parametrize("field", srs.DISTRICT_SCALARS)
def test_a_boolean_scalar_is_refused(field: str) -> None:
    """``True`` is an int in Python and must never be read as total fear."""
    document = export()
    document["world"]["districts"][0][field] = True
    refuses(document, f"{field} must be a real number")


@pytest.mark.parametrize("field", srs.DISTRICT_SCALARS)
@pytest.mark.parametrize("value", ["0.7", None, [0.7]])
def test_a_scalar_that_is_not_a_number_is_refused(field: str, value: object) -> None:
    """``"0.7"`` sorts, compares and formats -- and means nothing to arithmetic."""
    document = export()
    document["world"]["districts"][0][field] = value
    refuses(document, f"{field} must be a real number")


@pytest.mark.parametrize("field", ["created_tick", "housing_capacity", "population"])
@pytest.mark.parametrize("value", [100.0, True, "100", None])
def test_a_district_count_that_is_not_an_exact_integer_is_refused(
    field: str, value: object
) -> None:
    """A hundred people is a count; ``100.0`` and ``True`` are something else."""
    document = export()
    document["world"]["districts"][0][field] = value
    refuses(document, f"{field} must be an integer")


@pytest.mark.parametrize("field", ["created_tick", "housing_capacity", "population"])
def test_a_negative_district_count_is_refused(field: str) -> None:
    """There is no district of minus twelve people."""
    document = export()
    document["world"]["districts"][0][field] = -12
    refuses(document, f"{field} must not be negative")


@pytest.mark.parametrize("field", ["consumption_rate", "production_rate"])
def test_a_negative_rate_is_refused(field: str) -> None:
    """A district cannot produce or consume a negative amount of anything."""
    document = export()
    document["world"]["districts"][3][field] = -0.5
    refuses(document, f"{field} must not be negative")


@pytest.mark.parametrize("field", ["consumption_rate", "production_rate"])
def test_a_non_finite_rate_is_refused(field: str) -> None:
    """Infinite production is not abundance, it is a corrupted document."""
    document = export()
    document["world"]["districts"][3][field] = float("inf")
    refuses(document, f"{field} must be finite")


@pytest.mark.parametrize("state", ["SEALED", "open", "Open", "", True, None, 2])
def test_an_isolation_state_the_world_never_writes_is_refused(state: object) -> None:
    """Three answers exist, and case-folding a fourth would accept a forged document."""
    document = export()
    document["world"]["districts"][0]["isolation_state"] = state
    refuses(document, "declares isolation_state")


@pytest.mark.parametrize("resources", [[60.0, 60.0, 60.0], "full", None, {}])
def test_resources_that_are_not_a_full_mapping_are_refused(resources: object) -> None:
    """A list of numbers has no commodity names and cannot be read as a store."""
    document = export()
    document["world"]["districts"][0]["resources"] = resources
    refuses(document, "resources must carry exactly")


def test_an_unknown_commodity_is_refused() -> None:
    """A commodity the world does not have cannot be shown running out."""
    document = export()
    document["world"]["districts"][0]["resources"]["WATER"] = 4.0
    refuses(document, "resources must carry exactly")


def test_a_missing_commodity_is_refused() -> None:
    """A store counted over two of three commodities understates every one of them."""
    document = export()
    document["world"]["districts"][0]["resources"].pop("FOOD")
    refuses(document, "resources must carry exactly")


@pytest.mark.parametrize("kind", ["ENERGY", "FOOD", "MATERIALS"])
def test_a_negative_commodity_stock_is_refused(kind: str) -> None:
    """The world holds no negative food."""
    document = export()
    document["world"]["districts"][0]["resources"][kind] = -1.0
    refuses(document, f"resources[{kind}] must not be negative")


@pytest.mark.parametrize("kind", ["ENERGY", "FOOD", "MATERIALS"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "60"])
def test_an_unreadable_commodity_stock_is_refused(kind: str, value: object) -> None:
    """A ``NaN`` in one commodity poisons every total anybody later takes."""
    document = export()
    document["world"]["districts"][0]["resources"][kind] = value
    refuses(document, f"resources[{kind}] must")


# ---------------------------------------------------------------------------
# Malformed memory
# ---------------------------------------------------------------------------


def test_an_export_with_no_memory_section_is_refused() -> None:
    """What the world remembers is not optional, and an absent section is not empty."""
    document = export()
    document.pop("memory")
    refuses(document, "memory must be a JSON object")


def test_a_memory_facts_section_that_is_not_an_array_is_refused() -> None:
    """Facts are remembered in order, and an object has no order to remember."""
    document = export()
    document["memory"]["facts"] = {"fact_alpha": {}}
    refuses(document, "memory.facts must be a JSON array")


def test_a_non_object_memory_fact_is_refused() -> None:
    """A string in the fact array is not a fact."""
    document = export()
    document["memory"]["facts"].append("fact_gamma")
    refuses(document, "memory fact [2] must be a JSON object")


@pytest.mark.parametrize("key", ["episode", "fact_id", "fact_type", "tick"])
def test_a_memory_fact_missing_a_member_phase20_reads_is_refused(key: str) -> None:
    """A fact with no type is a memory of nothing in particular."""
    document = export()
    document["memory"]["facts"][0].pop(key)
    refuses(document, f"is missing {key!r}")


@pytest.mark.parametrize("label", ["fact_id", "fact_type"])
@pytest.mark.parametrize("value", ["", "   ", 3, None, True])
def test_an_unusable_fact_identifier_is_refused(label: str, value: object) -> None:
    """A blank identifier names nothing, and a number is not a structured type."""
    document = export()
    document["memory"]["facts"][0][label] = value
    refuses(document, f"declares an unusable {label}")


def test_a_duplicate_fact_id_is_refused() -> None:
    """A fact is remembered once; twice would raise two stones for one event."""
    document = export()
    document["memory"]["facts"].append(fact("fact_alpha", fact_type="LAW_CHANGED"))
    refuses(document, "twice; a fact is remembered once")


@pytest.mark.parametrize("key", ["episode", "tick"])
@pytest.mark.parametrize("value", [1.0, True, "1", None])
def test_a_fact_stamped_with_a_time_that_is_not_a_count_is_refused(key: str, value: object) -> None:
    """A fact happened at a tick, and a tick is counted, never measured."""
    document = export()
    document["memory"]["facts"][0][key] = value
    refuses(document, f"{key} must be an integer")


@pytest.mark.parametrize("key", ["episode", "tick"])
def test_a_fact_stamped_before_the_world_began_is_refused(key: str) -> None:
    """There is no episode minus one to have remembered something in."""
    document = export()
    document["memory"]["facts"][0][key] = -1
    refuses(document, f"{key} must not be negative")


def test_an_export_with_no_provenance_is_refused() -> None:
    """A plan says which verified episode it read, so an export must say which it is."""
    document = export()
    document.pop("source")
    refuses(document, "source must be a JSON object")


# ---------------------------------------------------------------------------
# Provenance and mapping
# ---------------------------------------------------------------------------


def test_every_air_response_names_its_own_district_and_field() -> None:
    """Traceability is not optional: a directive with no checkable source is a fiction."""
    for entry in CANONICAL["responses"]:
        if entry["channel"] != "district_air":
            continue
        district_id = entry["semantic_id"]
        assert entry["source_kind"] == "district_scalar"
        assert entry["source_field"] in srs.DISTRICT_SCALARS
        assert entry["source_path"] == f"world.districts[{district_id}].{entry['source_field']}"


def test_every_air_response_carries_the_number_the_export_actually_holds() -> None:
    """The recorded reading is the exported float, not a rounded restatement of it.

    A planner that stored ``round(scarcity, 3)`` as provenance would make two
    districts a thousandth apart indistinguishable in the record, so the value
    is compared for exact float identity against the document it came from.
    """
    document = export()
    document["world"]["districts"][0]["scarcity"] = 0.1234567890123
    document["world"]["districts"][2]["scarcity"] = 0.1234567890124
    plan = plan_for(document)
    holdings = {entry["id"]: entry["scarcity"] for entry in document["world"]["districts"]}
    readings = {
        entry["semantic_id"]: entry["source_value"]
        for entry in plan["responses"]
        if entry["channel"] == "district_air"
    }
    assert readings == holdings
    assert readings["district_a"] != readings["district_c"]


def test_the_air_response_is_the_declared_range_applied_to_the_declared_field() -> None:
    """The number the film shows is re-derivable from the spec's own constants.

    Re-derived from the resolved spec's declared bounds and base density rather
    than from the planner's helper, so a planner that scaled by ``1 - scarcity``
    or ignored the range entirely fails here even while every provenance test
    above still passes.
    """
    policy = srs.require_channel(SPEC, "district_air")
    low, high = policy["response_minimum"], policy["response_maximum"]
    base = SPEC["air"]["base_density"]
    for entry in CANONICAL["responses"]:
        if entry["channel"] != "district_air":
            continue
        reading = STORY_SCARCITY[entry["semantic_id"]]
        expected_scale = round(low + (high - low) * reading, 6)
        assert entry["source_value"] == reading
        assert entry["response_scale"] == expected_scale
        assert entry["value"] == round(base * expected_scale, 9)


def test_a_calm_district_and_a_starving_one_do_not_share_a_response() -> None:
    """Different state, different response -- a mapping that collapsed them shows one city."""
    values = {
        entry["semantic_id"]: entry["value"]
        for entry in CANONICAL["responses"]
        if entry["channel"] == "district_air"
    }
    assert len(set(values.values())) == len(STORY_SCARCITY)
    assert values["district_b"] > values["district_a"]


def test_each_air_response_covers_its_own_district_and_no_other() -> None:
    """The stratum sits over the district it reads, at the radius the scene declares."""
    margin = SPEC["air"]["rim_margin_metres"]
    ceiling = SPEC["air"]["ceiling_metres"]
    for entry in CANONICAL["responses"]:
        if entry["channel"] != "district_air":
            continue
        definition = MASTER["districts"][entry["semantic_id"]]
        assert entry["field"]["centre"] == [
            round(float(definition["center"][0]), 6),
            round(float(definition["center"][1]), 6),
        ]
        assert entry["field"]["radius"] == round(float(definition["radius"]) + margin, 6)
        assert entry["field"]["floor"] == round(float(definition["elevation"]), 6)
        assert entry["field"]["ceiling"] == round(float(definition["elevation"]) + ceiling, 6)
        assert entry["target"]["material"] == f"{srp.AIR_MATERIAL_PREFIX}{entry['semantic_id']}"


def test_every_record_response_names_the_fact_it_stands_for() -> None:
    """A stone is one durable fact, keyed by the structured type, never by its prose."""
    for entry in CANONICAL["responses"]:
        if entry["channel"] != "memory_record":
            continue
        assert entry["source_kind"] == "memory_fact"
        assert entry["source_field"] in srs.MEMORY_FACT_FIELDS
        assert entry["source_path"] == (
            f"memory.facts[{entry['semantic_id']}].{entry['source_field']}"
        )
        assert entry["source_value"] == "WALL_BUILT"


def test_record_stones_sit_on_the_arc_the_spec_declares() -> None:
    """Each stone stands where the declared arc puts its slot, and nowhere else."""
    record = SPEC["record"]
    for entry in CANONICAL["responses"]:
        if entry["channel"] != "memory_record":
            continue
        slot = entry["field"]["slot"]
        angle = math.radians(record["arc_start_degrees"] + record["arc_step_degrees"] * slot)
        assert entry["field"]["x"] == round(
            record["origin"][0] + record["arc_radius_metres"] * math.cos(angle), 6
        )
        assert entry["field"]["y"] == round(
            record["origin"][1] + record["arc_radius_metres"] * math.sin(angle), 6
        )
        assert entry["target"]["object"] == f"{srp.RECORD_OBJECT_PREFIX}{slot:03d}"


def test_a_stone_takes_the_slot_the_engine_remembered_it_in() -> None:
    """Chronology decides slots; the plan's own lexical order decides nothing.

    The export lists ``fact_zulu`` before ``fact_alpha``, so ``fact_zulu`` holds
    slot zero even though the finished plan sorts the other way round. A planner
    that assigned slots after sorting would silently rewrite the order the world
    remembered things in.
    """
    plan = plan_for(export(facts=("fact_zulu", "fact_alpha")))
    slots = {
        entry["semantic_id"]: entry["field"]["slot"]
        for entry in plan["responses"]
        if entry["channel"] == "memory_record"
    }
    assert slots == {"fact_zulu": 0, "fact_alpha": 1}


def test_the_plan_records_the_episode_it_was_derived_from() -> None:
    """A plan says which verified episode it read, and carries its bounded claim."""
    document = export(episode=2)
    plan = plan_for(document)
    assert plan["source"] == {
        "episode": 2,
        "state_hash": document["source"]["state_hash"],
        "tick": 20,
    }
    assert "not a claim about a person" in plan["representation"]
    assert "read back into the simulation" in plan["representation"]


def test_responses_are_in_the_modules_own_total_order() -> None:
    """A stable order makes plans diffable and their hashes meaningful."""
    keys = [
        (entry["channel"], entry["semantic_id"], json.dumps(entry["target"], sort_keys=True))
        for entry in CANONICAL["responses"]
    ]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys)


def test_no_two_responses_drive_the_same_property() -> None:
    """One property cannot carry two readings, whichever was written last."""
    targets = [json.dumps(entry["target"], sort_keys=True) for entry in CANONICAL["responses"]]
    assert len(set(targets)) == len(targets)


def test_the_summary_re_derives_from_the_body_it_summarises() -> None:
    """A summary is a claim about the plan, and it is checked against the plan."""
    responses = CANONICAL["responses"]
    by_channel: dict[str, int] = {}
    for entry in responses:
        by_channel[entry["channel"]] = by_channel.get(entry["channel"], 0) + 1
    assert CANONICAL["summary"]["responses"] == len(responses)
    assert CANONICAL["summary"]["responses_by_channel"] == dict(sorted(by_channel.items()))
    assert CANONICAL["summary"]["signals"] == sorted({e["source_field"] for e in responses})
    assert CANONICAL["summary"]["districts"] == len(DISTRICT_IDS)
    assert CANONICAL["summary"]["memory_facts"] == 2
    assert CANONICAL["summary"]["refused"] == len(CANONICAL["refused"])


def test_what_the_arc_cannot_hold_is_published_with_its_reason() -> None:
    """A fact the arc has no room for is refused out loud, never dropped in silence."""
    capacity = SPEC["record"]["capacity"]
    ids = tuple(f"fact_{index:02d}" for index in range(capacity + 3))
    plan = plan_for(export(facts=ids))
    stones = {e["semantic_id"] for e in plan["responses"] if e["channel"] == "memory_record"}
    assert stones == set(ids[:capacity])
    assert set(plan["refused"]) == set(ids[capacity:])
    assert plan["summary"]["refused"] == 3
    assert plan["summary"]["memory_facts"] == capacity + 3
    for fact_id, reason in plan["refused"].items():
        assert f"holds {capacity} stones" in reason, fact_id
        assert "not extended silently" in reason, fact_id
    assert srp.validate_state_response_plan(plan) == []


def test_an_export_the_arc_exactly_fits_refuses_nothing() -> None:
    """The counterfactual for the refusal above: at capacity, nothing is turned away."""
    capacity = SPEC["record"]["capacity"]
    plan = plan_for(export(facts=tuple(f"fact_{index:02d}" for index in range(capacity))))
    assert plan["refused"] == {}
    assert plan["summary"]["responses_by_channel"]["memory_record"] == capacity


def test_a_world_that_remembers_nothing_raises_no_stones() -> None:
    """No facts is no stones -- not one placeholder stone standing for the absence."""
    plan = plan_for(export(facts=()))
    assert [e for e in plan["responses"] if e["channel"] == "memory_record"] == []
    assert plan["summary"]["signals"] == ["scarcity"]
    assert srp.validate_state_response_plan(plan) == []


def test_planning_leaves_the_export_document_exactly_as_it_found_it() -> None:
    """Phase 20 reads state; writing it back would make the export disagree with itself.

    A planner that bound the district array and sorted it in place would pass
    every assertion above and still hand the next reader a different world.
    """
    document = export()
    original = json.dumps(document, sort_keys=True, separators=(",", ":"))
    plan_for(document)
    assert json.dumps(document, sort_keys=True, separators=(",", ":")) == original


def test_a_plan_derived_from_files_matches_one_derived_in_memory(tmp_path: Path) -> None:
    """The file entry point is the same derivation, not a second one that drifted."""
    document = export()
    path = tmp_path / "render_export.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    from_files = srp.plan_state_response_files(
        str(CONFIG_DIR / "master_scene_v1.json"), str(path), SPEC
    )
    assert srp.canonical_plan_bytes(from_files) == srp.canonical_plan_bytes(plan_for(document))


# ---------------------------------------------------------------------------
# The mutation sweep
# ---------------------------------------------------------------------------


def _mutate(document: dict, field: str) -> tuple[str, str]:
    """Apply the matrix's own mutation for one field, returning the response it must move."""
    if field == "scarcity":
        entry = next(e for e in document["world"]["districts"] if e["id"] == "district_b")
        entry["scarcity"] = 0.125
        return ("district_air", "district_b")
    document["memory"]["facts"][0]["fact_type"] = "LAW_CHANGED"
    return ("memory_record", document["memory"]["facts"][0]["fact_id"])


@pytest.mark.parametrize("field", sorted(CHANNEL_FOR_FIELD))
def test_mutating_one_field_moves_exactly_its_own_response(field: str) -> None:
    """One authoritative field, one visual consequence, and no side effects."""
    mutated = export()
    key = _mutate(mutated, field)
    assert_exactly_these_responses_moved(CANONICAL, plan_for(mutated), {key})


@pytest.mark.parametrize("field", sorted(CHANNEL_FOR_FIELD))
def test_the_response_that_moved_is_on_the_channel_the_matrix_declares(field: str) -> None:
    """The right response moving on the wrong channel is still the wrong plan."""
    mutated = export()
    channel, _ = _mutate(mutated, field)
    moved = moved_responses(CANONICAL, plan_for(mutated))
    assert {name for name, _ in moved} == CHANNEL_FOR_FIELD[field]
    assert channel in CHANNEL_FOR_FIELD[field]


def test_the_moved_response_names_the_field_that_moved_and_reads_its_new_value() -> None:
    """Coupling alone is not enough: the response must carry the number that changed."""
    mutated = export()
    _mutate(mutated, "scarcity")
    plan = plan_for(mutated)
    ((channel, semantic_id),) = moved_responses(CANONICAL, plan)
    moved = next(
        e for e in plan["responses"] if e["channel"] == channel and e["semantic_id"] == semantic_id
    )
    assert moved["source_path"] == "world.districts[district_b].scarcity"
    assert moved["source_value"] == 0.125
    assert moved["source_value"] != STORY_SCARCITY["district_b"]


def test_the_coupling_matrix_names_every_channel_the_planner_can_emit() -> None:
    """A channel no mutation covers is a channel that could be wired to anything."""
    emitted = {entry["channel"] for entry in CANONICAL["responses"]}
    covered: set[str] = set().union(*CHANNEL_FOR_FIELD.values())
    assert emitted == covered, f"uncovered channels: {sorted(emitted ^ covered)}"
    assert {entry["source_field"] for entry in CANONICAL["responses"]} == set(CHANNEL_FOR_FIELD)


@pytest.mark.parametrize(("field", "value"), UNREAD_DISTRICT_FIELDS)
def test_mutating_a_field_no_channel_reads_changes_nothing_at_all(
    field: str, value: object
) -> None:
    """Validating a field is not showing it, and the plan must not move when it moves."""
    mutated = export()
    next(e for e in mutated["world"]["districts"] if e["id"] == "district_b")[field] = value
    assert srp.canonical_plan_bytes(plan_for(mutated)) == srp.canonical_plan_bytes(CANONICAL)


def test_emptying_a_districts_stores_changes_nothing_at_all() -> None:
    """Phase 20 declares no depot channel, so an empty store is Phase 20's silence."""
    mutated = export()
    entry = next(e for e in mutated["world"]["districts"] if e["id"] == "district_b")
    entry["resources"] = {"FOOD": 0.0, "MATERIALS": 0.0, "ENERGY": 0.0}
    assert srp.canonical_plan_bytes(plan_for(mutated)) == srp.canonical_plan_bytes(CANONICAL)


def test_mutating_one_district_leaves_every_other_district_untouched() -> None:
    """Response is per-district: one district's collapse is not another's."""
    mutated = export()
    _mutate(mutated, "scarcity")
    plan = plan_for(mutated)
    before, after = response_fingerprints(CANONICAL), response_fingerprints(plan)
    others = {key for key in before if key != ("district_air", "district_b")}
    assert others, "the sweep needs districts other than the mutated one"
    assert {key: before[key] for key in others} == {key: after[key] for key in others}


def test_the_mutation_helper_would_actually_bite() -> None:
    """A helper nobody has seen fail is a helper nobody has tested.

    Four synthetic plans: one where a second response also moved, one where the
    expected response did not move, one where a response vanished outright, and
    one where both plans are empty. The last is the one that matters -- it is
    the shape of a planner that emits nothing, and the helper must refuse it
    rather than reporting a clean pass on the empty set.
    """
    base = {
        "responses": [
            {"channel": "district_air", "semantic_id": "district_a", "value": 1},
            {"channel": "district_air", "semantic_id": "district_b", "value": 1},
        ]
    }
    over = {
        "responses": [
            {"channel": "district_air", "semantic_id": "district_a", "value": 2},
            {"channel": "district_air", "semantic_id": "district_b", "value": 2},
        ]
    }
    with pytest.raises(AssertionError):
        assert_exactly_these_responses_moved(base, over, {("district_air", "district_a")})

    unchanged = {"responses": copy.deepcopy(base["responses"])}
    with pytest.raises(AssertionError):
        assert_exactly_these_responses_moved(base, unchanged, {("district_air", "district_a")})

    vanished = {"responses": [copy.deepcopy(base["responses"][0])]}
    assert moved_responses(base, vanished) == {("district_air", "district_b")}
    with pytest.raises(AssertionError):
        assert_exactly_these_responses_moved(base, vanished, {("district_air", "district_a")})

    empty: dict = {"responses": []}
    with pytest.raises(AssertionError):
        assert_exactly_these_responses_moved(empty, empty, set())


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_the_same_export_always_produces_the_same_bytes() -> None:
    """Determinism is the whole contract: same state, same response, every run."""
    first = plan_for(export())
    second = plan_for(copy.deepcopy(export()))
    assert srp.plan_hash(first) == srp.plan_hash(second)
    assert srp.canonical_plan_bytes(first) == srp.canonical_plan_bytes(second)


def test_the_plan_hash_changes_when_the_state_does() -> None:
    """A digest that never moved would prove nothing about what it had read."""
    mutated = export()
    _mutate(mutated, "scarcity")
    assert srp.plan_hash(plan_for(mutated)) != srp.plan_hash(CANONICAL)
    assert srp.canonical_plan_bytes(plan_for(mutated)) != srp.canonical_plan_bytes(CANONICAL)


def test_the_plan_does_not_depend_on_district_order_in_the_export() -> None:
    """A reordered export is the same world and must plan to the same bytes."""
    baseline = srp.plan_hash(CANONICAL)
    generator = random.Random(20260817)
    seen = set()
    for _ in range(8):
        shuffled = export()
        generator.shuffle(shuffled["world"]["districts"])
        seen.add(tuple(entry["id"] for entry in shuffled["world"]["districts"]))
        assert srp.plan_hash(plan_for(shuffled)) == baseline
    assert len(seen) > 1, "eight shuffles that never reordered anything prove nothing"


def test_the_plan_does_not_depend_on_the_order_keys_were_written_in() -> None:
    """A world is its values, not the order a serializer happened to emit them in."""
    reversed_document = export()
    reversed_document["world"]["districts"] = [
        dict(reversed(list(entry.items()))) for entry in reversed_document["world"]["districts"]
    ]
    for entry in reversed_document["world"]["districts"]:
        entry["resources"] = dict(reversed(list(entry["resources"].items())))
    assert srp.plan_hash(plan_for(reversed_document)) == srp.plan_hash(CANONICAL)


def test_the_plan_hash_is_stable_under_key_reordering() -> None:
    """A plan is its values too, so reversing its own top-level keys changes nothing."""
    shuffled = dict(reversed(list(copy.deepcopy(CANONICAL).items())))
    assert list(shuffled) != list(CANONICAL)
    assert srp.plan_hash(shuffled) == srp.plan_hash(CANONICAL)
    assert srp.canonical_plan_bytes(shuffled) == srp.canonical_plan_bytes(CANONICAL)


def test_the_canonical_encoding_is_the_thing_the_hash_is_taken_of() -> None:
    """The digest is a digest of the published bytes, not of some private restatement."""
    payload = srp.canonical_plan_bytes(CANONICAL)
    assert payload.endswith(b"\n")
    assert json.loads(payload.decode("utf-8")) == CANONICAL
    assert srp.plan_hash(CANONICAL) == hashlib.sha256(payload).hexdigest()


def test_a_changed_presentation_contract_changes_the_plan(tmp_path: Path) -> None:
    """A different policy is a different film, and it must not hash the same."""
    document = json.loads((CONFIG_DIR / "state_response_v1.json").read_text(encoding="utf-8"))
    document["channels"][0]["response_maximum"] = 6.0
    path = tmp_path / "state_response.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    widened = srs.load_state_response_spec(path)
    assert srp.plan_hash(srp.plan_state_response(export(), MASTER, widened)) != srp.plan_hash(
        CANONICAL
    )


def test_a_contract_reading_another_field_reads_that_field(tmp_path: Path) -> None:
    """The planner is a consumer of the spec, not a second author of it.

    Repointing the air channel at ``fear`` must repoint the provenance and the
    reading with it. A planner with ``scarcity`` written into its own body would
    keep publishing scarcity under a source path that named fear.
    """
    document = json.loads((CONFIG_DIR / "state_response_v1.json").read_text(encoding="utf-8"))
    document["channels"][0]["source_field"] = "fear"
    path = tmp_path / "fear.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    plan = srp.plan_state_response(export(), MASTER, srs.load_state_response_spec(path))
    for entry in plan["responses"]:
        if entry["channel"] != "district_air":
            continue
        assert entry["source_field"] == "fear"
        assert entry["source_path"] == f"world.districts[{entry['semantic_id']}].fear"
        assert entry["source_value"] == 0.1
    assert plan["summary"]["signals"] == ["fact_type", "fear"]


# ---------------------------------------------------------------------------
# The validator has teeth
# ---------------------------------------------------------------------------


def test_a_falsified_response_count_is_detected() -> None:
    """A summary nobody re-derived is a summary nobody checked."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["summary"]["responses"] += 4
    problems = srp.validate_state_response_plan(tampered)
    assert any("the body carries" in problem for problem in problems), problems


def test_a_falsified_per_channel_breakdown_is_detected() -> None:
    """Counting right in total and wrong per channel is still counting wrong."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["summary"]["responses_by_channel"] = {"district_air": 99}
    problems = srp.validate_state_response_plan(tampered)
    assert any("per channel" in problem for problem in problems), problems


def test_a_falsified_signal_list_is_detected() -> None:
    """A plan may not claim it read a field none of its responses came from."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["summary"]["signals"] = ["trust"]
    problems = srp.validate_state_response_plan(tampered)
    assert any("the body reads" in problem for problem in problems), problems


def test_a_falsified_refusal_count_is_detected() -> None:
    """Under-reporting refusals hides exactly what refusals exist to publish."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["summary"]["refused"] = 7
    problems = srp.validate_state_response_plan(tampered)
    assert any("refusals" in problem for problem in problems), problems


def test_a_wrong_plan_format_is_detected() -> None:
    """The document must say what it is."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["format"] = "living_diorama_motion_plan"
    tampered["schema_version"] = 4
    problems = srp.validate_state_response_plan(tampered)
    assert any("format must be" in problem for problem in problems), problems
    assert any("schema_version must be" in problem for problem in problems), problems


def test_a_relabelled_source_path_is_detected() -> None:
    """A directive pointed at another district's field is caught by re-derivation."""
    tampered = copy.deepcopy(CANONICAL)
    for entry in tampered["responses"]:
        if entry["channel"] == "district_air":
            entry["source_path"] = "world.districts[district_d].trust"
            break
    problems = srp.validate_state_response_plan(tampered)
    assert any("does not name its own district and field" in problem for problem in problems)


def test_a_blank_source_path_is_detected() -> None:
    """Provenance made of whitespace is no provenance at all."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["responses"][0]["source_path"] = "   "
    problems = srp.validate_state_response_plan(tampered)
    assert any("carries no source path" in problem for problem in problems), problems


@pytest.mark.parametrize("reading", ["0.25", None, True])
def test_a_non_real_reading_is_detected(reading: object) -> None:
    """A reading that is not a number cannot be checked against the world it names."""
    tampered = copy.deepcopy(CANONICAL)
    for entry in tampered["responses"]:
        if entry["channel"] == "district_air":
            entry["source_value"] = reading
            break
    problems = srp.validate_state_response_plan(tampered)
    assert any("non-real reading" in problem for problem in problems), problems


@pytest.mark.parametrize("reading", [-0.5, 1.5])
def test_a_reading_outside_the_fields_domain_is_detected(reading: float) -> None:
    """A plan may not publish a reading the field it names could never hold."""
    tampered = copy.deepcopy(CANONICAL)
    for entry in tampered["responses"]:
        if entry["channel"] == "district_air":
            entry["source_value"] = reading
            break
    problems = srp.validate_state_response_plan(tampered)
    assert any("outside the field's own domain" in problem for problem in problems), problems


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_a_non_finite_response_value_is_detected(value: float) -> None:
    """A ``NaN`` driven into a material would be a value nothing downstream could catch."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["responses"][0]["value"] = value
    problems = srp.validate_state_response_plan(tampered)
    assert any("non-finite value" in problem for problem in problems), problems


def test_a_non_real_response_value_is_detected() -> None:
    """Nor can a string be keyed into a socket, however numeric it looks."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["responses"][0]["value"] = "0.001925"
    problems = srp.validate_state_response_plan(tampered)
    assert any("non-real value" in problem for problem in problems), problems


def test_two_responses_driving_one_property_are_detected() -> None:
    """One property cannot carry two readings, and the auditor says which two."""
    tampered = copy.deepcopy(CANONICAL)
    air = [entry for entry in tampered["responses"] if entry["channel"] == "district_air"]
    air[0]["target"] = copy.deepcopy(air[1]["target"])
    problems = srp.validate_state_response_plan(tampered)
    assert any("drive the same target" in problem for problem in problems), problems


def test_responses_shuffled_out_of_their_own_order_are_detected() -> None:
    """A plan that lost its order lost the property that made its hash mean anything."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["responses"] = list(reversed(tampered["responses"]))
    problems = srp.validate_state_response_plan(tampered)
    assert any("not in their own total order" in problem for problem in problems), problems


def test_a_body_that_is_not_an_array_is_detected() -> None:
    """The auditor stops rather than guessing what a mapping of responses meant."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["responses"] = {"district_a": {}}
    assert "responses must be a JSON array" in srp.validate_state_response_plan(tampered)


def test_a_missing_summary_is_detected() -> None:
    """A plan with no summary makes no checkable claim about itself."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["summary"] = []
    assert "summary must be a JSON object" in srp.validate_state_response_plan(tampered)


def test_a_missing_refusal_block_is_detected() -> None:
    """Where refusals are published, the block that publishes them must exist."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["refused"] = []
    problems = srp.validate_state_response_plan(tampered)
    assert any("refused must be a JSON object" in problem for problem in problems), problems


# ---------------------------------------------------------------------------
# The canonical world, where this machine has it
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not WORK_EXPORT.exists(),
    reason="the canonical world export is absent on this machine; the derivation "
    "rules are proven against synthetic exports instead, and the story's own "
    "readings can only be pinned against the world that produced them",
)
def test_the_canonical_episode_shows_the_scarcity_it_actually_recorded() -> None:
    """One district starved and three did not, and the film says exactly that.

    The mid episode of the canonical chain holds ``district_b`` at scarcity 1.0
    and the other three at 0.0. So the plan must put district_b at the declared
    maximum response and the rest at the declared minimum -- the widest spread
    the contract allows, read from a world nobody built for this test.
    """
    document = ss.load_render_export(WORK_EXPORT)
    plan = plan_for(document)
    policy = srs.require_channel(SPEC, "district_air")
    assert srp.validate_state_response_plan(plan) == []
    scales = {
        entry["semantic_id"]: entry["response_scale"]
        for entry in plan["responses"]
        if entry["channel"] == "district_air"
    }
    assert scales["district_b"] == policy["response_maximum"]
    assert {name for name, scale in scales.items() if scale == policy["response_minimum"]} == {
        "district_a",
        "district_c",
        "district_d",
    }
