"""Phase 5 gates A and C: the one-command product and its fail-closed behaviour.

Fast tests need nothing but the code. The rest copy the REAL sealed episode package into a
private directory and break it in the ways storage, people and processes break things; each
asserts (1) a typed exit class, (2) that no false success was reported, (3) what state the
directory was left in, and (4) that recovery advice never tells anyone to delete a package.
"""
from __future__ import annotations

import errno
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ldyf.factory import FactoryError, production as PR
from ldyf.factory import faultlab as FL
from ldyf.factory import pipeline as P
from ldyf.factory import winproc
from ldyf.factory.util import sha256_file
from ldyf.factory.production import EXIT_CODES, ProductionError

from .factory_support import BRIEF_PATH, FFMPEG, WINDOWS_TTS

pytestmark = pytest.mark.skipif(not (FFMPEG and WINDOWS_TTS),
                                reason="production runs need ffmpeg and the Windows speech engine")


# ------------------------------------------------------------------------- helpers

def _short(tmp_path_factory) -> Path:
    return Path(tmp_path_factory.mktemp("p"))


@pytest.fixture
def clone(factory_pkg, tmp_path_factory):
    """A private, writable copy of the finished package (`pkg`) with its brief path."""
    base = _short(tmp_path_factory)
    dst = base / "pkg"
    shutil.copytree(factory_pkg, dst)
    return dst


def _produce(pkg: Path, **kw):
    kw.setdefault("log", lambda s: None)
    kw.setdefault("retry_backoff_s", (0.0, 0.0))
    return PR.produce(BRIEF_PATH, pkg, **kw)


def _assert_no_false_success(st: dict) -> None:
    assert st["exit_code"] != 0 and st["outcome"] in ("failed", "interrupted"), st["outcome"]
    assert st["package"].get("state_at_end") != "finished_verified"
    assert st["advice"] and st["code"]


def _digest(pkg: Path) -> dict[str, tuple[str, float]]:
    out = {}
    for p in sorted(pkg.rglob("*")):
        if p.is_file():
            rel = p.relative_to(pkg).as_posix()
            out[rel] = (sha256_file(p), p.stat().st_mtime)
    return out


def _released(state: Path) -> bool:
    """True when no run holds the package: asked of the OS lock, not of any file."""
    return not PR.lock_is_held(state)


def _editor_up() -> bool:
    try:
        PR.probe_editor(timeout=10)
        return True
    except Exception:  # noqa: BLE001
        return False


# ------------------------------------------------------------------ the exit-code contract

def test_exit_codes_are_unique_and_only_success_is_zero():
    zero = {k for k, v in EXIT_CODES.items() if v == 0}
    assert zero == {"complete", "already_complete"}
    nonzero = [v for v in EXIT_CODES.values() if v != 0]
    assert len(nonzero) == len(set(nonzero))
    assert EXIT_CODES["planned_not_rendered"] != 0           # a plan is never reported as an episode


def test_every_stage_and_known_code_maps_to_a_declared_class():
    for stage, klass in PR._STAGE_CLASS.items():
        assert klass in EXIT_CODES, (stage, klass)
    for (_s, _c), klass in PR._CODE_CLASS.items():
        assert klass in EXIT_CODES


def test_exit_class_of_typed_errors():
    from ldyf.factory.render import RenderError
    from ldyf.factory.simulate import SimulationError
    from ldyf.factory.audit import AuditError
    assert PR.exit_class(RenderError("editor_unreachable", "x")) == "dependency_missing"
    assert PR.exit_class(RenderError("render_incomplete", "x")) == "render_failed"
    assert PR.exit_class(SimulationError("no_sumo", "x")) == "dependency_missing"
    assert PR.exit_class(SimulationError("sumo_failed", "x")) == "simulation_failed"
    assert PR.exit_class(AuditError("fail", "x")) == "audit_failed"
    assert PR.exit_class(KeyboardInterrupt()) == "interrupted"
    assert PR.exit_class(ValueError("boom")) == "internal_error"
    assert PR.exit_class(ProductionError("already_running", "x")) == "already_running"
    assert PR.exit_class(ProductionError("editor_busy", "x")) == "dependency_missing"


_FORBIDDEN = re.compile(r"\b(delete|remove|erase|wipe|rmdir|rm -rf|start over|from scratch)\b", re.I)


def test_advice_never_recommends_destroying_a_package():
    texts = list(PR.ADVICE.values()) + [PR._GENERIC_ADVICE]
    for t in texts:
        scrubbed = t.replace("Do not delete the output directory", "")
        assert not _FORBIDDEN.search(scrubbed), t
    assert "Do not delete" in PR._GENERIC_ADVICE


def test_cli_help_lists_every_exit_code_and_resume_instruction():
    run = subprocess.run([sys.executable, "-m", "ldyf.factory", "produce", "--help"],
                         capture_output=True, text=True, cwd=str(PR.REPO_ROOT))
    assert run.returncode == 0
    for name, code in EXIT_CODES.items():
        assert name in run.stdout and str(code) in run.stdout
    assert "SAME command again" in run.stdout
    top = subprocess.run([sys.executable, "-m", "ldyf.factory", "--help"], capture_output=True,
                         text=True, cwd=str(PR.REPO_ROOT))
    for verb in ("produce", "status", "doctor", "verify", "run"):
        assert verb in top.stdout


