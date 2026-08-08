"""Shared Blender runtime for the Living Diorama master scene.

Everything here runs inside Blender (``bpy``) and nowhere else. The pure
contract logic lives in :mod:`scene_spec`; this module owns the Blender-side
mechanics: the version gate, LD collection management, deterministic mesh
primitives (including the windowed-facade generator that gives buildings real
recessed glazing), the material family, and camera math.

All objects, meshes, and materials carry stable ``LD_``-prefixed names.
Builders remove any existing object of the same name before creating it, so
repeated builds converge to the same scene instead of growing ``.001`` copies.
"""

import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from scene_spec import SUPPORTED_BLENDER_MAJOR_MINOR, stable_rng  # noqa: E402
from style_profiles import MATERIAL_ROLES  # noqa: E402

ROOT_COLLECTION = "LD_WORLD"
CHILD_COLLECTIONS = (
    "LD_DISTRICTS",
    "LD_BOUNDARIES",
    "LD_WALLS",
    "LD_INFRASTRUCTURE",
    "LD_LANDMARKS",
    "LD_RULE_OBJECT",
    "LD_EPISODE",
    "LD_CAMERAS",
    "LD_LIGHTS",
)

WINDOW_CELL_UV = "LDCELL"
"""UV layer carrying one stable (bay, floor) id per glazing pane.

The occupancy shader reads this attribute, so a lit/unlit decision is always
constant across a pane by construction -- never dependent on where a rotated
facade happens to fall in world space.
"""


def require_supported_blender() -> None:
    """Refuse to run under an unsupported Blender version."""
    version = bpy.app.version
    if (version[0], version[1]) != SUPPORTED_BLENDER_MAJOR_MINOR:
        raise RuntimeError(
            f"Living Diorama Phase 15 requires Blender "
            f"{SUPPORTED_BLENDER_MAJOR_MINOR[0]}.{SUPPORTED_BLENDER_MAJOR_MINOR[1]}.x LTS; "
            f"this is Blender {version[0]}.{version[1]}.{version[2]}"
        )


def remove_factory_defaults() -> None:
    """Delete the factory startup Cube/Camera/Light and orphaned data."""
    for name in ("Cube", "Camera", "Light"):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
    purge_orphans()


def purge_orphans() -> None:
    """Remove unused meshes, materials, cameras, and lights."""
    for block_list in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.curves,
    ):
        for block in list(block_list):
            if block.users == 0:
                block_list.remove(block)


def wipe_ld_collections() -> None:
    """Remove every LD collection and everything inside, then purge."""
    root = bpy.data.collections.get(ROOT_COLLECTION)
    if root is not None:
        for collection in [root, *list(root.children_recursive)]:
            for obj in list(collection.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
        for collection in list(root.children_recursive):
            bpy.data.collections.remove(collection)
        bpy.data.collections.remove(root)
    purge_orphans()


def ensure_collections() -> dict[str, bpy.types.Collection]:
    """Create the LD collection tree and return it by name."""
    scene_collection = bpy.context.scene.collection
    root = bpy.data.collections.get(ROOT_COLLECTION)
    if root is None:
        root = bpy.data.collections.new(ROOT_COLLECTION)
        scene_collection.children.link(root)
    collections = {ROOT_COLLECTION: root}
    for name in CHILD_COLLECTIONS:
        child = bpy.data.collections.get(name)
        if child is None:
            child = bpy.data.collections.new(name)
        if child.name not in {c.name for c in root.children}:
            root.children.link(child)
        collections[name] = child
    return collections


def replace_object(name: str) -> None:
    """Remove an existing object of this name so rebuilds stay idempotent."""
    existing = bpy.data.objects.get(name)
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)


def link_only(obj: bpy.types.Object, collection: bpy.types.Collection) -> None:
    """Link an object to exactly one collection."""
    for linked in list(obj.users_collection):
        linked.objects.unlink(obj)
    collection.objects.link(obj)


def add_bevel(obj: bpy.types.Object, width: float = 0.09, segments: int = 2) -> None:
    """Give a hard-surface object physically plausible edge softening."""
    modifier = obj.modifiers.new("LD_Bevel", "BEVEL")
    modifier.width = width
    modifier.segments = segments
    modifier.limit_method = "ANGLE"
    modifier.angle_limit = math.radians(40.0)
    modifier.harden_normals = False


def _finish_object(
    name: str,
    builder: bmesh.types.BMesh,
    location: tuple[float, float, float],
    rotation_z: float,
    collection: bpy.types.Collection,
    materials: list[bpy.types.Material],
    bevel: float,
) -> bpy.types.Object:
    """Weld, orient, and register one built bmesh as a scene object."""
    bmesh.ops.remove_doubles(builder, verts=list(builder.verts), dist=1.0e-5)
    bmesh.ops.recalc_face_normals(builder, faces=list(builder.faces))
    replace_object(name)
    mesh = bpy.data.meshes.new(name)
    builder.to_mesh(mesh)
    builder.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.rotation_euler = (0.0, 0.0, rotation_z)
    for material in materials:
        obj.data.materials.append(material)
    if bevel > 0.0:
        add_bevel(obj, width=bevel)
    link_only(obj, collection)
    return obj


def _emit_box(
    builder: bmesh.types.BMesh,
    size: tuple[float, float, float],
    center: tuple[float, float, float],
    *,
    material_index: int = 0,
    rotation_z: float = 0.0,
) -> None:
    """Emit one closed box shell (origin at base center) into a bmesh."""
    half_x, half_y = size[0] / 2.0, size[1] / 2.0
    cos_r, sin_r = math.cos(rotation_z), math.sin(rotation_z)
    corners = []
    for dz in (0.0, size[2]):
        for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            local_x, local_y = dx * half_x, dy * half_y
            corners.append(
                builder.verts.new(
                    (
                        center[0] + local_x * cos_r - local_y * sin_r,
                        center[1] + local_x * sin_r + local_y * cos_r,
                        center[2] + dz,
                    )
                )
            )
    b0, b1, b2, b3, t0, t1, t2, t3 = corners
    quads = (
        (b3, b2, b1, b0),
        (t0, t1, t2, t3),
        (b0, b1, t1, t0),
        (b1, b2, t2, t1),
        (b2, b3, t3, t2),
        (b3, b0, t0, t3),
    )
    for quad in quads:
        face = builder.faces.new(quad)
        face.material_index = material_index


