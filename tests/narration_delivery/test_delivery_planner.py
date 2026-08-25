"""The delivery planner: canonical slots, the allocation algorithm, and refusals.

Two layers of proof. The canonical tests pin the exact slots the locked
fixtures produce, so the policy's real output is a reviewed constant of the
suite rather than an emergent behaviour. The algorithm tests drive
``resolve_delivery_slots`` directly over structural shapes the canonical chain
does not (yet) contain -- trailing runs, interior free intervals, forward
folds -- because a policy is total over its inputs, not over its examples.
"""

from typing import Any

import pytest

from living_diorama.narration_delivery import (
    build_episode_narration_delivery_plan_bytes,
    build_episode_narration_delivery_plan_document,
    resolve_delivery_slots,
)

Sources = tuple[dict[str, Any], dict[str, Any]]


def slots_of(plan: dict[str, Any]) -> list[tuple[str, str, int, int]]:
    """Return each delivery as (unit_id, placement, start, end) for comparison."""
    return [
        (
            record["unit_id"],
            record["placement"],
            record["start_frame"],
            record["end_frame"],
        )
        for record in plan["deliveries"]
    ]


# ---- the canonical episodes, pinned slot by slot


def test_episode_zero_gives_the_whole_playback_to_the_empty_result(
    plan_ep0: dict[str, Any],
) -> None:
    """One unshown unit, no anchors: the free interval is all 192 playback frames.

    The establishing shot itself runs to frame 193, so this slot is also the
    witness clamp exercised on the simplest possible episode.
    """
    assert slots_of(plan_ep0) == [("unit_0001", "ALLOCATED_UNSHOWN", 1, 192)]
    assert plan_ep0["accounting"] == {
        "allocated_unshown": 1,
        "deliveries_total": 1,
        "shot_anchored": 0,
    }


def test_episode_one_folds_the_trapped_consequence_backward(plan_ep1: dict[str, Any]) -> None:
    """The canonical fold: two adjacent beat shots around an unshown PRIMARY.

    The seal shot's 71 frames split 36/35 in unit order, the law's narration
    keeps its onset on the cut at frame 25, and the consequence is spoken over
    the tail of the shot that just showed the law changing -- while staying
    UNSHOWN.
    """
    assert slots_of(plan_ep1) == [
        ("unit_0001", "SHOT_ANCHORED", 25, 60),
        ("unit_0002", "ALLOCATED_UNSHOWN", 61, 95),
        ("unit_0003", "SHOT_ANCHORED", 96, 144),
    ]
    assert plan_ep1["accounting"] == {
        "allocated_unshown": 1,
        "deliveries_total": 3,
        "shot_anchored": 2,
    }


def test_episode_two_places_the_persisted_consequence_in_the_opening_hold(
    plan_ep2: dict[str, Any],
) -> None:
    """A leading unshown unit takes the free interval before the first anchor."""
    assert slots_of(plan_ep2) == [
        ("unit_0001", "ALLOCATED_UNSHOWN", 1, 24),
        ("unit_0002", "SHOT_ANCHORED", 25, 144),
    ]
    assert plan_ep2["accounting"] == {
        "allocated_unshown": 1,
        "deliveries_total": 2,
        "shot_anchored": 1,
    }


def test_the_canonical_capacity_is_stated_not_repaired(plan_ep1: dict[str, Any]) -> None:
    """The 8-second contract: valid structure, no speech-feasibility claim.

    The trapped PRIMARY consequence gets 35 frames -- about a second and a
    half of the episode's 8.0 seconds -- for a nineteen-word sentence. This
    layer emits that structural maximum and nothing here inflates it, drops a
    unit, extends the episode, or consults the text to second-guess it: the
    slots tile the anchored segment exactly and the plan validates. Whether a
    natural voice fits is the voice layer's measured question, and this test
    exists so nobody mistakes a valid delivery plan for a promise that it
    does.
    """
    timeline = plan_ep1["timeline"]
    playback_frames = timeline["end_frame"] - 1 - timeline["start_frame"] + 1
    assert playback_frames == 192
    assert timeline["fps"] == 24
    trapped = plan_ep1["deliveries"][1]
    assert trapped["placement"] == "ALLOCATED_UNSHOWN"
    assert trapped["end_frame"] - trapped["start_frame"] + 1 == 35


