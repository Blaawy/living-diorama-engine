"""Contract tests for the pure pedestrian topology.

Pure pytest -- no Blender, and no dependency on generated proof artefacts: the
topology is derived from the canonical specs the repository ships, so these
tests prove the RULES rather than one recorded scene.

The rules under test are the ones that keep a populated city honest: nobody may
be offered ground the city already occupies, the answer must not depend on
iteration order or on the machine it runs on, and the offer must be blind to
how many people will eventually stand on it.
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


pt = _load("pedestrian_topology")
pps = _load("population_presence_spec")
scene_spec = _load("scene_spec")
production_spec = _load("production_spec")
road_graph = _load("road_graph")
urban_fabric = _load("urban_fabric")
spatial = _load("spatial_occupancy")

MASTER = scene_spec.load_master_scene_spec(CONFIG_DIR / "master_scene_v1.json")
PRODUCTION = production_spec.load_production_world_spec(CONFIG_DIR / "production_world_v1.json")
PRESENCE = pps.load_population_presence_spec(CONFIG_DIR / "population_presence_v1.json")
GRAPH = road_graph.build_road_graph(MASTER, PRODUCTION)
FABRIC = urban_fabric.plan_urban_fabric(MASTER, PRODUCTION, GRAPH)
TOPOLOGY = pt.plan_pedestrian_topology(MASTER, PRODUCTION, GRAPH, FABRIC, PRESENCE)

BODY_RADIUS = float(PRESENCE["proxy"]["radius"])


def every_candidate() -> list[dict]:
    """Every accepted candidate the topology publishes, flattened."""
    return [
        candidate
        for zones in TOPOLOGY["zones"].values()
        for entries in zones.values()
        for candidate in entries
    ]


# ---------------------------------------------------------------------------
# Safety: nobody is offered ground the city already owns
# ---------------------------------------------------------------------------


def test_the_canonical_topology_is_valid() -> None:
    """Re-prove every published candidate against a freshly loaded occupancy."""
    errors = pt.validate_pedestrian_topology(TOPOLOGY, MASTER, PRODUCTION, GRAPH, FABRIC)
    assert not errors, "\n".join(errors[:5])


def test_no_candidate_stands_in_a_carriageway() -> None:
    """The failure that would matter most, checked directly."""
    validator = pt.build_presence_occupancy(MASTER, PRODUCTION, GRAPH, FABRIC)
    roads = pt.street_occupancy_shapes(validator)
    assert roads, "the validator holds no road envelopes at all"
    for candidate in every_candidate():
        body = spatial.circle(candidate["x"], candidate["y"], BODY_RADIUS)
        for road in roads:
            assert spatial.shape_gap(body, road) > 0.0, (
                f"a {candidate['zone']} candidate stands in a carriageway at "
                f"({candidate['x']}, {candidate['y']})"
            )


def test_no_candidate_stands_in_the_harbour() -> None:
    """Water is held furthest off of all."""
    validator = pt.build_presence_occupancy(MASTER, PRODUCTION, GRAPH, FABRIC)
    water = [entry for entry in validator.entries if entry["category"] == "WATER"]
    assert water, "the harbour is not registered"
    for candidate in every_candidate():
        body = spatial.circle(candidate["x"], candidate["y"], BODY_RADIUS)
        for entry in water:
            assert spatial.shape_gap(body, entry["shape"]) >= pt.PRESENCE_CLEARANCE["WATER"]


def test_no_candidate_crowds_the_scar() -> None:
    """The historical boundary is never dressed with bystanders."""
    validator = pt.build_presence_occupancy(MASTER, PRODUCTION, GRAPH, FABRIC)
    walls = [entry for entry in validator.entries if entry["category"] == "WALL"]
    assert walls, "the wall lines are not registered"
    for candidate in every_candidate():
        body = spatial.circle(candidate["x"], candidate["y"], BODY_RADIUS)
        for entry in walls:
            assert spatial.shape_gap(body, entry["shape"]) >= pt.PRESENCE_CLEARANCE["WALL"]


def test_the_clearance_table_covers_every_registered_category() -> None:
    """No occupancy category may go unpolicied by the presence rules."""
    validator = pt.build_presence_occupancy(MASTER, PRODUCTION, GRAPH, FABRIC)
    present = {entry["category"] for entry in validator.entries}
    assert present <= set(pt.PRESENCE_CLEARANCE), (
        f"unpolicied categories in the scene: {sorted(present - set(pt.PRESENCE_CLEARANCE))}"
    )
    assert set(pt.PRESENCE_CLEARANCE) <= set(spatial.CATEGORIES)


def test_only_walkable_surfaces_are_open_ground() -> None:
    """Exactly three categories may be stood on, and they are the designed floors."""
    open_ground = {
        category for category, clearance in pt.PRESENCE_CLEARANCE.items() if clearance is None
    }
    assert open_ground == {"PAVING", "PLAZA", "PLATE"}


def test_a_body_placed_on_a_building_is_refused() -> None:
    """The check has teeth: aim one at a lot and it must come back with reasons."""
    validator = pt.build_presence_occupancy(MASTER, PRODUCTION, GRAPH, FABRIC)
    lot = next(lot for entry in FABRIC["neighborhoods"].values() for lot in entry["lots"])
    conflicts = pt.presence_conflicts(validator, spatial.circle(lot["x"], lot["y"], BODY_RADIUS))
    assert conflicts, "standing inside a building was not refused"
    assert conflicts[0]["their_category"] == "BUILDING"


def test_a_body_placed_in_the_harbour_is_refused() -> None:
    """The same teeth, aimed at the water."""
    validator = pt.build_presence_occupancy(MASTER, PRODUCTION, GRAPH, FABRIC)
    water = next(entry for entry in validator.entries if entry["category"] == "WATER")
    conflicts = pt.presence_conflicts(
        validator, spatial.circle(water["shape"]["x"], water["shape"]["y"], BODY_RADIUS)
    )
    assert any(conflict["their_category"] == "WATER" for conflict in conflicts)


def test_lot_plinths_are_registered_so_nobody_stands_on_one() -> None:
    """A raised plinth would leave a body built sunk into its own footing."""
    validator = pt.build_presence_occupancy(MASTER, PRODUCTION, GRAPH, FABRIC)
    plinths = [entry for entry in validator.entries if entry["id"].startswith("plinth_")]
    assert plinths, "no plinth was registered"
    for entry in plinths:
        shape = entry["shape"]
        conflicts = pt.presence_conflicts(
            validator, spatial.circle(shape["x"], shape["y"], BODY_RADIUS)
        )
        assert conflicts, "a body could stand on a plinth"


def test_the_seal_masts_are_registered_obstacles() -> None:
    """The civic forecourt's own lamp posts are known to the topology."""
    furniture = pt.street_furniture(MASTER, FABRIC)
    ids = {entry_id for entry_id, _category, _shapes in furniture}
    assert {f"seal_mast_{index}" for index in range(4)} <= ids
    seal = MASTER["landmarks"]["golden_seal"]
    expected = float(seal["radius"]) * pt.SEAL_MAST_FACTOR
    for entry_id, category, shapes in furniture:
        if not entry_id.startswith("seal_mast_"):
            continue
        assert category == "HISTORY"
        reach = math.hypot(
            shapes[0]["x"] - float(seal["location"][0]),
            shapes[0]["y"] - float(seal["location"][1]),
        )
        assert abs(reach - expected) < 1.0e-6


