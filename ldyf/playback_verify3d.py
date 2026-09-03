"""Pure 3-D playback verification (Phase 2 closure lane V; contracts C1/C2/C7).

Compares the editor's *placed* snapshot -- world-space actor transforms plus a
mesh-bounds bottom z measured at one pinned record frame -- against the sealed
record. This module is the pure half of the lane: no `unreal`, no editor
connection. It reads only the sealed record, through the frozen authorities
(`ldyf.sumo_record.read_frame` for frame samples, `ldyf.record_interp.pose_at`
for the half-step interpolation check) and the single angle authority
(`ldyf.coords.normalise_deg`).

Contracts used (docs_CONTRACTS_P2_CLOSURE.md):
  * C1 (the Z law): contact_error_cm = |world_bounds_bottom_z - (record_z +
    surface_z)|. The placed bottom z is the snapshot's mesh-bounds bottom; when
    a bounds read is absent the spawn-measured contact offset
    (bottom = root_z - contact_offset_cm) is the fallback, so a missing bounds
    read never silently drops the Z check.
  * C2: per-frame xy / contact_z / yaw max+mean, missing (expected uid, no
    placed actor) and extra (placed actor, no record sample at that frame)
    lists, an interpolation check at t = frame_time + step/2 against pose_at,
    and a playback_verify3d_v1 report whose tolerances are echoed arguments.
    PASS requires every frame within tolerance with zero missing/extra AND
    every interpolation entry within tolerance.
  * The lane rule layered on C2: compared must be >= min_actors (default 50)
    unless fewer are expected -- compared < min(min_actors, actors_expected)
    is reported as insufficient_sample and fails that frame and the report.

Pure: stdlib + the pure ldyf modules above. Deterministic: every uid list is
sorted before it reaches the report, errors iterate over sorted uids, and
normalise_deg kills -0.0 (round-3 finding 8). No wall clock anywhere.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .coords import normalise_deg
from .record_interp import pose_at
from .sumo_record import read_frame

REPORT_SCHEMA_VERSION = "playback_verify3d_v1"
DEFAULT_MIN_ACTORS = 50
DEFAULT_INTERP_TOL_CM = 1.0
DEFAULT_INTERP_TOL_DEG = 1.0


# --- frame expectations ----------------------------------------------------


def expected_at_frame(
    frames_path: str | Path, manifest: dict, frame: int
) -> dict[str, dict]:
    """uid -> record pose sample {"x","y","z","yaw","speed"} (read_frame semantics).

    Delegates to sumo_record.read_frame (the frozen frame reader: one
    sequential pass; raises IndexError past the end of the record) and keys the
    samples by the namespaced manifest uid. Only actors present IN that frame
    are keyed, so an actor absent at the frame is visible to compare_frame as
    an expected uid with no placed actor.
    """
    out: dict[str, dict] = {}
    for row in read_frame(frames_path, manifest, frame):
        uid = manifest["actors"][row["actor_index"]]["uid"]
        out[uid] = {k: row[k] for k in ("x", "y", "z", "yaw", "speed")}
    return out


# --- per-frame comparison --------------------------------------------------


def _agg(vals: list[float]) -> tuple[float, float]:
    """(max, mean); empty input reports (0.0, 0.0)."""
    if not vals:
        return 0.0, 0.0
    return max(vals), sum(vals) / len(vals)


def _placed_bottom_z(placed: dict, contact_offsets: dict | None) -> float | None:
    """World-space bottom of the placed mesh (cm).

    The snapshot normally carries bottom_z measured from the spawned mesh
    component bounds (C1). When it is absent, the spawn-measured contact offset
    (contact_offsets, keyed by uid, label or mesh path) lets us derive it from
    root_z -- C1: contact_offset_cm = root_z - world_bounds_bottom_z, so
    bottom = root_z - contact_offset_cm. None when neither source exists.
    """
    bz = placed.get("bottom_z")
    if bz is not None:
        return float(bz)
    if not contact_offsets:
        return None
    root = placed.get("root_z")
    if root is None:
        return None
    for key in (placed.get("uid"), placed.get("label"), placed.get("mesh")):
        if key is not None and key in contact_offsets:
            offset = contact_offsets[key]
            if offset is not None:
                return float(root) - float(offset)
    return None


def compare_frame(
    snapshot: dict,
    expected: dict[str, dict],
    *,
    surface_z_cm: float,
    contact_offsets: dict | None = None,
    xy_tol_cm: float,
    z_tol_cm: float,
    yaw_tol_deg: float,
) -> dict:
    """Compare one placed snapshot against the record expectation for a frame.

    Snapshot: {"frame","t","surface_z_cm","actors":[{label,uid,x,y,root_z,
    bottom_z,yaw,present}]}; `expected` is the output of expected_at_frame.
    Returns a schema-C2 frame entry:
      {"frame","t","actors_expected","actors_placed","compared","missing",
       "extra","xy":{"max","mean"},"contact_z":{"max","mean","surface_z_used"},
       "yaw":{"max","mean"},"pass"}
    Only actors present in both sides are compared. Errors per compared actor:
      xy_error_cm       hypot(placed x/y - expected x/y)
      contact_z_error   |placed bottom_z - (record z + surface_z_cm)|   (C1)
      yaw_error_deg     abs(normalise_deg(placed yaw - expected yaw))
    missing = expected uid with no present placed actor; extra = present placed
    actor whose uid has no record sample at this frame. pass is True only when
    every compared actor contributed a Z measurement too (a verifier that
    ignores z is forbidden, C1) and all maxima are within their tolerances.
    """
    placed: dict[str, dict] = {}
    n_placed = 0
    for a in snapshot.get("actors") or ():
        if not a.get("present", False):
            continue
        n_placed += 1
        placed[a["uid"]] = a

    missing = sorted(uid for uid in expected if uid not in placed)
    extra = sorted(
        placed[uid].get("label", uid) for uid in placed if uid not in expected
    )

    compared_uids = sorted(uid for uid in expected if uid in placed)
    compared = len(compared_uids)

    xy_err: list[float] = []
    contact_err: list[float] = []
    yaw_err: list[float] = []
    for uid in compared_uids:
        e = expected[uid]
        p = placed[uid]
        xy_err.append(math.hypot(p["x"] - e["x"], p["y"] - e["y"]))
        yaw_err.append(abs(normalise_deg(p["yaw"] - e["yaw"])))
        bz = _placed_bottom_z(p, contact_offsets)
        if bz is not None:
            contact_err.append(abs(bz - (e["z"] + surface_z_cm)))

    xy_max, xy_mean = _agg(xy_err)
    yaw_max, yaw_mean = _agg(yaw_err)
    cz_max, cz_mean = _agg(contact_err)

    z_verified = compared > 0 and len(contact_err) == compared
    ok = (
        compared > 0
        and not missing
        and not extra
        and z_verified
        and xy_max <= xy_tol_cm
        and cz_max <= z_tol_cm
        and yaw_max <= yaw_tol_deg
    )
    return {
        "frame": snapshot.get("frame"),
        "t": snapshot.get("t"),
        "actors_expected": len(expected),
        "actors_placed": n_placed,
        "compared": compared,
        "missing": missing,
        "extra": extra,
        "xy": {"max": xy_max, "mean": xy_mean},
        "contact_z": {
            "max": cz_max,
            "mean": cz_mean,
            "surface_z_used": float(surface_z_cm),
        },
        "yaw": {"max": yaw_max, "mean": yaw_mean},
        "pass": ok,
    }


# --- interpolation check ---------------------------------------------------


def compare_interpolated(
    snapshot_t: dict,
    frames_path: str | Path,
    manifest: dict,
    *,
    xy_tol_cm: float = DEFAULT_INTERP_TOL_CM,
    yaw_tol_deg: float = DEFAULT_INTERP_TOL_DEG,
) -> dict:
    """Compare a placed half-step snapshot with record_interp.pose_at (C2).

    snapshot_t is the interpolation snapshot {"t": float, "actors": [...]}
    taken at t = frame_time + step/2. For every present actor whose pose_at is
    defined at that t (never extrapolated across an absence), the placed x/y
    and yaw are compared with the interpolated record pose. Returns a schema-C2
    interpolation entry {"t","compared","xy_max","yaw_max","pass"}.
    """
    t = snapshot_t.get("t")
    placed = {
        a["uid"]: a for a in snapshot_t.get("actors") or () if a.get("present", False)
    }
    compared = 0
    xy_max = 0.0
    yaw_max = 0.0
    for uid in sorted(placed):
        exp = pose_at(frames_path, manifest, uid, t)
        if exp is None:
            continue
        p = placed[uid]
        compared += 1
        xy_max = max(xy_max, math.hypot(p["x"] - exp["x"], p["y"] - exp["y"]))
        yaw_max = max(yaw_max, abs(normalise_deg(p["yaw"] - exp["yaw"])))
    ok = compared > 0 and xy_max <= xy_tol_cm and yaw_max <= yaw_tol_deg
    return {"t": t, "compared": compared, "xy_max": xy_max, "yaw_max": yaw_max, "pass": ok}


# --- frame selection -------------------------------------------------------


def choose_frames(
    manifest: dict,
    closure_t_s: float,
    *,
    before_s: float = 50.0,
    after_s: float = 150.0,
) -> list[int]:
    """Frame indices before / around / post the closure time, from the manifest
    clock only -- never assuming a 0.1 s step (record_interp law 1).

    Targets are closure_t_s - before_s, closure_t_s and closure_t_s + after_s;
    each resolves to the NEAREST frame index on the manifest grid
    (i = round((t - t_begin) / step_seconds)), clamped to [0, frame_count-1].
    Duplicates (a record too short to separate two targets) are dropped while
    before/around/post order is kept.
    """
    clock = manifest["clock"]
    n = clock["frame_count"]
    if n <= 0:
        return []
    step = clock["step_seconds"]
    t_begin = clock["t_begin"]
    if step <= 0.0:
        return []

    def nearest(t: float) -> int:
        i = int(round((t - t_begin) / step))
        return min(max(i, 0), n - 1)

    out: list[int] = []
    for target in (closure_t_s - before_s, closure_t_s, closure_t_s + after_s):
        i = nearest(target)
        if i not in out:
            out.append(i)
    return out


# --- report ----------------------------------------------------------------


def build_report(
    frame_results: list[dict],
    interp_results: list[dict],
    *,
    record_sha256: str,
    tolerances: dict,
) -> dict:
    """Assemble a playback_verify3d_v1 report (C2, lane-V additions marked).

    Frame results are the compare_frame entries; interpolation results are the
    compare_interpolated entries. `tolerances` is echoed verbatim under
    "tolerances" and may carry min_actors (default DEFAULT_MIN_ACTORS). Each
    frame whose compared count is below min(min_actors, actors_expected) is
    marked "insufficient_sample": true and fails, and the whole report fails
    (lane-V addition: reported at the frame AND the top level). The report
    passes only when there is at least one frame and one interpolation entry,
    every frame and interpolation entry passes, and nothing is under-sampled.
    """
    min_actors = DEFAULT_MIN_ACTORS
    if isinstance(tolerances, dict):
        min_actors = tolerances.get("min_actors", DEFAULT_MIN_ACTORS)

    frames_out: list[dict] = []
    any_insufficient = False
    for fr in frame_results:
        insufficient = fr["compared"] < min(min_actors, fr["actors_expected"])
        any_insufficient = any_insufficient or insufficient
        entry = dict(fr)
        entry["insufficient_sample"] = insufficient
        entry["pass"] = bool(fr["pass"]) and not insufficient
        frames_out.append(entry)

    interp_out = list(interp_results)
    ok = (
        bool(frames_out)
        and all(bool(f["pass"]) for f in frames_out)
        and bool(interp_out)
        and all(bool(i["pass"]) for i in interp_out)
        and not any_insufficient
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "record_sha256": record_sha256,
        "frames": frames_out,
        "interpolation": interp_out,
        "tolerances": dict(tolerances) if isinstance(tolerances, dict) else {},
        "insufficient_sample": any_insufficient,
        "pass": ok,
    }


def write_report(report: dict, out_path: str | Path) -> Path:
    """Write the report with sorted keys and indent 2; returns the path."""
    p = Path(out_path)
    p.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return p
