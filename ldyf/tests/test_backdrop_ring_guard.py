"""``ldyf.backdrop`` ring guards: a negative margin and a ring inside the world.

Two defects this suite pins down, both found by an adversarial read of
``skirt_ring`` / ``backdrop_massing``:

* ``inner_margin_cm`` was taken on trust, so a NEGATIVE margin pulled the ring's
  inner radius *inside* the world bbox and let backdrop massing land inside the
  city.  Both builders now refuse it with ``ValueError``.
* the ring's inner boundary is a circle of radius
  ``half_diagonal_cm + inner_margin_cm``, i.e. the bbox circumcircle, which
  touches a rectangular world only at its corners.  ``ring_covers_rectangle``
  states the mechanical requirement (inner radius >= half-diagonal, so the
  circle contains the whole world rectangle) and ``validate_backdrop`` reports a
  ring that fails it.  The remaining circular-segment notches between a
  non-square rectangle's sides and the ring are documented: the ground plane
  owns that band, and the test below shows a point in a notch that neither the
  rectangle nor the ring covers.
"""
from __future__ import annotations

import math

import pytest

from ldyf.backdrop import (
    backdrop_massing,
    build_backdrop,
    point_in_ring,
    ring_covers_rectangle,
    skirt_ring,
    validate_backdrop,
    world_bounds,
)

# A deliberately NON-square world: 300 m x 100 m.  Its circumcircle touches the
# rectangle at the four corners only, which is what makes the notch visible.
RECT_POINTS = [(0.0, 0.0), (30000.0, 10000.0)]
SQUARE_POINTS = [(0.0, 0.0), (20000.0, 20000.0)]


def _spec(points) -> dict:
    return {"schema_version": "road_spec_v1",
            "edges": [{"id": "e0", "function": "normal",
                       "lanes": [{"id": "e0_0",
                                  "polyline": [{"x": float(x), "y": float(y),
                                                "z": 0.0}
                                               for x, y in points]}]}],
            "junctions": [], "counts": {}}


@pytest.fixture()
def rect_bounds() -> dict:
    return world_bounds(_spec(RECT_POINTS))


@pytest.fixture()
def square_bounds() -> dict:
    return world_bounds(_spec(SQUARE_POINTS))


def _hand_ring(bounds, inner_radius, outer_radius, segments=32):
    """A ring with an explicitly chosen inner radius (skirt_ring refuses < 0)."""
    cx, cy = bounds["centre_x"], bounds["centre_y"]
    two_pi = 2.0 * math.pi
    quads = []
    for i in range(segments):
        a0 = two_pi * i / segments
        a1 = two_pi * (i + 1) / segments
        quads.append({"id": "skirt_%04d" % i, "corners": [
            [cx + inner_radius * math.cos(a0), cy + inner_radius * math.sin(a0)],
            [cx + inner_radius * math.cos(a1), cy + inner_radius * math.sin(a1)],
            [cx + outer_radius * math.cos(a1), cy + outer_radius * math.sin(a1)],
            [cx + outer_radius * math.cos(a0), cy + outer_radius * math.sin(a0)],
        ]})
    return quads


# --- F2a: a negative margin is refused --------------------------------------


def test_skirt_ring_refuses_negative_inner_margin(rect_bounds):
    half = rect_bounds["half_diagonal_cm"]
    for bad in (-1.0, -0.001, -half):
        with pytest.raises(ValueError) as err:
            skirt_ring(rect_bounds, inner_margin_cm=bad,
                       outer_radius_cm=half * 5.0, segments=8)
        assert "inner_margin_cm" in str(err.value)
    # Zero and positive margins are still accepted (the default path).
    assert len(skirt_ring(rect_bounds, inner_margin_cm=0.0,
                          outer_radius_cm=half * 5.0, segments=8)) == 8
    assert len(skirt_ring(rect_bounds, inner_margin_cm=5000.0,
                          outer_radius_cm=half * 5.0, segments=8)) == 8


def test_backdrop_massing_refuses_negative_inner_margin(rect_bounds):
    ok = dict(rings=2, per_ring=4, min_h_cm=10000.0, max_h_cm=20000.0,
              ring_gap_cm=10000.0, seed=1)
    with pytest.raises(ValueError) as err:
        backdrop_massing(rect_bounds, **{**ok, "inner_margin_cm": -1.0})
    assert "inner_margin_cm" in str(err.value)
    with pytest.raises(ValueError):
        backdrop_massing(rect_bounds, **{**ok, "inner_margin_cm": -5000.0})
    # The positive path is untouched.
    assert len(backdrop_massing(rect_bounds, **{**ok,
                                                "inner_margin_cm": 5000.0})) == 8


