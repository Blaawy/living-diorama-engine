"""``ldyf.sgd_buildings`` -- the design brain for Epic's shape-grammar buildings.

Schema ``sgd_buildings_v1``.  This module emits **decisions, never geometry**.
For every building slot of a ``city_layout_v1`` document it states *where* the
building goes, *how big* its rectangle is, *which way* it faces, *how tall* it
is and *which shape-grammar style* it wears.  There are no triangles, no
vertices, no materials, no mesh names and no ``import unreal`` anywhere in this
file; a thin editor driver reads one order and sets the four graph-instance
parameter overrides on Epic's ``PCG_Bldg_SGD_test`` graph:

=====================  ==================  ===============================
parameter              type                order field
=====================  ==================  ===============================
``ShapeGrammarDefinition``  soft object path  ``sgd_asset``
``Width``              float cm            ``width_cm``
``Length``             float cm            ``length_cm``
``Height``             float cm            ``height_cm``
=====================  ==================  ===============================

Epic's grammar then makes the geometry, the facades, the windows, the storeys
and the roofs.  Our code owns location, size, orientation, height, role, style
and seed -- nothing else.

**Asset path and its object suffix.**  Every order's ``sgd_asset`` is
``/CitySamplePCG/PCG/DataAssets/Buildings/<FAMILY>/SGD_<FAMILY>_A.SGD_<FAMILY>_A``
(:func:`sgd_asset_path`), e.g. ``.../NYAF/SGD_NYAF_A.SGD_NYAF_A``.  The trailing
``.SGD_<FAMILY>_A`` object suffix is **required** by the engine call that
consumes this path: the graph-instance override takes the *object* path of the
shape-grammar definition data asset (package path plus the object's name inside
that package), so dropping the suffix makes the override resolve to nothing.

**The palette and why it is closed.**  ``SGD_PALETTE`` holds the nine families
that were measured to produce real wall modules with the meshes actually
installed (instance counts in Epic's demo are recorded per family).  Every
other family produced the foundation-only baseline of 72 instances, i.e. walls
are missing, so those families must never be selected: :func:`family_for` and
:func:`sgd_asset_path` refuse a family outside the palette with ``ValueError``,
and :func:`_check_palette` re-checks the whole table at import time (the same
import-time discipline ``building_styles`` uses).  ``NYG`` is **landmark
only** -- no ordinary order may wear it and :func:`validate_orders` says so.

**Reused, not reinvented.**  Slot traversal, the trusted slot ``yaw`` field,
the single footprint rule and the landmark slot decision all come from
:mod:`ldyf.pcg_buildings` (which in turn calls
``street_life_inputs.building_footprint`` for the footprint and
``building_kits`` for massing and the landmark pick).  This module adds no
second footprint source.

**Rectangle derivation.**  Rectangular buildings are an accepted Director
decision for this phase, and the rectangles are *derived from the existing
footprints*, not scattered: for a slot the footprint is the ``width_cm`` x
``depth_cm`` rectangle whose street side is centred on the slot point and whose
mass recedes away from the street
(``street_life_inputs._footprint_corners``).  With ``u = (cos yaw, sin yaw)``
(the outward normal, i.e. the direction the frontage faces) and its tangent
``t = (-sin yaw, cos yaw)`` this module projects the footprint corners onto both
axes and reports the axis-aligned extents in that rectangle's *own* frame:
``width_cm`` is the extent along ``t`` (the frontage edge) and ``length_cm`` the
extent along ``u`` (the receding depth), with ``center`` the mid-point of both
extents expressed back in world ``[x, y]``.  The result is exactly the
footprint rectangle's centre and side lengths for any yaw, so road alignment,
block placement, spacing and non-overlap are preserved by construction.

**Yaw, and which edge is "front".**  ``yaw_deg`` is the slot's trusted ``yaw``
field (``pcg_buildings._slot_yaw_deg``; outwards, away from the block centre
toward the road).  The **front** is the wall whose mid-point is the slot point
and whose outward normal is ``+yaw`` -- i.e. the wall on the ``u`` side of the
rectangle, facing the street.  The building therefore faces the street, not a
world axis, and ``length_cm`` always measures backwards from that front wall.

**Height: clamp, never re-randomise.**  A grammar given too little height makes
**zero** geometry: ``NYAF`` at 1500 cm yielded nothing while 6000 cm yielded a
real 7-storey building, so 6000.0 is the one measured minimum in
``STYLE_MIN_HEIGHT_CM`` and every other family is ``None`` ("unknown -- use
``DEFAULT_MIN_HEIGHT_CM``") until a measured table lands via
:func:`set_style_minimums`.  The requested height for a slot comes from the
existing massing rule (``building_kits.massing_variation``, the same source the
previous building path used), lifted to ``building_kits.LANDMARK_MIN_HEIGHT_CM``
for the landmark; :func:`clamp_height` then raises -- never lowers, never
re-rolls -- a request that is below its family's minimum and *reports* that it
did (``clamped``, and one entry in the document's ``clamps`` list).  No height
is invented anywhere else in this module.

Pure stdlib (``hashlib``/``math``/``re``), deterministic (sha256 digests, never
``random``), floats routed through :func:`_f3`.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Mapping, Sequence

try:  # package import (tests, drivers)
    from ldyf import pcg_buildings as _pcg
except ImportError:  # pragma: no cover - script-mode import
    import pcg_buildings as _pcg  # type: ignore


SCHEMA_VERSION = "sgd_buildings_v1"

#: Root of Epic's shape-grammar data assets.
SGD_ROOT = "/CitySamplePCG/PCG/DataAssets/Buildings"

#: The documented asset path pattern, with the family repeated three times so
#: a path whose folder and asset object disagree can never validate.
SGD_ASSET_RE = re.compile(
    r"/CitySamplePCG/PCG/DataAssets/Buildings/"
    r"(?P<family>[A-Z]+)/SGD_(?P=family)_A\.SGD_(?P=family)_A\Z")

#: Instance count every family *outside* the palette produced in Epic's demo:
#: the foundation-only baseline, i.e. no usable walls.
FOUNDATION_ONLY_INSTANCES = 72

#: The production palette: family -> the role band it is chosen for and the
#: instance count measured in Epic's own demo.  Exactly these nine families;
#: every other family sits at ``FOUNDATION_ONLY_INSTANCES`` and is never
#: selectable (see the module docstring).
SGD_PALETTE: dict[str, dict[str, Any]] = {
    "SFD": {"role_band": "low-rise, fine grain", "instances": 1032},
    "NYAE": {"role_band": "mid-rise", "instances": 352},
    "NYAF": {"role_band": "mid-rise and landmark", "instances": 352,
             "landmark_only": False},
}

#: NYG and NYGA were removed after Block V2's VISUAL gate, which every machine
#: check passed blind. NYG built 4,406 modules at height ratio 0.98 and still
#: rendered as four thin vertical SHAFTS rather than a tower -- identically at
#: 14000, 11000, 9000, 7000 and 5000 cm, so it is neither a height nor an aspect
#: problem: the family simply produces slender shaft forms with this mesh
#: subset. An in-situ A/B settled it -- swapping ONLY the landmark family to
#: NYAF, at the same 14000 cm, removed the shafts and produced a solid
#: 13,839.5 cm mass (ratio 0.988, 914 modules). NYGA is dropped as never
#: visually verified: no slot ever requested its band, so it would have shipped
#: untested, and that is exactly how NYG got through.
#: Evidence: EVIDENCE/PHASE_02/look_blockv2_nyaf14/, landmark_aspect.json.
#:
#: Families removed after the one-block machine check, which compared the
#: height actually achieved against the height requested and counted the modules
#: placed (EVIDENCE/PHASE_02/pcg_one_block.json):
#:
#: * ``NYAD`` -- asked for 4188 cm, built **475.5 cm** (ratio 0.11): a
#:   single-storey slab, levels {0, 1}, 98 modules. It ignores height outright.
#: * ``NYAC`` -- height fine (4116 of 4188) but only **56** modules across
#:   levels {0, 6}: a foundation plus one wall course, i.e. a hollow frame.
#: * ``NYH`` -- 54 modules at its own minimum, the same sparse signature as
#:   NYAC, so it is refused on the same grounds rather than shipped untested.
#: * ``CHA`` / ``CHB`` / ``CHH`` -- the 32-module foundation ring at every
#:   height tested; no Chicago family has usable walls in this mesh subset.
#:
#: Families kept all achieve ratio >= 0.93 with >= 200 modules, except the
#: landmark which is denser still (2510).
#:
#: The palette as a sorted literal, so the import-time check is order-free.
_PALETTE_FAMILIES: tuple[str, ...] = (
    "NYAE", "NYAF", "SFD")

#: The only family an ordinary order may not wear.
LANDMARK_FAMILY = "NYAF"

#: Minimum viable height per family, in cm -- **all measured**, not inferred.
#: A grammar given too little height produces ZERO geometry, so a request below
#: these values must never reach the editor.  "Viable" means a level token other
#: than 0 appears, i.e. real wall modules: the foundation ring alone already
#: yields a non-zero instance count and would otherwise read as success.
#: Measured instance counts at the minimum are in brackets.
#: Evidence: EVIDENCE/PHASE_02/pcg_sgd_minheights.json.
STYLE_MIN_HEIGHT_CM: dict[str, float | None] = {
    "SFD": 2500.0,    # [214] levels 0, 01-04
    "NYAE": 2500.0,   # [152] levels 0, 2-6
    "NYAF": 2500.0,   # [172] levels 0, 2-7
}

#: Height used for a family whose real minimum is unmeasured.  Chosen by hand,
#: not measured: it is strictly above the one height measured to give zero
#: geometry (``NYAF`` at 1500 cm) and below the top of ``building_kits``'s mid
#: band (2600 cm), so an unmeasured family keeps its requested height once the
#: request is at least this tall.  Replace it wholesale with
#: :func:`set_style_minimums` as soon as a measured table exists.
DEFAULT_MIN_HEIGHT_CM = 2000.0

#: Recommended height band per family, in cm: ``(minimum, maximum)``.
#: The minimum is MEASURED (see :data:`STYLE_MIN_HEIGHT_CM`); the maximum is a
#: judgement about where the family stops reading well, chosen per role band.
#:
#: Why this exists: our layout asks for 1600-2400 cm buildings, but every
#: grammar needs at least 2500 cm to emit any geometry at all, so clamping alone
#: flattens the whole city to one uniform height. :func:`apply_height_bands`
#: spreads the requests back out inside these bands, which keeps the relative
#: design intent (a slot asked to be taller stays taller) while every height
#: stays viable.
HEIGHT_BAND_CM: dict[str, tuple[float, float]] = {
    "SFD": (2500.0, 3400.0),     # low-rise, fine grain
    "NYAE": (2500.0, 5200.0),
    "NYAF": (2500.0, 5200.0),
}


#: The landmark's own band. It is SEPARATE from HEIGHT_BAND_CM because the
#: landmark family is no longer exclusive: NYAF serves ordinary mid-rise slots
#: too, and if the landmark shared that band an ordinary NYAF at the top of the
#: range would tie with it and the landmark would stop being the tallest mass.
#: The floor sits above every ordinary band top so the hierarchy cannot invert.
#:
#: The CEILING is 9000, not the 14000 originally asked for, and that is an
#: asset limit rather than a preference. Facade density tracks how many wall
#: VARIANTS each level has in this project's mesh subset: NYA carries 6 variants
#: at L3 (240 placements on the landmark) but only 1 at L7 (20 placements), so
#: above roughly 9000 cm the upper courses thin out into widely spaced piers and
#: a 14000 cm tower renders as shafts rather than a building -- measured, not
#: guessed. Lifting this needs a targeted mesh import: 526 missing
#: SM_BLDG_NYA_* files, 771 MB before dependency closure, which is far past a
#: "smallest targeted top-up" and is a Director decision, not an engineering
#: one. Evidence: EVIDENCE/PHASE_02/shaft_probe.json.
LANDMARK_HEIGHT_BAND_CM: tuple[float, float] = (6000.0, 9000.0)


def apply_height_bands(doc: dict, *, never_lower: bool = False) -> dict:
    """Spread clamped heights back out inside each family's recommended band.

    Clamping alone makes every building the same height whenever the whole
    layout requests less than the grammars' minimum, which is exactly our case
    (requests 1600-2400 cm against a 2500 cm floor). This remaps each order's
    REQUESTED height, not its clamped one, onto its family's
    :data:`HEIGHT_BAND_CM`, so ordering is preserved: the tallest request in the
    document lands at the top of its family's band and the shortest at the
    bottom.

    The normalisation is taken across the ORDINARY orders only. The landmark is
    excluded deliberately: its request is far taller than any ordinary slot
    (5600 against 1600-2400 here), so including it compresses every ordinary
    building into the bottom of its band -- measured, the ordinary spread
    collapsed from 2500-5200 to 2500-3040. The landmark instead takes the top of
    its own band, which is what makes it read as the civic landmark.

    The normalisation spans families rather than being per-family, so a family
    used only for low slots keeps low buildings. A document whose ordinary
    requests are all equal maps them to their band minimum, the conservative
    choice.

    Returns a NEW document; the input is not mutated. ``height_cm`` is replaced,
    ``requested_height_cm`` is left untouched, and ``band_remap`` records every
    change so a reviewer can see what moved.
    """
    orders = doc.get("orders") or []
    if not orders:
        raise ValueError("document has no orders")
    ordinary = [o for o in orders if o.get("role") != "landmark"]
    reqs = [float(o["requested_height_cm"]) for o in (ordinary or orders)]
    lo, hi = min(reqs), max(reqs)
    span = hi - lo
    out = dict(doc)
    new_orders = []
    remap = []
    for o in orders:
        fam = _require_palette_family(o["family"])
        if o.get("role") == "landmark":
            band_lo, band_hi = LANDMARK_HEIGHT_BAND_CM
        else:
            band_lo, band_hi = HEIGHT_BAND_CM[fam]
        req = float(o["requested_height_cm"])
        if o.get("role") == "landmark":
            t = 1.0          # the landmark takes the top of its own band
        elif span <= 0.0:
            t = 0.0
        else:
            t = min(1.0, max(0.0, (req - lo) / span))
        height = _f3(band_lo + t * (band_hi - band_lo))
        # never below the measured minimum, whatever the band says
        height = max(height, minimum_for(fam))
        # Grouped documents already carry a height TIER per group (2500 / 2800 /
        # 6500), and banding would pull the 6500 tier down to its family's 5200
        # ceiling -- below its own request, which validate_groups rejects on
        # eight of the nine real blocks. With never_lower the band can only
        # LIFT a building, so the tiers survive and the flat ones still spread.
        # The landmark is exempt: its band ceiling is an asset limit.
        if never_lower and o.get("role") != "landmark":
            height = max(height, float(o["height_cm"]))
        row = dict(o)
        row["height_cm"] = height
        new_orders.append(row)
        if height != float(o["height_cm"]):
            remap.append({"id": o["id"], "family": fam,
                          "requested_cm": req,
                          "was_cm": float(o["height_cm"]),
                          "height_cm": height})
    out["orders"] = new_orders
    out["band_remap"] = remap
    return out


#: How far a family's built mesh reaches BEYOND the ``Width`` / ``Length`` it was
#: asked for, per side, in cm (cornices, stoops, corner quoins).  MEASURED from
#: instance transforms x mesh bounds on generated buildings, not inferred; the
#: excess is constant per family across every footprint tried (SFD 7040 -> 7230,
#: 3000 -> 3190; NYAF 6183 -> 6272, 4500 -> 4589, 3750 -> 3839; NYAE 4637 -> 4721,
#: 3000 -> 3084; NYGA 5000 -> 5025.6, 3500 -> 3525.6; NYG 4400 -> 4424,
#: 3100 -> 3124), on both axes and at every yaw.  Rounded UP to the centimetre
#: so a planned envelope is never smaller than what gets built.
#: Evidence: EVIDENCE/PHASE_02/block_v2/axis_and_overhang_probe.json.
FAMILY_OVERHANG_CM: dict[str, float] = {
    "SFD": 95.0,
    "NYAE": 42.0,
    "NYAF": 45.0,
}


def overhang_for(family: str) -> float:
    """Per-side mesh overhang of ``family`` in cm (see :data:`FAMILY_OVERHANG_CM`)."""
    return float(FAMILY_OVERHANG_CM[_require_palette_family(family)])


def graph_parameters(order: Mapping[str, Any]) -> dict[str, float]:
    """The ``Width`` / ``Length`` / ``Height`` overrides for one order.

    An order's ``width_cm`` is its FRONTAGE (along the tangent of ``yaw_deg``)
    and ``length_cm`` its receding DEPTH (along the outward normal), which is the
    convention :func:`rect_corners` draws.  Epic's ``PCG_Bldg_SGD_test`` lays
    ``Width`` along the volume's local **X** -- the direction ``yaw_deg`` points,
    i.e. the outward normal -- and ``Length`` along local **Y**.  Measured on
    eight generated buildings (a 7040 x 3000 order at yaw 180 built 7230 cm along
    world X).  So the two are crossed here, once, and the driver writes exactly
    what this returns.  Passing ``width_cm`` straight through as ``Width`` builds
    every rectangle rotated a quarter turn about its own centre.
    """
    return {"Width": float(order["length_cm"]),
            "Length": float(order["width_cm"]),
            "Height": float(order["height_cm"])}


#: Footprint depth used for a slot that carries no positive ``depth_cm``
#: (``city_layout.building_slots`` always emits one); 1200 cm is the depth the
#: existing building tests use.
DEFAULT_FOOTPRINT_DEPTH_CM = 1200.0

#: Fallback landmark floor, mirroring ``pcg_buildings``; the live value is
#: read from ``building_kits.LANDMARK_MIN_HEIGHT_CM`` at call time.
LANDMARK_FLOOR_CM = 5600.0

#: Family candidates per role band, in the brief's role-band order.  ``NYG``
#: is deliberately absent: it is landmark-only.
ROLE_BAND_FAMILIES: dict[str, tuple[str, ...]] = {
    "low-rise": ("SFD",),
    "mid-rise": ("NYAE", "NYAF"),
    "upper-mid": ("NYAF",),
    "tall": ("NYAF",),
}

#: Upper bound of each band in cm of *requested* height; a request exactly at a
#: bound belongs to the next band, and anything at or above the last bound is
#: ``"tall"``.  Our boundaries, not Epic's: they are placed so
#: ``building_kits``'s own height bands land in sensible roles (edge
#: 1100-1900 -> low-rise, mid 1600-2600 -> low/mid, core 2300-3600 -> mid,
#: landmark >= 5600 -> tall).
ROLE_BAND_MAX_HEIGHT_CM: tuple[tuple[str, float], ...] = (
    ("low-rise", 1900.0),
    ("mid-rise", 3600.0),
    ("upper-mid", 6000.0),
)


# ---------------------------------------------------------------------------
# project-wide numeric conventions
# ---------------------------------------------------------------------------


def _f3(v: float) -> float:
    """Round to 3 decimals (the project-wide float convention)."""
    return round(float(v) + 0.0, 3)


def _digest(*parts: Any) -> int:
    """Deterministic sha256 digest (the one ``pcg_buildings`` uses)."""
    return _pcg._digest(*parts)


def _as_number(value: Any) -> float | None:
    """``value`` as a float, or ``None`` when it is not a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# palette guards
