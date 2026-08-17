"""Contract tests for Phase 19 pedestrian mobility and gait.

Pure pytest -- no Blender. The gait is measured on the GENERATED vertices, not
on the angles that produced them, so a walk whose numbers look right but whose
body never moves fails here rather than in a video.

The rules under test are the ones that make walking honest: nobody new is
created, a walker leaves and returns to its own Phase 18 anchor, the route
closes, the turnaround is an arc rather than a snap, and the stride is DERIVED
from the travel so a walker cannot skate.
"""

import importlib
import itertools
import math
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


walking = _load("pedestrian_mobility")
figure_kit = _load("figure_kit")
mobility_spec = _load("mobility_spec")
motion_time_spec = _load("motion_time_spec")

IDENTITIES = (
    {
        "age_presentation": "adult",
        "presentation": "masculine",
        "stature": "average",
        "build": "average",
        "hair": "short",
        "facial_hair": "none",
        "face": "a",
        "clothing": "jacket",
        "palette": "slate",
        "complexion": "c2",
        "hair_tone": "h1",
        "pose": "idle",
    },
    {
        "age_presentation": "child",
        "presentation": "unspecified",
        "stature": "short",
        "build": "slim",
        "hair": "medium",
        "facial_hair": "none",
        "face": "b",
        "clothing": "short_sleeve",
        "palette": "moss",
        "complexion": "c3",
        "hair_tone": "h2",
        "pose": "stroll",
    },
    {
        "age_presentation": "elder",
        "presentation": "feminine",
        "stature": "tall",
        "build": "broad",
        "hair": "long",
        "facial_hair": "none",
        "face": "c",
        "clothing": "dress",
        "palette": "rust",
        "complexion": "c1",
        "hair_tone": "h4",
        "pose": "rest",
    },
)
"""Three bodies chosen to exercise the geometry, not to describe anybody.

A split-sleeve arm, a dress, a child's proportions and a broad build between
them cover every branch the gait has to survive."""


@pytest.fixture(name="spec", scope="module")
def spec_fixture() -> dict:
    """The canonical mobility spec."""
    return mobility_spec.load_daily_life_mobility_spec(CONFIG_DIR / "daily_life_mobility_v1.json")


@pytest.fixture(name="timeline", scope="module")
def timeline_fixture(spec: dict) -> dict:
    """The canonical mobility timeline."""
    motion = motion_time_spec.load_motion_time_spec(CONFIG_DIR / "motion_time_v1.json")
    return mobility_spec.resolve_mobility_timeline(spec, motion["timeline"])


def _cycle(identity: dict, spec: dict, timeline: dict) -> dict:
    """One body's gait, sized by the route its own speed demands."""
    height = figure_kit.figure_dimensions(identity)["height"]
    speed = walking.walking_speed(height, spec)
    length = mobility_spec.pedestrian_route_length(speed, timeline)
    return walking.gait_cycles(length, identity, spec)


# ---------------------------------------------------------------------------
# Speed
# ---------------------------------------------------------------------------


def test_a_taller_body_walks_faster(spec: dict) -> None:
    """Pendulum scaling on height. Mechanics, never an age assumption."""
    band = spec["pedestrians"]["speed"]
    speeds = [walking.walking_speed(height, spec) for height in (1.1, 1.5, 1.9)]
    assert speeds == sorted(speeds)
    assert all(band["min"] <= speed <= band["max"] for speed in speeds)


def test_walking_speed_is_clamped_to_the_declared_band(spec: dict) -> None:
    """No body walks outside the band, however tall or short it is."""
    band = spec["pedestrians"]["speed"]
    assert walking.walking_speed(0.2, spec) == pytest.approx(band["min"])
    assert walking.walking_speed(9.0, spec) == pytest.approx(band["max"])


