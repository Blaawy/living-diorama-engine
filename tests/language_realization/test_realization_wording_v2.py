"""Wording profile V2: byte-identical V1 default, the V2 register laws, and scope.

The V1 register is the default and must reproduce today's derivation byte for
byte -- the golden literals below are independent, locked sentences from the
canonical chain, never derived by calling the production renderer inside the
expectation. The V2 register covers exactly the same template keys with exactly
the same structured atoms, composes short, active, concrete sentences, avoids
the simulation's analytic vocabulary, never speaks a district identifier
(the wall is "the wall between this side and the other side", a district
subject is "this area", and guidance points with "the two places" / "over
there"), binds every record to the fact and event it restates, and never
touches wording that is carried verbatim: the memory layer's own recorded
summaries stay byte-identical under both profiles, because every realization
in this build is genuinely template-driven and no realization reads a summary.

The real EP1 V2 script is fixed: three fact records realize "We changed one
rule.", "We built the wall between this side and the other side. It never went
away." and "The wall between this side and the other side changed.", and the
four viewer guidance lines are selected in their fixed pool order. Its total
word count is 57, inside the [55, 70] law, with every sentence at most 12 words
and six of the eight sentences (75%) between 3 and 9 words.
"""

import copy
import re

import pytest

from living_diorama.cinematic import build_shot_direction_plan_document
from living_diorama.language_realization import (
    EVENT_REALIZATION_TEMPLATES_V2,
    FACT_REALIZATION_TEMPLATES_V2,
    FORBIDDEN_V2_JARGON,
    VIEWER_GUIDANCE_POOL,
    WORDING_PROFILE_V1,
    WORDING_PROFILE_V2,
    build_episode_language_realization_plan_bytes,
    build_episode_language_realization_plan_document,
    select_viewer_guidance,
    validate_episode_language_realization_plan,
    validate_guidance_grounding,
    validate_language_realization_plan_against_sources,
)
from living_diorama.language_realization.realization_spec import (
    ABSENCE_KIND,
    V2_WALL_LABEL,
    render_event_realization,
    render_law_restored_wall_persisted,
    render_wall_built,
)
from living_diorama.narration import build_episode_narration_plan_document, forbidden_wording_hit
from living_diorama.story import build_episode_story_plan_document

from .conftest import MOTION_CONFIG, build_realization_sources, load_export

V1_GOLDEN_EP0 = ["No beats were emphasized for this episode."]
V1_GOLDEN_EP1 = [
    "At tick 7, the movement resource sharing law changed.",
    "At tick 9, a permanent wall was built on the boundary between District A and District B.",
    "At tick 9, the wall between District A and District B changed state.",
]
V1_GOLDEN_EP2 = [
    "At tick 22, the movement resource sharing law was restored; the permanent wall on "
    "the boundary between District A and District B, built at tick 9, remained in the "
    "world.",
    "At tick 21, the wall between District A and District B changed state.",
]

V2_GOLDEN_EP0 = ["Nothing stood out this time."]
V2_GOLDEN_EP1 = [
    "We changed one rule.",
    "We built the wall between this side and the other side. It never went away.",
    "The wall between this side and the other side changed.",
]
V2_GOLDEN_EP2 = [
    "The old rule came back. The wall between this side and the other side never goes away.",
    "The wall between this side and the other side changed.",
]

EP1_V2_GUIDANCE = [
    {"guidance_text": "Okay, here we go.", "grounding": "none"},
    {"guidance_text": "Now look at the road between the two places.", "grounding": "road"},
    {"guidance_text": "Now look at the wall between the two places.", "grounding": "wall"},
    {"guidance_text": "Look at the road over there.", "grounding": "road"},
]
"""The real EP1 V2 viewer guidance: the whole pool, in the fixed pool order."""

EP0_V2_GUIDANCE = [
    {"guidance_text": "Okay, here we go.", "grounding": "none"},
    {"guidance_text": "Now look at the road between the two places.", "grounding": "road"},
    {"guidance_text": "Look at the road over there.", "grounding": "road"},
]
"""The baseline selects the pool minus the wall line: the baseline has no walls."""

