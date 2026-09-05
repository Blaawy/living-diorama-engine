"""Tests for ldyf.perf_report -- honest performance recording (Phase 2).

All expected values are hand-computed.  Percentile rule used throughout:
nearest-rank, i.e. with N durations sorted ascending, p95_s is the value at
1-based rank ceil(0.95 * N) -- for N = 20 that is the 19th value, for N = 10
the 10th, for N = 44 the 42nd.

Pure stdlib: pytest only if present; the module also runs standalone via
``python ldyf/tests/test_perf_report.py``.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from ldyf.perf_report import (  # noqa: E402
    GEOMETRY_BUDGET,
    PERF_REPORT_VERSION,
    budget_report,
    build_report,
    classify,
    estimate_world_cost,
    is_stale,
    realtime_ratio,
    render_cost,
    summarise_samples,
    validate_budget,
    write_report,
)

# --- hand-computed fixtures -------------------------------------------------

# Durations 1..20 s.  mean = 10.5, median = 10.5, p95 (nearest-rank,
# ceil(0.95*20) = 19th ascending value) = 19.0, min = 1.0, max = 20.0.
ONES_TO_TWENTY = [float(i) for i in range(1, 21)]

# warmup = [99.0, 98.0], then 3..12 s.  With warmup_drop=2 the kept set is
# 3..12: count 10, mean 7.5, median 7.5, p95 = 12.0 (10th of 10), min 3, max 12.
WARMUP_SAMPLES = [99.0, 98.0] + [float(i) for i in range(3, 13)]

# Spiky series: 40 fast frames at 0.016 s plus 4 slow frames at 0.25 s.
# mean = (40*0.016 + 4*0.25)/44 = 1.64/44 ~ 0.03727 s; median = 0.016 s;
# p95 (ceil(0.95*44) = 42nd ascending) = 0.25 s.
SPIKY = [0.25] * 4 + [0.016] * 40


def _expects_value_error(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError("expected ValueError from %r" % (fn,))


# --- summarise_samples ------------------------------------------------------


def test_summarise_mean_median_p95_on_known_list():
    """1..20: mean 10.5, median 10.5, p95_s 19.0 (nearest-rank rule)."""
    s = summarise_samples(ONES_TO_TWENTY, warmup_drop=0)
    assert s["mean_s"] == 10.5
    assert s["median_s"] == 10.5
    assert s["p95_s"] == 19.0  # rank ceil(0.95 * 20) = 19 -> value 19


def test_summarise_count_min_max():
    s = summarise_samples(ONES_TO_TWENTY, warmup_drop=0)
    assert s["count"] == 20
    assert s["min_s"] == 1.0
    assert s["max_s"] == 20.0


def test_summarise_fps_values_hand_computed():
    # fps_mean = 1/10.5 = 0.09523... -> 0.095
    # fps_median = 1/10.5 = 0.095
    # fps_p95_low = 1/19.0 = 0.05263... -> 0.053
    s = summarise_samples(ONES_TO_TWENTY, warmup_drop=0)
    assert s["fps_mean"] == 0.095
    assert s["fps_median"] == 0.095
    assert s["fps_p95_low"] == 0.053


def test_summarise_sorts_unsorted_input():
    s = summarise_samples(list(reversed(ONES_TO_TWENTY)), warmup_drop=0)
    assert s["min_s"] == 1.0
    assert s["max_s"] == 20.0
    assert s["p95_s"] == 19.0


def test_p95_nearest_rank_documented_rule_independent_check():
    # Independent restatement of the rule inside the test:
    # rank = ceil(0.95 * N); p95 = that rank-th value of the ascending sort.
    s = summarise_samples(ONES_TO_TWENTY, warmup_drop=0)
    rank = math.ceil(0.95 * len(ONES_TO_TWENTY))
    expected = sorted(ONES_TO_TWENTY)[rank - 1]
    assert s["p95_s"] == expected == 19.0


def test_warmup_drop_removes_first_samples():
    s = summarise_samples(WARMUP_SAMPLES, warmup_drop=2)
    assert s["count"] == 10
    assert s["mean_s"] == 7.5  # (3+12)/2 for 3..12
    assert s["median_s"] == 7.5
    assert s["p95_s"] == 12.0  # 10th of 10
    assert s["min_s"] == 3.0
    assert s["max_s"] == 12.0
    assert s["fps_mean"] == 0.133  # 1/7.5 = 0.1333...
    assert s["fps_p95_low"] == 0.083  # 1/12 = 0.0833...


def test_warmup_drop_zero_keeps_all():
    s = summarise_samples(ONES_TO_TWENTY, warmup_drop=0)
    assert s["count"] == 20
    assert s["mean_s"] == 10.5


def test_warmup_drop_of_one_drops_the_warmup_value():
    s = summarise_samples([50.0] + [float(i) for i in range(1, 6)],
                          warmup_drop=1)
    # kept 1..5: mean 3.0, median 3.0, p95 = 5.0
    assert s["count"] == 5
    assert s["mean_s"] == 3.0
    assert s["median_s"] == 3.0
    assert s["p95_s"] == 5.0


def test_spiky_series_fps_p95_low_below_fps_mean():
    s = summarise_samples(SPIKY, warmup_drop=0)
    assert s["count"] == 44
    assert s["mean_s"] == 0.037  # 1.64/44 = 0.037272...
    assert s["fps_mean"] == 26.829  # 44/1.64 = 26.8292...
    assert s["fps_p95_low"] == 4.0  # 1/0.25
    assert s["fps_p95_low"] < s["fps_mean"]


def test_spiky_series_fps_p95_low_below_fps_median():
    s = summarise_samples(SPIKY, warmup_drop=0)
    assert s["fps_median"] == 62.5  # 1/0.016
    assert s["fps_p95_low"] < s["fps_median"]


def test_third_second_durations_round_to_three_decimals():
    third = 1.0 / 3.0
    s = summarise_samples([third, third, third], warmup_drop=0)
    assert s["mean_s"] == 0.333
    assert s["median_s"] == 0.333
    assert s["p95_s"] == 0.333
    assert s["fps_mean"] == 3.0
    assert s["fps_p95_low"] == 3.0


def test_empty_samples_raises_value_error():
    _expects_value_error(summarise_samples, [], warmup_drop=0)


def test_warmup_drop_equal_to_count_raises_value_error():
    _expects_value_error(summarise_samples, [1.0], warmup_drop=1)
    _expects_value_error(summarise_samples, ONES_TO_TWENTY, warmup_drop=20)


def test_warmup_drop_greater_than_count_raises_value_error():
    _expects_value_error(summarise_samples, ONES_TO_TWENTY, warmup_drop=21)


def test_negative_warmup_drop_raises_value_error():
    _expects_value_error(summarise_samples, ONES_TO_TWENTY, warmup_drop=-1)


def test_summarise_is_deterministic():
    a = summarise_samples(SPIKY, warmup_drop=2)
    b = summarise_samples(list(SPIKY), warmup_drop=2)
    assert a == b


# --- realtime_ratio ---------------------------------------------------------


def test_realtime_ratio_exact_target():
    ratio = realtime_ratio({"fps_p95_low": 60.0}, target_fps=60)
    assert ratio == 1.0


def test_realtime_ratio_half_target():
    ratio = realtime_ratio({"fps_p95_low": 30.0}, target_fps=60)
    assert ratio == 0.5


def test_realtime_ratio_uses_fps_p95_low_not_fps_mean():
    # mean is 120 fps but the felt (p95) rate is 30 -> ratio 0.5, not 2.0.
    ratio = realtime_ratio({"fps_p95_low": 30.0, "fps_mean": 120.0},
                           target_fps=60)
    assert ratio == 0.5


def test_realtime_ratio_from_a_real_summary():
    s = summarise_samples(SPIKY, warmup_drop=0)  # fps_p95_low == 4.0
    assert realtime_ratio(s, target_fps=20) == 0.2


def test_realtime_ratio_nonpositive_target_raises():
    _expects_value_error(realtime_ratio, {"fps_p95_low": 60.0}, target_fps=0)
    _expects_value_error(realtime_ratio, {"fps_p95_low": 60.0}, target_fps=-30)


# --- classify ---------------------------------------------------------------


def test_classify_realtime_at_exact_threshold():
    assert classify(0.95) == "realtime"


def test_classify_just_below_realtime_is_near_realtime():
    assert classify(0.95 - 1e-9) == "near_realtime"


def test_classify_near_realtime_at_exact_threshold():
    assert classify(0.5) == "near_realtime"


def test_classify_just_below_near_realtime_is_slow():
    assert classify(0.5 - 1e-9) == "slow"


def test_classify_slow_at_exact_threshold():
    assert classify(0.2) == "slow"


def test_classify_just_below_slow_is_offline():
    assert classify(0.2 - 1e-9) == "offline"


def test_classify_high_ratio_is_realtime():
    assert classify(2.0) == "realtime"
    assert classify(1.0) == "realtime"


def test_classify_zero_and_negative_are_offline():
    assert classify(0.0) == "offline"
    assert classify(-0.5) == "offline"


# --- render_cost ------------------------------------------------------------


def test_render_cost_arithmetic():
    r = render_cost(120, 10, fps=24, width=1920, height=1080)
    assert r["frames_per_wall_second"] == 12.0  # 120 / 10
    assert r["seconds_per_frame"] == 0.083  # 10 / 120 = 0.0833...
    assert r["presentation_seconds"] == 5.0  # 120 / 24


def test_render_cost_presentation_ignores_slow_wall_time():
    slow = render_cost(120, 600, fps=24, width=1920, height=1080)
    fast = render_cost(120, 10, fps=24, width=1920, height=1080)
    # Presentation duration is frames/fps and must NOT depend on wall time.
    assert slow["presentation_seconds"] == fast["presentation_seconds"] == 5.0
    assert slow["frames_per_wall_second"] == 0.2
    assert fast["frames_per_wall_second"] == 12.0


def test_render_cost_presentation_equals_frames_over_fps():
    frames, fps = 300, 30
    r = render_cost(frames, 42.5, fps=fps, width=1280, height=720)
    assert r["presentation_seconds"] == frames / fps == 10.0


def test_render_cost_carries_frame_authority_and_note():
    r = render_cost(120, 10, fps=24, width=1920, height=1080)
    assert r["authority"] == "frame"
    assert "simulation instant" in r["note"]
    assert "cost" in r["note"]


def test_render_cost_nonpositive_fps_raises():
    _expects_value_error(render_cost, 120, 10, fps=0, width=1920, height=1080)
    _expects_value_error(render_cost, 120, 10, fps=-24, width=1920, height=1080)


def test_render_cost_nonpositive_width_raises():
    _expects_value_error(render_cost, 120, 10, fps=24, width=0, height=1080)
    _expects_value_error(render_cost, 120, 10, fps=24, width=-5, height=1080)


def test_render_cost_nonpositive_height_raises():
    _expects_value_error(render_cost, 120, 10, fps=24, width=1920, height=0)
    _expects_value_error(render_cost, 120, 10, fps=24, width=1920, height=-5)


# --- build_report -----------------------------------------------------------


def _sample_report():
    interactive = summarise_samples(ONES_TO_TWENTY, warmup_drop=0)
    render = render_cost(120, 10, fps=24, width=1920, height=1080)
    world = {"actor_count": 16, "label": "sixteen-actor-sandbox"}
    environment = {"measured_utc": "2025-01-15T12:00:00Z", "host": "bench-a"}
    return build_report(interactive=interactive, render=render,
                        world=world, environment=environment)


def test_build_report_interactive_carries_measured_fields():
    report = _sample_report()
    assert report["interactive"]["measured_with_actor_count"] == 16
    assert report["interactive"]["measured_utc"] == "2025-01-15T12:00:00Z"


def test_build_report_structure_and_summary_intact():
    report = _sample_report()
    assert report["perf_report_version"] == PERF_REPORT_VERSION
    assert report["interactive"]["count"] == 20
    assert report["interactive"]["mean_s"] == 10.5
    assert report["render"]["authority"] == "frame"
    assert report["world"]["actor_count"] == 16
    assert report["environment"]["host"] == "bench-a"


def test_build_report_missing_world_actor_count_raises():
    interactive = summarise_samples(ONES_TO_TWENTY, warmup_drop=0)
    render = render_cost(120, 10, fps=24, width=1920, height=1080)
    _expects_value_error(build_report, interactive=interactive, render=render,
                         world={}, environment={"measured_utc": "X"})


def test_build_report_missing_environment_measured_utc_raises():
    interactive = summarise_samples(ONES_TO_TWENTY, warmup_drop=0)
    render = render_cost(120, 10, fps=24, width=1920, height=1080)
    _expects_value_error(build_report, interactive=interactive, render=render,
                         world={"actor_count": 16}, environment={})


def test_build_report_embedded_metadata_wins():
    interactive = summarise_samples(ONES_TO_TWENTY, warmup_drop=0)
    interactive["measured_with_actor_count"] = 999
    interactive["measured_utc"] = "2024-01-01T00:00:00Z"
    report = build_report(
        interactive=interactive,
        render=render_cost(120, 10, fps=24, width=1920, height=1080),
        world={"actor_count": 16},
        environment={"measured_utc": "2025-01-15T12:00:00Z"},
    )
    assert report["interactive"]["measured_with_actor_count"] == 999
    assert report["interactive"]["measured_utc"] == "2024-01-01T00:00:00Z"


# --- is_stale ---------------------------------------------------------------


def _stale_report(measured_actor_count):
    interactive = summarise_samples(ONES_TO_TWENTY, warmup_drop=0)
    interactive["measured_with_actor_count"] = measured_actor_count
    interactive["measured_utc"] = "2025-01-15T12:00:00Z"
    return build_report(
        interactive=interactive,
        render=render_cost(120, 10, fps=24, width=1920, height=1080),
        world={"actor_count": measured_actor_count},
        environment={"measured_utc": "2025-01-15T12:00:00Z"},
    )


def test_is_stale_true_when_world_doubled():
    # The trap from the past: 16 actors measured, 736 actors now.
    report = _stale_report(16)
    assert is_stale(report, 32, tolerance_fraction=0.25) is True
    assert is_stale(report, 736, tolerance_fraction=0.25) is True


def test_is_stale_false_inside_tolerance():
    report = _stale_report(16)
    assert is_stale(report, 18, tolerance_fraction=0.25) is False  # +12.5%


def test_is_stale_false_at_exact_tolerance():
    report = _stale_report(16)
    # +25% growth is exactly the tolerance; "grown beyond" means strictly >.
    assert is_stale(report, 20, tolerance_fraction=0.25) is False


def test_is_stale_true_just_beyond_tolerance():
    report = _stale_report(16)
    assert is_stale(report, 21, tolerance_fraction=0.25) is True  # +31.25%


def test_is_stale_false_when_world_shrank():
    report = _stale_report(16)
    assert is_stale(report, 15, tolerance_fraction=0.25) is False
    assert is_stale(report, 16, tolerance_fraction=0.25) is False


def test_is_stale_zero_tolerance_any_growth_is_stale():
    report = _stale_report(16)
    assert is_stale(report, 17, tolerance_fraction=0.0) is True
    assert is_stale(report, 16, tolerance_fraction=0.0) is False


# --- write_report -----------------------------------------------------------


def test_write_report_roundtrips_and_returns_path():
    report = _sample_report()
    tmp = tempfile.mkdtemp(prefix="perf_report_test_")
    try:
        out = write_report(report, os.path.join(tmp, "perf.json"))
        assert isinstance(out, Path)
        assert out.exists()
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded == report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_write_report_is_deterministic_bytes():
    report = _sample_report()
    tmp = tempfile.mkdtemp(prefix="perf_report_test_")
    try:
        a = write_report(report, os.path.join(tmp, "a.json"))
        b = write_report(report, os.path.join(tmp, "b.json"))
        assert a.read_bytes() == b.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_full_pipeline_stale_interactive_number_is_detectable():
    # Honesty end-to-end: a report measured with 16 actors, later checked
    # against the 736-actor world, is stale by code -- no reader memory needed.
    report = _stale_report(16)
    assert is_stale(report, 736, tolerance_fraction=0.1) is True
    # And a spiky interactive session must never classify as realtime just
    # because its mean is fine: p95 felt rate 4 fps vs target 20 -> slow.
    s = summarise_samples(SPIKY, warmup_drop=0)
    assert classify(realtime_ratio(s, target_fps=20)) == "slow"


# --- geometry budget --------------------------------------------------------

# The realistic world this pass ships.  Per-instance triangle figures are the
# committed pass targets stated in GEOMETRY_BUDGET's notes; only the tree
# figure (488 worst-case maple tris) is re-derived geometry (tree_mesh.py).
# Hand totals: buildings 252*800=201600, trees 240*488=117120,
# backdrop 100*12=1200, dressing 1816*150=272400, vehicles 150*1500=225000,
# crowd 65*3000=195000; grand total 1,012,320 against ceiling 2,000,000.
REALISTIC_WORLD = {
    "buildings": {"instances": 252, "triangles_per_instance": 800},
    "trees": {"instances": 240, "triangles_per_instance": 488},
    "backdrop": {"instances": 100, "triangles_per_instance": 12},
    "dressing": {"instances": 1816, "triangles_per_instance": 150},
    "vehicles": {"instances": 150, "triangles_per_instance": 1500},
    "crowd": {"instances": 65, "triangles_per_instance": 3000},
}


def test_geometry_budget_covers_every_realistic_world_category():
    # The budget must name every category the realistic world carries, or an
    # unbudgeted category slips into the world unchecked.
    for name in REALISTIC_WORLD:
        assert name in GEOMETRY_BUDGET["categories"]


def test_within_budget_world_validates_clean():
    estimate = estimate_world_cost(REALISTIC_WORLD)
    assert estimate["grand_total_triangles"] == 1_012_320
    assert estimate["over_budget"] == []
    assert validate_budget(estimate) == []


def test_shares_sum_to_one_within_tolerance():
    estimate = estimate_world_cost(REALISTIC_WORLD)
    total = sum(cat["share"] for cat in estimate["categories"].values())
    assert abs(total - 1.0) < 1e-9


def test_over_budget_category_is_named():
    # Doubling dressing past its 400,000 line: 1816*2 = 3632 pieces at 150
    # tris -> 544,800 > 400,000.  Every other category stays inside its line.
    counts = dict(REALISTIC_WORLD)
    counts["dressing"] = {"instances": 3632, "triangles_per_instance": 150}
    estimate = estimate_world_cost(counts)
    assert "dressing" in estimate["over_budget"]
    problems = validate_budget(estimate)
    assert any("dressing" in p for p in problems)
    assert any("over budget" in p for p in problems)


def test_unbudgeted_category_is_refused():
    counts = dict(REALISTIC_WORLD)
    counts["pigeons"] = {"instances": 40, "triangles_per_instance": 60}
    estimate = estimate_world_cost(counts)
    problems = validate_budget(estimate)
    assert any("pigeons" in p for p in problems)
    assert any("not in GEOMETRY_BUDGET" in p for p in problems)


def test_negative_count_is_refused():
    counts = dict(REALISTIC_WORLD)
    counts["trees"] = {"instances": -3, "triangles_per_instance": 488}
    problems = validate_budget(estimate_world_cost(counts))
    assert any("trees" in p and "negative" in p for p in problems)


def test_non_integer_count_is_refused():
    counts = dict(REALISTIC_WORLD)
    counts["crowd"] = {"instances": 65.5, "triangles_per_instance": 3000}
    problems = validate_budget(estimate_world_cost(counts))
    assert any("crowd" in p and "integer" in p for p in problems)


def test_grand_total_over_ceiling_is_refused():
    # 20,000 vehicles * 1500 tris = 30,000,000, far past the 2,000,000
    # ceiling; the vehicles line (400,000) is overrun too, so expect both.
    counts = dict(REALISTIC_WORLD)
    counts["vehicles"] = {"instances": 20000, "triangles_per_instance": 1500}
    problems = validate_budget(estimate_world_cost(counts))
    assert any("ceiling" in p for p in problems)
    assert any("vehicles" in p for p in problems)


def test_budget_report_mentions_every_category():
    estimate = estimate_world_cost(REALISTIC_WORLD)
    text = budget_report(estimate)
    for name in REALISTIC_WORLD:
        assert name in text
    # And it is a table a reviewer can read: grand total vs ceiling present.
    assert "1,012,320" in text
    assert "2,000,000" in text


if __name__ == "__main__":
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print("PASS %s" % _name)
            except Exception as exc:  # noqa: BLE001 - standalone runner
                failures += 1
                print("FAIL %s: %r" % (_name, exc))
    print("%d test(s) run, %d failure(s)" %
          (sum(1 for k, v in globals().items()
               if k.startswith("test_") and callable(v)), failures))
    sys.exit(1 if failures else 0)
