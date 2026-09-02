"""Contract tests for the OPEN presentation-trajectory pedestrian mobility V2.

Pure pytest -- no Blender. The V2 plan is derived once and interrogated: every
claim is recomputed from what the plan SAYS, exactly as the V1 suite does for
the closed-loop shape. The rules under test are the ones that make an open
trajectory an honest claim: no closed loop, no repeated sub-path, every route
start and end a REAL topology anchor, distinct speeds and start offsets,
dispersion across anchors, some solo and some grouped walkers, deterministic
output across runtime contexts, and a V1 profile that is byte-for-byte what it
always was.
"""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"
CONFIG_DIR = REPO_ROOT / "visual" / "blender" / "config"


def _load(name: str):
    """Import one pure visual module the same way Blender does: by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


mp = _load("mobility_plan")
v2 = _load("pedestrian_mobility_v2")
walking = _load("pedestrian_mobility")
figure_kit = _load("figure_kit")
mobility_spec = _load("mobility_spec")
motion_time_spec = _load("motion_time_spec")
scene_spec = _load("scene_spec")
production_spec = _load("production_spec")
road_graph = _load("road_graph")
urban_fabric = _load("urban_fabric")
topo = _load("pedestrian_topology")
pres = _load("population_presence_plan")
pps = _load("population_presence_spec")


@pytest.fixture(name="built", scope="module")
def built_fixture() -> dict:
    """The canonical V1 and V2 plans and everything they were derived from."""
    master = scene_spec.load_master_scene_spec(CONFIG_DIR / "master_scene_v1.json")
    prod = production_spec.load_production_world_spec(CONFIG_DIR / "production_world_v1.json")
    presence_spec = pps.load_population_presence_spec(CONFIG_DIR / "population_presence_v1.json")
    spec = mobility_spec.load_daily_life_mobility_spec(CONFIG_DIR / "daily_life_mobility_v1.json")
    timeline = mobility_spec.resolve_mobility_timeline(
        spec, motion_time_spec.load_motion_time_spec(CONFIG_DIR / "motion_time_v1.json")["timeline"]
    )
    graph = road_graph.build_road_graph(master, prod)
    fabric = urban_fabric.plan_urban_fabric(master, prod, graph)
    topology = topo.plan_pedestrian_topology(master, prod, graph, fabric, presence_spec)
    export = {
        "format": "living_diorama_render_export",
        "schema_version": 1,
        "source": {"episode": 0},
        "world": {
            "districts": [
                {"id": district_id, "population": 100, "character": entry["character"]}
                for district_id, entry in sorted(master["districts"].items())
            ],
            "boundaries": [],
            "infrastructure": [],
        },
        "events": [],
        "memory": {},
    }
    presence = pres.plan_population_presence(export, master, presence_spec, topology)
    plan_v1 = mp.plan_daily_life_mobility(
        presence, presence_spec, spec, timeline, master, prod, graph, fabric
    )
    plan_v1_explicit = mp.plan_daily_life_mobility(
        presence,
        presence_spec,
        spec,
        timeline,
        master,
        prod,
        graph,
        fabric,
        mobility_profile="v1",
    )
    plan_v2 = mp.plan_daily_life_mobility(
        presence,
        presence_spec,
        spec,
        timeline,
        master,
        prod,
        graph,
        fabric,
        mobility_profile="v2",
    )
    return {
        "plan_v1": plan_v1,
        "plan_v1_explicit": plan_v1_explicit,
        "plan_v2": plan_v2,
        "presence": presence,
        "presence_spec": presence_spec,
        "spec": spec,
        "timeline": timeline,
        "master": master,
        "production": prod,
        "graph": graph,
        "fabric": fabric,
        "topology": topology,
    }


def _canonical(plan: dict) -> str:
    return json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


# ---------------------------------------------------------------------------
# V1 compatibility: byte-for-byte regression
# ---------------------------------------------------------------------------


def test_v1_default_is_byte_identical_to_explicit_v1(built: dict) -> None:
    """mobility_profile="v1" (and the default) reproduce today's exact plan."""
    assert _canonical(built["plan_v1"]) == _canonical(built["plan_v1_explicit"])
    assert built["plan_v1"]["format"] == mp.MOBILITY_PLAN_FORMAT
    assert "mobility_profile" not in built["plan_v1"]


