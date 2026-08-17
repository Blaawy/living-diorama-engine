"""The Phase 16 spatial validity contract: occupancy, clearance, refusal.

Pure Python by design -- no ``bpy``. Every production placement must know
what space is already unavailable BEFORE any geometry exists. This module
owns that knowledge: a small set of exact 2D shapes (circles, capsules,
oriented rectangles), a single :class:`PlacementValidator` holding every
occupied envelope by category, and an explicit policy table saying which
overlaps are forbidden and by how much clearance.

The planning order is the urban-planning order: locked history and water
first, then the street network, then junctions, then plazas, then building
lots, then vegetation -- each layer registered as it is accepted, so the
next layer cannot claim the same space. A candidate that conflicts is
REFUSED with a diagnosable reason (candidate id, its category, the
conflicting entry, the required clearance), never silently skipped and
never silently placed.

Founding history includes the Phase 15 vegetation: its cluster positions
are re-derived here by running the exact locked Phase 15 sampling
algorithm (same seed, same draw order), so the pure plan knows precisely
where every founding tree stands without Blender.
"""

import copy
import json
import math

from production_spec import FOUNDING_RING_FACTOR
from road_graph import ROAD_CLASS_WIDTHS
from scene_spec import stable_rng

CATEGORIES = (
    "ROAD",
    "JUNCTION",
    "PAVING",
    "BUILDING",
    "VEGETATION",
    "PLAZA",
    "WALL",
    "HISTORY",
    "PLATE",
    "GROVE",
    "WATER",
)

POLICY: dict[str, dict[str, float | None]] = {
    "BUILDING": {
        "ROAD": 0.4,
        "JUNCTION": 0.3,
        "PAVING": None,
        "BUILDING": 0.5,
        "VEGETATION": 0.5,
        "PLAZA": 0.3,
        "WALL": 1.5,
        "HISTORY": 0.5,
        "PLATE": 0.5,
        "GROVE": 0.5,
        "WATER": 0.0,
    },
    "VEGETATION": {
        "ROAD": 0.3,
        "JUNCTION": 0.3,
        "PAVING": 0.2,
        "BUILDING": 0.6,
        "VEGETATION": None,
        "PLAZA": 0.0,
        "WALL": 1.0,
        "HISTORY": 0.4,
        "PLATE": None,
        "GROVE": None,
        "WATER": 0.0,
    },
    "PLAZA": {
        "ROAD": 0.3,
        "JUNCTION": 0.2,
        "PAVING": None,
        "BUILDING": 0.3,
        "VEGETATION": 0.3,
        "PLAZA": 1.0,
        "WALL": 1.5,
        "HISTORY": 0.5,
        "PLATE": 0.5,
        "GROVE": 0.3,
        "WATER": 0.0,
    },
    "PAVING": {
        "ROAD": None,
        "JUNCTION": None,
        "PAVING": None,
        "BUILDING": None,
        "VEGETATION": 0.0,
        "PLAZA": None,
        "WALL": 0.5,
        "HISTORY": 0.2,
        "PLATE": None,
        "GROVE": 0.2,
        "WATER": 0.0,
    },
}
"""Required clearance when a candidate category meets an existing category.

``None`` means the overlap is allowed (paving may meet paving; park
canopies may merge; designed planting may stand ON a founding plate,
which is why PLATE ground is its own category distinct from the HISTORY
objects that stand on it). A number is the minimum open gap between
envelopes: anything closer is a refusal. Policies exist only for
categories that are actually PLACED by the production planner; roads,
junctions, walls, history, plates, preserved groves, and water are
registered as fixed truth, never as candidates.

Plate GROUND being open is only safe because the ARCHITECTURE standing on
it is registered as HISTORY in its own right
(:func:`founding_building_lots`). Without that, a tree allowed onto a
plate could grow through a founding building with nothing able to detect
it.
"""

PRIORITY_CLASSES = {
    "A": ("WALL", "HISTORY", "WATER", "PLATE"),
    "B": ("ROAD", "JUNCTION", "PLAZA", "GROVE"),
    "C": ("BUILDING", "PAVING"),
    "D": ("VEGETATION",),
}
"""The obstacle priority model of the aesthetic-first redesign.

Class A is immutable semantic history: the scar wall lines, the founding
plates and their architecture, the Golden Seal, the harbor. The planner
designs AROUND these; the validator refuses anything that touches them.

Class B is chosen city structure: the designed streets and junctions, the
plazas, and the founding groves the landscape plan explicitly preserves
as parks. Class B is never deformed by lower classes -- a tree never
bends a road.

Class C is flexible architecture: production lots slide along their
frontage ladder or shrink before they may ever displace Class B.

Class D is decoration: production vegetation is planted LAST into ground
the city has finished claiming, and founding vegetation outside the
preserved park zones is cleared by the plan rather than routed around.

The planner enforces this hierarchy by ORDER (A registered, B designed
and registered, C laddered, D planted last); the validator enforces the
physics regardless of who claims otherwise.
"""


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------


def circle(x: float, y: float, radius: float) -> dict:
    """A disc envelope."""
    return {"kind": "circle", "x": float(x), "y": float(y), "r": float(radius)}


def capsule(ax: float, ay: float, bx: float, by: float, radius: float) -> dict:
    """A buffered segment envelope (roads, walls, lanes)."""
    return {
        "kind": "capsule",
        "ax": float(ax),
        "ay": float(ay),
        "bx": float(bx),
        "by": float(by),
        "r": float(radius),
    }


def rect(x: float, y: float, half_w: float, half_d: float, rotation: float) -> dict:
    """An oriented rectangle envelope (building footprints, water, quays)."""
    return {
        "kind": "rect",
        "x": float(x),
        "y": float(y),
        "hw": float(half_w),
        "hd": float(half_d),
        "rot": float(rotation),
    }


def polyline_capsules(path: list[tuple[float, float]], radius: float) -> list[dict]:
    """One capsule per leg of a polyline."""
    return [
        capsule(ax, ay, bx, by, radius)
        for (ax, ay), (bx, by) in zip(path, path[1:], strict=False)
        if math.hypot(bx - ax, by - ay) > 1.0e-9
    ]


def _segment_distance(
    ax: float, ay: float, bx: float, by: float, cx: float, cy: float, dx: float, dy: float
) -> float:
    """Minimum distance between two segments (0 when they cross)."""
    ux, uy = bx - ax, by - ay
    vx, vy = dx - cx, dy - cy
    denominator = ux * vy - uy * vx
    if abs(denominator) > 1.0e-12:
        t = ((cx - ax) * vy - (cy - ay) * vx) / denominator
        s = ((cx - ax) * uy - (cy - ay) * ux) / denominator
        if 0.0 <= t <= 1.0 and 0.0 <= s <= 1.0:
            return 0.0
    return min(
        _point_segment(ax, ay, cx, cy, dx, dy),
        _point_segment(bx, by, cx, cy, dx, dy),
        _point_segment(cx, cy, ax, ay, bx, by),
        _point_segment(dx, dy, ax, ay, bx, by),
    )


def _point_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Distance from a point to a segment."""
    ux, uy = bx - ax, by - ay
    length_squared = ux * ux + uy * uy
    if length_squared == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * ux + (py - ay) * uy) / length_squared))
    return math.hypot(px - (ax + ux * t), py - (ay + uy * t))


def _rect_corners(shape: dict) -> list[tuple[float, float]]:
    """World-space corners of an oriented rectangle."""
    cos_r, sin_r = math.cos(shape["rot"]), math.sin(shape["rot"])
    corners = []
    for sx, sy in ((1, 1), (1, -1), (-1, -1), (-1, 1)):
        lx, ly = sx * shape["hw"], sy * shape["hd"]
        corners.append((shape["x"] + lx * cos_r - ly * sin_r, shape["y"] + lx * sin_r + ly * cos_r))
    return corners


def _to_rect_frame(shape: dict, px: float, py: float) -> tuple[float, float]:
    """A world point expressed in a rectangle's local frame."""
    cos_r, sin_r = math.cos(shape["rot"]), math.sin(shape["rot"])
    dx, dy = px - shape["x"], py - shape["y"]
    return (dx * cos_r + dy * sin_r, -dx * sin_r + dy * cos_r)