def test_plaza_masts_are_registered_for_every_planned_plaza() -> None:
    """Every plaza that exists brings its seven masts with it."""
    furniture = dict(
        (entry_id, shapes) for entry_id, _category, shapes in pt.street_furniture(MASTER, FABRIC)
    )
    plazas = [
        neighborhood_id
        for neighborhood_id, entry in FABRIC["neighborhoods"].items()
        if entry["plaza"] is not None
    ]
    assert plazas, "the canonical city has no plaza to test"
    for neighborhood_id in plazas:
        shapes = furniture[f"plaza_masts_{neighborhood_id}"]
        assert len(shapes) == 7, "one centre mast and six around the rim"


# ---------------------------------------------------------------------------
# Ground height
# ---------------------------------------------------------------------------


def test_every_candidate_records_the_ground_beneath_it() -> None:
    """The published z is the surface, recomputed independently."""
    for candidate in every_candidate():
        expected = round(
            pt.presence_ground_level(candidate["x"], candidate["y"], MASTER, FABRIC), 4
        )
        assert candidate["z"] == expected


def test_plaza_candidates_stand_on_the_deck_not_the_ground_under_it() -> None:
    """A plaza is built ON the city floor, so its deck is the standing surface."""
    plazas = [
        entry["plaza"] for entry in FABRIC["neighborhoods"].values() if entry["plaza"] is not None
    ]
    assert plazas
    for plaza in plazas:
        deck = float(plaza["base"]) + pt.PLAZA_DECK_THICKNESS
        on_deck = [
            candidate
            for candidate in every_candidate()
            if math.hypot(
                candidate["x"] - float(plaza["center"][0]),
                candidate["y"] - float(plaza["center"][1]),
            )
            <= float(plaza["radius"])
        ]
        assert on_deck, "the plaza offers no standing ground at all"
        for candidate in on_deck:
            assert abs(candidate["z"] - deck) < 1.0e-4, (
                f"a body on the plaza stands at {candidate['z']}, the deck is at {deck}"
            )


