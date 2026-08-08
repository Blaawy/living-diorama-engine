"""Visual style profiles for the Phase 15 style bake-off.

Pure Python by design -- no ``bpy``. A style profile is a bundle of visual
OVERRIDES applied on top of the reviewed Phase 15 look: material construction
parameters, the lighting rig, scene settings, and a practical-light scale.
Style ``a`` is the identity profile (no overrides at all), so the benchmark
appearance is preserved exactly; ``b`` and ``c`` restyle the SAME world.

Profiles never touch geography: no district positions, roads, wall stations,
landmark locations, topology, or camera anchors live here. A profile can only
change how the one persistent world is surfaced and lit.
"""

STYLE_NAMES = ("a", "b", "c")

MATERIAL_ROLES = (
    "concrete",
    "concrete_dark",
    "scar_concrete",
    "facade_civic",
    "facade_residential",
    "facade_terrace",
    "facade_port",
    "curb",
    "pavement",
    "asphalt",
    "road_marking",
    "platform",
    "terrain",
    "water",
    "foliage",
    "bark",
    "metal_dark",
    "metal_civic",
    "metal_gate",
    "frame_metal",
    "roof_dark",
    "gold",
    "glass_civic",
    "glass_port",
    "glass_residential",
    "glass_terrace",
    "glass_dark",
    "interior_glow",
    "warm_light",
    "cool_light",
    "edge_glow",
    "seal_glow",
    "warning_red",
    "hazard",
    "container_a",
    "container_b",
    "container_c",
)
"""Every material role the family owns; profile overrides must stay inside it.

The Blender runtime asserts its construction table matches this tuple, so the
pure tests can validate profiles without importing ``bpy``.
"""

_BASE_LIGHTING: dict[str, object] = {
    "sun_elevation_deg": -0.8,
    "sun_rotation_deg": 250.0,
    "sun_intensity": 1.0,
    "air_density": 1.35,
    "dust_density": 2.2,
    "ozone_density": 1.8,
    "background_strength": 0.85,
    "key_location": (-170.0, 30.0, 34.0),
    "key_energy": 52000.0,
    "key_color": (1.0, 0.44, 0.16),
    "key_size": 95.0,
    "fill_location": (125.0, 70.0, 125.0),
    "fill_energy": 16000.0,
    "fill_color": (0.44, 0.57, 1.0),
    "fill_size": 170.0,
    "volume_density": 0.00095,
    "volume_anisotropy": 0.5,
}

_BASE_SETTINGS: dict[str, object] = {
    "exposure": 1.5,
    "look": "AgX - Medium High Contrast",
}

_STYLE_A: dict[str, object] = {
    "name": "a",
    "title": "Premium Stylized Cinematic 3D (benchmark)",
    "materials": {},
    "lighting": {},
    "settings": {},
    "practical_scale": 1.0,
}

