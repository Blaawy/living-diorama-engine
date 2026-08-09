"""The Phase 16 street-network connectivity contract (pure Python).

The canonical DESIGNED network must validate clean and must be built
exactly as authored -- the graph never bends a designed street. Every
rule of the contract must DETECT its violation when a tampered graph is
presented: no unexplained fragments, no duplicates, no zero-length legs,
no silent crossings, no street across a wall line, no invasion of the
founding plates or the harbor, and one single connected city.
"""

import copy

import pytest


def _tampered(canonical_graph):
    """A deep copy of the canonical graph, safe to mutate."""
    return copy.deepcopy(canonical_graph)


def test_canonical_network_validates_clean(
    road_graph, canonical_graph, master_document, production_document
):
    """The shipped network passes the entire connectivity contract."""
    errors = road_graph.validate_road_graph(canonical_graph, master_document, production_document)
    assert errors == []


def test_canonical_network_shape(road_graph, canonical_graph):
    """The network carries the full hierarchy and a real production layer."""
    summary = road_graph.graph_summary(canonical_graph)
    assert summary["production_segments"] >= 15
    assert set(summary["segments_by_class"]) == {"arterial", "collector", "local", "service"}
    assert summary["production_street_length"] > 500.0
    assert summary["intersections"] >= 25
    orbital = canonical_graph["segments"]["orbital"]
    assert len(orbital["path"]) >= 24, "the orbital is a smooth sampled boulevard"
    ends = (orbital["end_a"], orbital["end_b"])
    assert all(end is not None and "node" in end for end in ends), (
        "the orbital is anchored on shared junction nodes at both ends"
    )


def test_designed_streets_are_never_deformed(canonical_graph, production_document):
    """Class D never bends Class B: authored waypoints survive verbatim.

    Every interior waypoint of every designed street appears exactly in
    the built graph -- the redesign's planner clears obstacles instead of
    deforming roads, so the geometry the designer wrote is the geometry
    the city gets. (Endpoints may gain computed ring landings or snap to
    shared junction coordinates; the authored shape in between may not
    change.)
    """
    for street_id, street in sorted(production_document["streets"].items()):
        graph_path = [
            (round(x, 2), round(y, 2)) for x, y in canonical_graph["segments"][street_id]["path"]
        ]
        for point in street["path"][1:-1]:
            assert (round(point[0], 2), round(point[1], 2)) in graph_path, (
                f"{street_id} lost its authored waypoint {point}"
            )


def test_designed_vertex_on_street_becomes_a_junction(canonical_graph):
    """A designed vertex resting on another street is a real junction."""
    mid = canonical_graph["segments"]["southside_mid"]
    high = canonical_graph["segments"]["southside_high"]
    crossing_nodes = set(mid["via"]) & set(high["via"])
    assert crossing_nodes, (
        "southside_mid crosses southside_high at a designed vertex; both "
        "streets must share that junction node"
    )


def test_founding_streets_are_imported_as_existing(canonical_graph, master_document):
    """Avenues, plate rings, and spurs are graph truth but never re-meshed."""
    for boundary_id in master_document["boundaries"]:
        assert canonical_graph["segments"][f"avenue_{boundary_id}"]["existing"] is True
    for district_id in master_document["districts"]:
        assert canonical_graph["segments"][f"ring_{district_id}"]["existing"] is True
    assert canonical_graph["segments"]["orbital"]["existing"] is False


def test_generation_is_deterministic(road_graph, master_document, production_document):
    """Same spec + same seed produce the identical network, twice."""
    first = road_graph.build_road_graph(master_document, production_document)
    second = road_graph.build_road_graph(master_document, production_document)
    assert first == second


def test_generation_ignores_mapping_insertion_order(
    road_graph, master_document, production_document
):
    """Reordering spec mappings never changes the network."""
    reordered = copy.deepcopy(production_document)
    reordered["neighborhoods"] = dict(
        sorted(reordered["neighborhoods"].items(), key=lambda item: item[0], reverse=True)
    )
    reordered["streets"] = dict(sorted(reordered["streets"].items(), reverse=True))
    baseline = road_graph.build_road_graph(master_document, production_document)
    shuffled = road_graph.build_road_graph(master_document, reordered)
    assert baseline == shuffled


