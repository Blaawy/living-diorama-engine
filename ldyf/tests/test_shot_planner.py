"""Proof that shot_planner_v1 aims cameras at what is actually happening.

The synthetic record is built with the same FCD helper as the record tests
(``write_fcd`` from ``test_sumo_record``), step_seconds = 0.1. SUMO metres
become Unreal centimetres via the coords rule x*100, y -> -y*100, so:

    vehicle a @ SUMO (10, 20)  -> Unreal (1000, -2000)  cell (1, -2)
    vehicle b @ SUMO (50, 80)  -> Unreal (5000, -8000)  cell (5, -8)
    person  c @ SUMO (90, 90)  -> Unreal (9000, -9000)  cell (9, -9)

with cell_cm = 1000. Frame i sits at t = i * 0.1 s.
"""

from __future__ import annotations

import json
import math

import pytest

from ldyf.shot_planner import (
    SHOT_PLAN_SCHEMA_VERSION,
    actor_density,
    busiest_cell,
    frame_shot,
    hotspots,
    plan_shots,
)
from ldyf.sumo_record import build_record
from ldyf.tests.test_sumo_record import write_fcd

STEP = 0.1

MAIN_TIMESTEPS = [
    (0.0, [("vehicle", "a", 10.0, 20.0, 0.0, 5.0),
           ("vehicle", "b", 50.0, 80.0, 0.0, 5.0)]),
    (0.1, [("vehicle", "a", 10.0, 20.0, 0.0, 5.0),
           ("vehicle", "b", 50.0, 80.0, 0.0, 5.0),
           ("person", "c", 90.0, 90.0, 0.0, 1.0)]),
    (0.2, [("vehicle", "a", 10.0, 20.0, 0.0, 5.0),
           ("vehicle", "b", 50.0, 80.0, 0.0, 5.0)]),
    (0.3, [("vehicle", "b", 50.0, 80.0, 0.0, 5.0)]),
    (0.4, []),
    (0.5, [("vehicle", "a", 10.0, 20.0, 0.0, 5.0)]),
]


def build(tmp_path, timesteps):
    fcd = tmp_path / "t.fcd.xml"
    write_fcd(fcd, timesteps)
    out = tmp_path / "rec"
    build_record(fcd, out, step_seconds=STEP)
    man = json.loads((out / "record_manifest.json").read_text())
    return out / "frames.bin", man


@pytest.fixture
def rec(tmp_path):
    return build(tmp_path, MAIN_TIMESTEPS)


# --- actor_density --------------------------------------------------------


def test_density_bins_positions_and_counts_exactly(rec):
    frames_path, man = rec
    d = actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.3, cell_cm=1000.0)
    assert d["cells"] == {(1, -2): 3, (5, -8): 4, (9, -9): 1}
    assert d["frames"] == 4            # frames 0..3, empties included by count
    assert d["samples"] == 8
    assert d["cell_cm"] == 1000.0


def test_density_window_includes_the_end_frame_time(rec):
    frames_path, man = rec
    d = actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.1, cell_cm=1000.0)
    assert d["frames"] == 2
    assert d["cells"] == {(1, -2): 2, (5, -8): 2, (9, -9): 1}


def test_density_kinds_filter_excludes_persons(rec):
    frames_path, man = rec
    d = actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.3,
                      cell_cm=1000.0, kinds={"vehicle"})
    assert d["cells"] == {(1, -2): 3, (5, -8): 4}
    assert d["samples"] == 7


def test_density_kinds_filter_keeps_only_persons(rec):
    frames_path, man = rec
    d = actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.3,
                      cell_cm=1000.0, kinds={"person"})
    assert d["cells"] == {(9, -9): 1}
    assert d["samples"] == 1
    assert d["frames"] == 4


def test_density_stride_is_an_explicit_sampling_shortcut(rec):
    frames_path, man = rec
    d = actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.3,
                      cell_cm=1000.0, stride=2)
    assert d["cells"] == {(1, -2): 2, (5, -8): 2}   # frames 0 and 2 only
    assert d["frames"] == 2
    assert d["samples"] == 4


def test_density_empty_frames_are_walked_not_skipped(rec):
    frames_path, man = rec
    d = actor_density(frames_path, man, t_start_s=0.2, t_end_s=0.5, cell_cm=1000.0)
    assert d["frames"] == 4                          # frames 2, 3, 4, 5
    assert d["samples"] == 4                         # a twice (f2,f5), b twice (f2,f3)


