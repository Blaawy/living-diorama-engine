"""Contract tests for the State Response Spec V1 loader.

Pure pytest -- no Blender. Every document here is built in-test from the
canonical spec and then broken on purpose, so the suite proves the REFUSALS
rather than that one good file happens to load.

The rules under test are the ones that keep a presentation contract honest: a
channel exists only where an authoritative field backs it, an unknown or
duplicated declaration is refused rather than resolved by evaluation order, a
window that runs backwards is refused rather than quietly swapped, a response
range that cannot widen is refused rather than allowed to make a moving signal
look still, and an air tint that codes a hue is refused rather than desaturated
into something the author never wrote.

The clock is the other subject. Phase 20 owns no frames: it borrows the locked
Phase 17 timeline and resolves normalized positions against it. So the timeline
and easing tests are cross-checked against ``motion_time_spec`` itself -- two
independently written helpers that agree on every position are a shared clock,
and one that only agrees with itself is a second clock wearing the first one's
name.
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


srs = _load("state_response_spec")
mts = _load("motion_time_spec")

SPEC_PATH = CONFIG_DIR / "state_response_v1.json"
MOTION_PATH = CONFIG_DIR / "motion_time_v1.json"

TOP_LEVEL_KEYS = ("format", "schema_version", "statement", "channels", "air", "record")
"""Exactly the sections a State Response Spec V1 document carries.

Restated here rather than imported from the loader's own frozenset, because a
test that read the module's key set would prove only that the module agrees
with itself about which sections it requires.
"""

NUMERIC_LOCATIONS = (
    "air/base_density",
    "air/rim_margin_metres",
    "air/ceiling_metres",
    "air/floor_density_fraction",
    "air/anisotropy",
    "air/tint/1",
    "record/origin/0",
    "record/arc_radius_metres",
    "record/arc_start_degrees",
    "record/arc_step_degrees",
    "record/stone_size_metres/2",
    "record/lift_metres",
    "channels/0/window/0",
    "channels/0/response_minimum",
    "channels/0/response_maximum",
    "channels/1/member_span",
)
"""Every place in the shipped document that must hold a finite real number.