# ------------------------------------------------------------------------ lock + journal

def _journal(tmp_path):
    return PR.Journal(tmp_path / "journal.jsonl", "r1")


def test_lock_is_exclusive_while_its_owner_lives(tmp_path):
    j = _journal(tmp_path)
    PR.acquire_lock(tmp_path, "a", j)
    with pytest.raises(ProductionError) as e:
        PR.acquire_lock(tmp_path, "b", j)
    assert e.value.code == "already_running"
    PR.release_lock(tmp_path, "a")
    PR.acquire_lock(tmp_path, "c", j)           # free again
    PR.release_lock(tmp_path, "c")


def test_a_lock_whose_owner_died_is_taken_over_and_recorded(tmp_path):
    j = _journal(tmp_path)
    # pid of a process that is certainly gone
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (tmp_path / "owner.json").write_text(json.dumps(
        {"run": "old", "pid": dead.pid, "identity": 123, "host": os.environ.get("COMPUTERNAME", "")}))
    import socket
    (tmp_path / "owner.json").write_text(json.dumps(
        {"run": "old", "pid": dead.pid, "identity": 123, "host": socket.gethostname()}))
    info = PR.acquire_lock(tmp_path, "new", j)
    assert info["recovered_stale_lock"]["run"] == "old"
    assert "stale_lock_recovered" in (tmp_path / "journal.jsonl").read_text()


def test_a_recycled_pid_does_not_hold_the_lock(tmp_path):
    """The lock names the owner's creation time: a live process with the same pid but another
    start time is not the owner."""
    import socket
    j = _journal(tmp_path)
    (tmp_path / "owner.json").write_text(json.dumps(
        {"run": "old", "pid": os.getpid(), "identity": winproc.own_identity() + 1,
         "host": socket.gethostname()}))
    info = PR.acquire_lock(tmp_path, "new", j)
    assert info["recovered_stale_lock"] is not None


def test_two_runs_in_one_process_do_not_lock_each_other_out(tmp_path):
    """The soak found it: the lock file stays on disk after a clean release, and its stale
    'live owner' (this very process) must not refuse the next run."""
    j = _journal(tmp_path)
    for i in range(3):
        info = PR.acquire_lock(tmp_path, f"r{i}", j)
        assert info["recovered_stale_lock"] is None, i       # a clean release recovers nothing
        PR.release_lock(tmp_path, f"r{i}")


def test_a_crashed_runs_metadata_is_reported_as_recovered(tmp_path):
    j = _journal(tmp_path)
    PR.acquire_lock(tmp_path, "dies", j)
    PR._LOCK_HANDLES.clear()               # model the death: no release, no marker (handle just goes away)
    import gc
    gc.collect()
    info = PR.acquire_lock(tmp_path, "next", j)
    assert info["recovered_stale_lock"] and info["recovered_stale_lock"]["run"] == "dies"
    PR.release_lock(tmp_path, "next")


def test_garbage_lock_file_is_recovered(tmp_path):
    (tmp_path / "owner.json").write_bytes(b"\x00\xffnot json")
    info = PR.acquire_lock(tmp_path, "new", _journal(tmp_path))
    assert info["recovered_stale_lock"] == {"unreadable": True}


def test_journal_reports_an_unfinished_previous_run_and_survives_a_torn_line(tmp_path):
    j = PR.Journal(tmp_path / "journal.jsonl", "r1")
    j.write("run_start")
    j.write("stage", stage="facts", status="ran", line="[facts] ran")
    j.write("stage", stage="render", status="ran", line="[render] ran")
    with (tmp_path / "journal.jsonl").open("ab") as f:
        f.write(b'{"t": "x", "run": "r1", "event": "sta')      # killed mid-line
    prev = PR.Journal.previous_run(tmp_path / "journal.jsonl")
    assert prev == {"run": "r1", "ended": False, "last_stage": "render", "last_line": None}
    j.write("run_end")
    assert PR.Journal.previous_run(tmp_path / "journal.jsonl")["ended"] is True


def test_process_identity_distinguishes_live_from_dead():
    assert winproc.process_identity(os.getpid()) not in (None,)
    assert winproc.process_identity(4_000_000) is None
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        ident = winproc.process_identity(p.pid)
        assert ident is not None and ident != winproc.own_identity()
    finally:
        p.kill()
        p.wait()
    assert winproc.process_identity(p.pid) is None


# ---------------------------------------------------------------------- weird briefs

@pytest.mark.parametrize("payload,code", [
    (b"", "brief_unreadable"),
    (b"not json at all", "brief_unreadable"),
    (b"\xff\xfe\x00bad utf8", "brief_unreadable"),
    (b"[1, 2, 3]", "not_an_object"),
    (b'{"schema_version": "episode_brief_v1"}', "missing_field"),
    pytest.param(b"x" * 1_500_000, "brief_unreadable", id="larger-than-1MB"),
])
def test_unusable_briefs_exit_10_and_write_no_package(tmp_path, payload, code):
    bp = tmp_path / "brief.json"
    bp.write_bytes(payload)
    out = tmp_path / "pkg"
    st = PR.produce(bp, out, log=lambda s: None)
    assert st["exit_code"] == EXIT_CODES["brief_invalid"] == 10
    assert st["code"] == code
    assert not out.exists() or not any(out.iterdir())
    _assert_no_false_success(st)


