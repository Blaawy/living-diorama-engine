"""Cross-validation of an Episode Caption Plan against its actual sources.

Bindings, identity, seal.
"""

import copy

import pytest

from living_diorama.caption.caption_cross_check import validate_episode_caption_plan_against_sources
from living_diorama.caption.caption_planner import build_episode_caption_plan_document


def _sources(sources_ep1):
    """Sources."""
    realization, presentation, delivery, narration, shots, story, export = sources_ep1
    return realization, presentation, delivery, narration, shots, story, export


def test_valid_plan_passes(sources_ep1) -> None:
    """Valid plan passes."""
    realization, presentation, delivery, narration, shots, story, export = _sources(sources_ep1)
    plan = build_episode_caption_plan_document(realization, presentation)
    verified = validate_episode_caption_plan_against_sources(
        plan, realization, presentation, delivery, narration, shots, story, export
    )
    assert verified == plan


def test_wrong_realization_digest_binding_refused(sources_ep1) -> None:
    """Wrong realization digest binding refused."""
    realization, presentation, delivery, narration, shots, story, export = _sources(sources_ep1)
    plan = build_episode_caption_plan_document(realization, presentation)
    plan = copy.deepcopy(plan)
    plan["source"]["realization_plan_sha256"] = "a" * 64
    with pytest.raises(ValueError):
        validate_episode_caption_plan_against_sources(
            plan, realization, presentation, delivery, narration, shots, story, export
        )


def test_wrong_presentation_digest_binding_refused(sources_ep1) -> None:
    """Wrong presentation digest binding refused."""
    realization, presentation, delivery, narration, shots, story, export = _sources(sources_ep1)
    plan = build_episode_caption_plan_document(realization, presentation)
    plan = copy.deepcopy(plan)
    plan["source"]["presentation_plan_sha256"] = "a" * 64
    with pytest.raises(ValueError):
        validate_episode_caption_plan_against_sources(
            plan, realization, presentation, delivery, narration, shots, story, export
        )


def test_wrong_clock_fps_refused(sources_ep1) -> None:
    """Wrong clock FPS refused."""
    realization, presentation, delivery, narration, shots, story, export = _sources(sources_ep1)
    plan = build_episode_caption_plan_document(realization, presentation)
    plan = copy.deepcopy(plan)
    plan["clock"]["fps"] = 30
    with pytest.raises(ValueError):
        validate_episode_caption_plan_against_sources(
            plan, realization, presentation, delivery, narration, shots, story, export
        )


def test_cue_frame_disagreement_with_actual_window_refused(sources_ep1) -> None:
    """Cue frame disagreement with actual window refused."""
    realization, presentation, delivery, narration, shots, story, export = _sources(sources_ep1)
    plan = build_episode_caption_plan_document(realization, presentation)
    plan = copy.deepcopy(plan)
    plan["captions"][0]["presentation_start_frame"] += 1
    with pytest.raises(ValueError):
        validate_episode_caption_plan_against_sources(
            plan, realization, presentation, delivery, narration, shots, story, export
        )


def test_mismatched_caption_text_by_one_value_refused(sources_ep1) -> None:
    """Mismatched caption text by one value refused."""
    realization, presentation, delivery, narration, shots, story, export = _sources(sources_ep1)
    plan = build_episode_caption_plan_document(realization, presentation)
    plan = copy.deepcopy(plan)
    plan["captions"][0]["caption_text"] = "A completely different sentence entirely."
    with pytest.raises(ValueError):
        validate_episode_caption_plan_against_sources(
            plan, realization, presentation, delivery, narration, shots, story, export
        )


def test_seal_forced_to_disagree_by_monkeypatch(sources_ep1, monkeypatch) -> None:
    """Seal forced to disagree by monkeypatch."""
    from living_diorama.caption import caption_cross_check

    realization, presentation, delivery, narration, shots, story, export = _sources(sources_ep1)
    plan = build_episode_caption_plan_document(realization, presentation)

    def _wrong_bytes(_realization, _presentation):
        """Wrong bytes."""
        return b'{"format":"forced-disagreement"}\n'

    monkeypatch.setattr(caption_cross_check, "build_episode_caption_plan_bytes", _wrong_bytes)
    with pytest.raises(ValueError, match="deterministic derivation"):
        validate_episode_caption_plan_against_sources(
            plan, realization, presentation, delivery, narration, shots, story, export
        )


def test_upstream_gate_actually_runs_and_refuses_bad_story(sources_ep1) -> None:
    """A story plan missing a required top-level key fails the reused gate's own check."""
    realization, presentation, delivery, narration, shots, story, export = _sources(sources_ep1)
    plan = build_episode_caption_plan_document(realization, presentation)
    tampered_story = copy.deepcopy(story)
    del tampered_story["format"]
    with pytest.raises((ValueError, TypeError, KeyError)):
        validate_episode_caption_plan_against_sources(
            plan, realization, presentation, delivery, narration, shots, tampered_story, export
        )


def test_accounting_captions_total_mismatch_refused(sources_ep1) -> None:
    """Accounting captions total mismatch refused."""
    realization, presentation, delivery, narration, shots, story, export = _sources(sources_ep1)
    plan = build_episode_caption_plan_document(realization, presentation)
    plan = copy.deepcopy(plan)
    plan["accounting"]["captions_total"] += 1
    with pytest.raises(ValueError):
        validate_episode_caption_plan_against_sources(
            plan, realization, presentation, delivery, narration, shots, story, export
        )


def test_wrong_type_refused(sources_ep1) -> None:
    """Wrong type refused."""
    realization, presentation, delivery, narration, shots, story, export = _sources(sources_ep1)
    with pytest.raises(TypeError):
        validate_episode_caption_plan_against_sources(
            [], realization, presentation, delivery, narration, shots, story, export
        )


def test_all_three_canonical_episodes_pass(sources_ep0, sources_ep1, sources_ep2) -> None:
    """All three canonical episodes pass."""
    for sources in (sources_ep0, sources_ep1, sources_ep2):
        realization, presentation, delivery, narration, shots, story, export = sources
        plan = build_episode_caption_plan_document(realization, presentation)
        validate_episode_caption_plan_against_sources(
            plan, realization, presentation, delivery, narration, shots, story, export
        )
