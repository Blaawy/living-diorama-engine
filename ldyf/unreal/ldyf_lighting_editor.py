"""Apply a ``lighting_spec_v1`` document to the live level.

Why this exists
---------------
The level carried a DirectionalLight, a SkyLight and a SkyAtmosphere and **no
PostProcessVolume at all**, so nothing pinned exposure and Unreal's eye
adaptation metered whatever each shot happened to contain. The 90 s preview came
back with block interiors crushed to black against a blown-white carriageway,
and the grade visibly shifted between cuts. For a deterministic Movie Render
Queue pipeline that is a defect, not a taste question: the same frame must grade
the same way on every render.

Every property name here is **read back after writing**. The spec module that
produced these names said plainly that it inferred them from the C++ symbols
rather than verifying them against an editor, and an Unreal property name that
does not exist fails silently — which is exactly how the facade orientation mask
came to be missing from a shipped material for a whole revision. So this driver
reports, per property, whether the engine actually took the value.
"""
from __future__ import annotations

import unreal  # type: ignore[import-not-found]

PPV_LABEL = "LD_Exposure"


# Read-back comparison tolerance for numeric properties. Unreal round-trips
# most editor floats through 32-bit storage, so an exact comparison would flag
# honest values; 1e-4 relative (with the same absolute floor) is far tighter
# than a value the engine would "roughly" take and far looser than float32
# noise at these magnitudes.
VALUE_TOLERANCE = 1e-4


def _same_value(requested, returned, *, tol: float = VALUE_TOLERANCE) -> bool:
    """Did the engine actually take the value we asked for?

    Numbers compare within ``tol`` (relative, with ``tol`` as an absolute
    floor). Booleans and enums -- neither reliably a number nor a string across
    Unreal builds -- compare by their string form, case-folded and stripped,
    which is also what makes ``AEM_Manual`` and ``AEM_MANUAL`` equal.
    """
    if isinstance(requested, bool) or isinstance(returned, bool):
        return str(bool(requested)) == str(bool(returned))
    if isinstance(requested, (int, float)) and isinstance(returned, (int, float)):
        want = float(requested)
        return abs(want - float(returned)) <= tol * max(1.0, abs(want))
    return str(requested).strip().lower() == str(returned).strip().lower()


def _enum(enum_cls, name):
    """Resolve an enum member tolerantly of case.

    The spec module wrote ``AEM_Manual`` from the C++ symbol; Unreal's Python
    binding exposes ``AEM_MANUAL``. Rather than hard-code either spelling,
    match case-insensitively and fail loudly with the real member list if
    nothing matches, so a wrong name can never pass as a silent no-op.
    """
    want = str(name).upper()
    for m in dir(enum_cls):
        if m.upper() == want:
            return getattr(enum_cls, m)
    raise RuntimeError("%s has no member like %r; it has %s"
                       % (enum_cls.__name__, name,
                          [m for m in dir(enum_cls) if not m.startswith("_")]))


def _set_and_verify(obj, key, value, problems, *, label):
    """Set one editor property and read it back, recording any refusal."""
    try:
        obj.set_editor_property(key, value)
    except Exception as exc:                                   # noqa: BLE001
        problems.append("%s.%s rejected: %s" % (label, key, exc))
        return None
    try:
        got = obj.get_editor_property(key)
    except Exception as exc:                                   # noqa: BLE001
        problems.append("%s.%s unreadable after write: %s" % (label, key, exc))
        return None
    # Reading a value back and returning it without COMPARING it catches
    # nothing: an engine silently ignoring the write is exactly the case this
    # read-back exists to report. An adversarial review found this gap.
    if not _same_value(value, got):
        problems.append(
            "%s.%s did not take the requested value: requested %r, engine "
            "returned %r" % (label, key, value, got))
    return got


def _apply_block(settings, block, problems, *, label, enum_map=None):
    """Apply one spec block to a PostProcessSettings-like struct.

    A post-process setting is inert in Unreal unless its ``bOverride_`` flag is
    set, so the spec carries a parallel ``override_`` key for every value and
    both halves are written here. A missing override is the silent-no-op case.
    """
    written = {}
    enum_map = enum_map or {}
    for key, value in sorted(block.items()):
        if key.startswith("override_"):
            continue
        if key not in block or ("override_%s" % key) not in block:
            problems.append("%s.%s has no override flag in the spec" % (label, key))
            continue
        v = enum_map.get(key, lambda x: x)(value)
        got = _set_and_verify(settings, key, v, problems, label=label)
        written[key] = got
        _set_and_verify(settings, "override_%s" % key,
                        bool(block["override_%s" % key]), problems, label=label)
    return written


