"""MotionPlan V1: what is allowed to move, and exactly when, and why.

Pure Python by design -- this module never imports ``bpy``. Given two
authoritative Render Exports and the presentation contracts (Master Scene
Spec, Motion & Time Spec) it derives a deterministic, sorted, minimal list of
visual directives, and it can be inspected, hashed, diffed, and fully tested
without Blender installed.

The one rule that governs everything here:

    MOTION IS DOWNSTREAM. The simulation is authoritative. A directive may
    exist only because the before-state and the after-state genuinely differ,
    and it must be traceable to the exact fields that differ.

A channel is therefore animatable only if the LOCKED Phase 15 static
application ALREADY drives that property from authoritative state. That is
not a stylistic preference: the animated scene must equal the ordinary static
application of the before-export at the first frame and of the after-export
at the last one, so a property the static layer never writes could not be
animated without making one of those endpoints false. Transitions with no
such expression are REFUSED with a reason, never guessed.

Two mirror sets live here, both of them replays of locked Phase 15 mapping
code rather than new decisions: the scalar visual values (Seal glow, district
glazing) and the deterministic decoration samplers (depot slots, wall
struts). Blender structural tests pin every one of them against the real
objects the locked builders produce, so a drift fails loudly instead of
silently animating a fiction.
"""

import hashlib
import json
import math
from pathlib import Path

from motion_time_spec import (
    MotionSpecError,
    channel_frames,
    interpolate,
    member_span_frames,
    member_window,
    require_channel,
    staged_frames,
)
from scene_spec import (
    SceneContractError,
    depot_fill_fraction,
    occupancy_fraction,
    require_topology_agreement,
    stable_rng,
)

MOTION_PLAN_FORMAT = "living_diorama_motion_plan"
MOTION_PLAN_SCHEMA_VERSION = 1

MOVEMENT_LAW_ID = "law_movement_sharing"
"""The one law the Golden Seal indicates. Mirrors ``apply_law_state``: the
Seal is the recurring Rule Object for the movement/sharing law and Phase 17
does not give it new meanings."""

SEAL_GLOW_ACTIVE = 5.0
SEAL_GLOW_INACTIVE = 0.0
SEAL_GLOW_MATERIAL = "LD_MAT__seal_glow"
SEAL_GLOW_NODE = "Principled BSDF"
SEAL_GLOW_SOCKET = "input:Emission Strength"

GLAZING_BASE = 0.12
GLAZING_RANGE = 0.55
GLAZING_NODE = "LD_LitFraction"
GLAZING_SOCKET = "output:0"

DEPOT_SLOTS = 8
DEPOT_PREFIX = "LD_EPISODE__depot_"

WALL_PREFIX = "LD_WALL__"

INFRA_PREFIX = "LD_INFRA__"
STRUT_LANE_OFFSETS = {
    "TRANSIT_ROUTE": 6.0,
    "RESOURCE_ROUTE": -6.0,
    "HOUSING": 7.4,
    "CIVIC_SERVICE": -7.4,
}
STRUT_DEFAULT_OFFSET = 6.0
STRUT_SPACING = 1.6
STRUT_DEPENDENCY_WEIGHT = 3.0

PRESENCE_VISIBLE = 1.0
PRESENCE_HIDDEN = 0.0

TRANSFORM_COMPONENTS = ("location_x", "location_y", "location_z", "rotation_z")

VALUE_SPACES = ("absolute", "canonical_offset")
"""``canonical_offset`` directives carry a delta from the value the canonical
static application of the AFTER export produces, and every one of them ends
at exactly ``0.0``. That is what makes the final animated frame bit-identical
to the ordinary static world rather than merely similar to it."""


class MotionPlanError(ValueError):
    """A refusal to animate a transition.

    Raised when the two exports disagree in a way V1 has no truthful visual
    channel for, when a transition would contradict world history, or when a
    plan would need two conflicting directives on one target. Always a
    refusal, never a guess.
    """


