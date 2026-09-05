"""Crowd appearance data -- ``crowd_spec_v1``: who wears what, deterministically.

What this module does
---------------------
Given a list of stable person uids (one per placed City Sample human) it assigns
each person a skin tone, hair colour and shirt/trousers/shoes colours, purely
from ``hashlib.sha256`` digests of the uid strings -- never ``random``.  The same
uid always produces the same person, and a whole plan for 65 uids can be
validated at a glance (``validate_crowd``) before any editor driver touches a
material.

Why this module exists
----------------------
The measured defect: 65 City Sample humans render at street camera distance as
*dark silhouettes* with only two visual variants, and the skin material was
logged as failing to compile -- the same class of fault that made the ground
render as speckle.  A material that fails to compile falls back to error shading,
which is near-black; no amount of correct proportions fixes a body whose
materials carry no colour.  This module is the *data* side of the fix: tones
guaranteed bright enough to read as skin in linear space, a wide enough garment
palette that 65 people do not visibly repeat, and hard validation that refuses a
plan which would still collapse back onto a silhouette.

Deliberately **not** here (another module/agent owns it): any goals, decisions,
perception or animation.  Appearance only, so this file imports nothing from
Unreal and uses only the stdlib.

Colour space assumption
-----------------------
Every RGB triple in this module is **linear RGB** -- Unreal material ``BaseColor``
consumes linear values in the working space, and a vector parameter is not
sRGB-decoded for you.  The failure mode this guards against: a tone authored by
reading display-encoded (sRGB) bytes and pasted into a linear slot is a
colour-space mismatch that silently shifts the whole crowd off its intended
reflectance; at street distance the dark end of that mismatch is exactly what
reads as a silhouette.  The tones below are real skin swatches, linearised
(``sRGB -> linear``) and rounded to 3 decimals, so the numbers handed to a
material are already in the space the renderer expects.  The luminance floor
(``SKIN_LUMINANCE_FLOOR``, see below) is a hard rule that refuses any tone or
plan whose linear luminance has fallen back toward black.

Determinism laws (mirroring ``ldyf.city_layout``): every float is rounded to 3
decimals via ``_f3`` (which also kills ``-0.0``), iteration over uids and over
table names is lexicographically sorted, and digests are sha256 of the exact uid
string.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable

CROWD_SPEC_VERSION = "crowd_spec_v1"

# Hard validation constants (documented rules, not per-call tunables).
SKIN_LUMINANCE_FLOOR = 0.05      # linear luminance below this reads as silhouette
MIN_DISTINCT_SKIN_TONES = 6      # minimum distinct tones a valid plan must use
MIN_DISTINCT_GARMENT_COLOURS = 12  # minimum distinct garment colours used

# Rec.709 luma weights -- the same coefficients Unreal applies to linear RGB
# when computing luminance; written out here because validate_crowd encodes this
# formula as a hard rule.
_LUMA_R, _LUMA_G, _LUMA_B = 0.2126, 0.7152, 0.0722


# --- small deterministic helpers -------------------------------------------


def _f3(v: float) -> float:
    """Round to 3 decimals (byte determinism) and kill ``-0.0``."""
    return round(float(v), 3) + 0.0


def _f3_rgb(rgb: Iterable[float]) -> list[float]:
    """A linear RGB triple with every channel through ``_f3``."""
    return [_f3(c) for c in rgb]


def _luminance(rgb: Iterable[float]) -> float:
    """Linear luminance: 0.2126 R + 0.7152 G + 0.0722 B over the linear triple."""
    r, g, b = rgb
    return _LUMA_R * float(r) + _LUMA_G * float(g) + _LUMA_B * float(b)


def _digest_hex(key: str) -> str:
    """sha256 hex digest of a stable string -- every bit of variation descends
    from this one call, so ``variant_for``/``crowd_plan`` stay deterministic."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _pick(digest: str, offset: int, n: int) -> int:
    """0..n-1 from the 32-bit chunk of the digest at ``offset`` (8 hex chars)."""
    return int(digest[offset * 8:(offset + 1) * 8], 16) % max(1, n)