Enumerated so that no single field can pass the suite by hiding behind fifteen
working neighbours: ``NaN`` compares false against every bound it is checked
against, so a field whose guard was forgotten would accept one and carry it
into a hashed plan without a word.
"""

INTEGER_LOCATIONS = ("channels/0/samples", "record/capacity")
"""Every place that must hold an exact integer, counts being things you can have."""

NON_FINITE = (float("nan"), float("inf"), float("-inf"))

TIMELINE = {
    "fps": 24,
    "start_frame": 1,
    "transition_start": 25,
    "transition_end": 145,
    "end_frame": 193,
}
"""A Phase 17 timeline block, in the shape ``resolve_timeline`` returns it."""


@pytest.fixture(name="document")
def document_fixture() -> dict:
    """The canonical spec as raw JSON, ready to be broken."""
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture(name="resolved", scope="module")
def resolved_fixture() -> dict:
    """The canonical spec, loaded and validated once."""
    return srs.load_state_response_spec(SPEC_PATH)


@pytest.fixture(name="timeline", scope="module")
def timeline_fixture(resolved: dict) -> dict:
    """The Phase 20 view of the locked Phase 17 clock."""
    return srs.resolve_state_response_timeline(resolved, TIMELINE)


def _write(tmp_path: Path, document: object) -> Path:
    """Write one candidate document out for the loader to read."""
    path = tmp_path / "state_response.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _refuses(tmp_path: Path, document: object, fragment: str = "") -> str:
    """Assert the loader refuses a document, and return why."""
    with pytest.raises(srs.StateResponseSpecError) as error:
        srs.load_state_response_spec(_write(tmp_path, document))
    message = str(error.value)
    if fragment:
        assert fragment in message, message
    return message


def _put(document: dict, location: str, value: object) -> None:
    """Write ``value`` into a slash-separated location, digits meaning array index."""
    segments = location.split("/")
    cursor: object = document
    for segment in segments[:-1]:
        cursor = cursor[int(segment)] if segment.isdigit() else cursor[segment]
    last = segments[-1]
    cursor[int(last) if last.isdigit() else last] = value


def _refuses_timeline(spec: dict, block: object, fragment: str) -> None:
    """Assert Phase 20 refuses to borrow this clock, for the stated reason."""
    with pytest.raises(srs.StateResponseSpecError) as error:
        srs.resolve_state_response_timeline(spec, block)
    assert fragment in str(error.value), str(error.value)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_the_canonical_spec_loads(resolved: dict) -> None:
    """The shipped spec is a well-formed state response spec."""
    assert resolved["format"] == srs.STATE_RESPONSE_FORMAT
    assert resolved["schema_version"] == srs.STATE_RESPONSE_SCHEMA_VERSION
    assert resolved["statement"].strip()
    assert [policy["channel"] for policy in resolved["channels"]] == list(srs.SUPPORTED_CHANNELS)


def test_every_declared_channel_is_backed_by_an_authoritative_field(resolved: dict) -> None:
    """A reserved concept is not a signal; every channel names a field that exists."""
    for policy in resolved["channels"]:
        allowed = (
            srs.DISTRICT_SCALARS
            if policy["source_kind"] == "district_scalar"
            else srs.MEMORY_FACT_FIELDS
        )
        assert policy["source_kind"] in srs.SOURCE_KINDS, policy["channel"]
        assert policy["source_field"] in allowed, (
            f"{policy['channel']} reads {policy['source_field']}"
        )
        assert policy["interpolation"] in srs.INTERPOLATIONS, policy["channel"]
        assert policy["strategy"] in srs.STRATEGIES, policy["channel"]


def test_a_document_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    """A JSON array is not a presentation contract, however well formed it is."""
    _refuses(tmp_path, [1, 2, 3], "must be a JSON object")


def test_a_wrong_format_is_refused(tmp_path: Path, document: dict) -> None:
    """A document that is not a response spec is refused by name."""
    document["format"] = "living_diorama_daily_life_mobility"
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
    document["mood"] = 4
    _refuses(tmp_path, document, "unexpected keys ['mood']")


@pytest.mark.parametrize("section", TOP_LEVEL_KEYS)
def test_a_missing_section_is_refused(tmp_path: Path, document: dict, section: str) -> None:
    """A missing section must not silently become a default."""
    document.pop(section)
    _refuses(tmp_path, document, f"is missing ['{section}']")


@pytest.mark.parametrize("statement", ["", "   ", "\n\t"])
def test_an_empty_statement_is_refused(tmp_path: Path, document: dict, statement: str) -> None:
    """The sentence that bounds the claim cannot be blank space."""
    document["statement"] = statement
    _refuses(tmp_path, document, "non-empty statement")


def test_a_non_string_statement_is_refused(tmp_path: Path, document: dict) -> None:
    """A number cannot bound a claim about what the film is showing."""
    document["statement"] = 12
    _refuses(tmp_path, document, "non-empty statement")


# ---------------------------------------------------------------------------
# Channel vocabulary
# ---------------------------------------------------------------------------


def test_an_empty_channels_list_is_refused(tmp_path: Path, document: dict) -> None:
    """A contract that declares nothing shows nothing, and says so out loud."""
    document["channels"] = []
    _refuses(tmp_path, document, "non-empty channels list")


def test_a_channels_section_that_is_not_a_list_is_refused(tmp_path: Path, document: dict) -> None:
    """An object where an ordered list belongs is a malformed contract."""
    document["channels"] = {"district_air": {}}
    _refuses(tmp_path, document, "non-empty channels list")


def test_a_channel_entry_that_is_not_an_object_is_refused(tmp_path: Path, document: dict) -> None:
    """A string in the channel list is not a policy."""
    document["channels"].append("district_air")
    _refuses(tmp_path, document, "must be a JSON object")


def test_a_channel_outside_the_declared_vocabulary_is_refused(
    tmp_path: Path, document: dict
) -> None:
    """The spec may not name a channel the planner has no way to emit."""
    document["channels"][0]["channel"] = "district_mood_halo"
    _refuses(tmp_path, document, "unsupported channel 'district_mood_halo'")


def test_a_duplicated_channel_declaration_is_refused(tmp_path: Path, document: dict) -> None:
    """Two policies for one channel is two answers to one question."""
    document["channels"].append(copy.deepcopy(document["channels"][0]))
    _refuses(tmp_path, document, "is declared twice")


def test_an_unsupported_source_kind_is_refused(tmp_path: Path, document: dict) -> None:
    """A source kind nobody can resolve is a channel that reads nothing."""
    document["channels"][0]["source_kind"] = "district_vector"
    _refuses(tmp_path, document, "unsupported source_kind 'district_vector'")


def test_an_unsupported_strategy_is_refused(tmp_path: Path, document: dict) -> None:
    """Members either move together or in sequence; there is no third answer."""
    document["channels"][0]["strategy"] = "cascade"
    _refuses(tmp_path, document, "unsupported strategy 'cascade'")


def test_an_unsupported_interpolation_is_refused(tmp_path: Path, document: dict) -> None:
    """An easing the sampler cannot draw would be drawn as something else."""
    document["channels"][0]["interpolation"] = "bezier"
    _refuses(tmp_path, document, "unsupported interpolation 'bezier'")


def test_a_district_field_no_export_carries_is_refused(tmp_path: Path, document: dict) -> None:
    """A reserved concept that no stored field backs is a concept, not a signal."""
    document["channels"][0]["source_field"] = "grievance"
    _refuses(tmp_path, document, "which no authoritative district_scalar carries")


def test_a_district_channel_may_not_read_a_field_the_export_holds_elsewhere(
    tmp_path: Path, document: dict
) -> None:
    """``population`` is a real export field and still not a unit-interval signal."""
    document["channels"][0]["source_field"] = "population"
    _refuses(tmp_path, document, "which no authoritative district_scalar carries")


def test_a_memory_channel_may_not_read_the_prose_summary(tmp_path: Path, document: dict) -> None:
    """Parsing a summary would make presentation an author of meaning."""
    document["channels"][1]["source_field"] = "summary"
    _refuses(tmp_path, document, "which no authoritative memory_fact carries")


@pytest.mark.parametrize(
    "key",
    ["interpolation", "source_field", "window", "samples", "response_minimum", "response_maximum"],
)
def test_a_channel_missing_a_key_is_refused(tmp_path: Path, document: dict, key: str) -> None:
    """A missing policy field is a policy nobody wrote, not one nobody needed."""
    document["channels"][0].pop(key)
    _refuses(tmp_path, document, f"is missing ['{key}']")


def test_a_channel_carrying_a_key_its_strategy_does_not_use_is_refused(
    tmp_path: Path, document: dict
) -> None:
    """A member span on a channel that moves together is a stagger nobody applied."""
    document["channels"][0]["member_span"] = 0.2
    _refuses(tmp_path, document, "unexpected keys ['member_span']")


def test_a_memory_channel_carrying_a_response_range_is_refused(
    tmp_path: Path, document: dict
) -> None:
    """A fact has no magnitude, so a range to scale it onto is a range nobody reads."""
    document["channels"][1]["response_minimum"] = 1.0
    _refuses(tmp_path, document, "unexpected keys ['response_minimum']")


def test_a_staged_channel_missing_its_member_span_is_refused(
    tmp_path: Path, document: dict
) -> None:
    """Staggering with no declared span is a stagger of unstated length."""
    document["channels"][1].pop("member_span")
    _refuses(tmp_path, document, "is missing ['member_span']")


@pytest.mark.parametrize("interpolation", srs.INTERPOLATIONS)
def test_every_declared_interpolation_is_accepted(
    tmp_path: Path, document: dict, interpolation: str
) -> None:
    """A vocabulary the loader refuses in practice is a vocabulary of one."""
    document["channels"][0]["interpolation"] = interpolation
    spec = srs.load_state_response_spec(_write(tmp_path, document))
    assert spec["channels"][0]["interpolation"] == interpolation


@pytest.mark.parametrize("field", srs.DISTRICT_SCALARS)
def test_every_authoritative_district_scalar_is_accepted(
    tmp_path: Path, document: dict, field: str
) -> None:
    """All four stored scalars are legal sources, not just the one that shipped."""
    document["channels"][0]["source_field"] = field
    spec = srs.load_state_response_spec(_write(tmp_path, document))
    assert spec["channels"][0]["source_field"] == field


def test_a_channel_may_be_staged_instead_of_together(tmp_path: Path, document: dict) -> None:
    """Both strategies are real; the shipped choice is not the only choice."""
    document["channels"][0]["strategy"] = "staged"
    document["channels"][0]["member_span"] = 0.25
    spec = srs.load_state_response_spec(_write(tmp_path, document))
    assert spec["channels"][0]["strategy"] == "staged"
    assert spec["channels"][0]["member_span"] == 0.25


def test_a_channel_may_move_together_instead_of_staged(tmp_path: Path, document: dict) -> None:
    """And back again: dropping the stagger drops its span with it."""
    document["channels"][1]["strategy"] = "together"
    document["channels"][1].pop("member_span")
    spec = srs.load_state_response_spec(_write(tmp_path, document))
    assert spec["channels"][1]["strategy"] == "together"
    assert "member_span" not in spec["channels"][1]


def test_require_channel_returns_the_policy_it_was_asked_for(resolved: dict) -> None:
    """A lookup that returned the wrong policy would drive the wrong property."""
    for name in srs.SUPPORTED_CHANNELS:
        assert srs.require_channel(resolved, name)["channel"] == name


def test_require_channel_refuses_a_channel_nobody_declared(resolved: dict) -> None:
    """An undeclared channel is refused by name, never resolved to a neighbour."""
    with pytest.raises(srs.StateResponseSpecError) as error:
        srs.require_channel(resolved, "district_air_extra")
    assert "is not declared by this state response spec" in str(error.value)


# ---------------------------------------------------------------------------
# Windows, ranges and counts
# ---------------------------------------------------------------------------


def test_a_reversed_window_is_refused(tmp_path: Path, document: dict) -> None:
    """A window that runs backwards is refused rather than silently swapped."""
    document["channels"][0]["window"] = [0.9, 0.2]
    _refuses(tmp_path, document, "must run forwards")


def test_a_collapsed_window_is_refused(tmp_path: Path, document: dict) -> None:
    """A response that starts and ends at the same instant has no time to happen in."""
    document["channels"][0]["window"] = [0.5, 0.5]
    _refuses(tmp_path, document, "must run forwards")


@pytest.mark.parametrize("bound", [[-0.01, 0.9], [0.1, 1.01], [1.5, 2.5]])
def test_a_window_outside_the_unit_interval_is_refused(
    tmp_path: Path, document: dict, bound: list
) -> None:
    """A window is a position inside the transition, not a frame number."""
    document["channels"][0]["window"] = bound
    _refuses(tmp_path, document, "must lie in [0, 1]")


@pytest.mark.parametrize("window", [[0.2], [0.1, 0.5, 0.9], 0.5, {"start": 0.1}])
def test_a_window_that_is_not_a_pair_is_refused(
    tmp_path: Path, document: dict, window: object
) -> None:
    """Two positions make a window; anything else is a different shape entirely."""
    document["channels"][0]["window"] = window
    _refuses(tmp_path, document, "must be a two-element list")


def test_a_collapsed_response_range_is_refused(tmp_path: Path, document: dict) -> None:
    """A range that cannot widen would make a moving signal look still."""
    document["channels"][0]["response_maximum"] = document["channels"][0]["response_minimum"]
    _refuses(tmp_path, document, "response range must widen")


def test_a_reversed_response_range_is_refused(tmp_path: Path, document: dict) -> None:
    """Nor is a reversed range sorted into an ascending one behind the author's back."""
    document["channels"][0]["response_minimum"] = 4.0
    document["channels"][0]["response_maximum"] = 1.0
    _refuses(tmp_path, document, "response range must widen")