def _finite(value: object, description: str) -> float:
    """Return a finite number, refusing booleans and NaN/Infinity alike."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MotionPlanError(f"{description} must be a number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise MotionPlanError(f"{description} must be finite, got {value!r}")
    return number


def _by_id(entries: object, description: str) -> dict[str, dict]:
    """Index one export array by entity id, refusing duplicates."""
    if not isinstance(entries, list):
        raise MotionPlanError(f"{description} must be a JSON array")
    indexed: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise MotionPlanError(f"{description} entries must be JSON objects")
        entity_id = entry.get("id")
        if not isinstance(entity_id, str) or not entity_id:
            raise MotionPlanError(f"{description} entry has no usable id")
        if entity_id in indexed:
            raise MotionPlanError(f"{description} declares {entity_id!r} twice")
        indexed[entity_id] = entry
    return indexed


def _stock(district: dict) -> float:
    """Total resource stock, summed identically on every Python version.

    CPython 3.12 changed builtin ``sum`` over floats to compensated
    summation, so the same three numbers can add up to two different
    representable results depending on which interpreter is running -- the
    host's for a pure plan, Blender's bundled one for a rendered plan. That
    would make the plan HASH interpreter-dependent, which is not determinism.
    ``math.fsum`` is exactly rounded on both, so it is the only summation this
    module performs.
    """
    return math.fsum(district["resources"].values())


def depot_slot_placements(district: dict, definition: dict, visual_seed: str) -> dict[str, float]:
    """Replay the locked depot sampler: slot object name -> Z rotation.

    A faithful replay of ``apply_render_export.apply_districts`` -- the same
    ``stable_rng`` identity, the same fill fraction, the same slot order, the
    same two draws per stack -- so the planner knows exactly which container
    objects the static application of THIS export would create and how each
    one sits. It is a replay, not an invention: a Blender structural test
    pins it against the real meshes.
    """
    district_id = district["id"]
    fill = depot_fill_fraction(district, definition["depot_capacity"])
    visible = round(fill * DEPOT_SLOTS)
    rng = stable_rng(visual_seed, district_id, "containers")
    placements: dict[str, float] = {}
    for slot in range(DEPOT_SLOTS):
        if slot >= visible:
            continue
        stack = 1 + (1 if rng.random() < fill else 0)
        for level in range(stack):
            name = f"{DEPOT_PREFIX}{district_id}__{slot}_{level}"
            placements[name] = rng.uniform(-0.03, 0.03)
    return placements


def strut_placements(
    infrastructure: dict, boundary: dict, has_wall: bool
) -> dict[str, tuple[float, float]]:
    """Replay the locked wall-strut layout: strut object name -> (x, y).

    Mirrors the anchoring pass of ``apply_render_export.apply_infrastructure``:
    struts exist only where the conduit meets a wall the engine actually
    built, the count grows with the engine's dependency score, and the row is
    re-centred on the wall station every time the count changes. Pinned
    against the real objects by a Blender structural test.
    """
    if not has_wall:
        return {}
    station = boundary["wall_station"]
    wall_x, wall_y = station["center"]
    direction_x, direction_y = station["direction"]
    norm = math.hypot(direction_x, direction_y) or 1.0
    offset = STRUT_LANE_OFFSETS.get(infrastructure["infrastructure_type"], STRUT_DEFAULT_OFFSET)
    dependency = _finite(
        infrastructure["dependency_score"],
        f"infrastructure {infrastructure['id']!r} dependency_score",
    )
    struts = max(1, round(1 + dependency * STRUT_DEPENDENCY_WEIGHT))
    placements: dict[str, tuple[float, float]] = {}
    for strut in range(struts):
        along = (strut - (struts - 1) / 2.0) * STRUT_SPACING
        base_x = wall_x + (direction_x / norm) * along
        base_y = wall_y + (direction_y / norm) * along
        name = f"{INFRA_PREFIX}{infrastructure['id']}__wallstrut{strut}"
        placements[name] = (
            base_x + offset * 0.5 * (direction_y / norm),
            base_y - offset * 0.5 * (direction_x / norm),
        )
    return placements


def seal_glow_value(law: dict) -> float:
    """The Seal's emission for one law state. Mirrors ``apply_law_state``."""
    active = law.get("active")
    if not isinstance(active, bool):
        raise MotionPlanError(
            f"law {law.get('id')!r} has a non-boolean active value {active!r}; the "
            "Seal indicates a law that is in force or suspended, and 1, 1.0 and "
            '"true" are not that'
        )
    return SEAL_GLOW_ACTIVE if active else SEAL_GLOW_INACTIVE


