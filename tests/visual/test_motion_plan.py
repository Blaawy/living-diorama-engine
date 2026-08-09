"""Contract tests for the pure MotionPlan V1 derivation.

Pure pytest -- no Blender, and no dependency on generated proof artefacts:
every export here is built in-test from the canonical Master Scene Spec's own
topology, so the suite proves the PLANNING RULES rather than one recorded
story. The real engine's exports are exercised by the Phase 17 gate.

The rules under test are the ones that keep a film honest: a value that did
not change produces nothing, a change with no truthful visual channel is
refused with a reason, the same inputs always produce the same plan, and no
result anywhere depends on the order entries happen to appear in.
"""

import copy
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


def _load(name: str):
    """Import one pure visual module the same way Blender does: by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


mp = _load("motion_plan")
mts = _load("motion_time_spec")
ss = _load("scene_spec")

DISTRICT_IDS = ("district_a", "district_b", "district_c", "district_d")

BOUNDARIES = (
    ("boundary_ab", "district_a", "district_b"),
    ("boundary_ac", "district_a", "district_c"),
    ("boundary_ad", "district_a", "district_d"),
    ("boundary_cd", "district_c", "district_d"),
)

INFRASTRUCTURE = (
    ("infra_ab_transit", "boundary_ab", "TRANSIT_ROUTE"),
    ("infra_ab_resource", "boundary_ab", "RESOURCE_ROUTE"),
    ("infra_ac_transit", "boundary_ac", "TRANSIT_ROUTE"),
)


def district(district_id: str, *, population: int = 100, stock: float = 60.0) -> dict:
    """One export district entry with the fields the visual mapping reads."""
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
        "resources": {"FOOD": stock, "MATERIALS": stock, "ENERGY": stock},
    }


def wall(boundary_id: str, *, integrity: float = 1.0, dependency: float = 0.5) -> dict:
    """One export wall entry."""
    return {
        "id": f"wall_{boundary_id}",
        "created_tick": 9,
        "built_tick": 9,
        "boundary_id": boundary_id,
        "permanent": True,
        "active": True,
        "integrity": integrity,
        "dependency_score": dependency,
        "resource_dependency": dependency,
        "transport_dependency": dependency,
    }


def law(*, active: bool) -> dict:
    """One export law entry for the law the Golden Seal indicates."""
    return {
        "id": mp.MOVEMENT_LAW_ID,
        "created_tick": 0,
        "name": "movement_resource_sharing",
        "active": active,
        "current_value": active,
        "previous_value": not active,
        "changed_episode": 1,
        "restored_tick": None,
    }


def export(
    *,
    walls: tuple[str, ...] = (),
    law_active: bool = True,
    populations: dict[str, int] | None = None,
    stocks: dict[str, float] | None = None,
    dependencies: dict[str, float] | None = None,
    degraded: tuple[str, ...] = (),
    episode: int = 0,
) -> dict:
    """A Render Export V1 document agreeing with the canonical master scene."""
    populations = populations or {}
    stocks = stocks or {}
    dependencies = dependencies or {}
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
                "districts": len(DISTRICT_IDS),
                "boundaries": len(BOUNDARIES),
                "walls": len(walls),
                "laws": 1,
                "infrastructure": len(INFRASTRUCTURE),
            },
        },
        "world": {
            "districts": [
                district(
                    district_id,
                    population=populations.get(district_id, 100),
                    stock=stocks.get(district_id, 60.0),
                )
                for district_id in DISTRICT_IDS
            ],
            "boundaries": [
                {
                    "id": boundary_id,
                    "created_tick": 0,
                    "district_a_id": first,
                    "district_b_id": second,
                    "wall_id": f"wall_{boundary_id}" if boundary_id in walls else None,
                }
                for boundary_id, first, second in BOUNDARIES
            ],
            "walls": [wall(boundary_id) for boundary_id in walls],
            "laws": [law(active=law_active)],
            "infrastructure": [
                {
                    "id": infra_id,
                    "created_tick": 0,
                    "boundary_id": boundary_id,
                    "infrastructure_type": kind,
                    "capacity": 100.0,
                    "dependency_score": dependencies.get(infra_id, 0.0),
                    "degraded": infra_id in degraded,
                }
                for infra_id, boundary_id, kind in INFRASTRUCTURE
            ],
        },
        "events": [],
        "memory": {"through_episode": episode, "through_tick": episode * 10, "facts": []},
    }


@pytest.fixture(scope="module", name="master")
def master_fixture() -> dict:
    """The canonical Master Scene Spec V1."""
    return ss.load_master_scene_spec(CONFIG_DIR / "master_scene_v1.json")


@pytest.fixture(scope="module", name="motion")
def motion_fixture() -> dict:
    """The canonical Motion & Time Spec V1."""
    return mts.load_motion_time_spec(CONFIG_DIR / "motion_time_v1.json")


def refuses(before, after, master, motion, fragment: str) -> None:
    """Assert planning refuses this pair for the stated reason."""
    with pytest.raises(mp.MotionPlanError) as error:
        mp.plan_motion(before, after, master, motion)
    assert fragment in str(error.value)


def test_an_unchanged_world_produces_no_directives(master, motion) -> None:
    """Nothing moved, so nothing moves. The empty plan is the honest answer."""
    state = export()
    plan = mp.plan_motion(state, copy.deepcopy(state), master, motion)
    assert plan["directives"] == []
    assert plan["summary"]["directive_count"] == 0
    assert plan["summary"]["by_channel"] == {}


def test_the_same_inputs_always_produce_the_same_plan(master, motion) -> None:
    """Determinism is the whole contract: same story, same film, every run."""
    before = export(law_active=True)
    after = export(walls=("boundary_ab",), law_active=False, stocks={"district_a": 200.0})
    first = mp.plan_motion(before, after, master, motion)
    second = mp.plan_motion(
        copy.deepcopy(before), copy.deepcopy(after), master, copy.deepcopy(motion)
    )
    assert mp.plan_hash(first) == mp.plan_hash(second)
    assert mp.canonical_plan_bytes(first) == mp.canonical_plan_bytes(second)


def test_the_plan_does_not_depend_on_mapping_order(master, motion) -> None:
    """Shuffled export arrays are the same world and must plan identically."""
    before = export(law_active=True)
    after = export(walls=("boundary_ab",), law_active=False, stocks={"district_c": 300.0})
    baseline = mp.plan_hash(mp.plan_motion(before, after, master, motion))
    generator = random.Random(20260809)
    for _ in range(8):
        shuffled_before = copy.deepcopy(before)
        shuffled_after = copy.deepcopy(after)
        for document in (shuffled_before, shuffled_after):
            for key in ("districts", "boundaries", "walls", "laws", "infrastructure"):
                generator.shuffle(document["world"][key])
        assert mp.plan_hash(mp.plan_motion(shuffled_before, shuffled_after, master, motion)) == (
            baseline
        )


def test_directives_are_totally_ordered(master, motion) -> None:
    """A stable order makes plans diffable and hashes meaningful."""
    plan = mp.plan_motion(
        export(law_active=True),
        export(walls=("boundary_ab",), law_active=False, stocks={"district_b": 90.0}),
        master,
        motion,
    )
    keys = [
        (d["channel"], d["semantic_id"], json.dumps(d["target"], sort_keys=True))
        for d in plan["directives"]
    ]
    assert keys == sorted(keys)


def test_a_law_that_changes_standing_lights_or_darkens_the_seal(master, motion) -> None:
    """The Seal answers the law; it is never redesigned and never moves."""
    plan = mp.plan_motion(export(law_active=True), export(law_active=False), master, motion)
    directives = [d for d in plan["directives"] if d["channel"] == "law_seal_glow"]
    assert len(directives) == 1
    directive = directives[0]
    assert directive["from_value"] == mp.SEAL_GLOW_ACTIVE
    assert directive["to_value"] == mp.SEAL_GLOW_INACTIVE
    assert directive["target"]["material"] == mp.SEAL_GLOW_MATERIAL
    assert mp.MOVEMENT_LAW_ID in directive["source_before"]


def test_a_law_that_did_not_change_standing_emits_nothing(master, motion) -> None:
    """A restored law whose flag never moved is not a visual event."""
    plan = mp.plan_motion(export(law_active=True), export(law_active=True), master, motion)
    assert [d for d in plan["directives"] if d["channel"] == "law_seal_glow"] == []


@pytest.mark.parametrize("value", [1, 1.0, "true", None])
def test_a_non_boolean_law_flag_is_refused(master, motion, value) -> None:
    """``1``, ``1.0`` and ``"true"`` are six different things from ``True``."""
    after = export(law_active=False)
    after["world"]["laws"][0]["active"] = value
    refuses(export(law_active=True), after, master, motion, "non-boolean active value")


def test_a_law_present_in_only_one_export_is_refused(master, motion) -> None:
    """A law the Seal indicates does not blink into existence."""
    after = export(law_active=False)
    after["world"]["laws"] = []
    refuses(export(law_active=True), after, master, motion, "exists in only one export")


def test_a_wall_the_engine_built_rises(master, motion) -> None:
    """A scar that appears between two states is a real construction event."""
    plan = mp.plan_motion(export(), export(walls=("boundary_ab",)), master, motion)
    walls = [d for d in plan["directives"] if d["channel"] == "wall_presence"]
    assert len(walls) == 1
    assert walls[0]["semantic_id"] == "wall_boundary_ab"
    assert walls[0]["target"] == {
        "kind": "object_group_presence",
        "prefix": "LD_WALL__wall_boundary_ab",
    }
    assert walls[0]["from_value"] == 0.0
    assert walls[0]["to_value"] == 1.0
    assert walls[0]["rise_metres"] > 0.0
    assert walls[0]["member_span_frames"] >= 1


def test_a_wall_that_persists_emits_nothing(master, motion) -> None:
    """THE WORLD REMEMBERS: a standing wall is not re-built every episode."""
    standing = export(walls=("boundary_ab",))
    plan = mp.plan_motion(standing, copy.deepcopy(standing), master, motion)
    assert [d for d in plan["directives"] if d["channel"] == "wall_presence"] == []


def test_a_vanishing_wall_is_refused(master, motion) -> None:
    """History persists; a removal the engine never recorded is a lie."""
    refuses(
        export(walls=("boundary_ab",)),
        export(),
        master,
        motion,
        "the world remembers",
    )


def test_a_wall_that_changes_integrity_is_refused(master, motion) -> None:
    """Integrity drives canonical segment heights; V1 cannot morph geometry."""
    after = export(walls=("boundary_ab",))
    after["world"]["walls"][0]["integrity"] = 0.4
    refuses(export(walls=("boundary_ab",)), after, master, motion, "no geometry-morph channel")


def test_infrastructure_condition_is_refused_with_its_reason(master, motion) -> None:
    """The locked mapping swaps a MATERIAL for condition, which cannot be keyed.

    This is a deliberate, documented V1 limitation rather than an oversight:
    animating it would mean either driving a property the static application
    never writes, or inventing damage geometry. Both are forbidden, so the
    transition is refused and says why.
    """
    refuses(
        export(),
        export(degraded=("infra_ab_transit",)),
        master,
        motion,
        "refused rather than approximated",
    )


def test_moving_infrastructure_between_boundaries_is_refused(master, motion) -> None:
    """Conduits do not relocate; a spec that says so is malformed, not poetic."""
    after = export()
    after["world"]["infrastructure"][0]["boundary_id"] = "boundary_ac"
    refuses(export(), after, master, motion, "conduits do not relocate")


def test_struts_appear_only_where_the_engine_built_a_wall(master, motion) -> None:
    """Anchoring is a consequence of the scar, never a decoration."""
    plan = mp.plan_motion(
        export(),
        export(walls=("boundary_ab",), dependencies={"infra_ab_transit": 0.72}),
        master,
        motion,
    )
    struts = [d for d in plan["directives"] if d["channel"] == "infra_strut_presence"]
    assert struts, "a new wall must anchor its conduits"
    assert all("wallstrut" in d["target"]["object"] for d in struts)
    assert all("infra_ac_transit" not in d["target"]["object"] for d in struts)
    assert all(d["from_value"] == 0.0 and d["to_value"] == 1.0 for d in struts)


def test_a_changed_strut_count_recentres_the_row_and_is_reconciled(master, motion) -> None:
    """More struts means every shared strut sits somewhere new; V1 says so."""
    before = export(walls=("boundary_ab",), dependencies={"infra_ab_transit": 0.72})
    after = export(walls=("boundary_ab",), dependencies={"infra_ab_transit": 0.88})
    plan = mp.plan_motion(before, after, master, motion)
    settles = [d for d in plan["directives"] if d["channel"] == "infra_strut_settle"]
    assert settles, "a re-centred row must be reconciled, not silently snapped"
    assert all(d["value_space"] == "canonical_offset" for d in settles)
    assert all(d["to_value"] == 0.0 for d in settles)
    assert all(d["interpolation"] == "step" for d in settles)


def test_depot_slots_appear_and_vanish_with_the_stock(master, motion) -> None:
    """Storage fill is authoritative resource state, shown as standing crates."""
    plan = mp.plan_motion(
        export(stocks={district_id: 80.0 for district_id in DISTRICT_IDS}),
        export(stocks={district_id: 5.0 for district_id in DISTRICT_IDS}),
        master,
        motion,
    )
    presence = [d for d in plan["directives"] if d["channel"] == "depot_slot_presence"]
    assert presence
    assert any(d["to_value"] == 0.0 for d in presence), "emptying a yard removes crates"
    assert all(d["target"]["object"].startswith(mp.DEPOT_PREFIX) for d in presence)


def test_every_reconciling_directive_ends_exactly_at_canonical(master, motion) -> None:
    """The last frame is the canonical static world, not a near miss."""
    plan = mp.plan_motion(
        export(law_active=True, stocks={"district_a": 30.0}),
        export(
            walls=("boundary_ab",),
            law_active=False,
            stocks={"district_a": 240.0},
            dependencies={"infra_ab_transit": 0.9},
        ),
        master,
        motion,
    )
    offsets = [d for d in plan["directives"] if d["value_space"] == "canonical_offset"]
    assert offsets
    for directive in offsets:
        assert directive["to_value"] == 0.0
        assert directive["target"]["kind"] == "object_transform"
        assert directive["target"]["component"] in mp.TRANSFORM_COMPONENTS


def test_every_directive_names_the_state_it_came_from(master, motion) -> None:
    """Traceability is not optional: a directive with no source is a fiction."""
    plan = mp.plan_motion(
        export(law_active=True),
        export(walls=("boundary_ab",), law_active=False, stocks={"district_d": 200.0}),
        master,
        motion,
    )
    assert plan["directives"]
    for directive in plan["directives"]:
        assert directive["source_before"].startswith("world.")
        assert directive["source_after"].startswith("world.")
        assert directive["source_before"] != directive["source_after"]
        assert directive["start_frame"] < directive["end_frame"]
        assert directive["from_value"] != directive["to_value"]


def test_every_directive_stays_inside_the_transition(master, motion) -> None:
    """Nothing moves during a hold; that is what makes a hold provable."""
    plan = mp.plan_motion(
        export(law_active=True),
        export(walls=("boundary_ab",), law_active=False, stocks={"district_b": 5.0}),
        master,
        motion,
    )
    timeline = motion["timeline"]
    for directive in plan["directives"]:
        assert timeline["transition_start"] <= directive["start_frame"]
        assert directive["end_frame"] <= timeline["transition_end"]


def test_a_changed_district_set_is_refused(master, motion) -> None:
    """A district appearing between two frames is not a visual transition."""
    after = export()
    after["world"]["districts"] = after["world"]["districts"][:3]
    refuses(export(), after, master, motion, "different district sets")


def test_a_changed_infrastructure_set_is_refused(master, motion) -> None:
    """Nor is a conduit."""
    after = export()
    after["world"]["infrastructure"] = after["world"]["infrastructure"][:2]
    refuses(export(), after, master, motion, "different infrastructure sets")


def test_a_duplicated_entity_id_is_refused(master, motion) -> None:
    """Two districts with one id means one of them would be animated blind."""
    after = export()
    after["world"]["districts"].append(copy.deepcopy(after["world"]["districts"][0]))
    refuses(export(), after, master, motion, "twice")


def test_an_export_that_disagrees_with_the_master_scene_is_refused(master, motion) -> None:
    """Topology is never silently redrawn, in motion any more than in stills."""
    after = export()
    after["world"]["districts"][0]["id"] = "district_z"
    with pytest.raises(ss.SceneContractError):
        mp.plan_motion(export(), after, master, motion)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_a_non_finite_population_is_refused(master, motion, value) -> None:
    """A NaN would key a NaN into an F-curve, where nothing could catch it."""
    after = export()
    after["world"]["districts"][0]["population"] = value
    refuses(export(), after, master, motion, "must be finite")


def test_a_shared_glazing_material_with_two_truths_is_refused(master, motion) -> None:
    """One material cannot be two districts' occupancy at the same time."""
    forged = copy.deepcopy(master)
    forged["districts"]["district_b"]["character"] = "civic"
    refuses(
        export(populations={"district_a": 100, "district_b": 100}),
        export(populations={"district_a": 200, "district_b": 300}),
        forged,
        motion,
        "cannot hold two truths",
    )


