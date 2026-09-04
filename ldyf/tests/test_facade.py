"""Tests for ``ldyf.facade`` -- the ``facade_spec_v1`` material-graph spec.

The facade material is authored as a pure-Python node-graph specification (no
``import unreal``) so it can be unit-tested here; a thin editor module turns the
graph into ``MaterialEditingLibrary`` calls.  These tests pin down the graph
structure, the parameter/kit contract, validation behaviour and determinism.
"""
from __future__ import annotations

import copy
import itertools
import json

import pytest

from ldyf.facade import (
    EXPRESSION_CLASSES,
    FACADE_SPEC_VERSION,
    PARAMETER_NAMES,
    P_EDGE,
    P_GROUND,
    P_SPACING_H,
    P_SPACING_V,
    P_WALL_COL,
    P_WIN_COL,
    P_WIN_H,
    P_WIN_W,
    facade_graph,
    kit_parameters,
    validate_graph,
)

KITS = ("CHA", "NYA", "SFA")


def _graph(**over):
    kw = {"spacing_h_cm": 320.0, "spacing_v_cm": 340.0, "window_w": 0.30,
          "window_h": 0.52, "edge_sharpness": 60.0, "ground_floor_cm": 400.0}
    kw.update(over)
    return facade_graph(**kw)


def _broken(over):
    """A valid graph mutated by ``over(graph)``; deep-copied per call."""
    g = copy.deepcopy(_graph())
    over(g)
    return g


def _reach_outputs(g):
    """Ids of nodes that have a directed path to some output (backward walk)."""
    ids = {n["id"] for n in g["nodes"]}
    bwd = {}
    for c in g["connections"]:
        if c["from"] in ids and c["to"] in ids:
            bwd.setdefault(c["to"], set()).add(c["from"])
    seen = set(g["outputs"].values())
    stack = list(seen)
    while stack:
        cur = stack.pop()
        for prv in bwd.get(cur, ()):
            if prv not in seen:
                seen.add(prv)
                stack.append(prv)
    return seen


def _inputs_of(g, nid):
    return {(c["from"], c["to_input"]) for c in g["connections"]
            if c["to"] == nid}


# ------------------------------------------------------------------ structure

def test_valid_graph_clean():
    assert validate_graph(_graph()) == []


def test_schema_version():
    g = _graph()
    assert g["schema_version"] == FACADE_SPEC_VERSION == "facade_spec_v1"


def test_outputs_cover_three_material_properties():
    assert set(_graph()["outputs"]) == {"BaseColor", "Roughness", "Metallic"}


def test_every_node_id_unique():
    ids = [n["id"] for n in _graph()["nodes"]]
    assert len(ids) == len(set(ids))


def test_every_node_reaches_an_output():
    g = _graph()
    assert {n["id"] for n in g["nodes"]} <= _reach_outputs(g)


def test_connections_reference_existing_nodes():
    g = _graph()
    ids = {n["id"] for n in g["nodes"]}
    for c in g["connections"]:
        assert c["from"] in ids, c
        assert c["to"] in ids, c


def test_all_expression_classes_allowed():
    for n in _graph()["nodes"]:
        assert n["class"] in EXPRESSION_CLASSES, n["id"]
        assert {"id", "class", "props", "x", "y"} <= set(n)


def test_expected_node_ids_present():
    expected = {"wp", "wx", "wy", "wz", "sum_xy", "div_h", "frac_h", "sub_h",
                "abs_h", "open_h", "mul_h", "sat_h", "div_v", "frac_v",
                "sub_v", "abs_v", "open_v", "mul_v", "sat_v", "grid_mask",
                "below_ground", "ground_mul", "ground_band", "mask",
                "base_color", "roughness", "metallic"}
    assert expected <= {n["id"] for n in _graph()["nodes"]}


def test_material_outputs_are_lerps_over_final_mask():
    g = _graph()
    for prop, nid in g["outputs"].items():
        alphas = {frm for frm, _in in _inputs_of(g, nid) if _in == "Alpha"}
        assert alphas == {"mask"}, prop


def test_grid_mask_is_product_of_horizontal_and_vertical_saturation():
    assert _inputs_of(_graph(), "grid_mask") == {("sat_h", "A"),
                                                 ("sat_v", "B")}


def test_horizontal_bay_driven_by_world_xy():
    g = _graph()
    assert _inputs_of(g, "sum_xy") == {("wx", "A"), ("wy", "B")}
    assert _inputs_of(g, "div_h") == {("sum_xy", "A"), ("spacing_h", "B")}
    assert {c["from"] for c in g["connections"] if c["to"] == "frac_h"} \
        == {"div_h"}