def glazing_value(district: dict) -> float:
    """The lit-window fraction for one district. Mirrors ``apply_districts``.

    The two authoritative numbers are checked for finiteness first: a NaN
    population would otherwise sail through the clamp and key a NaN into an
    F-curve, which no later stage could detect.
    """
    _finite(district["population"], f"district {district['id']!r} population")
    _finite(district["housing_capacity"], f"district {district['id']!r} housing_capacity")
    return GLAZING_BASE + GLAZING_RANGE * occupancy_fraction(district)


def _directive(
    *,
    semantic_id: str,
    channel: str,
    target: dict,
    value_space: str,
    from_value: float,
    to_value: float,
    frames: tuple[int, int],
    policy: dict,
    source_before: str,
    source_after: str,
    member_span: int | None = None,
) -> dict:
    """Assemble one fully-resolved, self-describing motion directive."""
    if value_space not in VALUE_SPACES:
        raise MotionPlanError(f"unknown value space {value_space!r}")
    if value_space == "canonical_offset" and to_value != 0.0:
        raise MotionPlanError(
            f"{channel}/{semantic_id}: a canonical_offset directive must end at exactly "
            f"0.0 so the final frame is the canonical static world, got {to_value!r}"
        )
    if from_value == to_value:
        raise MotionPlanError(
            f"{channel}/{semantic_id}: refusing an empty directive; unchanged values "
            "never produce motion"
        )
    directive = {
        "semantic_id": semantic_id,
        "channel": channel,
        "target": target,
        "value_space": value_space,
        "from_value": float(from_value),
        "to_value": float(to_value),
        "start_frame": frames[0],
        "end_frame": frames[1],
        "interpolation": policy["interpolation"],
        "strategy": policy["strategy"],
        "samples": policy["samples"],
        "rise_metres": policy["rise_metres"],
        "source_before": source_before,
        "source_after": source_after,
    }
    if member_span is not None:
        directive["member_span_frames"] = member_span
    return directive


def _target_key(directive: dict) -> tuple:
    """The concrete thing a directive drives, for conflict detection."""
    target = directive["target"]
    return tuple(sorted((key, str(value)) for key, value in target.items()))


def _sort_key(directive: dict) -> tuple:
    """Total, mapping-order-independent ordering of the directive list."""
    return (
        directive["channel"],
        directive["semantic_id"],
        json.dumps(directive["target"], sort_keys=True),
        directive["start_frame"],
        directive["end_frame"],
    )