@pytest.mark.parametrize("bound", ["response_minimum", "response_maximum"])
def test_a_non_positive_response_bound_is_refused(
    tmp_path: Path, document: dict, bound: str
) -> None:
    """Zero density is not a faint response, it is the absence of one."""
    document["channels"][0][bound] = 0.0
    _refuses(tmp_path, document, "must be greater than zero")


@pytest.mark.parametrize("samples", [0, -3])
def test_a_channel_sampled_fewer_than_once_is_refused(
    tmp_path: Path, document: dict, samples: int
) -> None:
    """Zero samples is not a coarser curve, it is no curve at all."""
    document["channels"][0]["samples"] = samples
    _refuses(tmp_path, document, "samples must be at least 1")


@pytest.mark.parametrize("location", INTEGER_LOCATIONS)
@pytest.mark.parametrize("value", [8.0, True, "8", None])
def test_a_count_that_is_not_an_exact_integer_is_refused(
    tmp_path: Path, document: dict, location: str, value: object
) -> None:
    """``8.0`` and ``True`` are not counts, whatever Python is willing to do with them."""
    _put(document, location, value)
    _refuses(tmp_path, document, "must be an integer")


@pytest.mark.parametrize("location", NUMERIC_LOCATIONS)
@pytest.mark.parametrize("value", NON_FINITE)
def test_a_non_finite_number_is_refused_wherever_it_appears(
    tmp_path: Path, document: dict, location: str, value: float
) -> None:
    """A ``NaN`` compares false against every bound and would disable its own guard."""
    _put(document, location, value)
    _refuses(tmp_path, document, "must be finite")


