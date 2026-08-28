"""Standalone validation of the Episode Caption Plan V1 envelope."""

import pytest

from living_diorama.caption.caption_planner import build_episode_caption_plan_document
from living_diorama.caption.caption_schema_v1 import validate_episode_caption_plan


def _valid_plan(realization_ep1, presentation_ep1) -> dict:
    """Valid plan."""
    return build_episode_caption_plan_document(realization_ep1, presentation_ep1)


def test_valid_plan_round_trips(realization_ep1, presentation_ep1) -> None:
    """Valid plan round trips."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    assert validate_episode_caption_plan(plan) == plan


def test_top_level_keys_exact(realization_ep1, presentation_ep1) -> None:
    """Top level keys exact."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    assert set(plan.keys()) == {
        "accounting",
        "captions",
        "clock",
        "format",
        "policy",
        "schema_version",
        "source",
    }


def test_missing_top_level_key_refused(realization_ep1, presentation_ep1) -> None:
    """Missing top level key refused."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    del plan["clock"]
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_extra_top_level_key_refused(realization_ep1, presentation_ep1) -> None:
    """Extra top level key refused."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["extra"] = 1
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_wrong_format_refused(realization_ep1, presentation_ep1) -> None:
    """Wrong format refused."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["format"] = "wrong"
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_wrong_policy_refused(realization_ep1, presentation_ep1) -> None:
    """Wrong policy refused."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["policy"] = "wrong_policy"
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_wrong_schema_version_refused(realization_ep1, presentation_ep1) -> None:
    """Wrong schema version refused."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["schema_version"] = 2
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_source_keys_exact_and_match_phase28(realization_ep1, presentation_ep1) -> None:
    """Source keys exact and match phase28."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    assert set(plan["source"].keys()) == {
        "episode",
        "mode",
        "previous_episode",
        "presentation_plan_sha256",
        "presentation_schema_version",
        "realization_plan_sha256",
        "realization_schema_version",
    }


def test_source_bad_hash_refused(realization_ep1, presentation_ep1) -> None:
    """Source bad hash refused."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["source"]["realization_plan_sha256"] = "not-a-hash"
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_baseline_requires_null_previous_episode(realization_ep0, presentation_ep0) -> None:
    """Baseline requires null previous episode."""
    plan = build_episode_caption_plan_document(realization_ep0, presentation_ep0)
    assert plan["source"]["previous_episode"] is None
    plan["source"]["previous_episode"] = 0
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_transition_requires_direct_succession(realization_ep1, presentation_ep1) -> None:
    """Transition requires direct succession."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["source"]["previous_episode"] = 9
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_clock_keys_exact(realization_ep1, presentation_ep1) -> None:
    """Clock keys exact."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    assert set(plan["clock"].keys()) == {"fps", "presentation_frames_total"}


def test_clock_fps_matches_ep1(realization_ep1, presentation_ep1) -> None:
    """Clock FPS matches ep1."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    assert plan["clock"]["fps"] == 24


def test_clock_presentation_frames_total_matches_ep1(realization_ep1, presentation_ep1) -> None:
    """Clock presentation frames total matches ep1."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    assert plan["clock"]["presentation_frames_total"] == 720


def test_captions_must_not_be_empty(realization_ep1, presentation_ep1) -> None:
    """Captions must not be empty."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["captions"] = []
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_caption_keys_exact(realization_ep1, presentation_ep1) -> None:
    """Caption keys exact."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    for cue in plan["captions"]:
        assert set(cue.keys()) == {
            "caption_id",
            "caption_text",
            "presentation_end_frame",
            "presentation_start_frame",
            "realization_id",
            "unit_id",
            "window_id",
        }


def test_caption_id_positional(realization_ep1, presentation_ep1) -> None:
    """Caption ID positional."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["captions"][0]["caption_id"] = "caption_9999"
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_caption_unit_id_positional(realization_ep1, presentation_ep1) -> None:
    """Caption unit ID positional."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["captions"][0]["unit_id"] = "unit_9999"
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_caption_end_before_start_refused(realization_ep1, presentation_ep1) -> None:
    """Caption end before start refused."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["captions"][0]["presentation_end_frame"] = (
        plan["captions"][0]["presentation_start_frame"] - 1
    )
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_caption_end_beyond_total_refused(realization_ep1, presentation_ep1) -> None:
    """Caption end beyond total refused."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["captions"][-1]["presentation_end_frame"] = (
        plan["clock"]["presentation_frames_total"] + 1000
    )
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_caption_overlap_refused(realization_ep1, presentation_ep1) -> None:
    """Caption overlap refused."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    if len(plan["captions"]) < 2:
        pytest.skip("episode has only one caption")
    plan["captions"][1]["presentation_start_frame"] = plan["captions"][0][
        "presentation_start_frame"
    ]
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_caption_text_must_be_non_blank(realization_ep1, presentation_ep1) -> None:
    """Caption text must be non blank."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["captions"][0]["caption_text"] = "   "
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_accounting_keys_exact(realization_ep1, presentation_ep1) -> None:
    """Accounting keys exact."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    assert set(plan["accounting"].keys()) == {
        "caption_frames_total",
        "captions_total",
        "uncaptioned_frames_total",
    }


def test_accounting_matches_canonical_ep1(realization_ep1, presentation_ep1) -> None:
    """Accounting matches canonical ep1."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    assert plan["accounting"]["captions_total"] == 3
    assert plan["accounting"]["caption_frames_total"] == 648
    assert plan["accounting"]["uncaptioned_frames_total"] == 72


def test_accounting_matches_canonical_ep2(realization_ep2, presentation_ep2) -> None:
    """Accounting matches canonical ep2."""
    plan = build_episode_caption_plan_document(realization_ep2, presentation_ep2)
    assert plan["accounting"]["captions_total"] == 2
    assert plan["accounting"]["caption_frames_total"] == 504
    assert plan["accounting"]["uncaptioned_frames_total"] == 48


def test_accounting_matches_canonical_ep0(realization_ep0, presentation_ep0) -> None:
    """Accounting matches canonical ep0."""
    plan = build_episode_caption_plan_document(realization_ep0, presentation_ep0)
    assert plan["accounting"]["captions_total"] == 1
    assert plan["accounting"]["caption_frames_total"] == 192
    assert plan["accounting"]["uncaptioned_frames_total"] == 0


def test_accounting_captions_total_recomputed(realization_ep1, presentation_ep1) -> None:
    """Accounting captions total recomputed."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["accounting"]["captions_total"] += 1
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_accounting_uncaptioned_recomputed(realization_ep1, presentation_ep1) -> None:
    """Accounting uncaptioned recomputed."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["accounting"]["uncaptioned_frames_total"] += 1
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)


def test_wrong_document_type_refused() -> None:
    """Wrong document type refused."""
    with pytest.raises(TypeError):
        validate_episode_caption_plan([])


def test_wrong_source_type_refused(realization_ep1, presentation_ep1) -> None:
    """Wrong source type refused."""
    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["source"] = []
    with pytest.raises(TypeError):
        validate_episode_caption_plan(plan)


def test_max_caption_frame_rail_enforced_as_plausibility_only(
    realization_ep1, presentation_ep1
) -> None:
    """Max caption frame rail enforced as plausibility only."""
    from living_diorama.caption.caption_spec import MAX_CAPTION_FRAME

    plan = _valid_plan(realization_ep1, presentation_ep1)
    plan["captions"][-1]["presentation_end_frame"] = MAX_CAPTION_FRAME + 1
    with pytest.raises(ValueError):
        validate_episode_caption_plan(plan)
