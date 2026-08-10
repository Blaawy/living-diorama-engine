"""Population Presence Spec V1: loading, validation, and the density contract.

Pure Python by design -- this module never imports ``bpy``, so the Phase 18
presence contract can be validated and tested without Blender. The Blender
population builder imports it; nothing here imports Blender modules.

The Population Presence Spec is a VISIBILITY POLICY, not a simulation. It
declares how an authoritative district population becomes a number of
representative visual proxies, how many stable slots each district owns, which
pedestrian zone types the city offers and how a district's presence is spread
across them, the small deterministic vocabulary of bodies and poses, and the
proof configuration.

It never defines simulation entities, and it deliberately cannot express one:
there is no place in this schema to name a citizen, give one a home, a job, a
route, or a schedule. A proxy is a REPRESENTATIVE POPULATION PROXY -- one
visible body standing for ``residents_per_proxy`` real residents of its
district -- and the manifest says so in those words.

The scaling rule is the whole truth claim of Phase 18, so it lives here rather
than in the planner::

    population < visibility_threshold          -> 0 proxies
    otherwise  clamp(floor(population / residents_per_proxy),
                     min_proxies_per_district,
                     max_proxies_per_district)

Every value is validated aggressively and every contradiction is refused. A
spec whose slot pool is smaller than the maximum it allows itself to show is
not a conservative spec, it is an incoherent one, and it is rejected rather
than quietly clamped.
"""

import json
import math
from pathlib import Path

import figure_kit

POPULATION_PRESENCE_FORMAT = "living_diorama_population_presence"
POPULATION_PRESENCE_SCHEMA_VERSION = 1

ZONE_TYPES = ("frontage", "plaza", "park", "promenade")
"""Every pedestrian-safe area type a proxy may occupy.

Deliberately small. Frontage is the sidewalk band along a street, plaza
covers designed plazas and civic standing ground, park is the landscape
plan's declared park zones, and promenade is the waterfront walk. Phase 18
does not model transport, interiors, or any moving occupation.
"""

DISTRICT_CHARACTERS = ("civic", "port", "residential", "terrace")
"""The master scene's district characters, which key the spread policy.

Distribution is declared per CHARACTER rather than per district id so the
policy states an urban intention -- a port district's people belong on its
waterfront -- instead of a per-district lookup table that would have to be
re-authored for every world.
"""

EXHAUSTION_POLICIES = ("reduce", "refuse")
"""What to do when the geometry cannot supply a district's whole slot pool.

``reduce`` keeps every slot the ground can actually hold and records the
shortfall in the plan; ``refuse`` raises. Either way the outcome is
explicit -- a silently short pool is the one option that does not exist.
"""

POSE_NAMES = ("idle", "observe", "stroll", "rest")
"""The complete pose vocabulary: four static postures, no behaviour.

These are body attitudes, not activities. Nothing in Phase 18 selects a
pose from a goal, a destination, or another proxy; a pose is a deterministic
function of the slot's own identity, and it never changes over time.
"""

PALETTES = ("slate", "sand", "moss", "rust", "indigo", "clay", "teal", "ochre")
"""The muted colour families a proxy may wear.

Eight quiet families chosen to sit inside the city's existing material
range. Presence should read as people, never as confetti.
"""

COMPLEXIONS = ("c1", "c2", "c3", "c4", "c5")
"""Skin tones, named by index rather than by any word for a people.

A city contains people who do not all look alike, and a diorama that showed
one complexion would be making a claim about its world that its world does
not contain. These are presentation only: nothing reads them back, and the
simulation holds nothing they could correspond to.
"""

HAIR_TONES = ("h1", "h2", "h3", "h4", "h5")
"""Hair tones, likewise by index. ``h4`` and ``h5`` are the greyed pair the
elder presentation draws from."""

FIGURE_AXES = (
    "age_presentation",
    "presentation",
    "stature",
    "build",
    "hair",
    "facial_hair",
    "face",
    "clothing",
    "palette",
    "complexion",
    "hair_tone",
    "pose",
)
"""Every axis of a proxy's VISUAL identity.

Twelve independent choices, each drawn from a closed vocabulary the spec
weights. They are renderer presentation properties and nothing else: none of
them is written into world state, none is derivable back into a demographic
fact, and the simulation holds no data that could justify one if they were.
"""

