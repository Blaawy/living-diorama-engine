"""Phase 5 FINAL red-team pass (lane A product boundary, lane B truth/media): regressions.

Each test reproduces one finding of EVIDENCE/PHASE_05/redteam_final_A_product_boundary.md or
redteam_final_B_truth_media.md and requires the refusal or the safe outcome.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from ldyf.factory import FactoryError
from ldyf.factory import mediacheck as MC
from ldyf.factory import pipeline as P
from ldyf.factory import production as PR
from ldyf.factory import winproc
from ldyf.factory.production import EXIT_CODES

from .factory_support import BRIEF_PATH, FFMPEG, WINDOWS_TTS

pytestmark = pytest.mark.skipif(not (FFMPEG and WINDOWS_TTS), reason="needs ffmpeg and the speech engine")


@pytest.fixture
def clone(factory_pkg, tmp_path_factory):
    dst = Path(tmp_path_factory.mktemp("fr")) / "pkg"
    shutil.copytree(factory_pkg, dst)
    return dst


def _produce(pkg, **kw):
    kw.setdefault("log", lambda s: None)
    kw.setdefault("retry_backoff_s", (0.0, 0.0))
    return PR.produce(BRIEF_PATH, pkg, **kw)


# =============================================================== lane A

def test_status_file_cannot_point_into_the_package_the_state_dir_or_the_brief(clone, tmp_path):
    brief_copy = tmp_path / "my_brief.json"
    brief_copy.write_text(BRIEF_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    before = (clone / "brief.json").read_bytes()
    state = PR.state_dir_for(clone)
    for target, why in ((clone / "status.json", "inside the package"),
                        (clone / "brief.json", "the package brief"),
                        (state / "anything.json", "inside the state dir"),
                        (brief_copy, "the user's own brief")):
        st = PR.produce(brief_copy, clone, status_path=target, log=lambda s: None)
        assert st["exit_code"] == 12 and st["code"] == "bad_status_path", why
    assert (clone / "brief.json").read_bytes() == before
    assert not (clone / "status.json").exists()
    assert "outcome" not in json.loads(brief_copy.read_text(encoding="utf-8")) and "schema_version" in \
        json.loads(brief_copy.read_text(encoding="utf-8"))
    assert P.verify_package(clone)["audit_pass"]                  # the package was not polluted


def test_the_natural_out_plus_status_file_in_out_is_refused_before_building(tmp_path):
    out = tmp_path / "ep"
    st = PR.produce(BRIEF_PATH, out, status_path=out / "status.json", log=lambda s: None)
    assert st["code"] == "bad_status_path" and not out.exists()


def test_a_live_run_is_visible_to_status_and_a_refused_second_run_leaves_its_files_alone(tmp_path):
    state = tmp_path / "ep.production"
    state.mkdir()
    j = PR.Journal(state / "journal.jsonl", "live")
    PR.acquire_lock(state, "live", j)
    try:
        assert PR.lock_is_held(state)
        shown = PR.read_status(tmp_path / "ep")
        assert shown["run_in_progress"] is True and shown["lock"]["run"] == "live"
        marker = {"outcome": "in_progress", "run_id": "live"}
        (state / "final_status.json").write_text(json.dumps(marker), encoding="utf-8")
        status_file = tmp_path / "s.json"
        status_file.write_text(json.dumps(marker), encoding="utf-8")
        st = PR.produce(BRIEF_PATH, tmp_path / "ep", status_path=status_file, log=lambda s: None)
        assert st["exit_code"] == 14
        assert json.loads((state / "final_status.json").read_text()) == marker
        assert json.loads(status_file.read_text()) == marker
    finally:
        PR.release_lock(state, "live")
    assert not PR.lock_is_held(state)


@pytest.mark.parametrize("name", ["CON", "con", "PRN", "AUX", "NUL", "NUL.txt", "COM1", "LPT1", "COM9.log",
                                  "ep.", "ep ", "a<b", "a|b", "q?"])
def test_windows_reserved_and_aliased_names_are_refused(tmp_path, name):
    assert PR.output_path_problem(tmp_path / name), name


def test_a_reserved_name_deeper_in_the_path_is_refused_too(tmp_path):
    assert PR.output_path_problem(tmp_path / "AUX" / "ep")


def test_file_manager_droppings_are_set_aside_not_adopted_or_fatal(clone):
    (clone / "package.json").unlink()
    (clone / "render" / "Thumbs.db").write_bytes(b"thumbs")
    (clone / "desktop.ini").write_text("[.ShellClassInfo]")
    st = _produce(clone)
    assert st["outcome"] == "complete", st["message"]
    assert sorted(st["resumed"]["os_junk_quarantined"]) == ["desktop.ini", "render/Thumbs.db"]
    assert not (clone / "render" / "Thumbs.db").exists()
    kept = [p.name for p in (PR.state_dir_for(clone) / "quarantine").glob("*junk_*")]
    assert len(kept) == 2


def test_a_summary_with_non_ascii_letters_in_the_path_does_not_crash_the_cli(tmp_path):
    out = tmp_path / "журнал_pkg"
    run = subprocess.run([sys.executable, "-m", "ldyf.factory", "produce", "--brief", str(tmp_path / "missing.json"),
                          "--out", str(out), "--quiet"], capture_output=True, cwd=str(PR.REPO_ROOT))
    assert run.returncode == 10, run.stderr[-300:]


def test_the_orphan_reaper_matches_a_directory_not_a_prefix(monkeypatch, tmp_path):
    killed = []
    pkg = tmp_path / "pkgA"
    rows = [{"pid": 1, "ppid": 424242, "command_line": f'sumo --fcd-output "{tmp_path}\\pkgA2\\sim\\x.xml"'},
            {"pid": 2, "ppid": 424242, "command_line": f'sumo --fcd-output "{tmp_path}\\pkgA\\sim\\x.xml"'}]
    monkeypatch.setattr(winproc, "find_processes", lambda name: rows)
    monkeypatch.setattr(winproc, "process_identity", lambda pid: None)
    monkeypatch.setattr(winproc, "kill_pid", lambda pid: killed.append(pid) or True)
    PR.reap_orphans(pkg, PR.Journal(tmp_path / "j.jsonl", "r"))
    assert killed == [2]


def test_doctor_creates_nothing_and_judges_the_directory_like_produce(tmp_path_factory, clone):
    tmp_path = Path(tmp_path_factory.mktemp("d"))
    deep = tmp_path / "a" / "b" / "ep"
    res = PR.doctor(BRIEF_PATH, deep, render=False)
    assert not (tmp_path / "a").exists() and not PR.state_dir_for(deep).exists()
    assert res["ok"] is True
    foreign = tmp_path / "docs"
    foreign.mkdir()
    (foreign / "thesis.docx").write_text("x")
    assert PR.doctor(BRIEF_PATH, foreign, render=False)["ok"] is False
    other = tmp_path / "other.json"
    raw = json.loads(BRIEF_PATH.read_text(encoding="utf-8"))
    raw.update(episode_number=5, title="Another episode")
    other.write_text(json.dumps(raw), encoding="utf-8")
    assert PR.doctor(other, clone, render=False)["ok"] is False


def test_status_exit_codes_say_what_happened(clone, tmp_path):
    run = lambda *a: subprocess.run([sys.executable, "-m", "ldyf.factory", *a], capture_output=True, text=True,  # noqa: E731
                                    cwd=str(PR.REPO_ROOT))
    assert run("status", "--out", str(tmp_path / "never_built")).returncode == 1
    _produce(clone)
    assert run("status", "--out", str(clone)).returncode == 0
    PR.produce(tmp_path / "missing.json", clone, log=lambda s: None)        # a failed run is now the last run
    assert run("status", "--out", str(clone)).returncode == 10


def test_a_state_directory_that_is_a_junction_is_refused(tmp_path):
    inside = tmp_path / "elsewhere"
    inside.mkdir()
    pkg = tmp_path / "ep"
    state = PR.state_dir_for(pkg)
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(state), str(inside)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    try:
        st = PR.produce(BRIEF_PATH, pkg, log=lambda s: None)
        assert st["exit_code"] == 12 and st["code"] == "bad_output_path"
        assert not list(inside.iterdir())
    finally:
        os.rmdir(state)


def test_quarantine_names_stay_short_for_long_files(tmp_path):
    state = tmp_path / "s"
    state.mkdir()
    src = tmp_path / "f.tmp"
    src.write_text("x")
    name = PR.quarantine(state, src, "partial_" + "d__" * 40 + "x.tmp", PR.Journal(state / "j.jsonl", "r"))
    assert name is not None and len(name) < 100 and (state / "quarantine" / name).is_file()


def test_a_failed_deep_check_reports_no_success_facts(clone, monkeypatch):
    real = P.verify_package

    def deep_refuses(pkg, **k):
        if k.get("deep"):
            raise P.PipelineError("sound_mismatch", "forged")
        return real(pkg, **k)

    monkeypatch.setattr(P, "verify_package", deep_refuses)
    st = _produce(clone, deep=True)
    assert st["exit_code"] == EXIT_CODES["verification_failed"]
    for k in ("package_hash", "review_first", "episode_sha256", "seconds"):
        assert k not in st["package"], k
    assert (clone / "package.json").exists()          # a package that passed standard is not torn down by deep


# =============================================================== lane B

@pytest.fixture(scope="module")
def pkg(factory_pkg, tmp_path_factory):
    dst = Path(tmp_path_factory.mktemp("frb")) / "pkg"
    shutil.copytree(factory_pkg, dst)
    return dst


def _reseal_rows(pkg: Path) -> None:
    from ldyf.factory.util import doc_hash, sha256_file
    m = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
    for r in m["files"]:
        r["sha256"] = sha256_file(pkg / r["file"])
        r["bytes"] = (pkg / r["file"]).stat().st_size
    m["package_hash"] = doc_hash(m, "package_hash")
    (pkg / "package.json").write_text(json.dumps(m, indent=1), encoding="utf-8")


class touched:
    def __init__(self, pkg: Path, *rels: str):
        self.pkg, self.saved = pkg, {r: (pkg / r).read_bytes() for r in rels}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for r, data in self.saved.items():
            (self.pkg / r).write_bytes(data)


def test_duplicate_json_keys_in_a_reviewer_document_are_refused(pkg):
    with touched(pkg, "truth_audit.json", "package.json"):
        t = (pkg / "truth_audit.json").read_text(encoding="utf-8")
        forged = t.replace('"pass": true', '"pass": "REFUSED: this package is forged", "pass": true', 1)
        assert forged != t
        (pkg / "truth_audit.json").write_text(forged, encoding="utf-8")
        _reseal_rows(pkg)
        with pytest.raises(FactoryError):
            P.verify_package(pkg)


def test_an_empty_or_unlisted_directory_is_refused(pkg):
    d = pkg / "ZZ_hidden_notes_directory"
    d.mkdir()
    try:
        with pytest.raises(FactoryError) as e:
            P.verify_package(pkg)
        assert e.value.code == "package_changed" and "directory" in e.value.message
    finally:
        d.rmdir()


def test_a_sumo_log_payload_is_bounded(pkg):
    log = pkg / "sim" / "baseline.sumo.log"
    with touched(pkg, "sim/baseline.sumo.log"):
        log.write_bytes(log.read_bytes() + os.urandom(3 * 1024 * 1024))
        with pytest.raises(FactoryError) as e:
            P.verify_package(pkg)
        assert e.value.code == "foreign_file"


def test_a_replaced_contact_sheet_is_refused(pkg, tmp_path):
    with touched(pkg, "contact_sheet.jpg", "package.json"):
        subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "color=c=green:s=2400x1350", "-frames:v", "1", str(pkg / "contact_sheet.jpg")], check=True)
        _reseal_rows(pkg)
        with pytest.raises(FactoryError) as e:
            P.verify_package(pkg)
        assert e.value.code == "contact_sheet_changed"


def test_undecodable_caption_bytes_are_a_typed_refusal_not_a_traceback(pkg):
    with touched(pkg, "captions.srt", "package.json"):
        (pkg / "captions.srt").write_bytes(b"\xff\xfe\x00 not text")
        _reseal_rows(pkg)
        with pytest.raises(FactoryError):
            P.verify_package(pkg)


def test_a_stereo_track_hiding_a_second_channel_is_refused(tmp_path):
    f = tmp_path / "stereo.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=320x180:r=24:d=20", "-f", "lavfi", "-i", "sine=f=440:r=22050:d=20", "-ac", "2",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(f)], check=True)
    with pytest.raises(FactoryError) as e:
        MC.check_streams(f, 20.0)
    assert e.value.code == "bad_streams" and "channel" in e.value.message


def test_a_few_seconds_of_different_sound_are_refused(pkg, tmp_path):
    """The old allowance let ~1 % of the episode (about 6 s) say anything at all."""
    ep, mix = tmp_path / "ep60.mp4", tmp_path / "mix60.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(pkg / "episode.mp4"),
                    "-t", "60", "-c", "copy", str(ep)], check=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(pkg / "audio" / "episode.wav"),
                    "-t", "60", str(mix)], check=True)
    assert MC.check_sound(ep, mix)["windows_off"] == 0
    cut = tmp_path / "cut.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(ep), "-c:v", "copy",
                    "-af", "volume=enable='between(t,3,8)':volume=0", "-c:a", "aac", str(cut)], check=True)
    with pytest.raises(FactoryError) as e:
        MC.check_sound(cut, mix)
    assert e.value.code == "sound_mismatch"


def test_deep_speech_check_cannot_be_switched_off_from_inside_the_package(pkg, tmp_path):
    brief = P.normalise_brief(json.loads((pkg / "brief.json").read_text(encoding="utf-8")))
    narr = json.loads((pkg / "narration.json").read_text(encoding="utf-8"))
    voice = json.loads((pkg / "voice" / "voice.json").read_text(encoding="utf-8"))
    tl = json.loads((pkg / "timeline.json").read_text(encoding="utf-8"))
    audio = json.loads((pkg / "audio" / "audio.json").read_text(encoding="utf-8"))
    forged = json.loads(json.dumps(voice))
    forged["lines"][2]["sha256"] = "0" * 64
    forged["engine"]["voice_info"] = "Some Other Engine|en-GB|Male|Adult"      # the insider's escape hatch
    with pytest.raises(FactoryError) as e:
        MC.check_speech_and_mix(pkg, brief, narr, forged, tl, audio, tmp_path / "x")
    assert e.value.code == "voice_not_reproduced"


def test_deep_refuses_an_episode_that_is_not_the_one_the_segments_and_mix_give(pkg, tmp_path):
    tl = json.loads((pkg / "timeline.json").read_text(encoding="utf-8"))
    with touched(pkg, "episode.mp4"):
        subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"testsrc2=s=640x360:r=24:d=599", "-i", str(pkg / "audio" / "episode.wav"), "-c:v", "libx264",
                        "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(pkg / "episode.mp4")], check=True)
        with pytest.raises(FactoryError) as e:
            MC.check_reassembly(pkg, tl, tmp_path)
        assert e.value.code == "episode_not_reproduced"
    assert MC.check_reassembly(pkg, tl, tmp_path / "again")["episode"] == "identical"


# ===================================================== closure re-test of lane A (new findings)

def test_a_refused_out_path_never_writes_the_status_over_the_users_brief(tmp_path):
    brief = tmp_path / "mybrief.json"
    brief.write_text(BRIEF_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    before = brief.read_bytes()
    st = PR.produce(brief, tmp_path / "CON", status_path=brief, log=lambda s: None)
    assert st["exit_code"] == 12
    assert brief.read_bytes() == before
    inside = tmp_path / "elsewhere"
    inside.mkdir()
    pkg = tmp_path / "ep"
    state = PR.state_dir_for(pkg)
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(state), str(inside)], capture_output=True, text=True)
    assert r.returncode == 0
    try:
        st = PR.produce(brief, pkg, status_path=brief, log=lambda s: None)
        assert st["exit_code"] == 12 and brief.read_bytes() == before
    finally:
        os.rmdir(state)


@pytest.mark.parametrize("name", ["story.json", "truth_audit.json", "narration.json", "final_status.json",
                                  "owner.json", "journal.jsonl"])
def test_status_file_cannot_carry_a_package_or_run_state_file_name(tmp_path, name):
    out = tmp_path / "ep"
    assert PR.status_path_problem(tmp_path / "x" / name, out, PR.state_dir_for(out), tmp_path / "b.json")


@pytest.mark.parametrize("name", ["COM¹", "LPT²", "CLOCK$"])
def test_the_remaining_reserved_names_are_refused(tmp_path, name):
    assert PR.output_path_problem(tmp_path / name)


def test_polling_the_lock_cannot_make_a_real_run_lose_it(tmp_path):
    import threading
    state = tmp_path / "ep.production"
    state.mkdir()
    stop = threading.Event()

    def poller():
        while not stop.is_set():
            PR.lock_is_held(state)

    t = threading.Thread(target=poller, daemon=True)
    t.start()
    try:
        lost = 0
        for i in range(150):
            try:
                PR.acquire_lock(state, f"r{i}", PR.Journal(state / "j.jsonl", f"r{i}"))
                PR.release_lock(state, f"r{i}")
            except PR.ProductionError:
                lost += 1
        assert lost == 0
    finally:
        stop.set()
        t.join(timeout=5)


def test_doctor_exit_code_names_the_kind_of_failure(tmp_path):
    run = lambda *a: subprocess.run([sys.executable, "-m", "ldyf.factory", "doctor", *a], capture_output=True,  # noqa: E731
                                    text=True, cwd=str(PR.REPO_ROOT))
    assert run("--brief", str(tmp_path / "nope.json"), "--out", str(tmp_path / "ep"), "--no-render").returncode == 10
    assert run("--brief", str(BRIEF_PATH), "--out", str(tmp_path / "CON"), "--no-render").returncode == 12
    foreign = tmp_path / "docs"
    foreign.mkdir()
    (foreign / "a.txt").write_text("x")
    assert run("--brief", str(BRIEF_PATH), "--out", str(foreign), "--no-render").returncode == 13


def test_a_desktop_ini_in_a_finished_package_does_not_unfinish_it(clone):
    (clone / "desktop.ini").write_text("[.ShellClassInfo]")
    st = _produce(clone)
    assert st["outcome"] == "already_complete", st.get("message")
    assert not (clone / "desktop.ini").exists()


# ===================================================== closure re-test of lane B (remaining findings)

def test_sumo_logs_are_two_named_files_per_run_and_bounded(pkg):
    extra = pkg / "sim" / "zz_second.sumo.log"
    extra.write_bytes(b"Loading net-file from 'x' ... done\n" * 10)
    try:
        with pytest.raises(FactoryError) as e:
            P.verify_package(pkg)
        assert e.value.code == "foreign_file" and "SUMO console logs" in e.value.message
    finally:
        extra.unlink()
    log = pkg / "sim" / "baseline.sumo.log"
    with touched(pkg, "sim/baseline.sumo.log"):
        log.write_bytes(log.read_bytes()[:1000] + b"A" * (2 * 1024 * 1024))
        with pytest.raises(FactoryError) as e:
            P.verify_package(pkg)
        assert e.value.code == "foreign_file"


def test_a_blacked_out_tile_of_the_contact_sheet_is_refused(pkg):
    """The sheet's global SSIM moves by under 0.02 for one tile; its own tile moves by tens of levels."""
    with touched(pkg, "contact_sheet.jpg", "package.json"):
        subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(pkg / "contact_sheet.jpg"),
                        "-vf", "drawbox=x=480:y=0:w=480:h=270:color=black:t=fill", "-q:v", "3",
                        str(pkg / "contact_sheet.jpg")], check=True)
        _reseal_rows(pkg)
        with pytest.raises(FactoryError) as e:
            P.verify_package(pkg)
        assert e.value.code == "contact_sheet_changed"


