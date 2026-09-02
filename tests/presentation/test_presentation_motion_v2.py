"""The V2 presentation profile: motion-window holds over the real EP1 plan.

Golden V1 geometry is pinned from the real EP0->1 plan
(``docs/episode_presentation_plan.md`` segments block). The real safe slot spans come from
the EP1 delivery plan table (``docs/episode_narration_delivery_plan.md``):
``unit_0001`` ``[25, 60]``, ``unit_0002`` ``[61, 95]``, ``unit_0003`` ``[96, 144]``, all
three onsets inside the transition phase ``[25, 144]`` of the restated clock
(``start_hold_frames 24``, ``transition_start 25``, ``transition_frames 120``,
``transition_end 145``, ``end_hold_frames 48``).
"""

import pytest

from living_diorama.presentation import build_episode_presentation_plan_document
from living_diorama.presentation.presentation_planner import build_episode_presentation_plan_bytes
from living_diorama.presentation.presentation_schema_v2 import (
    validate_episode_presentation_plan_v2,
)
from living_diorama.presentation.presentation_spec import bounce_window, motion_window_for_hold

# The captured V1 golden geometry of the real EP0->1 presentation plan: seven segments.
GOLDEN_SEGMENTS_EP1 = [
    (1, 24, 1),
    (25, 25, 109),
    (26, 60, 1),
    (61, 61, 326),
    (62, 95, 1),
    (96, 96, 96),
    (97, 192, 1),
]

# The real EP1 delivery slots (onset, slot_end) from the EP1 delivery plan.
SLOTS_EP1 = [(25, 60), (61, 95), (96, 144)]
# The hold dwells (held-position counts) the golden segments pin.
HOLD_LENGTHS_EP1 = [109, 326, 96]


def _plan(sources_ep1, profile: str = "v1"):
    delivery, narration, _shots, realization, _story, _export = sources_ep1
    return build_episode_presentation_plan_document(
        delivery, narration, realization, presentation_profile=profile
    )


def test_v1_default_profile_reproduces_the_captured_golden_geometry(sources_ep1) -> None:
    """The default profile reproduces today's V1 plan byte for byte."""
    plan = _plan(sources_ep1)
    assert [
        (s["semantic_start_frame"], s["semantic_end_frame"], s["dwell_frames"])
        for s in plan["segments"]
    ] == GOLDEN_SEGMENTS_EP1
    assert plan["accounting"] == {
        "presentation_frames_total": 720,
        "segments_total": 7,
        "windows_total": 3,
    }
    assert "motion_windows" not in plan


def test_explicit_v1_profile_is_byte_identical_to_the_default(sources_ep1) -> None:
    """``presentation_profile="v1"`` reproduces the default derivation byte for byte."""
    delivery, narration, _shots, realization, _story, _export = sources_ep1
    default_bytes = build_episode_presentation_plan_bytes(delivery, narration, realization)
    v1_bytes = build_episode_presentation_plan_bytes(
        delivery, narration, realization, presentation_profile="v1"
    )
    assert v1_bytes == default_bytes


def test_v2_plan_carries_one_motion_window_per_hold_with_bounce_sequences(sources_ep1) -> None:
    """Each V2 motion window is a genuine bounce of exactly the required length."""
    plan = _plan(sources_ep1, "v2")
    motion = plan["motion_windows"]
    assert [entry["onset_frame"] for entry in motion] == [25, 61, 96]
    assert [entry["window_id"] for entry in motion] == [
        "window_0001",
        "window_0002",
        "window_0003",
    ]
    for entry, (onset, _slot_end), length in zip(motion, SLOTS_EP1, HOLD_LENGTHS_EP1, strict=True):
        frames = entry["semantic_frames"]
        assert len(frames) == length, "exactly one index per held position"
        assert frames[0] == onset, "entry continuity: the first held position is the onset"
        assert len(set(frames)) > 1, "a genuine bounce is never constant"
        assert all(abs(frames[i] - frames[i - 1]) == 1 for i in range(1, len(frames)))
        assert abs(frames[-1] - onset) <= 1, "exit lands within one frame of the onset"


