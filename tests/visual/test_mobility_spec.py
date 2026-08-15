"""Contract tests for the Daily Life Mobility Spec V1.

Pure pytest -- no Blender. Every document here is built in-test from the
canonical spec and then broken on purpose, so the suite proves the REFUSALS
rather than that one good file loads.

The rules under test are the ones that keep a presentation policy honest: a
malformed document is refused rather than defaulted, a band that is reversed or
empty is refused rather than sorted, a lane no buildable vehicle fits inside is
refused rather than narrowed, and the timeline is READ from the locked Phase 17
spec rather than restated here.
"""

import copy
import importlib
import json
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


mobility_spec = _load("mobility_spec")
motion_time_spec = _load("motion_time_spec")
vehicle_kit = _load("vehicle_kit")

SPEC_PATH = CONFIG_DIR / "daily_life_mobility_v1.json"
MOTION_PATH = CONFIG_DIR / "motion_time_v1.json"


@pytest.fixture(name="document")
def document_fixture() -> dict:
    """The canonical spec as raw JSON, ready to be broken."""
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture(name="resolved", scope="module")
def resolved_fixture() -> dict:
    """The canonical spec, loaded and validated once."""
    return mobility_spec.load_daily_life_mobility_spec(SPEC_PATH)


def _write(tmp_path: Path, document: dict) -> Path:
    """Write one candidate document out for the loader to read."""
    path = tmp_path / "mobility.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _refuses(tmp_path: Path, document: dict, fragment: str = "") -> str:
    """Assert the loader refuses a document, and return why."""
    with pytest.raises(mobility_spec.MobilitySpecError) as error:
        mobility_spec.load_daily_life_mobility_spec(_write(tmp_path, document))
    message = str(error.value)
    if fragment:
        assert fragment in message, message
    return message


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_the_canonical_spec_loads(resolved: dict) -> None:
    """The shipped spec is a well-formed mobility spec."""
    assert resolved["format"] == mobility_spec.DAILY_LIFE_MOBILITY_FORMAT
    assert resolved["schema_version"] == mobility_spec.DAILY_LIFE_MOBILITY_SCHEMA_VERSION
    assert resolved["mobility_seed"].strip()


def test_a_wrong_format_is_refused(tmp_path: Path, document: dict) -> None:
    """A document that is not a mobility spec is refused by name."""
    document["format"] = "living_diorama_population_presence"
    _refuses(tmp_path, document, "format must be")


def test_a_wrong_schema_version_is_refused(tmp_path: Path, document: dict) -> None:
    """V1 refuses to guess what a later schema meant."""
    document["schema_version"] = 2
    _refuses(tmp_path, document, "schema_version must be")


def test_a_boolean_schema_version_is_refused(tmp_path: Path, document: dict) -> None:
    """``True`` equals 1 in Python and must not pass for version one."""
    document["schema_version"] = True
    _refuses(tmp_path, document, "schema_version must be")


def test_an_unknown_top_level_field_is_refused(tmp_path: Path, document: dict) -> None:
    """A field nobody reads is a policy nobody applied."""
    document["traffic_demand"] = 4
    _refuses(tmp_path, document, "unknown field")


def test_a_missing_section_is_refused(tmp_path: Path, document: dict) -> None:
    """A missing section must not silently become a default."""
    document.pop("vehicles")
    _refuses(tmp_path, document, "missing field")


def test_an_empty_seed_is_refused(tmp_path: Path, document: dict) -> None:
    """Determinism starts at the seed, so a blank one is refused."""
    document["mobility_seed"] = "   "
    _refuses(tmp_path, document, "mobility_seed")


# ---------------------------------------------------------------------------
# Cycle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["pedestrian_cycles", "vehicle_cycles", "collision_frame_stride"])
def test_a_zero_cycle_count_is_refused(tmp_path: Path, document: dict, field: str) -> None:
    """Zero cycles is not a slower cycle, it is no cycle at all."""
    document["cycle"][field] = 0
    _refuses(tmp_path, document, field)


def test_a_boolean_cycle_count_is_refused(tmp_path: Path, document: dict) -> None:
    """A spec that says ``true`` where a count belongs is malformed."""
    document["cycle"]["vehicle_cycles"] = True
    _refuses(tmp_path, document, "integer")


def test_an_unknown_cycle_field_is_refused(tmp_path: Path, document: dict) -> None:
    """The cycle section is closed."""
    document["cycle"]["frames"] = 193
    _refuses(tmp_path, document, "unknown field")


# ---------------------------------------------------------------------------
# Pedestrians
# ---------------------------------------------------------------------------


