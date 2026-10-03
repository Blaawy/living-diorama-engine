"""Phase 5 red-team regressions: what `verify` accepts as a finished package.

Lane 2 forged packages whose manifest rows were recomputed (what anyone with write access can do) and
Phase 4's verify accepted them. Each test here makes ONE such forgery on a private copy of the real
package and requires a refusal by name. The copy is shared by the module; every test restores what it
touched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from ldyf.factory import FactoryError
from ldyf.factory import audit as AD
from ldyf.factory import mediacheck as MC
from ldyf.factory import pipeline as P
from ldyf.factory.util import doc_hash, seal, sha256_file

from .factory_support import FFMPEG, WINDOWS_TTS

pytestmark = pytest.mark.skipif(not (FFMPEG and WINDOWS_TTS), reason="needs ffmpeg and the speech engine")


@pytest.fixture(scope="module")
def pkg(factory_pkg, tmp_path_factory):
    dst = Path(tmp_path_factory.mktemp("vh")) / "pkg"
    shutil.copytree(factory_pkg, dst)
    return dst


@contextmanager
def touched(pkg: Path, *rels: str):
    """Back up the named files, let the test damage them, and put them back."""
    saved = {r: (pkg / r).read_bytes() for r in rels if (pkg / r).exists()}
    try:
        yield
    finally:
        for r, data in saved.items():
            (pkg / r).write_bytes(data)


def reseal_rows(pkg: Path) -> None:
    """The insider's move: recompute the sha256/bytes of every row, then the package seal. No audit is re-run."""
    m = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
    for r in m["files"]:
        r["sha256"] = sha256_file(pkg / r["file"])
        r["bytes"] = (pkg / r["file"]).stat().st_size
    m["package_hash"] = doc_hash(m, "package_hash")
    (pkg / "package.json").write_text(json.dumps(m, indent=1), encoding="utf-8")


def refused(pkg: Path, code: str | tuple[str, ...]) -> FactoryError:
    with pytest.raises(FactoryError) as e:
        P.verify_package(pkg)
    codes = (code,) if isinstance(code, str) else code
    assert e.value.code in codes, (e.value.code, e.value.message)
    return e.value


def test_the_genuine_package_verifies_and_says_what_it_covers(pkg):
    out = P.verify_package(pkg)
    v = out["verification"]
    assert v["level"] == "standard" and v["media"]["streams"]["streams"] == ["audio", "video"]
    assert v["media"]["stills_checked"] > 0
    assert "pixels of each rendered segment (Movie Render Queue is not reproducible)" in \
        v["coverage"]["attested_by_hash_only"]


# --------------------------------------------------------------- lane 2 F2: reviewer documents

@pytest.mark.parametrize("name,damage", [
    ("truth_audit.json", lambda d: d["counts"].update(sentences_refused=0, sentences=9999)),
    ("lineage.json", lambda d: d.update(links_ok=999)),
])
def test_a_forged_reviewer_document_with_a_recomputed_row_is_refused(pkg, name, damage):
    with touched(pkg, name, "package.json"):
        d = json.loads((pkg / name).read_text(encoding="utf-8"))
        damage(d)
        (pkg / name).write_text(json.dumps(d, indent=1), encoding="utf-8")
        reseal_rows(pkg)
        refused(pkg, ("reviewer_document_changed", "package_changed", "audit_changed"))


def test_altered_vtt_captions_with_a_recomputed_row_are_refused(pkg):
    with touched(pkg, "captions.vtt", "package.json"):
        t = (pkg / "captions.vtt").read_text(encoding="utf-8").replace("right", "wrong", 1)
        (pkg / "captions.vtt").write_text(t, encoding="utf-8")
        reseal_rows(pkg)
        refused(pkg, "reviewer_document_changed")


def test_a_swapped_still_is_refused(pkg):
    with touched(pkg, "render/hook/still_1.jpg", "package.json"):
        shutil.copy(pkg / "render" / "close" / "still_1.jpg", pkg / "render" / "hook" / "still_1.jpg")
        reseal_rows(pkg)
        refused(pkg, "still_changed")


# ---------------------------------------------------- lane 2 F3: manifest fields and duplicate rows

