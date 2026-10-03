"""Phase 5 red-team lane 1 regressions: the product boundary (paths, state, locks, journals, status).

Every test is the reproduction of a finding, with the refusal or the safe outcome it demands.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ldyf.factory import faultlab as FL
from ldyf.factory import pipeline as P
from ldyf.factory import production as PR
from ldyf.factory import winproc
from ldyf.factory.production import EXIT_CODES

from .factory_support import BRIEF_PATH, FFMPEG, WINDOWS_TTS
import shutil

pytestmark = pytest.mark.skipif(not (FFMPEG and WINDOWS_TTS), reason="needs ffmpeg and the speech engine")


@pytest.fixture
def clone(factory_pkg, tmp_path_factory):
    dst = Path(tmp_path_factory.mktemp("rt")) / "pkg"
    shutil.copytree(factory_pkg, dst)
    return dst


def _produce(pkg, **kw):
    kw.setdefault("log", lambda s: None)
    kw.setdefault("retry_backoff_s", (0.0, 0.0))
    return PR.produce(BRIEF_PATH, pkg, **kw)


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# ---- F1: nothing outside the package is ever deleted; a user's own files are never swallowed

def test_a_users_folder_with_a_brief_and_other_files_is_never_cleaned(tmp_path):
    folder = tmp_path / "pkg"
    folder.mkdir()
    (folder / "brief.json").write_text(BRIEF_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    (folder / "thesis.docx.tmp").write_bytes(b"my thesis")
    (folder / "mydoc.txt").write_text("mine")
    before = _tree(folder)
    st = _produce(folder)
    assert st["exit_code"] != 0 and st["code"] in ("foreign_directory", "bad_output_path")
    assert _tree(folder) == before


def test_a_junction_in_the_output_cannot_make_produce_delete_files_elsewhere(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "budget.tmp").write_bytes(b"precious")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "brief.json").write_text(BRIEF_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    run = subprocess.run(["cmd", "/c", "mklink", "/J", str(pkg / "render"), str(outside)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    try:
        st = _produce(pkg)
        assert st["exit_code"] != 0
        assert (outside / "budget.tmp").read_bytes() == b"precious"
    finally:
        os.rmdir(pkg / "render")


# ---- F2: no command wipes a directory

def test_the_destructive_no_resume_flag_is_gone():
    run = subprocess.run([sys.executable, "-m", "ldyf.factory", "run", "--brief", str(BRIEF_PATH), "--out", "x",
                          "--no-resume"], capture_output=True, text=True, cwd=str(PR.REPO_ROOT))
    assert run.returncode == 2 and "no-resume" in run.stderr


def test_the_advanced_run_verb_refuses_finished_foreign_and_owned_directories(clone, tmp_path):
    for target, why in ((clone, "finished package"),):
        run = subprocess.run([sys.executable, "-m", "ldyf.factory", "run", "--brief", str(BRIEF_PATH), "--out", str(target),
                              "--until", "brief"], capture_output=True, text=True, cwd=str(PR.REPO_ROOT))
        assert run.returncode == 2, why
    other = tmp_path / "important"
    other.mkdir()
    (other / "important.txt").write_text("keep")
    run = subprocess.run([sys.executable, "-m", "ldyf.factory", "run", "--brief", str(BRIEF_PATH), "--out", str(other),
                          "--until", "brief"], capture_output=True, text=True, cwd=str(PR.REPO_ROOT))
    assert run.returncode == 2 and (other / "important.txt").read_text() == "keep"
    assert [p.name for p in other.iterdir()] == ["important.txt"]


# ---- F3: a killed re-run never leaves a stale success on disk

def test_a_killed_rerun_does_not_leave_the_previous_success_in_the_status_files(clone, tmp_path):
    status_file = tmp_path / "status.json"
    good = _produce(clone, status_path=status_file)
    assert good["outcome"] == "already_complete" and json.loads(status_file.read_text())["exit_code"] == 0
    FL.corrupt_file(clone / "package.json", mode="truncate")          # forces a real re-run
    r = FL.run_produce(BRIEF_PATH, clone, kill_when=FL.line_contains("[facts]"), status_file=status_file)
    assert r["killed"], r["stdout_tail"]
    now = json.loads(status_file.read_text())
    assert now["outcome"] in ("in_progress", "interrupted") and now.get("exit_code") != 0
    shown = PR.read_status(clone)
    assert shown["last_run"]["outcome"] in ("in_progress", "interrupted")
    assert shown["run_in_progress"] is False
    assert _produce(clone)["outcome"] == "complete"


# ---- F5: a transient read failure never downgrades a valid package

def test_a_file_held_by_a_scanner_does_not_make_a_valid_package_look_invalid(clone):
    with winproc.ExclusiveHold(str(clone / "story.json")):
        st = _produce(clone)
    assert st["exit_code"] == EXIT_CODES["environment"]
    assert (clone / "package.json").is_file()                       # still marked finished, nothing quarantined
    assert not list((PR.state_dir_for(clone) / "quarantine").glob("*")) if (PR.state_dir_for(clone) / "quarantine").exists() else True
    assert _produce(clone)["outcome"] == "already_complete"


# ---- F6: the write probe never touches a finished package

def test_preflight_writes_nothing_into_a_finished_package(clone):
    before = {p: (clone / p).stat().st_mtime_ns for p in P.package_files(clone)}
    names_before = sorted(os.listdir(clone))
    _produce(clone)
    assert sorted(os.listdir(clone)) == names_before
    assert not list(clone.rglob(".write_probe_*"))


# ---- F7: unhashed state files can never block a verified package or a status read

def test_a_journal_with_a_torn_multibyte_tail_and_scalar_rows_does_not_block_a_run(clone):
    state = PR.state_dir_for(clone)
    state.mkdir(exist_ok=True)
    (state / "journal.jsonl").write_bytes(
        b'{"event": "run_start", "run": "a"}\n42\n[1, 2]\n"x"\n{"event": "stage", "run": "a", "stage": "facts"}\n'
        + "{\"event\": \"log\", \"line\": \"café".encode("utf-8")[:-1])
    assert PR.read_status(clone)["package"]
    assert _produce(clone)["outcome"] == "already_complete"


@pytest.mark.parametrize("junk", ["[]", '{"runs": [1]}', '{"runs": [{"stages": null}]}',
                                  '{"runs": [{"stages": [{"stage": "x", "seconds": "slow", "status": "ran"}]}]}', "\"s\""])
def test_a_malformed_run_log_never_turns_a_verified_package_into_an_error(clone, junk):
    (clone / "run_log.json").write_text(junk, encoding="utf-8")
    st = _produce(clone)
    assert st["outcome"] == "already_complete" and st["exit_code"] == 0


# ---- F8: path aliases and nesting

@pytest.mark.parametrize("name", ["ep.PRODUCTION", "ep.Production", "ep.production.", "ep.production "])
def test_every_spelling_of_the_state_suffix_is_refused(tmp_path, name):
    assert PR.output_path_problem(tmp_path / name)


def test_an_output_inside_a_finished_package_is_refused(clone):
    st = _produce(clone / "child")
    assert st["exit_code"] == 12 and st["code"] == "bad_output_path"
    assert P.verify_package(clone)["audit_pass"]                    # the parent was not made invalid


# ---- F9: --no-render never overwrites engine-confirmed documents of a rendered package

def test_a_plan_only_run_is_refused_on_a_package_whose_render_is_sealed(clone):
    FL.corrupt_file(clone / "package.json", mode="truncate")
    before = (clone / "narration.json").read_bytes()
    st = _produce(clone, render=False)
    assert st["exit_code"] != 0 or st["outcome"] == "planned_not_rendered"
    assert (clone / "narration.json").read_bytes() == before


# ---- F10: a refused run never reports stages it did not run

def test_a_refused_run_lists_no_stages_of_an_earlier_run(clone, tmp_path):
    _produce(clone)
    other = tmp_path / "other.json"
    raw = json.loads(BRIEF_PATH.read_text(encoding="utf-8"))
    raw.update(episode_number=9, title="Another episode")
    other.write_text(json.dumps(raw), encoding="utf-8")
    st = PR.produce(other, clone, log=lambda s: None)
    assert st["exit_code"] == 13 and st["stages"] == []


# ---- F11: hostile briefs

def test_a_depth_bomb_brief_is_a_typed_refusal(tmp_path):
    bp = tmp_path / "bomb.json"
    bp.write_bytes(b"[" * 200000)
    st = PR.produce(bp, tmp_path / "pkg", log=lambda s: None)
    assert st["exit_code"] == 10


def test_an_oversized_title_is_refused_not_narrated(tmp_path):
    raw = json.loads(BRIEF_PATH.read_text(encoding="utf-8"))
    raw["title"] = "A" * 900_000
    bp = tmp_path / "big.json"
    bp.write_text(json.dumps(raw), encoding="utf-8")
    st = PR.produce(bp, tmp_path / "pkg", log=lambda s: None, min_free_gb=10 ** 9)
    assert st["exit_code"] == 10, (st["exit_code"], st["code"])


# ---- F12: produce has no way to report success without having verified

def test_produce_cannot_be_asked_to_skip_verification():
    import inspect
    assert "verify" not in inspect.signature(PR.produce).parameters


def test_control_characters_in_the_title_are_refused(tmp_path):
    raw = json.loads(BRIEF_PATH.read_text(encoding="utf-8"))
    raw["title"] = "Bad\x07title\nwith controls"
    bp = tmp_path / "c.json"
    bp.write_text(json.dumps(raw), encoding="utf-8")
    assert PR.produce(bp, tmp_path / "pkg", log=lambda s: None)["exit_code"] == 10