def test_glazing_follows_the_locked_population_mapping(master, motion) -> None:
    """The lit fraction is the Phase 15 formula, not a Phase 17 reinvention."""
    entry = district("district_a", population=200)
    assert mp.glazing_value(entry) == pytest.approx(
        mp.GLAZING_BASE + mp.GLAZING_RANGE * (200 / 400)
    )
    plan = mp.plan_motion(
        export(populations={"district_a": 100}),
        export(populations={"district_a": 200}),
        master,
        motion,
    )
    glazing = [d for d in plan["directives"] if d["channel"] == "district_glazing"]
    assert len(glazing) == 1
    assert glazing[0]["target"]["material"] == "LD_MAT__glass_civic"
    assert glazing[0]["target"]["node"] == mp.GLAZING_NODE


def test_the_depot_replica_is_deterministic_and_seed_bound(master) -> None:
    """Two runs, two interpreters, one answer -- and never Python's hash()."""
    entry = district("district_a", stock=60.0)
    definition = master["districts"]["district_a"]
    first = mp.depot_slot_placements(entry, definition, master["visual_seed"])
    second = mp.depot_slot_placements(entry, definition, master["visual_seed"])
    assert first == second
    other = mp.depot_slot_placements(entry, definition, "a-different-world")
    assert other != first, "the visual seed must own the decoration"
    assert all(name.startswith(mp.DEPOT_PREFIX) for name in other)