def apply_lighting(spec: dict) -> dict:
    """Apply exposure, sun, sky and fog. Returns what the engine actually took."""
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    problems: list = []
    result: dict = {"schema_version": spec.get("schema_version")}

    # ---- exposure: an unbound PostProcessVolume so every camera inherits it
    ppv = None
    for a in EAS.get_all_level_actors():
        if a and str(a.get_actor_label()) == PPV_LABEL:
            ppv = a
            break
    if ppv is None:
        ppv = EAS.spawn_actor_from_class(unreal.PostProcessVolume,
                                         unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        ppv.set_actor_label(PPV_LABEL)
    # unbound = applies everywhere, so a camera outside any volume is still graded
    ppv.set_editor_property("unbound", True)
    ppv.set_editor_property("priority", 100.0)
    ppv.set_editor_property("blend_weight", 1.0)
    settings = ppv.get_editor_property("settings")
    exposure_enums = {
        "auto_exposure_method": lambda v: _enum(unreal.AutoExposureMethod, v),
    }
    result["exposure"] = _apply_block(settings, spec["exposure"], problems,
                                      label="exposure", enum_map=exposure_enums)
    ppv.set_editor_property("settings", settings)
    result["exposure_readback"] = {
        k: str(ppv.get_editor_property("settings").get_editor_property(k))
        for k in ("auto_exposure_method", "auto_exposure_bias",
                  "auto_exposure_min_brightness", "auto_exposure_max_brightness")
    }

    # ---- sun
    sun = None
    for a in EAS.get_all_level_actors():
        if a and isinstance(a, unreal.DirectionalLight):
            sun = a
            break
    if sun is None:
        problems.append("no DirectionalLight in the level")
    else:
        s = spec["sun"]
        # elevation/azimuth are an actor rotation, not light properties: a
        # negative pitch points the light downward at the given elevation.
        sun.set_actor_rotation(
            unreal.Rotator(0.0, -float(s["elevation_deg"]), float(s["azimuth_deg"])), False)
        comp = sun.light_component
        _set_and_verify(comp, "intensity", float(s["intensity_lux"]), problems, label="sun")
        _set_and_verify(comp, "use_temperature", bool(s["use_temperature"]), problems, label="sun")
        _set_and_verify(comp, "temperature", float(s["temperature_k"]), problems, label="sun")
        result["sun"] = {"rotation": [0.0, -float(s["elevation_deg"]), float(s["azimuth_deg"])],
                         "intensity": comp.get_editor_property("intensity"),
                         "temperature": comp.get_editor_property("temperature")}

    # ---- sky
    skyl = None
    for a in EAS.get_all_level_actors():
        if a and isinstance(a, unreal.SkyLight):
            skyl = a
            break
    if skyl is None:
        problems.append("no SkyLight in the level")
    else:
        sk = spec["sky"]
        comp = skyl.light_component
        # A STATIONARY SkyLight bakes its DIFFUSE ambient into lightmaps. No
        # lighting build exists in this project, so every STATIC object -- the
        # instanced street trees among them -- received no indirect light at all
        # and fell back to black wherever the sun did not reach. A tree in
        # building shadow rendered as a black silhouette of leaf cards while a
        # single sunlit leaf on the same tree came out green, which is what
        # proved the material innocent: it is MSM_TWO_SIDED_FOLIAGE with a
        # non-zero LeafSubsurface and both textures bound. MOVABLE gives fully
        # dynamic diffuse ambient with no bake, and the silhouette disappears.
        try:
            skyl.root_component.set_editor_property(
                "mobility", unreal.ComponentMobility.MOVABLE)
        except Exception as exc:                                   # noqa: BLE001
            problems.append("sky mobility not set MOVABLE: %s" % exc)
        _set_and_verify(comp, "intensity", float(sk["intensity"]), problems, label="sky")
        # real-time capture re-renders the sky every frame; for a deterministic
        # render the fill must be captured once and then held.
        _set_and_verify(comp, "real_time_capture", bool(sk["real_time_capture"]),
                        problems, label="sky")
        # A captured-scene skylight holds whatever cubemap it captured last. The
        # sun rotation and intensity have just been rewritten, so without an
        # explicit recapture the ambient fill is stale and every shadowed
        # surface renders far darker than the sky above it actually is. That
        # looks like a lighting bug and is really a caching one.
        recaptured = False
        try:
            comp.recapture_sky()
            recaptured = True
        except Exception as exc:                               # noqa: BLE001
            problems.append("sky.recapture_sky failed: %s" % exc)
        result["sky"] = {"mobility": str(
                             skyl.root_component.get_editor_property("mobility")),
                         "intensity": comp.get_editor_property("intensity"),
                         "real_time_capture": comp.get_editor_property("real_time_capture"),
                         "recaptured": recaptured}

    # ---- fog
    fog = None
    for a in EAS.get_all_level_actors():
        if a and isinstance(a, unreal.ExponentialHeightFog):
            fog = a
            break
    if fog is None:
        fog = EAS.spawn_actor_from_class(unreal.ExponentialHeightFog,
                                         unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        fog.set_actor_label("LD_Fog")
    f = spec["fog"]
    comp = fog.get_editor_property("component")
    _set_and_verify(comp, "fog_density", float(f["density"]), problems, label="fog")
    _set_and_verify(comp, "fog_height_falloff", float(f["height_falloff"]), problems, label="fog")
    # start distance is exposed only as a setter on the component, not as an
    # editor property, so it cannot go through _set_and_verify
    try:
        comp.set_start_distance(float(f["start_distance_cm"]))
        start_ok = True
    except Exception as exc:                                   # noqa: BLE001
        problems.append("fog.set_start_distance rejected: %s" % exc)
        start_ok = False
    result["fog"] = {"density": comp.get_editor_property("fog_density"),
                     "height_falloff": comp.get_editor_property("fog_height_falloff"),
                     "start_distance_set": start_ok}

    result["problems"] = problems
    return result