def _rect_point_distance(shape: dict, px: float, py: float) -> float:
    """Distance from a rectangle's boundary region to a point (0 inside)."""
    lx, ly = _to_rect_frame(shape, px, py)
    gap_x = max(0.0, abs(lx) - shape["hw"])
    gap_y = max(0.0, abs(ly) - shape["hd"])
    return math.hypot(gap_x, gap_y)


def _rect_segment_distance(shape: dict, ax: float, ay: float, bx: float, by: float) -> float:
    """Distance from a rectangle to a segment (0 on touch or crossing)."""
    la = _to_rect_frame(shape, ax, ay)
    lb = _to_rect_frame(shape, bx, by)
    if abs(la[0]) <= shape["hw"] and abs(la[1]) <= shape["hd"]:
        return 0.0
    if abs(lb[0]) <= shape["hw"] and abs(lb[1]) <= shape["hd"]:
        return 0.0
    hw, hd = shape["hw"], shape["hd"]
    edges = (
        (-hw, -hd, hw, -hd),
        (hw, -hd, hw, hd),
        (hw, hd, -hw, hd),
        (-hw, hd, -hw, -hd),
    )
    best = math.inf
    for ex0, ey0, ex1, ey1 in edges:
        best = min(
            best,
            _segment_distance(la[0], la[1], lb[0], lb[1], ex0, ey0, ex1, ey1),
        )
    return best


def _rect_rect_gap(first: dict, second: dict) -> float:
    """Separation between two oriented rectangles (0 when overlapping).

    Separating-axis theorem on the four face axes gives the maximum
    separation; when every axis overlaps the rectangles intersect.
    """
    best_gap = -math.inf
    for shape in (first, second):
        cos_r, sin_r = math.cos(shape["rot"]), math.sin(shape["rot"])
        for axis in ((cos_r, sin_r), (-sin_r, cos_r)):
            first_proj = _project_rect(first, axis)
            second_proj = _project_rect(second, axis)
            gap = max(second_proj[0] - first_proj[1], first_proj[0] - second_proj[1])
            best_gap = max(best_gap, gap)
    return max(0.0, best_gap)


def _project_rect(shape: dict, axis: tuple[float, float]) -> tuple[float, float]:
    """Min/max projection of a rectangle onto an axis."""
    center = shape["x"] * axis[0] + shape["y"] * axis[1]
    cos_r, sin_r = math.cos(shape["rot"]), math.sin(shape["rot"])
    extent = abs(shape["hw"] * (cos_r * axis[0] + sin_r * axis[1])) + abs(
        shape["hd"] * (-sin_r * axis[0] + cos_r * axis[1])
    )
    return (center - extent, center + extent)


def shape_gap(first: dict, second: dict) -> float:
    """Open gap between two envelopes; 0.0 means they touch or overlap."""
    kinds = (first["kind"], second["kind"])
    if kinds == ("circle", "circle"):
        gap = (
            math.hypot(first["x"] - second["x"], first["y"] - second["y"])
            - first["r"]
            - second["r"]
        )
        return max(0.0, gap)
    if kinds == ("circle", "capsule"):
        gap = (
            _point_segment(
                first["x"], first["y"], second["ax"], second["ay"], second["bx"], second["by"]
            )
            - first["r"]
            - second["r"]
        )
        return max(0.0, gap)
    if kinds == ("capsule", "circle"):
        return shape_gap(second, first)
    if kinds == ("capsule", "capsule"):
        gap = (
            _segment_distance(
                first["ax"],
                first["ay"],
                first["bx"],
                first["by"],
                second["ax"],
                second["ay"],
                second["bx"],
                second["by"],
            )
            - first["r"]
            - second["r"]
        )
        return max(0.0, gap)
    if kinds == ("rect", "circle"):
        return max(0.0, _rect_point_distance(first, second["x"], second["y"]) - second["r"])
    if kinds == ("circle", "rect"):
        return shape_gap(second, first)
    if kinds == ("rect", "capsule"):
        gap = (
            _rect_segment_distance(first, second["ax"], second["ay"], second["bx"], second["by"])
            - second["r"]
        )
        return max(0.0, gap)
    if kinds == ("capsule", "rect"):
        return shape_gap(second, first)
    if kinds == ("rect", "rect"):
        return _rect_rect_gap(first, second)
    raise ValueError(f"unsupported shape pair: {kinds}")


def signed_gap(shape: dict, envelope: dict) -> float:
    """Clearance from a rectangle to an envelope, NEGATIVE when it overlaps.

    :func:`shape_gap` clamps at zero because the placement policy only ever
    asks whether a required gap is met, and a refusal is a refusal however
    deep. A clearance REPORT needs the sign: without it, a slab resting
    against a junction pad and a slab buried half a metre into one are the
    same number, and the check that tells them apart has to be a positive
    margin -- which condemns the innocent one. Supports the rectangle
    against a capsule or a circle, which is every driveable surface.
    """
    if envelope["kind"] == "capsule":
        distance = _rect_segment_distance(
            shape, envelope["ax"], envelope["ay"], envelope["bx"], envelope["by"]
        )
    elif envelope["kind"] == "circle":
        distance = _rect_point_distance(shape, envelope["x"], envelope["y"])
    else:
        raise ValueError(f"unsupported envelope kind {envelope['kind']!r}")
    return distance - envelope["r"]


def convex_polygons_intersect(
    first: list[tuple[float, float]], second: list[tuple[float, float]]
) -> bool:
    """True when two convex polygons share any area (touching counts).

    Separating-axis theorem over both polygons' edge normals. The drawn
    road surfaces are strips and wedges rather than the oriented
    rectangles the placement contract works in, and a face either lies
    over a building or it does not -- there is no clearance to measure,
    so this answers the only question a mesh trim asks.
    """
    for polygon in (first, second):
        count = len(polygon)
        for index in range(count):
            x0, y0 = polygon[index]
            x1, y1 = polygon[(index + 1) % count]
            axis = (-(y1 - y0), x1 - x0)
            if abs(axis[0]) < 1.0e-12 and abs(axis[1]) < 1.0e-12:
                continue
            first_lo = min(x * axis[0] + y * axis[1] for x, y in first)
            first_hi = max(x * axis[0] + y * axis[1] for x, y in first)
            second_lo = min(x * axis[0] + y * axis[1] for x, y in second)
            second_hi = max(x * axis[0] + y * axis[1] for x, y in second)
            if first_hi < second_lo or second_hi < first_lo:
                return False
    return True


def _shape_bounds(shape: dict) -> tuple[float, float, float, float]:
    """A loose AABB for fast rejection."""
    if shape["kind"] == "circle":
        return (
            shape["x"] - shape["r"],
            shape["y"] - shape["r"],
            shape["x"] + shape["r"],
            shape["y"] + shape["r"],
        )
    if shape["kind"] == "capsule":
        return (
            min(shape["ax"], shape["bx"]) - shape["r"],
            min(shape["ay"], shape["by"]) - shape["r"],
            max(shape["ax"], shape["bx"]) + shape["r"],
            max(shape["ay"], shape["by"]) + shape["r"],
        )
    reach = math.hypot(shape["hw"], shape["hd"])
    return (shape["x"] - reach, shape["y"] - reach, shape["x"] + reach, shape["y"] + reach)


# ---------------------------------------------------------------------------
# The validator
# ---------------------------------------------------------------------------


