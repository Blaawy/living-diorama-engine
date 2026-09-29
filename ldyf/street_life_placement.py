"""What mesh each ``street_life`` item wears, and the transform to spawn it.

``ldyf.street_life`` is the placement half of street life: it decides WHERE a
storefront, a sign, a rooftop prop and a parked car go, in centimetres, and
carries no asset knowledge at all. ``build_street_life`` returns those four
lists plus the conflict pairs (street_life.py:953-977). This module is the
other half: one row per source item, holding mesh path, world position, yaw
and uniform scale -- everything an *instanced static mesh* spawner needs and
nothing more.

Schema: ``street_life_placement_v1``. A ``street_life_v1`` document is
required; anything else raises ``ValueError``.

WHERE ``z_cm`` COMES FROM (the point of the module)
---------------------------------------------------
No ``street_life`` item carries a ``z``, and the layout itself is 2D plus
heights. Each kind draws its row height from a different place, and each one is
stated here:

* ``sign`` -- ``z_cm = item["height_cm"]``, the sign's clear mounting height
  above the pavement. ``street_life.sign_slots`` already emits it (220-340 cm;
  street_life.py:601) and documents it as the clearance over the pavement for
  a flat sign against the wall (street_life.py:572-573).
* ``rooftop_prop`` -- ``z_cm = roof_record["height_cm"]`` for the building
  named by the item's ``building_id``: the prop sits ON its building's roof
  plane. Never 0, and never the prop's own ``height_cm``, which is the size of
  the vent/AC box, not where it stands.
* ``parked_car`` -- ``z_cm = 0.0``, the layout's ground plane, i.e. the road
  surface. A parked car item is x/y/yaw/lengths only (street_life.py:887-897).
* ``storefront`` -- ``z_cm = 0.0``, the footway at grade. The source carries
  ``footway_cm`` (facade-to-kerb distance) and no z.

``0.0`` is the ground plane of this frame, not a claim about ride height: the
wider project carries ground clearance as an injected ``surface_z_cm``
argument rather than a constant (playback_core.py:41, 228-230;
dressing_check.py:380-382), so a spawner that has one adds it; this module
cannot know it and does not guess it.

MESH TABLES, AND THE THREE THAT ARE EMPTY
-----------------------------------------
Each table is a list of real ``/Game/...`` paths seen in this repository, so a
variant can be rolled per item by sha256 digest. A category with no *plausible*
real asset is left EMPTY and every item of that category is reported in
``skipped`` with a reason -- an invented path spawns nothing and is worse than
an honest gap.

* ``SIGN_MESHES`` -- populated. The four sign meshes of ``asset_probe_v3.json``
  lines 124-130 (its ``prop_signs`` list). These are street signage, not
  authored shop blades; they are the only verified sign geometry in the
  project. ``SM_StreetLamp_A_WalkSignal_Latch`` is excluded: a latch is bracket
  hardware, not a sign face.
* ``STOREFRONT_MESHES`` -- EMPTY. No shopfront/entrance mesh appears in
  ``ldyf/dressing_assets.py`` or ``asset_probe_v3.json``. The nearest real
  props are street furniture (bench, bin, lamp, cone), which read as furniture
  against a facade, not as glazing or a door. A storefront mesh also has to
  match a slot width that runs 260-1400 cm (street_life.py:534-538), which one
  mesh cannot do.
* ``ROOFTOP_MESHES`` -- EMPTY. ``street_life``'s roof kinds are
  ``vent``/``ac_unit``/``stair_house``/``antenna`` (street_life.py:100); no
  mesh in either named source is any of those. The only roof-adjacent real
  meshes available are fascia/base items (``SM_TreeBase_Circle_A``,
  dressing_assets.py:75) and street furniture, which on a roof read as a bin
  or a bench in the sky.
* ``PARKED_VEHICLE_MESHES`` -- EMPTY. Neither named source carries a vehicle
  mesh. The only car mesh path anywhere in the repository is
  ``/Game/Vehicle/vehCar_vehicle02/Mesh/SKM_vehCar_vehicle02`` (quoted verbatim
  in ldyf/tests/test_world_inventory.py:145 and ldyf/tests/test_playback_core.py:302),
  and it is a *skeletal* mesh -- test_world_inventory.py:314 binds
  ``/Game/Vehicle/vehCar_vehicle02/Anim/SKM_vehCar_vehicle02_Anim`` to it. A
  static-mesh instance cannot wear it, so it is recorded here as the candidate
  that was checked and rejected, not used.

DENSITY PER 100 m OF FRONTAGE
-----------------------------
This module adds no density of its own: exactly one row per source item and one
skipped entry per item it cannot place, so the city's density is whatever
``street_life`` already emits. At its documented defaults:

* storefronts: one per 6 m of frontage -- ``DEFAULT_STOREFRONT_SPACING_CM``
  (street_life.py:83, "-> 1.7 storefronts per 100 m");
* signs: one per storefront x ``sign_share`` 0.35, about 0.6 per 100 m
  (street_life.sign_slots docstring, street_life.py:562);
* rooftop props: one per ~700 m2 of roof, capped at 4 per roof
  (street_life.py:89, 634-636);
* parked cars: one per (460 cm car + 80 cm bumper gap) = 540 cm of legal kerb
  run, times occupancy 0.30, i.e. about 5.6 per 100 m of kerb
  (street_life.py:90-93), outside junction and crosswalk clearances.

That is the Director's "only enough professional detail to stop the city
feeling empty": of the order of two shopfronts, half a sign and five cars per
100 m of frontage, and a couple of objects on a whole roof. Nothing here
duplicates an item, invents extra rows, or fills a gap with a stand-in mesh.

Determinism: sha256 only (``_digest``), no ``random``, no clock, and the
module imports no Unreal and touches no disk.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence

__all__ = [
    "PLACEMENT_VERSION",
    "SOURCE_VERSION",
    "KINDS",
    "SOURCE_LISTS",
    "SIGN_MESHES",
    "STOREFRONT_MESHES",
    "ROOFTOP_MESHES",
    "PARKED_VEHICLE_MESHES",
    "MESH_TABLES",
    "SCALE_BAND",
    "GLOBAL_SCALE_BAND",
    "Z_FLOOR_CM",
    "Z_CEILING_CM",
    "placement_rows",
    "group_by_mesh",
    "validate_placement",
]

PLACEMENT_VERSION = "street_life_placement_v1"
SOURCE_VERSION = "street_life_v1"

#: The four item categories, in the order the source document lists them.
KINDS = ("storefront", "sign", "rooftop_prop", "parked_car")

#: kind -> key in the ``street_life_v1`` document (build_street_life,
#: street_life.py:965-968).
SOURCE_LISTS = {
    "storefront": "storefronts",
    "sign": "signs",
    "rooftop_prop": "rooftop_props",
    "parked_car": "parked_cars",
}

# --- mesh tables ------------------------------------------------------------
# Variant per item: table[_digest(seed, source_id, "mesh") % len(table)].

# asset_probe_v3.json:124-130, its "prop_signs" list. Street signage used as
# the sign row's mesh: a sign on a facade is still a plate on a bracket.
SIGN_MESHES = [
    "/Game/Prop/Kit_StopSign_A/Mesh/SM_StopSign_A",
    "/Game/Prop/Kit_StreetLamp_A/Mesh/SM_StreetLamp_A_OneWaySign",
    "/Game/Prop/Kit_StreetLamp_A/Mesh/SM_StreetLamp_A_WalkSignal_01",
    "/Game/Prop/Kit_StreetLamp_A/Mesh/SM_StreetLamp_A_WalkSignal_02",
]

# EMPTY on purpose -- see the module docstring: no shopfront mesh exists in
# ldyf/dressing_assets.py or asset_probe_v3.json, and one mesh cannot match a
# 260-1400 cm slot width. Every storefront item is reported in `skipped`.
STOREFRONT_MESHES: list[str] = []

# EMPTY on purpose -- vent/ac_unit/stair_house/antenna (street_life.py:100)
# appear in neither named source. Every rooftop item is reported in `skipped`.
ROOFTOP_MESHES: list[str] = []

# EMPTY on purpose -- the only car mesh in the repository is the skeletal
# /Game/Vehicle/vehCar_vehicle02/Mesh/SKM_vehCar_vehicle02
# (ldyf/tests/test_world_inventory.py:145), which a static mesh instance
# cannot wear. Every parked car item is reported in `skipped`.
PARKED_VEHICLE_MESHES: list[str] = []

MESH_TABLES = {
    "storefront": STOREFRONT_MESHES,
    "sign": SIGN_MESHES,
    "rooftop_prop": ROOFTOP_MESHES,
    "parked_car": PARKED_VEHICLE_MESHES,
}

# --- stated bands, used by validate_placement -------------------------------

#: Uniform scale a row may carry, per kind. A sign plate varies with the
#: source's width_cm (80-140 cm, street_life.py:600) so it takes the widest
#: band; a car must not be distorted more than the sedan/hatch/suv/compact
#: family already varies (street_life.py:108); a shopfront is authored to the
#: facade; a roof object is a box of a stated size (street_life.py:102-107).
SCALE_BAND = {
    "storefront": (0.95, 1.05),
    "sign": (0.90, 1.15),
    "rooftop_prop": (0.90, 1.10),
    "parked_car": (0.96, 1.04),
}
GLOBAL_SCALE_BAND = (0.90, 1.15)

#: z sanity band. Nothing this module places is below the ground plane, and
#: 30 000 cm is an order of magnitude above the tallest roof plane the project
#: authors (height sampled in 1600-2600 cm, snapped up to a 300 cm storey, so
#: at most 2400 -- street_life_inputs.py:320-323, 361-367).
Z_FLOOR_CM = 0.0
Z_CEILING_CM = 30000.0

_SKIP_REASON = {
    "storefront": ("no_mesh_table",
                   "STOREFRONT_MESHES is empty: no shopfront mesh exists in "
                   "ldyf/dressing_assets.py or asset_probe_v3.json"),
    "sign": ("no_mesh_table",
             "SIGN_MESHES is empty: no sign mesh exists in the named sources"),
    "rooftop_prop": ("no_mesh_table",
                     "ROOFTOP_MESHES is empty: no vent/ac_unit/stair_house/"
                     "antenna mesh exists in the named sources"),
    "parked_car": ("no_mesh_table",
                   "PARKED_VEHICLE_MESHES is empty: no static car mesh exists "
                   "in the named sources"),
}


def _f3(value: Any) -> float:
    """Every float in this module goes through here (3 dp, as street_life)."""
    return round(float(value), 3)


def _digest(*parts: Any) -> int:
    """sha256 of the parts, as an int. No RNG anywhere in this module."""
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"\x1f")
    return int.from_bytes(h.digest()[:8], "big")


def _tables(mesh_tables: Mapping[str, Sequence[str]] | None) -> dict[str, list[str]]:
    """The module tables, with any caller override applied on top.

    The override exists so the z rules of all four kinds stay testable while
    the production tables stay honest: a test may inject placeholder meshes for
    a category whose real table is empty, and nothing in production does.
    """
    tables = {kind: list(MESH_TABLES[kind]) for kind in KINDS}
    if mesh_tables:
        for kind, paths in mesh_tables.items():
            tables[str(kind)] = [str(p) for p in (paths or ())]
    return tables


def _building_index(buildings: Any) -> dict[str, Mapping[str, Any]]:
    """Roof records by id, so a rooftop prop can find its roof-plane height.

    ``buildings`` is what ``street_life_inputs.roof_polygons`` emits:
    ``{"id", "polygon", "height_cm", ...}`` per building
    (street_life_inputs.py:302-379), and ``rooftop_props`` names it through
    ``building_id`` == that ``id`` (street_life.py:698).
    """
    if buildings is None:
        return {}
    if isinstance(buildings, Mapping):
        buildings = buildings.get("buildings") or buildings.get("slots") or []
    out: dict[str, Mapping[str, Any]] = {}
    for rec in buildings:
        if not isinstance(rec, Mapping):
            continue
        key = str(rec.get("id", rec.get("building_id", "")))
        if key:
            out[key] = rec
    return out


def _pick(table: Sequence[str], *parts: Any) -> str:
    return str(table[_digest(*parts) % len(table)])


def _roll_scale(kind: str, source_id: str, seed: int) -> float:
    lo, hi = SCALE_BAND.get(kind, GLOBAL_SCALE_BAND)
    unit = _digest(seed, source_id, "scale") / float(0xFFFFFFFFFFFFFFFF)
    return _f3(lo + (hi - lo) * unit)


def _skipped(kind: str, source_id: str, code: str, reason: str) -> dict:
    return {"kind": kind, "source_id": str(source_id),
            "reason_code": code, "reason": reason}


def _row_for(kind: str, item: Mapping[str, Any], source_id: str,
             table: Sequence[str], seed: int,
             roofs: Mapping[str, Mapping[str, Any]]) -> tuple[dict | None, str | None]:
    """One row, or (None, reason) when the item's z cannot be stated."""
    x, y = item.get("x"), item.get("y")
    if x is None or y is None:
        return None, "source item has no x/y to place a mesh at"
    if kind == "rooftop_prop":
        building_id = str(item.get("building_id"))
        rec = roofs.get(building_id)
        if rec is None or rec.get("height_cm") is None:
            return None, ("no roof record with height_cm for building_id %r: a "
                          "rooftop prop's z is its building's roof height, and "
                          "that height is not in the item" % building_id)
        z_cm = float(rec["height_cm"])
    elif kind == "sign":
        # mounting height over the pavement, carried by the source item
        z_cm = float(item.get("height_cm") or 0.0)
    else:
        # storefront on the footway, parked car on the road: both at grade
        z_cm = 0.0
    yaw = float(item.get("yaw_deg") or 0.0)
    return ({
        "id": "%s:%s" % (kind, source_id),
        "kind": kind,
        "mesh": _pick(table, seed, source_id, "mesh"),
        "x": _f3(x),
        "y": _f3(y),
        "z_cm": _f3(z_cm),
        "yaw_deg": _f3(yaw % 360.0),
        "scale": _roll_scale(kind, source_id, seed),
        "source_id": source_id,
    }, None)