def test_v2_motion_windows_stay_inside_each_units_own_slot(sources_ep1) -> None:
    """A ping-pong never borrows a frame a different unit's slot owns."""
    plan = _plan(sources_ep1, "v2")
    for entry, (onset, slot_end) in zip(plan["motion_windows"], SLOTS_EP1, strict=True):
        frames = entry["semantic_frames"]
        assert min(frames) == onset, "never drops below the slot's own onset"
        assert max(frames) <= slot_end, "never exceeds the slot's own final frame"


def test_v2_motion_windows_never_cross_an_animation_phase(sources_ep1) -> None:
    """No motion window leaves the animation phase its onset frame belongs to."""
    plan = _plan(sources_ep1, "v2")
    timeline = plan["timeline"]

    def phase(frame: int) -> int:
        if frame < timeline["transition_start"]:
            return 0
        if frame < timeline["transition_end"]:
            return 1
        return 2

    for entry in plan["motion_windows"]:
        onset_phase = phase(entry["onset_frame"])
        assert all(phase(frame) == onset_phase for frame in entry["semantic_frames"])


def test_v2_geometry_is_identical_to_v1(sources_ep1) -> None:
    """V2 changes only the per-position choice inside holds, never the geometry."""
    v1 = _plan(sources_ep1, "v1")
    v2 = _plan(sources_ep1, "v2")
    assert v2["segments"] == v1["segments"]
    assert v2["windows"] == v1["windows"]
    assert v2["accounting"] == v1["accounting"]
    assert v2["timeline"] == v1["timeline"]


def test_v2_plan_validates_under_the_v2_validator(sources_ep1) -> None:
    """The built V2 document passes its own closed validator."""
    plan = _plan(sources_ep1, "v2")
    assert validate_episode_presentation_plan_v2(plan) is plan


def test_v2_derivation_is_deterministic(sources_ep1) -> None:
    """Two V2 derivations produce identical bytes: pure arithmetic, no randomness."""
    delivery, narration, _shots, realization, _story, _export = sources_ep1
    first = build_episode_presentation_plan_bytes(
        delivery, narration, realization, presentation_profile="v2"
    )
    second = build_episode_presentation_plan_bytes(
        delivery, narration, realization, presentation_profile="v2"
    )
    assert second == first


def test_episode_zero_v2_carries_no_motion_windows(sources_ep0) -> None:
    """A plan with no holds carries an empty motion_windows block under V2."""
    plan = _plan(sources_ep0, "v2")
    assert plan["motion_windows"] == []
    assert validate_episode_presentation_plan_v2(plan) is plan


def test_an_unknown_profile_is_refused(sources_ep1) -> None:
    """Only the closed profiles v1, v2, v3 and v4 are derivable; anything else refuses."""
    delivery, narration, _shots, realization, _story, _export = sources_ep1
    with pytest.raises(ValueError, match="presentation_profile"):
        build_episode_presentation_plan_document(
            delivery, narration, realization, presentation_profile="v9"
        )


def test_bounce_window_is_pure_and_has_the_pinned_shape() -> None:
    """The pure bounce is deterministic and has the documented triangle shape."""
    assert bounce_window(25, 52, 8) == (25, 26, 27, 28, 29, 30, 31, 32)
    assert bounce_window(25, 52, 9) == (25, 26, 27, 28, 29, 30, 31, 32, 33)
    assert bounce_window(0, 2, 7) == (0, 1, 2, 1, 0, 1, 2)
    assert bounce_window(0, 2, 7) == bounce_window(0, 2, 7)
    with pytest.raises(ValueError, match="at least two"):
        bounce_window(25, 25, 10)
    with pytest.raises(ValueError, match="positive"):
        bounce_window(25, 52, 0)


def test_motion_window_for_hold_refuses_a_slot_with_no_safe_motion() -> None:
    """A one-frame slot offers no second frame of safe motion and is refused honestly."""
    with pytest.raises(ValueError, match="no second frame of safe motion"):
        motion_window_for_hold(25, 25, 10)


def test_motion_window_for_hold_chooses_the_pinned_real_windows(sources_ep1) -> None:
    """The real EP1 holds bounce over the tuned windows documented in the report."""
    assert motion_window_for_hold(25, 60, 109) == bounce_window(25, 52, 109)
    assert motion_window_for_hold(61, 95, 326) == bounce_window(61, 88, 326)
    assert motion_window_for_hold(96, 144, 96) == bounce_window(96, 144, 96)
