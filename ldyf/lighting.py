"""``lighting_spec_v1`` â€” deterministic lighting + exposure, as plain data.

Why this exists
---------------
The level ships with a DirectionalLight, a SkyLight, a SkyAtmosphere and zero
PostProcessVolumes, so nothing pins exposure. Unreal's automatic eye
adaptation meters whatever the frame happens to contain, and Movie Render
Queue's final render shows one shot with block interiors crushed to black
while the carriageway is blown to white, with exposure drifting between
shots. A deterministic pipeline needs the same frame to grade the same way on
every render, so the exposure, sun, sky and fog are described here as data a
thin ``ldyf/unreal/*`` driver applies.

House rule (see ``surface_material.py``): a module describes a configuration
as plain data so it is unit-testable without an editor. No ``import unreal``
anywhere in this file; everything is stdlib.

The exposure trick
------------------
Unreal ignores a post-process setting unless its companion ``override_``
boolean is set â€” a settings block with no overrides silently does nothing.
Every setting key below therefore carries a parallel ``override_<key>`` flag
that must be ``True``. Disabling adaptation needs two independent belts:

* ``auto_exposure_method = "AEM_Manual"`` â€” the metering mode is manual, and
* ``auto_exposure_min_brightness == auto_exposure_max_brightness`` â€” the
  metering range collapses to zero width, so no adaptation is possible even
  if the mode were ignored. The numeric pin value is arbitrary; equality is
  the point, and it defaults to the manual EV so the document is
  self-consistent.

Engine property names
---------------------
Keys are Unreal Python property names (snake_case of the C++ member), the
names the driver calls on ``PostProcessVolume.Settings`` / the light and fog
components:

* exposure: ``AutoExposureMethod``, ``AutoExposureBias``,
  ``AutoExposureMinBrightness``, ``AutoExposureMaxBrightness``,
  ``AutoExposureApplyPhysicalCameraExposure`` (each paired with its
  ``bOverride_*`` bit -> ``override_*`` here);
* sun: domain degrees/units keyed explicitly (``elevation_deg``,
  ``azimuth_deg``, ``intensity_lux``, ``temperature_k``) plus
  ``use_temperature`` (``LightComponent.UseTemperature`` gates
  ``Temperature``);
* sky: ``intensity`` (unitless multiplier on SkyLight), ``real_time_capture``
  (``bRealTimeCapture``), ``source_type`` (``SLS_CapturedScene``);
* fog: ``density`` (1/cm, ExponentialHeightFog ``FogDensity``),
  ``height_falloff`` (``FogHeightFalloff``), ``start_distance_cm``
  (``StartDistance``; cm is Unreal's world unit).

The uniform ``override_`` pairing rule applies to every settings block so the
validator can enforce one rule over all four: any key whose override is
missing or False is reported.
"""

from __future__ import annotations

import math

LIGHTING_SPEC_VERSION = "lighting_spec_v1"

# ---------------------------------------------------------------- defaults

# Exposure compensation written to AutoExposureBias. MEASURED, not derived.
#
# This module first shipped DEFAULT_EV100 = +15.0, reasoning that Unreal's
# Manual AutoExposureMethod treats AutoExposureBias as an EV100 index where a
# higher EV admits less light. Rendered against the real level that produced a
# PURE WHITE frame: the bias BRIGHTENS by 2^bias, so +15 is a 32,768x gain.
# The sign is inverted from that reading.
#
# A sunlit surface under the 100 klx sun below sits near
# 100000 * 0.18 / pi ~= 5730 cd/m^2, and mapping that to mid-grey needs a
# multiplier near 0.18 / 5730 = 3.1e-5, i.e. about 2^-15. A three-point sweep
# at -13, -15 and -17 was rendered through MRQ and looked at: -15 and -17
# crushed the aerial into near-black, while -13 held both a legible street and
# a legible aerial. The number below is what a frame actually showed, not what
# the photometry alone predicted.
DEFAULT_EV100 = -13.0

