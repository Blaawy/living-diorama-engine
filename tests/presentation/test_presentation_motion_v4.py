"""The V4 presentation profile: strict 1:1 forward presentation, zero holds.

V4 is the no-stretch profile: ``window_frames == slot_length``,
``hold_frames == 0``, ``dwell_frames == 1`` for every segment, and no
``motion_windows`` key anywhere. Presentation frame N shows rendered frame N,
so ``presentation_frames_total`` equals the rendered playback frame count.
When a unit's realized narration cannot fit its own slot, V4 refuses loudly
instead of holding, bouncing or freezing.

Of the three canonical episodes only episode 0 fits: its one unit's
whole-domain slot ``[1, 192]`` comfortably contains its realized sentence
under the calibrated affine speech estimate (a 24-frame fixed overhead plus
6 frames per word). Episodes 1 and 2 overflow (their slots are far shorter
than their realized narration), which is exactly the refusal this suite pins.
"""

import itertools

import pytest

from living_diorama.media_assembly.media_assembly_mapping import (
    presentation_frame_map,
    presentation_motion_metrics,
)
from living_diorama.presentation import build_episode_presentation_plan_document
from living_diorama.presentation.presentation_cross_check import (
    validate_episode_presentation_plan_against_sources,
)
from living_diorama.presentation.presentation_planner import (
    V4_FRAMES_PER_WORD,
    V4_OVERHEAD_FRAMES,
    build_episode_presentation_plan_bytes,
)
from living_diorama.presentation.presentation_schema_v1 import (
    validate_episode_presentation_plan,
)
from living_diorama.presentation.presentation_schema_v2 import (
    validate_episode_presentation_plan_v2,
)

from .test_presentation_motion_v3 import (
    REAL_SPEECH_FRAMES_EP1,
    REALIZED_TEXT_EP1,
    SLOTS_EP1,
)


def _v4_required(words: int) -> int:
    """The reviewed v4 speech allowance: fixed overhead plus per-word slope."""
    return V4_OVERHEAD_FRAMES + words * V4_FRAMES_PER_WORD


# The real EP1 overflow, computed the same way the planner computes it:
# unit_0001's realized sentence is 9 words, its slot is [25, 60] (36 frames),
# and the reviewed affine model requires 24 + 6*9 = 78 frames.
EP1_UNIT_ONE_REQUIRED = _v4_required(len(REALIZED_TEXT_EP1[0].split()))
EP1_UNIT_ONE_SLOT_FRAMES = SLOTS_EP1[0][1] - SLOTS_EP1[0][0] + 1
EP1_UNIT_ONE_SHORTFALL = EP1_UNIT_ONE_REQUIRED - EP1_UNIT_ONE_SLOT_FRAMES

# The three real EP1 points the affine model was calibrated on: the
# commander-measured word counts paired with the real measured Kokoro speech
# lengths in presentation frame-equivalents (the speech lengths are the same
# Director-provided measurements pinned in the v3 suite).
V4_MEASURED_POINTS = tuple(zip((4, 15, 10), REAL_SPEECH_FRAMES_EP1, strict=True))


def _plan(sources_ep0, profile: str = "v4"):
    delivery, narration, _shots, realization, _story, _export = sources_ep0
    return build_episode_presentation_plan_document(
        delivery, narration, realization, presentation_profile=profile
    )


def test_v4_never_emits_motion_windows_on_the_real_ep0_plan(sources_ep0) -> None:
    """A v4 plan carries no ``motion_windows`` key at all, so it is plain V1."""
    plan = _plan(sources_ep0)
    assert "motion_windows" not in plan
    assert validate_episode_presentation_plan(plan) is plan
    # The V2 validator delegates plans without motion_windows to the unchanged
    # V1 path, so v4 never needs -- and never hits -- the motion-window branch.
    assert validate_episode_presentation_plan_v2(plan) is plan


def test_v4_every_segment_dwells_exactly_one_frame_exhaustively(sources_ep0) -> None:
    """Exhaustively over every segment: no segment of a real v4 plan ever holds."""
    plan = _plan(sources_ep0)
    dwells = [segment["dwell_frames"] for segment in plan["segments"]]
    assert dwells, "a real v4 plan carries at least one segment"
    assert all(dwell == 1 for dwell in dwells)
    assert set(dwells) == {1}


def test_v4_presentation_frame_map_is_the_exact_identity_sequence(sources_ep0) -> None:
    """The Director's law, proven mechanically on the whole real v4 plan.

    This is the single most important assertion in the V4 suite: the full
    ``presentation_frame_map`` is asserted to equal the exact identity
    sequence ``1..N``, the direction-reversal count is 0, and the longest run
    of any repeated value is 1 -- the anti-freeze assertion. No hold, no
    reverse, no repeat anywhere.
    """
    plan = _plan(sources_ep0)
    n = plan["accounting"]["presentation_frames_total"]
    mapping = presentation_frame_map(plan)
    assert tuple(mapping) == tuple(range(1, n + 1))
    reversals = sum(1 for a, b in zip(mapping, mapping[1:], strict=False) if b < a)
    assert reversals == 0  # direction_reversal_count
    longest_repeated_run = max(len(list(group)) for _value, group in itertools.groupby(mapping))
    assert longest_repeated_run == 1  # the anti-freeze assertion
    metrics = presentation_motion_metrics(plan)
    assert metrics["frozen_frame_count"] == 0
    assert metrics["longest_freeze_run_frames"] == 0
    assert metrics["distinct_png_count_used"] == n
    assert metrics["total_frames"] == n