EP1_WALL_BUILT_FACT_ID = "fact_89378947433073c105058df0ef5047eed03825fdc221293a2a630ab6dec9947b"
EP1_WALL_BUILT_EVENT_ID = 61
EP1_WALL_STATE_CHANGE_EVENT_ID = 64

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

BANNED_V2_SPEECH = re.compile(
    r"\b(?:District|tick|mobility|infrastructure|boundary|enforcement|profile|id|"
    r"state transition|resource sharing|movement resource|persistent consequence|"
    r"behavioral consequence|simulation state)\b",
    re.IGNORECASE,
)
"""The mechanical ban on the Director's list, scanned over produced V2 speech.

Covers every district identifier label ("District" as a whole word), the
simulation's internal vocabulary, and every identifier-ish word ("id",
"profile") that must never leak into speech. ``FORBIDDEN_V2_JARGON`` is the
register's own narrower vocabulary check; this is the Director's wider ban,
applied to the real produced narration text rather than eyeballed.
"""

ALL_CAPS_WORD = re.compile(r"\b[A-Z]{2,}\b")


def _texts(plan: dict) -> list[str]:
    return [record["realized_text"] for record in plan["realizations"]]


def _sentences(texts: list[str]) -> list[str]:
    sentences: list[str] = []
    for text in texts:
        sentences.extend(SENTENCE_SPLIT.split(text))
    return sentences


# --------------------------------------------------------------------------
# V1 byte-identical regression, no new argument
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("episode", "golden"),
    [(0, V1_GOLDEN_EP0), (1, V1_GOLDEN_EP1), (2, V1_GOLDEN_EP2)],
)
def test_v1_default_reproduces_the_captured_golden(episode: int, golden: list[str]) -> None:
    """The default call -- no new argument -- derives today's sentences exactly."""
    narration, story, export = build_realization_sources(episode)
    plan = build_episode_language_realization_plan_document(narration, story, export)
    assert _texts(plan) == golden
    assert "wording_profile" not in plan
    assert "viewer_guidance" not in plan


def test_v1_default_bytes_carry_no_profile_field() -> None:
    """The canonical V1 bytes are today's bytes: no wording_profile anywhere."""
    narration, story, export = build_realization_sources(1)
    payload = build_episode_language_realization_plan_bytes(narration, story, export)
    assert b'"wording_profile"' not in payload
    assert b'"viewer_guidance"' not in payload


def test_an_explicit_v1_profile_is_byte_identical_to_the_default() -> None:
    """Requesting v1 explicitly must not change a single byte of the V1 plan."""
    narration, story, export = build_realization_sources(1)
    default = build_episode_language_realization_plan_bytes(narration, story, export)
    explicit = build_episode_language_realization_plan_bytes(
        narration, story, export, wording_profile=WORDING_PROFILE_V1
    )
    assert explicit == default


def test_v1_records_carry_no_v2_binding_fields() -> None:
    """The V1 record shape stays exactly realization_id, realized_text, unit_id."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(narration, story, export)
    for record in plan["realizations"]:
        assert set(record) == {"realization_id", "realized_text", "unit_id"}


# --------------------------------------------------------------------------
# V2 output on the real canonical episodes
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("episode", "golden"),
    [(0, V2_GOLDEN_EP0), (1, V2_GOLDEN_EP1), (2, V2_GOLDEN_EP2)],
)
def test_v2_realizes_the_episode_goldens(episode: int, golden: list[str]) -> None:
    """The V2 register composes the exact same units to the reviewed sentences."""
    narration, story, export = build_realization_sources(episode)
    plan = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    assert _texts(plan) == golden
    assert plan["wording_profile"] == WORDING_PROFILE_V2


def test_v2_render_functions_compose_exactly() -> None:
    """The render functions compose the reviewed V2 strings deterministically."""
    assert (
        render_event_realization(
            "LAW_CHANGE", "the movement resource sharing law", 7, wording_profile="v2"
        )
        == "We changed one rule."
    )
    assert (
        render_event_realization(
            "WALL_STATE_CHANGE",
            V2_WALL_LABEL[len("the ") :],
            9,
            wording_profile="v2",
        )
        == "The wall between this side and the other side changed."
    )
    assert (
        render_event_realization("POPULATION_MOVEMENT", "this area", 7, wording_profile="v2")
        == "People moved around here."
    )
    assert (
        render_event_realization(ABSENCE_KIND, None, None, wording_profile="v2")
        == "Nothing stood out this time."
    )
    assert (
        render_wall_built(
            9,
            "the boundary between District A and District B",
            wording_profile="v2",
            wall_label=V2_WALL_LABEL,
        )
        == "We built the wall between this side and the other side. It never went away."
    )
    assert (
        render_law_restored_wall_persisted(
            22,
            "the movement resource sharing law",
            "the boundary between District A and District B",
            9,
            wording_profile="v2",
            wall_label=V2_WALL_LABEL,
        )
        == "The old rule came back. The wall between this side and the other side never goes away."
    )


# --------------------------------------------------------------------------
# Viewer guidance: deterministic, grounded, in the fixed pool order
# --------------------------------------------------------------------------


def test_ep1_v2_guidance_is_the_full_pool_in_order() -> None:
    """The real EP1 episode selects exactly the four pool lines, in pool order."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    assert plan["viewer_guidance"] == EP1_V2_GUIDANCE
    assert plan["viewer_guidance"] == [dict(entry) for entry in VIEWER_GUIDANCE_POOL]


