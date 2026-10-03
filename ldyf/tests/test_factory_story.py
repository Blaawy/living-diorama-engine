"""Proof that the factory's story, camera, narration and timeline stages tell only what was measured.

Four stages are covered, against the REAL sealed episode (see conftest.py):

    story.py      beats are SELECTED from measured outcomes; an outcome that was
                  not measured has no beat, and an episode that cannot fill its
                  structure is refused
    camera.py     a camera per beat, measured from the record; a camera that
                  misses its event is a refusal, never a weaker shot
    narration.py  every sentence is a template bound to a fact or a shot; a
                  typed numeral, a spelled number, an unchecked comparison or a
                  false check stops the pipeline
    timeline.py   the edit recipe and the captions (pure parts only)

The session fixtures are read-only. Every attack below works on a deep copy and
re-seals it, i.e. it is what an insider with write access could do: the hashes
verify, so only the stage's own cross-checks can refuse it.

Geometry units use a lens at the origin looking down +x with a 90 degree
horizontal field of view at 1920x1080, so tan_h = 1 and tan_v = 0.5625 and
every expected number below can be worked out by hand.
"""
from __future__ import annotations

import copy
import re
from pathlib import Path

import pytest

from ldyf.factory import FactoryError
from ldyf.factory import narration as narration_mod
from ldyf.factory.camera import (PARAMS, CameraError, Lens, _seg_hits_rect, check_requirement,
                                 look_rot, measure, plan_shots, remeasure, sees)
from ldyf.factory.narration import (CLAIM_WORDS, MAX_WORDS, NUMBER_WORDS, NarrationError,
                                    bind_narration, estimate_seconds, evaluate_check, lint, render,
                                    resolve, words_of)
from ldyf.factory.record import Record, Track
from ldyf.factory.story import PACING, REQUIRED_DEVICES, StoryError, select_story
from ldyf.factory.timeline import (MIN_TAIL_SECONDS, TimelineError, build_captions,
                                   build_timeline)
from ldyf.factory.util import canonical_bytes, seal, verify_seal

from .factory_support import load


# --- helpers -----------------------------------------------------------------------

def _facts_with(facts, **values):
    """A deep copy of the fact sheet with some measured values replaced."""
    doc = copy.deepcopy(facts)
    for k, v in values.items():
        doc["facts"][k]["value"] = v
    return doc


def _beat(story, bid):
    return next(b for b in story["beats"] if b["id"] == bid)


def _ids(story):
    return [b["id"] for b in story["beats"]]


def _templates(story):
    return [l["template"] for b in story["beats"] for l in b["lines"]]


def _attack_line(story, shots, beat_id, index, **changes):
    """(story, shots) with ONE sentence changed, both re-sealed so lineage passes."""
    s = copy.deepcopy(story)
    row = _beat(s, beat_id)["lines"][index]
    for k, v in changes.items():
        if v is None:
            row.pop(k, None)
        else:
            row[k] = v
    s = seal(s, "story_hash")
    return s, seal({**shots, "story_hash": s["story_hash"]}, "shots_hash")


def _mini_story(story, ids, edit=None):
    """A re-sealed story of only the beats `ids`, optionally edited (`edit(beats_by_id, story)`)."""
    s = copy.deepcopy(story)
    s["beats"] = [b for b in s["beats"] if b["id"] in ids]
    if edit is not None:
        edit({b["id"]: b for b in s["beats"]}, s)
    return seal(s, "story_hash")


def _voice(narration, factor=0.8, drop=None, seconds=None):
    """A sealed voice document without speech synthesis: each line lasts factor x its plan."""
    lines = [{"id": l["id"], "seconds": round(factor * l["planned_seconds"], 3)}
             for l in narration["lines"] if l["id"] != drop]
    for row in lines:
        if seconds and row["id"] in seconds:
            row["seconds"] = seconds[row["id"]]
    return seal({"schema_version": "episode_voice_v1", "narration_hash": narration["narration_hash"],
                 "lines": lines, "voice_hash": ""}, "voice_hash")


def _picture(shots, **overrides):
    """A fake render manifest: the engine measures what the planner did, except `overrides`."""
    rows = {bid: {"engine_subjects_visible_min": s["subjects_visible_min"],
                  "engine_subjects_visible_max": s["subjects_visible_max"],
                  "engine_subjects_visible_last": s["subjects_visible_last"]}
            for bid, s in shots["shots"].items()}
    for bid, row in overrides.items():
        rows[bid].update(row)
    return {"shots_hash": shots["shots_hash"], "render_hash": "x" * 64, "shots": rows}


@pytest.fixture(scope="module")
def res(factory_brief):
    return factory_brief["resolution"]


@pytest.fixture(scope="module")
def plan(factory_facts, factory_recs, factory_net, factory_blocks, res):
    """`plan(story, facts=..., recs=...)` -> plan_shots on the real record."""
    def run(story, facts=None, recs=None):
        return plan_shots(story, facts or factory_facts, recs or factory_recs, factory_net,
                          factory_blocks, res)
    return run


@pytest.fixture(scope="module")
def voice(factory_narration):
    return _voice(factory_narration)


@pytest.fixture(scope="module")
def timeline(factory_story, factory_shots, factory_narration, voice, factory_brief):
    return build_timeline(factory_story, factory_shots, factory_narration, voice, factory_brief)


# ===================================================================================
# STORY
# ===================================================================================

def test_story_is_deterministic_and_equals_the_sealed_one(factory_facts, factory_brief, factory_pkg):
    """Would catch a selector that depends on anything but the fact sheet and the brief."""
    a = select_story(factory_facts, factory_brief)
    b = select_story(factory_facts, factory_brief)
    assert canonical_bytes(a) == canonical_bytes(b)
    assert a["story_hash"] == b["story_hash"]
    verify_seal(a, "story_hash", "story")
    on_disk = Path(factory_pkg) / "story.json"
    if on_disk.is_file():
        assert canonical_bytes(load(on_disk)) == canonical_bytes(a)


def test_story_opens_on_the_hook_and_predicts_before_it_reveals(factory_story):
    """Would catch a reveal told before the viewer has been given the sealed prediction."""
    beats = factory_story["beats"]
    ids, roles = _ids(factory_story), [b["role"] for b in beats]
    assert roles[0] == "hook"
    assert "reveal" in ids
    assert roles.index("prediction") < ids.index("reveal")
    assert len(set(ids)) == len(ids)


def test_story_fills_every_required_device(factory_story):
    """Would catch an episode sealed without one of the structural devices it promises."""
    for device in REQUIRED_DEVICES:
        told = [b["id"] for b in factory_story["beats"] if device in b["devices"]]
        assert told, device
        assert factory_story["structure"][device] == told


def test_story_length_is_inside_the_brief_and_every_beat_is_whole_seconds(factory_story,
                                                                         factory_brief):
    """Would catch a padded or cut episode, or a beat that is not a whole number of frames."""
    lo, hi = factory_brief["target_seconds"]
    assert lo <= factory_story["seconds_total"] <= hi
    assert factory_story["seconds_total"] == sum(b["seconds"] for b in factory_story["beats"])
    for b in factory_story["beats"]:
        assert b["seconds"] == int(b["seconds"]) and b["seconds"] > 0, b["id"]


def test_story_comparison_shots_point_back_at_the_other_arm(factory_story):
    """Would catch a 'same camera' beat that precedes, or replays the arm of, its source."""
    ids = _ids(factory_story)
    refs = [b for b in factory_story["beats"] if b["visual"].get("same_as") is not None]
    assert refs
    for b in refs:
        src_id = b["visual"]["same_as"]
        assert src_id in ids
        assert ids.index(src_id) < ids.index(b["id"]), b["id"]
        assert _beat(factory_story, src_id)["visual"]["arm"] != b["visual"]["arm"], b["id"]


def test_story_planned_seconds_cover_every_sentence(factory_story):
    """Would catch a beat shorter than its own lead-in, sentences, gaps and hold."""
    for b in factory_story["beats"]:
        spoken = sum(l["planned_seconds"] + l["gap_after"] for l in b["lines"])
        if "event" not in b:
            assert b["seconds"] >= PACING["lead_in_seconds"] + spoken + b["hold_seconds"] - 1e-9, b["id"]
        ids = [l["id"] for l in b["lines"]]
        assert ids == [f"{b['id']}.{i + 1:02d}" for i in range(len(ids))]


# --- grounded in measured outcomes ---------------------------------------------------

def test_no_stuck_car_measured_means_no_stuck_beat(factory_facts, factory_brief):
    """Would catch the 'cars find no other way' beat being told when no car was measured stuck."""
    story = select_story(_facts_with(factory_facts, cars_found_no_other_way=0), factory_brief)
    chosen = {s["beat"]: s["selected"] for s in story["selection"]}
    assert chosen["stuck"] is False
    assert "stuck" not in _ids(story)
    assert not any(l["id"].startswith("stuck.") for b in story["beats"] for l in b["lines"])
    assert "{cars_found_no_other_way} did not." not in _templates(story)
    # what the code does: a shorter, still valid story (not a refusal)
    lo, hi = factory_brief["target_seconds"]
    full = select_story(factory_facts, factory_brief)
    assert lo <= story["seconds_total"] < full["seconds_total"]
    verify_seal(story, "story_hash", "story")


def test_no_stuck_car_measured_means_no_sentence_about_cars_that_stood(factory_facts, factory_brief):
    """Would catch a sentence about 'the cars that stood' surviving when zero cars stood."""
    story = select_story(_facts_with(factory_facts, cars_found_no_other_way=0), factory_brief)
    assert not [t for t in _templates(story) if "cars_found_no_other_way" in t]


def test_no_stuck_car_record_means_no_stuck_and_no_moved_beat(factory_facts, factory_brief):
    """Would catch a beat about one named stuck car when the facts name no such car."""
    for empty in ("delete", {}):
        doc = copy.deepcopy(factory_facts)
        if empty == "delete":
            del doc["stuck_cars"]
        else:
            doc["stuck_cars"] = {}
        story = select_story(doc, factory_brief)
        assert "stuck" not in _ids(story) and "moved" not in _ids(story)
        assert not any("event" in b for b in story["beats"])
        assert all(not s["selected"] for s in story["selection"] if s["beat"] in ("stuck", "moved"))


