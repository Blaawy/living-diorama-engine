"""Phase 4 factory: voice, sound policy, render bookkeeping, assembly, truth audit, resume.

These tests attack a REAL episode. Two packages are used:

* the finished package the factory built (`factory_pkg`, read-only; tests that
  need the rendered episode skip when it is not complete);
* a PLANNED package (`planned_pkg`): the same sealed simulations taken through
  the real pipeline up to the sound track, without Unreal. Adversarial tests
  clone it with hard links (instant) and damage the clone.

The adversarial gate of the brief is covered here end to end, through the
truth audit: missing evidence, corrupt record, conflicting facts, a narration
that overclaims, stale lineage at every link, a camera that no longer holds
its subject, an interrupted render.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from ldyf.factory import FactoryError
from ldyf.factory import assemble as AS
from ldyf.factory import audio as AU
from ldyf.factory import audit as AD
from ldyf.factory import camera as C
from ldyf.factory import narration as N
from ldyf.factory import pipeline as P
from ldyf.factory import render as R
from ldyf.factory import simulate as SIM
from ldyf.factory import timeline as T
from ldyf.factory import voice as V
from ldyf.factory.util import seal, sha256_file, write_json

from .factory_support import BRIEF_PATH, FFMPEG, WINDOWS_TTS, clone, dump, load


#: The sealed Phase 3 agent-episode records. The factory's own simulation of the
#: same world, with drivers not rerouting, must reproduce them byte for byte.
PHASE3_FRAMES = {"baseline": "16382273da321569e5b00fc317d464fe19d62379c344f62db0048fa5ce19578e",
                 "ruled": "b67afe3cf248a8b4c19d7a202ffc9dd4a5b93b986da19e7cb11e113aaffc5e70"}


def replace_json(path: Path, doc) -> None:
    path.unlink()
    dump(path, doc)


def replace_bytes(path: Path, data: bytes) -> None:
    path.unlink()
    path.write_bytes(data)


def codes(report) -> set[str]:
    return {f["code"] for f in report["failures"]}


# --- voice ---------------------------------------------------------------------------

@pytest.mark.skipif(not WINDOWS_TTS, reason="needs the local Windows voice")
def test_voice_refuses_a_voice_that_is_not_installed(tmp_path):
    """A brief naming a voice this machine lacks must stop, not fall back to another."""
    with pytest.raises(V.VoiceError) as err:
        V.synthesise([{"id": "a", "text": "Hello."}], tmp_path, voice="No Such Voice", rate=0,
                     narration_hash="x")
    assert err.value.code == "no_voice"


@pytest.mark.skipif(not WINDOWS_TTS, reason="needs the local Windows voice")
def test_voice_is_byte_repeatable_and_sealed(tmp_path, factory_brief):
    """The same sentence, voice and rate give the same bytes: the sound track is a function
    of the narration, so a re-run cannot quietly change what is said."""
    lines = [{"id": "a", "text": "This is Baker Avenue."}, {"id": "b", "text": "Only 12 cars."}]
    docs = [V.synthesise(lines, tmp_path / str(i), voice=factory_brief["voice"],
                         rate=factory_brief["voice_rate"], narration_hash="n") for i in range(2)]
    assert [r["sha256"] for r in docs[0]["lines"]] == [r["sha256"] for r in docs[1]["lines"]]
    assert docs[0]["voice_hash"] == docs[1]["voice_hash"]
    assert all(r["seconds"] > 0.3 for r in docs[0]["lines"])
    assert docs[0]["engine"]["network"] is False and docs[0]["engine"]["runtime_model"] is False
    V.verify_voice(docs[0], tmp_path / "0")


def test_voice_refuses_empty_and_duplicate_lines(tmp_path):
    with pytest.raises(V.VoiceError) as err:
        V.synthesise([], tmp_path, voice="x", rate=0, narration_hash="n")
    assert err.value.code == "nothing_to_say"
    with pytest.raises(V.VoiceError) as err:
        V.synthesise([{"id": "a", "text": "x"}, {"id": "a", "text": "y"}], tmp_path, voice="x",
                     rate=0, narration_hash="n")
    assert err.value.code == "duplicate_line"


def test_wav_seconds_refuses_what_is_not_a_wave(tmp_path):
    bad = tmp_path / "x.wav"
    bad.write_bytes(b"not audio")
    with pytest.raises(V.VoiceError) as err:
        V.wav_seconds(bad)
    assert err.value.code == "bad_audio"


def test_a_swapped_or_missing_spoken_line_is_refused(planned_pkg, tmp_path):
    """The audio that is played must be the audio that was sealed."""
    vd = clone(planned_pkg / "voice", tmp_path / "voice")
    doc = V.load_voice(vd / "voice.json")
    a, b = vd / doc["lines"][0]["file"], vd / doc["lines"][1]["file"]
    replace_bytes(a, b.read_bytes())
    with pytest.raises(V.VoiceError) as err:
        V.load_voice(vd / "voice.json")
    assert err.value.code == "corrupt"
    a.unlink()
    with pytest.raises(V.VoiceError) as err:
        V.load_voice(vd / "voice.json")
    assert err.value.code == "missing"


# --- sound policy (gate G) -------------------------------------------------------------

def _audio_clone(planned_pkg, tmp_path):
    ad = clone(planned_pkg / "audio", tmp_path / "audio")
    vd = clone(planned_pkg / "voice", tmp_path / "voice")
    return AU.load_audio(ad / "audio.json"), ad, vd


def test_the_real_sound_track_obeys_the_policy(planned_pkg):
    doc = AU.load_audio(planned_pkg / "audio" / "audio.json")
    AU.validate_audio_policy(doc, planned_pkg / "audio", planned_pkg / "voice")
    assert doc["policy"]["external_assets"] == []
    assert {s["kind"] for s in doc["sources"]} <= set(AU.ALLOWED_KINDS)
    assert all(s["licence"].startswith("none: generated") for s in doc["sources"])
    spoken = [s for s in doc["sources"] if s["kind"] == "synthesised_speech"]
    assert len(spoken) == len(V.load_voice(planned_pkg / "voice" / "voice.json")["lines"])


@pytest.mark.parametrize("name", ["song.mp3", "sting.WAV", "loop.ogg", "bed2.flac"])
def test_an_audio_file_the_manifest_does_not_list_fails_the_episode(planned_pkg, tmp_path, name):
    """A music file dropped beside the sound track is a policy violation even if nothing uses it."""
    doc, ad, vd = _audio_clone(planned_pkg, tmp_path)
    (ad / name).write_bytes(b"RIFFxxxx")
    with pytest.raises(AU.AudioError) as err:
        AU.validate_audio_policy(doc, ad, vd)
    assert err.value.code == "policy_violation"


@pytest.mark.parametrize("change", [
    lambda d: d["sources"][0].__setitem__("kind", "licensed_music"),
    lambda d: d["sources"][0].__setitem__("licence", "CC-BY 4.0"),
    lambda d: d["policy"].__setitem__("external_assets", ["track.mp3"]),
])
def test_a_source_the_policy_does_not_allow_fails_even_when_sealed(planned_pkg, tmp_path, change):
    doc, ad, vd = _audio_clone(planned_pkg, tmp_path)
    change(doc)
    doc = seal({**doc, "audio_hash": ""}, "audio_hash")
    with pytest.raises(AU.AudioError) as err:
        AU.validate_audio_policy(doc, ad, vd)
    assert err.value.code == "policy_violation"


def test_a_changed_mix_or_a_changed_manifest_is_refused(planned_pkg, tmp_path):
    doc, ad, vd = _audio_clone(planned_pkg, tmp_path)
    replace_bytes(ad / "episode.wav", (planned_pkg / "audio" / "episode.wav").read_bytes()[:-2] + b"\x01\x02")
    with pytest.raises(AU.AudioError) as err:
        AU.validate_audio_policy(doc, ad, vd)
    assert err.value.code == "corrupt"
    doc2, ad2, vd2 = _audio_clone(planned_pkg, tmp_path / "b")
    doc2["seconds"] = 1.0
    with pytest.raises(AU.AudioError) as err:
        AU.validate_audio_policy(doc2, ad2, vd2)
    assert err.value.code == "corrupt"


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
def test_the_sound_track_is_rebuilt_byte_for_byte(planned_pkg, tmp_path):
    """Generated tones and the mix are deterministic: same timeline, same bytes."""
    timeline = T.load_timeline(planned_pkg / "timeline.json")
    voice = V.load_voice(planned_pkg / "voice" / "voice.json")
    sealed = AU.load_audio(planned_pkg / "audio" / "audio.json")
    again = AU.build_audio(timeline, voice, planned_pkg / "voice", tmp_path / "audio")
    assert again["audio_hash"] == sealed["audio_hash"]
    assert sha256_file(tmp_path / "audio" / "episode.wav") == sha256_file(planned_pkg / "audio" / "episode.wav")
    assert abs(again["seconds"] - timeline["seconds_total"]) < 0.05


def test_the_sound_track_refuses_a_stale_voice(planned_pkg, tmp_path):
    timeline = T.load_timeline(planned_pkg / "timeline.json")
    voice = V.load_voice(planned_pkg / "voice" / "voice.json")
    stale = seal({**voice, "narration_hash": "0" * 64, "voice_hash": ""}, "voice_hash")
    with pytest.raises(AU.AudioError) as err:
        AU.build_audio(timeline, stale, planned_pkg / "voice", tmp_path / "audio")
    assert err.value.code == "stale_lineage"


# --- the planned package: determinism and resume (gates A, F, K) -----------------------

def test_the_planned_package_matches_the_session_fixtures(planned_pkg, factory_facts, factory_story,
                                                          factory_shots, factory_narration):
    """Two independent computations of facts, story, shots and narration agree by hash."""
    assert load(planned_pkg / "facts.json")["facts_hash"] == factory_facts["facts_hash"]
    assert load(planned_pkg / "story.json")["story_hash"] == factory_story["story_hash"]
    assert load(planned_pkg / "shots.json")["shots_hash"] == factory_shots["shots_hash"]
    assert load(planned_pkg / "narration.json")["narration_hash"] == factory_narration["narration_hash"]
    assert load(planned_pkg / "narration.json")["picture_claims"] == "planned"


def test_the_timeline_is_a_playable_eight_to_ten_minute_recipe(planned_pkg, factory_brief):
    tl = T.load_timeline(planned_pkg / "timeline.json")
    lo, hi = factory_brief["target_seconds"]
    assert (lo, hi) == (480.0, 600.0) and lo <= tl["seconds_total"] <= hi
    assert tl["frames_total"] == sum(b["frames"] for b in tl["beats"]) == round(tl["seconds_total"] * tl["fps"])
    assert tl["sim_rate"] == 1.0 and all(b["shot"]["sim_rate"] == 1.0 for b in tl["beats"])
    for b in tl["beats"]:
        assert b["shot"]["sim_end"] - b["shot"]["sim_start"] == pytest.approx(b["seconds"])
    assert tl["seconds_without_words"] > 60, "an episode with no silence has no strategic silence"
    cues = T.build_captions(tl)["cues"]
    assert (planned_pkg / "captions.srt").read_text(encoding="utf-8") == T.build_captions(tl)["srt"]
    assert [c["text"] for c in cues] == [l["text"] for l in load(planned_pkg / "narration.json")["lines"]]


def test_a_second_run_resumes_and_reproduces_every_hash(planned_pkg, tmp_path):
    """Restart/resume: nothing expensive is redone and nothing deterministic changes."""
    pkg = clone(planned_pkg, tmp_path / "pkg")
    before = {n: load(pkg / n)[k] for n, k in (
        ("facts.json", "facts_hash"), ("story.json", "story_hash"), ("shots.json", "shots_hash"),
        ("narration.json", "narration_hash"), ("timeline.json", "timeline_hash"),
        ("voice/voice.json", "voice_hash"), ("audio/audio.json", "audio_hash"))}
    out = P.run_factory(BRIEF_PATH, pkg, render=False, log=lambda s: None)
    assert out["outcome"] == "planned_not_rendered"
    after = {n: load(pkg / n)[k] for n, k in (
        ("facts.json", "facts_hash"), ("story.json", "story_hash"), ("shots.json", "shots_hash"),
        ("narration.json", "narration_hash"), ("timeline.json", "timeline_hash"),
        ("voice/voice.json", "voice_hash"), ("audio/audio.json", "audio_hash"))}
    assert after == before
    run = load(pkg / "run_log.json")["runs"][-1]
    status = {s["stage"]: s for s in run["stages"]}
    assert status["simulate"]["status"] == "reused"
    assert all(s["status"] == "reused" for n, s in status.items() if n.startswith("simulate (repeat"))
    assert status["voice"]["status"] == "reused" and status["audio"]["status"] == "reused"
    for name in ("facts", "story", "shots", "narration", "timeline"):
        assert status[name]["identical_to_previous_run"] is True
    assert len(load(pkg / "run_log.json")["runs"]) >= 2


def test_a_package_is_never_continued_under_another_brief(planned_pkg, tmp_path):
    pkg = clone(planned_pkg, tmp_path / "pkg", skip=("replicates", "voice", "audio"))
    other = load(BRIEF_PATH)
    other["title"] = "Another episode"
    (tmp_path / "other.json").write_text(json.dumps(other), encoding="utf-8")
    with pytest.raises(P.PipelineError) as err:
        P.run_factory(tmp_path / "other.json", pkg, render=False, log=lambda s: None)
    assert err.value.code == "package_belongs_to_another_brief"
    assert load(pkg / "run_log.json")["runs"][-1]["refused"]["code"] == "package_belongs_to_another_brief"


def test_until_stops_early_and_an_unknown_stage_is_refused(planned_pkg, tmp_path):
    pkg = clone(planned_pkg, tmp_path / "pkg", skip=("voice", "audio"))
    out = P.run_factory(BRIEF_PATH, pkg, until="facts", log=lambda s: None)
    assert out == {"outcome": "stopped", "after": "facts", "package": str(pkg.resolve())}
    with pytest.raises(P.PipelineError) as err:
        P.run_factory(BRIEF_PATH, pkg, until="publish", log=lambda s: None)
    assert err.value.code == "bad_stage"


def test_a_damaged_simulation_is_not_reused(planned_pkg, tmp_path, factory_brief):
    """Resume re-runs a simulation whose evidence no longer verifies, instead of trusting it."""
    assert P._sim_current(planned_pkg / "sim", factory_brief) is True
    pkg = clone(planned_pkg, tmp_path / "pkg", skip=("replicates", "voice", "audio"))
    (pkg / "sim" / "agents_ruled.json").unlink()
    assert P._sim_current(pkg / "sim", factory_brief) is False
    pkg2 = clone(planned_pkg, tmp_path / "pkg2", skip=("replicates", "voice", "audio"))
    frames = pkg2 / "sim" / "record_baseline" / "frames.bin"
    data = bytearray(frames.read_bytes())
    data[4000] ^= 0xFF
    replace_bytes(frames, bytes(data))
    assert P._sim_current(pkg2 / "sim", factory_brief) is False
    # a repeat is only a repeat of THIS rule under ITS seed
    rep = planned_pkg / "replicates" / str(factory_brief["replicate_seeds"][0])
    manifest_hash = load(planned_pkg / "sim" / "rule_manifest.json")["manifest_hash"]
    assert P._sim_current(rep, None, manifest_hash, factory_brief["replicate_seeds"][0]) is True
    assert P._sim_current(rep, None, manifest_hash, factory_brief["seed"]) is False
    assert P._sim_current(rep, None, "0" * 64, factory_brief["replicate_seeds"][0]) is False


# --- the truth audit under attack (gates D, J) -----------------------------------------

def _audit(pkg, brief, world):
    return AD.audit_episode(pkg, brief, world, require_render=False)


def test_the_planned_package_passes_its_audit(planned_pkg, factory_brief, factory_world):
    rep = _audit(planned_pkg, factory_brief, factory_world)
    assert rep["pass"] is True and rep["complete"] is False and rep["failures"] == []
    assert rep["counts"]["sentences_refused"] == 0
    assert rep["counts"]["lineage_links"] == rep["counts"]["lineage_links_ok"] >= 15
    assert all(c["verdict"] == "supported" for c in rep["claims"])
    spoken_claims = [c for c in rep["claims"] if c["kind"] != "say"]
    assert all(c.get("cited") for c in spoken_claims), "every claim resolves to a field on disk"
    assert any(c.get("sealed_artefacts") for c in spoken_claims)


def test_audit_refuses_a_sentence_whose_number_was_changed(planned_pkg, tmp_path, factory_brief,
                                                           factory_world):
    """NARRATION OVERCLAIMS: 35 seconds becomes 45 and the document is re-sealed."""
    pkg = clone(planned_pkg, tmp_path / "pkg")
    nar = load(pkg / "narration.json")
    line = next(l for l in nar["lines"] if l["id"].startswith("reveal.") and "more" in l["text"])
    stated = line["cites"][0]["stated"]
    line["text"] = line["text"].replace(stated, str(int(stated) + 10))
    replace_json(pkg / "narration.json", seal({**nar, "narration_hash": ""}, "narration_hash"))
    rep = _audit(pkg, factory_brief, factory_world)
    assert rep["pass"] is False
    assert {"overclaim", "stale_lineage"} <= codes(rep)
    row = next(c for c in rep["claims"] if c["id"] == line["id"])
    assert row["verdict"] == "refused" and any("differs" in r for r in row["reasons"])


def test_audit_refuses_an_added_sentence_with_no_evidence(planned_pkg, tmp_path, factory_brief,
                                                          factory_world):
    pkg = clone(planned_pkg, tmp_path / "pkg")
    nar = load(pkg / "narration.json")
    extra = dict(nar["lines"][1])
    extra.update(id="hook.99", kind="fact", text="Every driver was late.", cites=[], checks=[])
    nar["lines"].insert(2, extra)
    replace_json(pkg / "narration.json", seal({**nar, "narration_hash": ""}, "narration_hash"))
    rep = _audit(pkg, factory_brief, factory_world)
    assert rep["pass"] is False and "overclaim" in codes(rep)
    assert next(c for c in rep["claims"] if c["id"] == "hook.99")["verdict"] == "refused"


def test_audit_refuses_a_check_that_was_edited_to_look_true(planned_pkg, tmp_path, factory_brief,
                                                            factory_world):
    """A stored `holds: true` is not believed: the check is evaluated again from disk."""
    pkg = clone(planned_pkg, tmp_path / "pkg")
    nar = load(pkg / "narration.json")
    # an equality that holds, turned into its negation: FALSE on disk, stored as true
    line = next(l for l in nar["lines"] if l["checks"] and l["checks"][0]["op"] == "==")
    line["checks"][0].update(op="!=", holds=True)
    replace_json(pkg / "narration.json", seal({**nar, "narration_hash": ""}, "narration_hash"))
    rep = _audit(pkg, factory_brief, factory_world)
    assert rep["pass"] is False and "overclaim" in codes(rep)


def test_audit_refuses_a_fact_sheet_that_was_edited_and_resealed(planned_pkg, tmp_path,
                                                                factory_brief, factory_world):
    """CONFLICTING CONSEQUENCE / STALE LINEAGE: the facts are extracted again from the evidence."""
    pkg = clone(planned_pkg, tmp_path / "pkg")
    facts = load(pkg / "facts.json")
    facts["facts"]["avg_duration_s_with_rule"]["value"] = 265.59
    replace_json(pkg / "facts.json", seal({**facts, "facts_hash": ""}, "facts_hash"))
    rep = _audit(pkg, factory_brief, factory_world)
    assert rep["pass"] is False and "stale_lineage" in codes(rep)
    assert any(not c["ok"] and "re-extracted" in c["binds"] for c in rep["lineage"])


@pytest.mark.parametrize("victim,expect", [
    ("sim/agents_ruled.json", "missing_evidence"),
    ("sim/ruled.tripinfo.xml", "missing_evidence"),
    ("sim/persistent_changes.json", "missing_evidence"),
    ("story.json", "missing"),
    ("shots.json", "missing"),
    ("voice/voice.json", "missing"),
    ("timeline.json", "missing"),
])
def test_audit_refuses_missing_evidence(planned_pkg, tmp_path, factory_brief, factory_world,
                                        victim, expect):
    """MISSING EVIDENCE at any link fails the audit; nothing is skipped quietly."""
    pkg = clone(planned_pkg, tmp_path / "pkg")
    (pkg / victim).unlink()
    rep = _audit(pkg, factory_brief, factory_world)
    assert rep["pass"] is False and expect in codes(rep)


def test_audit_refuses_a_corrupt_record(planned_pkg, tmp_path, factory_brief, factory_world):
    """CORRUPT RECORD: one flipped byte in frames.bin."""
    pkg = clone(planned_pkg, tmp_path / "pkg")
    frames = pkg / "sim" / "record_ruled" / "frames.bin"
    data = bytearray(frames.read_bytes())
    data[len(data) // 2] ^= 0x01
    replace_bytes(frames, bytes(data))
    rep = _audit(pkg, factory_brief, factory_world)
    assert rep["pass"] is False and "corrupt_evidence" in codes(rep)


@pytest.mark.parametrize("name,field,mutate", [
    ("story.json", "story_hash", lambda d: d["beats"].reverse()),
    ("story.json", "story_hash", lambda d: d["beats"][3].__setitem__("seconds", d["beats"][3]["seconds"] + 1)),
    ("shots.json", "shots_hash", lambda d: d["shots"]["hook"]["camera"]["loc"].__setitem__(2, 9999.0)),
    ("shots.json", "shots_hash", lambda d: d["shots"]["walkers_after"].__setitem__("subjects_visible_max", 5)),
    ("timeline.json", "timeline_hash", lambda d: d["beats"][0]["lines"][0].__setitem__("start", 0.1)),
    ("timeline.json", "timeline_hash", lambda d: d["beats"][2]["shot"].__setitem__("sim_rate", 4.0)),
])
def test_audit_refuses_stale_lineage_at_every_link(planned_pkg, tmp_path, factory_brief, factory_world,
                                                   name, field, mutate):
    """STALE LINEAGE: a document edited and re-sealed no longer derives from the one before it."""
    pkg = clone(planned_pkg, tmp_path / "pkg")
    doc = load(pkg / name)
    mutate(doc)
    replace_json(pkg / name, seal({**doc, field: ""}, field))
    rep = _audit(pkg, factory_brief, factory_world)
    assert rep["pass"] is False
    assert codes(rep) & {"stale_lineage", "check_failed", "overclaim", "narration_overruns_beat",
                         "narration_overruns_event", "event_not_visible"}
    assert any(not c["ok"] for c in rep["lineage"]) or rep["failures"]


def test_audit_refuses_edited_captions_and_a_foreign_audio_file(planned_pkg, tmp_path, factory_brief,
                                                                factory_world):
    pkg = clone(planned_pkg, tmp_path / "pkg")
    srt = (pkg / "captions.srt").read_text(encoding="utf-8")
    (pkg / "captions.srt").unlink()
    (pkg / "captions.srt").write_text(srt.replace("Baker Avenue", "Baker Street", 1), encoding="utf-8")
    rep = _audit(pkg, factory_brief, factory_world)
    assert rep["pass"] is False and "stale_lineage" in codes(rep)
    pkg2 = clone(planned_pkg, tmp_path / "pkg2")
    (pkg2 / "audio" / "theme.mp3").write_bytes(b"ID3")
    rep = _audit(pkg2, factory_brief, factory_world)
    assert rep["pass"] is False and "policy_violation" in codes(rep)


def test_audit_refuses_a_package_of_another_brief(planned_pkg, tmp_path, factory_world):
    from ldyf.factory.brief import normalise_brief
    other = normalise_brief({**load(BRIEF_PATH), "title": "Something else"})
    rep = AD.audit_episode(planned_pkg, other, factory_world, require_render=False)
    assert rep["pass"] is False and "stale_lineage" in codes(rep)


def test_a_planned_package_can_never_pass_as_a_finished_episode(planned_pkg, factory_brief,
                                                                factory_world):
    """No render, no episode: the complete audit refuses a package that was only planned."""
    rep = AD.audit_episode(planned_pkg, factory_brief, factory_world, require_render=True)
    assert rep["pass"] is False
    assert codes(rep) & {"missing", "render_incomplete", "unconfirmed_picture"}


# --- render bookkeeping (gate H, J: render interruption) --------------------------------

def _shot_fixture(factory_story, factory_shots, factory_recs, bid):
    beat = next(b for b in factory_story["beats"] if b["id"] == bid)
    shot = factory_shots["shots"][bid]
    return beat, shot, factory_recs[shot["arm"]]


def test_bake_and_engine_measure_agree_with_the_planner_when_the_engine_obeys(
        factory_story, factory_shots, factory_recs, factory_net, factory_blocks, factory_world,
        factory_pkg, factory_brief):
    """With an engine that puts every actor exactly where its keys say, the engine-side
    count equals the planner's count at the same samples."""
    beat, shot, rec = _shot_fixture(factory_story, factory_shots, factory_recs, "walkers_before")
    fps, res = factory_brief["fps"], factory_brief["resolution"]
    short = {**shot, "seconds": 4.0, "sim_end": shot["sim_start"] + 4.0,
             "require": {"min_visible": 1, "fraction": 1.0}}
    bake = R.bake_shot(factory_pkg / "sim" / f"record_{shot['arm']}", short["sim_start"], 4.0, fps,
                       factory_world)
    assert bake["frames"][1] - bake["frames"][0] + 1 == 4 * fps and not bake["missing_contact_offsets"]
    again = R.bake_shot(factory_pkg / "sim" / f"record_{shot['arm']}", short["sim_start"], 4.0, fps,
                        factory_world)
    assert json.dumps(again, sort_keys=True) == json.dumps(bake, sort_keys=True), "the bake is deterministic"
    first = bake["frames"][0]
    frames = list(range(0, 4 * fps, fps))

    def engine(move_cm=0.0, hide=None, block=False):
        poses, traces = {}, {}
        for f in frames:
            row = {}
            for uid, a in bake["actors"].items():
                k = next((k for k in a["keys"] if k["f"] - first == f), None)
                lab = R._label(uid)
                if k is None:
                    row[lab] = [0.0, 0.0, -100000.0, 0.0, True]
                else:
                    row[lab] = [k["x"] + move_cm, k["y"], k["z"], k["yaw"], uid == hide]
            poses[str(f)] = row
            traces[str(f)] = {u: ("blocked:LD_Tree_1" if block else "clear")
                              for u in short["subjects"]["uids"]}
        return {"ok": True, "poses": poses, "traces": traces, "trace_errors": 0}

    m = R.engine_measure(short, rec, factory_net, factory_blocks, res, fps, engine(), bake, frames)
    planner = [shot["subjects_visible_per_sample"][2 * i] for i in range(len(frames))]
    assert m["subjects_visible_per_sample"] == planner and m["requirement_met"] is True
    assert m["max_position_error_cm"] == 0.0 and m["visibility_mismatches"] == 0
    # CAMERA MISSES THE EVENT in the engine: every sight line blocked by a tree
    m = R.engine_measure(short, rec, factory_net, factory_blocks, res, fps, engine(block=True), bake, frames)
    assert m["subjects_visible_max"] == 0 and m["requirement_met"] is False
    assert m["sight_line_blocked_by"] == {"LD_Tree_1": sum(planner)}
    # an engine that does not put bodies where the keys say is refused outright
    with pytest.raises(R.RenderError) as err:
        R.engine_measure(short, rec, factory_net, factory_blocks, res, fps, engine(move_cm=5.0), bake, frames)
    assert err.value.code == "engine_disagrees"
    with pytest.raises(R.RenderError) as err:
        R.engine_measure(short, rec, factory_net, factory_blocks, res, fps,
                         engine(hide=short["subjects"]["uids"][0]), bake, frames)
    assert err.value.code == "engine_disagrees"