def _brief_with(**patch):
    raw = json.loads(BRIEF_PATH.read_text(encoding="utf-8"))
    for k, v in patch.items():
        if v is None:
            raw.pop(k, None)
        else:
            raw[k] = v
    return raw


@pytest.mark.parametrize("patch,code", [
    ({"surprise": 1}, "unknown_field"),
    ({"seed": float("nan")}, "bad_field"),
    ({"seed": True}, "bad_field"),
    ({"end_seconds": -5}, "bad_field"),
    ({"fps": 0}, "bad_field"),
    ({"world": "../../etc"}, "unknown_world"),
    ({"world": "atlantis"}, "unknown_world"),
    ({"rule": {"kind": "teleport_everyone", "edge": "B1B2", "at_second": 30}}, "bad_rule"),
    ({"rule": {"kind": "close_street", "edge": "B1B2"}}, "bad_rule"),
    ({"prediction": {"text": "x", "metric": "avg_duration_s", "direction": "sideways"}}, "bad_prediction"),
    ({"title": "   "}, "bad_field"),
])
def test_malformed_briefs_are_refused_by_name(tmp_path, patch, code):
    bp = tmp_path / "brief.json"
    bp.write_text(json.dumps(_brief_with(**patch)), encoding="utf-8")     # NaN written as NaN
    st = PR.produce(bp, tmp_path / "pkg", log=lambda s: None)
    assert st["exit_code"] == 10 and st["code"] == code, (st["code"], st["message"])


def test_bom_and_unicode_in_a_brief_are_handled(tmp_path):
    raw = _brief_with(title="¿Qué pasa si se cierra una calle? — 街 ‮ RTL \u0000".replace("\u0000", ""))
    bp = tmp_path / "brief.json"
    bp.write_bytes(b"\xef\xbb\xbf" + json.dumps(raw, ensure_ascii=False).encode("utf-8"))
    out = tmp_path / "pkg"
    st = PR.produce(bp, out, log=lambda s: None, min_free_gb=1e9)       # stop at preflight on purpose
    assert st["code"] == "disk_space"                                   # past the brief, in preflight
    assert st["brief"]["title"].startswith("¿Qué")


# -------------------------------------------------------------------- package assessment

def test_a_directory_that_is_not_a_package_is_never_written_into(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "holiday_photos.zip").write_bytes(b"precious")
    st = PR.produce(BRIEF_PATH, tmp_path / "pkg", log=lambda s: None)
    assert st["exit_code"] == EXIT_CODES["package_conflict"]
    assert st["code"] == "foreign_directory"
    assert sorted(p.name for p in (tmp_path / "pkg").iterdir()) == ["holiday_photos.zip"]
    assert (tmp_path / "pkg" / "holiday_photos.zip").read_bytes() == b"precious"


def test_a_brief_file_inside_the_dir_that_is_not_ours_is_foreign(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "brief.json").write_text('{"hello": "world"}')
    st = PR.produce(BRIEF_PATH, tmp_path / "pkg", log=lambda s: None)
    assert st["code"] == "foreign_directory"


def test_output_path_rules(tmp_path):
    for bad, why in ((Path(tmp_path.anchor), "drive root"), (PR.REPO_ROOT / "ldyf" / "x_out", "source tree")):
        st = PR.produce(BRIEF_PATH, bad, log=lambda s: None)
        assert st["code"] == "bad_output_path" and st["exit_code"] == 12, why
    f = tmp_path / "afile"
    f.write_text("x")
    assert PR.produce(BRIEF_PATH, f, log=lambda s: None)["code"] == "bad_output_path"
    deep = tmp_path / ("d" * 60) / ("e" * 60) / ("f" * 60)
    assert PR.produce(BRIEF_PATH, deep, log=lambda s: None)["code"] == "bad_output_path"
    assert not deep.exists()


# ------------------------------------------------------------------------- preflight

def test_missing_ffmpeg_is_named_before_anything_is_written(tmp_path, monkeypatch):
    real = shutil.which
    monkeypatch.setattr(shutil, "which", lambda n, *a, **k: None if n in ("ffmpeg", "ffprobe") else real(n, *a, **k))
    out = tmp_path / "pkg"
    st = PR.produce(BRIEF_PATH, out, log=lambda s: None)
    assert st["exit_code"] == EXIT_CODES["dependency_missing"] == 11
    assert "ffmpeg" in st["message"]
    assert not out.exists() or not any(out.iterdir())
    assert any(c["check"] == "ffmpeg" and c["status"] == "fail" for c in st["preflight"])


def test_not_enough_disk_stops_before_the_run(tmp_path):
    st = PR.produce(BRIEF_PATH, tmp_path / "pkg", log=lambda s: None, min_free_gb=10 ** 9)
    assert st["exit_code"] == 12 and st["code"] == "disk_space"
    assert "GB" in st["message"]
    assert not (tmp_path / "pkg").exists() or not any((tmp_path / "pkg").iterdir())


