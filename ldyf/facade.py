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

    grid_mask = saturate((win_w - abs(frac(h) - 0.5)) * K)
              * saturate((win_h - abs(frac(v) - 0.5)) * K)

Windows must appear on walls only, so the grid is gated by the surface
orientation.  A wall's vertex normal is near-horizontal (``abs(normal.z)`` near
0); a roof or pavement is a horizontal surface with ``abs(normal.z)`` near 1::

    wall_mask = saturate((FacadeWallNormalMaxZ - abs(normal.z))
                         * FacadeOrientSharpness)

The roof is selected by the *complement* of the same orientation term, so the
two branches share one threshold and one sharpness and the wall/roof boundary
is exactly complementary::

    roof_mask = saturate((abs(normal.z) - FacadeWallNormalMaxZ)
                         * FacadeOrientSharpness)

A roof therefore does not merely lose its windows (``wall_mask == 0`` zeroes
the glazing) -- it reads as a roof, through its own ``FacadeRoofTint`` colour
and ``FacadeRoofRoughness``:

    BaseColor = lerp(lerp(FacadeWallColor, FacadeRoofTint, roof_mask),
                     FacadeWindowColor, mask)
    Roughness = lerp(lerp(wall_rough, FacadeRoofRoughness, roof_mask),
                     window_rough, mask)

Ground floor (absolute world Z below ``FacadeGroundFloorCm``) reads as a
shopfront instead of the same small windows: a separate, wider window grid with
no vertical division (one tall pane per bay),

    shop_grid = saturate((FacadeShopWindowW - abs(frac(h) - 0.5)) * K)

selected by a sharp step ``saturate((ground_floor_cm - Z) * 100)``, plus a dark
spandrel strip of height ``FacadeBandCm`` immediately above the ground floor
(``saturate((Z - ground) * 100) * saturate((ground + band - Z) * 100)``) that
visually separates the shopfront from the storeys:

    glazing = lerp(lerp(grid_mask, shop_grid, below_ground_step),
                   one, spandrel_strip)
    mask    = glazing * wall_mask
    BaseColor  = lerp(lerp(WallColor, RoofTint, roof_mask),
                      WindowColor, mask)
    Roughness  = lerp(lerp(wall_rough, RoofRoughness, roof_mask),
                      window_rough, mask)
    Metallic   = lerp(0,          window_metal, mask)

Every tunable is a ``ScalarParameter``/``VectorParameter`` with a stable
``parameter_name`` so three building kits can share one master material and
differ only through material instances.  Names are part of the contract: bay
and floor spacings are *centimetre* quantities and carry the ``-Cm`` suffix
(``FacadeSpacingHCm``, ``FacadeSpacingVCm``) exactly like ``FacadeGroundFloorCm``;
window widths/heights are fractions of a bay and carry no suffix
(``FacadeWindowW``, ``FacadeWindowH``).  The material instances that the live
render reads back are queried by these names, so a graph parameter created
under any other name silently reads back as 0.0 (Unreal's value for a scalar
parameter that does not exist on the material) -- which is how an otherwise
real spacing can look zeroed in the editor.

Spec, oracle and validation
---------------------------
``facade_graph()`` returns ``{"schema_version", "params", "nodes",
"connections", "outputs"}``; its ``params`` dict is the spec used by the two
pure functions below:

* ``evaluate_masks(spec, x_cm, y_cm, z_cm, normal)`` re-runs the graph's mask
  arithmetic in Python (node id per formula is named in its docstring), so a
  mask regression is caught by a unit test, not by looking at a render;
