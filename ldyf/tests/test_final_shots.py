"""Proof that ``final_shots_v1`` covers the 90 s visual-lock spec.

A synthetic downtown (record summary + city layout + closure) is built here by
hand, in Unreal centimetres:

* bounds 0..40000 x 0..24000, centre (20000, 12000);
* four blocks A/B (north row, y 1000..11000) and C/D (south row,
  y 13000..23000); A and C end at x 17000, B and D start at x 20000, so the
  avenue corridor x 17000..20000 runs the full height of the city;
* closure barricade at (18500, 12000), the avenue/crossing centre;
* five vehicles queued on the avenue north of the barrier (x 18000,
  y 9000..11800);
* ten pedestrians around the crossing and along the avenue sidewalk;
* the civic clock tower (landmark, height 5600 cm) on block D's west frontage;
* four avenue trees along block D's west sidewalk (canopy 850-900 cm).

All checks are arithmetic: determinism (byte-identical JSON), exact tiling of
[0, 90], full requirement coverage, person_frame_fraction computed from the
700 cm camera standoff and cleared against the 0.20 floor, one validate_shots
refusal case per test, and the ValueError input paths.
"""

from __future__ import annotations

import copy
import json
import math

import pytest

from ldyf.final_shots import (
    FINAL_SHOTS_SCHEMA,
    PERSON_FRAME_FRACTION_FLOOR,
    REQUIREMENTS,
    final_shot_plan,
    person_frame_fraction,
    validate_shots,
    vertical_fov_deg,
)


def _pt(x: float, y: float) -> dict:
    return {"x": x, "y": y}


def make_record() -> dict:
    return {
        "clock": {"t_begin": 0.0, "step_seconds": 1.0 / 24.0, "frame_count": 2160},
        "bounds_cm": {"min_x": 0.0, "min_y": 0.0, "max_x": 40000.0, "max_y": 24000.0},
        "people_cm": [
            _pt(17100, 11200), _pt(17200, 6000), _pt(17200, 8000),
            _pt(17400, 11400), _pt(17900, 12900), _pt(18800, 12950),
            _pt(19600, 13100), _pt(19750, 15000), _pt(19800, 16200),
            _pt(20300, 11400),
        ],
        "vehicles_cm": [
            _pt(18000, 9000), _pt(18000, 9700), _pt(18000, 10400),
            _pt(18000, 11100), _pt(18000, 11800),
        ],
    }


def make_layout() -> dict:
    return {
        "schema_version": "city_layout_v1",
        "blocks": [
            {"id": "A", "polygon": [_pt(1000, 1000), _pt(17000, 1000),
                                    _pt(17000, 11000), _pt(1000, 11000)]},
            {"id": "B", "polygon": [_pt(20000, 1000), _pt(39000, 1000),
                                    _pt(39000, 11000), _pt(20000, 11000)]},
            {"id": "C", "polygon": [_pt(1000, 13000), _pt(17000, 13000),
                                    _pt(17000, 23000), _pt(1000, 23000)]},
            {"id": "D", "polygon": [_pt(20000, 13000), _pt(39000, 13000),
                                    _pt(39000, 23000), _pt(20000, 23000)]},
        ],
        "landmark": {"x": 20000.0, "y": 18000.0, "yaw": 180.0, "height_cm": 5600.0},
        "foliage": [
            {"x": 19800.0, "y": 5000.0, "canopy_height_cm": 850.0},
            {"x": 19800.0, "y": 9000.0, "canopy_height_cm": 850.0},
            {"x": 19800.0, "y": 15000.0, "canopy_height_cm": 900.0},
            {"x": 19800.0, "y": 17000.0, "canopy_height_cm": 900.0},
        ],
    }


def make_closure() -> dict:
    return {"x": 18500.0, "y": 12000.0, "edge_ids": ["avenue_n_s"]}


@pytest.fixture
def plan() -> dict:
    return final_shot_plan(make_record(), make_layout(), make_closure(),
                           fps=24, seconds=90.0)


# --- determinism ------------------------------------------------------------