def test_ep0_v2_guidance_drops_the_ungrounded_wall_line() -> None:
    """The baseline world carries no walls, so the wall line is filtered out."""
    narration, story, export = build_realization_sources(0)
    plan = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    assert plan["viewer_guidance"] == EP0_V2_GUIDANCE


def test_guidance_selection_is_deterministic_across_seed_inputs() -> None:
    """Same world export, any seed: the same grounded lines in the same order."""
    _narration, _story, export = build_realization_sources(1)
    first = select_viewer_guidance(export, 1)
    second = select_viewer_guidance(export, "anything-else")
    assert first == second == EP1_V2_GUIDANCE


def test_validate_guidance_grounding_refuses_an_ungrounded_wall_line() -> None:
    """A wall-grounded line is refused against a world export with zero walls."""
    _narration, _story, export = build_realization_sources(0)
    wall_line = next(entry for entry in VIEWER_GUIDANCE_POOL if entry["grounding"] == "wall")
    with pytest.raises(ValueError, match="grounded"):
        validate_guidance_grounding(wall_line, export)


# --------------------------------------------------------------------------
# The V2 register laws: forbidden vocabulary, banned labels, word count
# --------------------------------------------------------------------------


def test_no_v2_template_uses_a_forbidden_token() -> None:
    """No literal V2 template sentence contains a forbidden register token."""
    for table in (EVENT_REALIZATION_TEMPLATES_V2, FACT_REALIZATION_TEMPLATES_V2):
        for key, template in table.items():
            assert FORBIDDEN_V2_JARGON.search(template) is None, (key, template)


def test_no_real_episode_v2_sentence_uses_a_forbidden_token() -> None:
    """No finished V2 sentence or guidance line contains a forbidden token."""
    for episode in (1, 2):
        narration, story, export = build_realization_sources(episode)
        plan = build_episode_language_realization_plan_document(
            narration, story, export, wording_profile=WORDING_PROFILE_V2
        )
        for text in _texts(plan):
            assert FORBIDDEN_V2_JARGON.search(text) is None, text
        for entry in plan["viewer_guidance"]:
            assert FORBIDDEN_V2_JARGON.search(entry["guidance_text"]) is None, entry


def test_no_produced_v2_speech_names_a_district_or_speaks_internal_jargon() -> None:
    """The Director's ban, scanned mechanically over the real produced speech.

    Scans every realized sentence and every guidance line of the canonical V2
    episodes for "District A"/"District B"/any district label, the simulation's
    analytic vocabulary, identifier-ish words, snake_case and ALL_CAPS. This is
    a scan of the produced narration text, not an eyeball check.
    """
    for episode in (0, 1, 2):
        narration, story, export = build_realization_sources(episode)
        plan = build_episode_language_realization_plan_document(
            narration, story, export, wording_profile=WORDING_PROFILE_V2
        )
        spoken = _texts(plan) + [entry["guidance_text"] for entry in plan["viewer_guidance"]]
        assert spoken, episode
        for text in spoken:
            assert BANNED_V2_SPEECH.search(text) is None, (episode, text)
            assert "_" not in text, (episode, text)
            assert ALL_CAPS_WORD.search(text) is None, (episode, text)


