"""``tree_mesh_v1`` - street-tree geometry we generate ourselves, end to end.

Why this file exists (context recorded in ``ldyf.dressing_assets``): every
imported tree in this project renders bare. The City Sample prop kits are
branch skeletons with no leaf cards at all, and the Megascans Megaplants trees
have real leaf sections that render nothing under the shipped material, with
Nanite on, with Nanite off, and under a purpose-authored masked two-sided
material with its texture verified bound. The Director closed that path: this
module generates trunk + branches + leaf cards of our own, in raw mesh data an
editor driver can hand to Unreal, carrying the two material slots the driver
already expects (0 = bark, 1 = leaf).

Everything here is pure stdlib, deterministic (``hashlib.sha256`` digests of
stable strings, never the ``random`` module), and ``_f3``-rounded like the rest
of ``ldyf``.

Schema ``tree_mesh_v1``
-----------------------
A document returned by :func:`tree_mesh` is::

    {
      "schema_version": "tree_mesh_v1",
      "variant": "maple",
      "vertices": [[x, y, z], ...],        # cm, Z-up
      "triangles": [[i, j, k], ...],
      "normals": [[x, y, z], ...],         # one per vertex
      "uvs": [[u, v], ...],                # one per vertex, 0..1 per leaf card
      "up_bias": [0.0, ...],               # one scalar per vertex; 0 on bark,
                                           # leaf cards 0..1 (see leaf_cards)
      "material_slot_per_triangle": [0|1, ...],
      "counts": {...},
      "bounds": {...},
    }

Conventions
-----------
* Coordinates in centimetres, Z up. The trunk's base disk lies exactly in
  ``z == 0``, so a driver that places trees with their mesh-space ``min_z`` on
  the ground (the dressing editor's contact-offset convention, see
  ``ldyf.unreal.ldyf_dressing_editor.build_trees`` and
  ``ldyf.dressing_check.check_ground_contact``) puts the tree base at grade
  with no extra bookkeeping.
* Every float is emitted through ``_f3`` (round to 3 decimals, normalise
  ``-0.0``).
* Vertices are duplicated per triangle: each triangle owns its three vertex
  rows and rows are not shared between triangles. That makes per-corner
  normals and UVs trivial and keeps index arithmetic boring (triangle ``k``
  owns rows ``3k..3k+2``). At these budgets duplication costs nothing.
* Leaves come last and are emitted two triangles per card, in card order, so
  ``material_slot_per_triangle`` reads: a bark run then a leaf run; consecutive
  leaf-triangle pairs form one card each. ``validate_mesh`` relies on this.
* Leaf cards carry a *masked* material slot: the quad itself is a flat sheet
  of two triangles; whether it looks like a leaf is the material's job. The
  material must be two-sided, exactly like the purpose-authored one mentioned
  above, because the cards' stored normal is the outward crown normal, not
  the card-plane normal (see :func:`leaf_cards`). Each leaf card additionally
  emits an ``up_bias`` scalar (0..1) per vertex so a material driver can let
  sky-facing cards catch more light; the value is data only.

Triangle budget (240 trees will be instanced; one mesh per variant)
-------------------------------------------------------------------
All three variants share the same construction parameters, only the counts
differ, so the arithmetic is checkable in one place. With trunk 10 sides and 3
segments, branches 8 sides and 2 segments, B branches and C cards:

    trunk_tris    = 10 * (2*3 + 2) = 80     for every variant
    branch_tris   =  8 * (2*2 + 2) = 48     per branch
    card_tris     = 2 * C

    maple     B = 6, C = 130  ->  80 + 6*48 + 260 = 628 triangles
    columnar  B = 4, C = 110  ->  80 + 4*48 + 220 = 492 triangles
    sapling   B = 3, C = 62   ->  80 + 3*48 + 124 = 348 triangles

The canopy polish (ellipsoidal crown, shell-biased placement with ragged
radial jitter, per-card size, and the emitted ``up_bias``) costs no triangles:
it redistributes the same per-variant card budget inside :func:`leaf_cards`,
so these totals are unchanged from the spherical-crown version and the budget
test re-derives them from the construction parameters rather than trusting the
stored constant.

Every triangle owns 3 vertices, so the vertex counts are exactly three times
the triangle counts. 240 instanced maples at the worst case are
240 * 628 ~= 151k triangles, comfortably inside an ISM budget for street
furniture seen from 5-50 m. Each variant's constant is stated next to the
geometry parameters in :data:`TREE_VARIANTS`.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

SCHEMA_VERSION = "tree_mesh_v1"


# --------------------------------------------------------------------------
# deterministic digest plumbing
# --------------------------------------------------------------------------

def _hex(seed: Any, label: str) -> str:
    """sha256 hex digest of ``seed|label`` - the only source of variation."""
    return hashlib.sha256(f"{seed}|{label}".encode("utf-8")).hexdigest()


def _u01(seed: Any, label: str) -> float:
    """Deterministic float in [0, 1) from a digest."""
    return int(_hex(seed, label)[:16], 16) / float(1 << 64)


def _f3(v: float) -> float:
    """Round to 3 decimals and normalise ``-0.0``."""
    r = round(float(v), 3)
    return 0.0 if r == 0.0 else r


def _v3(x: float, y: float, z: float) -> list[float]:
    return [_f3(x), _f3(y), _f3(z)]


def _uv(u: float, v: float) -> list[float]:
    return [_f3(u), _f3(v)]


def _norm(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Unit vector; deterministic fallback for a zero input."""
    n = math.sqrt(x * x + y * y + z * z)
    if n == 0.0:
        return (0.0, 0.0, 1.0)
    return (x / n, y / n, z / n)