def make_box(
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    collection: bpy.types.Collection,
    material: bpy.types.Material,
    *,
    rotation_z: float = 0.0,
    bevel: float = 0.09,
) -> bpy.types.Object:
    """Create a beveled box with its origin at the base center."""
    builder = bmesh.new()
    _emit_box(builder, size, (0.0, 0.0, 0.0))
    return _finish_object(name, builder, location, rotation_z, collection, [material], bevel)


def make_detail_mesh(
    name: str,
    boxes: list[tuple],
    location: tuple[float, float, float],
    collection: bpy.types.Collection,
    materials: list[bpy.types.Material],
    *,
    rotation_z: float = 0.0,
    bevel: float = 0.03,
) -> bpy.types.Object:
    """Create one object holding many boxes: (size, offset, material index).

    Each entry is ``(size, offset, material_index)`` with an optional fourth
    element: a per-box local Z rotation. This is how repeated small details
    (railing posts, slab bands, radial fins, rooftop units, bollards, ladder
    rungs) stay one object each instead of exploding the scene object count.
    """
    builder = bmesh.new()
    for entry in boxes:
        size, offset, material_index = entry[0], entry[1], entry[2]
        box_rotation = entry[3] if len(entry) > 3 else 0.0
        _emit_box(builder, size, offset, material_index=material_index, rotation_z=box_rotation)
    return _finish_object(name, builder, location, rotation_z, collection, materials, bevel)


def make_cylinder(
    name: str,
    radius: float,
    depth: float,
    location: tuple[float, float, float],
    collection: bpy.types.Collection,
    material: bpy.types.Material,
    *,
    segments: int = 48,
    bevel: float = 0.08,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    smooth_sides: bool = False,
) -> bpy.types.Object:
    """Create a beveled cylinder with its origin at the base center."""
    replace_object(name)
    mesh = bpy.data.meshes.new(name)
    builder = bmesh.new()
    bmesh.ops.create_cone(
        builder,
        cap_ends=True,
        segments=segments,
        radius1=radius,
        radius2=radius,
        depth=depth,
    )
    for vertex in builder.verts:
        vertex.co.z += depth / 2.0
    if smooth_sides:
        for face in builder.faces:
            if abs(face.normal.z) < 0.5:
                face.smooth = True
    builder.to_mesh(mesh)
    builder.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.rotation_euler = rotation
    obj.data.materials.append(material)
    if bevel > 0.0:
        add_bevel(obj, width=bevel)
    link_only(obj, collection)
    return obj


def make_torus(
    name: str,
    major_radius: float,
    minor_radius: float,
    location: tuple[float, float, float],
    collection: bpy.types.Collection,
    material: bpy.types.Material,
    *,
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    major_segments: int = 64,
    minor_segments: int = 16,
) -> bpy.types.Object:
    """Create a torus ring (axis +Z before rotation), origin at its center."""
    replace_object(name)
    builder = bmesh.new()
    rings: list[list[bmesh.types.BMVert]] = []
    for major in range(major_segments):
        theta = 2.0 * math.pi * major / major_segments
        ring: list[bmesh.types.BMVert] = []
        for minor in range(minor_segments):
            phi = 2.0 * math.pi * minor / minor_segments
            radial = major_radius + minor_radius * math.cos(phi)
            ring.append(
                builder.verts.new(
                    (
                        radial * math.cos(theta),
                        radial * math.sin(theta),
                        minor_radius * math.sin(phi),
                    )
                )
            )
        rings.append(ring)
    for major in range(major_segments):
        ring_a = rings[major]
        ring_b = rings[(major + 1) % major_segments]
        for minor in range(minor_segments):
            builder.faces.new(
                (
                    ring_a[minor],
                    ring_b[minor],
                    ring_b[(minor + 1) % minor_segments],
                    ring_a[(minor + 1) % minor_segments],
                )
            )
    bmesh.ops.recalc_face_normals(builder, faces=list(builder.faces))
    mesh = bpy.data.meshes.new(name)
    builder.to_mesh(mesh)
    builder.free()
    mesh.shade_smooth()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    obj.rotation_euler = rotation
    obj.data.materials.append(material)
    link_only(obj, collection)
    return obj


class FacadeStyle:
    """Parameters describing one archetype's window and facade language."""

    def __init__(
        self,
        *,
        bay_pitch: float = 1.7,
        floor_height: float = 3.1,
        margin: float = 0.6,
        window_frac: float = 0.58,
        sill: float = 0.95,
        head: float = 0.45,
        recess: float = 0.22,
        frame: float = 0.07,
        plinth: float = 0.55,
        parapet: float = 0.7,
        ground_floor: float = 0.0,
        ground_window_frac: float = 0.72,
        ground_sill: float = 0.45,
        mullion: bool = True,
    ) -> None:
        """Store the facade proportions for one archetype."""
        self.bay_pitch = bay_pitch
        self.floor_height = floor_height
        self.margin = margin
        self.window_frac = window_frac
        self.sill = sill
        self.head = head
        self.recess = recess
        self.frame = frame
        self.plinth = plinth
        self.parapet = parapet
        self.ground_floor = ground_floor
        self.ground_window_frac = ground_window_frac
        self.ground_sill = ground_sill
        self.mullion = mullion


MASS_MATERIAL_SLOTS = ("facade", "frame", "glass", "roof", "interior")
"""Material slot order every windowed mass uses, keyed by role."""


def _facade_rows(height: float, style: FacadeStyle) -> list[tuple[float, float, bool]]:
    """Split a facade's height into (bottom, top, is_ground) window rows."""
    rows: list[tuple[float, float, bool]] = []
    cursor = style.plinth
    if style.ground_floor > 0.0 and height - cursor - style.parapet >= style.ground_floor:
        rows.append((cursor, cursor + style.ground_floor, True))
        cursor += style.ground_floor
    while cursor + style.floor_height <= height - style.parapet + 1.0e-6:
        rows.append((cursor, cursor + style.floor_height, False))
        cursor += style.floor_height
    return rows