def test_zero_length_leg_is_detected(
    road_graph, canonical_graph, master_document, production_document
):
    """A degenerate leg is named, never silently drawn."""
    tampered = _tampered(canonical_graph)
    segment = tampered["segments"]["orbital"]
    segment["path"].insert(2, segment["path"][2])
    errors = road_graph.validate_road_graph(tampered, master_document, production_document)
    assert any("zero-length" in error for error in errors)


def test_duplicate_street_is_detected(
    road_graph, canonical_graph, master_document, production_document
):
    """Two streets tracing the same carriageway are refused."""
    tampered = _tampered(canonical_graph)
    orbital = tampered["segments"]["orbital"]
    tampered["segments"]["orbital_copy"] = copy.deepcopy(orbital)
    errors = road_graph.validate_road_graph(tampered, master_document, production_document)
    assert any("duplicates" in error or "overlap collinearly" in error for error in errors)


def test_unexplained_dead_end_is_detected(
    road_graph, canonical_graph, master_document, production_document
):
    """An open end that is neither junction nor termination is refused."""
    tampered = _tampered(canonical_graph)
    tampered["nodes"]["orphan_end"] = {"x": 10.0, "y": -40.0}
    tampered["segments"]["stray"] = {
        "class": "local",
        "path": [(4.0, -40.0), (10.0, -40.0)],
        "closed": False,
        "end_a": {"termination": "cul_de_sac"},
        "end_b": {"node": "orphan_end"},
        "via": [],
        "existing": False,
        "owner": "",
    }
    errors = road_graph.validate_road_graph(tampered, master_document, production_document)
    assert any("dead-ends" in error for error in errors)


def test_unknown_termination_type_is_refused(
    road_graph, canonical_graph, master_document, production_document
):
    """Termination reasons come only from the fixed taxonomy."""
    tampered = _tampered(canonical_graph)
    service = tampered["segments"]["works_yard"]
    service["end_b"] = {"termination": "ran_out_of_geometry"}
    errors = road_graph.validate_road_graph(tampered, master_document, production_document)
    assert any("taxonomy" in error for error in errors)


def test_termination_taxonomy_is_pinned(road_graph):
    """The taxonomy is exactly the contract's list, including wall_break."""
    assert road_graph.TERMINATION_TYPES == (
        "cul_de_sac",
        "district_edge",
        "world_edge",
        "service_destination",
        "port_quay",
        "plaza_approach",
        "infrastructure_access",
        "wall_break",
    )


def test_junction_off_the_street_is_detected(
    road_graph, canonical_graph, master_document, production_document
):
    """A declared intersection must actually intersect."""
    tampered = _tampered(canonical_graph)
    orbital = tampered["segments"]["orbital"]
    tampered["nodes"]["floating_junction"] = {"x": 0.0, "y": 0.0}
    orbital["via"] = [*orbital["via"], "floating_junction"]
    errors = road_graph.validate_road_graph(tampered, master_document, production_document)
    assert any("must actually intersect" in error for error in errors)


def test_unregistered_crossing_is_detected(
    road_graph, canonical_graph, master_document, production_document
):
    """No street may cross another without a shared junction node."""
    tampered = _tampered(canonical_graph)
    tampered["segments"]["rogue"] = {
        "class": "local",
        "path": [(18.0, -52.0), (18.0, -60.0)],
        "closed": False,
        "end_a": {"termination": "cul_de_sac"},
        "end_b": {"termination": "cul_de_sac"},
        "via": [],
        "existing": False,
        "owner": "",
    }
    errors = road_graph.validate_road_graph(tampered, master_document, production_document)
    assert any("with no junction" in error for error in errors)