def _cross(ax: float, ay: float, az: float,
           bx: float, by: float, bz: float) -> tuple[float, float, float]:
    return (ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx)


# --------------------------------------------------------------------------
# emission plumbing: one vertex row per triangle corner
# --------------------------------------------------------------------------

def _new_geo() -> dict:
    return {"vertices": [], "triangles": [], "normals": [], "uvs": []}


def _tri(geo: dict, corners, normals, uvs) -> None:
    """Append one triangle as three private vertex rows."""
    base = len(geo["vertices"])
    for c, n, uv in zip(corners, normals, uvs):
        geo["vertices"].append(_v3(c[0], c[1], c[2]))
        geo["normals"].append(_v3(n[0], n[1], n[2]))
        geo["uvs"].append(_uv(uv[0], uv[1]))
    geo["triangles"].append([base, base + 1, base + 2])


def _ring_xyz(cx: float, cy: float, z: float, radius: float,
              sides: int) -> list[tuple[float, float, float]]:
    out = []
    for i in range(sides):
        a = 2.0 * math.pi * i / sides
        out.append((cx + radius * math.cos(a), cy + radius * math.sin(a), z))
    return out


def _side_normal(i: int, sides: int) -> tuple[float, float, float]:
    """Outward horizontal normal of a ring corner: radial in the XY plane."""
    a = 2.0 * math.pi * i / sides
    return (math.cos(a), math.sin(a), 0.0)


def _cap_uv(i: int, sides: int) -> tuple[float, float]:
    a = 2.0 * math.pi * i / sides
    return (0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a))


def _stacked_cylinder(geo: dict, x0: float, y0: float, z0: float,
                      x1: float, y1: float, z1: float,
                      r0: float, r1: float,
                      sides: int, segments: int) -> None:
    """Closed tapered stack of horizontal disks from base to top.

    Ring ``k`` sits at height fraction ``k/segments``; its centre drifts
    linearly from (x0, y0) to (x1, y1) and its radius tapers r0 -> r1, so a
    non-zero drift makes a *leaning* stack while every disk stays horizontal.
    The base disk lies in ``z == z0`` and the top disk in ``z == z1``; each is
    capped by a fan, so the surface has no open boundary.
    """
    rings: list[list[tuple[float, float, float]]] = []
    for k in range(segments + 1):
        t = k / segments
        z = z0 + (z1 - z0) * t
        cx = x0 + (x1 - x0) * t
        cy = y0 + (y1 - y0) * t
        r = r0 + (r1 - r0) * t
        rings.append(_ring_xyz(cx, cy, z, r, sides))
    bottom, top = rings[0], rings[-1]
    bottom_c = (x0, y0, z0)
    top_c = (x1, y1, z1)

    # side wall: one quad per (segment, side), split into two triangles.
    # Winding is CCW viewed from outside: cross(tangent_ccw, up) = outward.
    for k in range(segments):
        la, lb = rings[k], rings[k + 1]
        t_a, t_b = k / segments, (k + 1) / segments
        for i in range(sides):
            j = (i + 1) % sides
            n_i = _side_normal(i, sides)
            n_j = _side_normal(j, sides)
            # quad (la_i, la_j, lb_j, lb_i): the two triangles share the
            # diagonal (la_i, lb_j).
            _tri(geo,
                 (la[i], la[j], lb[j]),
                 (n_i, n_j, n_j),
                 ((i / sides, t_a), (j / sides, t_a), (j / sides, t_b)))
            _tri(geo,
                 (la[i], lb[j], lb[i]),
                 (n_i, n_j, n_i),
                 ((i / sides, t_a), (j / sides, t_b), (i / sides, t_b)))

    # bottom cap, facing down (-z): (centre, next, cur) winds downward.
    for i in range(sides):
        j = (i + 1) % sides
        _tri(geo,
             (bottom_c, bottom[j], bottom[i]),
             ((0.0, 0.0, -1.0),) * 3,
             ((0.5, 0.5), _cap_uv(j, sides), _cap_uv(i, sides)))
    # top cap, facing up (+z): (centre, cur, next) winds upward.
    for i in range(sides):
        j = (i + 1) % sides
        _tri(geo,
             (top_c, top[i], top[j]),
             ((0.0, 0.0, 1.0),) * 3,
             ((0.5, 0.5), _cap_uv(i, sides), _cap_uv(j, sides)))