def test_a_narrower_turnaround_belongs_to_a_slower_walker(spec: dict) -> None:
    """Turn rate is speed over radius, so a faster walk needs a wider turn."""
    slow = walking.turn_lateral(1.0, spec)
    fast = walking.turn_lateral(1.5, spec)
    assert slow < fast
    limit = math.radians(spec["pedestrians"]["route"]["max_turn_rate_deg_s"])
    for speed, width in ((1.0, slow), (1.5, fast)):
        assert 2.0 * speed / width <= limit + 1.0e-9


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def _proxies(count: int) -> list[dict]:
    """A stand-in population: slots and nothing else."""
    return [{"slot": f"district_a__slot_{index:03d}"} for index in range(1, count + 1)]


def test_the_walker_count_follows_the_declared_fraction(spec: dict) -> None:
    """Thirty per cent of eighty is twenty-four, by half-up rounding on integers."""
    assert walking.walker_count(80, spec) == 24
    assert walking.walker_count(0, spec) == 0


def test_the_walker_count_respects_its_own_ceiling(spec: dict) -> None:
    """A very large population still cannot walk more than the declared maximum."""
    assert walking.walker_count(10_000, spec) == spec["pedestrians"]["max_moving"]


def test_selection_is_a_property_of_the_slot_not_the_population(spec: dict) -> None:
    """A city that grows keeps every walker it had."""
    small = walking.selection_order(_proxies(20), spec)
    large = walking.selection_order(_proxies(40), spec)
    kept = [entry for entry in large if entry["slot"] in {item["slot"] for item in small}]
    assert [entry["slot"] for entry in kept] == [entry["slot"] for entry in small]


def test_selection_does_not_depend_on_input_order(spec: dict) -> None:
    """The order somebody listed the proxies in is not a policy."""
    proxies = _proxies(30)
    assert walking.selection_order(proxies, spec) == walking.selection_order(
        list(reversed(proxies)), spec
    )


def test_selection_is_deterministic(spec: dict) -> None:
    """The same city always sends the same people walking."""
    proxies = _proxies(30)
    assert [entry["slot"] for entry in walking.selection_order(proxies, spec)] == [
        entry["slot"] for entry in walking.selection_order(proxies, spec)
    ]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


CORRIDOR = {
    "family": "corridor_loop",
    "path": [(0.0, 0.0), (40.0, 0.0)],
    "station": 12.0,
    "closed": False,
    "lateral": 1.0,
    "anchor_offset": 2.0,
}
"""A straight synthetic corridor. STRUCTURAL TEST GEOMETRY ONLY."""


def test_a_route_is_a_closed_loop() -> None:
    """Nothing is corrected at the end; the shape of the route closes it."""
    loop = walking.build_route_loop(CORRIDOR, 4.0, 1.0, "outward", 0.15)
    assert math.dist(loop[0], loop[-1]) < 1.0e-9


def test_a_route_starts_at_the_corridor_station() -> None:
    """The anchor is a point ON the loop, which is what makes the walk return."""
    loop = walking.build_route_loop(CORRIDOR, 4.0, 1.0, "outward", 0.15)
    assert loop[0] == pytest.approx((12.0, 0.0))


def test_a_longer_excursion_makes_a_longer_loop() -> None:
    """Loop length grows with excursion, which is what lets it be solved."""
    lengths = [
        walking.build_length(CORRIDOR, excursion, 1.0, "outward", 0.15)
        for excursion in (3.0, 4.0, 5.0)
    ]
    assert lengths == sorted(lengths)


def test_the_excursion_is_solved_to_hit_the_length_the_speed_demands() -> None:
    """Speed, route length and gait are one set of numbers, not three settings."""
    excursion, loop = walking.solve_excursion(CORRIDOR, 11.5, 1.0, "outward", 0.15, (3.0, 6.0))
    assert 3.0 <= excursion <= 6.0
    assert walking.polyline_length(loop) == pytest.approx(11.5, abs=1.0e-4)