def test_two_runs_are_byte_identical(plan):
    again = final_shot_plan(make_record(), make_layout(), make_closure(),
                            fps=24, seconds=90.0)
    assert json.dumps(plan, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_schema_and_shape(plan):
    assert plan["schema_version"] == FINAL_SHOTS_SCHEMA
    assert len(plan["shots"]) == 11
    for s in plan["shots"]:
        assert set(("name", "kind", "start_s", "end_s", "loc", "rot",
                    "fov_deg", "covers")) <= set(s)
        assert len(s["loc"]) == 3 and len(s["rot"]) == 3
        assert s["fov_deg"] == 60.0


# --- timeline tiling ---------------------------------------------------------


def test_timeline_tiles_zero_to_ninety_exactly(plan):
    assert plan["total_seconds"] == 90.0
    starts = [0.0, 11.0, 20.0, 29.0, 37.0, 45.0, 53.0, 61.0, 69.0, 77.0, 84.0]
    t = 0.0
    for s in sorted(plan["shots"], key=lambda s: s["start_s"]):
        assert s["start_s"] == pytest.approx(t, abs=1e-6)
        assert s["end_s"] > s["start_s"]
        t = s["end_s"]
    assert t == pytest.approx(90.0, abs=1e-6)
    assert [s["start_s"] for s in sorted(plan["shots"],
                                         key=lambda s: s["start_s"])] == starts
    assert validate_shots(plan) == []


def test_plan_also_tiles_at_the_60_s_floor():
    doc = final_shot_plan(make_record(), make_layout(), make_closure(),
                          fps=24, seconds=60.0)
    assert doc["total_seconds"] == 60.0
    t = 0.0
    for s in sorted(doc["shots"], key=lambda s: s["start_s"]):
        assert s["start_s"] == pytest.approx(t, abs=1e-3)
        assert s["end_s"] - s["start_s"] >= 4.0
        t = s["end_s"]
    assert t == pytest.approx(60.0, abs=1e-3)
    assert validate_shots(doc) == []


# --- coverage ----------------------------------------------------------------


def test_every_requirement_is_covered(plan):
    covered = set()
    for s in plan["shots"]:
        covered.update(s["covers"])
    assert covered == set(REQUIREMENTS)
    for req in REQUIREMENTS:
        entry = plan["coverage"][req]
        assert entry["shots"], f"requirement {req} names no shot"


def test_coverage_names_which_shot_satisfies_each_requirement(plan):
    expected = {
        "city_overview": ["city_aerial_overview"],
        "street_level": ["street_level_avenue"],
        "visible_humans": ["people_recognisable"],
        "traffic_motion": ["traffic_in_motion"],
        "facade_detail": ["facade_ground_floor"],
        "leafy_vegetation": ["tree_canopy_sky"],
        "civic_landmark": ["civic_clock_tower"],
        "storefront_life": ["storefront_street_life"],
        "road_closure": ["closure_barrier"],
        "traffic_reaction": ["traffic_queue_at_barrier"],
        "final_city_view": ["city_final_view"],
    }
    for req, names in expected.items():
        assert plan["coverage"][req]["shots"] == names


# --- the arithmetic requirement (the one the old plan failed) -----------------


def test_close_shot_fraction_clears_the_floor(plan):
    close = next(s for s in plan["shots"] if "visible_humans" in s["covers"])
    assert close["person_frame_fraction"] >= PERSON_FRAME_FRACTION_FLOOR
    assert close["person_frame_fraction"] > 0.30      # comfortable margin


def test_fraction_matches_the_formula_by_hand(plan):
    close = next(s for s in plan["shots"] if "visible_humans" in s["covers"])
    # median pedestrian (18800, 12950); camera 700 cm west at (18100, 12950);
    # the nearest pedestrian with a positive view-direction dot is the anchor
    # itself at exactly 700 cm.
    assert close["person_distance_cm"] == 700.0
    vfov = vertical_fov_deg(60.0)
    expected = 175.0 / (2.0 * 700.0 * math.tan(math.radians(vfov) / 2.0))
    assert close["person_frame_fraction"] == pytest.approx(expected, abs=1e-3)
    entry = plan["coverage"]["visible_humans"]
    assert entry["distance_to_nearest_pedestrian_cm"] == 700.0
    assert entry["person_height_cm"] == 175.0
    assert entry["floor"] == PERSON_FRAME_FRACTION_FLOOR


def test_vertical_fov_derivation(plan):
    # hfov 60 deg at 16:9 -> vfov = 2*atan(tan(30 deg) / (16/9))
    #   tan(30) = 0.5773503, / 1.777778 = 0.3247596, atan = 17.9917 deg
    #   so vfov = 35.9834 deg. The old assertion used the rounded 36.0 with a
    #   0.01 tolerance, which is tighter than its own rounding.
    vfov = vertical_fov_deg(60.0)
    assert vfov == pytest.approx(35.9834, abs=1e-3)
    # tan(v/2) == tan(h/2)/aspect, so at 700 cm a 175 cm person is ~38.5 % tall
    assert person_frame_fraction(700.0, 60.0) == pytest.approx(0.385, abs=1e-2)


# --- every camera above ground ------------------------------------------------

def test_no_camera_below_ground(plan):
    for s in plan["shots"]:
        assert s["loc"][2] > 0.0


# --- validate_shots refusal cases, one test per refusal -----------------------


def _shot(plan, name):
    return next(s for s in plan["shots"] if s["name"] == name)


def test_validate_refuses_a_gap():
    doc = final_shot_plan(make_record(), make_layout(), make_closure())
    _shot(doc, "street_level_avenue")["start_s"] = 11.5   # was 11.0
    problems = validate_shots(doc)
    assert any("gap or overlap" in p for p in problems)


def test_validate_refuses_an_overlap():
    doc = final_shot_plan(make_record(), make_layout(), make_closure())
    _shot(doc, "people_recognisable")["start_s"] = 19.5   # overlaps 11..20
    problems = validate_shots(doc)
    assert any("gap or overlap" in p for p in problems)


def test_validate_refuses_total_duration_outside_60_120():
    doc = final_shot_plan(make_record(), make_layout(), make_closure())
    doc["total_seconds"] = 45.0
    problems = validate_shots(doc)
    assert any("outside" in p and "total duration" in p for p in problems)


def test_validate_refuses_requirement_with_no_covering_shot():
    doc = final_shot_plan(make_record(), make_layout(), make_closure())
    close = _shot(doc, "people_recognisable")
    close["covers"] = [c for c in close["covers"] if c != "visible_humans"]
    del doc["coverage"]["visible_humans"]
    problems = validate_shots(doc)
    assert any("'visible_humans' has no covering shot" in p for p in problems)
    assert any("coverage names no shot" in p for p in problems)


def test_validate_refuses_fraction_below_the_floor():
    doc = final_shot_plan(make_record(), make_layout(), make_closure())
    _shot(doc, "people_recognisable")["person_frame_fraction"] = 0.05
    problems = validate_shots(doc)
    assert any("below floor" in p for p in problems)


def test_validate_refuses_camera_below_ground():
    doc = final_shot_plan(make_record(), make_layout(), make_closure())
    _shot(doc, "closure_barrier")["loc"] = [18300.0, 12800.0, -5.0]
    problems = validate_shots(doc)
    assert any("below ground" in p for p in problems)


def test_validate_refuses_shot_shorter_than_minimum():
    doc = final_shot_plan(make_record(), make_layout(), make_closure())
    s = _shot(doc, "city_final_view")
    s["start_s"] = 84.0
    s["end_s"] = 84.5                               # 0.5 s cut
    problems = validate_shots(doc)
    assert any("minimum" in p for p in problems)


def test_validate_rejects_a_non_final_shots_document():
    problems = validate_shots({"schema_version": "something_else", "shots": []})
    assert problems and "not a final_shots_v1" in problems[0]


# --- ValueError input paths ----------------------------------------------------


@pytest.mark.parametrize("bad_fps", [0, -1, -24])
def test_fps_must_be_positive(bad_fps):
    with pytest.raises(ValueError):
        final_shot_plan(make_record(), make_layout(), make_closure(), fps=bad_fps)


@pytest.mark.parametrize("bad_seconds", [0, -1, -90])
def test_seconds_must_be_positive(bad_seconds):
    with pytest.raises(ValueError):
        final_shot_plan(make_record(), make_layout(), make_closure(),
                        seconds=bad_seconds)


def test_preview_too_short_for_eleven_cuts_raises():
    # 50 s would leave the shortest cut below the 4 s minimum
    with pytest.raises(ValueError):
        final_shot_plan(make_record(), make_layout(), make_closure(), seconds=50.0)


@pytest.mark.parametrize("empty", [
    {},
    {"clock": {"frame_count": 0}, "bounds_cm": make_record()["bounds_cm"]},
    {"clock": {"frame_count": 100},
     "bounds_cm": make_record()["bounds_cm"],
     "people_cm": [], "vehicles_cm": []},
])
def test_empty_record_raises(empty):
    with pytest.raises(ValueError):
        final_shot_plan(empty, make_layout(), make_closure())


def test_layout_without_landmark_raises():
    layout = make_layout()
    del layout["landmark"]
    with pytest.raises(ValueError):
        final_shot_plan(make_record(), layout, make_closure())


def test_layout_without_foliage_raises():
    layout = make_layout()
    layout["foliage"] = []
    with pytest.raises(ValueError):
        final_shot_plan(make_record(), layout, make_closure())


def test_layout_without_blocks_raises():
    layout = make_layout()
    layout["blocks"] = []
    with pytest.raises(ValueError):
        final_shot_plan(make_record(), layout, make_closure())


def test_closure_without_location_raises():
    with pytest.raises(ValueError):
        final_shot_plan(make_record(), make_layout(), {"edge_ids": ["x"]})


def test_mutating_a_returned_doc_does_not_leak_between_calls():
    doc = final_shot_plan(make_record(), make_layout(), make_closure())
    doc["shots"][0]["loc"][2] = -1.0
    fresh = final_shot_plan(make_record(), make_layout(), make_closure())
    assert fresh["shots"][0]["loc"][2] > 0.0
    assert validate_shots(copy.deepcopy(doc))  # the mutated copy is refused