# --------------------------------------------------------------------------
# public builders
# --------------------------------------------------------------------------

def trunk_geometry(*, height_cm: float, base_radius_cm: float,
                   top_radius_cm: float, sides: int, segments: int,
                   lean_deg: float, seed: Any) -> dict:
    """A closed tapered cylinder (base cap + top cap, no open boundary).

    The axis leans ``lean_deg`` from vertical; the lean azimuth is digested
    from ``seed`` so the same seed reproduces the same lean. Rings stay
    horizontal and the base disk lies in ``z == 0`` (see module conventions).
    """
    if height_cm <= 0.0 or base_radius_cm <= 0.0 or top_radius_cm <= 0.0:
        raise ValueError(
            "trunk_geometry: height/radii must be positive "
            f"(got {height_cm}, {base_radius_cm}, {top_radius_cm})")
    if sides < 3:
        raise ValueError(f"trunk_geometry: sides must be >= 3 (got {sides})")
    if segments < 1:
        raise ValueError(
            f"trunk_geometry: segments must be >= 1 (got {segments})")
    if lean_deg < 0.0:
        raise ValueError(
            f"trunk_geometry: lean_deg must be >= 0 (got {lean_deg})")
    slant = math.tan(math.radians(float(lean_deg)))
    yaw = 2.0 * math.pi * _u01(seed, "trunk|lean_yaw")
    dx = height_cm * slant * math.cos(yaw)
    dy = height_cm * slant * math.sin(yaw)
    geo = _new_geo()
    _stacked_cylinder(geo, 0.0, 0.0, 0.0,
                      dx, dy, float(height_cm),
                      float(base_radius_cm), float(top_radius_cm),
                      sides, segments)
    return geo


def branch_geometry(*, origin_z_cm: float, length_cm: float,
                    base_radius_cm: float, top_radius_cm: float,
                    sides: int, segments: int, incline_deg: float,
                    seed: Any) -> dict:
    """One closed tapered limb rising ``incline_deg`` off vertical.

    The limb's base centre sits on the trunk axis at ``origin_z_cm`` (inside
    the trunk, so the joint cannot show a gap); its azimuth is digested from
    ``seed``. A limb is the same closed stacked cylinder as the trunk.
    """
    if length_cm <= 0.0 or base_radius_cm <= 0.0 or top_radius_cm <= 0.0:
        raise ValueError(
            "branch_geometry: length/radii must be positive "
            f"(got {length_cm}, {base_radius_cm}, {top_radius_cm})")
    if sides < 3:
        raise ValueError(f"branch_geometry: sides must be >= 3 (got {sides})")
    if segments < 1:
        raise ValueError(
            f"branch_geometry: segments must be >= 1 (got {segments})")
    if not 0.0 <= incline_deg < 90.0:
        raise ValueError(
            f"branch_geometry: incline_deg must be in [0, 90) "
            f"(got {incline_deg})")
    incl = math.radians(float(incline_deg))
    az = 2.0 * math.pi * _u01(seed, "branch|azimuth")
    rise = length_cm * math.cos(incl)
    reach = length_cm * math.sin(incl)
    dx = reach * math.cos(az)
    dy = reach * math.sin(az)
    geo = _new_geo()
    _stacked_cylinder(geo, 0.0, 0.0, float(origin_z_cm),
                      dx, dy, float(origin_z_cm) + rise,
                      float(base_radius_cm), float(top_radius_cm),
                      sides, segments)
    return geo