def test_an_impossible_target_length_is_refused() -> None:
    """A loop the bounds cannot reach is refused, never stretched."""
    with pytest.raises(walking.PedestrianMobilityError):
        walking.solve_excursion(CORRIDOR, 2.0, 1.0, "outward", 0.15, (3.0, 6.0))
    with pytest.raises(walking.PedestrianMobilityError):
        walking.solve_excursion(CORRIDOR, 900.0, 1.0, "outward", 0.15, (3.0, 6.0))


def test_a_turnaround_never_snaps() -> None:
    """Every step of the loop turns by a bounded amount; there is no reversal."""
    loop = walking.build_route_loop(CORRIDOR, 4.0, 1.1, "outward", 0.05)
    headings = [
        math.atan2(b[1] - a[1], b[0] - a[0])
        for a, b in zip(loop, loop[1:], strict=False)
        if math.dist(a, b) > 1.0e-9
    ]
    for first, second in zip(headings, headings[1:], strict=False):
        turn = abs(math.atan2(math.sin(second - first), math.cos(second - first)))
        assert turn < math.radians(60.0)


def test_the_turn_rate_guard_refuses_a_pivot(spec: dict) -> None:
    """A turnaround too tight for the speed is refused as a number."""
    loop = walking.build_route_loop(CORRIDOR, 4.0, 0.2, "outward", 0.05)
    assert walking.turn_rate_violations(loop, 1.5, spec)


def test_shifting_the_anchor_keeps_it_on_the_loop() -> None:
    """The anchor may be at the start, middle or far end of the same track."""
    for share in (0.0, 0.5, 1.0):
        loop = walking.build_route_loop(CORRIDOR, 4.0, 1.0, "outward", 0.15, share)
        rotated = walking.rotate_loop_to(loop, (12.0, 0.0))
        assert math.dist(rotated[0], (12.0, 0.0)) < 0.05
        assert math.dist(rotated[0], rotated[-1]) < 1.0e-9


def test_reversing_a_corridor_keeps_the_anchor_where_it_was() -> None:
    """Walking the other way is the same corridor, entered from the other end."""
    reversed_corridor = walking.reversed_corridor(CORRIDOR)
    total = walking.polyline_length(CORRIDOR["path"])
    assert reversed_corridor["station"] == pytest.approx(total - CORRIDOR["station"])
    assert reversed_corridor["lateral"] == -CORRIDOR["lateral"]


def test_a_shift_never_runs_off_an_open_corridor() -> None:
    """A street has an end, and a shift may not ask for pavement before it."""
    shifted = walking.shifted_corridor(CORRIDOR, 30.0, 1.0)
    assert shifted["station"] >= 0.0


# ---------------------------------------------------------------------------
# Gait
# ---------------------------------------------------------------------------


def test_the_gait_closes_on_whole_strides(spec: dict, timeline: dict) -> None:
    """A loop that closed mid-stride would jump at the seam."""
    for identity in IDENTITIES:
        cycle = _cycle(identity, spec, timeline)
        assert cycle["cycles"] >= 1
        assert cycle["effective_stride"] * cycle["cycles"] == pytest.approx(
            walking.walking_speed(figure_kit.figure_dimensions(identity)["height"], spec)
            * timeline["pedestrian_cycle_seconds"],
            abs=1.0e-5,
        )


def test_the_stride_stays_inside_its_declared_tolerance(spec: dict, timeline: dict) -> None:
    """Rounding to whole strides may not turn a walk into a march."""
    for identity in IDENTITIES:
        cycle = _cycle(identity, spec, timeline)
        assert cycle["stride_drift"] <= spec["pedestrians"]["gait"]["stride_tolerance"]


