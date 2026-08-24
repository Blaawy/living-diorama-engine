"""The emission contract, the naming rules and the render profile.

The emission tests are the important ones in this file. They are the written
form of the single decision Phase 23 makes, and if they ever stop holding, the
episode's runtime has stopped agreeing with the timeline it was cut against.
"""

import json
from typing import Any

import pytest

from living_diorama.render_execution import render_execution_spec as spec

CANONICAL_TIMELINE = {
    "fps": 24,
    "start_frame": 1,
    "start_hold_frames": 24,
    "transition_frames": 120,
    "end_hold_frames": 48,
    "transition_start": 25,
    "transition_end": 145,
    "end_frame": 193,
}


# ------------------------------------------------------- the emission contract


def test_the_locked_clock_emits_one_hundred_and_ninety_two_playback_frames() -> None:
    """The whole contract in one assertion, on the real canonical clock."""
    emission = spec.derive_emission(CANONICAL_TIMELINE)
    assert emission == {
        "first_frame": 1,
        "final_frame": 192,
        "frame_count": 192,
        "witness_frame": 193,
        "playback_fps": 24,
        "playback_seconds": 8.0,
    }


def test_the_emitted_frames_are_exactly_the_declared_phase_lengths() -> None:
    """Why 192 and not 193: the phases themselves say so.

    Phase 17 declares 24 + 120 + 48 frames. Those counts only add up if each
    phase owns a half-open range, and their sum is the emitted frame count.
    Frame 193 is the boundary the last range closes against.
    """
    emission = spec.derive_emission(CANONICAL_TIMELINE)
    start_hold = range(1, 25)
    transition = range(25, 145)
    end_hold = range(145, 193)
    assert len(start_hold) == CANONICAL_TIMELINE["start_hold_frames"]
    assert len(transition) == CANONICAL_TIMELINE["transition_frames"]
    assert len(end_hold) == CANONICAL_TIMELINE["end_hold_frames"]
    emitted = [*start_hold, *transition, *end_hold]
    assert emitted == list(range(emission["first_frame"], emission["final_frame"] + 1))
    assert len(emitted) == emission["frame_count"] == 192


def test_the_playback_duration_is_the_duration_phase_seventeen_declares() -> None:
    """Phase 17 computes ``(end - start) / fps``; the emission must match it."""
    emission = spec.derive_emission(CANONICAL_TIMELINE)
    phase_seventeen = (
        CANONICAL_TIMELINE["end_frame"] - CANONICAL_TIMELINE["start_frame"]
    ) / CANONICAL_TIMELINE["fps"]
    assert phase_seventeen == 8.0
    assert emission["playback_seconds"] == phase_seventeen


def test_emitting_the_boundary_frame_would_break_the_declared_duration() -> None:
    """The arithmetic that rules out the other candidate contract."""
    emission = spec.derive_emission(CANONICAL_TIMELINE)
    inclusive_count = CANONICAL_TIMELINE["end_frame"] - CANONICAL_TIMELINE["start_frame"] + 1
    assert inclusive_count == 193
    assert inclusive_count / CANONICAL_TIMELINE["fps"] != emission["playback_seconds"]
    assert round(inclusive_count / CANONICAL_TIMELINE["fps"], 6) == 8.041667


def test_the_witness_frame_is_the_frame_after_the_last_playback_frame() -> None:
    """One witness, immediately past the end, never inside the episode."""
    emission = spec.derive_emission(CANONICAL_TIMELINE)
    assert emission["witness_frame"] == emission["final_frame"] + 1
    assert emission["witness_frame"] == CANONICAL_TIMELINE["end_frame"]


def test_a_timeline_that_does_not_close_on_its_own_end_frame_is_refused() -> None:
    """The emission is derived arithmetic; a broken clock cannot be guessed at."""
    broken = {**CANONICAL_TIMELINE, "end_hold_frames": 47}
    with pytest.raises(ValueError, match="do not close on end_frame"):
        spec.derive_emission(broken)


def test_a_boolean_frame_count_is_not_an_integer() -> None:
    """``True`` is not one frame."""
    with pytest.raises(TypeError):
        spec.derive_emission({**CANONICAL_TIMELINE, "fps": True})


def test_a_timeline_with_no_frames_has_no_episode_in_it() -> None:
    """A zero-length episode is refused rather than emitted as nothing."""
    empty = {
        "fps": 24,
        "start_frame": 1,
        "start_hold_frames": 0,
        "transition_frames": 0,
        "end_hold_frames": 0,
        "transition_start": 1,
        "transition_end": 1,
        "end_frame": 1,
    }
    with pytest.raises(ValueError, match="no episode in it"):
        spec.derive_emission(empty)


def test_a_faster_clock_changes_the_duration_and_nothing_else() -> None:
    """The contract is derived, not hard-coded to 24 fps or to 192 frames."""
    emission = spec.derive_emission({**CANONICAL_TIMELINE, "fps": 48})
    assert emission["frame_count"] == 192
    assert emission["playback_seconds"] == 4.0


# ------------------------------------------------------------------- naming