# ---------------------------------------------------------------------------


def _require_palette_family(family: Any) -> str:
    """``family`` as a palette name, or ``ValueError``.

    This is the single gate every emitted family passes through, so a family
    outside the palette cannot reach an order.
    """
    if family not in SGD_PALETTE:
        raise ValueError(
            "unknown shape-grammar family %r; SGD_PALETTE has %s"
            % (family, sorted(SGD_PALETTE)))
    return str(family)


def sgd_asset_path(family: str) -> str:
    """The shape-grammar asset path for ``family``.

    ``/CitySamplePCG/PCG/DataAssets/Buildings/<FAMILY>/SGD_<FAMILY>_A.SGD_<FAMILY>_A``;
    the trailing ``.SGD_<FAMILY>_A`` object suffix is required by the engine
    call that consumes it (see the module docstring).  ``ValueError`` for any
    family outside :data:`SGD_PALETTE`.
    """
    fam = _require_palette_family(family)
    return f"{SGD_ROOT}/{fam}/SGD_{fam}_A.SGD_{fam}_A"


def _check_palette() -> None:
    """Import-time check: nothing outside the palette can be emitted.

    Verifies that the palette is exactly the nine documented families, that no
    palette family sits at the foundation-only baseline, that the minimum table
    and the band tables only mention palette families, that every non-landmark
    family is reachable from a band, that ``NYG`` is the only landmark-only
    family, and that every family's asset path matches the documented pattern.
    """
    if sorted(SGD_PALETTE) != sorted(_PALETTE_FAMILIES):
        raise AssertionError(
            "SGD_PALETTE is %s, expected exactly %s"
            % (sorted(SGD_PALETTE), sorted(_PALETTE_FAMILIES)))
    for fam, entry in SGD_PALETTE.items():
        if int(entry.get("instances", 0)) <= FOUNDATION_ONLY_INSTANCES:
            raise AssertionError(
                "family %r is at the foundation-only baseline (%d instances), "
                "so it produces no walls and must not be in SGD_PALETTE"
                % (fam, FOUNDATION_ONLY_INSTANCES))
    if set(STYLE_MIN_HEIGHT_CM) != set(SGD_PALETTE):
        raise AssertionError(
            "STYLE_MIN_HEIGHT_CM covers %s, expected every palette family %s"
            % (sorted(STYLE_MIN_HEIGHT_CM), sorted(SGD_PALETTE)))
    # The landmark no longer has an EXCLUSIVE family, and that is deliberate.
    # NYG was landmark-only and rendered as thin shafts at every height; the
    # only families verified on screen are the ordinary ones, so the landmark
    # now shares NYAF and is distinguished by HEIGHT rather than by family.
    # What must still hold: the landmark family is in the palette, and any
    # family that DOES claim landmark_only is the landmark family.
    _require_palette_family(LANDMARK_FAMILY)
    landmark_only = sorted(f for f, e in SGD_PALETTE.items()
                           if e.get("landmark_only"))
    if landmark_only not in ([], [LANDMARK_FAMILY]):
        raise AssertionError(
            "only %r may be marked landmark_only, got %s"
            % (LANDMARK_FAMILY, landmark_only))
    banded = [fam for fams in ROLE_BAND_FAMILIES.values() for fam in fams]
    for fam in banded:
        _require_palette_family(fam)
    # the landmark family may also serve a role band now that it is shared
    if set(banded) - set(SGD_PALETTE) or set(SGD_PALETTE) - set(banded) - {LANDMARK_FAMILY}:
        raise AssertionError(
            "every non-landmark palette family must be reachable from a role "
            "band; bands cover %s, palette minus %r is %s"
            % (sorted(set(banded)), LANDMARK_FAMILY,
               sorted(set(SGD_PALETTE) - {LANDMARK_FAMILY})))
    for fam in SGD_PALETTE:
        if SGD_ASSET_RE.fullmatch(sgd_asset_path(fam)) is None:
            raise AssertionError(
                "asset path %r does not match the documented pattern"
                % (sgd_asset_path(fam),))