def placement_rows(street_life_doc: Mapping[str, Any], *, seed: int = 0,
                   buildings: Any = None,
                   mesh_tables: Mapping[str, Sequence[str]] | None = None) -> dict:
    """``street_life_v1`` document -> ``street_life_placement_v1`` rows.

    Returns ``{"schema_version", "rows", "counts", "skipped"}``.

    One row per source item: ``{"id", "kind", "mesh", "x", "y", "z_cm",
    "yaw_deg", "scale", "source_id"}`` where ``source_id`` is the id of the
    item in the source document and ``scale`` is uniform, drawn from
    ``SCALE_BAND[kind]`` by digest of ``(seed, source_id)``. ``z_cm`` per kind
    is stated in the module docstring; for a rooftop prop it needs
    ``buildings`` -- the roof records, e.g. ``street_life_inputs`` -->
    ``doc["buildings"]`` -- or ``doc["buildings"]`` when the argument is
    omitted. For rooftop props only, an item whose building has no record (or a
    record with no ``height_cm``) goes to ``skipped`` with
    ``reason_code "no_z_source"``: without the roof height there is no honest
    z to use.

    Any other item that cannot be placed goes to ``skipped`` as
    ``{"kind", "source_id", "reason_code", "reason"}`` -- never dropped
    silently -- so ``len(rows) + len(skipped)`` equals the number of source
    items.
    """
    if not isinstance(street_life_doc, Mapping) or \
            street_life_doc.get("schema_version") != SOURCE_VERSION:
        raise ValueError(
            "placement_rows needs a %s document, got %r"
            % (SOURCE_VERSION,
               None if not isinstance(street_life_doc, Mapping)
               else street_life_doc.get("schema_version")))

    seed = int(seed)
    tables = _tables(mesh_tables)
    roofs = _building_index(buildings if buildings is not None
                            else street_life_doc.get("buildings"))

    rows: list[dict] = []
    skipped: list[dict] = []
    source_items: dict[str, int] = {}
    for kind in KINDS:
        items = list(street_life_doc.get(SOURCE_LISTS[kind]) or ())
        source_items[kind] = len(items)
        table = tables.get(kind) or []
        for item in items:
            if not isinstance(item, Mapping):
                skipped.append(_skipped(kind, "", "bad_item",
                                        "source item is not a record"))
                continue
            source_id = str(item.get("id"))
            if not table:
                code, reason = _SKIP_REASON.get(
                    kind, ("no_mesh_table", "mesh table for %s is empty" % kind))
                skipped.append(_skipped(kind, source_id, code, reason))
                continue
            row, reason = _row_for(kind, item, source_id, table, seed, roofs)
            if row is None:
                skipped.append(_skipped(kind, source_id, "no_z_source", reason))
                continue
            rows.append(row)

    rows.sort(key=lambda r: str(r["id"]))
    skipped.sort(key=lambda s: (str(s["kind"]), str(s["source_id"])))
    by_kind: dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    by_mesh: dict[str, int] = {}
    for r in rows:
        by_mesh[r["mesh"]] = by_mesh.get(r["mesh"], 0) + 1
    return {
        "schema_version": PLACEMENT_VERSION,
        "rows": rows,
        "counts": {
            "rows": len(rows),
            "skipped": len(skipped),
            "source_items": source_items,
            "by_kind": {k: by_kind[k] for k in sorted(by_kind)},
            "by_mesh": {m: by_mesh[m] for m in sorted(by_mesh)},
        },
        "skipped": skipped,
    }