def test_a_contradicted_prediction_is_told_as_wrong(factory_facts, factory_brief, factory_story):
    """Would catch 'Our guess was right.' being said of a prediction the measurement contradicts."""
    assert _beat(factory_story, "reveal")["lines"][-1]["template"] == "Our guess was right."
    story = select_story(_facts_with(factory_facts, prediction_outcome="contradicted"), factory_brief)
    verdict = _beat(story, "reveal")["lines"][-1]
    assert verdict["template"] == "Our guess was wrong."
    assert verdict["checks"] == [["fact:prediction_outcome", "==", "contradicted"]]
    assert "Our guess was right." not in _templates(story)


def test_no_car_that_never_started_means_no_beat_and_no_closing_line(factory_facts, factory_brief,
                                                                    factory_story):
    """Would catch 'N cars never start' being told, in its beat or the close, when N is zero."""
    assert "{cars_never_started} never started." in _templates(factory_story)
    story = select_story(_facts_with(factory_facts, cars_never_started=0), factory_brief)
    chosen = {s["beat"]: s["selected"] for s in story["selection"]}
    assert chosen["never_started"] is False
    assert "never_started" not in _ids(story)
    assert not [t for t in _templates(story) if "cars_never_started" in t]


# --- fail closed -----------------------------------------------------------------------

def test_story_refuses_a_rule_it_has_no_catalogue_for(factory_facts, factory_brief):
    """Would catch a closure story being told about a rule that is not a closure."""
    with pytest.raises(StoryError) as err:
        select_story({**factory_facts, "rule_change_type": "speed_limit"}, factory_brief)
    assert err.value.code == "no_catalogue"
    assert err.value.stage == "story"
    assert isinstance(err.value, FactoryError)


def test_story_refuses_a_length_the_measured_beats_do_not_fill(factory_facts, factory_brief):
    """Would catch measured beats being cut (or padded) to hit a target length."""
    with pytest.raises(StoryError) as err:
        select_story(factory_facts, {**factory_brief, "target_seconds": [60.0, 120.0]})
    assert err.value.code == "length_out_of_range"
    with pytest.raises(StoryError) as err:
        select_story(factory_facts, {**factory_brief, "target_seconds": [900.0, 1200.0]})
    assert err.value.code == "length_out_of_range"


@pytest.mark.parametrize("fact", ["rule_second", "prediction_outcome", "cars_on_closed_block_without_rule"])
def test_story_refuses_a_fact_sheet_missing_what_the_catalogue_needs(factory_facts, factory_brief, fact):
    """Would catch a missing measurement being defaulted instead of refused."""
    doc = copy.deepcopy(factory_facts)
    del doc["facts"][fact]
    with pytest.raises(StoryError) as err:
        select_story(doc, factory_brief)
    assert err.value.code == "missing_evidence"


def test_story_refuses_when_the_hook_has_nothing_to_show(factory_facts, factory_brief):
    """Would catch an episode opening on a block no car was recorded on.

    The code refuses with `incomplete_story` (the always-told `rule` beat compares
    itself with the hook's shot) before it reaches the `structure_incomplete` checks.
    """
    with pytest.raises(StoryError) as err:
        select_story(_facts_with(factory_facts, cars_on_closed_block_without_rule=0), factory_brief)
    assert err.value.code == "incomplete_story"


def test_story_refuses_an_episode_without_a_declared_prediction(factory_facts, factory_brief):
    """Would catch a reveal with no prediction before it."""
    with pytest.raises(StoryError) as err:
        select_story(_facts_with(factory_facts, prediction_declared_before_run=False), factory_brief)
    assert err.value.code == "structure_incomplete"


def test_story_refuses_when_a_required_device_has_no_beat(factory_facts, factory_brief):
    """Would catch an episode sealed with no 'knowable uncertainty' beat at all."""
    doc = _facts_with(factory_facts, prediction_declared_before_run=False, walkers_arrived_later=0,
                      walkers_arrived_earlier=0, all_runs=1)
    with pytest.raises(StoryError) as err:
        select_story(doc, factory_brief)
    assert err.value.code == "structure_incomplete"


def test_no_story_template_types_a_numeral_or_spells_a_number(factory_story):
    """Would catch a quantity written into a template instead of bound to evidence."""
    templates = _templates(factory_story)
    assert templates
    for t in templates:
        bare = narration_mod._PLURAL.sub(lambda m: f" {m.group(1)} {m.group(2)} ",
                                         narration_mod._PLACE.sub(" ", t))
        assert not narration_mod._DIGIT.search(bare), t
        assert not set(words_of(bare)) & NUMBER_WORDS, t


# ===================================================================================
# NARRATION: units
# ===================================================================================

MINI = {
    "facts": {
        "n": {"value": 3}, "one": {"value": 1}, "zero": {"value": 0}, "two": {"value": 2},
        "x": {"value": 34.83}, "small": {"value": 2.28}, "flag": {"value": True},
        "word": {"value": "increase"},
    },
    "streets": {"a": {"street": "Baker Avenue"}, "b": {"street": "Route 66"}, "c": {"street": "  "}},
}
MINI_SHOTS = {"shots": {"b1": {"subjects_visible_min": 4, "arm": "ruled", "camera": {"fov_deg": 42.0}},
                        "b2": {"subjects_visible_min": 1}}}


def test_render_states_a_count_and_cites_it():
    """Would catch a count rendered wrongly or without its citation."""
    text, cites = render("{n} cars make a trip.", MINI, None, "")
    assert text == "3 cars make a trip."
    assert cites == [{"ref": "fact:n", "value": 3, "stated": "3", "decimals": 0}]
    assert render("{n:0} cars.", MINI, None, "")[0] == "3 cars."


def test_render_rounds_a_measurement_to_the_stated_decimals():
    """Would catch a measurement stated at a precision the template did not declare."""
    assert render("{x:0} seconds.", MINI, None, "")[0] == "35 seconds."
    text, cites = render("{x:1} seconds.", MINI, None, "")
    assert text == "34.8 seconds."
    assert cites == [{"ref": "fact:x", "value": 34.83, "stated": "34.8", "decimals": 1}]
    assert render("{small:1} metres.", MINI, None, "")[0] == "2.3 metres."
    assert render("{small:2} metres.", MINI, None, "")[0] == "2.28 metres."


@pytest.mark.parametrize("template, code", [
    ("{n:1} cars.", "false_precision"),
    ("{x} seconds.", "unstated_precision"),
    ("That is 35 seconds more.", "unbound_number"),
    ("{n} of 3 cars.", "unbound_number"),
    ("{nope} cars.", "unknown_fact"),
    ("{flag} cars.", "not_a_number"),
    ("{word:0} cars.", "not_a_number"),
    ("On {$streets.b.street}.", "unbound_number"),
    ("On {$streets.c.street}.", "not_a_string"),
    ("On {$streets.zzz.street}.", "unknown_fact"),
    ("On {$facts.word.value}.", "unknown_fact"),
    ("[car|cars:flag] here.", "not_a_number"),
    ("{n cars.", "bad_template"),
    ("[car|cars] here.", "bad_template"),
    ("At least {@subjects_visible_min} of them.", "unbound_shot"),
    ("[is|are:@subjects_visible_min] here.", "unbound_shot"),
])
def test_render_refuses(template, code):
    """Would catch a sentence filled from something that is not bound, measured evidence."""
    with pytest.raises(NarrationError) as err:
        render(template, MINI, None, "")
    assert err.value.code == code
    assert err.value.stage == "narration"


def test_render_fills_a_string_from_the_fact_sheet():
    """Would catch a street name said without a citation of where it came from."""
    text, cites = render("Here. On {$streets.a.street}.", MINI, None, "")
    assert text == "Here. On Baker Avenue."
    assert cites == [{"ref": "text:streets.a.street", "value": "Baker Avenue", "stated": "Baker Avenue"}]


def test_render_chooses_grammatical_number_from_the_value():
    """Would catch '1 cars are' / '0 car is': the singular is for exactly one."""
    t = "{%s} [car|cars:%s] [is|are:%s] here."
    assert render(t % (("one",) * 3), MINI, None, "")[0] == "1 car is here."
    assert render(t % (("zero",) * 3), MINI, None, "")[0] == "0 cars are here."
    assert render(t % (("two",) * 3), MINI, None, "")[0] == "2 cars are here."
    # the grammatical choice alone cites nothing
    assert render("[It|They:one] moved.", MINI, None, "") == ("It moved.", [])


def test_render_binds_a_shot_measurement_of_this_beat():
    """Would catch a picture claim filled from another beat's shot."""
    text, cites = render("At least {@subjects_visible_min} [is|are:@subjects_visible_min] here.",
                         MINI, MINI_SHOTS, "b1")
    assert text == "At least 4 are here."
    assert cites == [{"ref": "shot:subjects_visible_min", "value": 4, "stated": "4", "decimals": 0}]
    assert render("{@subjects_visible_min} [is|are:@subjects_visible_min] here.",
                  MINI, MINI_SHOTS, "b2")[0] == "1 is here."
    with pytest.raises(NarrationError) as err:
        render("{@subjects_visible_min} here.", MINI, MINI_SHOTS, "b3")
    assert err.value.code == "unbound_shot"
    with pytest.raises(NarrationError) as err:
        render("{@subjects_visible_max} here.", MINI, MINI_SHOTS, "b1")
    assert err.value.code == "unbound_shot"