# Sun at 40 deg elevation: shadow length ~= 1.19 * block height, so street
# floors between tall blocks still catch sun for part of the day (the old
# crushed plazas were partly a sun-angle problem) without the flat, shadowless
# look of an almost-overhead sun.
DEFAULT_SUN_ELEVATION_DEG = 40.0
DEFAULT_SUN_AZIMUTH_DEG = 135.0       # south-east; light runs down the N-S grid
DEFAULT_SUN_INTENSITY_LUX = 100000.0  # clear-day direct sun illuminance
DEFAULT_SUN_TEMPERATURE_K = 5800.0    # neutral clear-day white

# Sky fill, MEASURED. At intensity 1.0 the ambient fill was so weak that every
# surface facing away from the 40-degree sun rendered near black, which is what
# made the aerial read as a field of dark slabs. Rendered at 1.0, 3.0 and 6.0
# and looked at: 6.0 is where shadowed facades and block interiors carry legible
# detail without the scene flattening out.
DEFAULT_SKY_INTENSITY = 6.0
# Real-time capture re-renders the sky cubemap every frame, which is a source of
# render-to-render variation, so it stays off. The consequence is that the
# captured cubemap is only as current as its last capture: after ANY change to
# the sun or the atmosphere the driver must call recapture_sky(), or the fill
# stays stale and shadows go black for a reason that looks like a lighting bug
# but is really a caching one. That recapture is not optional.
DEFAULT_SKY_REAL_TIME_CAPTURE = False

# Exponential height fog tuned for a ~600 m city block. 2e-5 per cm leaves
# ~55% transmission at 300 m (depth cue) and ~30% at the 600 m far edge,
# while StartDistance = 80 m keeps the street foreground free of milkiness.
DEFAULT_FOG_DENSITY = 0.00002
DEFAULT_FOG_HEIGHT_FALLOFF = 0.002
DEFAULT_FOG_START_DISTANCE_CM = 8000.0

SETTINGS_SECTIONS = ("exposure", "sun", "sky", "fog")


