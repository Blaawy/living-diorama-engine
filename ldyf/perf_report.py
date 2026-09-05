"""Honest performance recording for the Living Diorama (Phase 2).

Why this module exists
----------------------
The *render* path is deterministic.  Output frame ``f`` always presents
simulation instant ``f / fps`` no matter how fast or how slow the renderer
runs, so the renderer's wall-clock speed is a pure *cost* measurement: it says
how long producing the movie takes, never which instant any frame shows.

The *interactive* path is a real frame rate that a human would feel while
driving the simulation live.

Conflating the two is exactly the dishonesty this module exists to prevent: an
earlier report quoted a stale 0.4x figure measured with 16 actors as though it
described a 736-actor world.  Staleness therefore has to be detectable by
code, not by a reader remembering.

Pure standard library only -- no numpy, no ``import unreal``.
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

PERF_REPORT_VERSION = "perf_report_v1"

# Classification scale, stated so nobody has to interpret a bare number:
#   ratio >= 0.95              -> "realtime"
#   ratio >= 0.5               -> "near_realtime"
#   ratio >= 0.2               -> "slow"
#   otherwise                  -> "offline"
_REALTIME_MIN = 0.95
_NEAR_REALTIME_MIN = 0.5
_SLOW_MIN = 0.2

# Interactive frame times shorter than this (seconds) are treated as zero for
# the purposes of "1 / duration" safety (never actually hit with sane data).
_EPS = 1e-12


def _f3(v: float) -> float:
    """Round to 3 decimals and normalise ``-0.0`` to ``0.0``."""
    r = round(float(v), 3)
    return 0.0 if r == 0.0 else r


def _nearest_rank_percentile(sorted_values: list, percentile: float) -> float:
    """Return the ``percentile``-th percentile via the *nearest-rank* method.

    Documented method: with N values sorted ascending, the p-th percentile is
    the value at rank ``r = ceil(p / 100 * N)`` counting from 1, i.e. the
    0-based element ``sorted_values[r - 1]``.  Implemented directly -- numpy is
    never used in this module.
    """
    n = len(sorted_values)
    rank = math.ceil((percentile / 100.0) * n)
    return sorted_values[rank - 1]


def summarise_samples(samples, *, warmup_drop: int) -> dict:
    """Summarise per-frame durations (seconds), dropping warm-up frames.

    The first ``warmup_drop`` samples are discarded before any statistic is
    computed: shader compilation and asset streaming make them meaningless.

    Percentile method: the 95th percentile duration ``p95_s`` is computed with
    the nearest-rank rule (rank ``ceil(0.95 * N)`` of the ascending durations).
    ``fps_p95_low`` is ``1 / p95_s`` -- the frame rate a viewer actually feels
    during the slowest 5% of frames, which is below the mean for a spiky
    series.

    Raises ``ValueError`` for an empty sample list, a negative ``warmup_drop``,
    or a ``warmup_drop`` >= the sample count.  Never returns a summary computed
    from zero samples.
    """
    sample_list = list(samples)
    if not sample_list:
        raise ValueError("summarise_samples: samples list is empty")
    if warmup_drop < 0:
        raise ValueError("summarise_samples: warmup_drop must be >= 0")
    if warmup_drop >= len(sample_list):
        raise ValueError(
            "summarise_samples: warmup_drop (%d) must be smaller than the "
            "sample count (%d)" % (warmup_drop, len(sample_list))
        )
    kept = sample_list[warmup_drop:]
    count = len(kept)
    if count == 0:
        raise ValueError(
            "summarise_samples: no samples remain after warmup_drop"
        )

    mean_s = sum(kept) / count
    median_s = statistics.median(kept)
    sorted_kept = sorted(kept)
    p95_s = _nearest_rank_percentile(sorted_kept, 95)

    def _fps(duration_s: float) -> float:
        return 1.0 / duration_s if duration_s > _EPS else float("inf")

    return {
        "count": count,
        "mean_s": _f3(mean_s),
        "median_s": _f3(median_s),
        "p95_s": _f3(p95_s),
        "min_s": _f3(sorted_kept[0]),
        "max_s": _f3(sorted_kept[-1]),
        "fps_mean": _f3(_fps(mean_s)),
        "fps_median": _f3(_fps(median_s)),
        "fps_p95_low": _f3(_fps(p95_s)),
    }


def realtime_ratio(summary: dict, *, target_fps: float) -> float:
    """Ratio of the felt interactive frame rate to ``target_fps``.

    The honest felt rate is ``fps_p95_low`` (``1 / p95_s``), the frame rate a
    viewer experiences during the slowest 5% of frames -- not the mean rate,
    which a handful of slow frames can pull far away from what is felt.  A
    spiky session whose mean exceeds ``target_fps`` therefore still cannot
    claim "realtime".

    Raises ``ValueError`` when ``target_fps`` is not positive.
    """
    if target_fps <= 0:
        raise ValueError("realtime_ratio: target_fps must be positive")
    felt_fps = summary["fps_p95_low"]
    return felt_fps / target_fps


def classify(ratio: float) -> str:
    """Map a realtime ratio onto a stated scale.

    ``>= 0.95`` -> ``"realtime"``, ``>= 0.5`` -> ``"near_realtime"``,
    ``>= 0.2`` -> ``"slow"``, otherwise ``"offline"``.
    """
    if ratio >= _REALTIME_MIN:
        return "realtime"
    if ratio >= _NEAR_REALTIME_MIN:
        return "near_realtime"
    if ratio >= _SLOW_MIN:
        return "slow"
    return "offline"


def render_cost(
    frames: int, wall_seconds: float, *, fps: float, width: int, height: int
) -> dict:
    """Report how much the deterministic render path *cost* in wall time.

    Returns frames per wall second, seconds per frame and the *presentation*
    duration ``frames / fps``.  The render path is deterministic: output frame
    ``f`` is always presentation second ``f / fps``, so wall-clock speed is a
    cost measurement only.  The returned dict carries ``"authority": "frame"``
    and a plain-words note saying that wall-clock speed cannot change which
    simulation instant a frame shows.

    Raises ``ValueError`` when ``fps``, ``width`` or ``height`` is not
    positive.
    """
    if fps <= 0:
        raise ValueError("render_cost: fps must be positive")
    if width <= 0:
        raise ValueError("render_cost: width must be positive")
    if height <= 0:
        raise ValueError("render_cost: height must be positive")
    if frames <= 0:
        raise ValueError("render_cost: frames must be positive")
    if wall_seconds <= 0:
        raise ValueError("render_cost: wall_seconds must be positive")

    frames_per_wall_second = frames / wall_seconds
    seconds_per_frame = wall_seconds / frames
    presentation_seconds = frames / fps
    note = (
        "Wall-clock render speed is a cost measurement only: output frame f "
        "always presents simulation instant f/fps, so how fast the renderer "
        "runs changes how long producing the movie takes, never which "
        "simulation instant any frame shows."
    )
    return {
        "frames_per_wall_second": _f3(frames_per_wall_second),
        "seconds_per_frame": _f3(seconds_per_frame),
        "presentation_seconds": _f3(presentation_seconds),
        "authority": "frame",
        "note": note,
    }


def build_report(*, interactive: dict, render: dict, world: dict,
                 environment: dict) -> dict:
    """Assemble a full performance report document.

    ``interactive`` is the summary returned by :func:`summarise_samples`.
    ``world`` is the snapshot of the world *as it was while the interactive
    frame rate was measured* and must carry the actor count; ``environment``
    is the measurement environment snapshot and must carry ``measured_utc``
    (the UTC instant the interactive measurement was taken).  The interactive
    block always carries an explicit ``measured_with_actor_count`` and
    ``measured_utc`` so that staleness is detectable by code.

    The caller may instead already have embedded ``measured_with_actor_count``
    / ``measured_utc`` inside ``interactive``; those values win.
    """
    interactive_block = dict(interactive)
    if "measured_with_actor_count" not in interactive_block:
        if "actor_count" not in world:
            raise ValueError(
                "build_report: world must carry 'actor_count' (or embed "
                "'measured_with_actor_count' in interactive)"
            )
        interactive_block["measured_with_actor_count"] = int(
            world["actor_count"]
        )
    if "measured_utc" not in interactive_block:
        if "measured_utc" not in environment:
            raise ValueError(
                "build_report: environment must carry 'measured_utc' (or "
                "embed 'measured_utc' in interactive)"
            )
        interactive_block["measured_utc"] = environment["measured_utc"]

    return {
        "perf_report_version": PERF_REPORT_VERSION,
        "interactive": interactive_block,
        "render": dict(render),
        "world": dict(world),
        "environment": dict(environment),
    }


def write_report(doc: dict, path) -> Path:
    """Write ``doc`` as pretty-printed JSON; returns the ``Path`` written."""
    path = Path(path)
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def is_stale(report: dict, current_actor_count: int, *,
             tolerance_fraction: float) -> bool:
    """True when the world grew beyond tolerance since the measurement.

    Compares the actor count recorded with the interactive measurement
    (``report["interactive"]["measured_with_actor_count"]``) against
    ``current_actor_count``.  Returns True when the relative growth exceeds
    ``tolerance_fraction``; shrinkage or growth inside tolerance is not stale.
    """
    measured = report["interactive"]["measured_with_actor_count"]
    if measured <= 0:
        raise ValueError("is_stale: measured actor count must be positive")
    growth = (current_actor_count - measured) / measured
    return growth > tolerance_fraction