def _plan_law(before: dict, after: dict, motion_spec: dict) -> list[dict]:
    """The Golden Seal's law indication, if the law's standing changed."""
    laws_before = _by_id(before["world"]["laws"], "before laws")
    laws_after = _by_id(after["world"]["laws"], "after laws")
    law_before = laws_before.get(MOVEMENT_LAW_ID)
    law_after = laws_after.get(MOVEMENT_LAW_ID)
    if (law_before is None) != (law_after is None):
        raise MotionPlanError(
            f"law {MOVEMENT_LAW_ID!r} exists in only one export; the Golden Seal "
            "indicates a law that persists, and a law appearing or vanishing is not "
            "a visual transition V1 can tell truthfully"
        )
    if law_before is None or law_after is None:
        return []
    glow_before = seal_glow_value(law_before)
    glow_after = seal_glow_value(law_after)
    if glow_before == glow_after:
        return []
    policy = require_channel(motion_spec, "law_seal_glow")
    timeline = motion_spec["timeline"]
    return [
        _directive(
            semantic_id=MOVEMENT_LAW_ID,
            channel="law_seal_glow",
            target={
                "kind": "material_node_value",
                "material": SEAL_GLOW_MATERIAL,
                "node": SEAL_GLOW_NODE,
                "socket": SEAL_GLOW_SOCKET,
            },
            value_space="absolute",
            from_value=glow_before,
            to_value=glow_after,
            frames=member_window(policy, timeline, 0, 1),
            policy=policy,
            source_before=f"world.laws[{MOVEMENT_LAW_ID}].active={law_before['active']}",
            source_after=f"world.laws[{MOVEMENT_LAW_ID}].active={law_after['active']}",
        )
    ]


def _plan_glazing(before: dict, after: dict, master_spec: dict, motion_spec: dict) -> list[dict]:
    """Population-linked glazing, per district, where occupancy changed."""
    districts_before = _by_id(before["world"]["districts"], "before districts")
    districts_after = _by_id(after["world"]["districts"], "after districts")
    if set(districts_before) != set(districts_after):
        raise MotionPlanError(
            "the two exports describe different district sets "
            f"({sorted(districts_before)} vs {sorted(districts_after)}); districts "
            "appearing or vanishing is not a V1 visual transition"
        )
    policy = require_channel(motion_spec, "district_glazing")
    timeline = motion_spec["timeline"]
    directives: list[dict] = []
    claimed: dict[str, tuple[str, float, float]] = {}
    for district_id in sorted(districts_before):
        definition = master_spec["districts"][district_id]
        value_before = glazing_value(districts_before[district_id])
        value_after = glazing_value(districts_after[district_id])
        material = f"LD_MAT__glass_{definition['character']}"
        previous = claimed.get(material)
        if previous is not None and previous[1:] != (value_before, value_after):
            raise MotionPlanError(
                f"districts {previous[0]!r} and {district_id!r} share glazing material "
                f"{material!r} but demand different transitions; one material cannot "
                "hold two truths at once"
            )
        claimed[material] = (district_id, value_before, value_after)
        if previous is not None or value_before == value_after:
            continue
        directives.append(
            _directive(
                semantic_id=district_id,
                channel="district_glazing",
                target={
                    "kind": "material_node_value",
                    "material": material,
                    "node": GLAZING_NODE,
                    "socket": GLAZING_SOCKET,
                },
                value_space="absolute",
                from_value=value_before,
                to_value=value_after,
                frames=member_window(policy, timeline, 0, 1),
                policy=policy,
                source_before=(
                    f"world.districts[{district_id}] population="
                    f"{districts_before[district_id]['population']}/"
                    f"{districts_before[district_id]['housing_capacity']}"
                ),
                source_after=(
                    f"world.districts[{district_id}] population="
                    f"{districts_after[district_id]['population']}/"
                    f"{districts_after[district_id]['housing_capacity']}"
                ),
            )
        )
    return directives


