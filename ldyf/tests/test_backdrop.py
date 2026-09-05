"""``ldyf.backdrop`` -- backdrop_spec_v1: ground skirt, skyline massing, fog.

The road spec used here is hand-built the same way ``test_city_layout`` builds
its lattice spec (plain dicts, no sumolib), plus one **internal** edge that
sticks out beyond the lattice.  That edge is what proves ``world_bounds``
includes every edge regardless of ``function``.

Coverage:

* determinism -- the same road spec builds a byte-identical backdrop twice;
* world bounds -- exact bbox/centre/half-diagonal, internal edges included;
* ring closure -- probes just outside the inner radius in the four side
  directions AND the four diagonal corner directions all land inside the ring
  (this is exactly where a four-side-quad frame used to leave corner gaps);
  the same probes just inside the inner radius / outside the outer radius are
  correctly reported as not covered;
* shared corners -- adjacent ring quads share their radial edge endpoints
  exactly, including the last -> first seam;
* consistent winding -- every quad has the same signed area orientation;
* massing -- no entry lands inside the world expanded by inner_margin_cm,
  heights strictly fall with ring index, counts and ids are right, the same
  seed reproduces the same skyline, angles are NOT evenly spaced (real
  variance and a guaranteed large empty band between focal arcs), widths span
  the stated range (slender towers and broad slabs both occur), yaw is
  independent of the block's bearing, a deterministic fraction of blocks
  carries a narrower ``step`` top box while the rest do not, and full
  silhouettes (base + step) still step down with ring index;
* atmosphere -- view distance derives from half_diagonal_cm;
* every required ``ValueError`` path.
"""

from __future__ import annotations

import json
import math

import pytest

from ldyf.backdrop import (
    BACKDROP_VERSION,
    atmosphere,
    backdrop_massing,
    build_backdrop,
    point_in_ring,
    skirt_ring,
    world_bounds,
)


def _pt(x: float, y: float) -> dict:
    return {"x": float(x), "y": float(y), "z": 0.0}


def make_world_spec() -> dict:
    """3x3 junction lattice spanning [0, 40000]^2 plus an outlying internal
    edge, so the true world bbox is [-20000, 40000]^2."""
    pos = {f"J{c}_{r}": _pt(c * 20000.0, r * 20000.0)
           for c in range(3) for r in range(3)}
    junctions = [{"id": jid, "type": "priority", "position": pos[jid],
                  "polygon": None, "incoming_edge_ids": []}
                 for jid in sorted(pos)]
    edges: list[dict] = []

    def add_edge(eid: str, a: str, b: str, function: str = "normal") -> None:
        edges.append({"id": eid, "from_junction": a, "to_junction": b,
                      "function": function, "priority": 1,
                      "lanes": [{"id": f"{eid}_0", "index": 0,
                                 "width_cm": 200.0,
                                 "width_cm_effective": 200.0,
                                 "width_source": "attribute",
                                 "speed_mps": 13.89, "length_m": 200.0,
                                 "allow": None, "disallow": None,
                                 "polyline": [dict(pos[a]), dict(pos[b])]}]})

    for r in range(3):
        for c in range(2):
            add_edge(f"H{r}_{c}", f"J{c}_{r}", f"J{c + 1}_{r}")
    for c in range(3):
        for r in range(2):
            add_edge(f"V{c}_{r}", f"J{c}_{r}", f"J{c}_{r + 1}")
    # Internal edge: function != normal, half outside the lattice bbox.
    edges.append({"id": "I0", "from_junction": "none", "to_junction": "none",
                  "function": "internal", "priority": 1,
                  "lanes": [{"id": "I0_0", "index": 0,
                             "width_cm": 200.0, "width_cm_effective": 200.0,
                             "width_source": "attribute",
                             "speed_mps": 0.0, "length_m": 400.0,
                             "allow": None, "disallow": None,
                             "polyline": [_pt(-20000.0, -20000.0),
                                          _pt(-20000.0, 20000.0)]}]})
    return {"schema_version": "road_spec_v1", "edges": edges,
            "junctions": junctions,
            "counts": {"edges": len(edges), "junctions": len(junctions)}}