def _emit_facade(
    builder: bmesh.types.BMesh,
    uv_layer,
    origin: Vector,
    u_dir: Vector,
    normal: Vector,
    length: float,
    height: float,
    style: FacadeStyle,
    *,
    facade_index: int,
    entrance_bay: int | None,
) -> None:
    """Emit one facade of a windowed mass: strips, jambs, frames, glazing.

    All quads. Facade-plane regions never overlap, every window opening is a
    closed pocket (jambs + frame border + pane), and each pane's loops carry a
    stable (bay, floor) id in the ``LDCELL`` UV layer.
    """
    up = Vector((0.0, 0.0, 1.0))

    def point(u: float, v: float, depth: float = 0.0) -> Vector:
        return origin + u_dir * u + up * v - normal * depth

    def quad(
        corners: tuple[Vector, Vector, Vector, Vector],
        material_index: int,
        cell: tuple[float, float] | None = None,
    ) -> None:
        verts = [builder.verts.new(corner) for corner in corners]
        face = builder.faces.new(verts)
        face.material_index = material_index
        if cell is not None:
            for loop in face.loops:
                loop[uv_layer].uv = cell

    def flat(u0: float, u1: float, v0: float, v1: float, material_index: int = 0) -> None:
        if u1 - u0 <= 1.0e-6 or v1 - v0 <= 1.0e-6:
            return
        quad(
            (point(u0, v0), point(u1, v0), point(u1, v1), point(u0, v1)),
            material_index,
        )

    rows = _facade_rows(height, style)
    usable = length - 2.0 * style.margin
    bays = max(1, int(usable // style.bay_pitch))
    bay_width = usable / bays

    flat(0.0, style.margin, 0.0, height)
    flat(length - style.margin, length, 0.0, height)
    flat(style.margin, length - style.margin, 0.0, style.plinth)
    top_of_rows = rows[-1][1] if rows else style.plinth
    flat(style.margin, length - style.margin, top_of_rows, height)

    for row_index, (v_bottom, v_top, is_ground) in enumerate(rows):
        window_frac = style.ground_window_frac if is_ground else style.window_frac
        sill = style.ground_sill if is_ground else style.sill
        head = style.head
        window_v0 = v_bottom + sill
        window_v1 = v_top - head
        if window_v1 - window_v0 < 0.4:
            flat(style.margin, length - style.margin, v_bottom, v_top)
            continue
        flat(style.margin, length - style.margin, v_bottom, window_v0)
        flat(style.margin, length - style.margin, window_v1, v_top)
        for bay in range(bays):
            bay_u0 = style.margin + bay * bay_width
            bay_u1 = bay_u0 + bay_width
            is_entrance = is_ground and entrance_bay is not None and bay == entrance_bay
            frac = 0.86 if is_entrance else window_frac
            window_width = bay_width * frac
            window_u0 = bay_u0 + (bay_width - window_width) / 2.0
            window_u1 = window_u0 + window_width
            flat(bay_u0, window_u0, window_v0, window_v1)
            flat(window_u1, bay_u1, window_v0, window_v1)
            recess = style.recess * (2.6 if is_entrance else 1.0)
            open_v0 = v_bottom + 0.06 if is_entrance else window_v0
            if is_entrance:
                flat(bay_u0, window_u0, v_bottom, window_v0)
                flat(window_u1, bay_u1, v_bottom, window_v0)
                flat(style.margin, bay_u0, v_bottom, window_v0)
                flat(bay_u1, length - style.margin, v_bottom, window_v0)

            quad(  # left jamb
                (
                    point(window_u0, open_v0),
                    point(window_u0, open_v0, recess),
                    point(window_u0, window_v1, recess),
                    point(window_u0, window_v1),
                ),
                1,
            )
            quad(  # right jamb
                (
                    point(window_u1, open_v0),
                    point(window_u1, window_v1),
                    point(window_u1, window_v1, recess),
                    point(window_u1, open_v0, recess),
                ),
                1,
            )
            quad(  # sill return
                (
                    point(window_u0, open_v0),
                    point(window_u1, open_v0),
                    point(window_u1, open_v0, recess),
                    point(window_u0, open_v0, recess),
                ),
                1,
            )
            quad(  # head return
                (
                    point(window_u0, window_v1),
                    point(window_u0, window_v1, recess),
                    point(window_u1, window_v1, recess),
                    point(window_u1, window_v1),
                ),
                1,
            )

            cell = (float(facade_index * 61 + bay), float(row_index))
            if is_entrance:
                flat_depth = recess
                quad(
                    (
                        point(window_u0, open_v0, flat_depth),
                        point(window_u1, open_v0, flat_depth),
                        point(window_u1, window_v1, flat_depth),
                        point(window_u0, window_v1, flat_depth),
                    ),
                    4,
                )
                continue
            border = style.frame
            pane_u0, pane_u1 = window_u0 + border, window_u1 - border
            pane_v0, pane_v1 = open_v0 + border, window_v1 - border
            for frame_quad in (
                (window_u0, pane_u0, open_v0, window_v1),
                (pane_u1, window_u1, open_v0, window_v1),
                (pane_u0, pane_u1, open_v0, pane_v0),
                (pane_u0, pane_u1, pane_v1, window_v1),
            ):
                fu0, fu1, fv0, fv1 = frame_quad
                quad(
                    (
                        point(fu0, fv0, recess),
                        point(fu1, fv0, recess),
                        point(fu1, fv1, recess),
                        point(fu0, fv1, recess),
                    ),
                    1,
                )
            pane_mid = (pane_u0 + pane_u1) / 2.0
            panes = (
                ((pane_u0, pane_mid - 0.03), (pane_mid + 0.03, pane_u1))
                if style.mullion and pane_u1 - pane_u0 > 1.05
                else ((pane_u0, pane_u1),)
            )
            if len(panes) == 2:
                mid0, mid1 = panes[0][1], panes[1][0]
                quad(
                    (
                        point(mid0, pane_v0, recess),
                        point(mid1, pane_v0, recess),
                        point(mid1, pane_v1, recess),
                        point(mid0, pane_v1, recess),
                    ),
                    1,
                )
            for pane_index, (pu0, pu1) in enumerate(panes):
                quad(
                    (
                        point(pu0, pane_v0, recess),
                        point(pu1, pane_v0, recess),
                        point(pu1, pane_v1, recess),
                        point(pu0, pane_v1, recess),
                    ),
                    2,
                    cell=(cell[0] + pane_index * 0.37, cell[1]),
                )


def make_windowed_mass(
    name: str,
    size: tuple[float, float, float],
    location: tuple[float, float, float],
    collection: bpy.types.Collection,
    materials: dict[str, bpy.types.Material],
    style: FacadeStyle,
    *,
    rotation_z: float = 0.0,
    entrance_facade: int | None = None,
    material_keys: tuple[str, str, str, str, str] = (
        "facade_panels",
        "frame_metal",
        "glass_civic",
        "roof_dark",
        "interior_glow",
    ),
    bevel: float = 0.0,
) -> bpy.types.Object:
    """Create one building mass whose facades carry real recessed windows.

    The mass is a closed solid: four windowed facades, roof, and underside.
    Windows are genuine openings -- jamb returns, a frame border, and a
    glazing pane set back into the wall -- so light and reflections behave
    like architecture instead of like decals. ``entrance_facade`` (0..3 for
    +Y, -Y, +X, -X) selects one ground-floor bay as a recessed lobby.
    """
    width, depth, height = size
    builder = bmesh.new()
    uv_layer = builder.loops.layers.uv.new(WINDOW_CELL_UV)
    half_w, half_d = width / 2.0, depth / 2.0
    facades = (
        (Vector((-half_w, half_d, 0.0)), Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), width),
        (Vector((half_w, -half_d, 0.0)), Vector((-1.0, 0.0, 0.0)), Vector((0.0, -1.0, 0.0)), width),
        (Vector((half_w, half_d, 0.0)), Vector((0.0, -1.0, 0.0)), Vector((1.0, 0.0, 0.0)), depth),
        (Vector((-half_w, -half_d, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((-1.0, 0.0, 0.0)), depth),
    )
    for facade_index, (origin, u_dir, normal, length) in enumerate(facades):
        usable = length - 2.0 * style.margin
        bays = max(1, int(usable // style.bay_pitch))
        entrance_bay = bays // 2 if entrance_facade == facade_index else None
        _emit_facade(
            builder,
            uv_layer,
            origin,
            u_dir,
            normal,
            length,
            height,
            style,
            facade_index=facade_index,
            entrance_bay=entrance_bay,
        )
    roof_corners = (
        Vector((-half_w, -half_d, height)),
        Vector((half_w, -half_d, height)),
        Vector((half_w, half_d, height)),
        Vector((-half_w, half_d, height)),
    )
    roof = builder.faces.new([builder.verts.new(corner) for corner in roof_corners])
    roof.material_index = 3
    floor_corners = (
        Vector((-half_w, half_d, 0.0)),
        Vector((half_w, half_d, 0.0)),
        Vector((half_w, -half_d, 0.0)),
        Vector((-half_w, -half_d, 0.0)),
    )
    floor = builder.faces.new([builder.verts.new(corner) for corner in floor_corners])
    floor.material_index = 0
    ordered = [materials[material_keys[index]] for index in range(len(MASS_MATERIAL_SLOTS))]
    return _finish_object(name, builder, location, rotation_z, collection, ordered, bevel)


def polyline_stations(
    path: list[tuple[float, float]], spacing: float
) -> list[tuple[float, float, float]]:
    """Return (x, y, heading) stations along a 2D polyline at fixed spacing."""
    stations: list[tuple[float, float, float]] = []
    carried = 0.0
    for (x0, y0), (x1, y1) in zip(path, path[1:], strict=False):
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length == 0.0:
            continue
        heading = math.atan2(dy, dx)
        distance = carried
        while distance <= length:
            t = distance / length
            stations.append((x0 + dx * t, y0 + dy * t, heading))
            distance += spacing
        carried = distance - length
    return stations


def make_ribbon(
    name: str,
    path: list[tuple[float, float]],
    width: float,
    height: float,
    elevation: float,
    collection: bpy.types.Collection,
    material: bpy.types.Material,
    *,
    offset: float = 0.0,
) -> bpy.types.Object:
    """Create a flat ribbon following a 2D polyline (roads, sidewalks)."""
    replace_object(name)
    left: list[Vector] = []
    right: list[Vector] = []
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
        half = width / 2.0
        left.append(Vector((cx + nx * half, cy + ny * half, elevation)))
        right.append(Vector((cx - nx * half, cy - ny * half, elevation)))
    mesh = bpy.data.meshes.new(name)
    builder = bmesh.new()
    lower: list[bmesh.types.BMVert] = []
    upper: list[bmesh.types.BMVert] = []
    for point in left:
        lower.append(builder.verts.new(point))
    for point in right:
        upper.append(builder.verts.new(point))
    for index in range(len(path) - 1):
        builder.faces.new((lower[index], lower[index + 1], upper[index + 1], upper[index]))
    result = bmesh.ops.extrude_face_region(builder, geom=list(builder.faces))
    extruded = [item for item in result["geom"] if isinstance(item, bmesh.types.BMVert)]
    bmesh.ops.translate(builder, verts=extruded, vec=(0.0, 0.0, height))
    bmesh.ops.recalc_face_normals(builder, faces=list(builder.faces))
    builder.to_mesh(mesh)
    builder.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(material)
    link_only(obj, collection)
    return obj


PRACTICAL_LIGHT_SCALE = 1.0
"""Style-profile multiplier applied to practical lights (not the key rig)."""


def set_practical_light_scale(scale: float) -> None:
    """Set the style profile's practical-light energy multiplier."""
    global PRACTICAL_LIGHT_SCALE
    PRACTICAL_LIGHT_SCALE = scale


def make_light(
    name: str,
    kind: str,
    location: tuple[float, float, float],
    collection: bpy.types.Collection,
    *,
    energy: float,
    color: tuple[float, float, float],
    target: tuple[float, float, float] | None = None,
    size: float = 0.5,
    spot_angle: float = 1.1,
    spot_blend: float = 0.4,
    practical: bool = True,
) -> bpy.types.Object:
    """Create or refresh one named light (POINT, SPOT, SUN, or AREA).

    Practical lights (street lamps, floods, washes, uplights) scale with the
    active style profile; rig lights pass ``practical=False`` because their
    energies are owned by the profile's lighting section directly.
    """
    light_data = bpy.data.lights.get(name)
    if light_data is None or light_data.type != kind:
        if light_data is not None:
            light_data.name = f"{name}__stale"
        light_data = bpy.data.lights.new(name, kind)
    light_data.energy = energy * (PRACTICAL_LIGHT_SCALE if practical else 1.0)
    light_data.color = color
    if kind == "AREA":
        light_data.size = size
    elif kind == "SPOT":
        light_data.spot_size = spot_angle
        light_data.spot_blend = spot_blend
        light_data.shadow_soft_size = size
    elif kind == "POINT":
        light_data.shadow_soft_size = size
    replace_object(name)
    light = bpy.data.objects.new(name, light_data)
    light.location = location
    if target is not None:
        light.rotation_euler = look_at_rotation(Vector(location), Vector(target))
    link_only(light, collection)
    return light


def look_at_rotation(location: Vector, target: Vector) -> tuple[float, float, float]:
    """Return the Euler rotation aiming a camera at a target."""
    direction = target - location
    rotation = direction.to_track_quat("-Z", "Y")
    return rotation.to_euler()[:]


def distance_to_polyline(x: float, y: float, path: list[tuple[float, float]]) -> float:
    """Return the shortest distance from a point to a 2D polyline."""
    best = math.inf
    for (x0, y0), (x1, y1) in zip(path, path[1:], strict=False):
        dx, dy = x1 - x0, y1 - y0
        length_squared = dx * dx + dy * dy
        if length_squared == 0.0:
            continue
        t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / length_squared))
        px, py = x0 + dx * t, y0 + dy * t
        best = min(best, math.hypot(x - px, y - py))
    return best


# ---------------------------------------------------------------------------
# Material family
# ---------------------------------------------------------------------------


def _fresh_material(name: str):
    """Return a fresh node material with its nodes, links, and Principled."""
    existing = bpy.data.materials.get(name)
    if existing is not None:
        bpy.data.materials.remove(existing)
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    principled = nodes["Principled BSDF"]
    return material, nodes, links, principled


def _object_coords(nodes, links):
    """Return the object-space coordinate socket for one material."""
    coords = nodes.new("ShaderNodeTexCoord")
    return coords.outputs["Object"]


def _math(nodes, links, operation: str, a, b=None, value: float | None = None):
    """Chain one math node; ``a``/``b`` may be sockets or constants."""
    node = nodes.new("ShaderNodeMath")
    node.operation = operation
    for index, operand in enumerate((a, b)):
        if operand is None:
            continue
        if hasattr(operand, "is_linked"):
            links.new(operand, node.inputs[index])
        else:
            node.inputs[index].default_value = operand
    if value is not None:
        node.inputs[1].default_value = value
    return node.outputs[0]


def _map_range(nodes, links, source, from_min, from_max, to_min, to_max):
    """Remap one scalar socket through a clamped Map Range node."""
    node = nodes.new("ShaderNodeMapRange")
    node.inputs["From Min"].default_value = from_min
    node.inputs["From Max"].default_value = from_max
    node.inputs["To Min"].default_value = to_min
    node.inputs["To Max"].default_value = to_max
    links.new(source, node.inputs["Value"])
    return node.outputs["Result"]


def _noise(nodes, links, vector, scale: float, detail: float = 3.0, *, stretch=None):
    """A noise texture over a vector socket, optionally anisotropic."""
    source = vector
    if stretch is not None:
        mapping = nodes.new("ShaderNodeMapping")
        mapping.inputs["Scale"].default_value = stretch
        links.new(vector, mapping.inputs["Vector"])
        source = mapping.outputs["Vector"]
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = detail
    links.new(source, noise.inputs["Vector"])
    return noise.outputs["Fac"]


def _grid_mask(nodes, links, axis, pitch: float, line_width: float):
    """A 0/1 mask that is 1 in a thin band around every multiple of pitch."""
    scaled = _math(nodes, links, "MULTIPLY", axis, 1.0 / pitch)
    fraction = _math(nodes, links, "FRACT", scaled)
    centered = _math(nodes, links, "SUBTRACT", fraction, 0.5)
    distance = _math(nodes, links, "ABSOLUTE", centered)
    threshold = 0.5 - (line_width / pitch) / 2.0
    return _math(nodes, links, "GREATER_THAN", distance, threshold)


def _mix_color(nodes, links, factor, color_a, color_b):
    """Mix two RGBA colors (sockets or tuples) by a factor socket."""
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    if hasattr(factor, "is_linked"):
        links.new(factor, mix.inputs["Factor"])
    else:
        mix.inputs["Factor"].default_value = factor
    for socket_name, operand in (("A", color_a), ("B", color_b)):
        if hasattr(operand, "is_linked"):
            links.new(operand, mix.inputs[socket_name])
        else:
            mix.inputs[socket_name].default_value = operand
    return mix.outputs["Result"]


def _concrete_material(
    name: str,
    color: tuple[float, float, float],
    *,
    roughness: float = 0.72,
    value_variation: float = 0.10,
    panel_pitch: tuple[float, float] | None = None,
    streaks: float = 0.0,
    grime_height: float = 0.0,
    grain_scale: float = 55.0,
    grain_strength: float = 0.035,
) -> bpy.types.Material:
    """Concrete and masonry: tonal patches, fine grain, seams, weathering.

    The goal is a surface that reads as cast material -- not as a noise
    texture. Panel seams are aligned grooves, streaking is vertical and
    subtle, grime hugs the base, and everything perturbs color, roughness,
    and normal together.
    """
    material, nodes, links, principled = _fresh_material(name)
    coords = _object_coords(nodes, links)
    low, high = 1.0 - 1.8 * value_variation, 1.0 + 1.2 * value_variation
    darker = (*[channel * low for channel in color], 1.0)
    lighter = (*[min(1.0, channel * high) for channel in color], 1.0)

    patches = _noise(nodes, links, coords, 0.33, 4.0)
    surface_color = _mix_color(nodes, links, patches, darker, lighter)

    height_sources = []
    grain = _noise(nodes, links, coords, grain_scale, 5.0)
    height_sources.append(_math(nodes, links, "MULTIPLY", grain, 1.0))

    if streaks > 0.0:
        streak = _noise(nodes, links, coords, 7.0, 4.0, stretch=(6.0, 6.0, 0.3))
        streak_mask = _map_range(nodes, links, streak, 0.35, 0.8, 0.0, streaks)
        surface_color = _mix_color(nodes, links, streak_mask, surface_color, darker)

    separate = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coords, separate.inputs["Vector"])
    if panel_pitch is not None:
        horizontal_pitch, vertical_pitch = panel_pitch
        lines_x = _grid_mask(nodes, links, separate.outputs["X"], horizontal_pitch, 0.03)
        lines_y = _grid_mask(nodes, links, separate.outputs["Y"], horizontal_pitch, 0.03)
        lines_h = _math(nodes, links, "MAXIMUM", lines_x, lines_y)
        lines_z = _grid_mask(nodes, links, separate.outputs["Z"], vertical_pitch, 0.03)
        seams = _math(nodes, links, "MAXIMUM", lines_h, lines_z)
        seam_shadow = _math(nodes, links, "MULTIPLY", seams, 0.55)
        surface_color = _mix_color(nodes, links, seam_shadow, surface_color, darker)
        seam_depth = _math(nodes, links, "MULTIPLY", seams, -2.4)
        height_sources.append(seam_depth)

    if grime_height > 0.0:
        grime = _map_range(nodes, links, separate.outputs["Z"], 0.0, grime_height, 0.5, 0.0)
        grime_noise = _noise(nodes, links, coords, 2.4, 3.0)
        grime_fac = _math(nodes, links, "MULTIPLY", grime, grime_noise)
        surface_color = _mix_color(nodes, links, grime_fac, surface_color, darker)

    height = height_sources[0]
    for extra in height_sources[1:]:
        height = _math(nodes, links, "ADD", height, extra)
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = grain_strength
    links.new(height, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], principled.inputs["Normal"])

    links.new(surface_color, principled.inputs["Base Color"])
    rough = _map_range(nodes, links, patches, 0.0, 1.0, roughness - 0.05, roughness + 0.07)
    links.new(rough, principled.inputs["Roughness"])
    return material


def _metal_material(
    name: str,
    color: tuple[float, float, float],
    roughness: float,
    *,
    metallic: float = 1.0,
    stretch: tuple[float, float, float] | None = None,
    variation: float = 0.10,
    rib_pitch: float = 0.0,
) -> bpy.types.Material:
    """Architectural metal with directional roughness breakup and ribs."""
    material, nodes, links, principled = _fresh_material(name)
    coords = _object_coords(nodes, links)
    principled.inputs["Base Color"].default_value = (*color, 1.0)
    principled.inputs["Metallic"].default_value = metallic
    streak = _noise(nodes, links, coords, 9.0, 3.0, stretch=stretch or (1.0, 1.0, 0.12))
    rough = _map_range(nodes, links, streak, 0.0, 1.0, roughness - variation, roughness + variation)
    links.new(rough, principled.inputs["Roughness"])
    height = _math(nodes, links, "MULTIPLY", streak, 1.0)
    if rib_pitch > 0.0:
        separate = nodes.new("ShaderNodeSeparateXYZ")
        links.new(coords, separate.inputs["Vector"])
        ribs_x = _grid_mask(nodes, links, separate.outputs["X"], rib_pitch, rib_pitch * 0.42)
        ribs_y = _grid_mask(nodes, links, separate.outputs["Y"], rib_pitch, rib_pitch * 0.42)
        ribs = _math(nodes, links, "MAXIMUM", ribs_x, ribs_y)
        height = _math(nodes, links, "ADD", height, _math(nodes, links, "MULTIPLY", ribs, 5.0))
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.06 if rib_pitch else 0.02
    links.new(height, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], principled.inputs["Normal"])
    return material