def _plan_walls(before: dict, after: dict, motion_spec: dict) -> list[dict]:
    """Engine-built walls that rise between the two states.

    A wall the engine built is permanent history. A wall present in the
    before-state and absent afterwards is not a demolition this layer may
    stage; it is a contradiction, and it is refused.
    """
    walls_before = _by_id(before["world"]["walls"], "before walls")
    walls_after = _by_id(after["world"]["walls"], "after walls")
    vanished = sorted(set(walls_before) - set(walls_after))
    if vanished:
        raise MotionPlanError(
            f"walls {vanished} stand in the before-state and are absent afterwards; "
            "the world remembers, and V1 refuses to animate a removal the engine "
            "never recorded"
        )
    policy = require_channel(motion_spec, "wall_presence")
    timeline = motion_spec["timeline"]
    directives: list[dict] = []
    for wall_id in sorted(walls_after):
        wall_after = walls_after[wall_id]
        wall_before = walls_before.get(wall_id)
        if wall_before is not None:
            integrity_before = _finite(wall_before["integrity"], f"wall {wall_id} integrity")
            integrity_after = _finite(wall_after["integrity"], f"wall {wall_id} integrity")
            if integrity_before != integrity_after:
                raise MotionPlanError(
                    f"wall {wall_id!r} changes integrity {integrity_before} -> "
                    f"{integrity_after}, which changes its canonical segment heights; "
                    "V1 has no geometry-morph channel and refuses to fake one"
                )
            continue
        directives.append(
            _directive(
                semantic_id=wall_id,
                channel="wall_presence",
                target={"kind": "object_group_presence", "prefix": f"{WALL_PREFIX}{wall_id}"},
                value_space="absolute",
                from_value=PRESENCE_HIDDEN,
                to_value=PRESENCE_VISIBLE,
                frames=channel_frames(policy, timeline),
                policy=policy,
                source_before=f"world.walls[{wall_id}]: absent",
                source_after=(
                    f"world.walls[{wall_id}]: built_tick="
                    f"{wall_after.get('built_tick')} integrity={wall_after['integrity']}"
                ),
                member_span=member_span_frames(policy, timeline),
            )
        )
    return directives


def _plan_depots(before: dict, after: dict, master_spec: dict, motion_spec: dict) -> list[dict]:
    """Storage-yard containers: which slots stand, and how they sit."""
    districts_before = _by_id(before["world"]["districts"], "before districts")
    districts_after = _by_id(after["world"]["districts"], "after districts")
    seed = master_spec["visual_seed"]
    placements_before: dict[str, float] = {}
    placements_after: dict[str, float] = {}
    provenance: dict[str, tuple[str, str]] = {}
    for district_id in sorted(districts_before):
        definition = master_spec["districts"][district_id]
        district_before = districts_before[district_id]
        district_after = districts_after[district_id]
        placements_before.update(depot_slot_placements(district_before, definition, seed))
        placements_after.update(depot_slot_placements(district_after, definition, seed))
        capacity = definition["depot_capacity"]
        provenance[district_id] = (
            f"world.districts[{district_id}].resources sum={_stock(district_before)}/{capacity}",
            f"world.districts[{district_id}].resources sum={_stock(district_after)}/{capacity}",
        )

    def district_of(name: str) -> str:
        """Recover the owning district id from a depot object name."""
        return name.removeprefix(DEPOT_PREFIX).rsplit("__", 1)[0]

    presence_policy = require_channel(motion_spec, "depot_slot_presence")
    settle_policy = require_channel(motion_spec, "depot_slot_settle")
    timeline = motion_spec["timeline"]

    appearing = sorted(set(placements_after) - set(placements_before))
    vanishing = sorted(set(placements_before) - set(placements_after))
    presence_members = vanishing + appearing
    settle_members = sorted(
        name
        for name in set(placements_before) & set(placements_after)
        if placements_before[name] != placements_after[name]
    )

    directives: list[dict] = []
    for index, name in enumerate(presence_members):
        appears = name in placements_after
        source_before, source_after = provenance[district_of(name)]
        directives.append(
            _directive(
                semantic_id=name,
                channel="depot_slot_presence",
                target={"kind": "object_presence", "object": name},
                value_space="absolute",
                from_value=PRESENCE_HIDDEN if appears else PRESENCE_VISIBLE,
                to_value=PRESENCE_VISIBLE if appears else PRESENCE_HIDDEN,
                frames=member_window(presence_policy, timeline, index, len(presence_members)),
                policy=presence_policy,
                source_before=source_before,
                source_after=source_after,
            )
        )
    for index, name in enumerate(settle_members):
        source_before, source_after = provenance[district_of(name)]
        directives.append(
            _directive(
                semantic_id=name,
                channel="depot_slot_settle",
                target={"kind": "object_transform", "object": name, "component": "rotation_z"},
                value_space="canonical_offset",
                from_value=placements_before[name] - placements_after[name],
                to_value=0.0,
                frames=member_window(settle_policy, timeline, index, len(settle_members)),
                policy=settle_policy,
                source_before=source_before,
                source_after=source_after,
            )
        )
    return directives