* ``validate_spec(spec)`` refuses a spec that carries ``0.0`` for
  ``FacadeOrientSharpness``, ``FacadeSpacingHCm`` or ``FacadeSpacingVCm``.
  All three have documented non-zero ``MASTER_DEFAULTS`` below; a spacing of 0
  is a divide by zero in ``h``/``v`` and a sharpness of 0 makes both
  orientation masks constant, so either value would silently destroy the image.

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
# Bay/floor spacings are centimetre quantities (the ``-Cm`` suffix matches the
# live material instance reads in the editor); window fractions carry none.
P_SPACING_H = "FacadeSpacingHCm"
P_SPACING_V = "FacadeSpacingVCm"
P_WIN_W = "FacadeWindowW"
P_WIN_H = "FacadeWindowH"
P_EDGE = "FacadeEdgeSharpness"
P_GROUND = "FacadeGroundFloorCm"
P_SHOP_WIN_W = "FacadeShopWindowW"
P_BAND = "FacadeBandCm"
P_ORIENT_MAX_Z = "FacadeWallNormalMaxZ"
P_ORIENT_SHARP = "FacadeOrientSharpness"
P_WALL_ROUGH = "FacadeWallRoughness"
P_WIN_ROUGH = "FacadeWindowRoughness"
P_WIN_METAL = "FacadeWindowMetallic"
P_ROOF_ROUGH = "FacadeRoofRoughness"
P_WALL_COL = "FacadeWallColor"
P_WIN_COL = "FacadeWindowColor"
P_ROOF_TINT = "FacadeRoofTint"

SCALAR_PARAMETER_NAMES = (P_SPACING_H, P_SPACING_V, P_WIN_W, P_WIN_H, P_EDGE,
                          P_GROUND, P_SHOP_WIN_W, P_BAND, P_ORIENT_MAX_Z,
                          P_ORIENT_SHARP, P_WALL_ROUGH, P_WIN_ROUGH,
                          P_WIN_METAL, P_ROOF_ROUGH)
VECTOR_PARAMETER_NAMES = (P_WALL_COL, P_WIN_COL, P_ROOF_TINT)
PARAMETER_NAMES = SCALAR_PARAMETER_NAMES + VECTOR_PARAMETER_NAMES

FACADE_SPEC_VERSION = "facade_spec_v1"

# Master-material (non-instance) fallbacks; kits override these per instance.
# FacadeSpacingHCm / FacadeSpacingVCm / FacadeOrientSharpness defaults are
# deliberately non-zero -- validate_spec() refuses a 0.0 for any of them.
MASTER_DEFAULTS = {
    P_SPACING_H: 320.0,
    P_SPACING_V: 340.0,
    P_WIN_W: 0.30,
    P_WIN_H: 0.52,
    P_EDGE: 60.0,
    P_GROUND: 400.0,
    P_SHOP_WIN_W: 0.42,     # wide shop pane (half-width); one pane, no mullions
    P_BAND: 40.0,           # dark spandrel strip above the ground floor
    P_ORIENT_MAX_Z: 0.5,    # |normal.z| below this reads as a wall
    P_ORIENT_SHARP: 8.0,    # wall/roof transition sharpness (never 0)
    P_WALL_ROUGH: 0.85,
    P_WIN_ROUGH: 0.10,
    P_WIN_METAL: 0.55,
    P_ROOF_ROUGH: 0.90,     # roof branch roughness (separate from the wall)
    P_WALL_COL: (0.45, 0.42, 0.38),   # master fallback; never a kit colour
    P_WIN_COL: (0.05, 0.08, 0.10),
    P_ROOF_TINT: (0.21, 0.23, 0.27),  # slate roof tint, distinct from wall/window
}

_GROUND_STEP_K = 100.0   # 1 cm transition at the shopfront/upper-wall boundary
_HALF = 0.5
_ZERO = 0.0
_ONE = 1.0

# Expression class names exactly as Unreal spells them.
_WORLD_POS = "MaterialExpressionWorldPosition"
_NORMAL_WS = "MaterialExpressionVertexNormalWS"
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

