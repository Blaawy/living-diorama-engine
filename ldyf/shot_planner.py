"""``shot_plan_v1`` -- aim the Phase 2 preview cameras at what is actually happening.

The Phase 2 preview has five camera shots whose positions were typed as
coordinates; two of them (``intersection``, ``street``) framed mostly empty
asphalt because nobody checked where the traffic actually is. Cameras here are
placed from the RECORD, never from a guess:

* ``hotspot`` -- target is the busiest activity cell inside the shot's own time
  window (``actor_density`` over the record frames between the two sim times);
* ``overview`` -- target is the centroid of ALL activity in the window and the
  camera pulls back until a caller-supplied bounding box
  ``fit_bbox_cm = (width_cm, depth_cm)`` fits the horizontal FOV;
* ``fixed`` -- target is a caller-given ``{"x", "y"}`` (the closure scene whose
  interesting place is known from the sealed rule manifest, not from density).

Determinism laws (same as ``ldyf.dressing`` / ``ldyf.record_interp``): every
float is rounded through ``_f3`` (which also removes ``-0.0``), ties are broken
lexicographically, iteration follows the record's own frame/sample order, and
there is no wall clock, no randomness and no mutable module state. The same
record plus the same request therefore yields byte-identical JSON.

Record time (``ldyf.sumo_record``): frame i sits at ``t(i) = t_begin +
i * step_seconds`` (manifest clock block, sumo_record.py:239), so a sim time
maps to a frame index as ``round((t - t_begin) * fps)``. ``actor_density`` has
no fps parameter, so it derives the record's own rate from
``clock["step_seconds"]``; ``plan_shots`` maps the shots' reported frame range
with its ``fps`` argument (equal to ``1 / step_seconds`` for records written by
``build_record``, i.e. plain ``round(t * fps)`` when the record starts at 0).

Coordinate system (``ldyf.coords``): X = centimetres east, Y = centimetres
south, Z = up, yaw 0 = +X increasing toward +Y. A ``bearing_deg`` is that
Unreal yaw direction FROM the target TO the camera.
"""

from __future__ import annotations

import math
from pathlib import Path

from .sumo_record import COUNT_STRUCT, SAMPLE_STRUCT, read_frame

SHOT_PLAN_SCHEMA_VERSION = "shot_plan_v1"
SHOT_KINDS = ("overview", "hotspot", "fixed")


def _f3(v: float) -> float:
    """Round to 3 decimals and normalise ``-0.0`` to ``0.0`` (dressing.py:79)."""
    r = round(float(v), 3)
    return 0.0 if r == 0.0 else r


def _check_stride(stride: int) -> int:
    if not isinstance(stride, int) or stride < 1:
        raise ValueError(f"stride must be a positive int, got {stride!r}")
    return stride


# --- record walking -------------------------------------------------------


def _record_fps(manifest: dict) -> float:
    """The record's own frame rate: 1 / step_seconds (sumo_record.py:239)."""
    step = manifest["clock"].get("step_seconds")
    if step is None or not step > 0:
        raise ValueError(f"record clock has no usable step_seconds: {step!r}")
    return 1.0 / float(step)


def _time_to_frame(manifest: dict, t_seconds: float, fps: float) -> int:
    """Frame index whose time is t: t(i) = t_begin + i * step_seconds."""
    clock = manifest["clock"]
    t_begin = clock.get("t_begin")
    if t_begin is None:
        raise ValueError("record clock has no t_begin (empty record)")
    return int(round((float(t_seconds) - float(t_begin)) * float(fps)))


def _window_frames(manifest: dict, t_start_s: float, t_end_s: float, fps: float) -> tuple[int, int]:
    """Inclusive frame range for a sim-time window, clamped to the record."""
    clock = manifest["clock"]
    n = int(clock["frame_count"])
    if n <= 0 or clock.get("t_begin") is None:
        raise ValueError(f"record clock has no frames (frame_count={n})")
    i0 = _time_to_frame(manifest, t_start_s, fps)
    i1 = _time_to_frame(manifest, t_end_s, fps)
    return max(0, min(i0, n - 1)), max(0, min(i1, n - 1))