@pytest.fixture()
def spec() -> dict:
    return make_world_spec()


@pytest.fixture()
def bounds(spec) -> dict:
    return world_bounds(spec)


# --- world bounds -----------------------------------------------------------


def test_world_bounds_bbox_centre_half_diagonal(spec, bounds):
    # min x/y come from the internal edge, max from the lattice grid.
    assert bounds["min_x"] == -20000.0
    assert bounds["max_x"] == 40000.0
    assert bounds["min_y"] == -20000.0
    assert bounds["max_y"] == 40000.0
    assert bounds["centre_x"] == 10000.0
    assert bounds["centre_y"] == 10000.0
    expected_half = math.hypot(30000.0, 30000.0) / 1.0 * 1.0
    assert bounds["half_diagonal_cm"] == round(expected_half, 3)


def test_world_bounds_includes_internal_edges(spec):
    # Same spec minus the internal edge must be strictly smaller.
    stripped = make_world_spec()
    stripped["edges"] = [e for e in stripped["edges"] if e["id"] != "I0"]
    assert world_bounds(stripped)["min_x"] > world_bounds(spec)["min_x"]
    assert world_bounds(stripped)["min_y"] > world_bounds(spec)["min_y"]


def test_world_bounds_empty_spec_is_degenerate_zero_bbox():
    empty = {"schema_version": "road_spec_v1", "edges": [], "junctions": []}
    b = world_bounds(empty)
    assert b == {"min_x": 0.0, "min_y": 0.0, "max_x": 0.0, "max_y": 0.0,
                 "centre_x": 0.0, "centre_y": 0.0, "half_diagonal_cm": 0.0}


# --- skirt ring: closure and shared corners ---------------------------------


def _ring(bounds, margin=0.0, outer=None, segments=36):
    outer = outer or (bounds["half_diagonal_cm"] * 5.0)
    return skirt_ring(bounds, inner_margin_cm=margin,
                      outer_radius_cm=outer, segments=segments)


def _probe(bounds, deg: float, radius: float):
    rad = math.radians(deg)
    return (bounds["centre_x"] + radius * math.cos(rad),
            bounds["centre_y"] + radius * math.sin(rad))


def test_ring_is_a_ring_bounds(bounds):
    ring = _ring(bounds)
    assert len(ring) == 36
    assert [q["id"] for q in ring] == sorted(q["id"] for q in ring)
    for q in ring:
        assert len(q["corners"]) == 4
        assert all(len(c) == 2 for c in q["corners"])


def test_ring_covers_side_and_corner_directions_just_outside(bounds):
    """No gaps anywhere: probe the four side directions and the four diagonal
    corner directions just beyond the ring's inner radius, at mid ring, and
    just inside the outer radius.  Every probe must be covered -- the diagonal
    corner directions are where a naive four-side frame used to leak."""
    margin = 0.0
    inner = bounds["half_diagonal_cm"] + margin
    outer = bounds["half_diagonal_cm"] * 5.0
    ring = _ring(bounds, margin=margin, outer=outer)
    # The ring is built from straight-edged quads, so its outer boundary is a
    # chord, not an arc: at mid-segment angles it sits inside the nominal outer
    # radius by cos(pi / segments). Probing AT outer_radius therefore reports a
    # "gap" that is really the inscribed-polygon inset, and probing beyond it is
    # outside the ring by definition. The contract that matters is that
    # everything from the inner radius out to the INSCRIBED outer radius is
    # covered from every direction -- including the diagonals, where a naive
    # four-sided frame used to leak.
    segments = 36
    inscribed = outer * math.cos(math.pi / segments)
    span = inscribed - inner
    for deg in range(0, 360, 5):
        for frac in (1e-6, 0.25, 0.5, 0.75, 1.0 - 1e-6):
            r = inner + span * frac
            x, y = _probe(bounds, float(deg), r)
            assert point_in_ring(bounds, ring, x, y), \
                f"gap at direction {deg} deg, radius {r:.1f}"