def group_by_mesh(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    """Rows bucketed by mesh path -- one instanced component per mesh.

    Keys are mesh paths in sorted order; each bucket is sorted by row id, so
    the same input always yields the same key order and the driver's component
    creation order is stable. The buckets partition the rows exactly: every row
    appears once, under its own mesh, and nowhere else.
    """
    out: dict[str, list[dict]] = {}
    for row in rows:
        out.setdefault(str(row.get("mesh")), []).append(dict(row))
    return {mesh: sorted(out[mesh], key=lambda r: str(r.get("id")))
            for mesh in sorted(out)}


def validate_placement(doc: Mapping[str, Any], source: Mapping[str, Any] | None = None,
                       mesh_tables: Mapping[str, Sequence[str]] | None = None) -> list[str]:
    """Problems with a ``street_life_placement_v1`` document; empty == valid.

    Catches: a row whose mesh is in no table; a negative or absurd ``z_cm``
    (outside ``[Z_FLOOR_CM, Z_CEILING_CM]``); a ``scale`` outside
    ``SCALE_BAND[kind]``; a duplicate row id; a row whose ``source_id`` names
    nothing in the source document; a count mismatch between
    ``rows + skipped`` and the source items. It also reports a missing row key,
    an unknown kind and a ``skipped`` entry with no reason.

    ``source`` is the ``street_life_v1`` document the rows came from; it is
    also taken from ``doc["source"]`` when the argument is omitted. Without it
    the two source-dependent checks (``source_id`` resolution and the count)
    cannot run, and the function says so instead of passing quietly.
    ``mesh_tables`` overrides the tables the mesh check uses, for the same
    reason ``placement_rows`` takes an override.

    Raises ``ValueError`` on a document with the wrong schema version.
    """
    if not isinstance(doc, Mapping) or \
            doc.get("schema_version") != PLACEMENT_VERSION:
        raise ValueError(
            "validate_placement needs a %s document, got %r"
            % (PLACEMENT_VERSION,
               None if not isinstance(doc, Mapping)
               else doc.get("schema_version")))
    if source is None:
        source = doc.get("source")

    allowed = {m for table in _tables(mesh_tables).values() for m in table}
    required = ("id", "kind", "mesh", "x", "y", "z_cm", "yaw_deg", "scale",
                "source_id")
    problems: list[str] = []
    rows = [r for r in (doc.get("rows") or ()) if isinstance(r, Mapping)]
    skipped = [s for s in (doc.get("skipped") or ()) if isinstance(s, Mapping)]

    rows_by_kind: dict[str, int] = {}
    skipped_by_kind: dict[str, int] = {}
    seen_ids: set[str] = set()

    for row in rows:
        rid = str(row.get("id"))
        kind = str(row.get("kind"))
        for key in required:
            if key not in row:
                problems.append("row %r: missing key %r" % (rid, key))
        if rid in seen_ids:
            problems.append("duplicate row id %r" % rid)
        seen_ids.add(rid)
        if kind not in KINDS:
            problems.append("row %s: kind %r is not one of %s"
                            % (rid, kind, ", ".join(KINDS)))
        if row.get("mesh") not in allowed:
            problems.append("row %s: mesh %r is in no mesh table"
                            % (rid, row.get("mesh")))
        z_cm = row.get("z_cm")
        if isinstance(z_cm, bool) or not isinstance(z_cm, (int, float)):
            problems.append("row %s: z_cm %r is not a number" % (rid, z_cm))
        elif not Z_FLOOR_CM <= float(z_cm) <= Z_CEILING_CM:
            problems.append("row %s: z_cm %r outside [%s, %s] -- negative or "
                            "absurd" % (rid, z_cm, Z_FLOOR_CM, Z_CEILING_CM))
        scale = row.get("scale")
        lo, hi = SCALE_BAND.get(kind, GLOBAL_SCALE_BAND)
        if isinstance(scale, bool) or not isinstance(scale, (int, float)):
            problems.append("row %s: scale %r is not a number" % (rid, scale))
        elif not lo <= float(scale) <= hi:
            problems.append("row %s: scale %r outside the stated band [%s, %s] "
                            "for kind %s" % (rid, scale, lo, hi, kind))
        rows_by_kind[kind] = rows_by_kind.get(kind, 0) + 1

    for entry in skipped:
        code = entry.get("reason_code")
        reason = entry.get("reason")
        if not reason or not code:
            problems.append("skipped entry %r has no reason and/or reason_code"
                            % (entry.get("source_id"),))
        kind = str(entry.get("kind"))
        if kind not in KINDS:
            problems.append("skipped entry for %r: kind %r is not one of %s"
                            % (entry.get("source_id"), kind, ", ".join(KINDS)))
            continue
        skipped_by_kind[kind] = skipped_by_kind.get(kind, 0) + 1

    if source is None:
        problems.append("no source document supplied: the source_id and count "
                        "checks were not run")
        return sorted(problems)
    if source.get("schema_version") != SOURCE_VERSION:
        problems.append("source document is not %s (got %r)"
                        % (SOURCE_VERSION, source.get("schema_version")))

    ids_by_kind = {
        kind: {str(i.get("id")) for i in (source.get(SOURCE_LISTS[kind]) or ())
               if isinstance(i, Mapping)}
        for kind in KINDS
    }
    for row in rows:
        kind = str(row.get("kind"))
        if kind not in KINDS:
            continue
        if str(row.get("source_id")) not in ids_by_kind[kind]:
            problems.append("row %s: source_id %r names no item in source[%s]"
                            % (row.get("id"), row.get("source_id"),
                               SOURCE_LISTS[kind]))
    for kind in KINDS:
        want = len(source.get(SOURCE_LISTS[kind]) or ())
        got = rows_by_kind.get(kind, 0) + skipped_by_kind.get(kind, 0)
        if got != want:
            problems.append("count mismatch for %s: %d rows + %d skipped != %d "
                            "source items (%d unaccounted)"
                            % (SOURCE_LISTS[kind], rows_by_kind.get(kind, 0),
                               skipped_by_kind.get(kind, 0), want, want - got))
    return sorted(problems)