def test_no_candidate_has_ground_rising_into_it() -> None:
    """Kerbs are fine; a knee-high step through a body is not."""
    for candidate in every_candidate():
        rise = pt.step_conflict(candidate["x"], candidate["y"], BODY_RADIUS, MASTER, FABRIC)
        assert rise == 0.0, (
            f"ground rises {rise} into a body at ({candidate['x']}, {candidate['y']})"
        )


def test_the_step_rule_actually_refuses_something() -> None:
    """Proven, not assumed: the canonical run records real step refusals."""
    step_refusals = {
        key: count for key, count in TOPOLOGY["refused"].items() if key.endswith("-step")
    }
    assert step_refusals, "the step rule never fired, so it is untested by the real world"


# ---------------------------------------------------------------------------
# Determinism and order independence
# ---------------------------------------------------------------------------


def test_the_same_world_produces_the_same_topology() -> None:
    """Same inputs, same offer -- byte for byte."""
    again = pt.plan_pedestrian_topology(MASTER, PRODUCTION, GRAPH, FABRIC, PRESENCE)
    assert again == TOPOLOGY


def test_the_topology_does_not_depend_on_mapping_order() -> None:
    """Reversing every dict the specs hand over changes nothing.

    Python preserves insertion order, so a planner that iterated a spec
    without sorting would silently depend on how the JSON happened to be
    written. This rewrites that order and demands the same answer.
    """
    master = copy.deepcopy(MASTER)
    master["districts"] = dict(reversed(list(master["districts"].items())))
    master["boundaries"] = dict(reversed(list(master["boundaries"].items())))
    production = copy.deepcopy(PRODUCTION)
    production["neighborhoods"] = dict(reversed(list(production["neighborhoods"].items())))
    production["streets"] = dict(reversed(list(production["streets"].items())))
    graph = road_graph.build_road_graph(master, production)
    fabric = urban_fabric.plan_urban_fabric(master, production, graph)
    shuffled = pt.plan_pedestrian_topology(master, production, graph, fabric, PRESENCE)
    assert shuffled["summary"] == TOPOLOGY["summary"]
    for district_id, zones in sorted(TOPOLOGY["zones"].items()):
        for zone_id, entries in sorted(zones.items()):
            assert shuffled["zones"][district_id][zone_id] == entries


def test_every_published_coordinate_is_the_coordinate_that_was_tested() -> None:
    """Rounded before the check, not after.

    A candidate proven clear at full precision and published rounded is a
    candidate nobody checked; on a polygon boundary the two answers genuinely
    differ. Every published value must therefore survive its own rounding.
    """
    for candidate in every_candidate():
        assert candidate["x"] == round(candidate["x"], 6)
        assert candidate["y"] == round(candidate["y"], 6)
        assert candidate["z"] == round(candidate["z"], 4)
        assert candidate["heading"] == round(candidate["heading"], 6)


def test_the_topology_never_consults_population() -> None:
    """The offer is a property of the ground, not of who will stand on it.

    Proved from the module's own signatures rather than from a text scan: no
    public function here accepts a render export or a population, so there is
    nowhere for population to enter the decision even by accident.
    """
    import inspect

    forbidden = {"export", "exports", "population", "populations", "plan", "proxies"}
    for name, value in sorted(vars(pt).items()):
        if name.startswith("_") or not inspect.isfunction(value):
            continue
        if value.__module__ != pt.__name__:
            continue
        parameters = set(inspect.signature(value).parameters)
        assert not (parameters & forbidden), (
            f"pedestrian_topology.{name} accepts {sorted(parameters & forbidden)}, "
            "which would let population reach a decision about ground"
        )


