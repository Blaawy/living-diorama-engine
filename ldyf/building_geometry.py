"""``building_geometry_v1`` â€” turn ``building_kits_v1`` descriptions into mesh.

Why this file exists (same argument as ``ldyf.tree_mesh``): ``ldyf.building_kits``
describes six facade families, height bands, setbacks, entrances and a civic
landmark, but nothing in ``ldyf`` ever turns that description into vertices.
The buildings on screen are still single extruded boxes. This module emits a
stepped mass (plinth / shaft / setback upper mass / parapet) per building, in
raw mesh data an editor driver can hand to Unreal, carrying the four material
slots the driver should bind:

=====  ===========================
slot   meaning
=====  ===========================
0      wall
1      roof (and any horizontal upward cap: plinth ledge and setback tread
       are capping surfaces and carry the roof slot)
2      ground floor / shopfront (the plinth band's vertical faces)
3      parapet
=====  ===========================

Everything here is pure stdlib, deterministic (geometry is a pure function of
the spec dicts; ``seed`` is accepted for driver symmetry and echoed into
``counts`` but is never turned into ``random`` variation), and every emitted
float goes through ``_f3`` (round to 3 decimals, normalise ``-0.0``) exactly
like the rest of ``ldyf``.

Schema ``building_geometry_v1``
-------------------------------
A document returned by :func:`building_mesh` is::

    {
      "schema_version": "building_geometry_v1",
      "kind": "building",                       # or "landmark"
      "vertices": [[x, y, z], ...],             # cm, Z up
      "triangles": [[i, j, k], ...],
      "uvs": [[u, v], ...],                     # one per vertex, METRES
      "material_slot_per_triangle": [0|1|2|3, ...],
      "counts": {...},
      "bounds": {...},
    }

Conventions
-----------
* Coordinates in centimetres, Z up. The footprint corners sit in the
  ``z == 0`` plane, so a driver that places buildings with ``min_z`` on grade
  (the dressing editor's contact-offset convention, same as tree trunks) puts
  the plinth base on the ground with no extra bookkeeping.
* Vertices are duplicated per triangle (triangle ``k`` owns rows ``3k..3k+2``),
  which keeps index arithmetic boring and per-corner UVs trivial, exactly like
  ``tree_mesh``.
* **UVs are in metres, not normalised** â€” ``u`` is distance along the ring
  perimeter in metres and ``v`` is height above grade in metres for vertical
  faces; horizontal caps map ``u = (x - min_x)/100``, ``v = (y - min_y)/100``
  in metres. A tiling facade material therefore gets a real architectural
  scale straight out of the mesh.
* Ring corners are re-ordered by angle about the centroid and forced to
  counter-clockwise (viewed from +z) before anything is emitted, so a caller
  may pass its footprint corners in any order and either winding.
* ``counts["rings"]`` records the horizontal outline of every construction
  band (plinth / lower shaft / upper mass / roof deck / parapet) so geometry
  checks can verify plinth proudness, setback insets and parapet enclosure
  without re-deriving polygons from triangle soup.

Triangle budget per building (252 buildings will be instanced)
--------------------------------------------------------------
All bands are built from the same ring of ``n`` corners (4 for a real slot);
per band the counts are ``sides = 2n``, ``top cap = n``.  A stepped building
with a parapet is the most expensive case (``n = 4``):

    plinth      = 2n sides (slot 2) + n cap (slot 1)          = 12
    lower shaft = 2n sides (slot 0) + n cap (slot 1)          = 12
    upper mass  = 2n sides (slot 0)                           =  8
    parapet     = 2n outer + 2n inner + n deck cap + 2n top   = 28
    ----------------------------------------------------------------
    total                                                     = 60 triangles

so every building is at most **60 triangles / 180 vertices**.  The same
building without a parapet is 36; a flat single-mass building is 24.
252 instanced stepped buildings are at most 252 * 60 ~= 15.1k triangles, a
trivial ISM budget next to the street trees (117k at 240 maples), and every
building is a *stepped* solid: the ground floor band is a plinth proud of the
wall above it, and â€” where the kits call for one â€” the roof carries a parapet
upstand so the roofline reads as an edge, not a bare cap.

:func:`landmark_mesh` builds the civic landmark from the stacked
boxes/cylinders of ``building_kits.landmark_spec``; cylinders are approximated
by prisms with :data:`PRISM_SIDES` sides.
"""

from __future__ import annotations