def test_resolve_reads_literals_facts_strings_and_shots():
    """Would catch an operand resolving to the wrong document or the wrong beat."""
    assert resolve(0, MINI, None, "") == 0
    assert resolve("ruled", MINI, None, "") == "ruled"
    assert resolve(True, MINI, None, "") is True
    assert resolve("fact:x", MINI, None, "") == 34.83
    assert resolve("text:streets.a.street", MINI, None, "") == "Baker Avenue"
    assert resolve("shot:arm", MINI, MINI_SHOTS, "b1") == "ruled"
    assert resolve("shot:camera.fov_deg", MINI, MINI_SHOTS, "b1") == 42.0
    assert resolve("shot@b2:subjects_visible_min", MINI, MINI_SHOTS, "b1") == 1
    for ref, code in (("fact:nope", "unknown_fact"), ("text:nope", "unknown_fact"),
                      ("text:facts.n.value", "unknown_fact"), ("shot:arm", "unbound_shot")):
        with pytest.raises(NarrationError) as err:
            resolve(ref, MINI, None, "b1")
        assert err.value.code == code
    with pytest.raises(NarrationError) as err:
        resolve("shot@b9:arm", MINI, MINI_SHOTS, "b1")
    assert err.value.code == "unbound_shot"


def test_resolve_prefers_the_engine_measurement_when_the_shot_is_rendered():
    """Would catch a picture claim still read from the plan after the engine measured the shot."""
    shots = {**MINI_SHOTS, "_picture": {"shots": {"b1": {"engine_subjects_visible_min": 2}}}}
    assert resolve("shot:subjects_visible_min", MINI, shots, "b1") == 2
    assert resolve("shot:arm", MINI, shots, "b1") == "ruled"       # not an engine field
    with pytest.raises(NarrationError) as err:
        resolve("shot:subjects_visible_min", MINI, shots, "b2")
    assert err.value.code == "unbound_shot"


def test_evaluate_check_reports_whether_the_relation_holds():
    """Would catch a check recorded as holding when the evidence says otherwise."""
    got = evaluate_check(["fact:x", ">", "fact:small"], MINI, None, "")
    assert got == {"left": "fact:x", "op": ">", "right": "fact:small",
                   "left_value": 34.83, "right_value": 2.28, "holds": True}
    assert evaluate_check(["fact:x", "<", "fact:small"], MINI, None, "")["holds"] is False
    assert evaluate_check(["fact:zero", "==", 0], MINI, None, "")["holds"] is True
    assert evaluate_check(["fact:flag", "==", True], MINI, None, "")["holds"] is True
    assert evaluate_check(["shot:arm", "!=", "baseline"], MINI, MINI_SHOTS, "b1")["holds"] is True


@pytest.mark.parametrize("check, code", [
    (["fact:x", "~", 1], "bad_check"),
    (["fact:x", ">"], "bad_check"),
    ("fact:x > 1", "bad_check"),
    (["fact:word", "<", 1], "bad_check"),
    (["fact:nope", "==", 1], "unknown_fact"),
    (["shot:arm", "==", "ruled"], "unbound_shot"),
])
def test_evaluate_check_refuses(check, code):
    """Would catch a malformed or unresolvable check being treated as holding."""
    with pytest.raises(NarrationError) as err:
        evaluate_check(check, MINI, None, "")
    assert err.value.code == code


def test_estimate_seconds_counts_words_numerals_and_rate():
    """Would catch a speaking-time plan that ignores how slowly numerals are read."""
    assert estimate_seconds("It is gone.", -1) == pytest.approx(0.7 + 3 * 0.36)
    # three plain words and one two-digit numeral
    assert estimate_seconds("It has 12 cars.", -1) == pytest.approx(0.7 + 3 * 0.36 + 0.5 + 2 * 0.40)
    assert estimate_seconds("It is gone.", 0) == pytest.approx(1.78 / 1.10, abs=1e-3)
    assert estimate_seconds("It is gone.", -2) == pytest.approx(1.78 * 1.10, abs=1e-3)
    assert estimate_seconds("It is gone.", -2) > estimate_seconds("It is gone.", -1)


def test_lint_refuses_a_spelled_number():
    """Would catch 'eighteen walkers' slipping past a check that only reads digits."""
    assert lint("Eighteen walkers changed.", "fact", False, True) == ["number_word:eighteen"]
    assert lint("Both cars drove twice.", "fact", True, True) == ["number_word:both,twice"]
    assert lint("18 walkers changed.", "fact", True, False) == []


def test_lint_refuses_a_claim_word_without_a_check_or_a_measured_number():
    """Would catch a comparison stated with nothing behind it."""
    assert lint("The trips are longer.", "fact", False, False) == ["overclaim:longer"]
    assert lint("The trips are longer.", "fact", False, True) == []
    assert lint("The trips are 35 seconds longer.", "fact", True, False) == []
    assert lint("It is gone.", "shot", False, False) == ["overclaim:gone"]
    assert lint("It is gone.", "shot", False, True) == []


def test_lint_refuses_a_say_sentence_that_states_something():
    """Would catch an unbound 'say' line carrying a number or a comparison."""
    assert lint("We ran it 2 times.", "say", False, False) == ["say_with_number"]
    assert lint("The trips are longer.", "say", False, False) == ["say_with_claim:longer"]
    assert lint("The trips are longer.", "say", False, True) == ["say_with_claim:longer"]
    assert lint("What happens to the city?", "say", False, False) == []


def test_lint_refuses_a_long_or_an_empty_sentence():
    """Would catch a sentence too long for the A1/A2 listener the factory writes for."""
    at_limit = " ".join(["word"] * MAX_WORDS) + "."
    assert lint(at_limit, "say", False, False) == []
    over = lint(" ".join(["word"] * (MAX_WORDS + 1)) + ".", "say", False, False)
    assert len(over) == 1 and over[0].startswith("too_long:")
    assert lint("...", "say", False, False) == ["empty"]


def test_number_and_claim_words_do_not_overlap_and_are_lower_case():
    """Would catch a refused word that can never match because `words_of` lower-cases."""
    assert not NUMBER_WORDS & CLAIM_WORDS
    assert all(w == w.lower() for w in NUMBER_WORDS | CLAIM_WORDS)


# ===================================================================================
# NARRATION: the real episode
# ===================================================================================

def test_narration_is_sealed_and_deterministic(factory_story, factory_facts, factory_shots,
                                               factory_brief, factory_narration):
    """Would catch a narration that differs between two bindings of the same evidence."""
    verify_seal(factory_narration, "narration_hash", "narration")
    again = bind_narration(factory_story, factory_facts, factory_shots, rate=factory_brief["voice_rate"])
    assert again["narration_hash"] == factory_narration["narration_hash"]
    assert canonical_bytes(again) == canonical_bytes(factory_narration)
    assert factory_narration["picture_claims"] == "planned"
    assert factory_narration["render_hash"] is None
    assert factory_narration["story_hash"] == factory_story["story_hash"]
    assert factory_narration["shots_hash"] == factory_shots["shots_hash"]


def test_narration_has_one_line_per_story_sentence_in_order(factory_story, factory_narration):
    """Would catch a sentence dropped, added or reordered between the story and what is spoken."""
    want = [(b["id"], l["id"], l["template"]) for b in factory_story["beats"] for l in b["lines"]]
    have = [(l["beat"], l["id"], l["template"]) for l in factory_narration["lines"]]
    assert have == want
    assert factory_narration["counts"]["sentences"] == len(want)


def test_every_fact_and_shot_sentence_is_bound_and_every_check_holds(factory_narration):
    """Would catch a claim that reaches the voice with no evidence, or with a failed check."""
    kinds = set()
    for l in factory_narration["lines"]:
        kinds.add(l["kind"])
        if l["kind"] == "say":
            assert not l["cites"] and not l["checks"], l["id"]
            continue
        assert l["cites"] or l["checks"], l["id"]
        assert all(c["holds"] is True for c in l["checks"]), l["id"]
        refs = [c["ref"] for c in l["cites"]] + \
               [x for c in l["checks"] for x in (c["left"], c["right"]) if isinstance(x, str)]
        if l["kind"] == "shot":
            assert any(r.startswith("shot") for r in refs), l["id"]
        else:
            assert any(r.startswith(("fact:", "text:")) for r in refs), l["id"]
    assert kinds == {"fact", "shot", "say"}


def test_every_numeral_spoken_is_a_cited_value_at_its_stated_precision(factory_narration,
                                                                      factory_facts, factory_shots):
    """Would catch a number in the spoken text that is not the measured value it cites."""
    numeral = re.compile(r"\d+(?:\.\d+)?")
    seen = 0
    for l in factory_narration["lines"]:
        expected = []
        for c in l["cites"]:
            ref, v = c["ref"], c["value"]
            # the cited value is the one in the sealed evidence, read here without the module
            if ref.startswith("fact:"):
                assert factory_facts["facts"][ref[5:]]["value"] == v, l["id"]
            elif ref.startswith("shot:"):
                assert factory_shots["shots"][l["beat"]][ref[5:]] == v, l["id"]
            if isinstance(v, str):
                assert not numeral.search(v), l["id"]
                assert v in l["text"], l["id"]
                continue
            assert isinstance(v, (int, float)) and not isinstance(v, bool), l["id"]
            d = c["decimals"]
            if isinstance(v, int):
                assert d == 0, l["id"]
                expected.append(str(v))
            else:
                expected.append(f"{round(v, d):.{d}f}")
        found = numeral.findall(l["text"])
        assert sorted(found) == sorted(expected), (l["id"], l["text"])
        seen += len(found)
        if l["kind"] == "say":
            assert not found, l["id"]
    assert seen > 20


def test_no_spoken_sentence_spells_a_number_or_runs_long(factory_narration):
    """Would catch a spelled quantity or an over-long sentence in the text that is spoken."""
    word = re.compile(r"[A-Za-z']+")
    for l in factory_narration["lines"]:
        ws = [w.lower() for w in word.findall(l["text"])]
        assert 0 < len(ws) <= MAX_WORDS, l["id"]
        assert not set(ws) & NUMBER_WORDS, l["id"]
        assert l["words"] == len(ws)


# --- overclaim attacks -------------------------------------------------------------------

def _bind(story, facts, shots, brief, **kw):
    return bind_narration(story, facts, shots, rate=brief["voice_rate"], **kw)


