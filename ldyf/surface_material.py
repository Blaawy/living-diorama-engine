"""``surface_spec_v1`` — a plain PBR surface material, as a node-graph spec.

Why this exists
---------------
The ground and sidewalk instances were children of City Sample's
``MS_DefaultMaterial``, and the editor logs it as **"Failed to compile Material
... Missing Material Function"**. A material that fails to compile falls back to
error shading, and that fallback is what the block-interior speckle actually is:
no albedo, normal, roughness or tiling change moved it; hiding the mesh showed
nothing z-fighting beneath it; and the same speckle appears on every surface
that material parents.

Chasing the missing functions through the vault cost a 29.8 GB import that had
to be rolled back, and the editor will not expose a material's expressions to
Python (``Expressions`` is protected), so the missing names cannot be read
directly. The engineering answer is to stop depending on a third-party material
this project can neither compile nor inspect, and author the surface itself —
exactly as the road paint and the building facades already are.

The graph
---------
::

    uv        = WorldPosition.xy / TilingCm
    BaseColor = TextureSample(Albedo, uv) * Tint
    Normal    = TextureSample(NormalMap, uv)
    Roughness = TextureSample(RoughnessMap, uv) * RoughnessScale
    Specular  = SpecularScale

World-aligned UVs matter here: the ground is one very large polygon whose own
UVs span the whole city, which is why every tiling value tried on the old
material produced sub-pixel noise. Driving UVs from world position makes
``TilingCm`` mean "one texture repeat every N centimetres", which is a real
dimension a reviewer can check against the frame.
"""

from __future__ import annotations

SURFACE_SPEC_VERSION = "surface_spec_v1"

P_TILING = "SurfaceTilingCm"
P_TINT = "SurfaceTint"
P_ROUGH = "SurfaceRoughnessScale"
P_SPEC = "SurfaceSpecular"
T_ALBEDO = "Albedo"
T_NORMAL = "NormalMap"
T_ROUGH = "RoughnessMap"

SCALAR_PARAMETER_NAMES = (P_TILING, P_ROUGH, P_SPEC)
VECTOR_PARAMETER_NAMES = (P_TINT,)
TEXTURE_PARAMETER_NAMES = (T_ALBEDO, T_NORMAL, T_ROUGH)

MASTER_DEFAULTS = {
    P_TILING: 400.0,          # one texture repeat every 4 metres
    P_ROUGH: 1.0,
    P_SPEC: 0.35,
    P_TINT: (1.0, 1.0, 1.0),
}

_WORLD_POS = "MaterialExpressionWorldPosition"
_MASK = "MaterialExpressionComponentMask"
_DIV = "MaterialExpressionDivide"
_MUL = "MaterialExpressionMultiply"
_SCALAR = "MaterialExpressionScalarParameter"
_VECTOR = "MaterialExpressionVectorParameter"
_TEXPARAM = "MaterialExpressionTextureSampleParameter2D"


def surface_graph(*, tiling_cm: float = MASTER_DEFAULTS[P_TILING],
                  roughness_scale: float = MASTER_DEFAULTS[P_ROUGH],
                  specular: float = MASTER_DEFAULTS[P_SPEC]) -> dict:
    """The node graph for one master surface material."""
    if tiling_cm <= 0.0:
        raise ValueError("tiling_cm must be > 0, got %r" % (tiling_cm,))
    if roughness_scale < 0.0:
        raise ValueError("roughness_scale must be >= 0, got %r" % (roughness_scale,))
    nodes: list = []
    conns: list = []

    def add(nid, cls, props=None, x=0.0, y=0.0):
        nodes.append({"id": nid, "class": cls, "props": dict(props or {}),
                      "x": float(x), "y": float(y)})
        return nid

    def link(frm, to, to_input, from_output=""):
        conns.append({"from": frm, "from_output": from_output,
                      "to": to, "to_input": to_input})

    add("wp", _WORLD_POS, x=-900, y=0)
    # Every channel is stated explicitly. Unreal's ComponentMask defaults to
    # R+G checked, and relying on that default once made an entire facade
    # render as one flat colour.
    add("uv_xy", _MASK, {"r": True, "g": True, "b": False, "a": False}, x=-720, y=0)
    add("tiling", _SCALAR, {"parameter_name": P_TILING,
                            "default_value": float(tiling_cm)}, x=-720, y=140)
    add("uv", _DIV, x=-540, y=0)
    link("wp", "uv_xy", "")
    link("uv_xy", "uv", "A")
    link("tiling", "uv", "B")

    for nid, pname, y in (("alb", T_ALBEDO, -160), ("nrm", T_NORMAL, 40),
                          ("rgh", T_ROUGH, 240)):
        add(nid, _TEXPARAM, {"parameter_name": pname}, x=-360, y=y)
        link("uv", nid, "UVs")

    add("tint", _VECTOR, {"parameter_name": P_TINT,
                          "default_value": list(MASTER_DEFAULTS[P_TINT])},
        x=-360, y=-320)
    add("base", _MUL, x=-160, y=-240)
    link("alb", "base", "A")
    link("tint", "base", "B")

    add("rough_scale", _SCALAR, {"parameter_name": P_ROUGH,
                                 "default_value": float(roughness_scale)},
        x=-360, y=380)
    add("rough", _MUL, x=-160, y=280)
    link("rgh", "rough", "A")
    link("rough_scale", "rough", "B")

    add("spec", _SCALAR, {"parameter_name": P_SPEC,
                          "default_value": float(specular)}, x=-160, y=460)

    return {
        "schema_version": SURFACE_SPEC_VERSION,
        "params": {P_TILING: float(tiling_cm), P_ROUGH: float(roughness_scale),
                   P_SPEC: float(specular), P_TINT: list(MASTER_DEFAULTS[P_TINT])},
        "nodes": nodes,
        "connections": conns,
        "outputs": {"BaseColor": "base", "Normal": "nrm",
                    "Roughness": "rough", "Specular": "spec"},
    }


