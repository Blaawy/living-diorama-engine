"""Phase-? closure lane: ``ldyf.dressing`` (``dressing_v1``) road furniture.

The module derives painted lines, zebra stripes, signals, street trees and
closure props purely from the road spec dict. Tests use hand-built fixtures
(the ``_spec`` helper below) only -- no sumolib, no netconvert, no Unreal,
nothing read from disk. Every expected number below was derived by hand from
the fixture geometry; the arithmetic is spelled out in the docstrings.
"""

from __future__ import annotations

def _by_id(rows, suffix):
    """Rows are sorted by their STRING id, so "10" sorts before "2".  Every
    assertion below therefore selects by id instead of by list position."""
    hits = [r for r in rows if r["id"].endswith(suffix)]
    assert len(hits) == 1, "expected exactly one row ending %r, got %d" % (suffix, len(hits))
    return hits[0]


import json
import math

import pytest

from ldyf.dressing import (
    _dash,
    build_dressing,
    closure_props,
    crosswalk_stripes,
    is_car_lane,
    is_sidewalk_lane,
    lane_markings,
    lateral_normal,
    signal_placements,
    tree_slots,
)

# Fixture units are centimetres, like the module's own parameters. The layout
# convention mirrors a real SUMO net: lane index 0 is the rightmost lane of
# travel, so on a northbound two-car-lane edge the index-1 lane sits west of
# the index-0 lane and the lateral normal points west (-x).
#
# Bidirectional road ``EN`` (northbound) / ``ES`` (southbound) between
# J0=(0,0) and J1=(0,1000): two car lanes of 400 cm each.  EN occupies the
# east half of the corridor (inner lane edge at x=0), ES the west half.
#   EN_0 idx0 centre x=600 | EN_1 idx1 centre x=200   (EN spans x 0..800)
#   ES_0 idx0 centre x=-600| ES_1 idx1 centre x=-200  (ES spans x -800..0)
# Lane polylines run with travel: EN from y=0 to y=1000, ES from y=1000 to
# y=0.  Carriageway width of each direction = 400+400 = 800 cm.


def _pt(x, y):
    return {"x": float(x), "y": float(y)}


def _car(lid, index, x0, y0, x1, y1, width=400.0):
    """A carriageway lane: disallows pedestrians (SUMO's marker)."""
    return {
        "id": lid, "index": index,
        "width_cm": width, "width_cm_effective": width,
        "width_source": "attribute", "speed_mps": 13.89, "length_m": 10.0,
        "allow": None, "disallow": ["pedestrian"],
        "polyline": [_pt(x0, y0), _pt(x1, y1)],
    }


def _walk(lid, index, x0, y0, x1, y1, width=200.0):
    """A sidewalk lane: allows pedestrians, disallows nothing."""
    return {
        "id": lid, "index": index,
        "width_cm": width, "width_cm_effective": width,
        "width_source": "attribute", "speed_mps": 0.0, "length_m": 10.0,
        "allow": ["pedestrian"], "disallow": [],
        "polyline": [_pt(x0, y0), _pt(x1, y1)],
    }


def _edge(eid, a, b, lanes, function="normal"):
    return {
        "id": eid, "from_junction": a, "to_junction": b,
        "function": function, "priority": 1, "lanes": lanes,
    }


def _junction(jid, jtype, x=0.0, y=0.0):
    return {"id": jid, "type": jtype, "position": _pt(x, y),
            "polygon": None, "incoming_edge_ids": []}


def _spec(edges, junctions):
    return {"schema_version": "road_spec_v1", "edges": edges,
            "junctions": junctions,
            "counts": {"edges": len(edges), "junctions": len(junctions)}}


def _road_edges():
    """EN (northbound, east half) + ES (southbound reverse, west half)."""
    return [
        _edge("EN", "J0", "J1", [_car("EN_0", 0, 600, 0, 600, 1000),
                                 _car("EN_1", 1, 200, 0, 200, 1000)]),
        _edge("ES", "J1", "J0", [_car("ES_0", 0, -600, 1000, -600, 0),
                                 _car("ES_1", 1, -200, 1000, -200, 0)]),
    ]


def _road_spec(j1_type="traffic_light", j0_type="priority"):
    return _spec(_road_edges(),
                 [_junction("J0", j0_type, 0.0, 0.0),
                  _junction("J1", j1_type, 0.0, 1000.0)])


def _mid(poly):
    """Midpoint of a two-point [(x0,y0),(x1,y1)] polyline."""
    return ((poly[0]["x"] + poly[1]["x"]) / 2.0,
            (poly[0]["y"] + poly[1]["y"]) / 2.0)


# --- 1. lateral_normal: measured, never assumed -----------------------------

def test_lateral_normal_two_car_lanes_north_points_lane0_to_lane1():
    """Two car lanes running north: normal must point from lane index 0
    toward lane index 1 (here west).  Would break if the sign were guessed
    from an axis instead of measured from the lane positions."""
    edge = _road_edges()[0]  # EN: idx0 at x=600, idx1 at x=200
    n = lateral_normal(edge)
    assert n == (-1.0, 0.0)
    a = _mid(edge["lanes"][0]["polyline"])   # (600, 500)
    b = _mid(edge["lanes"][1]["polyline"])   # (200, 500)
    ref = (b[0] - a[0], b[1] - a[1])
    assert ref[0] * n[0] + ref[1] * n[1] > 0.0