def test_an_unwritable_state_directory_is_a_typed_refusal(tmp_path):
    (tmp_path / "pkg.production").write_text("a file where the state directory must go")
    st = PR.produce(BRIEF_PATH, tmp_path / "pkg", log=lambda s: None)
    assert st["exit_code"] == 12 and st["code"] == "bad_output_path"
    _assert_no_false_success(st)


def test_unreachable_editor_stops_a_package_with_unrendered_shots_before_any_change(clone, monkeypatch):
    from ldyf.factory.render import RenderError
    # an interrupted package: marker gone, one shot unfinished, so the editor IS needed
    (clone / "package.json").unlink()
    (clone / "render" / "render.json").unlink()
    (clone / "render" / "hook" / "shot_render.json").unlink()
    monkeypatch.setattr(PR, "probe_editor", lambda timeout=25.0: (_ for _ in ()).throw(
        RenderError("editor_unreachable", "no editor")))
    before = _digest(clone)
    st = _produce(clone)
    assert st["exit_code"] == 11 and st["code"] == "editor_unreachable", st["message"]
    assert "Unreal editor" in st["advice"]
    assert _digest(clone) == before                       # nothing touched, nothing quarantined
    _assert_no_false_success(st)


def test_doctor_changes_nothing_and_reports_every_check(tmp_path):
    res = PR.doctor(BRIEF_PATH, tmp_path / "pkg", render=False)
    names = {c["check"] for c in res["checks"]}
    assert {"ffmpeg", "ffprobe", "ffmpeg_libx264", "sumo", "voice", "world", "disk_space"} <= names
    assert res["ok"] is True


# --------------------------------------------------------------- the finished package

def test_a_finished_verified_package_is_never_touched(clone):
    before = _digest(clone)
    st = _produce(clone)
    assert st["exit_code"] == 0 and st["outcome"] == "already_complete"
    assert st["package"]["state_at_end"] == "finished_verified"
    assert st["package"]["package_hash"] == json.loads((clone / "package.json").read_text())["package_hash"]
    assert _digest(clone) == before                       # every byte AND every mtime
    again = _produce(clone)
    assert again["outcome"] == "already_complete" and _digest(clone) == before
    assert not list(PR.state_dir_for(clone).glob("quarantine/*"))


def test_status_document_is_complete_and_machine_readable(clone):
    st = _produce(clone)
    for key in ("schema_version", "production_version", "run_id", "started_utc", "finished_utc",
                "outcome", "exit_code", "exit_class", "package", "brief", "preflight", "resumed",
                "performance", "verify"):
        assert key in st, key
    on_disk = json.loads((PR.state_dir_for(clone) / "final_status.json").read_text(encoding="utf-8"))
    assert on_disk["run_id"] == st["run_id"]
    assert on_disk["package"]["episode_sha256"]
    assert json.loads(json.dumps(on_disk)) == on_disk
    shown = PR.read_status(clone)
    assert shown["package_state"] == "marked_finished" and shown["run_in_progress"] is False


def test_a_later_refusal_does_not_erase_the_record_of_success(clone, tmp_path):
    good = _produce(clone)
    other = tmp_path / "other.json"
    other.write_text(json.dumps(_brief_with(episode_number=7, title="Another episode")), encoding="utf-8")
    bad = PR.produce(other, clone, log=lambda s: None)
    assert bad["exit_code"] == 13 and bad["code"] == "package_belongs_to_another_brief"
    last = json.loads((PR.state_dir_for(clone) / "last_success_status.json").read_text(encoding="utf-8"))
    assert last["run_id"] == good["run_id"] and last["exit_code"] == 0
    assert P.verify_package(clone)["audit_pass"] is True       # the package itself: untouched and valid


def test_the_package_manifest_is_unchanged_by_state_files(clone):
    _produce(clone)
    assert not any(n.endswith(".production") or "lock" in n for n in os.listdir(clone))
    assert set(P.package_files(clone)) == {r["file"] for r in json.loads(
        (clone / "package.json").read_text())["files"]}


# ---------------------------------------------------- malformed / damaged manifests (fast)

def _mutate_manifest(pkg: Path, fn) -> None:
    doc = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
    fn(doc)
    (pkg / "package.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")


@pytest.mark.parametrize("name,damage,code", [
    ("truncated", lambda p: FL.corrupt_file(p / "package.json", mode="truncate"), "corrupt"),
    ("empty", lambda p: FL.corrupt_file(p / "package.json", mode="empty"), "corrupt"),
    ("bad_seal", lambda p: _mutate_manifest(p, lambda d: d.update(package_hash="0" * 64)), "seal_broken"),
    ("no_files_key", lambda p: _mutate_manifest(p, lambda d: (d.pop("files"), d.update(package_hash=_reseal(d)))), "corrupt"),
    ("files_not_a_list", lambda p: _mutate_manifest(p, lambda d: (d.update(files=7), d.update(package_hash=_reseal(d)))), "corrupt"),
    ("wrong_schema", lambda p: _mutate_manifest(p, lambda d: (d.update(schema_version="x"), d.update(package_hash=_reseal(d)))), "bad_version"),
    ("lists_missing_file", lambda p: _mutate_manifest(p, lambda d: (d["files"].append(
        {"file": "ghost.bin", "bytes": 1, "sha256": "0" * 64}), d.update(package_hash=_reseal(d)))), "package_changed"),
    ("omits_required_file", lambda p: _mutate_manifest(p, lambda d: (d.update(files=[
        r for r in d["files"] if r["file"] != "episode.mp4"]), d.update(package_hash=_reseal(d)))), "package_changed"),
    ("path_traversal_row", lambda p: _mutate_manifest(p, lambda d: (d["files"].append(
        {"file": "../../secret", "bytes": 1, "sha256": "0" * 64}), d.update(package_hash=_reseal(d)))), "package_changed"),
])
def test_damaged_manifests_are_refused_by_verify(clone, name, damage, code):
    damage(clone)
    with pytest.raises(FactoryError) as e:
        P.verify_package(clone)
    assert e.value.code == code, (name, e.value.code, e.value.message)


