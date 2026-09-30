"""EXPERIMENTAL / NON-PRODUCTION -- do not use for the shipping world.

The Director has rejected custom triangle-by-triangle building production as
the production architecture: Epic's City Sample PCG building system owns
building geometry, facades, windows, ground floors and roofs. This module is
kept as research evidence. It validates clean and its massing renders exactly
as designed, but every building it produced rendered completely UNLIT in the
level and the cause was never found (report section 2.20).

Keep for evidence and tests. Do not deploy.

``building_integration_v1`` -- the join that puts real buildings in the world.

Three modules already exist and are tested, and until this module nothing joined
them:

* ``building_kits`` (``building_kits_v1``) decides, per slot, the facade family,
  massing (height/setback/parapet), the ground-floor band and the roof, plus the
  single civic landmark (``build_kits``, ``massing_variation``,
  ``ground_floor_spec``, ``roof_spec``, ``landmark_spec``, ``FACADE_FAMILIES``);
* ``building_geometry`` (``building_geometry_v1``) turns one building into
  vertices/triangles through ``building_mesh`` and ``landmark_mesh``, with
  material slots 0 wall / 1 roof / 2 ground floor / 3 parapet;
* ``street_life_inputs.building_footprint`` gives the four ground-plane corners
  of one slot's footprint (reused here verbatim -- this module deliberately owns
  no second footprint rule).

The join is what ``ldyf/unreal/ldyf_building_editor.py`` already consumes
(``build_block_mesh`` lines 71-145, ``build_buildings`` lines 148-173), whose
contract is fixed::

    {"schema_version": "building_integration_v1",
     "blocks": {block_id: [{"id": str, "family": str, "geometry": <geo doc>}]},
     "family_paths": {family: "/Game/..."},
     "landmark": {"block": block_id, "id": str, "geometry": <geo doc>},
     "counts": {...}}

One mesh per block, so the per-building entries carry exactly the three keys the
driver reads (``id``, ``family``, ``geometry`` at lines 106-133 and 138); the
extra bookkeeping this module needs for its own validation (footprints, triangle
totals, the landmark's ground placement) lives under ``counts``, which the driver
never touches.

Landmark: exactly once, on the block ``building_kits`` chooses, REPLACING the
ordinary building on that slot instead of standing beside it.  The guarantee is
three-layered, and each layer is a code fact rather than an intention:

1. ``building_kits.build_kits`` picks the landmark slot and drops that slot id
   from the ordinary list (``building_kits.py`` lines 731-733:
   ``landmark_slot_ids = {landmark["building_id"]}`` /
   ``ordinary = [s for s in slots if s["slot_id"] not in landmark_slot_ids]``).
   The ordinary loop this module iterates therefore cannot re-add it.
2. This module cross-checks that fact instead of trusting it: it looks the
   landmark id up in the layout's own slots and raises ``ValueError`` if that
   same id also appears among the ordinary buildings it just emitted, so a
   changed upstream cannot silently produce two buildings on one footprint.
3. ``validate_integration`` records the footprint of the landmark's own slot in
   ``counts["footprints"]`` and runs a real convex-polygon overlap test (SAT,
   not a bounding box) over every pair.  An orphaned ordinary building on the
   landmark slot == the same rectangle twice == an overlap problem, which is
   exactly the defect this check exists to make impossible to ship.

Determinism: sha256 digests only, never ``random``; no clock, no environment, no
``import unreal``.  Every float that reaches the document goes through ``_f3``.
The material paths are read from ``asset_probe_v3.json`` at the repo root --
never invented -- and the choice per family is a digest of the family name, so a
family always yields the same path.

Scope note (what this module does NOT do): it does not place the landmark in
world space.  ``building_geometry.landmark_mesh`` emits the landmark in its
slot's LOCAL frame (see ``building_kits.landmark_spec`` lines 637-640) and the
driver contract's landmark entry has no transform field, so the ground placement
is recorded under ``counts["landmark_placement"]`` rather than silently dropped.
``building_geometry.building_mesh`` keeps its own guards (a footprint side too
small for the 20 cm-proud plinth, a setback wider than the footprint); a layout
that trips them raises ``ValueError`` here rather than emitting a broken mesh.

Pure standard library.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from . import building_geometry as _bg
from . import building_kits as _bk
from . import street_life_inputs as _sli

SCHEMA_VERSION = "building_integration_v1"

#: Probe file the material paths must come from: ``<repo root>/asset_probe_v3.json``
#: (``building_integration.py`` -> ``ldyf/`` -> repo root).
PROBE_FILENAME = "asset_probe_v3.json"


# ---------------------------------------------------------------------------
# small helpers: rounding, digests, the probe file
# ---------------------------------------------------------------------------


def _f3(v: float) -> float:
    """Round to 3 decimals and kill ``-0.0`` (byte determinism)."""
    r = round(float(v), 3)
    return 0.0 if r == 0.0 else r


def _digest(*parts: Any) -> int:
    """Deterministic int from the first 16 hex chars of a sha256 digest."""
    text = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def probe_path() -> Path:
    """Path of the asset probe at the repo root."""
    return Path(__file__).resolve().parent.parent / PROBE_FILENAME


_PROBE_CACHE: dict[str, Any] = {}


def probe_material_paths() -> tuple[str, ...]:
    """``building_materials`` of ``asset_probe_v3.json`` as a tuple.

    Read from the file itself (not from any transcribed copy), so a test that
    reloads the same JSON sees the same list.  Cached per process.
    """
    cached = _PROBE_CACHE.get("materials")
    if cached is None:
        raw = json.loads(probe_path().read_text(encoding="utf-8"))
        mats = raw.get("building_materials") or []
        if not mats:
            raise ValueError(
                f"{probe_path()} carries no 'building_materials' list")
        cached = tuple(str(m) for m in mats)
        _PROBE_CACHE["materials"] = cached
    return cached


def probe_material_set() -> frozenset:
    """The probe file's material paths as a set (membership tests)."""
    return frozenset(probe_material_paths())


