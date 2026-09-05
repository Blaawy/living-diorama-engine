"""``road_surface_v1`` â€” the parameter set that makes a carriageway read dry.

Why this exists
---------------
In the rendered stills the carriageway reads as **wet** under a clear midday
sun: broad specular sheets down the lane lines and mirror-like highlights on
the tarmac.  Real dry asphalt is a rough, mostly diffuse surface â€” the
aggregate grains scatter light rather than reflect it, so its PBR response is
high roughness and a low dielectric specular â€” and it only gets *slightly*
smoother (a faint sheen, never a mirror) in the wheel tracks where tyres
polish the stone.  This module authors those values and refuses the glossy
values that produced the wet look.

What the previous look implies
------------------------------
The surface master lives in ``ldyf/surface_material.py``
(``surface_spec_v1``): ``Roughness = TextureSample(RoughnessMap, uv) *
RoughnessScale`` and ``Specular = SpecularScale`` with a master default of
``SurfaceSpecular = 0.35``.  Broad specular sheets and mirror highlights under
one fixed sun are only reachable when effective roughness sits far below the
dry band *and* specular rides at or above that 0.35 default.  So the previous
road instance must have carried ``SurfaceRoughnessScale`` well under the 0.85
floor this module states (the roughness map then pulled the product into the
glossy 0.3-0.6 band) with ``SurfaceSpecular`` near 0.35 â€” roughly 10x the
~0.03-0.04 of a dry dark dielectric.  The module below names that floor and
that ceiling as hard rules.

Material response of dry asphalt (the numbers chosen)
-----------------------------------------------------
* ``DRY_ASPHALT_ROUGHNESS = 0.90`` â€” roughness 1.0 is perfectly diffuse, 0.0
  is a mirror; published/measured dry asphalt sits at or above ~0.85 and
  commonly ~0.9, so 0.90 is chosen mid-band.  In the graph this value is a
  *scale* on the roughness map, so keeping it high means the map can only pull
  effective roughness down toward (not past) the glossy band.
* ``DRY_ASPHALT_ROUGHNESS_FLOOR = 0.85`` â€” the named floor.  Dry asphalt does
  not go below it; the wet sheen is exactly what lives below it, so the floor
  is a hard validation rule for every preset that presents itself as dry.
* ``DRY_ASPHALT_SPECULAR = 0.03`` â€” Unreal's Specular input feeds F0 at normal
  incidence; a non-metal dielectric is ~0.04-0.06, and dark asphalt, which
  absorbs much of the incident light, is at the low end (~0.02-0.04).  0.03 is
  chosen.  The old 0.35 default is an artistic value, ~10x physical, and is
  what the mirror highlights imply was applied.
* ``WHEEL_POLISH_ROUGHNESS = 0.86`` â€” tyres polish a band of stone smooth, so
  that band is slightly shinier (0.90 -> 0.86) but stays above the 0.85 floor:
  polished dry asphalt sheens faintly; it does not go wet.

Parameter names
---------------
Every applied name is imported from ``ldyf/surface_material.py``, so they are
verified against that module by construction, not copied by hand:
``SurfaceTilingCm`` (P_TILING), ``SurfaceRoughnessScale`` (P_ROUGH),
``SurfaceSpecular`` (P_SPEC) and the vector ``SurfaceTint`` (P_TINT), which
are the scalar/vector parameter-name tuples that module already publishes.
No new material parameter name is invented.  ``surface_material.py`` exposes
**no** normal-strength scalar (its graph sends ``NormalMap`` straight to the
Normal output with no strength node), so this module emits none â€” the "normal
strength" slot in the brief has nothing verified to bind to.

``surface_parameters()`` returns a dict keyed by those material names plus a
single non-material ``"preset"`` metadata entry so ``validate_surface()`` can
enforce per-preset floors (a damp surface is legitimately below the *dry*
floor; a dulled marking is not).  An editor driver must apply only the keys in
``SCALAR_PARAMETER_NAMES`` / ``VECTOR_PARAMETER_NAMES`` â€” the same split
``ldyf/unreal/ldyf_surface_editor.py`` already makes between scalars and
textures.
"""

from __future__ import annotations

from ldyf.surface_material import (  # names verified against surface_material.py
    P_ROUGH,
    P_SPEC,
    P_TILING,
    P_TINT,
    SCALAR_PARAMETER_NAMES,
    VECTOR_PARAMETER_NAMES,
)

ROAD_SURFACE_VERSION = "road_surface_v1"

# --- the dry-asphalt rules (the fix, encoded as named constants) -------------

