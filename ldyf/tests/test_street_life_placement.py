"""street_life_placement tests: real tables, inline fixtures, no Unreal.

Every fixture is built inline (the style of ldyf/tests/test_dressing_check.py).
The mesh paths in ``FIXTURE_TABLES`` are **not assets**: they exist only in
this module so the z rule of a category whose real table is empty stays
testable. The production tables are asserted separately, against the real paths
the module cites.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from ldyf.street_life_placement import (
    GLOBAL_SCALE_BAND,
    KINDS,
    PARKED_VEHICLE_MESHES,
    PLACEMENT_VERSION,
    ROOFTOP_MESHES,
    SCALE_BAND,
    SIGN_MESHES,
    SOURCE_LISTS,
    SOURCE_VERSION,
    STOREFRONT_MESHES,
    Z_CEILING_CM,
    group_by_mesh,
    placement_rows,
    validate_placement,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# test-only placeholders -- never spawned, never in the module's tables
FIXTURE_STOREFRONT = "/Game/Fake/SM_StorefrontFixture"
FIXTURE_ROOF = "/Game/Fake/SM_RoofFixture"
FIXTURE_CAR = "/Game/Fake/SM_CarFixture"
FIXTURE_TABLES = {
    "storefront": [FIXTURE_STOREFRONT],
    "rooftop_prop": [FIXTURE_ROOF],
    "parked_car": [FIXTURE_CAR],
}

ROOF_HEIGHT_CM = 2400.0        # the building record's roof plane
ROOF_PROP_HEIGHT_CM = 80.0     # the prop's own size, NOT its z
SIGN_HEIGHT_CM = 260.0         # mounting height over the pavement
SIGN_ID = "sign_storefront_b01"
ROOF_ID = "roof_b01_0"
CAR_ID = "parked_way1_0"


def _source() -> dict:
    """A street_life_v1 document shaped exactly like build_street_life's."""
    return {
        "schema_version": SOURCE_VERSION,
        "params": {"seed": 0},
        "storefronts": [
            {"id": "storefront_b01", "x": 100.0, "y": 250.0, "yaw_deg": 90.0,
             "kind": "shopfront", "width_cm": 1400.0, "block_id": "b01",
             "depth_cm": 90.0, "footway_cm": 300.0, "slot_id": "b01"},
        ],
        "signs": [
            {"id": SIGN_ID, "storefront_id": "storefront_b01", "x": 100.0,
             "y": 250.0, "yaw_deg": 90.0, "kind": "projecting",
             "width_cm": 120.0, "height_cm": SIGN_HEIGHT_CM,
             "projection_cm": 120.0, "offset_along_cm": 60.0,
             "depth_cm": 135.0},
        ],
        "rooftop_props": [
            {"id": ROOF_ID, "building_id": "b01", "x": 1000.0, "y": 2000.0,
             "yaw_deg": 217.0, "kind": "vent", "width_cm": 120.0,
             "depth_cm": 90.0, "height_cm": ROOF_PROP_HEIGHT_CM},
        ],
        "parked_cars": [
            {"id": CAR_ID, "x": 1234.5, "y": -678.0, "yaw_deg": 45.0,
             "length_cm": 460.0, "width_cm": 190.0, "depth_cm": 460.0,
             "variant": "sedan", "edge_id": "way1"},
        ],
        "counts": {"storefronts": 1, "signs": 1, "rooftop_props": 1,
                   "parked_cars": 1, "conflict_pairs": 0},
        "conflicts": [],
    }


def _buildings() -> list:
    """What street_life_inputs.roof_polygons emits: id + polygon + height_cm."""
    return [{
        "id": "b01",
        "polygon": [{"x": 0.0, "y": 0.0}, {"x": 1000.0, "y": 0.0},
                    {"x": 1000.0, "y": 800.0}, {"x": 0.0, "y": 800.0}],
        "block_id": "blk",
        "height_cm": ROOF_HEIGHT_CM,
    }]


def _rows_by_kind(doc: dict) -> dict:
    out: dict = {}
    for row in doc["rows"]:
        out.setdefault(row["kind"], []).append(row)
    return out