def test_build_backdrop_propagates_the_refusal():
    """build_backdrop forwards inner_margin_cm to both builders."""
    with pytest.raises(ValueError) as err:
        build_backdrop(_spec(RECT_POINTS), inner_margin_cm=-1.0, segments=8,
                       rings=2, per_ring=4, min_h_cm=10000.0,
                       max_h_cm=20000.0, ring_gap_cm=10000.0)
    assert "inner_margin_cm" in str(err.value)


# --- F2b: the ring must reach the world rectangle ---------------------------


def test_ring_covers_rectangle_needs_the_half_diagonal(rect_bounds):
    half = rect_bounds["half_diagonal_cm"]
    assert ring_covers_rectangle(rect_bounds, half)
    assert ring_covers_rectangle(rect_bounds, half * 1.5)
    assert not ring_covers_rectangle(rect_bounds, half - 1000.0)
    assert not ring_covers_rectangle(rect_bounds, half * 0.999)
    assert not ring_covers_rectangle(rect_bounds, 0.0)


def test_ring_covers_rectangle_uses_the_bbox_not_a_cached_half_diagonal(
        square_bounds):
    """The threshold is hypot(w, h) / 2 for whatever rectangle is passed in."""
    w = square_bounds["max_x"] - square_bounds["min_x"]
    h = square_bounds["max_y"] - square_bounds["min_y"]
    half = math.hypot(w, h) / 2.0
    assert square_bounds["half_diagonal_cm"] == round(half, 3)
    assert ring_covers_rectangle(square_bounds, half + 0.01)
    assert not ring_covers_rectangle(square_bounds, half - 1.0)


def test_skirt_ring_with_a_non_negative_margin_covers_the_rectangle(rect_bounds):
    half = rect_bounds["half_diagonal_cm"]
    for margin in (0.0, 5000.0):
        ring = skirt_ring(rect_bounds, inner_margin_cm=margin,
                          outer_radius_cm=half * 2.6, segments=64)
        inner = min(math.hypot(c[0] - rect_bounds["centre_x"],
                               c[1] - rect_bounds["centre_y"])
                    for q in ring for c in q["corners"])
        assert ring_covers_rectangle(rect_bounds, inner), margin


def test_a_non_square_world_leaves_a_notch_the_ring_cannot_cover(rect_bounds):
    """The documented limitation: the ground owns the band the circle misses.

    This point is outside the world rectangle (it is further east than max_x)
    and inside the ring's inner circle, so no skirt quad and no ground quad
    covers it -- exactly the circular-segment notch the module note describes.
    """
    half = rect_bounds["half_diagonal_cm"]
    ring = skirt_ring(rect_bounds, inner_margin_cm=0.0,
                      outer_radius_cm=half * 2.6, segments=64)
    x = rect_bounds["centre_x"] + half * 0.99
    y = rect_bounds["centre_y"]
    assert x > rect_bounds["max_x"]
    assert not point_in_ring(rect_bounds, ring, x, y)
    # ... and the ring still passes the mechanical check, because the check is
    # about not cutting a corner off the world, not about filling the notch.
    assert ring_covers_rectangle(rect_bounds, half)


def test_validate_backdrop_accepts_a_default_build(rect_bounds):
    doc = build_backdrop(_spec(RECT_POINTS))
    assert doc["bounds"] == rect_bounds
    assert validate_backdrop(doc) == []


def test_validate_backdrop_reports_a_ring_inside_the_rectangle(rect_bounds):
    half = rect_bounds["half_diagonal_cm"]
    doc = build_backdrop(_spec(RECT_POINTS))
    doc["skirt"] = _hand_ring(rect_bounds, inner_radius=half * 0.5,
                              outer_radius=half * 2.6)
    problems = validate_backdrop(doc)
    assert len(problems) == 1
    assert "half_diagonal" in problems[0]


def test_validate_backdrop_agrees_with_ring_covers_rectangle(rect_bounds):
    half = rect_bounds["half_diagonal_cm"]
    doc = build_backdrop(_spec(RECT_POINTS))
    for inner in (half * 0.5, half * 0.99, half, half * 1.2):
        doc["skirt"] = _hand_ring(rect_bounds, inner_radius=inner,
                                  outer_radius=half * 2.6)
        # a covering ring yields ZERO problems; comparing len(...) to []
        # made the covered case unpassable regardless of the module
        expected = 0 if ring_covers_rectangle(rect_bounds, inner) else 1
        assert len(validate_backdrop(doc)) == expected, inner


def test_validate_backdrop_has_nothing_to_check_without_a_ring():
    """No bounds / no skirt: those are the builders' ValueError paths."""
    assert validate_backdrop({}) == []
    assert validate_backdrop({"bounds": {}, "skirt": []}) == []