import math
from typing import Any

SCHEMA_VERSION = "building_geometry_v1"

# --------------------------------------------------------------------------
# material slots (documented contract for the editor driver)
# --------------------------------------------------------------------------

MAT_WALL = 0          # vertical wall faces of the shaft / upper mass / landmark
MAT_ROOF = 1          # roof deck caps + any horizontal upward cap (ledge/tread)
MAT_GROUND = 2        # ground-floor band (plinth) vertical faces
MAT_PARAPET = 3       # parapet upstand faces + its top cap

MATERIAL_SLOTS = {
    "wall": MAT_WALL,
    "roof": MAT_ROOF,
    "ground": MAT_GROUND,
    "parapet": MAT_PARAPET,
}
ALL_SLOTS = (MAT_WALL, MAT_ROOF, MAT_GROUND, MAT_PARAPET)

# Construction parameters (cm). PLINTH_PROUD_CM is how far the ground-floor
# band stands proud of the wall above it on every side; PARAPET_THICKNESS_CM
# is how far the roof deck is set in from the parapet's outer face.
PLINTH_PROUD_CM = 20.0
PARAPET_THICKNESS_CM = 15.0
PRISM_SIDES = 10      # landmark cylinders are approximated by this many sides


# --------------------------------------------------------------------------
# deterministic plumbing (rounded emission helpers)
# --------------------------------------------------------------------------

def _f3(v: float) -> float:
    """Round to 3 decimals and normalise ``-0.0``."""
    r = round(float(v), 3)
    return 0.0 if r == 0.0 else r


def _v3(x: float, y: float, z: float) -> list[float]:
    return [_f3(x), _f3(y), _f3(z)]


def _uv(u: float, v: float) -> list[float]:
    return [_f3(u), _f3(v)]


def _new_geo() -> dict:
    return {"vertices": [], "triangles": [], "uvs": [], "slots": []}


def _cross(ax: float, ay: float, az: float,
           bx: float, by: float, bz: float) -> tuple[float, float, float]:
    return (ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx)


# --------------------------------------------------------------------------
# polygon plumbing: footprints and inset rings
# --------------------------------------------------------------------------

def _signed_area2(ring: list[tuple[float, float]]) -> float:
    total = 0.0
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        total += ring[i][0] * ring[j][1] - ring[j][0] * ring[i][1]
    return 0.5 * total


def _ordered_ring(footprint: Any) -> list[tuple[float, float]]:
    """Convex ring from ``[{x, y}, ...]``: centroid-ordered, counter-clockwise.

    Accepts corners in any order / winding (a convex quad is enough).  Raises
    ``ValueError`` when there are fewer than 3 corners, a corner is not
    finite, or the polygon has zero area.
    """
    if not isinstance(footprint, list) or len(footprint) < 3:
        raise ValueError("footprint needs at least 3 corners")
    pts: list[tuple[float, float]] = []
    for c in footprint:
        if not isinstance(c, dict):
            raise ValueError("footprint corners must be {x, y} dicts")
        x, y = float(c.get("x", float("nan"))), float(c.get("y", float("nan")))
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError("footprint corner has non-finite x/y")
        pts.append((x, y))
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    pts.sort(key=lambda p: (math.atan2(p[1] - cy, p[0] - cx), p[0], p[1]))
    if abs(_signed_area2(pts)) < 1e-6:
        raise ValueError("footprint corners are collinear (zero area)")
    if _signed_area2(pts) < 0.0:
        pts.reverse()
    return pts


