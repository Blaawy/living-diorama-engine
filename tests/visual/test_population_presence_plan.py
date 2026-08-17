"""Contract tests for the pure Population Presence Plan V1.

Pure pytest -- no Blender. Every export here is built in-test from the
canonical Master Scene Spec's own district list, so the suite proves the
PLANNING RULES rather than one recorded story.

The rules under test are the ones that make a populated city an honest claim:
the visible count follows from authoritative population and nothing else, a
district that grows extends its people instead of rearranging them, an empty
district shows nobody, and the same inputs always produce the same plan no
matter what order anything was written in.
"""

import copy
import importlib
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"
CONFIG_DIR = REPO_ROOT / "visual" / "blender" / "config"


def _load(name: str):
    """Import one pure visual module the same way Blender does: by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


ppp = _load("population_presence_plan")
figure_kit = _load("figure_kit")
pps = _load("population_presence_spec")
pt = _load("pedestrian_topology")
scene_spec = _load("scene_spec")
production_spec = _load("production_spec")
road_graph = _load("road_graph")
urban_fabric = _load("urban_fabric")

MASTER = scene_spec.load_master_scene_spec(CONFIG_DIR / "master_scene_v1.json")
PRODUCTION = production_spec.load_production_world_spec(CONFIG_DIR / "production_world_v1.json")
PRESENCE = pps.load_population_presence_spec(CONFIG_DIR / "population_presence_v1.json")
GRAPH = road_graph.build_road_graph(MASTER, PRODUCTION)
FABRIC = urban_fabric.plan_urban_fabric(MASTER, PRODUCTION, GRAPH)
TOPOLOGY = pt.plan_pedestrian_topology(MASTER, PRODUCTION, GRAPH, FABRIC, PRESENCE)

DISTRICT_IDS = tuple(sorted(MASTER["districts"]))

STORY_POPULATIONS = {
    "district_a": 140,
    "district_b": 60,
    "district_c": 90,
    "district_d": 110,
}
"""The populations the real engine story actually holds, used as the default."""


def district(district_id: str, population: int) -> dict:
    """One export district entry with the fields the presence mapping reads."""
    return {
        "id": district_id,
        "created_tick": 0,
        "population": population,
        "housing_capacity": 400,
        "production_rate": 10.0,
        "consumption_rate": 0.1,
        "scarcity": 0.0,
        "fear": 0.0,
        "trust": 1.0,
        "institutional_pressure": 0.0,
        "isolation_state": "OPEN",
        "resources": {"FOOD": 60.0, "MATERIALS": 60.0, "ENERGY": 60.0},
    }


def export(populations: dict[str, int] | None = None, *, ids=DISTRICT_IDS) -> dict:
    """A Render Export V1 document agreeing with the canonical master scene."""
    populations = {**STORY_POPULATIONS, **(populations or {})}
    return {
        "format": "living_diorama_render_export",
        "schema_version": 1,
        "source": {
            "engine_version": "0.0.1",
            "episode": 0,
            "tick": 0,
            "state_hash": "0" * 64,
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
            "districts": [district(entry, populations.get(entry, 0)) for entry in ids],
            "boundaries": [],
            "infrastructure": [],
            "laws": [],
            "walls": [],
        },
        "events": [],
        "memory": {"facts": []},
    }


def plan_for(populations: dict[str, int] | None = None) -> dict:
    """The presence plan for one set of district populations."""
    return ppp.plan_population_presence(export(populations), MASTER, PRESENCE, TOPOLOGY)


CANONICAL = plan_for()


# ---------------------------------------------------------------------------
# Truth: the count follows from population
# ---------------------------------------------------------------------------


def test_the_canonical_plan_validates() -> None:
    """Every claim in the plan re-derives from the export and the topology."""
    errors = ppp.validate_population_presence_plan(CANONICAL, export(), MASTER, PRESENCE, TOPOLOGY)
    assert not errors, "\n".join(errors[:5])


def test_every_district_shows_exactly_what_its_population_earns() -> None:
    """No district shows a person its population did not pay for."""
    for district_id, population in STORY_POPULATIONS.items():
        entry = CANONICAL["districts"][district_id]
        assert entry["population"] == population
        assert entry["earned_proxies"] == pps.visible_proxy_count(population, PRESENCE)
        assert entry["active_proxies"] == entry["earned_proxies"]


def test_the_total_is_the_sum_of_the_districts() -> None:
    """The summary is arithmetic over the plan, not a separate assertion."""
    total = 0
    for entry in CANONICAL["districts"].values():
        total += entry["active_proxies"]
    assert CANONICAL["summary"]["active_proxies"] == total == len(CANONICAL["proxies"])


def test_zero_population_produces_no_proxies() -> None:
    """An empty district shows nobody, and says so."""
    plan = plan_for({"district_b": 0})
    assert plan["districts"]["district_b"]["active_proxies"] == 0
    assert not [proxy for proxy in plan["proxies"] if proxy["district"] == "district_b"]
    assert "district_b" in plan["summary"]["districts_with_no_presence"]


def test_emptying_one_district_leaves_the_others_alone() -> None:
    """Presence is per-district: one district's collapse is not another's."""
    plan = plan_for({"district_b": 0})
    for district_id in ("district_a", "district_c", "district_d"):
        original = [p for p in CANONICAL["proxies"] if p["district"] == district_id]
        changed = [p for p in plan["proxies"] if p["district"] == district_id]
        assert changed == original


def test_a_whole_world_with_no_residents_shows_nobody() -> None:
    """The degenerate case produces an empty plan rather than an error."""
    plan = plan_for(dict.fromkeys(DISTRICT_IDS, 0))
    assert plan["proxies"] == []
    assert plan["summary"]["active_proxies"] == 0
    assert sorted(plan["summary"]["districts_with_no_presence"]) == list(DISTRICT_IDS)
    assert not ppp.validate_population_presence_plan(
        plan, export(dict.fromkeys(DISTRICT_IDS, 0)), MASTER, PRESENCE, TOPOLOGY
    )


def test_the_plan_states_what_a_proxy_represents() -> None:
    """The manifest sentence is part of the plan, not the report."""
    assert "representative population proxy" in CANONICAL["representation"]
    assert str(PRESENCE["density"]["residents_per_proxy"]) in CANONICAL["representation"]
    assert "does not simulate" in CANONICAL["representation"]


def test_the_plan_records_no_identity_for_anybody() -> None:
    """A proxy is a slot, a place and a posture -- never a person."""
    forbidden = {"name", "home", "destination", "job", "age", "goal", "target"}
    for proxy in CANONICAL["proxies"]:
        assert not (set(proxy) & forbidden), f"{proxy['slot']} carries identity fields"


# ---------------------------------------------------------------------------
# Stability: the slot contract
# ---------------------------------------------------------------------------


def test_growth_extends_the_slots_it_does_not_reshuffle_them() -> None:
    """The core promise: more people appear AFTER the people already there."""
    grown = plan_for({"district_a": 320})
    before = [p for p in CANONICAL["proxies"] if p["district"] == "district_a"]
    after = [p for p in grown["proxies"] if p["district"] == "district_a"]
    assert len(after) > len(before)
    assert after[: len(before)] == before


def test_growth_is_stable_at_every_step() -> None:
    """Not just one jump: every increase keeps every earlier prefix intact."""
    sequence = [plan_for({"district_a": population}) for population in (40, 70, 140, 220, 320)]
    proxies = [[p for p in plan["proxies"] if p["district"] == "district_a"] for plan in sequence]
    for smaller, larger in zip(proxies, proxies[1:], strict=False):
        assert len(larger) >= len(smaller)
        assert larger[: len(smaller)] == smaller


def test_shrinking_is_the_exact_inverse_of_growing() -> None:
    """A district that loses people keeps the ones with the lowest slot numbers."""
    shrunk = plan_for({"district_a": 40})
    before = [p for p in CANONICAL["proxies"] if p["district"] == "district_a"]
    after = [p for p in shrunk["proxies"] if p["district"] == "district_a"]
    assert len(after) < len(before)
    assert after == before[: len(after)]


def test_slot_ids_are_a_dense_prefix_per_district() -> None:
    """``slot_001`` upward with no gaps: a hole would mean a lost identity."""
    by_district: dict[str, list[int]] = {}
    for proxy in CANONICAL["proxies"]:
        by_district.setdefault(proxy["district"], []).append(proxy["slot_index"])
    for district_id, indices in sorted(by_district.items()):
        assert sorted(indices) == list(range(1, len(indices) + 1)), district_id
        for index in indices:
            slot = f"{district_id}__slot_{index:03d}"
            assert any(proxy["slot"] == slot for proxy in CANONICAL["proxies"])


def test_a_slots_appearance_never_changes_when_others_activate() -> None:
    """A slot's whole visual identity comes from the pool, not from the crowd.

    Local diversity looks at neighbours, so it is resolved over the
    POPULATION-BLIND pool. If it were resolved over the visible subset, a
    district that grew would repaint somebody already standing there.
    """
    grown = plan_for({"district_a": 320})
    axes = (*pps.FIGURE_AXES, "heading", "geometry_key", "height")
    original = {p["slot"]: tuple(p[axis] for axis in axes) for p in CANONICAL["proxies"]}
    for proxy in grown["proxies"]:
        if proxy["slot"] in original:
            assert tuple(proxy[axis] for axis in axes) == original[proxy["slot"]]


def test_the_slot_pool_does_not_depend_on_population() -> None:
    """The ground decides the slots; population only decides how many are lit.

    Proved by taking the largest plan any population could produce and showing
    every smaller one is a prefix of it.
    """
    saturated = plan_for(dict.fromkeys(DISTRICT_IDS, 100_000))
    for populations in ({"district_a": 40}, {"district_a": 140}, STORY_POPULATIONS):
        plan = plan_for(populations)
        for district_id in DISTRICT_IDS:
            small = [p for p in plan["proxies"] if p["district"] == district_id]
            large = [p for p in saturated["proxies"] if p["district"] == district_id]
            assert small == large[: len(small)], district_id


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_the_same_inputs_produce_the_same_plan() -> None:
    """Byte for byte, hash for hash."""
    again = plan_for()
    assert again == CANONICAL
    assert ppp.plan_hash(again) == ppp.plan_hash(CANONICAL)


def test_the_plan_hash_changes_when_the_plan_does() -> None:
    """A digest that never moved would prove nothing."""
    assert ppp.plan_hash(plan_for({"district_a": 320})) != ppp.plan_hash(CANONICAL)


def test_the_plan_does_not_depend_on_district_order_in_the_export() -> None:
    """A reordered export is the same world and must give the same plan."""
    reordered = export()
    reordered["world"]["districts"] = list(reversed(reordered["world"]["districts"]))
    plan = ppp.plan_population_presence(reordered, MASTER, PRESENCE, TOPOLOGY)
    assert plan == CANONICAL


def test_the_plan_does_not_depend_on_master_spec_mapping_order() -> None:
    """Reversing the master scene's own dicts changes nothing."""
    master = copy.deepcopy(MASTER)
    master["districts"] = dict(reversed(list(master["districts"].items())))
    plan = ppp.plan_population_presence(export(), master, PRESENCE, TOPOLOGY)
    assert plan == CANONICAL