def test_the_timeline_is_copied_from_the_shot_plan(
    plan_ep1: dict[str, Any], sources_ep1: Sources
) -> None:
    """The clock is restated provenance, key for key, never arithmetic here."""
    assert plan_ep1["timeline"] == sources_ep1[1]["timeline"]


def test_the_source_block_binds_both_documents_and_the_clock(
    plan_ep2: dict[str, Any], sources_ep2: Sources
) -> None:
    """Digests, identity and versions all come from the offered documents."""
    narration, shots = sources_ep2
    source = plan_ep2["source"]
    assert source["narration_schema_version"] == narration["schema_version"]
    assert source["shot_schema_version"] == shots["schema_version"]
    assert source["motion_time_sha256"] == shots["source"]["motion_time_sha256"]
    assert source["episode"] == narration["source"]["episode"]
    assert source["mode"] == narration["source"]["mode"]
    assert source["previous_episode"] == narration["source"]["previous_episode"]
    assert source["shot_plan_sha256"] == narration["source"]["shot_plan_sha256"]


# ---- prose is not an input


def test_changing_every_sentence_moves_no_slot(sources_ep1: Sources) -> None:
    """Wording is not a timing input: same structure, same slots.

    The planner is handed a narration document whose sentences have all been
    replaced, with everything structural untouched. The derived slots are
    identical, which is the behavioural half of the no-text rule -- the
    boundary suite proves structurally that no module here even reads the
    field. The whole documents differ, of course: the digest binding names the
    changed input, which is exactly what it is for.
    """
    narration, shots = sources_ep1
    reworded = {
        **narration,
        "units": [
            {**unit, "text": f"Reworded sentence {index}."}
            for index, unit in enumerate(narration["units"], start=1)
        ],
    }
    original = build_episode_narration_delivery_plan_document(narration, shots)
    changed = build_episode_narration_delivery_plan_document(reworded, shots)
    assert slots_of(changed) == slots_of(original)
    assert changed["source"]["narration_plan_sha256"] != original["source"]["narration_plan_sha256"]


def test_a_very_long_sentence_moves_no_slot(sources_ep2: Sources) -> None:
    """A ten-thousand-word sentence is carried by upstream, not measured here."""
    narration, shots = sources_ep2
    unit = dict(narration["units"][0])
    unit["text"] = "word " * 9999 + "word."
    padded = {**narration, "units": [unit, *narration["units"][1:]]}
    assert slots_of(build_episode_narration_delivery_plan_document(padded, shots)) == slots_of(
        build_episode_narration_delivery_plan_document(narration, shots)
    )


# ---- the pair must join


def test_a_narration_plan_offered_with_the_wrong_shot_plan_is_refused(
    sources_ep1: Sources, sources_ep2: Sources
) -> None:
    """Episode 1's narration under episode 2's direction is not a schedule."""
    narration, _ = sources_ep1
    _, wrong_shots = sources_ep2
    with pytest.raises(ValueError, match="not about the same directed episode"):
        build_episode_narration_delivery_plan_document(narration, wrong_shots)


def test_a_lying_framing_field_is_refused(sources_ep1: Sources) -> None:
    """A narration unit whose copied span drifts from the direction is refused.

    The narration plan validates on its own -- the lie is internally
    consistent -- so only the pairing with the actual shot plan can catch it.
    """
    narration, shots = sources_ep1
    unit = dict(narration["units"][0])
    unit["start_frame"] = unit["start_frame"] + 1
    unit["end_frame"] = unit["end_frame"] + 1
    lying = {**narration, "units": [unit, *narration["units"][1:]]}
    with pytest.raises(ValueError, match="shot direction plan grants"):
        build_episode_narration_delivery_plan_document(lying, shots)


def test_an_invalid_narration_document_is_refused_first(sources_ep1: Sources) -> None:
    """The inputs' own contracts run before any slot arithmetic."""
    narration, shots = sources_ep1
    broken = {**narration, "units": []}
    with pytest.raises(ValueError, match="carries no units"):
        build_episode_narration_delivery_plan_document(broken, shots)