@pytest.mark.parametrize("location", NUMERIC_LOCATIONS)
def test_a_boolean_number_is_refused_wherever_it_appears(
    tmp_path: Path, document: dict, location: str
) -> None:
    """``True`` is an int in Python and must never stand in for a magnitude."""
    _put(document, location, True)
    _refuses(tmp_path, document, "must be a real number")


@pytest.mark.parametrize("location", NUMERIC_LOCATIONS)
def test_a_number_written_as_a_string_is_refused(
    tmp_path: Path, document: dict, location: str
) -> None:
    """``"0.5"`` sorts, compares and formats -- and means nothing to arithmetic."""
    _put(document, location, "0.5")
    _refuses(tmp_path, document, "must be a real number")


# ---------------------------------------------------------------------------
# The air block
# ---------------------------------------------------------------------------


def test_a_hue_coded_air_tint_is_refused(tmp_path: Path, document: dict) -> None:
    """A stratum that codes a hue is a heatmap floating over the city, not weather."""
    document["air"]["tint"] = [0.92, 0.30, 0.28]
    _refuses(tmp_path, document, "exceeds 0.18")


def test_a_tint_spread_just_over_the_limit_is_refused(tmp_path: Path, document: dict) -> None:
    """The limit is a limit: 0.19 of spread is refused where 0.17 is not.

    A guard written with the comparison the other way round would still accept
    the tint the shipped file happens to carry, so the pair that matters is the
    one either side of the declared edge.
    """
    document["air"]["tint"] = [0.70, 0.70, 0.89]
    _refuses(tmp_path, document, "exceeds 0.18")
    document["air"]["tint"] = [0.70, 0.70, 0.87]
    spec = srs.load_state_response_spec(_write(tmp_path, document))
    assert spec["air"]["tint"] == [0.70, 0.70, 0.87]


