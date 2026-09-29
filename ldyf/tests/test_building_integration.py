"""``ldyf.building_integration``: the kit -> geometry join, and its validators.

The fixture is a hand-built lattice laid out the way ``test_city_layout`` does it
(``make_lattice_spec`` -> ``city_layout.blocks`` -> ``city_layout.building_slots``),
so the slots carry the real ``slot_id`` / ``block_id`` / ``x`` / ``y`` / ``yaw`` /
``width_cm`` / ``depth_cm`` fields ``building_kits`` consumes.
"""

from __future__ import annotations

import copy
import json

import pytest

from ldyf import building_geometry, building_kits
from ldyf.building_integration import (
    SCHEMA_VERSION,
    family_material_paths,
    footprints_overlap,
    integrate_buildings,
    probe_path,
    validate_integration,
)
from ldyf.city_layout import blocks, building_slots

LANE_W = 200.0
DEPTH_CM = 1500.0


# ---------------------------------------------------------------- fixtures --


def _pt(x, y):
    return {"x": float(x), "y": float(y), "z": 0.0}


def make_lattice_spec(n_x: int, n_y: int, *, step_cm: float = 20000.0,
                      lane_width: float = LANE_W) -> dict:
    """Hand-built lattice, same construction as ``test_city_layout``."""
    pos = {f"J{c}_{r}": _pt(c * step_cm, r * step_cm)
           for c in range(n_x) for r in range(n_y)}
    junctions = [{"id": jid, "type": "priority", "position": pos[jid],
                  "polygon": None, "incoming_edge_ids": []}
                 for jid in sorted(pos)]
    edges: list[dict] = []

    def add_edge(eid: str, a: str, b: str) -> None:
        edges.append({"id": eid, "from_junction": a, "to_junction": b,
                      "function": "normal", "priority": 1,
                      "lanes": [{"id": f"{eid}_0", "index": 0,
                                 "width_cm": lane_width,
                                 "width_cm_effective": lane_width,
                                 "width_source": "attribute",
                                 "speed_mps": 13.89, "length_m": 200.0,
                                 "allow": None, "disallow": None,
                                 "polyline": [dict(pos[a]), dict(pos[b])]}]})

    for r in range(n_y):
        for c in range(n_x - 1):
            add_edge(f"H{r}_{c}", f"J{c}_{r}", f"J{c + 1}_{r}")
    for c in range(n_x):
        for r in range(n_y - 1):
            add_edge(f"V{c}_{r}", f"J{c}_{r}", f"J{c}_{r + 1}")
    return {"schema_version": "road_spec_v1", "edges": edges,
            "junctions": junctions,
            "counts": {"edges": len(edges), "junctions": len(junctions)}}


def make_layout(n: int = 3, *, seed: int = 11, step_cm: float = 20000.0) -> dict:
    """A ``city_layout_v1``-shaped document: blocks + building slots."""
    spec = make_lattice_spec(n, n, step_cm=step_cm)
    return {"schema_version": "city_layout_v1", "seed": seed,
            "blocks": blocks(spec),
            "building_slots": building_slots(spec, kits=["a", "b", "c"],
                                             seed=seed)}


def make_doc(layout: dict = None, **kw) -> dict:
    layout = make_layout() if layout is None else layout
    return integrate_buildings(layout, depth_cm=kw.pop("depth_cm", DEPTH_CM),
                               seed=kw.pop("seed", 11), **kw)


def _all_buildings(doc: dict) -> list:
    return [e for block_id in doc["blocks"] for e in doc["blocks"][block_id]]


def _probe_materials() -> set:
    raw = json.loads(probe_path().read_text(encoding="utf-8"))
    return {str(m) for m in raw["building_materials"]}


# -------------------------------------------------------------- the shape ---


def test_document_matches_the_editor_contract():
    doc = make_doc()
    assert doc["schema_version"] == SCHEMA_VERSION
    assert set(doc) == {"schema_version", "blocks", "family_paths", "landmark",
                        "counts"}
    assert set(doc["landmark"]) == {"block", "id", "geometry"}
    for block_id, entries in doc["blocks"].items():
        assert isinstance(block_id, str)
        assert entries, f"block {block_id} has no buildings"
        for e in entries:
            assert set(e) == {"id", "family", "geometry"}
            assert isinstance(e["id"], str)
            assert e["geometry"]["schema_version"] == \
                building_geometry.SCHEMA_VERSION