def test_frames_are_named_by_their_semantic_frame_number() -> None:
    """A file name is traceable to the clock without consulting anything else."""
    assert spec.frame_filename(1) == "frame_0001.png"
    assert spec.frame_filename(192) == "frame_0192.png"
    assert spec.frame_filename(193) == "frame_0193.png"


def test_frame_names_sort_in_frame_order() -> None:
    """Zero padding is what makes an ordinary directory listing correct."""
    names = [spec.frame_filename(frame) for frame in (1, 2, 10, 100, 192)]
    assert names == sorted(names)


@pytest.mark.parametrize("frame", [0, -1])
def test_a_frame_outside_the_naming_domain_is_refused(frame: int) -> None:
    """Refused, never clamped into a name that would collide."""
    with pytest.raises(ValueError):
        spec.frame_filename(frame)


def test_a_frame_too_wide_for_the_field_is_refused_not_widened() -> None:
    """Silently widening the field would break sort order for existing renders."""
    with pytest.raises(ValueError, match="reviewed schema change"):
        spec.frame_filename(10000)


def test_a_boolean_is_not_a_frame_number() -> None:
    """``True`` would otherwise name frame 1."""
    with pytest.raises(TypeError):
        spec.frame_filename(True)


# --------------------------------------------------------------- render id


def test_a_transition_and_a_baseline_never_share_a_directory() -> None:
    """Two renders of different episodes cannot collide by name."""
    transition = spec.render_id(mode="transition", episode=1, previous_episode=0)
    baseline = spec.render_id(mode="baseline", episode=0, previous_episode=None)
    assert transition == "episode_0000_to_0001"
    assert baseline == "episode_0000_baseline"
    assert transition != baseline


def test_the_same_leg_always_lands_in_the_same_place() -> None:
    """A re-run resumes its own render instead of scattering copies."""
    first = spec.render_id(mode="transition", episode=2, previous_episode=1)
    second = spec.render_id(mode="transition", episode=2, previous_episode=1)
    assert first == second == "episode_0001_to_0002"


def test_a_baseline_that_names_a_previous_episode_is_refused() -> None:
    """A baseline has no previous episode; claiming one is incoherent."""
    with pytest.raises(ValueError, match="no previous episode"):
        spec.render_id(mode="baseline", episode=1, previous_episode=0)


def test_a_transition_that_skips_an_episode_is_refused() -> None:
    """Phase 23 renders the transition Phase 22 directed and derives no other."""
    with pytest.raises(ValueError, match="does not directly follow"):
        spec.render_id(mode="transition", episode=3, previous_episode=1)


def test_an_unknown_mode_is_refused() -> None:
    """Refused, not defaulted to a shape that happens to parse."""
    with pytest.raises(ValueError, match="unknown episode mode"):
        spec.render_id(mode="montage", episode=1, previous_episode=0)


# ------------------------------------------------------------ render profile


def test_the_profile_digest_is_stable_across_calls() -> None:
    """A digest that moved between calls would make every binding meaningless."""
    assert spec.render_profile_sha256() == spec.render_profile_sha256()


def test_the_profile_digest_changes_when_any_value_changes() -> None:
    """The pin is what stops a re-tuned render being mistaken for this one."""
    document = spec.render_profile_document()
    document["owned"]["cycles_samples"] = 1024
    changed = (
        json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        + b"\n"
    )
    import hashlib

    assert hashlib.sha256(changed).hexdigest() != spec.render_profile_sha256()


def test_the_profile_document_is_a_copy_not_the_source_of_truth() -> None:
    """A caller embedding the profile in a plan cannot mutate the real one."""
    first = spec.render_profile_document()
    first["owned"]["resolution_x"] = 42
    assert spec.render_profile_document()["owned"]["resolution_x"] == 1280


def test_the_profile_pins_the_sampling_seed_to_narrow_the_noise_band() -> None:
    """Pinning the seed narrows the band; it does not make two renders agree.

    Cycles on a GPU stays stochastic with the seed fixed, so this asserts only
    what the profile actually does. What the narrowed band buys is measured in
    the real-Blender suite, not claimed here.
    """
    owned: dict[str, Any] = spec.render_profile_document()["owned"]
    assert owned["cycles_seed"] == 0
    assert owned["cycles_use_animated_seed"] is False


def test_the_profile_disables_motion_blur() -> None:
    """Every claim this phase makes is per-frame; a blurred frame is not."""
    assert spec.render_profile_document()["owned"]["use_motion_blur"] is False


def test_the_profile_verifies_the_colour_management_it_refuses_to_set() -> None:
    """Colour belongs to the Phase 15 world build; Phase 23 checks and never writes."""
    verified: dict[str, Any] = spec.render_profile_document()["verified"]
    assert verified["view_transform"] == "AgX"
    assert verified["look"] == "AgX - Medium High Contrast"
    assert verified["fps"] == 24
    assert verified["fps_base"] == 1.0


def test_the_owned_and_verified_halves_are_disjoint() -> None:
    """A setting is either Phase 23's to set or someone else's to keep. Never both."""
    document = spec.render_profile_document()
    assert not set(document["owned"]) & set(document["verified"])