def _walk_window(frames_path, manifest, t_start_s: float, t_end_s: float, *,
                 fps: float, stride: int):
    """Yield (frame_index, actor_index, x, y) for window frames, stride apart.

    Single sequential pass over the binary, mirroring ``record_interp``'s
    reader: it consumes the record's own ``COUNT_STRUCT`` / ``SAMPLE_STRUCT``
    layout and the record's in-frame order (ascending actor index).
    """
    i0, i1 = _window_frames(manifest, t_start_s, t_end_s, fps)
    with Path(frames_path).open("rb") as f:
        frame = 0
        while True:
            raw = f.read(COUNT_STRUCT.size)
            if len(raw) < COUNT_STRUCT.size:
                if frame <= i1:
                    raise IndexError(f"frame {frame} beyond end of record")
                return
            (n,) = COUNT_STRUCT.unpack(raw)
            payload = f.read(n * SAMPLE_STRUCT.size)
            if i0 <= frame <= i1 and (frame - i0) % stride == 0:
                for k in range(n):
                    idx, x, y, _z, _yaw, _speed = SAMPLE_STRUCT.unpack_from(
                        payload, k * SAMPLE_STRUCT.size
                    )
                    yield frame, idx, x, y
            frame += 1
            if frame > i1:
                return


def _activity_centroid(frames_path, manifest, t_start_s: float, t_end_s: float, *,
                       stride: int) -> tuple[float, float] | None:
    """Mean (x, y) over every actor sample in the window, or None when empty."""
    fps = _record_fps(manifest)
    sx = 0.0
    sy = 0.0
    count = 0
    for _fi, _idx, x, y in _walk_window(frames_path, manifest, t_start_s, t_end_s,
                                        fps=fps, stride=stride):
        sx += x
        sy += y
        count += 1
    if count == 0:
        return None
    return (sx / count, sy / count)


def _count_in_view(frames_path, manifest, t_mid_s: float, fps: float,
                   x: float, y: float, radius: float) -> int:
    """Actors within ``radius`` of (x, y) on the single frame nearest t_mid."""
    clock = manifest["clock"]
    n = int(clock["frame_count"])
    if n <= 0 or clock.get("t_begin") is None:
        raise ValueError(f"record clock has no frames (frame_count={n})")
    fi = _time_to_frame(manifest, t_mid_s, fps)
    fi = max(0, min(fi, n - 1))
    r2 = float(radius) ** 2
    samples = read_frame(frames_path, manifest, fi)
    return sum(1 for s in samples if (s["x"] - x) ** 2 + (s["y"] - y) ** 2 <= r2)


# --- density --------------------------------------------------------------


def actor_density(frames_path, manifest, *, t_start_s, t_end_s, cell_cm,
                  kinds=None, stride=1) -> dict:
    """Bin every actor position in [t_start_s, t_end_s] into ``cell_cm`` cells.

    Exact and deterministic: no sampling shortcuts unless the caller passes an
    explicit ``stride`` (then every stride-th frame of the window is walked).
    Cells are anchored at the record origin (0, 0): ``ix = floor(x / cell_cm)``.

    Returns ``{"cells": {(ix, iy): count}, "frames": n, "samples": m,
    "cell_cm": float}``. ``frames`` is the number of window frames walked
    (inclusive, stride apart -- empty frames included, because a frame with
    zero actors is still written and frame index is a pure function of time,
    sumo_record.py:31); ``samples`` counts the actor positions binned.
    ``kinds`` (e.g. ``{"vehicle"}``) filters on the manifest actor kind; None
    bins every actor.
    """
    if not t_end_s > t_start_s:
        raise ValueError(f"t_end_s ({t_end_s}) must be > t_start_s ({t_start_s})")
    if not cell_cm > 0:
        raise ValueError(f"cell_cm must be positive, got {cell_cm!r}")
    stride = _check_stride(stride)
    fps = _record_fps(manifest)
    wanted = set(kinds) if kinds is not None else None
    cells: dict[tuple[int, int], int] = {}
    samples = 0
    for _fi, idx, x, y in _walk_window(frames_path, manifest, t_start_s, t_end_s,
                                       fps=fps, stride=stride):
        if wanted is not None and manifest["actors"][idx]["kind"] not in wanted:
            continue
        ix = math.floor(x / cell_cm)
        iy = math.floor(y / cell_cm)
        cells[(ix, iy)] = cells.get((ix, iy), 0) + 1
        samples += 1
    i0, i1 = _window_frames(manifest, t_start_s, t_end_s, fps)
    frames = (i1 - i0) // stride + 1
    return {"cells": cells, "frames": frames, "samples": samples, "cell_cm": float(cell_cm)}


