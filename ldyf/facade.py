"""``facade_spec_v1``: a procedural building-facade material, as a node-graph
specification.

Pure Python (stdlib only) -- no ``import unreal``, on purpose.  This module
*describes* the material graph (nodes, connections, parameter names); a thin
editor module executes it against Unreal's ``MaterialEditingLibrary``, which is
what makes the graph unit-testable without an editor.  See
``ldyf/unreal/ldyf_dressing_editor.py::ensure_paint_materials`` for the editor
calling convention this spec was written against:

* expressions are created with
  ``mel.create_material_expression(material, <ExpressionClass>, x, y)`` -- so
  each node's ``class`` is the exact Unreal expression class name;
* ``set_editor_property("parameter_name", ...)`` /
  ``set_editor_property("default_value", ...)`` -- so ``ScalarParameter`` and
  ``VectorParameter`` nodes carry ``parameter_name`` and ``default_value``;
* connecting an expression's single unnamed output to a material property is
  ``mel.connect_material_property(expr, "", MP_*)`` -- the ``""`` there is the
  real single unnamed pin, and the same convention is used here for every
  single-input / single-output expression (``Frac``, ``Abs``, ``Saturate``,
  ``ComponentMask`` input, ``WorldPosition`` output, parameter outputs);
* multi-input expressions use Unreal's real named pins ``A``, ``B`` and, for
  ``MaterialExpressionLinearInterpolate``, ``Alpha``.

Why world position, not UVs
---------------------------
The Phase 2 buildings are PCG extrusions whose UVs are unknown and
inconsistent, so the window grid is driven from world space:

    h = (WorldPosition.X + WorldPosition.Y) / spacing_h_cm
    v = WorldPosition.Z / spacing_v_cm

For an axis-aligned wall one of X or Y is constant, so ``X + Y`` varies along
the wall whichever way it faces, and ``spacing_h_cm`` becomes a real
architectural bay width in centimetres.  Caveat: on a wall rotated 45 degrees
the plane is ``X + Y = const``, so ``h`` stops varying along the wall and the
horizontal repetition degenerates (the whole wall shares one bay column).  Our
blocks are axis-aligned, so this never bites, but the formula is not general.

Mask and outputs (the dictated design, implemented exactly)::

    mask  = saturate((win_w - abs(frac(h) - 0.5)) * K)
          * saturate((win_h - abs(frac(v) - 0.5)) * K)
    BaseColor = lerp(WallColor,  WindowColor,  mask)
    Roughness = lerp(wall_rough, window_rough, mask)
    Metallic  = lerp(0,          window_metal, mask)

Every tunable is a ``ScalarParameter``/``VectorParameter`` with a stable
``parameter_name`` so three building kits can share one master material and
differ only through material instances.  Below ``ground_floor_cm`` (absolute
world Z) the mask is replaced by a shopfront value instead of the window grid:
a sharp step ``saturate((ground_floor_cm - Z) * 100)`` selects
``lerp(window_grid_mask, shopfront_mask, step)``.

props -> Unreal editor property mapping the executing module must apply
-----------------------------------------------------------------------
* ``ScalarParameter``:  ``parameter_name`` -> ``parameter_name``,
  ``default_value`` -> ``default_value`` (float).
* ``VectorParameter``: ``parameter_name`` -> ``parameter_name``,
  ``default_value`` -> ``default_value`` (list of 3 floats ->
  ``unreal.LinearColor``).
* ``ComponentMask``:   ``r``/``g``/``b`` -> ``r``/``g``/``b`` booleans.
* ``Constant``:        ``R`` -> ``R`` (the Unreal constant's single value).

The returned dicts are JSON-serialisable (vector defaults are lists, never
tuples), matching how the rest of ``ldyf`` stores its specs.
"""
from __future__ import annotations