def test_the_attack_helper_itself_is_accepted_when_it_changes_nothing_false(
        factory_story, factory_facts, factory_shots, factory_brief):
    """Would catch the attacks below being refused for their lineage rather than their claim."""
    story, shots = _attack_line(factory_story, factory_shots, "reveal", 4, planned_seconds=99.0)
    assert story["story_hash"] != factory_story["story_hash"]
    doc = _bind(story, factory_facts, shots, factory_brief)
    assert [l["text"] for l in doc["lines"]] == \
        [l["text"] for l in bind_narration(factory_story, factory_facts, factory_shots,
                                           rate=factory_brief["voice_rate"])["lines"]]


def test_a_typed_number_is_refused(factory_story, factory_facts, factory_shots, factory_brief):
    """Would catch '35 seconds more' typed into a template instead of bound to the fact."""
    story, shots = _attack_line(factory_story, factory_shots, "reveal", 4,
                                template="That is 35 seconds more.", planned_seconds=99.0)
    with pytest.raises(NarrationError) as err:
        _bind(story, factory_facts, shots, factory_brief)
    assert err.value.code == "unbound_number"


def test_a_spelled_number_is_refused(factory_story, factory_facts, factory_shots, factory_brief):
    """Would catch 'Eighteen walkers changed' even though it is true and carries a holding check."""
    story, shots = _attack_line(factory_story, factory_shots, "reveal", 4,
                                template="Eighteen walkers changed.", planned_seconds=99.0,
                                checks=[["fact:walkers_changed_route", "==", 18]])
    with pytest.raises(NarrationError) as err:
        _bind(story, factory_facts, shots, factory_brief)
    assert err.value.code == "refused_sentence"


def test_a_comparison_citing_nothing_is_refused(factory_story, factory_facts, factory_shots,
                                                factory_brief):
    """Would catch 'The trips are longer.' said as a fact with no evidence at all (unbound_claim)."""
    story, shots = _attack_line(factory_story, factory_shots, "reveal", 4,
                                template="The trips are longer.", planned_seconds=99.0, checks=None)
    with pytest.raises(NarrationError) as err:
        _bind(story, factory_facts, shots, factory_brief)
    assert err.value.code == "unbound_claim"


def test_a_comparison_citing_only_a_street_name_is_refused(factory_story, factory_facts,
                                                           factory_shots, factory_brief):
    """Would catch a comparison laundered through a string citation (refused_sentence: overclaim)."""
    story, shots = _attack_line(factory_story, factory_shots, "reveal", 4, planned_seconds=99.0,
                                template="The trips on {$streets.closed.street} are longer.",
                                checks=None)
    with pytest.raises(NarrationError) as err:
        _bind(story, factory_facts, shots, factory_brief)
    assert err.value.code == "refused_sentence"


def test_a_false_check_is_refused(factory_story, factory_facts, factory_shots, factory_brief):
    """Would catch a sentence whose own check the measurement contradicts."""
    story, shots = _attack_line(
        factory_story, factory_shots, "reveal", 4, template="The trips are shorter.",
        planned_seconds=99.0,
        checks=[["fact:avg_duration_s_with_rule", "<", "fact:avg_duration_s_without_rule"]])
    with pytest.raises(NarrationError) as err:
        _bind(story, factory_facts, shots, factory_brief)
    assert err.value.code == "check_failed"


def test_a_say_line_carrying_a_check_is_refused(factory_story, factory_facts, factory_shots,
                                                factory_brief):
    """Would catch a 'say' line being used to smuggle a bound claim past the kind rules."""
    assert _beat(factory_story, "hook")["lines"][1]["kind"] == "say"
    story, shots = _attack_line(factory_story, factory_shots, "hook", 1,
                                checks=[["fact:blocks_closed", "==", 1]])
    with pytest.raises(NarrationError) as err:
        _bind(story, factory_facts, shots, factory_brief)
    assert err.value.code == "bad_kind"
    story, shots = _attack_line(factory_story, factory_shots, "hook", 1, kind="aside")
    with pytest.raises(NarrationError) as err:
        _bind(story, factory_facts, shots, factory_brief)
    assert err.value.code == "bad_kind"


def test_a_shot_line_bound_to_no_shot_measurement_is_refused(factory_story, factory_facts,
                                                             factory_shots, factory_brief):
    """Would catch a statement about the picture backed by nothing, or only by the fact sheet."""
    assert _beat(factory_story, "hook")["lines"][2]["kind"] == "shot"
    for checks in (None, [["fact:cars_on_closed_block_without_rule", ">", 0]]):
        story, shots = _attack_line(factory_story, factory_shots, "hook", 2, checks=checks)
        with pytest.raises(NarrationError) as err:
            _bind(story, factory_facts, shots, factory_brief)
        assert err.value.code == "unbound_claim"


def test_a_fact_line_bound_only_to_a_shot_is_refused(factory_story, factory_facts, factory_shots,
                                                     factory_brief):
    """Would catch a 'measured fact' whose only evidence is one camera's picture."""
    story, shots = _attack_line(factory_story, factory_shots, "reveal", 4, planned_seconds=99.0,
                                template="Cars drive here.",
                                checks=[["shot:subjects_visible_max", ">=", 1]])
    with pytest.raises(NarrationError) as err:
        _bind(story, factory_facts, shots, factory_brief)
    assert err.value.code == "unbound_claim"


def test_a_sentence_longer_than_its_plan_is_refused(factory_story, factory_facts, factory_shots,
                                                    factory_brief):
    """Would catch a filled sentence that needs more time than the story planned for it."""
    story, shots = _attack_line(factory_story, factory_shots, "reveal", 4, planned_seconds=0.5)
    with pytest.raises(NarrationError) as err:
        _bind(story, factory_facts, shots, factory_brief)
    assert err.value.code == "outruns_plan"


def test_narration_refuses_a_story_from_other_facts(factory_story, factory_facts, factory_shots,
                                                    factory_brief):
    """Would catch sentences being filled from a fact sheet the story was not selected from."""
    story = seal({**factory_story, "facts_hash": "0" * 64}, "story_hash")
    shots = seal({**factory_shots, "story_hash": story["story_hash"]}, "shots_hash")
    with pytest.raises(NarrationError) as err:
        _bind(story, factory_facts, shots, factory_brief)
    assert err.value.code == "stale_lineage"


def test_narration_refuses_shots_planned_for_another_story(factory_story, factory_facts,
                                                           factory_shots, factory_brief):
    """Would catch picture claims being bound to shots of a different story or fact sheet."""
    for field in ("story_hash", "facts_hash"):
        shots = seal({**factory_shots, field: "0" * 64}, "shots_hash")
        with pytest.raises(NarrationError) as err:
            _bind(factory_story, factory_facts, shots, factory_brief)
        assert err.value.code == "stale_lineage"


def test_narration_refuses_a_beat_with_no_shot(factory_story, factory_facts, factory_shots,
                                               factory_brief):
    """Would catch a beat narrated although the camera planner produced no shot for it."""
    rows = {k: v for k, v in factory_shots["shots"].items() if k != "detour"}
    shots = seal({**factory_shots, "shots": rows}, "shots_hash")
    with pytest.raises(NarrationError) as err:
        _bind(factory_story, factory_facts, shots, factory_brief)
    assert err.value.code == "unbound_shot"


# --- the rendered picture -----------------------------------------------------------------

def test_with_a_render_the_picture_sentences_state_the_engine_numbers(
        factory_story, factory_facts, factory_shots, factory_brief, factory_narration):
    """Would catch 'at least N in the picture' still quoting the plan after the engine measured it."""
    plan_before = factory_shots["shots"]["walkers_before"]["subjects_visible_min"]
    plan_detour = factory_shots["shots"]["detour"]["subjects_visible_min"]
    assert plan_before >= 11 and plan_detour >= 11          # so the engine numbers keep two digits
    pic = _picture(factory_shots, walkers_before={"engine_subjects_visible_min": plan_before - 1},
                   detour={"engine_subjects_visible_min": plan_detour - 2})
    doc = _bind(factory_story, factory_facts, factory_shots, factory_brief, picture=pic)
    assert doc["picture_claims"] == "engine_confirmed"
    assert doc["render_hash"] == "x" * 64
    verify_seal(doc, "narration_hash", "narration")
    assert doc["narration_hash"] != factory_narration["narration_hash"]
    stated = {}
    for l in doc["lines"]:
        for c in l["cites"]:
            if c["ref"] == "shot:subjects_visible_min":
                stated[l["beat"]] = (c["value"], l["text"])
    assert stated["walkers_before"][0] == plan_before - 1
    assert stated["detour"][0] == plan_detour - 2
    assert re.findall(r"\d+", stated["walkers_before"][1]) == [str(plan_before - 1)]
    assert re.findall(r"\d+", stated["detour"][1]) == [str(plan_detour - 2)]
    # the input was not polluted with the manifest
    assert "_picture" not in factory_shots


def test_an_engine_measurement_that_breaks_a_check_is_refused(factory_story, factory_facts,
                                                              factory_shots, factory_brief):
    """Would catch 'none of them are in this picture' said over a render that shows one."""
    pic = _picture(factory_shots, walkers_after={"engine_subjects_visible_max": 1})
    with pytest.raises(NarrationError) as err:
        _bind(factory_story, factory_facts, factory_shots, factory_brief, picture=pic)
    assert err.value.code == "check_failed"
    pic = _picture(factory_shots, moved={"engine_subjects_visible_last": 1})
    with pytest.raises(NarrationError) as err:
        _bind(factory_story, factory_facts, factory_shots, factory_brief, picture=pic)
    assert err.value.code == "check_failed"


def test_a_render_of_other_shots_is_refused(factory_story, factory_facts, factory_shots,
                                            factory_brief):
    """Would catch picture claims confirmed by a render made from a different shot plan."""
    pic = {**_picture(factory_shots), "shots_hash": "0" * 64}
    with pytest.raises(NarrationError) as err:
        _bind(factory_story, factory_facts, factory_shots, factory_brief, picture=pic)
    assert err.value.code == "stale_lineage"