def test_lateral_normal_mirrored_edge_flips_normal():
    """Mirror of the northbound two-lane edge (lanes on the west half) must
    flip the normal from (-1,0) to (1,0).  Would break if the normal were
    hardcoded to a compass point."""
    edge = _edge("M", "J0", "J1", [_car("M_0", 0, -600, 0, -600, 1000),
                                   _car("M_1", 1, -200, 0, -200, 1000)])
    n = lateral_normal(edge)
    assert n == (1.0, 0.0)
    assert n == (-1.0 * -1.0, 0.0)


def test_lateral_normal_east_running_edge_measured():
    """East-running edge (polyline +x): normal still points lane0 -> lane1
    (here +y, since index 1 sits north of index 0).  Would break if the code
    assumed north-south edges only."""
    edge = _edge("E", "A", "B", [_car("E_0", 0, 0, -600, 1000, -600),
                                 _car("E_1", 1, 0, -200, 1000, -200)])
    n = lateral_normal(edge)
    assert n == pytest.approx((0.0, 1.0))
    a = _mid(edge["lanes"][0]["polyline"])
    b = _mid(edge["lanes"][1]["polyline"])
    ref = (b[0] - a[0], b[1] - a[1])
    assert ref[0] * n[0] + ref[1] * n[1] > 0.0


def test_lateral_normal_diagonal_edge_measured():
    """Diagonal edge (1,1): normal must be the perpendicular that points from
    lane 0 to lane 1 (NW = (-.7071,.7071)).  Would break if only axis-aligned
    edges were handled."""
    s = math.sqrt(2.0) / 2.0
    off = 400.0
    px, py = -s * off, s * off  # lane 1 offset NW by 400 from lane 0
    edge = _edge("D", "A", "B",
                 [_car("D_0", 0, 0.0, 0.0, 1000.0, 1000.0),
                  _car("D_1", 1, px, py, 1000.0 + px, 1000.0 + py)])
    n = lateral_normal(edge)
    assert n == pytest.approx((-s, s))
    a = _mid(edge["lanes"][0]["polyline"])
    b = _mid(edge["lanes"][1]["polyline"])
    ref = (b[0] - a[0], b[1] - a[1])
    assert ref[0] * n[0] + ref[1] * n[1] > 0.0


def test_lateral_normal_single_car_lane_sidewalk_supplies_sign():
    """One car lane plus a sidewalk: the sidewalk (outboard, on the -n side)
    must decide the sign; car at x=600 with sidewalk at x=900 gives
    n = (-1,0).  Would break if the code guessed from lane count alone."""
    edge = _edge("SW", "J0", "J1",
                 [_car("SW_0", 0, 600, 0, 600, 1000),
                  _walk("SW_1", 1, 900, 0, 900, 1000)])
    n = lateral_normal(edge)
    assert n == (-1.0, 0.0)
    # normal points from the sidewalk toward the car lane (road side)
    w = _mid(edge["lanes"][1]["polyline"])   # sidewalk (900, 500)
    c = _mid(edge["lanes"][0]["polyline"])   # car (600, 500)
    ref = (c[0] - w[0], c[1] - w[1])
    assert ref[0] * n[0] + ref[1] * n[1] > 0.0


def test_lateral_normal_single_lane_sidewalk_on_other_side_flips():
    """Mirror of the single-car-lane case (sidewalk west of the car) must flip
    the normal to (1,0).  Would break if the sign only ever went one way."""
    edge = _edge("SW", "J0", "J1",
                 [_car("SW_0", 0, -600, 0, -600, 1000),
                  _walk("SW_1", 1, -900, 0, -900, 1000)])
    assert lateral_normal(edge) == (1.0, 0.0)


def test_lateral_normal_no_car_lanes_returns_none():
    """An edge carrying only sidewalks has no car lanes -> None, never an
    invented side.  Would break if a normal were fabricated."""
    edge = _edge("P", "J0", "J1",
                 [_walk("P_0", 0, 0, 0, 0, 1000),
                  _walk("P_1", 1, 300, 0, 300, 1000)])
    assert lateral_normal(edge) is None


def test_lateral_normal_degenerate_polyline_returns_none():
    """Zero-length car-lane polyline -> None.  Would break if a division by
    zero slipped through or a bogus unit vector were returned."""
    edge = _edge("Z", "J0", "J1",
                 [_car("Z_0", 0, 5, 5, 5, 5),
                  _car("Z_1", 1, 9, 5, 9, 5)])
    assert lateral_normal(edge) is None
    one_pt = _edge("O", "J0", "J1", [_car("O_0", 0, 5, 5, 5, 5)])
    one_pt["lanes"][0]["polyline"] = [_pt(5, 5)]
    assert lateral_normal(one_pt) is None


# --- 2. is_car_lane / is_sidewalk_lane read allow/disallow ------------------