# leaf-card cluster controls, shared by every variant (see leaf_cards)
_CARD_RADIAL_MIN = 0.70        # centres sit in the outer shell band [0.70, 1]
_CARD_SCALE_BAND = (0.6, 1.0)  # per-card size factor; the nominal card is max


def leaf_cards(*, crown_centre_z_cm: float, crown_radius_cm: float,
               card_count: int, card_w_cm: float, card_h_cm: float,
               seed: Any,
               crown_radius_v_cm: float | None = None) -> dict:
    """``card_count`` leaf quads (two triangles each) on an ellipsoidal crown.

    ``crown_radius_cm`` is the crown's horizontal semi-axis and
    ``crown_radius_v_cm`` its vertical semi-axis; a vertical radius of ``None``
    (the default) means a spherical crown, the shape older callers and tests
    expect. A card picks a uniform unit direction ``d`` on the sphere and maps
    it onto the ellipsoid shell ``e = (rx*d_x, rx*d_y, rz*d_z)``, so the broad
    variant is wider than tall and the columnar taller than wide.

    Card centres are biased to the outer shell: the radial factor in
    ``[_CARD_RADIAL_MIN, 1.0]`` of ``e`` is a digest-derived jitter inside the
    band, so the canopy is densest near its outside and the outline is ragged
    rather than a clean ball. Every card is additionally scaled by a
    digest-derived factor in ``_CARD_SCALE_BAND``, so one crown carries small
    and large lobes instead of one repeated stamp.

    The card's *stored normal* is the unit outward normal of the ellipsoid at
    ``e`` (proportional to ``(d_x/rx, d_y/rx, d_z/rz)``), NOT the card-plane
    normal, so the crown lights as a volume; the dot product of the normal
    with ``e`` is positive for every card, i.e. normals always point away from
    the crown centre. The card plane is the tangent plane of the ellipsoid at
    that point, randomised by a digest-derived roll about the normal and a
    pitch jitter of at most +-22 degrees, so cards splay outward and no two
    need be coplanar - the crown cannot read as one flat billboard.

    A per-card ``up_bias`` scalar in [0, 1] is emitted once per vertex (six
    rows per card) as ``(n_z + 1) / 2`` of the stored normal: 0 for a card
    facing straight down, 0.5 for a vertical side card, 1 for a card on the
    crown top. The value is data for an editor driver to feed the leaf
    material (sky-facing cards catch more light); lighting is not solved here.
    UVs span the full 0..1 range on every card.
    """
    if crown_radius_cm <= 0.0 or card_w_cm <= 0.0 or card_h_cm <= 0.0:
        raise ValueError(
            "leaf_cards: crown radius and card sizes must be positive "
            f"(got {crown_radius_cm}, {card_w_cm}, {card_h_cm})")
    if crown_radius_v_cm is not None and float(crown_radius_v_cm) <= 0.0:
        raise ValueError(
            "leaf_cards: vertical crown radius must be positive "
            f"(got {crown_radius_v_cm})")
    if crown_radius_v_cm is not None \
            and not math.isfinite(float(crown_radius_v_cm)):
        raise ValueError(
            "leaf_cards: crown_radius_v_cm must be finite "
            f"(got {crown_radius_v_cm})")
    if card_count < 1:
        raise ValueError(
            f"leaf_cards: card_count must be >= 1 (got {card_count})")
    if not math.isfinite(float(crown_centre_z_cm)):
        raise ValueError("leaf_cards: crown_centre_z_cm must be finite")
    centre_z = float(crown_centre_z_cm)
    rx = float(crown_radius_cm)
    rz = rx if crown_radius_v_cm is None else float(crown_radius_v_cm)
    w2 = float(card_w_cm) / 2.0
    h2 = float(card_h_cm) / 2.0
    geo = _new_geo()
    geo["up_bias"] = []
    for i in range(int(card_count)):
        lab = f"leaf|{i}"
        # uniform direction on the sphere (z-up); maps onto the ellipsoid shell
        az_c = 2.0 * math.pi * _u01(seed, lab + "|az_c")
        cosz = 2.0 * _u01(seed, lab + "|cosz") - 1.0
        hxy = math.sqrt(max(0.0, 1.0 - cosz * cosz))
        d = _norm(math.cos(az_c) * hxy, math.sin(az_c) * hxy, cosz)
        # outer-shell radial factor: deterministic jitter inside the band
        radial = (_CARD_RADIAL_MIN
                  + (1.0 - _CARD_RADIAL_MIN) * _u01(seed, lab + "|radial"))
        ex = rx * d[0]
        ey = rx * d[1]
        ez = rz * d[2]
        px = ex * radial
        py = ey * radial
        pz = centre_z + ez * radial
        # outward lighting normal: unit gradient of the ellipsoid at e
        g = _norm(d[0] / rx, d[1] / rx, d[2] / rz)
        # tangent frame around the outward normal g
        if abs(g[2]) <= 0.95:
            ref = (0.0, 0.0, 1.0)
        else:
            ref = (1.0, 0.0, 0.0)
        t1_0 = _norm(*_cross(g[0], g[1], g[2], ref[0], ref[1], ref[2]))
        t2_0 = _cross(g[0], g[1], g[2], t1_0[0], t1_0[1], t1_0[2])
        roll = 2.0 * math.pi * _u01(seed, lab + "|roll")
        pitch = (_u01(seed, lab + "|pitch") - 0.5) * math.radians(44.0)
        scale = (_CARD_SCALE_BAND[0]
                 + (_CARD_SCALE_BAND[1] - _CARD_SCALE_BAND[0])
                 * _u01(seed, lab + "|scale"))
        w2s = w2 * scale
        h2s = h2 * scale
        cr, sr = math.cos(roll), math.sin(roll)
        cp, sp = math.cos(pitch), math.sin(pitch)
        # rotate t1 about g by `roll` ...
        t1 = (t1_0[0] * cr + t2_0[0] * sr,
              t1_0[1] * cr + t2_0[1] * sr,
              t1_0[2] * cr + t2_0[2] * sr)
        # ... then tip the plane up to +-22 deg toward/away from g, i.e. a
        # rotation of t2 about t1 (t2_0 x t1 == g keeps the frame consistent).
        t2 = (t2_0[0] * cp + g[0] * sp,
              t2_0[1] * cp + g[1] * sp,
              t2_0[2] * cp + g[2] * sp)
        c00 = (px + t1[0] * w2s + t2[0] * h2s,
               py + t1[1] * w2s + t2[1] * h2s,
               pz + t1[2] * w2s + t2[2] * h2s)
        c10 = (px - t1[0] * w2s + t2[0] * h2s,
               py - t1[1] * w2s + t2[1] * h2s,
               pz - t1[2] * w2s + t2[2] * h2s)
        c11 = (px - t1[0] * w2s - t2[0] * h2s,
               py - t1[1] * w2s - t2[1] * h2s,
               pz - t1[2] * w2s - t2[2] * h2s)
        c01 = (px + t1[0] * w2s - t2[0] * h2s,
               py + t1[1] * w2s - t2[1] * h2s,
               pz + t1[2] * w2s - t2[2] * h2s)
        # both triangles share the c00-c11 diagonal; normals = outward normal.
        _tri(geo, (c00, c10, c11), (g, g, g),
             ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0)))
        _tri(geo, (c00, c11, c01), (g, g, g),
             ((0.0, 1.0), (1.0, 0.0), (0.0, 0.0)))
        # per-card sky-facing scalar, one copy per corner row (6 rows/card)
        up_bias = _f3((g[2] + 1.0) / 2.0)
        geo["up_bias"].extend([up_bias] * 6)
    return geo