def test_a_render_that_did_not_measure_a_beat_is_refused(factory_story, factory_facts,
                                                         factory_shots, factory_brief):
    """Would catch a picture claim falling back to the plan when the engine measured nothing."""
    pic = _picture(factory_shots)
    del pic["shots"]["walkers_before"]
    with pytest.raises(NarrationError) as err:
        _bind(factory_story, factory_facts, factory_shots, factory_brief, picture=pic)
    assert err.value.code == "unbound_shot"


# ===================================================================================
# CAMERA: geometry units
# ===================================================================================

RES = [1920, 1080]


def _lens(loc=(0.0, 0.0, 0.0), rot=(0.0, 0.0, 0.0), fov=90.0):
    return Lens(list(loc), list(rot), fov, RES)


def test_lens_projects_a_point_straight_ahead_to_the_centre():
    """Would catch a wrong forward axis: 1000 cm ahead is depth 1000 at the picture's centre."""
    depth, h, v = _lens().project(1000.0, 0.0, 0.0)
    assert (depth, h, v) == pytest.approx((1000.0, 0.0, 0.0))


def test_lens_projects_sideways_and_upwards_as_fractions_of_the_half_picture():
    """Would catch a wrong field-of-view or aspect term: tan_h = 1, tan_v = 1080/1920."""
    lens = _lens()
    assert lens.tan_h == pytest.approx(1.0) and lens.tan_v == pytest.approx(0.5625)
    assert lens.project(1000.0, 500.0, 0.0) == pytest.approx((1000.0, 0.5, 0.0))
    assert lens.project(1000.0, -1000.0, 0.0) == pytest.approx((1000.0, -1.0, 0.0))
    assert lens.project(1000.0, 0.0, 281.25) == pytest.approx((1000.0, 0.0, 0.5))


def test_lens_reports_a_point_behind_it_as_unprojectable():
    """Would catch a body behind the camera being mirrored into the picture."""
    depth, h, v = _lens().project(-10.0, 0.0, 0.0)
    assert depth == pytest.approx(-10.0)
    assert h == float("inf") and v == float("inf")


def test_lens_follows_its_yaw_and_pitch():
    """Would catch a rotation convention that does not match `look_rot`."""
    assert look_rot([0.0, 0.0, 0.0], [100.0, 100.0, 0.0]) == [0.0, 45.0, 0.0]
    assert look_rot([0.0, 0.0, 100.0], [100.0, 0.0, 0.0]) == [-45.0, 0.0, 0.0]
    assert _lens(rot=(0.0, 90.0, 0.0)).project(0.0, 1000.0, 0.0) == pytest.approx((1000.0, 0.0, 0.0))
    down = _lens(loc=(0.0, 0.0, 100.0), rot=look_rot([0.0, 0.0, 100.0], [100.0, 0.0, 0.0]))
    depth, h, v = down.project(100.0, 0.0, 0.0)
    assert depth == pytest.approx(141.4214, abs=1e-3)
    assert (h, v) == pytest.approx((0.0, 0.0), abs=1e-9)


def test_lens_height_in_pixels():
    """Would catch a wrong size estimate: 170 cm at 1000 cm fills 170/1125 of 1080 px."""
    assert _lens().height_px(1000.0, 170.0) == pytest.approx(163.2)
    assert _lens().height_px(2000.0, 170.0) == pytest.approx(81.6)


def test_sees_names_why_a_body_is_not_held():
    """Would catch a subject counted although it is too near, out of frame, a dot, or hidden."""
    lens = _lens(loc=(0.0, 0.0, 85.0))
    block = {"x_min": 400.0, "x_max": 600.0, "y_min": -100.0, "y_max": 100.0}
    aside = {"x_min": 400.0, "x_max": 600.0, "y_min": 300.0, "y_max": 500.0}
    assert sees(lens, 1000.0, 0.0, "person", []) == "visible"
    assert sees(lens, 1000.0, 0.0, "person", [aside]) == "visible"
    assert sees(lens, 100.0, 0.0, "person", []) == "behind_or_too_near"
    assert sees(lens, -1000.0, 0.0, "person", []) == "behind_or_too_near"
    assert sees(lens, 1000.0, 950.0, "person", []) == "out_of_frame"          # h = 0.95 > 0.92
    assert sees(lens, 1000.0, 900.0, "person", []) == "visible"               # h = 0.90
    assert sees(lens, 1000.0, 0.0, "person", [block]) == "behind_a_block"
    assert sees(lens, 1000.0, 0.0, "person", [aside, block]) == "behind_a_block"


def test_sees_applies_the_size_floor_of_the_subject_kind():
    """Would catch a person counted as a figure when it is under 22 px (a car needs 14 px)."""
    lens = _lens(loc=(0.0, 0.0, 85.0))
    # at 8000 cm: a person is 163200/8000 = 20.4 px, a car 144000/8000 = 18 px
    assert sees(lens, 8000.0, 0.0, "person", []) == "too_small"
    assert sees(lens, 8000.0, 0.0, "vehicle", []) == "visible"
    assert sees(lens, 7000.0, 0.0, "person", []) == "visible"                 # 23.3 px
    assert sees(lens, 11000.0, 0.0, "vehicle", []) == "too_small"             # 13.1 px


def test_a_high_camera_looking_level_loses_the_body_below_the_frame():
    """Would catch the vertical safe area being ignored."""
    lens = _lens(loc=(0.0, 0.0, 1085.0))
    # body centre 1000 cm below the axis at depth 1000: v = -1000/562.5
    assert sees(lens, 1000.0, 0.0, "person", []) == "out_of_frame"


BOX = {"x_min": 0.0, "x_max": 10.0, "y_min": 0.0, "y_max": 10.0}


@pytest.mark.parametrize("seg, hit", [
    ((-5.0, 5.0, 15.0, 5.0), True),        # straight through
    ((2.0, 2.0, 8.0, 8.0), True),          # wholly inside
    ((5.0, 5.0, 5.0, 20.0), True),         # starts inside
    ((-5.0, 8.0, 2.0, 15.0), False),       # diagonal past the corner
    ((-5.0, 5.0, -1.0, 5.0), False),       # stops short
    ((-5.0, 20.0, 15.0, 20.0), False),     # parallel to x, outside
    ((20.0, -5.0, 20.0, 15.0), False),     # parallel to y, outside
    ((-5.0, 10.0, 15.0, 10.0), True),      # touching: runs along the top edge
    ((-5.0, 5.0, 0.0, 5.0), True),         # touching: ends on the left edge
    ((-5.0, 15.0, 5.0, 5.0), True),        # ends inside, entering through the corner region
    ((-10.0, 10.0, 0.0, 20.0), False),     # diagonal, misses
])
def test_seg_hits_rect(seg, hit):
    """Would catch a sight line through a block being passed, or a clear one refused."""
    assert _seg_hits_rect(*seg, BOX) is hit
    ax, ay, bx, by = seg
    assert _seg_hits_rect(bx, by, ax, ay, BOX) is hit       # direction does not matter


# --- check_requirement -------------------------------------------------------------------

def _m(per):
    return {"per_sample": list(per)}


def test_requirement_min_visible_with_a_fraction():
    """Would catch a shot passing when fewer samples than required hold the subjects."""
    assert check_requirement({"min_visible": 2, "fraction": 0.75}, _m([2, 2, 0, 3]), 0.0) == (True, 0.75)
    assert check_requirement({"min_visible": 2, "fraction": 0.8}, _m([2, 2, 0, 3]), 0.0) == (False, 0.75)
    # no fraction stated: every sample must meet it
    assert check_requirement({"min_visible": 2}, _m([2, 2, 0, 3]), 0.0) == (False, 0.75)
    assert check_requirement({"min_visible": 2}, _m([2, 2, 2, 3]), 0.0) == (True, 1.0)
    assert check_requirement({"min_visible": 1}, _m([]), 0.0) == (False, 0.0)


def test_requirement_max_visible_is_an_absence_over_every_sample():
    """Would catch an absence claim passing although one sample shows a subject."""
    assert check_requirement({"max_visible": 0}, _m([0, 0, 0]), 0.0) == (True, 1.0)
    met, frac = check_requirement({"max_visible": 0}, _m([0, 0, 1]), 0.0)
    assert met is False and frac == pytest.approx(2 / 3)
    assert check_requirement({"max_visible": 1}, _m([0, 1, 1]), 0.0) == (True, 1.0)
    # a stated fraction does not soften an absence
    assert check_requirement({"max_visible": 0, "fraction": 0.5}, _m([0, 0, 1]), 0.0)[0] is False


EVENT = {"min_visible": 1, "until": 1.0, "then_absent": True}


def test_requirement_event_is_met_when_held_before_and_absent_after():
    """Would catch a real disappearance being refused: samples at 0, 0.5 | 1.0 | 1.5, 2.0 s."""
    assert check_requirement(EVENT, _m([1, 1, 1, 0, 0]), 0.0) == (True, 1.0)
    assert check_requirement(EVENT, _m([1, 1, 0, 0, 0]), 0.0) == (True, 1.0)   # the event sample is not judged
    # the same samples placed on the clock by t0
    assert check_requirement({**EVENT, "until": 101.0}, _m([1, 1, 1, 0, 0]), 100.0) == (True, 1.0)
    assert check_requirement(EVENT, _m([1, 1, 1, 0, 0]), 0.0,
                             times=[0.0, 0.5, 1.0, 1.5, 2.0]) == (True, 1.0)


def test_requirement_event_is_not_met_when_the_subject_is_still_there_after():
    """Would catch 'it is gone' over a picture that still holds the car."""
    met, frac = check_requirement(EVENT, _m([1, 1, 1, 1, 0]), 0.0)
    assert met is False and frac == pytest.approx(0.75)
    assert check_requirement(EVENT, _m([1, 1, 1, 0, 1]), 0.0)[0] is False


def test_requirement_event_is_not_met_when_the_subject_was_absent_before():
    """Would catch a disappearance narrated of a car the camera never held."""
    met, frac = check_requirement(EVENT, _m([0, 1, 1, 0, 0]), 0.0)
    assert met is False and frac == pytest.approx(0.75)
    assert check_requirement(EVENT, _m([0, 0, 0, 0, 0]), 0.0)[0] is False