# Stable parameter names shared by the master material and every kit instance.
P_SPACING_H = "FacadeSpacingH"
P_SPACING_V = "FacadeFloorHeight"
P_WIN_W = "FacadeWindowW"
P_WIN_H = "FacadeWindowH"
P_EDGE = "FacadeEdgeSharpness"
P_GROUND = "FacadeGroundFloorCm"
P_WALL_ROUGH = "FacadeWallRoughness"
P_WIN_ROUGH = "FacadeWindowRoughness"
P_WIN_METAL = "FacadeWindowMetallic"
P_SHOPFRONT = "FacadeShopfrontMask"
P_WALL_COL = "FacadeWallColor"
P_WIN_COL = "FacadeWindowColor"

SCALAR_PARAMETER_NAMES = (P_SPACING_H, P_SPACING_V, P_WIN_W, P_WIN_H, P_EDGE,
                          P_GROUND, P_WALL_ROUGH, P_WIN_ROUGH, P_WIN_METAL,
                          P_SHOPFRONT)
VECTOR_PARAMETER_NAMES = (P_WALL_COL, P_WIN_COL)
PARAMETER_NAMES = SCALAR_PARAMETER_NAMES + VECTOR_PARAMETER_NAMES

FACADE_SPEC_VERSION = "facade_spec_v1"

# Master-material (non-instance) fallbacks; kits override these per instance.
MASTER_DEFAULTS = {
    P_SPACING_H: 320.0,
    P_SPACING_V: 340.0,
    P_WIN_W: 0.30,
    P_WIN_H: 0.52,
    P_EDGE: 60.0,
    P_GROUND: 400.0,
    P_WALL_ROUGH: 0.85,
    P_WIN_ROUGH: 0.10,
    P_WIN_METAL: 0.55,
    P_SHOPFRONT: 0.90,
    P_WALL_COL: (0.45, 0.42, 0.38),   # master fallback; never a kit colour
    P_WIN_COL: (0.05, 0.08, 0.10),
}

_GROUND_STEP_K = 100.0   # 1 cm transition at the shopfront/upper-wall boundary
_HALF = 0.5
_ZERO = 0.0

# Expression class names exactly as Unreal spells them.
_WORLD_POS = "MaterialExpressionWorldPosition"
_MASK = "MaterialExpressionComponentMask"
_ADD = "MaterialExpressionAdd"
_DIV = "MaterialExpressionDivide"
_FRAC = "MaterialExpressionFrac"
_SUB = "MaterialExpressionSubtract"
_ABS = "MaterialExpressionAbs"
_MUL = "MaterialExpressionMultiply"
_SAT = "MaterialExpressionSaturate"
_LERP = "MaterialExpressionLinearInterpolate"
_CONST = "MaterialExpressionConstant"
_SCALAR = "MaterialExpressionScalarParameter"
_VECTOR = "MaterialExpressionVectorParameter"

EXPRESSION_CLASSES = (_WORLD_POS, _MASK, _ADD, _DIV, _FRAC, _SUB, _ABS, _MUL,
                      _SAT, _LERP, _CONST, _SCALAR, _VECTOR)