EXPRESSION_CLASSES = (_WORLD_POS, _NORMAL_WS, _MASK, _ADD, _DIV, _FRAC, _SUB,
                      _ABS, _MUL, _SAT, _LERP, _CONST, _SCALAR, _VECTOR)


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

    # --- raw inputs (x = 0): world position, vertex normal, parameters, consts
    add("wp", _WORLD_POS)
    add("vn", _NORMAL_WS)
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
    add("shop_win_w", _SCALAR, {"parameter_name": P_SHOP_WIN_W,
                                "default_value": params[P_SHOP_WIN_W]})
    add("band_cm", _SCALAR, {"parameter_name": P_BAND,
                             "default_value": params[P_BAND]})
    add("norm_maxz", _SCALAR, {"parameter_name": P_ORIENT_MAX_Z,
                               "default_value": params[P_ORIENT_MAX_Z]})
    add("orient_sharp", _SCALAR, {"parameter_name": P_ORIENT_SHARP,
                                  "default_value": params[P_ORIENT_SHARP]})
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
    add("roof_tint", _VECTOR, {"parameter_name": P_ROOF_TINT,
                               "default_value": params[P_ROOF_TINT]})
    add("roof_rough", _SCALAR, {"parameter_name": P_ROOF_ROUGH,
                                "default_value": params[P_ROOF_ROUGH]})
    add("half", _CONST, {"R": _HALF})
    add("zero", _CONST, {"R": _ZERO})
    add("one", _CONST, {"R": _ONE})
    add("ground_step", _CONST, {"R": _GROUND_STEP_K})

    # --- channel splits: X, Y, Z from WorldPosition, Z from the vertex normal.
    # Every channel is stated explicitly, including the ones being turned OFF.
    # Unreal's ComponentMask defaults to R+G checked, so setting only ``r``
    # leaves ``g`` on and the node yields the two-component vector (X, Y)
    # instead of the scalar X the arithmetic below needs. That is not
    # hypothetical: the first build of this material rendered every facade as
    # one flat colour precisely because ``wx`` was really (X, Y).
    add("wx", _MASK, {"r": True, "g": False, "b": False, "a": False}, x=200.0)
    add("wy", _MASK, {"r": False, "g": True, "b": False, "a": False}, x=200.0)
    add("wz", _MASK, {"r": False, "g": False, "b": True, "a": False}, x=200.0)
    add("vnz", _MASK, {"r": False, "g": False, "b": True, "a": False}, x=200.0)
    link("wp", "wx", "")
    link("wp", "wy", "")
    link("wp", "wz", "")
    link("vn", "vnz", "")

    # --- orientation wall mask: wall_mask = saturate((max_z - |normal.z|)
    #                                               * sharpness)
    # A wall has |normal.z| near 0 (horizontal normal); a roof/pavement is a
    # horizontal surface with |normal.z| near 1.  abs(normal.z) is the
    # discriminant: subtract it from FacadeWallNormalMaxZ, scale by the
    # sharpness and saturate -- walls land at 1, roofs at 0.
    add("abs_nz", _ABS, x=400.0)
    add("orient_sub", _SUB, x=600.0)
    add("orient_mul", _MUL, x=800.0)
    add("wall_mask", _SAT, x=1000.0)
    link("vnz", "abs_nz", "")
    link("norm_maxz", "orient_sub", "A")
    link("abs_nz", "orient_sub", "B")
    link("orient_sub", "orient_mul", "A")
    link("orient_sharp", "orient_mul", "B")
    link("orient_mul", "wall_mask", "")

    # --- orientation roof mask: roof_mask = saturate((|normal.z| - max_z)
    #                                                * sharpness)
    # The exact complement of the wall mask, built on the same abs(normal.z)
    # and the same FacadeOrientSharpness term, so every surface is classified
    # wall or roof and the transition is as sharp as the wall one.  A roof then
    # reads as FacadeRoofTint / FacadeRoofRoughness instead of plain wall.
    add("roof_sub", _SUB, x=600.0)      # |normal.z| - max_z
    add("roof_mul", _MUL, x=800.0)
    add("roof_mask", _SAT, x=1000.0)
    link("abs_nz", "roof_sub", "A")
    link("norm_maxz", "roof_sub", "B")
    link("roof_sub", "roof_mul", "A")
    link("orient_sharp", "roof_mul", "B")
    link("roof_mul", "roof_mask", "")

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

    # --- shopfront pane: same bay columns (reuse abs_h), wider opening and NO
    # vertical division -- a shopfront is one tall pane, not small windows.
    add("shop_open", _SUB, x=1400.0)  # shop_win_w - abs(frac(h) - 0.5)
    add("shop_mul", _MUL, x=1600.0)
    add("shop_sat", _SAT, x=1800.0)
    link("shop_win_w", "shop_open", "A")
    link("abs_h", "shop_open", "B")
    link("shop_open", "shop_mul", "A")
    link("edge", "shop_mul", "B")
    link("shop_mul", "shop_sat", "")

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

    # --- storey window grid mask = sat_h * sat_v (small, repeated windows)
    add("grid_mask", _MUL, x=2000.0)
    link("sat_h", "grid_mask", "A")
    link("sat_v", "grid_mask", "B")

    # --- ground-floor selection: step = saturate((ground - Z) * 100),
    # 1 below FacadeGroundFloorCm (the shopfront), 0 above it.
    add("below_ground", _SUB, x=400.0)
    add("ground_mul", _MUL, x=600.0)
    add("ground_band", _SAT, x=800.0)
    link("ground_cm", "below_ground", "A")
    link("wz", "below_ground", "B")
    link("below_ground", "ground_mul", "A")
    link("ground_step", "ground_mul", "B")
    link("ground_mul", "ground_band", "")

    # --- spandrel strip: 1 only for ground < Z < ground + FacadeBandCm, the
    # dark band that visually separates the shopfront from the storeys above.
    add("ground_plus", _ADD, x=400.0)
    add("sp_above", _SUB, x=600.0)          # Z - ground
    add("sp_above_mul", _MUL, x=800.0)
    add("sp_above_sat", _SAT, x=1000.0)
    add("sp_below_edge", _SUB, x=600.0)     # (ground + band) - Z
    add("sp_below_mul", _MUL, x=800.0)
    add("sp_below_sat", _SAT, x=1000.0)
    add("spandrel", _MUL, x=1200.0)
    link("ground_cm", "ground_plus", "A")
    link("band_cm", "ground_plus", "B")
    link("wz", "sp_above", "A")
    link("ground_cm", "sp_above", "B")
    link("sp_above", "sp_above_mul", "A")
    link("ground_step", "sp_above_mul", "B")
    link("sp_above_mul", "sp_above_sat", "")
    link("ground_plus", "sp_below_edge", "A")
    link("wz", "sp_below_edge", "B")
    link("sp_below_edge", "sp_below_mul", "A")
    link("ground_step", "sp_below_mul", "B")
    link("sp_below_mul", "sp_below_sat", "")
    link("sp_above_sat", "spandrel", "A")
    link("sp_below_sat", "spandrel", "B")

    # --- glazing composition:
    #   glazing_a = lerp(grid_mask, shop_grid, ground_band)   shop below, grid above
    #   glazing_b = lerp(glazing_a, one, spandrel)            solid dark spandrel strip
    #   mask      = glazing_b * wall_mask                     windows on walls only
    add("glazing_a", _LERP, x=2200.0)
    add("glazing_b", _LERP, x=2400.0)
    add("mask", _MUL, x=2600.0)
    link("grid_mask", "glazing_a", "A")
    link("shop_sat", "glazing_a", "B")
    link("ground_band", "glazing_a", "Alpha")
    link("glazing_a", "glazing_b", "A")
    link("one", "glazing_b", "B")
    link("spandrel", "glazing_b", "Alpha")
    link("glazing_b", "mask", "A")
    link("wall_mask", "mask", "B")

    # --- material outputs.  Base colour and roughness first blend the wall
    # value into the roof value under roof_mask, and the result is then lerped
    # towards window colour/roughness by the glazing mask; metallic stays flat
    # 0 unless a window (mask == 1) is present, so roofs are not metallic.
    add("roof_base", _LERP, x=2700.0)   # lerp(wall_col, roof_tint, roof_mask)
    add("roof_rough_l", _LERP, x=2700.0)
    add("base_color", _LERP, x=2800.0)
    add("roughness", _LERP, x=2800.0)
    add("metallic", _LERP, x=2800.0)
    link("wall_col", "roof_base", "A")
    link("roof_tint", "roof_base", "B")
    link("roof_mask", "roof_base", "Alpha")
    link("wall_rough", "roof_rough_l", "A")
    link("roof_rough", "roof_rough_l", "B")
    link("roof_mask", "roof_rough_l", "Alpha")
    link("roof_base", "base_color", "A")
    link("win_col", "base_color", "B")
    link("mask", "base_color", "Alpha")
    link("roof_rough_l", "roughness", "A")
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


