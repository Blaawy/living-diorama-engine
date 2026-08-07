"""Render export CLI: explicit input, guarded output, honest exits.

The command's whole job is to refuse everything unsafe -- blank paths, bad
episode text, existing destinations, anything resolving into the immutable
save root -- and to report only what was actually written and read back.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from living_diorama.persistence import loads_canonical, sha256_hex
from living_diorama.render import build_render_export_bytes, write_render_export
from living_diorama.render.export_episode import main
from persistence.test_save_manager import require_symlink_support
from render.conftest import (
    publish_calm_episode_zero,
    publish_scar_chain,
    tree_bytes,
)


class TestSuccessPath:
    """A verified export, reported from the written bytes."""

    def test_main_exports_and_reports_the_written_artifact(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 0, correct report lines, and the exact bytes on disk."""
        root = tmp_path / "saves"
        publish_calm_episode_zero(root)
        output = tmp_path / "export.json"
        exit_code = main(["--save-root", str(root), "--episode", "0", "--output", str(output)])
        assert exit_code == 0
        data = output.read_bytes()
        assert data == build_render_export_bytes(root, 0)
        document = loads_canonical(data, "render export")
        assert type(document) is dict
        source = document["source"]
        assert type(source) is dict
        captured = capsys.readouterr()
        assert "render export verified" in captured.out
        assert f"episode: {source['episode']}" in captured.out
        assert f"tick: {source['tick']}" in captured.out
        assert f"source state hash: {source['state_hash']}" in captured.out
        assert f"render sha256: {sha256_hex(data)}" in captured.out
        assert f"bytes: {len(data)}" in captured.out
        assert f"output: {output}" in captured.out
        assert captured.err == ""

    def test_write_returns_exactly_the_read_back_bytes(self, tmp_path: Path) -> None:
        """The returned bytes are the destination's actual content."""
        root = tmp_path / "saves"
        publish_calm_episode_zero(root)
        output = tmp_path / "export.json"
        written = write_render_export(root, 0, output)
        assert written == output.read_bytes()

    def test_module_is_invocable_with_python_dash_m(self) -> None:
        """The documented entry point exists and describes its arguments."""
        completed = subprocess.run(
            [sys.executable, "-m", "living_diorama.render.export_episode", "--help"],
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0
        assert b"--save-root" in completed.stdout
        assert b"--episode" in completed.stdout
        assert b"--output" in completed.stdout


class TestInputHardening:
    """Operator input is refused as found, never repaired."""

    def test_blank_save_root_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An empty save root is refused, not normalized to the cwd."""
        for blank in ("", "   "):
            exit_code = main(
                ["--save-root", blank, "--episode", "0", "--output", str(tmp_path / "e.json")]
            )
            assert exit_code == 1
            assert "--save-root must not be empty" in capsys.readouterr().err

    def test_blank_output_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An empty output path is refused before anything loads."""
        for blank in ("", "  "):
            exit_code = main(
                ["--save-root", str(tmp_path / "saves"), "--episode", "0", "--output", blank]
            )
            assert exit_code == 1
            assert "--output must not be empty" in capsys.readouterr().err

    @pytest.mark.parametrize("text", ["-1", "abc", "1.0", "+1", " 1", "007", "0x1", ""])
    def test_invalid_episode_text_is_refused(
        self, text: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Only a canonical non-negative integer names an episode."""
        exit_code = main(
            [
                "--save-root",
                str(tmp_path / "saves"),
                "--episode",
                text,
                "--output",
                str(tmp_path / "e.json"),
            ]
        )
        assert exit_code == 1
        assert "--episode must be a non-negative integer" in capsys.readouterr().err

    def test_missing_source_episode_fails_cleanly(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An absent episode is a refusal, not an empty export."""
        exit_code = main(
            [
                "--save-root",
                str(tmp_path / "saves"),
                "--episode",
                "0",
                "--output",
                str(tmp_path / "e.json"),
            ]
        )
        assert exit_code == 1
        assert "render export failed" in capsys.readouterr().err
        assert not (tmp_path / "e.json").exists()

    def test_main_requires_all_arguments(self) -> None:
        """Missing required arguments exit nonzero through the parser."""
        with pytest.raises(SystemExit) as excinfo:
            main([])
        assert excinfo.value.code == 2


class TestOutputSafety:
    """The destination is fresh, outside the save root, and never replaced."""

    def test_existing_output_is_never_overwritten(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An existing destination is refused and left untouched."""
        root = tmp_path / "saves"
        publish_calm_episode_zero(root)
        output = tmp_path / "export.json"
        output.write_bytes(b"precious\n")
        with pytest.raises(FileExistsError, match="never overwritten"):
            write_render_export(root, 0, output)
        assert output.read_bytes() == b"precious\n"
        exit_code = main(["--save-root", str(root), "--episode", "0", "--output", str(output)])
        assert exit_code == 1
        assert "never overwritten" in capsys.readouterr().err
        assert output.read_bytes() == b"precious\n"

    def test_output_at_the_save_root_is_refused(self, tmp_path: Path) -> None:
        """The save root itself is not a destination."""
        root = tmp_path / "saves"
        publish_calm_episode_zero(root)
        with pytest.raises(ValueError, match="resolves inside the save root"):
            write_render_export(root, 0, root)

    def test_output_inside_the_save_root_is_refused(self, tmp_path: Path) -> None:
        """Nothing derived may land beside the episode directories."""
        root = tmp_path / "saves"
        publish_calm_episode_zero(root)
        before = tree_bytes(root)
        with pytest.raises(ValueError, match="resolves inside the save root"):
            write_render_export(root, 0, root / "render_export.json")
        assert tree_bytes(root) == before

    def test_output_inside_an_episode_directory_is_refused(self, tmp_path: Path) -> None:
        """The immutable episode directory may not gain a media artifact."""
        root = tmp_path / "saves"
        publish_calm_episode_zero(root)
        before = tree_bytes(root)
        with pytest.raises(ValueError, match="resolves inside the save root"):
            write_render_export(root, 0, root / "episode_000" / "render_export.json")
        assert tree_bytes(root) == before

    def test_symlink_alias_into_the_save_root_is_refused(self, tmp_path: Path) -> None:
        """A destination that resolves into the root through a link is refused."""
        require_symlink_support(tmp_path, target_is_directory=True)
        root = tmp_path / "saves"
        publish_calm_episode_zero(root)
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        before = tree_bytes(root)
        with pytest.raises(ValueError, match="resolves inside the save root"):
            write_render_export(root, 0, alias / "sneaky.json")
        assert tree_bytes(root) == before

    def test_missing_output_directory_is_refused_cleanly(self, tmp_path: Path) -> None:
        """A destination in an absent directory is a clear refusal."""
        root = tmp_path / "saves"
        publish_calm_episode_zero(root)
        with pytest.raises(FileNotFoundError, match="does not exist"):
            write_render_export(root, 0, tmp_path / "missing" / "export.json")

    def test_verification_failure_creates_no_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A refused source leaves no file behind anywhere."""
        root = tmp_path / "saves"
        publish_calm_episode_zero(root)
        state_path = root / "episode_000" / "world_state.json"
        state_path.write_bytes(state_path.read_bytes().replace(b"1", b"2", 1))
        output = tmp_path / "export.json"
        exit_code = main(["--save-root", str(root), "--episode", "0", "--output", str(output)])
        assert exit_code == 1
        assert "render export failed" in capsys.readouterr().err
        assert not output.exists()


class TestCrossInterpreterDeterminism:
    """The same source exports identically across interpreters and seeds."""

    def test_exports_agree_across_hash_seeds(self, tmp_path: Path) -> None:
        """Two subprocesses with different hash seeds produce equal bytes."""
        exports: list[bytes] = []
        for seed, name in (("0", "a"), ("123456", "b")):
            root = tmp_path / f"saves_{name}"
            publish_scar_chain(root)
            output = tmp_path / f"export_{name}.json"
            environment = dict(os.environ)
            environment["PYTHONHASHSEED"] = seed
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "living_diorama.render.export_episode",
                    "--save-root",
                    str(root),
                    "--episode",
                    "1",
                    "--output",
                    str(output),
                ],
                capture_output=True,
                env=environment,
                check=False,
            )
            assert completed.returncode == 0, completed.stderr
            exports.append(output.read_bytes())
        assert exports[0] == exports[1]