class PlacementValidator:
    """Every occupied envelope, by category, with explicit overlap policy.

    Fixed truth (roads, junctions, walls, history, water) is registered
    first; candidates are then checked -- and, if clean, placed -- in the
    urban-planning order. Refusals are recorded with their reasons so the
    generation run is diagnosable, never silent.
    """

    def __init__(self) -> None:
        """Start empty, with empty diagnostics."""
        self.entries: list[dict] = []
        self.rejections: list[dict] = []

    def register(self, entry_id: str, category: str, shapes: list[dict]) -> None:
        """Record fixed or accepted occupancy (no policy check)."""
        if category not in CATEGORIES:
            raise ValueError(f"unknown occupancy category {category!r}")
        for shape in shapes:
            self.entries.append(
                {
                    "id": entry_id,
                    "category": category,
                    "shape": shape,
                    "bounds": _shape_bounds(shape),
                }
            )

    def conflicts(self, category: str, shapes: list[dict], *, ignore: str = "") -> list[dict]:
        """Every policy violation a candidate would commit, with reasons."""
        policy = POLICY.get(category)
        if policy is None:
            raise ValueError(f"category {category!r} is fixed truth, never a candidate")
        found: list[dict] = []
        for shape in shapes:
            bounds = _shape_bounds(shape)
            for entry in self.entries:
                if ignore and entry["id"] == ignore:
                    continue
                clearance = policy.get(entry["category"])
                if clearance is None:
                    continue
                other_bounds = entry["bounds"]
                if (
                    bounds[0] > other_bounds[2] + clearance
                    or bounds[2] < other_bounds[0] - clearance
                    or bounds[1] > other_bounds[3] + clearance
                    or bounds[3] < other_bounds[1] - clearance
                ):
                    continue
                gap = shape_gap(shape, entry["shape"])
                if gap < clearance or (clearance == 0.0 and gap <= 0.0):
                    found.append(
                        {
                            "conflict_with": entry["id"],
                            "their_category": entry["category"],
                            "required_clearance": clearance,
                            "gap": round(gap, 4),
                        }
                    )
        return found

    def place(self, entry_id: str, category: str, shapes: list[dict]) -> list[dict]:
        """Check a candidate; register it when clean, record refusal when not.

        Returns the conflict list (empty means the candidate now occupies
        its space).

        An id may be PLACED only once. ``conflicts`` deliberately exempts a
        candidate's own id so an entry can be re-audited against everything
        else, and that exemption is only safe while ids are unique: a second
        placement under a live id would be checked against every obstacle
        EXCEPT its namesake, so two objects could occupy the same ground and
        the audit would report nothing. That is refused loudly here rather
        than left to hide.

        Raises:
            ValueError: If ``entry_id`` is already registered.
        """
        if any(entry["id"] == entry_id for entry in self.entries):
            raise ValueError(
                f"placement id {entry_id!r} is already registered; placement ids must be "
                "unique or the self-exemption in conflicts() would mask a real overlap"
            )
        found = self.conflicts(category, shapes, ignore=entry_id)
        if found:
            self.rejections.append(
                {
                    "candidate": entry_id,
                    "category": category,
                    "conflicts": found[:4],
                }
            )
            return found
        self.register(entry_id, category, shapes)
        return []

    def audit(self, entry_id: str, category: str, shapes: list[dict]) -> list[dict]:
        """Re-check an already-placed entry against everything else."""
        return self.conflicts(category, shapes, ignore=entry_id)

    def rejection_summary(self) -> dict:
        """Refusal counts by (candidate category, conflicting category)."""
        summary: dict[str, int] = {}
        for rejection in self.rejections:
            for conflict in rejection["conflicts"]:
                key = f"{rejection['category'].lower()}-{conflict['their_category'].lower()}"
                summary[key] = summary.get(key, 0) + 1
        return dict(sorted(summary.items()))


# ---------------------------------------------------------------------------
# Locked Phase 15 truth, re-derived purely
# ---------------------------------------------------------------------------


def _distance_to_polyline(x: float, y: float, path: list[tuple[float, float]]) -> float:
    """Shortest distance from a point to a polyline (Phase 15 semantics)."""
    best = math.inf
    for (x0, y0), (x1, y1) in zip(path, path[1:], strict=False):
        best = min(best, _point_segment(x, y, x0, y0, x1, y1))
    return best


def founding_tree_clusters(master_spec: dict) -> list[tuple[float, float]]:
    """The EXACT founding vegetation cluster positions, without Blender.

    This replays the locked Phase 15 sampling algorithm draw for draw:
    the same seed identity, the same two uniform draws per attempt, the
    same rejection rules in the same order. The Phase 15 build consumes
    randomness only at the top of each attempt, so the accepted positions
    are bit-identical to the ones standing in the master scene.
    """
    seed = master_spec["visual_seed"]
    rng = stable_rng(seed, "vegetation")
    platform_radius = master_spec["world"]["platform_radius"]
    port = next(
        (entry for entry in master_spec["districts"].values() if entry["character"] == "port"),
        None,
    )
    clusters: list[tuple[float, float]] = []
    attempts = 0
    while len(clusters) < 40 and attempts < 500:
        attempts += 1
        angle = rng.uniform(0.0, 2.0 * math.pi)
        distance = math.sqrt(rng.uniform(0.05, 0.92)) * (platform_radius - 10.0)
        x, y = distance * math.cos(angle), distance * math.sin(angle)
        rejected = False
        for district in master_spec["districts"].values():
            if (
                math.hypot(x - district["center"][0], y - district["center"][1])
                < district["radius"] + 4.0
            ):
                rejected = True
                break
        if not rejected and port is not None:
            center_x, center_y = port["center"]
            length = math.hypot(center_x, center_y) or 1.0
            quay = port["radius"] + 6.0
            along = (x - center_x) * center_x / length + (y - center_y) * center_y / length
            if along > quay:
                rejected = True
        if not rejected:
            for boundary in master_spec["boundaries"].values():
                if _distance_to_polyline(x, y, [tuple(p) for p in boundary["path"]]) < 8.0:
                    rejected = True
                    break
                station = boundary["wall_station"]
                if math.hypot(x - station["center"][0], y - station["center"][1]) < 14.0:
                    rejected = True
                    break
        if rejected:
            continue
        clusters.append((x, y))
    return clusters


FOUNDING_TREE_ENVELOPE = 5.8
"""Conservative radius of one founding cluster: tree offsets reach 3.4 and
the widest wobbled canopy another 2.31; 5.8 covers every real branch."""

ICOSPHERE_VERTS = 42
"""Vertex count of ``bmesh.ops.create_icosphere(subdivisions=2)``.

The locked Phase 15 vegetation builder draws one wobble per canopy vertex
from the cluster's own generator, so replaying a cluster exactly requires
burning precisely this many draws per tree. The Blender structural suite
pins the replica against the real meshes, so a drift here cannot hide.
"""

CANOPY_WOBBLE_FACTOR = 1.16
"""Worst-case horizontal canopy scale in the locked builder: the 1.06
stretch times the widest +9% wobble."""

TREE_CLEARANCE_MARGIN = 0.25
"""Extra ground kept beyond every replicated canopy edge."""


def founding_trees(master_spec: dict) -> list[dict]:
    """Every INDIVIDUAL founding tree, exactly as the locked builder grew it.

    For each cluster position this replays the cluster's private generator
    draw for draw -- tree count, per-tree offsets, trunk height, canopy
    radius, then the 42 per-vertex canopy wobbles the locked builder
    consumes -- so the next tree's draws stay aligned. The result is one
    small canopy envelope per real tree instead of one fat disc per
    cluster: production fabric can nestle BETWEEN history's trees while
    still never touching a single branch.
    """
    seed = master_spec["visual_seed"]
    trees: list[dict] = []
    for cluster_index, (cluster_x, cluster_y) in enumerate(founding_tree_clusters(master_spec)):
        cluster_rng = stable_rng(seed, "vegetation", str(cluster_index))
        for _tree in range(cluster_rng.randint(2, 5)):
            offset_x = cluster_rng.uniform(-3.4, 3.4)
            offset_y = cluster_rng.uniform(-3.4, 3.4)
            cluster_rng.uniform(0.9, 1.6)
            canopy_radius = cluster_rng.uniform(1.0, 2.0)
            for _vertex in range(ICOSPHERE_VERTS):
                cluster_rng.uniform(-0.09, 0.09)
            trees.append(
                {
                    "cluster": cluster_index,
                    "x": cluster_x + offset_x,
                    "y": cluster_y + offset_y,
                    "r": canopy_radius * CANOPY_WOBBLE_FACTOR + TREE_CLEARANCE_MARGIN,
                }
            )
    return trees


