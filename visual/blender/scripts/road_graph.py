"""The Phase 16 street network: deterministic road graph and its validation.

Pure Python by design -- no ``bpy``. The road graph is the abstract truth of
the production city's streets: every avenue, ring road, boulevard, and local
street is a SEGMENT with a polyline, a hierarchy class, and explicit endpoint
semantics; every junction is a NODE both segments reference. The Blender
street builder only draws what this graph declares, so connectivity is proven
as data BEFORE any geometry exists.

Redesign contract (aesthetic-first): every production street is an AUTHORED
polyline from the Production World Spec -- city planning, not generated
avoidance. The graph never bends, trims, or reroutes a designed street. When
a designed street would violate Class A truth (founding plates, wall-station
lines, the harbor, the diorama edge), the network is REFUSED so the design
can be fixed; low-priority presentation objects are the planner's problem to
clear, never a reason to deform a road.

The connectivity contract still holds in full: there are no unexplained road
fragments. Every open end of every street is either a shared junction node or
an intentional termination from the fixed taxonomy. A street may stop at a
quay, a plaza, a turnaround, or history -- never because the generator ran
out of geometry.

Determinism: the graph is a pure function of the Master Scene Spec and the
Production World Spec. Iteration is sorted, ids are constructed, and no
process randomness or ``hash()`` is involved anywhere.
"""

import math

from production_spec import FOUNDING_RING_FACTOR, coast_coordinate, port_frame

ROAD_CLASS_WIDTHS = {
    "arterial": 7.0,
    "collector": 5.2,
    "local": 3.4,
    "service": 4.2,
}
"""The street hierarchy: class name -> carriageway width in meters."""

TERMINATION_TYPES = (
    "cul_de_sac",
    "district_edge",
    "world_edge",
    "service_destination",
    "port_quay",
    "plaza_approach",
    "infrastructure_access",
    "wall_break",
)
"""Every legal reason a street may end without a junction."""

ROAD_EXTENT_LIMIT = 76.0
"""No street point may leave this radius from the world origin."""

TOUCH_TOLERANCE = 0.45
"""A node this close to another segment's polyline is a T-junction on it."""

CROSSING_NODE_TOLERANCE = 0.8
"""A computed crossing this close to a shared node reuses it."""

WALL_CLEARANCE = 3.0
"""Minimum distance between production streets and any wall station line."""

PLATE_ROAD_CLEARANCE = 0.0
"""Production street edges may touch, never overlap, a plate rim."""


class RoadGraphError(ValueError):
    """A road-network contract violation: always a refusal, never a repair."""


# ---------------------------------------------------------------------------
# Pure geometry
# ---------------------------------------------------------------------------


def _distance_point_segment(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    """Shortest distance from a point to one finite segment."""
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0.0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))


def distance_point_polyline(point: tuple[float, float], path: list[tuple[float, float]]) -> float:
    """Shortest distance from a point to a polyline."""
    best = math.inf
    for (ax, ay), (bx, by) in zip(path, path[1:], strict=False):
        best = min(best, _distance_point_segment(point[0], point[1], ax, ay, bx, by))
    return best