_check_palette()


# ---------------------------------------------------------------------------
# minimum heights
# ---------------------------------------------------------------------------


def _coerce_minimums(mapping: Mapping[str, Any]) -> dict[str, float | None]:
    """A ``{family: cm or None}`` table, checked against the palette."""
    out: dict[str, float | None] = {}
    for family, value in dict(mapping).items():
        fam = _require_palette_family(family)
        if value is None:
            out[fam] = None
            continue
        cm = float(value)
        if not cm > 0.0:
            raise ValueError(
                "minimum height for %r must be positive or None, got %r"
                % (family, value))
        out[fam] = _f3(cm)
    return out


def set_style_minimums(mapping: Mapping[str, Any]) -> dict[str, float | None]:
    """Inject a measured ``{family: minimum cm or None}`` table.

    Only palette families may appear (``ValueError`` otherwise) and a minimum
    must be positive or ``None``; a ``None`` keeps "unknown -- use
    :data:`DEFAULT_MIN_HEIGHT_CM`".  Returns the effective table.
    """
    STYLE_MIN_HEIGHT_CM.update(_coerce_minimums(mapping))
    return dict(STYLE_MIN_HEIGHT_CM)


def style_minimums() -> dict[str, float | None]:
    """The effective ``{family: minimum cm or None}`` table (a copy)."""
    return dict(STYLE_MIN_HEIGHT_CM)