def _reseal(doc: dict) -> str:
    from ldyf.factory.util import doc_hash
    return doc_hash(doc, "package_hash")


def test_an_extra_file_in_the_package_or_a_link_is_refused(clone):
    (clone / "notes.txt").write_text("not mine")
    with pytest.raises(FactoryError) as e:
        P.verify_package(clone)
    assert e.value.code == "package_changed" and "not in the manifest" in e.value.message
    (clone / "notes.txt").unlink()
    (clone / "x.tmp").write_text("half")
    with pytest.raises(FactoryError) as e:
        P.verify_package(clone)
    assert e.value.code == "unfinished_write"


# ------------------------------------------------- repair: the same command, run again

def test_malformed_manifest_is_repaired_by_running_the_same_command(clone):
    """Interrupted final packaging: package.json truncated mid-write. The package is NOT
    reported finished; running the same command re-derives it and verifies."""
    original = json.loads((clone / "package.json").read_text())["package_hash"]
    FL.corrupt_file(clone / "package.json", mode="truncate")
    st = _produce(clone)
    assert st["outcome"] == "complete" and st["exit_code"] == 0, st["message"]
    assert st["package"]["state_at_start"] == "finished_invalid"
    assert st["package"]["package_hash"] == original          # same evidence, same manifest
    q = list((PR.state_dir_for(clone) / "quarantine").glob("*package.json"))
    assert len(q) == 1 and q[0].stat().st_size > 0            # the damaged marker was kept, not deleted
    assert P.verify_package(clone)["audit_pass"]


def test_partial_temp_files_are_cleared_and_the_run_completes(clone):
    (clone / "package.json").unlink()                         # an unfinished package
    (clone / "facts.json.tmp").write_bytes(b'{"half')
    (clone / "render" / "hook" / "shot_render.json.tmp").write_bytes(b"{")
    st = _produce(clone)
    assert st["outcome"] == "complete"
    assert sorted(st["resumed"]["partial_writes_removed"]) == ["facts.json.tmp", "render/hook/shot_render.json.tmp"]
    assert not list(clone.rglob("*.tmp"))
    assert "partial_write_quarantined" in (PR.state_dir_for(clone) / "journal.jsonl").read_text()
    kept = sorted(p.name for p in (PR.state_dir_for(clone) / "quarantine").glob("*partial_*"))
    assert len(kept) == 2, kept                       # moved aside, never deleted


def test_corrupt_voice_wav_is_not_reused(clone):
    """A damaged line of speech is re-spoken; the rest is verified and kept."""
    before_voice = json.loads((clone / "voice" / "voice.json").read_text())["voice_hash"]
    FL.corrupt_file(clone / "voice" / "hook.01.wav", mode="empty")
    st = _produce(clone)
    assert st["outcome"] == "complete", st["message"]
    assert "voice" in st["performance"]["stages_ran"]
    assert json.loads((clone / "voice" / "voice.json").read_text())["voice_hash"] == before_voice
    assert (clone / "voice" / "hook.01.wav").stat().st_size > 1000


def test_stale_lineage_in_the_voice_document_is_not_reused(clone):
    """voice.json says it was made from a different narration: it is re-made, not trusted."""
    from ldyf.factory.util import seal
    doc = json.loads((clone / "voice" / "voice.json").read_text())
    doc["narration_hash"] = "f" * 64
    (clone / "voice" / "voice.json").write_text(json.dumps(seal(doc, "voice_hash"), indent=1))
    st = _produce(clone)
    assert st["outcome"] == "complete"
    assert "voice" in st["performance"]["stages_ran"]
    assert json.loads((clone / "voice" / "voice.json").read_text())["narration_hash"] != "f" * 64


def test_truncated_audio_document_forces_a_rebuild(clone):
    FL.corrupt_file(clone / "audio" / "audio.json", mode="truncate")
    st = _produce(clone)
    assert st["outcome"] == "complete"
    assert "audio" in st["performance"]["stages_ran"]