def _gold_material(
    name: str,
    *,
    color: tuple[float, float, float] = (0.855, 0.638, 0.242),
    rough_min: float = 0.12,
    rough_max: float = 0.30,
) -> bpy.types.Material:
    """The Golden Seal alloy: engraved concentric rings and radial spokes."""
    material, nodes, links, principled = _fresh_material(name)
    coords = _object_coords(nodes, links)
    principled.inputs["Base Color"].default_value = (*color, 1.0)
    principled.inputs["Metallic"].default_value = 1.0
    separate = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coords, separate.inputs["Vector"])
    xx = _math(nodes, links, "MULTIPLY", separate.outputs["X"], separate.outputs["X"])
    yy = _math(nodes, links, "MULTIPLY", separate.outputs["Y"], separate.outputs["Y"])
    radius = _math(nodes, links, "SQRT", _math(nodes, links, "ADD", xx, yy))
    rings = _math(nodes, links, "SINE", _math(nodes, links, "MULTIPLY", radius, 22.0))
    angle = _math(nodes, links, "ARCTAN2", separate.outputs["Y"], separate.outputs["X"])
    spokes = _math(nodes, links, "SINE", _math(nodes, links, "MULTIPLY", angle, 24.0))
    spokes_sharp = _math(nodes, links, "GREATER_THAN", spokes, 0.86)
    engraving = _math(
        nodes,
        links,
        "ADD",
        _math(nodes, links, "MULTIPLY", rings, 0.45),
        _math(nodes, links, "MULTIPLY", spokes_sharp, -1.4),
    )
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.18
    links.new(engraving, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], principled.inputs["Normal"])
    rough = _map_range(nodes, links, rings, -1.0, 1.0, rough_min, rough_max)
    links.new(rough, principled.inputs["Roughness"])
    return material