_STYLE_B: dict[str, object] = {
    "name": "b",
    "title": "Semi-Stylized Architectural Macro Diorama",
    "materials": {
        "concrete": {
            "color": (0.52, 0.50, 0.455),
            "value_variation": 0.04,
            "grain_strength": 0.012,
        },
        "concrete_dark": {"color": (0.165, 0.16, 0.152), "grime_height": 0.0},
        "scar_concrete": {
            "color": (0.030, 0.031, 0.035),
            "streaks": 0.0,
            "grime_height": 0.0,
            "roughness": 0.6,
            "grain_strength": 0.012,
        },
        "facade_civic": {
            "color": (0.55, 0.52, 0.465),
            "value_variation": 0.04,
            "grain_strength": 0.012,
        },
        "facade_residential": {
            "color": (0.465, 0.34, 0.26),
            "roughness": 0.7,
            "grime_height": 0.0,
            "value_variation": 0.05,
        },
        "facade_terrace": {"color": (0.42, 0.43, 0.43), "grain_strength": 0.012},
        "facade_port": {
            "color": (0.145, 0.14, 0.132),
            "roughness": 0.42,
            "metallic": 0.9,
            "variation": 0.05,
        },
        "curb": {"color": (0.42, 0.41, 0.39)},
        "pavement": {"color": (0.30, 0.29, 0.27), "roughness": 0.7, "grain_strength": 0.01},
        "asphalt": {"color": (0.055, 0.055, 0.058), "roughness": 0.55, "grain_strength": 0.012},
        "road_marking": {"color": (0.75, 0.74, 0.70)},
        "platform": {
            "color": (0.24, 0.235, 0.225),
            "roughness": 0.5,
            "metallic": 0.05,
            "variation": 0.04,
        },
        "terrain": {"color": (0.205, 0.198, 0.178), "roughness": 0.85, "grain_strength": 0.08},
        "water": {"roughness": 0.14, "bump_strength": 0.03},
        "foliage": {"color": (0.088, 0.118, 0.072), "roughness": 0.8, "grain_strength": 0.3},
        "bark": {"color": (0.12, 0.096, 0.072)},
        "metal_dark": {"color": (0.105, 0.105, 0.11), "roughness": 0.4, "variation": 0.05},
        "metal_civic": {"color": (0.125, 0.15, 0.16), "roughness": 0.4, "variation": 0.05},
        "metal_gate": {"color": (0.092, 0.094, 0.10), "roughness": 0.45, "variation": 0.06},
        "frame_metal": {"color": (0.072, 0.074, 0.08)},
        "roof_dark": {"color": (0.125, 0.125, 0.128), "grain_strength": 0.02},
        "gold": {"color": (0.82, 0.575, 0.195), "rough_min": 0.10, "rough_max": 0.22},
        "glass_civic": {"strength": 0.9, "unlit_roughness": 0.24},
        "glass_port": {"strength": 0.8, "unlit_roughness": 0.24},
        "glass_residential": {"strength": 0.95, "unlit_roughness": 0.24},
        "glass_terrace": {"strength": 0.95, "unlit_roughness": 0.24},
        "glass_dark": {"unlit_roughness": 0.24},
        "interior_glow": {"strength": 0.9},
        "warm_light": {"strength": 9.0},
        "cool_light": {"strength": 1.0},
        "edge_glow": {"strength": 0.4},
        "seal_glow": {"strength": 3.5},
        "warning_red": {"strength": 6.0},
        "container_a": {"color": (0.30, 0.13, 0.09)},
        "container_b": {"color": (0.11, 0.19, 0.22)},
        "container_c": {"color": (0.14, 0.17, 0.11)},
    },
    "lighting": {
        "sun_elevation_deg": 10.0,
        "sun_rotation_deg": 235.0,
        "air_density": 1.0,
        "dust_density": 1.1,
        "ozone_density": 1.2,
        "background_strength": 0.95,
        "key_location": (-140.0, 60.0, 85.0),
        "key_energy": 30000.0,
        "key_color": (1.0, 0.72, 0.50),
        "key_size": 120.0,
        "fill_energy": 18000.0,
        "fill_color": (0.86, 0.90, 1.0),
        "volume_density": 0.00012,
        "volume_anisotropy": 0.3,
    },
    "settings": {"exposure": 0.7},
    "practical_scale": 0.5,
}

_STYLE_C: dict[str, object] = {
    "name": "c",
    "title": "Living Museum Hybrid",
    "materials": {
        "scar_concrete": {"color": (0.155, 0.158, 0.168), "streaks": 0.4, "grime_height": 2.2},
        "facade_civic": {"color": (0.47, 0.445, 0.395), "grain_strength": 0.02},
        "facade_residential": {"color": (0.36, 0.235, 0.16), "grime_height": 0.4},
        "facade_terrace": {"color": (0.285, 0.30, 0.31)},
        "concrete": {"color": (0.43, 0.415, 0.38)},
        "pavement": {"color": (0.185, 0.178, 0.163)},
        "terrain": {"color": (0.036, 0.043, 0.030)},
        "platform": {"roughness": 0.3, "metallic": 0.3},
        "water": {"roughness": 0.035},
        "gold": {"color": (0.90, 0.655, 0.215), "rough_min": 0.10, "rough_max": 0.26},
        "glass_civic": {"strength": 1.8},
        "glass_port": {"strength": 1.9},
        "glass_residential": {"strength": 2.2},
        "glass_terrace": {"strength": 2.3},
        "interior_glow": {"strength": 2.2},
        "warm_light": {"strength": 24.0},
        "edge_glow": {"strength": 2.2, "color": (0.70, 0.80, 1.0)},
        "seal_glow": {"strength": 6.5},
    },
    "lighting": {
        "sun_elevation_deg": -5.0,
        "background_strength": 0.10,
        "dust_density": 1.8,
        "key_location": (-120.0, -40.0, 110.0),
        "key_energy": 140000.0,
        "key_color": (1.0, 0.72, 0.45),
        "key_size": 30.0,
        "fill_location": (110.0, 20.0, 60.0),
        "fill_energy": 15000.0,
        "fill_color": (0.36, 0.48, 1.0),
        "fill_size": 120.0,
        "volume_density": 0.0012,
        "volume_anisotropy": 0.55,
    },
    "settings": {"exposure": 1.5},
    "practical_scale": 1.4,
}

DNA_STYLE = "dna"