FOUNDING_BUILDING_ENVELOPE = {
    "civic": 9.5,
    "port": 10.5,
    "residential": 12.5,
    "terrace": 16.0,
}
"""Conservative footprint envelope of one founding building, per district
character, measured from its lot origin.

Each locked Phase 15 archetype is generated from its own seeded ranges;
rather than replay every draw, this covers the WIDEST reach any of them
can take -- the civic podium's diagonal, the port shed's length, the
residential block plus its two wings, and the terrace slab's full stepped
run. Over-covering is the safe direction for an obstacle.
"""

FOUNDING_CARRIAGEWAY_CLEARANCE = 0.6
"""Open ground required between founding architecture and every declared
carriageway edge.

This is the production masses' own standard (the tightest legally placed
production mass clears its street by 0.615); history is held to the same
bar, measured against the real replayed footprint rather than the lot
origin. The original Phase 15 sampler accepted lots by ORIGIN distance
alone while a civic podium reaches 8.53 from its origin, which is how
seven founding footprint rectangles came to stand inside legal driving
space.

The clearance is measured to CARRIAGEWAYS -- the avenues, spurs, and
plate rings the master spec itself implies. Junction pads belong to the
production design: a production street that lands on a ring or meets an
avenue endpoint brings its pad to ground history already holds, and the
clearance suite measures those pads directly rather than this sampler
reserving every angle a future landing might take."""

FOUNDING_MUTUAL_CLEARANCE = 0.3
FOUNDING_PLAZA_CLEARANCE = 0.05
FOUNDING_DEPOT_CLEARANCE = 0.3
"""What a RELOCATED founding building keeps clear of, beyond the roads.

These are prudence rules, not mandates (see
:func:`_founding_position_is_legal`): a building standing on its original
Phase 15 ground keeps whatever plaza, mast, wall, depot or neighbour
contact the locked build gave it, because none of those is the road
encroachment this contract exists to correct. They bind only where the
ladder is already moving a building for a road reason, so a relocation
cannot swap one defect for another -- the gap rule in particular exists
solely to stop a relocation landing inside a neighbour, never to start
one."""

SEAL_MAST_FACTOR = 1.32
SEAL_MAST_ENVELOPE = 0.26
"""The Seal's four corner masts stand at ``1.32 * seal radius`` on the
diagonals of the gnomon frame; 0.26 covers a mast cap's half-diagonal.
Replicated from the locked ``build_golden_seal`` builder."""

FOUNDING_WALL_SCAR_LENGTH = 30.0
FOUNDING_WALL_SCAR_CORRIDOR = 6.0
FOUNDING_WALL_STATION_CORRIDOR = 2.5
"""Wall-station respect, mirrored from the production planning constants
(:mod:`urban_fabric` and :mod:`city_ground` carry the same three numbers):
a station at least 30.0 long is the scar and keeps its 6.0 corridor; the
short reserved alignments keep 2.5. Walls are episode state -- an export
may raise one on any boundary -- so the alignments stay buildable even
though the canonical export builds none."""

_FOUNDING_LADDER_RADIAL = tuple(step * 0.5 for step in range(-12, 13))
_FOUNDING_LADDER_ANGULAR = tuple(math.radians(step * 3.0) for step in range(-59, 61))
"""The deterministic relocation ladder: every candidate offset a founding
lot may try, radially in half-metre steps to +/-6.0 and angularly in
three-degree steps around the whole plate. Rungs are tried in order of
real ground displacement, so a lot moves exactly as far as legality
demands and not a step further."""

FOUNDING_LADDER_ROUNDS = 3
"""How many relaxation rounds the lots get to settle together.

One round is not enough for a crowded plate: a lot can be boxed in by a
neighbour that itself has to move, and only the neighbour's departure
frees the ground. Each round re-ladders exactly the lots still standing
illegally, so the pass is a fixpoint iteration that stops early the
moment a round changes nothing."""


def _ring_path(center: tuple[float, float], radius: float) -> list[tuple[float, float]]:
    """The 64-gon ring polyline exactly as the road graph declares it."""
    path = [
        (
            center[0] + radius * math.cos(2.0 * math.pi * index / 64),
            center[1] + radius * math.sin(2.0 * math.pi * index / 64),
        )
        for index in range(64)
    ]
    path.append(path[0])
    return path


def founding_carriageways(master_spec: dict) -> list[dict]:
    """Every founding carriageway, purely from the master spec.

    Avenues are arterial along their boundary paths; plate rings are
    collector circles at ``FOUNDING_RING_FACTOR * radius``; spurs are
    collector connectors from each ring to the nearest avenue endpoint --
    the same segments, classes, and 64-gon ring geometry
    :func:`road_graph._import_founding_network` declares, re-derived here
    so the Phase 15 sampler needs no production input to know where legal
    driving space is.

    Returns ``[{"id", "path", "half", "ring"}]``; ``ring`` marks the plate
    rings, whose circular geometry earns them an analytic distance
    shortcut in the ladder's fast path.
    """
    arterial = ROAD_CLASS_WIDTHS["arterial"] / 2.0
    collector = ROAD_CLASS_WIDTHS["collector"] / 2.0
    ways: list[dict] = []
    for boundary_id, boundary in sorted(master_spec["boundaries"].items()):
        path = [tuple(point) for point in boundary["path"]]
        ways.append({"id": f"avenue_{boundary_id}", "path": path, "half": arterial, "ring": False})
    for district_id, district in sorted(master_spec["districts"].items()):
        center = (float(district["center"][0]), float(district["center"][1]))
        ring_radius = FOUNDING_RING_FACTOR * float(district["radius"])
        ways.append(
            {
                "id": f"ring_{district_id}",
                "path": _ring_path(center, ring_radius),
                "half": collector,
                "ring": True,
                "center": center,
                "radius": ring_radius,
            }
        )
    for boundary_id, boundary in sorted(master_spec["boundaries"].items()):
        path = [tuple(point) for point in boundary["path"]]
        endpoints = {"a": path[0], "b": path[-1]}
        for district_id in boundary["districts"]:
            district = master_spec["districts"][district_id]
            center = district["center"]
            _which, best = min(
                endpoints.items(),
                key=lambda item: math.hypot(item[1][0] - center[0], item[1][1] - center[1]),
            )
            dx, dy = best[0] - center[0], best[1] - center[1]
            length = math.hypot(dx, dy) or 1.0
            ring_radius = FOUNDING_RING_FACTOR * float(district["radius"])
            ring_point = (
                center[0] + dx / length * ring_radius,
                center[1] + dy / length * ring_radius,
            )
            ways.append(
                {
                    "id": f"spur_{boundary_id}_{district_id}",
                    "path": [ring_point, tuple(best)],
                    "half": collector,
                    "ring": False,
                }
            )
    return ways


def _founding_wall_lines(master_spec: dict) -> list[tuple[tuple, tuple, float]]:
    """Every wall-station line with the corridor founding lots respect."""
    lines = []
    for _boundary_id, boundary in sorted(master_spec["boundaries"].items()):
        station = boundary["wall_station"]
        x, y = station["center"]
        dx, dy = station["direction"]
        length = math.hypot(dx, dy) or 1.0
        half = float(station["length"]) / 2.0
        ux, uy = dx / length, dy / length
        corridor = (
            FOUNDING_WALL_SCAR_CORRIDOR
            if float(station["length"]) >= FOUNDING_WALL_SCAR_LENGTH
            else FOUNDING_WALL_STATION_CORRIDOR
        )
        lines.append(((x - ux * half, y - uy * half), (x + ux * half, y + uy * half), corridor))
    return lines