def _glass_occupancy_material(
    name: str,
    *,
    warm_color: tuple[float, float, float],
    cool_color: tuple[float, float, float],
    cool_share: float,
    strength: float,
    default_fraction: float = 0.35,
    unlit_roughness: float = 0.07,
) -> bpy.types.Material:
    """District glazing: dark reflective glass whose panes light per episode.

    The lit/unlit decision reads the pane's stable ``LDCELL`` id plus the
    building's location through white noise, compared against the
    ``LD_LitFraction`` value the episode application drives per district.
    Deterministic across machines; constant across each pane by construction.
    """
    material, nodes, links, principled = _fresh_material(name)
    principled.inputs["Base Color"].default_value = (0.010, 0.014, 0.020, 1.0)
    principled.inputs["Metallic"].default_value = 0.0
    principled.inputs["Roughness"].default_value = unlit_roughness

    cell = nodes.new("ShaderNodeAttribute")
    cell.attribute_name = WINDOW_CELL_UV
    object_info = nodes.new("ShaderNodeObjectInfo")
    identity = nodes.new("ShaderNodeVectorMath")
    identity.operation = "ADD"
    links.new(cell.outputs["Vector"], identity.inputs[0])
    links.new(object_info.outputs["Location"], identity.inputs[1])

    lit_noise = nodes.new("ShaderNodeTexWhiteNoise")
    lit_noise.noise_dimensions = "3D"
    links.new(identity.outputs[0], lit_noise.inputs["Vector"])

    lit_fraction = nodes.new("ShaderNodeValue")
    lit_fraction.name = "LD_LitFraction"
    lit_fraction.label = "LD_LitFraction"
    lit_fraction.outputs[0].default_value = default_fraction
    lit = _math(nodes, links, "LESS_THAN", lit_noise.outputs["Value"], lit_fraction.outputs[0])

    shifted = nodes.new("ShaderNodeVectorMath")
    shifted.operation = "ADD"
    links.new(identity.outputs[0], shifted.inputs[0])
    shifted.inputs[1].default_value = (13.71, 5.33, 9.17)
    tone_noise = nodes.new("ShaderNodeTexWhiteNoise")
    tone_noise.noise_dimensions = "3D"
    links.new(shifted.outputs[0], tone_noise.inputs["Vector"])
    tone = tone_noise.outputs["Value"]

    is_cool = _math(nodes, links, "GREATER_THAN", tone, 1.0 - cool_share)
    interior = _mix_color(nodes, links, is_cool, (*warm_color, 1.0), (*cool_color, 1.0))
    links.new(interior, principled.inputs["Emission Color"])

    jitter = _map_range(nodes, links, tone, 0.0, 1.0, 0.35, 1.25)
    per_window = _math(nodes, links, "MULTIPLY", lit, jitter)
    emission = _math(nodes, links, "MULTIPLY", per_window, strength)
    links.new(emission, principled.inputs["Emission Strength"])

    rough = _map_range(nodes, links, lit, 0.0, 1.0, unlit_roughness, 0.32)
    links.new(rough, principled.inputs["Roughness"])
    return material