def test_density_raises_when_end_not_after_start(rec):
    frames_path, man = rec
    with pytest.raises(ValueError, match="must be > t_start_s"):
        actor_density(frames_path, man, t_start_s=0.3, t_end_s=0.2, cell_cm=1000.0)
    with pytest.raises(ValueError, match="must be > t_start_s"):
        actor_density(frames_path, man, t_start_s=0.3, t_end_s=0.3, cell_cm=1000.0)


def test_density_raises_on_nonpositive_cell(rec):
    frames_path, man = rec
    with pytest.raises(ValueError, match="cell_cm"):
        actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.1, cell_cm=0.0)


def test_density_raises_on_record_with_no_frames(tmp_path):
    frames_path, man = build(tmp_path, [])
    with pytest.raises(ValueError, match="no frames"):
        actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.1, cell_cm=1000.0)


# --- busiest_cell / hotspots ----------------------------------------------


def test_busiest_cell_picks_the_highest_count(rec):
    frames_path, man = rec
    d = actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.3, cell_cm=1000.0)
    assert busiest_cell(d) == (5, -8)


def test_busiest_cell_tie_breaks_lexicographically_smallest():
    """Two cells tied on count must resolve to the lexicographically smallest
    (ix, iy), so the choice is reproducible run to run.  Built as a literal
    density so the test covers the tie rule and not the window contract."""
    d = {"cells": {(1, -2): 3, (5, -1): 3, (1, -1): 1},
         "frames": 1, "samples": 7, "cell_cm": 1000.0}
    assert busiest_cell(d) == (1, -2)
    assert busiest_cell(d, exclude=((1, -2),)) == (5, -1)
    assert busiest_cell({"cells": {}, "frames": 0, "samples": 0,
                         "cell_cm": 1000.0}) is None
def test_busiest_cell_exclude_skips_cells(rec):
    frames_path, man = rec
    d = actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.3, cell_cm=1000.0)
    assert busiest_cell(d, exclude={(5, -8)}) == (1, -2)


def test_busiest_cell_none_when_empty(tmp_path):
    frames_path, man = build(tmp_path, [(0.0, [])])
    d = actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.1, cell_cm=1000.0)
    assert d["cells"] == {}
    assert busiest_cell(d) is None


def test_hotspots_return_busiest_separated_cells(rec):
    frames_path, man = rec
    d = actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.5, cell_cm=1000.0)
    hs = hotspots(d, count=2, min_separation_cells=2)
    assert [(h["ix"], h["iy"]) for h in hs] == [(1, -2), (5, -8)]
    assert [h["count"] for h in hs] == [4, 4]


def test_hotspots_exclude_cells_below_min_separation(rec):
    frames_path, man = rec
    d = actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.5, cell_cm=1000.0)
    # (5, -8) is 7.2 cells from (1, -2): rejected; (9, -9) is 10.6: kept
    hs = hotspots(d, count=2, min_separation_cells=10)
    assert [(h["ix"], h["iy"]) for h in hs] == [(1, -2), (9, -9)]


def test_hotspots_return_fewer_when_window_cannot_supply(rec):
    frames_path, man = rec
    d = actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.5, cell_cm=1000.0)
    hs = hotspots(d, count=3, min_separation_cells=100)
    assert len(hs) == 1
    assert (hs[0]["ix"], hs[0]["iy"]) == (1, -2)
    assert hs[0]["count"] == 4


def test_hotspots_tie_break_is_deterministic():
    """Equal-count cells must come back in (-count, ix, iy) order every time,
    so a shot plan does not move between runs."""
    d = {"cells": {(0, 0): 5, (9, 9): 5, (4, 4): 5, (0, 1): 1},
         "frames": 1, "samples": 16, "cell_cm": 1000.0}
    a = hotspots(d, count=3, min_separation_cells=1.0)
    b = hotspots(d, count=3, min_separation_cells=1.0)
    assert [(h["ix"], h["iy"]) for h in a] == [(0, 0), (4, 4), (9, 9)]
    assert a == b
def test_hotspots_report_cell_centres(rec):
    frames_path, man = rec
    d = actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.5, cell_cm=1000.0)
    hs = hotspots(d, count=2, min_separation_cells=2)
    assert hs[0]["x_cm"] == 1500.0 and hs[0]["y_cm"] == -1500.0
    assert hs[1]["x_cm"] == 5500.0 and hs[1]["y_cm"] == -7500.0