# ---------------------------------------------------------------------------
# family -> one concrete material path
# ---------------------------------------------------------------------------


def family_material_paths() -> dict:
    """One probed material path per facade family, deterministically chosen.

    Six ordinary families (``building_kits.FACADE_FAMILIES``) plus the landmark's
    own ``building_kits.CIVIC_FAMILY``, whose members are
    ``building_kits.LANDMARK_MATERIALS``.  For each family the candidate list is
    the family's members that actually appear in ``asset_probe_v3.json``
    (``sorted`` for a stable order) and the chosen path is
    ``candidates[sha256("family_path|<family>") % len(candidates)]`` -- a
    function of the family name alone, so the mapping is stable across runs and
    across machines.

    The driver welds a block's buildings into one mesh and binds the wall slot
    per family (``ldyf_building_editor.py`` lines 89-102, 137-140), which is why
    one path per family is the right granularity here, not one per building.

    Raises ``ValueError`` for a family none of whose members is in the probe
    file: inventing a path is never the answer.
    """
    probed = probe_material_set()
    out: dict = {}
    groups: list = [(name, tuple(members)) for name, members
                    in sorted(_bk.FACADE_FAMILIES.items())]
    groups.append((_bk.CIVIC_FAMILY, tuple(_bk.LANDMARK_MATERIALS)))
    for family, members in groups:
        candidates = sorted({p for p in members if p in probed})
        if not candidates:
            raise ValueError(
                f"facade family {family!r} has no member in {PROBE_FILENAME}")
        out[family] = candidates[_digest("family_path", family)
                                 % len(candidates)]
    return out


# ---------------------------------------------------------------------------
# overlap test (real polygon test, not a bounding box)
# ---------------------------------------------------------------------------


def _project(poly: list, ax: float, ay: float) -> tuple:
    dots = [pt[0] * ax + pt[1] * ay for pt in poly]
    return min(dots), max(dots)