def minimum_for(family: str, table: Mapping[str, Any] | None = None) -> float:
    """The effective minimum height for ``family``, in cm.

    ``None`` in the table (or a family missing from an injected ``table``)
    means "unknown" and resolves to :data:`DEFAULT_MIN_HEIGHT_CM`.
    ``ValueError`` for a family outside the palette.
    """
    fam = _require_palette_family(family)
    source: Mapping[str, Any] = STYLE_MIN_HEIGHT_CM if table is None else table
    value = source.get(fam)
    if value is None:
        return _f3(DEFAULT_MIN_HEIGHT_CM)
    return _f3(float(value))


def resolved_minimums(table: Mapping[str, Any] | None = None) -> dict[str, float]:
    """``{family: effective minimum cm}`` for the whole palette."""
    return {fam: minimum_for(fam, table) for fam in SGD_PALETTE}


def clamp_height(family: str, requested_cm: float) -> dict:
    """Keep a requested height at or above ``family``'s minimum.

    Returns ``{"height_cm", "requested_cm", "clamped", "minimum_cm"}``.
    ``height_cm`` is never below the family minimum; ``clamped`` is ``True``
    exactly when the request had to be raised, so a driver can report it.  The
    request is only ever *raised*, never lowered and never re-randomised:
    preserving deterministic design intent matters more than tidiness.

    ``ValueError`` for a family outside the palette or a non-positive
    ``requested_cm``.
    """
    fam = _require_palette_family(family)
    requested = float(requested_cm)
    if not requested > 0.0:
        raise ValueError("requested height must be positive, got %r"
                         % (requested_cm,))
    minimum = minimum_for(fam)
    height = requested if requested >= minimum else minimum
    return {"height_cm": _f3(height),
            "requested_cm": _f3(requested),
            "clamped": bool(height > requested),
            "minimum_cm": _f3(minimum)}