def test_an_invalid_shot_document_is_refused_first(sources_ep1: Sources) -> None:
    """So does the direction's."""
    narration, shots = sources_ep1
    broken = {**shots, "shots": []}
    with pytest.raises(ValueError, match="carries no shots"):
        build_episode_narration_delivery_plan_document(narration, broken)


# ---- the algorithm, driven directly


def test_a_sole_shown_unit_takes_its_whole_segment() -> None:
    """One anchored claimant, one segment, every frame of it."""
    assert resolve_delivery_slots([(25, 144)], 1, 192) == [(25, 144)]


def test_a_merged_shot_partitions_among_its_units_in_order() -> None:
    """Three units sharing one merged shot split its segment three ways."""
    assert resolve_delivery_slots([(25, 96), (25, 96), (25, 96)], 1, 192) == [
        (25, 48),
        (49, 72),
        (73, 96),
    ]


def test_a_leading_run_takes_the_frames_before_the_first_anchor() -> None:
    """The canonical episode 2 shape, as bare structure."""
    assert resolve_delivery_slots([None, (25, 144)], 1, 192) == [(1, 24), (25, 144)]


def test_a_trailing_run_takes_the_frames_after_the_last_anchor() -> None:
    """A final unshown unit is hosted by the closing free interval."""
    assert resolve_delivery_slots([(25, 144), None], 1, 192) == [(25, 144), (145, 192)]


def test_an_interior_run_takes_the_free_interval_between_anchors() -> None:
    """Establishing frames between two beat segments host the run between them."""
    assert resolve_delivery_slots([(1, 50), None, (100, 192)], 1, 192) == [
        (1, 50),
        (51, 99),
        (100, 192),
    ]


def test_a_multi_unit_run_partitions_its_free_interval() -> None:
    """Two unshown units split the opening hold's 24 frames twelve each."""
    assert resolve_delivery_slots([None, None, (25, 144)], 1, 192) == [
        (1, 12),
        (13, 24),
        (25, 144),
    ]


def test_an_all_unshown_episode_partitions_the_whole_playback() -> None:
    """No anchors at all: the playback domain is the one free interval."""
    assert resolve_delivery_slots([None, None], 1, 192) == [(1, 96), (97, 192)]


def test_a_trapped_run_folds_backward_into_the_previous_segment() -> None:
    """The canonical episode 1 shape: zero free frames between adjacent anchors."""
    assert resolve_delivery_slots([(25, 95), None, (96, 144)], 1, 192) == [
        (25, 60),
        (61, 95),
        (96, 144),
    ]


def test_a_backward_fold_keeps_the_next_onset_on_its_cut() -> None:
    """Folding backward never delays the following unit past its own footage."""
    slots = resolve_delivery_slots([(25, 95), None, (96, 144)], 1, 192)
    assert slots[2][0] == 96


def test_a_document_start_trap_folds_forward() -> None:
    """No preceding shown unit and no free frames: the next segment hosts.

    Unreachable under the canonical clock, whose start hold always precedes
    the first beat shot -- but the policy is total, and the mirrored fold is
    the only remaining direction.
    """
    assert resolve_delivery_slots([None, (1, 100)], 1, 192) == [(1, 50), (51, 100)]


def test_a_forward_fold_precedes_the_segments_own_units() -> None:
    """A folded leading run speaks before the unit whose segment hosts it."""
    slots = resolve_delivery_slots([None, None, (1, 90)], 1, 192)
    assert slots == [(1, 30), (31, 60), (61, 90)]


def test_a_trailing_trap_folds_backward() -> None:
    """A final run with no free frames joins its predecessor's segment."""
    assert resolve_delivery_slots([(1, 192), None], 1, 192) == [(1, 96), (97, 192)]


def test_a_run_trapped_between_units_of_one_merged_shot_folds_with_them() -> None:
    """Unshown units interleaved inside a merged shot partition it with everyone."""
    assert resolve_delivery_slots([(1, 100), None, (1, 100)], 1, 192) == [
        (1, 34),
        (35, 67),
        (68, 100),
    ]