def test_a_shot_is_finished_only_when_sealed_current_and_intact(complete_pkg, factory_story,
                                                               factory_shots, factory_recs,
                                                               factory_brief, factory_world, tmp_path):
    """RENDER INTERRUPTION: a shot with no sealed result, another input, an edited result or a
    changed segment is not finished, so resume renders it again and the manifest refuses it."""
    fps, res = factory_brief["fps"], factory_brief["resolution"]
    beat, shot, rec = _shot_fixture(factory_story, factory_shots, factory_recs, "detour_before")
    inputs = R.shot_inputs(beat, shot, rec.frames_sha256, fps, res, R.scene_hashes(factory_world))
    src = complete_pkg / "render" / "detour_before"
    assert R.shot_is_finished(src, inputs) is not None
    assert R.shot_is_finished(src, {**inputs, "fps": 25}) is None
    assert R.shot_is_finished(src, {**inputs, "code_sha256": "0" * 64}) is None
    assert R.shot_is_finished(src, {**inputs, "record_frames_sha256": "0" * 64}) is None
    d = clone(src, tmp_path / "a")
    (d / "shot_render.json").unlink()
    assert R.shot_is_finished(d, inputs) is None, "interrupted before the result was sealed"
    d = clone(src, tmp_path / "b")
    seg = d / "segment.mp4"
    replace_bytes(seg, seg.read_bytes()[:-1000])
    assert R.shot_is_finished(d, inputs) is None, "a truncated segment"
    d = clone(src, tmp_path / "c")
    doc = load(d / "shot_render.json")
    doc["frames_rendered"] -= 1
    replace_json(d / "shot_render.json", doc)
    assert R.shot_is_finished(d, inputs) is None, "edited without re-sealing"
    replace_json(d / "shot_render.json", seal({**doc, "shot_render_hash": ""}, "shot_render_hash"))
    assert R.shot_is_finished(d, inputs) is None, "sealed, but a frame short"
    d = clone(src, tmp_path / "e")
    doc = load(d / "shot_render.json")
    doc["engine"]["requirement_met"] = False
    replace_json(d / "shot_render.json", seal({**doc, "shot_render_hash": ""}, "shot_render_hash"))
    assert R.shot_is_finished(d, inputs) is None, "the engine did not hold the subject"


