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

Geometry budgeting
------------------
This pass also ships the geometry the frame rate will be measured on: stepped
building masses with parapets and storefronts, dressing, vehicles, crowd,
instanced trees and a distant skyline.  None of it was previously budgeted, so
this module now also carries :data:`GEOMETRY_BUDGET` -- a triangle cap per
category, a total ceiling and the assumption behind that ceiling -- plus
:func:`estimate_world_cost`, :func:`budget_report` and :func:`validate_budget`,
which turn per-category instance counts into totals and refuse an estimate that
cannot be defended.  The budget is a *gate for what may be shipped*, never a
measurement: measured cost still comes from :func:`render_cost` /
:func:`summarise_samples`, and :func:`is_stale` still guards those measurements
against a world that has grown since they were taken.

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


# ---------------------------------------------------------------------------
# Geometry budget (Phase 2 geometry pass)
# ---------------------------------------------------------------------------
#
# The pass adds per-building stepped masses with parapets, storefronts, signs
# and rooftop props for 252 buildings, ~1816 dressing pieces, 150 parked
# vehicles, 65 people, 240 instanced trees and a ~100-instance distant
# skyline.  None of that was previously budgeted, so this section states the
# triangle cap per category, the ceiling over all categories and the
# assumption the ceiling rests on.
#
# The budget is a shipping gate -- geometry past a line must be justified or
# cut -- never a measurement.  Measured cost still comes from render_cost()
# and summarise_samples() above, and is_stale() still guards those
# measurements against a world that has grown since they were taken.

GEOMETRY_BUDGET_VERSION = "geometry_budget_v1"

# Caps are stated as LOD0 *drawn* triangles per category at full population:
# what the renderer is asked to rasterise each frame.  Instancing is assumed
# for the heavy categories -- trees by design (tree_mesh.py: "240 instanced
# maples ... comfortably inside an ISM budget").
GEOMETRY_BUDGET = {
    "version": GEOMETRY_BUDGET_VERSION,
    # Assumption behind the ceiling: with the heavy categories instanced
    # (ISM/HISM), ~2M drawn triangles per frame keeps the interactive path
    # inside its frame-time target on mid-tier hardware.  The realistic world
    # this pass ships is ~1.01M drawn, roughly half the ceiling: headroom for
    # a pass to grow, not a licence to ignore the per-category lines.  The
    # sum of the per-category caps (1,560,000) sits below the ceiling on
    # purpose, so the ceiling fires only when several categories overrun
    # their lines at once.
    "ceiling_triangles": 2_000_000,
    "ceiling_assumption": (
        "Every category is instanced (trees by design, tree_mesh.py), so the "
        "count that matters is LOD0 drawn triangles per frame.  ~2M drawn "
        "triangles per frame is a defensible ceiling for an interactive 60 "
        "fps target on mid-tier hardware once the heavy categories run "
        "instanced; the world this pass ships is ~1.01M, about half of that "
        "ceiling."
    ),
    "categories": {
        # 252 stepped masses with parapets, storefronts, signs and rooftop
        # props at ~800 tris per building -> 201,600 drawn.
        "buildings": {
            "budget_triangles": 250_000,
            "note": (
                "252 stepped masses with parapets, storefronts, signs and "
                "rooftop props; ~800 tris/building is the pass target."
            ),
        },
        # 240 instanced trees; worst-case maple = 488 tris each (80 trunk +
        # 6*48 branches + 2*60 cards, tree_mesh.py budget table) -> 117,120.
        "trees": {
            "budget_triangles": 200_000,
            "note": (
                "240 instanced trees; worst-case maple 488 tris each "
                "(tree_mesh.py triangle budget)."
            ),
        },
        # Distant skyline: backdrop_massing silhouette towers on concentric
        # rings (backdrop.py), one closed 6-face box (12 tris) per tower.
        "backdrop": {
            "budget_triangles": 10_000,
            "note": (
                "~100 low-detail silhouette massing towers (backdrop.py); "
                "one closed 6-face box, 12 tris, per tower."
            ),
        },
        # 1816 street props at ~150 tris each -> 272,400.  Authored City
        # Sample props run 2.5k-5k tris each (dressing_assets.py) and are
        # refused at this count; purpose-built cheap props are the line.
        "dressing": {
            "budget_triangles": 400_000,
            "note": (
                "1816 street props at ~150 tris each; authored kits of "
                "2.5k-5k tris/prop are refused (dressing_assets.py note)."
            ),
        },
        # 150 parked vehicles, single-body LOD0 at ~1500 tris -> 225,000.
        "vehicles": {
            "budget_triangles": 400_000,
            "note": (
                "150 vehicles at ~1500 tris each (body only, no interior "
                "detail)."
            ),
        },
        # 65 people at ~3000 tris each -> 195,000.  crowd_spec.py is sized
        # so that 65 people do not visibly repeat.
        "crowd": {
            "budget_triangles": 300_000,
            "note": (
                "65 people at ~3000 tris each (crowd_spec.py palette is "
                "sized so 65 people do not visibly repeat)."
            ),
        },
    },
}