def test_is_car_lane_reads_disallow_not_index():
    """A lane is a car lane iff ``disallow`` contains pedestrian; index,
    allow and speed must be irrelevant.  Would break if the classifier guessed
    from lane index or width."""
    assert is_car_lane({"index": 7, "disallow": ["pedestrian"],
                        "allow": None, "width_cm_effective": 400.0})
    assert is_car_lane({"index": 0, "disallow": ["truck", "pedestrian"],
                        "allow": ["passenger"], "width_cm_effective": 400.0})
    assert not is_car_lane({"index": 0, "disallow": None,
                            "allow": ["pedestrian"],
                            "width_cm_effective": 200.0})


def test_is_car_lane_empty_disallow_is_not_car_lane():
    """``disallow: []`` is not a car lane: the read is of the token list, so an
    empty list must not accidentally count as 'disallows nothing but cars'.
    Would break if falsy-but-present were treated as a car lane."""
    lane = {"index": 0, "disallow": [], "allow": None,
            "width_cm_effective": 400.0}
    assert not is_car_lane(lane)
    lane["allow"] = ["pedestrian"]
    assert not is_car_lane(lane) and is_sidewalk_lane(lane)


def test_is_sidewalk_lane_reads_allow():
    """A lane is a sidewalk iff ``allow`` contains pedestrian.  Would break if
    it guessed from disallow or from the lane number."""
    assert is_sidewalk_lane({"index": 1, "allow": ["pedestrian"],
                             "disallow": [], "width_cm_effective": 200.0})
    assert not is_sidewalk_lane({"index": 0, "allow": ["passenger"],
                                 "disallow": ["pedestrian"],
                                 "width_cm_effective": 400.0})
    assert not is_sidewalk_lane({"index": 0, "allow": None,
                                 "disallow": None,
                                 "width_cm_effective": 400.0})


# --- 3. lane_markings geometry ----------------------------------------------

def test_lane_markings_edge_line_exact_coordinates():
    """Kerb-side edge line of the lowest-index car lane.  EN_0 centre x=600,
    width 400, normal (-1,0): outer boundary = 600 + 400/2 = x=800, running
    y 0..1000.  Would break if the offset sign or the lane chosen was wrong."""
    rows = lane_markings(_road_spec())
    edge = [r for r in rows if r["kind"] == "edge_line" and
            r["edge_id"] == "EN"][0]
    assert edge["id"] == "EN|edge|0"
    assert (edge["x0"], edge["y0"], edge["x1"], edge["y1"]) == \
        (800.0, 0.0, 800.0, 1000.0)
    assert edge["colour"] == "white"
    assert edge["length_cm"] == 1000.0
    assert edge["width_cm"] == 12.0  # default line width
    es = [r for r in rows if r["kind"] == "edge_line" and
          r["edge_id"] == "ES"][0]
    # ES_0 centre x=-600, normal (1,0): outer boundary x=-800, polyline
    # reversed (y 1000 -> 0)
    assert (es["x0"], es["y0"], es["x1"], es["y1"]) == \
        (-800.0, 1000.0, -800.0, 0.0)


def test_lane_markings_divider_dashes_exact_endpoints():
    """Dashed divider between the two car lanes sits at the shared boundary
    x=400 (EN_0 centre 600 + 200 along n=(-1,0)).  Over length 1000 with
    dash_len 300 / gap 500 the dashes are [0,300] and [800,1000] on the
    polyline, i.e. y 0..300 and y 800..1000.  Would break if the boundary
    offset or the dash split changed."""
    rows = lane_markings(_road_spec())
    divs = sorted([r for r in rows if r["kind"] == "lane_divider" and
                   r["edge_id"] == "EN"], key=lambda r: r["id"])
    assert [r["id"] for r in divs] == ["EN|divider0|0", "EN|divider0|1"]
    a, b = divs
    assert (a["x0"], a["y0"], a["x1"], a["y1"]) == (400.0, 0.0, 400.0, 300.0)
    assert (b["x0"], b["y0"], b["x1"], b["y1"]) == (400.0, 800.0, 400.0, 1000.0)
    assert a["length_cm"] == 300.0 and b["length_cm"] == 200.0  # truncated
    assert a["colour"] == "white"
    # reverse edge dashes at x=-400, mirrored along the polyline
    es = sorted([r for r in rows if r["kind"] == "lane_divider" and
                 r["edge_id"] == "ES"], key=lambda r: r["id"])
    assert (es[0]["x0"], es[0]["y0"], es[0]["x1"], es[0]["y1"]) == \
        (-400.0, 1000.0, -400.0, 700.0)
    assert (es[1]["x0"], es[1]["y0"], es[1]["x1"], es[1]["y1"]) == \
        (-400.0, 200.0, -400.0, 0.0)


def test_lane_markings_centre_line_pullback_exact():
    """Centre line = inner boundary of the highest-index car lane pulled back
    by double_gap/2 = 10.  EN_1 centre x=200, width 400, normal (-1,0):
    200 - (400/2 - 20/2) = 200 - 190 = x=10.  Would break if the pullback
    (or its sign) were wrong."""
    rows = lane_markings(_road_spec())
    en = [r for r in rows if r["kind"] == "centre_line" and
          r["edge_id"] == "EN"][0]
    assert en["colour"] == "yellow"
    assert (en["x0"], en["y0"], en["x1"], en["y1"]) == (10.0, 0.0, 10.0, 1000.0)
    es = [r for r in rows if r["kind"] == "centre_line" and
          r["edge_id"] == "ES"][0]
    assert (es["x0"], es["y0"], es["x1"], es["y1"]) == (-10.0, 1000.0, -10.0, 0.0)


