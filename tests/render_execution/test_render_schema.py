"""Attacks on the Episode Render Plan contract.

Each test hands the validator a document that is wrong in exactly one way and
requires a refusal. A contract nobody has seen refuse anything is a contract
nobody has tested.
"""

import copy
from typing import Any

import pytest

from living_diorama.persistence.json_codec import loads_canonical
from living_diorama.render_execution import validate_episode_render_plan


def test_the_canonical_plan_validates(render_plan: dict[str, Any]) -> None:
    """The control: what the planner emits is what the contract describes."""
    assert validate_episode_render_plan(copy.deepcopy(render_plan)) is not None


# ------------------------------------------------------------ document shape


@pytest.mark.parametrize("value", [None, [], "plan", 7, True])
def test_a_document_that_is_not_an_object_is_refused(value: object) -> None:
    """A list of frames is not a plan."""
    with pytest.raises(TypeError):
        validate_episode_render_plan(value)


def test_a_missing_top_level_key_is_refused(render_plan: dict[str, Any]) -> None:
    """An incomplete plan is refused, never completed with a default."""
    broken = copy.deepcopy(render_plan)
    del broken["emission"]
    with pytest.raises(ValueError, match="missing"):
        validate_episode_render_plan(broken)


def test_an_extra_top_level_key_is_refused(render_plan: dict[str, Any]) -> None:
    """An unexpected key means something else wrote this document."""
    broken = copy.deepcopy(render_plan)
    broken["notes"] = "rendered on the good machine"
    with pytest.raises(ValueError):
        validate_episode_render_plan(broken)


def test_a_wrong_format_tag_is_refused(render_plan: dict[str, Any]) -> None:
    """A shot plan is not a render plan, however similar the keys look."""
    broken = copy.deepcopy(render_plan)
    broken["format"] = "living_diorama_shot_direction_plan"
    with pytest.raises(ValueError, match="declares format"):
        validate_episode_render_plan(broken)


def test_an_unsupported_schema_version_is_refused(render_plan: dict[str, Any]) -> None:
    """A future plan is refused by this build rather than half-understood."""
    broken = copy.deepcopy(render_plan)
    broken["schema_version"] = 2
    with pytest.raises(ValueError, match="schema version"):
        validate_episode_render_plan(broken)


def test_a_repeated_json_key_never_reaches_the_validator() -> None:
    """The canonical decoder refuses a duplicate key before shape is even checked."""
    with pytest.raises(ValueError):
        loads_canonical(b'{"format": "a", "format": "b"}\n', "render plan")


# ------------------------------------------------------------ source binding