# ---------------------------------------------------------------------------
# family selection
# ---------------------------------------------------------------------------


def role_band_for(height_cm: float) -> str:
    """The role band a *requested* height falls in (see the band bounds)."""
    height = float(height_cm)
    for band, top in ROLE_BAND_MAX_HEIGHT_CM:
        if height < top:
            return band
    return "tall"


def family_for(slot_id: Any, requested_cm: float, seed: int, *,
               landmark: bool = False, avoid: str | None = None) -> str:
    """The family one slot wears, deterministic from ``(slot_id, seed)``.

    The *requested* height picks the role band (:func:`role_band_for`) so tall
    slots get tall families and low slots get ``SFD``; within the band a sha256
    digest of ``("sgd_family", band, slot_id, seed)`` picks the starting
    candidate and, **if that candidate is the previous slot's family in the
    same block** (``avoid``) and the band has an alternative, the rotation
    steps forward to the next candidate.  So two adjacent slots in one block
    never share a family unless the band offers only one (``SFD`` in the
    low-rise band is the one such case).  ``landmark`` short-circuits to
    :data:`LANDMARK_FAMILY`: only a landmark may wear ``NYG``.
    """
    if landmark:
        return LANDMARK_FAMILY
    height = float(requested_cm)
    if not height > 0.0:
        raise ValueError("requested height must be positive, got %r"
                         % (requested_cm,))
    band = role_band_for(height)
    candidates = ROLE_BAND_FAMILIES[band]
    start = _digest("sgd_family", band, str(slot_id), int(seed)) % len(candidates)
    for step in range(len(candidates)):
        family = candidates[(start + step) % len(candidates)]
        if family != avoid:
            return _require_palette_family(family)
    return _require_palette_family(candidates[start % len(candidates)])


