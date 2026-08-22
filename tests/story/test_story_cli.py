"""The command-line entry point is a thin shell over the contract.

It reads files, hands them to the story layer, and writes canonical bytes. Every
refusal it reports comes from the contract, not from the shell.
"""

import json
import shutil
from pathlib import Path

import pytest

from living_diorama.cli import build_story_plan

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A scratch directory holding copies of the three real exports."""
    for episode in (0, 1, 2):
        name = f"render_export_ep{episode}.json"
        shutil.copy(FIXTURES / name, tmp_path / name)
    return tmp_path


def test_it_writes_a_transition_plan(workspace: Path) -> None:
    """It writes a transition plan."""
    output = workspace / "plan.json"
    code = build_story_plan.main(
        [
            "--current",
            str(workspace / "render_export_ep2.json"),
            "--previous",
            str(workspace / "render_export_ep1.json"),
            "--output",
            str(output),
        ]
    )
    assert code == 0
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["source"]["mode"] == "transition"
    assert document["beats"]


def test_it_writes_a_baseline_plan_without_a_previous_export(workspace: Path) -> None:
    """It writes a baseline plan without a previous export."""
    output = workspace / "plan.json"
    code = build_story_plan.main(
        [
            "--current",
            str(workspace / "render_export_ep0.json"),
            "--output",
            str(output),
        ]
    )
    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["source"]["mode"] == "baseline"


def test_the_written_bytes_are_the_canonical_bytes(workspace: Path) -> None:
    """The written bytes are the canonical bytes."""
    from living_diorama.story import build_episode_story_plan_bytes

    output = workspace / "plan.json"
    build_story_plan.main(
        [
            "--current",
            str(workspace / "render_export_ep2.json"),
            "--previous",
            str(workspace / "render_export_ep1.json"),
            "--output",
            str(output),
        ]
    )
    current = json.loads((workspace / "render_export_ep2.json").read_text(encoding="utf-8"))
    previous = json.loads((workspace / "render_export_ep1.json").read_text(encoding="utf-8"))
    assert output.read_bytes() == build_episode_story_plan_bytes(current, previous)


def test_it_refuses_to_overwrite_an_existing_plan(workspace: Path) -> None:
    """A plan is evidence; silently replacing one loses history."""
    output = workspace / "plan.json"
    output.write_text("{}", encoding="utf-8")
    code = build_story_plan.main(
        [
            "--current",
            str(workspace / "render_export_ep0.json"),
            "--output",
            str(output),
        ]
    )
    assert code == 1
    assert output.read_text(encoding="utf-8") == "{}"


def test_it_reports_a_missing_input_rather_than_crashing(workspace: Path) -> None:
    """It reports a missing input rather than crashing."""
    code = build_story_plan.main(
        [
            "--current",
            str(workspace / "absent.json"),
            "--output",
            str(workspace / "plan.json"),
        ]
    )
    assert code == 1


def test_it_reports_a_non_consecutive_pair_rather_than_writing_a_plan(
    workspace: Path,
) -> None:
    """It reports a non consecutive pair rather than writing a plan."""
    output = workspace / "plan.json"
    code = build_story_plan.main(
        [
            "--current",
            str(workspace / "render_export_ep2.json"),
            "--previous",
            str(workspace / "render_export_ep0.json"),
            "--output",
            str(output),
        ]
    )
    assert code == 1
    assert not output.exists()


def test_it_does_not_modify_the_exports_it_reads(workspace: Path) -> None:
    """It does not modify the exports it reads."""
    before = {
        name: (workspace / name).read_bytes()
        for name in ("render_export_ep1.json", "render_export_ep2.json")
    }
    build_story_plan.main(
        [
            "--current",
            str(workspace / "render_export_ep2.json"),
            "--previous",
            str(workspace / "render_export_ep1.json"),
            "--output",
            str(workspace / "plan.json"),
        ]
    )
    for name, payload in before.items():
        assert (workspace / name).read_bytes() == payload


def test_two_runs_produce_identical_files(workspace: Path) -> None:
    """Two runs produce identical files."""
    args = [
        "--current",
        str(workspace / "render_export_ep2.json"),
        "--previous",
        str(workspace / "render_export_ep1.json"),
    ]
    build_story_plan.main([*args, "--output", str(workspace / "one.json")])
    build_story_plan.main([*args, "--output", str(workspace / "two.json")])
    assert (workspace / "one.json").read_bytes() == (workspace / "two.json").read_bytes()


# ------------------------------------------------- canonical source bytes


def test_it_accepts_a_canonical_export_file(workspace: Path) -> None:
    """The files write_render_export produces are exactly what is expected."""
    output = workspace / "plan.json"
    code = build_story_plan.main(
        [
            "--current",
            str(workspace / "render_export_ep2.json"),
            "--previous",
            str(workspace / "render_export_ep1.json"),
            "--output",
            str(output),
        ]
    )
    assert code == 0


def test_the_document_digest_is_the_digest_of_the_source_file_bytes(
    workspace: Path,
) -> None:
    """The claim the binding makes, stated as a test.

    Because the CLI refuses any file that is not its own canonical encoding,
    ``document_sha256`` is simultaneously the digest of the canonical document
    and of the bytes actually on disk.
    """
    import hashlib

    output = workspace / "plan.json"
    build_story_plan.main(
        [
            "--current",
            str(workspace / "render_export_ep2.json"),
            "--previous",
            str(workspace / "render_export_ep1.json"),
            "--output",
            str(output),
        ]
    )
    plan = json.loads(output.read_text(encoding="utf-8"))
    for role, name in (("current", "render_export_ep2.json"),
                       ("previous", "render_export_ep1.json")):
        on_disk = hashlib.sha256((workspace / name).read_bytes()).hexdigest()
        assert plan["source"][role]["document_sha256"] == on_disk


def test_a_pretty_printed_export_is_refused(workspace: Path) -> None:
    """Reformatting a file changes its bytes, so it can no longer be bound."""
    target = workspace / "render_export_ep0.json"
    document = json.loads(target.read_text(encoding="utf-8"))
    target.write_text(json.dumps(document, indent=2), encoding="utf-8")
    output = workspace / "plan.json"
    code = build_story_plan.main(
        ["--current", str(target), "--output", str(output)]
    )
    assert code == 1
    assert not output.exists()


def test_a_reordered_key_export_is_refused(workspace: Path) -> None:
    """Same document, different bytes. Refused rather than re-serialized."""
    target = workspace / "render_export_ep0.json"
    document = json.loads(target.read_text(encoding="utf-8"))
    reordered = {key: document[key] for key in sorted(document, reverse=True)}
    target.write_bytes(
        json.dumps(reordered, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        + b"\n"
    )
    output = workspace / "plan.json"
    code = build_story_plan.main(
        ["--current", str(target), "--output", str(output)]
    )
    assert code == 1
    assert not output.exists()


def test_an_export_missing_its_trailing_newline_is_refused(workspace: Path) -> None:
    """A single byte is enough to break the binding, and it is caught."""
    target = workspace / "render_export_ep0.json"
    target.write_bytes(target.read_bytes().rstrip(b"\n"))
    output = workspace / "plan.json"
    code = build_story_plan.main(
        ["--current", str(target), "--output", str(output)]
    )
    assert code == 1


def test_a_non_json_file_is_reported_not_crashed(workspace: Path) -> None:
    """A non json file is reported not crashed."""
    target = workspace / "render_export_ep0.json"
    target.write_bytes(b"not json at all")
    code = build_story_plan.main(
        ["--current", str(target), "--output", str(workspace / "plan.json")]
    )
    assert code == 1


def test_a_baseline_request_for_a_later_episode_is_refused(workspace: Path) -> None:
    """The CLI surfaces the baseline scope rule rather than bypassing it."""
    output = workspace / "plan.json"
    code = build_story_plan.main(
        ["--current", str(workspace / "render_export_ep2.json"), "--output", str(output)]
    )
    assert code == 1
    assert not output.exists()