def test_the_render_manifest_refuses_a_missing_shot(complete_pkg, factory_story, factory_shots,
                                                    factory_recs, factory_brief, factory_world,
                                                    tmp_path):
    fps, res = factory_brief["fps"], factory_brief["resolution"]
    sealed = R.load_render(complete_pkg / "render" / "render.json")
    again = R.seal_render(factory_story, factory_shots, factory_recs, complete_pkg / "render",
                          fps=fps, res=res, world=factory_world,
                          level_sha=sealed["level_file_sha256"])
    assert again["render_hash"] == sealed["render_hash"]
    assert sealed["frames_total"] == round(factory_story["seconds_total"] * fps)
    rd = clone(complete_pkg / "render", tmp_path / "render")
    (rd / "stuck" / "shot_render.json").unlink()
    with pytest.raises(R.RenderError) as err:
        R.seal_render(factory_story, factory_shots, factory_recs, rd, fps=fps, res=res, world=factory_world)
    assert err.value.code == "render_incomplete"


def test_assembly_refuses_a_segment_that_is_not_the_sealed_one(complete_pkg, tmp_path):
    """Checked before any encoding: a swapped segment never reaches the episode."""
    timeline = T.load_timeline(complete_pkg / "timeline.json")
    render = R.load_render(complete_pkg / "render" / "render.json")
    audio = AU.load_audio(complete_pkg / "audio" / "audio.json")
    rd = clone(complete_pkg / "render", tmp_path / "render")
    a, b = rd / "hook" / "segment.mp4", rd / "stuck" / "segment.mp4"
    replace_bytes(a, b.read_bytes())
    with pytest.raises(AS.AssemblyError) as err:
        AS.assemble(timeline, render, audio, rd, complete_pkg / "audio", tmp_path / "out")
    assert err.value.code == "stale_lineage"
    (rd / "promise" / "segment.mp4").unlink()
    replace_bytes(a, (complete_pkg / "render" / "hook" / "segment.mp4").read_bytes())
    with pytest.raises(AS.AssemblyError) as err:
        AS.assemble(timeline, render, audio, rd, complete_pkg / "audio", tmp_path / "out")
    assert err.value.code == "render_incomplete"
    other = seal({**render, "shots_hash": "0" * 64, "render_hash": ""}, "render_hash")
    with pytest.raises(AS.AssemblyError) as err:
        AS.assemble(timeline, other, audio, complete_pkg / "render", complete_pkg / "audio", tmp_path / "out")
    assert err.value.code == "stale_lineage"