def test_determinism_is_byte_identical():
    layout = make_layout()
    a = integrate_buildings(layout, depth_cm=DEPTH_CM, seed=11)
    b = integrate_buildings(layout, depth_cm=DEPTH_CM, seed=11)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    c = integrate_buildings(make_layout(), depth_cm=DEPTH_CM, seed=11)
    assert json.dumps(a, sort_keys=True) == json.dumps(c, sort_keys=True)


def test_every_emitted_geometry_validates():
    doc = make_doc()
    for e in _all_buildings(doc):
        assert building_geometry.validate_geometry(e["geometry"]) == [], e["id"]
    assert building_geometry.validate_geometry(
        doc["landmark"]["geometry"]) == []


def test_footprints_come_from_street_life_inputs():
    layout = make_layout()
    doc = integrate_buildings(layout, depth_cm=DEPTH_CM, seed=11)
    from ldyf.street_life_inputs import building_footprint

    slot = next(s for s in layout["building_slots"]["slots"]
                if s["slot_id"] == doc["landmark"]["id"])
    expected = [[round(c["x"], 3), round(c["y"], 3)]
                for c in building_footprint(slot, depth_cm=DEPTH_CM)]
    assert doc["counts"]["footprints"][doc["landmark"]["id"]] == expected


# ------------------------------------------------------- families / probe ---


def test_every_family_resolves_to_a_path_in_the_probe_file():
    probed = _probe_materials()
    paths = family_material_paths()
    for e in _all_buildings(make_doc()):
        assert e["family"] in paths
    assert set(building_kits.FACADE_FAMILIES) <= set(paths)
    for family, path in paths.items():
        assert path in probed, f"{family} -> {path}"
    for family, members in building_kits.FACADE_FAMILIES.items():
        assert paths[family] in set(members)
    assert paths[building_kits.CIVIC_FAMILY] in \
        set(building_kits.LANDMARK_MATERIALS)


def test_family_paths_are_stable():
    assert family_material_paths() == family_material_paths()


# --------------------------------------------------------------- landmark ---


def test_exactly_one_landmark_and_its_slot_carries_no_ordinary_building():
    layout = make_layout()
    doc = make_doc(layout)
    spec = building_kits.landmark_spec(layout)
    lm = doc["landmark"]
    assert lm["id"] == spec["building_id"]
    assert lm["block"] == spec["block_id"]
    ids = [e["id"] for e in _all_buildings(doc)]
    assert lm["id"] not in ids
    slots = layout["building_slots"]["slots"]
    assert len(ids) == len(slots) - 1
    assert len(ids) == len(set(ids))
    assert doc["counts"]["landmark"] == 1
    assert lm["id"] in doc["counts"]["footprints"]


def test_landmark_geometry_is_a_landmark_and_stands_above_the_bands():
    doc = make_doc()
    assert doc["landmark"]["geometry"]["counts"]["kind"] == "landmark"
    assert doc["landmark"]["geometry"]["bounds"]["max_z"] >= \
        building_kits.LANDMARK_MIN_HEIGHT_CM


# ------------------------------------------------------- blocks / overlap ---


def test_blocks_partition_the_buildings_with_none_lost():
    layout = make_layout()
    doc = make_doc(layout)
    slots = layout["building_slots"]["slots"]
    slot_ids = {s["slot_id"] for s in slots}
    by_block = {s["slot_id"]: s["block_id"] for s in slots}
    emitted = [e["id"] for e in _all_buildings(doc)]
    assert set(emitted) == slot_ids - {doc["landmark"]["id"]}
    assert doc["counts"]["buildings"] == len(emitted)
    assert doc["counts"]["blocks"] == len(doc["blocks"])
    for block_id, entries in doc["blocks"].items():
        for e in entries:
            assert by_block[e["id"]] == block_id
        assert [e["id"] for e in entries] == \
            sorted(e["id"] for e in entries)


def test_buildings_do_not_overlap_and_the_document_validates():
    doc = make_doc()
    rings = doc["counts"]["footprints"]
    ids = sorted(rings)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            assert not footprints_overlap(rings[a], rings[b]), (a, b)
    assert validate_integration(doc) == []


