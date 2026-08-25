"""Structured atom extraction: event resolution, entity resolvers, fact details.

These tests mutate copies of the genuine canonical documents one field at a
time, so every refusal exercised here is one a hand-built export could really
present. The envelope validator deliberately tolerates all of them; this layer
is where they die.
"""

import copy
from typing import Any

import pytest

from living_diorama.language_realization.realization_atoms import (
    fact_for_beat,
    realized_text_for_beat,
    resolve_boundary,
    resolve_district,
    resolve_event,
    resolve_law,
    resolve_wall,
)


def _beat(story: dict[str, Any], position: int) -> dict[str, Any]:
    return story["beats"][position]


def _law_evidence(story: dict[str, Any]) -> dict[str, Any]:
    """The ep1 LAW_CHANGE beat's single event evidence entry."""
    return _beat(story, 0)["evidence"][0]


class TestResolveEvent:
    """The evidence-vs-actual-export gate: the silent hole, closed."""

    def test_the_canonical_evidence_resolves(self, sources_ep1: tuple) -> None:
        """A genuine evidence entry returns the actual export event."""
        _narration, story, export = sources_ep1
        event = resolve_event(export, _law_evidence(story), "test")
        assert event["type"] == "LAW_CHANGED"
        assert event["tick"] == 7

    def test_a_lying_event_type_is_refused(self, sources_ep1: tuple) -> None:
        """Evidence claiming a different type than the actual event dies here."""
        _narration, story, export = sources_ep1
        evidence = copy.deepcopy(_law_evidence(story))
        evidence["index"] = 61
        with pytest.raises(ValueError, match="does not identify the moment"):
            resolve_event(export, evidence, "test")

    def test_a_lying_source_id_is_refused(self, sources_ep1: tuple) -> None:
        """Evidence claiming another publisher than the actual event dies here."""
        _narration, story, export = sources_ep1
        evidence = copy.deepcopy(_law_evidence(story))
        evidence["source_id"] = "law_border_control"
        with pytest.raises(ValueError, match="was published by"):
            resolve_event(export, evidence, "test")

    def test_a_lying_tick_is_refused(self, sources_ep1: tuple) -> None:
        """Evidence claiming another tick than the actual event dies here."""
        _narration, story, export = sources_ep1
        evidence = copy.deepcopy(_law_evidence(story))
        evidence["tick"] = 8
        with pytest.raises(ValueError, match="share a tick"):
            resolve_event(export, evidence, "test")

    def test_an_out_of_range_index_is_refused(self, sources_ep1: tuple) -> None:
        """An index beyond the export's events is a dangling reference."""
        _narration, story, export = sources_ep1
        evidence = copy.deepcopy(_law_evidence(story))
        evidence["index"] = len(export["events"])
        with pytest.raises(ValueError, match="carries only"):
            resolve_event(export, evidence, "test")

    def test_an_index_at_another_valid_event_is_refused(self, sources_ep1: tuple) -> None:
        """Pointing at a different structurally valid event still disagrees."""
        _narration, story, export = sources_ep1
        evidence = copy.deepcopy(_law_evidence(story))
        evidence["index"] = 64
        with pytest.raises(ValueError, match="does not identify the moment"):
            resolve_event(export, evidence, "test")

    def test_a_mutated_actual_event_tick_is_refused(self, sources_ep1: tuple) -> None:
        """Editing the export event itself breaks the agreement equally."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["events"][0]["tick"] = 6
        with pytest.raises(ValueError, match="share a tick"):
            resolve_event(export, _law_evidence(story), "test")

    def test_a_boolean_event_tick_is_refused(self, sources_ep1: tuple) -> None:
        """A boolean tick is validated before equality can excuse it."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["events"][0]["tick"] = True
        with pytest.raises(TypeError, match="tick"):
            resolve_event(export, _law_evidence(story), "test")

    def test_a_non_dict_event_is_refused(self, sources_ep1: tuple) -> None:
        """The envelope tolerates garbage in the events array; this layer refuses."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["events"][0] = 999
        with pytest.raises(TypeError, match="must be a dict"):
            resolve_event(export, _law_evidence(story), "test")

    def test_an_event_missing_a_field_is_refused(self, sources_ep1: tuple) -> None:
        """An event without a tick cannot prove the moment it records."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        del export["events"][0]["tick"]
        with pytest.raises(ValueError, match="is missing tick"):
            resolve_event(export, _law_evidence(story), "test")

    def test_a_non_list_events_section_is_refused(self, sources_ep1: tuple) -> None:
        """An export whose events section is not a list has no moments at all."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["events"] = {}
        with pytest.raises(TypeError, match="must be a list"):
            resolve_event(export, _law_evidence(story), "test")


class TestEntityResolvers:
    """Strict world lookups: exactly one match, valid shape, or refusal."""

    def test_the_canonical_entities_resolve(self, sources_ep1: tuple) -> None:
        """Law, district, boundary and wall all resolve from the real export."""
        _narration, _story, export = sources_ep1
        assert resolve_law(export, "law_movement_sharing", "test")["name"] == (
            "movement_resource_sharing"
        )
        assert resolve_district(export, "district_a", "test")["id"] == "district_a"
        boundary = resolve_boundary(export, "boundary_ab", "test")
        assert boundary["district_a_id"] == "district_a"
        wall, wall_boundary = resolve_wall(export, "wall_boundary_ab", "test")
        assert wall["id"] == "wall_boundary_ab"
        assert wall_boundary["id"] == "boundary_ab"

    def test_a_missing_entity_is_refused(self, sources_ep1: tuple) -> None:
        """A label is never written for an entity the world cannot produce."""
        _narration, _story, export = sources_ep1
        with pytest.raises(ValueError, match="does not carry"):
            resolve_law(export, "law_border_control", "test")

    def test_a_duplicated_entity_is_refused(self, sources_ep1: tuple) -> None:
        """World identifiers are unique, so a duplicate is not from the engine."""
        _narration, _story, export = sources_ep1
        export = copy.deepcopy(export)
        export["world"]["districts"].append(copy.deepcopy(export["world"]["districts"][0]))
        with pytest.raises(ValueError, match="carries district .* 2 times|2 times"):
            resolve_district(export, "district_a", "test")

    def test_a_blank_law_name_is_refused(self, sources_ep1: tuple) -> None:
        """A law without a usable name cannot be labeled."""
        _narration, _story, export = sources_ep1
        export = copy.deepcopy(export)
        export["world"]["laws"][0]["name"] = "   "
        with pytest.raises(ValueError, match="name of law"):
            resolve_law(export, "law_movement_sharing", "test")

    def test_a_boundary_self_loop_is_refused(self, sources_ep1: tuple) -> None:
        """A boundary joins two different districts."""
        _narration, _story, export = sources_ep1
        export = copy.deepcopy(export)
        export["world"]["boundaries"][0]["district_b_id"] = "district_a"
        with pytest.raises(ValueError, match="to itself"):
            resolve_boundary(export, "boundary_ab", "test")

    def test_a_boundary_with_a_missing_endpoint_is_refused(self, sources_ep1: tuple) -> None:
        """Both endpoint districts must resolve exactly once."""
        _narration, _story, export = sources_ep1
        export = copy.deepcopy(export)
        export["world"]["boundaries"][0]["district_b_id"] = "district_z"
        with pytest.raises(ValueError, match="does not carry"):
            resolve_boundary(export, "boundary_ab", "test")

    def test_a_wall_on_a_missing_boundary_is_refused(self, sources_ep1: tuple) -> None:
        """A wall pointing at an absent boundary is a dangling relation."""
        _narration, _story, export = sources_ep1
        export = copy.deepcopy(export)
        export["world"]["walls"][0]["boundary_id"] = "boundary_zz"
        with pytest.raises(ValueError, match="does not carry"):
            resolve_wall(export, "wall_boundary_ab", "test")

    def test_a_boundary_denying_its_wall_is_refused(self, sources_ep1: tuple) -> None:
        """A wall phrase is never built from a relation the other side denies."""
        _narration, _story, export = sources_ep1
        export = copy.deepcopy(export)
        export["world"]["boundaries"][0]["wall_id"] = None
        with pytest.raises(ValueError, match="the other side denies"):
            resolve_wall(export, "wall_boundary_ab", "test")

    def test_a_boundary_claiming_another_wall_is_refused(self, sources_ep1: tuple) -> None:
        """A wall phrase is never built from a contradicted relation."""
        _narration, _story, export = sources_ep1
        export = copy.deepcopy(export)
        export["world"]["boundaries"][0]["wall_id"] = "wall_boundary_cd"
        with pytest.raises(ValueError, match="the other side contradicts"):
            resolve_wall(export, "wall_boundary_ab", "test")


class TestFactForBeat:
    """Fact resolution: evidence agreement, subjects, and the derived event."""

    def test_the_canonical_fact_resolves(self, sources_ep1: tuple) -> None:
        """The wall fact resolves with every agreement proven."""
        _narration, story, export = sources_ep1
        fact = fact_for_beat(_beat(story, 1), export, "test")
        assert fact["fact_type"] == "WALL_BUILT"

    def test_a_missing_fact_is_refused(self, sources_ep1: tuple) -> None:
        """A fact the export does not carry cannot be realized."""
        _narration, story, export = sources_ep1
        story = copy.deepcopy(story)
        _beat(story, 1)["evidence"][0]["fact_id"] = "fact_" + "0" * 64
        with pytest.raises(ValueError, match="does not carry"):
            fact_for_beat(_beat(story, 1), export, "test")

    def test_an_evidence_field_disagreement_is_refused(self, sources_ep1: tuple) -> None:
        """Evidence and the exported fact must agree field for field."""
        _narration, story, export = sources_ep1
        story = copy.deepcopy(story)
        _beat(story, 1)["evidence"][0]["tick"] = 8
        with pytest.raises(ValueError, match="belongs to a different record"):
            fact_for_beat(_beat(story, 1), export, "test")

    def test_a_subject_disagreement_is_refused(self, sources_ep1: tuple) -> None:
        """A fact-backed beat is about the fact's own subjects and no other."""
        _narration, story, export = sources_ep1
        story = copy.deepcopy(story)
        _beat(story, 1)["subject_ids"] = ["district_a", "wall_boundary_ab"]
        with pytest.raises(ValueError, match="fact's own subjects"):
            fact_for_beat(_beat(story, 1), export, "test")

    def test_a_fact_tick_drifting_from_its_evidence_is_refused(self, sources_ep1: tuple) -> None:
        """A mutated exported fact no longer matches the story's own evidence."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["memory"]["facts"][0]["tick"] = 10
        with pytest.raises(ValueError, match="belongs to a different record"):
            fact_for_beat(_beat(story, 1), export, "test")

    def test_a_derived_event_tick_disagreement_is_refused(self, sources_ep1: tuple) -> None:
        """The fact and the actual event it derives from share a tick.

        Evidence and fact are moved together so the field-agreement loop
        passes and the later actual-event comparison is the check that fires.
        """
        _narration, story, export = sources_ep1
        story = copy.deepcopy(story)
        export = copy.deepcopy(export)
        _beat(story, 1)["evidence"][0]["tick"] = 10
        export["memory"]["facts"][0]["tick"] = 10
        with pytest.raises(ValueError, match="share a tick"):
            fact_for_beat(_beat(story, 1), export, "test")

    def test_a_beat_citing_two_memory_facts_is_refused(self, sources_ep1: tuple) -> None:
        """A fact-backed beat cites exactly one memory fact, never two."""
        _narration, story, export = sources_ep1
        story = copy.deepcopy(story)
        beat = _beat(story, 1)
        beat["evidence"].append(copy.deepcopy(beat["evidence"][0]))
        with pytest.raises(ValueError, match="exactly one memory fact"):
            fact_for_beat(beat, export, "test")

    def test_a_beat_citing_two_events_is_refused(self, sources_ep1: tuple) -> None:
        """A fact-backed beat cites the one event its fact derives from, never two."""
        _narration, story, export = sources_ep1
        story = copy.deepcopy(story)
        beat = _beat(story, 1)
        beat["evidence"].append(copy.deepcopy(beat["evidence"][1]))
        with pytest.raises(ValueError, match="cites 2 events"):
            fact_for_beat(beat, export, "test")

    def test_a_forged_fact_source_event_index_is_refused(self, sources_ep1: tuple) -> None:
        """A fact claiming a different source event index is not the beat's fact."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["memory"]["facts"][0]["source_event_index"] = 0
        with pytest.raises(ValueError, match="name one source event"):
            fact_for_beat(_beat(story, 1), export, "test")

    def test_a_forged_fact_source_event_type_is_refused(self, sources_ep1: tuple) -> None:
        """A fact claiming a different source event type is refused on that alone.

        Only source_event_type moves; fact_type and every evidence field stay
        canonical, so the refusal is attributable to this check and no sibling.
        """
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["memory"]["facts"][0]["source_event_type"] = "LAW_CHANGED"
        with pytest.raises(ValueError, match="name one source event"):
            fact_for_beat(_beat(story, 1), export, "test")

    def test_a_same_triplet_event_redirect_is_refused(self, sources_ep1: tuple) -> None:
        """Evidence pointing at a same-type, same-source, same-tick twin dies.

        A forged export duplicates the source event at another index; every
        triplet equality holds, so only the evidence-index-versus-declared-
        index identity can expose the redirect.
        """
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["events"][60] = copy.deepcopy(export["events"][61])
        story = copy.deepcopy(story)
        _beat(story, 1)["evidence"][1]["index"] = 60
        with pytest.raises(ValueError, match="name one source event"):
            fact_for_beat(_beat(story, 1), export, "test")