def footprints_overlap(a: list, b: list, *, tol: float = 1e-6) -> bool:
    """True when two convex footprint polygons overlap with positive area.

    Separating-axis theorem over both rings' edge normals.  Shared edges -- the
    normal case for neighbouring slots along one frontage, which abut exactly --
    are NOT an overlap: a candidate axis separates them by ``<= tol``.  This is
    the real test the landmark-orphan case needs: the same rectangle twice has
    no separating axis, so it overlaps.
    """
    if len(a) < 3 or len(b) < 3:
        return False
    for poly in (a, b):
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            ax, ay = -(y2 - y1), (x2 - x1)
            if ax == 0.0 and ay == 0.0:
                continue
            a0, a1 = _project(a, ax, ay)
            b0, b1 = _project(b, ax, ay)
            if a1 <= b0 + tol or b1 <= a0 + tol:
                return False
    return True


# ---------------------------------------------------------------------------
# the join
# ---------------------------------------------------------------------------


def _slots_of(layout: dict) -> list:
    return list((layout.get("building_slots") or {}).get("slots") or [])


def _corners(slot: dict, depth_cm: float) -> list:
    """Footprint of one slot as ``[{"x": .., "y": ..}, ...]``.

    The single footprint rule is ``street_life_inputs.building_footprint``; this
    is only the rounding wrapper.
    """
    return [{"x": _f3(c["x"]), "y": _f3(c["y"])}
            for c in _sli.building_footprint(slot, depth_cm=depth_cm)]


def _ring_xy(corners: list) -> list:
    """``[{"x","y"}, ...]`` -> ``[[x, y], ...]`` for the footprint bookkeeping."""
    return [[_f3(c["x"]), _f3(c["y"])] for c in corners]


