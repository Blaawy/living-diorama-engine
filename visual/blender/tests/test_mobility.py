"""Structural tests for the Phase 19 daily-life mobility layer.

Runs INSIDE Blender, against the real scene, because the claims that matter
here cannot be checked anywhere else: that a walking body's limbs really move,
that a wheel really turns, that a route really lands on carriageway, that the
loop really closes, and that clearing the layer really gives Phase 18 back.

Every measurement is taken from the EVALUATED scene. A follow-path constraint
is not in an object's own transform and a shape key is not in its mesh data, so
a suite that read ``object.location`` or ``mesh.vertices`` would pass vacuously
while nothing moved at all.
"""

import math

import apply_mobility as mobility
import apply_population_presence as population
import bpy
import build_production_world
import mobility_plan as mp
import pedestrian_topology as topo
import population_presence_plan as pres
import production_spec
import road_graph
import scene_spec
import urban_fabric
import vehicle_kit
import vehicle_lane_network as vln
from mathutils import Vector
from mobility_spec import load_daily_life_mobility_spec, resolve_mobility_timeline
from motion_time_spec import load_motion_time_spec
from population_presence_spec import load_population_presence_spec
from produce_mobility_proof import build_mobility_cameras

_STATE: dict = {}


def _prepare(context: dict) -> dict:
    """Build the world, the population and the mobility layer exactly once.

    Cached because every test below needs the same scene and rebuilding a
    populated, trafficked city per test would make the suite cost minutes
    rather than seconds.
    """
    if _STATE:
        return _STATE
    master = scene_spec.load_master_scene_spec(context["spec_path"])
    prod = production_spec.load_production_world_spec(context["production_path"])
    presence_spec = load_population_presence_spec(context["presence_path"])
    spec = load_daily_life_mobility_spec(context["mobility_path"])
    timeline = resolve_mobility_timeline(
        spec, load_motion_time_spec(context["motion_path"])["timeline"]
    )
    graph = road_graph.build_road_graph(master, prod)
    fabric = urban_fabric.plan_urban_fabric(master, prod, graph)
    topology = topo.plan_pedestrian_topology(master, prod, graph, fabric, presence_spec)
    export = scene_spec.load_render_export(context["before_path"])
    presence = pres.plan_population_presence(export, master, presence_spec, topology)
    plan = mp.plan_daily_life_mobility(
        presence, presence_spec, spec, timeline, master, prod, graph, fabric
    )

    build_production_world.add_production_world(
        context["spec_path"], context["production_path"], style="dna"
    )
    population.apply_population_presence(presence, presence_spec)
    before_transforms = population.proxy_positions()
    before_meshes = {
        obj.name: (len(obj.data.vertices), len(obj.data.polygons))
        for obj in population.population_objects()
    }
    metrics = mobility.apply_mobility(plan, spec)
    _STATE.update(
        {
            "master": master,
            "production": prod,
            "graph": graph,
            "fabric": fabric,
            "spec": spec,
            "timeline": timeline,
            "presence": presence,
            "plan": plan,
            "metrics": metrics,
            "phase18_transforms": before_transforms,
            "phase18_meshes": before_meshes,
        }
    )
    return _STATE


def _at(frame: int) -> dict:
    """Every mover's evaluated world transform on one frame."""
    bpy.context.scene.frame_set(frame)
    bpy.context.view_layer.update()
    return mobility.mobility_transforms()


# ---------------------------------------------------------------------------
# The layer exists, and is exactly what the plan asked for
# ---------------------------------------------------------------------------


def test_the_mobility_layer_builds_the_planned_traffic(context: dict) -> None:
    """Fourteen vehicles, fifty-six wheels, and the plan's own digest."""
    state = _prepare(context)
    summary = mobility.mobility_summary()
    plan = state["plan"]
    assert summary["vehicle_bodies"] == plan["vehicles"]["count"]
    assert summary["vehicle_wheels"] == 4 * plan["vehicles"]["count"]
    assert state["metrics"]["plan_hash"] == mp.mobility_plan_hash(plan)