# --------------------------------------------------------------------------
# variant table and assembly
# --------------------------------------------------------------------------

def _cylinder_tris(sides: int, segments: int) -> int:
    """Triangles in a closed stacked cylinder: sides quads * 2 per segment
    plus a sides-triangle fan on each of the two caps."""
    return sides * (2 * segments + 2)


# trunk construction shared by every variant: 10 sides, 3 segments -> 80 tris
_TRUNK_SIDES, _TRUNK_SEGMENTS = 10, 3
# branch construction shared by every variant: 8 sides, 2 segments -> 48 tris
_BRANCH_SIDES, _BRANCH_SEGMENTS = 8, 2

_TREE_VARIANT_COMMON = {
    # every variant budgets exactly this many trunk triangles
    "budget_trunk": _cylinder_tris(_TRUNK_SIDES, _TRUNK_SEGMENTS),
    # and this many per branch
    "budget_branch": _cylinder_tris(_BRANCH_SIDES, _BRANCH_SEGMENTS),
}


def _budget(branch_count: int, card_count: int) -> int:
    return (_TREE_VARIANT_COMMON["budget_trunk"]
            + branch_count * _TREE_VARIANT_COMMON["budget_branch"]
            + 2 * card_count)


TREE_VARIANTS: dict[str, dict] = {
    "maple": {
        "description": "broad street maple",
        # bare bole 3.0 m; leafy head centred 4.8 m up with 2.6 m horizontal
        # and 2.0 m vertical radii -> nominal crown top ~6.8 m, ~5.2 m wide at
        # full scale (cards may poke a little past the ellipsoid; the real
        # bounds are in the document).
        "trunk_height_cm": 300.0,
        "trunk_base_radius_cm": 20.0,
        "trunk_top_radius_cm": 12.0,
        "lean_deg": 2.5,
        "branch_count": 6,
        "crown_radius_cm": 260.0,
        "crown_radius_v_cm": 200.0,
        "crown_centre_z_cm": 480.0,
        "card_count": 130,
        "card_w_cm": 78.0,
        "card_h_cm": 58.0,
        "nominal_height_cm": 680.0,
        "budget_triangles": _budget(6, 130),
    },
    "columnar": {
        "description": "narrow columnar (poplar-like)",
        # high bare bole (5.2 m); the head at 6.2 m is 1.5 m wide and 1.8 m
        # tall, so the column reads tall and thin even though the crown centre
        # is a fixed constant.
        "trunk_height_cm": 520.0,
        "trunk_base_radius_cm": 16.0,
        "trunk_top_radius_cm": 9.0,
        "lean_deg": 1.5,
        "branch_count": 4,
        "crown_radius_cm": 150.0,
        "crown_radius_v_cm": 180.0,
        "crown_centre_z_cm": 620.0,
        "card_count": 110,
        "card_w_cm": 58.0,
        "card_h_cm": 96.0,
        "nominal_height_cm": 800.0,
        "budget_triangles": _budget(4, 110),
    },
    "sapling": {
        "description": "young sapling",
        "trunk_height_cm": 180.0,
        "trunk_base_radius_cm": 12.0,
        "trunk_top_radius_cm": 7.0,
        "lean_deg": 2.0,
        "branch_count": 3,
        "crown_radius_cm": 130.0,
        "crown_radius_v_cm": 120.0,
        "crown_centre_z_cm": 270.0,
        "card_count": 62,
        "card_w_cm": 54.0,
        "card_h_cm": 44.0,
        "nominal_height_cm": 390.0,
        "budget_triangles": _budget(3, 62),
    },
}