# --- the finished episode (gates H, I) --------------------------------------------------

def test_the_finished_episode_is_complete_playable_and_audited(complete_pkg, factory_brief):
    manifest = load(complete_pkg / "package.json")
    audit = load(complete_pkg / "truth_audit.json")
    assembly = AS.load_assembly(complete_pkg / "assembly.json")
    AS.verify_assembly(assembly, complete_pkg)
    ep = assembly["episode"]
    lo, hi = factory_brief["target_seconds"]
    assert lo <= ep["seconds"] <= hi, "the public format is 8-10 minutes"
    assert ep["audio_codec"] is not None and ep["frames"] == manifest["frames"]
    assert [ep["width"], ep["height"]] == factory_brief["resolution"]
    assert audit["pass"] is True and audit["complete"] is True and audit["failures"] == []
    assert audit["counts"]["sentences_refused"] == 0
    assert audit["counts"]["shots_passing"] == audit["counts"]["shots"] == manifest["beats"]
    assert audit["counts"]["lineage_links"] == audit["counts"]["lineage_links_ok"]
    assert assembly["edit"] == {**assembly["edit"], "segments_trimmed": 0, "segments_reused": 0,
                                "speed_changes": 0, "transitions": 0}
    nar = load(complete_pkg / "narration.json")
    assert nar["picture_claims"] == "engine_confirmed"
    assert nar["render_hash"] == load(complete_pkg / "render" / "render.json")["render_hash"]


