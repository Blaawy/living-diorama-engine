"""The Phase 16 urban-ground contract (pure Python).

The final composition's promise is that the world reads as ONE CITY: the
arbitrary circular district floors are reinterpreted into designed,
block-aligned ground, while every piece of MEANING -- the plates, the
Seal, the scar and the reserved alignments, the harbor, and the districts
themselves -- keeps its territory exactly. These tests prove both halves:
the circles genuinely go, and history genuinely stays.
"""

import copy
import math

import pytest


def test_canonical_ground_validates_clean(
    city_ground, canonical_ground, master_document, production_document, canonical_graph
):
    """The shipped ground plan passes every composition rule."""
    errors = city_ground.validate_city_ground(
        canonical_ground, master_document, production_document, canonical_graph
    )
    assert errors == []


def test_ground_is_deterministic(
    city_ground, master_document, production_document, canonical_graph, canonical_ground
):
    """Same specs + same graph produce the identical ground, bit for bit."""
    again = city_ground.plan_city_ground(master_document, production_document, canonical_graph)
    assert again == canonical_ground


def test_ground_ignores_mapping_insertion_order(
    city_ground, road_graph, master_document, production_document, canonical_ground
):
    """Reordering the plates mapping never changes the ground."""
    reordered = copy.deepcopy(production_document)
    reordered["ground"]["plates"] = dict(
        sorted(reordered["ground"]["plates"].items(), key=lambda item: item[0], reverse=True)
    )
    graph = road_graph.build_road_graph(master_document, reordered)
    assert city_ground.plan_city_ground(master_document, reordered, graph) == canonical_ground


def test_every_district_joins_the_composition(canonical_ground, master_document):
    """No founding plate is left out of the final composition."""
    assert set(canonical_ground["plates"]) == set(master_document["districts"])
    for plate in canonical_ground["plates"].values():
        assert plate["pieces"], "a plate with no ground panels is still a bare circle"


def test_the_pod_circles_are_gone(city_ground, canonical_ground):
    """Every plate's measured rim exposure stays inside the contract.

    This is the reviewer's acceptance question -- "do I immediately notice
    giant circular district pods?" -- expressed as a number the plan
    publishes rather than a claim the report makes.
    """
    assert canonical_ground["summary"]["buried_ring_arcs"] >= 1
    for district_id, plate in canonical_ground["plates"].items():
        assert plate["rim_exposure_deg"] <= city_ground.MAX_RIM_EXPOSURE_DEG, (
            f"{district_id} still reads as a pod ({plate['rim_exposure_deg']} degrees)"
        )


def test_the_civic_ring_survives_whole(canonical_ground, production_document):
    """The Golden Seal's district keeps its designed Ring.

    Not every circle is an accident: the civic Ring is intentional civic
    form and is preserved by declaration, which is exactly the
    semantic-versus-arbitrary distinction the phase turns on.
    """
    civic = [
        district_id
        for district_id, plate in production_document["ground"]["plates"].items()
        if plate["ring"] == "full"
    ]
    assert civic, "the composition must keep at least one intentional ring"
    for district_id in civic:
        plate = canonical_ground["plates"][district_id]
        assert plate["buried_arcs"] == []
        assert len(plate["kept_arcs"]) == 1, f"{district_id} split its intentional ring"
        start, end = plate["kept_arcs"][0]
        assert ((end - start) % 360.0 or 360.0) == 360.0, (
            f"{district_id} declares a full ring but keeps only {end - start} degrees"
        )


def test_kept_arcs_carry_every_street_landing(canonical_ground):
    """Every landing keeps carriageway, and the arcs partition the ring.

    Checking that arc ENDPOINTS are vias would be circular -- the arcs are
    built from the vias. What actually matters is the reverse and the
    whole: no landing may be left without a street, and kept plus buried
    arcs together must cover the circle exactly once.
    """
    for district_id, plate in canonical_ground["plates"].items():
        if plate["ring"] == "full":
            assert plate["buried_arcs"] == []
            continue
        arcs = plate["kept_arcs"] + plate["buried_arcs"]
        total = sum((b - a) % 360.0 or 360.0 for a, b in arcs)
        assert abs(total - 360.0) < 0.01, (
            f"{district_id} arcs cover {total:.2f} degrees, not the whole ring"
        )
        for via in plate["vias"]:
            carried = [
                (a, b)
                for a, b in plate["kept_arcs"]
                if min((via - a) % 360.0, (a - via) % 360.0) < 0.01
                or min((via - b) % 360.0, (b - via) % 360.0) < 0.01
            ]
            assert carried, f"{district_id} landing at {via:.2f} has no kept arc touching it"


def test_rim_exposure_measures_the_whole_circle(city_ground, canonical_ground, master_document):
    """The pod metric must not be scoped to the plan's own choices.

    A plate that buries nothing must not score a vacuous zero. Proven by
    re-measuring a plate with its buried arcs erased: the metric is taken
    over all 360 degrees, so erasing the plan's burial record cannot
    improve the score.
    """
    import copy

    for district_id, plate in canonical_ground["plates"].items():
        stripped = copy.deepcopy(plate)
        stripped["buried_arcs"] = []
        rescored = city_ground.rim_exposure(stripped, master_document, district_id)
        assert rescored >= plate["rim_exposure_deg"] - 0.01, (
            f"{district_id} scores better with its burial record erased; "
            "the metric is scoped to the arcs the plan chose"
        )


