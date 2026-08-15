"""Daily Life Mobility Spec V1: the presentation contract for ambient motion.

Pure Python by design -- this module never imports ``bpy``, so the whole
mobility policy can be validated and tested without Blender installed. The
Blender mobility runtime imports it; nothing here imports Blender modules.

A Mobility Spec is PRESENTATION architecture, never simulation state. It owns
how many of the existing Phase 18 proxies walk, how far and how fast they walk,
how their gait relates to their travel, how many vehicles the city carries,
where a lane may be drawn inside a carriageway, how fast a vehicle may move,
how close two moving bodies may pass, and how the proof is framed.

It never defines simulation entities and it deliberately cannot express one:
there is no place in this schema for a citizen, a home, a workplace, a
destination, a schedule, a passenger or an owner. Phase 19 movement is AMBIENT
PRESENTATION MOBILITY -- it makes aggregate life visibly active, and it makes
no claim about any individual.

    THE SPEC OWNS THE NUMBERS.

Nothing downstream may invent a fraction, a speed, a margin or a count. The one
thing this spec does NOT own is the timeline: frame numbers belong to the
LOCKED Phase 17 Motion & Time Spec, and :func:`resolve_mobility_timeline` reads
them from the resolved Phase 17 timeline rather than restating them, so a
Phase 19 cycle can never drift from the cinematic time it overlays.

THE LOOP CONTRACT IS AN ARITHMETIC CONSTRAINT, NOT A WISH
---------------------------------------------------------
Every moving thing must be in exactly the same state on the first and last
frame of the canonical timeline, so every route is a CLOSED loop travelled an
exact whole number of times. A route's length is therefore its speed times the
cycle duration, divided by its cycle count -- which is why the vehicle speed
band and the canonical eight-second timeline together decide, with no freedom
left over, how long a drivable circuit is allowed to be.
"""

import json
import math
from pathlib import Path

import vehicle_kit
from scene_spec import stable_rng

DAILY_LIFE_MOBILITY_FORMAT = "living_diorama_daily_life_mobility"
DAILY_LIFE_MOBILITY_SCHEMA_VERSION = 1

DRIVING_SIDES = ("right", "left")
"""Which side of a carriageway a lane is drawn on. V1 declares ``right``; the
alternative exists so the convention is a stated policy rather than an
assumption baked into the offset arithmetic."""

ROUTE_FAMILIES = ("corridor_loop", "ring_loop")
"""The two pedestrian route shapes.

``corridor_loop`` is a closed circuit around a straight-ish corridor -- out
along one side, round a turn, back along the other, round again. It suits a
sidewalk and a waterfront walk, where the safe ground is a band.

``ring_loop`` is a closed circuit around a centre at a fixed radius, which is
what a plaza and a park zone actually offer: their safe ground is annular, and
walking a ring keeps a body at the radius the topology already proved clear.

Both are CLOSED, and that is the point: a closed route returns a walker to its
own Phase 18 anchor with the heading it started with, so the loop contract is
satisfied by the shape of the route rather than by a correction at the end."""

REQUIRED_MOBILITY_CAMERAS = (
    "CAM_P19_DAILY_LIFE",
    "CAM_P19_GAIT",
    "CAM_P19_TRAFFIC",
    "CAM_P19_CITY",
    "CAM_P19_VALIDITY",
)
"""The Phase 19 proof anchors.

``CAM_P19_DAILY_LIFE`` is the hero: a working city view where pedestrians and
vehicles are both legible and the architecture still dominates.
``CAM_P19_GAIT`` stands close enough to a walking route that a frozen mannequin
sliding along the ground would be impossible to miss, and ``CAM_P19_TRAFFIC``
does the same for wheels. ``CAM_P19_CITY`` is the wide frame that shows the
city is still the subject, and ``CAM_P19_VALIDITY`` looks down from above,
where a body in a carriageway or a vehicle on a pavement could not hide."""

_TOP_LEVEL = (
    "format",
    "schema_version",
    "mobility_seed",
    "cycle",
    "pedestrians",
    "vehicles",
    "proof",
)