def _one(doc: dict, kind: str) -> dict:
    rows = _rows_by_kind(doc).get(kind)
    assert rows and len(rows) == 1, (kind, rows)
    return rows[0]


def _expected_mesh(table: list, seed: int, source_id: str) -> str:
    """The module's documented pick, recomputed here to pin the algorithm."""
    h = hashlib.sha256()
    for part in (seed, source_id, "mesh"):
        h.update(str(part).encode("utf-8"))
        h.update(b"\x1f")
    return table[int.from_bytes(h.digest()[:8], "big") % len(table)]


# --- the documented contract ------------------------------------------------


def test_wrong_schema_version_raises():
    for bad in ({"schema_version": "street_life_v2"}, {"schema_version": None},
                {}, "not a document", None):
        with pytest.raises(ValueError):
            placement_rows(bad)
    for bad in ({"schema_version": "street_life_placement_v2"},
                {"schema_version": None}, {}, "not a document"):
        with pytest.raises(ValueError):
            validate_placement(bad)


def test_document_is_deterministic_and_json_serialisable():
    a = placement_rows(_source(), seed=7, buildings=_buildings(),
                       mesh_tables=FIXTURE_TABLES)
    b = placement_rows(_source(), seed=7, buildings=_buildings(),
                       mesh_tables=FIXTURE_TABLES)
    assert a == b
    assert json.loads(json.dumps(a)) == a
    assert a["schema_version"] == PLACEMENT_VERSION
    assert set(a) == {"schema_version", "rows", "counts", "skipped"}


def test_production_tables_hold_only_real_paths_the_module_cites():
    # the one table with a plausible real asset; the other three are honest gaps
    assert SIGN_MESHES == [
        "/Game/Prop/Kit_StopSign_A/Mesh/SM_StopSign_A",
        "/Game/Prop/Kit_StreetLamp_A/Mesh/SM_StreetLamp_A_OneWaySign",
        "/Game/Prop/Kit_StreetLamp_A/Mesh/SM_StreetLamp_A_WalkSignal_01",
        "/Game/Prop/Kit_StreetLamp_A/Mesh/SM_StreetLamp_A_WalkSignal_02",
    ]
    assert STOREFRONT_MESHES == []
    assert ROOFTOP_MESHES == []
    assert PARKED_VEHICLE_MESHES == []
    for path in SIGN_MESHES:
        assert path.startswith("/Game/Prop/")


def test_module_is_pure_stdlib_and_never_imports_unreal():
    src = (REPO_ROOT / "ldyf" / "street_life_placement.py").read_text("utf-8")
    assert "import unreal" not in src
    assert "import random" not in src
    assert "from random" not in src


# --- rows -------------------------------------------------------------------


def test_production_run_emits_signs_and_skips_the_empty_categories():
    doc = placement_rows(_source(), seed=3)
    kinds = _rows_by_kind(doc)
    assert list(kinds) == ["sign"]
    assert kinds["sign"][0]["mesh"] in SIGN_MESHES
    assert kinds["sign"][0]["source_id"] == SIGN_ID
    assert kinds["sign"][0]["id"] == "sign:" + SIGN_ID
    assert doc["counts"]["rows"] == 1
    assert doc["counts"]["skipped"] == 3
    codes = {s["kind"]: s["reason_code"] for s in doc["skipped"]}
    assert codes == {"storefront": "no_mesh_table",
                     "rooftop_prop": "no_mesh_table",
                     "parked_car": "no_mesh_table"}
    for entry in doc["skipped"]:
        assert entry["reason"].strip()
        assert "empty" in entry["reason"]
        assert entry["source_id"]


def test_every_row_mesh_is_in_a_table_and_matches_the_documented_pick():
    doc = placement_rows(_source(), seed=11, buildings=_buildings(),
                         mesh_tables=FIXTURE_TABLES)
    in_force = {FIXTURE_STOREFRONT, FIXTURE_ROOF, FIXTURE_CAR} | set(SIGN_MESHES)
    for row in doc["rows"]:
        assert row["mesh"] in in_force
    # signs still use the production table when only the gaps are overridden
    assert _one(doc, "sign")["mesh"] == _expected_mesh(SIGN_MESHES, 11, SIGN_ID)
    assert _one(doc, "storefront")["mesh"] == FIXTURE_STOREFRONT
    assert _one(doc, "parked_car")["mesh"] == FIXTURE_CAR