@pytest.mark.parametrize("tint", [[0.0, 0.71, 0.66], [0.74, 0.0, 0.66], [0.74, 0.71, 0.0]])
def test_a_tint_with_a_dead_component_is_refused(
    tmp_path: Path, document: dict, tint: list
) -> None:
    """Air with no light in one channel is a filter, and a filter is a judgement."""
    document["air"]["tint"] = tint
    _refuses(tmp_path, document, "must carry light in every channel")


@pytest.mark.parametrize("tint", [[1.4, 0.71, 0.66], [0.74, -0.2, 0.66]])
def test_a_tint_outside_its_domain_is_refused(tmp_path: Path, document: dict, tint: list) -> None:
    """A colour component outside ``[0, 1]`` is refused, never clamped."""
    document["air"]["tint"] = tint
    _refuses(tmp_path, document, "components must lie in [0, 1]")


@pytest.mark.parametrize("tint", [[0.7, 0.7], [0.7, 0.7, 0.7, 0.7], "grey"])
def test_a_tint_that_is_not_a_triple_is_refused(
    tmp_path: Path, document: dict, tint: object
) -> None:
    """Three components make a colour; a fourth is a channel nobody renders."""
    document["air"]["tint"] = tint
    _refuses(tmp_path, document, "must be a three-element list")


@pytest.mark.parametrize("key", ["base_density", "rim_margin_metres", "ceiling_metres"])
def test_a_non_positive_air_extent_is_refused(tmp_path: Path, document: dict, key: str) -> None:
    """A stratum with no density, no margin or no ceiling is not a stratum."""
    document["air"][key] = 0.0
    _refuses(tmp_path, document, "must be greater than zero")


@pytest.mark.parametrize("key", ["floor_density_fraction", "anisotropy"])
def test_an_air_fraction_outside_its_domain_is_refused(
    tmp_path: Path, document: dict, key: str
) -> None:
    """A fraction above one is not a stronger fraction, it is a different quantity."""
    document["air"][key] = 1.4
    _refuses(tmp_path, document, "must lie in [0, 1]")


def test_an_unknown_air_key_is_refused(tmp_path: Path, document: dict) -> None:
    """A constant nobody reads is a constant nobody applied."""
    document["air"]["emotion"] = 0.5
    _refuses(tmp_path, document, "unexpected keys ['emotion']")


def test_an_air_block_that_is_not_an_object_is_refused(tmp_path: Path, document: dict) -> None:
    """A list where a block belongs is a malformed contract."""
    document["air"] = [0.0011]
    _refuses(tmp_path, document, "air block must be a JSON object")