# --------------------------------------------------------------------------- mask oracle

def _clamp01(x: float) -> float:
    """Mirror of Unreal's Saturate node on a scalar."""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _spec_float(spec, name):
    """One named scalar from a facade spec; missing names fall back to the
    documented ``MASTER_DEFAULTS`` (so a partial kit override is a valid spec)."""
    try:
        return float(spec.get(name, MASTER_DEFAULTS[name]))
    except (KeyError, TypeError, ValueError):
        raise ValueError(
            "facade spec must give a number for %r (master default %r)"
            % (name, MASTER_DEFAULTS.get(name))) from None


def evaluate_masks(spec, x_cm, y_cm, z_cm, normal) -> dict:
    """Pure-Python oracle for the mask arithmetic the node graph encodes.

    ``spec`` has the shape of ``facade_graph()["params"]`` -- a dict of
    ``{parameter_name: value}``; every missing scalar falls back to
    ``MASTER_DEFAULTS``.  ``normal`` is the ``(nx, ny, nz)`` surface normal.

    Returns (each key is computed by the node id in parentheses)::

        wall_mask      saturate((FacadeWallNormalMaxZ - |nz|) * sharp)   (wall_mask)
        roof_mask      saturate((|nz| - FacadeWallNormalMaxZ) * sharp)   (roof_mask)
        window_mask    the storey grid  sat_h * sat_v                    (grid_mask)
        shop_mask      shop pane * ground-floor step                     (shop_sat, ground_band)
        final_window   glazing * wall_mask                               (mask)

    This is exactly the graph arithmetic: the same spacing/edge/ground/band
    values feed the same lerp/saturate/multiply sequence, so mask behaviour is
    pinned by unit test without an Unreal editor.
    """
    spacing_h = _spec_float(spec, P_SPACING_H)
    spacing_v = _spec_float(spec, P_SPACING_V)
    window_w = _spec_float(spec, P_WIN_W)
    window_h = _spec_float(spec, P_WIN_H)
    edge = _spec_float(spec, P_EDGE)
    ground = _spec_float(spec, P_GROUND)
    shop_w = _spec_float(spec, P_SHOP_WIN_W)
    band = _spec_float(spec, P_BAND)
    max_z = _spec_float(spec, P_ORIENT_MAX_Z)
    sharp = _spec_float(spec, P_ORIENT_SHARP)

    z = float(z_cm)
    nz = abs(float(normal[2]))

    # orientation pair (nodes abs_nz/orient_sub/orient_mul/wall_mask and
    # roof_sub/roof_mul/roof_mask) -- one is the complement of the other.
    wall_mask = _clamp01((max_z - nz) * sharp)
    roof_mask = _clamp01((nz - max_z) * sharp)

    # bay + floor grid (nodes div_h/frac_h/abs_h/.../sat_h and the v twin).
    # ``% 1.0`` is Python floor-mod, equal to Unreal Frac for the positive
    # world coordinates the buildings use.
    h = (float(x_cm) + float(y_cm)) / spacing_h
    v = z / spacing_v
    d_h = abs((h % 1.0) - _HALF)
    d_v = abs((v % 1.0) - _HALF)
    sat_h = _clamp01((window_w - d_h) * edge)
    sat_v = _clamp01((window_h - d_v) * edge)
    grid_mask = sat_h * sat_v                                    # node grid_mask
    shop_sat = _clamp01((shop_w - d_h) * edge)                   # node shop_sat

    # ground-floor step and spandrel strip (nodes below_ground/.../ground_band
    # and sp_above/sp_below_edge/spandrel).
    ground_band = _clamp01((ground - z) * _GROUND_STEP_K)
    spandrel = (_clamp01((z - ground) * _GROUND_STEP_K)
                * _clamp01((ground + band - z) * _GROUND_STEP_K))

    # glazing composition = the two lerps (nodes glazing_a, glazing_b).
    glazing_a = grid_mask + (shop_sat - grid_mask) * ground_band
    glazing_b = glazing_a + (_ONE - glazing_a) * spandrel
    final_window = glazing_b * wall_mask                         # node "mask"

    return {
        "wall_mask": wall_mask,
        "roof_mask": roof_mask,
        "window_mask": grid_mask,
        "shop_mask": shop_sat * ground_band,
        "final_window": final_window,
    }


