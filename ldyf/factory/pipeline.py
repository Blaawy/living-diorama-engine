"""The factory, end to end: one brief in, one reviewable episode package out.

    python -m ldyf.factory run --brief ldyf/factory/briefs/close_baker_avenue.json --out <package>

Stages, in order, each one FAILING CLOSED and each one resumable:

    brief      validate, normalise, pin the package to this brief
    simulate   both arms of the locked world (and any repeat seeds), sealed
    facts      evidence-bound consequence extraction, cross-checked
    story      beats selected from the measured outcomes
    shots      a camera per beat, planned from the record and measured
    render     every shot through Unreal / Movie Render Queue, measured in the engine
    narration  every sentence bound to a fact or to a rendered shot
    voice      local speech synthesis, one wave per sentence
    timeline   the deterministic edit recipe, and the captions
    audio      generated bed + voice, under the audio policy
    assemble   segments + sound + captions -> episode.mp4
    audit      the truth audit; a failing audit stops the package
    package    manifest of every file, contact sheet

RESUME. Re-running the command on an existing package continues it. Expensive
stages are reused only when their sealed output still names the current
upstream hashes and their files still hash to what was sealed: a finished
simulation, a spoken narration, a rendered shot, an assembled episode. The
cheap deterministic stages (facts, story, shots, narration, timeline) are
always computed again -- which is also what proves, on every run, that they
are deterministic: a resumed package whose recomputed story differed from the
one its shots were rendered for would stop at the render stage.

`run_log.json` records, per run, which stages ran and which were reused, with
wall-clock seconds. It is the only document here that holds a wall clock and
nothing hashes it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from . import FACTORY_VERSION, FactoryError
from . import assemble as AS
from . import audio as AU
from . import audit as AD
from . import camera as C
from . import facts as F
from . import narration as N
from . import render as R
from . import simulate as SIM
from . import story as S
from . import timeline as T
from . import voice as V
from .brief import brief_hash, normalise_brief
from .record import load_record
from .util import read_json, seal, sha256_file, write_json, write_text
from .world import REPO_ROOT, load_world

STAGES = ("brief", "simulate", "facts", "story", "shots", "render", "narration", "voice",
          "timeline", "audio", "assemble", "audit", "package")
PACKAGE_SCHEMA = "episode_package_v1"
#: A finished package always holds these; a manifest that omits one is refused.
REQUIRED_FILES = ("brief.json", "facts.json", "story.json", "shots.json", "narration.json",
                  "timeline.json", "captions.srt", "captions.vtt", "voice/voice.json",
                  "audio/audio.json", "audio/episode.wav", "render/render.json", "assembly.json",
                  "episode.mp4", "truth_audit.json", "lineage.json", "contact_sheet.jpg")


class PipelineError(FactoryError):
    stage = "pipeline"


def _same_doc(path: Path, doc: dict[str, Any], hash_field: str) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get(hash_field) == doc[hash_field]
    except Exception:  # noqa: BLE001
        return False


def _sim_current(sim_dir: Path, brief: dict[str, Any] | None, manifest_hash: str | None = None,
                 seed: int | None = None) -> bool:
    try:
        docs = F.load_verified_simulation(sim_dir, brief)
        for arm in SIM.ARMS:
            load_record(sim_dir / f"record_{arm}")
        if manifest_hash is not None and docs["manifest"]["manifest_hash"] != manifest_hash:
            return False
        if seed is not None and int(docs["sim"]["seed"]) != int(seed):
            return False
        return True
    except Exception:  # noqa: BLE001 - anything short of a verified simulation is re-run
        return False


def contact_sheet(pkg: Path, timeline: dict[str, Any]) -> str | None:
    """One still per beat, in order, as a single picture for a first look."""
    stills = [pkg / "render" / b["id"] / "still_2.jpg" for b in timeline["beats"]]
    stills = [p for p in stills if p.is_file()]
    if not stills:
        return None
    cols = 5
    rows = (len(stills) + cols - 1) // cols
    args = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    for p in stills:
        args += ["-i", str(p)]
    lay = "".join(f"[{i}:v]scale=480:270[s{i}];" for i in range(len(stills)))
    lay += "".join(f"[s{i}]" for i in range(len(stills)))
    lay += f"xstack=inputs={len(stills)}:layout=" + "|".join(
        f"{(i % cols) * 480}_{(i // cols) * 270}" for i in range(len(stills))) + ":fill=black[o]"
    out = pkg / "contact_sheet.jpg"
    run = subprocess.run(args + ["-filter_complex", lay, "-map", "[o]", "-frames:v", "1",
                                 "-q:v", "3", str(out)], capture_output=True, text=True)
    _ = rows
    return out.name if run.returncode == 0 and out.is_file() else None


#: The only files of a package its manifest does not list: the manifest itself, the
#: wall-clock run log, and SUMO's console logs (wall-clock lines). Everything else
#: in the directory must be listed, and everything listed must be there.
UNLISTED_NAMES = ("package.json", "run_log.json")
UNLISTED_SUFFIXES = (".sumo.log",)


def package_files(pkg: Path) -> list[str]:
    """Every file of a package directory that its manifest must list. A leftover
    `.tmp` (an interrupted write) is refused: such a package is not finished."""
    out = []
    for p in sorted(pkg.rglob("*")):
        rel = p.relative_to(pkg).as_posix()
        if p.is_dir():
            continue
        if p.is_symlink():
            raise PipelineError("foreign_file", f"{rel} is a link; a package holds only its own files")
        if rel.endswith(".tmp"):
            raise PipelineError("unfinished_write", f"{rel} is left from an interrupted write")
        if not p.is_file() or rel in UNLISTED_NAMES:
            continue
        if rel.endswith(UNLISTED_SUFFIXES) and (
                (rel.startswith("sim/") and rel.count("/") == 1)
                or (rel.startswith("replicates/") and rel.count("/") == 2)):
            continue
        out.append(rel)
    return out


def build_package_manifest(pkg: Path, brief: dict[str, Any], audit: dict[str, Any],
                           timeline: dict[str, Any]) -> dict[str, Any]:
    files = [{"file": rel, "bytes": (pkg / rel).stat().st_size, "sha256": sha256_file(pkg / rel)}
             for rel in package_files(pkg)]
    doc = {
        "schema_version": PACKAGE_SCHEMA, "factory_version": FACTORY_VERSION,
        "title": brief["title"], "episode_number": brief["episode_number"],
        "brief_sha256": brief_hash(brief),
        "episode": audit.get("episode"),
        "seconds": timeline["seconds_total"], "frames": timeline["frames_total"],
        "beats": len(timeline["beats"]),
        "truth_audit": {"pass": audit["pass"], "complete": audit["complete"],
                        "audit_hash": audit["audit_hash"], **audit["counts"]},
        "review_first": ["episode.mp4", "contact_sheet.jpg", "truth_audit.json", "lineage.json",
                         "narration.json", "captions.srt"],
        "files": files,
        "package_hash": "",
    }
    return seal(doc, "package_hash")


def run_factory(brief_path: str | Path, out_dir: str | Path, *, resume: bool = True,
                render: bool = True, until: str | None = None, only_shots: list[str] | None = None,
                sim_ports: tuple[int, int] = (55941, 55942),
                log: Callable[[str], None] = print) -> dict[str, Any]:
    """Run (or continue) the factory for one brief. Returns a summary; raises a typed
    `FactoryError` at the first stage that refuses."""
    import sumolib

    if until is not None and until not in STAGES:
        raise PipelineError("bad_stage", f"unknown stage {until!r}; stages are {STAGES}")
    pkg = Path(out_dir).resolve()
    pkg.mkdir(parents=True, exist_ok=True)
    run_log: dict[str, Any] = {"started_unix": round(time.time(), 1), "resume": resume, "stages": []}
    state: dict[str, Any] = {}

    def record(name: str, status: str, t0: float, **extra: Any) -> None:
        row = {"stage": name, "status": status, "seconds": round(time.perf_counter() - t0, 2), **extra}
        run_log["stages"].append(row)
        log(f"[{name}] {status} ({row['seconds']} s)" + (f" {extra}" if extra else ""))

    def finish(summary: dict[str, Any]) -> dict[str, Any]:
        run_log["finished_unix"] = round(time.time(), 1)
        run_log["outcome"] = summary.get("outcome")
        path = pkg / "run_log.json"
        runs = []
        if path.is_file():
            try:
                runs = json.loads(path.read_text(encoding="utf-8")).get("runs", [])
            except Exception:  # noqa: BLE001
                runs = []
        runs.append(run_log)
        write_json(path, {"note": "wall-clock evidence; nothing hashes this file", "runs": runs})
        return summary

    def stop_after(name: str) -> bool:
        return until == name

    try:
        # ---------------------------------------------------------------- brief
        t0 = time.perf_counter()
        raw = read_json(brief_path, "the brief", error=PipelineError)
        brief = normalise_brief(raw)
        bh = brief_hash(brief)
        existing = pkg / "brief.json"
        if existing.is_file():
            try:
                old = brief_hash(json.loads(existing.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                old = None
            if old != bh:
                if resume:
                    raise PipelineError(
                        "package_belongs_to_another_brief",
                        f"{pkg} was built from a different brief; an episode package is never "
                        "continued under another brief (use a new directory, or --no-resume)")
                for child in pkg.iterdir():
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
        if not resume:
            for child in pkg.iterdir():
                shutil.rmtree(child) if child.is_dir() else child.unlink()
        if resume and not render and (pkg / "package.json").is_file():
            raise PipelineError(
                "package_is_finished",
                f"{pkg} holds a finished episode; a run without the render would replace its "
                "engine-confirmed narration, voice and sound with a plan; plan in a new "
                "directory instead")
        write_json(existing, brief)
        world = load_world(brief["world"])
        record("brief", "ran", t0, brief_sha256=bh[:16])
        if stop_after("brief"):
            return finish({"outcome": "stopped", "after": "brief", "package": str(pkg)})

        # ------------------------------------------------------------- simulate
        t0 = time.perf_counter()
        sim_dir = pkg / "sim"
        if resume and _sim_current(sim_dir, brief):
            record("simulate", "reused", t0)
        else:
            if sim_dir.exists():
                shutil.rmtree(sim_dir)
            SIM.run_episode(brief, world, sim_dir, ports=sim_ports, log=log)
            record("simulate", "ran", t0)
        manifest_hash = read_json(sim_dir / "rule_manifest.json", "rule manifest",
                                  error=PipelineError)["manifest_hash"]
        rep_dirs = []
        for k, seed in enumerate(brief["replicate_seeds"]):
            t0 = time.perf_counter()
            rd = pkg / "replicates" / str(seed)
            rep_dirs.append(rd)
            if resume and _sim_current(rd, None, manifest_hash, seed):
                record(f"simulate (repeat seed {seed})", "reused", t0)
                continue
            if rd.exists():
                shutil.rmtree(rd)
            rb = normalise_brief({**raw, "seed": seed, "replicate_seeds": []})
            SIM.run_episode(rb, world, rd, ports=(sim_ports[0] + 10 * (k + 1), sim_ports[1] + 10 * (k + 1)),
                            log=log)
            record(f"simulate (repeat seed {seed})", "ran", t0)
        if stop_after("simulate"):
            return finish({"outcome": "stopped", "after": "simulate", "package": str(pkg)})

        # ---------------------------------------------------------------- facts
        t0 = time.perf_counter()
        facts = F.extract_facts(sim_dir, brief, world, replicate_dirs=rep_dirs)
        same = _same_doc(pkg / "facts.json", facts, "facts_hash")
        write_json(pkg / "facts.json", facts)
        record("facts", "ran", t0, identical_to_previous_run=same,
               cross_checks=len(facts["cross_checks"]))
        state["facts_hash"] = facts["facts_hash"]
        if stop_after("facts"):
            return finish({"outcome": "stopped", "after": "facts", "package": str(pkg)})

        # ---------------------------------------------------------------- story
        t0 = time.perf_counter()
        story = S.select_story(facts, brief)
        same = _same_doc(pkg / "story.json", story, "story_hash")
        write_json(pkg / "story.json", story)
        record("story", "ran", t0, identical_to_previous_run=same, beats=len(story["beats"]),
               seconds_total=story["seconds_total"])
        if stop_after("story"):
            return finish({"outcome": "stopped", "after": "story", "package": str(pkg)})

        # ---------------------------------------------------------------- shots
        t0 = time.perf_counter()
        net = sumolib.net.readNet(world["_net_path"])
        recs = {arm: load_record(sim_dir / f"record_{arm}") for arm in SIM.ARMS}
        blocks = C.load_blocks(REPO_ROOT / world["unreal"]["city_layout"])
        shots = C.plan_shots(story, facts, recs, net, blocks, brief["resolution"])
        same = _same_doc(pkg / "shots.json", shots, "shots_hash")
        write_json(pkg / "shots.json", shots)
        record("shots", "ran", t0, identical_to_previous_run=same)
        if stop_after("shots"):
            return finish({"outcome": "stopped", "after": "shots", "package": str(pkg)})

        # --------------------------------------------------------------- render
        # Before the words: what a sentence says a picture holds is bound to what
        # the engine was measured to hold, so the pictures come first.
        render_dir = pkg / "render"
        render_doc = None
        fps, res = int(brief["fps"]), list(brief["resolution"])
        if render:
            t0 = time.perf_counter()
            done = R.render_episode(story, shots, recs, sim_dir, world, net, blocks, render_dir,
                                    fps=fps, res=res, resume=resume, only=only_shots, log=log)
            record("render", "ran", t0, rendered=done["rendered"], reused=done["reused"])
            if only_shots is not None:
                return finish({"outcome": "stopped", "after": "render (some shots)",
                               "package": str(pkg), **done})
            render_doc = R.seal_render(story, shots, recs, render_dir, fps=fps, res=res, world=world,
                                       level_sha=done["level_file_sha256"])
            write_json(render_dir / "render.json", render_doc)
            if stop_after("render"):
                return finish({"outcome": "stopped", "after": "render", "package": str(pkg)})

        # ------------------------------------------------------------ narration
        t0 = time.perf_counter()
        narration = N.bind_narration(story, facts, shots, rate=brief["voice_rate"], picture=render_doc)
        same = _same_doc(pkg / "narration.json", narration, "narration_hash")
        write_json(pkg / "narration.json", narration)
        record("narration", "ran", t0, identical_to_previous_run=same,
               sentences=narration["counts"]["sentences"])
        if stop_after("narration"):
            return finish({"outcome": "stopped", "after": "narration", "package": str(pkg)})

        # ---------------------------------------------------------------- voice
        t0 = time.perf_counter()
        voice_dir = pkg / "voice"
        voice = None
        if resume and (voice_dir / "voice.json").is_file():
            try:
                cand = V.load_voice(voice_dir / "voice.json")
                if cand.get("narration_hash") == narration["narration_hash"] and \
                        cand["engine"]["voice"] == brief["voice"] and \
                        cand["engine"]["rate"] == brief["voice_rate"]:
                    voice = cand
            except FactoryError:
                voice = None
        if voice is not None:
            record("voice", "reused", t0)
        else:
            if voice_dir.exists():
                shutil.rmtree(voice_dir)
            voice = V.synthesise([{"id": l["id"], "text": l["text"]} for l in narration["lines"]],
                                 voice_dir, voice=brief["voice"], rate=brief["voice_rate"],
                                 narration_hash=narration["narration_hash"])
            write_json(voice_dir / "voice.json", voice)
            record("voice", "ran", t0, spoken_seconds=voice["total_spoken_seconds"])
        if stop_after("voice"):
            return finish({"outcome": "stopped", "after": "voice", "package": str(pkg)})

        # ------------------------------------------------------------- timeline
        t0 = time.perf_counter()
        timeline = T.build_timeline(story, shots, narration, voice, brief)
        same = _same_doc(pkg / "timeline.json", timeline, "timeline_hash")
        write_json(pkg / "timeline.json", timeline)
        caps = T.build_captions(timeline)
        write_text(pkg / "captions.srt", caps["srt"])
        write_text(pkg / "captions.vtt", caps["vtt"])
        record("timeline", "ran", t0, identical_to_previous_run=same,
               seconds_total=timeline["seconds_total"], frames_total=timeline["frames_total"],
               captions=len(caps["cues"]))
        if stop_after("timeline"):
            return finish({"outcome": "stopped", "after": "timeline", "package": str(pkg)})

        # ---------------------------------------------------------------- audio
        t0 = time.perf_counter()
        audio_dir = pkg / "audio"
        audio = None
        if resume and (audio_dir / "audio.json").is_file():
            try:
                cand = AU.load_audio(audio_dir / "audio.json")
                AU.validate_audio_policy(cand, audio_dir, voice_dir)
                if cand.get("timeline_hash") == timeline["timeline_hash"]:
                    audio = cand
            except FactoryError:
                audio = None
        if audio is not None:
            record("audio", "reused", t0)
        else:
            if audio_dir.exists():
                shutil.rmtree(audio_dir)
            audio = AU.build_audio(timeline, voice, voice_dir, audio_dir)
            write_json(audio_dir / "audio.json", audio)
            AU.validate_audio_policy(audio, audio_dir, voice_dir)
            record("audio", "ran", t0, audio_seconds=audio["seconds"])
        if stop_after("audio"):
            return finish({"outcome": "stopped", "after": "audio", "package": str(pkg)})

        if not render:
            t0 = time.perf_counter()
            audit = AD.audit_episode(pkg, brief, world, require_render=False)
            write_json(pkg / "truth_audit.json", audit)
            record("audit", "ran", t0, complete=False, **{"pass": audit["pass"]})
            if not audit["pass"]:
                f0 = audit["failures"][0]
                raise PipelineError("audit_failed", f"{len(audit['failures'])} failure(s); first: "
                                                    f"[{f0['code']}] {f0['where']}: {f0['message']}")
            return finish({"outcome": "planned_not_rendered", "package": str(pkg),
                           "seconds": timeline["seconds_total"], "audit_pass": audit["pass"]})

        # ------------------------------------------------------------- assemble
        t0 = time.perf_counter()
        assembly = None
        if resume and (pkg / "assembly.json").is_file():
            try:
                cand = AS.load_assembly(pkg / "assembly.json")
                AS.verify_assembly(cand, pkg)
                if (cand.get("render_hash"), cand.get("audio_hash"), cand.get("timeline_hash")) == \
                        (render_doc["render_hash"], audio["audio_hash"], timeline["timeline_hash"]):
                    assembly = cand
            except FactoryError:
                assembly = None
        if assembly is not None:
            record("assemble", "reused", t0)
        else:
            assembly = AS.assemble(timeline, render_doc, audio, render_dir, audio_dir, pkg)
            write_json(pkg / "assembly.json", assembly)
            record("assemble", "ran", t0, episode_seconds=assembly["episode"]["seconds"],
                   frames=assembly["episode"]["frames"])
        if stop_after("assemble"):
            return finish({"outcome": "stopped", "after": "assemble", "package": str(pkg)})

        # ---------------------------------------------------------------- audit
        t0 = time.perf_counter()
        audit = AD.audit_episode(pkg, brief, world, require_render=True)
        write_json(pkg / "truth_audit.json", audit)
        write_json(pkg / "lineage.json", AD.lineage_document(pkg, audit))
        record("audit", "ran", t0, complete=True, **{"pass": audit["pass"]},
               sentences=audit["counts"]["sentences"], links=audit["counts"]["lineage_links"])
        if not audit["pass"]:
            (pkg / "package.json").unlink(missing_ok=True)
            f0 = audit["failures"][0]
            raise PipelineError("audit_failed", f"{len(audit['failures'])} failure(s); first: "
                                                f"[{f0['code']}] {f0['where']}: {f0['message']}")
        if stop_after("audit"):
            return finish({"outcome": "stopped", "after": "audit", "package": str(pkg)})

        # -------------------------------------------------------------- package
        t0 = time.perf_counter()
        sheet = contact_sheet(pkg, timeline)
        manifest = build_package_manifest(pkg, brief, audit, timeline)
        write_json(pkg / "package.json", manifest)
        record("package", "ran", t0, files=len(manifest["files"]), contact_sheet=sheet)
        return finish({"outcome": "complete", "package": str(pkg),
                       "episode": str(pkg / "episode.mp4"),
                       "seconds": assembly["episode"]["seconds"],
                       "audit_pass": True, "package_hash": manifest["package_hash"]})
    except FactoryError as e:
        run_log["refused"] = {"stage": e.stage, "code": e.code, "message": e.message[:600]}
        finish({"outcome": f"refused:{e.stage}:{e.code}"})
        raise


def _trip_rows(tripinfo: Path) -> list[tuple]:
    """Every trip and walk row SUMO wrote, attribute by attribute (the header, which
    names this machine's output paths, is left out)."""
    import xml.etree.ElementTree as ET
    rows = []
    for _e, el in ET.iterparse(str(tripinfo), events=("end",)):
        if el.tag in ("tripinfo", "personinfo"):
            rows.append((el.tag, tuple(sorted(el.attrib.items()))))
            el.clear()
    return rows


def resimulate(pkg: Path, brief: dict[str, Any], world: dict[str, Any], scratch: Path,
               ports: tuple[int, int] = (55981, 55982), repeats: bool = True,
               log: Callable[[str], None] = lambda s: None) -> dict[str, Any]:
    """Run the locked world again for the episode and every repeat, and compare.

    A sealed simulation can be re-sealed by anyone who can write the files: the
    cross-checks in facts.py make a lie expensive, but only running SUMO again
    makes it impossible. The simulator is deterministic (gate A), so the records
    must come out byte for byte and every trip row attribute for attribute.
    """
    runs = [("episode", pkg / "sim", brief)]
    for seed in (brief["replicate_seeds"] if repeats else []):
        runs.append((f"repeat {seed}", pkg / "replicates" / str(seed),
                     normalise_brief({**brief, "seed": seed, "replicate_seeds": []})))
    out = {}
    for k, (name, sealed_dir, b) in enumerate(runs):
        t0 = time.perf_counter()
        fresh = scratch / f"run_{k}"
        if fresh.exists():
            shutil.rmtree(fresh)
        doc = SIM.run_episode(b, world, fresh, ports=(ports[0] + 10 * k, ports[1] + 10 * k), log=log)
        result = read_json(sealed_dir / "simulation_result.json", "simulation_result.json",
                           error=PipelineError)
        diffs = []
        for arm in SIM.ARMS:
            want = result["artifacts"][f"{arm}_record_frames"]["sha256"]
            if doc["records"][arm]["frames_sha256"] != want:
                diffs.append(f"{arm} record")
            if _trip_rows(fresh / f"{arm}.tripinfo.xml") != _trip_rows(sealed_dir / f"{arm}.tripinfo.xml"):
                diffs.append(f"{arm} tripinfo")
        if diffs:
            raise PipelineError("simulation_not_reproduced",
                                f"{name}: running the locked world again does not give the sealed "
                                f"{', '.join(diffs)}")
        out[name] = {"records_identical": True, "trip_rows_identical": True,
                     "seconds": round(time.perf_counter() - t0, 1)}
        shutil.rmtree(fresh, ignore_errors=True)
    return out


def decode_check(path: Path) -> None:
    """Decode every frame and sample: a file whose packets look right but whose
    content does not decode is refused."""
    run = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(path),
                          "-f", "null", "-"], capture_output=True, text=True)
    if run.returncode != 0 or run.stderr.strip():
        raise PipelineError("episode_does_not_decode",
                            f"{path.name} does not decode cleanly: {run.stderr.strip()[:400]}")