def test_the_leg_swing_is_derived_from_the_stride(spec: dict, timeline: dict) -> None:
    """``stride = 4 L sin(swing)`` -- so a walker cannot be made to skate."""
    for identity in IDENTITIES:
        cycle = _cycle(identity, spec, timeline)
        reach = 4.0 * cycle["leg_length"] * math.sin(cycle["leg_swing"])
        assert reach == pytest.approx(cycle["effective_stride"], abs=1.0e-6)
        assert cycle["leg_swing_deg"] <= spec["pedestrians"]["gait"]["leg_swing_max_deg"]


def test_a_stride_beyond_the_bodys_reach_is_refused(spec: dict) -> None:
    """A leg cannot cover a stride longer than four times its own length.

    Reached by asking for an absurd stride FACTOR rather than an absurd route:
    the cycle count is rounded from the route, so a long route simply takes more
    strides and the effective stride stays near the natural one. The only way to
    demand an impossible step is to declare one.
    """
    greedy = {
        **spec,
        "pedestrians": {
            **spec["pedestrians"],
            "gait": {**spec["pedestrians"]["gait"], "stride_factor": 6.0},
        },
    }
    with pytest.raises(walking.PedestrianMobilityError):
        walking.gait_cycles(11.5, IDENTITIES[0], greedy)


def test_the_gait_mesh_matches_the_locked_body_vertex_for_vertex(
    spec: dict, timeline: dict
) -> None:
    """Shape keys must line up with the mesh, or the body turns inside out."""
    for identity in IDENTITIES:
        cycle = _cycle(identity, spec, timeline)
        base = figure_kit.figure_mesh(identity)["vertices"]
        for shape in walking.gait_shapes(identity, cycle, spec):
            assert len(shape) == len(base)


def test_only_the_limbs_and_the_whole_body_lift_ever_move(spec: dict, timeline: dict) -> None:
    """A gait that moved the head independently would be a different body."""
    for identity in IDENTITIES:
        cycle = _cycle(identity, spec, timeline)
        travel = walking.gait_travel(identity, cycle, spec)
        limbs = {
            name: value
            for name, value in travel.items()
            if any(part in name for part in ("arm", "leg", "foot"))
        }
        others = {name: value for name, value in travel.items() if name not in limbs}
        assert min(limbs.values()) >= spec["pedestrians"]["gait"]["min_limb_travel"]
        assert max(limbs.values()) > max(others.values()) if others else True


def test_the_torso_travels_only_as_far_as_the_pelvis_drops(spec: dict, timeline: dict) -> None:
    """The bob is a consequence of the stance leg, and it stays small."""
    for identity in IDENTITIES:
        cycle = _cycle(identity, spec, timeline)
        travel = walking.gait_travel(identity, cycle, spec)
        assert travel["torso"] < 0.12


def test_opposite_arm_and_leg_swing(spec: dict, timeline: dict) -> None:
    """The cue a viewer reads as walking rather than marching."""
    for identity in IDENTITIES:
        cycle = _cycle(identity, spec, timeline)
        for phase in (0.05, 0.2, 0.4, 0.7, 0.9):
            angles = walking.gait_angles(phase, cycle)
            assert angles["left_hip"] * angles["right_hip"] <= 0.0
            assert angles["left_hip"] * angles["left_shoulder"] <= 0.0


def test_no_foot_ever_goes_below_the_ground(spec: dict, timeline: dict) -> None:
    """The whole figure is lifted so its lowest foot rests exactly on zero."""
    for identity in IDENTITIES:
        cycle = _cycle(identity, spec, timeline)
        phases = spec["pedestrians"]["gait"]["phases"]
        for index in range(phases):
            primitives = walking.gait_primitives(identity, index / phases, cycle, spec)
            feet = [
                vertex[2]
                for primitive in primitives
                if primitive["name"].endswith("_foot")
                for vertex in primitive["vertices"]
            ]
            assert min(feet) == pytest.approx(0.0, abs=1.0e-9)