def test_row_shape_is_exactly_what_a_spawner_needs():
    doc = placement_rows(_source(), seed=5, buildings=_buildings(),
                         mesh_tables=FIXTURE_TABLES)
    assert len(doc["rows"]) == 4
    for row in doc["rows"]:
        assert set(row) == {"id", "kind", "mesh", "x", "y", "z_cm", "yaw_deg",
                            "scale", "source_id"}
        assert row["kind"] in KINDS
        assert row["id"] == "%s:%s" % (row["kind"], row["source_id"])
        for key in ("x", "y", "z_cm", "yaw_deg", "scale"):
            assert row[key] == round(row[key], 3)
        assert 0.0 <= row["yaw_deg"] < 360.0
        lo, hi = SCALE_BAND[row["kind"]]
        assert lo <= row["scale"] <= hi


def test_z_comes_from_the_right_source_for_each_kind():
    doc = placement_rows(_source(), seed=5, buildings=_buildings(),
                         mesh_tables=FIXTURE_TABLES)
    roof_row = _one(doc, "rooftop_prop")
    # the roof plane of building b01 -- not 0, and not the prop's own size
    assert roof_row["z_cm"] == ROOF_HEIGHT_CM
    assert roof_row["z_cm"] != 0.0
    assert roof_row["z_cm"] != ROOF_PROP_HEIGHT_CM
    assert _one(doc, "sign")["z_cm"] == SIGN_HEIGHT_CM      # mounted height
    assert _one(doc, "parked_car")["z_cm"] == 0.0           # road surface
    assert _one(doc, "storefront")["z_cm"] == 0.0           # footway, grade
    # x/y/yaw are the source item's, untouched
    car = _one(doc, "parked_car")
    assert (car["x"], car["y"], car["yaw_deg"]) == (1234.5, -678.0, 45.0)


def test_rooftop_without_a_roof_record_is_skipped_with_a_reason():
    doc = placement_rows(_source(), seed=5, mesh_tables=FIXTURE_TABLES)
    assert ROOF_ID not in [r["source_id"] for r in doc["rows"]]
    entry = [s for s in doc["skipped"] if s["source_id"] == ROOF_ID][0]
    assert entry["reason_code"] == "no_z_source"
    assert "b01" in entry["reason"]
    assert "height_cm" in entry["reason"]
    # the other three kinds are still placed: a missing roof record loses that
    # building's props, not the street
    assert sorted(_rows_by_kind(doc)) == ["parked_car", "sign", "storefront"]


def test_buildings_may_ride_on_the_source_document():
    source = _source()
    source["buildings"] = _buildings()
    doc = placement_rows(source, seed=5, mesh_tables=FIXTURE_TABLES)
    assert _one(doc, "rooftop_prop")["z_cm"] == ROOF_HEIGHT_CM


def test_rows_plus_skipped_account_for_every_source_item():
    source = _source()
    for kwargs in ({}, {"buildings": _buildings(),
                        "mesh_tables": FIXTURE_TABLES}):
        doc = placement_rows(source, seed=2, **kwargs)
        total = sum(len(source[SOURCE_LISTS[k]]) for k in KINDS)
        assert len(doc["rows"]) + len(doc["skipped"]) == total
        for kind in KINDS:
            rows = [r for r in doc["rows"] if r["kind"] == kind]
            skips = [s for s in doc["skipped"] if s["kind"] == kind]
            n_source = len(source[SOURCE_LISTS[kind]])
            assert len(rows) + len(skips) == n_source
            assert doc["counts"]["source_items"][kind] == n_source
        assert doc["counts"]["rows"] == len(doc["rows"])
        assert doc["counts"]["skipped"] == len(doc["skipped"])
        assert doc["counts"]["by_kind"] == {
            k: len(v) for k, v in _rows_by_kind(doc).items()}


