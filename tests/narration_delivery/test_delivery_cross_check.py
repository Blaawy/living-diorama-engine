"""Cross-validation: the plan's claims must be true of its actual sources.

Schema validity is proven elsewhere; everything here offers a real plan beside
real documents and then breaks exactly one relationship at a time. The final
tests exercise the seal, because a plan that survives every named check while
not being the derivation of its sources is precisely the forgery the seal
exists to refuse.
"""

from typing import Any

import pytest

from living_diorama.narration_delivery import (
    build_episode_narration_delivery_plan_document,
    validate_narration_delivery_plan_against_sources,
)

Sources = tuple[dict[str, Any], dict[str, Any]]


def verified(plan: dict[str, Any], sources: Sources) -> dict[str, Any]:
    """Run the full cross-check and hand back the verified plan."""
    return validate_narration_delivery_plan_against_sources(plan, sources[0], sources[1])


# ---- the canonical plans verify against their own sources


def test_the_baseline_plan_verifies(plan_ep0: dict[str, Any], sources_ep0: Sources) -> None:
    """Episode 0 passes every named check and the seal."""
    assert verified(plan_ep0, sources_ep0) is plan_ep0


def test_the_fold_episode_verifies(plan_ep1: dict[str, Any], sources_ep1: Sources) -> None:
    """Episode 1 -- the backward fold -- passes every named check and the seal."""
    assert verified(plan_ep1, sources_ep1) is plan_ep1


def test_the_persistence_episode_verifies(plan_ep2: dict[str, Any], sources_ep2: Sources) -> None:
    """Episode 2 passes every named check and the seal."""
    assert verified(plan_ep2, sources_ep2) is plan_ep2


# ---- digest bindings


def test_a_plan_offered_the_wrong_narration_document_is_refused(
    plan_ep1: dict[str, Any], sources_ep2: Sources
) -> None:
    """Episode 1's plan does not schedule episode 2's narration."""
    with pytest.raises(ValueError, match="does not schedule that document"):
        verified(plan_ep1, sources_ep2)


def test_a_tampered_narration_digest_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: Sources
) -> None:
    """The narration binding names the exact document offered."""
    plan_ep1["source"]["narration_plan_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="narration plan.*does not schedule"):
        verified(plan_ep1, sources_ep1)


def test_a_tampered_shot_digest_is_refused(plan_ep1: dict[str, Any], sources_ep1: Sources) -> None:
    """So does the shot binding."""
    plan_ep1["source"]["shot_plan_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="shot direction plan.*does not schedule"):
        verified(plan_ep1, sources_ep1)


def test_a_mixed_pair_is_refused_even_with_matching_digests(
    sources_ep1: Sources, sources_ep2: Sources
) -> None:
    """A plan rebound to a shot plan its narration never reported is refused.

    The forged source block names the offered documents honestly -- both
    digests match -- but the narration plan itself reports visibility from a
    different direction, and that inner binding is the one that catches it.
    """
    import copy

    from living_diorama.persistence.json_codec import dumps_canonical
    from living_diorama.persistence.schema.state_hash import sha256_hex

    narration_ep1, _ = sources_ep1
    _, shots_ep2 = sources_ep2
    plan = copy.deepcopy(build_episode_narration_delivery_plan_document(*sources_ep1))
    plan["source"]["shot_plan_sha256"] = sha256_hex(
        dumps_canonical(shots_ep2, "shot direction plan")
    )
    with pytest.raises(ValueError, match="not the same episode's"):
        validate_narration_delivery_plan_against_sources(plan, narration_ep1, shots_ep2)


# ---- identity agreement


def test_a_tampered_episode_number_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: Sources
) -> None:
    """The plan's episode is the narration plan's episode."""
    plan_ep1["source"]["episode"] = 2
    plan_ep1["source"]["previous_episode"] = 1
    with pytest.raises(ValueError, match="declares episode"):
        verified(plan_ep1, sources_ep1)


def test_a_tampered_mode_is_refused(plan_ep1: dict[str, Any], sources_ep1: Sources) -> None:
    """A transition schedule may not claim to be a baseline.

    The mutation keeps the schema's own mode rules satisfied -- episode zero
    and a null previous episode are forged beside it -- so only the comparison
    against the narration plan refuses.
    """
    plan_ep1["source"]["mode"] = "baseline"
    plan_ep1["source"]["episode"] = 0
    plan_ep1["source"]["previous_episode"] = None
    with pytest.raises(ValueError, match="declares mode"):
        verified(plan_ep1, sources_ep1)


# ---- clock identity


def test_a_tampered_motion_time_pin_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: Sources
) -> None:
    """The pinned clock source is the shot plan's own."""
    plan_ep1["source"]["motion_time_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="names the exact"):
        verified(plan_ep1, sources_ep1)


def test_a_tampered_timeline_value_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: Sources
) -> None:
    """A self-consistent alternate clock still dies against the shot plan.

    ``1 + 25 + 119 + 48`` closes on frame 193 exactly as the locked clock
    does; only the key-for-key comparison against the source can refuse it.
    """
    plan_ep1["timeline"]["start_hold_frames"] = 25
    plan_ep1["timeline"]["transition_frames"] = 119
    plan_ep1["timeline"]["transition_start"] = 26
    with pytest.raises(ValueError, match="restated provenance"):
        verified(plan_ep1, sources_ep1)