def _founding_depot_pads(master_spec: dict) -> list[dict]:
    """Every district depot pad as the axis-aligned rectangle it is built as."""
    pads = []
    for _district_id, district in sorted(master_spec["districts"].items()):
        center_x, center_y = district["center"]
        length = math.hypot(center_x, center_y) or 1.0
        radius = float(district["radius"])
        pads.append(
            rect(
                center_x + (center_x / length) * radius * 0.62,
                center_y + (center_y / length) * radius * 0.62,
                6.5,
                8.5,
                0.0,
            )
        )
    return pads


def _archetype_plan(character: str, rng) -> dict:
    """The footprint-defining draws of one locked archetype, burned once.

    Consumes exactly the leading draws each Phase 15 builder makes before
    its footprint is fixed -- including the draws that shape nothing on the
    ground (heights, rooftop clutter) but keep the stream aligned -- so the
    plan's rectangles are bit-identical to the meshes the builder emits.
    """
    if character == "civic":
        width = rng.uniform(9.0, 12.0)
        depth = rng.uniform(9.0, 12.0)
        rotation = rng.uniform(-0.10, 0.10)
        return {"w": width, "d": depth, "rot": rotation}
    if character == "port":
        width = rng.uniform(13.0, 17.0)
        depth = rng.uniform(8.0, 11.0)
        rng.uniform(6.9, 8.3)
        rotation = rng.uniform(-0.35, 0.35)
        return {"w": width, "d": depth, "rot": rotation}
    if character == "residential":
        width = rng.uniform(10.0, 13.5)
        depth = rng.uniform(5.5, 6.5)
        rng.uniform(9.5, 15.5)
        rotation = rng.uniform(-0.3, 0.3)
        for _unit in range(rng.randint(2, 4)):
            for _draw in range(5):
                rng.uniform(0.0, 1.0)
        rng.uniform(-width * 0.2, width * 0.2)
        wing_depth = rng.uniform(5.0, 7.0)
        return {"w": width, "d": depth, "rot": rotation, "wing": wing_depth}
    width = rng.uniform(11.0, 15.0)
    depth = rng.uniform(6.5, 8.0)
    rotation = rng.uniform(-0.2, 0.2)
    rng.uniform(5.6, 8.6)
    steps = rng.randint(2, 3)
    return {"w": width, "d": depth, "rot": rotation, "steps": steps}


def _entrance_facade(x: float, y: float, rotation: float, center: tuple[float, float]) -> int:
    """Pick the facade (0..3 for +Y/-Y/+X/-X) facing the district center."""
    target = math.atan2(center[1] - y, center[0] - x)
    normals = (rotation + math.pi / 2.0, rotation - math.pi / 2.0, rotation, rotation + math.pi)
    scores = [math.cos(target - normal) for normal in normals]
    return scores.index(max(scores))


def _local_rect(x: float, y: float, rot: float, lx: float, ly: float, hw: float, hd: float) -> dict:
    """A rectangle at a local offset of a rotated lot frame."""
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    return rect(x + lx * cos_r - ly * sin_r, y + lx * sin_r + ly * cos_r, hw, hd, rot)


def _archetype_footprint(
    character: str, plan: dict, x: float, y: float, center: tuple[float, float]
) -> list[dict]:
    """Every ground-plan rectangle one archetype stands on at a position.

    The dims come from :func:`_archetype_plan` and never change; the
    entrance-dependent parts (a civic entry canopy, residential balconies)
    are re-derived per position exactly as the locked builders derive them,
    because the entrance follows the district center.
    """
    width, depth, rot = plan["w"], plan["d"], plan["rot"]
    parts: list[dict] = []
    if character == "civic":
        entrance = _entrance_facade(x, y, rot, center)
        parts.append({"part": "podium", "shape": rect(x, y, width / 2.0, depth / 2.0, rot)})
        nx, ny = ((0.0, 1.0), (0.0, -1.0), (1.0, 0.0), (-1.0, 0.0))[entrance]
        cw, cd = (3.6, 1.9) if nx == 0.0 else (1.9, 3.6)
        parts.append(
            {
                "part": "entry_canopy",
                "shape": _local_rect(
                    x,
                    y,
                    rot,
                    nx * (width / 2.0 + 0.85),
                    ny * (depth / 2.0 + 0.85),
                    cw / 2.0,
                    cd / 2.0,
                ),
            }
        )
    elif character == "port":
        parts.append({"part": "shed", "shape": rect(x, y, width / 2.0, depth / 2.0, rot)})
        parts.append(
            {
                "part": "door_trim",
                "shape": _local_rect(x, y, rot, 0.0, -(depth / 2.0 + 0.205), width / 2.0, 0.205),
            }
        )
    elif character == "residential":
        entrance = _entrance_facade(x, y, rot, center)
        parts.append({"part": "block", "shape": rect(x, y, width / 2.0, depth / 2.0, rot)})
        if entrance in (0, 1):
            sign = 1.0 if entrance == 0 else -1.0
            parts.append(
                {
                    "part": "balconies",
                    "shape": _local_rect(
                        x, y, rot, 0.0, sign * (depth / 2.0 + 0.515), width / 2.0, 0.515
                    ),
                }
            )
        wing = plan["wing"]
        for side, label in ((-1.0, "wing_west"), (1.0, "wing_east")):
            parts.append(
                {
                    "part": label,
                    "shape": _local_rect(
                        x,
                        y,
                        rot,
                        side * (width / 2.0 - depth / 2.0),
                        depth / 2.0 + wing / 2.0,
                        depth / 2.0,
                        wing / 2.0,
                    ),
                }
            )
    else:
        for step in range(plan["steps"]):
            step_width = width * (1.0 - 0.10 * step)
            parts.append(
                {
                    "part": f"step{step}",
                    "shape": _local_rect(
                        x, y, rot, 0.0, step * depth * 0.62, step_width / 2.0, depth / 2.0
                    ),
                }
            )
    return parts


def _footprint_reach(parts: list[dict], x: float, y: float) -> float:
    """The furthest any part's corner reaches from the lot origin."""
    return max(
        math.hypot(entry["shape"]["x"] - x, entry["shape"]["y"] - y)
        + math.hypot(entry["shape"]["hw"], entry["shape"]["hd"])
        for entry in parts
    )


def _rect_polyline_distance(shape: dict, path: list[tuple[float, float]], below: float) -> float:
    """Distance from a rectangle to a polyline, with a fast-fail cutoff.

    The relocation ladder only ever asks "is this rectangle closer than the
    required clearance"; the walk stops at the first leg that answers yes,
    which is what keeps an exhaustive ladder search affordable.
    """
    best = math.inf
    for (ax, ay), (bx, by) in zip(path, path[1:], strict=False):
        best = min(best, _rect_segment_distance(shape, ax, ay, bx, by))
        if best < below:
            return best
    return best