def test_v2_is_a_distinct_additive_document(built: dict) -> None:
    """V2 has its own format, schema, statement and profile, and no loop fields."""
    plan = built["plan_v2"]
    assert plan["format"] == v2.MOBILITY_PLAN_V2_FORMAT
    assert plan["schema_version"] == v2.MOBILITY_PLAN_V2_SCHEMA_VERSION
    assert plan["mobility_profile"] == "v2"
    assert plan["statement"] == v2.PRESENTATION_STATEMENT_V2
    assert _canonical(plan) != _canonical(built["plan_v1"])
    assert all("cycles" not in walker for walker in plan["pedestrians"]["walkers"])


# ---------------------------------------------------------------------------
# Hard constraints
# ---------------------------------------------------------------------------


def test_no_visible_pedestrian_loop(built: dict) -> None:
    """No V2 trajectory repeats a directed sub-path or returns to its start."""
    metrics = v2.mobility_metrics_v2(built["plan_v2"])
    assert metrics["loop_violation_count"] == 0
    for walker in built["plan_v2"]["pedestrians"]["walkers"]:
        assert v2._repeats_subpath(walker["points"]) is False
        assert walker["route_end"]["anchor_id"] != walker["route_start"]["anchor_id"]


def test_spatial_dispersion_and_distinct_values(built: dict) -> None:
    """Starts and ends spread across anchors; speeds and offsets are distinct."""
    metrics = v2.mobility_metrics_v2(built["plan_v2"])
    moving = metrics["visible_agent_count"]
    assert metrics["distinct_route_start_count"] >= min(6, moving)
    assert metrics["distinct_route_end_count"] >= min(6, moving)
    assert metrics["distinct_speed_count"] == moving
    assert metrics["distinct_start_offset_count"] == moving


def test_solo_and_groups_both_present_when_count_permits(built: dict) -> None:
    """Some walkers are solo and some are in small groups when the crowd allows."""
    walkers = built["plan_v2"]["pedestrians"]["walkers"]
    grouped = [w for w in walkers if w["social_grouping_state"].get("group") is not None]
    solo = [w for w in walkers if w["social_grouping_state"].get("group") is None]
    if len(walkers) >= 6:
        assert grouped and solo
    for walker in grouped:
        members = int(walker["social_grouping_state"]["members"])
        assert 2 <= members <= 4


def test_every_route_is_on_proven_clear_ground(built: dict) -> None:
    """The V2 validator re-proves every waypoint/segment clear of the city."""
    errors = v2.validate_mobility_plan_v2(
        built["plan_v2"],
        built["presence"],
        built["topology"],
        built["spec"],
        built["timeline"],
        built["master"],
        built["production"],
        built["graph"],
        built["fabric"],
    )
    assert errors == []


def test_metrics_are_pure_and_consistent(built: dict) -> None:
    """The plan's published metrics equal the recomputed pure function output."""
    metrics = v2.mobility_metrics_v2(built["plan_v2"])
    assert built["plan_v2"]["summary"]["metrics"] == metrics
    assert metrics["freeze_violation_count"] == 0
    assert metrics["loop_violation_count"] == 0