def test_proxies_are_published_in_slot_order() -> None:
    """A stable published order, independent of how the pools were walked."""
    slots = [proxy["slot"] for proxy in CANONICAL["proxies"]]
    assert slots == sorted(slots)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_an_export_naming_an_unknown_district_is_refused() -> None:
    """Presence in a place the city does not have is not presence."""
    stray = export()
    stray["world"]["districts"].append(district("district_z", 100))
    with pytest.raises(ppp.PopulationPlanError, match="district_z"):
        ppp.plan_population_presence(stray, MASTER, PRESENCE, TOPOLOGY)


def test_an_export_missing_a_district_is_refused() -> None:
    """A city built from four districts needs four districts of truth."""
    partial = export()
    partial["world"]["districts"] = partial["world"]["districts"][:2]
    with pytest.raises(ppp.PopulationPlanError, match="missing"):
        ppp.plan_population_presence(partial, MASTER, PRESENCE, TOPOLOGY)


def test_a_duplicated_district_is_refused() -> None:
    """Two rows for one district means two answers to one question."""
    doubled = export()
    doubled["world"]["districts"].append(district("district_a", 999))
    with pytest.raises(ppp.PopulationPlanError, match="twice"):
        ppp.plan_population_presence(doubled, MASTER, PRESENCE, TOPOLOGY)


