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

import math

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


def founding_building_lots(master_spec: dict) -> list[dict]:
    """Every founding building lot, re-derived purely from the locked rules.

    Replays the Phase 15 lot sampler draw for draw -- the same per-district
    generator identity, one ring offset and one jitter per candidate, the
    same depot / plaza / avenue / wall-station rejections in the same
    order -- so the pure planner knows where the founding architecture
    stands without Blender.

    This exists because plate GROUND is open to designed planting while the
    ARCHITECTURE on it is not: without these envelopes a production tree
    could stand inside a founding building and no check would notice.
    """
    seed = master_spec["visual_seed"]
    seal = master_spec["landmarks"]["golden_seal"]
    lots: list[dict] = []
    for district_id, district in sorted(master_spec["districts"].items()):
        center_x, center_y = district["center"]
        radius = float(district["radius"])
        character = district["character"]
        rng = stable_rng(seed, district_id, "lots")
        plaza_clearance = float(seal["radius"]) + 3.5 if character == "civic" else 0.0
        length = math.hypot(center_x, center_y) or 1.0
        depot_x = center_x + (center_x / length) * radius * 0.62
        depot_y = center_y + (center_y / length) * radius * 0.62
        road_clearance = 8.5 if character == "civic" else 10.0
        ring_step = 8.0 if plaza_clearance else 11.0
        ring_radius = max(9.0, plaza_clearance + 3.5)
        while ring_radius < radius - 3.0:
            count = max(5, int((2.0 * math.pi * ring_radius) / 11.0))
            offset = rng.uniform(0.0, 2.0 * math.pi)
            for index in range(count):
                angle = offset + (2.0 * math.pi * index) / count
                jitter = rng.uniform(-1.2, 1.2)
                x = center_x + (ring_radius + jitter) * math.cos(angle)
                y = center_y + (ring_radius + jitter) * math.sin(angle)
                if math.hypot(x - depot_x, y - depot_y) < 11.0:
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
                lots.append(
                    {
                        "district": district_id,
                        "character": character,
                        "x": x,
                        "y": y,
                        "r": FOUNDING_BUILDING_ENVELOPE[character],
                    }
                )
            ring_radius += ring_step
    return lots


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