class TestFactParameters:
    """Structured detail extraction for both supported fact types."""

    def test_the_wall_built_sentence_derives(self, sources_ep1: tuple) -> None:
        """The canonical WALL_BUILT fact realizes to the reviewed sentence."""
        _narration, story, export = sources_ep1
        text = realized_text_for_beat("DURABLE_CONSEQUENCE", _beat(story, 1), export, "test")
        assert text == (
            "At tick 9, a permanent wall was built on the boundary between District A "
            "and District B."
        )

    def test_the_persistence_sentence_derives(self, sources_ep2: tuple) -> None:
        """The canonical persistence fact realizes to the reviewed sentence."""
        _narration, story, export = sources_ep2
        text = realized_text_for_beat("CONSEQUENCE_PERSISTED", _beat(story, 0), export, "test")
        assert text == (
            "At tick 22, the movement resource sharing law was restored; the permanent "
            "wall on the boundary between District A and District B, built at tick 9, "
            "remained in the world."
        )

    def test_a_missing_required_detail_is_refused(self, sources_ep1: tuple) -> None:
        """A fact without a field the template reads cannot be realized."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        del export["memory"]["facts"][0]["details"]["boundary_id"]
        with pytest.raises(ValueError, match="missing required fields"):
            realized_text_for_beat("DURABLE_CONSEQUENCE", _beat(story, 1), export, "test")

    def test_a_wrong_detail_type_is_refused(self, sources_ep1: tuple) -> None:
        """A fractional tick in the details is a type error, not a variant."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["memory"]["facts"][0]["details"]["built_tick"] = 9.0
        with pytest.raises(TypeError, match="built_tick"):
            realized_text_for_beat("DURABLE_CONSEQUENCE", _beat(story, 1), export, "test")

    def test_an_impermanent_wall_fact_is_refused(self, sources_ep1: tuple) -> None:
        """Only a permanent wall is remembered as built."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["memory"]["facts"][0]["details"]["permanent"] = False
        with pytest.raises(ValueError, match="only a permanent wall is remembered as built"):
            realized_text_for_beat("DURABLE_CONSEQUENCE", _beat(story, 1), export, "test")

    def test_an_impermanent_persisted_wall_is_refused(self, sources_ep2: tuple) -> None:
        """Only a permanent wall is remembered as persisting."""
        _narration, story, export = sources_ep2
        export = copy.deepcopy(export)
        export["memory"]["facts"][1]["details"]["wall_permanent"] = False
        with pytest.raises(ValueError, match="remembered as persisting"):
            realized_text_for_beat("CONSEQUENCE_PERSISTED", _beat(story, 0), export, "test")

    def test_a_built_tick_disagreeing_with_the_fact_is_refused(self, sources_ep1: tuple) -> None:
        """A built fact and its wall share a tick."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["memory"]["facts"][0]["details"]["built_tick"] = 10
        with pytest.raises(ValueError, match="share a tick"):
            realized_text_for_beat("DURABLE_CONSEQUENCE", _beat(story, 1), export, "test")

    def test_a_restored_tick_disagreeing_with_the_fact_is_refused(self, sources_ep2: tuple) -> None:
        """A restoration fact and its restored law share a tick."""
        _narration, story, export = sources_ep2
        export = copy.deepcopy(export)
        export["memory"]["facts"][1]["details"]["restored_tick"] = 23
        with pytest.raises(ValueError, match="share a tick"):
            realized_text_for_beat("CONSEQUENCE_PERSISTED", _beat(story, 0), export, "test")

    def test_a_forged_wall_built_tick_is_refused(self, sources_ep2: tuple) -> None:
        """The persisted wall's claimed built tick follows the world's record."""
        _narration, story, export = sources_ep2
        export = copy.deepcopy(export)
        export["memory"]["facts"][1]["details"]["wall_built_tick"] = 8
        with pytest.raises(ValueError, match="world's wall records tick"):
            realized_text_for_beat("CONSEQUENCE_PERSISTED", _beat(story, 0), export, "test")

    def test_a_world_wall_tick_disagreement_is_refused(self, sources_ep1: tuple) -> None:
        """A built fact whose tick the world's wall denies cannot be realized."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["world"]["walls"][0]["built_tick"] = 8
        with pytest.raises(ValueError, match="world's wall records tick"):
            realized_text_for_beat("DURABLE_CONSEQUENCE", _beat(story, 1), export, "test")

    def test_swapped_endpoint_details_are_refused(self, sources_ep1: tuple) -> None:
        """Endpoints are the world's own and are never swapped or substituted."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        details = export["memory"]["facts"][0]["details"]
        details["district_a_id"], details["district_b_id"] = (
            details["district_b_id"],
            details["district_a_id"],
        )
        with pytest.raises(ValueError, match="never swapped or substituted"):
            realized_text_for_beat("DURABLE_CONSEQUENCE", _beat(story, 1), export, "test")

    def test_a_substituted_endpoint_detail_is_refused(self, sources_ep1: tuple) -> None:
        """A real-but-wrong district in the details disagrees with the world."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["memory"]["facts"][0]["details"]["district_b_id"] = "district_c"
        with pytest.raises(ValueError, match="never swapped or substituted"):
            realized_text_for_beat("DURABLE_CONSEQUENCE", _beat(story, 1), export, "test")

    def test_a_drifted_law_name_detail_is_refused(self, sources_ep2: tuple) -> None:
        """A presentation label follows the world's own name."""
        _narration, story, export = sources_ep2
        export = copy.deepcopy(export)
        export["memory"]["facts"][1]["details"]["law_name"] = "movement_resource_pooling"
        with pytest.raises(ValueError, match="world's own name"):
            realized_text_for_beat("CONSEQUENCE_PERSISTED", _beat(story, 0), export, "test")

    def test_a_non_boolean_permanence_flag_is_refused(self, sources_ep1: tuple) -> None:
        """A truthy integer is not a genuine True; the flag is typed before read."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["memory"]["facts"][0]["details"]["permanent"] = 1
        with pytest.raises(TypeError, match="must be a bool"):
            realized_text_for_beat("DURABLE_CONSEQUENCE", _beat(story, 1), export, "test")

    def test_a_substituted_wall_identity_is_refused(self, sources_ep1: tuple) -> None:
        """Details naming a different real wall die at the fact's own identity.

        The injected second wall is fully world-consistent -- reciprocal
        boundary, matching endpoints, matching built tick -- so every world
        check would pass; only the binding to the fact's own publisher can
        expose that the sentence would restate another entity's story.
        """
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        second = copy.deepcopy(export["world"]["walls"][0])
        second["id"] = "wall_boundary_cd"
        second["boundary_id"] = "boundary_cd"
        export["world"]["walls"].append(second)
        for boundary in export["world"]["boundaries"]:
            if boundary["id"] == "boundary_cd":
                boundary["wall_id"] = "wall_boundary_cd"
        details = export["memory"]["facts"][0]["details"]
        details["wall_id"] = "wall_boundary_cd"
        details["boundary_id"] = "boundary_cd"
        details["district_a_id"] = "district_c"
        details["district_b_id"] = "district_d"
        with pytest.raises(ValueError, match="its own subject"):
            realized_text_for_beat("DURABLE_CONSEQUENCE", _beat(story, 1), export, "test")

    def test_a_substituted_law_identity_is_refused(self, sources_ep2: tuple) -> None:
        """Details naming a different real law with the same name still die."""
        _narration, story, export = sources_ep2
        export = copy.deepcopy(export)
        second = copy.deepcopy(export["world"]["laws"][0])
        second["id"] = "law_border_control"
        export["world"]["laws"].append(second)
        export["memory"]["facts"][1]["details"]["law_id"] = "law_border_control"
        with pytest.raises(ValueError, match="its own subject"):
            realized_text_for_beat("CONSEQUENCE_PERSISTED", _beat(story, 0), export, "test")

    def test_a_persisted_wall_outside_the_facts_subjects_is_refused(
        self, sources_ep2: tuple
    ) -> None:
        """A persistence fact speaks only about a wall among its own subjects."""
        _narration, story, export = sources_ep2
        export = copy.deepcopy(export)
        second = copy.deepcopy(export["world"]["walls"][0])
        second["id"] = "wall_boundary_cd"
        second["boundary_id"] = "boundary_cd"
        export["world"]["walls"].append(second)
        for boundary in export["world"]["boundaries"]:
            if boundary["id"] == "boundary_cd":
                boundary["wall_id"] = "wall_boundary_cd"
        details = export["memory"]["facts"][1]["details"]
        details["wall_id"] = "wall_boundary_cd"
        details["boundary_id"] = "boundary_cd"
        with pytest.raises(ValueError, match="its own subject"):
            realized_text_for_beat("CONSEQUENCE_PERSISTED", _beat(story, 0), export, "test")

    def test_a_persisted_boundary_disagreement_is_refused(self, sources_ep2: tuple) -> None:
        """The persistence fact's boundary claim must match the world's wall."""
        _narration, story, export = sources_ep2
        export = copy.deepcopy(export)
        export["memory"]["facts"][1]["details"]["boundary_id"] = "boundary_ac"
        with pytest.raises(ValueError, match="follows the world's own record"):
            realized_text_for_beat("CONSEQUENCE_PERSISTED", _beat(story, 0), export, "test")

    def test_a_wall_boundary_disagreement_is_refused(self, sources_ep1: tuple) -> None:
        """The fact's boundary claim must match the world's wall."""
        _narration, story, export = sources_ep1
        export = copy.deepcopy(export)
        export["memory"]["facts"][0]["details"]["boundary_id"] = "boundary_ac"
        with pytest.raises(ValueError, match="follows the world's own record"):
            realized_text_for_beat("DURABLE_CONSEQUENCE", _beat(story, 1), export, "test")

    def test_an_unknown_fact_type_is_refused(self, sources_ep1: tuple) -> None:
        """An unreviewed fact type is refused, never paraphrased."""
        _narration, story, export = sources_ep1
        story = copy.deepcopy(story)
        export = copy.deepcopy(export)
        _beat(story, 1)["evidence"][0]["fact_type"] = "WALL_PAINTED"
        export["memory"]["facts"][0]["fact_type"] = "WALL_PAINTED"
        export["memory"]["facts"][0]["source_event_type"] = "WALL_BUILT"
        with pytest.raises(ValueError, match="no reviewed realization exists"):
            realized_text_for_beat("DURABLE_CONSEQUENCE", _beat(story, 1), export, "test")


class TestEventBackedRealization:
    """Template-backed derivation: subjects, ticks, and the absence beat."""

    def test_the_law_change_sentence_derives(self, sources_ep1: tuple) -> None:
        """The canonical LAW_CHANGE beat realizes through the law's own name."""
        _narration, story, export = sources_ep1
        text = realized_text_for_beat("LAW_CHANGE", _beat(story, 0), export, "test")
        assert text == "At tick 7, the movement resource sharing law changed."

    def test_the_wall_state_sentence_derives(self, sources_ep1: tuple) -> None:
        """The canonical WALL_STATE_CHANGE beat realizes through the wall phrase."""
        _narration, story, export = sources_ep1
        text = realized_text_for_beat("WALL_STATE_CHANGE", _beat(story, 2), export, "test")
        assert text == "At tick 9, the wall between District A and District B changed state."

    def test_the_absence_sentence_derives(self, sources_ep0: tuple) -> None:
        """The baseline's absence beat realizes to the carried sentence."""
        _narration, story, export = sources_ep0
        text = realized_text_for_beat("NO_EMPHASIZED_BEATS", _beat(story, 0), export, "test")
        assert text == "No beats were emphasized for this episode."

    def test_an_absence_beat_with_evidence_is_refused(self, sources_ep0: tuple) -> None:
        """The absence beat reports an absence and cites nothing."""
        _narration, story, export = sources_ep0
        story = copy.deepcopy(story)
        _beat(story, 0)["evidence"] = [
            {
                "index": 0,
                "kind": "event",
                "source_id": "law_movement_sharing",
                "tick": 1,
                "type": "LAW_CHANGED",
            }
        ]
        with pytest.raises(ValueError, match="cites nothing"):
            realized_text_for_beat("NO_EMPHASIZED_BEATS", _beat(story, 0), export, "test")

    def test_a_beat_citing_two_events_is_refused(self, sources_ep1: tuple) -> None:
        """An event-derived beat cites exactly one event."""
        _narration, story, export = sources_ep1
        story = copy.deepcopy(story)
        beat = _beat(story, 0)
        beat["evidence"] = beat["evidence"] + beat["evidence"]
        with pytest.raises(ValueError, match="exactly one event"):
            realized_text_for_beat("LAW_CHANGE", beat, export, "test")

    def test_a_multi_subject_event_beat_is_refused(self, sources_ep1: tuple) -> None:
        """An event-derived beat is about exactly one entity."""
        _narration, story, export = sources_ep1
        story = copy.deepcopy(story)
        _beat(story, 0)["subject_ids"] = ["district_a", "law_movement_sharing"]
        with pytest.raises(ValueError, match="exactly one entity"):
            realized_text_for_beat("LAW_CHANGE", _beat(story, 0), export, "test")

    def test_a_subject_outside_its_class_is_refused(self, sources_ep1: tuple) -> None:
        """A law beat's subject resolves in the law collection and nowhere else."""
        _narration, story, export = sources_ep1
        story = copy.deepcopy(story)
        _beat(story, 0)["subject_ids"] = ["district_a"]
        _beat(story, 0)["evidence"][0]["source_id"] = "district_a"
        export = copy.deepcopy(export)
        export["events"][0]["source_id"] = "district_a"
        with pytest.raises(ValueError, match="does not carry"):
            realized_text_for_beat("LAW_CHANGE", _beat(story, 0), export, "test")

    def test_an_unknown_kind_is_refused(self, sources_ep1: tuple) -> None:
        """A kind outside the narration vocabulary has no realization."""
        _narration, story, export = sources_ep1
        with pytest.raises(ValueError, match="has no narration text source"):
            realized_text_for_beat("WEATHER_CHANGE", _beat(story, 0), export, "test")