def test_lane_markings_reverse_edge_centre_lines_double_gap():
    """Double-yellow law: an edge and its exact reverse paint two centre lines
    separated by exactly double_gap_cm (20 here), never coincident.  Would
    break if the pullback was dropped (z-fighting coincident lines) or doubled
    (40 cm)."""
    rows = lane_markings(_road_spec())  # double_gap_cm default 20.0
    en = [r for r in rows if r["kind"] == "centre_line" and
          r["edge_id"] == "EN"][0]
    es = [r for r in rows if r["kind"] == "centre_line" and
          r["edge_id"] == "ES"][0]
    sep = abs(en["x0"] - es["x0"])
    assert sep == pytest.approx(20.0)  # == double_gap_cm
    # explicit parameter honoured too
    rows2 = lane_markings(_road_spec(), double_gap_cm=30.0)
    en2 = [r for r in rows2 if r["kind"] == "centre_line" and
           r["edge_id"] == "EN"][0]
    es2 = [r for r in rows2 if r["kind"] == "centre_line" and
           r["edge_id"] == "ES"][0]
    assert abs(en2["x0"] - es2["x0"]) == pytest.approx(30.0)
    assert en2["x0"] == pytest.approx(15.0)  # 200 - (200 - 15) = 15


def test_lane_markings_ignores_non_normal_edges():
    """A crossing edge must produce no painted lines.  Would break if
    ``function`` was ignored."""
    spec = _spec([_edge("X0", "J0", "J0",
                        [_walk("X0_0", 0, 0, 0, 1000, 0, width=400.0)],
                        function="crossing")],
                 [_junction("J0", "priority")])
    assert lane_markings(spec) == []


# --- 4. _dash ---------------------------------------------------------------

def test_dash_count_and_first_last_endpoints():
    """1000 cm straight polyline, dash 300 / gap 500: dashes [0,300] and
    [800,1000] (the second is truncated to the line end but still >= a
    quarter).  Would break if the pattern phase or the truncation rule
    changed."""
    pts = [(0.0, 0.0), (1000.0, 0.0)]
    dashes = _dash(pts, 300.0, 500.0)
    assert len(dashes) == 2
    assert dashes[0] == ((0.0, 0.0), (300.0, 0.0))
    assert dashes[1] == ((800.0, 0.0), (1000.0, 0.0))


def test_dash_final_partial_shorter_than_quarter_dropped():
    """Total 1000, dash 600 / gap 300: the second partial dash would run
    s=900..1000 (100 cm < 600/4=150) and must be dropped -> one dash.
    Would break if every partial tail were kept."""
    dashes = _dash([(0.0, 0.0), (1000.0, 0.0)], 600.0, 300.0)
    assert dashes == [((0.0, 0.0), (600.0, 0.0))]


def test_dash_final_partial_quarter_or_more_kept():
    """Total 1000, dash 600 / gap 200: tail s=800..1000 is 200 cm >= 150, so
    it is kept as a truncated dash.  Would break if only full dashes were
    emitted (a short lane would read blank)."""
    dashes = _dash([(0.0, 0.0), (1000.0, 0.0)], 600.0, 200.0)
    assert dashes == [((0.0, 0.0), (600.0, 0.0)),
                      ((800.0, 0.0), (1000.0, 0.0))]


def test_dash_nonpositive_dash_len_empty():
    """dash_len <= 0 yields no dashes at all.  Would break on a division or an
    infinite loop for zero/negative lengths."""
    pts = [(0.0, 0.0), (1000.0, 0.0)]
    assert _dash(pts, 0.0, 500.0) == []
    assert _dash(pts, -10.0, 500.0) == []


def test_dash_degenerate_polyline_empty():
    """Zero-length or single-point polylines yield no dashes.  Would break if
    a zero-length segment produced an endpoint pair."""
    assert _dash([(5.0, 5.0)], 300.0, 500.0) == []
    assert _dash([(5.0, 5.0), (5.0, 5.0)], 300.0, 500.0) == []


# --- 5. crosswalk_stripes ---------------------------------------------------

def test_crosswalk_stripes_count_and_centring():
    """Span 1000, stripe 45 / gap 45 -> pitch 90, count = 1000//90 = 11;
    used = 11*90 - 45 = 945, so the band starts at (1000-945)/2 = 27.5 and the
    end margin is equal (1000 - (27.5 + 11*90 - 45) = 27.5).  Would break if
    stripes were counted or centred wrong."""
    spec = _spec([_edge("X0", "J0", "J0",
                        [_walk("X0_0", 0, 0, 0, 1000, 0, width=400.0)],
                        function="crossing")],
                 [_junction("J0", "priority")])
    rows = crosswalk_stripes(spec)
    assert len(rows) == 11
    first, last = _by_id(rows, "|0"), _by_id(rows, "|10")
    # stripe i occupies [27.5 + i*90, 27.5 + i*90 + 45]; x is its CENTRE
    assert first["x"] == pytest.approx(50.0)            # 27.5 + 45/2
    assert last["x"] == pytest.approx(27.5 + 10 * 90.0 + 22.5)   # 950.0
    band_start = first["x"] - 22.5
    band_end = last["x"] + 22.5
    assert band_start == pytest.approx(27.5)
    assert 1000.0 - band_end == pytest.approx(band_start)   # equal margins