def _segment_crossing(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> tuple[float, float] | None:
    """Return the proper interior crossing point of two segments, if any.

    Endpoint touches are NOT crossings here; the T-junction pass owns those.
    """
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denominator = r[0] * s[1] - r[1] * s[0]
    if abs(denominator) < 1.0e-9:
        return None
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / denominator
    u = (qp[0] * r[1] - qp[1] * r[0]) / denominator
    margin = 1.0e-6
    if margin < t < 1.0 - margin and margin < u < 1.0 - margin:
        return (a[0] + r[0] * t, a[1] + r[1] * t)
    return None


def _segments_overlap_collinear(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> float:
    """Return the shared length of two collinear overlapping segments, else 0."""
    r = (b[0] - a[0], b[1] - a[1])
    length = math.hypot(*r)
    if length < 1.0e-9:
        return 0.0
    unit = (r[0] / length, r[1] / length)
    off_c = abs((c[0] - a[0]) * unit[1] - (c[1] - a[1]) * unit[0])
    off_d = abs((d[0] - a[0]) * unit[1] - (d[1] - a[1]) * unit[0])
    if off_c > 0.35 or off_d > 0.35:
        return 0.0
    t_c = (c[0] - a[0]) * unit[0] + (c[1] - a[1]) * unit[1]
    t_d = (d[0] - a[0]) * unit[0] + (d[1] - a[1]) * unit[1]
    low, high = min(t_c, t_d), max(t_c, t_d)
    return max(0.0, min(length, high) - max(0.0, low))


def _circle_path(
    center: tuple[float, float], radius: float, points: int
) -> list[tuple[float, float]]:
    """A closed circular polyline (first point repeated at the end)."""
    path = []
    for index in range(points):
        angle = 2.0 * math.pi * index / points
        path.append((center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle)))
    path.append(path[0])
    return path


def _polyline_length(path: list[tuple[float, float]]) -> float:
    """Total length of a polyline."""
    return sum(
        math.hypot(bx - ax, by - ay) for (ax, ay), (bx, by) in zip(path, path[1:], strict=False)
    )


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def _add_node(graph: dict, node_id: str, x: float, y: float) -> str:
    """Register one junction node, refusing silent redefinition."""
    existing = graph["nodes"].get(node_id)
    if existing is not None:
        if math.hypot(existing["x"] - x, existing["y"] - y) > 1.0e-6:
            raise RoadGraphError(f"node {node_id} redefined at a different position")
        return node_id
    graph["nodes"][node_id] = {"x": x, "y": y}
    return node_id


def _add_segment(
    graph: dict,
    segment_id: str,
    road_class: str,
    path: list[tuple[float, float]],
    *,
    closed: bool = False,
    end_a: dict | None = None,
    end_b: dict | None = None,
    existing: bool = False,
    owner: str = "",
) -> None:
    """Register one street segment."""
    if segment_id in graph["segments"]:
        raise RoadGraphError(f"segment {segment_id} defined twice")
    graph["segments"][segment_id] = {
        "class": road_class,
        "path": [(float(x), float(y)) for x, y in path],
        "closed": closed,
        "end_a": end_a,
        "end_b": end_b,
        "via": [],
        "existing": existing,
        "owner": owner,
    }


def _import_founding_network(graph: dict, master_spec: dict) -> None:
    """Import the authoritative Phase 15 streets as existing graph segments.

    Avenues, district plate ring roads, and spurs already exist as reviewed
    geometry; the graph represents them so connectivity can be proven across
    the WHOLE city, but the production builder never re-meshes them.
    """
    for boundary_id, boundary in sorted(master_spec["boundaries"].items()):
        path = [tuple(point) for point in boundary["path"]]
        end_a = _add_node(graph, f"avenue_{boundary_id}__a", path[0][0], path[0][1])
        end_b = _add_node(graph, f"avenue_{boundary_id}__b", path[-1][0], path[-1][1])
        _add_segment(
            graph,
            f"avenue_{boundary_id}",
            "arterial",
            path,
            end_a={"node": end_a},
            end_b={"node": end_b},
            existing=True,
        )
    for district_id, district in sorted(master_spec["districts"].items()):
        center = (float(district["center"][0]), float(district["center"][1]))
        ring_radius = FOUNDING_RING_FACTOR * float(district["radius"])
        _add_segment(
            graph,
            f"ring_{district_id}",
            "collector",
            _circle_path(center, ring_radius, 64),
            closed=True,
            existing=True,
        )
    for boundary_id, boundary in sorted(master_spec["boundaries"].items()):
        path = [tuple(point) for point in boundary["path"]]
        endpoints = {"a": path[0], "b": path[-1]}
        for district_id in boundary["districts"]:
            district = master_spec["districts"][district_id]
            center = district["center"]
            which, best = min(
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
            ring_node = _add_node(
                graph, f"ring_{district_id}__{boundary_id}", ring_point[0], ring_point[1]
            )
            graph["segments"][f"ring_{district_id}"]["via"].append(ring_node)
            _add_segment(
                graph,
                f"spur_{boundary_id}_{district_id}",
                "collector",
                [ring_point, best],
                end_a={"node": ring_node},
                end_b={"node": f"avenue_{boundary_id}__{which}"},
                existing=True,
            )


def _ring_landing(
    graph: dict, master_spec: dict, district_id: str, toward: tuple[float, float], label: str
) -> tuple[str, tuple[float, float]]:
    """A computed junction on a founding district's ring road."""
    district = master_spec["districts"].get(district_id)
    if district is None:
        raise RoadGraphError(f"{label} lands on unknown district {district_id!r}")
    center = district["center"]
    dx, dy = toward[0] - center[0], toward[1] - center[1]
    length = math.hypot(dx, dy) or 1.0
    ring_radius = FOUNDING_RING_FACTOR * float(district["radius"])
    point = (center[0] + dx / length * ring_radius, center[1] + dy / length * ring_radius)
    node_id = _add_node(graph, f"ring_{district_id}__{label}", point[0], point[1])
    graph["segments"][f"ring_{district_id}"]["via"].append(node_id)
    return node_id, point


def _add_designed_streets(graph: dict, master_spec: dict, spec: dict) -> None:
    """Register every authored production street exactly as designed.

    Declared ends resolve to ring landings (a computed node on a founding
    plate ring), avenue continuations (the existing avenue endpoint node), or
    terminations from the taxonomy. Undeclared ends become junction nodes:
    coincident endpoints share one node, and ends that stop on another
    street's polyline are attached by the T-junction pass. Nothing here ever
    moves a designed vertex.
    """
    streets = spec["streets"]
    resolved: dict[str, dict] = {}
    pending: list[tuple[str, str]] = []
    for street_id in sorted(streets):
        entry = streets[street_id]
        path = [(float(x), float(y)) for x, y in entry["path"]]
        ends: dict[str, dict | None] = {"end_a": None, "end_b": None}
        for end_name in ("end_a", "end_b"):
            declared = entry.get(end_name)
            if declared is None:
                continue
            if "termination" in declared:
                ends[end_name] = {"termination": declared["termination"]}
            elif "avenue" in declared:
                boundary = master_spec["boundaries"].get(declared["avenue"])
                if boundary is None:
                    raise RoadGraphError(
                        f"{street_id} {end_name} continues unknown avenue {declared['avenue']!r}"
                    )
                which = declared["end"]
                point = boundary["path"][0] if which == "a" else boundary["path"][-1]
                anchor = (float(point[0]), float(point[1]))
                own = path[0] if end_name == "end_a" else path[-1]
                if math.hypot(own[0] - anchor[0], own[1] - anchor[1]) > TOUCH_TOLERANCE:
                    raise RoadGraphError(
                        f"{street_id} {end_name} does not reach the "
                        f"{declared['avenue']} avenue endpoint"
                    )
                if end_name == "end_a":
                    path[0] = anchor
                else:
                    path[-1] = anchor
                ends[end_name] = {"node": f"avenue_{declared['avenue']}__{which}"}
            else:
                toward = path[0] if end_name == "end_a" else path[-1]
                node_id, point = _ring_landing(
                    graph, master_spec, declared["lands_on"], toward, street_id
                )
                if end_name == "end_a":
                    path.insert(0, point)
                else:
                    path.append(point)
                ends[end_name] = {"node": node_id}
        resolved[street_id] = {"class": entry["class"], "path": path, "ends": ends}
        for end_name in ("end_a", "end_b"):
            if ends[end_name] is None:
                pending.append((street_id, end_name))

    groups: dict[tuple[float, float], list[tuple[str, str]]] = {}
    for street_id, end_name in pending:
        record = resolved[street_id]
        point = record["path"][0] if end_name == "end_a" else record["path"][-1]
        key = (round(point[0], 2), round(point[1], 2))
        groups.setdefault(key, []).append((street_id, end_name))
    for key in sorted(groups):
        owner_id, owner_end = sorted(groups[key])[0]
        node_id = _add_node(graph, f"j__{owner_id}__{owner_end[-1]}", key[0], key[1])
        for street_id, end_name in groups[key]:
            record = resolved[street_id]
            record["ends"][end_name] = {"node": node_id}
            if end_name == "end_a":
                record["path"][0] = key
            else:
                record["path"][-1] = key

    for street_id in sorted(resolved):
        record = resolved[street_id]
        _add_segment(
            graph,
            street_id,
            record["class"],
            record["path"],
            end_a=record["ends"]["end_a"],
            end_b=record["ends"]["end_b"],
            existing=False,
        )


def _segment_node_ids(segment: dict) -> list[str]:
    """Every node id one segment references (endpoints then vias)."""
    ids = []
    for end in (segment["end_a"], segment["end_b"]):
        if end is not None and "node" in end:
            ids.append(end["node"])
    ids.extend(segment["via"])
    return ids


def _register_vertex_junctions(graph: dict) -> None:
    """Give every designed vertex that rests on another street a real node.

    A polyline INTERIOR vertex sitting on another street's carriageway is a
    designed junction (the southside grid's mid street crossing its high
    street, for example). Proper crossings get nodes from the crossing
    pass and endpoint touches from the T-junction pass; this pass owns the
    vertex-exactly-on-line case neither of those sees.
    """
    for segment_id, segment in sorted(graph["segments"].items()):
        if segment["existing"]:
            continue
        for index, point in enumerate(segment["path"][1:-1], start=1):
            hosts = [
                other_id
                for other_id, other in sorted(graph["segments"].items())
                if other_id != segment_id
                and distance_point_polyline(point, other["path"]) <= TOUCH_TOLERANCE
            ]
            if not hosts:
                continue
            near_existing = any(
                math.hypot(node["x"] - point[0], node["y"] - point[1]) <= CROSSING_NODE_TOLERANCE
                for node in graph["nodes"].values()
            )
            if near_existing:
                continue
            node_id = _add_node(graph, f"v__{segment_id}__{index:02d}", point[0], point[1])
            segment["via"].append(node_id)


def _register_t_junctions(graph: dict) -> None:
    """Attach any node lying on another segment's polyline as a via junction.

    This is how a boulevard's far end meets the orbital, a lane's start meets
    its collector, and a designed grid corner meets its cross street: the
    node position IS on the other polyline, so it becomes a shared junction.
    Existing/existing pairs are skipped -- the founding network is reviewed
    Phase 15 truth and is not re-derived here.
    """
    for _segment_id, segment in sorted(graph["segments"].items()):
        own = set(_segment_node_ids(segment))
        for node_id, node in sorted(graph["nodes"].items()):
            if node_id in own:
                continue
            referencing = [
                other_id
                for other_id, other in graph["segments"].items()
                if node_id in _segment_node_ids(other)
            ]
            if segment["existing"] and all(
                graph["segments"][other_id]["existing"] for other_id in referencing
            ):
                continue
            point = (node["x"], node["y"])
            if distance_point_polyline(point, segment["path"]) <= TOUCH_TOLERANCE:
                segment["via"].append(node_id)
                own.add(node_id)


def _register_crossings(graph: dict) -> None:
    """Turn every geometric street crossing into an explicit shared junction.

    Every proper crossing between two segments (unless both are founding
    streets) must resolve to a node both segments reference. If no shared
    node sits near the crossing, one is created. Collinear overlaps are never
    legalized this way -- they surface later as duplicate-street errors.
    """
    ordered = sorted(graph["segments"].items())
    for first_index, (first_id, first) in enumerate(ordered):
        for second_id, second in ordered[first_index + 1 :]:
            if first["existing"] and second["existing"]:
                continue
            shared = set(_segment_node_ids(first)) & set(_segment_node_ids(second))
            shared_points = [
                (graph["nodes"][node_id]["x"], graph["nodes"][node_id]["y"]) for node_id in shared
            ]
            crossing_count = 0
            for a, b in zip(first["path"], first["path"][1:], strict=False):
                for c, d in zip(second["path"], second["path"][1:], strict=False):
                    crossing = _segment_crossing(a, b, c, d)
                    if crossing is None:
                        continue
                    near_shared = any(
                        math.hypot(crossing[0] - px, crossing[1] - py) <= CROSSING_NODE_TOLERANCE
                        for px, py in shared_points
                    )
                    if near_shared:
                        continue
                    node_id = f"x__{first_id}__{second_id}__{crossing_count:02d}"
                    crossing_count += 1
                    _add_node(graph, node_id, crossing[0], crossing[1])
                    first["via"].append(node_id)
                    second["via"].append(node_id)
                    shared_points.append(crossing)


def build_road_graph(master_spec: dict, production_spec: dict) -> dict:
    """Build and validate the complete Phase 16 street network.

    Returns:
        The graph: ``{"nodes": {id: {x, y}}, "segments": {id: {...}}}``.

    Raises:
        RoadGraphError: Listing every violated network rule.
    """
    graph: dict = {"nodes": {}, "segments": {}}
    _import_founding_network(graph, master_spec)
    _add_designed_streets(graph, master_spec, production_spec)
    _register_vertex_junctions(graph)
    _register_t_junctions(graph)
    _register_crossings(graph)
    errors = validate_road_graph(graph, master_spec, production_spec)
    if errors:
        raise RoadGraphError(
            "the street network violates the connectivity contract:\n- " + "\n- ".join(errors)
        )
    return graph


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _check_segments_wellformed(graph: dict) -> list[str]:
    """Classes, polylines, closure, and zero-length legs."""
    errors = []
    for segment_id, segment in sorted(graph["segments"].items()):
        if segment["class"] not in ROAD_CLASS_WIDTHS:
            errors.append(f"{segment_id}: unknown road class {segment['class']!r}")
        path = segment["path"]
        if len(path) < 2:
            errors.append(f"{segment_id}: polyline needs at least two points")
            continue
        for index, ((ax, ay), (bx, by)) in enumerate(zip(path, path[1:], strict=False)):
            if math.hypot(bx - ax, by - ay) < 1.0e-6:
                errors.append(f"{segment_id}: zero-length leg at index {index}")
        if segment["closed"]:
            if math.hypot(path[0][0] - path[-1][0], path[0][1] - path[-1][1]) > 1.0e-6:
                errors.append(f"{segment_id}: declared closed but the polyline does not close")
        elif _polyline_length(path) < 2.0:
            errors.append(f"{segment_id}: open street shorter than 2.0")
    return errors


def _check_duplicates(graph: dict) -> list[str]:
    """No two streets may trace the same geometry, wholly or in part."""
    errors = []
    seen: dict[tuple, str] = {}
    ordered = sorted(graph["segments"].items())
    for segment_id, segment in ordered:
        rounded = tuple(sorted(((round(x, 3), round(y, 3)) for x, y in segment["path"])))
        key = (segment["class"], rounded)
        if key in seen:
            errors.append(f"{segment_id} duplicates {seen[key]}")
        else:
            seen[key] = segment_id
    for first_index, (first_id, first) in enumerate(ordered):
        for second_id, second in ordered[first_index + 1 :]:
            if first["existing"] and second["existing"]:
                continue
            for a, b in zip(first["path"], first["path"][1:], strict=False):
                for c, d in zip(second["path"], second["path"][1:], strict=False):
                    if _segments_overlap_collinear(a, b, c, d) > 1.5:
                        errors.append(
                            f"{first_id} and {second_id} overlap collinearly; "
                            "two streets may never trace the same carriageway"
                        )
                        break
                else:
                    continue
                break
    return errors


def _check_endpoints(graph: dict) -> list[str]:
    """Every open end is a real junction or an intentional termination."""
    errors = []
    node_use_count: dict[str, int] = {}
    for segment in graph["segments"].values():
        for node_id in set(_segment_node_ids(segment)):
            node_use_count[node_id] = node_use_count.get(node_id, 0) + 1
    for segment_id, segment in sorted(graph["segments"].items()):
        if segment["closed"]:
            if segment["end_a"] is not None or segment["end_b"] is not None:
                errors.append(f"{segment_id}: closed streets carry no endpoint records")
            continue
        for label, end, point in (
            ("end_a", segment["end_a"], segment["path"][0]),
            ("end_b", segment["end_b"], segment["path"][-1]),
        ):
            if end is None:
                errors.append(f"{segment_id}: {label} is an unexplained open end")
                continue
            if "node" in end:
                node = graph["nodes"].get(end["node"])
                if node is None:
                    errors.append(f"{segment_id}: {label} references unknown node {end['node']}")
                    continue
                if math.hypot(node["x"] - point[0], node["y"] - point[1]) > 1.0e-6:
                    errors.append(
                        f"{segment_id}: {label} node {end['node']} is not at the polyline end"
                    )
                if node_use_count.get(end["node"], 0) < 2:
                    errors.append(
                        f"{segment_id}: {label} dead-ends at {end['node']} with no "
                        "second street and no termination; unexplained fragments "
                        "are refused"
                    )
            elif "termination" in end:
                if end["termination"] not in TERMINATION_TYPES:
                    errors.append(
                        f"{segment_id}: {label} termination {end['termination']!r} is not "
                        f"in the taxonomy {TERMINATION_TYPES}"
                    )
            else:
                errors.append(f"{segment_id}: {label} must be a node or a termination")
    for node_id in sorted(node_use_count):
        if node_id not in graph["nodes"]:
            errors.append(f"via reference to unknown node {node_id}")
    for node_id in sorted(graph["nodes"]):
        if node_id not in node_use_count:
            errors.append(f"node {node_id} is referenced by no street")
    return errors


def _check_via_on_path(graph: dict) -> list[str]:
    """Every declared junction actually lies on its street."""
    errors = []
    for segment_id, segment in sorted(graph["segments"].items()):
        for node_id in segment["via"]:
            node = graph["nodes"].get(node_id)
            if node is None:
                continue
            gap = distance_point_polyline((node["x"], node["y"]), segment["path"])
            if gap > TOUCH_TOLERANCE:
                errors.append(
                    f"{segment_id}: junction {node_id} sits {gap:.2f} off the street; "
                    "intersections must actually intersect"
                )
    return errors


def _check_connectivity(graph: dict) -> list[str]:
    """One city, one network: every street reachable from the first avenue."""
    adjacency: dict[str, set[str]] = {}
    for segment_id, segment in graph["segments"].items():
        for node_id in _segment_node_ids(segment):
            adjacency.setdefault(node_id, set()).add(segment_id)
    start = "avenue_boundary_ab"
    if start not in graph["segments"]:
        return [f"connectivity anchor {start} is missing from the graph"]
    reached = {start}
    frontier = [start]
    while frontier:
        segment_id = frontier.pop()
        for node_id in _segment_node_ids(graph["segments"][segment_id]):
            for neighbor in adjacency.get(node_id, ()):
                if neighbor not in reached:
                    reached.add(neighbor)
                    frontier.append(neighbor)
    stranded = sorted(set(graph["segments"]) - reached)
    if stranded:
        return [
            "streets unreachable from the founding network (floating fragments): "
            + ", ".join(stranded)
        ]
    return []


def _wall_station_segment(
    boundary: dict,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """The finite wall line a boundary's station would occupy."""
    station = boundary["wall_station"]
    x, y = station["center"]
    dx, dy = station["direction"]
    length = math.hypot(dx, dy) or 1.0
    half = station["length"] / 2.0
    ux, uy = dx / length, dy / length
    return ((x - ux * half, y - uy * half), (x + ux * half, y + uy * half))


def _min_distance_paths(
    first: list[tuple[float, float]], second: list[tuple[float, float]]
) -> float:
    """Minimum distance between two polylines (crossing counts as zero)."""
    best = math.inf
    for a, b in zip(first, first[1:], strict=False):
        for c, d in zip(second, second[1:], strict=False):
            if _segment_crossing(a, b, c, d) is not None:
                return 0.0
            best = min(
                best,
                _distance_point_segment(a[0], a[1], c[0], c[1], d[0], d[1]),
                _distance_point_segment(b[0], b[1], c[0], c[1], d[0], d[1]),
                _distance_point_segment(c[0], c[1], a[0], a[1], b[0], b[1]),
                _distance_point_segment(d[0], d[1], a[0], a[1], b[0], b[1]),
            )
    return best


def _check_wall_clearance(graph: dict, master_spec: dict) -> list[str]:
    """History interrupts streets; streets never casually cross history.

    No production street may cross or crowd any wall-station line. Crossing
    the scar remains the privilege of the founding avenue with the controlled
    gate. A street that must stop AT a wall would declare a ``wall_break``
    termination -- none does in this design, and silent crossings are refused.
    """
    errors = []
    for boundary_id, boundary in sorted(master_spec["boundaries"].items()):
        wall = _wall_station_segment(boundary)
        for segment_id, segment in sorted(graph["segments"].items()):
            if segment["existing"]:
                continue
            gap = _min_distance_paths(segment["path"], list(wall))
            if gap < WALL_CLEARANCE:
                errors.append(
                    f"{segment_id} passes {gap:.2f} from the {boundary_id} wall station; "
                    "the scar keeps its ground even in the redesigned city"
                )
    return errors


def _street_end_exemptions(production_spec: dict, master_spec: dict) -> tuple[dict, dict]:
    """Which streets may approach which plates, and why.

    A street landing on a district's ring road may of course come down to
    that ring; a street continuing a founding avenue may leave the plate that
    avenue endpoint already stands on.
    """
    ring_gateway: dict[str, set[str]] = {}
    avenue_gateway: dict[str, set[str]] = {}
    for street_id, street in sorted(production_spec["streets"].items()):
        for end_name in ("end_a", "end_b"):
            end = street.get(end_name)
            if not isinstance(end, dict):
                continue
            if "lands_on" in end:
                ring_gateway.setdefault(street_id, set()).add(end["lands_on"])
            if "avenue" in end:
                boundary = master_spec["boundaries"][end["avenue"]]
                path = boundary["path"]
                point = path[0] if end["end"] == "a" else path[-1]
                for district_id, district in master_spec["districts"].items():
                    reach = math.hypot(
                        point[0] - district["center"][0], point[1] - district["center"][1]
                    )
                    if reach <= district["radius"] + 1.5:
                        avenue_gateway.setdefault(street_id, set()).add(district_id)
    return ring_gateway, avenue_gateway


def _check_plate_protection(graph: dict, master_spec: dict, production_spec: dict) -> list[str]:
    """Production streets never invade the founding plates.

    Ring landings alone may touch their own district's ring road -- that is
    their entire purpose -- and a street continuing an avenue may leave the
    plate that avenue already stands on. Everything else keeps clear.
    """
    errors = []
    ring_gateway, avenue_gateway = _street_end_exemptions(production_spec, master_spec)
    for segment_id, segment in sorted(graph["segments"].items()):
        if segment["existing"]:
            continue
        half_width = ROAD_CLASS_WIDTHS[segment["class"]] / 2.0
        for district_id, district in sorted(master_spec["districts"].items()):
            if district_id in avenue_gateway.get(segment_id, ()):
                continue
            center = (float(district["center"][0]), float(district["center"][1]))
            radius = float(district["radius"])
            gap = distance_point_polyline(center, segment["path"])
            if district_id in ring_gateway.get(segment_id, ()):
                allowed = FOUNDING_RING_FACTOR * radius - 0.5
            else:
                allowed = radius + 1.5 + half_width + PLATE_ROAD_CLEARANCE
            if gap < allowed:
                errors.append(
                    f"{segment_id} passes {gap:.2f} from {district_id} "
                    f"(minimum {allowed:.2f}); the historic core is never overbuilt"
                )
    return errors


def _check_extents(graph: dict, master_spec: dict, production_spec: dict) -> list[str]:
    """Streets stay on the diorama and out of the harbor water."""
    errors = []
    _center, _unit, quay_distance = port_frame(master_spec)
    for segment_id, segment in sorted(graph["segments"].items()):
        if segment["existing"]:
            continue
        quay_limit = quay_distance - 1.2
        for end in (segment["end_a"], segment["end_b"]):
            if end is not None and end.get("termination") == "port_quay":
                quay_limit = quay_distance + 0.5
        for x, y in segment["path"]:
            if math.hypot(x, y) > ROAD_EXTENT_LIMIT:
                errors.append(f"{segment_id} leaves the diorama at ({x:.1f}, {y:.1f})")
                break
            if coast_coordinate((x, y), master_spec) > quay_limit:
                errors.append(f"{segment_id} enters the harbor water at ({x:.1f}, {y:.1f})")
                break
    return errors


def _check_crossings_registered(graph: dict) -> list[str]:
    """No street crosses another without a shared junction node."""
    errors = []
    ordered = sorted(graph["segments"].items())
    for first_index, (first_id, first) in enumerate(ordered):
        for second_id, second in ordered[first_index + 1 :]:
            if first["existing"] and second["existing"]:
                continue
            shared_points = [
                (graph["nodes"][node_id]["x"], graph["nodes"][node_id]["y"])
                for node_id in set(_segment_node_ids(first)) & set(_segment_node_ids(second))
            ]
            for a, b in zip(first["path"], first["path"][1:], strict=False):
                for c, d in zip(second["path"], second["path"][1:], strict=False):
                    crossing = _segment_crossing(a, b, c, d)
                    if crossing is None:
                        continue
                    if not any(
                        math.hypot(crossing[0] - px, crossing[1] - py) <= CROSSING_NODE_TOLERANCE
                        for px, py in shared_points
                    ):
                        errors.append(
                            f"{first_id} crosses {second_id} near "
                            f"({crossing[0]:.1f}, {crossing[1]:.1f}) with no junction"
                        )
    return errors


def validate_road_graph(graph: dict, master_spec: dict, production_spec: dict) -> list[str]:
    """Run the full connectivity contract; return every violation found."""
    errors: list[str] = []
    errors.extend(_check_segments_wellformed(graph))
    errors.extend(_check_duplicates(graph))
    errors.extend(_check_endpoints(graph))
    errors.extend(_check_via_on_path(graph))
    errors.extend(_check_connectivity(graph))
    errors.extend(_check_wall_clearance(graph, master_spec))
    errors.extend(_check_plate_protection(graph, master_spec, production_spec))
    errors.extend(_check_extents(graph, master_spec, production_spec))
    errors.extend(_check_crossings_registered(graph))
    return errors


def junction_pads(graph: dict) -> list[dict]:
    """Every junction disc and turnaround the street network implies.

    One source of truth for both the spatial validator and the Blender
    junction builder: shared nodes get a disc sized for their widest
    street, intentional terminations get their turnaround or quay apron.
    """
    node_ids: dict[str, list[str]] = {}
    for segment_id, segment in graph["segments"].items():
        ids = list(segment["via"])
        for end in (segment["end_a"], segment["end_b"]):
            if end is not None and "node" in end:
                ids.append(end["node"])
        for node_id in set(ids):
            node_ids.setdefault(node_id, []).append(segment_id)
    pads: list[dict] = []
    node_width: dict[str, float] = {}
    for _segment_id, segment in graph["segments"].items():
        if segment["existing"]:
            continue
        ids = list(segment["via"])
        for end in (segment["end_a"], segment["end_b"]):
            if end is not None and "node" in end:
                ids.append(end["node"])
        for node_id in ids:
            width = ROAD_CLASS_WIDTHS[segment["class"]]
            node_width[node_id] = max(node_width.get(node_id, 0.0), width)
    for node_id, width in sorted(node_width.items()):
        if len(node_ids.get(node_id, ())) < 2:
            continue
        node = graph["nodes"][node_id]
        pads.append({"x": node["x"], "y": node["y"], "r": width / 2.0 + 1.0, "kind": "junction"})
    for _segment_id, segment in sorted(graph["segments"].items()):
        if segment["existing"]:
            continue
        for end, point in (
            (segment["end_a"], segment["path"][0]),
            (segment["end_b"], segment["path"][-1]),
        ):
            if end is None or "termination" not in end:
                continue
            if end["termination"] == "cul_de_sac":
                pads.append(
                    {
                        "x": point[0],
                        "y": point[1],
                        "r": ROAD_CLASS_WIDTHS[segment["class"]] / 2.0 + 1.6,
                        "kind": "turnaround",
                    }
                )
            elif end["termination"] == "port_quay":
                pads.append(
                    {
                        "x": point[0],
                        "y": point[1],
                        "r": ROAD_CLASS_WIDTHS[segment["class"]] / 2.0 + 0.8,
                        "kind": "quay_apron",
                    }
                )
    return pads


def graph_summary(graph: dict) -> dict:
    """Small deterministic stats block for reports and manifests."""
    class_counts: dict[str, int] = {}
    production_length = 0.0
    for segment in graph["segments"].values():
        class_counts[segment["class"]] = class_counts.get(segment["class"], 0) + 1
        if not segment["existing"]:
            production_length += _polyline_length(segment["path"])
    node_use_count: dict[str, int] = {}
    for segment in graph["segments"].values():
        for node_id in set(_segment_node_ids(segment)):
            node_use_count[node_id] = node_use_count.get(node_id, 0) + 1
    return {
        "nodes": len(graph["nodes"]),
        "segments": len(graph["segments"]),
        "segments_by_class": dict(sorted(class_counts.items())),
        "production_street_length": round(production_length, 1),
        "production_segments": sum(
            1 for segment in graph["segments"].values() if not segment["existing"]
        ),
        "intersections": sum(1 for count in node_use_count.values() if count >= 2),
    }