def test_every_vehicle_is_named_for_its_slot(context: dict) -> None:
    """Semantic names, so a reviewer can find a vehicle the plan describes."""
    _prepare(context)
    for vehicle in _STATE["plan"]["vehicles"]["vehicles"]:
        assert bpy.data.objects.get(f"LD_VEH__{vehicle['slot']}") is not None
        for corner in ("fl", "fr", "rl", "rr"):
            assert bpy.data.objects.get(f"LD_VEH__{vehicle['slot']}__wheel_{corner}") is not None


def test_the_layer_grows_no_duplicate_datablocks(context: dict) -> None:
    """A ``.001`` anywhere means a rebuild grew the scene instead of replacing it."""
    _prepare(context)
    assert mobility.mobility_summary()["duplicate_named_objects"] == 0


def test_nothing_is_linked_outside_the_mobility_collection(context: dict) -> None:
    """The layer is isolated, so removing it cannot take anything else with it."""
    _prepare(context)
    assert mobility.mobility_summary()["linked_elsewhere"] == 0


def test_the_vehicle_layer_fits_its_triangle_budget(context: dict) -> None:
    """Performance is a contract, measured off the built meshes."""
    state = _prepare(context)
    budget = state["spec"]["vehicles"]["budget"]["layer_triangles"]
    assert mobility.mobility_summary()["vehicle_triangles"] <= budget


def test_the_vehicle_kit_builds_every_declared_archetype(context: dict) -> None:
    """Every archetype the spec enables must be a body the kit can weld."""
    state = _prepare(context)
    for name in state["spec"]["vehicles"]["enabled_archetypes"]:
        mesh = vehicle_kit.vehicle_mesh(name)
        assert mesh["vertices"] and mesh["faces"]


def test_no_phase17_action_touches_a_phase19_object(context: dict) -> None:
    """Two animation systems, two namespaces, no overlap."""
    _prepare(context)
    for obj in bpy.data.objects:
        animation = getattr(obj, "animation_data", None)
        if animation is None or animation.action is None:
            continue
        if obj.name.startswith(("LD_VEH__", "LD_MOBILITY_PATH__")):
            assert animation.action.name.startswith("LD_MOBILITY__"), obj.name
        if animation.action.name.startswith("LD_MOTION__"):
            assert not obj.name.startswith(("LD_VEH__", "LD_MOBILITY_PATH__")), obj.name


# ---------------------------------------------------------------------------
# The loop contract
# ---------------------------------------------------------------------------


def test_every_mover_returns_to_its_own_start(context: dict) -> None:
    """Frame one and the last frame are the same state, measured, not asserted."""
    state = _prepare(context)
    timeline = state["timeline"]
    first = _at(timeline["start_frame"])
    last = _at(timeline["end_frame"])
    assert set(first) == set(last)
    for name in sorted(first):
        for index, axis in enumerate("xyz"):
            assert abs(first[name][index] - last[name][index]) < 1.0e-4, (name, axis)
        # Heading is the one channel that can come home displaced by whole
        # turns: a mover that yaws through its circuit stores start plus 2*pi
        # as the SAME physical orientation. The remainder folds the difference
        # back to the nearest full turn, so equivalence at any multiple of
        # 2*pi passes and the tolerance still means what it means on the axes.
        spin = first[name][3] - last[name][3]
        assert abs(math.remainder(spin, 2.0 * math.pi)) < 1.0e-4, (name, "h")


def test_every_walker_starts_on_its_phase18_anchor(context: dict) -> None:
    """A walk leaves the proxy's own anchor and comes back to it."""
    state = _prepare(context)
    tolerance = state["spec"]["pedestrians"]["route"]["anchor_tolerance"]
    placed = _at(state["timeline"]["start_frame"])
    for walker in state["plan"]["pedestrians"]["walkers"]:
        anchor = walker["anchor"]
        here = placed[f"LD_POP__{walker['slot']}"]
        assert math.hypot(here[0] - anchor["x"], here[1] - anchor["y"]) <= tolerance + 1.0e-6
        assert abs(here[2] - anchor["z"]) < 1.0e-3


def test_a_stationary_proxy_never_moves(context: dict) -> None:
    """Fifty-six people stand exactly where Phase 18 put them, all cycle long."""
    state = _prepare(context)
    timeline = state["timeline"]
    stationary = set(state["plan"]["pedestrians"]["stationary_slots"])
    frames = [
        timeline["start_frame"],
        (timeline["start_frame"] + timeline["end_frame"]) // 2,
        timeline["end_frame"],
    ]
    samples = [_at(frame) for frame in frames]
    for slot in sorted(stationary):
        name = f"LD_POP__{slot}"
        for later in samples[1:]:
            assert samples[0][name] == later[name], slot