def test_a_locked_output_file_is_a_typed_refusal_and_recoverable(clone):
    """Locked output: facts.json is rewritten on every run and another program holds it with no
    sharing (nothing can replace or write it). The run stops with an environment error, the
    directory is left UNFINISHED (not looking finished), nothing is lost, and once the lock is
    released the same command completes."""
    target = clone / "facts.json"
    with winproc.ExclusiveHold(str(target)):
        # (a) a FINISHED package whose file is locked cannot even be verified: typed refusal and the
        #     package is not touched
        st0 = _produce(clone)
        assert st0["exit_code"] == 12 and st0["code"] in ("io_error", "output_not_writable"), st0["message"]
        assert (clone / "package.json").exists() and st0["package"]["state_at_end"] == "marked_finished"
        # (b) an UNFINISHED package whose file is locked fails on the write, and stays unfinished
        (clone / "package.json").unlink()
        st = _produce(clone)
        assert st["exit_code"] == EXIT_CODES["environment"] == 12, st["message"]
        assert st["code"] in ("write_failed", "io_error") and "facts.json" in st["message"]
        assert "permissions" in st["advice"] or "writable" in st["advice"]
        assert st["package"]["state_at_end"] == "unfinished_resumable"
        assert not (clone / "package.json").exists()
        assert not list(clone.rglob("*.tmp"))
        _assert_no_false_success(st)
    assert _produce(clone)["outcome"] == "complete"


def test_a_read_only_finished_package_is_confirmed_without_a_single_write(clone):
    """An archived, read-only copy: produce verifies it and reports already_complete; the
    package directory is not written (the run's own state lives beside it)."""
    before = _digest(clone)
    for p in clone.rglob("*"):
        if p.is_file():
            os.chmod(p, 0o444)
    try:
        st = _produce(clone)
        assert st["outcome"] == "already_complete" and st["exit_code"] == 0
        assert _digest(clone) == before
    finally:
        for p in clone.rglob("*"):
            if p.is_file():
                os.chmod(p, 0o666)


def test_a_file_held_open_by_another_program_does_not_fail_the_run(clone):
    (clone / "package.json").unlink()
    with open(clone / "timeline.json", "rb") as held:        # a scanner / indexer / viewer
        st = _produce(clone)
        _ = held.read(1)
    assert st["outcome"] == "complete", st["message"]


def test_a_failed_write_models_a_full_disk_and_leaves_the_package_resumable(clone, monkeypatch):
    (clone / "package.json").unlink()
    real = Path.write_bytes

    def full_disk(self, data):
        if self.name == "story.json.tmp":
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(self, data)

    monkeypatch.setattr(Path, "write_bytes", full_disk)
    st = _produce(clone)
    assert st["exit_code"] == 12 and st["code"] == "write_failed", st["message"]
    assert "story.json" in st["message"]
    assert not list(clone.rglob("*.tmp"))
    assert st["package"]["state_at_end"] == "unfinished_resumable"
    monkeypatch.setattr(Path, "write_bytes", real)
    assert _produce(clone)["outcome"] == "complete"


def test_dependency_vanishing_mid_run_is_reported_as_such(clone, monkeypatch):
    from ldyf.factory.assemble import AssemblyError
    # force a re-assembly, then lose ffmpeg between preflight and the stage
    (clone / "package.json").unlink()
    (clone / "assembly.json").unlink()
    monkeypatch.setattr(P.AS, "assemble", lambda *a, **k: (_ for _ in ()).throw(
        AssemblyError("no_ffmpeg", "ffmpeg is not installed")))
    st = _produce(clone)
    assert st["exit_code"] == 11 and st["code"] == "no_ffmpeg" and st["stage"] == "assemble"
    assert "ffmpeg" in st["advice"]
    assert st["package"]["state_at_end"] == "unfinished_resumable"
    _assert_no_false_success(st)


