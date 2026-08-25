"""The Phase 26 realization policy: totality, label rules, and wording safety."""

import re
import string

import pytest

from living_diorama.language_realization.realization_spec import (
    ABSENCE_KIND,
    DISTRICT_ID_PATTERN,
    EVENT_REALIZATION_PARAMETERS,
    EVENT_REALIZATION_TEMPLATES,
    EXPLICIT_LABELS,
    FACT_REALIZATION_PARAMETERS,
    FACT_REALIZATION_TEMPLATES,
    LAW_NAME_PATTERN,
    REALIZATION_ID_FORM,
    REALIZATION_PLAN_FORMAT,
    REALIZATION_POLICY_V1,
    REALIZATION_SCHEMA_VERSION,
    REQUIRED_FACT_DETAILS,
    SUBJECT_ENTITY_CLASS_BY_KIND,
    boundary_phrase,
    district_label,
    law_label,
    render_event_realization,
    render_law_restored_wall_persisted,
    render_wall_built,
    wall_phrase,
)
from living_diorama.narration import NARRATION_TEMPLATES, forbidden_wording_hit
from living_diorama.narration.narration_spec import (
    TEXT_SOURCE_MEMORY_FACT_SUMMARY,
    TEXT_SOURCE_NARRATION_TEMPLATE,
    text_source_for_kind,
)
from living_diorama.story import BEAT_KINDS, FACT_BEAT_RULES
from living_diorama.story.story_spec import KNOWN_FACT_TYPES

PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def test_format_and_versions_are_pinned() -> None:
    """The format tag, schema version and policy identifier are exact constants."""
    assert REALIZATION_PLAN_FORMAT == "living_diorama_episode_language_realization_plan"
    assert REALIZATION_SCHEMA_VERSION == 1
    assert REALIZATION_POLICY_V1 == "language_realization_policy_v1"
    assert REALIZATION_ID_FORM % 7 == "realization_0007"


def test_the_absence_kind_restatement_still_agrees_with_the_story() -> None:
    """The restated absence kind is the story vocabulary's own, so drift fails."""
    assert ABSENCE_KIND in BEAT_KINDS


def test_every_template_backed_beat_kind_has_a_template() -> None:
    """The event table is total over exactly the template-backed story kinds."""
    template_kinds = {
        kind for kind in BEAT_KINDS if text_source_for_kind(kind) == TEXT_SOURCE_NARRATION_TEMPLATE
    }
    assert set(EVENT_REALIZATION_TEMPLATES) == template_kinds


def test_no_template_exists_for_an_unknown_kind() -> None:
    """A template for a kind the story never emits would be an invention."""
    for kind in EVENT_REALIZATION_TEMPLATES:
        assert kind in BEAT_KINDS


def test_every_fact_backed_fact_type_has_a_template() -> None:
    """The fact table is total over exactly the story's supported fact types."""
    assert set(FACT_REALIZATION_TEMPLATES) == set(KNOWN_FACT_TYPES)
    assert set(FACT_REALIZATION_TEMPLATES) == set(FACT_BEAT_RULES)


def test_every_fact_type_declares_its_required_details() -> None:
    """The required-detail table covers exactly the supported fact types."""
    assert set(REQUIRED_FACT_DETAILS) == set(FACT_REALIZATION_TEMPLATES)


def test_the_payload_is_never_a_required_detail() -> None:
    """The source event payload is not a presentation atom and is never read."""
    for fact_type, fields in REQUIRED_FACT_DETAILS.items():
        assert "source_event_payload" not in fields, fact_type


def test_the_omitted_presentation_fields_stay_omitted() -> None:
    """Fields the locked memory summaries omit are not promoted into speech."""
    persisted = REQUIRED_FACT_DETAILS["LAW_RESTORED_WALL_PERSISTED"]
    assert "wall_active_at_episode_close" not in persisted
    assert "wall_dependency_score_at_episode_close" not in persisted
    assert "law_previous_value" not in persisted
    assert "law_current_value" not in persisted


def test_event_template_placeholders_match_their_declarations() -> None:
    """A template's placeholders and its declaration agree in both directions."""
    for kind, template in EVENT_REALIZATION_TEMPLATES.items():
        found = set(PLACEHOLDER.findall(template))
        assert found == set(EVENT_REALIZATION_PARAMETERS[kind]), kind


def test_fact_template_placeholders_match_their_declarations() -> None:
    """A fact template's placeholders and its declaration agree both ways."""
    for fact_type, template in FACT_REALIZATION_TEMPLATES.items():
        found = set(PLACEHOLDER.findall(template))
        assert found == set(FACT_REALIZATION_PARAMETERS[fact_type]), fact_type


def test_every_subject_bearing_kind_declares_an_entity_class() -> None:
    """Every template kind except the absence kind resolves one entity class."""
    expected = set(EVENT_REALIZATION_TEMPLATES) - {ABSENCE_KIND}
    assert set(SUBJECT_ENTITY_CLASS_BY_KIND) == expected


def test_the_absence_sentence_is_the_locked_narration_sentence() -> None:
    """The absence kind is already human-facing, so it is carried unchanged."""
    assert EVENT_REALIZATION_TEMPLATES[ABSENCE_KIND] == NARRATION_TEMPLATES[ABSENCE_KIND]