def test_hotspots_raise_on_nonpositive_count(rec):
    frames_path, man = rec
    d = actor_density(frames_path, man, t_start_s=0.0, t_end_s=0.1, cell_cm=1000.0)
    with pytest.raises(ValueError, match="count"):
        hotspots(d, count=0, min_separation_cells=1)


# --- frame_shot arithmetic -------------------------------------------------


def test_frame_shot_bearing_zero_faces_back_west(rec):
    s = frame_shot(0.0, 0.0, distance_cm=100.0, height_cm=0.0, bearing_deg=0.0)
    assert s["location"] == {"x": 100.0, "y": 0.0, "z": 0.0}
    assert s["rotation"] == {"pitch": 0.0, "yaw": 180.0, "roll": 0.0}


def test_frame_shot_bearing_ninety_places_camera_south(rec):
    s = frame_shot(0.0, 0.0, distance_cm=100.0, height_cm=0.0, bearing_deg=90.0)
    assert s["location"] == {"x": 0.0, "y": 100.0, "z": 0.0}
    assert s["rotation"]["yaw"] == -90.0


def test_frame_shot_pitch_is_minus_forty_five_at_equal_height(rec):
    s = frame_shot(0.0, 0.0, distance_cm=100.0, height_cm=100.0, bearing_deg=0.0)
    assert s["rotation"]["pitch"] == -45.0
    assert s["location"]["z"] == 100.0


def test_frame_shot_bearing_180_and_trig_float_noise(rec):
    s = frame_shot(100.0, 100.0, distance_cm=50.0, height_cm=0.0, bearing_deg=180.0)
    # sin(pi) is ~1.2e-16; _f3 must kill that noise
    assert s["location"] == {"x": 50.0, "y": 100.0, "z": 0.0}
    assert s["rotation"]["yaw"] == 0.0


def test_frame_shot_general_bearing_matches_hand_trig(rec):
    tx, ty, d, h, b = 1000.0, -2000.0, 200.0, 50.0, 30.0
    s = frame_shot(tx, ty, distance_cm=d, height_cm=h, bearing_deg=b)
    rad = math.radians(b)
    assert s["location"]["x"] == pytest.approx(tx + d * math.cos(rad), abs=1e-3)
    assert s["location"]["y"] == pytest.approx(ty + d * math.sin(rad), abs=1e-3)
    assert s["location"]["z"] == 50.0
    assert s["rotation"]["yaw"] == pytest.approx(
        math.degrees(math.atan2(ty - (ty + d * math.sin(rad)),
                                tx - (tx + d * math.cos(rad)))), abs=1e-3)
    assert s["rotation"]["pitch"] == pytest.approx(
        math.degrees(math.atan2(-h, d)), abs=1e-3)
    assert s["rotation"]["roll"] == 0.0


# --- plan_shots ------------------------------------------------------------


def _fixed_req(**kw):
    base = {"name": "s", "kind": "fixed", "start_s": 0.0, "end_s": 0.3,
            "distance_cm": 800.0, "height_cm": 300.0, "bearing_deg": 0.0,
            "x": 1000.0, "y": -2000.0}
    base.update(kw)
    return base


def test_plan_overview_fov_fit_distance_90(rec):
    frames_path, man = rec
    req = {"name": "over", "kind": "overview", "start_s": 0.0, "end_s": 0.3,
           "distance_cm": 1.0, "height_cm": 300.0, "bearing_deg": 0.0}
    plan = plan_shots(frames_path, man, fps=10.0, shots=[req], cell_cm=1000.0,
                      fov_deg=90.0, fit_bbox_cm=(2000.0, 1000.0),
                      view_radius_cm=6000.0)
    shot = plan["shots"][0]
    assert shot["target"] == {"x": 4000.0, "y": -5875.0}     # activity centroid
    assert shot["distance_cm"] == 1000.0                     # 1000 / tan(45)
    assert (shot["start_frame"], shot["end_frame"]) == (0, 3)
    assert shot["actors_in_view_estimate"] == 2              # a and b at frame 2
    # the box actually fits: visible half-width at that distance
    assert shot["distance_cm"] * math.tan(math.radians(90.0) / 2.0) == pytest.approx(1000.0)
    # exact equality would fail on float noise alone: tan(45 deg) is
    # 0.9999999999999999, not 1.0