def integrate_buildings(layout: dict, *, depth_cm: float, seed: int,
                        **kw: Any) -> dict:
    """Join ``city_layout_v1`` + ``building_kits_v1`` + ``building_geometry_v1``.

    For every building slot of ``layout``:

    * footprint -- ``street_life_inputs.building_footprint(slot, depth_cm=...)``
      (the rectangle recedes ``depth_cm`` away from the street);
    * family, massing, ground floor and roof -- ``building_kits.build_kits``,
      which also names the one landmark slot and removes it from the ordinary
      list;
    * geometry -- ``building_geometry.building_mesh(footprint, massing,
      ground_floor, roof, seed=seed)``, or ``landmark_mesh`` for the landmark.

    The result is grouped by ``block_id`` with keys and ids sorted, so two runs
    on the same layout are byte-identical under
    ``json.dumps(..., sort_keys=True)``.  ``kw`` is forwarded to ``build_kits``
    (which ignores keys it does not use).

    Raises ``ValueError`` when ``depth_cm`` is not a positive finite number, when
    the layout has no building slots, when the landmark's slot is missing from
    the layout, or when the landmark slot id also turns up as an ordinary
    building (two buildings on one footprint) -- and, from
    ``building_geometry``, for a slot whose footprint cannot carry the mesh its
    kit asks for.
    """
    depth = float(depth_cm)
    if not math.isfinite(depth) or depth <= 0.0:
        raise ValueError(
            "integrate_buildings: depth_cm must be positive and finite, "
            f"got {depth_cm!r}")
    slots = _slots_of(layout)
    if not slots:
        raise ValueError("integrate_buildings: layout has no building slots")
    seed = int(seed)

    kws = dict(kw)
    kws["seed"] = seed
    kits = _bk.build_kits(layout, **kws)

    blocks: dict = {}
    footprints: dict = {}
    tris_buildings = 0
    by_family: dict = {}
    for entry in kits["buildings"]:
        bid = entry["building_id"]
        corners = _corners(entry, depth)
        geo = _bg.building_mesh(corners, entry["massing"],
                                entry["ground_floor"], entry["roof"],
                                seed=seed)
        blocks.setdefault(entry["block_id"], []).append(
            {"id": bid, "family": entry["family"], "geometry": geo})
        footprints[bid] = _ring_xy(corners)
        tris_buildings += int(geo["counts"]["triangles"])
        by_family[entry["family"]] = by_family.get(entry["family"], 0) + 1

    # ---- the landmark: one, and it replaces its slot ----------------------
    landmark_spec = kits["landmark"]
    lm_id = landmark_spec["building_id"]
    lm_slot = next((s for s in slots if s["slot_id"] == lm_id), None)
    if lm_slot is None:
        raise ValueError(
            f"landmark slot {lm_id!r} is not in the layout's building slots")
    ordinary_ids = {e["id"] for entries in blocks.values() for e in entries}
    if lm_id in ordinary_ids:
        raise ValueError(
            f"landmark slot {lm_id!r} is also emitted as an ordinary building; "
            "the landmark must REPLACE its slot, not stand beside it")
    lm_geo = _bg.landmark_mesh(landmark_spec, seed=seed)
    footprints[lm_id] = _ring_xy(_corners(lm_slot, depth))
    tris_landmark = int(lm_geo["counts"]["triangles"])

    ordered = {bid: sorted(blocks[bid], key=lambda e: e["id"])
               for bid in sorted(blocks)}
    landmark = {"block": landmark_spec["block_id"], "id": lm_id,
                "geometry": lm_geo}
    counts = {
        "schema_version": SCHEMA_VERSION,
        "depth_cm": _f3(depth),
        "seed": seed,
        "slots": len(slots),
        "blocks": len(ordered),
        "buildings": sum(len(v) for v in ordered.values()),
        "landmark": 1,
        "triangles": tris_buildings + tris_landmark,
        "triangles_buildings": tris_buildings,
        "triangles_landmark": tris_landmark,
        "by_family": {f: by_family[f] for f in sorted(by_family)},
        # The landmark mesh is built in its slot's LOCAL frame (origin at the
        # footprint centre on the ground, see building_kits.landmark_spec lines
        # 637-640) and the contract's landmark entry carries no transform, so
        # the ground placement is recorded here rather than dropped.
        "landmark_placement": {
            "x": _f3(landmark_spec["x"]),
            "y": _f3(landmark_spec["y"]),
            "yaw": _f3(landmark_spec["yaw"]),
            "footprint_cm": landmark_spec["footprint_cm"],
        },
        # id -> [[x, y], ...]: what validate_integration tests for overlap.
        "footprints": {bid: footprints[bid] for bid in sorted(footprints)},
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "blocks": ordered,
        "family_paths": family_material_paths(),
        "landmark": landmark,
        "counts": counts,
    }


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def _landmark_entries(doc: dict) -> list:
    """The document's landmark entries as a list (0, 1 or more)."""
    lm = doc.get("landmark")
    if lm is None:
        return []
    if isinstance(lm, list):
        return list(lm)
    return [lm]


def _doc_footprints(doc: dict) -> dict:
    """``id -> polygon`` for the overlap test.

    ``counts["footprints"]`` is authoritative.  For a hand-made document that
    carries none, a building's own geometry bounds are used as its rectangle:
    that is a weaker test (an axis-aligned box, not the footprint), which is why
    it is only the fallback.
    """
    out: dict = {}
    counts = doc.get("counts") or {}
    raw = counts.get("footprints")
    if isinstance(raw, dict):
        for bid, ring in raw.items():
            if isinstance(ring, list) and len(ring) >= 3:
                out[str(bid)] = [[float(p[0]), float(p[1])] for p in ring]
    for block_id in sorted(doc.get("blocks") or {}):
        for entry in (doc.get("blocks") or {}).get(block_id) or []:
            if not isinstance(entry, dict):
                continue
            bid = str(entry.get("id"))
            if bid in out:
                continue
            bounds = ((entry.get("geometry") or {}).get("bounds") or {})
            if "min_x" in bounds:
                out[bid] = [[bounds["min_x"], bounds["min_y"]],
                            [bounds["max_x"], bounds["min_y"]],
                            [bounds["max_x"], bounds["max_y"]],
                            [bounds["min_x"], bounds["max_y"]]]
    return out