def _plan_infrastructure(
    before: dict, after: dict, master_spec: dict, motion_spec: dict
) -> list[dict]:
    """Conduit anchoring into the scar: struts appear, and the row re-centres."""
    infra_before = _by_id(before["world"]["infrastructure"], "before infrastructure")
    infra_after = _by_id(after["world"]["infrastructure"], "after infrastructure")
    if set(infra_before) != set(infra_after):
        raise MotionPlanError(
            "the two exports describe different infrastructure sets "
            f"({sorted(infra_before)} vs {sorted(infra_after)}); infrastructure "
            "appearing or vanishing is not a V1 visual transition"
        )
    walls_before = {wall["boundary_id"] for wall in before["world"]["walls"]}
    walls_after = {wall["boundary_id"] for wall in after["world"]["walls"]}

    placements_before: dict[str, tuple[float, float]] = {}
    placements_after: dict[str, tuple[float, float]] = {}
    provenance: dict[str, tuple[str, str]] = {}
    for infra_id in sorted(infra_before):
        entry_before = infra_before[infra_id]
        entry_after = infra_after[infra_id]
        if entry_before["boundary_id"] != entry_after["boundary_id"]:
            raise MotionPlanError(
                f"infrastructure {infra_id!r} moves from boundary "
                f"{entry_before['boundary_id']!r} to {entry_after['boundary_id']!r}; "
                "conduits do not relocate, and V1 refuses to animate it"
            )
        if bool(entry_before["degraded"]) != bool(entry_after["degraded"]):
            raise MotionPlanError(
                f"infrastructure {infra_id!r} changes condition "
                f"degraded={entry_before['degraded']} -> {entry_after['degraded']}. "
                "The locked static mapping expresses condition by SWAPPING the pipe "
                "material, which is an assignment and not an animatable value; "
                "animating it would need geometry V1 is not authorised to invent, so "
                "the transition is refused rather than approximated"
            )
        boundary = master_spec["boundaries"][entry_before["boundary_id"]]
        placements_before.update(
            strut_placements(entry_before, boundary, entry_before["boundary_id"] in walls_before)
        )
        placements_after.update(
            strut_placements(entry_after, boundary, entry_after["boundary_id"] in walls_after)
        )
        provenance[infra_id] = (
            f"world.infrastructure[{infra_id}].dependency_score="
            f"{entry_before['dependency_score']} wall="
            f"{entry_before['boundary_id'] in walls_before}",
            f"world.infrastructure[{infra_id}].dependency_score="
            f"{entry_after['dependency_score']} wall="
            f"{entry_after['boundary_id'] in walls_after}",
        )

    def infra_of(name: str) -> str:
        """Recover the owning infrastructure id from a strut object name."""
        return name.removeprefix(INFRA_PREFIX).rsplit("__wallstrut", 1)[0]

    presence_policy = require_channel(motion_spec, "infra_strut_presence")
    settle_policy = require_channel(motion_spec, "infra_strut_settle")
    timeline = motion_spec["timeline"]

    appearing = sorted(set(placements_after) - set(placements_before))
    vanishing = sorted(set(placements_before) - set(placements_after))
    presence_members = vanishing + appearing
    settle_members = sorted(
        name
        for name in set(placements_before) & set(placements_after)
        if placements_before[name] != placements_after[name]
    )

    directives: list[dict] = []
    for index, name in enumerate(presence_members):
        appears = name in placements_after
        source_before, source_after = provenance[infra_of(name)]
        directives.append(
            _directive(
                semantic_id=name,
                channel="infra_strut_presence",
                target={"kind": "object_presence", "object": name},
                value_space="absolute",
                from_value=PRESENCE_HIDDEN if appears else PRESENCE_VISIBLE,
                to_value=PRESENCE_VISIBLE if appears else PRESENCE_HIDDEN,
                frames=member_window(presence_policy, timeline, index, len(presence_members)),
                policy=presence_policy,
                source_before=source_before,
                source_after=source_after,
            )
        )
    components = ("location_x", "location_y")
    total = len(settle_members) * len(components)
    for index, name in enumerate(settle_members):
        source_before, source_after = provenance[infra_of(name)]
        for axis, component in enumerate(components):
            offset = placements_before[name][axis] - placements_after[name][axis]
            if offset == 0.0:
                continue
            directives.append(
                _directive(
                    semantic_id=name,
                    channel="infra_strut_settle",
                    target={"kind": "object_transform", "object": name, "component": component},
                    value_space="canonical_offset",
                    from_value=offset,
                    to_value=0.0,
                    frames=member_window(
                        settle_policy, timeline, index * len(components) + axis, total
                    ),
                    policy=settle_policy,
                    source_before=source_before,
                    source_after=source_after,
                )
            )
    return directives