def _f3(value, name="value"):
    """Coerce to a plain float, canonicalised for byte-deterministic JSON.

    Every float that leaves this module goes through here: it rejects
    non-numeric input and non-finite values with ValueError, and rounds to 6
    decimals so two builds of the same spec serialise to identical bytes.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number, got %r" % (name, value))
    if not math.isfinite(f):
        raise ValueError("%s must be finite, got %r" % (name, value))
    return round(f, 6)


def _require_bool(value, name):
    if not isinstance(value, bool):
        raise ValueError("%s must be a bool, got %r" % (name, value))
    return value


# ----------------------------------------------------------------- exposure

def exposure_settings(*, ev100: float = DEFAULT_EV100,
                      brightness_pin: float | None = None,
                      apply_physical_camera_exposure: bool = False) -> dict:
    """A manual-exposure block for the level's (currently absent) volume.

    ``ev100`` is the exposure value in EV100 units. It is stored twice, in
    two different roles:

    * ``auto_exposure_bias`` â€” in Unreal a Manual ``AutoExposureMethod``
      exposes through ``AutoExposureBias`` (the EV100 index: higher EV =
      less light reaching the sensor);
    * ``auto_exposure_min_brightness == auto_exposure_max_brightness`` â€”
      pinning the auto metering range to zero width so no adaptation is
      possible even if the method flag were ignored. ``brightness_pin``
      defaults to ``ev100`` so the doc stays self-consistent; equality is
      what matters, the number is arbitrary.

    ``apply_physical_camera_exposure`` is kept False: physical camera
    exposure (ISO/shutter/aperture) would be a second knob on the same
    exposure, and leaving it on makes Manual less predictable.
    """
    ev = _f3(ev100, "ev100")
    pin = _f3(ev100 if brightness_pin is None else brightness_pin,
              "brightness_pin")
    physical = _require_bool(apply_physical_camera_exposure,
                             "apply_physical_camera_exposure")
    return {
        "auto_exposure_method": "AEM_Manual",
        "override_auto_exposure_method": True,
        "auto_exposure_bias": ev,
        "override_auto_exposure_bias": True,
        "auto_exposure_min_brightness": pin,
        "override_auto_exposure_min_brightness": True,
        "auto_exposure_max_brightness": pin,
        "override_auto_exposure_max_brightness": True,
        "auto_exposure_apply_physical_camera_exposure": physical,
        "override_auto_exposure_apply_physical_camera_exposure": True,
    }


# ---------------------------------------------------------------------- sun

def sun_settings(*, elevation_deg: float = DEFAULT_SUN_ELEVATION_DEG,
                 azimuth_deg: float = DEFAULT_SUN_AZIMUTH_DEG,
                 intensity_lux: float = DEFAULT_SUN_INTENSITY_LUX,
                 temperature_k: float = DEFAULT_SUN_TEMPERATURE_K) -> dict:
    """Directional-light settings.

    Bright clear-daylight defaults. The sun is high enough (40 deg elevation)
    that a street canyon only ~1.2 block-heights deep still catches direct
    sun on its floor for much of the day â€” the crushed plazas of the previous
    render were partly a sun-angle problem, not only an exposure one â€” yet
    low enough to leave modelled shadows instead of the flat look of an
    almost-overhead noon sun. The azimuth (135 deg, south-east) runs light
    down the N-S road grid so the light penetrates rather than skimming
    across the block rows.

    Intensity is in lux on the directional light (clear-day sun ~ 100 klx).
    ``temperature_k`` is only honoured when ``use_temperature`` is True â€” the
    LightComponent behaves the same way as a post-process setting here.
    """
    elev = _f3(elevation_deg, "elevation_deg")
    if not 0.0 < elev < 90.0:
        raise ValueError("elevation_deg must be in (0, 90), got %r"
                         % (elevation_deg,))
    azi = _f3(azimuth_deg, "azimuth_deg")
    if not 0.0 <= azi < 360.0:
        raise ValueError("azimuth_deg must be in [0, 360), got %r"
                         % (azimuth_deg,))
    lux = _f3(intensity_lux, "intensity_lux")
    if lux <= 0.0:
        raise ValueError("intensity_lux must be > 0, got %r"
                         % (intensity_lux,))
    temp = _f3(temperature_k, "temperature_k")
    if temp <= 0.0:
        raise ValueError("temperature_k must be > 0, got %r"
                         % (temperature_k,))
    return {
        "elevation_deg": elev,
        "override_elevation_deg": True,
        "azimuth_deg": azi,
        "override_azimuth_deg": True,
        "intensity_lux": lux,
        "override_intensity_lux": True,
        "temperature_k": temp,
        "override_temperature_k": True,
        "use_temperature": True,
        "override_use_temperature": True,
    }


# ---------------------------------------------------------------------- sky

def sky_settings(*, intensity: float = DEFAULT_SKY_INTENSITY,
                 real_time_capture: bool = DEFAULT_SKY_REAL_TIME_CAPTURE
                 ) -> dict:
    """Sky-light settings.

    Real-time capture is off by default: a SkyLight that re-captures every
    frame ties the grade to per-frame state and breaks determinism. With a
    fixed scene, one capture at load produces byte-identical light every
    render. ``intensity`` is the SkyLight's unitless multiplier (1.0 keeps
    the captured scene's own scale).
    """
    mul = _f3(intensity, "intensity")
    if mul <= 0.0:
        raise ValueError("intensity must be > 0, got %r" % (intensity,))
    rtc = _require_bool(real_time_capture, "real_time_capture")
    return {
        "intensity": mul,
        "override_intensity": True,
        "real_time_capture": rtc,
        "override_real_time_capture": True,
        "source_type": "SLS_CapturedScene",
        "override_source_type": True,
    }


# ---------------------------------------------------------------------- fog

def fog_settings(*, density: float = DEFAULT_FOG_DENSITY,
                 height_falloff: float = DEFAULT_FOG_HEIGHT_FALLOFF,
                 start_distance_cm: float = DEFAULT_FOG_START_DISTANCE_CM
                 ) -> dict:
    """Exponential height fog, tuned to sell distance without milkiness.

    ``density`` is ExponentialHeightFog's FogDensity in 1/cm at the fog
    altitude; ``height_falloff`` in 1/cm softens the fog with altitude so
    rooftops stay clearer than the ground plane; ``start_distance_cm`` keeps
    everything between the camera and that distance perfectly clear.

    This pairs with ``ldyf/backdrop.py``'s ``atmosphere()`` if that module
    exists; it does not yet, so these numbers stand alone â€” a probe render
    should confirm them against the SkyAtmosphere haze before finalising.
    """
    dens = _f3(density, "density")
    if dens < 0.0:
        raise ValueError("density must be >= 0, got %r" % (density,))
    fall = _f3(height_falloff, "height_falloff")
    if fall < 0.0:
        raise ValueError("height_falloff must be >= 0, got %r"
                         % (height_falloff,))
    start = _f3(start_distance_cm, "start_distance_cm")
    if start < 0.0:
        raise ValueError("start_distance_cm must be >= 0, got %r"
                         % (start_distance_cm,))
    return {
        "density": dens,
        "override_density": True,
        "height_falloff": fall,
        "override_height_falloff": True,
        "start_distance_cm": start,
        "override_start_distance_cm": True,
    }


# ------------------------------------------------------------------- build

def _default_rationale() -> list:
    """Design-intent text for the module defaults (build_lighting uses it even
    when a block was replaced wholesale, so it must never index into caller
    data)."""
    ev = DEFAULT_EV100
    lux = DEFAULT_SUN_INTENSITY_LUX
    return [
        "Exposure is fully manual and pinned: auto_exposure_method is "
        "AEM_Manual and auto_exposure_min_brightness == "
        "auto_exposure_max_brightness, so the meter cannot adapt and the "
        "same frame grades identically on every MRQ render.",
        f"EV100={ev:.1f} is the sunny-16 daylight value. An 18%-grey card "
        f"there sits at 4096 cd/m^2; a sunlit asphalt carriageway (rho ~ "
        f"0.15-0.2 under {lux / 1000.0:.0f} klx direct sun) lands at "
        "~4800-6400 cd/m^2, i.e. within half a stop of middle grey, so the "
        "road cannot clip, while the film curve's highlight rolloff absorbs "
        "sunlit white facades.",
        "Fixed EV is bright-but-conservative rather than pumped: an auto "
        "meter reading a dark plaza raises gain until the sunlit road clips "
        "- exactly the blown/crushed split seen before.",
        "Sun at 40 deg elevation and 135 deg azimuth: street floors between "
        "tall blocks catch direct sun (shadow ~ 1.2x block height) without "
        "the flat, shadowless look of an almost-overhead sun. The crushed "
        "plazas were partly a sun-angle problem, not only exposure.",
        "SkyLight real-time capture is off: one capture per loaded scene, so "
        "the fill is identical on every render of the same scene.",
        "Fog: density 2e-5/cm with 0.002/cm height falloff leaves ~55% "
        "transmission at 300 m and a clear foreground past an 80 m start "
        "distance - depth without milkiness.",
    ]


def build_lighting(**kw) -> dict:
    """Assemble the whole ``lighting_spec_v1`` document.

    Call with no arguments for the defaults. Keyword arguments are routed to
    the four settings builders by their parameter names (``ev100``,
    ``elevation_deg``, ``intensity``, ...); a whole block may be replaced by
    passing the section name with a dict value (``sun={...}``); ``rationale``
    replaces the generated rationale with your own list of strings. Unknown
    keywords raise TypeError rather than silently dropping configuration.
    """
    import inspect

    builders = {
        "exposure": exposure_settings,
        "sun": sun_settings,
        "sky": sky_settings,
        "fog": fog_settings,
    }
    blocks = {}
    forwarded = {}
    rationale = None
    for key, value in kw.items():
        if key in builders and isinstance(value, dict):
            blocks[key] = value
        elif key == "rationale":
            if not isinstance(value, list):
                raise TypeError("rationale must be a list of strings")
            rationale = value
        elif key in {p for b in builders.values()
                     for p in inspect.signature(b).parameters}:
            forwarded.setdefault(key, value)
        else:
            raise TypeError("build_lighting got an unexpected keyword %r"
                            % (key,))

    for name, builder in builders.items():
        if name not in blocks:
            blocks[name] = builder(**{k: v for k, v in forwarded.items()
                                      if k in inspect.signature(builder)
                                      .parameters})
    return {
        "schema_version": LIGHTING_SPEC_VERSION,
        "exposure": blocks["exposure"],
        "sun": blocks["sun"],
        "sky": blocks["sky"],
        "fog": blocks["fog"],
        "rationale": _default_rationale() if rationale is None else rationale,
    }


# ---------------------------------------------------------------- validate

def validate_lighting(spec: dict) -> list:
    """Problems with a lighting spec; an empty list means valid.

    Refuses (each as one or more problem strings):

    * auto exposure left enabled (method not Manual / override not True);
    * min brightness != max brightness in the exposure block;
    * any settings block whose ``override_`` flag is missing or False;
    * a non-positive intensity (sun lux or sky multiplier);
    * a sun elevation outside (0, 90).
    """
    problems: list = []
    if not isinstance(spec, dict):
        return ["spec must be a dict, got %r" % (type(spec).__name__,)]

    for section in SETTINGS_SECTIONS:
        block = spec.get(section)
        if not isinstance(block, dict):
            problems.append("%s: settings block is missing or not a dict"
                            % section)
            continue
        for key, value in block.items():
            if key.startswith("override_"):
                if value is not True:
                    problems.append(
                        "%s: override flag for %r is missing or False"
                        % (section, key[len("override_"):]))
            else:
                twin = "override_" + key
                if block.get(twin) is not True:
                    problems.append(
                        "%s: override flag for %r is missing or False"
                        % (section, key))

    exposure = spec.get("exposure")
    if isinstance(exposure, dict):
        if exposure.get("auto_exposure_method") != "AEM_Manual":
            problems.append(
                "exposure: auto exposure left enabled (auto_exposure_method "
                "is %r; must be 'AEM_Manual')"
                % (exposure.get("auto_exposure_method"),))
        try:
            lo = float(exposure.get("auto_exposure_min_brightness"))
            hi = float(exposure.get("auto_exposure_max_brightness"))
            if abs(lo - hi) > 1e-9:
                problems.append(
                    "exposure: auto_exposure_min_brightness (%r) must equal "
                    "auto_exposure_max_brightness (%r)" % (lo, hi))
        except (TypeError, ValueError):
            problems.append("exposure: brightness pins must be numbers")

    sun = spec.get("sun")
    if isinstance(sun, dict):
        try:
            lux = float(sun.get("intensity_lux"))
            if lux <= 0.0:
                problems.append("sun: intensity_lux must be > 0, got %r"
                                % (lux,))
        except (TypeError, ValueError):
            problems.append("sun: intensity_lux must be a number")
        try:
            elev = float(sun.get("elevation_deg"))
            if not 0.0 < elev < 90.0:
                problems.append("sun: elevation_deg must be in (0, 90), got "
                                "%r" % (elev,))
        except (TypeError, ValueError):
            problems.append("sun: elevation_deg must be a number")

    sky = spec.get("sky")
    if isinstance(sky, dict):
        try:
            mul = float(sky.get("intensity"))
            if mul <= 0.0:
                problems.append("sky: intensity must be > 0, got %r"
                                % (mul,))
        except (TypeError, ValueError):
            problems.append("sky: intensity must be a number")

    return problems