def test_an_engine_measurement_must_agree_with_the_planner_and_the_shots_requirement():
    shot = {"subjects": {"uids": list("abcdefghijklmnop")}, "subjects_visible_min": 10, "subjects_visible_max": 12,
            "require": {"fraction": 0.6, "min_visible": 1}}
    shots = {"shots": {"b": shot}}
    ok = {"shots": {"b": {"engine_subjects_visible_min": 10, "engine_subjects_visible_max": 12}}}
    assert MC.check_engine_plausibility(shots, ok) == 1
    for lo, hi in ((0, 0), (0, 1), (2, 3), (13, 16)):                     # deflated (the 'none of them' claim) and inflated
        bad = {"shots": {"b": {"engine_subjects_visible_min": lo, "engine_subjects_visible_max": hi}}}
        with pytest.raises(FactoryError) as e:
            MC.check_engine_plausibility(shots, bad)
        assert e.value.code == "engine_measurement_implausible", (lo, hi)
    absence = {"shots": {"b": {**shot, "subjects_visible_min": 0, "subjects_visible_max": 0, "require": {"max_visible": 0}}}}
    seen = {"shots": {"b": {"engine_subjects_visible_min": 0, "engine_subjects_visible_max": 2}}}
    with pytest.raises(FactoryError):
        MC.check_engine_plausibility(absence, seen)