def _emissive_material(
    name: str, color: tuple[float, float, float], strength: float
) -> bpy.types.Material:
    """A practical-light emissive surface."""
    material, nodes, links, principled = _fresh_material(name)
    principled.inputs["Base Color"].default_value = (*color, 1.0)
    principled.inputs["Emission Color"].default_value = (*color, 1.0)
    principled.inputs["Emission Strength"].default_value = strength
    return material


def _hazard_material(name: str) -> bpy.types.Material:
    """Painted yellow/charcoal warning chevrons (never emissive)."""
    material, nodes, links, principled = _fresh_material(name)
    coords = _object_coords(nodes, links)
    separate = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coords, separate.inputs["Vector"])
    diagonal = _math(nodes, links, "ADD", separate.outputs["X"], separate.outputs["Z"])
    with_y = _math(nodes, links, "ADD", diagonal, separate.outputs["Y"])
    stripes = _math(nodes, links, "FRACT", _math(nodes, links, "MULTIPLY", with_y, 2.4))
    band = _math(nodes, links, "GREATER_THAN", stripes, 0.5)
    color = _mix_color(nodes, links, band, (0.60, 0.42, 0.03, 1.0), (0.028, 0.028, 0.030, 1.0))
    links.new(color, principled.inputs["Base Color"])
    principled.inputs["Roughness"].default_value = 0.5
    return material