class MobilitySpecError(ValueError):
    """A Daily Life Mobility Spec contract violation.

    Raised for malformed documents, impossible cycles, invalid fractions or
    counts, lane margins no vehicle could fit inside, reversed speed bands,
    incoherent gait settings and impossible route bounds. Always a refusal,
    never a repair and never a silent default.
    """


# ---------------------------------------------------------------------------
# Primitive validators
# ---------------------------------------------------------------------------


def _require_object(value: object, description: str) -> dict:
    """Return the value if it is a JSON object, else refuse."""
    if not isinstance(value, dict):
        raise MobilitySpecError(f"{description} must be a JSON object, got {type(value).__name__}")
    return value


def _require_keys(entry: dict, allowed: tuple[str, ...], description: str) -> None:
    """Refuse any section that carries an unknown or a missing field.

    Both directions, because a typo that silently falls back to a default is
    how a spec ends up describing a policy nobody chose.
    """
    unknown = sorted(set(entry) - set(allowed))
    if unknown:
        raise MobilitySpecError(f"{description} has unknown field(s): {unknown}")
    missing = sorted(set(allowed) - set(entry))
    if missing:
        raise MobilitySpecError(f"{description} is missing field(s): {missing}")


def _require_number(value: object, description: str) -> float:
    """Return a finite number, else refuse."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MobilitySpecError(f"{description} must be a number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise MobilitySpecError(f"{description} must be finite, got {value!r}")
    return number


def _require_positive(value: object, description: str) -> float:
    """Return a finite number greater than zero, else refuse."""
    number = _require_number(value, description)
    if number <= 0.0:
        raise MobilitySpecError(f"{description} must be greater than zero, got {number}")
    return number


def _require_non_negative(value: object, description: str) -> float:
    """Return a finite number at or above zero, else refuse."""
    number = _require_number(value, description)
    if number < 0.0:
        raise MobilitySpecError(f"{description} must not be negative, got {number}")
    return number


def _require_fraction(value: object, description: str) -> float:
    """Return a finite number in [0, 1], else refuse."""
    number = _require_number(value, description)
    if not 0.0 <= number <= 1.0:
        raise MobilitySpecError(f"{description} must lie within [0, 1], got {number}")
    return number


def _require_count(value: object, description: str, *, minimum: int = 0) -> int:
    """Return an exact integer at or above a floor, refusing booleans.

    ``True`` is an ``int`` in Python and would otherwise quietly become one
    vehicle; a spec that says ``true`` where a count belongs is malformed.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise MobilitySpecError(f"{description} must be an integer, got {type(value).__name__}")
    if value < minimum:
        raise MobilitySpecError(f"{description} must be at least {minimum}, got {value}")
    return value


def _require_band(entry: object, description: str) -> tuple[float, float]:
    """Return a validated ``{"min", "max"}`` band with max strictly above min."""
    band = _require_object(entry, description)
    _require_keys(band, ("min", "max"), description)
    low = _require_positive(band["min"], f"{description} min")
    high = _require_positive(band["max"], f"{description} max")
    if high <= low:
        raise MobilitySpecError(f"{description} is reversed or empty: [{low}, {high}]")
    return low, high


def _require_choice(value: object, choices: tuple[str, ...], description: str) -> str:
    """Return one of a closed set of strings, else refuse."""
    if value not in choices:
        raise MobilitySpecError(f"{description} must be one of {choices}, got {value!r}")
    return str(value)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

_CYCLE_FIELDS = ("pedestrian_cycles", "vehicle_cycles", "collision_frame_stride")


def _validate_cycle(document: dict) -> dict:
    """Shape-check how the mobility cycle sits on the cinematic timeline."""
    cycle = _require_object(document.get("cycle"), "cycle")
    _require_keys(cycle, _CYCLE_FIELDS, "cycle")
    pedestrian = _require_count(cycle["pedestrian_cycles"], "cycle pedestrian_cycles", minimum=1)
    vehicle = _require_count(cycle["vehicle_cycles"], "cycle vehicle_cycles", minimum=1)
    stride = _require_count(
        cycle["collision_frame_stride"], "cycle collision_frame_stride", minimum=1
    )
    return {
        "pedestrian_cycles": pedestrian,
        "vehicle_cycles": vehicle,
        "collision_frame_stride": stride,
    }