AXIS_VALUES = {
    "age_presentation": figure_kit.AGE_PRESENTATIONS,
    "presentation": figure_kit.PRESENTATIONS,
    "stature": figure_kit.STATURES,
    "build": figure_kit.BUILDS,
    "hair": figure_kit.HAIR_VARIANTS,
    "facial_hair": figure_kit.FACIAL_HAIR,
    "face": figure_kit.FACE_VARIANTS,
    "clothing": figure_kit.CLOTHING_SILHOUETTES,
    "palette": PALETTES,
    "complexion": COMPLEXIONS,
    "hair_tone": HAIR_TONES,
    "pose": POSE_NAMES,
}
"""The closed vocabulary each axis may draw from.

The geometry axes come from :mod:`figure_kit`, which is the module that has
to be able to build them; a spec that offered a hair style the kit cannot cut
would be a spec describing a body nobody can make.
"""

ORIENTATION_RULES = ("face_street", "along_street", "face_center", "face_water")
"""How a zone decides which way its proxies look.

Orientation is geometry, not intention: a promenade proxy faces the water
because the promenade faces the water, not because it decided to.
"""

REQUIRED_PRESENCE_CAMERAS = (
    "CAM_P18_WORLD",
    "CAM_P18_QUARTER",
    "CAM_P18_STREET",
    "CAM_P18_PLAZA",
    "CAM_P18_CIVIC",
    "CAM_P18_PARK",
    "CAM_P18_GROUP",
    "CAM_P18_VALIDITY",
)
"""The Phase 18 proof anchors.

``CAM_P18_WORLD`` and ``CAM_P18_QUARTER`` are the two COMPARISON anchors,
each rendered twice -- once with the population layer suppressed and once
with it built, from an identical camera -- so the before/after question is
answered by the same view of the same city rather than by two different
pictures. Two scales, because they answer different halves of the question:
the world frame shows that the city's identity and geography are untouched,
and the quarter frame shows the difference at the scale a person is actually
legible.

The rest are the contexts the approved area types promise: a street, a plaza,
the civic forecourt, a park. ``CAM_P18_GROUP`` stands at head height among a
real gathering, close enough that a reviewer can tell one person from another
without reading an object name. ``CAM_P18_VALIDITY`` looks down on a populated
quarter from above, where a body standing in a carriageway would be impossible
to miss.
"""


class PopulationPresenceError(ValueError):
    """A population presence contract violation.

    Raised for malformed specs, impossible density policies, unknown zone
    types, contradictory limits, and every other Phase 18 refusal. Always a
    refusal, never a repair.
    """