def estimate_world_cost(counts: dict) -> dict:
    """Total drawn triangles for the world described by ``counts``.

    ``counts`` maps a category name to ``{"instances": int,
    "triangles_per_instance": int}``.  Pure arithmetic only, no guessing:
    per-category ``triangles = instances * triangles_per_instance``, plus the
    grand total, each category's share of the grand total, and the
    ``over_budget`` list naming any category whose total exceeds its
    ``GEOMETRY_BUDGET`` line.  Validation is deliberately not here -- that is
    :func:`validate_budget`'s job -- so a caller can see the arithmetic even
    when it fails validation.  The raw inputs are copied into the result so
    :func:`validate_budget` can refuse negative or non-integer counts.
    """
    categories = {}
    grand_total = 0
    for name in sorted(counts):
        entry = counts[name]
        instances = entry["instances"]
        per_instance = entry["triangles_per_instance"]
        tris = instances * per_instance
        grand_total += tris
        categories[name] = {
            "instances": instances,
            "triangles_per_instance": per_instance,
            "triangles": tris,
        }
    over_budget = []
    for name, cat in categories.items():
        line = GEOMETRY_BUDGET["categories"].get(name)
        if line is not None and cat["triangles"] > line["budget_triangles"]:
            over_budget.append(name)
    for name, cat in categories.items():
        cat["share"] = (cat["triangles"] / grand_total) if grand_total else 0.0
        line = GEOMETRY_BUDGET["categories"].get(name)
        cat["budget_triangles"] = (
            line["budget_triangles"] if line is not None else None
        )
    return {
        "budget_version": GEOMETRY_BUDGET_VERSION,
        "categories": categories,
        "grand_total_triangles": grand_total,
        "ceiling_triangles": GEOMETRY_BUDGET["ceiling_triangles"],
        "over_budget": over_budget,
    }


def budget_report(estimate: dict) -> str:
    """Short human-readable table of the estimate.

    One row per category (instances, triangles per instance, total triangles,
    budget line, share of the grand total, status) plus a grand-total row
    against the ceiling and the over-budget list -- readable in a review
    report without opening JSON.
    """
    rows = []
    for name in sorted(estimate["categories"]):
        cat = estimate["categories"][name]
        if cat["budget_triangles"] is None:
            budget = "none"
            status = "UNBUDGETED"
        else:
            budget = format(cat["budget_triangles"], ",")
            status = "OVER" if name in estimate["over_budget"] else "ok"
        rows.append(
            "  %-10s %10d %10d %12s %12s %7.1f%%  %s" % (
                name,
                cat["instances"],
                cat["triangles_per_instance"],
                format(cat["triangles"], ","),
                budget,
                cat["share"] * 100.0,
                status,
            )
        )
    total = estimate["grand_total_triangles"]
    ceiling = estimate["ceiling_triangles"]
    if ceiling:
        ceiling_status = (
            "OVER CEILING" if total > ceiling else "ok"
        )
        summary = (
            "  grand total %s of ceiling %s (%5.1f%%)  -- %s" % (
                format(total, ","), format(ceiling, ","),
                (total / ceiling) * 100.0, ceiling_status,
            )
        )
    else:
        summary = "  grand total %s (no ceiling set)  -- ok" % format(total, ",")
    return "\n".join([
        "GEOMETRY BUDGET (%s)" % estimate["budget_version"],
        "  category     instances  tris/inst   triangles     budget  "
        "   share  status",
    ] + rows + [
        summary,
        "  over budget: %s" % (", ".join(estimate["over_budget"]) or "none"),
    ])


def validate_budget(estimate: dict) -> list:
    """Problems with ``estimate``; an empty list means the world is valid.

    Refuses, each reported as one string in the returned list:

    * any budgeted category whose total exceeds its ``GEOMETRY_BUDGET`` line;
    * a grand total over the ceiling;
    * a negative or non-integer instance or per-instance count; and
    * a category present in the counts but absent from ``GEOMETRY_BUDGET`` --
      an unbudgeted category is how a world silently gets heavy.
    """
    problems = []
    for name in sorted(estimate["categories"]):
        cat = estimate["categories"][name]
        instances = cat["instances"]
        per_instance = cat["triangles_per_instance"]
        for label, value in (("instance count", instances),
                             ("triangles per instance", per_instance)):
            if isinstance(value, bool) or not isinstance(value, int):
                problems.append(
                    "category %r: %s must be an integer, got %r"
                    % (name, label, value)
                )
            elif value < 0:
                problems.append(
                    "category %r: %s must not be negative, got %r"
                    % (name, label, value)
                )
        if name not in GEOMETRY_BUDGET["categories"]:
            problems.append(
                "category %r is not in GEOMETRY_BUDGET; add a budget line "
                "for it or remove it from the world" % (name,)
            )
            continue
        line = GEOMETRY_BUDGET["categories"][name]["budget_triangles"]
        if cat["triangles"] > line:
            problems.append(
                "category %r is over budget: %d triangles > %d"
                % (name, cat["triangles"], line)
            )
    if estimate["grand_total_triangles"] > estimate["ceiling_triangles"]:
        problems.append(
            "grand total %d triangles exceeds the ceiling of %d"
            % (estimate["grand_total_triangles"],
               estimate["ceiling_triangles"])
        )
    return problems