def test_v4_presentation_frames_total_equals_the_playback_frame_count(sources_ep0) -> None:
    """N presentation frames for N rendered playback frames: no stretching at all."""
    plan = _plan(sources_ep0)
    timeline = plan["timeline"]
    playback_frames = timeline["end_frame"] - timeline["start_frame"]  # witness excluded
    assert plan["accounting"]["presentation_frames_total"] == playback_frames
    assert plan["accounting"]["presentation_frames_total"] == 192


def test_v4_ep0_geometry_is_the_identity_geometry(sources_ep0) -> None:
    """The real EP0 v4 plan: one dwell-1 segment and one slot-sized window."""
    plan = _plan(sources_ep0)
    assert plan["accounting"] == {
        "presentation_frames_total": 192,
        "segments_total": 1,
        "windows_total": 1,
    }
    assert plan["segments"] == [
        {
            "dwell_frames": 1,
            "presentation_end_frame": 192,
            "presentation_start_frame": 1,
            "segment_id": "segment_0001",
            "semantic_end_frame": 192,
            "semantic_start_frame": 1,
        }
    ]
    (window,) = plan["windows"]
    assert (window["presentation_start_frame"], window["presentation_end_frame"]) == (1, 192)


def test_v4_refuses_when_a_units_narration_exceeds_its_slot(sources_ep1) -> None:
    """The real EP1 overflow: the message names the unit, both frame counts and the shortfall.

    EP1's rendered world (192 playback frames) is far shorter than its real
    narration, so v4 must refuse loudly rather than stretch, hold or freeze.
    The quantities compared are the real realized sentence at the calibrated
    affine speech model (a 24-frame fixed overhead plus 6 frames per word) and
    the real delivery slot -- the best real quantities this layer may read
    (measured voice duration exists only downstream).
    """
    delivery, narration, _shots, realization, _story, _export = sources_ep1
    with pytest.raises(ValueError) as excinfo:
        build_episode_presentation_plan_document(
            delivery, narration, realization, presentation_profile="v4"
        )
    message = str(excinfo.value)
    assert "unit_0001" in message
    assert str(EP1_UNIT_ONE_REQUIRED) in message
    assert str(EP1_UNIT_ONE_SLOT_FRAMES) in message
    assert str(EP1_UNIT_ONE_SHORTFALL) in message
    assert EP1_UNIT_ONE_REQUIRED == 78
    assert EP1_UNIT_ONE_SLOT_FRAMES == 36
    assert EP1_UNIT_ONE_SHORTFALL == 42


def test_v4_affine_estimate_matches_the_reviewed_model_on_the_real_ep1_word_counts() -> None:
    """The reviewed model's exact outputs for the three real EP1 word counts."""
    assert _v4_required(4) == 48
    assert _v4_required(15) == 114
    assert _v4_required(10) == 84


def test_v4_affine_estimate_over_shoots_every_real_measured_speech_length() -> None:
    """The gate's load-bearing property: the allowance strictly exceeds real speech.

    The refusal compares this allowance against the delivery slot, so an
    under-estimate would admit a unit whose real speech outruns its window.
    Every calibrated point must therefore over-estimate the real measured
    Kokoro length (44.4 / 111.0 / 81.6 presentation frame-equivalents).
    """
    assert all(_v4_required(words) > real_frames for words, real_frames in V4_MEASURED_POINTS)


def test_v4_also_refuses_episode_two(sources_ep2) -> None:
    """Episode 2's leading fact unit (204 frames needed, 23-frame slot) refuses too."""
    delivery, narration, _shots, realization, _story, _export = sources_ep2
    with pytest.raises(ValueError, match="unit_0001"):
        build_episode_presentation_plan_document(
            delivery, narration, realization, presentation_profile="v4"
        )


def test_v4_derivation_is_deterministic(sources_ep0) -> None:
    """Two v4 derivations produce identical bytes: pure arithmetic, no randomness."""
    delivery, narration, _shots, realization, _story, _export = sources_ep0
    first = build_episode_presentation_plan_bytes(
        delivery, narration, realization, presentation_profile="v4"
    )
    second = build_episode_presentation_plan_bytes(
        delivery, narration, realization, presentation_profile="v4"
    )
    assert second == first


def test_v4_plan_is_source_verified_under_the_plain_v1_cross_check_path(sources_ep0) -> None:
    """The cross-check's ``== "v2"`` branch is never hit; v4 falls through to V1.

    The re-derivation seal inside the cross-check rebuilds the plan under the
    same profile and demands byte equality, so this end-to-end verification
    proves v4 plans are first-class without any V2 machinery.
    """
    delivery, narration, shots, realization, story, export = sources_ep0
    plan = _plan(sources_ep0)
    assert (
        validate_episode_presentation_plan_against_sources(
            plan,
            delivery,
            narration,
            shots,
            realization,
            story,
            export,
            presentation_profile="v4",
        )
        is plan
    )


def test_v1_v2_v3_remain_derivable_over_the_canonical_episodes(sources_ep1) -> None:
    """The historical profiles still build with their golden totals; v4 is additive only.

    The byte-identity and golden-geometry guarantees for v1, v2 and v3 live in
    their own suites; this local pin just confirms the new closed profile set
    leaves the historical derivations reachable and unchanged in total.
    """
    delivery, narration, _shots, realization, _story, _export = sources_ep1
    v1 = build_episode_presentation_plan_document(delivery, narration, realization)
    v2 = build_episode_presentation_plan_document(
        delivery, narration, realization, presentation_profile="v2"
    )
    v3 = build_episode_presentation_plan_document(
        delivery, narration, realization, presentation_profile="v3"
    )
    assert v1["accounting"]["presentation_frames_total"] == 720
    assert v2["accounting"]["presentation_frames_total"] == 720
    assert v3["accounting"]["presentation_frames_total"] == 714
