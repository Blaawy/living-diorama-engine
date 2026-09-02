"""The command-line entry point is a thin shell over the contract.

It reads canonical story bytes and the exact Motion & Time Spec bytes, hands
them to the cinematic layer, cross-validates what came back against both
inputs, and writes canonical bytes. Every refusal it reports comes from the
contract, not from the shell.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from living_diorama.cinematic import (
    build_shot_direction_plan_bytes,
    build_shot_direction_plan_v2_bytes,
    validate_shot_direction_plan_against_story,
)
from living_diorama.cinematic.camera_movement_planner import plan_camera_movements
from living_diorama.cinematic.cinematic_schema_v1 import validate_shot_direction_plan
from living_diorama.cinematic.cinematic_schema_v2 import validate_shot_direction_plan_v2
from living_diorama.cinematic.shot_planner import build_shot_direction_plan_document
from living_diorama.cli import build_shot_plan
from living_diorama.persistence.json_codec import dumps_canonical


@pytest.fixture
def workspace(tmp_path: Path, story_ep0_to_ep1: dict[str, Any], motion_time: bytes) -> Path:
    """A scratch directory holding a canonical story plan and the real clock."""
    (tmp_path / "story.json").write_bytes(dumps_canonical(story_ep0_to_ep1, "story"))
    (tmp_path / "motion_time.json").write_bytes(motion_time)
    return tmp_path


def _run(workspace: Path, output: str = "shots.json", **overrides: str) -> int:
    args = [
        "--story",
        str(overrides.get("story", workspace / "story.json")),
        "--motion-time",
        str(overrides.get("motion_time", workspace / "motion_time.json")),
        "--output",
        str(workspace / output),
    ]
    if "camera_profile" in overrides:
        args += ["--camera-profile", overrides["camera_profile"]]
    return build_shot_plan.main(args)


def test_it_writes_a_shot_plan(workspace: Path) -> None:
    """It writes a shot plan."""
    assert _run(workspace) == 0
    document = json.loads((workspace / "shots.json").read_text(encoding="utf-8"))
    assert document["source"]["mode"] == "transition"
    assert len(document["shots"]) == 4


def test_the_written_bytes_are_the_canonical_bytes(
    workspace: Path, story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """The written bytes are the canonical bytes."""
    _run(workspace)
    expected = build_shot_direction_plan_bytes(story_ep0_to_ep1, motion_time)
    assert (workspace / "shots.json").read_bytes() == expected


def test_it_binds_the_story_file_it_actually_read(workspace: Path) -> None:
    """Because the input must be canonical, the digest is also the file digest."""
    import hashlib

    _run(workspace)
    document = json.loads((workspace / "shots.json").read_text(encoding="utf-8"))
    on_disk = hashlib.sha256((workspace / "story.json").read_bytes()).hexdigest()
    assert document["source"]["story_plan_sha256"] == on_disk


def test_it_binds_the_motion_time_file_it_actually_read(workspace: Path) -> None:
    """The clock digest is the digest of the file on disk, byte for byte."""
    import hashlib

    _run(workspace)
    document = json.loads((workspace / "shots.json").read_text(encoding="utf-8"))
    on_disk = hashlib.sha256((workspace / "motion_time.json").read_bytes()).hexdigest()
    assert document["source"]["motion_time_sha256"] == on_disk


def test_the_shipped_pretty_printed_motion_config_is_accepted(workspace: Path) -> None:
    """The Motion & Time Spec is bound as raw source bytes, not re-encoded.

    Phase 17 ships it pretty-printed; imposing this layer's canonical encoding
    on another phase's document would be a boundary violation, so the exact
    shipped formatting must pass.
    """
    raw = (workspace / "motion_time.json").read_bytes()
    assert b"\n  " in raw  # genuinely pretty-printed, or this test proves nothing
    assert _run(workspace) == 0


def test_it_refuses_to_overwrite_an_existing_plan(workspace: Path) -> None:
    """A plan is evidence; silently replacing one loses history."""
    (workspace / "shots.json").write_text("{}", encoding="utf-8")
    assert _run(workspace) == 1
    assert (workspace / "shots.json").read_text(encoding="utf-8") == "{}"


def test_a_pretty_printed_story_plan_is_refused(workspace: Path) -> None:
    """Reformatting changes the bytes, so the binding could no longer be true."""
    target = workspace / "story.json"
    target.write_text(
        json.dumps(json.loads(target.read_text(encoding="utf-8")), indent=2),
        encoding="utf-8",
    )
    assert _run(workspace) == 1
    assert not (workspace / "shots.json").exists()


def test_a_missing_input_is_reported_not_crashed(workspace: Path) -> None:
    """A missing input is reported not crashed."""
    assert _run(workspace, story=str(workspace / "absent.json")) == 1


def test_a_missing_motion_time_file_is_reported(workspace: Path) -> None:
    """A missing motion time file is reported."""
    assert _run(workspace, motion_time=str(workspace / "absent.json")) == 1
    assert not (workspace / "shots.json").exists()


def test_an_empty_motion_time_file_is_refused(workspace: Path) -> None:
    """An empty motion time file is refused."""
    (workspace / "motion_time.json").write_bytes(b"")
    assert _run(workspace) == 1
    assert not (workspace / "shots.json").exists()


def test_a_non_json_input_is_reported(workspace: Path) -> None:
    """A non json input is reported."""
    (workspace / "story.json").write_bytes(b"not json")
    assert _run(workspace) == 1


def test_a_story_plan_paired_with_a_broken_clock_is_refused(
    workspace: Path,
) -> None:
    """A hand-written five-integer timeline can no longer stand in for the clock."""
    (workspace / "motion_time.json").write_bytes(
        dumps_canonical({"fps": 24, "start_frame": 1, "end_frame": 193}, "timeline")
    )
    assert _run(workspace) == 1
    assert not (workspace / "shots.json").exists()


def test_a_self_consistent_alternate_clock_file_is_refused_end_to_end(
    workspace: Path, motion_time: bytes
) -> None:
    """The reviewer's exact V2 gap, closed at the CLI too.

    A well-formed 30 fps Motion & Time Spec whose arithmetic closes is written
    to disk and offered as ``--motion-time``; the command refuses and writes
    nothing, because the source is not the canonical Phase 17 document.
    """
    document = json.loads(motion_time.decode("utf-8"))
    document["timeline"]["fps"] = 30
    (workspace / "motion_time.json").write_text(json.dumps(document, indent=2), encoding="utf-8")
    assert _run(workspace) == 1
    assert not (workspace / "shots.json").exists()


def test_a_shifted_alternate_clock_file_is_refused_end_to_end(workspace: Path) -> None:
    """A shifted-but-consistent window is refused end to end."""
    document = json.loads((workspace / "motion_time.json").read_text(encoding="utf-8"))
    timeline = document["timeline"]
    timeline["start_frame"] = 101
    timeline["end_frame"] = 101 + 24 + 120 + 48
    (workspace / "motion_time.json").write_text(json.dumps(document), encoding="utf-8")
    assert _run(workspace) == 1
    assert not (workspace / "shots.json").exists()


def test_a_rehold_alternate_clock_file_is_refused_end_to_end(workspace: Path) -> None:
    """Altered hold lengths whose arithmetic closes are refused end to end."""
    document = json.loads((workspace / "motion_time.json").read_text(encoding="utf-8"))
    timeline = document["timeline"]
    timeline["start_hold_frames"] = 48
    timeline["end_hold_frames"] = 24
    (workspace / "motion_time.json").write_text(json.dumps(document), encoding="utf-8")
    assert _run(workspace) == 1
    assert not (workspace / "shots.json").exists()


def test_a_byte_variant_of_the_canonical_clock_is_refused_end_to_end(
    workspace: Path, motion_time: bytes
) -> None:
    """Same parsed meaning, different bytes: still not the canonical source."""
    (workspace / "motion_time.json").write_bytes(motion_time + b"\n")
    assert _run(workspace) == 1
    assert not (workspace / "shots.json").exists()


def test_it_does_not_modify_the_files_it_reads(workspace: Path) -> None:
    """It does not modify the files it reads."""
    names = ("story.json", "motion_time.json")
    before = {name: (workspace / name).read_bytes() for name in names}
    _run(workspace)
    for name, payload in before.items():
        assert (workspace / name).read_bytes() == payload


def test_two_runs_produce_identical_files(workspace: Path) -> None:
    """Two runs produce identical files."""
    _run(workspace, output="one.json")
    _run(workspace, output="two.json")
    assert (workspace / "one.json").read_bytes() == (workspace / "two.json").read_bytes()


# ---------------------------------------------------------------------------
# camera_profile: V1 stays byte-for-byte historical; V2 is the deterministic
# edit layer over the same V1 document.
# ---------------------------------------------------------------------------


def test_v1_is_the_default_and_is_byte_for_byte_unchanged(
    workspace: Path, story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """Omitted and explicit ``--camera-profile v1`` both write today's bytes."""
    _run(workspace, output="omitted.json")
    _run(workspace, output="explicit.json", camera_profile="v1")
    expected = build_shot_direction_plan_bytes(story_ep0_to_ep1, motion_time)
    assert (workspace / "omitted.json").read_bytes() == expected
    assert (workspace / "explicit.json").read_bytes() == expected


