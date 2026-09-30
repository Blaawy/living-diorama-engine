"""``ldyf.building_styles`` -- map our facade-family decisions onto Epic's
City Sample shape-grammar styles (schema ``building_styles_v1``).

The Director rejected custom building geometry: Epic's City Sample PCG system
owns geometry, facades, windows, ground floors and roofs.  This lane keeps the
*decisions* on our side -- which building goes where, how tall it is, which
facade family it wears, which one is the civic landmark and the seed that makes
all of it reproducible -- and hands City Sample a concrete style code plus a
level.  This module is that join.

Ground truth is the editor probe ``pcg_building_rules.json`` at the repo root:
27 style families (``style_count`` 27, line 2) and, per family, the set of
levels its shape-grammar rules cover -- 240 levels in total across the 27
``levels`` lists (lines 5-378).  ``rule_example`` is
``.../CHA/RULE_CHA_L00`` (line 408).  A style is only usable at a level it
really has a rule for: asking for a level a family does not cover is how this
silently produces nothing, so every level this module emits is clamped into the
chosen family's real level list and the clamp is reported.

Probe totals do not reconcile, so none of them is trusted
---------------------------------------------------------
The probe also declares ``total`` = 270 (line 407), but the 27 per-family
``count`` fields (lines 28-377) sum to 240 -- exactly the number of levels the
``levels`` lists enumerate.  ``total`` therefore does not describe the level
lists, and this module never compares against it; ``_check_mirror`` guards on
``style_count`` and on the level lists themselves.  *Inference*: ``total``
probably counts rule assets found in the editor rather than the subset written
into the file; this lane does not rely on that guess either way.

Style-code groups
-----------------
*Explicit evidence* from the probe: 10 ``CH*`` families, 9 ``NY*`` families,
2 ``QB*`` families, 6 ``SF*`` families; ``style_count`` is 27.
*Inference* (engineering observation -- the probe never spells these meanings
out, they are read off the level lists and the kit probe
``pcg_building_kits.json``):

``CH*``
    Dense downtown.  Holds the deepest single grammar (``CHA`` = levels 0-20,
    21 of them; ``CHC`` = 16) and is the only group that reaches level 20.
    The remaining CH families are short (``CHJ`` 4 levels, ``CHF`` 6,
    ``CHB``/``CHG`` 7, ``CHD``/``CHE``/``CHH``/``CHI`` 9-10).
``NY*``
    Mid-rise blocks.  Level lists stop between 5 (``NYAA``/``NYAD``) and 17
    (``NYG``/``NYGA``), mostly 6-8, so none is a 20-level tower and none is a
    4-level low-rise.  ``NYG``/``NYGA`` skip levels 15-16, ``NYH`` skips 6-7.
``SF*``
    Lower, finer grain.  Every SF grammar tops out at level 10 (``SFA``) or
    below (``SFB``/``SFE``/``SFJ`` 6, ``SFC``/``SFD`` 5), and the kit probe
    shows SF levels carrying dozens of meshes each (``SFD_L1_A``: 39 meshes,
    corners/walls/other) rather than the one-wall NY and CH levels.
``QB*``
    Exactly two families, ``QBA`` and ``QBAA``, with byte-identical 9-level
    lists (0-8): one block family and a duplicate of it.

Heights become levels on a 300 cm storey (``_LEVEL_CM``), matching
``building_kits._STOREY_CM``.  ``target = floor(height_cm / 300 + 0.5)`` is
clamped into the chosen family's real list and then snapped to the nearest
real level (ties to the lower one), so taller buildings never get a lower
level: the snap is a monotone projection onto a sorted set.

The clamp reported with each assignment is ``None`` (the requested level is a
real level of the chosen style), ``"high"`` (pushed down to the family's
deepest level), ``"gap"`` (the requested level falls in a hole in that family's
list, e.g. ``NYG`` has none at 15-16) or ``"low"`` (pushed up to the family's
shallowest level).  ``"low"`` is defensive only: every family in the probe
starts at level 0 and heights are required to be positive, so a negative
requested level is the only way to reach it.

Pure stdlib, deterministic (sha256 only, never ``random``), no ``import
unreal``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "building_styles_v1"

PROBE_FILENAME = "pcg_building_rules.json"

#: Root of the building data assets, as the probe shows it
#: (``pcg_building_rules.json`` -> ``rule_example``).
_RULE_ROOT = "/CitySamplePCG/PCG/DataAssets/Buildings"

#: Documented rule-asset pattern.  Level is zero-padded to two digits exactly
#: as the probe shows it: ``.../CHA/RULE_CHA_L00`` .. ``RULE_CHA_L20``.
RULE_ASSET_RE = (
    r"^/CitySamplePCG/PCG/DataAssets/Buildings/[A-Z]{2,4}"
    r"/RULE_[A-Z]{2,4}_L[0-9]{2}$"
)
_RULE_ASSET_RE_C = re.compile(RULE_ASSET_RE)

#: Storey height (cm) used to turn our height decision into a grammar level.
#: Mirrors ``building_kits._STOREY_CM`` (300.0).
_LEVEL_CM = 300.0

# ---------------------------------------------------------------------------
# 1. style families -- mirror of pcg_building_rules.json + import-time check
# ---------------------------------------------------------------------------

#: Literal mirror of ``pcg_building_rules.json["styles"]`` (style -> the real
#: levels its shape-grammar rules cover).  ``_check_mirror`` below fails the
#: import if this ever drifts from the probe file, so the two cannot diverge.
MIRRORED_STYLE_FAMILIES: dict[str, tuple[int, ...]] = {
    # CH* -- dense downtown (see module docstring).
    "CHA": tuple(range(0, 21)),                          # 21 levels
    "CHB": tuple(range(0, 7)),                           # 7
    "CHC": tuple(range(0, 16)),                          # 16
    "CHD": tuple(range(0, 9)),                           # 9
    "CHE": tuple(range(0, 10)),                          # 10
    "CHF": tuple(range(0, 6)),                           # 6
    "CHG": tuple(range(0, 7)),                           # 7
    "CHH": tuple(range(0, 10)),                          # 10
    "CHI": tuple(range(0, 10)),                          # 10
    "CHJ": tuple(range(0, 4)),                           # 4
    # NY* -- mid-rise blocks.
    "NYAA": tuple(range(0, 6)),                          # 6
    "NYAB": tuple(range(0, 7)),                          # 7
    "NYAC": tuple(range(0, 7)),                          # 7
    "NYAD": tuple(range(0, 6)),                          # 6
    "NYAE": tuple(range(0, 7)),                          # 7
    "NYAF": tuple(range(0, 8)),                          # 8
    "NYG": tuple(range(0, 15)) + (17,),                  # 16, skips 15-16
    "NYGA": tuple(range(0, 15)) + (17,),                 # 16, skips 15-16
    "NYH": tuple(range(0, 6)) + tuple(range(8, 13)),     # 11, skips 6-7
    # QB* -- block family and its duplicate.
    "QBA": tuple(range(0, 9)),                           # 9
    "QBAA": tuple(range(0, 9)),                          # 9
    # SF* -- lower, finer grain.
    "SFA": tuple(range(0, 10)),                          # 10
    "SFB": tuple(range(0, 6)),                           # 6
    "SFC": tuple(range(0, 5)),                           # 5
    "SFD": tuple(range(0, 5)),                           # 5
    "SFE": tuple(range(0, 6)),                           # 6
    "SFJ": tuple(range(0, 6)),                           # 6
}

#: ``style_count`` in the probe file (line 2).
MIRRORED_STYLE_COUNT = 27


def probe_path() -> Path:
    """Path of the editor probe at the repo root."""
    return Path(__file__).resolve().parent.parent / PROBE_FILENAME


def read_probe_rules(path: Path | None = None) -> dict[str, Any] | None:
    """The probe JSON, or ``None`` if it is not on disk.

    ``None`` only happens outside the repo checkout; the import-time check
    below is skipped in that case so the module still works from the mirror.
    Tests assert the file is present, so the check does run where it matters.
    """
    target = Path(path) if path is not None else probe_path()
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except OSError:
        return None


def probe_style_levels(probe: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
    """``styles`` of a probe document as ``style -> tuple(levels)``."""
    out: dict[str, tuple[int, ...]] = {}
    for style, entry in probe["styles"].items():
        out[str(style)] = tuple(int(level) for level in entry["levels"])
    return out


#: Number of levels the probe enumerates, i.e. the number of rule assets this
#: module can name: 240 across the 27 families.  Deliberately *not* the probe's
#: ``total`` field (270), which does not equal the sum of its own ``count``
#: fields -- see the module docstring.
ENUMERATED_RULE_COUNT = sum(len(v) for v in MIRRORED_STYLE_FAMILIES.values())


def _check_mirror() -> None:
    """Import guard: the literal mirror must equal the probe file.

    Raises ``AssertionError`` naming the differing families, so a re-probed
    editor cannot silently leave this module emitting levels that no longer
    have a rule.  The probe's ``total`` field is deliberately not compared:
    it does not reconcile with the per-family ``count`` fields.
    """
    probe = read_probe_rules()
    if probe is None:  # pragma: no cover - probe absent, mirror is all we have
        return
    live = probe_style_levels(probe)
    missing = sorted(set(live) - set(MIRRORED_STYLE_FAMILIES))
    extra = sorted(set(MIRRORED_STYLE_FAMILIES) - set(live))
    changed = sorted(k for k in set(live) & set(MIRRORED_STYLE_FAMILIES)
                     if live[k] != MIRRORED_STYLE_FAMILIES[k])
    if missing or extra or changed:
        raise AssertionError(
            f"{PROBE_FILENAME} and MIRRORED_STYLE_FAMILIES have drifted: "
            f"new in probe={missing}, missing from probe={extra}, "
            f"changed levels={changed}"
        )
    declared = int(probe.get("style_count", -1))
    if declared != len(MIRRORED_STYLE_FAMILIES):
        raise AssertionError(
            f"{PROBE_FILENAME} declares style_count={declared} but the "
            f"mirror has {len(MIRRORED_STYLE_FAMILIES)} families"
        )


_check_mirror()

#: Style family -> the real levels it has rules for.  Content is identical to
#: ``MIRRORED_STYLE_FAMILIES`` (checked at import) and is what every function
#: below reads.
STYLE_FAMILIES: dict[str, tuple[int, ...]] = dict(MIRRORED_STYLE_FAMILIES)

STYLE_COUNT = len(STYLE_FAMILIES)


def style_levels(style: str) -> tuple[int, ...]:
    """Real levels of ``style``; ``KeyError`` if the probe does not list it."""
    return STYLE_FAMILIES[style]


def rule_asset_path(style: str, level: int) -> str:
    """``/CitySamplePCG/PCG/DataAssets/Buildings/<STYLE>/RULE_<STYLE>_L<NN>``.

    Level is zero-padded to two digits exactly as the probe shows it
    (``RULE_CHA_L00`` .. ``RULE_CHA_L20``).
    """
    return f"{_RULE_ROOT}/{style}/RULE_{style}_L{int(level):02d}"


# ---------------------------------------------------------------------------
# 2. our facade families -> acceptable City Sample families
# ---------------------------------------------------------------------------

#: Our civic family, mirroring ``building_kits.CIVIC_FAMILY`` ("civic_stone");
#: never handed to an ordinary building.
CIVIC_FAMILY = "civic_stone"

#: Our six facade families plus the landmark's ``civic_stone``, each mapped to
#: City Sample families that read the same way.  Reasons live in
#: ``FAMILY_GROUP_REASONS`` (one entry per family, checked at import).
FAMILY_GROUPS: dict[str, tuple[str, ...]] = {
    # brick: our lowest, finest-grain masonry.
    "brick": ("SFA", "SFB", "SFC", "SFD", "SFE", "SFJ"),
    # concrete: the downtown core material.
    "concrete": ("CHC", "CHD", "CHH", "CHI"),
    # granite_dark: the short downtown stone forms.
    "granite_dark": ("CHB", "CHF", "CHG", "CHJ"),
    # granite_light: pale mid-rise block cladding.
    "granite_light": ("NYAA", "NYAB", "NYAC"),
    # limestone: institutional mid-rise stone, including the tall NY office
    # blocks (NYG/NYGA reach 17) and the 11-level NYH.
    "limestone": ("NYAD", "NYAE", "NYAF", "NYG", "NYGA", "NYH"),
    # painted_stone: low, blocky, repainted street fabric.
    "painted_stone": ("QBA", "QBAA", "NYAD", "NYAE"),
    # civic_stone: the landmark only.
    CIVIC_FAMILY: ("CHA",),
}

FAMILY_GROUP_REASONS: dict[str, str] = {
    "brick": (
        "brick is our lowest, finest-grain masonry, and the SF* group is the "
        "only one whose grammars stop at level 10 or below (SFA 10, SFB/SFE/"
        "SFJ 6, SFC/SFD 5); the kit probe shows SF levels built from dozens of "
        "small meshes (SFD_L1_A: 39), which is the grain we want for brick."
    ),
    "concrete": (
        "plain unpainted concrete is the downtown-core material, so the dense-"
        "downtown CH* group; CHA (21 levels) is withheld for the landmark, and "
        "CHC's 16 levels give concrete the tallest ordinary range (level 15) "
        "so a concrete tower still reads tall without competing with CHA."
    ),
    "granite_dark": (
        "dark dressed granite reads as the older, pedestrian-scale stone plinth "
        "rather than a tower, so exactly the short CH* families (CHB 7, CHF 6, "
        "CHG 7, CHJ 4 levels) -- all the downtown forms that stop below level 7."
    ),
    "granite_light": (
        "pale granite is the classic mid-rise block cladding; the NY* group is "
        "the mid-rise group (6-17 levels, mostly 6-8), and the three shortest "
        "NY families keep light granite on block-scale massing."
    ),
    "limestone": (
        "limestone is institutional/office stone and must be able to go tall on "
        "a mid-rise block, so the short NY families plus NYG/NYGA (the two "
        "17-level NY grammars, which also skip levels 15-16) and NYH."
    ),
    "painted_stone": (
        "repainted stone is our low, blocky street fabric: the only QB* "
        "families (QBA and its duplicate QBAA, 9 levels each) plus the two "
        "shortest NY families (NYAD 6, NYAE 7 levels)."
    ),
    CIVIC_FAMILY: (
        "the civic landmark: CHA is the widest and deepest grammar in the probe "
        "(21 levels, 0-20) and the only family that reaches level 20, so a "
        "civic building placed in it is unambiguously the biggest thing on the "
        "street."
    ),
}

#: Our families that ordinary buildings may wear (everything but civic_stone).
ORDINARY_FAMILIES: tuple[str, ...] = tuple(
    sorted(f for f in FAMILY_GROUPS if f != CIVIC_FAMILY)
)

for _fam, _targets in FAMILY_GROUPS.items():
    if not _targets:  # pragma: no cover - import guard
        raise AssertionError(f"family {_fam!r} maps to no City Sample family")
    for _target in _targets:
        if _target not in STYLE_FAMILIES:  # pragma: no cover - import guard
            raise AssertionError(
                f"family {_fam!r} maps to {_target!r}, which is not in "
                f"{PROBE_FILENAME}"
            )
    if not FAMILY_GROUP_REASONS.get(_fam, "").strip():  # pragma: no cover
        raise AssertionError(f"family {_fam!r} has no documented reason")

# ---------------------------------------------------------------------------
# 3. the civic landmark
# ---------------------------------------------------------------------------

#: The highest level any ordinary family can reach (NYG/NYGA -> 17).  The
#: landmark is floored strictly above this, which is what makes it the tallest
#: building in any assignment set this module produced.
ORDINARY_MAX_LEVEL = max(
    max(STYLE_FAMILIES[target])
    for fam, targets in FAMILY_GROUPS.items() if fam != CIVIC_FAMILY
    for target in targets
)

#: Mirrors ``building_kits.LANDMARK_MIN_HEIGHT_CM`` (5600.0 cm).
LANDMARK_MIN_HEIGHT_CM = 5600.0

#: Landmark style: the deepest grammar in the probe.
LANDMARK_STYLE = "CHA"

#: Lowest level the landmark may use: strictly above every ordinary family and
#: at least ``LANDMARK_MIN_HEIGHT_CM`` of storeys.
LANDMARK_LEVEL_FLOOR = max(
    ORDINARY_MAX_LEVEL + 1,
    int(math.ceil(LANDMARK_MIN_HEIGHT_CM / _LEVEL_CM)),
)

#: The landmark picks from the top of CHA: every level at or above the floor.
LANDMARK_SLICE: tuple[int, ...] = tuple(
    level for level in STYLE_FAMILIES[LANDMARK_STYLE]
    if level >= LANDMARK_LEVEL_FLOOR
)

if not LANDMARK_SLICE:  # pragma: no cover - import guard
    raise AssertionError(
        f"{LANDMARK_STYLE} has no level at or above {LANDMARK_LEVEL_FLOOR}"
    )

# ---------------------------------------------------------------------------
# small deterministic helpers
# ---------------------------------------------------------------------------


def _f3(v: float) -> float:
    """Round to 3 decimals and kill ``-0.0`` (byte determinism)."""
    r = round(float(v), 3)
    return 0.0 if r == 0.0 else r


def _digest(*parts: Any) -> int:
    """Deterministic int from the first 16 hex chars of a sha256 digest."""
    text = "|".join(str(p) for p in parts)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def _pick(options: tuple[str, ...] | tuple[int, ...], building_id: Any,
          family: str, seed: Any) -> Any:
    """sha256-driven choice from ``options`` (never ``random``)."""
    return options[_digest(building_id, family, seed) % len(options)]


def _height_cm(height_cm: Any) -> float:
    """Strictly positive height in cm, else ``ValueError``."""
    if isinstance(height_cm, bool) or not isinstance(height_cm, (int, float)):
        raise ValueError(
            f"height_cm must be a positive number, got {height_cm!r}"
        )
    h = float(height_cm)
    if not h > 0.0:
        raise ValueError(f"height_cm must be positive, got {height_cm!r}")
    return h


def _target_level(height_cm: float) -> int:
    """Our height -> the grammar level we would ask for (300 cm storeys)."""
    return int(math.floor(height_cm / _LEVEL_CM + 0.5))


def _resolve_level(style: str, requested: int) -> tuple[int, str | None]:
    """Clamp/snap ``requested`` onto ``style``'s real levels.

    Returns ``(level, clamp)`` where ``clamp`` is ``None`` when ``requested``
    is a real level of ``style``, ``"high"`` when it was pushed down into the
    family's range, ``"gap"`` when it fell in a hole in the family's list
    (``NYG``/``NYGA`` skip 15-16, ``NYH`` skips 6-7) and ``"low"`` when it was
    pushed up.  ``"low"`` cannot be reached from :func:`assign_style`, whose
    heights are strictly positive, because every family in the probe starts at
    level 0; it is kept for completeness and for direct callers.
    """
    levels = STYLE_FAMILIES[style]
    clamp: str | None = None
    target = requested
    if target < levels[0]:
        clamp, target = "low", levels[0]
    elif target > levels[-1]:
        clamp, target = "high", levels[-1]
    # nearest real level; ties go to the lower one.  Monotone in ``requested``.
    level = min(levels, key=lambda lv: (abs(lv - target), lv))
    if clamp is None and level != requested:
        clamp = "gap"
    return level, clamp


def _assignment(style: str, level: int, height_cm: float, family: str,
                requested_level: int, clamp: str | None,
                is_landmark: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "style": style,
        "level": level,
        "rule_asset": rule_asset_path(style, level),
        "height_cm": _f3(height_cm),
        "levels_available": list(STYLE_FAMILIES[style]),
        "family": family,
        "requested_level": requested_level,
        "level_height_cm": _f3(level * _LEVEL_CM),
        "clamp": clamp,
    }
    if is_landmark:
        out["is_landmark"] = True
    return out


# ---------------------------------------------------------------------------
# 4. the join
# ---------------------------------------------------------------------------


def assign_style(building_id: Any, family: str, height_cm: Any, *,
                 seed: Any) -> dict[str, Any]:
    """One of our buildings -> a real City Sample style and level.

    ``family`` is one of ``FAMILY_GROUPS`` (the six ordinary facade families;
    ``civic_stone`` is reserved for :func:`assign_landmark`).  The City Sample
    family is chosen from that group by sha256 of ``building_id|family|seed``,
    so the same inputs always give the same style and neighbouring ids do not
    march down the list in order.

    ``height_cm`` becomes a grammar level at 300 cm per storey and is clamped
    onto the chosen family's real levels; ``clamp`` reports ``None`` (the
    requested level exists), ``"low"`` or ``"high"`` (pushed into the family's
    range) or ``"gap"`` (requested level falls in a hole in that family's
    list).  ``height_cm`` is our input echoed back -- the height decision stays
    ours; ``level_height_cm`` is what the level will actually build.

    ``ValueError`` for a family we have no mapping for, or a non-positive
    height.
    """
    if family not in FAMILY_GROUPS:
        known = ", ".join(sorted(FAMILY_GROUPS))
        raise ValueError(f"unknown facade family {family!r}; known: {known}")
    height = _height_cm(height_cm)

    style = _pick(FAMILY_GROUPS[family], building_id, family, seed)
    requested = _target_level(height)
    level, clamp = _resolve_level(style, requested)
    return _assignment(style, level, height, family, requested, clamp)


def assign_landmark(building_id: Any, *, seed: Any) -> dict[str, Any]:
    """The civic landmark -- visibly different from its neighbours.

    It wears ``LANDMARK_STYLE`` (``CHA``, the probe's deepest grammar: 21
    levels, 0-20, the only family that reaches level 20) and picks from
    ``LANDMARK_SLICE``, the top of that range at or above
    ``LANDMARK_LEVEL_FLOOR``.  That floor is strictly above the highest level
    any ordinary family can reach, so the landmark is the tallest building in
    any set this module produced, and it never shares a style *or* a level with
    the concrete downtown blocks around it.  Its height comes from its level
    (level x 300 cm) and is at least ``LANDMARK_MIN_HEIGHT_CM``.

    This is why it reads as civic: civic buildings are the ones the whole
    grammar has the most room to elaborate (21 levels of shape rules) at a
    height and storey count nothing else in the city reaches.
    """
    level = _pick(LANDMARK_SLICE, building_id, CIVIC_FAMILY, seed)
    height = level * _LEVEL_CM
    return _assignment(LANDMARK_STYLE, level, height, CIVIC_FAMILY, level,
                       None, is_landmark=True)


# ---------------------------------------------------------------------------
# 5. validation
# ---------------------------------------------------------------------------


def _entries(assignments: Any) -> list[tuple[Any, Any]]:
    """``[(key, assignment)]`` from a mapping or an iterable of dicts."""
    if isinstance(assignments, Mapping):
        return list(assignments.items())
    return [(None, a) for a in assignments]


def validate_styles(assignments: Any) -> list[str]:
    """Problems with ``assignments``; an empty list means valid.

    Accepts a mapping ``{building_id: assignment}`` or any iterable of
    assignment dicts (as returned by :func:`assign_style` /
    :func:`assign_landmark`).  Catches:

    * a style that is not one of the families in ``PROBE_FILENAME``;
    * a level the chosen style has no rule for;
    * a ``rule_asset`` that does not match :data:`RULE_ASSET_RE`, or that does
      not equal the documented path for that style and level;
    * one of our families with no entry in ``FAMILY_GROUPS`` (and a style that
      is not an acceptable target for the family it wears);
    * a landmark that is not taller than every ordinary building in the same
      assignment set (compared on level, which is what City Sample resolves
      into geometry; the requested ``height_cm`` stays our input and may
      legitimately exceed the style's range -- that is what ``clamp`` reports).
    """
    problems: list[str] = []
    landmarks: list[tuple[str, int]] = []
    ordinary: list[tuple[str, int]] = []

    for key, a in _entries(assignments):
        if not isinstance(a, Mapping):
            problems.append(f"{key!r}: assignment is not a mapping")
            continue
        label = str(key) if key is not None else str(a.get("building_id", "?"))
        style = a.get("style")
        level = a.get("level")
        family = a.get("family")
        path = a.get("rule_asset")
        is_int = isinstance(level, int) and not isinstance(level, bool)

        if style not in STYLE_FAMILIES:
            problems.append(
                f"{label}: style {style!r} is not one of the {STYLE_COUNT} "
                f"families in {PROBE_FILENAME}"
            )
        else:
            if level not in STYLE_FAMILIES[style]:
                problems.append(
                    f"{label}: {style} has no rule for level {level!r} "
                    f"(available {list(STYLE_FAMILIES[style])})"
                )
            expected = rule_asset_path(style, level) if is_int else None
            if not isinstance(path, str) or not _RULE_ASSET_RE_C.match(path):
                problems.append(
                    f"{label}: rule_asset {path!r} does not match "
                    f"{RULE_ASSET_RE}"
                )
            elif expected is not None and path != expected:
                problems.append(
                    f"{label}: rule_asset {path!r} is not the documented path "
                    f"{expected!r} for {style} level {level}"
                )

        if family not in FAMILY_GROUPS:
            problems.append(
                f"{label}: family {family!r} has no entry in FAMILY_GROUPS"
            )
        elif style in STYLE_FAMILIES and style not in FAMILY_GROUPS[family]:
            problems.append(
                f"{label}: style {style!r} is not an acceptable target for "
                f"family {family!r} ({list(FAMILY_GROUPS[family])})"
            )

        if is_int:
            if a.get("is_landmark") or family == CIVIC_FAMILY:
                landmarks.append((label, level))
            else:
                ordinary.append((label, level))

    top = max((lv for _, lv in ordinary), default=None)
    for label, lv in landmarks:
        if top is not None and lv <= top:
            tallest = max(ordinary, key=lambda item: item[1])
            problems.append(
                f"{label}: landmark is not taller than every ordinary "
                f"building (landmark level {lv}, {tallest[0]} level "
                f"{tallest[1]})"
            )
    return problems
