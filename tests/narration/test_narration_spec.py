"""The wording table is closed, total, minimal, and says nothing it may not say.

These tests are the reviewable half of Phase 24's honesty claim. The other half
is structural -- visibility lives in a field a machine checks against the shot
plan -- but wording is where a narration layer would fabricate if it ever did,
so every template is asserted against both ban lists, and both ban lists are
asserted against seeded offenders and near-miss controls.
"""

import pytest

from living_diorama.cinematic.cinematic_spec import UNSHOWN_REASONS as PHASE22_UNSHOWN_REASONS
from living_diorama.narration.narration_spec import (
    CAUSAL_TOKENS,
    DEIXIS_TOKENS,
    KNOWN_BEAT_KINDS,
    NARRATION_TEMPLATES,
    TEMPLATE_PARAMETERS,
    TEMPLATE_PARAMETERS_BY_KIND,
    TEXT_SOURCE_BY_KIND,
    TEXT_SOURCE_MEMORY_FACT_SUMMARY,
    TEXT_SOURCE_NARRATION_TEMPLATE,
    TEXT_SOURCES,
    UNSHOWN_REASONS,
    forbidden_wording_hit,
    render_narration_text,
    render_subjects,
    text_source_for_kind,
)
from living_diorama.story import BEAT_KINDS

# ---- the table is total and closed


def test_every_beat_kind_has_a_text_source() -> None:
    """No Phase 21 beat kind may fall through to a guessed source."""
    assert sorted(TEXT_SOURCE_BY_KIND) == sorted(BEAT_KINDS)


def test_no_text_source_is_declared_for_an_unknown_kind() -> None:
    """The table names Phase 21's vocabulary and nothing of its own invention."""
    assert set(TEXT_SOURCE_BY_KIND) <= set(BEAT_KINDS)


def test_every_declared_text_source_is_a_known_source() -> None:
    """The table names only the two sources this contract defines."""
    assert set(TEXT_SOURCE_BY_KIND.values()) <= set(TEXT_SOURCES)


def test_template_backed_kinds_have_exactly_one_template_each() -> None:
    """Every kind narrated from the table has a sentence, and no kind has a spare."""
    expected = sorted(
        kind
        for kind, source in TEXT_SOURCE_BY_KIND.items()
        if source == TEXT_SOURCE_NARRATION_TEMPLATE
    )
    assert sorted(NARRATION_TEMPLATES) == expected
    assert sorted(TEMPLATE_PARAMETERS_BY_KIND) == expected


def test_fact_backed_kinds_have_no_template() -> None:
    """A kind whose sentence the world already wrote is never composed here."""
    for kind, source in TEXT_SOURCE_BY_KIND.items():
        if source == TEXT_SOURCE_MEMORY_FACT_SUMMARY:
            assert kind not in NARRATION_TEMPLATES


def test_text_source_for_an_unknown_kind_is_refused() -> None:
    """An unknown kind is never given a guessed source; the derivation stops."""
    with pytest.raises(ValueError, match="no narration text source"):
        text_source_for_kind("SOMETHING_PHASE_21_NEVER_EMITS")


def test_known_beat_kinds_matches_phase21() -> None:
    """The restated vocabulary is Phase 21's, sorted."""
    assert tuple(sorted(BEAT_KINDS)) == KNOWN_BEAT_KINDS


# ---- parameters are declared, minimal, and honest


def test_declared_parameters_match_the_sentences() -> None:
    """A template and its declaration agree in both directions."""
    for kind, template in NARRATION_TEMPLATES.items():
        declared = set(TEMPLATE_PARAMETERS_BY_KIND[kind])
        present = {parameter for parameter in TEMPLATE_PARAMETERS if parameter in template}
        assert declared == present, kind


def test_no_template_uses_a_parameter_outside_the_closed_set() -> None:
    """The whole parameter surface is two structural values.

    A template that reached for anything else -- a population, a pressure, a
    destination district -- would be asserting detail out of an event payload no
    upstream contract proved.
    """
    for kind, template in NARRATION_TEMPLATES.items():
        opened = template.count("{")
        assert opened == len(TEMPLATE_PARAMETERS_BY_KIND[kind]), kind


def test_the_empty_result_sentence_takes_no_parameters() -> None:
    """It reports an absence, so it has nothing to be parameterised by."""
    assert TEMPLATE_PARAMETERS_BY_KIND["NO_EMPHASIZED_BEATS"] == ()


def test_the_empty_result_sentence_does_not_claim_nothing_happened() -> None:
    """It is a statement about the emphasis policy, never about the world."""
    text = render_narration_text("NO_EMPHASIZED_BEATS", [], 0)
    assert "emphasized" in text
    lowered = text.lower()
    for forbidden in ("nothing happened", "no events", "uneventful", "quiet"):
        assert forbidden not in lowered