#: Hard floor (docstring above): no surface presented as dry may drop below.
DRY_ASPHALT_ROUGHNESS_FLOOR = 0.85
#: Dry asphalt: rough aggregate, mostly diffuse (see module docstring).
DRY_ASPHALT_ROUGHNESS = 0.90
#: Wheel-polished band: slightly smoother stone, still matte (see docstring).
WHEEL_POLISH_ROUGHNESS = 0.86
#: Dry dark dielectric, low end of the ~0.02-0.06 non-metal band.
DRY_ASPHALT_SPECULAR = 0.03
#: Hard ceiling: above this a dry surface carries a wet-film look.
SPECULAR_CEILING = 0.10
#: Marking tint must stay bright so the paint stays legible after the gloss is
#: killed (see module docstring); luminance floor on the SurfaceTint vector.
MARKING_BRIGHTNESS_FLOOR = 0.85
MARKING_PRESET = "painted_marking"
#: The one preset that is allowed below the *dry* floor: it declares dampness.
DAMP_PRESET = "damp_asphalt"

#: The parameter set for a dry carriageway, material names only.
DRY_ASPHALT = {
    P_ROUGH: DRY_ASPHALT_ROUGHNESS,
    P_SPEC: DRY_ASPHALT_SPECULAR,
    P_TINT: (0.95, 0.93, 0.89),   # faint warm cast of sunlit aggregate
    P_TILING: 400.0,              # same world repeat as the master default
}

#: One texture repeat every 4 m, matching surface_material.MASTER_DEFAULTS.
_DEFAULT_TILING_CM = 400.0


def _f3(v: float) -> float:
    """Round to 3 decimals and kill ``-0.0`` (byte determinism)."""
    return round(float(v), 3) + 0.0


def _luminance(rgb) -> float:
    """Rec.709 luminance of a tint vector â€” the brightness the eye reads."""
    return 0.2126 * float(rgb[0]) + 0.7152 * float(rgb[1]) + 0.0722 * float(rgb[2])


# --- the preset table ---------------------------------------------------------
# The distinction the fix depends on lives here, explicitly per row: the point
# is to kill the wet sheen, NOT to dull the paint, so ``painted_marking`` is
# flagged ``marking: True`` with a near-white tint and a brightness floor, and
# every other row carries dry-band roughness.  ``damp_asphalt`` is the single
# deliberate exception to the roughness floor and says so in its own row.
SURFACE_PRESETS = {
    "dry_asphalt": {
        "marking": False,
        P_ROUGH: DRY_ASPHALT_ROUGHNESS,
        P_SPEC: DRY_ASPHALT_SPECULAR,
        P_TINT: DRY_ASPHALT[P_TINT],
        P_TILING: _DEFAULT_TILING_CM,
    },
    "damp_asphalt": {
        # Wet film smooths the surface (roughness 0.60, far below the dry
        # floor) and lifts specular; it is the only row exempt from the floor.
        "marking": False,
        P_ROUGH: 0.60,
        P_SPEC: 0.08,
        P_TINT: (0.90, 0.90, 0.92),  # slight cool cast of a wet film
        P_TILING: _DEFAULT_TILING_CM,
    },
    "concrete_sidewalk": {
        "marking": False,
        P_ROUGH: 0.92,
        P_SPEC: 0.04,
        P_TINT: (0.98, 0.98, 0.98),  # bright brushed concrete
        P_TILING: _DEFAULT_TILING_CM,
    },
    MARKING_PRESET: {
        # Bright, legible white paint: near-white tint so the albedo stays
        # bright; gloss stays in the dry band so it cannot sheen like the wet
        # road did.  Legibility comes from brightness contrast, not gloss.
        "marking": True,
        P_ROUGH: 0.88,
        P_SPEC: 0.04,
        P_TINT: (0.98, 0.98, 0.96),
        P_TILING: _DEFAULT_TILING_CM,
    },
}

#: Material parameter names an editor driver may apply to the material.
APPLIED_PARAMETER_NAMES = tuple(sorted(SCALAR_PARAMETER_NAMES)
                                + sorted(VECTOR_PARAMETER_NAMES))