def busiest_cell(density, *, exclude=()) -> tuple[int, int] | None:
    """Busiest cell; ties broken by the lexicographically smallest (ix, iy).

    ``exclude`` cells are skipped (e.g. cells already aimed at by an earlier
    shot). Returns None when the density is empty or every cell is excluded.
    """
    excluded = set(exclude)
    best = None
    best_key = None
    for cell, count in density["cells"].items():
        if cell in excluded:
            continue
        key = (-count, cell[0], cell[1])
        if best_key is None or key < best_key:
            best_key = key
            best = cell
    return best


def hotspots(density, *, count, min_separation_cells) -> list[dict]:
    """The ``count`` busiest cells at least ``min_separation_cells`` apart.

    Greedy: cells are ranked by (-count, ix, iy) (so ties resolve to the
    lexicographically smallest cell first) and each candidate is kept iff its
    Euclidean distance, in cell units, from every already-kept cell is >=
    ``min_separation_cells``. Fewer than ``count`` are returned when the window
    cannot supply that many separated cells -- never a made-up fallback. Each
    result is ``{"ix", "iy", "count", "x_cm", "y_cm"}`` with the cell centre in
    record centimetres, rounded through ``_f3``.
    """
    if count < 1:
        raise ValueError(f"count must be positive, got {count!r}")
    cell_cm = float(density["cell_cm"])
    ranked = sorted(
        density["cells"].items(),
        key=lambda kv: (-kv[1], kv[0][0], kv[0][1]),
    )
    chosen: list[tuple[int, int]] = []
    for (ix, iy), _c in ranked:
        if len(chosen) >= count:
            break
        if all(math.hypot(ix - jx, iy - jy) >= min_separation_cells for (jx, jy) in chosen):
            chosen.append((ix, iy))
    return [
        {
            "ix": ix,
            "iy": iy,
            "count": density["cells"][(ix, iy)],
            "x_cm": _f3((ix + 0.5) * cell_cm),
            "y_cm": _f3((iy + 0.5) * cell_cm),
        }
        for ix, iy in chosen
    ]


# --- cameras --------------------------------------------------------------


def frame_shot(target_x, target_y, *, distance_cm, height_cm, bearing_deg) -> dict:
    """Camera transform for a camera on ``bearing_deg`` FROM the target.

    ``bearing_deg`` is the Unreal yaw direction from the target to the camera
    (yaw 0 = +X, increasing toward +Y -- the record's convention), so the
    camera sits at

        cam = (target_x + distance_cm * cos b, target_y + distance_cm * sin b,
               height_cm)

    and looks back at the target on the ground (z = 0). Pitch and yaw are both
    computed with ``math.atan2`` only, from the look vector:

        yaw   = degrees(atan2(target_y - cam_y, target_x - cam_x))
        pitch = degrees(atan2(-height_cm, distance_cm))      # looks down

    Returns ``{"location": {"x","y","z"}, "rotation": {"pitch","yaw","roll"}}``;
    every float goes through ``_f3`` and roll is 0.0.
    """
    b = math.radians(bearing_deg)
    cam_x = target_x + distance_cm * math.cos(b)
    cam_y = target_y + distance_cm * math.sin(b)
    yaw = math.degrees(math.atan2(target_y - cam_y, target_x - cam_x))
    pitch = math.degrees(math.atan2(-float(height_cm), float(distance_cm)))
    return {
        "location": {"x": _f3(cam_x), "y": _f3(cam_y), "z": _f3(float(height_cm))},
        "rotation": {"pitch": _f3(pitch), "yaw": _f3(yaw), "roll": 0.0},
    }


# --- the plan -------------------------------------------------------------