def test_a_brief_edited_while_the_run_is_in_progress_is_not_reported_as_success(clone, tmp_path, monkeypatch):
    (clone / "package.json").unlink()
    live = tmp_path / "live_brief.json"
    live.write_text(BRIEF_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    real = P.run_factory

    def edit_then_run(*a, **k):
        live.write_text(json.dumps(_brief_with(title="Edited while running")), encoding="utf-8")
        return real(*a, **k)

    monkeypatch.setattr(P, "run_factory", edit_then_run)
    st = PR.produce(live, clone, log=lambda s: None)
    assert st["exit_code"] == EXIT_CODES["brief_changed_during_run"] == 28
    assert st["code"] == "brief_changed_during_run"
    assert st["package"]["valid_for_snapshot"] is True
    assert "new --out" in st["advice"]
    # the package itself is valid for the brief the run STARTED with, and says so honestly
    assert P.verify_package(clone)["audit_pass"]
    snap = json.loads((PR.state_dir_for(clone) / "brief.snapshot.json").read_text())
    assert snap["title"] == "What happens when one street closes?"


def test_a_transient_editor_failure_is_retried_and_the_run_completes(clone, monkeypatch):
    from ldyf.factory.render import RenderError
    (clone / "package.json").unlink()
    real = P.run_factory
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RenderError("editor_unreachable", "remote execution dropped")
        return real(*a, **k)

    monkeypatch.setattr(P, "run_factory", flaky)
    st = _produce(clone)
    assert st["outcome"] == "complete" and st["attempts"] == 2
    assert '"event": "retry"' in (PR.state_dir_for(clone) / "journal.jsonl").read_text()


def test_a_persistent_failure_is_retried_a_bounded_number_of_times_then_reported(clone, monkeypatch):
    from ldyf.factory.render import RenderError
    (clone / "package.json").unlink()
    calls = {"n": 0}

    def down(*a, **k):
        calls["n"] += 1
        raise RenderError("editor_unreachable", "editor is gone")

    monkeypatch.setattr(P, "run_factory", down)
    st = _produce(clone)
    assert calls["n"] == 3                                   # first try + the two backoffs, no more
    assert st["exit_code"] == 11 and st["code"] == "editor_unreachable"
    _assert_no_false_success(st)


def test_a_dropped_editor_socket_is_a_dependency_failure_not_a_file_error(clone, monkeypatch):
    (clone / "package.json").unlink()
    calls = {"n": 0}

    def dropped(*a, **k):
        calls["n"] += 1
        raise ConnectionAbortedError(10053, "An established connection was aborted")

    monkeypatch.setattr(P, "run_factory", dropped)
    st = _produce(clone)
    assert calls["n"] == 3                                       # transient: retried, bounded
    assert st["exit_code"] == 11 and st["code"] == "editor_connection_lost"
    assert "Unreal editor" in st["advice"]


def test_non_transient_failures_are_never_retried(clone, monkeypatch):
    from ldyf.factory.audit import AuditError
    (clone / "package.json").unlink()
    calls = {"n": 0}

    def refuse(*a, **k):
        calls["n"] += 1
        raise AuditError("audit_failed", "a sentence is false")

    monkeypatch.setattr(P, "run_factory", refuse)
    st = _produce(clone)
    assert calls["n"] == 1 and st["exit_code"] == 26


def test_ctrl_c_is_reported_released_and_resumable(clone, monkeypatch):
    (clone / "package.json").unlink()

    def interrupted(*a, **k):
        raise KeyboardInterrupt()

    monkeypatch.setattr(P, "run_factory", interrupted)
    st = _produce(clone)
    assert st["exit_code"] == 30 and st["outcome"] == "interrupted"
    assert _released(PR.state_dir_for(clone))
    monkeypatch.undo()
    assert _produce(clone)["outcome"] == "complete"


def test_an_unexpected_exception_is_an_internal_error_not_a_success(clone, monkeypatch):
    (clone / "package.json").unlink()
    monkeypatch.setattr(P, "run_factory", lambda *a, **k: (_ for _ in ()).throw(ZeroDivisionError("bug")))
    st = _produce(clone)
    assert st["exit_code"] == 70 and st["exit_class"] == "internal_error"
    assert "ZeroDivisionError" in st["message"]
    assert _released(PR.state_dir_for(clone))


def test_a_package_that_fails_verification_after_the_build_is_not_published(clone, monkeypatch):
    (clone / "package.json").unlink()
    real = P.verify_package
    calls = {"n": 0}

    def flaky(pkg, **k):
        calls["n"] += 1
        if calls["n"] >= 1:
            raise P.PipelineError("package_changed", "changed episode.mp4")
        return real(pkg, **k)

    monkeypatch.setattr(P, "verify_package", flaky)
    # assess_package sees no package.json (partial), run builds, post-verify fails
    st = _produce(clone)
    assert st["exit_code"] == EXIT_CODES["verification_failed"]
    assert not (clone / "package.json").exists()              # not left claiming to be finished
    assert list((PR.state_dir_for(clone) / "quarantine").glob("*unverified"))
    _assert_no_false_success(st)


# ---------------------------------------------------------- process death + concurrency

def test_process_death_mid_run_leaves_an_unfinished_dir_and_resume_completes(clone):
    """The real thing: TerminateProcess on a child `produce` after the audio stage, with an
    episode that has to be re-assembled. No finally runs. The directory must not look finished;
    the next run takes over the dead run's lock and completes."""
    FL.corrupt_file(clone / "episode.mp4")
    r = FL.run_produce(BRIEF_PATH, clone, kill_when=FL.line_contains("[audio] "))
    assert r["killed"], r["stdout_tail"]
    assert not (clone / "package.json").exists()
    assert (PR.state_dir_for(clone) / "lock.json").exists()      # the dead run could not release it
    assert PR.read_status(clone)["run_in_progress"] is False
    r2 = FL.run_produce(BRIEF_PATH, clone)
    assert r2["returncode"] == 0, r2["stdout_tail"]
    st = FL.status_of(clone)
    assert st["outcome"] == "complete"
    assert st["resumed"]["recovered_stale_lock"] and st["resumed"]["previous_run_interrupted"]
    assert _released(PR.state_dir_for(clone))


def test_a_second_run_on_a_package_being_built_is_refused(clone):
    FL.corrupt_file(clone / "episode.mp4")                  # run A needs ~2.5 minutes of assembly
    import threading
    out = {}

    def run_a():
        out["a"] = FL.run_produce(BRIEF_PATH, clone)

    t = threading.Thread(target=run_a)
    t.start()
    try:
        deadline = __import__("time").time() + 120
        lock = PR.state_dir_for(clone) / "lock.json"
        while not lock.exists() and __import__("time").time() < deadline:
            __import__("time").sleep(0.2)
        assert lock.exists()
        __import__("time").sleep(5)
        b = FL.run_produce(BRIEF_PATH, clone, extra=("--json", "--quiet"))
        assert b["returncode"] == EXIT_CODES["already_running"] == 14, b["stdout_tail"]
        assert "already_running" in "\n".join(b["lines"])
    finally:
        t.join(timeout=900)
    assert out["a"]["returncode"] == 0                       # A was not disturbed
    assert P.verify_package(clone)["audit_pass"]


# ----------------------------------------------- engine-dependent: killed renderer, bad media

@pytest.fixture(scope="module")
def editor():
    if not (PR.REPO_ROOT / "LivingDioramaYF" / "LivingDioramaYF.uproject").exists():
        pytest.skip("engine tests run only from the live workspace (the MASTER does not ship the Unreal project)")
    if not _editor_up():
        pytest.skip("the Unreal editor is not running on this machine")


def test_an_incomplete_shot_left_by_a_killed_renderer_is_rendered_again(clone, editor):
    """Debris of a renderer killed mid-shot: a frames directory with part of the PNGs, a bake
    file, no sealed shot. The shot is rendered again from nothing; the other shots are reused."""
    shot = clone / "render" / "world"
    keep = {p.parent.name: p.read_bytes() for p in (clone / "render").glob("*/shot_render.json")
            if p.parent.name != "world"}
    (clone / "package.json").unlink()
    (shot / "shot_render.json").unlink()
    (shot / "segment.mp4").write_bytes(b"\x00\x00half an mp4")
    (shot / "frames").mkdir()
    for i in range(7):
        (shot / "frames" / f"frame_{i:04d}.png").write_bytes(b"\x89PNG partial")
    (shot / "sequence_bake.json").write_text("{}")
    (clone / "render" / "render.json").unlink()
    st = _produce(clone)
    assert st["outcome"] == "complete", st["message"]
    assert (shot / "shot_render.json").is_file() and not (shot / "frames").exists()
    for beat, data in keep.items():
        assert (clone / "render" / beat / "shot_render.json").read_bytes() == data, beat   # not re-rendered


def test_invalid_media_in_a_finished_shot_is_not_reused(clone, editor):
    shot = clone / "render" / "limits"
    FL.corrupt_file(shot / "segment.mp4", mode="truncate")
    st = _produce(clone)
    assert st["outcome"] == "complete", st["message"]
    assert "render" in st["performance"]["stages_ran"]
    assert P.verify_package(clone)["audit_pass"]


def test_a_brief_file_next_to_the_output_is_the_normal_layout_not_nesting(tmp_path):
    """Regression (found by the full-suite run): `episodes/my/brief.json` + `--out episodes/my/pkg`
    must be accepted; only an enclosing REAL package (manifest / sealed sim / state dir) is refused."""
    (tmp_path / "brief.json").write_text("{}")
    assert PR.output_path_problem(tmp_path / "pkg") is None
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "package.json").write_text("{}")
    assert "nested" in PR.output_path_problem(tmp_path / "pkg" / "child")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "brief.json").write_text("{}")
    (tmp_path / "other" / "sim").mkdir()
    assert "nested" in PR.output_path_problem(tmp_path / "other" / "child")