# Index agreement with the dressing plan: ``tree_slots`` rolls a variant in
# {0, 1, 2} (``dressing.py:_digest_int(rid + "|tree", 3)``) and the editor
# indexes an asset table by it. Order here is the order that table should
# wear, so a slot's 0/1/2 already names the shape.
TREE_VARIANT_ORDER = ("maple", "columnar", "sapling")


def _trunk_radius_at(p: dict, z_cm: float) -> float:
    """Trunk radius at height z (ignores the slight lean)."""
    h = float(p["trunk_height_cm"])
    t = max(0.0, min(1.0, z_cm / h)) if h > 0.0 else 0.0
    return (float(p["trunk_base_radius_cm"])
            + (float(p["trunk_top_radius_cm"])
               - float(p["trunk_base_radius_cm"])) * t)


def _branches(p: dict, seed: Any) -> dict:
    """Merge the per-variant limb count into a single bark sub-document."""
    merged = _new_geo()
    count = int(p["branch_count"])
    if count < 0:
        raise ValueError(f"tree_mesh: branch_count must be >= 0 (got {count})")
    for k in range(count):
        lab = f"branch|{k}"
        attach = (float(p["trunk_height_cm"])
                  * (0.45 + 0.47 * _u01(seed, lab + "|attach")))
        r_trunk = _trunk_radius_at(p, attach)
        base_r = r_trunk * (0.5 + 0.25 * _u01(seed, lab + "|base_r"))
        length = (float(p["crown_radius_cm"])
                  * (0.55 + 0.30 * _u01(seed, lab + "|length")))
        incl = 15.0 + 30.0 * _u01(seed, lab + "|incline")
        geo = branch_geometry(origin_z_cm=attach, length_cm=length,
                              base_radius_cm=base_r,
                              top_radius_cm=base_r * 0.3,
                              sides=_BRANCH_SIDES,
                              segments=_BRANCH_SEGMENTS,
                              incline_deg=incl, seed=seed + "|" + lab)
        _merge_into(merged, geo)
    return merged


def _merge_into(target: dict, source: dict) -> None:
    offset = len(target["vertices"])
    for t in source["triangles"]:
        target["triangles"].append([i + offset for i in t])
    target["vertices"].extend(source["vertices"])
    target["normals"].extend(source["normals"])
    target["uvs"].extend(source["uvs"])