# ---------------------------------------------------------------------------
# The record block
# ---------------------------------------------------------------------------


def test_a_record_arc_that_holds_nothing_is_refused(tmp_path: Path, document: dict) -> None:
    """An arc with no capacity would refuse every fact the engine remembered."""
    document["record"]["capacity"] = 0
    _refuses(tmp_path, document, "capacity must be at least 1")


@pytest.mark.parametrize("axis", [0, 1, 2])
def test_a_flat_record_stone_is_refused(tmp_path: Path, document: dict, axis: int) -> None:
    """A stone with a zero axis is a plane, and a plane is not a marker."""
    document["record"]["stone_size_metres"][axis] = 0.0
    _refuses(tmp_path, document, "must be positive in every axis")


@pytest.mark.parametrize("origin", [[1.0], [1.0, 2.0, 3.0], 4.0])
def test_a_record_origin_that_is_not_a_pair_is_refused(
    tmp_path: Path, document: dict, origin: object
) -> None:
    """An arc is anchored on the ground plane by exactly two numbers."""
    document["record"]["origin"] = origin
    _refuses(tmp_path, document, "must be a two-element list")


def test_a_non_positive_arc_radius_is_refused(tmp_path: Path, document: dict) -> None:
    """A radius of zero would stack every stone the world remembers on one spot."""
    document["record"]["arc_radius_metres"] = 0.0
    _refuses(tmp_path, document, "must be greater than zero")


def test_an_unknown_record_key_is_refused(tmp_path: Path, document: dict) -> None:
    """A field this contract does not describe means the file came from something else."""
    document["record"]["belief"] = 1
    _refuses(tmp_path, document, "unexpected keys ['belief']")


# ---------------------------------------------------------------------------
# The borrowed clock
# ---------------------------------------------------------------------------


def test_the_locked_phase17_timeline_resolves(resolved: dict) -> None:
    """The clock Phase 20 borrows is the clock Phase 17 actually publishes."""
    phase17 = mts.load_motion_time_spec(MOTION_PATH)["timeline"]
    borrowed = srs.resolve_state_response_timeline(resolved, phase17)
    for field in ("fps", "start_frame", "transition_start", "transition_end", "end_frame"):
        assert borrowed[field] == phase17[field], field
    assert borrowed["transition_span"] == phase17["transition_end"] - phase17["transition_start"]


@pytest.mark.parametrize(
    "field", ["fps", "start_frame", "transition_start", "transition_end", "end_frame"]
)
def test_a_timeline_missing_a_field_phase20_reads_is_refused(resolved: dict, field: str) -> None:
    """Phase 20 supplies no clock of its own, so a missing field is not filled in."""
    block = dict(TIMELINE)
    block.pop(field)
    _refuses_timeline(resolved, block, f"missing {field!r}")


@pytest.mark.parametrize("value", [24.0, True, "24", None])
def test_a_timeline_frame_that_is_not_an_integer_is_refused(resolved: dict, value: object) -> None:
    """Frames are counted, and a frame numbered ``24.0`` is a frame nobody renders."""
    block = dict(TIMELINE)
    block["transition_end"] = value
    _refuses_timeline(resolved, block, "must be an integer")


def test_a_timeline_with_no_frames_per_second_is_refused(resolved: dict) -> None:
    """A clock at zero frames a second never advances."""
    block = dict(TIMELINE, fps=0)
    _refuses_timeline(resolved, block, "fps must be positive")


@pytest.mark.parametrize(
    "override",
    [
        {"transition_start": 145, "transition_end": 25},
        {"transition_start": 60, "transition_end": 60},
        {"start_frame": 40},
        {"end_frame": 100},
    ],
)
def test_a_timeline_that_does_not_run_forwards_is_refused(resolved: dict, override: dict) -> None:
    """A hold that ends before it starts is not a slower hold, it is a broken one."""
    _refuses_timeline(resolved, dict(TIMELINE, **override), "must run forwards")


def test_a_timeline_that_is_not_an_object_is_refused(resolved: dict) -> None:
    """A list of frame numbers is not a timeline, whatever order it is in."""
    _refuses_timeline(resolved, [1, 25, 145, 193], "must be a JSON object")