def test_the_depot_replica_fills_slots_in_order(master) -> None:
    """Slot ordering is deterministic: yards fill from slot zero upward."""
    definition = master["districts"]["district_a"]
    names = mp.depot_slot_placements(
        district("district_a", stock=40.0), definition, master["visual_seed"]
    )
    slots = sorted({int(name.rsplit("__", 1)[1].split("_")[0]) for name in names})
    assert slots == list(range(len(slots)))


def test_an_empty_yard_has_no_containers(master) -> None:
    """Zero stock is zero crates, not one lonely crate at the origin."""
    definition = master["districts"]["district_b"]
    assert mp.depot_slot_placements(district("district_b", stock=0.0), definition, "seed") == {}


def test_the_strut_replica_follows_the_locked_count_and_centring(master) -> None:
    """Count grows with dependency; the row stays centred on the wall station."""
    boundary = master["boundaries"]["boundary_ab"]
    entry = {
        "id": "infra_ab_transit",
        "boundary_id": "boundary_ab",
        "infrastructure_type": "TRANSIT_ROUTE",
        "dependency_score": 0.72,
    }
    without = mp.strut_placements(entry, boundary, False)
    assert without == {}
    placements = mp.strut_placements(entry, boundary, True)
    assert len(placements) == max(1, round(1 + 0.72 * mp.STRUT_DEPENDENCY_WEIGHT))
    centre = (
        sum(x for x, _ in placements.values()) / len(placements),
        sum(y for _, y in placements.values()) / len(placements),
    )
    station = boundary["wall_station"]
    direction = station["direction"]
    norm = math.hypot(*direction)
    offset = mp.STRUT_LANE_OFFSETS["TRANSIT_ROUTE"]
    assert centre[0] == pytest.approx(station["center"][0] + offset * 0.5 * (direction[1] / norm))
    assert centre[1] == pytest.approx(station["center"][1] - offset * 0.5 * (direction[0] / norm))