def test_a_wrong_render_profile_digest_is_refused(render_plan: dict[str, Any]) -> None:
    """A render carries the profile it was made with and is never reinterpreted."""
    broken = copy.deepcopy(render_plan)
    broken["source"]["render_profile_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="render profile"):
        validate_episode_render_plan(broken)


def test_an_edited_profile_body_is_refused(render_plan: dict[str, Any]) -> None:
    """Editing the profile in place, digest untouched, is the obvious forgery."""
    broken = copy.deepcopy(render_plan)
    broken["profile"]["owned"]["cycles_samples"] = 2048
    with pytest.raises(ValueError, match="but this build renders under"):
        validate_episode_render_plan(broken)


def test_a_profile_value_that_only_deep_equals_is_refused(render_plan: dict[str, Any]) -> None:
    """``1 == 1.0`` in Python, but not in bytes -- and bytes are what is pinned.

    Comparing the profile document with ``==`` accepted an integer written where
    the approved profile holds a float, because Python calls those equal. The
    Blender executor has always compared canonical digests and refused it, so
    the engine was the lenient half of a pair that is supposed to be identical.
    """
    broken = copy.deepcopy(render_plan)
    assert broken["profile"]["owned"]["pixel_aspect_x"] == 1.0
    broken["profile"]["owned"]["pixel_aspect_x"] = 1
    with pytest.raises(ValueError, match="but this build renders under"):
        validate_episode_render_plan(broken)


def test_a_malformed_digest_is_refused(render_plan: dict[str, Any]) -> None:
    """Sixty-four lowercase hexadecimal characters, or nothing."""
    broken = copy.deepcopy(render_plan)
    broken["source"]["shot_plan_sha256"] = "NOTAHASH"
    with pytest.raises(ValueError):
        validate_episode_render_plan(broken)


def test_an_unsupported_shot_plan_schema_version_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """This build renders the direction contract it understands."""
    broken = copy.deepcopy(render_plan)
    broken["source"]["shot_plan_schema_version"] = 2
    with pytest.raises(ValueError, match="shot plan schema version"):
        validate_episode_render_plan(broken)


def test_a_foreign_shot_plan_format_is_refused(render_plan: dict[str, Any]) -> None:
    """Phase 23 renders Phase 22's format and refuses to guess at another."""
    broken = copy.deepcopy(render_plan)
    broken["source"]["shot_plan_format"] = "someone_elses_direction"
    with pytest.raises(ValueError, match="shot plan format"):
        validate_episode_render_plan(broken)


def test_an_episode_that_does_not_follow_its_predecessor_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """A render plan describes one transition, not a jump."""
    broken = copy.deepcopy(render_plan)
    broken["source"]["episode"] = 5
    with pytest.raises(ValueError):
        validate_episode_render_plan(broken)


def test_an_unknown_mode_is_refused(render_plan: dict[str, Any]) -> None:
    """Two shapes exist; a third is refused."""
    broken = copy.deepcopy(render_plan)
    broken["source"]["mode"] = "montage"
    with pytest.raises(ValueError, match="mode"):
        validate_episode_render_plan(broken)


# ----------------------------------------------------------- timeline and emission


def test_a_clock_that_disagrees_with_itself_is_refused(render_plan: dict[str, Any]) -> None:
    """The copied timeline is re-checked against its own arithmetic."""
    broken = copy.deepcopy(render_plan)
    broken["timeline"]["transition_end"] = 150
    with pytest.raises(ValueError, match="disagrees with its own phases"):
        validate_episode_render_plan(broken)


def test_an_emission_that_claims_more_frames_than_the_clock_allows_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """The 193-frame contract, refused where it would actually matter."""
    broken = copy.deepcopy(render_plan)
    broken["emission"]["frame_count"] = 193
    broken["emission"]["final_frame"] = 193
    with pytest.raises(ValueError, match="implies"):
        validate_episode_render_plan(broken)


def test_an_emission_claiming_the_wrong_duration_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """A plan cannot declare a runtime its own frame count does not produce."""
    broken = copy.deepcopy(render_plan)
    broken["emission"]["playback_seconds"] = 8.041667
    with pytest.raises(ValueError):
        validate_episode_render_plan(broken)


def test_an_integer_duration_is_not_a_float(render_plan: dict[str, Any]) -> None:
    """Exact types: 8 seconds and 8.0 seconds are stored differently."""
    broken = copy.deepcopy(render_plan)
    broken["emission"]["playback_seconds"] = 8
    with pytest.raises(TypeError):
        validate_episode_render_plan(broken)


# ------------------------------------------------------------------- frames


def test_a_missing_interior_frame_is_refused(render_plan: dict[str, Any]) -> None:
    """The failure a file count would never catch."""
    broken = copy.deepcopy(render_plan)
    del broken["frames"][86]
    with pytest.raises(ValueError, match="accounts for"):
        validate_episode_render_plan(broken)


def test_a_duplicated_frame_is_refused(render_plan: dict[str, Any]) -> None:
    """Two records for one frame would make the count right and the render wrong."""
    broken = copy.deepcopy(render_plan)
    broken["frames"][5] = copy.deepcopy(broken["frames"][4])
    with pytest.raises(ValueError, match="expects"):
        validate_episode_render_plan(broken)


def test_frames_out_of_order_are_refused(render_plan: dict[str, Any]) -> None:
    """Order is part of the contract, not a presentation detail."""
    broken = copy.deepcopy(render_plan)
    broken["frames"][10], broken["frames"][11] = broken["frames"][11], broken["frames"][10]
    with pytest.raises(ValueError, match="expects"):
        validate_episode_render_plan(broken)


def test_a_witness_role_on_a_playback_frame_is_refused(render_plan: dict[str, Any]) -> None:
    """Only the boundary frame is the witness."""
    broken = copy.deepcopy(render_plan)
    broken["frames"][0]["role"] = "witness"
    with pytest.raises(ValueError, match="playback frame"):
        validate_episode_render_plan(broken)


def test_a_playback_role_on_the_witness_frame_is_refused(render_plan: dict[str, Any]) -> None:
    """Promoting the witness into the episode would change the runtime."""
    broken = copy.deepcopy(render_plan)
    broken["frames"][-1]["role"] = "playback"
    with pytest.raises(ValueError, match="witness frame"):
        validate_episode_render_plan(broken)


def test_an_unknown_role_is_refused(render_plan: dict[str, Any]) -> None:
    """Two roles exist."""
    broken = copy.deepcopy(render_plan)
    broken["frames"][0]["role"] = "bonus"
    with pytest.raises(ValueError, match="role"):
        validate_episode_render_plan(broken)


def test_a_non_canonical_file_name_is_refused(render_plan: dict[str, Any]) -> None:
    """The naming contract is not negotiable per frame."""
    broken = copy.deepcopy(render_plan)
    broken["frames"][0]["file"] = "frame_1.png"
    with pytest.raises(ValueError, match="naming contract"):
        validate_episode_render_plan(broken)


@pytest.mark.parametrize(
    "name",
    [
        "../frame_0001.png",
        "sub/frame_0001.png",
        "sub\\frame_0001.png",
        "C:frame_0001.png",
        ".frame_0001.png",
    ],
)
def test_a_file_name_carrying_path_structure_is_refused(
    render_plan: dict[str, Any], name: str
) -> None:
    """A frame name is joined onto a directory this phase owns; it may not escape."""
    broken = copy.deepcopy(render_plan)
    broken["frames"][0]["file"] = name
    with pytest.raises(ValueError):
        validate_episode_render_plan(broken)


def test_an_unapproved_camera_anchor_is_refused(render_plan: dict[str, Any]) -> None:
    """Phase 23 knows only the cameras Phase 22 may select."""
    broken = copy.deepcopy(render_plan)
    broken["frames"][0]["camera_anchor_id"] = "CAM_INVENTED"
    with pytest.raises(ValueError, match="approved anchor"):
        validate_episode_render_plan(broken)


def test_an_empty_frame_list_is_refused(render_plan: dict[str, Any]) -> None:
    """A render with no frames is not a render."""
    broken = copy.deepcopy(render_plan)
    broken["frames"] = []
    with pytest.raises(ValueError, match="no frames"):
        validate_episode_render_plan(broken)


# -------------------------------------------------------------- destination


def test_a_destination_that_disagrees_with_the_episode_identity_is_refused(
    render_plan: dict[str, Any],
) -> None:
    """A directory named for another episode would hide a mixed render."""
    broken = copy.deepcopy(render_plan)
    broken["destination"]["render_id"] = "episode_0007_to_0008"
    with pytest.raises(ValueError, match="derives"):
        validate_episode_render_plan(broken)


@pytest.mark.parametrize("value", ["../escape", "nested/dir", "C:", ".hidden"])
def test_a_destination_that_is_not_one_ordinary_directory_name_is_refused(
    render_plan: dict[str, Any], value: str
) -> None:
    """Path traversal is refused at the contract, not sanitised at use."""
    broken = copy.deepcopy(render_plan)
    broken["destination"]["frames_dir"] = value
    with pytest.raises(ValueError):
        validate_episode_render_plan(broken)
