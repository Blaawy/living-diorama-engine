"""Structural tests for the Phase 18 population presence layer.

Executed by ``run_blender_tests_p18.py`` inside background Blender, after every
Phase 15, Phase 16 and Phase 17 structural test has passed. These tests own the
questions a reviewer will actually ask of a populated city:

* is anybody standing somewhere a person could not stand -- in a carriageway,
  inside a building, in the harbour, on a wall line, inside a lamp post;
* are the visible people the number the authoritative population earns;
* do the same slots stay put when the population grows;
* does a district with nobody in it show nobody;
* does rebuilding converge instead of growing ``.001`` copies;
* is the city underneath byte-for-byte the city that was there before;
* and does the Phase 17 motion layer still work over a populated world.

Two of them exist because the pure planner has to replicate Blender-side
geometry it cannot see: the plaza deck height and the Golden Seal's lighting
masts. Those replicas are pinned against the real objects here, so a Phase 16
change that moved them would fail loudly rather than quietly putting somebody
inside a lamp post.
"""

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import apply_motion_plan as motion  # noqa: E402
import apply_population_presence as population  # noqa: E402
import build_master_scene  # noqa: E402
import build_production_world  # noqa: E402
import figure_kit  # noqa: E402
import pedestrian_topology as topology  # noqa: E402
import population_presence_plan as presence_plan  # noqa: E402
from population_presence_spec import (  # noqa: E402
    ZONE_TYPES,
    load_population_presence_spec,
)
from production_spec import load_production_world_spec  # noqa: E402
from road_graph import build_road_graph  # noqa: E402
from scene_spec import load_master_scene_spec, load_render_export  # noqa: E402
from spatial_occupancy import circle, shape_gap  # noqa: E402
from urban_fabric import plan_urban_fabric  # noqa: E402

STYLE = "dna"

BODY_BAND = 2.1
"""How high above a surface a standing body reaches.

Furniture above this cannot meet anybody, so the mast replicas are pinned
against the vertices inside it rather than against a lamp head five metres up
that no proxy could ever touch."""

MAX_FIGURE_TRIANGLES = 950
MAX_LAYER_TRIANGLES = 68000
"""The declared geometry budget for the population layer.

No single body above 950 triangles, no more than 68,000 for the whole layer.
Both ceilings are the remediation's, raised from 430 and 30,000 when Visual
DNA v2 was authorised, and they must stay equal to the pins the pure suites
carry in ``test_figure_kit.py`` and ``test_population_presence_plan.py``.

The raise bought resolution where the first rebuild was visibly coarse:
twelve facets around every skull with five rings and two poles through it, an
eight-sided six-section torso, five-ring legs with a real calf, three-member
arms ending in hands, socket rings closing the armpits, ears, and a shaped
28-triangle brim on the cap. Measured against the FINAL kit on 2026-08-16,
the heaviest body the vocabulary can build costs 902 -- a child with tied
hair, a beard and formal clothing -- none of the 6,912 primitive-changing
combinations exceeds the 950 ceiling, and the canonical eighty cost 66,300
of the 68,000 layer ceiling with a heaviest fielded body of 902 and a
lightest of 668. The per-body ceiling still has room; the LAYER ceiling has
1,700 triangles left, two and a half per cent, and eighty of the heaviest
body would come to 72,160. Check the layer before adding geometry rather
than assuming there is room.

The figure bevel is worth recording here, because this suite counts the
triangles it produces. ``blender_runtime.add_bevel`` gained an optional
``limit_method`` DEFAULTING to the existing angle/40-degree behaviour, so
vehicles, buildings and every other caller are byte-identical; only
``apply_population_presence`` passes ``"NONE"``, at both figure call sites.
An angle threshold cannot work for a walking figure: the swept dihedrals
form one continuous block from 0.001 to 128.55 degrees with no gap in it, so
75 degrees still left 841 crossings and the first angle that crosses nothing
bevels nothing at all. ``"NONE"`` makes bevel selection a function of
TOPOLOGY -- and therefore of identity -- rather than of pose, which is what
holds the evaluated vertex count still across a stride.

THE CEILINGS ABOVE NO LONGER BOUND THE EVALUATED COST, and a reviewer needs
to know it. ``MAX_FIGURE_TRIANGLES`` and ``MAX_LAYER_TRIANGLES`` are counted
on the DATABLOCK -- the mesh as authored, before modifiers. Bevelling with
no angle limit touches every edge rather than the few that cross a
threshold, which the gate measured at 8.25x the datablock count and 2.34x
the previous angle behaviour: roughly 536,000 evaluated triangles for the
eighty figures against about 229,000 before. The datablock still fits
64,748 of 68,000, and that is a true statement about a number which is no
longer the whole cost.

The trade was accepted for this candidate because the alternatives were a
broken gait proof or a flat leg. ``limit_method="WEIGHT"`` is the cheaper
long-term answer -- it bevels an explicitly marked edge set, so it is
pose-independent like ``"NONE"`` without paying for every edge -- and it is
the direction a future pass should take rather than raising these ceilings.

    THE GEOMETRY NOW DEPENDS ON THAT BEVEL METHOD. DO NOT REVERT ONE
    WITHOUT THE OTHER.

The arm once carried a fourth ring (a collar) and the leg a sixth (a
kneecap). Neither was anatomy: both existed solely to hold a hinge's rest
dihedral under the 40-degree angle limit, and both were removed once the
bevel stopped consulting angles -- the collar because it was also causing a
reported shoulder pad, a 51.8-degree convex ridge at full shoulder width
with a 28mm overhanging wall beneath it.

Removing them made the dihedral picture WORSE, which is exactly the point:
crossings at 40 degrees went from 243 to 702, and at 50 degrees from 751 to
1193, with 402 still crossing at 60. Under ``"NONE"`` none of that matters,
because nothing is ever compared against an angle. Restore an angle limit
over this geometry and the evaluated vertex count becomes unstable across a
stride again -- worse than it was before the rings were ever added, and the
gait proof that depends on a stable count breaks with it.

Those figures are evidence; the two ceilings above are the contract."""

MAX_FOOT_DROP = 0.16
"""How far above the built floor a body's feet may sit.

Small but not zero: the frontage walk strips and kerb lips Phase 16 lays over
the ground are a few centimetres proud of it, and the planner deliberately
does not model every one of them. Anything more than this reads as hovering.
"""

MIN_BODY_CLEARANCE = 0.15
"""Open ground a body must keep from any vertical geometry in its own height
band, measured against the REAL scene rather than the planner's model.

The pure contract asks for far more than this; the margin here is what
survives after every replica, rounding and envelope approximation in the
pipeline. It exists to catch the class of defect a pure model cannot see at
all -- a Blender-side detail object nobody registered."""


def _sync() -> None:
    """Force Blender to recompute object matrices before anything reads them.

    ``obj.matrix_world`` is evaluated lazily: an object created and given a
    location in the same script still reports an IDENTITY matrix until the
    view layer updates. Every world-space measurement below would silently
    compare plan coordinates against LOCAL vertex coordinates and pass while
    proving nothing, which is precisely what happened the first time this
    suite ran.
    """
    bpy.context.view_layer.update()


def _presence_context(context) -> dict:
    """Rebuild the canonical city and derive the presence plan for it.

    Rebuilt rather than inherited: the Phase 17 suite runs first and leaves an
    animated union scene behind, which is not the world Phase 18 describes.
    Everything below therefore measures a city in exactly the state the proof
    renders it in.
    """
    cache = context.get("presence")
    if cache is not None:
        return cache
    master_spec = load_master_scene_spec(context["spec_path"])
    production = load_production_world_spec(context["production_path"])
    presence_spec = load_population_presence_spec(context["presence_path"])
    build_master_scene.build_master_scene(context["spec_path"], style=STYLE)
    build_production_world.add_production_world(
        context["spec_path"], context["production_path"], style=STYLE
    )
    graph = build_road_graph(master_spec, production)
    fabric = plan_urban_fabric(master_spec, production, graph)
    topology_plan = topology.plan_pedestrian_topology(
        master_spec, production, graph, fabric, presence_spec
    )
    _sync()
    export = load_render_export(context["before_path"])
    plan = presence_plan.plan_population_presence(export, master_spec, presence_spec, topology_plan)
    cache = {
        "master_spec": master_spec,
        "production": production,
        "presence_spec": presence_spec,
        "graph": graph,
        "fabric": fabric,
        "topology": topology_plan,
        "export": export,
        "plan": plan,
        "city_snapshot": _city_snapshot(),
    }
    context["presence"] = cache
    return cache