# ---- per-record agreement


def test_a_flipped_placement_is_refused(plan_ep1: dict[str, Any], sources_ep1: Sources) -> None:
    """An unshown unit's slot may never claim to be anchored.

    Two placements are swapped so the schema's measured accounting still
    balances; only the narration plan's own visibility can catch the flip.
    """
    plan_ep1["deliveries"][0]["placement"] = "ALLOCATED_UNSHOWN"
    plan_ep1["deliveries"][1]["placement"] = "SHOT_ANCHORED"
    with pytest.raises(ValueError, match="visibility"):
        verified(plan_ep1, sources_ep1)


def test_an_anchored_slot_leaving_its_shot_is_refused(
    plan_ep2: dict[str, Any], sources_ep2: Sources
) -> None:
    """Anchored narration is scheduled only while its own footage is on screen.

    The slot is stretched backward into the opening hold -- still inside
    playback, still non-overlapping after the leading slot is trimmed, so the
    schema passes and only the shot containment check refuses.
    """
    plan_ep2["deliveries"][0]["end_frame"] = 12
    plan_ep2["deliveries"][1]["start_frame"] = 13
    with pytest.raises(ValueError, match="playback segment"):
        verified(plan_ep2, sources_ep2)


def test_a_tampered_slot_fails_the_seal(plan_ep2: dict[str, Any], sources_ep2: Sources) -> None:
    """A plausible hand-edit survives every named check and dies byte for byte.

    Trimming the leading allocated slot from 24 frames to 23 keeps every
    schema rule, every binding, every placement and the whole accounting
    intact. It is simply not the plan these sources produce, and the seal is
    the check that knows.
    """
    plan_ep2["deliveries"][0]["end_frame"] = 23
    with pytest.raises(ValueError, match="deterministic derivation"):
        verified(plan_ep2, sources_ep2)


def test_a_shifted_onset_fails_the_seal(plan_ep0: dict[str, Any], sources_ep0: Sources) -> None:
    """The baseline's one slot, delayed a frame, is refused the same way."""
    plan_ep0["deliveries"][0]["start_frame"] = 2
    with pytest.raises(ValueError, match="deterministic derivation"):
        verified(plan_ep0, sources_ep0)


def test_a_lying_unshown_reason_is_refused_through_the_seal(sources_ep1: Sources) -> None:
    """A narration lie no named check can see dies inside the derivation.

    The lying narration plan swaps one unshown reason for another valid one --
    a field no delivery record carries and no named check reads -- and the
    delivery plan is re-bound to the lying document's own digest, so every
    binding, placement, containment and accounting check passes. The seal
    re-derives from the offered documents, and the derivation's own framing
    check names the disagreement with the shot plan.
    """
    import copy

    from living_diorama.persistence.json_codec import dumps_canonical
    from living_diorama.persistence.schema.state_hash import sha256_hex

    narration, shots = sources_ep1
    plan = build_episode_narration_delivery_plan_document(narration, shots)
    lying = copy.deepcopy(narration)
    lying["units"][1]["unshown_reason"] = "TRANSITION_BUDGET_EXHAUSTED"
    forged = copy.deepcopy(plan)
    forged["source"]["narration_plan_sha256"] = sha256_hex(
        dumps_canonical(lying, "episode narration plan")
    )
    with pytest.raises(ValueError, match="shot direction plan grants"):
        validate_narration_delivery_plan_against_sources(forged, lying, shots)