def _water_material(
    name: str, *, roughness: float = 0.045, bump_strength: float = 0.075
) -> bpy.types.Material:
    """Still harbor water: dark, glossy, with two scales of ripple."""
    material, nodes, links, principled = _fresh_material(name)
    coords = _object_coords(nodes, links)
    principled.inputs["Base Color"].default_value = (0.006, 0.016, 0.020, 1.0)
    principled.inputs["Roughness"].default_value = roughness
    ripple = _noise(nodes, links, coords, 11.0, 5.0)
    swell = _noise(nodes, links, coords, 1.3, 3.0)
    height = _math(
        nodes,
        links,
        "ADD",
        _math(nodes, links, "MULTIPLY", ripple, 0.5),
        _math(nodes, links, "MULTIPLY", swell, 1.0),
    )
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = bump_strength
    links.new(height, bump.inputs["Height"])
    links.new(bump.outputs["Normal"], principled.inputs["Normal"])
    return material


MATERIAL_SPECS: dict[str, tuple] = {
    "concrete": (_concrete_material, {"color": (0.380, 0.365, 0.335), "panel_pitch": (1.5, 1.5)}),
    "concrete_dark": (_concrete_material, {"color": (0.115, 0.115, 0.120), "grime_height": 1.2}),
    "scar_concrete": (
        _concrete_material,
        {
            "color": (0.225, 0.230, 0.244),
            "roughness": 0.68,
            "panel_pitch": (2.52, 3.6),
            "streaks": 0.65,
            "grime_height": 3.6,
        },
    ),
    "facade_civic": (
        _concrete_material,
        {"color": (0.430, 0.408, 0.360), "panel_pitch": (1.7, 3.1)},
    ),
    "facade_residential": (
        _concrete_material,
        {"color": (0.310, 0.196, 0.130), "roughness": 0.78, "grime_height": 1.0},
    ),
    "facade_terrace": (
        _concrete_material,
        {"color": (0.238, 0.252, 0.262), "panel_pitch": (2.0, 3.1)},
    ),
    "facade_port": (
        _metal_material,
        {
            "color": (0.062, 0.058, 0.055),
            "roughness": 0.55,
            "metallic": 0.85,
            "stretch": (1.0, 1.0, 0.10),
            "rib_pitch": 0.55,
        },
    ),
    "curb": (_concrete_material, {"color": (0.290, 0.280, 0.262), "value_variation": 0.05}),
    "pavement": (
        _concrete_material,
        {
            "color": (0.148, 0.142, 0.130),
            "roughness": 0.8,
            "panel_pitch": (1.1, 1.1),
            "grain_scale": 90.0,
        },
    ),
    "asphalt": (
        _concrete_material,
        {
            "color": (0.020, 0.020, 0.023),
            "roughness": 0.82,
            "grain_scale": 140.0,
            "grain_strength": 0.05,
        },
    ),
    "road_marking": (_concrete_material, {"color": (0.520, 0.505, 0.470), "roughness": 0.55}),
    "platform": (
        _metal_material,
        {
            "color": (0.016, 0.017, 0.020),
            "roughness": 0.34,
            "metallic": 0.25,
            "stretch": (0.25, 4.0, 1.0),
            "variation": 0.14,
        },
    ),
    "terrain": (
        _concrete_material,
        {
            "color": (0.042, 0.050, 0.036),
            "roughness": 0.92,
            "grain_scale": 3.0,
            "grain_strength": 0.30,
        },
    ),
    "water": (_water_material, {}),
    "foliage": (
        _concrete_material,
        {
            "color": (0.028, 0.052, 0.024),
            "roughness": 0.85,
            "grain_scale": 22.0,
            "grain_strength": 0.45,
        },
    ),
    "bark": (
        _concrete_material,
        {"color": (0.052, 0.038, 0.026), "roughness": 0.9, "grain_scale": 30.0},
    ),
    "metal_dark": (_metal_material, {"color": (0.038, 0.040, 0.046), "roughness": 0.52}),
    "metal_civic": (
        _metal_material,
        {"color": (0.052, 0.070, 0.080), "roughness": 0.45, "metallic": 0.8},
    ),
    "metal_gate": (
        _metal_material,
        {
            "color": (0.045, 0.047, 0.052),
            "roughness": 0.52,
            "stretch": (1.0, 1.0, 0.08),
            "variation": 0.16,
        },
    ),
    "frame_metal": (
        _metal_material,
        {"color": (0.030, 0.031, 0.034), "roughness": 0.44, "metallic": 0.9},
    ),
    "roof_dark": (
        _concrete_material,
        {
            "color": (0.036, 0.036, 0.038),
            "roughness": 0.9,
            "grain_scale": 70.0,
            "grain_strength": 0.06,
        },
    ),
    "gold": (_gold_material, {}),
    "glass_civic": (
        _glass_occupancy_material,
        {
            "warm_color": (1.0, 0.62, 0.30),
            "cool_color": (0.84, 0.88, 0.97),
            "cool_share": 0.22,
            "strength": 1.5,
        },
    ),
    "glass_port": (
        _glass_occupancy_material,
        {
            "warm_color": (1.0, 0.66, 0.34),
            "cool_color": (0.78, 0.88, 1.0),
            "cool_share": 0.5,
            "strength": 1.6,
        },
    ),
    "glass_residential": (
        _glass_occupancy_material,
        {
            "warm_color": (1.0, 0.56, 0.24),
            "cool_color": (0.95, 0.88, 0.76),
            "cool_share": 0.12,
            "strength": 1.9,
        },
    ),
    "glass_terrace": (
        _glass_occupancy_material,
        {
            "warm_color": (1.0, 0.60, 0.28),
            "cool_color": (0.86, 0.90, 1.0),
            "cool_share": 0.25,
            "strength": 2.0,
        },
    ),
    "glass_dark": (
        _glass_occupancy_material,
        {
            "warm_color": (1.0, 0.62, 0.30),
            "cool_color": (0.80, 0.90, 1.0),
            "cool_share": 0.5,
            "strength": 0.0,
            "default_fraction": 0.0,
        },
    ),
    "interior_glow": (_emissive_material, {"color": (1.0, 0.58, 0.26), "strength": 1.7}),
    "warm_light": (_emissive_material, {"color": (1.0, 0.60, 0.27), "strength": 18.0}),
    "cool_light": (_emissive_material, {"color": (0.78, 0.87, 1.0), "strength": 1.3}),
    "edge_glow": (_emissive_material, {"color": (0.55, 0.72, 1.0), "strength": 1.1}),
    "seal_glow": (_emissive_material, {"color": (1.0, 0.70, 0.28), "strength": 5.0}),
    "warning_red": (_emissive_material, {"color": (1.0, 0.04, 0.02), "strength": 12.0}),
    "hazard": (_hazard_material, {}),
    "container_a": (
        _metal_material,
        {"color": (0.235, 0.085, 0.050), "roughness": 0.58, "metallic": 0.35, "rib_pitch": 0.45},
    ),
    "container_b": (
        _metal_material,
        {"color": (0.070, 0.140, 0.170), "roughness": 0.58, "metallic": 0.35, "rib_pitch": 0.45},
    ),
    "container_c": (
        _metal_material,
        {"color": (0.095, 0.120, 0.070), "roughness": 0.58, "metallic": 0.35, "rib_pitch": 0.45},
    ),
}
"""Every family material: role key -> (builder, benchmark construction kwargs).

The benchmark (style ``a``) values here ARE the reviewed Phase 15 look; a
style profile may override individual kwargs per role, never the set of
roles, so all styles keep the identical material inventory over the
identical world.
"""