def _require_export_shape(export: dict, label: str) -> None:
    """Refuse an export that is not a Render Export V1 world document."""
    world = export.get("world")
    if not isinstance(world, dict):
        raise MotionPlanError(f"{label} export has no world section")
    for key in ("districts", "boundaries", "walls", "laws", "infrastructure"):
        if not isinstance(world.get(key), list):
            raise MotionPlanError(f"{label} export world.{key} must be a JSON array")


def plan_motion(before: dict, after: dict, master_spec: dict, motion_spec: dict) -> dict:
    """Derive the deterministic MotionPlan between two Render Exports.

    Every directive is minimal (a value that did not change produces nothing),
    traceable (it names the export fields it came from), and sorted into a
    total order that does not depend on mapping iteration order anywhere.

    Raises:
        MotionPlanError: On any transition V1 cannot tell truthfully.
        SceneContractError: If either export disagrees with the master scene.
    """
    _require_export_shape(before, "before")
    _require_export_shape(after, "after")
    require_topology_agreement(master_spec, before)
    require_topology_agreement(master_spec, after)

    directives: list[dict] = []
    directives.extend(_plan_law(before, after, motion_spec))
    directives.extend(_plan_glazing(before, after, master_spec, motion_spec))
    directives.extend(_plan_walls(before, after, motion_spec))
    directives.extend(_plan_depots(before, after, master_spec, motion_spec))
    directives.extend(_plan_infrastructure(before, after, master_spec, motion_spec))
    directives.sort(key=_sort_key)

    seen: dict[tuple, str] = {}
    for directive in directives:
        key = _target_key(directive)
        owner = seen.get(key)
        if owner is not None:
            raise MotionPlanError(
                f"channels {owner!r} and {directive['channel']!r} both drive "
                f"{directive['target']}; one property cannot carry two transitions"
            )
        seen[key] = directive["channel"]

    by_channel: dict[str, int] = {}
    for directive in directives:
        by_channel[directive["channel"]] = by_channel.get(directive["channel"], 0) + 1

    plan = {
        "format": MOTION_PLAN_FORMAT,
        "schema_version": MOTION_PLAN_SCHEMA_VERSION,
        "timeline": dict(motion_spec["timeline"]),
        "before": _provenance(before),
        "after": _provenance(after),
        "directives": directives,
        "summary": {
            "directive_count": len(directives),
            "by_channel": dict(sorted(by_channel.items())),
            "animated_semantic_ids": sorted({d["semantic_id"] for d in directives}),
            "animated_channels": sorted(by_channel),
        },
    }
    return plan