def validate_graph(graph: dict) -> list:
    """Problems with a surface graph; an empty list means valid."""
    problems: list = []
    ids = [n["id"] for n in graph.get("nodes", [])]
    if len(ids) != len(set(ids)):
        problems.append("duplicate node id")
    known = set(ids)
    for c in graph.get("connections", []):
        if c["from"] not in known:
            problems.append("connection from unknown node %s" % c["from"])
        if c["to"] not in known:
            problems.append("connection to unknown node %s" % c["to"])
    for prop, nid in (graph.get("outputs") or {}).items():
        if nid not in known:
            problems.append("output %s names unknown node %s" % (prop, nid))
    incoming: dict = {}
    for c in graph.get("connections", []):
        incoming.setdefault(c["to"], set()).add(c["from"])
    reach: set = set()
    stack = list((graph.get("outputs") or {}).values())
    while stack:
        n = stack.pop()
        if n in reach:
            continue
        reach.add(n)
        stack.extend(incoming.get(n, ()))
    for n in ids:
        if n not in reach:
            problems.append("node %s cannot reach any output" % n)
    return problems


# --------------------------------------------------------------------------- foliage

FOLIAGE_MASTER_DEFAULTS = {
    "FoliageOpacityClip": 0.33,
    "FoliageRoughness": 0.65,
    "FoliageSpecular": 0.25,
}
T_FOLIAGE = "FoliageColorAlpha"


def foliage_graph(*, roughness: float = FOLIAGE_MASTER_DEFAULTS["FoliageRoughness"],
                  specular: float = FOLIAGE_MASTER_DEFAULTS["FoliageSpecular"]) -> dict:
    """A masked, two-sided leaf material.

    The Megaplants trees ship with their own foliage material. It compiles
    without error and its textures resolve, yet the leaf sections render
    nothing: bare bark on every variant from a 41k-triangle sapling to a 135k
    beech, with Nanite on and with Nanite off. Whatever drives its opacity mask
    evaluates to zero in this project, and Unreal will not expose a Material's
    expressions to Python so it cannot be inspected.

    So the leaf material is authored here instead, the same way the ground
    surface was after MS_DefaultMaterial turned out never to compile. Megascans
    plant textures pack colour in RGB and the leaf cutout in ALPHA of a single
    ``_CA`` map, so one sampler feeds both BaseColor and OpacityMask.

    ``material_properties`` in the returned document are engine properties the
    executor sets on the Material itself rather than graph nodes: a leaf card
    needs BLEND_MASKED (so the cutout applies at all) and two-sided rendering
    (so a card is not invisible from behind).
    """
    if roughness < 0.0:
        raise ValueError("roughness must be >= 0, got %r" % (roughness,))
    nodes, conns = [], []

    def add(nid, cls, props=None, x=0.0, y=0.0):
        nodes.append({"id": nid, "class": cls, "props": dict(props or {}),
                      "x": float(x), "y": float(y)})

    def link(frm, to, to_input, from_output=""):
        conns.append({"from": frm, "from_output": from_output,
                      "to": to, "to_input": to_input})

    add("ca", _TEXPARAM, {"parameter_name": T_FOLIAGE}, x=-500, y=0)
    add("rough", _SCALAR, {"parameter_name": "FoliageRoughness",
                           "default_value": float(roughness)}, x=-500, y=260)
    add("spec", _SCALAR, {"parameter_name": "FoliageSpecular",
                          "default_value": float(specular)}, x=-500, y=360)
    return {
        "schema_version": SURFACE_SPEC_VERSION,
        "params": {"FoliageRoughness": float(roughness),
                   "FoliageSpecular": float(specular)},
        "nodes": nodes, "connections": conns,
        # RGB of the sampler drives colour; its ALPHA drives the cutout
        "outputs": {"BaseColor": "ca", "Roughness": "rough", "Specular": "spec"},
        "output_pins": {"BaseColor": "RGB", "OpacityMask": "A"},
        "opacity_mask_from": "ca",
        "material_properties": {
            "blend_mode": "BLEND_MASKED",
            "two_sided": True,
            "opacity_mask_clip_value": FOLIAGE_MASTER_DEFAULTS["FoliageOpacityClip"],
        },
    }