def test_requirement_event_is_not_met_without_samples_on_both_sides():
    """Would catch an event at the very edge of a shot passing with nothing to judge it by."""
    assert check_requirement(EVENT, _m([1, 1, 1]), 0.0)[0] is False            # nothing after
    assert check_requirement(EVENT, _m([1, 1, 1, 0, 0]), 1.0)[0] is False      # nothing before
    # without then_absent only the 'before' samples are judged
    assert check_requirement({"min_visible": 1, "until": 1.0}, _m([1, 1, 5, 5, 5]), 0.0) == (True, 1.0)
    assert check_requirement({"min_visible": 1, "until": 1.0}, _m([1, 0, 5, 5, 5]), 0.0)[0] is False


# --- measure on a hand-built record --------------------------------------------------------

def _tiny_record():
    """Two people 1000 cm ahead of the origin; B (200 cm aside, walking) leaves after frame 1."""
    rec = Record(Path("."), {"clock": {"step_seconds": 0.5, "frame_count": 5},
                             "binary": {"sha256": "tiny"}})
    for uid, y, frames, speed in (("person:a", 0.0, range(5), 0.0), ("person:b", 200.0, range(2), 1.0)):
        t = Track(uid, "person")
        for f in frames:
            t.frames.append(f)
            t.x.append(1000.0)
            t.y.append(y)
            t.yaw.append(0.0)
            t.speed.append(speed)
        rec.tracks[uid] = t
    return rec


def test_measure_counts_per_sample_and_says_why_not():
    """Would catch a wrong per-sample count, or an absent subject counted as held."""
    rec = _tiny_record()
    lens = _lens(loc=(0.0, 0.0, 85.0))
    m = measure(lens, rec, rec.select(["person:a", "person:b"]), 0.0, 2.0, [])
    assert m["samples"] == 5
    assert m["per_sample"] == [2, 2, 1, 1, 1]
    assert (m["visible_min"], m["visible_max"], m["visible_mean"]) == (1, 2, 1.4)
    assert (m["stopped_min"], m["stopped_max"]) == (1, 1)
    assert m["speed_max_mps"] == 1.0
    assert m["mean_height_px"] == 163.2
    assert m["not_visible_reasons"] == {"absent": 3}


def test_measure_counts_only_stopped_subjects_or_only_those_on_the_street_when_told_to():
    """Would catch a moving car counted as 'standing still', or a subject off the street counted on it."""
    rec = _tiny_record()
    lens = _lens(loc=(0.0, 0.0, 85.0))
    tracks = rec.select(["person:a", "person:b"])
    m = measure(lens, rec, tracks, 0.0, 2.0, [], stopped_only=True)
    assert m["per_sample"] == [1, 1, 1, 1, 1]
    assert m["not_visible_reasons"] == {"absent": 3, "moving": 2}
    assert m["speed_max_mps"] == 0.0
    m = measure(lens, rec, tracks, 0.0, 2.0, [], corridor=([(0.0, 0.0, 2000.0, 0.0)], 100.0))
    assert m["per_sample"] == [1, 1, 1, 1, 1]
    assert m["not_visible_reasons"] == {"absent": 3, "off_street": 2}
    block = {"x_min": 400.0, "x_max": 600.0, "y_min": -50.0, "y_max": 50.0}
    m = measure(lens, rec, tracks, 0.0, 2.0, [block])
    assert m["per_sample"] == [1, 1, 0, 0, 0]
    assert m["not_visible_reasons"] == {"absent": 3, "behind_a_block": 5}


# ===================================================================================
# CAMERA: the real episode
# ===================================================================================

def test_shots_are_deterministic_and_equal_the_sealed_ones(plan, factory_story, factory_shots,
                                                           factory_pkg):
    """Would catch a planner that depends on anything but the record, the facts and the story."""
    again = plan(factory_story)
    assert again["shots_hash"] == factory_shots["shots_hash"]
    assert canonical_bytes(again) == canonical_bytes(factory_shots)
    verify_seal(factory_shots, "shots_hash", "shots")
    assert list(factory_shots["shots"]) == _ids(factory_story)
    on_disk = Path(factory_pkg) / "shots.json"
    if on_disk.is_file():
        assert load(on_disk)["shots_hash"] == factory_shots["shots_hash"]


def test_every_shot_holds_its_requirement_when_measured_again(factory_shots, factory_recs,
                                                              factory_net, factory_blocks, res):
    """Would catch a shot marked 'pass' whose camera, re-measured from the record, misses its claim."""
    for bid, shot in factory_shots["shots"].items():
        assert shot["verdict"] == "pass", bid
        m = remeasure(shot, factory_recs[shot["arm"]], factory_net, factory_blocks, res)
        assert m["per_sample"] == shot["subjects_visible_per_sample"], bid
        assert (m["visible_min"], m["visible_max"]) == \
            (shot["subjects_visible_min"], shot["subjects_visible_max"]), bid
        assert shot["subjects_visible_last"] == m["per_sample"][-1], bid
        met, frac = check_requirement(shot["require"], m, shot["sim_start"])
        assert met, bid
        assert round(frac, 4) == shot["samples_meeting_requirement"], bid
        assert len(m["per_sample"]) == int(round(shot["seconds"] / PARAMS["sample_seconds"])) + 1, bid


def test_every_comparison_shot_reuses_camera_and_minute_in_the_other_arm(factory_shots,
                                                                        factory_story):
    """Would catch a 'same camera, same minute' claim over a different camera, time or the same arm."""
    seen = 0
    for b in factory_story["beats"]:
        ref = b["visual"].get("same_as")
        if ref is None:
            assert "same_camera_as" not in factory_shots["shots"][b["id"]]["camera"]
            continue
        seen += 1
        shot, src = factory_shots["shots"][b["id"]], factory_shots["shots"][ref]
        for k in ("loc", "rot", "fov_deg"):
            assert shot["camera"][k] == src["camera"][k], (b["id"], k)
        assert shot["camera"]["same_camera_as"] == ref
        assert shot["sim_start"] == src["sim_start"], b["id"]
        assert shot["arm"] != src["arm"], b["id"]
        assert {shot["arm"], src["arm"]} == {"baseline", "ruled"}
    assert seen >= 4


def test_absence_shots_measure_no_subject_at_any_sample(factory_shots):
    """Would catch an absence claimed over a shot in which a subject appears."""
    absent = [s for s in factory_shots["shots"].values() if "max_visible" in s["require"]]
    assert {s["beat"] for s in absent} >= {"rule", "walkers_after", "detour_before"}
    for s in absent:
        assert (s["subjects_visible_min"], s["subjects_visible_max"]) == (0, 0), s["beat"]
        assert set(s["subjects_visible_per_sample"]) == {0}, s["beat"]
        # and the subjects it is an absence OF exist in that arm's record
        assert s["subjects"]["count"] > 0, s["beat"]


def test_every_shot_starts_on_a_whole_second_inside_the_record(factory_shots, factory_recs):
    """Would catch a shot starting between frames, or running past the end of the record."""
    for bid, s in factory_shots["shots"].items():
        rec = factory_recs[s["arm"]]
        assert s["sim_start"] == int(s["sim_start"]), bid
        assert s["sim_end"] == s["sim_start"] + s["seconds"], bid
        assert rec.t_begin <= s["sim_start"] and s["sim_end"] <= rec.time_of(rec.frame_count - 1), bid
        assert s["record_frames_sha256"] == rec.frames_sha256, bid


def test_no_stretch_of_footage_is_shown_twice(factory_shots):
    """Would catch the same camera on the same arm over overlapping simulated time in two beats."""
    rows = list(factory_shots["shots"].values())
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            same = (a["arm"] == b["arm"] and a["camera"]["loc"] == b["camera"]["loc"]
                    and a["camera"]["rot"] == b["camera"]["rot"])
            overlap = a["sim_start"] < b["sim_end"] and b["sim_start"] < a["sim_end"]
            assert not (same and overlap), (a["beat"], b["beat"])


def test_the_removal_event_happens_inside_its_shot_and_the_car_is_gone_at_the_end(factory_shots,
                                                                                 factory_story):
    """Would catch 'Watch. It is gone.' over a shot that ends before, or starts after, the removal."""
    shot = factory_shots["shots"]["moved"]
    ev = shot["event"]
    assert shot["sim_start"] < ev["second"] < shot["sim_end"]
    assert ev["second"] == _beat(factory_story, "moved")["event"]["second"]
    assert shot["sim_start"] + ev["offset_seconds"] == pytest.approx(ev["second"])
    per = shot["subjects_visible_per_sample"]
    assert per[-1] == 0 and shot["subjects_visible_last"] == 0
    times = [shot["sim_start"] + k * PARAMS["sample_seconds"] for k in range(len(per))]
    assert all(c >= 1 for c, t in zip(per, times) if t <= ev["second"] - 0.5)
    assert all(c == 0 for c, t in zip(per, times) if t >= ev["second"] + 0.5)
    assert shot["subjects"]["uids"] == [_beat(factory_story, "moved")["event"]["subject"]]


def test_marks_name_the_followed_walkers_and_the_beats_own_subjects(factory_shots, factory_facts):
    """Would catch 'it has a red ball' over a shot whose red mark is on other actors."""
    for bid, s in factory_shots["shots"].items():
        assert s["marks"]["yellow"]["uids"] == sorted(factory_facts["groups"]["walkers"]), bid
    stuck = factory_shots["shots"]["stuck"]
    assert stuck["marks"]["red"]["uids"] == stuck["subjects"]["uids"]
    assert stuck["marks"]["red"]["count"] == 1
    assert stuck["counted_stopped_only"] is True and stuck["subjects_speed_max_mps"] < 0.1


def test_a_one_beat_story_plans_the_same_shot_as_the_full_story(plan, factory_story, factory_shots):
    """Would catch the adversarial cases below exercising a different planner path than the episode."""
    doc = plan(_mini_story(factory_story, ["stuck"]))
    assert list(doc["shots"]) == ["stuck"]
    assert doc["shots"]["stuck"] == factory_shots["shots"]["stuck"]