def _outward_normals(ring: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Unit outward edge normals of a CCW ring (viewed from +z)."""
    n = len(ring)
    out: list[tuple[float, float]] = []
    for i in range(n):
        j = (i + 1) % n
        ex = ring[j][0] - ring[i][0]
        ey = ring[j][1] - ring[i][1]
        length = math.hypot(ex, ey)
        if length <= 0.0:
            raise ValueError("footprint has a zero-length edge")
        # CCW ring: interior on the left, outward is the right-hand normal.
        out.append((ey / length, -ex / length))
    return out


def _inset_ring(ring: list[tuple[float, float]],
                distance_cm: float) -> list[tuple[float, float]]:
    """Inset every side of a convex CCW ring by ``distance_cm`` (miter join)."""
    if distance_cm <= 0.0:
        return list(ring)
    outs = _outward_normals(ring)
    n = len(ring)
    inset: list[tuple[float, float]] = []
    for i in range(n):
        p = (i - 1) % n
        n1x, n1y = outs[p]
        n2x, n2y = outs[i]
        denom = 1.0 + (n1x * n2x + n1y * n2y)
        if denom <= 1e-9:
            raise ValueError(
                "footprint too tight to inset by "
                f"{distance_cm} cm (corner angle too sharp)")
        s = distance_cm / denom
        inset.append((ring[i][0] - s * (n1x + n2x),
                      ring[i][1] - s * (n1y + n2y)))
    return inset


def _ring_bbox(ring: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (min(xs), min(ys), max(xs), max(ys))


def _arcs_cm(ring: list[tuple[float, float]]) -> list[float]:
    """Cumulative perimeter distance at each corner (arc[0] == 0)."""
    arcs = [0.0]
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        arcs.append(arcs[-1]
                    + math.hypot(ring[j][0] - ring[i][0],
                                 ring[j][1] - ring[i][1]))
    return arcs[:n]


# --------------------------------------------------------------------------
# emission plumbing: one vertex row per triangle corner
# --------------------------------------------------------------------------

def _push_tri(geo: dict, corners: list[tuple[float, float, float]],
              uvs: list[tuple[float, float]], slot: int,
              want: tuple[float, float, float]) -> None:
    """Append one triangle wound so its normal points along ``want``."""
    a, b, c = corners
    u0, u1, u2 = uvs
    nx, ny, nz = _cross(b[0] - a[0], b[1] - a[1], b[2] - a[2],
                        c[0] - a[0], c[1] - a[1], c[2] - a[2])
    if nx * want[0] + ny * want[1] + nz * want[2] < 0.0:
        b, c = c, b
        u1, u2 = u2, u1
    base = len(geo["vertices"])
    for pos, uv in ((a, u0), (b, u1), (c, u2)):
        geo["vertices"].append(_v3(pos[0], pos[1], pos[2]))
        geo["uvs"].append(_uv(uv[0], uv[1]))
    geo["triangles"].append([base, base + 1, base + 2])
    geo["slots"].append(slot)


def _emit_side_band(geo: dict, ring: list[tuple[float, float]],
                    z0: float, z1: float, slot: int) -> None:
    """Vertical wall around a CCW ring between z0 and z1 (one quad per side)."""
    outs = _outward_normals(ring)
    arcs = _arcs_cm(ring)
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        ua = arcs[i] / 100.0
        ub = arcs[j] / 100.0
        v0 = z0 / 100.0
        v1 = z1 / 100.0
        ox, oy = outs[i]
        corners = [
            (ring[i][0], ring[i][1], z0),
            (ring[j][0], ring[j][1], z0),
            (ring[j][0], ring[j][1], z1),
            (ring[i][0], ring[i][1], z1),
        ]
        uvs = [(ua, v0), (ub, v0), (ub, v1), (ua, v1)]
        _push_tri(geo, [corners[0], corners[1], corners[2]],
                  [uvs[0], uvs[1], uvs[2]], slot, (ox, oy, 0.0))
        _push_tri(geo, [corners[0], corners[2], corners[3]],
                  [uvs[0], uvs[2], uvs[3]], slot, (ox, oy, 0.0))


def _emit_cap(geo: dict, ring: list[tuple[float, float]], z: float,
              slot: int, up: bool) -> None:
    """Fan cap of a CCW ring at height z (up=True faces +z)."""
    minx, miny, _, _ = _ring_bbox(ring)
    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    centre = (cx, cy, z)
    n = len(ring)
    want = (0.0, 0.0, 1.0 if up else -1.0)
    for i in range(n):
        j = (i + 1) % n
        a = (ring[i][0], ring[i][1], z)
        b = (ring[j][0], ring[j][1], z)
        if up:
            corners, uvs = [centre, a, b], [
                ((cx - minx) / 100.0, (cy - miny) / 100.0),
                ((ring[i][0] - minx) / 100.0, (ring[i][1] - miny) / 100.0),
                ((ring[j][0] - minx) / 100.0, (ring[j][1] - miny) / 100.0)]
        else:
            corners, uvs = [centre, b, a], [
                ((cx - minx) / 100.0, (cy - miny) / 100.0),
                ((ring[j][0] - minx) / 100.0, (ring[j][1] - miny) / 100.0),
                ((ring[i][0] - minx) / 100.0, (ring[i][1] - miny) / 100.0)]
        _push_tri(geo, corners, uvs, slot, want)


def _emit_annulus(geo: dict, outer: list[tuple[float, float]],
                  inner: list[tuple[float, float]], z: float, slot: int) -> None:
    """Up-facing ring strip between two CCW rings of equal corner count."""
    if len(outer) != len(inner):
        raise ValueError("annulus rings must share a corner count")
    minx, miny, _, _ = _ring_bbox(outer)
    n = len(outer)
    for i in range(n):
        j = (i + 1) % n
        corners = [
            (outer[i][0], outer[i][1], z),
            (outer[j][0], outer[j][1], z),
            (inner[j][0], inner[j][1], z),
            (inner[i][0], inner[i][1], z),
        ]
        uvs = [((p[0] - minx) / 100.0, (p[1] - miny) / 100.0)
               for p in (outer[i], outer[j], inner[j], inner[i])]
        _push_tri(geo, [corners[0], corners[1], corners[2]],
                  [uvs[0], uvs[1], uvs[2]], slot, (0.0, 0.0, 1.0))
        _push_tri(geo, [corners[0], corners[2], corners[3]],
                  [uvs[0], uvs[2], uvs[3]], slot, (0.0, 0.0, 1.0))


def _ring2d(ring: list[tuple[float, float]]) -> list[list[float]]:
    return [[_f3(x), _f3(y)] for x, y in ring]


# --------------------------------------------------------------------------
# document assembly
# --------------------------------------------------------------------------

def _finish(geo: dict, kind: str, counts: dict) -> dict:
    verts = geo["vertices"]
    counts = dict(counts)
    counts["triangles"] = len(geo["triangles"])
    counts["vertices"] = len(verts)
    tally: dict[int, int] = {}
    for s in geo["slots"]:
        tally[s] = tally.get(s, 0) + 1
    counts["slot_triangle_counts"] = {
        str(k): tally.get(k, 0) for k in ALL_SLOTS}
    bounds = {
        "min_x": _f3(min(v[0] for v in verts)),
        "min_y": _f3(min(v[1] for v in verts)),
        "min_z": _f3(min(v[2] for v in verts)),
        "max_x": _f3(max(v[0] for v in verts)),
        "max_y": _f3(max(v[1] for v in verts)),
        "max_z": _f3(max(v[2] for v in verts)),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "vertices": verts,
        "triangles": geo["triangles"],
        "uvs": geo["uvs"],
        "material_slot_per_triangle": geo["slots"],
        "counts": counts,
        "bounds": bounds,
    }


def _as_positive(name: str, value: Any) -> float:
    v = float(value or 0.0)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"{name} must be a positive finite number, got {value!r}")
    return v


# --------------------------------------------------------------------------
# building mesh
# --------------------------------------------------------------------------

def building_mesh(footprint: list, massing: dict, ground_floor: dict,
                  roof: dict, *, seed: Any) -> dict:
    """Stepped building mass from one ``building_kits_v1`` building entry.

    ``footprint`` is a list of ``{x, y}`` corners (a convex quad is enough),
    in cm, in the ground plane (``z == 0``).  ``massing``, ``ground_floor``
    and ``roof`` are the dicts returned by ``building_kits.massing_variation``,
    ``ground_floor_spec`` and ``roof_spec``.  The mesh is, bottom to top:

    * **plinth** â€” ground-floor band ``0 .. ground_floor["height_cm"]``,
      standing ``PLINTH_PROUD_CM`` proud of the wall above it on every side
      (slot 2 vertical faces);
    * **lower shaft** â€” from the plinth top to ``massing["setback_start_cm"]``
      (slot 0 walls);
    * **upper mass** â€” inset by ``massing["setback_cm"]`` on every side, up to
      ``massing["height_cm"]`` (slot 0 walls); only when a setback actually
      leaves room above the ground floor;
    * **parapet** â€” a ``roof["parapet_height_cm"]`` tall upstand around the
      roof edge (slot 3), with the roof deck set ``PARAPET_THICKNESS_CM``
      inside it (slot 1).  When ``parapet_height_cm`` is 0 no parapet band is
      emitted and the flat roof cap carries slot 1.

    Raises ``ValueError`` for a non-positive dimension, a ground floor not
    shorter than the building, or a setback so wide the inset upper mass
    would vanish.  ``seed`` is echoed into ``counts`` (deterministic only).
    """
    massing = massing or {}
    ground_floor = ground_floor or {}
    roof = roof or {}
    height = _as_positive("massing height_cm", massing.get("height_cm"))
    ground_h = _as_positive("ground_floor height_cm",
                            ground_floor.get("height_cm"))
    if ground_h >= height:
        raise ValueError(
            f"ground-floor band {ground_h} cm must be shorter than the "
            f"building height {height} cm")
    setback = float(massing.get("setback_cm") or 0.0)
    setback_start = float(massing.get("setback_start_cm") or 0.0)
    parapet_h = float(roof.get("parapet_height_cm") or 0.0)
    if setback < 0.0 or setback_start < 0.0:
        raise ValueError("setback_cm and setback_start_cm must be >= 0")
    if parapet_h < 0.0:
        raise ValueError("parapet_height_cm must be >= 0")

    ring = _ordered_ring(footprint)
    minx, miny, maxx, maxy = _ring_bbox(ring)
    bw = maxx - minx
    bd = maxy - miny
    if 2.0 * PLINTH_PROUD_CM >= min(bw, bd) - 1e-6:
        raise ValueError("footprint too small to carry a proud plinth "
                         f"(2 * {PLINTH_PROUD_CM} cm >= footprint side)")
    wall_ring = _inset_ring(ring, PLINTH_PROUD_CM)
    wminx, wminy, wmaxx, wmaxy = _ring_bbox(wall_ring)
    if 2.0 * setback >= min(wmaxx - wminx, wmaxy - wminy) - 1e-6:
        raise ValueError(
            f"setback {setback} cm too wide for footprint "
            f"({wmaxx - wminx:.1f} x {wmaxy - wminy:.1f} cm wall ring); "
            "2 * setback must be smaller")

    geo = _new_geo()
    gz = ground_h

    # ---- plinth: full footprint ring, ground band ----
    _emit_side_band(geo, ring, 0.0, gz, MAT_GROUND)
    _emit_cap(geo, ring, gz, MAT_ROOF, up=True)   # capping ledge (see slots)

    # ---- shaft / upper mass ----
    upper_start = max(setback_start, gz)
    upper_exists = (setback > 0.5 and setback_start > gz + 1.0
                    and height - upper_start > 1.0)
    if not upper_exists:
        top_ring = wall_ring
        _emit_side_band(geo, wall_ring, gz, height, MAT_WALL)
    else:
        top_ring = _inset_ring(wall_ring, setback)
        _emit_side_band(geo, wall_ring, gz, upper_start, MAT_WALL)
        _emit_cap(geo, wall_ring, upper_start, MAT_ROOF, up=True)  # tread
        _emit_side_band(geo, top_ring, upper_start, height, MAT_WALL)

    # ---- parapet / roof deck on top_ring ----
    rings = {
        "plinth": _ring2d(ring),
        "lower": _ring2d(wall_ring),
        "upper": _ring2d(top_ring),
    }
    if parapet_h > 0.0:
        deck_ring = _inset_ring(top_ring, PARAPET_THICKNESS_CM)
        _emit_side_band(geo, top_ring, height, height + parapet_h,
                        MAT_PARAPET)                          # outer face
        _emit_side_band(geo, deck_ring, height, height + parapet_h,
                        MAT_PARAPET)                          # inner face
        _emit_cap(geo, deck_ring, height, MAT_ROOF, up=True)  # roof deck
        _emit_annulus(geo, top_ring, deck_ring, height + parapet_h,
                      MAT_PARAPET)                            # parapet top
        rings["roof_deck"] = _ring2d(deck_ring)
        rings["parapet"] = _ring2d(top_ring)
    else:
        _emit_cap(geo, top_ring, height, MAT_ROOF, up=True)   # flat roof cap

    counts = {
        "kind": "building",
        "seed": seed,
        "budget_triangles": 60,   # 4-corner footprint, worst case (module doc)
        "rings": rings,
    }
    return _finish(geo, "building", counts)


# --------------------------------------------------------------------------
# landmark mesh
# --------------------------------------------------------------------------

def _rect_ring(cx: float, cy: float, sx: float,
               sy: float) -> list[tuple[float, float]]:
    hx, hy = sx / 2.0, sy / 2.0
    return _ordered_ring([{"x": cx - hx, "y": cy - hy},
                          {"x": cx + hx, "y": cy - hy},
                          {"x": cx + hx, "y": cy + hy},
                          {"x": cx - hx, "y": cy + hy}])


def _prism_ring(cx: float, cy: float, radius: float,
                sides: int) -> list[tuple[float, float]]:
    pts = []
    for i in range(sides):
        a = 2.0 * math.pi * i / sides
        pts.append({"x": cx + radius * math.cos(a),
                    "y": cy + radius * math.sin(a)})
    return _ordered_ring(pts)


def _emit_box(geo: dict, size_cm: list, offset_cm: list,
              wall_slot: int, cap_slot: int) -> None:
    sx, sy, sz = (float(size_cm[0]), float(size_cm[1]), float(size_cm[2]))
    ox, oy, oz = (float(offset_cm[0]), float(offset_cm[1]),
                  float(offset_cm[2]))
    if sx <= 0.0 or sy <= 0.0 or sz <= 0.0:
        raise ValueError("landmark box size_cm must be positive")
    ring = _rect_ring(ox, oy, sx, sy)
    z0, z1 = oz - sz / 2.0, oz + sz / 2.0
    _emit_side_band(geo, ring, z0, z1, wall_slot)
    _emit_cap(geo, ring, z1, cap_slot, up=True)
    if z0 > 0.0:
        _emit_cap(geo, ring, z0, wall_slot, up=False)


def _emit_prism(geo: dict, radius_cm: float, height_cm: float,
                offset_cm: list, wall_slot: int, cap_slot: int) -> None:
    r = float(radius_cm)
    h = float(height_cm)
    ox, oy, oz = (float(offset_cm[0]), float(offset_cm[1]),
                  float(offset_cm[2]))
    if r <= 0.0 or h <= 0.0:
        raise ValueError("landmark cylinder radius_cm/height_cm must be positive")
    ring = _prism_ring(ox, oy, r, PRISM_SIDES)
    z0, z1 = oz - h / 2.0, oz + h / 2.0
    _emit_side_band(geo, ring, z0, z1, wall_slot)
    _emit_cap(geo, ring, z1, cap_slot, up=True)
    if z0 > 0.0:
        _emit_cap(geo, ring, z0, wall_slot, up=False)


def landmark_mesh(landmark_spec: dict, *, seed: Any) -> dict:
    """Civic landmark from ``building_kits.landmark_spec``.

    Consumes the stacked ``parts`` (``box`` and ``cylinder`` entries with
    ``size_cm``/``radius_cm``/``height_cm`` and ``offset_cm`` in the slot's
    local frame) and emits each as a solid: vertical faces carry the wall
    slot (0) and every horizontal top cap carries the roof slot (1) â€” the
    landmark's slot-1 use is the roof of each stepped level.  Cylinders are
    approximated by regular prisms with :data:`PRISM_SIDES` (10) sides.  The
    returned document has the same ``building_geometry_v1`` shape as
    :func:`building_mesh`; its ``counts["prism_sides"]`` states the side
    count.  Raises ``ValueError`` for an empty parts list or a part with a
    non-positive dimension.
    """
    parts = (landmark_spec or {}).get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("landmark_spec needs a non-empty parts list")
    geo = _new_geo()
    n_box = n_cyl = 0
    for part in parts:
        kind = part.get("kind")
        if kind == "box":
            _emit_box(geo, part["size_cm"], part["offset_cm"],
                      MAT_WALL, MAT_ROOF)
            n_box += 1
        elif kind == "cylinder":
            _emit_prism(geo, part["radius_cm"], part["height_cm"],
                        part["offset_cm"], MAT_WALL, MAT_ROOF)
            n_cyl += 1
        else:
            raise ValueError(f"landmark part has unknown kind {kind!r}")
    counts = {
        "kind": "landmark",
        "seed": seed,
        "prism_sides": PRISM_SIDES,
        "boxes": n_box,
        "cylinders": n_cyl,
    }
    return _finish(geo, "landmark", counts)


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def _finite(vals: Any) -> bool:
    for v in vals:
        if not math.isfinite(float(v)):
            return False
    return True


def _point_in_ring(x: float, y: float,
                   ring: list[tuple[float, float]]) -> bool:
    """Ray-cast point-in-polygon test (points on the boundary count as out)."""
    inside = False
    n = len(ring)
    for i in range(n):
        j = (i + 1) % n
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and \
                x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
    return inside


def validate_geometry(doc: dict) -> list[str]:
    """Problems with a ``building_geometry_v1`` doc; empty list means valid.

    Checks: schema version; per-triangle vertex ownership
    (``len(vertices) == 3 * len(triangles) == len(uvs)``); triangle indices in
    range; ``material_slot_per_triangle`` length matches and every slot is in
    ``0..3``; no degenerate (zero-area) triangle; every triangle whose
    up-facing normal is not slot 1 (roof) or 3 (parapet); no NaN/infinite
    coordinate or UV; and â€” when ``counts["rings"]`` carries a parapet (only
    buildings with ``parapet_height_cm > 0`` do) â€” a parapet ring that
    encloses the roof deck ring.
    """
    problems: list[str] = []
    if not isinstance(doc, dict):
        return ["document is not a dict"]
    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version is not {SCHEMA_VERSION}")
    verts = doc.get("vertices")
    tris = doc.get("triangles")
    uvs = doc.get("uvs")
    slots = doc.get("material_slot_per_triangle")
    if not isinstance(verts, list) or not isinstance(tris, list):
        return problems + ["vertices/triangles must be lists"]
    if not isinstance(uvs, list):
        problems.append("uvs missing")
        uvs = []
    if not isinstance(slots, list):
        problems.append("material_slot_per_triangle missing")
        slots = []
    if len(verts) != 3 * len(tris):
        problems.append(
            f"vertices length {len(verts)} != 3 * triangles {len(tris)}")
    if len(uvs) != len(verts):
        problems.append(
            f"uvs length {len(uvs)} != vertices length {len(verts)}")
    if len(slots) != len(tris):
        problems.append(
            "material_slot_per_triangle length "
            f"{len(slots)} != triangles length {len(tris)}")
    nv = len(verts)

    def tri_broken(t: Any) -> bool:
        if not isinstance(t, list) or len(t) != 3:
            return True
        return t[0] < 0 or t[0] >= nv or t[1] < 0 or t[1] >= nv \
            or t[2] < 0 or t[2] >= nv

    for k, t in enumerate(tris):
        if tri_broken(t):
            problems.append(f"triangle {k} index out of range")
            continue
        a, b, c = verts[t[0]], verts[t[1]], verts[t[2]]
        if not (_finite(a) and _finite(b) and _finite(c)):
            problems.append(f"triangle {k} has NaN/inf vertex")
            continue
        ux = b[0] - a[0]
        uy = b[1] - a[1]
        uz = b[2] - a[2]
        vx = c[0] - a[0]
        vy = c[1] - a[1]
        vz = c[2] - a[2]
        cxn = _cross(ux, uy, uz, vx, vy, vz)
        cross_len = math.hypot(cxn[0], math.hypot(cxn[1], cxn[2]))
        if cross_len < 1e-6:
            problems.append(f"triangle {k} is degenerate")
            continue
        slot = slots[k] if 0 <= k < len(slots) else None
        # Upward-facing means the triangle normal is mostly vertical with
        # positive z.  Only the roof slot (1) and the parapet slot (3) may
        # look up: wall treatment must never land on a roof (the historical
        # roof-banding defect).  A direction test (not exact zero) keeps
        # vertical walls safe when setbacks carry 3-decimal fractions.
        if cxn[2] > 0.5 * cross_len and slot not in (MAT_ROOF, MAT_PARAPET):
            problems.append(
                f"triangle {k} faces up (normal z>0) but has slot {slot}")
    for k, s in enumerate(slots):
        if s not in ALL_SLOTS:
            problems.append(f"slot {s} at triangle {k} not in 0..3")
    for k, uv in enumerate(uvs):
        if not (isinstance(uv, list) and len(uv) == 2
                and math.isfinite(float(uv[0])) and math.isfinite(float(uv[1]))):
            problems.append(f"uv {uv} at vertex {k} is not a finite pair")

    # parapet enclosure check (building docs with a parapet only)
    rings = (doc.get("counts") or {}).get("rings")
    if isinstance(rings, dict) and "parapet" in rings:
        para = rings.get("parapet")
        deck = rings.get("roof_deck")
        if not isinstance(deck, list) or len(deck) < 3:
            problems.append("rings.roof_deck missing")
        else:
            p_ring = [(float(p[0]), float(p[1])) for p in para]
            d_ring = [(float(p[0]), float(p[1])) for p in deck]
            for x, y in d_ring:
                if not _point_in_ring(x, y, p_ring):
                    problems.append(
                        "parapet does not enclose the roof deck "
                        f"(deck corner ({x}, {y}) outside parapet ring)")
    return problems