def test_overlap_test_is_not_a_bounding_box_test():
    a = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
    touch = [[100.0, 100.0], [200.0, 100.0], [200.0, 200.0], [100.0, 200.0]]
    over = [[50.0, 50.0], [150.0, 50.0], [150.0, 150.0], [50.0, 150.0]]
    assert not footprints_overlap(a, touch)
    assert footprints_overlap(a, over)
    assert footprints_overlap(a, copy.deepcopy(a))


# ------------------------------------------------- validate catches things --


def test_validate_catches_a_broken_geometry_document():
    doc = make_doc()
    e = _all_buildings(doc)[0]
    e["geometry"]["triangles"] = []
    problems = validate_integration(doc)
    assert any(e["id"] in p and "vertices length" in p for p in problems)


def test_validate_catches_an_unknown_family():
    doc = make_doc()
    _all_buildings(doc)[0]["family"] = "no_such_family"
    assert any("has no entry in family_paths" in p
               for p in validate_integration(doc))


def test_validate_catches_a_path_absent_from_the_probe_file():
    doc = make_doc()
    doc["family_paths"]["brick"] = "/Game/Building/Material/MI/NotProbed"
    problems = validate_integration(doc)
    assert any("is not in asset_probe_v3.json" in p for p in problems)


def test_validate_catches_more_or_fewer_than_one_landmark():
    doc = make_doc()
    lm = doc["landmark"]
    doc["landmark"] = [copy.deepcopy(lm), copy.deepcopy(lm)]
    assert any("exactly one landmark, found 2" in p
               for p in validate_integration(doc))
    doc2 = make_doc()
    doc2["landmark"] = None
    assert any("exactly one landmark, found 0" in p
               for p in validate_integration(doc2))


def test_validate_catches_a_block_with_zero_buildings():
    doc = make_doc()
    doc["blocks"]["EMPTY"] = []
    assert any("has zero buildings" in p for p in validate_integration(doc))


def test_validate_catches_the_landmark_orphan_two_ways():
    """The defect the overlap check exists for: a second building on the
    landmark's slot."""
    doc = make_doc()
    lm = doc["landmark"]
    family = _all_buildings(doc)[0]["family"]

    same_id = copy.deepcopy(doc)
    same_id["blocks"][lm["block"]].append(
        {"id": lm["id"], "family": family,
         "geometry": copy.deepcopy(lm["geometry"])})
    problems = validate_integration(same_id)
    assert any("also appears as an ordinary building" in p for p in problems)
    assert any("one footprint" in p for p in problems)

    squatter = copy.deepcopy(doc)
    squatter["counts"]["footprints"]["SQUATTER"] = \
        list(squatter["counts"]["footprints"][lm["id"]])
    squatter["blocks"][lm["block"]].append(
        {"id": "SQUATTER", "family": family,
         "geometry": copy.deepcopy(lm["geometry"])})
    problems = validate_integration(squatter)
    assert any("SQUATTER" in p and "footprints overlap" in p
               for p in problems)


def test_validate_catches_a_tampered_landmark_block_name():
    doc = make_doc()
    doc["landmark"]["block"] = "NO_SUCH_BLOCK"
    assert any("which has no buildings" in p
               for p in validate_integration(doc))


# ------------------------------------------------------------- ValueError --


def test_integrate_rejects_non_positive_depth():
    layout = make_layout()
    for bad in (0.0, -1.0, -1500.0):
        with pytest.raises(ValueError):
            integrate_buildings(layout, depth_cm=bad, seed=1)


def test_integrate_rejects_a_layout_with_no_building_slots():
    layout = make_layout()
    layout["building_slots"] = {"slots": [], "seed": 1}
    with pytest.raises(ValueError):
        integrate_buildings(layout, depth_cm=DEPTH_CM, seed=1)
    with pytest.raises(ValueError):
        integrate_buildings({"blocks": []}, depth_cm=DEPTH_CM, seed=1)


def test_validate_rejects_a_non_document():
    assert validate_integration([]) == ["document is not a dict"]
    doc = make_doc()
    doc["schema_version"] = "something_else"
    assert any("schema_version" in p for p in validate_integration(doc))
