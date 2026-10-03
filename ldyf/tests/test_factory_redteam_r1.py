"""Phase 4 factory: every finding of red-team round 1, now a refusal (or a held claim).

The reports are in EVIDENCE/PHASE_04/redteam/. Each test names its finding:
T* the truth-and-evidence lane, F* the pipeline-and-picture lane. Every attack
works on a private copy; the sealed package is read-only here.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from ldyf.factory import narration as N
from ldyf.factory import pipeline as P
from ldyf.factory import render as R
from ldyf.factory.facts import FactsError, _max_gap_cm, extract_facts, path_distance_cm
from ldyf.factory.util import seal

from .factory_support import BRIEF_PATH, FFMPEG, WINDOWS_TTS, clone, copy_sim, dump, load, reseal_simulation
from .test_factory_package import replace_bytes, replace_json


def _facts(sim, brief, world, reps=None):
    return extract_facts(sim, brief, world, replicate_dirs=reps or [])


def _edit_tripinfo(sim: Path, arm: str, attr: str, factor: float) -> None:
    p = sim / f"{arm}.tripinfo.xml"
    text = p.read_text(encoding="utf-8")

    def scale(m):
        return f'{attr}="{float(m.group(1)) * factor:.2f}"'
    p.write_text(re.sub(rf'(?<= ){attr}="([0-9.]+)"', scale, text), encoding="utf-8")


# --- T/A1, A2: tripinfo contents are measured against the record -------------------------

@pytest.mark.parametrize("attr,factor", [("duration", 0.5), ("duration", 3.0),
                                         ("waitingTime", 2.0), ("routeLength", 1.5)])
def test_a_resealed_tripinfo_that_the_record_does_not_support_is_refused(
        factory_pkg, factory_brief, factory_world, tmp_path, attr, factor):
    """A1/A2: an insider halves (or triples) the ruled trip durations and re-seals every
    hash. The headline would flip; the per-trip cross-check against the record refuses."""
    sim = copy_sim(factory_pkg, tmp_path)
    _edit_tripinfo(sim, "ruled", attr, factor)
    reseal_simulation(sim)
    with pytest.raises(FactsError) as err:
        _facts(sim, factory_brief, factory_world)
    assert err.value.code == "conflicting_consequence"
    assert "trip by trip" in err.value.message


def test_every_real_trip_agrees_with_its_own_track(factory_facts):
    rows = [c for c in factory_facts["cross_checks"] if "trip by trip" in c["name"]]
    assert len(rows) == 6, "both arms of the episode and of both repeats"
    assert all(c["agree"] and c["event_log"] == c["record"] for c in rows)


# --- T/A3, A4: a repeat is a different run, and seeds are the simulator's own ---------------

def test_a_replicate_that_is_the_episode_again_is_refused(factory_pkg, factory_brief, factory_world,
                                                          tmp_path):
    """A3: both repeats replaced by copies of the episode's own sim/, only the (unsealed)
    seed in simulation.json edited. "3 of 3 runs" would count one run three times."""
    reps = []
    for seed in factory_brief["replicate_seeds"]:
        d = tmp_path / "reps" / str(seed)
        shutil.copytree(factory_pkg / "sim", d)
        doc = load(d / "simulation.json")
        doc["seed"] = seed
        dump(d / "simulation.json", doc)
        reps.append(d)
    with pytest.raises(FactsError) as err:
        _facts(factory_pkg / "sim", factory_brief, factory_world, reps)
    assert err.value.code == "uncontrolled_arms"


def test_an_arm_run_with_another_seed_is_refused_even_when_its_json_says_otherwise(
        factory_pkg, factory_brief, factory_world, tmp_path):
    """A4: the baseline arm swapped for a repeat's baseline, every JSON seed field edited
    back. SUMO wrote its real seed into the tripinfo header; that is what is checked."""
    sim = copy_sim(factory_pkg, tmp_path)
    other = factory_pkg / "replicates" / str(factory_brief["replicate_seeds"][0])
    for name in ("baseline.tripinfo.xml", "agents_baseline.json", "baseline_demand.json"):
        shutil.copy2(other / name, sim / name)
    shutil.rmtree(sim / "record_baseline")
    shutil.copytree(other / "record_baseline", sim / "record_baseline")
    ag = load(sim / "agents_baseline.json")
    ag["seed"] = factory_brief["seed"]
    dump(sim / "agents_baseline.json", ag)
    result = load(sim / "simulation_result.json")
    rep = load(other / "simulation_result.json")["run_report"]["baseline"]
    result["run_report"]["baseline"] = {**rep, "seed": factory_brief["seed"]}
    dump(sim / "simulation_result.json", result)
    reseal_simulation(sim)
    with pytest.raises(FactsError) as err:
        _facts(sim, factory_brief, factory_world)
    assert err.value.code in ("conflicting_consequence", "uncontrolled_arms")
    assert "seed" in err.value.message


def test_the_seeds_the_simulator_wrote_are_the_declared_ones(factory_facts, factory_brief):
    rows = [c for c in factory_facts["cross_checks"] if "simulator's own configuration" in c["name"]]
    assert len(rows) == 6 and all(c["agree"] for c in rows)
    assert {c["record"] for c in rows} == {factory_brief["seed"], *factory_brief["replicate_seeds"]}


# --- T1: path to path, not the same-instant gap ---------------------------------------------

def test_path_shift_is_measured_path_to_path(factory_facts, factory_recs):
    """T1: "up to N metres away from the old path" is geometry; the same-instant gap mixes
    in timing (282 m against 199 m on this episode)."""
    rec = factory_recs["ruled"]
    uid = next(u for u in rec.tracks if u.startswith("person:agent"))
    assert path_distance_cm(rec, rec, uid) == 0.0
    treatment_gap = max(_max_gap_cm(factory_recs["baseline"], rec, u)
                        for u in rec.tracks if u.startswith("person:agent"))
    shift = factory_facts["facts"]["path_shift_max_m"]["value"]
    assert 0 < shift * 100 <= treatment_gap
    assert "path-to-path" in factory_facts["facts"]["path_shift_max_m"]["how"]


# --- T2, T3, T4, T5, T7, F1, F9: the sentences say what was measured ------------------------

def test_the_reworded_sentences(factory_narration):
    text = {l["id"]: l["text"] for l in factory_narration["lines"]}
    allt = " ".join(text.values())
    assert "this street" not in allt                                   # F1
    assert "they know in the same second" not in allt                  # T2
    assert re.search(r"We ran the city \d+ more times", allt)          # T3
    assert re.search(r"The \d+ cars that never start are not\.", allt)  # T4
    assert "stood for" not in allt                                      # T5
    assert "Any people you see are other people." in allt              # T7
    assert re.search(r"Up to \d+ of them (is|are) in this picture, with a red ball", allt)  # F9


@pytest.mark.parametrize("sentence,kind,numeric,check", [
    ("The closure caused the jam.", "say", False, False),
    ("This proves the rule works.", "say", False, False),
    ("Traffic doubled.", "say", False, False),
    ("A third of the cars wait.", "say", False, False),
    ("Dozens of cars wait.", "say", False, False),
    ("Cars are stuck here forever.", "say", False, False),
    ("All 488 trips take longer.", "fact", True, False),
])
def test_the_linter_refuses_what_round_one_slipped_past_it(sentence, kind, numeric, check):
    """T8: causal words, fractions and universal claims are refused without a check."""
    assert N.lint(sentence, kind, numeric, check)


# --- F2, F3, F4: verify measures the file and the whole directory ---------------------------

def _reseal_package(pkg: Path) -> None:
    from ldyf.factory.util import sha256_file
    man = load(pkg / "package.json")
    for row in man["files"]:
        p = pkg / row["file"]
        if p.is_file():
            row["sha256"], row["bytes"] = sha256_file(p), p.stat().st_size
    replace_json(pkg / "package.json", seal({**man, "package_hash": ""}, "package_hash"))


def test_verify_refuses_a_forged_episode_even_with_every_seal_redone(complete_pkg, tmp_path):
    """F2: episode.mp4 replaced by text, assembly.json and package.json re-sealed. The
    audit probes the FILE, so the forgery is refused."""
    pkg = clone(complete_pkg, tmp_path / "pkg")
    replace_bytes(pkg / "episode.mp4", b"not a video " * 200)
    from ldyf.factory.util import sha256_file
    asm = load(pkg / "assembly.json")
    asm["episode"]["sha256"] = sha256_file(pkg / "episode.mp4")
    replace_json(pkg / "assembly.json", seal({**asm, "assembly_hash": ""}, "assembly_hash"))
    _reseal_package(pkg)
    with pytest.raises(P.PipelineError) as err:
        P.verify_package(pkg)
    assert err.value.code == "audit_failed" and "episode.mp4" in err.value.message


def test_verify_refuses_a_manifest_that_does_not_cover_the_package(complete_pkg, tmp_path):
    """F3: a re-sealed manifest that lists nothing."""
    pkg = clone(complete_pkg, tmp_path / "pkg")
    man = load(pkg / "package.json")
    replace_json(pkg / "package.json", seal({**man, "files": [], "package_hash": ""}, "package_hash"))
    with pytest.raises(P.PipelineError) as err:
        P.verify_package(pkg)
    assert err.value.code == "package_changed"


@pytest.mark.parametrize("extra", ["EXTRA_UNLISTED.txt", "render/hook/segment_alt.mp4",
                                   "render/hook/timing.json.bak", "episode_final_v2.mp4"])
def test_verify_refuses_an_unlisted_file(complete_pkg, tmp_path, extra):
    """F4: anything in the directory that the manifest does not list."""
    pkg = clone(complete_pkg, tmp_path / "pkg")
    (pkg / extra).write_bytes(b"smuggled")
    with pytest.raises(P.PipelineError) as err:
        P.verify_package(pkg)
    assert err.value.code == "package_changed" and "not in the manifest" in err.value.message


def test_verify_refuses_a_leftover_partial_write(complete_pkg, tmp_path):
    pkg = clone(complete_pkg, tmp_path / "pkg")
    (pkg / "truth_audit.json.tmp").write_text("{", encoding="utf-8")
    with pytest.raises(P.PipelineError) as err:
        P.verify_package(pkg)
    assert err.value.code == "unfinished_write"


def test_verify_refuses_a_malformed_manifest_with_a_typed_error(complete_pkg, tmp_path):
    """F6: a re-sealed manifest with a row that has no sha256 is a refusal, not a KeyError."""
    pkg = clone(complete_pkg, tmp_path / "pkg")
    man = load(pkg / "package.json")
    man["files"][0].pop("sha256")
    replace_json(pkg / "package.json", seal({**man, "package_hash": ""}, "package_hash"))
    with pytest.raises(P.PipelineError) as err:
        P.verify_package(pkg)
    assert err.value.code == "corrupt"


# --- F5: a finished package is not downgraded ------------------------------------------------

def test_a_run_without_render_never_overwrites_a_finished_episode(complete_pkg, tmp_path):
    pkg = clone(complete_pkg, tmp_path / "pkg")
    before = (pkg / "narration.json").read_bytes()
    with pytest.raises(P.PipelineError) as err:
        P.run_factory(BRIEF_PATH, pkg, render=False, log=lambda s: None)
    assert err.value.code == "package_is_finished"
    assert (pkg / "narration.json").read_bytes() == before
    P.verify_package(pkg)


# --- F7: the engine check counts only what it saw -------------------------------------------

def test_an_untraced_subject_never_helps_a_presence_or_an_absence_claim(
        factory_story, factory_shots, factory_recs, factory_net, factory_blocks, factory_world,
        factory_pkg, factory_brief):
    fps, res = factory_brief["fps"], factory_brief["resolution"]
    shot = factory_shots["shots"]["walkers_before"]
    short = {**shot, "seconds": 3.0, "sim_end": shot["sim_start"] + 3.0,
             "require": {"min_visible": 1, "fraction": 1.0}}
    bake = R.bake_shot(factory_pkg / "sim" / f"record_{shot['arm']}", short["sim_start"], 3.0, fps,
                       factory_world)
    first = bake["frames"][0]
    frames = list(range(0, 3 * fps, fps))

    def engine(trace, errors=0):
        poses, traces = {}, {}
        for f in frames:
            row = {}
            for uid, a in bake["actors"].items():
                k = next((k for k in a["keys"] if k["f"] - first == f), None)
                row[R._label(uid)] = ([0.0, 0.0, -1e5, 0.0, True] if k is None
                                      else [k["x"], k["y"], k["z"], k["yaw"], False])
            poses[str(f)] = row
            traces[str(f)] = {} if trace is None else {u: trace for u in short["subjects"]["uids"]}
        return {"ok": True, "poses": poses, "traces": traces, "trace_errors": errors}

    rec = factory_recs[shot["arm"]]
    seen = R.engine_measure(short, rec, factory_net, factory_blocks, res, fps, engine("clear"), bake, frames)
    assert seen["subjects_visible_min"] >= 1
    for verdict in (None, "untraced", "missing"):          # presence: not seen is not counted
        m = R.engine_measure(short, rec, factory_net, factory_blocks, res, fps, engine(verdict), bake, frames)
        assert m["subjects_visible_max"] == 0 and m["requirement_met"] is False
    absent = {**short, "require": {"max_visible": 0}}      # absence: untraced still counts
    m = R.engine_measure(absent, rec, factory_net, factory_blocks, res, fps, engine(None), bake, frames)
    assert m["subjects_visible_max"] == seen["subjects_visible_max"] and m["requirement_met"] is False
    with pytest.raises(R.RenderError) as err:
        R.engine_measure(short, rec, factory_net, factory_blocks, res, fps, engine("clear", 2), bake, frames)
    assert err.value.code == "engine_trace_failed"


# --- F8: a shot is current only for the scene it was drawn in -------------------------------

def test_a_finished_shot_is_stale_when_the_scene_or_the_counting_rule_changes(
        complete_pkg, factory_story, factory_shots, factory_recs, factory_brief, factory_world):
    fps, res = factory_brief["fps"], factory_brief["resolution"]
    beat = next(b for b in factory_story["beats"] if b["id"] == "stuck")
    shot = factory_shots["shots"]["stuck"]
    scene = R.scene_hashes(factory_world)
    inputs = R.shot_inputs(beat, shot, factory_recs[shot["arm"]].frames_sha256, fps, res, scene)
    d = complete_pkg / "render" / "stuck"
    assert R.shot_is_finished(d, inputs) is not None
    for key in scene:
        assert R.shot_is_finished(d, {**inputs, "scene_sha256": {**scene, key: "0" * 64}}) is None
    doc = load(d / "shot_render.json")
    assert all(len(s.get("sha256", "")) == 64 for s in doc["stills"]), "stills are hashed"
    assert "camera.py" in Path(R.__file__).read_text(encoding="utf-8").split("def code_hash")[1][:600]


# --- F11: nothing unlisted in the sound directories ------------------------------------------

@pytest.mark.parametrize("name", ["music.mka", "loop.webm", "notes.txt"])
def test_any_unlisted_file_in_the_sound_directories_fails_the_policy(planned_pkg, tmp_path, name):
    from ldyf.factory import audio as AU
    pkg = clone(planned_pkg, tmp_path / "pkg")
    (pkg / "audio" / name).write_bytes(b"\x1aE\xdf\xa3")
    with pytest.raises(AU.AudioError) as err:
        AU.validate_audio_policy(AU.load_audio(pkg / "audio" / "audio.json"), pkg / "audio", pkg / "voice")
    assert err.value.code == "policy_violation"


_ = (json, FFMPEG, WINDOWS_TTS)