_SPEED_FIELDS = ("reference_height", "base_speed", "min", "max")
_ROUTE_FIELDS = (
    "excursion_min",
    "excursion_max",
    "lateral_offset",
    "sample_step",
    "max_turn_rate_deg_s",
    "clearance",
    "vehicle_clearance",
    "ground_tolerance",
    "anchor_tolerance",
    "speed_ladder",
    "anchor_positions",
)
_GAIT_FIELDS = (
    "phases",
    "stride_factor",
    "stride_tolerance",
    "leg_swing_max_deg",
    "knee_bend_deg",
    "arm_swing_ratio",
    "bob_metres",
    "min_limb_travel",
)
_PEDESTRIAN_FIELDS = ("moving_fraction", "min_moving", "max_moving", "speed", "route", "gait")


def _validate_pedestrians(document: dict) -> dict:
    """Shape-check the walking policy, including its own internal coherence."""
    entry = _require_object(document.get("pedestrians"), "pedestrians")
    _require_keys(entry, _PEDESTRIAN_FIELDS, "pedestrians")
    fraction = _require_fraction(entry["moving_fraction"], "pedestrians moving_fraction")
    minimum = _require_count(entry["min_moving"], "pedestrians min_moving")
    maximum = _require_count(entry["max_moving"], "pedestrians max_moving", minimum=1)
    if maximum < minimum:
        raise MobilitySpecError(
            f"pedestrians max_moving ({maximum}) is below min_moving ({minimum})"
        )
    if fraction >= 1.0:
        raise MobilitySpecError(
            "pedestrians moving_fraction must be below 1.0; a city in which every "
            "representative proxy is walking has no stationary presence left"
        )

    speed = _require_object(entry["speed"], "pedestrians speed")
    _require_keys(speed, _SPEED_FIELDS, "pedestrians speed")
    reference = _require_positive(speed["reference_height"], "pedestrians speed reference_height")
    base = _require_positive(speed["base_speed"], "pedestrians speed base_speed")
    low = _require_positive(speed["min"], "pedestrians speed min")
    high = _require_positive(speed["max"], "pedestrians speed max")
    if high <= low:
        raise MobilitySpecError(f"pedestrians speed band is reversed or empty: [{low}, {high}]")
    if not low <= base <= high:
        raise MobilitySpecError(
            f"pedestrians speed base_speed {base} sits outside its own band [{low}, {high}]"
        )

    route = _require_object(entry["route"], "pedestrians route")
    _require_keys(route, _ROUTE_FIELDS, "pedestrians route")
    excursion_min = _require_positive(route["excursion_min"], "pedestrians route excursion_min")
    excursion_max = _require_positive(route["excursion_max"], "pedestrians route excursion_max")
    if excursion_max <= excursion_min:
        raise MobilitySpecError(
            f"pedestrians route excursion bounds are reversed or empty: "
            f"[{excursion_min}, {excursion_max}]"
        )
    lateral = _require_positive(route["lateral_offset"], "pedestrians route lateral_offset")
    ladder = route.get("speed_ladder")
    if not isinstance(ladder, list) or not ladder:
        raise MobilitySpecError("pedestrians route speed_ladder must list at least one factor")
    factors = [_require_fraction(entry, "pedestrians route speed_ladder entry") for entry in ladder]
    if factors[0] != 1.0:
        raise MobilitySpecError(
            "pedestrians route speed_ladder must begin at 1.0; a walker's own pace is the "
            "first thing tried, and slowing down is the fallback"
        )
    if factors != sorted(factors, reverse=True) or len(set(factors)) != len(factors):
        raise MobilitySpecError("pedestrians route speed_ladder must strictly decrease")
    positions = route.get("anchor_positions")
    if not isinstance(positions, list) or not positions:
        raise MobilitySpecError("pedestrians route anchor_positions must list at least one share")
    shares = [
        _require_fraction(entry, "pedestrians route anchor_positions entry") for entry in positions
    ]
    if len(set(shares)) != len(shares):
        raise MobilitySpecError("pedestrians route anchor_positions must be distinct")
    _require_positive(route["sample_step"], "pedestrians route sample_step")
    turn_rate = _require_positive(route["max_turn_rate_deg_s"], "pedestrians route max_turn_rate")
    _require_non_negative(route["clearance"], "pedestrians route clearance")
    _require_positive(route["vehicle_clearance"], "pedestrians route vehicle_clearance")
    _require_positive(route["ground_tolerance"], "pedestrians route ground_tolerance")
    _require_positive(route["anchor_tolerance"], "pedestrians route anchor_tolerance")

    gait = _require_object(entry["gait"], "pedestrians gait")
    _require_keys(gait, _GAIT_FIELDS, "pedestrians gait")
    phases = _require_count(gait["phases"], "pedestrians gait phases", minimum=4)
    if phases % 2:
        raise MobilitySpecError(
            f"pedestrians gait phases must be even so the two halves of a stride are "
            f"the same length, got {phases}"
        )
    _require_positive(gait["stride_factor"], "pedestrians gait stride_factor")
    tolerance = _require_fraction(gait["stride_tolerance"], "pedestrians gait stride_tolerance")
    if tolerance <= 0.0:
        raise MobilitySpecError(
            "pedestrians gait stride_tolerance must be greater than zero; a loop "
            "closes on a WHOLE number of gait cycles, so the effective stride can "
            "never be exactly the nominal one"
        )
    for field in ("leg_swing_max_deg", "knee_bend_deg"):
        angle = _require_positive(gait[field], f"pedestrians gait {field}")
        if angle >= 90.0:
            raise MobilitySpecError(
                f"pedestrians gait {field} must stay below a quarter turn, got {angle}"
            )
    ratio = _require_positive(gait["arm_swing_ratio"], "pedestrians gait arm_swing_ratio")
    if ratio > 1.5:
        raise MobilitySpecError(
            f"pedestrians gait arm_swing_ratio {ratio} would swing the arms further than "
            "the legs by half again; an arm follows a stride, it does not lead it"
        )
    _require_non_negative(gait["bob_metres"], "pedestrians gait bob_metres")
    _require_positive(gait["min_limb_travel"], "pedestrians gait min_limb_travel")

    # The loop contract turns a speed band into a route-length band, and a
    # route length into an excursion. If those two intervals do not overlap the
    # spec is asking for a walk that cannot close on this timeline, and that is
    # a contradiction the loader has to catch rather than the planner.
    return {
        "moving_fraction": fraction,
        "min_moving": minimum,
        "max_moving": maximum,
        "speed": {
            "reference_height": reference,
            "base_speed": base,
            "min": low,
            "max": high,
        },
        "route": {
            "excursion_min": excursion_min,
            "excursion_max": excursion_max,
            "lateral_offset": lateral,
            "sample_step": float(route["sample_step"]),
            "max_turn_rate_deg_s": turn_rate,
            "clearance": float(route["clearance"]),
            "vehicle_clearance": float(route["vehicle_clearance"]),
            "ground_tolerance": float(route["ground_tolerance"]),
            "anchor_tolerance": float(route["anchor_tolerance"]),
            "speed_ladder": tuple(factors),
            "anchor_positions": tuple(shares),
        },
        "gait": {
            "phases": phases,
            "stride_factor": float(gait["stride_factor"]),
            "stride_tolerance": tolerance,
            "leg_swing_max_deg": float(gait["leg_swing_max_deg"]),
            "knee_bend_deg": float(gait["knee_bend_deg"]),
            "arm_swing_ratio": ratio,
            "bob_metres": float(gait["bob_metres"]),
            "min_limb_travel": float(gait["min_limb_travel"]),
        },
    }