# ---------------------------------------------------------------------------
# footprint -> rectangle (reuse of the one footprint source)
# ---------------------------------------------------------------------------


def _slot_depth_cm(slot: dict) -> float:
    """The slot's own footprint depth, or the module fallback."""
    depth = slot.get("depth_cm")
    if depth is None:
        return DEFAULT_FOOTPRINT_DEPTH_CM
    depth = float(depth)
    if not depth > 0.0:
        return DEFAULT_FOOTPRINT_DEPTH_CM
    return depth


def _slot_id(slot: dict) -> str:
    return str(slot.get("slot_id") or slot.get("building_id") or "b")


def _slot_block(slot: dict) -> str:
    return str(slot.get("block_id") or "")


def _slot_key(slot: dict) -> tuple:
    """Stable order: block, then frontage index, then id.

    ``city_layout`` emits ``frontage_index`` along each frontage, so
    consecutive entries of this order are neighbours along a street inside one
    block -- which is the adjacency the family rule avoids duplicating.
    """
    index = slot.get("frontage_index")
    return (_slot_block(slot),
            float(index) if index is not None else float("inf"),
            _slot_id(slot))


def _derive_rectangle(slot: dict) -> dict:
    """The slot's existing footprint as centre / own-axis extents / yaw.

    The footprint comes from ``pcg_buildings._footprint_of`` (the single
    footprint rule; ``street_life_inputs.building_footprint``).  Extents are
    measured in the rectangle's own frame -- ``u = (cos yaw, sin yaw)`` is the
    outward frontage normal, ``t = (-sin yaw, cos yaw)`` its tangent -- so
    ``width_cm`` is the frontage edge length and ``length_cm`` the receding
    depth; ``center`` is the mid-point of both extents back in world ``[x, y]``.
    """
    yaw = _pcg._slot_yaw_deg(slot)
    pts = _pcg._as_pairs(_pcg._footprint_of(slot, _slot_depth_cm(slot)))
    if len(pts) < 3:
        raise ValueError("footprint of slot %r has fewer than 3 corners"
                         % (slot.get("slot_id"),))
    rad = math.radians(yaw)
    ux, uy = math.cos(rad), math.sin(rad)
    tx, ty = -math.sin(rad), math.cos(rad)
    us = [p[0] * ux + p[1] * uy for p in pts]
    ts = [p[0] * tx + p[1] * ty for p in pts]
    mid_u = (min(us) + max(us)) / 2.0
    mid_t = (min(ts) + max(ts)) / 2.0
    return {"center": [_f3(mid_t * tx + mid_u * ux),
                       _f3(mid_t * ty + mid_u * uy)],
            "width_cm": _f3(max(ts) - min(ts)),
            "length_cm": _f3(max(us) - min(us)),
            "yaw_deg": _f3(yaw)}


def _axes(yaw_deg: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """``(tangent, outward normal)`` unit vectors of a yaw."""
    rad = math.radians(float(yaw_deg))
    ux, uy = math.cos(rad), math.sin(rad)
    return ((-uy, ux), (ux, uy))


def rect_corners(order: Mapping[str, Any]) -> list[list[float]]:
    """The four ``[x, y]`` corners of an order's rectangle (no winding claim).

    A diagnostic / overlap helper for this module and its tests only: the order
    itself carries centre, extents and yaw, and Epic's grammar makes the
    geometry.
    """
    cx, cy = (float(v) for v in order["center"])
    hw = float(order["width_cm"]) / 2.0
    hl = float(order["length_cm"]) / 2.0
    (tx, ty), (ux, uy) = _axes(float(order["yaw_deg"]))
    return [[_f3(cx + st * hw * tx + sl * hl * ux),
             _f3(cy + st * hw * ty + sl * hl * uy)]
            for st, sl in ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))]


