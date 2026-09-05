"""Tests for the authored surface material spec.

This material exists because City Sample's MS_DefaultMaterial fails to compile
in this project ("Missing Material Function"), and a material that fails to
compile renders with fallback shading — the block-interior speckle. These tests
guard the properties that made the replacement necessary in the first place.
"""

from __future__ import annotations

import json

import pytest

from ldyf.surface_material import (
    MASTER_DEFAULTS,
    P_TILING,
    SCALAR_PARAMETER_NAMES,
    SURFACE_SPEC_VERSION,
    TEXTURE_PARAMETER_NAMES,
    surface_graph,
    validate_graph,
)


def _g(**kw):
    return surface_graph(**kw)


def test_graph_validates_clean():
    """An unreachable node or a dangling connection would compile to something
    other than what the spec describes."""
    assert validate_graph(_g()) == []


def test_schema_version_and_outputs():
    g = _g()
    assert g["schema_version"] == SURFACE_SPEC_VERSION
    assert set(g["outputs"]) == {"BaseColor", "Normal", "Roughness", "Specular"}


def test_node_ids_are_unique():
    ids = [n["id"] for n in _g()["nodes"]]
    assert len(ids) == len(set(ids))


def test_every_node_reaches_an_output():
    assert not [p for p in validate_graph(_g()) if "cannot reach" in p]


def test_uv_mask_states_every_channel():
    """Unreal's ComponentMask defaults to R+G checked, so a node that sets only
    the channels it wants silently keeps a default one. That exact mistake made
    an entire facade render as one flat colour. Would break if a mask relied on
    the engine default again."""
    masks = [n for n in _g()["nodes"]
             if n["class"] == "MaterialExpressionComponentMask"]
    assert masks
    for m in masks:
        assert set(m["props"]) == {"r", "g", "b", "a"}


def test_uv_mask_selects_x_and_y_only():
    m = [n for n in _g()["nodes"]
         if n["class"] == "MaterialExpressionComponentMask"][0]
    assert m["props"]["r"] is True and m["props"]["g"] is True
    assert m["props"]["b"] is False and m["props"]["a"] is False


def test_uv_is_world_position_divided_by_tiling():
    """Texel density must be a real size in centimetres rather than a function
    of the mesh's own UVs: the ground is one very large polygon whose UVs span
    the whole city, which is why every tiling value on the old material produced
    sub-pixel noise."""
    conns = {(c["from"], c["to"], c["to_input"]) for c in _g()["connections"]}
    assert ("wp", "uv_xy", "") in conns
    assert ("uv_xy", "uv", "A") in conns
    assert ("tiling", "uv", "B") in conns


def test_all_three_textures_sample_the_shared_uv():
    conns = {(c["from"], c["to"], c["to_input"]) for c in _g()["connections"]}
    for nid in ("alb", "nrm", "rgh"):
        assert ("uv", nid, "UVs") in conns


def test_texture_parameter_names_present():
    names = {n["props"].get("parameter_name") for n in _g()["nodes"]
             if n["class"] == "MaterialExpressionTextureSampleParameter2D"}
    assert set(TEXTURE_PARAMETER_NAMES) <= names


def test_scalar_parameter_names_present():
    names = {n["props"].get("parameter_name") for n in _g()["nodes"]
             if n["class"] == "MaterialExpressionScalarParameter"}
    assert set(SCALAR_PARAMETER_NAMES) <= names


def test_base_colour_is_albedo_times_tint():
    conns = {(c["from"], c["to"], c["to_input"]) for c in _g()["connections"]}
    assert ("alb", "base", "A") in conns
    assert ("tint", "base", "B") in conns
    assert _g()["outputs"]["BaseColor"] == "base"


def test_roughness_is_texture_times_scale():
    conns = {(c["from"], c["to"], c["to_input"]) for c in _g()["connections"]}
    assert ("rgh", "rough", "A") in conns
    assert ("rough_scale", "rough", "B") in conns


def test_tiling_default_is_the_master_default():
    t = [n for n in _g()["nodes"]
         if n["props"].get("parameter_name") == P_TILING][0]
    assert t["props"]["default_value"] == MASTER_DEFAULTS[P_TILING]


def test_tiling_argument_is_honoured():
    g = _g(tiling_cm=250.0)
    t = [n for n in g["nodes"] if n["props"].get("parameter_name") == P_TILING][0]
    assert t["props"]["default_value"] == 250.0
    assert g["params"][P_TILING] == 250.0


def test_non_positive_tiling_raises():
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            _g(tiling_cm=bad)


def test_negative_roughness_scale_raises():
    with pytest.raises(ValueError):
        _g(roughness_scale=-0.1)


def test_vector_default_is_a_json_safe_list():
    v = [n for n in _g()["nodes"]
         if n["class"] == "MaterialExpressionVectorParameter"][0]
    assert isinstance(v["props"]["default_value"], list)


def test_determinism():
    assert json.dumps(_g(), sort_keys=True) == json.dumps(_g(), sort_keys=True)


def test_validate_catches_duplicate_id():
    g = _g()
    g["nodes"].append(dict(g["nodes"][0]))
    assert any("duplicate" in p for p in validate_graph(g))


def test_validate_catches_unknown_connection():
    g = _g()
    g["connections"].append({"from": "nope", "from_output": "",
                             "to": "uv", "to_input": "A"})
    assert any("unknown node" in p for p in validate_graph(g))


def test_validate_catches_unknown_output():
    g = _g()
    g["outputs"]["BaseColor"] = "nope"
    assert any("output BaseColor" in p for p in validate_graph(g))


def test_validate_catches_orphan_node():
    g = _g()
    g["nodes"].append({"id": "orphan", "class": "MaterialExpressionConstant",
                       "props": {}, "x": 0.0, "y": 0.0})
    assert any("orphan" in p for p in validate_graph(g))