def plan_shots(frames_path, manifest, *, fps, shots, cell_cm, fov_deg,
               stride=1, fit_bbox_cm=None, view_radius_cm=None) -> dict:
    """Build the whole ``shot_plan_v1`` document from the record.

    Each request is ``{"name", "kind", "start_s", "end_s", "distance_cm",
    "height_cm", "bearing_deg"}``; a ``fixed`` shot additionally carries the
    target ``"x"`` / ``"y"`` in record centimetres.

    * ``overview`` -- target is the centroid of ALL activity in the window and
      the shot's distance is overridden by the FOV fit: the camera pulls back
      to ``max(width, depth) / 2 / tan(fov_deg / 2)`` so the caller-supplied
      ``fit_bbox_cm = (width_cm, depth_cm)`` fits the horizontal FOV.
    * ``hotspot`` -- target is the busiest cell of the shot's own window
      (``actor_density`` + ``busiest_cell``).
    * ``fixed`` -- target is the request's ``x`` / ``y``.

    Every shot carries its resolved target, its camera transform, the frame
    range ``[start_frame, end_frame]`` (``round((t - t_begin) * fps)``) and
    ``actors_in_view_estimate`` -- actors within the shot's view radius on the
    window's midpoint frame -- so a human can see the shot is not empty. The
    view radius defaults to the camera's horizontal distance from the target
    and can be overridden with ``view_radius_cm``.
    """
    if not fps > 0:
        raise ValueError(f"fps must be positive, got {fps!r}")
    fps = float(fps)
    if not cell_cm > 0:
        raise ValueError(f"cell_cm must be positive, got {cell_cm!r}")
    if not fov_deg > 0:
        raise ValueError(f"fov_deg must be positive, got {fov_deg!r}")
    stride = _check_stride(stride)
    if fit_bbox_cm is not None and (
        len(fit_bbox_cm) != 2 or not fit_bbox_cm[0] > 0 or not fit_bbox_cm[1] > 0
    ):
        raise ValueError(
            f"fit_bbox_cm must be (width_cm, depth_cm) both positive, got {fit_bbox_cm!r}"
        )
    if view_radius_cm is not None and not view_radius_cm > 0:
        raise ValueError(f"view_radius_cm must be positive, got {view_radius_cm!r}")

    rows = []
    for req in shots:
        kind = req["kind"]
        if kind not in SHOT_KINDS:
            raise ValueError(f"unknown shot kind {kind!r} (expected one of {SHOT_KINDS})")
        name = str(req["name"])
        t0 = float(req["start_s"])
        t1 = float(req["end_s"])
        if not t1 > t0:
            raise ValueError(f"shot {name!r}: end_s ({t1}) must be > start_s ({t0})")
        height_cm = float(req["height_cm"])
        bearing_deg = float(req["bearing_deg"])

        if kind == "fixed":
            if "x" not in req or "y" not in req:
                raise ValueError(f"fixed shot {name!r} needs x and y in the request")
            tx, ty = float(req["x"]), float(req["y"])
            distance_cm = float(req["distance_cm"])
        elif kind == "hotspot":
            dens = actor_density(frames_path, manifest, t_start_s=t0, t_end_s=t1,
                                 cell_cm=cell_cm, stride=stride)
            cell = busiest_cell(dens)
            if cell is None:
                raise ValueError(
                    f"hotspot shot {name!r}: no activity in [{t0}, {t1}] to aim at"
                )
            tx = (cell[0] + 0.5) * cell_cm
            ty = (cell[1] + 0.5) * cell_cm
            distance_cm = float(req["distance_cm"])
        else:  # overview
            if fit_bbox_cm is None:
                raise ValueError(
                    f"overview shot {name!r} needs fit_bbox_cm (width_cm, depth_cm)"
                )
            centroid = _activity_centroid(frames_path, manifest, t0, t1, stride=stride)
            if centroid is None:
                raise ValueError(
                    f"overview shot {name!r}: no activity in [{t0}, {t1}] to centre on"
                )
            tx, ty = centroid
            half = max(float(fit_bbox_cm[0]), float(fit_bbox_cm[1])) / 2.0
            distance_cm = half / math.tan(math.radians(fov_deg) / 2.0)

        cam = frame_shot(tx, ty, distance_cm=distance_cm, height_cm=height_cm,
                         bearing_deg=bearing_deg)
        radius = float(view_radius_cm) if view_radius_cm is not None else float(distance_cm)
        rows.append({
            "name": name,
            "kind": kind,
            "start_s": _f3(t0),
            "end_s": _f3(t1),
            "start_frame": _time_to_frame(manifest, t0, fps),
            "end_frame": _time_to_frame(manifest, t1, fps),
            "distance_cm": _f3(distance_cm),
            "height_cm": _f3(height_cm),
            "bearing_deg": _f3(bearing_deg),
            "target": {"x": _f3(tx), "y": _f3(ty)},
            "camera": cam,
            "view_radius_cm": _f3(radius),
            "actors_in_view_estimate": _count_in_view(
                frames_path, manifest, (t0 + t1) / 2.0, fps, tx, ty, radius
            ),
        })

    return {
        "schema_version": SHOT_PLAN_SCHEMA_VERSION,
        "params": {
            "fps": _f3(fps),
            "cell_cm": _f3(cell_cm),
            "fov_deg": _f3(fov_deg),
            "stride": stride,
            "fit_bbox_cm": (
                [_f3(float(fit_bbox_cm[0])), _f3(float(fit_bbox_cm[1]))]
                if fit_bbox_cm is not None else None
            ),
            "view_radius_cm": _f3(float(view_radius_cm)) if view_radius_cm is not None else None,
        },
        "shots": rows,
    }