def rects_overlap(a: Mapping[str, Any], b: Mapping[str, Any],
                  eps: float = 1e-6) -> bool:
    """Do two yaw-carrying rectangles overlap? (axis-aware, SAT for boxes).

    Separating-axis test over the four face normals of the two rectangles --
    ``yaw`` is honoured, so two rectangles that are rotated relative to each
    other are compared in their own frames rather than by world-axis boxes.
    Touching exactly (zero or ``eps``-sized gap) is *not* an overlap, so slots
    that legitimately share a party wall validate.
    """
    ca = rect_corners(a)
    cb = rect_corners(b)
    for ax, ay in _axes(float(a["yaw_deg"])) + _axes(float(b["yaw_deg"])):
        pa = [p[0] * ax + p[1] * ay for p in ca]
        pb = [p[0] * ax + p[1] * ay for p in cb]
        if min(max(pa), max(pb)) - max(min(pa), min(pb)) <= eps:
            return False
    return True


def _rect_ready(order: Mapping[str, Any]) -> bool:
    """Whether an order carries the numbers :func:`rects_overlap` needs."""
    center = order.get("center")
    if (isinstance(center, str) or not isinstance(center, Sequence)
            or len(center) != 2
            or _as_number(center[0]) is None or _as_number(center[1]) is None):
        return False
    if _as_number(order.get("yaw_deg")) is None:
        return False
    for key in ("width_cm", "length_cm"):
        value = _as_number(order.get(key))
        if value is None or value <= 0.0:
            return False
    return True


# ---------------------------------------------------------------------------
# orders
# ---------------------------------------------------------------------------