def _city_snapshot() -> list[tuple]:
    """Identity, transform, mesh and materials of every non-population object.

    Transforms alone would not notice the population layer appending a
    material slot to a locked Phase 16 object, or swapping its mesh: nothing
    would have moved, and "the city underneath is untouched" would be a claim
    about position only.
    """
    return sorted(
        (
            obj.name,
            tuple(round(value, 5) for value in obj.location),
            tuple(round(value, 5) for value in obj.rotation_euler),
            tuple(round(value, 5) for value in obj.scale),
            obj.data.name if obj.data is not None else "",
            tuple(slot.material.name if slot.material else "" for slot in obj.material_slots),
            len(obj.modifiers),
        )
        for obj in bpy.data.objects
        if not obj.name.startswith(population.PROXY_PREFIX)
    )


def _apply(context) -> dict:
    """Ensure the canonical presence layer stands in the rebuilt city."""
    state = _presence_context(context)
    if not state.get("applied"):
        state["metrics"] = population.apply_population_presence(
            state["plan"], state["presence_spec"]
        )
        state["applied"] = True
        _sync()
    return state


def _floor_targets() -> list:
    """Every non-population mesh a body could be standing on."""
    _sync()
    return [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and not obj.name.startswith(population.PROXY_PREFIX)
        and len(obj.data.vertices)
    ]


def _vertical_geometry() -> list[tuple[str, list]]:
    """Every non-population mesh in the scene, as world-space vertex clouds."""
    _sync()
    clouds = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or obj.name.startswith(population.PROXY_PREFIX):
            continue
        if not len(obj.data.vertices):
            continue
        clouds.append((obj.name, [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]))
    return clouds


def test_the_population_layer_lives_in_its_own_collection(context) -> None:
    """One collection, under the master root, holding exactly the proxies."""
    state = _apply(context)
    collection = bpy.data.collections.get(population.POPULATION_ROOT)
    assert collection is not None, "LD_POPULATION was never created"
    world = bpy.data.collections.get("LD_WORLD")
    assert population.POPULATION_ROOT in {child.name for child in world.children}
    names = {obj.name for obj in collection.objects}
    assert names == {f"{population.PROXY_PREFIX}{p['slot']}" for p in state["plan"]["proxies"]}
    summary = population.population_summary()
    assert summary["linked_elsewhere"] == 0, "a proxy is linked outside LD_POPULATION"


def test_the_visible_count_is_the_count_population_earns(context) -> None:
    """The scene holds exactly as many people as the plan derived."""
    state = _apply(context)
    objects = population.population_objects()
    assert len(objects) == state["plan"]["summary"]["active_proxies"]
    for district_id, entry in sorted(state["plan"]["districts"].items()):
        built = [obj for obj in objects if f"__{district_id}__" in obj.name]
        assert len(built) == entry["active_proxies"], (
            f"{district_id} shows {len(built)} proxies, its population earns "
            f"{entry['active_proxies']}"
        )


def test_every_proxy_carries_its_stable_semantic_name(context) -> None:
    """``LD_POP__<district>__slot_NNN``, and short enough for Blender to keep."""
    state = _apply(context)
    for proxy in state["plan"]["proxies"]:
        name = f"{population.PROXY_PREFIX}{proxy['slot']}"
        assert bpy.data.objects.get(name) is not None, f"{name} is missing"
        assert len(name.encode("utf-8")) <= 63, (
            f"{name} is {len(name.encode('utf-8'))} bytes; Blender truncates past 63 and "
            "replace-by-name idempotency would break"
        )


def test_rebuilding_the_same_plan_changes_nothing(context) -> None:
    """Idempotency: same plan, same objects, same transforms, no growth."""
    state = _apply(context)
    before = population.proxy_positions()
    objects_before = len(bpy.data.objects)
    meshes_before = len(bpy.data.meshes)
    population.apply_population_presence(state["plan"], state["presence_spec"])
    assert population.proxy_positions() == before, "a rebuild moved somebody"
    assert len(bpy.data.objects) == objects_before, "a rebuild grew the object count"
    assert len(bpy.data.meshes) == meshes_before, "a rebuild grew the mesh count"
    assert population.population_summary()["duplicate_named_objects"] == 0


def test_the_city_underneath_is_untouched(context) -> None:
    """Population is additive: nothing else moved, and nothing else vanished."""
    state = _apply(context)
    assert _city_snapshot() == state["city_snapshot"], (
        "the population layer changed the city it was supposed to stand in"
    )


def test_removing_the_layer_leaves_the_city_alone(context) -> None:
    """The layer is fully removable, and takes only its own datablocks."""
    state = _apply(context)
    removed = population.clear_population_layer()
    assert removed == len(state["plan"]["proxies"])
    assert not population.population_objects()
    assert _city_snapshot() == state["city_snapshot"]
    assert not [mesh for mesh in bpy.data.meshes if mesh.name.startswith("LD_POP")]
    population.apply_population_presence(state["plan"], state["presence_spec"])
    assert len(population.population_objects()) == len(state["plan"]["proxies"])


def test_nobody_stands_in_a_carriageway(context) -> None:
    """The failure that would matter most, checked against the road envelopes."""
    state = _apply(context)
    validator = topology.build_presence_occupancy(
        state["master_spec"], state["production"], state["graph"], state["fabric"]
    )
    shapes = topology.street_occupancy_shapes(validator)
    radius = float(state["presence_spec"]["proxy"]["radius"])
    for proxy in state["plan"]["proxies"]:
        body = circle(proxy["x"], proxy["y"], radius)
        for shape in shapes:
            assert shape_gap(body, shape) > 0.0, (
                f"{proxy['slot']} stands in a carriageway at ({proxy['x']}, {proxy['y']})"
            )


def test_no_proxy_touches_protected_geometry(context) -> None:
    """Re-prove the whole clearance table against a freshly loaded occupancy."""
    state = _apply(context)
    errors = topology.validate_pedestrian_topology(
        state["topology"],
        state["master_spec"],
        state["production"],
        state["graph"],
        state["fabric"],
    )
    assert not errors, "\n".join(errors[:5])
    validator = topology.build_presence_occupancy(
        state["master_spec"], state["production"], state["graph"], state["fabric"]
    )
    radius = float(state["presence_spec"]["proxy"]["radius"])
    for proxy in state["plan"]["proxies"]:
        conflicts = topology.presence_conflicts(validator, circle(proxy["x"], proxy["y"], radius))
        assert not conflicts, f"{proxy['slot']} violates {conflicts[0]}"


def test_no_proxy_intersects_real_scene_geometry(context) -> None:
    """The question a pure model cannot answer: measure the built world.

    Every replica, envelope and rounding in the pipeline is an approximation
    of what Blender actually builds. This walks the real vertices of every
    other mesh and refuses any that reaches into a body's own height band --
    the only check that would catch a detail object nobody thought to model.
    """
    state = _apply(context)
    radius = float(state["presence_spec"]["proxy"]["radius"])
    clouds = _vertical_geometry()
    worst = (math.inf, "", "")
    for proxy in state["plan"]["proxies"]:
        low = proxy["z"] + 0.05
        high = proxy["z"] + float(proxy["height"])
        for name, points in clouds:
            for point in points:
                if point.z < low or point.z > high:
                    continue
                gap = math.hypot(point.x - proxy["x"], point.y - proxy["y"]) - radius
                if gap < worst[0]:
                    worst = (gap, proxy["slot"], name)
    assert worst[0] >= MIN_BODY_CLEARANCE, (
        f"{worst[1]} comes within {round(worst[0], 4)} of {worst[2]}, below the "
        f"{MIN_BODY_CLEARANCE} minimum body clearance"
    )