_LANE_FIELDS = (
    "edge_margin",
    "centreline_margin",
    "corner_radius",
    "corner_radius_min",
    "sample_step",
)
_BUDGET_FIELDS = ("triangles_per_vehicle", "layer_triangles")
_VEHICLE_FIELDS = (
    "target_count",
    "max_count",
    "driving_side",
    "lane",
    "speed",
    "slot_pitch",
    "rolling_radius_tolerance",
    "body_clearance",
    "pedestrian_clearance",
    "archetypes",
    "budget",
)


def _validate_vehicles(document: dict) -> dict:
    """Shape-check the traffic policy against the geometry the kit can build."""
    entry = _require_object(document.get("vehicles"), "vehicles")
    _require_keys(entry, _VEHICLE_FIELDS, "vehicles")
    target = _require_count(entry["target_count"], "vehicles target_count", minimum=1)
    maximum = _require_count(entry["max_count"], "vehicles max_count", minimum=1)
    if maximum < target:
        raise MobilitySpecError(f"vehicles max_count ({maximum}) is below target_count ({target})")
    side = _require_choice(entry["driving_side"], DRIVING_SIDES, "vehicles driving_side")

    lane = _require_object(entry["lane"], "vehicles lane")
    _require_keys(lane, _LANE_FIELDS, "vehicles lane")
    edge = _require_non_negative(lane["edge_margin"], "vehicles lane edge_margin")
    centre = _require_non_negative(lane["centreline_margin"], "vehicles lane centreline_margin")
    corner = _require_positive(lane["corner_radius"], "vehicles lane corner_radius")
    corner_min = _require_positive(lane["corner_radius_min"], "vehicles lane corner_radius_min")
    if corner_min > corner:
        raise MobilitySpecError(
            f"vehicles lane corner_radius_min ({corner_min}) is above the target "
            f"corner_radius ({corner})"
        )
    step = _require_positive(lane["sample_step"], "vehicles lane sample_step")

    low, high = _require_band(entry["speed"], "vehicles speed")
    pitch = _require_positive(entry["slot_pitch"], "vehicles slot_pitch")
    rolling = _require_fraction(
        entry["rolling_radius_tolerance"], "vehicles rolling_radius_tolerance"
    )
    if rolling <= 0.0 or rolling > 0.15:
        raise MobilitySpecError(
            "vehicles rolling_radius_tolerance must lie in (0, 0.15]; beyond that the "
            "rolling radius stops being a tyre and becomes a different wheel"
        )
    body_clearance = _require_positive(entry["body_clearance"], "vehicles body_clearance")
    pedestrian_clearance = _require_positive(
        entry["pedestrian_clearance"], "vehicles pedestrian_clearance"
    )

    archetypes = _require_object(entry["archetypes"], "vehicles archetypes")
    unknown = sorted(set(archetypes) - set(vehicle_kit.ARCHETYPES))
    if unknown:
        raise MobilitySpecError(f"vehicles archetypes names unknown archetype(s): {unknown}")
    missing = sorted(set(vehicle_kit.ARCHETYPES) - set(archetypes))
    if missing:
        raise MobilitySpecError(
            f"vehicles archetypes must weight every archetype the kit builds; missing {missing}"
        )
    total = 0.0
    for name in vehicle_kit.ARCHETYPES:
        total = math.fsum((total, _require_non_negative(archetypes[name], f"archetype {name}")))
    if total <= 0.0:
        raise MobilitySpecError("vehicles archetypes gives every archetype zero weight")
    enabled = [name for name in vehicle_kit.ARCHETYPES if float(archetypes[name]) > 0.0]
    if len(enabled) < 2:
        raise MobilitySpecError(
            "vehicles archetypes must enable at least two archetypes; a city whose "
            "traffic is one repeated vehicle is a car park with a conveyor belt"
        )

    budget = _require_object(entry["budget"], "vehicles budget")
    _require_keys(budget, _BUDGET_FIELDS, "vehicles budget")
    per_vehicle = _require_count(budget["triangles_per_vehicle"], "budget per vehicle", minimum=1)
    layer = _require_count(budget["layer_triangles"], "budget layer_triangles", minimum=1)
    if layer < per_vehicle * target:
        raise MobilitySpecError(
            f"vehicles budget layer_triangles ({layer}) cannot hold target_count "
            f"({target}) vehicles at {per_vehicle} triangles each"
        )

    # A lane the widest buildable vehicle cannot sit inside is not a
    # conservative lane, it is an impossible one. Checked against the kit's
    # RESERVED planning envelope -- the box the lane network was sized from --
    # and never against the body the kit happens to emit today, so restyling a
    # vehicle can neither loosen this gate nor silently re-plan the city. The
    # kit proves separately, component by component, that what it builds fits
    # inside that reservation.
    half = vehicle_kit.widest_vehicle() / 2.0
    if pitch <= vehicle_kit.longest_vehicle():
        raise MobilitySpecError(
            f"vehicles slot_pitch ({pitch}) is not longer than the longest vehicle "
            f"({vehicle_kit.longest_vehicle()}); two adjacent slots would overlap"
        )
    if body_clearance >= pitch - vehicle_kit.longest_vehicle():
        raise MobilitySpecError(
            f"vehicles body_clearance ({body_clearance}) cannot be met at slot_pitch "
            f"({pitch}) by the longest vehicle ({vehicle_kit.longest_vehicle()})"
        )
    if edge + half <= 0.0 or centre + half <= 0.0:
        raise MobilitySpecError("vehicles lane margins are degenerate")
    if corner_min < half:
        raise MobilitySpecError(
            f"vehicles lane corner_radius_min ({corner_min}) is tighter than half the "
            f"widest vehicle ({half}); the inside of that turn is inside the vehicle"
        )
    return {
        "target_count": target,
        "max_count": maximum,
        "driving_side": side,
        "lane": {
            "edge_margin": edge,
            "centreline_margin": centre,
            "corner_radius": corner,
            "corner_radius_min": corner_min,
            "sample_step": step,
        },
        "speed": {"min": low, "max": high},
        "slot_pitch": pitch,
        "rolling_radius_tolerance": rolling,
        "body_clearance": body_clearance,
        "pedestrian_clearance": pedestrian_clearance,
        "archetypes": {name: float(archetypes[name]) for name in vehicle_kit.ARCHETYPES},
        "enabled_archetypes": tuple(enabled),
        "budget": {"triangles_per_vehicle": per_vehicle, "layer_triangles": layer},
    }