def _provenance(export: dict) -> dict:
    """The identity of one export, as recorded in the plan."""
    source = export.get("source")
    if not isinstance(source, dict):
        return {"episode": None, "tick": None, "state_hash": None}
    return {
        "episode": source.get("episode"),
        "tick": source.get("tick"),
        "state_hash": source.get("state_hash"),
    }


def canonical_plan_bytes(plan: dict) -> bytes:
    """The plan's canonical encoding: sorted keys, compact, UTF-8, one newline."""
    return (json.dumps(plan, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def plan_hash(plan: dict) -> str:
    """SHA-256 of the plan's canonical encoding."""
    return hashlib.sha256(canonical_plan_bytes(plan)).hexdigest()


def keyframes(
    interpolation: str,
    samples: int,
    from_value: float,
    to_value: float,
    start_frame: int,
    end_frame: int,
) -> list[tuple[int, float]]:
    """The exact (frame, value) keys one value transition must carry.

    The project never inherits Blender's default Bezier: a ``step`` transition
    becomes two constant keys, and a ``linear`` or ``smoothstep`` transition is
    sampled from the documented formula at evenly spaced frames. Whatever the
    policy, the first key holds the exact from-value and the last key the exact
    to-value, so the endpoints can never drift.

    Raises:
        MotionPlanError: On a collapsed window or a non-positive sample count.
    """
    if end_frame <= start_frame:
        raise MotionPlanError(f"collapsed key window [{start_frame}, {end_frame}]")
    if isinstance(samples, bool) or not isinstance(samples, int) or samples < 1:
        raise MotionPlanError(f"sample count must be a positive integer, got {samples!r}")
    if interpolation == "step":
        return [(start_frame, float(from_value)), (end_frame, float(to_value))]
    span = end_frame - start_frame
    keys: list[tuple[int, float]] = []
    for index in range(samples + 1):
        frame = start_frame + int(math.floor(span * index / samples + 0.5))
        position = (frame - start_frame) / span
        value = interpolate(interpolation, from_value, to_value, position)
        if keys and keys[-1][0] == frame:
            continue
        keys.append((frame, value))
    keys[0] = (start_frame, float(from_value))
    keys[-1] = (end_frame, float(to_value))
    return keys


def sampled_keyframes(directive: dict) -> list[tuple[int, float]]:
    """The exact (frame, value) keys one directive's own F-curve must carry."""
    return keyframes(
        directive["interpolation"],
        directive["samples"],
        directive["from_value"],
        directive["to_value"],
        directive["start_frame"],
        directive["end_frame"],
    )


def load_export(path: str | Path) -> dict:
    """Load one Render Export document for planning.

    Raises:
        SceneContractError: If the document is not a Render Export V1.
    """
    from scene_spec import load_render_export

    return load_render_export(path)


def describe(plan: dict) -> str:
    """One-line human summary of a plan, for gate output."""
    summary = plan["summary"]
    channels = ", ".join(f"{name}x{count}" for name, count in sorted(summary["by_channel"].items()))
    return (
        f"{summary['directive_count']} directives over frames "
        f"{plan['timeline']['start_frame']}-{plan['timeline']['end_frame']}"
        + (f" ({channels})" if channels else " (nothing changed)")
    )


__all__ = [
    "MOTION_PLAN_FORMAT",
    "MOTION_PLAN_SCHEMA_VERSION",
    "MotionPlanError",
    "MotionSpecError",
    "SceneContractError",
    "canonical_plan_bytes",
    "depot_slot_placements",
    "describe",
    "glazing_value",
    "keyframes",
    "load_export",
    "plan_hash",
    "plan_motion",
    "sampled_keyframes",
    "seal_glow_value",
    "staged_frames",
    "strut_placements",
]