# --- the camera misses the event: fail closed ------------------------------------------------

def _refused(plan, story, **kw):
    with pytest.raises(CameraError) as err:
        plan(story, **kw)
    assert err.value.stage == "camera"
    return err.value.code


def test_camera_refuses_a_requirement_it_cannot_hold(plan, factory_story):
    """Would catch a shot being sealed although fewer subjects are held than the beat claims."""
    def edit(b, _s):
        b["stuck"]["visual"]["require"]["min_visible"] = 99
    assert _refused(plan, _mini_story(factory_story, ["stuck"], edit)) == "event_not_visible"


def test_camera_refuses_an_empty_subject_group(plan, factory_story, factory_facts):
    """Would catch a beat about followed walkers being shot when the facts name none."""
    facts = copy.deepcopy(factory_facts)
    facts["groups"]["treatment"] = []
    assert _refused(plan, _mini_story(factory_story, ["replan"]), facts=facts) == "no_subjects"


def test_camera_refuses_an_unknown_subject_group(plan, factory_story):
    """Would catch a beat's subjects silently becoming 'whoever is there'."""
    def edit(b, _s):
        b["stuck"]["visual"]["subjects"] = {"group": "ghosts"}
    assert _refused(plan, _mini_story(factory_story, ["stuck"], edit)) == "unknown_subjects"


def test_camera_refuses_named_subjects_that_are_not_in_the_measured_group(plan, factory_story,
                                                                         factory_recs):
    """Would catch 'the first stuck car' being any car the story cares to name."""
    stuck = set(_beat(factory_story, "stuck")["visual"]["subjects"]["uids"])
    other = next(u for u in sorted(factory_recs["ruled"].tracks) if u.startswith("vehicle:")
                 and u not in stuck)

    def edit(b, _s):
        b["stuck"]["visual"]["subjects"]["uids"] = [other, "vehicle:does_not_exist"]
    assert _refused(plan, _mini_story(factory_story, ["stuck"], edit)) == "unknown_subjects"


def test_camera_refuses_a_comparison_within_the_same_arm(plan, factory_story):
    """Would catch 'the closed city, same camera' being a replay of the open city's footage."""
    def edit(b, _s):
        b["walkers_after"]["visual"]["arm"] = "baseline"
    story = _mini_story(factory_story, ["walkers_before", "walkers_after"], edit)
    assert _refused(plan, story) == "footage_reused"


def test_camera_refuses_an_absence_claim_over_subjects_that_are_there(plan, factory_story):
    """Would catch 'none of them are in this picture' over a picture that holds them."""
    def edit(b, _s):
        # the detour street in the RULED arm is where the treatment walkers are;
        # claim their absence from the baseline camera's twin there
        b["detour_before"]["visual"]["subjects"] = {"group": "people"}
    story = _mini_story(factory_story, ["detour", "detour_before"], edit)
    assert _refused(plan, story) == "event_not_visible"


def test_camera_refuses_a_window_past_the_end_of_the_record(plan, factory_story, factory_recs):
    """Would catch a shot of simulated time the record does not contain."""
    rec = factory_recs["ruled"]
    end = rec.time_of(rec.frame_count - 1)
    for start in (end - 1.0, end + 500.0, -5.0):
        def edit(b, _s, start=start):
            b["stuck"]["visual"]["window"] = {"mode": "fixed", "start": start}
        assert _refused(plan, _mini_story(factory_story, ["stuck"], edit)) == "window_outside_record"


def test_camera_refuses_a_best_window_shorter_than_the_shot(plan, factory_story):
    """Would catch a shot longer than the stretch of time the beat allows it to be taken from."""
    def edit(b, _s):
        b["hook"]["visual"]["window"] = {"mode": "best", "t_min": 100.0, "t_max": 105.0}
    assert _refused(plan, _mini_story(factory_story, ["hook"], edit)) == "window_outside_record"


def test_camera_refuses_an_event_outside_its_shot(plan, factory_story):
    """Would catch an event beat whose shot does not contain the second the event happens."""
    def edit(b, _s):
        b["moved"]["event"]["second"] = b["moved"]["visual"]["window"]["start"] + 500.0
    assert _refused(plan, _mini_story(factory_story, ["moved"], edit)) == "event_not_visible"


def test_camera_refuses_an_event_shot_that_starts_after_the_event(plan, factory_story):
    """Would catch 'watch, it is removed' over a window in which the car is already gone."""
    def edit(b, _s):
        b["moved"]["visual"]["window"]["start"] = float(int(b["moved"]["event"]["second"]) + 5)
    assert _refused(plan, _mini_story(factory_story, ["moved"], edit)) == "event_not_visible"


def test_camera_refuses_an_unknown_street(plan, factory_story):
    """Would catch a camera being placed for a street the network does not have."""
    def edit(b, _s):
        b["stuck"]["visual"]["street"] = "NO_SUCH_EDGE"
    assert _refused(plan, _mini_story(factory_story, ["stuck"], edit)) == "bad_street"

    def edit(b, _s):
        del b["hook"]["visual"]["street"]
    assert _refused(plan, _mini_story(factory_story, ["hook"], edit)) == "bad_street"


def test_camera_refuses_an_unknown_on_street_mode(plan, factory_story):
    """Would catch an unknown counting rule being read as 'count everywhere'."""
    def edit(b, _s):
        b["hook"]["visual"]["on_street"] = "pavement"
    assert _refused(plan, _mini_story(factory_story, ["hook"], edit)) == "bad_visual"


def test_camera_refuses_an_unknown_visual_kind_arm_or_window_mode(plan, factory_story):
    """Would catch an unknown instruction being planned as if it were a street shot."""
    def kind(b, _s):
        b["stuck"]["visual"]["kind"] = "drone"
    assert _refused(plan, _mini_story(factory_story, ["stuck"], kind)) == "bad_visual"

    def arm(b, _s):
        b["stuck"]["visual"]["arm"] = "third"
    assert _refused(plan, _mini_story(factory_story, ["stuck"], arm)) == "bad_arm"

    def window(b, _s):
        b["stuck"]["visual"]["window"] = {"mode": "whenever"}
    assert _refused(plan, _mini_story(factory_story, ["stuck"], window)) == "bad_window"


def test_camera_refuses_a_comparison_with_a_shot_that_does_not_exist(plan, factory_story):
    """Would catch a 'same camera' beat planned with no source shot to take the camera from."""
    assert _refused(plan, _mini_story(factory_story, ["walkers_after"])) == "bad_reference"


def test_camera_refuses_two_beats_showing_the_same_footage(plan, factory_story):
    """Would catch one stretch of one arm from one camera being used for two beats."""
    def edit(_b, s):
        twin = copy.deepcopy(s["beats"][0])
        twin["id"] = "stuck_again"
        s["beats"].append(twin)
    assert _refused(plan, _mini_story(factory_story, ["stuck"], edit)) == "footage_reused"


def test_camera_refuses_a_story_from_other_facts(plan, factory_story, factory_facts):
    """Would catch shots being planned for a story selected from a different fact sheet."""
    facts = {**factory_facts, "facts_hash": "0" * 64}
    assert _refused(plan, _mini_story(factory_story, ["stuck"]), facts=facts) == "stale_lineage"


def test_camera_refuses_a_record_the_facts_were_not_extracted_from(plan, factory_story,
                                                                   factory_recs):
    """Would catch cameras being measured against a record other than the sealed one."""
    fake = copy.copy(factory_recs["ruled"])
    fake.frames_sha256 = "0" * 64
    assert factory_recs["ruled"].frames_sha256 != fake.frames_sha256
    recs = {"baseline": factory_recs["baseline"], "ruled": fake}
    assert _refused(plan, _mini_story(factory_story, ["stuck"]), recs=recs) == "stale_lineage"


# ===================================================================================
# TIMELINE and CAPTIONS
# ===================================================================================

def test_timeline_is_sealed_and_deterministic(timeline, factory_story, factory_shots,
                                              factory_narration, voice, factory_brief):
    """Would catch an edit recipe that differs between two builds from the same documents."""
    again = build_timeline(factory_story, factory_shots, factory_narration, voice, factory_brief)
    assert canonical_bytes(again) == canonical_bytes(timeline)
    verify_seal(timeline, "timeline_hash", "timeline")
    assert timeline["voice_hash"] == voice["voice_hash"]
    assert timeline["narration_hash"] == factory_narration["narration_hash"]
    assert timeline["sim_rate"] == 1.0


def test_timeline_frames_add_up_and_beats_are_contiguous(timeline, factory_story, factory_brief):
    """Would catch a gap, an overlap or a lost frame between two beats."""
    fps = factory_brief["fps"]
    assert [b["id"] for b in timeline["beats"]] == _ids(factory_story)
    frame = 0
    for b in timeline["beats"]:
        assert b["frame_start"] == frame, b["id"]
        assert b["frames"] == b["seconds"] * fps, b["id"]
        assert b["start"] == pytest.approx(frame / fps), b["id"]
        assert b["end"] == pytest.approx(b["start"] + b["seconds"]), b["id"]
        frame += b["frames"]
    assert frame == timeline["frames_total"] == sum(b["frames"] for b in timeline["beats"])
    assert timeline["seconds_total"] == pytest.approx(frame / fps)
    assert timeline["seconds_total"] == factory_story["seconds_total"]
    lo, hi = factory_brief["target_seconds"]
    assert lo <= timeline["seconds_total"] <= hi


def test_timeline_shows_each_beats_own_shot_at_one_times_speed(timeline, factory_shots):
    """Would catch a beat cut to another shot, or a shot stretched to fit its beat."""
    for b in timeline["beats"]:
        shot = factory_shots["shots"][b["id"]]
        assert b["shot"]["arm"] == shot["arm"]
        assert b["shot"]["sim_start"] == shot["sim_start"]
        assert b["shot"]["sim_end"] - b["shot"]["sim_start"] == b["seconds"], b["id"]
        assert b["shot"]["sim_rate"] == 1.0
        assert b["shot"]["camera"] == {k: shot["camera"][k] for k in ("loc", "rot", "fov_deg")}
        assert b["label"] == {"baseline": "OPEN CITY", "ruled": "CLOSED CITY"}[shot["arm"]]