def validate_integration(doc: dict) -> list:
    """Problems with a ``building_integration_v1`` document; empty means valid.

    Catches, each as one human-readable string:

    * a geometry document that fails ``building_geometry.validate_geometry``
      (per building and for the landmark, prefixed with the building id);
    * a building whose ``family`` has no entry in ``family_paths``;
    * a material path in ``family_paths`` that is absent from
      ``asset_probe_v3.json``;
    * anything other than exactly one landmark;
    * a block with zero buildings;
    * two buildings -- or a building and the landmark -- whose footprints
      overlap: a real convex-polygon test (SAT) over ``counts["footprints"]``,
      with the geometry bounds as the fallback rectangle for a document without
      them.  This is the check that catches an orphaned ordinary building left
      on the landmark's slot;
    * the landmark's id also appearing among the block buildings (the same
      defect, named directly).
    """
    problems: list = []
    if not isinstance(doc, dict):
        return ["document is not a dict"]
    if doc.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            f"schema_version is not {SCHEMA_VERSION}: "
            f"{doc.get('schema_version')!r}")

    paths = doc.get("family_paths")
    if not isinstance(paths, dict) or not paths:
        problems.append("family_paths missing or empty")
        paths = {}
    probed = probe_material_set()
    for family in sorted(paths):
        path = paths[family]
        if path not in probed:
            problems.append(
                f"family_paths[{family!r}] = {path!r} is not in "
                f"{PROBE_FILENAME}")

    blocks = doc.get("blocks")
    if not isinstance(blocks, dict):
        problems.append("blocks missing or not a dict")
        blocks = {}

    building_ids: list = []
    for block_id in sorted(blocks):
        entries = blocks[block_id]
        if not isinstance(entries, list):
            problems.append(f"block {block_id!r} is not a list of buildings")
            continue
        if not entries:
            problems.append(f"block {block_id!r} has zero buildings")
            continue
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                problems.append(f"block {block_id!r} entry #{i} is not a dict")
                continue
            bid = str(entry.get("id", f"{block_id}#{i}"))
            building_ids.append(bid)
            family = entry.get("family")
            if family not in paths:
                problems.append(
                    f"{bid}: family {family!r} has no entry in family_paths")
            for p in _bg.validate_geometry(entry.get("geometry")):
                problems.append(f"{bid}: {p}")

    landmarks = _landmark_entries(doc)
    if len(landmarks) != 1:
        problems.append(
            f"expected exactly one landmark, found {len(landmarks)}")
    for lm in landmarks:
        if not isinstance(lm, dict):
            problems.append("landmark entry is not a dict")
            continue
        lm_id = str(lm.get("id"))
        if not lm_id:
            problems.append("landmark entry has no id")
        if lm.get("block") not in blocks:
            problems.append(
                f"landmark {lm_id} names block {lm.get('block')!r} which has "
                "no buildings")
        if lm_id in building_ids:
            problems.append(
                f"landmark {lm_id} also appears as an ordinary building: the "
                "landmark must replace its slot, not stand beside it")
        for p in _bg.validate_geometry(lm.get("geometry")):
            problems.append(f"landmark {lm_id}: {p}")

    # footprint overlap, including the landmark's slot footprint
    rings = _doc_footprints(doc)
    ids = list(building_ids)
    for lm in landmarks:
        if isinstance(lm, dict) and lm.get("id") is not None:
            ids.append(str(lm.get("id")))
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            if a not in rings or b not in rings:
                continue
            if a == b:
                problems.append(
                    f"{a}: the same id appears twice (two buildings on one "
                    "footprint)")
                continue
            if footprints_overlap(rings[a], rings[b]):
                problems.append(
                    f"{a} and {b}: footprints overlap "
                    "(two buildings on one footprint)")
    return problems