def test_no_body_is_buried_in_the_world_it_stands_on(context) -> None:
    """Measure burial against Blender's own geometry, not against the planner.

    The pure model of the floor is a MODEL. Re-deriving a proxy's z from the
    same function that produced it proves only that the function is
    consistent with itself, and the first version of this suite did exactly
    that while twelve of eighty bodies stood knee-deep in the founding
    district plates -- a surface the Phase 16 ground model never described.

    So this asks Blender. An upward ray from just above each proxy's feet
    that exits through an UP-facing surface means the body is inside a solid;
    a down-facing hit is an overhang (a crane boom, a lamp arm) and is fine.
    """
    state = _apply(context)
    _sync()
    targets = [
        obj
        for obj in bpy.data.objects
        if obj.type == "MESH"
        and not obj.name.startswith(population.PROXY_PREFIX)
        and len(obj.data.vertices)
    ]
    assert targets, "there is no city to be buried in"
    buried = []
    for proxy in state["plan"]["proxies"]:
        origin = Vector((proxy["x"], proxy["y"], proxy["z"] + 0.01))
        for obj in targets:
            inverse = obj.matrix_world.inverted()
            direction = (inverse.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
            hit, location, normal, _index = obj.ray_cast(
                inverse @ origin, direction, distance=float(proxy["height"])
            )
            if not hit:
                continue
            if ((obj.matrix_world.to_3x3() @ normal).normalized()).z <= 0.15:
                continue
            depth = (obj.matrix_world @ location).z - proxy["z"]
            buried.append((round(depth, 4), proxy["slot"], obj.name))
    assert not buried, f"bodies standing inside solid geometry: {sorted(buried, reverse=True)[:5]}"


def _built_floor(targets: list, x: float, y: float, feet: float) -> tuple[float, str]:
    """The highest real surface at (x, y) that is not above a body's feet.

    Cast DOWNWARD from just above the feet, per object, over everything except
    the proxies themselves. Starting below the feet would begin inside the very
    slab the body stands on and exit through its underside, reporting whatever
    lies beneath it -- which is how the first version of the hover test managed
    to accuse correctly-placed bodies of floating.
    """
    best = (-math.inf, "nothing")
    for obj in targets:
        inverse = obj.matrix_world.inverted()
        origin = inverse @ Vector((x, y, feet + 0.05))
        direction = (inverse.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
        hit, location, _normal, _index = obj.ray_cast(origin, direction, distance=6.0)
        if not hit:
            continue
        height = (obj.matrix_world @ location).z
        if height > feet + 0.05:
            continue
        if height > best[0]:
            best = (height, obj.name)
    return best


def test_no_body_hovers_above_the_world_it_stands_on(context) -> None:
    """The other half of the same question, also asked of Blender.

    A floor model that over-covers is as wrong as one that under-covers: it
    leaves bodies standing on air. The highest real surface under each body
    must be within a short drop of its feet.
    """
    state = _apply(context)
    _sync()
    targets = _floor_targets()
    hovering = []
    for proxy in state["plan"]["proxies"]:
        height, name = _built_floor(targets, proxy["x"], proxy["y"], proxy["z"])
        drop = proxy["z"] - height
        if drop > MAX_FOOT_DROP:
            hovering.append((proxy["slot"], round(drop, 3), name))
    assert not hovering, f"bodies standing on air: {sorted(hovering, key=lambda e: -e[1])[:5]}"


def test_the_pure_floor_model_matches_the_built_floor(context) -> None:
    """Pin the planner's floor model against the surface Blender actually built.

    Complements the two ray-cast tests: they prove no body is buried or
    hovering, this proves the PURE function a reviewer can run without Blender
    gives the same answer as the world.
    """
    state = _apply(context)
    _sync()
    targets = _floor_targets()
    for proxy in state["plan"]["proxies"]:
        modelled = topology.presence_ground_level(
            proxy["x"], proxy["y"], state["master_spec"], state["fabric"]
        )
        height, name = _built_floor(targets, proxy["x"], proxy["y"], proxy["z"])
        assert modelled - height <= MAX_FOOT_DROP, (
            f"the floor model puts {proxy['slot']} at {modelled}, Blender built {height} ({name})"
        )
        assert height - modelled <= 1.0e-3, (
            f"the floor model puts {proxy['slot']} BELOW the built floor: "
            f"{modelled} vs {height} ({name})"
        )


def test_the_plaza_deck_replica_matches_the_real_plaza(context) -> None:
    """Pin the deck height the pure planner has to assume.

    ``city_ground`` knows the city's floor; it does not know a plaza is built
    ON that floor. Phase 18 adds the deck itself, so the constant it adds is
    compared here with the object Phase 16 actually builds.
    """
    state = _apply(context)
    _sync()
    checked = 0
    for neighborhood_id, entry in sorted(state["fabric"]["neighborhoods"].items()):
        plaza = entry["plaza"]
        if plaza is None:
            continue
        obj = bpy.data.objects.get(f"LD_P16_PLAZA__{neighborhood_id}")
        assert obj is not None, f"the {neighborhood_id} plaza is missing"
        top = max((obj.matrix_world @ vertex.co).z for vertex in obj.data.vertices)
        expected = float(plaza["base"]) + topology.PLAZA_DECK_THICKNESS
        assert abs(top - expected) < 1.0e-4, (
            f"the {neighborhood_id} plaza deck tops out at {top}, the replica assumes {expected}"
        )
        checked += 1
    assert checked, "no plaza was available to pin the deck replica against"


def test_the_plaza_mast_replica_matches_the_real_masts(context) -> None:
    """Pin the plaza furniture the pure planner has to assume.

    A plaza is registered as walkable ground and the seven masts standing on
    it are registered nowhere, so Phase 18 models them. Same drift risk as the
    Seal masts, same answer: compare the replica with what Blender built.
    """
    state = _apply(context)
    _sync()
    furniture = {
        entry_id: shapes
        for entry_id, _category, shapes in topology.street_furniture(
            state["master_spec"], state["fabric"]
        )
    }
    checked = 0
    for neighborhood_id, entry in sorted(state["fabric"]["neighborhoods"].items()):
        if entry["plaza"] is None:
            continue
        obj = bpy.data.objects.get(f"LD_P16_PLAZA__{neighborhood_id}__masts")
        assert obj is not None, f"the {neighborhood_id} plaza masts are missing"
        shapes = furniture[f"plaza_masts_{neighborhood_id}"]
        for vertex in obj.data.vertices:
            point = obj.matrix_world @ vertex.co
            if point.z > entry["plaza"]["base"] + BODY_BAND:
                continue
            covered = any(
                math.hypot(point.x - shape["x"], point.y - shape["y"]) <= shape["r"] + 1.0e-4
                for shape in shapes
            )
            assert covered, (
                f"a {neighborhood_id} mast vertex at ({point.x}, {point.y}) lies outside "
                "every modelled mast envelope"
            )
        checked += 1
    assert checked, "no plaza was available to pin the mast replica against"


def test_the_seal_mast_replica_matches_the_real_masts(context) -> None:
    """Pin the civic forecourt's obstacles against the built monument.

    Vertex by vertex, not radius by radius: the four masts sit on a ring, so a
    radial-extent check passes unchanged if they are ROTATED to different
    angles on the same ring, and the forecourt would then be modelled with its
    lamp posts in the wrong places.
    """
    state = _apply(context)
    _sync()
    obj = bpy.data.objects.get("LD_SEAL__masts")
    assert obj is not None, "the Golden Seal masts are missing"
    modelled = [
        shapes[0]
        for entry_id, _category, shapes in topology.street_furniture(
            state["master_spec"], state["fabric"]
        )
        if entry_id.startswith("seal_mast_")
    ]
    assert len(modelled) == 4
    base = min((obj.matrix_world @ vertex.co).z for vertex in obj.data.vertices)
    checked = 0
    for vertex in obj.data.vertices:
        point = obj.matrix_world @ vertex.co
        if point.z > base + BODY_BAND:
            continue
        assert any(
            math.hypot(point.x - shape["x"], point.y - shape["y"]) <= shape["r"] + 1.0e-4
            for shape in modelled
        ), f"a Seal mast vertex at ({point.x}, {point.y}) lies outside every modelled mast"
        checked += 1
    assert checked, "no mast vertex fell inside a body's height band"


def test_zero_population_shows_nobody(context) -> None:
    """A district with no residents gets no proxies -- and the rest are unmoved."""
    state = _apply(context)
    emptied = _with_populations(state["export"], {"district_b": 0})
    plan = presence_plan.plan_population_presence(
        emptied, state["master_spec"], state["presence_spec"], state["topology"]
    )
    assert plan["districts"]["district_b"]["active_proxies"] == 0
    assert "district_b" in plan["summary"]["districts_with_no_presence"]
    assert not [proxy for proxy in plan["proxies"] if proxy["district"] == "district_b"]
    for district_id in ("district_a", "district_c", "district_d"):
        assert (
            plan["districts"][district_id]["active_proxies"]
            == state["plan"]["districts"][district_id]["active_proxies"]
        )
    population.apply_population_presence(plan, state["presence_spec"])
    assert len(population.population_objects()) == plan["summary"]["active_proxies"]
    assert not [obj for obj in population.population_objects() if "__district_b__" in obj.name]
    population.apply_population_presence(state["plan"], state["presence_spec"])


def test_a_growing_population_extends_the_same_slots(context) -> None:
    """More residents activate MORE slots; it never rearranges the old ones."""
    state = _apply(context)
    grown = _with_populations(state["export"], {"district_a": 320})
    plan = presence_plan.plan_population_presence(
        grown, state["master_spec"], state["presence_spec"], state["topology"]
    )
    before = [p for p in state["plan"]["proxies"] if p["district"] == "district_a"]
    after = [p for p in plan["proxies"] if p["district"] == "district_a"]
    assert len(after) > len(before), "a larger population showed no more people"
    assert after[: len(before)] == before, "growth reshuffled the people already standing there"
    population.apply_population_presence(plan, state["presence_spec"])
    positions = population.proxy_positions()
    for proxy in before:
        name = f"{population.PROXY_PREFIX}{proxy['slot']}"
        placed = positions[name]
        for axis, value in enumerate((proxy["x"], proxy["y"], proxy["z"])):
            assert abs(placed[axis] - value) < 1.0e-4, (
                f"{name} moved on axis {axis}: {placed[axis]} vs {value}"
            )
    population.apply_population_presence(state["plan"], state["presence_spec"])


def test_presence_spreads_across_the_approved_area_types(context) -> None:
    """Every zone the policy funds and the ground supplies is actually used."""
    state = _apply(context)
    used = {proxy["zone"] for proxy in state["plan"]["proxies"]}
    assert used <= set(ZONE_TYPES), f"the plan invented a zone type: {used - set(ZONE_TYPES)}"
    assert len(used) >= 3, f"presence collapsed onto too few area types: {sorted(used)}"
    for zone_id in sorted(used):
        assert state["plan"]["summary"]["proxies_by_zone"][zone_id] > 0


def test_the_proxy_kit_builds_readable_bodies(context) -> None:
    """A body is a person-shaped, person-sized object carrying four materials."""
    state = _apply(context)
    _sync()
    for proxy in state["plan"]["proxies"]:
        obj = bpy.data.objects[f"{population.PROXY_PREFIX}{proxy['slot']}"]
        zs = [(obj.matrix_world @ vertex.co).z for vertex in obj.data.vertices]
        height = max(zs) - proxy["z"]
        assert 1.0 <= height <= 2.2, f"{proxy['slot']} is {height} tall"
        assert abs(height - float(proxy["height"])) < 0.12, (
            f"{proxy['slot']} builds to {height} against a planned {proxy['height']}"
        )
        assert len(obj.data.materials) == 4, "clothing, complexion, hair and accent"


def test_the_built_city_contains_visibly_different_people(context) -> None:
    """The Director's question, asked of the scene rather than of the plan.

    Every archetype the vocabulary offers has to actually stand in the world,
    and no two bodies may be the same body. A population that reads as many
    copies of one generic person is the defect this test exists to catch.
    """
    state = _apply(context)
    proxies = state["plan"]["proxies"]
    ages = {proxy["age_presentation"] for proxy in proxies}
    assert ages == set(figure_kit.AGE_PRESENTATIONS), f"only {sorted(ages)} appear in the city"
    assert len({proxy["build"] for proxy in proxies}) == len(figure_kit.BUILDS)
    assert len({proxy["stature"] for proxy in proxies}) == len(figure_kit.STATURES)
    assert len({proxy["presentation"] for proxy in proxies}) == len(figure_kit.PRESENTATIONS)
    assert len({proxy["hair"] for proxy in proxies}) >= 5
    assert len({proxy["clothing"] for proxy in proxies}) >= 5
    meshes = [
        bpy.data.objects[f"{population.PROXY_PREFIX}{proxy['slot']}"].data.name for proxy in proxies
    ]
    assert len(set(meshes)) == len(meshes), "two visible people share one body"


def test_the_scene_agrees_with_the_planned_proportions(context) -> None:
    """The bodies Blender built are the bodies the pure kit described.

    Measured, not trusted: a child's head really is proportionally larger in
    the mesh, and a broad figure really is wider across the shoulders.
    """
    state = _apply(context)
    _sync()
    heights: dict[str, list[float]] = {}
    widths: dict[str, list[float]] = {}
    for proxy in state["plan"]["proxies"]:
        obj = bpy.data.objects[f"{population.PROXY_PREFIX}{proxy['slot']}"]
        points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
        heights.setdefault(proxy["age_presentation"], []).append(
            max(point.z for point in points) - proxy["z"]
        )
        span = max(
            math.hypot(a.x - b.x, a.y - b.y)
            for a in points
            for b in points
            if a.z > proxy["z"] + float(proxy["height"]) * 0.60
            and b.z > proxy["z"] + float(proxy["height"]) * 0.60
        )
        widths.setdefault(proxy["build"], []).append(span)
    assert max(heights["child"]) < min(heights["adult"]), (
        "a child in the built scene is not shorter than every built adult"
    )
    # Compared at a FIXED age and stature. Across the whole scene the widest
    # broad body beats the narrowest slim one for free -- a tall broad adult
    # against a short slim child proves nothing about build.
    paired: dict[tuple[str, str], dict[str, float]] = {}
    for proxy in state["plan"]["proxies"]:
        key = (proxy["age_presentation"], proxy["stature"])
        paired.setdefault(key, {})[proxy["build"]] = float(proxy["shoulder_width"])
    compared = 0
    for key, builds in sorted(paired.items()):
        if "slim" in builds and "broad" in builds:
            assert builds["broad"] > builds["slim"], (
                f"a broad {key[0]} of {key[1]} stature is not broader than a slim one"
            )
            compared += 1
        if "athletic" in builds and "slim" in builds:
            assert builds["athletic"] > builds["slim"], (
                f"an athletic {key[0]} of {key[1]} stature is not broader than a slim one"
            )
            compared += 1
    assert compared > 0, "the scene held no like-for-like build comparison to make"


def test_no_two_neighbours_read_as_the_same_person(context) -> None:
    """Local duplication control, measured in the built world."""
    state = _apply(context)
    radius = float(state["presence_spec"]["figure"]["diversity"]["radius"])
    proxies = state["plan"]["proxies"]
    for first in range(len(proxies)):
        for second in range(first + 1, len(proxies)):
            gap = math.hypot(
                proxies[first]["x"] - proxies[second]["x"],
                proxies[first]["y"] - proxies[second]["y"],
            )
            if gap > radius:
                continue
            assert figure_kit.silhouette_signature(
                proxies[first]
            ) != figure_kit.silhouette_signature(proxies[second]), (
                f"{proxies[first]['slot']} and {proxies[second]['slot']} stand "
                f"{round(gap, 2)} apart and read as the same person"
            )


def test_the_population_stays_inside_its_geometry_budget(context) -> None:
    """Diversity must come from vocabulary, not from heavier bodies."""
    state = _apply(context)
    total = 0
    for proxy in state["plan"]["proxies"]:
        obj = bpy.data.objects[f"{population.PROXY_PREFIX}{proxy['slot']}"]
        obj.data.calc_loop_triangles()
        count = len(obj.data.loop_triangles)
        assert count <= MAX_FIGURE_TRIANGLES, f"{proxy['slot']} costs {count} triangles"
        total += count
    assert total <= MAX_LAYER_TRIANGLES, f"the population layer costs {total} triangles"


def test_every_body_is_finished_the_same_way(context) -> None:
    """Shared geometry is not the same as a shared appearance.

    A bevel is an OBJECT modifier, not mesh data, so bodies sharing a mesh
    datablock do not inherit it. The first version of this builder gave it only
    to the first proxy of each (variant, pose) and left the other sixty
    rendering as hard-edged boxes -- shared meshes, unshared appearance.
    """
    state = _apply(context)
    objects = population.population_objects()
    assert objects
    for obj in objects:
        bevels = [modifier for modifier in obj.modifiers if modifier.type == "BEVEL"]
        assert len(bevels) == 1, f"{obj.name} carries {len(bevels)} bevel modifiers"
        assert abs(bevels[0].width - population.PROXY_BEVEL) < 1.0e-6
    assert len({obj.data.name for obj in objects}) == len(
        {proxy["geometry_key"] for proxy in state["plan"]["proxies"]}
    ), "one mesh datablock per distinct body, no more and no fewer"


def test_removing_the_layer_takes_its_collection_too(context) -> None:
    """Full removal means the file carries no trace of the layer.

    An empty ``LD_POPULATION`` still hanging under ``LD_WORLD`` is a trace, so
    the collection goes with the objects and the meshes.
    """
    state = _apply(context)
    population.clear_population_layer()
    assert bpy.data.collections.get(population.POPULATION_ROOT) is None
    world = bpy.data.collections.get("LD_WORLD")
    assert population.POPULATION_ROOT not in {child.name for child in world.children}
    assert _city_snapshot() == state["city_snapshot"]
    population.apply_population_presence(state["plan"], state["presence_spec"])
    assert bpy.data.collections.get(population.POPULATION_ROOT) is not None
    assert len(population.population_objects()) == len(state["plan"]["proxies"])


FACE_PROBE_COMBINATIONS = tuple(
    {
        "age_presentation": age,
        "presentation": presentation,
        "stature": "average",
        "build": "average",
        "hair": hair,
        "facial_hair": growth,
        "face": face,
        "clothing": "shirt",
        "palette": "slate",
        "complexion": "c1",
        "hair_tone": "h1",
        "pose": pose,
    }
    for age, presentation, hair, growth, face, pose in (
        ("child", "unspecified", "short", "none", "a", "idle"),
        ("teen", "feminine", "long", "none", "c", "observe"),
        ("adult", "masculine", "bald", "beard", "b", "stroll"),
        ("adult", "feminine", "tied", "none", "d", "rest"),
        ("adult", "masculine", "cap", "moustache", "c", "idle"),
        ("adult", "unspecified", "medium", "none", "a", "observe"),
        ("elder", "feminine", "short", "none", "b", "rest"),
        ("elder", "masculine", "bald", "moustache", "d", "stroll"),
    )
)
"""Representative heads for the structural face probe.

Every age band, every presentation, every hair variant that touches the face,
both facial-hair options, all four face variants and all four poses -- chosen
so each row exercises a different combination rather than repeating one.
"""


def _face_probe_object(identity: dict, index: int):
    """Build one probe figure in the scene and return it."""
    materials = population.build_population_materials()
    name = f"LD_POP_FACEPROBE__{index:02d}"
    obj = population.build_figure_object(
        name,
        figure_kit.figure_mesh(identity),
        (float(index) * 3.0, 400.0, 0.0),
        bpy.data.collections[population.POPULATION_ROOT],
        [
            materials[identity["palette"]],
            materials[f"skin_{identity['complexion']}"],
            materials[f"hair_{identity['hair_tone']}"],
            materials["accent"],
        ],
        rotation_z=0.0,
        bevel=population.PROXY_BEVEL,
    )
    return obj


def _clear_face_probes() -> None:
    """Remove every probe figure and its mesh."""
    for obj in [o for o in bpy.data.objects if o.name.startswith("LD_POP_FACEPROBE__")]:
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in [m for m in bpy.data.meshes if m.name.startswith("LD_POP_FACEPROBE__")]:
        bpy.data.meshes.remove(mesh, do_unlink=True)


def test_every_probe_face_carries_two_eyes_a_nose_and_a_mouth(context) -> None:
    """The named face contract, asked of the kit that Blender is about to build."""
    _apply(context)
    for identity in FACE_PROBE_COMBINATIONS:
        placed = figure_kit.placed_head_features(identity)
        for required in ("left_eye", "right_eye", "nose", "mouth", "brow", "skull"):
            assert required in placed, f"{identity['age_presentation']} has no {required}"
        left = figure_kit.feature_bounds(placed["left_eye"])
        right = figure_kit.feature_bounds(placed["right_eye"])
        assert left["z"] == right["z"], "the eyes are not level in world space"


def test_the_built_mesh_really_contains_both_eyes(context) -> None:
    """Not "a feature was generated" -- vertices exist where the eye should be.

    Reads the assembled mesh Blender built and requires real geometry within a
    millimetre of each eye's computed corner. A feature that was generated and
    then swallowed by the skull would still be generated; it would not be here.
    """
    _apply(context)
    _sync()
    _clear_face_probes()
    try:
        for index, identity in enumerate(FACE_PROBE_COMBINATIONS):
            obj = _face_probe_object(identity, index)
            _sync()
            points = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
            origin = obj.location
            placed = figure_kit.placed_head_features(identity)
            for eye in ("left_eye", "right_eye"):
                # EVERY vertex of the eye must be present in the welded mesh,
                # to a tenth of a millimetre. The earlier version asked whether
                # any vertex lay near the eye's front-face CENTRE, which no
                # vertex ever does -- the centre of a quad is half a diagonal
                # away from its nearest corner, so the check could only pass by
                # carrying a tolerance three times larger than the eye itself.
                for corner in placed[eye]["vertices"]:
                    target = Vector(
                        (origin.x + corner[0], origin.y + corner[1], origin.z + corner[2])
                    )
                    nearest = min((point - target).length for point in points)
                    assert nearest < 1.0e-4, (
                        f"{identity['age_presentation']}/{identity['hair']} is missing part of "
                        f"its {eye} in the welded mesh (nearest vertex {round(nearest, 5)}m away)"
                    )
    finally:
        _clear_face_probes()


def test_both_eyes_and_the_nose_are_visible_from_the_front(context) -> None:
    """The defect that shipped, tested the way a camera would see it.

    A ray fired at each feature ALONG THE HEAD'S OWN FORWARD AXIS must strike
    that feature, not the skull behind it. The first candidate buried the eyes
    three millimetres inside the head, so this ray would have hit flat
    complexion and the figure rendered with a nose and no eyes.

    The axis matters: an axis-aligned ray probes a turned head at an angle and
    reports a miss that is the test's fault, not the geometry's.
    """
    _apply(context)
    _sync()
    _clear_face_probes()
    try:
        for index, identity in enumerate(FACE_PROBE_COMBINATIONS):
            obj = _face_probe_object(identity, index)
            _sync()
            frame, features = figure_kit.head_probe(identity)
            forward = Vector(figure_kit.head_forward(frame))
            origin = Vector(frame["origin"])
            for name in ("left_eye", "right_eye", "nose"):
                front = Vector(figure_kit.feature_front(frame, features[name]))
                hit, location, _normal, _face = obj.ray_cast(
                    front + forward * 0.30, -forward, distance=0.60
                )
                assert hit, f"nothing at all was hit aiming at the {name}"
                # Measured against the skull surface UNDER THIS FEATURE, not
                # against the head's single most forward point. On a faceted
                # skull the cheek falls away towards the temples, so an eye can
                # sit correctly proud of the surface it is mounted on while
                # still being behind the tip of the nose ridge -- comparing it
                # to one global front point was a flat-box assumption.
                offset = location - origin
                along = offset.dot(forward)
                lateral = offset.x * -forward.y + offset.y * forward.x
                level = (location.z - origin.z) / frame["height"]
                surface = figure_kit.head_surface_x(frame, level, lateral)
                proud = along - surface
                assert proud > 0.001, (
                    f"{identity['age_presentation']}/{identity['hair']} {name} is behind the "
                    f"skull surface beneath it by {round(-proud, 4)}m"
                )
                assert (location - front).length < 0.006, (
                    f"{name} was not the first surface the ray met "
                    f"({round((location - front).length, 4)}m off)"
                )
    finally:
        _clear_face_probes()


EYE_RAY_INSET = 0.85
"""How far a corner sample is pulled back towards the eye's own centre.

Rays are fired at the eye's centre AND at its four corners, because hair
that clips only an outer corner is invisible to a centre-only probe -- a
narrow tab over one corner measures 11.2mm of occlusion at the corners and
a clean -0.029mm at the centre. The corners are pulled fifteen per cent
inward so a ray lands solidly on the plate rather than grazing its rim and
striking the cheek beside it, which would be the test's fault rather than
the geometry's.
"""

EYE_OCCLUSION_TOLERANCE = 0.001
"""How far in front of an eye another surface may sit, in metres.

One millimetre, against a measured worst of 0.029mm across the whole probe
vocabulary -- so this is thirty-odd times the float and sampling noise, and
far under the millimetres any real strand of hair would stand proud by.
"""


def _eye_ray_samples(primitive) -> list:
    """The points on one eye's outward face that a ray is aimed at.

    The plate records WHICH of its vertices form its front face, so the
    samples come from the surface a viewer actually sees rather than from a
    bounding box around it. A conforming eye is strongly slanted -- its front
    face sweeps almost 30mm through x across 22mm of y as it follows the
    cheek -- which is precisely why a box around it describes something the
    figure does not contain.
    """
    indices = primitive.get("front")
    corners = (
        [primitive["vertices"][index] for index in indices]
        if indices
        else list(primitive["vertices"])
    )
    centre = Vector(
        (
            sum(corner[0] for corner in corners) / len(corners),
            sum(corner[1] for corner in corners) / len(corners),
            sum(corner[2] for corner in corners) / len(corners),
        )
    )
    return [centre] + [centre + (Vector(corner) - centre) * EYE_RAY_INSET for corner in corners]


def test_no_hair_variant_hides_an_eye_on_a_built_figure(context) -> None:
    """Hair may frame a face; it may never be the first thing a ray meets.

    A RAY, because that is what the sentence above says and what a camera
    does. This test used to say it and then measure something else: it
    compared the axis-aligned bounding box of each hair piece against the box
    of each eye, and an AABB is not the shape of either.

    The box version failed the final gate on teen/feminine/long, and the
    geometry was innocent. The offender was ``hair_crown_nape``, the
    back-of-head band: its box necessarily spans the full head width, 0.248m
    in y, so it reaches forward in the box while the mesh sits entirely
    BEHIND the skull. The giveaway was the asymmetry -- it overlapped the
    left eye by 0.00324m and cleared the right by 0.01953m, and a real
    fringe does not fall on one eye by three millimetres. ``hair_crown``,
    the volume that art round actually raised, cleared both eyes outright
    with a negative z overlap of -0.0067. Meanwhile the genuine raycast in
    :func:`test_both_eyes_and_the_nose_are_visible_from_the_front` passed on
    that same identity, against the welded mesh with hair bound.

    This exact false-positive class had already been retired once in this
    file -- a sibling carries a comment about the flat-box assumption it
    replaced -- and this test was simply never brought along.

    So the guard is kept and the METHOD is corrected. Rays are cast along the
    head's own forward axis at each eye's centre and corners; nothing may sit
    more than :data:`EYE_OCCLUSION_TOLERANCE` in front of the eye's own
    outward face. That is strictly stronger than the box it replaces, which
    could not see a corner clipped at all.

    Do not "simplify" this back to comparing bounds. It will start failing on
    hair that is nowhere near an eye.
    """
    _apply(context)
    _sync()
    _clear_face_probes()
    try:
        for index, identity in enumerate(FACE_PROBE_COMBINATIONS):
            obj = _face_probe_object(identity, index)
            _sync()
            frame, _features = figure_kit.head_probe(identity)
            forward = Vector(figure_kit.head_forward(frame))
            placed = figure_kit.placed_head_features(identity)
            for eye in ("left_eye", "right_eye"):
                for sample in _eye_ray_samples(placed[eye]):
                    hit, location, _normal, _face = obj.ray_cast(
                        sample + forward * 0.30, -forward, distance=0.60
                    )
                    assert hit, (
                        f"{identity['age_presentation']}/{identity['hair']} hit nothing at "
                        f"all aiming at the {eye}"
                    )
                    proud = (location - sample).dot(forward)
                    assert proud <= EYE_OCCLUSION_TOLERANCE, (
                        f"{identity['age_presentation']}/{identity['hair']} hair stands "
                        f"{round(proud * 1000, 2)}mm in front of the {eye}"
                    )
    finally:
        _clear_face_probes()


def test_the_face_survives_the_body_heading(context) -> None:
    """A rotated body must carry its face round with it.

    The nose's bearing from the head centre, measured in WORLD space on the
    built object, must equal the body heading plus the head turn.
    """
    state = _apply(context)
    _sync()
    for proxy in state["plan"]["proxies"][:24]:
        obj = bpy.data.objects[f"{population.PROXY_PREFIX}{proxy['slot']}"]
        size = figure_kit.figure_dimensions(proxy)
        turn = figure_kit._pose_frame(proxy["pose"], size)["head_turn"]
        frame, features = figure_kit.head_probe(proxy)
        # The head's own origin, not the midpoint of the skull's axis-aligned
        # bounds. The skull is deliberately fuller at the back than at the
        # face, so once it turns those bounds are no longer centred on it and
        # a bearing measured from them drifts by a degree or so.
        head_centre = Vector(frame["origin"])
        nose_centre = Vector(figure_kit.feature_front(frame, features["nose"]))
        world_head = obj.matrix_world @ head_centre
        world_nose = obj.matrix_world @ nose_centre
        bearing = math.atan2(world_nose.y - world_head.y, world_nose.x - world_head.x)
        expected = float(proxy["heading"]) + turn
        difference = math.atan2(math.sin(bearing - expected), math.cos(bearing - expected))
        assert abs(difference) < 1.0e-4, (
            f"{proxy['slot']} faces {bearing} but its heading and head turn say {expected}"
        )


def test_rebuilding_reproduces_identical_facial_placement(context) -> None:
    """Faces are as idempotent as the bodies that carry them."""
    state = _apply(context)
    _sync()
    before = {
        proxy["slot"]: figure_kit.placed_head_features(proxy) for proxy in state["plan"]["proxies"]
    }
    population.apply_population_presence(state["plan"], state["presence_spec"])
    _sync()
    after = {
        proxy["slot"]: figure_kit.placed_head_features(proxy) for proxy in state["plan"]["proxies"]
    }
    assert before == after
    assert population.population_summary()["duplicate_named_objects"] == 0


def test_the_motion_layer_still_works_over_a_populated_city(context) -> None:
    """Phase 17 is not damaged: a real leg still animates a populated world.

    ``build_motion_scene`` rebuilds the city from the locked builders, so the
    population layer must be re-applied afterwards -- and the point of the
    test is that it can be, and that the motion it finds is the motion Phase
    17 always found.
    """
    state = _apply(context)
    report = motion.build_motion_scene(
        context["spec_path"],
        context["production_path"],
        context["before_path"],
        context["mid_path"],
        context["motion_path"],
        style=STYLE,
    )
    assert report["metrics"]["animated_objects"] > 0, "the motion layer animated nothing"
    assert report["metrics"]["keyframes"] > 0
    population.apply_population_presence(state["plan"], state["presence_spec"])
    assert len(population.population_objects()) == state["plan"]["summary"]["active_proxies"]
    for obj in population.population_objects():
        assert obj.animation_data is None or obj.animation_data.action is None, (
            f"{obj.name} carries animation; Phase 18 population is static presence"
        )
    context.pop("presence", None)


# ---------------------------------------------------------------------------
# The body is not a box, proved on the mesh Blender assembled
# ---------------------------------------------------------------------------

BODY_PROBE_COMBINATIONS = tuple(
    {
        "age_presentation": age,
        "presentation": presentation,
        "stature": stature,
        "build": build,
        "hair": "short",
        "facial_hair": "none",
        "face": "a",
        "clothing": clothing,
        "palette": "slate",
        "complexion": "c1",
        "hair_tone": "h1",
        "pose": pose,
    }
    for age, presentation, stature, build, clothing, pose in (
        ("child", "unspecified", "short", "average", "shirt", "idle"),
        ("teen", "masculine", "tall", "slim", "short_sleeve", "stroll"),
        ("adult", "feminine", "average", "athletic", "shirt", "observe"),
        ("adult", "masculine", "tall", "broad", "jacket", "rest"),
        ("elder", "feminine", "short", "slim", "coat", "idle"),
    )
)
"""Representative bodies for the structural anatomy probe.

Every age band, both extremes of build and stature, and all four poses. These
are the figures the "is it still a block character?" regressions measure, and
they are measured on the ASSEMBLED Blender mesh rather than on the pure kit,
because the pure suite already proves the kit and this proves the weld.
"""


def _body_probe_object(identity: dict, index: int):
    """Build one anatomy probe figure in the scene and return it."""
    materials = population.build_population_materials()
    return population.build_figure_object(
        f"LD_POP_BODYPROBE__{index:02d}",
        figure_kit.figure_mesh(identity),
        (float(index) * 3.0, 460.0, 0.0),
        bpy.data.collections[population.POPULATION_ROOT],
        [
            materials[identity["palette"]],
            materials[f"skin_{identity['complexion']}"],
            materials[f"hair_{identity['hair_tone']}"],
            materials["accent"],
        ],
        rotation_z=0.0,
        bevel=population.PROXY_BEVEL,
    )


def _clear_body_probes() -> None:
    """Remove every anatomy probe figure and its mesh."""
    for obj in [o for o in bpy.data.objects if o.name.startswith("LD_POP_BODYPROBE__")]:
        bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in [m for m in bpy.data.meshes if m.name.startswith("LD_POP_BODYPROBE__")]:
        bpy.data.meshes.remove(mesh, do_unlink=True)


def _built_parts(obj, identity: dict) -> dict:
    """Each named primitive's vertices AS BUILT, sliced out of the welded mesh.

    ``figure_mesh`` concatenates the primitives ``figure_geometry`` returned,
    in order, so each one's offset is the running vertex total before it. That
    makes it possible to ask a question about the torso alone even though
    Blender holds a single mesh -- which matters, because a horizontal slice of
    a whole body at chest height cuts through both arms too, and would report
    the arm span as if it were the torso.

    The coordinates come from ``obj.data.vertices``, so this measures what
    Blender welded rather than what the kit intended.
    """
    built = {}
    offset = 0
    for primitive in figure_kit.figure_geometry(identity):
        count = len(primitive["vertices"])
        built[primitive["name"]] = [
            obj.data.vertices[index].co for index in range(offset, offset + count)
        ]
        offset += count
    assert offset == len(obj.data.vertices), "the welded mesh does not match the kit's primitives"
    return built


def _span(points, axis: str) -> float:
    """How far one set of built vertices reaches along an axis."""
    values = [getattr(point, axis) for point in points]
    return max(values) - min(values)


def _width_between(points, low: float, high: float) -> float:
    """The lateral width of one primitive between two heights."""
    inside = [point for point in points if low <= point.z <= high]
    if not inside:
        return 0.0
    return max(point.y for point in inside) - min(point.y for point in inside)


def test_no_built_head_is_a_cuboid(context) -> None:
    """The blocker, tested on the assembled mesh rather than on the kit.

    A cuboid skull has six faces whose normals are all axis-aligned. The head
    Blender welds has to be demonstrably rounder than that: many distinct face
    directions, most of them off-axis, measured on the polygons in the mesh
    datablock above the neck.
    """
    _apply(context)
    _sync()
    _clear_body_probes()
    try:
        for index, identity in enumerate(BODY_PROBE_COMBINATIONS):
            obj = _body_probe_object(identity, index)
            _sync()
            size = figure_kit.figure_dimensions(identity)
            neck_top = size["neck_top"]
            mesh = obj.data
            mesh.calc_loop_triangles()
            head_faces = [
                polygon
                for polygon in mesh.polygons
                if min(mesh.vertices[i].co.z for i in polygon.vertices) >= neck_top - 1.0e-6
            ]
            assert len(head_faces) > 6, (
                f"{identity['age_presentation']} head has {len(head_faces)} faces"
            )
            directions = {
                tuple(round(component, 3) for component in polygon.normal) for polygon in head_faces
            }
            assert len(directions) > 6, f"only {len(directions)} distinct head normals"
            off_axis = [
                polygon
                for polygon in head_faces
                if not any(abs(abs(component) - 1.0) < 1.0e-3 for component in polygon.normal)
            ]
            assert len(off_axis) >= len(head_faces) * 0.4, (
                f"{identity['age_presentation']} head is mostly axis-aligned faces"
            )
    finally:
        _clear_body_probes()


def test_every_built_body_tapers_at_the_waist(context) -> None:
    """The torso is one hull with a real waist, measured on the built mesh.

    Measured on the TORSO's own vertices. A slice through the whole body at
    chest height also cuts both arms, and would report a waist wider than a hip
    for no better reason than that the arms hang beside it.

    The v2 hull authors its waist ring at 0.38 of the torso span and its chest
    ring at 0.72, so each sampling band STRADDLES its ring rather than ending
    on it: a band edge exactly on a ring's height asks a float32-stored vertex
    to round the right way, and this suite must not own a coin toss.
    """
    _apply(context)
    _sync()
    _clear_body_probes()
    try:
        for index, identity in enumerate(BODY_PROBE_COMBINATIONS):
            obj = _body_probe_object(identity, index)
            _sync()
            size = figure_kit.figure_dimensions(identity)
            torso = _built_parts(obj, identity)["torso"]
            span = size["torso_top"] - size["leg_top"]
            hip = _width_between(torso, size["leg_top"] - span * 0.12, size["leg_top"] + 1.0e-6)
            waist = _width_between(
                torso, size["leg_top"] + span * 0.34, size["leg_top"] + span * 0.42
            )
            chest = _width_between(
                torso, size["leg_top"] + span * 0.68, size["leg_top"] + span * 0.76
            )
            assert 0.0 < waist < hip, (
                f"{identity['age_presentation']}/{identity['build']} waist {waist} vs hip {hip}"
            )
            assert waist < chest, (
                f"{identity['age_presentation']}/{identity['build']} waist {waist} vs chest {chest}"
            )
    finally:
        _clear_body_probes()


def test_every_built_body_has_elbows_knees_and_feet(context) -> None:
    """Segmented limbs and real feet, read back off the welded mesh.

    Each limb's own vertices are sliced out and measured at every height it
    was built at, against the shapes ``figure_kit.CHAIN_SPEC`` declares.

    A leg is FIVE cross-sections -- hip, thigh, knee, calf, ankle -- and its
    taper is asserted at the JOINTS only, because the calf below the knee is
    deliberately fuller than the knee's own pinch and a monotonic check would
    refuse the designed leg.

    An arm is a three-ring upper arm -- socket, deltoid, elbow -- then a
    two-ring forearm and a FOUR-ring hand of wrist, knuckle, fingers and tip.
    The socket is the narrow band that tucks into the shoulder; the deltoid
    is the widest, carrying the silhouette out to full shoulder width. The
    hand is checked here only for existence: its own shape is measured in
    the pure suite, which can read the rings without a weld in the way.

    A kneecap ring and an arm collar briefly sat in both chains, purely to
    hold hinge dihedrals under Blender's bevel angle limit. The figure bevel
    no longer consults angles, so both were removed -- see the budget
    docstring above for why that removal depends on the bevel method and must
    not be undone without it.

    A rectangular column measures the same everywhere, which is exactly what
    this rejects; a foot is proved by reaching forward of the ankle it hangs
    from.
    """
    _apply(context)
    _sync()
    _clear_body_probes()
    try:
        for index, identity in enumerate(BODY_PROBE_COMBINATIONS):
            obj = _body_probe_object(identity, index)
            _sync()
            size = figure_kit.figure_dimensions(identity)
            built = _built_parts(obj, identity)
            for side in ("left", "right"):
                leg = built[f"{side}_leg"]
                heights = sorted({round(point.z, 6) for point in leg})
                assert len(heights) == 5, f"{side} leg has {len(heights)} cross-sections"
                ankle_w, calf_w, knee_w, thigh_w, hip_w = (
                    _width_between(leg, height - 1.0e-4, height + 1.0e-4) for height in heights
                )
                assert hip_w > knee_w * 1.15, f"{side} thigh is not thicker than its knee"
                assert knee_w > ankle_w * 1.15, f"{side} shin does not narrow to an ankle"
                assert calf_w > knee_w, f"{side} calf does not swell below its knee"

                upper = built[f"{side}_upper_arm"]
                forearm = built[f"{side}_forearm"]
                assert f"{side}_hand" in built, f"{side} arm carries no hand"
                upper_heights = sorted({round(point.z, 6) for point in upper})
                forearm_heights = sorted({round(point.z, 6) for point in forearm})
                # Three rings up here, lowest first: elbow, deltoid, socket.
                # The taper is read from the deltoid down, and the SOCKET is
                # the narrow band that tucks up into the shoulder.
                assert len(upper_heights) == 3, f"{side} upper arm is not a three-ring member"
                assert len(forearm_heights) == 2, f"{side} forearm is not a two-ring member"
                elbow_w, deltoid_w, socket_w = (
                    _width_between(upper, height - 1.0e-4, height + 1.0e-4)
                    for height in upper_heights
                )
                wrist_w = _width_between(
                    forearm, forearm_heights[0] - 1.0e-4, forearm_heights[0] + 1.0e-4
                )
                assert socket_w < deltoid_w, f"{side} socket is not tucked inside its deltoid"
                assert deltoid_w > elbow_w * 1.10, f"{side} upper arm does not taper"
                assert elbow_w > wrist_w * 1.10, f"{side} forearm does not taper"
                # The LEG's widest against the ARM's widest, which is the
                # deltoid: it is the junction that reaches full shoulder
                # width. Comparing against the socket instead would compare a
                # hip to the narrowest ring in the arm and pass on anything.
                assert hip_w > deltoid_w, f"{side} leg must be a thicker limb than its arm"

                foot = built[f"{side}_foot"]
                ankle_ring = [point for point in leg if round(point.z, 6) == heights[0]]
                ankle_x = sum(point.x for point in ankle_ring) / len(ankle_ring)
                forward = max(point.x for point in foot) - ankle_x
                behind = ankle_x - min(point.x for point in foot)
                assert forward > behind * 1.4, f"{side} foot does not project forward"
                assert _span(foot, "x") > size["foot_length"] * 0.8, f"{side} foot has no length"
                assert abs(min(point.z for point in foot)) < 1.0e-6, f"{side} foot is off the floor"
            assert min(vertex.co.z for vertex in obj.data.vertices) >= -1.0e-6, (
                "the body sinks below its feet"
            )
    finally:
        _clear_body_probes()


def test_shoulders_emerge_from_the_torso_rather_than_sitting_on_it(context) -> None:
    """No beam laid across the top: the arms carry the shoulder silhouette.

    Compared AT CHEST HEIGHT. The torso's widest point overall may be a hip, or
    the flared hem of a coat down at ankle level, so measuring the whole
    primitive against the whole arm answers a question nobody asked.
    """
    _apply(context)
    _sync()
    _clear_body_probes()
    try:
        for index, identity in enumerate(BODY_PROBE_COMBINATIONS):
            obj = _body_probe_object(identity, index)
            _sync()
            size = figure_kit.figure_dimensions(identity)
            built = _built_parts(obj, identity)
            span = size["torso_top"] - size["leg_top"]
            chest = (
                _width_between(built["torso"], size["leg_top"] + span * 0.66, size["torso_top"])
                / 2.0
            )
            arm = built["left_upper_arm"]
            assert max(point.y for point in arm) > chest, (
                "the arm does not reach past the torso at chest height"
            )
            assert min(point.y for point in arm) < chest, "the arm is detached from the torso"
            assert chest * 2.0 < size["shoulder_width"] * 0.85, (
                "the torso hull is as wide as the whole shoulder span"
            )
    finally:
        _clear_body_probes()


def test_the_population_layer_reports_its_mesh_reuse_honestly(context) -> None:
    """The manifest's mesh metrics have to match the datablocks in the file.

    An earlier manifest reported ``shared_meshes: 80`` for eighty proxies,
    which reads as sharing and is really a count of distinct meshes. The
    replacement names are checked against Blender itself here, including the
    case the old label hid: zero reuse.
    """
    state = _apply(context)
    _sync()
    summary = population.population_summary()
    objects = population.population_objects()
    distinct = {obj.data.name for obj in objects}
    assert summary["proxy_objects"] == len(objects)
    assert summary["distinct_body_meshes"] == len(distinct)
    assert summary["reused_body_mesh_instances"] == len(objects) - len(distinct)
    assert summary["mesh_reuse_ratio"] == round((len(objects) - len(distinct)) / len(objects), 4)
    expected = sum(figure_kit.figure_triangles(proxy) for proxy in state["plan"]["proxies"])
    assert summary["population_triangles"] == expected, (
        f"the file holds {summary['population_triangles']} triangles, the kit says {expected}"
    )


def _with_populations(export: dict, populations: dict[str, int]) -> dict:
    """A copy of one render export with some district populations replaced.

    A clearly-labelled FIXTURE, never rendered and never packaged: the real
    three-episode story holds population constant, so the only way to prove
    the growth contract is to state the counterfactual explicitly.
    """
    districts = []
    for district in export["world"]["districts"]:
        entry = dict(district)
        if entry["id"] in populations:
            entry["population"] = populations[entry["id"]]
        districts.append(entry)
    world = dict(export["world"])
    world["districts"] = districts
    changed = dict(export)
    changed["world"] = world
    return changed