def test_sampled_keys_are_exact_at_both_ends(master, motion) -> None:
    """However a curve is sampled, its first and last keys are the endpoints."""
    plan = mp.plan_motion(
        export(law_active=True),
        export(walls=("boundary_ab",), law_active=False, stocks={"district_a": 200.0}),
        master,
        motion,
    )
    for directive in plan["directives"]:
        keys = mp.sampled_keyframes(directive)
        assert keys[0] == (directive["start_frame"], directive["from_value"])
        assert keys[-1] == (directive["end_frame"], directive["to_value"])
        frames = [frame for frame, _ in keys]
        assert frames == sorted(frames)
        assert len(set(frames)) == len(frames)


def test_a_step_directive_carries_exactly_two_keys(master, motion) -> None:
    """A state swap is two keys; anything more would be invented motion."""
    plan = mp.plan_motion(
        export(stocks={"district_a": 240.0}),
        export(stocks={"district_a": 20.0}),
        master,
        motion,
    )
    steps = [d for d in plan["directives"] if d["interpolation"] == "step"]
    assert steps
    for directive in steps:
        assert len(mp.sampled_keyframes(directive)) == 2


def test_a_smoothstep_directive_is_sampled_from_the_documented_formula() -> None:
    """The curve Blender draws is the curve this project computed."""
    keys = mp.keyframes("smoothstep", 8, 0.0, 1.0, 0, 80)
    assert keys[0] == (0, 0.0)
    assert keys[-1] == (80, 1.0)
    for frame, value in keys:
        assert value == pytest.approx(mts.interpolate("smoothstep", 0.0, 1.0, frame / 80.0))