def test_the_body_rises_and_falls_over_its_stance_leg(spec: dict, timeline: dict) -> None:
    """A figure held at a constant height while its legs swing would float."""
    identity = IDENTITIES[0]
    cycle = _cycle(identity, spec, timeline)
    phases = spec["pedestrians"]["gait"]["phases"]
    heights = []
    for index in range(phases):
        primitives = walking.gait_primitives(identity, index / phases, cycle, spec)
        torso = next(entry for entry in primitives if entry["name"] == "torso")
        heights.append(max(vertex[2] for vertex in torso["vertices"]))
    assert max(heights) - min(heights) > 0.01


def test_a_split_sleeve_arm_articulates_as_one_chain(spec: dict, timeline: dict) -> None:
    """The sleeve's elbow and the forearm's elbow are the same joint."""
    identity = IDENTITIES[1]
    cycle = _cycle(identity, spec, timeline)
    primitives = {
        entry["name"]: entry for entry in walking.gait_primitives(identity, 0.25, cycle, spec)
    }
    assert "left_upper_arm" in primitives and "left_forearm" in primitives
    upper = primitives["left_upper_arm"]["vertices"][-figure_kit.ARM_SIDES :]
    lower = primitives["left_forearm"]["vertices"][: figure_kit.ARM_SIDES]
    for a, b in zip(upper, lower, strict=True):
        assert math.dist(a, b) < 0.02


def test_every_vocabulary_body_can_walk(spec: dict, timeline: dict) -> None:
    """No age, stature or build the kit can dress may be unable to stride.

    The presence plan draws walkers from the whole vocabulary, so a body the
    gait arithmetic refuses is a mobility plan that fails at derivation time on
    a world that validated. Every age x stature x build is asked for the gait
    its own speed demands, and the two invariants the arithmetic rests on are
    measured per body: the legs it swings are equal at idle -- the kit builds
    the right leg as the left's mirror, and a walker on uneven legs would limp
    at the seam of every cycle -- and the leg is a plausible fraction of the
    body, because a stride formula fed a leg outside 0.42 to 0.60 of height is
    solving a pendulum no human silhouette owns.
    """
    for age, stature, build in itertools.product(
        figure_kit.AGE_PRESENTATIONS, figure_kit.STATURES, figure_kit.BUILDS
    ):
        identity = {
            "age_presentation": age,
            "presentation": "unspecified",
            "stature": stature,
            "build": build,
            "hair": "short",
            "facial_hair": "none",
            "face": "a",
            "clothing": "shirt",
            "palette": "slate",
            "complexion": "c1",
            "hair_tone": "h1",
            "pose": "idle",
        }
        height = figure_kit.figure_dimensions(identity)["height"]
        speed = walking.walking_speed(height, spec)
        length = mobility_spec.pedestrian_route_length(speed, timeline)
        cycle = walking.gait_cycles(length, identity, spec)
        chains = walking.body_chains(identity)
        left = chains["left_leg"]["joints"]
        right = chains["right_leg"]["joints"]
        assert math.dist(left[0], left[2]) == pytest.approx(
            math.dist(right[0], right[2]), abs=1.0e-9
        ), f"a {stature} {build} {age} stands on unequal legs"
        ratio = cycle["leg_length"] / height
        assert 0.42 <= ratio <= 0.60, (
            f"a {stature} {build} {age} walks on legs {ratio:.4f} of its height"
        )


def test_the_gait_is_deterministic(spec: dict, timeline: dict) -> None:
    """The same body and the same route always walk the same way."""
    for identity in IDENTITIES:
        cycle = _cycle(identity, spec, timeline)
        assert walking.gait_digest(identity, cycle, spec) == walking.gait_digest(
            identity, cycle, spec
        )


def test_two_different_bodies_walk_differently(spec: dict, timeline: dict) -> None:
    """A gait is a deformation of a particular body, not a shared animation."""
    digests = {
        walking.gait_digest(identity, _cycle(identity, spec, timeline), spec)
        for identity in IDENTITIES
    }
    assert len(digests) == len(IDENTITIES)