def test_crosswalk_stripes_first_last_stripe_positions():
    """Stripe centres sit at start + i*pitch + stripe_width/2 = 50 + i*90
    (i=0..10).  Would break if the stripe anchor moved."""
    spec = _spec([_edge("X0", "J0", "J0",
                        [_walk("X0_0", 0, 0, 0, 1000, 0, width=400.0)],
                        function="crossing")],
                 [_junction("J0", "priority")])
    rows = crosswalk_stripes(spec)
    assert _by_id(rows, "|0")["x"] == pytest.approx(50.0)   # 27.5 + 22.5
    assert _by_id(rows, "|10")["x"] == pytest.approx(50.0 + 10 * 90.0)  # 950.0
    ids = [r["id"] for r in rows]
    assert set(ids) == {"X0|0|%d" % i for i in range(11)}
    # ids are sorted as STRINGS, which is why every lookup above used _by_id
    assert ids == sorted(ids)


def test_crosswalk_stripes_size_across_equals_lane_width():
    """size_across_cm must equal the crossing lane's own width_cm_effective
    (400), and size_along_cm the stripe width (45).  Would break if the depth
    were taken from a guess instead of the lane width."""
    spec = _spec([_edge("X0", "J0", "J0",
                        [_walk("X0_0", 0, 0, 0, 1000, 0, width=400.0)],
                        function="crossing")],
                 [_junction("J0", "priority")])
    for r in crosswalk_stripes(spec):
        assert r["size_across_cm"] == 400.0
        assert r["size_along_cm"] == 45.0


# --- 6. signal_placements ---------------------------------------------------

def test_signal_traffic_light_junction_kind_and_setback():
    """A traffic_light junction yields a traffic_light.  EN_0 lane centre
    x=600, normal (-1,0), setback 250 -> point at s=750 -> y=750, lateral
    offset -(200+120) = -320 along n -> x = 600 + 320 = 920, i.e. 250 cm back
    from the junction end (y=1000).  Would break if the kind mapping or the
    setback arithmetic changed."""
    rows = signal_placements(_road_spec(j1_type="traffic_light"))
    # the fixture has two incoming normal edges: EN->J1 and ES->J0, and a
    # priority junction legitimately gets a stop sign, so both appear.
    assert len(rows) == 2
    assert {r["kind"] for r in rows} == {"traffic_light", "stop_sign"}
    r = _by_id(rows, "|EN")
    assert r["id"] == "J1|EN"
    assert r["junction_id"] == "J1"
    assert r["kind"] == "traffic_light"
    assert r["x"] == pytest.approx(920.0)
    assert r["y"] == pytest.approx(750.0)
    # set back from the junction end (lane end y=1000) by exactly setback_cm
    assert 1000.0 - r["y"] == pytest.approx(250.0)


def test_signal_priority_junction_yields_stop_sign():
    """A priority junction yields a stop_sign for each incoming normal edge
    (ES into J0 here).  Would break if priority were turned into a light or
    skipped."""
    rows = signal_placements(_road_spec(j1_type="priority", j0_type="priority"))
    kinds = sorted(r["kind"] for r in rows)
    assert kinds == ["stop_sign", "stop_sign"]
    es = [r for r in rows if r["edge_id"] == "ES"][0]
    assert es["junction_id"] == "J0"
    assert es["kind"] == "stop_sign"
    # ES runs south; signal sits 250 cm short of J0 (y=0) -> y=250
    assert es["y"] == pytest.approx(250.0)
    assert es["y"] == pytest.approx(250.0)  # 1000 - 750 along reversed poly


def test_signal_unknown_junction_type_produces_no_rows():
    """Any junction type other than traffic_light/priority must produce
    NOTHING, never a silently invented signal.  Would break if an unknown
    type fell through to a default signal."""
    rows = signal_placements(_road_spec(j1_type="unknown", j0_type="unknown"))
    assert rows == []
    spec = _road_spec()
    spec["junctions"][1]["type"] = "allway_stop"
    # J0 is still "priority", so its stop sign remains; only the
    # allway_stop junction contributes nothing.
    left = signal_placements(spec)
    assert [r["kind"] for r in left] == ["stop_sign"]
    assert all(r["junction_type"] == "priority" for r in left)


def test_signal_yaw_faces_back_down_the_approach():
    """Signal yaw must be the approach direction rotated 180 degrees.  EN
    travels north (+y, yaw 90); the signal must face south: yaw -90.  Would
    break if the face pointed with traffic or sideways."""
    rows = signal_placements(_road_spec(j1_type="traffic_light"))
    r = _by_id(rows, "|EN")
    assert r["yaw"] == pytest.approx(-90.0)
    # unit vector from yaw equals -(approach unit (0,1)) = (0,-1)
    rad = math.radians(r["yaw"])
    assert (math.cos(rad), math.sin(rad)) == pytest.approx((0.0, -1.0))
    es = [x for x in signal_placements(
        _road_spec(j1_type="priority", j0_type="priority"))
        if x["edge_id"] == "ES"][0]
    assert es["yaw"] == pytest.approx(90.0)  # ES travels -y, faces +y


