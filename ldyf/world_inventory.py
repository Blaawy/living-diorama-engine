"""Machine classification of an Unreal actor dump (actor_dump_v1).

Phase-2 gate proof. The "professional non-blockout world", "vehicles have
wheels" and "humans have skeletal meshes with animation" claims are proven by a
deterministic classification of the in-editor actor dump, not by a screenshot.
This module owns that classification. Pure stdlib, deterministic, sorted-key
JSON on write.

Laws (frozen)
-------------
1. Pure stdlib, deterministic output, sorted-key JSON.
2. Any component asset under ``/Engine/BasicShapes/`` is BLOCKOUT, full stop.
   The actor still gets a normal role -- blockout is a flag, not a role.
3. No invented thresholds. ``min_building_kits`` / ``min_vehicle_wheels`` are
   arguments with the gate-plan defaults (3 / 4).
4. An actor's role is never guessed from its label. Role = actor class +
   component classes + asset path prefixes, and the rule that fired is written
   into every ``role_reason``.

Role rules are data: an ordered list of (predicate-name, role) pairs evaluated
in order; the first predicate that fires decides the role. Nothing that fires
-> "unknown".

Phase-2 L7 classifier facts
---------------------------
* A component whose class contains "poseablemesh" is bone-driven and counts as
  skeletal, exactly like a SkeletalMeshComponent: the v2 playback lane spawns
  City Sample vehicles as ``Actor`` + ``PoseableMeshComponent``.
* Vehicle wheels come from a component's ``wheel_bones`` list when the dump
  carries one (truthful bone names from the spawned mesh), falling back to the
  old name/class "wheel" count.
* A component is animated when it carries ``animation`` (the current sequence
  path, written by ldyf_playback.dump_actors) or ``anim_class``. This makes a
  L7 person -- SkeletalMeshComponent on TutorialTPP with an "animation" field
  -- classify as a skeletal, animated pedestrian.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

INVENTORY_VERSION = "world_inventory_v1"

# Law 2 marker: any asset path containing this is blockout.
BLOCKOUT_MARKER = "/Engine/BasicShapes/"

# Bone-driven component class markers (L7: PoseableMeshComponent is skeletal).
SKELETAL_CLASS_MARKERS = ("skeletalmesh", "poseablemesh")

# Keyword groups, matched case-insensitively against lowercased paths/classes.
PEDESTRIAN_KEYWORDS = ("crowd", "character", "mannequin", "manny", "quinn", "metahuman", "mca_")
VEHICLE_KEYWORDS = ("vehicle", "veh", "car", "truck", "van", "bus")
ROAD_KEYWORDS = ("road", "lane", "asphalt")
SIDEWALK_KEYWORDS = ("sidewalk", "curb", "kerb")
JUNCTION_KEYWORDS = ("junction", "intersection", "crosswalk")
BUILDING_KEYWORDS = ("bldg", "building", "facade")

ROLES = (
    "road",
    "sidewalk",
    "junction",
    "building",
    "vehicle",
    "pedestrian",
    "prop",
    "light",
    "camera",
    "volume",
    "unknown",
)


# --- predicates -----------------------------------------------------------


def _skeletal_hit(bag: dict[str, Any], keywords: tuple[str, ...]) -> str | None:
    """First SkeletalMesh/PoseableMesh component whose asset carries a keyword."""
    for c in bag["comps"]:
        cls = (c.get("class") or "").lower()
        if not any(m in cls for m in SKELETAL_CLASS_MARKERS):
            continue
        hay = "{} {}".format(c.get("skeleton") or "", c.get("asset") or "").lower()
        for kw in keywords:
            if kw in hay:
                name = c.get("name") or ""
                return f"skeletal component {name!r} asset contains {kw!r}"
    return None


def _spline_hit(bag: dict[str, Any], keywords: tuple[str, ...]) -> str | None:
    """First SplineMesh/InstancedStaticMesh component whose asset carries a keyword."""
    for c in bag["comps"]:
        cls = (c.get("class") or "").lower()
        if "splinemesh" not in cls and "instancedstaticmesh" not in cls:
            continue
        asset = (c.get("asset") or "").lower()
        for kw in keywords:
            if asset and kw in asset:
                return f"{c.get('class')} asset contains {kw!r}"
    return None


def _class_hit(bag: dict[str, Any], keywords: tuple[str, ...]) -> str | None:
    """Actor class containing one of the keywords (case-insensitive)."""
    cls = bag["class"].lower()
    for kw in keywords:
        if kw in cls:
            return f"actor class {bag['class']!r} contains {kw!r}"
    return None


def _p_skeletal_pedestrian(bag: dict[str, Any]) -> str | None:
    return _skeletal_hit(bag, PEDESTRIAN_KEYWORDS)


def _p_skeletal_vehicle(bag: dict[str, Any]) -> str | None:
    return _skeletal_hit(bag, VEHICLE_KEYWORDS)


def _p_spline_road(bag: dict[str, Any]) -> str | None:
    return _spline_hit(bag, ROAD_KEYWORDS)


def _p_spline_sidewalk(bag: dict[str, Any]) -> str | None:
    return _spline_hit(bag, SIDEWALK_KEYWORDS)


def _p_spline_junction(bag: dict[str, Any]) -> str | None:
    return _spline_hit(bag, JUNCTION_KEYWORDS)


def _p_static_building(bag: dict[str, Any]) -> str | None:
    for c in bag["comps"]:
        cls = (c.get("class") or "").lower()
        if "staticmesh" not in cls:
            continue
        if "skeletal" in cls or "spline" in cls or "instanced" in cls:
            continue
        asset = (c.get("asset") or "").lower()
        for kw in BUILDING_KEYWORDS:
            if asset and kw in asset:
                return f"static mesh asset contains {kw!r}"
    return None


def _p_class_light(bag: dict[str, Any]) -> str | None:
    return _class_hit(bag, ("light",))


def _p_class_camera(bag: dict[str, Any]) -> str | None:
    return _class_hit(bag, ("camera", "cine"))


def _p_class_volume(bag: dict[str, Any]) -> str | None:
    return _class_hit(bag, ("volume",))


def _p_mesh_prop(bag: dict[str, Any]) -> str | None:
    """'else prop' fallback: a mesh component / asset exists but no rule fired."""
    for c in bag["comps"]:
        if "mesh" in (c.get("class") or "").lower() or c.get("asset"):
            return "fallback prop: actor carries a mesh component or asset"
    if "mesh" in bag["class"].lower():
        return "fallback prop: actor class names a mesh"
    return None


# Ordered rule data: (predicate name, role). First match wins (Law: role rules
# evaluated in order; nothing matched -> "unknown").
ROLE_RULES: tuple[tuple[str, str], ...] = (
    ("skeletal_pedestrian", "pedestrian"),
    ("skeletal_vehicle", "vehicle"),
    ("spline_road", "road"),
    ("spline_sidewalk", "sidewalk"),
    ("spline_junction", "junction"),
    ("static_building", "building"),
    ("class_light", "light"),
    ("class_camera", "camera"),
    ("class_volume", "volume"),
    ("mesh_prop", "prop"),
)

_PREDICATES = {
    "skeletal_pedestrian": _p_skeletal_pedestrian,
    "skeletal_vehicle": _p_skeletal_vehicle,
    "spline_road": _p_spline_road,
    "spline_sidewalk": _p_spline_sidewalk,
    "spline_junction": _p_spline_junction,
    "static_building": _p_static_building,
    "class_light": _p_class_light,
    "class_camera": _p_class_camera,
    "class_volume": _p_class_volume,
    "mesh_prop": _p_mesh_prop,
}


def _resolve_role(bag: dict[str, Any]) -> tuple[str, str]:
    for name, role in ROLE_RULES:
        detail = _PREDICATES[name](bag)
        if detail is not None:
            return role, f"{role} ({name}): {detail}"
    return "unknown", "unknown: no role rule matched"


# --- public API -----------------------------------------------------------


def kit_of(asset_path: str) -> str | None:
    """Innermost containing-folder name of the asset's object path.

    ``/Game/Building/CH/SM_x.SM_x`` -> ``"CH"``. An object sitting directly in
    a content root (``/Game/...`` with no subfolder) has no kit -> ``None``.
    """
    if not asset_path:
        return None
    obj = asset_path.split(".", 1)[0]
    if "/" not in obj:
        return None
    folder = obj.rsplit("/", 1)[0]
    parts = [p for p in folder.split("/") if p]
    if len(parts) <= 1:
        return None
    return parts[-1]


def classify_actor(actor: dict) -> dict:
    """Classify one actor from the dump.

    Returns ``{"role", "role_reason", "blockout", "assets", "kit", "wheels",
    "skeletal", "animated"}``. ``blockout`` is a flag (Law 2) independent of
    the role. ``skeletal`` is True for SkeletalMeshComponent AND
    PoseableMeshComponent (L7: the v2 spawned vehicle); ``animated`` is True
    when a component carries an ``animation`` sequence path or an ``anim_class``.
    Wheels prefer a component's ``wheel_bones`` list length when the dump
    carries one, else the name/class "wheel" count (case-insensitive),
    regardless of role.
    """
    comps = actor.get("components") or []
    bag = {
        "class": actor.get("class") or "",
        "comps": comps,
    }
    role, reason = _resolve_role(bag)

    blockout = any(BLOCKOUT_MARKER in (c.get("asset") or "") for c in comps)

    assets: set[str] = set()
    wheels = 0
    skeletal = False
    animated = False
    for c in comps:
        asset = c.get("asset")
        if isinstance(asset, str) and asset:
            assets.add(asset)
        blob = "{} {}".format(c.get("name") or "", c.get("class") or "").lower()
        wheel_bones = c.get("wheel_bones")
        if isinstance(wheel_bones, list):
            wheels += len(wheel_bones)
        elif "wheel" in blob:
            wheels += 1
        cls = (c.get("class") or "").lower()
        if any(m in cls for m in SKELETAL_CLASS_MARKERS):
            skeletal = True
            if c.get("anim_class") or c.get("animation"):
                animated = True

    kit = None
    if role == "building":
        # First building-matching static asset, in component order.
        for c in comps:
            asset = c.get("asset") or ""
            if asset and any(kw in asset.lower() for kw in BUILDING_KEYWORDS):
                kit = kit_of(asset)
                break

    return {
        "role": role,
        "role_reason": reason,
        "blockout": blockout,
        "assets": sorted(assets),
        "kit": kit,
        "wheels": wheels,
        "skeletal": skeletal,
        "animated": animated,
    }


def inventory(dump: dict, *, min_building_kits: int = 3, min_vehicle_wheels: int = 4) -> dict:
    """Classify a whole dump and aggregate the gate metrics.

    ``building_kits.count`` is the number of *distinct* non-None kits among
    building-role actors; ``building_kits.pass`` is that count meeting
    ``min_building_kits``. ``vehicles.pass`` is every vehicle carrying at
    least ``min_vehicle_wheels`` wheels (vacuously true with no vehicles).
    ``pedestrians.pass`` is every pedestrian skeletal and animated (vacuously
    true with no pedestrians). Overall ``pass`` = no blockout actors AND all
    three sub-passes.
    """
    actors = dump.get("actors") or []
    counts = {role: 0 for role in ROLES}
    blockout_actors: list[str] = []
    unknown_actors: list[str] = []
    kits: set[str] = set()
    vehicle_total = 0
    vehicle_with_min = 0
    ped_total = 0
    ped_animated = 0

    for a in actors:
        c = classify_actor(a)
        name = a.get("name") or ""
        role = c["role"]
        counts[role] += 1
        if c["blockout"]:
            blockout_actors.append(name)
        if role == "unknown":
            unknown_actors.append(name)
        if role == "building" and c["kit"] is not None:
            kits.add(c["kit"])
        if role == "vehicle":
            vehicle_total += 1
            if c["wheels"] >= min_vehicle_wheels:
                vehicle_with_min += 1
        if role == "pedestrian":
            ped_total += 1
            if c["skeletal"] and c["animated"]:
                ped_animated += 1

    blockout_actors.sort()
    unknown_actors.sort()
    kits_sorted = sorted(kits)
    building_pass = len(kits_sorted) >= min_building_kits
    vehicles_pass = vehicle_with_min == vehicle_total
    peds_pass = ped_animated == ped_total
    overall_pass = (
        len(blockout_actors) == 0 and building_pass and vehicles_pass and peds_pass
    )

    return {
        "schema_version": INVENTORY_VERSION,
        "level": dump.get("level"),
        "counts_by_role": counts,
        "blockout_actors": blockout_actors,
        "blockout_count": len(blockout_actors),
        "building_kits": {
            "kits": kits_sorted,
            "count": len(kits_sorted),
            "pass": building_pass,
        },
        "vehicles": {
            "count": vehicle_total,
            "with_min_wheels": vehicle_with_min,
            "pass": vehicles_pass,
        },
        "pedestrians": {
            "count": ped_total,
            "skeletal_animated": ped_animated,
            "pass": peds_pass,
        },
        "unknown_actors": unknown_actors,
        "params": {
            "min_building_kits": min_building_kits,
            "min_vehicle_wheels": min_vehicle_wheels,
        },
        "pass": overall_pass,
    }


def write_inventory(dump_path: str | Path, out_path: str | Path, **params) -> dict:
    """Load an actor dump, classify it and write sorted-key JSON. Returns the result."""
    dump = json.loads(Path(dump_path).read_text(encoding="utf-8"))
    result = inventory(dump, **params)
    Path(out_path).write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8"
    )
    return result
