"""``ldyf.building_styles`` -- every claim checked against the probe files.

Ground truth is ``pcg_building_rules.json`` (27 style families and the levels
their shape-grammar rules cover) and ``pcg_building_kits.json`` (real rule and
shape asset paths); both are re-read here rather than trusted from the module,
so the module's mirror cannot drift quietly.  No test imports ``unreal``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ldyf.building_styles import (
    CIVIC_FAMILY,
    ENUMERATED_RULE_COUNT,
    FAMILY_GROUP_REASONS,
    FAMILY_GROUPS,
    LANDMARK_LEVEL_FLOOR,
    LANDMARK_MIN_HEIGHT_CM,
    LANDMARK_SLICE,
    LANDMARK_STYLE,
    MIRRORED_STYLE_COUNT,
    MIRRORED_STYLE_FAMILIES,
    ORDINARY_FAMILIES,
    ORDINARY_MAX_LEVEL,
    RULE_ASSET_RE,
    SCHEMA_VERSION,
    STYLE_FAMILIES,
    assign_landmark,
    assign_style,
    probe_style_levels,
    read_probe_rules,
    rule_asset_path,
    validate_styles,
)
from ldyf.building_styles import _resolve_level, _target_level

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = REPO_ROOT / "pcg_building_rules.json"
KITS_PATH = REPO_ROOT / "pcg_building_kits.json"

OUR_SIX = ("brick", "concrete", "granite_dark", "granite_light", "limestone",
           "painted_stone")


def probe_rules() -> dict:
    with RULES_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def probe_kits() -> dict:
    with KITS_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def probe_styles() -> dict[str, list[int]]:
    return {s: list(e["levels"]) for s, e in probe_rules()["styles"].items()}


# --- 1. the mirror ---------------------------------------------------------


def test_schema_version():
    assert SCHEMA_VERSION == "building_styles_v1"


def test_probe_file_is_present_and_readable():
    assert RULES_PATH.is_file()
    probe = read_probe_rules()
    assert probe is not None
    assert probe["style_count"] == 27
    assert len(probe["styles"]) == 27


def test_mirror_equals_probe_levels():
    live = probe_styles()
    assert set(live) == set(MIRRORED_STYLE_FAMILIES)
    for style, levels in live.items():
        assert list(MIRRORED_STYLE_FAMILIES[style]) == levels, style
    assert STYLE_FAMILIES == MIRRORED_STYLE_FAMILIES
    assert MIRRORED_STYLE_COUNT == len(live) == len(STYLE_FAMILIES)


def test_mirror_counts_match_the_probe_count_fields():
    probe = probe_rules()
    total = 0
    for style, entry in probe["styles"].items():
        assert entry["count"] == len(entry["levels"]), style
        assert len(STYLE_FAMILIES[style]) == entry["count"], style
        total += entry["count"]
    assert probe_style_levels(probe) == STYLE_FAMILIES
    assert total == ENUMERATED_RULE_COUNT == 240
    assert probe["style_count"] == len(probe["styles"]) == 27


def test_the_probes_own_total_does_not_reconcile_and_is_not_guarded_on():
    """The probe says ``total`` 270; its 27 ``count`` fields sum to 240.

    Counting the ``levels`` lists by hand gives 240 as well, so ``total`` is
    not the number of enumerated rules.  The module guards on ``style_count``
    and the level lists instead (see its docstring); if a later probe
    reconciles these two numbers, this test fails on purpose and the caveat
    should be deleted.
    """
    probe = probe_rules()
    enumerated = [len(e["levels"]) for e in probe["styles"].values()]
    assert sum(enumerated) == 240 == ENUMERATED_RULE_COUNT
    assert probe["total"] == 270
    assert 240 != 270


# --- 2. mapping ------------------------------------------------------------


def test_every_target_family_exists_in_the_probe():
    live = set(probe_styles())
    for family, targets in FAMILY_GROUPS.items():
        assert targets, family
        for target in targets:
            assert target in live, (family, target)


def test_our_families_are_all_mapped_and_documented():
    assert set(FAMILY_GROUPS) == set(OUR_SIX) | {CIVIC_FAMILY}
    for family in FAMILY_GROUPS:
        assert len(FAMILY_GROUP_REASONS.get(family, "").strip()) > 40, family
    assert CIVIC_FAMILY == "civic_stone"
    assert CIVIC_FAMILY not in ORDINARY_FAMILIES
    assert set(ORDINARY_FAMILIES) == set(OUR_SIX)


def test_ordinary_families_never_reach_the_landmark_levels():
    reachable = {
        max(STYLE_FAMILIES[target])
        for family in ORDINARY_FAMILIES
        for target in FAMILY_GROUPS[family]
    }
    assert max(reachable) == ORDINARY_MAX_LEVEL == 17
    assert min(LANDMARK_SLICE) == LANDMARK_LEVEL_FLOOR
    assert LANDMARK_LEVEL_FLOOR > ORDINARY_MAX_LEVEL
    assert set(LANDMARK_SLICE) <= set(STYLE_FAMILIES[LANDMARK_STYLE])


# --- 3. rule asset paths ---------------------------------------------------


def test_rule_path_matches_the_probes_own_example():
    assert rule_asset_path("CHA", 0) == probe_rules()["rule_example"]
    assert rule_asset_path("CHA", 0).endswith("CHA/RULE_CHA_L00")
    assert rule_asset_path("CHA", 20).endswith("CHA/RULE_CHA_L20")


def test_every_style_and_level_has_a_pattern_matching_path():
    pattern = re.compile(RULE_ASSET_RE)
    for style, levels in probe_styles().items():
        for level in levels:
            path = rule_asset_path(style, level)
            assert pattern.match(path), path
            assert path == (f"/CitySamplePCG/PCG/DataAssets/Buildings/{style}"
                            f"/RULE_{style}_L{level:02d}")


def test_rule_path_table_has_one_entry_per_enumerated_level():
    paths = {rule_asset_path(style, level)
             for style, levels in probe_styles().items() for level in levels}
    assert len(paths) == ENUMERATED_RULE_COUNT == 240


def test_rule_paths_agree_with_the_real_rule_assets_in_the_kit_probe():
    """The kit probe lists real RULE_* assets; our generated names must match."""
    assets = [a for a in probe_kits()["building_data_assets"]
              if "/Buildings/CHA/RULE_" in a]
    assert assets == [rule_asset_path("CHA", lv)
                      for lv in probe_styles()["CHA"]]
    for style in ("CHB", "CHC"):
        listed = {a for a in probe_kits()["building_data_assets"]
                  if f"/Buildings/{style}/RULE_" in a}
        assert listed
        assert listed <= {rule_asset_path(style, lv)
                          for lv in probe_styles()[style]}


# --- 4. assign_style -------------------------------------------------------


def test_emitted_style_and_level_are_real_for_every_family():
    live = probe_styles()
    for family in FAMILY_GROUPS:
        for i in range(40):
            for height in (150.0, 900.0, 3000.0, 9000.0, 45000.0):
                a = assign_style(f"block_1_1:f{i}", family, height, seed=11)
                assert a["style"] in live
                assert a["level"] in live[a["style"]]
                assert a["levels_available"] == live[a["style"]]
                assert a["style"] in FAMILY_GROUPS[family]
                assert a["rule_asset"] == rule_asset_path(a["style"],
                                                          a["level"])
                assert a["family"] == family
                assert a["height_cm"] == pytest.approx(float(height), abs=1e-3)
                assert validate_styles([a]) == []


def test_deterministic_same_inputs_same_result():
    a = assign_style("block_2_4:f3", "limestone", 2450.0, seed=99)
    b = assign_style("block_2_4:f3", "limestone", 2450.0, seed=99)
    assert a == b
    assert assign_landmark("civic_1", seed=3) == assign_landmark("civic_1",
                                                                 seed=3)


def test_seed_and_id_change_the_pick():
    picks = {assign_style(f"b{i}", "brick", 1200.0, seed=1)["style"]
             for i in range(40)}
    assert len(picks) > 1
    seeds = {assign_style("b0", "brick", 1200.0, seed=s)["style"]
             for s in range(40)}
    assert len(seeds) > 1


def test_neighbouring_ids_do_not_all_collapse_to_one_style():
    for family in ORDINARY_FAMILIES:
        for start in range(0, 40, 10):
            window = {assign_style(f"row_{start + i}", family, 1500.0,
                                   seed=7)["style"]
                      for i in range(10)}
            assert len(window) >= 2, (family, start, window)


def test_heights_map_monotonically_to_levels():
    heights = list(range(1, 12001, 137))
    for family in ORDINARY_FAMILIES:
        levels = [assign_style("mono_1", family, h, seed=5)["level"]
                  for h in heights]
        assert levels == sorted(levels), family
        assert levels[0] == 0


def test_short_and_tall_heights_clamp_and_report_it():
    live = probe_styles()
    for family in ORDINARY_FAMILIES:
        for i in range(30):
            # 60 cm is below one 300 cm storey: level 0, every family's floor.
            low = assign_style(f"c{i}", family, 60.0, seed=2)
            assert low["level"] == min(live[low["style"]]) == 0
            assert low["clamp"] is None
            assert low["requested_level"] == 0
            high = assign_style(f"c{i}", family, 90000.0, seed=2)
            assert high["level"] == max(live[high["style"]])
            assert high["clamp"] == "high"
            assert high["level_height_cm"] == high["level"] * 300.0


def test_below_range_is_reported_as_low():
    """Only reachable with a negative requested level: positives start at 0."""
    for style in probe_styles():
        assert _resolve_level(style, -4) == (min(STYLE_FAMILIES[style]), "low")


def test_storey_maths_is_300cm_per_level():
    assert _target_level(300.0) == 1
    assert _target_level(150.0) == 1        # rounds up
    assert _target_level(1449.0) == 5
    assert _target_level(60.0) == 0


def test_interior_gaps_snap_and_are_reported():
    # NYG / NYGA skip levels 15-16; NYH skips 6-7 (read from the probe).
    live = probe_styles()
    assert 15 not in live["NYG"] and 16 not in live["NYG"]
    assert 6 not in live["NYH"] and 7 not in live["NYH"]
    assert _resolve_level("NYG", 16) == (17, "gap")
    assert _resolve_level("NYH", 7) == (8, "gap")
    assert _resolve_level("NYG", 14) == (14, None)
    assert _resolve_level("SFA", 9) == (9, None)


def test_a_real_assignment_can_report_a_gap():
    live = probe_styles()
    clamps: dict = {}
    for i in range(400):
        a = assign_style(f"gap_{i}", "limestone", 4800.0, seed=3)  # level 16
        assert a["level"] in live[a["style"]]
        clamps.setdefault(a["clamp"], set()).add(a["style"])
    assert clamps["gap"]
    assert clamps["gap"] <= {"NYG", "NYGA"}


def test_hand_check_three_heights_through_limestone():
    """Three heights walked by hand against the probe's level lists.

    ``limestone`` -> NYAD(0-5) NYAE(0-6) NYAF(0-7) NYG(0-14,17) NYGA(same)
    NYH(0-5,8-12).  ``target`` is floor(height/300 + 0.5), so 150 cm -> 1,
    4800 cm -> 16, 45000 cm -> 150.  Expected (level, clamp) per style is read
    off those lists by hand; the style itself is the digest's business and all
    six candidates are exercised below.
    """
    expected = {
        150.0: {"NYAD": (1, None), "NYAE": (1, None), "NYAF": (1, None),
                "NYG": (1, None), "NYGA": (1, None), "NYH": (1, None)},
        4800.0: {"NYAD": (5, "high"), "NYAE": (6, "high"), "NYAF": (7, "high"),
                 "NYG": (17, "gap"), "NYGA": (17, "gap"), "NYH": (12, "high")},
        45000.0: {"NYAD": (5, "high"), "NYAE": (6, "high"),
                  "NYAF": (7, "high"), "NYG": (17, "high"),
                  "NYGA": (17, "high"), "NYH": (12, "high")},
    }
    seen = set()
    for i in range(200):
        bid = f"hand_{i}"
        for height, per_style in expected.items():
            a = assign_style(bid, "limestone", height, seed=1)
            seen.add(a["style"])
            assert (a["level"], a["clamp"]) == per_style[a["style"]]
            assert a["rule_asset"] == rule_asset_path(a["style"], a["level"])
    assert seen == set(expected[150.0])


# --- 5. the landmark -------------------------------------------------------


def test_landmark_is_the_deepest_grammar_and_near_its_top():
    assert LANDMARK_STYLE == "CHA"
    assert FAMILY_GROUPS[CIVIC_FAMILY] == (LANDMARK_STYLE,)
    assert len(probe_styles()["CHA"]) == max(len(v)
                                             for v in probe_styles().values())
    for i in range(40):
        lm = assign_landmark(f"civic_{i}", seed=17)
        assert lm["style"] == LANDMARK_STYLE
        assert lm["level"] in probe_styles()[LANDMARK_STYLE]
        assert lm["level"] in LANDMARK_SLICE
        assert lm["level"] >= LANDMARK_LEVEL_FLOOR
        assert lm["family"] == CIVIC_FAMILY
        assert lm["is_landmark"] is True
        assert lm["height_cm"] == lm["level"] * 300.0
        assert lm["height_cm"] >= LANDMARK_MIN_HEIGHT_CM
        assert validate_styles([lm]) == []


def test_landmark_is_taller_than_every_ordinary_building_in_its_set():
    ordinary = []
    for family in ORDINARY_FAMILIES:
        for i in range(20):
            for height in (400.0, 2500.0, 6000.0, 60000.0):
                ordinary.append(assign_style(f"blk_{family}_{i}", family,
                                             height, seed=i))
    top = max(a["level"] for a in ordinary)
    assert top == ORDINARY_MAX_LEVEL == 17
    for i in range(10):
        lm = assign_landmark(f"civic_{i}", seed=4)
        assert lm["level"] > top
        assert validate_styles(ordinary + [lm]) == []


def test_landmark_min_height_mirrors_building_kits():
    from ldyf import building_kits

    assert LANDMARK_MIN_HEIGHT_CM == building_kits.LANDMARK_MIN_HEIGHT_CM
    assert building_kits.CIVIC_FAMILY == CIVIC_FAMILY
    assert CIVIC_FAMILY not in building_kits.FACADE_FAMILIES


def test_landmark_style_is_unreachable_by_an_ordinary_family():
    for family in ORDINARY_FAMILIES:
        assert LANDMARK_STYLE not in FAMILY_GROUPS[family]
        for i in range(20):
            assert assign_style(f"x{i}", family, 20000.0,
                                seed=i)["style"] != LANDMARK_STYLE


# --- 6. validate_styles ----------------------------------------------------


def make_set(n: int = 12) -> dict:
    out = {f"b{i}": assign_style(f"b{i}", OUR_SIX[i % len(OUR_SIX)],
                                 900.0 * ((i % 5) + 1), seed=3)
           for i in range(n)}
    out["civic_1"] = assign_landmark("civic_1", seed=3)
    return out


def test_validate_accepts_a_good_set():
    assert validate_styles(make_set()) == []


def test_validate_flags_a_style_not_in_the_probe():
    s = make_set()
    s["b0"]["style"] = "ZZZ"
    problems = validate_styles(s)
    assert any("ZZZ" in p and "not one of the" in p for p in problems)


def test_validate_flags_a_level_the_style_has_no_rule_for():
    s = make_set()
    victim = next(a for a in s.values() if not a.get("is_landmark"))
    assert 99 not in victim["levels_available"]
    victim["level"] = 99
    problems = validate_styles(s)
    assert any("has no rule for level 99" in p for p in problems)


def test_validate_flags_a_path_that_is_not_the_documented_one():
    s = make_set()
    victim = next(a for a in s.values() if not a.get("is_landmark"))
    good = victim["rule_asset"]
    victim["rule_asset"] = good.replace("RULE_", "Rule_")
    assert any("does not match" in p for p in validate_styles(s))
    victim["rule_asset"] = good.rsplit("_L", 1)[0] + "_L99"
    assert any("not the documented path" in p for p in validate_styles(s))


def test_validate_flags_a_family_of_ours_with_no_mapping():
    s = make_set()
    s["b1"]["family"] = "sandstone"
    assert any("sandstone" in p and "FAMILY_GROUPS" in p
               for p in validate_styles(s))


def test_validate_flags_a_style_outside_the_family_group():
    s = make_set()
    s["b2"]["style"] = LANDMARK_STYLE
    s["b2"]["level"] = 1
    s["b2"]["rule_asset"] = rule_asset_path(LANDMARK_STYLE, 1)
    s["b2"]["levels_available"] = probe_styles()[LANDMARK_STYLE]
    assert any("not an acceptable target" in p for p in validate_styles(s))


def test_validate_flags_a_landmark_that_is_not_the_tallest():
    s = make_set()
    s["civic_1"]["level"] = 3
    s["civic_1"]["rule_asset"] = rule_asset_path(LANDMARK_STYLE, 3)
    assert any("landmark is not taller" in p for p in validate_styles(s))

    s2 = make_set()
    s2["civic_1"]["level"] = max(a["level"] for k, a in s2.items()
                                 if not a.get("is_landmark"))
    assert any("landmark is not taller" in p for p in validate_styles(s2))


def test_validate_accepts_an_iterable_of_assignments():
    assert validate_styles(list(make_set().values())) == []


def test_validate_reports_non_mappings_and_missing_keys():
    assert validate_styles([42])
    assert validate_styles([{}])


# --- 7. ValueErrors --------------------------------------------------------


@pytest.mark.parametrize("height", [0, 0.0, -1, -0.5, -9000])
def test_non_positive_heights_raise(height):
    with pytest.raises(ValueError):
        assign_style("b0", "brick", height, seed=1)


@pytest.mark.parametrize("height", [None, "1200", True, [1200]])
def test_non_numeric_heights_raise(height):
    with pytest.raises(ValueError):
        assign_style("b0", "brick", height, seed=1)


@pytest.mark.parametrize("family", ["", "sandstone", "CIVIC_STONE", "cha",
                                    "civic", None])
def test_unknown_families_raise(family):
    with pytest.raises(ValueError):
        assign_style("b0", family, 1200.0, seed=1)