def facade_graph(*, spacing_h_cm, spacing_v_cm, window_w, window_h,
                 edge_sharpness, ground_floor_cm) -> dict:
    """Return the node graph for one master facade material.

    Keyword args are the master material's parameter defaults in centimetres /
    fractions; kits override them later through material instances.  Returns
    ``{"schema_version", "params", "nodes", "connections", "outputs"}`` with
    deterministic ordering (two calls produce identical dicts).
    """
    params = dict(MASTER_DEFAULTS)
    params.update({
        P_SPACING_H: float(spacing_h_cm),
        P_SPACING_V: float(spacing_v_cm),
        P_WIN_W: float(window_w),
        P_WIN_H: float(window_h),
        P_EDGE: float(edge_sharpness),
        P_GROUND: float(ground_floor_cm),
    })
    # JSON-serialisable vector defaults (lists, not tuples).
    for name in VECTOR_PARAMETER_NAMES:
        params[name] = list(params[name])

    _col = {}

    def _xy(x):
        y = _col.get(x, 0) * 80.0
        _col[x] = _col.get(x, 0) + 1
        return float(x), y

    nodes = []
    connections = []

    def add(nid, cls, props=None, x=0.0):
        px, py = _xy(x)
        nodes.append({"id": nid, "class": cls, "props": dict(props or {}),
                      "x": px, "y": py})
        return nid

    def link(frm, to, to_input, from_output=""):
        connections.append({"from": frm, "from_output": from_output,
                            "to": to, "to_input": to_input})

    # --- raw inputs (x = 0): world position, every parameter, every constant
    add("wp", _WORLD_POS)
    add("spacing_h", _SCALAR, {"parameter_name": P_SPACING_H,
                               "default_value": params[P_SPACING_H]})
    add("spacing_v", _SCALAR, {"parameter_name": P_SPACING_V,
                               "default_value": params[P_SPACING_V]})
    add("win_w", _SCALAR, {"parameter_name": P_WIN_W,
                           "default_value": params[P_WIN_W]})
    add("win_h", _SCALAR, {"parameter_name": P_WIN_H,
                           "default_value": params[P_WIN_H]})
    add("edge", _SCALAR, {"parameter_name": P_EDGE,
                          "default_value": params[P_EDGE]})
    add("ground_cm", _SCALAR, {"parameter_name": P_GROUND,
                               "default_value": params[P_GROUND]})
    add("wall_col", _VECTOR, {"parameter_name": P_WALL_COL,
                              "default_value": params[P_WALL_COL]})
    add("win_col", _VECTOR, {"parameter_name": P_WIN_COL,
                             "default_value": params[P_WIN_COL]})
    add("wall_rough", _SCALAR, {"parameter_name": P_WALL_ROUGH,
                                "default_value": params[P_WALL_ROUGH]})
    add("win_rough", _SCALAR, {"parameter_name": P_WIN_ROUGH,
                               "default_value": params[P_WIN_ROUGH]})
    add("win_metal", _SCALAR, {"parameter_name": P_WIN_METAL,
                               "default_value": params[P_WIN_METAL]})
    add("shopfront", _SCALAR, {"parameter_name": P_SHOPFRONT,
                               "default_value": params[P_SHOPFRONT]})
    add("half", _CONST, {"R": _HALF})
    add("zero", _CONST, {"R": _ZERO})
    add("ground_step", _CONST, {"R": _GROUND_STEP_K})

    # --- channel splits: X, Y, Z from WorldPosition (single unnamed input)
    add("wx", _MASK, {"r": True}, x=200.0)
    add("wy", _MASK, {"g": True}, x=200.0)
    add("wz", _MASK, {"b": True}, x=200.0)
    link("wp", "wx", "")
    link("wp", "wy", "")
    link("wp", "wz", "")

    # --- horizontal bay: h = (X + Y) / spacing_h
    add("sum_xy", _ADD, x=400.0)
    add("div_h", _DIV, x=600.0)
    add("frac_h", _FRAC, x=800.0)
    add("sub_h", _SUB, x=1000.0)      # frac(h) - 0.5
    add("abs_h", _ABS, x=1200.0)
    add("open_h", _SUB, x=1400.0)     # win_w - abs(frac(h) - 0.5)
    add("mul_h", _MUL, x=1600.0)
    add("sat_h", _SAT, x=1800.0)
    link("wx", "sum_xy", "A")
    link("wy", "sum_xy", "B")
    link("sum_xy", "div_h", "A")
    link("spacing_h", "div_h", "B")
    link("div_h", "frac_h", "")
    link("frac_h", "sub_h", "A")
    link("half", "sub_h", "B")
    link("sub_h", "abs_h", "")
    link("win_w", "open_h", "A")
    link("abs_h", "open_h", "B")
    link("open_h", "mul_h", "A")
    link("edge", "mul_h", "B")
    link("mul_h", "sat_h", "")

    # --- vertical floor: v = Z / spacing_v
    add("div_v", _DIV, x=600.0)
    add("frac_v", _FRAC, x=800.0)
    add("sub_v", _SUB, x=1000.0)      # frac(v) - 0.5
    add("abs_v", _ABS, x=1200.0)
    add("open_v", _SUB, x=1400.0)     # win_h - abs(frac(v) - 0.5)
    add("mul_v", _MUL, x=1600.0)
    add("sat_v", _SAT, x=1800.0)
    link("wz", "div_v", "A")
    link("spacing_v", "div_v", "B")
    link("div_v", "frac_v", "")
    link("frac_v", "sub_v", "A")
    link("half", "sub_v", "B")
    link("sub_v", "abs_v", "")
    link("win_h", "open_v", "A")
    link("abs_v", "open_v", "B")
    link("open_v", "mul_v", "A")
    link("edge", "mul_v", "B")
    link("mul_v", "sat_v", "")

    # --- window grid mask = sat_h * sat_v
    add("grid_mask", _MUL, x=2000.0)
    link("sat_h", "grid_mask", "A")
    link("sat_v", "grid_mask", "B")

    # --- ground-floor shopfront band: step = saturate((ground - Z) * 100)
    add("below_ground", _SUB, x=400.0)
    add("ground_mul", _MUL, x=600.0)
    add("ground_band", _SAT, x=800.0)
    link("ground_cm", "below_ground", "A")
    link("wz", "below_ground", "B")
    link("below_ground", "ground_mul", "A")
    link("ground_step", "ground_mul", "B")
    link("ground_mul", "ground_band", "")

    # --- final mask: grid above the ground floor, shopfront below it
    add("mask", _LERP, x=2400.0)
    link("grid_mask", "mask", "A")
    link("shopfront", "mask", "B")
    link("ground_band", "mask", "Alpha")

    # --- material outputs
    add("base_color", _LERP, x=2600.0)
    add("roughness", _LERP, x=2600.0)
    add("metallic", _LERP, x=2600.0)
    link("wall_col", "base_color", "A")
    link("win_col", "base_color", "B")
    link("mask", "base_color", "Alpha")
    link("wall_rough", "roughness", "A")
    link("win_rough", "roughness", "B")
    link("mask", "roughness", "Alpha")
    link("zero", "metallic", "A")
    link("win_metal", "metallic", "B")
    link("mask", "metallic", "Alpha")

    return {
        "schema_version": FACADE_SPEC_VERSION,
        "params": dict(params),
        "nodes": nodes,
        "connections": connections,
        "outputs": {"BaseColor": "base_color",
                    "Roughness": "roughness",
                    "Metallic": "metallic"},
    }