_STYLE_DNA: dict[str, object] = {
    "name": "dna",
    "title": "Living Diorama Macro-to-Monumental Visual DNA V1",
    "materials": {
        "concrete": {"color": (0.46, 0.44, 0.40), "grain_strength": 0.02},
        "concrete_dark": {"color": (0.14, 0.138, 0.132), "grime_height": 0.6},
        "scar_concrete": {
            "color": (0.045, 0.047, 0.052),
            "streaks": 0.25,
            "grime_height": 1.2,
            "roughness": 0.62,
            "grain_strength": 0.02,
        },
        "facade_civic": {"color": (0.48, 0.45, 0.40), "grain_strength": 0.02},
        "facade_residential": {
            "color": (0.40, 0.28, 0.20),
            "roughness": 0.74,
            "grime_height": 0.4,
        },
        "facade_terrace": {"color": (0.33, 0.35, 0.36), "grain_strength": 0.02},
        "facade_port": {"color": (0.10, 0.096, 0.09), "roughness": 0.46, "variation": 0.07},
        "curb": {"color": (0.34, 0.33, 0.31)},
        "pavement": {"color": (0.24, 0.232, 0.216), "grain_strength": 0.02},
        "asphalt": {"color": (0.042, 0.042, 0.046), "roughness": 0.6, "grain_strength": 0.02},
        "road_marking": {"color": (0.68, 0.67, 0.63)},
        "platform": {
            "color": (0.05, 0.052, 0.058),
            "roughness": 0.35,
            "metallic": 0.3,
            "variation": 0.08,
        },
        "terrain": {"color": (0.085, 0.095, 0.070), "roughness": 0.9, "grain_strength": 0.18},
        "foliage": {"color": (0.060, 0.090, 0.050), "grain_strength": 0.35},
        "bark": {"color": (0.085, 0.068, 0.050)},
        "metal_dark": {"color": (0.070, 0.072, 0.078), "roughness": 0.45, "variation": 0.07},
        "metal_civic": {"color": (0.080, 0.100, 0.110), "roughness": 0.42, "variation": 0.06},
        "metal_gate": {"color": (0.060, 0.062, 0.068), "roughness": 0.48, "variation": 0.1},
        "frame_metal": {"color": (0.050, 0.051, 0.056)},
        "roof_dark": {"color": (0.070, 0.070, 0.072), "grain_strength": 0.04},
        "water": {"roughness": 0.05},
        "gold": {"color": (0.88, 0.64, 0.21), "rough_min": 0.10, "rough_max": 0.24},
        "glass_civic": {"strength": 1.6, "unlit_roughness": 0.12},
        "glass_port": {"strength": 1.5, "unlit_roughness": 0.12},
        "glass_residential": {"strength": 1.9, "unlit_roughness": 0.12},
        "glass_terrace": {"strength": 1.9, "unlit_roughness": 0.12},
        "glass_dark": {"unlit_roughness": 0.12},
        "interior_glow": {"strength": 1.9},
        "warm_light": {"strength": 20.0},
        "edge_glow": {"strength": 2.8, "color": (0.75, 0.83, 1.0)},
        "seal_glow": {"strength": 6.0},
        "warning_red": {"strength": 10.0},
    },
    "lighting": {
        "sun_elevation_deg": -3.0,
        "sun_rotation_deg": 250.0,
        "dust_density": 2.0,
        "background_strength": 0.30,
        "key_location": (-140.0, -10.0, 70.0),
        "key_energy": 110000.0,
        "key_color": (1.0, 0.70, 0.42),
        "key_size": 55.0,
        "fill_location": (115.0, 30.0, 70.0),
        "fill_energy": 15500.0,
        "fill_color": (0.45, 0.57, 1.0),
        "fill_size": 130.0,
        "volume_density": 0.0011,
        "volume_anisotropy": 0.5,
    },
    "settings": {"exposure": 1.25},
    "practical_scale": 1.15,
}

_PROFILES = {"a": _STYLE_A, "b": _STYLE_B, "c": _STYLE_C, "dna": _STYLE_DNA}


def resolve_style(name: str) -> dict:
    """Return one style profile with fully-resolved lighting and settings.

    Raises:
        ValueError: If the style name is unknown.
    """
    if name not in _PROFILES:
        raise ValueError(f"unknown style {name!r}; expected one of {(*STYLE_NAMES, DNA_STYLE)}")
    profile = _PROFILES[name]
    lighting = dict(_BASE_LIGHTING)
    lighting.update(profile["lighting"])
    settings = dict(_BASE_SETTINGS)
    settings.update(profile["settings"])
    return {
        "name": profile["name"],
        "title": profile["title"],
        "materials": dict(profile["materials"]),
        "lighting": lighting,
        "settings": settings,
        "practical_scale": profile["practical_scale"],
    }