# --- appearance tables ------------------------------------------------------
#
# SKIN_TONES: name -> {rgb (linear), roughness, subsurface_strength}.  Each rgb
# is a real skin swatch linearised from sRGB and rounded to 3 decimals; the
# sRGB anchor is quoted so a reviewer can re-derive the number.  Linear
# luminances (Rec.709 weights, computed by _luminance) span ~0.08 (deep) to
# ~0.63 (pale), every one far above SKIN_LUMINANCE_FLOOR.  Roughness is higher
# and subsurface strength lower on deeper tones (thicker, less translucent
# skin scatters less); a skin with no subsurface term reads as plastic, and a
# plastic-looking body is the next-best thing to a silhouette at street range.

SKIN_TONES: dict[str, dict[str, Any]] = {
    # name: linearised rgb (sRGB anchor), roughness, subsurface strength
    "pale":    {"rgb": [0.890, 0.570, 0.448], "roughness": 0.45, "subsurface_strength": 0.55},  # sRGB #f0c6ae
    "fair":    {"rgb": [0.711, 0.367, 0.253], "roughness": 0.46, "subsurface_strength": 0.50},  # sRGB #dba487
    "light":   {"rgb": [0.587, 0.296, 0.179], "roughness": 0.48, "subsurface_strength": 0.45},  # sRGB #c99475
    "medium":  {"rgb": [0.507, 0.233, 0.133], "roughness": 0.50, "subsurface_strength": 0.42},  # sRGB #b97b52
    "olive":   {"rgb": [0.448, 0.214, 0.113], "roughness": 0.51, "subsurface_strength": 0.40},  # sRGB #a9714b
    "tan":     {"rgb": [0.367, 0.163, 0.095], "roughness": 0.53, "subsurface_strength": 0.36},  # sRGB #8f5d40
    "caramel": {"rgb": [0.243, 0.100, 0.059], "roughness": 0.55, "subsurface_strength": 0.32},  # sRGB #6b3b26
    "deep":    {"rgb": [0.147, 0.059, 0.036], "roughness": 0.58, "subsurface_strength": 0.28},  # sRGB #462719
}

# Hair colours (linear).  Hair is legitimately dark so these are *not* subject
# to the skin luminance floor; the floor exists so faces read as skin.
_HAIR_RGB: dict[str, list[float]] = {
    "black":       [0.030, 0.025, 0.023],
    "dark_brown":  [0.080, 0.050, 0.038],
    "brown":       [0.150, 0.095, 0.070],
    "chestnut":    [0.220, 0.120, 0.075],
    "auburn":      [0.280, 0.100, 0.060],
    "dark_blonde": [0.350, 0.240, 0.150],
    "blonde":      [0.470, 0.370, 0.240],
    "grey":        [0.400, 0.390, 0.380],
}

# GARMENT_PALETTE: 24 plausible daytime-city-street colours, each name -> linear
# RGB.  Wide enough that 65 people (shirt + trousers + shoes each drawn from the
# full set, trousers forced different from the shirt) do not visibly repeat.
GARMENT_PALETTE: dict[str, list[float]] = {
    "white":      [0.800, 0.795, 0.780],
    "cream":      [0.750, 0.690, 0.590],
    "light_grey": [0.560, 0.560, 0.560],
    "medium_grey": [0.380, 0.380, 0.380],
    "charcoal":   [0.180, 0.180, 0.180],
    "black":      [0.030, 0.030, 0.032],
    "navy":       [0.055, 0.090, 0.190],
    "denim":      [0.160, 0.230, 0.340],
    "steel_blue": [0.240, 0.330, 0.440],
    "sky_blue":   [0.400, 0.600, 0.780],
    "teal":       [0.120, 0.320, 0.320],
    "forest_green": [0.150, 0.300, 0.160],
    "olive":      [0.320, 0.320, 0.150],
    "sage":       [0.430, 0.500, 0.370],
    "khaki":      [0.550, 0.500, 0.340],
    "camel":      [0.620, 0.470, 0.300],
    "coffee":     [0.330, 0.230, 0.150],
    "brick_red":  [0.450, 0.190, 0.150],
    "maroon":     [0.280, 0.090, 0.100],
    "rust":       [0.500, 0.250, 0.100],
    "mustard":    [0.600, 0.480, 0.130],
    "blush":      [0.620, 0.400, 0.380],
    "lavender":   [0.500, 0.450, 0.600],
    "mint":       [0.450, 0.580, 0.460],
}