def test_schema_versions_are_checked_against_the_documents(
    plan_ep1: dict[str, Any], sources_ep1: Sources
) -> None:
    """The recorded upstream versions must be the documents' own.

    Both the schema and this check pin version 1, so the mutation trips the
    schema first -- the cross-check's own comparison stands behind it for the
    day the supported set widens.
    """
    plan_ep1["source"]["narration_schema_version"] = 2
    with pytest.raises(ValueError, match="narration schema version 2"):
        verified(plan_ep1, sources_ep1)


# ---- accounting against the narration plan


def test_a_missing_slot_is_refused_against_the_narration_plan(
    plan_ep1: dict[str, Any], sources_ep1: Sources
) -> None:
    """A schedule that drops a unit is refused by the count against the sources.

    The delivery accounting is internally consistent -- records and counts are
    mutated together -- so the schema passes; the cross-check's slot count
    against the narration plan refuses. The per-field ledger comparison behind
    it is deliberate defense in depth: with the count and the per-record
    placement loop both enforced, the ledgers cannot disagree on their own,
    and the comparison stands for the day one of those checks is loosened --
    the same posture the schema takes with its own sum re-check.
    """
    del plan_ep1["deliveries"][2]
    plan_ep1["accounting"] = {
        "allocated_unshown": 1,
        "deliveries_total": 2,
        "shot_anchored": 1,
    }
    with pytest.raises(ValueError, match="carries 2 slots for a narration plan holding 3"):
        verified(plan_ep1, sources_ep1)


def test_an_anchor_to_a_nonexistent_shot_is_refused(sources_ep1: Sources) -> None:
    """A narration citation of a shot the direction does not hold is refused.

    The forged narration renames a shown unit's citation to a well-formed but
    absent shot id and the plan is re-bound to the forged document's digest, so
    every earlier named check passes; the containment lookup is the one that
    refuses.
    """
    import copy

    from living_diorama.persistence.json_codec import dumps_canonical
    from living_diorama.persistence.schema.state_hash import sha256_hex

    narration, shots = sources_ep1
    plan = build_episode_narration_delivery_plan_document(narration, shots)
    lying = copy.deepcopy(narration)
    lying["units"][0]["shot_id"] = "shot_0099"
    forged = copy.deepcopy(plan)
    forged["source"]["narration_plan_sha256"] = sha256_hex(
        dumps_canonical(lying, "episode narration plan")
    )
    with pytest.raises(ValueError, match="does not hold"):
        validate_narration_delivery_plan_against_sources(forged, lying, shots)


def test_a_tampered_shot_schema_version_is_refused(
    plan_ep1: dict[str, Any], sources_ep1: Sources
) -> None:
    """The recorded shot contract version must be the document's own.

    Both the schema and this check pin version 1, so the mutation trips the
    schema first -- the cross-check's own comparison stands behind it for the
    day the supported set widens, exactly as its narration sibling does.
    """
    plan_ep1["source"]["shot_schema_version"] = 2
    with pytest.raises(ValueError, match="shot schema version 2"):
        verified(plan_ep1, sources_ep1)


def test_a_lone_fps_tamper_is_refused_by_the_source_comparison(
    plan_ep1: dict[str, Any], sources_ep1: Sources
) -> None:
    """The fps field takes no part in closure arithmetic; only the source refuses it.

    A single-field mutation that every self-consistency rule tolerates: 25
    frames per second closes on exactly the same frame numbers as 24. The
    key-for-key comparison against the shot plan is the one check that knows
    the difference.
    """
    plan_ep1["timeline"]["fps"] = 25
    with pytest.raises(ValueError, match="restated provenance"):
        verified(plan_ep1, sources_ep1)