def _validate_proof(document: dict) -> dict:
    """Shape-check the Phase 19 proof camera anchors."""
    proof = _require_object(document.get("proof"), "proof")
    _require_keys(proof, ("cameras",), "proof")
    cameras = _require_object(proof["cameras"], "proof cameras")
    unknown = sorted(set(cameras) - set(REQUIRED_MOBILITY_CAMERAS))
    if unknown:
        raise MobilitySpecError(f"proof cameras declares unknown camera(s): {unknown}")
    resolved: dict[str, dict] = {}
    for name in REQUIRED_MOBILITY_CAMERAS:
        camera = _require_object(cameras.get(name), f"camera {name}")
        _require_keys(camera, ("location", "look_at", "lens_mm"), f"camera {name}")
        placed: dict[str, object] = {}
        for key in ("location", "look_at"):
            value = camera[key]
            if not isinstance(value, list) or len(value) != 3:
                raise MobilitySpecError(f"camera {name} {key} must be [x, y, z]")
            placed[key] = tuple(
                _require_number(coordinate, f"camera {name} {key}[{index}]")
                for index, coordinate in enumerate(value)
            )
        placed["lens_mm"] = _require_positive(camera["lens_mm"], f"camera {name} lens_mm")
        resolved[name] = placed
    return {"cameras": resolved}