def test_signal_skipped_when_kerb_side_is_unknowable():
    """A one-car-lane edge with no sidewalk gives no way to know which side the
    kerb is on, so no signal is invented -- but the skip must be COUNTED, never
    silent.  Would break if such an edge were dropped without a trace, which is
    how a network could lose signals and still report a pass."""
    short = _edge("SH", "J0", "J1", [_car("SH_0", 0, 600, 0, 600, 100)])
    spec = _spec([short],
                 [_junction("J0", "priority", 0.0, 0.0),
                  _junction("J1", "traffic_light", 0.0, 100.0)])
    rows, skipped = signal_placements(spec, setback_cm=250.0, with_skips=True)
    assert rows == []
    assert skipped == [{"junction_id": "J1", "edge_id": "SH",
                        "reason": "lateral_normal_unknown"}]


def test_signal_setback_clamps_to_edge_start():
    """An approach shorter than setback_cm must clamp to s=0, never run past
    the edge's far end into a negative arc length."""
    short = _edge("SH", "J0", "J1",
                  [_walk("SH_0", 0, 900, 0, 900, 100, width=200.0),
                   _car("SH_1", 1, 600, 0, 600, 100)])
    spec = _spec([short],
                 [_junction("J0", "priority", 0.0, 0.0),
                  _junction("J1", "traffic_light", 0.0, 100.0)])
    rows = signal_placements(spec, setback_cm=250.0)
    assert len(rows) == 1
    # the lane is 100 cm long and the setback is 250, so the point clamps to the
    # lane start (y=0) rather than to y=-150
    assert rows[0]["y"] == pytest.approx(0.0)



def _sidewalk_spec():
    """One north-running edge with a 200 cm sidewalk at x=900 outboard of a
    320 cm car lane at x=600, so the lateral normal points from the sidewalk
    toward the carriageway."""
    return _spec([_edge("SW", "J0", "J1",
                        [_car("SW_0", 0, 600, 0, 600, 1000, width=320.0),
                         _walk("SW_1", 1, 900, 0, 900, 1000, width=200.0)])],
                 [_junction("J0", "priority", 0.0, 0.0),
                  _junction("J1", "traffic_light", 0.0, 1000.0)])

def test_tree_slots_spacing_phase_and_no_tree_at_zero():
    """Trees start at phase (200) and repeat every spacing (400): distances
    200 and 600 on a 1000 cm sidewalk; none at distance 0.  Would break if
    the phase were ignored or a tree were planted at the kerb."""
    rows = tree_slots(_sidewalk_spec(), spacing_cm=400.0, phase_cm=200.0)
    assert [r["distance_cm"] for r in rows] == [200.0, 600.0]
    assert all(r["distance_cm"] > 0.0 for r in rows)
    assert [r["id"] for r in rows] == ["SW_1|tree|0", "SW_1|tree|1"]


def test_tree_slots_trees_on_far_side_of_sidewalk():
    """Trees sit beyond the sidewalk centre, away from the road: sidewalk
    centre x=900 (car at x=600), width 200, back_offset 70 -> lat =
    -(100-70) = -30 along n=(-1,0) -> x=930, i.e. 70 cm short of the far edge
    x=1000.  Would break if trees were pushed toward the carriageway."""
    rows = tree_slots(_sidewalk_spec(), spacing_cm=400.0, phase_cm=200.0)
    assert rows
    for r in rows:
        assert r["x"] == pytest.approx(930.0)
        assert r["x"] > 900.0        # far half of the pavement
        # `yaw` is now the planned variety rotation; the walk alignment moved
        # to `lane_yaw` so both are stated and both are verifiable.
        assert r["lane_yaw"] == pytest.approx(90.0)


def test_tree_slots_edge_without_sidewalk_lane_yields_none():
    """A normal edge with only car lanes has no tree slots.  Would break if a
    tree were planted on the carriageway."""
    spec = _spec([_edge("EN", "J0", "J1",
                        [_car("EN_0", 0, 600, 0, 600, 1000),
                         _car("EN_1", 1, 200, 0, 200, 1000)])],
                 [_junction("J0", "priority", 0.0, 0.0),
                  _junction("J1", "priority", 0.0, 1000.0)])
    assert tree_slots(spec) == []


# --- 8. closure_props -------------------------------------------------------

def test_closure_barricade_plus_at_least_two_cones():
    """Closing EN (width 800, setback 400 -> barricade line at s=600/y=600)
    yields one barricade and six cones: count = max(2, 800//160 + 1) = 6.
    Would break if a closed edge got no barricade or fewer than two cones."""
    rows = closure_props(_road_spec(), ["EN"])
    bar = [r for r in rows if r["kind"] == "barricade"]
    cones = [r for r in rows if r["kind"] == "cone"]
    assert len(bar) == 1 and bar[0]["id"] == "EN|barricade"
    assert len(cones) == 6
    # cones span x=800 down to x=0 in five equal steps (160 cm)
    xs = [c["x"] for c in sorted(cones, key=lambda c: c["id"])]
    assert xs == [800.0, 640.0, 480.0, 320.0, 160.0, 0.0]