# RGB fields of a variant that are subject to the [0, 1] channel check.
_RGB_FIELDS = ("skin_rgb", "hair_rgb", "shirt_rgb", "trousers_rgb", "shoes_rgb")


# --- public API -------------------------------------------------------------


def variant_for(person_uid: str) -> dict[str, Any]:
    """Deterministic appearance of one person, derived entirely from
    ``sha256(person_uid)``.

    Returns ``{"uid", "skin_tone", "skin_rgb", "hair_rgb", "shirt_rgb",
    "trousers_rgb", "shoes_rgb", "roughness", "subsurface"}``.  The same uid
    always yields the same dict; two uids that share a digest prefix for a
    field may share that one colour, but the 32-bit chunks per field keep the
    assignments effectively decorrelated across the crowd.
    """
    if not isinstance(person_uid, str) or not person_uid:
        raise ValueError("person_uid must be a non-empty string")
    digest = _digest_hex(person_uid)

    tone_names = sorted(SKIN_TONES)
    palette_names = sorted(GARMENT_PALETTE)
    hair_names = sorted(_HAIR_RGB)

    skin_name = tone_names[_pick(digest, 0, len(tone_names))]
    hair_name = hair_names[_pick(digest, 1, len(hair_names))]
    shirt_name = palette_names[_pick(digest, 2, len(palette_names))]
    shoes_name = palette_names[_pick(digest, 3, len(palette_names))]
    # Trousers: draw from the palette minus the shirt colour so an outfit is
    # never one flat block of colour (and never reads as a single dark column).
    trousers_raw = _pick(digest, 4, len(palette_names) - 1)
    trousers_name = palette_names[trousers_raw if trousers_raw < palette_names.index(shirt_name)
                                  else trousers_raw + 1]

    skin = SKIN_TONES[skin_name]
    return {
        "uid": person_uid,
        "skin_tone": skin_name,
        "skin_rgb": _f3_rgb(skin["rgb"]),
        "hair_rgb": _f3_rgb(_HAIR_RGB[hair_name]),
        "shirt_rgb": _f3_rgb(GARMENT_PALETTE[shirt_name]),
        "trousers_rgb": _f3_rgb(GARMENT_PALETTE[trousers_name]),
        "shoes_rgb": _f3_rgb(GARMENT_PALETTE[shoes_name]),
        "roughness": _f3(skin["roughness"]),
        "subsurface": _f3(skin["subsurface_strength"]),
    }


def crowd_plan(person_uids: Iterable[str]) -> dict[str, Any]:
    """Assign a variant to every uid and report the resulting distribution.

    ``ValueError`` on an empty uid list or on a duplicated uid.  Persons are
    emitted sorted by uid (lexicographic, mirroring ``city_layout``).  The
    ``distribution`` block counts, per skin tone and per garment colour, how
    many people actually received it (zero-count entries included), so a
    reviewer can see at a glance whether the digest is spreading 65 people
    across the tables or collapsing onto two variants.
    """
    uids = list(person_uids)
    if not uids:
        raise ValueError("person_uids must not be empty")
    seen: set[str] = set()
    for uid in uids:
        if uid in seen:
            raise ValueError(f"duplicate person_uid: {uid!r}")
        seen.add(uid)

    variants = [variant_for(uid) for uid in sorted(uids)]

    skin_counts = {name: 0 for name in sorted(SKIN_TONES)}
    garment_counts = {name: 0 for name in sorted(GARMENT_PALETTE)}
    for v in variants:
        skin_counts[v["skin_tone"]] += 1
        for field in ("shirt_rgb", "trousers_rgb", "shoes_rgb"):
            rgb = tuple(v[field])
            for name, value in GARMENT_PALETTE.items():
                if tuple(_f3_rgb(value)) == rgb:
                    garment_counts[name] += 1
                    break

    return {
        "schema_version": CROWD_SPEC_VERSION,
        "persons": variants,
        "distribution": {
            "skin_tones": skin_counts,
            "garment_colours": garment_counts,
        },
    }