def test_the_topology_never_imports_a_population_reader() -> None:
    """Nothing it imports could hand it an export either."""
    import ast

    tree = ast.parse((SCRIPTS_DIR / "pedestrian_topology.py").read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            roots.add(node.module.split(".")[0])
    assert "population_presence_plan" not in roots, "the topology must not depend on the planner"
    assert "living_diorama" not in roots
    assert "bpy" not in roots


# ---------------------------------------------------------------------------
# Shape of the offer
# ---------------------------------------------------------------------------


def test_every_zone_type_is_offered_somewhere() -> None:
    """All four approved area types exist in the canonical city."""
    for zone_id in pt.ZONE_TYPES:
        assert TOPOLOGY["summary"]["candidates_by_zone"][zone_id] > 0, (
            f"the {zone_id} zone offered no ground at all"
        )


def test_every_district_is_offered_ground() -> None:
    """No district is left with nowhere for its people to be."""
    for district_id in sorted(MASTER["districts"]):
        assert TOPOLOGY["summary"]["candidates_by_district"][district_id] > 0


def test_candidates_are_filed_under_the_district_that_owns_the_ground() -> None:
    """Ownership is nearest-territory, recomputed here from scratch."""
    territories = pt.district_territories(MASTER, PRODUCTION)
    for district_id, zones in sorted(TOPOLOGY["zones"].items()):
        for entries in zones.values():
            for candidate in entries:
                owner, _gap = pt.owning_district(candidate["x"], candidate["y"], territories)
                assert owner == district_id


def test_ownership_ties_break_on_district_id() -> None:
    """A point equidistant from two districts always picks the same one."""
    territories = {"district_b": [(1.0, 0.0)], "district_a": [(-1.0, 0.0)]}
    assert pt.owning_district(0.0, 0.0, territories)[0] == "district_a"
    reversed_territories = dict(reversed(list(territories.items())))
    assert pt.owning_district(0.0, 0.0, reversed_territories)[0] == "district_a"


def test_a_neighborhood_claiming_an_unknown_district_is_refused() -> None:
    """Presence may never be filed under a district the world does not have."""
    production = copy.deepcopy(PRODUCTION)
    production["neighborhoods"]["eastgate"]["district"] = "district_z"
    with pytest.raises(pt.PedestrianTopologyError, match="district_z"):
        pt.district_territories(MASTER, production)


def test_refusals_are_recorded_by_reason() -> None:
    """A silent skip is indistinguishable from ground that was never sampled."""
    assert TOPOLOGY["summary"]["candidates_refused"] > 0
    assert sum(TOPOLOGY["refused"].values()) == TOPOLOGY["summary"]["candidates_refused"]
    assert all("-" in key for key in TOPOLOGY["refused"])
    accepted = sum(TOPOLOGY["summary"]["candidates_by_zone"].values())
    assert (
        accepted + TOPOLOGY["summary"]["candidates_refused"]
        == (TOPOLOGY["summary"]["candidates_tested"])
    )


# ---------------------------------------------------------------------------
# Orientation and spread
# ---------------------------------------------------------------------------


def test_promenade_candidates_face_the_water() -> None:
    """Orientation is geometry: the waterfront faces the harbour."""
    _port, (unit_x, unit_y), _quay = production_spec.port_frame(MASTER)
    expected = math.atan2(unit_y, unit_x)
    promenade = [
        candidate for zones in TOPOLOGY["zones"].values() for candidate in zones["promenade"]
    ]
    assert promenade
    for candidate in promenade:
        assert abs(candidate["heading"] - expected) < 1.0e-5


def test_plaza_and_park_candidates_face_their_centre() -> None:
    """A body on a plaza looks INTO it, not away from it.

    Asserted as a bearing, not as a range: the first version of this test
    checked only that the heading was a valid angle, which every heading is.
    Reversing the orientation rule would have passed it unchanged.
    """
    centres = {
        source["id"]: (source["x"], source["y"]) for source in pt.plaza_sources(MASTER, FABRIC)
    }
    for zone_id, park in PRODUCTION["landscape"]["park_zones"].items():
        centres[zone_id] = (float(park["center"][0]), float(park["center"][1]))
    checked = 0
    for zones in TOPOLOGY["zones"].values():
        for zone_name in ("plaza", "park"):
            for candidate in zones[zone_name]:
                center_x, center_y = centres[candidate["source"]]
                expected = math.atan2(center_y - candidate["y"], center_x - candidate["x"])
                difference = abs(pt._wrap_angle(candidate["heading"] - expected))
                assert difference < 1.0e-5, (
                    f"a {zone_name} body at ({candidate['x']}, {candidate['y']}) faces "
                    f"{candidate['heading']}, its centre is at {expected}"
                )
                checked += 1
    assert checked > 10, "too few candidates to prove the orientation rule"


def test_the_orientation_guard_would_catch_a_reversed_rule() -> None:
    """Proven, not assumed: reverse the rule and the bearing check must fail."""
    candidate = {"x": 1.0, "y": 0.0, "center": (0.0, 0.0), "side": ""}
    facing = pt.candidate_heading(candidate, "face_center")
    assert abs(pt._wrap_angle(facing - math.pi)) < 1.0e-9, "a body east of centre looks west"
    reversed_rule = math.atan2(candidate["y"] - 0.0, candidate["x"] - 0.0)
    assert abs(pt._wrap_angle(facing - reversed_rule)) > 1.0
    assert abs(pt._wrap_angle(facing - reversed_rule)) > 1.0


def test_the_two_sides_of_a_street_look_opposite_ways() -> None:
    """A pavement reads as two directions of travel, not a queue."""
    heading = 0.4
    left = {"street_heading": heading, "side": "l"}
    right = {"street_heading": heading, "side": "r"}
    difference = abs(
        pt.candidate_heading(left, "along_street") - pt.candidate_heading(right, "along_street")
    )
    assert abs(difference - math.pi) < 1.0e-9


def test_an_unknown_orientation_rule_is_refused() -> None:
    """Headings come only from the declared geometries."""
    with pytest.raises(pt.PedestrianTopologyError, match="orientation"):
        pt.candidate_heading({"side": "l", "street_heading": 0.0}, "face_the_music")


def test_spread_order_is_a_stable_prefix() -> None:
    """Any prefix of the order is the order you would get asking for that many.

    This is the property the whole slot contract rests on: a district that
    grows must extend its people, never rearrange them.
    """
    points = [{"x": float(index % 7) * 3.0, "y": float(index // 7) * 3.0} for index in range(35)]
    full = pt.spread_order(points, (0.0, 0.0))
    assert len(full) == len(points)
    assert {id(entry) for entry in full} == {id(entry) for entry in points}
    for length in (1, 3, 8, 21):
        assert pt.spread_order(points, (0.0, 0.0))[:length] == full[:length]


def test_spread_order_starts_nearest_the_anchor() -> None:
    """The first person in a district stands at its heart."""
    points = [{"x": 40.0, "y": 0.0}, {"x": 1.0, "y": 1.0}, {"x": -30.0, "y": 12.0}]
    assert pt.spread_order(points, (0.0, 0.0))[0] == {"x": 1.0, "y": 1.0}


def test_spread_order_actually_spreads() -> None:
    """The second pick is the far one, not the next one in the list."""
    points = [{"x": 0.0, "y": 0.0}, {"x": 0.5, "y": 0.0}, {"x": 30.0, "y": 0.0}]
    ordered = pt.spread_order(points, (0.0, 0.0))
    assert ordered[0]["x"] == 0.0
    assert ordered[1]["x"] == 30.0


def test_spread_order_handles_the_empty_case() -> None:
    """A zone with no ground orders nothing rather than raising."""
    assert pt.spread_order([], (0.0, 0.0)) == []


def test_presence_seeds_are_owned_by_their_identity() -> None:
    """Two slots never share a generator, and one slot always gets the same one."""
    first = pt.presence_seed(PRESENCE, "district_a__slot_001").random()
    again = pt.presence_seed(PRESENCE, "district_a__slot_001").random()
    other = pt.presence_seed(PRESENCE, "district_a__slot_002").random()
    assert first == again
    assert first != other