def surface_parameters(preset: str, *, wheel_polish: bool = False) -> dict:
    """The concrete parameter-name/value mapping an editor driver applies.

    ``preset`` must name a row of :data:`SURFACE_PRESETS`.  Returns the
    material names verified against ``ldyf/surface_material.py`` (all four:
    P_TILING, P_ROUGH, P_SPEC, P_TINT â€” none guessed) plus the ``"preset"``
    metadata entry used by :func:`validate_surface`; a driver applies only the
    names in ``APPLIED_PARAMETER_NAMES``.

    With ``wheel_polish=True`` (dry asphalt only) the roughness drops from
    0.90 to :data:`WHEEL_POLISH_ROUGHNESS` (0.86) â€” the tyre-polished band â€”
    still above the dry-asphalt floor, because a polished dry track sheens
    faintly and never reads wet.
    """
    if preset not in SURFACE_PRESETS:
        raise ValueError("unknown preset %r; known: %s"
                         % (preset, ", ".join(sorted(SURFACE_PRESETS))))
    if wheel_polish and preset != "dry_asphalt":
        raise ValueError(
            "wheel_polish only applies to the dry asphalt carriageway, "
            "not preset %r" % (preset,))
    row = SURFACE_PRESETS[preset]
    roughness = WHEEL_POLISH_ROUGHNESS if wheel_polish else row[P_ROUGH]
    tint = tuple(_f3(c) for c in row[P_TINT])
    for label, value in ((P_ROUGH, roughness), (P_SPEC, row[P_SPEC])):
        if not 0.0 <= float(value) <= 1.0:
            raise ValueError("%s out of range [0, 1]: %r" % (label, value))
    for c in tint:
        if not 0.0 <= c <= 1.0:
            raise ValueError("%s channel out of range [0, 1]: %r"
                             % (P_TINT, row[P_TINT]))
    return {
        P_TILING: _f3(row[P_TILING]),
        P_ROUGH: _f3(roughness),
        P_SPEC: _f3(row[P_SPEC]),
        P_TINT: list(tint),
        "preset": preset,
    }


def validate_surface(params: dict) -> list:
    """Problems with a ``surface_parameters()`` mapping; ``[]`` means valid.

    Hard rules, in order:
    * a scalar (roughness, specular) or tint channel outside [0, 1];
    * roughness below :data:`DRY_ASPHALT_ROUGHNESS_FLOOR` (0.85) for any
      preset that presents itself as dry â€” this is the exact defect being
      fixed, so it is a hard rule with a named floor; ``damp_asphalt`` is the
      single row that declares itself damp and is exempt;
    * specular above :data:`SPECULAR_CEILING` (0.10);
    * a marking preset whose tint luminance falls below
      :data:`MARKING_BRIGHTNESS_FLOOR` (0.85) â€” killing the sheen must not
      dull the paint.
    """
    problems: list = []
    preset = params.get("preset")
    if preset not in SURFACE_PRESETS:
        problems.append("params carry no known \"preset\" (%r); per-preset "
                        "floors cannot be enforced" % (preset,))
    rough = params.get(P_ROUGH)
    spec = params.get(P_SPEC)
    tint = params.get(P_TINT)
    for label, value in ((P_ROUGH, rough), (P_SPEC, spec)):
        if value is None:
            problems.append("%s is missing" % label)
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            problems.append("%s must be a number, got %r" % (label, value))
            continue
        if not 0.0 <= value <= 1.0:
            problems.append("%s out of range [0, 1]: %r" % (label, value))
    if tint is None:
        problems.append("%s is missing" % P_TINT)
    else:
        try:
            channels = [float(c) for c in tint]
        except (TypeError, ValueError):
            problems.append("%s must be a 3-channel vector, got %r"
                            % (P_TINT, tint))
            channels = []
        if len(channels) != 3:
            problems.append("%s must have 3 channels, got %r" % (P_TINT, tint))
        for c in channels:
            if not 0.0 <= c <= 1.0:
                problems.append("%s channel out of range [0, 1]: %r"
                                % (P_TINT, tint))

    # Roughness floor â€” the defect fix.  damp_asphalt is the declared
    # exception; everything else is dry-intent and must not go glossy.
    if (preset != DAMP_PRESET and rough is not None):
        try:
            rv = float(rough)
        except (TypeError, ValueError):
            rv = -1.0
        if 0.0 <= rv < DRY_ASPHALT_ROUGHNESS_FLOOR:
            problems.append(
                "roughness %.3f is below the dry-asphalt floor %.2f: this is "
                "the wet-sheen band the fix refuses" % (rv,
                                                        DRY_ASPHALT_ROUGHNESS_FLOOR))
    if spec is not None:
        try:
            sv = float(spec)
        except (TypeError, ValueError):
            sv = 2.0
        if sv > SPECULAR_CEILING:
            problems.append(
                "specular %.3f is above the ceiling %.2f: the mirror "
                "highlights the fix refuses" % (sv, SPECULAR_CEILING))

    # Marking brightness floor: gloss is gone, paint must stay bright.
    if preset == MARKING_PRESET and tint is not None:
        try:
            lum = _luminance(tint)
        except (TypeError, ValueError, IndexError):
            lum = -1.0
        if lum < MARKING_BRIGHTNESS_FLOOR:
            problems.append(
                "painted-marking tint luminance %.3f is below the brightness "
                "floor %.2f: killing the sheen must not dull the paint"
                % (lum, MARKING_BRIGHTNESS_FLOOR))
    return problems