def test_import_audit_no_narration_or_caption_coupling() -> None:
    """The V2 module's dependency closure never touches narration/caption."""
    import ast

    pending = ["pedestrian_mobility_v2.py"]
    seen: set[str] = set()
    roots: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        tree = ast.parse((SCRIPTS_DIR / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    roots.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots.add(node.module.split(".")[0])
        for node in ast.walk(tree):
            # Only recurse into a LOCAL sibling module (a file that really
            # exists under visual/blender/scripts/). A stdlib or third-party
            # name such as pathlib/math/hashlib is an external dependency:
            # its own name was already checked against the banned-substring
            # list above, but there is no file to open for it, so recursion
            # must stop there instead of crashing on a missing file.
            if (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
                and (SCRIPTS_DIR / f"{node.module}.py").is_file()
            ):
                pending.append(f"{node.module}.py")
    forbidden = {root for root in roots if "narration" in root or "caption" in root}
    assert not forbidden, f"V2 dependency closure imports {sorted(forbidden)}"


# ---------------------------------------------------------------------------
# Metamorphic determinism across hash seeds and runtime contexts
# ---------------------------------------------------------------------------

_METAMORPHIC_SCRIPT = f"""
import os, socket, platform, time
_pid = int(os.environ["V2_TEST_PID"]); _host = os.environ["V2_TEST_HOST"]
_t = float(os.environ["V2_TEST_TIME"]); _t_ns = int(os.environ["V2_TEST_TIME_NS"])
os.getpid = lambda: _pid
socket.gethostname = lambda: _host
platform.node = lambda: _host
time.time = lambda: _t
time.time_ns = lambda: _t_ns
import sys
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
import mobility_plan as mp
import motion_time_spec, scene_spec, production_spec, road_graph, urban_fabric, pedestrian_topology
import population_presence_plan as pres
import population_presence_spec as pps
import mobility_spec as msp
master = scene_spec.load_master_scene_spec(\
{str(CONFIG_DIR / "master_scene_v1.json")!r})
prod = production_spec.load_production_world_spec(\
{str(CONFIG_DIR / "production_world_v1.json")!r})
pspec = pps.load_population_presence_spec(\
{str(CONFIG_DIR / "population_presence_v1.json")!r})
spec = msp.load_daily_life_mobility_spec(\
{str(CONFIG_DIR / "daily_life_mobility_v1.json")!r})
timeline = msp.resolve_mobility_timeline(spec, motion_time_spec.load_motion_time_spec(\
{str(CONFIG_DIR / "motion_time_v1.json")!r})["timeline"])
graph = road_graph.build_road_graph(master, prod)
fabric = urban_fabric.plan_urban_fabric(master, prod, graph)
topology = pedestrian_topology.plan_pedestrian_topology(master, prod, graph, fabric, pspec)
export = {{"format": "living_diorama_render_export", "schema_version": 1,
    "source": {{"episode": 0}},
    "world": {{"districts": [{{"id": d, "population": 100,
        "character": master["districts"][d]["character"]}} for d in sorted(master["districts"])],
        "boundaries": [], "infrastructure": []}},
    "events": [], "memory": {{}}}}
presence = pres.plan_population_presence(export, master, pspec, topology)
plan = mp.plan_daily_life_mobility(\
presence, pspec, spec, timeline, master, prod, graph, fabric, mobility_profile="v2")
print(mp.mobility_plan_hash(plan))
"""

_METAMORPHIC_CONTEXTS = [
    {
        "seed": "0",
        "pid": "410001",
        "host": "ci-runner-alpha.example",
        "t": "1000000000.0",
        "t_ns": "1000000000000000000",
    },
    {
        "seed": "1",
        "pid": "520002",
        "host": "build-node-beta.internal",
        "t": "1500000000.5",
        "t_ns": "1500000000500000000",
    },
    {
        "seed": "42",
        "pid": "630003",
        "host": "runner-gamma-42",
        "t": "1700000000.25",
        "t_ns": "1700000000250000000",
    },
    {
        "seed": "123456",
        "pid": "740004",
        "host": "worker-delta-999",
        "t": "1999999999.75",
        "t_ns": "1999999999750000000",
    },
]


def test_v2_plan_is_one_digest_across_hash_seeds_and_runtime_contexts() -> None:
    """Fresh interpreters under varied hash seeds and runtime contexts agree on one digest.

    PYTHONHASHSEED in {0,1,42,123456}, each with a deliberately different pid,
    hostname and wall clock, all emit one identical V2 plan digest.
    """
    digests: list[str] = []
    for context in _METAMORPHIC_CONTEXTS:
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = context["seed"]
        env["V2_TEST_PID"] = context["pid"]
        env["V2_TEST_HOST"] = context["host"]
        env["V2_TEST_TIME"] = context["t"]
        env["V2_TEST_TIME_NS"] = context["t_ns"]
        result = subprocess.run(
            [sys.executable, "-c", _METAMORPHIC_SCRIPT],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        digest = result.stdout.strip()
        assert digest, f"seed {context['seed']} produced no digest: {result.stderr}"
        digests.append(digest)
    assert len(set(digests)) == 1, f"V2 plan diverged across contexts: {digests}"


# ---------------------------------------------------------------------------
# Metrics on a small synthetic sample (hand-pinned so the numbers are reviewable)
# ---------------------------------------------------------------------------


def _synthetic_v2_plan() -> dict:
    """A six-walker V2 document with every invariant hand-chosen.

    The metric numbers below are derived by hand from THIS document, so a
    reviewer can audit the pure function against the exact input.
    """
    walkers = []
    for index in range(6):
        walkers.append(
            {
                "slot": f"D1__slot_{index + 1:03d}",
                "district": "D1",
                "slot_index": index + 1,
                "route_start": {"anchor_id": f"D1__frontage__{index:03d}"},
                "route_end": {"anchor_id": f"D1__promenade__{index:03d}"},
                "preferred_speed": round(1.00 + index * 0.11, 2),
                "start_offset": round(0.333 + index * 0.667, 3),
                "points": [[index * 2.0, 0.0, 0.0], [index * 2.0 + 2.0, 1.0, 0.0]],
                "route_length": (2.0**2 + 1.0**2) ** 0.5,
                "social_grouping_state": (
                    {"group": "v2_group_01", "members": 2, "role": "lead", "member_index": 0}
                    if index == 0
                    else {"group": "v2_group_01", "members": 2, "role": "member", "member_index": 1}
                    if index == 1
                    else {"group": None}
                ),
                "micro_behavior_schedule": [],
            }
        )
    return {
        "format": v2.MOBILITY_PLAN_V2_FORMAT,
        "schema_version": 1,
        "mobility_profile": "v2",
        "statement": v2.PRESENTATION_STATEMENT_V2,
        "timeline": {},
        "pedestrians": {"walkers": walkers},
    }


def test_metrics_on_the_synthetic_sample_are_exactly_these_numbers() -> None:
    """The pure metrics function, pinned to hand-derived values."""
    plan = _synthetic_v2_plan()
    assert v2.mobility_metrics_v2(plan) == {
        "visible_agent_count": 6,
        "distinct_route_start_count": 6,
        "distinct_route_end_count": 6,
        "group_participation_fraction": 0.3333,
        "distinct_speed_count": 6,
        "distinct_start_offset_count": 6,
        "freeze_violation_count": 0,
        "loop_violation_count": 0,
    }


# ---------------------------------------------------------------------------
# The OPEN-path turn check (the V2 architectural fix)
# ---------------------------------------------------------------------------


def test_open_path_turn_check_measures_only_interior_turns(built: dict) -> None:
    """The open-path turn check never wraps to the route's own start.

    A straight two-point open route (the S->E, 2.5m minimal example) has no
    interior turn at all -- every resampled interior point is collinear -- so
    it must report ZERO violations, while the closed-loop V1
    ``turn_rate_violations`` reports a phantom seam turn (about 1700 deg/s
    against the 165 deg/s limit) on that same polyline. A genuinely sharp
    interior corner must be flagged instead, and only interior points are ever
    measured.
    """
    spec = built["spec"]
    straight = [(0.0, 0.0), (2.5, 0.0)]
    assert v2.open_path_turn_violations(straight, 1.4, spec) == []
    sharp = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    sharp_turns = v2.open_path_turn_violations(sharp, 1.4, spec)
    assert sharp_turns
    assert "turns at" in sharp_turns[0]


# ---------------------------------------------------------------------------
# The improved search: real achieved count, real safety, V1 untouched
# ---------------------------------------------------------------------------


def test_real_ep1_achieved_moving_count_under_the_improved_search(built: dict) -> None:
    """The real EP1 world's achieved-moving count under the improved search.

    The pre-improvement search honestly achieved 11 of the 24 requested
    movers on the real EP1 world (every refusal carried a recorded geometric
    reason; the 24-target was never reached so the search never stopped
    early). The improved search -- more seeded attempts, a wider waypoint
    pool, and a new straight single-hop shape, all over the SAME real
    topology and the SAME safety thresholds -- must report its REAL achieved
    count, and must never regress below the honest baseline of 11. The number
    asserted here is whatever the planner really produces; the pre-improvement
    baseline of 11 is recorded in the Director's real EP1 measurement.
    """
    pedestrians = built["plan_v2"]["pedestrians"]
    moving = pedestrians["moving"]
    requested = pedestrians["requested_moving"]
    refused = pedestrians["refused"]
    # The declared fraction is a ceiling, never a floor: over-delivery is a
    # contract violation, and a shortfall is only legitimate when every
    # unreached slot carries a real, non-empty recorded reason.
    assert moving <= requested, f"improved search walks {moving}, above the declared {requested}"
    assert len(refused) >= requested - moving, (
        f"achieved {moving}/{requested} with only {len(refused)} refusal(s); every "
        "unreached slot must carry a real recorded reason"
    )
    assert all(reason.strip() for reason in refused.values()), "a refusal carries no reason"
    assert moving >= 11, (
        f"improved search achieved {moving}/{requested}, below the honest "
        "pre-improvement baseline of 11"
    )


def test_every_accepted_route_still_passes_every_real_safety_check(built: dict) -> None:
    """No route accepted by the improved search is unsafe.

    Independently of ``validate_mobility_plan_v2``, re-run the two real
    safety checks on every accepted route with the walker's own recorded
    speed: proven-clear ground (``route_violations``) and the open-path turn
    check (``open_path_turn_violations``). The straight single-hop shape is
    new candidate SPACE, not a new safety standard -- a route accepted
    through it must pass the exact same checks as every multi-hop route.
    """
    pedestrians = built["plan_v2"]["pedestrians"]
    known = {proxy["slot"]: proxy for proxy in built["presence"]["proxies"]}
    spec = built["spec"]
    validator = topo.build_presence_occupancy(
        built["master"], built["production"], built["graph"], built["fabric"]
    )
    roads = topo.street_occupancy_shapes(validator)
    body_radius = float(built["presence_spec"]["proxy"]["radius"])
    index = walking.PresenceIndex(validator, body_radius)
    probe = walking.GroundProbe(built["master"], built["fabric"])
    for walker in pedestrians["walkers"]:
        proxy = known[walker["slot"]]
        loop_2d = [(point[0], point[1]) for point in walker["points"]]
        violations = walking.route_violations(
            loop_2d, proxy, index, roads, probe, spec, body_radius
        )
        assert violations == [], f"{walker['slot']} is not on proven-clear ground: {violations[:1]}"
        turning = v2.open_path_turn_violations(loop_2d, float(walker["preferred_speed"]), spec)
        assert turning == [], f"{walker['slot']} turns too sharply: {turning[:1]}"
        assert len(loop_2d) >= 2
        assert walker["route_end"]["anchor_id"] != walker["route_start"]["anchor_id"]


def test_gait_cycles_compatibility_is_checked_before_a_route_is_accepted(built: dict) -> None:
    """A route whose length cannot close on whole strides is refused by the search.

    The plan's own downstream gait resolution (``pedestrian_mobility.
    gait_cycles``, the shared V1/V2 helper) refuses a route whose real length
    cannot close on a whole number of strides within the declared
    ``stride_tolerance`` -- the check the improved search previously never
    validated against, which crashed the real EP1 plan with e.g. "closing
    this loop on 2 whole strides needs a 1.635m stride against a natural
    1.328m, 23.1% off the declared 20% tolerance". The search now runs that
    SAME check on every candidate before accepting it
    (``pedestrian_mobility_v2.gait_cycle_violation``), so a length that would
    trip the downstream check is refused here with a real, categorized reason
    instead of crashing the plan after acceptance. This is a real synthetic
    case: a real proxy's identity and the real spec, and a length computed
    from that body's own nominal stride to land 23% off -- the same refusal
    class as the real EP1 regression.
    """
    spec = built["spec"]
    proxy = next(iter(built["presence"]["proxies"]))
    identity = {axis: proxy[axis] for axis in pps.FIGURE_AXES}
    identity["height"] = float(proxy["height"])
    nominal = float(spec["pedestrians"]["gait"]["stride_factor"]) * float(
        figure_kit.figure_dimensions(identity)["height"]
    )
    # 2.46 nominal strides rounds down to 2 WHOLE strides, so the effective
    # stride becomes 1.23 * nominal -- 23% off, beyond the declared 20%.
    tripping = 2.46 * nominal
    # 2.0 nominal strides closes exactly: effective stride == nominal stride.
    whole = 2.0 * nominal
    # The downstream check really refuses the tripping length (the plan would
    # crash at gait resolution without the search-level gate)...
    with pytest.raises(walking.PedestrianMobilityError) as raised:
        walking.gait_cycles(tripping, identity, spec)
    assert "stride" in str(raised.value)
    # ...and the search refuses the SAME length, with the SAME real message,
    # before accepting the candidate...
    reason = v2.gait_cycle_violation(tripping, proxy, spec)
    assert reason is not None
    assert "stride" in reason
    assert reason == str(raised.value)
    # ...while a whole-strides route of the same body passes the gate.
    assert v2.gait_cycle_violation(whole, proxy, spec) is None
    assert walking.gait_cycles(whole, identity, spec)["stride_drift"] == 0.0


def test_every_accepted_route_closes_on_a_whole_number_of_strides(built: dict) -> None:
    """Every accepted route is gait-compatible: it closes on whole strides.

    Independently of the plan construction, re-run the plan's OWN gait
    resolution (``gait_cycles``) on every accepted route with the walker's
    recorded length and identity. Before the search learned to check gait
    compatibility, a route whose length could not close on a whole number of
    strides within ``stride_tolerance`` crashed the whole plan at this very
    step (the real EP1 regression); the search now refuses such a candidate
    before accepting it, so every accepted route must resolve without raising
    and stay inside the declared tolerance.
    """
    spec = built["spec"]
    tolerance = float(spec["pedestrians"]["gait"]["stride_tolerance"])
    for walker in built["plan_v2"]["pedestrians"]["walkers"]:
        cycle = walking.gait_cycles(float(walker["route_length"]), walker, spec)
        assert cycle["stride_drift"] <= tolerance, walker["slot"]


def test_v1_profile_is_completely_unaffected_by_the_improved_v2_search(built: dict) -> None:
    """mobility_profile="v1" keeps today's exact plan and its real 24 movers.

    The improved search lives entirely inside ``pedestrian_mobility_v2``;
    the V1 path in ``mobility_plan.plan_pedestrian_mobility`` never calls it
    (see the dispatch in ``mobility_plan.plan_daily_life_mobility``: only
    ``mobility_profile="v2"`` reaches this module). The V1 plan must stay
    byte-identical to the explicit-V1 plan and keep the real EP1 moving count
    of 24 that the declared fraction derives -- the V1 suite pins this too.
    """
    assert _canonical(built["plan_v1"]) == _canonical(built["plan_v1_explicit"])
    assert built["plan_v1"]["pedestrians"]["moving"] == 24
    assert (
        built["plan_v1"]["pedestrians"]["moving"]
        == built["plan_v1"]["pedestrians"]["requested_moving"]
    )


def test_the_improved_search_is_deterministic_byte_for_byte(built: dict) -> None:
    """Two independent V2 plans from the same world are one canonical JSON.

    The new straight single-hop shape draws from its own seeded generator
    (slot + attempt + "hop"), so a second full run -- including the new
    shape, the doubled attempt count and the wider waypoint pool -- must
    reproduce the first plan exactly. This is the in-process sibling of the
    metamorphic cross-context test above.
    """
    again = mp.plan_daily_life_mobility(
        built["presence"],
        built["presence_spec"],
        built["spec"],
        built["timeline"],
        built["master"],
        built["production"],
        built["graph"],
        built["fabric"],
        mobility_profile="v2",
    )
    assert _canonical(again) == _canonical(built["plan_v2"])