def test_plan_overview_fov_fit_trigonometry_60(rec):
    frames_path, man = rec
    req = {"name": "over", "kind": "overview", "start_s": 0.0, "end_s": 0.3,
           "distance_cm": 1.0, "height_cm": 300.0, "bearing_deg": 0.0}
    plan = plan_shots(frames_path, man, fps=10.0, shots=[req], cell_cm=1000.0,
                      fov_deg=60.0, fit_bbox_cm=(2000.0, 1000.0),
                      view_radius_cm=6000.0)
    shot = plan["shots"][0]
    expect = 1000.0 / math.tan(math.radians(30.0))
    assert shot["distance_cm"] == pytest.approx(expect, abs=1e-2)
    assert shot["distance_cm"] * math.tan(math.radians(60.0) / 2.0) == pytest.approx(1000.0, abs=1e-2)


def test_plan_overview_fit_uses_the_larger_box_dimension(rec):
    frames_path, man = rec
    req = {"name": "over", "kind": "overview", "start_s": 0.0, "end_s": 0.3,
           "distance_cm": 1.0, "height_cm": 300.0, "bearing_deg": 0.0}
    plan = plan_shots(frames_path, man, fps=10.0, shots=[req], cell_cm=1000.0,
                      fov_deg=90.0, fit_bbox_cm=(500.0, 4000.0), view_radius_cm=6000.0)
    assert plan["shots"][0]["distance_cm"] == 2000.0         # 4000/2 / tan(45)


def test_plan_hotspot_targets_busiest_cell_of_its_window(rec):
    frames_path, man = rec
    req = {"name": "hot", "kind": "hotspot", "start_s": 0.0, "end_s": 0.3,
           "distance_cm": 800.0, "height_cm": 300.0, "bearing_deg": 0.0}
    plan = plan_shots(frames_path, man, fps=10.0, shots=[req], cell_cm=1000.0, fov_deg=90.0)
    shot = plan["shots"][0]
    assert shot["target"] == {"x": 5500.0, "y": -7500.0}     # busiest cell centre
    assert shot["distance_cm"] == 800.0
    assert shot["camera"]["location"]["x"] == 6300.0
    assert shot["camera"]["rotation"]["yaw"] == 180.0
    assert shot["camera"]["rotation"]["pitch"] == pytest.approx(-20.556, abs=1e-3)
    assert shot["actors_in_view_estimate"] == 1              # only b at frame 2


def test_plan_fixed_uses_request_coordinates(rec):
    frames_path, man = rec
    req = _fixed_req(bearing_deg=90.0, distance_cm=500.0, height_cm=200.0)
    plan = plan_shots(frames_path, man, fps=10.0, shots=[req], cell_cm=1000.0, fov_deg=90.0)
    shot = plan["shots"][0]
    assert shot["kind"] == "fixed"
    assert shot["target"] == {"x": 1000.0, "y": -2000.0}
    assert shot["camera"]["location"] == {"x": 1000.0, "y": -1500.0, "z": 200.0}
    assert shot["camera"]["rotation"]["yaw"] == -90.0


def test_plan_frame_range_rounds_times_to_frames(rec):
    frames_path, man = rec
    plan = plan_shots(frames_path, man, fps=10.0, shots=[_fixed_req()],
                      cell_cm=1000.0, fov_deg=90.0)
    assert (plan["shots"][0]["start_frame"], plan["shots"][0]["end_frame"]) == (0, 3)
    plan2 = plan_shots(frames_path, man, fps=10.0,
                       shots=[_fixed_req(end_s=0.25)], cell_cm=1000.0, fov_deg=90.0)
    # Python round: 0.25 * 10 = 2.5 rounds to 2 (banker's) -- locked here
    assert plan2["shots"][0]["end_frame"] == int(round(0.25 * 10.0)) == 2


def test_plan_schema_version_and_params_echo(rec):
    frames_path, man = rec
    plan = plan_shots(frames_path, man, fps=10.0, shots=[_fixed_req()],
                      cell_cm=1000.0, fov_deg=90.0, stride=1,
                      fit_bbox_cm=(2000.0, 1000.0), view_radius_cm=500.0)
    assert plan["schema_version"] == SHOT_PLAN_SCHEMA_VERSION == "shot_plan_v1"
    assert plan["params"]["fps"] == 10.0
    assert plan["params"]["cell_cm"] == 1000.0
    assert plan["params"]["fov_deg"] == 90.0
    assert plan["params"]["stride"] == 1
    assert plan["params"]["fit_bbox_cm"] == [2000.0, 1000.0]
    assert plan["params"]["view_radius_cm"] == 500.0
    shot = plan["shots"][0]
    for key in ("name", "kind", "start_s", "end_s", "start_frame", "end_frame",
                "distance_cm", "height_cm", "bearing_deg", "target", "camera",
                "view_radius_cm", "actors_in_view_estimate"):
        assert key in shot