def test_a_float_population_in_the_export_is_refused() -> None:
    """A population is a count, and a float one means a non-authoritative source."""
    broken = export()
    broken["world"]["districts"][0]["population"] = 140.5
    with pytest.raises(ppp.PopulationPlanError, match="exact integer"):
        ppp.plan_population_presence(broken, MASTER, PRESENCE, TOPOLOGY)


def test_a_boolean_population_in_the_export_is_refused() -> None:
    """``True`` is an int in Python and must never be read as one resident."""
    broken = export()
    broken["world"]["districts"][0]["population"] = True
    with pytest.raises(ppp.PopulationPlanError, match="exact integer"):
        ppp.plan_population_presence(broken, MASTER, PRESENCE, TOPOLOGY)


def test_a_negative_population_is_refused() -> None:
    """The simulation has no negative districts, and neither has presence."""
    broken = export()
    broken["world"]["districts"][0]["population"] = -5
    with pytest.raises(ppp.PopulationPlanError, match="negative"):
        ppp.plan_population_presence(broken, MASTER, PRESENCE, TOPOLOGY)


def test_an_export_with_no_world_is_refused() -> None:
    """A malformed document fails loudly rather than producing an empty city."""
    with pytest.raises(ppp.PopulationPlanError, match="world"):
        ppp.plan_population_presence({}, MASTER, PRESENCE, TOPOLOGY)


