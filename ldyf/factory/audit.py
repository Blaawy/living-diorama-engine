"""Stage 11: the truth audit. Re-derive the episode from its evidence, or refuse it.

The audit trusts no document the pipeline wrote. It reads the package from
disk and, link by link, RE-DERIVES each stage from the stage before it and
compares hashes:

    brief  ->  rule manifest  ->  sealed simulation (both arms, records re-hashed)
           ->  facts          (extracted AGAIN from the sealed artefacts)
           ->  story          (selected AGAIN from those facts)
           ->  shots          (planned and measured AGAIN from the records)
           ->  narration      (bound AGAIN; every check evaluated again)
           ->  voice, timeline, sound track (hashes, policy, rebuilt timeline)
           ->  render         (every shot finished, current, held in the engine)
           ->  episode.mp4    (hash, frame count)

and then audits every spoken sentence on its own:

* each NUMERAL in a sentence must equal a cited measurement at the precision
  stated -- checked by `ldyf.truth_audit`, the Phase 1 auditor, which shares no
  code with the narrator;
* each CHECK the sentence carries is evaluated again from the files on disk;
* a sentence that binds nothing must be free of numerals and claim words;
* a sentence about the picture is tied to its shot: the arm, the simulated
  window, what the planner measured and what the engine measured.

The result is `truth_audit.json`: one row per sentence and per shot, the whole
lineage chain, and `pass`. Any failure makes `pass` false, and the pipeline
then refuses to package the episode.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import truth_audit as TA
from . import FACTORY_VERSION, FactoryError
from . import assemble as AS
from . import audio as AU
from . import camera as C
from . import facts as F
from . import narration as N
from . import render as R
from . import story as S
from . import timeline as T
from . import voice as V
from .brief import brief_hash
from .record import load_record
from .util import seal, sha256_file
from .world import REPO_ROOT

AUDIT_SCHEMA = "episode_truth_audit_v1"


class AuditError(FactoryError):
    stage = "audit"


def _cite_pair(ref: str, beat: str, engine: bool) -> tuple[str, str] | None:
    """A narration reference as the (artefact, dotted field) pair the Phase 1 auditor reads.

    What a picture HOLDS is cited from the engine's measurement (render.json)
    once the episode is rendered; everything else about a shot from shots.json.
    """
    if ref.startswith("fact:"):
        return "facts.json", f"facts.{ref[5:]}.value"
    if ref.startswith("text:"):
        return "facts.json", ref[5:]
    if ref.startswith("shot@"):
        which, field = ref[5:].split(":", 1)
    elif ref.startswith("shot:"):
        which, field = beat, ref[5:]
    else:
        return None
    if engine and field in N.ENGINE_FIELDS:
        return "render/render.json", f"shots.{which}.engine_{field}"
    return "shots.json", f"shots.{which}.{field}"


def audit_episode(pkg: str | Path, brief: dict[str, Any], world: dict[str, Any], *,
                  require_render: bool = True) -> dict[str, Any]:
    """Audit a package directory. Returns the sealed report; `pass` says whether it holds."""
    import sumolib

    pkg = Path(pkg)
    failures: list[dict[str, str]] = []
    chain: list[dict[str, Any]] = []

    def fail(code: str, where: str, message: str) -> None:
        failures.append({"code": code, "where": where, "message": message[:600]})

    def link(frm: str, to: str, what: str, expected: Any, actual: Any) -> None:
        ok = expected is not None and expected == actual
        chain.append({"from": frm, "to": to, "binds": what, "expected": expected, "actual": actual,
                      "ok": ok})
        if not ok:
            fail("stale_lineage", f"{frm} -> {to}", f"{what}: {to} names {actual!r}, {frm} is {expected!r}")

    def stage(where: str, fn):
        try:
            return fn()
        except FactoryError as e:
            fail(e.code, where, f"[{e.stage}] {e.message}")
        except Exception as e:  # noqa: BLE001 - an audit never crashes; it reports
            fail("unreadable", where, repr(e))
        return None

    bh = brief_hash(brief)
    sim_dir = pkg / "sim"
    on_disk_brief = stage("brief.json", lambda: json.loads((pkg / "brief.json").read_text(encoding="utf-8")))
    if on_disk_brief is not None:
        link("brief", "brief.json", "normalised brief", bh, brief_hash(on_disk_brief))

    # --- simulation, re-verified; facts, re-extracted ------------------------------
    docs = stage("sim", lambda: F.load_verified_simulation(sim_dir, brief))
    rep_dirs = [pkg / "replicates" / str(s) for s in brief["replicate_seeds"]]
    facts_disk = stage("facts.json", lambda: F.load_facts(pkg / "facts.json"))
    facts_again = stage("facts (re-extracted)",
                        lambda: F.extract_facts(sim_dir, brief, world, replicate_dirs=rep_dirs))
    recs = {}
    if docs is not None:
        link("brief", "simulation.json", "brief_sha256", bh, docs["sim"].get("brief_sha256"))
        link("rule_manifest.json", "simulation.json", "rule_manifest_hash",
             docs["manifest"].get("manifest_hash"), docs["sim"].get("rule_manifest_hash"))
        link("simulation_result.json", "simulation.json", "simulation_result_hash",
             docs["result"].get("result_hash"), docs["sim"].get("simulation_result_hash"))
        for arm in ("baseline", "ruled"):
            rec = stage(f"record_{arm}", lambda arm=arm: load_record(sim_dir / f"record_{arm}"))
            if rec is not None:
                recs[arm] = rec
                link(f"record_{arm}/frames.bin", "simulation_result.json", "record frames sha256",
                     rec.frames_sha256, docs["result"]["artifacts"][f"{arm}_record_frames"]["sha256"])
    if facts_disk is not None and facts_again is not None:
        link("sealed simulation", "facts.json", "facts_hash (re-extracted)",
             facts_again["facts_hash"], facts_disk["facts_hash"])
    if facts_disk is not None and docs is not None:
        link("simulation_result.json", "facts.json", "simulation_result_hash",
             docs["result"].get("result_hash"), facts_disk.get("simulation_result_hash"))
        for arm, rec in recs.items():
            link(f"record_{arm}/frames.bin", "facts.json", f"records.{arm}",
                 rec.frames_sha256, (facts_disk.get("records") or {}).get(arm))
    facts = facts_disk

    # --- story, shots, narration: each derived again -------------------------------
    story = stage("story.json", lambda: S.load_story(pkg / "story.json"))
    shots = stage("shots.json", lambda: C.load_shots(pkg / "shots.json"))
    narration = stage("narration.json", lambda: N.load_narration(pkg / "narration.json"))
    net = blocks = None
    if facts is not None and story is not None:
        again = stage("story (re-selected)", lambda: S.select_story(facts, brief))
        if again is not None:
            link("facts.json", "story.json", "story_hash (re-selected)", again["story_hash"],
                 story["story_hash"])
        link("facts.json", "story.json", "facts_hash", facts["facts_hash"], story.get("facts_hash"))
    if facts is not None and story is not None and shots is not None and len(recs) == 2:
        net = sumolib.net.readNet(world["_net_path"])
        blocks = stage("city layout", lambda: C.load_blocks(REPO_ROOT / world["unreal"]["city_layout"]))
        if blocks is not None:
            again = stage("shots (re-planned)",
                          lambda: C.plan_shots(story, facts, recs, net, blocks, brief["resolution"]))
            if again is not None:
                link("story.json + records", "shots.json", "shots_hash (re-planned and re-measured)",
                     again["shots_hash"], shots["shots_hash"])
        link("story.json", "shots.json", "story_hash", story["story_hash"], shots.get("story_hash"))
    render = None
    fps, res = int(brief["fps"]), list(brief["resolution"])
    if require_render:
        render = stage("render.json", lambda: R.load_render(pkg / "render" / "render.json"))
        if None not in (render, story, shots) and len(recs) == 2:
            again = stage("render (re-sealed from the shots on disk)",
                          lambda: R.seal_render(story, shots, recs, pkg / "render", fps=fps, res=res,
                                                world=world, level_sha=render.get("level_file_sha256")))
            if again is not None:
                link("story + shots + segments", "render.json", "render_hash (re-sealed)",
                     again["render_hash"], render["render_hash"])
            link("shots.json", "render.json", "shots_hash", shots["shots_hash"], render.get("shots_hash"))
    if None not in (facts, story, shots, narration):
        again = stage("narration (re-bound)",
                      lambda: N.bind_narration(story, facts, shots, rate=brief["voice_rate"],
                                               picture=render))
        if again is not None:
            link("story.json + facts.json + shots.json" + (" + render.json" if render else ""),
                 "narration.json", "narration_hash (re-bound)", again["narration_hash"],
                 narration["narration_hash"])
        if require_render and narration.get("picture_claims") != "engine_confirmed":
            fail("unconfirmed_picture", "narration.json",
                 "the narration's statements about the picture were never bound to the engine's "
                 "measurement of the rendered shots")

    # --- every sentence, on its own --------------------------------------------------
    claims: list[dict[str, Any]] = []
    if None not in (facts, shots, narration) and not (require_render and render is None):
        artefact_sha = facts.get("artifacts") or {}
        engine = render is not None
        shots_p = {**shots, "_picture": render} if engine else shots
        for l in narration["lines"]:
            try:
                row: dict[str, Any] = {"id": l["id"], "beat": l["beat"], "kind": l["kind"],
                                       "text": l["text"], "verdict": "supported", "reasons": []}
                refs = [c["ref"] for c in l["cites"]]
                for c in l["checks"]:
                    refs += [x for x in (c["left"], c["right"]) if isinstance(x, str)]
                pairs = [p for p in (_cite_pair(r, l["beat"], engine) for r in refs) if p is not None]
                if l["kind"] == "say":
                    if pairs:
                        row["reasons"].append("a 'say' sentence may bind no evidence")
                elif not pairs:
                    row["reasons"].append("the sentence cites no evidence")
                else:
                    rep = TA.audit_claims([{"text": l["text"], "cites": [list(p) for p in pairs]}], pkg)
                    row["reasons"] += rep["claims"][0]["reasons"]
                    row["cited"] = [{"artefact": c["artefact"], "field": c["field"], "value": c["value"]}
                                    for c in rep["claims"][0]["citations"]]
                numeric = any("decimals" in c for c in l["cites"])
                row["reasons"] += N.lint(l["text"], l["kind"], numeric, bool(l["checks"]))
                checks = []
                for c in l["checks"]:
                    try:
                        ev = N.evaluate_check([c["left"], c["op"], c["right"]], facts, shots_p, l["beat"])
                    except FactoryError as e:
                        row["reasons"].append(f"check cannot be evaluated: {e.message}")
                        continue
                    checks.append(ev)
                    if not ev["holds"]:
                        row["reasons"].append(f"check does not hold: {ev['left']} {ev['op']} {ev['right']} "
                                              f"({ev['left_value']!r} vs {ev['right_value']!r})")
                row["checks"] = checks
                sources = sorted({a for c in l["cites"] if c["ref"].startswith("fact:")
                                  for a in facts["facts"].get(c["ref"][5:], {}).get("from", [])})
                row["sealed_artefacts"] = {a: artefact_sha.get(a) for a in sources}
                if l["kind"] == "shot" or any(r.startswith("shot") for r in refs):
                    s = shots["shots"].get(l["beat"]) or {}
                    row["shot"] = {"beat": l["beat"], "arm": s.get("arm"),
                                   "sim_window": [s.get("sim_start"), s.get("sim_end")],
                                   "record_frames_sha256": s.get("record_frames_sha256")}
                if row["reasons"]:
                    row["verdict"] = "refused"
                    fail("overclaim", l["id"], f"{l['text']!r}: " + " | ".join(row["reasons"]))
                claims.append(row)
            except FactoryError:
                raise
            except Exception as e:  # noqa: BLE001 - a malformed sentence record is a finding, not a crash
                fail("unreadable", str(l.get("id", "?")) if isinstance(l, dict) else "narration line",
                     f"the narration line cannot be audited: {e!r}")

    # --- voice, timeline, captions, sound --------------------------------------------
    voice = stage("voice.json", lambda: V.load_voice(pkg / "voice" / "voice.json"))
    timeline = stage("timeline.json", lambda: T.load_timeline(pkg / "timeline.json"))
    if voice is not None and narration is not None:
        link("narration.json", "voice.json", "narration_hash", narration["narration_hash"],
             voice.get("narration_hash"))
        want = {l["id"]: V.sha256_bytes(V.spoken_text(l["text"]).encode("utf-8"))
                for l in narration["lines"]}
        have = {r["id"]: r["text_sha256"] for r in voice["lines"]}
        if want != have:
            fail("stale_lineage", "voice.json", "the spoken sentences are not the audited sentences")
    if None not in (story, shots, narration, voice, timeline):
        again = stage("timeline (rebuilt)",
                      lambda: T.build_timeline(story, shots, narration, voice, brief))
        if again is not None:
            link("story + shots + narration + voice", "timeline.json", "timeline_hash (rebuilt)",
                 again["timeline_hash"], timeline["timeline_hash"])
    if timeline is not None and narration is not None:
        caps = stage("captions", lambda: T.build_captions(timeline))
        srt = pkg / "captions.srt"
        if caps is not None:
            texts = [c["text"] for c in caps["cues"]]
            if texts != [l["text"] for l in narration["lines"]]:
                fail("stale_lineage", "captions", "the captions are not the audited sentences")
            if srt.is_file() and srt.read_text(encoding="utf-8") != caps["srt"]:
                fail("stale_lineage", "captions.srt", "the caption file is not the one the timeline gives")
    audio = stage("audio.json", lambda: AU.load_audio(pkg / "audio" / "audio.json"))
    if audio is not None:
        stage("audio policy", lambda: AU.validate_audio_policy(audio, pkg / "audio", pkg / "voice"))
        if timeline is not None:
            link("timeline.json", "audio.json", "timeline_hash", timeline["timeline_hash"],
                 audio.get("timeline_hash"))

    # --- render and the assembled episode --------------------------------------------
    shot_rows: list[dict[str, Any]] = []
    assembly = None
    if require_render:
        if render is not None and narration is not None:
            link("render.json", "narration.json", "render_hash", render["render_hash"],
                 narration.get("render_hash"))
        assembly = stage("assembly.json", lambda: AS.load_assembly(pkg / "assembly.json"))
        if assembly is not None:
            stage("episode.mp4", lambda: AS.verify_assembly(assembly, pkg))
            if render is not None:
                link("render.json", "assembly.json", "render_hash", render["render_hash"],
                     assembly.get("render_hash"))
            if audio is not None:
                link("audio.json", "assembly.json", "audio_hash", audio["audio_hash"],
                     assembly.get("audio_hash"))
            if timeline is not None:
                link("timeline.json", "assembly.json", "timeline_hash", timeline["timeline_hash"],
                     assembly.get("timeline_hash"))
                # the FILE is measured, not the document that describes it
                got = stage("episode.mp4 (probed)", lambda: AS.probe_packets(pkg / "episode.mp4"))
                if got is not None:
                    want = [timeline["frames_total"], list(timeline["resolution"]),
                            f"{int(timeline['fps'])}/1"]
                    have = [got["frames"], [got["width"], got["height"]], got["frame_rate"]]
                    if have != want:
                        fail("bad_output", "episode.mp4", f"the file holds frames, size, rate {have}; "
                                                          f"the timeline gives {want}")
                    if got["audio_codec"] is None:
                        fail("bad_output", "episode.mp4", "the file has no sound")
                    if abs(got["seconds"] - float(timeline["seconds_total"])) > 0.25:
                        fail("bad_output", "episode.mp4", f"the file runs {got['seconds']} s, the "
                                                          f"timeline {timeline['seconds_total']} s")
                    lo, hi = brief["target_seconds"]
                    if not lo <= got["seconds"] <= hi:
                        fail("length_out_of_range", "episode.mp4",
                             f"{got['seconds']} s is outside {lo}-{hi} s")
    if shots is not None:
        rendered = (render or {}).get("shots") or {}
        for bid, s in shots["shots"].items():
            e = rendered.get(bid)
            shot_rows.append({
                "beat": bid, "arm": s["arm"], "sim_window": [s["sim_start"], s["sim_end"]],
                "subjects": s["subjects"]["group"], "subjects_in_group": s["subjects"]["count"],
                "counted_where": s["counted_where"], "require": s["require"],
                "record_visible_min": s["subjects_visible_min"],
                "record_visible_max": s["subjects_visible_max"],
                "samples_meeting_requirement": s["samples_meeting_requirement"],
                "engine_visible_min": e["engine_subjects_visible_min"] if e else None,
                "engine_visible_max": e["engine_subjects_visible_max"] if e else None,
                "engine_max_position_error_cm": e["engine_max_position_error_cm"] if e else None,
                "sight_line_blocked_by": e["sight_line_blocked_by"] if e else None,
                "segment_sha256": e["segment_sha256"] if e else None,
                "record_frames_sha256": s["record_frames_sha256"],
                "verdict": "pass" if (e or not require_render) else "not_rendered"})
            if require_render and e is None:
                fail("render_incomplete", bid, "the shot has no finished render")

    supported = sum(1 for c in claims if c["verdict"] == "supported")
    doc = {
        "schema_version": AUDIT_SCHEMA,
        "factory_version": FACTORY_VERSION,
        "brief_sha256": bh,
        "complete": bool(require_render),
        "pass": not failures and bool(claims),
        "failures": failures,
        "counts": {
            "sentences": len(claims), "sentences_supported": supported,
            "sentences_refused": len(claims) - supported,
            "sentences_with_numerals_or_checks": sum(1 for c in claims if c["kind"] != "say"),
            "checks_evaluated": sum(len(c.get("checks", [])) for c in claims),
            "shots": len(shot_rows),
            "shots_passing": sum(1 for s in shot_rows if s["verdict"] == "pass"),
            "lineage_links": len(chain), "lineage_links_ok": sum(1 for c in chain if c["ok"]),
        },
        "lineage": chain,
        "shots": shot_rows,
        "claims": claims,
        "episode": (assembly or {}).get("episode"),
        "audit_hash": "",
    }
    return seal(doc, "audit_hash")


def lineage_document(pkg: str | Path, audit: dict[str, Any]) -> dict[str, Any]:
    """brief -> rule -> simulation -> facts -> story -> narration -> shots -> render, by hash."""
    pkg = Path(pkg)

    def h(rel: str) -> str | None:
        p = pkg / rel
        return sha256_file(p) if p.is_file() else None

    def field(rel: str, name: str) -> Any:
        try:
            return json.loads((pkg / rel).read_text(encoding="utf-8")).get(name)
        except Exception:  # noqa: BLE001
            return None

    steps = [
        ("episode brief", "brief.json", None, None),
        ("rule manifest", "sim/rule_manifest.json", "manifest_hash", "sim/rule_manifest.json"),
        ("simulation result", "sim/simulation_result.json", "result_hash", "sim/simulation_result.json"),
        ("simulation record (baseline)", "sim/record_baseline/frames.bin", None, None),
        ("simulation record (ruled)", "sim/record_ruled/frames.bin", None, None),
        ("consequence extraction", "facts.json", "facts_hash", "facts.json"),
        ("selected story beats", "story.json", "story_hash", "story.json"),
        ("camera shots", "shots.json", "shots_hash", "shots.json"),
        ("narration claims", "narration.json", "narration_hash", "narration.json"),
        ("voice", "voice/voice.json", "voice_hash", "voice/voice.json"),
        ("timeline", "timeline.json", "timeline_hash", "timeline.json"),
        ("sound track", "audio/audio.json", "audio_hash", "audio/audio.json"),
        ("rendered shots", "render/render.json", "render_hash", "render/render.json"),
        ("assembled episode", "assembly.json", "assembly_hash", "assembly.json"),
        ("rendered output", "episode.mp4", None, None),
    ]
    doc = {
        "schema_version": "episode_lineage_v1",
        "chain": [{"step": name, "file": rel, "file_sha256": h(rel),
                   **({"sealed_hash": field(src, key)} if key else {})}
                  for name, rel, key, src in steps],
        "links_checked": audit["counts"]["lineage_links"],
        "links_ok": audit["counts"]["lineage_links_ok"],
        "audit_hash": audit["audit_hash"],
        "lineage_hash": "",
    }
    return seal(doc, "lineage_hash")