def test_v2_output_is_accepted_by_v2_and_refused_by_v1(workspace: Path) -> None:
    """Genuine isolation: the V2 plan passes V2 and fails the V1-only validator."""
    assert _run(workspace, output="v2.json", camera_profile="v2") == 0
    document = json.loads((workspace / "v2.json").read_text(encoding="utf-8"))
    assert validate_shot_direction_plan_v2(document) is not None
    with pytest.raises(ValueError):
        validate_shot_direction_plan(document)


def test_v2_output_pins_the_independent_camera_movement_derivation(
    workspace: Path, story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """The CLI's V2 bytes equal the independently derived chain, byte for byte.

    The independent chain is the one other V2 lanes already pin:
    ``plan_camera_movements(build_shot_direction_plan_document(...))``.
    """
    assert _run(workspace, output="v2.json", camera_profile="v2") == 0
    v1_document = build_shot_direction_plan_document(story_ep0_to_ep1, motion_time)
    independent = plan_camera_movements(v1_document)
    assert (workspace / "v2.json").read_bytes() == dumps_canonical(
        independent, "shot direction plan"
    )
    moving = [shot for shot in independent["shots"] if shot.get("camera_movement") is not None]
    assert moving, "the canonical EP1 V2 plan must carry camera_movement blocks"
    assert (
        build_shot_direction_plan_v2_bytes(story_ep0_to_ep1, motion_time)
        == (workspace / "v2.json").read_bytes()
    )


def test_two_v2_runs_produce_identical_bytes(workspace: Path) -> None:
    """Same story and clock always produce the same V2 bytes."""
    _run(workspace, output="one.json", camera_profile="v2")
    _run(workspace, output="two.json", camera_profile="v2")
    assert (workspace / "one.json").read_bytes() == (workspace / "two.json").read_bytes()


def test_the_cross_check_threads_the_v2_profile(
    workspace: Path, story_ep0_to_ep1: dict[str, Any], motion_time: bytes
) -> None:
    """The CLI's own cross-check accepts the V2 plan under v2 and refuses it under v1."""
    _run(workspace, output="v2.json", camera_profile="v2")
    document = json.loads((workspace / "v2.json").read_text(encoding="utf-8"))
    verified = validate_shot_direction_plan_against_story(
        document, story_ep0_to_ep1, motion_time, camera_profile="v2"
    )
    assert verified is not None
    with pytest.raises(ValueError):
        validate_shot_direction_plan_against_story(
            document, story_ep0_to_ep1, motion_time, camera_profile="v1"
        )
