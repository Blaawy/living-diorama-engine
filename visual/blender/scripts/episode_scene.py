"""Stand one complete directed episode world up in Blender, in phase order.

This is the production composition path: the same locked planners and appliers
the structural suites use, called in the one order the layers allow, followed
by Phase 22's camera cuts. It builds a scene; it renders nothing and writes no
files.

The order is not a preference. ``build_motion_scene`` wipes and rebuilds
Phases 15 to 17 -- it calls ``build_master_scene``, which clears the LD
collections -- so it runs first and exactly once. Phases 18, 19 and 20 are
additive and each clears only its own prefix, so they follow. Phase 20's
static layer is applied from the leg's AFTER export, because memory only
grows and the after state is the superset both motion endpoints need, and its
transition curves are written over that. Phase 22's markers come last, over a
world that is already complete.

Nothing here reimplements a prior layer. Every call is that layer's own
public entry point with the arguments its own suite uses, so a world composed
here is the world those suites already prove.
"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:  # pragma: no cover - import-path bootstrap
    sys.path.insert(0, str(SCRIPTS_DIR))

COMPOSITION_STYLE = "dna"
"""The reviewed visual style every canonical proof and render is built in."""

OWNED_PREFIXES = {
    "population_proxies": "LD_POP__",
    "state_response_air_strata": "LD_SR__air_",
    "state_response_record_stones": "LD_SR__record_stone_",
}
"""Object-name prefixes the census counts, per layer that owns them."""


def compose_episode_world(
    *,
    spec_path: Path,
    production_path: Path,
    motion_path: Path,
    presence_path: Path,
    mobility_path: Path,
    state_response_path: Path,
    before_path: Path,
    after_path: Path,
) -> dict:
    """Compose Phases 15 through 20 on one transition world.

    Args:
        spec_path: Phase 15 master scene spec.
        production_path: Phase 16 production world spec.
        motion_path: Phase 17 Motion & Time spec.
        presence_path: Phase 18 population presence spec.
        mobility_path: Phase 19 daily-life mobility spec.
        state_response_path: Phase 20 state response spec.
        before_path: The render export the transition starts from.
        after_path: The render export the transition ends on.

    Returns:
        The expected census of the composed world, derived from the plans that
        built it rather than from constants: proxies, vehicle bodies, air
        strata and record stones.
    """
    import apply_mobility as mobility
    import apply_motion_plan as motion
    import apply_population_presence as population
    import apply_state_response as state_response
    import apply_state_response_motion as state_response_motion
    import mobility_plan as mobility_planner
    import pedestrian_topology as topology_planner
    import population_presence_plan as presence_planner
    import road_graph
    import state_response_motion_plan
    import state_response_plan
    import urban_fabric
    from mobility_spec import load_daily_life_mobility_spec, resolve_mobility_timeline
    from motion_time_spec import load_motion_time_spec
    from population_presence_spec import load_population_presence_spec
    from production_spec import load_production_world_spec
    from scene_spec import load_master_scene_spec, load_render_export
    from state_response_spec import load_state_response_spec, resolve_state_response_timeline

    master = load_master_scene_spec(spec_path)
    production = load_production_world_spec(production_path)
    motion_timeline = load_motion_time_spec(motion_path)["timeline"]

    graph = road_graph.build_road_graph(master, production)
    fabric = urban_fabric.plan_urban_fabric(master, production, graph)
    presence_spec = load_population_presence_spec(presence_path)
    topology = topology_planner.plan_pedestrian_topology(
        master, production, graph, fabric, presence_spec
    )
    export_before = load_render_export(before_path)
    export_after = load_render_export(after_path)
    presence = presence_planner.plan_population_presence(
        export_before, master, presence_spec, topology
    )

    mobility_spec = load_daily_life_mobility_spec(mobility_path)
    mobility_timeline = resolve_mobility_timeline(mobility_spec, motion_timeline)
    daily_life = mobility_planner.plan_daily_life_mobility(
        presence,
        presence_spec,
        mobility_spec,
        mobility_timeline,
        master,
        production,
        graph,
        fabric,
    )

    sr_spec = load_state_response_spec(state_response_path)
    sr_timeline = resolve_state_response_timeline(sr_spec, motion_timeline)
    sr_before = state_response_plan.plan_state_response(export_before, master, sr_spec)
    sr_after = state_response_plan.plan_state_response(export_after, master, sr_spec)
    sr_motion = state_response_motion_plan.plan_state_response_motion(
        sr_before, sr_after, sr_spec, sr_timeline
    )

    motion.build_motion_scene(
        spec_path,
        production_path,
        before_path,
        after_path,
        motion_path,
        style=COMPOSITION_STYLE,
    )
    population.apply_population_presence(presence, presence_spec)
    mobility.apply_mobility(daily_life, mobility_spec)
    state_response.apply_state_response(sr_after, sr_spec)
    state_response_motion.apply_state_response_motion(sr_motion, sr_timeline)

    responses = sr_after["responses"]
    return {
        "expected_proxies": len(presence["proxies"]),
        "expected_vehicles": daily_life["vehicles"]["count"],
        "expected_air": sum(1 for entry in responses if entry["channel"] == "district_air"),
        "expected_stones": sum(1 for entry in responses if entry["channel"] == "memory_record"),
    }


def census_composed_world(
    bpy_module, expected: dict, *, expect_state_response_motion: bool = True
) -> dict:
    """Count what the composed scene actually holds, and refuse a half-built one.

    Photographing an incomplete world would produce footage that looks like a
    finished episode and quietly omits a layer, so the counts must be exact --
    not merely non-zero -- against the plans that were just applied.

    Args:
        bpy_module: The Blender module.
        expected: The census returned by :func:`compose_episode_world`.
        expect_state_response_motion: Whether Phase 20 transition curves must
            exist. A baseline composes one state from one export, so Phase 20
            writes no transition directives and there is legitimately nothing to
            animate -- its static layer still stands, and is still counted
            exactly. Requiring curves there would refuse a correct world.

    Returns:
        The observed census, once it matches.

    Raises:
        RuntimeError: If any layer is missing or the wrong size.
    """
    objects = [obj.name for obj in bpy_module.data.objects]
    actions = [action.name for action in bpy_module.data.actions]
    observed = {
        "population_proxies": sum(1 for name in objects if name.startswith("LD_POP__")),
        "mobility_vehicle_bodies": sum(
            1 for name in objects if name.startswith("LD_VEH__") and "__wheel_" not in name
        ),
        "state_response_air_strata": sum(1 for name in objects if name.startswith("LD_SR__air_")),
        "state_response_record_stones": sum(
            1 for name in objects if name.startswith("LD_SR__record_stone_")
        ),
        "mobility_actions": sum(1 for name in actions if name.startswith("LD_MOBILITY__")),
        "state_response_actions": sum(
            1 for name in actions if name.startswith("LD_STATE_RESPONSE__")
        ),
    }
    required = {
        "population_proxies": expected["expected_proxies"],
        "mobility_vehicle_bodies": expected["expected_vehicles"],
        "state_response_air_strata": expected["expected_air"],
        "state_response_record_stones": expected["expected_stones"],
    }
    for key, wanted in sorted(required.items()):
        if observed[key] != wanted:
            raise RuntimeError(
                f"composed world holds {observed[key]} {key}, but the applied plans account "
                f"for {wanted}; Phase 23 refuses to photograph a half-built world"
            )
    required_actions = ["mobility_actions"]
    if expect_state_response_motion:
        required_actions.append("state_response_actions")
    for key in required_actions:
        if observed[key] < 1:
            raise RuntimeError(
                f"composed world carries no {key}; the episode would render as a still world"
            )
    return observed


def direct_episode_world(bpy_module, shot_plan: dict, catalogue: dict) -> dict:
    """Bind Phase 22's camera cuts onto the composed world, unchanged.

    Phase 23 does not re-implement direction: it calls Phase 22's own applier,
    which verifies every anchor's full identity, the execution clock and the
    absence of foreign camera markers, and refuses rather than repairs.

    Args:
        bpy_module: The Blender module.
        shot_plan: The validated Shot Direction Plan document.
        catalogue: The approved camera-anchor catalogue.

    Returns:
        Phase 22's own applier report.
    """
    from apply_cinematic_direction import apply_shot_direction_plan

    return apply_shot_direction_plan(bpy_module, shot_plan, catalogue)