def test_closure_span_equals_measured_carriageway_width():
    """span_cm equals the measured carriageway width: outer boundary of lane 0
    (x=800) to inner boundary of the last lane (x=0) -> 800 = 400+400.
    Would break if the span came from a typed constant."""
    rows = closure_props(_road_spec(), ["EN"])
    assert rows[0]["id"] == "EN|barricade"  # 'b' sorts before 'c'
    assert rows[0]["span_cm"] == 800.0
    assert all(r["span_cm"] == 800.0 for r in rows)
    assert rows[0]["x"] == pytest.approx(400.0)
    assert rows[0]["y"] == pytest.approx(600.0)
    assert rows[0]["yaw"] == pytest.approx(180.0)  # spans across the road


def test_closure_unknown_edge_id_skipped():
    """An edge id absent from the spec is skipped silently.  Would break if it
    raised or fabricated geometry."""
    assert closure_props(_road_spec(), ["NOPE"]) == []
    assert closure_props(_road_spec(), ["EN", "NOPE", "ALSO_GONE"]) != []


def test_closure_non_normal_edge_skipped():
    """A closed edge whose function is not ``normal`` (e.g. a crossing) is
    skipped silently.  Would break if a crossing got barricaded."""
    spec = _spec([_edge("X0", "J0", "J0",
                        [_walk("X0_0", 0, 0, 0, 1000, 0, width=400.0)],
                        function="crossing")],
                 [_junction("J0", "priority")])
    assert closure_props(spec, ["X0"]) == []
    # normal edge but no car lanes is also skipped
    spec2 = _spec([_edge("P", "J0", "J1",
                         [_walk("P_0", 0, 0, 0, 0, 1000)])],
                  [_junction("J0", "priority", 0.0, 0.0),
                   _junction("J1", "priority", 0.0, 1000.0)])
    assert closure_props(spec2, ["P"]) == []


# --- 9. build_dressing determinism + 10. counts/params ----------------------

def _full_spec():
    """EN/ES two-lane road (J1 traffic_light), SW single-car-lane + sidewalk
    at x=2600 (a separate parallel street), X0 crossing at x=5000."""
    edges = _road_edges() + [
        _edge("SW", "J0", "J1",
              [_car("SW_0", 0, 2600, 0, 2600, 1000),
               _walk("SW_1", 1, 2900, 0, 2900, 1000)]),
        _edge("X0", "J0", "J0",
              [_walk("X0_0", 0, 5000, 0, 5000, 1000, width=400.0)],
              function="crossing"),
    ]
    return _spec(edges, [_junction("J0", "priority", 0.0, 0.0),
                         _junction("J1", "traffic_light", 0.0, 1000.0)])


def _build_kwargs():
    return dict(line_width_cm=13.5, dash_len_cm=250.0, dash_gap_cm=450.0,
                double_gap_cm=24.0, stripe_width_cm=50.0, stripe_gap_cm=40.0,
                signal_setback_cm=300.0, tree_spacing_cm=400.0,
                tree_phase_cm=200.0, closed_edge_ids=["EN", "ZZ"])


def test_build_dressing_twice_byte_identical():
    """Two runs over the same spec produce byte-identical sorted JSON.  Would
    break on any dict-order or float-drift nondeterminism."""
    a = json.dumps(build_dressing(_full_spec(), **_build_kwargs()),
                   sort_keys=True)
    b = json.dumps(build_dressing(_full_spec(), **_build_kwargs()),
                   sort_keys=True)
    assert a == b


def test_build_dressing_no_negative_zero_and_floats_rounded():
    """Every float in the serialised document is round(x, 3) and no '-0.0'
    byte appears.  Would break if a raw float leaked through or a -0.0 was
    serialised."""
    doc = build_dressing(_full_spec(), **_build_kwargs())
    text = json.dumps(doc, sort_keys=True)
    assert "-0.0" not in text

    def floats(o):
        if isinstance(o, float):
            yield o
        elif isinstance(o, dict):
            for v in o.values():
                yield from floats(v)
        elif isinstance(o, list):
            for v in o:
                yield from floats(v)

    for f in floats(doc):
        assert round(f, 3) == f


def test_build_dressing_every_list_sorted_by_id():
    """Each row list in the document is sorted by its ``id`` key.  Would break
    if iteration order stopped following the lexicographic id law."""
    doc = build_dressing(_full_spec(), **_build_kwargs())
    for key in ("lane_markings", "crosswalk_stripes", "signals", "trees",
                "closure_props"):
        ids = [r["id"] for r in doc[key]]
        assert ids == sorted(ids), key