def test_a_refusing_exhaustion_policy_raises_when_the_ground_is_short() -> None:
    """``refuse`` means refuse: a pool the city cannot site is an error."""
    spec = copy.deepcopy(PRESENCE)
    spec["slots"]["exhaustion_policy"] = "refuse"
    spec["slots"]["pool_size"] = 10_000
    spec["density"]["max_proxies_per_district"] = 10_000
    spec["density"]["global_max_proxies"] = 40_000
    with pytest.raises(ppp.PopulationPlanError, match="pedestrian-safe ground"):
        ppp.plan_population_presence(export(), MASTER, spec, TOPOLOGY)


def test_a_reducing_exhaustion_policy_records_the_shortfall() -> None:
    """``reduce`` never hides what it dropped.

    A population large enough to earn more people than the city has room for
    is the only way this branch is reachable, so the counterfactual is stated
    outright: every district asks for ten thousand and the ground answers with
    what it actually has.
    """
    spec = copy.deepcopy(PRESENCE)
    spec["slots"]["pool_size"] = 10_000
    spec["density"]["max_proxies_per_district"] = 10_000
    spec["density"]["global_max_proxies"] = 40_000
    plan = ppp.plan_population_presence(
        export(dict.fromkeys(DISTRICT_IDS, 1_000_000)), MASTER, spec, TOPOLOGY
    )
    assert plan["summary"]["reduced_by_ground"] > 0
    for entry in plan["districts"].values():
        assert entry["pool_size_available"] < entry["pool_size_requested"]
        assert entry["granted_proxies"] > entry["active_proxies"]
        assert entry["active_proxies"] == entry["pool_size_available"]
        assert entry["reduced_by_ground"] == entry["granted_proxies"] - entry["active_proxies"]


# ---------------------------------------------------------------------------
# Placement legality and the global ceiling
# ---------------------------------------------------------------------------


def test_every_proxy_stands_on_ground_the_topology_offered_its_district() -> None:
    """A plan may only use ground that was proven clear for that district."""
    for proxy in CANONICAL["proxies"]:
        offered = TOPOLOGY["zones"][proxy["district"]][proxy["zone"]]
        assert any(
            candidate["x"] == proxy["x"] and candidate["y"] == proxy["y"] for candidate in offered
        ), f"{proxy['slot']} stands where nobody offered it ground"


def test_no_two_proxies_stand_on_top_of_each_other() -> None:
    """Separation holds across the whole world, not just within a district."""
    separation = float(PRESENCE["proxy"]["separation"])
    proxies = CANONICAL["proxies"]
    for first in range(len(proxies)):
        for second in range(first + 1, len(proxies)):
            gap = math.hypot(
                proxies[first]["x"] - proxies[second]["x"],
                proxies[first]["y"] - proxies[second]["y"],
            )
            assert gap >= separation, (
                f"{proxies[first]['slot']} and {proxies[second]['slot']} are {gap} apart"
            )


def test_the_saturated_world_also_keeps_its_distance() -> None:
    """Separation is a property of the pool, so it holds at full occupancy too."""
    separation = float(PRESENCE["proxy"]["separation"])
    proxies = plan_for(dict.fromkeys(DISTRICT_IDS, 100_000))["proxies"]
    for first in range(len(proxies)):
        for second in range(first + 1, len(proxies)):
            assert (
                math.hypot(
                    proxies[first]["x"] - proxies[second]["x"],
                    proxies[first]["y"] - proxies[second]["y"],
                )
                >= separation
            )


def test_the_global_ceiling_binds_when_it_has_to() -> None:
    """A world-wide cap reduces proportionally and says that it did."""
    spec = copy.deepcopy(PRESENCE)
    spec["density"]["global_max_proxies"] = 40
    plan = ppp.plan_population_presence(export(), MASTER, spec, TOPOLOGY)
    assert plan["density"]["global_ceiling_applied"] is True
    assert plan["summary"]["active_proxies"] <= 40
    assert all(entry["active_proxies"] > 0 for entry in plan["districts"].values())