def test_a_moving_fraction_of_one_is_refused(tmp_path: Path, document: dict) -> None:
    """A city where everybody walks has no stationary presence left."""
    document["pedestrians"]["moving_fraction"] = 1.0
    _refuses(tmp_path, document, "moving_fraction")


def test_a_moving_fraction_above_one_is_refused(tmp_path: Path, document: dict) -> None:
    """A fraction is a fraction."""
    document["pedestrians"]["moving_fraction"] = 1.4
    _refuses(tmp_path, document, "within [0, 1]")


def test_a_maximum_below_the_minimum_is_refused(tmp_path: Path, document: dict) -> None:
    """Contradictory limits are refused rather than reconciled."""
    document["pedestrians"]["min_moving"] = 9
    document["pedestrians"]["max_moving"] = 4
    _refuses(tmp_path, document, "below min_moving")


def test_a_reversed_speed_band_is_refused(tmp_path: Path, document: dict) -> None:
    """A band whose maximum is under its minimum is not sorted, it is refused."""
    document["pedestrians"]["speed"]["min"] = 2.0
    document["pedestrians"]["speed"]["max"] = 1.0
    _refuses(tmp_path, document, "reversed or empty")


def test_a_base_speed_outside_its_own_band_is_refused(tmp_path: Path, document: dict) -> None:
    """A default nobody may reach is an incoherent default."""
    document["pedestrians"]["speed"]["base_speed"] = 9.0
    _refuses(tmp_path, document, "outside its own band")


def test_reversed_excursion_bounds_are_refused(tmp_path: Path, document: dict) -> None:
    """An impossible route-length band is refused."""
    document["pedestrians"]["route"]["excursion_min"] = 6.0
    document["pedestrians"]["route"]["excursion_max"] = 3.0
    _refuses(tmp_path, document, "excursion bounds are reversed")


def test_a_negative_lateral_offset_is_refused(tmp_path: Path, document: dict) -> None:
    """A turnaround with no width is not a turnaround."""
    document["pedestrians"]["route"]["lateral_offset"] = -0.4
    _refuses(tmp_path, document, "lateral_offset")


def test_a_speed_ladder_that_does_not_start_at_one_is_refused(
    tmp_path: Path, document: dict
) -> None:
    """A walker's own pace is tried first; slowing down is the fallback."""
    document["pedestrians"]["route"]["speed_ladder"] = [0.9, 0.8]
    _refuses(tmp_path, document, "must begin at 1.0")


def test_a_speed_ladder_that_does_not_decrease_is_refused(tmp_path: Path, document: dict) -> None:
    """A ladder that goes up would try the same route twice and call it two."""
    document["pedestrians"]["route"]["speed_ladder"] = [1.0, 0.8, 0.9]
    _refuses(tmp_path, document, "strictly decrease")


def test_duplicate_anchor_positions_are_refused(tmp_path: Path, document: dict) -> None:
    """Two identical shares would try the same route twice."""
    document["pedestrians"]["route"]["anchor_positions"] = [0.0, 0.5, 0.5]
    _refuses(tmp_path, document, "distinct")


def test_an_odd_gait_phase_count_is_refused(tmp_path: Path, document: dict) -> None:
    """A stride has two identical halves; an odd count cannot express that."""
    document["pedestrians"]["gait"]["phases"] = 7
    _refuses(tmp_path, document, "even")


def test_too_few_gait_phases_are_refused(tmp_path: Path, document: dict) -> None:
    """Two poses is a metronome, not a walk."""
    document["pedestrians"]["gait"]["phases"] = 2
    _refuses(tmp_path, document, "phases")


def test_a_zero_stride_tolerance_is_refused(tmp_path: Path, document: dict) -> None:
    """A loop closes on whole strides, so the effective stride is never exact."""
    document["pedestrians"]["gait"]["stride_tolerance"] = 0.0
    _refuses(tmp_path, document, "stride_tolerance")


def test_a_quarter_turn_leg_swing_is_refused(tmp_path: Path, document: dict) -> None:
    """A leg that swings ninety degrees is not walking."""
    document["pedestrians"]["gait"]["leg_swing_max_deg"] = 95.0
    _refuses(tmp_path, document, "quarter turn")


def test_an_arm_that_leads_the_stride_is_refused(tmp_path: Path, document: dict) -> None:
    """An arm follows a stride; it does not lead it."""
    document["pedestrians"]["gait"]["arm_swing_ratio"] = 1.9
    _refuses(tmp_path, document, "arm_swing_ratio")


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------