def _founding_position_is_legal(
    character: str,
    plan: dict,
    x: float,
    y: float,
    center: tuple[float, float],
    truth: dict,
    placed: list[dict],
    moved: bool,
) -> list[dict] | None:
    """The footprint at one position, or ``None`` with the position refused.

    Exactly ONE rule is a MANDATE, binding everywhere including original
    Phase 15 ground: every part clears every carriageway by
    :data:`FOUNDING_CARRIAGEWAY_CLEARANCE`. That rule, and only that rule,
    may cause a locked building to be relocated, because the encroachment
    of founding architecture on legal driving space is the defect this
    contract was opened to correct.

    Everything else -- the Seal plaza and its compass masts, the wall
    alignments, the depot pads, and the gap between two founding
    buildings -- is PRUDENCE, and binds only a position the ladder is
    MOVING a building to for that authorized road reason. The distinction
    is deliberate and was learned the hard way: as mandates these rules
    relitigate pre-existing Phase 15 conditions that are nobody's defect,
    and one of them dragged a building that already cleared every road by
    3.57 m down to 0.70 m to satisfy a gap rule nobody had asked for. As
    prudence they still do the one job worth doing -- a relocation may not
    CREATE a new conflict -- without ever moving a building on their own.
    """
    seal = truth["seal"]
    parts = _archetype_footprint(character, plan, x, y, center)
    reach = _footprint_reach(parts, x, y)
    for way in truth["ways"]:
        needed = way["half"] + FOUNDING_CARRIAGEWAY_CLEARANCE
        if way["ring"]:
            # The 64-gon lies inside its circle by at most the sagitta;
            # 0.05 over-covers it so the analytic shortcut never skips a
            # way the polyline test would have failed.
            origin_gap = (
                abs(math.hypot(x - way["center"][0], y - way["center"][1]) - way["radius"]) - 0.05
            )
        else:
            origin_gap = _distance_to_polyline(x, y, way["path"])
        if origin_gap - reach >= needed:
            continue
        for entry in parts:
            if _rect_polyline_distance(entry["shape"], way["path"], needed) < needed:
                return None
    if not moved:
        return parts
    for entry in parts:
        shape = entry["shape"]
        if _rect_point_distance(shape, seal["x"], seal["y"]) - seal["r"] < (
            FOUNDING_PLAZA_CLEARANCE
        ):
            return None
        for mast_x, mast_y in truth["masts"]:
            if _rect_point_distance(shape, mast_x, mast_y) - SEAL_MAST_ENVELOPE < (
                FOUNDING_PLAZA_CLEARANCE
            ):
                return None
        for line_a, line_b, corridor in truth["walls"]:
            if _rect_segment_distance(shape, line_a[0], line_a[1], line_b[0], line_b[1]) < corridor:
                return None
        for pad in truth["depot_pads"]:
            if shape_gap(shape, pad) < FOUNDING_DEPOT_CLEARANCE:
                return None
        for other in placed:
            if shape_gap(shape, other["shape"]) < FOUNDING_MUTUAL_CLEARANCE:
                return None
    return parts


def _founding_ladder(radius: float) -> list[tuple[float, float, float]]:
    """Relocation rungs sorted by true ground displacement, then offsets."""
    rungs = []
    for radial in _FOUNDING_LADDER_RADIAL:
        moved_radius = radius + radial
        for angular in _FOUNDING_LADDER_ANGULAR:
            chord = math.sqrt(
                max(
                    0.0,
                    radius * radius
                    + moved_radius * moved_radius
                    - 2.0 * radius * moved_radius * math.cos(angular),
                )
            )
            rungs.append((round(chord, 9), radial, angular))
    rungs.sort()
    return rungs


_FOUNDING_FOOTPRINT_CACHE: dict[str, list[dict]] = {}


def founding_building_footprints(master_spec: dict) -> list[dict]:
    """Every founding building's legal position and real ground plan.

    Replays the Phase 15 lot sampler draw for draw -- the same per-district
    generator identity, one ring offset and one jitter per candidate, the
    same depot / plaza / avenue / wall-station rejections in the same
    order -- and then makes each ACCEPTED lot street-legal: the archetype
    the builder will grow at that index is replayed to its footprint
    rectangles, and if any rectangle stands inside a carriageway, the Seal
    plaza, a wall corridor, a depot pad, or another founding building, the
    lot walks a deterministic relocation ladder and stands at the nearest
    position where nothing does.

    The candidate stream and its acceptance gates are untouched, so the
    lot COUNT and every building's index -- and therefore its seeded
    dimensions -- are exactly Phase 15's; only positions move, and only as
    far as legality demands. A lot ladders against the ground every other
    lot is CURRENTLY standing on, and the pass relaxes for up to
    :data:`FOUNDING_LADDER_ROUNDS` rounds, so a building never solves its
    own legality by stealing ground a neighbour holds -- it waits for the
    neighbour to vacate instead. A lot with no legal position anywhere on
    its plate keeps its original ground and is returned with ``blocked``
    True: refusal is recorded, never silently repaired by deletion.

    Returns one record per building: ``{"district", "index", "character",
    "name", "x", "y", "origin", "moved", "blocked", "parts"}`` with
    ``parts`` carrying the world-space footprint rectangles.
    """
    cache_key = json.dumps(
        [
            master_spec["visual_seed"],
            master_spec["districts"],
            master_spec["boundaries"],
            master_spec["landmarks"]["golden_seal"],
        ],
        sort_keys=True,
        default=str,
    )
    cached = _FOUNDING_FOOTPRINT_CACHE.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)

    seed = master_spec["visual_seed"]
    seal = master_spec["landmarks"]["golden_seal"]
    seal_x, seal_y = float(seal["location"][0]), float(seal["location"][1])
    masts = [
        (
            seal_x
            + math.cos(math.pi / 4.0 + index * math.pi / 2.0) * seal["radius"] * (SEAL_MAST_FACTOR),
            seal_y
            + math.sin(math.pi / 4.0 + index * math.pi / 2.0) * seal["radius"] * (SEAL_MAST_FACTOR),
        )
        for index in range(4)
    ]
    truth = {
        "ways": founding_carriageways(master_spec),
        "walls": _founding_wall_lines(master_spec),
        "depot_pads": _founding_depot_pads(master_spec),
        "masts": masts,
        "seal": {"x": seal_x, "y": seal_y, "r": float(seal["radius"])},
    }

    # Pass one: the locked candidate walk, exactly as Phase 15 accepted it.
    candidates: list[dict] = []
    for district_id, district in sorted(master_spec["districts"].items()):
        center_x, center_y = district["center"]
        radius = float(district["radius"])
        character = district["character"]
        rng = stable_rng(seed, district_id, "lots")
        plaza_clearance = float(seal["radius"]) + 3.5 if character == "civic" else 0.0
        length = math.hypot(center_x, center_y) or 1.0
        depot = (
            center_x + (center_x / length) * radius * 0.62,
            center_y + (center_y / length) * radius * 0.62,
        )
        road_clearance = 8.5 if character == "civic" else 10.0
        ring_step = 8.0 if plaza_clearance else 11.0
        ring_radius = max(9.0, plaza_clearance + 3.5)
        accepted = 0
        while ring_radius < radius - 3.0:
            count = max(5, int((2.0 * math.pi * ring_radius) / 11.0))
            offset = rng.uniform(0.0, 2.0 * math.pi)
            for index in range(count):
                angle = offset + (2.0 * math.pi * index) / count
                jitter = rng.uniform(-1.2, 1.2)
                x = center_x + (ring_radius + jitter) * math.cos(angle)
                y = center_y + (ring_radius + jitter) * math.sin(angle)
                if math.hypot(x - depot[0], y - depot[1]) < 11.0:
                    continue
                if plaza_clearance and math.hypot(x - center_x, y - center_y) < plaza_clearance:
                    continue
                rejected = False
                for boundary in master_spec["boundaries"].values():
                    path = [tuple(point) for point in boundary["path"]]
                    if _distance_to_polyline(x, y, path) < road_clearance:
                        rejected = True
                        break
                    station = boundary["wall_station"]
                    if math.hypot(x - station["center"][0], y - station["center"][1]) < 13.0:
                        rejected = True
                        break
                if rejected:
                    continue
                lot_index = accepted
                accepted += 1
                plan = _archetype_plan(
                    character, stable_rng(seed, district_id, "building", str(lot_index))
                )
                candidates.append(
                    {
                        "district": district_id,
                        "index": lot_index,
                        "character": character,
                        "plan": plan,
                        "x": x,
                        "y": y,
                        "center": (center_x, center_y),
                        "original": _archetype_footprint(
                            character, plan, x, y, (center_x, center_y)
                        ),
                    }
                )
            ring_radius += ring_step

    # Pass two: make the lots legal together. Each lot whose current ground
    # is illegal ladders to the nearest position clear of everything else's
    # CURRENT ground -- other lots' finals where they exist, their original
    # footprints where they do not -- and the pass repeats until a round
    # changes nothing, so a lot vacating its ground can free a neighbour
    # the previous round had nowhere to put. A lot already standing legally
    # is never re-laddered: placements stay put once they are right.
    states = [
        {"x": entry["x"], "y": entry["y"], "parts": entry["original"], "blocked": False}
        for entry in candidates
    ]
    for _round in range(FOUNDING_LADDER_ROUNDS):
        changed = False
        for position, candidate in enumerate(candidates):
            x, y = candidate["x"], candidate["y"]
            center_x, center_y = candidate["center"]
            others = [
                entry
                for other_position, state in enumerate(states)
                if other_position != position
                for entry in state["parts"]
            ]
            state = states[position]
            if (
                _founding_position_is_legal(
                    candidate["character"],
                    candidate["plan"],
                    state["x"],
                    state["y"],
                    (center_x, center_y),
                    truth,
                    others,
                    moved=(state["x"], state["y"]) != (x, y),
                )
                is not None
            ):
                state["blocked"] = False
                continue
            origin_radius = math.hypot(x - center_x, y - center_y)
            origin_angle = math.atan2(y - center_y, x - center_x)
            final = None
            for _chord, radial, angular in _founding_ladder(origin_radius):
                moved_x = center_x + (origin_radius + radial) * math.cos(origin_angle + angular)
                moved_y = center_y + (origin_radius + radial) * math.sin(origin_angle + angular)
                parts = _founding_position_is_legal(
                    candidate["character"],
                    candidate["plan"],
                    moved_x,
                    moved_y,
                    (center_x, center_y),
                    truth,
                    others,
                    moved=True,
                )
                if parts is not None:
                    final = (moved_x, moved_y, parts)
                    break
            if final is None:
                if (state["x"], state["y"]) != (x, y):
                    changed = True
                states[position] = {
                    "x": x,
                    "y": y,
                    "parts": candidate["original"],
                    "blocked": True,
                }
                continue
            final_x, final_y, parts = final
            if (final_x, final_y) != (state["x"], state["y"]):
                changed = True
            states[position] = {"x": final_x, "y": final_y, "parts": parts, "blocked": False}
        if not changed:
            break

    lots = [
        {
            "district": candidate["district"],
            "index": candidate["index"],
            "character": candidate["character"],
            "name": f"LD_BLDG__{candidate['district']}__{candidate['index']:03d}",
            "x": state["x"],
            "y": state["y"],
            "origin": (candidate["x"], candidate["y"]),
            "moved": round(math.hypot(state["x"] - candidate["x"], state["y"] - candidate["y"]), 6),
            "blocked": state["blocked"],
            "parts": state["parts"],
        }
        for candidate, state in zip(candidates, states, strict=True)
    ]
    _FOUNDING_FOOTPRINT_CACHE[cache_key] = copy.deepcopy(lots)
    return lots