def test_vertical_floor_driven_by_world_z():
    g = _graph()
    assert _inputs_of(g, "div_v") == {("wz", "A"), ("spacing_v", "B")}
    assert {c["from"] for c in g["connections"] if c["to"] == "frac_v"} \
        == {"div_v"}


def test_world_position_feeds_all_three_channel_masks():
    g = _graph()
    feeds = {c["to"] for c in g["connections"] if c["from"] == "wp"}
    assert feeds == {"wx", "wy", "wz"}


def test_ground_band_replaces_grid_below_ground_floor():
    g = _graph()
    # final mask lerp: A=grid, B=shopfront, selected by the ground step band
    assert _inputs_of(g, "mask") == {("grid_mask", "A"),
                                     ("shopfront", "B"),
                                     ("ground_band", "Alpha")}
    # the band itself: saturate((ground_floor_cm - Z) * constant)
    assert _inputs_of(g, "below_ground") == {("ground_cm", "A"), ("wz", "B")}
    assert _inputs_of(g, "ground_mul") == {("below_ground", "A"),
                                           ("ground_step", "B")}


def test_window_mask_is_saturate_of_scaled_openness():
    g = _graph()
    # sat_h = saturate((win_w - abs(frac(h)-0.5)) * edge_sharpness)
    assert _inputs_of(g, "mul_h") == {("open_h", "A"), ("edge", "B")}
    assert _inputs_of(g, "open_h") == {("win_w", "A"), ("abs_h", "B")}
    assert {c["from"] for c in g["connections"] if c["to"] == "sub_h"} \
        == {"frac_h", "half"}


# ------------------------------------------------------------------ parameters

def test_parameter_names_unique_and_complete():
    g = _graph()
    names = [n["props"]["parameter_name"] for n in g["nodes"]
             if "parameter_name" in n["props"]]
    assert len(names) == len(set(names))
    assert set(names) == set(PARAMETER_NAMES)
    assert set(g["params"]) == set(PARAMETER_NAMES)


def test_params_dict_matches_node_defaults():
    g = _graph()
    for n in g["nodes"]:
        if "parameter_name" in n["props"]:
            pn = n["props"]["parameter_name"]
            assert pn in g["params"], pn
            assert n["props"]["default_value"] == g["params"][pn], pn


def test_every_tunable_is_a_named_parameter_node():
    g = _graph()
    tunables = {P_SPACING_H, P_SPACING_V, P_WIN_W, P_WIN_H, P_EDGE, P_GROUND,
                P_WALL_COL, P_WIN_COL}
    names = {n["props"]["parameter_name"] for n in g["nodes"]
             if "parameter_name" in n["props"]}
    assert tunables <= names


def test_ground_floor_and_edge_are_tunable_parameters():
    g = _graph()
    scalar = {n["props"]["parameter_name"] for n in g["nodes"]
              if n["class"] == "MaterialExpressionScalarParameter"}
    assert P_GROUND in scalar and P_EDGE in scalar


# ------------------------------------------------------------------ kits

def test_kits_return_scalar_and_vector_maps():
    for kit in KITS:
        p = kit_parameters(kit)
        assert set(p) == {"scalar", "vector"}
        assert P_WALL_COL in p["vector"] and P_WIN_COL in p["vector"]
        assert P_SPACING_V in p["scalar"]


def test_kit_wall_colours_pairwise_distinct():
    cols = {kit: kit_parameters(kit)["vector"][P_WALL_COL] for kit in KITS}
    for a, b in itertools.combinations(KITS, 2):
        assert cols[a] != cols[b], (a, b)


def test_kit_floor_heights_pairwise_distinct():
    heights = {kit: kit_parameters(kit)["scalar"][P_SPACING_V] for kit in KITS}
    for a, b in itertools.combinations(KITS, 2):
        assert heights[a] != heights[b], (a, b)


def test_kit_window_proportions_pairwise_distinct():
    props = {kit: (kit_parameters(kit)["scalar"][P_WIN_W],
                   kit_parameters(kit)["scalar"][P_WIN_H]) for kit in KITS}
    for a, b in itertools.combinations(KITS, 2):
        assert props[a] != props[b], (a, b)


def test_kit_colours_are_not_shades_of_grey():
    for kit in KITS:
        r, g, b = kit_parameters(kit)["vector"][P_WALL_COL]
        assert max(r, g, b) - min(r, g, b) > 0.05, kit


def test_kit_override_names_are_master_parameter_names():
    for kit in KITS:
        p = kit_parameters(kit)
        names = set(p["scalar"]) | set(p["vector"])
        assert names <= set(PARAMETER_NAMES), kit


def test_unknown_kit_raises_value_error():
    with pytest.raises(ValueError):
        kit_parameters("PARIS")


# ------------------------------------------------------------------ validation