# ------------------------------------------------ red team lane 2 F4: prediction text vs direction

@pytest.mark.parametrize("text,direction,ok", [
    ("Car trips will take longer.", "increase", True),
    ("Car trips will take longer on average.", "increase", True),
    ("More car trips will be in the city.", "increase", False),                   # a COUNT, not the measured time
    ("Car trips will take no change.", "no_change", False),
    ("Car trips will take less time.", "decrease", True),
    ("Nothing will change; the average stays the same.", "no_change", False),      # 'nothing' is universal
    ("Car trips will stay the same.", "no_change", True),
    ("No change in car trips.", "no_change", True),
    ("Car trips will take less time.", "increase", False),                          # lane 2 'mis1'
    ("Car trips will take longer.", "decrease", False),
    ("Every trip will always be worse.", "increase", False),                        # lane 2 'inj2'
    ("Closing it always wastes every driver's time.", "increase", False),           # lane 2 'inj1'
    ("Trips will be longer and shorter.", "increase", False),                       # says both
    ("Something will happen.", "increase", False),                                  # says nothing
    ("Car trips will not take longer.", "increase", False),                         # final lane B: negation
    ("Car trips won't take longer.", "increase", False),
    ("Walkers will take longer.", "increase", False),                               # wrong subject
    ("Will car trips take longer?", "increase", False),                             # a question
    ("Car trips will take longer, or maybe not.", "increase", False),
    ("Car trips will take longer because the mayor lied.", "increase", False),      # a cause
    ("Car trips will take longer by 9 minutes.", "increase", False),                # a numeral
    ("Car trips will take longerа.", "increase", False),                       # look-alike letter
])
def test_the_spoken_guess_must_be_the_guess_that_is_judged(text, direction, ok):
    from ldyf.factory.brief import BriefError, normalise_brief
    raw = _brief_with(prediction={"text": text, "metric": "avg_duration_s", "direction": direction})
    if ok:
        assert normalise_brief(raw)["prediction"]["text"] == text
    else:
        with pytest.raises(BriefError) as e:
            normalise_brief(raw)
        assert e.value.code == "bad_prediction"


def test_the_shipped_briefs_still_normalise():
    from ldyf.factory.brief import normalise_brief
    for name in ("close_baker_avenue.json", "close_baker_avenue_contrarian.json"):
        normalise_brief(json.loads((BRIEF_PATH.parent / name).read_text(encoding="utf-8")))