def test_street_through_a_wall_station_is_refused(
    road_graph, canonical_graph, master_document, production_document
):
    """The scar keeps its ground: crossing a wall line is refused."""
    tampered = _tampered(canonical_graph)
    station = master_document["boundaries"]["boundary_ab"]["wall_station"]
    x, y = station["center"]
    tampered["segments"]["through_history"] = {
        "class": "local",
        "path": [(x - 6.0, y), (x + 6.0, y)],
        "closed": False,
        "end_a": {"termination": "cul_de_sac"},
        "end_b": {"termination": "cul_de_sac"},
        "via": [],
        "existing": False,
        "owner": "",
    }
    errors = road_graph.validate_road_graph(tampered, master_document, production_document)
    assert any("keeps its ground" in error for error in errors)


def test_street_over_a_founding_plate_is_refused(
    road_graph, canonical_graph, master_document, production_document
):
    """Production streets never invade the founding plates."""
    tampered = _tampered(canonical_graph)
    center = master_document["districts"]["district_a"]["center"]
    tampered["segments"]["over_the_core"] = {
        "class": "local",
        "path": [(center[0] - 4.0, center[1]), (center[0] + 4.0, center[1])],
        "closed": False,
        "end_a": {"termination": "cul_de_sac"},
        "end_b": {"termination": "cul_de_sac"},
        "via": [],
        "existing": False,
        "owner": "",
    }
    errors = road_graph.validate_road_graph(tampered, master_document, production_document)
    assert any("never overbuilt" in error for error in errors)


def test_street_into_the_harbor_is_refused(
    road_graph, canonical_graph, master_document, production_document
):
    """Only port_quay-terminated stubs may approach the quay line."""
    tampered = _tampered(canonical_graph)
    tampered["segments"]["into_the_water"] = {
        "class": "local",
        "path": [(58.0, -18.0), (66.0, -16.0)],
        "closed": False,
        "end_a": {"termination": "cul_de_sac"},
        "end_b": {"termination": "cul_de_sac"},
        "via": [],
        "existing": False,
        "owner": "",
    }
    errors = road_graph.validate_road_graph(tampered, master_document, production_document)
    assert any("harbor water" in error for error in errors)


def test_street_beyond_the_diorama_is_refused(
    road_graph, canonical_graph, master_document, production_document
):
    """No street point may leave the diorama's road extent."""
    tampered = _tampered(canonical_graph)
    tampered["segments"]["off_world"] = {
        "class": "local",
        "path": [(-60.0, 40.0), (-76.0, 40.0)],
        "closed": False,
        "end_a": {"termination": "cul_de_sac"},
        "end_b": {"termination": "cul_de_sac"},
        "via": [],
        "existing": False,
        "owner": "",
    }
    errors = road_graph.validate_road_graph(tampered, master_document, production_document)
    assert any("leaves the diorama" in error for error in errors)


def test_stranded_streets_are_detected(
    road_graph, canonical_graph, master_document, production_document
):
    """A street cluster with no path to the founding network is refused."""
    tampered = _tampered(canonical_graph)
    tampered["nodes"]["island_a"] = {"x": -20.0, "y": -40.0}
    tampered["segments"]["island_one"] = {
        "class": "local",
        "path": [(-24.0, -44.0), (-20.0, -40.0)],
        "closed": False,
        "end_a": {"termination": "cul_de_sac"},
        "end_b": {"node": "island_a"},
        "via": [],
        "existing": False,
        "owner": "",
    }
    tampered["segments"]["island_two"] = {
        "class": "local",
        "path": [(-20.0, -40.0), (-16.0, -44.0)],
        "closed": False,
        "end_a": {"node": "island_a"},
        "end_b": {"termination": "cul_de_sac"},
        "via": [],
        "existing": False,
        "owner": "",
    }
    errors = road_graph.validate_road_graph(tampered, master_document, production_document)
    assert any("floating fragments" in error for error in errors)


def test_hierarchy_widths_are_ordered(road_graph):
    """Arterials outrank collectors, which outrank locals."""
    widths = road_graph.ROAD_CLASS_WIDTHS
    assert widths["arterial"] > widths["collector"] > widths["local"]
    assert widths["arterial"] == pytest.approx(7.0)