def tree_mesh(variant: str, *, seed: Any) -> dict:
    """Assemble trunk + branches + leaf cards into one ``tree_mesh_v1`` doc.

    ``material_slot_per_triangle``: 0 for every trunk/branch triangle (bark),
    1 for every leaf triangle. Leaves are emitted after bark, two triangles
    per card in card order. ``up_bias`` parallels the vertices: 0.0 on every
    bark row and the per-card sky-facing scalar on leaf rows, so an editor
    driver can read one scalar per vertex straight off the document.
    """
    if variant not in TREE_VARIANTS:
        raise ValueError(
            f"tree_mesh: unknown variant {variant!r}; "
            f"known: {sorted(TREE_VARIANTS)}")
    p = TREE_VARIANTS[variant]
    seed0 = f"tree_mesh|{variant}|{seed}"

    trunk = trunk_geometry(height_cm=float(p["trunk_height_cm"]),
                           base_radius_cm=float(p["trunk_base_radius_cm"]),
                           top_radius_cm=float(p["trunk_top_radius_cm"]),
                           sides=_TRUNK_SIDES, segments=_TRUNK_SEGMENTS,
                           lean_deg=float(p["lean_deg"]), seed=seed0 + "|trunk")
    branches = _branches(p, seed0)
    leaves = leaf_cards(crown_centre_z_cm=float(p["crown_centre_z_cm"]),
                        crown_radius_cm=float(p["crown_radius_cm"]),
                        crown_radius_v_cm=float(p["crown_radius_v_cm"]),
                        card_count=int(p["card_count"]),
                        card_w_cm=float(p["card_w_cm"]),
                        card_h_cm=float(p["card_h_cm"]),
                        seed=seed0 + "|leaf")

    merged = _new_geo()
    _merge_into(merged, trunk)
    trunk_tris = len(trunk["triangles"])
    _merge_into(merged, branches)
    branch_tris = len(branches["triangles"])
    _merge_into(merged, leaves)
    leaf_tris = len(leaves["triangles"])
    slot_per_tri = ([0] * (trunk_tris + branch_tris)
                    + [1] * leaf_tris)
    # one scalar per vertex: neutral 0 on bark rows, the card's own bias on
    # leaf rows (leaves own the rows after the bark run, 3 rows per triangle)
    up_bias = ([0.0] * (3 * (trunk_tris + branch_tris))
               + leaves["up_bias"])

    verts = merged["vertices"]
    tris = merged["triangles"]
    bounds = {
        "min_x": _f3(min(v[0] for v in verts)),
        "min_y": _f3(min(v[1] for v in verts)),
        "min_z": _f3(min(v[2] for v in verts)),
        "max_x": _f3(max(v[0] for v in verts)),
        "max_y": _f3(max(v[1] for v in verts)),
        "max_z": _f3(max(v[2] for v in verts)),
    }
    total = int(p["budget_triangles"])
    counts = {
        "triangles": len(tris),
        "vertices": len(verts),
        "material_slot_0_triangles": trunk_tris + branch_tris,
        "material_slot_1_triangles": leaf_tris,
        "trunk_triangles": trunk_tris,
        "branch_triangles": branch_tris,
        "leaf_triangles": leaf_tris,
        "branches": int(p["branch_count"]),
        "cards": int(p["card_count"]),
        "budget_triangles": total,
        "triangles_per_instanced_tree": total,
        "budget_240_trees_triangles": total * 240,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "variant": variant,
        "vertices": verts,
        "triangles": tris,
        "normals": merged["normals"],
        "uvs": merged["uvs"],
        "up_bias": up_bias,
        "material_slot_per_triangle": slot_per_tri,
        "counts": counts,
        "bounds": bounds,
    }


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def _finite(vals) -> bool:
    for v in vals:
        if not math.isfinite(float(v)):
            return False
    return True


def _pos_key(p: list[float]) -> tuple[float, float, float]:
    """Rounded position tuple used as an equality key."""
    return (_f3(p[0]), _f3(p[1]), _f3(p[2]))