def test_every_picture_claim_is_bound_to_the_engine_measurement(complete_pkg):
    """A sentence about what a picture holds cites render.json, and states its number."""
    audit = load(complete_pkg / "truth_audit.json")
    render = load(complete_pkg / "render" / "render.json")
    nar = load(complete_pkg / "narration.json")
    seen = 0
    for l in nar["lines"]:
        for c in l["cites"]:
            if c["ref"].startswith("shot:") and c["ref"][5:] in N.ENGINE_FIELDS:
                assert c["value"] == render["shots"][l["beat"]]["engine_" + c["ref"][5:]]
                row = next(r for r in audit["claims"] if r["id"] == l["id"])
                assert any(x["artefact"] == "render/render.json" for x in row["cited"])
                seen += 1
    assert seen >= 3
    for bid, r in render["shots"].items():
        assert r["engine_max_position_error_cm"] <= R.POSE_TOLERANCE_CM
        assert r["unique_frames"] == r["frames"], f"{bid}: a repeated frame would be a freeze"


def test_the_finished_package_verifies_and_a_changed_file_is_caught(complete_pkg, tmp_path):
    out = P.verify_package(complete_pkg)
    assert out["audit_pass"] is True
    pkg = clone(complete_pkg, tmp_path / "pkg")
    srt = pkg / "captions.srt"
    text = srt.read_text(encoding="utf-8")
    srt.unlink()
    srt.write_text(text.replace("Baker", "Maker", 1), encoding="utf-8")
    with pytest.raises(P.PipelineError) as err:
        P.verify_package(pkg)
    assert err.value.code == "package_changed"


