"""Tests for the instrument the building decision rests on.

The gate attacker in run ``p2p_atk`` ranked this first, and it was right: no
test imported ``ldyf.unreal.ldyf_sgd_editor``, and a grep for
``facade_coverage`` in this directory returned nothing. The single number used
to decide whether a building family is real or hollow had no coverage in either
direction, which is how two false "visual pass" reports reached the Director.

The module imports ``unreal``, so it is loaded with a stub in ``sys.modules``,
the technique ``test_lighting_readback_compare.py`` already uses here.

Every case below is one of the concrete attacks the two adversaries described,
with the numbers they used.
"""
from __future__ import annotations

import sys
import types

import pytest


def _editor():
    """Import the editor driver with ``unreal`` stubbed out."""
    if "unreal" not in sys.modules:
        sys.modules["unreal"] = types.ModuleType("unreal")
    import ldyf.unreal.ldyf_sgd_editor as drv
    return drv


# a 1200 x 1200 cm footprint, the production minimum group dimension
FOOT_LO = (0.0, 0.0)
FOOT_HI = (1200.0, 1200.0)
SIDE = 1200.0


def face(intervals_x=(), intervals_y=(), *, xs=(0.0,), ys=(0.0,)):
    return {"ix": list(intervals_x), "iy": list(intervals_y),
            "x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys)}


def tiled(axis="x"):
    """Three 400 cm modules tiling a 1200 cm side: a genuinely solid face."""
    iv = [(0.0, 400.0), (400.0, 800.0), (800.0, 1200.0)]
    xs = (0.0, 400.0, 800.0)
    if axis == "x":
        return face(intervals_x=iv, xs=xs, ys=(0.0,))
    return face(intervals_y=iv, xs=(0.0,), ys=xs)


def four_solid_faces():
    return {0: tiled("x"), 1: tiled("y"), 2: tiled("x"), 3: tiled("y")}


# ---------------------------------------------------------------- the union
def test_union_counts_overlap_once():
    u = _editor()._union_length
    assert u([(0.0, 400.0), (400.0, 800.0)], (0.0, 1200.0)) == 800.0
    # the same wall built twice covers what one wall covers
    assert u([(0.0, 400.0)] * 5, (0.0, 1200.0)) == 400.0
    # partial overlap merges
    assert u([(0.0, 400.0), (200.0, 600.0)], (0.0, 1200.0)) == 600.0


def test_union_is_clipped_to_the_footprint():
    u = _editor()._union_length
    # a module overhanging both ends cannot buy more than the side
    assert u([(-500.0, 1700.0)], (0.0, 1200.0)) == 1200.0
    # and one entirely outside buys nothing
    assert u([(2000.0, 2400.0)], (0.0, 1200.0)) == 0.0


def test_union_handles_reversed_and_empty_intervals():
    u = _editor()._union_length
    assert u([(400.0, 0.0)], (0.0, 1200.0)) == 400.0
    assert u([], (0.0, 1200.0)) == 0.0
    assert u([(300.0, 300.0)], (0.0, 1200.0)) == 0.0


# -------------------------------------------------------- the attacks, scored
def test_a_genuinely_tiled_building_passes():
    drv = _editor()
    worst, faces_min = drv.worst_face_coverage(
        {0: four_solid_faces(), 325: four_solid_faces()}, FOOT_LO, FOOT_HI)
    assert faces_min == 4
    assert worst == pytest.approx(1.0)
    assert worst >= drv.FACADE_COVERAGE_MIN


def test_four_modules_stacked_at_one_point_fail():
    """The p2p_atk construction: 4 modules at the SAME (x, y), yaws 0/90/180/270.

    Under the previous instrument each face got ``side = min(ext_x, ext_y)`` and
    a summed width >= that side, scoring >= 1.0, and the building was counted in
    ``solid_facades``: a 4-module-per-storey pole certified as a solid facade.
    """
    drv = _editor()
    one = (350.0, 850.0)        # a single 500 cm module at mid-side
    faces = {q: face(intervals_x=[one], intervals_y=[one]) for q in range(4)}
    worst, _ = drv.worst_face_coverage({0: faces}, FOOT_LO, FOOT_HI)
    assert worst == pytest.approx(500.0 / SIDE, abs=1e-6)
    assert worst < drv.FACADE_COVERAGE_MIN


def test_a_half_empty_face_plus_an_offset_copy_fails():
    """Offset 2.5 cm defeated the old 5 cm spot de-duplication and reached 0.85."""
    drv = _editor()
    half = [(0.0, 600.0), (2.5, 602.5)]
    faces = dict(four_solid_faces())
    faces[0] = face(intervals_x=half, xs=(0.0, 2.5))
    worst, _ = drv.worst_face_coverage({0: faces}, FOOT_LO, FOOT_HI)
    assert worst == pytest.approx(602.5 / SIDE, abs=1e-6)
    assert worst < drv.FACADE_COVERAGE_MIN


def test_doubling_a_wall_does_not_inflate_the_score():
    drv = _editor()
    doubled = dict(four_solid_faces())
    doubled[0] = face(intervals_x=tiled("x")["ix"] * 2,
                      xs=(0.0, 400.0, 800.0))
    worst, _ = drv.worst_face_coverage({0: doubled}, FOOT_LO, FOOT_HI)
    # exactly 1.0, not 2.0: coverage is a fraction of the side and cannot exceed it
    assert worst == pytest.approx(1.0)


def test_a_missing_side_scores_zero():
    drv = _editor()
    three = four_solid_faces()
    del three[2]
    worst, faces_min = drv.worst_face_coverage({0: three}, FOOT_LO, FOOT_HI)
    assert faces_min == 3
    assert worst == 0.0


def test_one_bad_floor_decides_the_building():
    drv = _editor()
    bad = {q: face(intervals_x=[(0.0, 200.0)], intervals_y=[(0.0, 200.0)])
           for q in range(4)}
    worst, _ = drv.worst_face_coverage(
        {0: four_solid_faces(), 325: four_solid_faces(), 650: bad},
        FOOT_LO, FOOT_HI)
    assert worst == pytest.approx(200.0 / SIDE, abs=1e-6)
    assert worst < drv.FACADE_COVERAGE_MIN


def test_a_lone_module_is_not_measured_against_the_short_side():
    """A non-square footprint is where the old lone-module rule did its damage.

    On a 3000 x 1200 building a single 1300 cm module facing along the LONG side
    used to be divided by 1200 and score > 1.0. It must be divided by 3000.
    """
    drv = _editor()
    lo, hi = (0.0, 0.0), (3000.0, 1200.0)
    # the two long faces hold ONE 1300 cm module; the two short faces are tiled
    lone = face(intervals_x=[(850.0, 2150.0)], xs=(1500.0,), ys=(0.0,))
    faces = {0: lone, 2: lone, 1: tiled("y"), 3: tiled("y")}
    worst, _ = drv.worst_face_coverage({0: faces}, lo, hi)
    assert worst == pytest.approx(1300.0 / 3000.0, abs=1e-6)
    assert worst < drv.FACADE_COVERAGE_MIN


def test_coverage_can_never_exceed_one():
    drv = _editor()
    greedy = {q: face(intervals_x=[(-5000.0, 5000.0)],
                      intervals_y=[(-5000.0, 5000.0)]) for q in range(4)}
    worst, _ = drv.worst_face_coverage({0: greedy}, FOOT_LO, FOOT_HI)
    assert worst == pytest.approx(1.0)


def test_no_faces_at_all_reports_nothing_rather_than_passing():
    drv = _editor()
    worst, faces_min = drv.worst_face_coverage({}, FOOT_LO, FOOT_HI)
    assert worst is None and faces_min is None


# ----------------------------------------------------- the height half of it
def test_the_gate_requires_height_and_wall_reach():
    """A facade score says nothing about height; both adversaries said so.

    This pins the thresholds that make a one-storey slab fail, so the pass
    condition cannot quietly lose them again.
    """
    drv = _editor()
    assert drv.HEIGHT_RATIO_MIN >= 0.90
    assert drv.WALL_REACH_MIN >= 0.90
    src = drv.measure.__doc__ or ""
    assert "union" in src.lower()