def test_consecutive_free_hosted_runs_advance_together() -> None:
    """Runs on both sides of one anchor each take their own free interval."""
    assert resolve_delivery_slots([None, (49, 96), None], 1, 192) == [
        (1, 48),
        (49, 96),
        (97, 192),
    ]


# ---- the algorithm's refusals


def test_a_segment_regressing_against_unit_order_is_refused() -> None:
    """Narration order is timeline order; a slot never crosses it."""
    with pytest.raises(ValueError, match="overlaps or precedes"):
        resolve_delivery_slots([(100, 192), (1, 50)], 1, 192)


def test_overlapping_host_segments_are_refused() -> None:
    """Shots tile the timeline upstream; overlapping hosts are refused, not assumed away.

    The document flow can never produce this input -- the shot plan's own
    validator enforces the tiling -- but the resolver refuses it rather than
    trusting its caller, because two overlapping hosts would silently yield
    overlapping slots.
    """
    with pytest.raises(ValueError, match="overlaps or precedes"):
        resolve_delivery_slots([(1, 100), (50, 150)], 1, 192)


def test_an_overlap_reached_through_a_fold_is_refused_too() -> None:
    """A trapped run folded backward does not exempt the next host from the rule."""
    with pytest.raises(ValueError, match="overlaps or precedes"):
        resolve_delivery_slots([(10, 20), None, (15, 25)], 1, 192)


def test_a_segment_outside_the_playback_domain_is_refused() -> None:
    """A host that includes the witness frame is not a host."""
    with pytest.raises(ValueError, match="playback domain"):
        resolve_delivery_slots([(145, 193)], 1, 192)


def test_an_inverted_segment_is_refused() -> None:
    """A segment that ends before it starts hosts nothing."""
    with pytest.raises(ValueError, match="playback domain"):
        resolve_delivery_slots([(50, 40)], 1, 192)


def test_a_free_interval_smaller_than_its_run_is_refused() -> None:
    """Three units cannot share two establishing frames; nothing is shrunk."""
    with pytest.raises(ValueError, match="cannot allocate delivery slots for unit_0001"):
        resolve_delivery_slots([None, None, None, (3, 192)], 1, 192)


def test_a_fold_overfilling_its_segment_is_refused() -> None:
    """A one-frame segment cannot host its own unit plus a folded run."""
    with pytest.raises(ValueError, match="cannot allocate delivery slots"):
        resolve_delivery_slots([(1, 1), None, (2, 192)], 1, 192)


def test_the_refusal_names_every_starved_unit() -> None:
    """A refusal that names its units is one somebody can act on."""
    with pytest.raises(ValueError, match=r"unit_0002, unit_0003"):
        resolve_delivery_slots([(1, 190), None, None, (192, 192)], 1, 192)


# ---- the witness clamp on a cited shot, in the full document flow