assert set(MATERIAL_SPECS) == set(MATERIAL_ROLES), (
    "MATERIAL_SPECS and style_profiles.MATERIAL_ROLES disagree"
)


def build_material_family(
    overrides: dict[str, dict] | None = None,
) -> dict[str, bpy.types.Material]:
    """Create the controlled Phase 15 material family, keyed by role.

    ``overrides`` (from a style profile) merges per-role construction kwargs
    over the benchmark values; unknown roles or kwargs are refused loudly so
    a typo in a profile can never silently do nothing.
    """
    overrides = overrides or {}
    unknown = set(overrides) - set(MATERIAL_SPECS)
    if unknown:
        raise KeyError(f"style overrides reference unknown material roles: {sorted(unknown)}")
    family: dict[str, bpy.types.Material] = {}
    for role, (builder, base_kwargs) in MATERIAL_SPECS.items():
        kwargs = dict(base_kwargs)
        kwargs.update(overrides.get(role, {}))
        family[role] = builder(f"LD_MAT__{role}", **kwargs)
    return family


__all__ = [
    "CHILD_COLLECTIONS",
    "MASS_MATERIAL_SLOTS",
    "MATERIAL_SPECS",
    "ROOT_COLLECTION",
    "WINDOW_CELL_UV",
    "FacadeStyle",
    "add_bevel",
    "build_material_family",
    "set_practical_light_scale",
    "distance_to_polyline",
    "ensure_collections",
    "link_only",
    "look_at_rotation",
    "make_box",
    "make_cylinder",
    "make_detail_mesh",
    "make_light",
    "make_ribbon",
    "make_torus",
    "make_windowed_mass",
    "polyline_stations",
    "purge_orphans",
    "remove_factory_defaults",
    "replace_object",
    "require_supported_blender",
    "stable_rng",
    "wipe_ld_collections",
]