def test_ring_hole_and_outside_are_not_covered(bounds):
    margin = 0.0
    inner = bounds["half_diagonal_cm"] + margin
    outer = bounds["half_diagonal_cm"] * 5.0
    ring = _ring(bounds, margin=margin, outer=outer)
    for deg in (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0):
        # Inside the ring's own inner hole: no ground quad there.
        x, y = _probe(bounds, deg, inner - 1000.0)
        assert not point_in_ring(bounds, ring, x, y)
        # Beyond the outer radius: no ground quad there either.
        x, y = _probe(bounds, deg, outer + 1000.0)
        assert not point_in_ring(bounds, ring, x, y)
    # And a point in the middle of the world is not in the ring.
    assert not point_in_ring(bounds, ring,
                             bounds["centre_x"], bounds["centre_y"])


def test_adjacent_ring_quads_share_corners_exactly(bounds):
    """Quad i's outer-right corner == quad i+1's outer-left corner, and the
    same for the inner pair -- including the last -> first seam."""
    ring = _ring(bounds)
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        # skirt_ring emits corners as
        # [inner_start, inner_end, outer_end, outer_start], so the edge a
        # neighbour shares is inner_end -> inner_start and
        # outer_end -> outer_start. Asserting any other index pair tests the
        # winding convention rather than closure, and closure is the point.
        assert ring[i]["corners"][1] == ring[j]["corners"][0], \
            f"inner seam {ring[i]['id']} -> {ring[j]['id']}"
        assert ring[i]["corners"][2] == ring[j]["corners"][3], \
            f"outer seam {ring[i]['id']} -> {ring[j]['id']}"


def test_ring_quads_wound_consistently(bounds):
    ring = _ring(bounds)
    areas = []
    for q in ring:
        c = q["corners"]
        area = 0.0
        for k in range(4):
            ax, ay = c[k]
            bx, by = c[(k + 1) % 4]
            area += ax * by - ay * bx
        areas.append(area)
    assert all(a != 0.0 for a in areas)
    assert all((a > 0) == (areas[0] > 0) for a in areas)


# --- massing ----------------------------------------------------------------

# Keyword set shared by every massing test that needs the default variation.
MASSING_KW = dict(rings=3, per_ring=14, min_h_cm=10000.0, max_h_cm=40000.0,
                  ring_gap_cm=20000.0)


def test_massing_never_lands_inside_world(bounds):
    margin = 5000.0
    m = backdrop_massing(bounds, rings=3, per_ring=8, min_h_cm=10000.0,
                         max_h_cm=40000.0, ring_gap_cm=20000.0, seed=7,
                         inner_margin_cm=margin)
    lo_x, hi_x = bounds["min_x"] - margin, bounds["max_x"] + margin
    lo_y, hi_y = bounds["min_y"] - margin, bounds["max_y"] + margin
    for entry in m:
        assert not (lo_x <= entry["x"] <= hi_x and lo_y <= entry["y"] <= hi_y), \
            entry["id"]


def test_massing_heights_fall_with_ring_index(bounds):
    """Ring r+1 is strictly lower than ring r: the tallest building of the
    farther ring is shorter than the shortest building of the nearer ring."""
    m = backdrop_massing(bounds, rings=3, per_ring=8, min_h_cm=10000.0,
                         max_h_cm=40000.0, ring_gap_cm=20000.0, seed=7)
    heights = {r: [e["h_cm"] for e in m if e["ring"] == r]
               for r in range(3)}
    for r in range(2):
        assert max(heights[r + 1]) < min(heights[r]), \
            f"ring {r + 1} not strictly lower than ring {r}"