def test_a_position_names_the_same_frame_in_both_phases(resolved: dict, timeline: dict) -> None:
    """Two independent rounding helpers that agree everywhere are one clock.

    ``motion_time_spec.frame_at`` is a separately written implementation over
    the same locked frames. If Phase 20 rounded even one position differently,
    the same normalized instant would name adjacent frames in the two layers and
    the shared clock would quietly stop being shared.
    """
    phase17 = mts.load_motion_time_spec(MOTION_PATH)["timeline"]
    for step in range(0, 481):
        position = step / 480.0
        assert srs.frame_at(timeline, position) == mts.frame_at(phase17, position), position


def test_a_position_at_either_end_names_the_transition_boundary(timeline: dict) -> None:
    """Zero is the first transition frame and one is the last, exactly."""
    assert srs.frame_at(timeline, 0.0) == timeline["transition_start"]
    assert srs.frame_at(timeline, 1.0) == timeline["transition_end"]


def test_a_half_frame_position_rounds_up_rather_than_to_even(resolved: dict) -> None:
    """Half-up, not Python's half-to-even, and the two disagree here.

    ``round(0.5)`` is ``0`` in Python and ``round(1.5)`` is ``2``: banker's
    rounding would place these two positions on frames 100 and 102. Half-up
    places them on 101 and 102, and a helper that used the builtin would pass
    every test that only checked the endpoints.
    """
    short = srs.resolve_state_response_timeline(
        resolved,
        {
            "fps": 24,
            "start_frame": 0,
            "transition_start": 100,
            "transition_end": 102,
            "end_frame": 102,
        },
    )
    assert short["transition_span"] == 2
    assert srs.frame_at(short, 0.25) == 101
    assert srs.frame_at(short, 0.25) != short["transition_start"] + round(0.5)
    assert srs.frame_at(short, 0.75) == 102


@pytest.mark.parametrize("position", [-0.01, 1.01, float("nan"), True, "0.5"])
def test_a_position_outside_the_unit_interval_is_refused(timeline: dict, position: object) -> None:
    """A position is a fraction of the transition, and there is no frame at 1.4."""
    with pytest.raises(srs.StateResponseSpecError):
        srs.frame_at(timeline, position)


def test_a_channel_window_resolves_inside_the_transition(resolved: dict, timeline: dict) -> None:
    """Nothing moves during a hold; that is what makes a hold provable."""
    for policy in resolved["channels"]:
        start, end = srs.channel_frames(policy, timeline)
        assert timeline["transition_start"] <= start < end <= timeline["transition_end"], (
            f"{policy['channel']} resolves to {start}..{end}"
        )
        assert start == srs.frame_at(timeline, policy["window"][0])
        assert end == srs.frame_at(timeline, policy["window"][1])


def test_members_that_move_together_all_share_the_channel_window(
    resolved: dict, timeline: dict
) -> None:
    """Moving together means together: four districts, one window, no stagger."""
    policy = srs.require_channel(resolved, "district_air")
    assert policy["strategy"] == "together"
    window = srs.channel_frames(policy, timeline)
    assert [srs.member_window(policy, timeline, index, 4) for index in range(4)] == [window] * 4


def test_staged_members_are_staggered_across_the_whole_window(
    resolved: dict, timeline: dict
) -> None:
    """Staged means the first opens the window, the last closes it, and each waits."""
    policy = srs.require_channel(resolved, "memory_record")
    assert policy["strategy"] == "staged"
    start, end = srs.channel_frames(policy, timeline)
    span = srs.member_span_frames(policy, timeline)
    windows = [srs.member_window(policy, timeline, index, 5) for index in range(5)]
    assert windows[0][0] == start
    assert windows[-1][1] == end
    assert [first for first, _ in windows] == sorted(first for first, _ in windows)
    assert {last - first for first, last in windows} == {span}
    assert len({first for first, _ in windows}) == 5


def test_a_lone_staged_member_takes_the_whole_window(resolved: dict, timeline: dict) -> None:
    """One member cannot be staggered against anybody, so it holds the window."""
    policy = srs.require_channel(resolved, "memory_record")
    assert srs.member_window(policy, timeline, 0, 1) == srs.channel_frames(policy, timeline)


# ---------------------------------------------------------------------------
# Easing and response magnitude
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", srs.INTERPOLATIONS)
def test_an_eased_curve_is_exact_at_both_ends(kind: str) -> None:
    """However a curve is eased, its endpoints are the values it was given."""
    assert srs.interpolate(kind, 3.5, 9.25, 0.0) == 3.5
    assert srs.interpolate(kind, 3.5, 9.25, 1.0) == 9.25