@pytest.mark.parametrize("patch", [
    {"seconds": 1.0}, {"beats": 99}, {"title": "FORGED TITLE"}, {"factory_version": "factory_v99"},
    {"review_first": ["nonexistent.mp4"]}, {"frames": 1}, {"brief_sha256": "f" * 64},
])
def test_a_forged_top_level_manifest_field_is_refused(pkg, patch):
    with touched(pkg, "package.json"):
        m = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
        m.update(patch)
        m["package_hash"] = doc_hash(m, "package_hash")
        (pkg / "package.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
        refused(pkg, "package_changed")


def test_forged_audit_counts_inside_the_manifest_are_refused(pkg):
    with touched(pkg, "package.json"):
        m = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
        m["truth_audit"]["sentences"] = 9999
        m["truth_audit"]["sentences_refused"] = 0
        m["package_hash"] = doc_hash(m, "package_hash")
        (pkg / "package.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
        refused(pkg, "package_changed")


@pytest.mark.parametrize("order", ["bad_first", "good_first"])
def test_a_duplicate_manifest_row_is_refused_in_either_order(pkg, order):
    with touched(pkg, "package.json"):
        m = json.loads((pkg / "package.json").read_text(encoding="utf-8"))
        good = next(r for r in m["files"] if r["file"] == "facts.json")
        bad = dict(good, sha256="0" * 64)
        m["files"] = [bad] + m["files"] if order == "bad_first" else m["files"] + [bad]
        m["package_hash"] = doc_hash(m, "package_hash")
        (pkg / "package.json").write_text(json.dumps(m, indent=1), encoding="utf-8")
        refused(pkg, "package_changed")


# ---------------------------------------------------------------- lane 2 F6, F9: hidden channels

def test_a_directory_junction_inside_the_package_is_refused(pkg, tmp_path):
    outside = tmp_path / "outside_render"
    with touched(pkg, "package.json"):
        shutil.move(str(pkg / "render"), str(outside))
        run = subprocess.run(["cmd", "/c", "mklink", "/J", str(pkg / "render"), str(outside)],
                             capture_output=True, text=True)
        try:
            assert run.returncode == 0, run.stderr
            with pytest.raises(FactoryError) as e:
                P.verify_package(pkg)
            assert e.value.code == "foreign_file"
        finally:
            os.rmdir(pkg / "render")                     # removes the junction only
            shutil.move(str(outside), str(pkg / "render"))


def test_a_hidden_alternate_data_stream_is_refused(pkg):
    with touched(pkg, "facts.json"):
        with open(str(pkg / "facts.json") + ":payload", "wb") as f:
            f.write(b"hidden")
        try:
            with pytest.raises(FactoryError) as e:
                P.verify_package(pkg)
            assert e.value.code == "foreign_file" and "stream" in e.value.message
        finally:
            (pkg / "facts.json").unlink()
    # `touched` restores the file; the stream went with the unlink


def test_a_payload_posing_as_a_sumo_console_log_is_refused(pkg):
    log = pkg / "sim" / "payload.sumo.log"
    log.write_bytes(os.urandom(4096))
    try:
        with pytest.raises(FactoryError) as e:
            P.verify_package(pkg)
        assert e.value.code == "foreign_file"
    finally:
        log.unlink()


# ------------------------------------------------------ lane 2 F5: a malformed sentence is a finding

@pytest.mark.parametrize("name,damage", [
    ("no_cites", lambda l: l.pop("cites")),
    ("null_cites", lambda l: l.update(cites=None)),
    ("no_checks", lambda l: l.pop("checks")),
    ("half_check", lambda l: l.update(checks=[{"left": 1}])),
])
def test_a_malformed_narration_line_is_reported_not_a_crash(pkg, name, damage):
    with touched(pkg, "narration.json"):
        d = json.loads((pkg / "narration.json").read_text(encoding="utf-8"))
        damage(d["lines"][3])
        (pkg / "narration.json").write_text(json.dumps(seal(d, "narration_hash"), indent=1), encoding="utf-8")
        brief = P.normalise_brief(json.loads((pkg / "brief.json").read_text(encoding="utf-8")))
        audit = AD.audit_episode(pkg, brief, P.load_world(brief["world"]), require_render=True)
        assert audit["pass"] is False and audit["failures"]


# ------------------------------------------------------------- lane 2 F1: media, in isolation

def _forge(path: Path, *, video: str = "testsrc2=s=640x360:r=24", audio: str = "sine=f=440:r=44100",
           seconds: float = 599.0, extra_stream: bool = False) -> Path:
    args = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", video + f":d={seconds}",
            "-f", "lavfi", "-i", audio + f":d={seconds}"]
    if extra_stream:
        args += ["-f", "lavfi", "-i", f"sine=f=880:r=44100:d={seconds}", "-map", "0:v", "-map", "1:a", "-map", "2:a"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)]
    subprocess.run(args, check=True)
    return path