def test_a_walker_travels_its_whole_route(context: dict) -> None:
    """A walker that closed its loop by never leaving would also close it."""
    state = _prepare(context)
    timeline = state["timeline"]
    frames = range(timeline["start_frame"], timeline["end_frame"] + 1, 8)
    tracks: dict[str, list] = {}
    for frame in frames:
        for name, transform in _at(frame).items():
            if name.startswith("LD_POP__"):
                tracks.setdefault(name, []).append(transform[:2])
    for walker in state["plan"]["pedestrians"]["walkers"]:
        points = tracks[f"LD_POP__{walker['slot']}"]
        travelled = sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))
        assert travelled > walker["route_length"] * 0.8, walker["slot"]


def test_a_vehicle_travels_its_whole_circuit(context: dict) -> None:
    """Same claim for traffic: distance covered, not merely position restored."""
    state = _prepare(context)
    timeline = state["timeline"]
    tracks: dict[str, list] = {}
    for frame in range(timeline["start_frame"], timeline["end_frame"] + 1, 4):
        for name, transform in _at(frame).items():
            if name.startswith("LD_VEH__") and "__wheel_" not in name:
                tracks.setdefault(name, []).append(transform[:2])
    for vehicle in state["plan"]["vehicles"]["vehicles"]:
        points = tracks[f"LD_VEH__{vehicle['slot']}"]
        travelled = sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))
        assert travelled > vehicle["route_length"] * 0.9, vehicle["slot"]


# ---------------------------------------------------------------------------
# Walking really is walking
# ---------------------------------------------------------------------------