# --------------------------------------------------------------------------- occlusion

def point_in_polygon(x: float, y: float, poly) -> bool:
    """Even-odd ray cast. ``poly`` is a sequence of ``{"x","y"}`` or ``(x, y)``.

    Points exactly on an edge are not guaranteed either way; that is fine here,
    because the caller uses this to reject camera positions and a camera on a
    building's exact boundary is worth rejecting regardless.
    """
    pts = [(float(p["x"]), float(p["y"])) if isinstance(p, dict) else (float(p[0]), float(p[1]))
           for p in poly]
    n = len(pts)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y):
            t = (y - yi) / (yj - yi) if yj != yi else 0.0
            if x < xi + t * (xj - xi):
                inside = not inside
        j = i
    return inside


def segment_crosses_polygon(ax, ay, bx, by, poly, *, samples: int = 24) -> bool:
    """True if the segment a->b passes through the polygon.

    Sampled rather than analytic: the caller only needs to know whether a
    camera can see its target, and a sampled test with enough points is honest
    about what it is (it can miss a sliver thinner than the sample spacing,
    which is recorded in the shot plan rather than hidden).
    """
    if samples < 2:
        raise ValueError("samples must be >= 2")
    for i in range(samples + 1):
        t = i / samples
        if point_in_polygon(ax + (bx - ax) * t, ay + (by - ay) * t, poly):
            return True
    return False


def choose_bearing(target_x, target_y, *, distance_cm, preferred_deg, obstacles,
                   step_deg: float = 15.0, samples: int = 24):
    """The preferred bearing if the camera can see the target, else the nearest
    bearing that can, searched outward in ``step_deg`` increments.

    Returns ``(bearing_deg, tried, blocked_at_preferred)``. Raises ``ValueError``
    if no bearing in the full circle is clear, rather than returning a blocked
    camera and letting the render show a wall.
    """
    if step_deg <= 0:
        raise ValueError("step_deg must be > 0")
    obstacles = list(obstacles or ())
    tried = []
    n = max(1, int(round(360.0 / step_deg)))
    order = [0.0]
    for k in range(1, n // 2 + 1):
        order += [k * step_deg, -k * step_deg]
    blocked_pref = None
    for delta in order:
        b = (float(preferred_deg) + delta) % 360.0
        rad = math.radians(b)
        cx = float(target_x) + float(distance_cm) * math.cos(rad)
        cy = float(target_y) + float(distance_cm) * math.sin(rad)
        clear = True
        for poly in obstacles:
            if point_in_polygon(cx, cy, poly) or segment_crosses_polygon(
                    cx, cy, float(target_x), float(target_y), poly, samples=samples):
                clear = False
                break
        tried.append({"bearing_deg": _f3(b), "clear": clear})
        if blocked_pref is None:
            blocked_pref = not clear
        if clear:
            return _f3(b), tried, bool(blocked_pref)
    raise ValueError("no unobstructed bearing found around (%s, %s) at %s cm"
                     % (target_x, target_y, distance_cm))