def test_the_v2_wall_label_never_passes_through_district_capitalization() -> None:
    """The V2 wall label is the reviewed deictic phrase, not a district label."""
    assert V2_WALL_LABEL == "the wall between this side and the other side"
    assert "District" not in V2_WALL_LABEL
    for episode in (1, 2):
        narration, story, export = build_realization_sources(episode)
        plan = build_episode_language_realization_plan_document(
            narration, story, export, wording_profile=WORDING_PROFILE_V2
        )
        for text in _texts(plan):
            assert "District A" not in text and "District B" not in text, text


def test_every_v2_template_sentence_obeys_the_word_count_law() -> None:
    """Every literal V2 template sentence is 3-12 words, each slot counting as one."""
    tables = (EVENT_REALIZATION_TEMPLATES_V2, FACT_REALIZATION_TEMPLATES_V2)
    for table in tables:
        for key, template in table.items():
            for sentence in SENTENCE_SPLIT.split(template):
                assert 3 <= len(sentence.split()) <= 12, (key, sentence)


def test_the_real_ep1_v2_sentences_obey_the_length_law() -> None:
    """Every EP1 V2 sentence is at most 12 words and at least 70% are 3-9 words."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    sentences = _sentences(_texts(plan)) + [
        entry["guidance_text"] for entry in plan["viewer_guidance"]
    ]
    counts = [len(sentence.split()) for sentence in sentences]
    assert all(count <= 12 for count in counts), counts
    short = sum(1 for count in counts if 3 <= count <= 9)
    assert short / len(counts) >= 0.7, counts


def test_the_real_ep1_v2_total_word_count_is_57() -> None:
    """The whole EP1 V2 script -- facts and guidance -- is exactly 57 words."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    sentences = _sentences(_texts(plan)) + [
        entry["guidance_text"] for entry in plan["viewer_guidance"]
    ]
    total = sum(len(sentence.split()) for sentence in sentences)
    assert total == 57
    assert 55 <= total <= 70


# --------------------------------------------------------------------------
# The EP2 lower-case-after-period regression, fixed structurally
# --------------------------------------------------------------------------


def test_the_v2_persistence_sentence_capitalizes_any_wall_label() -> None:
    """A wall label at a sentence start is capitalized for any label value.

    The EP2 regression -- "The old rule came back. the wall ... never goes
    away." -- is fixed at label construction in
    ``render_law_restored_wall_persisted``, so a fabricated wall_label that
    begins with "the" (or any lowercase word) is cased correctly, for any
    value, not just today's reviewed label.
    """
    sentence = render_law_restored_wall_persisted(
        22,
        "the movement resource sharing law",
        "the boundary between District A and District B",
        9,
        wording_profile="v2",
        wall_label="the wall between the two places",
    )
    assert sentence == "The old rule came back. The wall between the two places never goes away."
    other = render_law_restored_wall_persisted(
        22,
        "the movement resource sharing law",
        "the boundary between District A and District B",
        9,
        wording_profile="v2",
        wall_label="the great wall",
    )
    assert other == "The old rule came back. The great wall never goes away."
    assert (
        render_law_restored_wall_persisted(
            22,
            "the movement resource sharing law",
            "the boundary between District A and District B",
            9,
            wording_profile="v2",
            wall_label=V2_WALL_LABEL,
        )
        == "The old rule came back. The wall between this side and the other side never goes away."
    )


# --------------------------------------------------------------------------
# Fact and event bindings on V2 records
# --------------------------------------------------------------------------