def test_the_explicit_label_table_is_empty_in_v1() -> None:
    """Every canonical entity resolves through a rule, so the table holds none."""
    assert dict(EXPLICIT_LABELS) == {}


@pytest.mark.parametrize("letter", sorted(string.ascii_lowercase))
def test_the_district_grammar_accepts_every_single_letter(letter: str) -> None:
    """Each single-letter district id maps to its display label."""
    assert district_label(f"district_{letter}", "test") == f"District {letter.upper()}"


@pytest.mark.parametrize(
    "district_id",
    ["district_ab", "district_1", "districtx", "district_", "district_A", "District_a", ""],
)
def test_the_district_grammar_refuses_everything_else(district_id: str) -> None:
    """An identifier outside the reviewed grammar is refused, never prettified."""
    with pytest.raises(ValueError, match="reviewed district label grammar"):
        district_label(district_id, "test")


def test_the_district_pattern_is_the_reviewed_grammar() -> None:
    """The compiled pattern is exactly the documented grammar."""
    assert DISTRICT_ID_PATTERN.pattern == r"\Adistrict_([a-z])\Z"


def test_the_law_label_formats_the_authoritative_name() -> None:
    """The canonical law name formats under the reviewed rule."""
    label = law_label("movement_resource_sharing", "test")
    assert label == "the movement resource sharing law"


@pytest.mark.parametrize("name", ["Movement_Sharing", "law 1", "_leading", "trailing_", "", "a__b"])
def test_the_law_grammar_refuses_unreviewed_names(name: str) -> None:
    """A law name outside the reviewed grammar is refused, never formatted."""
    with pytest.raises(ValueError, match="reviewed law label grammar"):
        law_label(name, "test")


def test_the_law_pattern_is_the_reviewed_grammar() -> None:
    """The compiled pattern is exactly the documented grammar."""
    assert LAW_NAME_PATTERN.pattern == r"\A[a-z]+(?:_[a-z]+)*\Z"


def test_the_relationship_phrases_compose_from_endpoint_labels() -> None:
    """Boundary and wall phrases are deterministic compositions."""
    assert (
        boundary_phrase("District A", "District B")
        == "the boundary between District A and District B"
    )
    assert wall_phrase("District A", "District B") == "the wall between District A and District B"


def test_the_absence_template_takes_no_parameters() -> None:
    """The absence sentence names nothing and refuses offered parameters."""
    assert render_event_realization(ABSENCE_KIND, None, None) == (
        "No beats were emphasized for this episode."
    )
    with pytest.raises(ValueError, match="takes no parameters"):
        render_event_realization(ABSENCE_KIND, "District A", 7)


def test_a_parameterized_template_requires_both_parameters() -> None:
    """A template is filled completely or not at all."""
    with pytest.raises(ValueError, match="filled completely"):
        render_event_realization("LAW_CHANGE", None, 7)
    with pytest.raises(ValueError, match="filled completely"):
        render_event_realization("LAW_CHANGE", "the movement resource sharing law", None)


def test_an_unknown_kind_has_no_template() -> None:
    """An unreviewed kind is refused, never paraphrased."""
    with pytest.raises(ValueError, match="no reviewed realization template"):
        render_event_realization("WEATHER_CHANGE", "the sky", 3)


def test_rendered_event_sentences_clear_the_wording_bans() -> None:
    """Every event template, filled with canonical-shaped labels, is safe."""
    for kind in EVENT_REALIZATION_TEMPLATES:
        if kind == ABSENCE_KIND:
            sentence = render_event_realization(kind, None, None)
        else:
            sentence = render_event_realization(kind, "the wall between District A and B", 9)
        assert forbidden_wording_hit(sentence) is None, sentence
        assert "_" not in sentence
        assert '"' not in sentence


def test_rendered_fact_sentences_clear_the_wording_bans() -> None:
    """Both fact templates, filled with canonical-shaped labels, are safe."""
    built = render_wall_built(9, "the boundary between District A and District B")
    persisted = render_law_restored_wall_persisted(
        22,
        "the movement resource sharing law",
        "the boundary between District A and District B",
        9,
    )
    for sentence in (built, persisted):
        assert forbidden_wording_hit(sentence) is None, sentence
        assert "_" not in sentence
        assert '"' not in sentence


def test_the_wall_built_rendering_is_exact() -> None:
    """The WALL_BUILT template composes byte-for-byte deterministically."""
    assert render_wall_built(9, "the boundary between District A and District B") == (
        "At tick 9, a permanent wall was built on the boundary between District A and District B."
    )


def test_the_persistence_rendering_is_exact() -> None:
    """The LAW_RESTORED_WALL_PERSISTED template composes deterministically."""
    sentence = render_law_restored_wall_persisted(
        22,
        "the movement resource sharing law",
        "the boundary between District A and District B",
        9,
    )
    assert sentence == (
        "At tick 22, the movement resource sharing law was restored; the permanent wall "
        "on the boundary between District A and District B, built at tick 9, remained "
        "in the world."
    )


def test_fact_backed_kinds_are_exactly_the_summary_restating_kinds() -> None:
    """The fact-backed classification is the narration layer's own."""
    fact_backed = {
        kind for kind in BEAT_KINDS if text_source_for_kind(kind) == TEXT_SOURCE_MEMORY_FACT_SUMMARY
    }
    assert fact_backed == {rule[0] for rule in FACT_BEAT_RULES.values()}