@pytest.mark.parametrize("attack,expect", [
    ("drop_shot_result", {"render_incomplete"}),
    ("swap_segment", {"render_incomplete", "stale_lineage"}),
    ("planned_narration", {"unconfirmed_picture", "stale_lineage"}),
    ("truncate_episode", {"corrupt"}),
    ("engine_says_visible", {"stale_lineage", "render_incomplete"}),
])
def test_the_complete_audit_refuses_a_damaged_finished_package(complete_pkg, tmp_path, factory_brief,
                                                               factory_world, factory_story,
                                                               factory_facts, factory_shots,
                                                               attack, expect):
    pkg = clone(complete_pkg, tmp_path / "pkg")
    if attack == "drop_shot_result":                       # RENDER INTERRUPTION
        (pkg / "render" / "moved" / "shot_render.json").unlink()
    elif attack == "swap_segment":
        a = pkg / "render" / "walkers_after" / "segment.mp4"
        replace_bytes(a, (pkg / "render" / "walkers_before" / "segment.mp4").read_bytes())
    elif attack == "planned_narration":                    # picture claims never engine-confirmed
        planned = N.bind_narration(factory_story, factory_facts, factory_shots,
                                   rate=factory_brief["voice_rate"])
        replace_json(pkg / "narration.json", planned)
    elif attack == "truncate_episode":
        ep = pkg / "episode.mp4"
        replace_bytes(ep, ep.read_bytes()[: ep.stat().st_size // 2])
    elif attack == "engine_says_visible":                  # CAMERA MISSES THE EVENT, papered over
        rj = pkg / "render" / "render.json"
        doc = load(rj)
        doc["shots"]["walkers_after"]["engine_subjects_visible_max"] = 3
        replace_json(rj, seal({**doc, "render_hash": ""}, "render_hash"))
    rep = AD.audit_episode(pkg, factory_brief, factory_world, require_render=True)
    assert rep["pass"] is False and codes(rep) & expect, codes(rep)


# --- simulation determinism (gate A); needs SUMO, about two minutes each ----------------

def _sumo():
    try:
        return SIM.find_sumo()
    except FactoryError:
        return None


@pytest.mark.skipif(_sumo() is None, reason="needs SUMO")
def test_the_simulation_reproduces_the_sealed_records_byte_for_byte(factory_pkg, factory_brief,
                                                                    factory_world, tmp_path):
    """Brief -> simulation is deterministic: a fresh run gives the sealed records and the
    same sealed result, rule manifest and ledger."""
    doc = SIM.run_episode(factory_brief, factory_world, tmp_path / "sim", ports=(55961, 55962),
                          log=lambda s: None)
    sealed = load(factory_pkg / "sim" / "simulation.json")
    assert doc["records"] == sealed["records"]
    for key in ("simulation_result_hash", "rule_manifest_hash", "ledger_hash", "rule_id",
                "brief_sha256"):
        assert doc[key] == sealed[key], key


@pytest.mark.skipif(_sumo() is None, reason="needs SUMO")
def test_the_factory_runs_the_locked_phase_3_world_not_a_lookalike(factory_brief, factory_world,
                                                                  tmp_path):
    """With drivers not rerouting, the factory's runner reproduces the sealed Phase 3 agent
    episode records byte for byte."""
    doc = SIM.run_episode(factory_brief, factory_world, tmp_path / "sim", drivers_reroute=False,
                          ports=(55971, 55972), log=lambda s: None)
    assert {arm: doc["records"][arm]["frames_sha256"] for arm in SIM.ARMS} == PHASE3_FRAMES