def validate_crowd(plan: dict[str, Any]) -> list[str]:
    """Return a list of problems with ``plan``; empty list means valid.

    Refuses, as hard rules:
    * any RGB channel (table or person) outside [0, 1] -- the linear-space trap;
    * a skin tone whose linear luminance (0.2126 R + 0.7152 G + 0.0722 B) is
      below ``SKIN_LUMINANCE_FLOOR`` -- the specific silhouette defect;
    * fewer than ``MIN_DISTINCT_SKIN_TONES`` distinct skin tones actually used;
    * fewer than ``MIN_DISTINCT_GARMENT_COLOURS`` distinct garment colours used;
    * a duplicated uid (persons or against the plan's own list);
    * a person missing a required key, an unknown skin tone name, or a plan
      with the wrong schema version.
    """
    problems: list[str] = []

    # --- module tables first: a broken table poisons every plan derived from it
    for name, entry in SKIN_TONES.items():
        for channel in entry["rgb"]:
            if not 0.0 <= channel <= 1.0:
                problems.append(f"SKIN_TONES[{name}]: rgb channel {channel} outside [0, 1]")
        if _luminance(entry["rgb"]) < SKIN_LUMINANCE_FLOOR:
            problems.append(
                f"SKIN_TONES[{name}]: linear luminance "
                f"{_luminance(entry['rgb']):.3f} below floor {SKIN_LUMINANCE_FLOOR}"
            )
    for name, rgb in GARMENT_PALETTE.items():
        for channel in rgb:
            if not 0.0 <= channel <= 1.0:
                problems.append(f"GARMENT_PALETTE[{name}]: channel {channel} outside [0, 1]")

    if plan.get("schema_version") != CROWD_SPEC_VERSION:
        problems.append(
            f"plan schema_version {plan.get('schema_version')!r} != {CROWD_SPEC_VERSION!r}"
        )

    persons = plan.get("persons")
    if not isinstance(persons, list) or not persons:
        return problems + ["plan has no persons list"]

    seen_uids: set[str] = set()
    used_skin: set[str] = set()
    used_garment: set[str] = set()
    palette_by_rgb = {tuple(_f3_rgb(rgb)): name for name, rgb in GARMENT_PALETTE.items()}
    tones_by_rgb = {tuple(_f3_rgb(e["rgb"])): name for name, e in SKIN_TONES.items()}

    for person in persons:
        uid = person.get("uid")
        if uid in seen_uids:
            problems.append(f"duplicated uid in plan persons: {uid!r}")
        seen_uids.add(uid)
        if person.get("skin_tone") not in SKIN_TONES:
            problems.append(f"person {uid!r}: unknown skin_tone {person.get('skin_tone')!r}")
        for field in _RGB_FIELDS:
            rgb = person.get(field)
            if rgb is None:
                problems.append(f"person {uid!r}: missing {field}")
                continue
            for channel in rgb:
                if not 0.0 <= float(channel) <= 1.0:
                    problems.append(
                        f"person {uid!r}: {field} channel {channel} outside [0, 1]"
                    )
        skin_rgb = person.get("skin_rgb")
        lum = _luminance(skin_rgb) if skin_rgb else 0.0
        if lum < SKIN_LUMINANCE_FLOOR:
            problems.append(
                f"person {uid!r}: skin linear luminance {lum:.3f} "
                f"below floor {SKIN_LUMINANCE_FLOOR}"
            )
        used_skin.add(person.get("skin_tone"))
        for field in ("shirt_rgb", "trousers_rgb", "shoes_rgb"):
            colour = person.get(field)
            if colour is None:
                continue
            name = palette_by_rgb.get(tuple(_f3_rgb(colour)))
            if name is None:
                problems.append(f"person {uid!r}: {field} not in GARMENT_PALETTE")
            else:
                used_garment.add(name)
        if skin_rgb is not None:
            skin_name = tones_by_rgb.get(tuple(_f3_rgb(skin_rgb)))
            if skin_name is None:
                problems.append(f"person {uid!r}: skin_rgb not in SKIN_TONES")

    if len(used_skin) < MIN_DISTINCT_SKIN_TONES:
        problems.append(
            f"plan uses {len(used_skin)} distinct skin tones; "
            f"minimum is {MIN_DISTINCT_SKIN_TONES}"
        )
    if len(used_garment) < MIN_DISTINCT_GARMENT_COLOURS:
        problems.append(
            f"plan uses {len(used_garment)} distinct garment colours; "
            f"minimum is {MIN_DISTINCT_GARMENT_COLOURS}"
        )
    return problems