# --------------------------------------------------------------------------- kits

_KIT_SPECS = {
    # Chicago: dark red brick, wide loft bays, moderate floors.
    "CHA": {
        "wall_colour": (0.44, 0.17, 0.15),
        "window_colour": (0.07, 0.13, 0.20),
        "spacing_h_cm": 380.0, "spacing_v_cm": 330.0,
        "window_w": 0.30, "window_h": 0.50, "ground_floor_cm": 430.0,
        "wall_roughness": 0.92, "window_roughness": 0.08,
        "window_metallic": 0.60, "shopfront_mask": 0.90,
    },
    # New York: warm limestone, tall narrow windows, high floors.
    "NYA": {
        "wall_colour": (0.76, 0.71, 0.58),
        "window_colour": (0.10, 0.15, 0.18),
        "spacing_h_cm": 280.0, "spacing_v_cm": 370.0,
        "window_w": 0.22, "window_h": 0.62, "ground_floor_cm": 460.0,
        "wall_roughness": 0.72, "window_roughness": 0.12,
        "window_metallic": 0.35, "shopfront_mask": 0.95,
    },
    # San Francisco: pale teal, squat wide windows, low floors.
    "SFA": {
        "wall_colour": (0.55, 0.74, 0.71),
        "window_colour": (0.04, 0.06, 0.09),
        "spacing_h_cm": 340.0, "spacing_v_cm": 300.0,
        "window_w": 0.34, "window_h": 0.44, "ground_floor_cm": 390.0,
        "wall_roughness": 0.88, "window_roughness": 0.05,
        "window_metallic": 0.45, "shopfront_mask": 0.88,
    },
}