def _evaluated_vertices(obj) -> list:
    """One object's vertex positions AFTER modifiers and shape keys."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    points = [tuple(vertex.co) for vertex in mesh.vertices]
    evaluated.to_mesh_clear()
    return points


def test_a_walkers_limbs_actually_move(context: dict) -> None:
    """The sliding-mannequin test, and it is not satisfiable by translation.

    Vertices are read in the object's LOCAL frame after evaluation, so the
    route's translation contributes nothing at all. Only the gait can make these
    numbers move, and the declared floor is what stops a token wobble passing.
    """
    state = _prepare(context)
    timeline = state["timeline"]
    floor = state["spec"]["pedestrians"]["gait"]["min_limb_travel"]
    for walker in state["plan"]["pedestrians"]["walkers"][:6]:
        obj = bpy.data.objects[f"LD_POP__{walker['slot']}"]
        span = max(2, int(timeline["frame_span"] / walker["gait"]["cycles"]))
        samples = []
        for frame in range(timeline["start_frame"], timeline["start_frame"] + span + 1, 2):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            samples.append(_evaluated_vertices(obj))
        travel = max(
            max(math.dist(samples[0][index], later[index]) for later in samples[1:])
            for index in range(len(samples[0]))
        )
        assert travel >= floor, (walker["slot"], travel, floor)


def test_the_gait_is_the_pure_kits_own_geometry(context: dict) -> None:
    """The render performs the deformation a reviewer can measure without Blender."""
    state = _prepare(context)
    import pedestrian_mobility as walking

    for walker in state["plan"]["pedestrians"]["walkers"][:4]:
        obj = bpy.data.objects[f"LD_POP__{walker['slot']}"]
        blocks = obj.data.shape_keys.key_blocks
        shapes = walking.gait_shapes(walker, walker["gait"], state["spec"])
        assert len(blocks) == len(shapes) + 1
        for index, shape in enumerate(shapes):
            block = blocks[f"LD_GAIT__p{index:02d}"]
            for built, wanted in zip(block.data, shape, strict=True):
                assert (Vector(wanted) - built.co).length < 1.0e-5


def test_opposite_arm_and_leg_swing(context: dict) -> None:
    """The single cue that separates walking from marching, checked as a sign."""
    state = _prepare(context)
    import pedestrian_mobility as walking

    for walker in state["plan"]["pedestrians"]["walkers"][:6]:
        angles = walking.gait_angles(0.125, walker["gait"])
        assert angles["left_hip"] * angles["right_hip"] < 0.0, walker["slot"]
        assert angles["left_hip"] * angles["left_shoulder"] < 0.0, walker["slot"]
        assert angles["right_hip"] * angles["right_shoulder"] < 0.0, walker["slot"]


def test_a_walking_body_is_never_buried_or_hovering(context: dict) -> None:
    """Ray-cast the real scene: a gait that sank a foot would pass any z test."""
    state = _prepare(context)
    timeline = state["timeline"]
    frames = (
        timeline["start_frame"],
        timeline["start_frame"] + timeline["frame_span"] // 3,
        timeline["start_frame"] + 2 * timeline["frame_span"] // 3,
    )
    for frame in frames:
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for walker in state["plan"]["pedestrians"]["walkers"][:8]:
            obj = bpy.data.objects[f"LD_POP__{walker['slot']}"]
            matrix = obj.matrix_world
            lowest = min((matrix @ Vector(point)).z for point in _evaluated_vertices(obj))
            assert lowest > walker["anchor"]["z"] - 0.16, (walker["slot"], frame, lowest)
            assert lowest < walker["anchor"]["z"] + 0.16, (walker["slot"], frame, lowest)


def test_a_walker_still_represents_exactly_one_phase18_slot(context: dict) -> None:
    """No walker is a duplicate body: the layer moves people, it never adds them."""
    state = _prepare(context)
    proxies = [obj for obj in bpy.data.objects if obj.name.startswith("LD_POP__")]
    assert len(proxies) == state["plan"]["pedestrians"]["total_proxies"]
    assert len({obj.name for obj in proxies}) == len(proxies)


# ---------------------------------------------------------------------------
# Driving really is driving
# ---------------------------------------------------------------------------


def test_a_wheel_turns_at_the_speed_the_car_travels(context: dict) -> None:
    """Rotation is derived from distance and radius, so it is checked as both."""
    state = _prepare(context)
    timeline = state["timeline"]
    for vehicle in state["plan"]["vehicles"]["vehicles"]:
        wheel = bpy.data.objects[f"LD_VEH__{vehicle['slot']}__wheel_fl"]
        bpy.context.scene.frame_set(timeline["start_frame"])
        start = wheel.rotation_euler[1]
        bpy.context.scene.frame_set(timeline["end_frame"])
        end = wheel.rotation_euler[1]
        turns = (end - start) / (2.0 * math.pi)
        # Blender stores keyframe values as float32, so a forty-one revolution
        # wheel carries about two parts in ten million of storage error. The
        # tolerance is sized for that rather than for the arithmetic, which is
        # exact: tightening it further would only be testing IEEE 754.
        assert abs(turns - vehicle["wheel_turns"]) < 1.0e-4, (vehicle["slot"], turns)
        rolled = 2.0 * math.pi * vehicle["rolling_radius"] * turns
        travelled = vehicle["route_length"] * vehicle["cycles"]
        assert abs(rolled - travelled) < 1.0e-2, (vehicle["slot"], rolled, travelled)


def test_a_wheel_turns_forward(context: dict) -> None:
    """A wheel spinning backwards would be a car being dragged."""
    state = _prepare(context)
    timeline = state["timeline"]
    for vehicle in state["plan"]["vehicles"]["vehicles"][:6]:
        wheel = bpy.data.objects[f"LD_VEH__{vehicle['slot']}__wheel_fl"]
        bpy.context.scene.frame_set(timeline["start_frame"])
        start = wheel.rotation_euler[1]
        bpy.context.scene.frame_set(timeline["start_frame"] + 12)
        assert wheel.rotation_euler[1] > start, vehicle["slot"]


def test_a_wheel_state_closes_on_whole_revolutions(context: dict) -> None:
    """The loop contract for wheels: the same state modulo full revolutions."""
    state = _prepare(context)
    for vehicle in state["plan"]["vehicles"]["vehicles"]:
        assert float(vehicle["wheel_turns"]).is_integer(), vehicle["slot"]


def test_every_vehicle_stays_on_the_carriageway(context: dict) -> None:
    """Sampled from the EVALUATED transforms, against the road graph's own widths."""
    state = _prepare(context)
    timeline = state["timeline"]
    envelope = vln.drivable_envelope(state["graph"])
    for frame in range(timeline["start_frame"], timeline["end_frame"] + 1, 6):
        for name, transform in _at(frame).items():
            if not name.startswith("LD_VEH__") or "__wheel_" in name:
                continue
            assert vln.on_carriageway(transform[0], transform[1], envelope), (name, frame)


