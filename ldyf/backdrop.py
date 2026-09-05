"""``backdrop_spec_v1``: presentation-only scenery behind (and around) the city.

The simulated world ends at the finite ground plane that bounds the road
lattice.  In a wide aerial shot the plane visibly runs out.  This module builds
**scenery only** -- never simulated, never traffic, never world truth:

* ``world_bounds`` -- the bbox (in Unreal centimetres) of every lane polyline
  point in a ``road_spec_v1`` (``ldyf.roads``).  Nesting walked is exactly what
  ``roads.py`` produces: ``spec["edges"]`` -> ``edge["lanes"]`` ->
  ``lane["polyline"]`` -> point dicts holding ``x``, ``y`` (and ``z``, unused
  here).  Every edge counts regardless of its ``function`` (normal, internal,
  crossing, ...).
* ``skirt_ring`` -- a closed annulus of ``segments`` ground quads around the
  world centre, from an inner radius that fully contains the world bbox out to
  ``outer_radius_cm``.  No four-side "frame" here: because the quads tile every
  one of the ``segments`` angular steps of a full turn there is no diagonal
  corner gap.  Adjacent quads share their radial edges exactly.
* ``point_in_ring`` -- inside-any-quad test used to probe the ring in tests.
* ``backdrop_massing`` -- low-detail silhouette towers on concentric rings
  beyond the world that break the horizon.  Heights live in per-ring height
  bands that step down with distance, so a farther ring is lower on average.
* ``atmosphere`` -- fog presets; ``view_distance_cm`` is derived from
  ``half_diagonal_cm`` (arithmetic in the docstring).
* ``build_backdrop`` -- assembles all of the above into one schema dict.

Determinism laws (mirroring ``ldyf.roads`` / ``ldyf.city_layout``): pure
stdlib, no ``import unreal``, never the ``random`` module.  Every float goes
through ``_f3`` (round to 3 decimals, kill ``-0.0``).  All randomness comes
from ``sha256(f"{seed}|{ring}|{i}")`` hexdigest slices mapped into ranges, so a
replay of the same road spec reproduces the same skyline byte for byte
(``json.dumps(spec, sort_keys=True)``).  Lists are iterated in ascending id
order before emission.

Coordinate conventions: X east, Y south, Z up, centimetres (the same frame the
road spec uses).  Corner lists are wound consistently for every quad of a ring
(the orientation is uniform even though it does not matter which handedness).
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

BACKDROP_VERSION = "backdrop_spec_v1"

# Defaults used by build_backdrop when the caller does not override.  They are
# expressed relative to the world's own half_diagonal_cm so a bare call scales
# with the city instead of inventing an absolute size.
_DEFAULT_SKIRT_SEGMENTS = 64
_DEFAULT_RINGS = 3
_DEFAULT_PER_RING = 14

# Presentation presets (deterministic constants, documented in atmosphere()).
_FOG_HEIGHT_FALLOFF = 0.4       # vertical haze falloff, per km
_SKY_INFLUENCE = 0.6


# --- small deterministic helpers -------------------------------------------


def _f3(v: float) -> float:
    """Round to 3 decimals (cm resolution) and kill ``-0.0`` (byte determinism)."""
    return round(float(v), 3) + 0.0


def _positive_int(name: str, v: Any) -> int:
    """Coerce ``v`` to an int and require it to be strictly positive.

    Accepts integral floats such as ``8.0``; rejects ``0``, negatives and
    fractional values with a ``ValueError`` (matches the module's validation
    contract).
    """
    if isinstance(v, bool):
        raise ValueError(f"{name} must be a positive integer, got {v!r}")
    try:
        n = int(v)
    except (TypeError, ValueError) as exc:  # e.g. None, "8"
        raise ValueError(f"{name} must be a positive integer, got {v!r}") from exc
    if n <= 0 or n != v:
        raise ValueError(f"{name} must be a positive integer, got {v!r}")
    return n


def _slice01(hexd: str, start: int) -> float:
    """4 hex chars -> (0.0, 1.0].

    ``0x0000`` maps to ``1/65536`` (never zero) so a value drawn from a band
    is always strictly inside the band; ``0xffff`` maps to exactly 1.0.  The
    strict lower bound is what makes consecutive massing height bands touch
    without ever sharing a height (see ``backdrop_massing``).
    """
    return (int(hexd[start:start + 4], 16) + 1) / 65536.0


# --- 1. world bounds --------------------------------------------------------


def world_bounds(road_spec: dict) -> dict:
    """Bounding box of every lane polyline point in the road spec (cm).

    Walks the nesting ``roads.py`` actually emits: ``spec["edges"]`` (a list
    of edge dicts) -> ``edge["lanes"]`` (a list of lane dicts) ->
    ``lane["polyline"]`` (a list of ``{"x", "y", "z"}`` points).  Edges with no
    lanes, and lanes with an empty/absent polyline, are skipped.  No edge is
    filtered by ``function``: internal and crossing edges are part of the
    built world and must extend the bounds too.

    Returns keys ``min_x, min_y, max_x, max_y, centre_x, centre_y,
    half_diagonal_cm`` (all floats rounded to 3 decimals).  An empty spec has
    no extent; the function returns a degenerate all-zero bbox so callers can
    decide how to react (the builders reject degenerate geometry).
    """
    xs: list[float] = []
    ys: list[float] = []
    for edge in road_spec.get("edges", []):
        for lane in edge.get("lanes", []):
            for pt in lane.get("polyline") or []:
                xs.append(float(pt["x"]))
                ys.append(float(pt["y"]))
    if not xs:
        return {"min_x": 0.0, "min_y": 0.0, "max_x": 0.0, "max_y": 0.0,
                "centre_x": 0.0, "centre_y": 0.0, "half_diagonal_cm": 0.0}
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    centre_x, centre_y = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
    half_diagonal = math.hypot(max_x - min_x, max_y - min_y) / 2.0
    return {"min_x": _f3(min_x), "min_y": _f3(min_y),
            "max_x": _f3(max_x), "max_y": _f3(max_y),
            "centre_x": _f3(centre_x), "centre_y": _f3(centre_y),
            "half_diagonal_cm": _f3(half_diagonal)}


# --- 2. ground skirt -------------------------------------------------------


def skirt_ring(bounds: dict, *, inner_margin_cm: float,
               outer_radius_cm: float, segments: int) -> list[dict]:
    """Annulus of ``segments`` ground quads continuing the ground outward.

    The ring is a polar annulus around ``bounds["centre_*"]``:

    * inner radius  = ``half_diagonal_cm + inner_margin_cm`` -- a circle that
      fully contains the world bbox (the bbox's circumcircle has radius exactly
      ``half_diagonal_cm``).
    * outer radius  = ``outer_radius_cm``.
    * quad ``i`` spans the angular step ``[i*2*pi/segments, (i+1)*2*pi/segments]``
      with corners ``[inner-left, inner-right, outer-right, outer-left]``, all
      wound with the same orientation.

    Closure argument: the quad for step ``i`` ends at angle
    ``(i+1)*2*pi/segments`` and the quad for step ``i+1`` starts at exactly the
    same angle, so their radial edges are computed from the *same* ``(cos, sin)``
    inputs and are bit-identical (the inner-right corner of quad ``i`` equals
    the inner-left corner of quad ``i+1``, and likewise for the outer corners).
    The last quad ends at ``2*pi``; ``cos(2*pi) == cos(0) == 1.0`` and
    ``sin(2*pi)*r`` is about ``-2.4e-16 * r`` cm, which rounds to ``0.0`` at 3
    decimals, so the seam back onto quad 0 is equally gap-free.  Every angular
    direction between the two radii is therefore covered: there is no seam and
    in particular no diagonal corner gap.

    Raises ``ValueError`` for a non-positive ``segments``, a non-positive
    ``outer_radius_cm``, an ``outer_radius_cm`` smaller than the world's own
    ``half_diagonal_cm``, or an outer radius that does not even clear the ring's
    own inner radius (a degenerate annulus).
    """
    seg = _positive_int("segments", segments)
    outer_radius_cm = float(outer_radius_cm)
    if outer_radius_cm <= 0.0:
        raise ValueError(f"outer_radius_cm must be positive, got {outer_radius_cm}")
    half = float(bounds["half_diagonal_cm"])
    if outer_radius_cm < half:
        raise ValueError(
            f"outer_radius_cm ({outer_radius_cm}) is smaller than the world's "
            f"half_diagonal_cm ({half})")
    inner_radius = _f3(half + float(inner_margin_cm))
    outer_radius = _f3(outer_radius_cm)
    if outer_radius <= inner_radius:
        raise ValueError(
            f"outer_radius_cm ({outer_radius}) must exceed the ring inner "
            f"radius half_diagonal_cm + inner_margin_cm ({inner_radius})")

    cx, cy = float(bounds["centre_x"]), float(bounds["centre_y"])
    two_pi = 2.0 * math.pi
    quads: list[dict] = []
    for i in range(seg):
        a0 = two_pi * i / seg
        a1 = two_pi * (i + 1) / seg
        c0, s0 = math.cos(a0), math.sin(a0)
        c1, s1 = math.cos(a1), math.sin(a1)
        corners = [
            [_f3(cx + inner_radius * c0), _f3(cy + inner_radius * s0)],
            [_f3(cx + inner_radius * c1), _f3(cy + inner_radius * s1)],
            [_f3(cx + outer_radius * c1), _f3(cy + outer_radius * s1)],
            [_f3(cx + outer_radius * c0), _f3(cy + outer_radius * s0)],
        ]
        quads.append({"id": f"skirt_{i:04d}", "corners": corners})
    return quads


def _point_in_quad(corners: list[list[float]], x: float, y: float,
                   tol: float = 1e-6) -> bool:
    """Convex-quad containment via edge cross products.

    For a convex quad all edge cross products with the query point share one
    sign when the point is inside (or on) the polygon.  Values within ``tol``
    of zero are treated as "on the boundary" (inside), which is what lets a
    probe placed on a shared radial edge between two quads count as covered by
    either neighbour.
    """
    signs: set[int] = set()
    for k in range(4):
        ax, ay = corners[k]
        bx, by = corners[(k + 1) % 4]
        cross = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
        if cross > tol:
            signs.add(1)
        elif cross < -tol:
            signs.add(-1)
    return len(signs) <= 1


def point_in_ring(bounds: dict, ring: list[dict], x: float, y: float) -> bool:
    """True when ``(x, y)`` lies inside (or on) some quad of the ring.

    ``bounds`` is accepted for signature symmetry with the other builders; only
    ``ring`` is consulted.  Used by tests to probe just outside the world on
    the four side directions and the four diagonal corner directions.
    """
    for quad in ring:
        if _point_in_quad(quad["corners"], x, y):
            return True
    return False


# --- 3. skyline massing ----------------------------------------------------


def backdrop_massing(bounds: dict, *, rings: int, per_ring: int,
                     min_h_cm: float, max_h_cm: float, ring_gap_cm: float,
                     seed: int, inner_margin_cm: float = 0.0) -> list[dict]:
    """Distant low-detail silhouettes on concentric rings beyond the city.

    Placement: ring ``r`` (0 = nearest, highest) sits at radius
    ``clear + ring_gap_cm * (r + 1)`` around the world centre, where
    ``clear`` is the distance from the centre to a corner of the world bbox
    expanded by ``inner_margin_cm``: ``hypot((max_x-min_x)/2 + m,
    (max_y-min_y)/2 + m)``.  Every point of the expanded box is within that
    corner distance of the centre, so every building centre (on any ring, any
    angle) is strictly outside ``bounds`` expanded by ``inner_margin_cm``.

    Heights step down with distance *by construction*: the height range
    ``[min_h_cm, max_h_cm]`` is partitioned into ``rings`` equal bands and ring
    ``r`` is assigned band ``rings - 1 - r`` (nearest ring owns the tallest
    band).  Inside its band a building's height comes from a slice of
    ``sha256(f"{seed}|{ring}|{i}").hexdigest()`` mapped into ``(0.0, 1.0]``.
    Because the slice never maps to zero and adjacent bands touch exactly, the
    tallest building of a farther ring is strictly shorter than the shortest
    building of the nearer ring -- a farther ring is lower on average with no
    possible inversion.

    Footprint and yaw also come from slices of the same hexdigest (offsets 4,
    8, 12, 16): ``width/depth`` scale with the building's height and ``yaw``
    sweeps ``[0, 360)``.  Each entry is
    ``{"id", "x", "y", "yaw_deg", "w_cm", "d_cm", "h_cm", "ring"}`` and the
    list is emitted in ascending id order.

    Raises ``ValueError`` for a non-positive ``rings`` or ``per_ring``, a
    non-positive ``ring_gap_cm``, or ``max_h_cm < min_h_cm``.
    """
    rings_n = _positive_int("rings", rings)
    per_ring_n = _positive_int("per_ring", per_ring)
    ring_gap_cm = float(ring_gap_cm)
    if ring_gap_cm <= 0.0:
        raise ValueError(f"ring_gap_cm must be positive, got {ring_gap_cm}")
    min_h = float(min_h_cm)
    max_h = float(max_h_cm)
    if max_h < min_h:
        raise ValueError(f"max_h_cm ({max_h}) must be >= min_h_cm ({min_h})")

    m = float(inner_margin_cm)
    half_w = (float(bounds["max_x"]) - float(bounds["min_x"])) / 2.0 + m
    half_h = (float(bounds["max_y"]) - float(bounds["min_y"])) / 2.0 + m
    clear = math.hypot(half_w, half_h)
    cx, cy = float(bounds["centre_x"]), float(bounds["centre_y"])

    span = max_h - min_h
    band_w = span / rings_n
    two_pi = 2.0 * math.pi
    out: list[dict] = []
    for r in range(rings_n):
        # Nearest ring (r == 0) owns the top band (index rings_n - 1 - r).
        band_top = rings_n - 1 - r
        lo = min_h + span * band_top / rings_n
        hi = lo + band_w
        radius = clear + ring_gap_cm * (r + 1)
        for i in range(per_ring_n):
            hexd = hashlib.sha256(
                f"{seed}|{r}|{i}".encode("utf-8")).hexdigest()
            u_h = _slice01(hexd, 0)    # (0.0, 1.0] within this ring's band
            u_w = _slice01(hexd, 4)
            u_d = _slice01(hexd, 8)
            u_yaw = _slice01(hexd, 12)
            u_ang = _slice01(hexd, 16)
            height = lo + (hi - lo) * u_h
            width = height * (0.5 + 0.35 * u_w)
            depth = height * (0.5 + 0.35 * u_d)
            yaw = u_yaw * 360.0
            theta = two_pi * (i + u_ang) / per_ring_n
            x = cx + radius * math.cos(theta)
            y = cy + radius * math.sin(theta)
            out.append({
                "id": f"massing_{r:03d}_{i:03d}",
                "x": _f3(x), "y": _f3(y),
                "yaw_deg": _f3(yaw),
                "w_cm": _f3(width), "d_cm": _f3(depth), "h_cm": _f3(height),
                "ring": r,
            })
    return out


# --- 4. atmosphere ---------------------------------------------------------


def atmosphere(bounds: dict) -> dict:
    """Fog/haze settings that sell distance.

    ``view_distance_cm`` is derived from the world: ``5.0 * half_diagonal_cm``
    (rounded to 3 decimals).  With ``build_backdrop``'s defaults the ground
    skirt ends at ``2.6 * half_diagonal_cm`` and the outermost default massing
    ring sits inside ``~2.5 * half_diagonal_cm`` (corner clear ``<= sqrt(2) *
    half`` plus two ``0.35 * half`` gaps), so five times ``half_diagonal_cm``
    keeps the whole built backdrop inside the fog view with margin to spare.
    ``fog_density`` is derived from that view distance so horizontal
    transmittance at the view distance is about 2%:
    ``fog_density = -ln(0.02) / (view_distance_cm / 100000.0)`` (per kilometre,
    which keeps the value comfortably above 3-decimal rounding).  The other
    three values are deterministic presets (documented in the module header).
    """
    half = float(bounds["half_diagonal_cm"])
    view_distance = _f3(5.0 * half)
    start_distance = _f3(1.6 * half)
    fog_density = _f3(-math.log(0.02) / (view_distance / 100000.0))
    return {"fog_density": fog_density,
            "fog_height_falloff": _f3(_FOG_HEIGHT_FALLOFF),
            "start_distance_cm": start_distance,
            "view_distance_cm": view_distance,
            "sky_influence": _f3(_SKY_INFLUENCE)}


# --- 5. assembly -----------------------------------------------------------


def build_backdrop(road_spec: dict, **kw: Any) -> dict:
    """Assemble the whole backdrop for a ``road_spec_v1``.

    Returns ``{"schema_version": "backdrop_spec_v1", "bounds", "skirt",
    "massing", "atmosphere", "counts"}``.  Unknown keyword arguments are
    ignored; every known one is forwarded to the matching builder.  Defaults
    are derived from the world's own ``half_diagonal_cm`` so a bare call scales
    with the city:

    * skirt ``inner_margin_cm=0``, ``outer_radius_cm=2.6*half_diagonal_cm``,
      ``segments=64``;
    * massing ``rings=3``, ``per_ring=14``, heights in
      ``[0.18, 0.55] * half_diagonal_cm``, ``ring_gap_cm=0.35*half_diagonal_cm``
      (outermost ring ``<= ~2.5*half_diagonal_cm``, inside the default skirt);
    * ``seed=0``.

    Deterministic: ``json.dumps(result, sort_keys=True)`` is byte-identical
    across runs of the same road spec.
    """
    bounds = world_bounds(road_spec)
    half = bounds["half_diagonal_cm"]

    inner_margin = kw.get("inner_margin_cm", 0.0)
    skirt = skirt_ring(
        bounds,
        inner_margin_cm=inner_margin,
        outer_radius_cm=kw.get("outer_radius_cm", _f3(2.6 * half)),
        segments=kw.get("segments", _DEFAULT_SKIRT_SEGMENTS),
    )
    massing = backdrop_massing(
        bounds,
        rings=kw.get("rings", _DEFAULT_RINGS),
        per_ring=kw.get("per_ring", _DEFAULT_PER_RING),
        min_h_cm=kw.get("min_h_cm", _f3(0.18 * half)),
        max_h_cm=kw.get("max_h_cm", _f3(0.55 * half)),
        ring_gap_cm=kw.get("ring_gap_cm", _f3(0.35 * half)),
        seed=kw.get("seed", 0),
        inner_margin_cm=inner_margin,
    )
    atmos = atmosphere(bounds)

    skirt = sorted(skirt, key=lambda q: q["id"])
    massing = sorted(massing, key=lambda e: e["id"])
    rings_used = (max((e["ring"] for e in massing), default=-1) + 1
                  if massing else 0)
    counts = {
        "skirt_quads": len(skirt),
        "massing_entries": len(massing),
        "rings": rings_used,
        "per_ring": (len(massing) // rings_used) if rings_used else 0,
    }
    return {"schema_version": BACKDROP_VERSION,
            "bounds": bounds,
            "skirt": skirt,
            "massing": massing,
            "atmosphere": atmos,
            "counts": counts}