def kit_parameters(kit: str) -> dict:
    """Scalar/vector parameter overrides making one kit's material instance.

    Returns ``{"scalar": {parameter_name: float, ...},
    "vector": {parameter_name: [r, g, b], ...}}`` (lists, JSON-safe).
    Unknown kits raise ``ValueError``.
    """
    spec = _KIT_SPECS.get(kit)
    if spec is None:
        raise ValueError("unknown facade kit %r (expected one of %s)"
                         % (kit, ", ".join(sorted(_KIT_SPECS))))
    scalar = {
        P_SPACING_H: spec["spacing_h_cm"],
        P_SPACING_V: spec["spacing_v_cm"],
        P_WIN_W: spec["window_w"],
        P_WIN_H: spec["window_h"],
        P_GROUND: spec["ground_floor_cm"],
        P_WALL_ROUGH: spec["wall_roughness"],
        P_WIN_ROUGH: spec["window_roughness"],
        P_WIN_METAL: spec["window_metallic"],
        P_SHOPFRONT: spec["shopfront_mask"],
    }
    vector = {
        P_WALL_COL: list(spec["wall_colour"]),
        P_WIN_COL: list(spec["window_colour"]),
    }
    return {"scalar": scalar, "vector": vector}


# --------------------------------------------------------------------------- validation

def validate_graph(graph) -> list:
    """Return human-readable problems with ``graph``, [] when valid.

    Checks, in order: duplicate node ids; connections naming unknown nodes; a
    node with no directed path to any output; an output naming a missing node;
    a cycle among nodes.
    """
    problems = []
    nodes = graph.get("nodes", [])
    connections = graph.get("connections", [])
    outputs = graph.get("outputs", {})

    ids = [n.get("id") for n in nodes]
    seen = set()
    for nid in ids:
        if nid in seen:
            problems.append("node id %r used more than once" % (nid,))
        seen.add(nid)
    id_set = set(ids)

    for c in connections:
        for side in ("from", "to"):
            nid = c.get(side)
            if nid not in id_set:
                problems.append("connection %s names unknown node %r"
                                % (side, nid))

    out_edges = {nid: [] for nid in id_set}
    for c in connections:
        if c.get("from") in id_set and c.get("to") in id_set:
            out_edges[c["from"]].append(c["to"])

    output_values = set(outputs.values())
    for prop, nid in outputs.items():
        if nid not in id_set:
            problems.append("output %r names unknown node %r" % (prop, nid))

    # Nodes with no path to any output: walk downstream from each node.
    for start in ids:
        hit = start in output_values
        visited = set()
        stack = [start]
        while stack and not hit:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            for nxt in out_edges.get(cur, ()):
                if nxt in output_values:
                    hit = True
                    break
                stack.append(nxt)
        if not hit:
            problems.append("node %r has no path to any output" % (start,))

    # Cycles: three-colour DFS over data-flow edges.
    colour = {}

    def _dfs(nid):
        colour[nid] = 1
        for nxt in out_edges.get(nid, ()):
            if colour.get(nxt) == 1:
                problems.append("cycle detected involving node %r" % (nxt,))
            elif colour.get(nxt) is None:
                _dfs(nxt)
        colour[nid] = 2

    for nid in id_set:
        if colour.get(nid) is None:
            _dfs(nid)

    return problems