# ---- rendering


def test_subjects_are_quoted_in_the_order_given() -> None:
    """Quoted like the engine's own summaries, and never re-sorted here."""
    assert render_subjects(["district_a", "district_b"]) == '"district_a", "district_b"'


def test_rendering_substitutes_every_declared_parameter() -> None:
    """The exact sentence the real episode 0 to 1 transition produces."""
    text = render_narration_text("LAW_CHANGE", ["law_movement_sharing"], 7)
    assert text == 'At tick 7, law "law_movement_sharing" changed.'


def test_no_rendered_sentence_keeps_a_placeholder() -> None:
    """A template and its declaration cannot silently disagree at derivation time."""
    for kind in NARRATION_TEMPLATES:
        text = render_narration_text(kind, ["subject_a"], 5)
        for parameter in TEMPLATE_PARAMETERS:
            assert parameter not in text


def test_rendering_an_unknown_kind_is_refused() -> None:
    """There is no fallback sentence for a kind this build does not know."""
    with pytest.raises(KeyError):
        render_narration_text("SOMETHING_ELSE", ["a"], 1)


def test_every_rendered_sentence_is_one_sentence() -> None:
    """One beat, one sentence: a second would be a second claim."""
    for kind in NARRATION_TEMPLATES:
        text = render_narration_text(kind, ["subject_a"], 5)
        assert text.endswith(".")
        assert text.count(".") == 1


# ---- the ban lists


@pytest.mark.parametrize("kind", sorted(NARRATION_TEMPLATES))
def test_no_template_uses_a_banned_word(kind: str) -> None:
    """Checked on the raw template and on a rendered instance of it."""
    assert forbidden_wording_hit(NARRATION_TEMPLATES[kind]) is None
    assert forbidden_wording_hit(render_narration_text(kind, ["district_a"], 9)) is None


@pytest.mark.parametrize("token", sorted({*CAUSAL_TOKENS, *DEIXIS_TOKENS}))
def test_the_guard_catches_every_term_it_claims_to(token: str) -> None:
    """Each banned term, asserted on its own rather than trusted in bulk."""
    assert forbidden_wording_hit(f"The record {token} something at tick 4.") == token


@pytest.mark.parametrize(
    "sentence",
    [
        "The wall was built because the pressure rose.",
        "The law changed, therefore the wall rose.",
        "The district was responsible for the shortfall.",
        "The restoration led to nothing.",
        "Scarcity resulted in migration.",
    ],
)
def test_seeded_causal_offenders_are_caught(sentence: str) -> None:
    """Plausible sentences that assert a link the evidence never proved."""
    assert forbidden_wording_hit(sentence) is not None


@pytest.mark.parametrize(
    "sentence",
    [
        "The wall is shown at tick 9.",
        "The viewer sees the monument.",
        "This beat is visible in the frame.",
        "The camera holds on the scar.",
        "The record appears onscreen.",
    ],
)
def test_seeded_deixis_offenders_are_caught(sentence: str) -> None:
    """Plausible sentences that claim the viewer is looking at something."""
    assert forbidden_wording_hit(sentence) is not None


@pytest.mark.parametrize(
    "sentence",
    [
        'Wall "wall_boundary_ab" was built at tick 9.',
        'Law "law_movement_sharing" was restored at tick 22.',
        "An overview of the district was recorded.",
        "The framework_district reported a change.",
        "The screening_committee was seeded at tick 3.",
        'District "frame_budget_west" recorded population movement.',
        "The wall remained in the world.",
    ],
)
def test_the_guard_leaves_honest_sentences_alone(sentence: str) -> None:
    """Word boundaries, not substrings.

    ``overview`` contains ``view`` and ``framework_district`` contains ``frame``.
    Subject identifiers are substituted into these sentences, so an entity whose
    name merely contains a banned word must not make an honest sentence
    unpublishable.
    """
    assert forbidden_wording_hit(sentence) is None


def test_the_guard_is_case_insensitive() -> None:
    """Capitalisation is not a way around the ban list."""
    assert forbidden_wording_hit("The wall is SHOWN at tick 9.") == "shown"


def test_the_guard_catches_a_multi_word_term_across_whitespace() -> None:
    """Nor is a line break in the middle of one."""
    assert forbidden_wording_hit("The change  led\nto the wall.") is not None


# ---- restated upstream vocabulary


def test_unshown_reasons_still_agree_with_phase22() -> None:
    """Restated, not imported -- so drift must fail loudly rather than silently."""
    assert sorted(UNSHOWN_REASONS) == sorted(PHASE22_UNSHOWN_REASONS)
