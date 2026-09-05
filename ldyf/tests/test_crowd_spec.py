"""Tests for the crowd appearance data spec (``crowd_spec_v1``).

The module exists because 65 City Sample humans rendered as dark silhouettes at
street distance (skin material failed to compile -> fallback error shading).
These tests guard the properties that make that regression impossible again:
tones bright enough in linear space, real spread across the tables, and a
validator that refuses any plan which would collapse back onto a silhouette.
"""

from __future__ import annotations

import pytest

from ldyf.crowd_spec import (
    GARMENT_PALETTE,
    MIN_DISTINCT_GARMENT_COLOURS,
    MIN_DISTINCT_SKIN_TONES,
    SKIN_LUMINANCE_FLOOR,
    SKIN_TONES,
    _luminance,
    crowd_plan,
    material_parameters,
    validate_crowd,
    variant_for,
)

CROWD_SIZE = 65
UIDS = [f"citizen_{i:04d}" for i in range(CROWD_SIZE)]


def _good_plan(uids=None):
    return crowd_plan(uids if uids is not None else UIDS)


def _all_channels(plan):
    for person in plan["persons"]:
        for field in ("skin_rgb", "hair_rgb", "shirt_rgb", "trousers_rgb", "shoes_rgb"):
            for channel in person[field]:
                yield channel


def test_determinism_same_uid_twice():
    a = variant_for("citizen_0001")
    b = variant_for("citizen_0001")
    assert a == b


def test_determinism_plan_identical():
    assert crowd_plan(UIDS) == crowd_plan(UIDS)


def test_65_uids_hit_minimum_distinct_skin_tones():
    plan = _good_plan()
    tones = {p["skin_tone"] for p in plan["persons"]}
    assert len(tones) >= MIN_DISTINCT_SKIN_TONES
    # the defect was "two visual variants" -- assert the real spread, not the floor
    assert len(tones) >= 6


def test_65_uids_hit_minimum_distinct_garment_colours():
    plan = _good_plan()
    colours = set()
    for p in plan["persons"]:
        colours.update(tuple(p[f]) for f in ("shirt_rgb", "trousers_rgb", "shoes_rgb"))
    assert len(colours) >= MIN_DISTINCT_GARMENT_COLOURS


def test_every_channel_in_unit_range():
    plan = _good_plan()
    for c in _all_channels(plan):
        assert 0.0 <= c <= 1.0
    for rgb in GARMENT_PALETTE.values():
        for c in rgb:
            assert 0.0 <= c <= 1.0
    for entry in SKIN_TONES.values():
        for c in entry["rgb"]:
            assert 0.0 <= c <= 1.0


def test_every_table_skin_luminance_above_floor():
    for name, entry in SKIN_TONES.items():
        assert _luminance(entry["rgb"]) >= SKIN_LUMINANCE_FLOOR, name


def test_every_plan_skin_luminance_above_floor():
    for p in _good_plan()["persons"]:
        assert _luminance(p["skin_rgb"]) >= SKIN_LUMINANCE_FLOOR, p["uid"]


def test_validate_accepts_good_plan():
    assert validate_crowd(_good_plan()) == []


def test_validate_rejects_channel_out_of_range():
    plan = _good_plan()
    plan["persons"][0]["shirt_rgb"] = [1.5, 0.0, 0.0]
    problems = validate_crowd(plan)
    assert any("outside [0, 1]" in p for p in problems)


def test_validate_rejects_skin_below_luminance_floor():
    plan = _good_plan()
    plan["persons"][0]["skin_rgb"] = [0.01, 0.01, 0.01]
    problems = validate_crowd(plan)
    assert any("below floor" in p for p in problems)


def test_validate_rejects_too_few_distinct_skin_tones():
    plan = _good_plan()
    for p in plan["persons"]:
        p["skin_tone"] = "pale"
        p["skin_rgb"] = list(SKIN_TONES["pale"]["rgb"])
    problems = validate_crowd(plan)
    assert any("distinct skin tones" in p for p in problems)


def test_validate_rejects_too_few_distinct_garment_colours():
    plan = _good_plan()
    grey = list(GARMENT_PALETTE["light_grey"])
    for p in plan["persons"]:
        p["shirt_rgb"] = list(grey)
        p["trousers_rgb"] = list(grey)
        p["shoes_rgb"] = list(grey)
    problems = validate_crowd(plan)
    assert any("distinct garment colours" in p for p in problems)


def test_validate_rejects_duplicated_uid_in_persons():
    plan = _good_plan()
    plan["persons"].append(dict(plan["persons"][0]))
    problems = validate_crowd(plan)
    assert any("duplicated uid" in p for p in problems)


def test_crowd_plan_rejects_empty_uid_list():
    with pytest.raises(ValueError):
        crowd_plan([])


def test_crowd_plan_rejects_duplicate_uids():
    with pytest.raises(ValueError):
        crowd_plan(["a", "a"])


def test_crowd_plan_persons_sorted_by_uid():
    plan = _good_plan(["zeta", "alpha", "beta"])
    assert [p["uid"] for p in plan["persons"]] == sorted(["zeta", "alpha", "beta"])


def test_variant_schema_keys():
    v = variant_for("citizen_0001")
    assert set(v) == {
        "uid", "skin_tone", "skin_rgb", "hair_rgb", "shirt_rgb",
        "trousers_rgb", "shoes_rgb", "roughness", "subsurface",
    }
    assert v["uid"] == "citizen_0001"


def test_distribution_counts_match_persons():
    plan = _good_plan()
    total = len(plan["persons"])
    assert sum(plan["distribution"]["skin_tones"].values()) == total
    # every garment field is counted exactly once per person
    assert sum(plan["distribution"]["garment_colours"].values()) == 3 * total


def test_trousers_never_same_colour_as_shirt():
    for p in _good_plan()["persons"]:
        assert tuple(p["shirt_rgb"]) != tuple(p["trousers_rgb"])


def test_material_parameters_marks_candidates_from_probe():
    params = material_parameters(variant_for("citizen_0001"))
    assert params["schema_version"] == "crowd_spec_v1"
    # candidate assets are real paths quoted from asset_probe_v3.json
    assert params["shirt"]["material_candidates"] == [
        "/Game/Character/Player/Female/Materials/MI_Player_Shirt",
        "/Game/Character/Player/Male/Materials/MI_Shirt_Player",
        "/Game/Character/Player/Female/Materials/MI_Player_Jacket",
    ]
    for slot in ("skin", "hair", "shirt", "trousers", "shoes"):
        for name, value in params[slot]["parameters"].items():
            if isinstance(value, list):
                for c in value:
                    assert 0.0 <= c <= 1.0
            else:
                assert isinstance(value, float)