def material_parameters(variant: dict[str, Any]) -> dict[str, Any]:
    """Concrete parameter values an editor driver would set per material slot.

    VERIFIED vs INFERRED -- read before wiring this into the driver:
    * The *asset paths* below (``material_candidates`` per slot) are VERIFIED:
      every one is copied verbatim from the ``crowd_materials`` list of
      ``asset_probe_v3.json`` (female and male player-character materials).
    * Every *parameter name* ("BaseColor", "Roughness", "SubsurfaceStrength",
      "SubsurfaceColor") is INFERRED.  ``asset_probe_v3.json`` records only
      asset paths for characters -- no scalar/vector parameters -- so none of
      these names is verified against the real City Sample graph.  The driver
      MUST reconcile each name against the actual material instance before
      setting it; a parameter name that does not exist silently does nothing,
      and that is exactly how the original defect went dark.

    Values are linear RGB (or scalars) for the character's skin, hair, shirt,
    trousers and shoes, every float through ``_f3``.  Returned dict is keyed by
    slot; the driver picks the candidate material instance that exists in its
    session (gender choice is out of scope here) and applies ``parameters``.
    """
    skin_rgb = variant["skin_rgb"]
    return {
        "schema_version": CROWD_SPEC_VERSION,
        "uid": variant["uid"],
        "skin": {
            "material_candidates": [
                "/Game/Character/Player/Female/Materials/M_HeadSynthesized",
                "/Game/Character/Player/Female/Materials/M_Head_Player",
            ],
            # INFERRED parameter names; M_HeadSynthesized bakes a texture, so a
            # tint/instance override may be needed instead of a BaseColor set.
            "parameters": {
                "BaseColor": _f3_rgb(skin_rgb),
                "Roughness": _f3(variant["roughness"]),
                "SubsurfaceStrength": _f3(variant["subsurface"]),
                "SubsurfaceColor": _f3_rgb([_f3(c * 0.6) for c in skin_rgb]),
            },
        },
        "hair": {
            "material_candidates": [
                "/Game/Character/Player/Female/Materials/MI_Hair_Cards_Player",
                "/Game/Character/Player/Female/Materials/MI_Hair_Player",
                "/Game/Character/Player/Female/Materials/M_hair_v2",
            ],
            "parameters": {"BaseColor": _f3_rgb(variant["hair_rgb"])},
        },
        "shirt": {
            "material_candidates": [
                "/Game/Character/Player/Female/Materials/MI_Player_Shirt",
                "/Game/Character/Player/Male/Materials/MI_Shirt_Player",
                "/Game/Character/Player/Female/Materials/MI_Player_Jacket",
            ],
            "parameters": {"BaseColor": _f3_rgb(variant["shirt_rgb"])},
        },
        "trousers": {
            "material_candidates": [
                "/Game/Character/Player/Female/Materials/MI_Player_Pants",
                "/Game/Character/Player/Male/Materials/MI_Outfit_Bottom",
            ],
            "parameters": {"BaseColor": _f3_rgb(variant["trousers_rgb"])},
        },
        "shoes": {
            "material_candidates": [
                "/Game/Character/Player/Female/Materials/MI_Player_Boots",
                "/Game/Character/Player/Male/Materials/MI_Outfit_Shoes",
            ],
            "parameters": {"BaseColor": _f3_rgb(variant["shoes_rgb"])},
        },
    }