def _require_object(value: object, description: str) -> dict:
    """Return the value if it is a JSON object, else refuse."""
    if not isinstance(value, dict):
        raise PopulationPresenceError(
            f"{description} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _require_number(value: object, description: str) -> float:
    """Return a finite number, else refuse."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PopulationPresenceError(f"{description} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise PopulationPresenceError(f"{description} must be finite")
    return number


def _require_positive(value: object, description: str) -> float:
    """Return a strictly positive finite number, else refuse."""
    number = _require_number(value, description)
    if number <= 0.0:
        raise PopulationPresenceError(f"{description} must be greater than zero, got {number}")
    return number


def _require_non_negative(value: object, description: str) -> float:
    """Return a finite number at or above zero, else refuse."""
    number = _require_number(value, description)
    if number < 0.0:
        raise PopulationPresenceError(f"{description} must not be negative, got {number}")
    return number


def _require_count(value: object, description: str) -> int:
    """Return a non-negative exact integer, else refuse."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise PopulationPresenceError(f"{description} must be an integer")
    if value < 0:
        raise PopulationPresenceError(f"{description} must not be negative, got {value}")
    return value


def _require_choice(value: object, choices: tuple[str, ...], description: str) -> str:
    """Return one of a closed set of strings, else refuse."""
    if value not in choices:
        raise PopulationPresenceError(f"{description} must be one of {choices}, got {value!r}")
    return str(value)


def _require_numbers(value: object, description: str, minimum: int = 1) -> list[float]:
    """Return a list of at least ``minimum`` finite numbers, else refuse."""
    if not isinstance(value, list) or len(value) < minimum:
        raise PopulationPresenceError(f"{description} must list at least {minimum} number(s)")
    return [_require_number(item, f"{description}[{index}]") for index, item in enumerate(value)]


def _validate_density(document: dict) -> None:
    """Shape-check the population-to-proxy mapping and its limits."""
    density = _require_object(document.get("density"), "density")
    _require_positive(density.get("residents_per_proxy"), "density residents_per_proxy")
    _require_count(density.get("visibility_threshold"), "density visibility_threshold")
    minimum = _require_count(density.get("min_proxies_per_district"), "density min_proxies")
    maximum = _require_count(density.get("max_proxies_per_district"), "density max_proxies")
    ceiling = _require_count(density.get("global_max_proxies"), "density global_max_proxies")
    if maximum < minimum:
        raise PopulationPresenceError(
            f"density max_proxies_per_district ({maximum}) is below "
            f"min_proxies_per_district ({minimum})"
        )
    if maximum <= 0:
        raise PopulationPresenceError("density max_proxies_per_district must allow at least one")
    if ceiling < maximum:
        raise PopulationPresenceError(
            f"density global_max_proxies ({ceiling}) is below the per-district "
            f"maximum ({maximum}); one district alone could never be shown"
        )
    threshold = int(density["visibility_threshold"])
    if minimum > 0 and threshold < 1:
        raise PopulationPresenceError(
            "density visibility_threshold must be at least 1 when "
            "min_proxies_per_district is; a threshold of zero would let the minimum "
            "put a visible body in a district with no residents at all"
        )
    ratio = float(density["residents_per_proxy"])
    earnable = int(math.floor(threshold / ratio)) if threshold else 0
    if minimum > earnable:
        raise PopulationPresenceError(
            f"density min_proxies_per_district ({minimum}) is more than the "
            f"visibility threshold earns ({earnable} at {ratio} residents per proxy); "
            "the minimum would manufacture people the population never paid for"
        )


def _validate_slots(document: dict) -> None:
    """Shape-check the stable slot pool declaration."""
    slots = _require_object(document.get("slots"), "slots")
    pool = _require_count(slots.get("pool_size"), "slots pool_size")
    if pool <= 0:
        raise PopulationPresenceError("slots pool_size must be at least one")
    _require_choice(slots.get("exhaustion_policy"), EXHAUSTION_POLICIES, "slots exhaustion_policy")
    density = _require_object(document.get("density"), "density")
    maximum = _require_count(
        density.get("max_proxies_per_district"), "density max_proxies_per_district"
    )
    if pool < maximum:
        raise PopulationPresenceError(
            f"slots pool_size ({pool}) is smaller than density max_proxies_per_district "
            f"({maximum}); the spec would permit more visible people than it has "
            "stable identities for"
        )


def _validate_zones(document: dict) -> None:
    """Shape-check every pedestrian zone's sampling and safety geometry."""
    zones = _require_object(document.get("zones"), "zones")
    unknown = sorted(set(zones) - set(ZONE_TYPES))
    if unknown:
        raise PopulationPresenceError(f"zones declares unknown area type(s): {unknown}")
    missing = sorted(set(ZONE_TYPES) - set(zones))
    if missing:
        raise PopulationPresenceError(f"zones must declare every area type; missing {missing}")
    for zone_id in ZONE_TYPES:
        zone = _require_object(zones.get(zone_id), f"zone {zone_id}")
        _require_positive(zone.get("spacing"), f"zone {zone_id} spacing")
        _require_choice(zone.get("orientation"), ORIENTATION_RULES, f"zone {zone_id} orientation")
        offsets = _require_numbers(zone.get("offsets"), f"zone {zone_id} offsets")
        if any(offset < 0.0 for offset in offsets):
            raise PopulationPresenceError(f"zone {zone_id} offsets must not be negative")
        if len(set(offsets)) != len(offsets):
            raise PopulationPresenceError(f"zone {zone_id} offsets must be distinct")
        if zone_id == "park" and any(offset <= 0.0 or offset >= 1.0 for offset in offsets):
            raise PopulationPresenceError(
                "zone park offsets are FRACTIONS of each park zone's radius and must "
                f"lie strictly between 0 and 1, got {offsets}"
            )


def _validate_proxy(document: dict) -> None:
    """Shape-check the physical envelope one standing proxy occupies."""
    proxy = _require_object(document.get("proxy"), "proxy")
    _require_positive(proxy.get("radius"), "proxy radius")
    _require_positive(proxy.get("separation"), "proxy separation")
    jitter = _require_non_negative(proxy.get("heading_jitter"), "proxy heading_jitter")
    if jitter > math.pi / 2.0:
        raise PopulationPresenceError(
            "proxy heading_jitter must not exceed a quarter turn, or a body could "
            f"end up facing away from the thing its zone orients it towards, got {jitter}"
        )
    if float(proxy["separation"]) < 2.0 * float(proxy["radius"]):
        raise PopulationPresenceError(
            f"proxy separation ({proxy['separation']}) is below two body radii "
            f"({2.0 * float(proxy['radius'])}); proxies could overlap each other"
        )


def _validate_weight_table(value: object, allowed: tuple[str, ...], description: str) -> None:
    """Shape-check one weighted vocabulary against a closed value set."""
    table = _require_object(value, description)
    unknown = sorted(set(table) - set(allowed))
    if unknown:
        raise PopulationPresenceError(f"{description} offers unknown value(s): {unknown}")
    missing = sorted(set(allowed) - set(table))
    if missing:
        raise PopulationPresenceError(f"{description} must weight every value; missing {missing}")
    total = 0.0
    for name in allowed:
        total = math.fsum((total, _require_non_negative(table[name], f"{description} {name}")))
    if total <= 0.0:
        raise PopulationPresenceError(f"{description} gives every value zero weight")


def _validate_figure(document: dict) -> None:
    """Shape-check the whole visual vocabulary and its coherence rules.

    Aggressively, because an incoherent figure policy does not fail loudly at
    render time -- it quietly produces a city of near-identical people, which
    is exactly the defect this section exists to prevent.
    """
    figure = _require_object(document.get("figure"), "figure")
    vocabularies = _require_object(figure.get("vocabularies"), "figure vocabularies")
    missing = sorted(set(FIGURE_AXES) - set(vocabularies))
    if missing:
        raise PopulationPresenceError(
            f"figure vocabularies must cover every axis; missing {missing}"
        )
    unknown = sorted(set(vocabularies) - set(FIGURE_AXES))
    if unknown:
        raise PopulationPresenceError(f"figure vocabularies declares unknown axis/axes: {unknown}")
    for axis in FIGURE_AXES:
        _validate_weight_table(vocabularies[axis], AXIS_VALUES[axis], f"figure vocabulary {axis}")

    rules = _require_object(figure.get("age_rules"), "figure age_rules")
    unknown_ages = sorted(set(rules) - set(AXIS_VALUES["age_presentation"]))
    if unknown_ages:
        raise PopulationPresenceError(f"figure age_rules names unknown age(s): {unknown_ages}")
    for age, entry in sorted(rules.items()):
        restrictions = _require_object(entry, f"figure age_rules {age}")
        for axis, allowed in sorted(restrictions.items()):
            if axis not in FIGURE_AXES:
                raise PopulationPresenceError(
                    f"figure age_rules {age} restricts unknown axis {axis}"
                )
            if not isinstance(allowed, list) or not allowed:
                raise PopulationPresenceError(
                    f"figure age_rules {age} {axis} must list at least one permitted value"
                )
            stray = sorted(set(allowed) - set(AXIS_VALUES[axis]))
            if stray:
                raise PopulationPresenceError(
                    f"figure age_rules {age} {axis} permits unknown value(s): {stray}"
                )
            if not any(float(vocabularies[axis].get(name, 0.0)) > 0.0 for name in allowed):
                raise PopulationPresenceError(
                    f"figure age_rules {age} {axis} permits only values the vocabulary "
                    "weights at zero, so that age could never be built"
                )

    known_values = {name for axis in FIGURE_AXES for name in AXIS_VALUES[axis]}
    bias = _require_object(figure.get("presentation_bias"), "figure presentation_bias")
    stray = sorted(set(bias) - set(AXIS_VALUES["presentation"]))
    if stray:
        raise PopulationPresenceError(
            f"figure presentation_bias names unknown presentation(s): {stray}"
        )
    for presentation, entry in sorted(bias.items()):
        table = _require_object(entry, f"figure presentation_bias {presentation}")
        for name, weight in sorted(table.items()):
            if name not in known_values:
                raise PopulationPresenceError(
                    f"figure presentation_bias {presentation} biases unknown value {name!r}"
                )
            _require_non_negative(weight, f"figure presentation_bias {presentation} {name}")

    zone_bias = _require_object(figure.get("zone_age_bias"), "figure zone_age_bias")
    stray_zones = sorted(set(zone_bias) - set(ZONE_TYPES))
    if stray_zones:
        raise PopulationPresenceError(f"figure zone_age_bias names unknown zone(s): {stray_zones}")
    for zone_id, entry in sorted(zone_bias.items()):
        table = _require_object(entry, f"figure zone_age_bias {zone_id}")
        stray_ages = sorted(set(table) - set(AXIS_VALUES["age_presentation"]))
        if stray_ages:
            raise PopulationPresenceError(
                f"figure zone_age_bias {zone_id} names unknown age(s): {stray_ages}"
            )
        for name, weight in sorted(table.items()):
            _require_non_negative(weight, f"figure zone_age_bias {zone_id} {name}")

    composition = _require_object(figure.get("composition"), "figure composition")
    zones = composition.get("gathering_zones")
    if not isinstance(zones, list) or not zones:
        raise PopulationPresenceError(
            "figure composition gathering_zones must list at least one zone"
        )
    stray_gathering = sorted(set(zones) - set(ZONE_TYPES))
    if stray_gathering:
        raise PopulationPresenceError(
            f"figure composition gathering_zones names unknown zone(s): {stray_gathering}"
        )
    _require_positive(composition.get("child_adjacency_radius"), "figure composition radius")
    _require_non_negative(composition.get("child_adjacency_bias"), "figure composition bias")

    diversity = _require_object(figure.get("diversity"), "figure diversity")
    _require_positive(diversity.get("radius"), "figure diversity radius")
    attempts = _require_count(diversity.get("attempts"), "figure diversity attempts")
    if attempts < 1:
        raise PopulationPresenceError("figure diversity attempts must allow at least one draw")


def _validate_distribution(document: dict) -> None:
    """Shape-check the per-character spread across zone types."""
    distribution = _require_object(document.get("distribution"), "distribution")
    missing = sorted(set(DISTRICT_CHARACTERS) - set(distribution))
    if missing:
        raise PopulationPresenceError(
            f"distribution must cover every district character; missing {missing}"
        )
    unknown = sorted(set(distribution) - set(DISTRICT_CHARACTERS))
    if unknown:
        raise PopulationPresenceError(f"distribution declares unknown character(s): {unknown}")
    for character in DISTRICT_CHARACTERS:
        weights = _require_object(distribution[character], f"distribution {character}")
        unknown_zones = sorted(set(weights) - set(ZONE_TYPES))
        if unknown_zones:
            raise PopulationPresenceError(
                f"distribution {character} names unknown zone(s): {unknown_zones}"
            )
        total = 0.0
        for zone_id in ZONE_TYPES:
            total += _require_non_negative(
                weights.get(zone_id, 0.0), f"distribution {character} {zone_id}"
            )
        if total <= 0.0:
            raise PopulationPresenceError(
                f"distribution {character} gives every zone zero weight; its people "
                "would have nowhere they are allowed to be"
            )


def _validate_proof(document: dict) -> None:
    """Shape-check the Phase 18 proof camera anchors."""
    proof = _require_object(document.get("proof"), "proof")
    cameras = _require_object(proof.get("cameras"), "proof cameras")
    for name in REQUIRED_PRESENCE_CAMERAS:
        camera = _require_object(cameras.get(name), f"camera {name}")
        for key in ("location", "look_at"):
            value = camera.get(key)
            if not isinstance(value, list) or len(value) != 3:
                raise PopulationPresenceError(f"camera {name} {key} must be [x, y, z]")
            for index, coordinate in enumerate(value):
                _require_number(coordinate, f"camera {name} {key}[{index}]")
        _require_number(camera.get("lens_mm"), f"camera {name} lens_mm")


def load_population_presence_spec(path: str | Path) -> dict:
    """Load and shape-validate the Population Presence Spec V1.

    Raises:
        PopulationPresenceError: If the document is not a well-formed spec.
    """
    document = _require_object(
        json.loads(Path(path).read_text(encoding="utf-8")), "population presence spec"
    )
    if document.get("format") != POPULATION_PRESENCE_FORMAT:
        raise PopulationPresenceError(
            f"population presence spec format must be {POPULATION_PRESENCE_FORMAT!r}, "
            f"got {document.get('format')!r}"
        )
    version = document.get("schema_version")
    if isinstance(version, bool) or version != POPULATION_PRESENCE_SCHEMA_VERSION:
        raise PopulationPresenceError(
            f"population presence spec schema_version must be "
            f"{POPULATION_PRESENCE_SCHEMA_VERSION}, got {version!r}"
        )
    seed = document.get("visual_seed")
    if not isinstance(seed, str) or not seed.strip():
        raise PopulationPresenceError(
            "population presence spec visual_seed must be a non-empty string"
        )
    _validate_density(document)
    _validate_slots(document)
    _validate_zones(document)
    _validate_proxy(document)
    _validate_distribution(document)
    _validate_figure(document)
    _validate_proof(document)
    return document


def unclamped_proxy_count(population: int, spec: dict) -> int:
    """What the density scale alone would show, before any per-district cap.

    Exists so the cap can never be silent. :func:`visible_proxy_count` clamps
    to ``max_proxies_per_district``, and a plan that published only the clamped
    number while still claiming every body stands for exactly
    ``residents_per_proxy`` residents would be overstating what the render
    shows. The plan reports both, and their difference.

    Raises:
        PopulationPresenceError: If ``population`` is not a non-negative
            exact integer.
    """
    count = _require_count(population, "district population")
    density = spec["density"]
    if count <= 0 or count < int(density["visibility_threshold"]):
        return 0
    scaled = int(math.floor(count / float(density["residents_per_proxy"])))
    return max(scaled, int(density["min_proxies_per_district"]))


def visible_proxy_count(population: int, spec: dict) -> int:
    """How many representative proxies one district's population earns.

    The entire truth claim of Phase 18 in one function: a count derived from
    authoritative population by a declared, inspectable rule. Below the
    visibility threshold the district shows nobody at all -- a world with two
    residents does not get a crowd rounded up out of a minimum.

    Raises:
        PopulationPresenceError: If ``population`` is not a non-negative
            exact integer. A population is a count, and a float population
            would mean the export was not the authoritative document.
    """
    count = _require_count(population, "district population")
    density = spec["density"]
    if count <= 0 or count < int(density["visibility_threshold"]):
        return 0
    scaled = int(math.floor(count / float(density["residents_per_proxy"])))
    scaled = max(scaled, int(density["min_proxies_per_district"]))
    return min(scaled, int(density["max_proxies_per_district"]))


def zone_weights(character: str, spec: dict) -> dict[str, float]:
    """The declared spread across zone types for one district character.

    Raises:
        PopulationPresenceError: If the character is not one the spec covers.
    """
    if character not in DISTRICT_CHARACTERS:
        raise PopulationPresenceError(
            f"district character {character!r} is not one of {DISTRICT_CHARACTERS}"
        )
    declared = spec["distribution"][character]
    return {zone_id: float(declared.get(zone_id, 0.0)) for zone_id in ZONE_TYPES}