def test_massing_counts_ids_and_fields(bounds):
    rings, per_ring = 3, 8
    m = backdrop_massing(bounds, rings=rings, per_ring=per_ring,
                         min_h_cm=10000.0, max_h_cm=40000.0,
                         ring_gap_cm=20000.0, seed=7)
    assert len(m) == rings * per_ring
    assert [e["id"] for e in m] == sorted(e["id"] for e in m)
    assert sorted({e["ring"] for e in m}) == [0, 1, 2]
    base = {"id", "x", "y", "yaw_deg", "w_cm", "d_cm", "h_cm", "ring"}
    step_keys = {"step_w_cm", "step_d_cm", "step_h_cm"}
    for e in m:
        assert set(e) == base | step_keys
        assert 0.0 <= e["yaw_deg"] < 360.0
        assert e["h_cm"] > 0.0 and e["w_cm"] > 0.0 and e["d_cm"] > 0.0
        # step keys are always present; either all null (no top box) or all
        # positive with a strictly narrower footprint than the base box.
        if e["step_h_cm"] is None:
            assert e["step_w_cm"] is None and e["step_d_cm"] is None
        else:
            assert 0.0 < e["step_h_cm"]
            assert 0.0 < e["step_w_cm"] < e["w_cm"]
            assert 0.0 < e["step_d_cm"] < e["d_cm"]


def test_massing_same_seed_reproducible_different_seed_differs(bounds):
    kw = dict(rings=3, per_ring=6, min_h_cm=10000.0, max_h_cm=40000.0,
              ring_gap_cm=20000.0)
    a = backdrop_massing(bounds, seed=11, **kw)
    b = backdrop_massing(bounds, seed=11, **kw)
    c = backdrop_massing(bounds, seed=12, **kw)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert json.dumps(a, sort_keys=True) != json.dumps(c, sort_keys=True)


# --- massing variation: angles, widths, yaw, steps --------------------------


def _bearing_deg(bounds, entry: dict) -> float:
    """Bearing of a massing entry from the world centre, degrees in [0, 360)."""
    return math.degrees(math.atan2(
        entry["y"] - bounds["centre_y"], entry["x"] - bounds["centre_x"])) \
        % 360.0