def test_extra_streams_are_refused(pkg, tmp_path):
    f = _forge(tmp_path / "x.mp4", extra_stream=True, seconds=20.0)
    with pytest.raises(FactoryError) as e:
        MC.check_streams(f, 20.0)
    assert e.value.code == "bad_streams"


def test_audio_cut_short_is_refused(pkg, tmp_path):
    f = tmp_path / "short.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(pkg / "episode.mp4"), "-t", "30",
                    "-c", "copy", str(f)], check=True)
    with pytest.raises(FactoryError) as e:
        MC.check_streams(f, 599.0)
    assert e.value.code in ("audio_length", "bad_streams")


def test_a_sine_tone_is_not_the_sealed_mix(pkg, tmp_path):
    f = _forge(tmp_path / "sine.mp4", seconds=120.0)
    clip = tmp_path / "mix120.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(pkg / "audio" / "episode.wav"),
                    "-t", "120", str(clip)], check=True)
    with pytest.raises(FactoryError) as e:
        MC.check_sound(f, clip)
    assert e.value.code == "sound_mismatch"


def test_the_genuine_sound_matches_its_mix(pkg, tmp_path):
    clip_ep, clip_mix = tmp_path / "ep120.mp4", tmp_path / "mix120.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(pkg / "episode.mp4"), "-t", "120",
                    "-c", "copy", str(clip_ep)], check=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(pkg / "audio" / "episode.wav"),
                    "-t", "120", str(clip_mix)], check=True)
    assert MC.check_sound(clip_ep, clip_mix)["windows_off"] == 0


def test_a_picture_swap_between_segments_is_refused(pkg):
    """Lane 2's sharp attack: the walkers_before picture put into the walkers_after shot."""
    tl = json.loads((pkg / "timeline.json").read_text(encoding="utf-8"))
    only = {**tl, "beats": [b for b in tl["beats"] if b["id"] == "walkers_after"]}
    with touched(pkg, "render/walkers_after/segment.mp4"):
        assert MC.check_picture(pkg, only)["ssim_min"] > 0.8          # genuine: passes
        shutil.copy(pkg / "render" / "walkers_before" / "segment.mp4", pkg / "render" / "walkers_after" / "segment.mp4")
        with pytest.raises(FactoryError) as e:
            MC.check_picture(pkg, only)
        assert e.value.code == "picture_mismatch"


def test_a_substituted_voice_recording_is_not_the_audited_sentence(pkg, tmp_path):
    brief = P.normalise_brief(json.loads((pkg / "brief.json").read_text(encoding="utf-8")))
    narr = json.loads((pkg / "narration.json").read_text(encoding="utf-8"))
    voice = json.loads((pkg / "voice" / "voice.json").read_text(encoding="utf-8"))
    tl = json.loads((pkg / "timeline.json").read_text(encoding="utf-8"))
    audio = json.loads((pkg / "audio" / "audio.json").read_text(encoding="utf-8"))
    assert MC.check_speech_and_mix(pkg, brief, narr, voice, tl, audio, tmp_path / "ok")["mix"] == "identical"
    row = voice["lines"][3]
    voice2 = json.loads(json.dumps(voice))
    voice2["lines"][3]["sha256"] = "0" * 64                           # the sealed record says another recording
    with pytest.raises(FactoryError) as e:
        MC.check_speech_and_mix(pkg, brief, narr, voice2, tl, audio, tmp_path / "bad")
    assert e.value.code == "voice_not_reproduced", row


# ------------------------------------------------------- lane 2 F8: the whole simulation is re-derived

def test_resimulate_notices_a_doctored_agents_document(pkg, tmp_path):
    brief = P.normalise_brief(json.loads((pkg / "brief.json").read_text(encoding="utf-8")))
    world = P.load_world(brief["world"])
    with touched(pkg, "sim/agents_ruled.json"):
        text = (pkg / "sim" / "agents_ruled.json").read_text(encoding="utf-8")
        (pkg / "sim" / "agents_ruled.json").write_text(text.replace('"t": 30', '"t": 37', 1) if '"t": 30' in text
                                                       else text + " ", encoding="utf-8")
        with pytest.raises(FactoryError) as e:
            P.resimulate(pkg, brief, world, tmp_path / "rs", repeats=False)
        assert e.value.code == "simulation_not_reproduced" and "agents_ruled.json" in e.value.message