def test_plan_is_byte_identical_across_runs(rec):
    frames_path, man = rec
    reqs = [_fixed_req(), {"name": "over", "kind": "overview", "start_s": 0.0,
                           "end_s": 0.5, "distance_cm": 1.0, "height_cm": 300.0,
                           "bearing_deg": 45.0}]
    p1 = plan_shots(frames_path, man, fps=10.0, shots=reqs, cell_cm=1000.0,
                    fov_deg=90.0, fit_bbox_cm=(2000.0, 1000.0), view_radius_cm=6000.0)
    p2 = plan_shots(frames_path, man, fps=10.0, shots=reqs, cell_cm=1000.0,
                    fov_deg=90.0, fit_bbox_cm=(2000.0, 1000.0), view_radius_cm=6000.0)
    assert json.dumps(p1, indent=2, sort_keys=True) == json.dumps(p2, indent=2, sort_keys=True)


def test_plan_raises_when_fps_not_positive(rec):
    frames_path, man = rec
    with pytest.raises(ValueError, match="fps"):
        plan_shots(frames_path, man, fps=0.0, shots=[], cell_cm=1000.0, fov_deg=90.0)
    with pytest.raises(ValueError, match="fps"):
        plan_shots(frames_path, man, fps=-10.0, shots=[], cell_cm=1000.0, fov_deg=90.0)


def test_plan_raises_on_unknown_kind(rec):
    frames_path, man = rec
    with pytest.raises(ValueError, match="unknown shot kind"):
        plan_shots(frames_path, man, fps=10.0, shots=[{"name": "x", "kind": "zoom"}],
                   cell_cm=1000.0, fov_deg=90.0)


def test_plan_raises_when_window_not_increasing(rec):
    frames_path, man = rec
    with pytest.raises(ValueError, match="must be > start_s"):
        plan_shots(frames_path, man, fps=10.0,
                   shots=[_fixed_req(start_s=0.4, end_s=0.2)],
                   cell_cm=1000.0, fov_deg=90.0)


def test_plan_overview_requires_fit_bbox(rec):
    frames_path, man = rec
    req = {"name": "over", "kind": "overview", "start_s": 0.0, "end_s": 0.3,
           "distance_cm": 1.0, "height_cm": 300.0, "bearing_deg": 0.0}
    with pytest.raises(ValueError, match="fit_bbox_cm"):
        plan_shots(frames_path, man, fps=10.0, shots=[req], cell_cm=1000.0, fov_deg=90.0)


def test_plan_fixed_requires_x_and_y(rec):
    frames_path, man = rec
    req = {"name": "s", "kind": "fixed", "start_s": 0.0, "end_s": 0.3,
           "distance_cm": 100.0, "height_cm": 100.0, "bearing_deg": 0.0}
    with pytest.raises(ValueError, match="needs x and y"):
        plan_shots(frames_path, man, fps=10.0, shots=[req], cell_cm=1000.0, fov_deg=90.0)


def test_plan_hotspot_with_no_activity_raises(tmp_path):
    frames_path, man = build(tmp_path, [(0.0, [])])
    req = {"name": "h", "kind": "hotspot", "start_s": 0.0, "end_s": 0.1,
           "distance_cm": 100.0, "height_cm": 100.0, "bearing_deg": 0.0}
    with pytest.raises(ValueError, match="no activity"):
        plan_shots(frames_path, man, fps=10.0, shots=[req], cell_cm=1000.0, fov_deg=90.0)


def test_plan_overview_with_no_activity_raises(tmp_path):
    frames_path, man = build(tmp_path, [(0.0, [])])
    req = {"name": "o", "kind": "overview", "start_s": 0.0, "end_s": 0.1,
           "distance_cm": 1.0, "height_cm": 100.0, "bearing_deg": 0.0}
    with pytest.raises(ValueError, match="no activity"):
        plan_shots(frames_path, man, fps=10.0, shots=[req], cell_cm=1000.0,
                   fov_deg=90.0, fit_bbox_cm=(2000.0, 1000.0))