def test_group_by_mesh_partitions_the_rows_exactly():
    doc = placement_rows(_source(), seed=5, buildings=_buildings(),
                         mesh_tables=FIXTURE_TABLES)
    buckets = group_by_mesh(doc["rows"])
    assert list(buckets) == sorted(buckets)
    flat = [row for mesh in buckets for row in buckets[mesh]]
    assert len(flat) == len(doc["rows"])
    assert sorted(r["id"] for r in flat) == sorted(r["id"] for r in doc["rows"])
    for mesh, rows in buckets.items():
        assert all(r["mesh"] == mesh for r in rows)
        assert [r["id"] for r in rows] == sorted(r["id"] for r in rows)
    assert sum(len(v) for v in buckets.values()) == doc["counts"]["rows"]
    assert group_by_mesh([]) == {}


# --- validate ---------------------------------------------------------------


def _good() -> tuple:
    source = _source()
    doc = placement_rows(source, seed=5, buildings=_buildings(),
                         mesh_tables=FIXTURE_TABLES)
    return doc, source


def test_validate_is_empty_on_a_good_document():
    doc, source = _good()
    assert validate_placement(doc, source, mesh_tables=FIXTURE_TABLES) == []
    # the production run too: signs placed, the three gaps skipped
    prod = placement_rows(_source(), seed=3)
    assert validate_placement(prod, _source()) == []
    # and with the source embedded in the document instead of passed in
    assert validate_placement(dict(prod, source=_source())) == []


def test_validate_says_so_when_it_cannot_check_the_source():
    prod = placement_rows(_source(), seed=3)
    problems = validate_placement(prod)
    assert problems and any("no source document" in p for p in problems)


def test_validate_catches_a_mesh_in_no_table():
    doc, source = _good()
    bad = copy.deepcopy(doc)
    bad["rows"][0]["mesh"] = "/Game/Fake/SM_NotInAnyTable"
    problems = validate_placement(bad, source, mesh_tables=FIXTURE_TABLES)
    assert any("is in no mesh table" in p for p in problems)


def test_validate_catches_negative_and_absurd_z():
    doc, source = _good()
    for value in (-25.0, Z_CEILING_CM + 1.0):
        bad = copy.deepcopy(doc)
        bad["rows"][0]["z_cm"] = value
        problems = validate_placement(bad, source, mesh_tables=FIXTURE_TABLES)
        assert any("z_cm" in p and "outside" in p for p in problems), problems


def test_validate_catches_a_scale_outside_the_stated_band():
    doc, source = _good()
    lo, hi = SCALE_BAND[doc["rows"][0]["kind"]]
    for value in (lo - 0.01, hi + 0.01, GLOBAL_SCALE_BAND[1] + 1.0):
        bad = copy.deepcopy(doc)
        bad["rows"][0]["scale"] = value
        problems = validate_placement(bad, source, mesh_tables=FIXTURE_TABLES)
        assert any("outside the stated band" in p for p in problems), problems


def test_validate_catches_a_duplicate_row_id():
    doc, source = _good()
    bad = copy.deepcopy(doc)
    bad["rows"].append(dict(bad["rows"][0]))
    problems = validate_placement(bad, source, mesh_tables=FIXTURE_TABLES)
    assert any("duplicate row id" in p for p in problems)


def test_validate_catches_a_source_id_that_names_nothing():
    doc, source = _good()
    bad = copy.deepcopy(doc)
    bad["rows"][0]["source_id"] = "sign_does_not_exist"
    problems = validate_placement(bad, source, mesh_tables=FIXTURE_TABLES)
    assert any("names no item" in p for p in problems)


def test_validate_catches_a_count_mismatch():
    doc, source = _good()
    bad = copy.deepcopy(doc)
    bad["rows"].pop(0)
    problems = validate_placement(bad, source, mesh_tables=FIXTURE_TABLES)
    assert any("count mismatch" in p for p in problems)


def test_validate_catches_an_unreasoned_skip():
    source = _source()
    doc = placement_rows(source, seed=3)   # production: three skips
    assert doc["skipped"]
    bad = copy.deepcopy(doc)
    bad["skipped"][0].pop("reason")
    problems = validate_placement(bad, source)
    assert any("has no reason" in p for p in problems)