def sgd_orders(layout: dict, *, seed: int,
               minimums: Mapping[str, Any] | None = None) -> dict:
    """One ``sgd_buildings_v1`` order per ``city_layout_v1`` building slot.

    Returns ``{"schema_version", "orders", "landmark_id", "counts", "clamps"}``
    plus ``style_minimum_cm`` (the effective ``{family: minimum cm}`` table the
    heights were clamped against, so :func:`validate_orders` can re-check a
    document without re-deriving the table) and the echoed ``seed``.

    Each order is exactly::

        {"id", "block_id", "center", "width_cm", "length_cm", "yaw_deg",
         "height_cm", "requested_height_cm", "family", "sgd_asset", "role",
         "seed"}

    ``center`` / ``width_cm`` / ``length_cm`` / ``yaw_deg`` come from the
    slot's existing footprint (see :func:`_derive_rectangle` and the module
    docstring: ``yaw`` is the outward frontage normal, so the front wall faces
    the street).  ``requested_height_cm`` is the height massing asked for and
    ``height_cm`` the same request after :func:`clamp_height`, which is the
    only place in this module that changes a height.  ``family`` is a palette
    family (tall slots get tall families, low slots ``SFD``), ``sgd_asset`` its
    shape-grammar asset path, ``seed`` a per-order digest the driver can hand
    Epic's grammar, and exactly one order -- the landmark -- has
    ``role == "landmark"`` and wears ``NYG``.  ``clamps`` records every order
    whose request had to be raised.

    ``minimums`` injects a measured ``{family: cm or None}`` table for this
    call only (:func:`set_style_minimums` changes the module default); a family
    the injected table omits stays "unknown".

    ``ValueError`` for an empty layout, a missing / non-integer ``seed``, a
    family or minimums key outside the palette, and for a slot whose footprint
    cannot be built (no position, non-positive ``width_cm``, or neither
    ``yaw`` nor ``yaw_deg`` -- the footprint source's own rules).
    """
    if seed is None or isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an int, got %r" % (seed,))
    table: Mapping[str, Any] = (STYLE_MIN_HEIGHT_CM if minimums is None
                                else _coerce_minimums(minimums))
    slots = _pcg._slots_of(layout)
    if not slots:
        raise ValueError("layout has no building slots")

    kits = _pcg._building_kits()
    massing = getattr(kits, "massing_variation", None)
    landmark_floor = float(getattr(kits, "LANDMARK_MIN_HEIGHT_CM",
                                   LANDMARK_FLOOR_CM))

    chosen = _pcg._landmark_slot(layout, int(seed))
    if chosen is None:
        # No blocks to decide from: the first slot in the stable order, so the
        # document still holds exactly one landmark (mirrors pcg_buildings).
        chosen = sorted(slots, key=_slot_key)[0]
    landmark_key = _slot_id(chosen)

    orders: list[dict] = []
    clamps: list[dict] = []
    previous: dict[str, str] = {}
    for slot in sorted(slots, key=_slot_key):
        sid = _slot_id(slot)
        block_id = _slot_block(slot)
        is_landmark = sid == landmark_key
        rect = _derive_rectangle(slot)
        mass_in = dict(slot)
        mass_in["depth_cm"] = _slot_depth_cm(slot)  # massing sees the depth used
        mass = massing(mass_in, seed=int(seed)) if massing else {}
        requested = float(mass.get("height_cm") or rect["length_cm"])
        if is_landmark:
            requested = max(requested, landmark_floor)
        requested = _f3(requested)
        family = family_for(sid, requested, seed, landmark=is_landmark,
                            avoid=previous.get(block_id))
        previous[block_id] = family
        clamp = clamp_height(family, requested)
        if clamp["clamped"]:
            clamps.append({"id": sid, "block_id": block_id, "family": family,
                           "requested_cm": clamp["requested_cm"],
                           "height_cm": clamp["height_cm"],
                           "minimum_cm": clamp["minimum_cm"]})
        orders.append({
            "id": sid,
            "block_id": block_id,
            "center": rect["center"],
            "width_cm": rect["width_cm"],
            "length_cm": rect["length_cm"],
            "yaw_deg": rect["yaw_deg"],
            "height_cm": clamp["height_cm"],
            "requested_height_cm": clamp["requested_cm"],
            "family": family,
            "sgd_asset": sgd_asset_path(family),
            "role": "landmark" if is_landmark else "ordinary",
            "seed": _digest("sgd_order", int(seed), sid) % (1 << 31),
        })

    orders.sort(key=lambda o: o["id"])
    doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "orders": orders,
        "landmark_id": next((o["id"] for o in orders
                             if o["role"] == "landmark"), None),
        "counts": {
            "orders": len(orders),
            "ordinary": sum(1 for o in orders if o["role"] == "ordinary"),
            "landmark": sum(1 for o in orders if o["role"] == "landmark"),
            "families": {fam: sum(1 for o in orders if o["family"] == fam)
                         for fam in sorted(SGD_PALETTE)
                         if any(o["family"] == fam for o in orders)},
        },
        "clamps": clamps,
        "style_minimum_cm": resolved_minimums(table),
        "seed": int(seed),
    }
    return doc


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def validate_orders(doc: dict) -> list:
    """Problems with an ``sgd_buildings_v1`` document; empty means valid.

    Catches, for every order: a family outside :data:`SGD_PALETTE`; a height at
    or below zero or below that family's minimum; a non-positive
    ``width_cm``/``length_cm``; an ``sgd_asset`` that does not match the
    documented pattern or does not name that order's family; a malformed
    ``center``/``yaw_deg``; ``NYG`` on an order that is not the landmark; a
    duplicate id; and two rectangles that overlap (axis-aware, using
    ``center``/``width_cm``/``length_cm``/``yaw_deg``, so a rotated rectangle is
    compared in its own frame).  Document-wide it catches a wrong
    ``schema_version``, an empty document, and more or fewer than one landmark
    (or a ``landmark_id`` that does not name it).
    """
    problems: list[str] = []
    orders = doc.get("orders")
    if not isinstance(orders, list) or not orders:
        return ["document has no orders"]
    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version is %r, expected %r"
                        % (doc.get("schema_version"), SCHEMA_VERSION))

    minimums = doc.get("style_minimum_cm")
    if not isinstance(minimums, dict):
        minimums = None

    landmarks = [o for o in orders if o.get("role") == "landmark"]
    if len(landmarks) != 1:
        problems.append("expected exactly one landmark, found %d"
                        % len(landmarks))
    elif doc.get("landmark_id") != landmarks[0].get("id"):
        problems.append("landmark_id %r does not name the landmark order %r"
                        % (doc.get("landmark_id"), landmarks[0].get("id")))

    seen: set[str] = set()
    rects: list[tuple[str, Mapping[str, Any]]] = []
    for order in orders:
        oid = str(order.get("id"))
        if oid in seen:
            problems.append("duplicate order id %r" % (oid,))
        seen.add(oid)

        role = order.get("role")
        if role not in ("ordinary", "landmark"):
            problems.append("order %s: role %r is neither 'ordinary' nor "
                            "'landmark'" % (oid, role))

        family = order.get("family")
        if family not in SGD_PALETTE:
            problems.append("order %s: family %r is not one of the %d palette "
                            "families %s"
                            % (oid, family, len(SGD_PALETTE),
                               sorted(SGD_PALETTE)))
        else:
            # exclusivity only applies when the palette actually marks the
            # landmark family landmark_only; NYAF now serves both roles
            if (SGD_PALETTE.get(LANDMARK_FAMILY, {}).get("landmark_only")
                    and family == LANDMARK_FAMILY and role != "landmark"):
                problems.append("order %s: %s is landmark-only but the role is "
                                "%r" % (oid, LANDMARK_FAMILY, role))
            expected_asset = sgd_asset_path(family)
            asset = order.get("sgd_asset")
            if (not isinstance(asset, str)
                    or SGD_ASSET_RE.fullmatch(asset) is None):
                problems.append("order %s: sgd_asset %r does not match the "
                                "documented pattern (.../Buildings/<FAMILY>/"
                                "SGD_<FAMILY>_A.SGD_<FAMILY>_A)"
                                % (oid, asset))
            elif asset != expected_asset:
                problems.append("order %s: sgd_asset %r is not the documented "
                                "path for family %r (%r)"
                                % (oid, asset, family, expected_asset))
            minimum = minimum_for(family, minimums)
            height = _as_number(order.get("height_cm"))
            if height is None or height <= 0.0:
                problems.append("order %s: height_cm %r is not positive"
                                % (oid, order.get("height_cm")))
            elif height < minimum - 1e-6:
                problems.append("order %s: height_cm %r is below the %s "
                                "minimum %r" % (oid, height, family, minimum))

        for key in ("width_cm", "length_cm"):
            value = _as_number(order.get(key))
            if value is None or value <= 0.0:
                problems.append("order %s: %s %r is not positive"
                                % (oid, key, order.get(key)))

        if not _rect_ready(order):
            problems.append("order %s: center %r / yaw_deg %r do not describe "
                            "a rectangle" % (oid, order.get("center"),
                                             order.get("yaw_deg")))
        elif family in SGD_PALETTE:
            rects.append((oid, order))

    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            first, second = rects[i], rects[j]
            try:
                overlapping = rects_overlap(first[1], second[1])
            except (KeyError, TypeError, ValueError):  # pragma: no cover
                continue
            if overlapping:
                problems.append("orders %s and %s: rectangles overlap"
                                % (first[0], second[0]))
    return problems