def founding_blocked_buildings(master_spec: dict) -> list[str]:
    """The founding buildings this pass leaves in carriageway plan-space.

    These are the residual of the road-encroachment remediation, and they
    are named rather than counted so the set cannot quietly change size.
    Each one stands in legal carriageway space on its original Phase 15
    ground, and the Director has formally ACCEPTED the whole set as a
    permanent compatibility exception rather than an open defect.

    Four of them are irreducible: an exhaustive sweep of the whole
    district plate -- every position, at the archetype's locked
    dimensions -- found nowhere they could stand instead. The ground that
    clears every carriageway is already held by Class A history, by the
    Seal plaza and its masts and a wall corridor on the civic plate, by a
    depot pad or another founding building on the residential one.
    Lowering the mandate does not free them either: the same pass run at
    zero carriageway clearance blocks the identical set.

    The fifth, ``LD_BLDG__district_a__002``, is a DECLINE rather than an
    impossibility. No rung of this module's ladder reaches a legal
    position for it, but one exists off the ladder with roughly 15 mm of
    clearance, and refining the ladder to reach it was refused. Stating
    that here matters: the set is five, four of which are impossible and
    one of which is a decision.

    None of the five is moved and none is deleted; the lane network
    refuses to drive the sectors they occupy
    (:func:`vehicle_lane_network._founding_obstruction`) and the drawn
    road surfaces stop short of them, so the overlap survives in plan
    space and nowhere else. Both guards are permanent, because the
    residual is. A change in this list means the geometry of the
    remediation changed and the residual must be re-argued.
    """
    return [
        entry["name"] for entry in founding_building_footprints(master_spec) if entry["blocked"]
    ]


def founding_lot_positions(master_spec: dict, district_id: str) -> list[tuple[float, float]]:
    """The final lot positions of one district, in building-index order.

    This is what the Blender master-scene builder consumes; the structural
    suite pins the built meshes against the same replay, so the pure plan
    and the scene cannot drift apart.
    """
    return [
        (entry["x"], entry["y"])
        for entry in founding_building_footprints(master_spec)
        if entry["district"] == district_id
    ]


def founding_building_lots(master_spec: dict) -> list[dict]:
    """Every founding building lot as an obstacle envelope.

    One conservative disc per building (:data:`FOUNDING_BUILDING_ENVELOPE`)
    at the building's LEGAL position from
    :func:`founding_building_footprints`. The envelope is measured from the
    lot origin and covers the widest reach the archetype can take, so it
    over-covers the real footprint wherever the building stands.

    This exists because plate GROUND is open to designed planting while the
    ARCHITECTURE on it is not: without these envelopes a production tree
    could stand inside a founding building and no check would notice.
    """
    return [
        {
            "district": entry["district"],
            "character": entry["character"],
            "x": entry["x"],
            "y": entry["y"],
            "r": FOUNDING_BUILDING_ENVELOPE[entry["character"]],
        }
        for entry in founding_building_footprints(master_spec)
    ]


# ---------------------------------------------------------------------------
# What founding architecture stands over: the drawn-surface trim contract
# ---------------------------------------------------------------------------

TRIM_SCAN_STEP = 0.2
TRIM_BISECTION = 1.0e-3
TRIM_PAD = 0.15
"""How the trim finds a building's edge along a drawn strip.

The coverage boundary is found by scanning at
:data:`TRIM_SCAN_STEP` and bisecting to :data:`TRIM_BISECTION`, then the
covered span is widened by :data:`TRIM_PAD` on each side. Splitting at the
exact crossing rather than densifying the whole path is what keeps a
four-point avenue from becoming a hundred-quad ribbon.

The pad is not decoration. Coverage is measured on the WHOLE path's mitre,
while each surviving span is redrawn with its own end mitre, so the cut
edge lands a few millimetres off where it was measured; the pad swallows
that difference and leaves the facade a visible sliver of daylight instead
of a face grazing it."""