def test_a_vehicle_faces_the_way_it_is_going(context: dict) -> None:
    """A car crabbing down its own lane is the failure a coarse path produces."""
    state = _prepare(context)
    timeline = state["timeline"]
    for vehicle in state["plan"]["vehicles"]["vehicles"][:6]:
        name = f"LD_VEH__{vehicle['slot']}"
        worst = 0.0
        for frame in range(timeline["start_frame"] + 4, timeline["end_frame"] - 4, 12):
            here = _at(frame)[name]
            ahead = _at(frame + 2)[name]
            travel = math.atan2(ahead[1] - here[1], ahead[0] - here[0])
            drift = abs(math.atan2(math.sin(travel - here[3]), math.cos(travel - here[3])))
            worst = max(worst, drift)
        assert worst < math.radians(20.0), (vehicle["slot"], math.degrees(worst))


def test_the_road_surface_constants_match_the_real_meshes(context: dict) -> None:
    """The replicated builder constants are PINNED against what Blender drew.

    Phase 19 places vehicles on road heights it copied from the locked builders.
    A copy that drifted would float or sink every car in the city, so the copy is
    checked against the meshes themselves rather than trusted.
    """
    state = _prepare(context)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    checked = 0
    for circuit in state["plan"]["vehicles"]["circuits"]:
        for point in circuit["points"][:: max(1, len(circuit["points"]) // 12)]:
            # The traffic is already standing on these lanes, so the first thing
            # a downward ray meets is often a van roof. Skip past anything the
            # mobility layer put there and keep going until the ROAD is reached;
            # measuring against a vehicle would be measuring Phase 19 against
            # itself.
            height = 8.0
            obj = None
            for _attempt in range(8):
                hit, location, _n, _i, obj, _m = bpy.context.scene.ray_cast(
                    depsgraph, Vector((point[0], point[1], height)), Vector((0.0, 0.0, -1.0))
                )
                if not hit:
                    obj = None
                    break
                if not obj.name.startswith(("LD_VEH__", "LD_MOBILITY_PATH__")):
                    break
                height = location.z - 0.02
            assert obj is not None, point
            assert not obj.name.startswith("LD_VEH__"), obj.name
            assert abs(location.z - point[2]) < 0.09, (obj.name, location.z, point[2])
            checked += 1
    assert checked >= 12


# ---------------------------------------------------------------------------
# The proof cameras -- the proof is worthless if they are pointed at nothing
# ---------------------------------------------------------------------------

_ATMOSPHERE = "LD_ATMOSPHERE"
_FRUSTUM_SAMPLES = 5
_SEEING_RANGE = 110.0
"""How far a camera can be from the city and still render it.

The diorama sits under a dense volumetric shell, so geometry much beyond this
is extinguished to black long before it reaches the film. Measured, not
guessed: the frame that shipped black stood 120 m out."""


def _solid_hit(origin, direction):
    """First hit that is not the atmosphere shell, which every ray passes through."""
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()
    start = origin.copy()
    for _attempt in range(6):
        hit, location, _n, _i, obj, _m = scene.ray_cast(depsgraph, start, direction)
        if not hit:
            return None, 0.0
        if not obj.name.startswith(_ATMOSPHERE):
            return obj, (location - origin).length
        start = location + direction * 0.05
    return None, 0.0


def _frustum_directions(camera) -> list:
    """Rays across the camera's OWN frame, so the test looks where the lens looks."""
    top_right, bottom_right, bottom_left, top_left = camera.data.view_frame(scene=bpy.context.scene)
    origin = camera.matrix_world.translation
    directions = []
    for row in range(_FRUSTUM_SAMPLES):
        down = row / (_FRUSTUM_SAMPLES - 1)
        left_edge = top_left.lerp(bottom_left, down)
        right_edge = top_right.lerp(bottom_right, down)
        for column in range(_FRUSTUM_SAMPLES):
            local = left_edge.lerp(right_edge, column / (_FRUSTUM_SAMPLES - 1))
            directions.append((camera.matrix_world @ local - origin).normalized())
    return directions


def test_every_proof_camera_actually_sees_the_diorama(context: dict) -> None:
    """A camera aimed at nothing proves nothing.

    Phase 19's first proof pass rendered a black city frame and a hero plate
    that was the inside of a wall: one camera stood off the edge of the round
    diorama entirely, another was buried in a Phase 16 building. Every test
    passed, because no test looked. This one looks, by firing the camera's own
    frustum at the real scene and demanding that most of the frame land on
    solid city within the distance the atmosphere still transmits.
    """
    state = _prepare(context)
    build_mobility_cameras(state["spec"])
    total = _FRUSTUM_SAMPLES * _FRUSTUM_SAMPLES
    complaints = []
    for name in sorted(state["spec"]["proof"]["cameras"]):
        camera = bpy.data.objects.get(name)
        assert camera is not None, f"{name} was not built"
        origin = camera.matrix_world.translation
        seen, nearest, subjects = 0, 1.0e9, set()
        for direction in _frustum_directions(camera):
            obj, reach = _solid_hit(origin, direction)
            if obj is None or reach > _SEEING_RANGE:
                continue
            seen += 1
            nearest = min(nearest, reach)
            subjects.add(obj.name)
        if seen * 2 < total:
            complaints.append(f"{name} sees the city in only {seen}/{total} of its frame")
        elif nearest <= 1.0:
            complaints.append(f"{name} is buried, nearest surface {nearest:.2f} m")
        elif len(subjects) < 3:
            # One flat surface filling the frame is what a camera inside a wall
            # renders, and it is not a picture of a city.
            complaints.append(f"{name} sees only {len(subjects)} thing(s): {sorted(subjects)}")
    assert not complaints, "; ".join(complaints)


def test_no_mover_ever_passes_through_a_proof_camera(context: dict) -> None:
    """A camera parked on a carriageway goes black the moment a car reaches it.

    The Phase 19 gait camera did exactly that: it stood on circuit_02's lane,
    so three of five sampled frames rendered the inside of a van. Sampling a
    few frames cannot catch this, so every canonical frame is swept.
    """
    state = _prepare(context)
    timeline = state["timeline"]
    origins = {
        name: Vector(entry["location"]) for name, entry in state["spec"]["proof"]["cameras"].items()
    }
    worst = {name: (1.0e9, "", 0) for name in origins}
    for frame in range(timeline["start_frame"], timeline["end_frame"] + 1):
        for mover, transform in _at(frame).items():
            where = Vector(transform[:3])
            for name, origin in origins.items():
                gap = (where - origin).length
                if gap < worst[name][0]:
                    worst[name] = (gap, mover, frame)
    for name, (gap, mover, frame) in sorted(worst.items()):
        assert gap > 1.5, f"{mover} comes within {gap:.2f} m of {name} at frame {frame}"


# ---------------------------------------------------------------------------
# The Phase 18 recovery contract
# ---------------------------------------------------------------------------


def test_clearing_mobility_restores_phase18_exactly(context: dict) -> None:
    """Removability is a contract, and it is proved by comparison, not by intent.

    Runs LAST on purpose -- it tears the layer down and builds it again, so
    anything after it would be measuring the second build.
    """
    state = _prepare(context)
    mobility.clear_mobility_layer()
    mobility.restore_population_transforms(state["plan"])
    bpy.context.view_layer.update()

    assert population.proxy_positions() == state["phase18_transforms"]
    assert {
        obj.name: (len(obj.data.vertices), len(obj.data.polygons))
        for obj in population.population_objects()
    } == state["phase18_meshes"]
    assert not [
        obj.name
        for obj in bpy.data.objects
        if obj.name.startswith(("LD_VEH__", "LD_MOBILITY_PATH__"))
    ]
    assert not [
        action.name for action in bpy.data.actions if action.name.startswith("LD_MOBILITY__")
    ]
    assert not [
        obj.name for obj in population.population_objects() if obj.data.shape_keys is not None
    ]
    assert bpy.data.collections.get("LD_MOBILITY") is None

    rebuilt = mobility.apply_mobility(state["plan"], state["spec"])
    assert rebuilt["plan_hash"] == state["metrics"]["plan_hash"]
    assert mobility.mobility_summary()["duplicate_named_objects"] == 0