def test_build_dressing_counts_agree_with_list_lengths():
    """The counts block must agree with the lists it describes.  Hand-derived
    totals for this spec: markings 10 (EN 4 + ES 4 + SW 2), stripes 11
    (1000//90 with stripe 50/gap 40), signals 3 (2 lights + 1 stop sign),
    trees 2 (sidewalk SW_1, phase 200 step 400 on 1000), closure 7
    (1 barricade + 6 cones for EN).  Would break if a list were counted
    elsewhere than where it was built."""
    doc = build_dressing(_full_spec(), **_build_kwargs())
    c = doc["counts"]
    assert c["markings"] == len(doc["lane_markings"]) == 10
    assert c["crosswalk_stripes"] == len(doc["crosswalk_stripes"]) == 11
    assert c["signals"] == len(doc["signals"]) == 3
    assert c["trees"] == len(doc["trees"]) == 2
    assert c["closure_props"] == len(doc["closure_props"]) == 7


def test_build_dressing_counts_by_kind_agree():
    """markings_by_kind / signals_by_kind must sum to the lists they describe.
    Hand-derived: markings 3 edge_line + 4 lane_divider + 3 centre_line;
    signals 2 traffic_light (EN, SW into J1) + 1 stop_sign (ES into J0)."""
    doc = build_dressing(_full_spec(), **_build_kwargs())
    c = doc["counts"]
    assert c["markings_by_kind"] == {"edge_line": 3, "lane_divider": 4,
                                     "centre_line": 3}
    assert c["signals_by_kind"] == {"traffic_light": 2, "stop_sign": 1}
    assert sum(c["markings_by_kind"].values()) == len(doc["lane_markings"])
    assert sum(c["signals_by_kind"].values()) == len(doc["signals"])


def test_build_dressing_params_echo_every_argument_used():
    """params echoes every argument the builders actually received, rounded
    and de-duplicated.  Would break if a caller override silently fell back to
    a default or a closed id was dropped."""
    doc = build_dressing(_full_spec(), **_build_kwargs())
    p = doc["params"]
    assert p["line_width_cm"] == 13.5
    assert p["dash_len_cm"] == 250.0
    assert p["dash_gap_cm"] == 450.0
    assert p["double_gap_cm"] == 24.0
    assert p["stripe_width_cm"] == 50.0
    assert p["stripe_gap_cm"] == 40.0
    assert p["signal_setback_cm"] == 300.0
    assert p["tree_spacing_cm"] == 400.0
    assert p["tree_phase_cm"] == 200.0
    assert p["closed_edge_ids"] == ["EN", "ZZ"]  # deduped + sorted
    assert doc["schema_version"] == "dressing_v1"


def test_build_dressing_custom_values_reach_rows():
    """Override values must be visible in the rows (line width in markings,
    setback on the signal, tree spacing on the ground), proving the params
    block is not decorative.  Would break if the overrides were swallowed."""
    doc = build_dressing(_full_spec(), **_build_kwargs())
    assert all(r["width_cm"] == 13.5 for r in doc["lane_markings"])
    sig = [r for r in doc["signals"] if r["edge_id"] == "EN"][0]
    # EN_0 centre x=600, setback 300 -> s=700 -> y=700 on a 1000 edge
    assert 1000.0 - sig["y"] == pytest.approx(300.0)
    assert [r["distance_cm"] for r in doc["trees"]] == [200.0, 600.0]


def test_tree_rows_carry_the_variant_scale_and_yaw_the_spawner_must_use():
    """The spawner used to roll a tree's mesh variant, scale and yaw itself,
    which meant the plan promised a yaw the spawner discarded and the verifier
    had to skip yaw AND mesh -- so a tree rotated into the carriageway, or the
    wrong species, passed. The plan owns all three now. Would break if any of
    them went back to being decided at spawn time."""
    rows = tree_slots(_sidewalk_spec(), spacing_cm=400.0, phase_cm=200.0)
    assert rows
    for r in rows:
        assert set(("variant", "scale", "yaw", "lane_yaw")) <= set(r)
        assert r["variant"] in (0, 1, 2)
        assert 0.85 <= r["scale"] <= 1.15
        assert 0.0 <= r["yaw"] < 360.0


def test_tree_variant_scale_and_yaw_are_deterministic():
    """Two builds must agree, or a replay would re-dress the street."""
    a = tree_slots(_sidewalk_spec(), spacing_cm=400.0, phase_cm=200.0)
    b = tree_slots(_sidewalk_spec(), spacing_cm=400.0, phase_cm=200.0)
    assert [(r["variant"], r["scale"], r["yaw"]) for r in a] == \
           [(r["variant"], r["scale"], r["yaw"]) for r in b]


def test_tree_yaw_is_not_the_lane_direction():
    """A street tree has no meaningful facing, so its yaw is deterministic
    variety rather than geometry -- but it must still be stated so it can be
    verified. Would break if yaw silently became the lane alignment again."""
    rows = tree_slots(_sidewalk_spec(), spacing_cm=400.0, phase_cm=200.0)
    assert any(r["yaw"] != r["lane_yaw"] for r in rows)


def test_crosswalk_stripes_state_their_colour():
    """Stripes carried no colour, so the verifier had no expected material and
    a crossing painted in centre-line yellow passed. Would break if the field
    were dropped."""
    spec = _spec([_edge("X0", "J0", "J0",
                        [_walk("X0_0", 0, 0, 0, 1000, 0, width=400.0)],
                        function="crossing")],
                 [_junction("J0", "priority")])
    rows = crosswalk_stripes(spec)
    assert rows and all(r["colour"] == "white" for r in rows)