def test_a_collapsed_key_window_is_refused() -> None:
    """A curve from frame 40 to frame 40 has no time to travel in."""
    with pytest.raises(mp.MotionPlanError):
        mp.keyframes("linear", 4, 0.0, 1.0, 40, 40)


def test_the_plan_records_both_endpoints_provenance(master, motion) -> None:
    """A plan says which two verified episodes it came from."""
    plan = mp.plan_motion(
        export(episode=0), export(episode=2, walls=("boundary_ab",)), master, motion
    )
    assert plan["before"]["episode"] == 0
    assert plan["after"]["episode"] == 2
    assert plan["after"]["state_hash"] != plan["before"]["state_hash"]
    assert plan["format"] == mp.MOTION_PLAN_FORMAT
    assert plan["schema_version"] == mp.MOTION_PLAN_SCHEMA_VERSION


def test_a_plan_changes_when_the_presentation_contract_changes(master, motion, tmp_path) -> None:
    """Retimed channels are a different film, and hash differently."""
    before, after = export(law_active=True), export(law_active=False)
    baseline = mp.plan_hash(mp.plan_motion(before, after, master, motion))
    document = json.loads((CONFIG_DIR / "motion_time_v1.json").read_text(encoding="utf-8"))
    document["timeline"]["transition_frames"] = 60
    document["timeline"]["end_frame"] = 133
    path = tmp_path / "retimed.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    retimed = mts.load_motion_time_spec(path)
    assert mp.plan_hash(mp.plan_motion(before, after, master, retimed)) != baseline


