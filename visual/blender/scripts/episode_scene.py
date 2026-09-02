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


def merge_mobility_v2_plan(pedestrian_plan: dict, vehicle_plan: dict) -> dict:
    """Merge a pedestrians-only V2 plan with the separately-planned vehicles.

    V2's daily-life planner returns a document with NO ``vehicles`` key at all
    (see ``pedestrian_mobility_v2.plan_daily_life_mobility_v2``), so the
    vehicle half is planned independently via
    ``mobility_plan.plan_vehicle_mobility`` and merged in here, producing the
    single document the V2 pedestrian applier and the (already V2-aware)
    vehicle applier both consume. The pedestrian half keeps its own format,
    schema, statement and summary; only the ``vehicles`` key is added.
    """
    return {**pedestrian_plan, "vehicles": vehicle_plan}


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
    mobility_profile: str = "v1",
    traffic_profile: str = "v1",
    lighting_profile: str = "dna",
    visibility_profile: str = "full",
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
        mobility_profile: ``"v1"`` (default) or ``"v2"``. V1 reproduces today's
            closed-loop daily-life mobility byte-for-byte. V2 plans the
            open-trajectory pedestrian document separately from the vehicles
            and merges the two, then applies them with the V2 pedestrian
            applier and the already-V2-aware vehicle applier.
        traffic_profile: ``"v1"`` (default) or ``"v2"``. Selects the vehicle
            candidate set and the bounded-arc presentation. It is honoured ONLY
            under ``mobility_profile="v2"``: the V1 pedestrian path does not
            pass ``traffic_profile`` through, so ``traffic_profile="v2"`` with
            ``mobility_profile="v1"`` is refused rather than silently downgraded
            to V1 traffic. Unknown profile values are refused, never silently
            reinterpreted.
        lighting_profile: ``"dna"`` (default) or ``"dna_daylight"``. The
            additive lighting lane threaded into the Phase 15 world build,
            mirroring the ``camera_profile`` precedent: ``"dna"`` reproduces
            today's exact lighting byte-for-byte, ``"dna_daylight"`` applies
            the Director-revision late-morning daylight lane. The lane never
            touches exposure/view transform/look, which stay pinned by the
            render-profile digest.
        visibility_profile: ``"full"`` (default) or ``"director_clear_air_v1"``.
            ``"full"`` reproduces today's presentation byte-for-byte: every
            channel the state-response plan declares is drawn, including each
            district's air haze. ``"director_clear_air_v1"`` declines to DRAW
            the per-district air haze for the Director's final EP1 profile; the
            district-air FACT is unchanged -- the plan is still computed and
            reported in full -- only its visualisation is skipped.

    Returns:
        The expected census of the composed world, derived from the plans that
        built it rather than from constants: proxies, vehicle bodies, air
        strata and record stones.
    """
    import apply_mobility as mobility
    import apply_mobility_v2 as mobility_v2
    import apply_motion_plan as motion
    import apply_population_presence as population
    import apply_state_response as state_response
    import apply_state_response_motion as state_response_motion
    import collision_core_v2 as collision_verifier
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

    # Fail-closed profile validation: an unknown or unsupported combination
    # must refuse rather than silently reinterpret. An unknown mobility_profile
    # used to fall into the V1 branch, and the V1 branch never passes
    # traffic_profile, so v1+v2 silently produced V1 traffic. Valid v1 requests
    # (mobility_profile="v1", traffic_profile="v1") flow through untouched;
    # only invalid requests are refused.
    if mobility_profile not in ("v1", "v2"):
        raise mobility_planner.MobilityPlanError(
            f"unknown mobility_profile {mobility_profile!r}; expected 'v1' or 'v2'"
        )
    if traffic_profile not in ("v1", "v2"):
        raise mobility_planner.MobilityPlanError(
            f"unknown traffic_profile {traffic_profile!r}; expected 'v1' or 'v2'"
        )
    if mobility_profile == "v1" and traffic_profile == "v2":
        raise mobility_planner.MobilityPlanError(
            "mobility_profile='v1' cannot carry traffic_profile='v2': the V1 pedestrian "
            "path plans vehicles without traffic_profile and would silently downgrade the "
            "request to V1 traffic. Refusing rather than silently reinterpreting; use "
            "mobility_profile='v2' to carry V2 traffic."
        )

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
    if mobility_profile == "v2":
        # V2 pedestrians come from the open-trajectory planner, which returns a
        # pedestrians-ONLY document with no ``vehicles`` key at all, so the
        # vehicle half is planned SEPARATELY -- ``traffic_profile`` is an
        # independent choice and stays so -- and merged into one document the
        # V2 pedestrian applier and the V2-aware vehicle applier share.
        daily_life = merge_mobility_v2_plan(
            mobility_planner.plan_daily_life_mobility(
                presence,
                presence_spec,
                mobility_spec,
                mobility_timeline,
                master,
                production,
                graph,
                fabric,
                mobility_profile="v2",
            ),
            mobility_planner.plan_vehicle_mobility(
                mobility_spec,
                mobility_timeline,
                master,
                graph,
                fabric,
                traffic_profile=traffic_profile,
            ),
        )
    else:
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

    if mobility_profile == "v2":
        # Fail-closed production gate: the merged V2 plan must satisfy the V2
        # collision contract before any expensive Blender work (build_motion_scene
        # wipes and rebuilds Phases 15-17). Runs ONLY under v2; V1 documents carry
        # ``cycles`` and are never interpreted with V2 maths, so the V1 path is
        # untouched. A world with any violation is refused outright.
        collision_report = collision_verifier.verify_v2_collisions(
            daily_life, mobility_timeline, presence, mobility_spec
        )
        collision_totals = collision_verifier.violation_totals(collision_report)
        collision_rows = collision_report["rows"]
        reported = collision_totals["collision_violation_count"]
        # Fail closed on EITHER signal, and refuse outright if they disagree.
        # The count and the rows are two views of the same sweep; if a future
        # change to the core ever let them diverge, trusting the count alone
        # would silently pass a colliding world, so disagreement is itself a
        # refusal rather than a judgement call about which one to believe.
        if reported != len(collision_rows):
            raise mobility_planner.MobilityPlanError(
                "V2 collision gate refuses to compose the world: the collision report is "
                f"internally inconsistent -- it reports {reported} violation(s) but carries "
                f"{len(collision_rows)} violation row(s). The world will not be composed."
            )
        if reported != 0:
            first = min(collision_rows, key=lambda row: row["presentation_frame"])
            raise mobility_planner.MobilityPlanError(
                f"V2 collision gate refuses to compose the world: "
                f"{collision_totals['collision_violation_count']} collision violation(s) "
                f"across {collision_totals['frames_checked']} sampled frame(s). Minimum "
                f"clearances -- pedestrian-pedestrian "
                f"{collision_totals['minimum_pedestrian_pedestrian_clearance']}, "
                f"vehicle-vehicle {collision_totals['minimum_vehicle_vehicle_clearance']}, "
                f"vehicle-pedestrian "
                f"{collision_totals['minimum_vehicle_pedestrian_clearance']}. First "
                f"violation: frame {first['presentation_frame']}, {first['entity_a']} "
                f"({first['entity_type_a']}) vs {first['entity_b']} "
                f"({first['entity_type_b']}), distance {first['distance']}, required "
                f"clearance {first['required_clearance']}. The world will not be composed."
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
        lighting_profile=lighting_profile,
    )
    population.apply_population_presence(presence, presence_spec)
    if mobility_profile == "v2":
        # The V2 pedestrian applier clears and restores the Phase 18 proxies
        # exactly as V1's ``apply_mobility`` does, then the vehicles are applied
        # with the same collection and materials the V1 path builds.
        mobility_v2.apply_mobility_v2(daily_life, mobility_spec)
        collection = mobility.ensure_mobility_collection()
        materials = mobility.build_vehicle_materials()
        mobility.apply_vehicle_mobility(daily_life, materials, collection)
    else:
        mobility.apply_mobility(daily_life, mobility_spec)
    state_response.apply_state_response(sr_after, sr_spec, visibility_profile=visibility_profile)
    state_response_motion.apply_state_response_motion(
        sr_motion, sr_timeline, visibility_profile=visibility_profile
    )

    responses = sr_after["responses"]
    expected_air = sum(1 for entry in responses if entry["channel"] == "district_air")
    if visibility_profile == "director_clear_air_v1":
        # The district-air FACT is unchanged -- the plan above still computed
        # and reports it in full. This profile only declines to DRAW the haze,
        # so the composition check must expect zero air strata in the scene.
        expected_air = 0
    return {
        "expected_proxies": len(presence["proxies"]),
        "expected_vehicles": daily_life["vehicles"]["count"],
        "expected_air": expected_air,
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


def direct_episode_world(
    bpy_module, shot_plan: dict, catalogue: dict, *, camera_profile: str = "v1"
) -> dict:
    """Bind Phase 22's camera cuts onto the composed world, unchanged.

    Phase 23 does not re-implement direction: it calls Phase 22's own applier,
    which verifies every anchor's full identity, the execution clock and the
    absence of foreign camera markers, and refuses rather than repairs.

    ``camera_profile`` is ``"v1"`` (default) or ``"v2"``. Under V2, the
    movement applier runs FIRST -- before direction is applied -- so every
    movement shot's derived camera already exists in the scene (keyframed and
    marker-bound) when Phase 22's applier accepts the plan; under V1 the body
    is exactly the historic one.

    Args:
        bpy_module: The Blender module.
        shot_plan: The validated Shot Direction Plan document.
        catalogue: The approved camera-anchor catalogue.
        camera_profile: ``"v1"`` (default) or ``"v2"``.

    Returns:
        Phase 22's own applier report.
    """
    from apply_cinematic_direction import apply_shot_direction_plan

    if camera_profile == "v2":
        from apply_camera_movement import apply_camera_movements

        apply_camera_movements(bpy_module, shot_plan, catalogue)

    return apply_shot_direction_plan(
        bpy_module, shot_plan, catalogue, camera_profile=camera_profile
    )