def test_a_target_above_the_maximum_is_refused(tmp_path: Path, document: dict) -> None:
    """A spec must not ask for more than it allows itself."""
    document["vehicles"]["target_count"] = 40
    _refuses(tmp_path, document, "below target_count")


def test_an_unknown_driving_side_is_refused(tmp_path: Path, document: dict) -> None:
    """The convention is a declared policy, not a free string."""
    document["vehicles"]["driving_side"] = "middle"
    _refuses(tmp_path, document, "driving_side")


def test_a_corner_floor_above_its_target_is_refused(tmp_path: Path, document: dict) -> None:
    """A floor above the target would make the ladder run backwards."""
    document["vehicles"]["lane"]["corner_radius_min"] = 9.0
    _refuses(tmp_path, document, "corner_radius_min")


def test_a_corner_floor_inside_the_vehicle_is_refused(tmp_path: Path, document: dict) -> None:
    """A turn tighter than half the car has its own centre inside the car."""
    document["vehicles"]["lane"]["corner_radius"] = 0.9
    document["vehicles"]["lane"]["corner_radius_min"] = 0.5
    _refuses(tmp_path, document, "inside the vehicle")


def test_a_slot_pitch_shorter_than_a_vehicle_is_refused(tmp_path: Path, document: dict) -> None:
    """Two slots closer than one car long would overlap before anything moved."""
    document["vehicles"]["slot_pitch"] = 2.0
    _refuses(tmp_path, document, "not longer than the longest vehicle")


def test_a_body_clearance_the_pitch_cannot_meet_is_refused(tmp_path: Path, document: dict) -> None:
    """A clearance the spacing makes impossible is a contradiction, not a policy."""
    document["vehicles"]["body_clearance"] = 20.0
    _refuses(tmp_path, document, "body_clearance")


def test_an_unknown_archetype_is_refused(tmp_path: Path, document: dict) -> None:
    """The kit decides what a vehicle can be."""
    document["vehicles"]["archetypes"]["limousine"] = 1.0
    _refuses(tmp_path, document, "unknown archetype")


def test_a_missing_archetype_weight_is_refused(tmp_path: Path, document: dict) -> None:
    """Every archetype the kit builds must be weighted, even at zero."""
    document["vehicles"]["archetypes"].pop("van")
    _refuses(tmp_path, document, "must weight every archetype")


def test_a_single_enabled_archetype_is_refused(tmp_path: Path, document: dict) -> None:
    """Traffic made of one repeated car is a conveyor belt."""
    for name in vehicle_kit.ARCHETYPES[1:]:
        document["vehicles"]["archetypes"][name] = 0.0
    _refuses(tmp_path, document, "at least two archetypes")


def test_all_zero_archetype_weights_are_refused(tmp_path: Path, document: dict) -> None:
    """A vocabulary that offers nothing cannot be drawn from."""
    for name in vehicle_kit.ARCHETYPES:
        document["vehicles"]["archetypes"][name] = 0.0
    _refuses(tmp_path, document, "zero weight")


def test_a_layer_budget_below_the_target_is_refused(tmp_path: Path, document: dict) -> None:
    """A budget that cannot hold the traffic it asks for is incoherent."""
    document["vehicles"]["budget"]["layer_triangles"] = 100
    _refuses(tmp_path, document, "cannot hold target_count")


def test_an_absurd_rolling_radius_tolerance_is_refused(tmp_path: Path, document: dict) -> None:
    """Past a point a rolling radius stops being a tyre and becomes a wheel swap."""
    document["vehicles"]["rolling_radius_tolerance"] = 0.6
    _refuses(tmp_path, document, "rolling_radius_tolerance")


# ---------------------------------------------------------------------------
# Proof cameras
# ---------------------------------------------------------------------------


def test_every_required_camera_is_declared(resolved: dict) -> None:
    """The proof anchors are part of the contract, not of the render script."""
    assert set(resolved["proof"]["cameras"]) == set(mobility_spec.REQUIRED_MOBILITY_CAMERAS)


def test_a_missing_camera_is_refused(tmp_path: Path, document: dict) -> None:
    """A proof that cannot be framed is refused before it is rendered."""
    document["proof"]["cameras"].pop("CAM_P19_GAIT")
    _refuses(tmp_path, document, "camera CAM_P19_GAIT")


def test_an_unknown_camera_is_refused(tmp_path: Path, document: dict) -> None:
    """A camera nobody renders is a camera nobody checked."""
    document["proof"]["cameras"]["CAM_P19_EXTRA"] = document["proof"]["cameras"]["CAM_P19_CITY"]
    _refuses(tmp_path, document, "unknown camera")