def test_validate_catches_duplicate_node_id():
    def over(g):
        g["nodes"].append({"id": "wp", "class": "MaterialExpressionConstant",
                           "props": {"R": 1.0}, "x": 0.0, "y": 0.0})
    problems = validate_graph(_broken(over))
    assert any("used more than once" in p and "wp" in p for p in problems)


def test_validate_catches_connection_to_unknown_node():
    def over(g):
        g["connections"].append({"from": "ghost", "from_output": "",
                                 "to": "wp", "to_input": ""})
    problems = validate_graph(_broken(over))
    assert any("unknown node" in p and "ghost" in p for p in problems)


def test_validate_catches_node_with_no_path_to_output():
    def over(g):
        g["nodes"].append({"id": "orphan",
                           "class": "MaterialExpressionConstant",
                           "props": {"R": 0.0}, "x": 0.0, "y": 0.0})
    problems = validate_graph(_broken(over))
    assert any("no path to any output" in p and "orphan" in p
               for p in problems)


def test_validate_catches_output_without_node():
    def over(g):
        g["outputs"]["BaseColor"] = "missing_node"
    problems = validate_graph(_broken(over))
    assert any("unknown node" in p and "missing_node" in p for p in problems)


def test_validate_catches_cycle():
    def over(g):
        g["nodes"].extend([
            {"id": "c1", "class": "MaterialExpressionConstant",
             "props": {"R": 0.0}, "x": 0.0, "y": 0.0},
            {"id": "c2", "class": "MaterialExpressionConstant",
             "props": {"R": 0.0}, "x": 0.0, "y": 0.0},
        ])
        g["connections"].extend([
            {"from": "c1", "from_output": "", "to": "c2", "to_input": ""},
            {"from": "c2", "from_output": "", "to": "c1", "to_input": ""},
            {"from": "c2", "from_output": "", "to": "mask", "to_input": "A"},
        ])
    problems = validate_graph(_broken(over))
    assert any("cycle" in p for p in problems)


# ------------------------------------------------------------------ determinism

def test_determinism_two_calls_identical():
    a = _graph()
    b = _graph()
    assert a == b
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_determinism_node_order_stable():
    ids_a = [n["id"] for n in _graph()["nodes"]]
    ids_b = [n["id"] for n in _graph()["nodes"]]
    assert ids_a == ids_b


def test_component_masks_state_every_channel_explicitly():
    """Unreal's ComponentMask defaults to R+G checked, so a node that sets only
    the channel it wants silently keeps a second channel and returns a vector
    where the graph needs a scalar.  The first built material rendered every
    facade as one flat colour for exactly this reason.  Would break if a mask
    ever went back to relying on the engine default."""
    g = facade_graph(spacing_h_cm=350.0, spacing_v_cm=400.0, window_w=0.3,
                     window_h=0.34, edge_sharpness=40.0, ground_floor_cm=450.0)
    masks = [n for n in g["nodes"] if n["class"] == "MaterialExpressionComponentMask"]
    assert masks, "the graph must split WorldPosition into components"
    for n in masks:
        props = n["props"]
        assert set(props) == {"r", "g", "b", "a"}, (
            "mask %s states %s; it must state every channel" % (n["id"], sorted(props)))
        assert sum(1 for v in props.values() if v) == 1, (
            "mask %s selects %d channels; each must be a single scalar"
            % (n["id"], sum(1 for v in props.values() if v)))


def test_component_masks_select_x_y_and_z_once_each():
    """The three masks must select X, Y and Z respectively -- one each, no
    duplicates -- or the bay and floor coordinates collapse together."""
    g = facade_graph(spacing_h_cm=350.0, spacing_v_cm=400.0, window_w=0.3,
                     window_h=0.34, edge_sharpness=40.0, ground_floor_cm=450.0)
    picked = {}
    for n in g["nodes"]:
        if n["class"] != "MaterialExpressionComponentMask":
            continue
        chan = [c for c in ("r", "g", "b", "a") if n["props"].get(c)][0]
        picked[n["id"]] = chan
    assert sorted(picked.values()) == ["b", "g", "r"]


def test_kit_window_fractions_stay_below_the_degenerate_half():
    """window_w/window_h are half-widths measured from a bay's centre, so at 0.5
    the mask covers the entire bay and the grid disappears -- vertically that
    means continuous ribbons with no floors.  Two kits originally shipped at
    0.50 and 0.62 and rendered exactly that way.  Would break if a kit crept
    back to >= 0.5."""
    for kit in ("CHA", "NYA", "SFA"):
        sc = kit_parameters(kit)["scalar"]
        assert 0.0 < sc[P_WIN_W] < 0.5, "%s window_w %s" % (kit, sc[P_WIN_W])
        assert 0.0 < sc[P_WIN_H] < 0.5, "%s window_h %s" % (kit, sc[P_WIN_H])
