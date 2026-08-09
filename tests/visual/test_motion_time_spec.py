"""Contract tests for the Motion & Time Spec V1.

Pure pytest -- no Blender. The spec is presentation architecture, so these
tests are mostly adversarial: a malformed timeline, a reversed window, a
boolean where a frame belongs, or an easing nobody declared must all be
refusals rather than quiet defaults, because every one of them would
otherwise become a wrong frame in a finished film.
"""

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"
CONFIG_PATH = REPO_ROOT / "visual" / "blender" / "config" / "motion_time_v1.json"


def _load(name: str):
    """Import one pure visual module the same way Blender does: by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


mts = _load("motion_time_spec")


@pytest.fixture(name="document")
def document_fixture() -> dict:
    """The canonical motion spec as a mutable raw JSON document."""
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(name="spec")
def spec_fixture() -> dict:
    """The canonical motion spec, loaded and resolved."""
    return mts.load_motion_time_spec(CONFIG_PATH)


def write(tmp_path: Path, document: dict) -> Path:
    """Write one candidate spec document and return its path."""
    path = tmp_path / "motion.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def refuses(tmp_path: Path, document: dict, fragment: str) -> None:
    """Assert the spec loader refuses this document for the stated reason."""
    with pytest.raises(mts.MotionSpecError) as error:
        mts.load_motion_time_spec(write(tmp_path, document))
    assert fragment in str(error.value)


def test_the_canonical_spec_resolves_its_three_phases(spec) -> None:
    """START HOLD, TRANSITION and END HOLD are derived once, consistently."""
    timeline = spec["timeline"]
    assert timeline["start_frame"] == 1
    assert timeline["transition_start"] == 25
    assert timeline["transition_end"] == 145
    assert timeline["end_frame"] == 193
    assert timeline["fps"] == 24
    assert timeline["duration_seconds"] == pytest.approx(8.0)
    assert (
        timeline["end_frame"] - timeline["start_frame"]
        == timeline["start_hold_frames"]
        + timeline["transition_frames"]
        + timeline["end_hold_frames"]
    )


def test_every_declared_channel_is_supported_and_unique(spec) -> None:
    """The spec may only enable channels the plan layer knows how to tell."""
    assert set(spec["channels"]) <= set(mts.SUPPORTED_CHANNELS)
    assert len(spec["channels"]) == len(set(spec["channels"]))


def test_proof_samples_resolve_to_strictly_increasing_frames(spec) -> None:
    """A contact sheet needs distinct moments in order, not a repeated frame."""
    frames = [sample["frame"] for sample in spec["proof_samples"]]
    assert frames == sorted(frames)
    assert len(set(frames)) == len(frames)
    assert frames[0] == spec["timeline"]["start_frame"]
    assert frames[-1] == spec["timeline"]["end_frame"]


def test_a_wrong_format_or_version_is_refused(tmp_path, document) -> None:
    """A spec that is not this format is never coerced into being one."""
    wrong = copy.deepcopy(document)
    wrong["format"] = "something_else"
    refuses(tmp_path, wrong, "format must be")
    wrong = copy.deepcopy(document)
    wrong["schema_version"] = 2
    refuses(tmp_path, wrong, "schema_version must be")


def test_a_boolean_schema_version_is_not_version_one(tmp_path, document) -> None:
    """``True == 1`` in Python; a spec that says ``true`` is still malformed."""
    wrong = copy.deepcopy(document)
    wrong["schema_version"] = True
    refuses(tmp_path, wrong, "schema_version must be")


def test_unknown_top_level_fields_are_refused(tmp_path, document) -> None:
    """A misspelled section would silently do nothing; it is refused instead."""
    wrong = copy.deepcopy(document)
    wrong["chanels"] = []
    refuses(tmp_path, wrong, "unknown top-level fields")


def test_unknown_and_missing_timeline_fields_are_refused(tmp_path, document) -> None:
    """Every phase length is declared explicitly, and only those."""
    wrong = copy.deepcopy(document)
    wrong["timeline"]["frames_per_second"] = 24
    refuses(tmp_path, wrong, "unknown fields")
    wrong = copy.deepcopy(document)
    del wrong["timeline"]["end_frame"]
    refuses(tmp_path, wrong, "missing fields")


@pytest.mark.parametrize("field", ["fps", "start_frame", "transition_frames", "end_frame"])
def test_a_boolean_where_a_frame_belongs_is_refused(tmp_path, document, field) -> None:
    """``True`` must never quietly become frame 1 or 1 fps."""
    wrong = copy.deepcopy(document)
    wrong["timeline"][field] = True
    refuses(tmp_path, wrong, "must be an integer, not a boolean")


@pytest.mark.parametrize("field", ["fps", "start_frame", "transition_frames"])
def test_a_float_where_a_frame_belongs_is_refused(tmp_path, document, field) -> None:
    """Half a frame does not exist; the spec says so rather than rounding."""
    wrong = copy.deepcopy(document)
    wrong["timeline"][field] = 24.5
    refuses(tmp_path, wrong, "must be an integer")


def test_a_zero_or_negative_frame_rate_is_refused(tmp_path, document) -> None:
    """A timeline with no frame rate has no time in it."""
    for value in (0, -24):
        wrong = copy.deepcopy(document)
        wrong["timeline"]["fps"] = value
        refuses(tmp_path, wrong, "timeline fps must be within")


def test_a_negative_start_frame_is_refused(tmp_path, document) -> None:
    """Frames run forward from zero."""
    wrong = copy.deepcopy(document)
    wrong["timeline"]["start_frame"] = -1
    wrong["timeline"]["end_frame"] = 191
    refuses(tmp_path, wrong, "start_frame must be within")


def test_a_zero_length_transition_is_refused(tmp_path, document) -> None:
    """A transition of no frames cannot show anything transitioning."""
    wrong = copy.deepcopy(document)
    wrong["timeline"]["transition_frames"] = 0
    wrong["timeline"]["end_frame"] = 73
    refuses(tmp_path, wrong, "transition_frames must be within")


@pytest.mark.parametrize("field", ["start_hold_frames", "end_hold_frames"])
def test_a_zero_length_hold_is_refused(tmp_path, document, field) -> None:
    """An endpoint the film never rests on is not an endpoint you can prove."""
    wrong = copy.deepcopy(document)
    removed = wrong["timeline"][field]
    wrong["timeline"][field] = 0
    wrong["timeline"]["end_frame"] -= removed
    refuses(tmp_path, wrong, f"{field} must be within")


def test_an_end_frame_that_disagrees_with_its_phases_is_refused(tmp_path, document) -> None:
    """The declared end and the summed phases must be the same number."""
    wrong = copy.deepcopy(document)
    wrong["timeline"]["end_frame"] = 200
    refuses(tmp_path, wrong, "disagrees with its own phases")


def test_an_unknown_channel_is_refused(tmp_path, document) -> None:
    """A channel nobody implemented would animate nothing, silently."""
    wrong = copy.deepcopy(document)
    wrong["channels"][0]["channel"] = "gate_mechanism"
    refuses(tmp_path, wrong, "unsupported channel")


def test_a_duplicated_channel_is_refused(tmp_path, document) -> None:
    """Two policies for one channel is two answers to one question."""
    wrong = copy.deepcopy(document)
    wrong["channels"].append(copy.deepcopy(wrong["channels"][0]))
    refuses(tmp_path, wrong, "twice")


def test_an_unknown_channel_field_is_refused(tmp_path, document) -> None:
    """A misspelled policy field is a policy that never took effect."""
    wrong = copy.deepcopy(document)
    wrong["channels"][0]["easing"] = "smoothstep"
    refuses(tmp_path, wrong, "unknown fields")


@pytest.mark.parametrize("field,value", [("interpolation", "bounce"), ("strategy", "random")])
def test_an_undeclared_easing_or_strategy_is_refused(tmp_path, document, field, value) -> None:
    """Blender's defaults never get to decide this project's motion."""
    wrong = copy.deepcopy(document)
    wrong["channels"][0][field] = value
    refuses(tmp_path, wrong, f"must declare {'an' if field == 'interpolation' else 'a'} {field}")


@pytest.mark.parametrize("window", [[0.6, 0.2], [0.4, 0.4], [-0.1, 0.5], [0.5, 1.4]])
def test_a_reversed_empty_or_out_of_range_window_is_refused(tmp_path, document, window) -> None:
    """A channel window is a real forward interval inside the transition."""
    wrong = copy.deepcopy(document)
    wrong["channels"][0]["window"] = window
    with pytest.raises(mts.MotionSpecError):
        mts.load_motion_time_spec(write(tmp_path, wrong))


def test_a_member_span_wider_than_its_window_is_refused(tmp_path, document) -> None:
    """A staged member cannot occupy more time than the channel owns."""
    wrong = copy.deepcopy(document)
    staged = next(entry for entry in wrong["channels"] if entry["strategy"] == "staged")
    staged["member_span"] = 1.0
    refuses(tmp_path, wrong, "exceeds its own window span")


def test_a_together_channel_may_not_narrow_its_members(tmp_path, document) -> None:
    """``together`` means every member shares the whole window, by definition."""
    wrong = copy.deepcopy(document)
    together = next(entry for entry in wrong["channels"] if entry["strategy"] == "together")
    together["member_span"] = 0.01
    refuses(tmp_path, wrong, "narrower than its window")


def test_a_step_channel_must_not_claim_to_be_sampled(tmp_path, document) -> None:
    """A step has two keys; asking for eight samples of it is a contradiction."""
    wrong = copy.deepcopy(document)
    step = next(entry for entry in wrong["channels"] if entry["interpolation"] == "step")
    step["samples"] = 8
    refuses(tmp_path, wrong, "must declare samples 1")


@pytest.mark.parametrize("samples", [0, -1, 65, True])
def test_a_malformed_sample_count_is_refused(tmp_path, document, samples) -> None:
    """Sampling density is bounded, integral, and never a boolean."""
    wrong = copy.deepcopy(document)
    smooth = next(entry for entry in wrong["channels"] if entry["interpolation"] == "smoothstep")
    smooth["samples"] = samples
    with pytest.raises(mts.MotionSpecError):
        mts.load_motion_time_spec(write(tmp_path, wrong))


@pytest.mark.parametrize("rise", [-1.0, float("nan"), float("inf"), True])
def test_a_malformed_rise_is_refused(tmp_path, document, rise) -> None:
    """A reveal cannot lift an object by NaN metres."""
    wrong = copy.deepcopy(document)
    wall = next(entry for entry in wrong["channels"] if entry["channel"] == "wall_presence")
    wall["rise_metres"] = rise
    path = tmp_path / "motion.json"
    path.write_text(json.dumps(wrong, allow_nan=True), encoding="utf-8")
    with pytest.raises(mts.MotionSpecError):
        mts.load_motion_time_spec(path)


def test_an_empty_channel_or_proof_list_is_refused(tmp_path, document) -> None:
    """A spec that enables nothing and proves nothing is not a spec."""
    wrong = copy.deepcopy(document)
    wrong["channels"] = []
    refuses(tmp_path, wrong, "non-empty channels list")
    wrong = copy.deepcopy(document)
    wrong["proof_samples"] = []
    refuses(tmp_path, wrong, "non-empty proof_samples list")


def test_duplicate_or_unordered_proof_samples_are_refused(tmp_path, document) -> None:
    """Two frames with one name, or a sheet that runs backwards, are refused."""
    wrong = copy.deepcopy(document)
    wrong["proof_samples"][1]["name"] = "start"
    refuses(tmp_path, wrong, "twice")
    wrong = copy.deepcopy(document)
    wrong["proof_samples"][1]["position"] = 0.9
    refuses(tmp_path, wrong, "strictly increasing frames")


def test_interpolation_is_exact_at_both_ends() -> None:
    """No easing is allowed to overshoot, undershoot, or drift at an endpoint."""
    for kind in mts.INTERPOLATIONS:
        assert mts.interpolate(kind, 3.0, 9.0, 0.0) == 3.0
        assert mts.interpolate(kind, 3.0, 9.0, 1.0) == 9.0


def test_smoothstep_is_the_documented_curve() -> None:
    """``3t^2 - 2t^3``: symmetric, monotonic, and exactly half-way at half-way."""
    assert mts.interpolate("smoothstep", 0.0, 1.0, 0.5) == pytest.approx(0.5)
    assert mts.interpolate("smoothstep", 0.0, 1.0, 0.25) == pytest.approx(0.15625)
    values = [mts.interpolate("smoothstep", 0.0, 1.0, i / 20.0) for i in range(21)]
    assert values == sorted(values)


def test_a_step_holds_until_its_very_end() -> None:
    """A state change swaps once; it does not creep."""
    assert mts.interpolate("step", 0.0, 1.0, 0.999) == 0.0
    assert mts.interpolate("step", 0.0, 1.0, 1.0) == 1.0


@pytest.mark.parametrize("position", [-0.01, 1.01, float("nan"), True])
def test_an_impossible_interpolation_position_is_refused(position) -> None:
    """Positions live in [0, 1]; a boolean is not a position."""
    with pytest.raises(mts.MotionSpecError):
        mts.interpolate("linear", 0.0, 1.0, position)


def test_an_unknown_interpolation_is_refused() -> None:
    """There are exactly three easings in this project."""
    with pytest.raises(mts.MotionSpecError):
        mts.interpolate("elastic", 0.0, 1.0, 0.5)


def test_one_member_always_owns_the_whole_window(spec) -> None:
    """A single wall, a single law: staging is meaningless, so it is skipped."""
    for policy in spec["channels"].values():
        window = mts.channel_frames(policy, spec["timeline"])
        assert mts.member_window(policy, spec["timeline"], 0, 1) == window


def test_staged_members_are_evenly_distributed_and_ordered(spec) -> None:
    """Member N always starts no earlier than member N-1, and all fit inside."""
    policy = spec["channels"]["wall_presence"]
    window = mts.channel_frames(policy, spec["timeline"])
    windows = [mts.member_window(policy, spec["timeline"], index, 12) for index in range(12)]
    starts = [start for start, _ in windows]
    assert starts == sorted(starts)
    assert windows[0][0] == window[0]
    assert windows[-1][1] == window[1]
    for start, end in windows:
        assert window[0] <= start < end <= window[1]


def test_a_member_that_cannot_fit_is_refused(spec) -> None:
    """Widening the span past the window is a spec error, not a squeeze."""
    with pytest.raises(mts.MotionSpecError):
        mts.staged_frames((10, 20), 30, 0, 4, staged=True)


@pytest.mark.parametrize("index,count", [(-1, 4), (4, 4), (0, 0), (True, 4), (0, True)])
def test_a_malformed_member_index_is_refused(index, count) -> None:
    """Booleans and out-of-range indices never silently pick member zero."""
    with pytest.raises(mts.MotionSpecError):
        mts.staged_frames((10, 40), 5, index, count, staged=True)


def test_frame_at_maps_the_transition_not_the_whole_timeline(spec) -> None:
    """Normalised channel positions address the TRANSITION, never the holds."""
    timeline = spec["timeline"]
    assert mts.frame_at(timeline, 0.0) == timeline["transition_start"]
    assert mts.frame_at(timeline, 1.0) == timeline["transition_end"]
    assert mts.frame_at(timeline, 0.5) == 85


def test_requiring_an_undeclared_channel_is_refused(spec) -> None:
    """A plan cannot use a channel the presentation contract never enabled."""
    with pytest.raises(mts.MotionSpecError) as error:
        mts.require_channel(spec, "district_glazing_v2")
    assert "not declared" in str(error.value)