def _witness_touching_pair() -> Sources:
    """A valid narration/shot pair whose final BEAT shot ends on the boundary.

    Unreachable through the locked Phase 22 planner, whose end hold always
    directs the boundary from an establishing shot -- but perfectly legal under
    the shot plan's own validator, whose tiling runs through the boundary frame
    and whose loop closure is satisfied by first and last beat shots sharing an
    anchor. The narration plan copies the citing shots' spans verbatim, exactly
    as Phase 24 does, so its last unit's copied span ends on frame 193.
    """
    from living_diorama.persistence.json_codec import dumps_canonical
    from living_diorama.persistence.schema.state_hash import sha256_hex

    from .conftest import build_delivery_sources

    _, real_shots = build_delivery_sources(2)
    beat_shots = [
        ("shot_0001", "CAM_SEAL_DETAIL", 1, 60, "beat_0001", "PRIMARY"),
        ("shot_0002", "CAM_SCAR_DETAIL", 61, 120, "beat_0002", "SECONDARY"),
        ("shot_0003", "CAM_SEAL_DETAIL", 121, 193, "beat_0003", "PRIMARY"),
    ]
    shots = {
        "format": real_shots["format"],
        "schema_version": real_shots["schema_version"],
        "source": dict(real_shots["source"]),
        "timeline": dict(real_shots["timeline"]),
        "shots": [
            {
                "camera_anchor_id": anchor,
                "emphasis": emphasis,
                "end_frame": end,
                "kind": "BEAT",
                "reason_code": "BEAT_KIND_RULE",
                "shot_id": shot_id,
                "source_beat_ids": [beat_id],
                "start_frame": start,
            }
            for shot_id, anchor, start, end, beat_id, emphasis in beat_shots
        ],
        "unshown": [],
    }
    units = [
        {
            "beat_id": beat_id,
            "emphasis": emphasis,
            "end_frame": end,
            "fact_id": None,
            "kind": kind,
            "shot_id": shot_id,
            "start_frame": start,
            "subject_ids": [subject],
            "text": text,
            "text_source": "NARRATION_TEMPLATE",
            "unit_id": f"unit_{position:04d}",
            "unshown_reason": None,
            "visibility": "SHOWN",
        }
        for position, (shot_id, _, start, end, beat_id, emphasis), (kind, subject, text) in zip(
            (1, 2, 3),
            beat_shots,
            (
                (
                    "LAW_CHANGE",
                    "law_movement_sharing",
                    'At tick 5, law "law_movement_sharing" changed.',
                ),
                (
                    "WALL_STATE_CHANGE",
                    "wall_boundary_ab",
                    'At tick 9, wall "wall_boundary_ab" changed state.',
                ),
                (
                    "LAW_RESTORATION",
                    "law_movement_sharing",
                    'At tick 22, law "law_movement_sharing" was restored.',
                ),
            ),
            strict=True,
        )
    ]
    narration = {
        "accounting": {"beats_total": 3, "units_shown": 3, "units_unshown": 0},
        "format": "living_diorama_episode_narration_plan",
        "schema_version": 1,
        "source": {
            "current_export_sha256": "0" * 64,
            "episode": real_shots["source"]["episode"],
            "mode": real_shots["source"]["mode"],
            "previous_episode": real_shots["source"]["previous_episode"],
            "shot_plan_sha256": sha256_hex(dumps_canonical(shots, "shot direction plan")),
            "shot_schema_version": 1,
            "story_plan_sha256": "0" * 64,
            "story_schema_version": 1,
        },
        "units": units,
    }
    return narration, shots


def test_a_cited_shot_touching_the_boundary_is_clamped_in_the_slot() -> None:
    """A SHOT_ANCHORED slot stops at the last playback frame, not the shot's end.

    The final beat shot legally spans [121, 193]; its unit's slot must end at
    192, because the witness boundary frame is rendered once as evidence and
    never played back. This is the clamp changing a real slot, not merely
    dropping an uncited establishing span.
    """
    narration, shots = _witness_touching_pair()
    plan = build_episode_narration_delivery_plan_document(narration, shots)
    assert slots_of(plan) == [
        ("unit_0001", "SHOT_ANCHORED", 1, 60),
        ("unit_0002", "SHOT_ANCHORED", 61, 120),
        ("unit_0003", "SHOT_ANCHORED", 121, 192),
    ]


def test_the_clamped_pair_passes_the_full_cross_check() -> None:
    """The hand-built boundary-touching pair verifies end to end, seal included."""
    from living_diorama.narration_delivery import validate_narration_delivery_plan_against_sources

    narration, shots = _witness_touching_pair()
    plan = build_episode_narration_delivery_plan_document(narration, shots)
    assert validate_narration_delivery_plan_against_sources(plan, narration, shots) is plan


# ---- determinism of the whole derivation


@pytest.mark.parametrize("episode", [0, 1, 2])
def test_rebuilding_produces_identical_bytes(episode: int) -> None:
    """Two derivations from freshly rebuilt sources agree byte for byte."""
    from .conftest import build_delivery_sources

    first = build_episode_narration_delivery_plan_bytes(*build_delivery_sources(episode))
    second = build_episode_narration_delivery_plan_bytes(*build_delivery_sources(episode))
    assert first == second