# --------------------------------------------------------------------------- kits

# NOTE: window_h and window_w are HALF-widths of the lit band inside a bay,
# measured from the bay centre, so any value >= 0.5 makes the mask cover the
# whole bay and the grid degenerates: window_h >= 0.5 gives continuous
# vertical ribbons with no floor separation at all. Two kits shipped at 0.50
# and 0.62 and rendered exactly that way. Keep both well under 0.5.
#
# Bay widths (spacing_h_cm) sit in 240-320 cm and floor heights
# (spacing_v_cm) in 300-380 cm so the kits read as architecture at street
# distance; each kit is genuinely distinct in wall colour, bay width and
# floor height.
_KIT_SPECS = {
    # Chicago: dark red brick, wide loft bays, moderate floors.
    "CHA": {
        "wall_colour": (0.44, 0.17, 0.15),
        "window_colour": (0.07, 0.13, 0.20),
        "spacing_h_cm": 320.0, "spacing_v_cm": 330.0,
        "window_w": 0.30, "window_h": 0.34, "ground_floor_cm": 430.0,
        "wall_roughness": 0.92, "window_roughness": 0.08,
        "window_metallic": 0.60,
    },
    # New York: warm limestone, tall narrow windows, high floors.
    "NYA": {
        "wall_colour": (0.76, 0.71, 0.58),
        "window_colour": (0.10, 0.15, 0.18),
        "spacing_h_cm": 280.0, "spacing_v_cm": 370.0,
        "window_w": 0.22, "window_h": 0.28, "ground_floor_cm": 460.0,
        "wall_roughness": 0.72, "window_roughness": 0.12,
        "window_metallic": 0.35,
    },
    # San Francisco: pale teal, squat wide windows, low floors.
    "SFA": {
        "wall_colour": (0.55, 0.74, 0.71),
        "window_colour": (0.04, 0.06, 0.09),
        "spacing_h_cm": 260.0, "spacing_v_cm": 300.0,
        "window_w": 0.34, "window_h": 0.40, "ground_floor_cm": 390.0,
        "wall_roughness": 0.88, "window_roughness": 0.05,
        "window_metallic": 0.45,
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
    }
    vector = {
        P_WALL_COL: list(spec["wall_colour"]),
        P_WIN_COL: list(spec["window_colour"]),
    }
    return {"scalar": scalar, "vector": vector}


# --------------------------------------------------------------------------- validation

def validate_spec(spec) -> list:
    """Problems with a facade ``spec`` (the ``facade_graph()["params"]`` shape),
    ``[]`` when valid.

    Refuses a missing or ``0.0`` value for ``FacadeOrientSharpness``,
    ``FacadeSpacingHCm`` and ``FacadeSpacingVCm``.  All three have documented
    non-zero ``MASTER_DEFAULTS``; a spacing of 0.0 is a divide by zero in the
    bay/floor grid and a sharpness of 0.0 makes both orientation masks
    constant, so either silently destroys the image and must be impossible to
    ship.
    """
    problems = []
    for name in (P_ORIENT_SHARP, P_SPACING_H, P_SPACING_V):
        if name not in spec:
            problems.append("%s is missing; it needs a non-zero value" % name)
            continue
        try:
            value = float(spec[name])
        except (TypeError, ValueError):
            problems.append("%s must be a number, got %r" % (name, spec[name]))
            continue
        if value == 0.0:
            if name == P_ORIENT_SHARP:
                problems.append(
                    "%s must be non-zero: sharpness 0.0 makes the wall/roof "
                    "orientation masks constant" % name)
            else:
                problems.append(
                    "%s must be non-zero: a bay/floor spacing of 0.0 is a "
                    "divide by zero in the window grid" % name)
    return problems


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