def test_kept_ring_paths_follow_the_founding_radius(city_ground, canonical_ground, master_document):
    """Redrawn ring arcs sit exactly on the founding ring alignment."""
    for district_id, district in master_document["districts"].items():
        expected = city_ground.RING_OUTER_FACTOR * float(district["radius"])
        for path in city_ground.kept_ring_paths(master_document, canonical_ground, district_id):
            for x, y in path:
                reach = math.hypot(x - district["center"][0], y - district["center"][1])
                assert abs(reach - expected) < 1.0e-6


def test_ground_never_covers_the_scar_corridor(city_ground, canonical_ground, master_document):
    """The wall corridors stay open ground in the finished city."""
    scar = master_document["boundaries"]["boundary_ab"]["wall_station"]
    x, y = scar["center"]
    dx, dy = scar["direction"]
    length = math.hypot(dx, dy)
    half = scar["length"] / 2.0
    ax, ay = x - dx / length * half, y - dy / length * half
    bx, by = x + dx / length * half, y + dy / length * half
    polygons = [
        piece["points"]
        for plate in canonical_ground["plates"].values()
        for piece in plate["pieces"]
    ]
    polygons += [cell["points"] for cell in canonical_ground["cells"].values()]
    for step in range(41):
        t = step / 40.0
        point = (ax + (bx - ax) * t, ay + (by - ay) * t)
        for polygon in polygons:
            assert not city_ground.point_in_polygon(point, polygon), (
                f"ground covers the scar at ({point[0]:.1f}, {point[1]:.1f})"
            )


def test_ground_never_covers_the_golden_seal(canonical_ground, master_document, city_ground):
    """The Rule Object keeps its plaza ground."""
    seal = master_document["landmarks"]["golden_seal"]
    for plate in canonical_ground["plates"].values():
        for piece in plate["pieces"]:
            for x, y in piece["points"]:
                gap = math.hypot(x - seal["location"][0], y - seal["location"][1])
                assert gap >= float(seal["radius"]) + city_ground.SEAL_PANEL_CLEARANCE - 0.05


def test_ground_cells_are_real_urban_ground(canonical_ground):
    """Every authored cell is a well-formed, meaningful piece of city."""
    assert canonical_ground["summary"]["ground_cells"] >= 8
    assert canonical_ground["summary"]["paved_cells"] >= 4
    assert canonical_ground["summary"]["lawn_cells"] >= 3
    for cell_id, cell in canonical_ground["cells"].items():
        assert len(cell["points"]) >= 3, cell_id
        assert 0.05 <= cell["level"] <= 0.8, cell_id


def test_a_panel_over_the_scar_is_detected(
    city_ground, canonical_ground, master_document, production_document, canonical_graph
):
    """A tampered ground panel bridging the wall corridor is refused."""
    tampered = copy.deepcopy(canonical_ground)
    station = master_document["boundaries"]["boundary_ab"]["wall_station"]
    x, y = station["center"]
    tampered["cells"]["intruder"] = {
        "surface": "pavement",
        "level": 0.3,
        "points": [[x - 6, y - 6], [x + 6, y - 6], [x + 6, y + 6], [x - 6, y + 6]],
    }
    errors = city_ground.validate_city_ground(
        tampered, master_document, production_document, canonical_graph
    )
    assert any("wall corridor" in error for error in errors)


def test_a_hand_edited_ground_plan_is_detected(
    city_ground, canonical_ground, master_document, production_document, canonical_graph
):
    """The ground must equal its own deterministic recomputation."""
    tampered = copy.deepcopy(canonical_ground)
    first = sorted(tampered["plates"])[0]
    tampered["plates"][first]["pieces"] = tampered["plates"][first]["pieces"][:-1]
    errors = city_ground.validate_city_ground(
        tampered, master_document, production_document, canonical_graph
    )
    assert any("deterministic recomputation" in error for error in errors)


def test_a_degenerate_cell_is_detected(
    city_ground, canonical_ground, master_document, production_document, canonical_graph
):
    """A sliver of ground is not urban ground."""
    tampered = copy.deepcopy(canonical_ground)
    tampered["cells"]["sliver"] = {
        "surface": "pavement",
        "level": 0.3,
        "points": [[10.0, 40.0], [10.4, 40.0], [10.2, 40.3]],
    }
    errors = city_ground.validate_city_ground(
        tampered, master_document, production_document, canonical_graph
    )
    assert any("degenerate" in error for error in errors)


def test_ring_mode_must_be_declared(production_spec, production_document, tmp_path):
    """An undeclared ring mode is refused, never guessed."""
    import json

    document = copy.deepcopy(production_document)
    first = sorted(document["ground"]["plates"])[0]
    document["ground"]["plates"][first]["ring"] = "sometimes"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(production_spec.ProductionContractError, match="ring"):
        production_spec.load_production_world_spec(path)


def test_missing_ground_plate_is_refused(production_spec, master_document, production_document):
    """Every authoritative district must join the composition."""
    tampered = copy.deepcopy(production_document)
    del tampered["ground"]["plates"]["district_a"]
    with pytest.raises(production_spec.ProductionContractError, match="district_a"):
        production_spec.require_production_agreement(master_document, tampered)