def test_stock_provenance_does_not_depend_on_the_interpreter(master, motion) -> None:
    """A plan's hash must not depend on which Python computed it.

    REGRESSION. CPython 3.12 changed ``sum`` over floats to compensated
    summation, so the same three resource numbers add up to two different
    representable results on the host's interpreter and on the one Blender
    bundles. That leaked into the provenance strings and made the plan HASH
    interpreter-dependent -- caught by the gate's own cross-check between the
    plan it validates and the plan the renderer actually animated.

    The planner now sums with ``math.fsum``, which is exactly rounded on both.
    """
    resources = {"ENERGY": 84.80000000000004, "FOOD": 202.0, "MATERIALS": 127.19999999999997}
    naive = 0.0
    for value in resources.values():
        naive += value
    exact = math.fsum(resources.values())
    assert naive != exact, "this fixture must actually exercise the difference"

    before = export()
    after = export()
    after["world"]["districts"][0]["resources"] = dict(resources)
    plan = mp.plan_motion(before, after, master, motion)
    provenance = {
        directive["source_after"]
        for directive in plan["directives"]
        if directive["channel"].startswith("depot_slot")
    }
    assert provenance, "changing a yard's stock must produce depot directives"
    assert any(f"sum={exact}/" in entry for entry in provenance)
    assert not any(f"sum={naive}/" in entry for entry in provenance)


def test_a_malformed_export_shape_is_refused(master, motion) -> None:
    """A document with no world section never reaches the mapping code."""
    refuses(export(), {"world": {"districts": []}}, master, motion, "must be a JSON array")
    refuses(export(), {}, master, motion, "no world section")


def test_describe_summarises_without_lying(master, motion) -> None:
    """The gate's one-line summary reports the real counts."""
    empty = mp.plan_motion(export(), export(), master, motion)
    assert "nothing changed" in mp.describe(empty)
    plan = mp.plan_motion(export(), export(walls=("boundary_ab",)), master, motion)
    assert f"{plan['summary']['directive_count']} directives" in mp.describe(plan)