def test_v2_records_carry_resolvable_fact_and_event_bindings() -> None:
    """Every EP1 V2 record binds the real fact and event its sentence restates."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    records = plan["realizations"]
    assert records[0]["category"] == "fact"
    assert records[0]["event_id"] == 0
    assert records[0]["fact_id"] is None
    assert records[1]["category"] == "fact"
    assert records[1]["event_id"] == EP1_WALL_BUILT_EVENT_ID
    assert records[1]["fact_id"] == EP1_WALL_BUILT_FACT_ID
    assert records[2]["category"] == "fact"
    assert records[2]["event_id"] == EP1_WALL_STATE_CHANGE_EVENT_ID
    assert records[2]["fact_id"] is None


def test_a_wrong_v2_event_binding_is_refused_by_the_cross_check() -> None:
    """A record binding an event its beat does not cite is refused."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    plan["realizations"][0]["event_id"] = 99
    with pytest.raises(ValueError, match="event binding"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_an_unbound_v2_event_id_is_refused_by_the_cross_check() -> None:
    """A record whose event binding is missing is refused against the sources."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    plan["realizations"][0]["event_id"] = None
    with pytest.raises(ValueError, match="event binding"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_a_wrong_v2_fact_binding_is_refused_by_the_cross_check() -> None:
    """A record binding a fact its beat does not cite is refused."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    plan["realizations"][1]["fact_id"] = "fact_" + "0" * 64
    with pytest.raises(ValueError, match="fact binding"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


def test_an_ungrounded_guidance_entry_is_refused_by_the_cross_check() -> None:
    """A guidance line the real world cannot ground is refused against sources."""
    narration, story, export = build_realization_sources(0)
    plan = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    wall_line = next(entry for entry in VIEWER_GUIDANCE_POOL if entry["grounding"] == "wall")
    plan["viewer_guidance"].append(dict(wall_line))
    with pytest.raises(ValueError, match="grounded"):
        validate_language_realization_plan_against_sources(plan, narration, story, export)


# --------------------------------------------------------------------------
# Schema: the V2-only fields and bans
# --------------------------------------------------------------------------


def test_a_v1_plan_carrying_viewer_guidance_is_refused() -> None:
    """viewer_guidance is a v2-only top-level field."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(narration, story, export)
    plan["viewer_guidance"] = [dict(EP1_V2_GUIDANCE[0])]
    with pytest.raises(ValueError, match="v2-only"):
        validate_episode_language_realization_plan(plan)


def test_a_v1_record_carrying_a_binding_field_is_refused() -> None:
    """The v1 record shape does not grow; binding fields are v2-only."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(narration, story, export)
    plan["realizations"][0]["category"] = "fact"
    with pytest.raises(ValueError, match="unexpected keys"):
        validate_episode_language_realization_plan(plan)


def test_a_v2_sentence_with_a_forbidden_token_is_refused_by_the_schema() -> None:
    """The schema enforces the register vocabulary on every v2 realized text."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    plan["realizations"][0]["realized_text"] = "We changed one rule and the boundary moved."
    with pytest.raises(ValueError, match="never speaks"):
        validate_episode_language_realization_plan(plan)


def test_a_v2_guidance_text_with_a_forbidden_token_is_refused_by_the_schema() -> None:
    """The register vocabulary ban applies to viewer guidance text as well."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    plan["viewer_guidance"][0]["guidance_text"] = "Look at the boundary now."
    with pytest.raises(ValueError, match="never speaks"):
        validate_episode_language_realization_plan(plan)


# --------------------------------------------------------------------------
# Scope: verbatim kinds are never touched
# --------------------------------------------------------------------------


def test_the_fact_backed_unit_text_is_the_memory_summary_verbatim() -> None:
    """The genuinely verbatim surface is the narration layer's carried summary."""
    narration, _story, export = build_realization_sources(1)
    fact_unit = narration["units"][1]
    fact = next(fact for fact in export["memory"]["facts"] if fact["episode"] == 1)
    assert fact_unit["text"] == fact["summary"]


def test_v2_building_never_touches_the_verbatim_summaries() -> None:
    """Narration text is byte-identical whether a v1 or v2 plan is built."""
    narration, story, export = build_realization_sources(1)
    narration_before = copy.deepcopy(narration)
    build_episode_language_realization_plan_document(narration, story, export)
    assert narration == narration_before
    build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    assert narration == narration_before


def test_no_realization_is_a_verbatim_copy_of_the_memory_summary() -> None:
    """Every realization kind is genuinely template-driven, never a pass-through.

    The V1 and V2 wall-built realizations both differ from the memory layer's
    own summary, which is exactly why both registers may compose them.
    """
    narration, story, export = build_realization_sources(1)
    fact = next(fact for fact in export["memory"]["facts"] if fact["episode"] == 1)
    v1 = build_episode_language_realization_plan_document(narration, story, export)
    v2 = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    assert v1["realizations"][1]["realized_text"] != fact["summary"]
    assert v2["realizations"][1]["realized_text"] != fact["summary"]
    assert v1["realizations"][1]["realized_text"] != v2["realizations"][1]["realized_text"]


def test_a_mutated_summary_moves_no_v2_wording() -> None:
    """V2 wording, like V1 wording, is derived from structure, never a summary."""
    honest = build_episode_language_realization_plan_document(
        *build_realization_sources(1), wording_profile=WORDING_PROFILE_V2
    )

    export = load_export(1)
    new_fact = next(fact for fact in export["memory"]["facts"] if fact["episode"] == 1)
    new_fact["summary"] = "A wall now divides two districts, recorded at tick 9."
    previous = load_export(0)
    story = build_episode_story_plan_document(copy.deepcopy(export), previous)
    shots = build_shot_direction_plan_document(story, MOTION_CONFIG.read_bytes())
    narration = build_episode_narration_plan_document(story, shots, copy.deepcopy(export))
    mutated = build_episode_language_realization_plan_document(
        narration, story, copy.deepcopy(export), wording_profile=WORDING_PROFILE_V2
    )

    assert _texts(mutated) == _texts(honest)


# --------------------------------------------------------------------------
# Schema, cross-check, determinism and refusal
# --------------------------------------------------------------------------


def test_a_v2_plan_cross_checks_against_its_own_register() -> None:
    """Cross-check re-derives under the document's declared profile, not V1."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    assert (
        validate_language_realization_plan_against_sources(plan, narration, story, export) is plan
    )
    plan_v1 = build_episode_language_realization_plan_document(narration, story, export)
    assert (
        validate_language_realization_plan_against_sources(plan_v1, narration, story, export)
        is plan_v1
    )


def test_an_unknown_wording_profile_is_refused() -> None:
    """A profile outside the reviewed pair is refused, never guessed."""
    narration, story, export = build_realization_sources(1)
    with pytest.raises(ValueError, match="expected one of"):
        build_episode_language_realization_plan_document(
            narration, story, export, wording_profile="v3"
        )
    plan = build_episode_language_realization_plan_document(narration, story, export)
    plan["wording_profile"] = "v3"
    with pytest.raises(ValueError, match="expected one of"):
        validate_episode_language_realization_plan(plan)


def test_an_explicit_v1_field_is_accepted_by_the_schema() -> None:
    """The schema reads an explicit v1 declaration, and absent means v1 too."""
    narration, story, export = build_realization_sources(1)
    plan = build_episode_language_realization_plan_document(narration, story, export)
    assert "wording_profile" not in plan
    plan["wording_profile"] = WORDING_PROFILE_V1
    assert validate_episode_language_realization_plan(plan) is plan


def test_v2_builds_are_deterministic() -> None:
    """Same sources, same register: same bytes, twice."""
    narration, story, export = build_realization_sources(2)
    first = build_episode_language_realization_plan_bytes(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    second = build_episode_language_realization_plan_bytes(
        narration, story, export, wording_profile=WORDING_PROFILE_V2
    )
    assert first == second


def test_every_v2_template_clears_the_causal_and_deictic_bans_when_filled() -> None:
    """Every V2 sentence must clear the same bans the schema enforces."""
    for table in (EVENT_REALIZATION_TEMPLATES_V2, FACT_REALIZATION_TEMPLATES_V2):
        for key, template in table.items():
            sentence = template.replace(
                "{subject_label}", "wall between this side and the other side"
            )
            sentence = sentence.replace(
                "{wall_label}", "the wall between this side and the other side"
            )
            assert forbidden_wording_hit(sentence) is None, (key, sentence)
            assert "_" not in sentence, key
            assert '"' not in sentence, key
