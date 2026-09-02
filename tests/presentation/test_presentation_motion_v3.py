"""The V3 presentation profile: frozen, content-sized holds over the real EP1 plan.

V3 is the Director's no-reverse-time profile. It never emits ``motion_windows``
at all -- every hold is the unchanged V1 frozen repeat of the slot's own onset
frame, a constant-value run that is trivially non-decreasing -- and each
window's floor is sized from the unit's own realized text at a commander-chosen
2.0 words/sec (12 frames per word) plus a fixed 0.75 s comprehension buffer (18
frames), replacing the fixed per-text-source floors.

The real EP1 numbers this suite pins: delivery slots ``[25, 60]`` (36 frames),
``[61, 95]`` (35 frames), ``[96, 144]`` (49 frames); realized texts with 9, 17
and 13 whitespace tokens; and the Director-provided real measured Kokoro speech
lengths of 44400, 111000 and 81600 samples, i.e. 44.4, 111.0 and 81.6
presentation frame-equivalents at 1000 samples/frame.
"""

import math

from living_diorama.media_assembly.media_assembly_mapping import presentation_frame_map
from living_diorama.presentation import build_episode_presentation_plan_document
from living_diorama.presentation.presentation_planner import (
    V3_COMPREHENSION_BUFFER_FRAMES,
    V3_FRAMES_PER_WORD,
    build_episode_presentation_plan_bytes,
)
from living_diorama.presentation.presentation_schema_v1 import (
    validate_episode_presentation_plan,
)

# Real EP1 delivery slots (onset, slot_end) from the EP1 delivery plan.
SLOTS_EP1 = [(25, 60), (61, 95), (96, 144)]
# The real EP1 realized sentences (locked golden literals from the realization suite).
REALIZED_TEXT_EP1 = [
    "At tick 7, the movement resource sharing law changed.",
    "At tick 9, a permanent wall was built on the boundary between District A and District B.",
    "At tick 9, the wall between District A and District B changed state.",
]
# The real whitespace-token counts of those sentences.
WORD_COUNTS_EP1 = [len(text.split()) for text in REALIZED_TEXT_EP1]
# Real measured Kokoro speech lengths in presentation frame-equivalents
# (samples / 1000): 44400 -> 44.4, 111000 -> 111.0, 81600 -> 81.6.
# Director-provided real measurements; they appear nowhere in this repo
# (voice tests synthesize speech), so they are pinned here as given.
REAL_SPEECH_FRAMES_EP1 = [44.4, 111.0, 81.6]
FPS = 24


def _plan(sources_ep1, profile: str = "v1"):
    delivery, narration, _shots, realization, _story, _export = sources_ep1
    return build_episode_presentation_plan_document(
        delivery, narration, realization, presentation_profile=profile
    )


def _expected_window(slot_length: int, realized_text: str) -> int:
    """The v3 window floor exactly as the planner derives it."""
    word_count = len(realized_text.split())
    speech_estimate_frames = math.ceil(word_count * V3_FRAMES_PER_WORD)
    floor = slot_length + speech_estimate_frames + V3_COMPREHENSION_BUFFER_FRAMES
    return max(slot_length, floor)


def test_v3_never_emits_motion_windows_on_the_real_ep1_plan(sources_ep1) -> None:
    """A v3 plan carries no ``motion_windows`` key, so it validates as plain V1."""
    plan = _plan(sources_ep1, "v3")
    assert "motion_windows" not in plan
    assert validate_episode_presentation_plan(plan) is plan


def test_v3_window_floors_are_content_sized_from_the_real_realized_text(
    sources_ep1,
) -> None:
    """Each v3 window is the slot length plus speech estimate plus buffer."""
    plan = _plan(sources_ep1, "v3")
    assert WORD_COUNTS_EP1 == [9, 17, 13]
    for window, (onset, slot_end), text in zip(
        plan["windows"], SLOTS_EP1, REALIZED_TEXT_EP1, strict=True
    ):
        slot_length = slot_end - onset + 1
        expected = _expected_window(slot_length, text)
        assert window["presentation_end_frame"] - window["presentation_start_frame"] + 1 == expected


def test_v3_presentation_frame_map_is_monotonically_non_decreasing_across_the_whole_plan(
    sources_ep1,
) -> None:
    """The Director's law, proven mechanically: mapped source frames never decrease.

    This is the single most important assertion in the V3 suite: the full
    ``presentation_frame_map`` over the whole real EP1 v3 plan is compared
    pair by adjacent pair, exhaustively -- not spot-checked.
    """
    plan = _plan(sources_ep1, "v3")
    mapping = presentation_frame_map(plan)
    assert len(mapping) == plan["accounting"]["presentation_frames_total"]
    assert all(a <= b for a, b in zip(mapping, mapping[1:], strict=False))


def test_v3_every_hold_is_the_frozen_onset_repeat(sources_ep1) -> None:
    """V3 reuses the V1 frozen hold: each held segment repeats its onset only."""
    plan = _plan(sources_ep1, "v3")
    mapping = presentation_frame_map(plan)
    for segment in plan["segments"]:
        dwell = segment["dwell_frames"]
        if dwell == 1:
            continue
        start = segment["presentation_start_frame"]
        end = segment["presentation_end_frame"]
        onset = segment["semantic_start_frame"]
        assert mapping[start - 1 : end] == (onset,) * dwell


def test_v3_real_per_unit_hold_vs_speech_margins(sources_ep1) -> None:
    """The real EP1 margins, as literal assertions.

    A future constant change that makes any margin negative fails loudly,
    and any drift in the hold arithmetic fails here too.

    margin(unit) = (window - slot_length) - real_speech_frame_equivalents,
    i.e. the hold-only portion minus the real measured speech it must contain.
    """
    plan = _plan(sources_ep1, "v3")
    holds: list[int] = []
    for window, (onset, slot_end) in zip(plan["windows"], SLOTS_EP1, strict=True):
        slot_length = slot_end - onset + 1
        window_length = window["presentation_end_frame"] - window["presentation_start_frame"] + 1
        holds.append(window_length - slot_length)
    assert holds == [126, 222, 174]
    margins = [hold - speech for hold, speech in zip(holds, REAL_SPEECH_FRAMES_EP1, strict=True)]
    assert margins == [81.6, 111.0, 92.4]
    assert [margin / FPS for margin in margins] == [3.4, 4.625, 3.85]
    assert all(margin > 0 for margin in margins), "every hold must exceed its real speech"


def test_v3_real_ep1_total_presentation_frames(sources_ep1) -> None:
    """The real resulting total for the EP1 plan under v3, in frames and seconds."""
    plan = _plan(sources_ep1, "v3")
    assert plan["accounting"]["presentation_frames_total"] == 714
    assert plan["accounting"]["presentation_frames_total"] / FPS == 29.75


def test_v3_derivation_is_deterministic(sources_ep1) -> None:
    """Two v3 derivations produce identical bytes: pure arithmetic, no randomness."""
    delivery, narration, _shots, realization, _story, _export = sources_ep1
    first = build_episode_presentation_plan_bytes(
        delivery, narration, realization, presentation_profile="v3"
    )
    second = build_episode_presentation_plan_bytes(
        delivery, narration, realization, presentation_profile="v3"
    )
    assert second == first