def strip_edges(
    path: list[tuple[float, float]], offset: float, half_width: float
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """The two lateral edges a ribbon builder lays down, vertex by vertex.

    Replicates the MITRE of the locked ribbon builder exactly: interior
    vertices take a central difference of their neighbours, ends take a
    one-sided one. Testing coverage against a per-leg perpendicular
    instead silently misses a building sitting in the wedge on the outside
    of a bend -- which is precisely where the founding wing on the
    boundary_cd elbow stands.
    """
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    for index, (x, y) in enumerate(path):
        if index == 0:
            dx, dy = path[1][0] - x, path[1][1] - y
        elif index == len(path) - 1:
            dx, dy = x - path[index - 1][0], y - path[index - 1][1]
        else:
            dx = path[index + 1][0] - path[index - 1][0]
            dy = path[index + 1][1] - path[index - 1][1]
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length, dx / length
        cx, cy = x + nx * offset, y + ny * offset
        left.append((cx + nx * half_width, cy + ny * half_width))
        right.append((cx - nx * half_width, cy - ny * half_width))
    return left, right


def _strip_cross_section(
    path: list[tuple[float, float]],
    stations: list[float],
    left: list[tuple[float, float]],
    right: list[tuple[float, float]],
    along: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """The drawn strip's two edges at one arc length, on the mitred surface."""
    for index in range(len(path) - 1):
        low, high = stations[index], stations[index + 1]
        if along <= high or index == len(path) - 2:
            span = high - low
            t = 0.0 if span <= 0.0 else min(1.0, max(0.0, (along - low) / span))
            return (
                (
                    left[index][0] + (left[index + 1][0] - left[index][0]) * t,
                    left[index][1] + (left[index + 1][1] - left[index][1]) * t,
                ),
                (
                    right[index][0] + (right[index + 1][0] - right[index][0]) * t,
                    right[index][1] + (right[index + 1][1] - right[index][1]) * t,
                ),
            )
    return (left[-1], right[-1])


def _path_stations(path: list[tuple[float, float]]) -> list[float]:
    """Cumulative arc length at each vertex of a polyline."""
    stations = [0.0]
    for (x0, y0), (x1, y1) in zip(path, path[1:], strict=False):
        stations.append(stations[-1] + math.hypot(x1 - x0, y1 - y0))
    return stations


def _point_at(path: list[tuple[float, float]], along: float) -> tuple[float, float]:
    """The point at one arc length along a polyline."""
    travelled = 0.0
    for (x0, y0), (x1, y1) in zip(path, path[1:], strict=False):
        length = math.hypot(x1 - x0, y1 - y0)
        if length <= 0.0:
            continue
        if travelled + length >= along:
            t = (along - travelled) / length
            return (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
        travelled += length
    return path[-1]


def founding_clear_spans(
    path: list[tuple[float, float]],
    footprints: list[dict],
    *,
    offset: float = 0.0,
    half_width: float = 0.0,
) -> list[list[tuple[float, float]]]:
    """The sub-paths of one drawn strip that no founding building stands on.

    A strip is the surface a ribbon builder lays down: the polyline pushed
    sideways by ``offset`` and widened by ``half_width`` on each side --
    carriageway, sidewalk, curb, or marking alike. This returns the
    maximal runs of that strip which are clear of every founding
    footprint, as sub-paths that keep the ORIGINAL vertices and add points
    only at the crossings, so a trimmed ribbon costs a handful of extra
    faces rather than a densified one.

    When nothing covers the strip the result is exactly ``[list(path)]``,
    which lets a caller delegate to the untrimmed builder and leave
    unaffected roads byte-identical.

    The footprints are :func:`founding_building_footprints` records -- the
    same source :mod:`vehicle_lane_network` refuses runs from -- so the
    drawn mesh and the lane guard cannot disagree about where a building
    stands.
    """
    parts = [entry["shape"] for lot in footprints for entry in lot["parts"]]
    if not parts or len(path) < 2:
        return [list(path)]
    stations = _path_stations(path)
    total = stations[-1]
    if total <= 0.0:
        return [list(path)]
    left, right = strip_edges(path, offset, half_width)

    def covered(along: float) -> bool:
        low, high = _strip_cross_section(path, stations, left, right, along)
        return any(
            _rect_segment_distance(shape, low[0], low[1], high[0], high[1]) <= 0.0
            for shape in parts
        )

    samples: list[tuple[float, bool]] = []
    steps = max(1, int(math.ceil(total / TRIM_SCAN_STEP)))
    for index in range(steps + 1):
        along = min(total, index * total / steps)
        samples.append((along, covered(along)))
    if not any(hit for _along, hit in samples):
        return [list(path)]

    def boundary(low: float, high: float) -> float:
        """Where coverage flips between two samples, to the declared precision."""
        low_state = covered(low)
        while high - low > TRIM_BISECTION:
            middle = (low + high) / 2.0
            if covered(middle) == low_state:
                low = middle
            else:
                high = middle
        return (low + high) / 2.0

    intervals: list[list[float]] = []
    for (a_along, a_hit), (b_along, b_hit) in zip(samples, samples[1:], strict=False):
        if a_hit and not intervals:
            intervals.append([a_along, a_along])
        if a_hit != b_hit:
            crossing = boundary(a_along, b_along)
            if b_hit:
                intervals.append([crossing, crossing])
            else:
                intervals[-1][1] = crossing
        elif a_hit and intervals:
            intervals[-1][1] = b_along
    if intervals and samples[-1][1]:
        intervals[-1][1] = total

    merged: list[list[float]] = []
    for start, end in intervals:
        start = max(0.0, start - TRIM_PAD)
        end = min(total, end + TRIM_PAD)
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    spans: list[list[tuple[float, float]]] = []
    cursor = 0.0
    for start, end in [*merged, [total, total]]:
        if start - cursor > TRIM_PAD:
            piece = [_point_at(path, cursor)]
            piece.extend(
                point
                for point, station in zip(path, stations, strict=True)
                if cursor < station < start
            )
            piece.append(_point_at(path, start))
            cleaned = [piece[0]]
            for point in piece[1:]:
                if math.hypot(point[0] - cleaned[-1][0], point[1] - cleaned[-1][1]) > 1.0e-9:
                    cleaned.append(point)
            if len(cleaned) >= 2:
                spans.append(cleaned)
        cursor = max(cursor, end)
    return spans


def founding_point_is_covered(
    x: float, y: float, footprints: list[dict], *, margin: float = 0.0
) -> bool:
    """True when a point stands inside (or within ``margin`` of) a building.

    Used for the scattered furniture a ribbon trim cannot express -- the
    centre-line dashes, which are individual boxes rather than a strip.
    """
    return any(
        _rect_point_distance(entry["shape"], x, y) <= margin
        for lot in footprints
        for entry in lot["parts"]
    )


def founding_ring_shadow(
    master_spec: dict,
    district_id: str,
    footprints: list[dict],
    *,
    segments: int,
    disc_radius: float,
) -> set[int]:
    """Which sectors of one district's ring disc stand under architecture.

    The disc is drawn as a fan of ``segments`` wedges; a wedge is omitted
    when it meets a founding footprint that ALSO occupies that ring's
    carriageway. The second condition is the point: it is the exact test
    :func:`vehicle_lane_network._founding_obstruction` applies to refuse a
    run, so the sectors that stop being drawn are precisely the sectors
    that stopped carrying traffic. A district whose architecture never
    reaches its carriageway keeps its disc whole.
    """
    ring = next(
        (way for way in founding_carriageways(master_spec) if way["id"] == f"ring_{district_id}"),
        None,
    )
    if ring is None:
        return set()
    shadowing = [
        entry["shape"]
        for lot in footprints
        for entry in lot["parts"]
        if any(
            _rect_segment_distance(entry["shape"], a[0], a[1], b[0], b[1]) <= ring["half"]
            for a, b in zip(ring["path"], ring["path"][1:], strict=False)
        )
    ]
    if not shadowing:
        return set()
    center = (
        float(master_spec["districts"][district_id]["center"][0]),
        float(master_spec["districts"][district_id]["center"][1]),
    )
    omit: set[int] = set()
    for index in range(segments):
        first = 2.0 * math.pi * index / segments
        second = 2.0 * math.pi * (index + 1) / segments
        wedge = [
            center,
            (center[0] + disc_radius * math.cos(first), center[1] + disc_radius * math.sin(first)),
            (
                center[0] + disc_radius * math.cos(second),
                center[1] + disc_radius * math.sin(second),
            ),
        ]
        if any(convex_polygons_intersect(wedge, _rect_corners(shape)) for shape in shadowing):
            omit.add(index)
    return omit


def founding_grove_clusters(master_spec: dict) -> dict[int, list[dict]]:
    """The founding forest grouped by cluster (one Blender object each).

    The locked Phase 15 builder merges every cluster into a single
    ``LD_TREE__NN`` object, so the landscape plan keeps or clears whole
    clusters; this grouping is the unit of that decision.
    """
    clusters: dict[int, list[dict]] = {}
    for tree in founding_trees(master_spec):
        clusters.setdefault(tree["cluster"], []).append(tree)
    return clusters
