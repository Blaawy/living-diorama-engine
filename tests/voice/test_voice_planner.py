"""Deriving an Episode Voice Plan from a realization and a presentation plan.

Golden capacities here are legitimate canonical test truth: they are
re-derived from locked Phase 27 window geometry, never from a measured
speech duration or sample count. No Kokoro measurement of any kind appears
anywhere in this module.
"""

import copy
from typing import Any

import pytest

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.voice.voice_planner import (
    build_episode_voice_plan_bytes,
    build_episode_voice_plan_document,
)

GOLDEN_CAPACITIES = {
    0: [192_000],
    1: [144_000, 360_000, 144_000],
    2: [360_000, 144_000],
}


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_the_canonical_geometry_matches_the_locked_presentation_windows(
    episode: int, request: pytest.FixtureRequest
) -> None:
    """The canonical geometry matches the locked presentation windows."""
    realization, presentation, _delivery, _narration, _shots, _story, _export = (
        request.getfixturevalue(f"sources_ep{episode}")
    )
    document = build_episode_voice_plan_document(realization, presentation)
    capacities = [unit["capacity_samples"] for unit in document["voice_units"]]
    assert capacities == GOLDEN_CAPACITIES[episode]
    assert document["accounting"]["capacity_samples_total"] == sum(GOLDEN_CAPACITIES[episode])
    assert document["accounting"]["voice_units_total"] == len(GOLDEN_CAPACITIES[episode])


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_derivation_is_stable_across_repeated_calls(
    episode: int, request: pytest.FixtureRequest
) -> None:
    """Derivation is stable across repeated calls."""
    realization, presentation, *_ = request.getfixturevalue(f"sources_ep{episode}")
    first = build_episode_voice_plan_bytes(realization, presentation)
    second = build_episode_voice_plan_bytes(copy.deepcopy(realization), copy.deepcopy(presentation))
    assert first == second


def test_the_source_block_binds_the_exact_offered_documents(sources_ep1: tuple[Any, ...]) -> None:
    """The source block binds the exact offered documents."""
    realization, presentation, *_ = sources_ep1
    document = build_episode_voice_plan_document(realization, presentation)
    assert document["source"]["realization_plan_sha256"] == sha256_hex(
        dumps_canonical(realization, "language realization plan")
    )
    assert document["source"]["presentation_plan_sha256"] == sha256_hex(
        dumps_canonical(presentation, "presentation plan")
    )


def test_a_realization_plan_from_a_different_episode_is_refused(
    sources_ep1: tuple[Any, ...], sources_ep2: tuple[Any, ...]
) -> None:
    """A realization plan from a different episode is refused."""
    _realization1, presentation1, *_ = sources_ep1
    realization2, _presentation2, *_ = sources_ep2
    with pytest.raises(ValueError, match="not the same episode"):
        build_episode_voice_plan_document(realization2, presentation1)


def test_a_realization_the_presentation_plan_never_presented_is_refused(
    sources_ep1: tuple[Any, ...],
) -> None:
    """A realization the presentation plan never presented is refused."""
    realization, presentation, *_ = sources_ep1
    forged_realization = copy.deepcopy(realization)
    forged_realization["realizations"][0]["realized_text"] = "A different sentence entirely."
    with pytest.raises(ValueError, match="not the same episode"):
        build_episode_voice_plan_document(forged_realization, presentation)


# ---- Test B: whole-document binding sensitivity (see architecture V2.1 §F) ----
#
# This is a planner-level determinism/binding test only. It proves that
# mutating realized_text changes the bound digest and therefore the derived
# plan -- the opposite of what an earlier, incorrect draft of this test once
# proposed. It deliberately does NOT run the mutated document through the
# full semantic Phase 26/27 source gate; that is a different concern, already
# covered by test_voice_cross_check's forged-realization tests.


def test_mutating_realized_text_changes_the_bound_digest_and_the_derived_plan(
    sources_ep1: tuple[Any, ...],
) -> None:
    """Mutating realized text changes the bound digest and the derived plan."""
    realization, presentation, *_ = sources_ep1

    mutated = copy.deepcopy(realization)
    mutated["realizations"][0]["realized_text"] = (
        mutated["realizations"][0]["realized_text"] + " Extra words that change nothing structural."
    )

    old_digest = sha256_hex(dumps_canonical(realization, "language realization plan"))
    new_digest = sha256_hex(dumps_canonical(mutated, "language realization plan"))
    assert old_digest != new_digest

    old_bytes = build_episode_voice_plan_bytes(realization, presentation)

    # The mutated realization plan no longer matches the presentation plan's
    # own bound restatement of its narration lineage byte for byte, so the
    # planner's own join refuses it -- exactly the same refusal a genuinely
    # forged realization plan would meet. Digest sensitivity is proven at the
    # digest itself, above; this proves the planner never silently accepts a
    # mismatched pair either.
    with pytest.raises(ValueError, match="not the same episode"):
        build_episode_voice_plan_bytes(mutated, presentation)

    # Rebuild presentation on top of the SAME mutated realization plan, so
    # the pair is internally consistent again, and prove the derived voice
    # plan bytes -- and specifically the bound digest -- differ from the
    # unmutated pair's.
    from living_diorama.presentation import build_episode_presentation_plan_document

    _realization, _presentation, delivery, narration, _shots, _story, _export = sources_ep1
    mutated_presentation = build_episode_presentation_plan_document(delivery, narration, mutated)
    new_bytes = build_episode_voice_plan_bytes(mutated, mutated_presentation)

    assert old_bytes != new_bytes
    old_document = build_episode_voice_plan_document(realization, presentation)
    new_document = build_episode_voice_plan_document(mutated, mutated_presentation)
    assert (
        old_document["source"]["realization_plan_sha256"]
        != new_document["source"]["realization_plan_sha256"]
    )