def test_the_global_ceiling_never_empties_a_populated_district() -> None:
    """Its own stated guarantee, exercised where proportional rounding breaks it.

    Largest-remainder alone can floor a small district to zero while a large
    sibling keeps dozens. A populated district rendered empty is a false
    statement about the world, not a rounding detail, so the allocation borrows
    one back from the largest.
    """
    spec = copy.deepcopy(PRESENCE)
    spec["density"]["global_max_proxies"] = 32
    lopsided = plan_for({"district_a": 100_000, "district_b": 5, "district_c": 5, "district_d": 5})
    plan = ppp.plan_population_presence(
        export({"district_a": 100_000, "district_b": 5, "district_c": 5, "district_d": 5}),
        MASTER,
        spec,
        TOPOLOGY,
    )
    assert plan["density"]["global_ceiling_applied"] is True
    assert plan["summary"]["active_proxies"] <= 32
    for district_id in DISTRICT_IDS:
        assert lopsided["districts"][district_id]["earned_proxies"] > 0
        assert plan["districts"][district_id]["active_proxies"] > 0, (
            f"{district_id} has residents but the ceiling rendered it empty"
        )


def test_the_ceiling_still_empties_nobody_it_was_not_asked_to() -> None:
    """A district with no residents is not given a proxy by the floor rule."""
    spec = copy.deepcopy(PRESENCE)
    spec["density"]["global_max_proxies"] = 32
    plan = ppp.plan_population_presence(
        export({"district_a": 100_000, "district_b": 0, "district_c": 5, "district_d": 5}),
        MASTER,
        spec,
        TOPOLOGY,
    )
    assert plan["districts"]["district_b"]["active_proxies"] == 0


def test_the_per_district_clamp_is_never_silent() -> None:
    """A population that earns more people than policy shows says so in the plan.

    ``visible_proxy_count`` clamps to ``max_proxies_per_district``. Publishing
    only the clamped number while still claiming every body stands for exactly
    ``residents_per_proxy`` residents would overstate what the render shows, so
    the plan carries the unclamped count and the difference.
    """
    plan = plan_for({"district_a": 100_000})
    entry = plan["districts"]["district_a"]
    assert entry["scaled_proxies"] > entry["earned_proxies"]
    assert entry["clamped_by_policy"] == entry["scaled_proxies"] - entry["earned_proxies"]
    assert entry["earned_proxies"] == PRESENCE["density"]["max_proxies_per_district"]
    assert plan["summary"]["clamped_by_policy"] > 0
    assert plan["summary"]["districts_clamped_by_policy"] == ["district_a"]


def test_the_canonical_world_clamps_nobody_and_says_so() -> None:
    """No silent caps: the shipped world states that nothing was clipped."""
    assert CANONICAL["summary"]["clamped_by_policy"] == 0
    assert CANONICAL["summary"]["districts_clamped_by_policy"] == []
    for entry in CANONICAL["districts"].values():
        assert entry["scaled_proxies"] == entry["earned_proxies"] == entry["active_proxies"]


