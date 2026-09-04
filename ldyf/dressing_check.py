"""dressing_check.py -- validate a dressing_snapshot_v1 against the dressing_v1 plan.

Consumes the snapshot the in-editor sampler takes of SPAWNED dressing
(decals + InstancedStaticMesh instances, ``ldyf/unreal/ldyf_dressing_editor.py``)
and compares it against the independent ``dressing_v1`` document
(``ldyf/dressing.py``), exactly as the settled dressing design demands.

Laws encoded here
-----------------
* Decal size contract.  The editor sets ``decal_size = Vector(depth,
  half_width, half_length)`` (``_decal`` in the dressing editor), so a paint
  decal satisfies ``2 * size_y == width_cm`` and ``2 * size_z == length_cm``:
  for a lane marking that is the planned ``width_cm`` / ``length_cm``, for a
  crosswalk stripe the planned ``size_across_cm`` / ``size_along_cm``.
* Yaw law differs by category, which is the crux of this module:

  * markings and crosswalk stripes are paint and symmetric: compared modulo
    180, folded at 90, so a 180-degree flip of a painted line PASSES;
  * signals are directional (placed facing back down the approach so a driver
    sees the face): compared over the full 360 degrees, so a 180-degree flip
    FAILS;
  * trees are never yaw-compared -- the editor assigns a digest-derived
    rotation the plan does not specify, so comparing yaw would compare against
    a number the plan never promised.  ``match_props(..., yaw_tol_deg=None)``
    is how that is expressed.

* Contact law.  ``check_ground_contact`` asserts
  ``z + min_z * scale_z == surface_z_cm`` within ``tol_cm`` (raw float
  compare -- nothing is rounded away, so a kilometre of vertical displacement
  can never be reported as a pass), where ``min_z`` comes from a caller
  supplied ``mesh_bounds`` map.  A ``buried`` map (mesh -> allowed depth cm)
  shifts the expectation downward; only street trees are buried.
* Pairing law.  Planned rows in sorted id order each claim the nearest
  not-yet-claimed snapshot row of the expected kind (family split by actor
  label prefix).  Nearest beyond ``match_max_cm`` (default 50.0) becomes
  ``unmatched_planned``; snapshot rows nobody claimed become
  ``unmatched_snapshot`` -- both are failures and both appear in every report.
* Empty is never a pass.  A category with nothing compared sets
  ``insufficient_sample: True`` and ``pass: False``; the overall ``pass``
  requires every sub-check to pass AND every category to have compared at
  least one row.
* Asset paths are normalised before comparing: a trailing ``.ObjectName``
  suffix after the final dot is stripped, so ``/Game/X/SM_Y.SM_Y`` equals
  ``/Game/X/SM_Y``.  A missing ``scale_z`` counts as 1.0.

Determinism laws (same as the other checkers): pure stdlib, floats rounded
through ``_f3`` for output only, iteration over planned rows sorted by id, and
``json.dumps(indent=2, sort_keys=True)`` on write.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

DRESSING_CHECK_VERSION = "dressing_check_v1"

# Actor-label prefixes that split the flat snapshot into the dressing
# families (identical to ldyf.unreal.ldyf_dressing_editor).
MARK_PREFIX = "LD_Mark"
CROSSWALK_PREFIX = "LD_Crosswalk"
SIGNAL_PREFIX = "LD_Signal"
TREE_PREFIX = "LD_Tree"
CLOSURE_PREFIX = "LD_ClosureProp"

# Default bound (cm) for claiming a snapshot row; see pairing law above.
_MATCH_MAX_CM = 50.0

# Paint colours the plan names ("colour" on lane-marking rows) and the
# material instances the editor uses for them are named after.
PAINT_COLOURS = ("white", "yellow")


def _f3(v: float) -> float:
    """Round to 3 decimals (cm resolution) and normalise ``-0.0``."""
    return round(float(v), 3) + 0.0


def _norm_asset_path(value):
    """Normalise an Unreal asset path for comparison.

    The editor reports paths such as ``/Game/X/SM_Y.SM_Y``; the plan stores
    ``/Game/X/SM_Y``.  Both name the same asset, so a trailing
    ``.ObjectName`` suffix that repeats the final path segment is stripped.
    """
    if value is None:
        return None
    text = str(value)
    head, dot, tail = text.rpartition(".")
    if dot and head and tail and tail == head.rsplit("/", 1)[-1]:
        return head
    return text


def _num(row, *names, default=None):
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return default


def _row_id(row):
    return _num(row, "id", "name", default=str(row))


def _coord(row, *names):
    value = _num(row, *names)
    if value is None:
        return 0.0
    return float(value)


def _yaw_diff_paint(a, b):
    """Angular distance (deg) for paint: compare modulo 180, folded at 90.

    A 180-degree flip is the same painted line and must pass.
    """
    d = abs(float(a) - float(b)) % 180.0
    if d > 90.0:
        d = 180.0 - d
    return d


def _yaw_diff_full(a, b):
    """Angular distance (deg) over the full 360-degree circle.

    Signals are directional: a 180-degree flip faces away from the approach
    and must fail, so no fold is applied.
    """
    d = abs(float(a) - float(b)) % 360.0
    if d > 180.0:
        d = 360.0 - d
    return d


def _xy_distance(a_row, b_row):
    return math.hypot(
        _coord(a_row, "x_cm", "centre_x", "x") - _coord(b_row, "x_cm", "centre_x", "x"),
        _coord(a_row, "y_cm", "centre_y", "y") - _coord(b_row, "y_cm", "centre_y", "y"),
    )


def _snapshot_rows(snapshot, key):
    if not isinstance(snapshot, dict):
        raise TypeError("snapshot must be a dressing_snapshot_v1 dict")
    version = snapshot.get("schema_version")
    if version is not None and version != "dressing_snapshot_v1":
        raise ValueError("snapshot schema_version %r is not dressing_snapshot_v1" % version)
    rows = snapshot.get(key) or []
    return list(rows)


def _with_prefix(rows, prefix):
    return [row for row in rows if str(row.get("actor", "")).startswith(prefix)]


def _nearest_unclaimed(planned_row, snapshot_rows, claimed):
    """(index, distance) of the nearest not-yet-claimed snapshot row."""
    best_idx = None
    best_d = None
    for idx, snap in enumerate(snapshot_rows):
        if idx in claimed:
            continue
        d = _xy_distance(planned_row, snap)
        if best_d is None or d < best_d:
            best_d = d
            best_idx = idx
    return best_idx, best_d


def _pair_nearest(planned_rows, snapshot_rows, match_max_cm):
    """Planned rows (sorted id order) each claim the nearest not-yet-claimed
    snapshot row.  Nearest beyond match_max_cm leaves the planned row
    unmatched; snapshot rows nobody claimed stay unmatched too."""
    pairs = []
    claimed = set()
    matched_ids = set()
    for planned_row in sorted(planned_rows, key=lambda r: str(_row_id(r))):
        idx, dist = _nearest_unclaimed(planned_row, snapshot_rows, claimed)
        if idx is None or dist > match_max_cm:
            continue
        claimed.add(idx)
        matched_ids.add(id(planned_row))
        pairs.append((planned_row, snapshot_rows[idx]))
    unmatched_planned = [row for row in planned_rows if id(row) not in matched_ids]
    unmatched_snapshot = [row for idx, row in enumerate(snapshot_rows) if idx not in claimed]
    return pairs, unmatched_planned, unmatched_snapshot


def _material_matches(planned_row, snap_row):
    """Colour/material law: a wrong paint colour fails.

    The plan names the colour (``colour``: "white"/"yellow" on lane-marking
    rows); the snapshot records the material asset the editor assigned
    (``MI_LD_Paint_White`` / ``MI_LD_Paint_Yellow``).  A planned row that
    carries neither ``colour`` nor ``material`` (crosswalk stripes are always
    white and the plan does not say so) is not colour-checked.
    """
    expected_path = planned_row.get("material")
    if expected_path is not None:
        return _norm_asset_path(expected_path) == _norm_asset_path(snap_row.get("material"))
    colour = planned_row.get("colour")
    if colour is None:
        return True
    text = str(snap_row.get("material") or "").lower()
    return str(colour).strip().lower() in text


def _check_dict(label, pairs, unmatched_planned, unmatched_snapshot,
                mismatches, tolerances):
    compared = len(pairs)
    insufficient = compared == 0
    passed = (not unmatched_planned and not unmatched_snapshot
              and not mismatches and not insufficient)
    return {
        "check": label,
        "pass": passed,
        "compared": compared,
        "matched": compared - len(mismatches),
        "mismatches": mismatches,
        "unmatched_planned": [{"id": _row_id(r)} for r in unmatched_planned],
        "unmatched_planned_count": len(unmatched_planned),
        "unmatched_snapshot": [{"actor": r.get("actor")} for r in unmatched_snapshot],
        "unmatched_snapshot_count": len(unmatched_snapshot),
        "insufficient_sample": insufficient,
        "tolerances": tolerances,
    }


def _compare_decals(planned_rows, snapshot, *, xy_tol_cm, yaw_tol_deg,
                    size_tol_cm, match_max_cm, prefix, check_name,
                    expected_size, expected_z_cm=None, z_tol_cm=1.0):
    """Shared marking/crosswalk logic.

    expected_size(row) -> (width_cm, length_cm).  The editor sets
    decal_size = Vector(depth, half_width, half_length), so the paint decal
    must satisfy 2*size_y == width_cm and 2*size_z == length_cm.
    """
    snap_rows = _with_prefix(_snapshot_rows(snapshot, "decals"), prefix)
    pairs, unmatched_planned, unmatched_snapshot = _pair_nearest(
        list(planned_rows or []), snap_rows, match_max_cm
    )
    mismatches = []
    for planned_row, snap_row in pairs:
        reasons = []
        if _xy_distance(planned_row, snap_row) > xy_tol_cm:
            reasons.append("position")
        width_cm, length_cm = expected_size(planned_row)
        if abs(2.0 * float(snap_row.get("size_y") or 0.0) - width_cm) > size_tol_cm:
            reasons.append("size_y")
        if abs(2.0 * float(snap_row.get("size_z") or 0.0) - length_cm) > size_tol_cm:
            reasons.append("size_z")
        if _yaw_diff_paint(_num(planned_row, "yaw", default=0.0),
                           snap_row.get("yaw", 0.0)) > yaw_tol_deg:
            reasons.append("yaw")
        # Height was previously never read, so a marking decal lifted clear of
        # the road passed. The plan does not carry a Z (the editor supplies the
        # projection plane), so the caller states the plane it asked for.
        if expected_z_cm is not None:
            if abs(float(snap_row.get("z") or 0.0) - float(expected_z_cm)) > z_tol_cm:
                reasons.append("z")
        if not _material_matches(planned_row, snap_row):
            reasons.append("material")
        if reasons:
            mismatches.append({
                "id": _row_id(planned_row),
                "actor": snap_row.get("actor"),
                "reasons": reasons,
            })
    return _check_dict(
        check_name, pairs, unmatched_planned, unmatched_snapshot, mismatches,
        {"xy_tol_cm": xy_tol_cm, "yaw_tol_deg": yaw_tol_deg,
         "size_tol_cm": size_tol_cm, "match_max_cm": match_max_cm,
         "expected_z_cm": expected_z_cm, "z_tol_cm": z_tol_cm},
    )


def match_markings(planned, snapshot, *, xy_tol_cm, yaw_tol_deg,
                   size_tol_cm, match_max_cm=_MATCH_MAX_CM,
                   expected_z_cm=None, z_tol_cm=1.0, prefix=MARK_PREFIX):
    """Match planned lane-marking rows (``dressing_v1`` lane_markings) against
    snapshot decals.  For a lane marking 2*size_y == width_cm and
    2*size_z == length_cm."""

    def expected_size(row):
        return (
            float(_num(row, "width_cm", "width", default=0.0)),
            float(_num(row, "length_cm", "length", default=0.0)),
        )

    return _compare_decals(
        planned, snapshot, xy_tol_cm=xy_tol_cm, yaw_tol_deg=yaw_tol_deg,
        size_tol_cm=size_tol_cm, match_max_cm=match_max_cm, prefix=prefix,
        check_name="markings", expected_size=expected_size,
        expected_z_cm=expected_z_cm, z_tol_cm=z_tol_cm,
    )


def match_crosswalks(planned, snapshot, *, xy_tol_cm, yaw_tol_deg,
                     size_tol_cm, match_max_cm=_MATCH_MAX_CM,
                     expected_z_cm=None, z_tol_cm=1.0,
                     prefix=CROSSWALK_PREFIX):
    """Match planned crosswalk-stripe rows (``dressing_v1`` crosswalk_stripes)
    against snapshot decals.  For a crosswalk stripe
    2*size_y == size_across_cm and 2*size_z == size_along_cm."""

    def expected_size(row):
        return (
            float(_num(row, "size_across_cm", "width_cm", default=0.0)),
            float(_num(row, "size_along_cm", "length_cm", default=0.0)),
        )

    return _compare_decals(
        planned, snapshot, xy_tol_cm=xy_tol_cm, yaw_tol_deg=yaw_tol_deg,
        size_tol_cm=size_tol_cm, match_max_cm=match_max_cm, prefix=prefix,
        check_name="crosswalks", expected_size=expected_size,
        expected_z_cm=expected_z_cm, z_tol_cm=z_tol_cm,
    )


def match_props(planned_rows, snapshot, kind_to_mesh, *, xy_tol_cm,
                yaw_tol_deg=None, match_max_cm=_MATCH_MAX_CM, prefix):
    """Match planned signal/tree/prop rows against snapshot instances.

    kind_to_mesh maps a planned row's ``kind`` to the mesh path that row must
    wear, so a signal wearing a tree mesh fails; a planned kind missing from
    the map fails too.  Rows without a ``kind`` (tree_slots) are
    mesh-agnostic -- the editor digest-picks among several street-tree meshes
    -- and are not mesh-compared.  With yaw_tol_deg=None (trees) yaw is not
    compared at all; otherwise (signals, closure props) yaw is compared over
    the full 360 degrees.
    """
    snap_rows = _with_prefix(_snapshot_rows(snapshot, "instances"), prefix)
    pairs, unmatched_planned, unmatched_snapshot = _pair_nearest(
        list(planned_rows or []), snap_rows, match_max_cm
    )
    mismatches = []
    for planned_row, snap_row in pairs:
        reasons = []
        if _xy_distance(planned_row, snap_row) > xy_tol_cm:
            reasons.append("position")
        kind = planned_row.get("kind")
        if kind is not None and kind_to_mesh:
            expected_mesh = kind_to_mesh.get(kind)
            actual_mesh = _norm_asset_path(snap_row.get("mesh"))
            if expected_mesh is None or actual_mesh != _norm_asset_path(expected_mesh):
                reasons.append("mesh")
        if yaw_tol_deg is not None:
            if _yaw_diff_full(_num(planned_row, "yaw", default=0.0),
                              snap_row.get("yaw", 0.0)) > yaw_tol_deg:
                reasons.append("yaw")
        if reasons:
            mismatches.append({
                "id": _row_id(planned_row),
                "actor": snap_row.get("actor"),
                "kind": kind,
                "mesh": snap_row.get("mesh"),
                "reasons": reasons,
            })
    return _check_dict(
        prefix, pairs, unmatched_planned, unmatched_snapshot, mismatches,
        {"xy_tol_cm": xy_tol_cm, "yaw_tol_deg": yaw_tol_deg,
         "match_max_cm": match_max_cm},
    )


def _bounds_min_z(bounds):
    if isinstance(bounds, dict):
        if "min_z" in bounds:
            return float(bounds["min_z"])
        if "min" in bounds:
            return float(bounds["min"])
        if "bounds_min" in bounds:
            return float(bounds["bounds_min"].get("z", 0.0))
        return 0.0
    return float(bounds)


def check_ground_contact(snapshot, *, surface_z_cm, mesh_bounds, tol_cm,
                         buried=None):
    """Assert z + min_z * scale_z == surface_z_cm within tol_cm for every
    snapshot instance (raw float compare -- nothing is rounded away).

    min_z comes from the caller-supplied mesh_bounds map (mesh -> bounds); a
    mesh without bounds fails loudly instead of passing.  A ``buried`` map
    (mesh -> allowed depth in cm, street trees only) shifts the expectation
    downward, so the tree base sits below grade by exactly the allowed depth.
    A missing ``scale_z`` counts as 1.0.
    """
    buried = buried or {}
    mesh_bounds = mesh_bounds or {}
    failures = []
    checked = []
    for row in _snapshot_rows(snapshot, "instances"):
        mesh = str(row.get("mesh") or "")
        key = _norm_asset_path(mesh)
        bounds = mesh_bounds.get(key)
        if bounds is None:
            bounds = mesh_bounds.get(mesh)
        if bounds is None:
            failures.append({
                "actor": row.get("actor"),
                "mesh": mesh,
                "reason": "no_bounds",
            })
            continue
        min_z = _bounds_min_z(bounds)
        scale_z = float(row.get("scale_z") or 1.0)
        actual = float(row.get("z") or 0.0) + min_z * scale_z
        expected = float(surface_z_cm) - float(buried.get(key, buried.get(mesh, 0.0)))
        diff = abs(actual - expected)
        entry = {
            "actor": row.get("actor"),
            "mesh": mesh,
            "z": _f3(row.get("z") or 0.0),
            "scale_z": _f3(scale_z),
            "min_z": _f3(min_z),
            "expected_contact_z_cm": _f3(expected),
            "actual_contact_z_cm": _f3(actual),
            "diff_cm": _f3(diff),
            "pass": diff <= tol_cm,
        }
        checked.append(entry)
        if diff > tol_cm:
            failures.append(entry)
    compared = len(checked)
    insufficient = compared == 0
    passed = not failures and not insufficient
    return {
        "check": "ground_contact",
        "pass": passed,
        "compared": compared,
        "checked": checked,
        "failures": failures,
        "insufficient_sample": insufficient,
        "tolerances": {"surface_z_cm": surface_z_cm, "tol_cm": tol_cm},
    }


def build_report(marking_res, crosswalk_res, prop_results, contact_res, *,
                 tolerances):
    """Aggregate every sub-check into a ``dressing_check_v1`` report.

    prop_results maps a family name ("signals", "trees", "props", ...) to the
    dict returned by match_props for that family.  Tolerances are echoed at
    the top level.  Overall pass requires every sub-check to pass AND every
    category to have compared at least one row (empty is never a pass).
    """
    checks = {
        "markings": marking_res,
        "crosswalks": crosswalk_res,
        "ground_contact": contact_res,
    }
    for name, res in (prop_results or {}).items():
        checks[name] = res
    sub_passes = [bool(res.get("pass", False)) for res in checks.values()]
    sub_insufficient = [
        bool(res.get("insufficient_sample", False)) for res in checks.values()
    ]
    return {
        "schema_version": DRESSING_CHECK_VERSION,
        "pass": bool(all(sub_passes) and not any(sub_insufficient)),
        "insufficient_sample": bool(any(sub_insufficient)),
        "tolerances": dict(tolerances or {}),
        "checks": checks,
    }


def write_report(doc, path) -> Path:
    """Serialise the report as sorted, indented JSON; return the path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    return target
