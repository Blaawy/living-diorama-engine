"""Phase-2 closure lane B: ``ldyf.building_kits`` -- building material kits.

Ground truth for material paths is ``asset_probe_v3.json`` at the repo
root; every path this suite checks against is read from that file (the
module mirrors it in ``PROBE_BUILDING_MATERIALS``).  All layouts below are
hand-built city_layout-shaped dicts (blocks + building_slots), so no SUMO
or network fixtures are needed.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ldyf.building_kits import (
    CIVIC_FAMILY,
    FACADE_FAMILIES,
    HEIGHT_BAND_CORE,
    HEIGHT_BAND_EDGE,
    LANDMARK_MIN_HEIGHT_CM,
    ROOF_MASTER,
    WINDOW_MASTER,
    assign_family,
    build_kits,
    ground_floor_spec,
    landmark_spec,
    massing_variation,
    roof_spec,
    validate_kits,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "asset_probe_v3.json"


def probe_material_set() -> set[str]:
    with PROBE_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return set(data["building_materials"])


def make_layout(*, seed: int = 7, slots_per_block: int = 4) -> dict:
    """Nine-block grid centred on (0, 0): centre block = core (downtown),
    edge blocks = edge, diagonals = mid.  Blocks carry ``centre`` and slots
    shaped like ``city_layout.building_slots`` output."""
    step = 4000.0
    blocks = []
    all_slots = []
    for i in range(3):
        for j in range(3):
            bx = -step + i * step
            by = -step + j * step
            bid = f"block_{i}_{j}"
            blocks.append({
                "id": bid,
                "centre": {"x": bx, "y": by},
                "bbox": {"x_min": bx - 1500.0, "x_max": bx + 1500.0,
                         "y_min": by - 1500.0, "y_max": by + 1500.0},
                "polygon": [],
                "area_cm2": 9_000_000.0,
            })
            for f in range(slots_per_block):
                yaw = float(f * 90)
                all_slots.append({
                    "slot_id": f"{bid}:f{f}",
                    "block_id": bid,
                    "kit": "A",
                    "x": bx, "y": by, "yaw": yaw,
                    "width_cm": 1800.0 + (f % 2) * 300.0,
                    "depth_cm": 1200.0 + (f % 2) * 200.0,
                    "frontage_index": f,
                })
    return {
        "schema_version": "city_layout_v1",
        "seed": seed,
        "blocks": blocks,
        "building_slots": {
            "schema_version": "city_layout_v1",
            "seed": seed,
            "kits": ["A"],
            "counts": {"blocks": len(blocks), "slots": len(all_slots)},
            "slots": all_slots,
        },
    }


# --- determinism ------------------------------------------------------------


def test_kit_document_is_deterministic():
    doc1 = build_kits(make_layout(seed=11))
    doc2 = build_kits(make_layout(seed=11))
    assert doc1 == doc2


def test_family_assignment_is_stable():
    assert assign_family("block_1_1", "block_1_1:f2") == \
        assign_family("block_1_1", "block_1_1:f2")
    assert assign_family("block_1_1", "block_1_1:f2") in FACADE_FAMILIES


def test_massing_variation_deterministic():
    b = {"building_id": "block_1_1:f1", "width_cm": 1800.0,
         "depth_cm": 1400.0, "height_band": [1600.0, 2600.0]}
    assert massing_variation(b, seed=3) == massing_variation(b, seed=3)


# --- neighbours never share a family ---------------------------------------


def test_consecutive_frontages_never_share_family():
    block_id = "block_0_0"
    fams = [assign_family(block_id, f"{block_id}:f{i}") for i in range(24)]
    for a, b in zip(fams, fams[1:]):
        assert a != b, f"adjacent frontages share family {a}"


def test_assign_family_differs_between_blocks():
    got = {assign_family(f"block_{i}_{j}", f"block_{i}_{j}:f0")
           for i in range(3) for j in range(3)}
    assert len(got) > 1  # not every block starts on the same family


# --- material paths come from the probe file -------------------------------


def test_every_emitted_material_is_in_probe_file():
    probe = probe_material_set()
    doc = build_kits(make_layout(seed=5))
    for b in doc["buildings"]:
        assert b["wall_material"] in probe
        assert b["window_material"] in probe
        assert b["ground_floor"]["material"] in probe
        assert b["roof"]["material"] in probe
    for part in doc["landmark"]["parts"]:
        assert part["material"] in probe
    for fam in doc["families_used"].values():
        for member in fam["members"]:
            assert member in probe
    for members in FACADE_FAMILIES.values():
        for member in members:
            assert member in probe
    assert ROOF_MASTER in probe and WINDOW_MASTER in probe


def test_facade_families_are_real_probe_paths():
    probe = probe_material_set()
    flat = {m for members in FACADE_FAMILIES.values() for m in members}
    assert flat <= probe


# --- heights ----------------------------------------------------------------


def test_heights_vary_and_stay_in_band():
    b = {"building_id": "block_1_1:f1", "width_cm": 1800.0,
         "depth_cm": 1400.0, "height_band": [1600.0, 2600.0]}
    heights = [massing_variation(b, seed=s)["height_cm"] for s in range(50)]
    assert len(set(heights)) > 1
    assert all(1600.0 <= h <= 2600.0 for h in heights)


def test_band_differs_by_block_downtown_taller():
    doc = build_kits(make_layout(seed=5))
    by_block: dict[str, list[float]] = {}
    for b in doc["buildings"]:
        by_block.setdefault(b["block_id"], []).append(b["height_cm"])
    core = by_block["block_1_1"]           # centre block: core band
    corner = by_block["block_0_0"]         # corner block: edge band
    assert max(core) <= HEIGHT_BAND_CORE[1]
    assert min(core) >= HEIGHT_BAND_CORE[0]
    assert max(corner) <= HEIGHT_BAND_EDGE[1]
    assert min(core) > max(corner)  # downtown strictly taller than edges


def test_massing_band_recorded_on_document():
    doc = build_kits(make_layout(seed=5))
    for b in doc["buildings"]:
        lo, hi = b["height_band_cm"]
        assert lo <= b["massing"]["height_cm"] <= hi


# --- setback -----------------------------------------------------------------


def test_setback_never_exceeds_footprint():
    for w in (900.0, 1800.0, 2400.0):
        for d in (800.0, 1200.0, 2000.0):
            b = {"building_id": "block_0_0:f1", "width_cm": w,
                 "depth_cm": d, "height_band": [2300.0, 3600.0]}
            for s in range(40):
                m = massing_variation(b, seed=s)
                assert 2.0 * m["setback_cm"] <= w
                assert m["setback_cm"] <= d
                if m["setback_cm"] > 0.0:
                    assert 0.0 < m["setback_start_cm"] < m["height_cm"]


# --- ground floor / roof ------------------------------------------------------


def test_ground_floor_entrances_face_a_footway_frontage():
    b = {"building_id": "block_0_0:f2", "width_cm": 2000.0,
         "depth_cm": 1400.0, "yaw": 180.0}
    gf = ground_floor_spec(b)
    assert gf["frontage_faces_footway"] is True
    assert 1 <= gf["entrance_count"] <= 3
    assert gf["height_cm"] > 0.0


def test_roof_uses_roof_material_and_keeps_middle_clear():
    b = {"building_id": "block_0_0:f3", "width_cm": 2400.0,
         "depth_cm": 1600.0,
         "massing": {"has_parapet": True}}
    rs = roof_spec(b)
    probe = probe_material_set()
    assert rs["material"] in probe
    if rs["has_plant_room"]:
        fp = rs["plant_room_footprint"]
        # rear-left corner: offsets leave the middle and the front clear
        assert fp["corner"] == "rear_left"
        assert fp["offset_lateral_cm"] > 0.0
        assert fp["offset_depth_cm"] > 0.0
        assert 2.0 * fp["offset_lateral_cm"] + fp["width_cm"] \
            <= 2400.0 + 1e-6
        assert 2.0 * fp["offset_depth_cm"] + fp["depth_cm"] \
            <= 1600.0 + 1e-6


# --- landmark -----------------------------------------------------------------


def test_exactly_one_distinguishable_landmark():
    doc = build_kits(make_layout(seed=5))
    assert doc["counts"]["landmark"] == 1
    lm = doc["landmark"]
    assert lm["family"] == CIVIC_FAMILY
    assert lm["height_cm"] >= LANDMARK_MIN_HEIGHT_CM
    assert len(lm["parts"]) >= 5
    assert {p["kind"] for p in lm["parts"]} >= {"box", "cylinder"}
    for b in doc["buildings"]:
        assert b["family"] != CIVIC_FAMILY  # ordinary buildings never civic
        assert b["height_cm"] < lm["height_cm"]  # landmark is the tallest
    # landmark block is downtown (the centre block of the fixture)
    assert lm["block_id"] == "block_1_1"


def test_landmark_spec_deterministic():
    l1 = landmark_spec(make_layout(seed=3))
    l2 = landmark_spec(make_layout(seed=3))
    assert l1 == l2
    assert l1["footprint_cm"]["height_cm"] >= LANDMARK_MIN_HEIGHT_CM


# --- validation ---------------------------------------------------------------


def _valid_doc():
    return copy.deepcopy(build_kits(make_layout(seed=5)))


def test_validate_accepts_generated_document():
    assert validate_kits(_valid_doc()) == []


def test_validate_catches_material_not_in_probe():
    doc = _valid_doc()
    doc["buildings"][0]["wall_material"] = "/Game/Fake/M_NotReal"
    problems = validate_kits(doc)
    assert any("not in probe list" in p for p in problems)


def test_validate_catches_height_outside_band():
    doc = _valid_doc()
    doc["buildings"][0]["massing"]["height_cm"] = 99999.0
    problems = validate_kits(doc)
    assert any("outside stated band" in p for p in problems)


def test_validate_catches_setback_wider_than_building():
    doc = _valid_doc()
    b = doc["buildings"][0]
    b["width_cm"] = 1000.0
    b["massing"]["setback_cm"] = 600.0
    problems = validate_kits(doc)
    assert any("wider than building" in p for p in problems)


def test_validate_catches_entrance_without_footway():
    doc = _valid_doc()
    doc["buildings"][0]["ground_floor"]["frontage_faces_footway"] = False
    problems = validate_kits(doc)
    assert any("no footway" in p for p in problems)


def test_validate_catches_missing_landmark():
    doc = _valid_doc()
    del doc["landmark"]
    assert any("exactly one landmark" in p for p in validate_kits(doc))
    doc = _valid_doc()
    doc["landmark"] = {"parts": []}
    assert any("exactly one landmark" in p for p in validate_kits(doc))


# --- ValueError paths -----------------------------------------------------------


def test_non_positive_dimensions_raise_value_error():
    bad = {"building_id": "block_0_0:f0", "width_cm": 0.0,
           "depth_cm": 1200.0, "height_band": [1600.0, 2600.0]}
    with pytest.raises(ValueError):
        massing_variation(bad, seed=1)
    with pytest.raises(ValueError):
        ground_floor_spec({"building_id": "x", "width_cm": 100.0,
                           "depth_cm": -5.0})
    with pytest.raises(ValueError):
        roof_spec({"building_id": "x", "width_cm": 0.0, "depth_cm": 5.0})


def test_massing_rejects_invalid_band():
    b = {"building_id": "x", "width_cm": 100.0, "depth_cm": 100.0,
         "height_band": [-5.0, 100.0]}
    with pytest.raises(ValueError):
        massing_variation(b, seed=1)
    b = {"building_id": "x", "width_cm": 100.0, "depth_cm": 100.0,
         "height_band": [900.0, 400.0]}
    with pytest.raises(ValueError):
        massing_variation(b, seed=1)


def test_build_kits_rejects_layout_without_slots():
    with pytest.raises(ValueError):
        build_kits({"blocks": [], "building_slots": {"slots": []}})


def test_landmark_spec_rejects_empty_layout():
    with pytest.raises(ValueError):
        landmark_spec({"blocks": [], "building_slots": {"slots": []}})