def load_daily_life_mobility_spec(path: str | Path) -> dict:
    """Load and shape-validate the Daily Life Mobility Spec V1.

    Returns a RESOLVED document: every number coerced, every band checked
    against its own bounds, and every archetype weight checked against the
    geometry the vehicle kit can actually build.

    Raises:
        MobilitySpecError: If the document is not a well-formed mobility spec.
    """
    document = _require_object(
        json.loads(Path(path).read_text(encoding="utf-8")), "daily life mobility spec"
    )
    if document.get("format") != DAILY_LIFE_MOBILITY_FORMAT:
        raise MobilitySpecError(
            f"mobility spec format must be {DAILY_LIFE_MOBILITY_FORMAT!r}, "
            f"got {document.get('format')!r}"
        )
    version = document.get("schema_version")
    if isinstance(version, bool) or version != DAILY_LIFE_MOBILITY_SCHEMA_VERSION:
        raise MobilitySpecError(
            f"mobility spec schema_version must be {DAILY_LIFE_MOBILITY_SCHEMA_VERSION}, "
            f"got {version!r}"
        )
    _require_keys(document, _TOP_LEVEL, "mobility spec")
    seed = document.get("mobility_seed")
    if not isinstance(seed, str) or not seed.strip():
        raise MobilitySpecError("mobility spec mobility_seed must be a non-empty string")
    return {
        "format": DAILY_LIFE_MOBILITY_FORMAT,
        "schema_version": DAILY_LIFE_MOBILITY_SCHEMA_VERSION,
        "mobility_seed": seed,
        "cycle": _validate_cycle(document),
        "pedestrians": _validate_pedestrians(document),
        "vehicles": _validate_vehicles(document),
        "proof": _validate_proof(document),
    }