def test_the_unclamped_count_matches_the_declared_scale() -> None:
    """The pre-clamp number really is population over the density ratio."""
    ratio = float(PRESENCE["density"]["residents_per_proxy"])
    for population in (0, 4, 5, 90, 140, 320, 100_000):
        expected = (
            0
            if population < PRESENCE["density"]["visibility_threshold"]
            else max(int(population // ratio), PRESENCE["density"]["min_proxies_per_district"])
        )
        assert pps.unclamped_proxy_count(population, PRESENCE) == expected


def test_the_validator_catches_a_district_showing_too_few() -> None:
    """Under-showing is as much a lie as over-showing, and both are refused."""
    tampered = copy.deepcopy(CANONICAL)
    district_a = [p for p in tampered["proxies"] if p["district"] == "district_a"]
    tampered["proxies"].remove(district_a[-1])
    tampered["districts"]["district_a"]["active_proxies"] -= 1
    tampered["summary"]["active_proxies"] -= 1
    tampered["summary"]["proxies_by_district"]["district_a"] -= 1
    errors = ppp.validate_population_presence_plan(tampered, export(), MASTER, PRESENCE, TOPOLOGY)
    assert errors, "a district quietly showing one person fewer was accepted"
    assert any("re-derivation" in error for error in errors)


def test_the_validator_catches_a_tampered_summary() -> None:
    """The summary is re-derived, not trusted."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["summary"]["proxies_by_zone"]["promenade"] += 99
    errors = ppp.validate_population_presence_plan(tampered, export(), MASTER, PRESENCE, TOPOLOGY)
    assert any("summary proxies_by_zone" in error for error in errors)


def test_the_global_ceiling_is_reported_as_unused_when_it_is() -> None:
    """No silent caps: the canonical run states that nothing was clipped."""
    assert CANONICAL["density"]["global_ceiling_applied"] is False
    assert CANONICAL["summary"]["reduced_by_ground"] == 0


def test_the_global_ceiling_reduction_is_deterministic() -> None:
    """Largest-remainder, with district id as the tie-break."""
    spec = copy.deepcopy(PRESENCE)
    spec["density"]["global_max_proxies"] = 37
    first = ppp.plan_population_presence(export(), MASTER, spec, TOPOLOGY)
    second = ppp.plan_population_presence(export(), MASTER, spec, TOPOLOGY)
    assert ppp.plan_hash(first) == ppp.plan_hash(second)
    assert first["summary"]["active_proxies"] == 37


# ---------------------------------------------------------------------------
# Distribution and dressing
# ---------------------------------------------------------------------------


def test_presence_is_spread_across_the_approved_area_types() -> None:
    """Not everybody on one street: the spread policy is actually applied."""
    used = {proxy["zone"] for proxy in CANONICAL["proxies"]}
    assert len(used) >= 3
    assert used <= set(pps.ZONE_TYPES)


def test_the_port_district_reaches_its_waterfront() -> None:
    """A policy that names the promenade must actually put somebody on it."""
    port = [
        proxy
        for proxy in CANONICAL["proxies"]
        if MASTER["districts"][proxy["district"]]["character"] == "port"
    ]
    assert port
    assert any(proxy["zone"] == "promenade" for proxy in port)


def test_the_zone_sequence_is_proportional_and_truncation_stable() -> None:
    """The interleave is both proportional and a stable prefix."""
    weights = {"frontage": 4.0, "plaza": 2.0, "park": 2.0, "promenade": 0.0}
    full = ppp.zone_sequence(weights, 16)
    assert "promenade" not in full, "a zero weight must claim no slots"
    assert full.count("frontage") == 8
    assert full.count("plaza") == 4
    assert full.count("park") == 4
    for length in (1, 3, 7, 12):
        assert ppp.zone_sequence(weights, length) == full[:length]


def test_the_zone_sequence_handles_a_single_funded_zone() -> None:
    """A district with one usable area type spends everything there."""
    sequence = ppp.zone_sequence({"frontage": 1.0}, 5)
    assert sequence == ["frontage"] * 5


def test_every_proxy_is_dressed_from_the_declared_vocabulary() -> None:
    """Every axis of every identity comes only from the spec."""
    for proxy in CANONICAL["proxies"]:
        for axis in pps.FIGURE_AXES:
            assert proxy[axis] in pps.AXIS_VALUES[axis], f"{proxy['slot']} {axis}={proxy[axis]}"
        assert 1.0 < proxy["height"] < 2.1


def test_every_identity_obeys_its_age_rules() -> None:
    """The declared coherence rules actually constrain what gets drawn."""
    rules = PRESENCE["figure"]["age_rules"]
    for proxy in CANONICAL["proxies"]:
        for axis, permitted in rules.get(proxy["age_presentation"], {}).items():
            assert proxy[axis] in permitted, (
                f"{proxy['slot']} is a {proxy['age_presentation']} with {axis}={proxy[axis]}"
            )


def test_no_child_carries_facial_hair() -> None:
    """The rule a reviewer would check first, checked explicitly."""
    for proxy in CANONICAL["proxies"]:
        if proxy["age_presentation"] in ("child", "teen"):
            assert proxy["facial_hair"] == "none"


def test_the_population_is_visibly_diverse() -> None:
    """A city contains different kinds of people, and the plan must show it."""
    proxies = CANONICAL["proxies"]
    ages = {proxy["age_presentation"] for proxy in proxies}
    assert ages == set(figure_kit.AGE_PRESENTATIONS), f"only {sorted(ages)} appear"
    assert len({proxy["build"] for proxy in proxies}) >= 4
    assert len({proxy["stature"] for proxy in proxies}) == 3
    assert len({proxy["hair"] for proxy in proxies}) >= 5
    assert len({proxy["clothing"] for proxy in proxies}) >= 5
    assert len({proxy["presentation"] for proxy in proxies}) == 3
    assert len({proxy["pose"] for proxy in proxies}) == 4
    assert len({proxy["complexion"] for proxy in proxies}) >= 4


def test_no_two_visible_people_are_the_same_body() -> None:
    """Not one clone anywhere in the canonical city."""
    keys = [proxy["geometry_key"] for proxy in CANONICAL["proxies"]]
    assert len(set(keys)) == len(keys), "two proxies share a complete body"


def test_neighbours_never_share_a_silhouette() -> None:
    """The local-diversity rule, checked at the distance it claims to work at."""
    radius = float(PRESENCE["figure"]["diversity"]["radius"])
    proxies = CANONICAL["proxies"]
    for first in range(len(proxies)):
        for second in range(first + 1, len(proxies)):
            gap = math.hypot(
                proxies[first]["x"] - proxies[second]["x"],
                proxies[first]["y"] - proxies[second]["y"],
            )
            if gap > radius:
                continue
            assert figure_kit.silhouette_signature(
                proxies[first]
            ) != figure_kit.silhouette_signature(proxies[second]), (
                f"{proxies[first]['slot']} and {proxies[second]['slot']} stand "
                f"{round(gap, 2)} apart and read as the same person"
            )


def test_children_are_shorter_than_every_adult() -> None:
    """A child must be unmistakable at proof distance, not merely smaller."""
    children = [p for p in CANONICAL["proxies"] if p["age_presentation"] == "child"]
    adults = [p for p in CANONICAL["proxies"] if p["age_presentation"] == "adult"]
    assert children and adults
    assert max(p["height"] for p in children) < min(p["height"] for p in adults)


def test_children_are_built_like_children_not_scaled_adults() -> None:
    """The head-to-height ratio is the cue, and it must be a real difference."""
    for proxy in CANONICAL["proxies"]:
        ratio = proxy["head_height"] / proxy["height"]
        if proxy["age_presentation"] == "child":
            assert ratio > 0.17, f"{proxy['slot']} is a child with an adult head ratio {ratio}"
        if proxy["age_presentation"] == "adult":
            assert ratio < 0.15, f"{proxy['slot']} is an adult with a child head ratio {ratio}"


def test_builds_differ_in_shape_not_only_in_size() -> None:
    """A broad figure is broader across the shoulders than a slim one of a height."""
    slim = figure_kit.figure_dimensions(
        {
            "age_presentation": "adult",
            "stature": "average",
            "build": "slim",
            "presentation": "unspecified",
        }
    )
    broad = figure_kit.figure_dimensions(
        {
            "age_presentation": "adult",
            "stature": "average",
            "build": "broad",
            "presentation": "unspecified",
        }
    )
    athletic = figure_kit.figure_dimensions(
        {
            "age_presentation": "adult",
            "stature": "average",
            "build": "athletic",
            "presentation": "unspecified",
        }
    )
    assert slim["height"] == broad["height"] == athletic["height"]
    assert broad["shoulder_width"] > slim["shoulder_width"] * 1.2
    assert broad["hip_width"] > athletic["hip_width"] * 1.2
    assert athletic["shoulder_width"] / athletic["hip_width"] > (
        slim["shoulder_width"] / slim["hip_width"]
    )


def test_heading_jitter_stays_inside_its_declared_bound() -> None:
    """Jitter never turns a body away from what its zone orients it towards."""
    jitter = float(PRESENCE["proxy"]["heading_jitter"])
    for proxy in CANONICAL["proxies"]:
        offered = TOPOLOGY["zones"][proxy["district"]][proxy["zone"]]
        base = next(
            candidate["heading"]
            for candidate in offered
            if candidate["x"] == proxy["x"] and candidate["y"] == proxy["y"]
        )
        difference = abs(proxy["heading"] - base)
        assert difference <= jitter + 1.0e-6


# ---------------------------------------------------------------------------
# The canonical fleet: a portable pin and the geometry budget
# ---------------------------------------------------------------------------


MAX_TRIANGLES_PER_FIGURE = 950
MAX_FLEET_TRIANGLES = 68000
"""The remediation's geometry ceilings, restated where the fleet is planned.

The per-figure 950 must stay equal to ``MAX_TRIANGLES_PER_FIGURE`` in
``test_figure_kit.py``: the kit suite proves no body the VOCABULARY can build
exceeds it, and this suite proves the bodies the canonical story actually
FIELDS stay under both it and the 68,000 layer ceiling. Two constants that
drifted apart would let a budget argument pass in one court and fail in the
other. Measured against the FINAL kit on 2026-08-16, the canonical eighty
cost 66,300 of the 68,000 ceiling -- only 1,700 spare -- at a fleet mean of
828.8, with the heaviest fielded body at 902 (``district_c__slot_011``) and
the lightest at 668 (``district_a__slot_028``).

That margin is thin and this is the test that holds it. Eighty proxies may
average 850; they currently average 828.8, so the whole layer rides on about
twenty-one triangles a person. The heaviest body the vocabulary can build is
902, and eighty of those would be 72,160 -- so the fleet fits because the
dressing draw spreads across light and heavy identities, not because every
identity fits. That is precisely why the sum below walks the real eighty
instead of multiplying a maximum, and why a change to the dressing weights
is a change to the geometry budget whether or not any body grew.

That fleet mean is NOT the vocabulary mean of 830.3 that ``test_figure_kit``
records: the fleet is the eighty bodies the story actually dresses, not an
average over every combination the kit can build. Multiplying the vocabulary
mean by eighty gives a total some three hundred triangles adrift, which is
why the sum below is taken PER PROXY rather than estimated -- that per-proxy
sum is the number which actually gates the 68,000.

Evidence for the headroom, not a second contract; only the two ceilings are
asserted.
"""


def test_the_canonical_story_fields_eighty_unique_slots() -> None:
    """Eighty proxies, eighty distinct slots, from the repo's own numbers.

    This pin is PORTABLE on purpose: ``CANONICAL`` derives from the in-repo
    ``STORY_POPULATIONS`` and the synthetic export above, so the eighty holds
    on any machine with no generated story file present. The mobility suite
    pins the same eighty only where the canonical world export exists; this is
    the copy of that promise a fresh checkout can still enforce.
    """
    slots = [proxy["slot"] for proxy in CANONICAL["proxies"]]
    assert len(slots) == 80, f"the canonical story fields {len(slots)} proxies"
    assert len(set(slots)) == len(slots), "two proxies share one slot"
    assert CANONICAL["summary"]["active_proxies"] == 80


def test_the_canonical_fleet_fits_the_declared_triangle_budget() -> None:
    """The eighty bodies the story fields fit the remediation's ceilings.

    The kit suite bounds the whole vocabulary; this bounds the FLEET, because
    a dressing draw that drifted heavy -- every proxy in a coat with a beard
    -- would blow the layer budget without any single body breaking its own.
    """
    counts = [figure_kit.figure_triangles(proxy) for proxy in CANONICAL["proxies"]]
    heaviest = max(counts)
    assert heaviest <= MAX_TRIANGLES_PER_FIGURE, f"the heaviest proxy costs {heaviest}"
    assert sum(counts) <= MAX_FLEET_TRIANGLES, f"the fleet costs {sum(counts)} triangles"


# ---------------------------------------------------------------------------
# The validator has teeth
# ---------------------------------------------------------------------------


def test_a_tampered_count_is_detected() -> None:
    """Claiming more people than population earns must not survive validation."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["districts"]["district_a"]["earned_proxies"] += 5
    errors = ppp.validate_population_presence_plan(tampered, export(), MASTER, PRESENCE, TOPOLOGY)
    assert any("earned proxies" in error for error in errors)


def test_a_tampered_population_is_detected() -> None:
    """The plan's population must match the export's."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["districts"]["district_a"]["population"] = 999
    errors = ppp.validate_population_presence_plan(tampered, export(), MASTER, PRESENCE, TOPOLOGY)
    assert any("does not match the export" in error for error in errors)


def test_a_moved_proxy_is_detected() -> None:
    """A body relocated to ground nobody offered is caught."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["proxies"][0]["x"] += 3.0
    errors = ppp.validate_population_presence_plan(tampered, export(), MASTER, PRESENCE, TOPOLOGY)
    assert any("never offered" in error for error in errors)


def test_a_broken_slot_sequence_is_detected() -> None:
    """A gap in the slot numbering is a lost identity, and it is refused."""
    tampered = copy.deepcopy(CANONICAL)
    district_a = [p for p in tampered["proxies"] if p["district"] == "district_a"]
    tampered["proxies"].remove(district_a[0])
    tampered["districts"]["district_a"]["active_proxies"] -= 1
    errors = ppp.validate_population_presence_plan(tampered, export(), MASTER, PRESENCE, TOPOLOGY)
    assert any("dense prefix" in error or "naming contract" in error for error in errors)


def test_an_extra_district_in_the_plan_is_detected() -> None:
    """A plan may not invent a district the export never carried."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["districts"]["district_z"] = dict(tampered["districts"]["district_a"])
    errors = ppp.validate_population_presence_plan(tampered, export(), MASTER, PRESENCE, TOPOLOGY)
    assert any("invents district" in error for error in errors)


def test_two_proxies_stacked_on_one_spot_are_detected() -> None:
    """Separation is re-proved by the validator, not trusted from the planner."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["proxies"][1]["x"] = tampered["proxies"][0]["x"]
    tampered["proxies"][1]["y"] = tampered["proxies"][0]["y"]
    errors = ppp.validate_population_presence_plan(tampered, export(), MASTER, PRESENCE, TOPOLOGY)
    assert any("apart" in error for error in errors)


def test_a_wrong_plan_format_is_detected() -> None:
    """The document must say what it is."""
    tampered = copy.deepcopy(CANONICAL)
    tampered["format"] = "something_else"
    errors = ppp.validate_population_presence_plan(tampered, export(), MASTER, PRESENCE, TOPOLOGY)
    assert any("format" in error for error in errors)