def test_every_sentence_lies_inside_its_beat_with_a_tail_and_none_overlap(timeline, voice,
                                                                         factory_narration):
    """Would catch a sentence spoken over the next beat, or two sentences spoken at once."""
    spoken = {r["id"]: r["seconds"] for r in voice["lines"]}
    prev_end, ids = 0.0, []
    for b in timeline["beats"]:
        assert b["lines"], b["id"]
        for l in b["lines"]:
            ids.append(l["id"])
            assert l["start"] >= b["start"] + PACING["lead_in_seconds"] - 1e-6, l["id"]
            assert l["end"] <= b["end"] - MIN_TAIL_SECONDS + 1e-6, l["id"]
            assert l["start"] >= prev_end - 1e-6, l["id"]
            assert l["end"] - l["start"] == pytest.approx(spoken[l["id"]], abs=1e-3), l["id"]
            prev_end = l["end"]
        assert b["silence_after_last_word"] >= MIN_TAIL_SECONDS - 1e-6, b["id"]
    assert ids == [l["id"] for l in factory_narration["lines"]]


def test_the_words_after_an_event_are_not_heard_before_it(timeline):
    """Would catch 'It is gone.' being spoken while the car is still on screen."""
    beat = next(b for b in timeline["beats"] if b["id"] == "moved")
    ev = beat["event"]
    assert ev["episode_second"] == pytest.approx(beat["start"] + ev["offset_seconds"])
    # the frame rule puts the event's simulated second at that episode second
    assert beat["shot"]["sim_start"] + (ev["episode_second"] - beat["start"]) == pytest.approx(ev["second"])
    waiting = [l for l in beat["lines"] if "after_event" in l]
    assert waiting
    first = beat["lines"].index(waiting[0])
    for l in beat["lines"][first:]:
        assert l["start"] >= ev["episode_second"] + PACING["event_settle_seconds"] - 1e-6, l["id"]
    assert first > 0
    for l in beat["lines"][:first]:
        assert l["end"] <= ev["episode_second"] + 1e-6, l["id"]
    assert [b["id"] for b in timeline["beats"] if "event" in b] == ["moved"]


def test_timeline_refuses_a_voice_that_outruns_its_beats(factory_story, factory_shots,
                                                         factory_narration, factory_brief):
    """Would catch a shot being stretched, or a voice sped up, to make long audio fit."""
    with pytest.raises(TimelineError) as err:
        build_timeline(factory_story, factory_shots, factory_narration,
                       _voice(factory_narration, factor=3.0), factory_brief)
    assert err.value.code == "narration_overruns_beat"
    assert err.value.stage == "timeline"


def test_timeline_refuses_a_sentence_still_being_spoken_at_the_event(factory_story, factory_shots,
                                                                    factory_narration, factory_brief):
    """Would catch the removal happening on screen under the sentence that announces it."""
    moved = [l["id"] for l in factory_narration["lines"] if l["beat"] == "moved"]
    long = _voice(factory_narration, seconds={moved[0]: 30.0})
    with pytest.raises(TimelineError) as err:
        build_timeline(factory_story, factory_shots, factory_narration, long, factory_brief)
    assert err.value.code == "narration_overruns_event"


def test_timeline_refuses_a_sentence_with_no_audio(factory_story, factory_shots, factory_narration,
                                                   factory_brief):
    """Would catch a captioned sentence that was never synthesised."""
    missing = factory_narration["lines"][7]["id"]
    with pytest.raises(TimelineError) as err:
        build_timeline(factory_story, factory_shots, factory_narration,
                       _voice(factory_narration, drop=missing), factory_brief)
    assert err.value.code == "unspoken_line"


def test_timeline_refuses_a_voice_of_another_narration(factory_story, factory_shots,
                                                       factory_narration, voice, factory_brief):
    """Would catch audio of one script being laid under the captions of another."""
    other = seal({**voice, "narration_hash": "0" * 64}, "voice_hash")
    with pytest.raises(TimelineError) as err:
        build_timeline(factory_story, factory_shots, factory_narration, other, factory_brief)
    assert err.value.code == "stale_lineage"


def test_timeline_refuses_a_narration_of_another_story_or_other_shots(factory_story, factory_shots,
                                                                     factory_narration, factory_brief):
    """Would catch sentences bound to one plan being timed against another."""
    for field in ("story_hash", "shots_hash"):
        narration = seal({**factory_narration, field: "0" * 64}, "narration_hash")
        with pytest.raises(TimelineError) as err:
            build_timeline(factory_story, factory_shots, narration, _voice(narration), factory_brief)
        assert err.value.code == "stale_lineage"


def test_timeline_refuses_a_shot_that_starts_between_frames(factory_story, factory_shots,
                                                            factory_narration, factory_brief):
    """Would catch a shot whose first frame would have to be interpolated between record frames."""
    shots = copy.deepcopy(factory_shots)
    shots["shots"]["hook"]["sim_start"] = 10.01
    shots = seal(shots, "shots_hash")
    narration = seal({**factory_narration, "shots_hash": shots["shots_hash"]}, "narration_hash")
    with pytest.raises(TimelineError) as err:
        build_timeline(factory_story, shots, narration, _voice(narration), factory_brief)
    assert err.value.code == "off_grid"


def test_timeline_refuses_a_shot_planned_for_another_length_or_missing(factory_story, factory_shots,
                                                                      factory_narration, factory_brief):
    """Would catch a beat being filled by a shot of a different length, or by nothing."""
    def rebuilt(mutate):
        shots = copy.deepcopy(factory_shots)
        mutate(shots["shots"])
        shots = seal(shots, "shots_hash")
        narration = seal({**factory_narration, "shots_hash": shots["shots_hash"]}, "narration_hash")
        with pytest.raises(TimelineError) as err:
            build_timeline(factory_story, shots, narration, _voice(narration), factory_brief)
        return err.value.code

    assert rebuilt(lambda rows: rows["hook"].update(seconds=rows["hook"]["seconds"] + 1.0)) == "stale_lineage"
    assert rebuilt(lambda rows: rows.pop("hook")) == "missing_shot"


def test_timeline_refuses_a_length_outside_the_brief(factory_story, factory_shots, factory_narration,
                                                     voice, factory_brief):
    """Would catch an episode assembled at a length the brief did not ask for."""
    for target in ([60.0, 120.0], [900.0, 1200.0]):
        with pytest.raises(TimelineError) as err:
            build_timeline(factory_story, factory_shots, factory_narration, voice,
                           {**factory_brief, "target_seconds": target})
        assert err.value.code == "length_out_of_range"


# --- captions -------------------------------------------------------------------------------

STAMP = r"\d{2}:[0-5]\d:[0-5]\d%s\d{3}"


def test_captions_are_one_cue_per_sentence_with_the_exact_text(timeline, factory_narration):
    """Would catch a caption that paraphrases, drops or reorders what is spoken."""
    cap = build_captions(timeline)
    assert [(c["id"], c["text"]) for c in cap["cues"]] == \
        [(l["id"], l["text"]) for l in factory_narration["lines"]]
    assert [c["index"] for c in cap["cues"]] == list(range(1, len(cap["cues"]) + 1))


def test_caption_cues_are_in_order_never_overlap_and_cover_their_sentence_start(timeline):
    """Would catch two captions on screen at once, or a caption shown before its sentence."""
    cap = build_captions(timeline)
    rows = {l["id"]: l for b in timeline["beats"] for l in b["lines"]}
    prev_end = 0.0
    for c in cap["cues"]:
        assert c["start"] == pytest.approx(rows[c["id"]]["start"], abs=1e-3)
        assert c["start"] < c["end"] <= timeline["seconds_total"], c["id"]
        assert c["start"] >= prev_end, c["id"]
        prev_end = c["end"]


def test_srt_and_vtt_are_well_formed(timeline):
    """Would catch a caption file a player cannot parse."""
    cap = build_captions(timeline)
    srt_time = re.compile(r"^%s --> %s$" % (STAMP % ",", STAMP % ","))
    vtt_time = re.compile(r"^%s --> %s$" % (STAMP % r"\.", STAMP % r"\."))
    blocks = cap["srt"].strip("\n").split("\n\n")
    assert len(blocks) == len(cap["cues"])
    for block, cue in zip(blocks, cap["cues"]):
        index, times, text = block.split("\n")
        assert index == str(cue["index"])
        assert srt_time.match(times), times
        assert text == cue["text"]
    assert cap["srt"].endswith("\n\n")
    assert cap["vtt"].startswith("WEBVTT\n\n")
    vtt_blocks = cap["vtt"][len("WEBVTT\n\n"):].strip("\n").split("\n\n")
    assert len(vtt_blocks) == len(cap["cues"])
    for block, cue in zip(vtt_blocks, cap["cues"]):
        _index, times, text = block.split("\n")
        assert vtt_time.match(times), times
        assert text == cue["text"]


def test_caption_stamps_are_the_cue_times(timeline):
    """Would catch a stamp formatter that drops hours, minutes or milliseconds."""
    cap = build_captions(timeline)

    def seconds(stamp):
        h, m, rest = stamp.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

    times = [line for line in cap["srt"].split("\n") if " --> " in line]
    assert len(times) == len(cap["cues"])
    for line, cue in zip(times, cap["cues"]):
        a, b = line.split(" --> ")
        assert seconds(a) == pytest.approx(cue["start"], abs=1e-3)
        assert seconds(b) == pytest.approx(cue["end"], abs=1e-3)
    assert any(seconds(line.split(" --> ")[0]) > 60.0 for line in times)     # minutes are exercised


def test_captions_refuse_a_cue_with_no_time_on_screen(timeline):
    """Would catch a zero-length caption being written instead of refused."""
    doc = copy.deepcopy(timeline)
    lines = doc["beats"][0]["lines"]
    lines[1]["start"] = lines[0]["start"]            # the next sentence starts with this one
    with pytest.raises(TimelineError) as err:
        build_captions(doc)
    assert err.value.code == "bad_caption"