def validate_mesh(doc: dict) -> list[str]:
    """Return a list of problems; empty means valid.

    Checks: schema presence; triangle indices in range; normals/uvs length ==
    vertices; ``up_bias`` (when present) length == vertices and every value in
    [0, 1]; material_slot_per_triangle length == triangles; no degenerate
    (zero-area) triangle; every consecutive pair of material-slot-1 triangles
    (two triangles per leaf card, emitted adjacently by :func:`tree_mesh`)
    shares exactly two vertices; no NaN/inf coordinate anywhere.
    """
    problems: list[str] = []
    if not isinstance(doc, dict):
        return ["document is not a dict"]
    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version is not tree_mesh_v1")
    verts = doc.get("vertices")
    tris = doc.get("triangles")
    norms = doc.get("normals")
    uvs = doc.get("uvs")
    slots = doc.get("material_slot_per_triangle")
    up_bias = doc.get("up_bias")
    if not isinstance(verts, list) or not isinstance(tris, list):
        return problems + ["vertices/triangles must be lists"]
    if not isinstance(norms, list):
        problems.append("normals missing")
        norms = []
    if not isinstance(uvs, list):
        problems.append("uvs missing")
        uvs = []
    if not isinstance(slots, list):
        problems.append("material_slot_per_triangle missing")
        slots = []
    if up_bias is not None and not isinstance(up_bias, list):
        problems.append("up_bias must be a list")
        up_bias = []
    if len(norms) != len(verts):
        problems.append(
            f"normals length {len(norms)} != vertices length {len(verts)}")
    if len(uvs) != len(verts):
        problems.append(
            f"uvs length {len(uvs)} != vertices length {len(verts)}")
    if isinstance(up_bias, list) and len(up_bias) != len(verts):
        problems.append(
            f"up_bias length {len(up_bias)} != vertices length {len(verts)}")
    if len(slots) != len(tris):
        problems.append(
            "material_slot_per_triangle length "
            f"{len(slots)} != triangles length {len(tris)}")
    nv = len(verts)

    def tri_broken(t) -> bool:
        """Triangle cannot be dereferenced safely (bad arity or index)."""
        if len(t) != 3:
            return True
        return t[0] < 0 or t[0] >= nv or t[1] < 0 or t[1] >= nv \
            or t[2] < 0 or t[2] >= nv

    for k, t in enumerate(tris):
        if tri_broken(t):
            if len(t) != 3:
                problems.append(f"triangle {k} does not have 3 indices")
            else:
                problems.append(f"triangle {k} index out of range")
            continue  # never dereference a broken triangle
        a, b, c = verts[t[0]], verts[t[1]], verts[t[2]]
        # degenerate (zero-area): squared magnitude of the cross product
        abx = b[0] - a[0]
        aby = b[1] - a[1]
        abz = b[2] - a[2]
        acx = c[0] - a[0]
        acy = c[1] - a[1]
        acz = c[2] - a[2]
        crx = aby * acz - abz * acy
        cry = abz * acx - abx * acz
        crz = abx * acy - aby * acx
        if crx * crx + cry * cry + crz * crz < 1e-9:
            problems.append(f"triangle {k} is degenerate (zero area)")
    for k, v in enumerate(verts):
        if len(v) < 3 or not _finite(v[:3]):
            problems.append(f"vertex {k} not finite")
    for k, n in enumerate(norms[:nv]):
        if len(n) < 3 or not _finite(n[:3]):
            problems.append(f"normal {k} not finite")
    for k, u in enumerate(uvs[:nv]):
        if len(u) < 2 or not _finite(u[:2]):
            problems.append(f"uv {k} not finite")
    if isinstance(up_bias, list) and len(up_bias) == len(verts):
        for k, b in enumerate(up_bias):
            try:
                fb = float(b)
            except (TypeError, ValueError):
                problems.append(f"up_bias {k} is not a number")
                continue
            if not math.isfinite(fb) or not 0.0 <= fb <= 1.0:
                problems.append(f"up_bias {k} not in [0, 1]")

    # leaf-card pairing: consecutive slot-1 triangles, two per card.
    if slots and len(slots) == len(tris):
        one = [k for k, s in enumerate(slots) if s == 1]
        if len(one) % 2 != 0:
            problems.append(
                "leaf triangle count is odd; cards cannot be paired")
        else:
            for ci in range(0, len(one), 2):
                t1, t2 = one[ci], one[ci + 1]
                if t2 != t1 + 1:
                    problems.append(
                        f"leaf triangles {t1},{t2} are not adjacent")
                    continue
                if tri_broken(tris[t1]) or tri_broken(tris[t2]):
                    continue  # already reported above; nothing safe to compare
                corners = []
                for t in (tris[t1], tris[t2]):
                    for i in t:
                        corners.append(_pos_key(verts[i]))
                shared = len(set(corners[:3]) & set(corners[3:]))
                if shared != 2:
                    problems.append(
                        f"leaf card triangles {t1},{t2} do not share "
                        f"exactly two vertices (share {shared})")
    return problems