# ---------------------------------------------------------------------------
# The timeline this cycle overlays
# ---------------------------------------------------------------------------


def resolve_mobility_timeline(mobility_spec: dict, motion_timeline: dict) -> dict:
    """Bind the mobility cycle to the LOCKED Phase 17 timeline.

    Phase 19 invents no frames. It reads the resolved Phase 17 timeline -- the
    same object :func:`motion_time_spec.resolve_timeline` returns -- and derives
    its own cycle from it, which is why the canonical mobility loop is exactly
    the canonical cinematic loop and cannot drift from it.

    Returns the frame span, its duration, and the duration of one pedestrian
    and one vehicle cycle. A cycle count above one means the movement repeats
    inside the span, which still lands on the same state at both ends.

    Raises:
        MobilitySpecError: If the timeline is malformed or too short to carry
            a cycle at all.
    """
    for field in ("fps", "start_frame", "end_frame"):
        if field not in motion_timeline:
            raise MobilitySpecError(f"the motion timeline is missing {field!r}")
    fps = motion_timeline["fps"]
    start = motion_timeline["start_frame"]
    end = motion_timeline["end_frame"]
    if isinstance(fps, bool) or not isinstance(fps, int) or fps < 1:
        raise MobilitySpecError(f"the motion timeline fps must be a positive integer, got {fps!r}")
    for name, value in (("start_frame", start), ("end_frame", end)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise MobilitySpecError(f"the motion timeline {name} must be an integer, got {value!r}")
    span = end - start
    if span < 1:
        raise MobilitySpecError(
            f"the motion timeline spans {span} frames; a mobility cycle needs at least one"
        )
    duration = span / fps
    cycle = mobility_spec["cycle"]
    return {
        "fps": fps,
        "start_frame": start,
        "end_frame": end,
        "frame_span": span,
        "duration_seconds": round(duration, 9),
        "pedestrian_cycles": cycle["pedestrian_cycles"],
        "vehicle_cycles": cycle["vehicle_cycles"],
        "pedestrian_cycle_seconds": round(duration / cycle["pedestrian_cycles"], 9),
        "vehicle_cycle_seconds": round(duration / cycle["vehicle_cycles"], 9),
        "collision_frame_stride": cycle["collision_frame_stride"],
    }


def pedestrian_route_length(speed: float, timeline: dict) -> float:
    """The closed-route length one walker at this speed must have.

    The loop contract, stated as arithmetic: a walker travelling at ``speed``
    for exactly one cycle covers ``speed * cycle_seconds``, and it has to end
    where it began, so that distance IS the route's length. There is no other
    degree of freedom, which is why the planner sizes an excursion from a speed
    rather than choosing both.
    """
    return float(speed) * float(timeline["pedestrian_cycle_seconds"])


def vehicle_route_length_bounds(mobility_spec: dict, timeline: dict) -> tuple[float, float]:
    """The circuit lengths the declared vehicle speed band can close on.

    A circuit outside this band cannot be driven at a legal speed and still
    return to its start on the canonical timeline, so the lane network refuses
    it rather than racing a vehicle round it or leaving it half-driven.
    """
    seconds = float(timeline["vehicle_cycle_seconds"])
    band = mobility_spec["vehicles"]["speed"]
    return band["min"] * seconds, band["max"] * seconds


def mobility_seed(mobility_spec: dict, *parts: str):
    """A deterministic generator owned by one mobility identity and nothing else.

    Every walker and every vehicle draws from a generator seeded by its own slot
    id, so activating a fifteenth vehicle cannot disturb the fourteen that were
    already driving.
    """
    return stable_rng(mobility_spec["mobility_seed"], "mobility", *parts)