def verify_package(pkg: str | Path, *, deep: bool = False, scratch: str | Path | None = None,
                   log: Callable[[str], None] = lambda s: None) -> dict[str, Any]:
    """Check a finished package against its own manifest and audit it again.

    `deep` also decodes the whole episode and runs the simulations again
    (`resimulate`): minutes instead of seconds, and the only check that an
    insider who re-seals doctored evidence cannot pass."""
    pkg = Path(pkg)
    manifest = read_json(pkg / "package.json", "package.json", error=PipelineError)
    from .util import verify_seal
    verify_seal(manifest, "package_hash", "package.json")
    try:
        rows = {str(r["file"]): str(r["sha256"]) for r in manifest["files"]}
        sealed_audit = str(manifest["truth_audit"]["audit_hash"])
    except (KeyError, TypeError, AttributeError) as e:
        raise PipelineError("corrupt", f"package.json is not a package manifest: {e!r}")
    if manifest.get("schema_version") != PACKAGE_SCHEMA:
        raise PipelineError("bad_version", f"package.json declares {manifest.get('schema_version')!r}")
    bad = []
    on_disk = set(package_files(pkg))
    for rel in sorted(on_disk - set(rows)):
        bad.append(f"not in the manifest {rel}")
    for rel in sorted(set(rows) - on_disk):
        bad.append(f"missing {rel}")
    for rel in sorted(on_disk & set(rows)):
        if sha256_file(pkg / rel) != rows[rel]:
            bad.append(f"changed {rel}")
    for rel in REQUIRED_FILES:
        if rel not in rows:
            bad.append(f"the manifest does not list {rel}")
    if bad:
        raise PipelineError("package_changed", "; ".join(bad[:6]))
    brief = normalise_brief(read_json(pkg / "brief.json", "brief.json", error=PipelineError))
    world = load_world(brief["world"])
    audit = AD.audit_episode(pkg, brief, world, require_render=True)
    if not audit["pass"]:
        f0 = audit["failures"][0]
        raise PipelineError("audit_failed", f"[{f0['code']}] {f0['where']}: {f0['message']}")
    if audit["audit_hash"] != sealed_audit:
        raise PipelineError("audit_changed", "the audit, run again, does not give the sealed report")
    out: dict[str, Any] = {"files": len(rows), "audit_pass": True,
                           "package_hash": manifest["package_hash"]}
    if deep:
        t0 = time.perf_counter()
        decode_check(pkg / "episode.mp4")
        out["episode_decodes"] = True
        out["episode_decode_seconds"] = round(time.perf_counter() - t0, 1)
        import tempfile
        root = Path(scratch) if scratch else Path(tempfile.mkdtemp(prefix="ldyf_resim_"))
        root.mkdir(parents=True, exist_ok=True)
        out["resimulated"] = resimulate(pkg, brief, world, root, log=log)
    return out