@pytest.mark.parametrize("kind", srs.INTERPOLATIONS)
def test_an_eased_curve_matches_the_locked_phase17_easing(kind: str) -> None:
    """Two layers easing the same channel must draw the same curve, not a similar one."""
    for step in range(0, 101):
        position = step / 100.0
        assert srs.interpolate(kind, -2.0, 6.0, position) == pytest.approx(
            mts.interpolate(kind, -2.0, 6.0, position)
        ), position


def test_a_stepped_curve_holds_its_start_until_the_last_instant() -> None:
    """A state swap is a swap: nothing in between is a value the world ever held."""
    interior = [srs.interpolate("step", 0.0, 1.0, step / 10.0) for step in range(1, 10)]
    assert interior == [0.0] * 9
    assert srs.interpolate("step", 0.0, 1.0, 1.0) == 1.0


def test_a_smoothstepped_curve_is_not_a_straight_line() -> None:
    """Easing that matched linear everywhere would be linear under another name."""
    assert srs.interpolate("smoothstep", 0.0, 1.0, 0.25) == pytest.approx(0.15625)
    assert srs.interpolate("smoothstep", 0.0, 1.0, 0.25) != srs.interpolate(
        "linear", 0.0, 1.0, 0.25
    )
    assert srs.interpolate("smoothstep", 0.0, 1.0, 0.5) == pytest.approx(0.5)


def test_a_linear_curve_is_the_straight_line_between_its_ends() -> None:
    """Linear means the fraction of the way, and nothing more interesting."""
    assert srs.interpolate("linear", 2.0, 10.0, 0.25) == pytest.approx(4.0)
    assert srs.interpolate("linear", 2.0, 10.0, 0.75) == pytest.approx(8.0)


def test_an_unsupported_easing_is_refused() -> None:
    """An easing nobody implemented would otherwise be drawn as whatever came last."""
    with pytest.raises(srs.StateResponseSpecError) as error:
        srs.interpolate("bezier", 0.0, 1.0, 0.5)
    assert "unsupported interpolation 'bezier'" in str(error.value)


@pytest.mark.parametrize("position", [-0.5, 1.5, float("inf")])
def test_easing_outside_the_unit_interval_is_refused(position: float) -> None:
    """Extrapolation is invention; the curve exists only between its own ends."""
    with pytest.raises(srs.StateResponseSpecError):
        srs.interpolate("linear", 0.0, 1.0, position)


def test_a_response_reaches_exactly_its_declared_bounds(resolved: dict) -> None:
    """The signal's whole domain maps onto the range's whole span, end to end."""
    policy = srs.require_channel(resolved, "district_air")
    low, high = policy["response_minimum"], policy["response_maximum"]
    values = [srs.response_value(policy, step / 100.0) for step in range(0, 101)]
    assert values[0] == low
    assert values[-1] == high
    assert min(values) == low
    assert max(values) == high


def test_a_response_is_linear_in_the_signal_it_reads(resolved: dict) -> None:
    """Equal steps of state make equal steps of response: no band, no threshold.

    A banded mapping would repeat values across a stretch of the domain and jump
    at its edges; this asserts the differences between evenly spaced readings are
    all the same, which no banding can survive.
    """
    policy = srs.require_channel(resolved, "district_air")
    values = [srs.response_value(policy, step / 8.0) for step in range(0, 9)]
    steps = [second - first for first, second in zip(values[:-1], values[1:], strict=True)]
    assert steps == [pytest.approx(steps[0])] * len(steps)
    assert steps[0] > 0.0
    assert values == sorted(values)
    assert len(set(values)) == len(values)


@pytest.mark.parametrize("reading", [-0.01, 1.01, float("nan"), True, None, "0.5"])
def test_a_response_refuses_a_reading_outside_the_field_domain(
    resolved: dict, reading: object
) -> None:
    """The persistence layer validates the field into ``[0, 1]``; anything else is corruption."""
    policy = srs.require_channel(resolved, "district_air")
    with pytest.raises(srs.StateResponseSpecError):
        srs.response_value(policy, reading)


def test_a_channel_with_no_response_range_cannot_scale_a_signal(resolved: dict) -> None:
    """A fact has no magnitude, and inventing one for it would be inventing meaning."""
    policy = srs.require_channel(resolved, "memory_record")
    with pytest.raises(srs.StateResponseSpecError) as error:
        srs.response_value(policy, 0.5)
    assert "declares no response range" in str(error.value)