def test_a_two_component_camera_location_is_refused(tmp_path: Path, document: dict) -> None:
    """A camera lives in three dimensions."""
    document["proof"]["cameras"]["CAM_P19_CITY"]["location"] = [1.0, 2.0]
    _refuses(tmp_path, document, "must be [x, y, z]")


# ---------------------------------------------------------------------------
# The timeline this cycle overlays
# ---------------------------------------------------------------------------


def test_the_mobility_cycle_reads_the_locked_phase17_timeline(resolved: dict) -> None:
    """Phase 19 invents no frames: the span comes from Phase 17's own spec."""
    motion = motion_time_spec.load_motion_time_spec(MOTION_PATH)
    timeline = mobility_spec.resolve_mobility_timeline(resolved, motion["timeline"])
    assert timeline["start_frame"] == motion["timeline"]["start_frame"]
    assert timeline["end_frame"] == motion["timeline"]["end_frame"]
    assert timeline["fps"] == motion["timeline"]["fps"]
    span = motion["timeline"]["end_frame"] - motion["timeline"]["start_frame"]
    assert timeline["frame_span"] == span


def test_a_malformed_timeline_is_refused(resolved: dict) -> None:
    """A timeline missing its own fields cannot carry a cycle."""
    with pytest.raises(mobility_spec.MobilitySpecError):
        mobility_spec.resolve_mobility_timeline(resolved, {"fps": 24, "start_frame": 1})


def test_a_reversed_timeline_is_refused(resolved: dict) -> None:
    """A span of zero frames has no cycle in it."""
    with pytest.raises(mobility_spec.MobilitySpecError):
        mobility_spec.resolve_mobility_timeline(
            resolved, {"fps": 24, "start_frame": 100, "end_frame": 100}
        )


def test_a_boolean_fps_is_refused(resolved: dict) -> None:
    """``True`` is an int and must not become one frame a second."""
    with pytest.raises(mobility_spec.MobilitySpecError):
        mobility_spec.resolve_mobility_timeline(
            resolved, {"fps": True, "start_frame": 1, "end_frame": 193}
        )


def test_the_route_length_is_the_speed_times_the_cycle(resolved: dict) -> None:
    """The loop contract, stated as arithmetic and checked as arithmetic."""
    motion = motion_time_spec.load_motion_time_spec(MOTION_PATH)
    timeline = mobility_spec.resolve_mobility_timeline(resolved, motion["timeline"])
    for speed in (1.0, 1.25, 1.5):
        assert mobility_spec.pedestrian_route_length(speed, timeline) == pytest.approx(
            speed * timeline["pedestrian_cycle_seconds"]
        )


def test_the_vehicle_length_band_follows_the_speed_band(resolved: dict) -> None:
    """A circuit outside the band cannot be closed at a legal speed."""
    motion = motion_time_spec.load_motion_time_spec(MOTION_PATH)
    timeline = mobility_spec.resolve_mobility_timeline(resolved, motion["timeline"])
    low, high = mobility_spec.vehicle_route_length_bounds(resolved, timeline)
    band = resolved["vehicles"]["speed"]
    assert low == pytest.approx(band["min"] * timeline["vehicle_cycle_seconds"])
    assert high == pytest.approx(band["max"] * timeline["vehicle_cycle_seconds"])


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_loading_twice_gives_the_same_document(resolved: dict) -> None:
    """The loader is a pure function of the file."""
    assert mobility_spec.load_daily_life_mobility_spec(SPEC_PATH) == resolved


def test_the_seed_generator_is_owned_by_its_identity(resolved: dict) -> None:
    """Two identities never share a draw, and one identity always repeats."""
    first = mobility_spec.mobility_seed(resolved, "vehicle", "slot_001").random()
    again = mobility_spec.mobility_seed(resolved, "vehicle", "slot_001").random()
    other = mobility_spec.mobility_seed(resolved, "vehicle", "slot_002").random()
    assert first == again
    assert first != other


def test_key_order_does_not_change_the_resolved_spec(tmp_path: Path, document: dict) -> None:
    """A spec is its values, not the order somebody typed them in."""
    shuffled = copy.deepcopy(document)
    shuffled["vehicles"] = dict(reversed(list(shuffled["vehicles"].items())))
    shuffled["pedestrians"] = dict(reversed(list(shuffled["pedestrians"].items())))
    assert mobility_spec.load_daily_life_mobility_spec(
        _write(tmp_path, shuffled)
    ) == mobility_spec.load_daily_life_mobility_spec(SPEC_PATH)