def _circ_diff_deg(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _sorted_gaps(entries: list[dict], bounds) -> list[float]:
    """Circular successive gaps (radians) between a ring's sorted bearings."""
    angles = sorted(_bearing_deg(bounds, e) * math.pi / 180.0 for e in entries)
    n = len(angles)
    gaps = [(angles[(k + 1) % n] - angles[k]) % (2.0 * math.pi)
            for k in range(n)]
    assert math.isclose(sum(gaps), 2.0 * math.pi, rel_tol=1e-9)
    return gaps


def test_massing_angles_not_evenly_spaced(bounds):
    """No picket fence: the per-ring angular gaps must show real variance and
    a guaranteed wide empty band between the focal arcs.  With the defaults
    (3 focal arcs, cluster_fill 0.55) each arc keeps its outer margins empty,
    so every ring has 3 angular gaps of at least arc - window = 54 deg while
    the mean slot is 360/14 ~= 25.7 deg -- a distribution an even grid can
    never produce (an even grid would make every gap equal the mean)."""
    m = backdrop_massing(bounds, seed=7, **MASSING_KW)
    gaps = []
    for r in range(3):
        gaps.extend(_sorted_gaps([e for e in m if e["ring"] == r], bounds))
    mean_gap = 2.0 * math.pi / MASSING_KW["per_ring"]
    assert max(gaps) > 2.05 * mean_gap, "no nearly-empty arc between clumps"
    assert min(gaps) < mean_gap, "no dense clump"
    avg = sum(gaps) / len(gaps)
    var = sum((g - avg) ** 2 for g in gaps) / len(gaps)
    assert var ** 0.5 > 0.3 * mean_gap, "spacing distribution has no variance"


def test_massing_widths_span_stated_range(bounds):
    """Widths span [0.2, 1.6] x height by default: slender towers AND broad
    slabs both occur, and the observed factor range is wide (the old code
    pinned every block inside a 0.5-0.85 x height band)."""
    m = backdrop_massing(bounds, seed=7, **MASSING_KW)
    ratios = [e["w_cm"] / e["h_cm"] for e in m]
    assert min(ratios) < 0.65, "no slender tower occurred"
    assert max(ratios) > 1.0, "no broad slab occurred"
    assert max(ratios) - min(ratios) > 0.7, "width factors barely vary"
    assert max(ratios) <= 1.6 + 1e-6 and min(ratios) >= 0.2 - 1e-6


def test_massing_yaw_independent_of_bearing(bounds):
    """Yaw must not be the block's bearing (that would present one radially
    aligned face and make the ring look machined).  Yaw is drawn from its own
    digest slice, so it is independent of the bearing: circular offsets spread
    across the full circle, mean offset near 90 deg, and linear correlation
    with the bearing is ~0.  An implementation that set yaw == bearing fails
    every one of these assertions."""
    m = backdrop_massing(bounds, seed=7, **MASSING_KW)
    diffs = [_circ_diff_deg(e["yaw_deg"], _bearing_deg(bounds, e)) for e in m]
    assert min(diffs) > 0.01, "some block's yaw equals its bearing"
    assert max(diffs) > 90.0
    mean_diff = sum(diffs) / len(diffs)
    assert 60.0 < mean_diff < 120.0
    n = len(m)
    bearings = [_bearing_deg(bounds, e) for e in m]
    b_mean = sum(bearings) / n
    y_mean = sum(e["yaw_deg"] for e in m) / n
    num = sum((b - b_mean) * (e["yaw_deg"] - y_mean)
              for b, e in zip(bearings, m))
    den = (sum((b - b_mean) ** 2 for b in bearings)
           * sum((e["yaw_deg"] - y_mean) ** 2 for e in m)) ** 0.5
    assert den > 0.0
    assert abs(num / den) < 0.35, "yaw correlates with bearing"


def test_massing_steps_present_and_absent(bounds):
    """A deterministic fraction (default 0.4) of blocks carries a narrower
    step box on top; the rest carry all-null step keys.  Step footprints must
    be strictly inside the base footprint."""
    m = backdrop_massing(bounds, seed=7, **MASSING_KW)
    stepped = [e for e in m if e["step_h_cm"] is not None]
    plain = [e for e in m if e["step_h_cm"] is None]
    assert stepped and plain, "step mix missing at the default fraction"
    assert len(stepped) < len(m)
    for e in stepped:
        assert e["step_w_cm"] is not None and e["step_d_cm"] is not None
        assert 0.0 < e["step_w_cm"] < e["w_cm"]
        assert 0.0 < e["step_d_cm"] < e["d_cm"]
        assert e["step_h_cm"] > 0.0
    for e in plain:
        assert e["step_w_cm"] is None and e["step_d_cm"] is None
        assert e["step_h_cm"] is None


def test_massing_silhouette_tops_fall_with_ring_index(bounds):
    """Base heights fall with ring index (tested above); steps must not undo
    that.  Step height is capped at the ring's own band top, which sits below
    the nearer ring's shortest plain box, so full silhouettes (base + step)
    still step strictly down ring by ring."""
    m = backdrop_massing(bounds, seed=7, **MASSING_KW)
    tops: dict[int, list[float]] = {}
    for e in m:
        tops.setdefault(e["ring"], []).append(
            e["h_cm"] + (e["step_h_cm"] if e["step_h_cm"] is not None else 0.0))
    for r in range(2):
        assert max(tops[r + 1]) < min(tops[r]), \
            f"silhouette tops of ring {r + 1} not strictly below ring {r}"


# --- atmosphere -------------------------------------------------------------


def test_atmosphere_view_distance_derived_from_half_diagonal(bounds):
    a = atmosphere(bounds)
    half = bounds["half_diagonal_cm"]
    assert a["view_distance_cm"] == round(5.0 * half, 3)
    assert a["start_distance_cm"] == round(1.6 * half, 3)
    assert a["fog_density"] > 0.0
    assert set(a) == {"fog_density", "fog_height_falloff",
                      "start_distance_cm", "view_distance_cm",
                      "sky_influence"}


# --- build_backdrop and determinism -----------------------------------------


def test_build_backdrop_schema_and_counts(bounds, spec):
    out = build_backdrop(spec, outer_radius_cm=200000.0, segments=24,
                         rings=2, per_ring=5, min_h_cm=5000.0,
                         max_h_cm=20000.0, ring_gap_cm=15000.0, seed=3)
    assert out["schema_version"] == BACKDROP_VERSION
    assert out["bounds"] == bounds
    assert len(out["skirt"]) == 24
    assert len(out["massing"]) == 10
    assert out["counts"] == {"skirt_quads": 24, "massing_entries": 10,
                             "rings": 2, "per_ring": 5}
    assert out["atmosphere"] == atmosphere(bounds)
    assert set(out) == {"schema_version", "bounds", "skirt", "massing",
                        "atmosphere", "counts"}


def test_build_backdrop_defaults_run_and_are_consistent(spec):
    out = build_backdrop(spec)
    assert out["counts"]["skirt_quads"] == len(out["skirt"])
    assert out["counts"]["massing_entries"] == len(out["massing"])
    assert out["counts"]["massing_entries"] == \
        out["counts"]["rings"] * out["counts"]["per_ring"]


def test_determinism_byte_identical(spec):
    first = build_backdrop(spec, seed=9, outer_radius_cm=200000.0,
                           segments=32, rings=3, per_ring=7,
                           min_h_cm=8000.0, max_h_cm=24000.0,
                           ring_gap_cm=16000.0)
    second = build_backdrop(spec, seed=9, outer_radius_cm=200000.0,
                            segments=32, rings=3, per_ring=7,
                            min_h_cm=8000.0, max_h_cm=24000.0,
                            ring_gap_cm=16000.0)
    a = json.dumps(first, sort_keys=True)
    b = json.dumps(second, sort_keys=True)
    assert a == b
    assert a.encode("utf-8") == b.encode("utf-8")


# --- ValueError paths -------------------------------------------------------


def test_value_errors_skirt_ring(bounds):
    half = bounds["half_diagonal_cm"]
    ok = dict(inner_margin_cm=0.0, outer_radius_cm=half * 5.0, segments=8)
    for bad in ("segments", "outer_radius_cm", "outer_radius_cm"):
        pass  # parametrised below; keep loop for lint symmetry
    with pytest.raises(ValueError):
        skirt_ring(bounds, **{**ok, "segments": 0})
    with pytest.raises(ValueError):
        skirt_ring(bounds, **{**ok, "segments": -3})
    with pytest.raises(ValueError):
        skirt_ring(bounds, **{**ok, "outer_radius_cm": 0.0})
    with pytest.raises(ValueError):
        skirt_ring(bounds, **{**ok, "outer_radius_cm": half * 0.5})
    # outer radius smaller than the ring's own inner radius (margin pushes the
    # inner circle out past the requested outer radius).
    with pytest.raises(ValueError):
        skirt_ring(bounds, inner_margin_cm=20000.0,
                   outer_radius_cm=half + 10000.0, segments=8)


def test_value_errors_massing(bounds):
    ok = dict(rings=2, per_ring=4, min_h_cm=10000.0, max_h_cm=20000.0,
              ring_gap_cm=10000.0, seed=1)
    with pytest.raises(ValueError):
        backdrop_massing(bounds, **{**ok, "rings": 0})
    with pytest.raises(ValueError):
        backdrop_massing(bounds, **{**ok, "per_ring": -1})
    with pytest.raises(ValueError):
        backdrop_massing(bounds, **{**ok, "ring_gap_cm": 0.0})
    with pytest.raises(ValueError):
        backdrop_massing(bounds, **{**ok, "max_h_cm": 5000.0})
    # New variation knobs are validated with the same contract.
    with pytest.raises(ValueError):
        backdrop_massing(bounds, **{**ok, "cluster_centres": 0})
    with pytest.raises(ValueError):
        backdrop_massing(bounds, **{**ok, "cluster_centres": 99})
    with pytest.raises(ValueError):
        backdrop_massing(bounds, **{**ok, "cluster_fill": 1.0})
    with pytest.raises(ValueError):
        backdrop_massing(bounds, **{**ok, "width_max_frac": 0.1})
    with pytest.raises(ValueError):
        backdrop_massing(bounds, **{**ok, "depth_min_frac": 0.0})
    with pytest.raises(ValueError):
        backdrop_massing(bounds, **{**ok, "step_fraction": 1.5})
    with pytest.raises(ValueError):
        backdrop_massing(bounds, **{**ok, "step_scale": -1.0})
