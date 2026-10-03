"""Stage 7: the timeline. One deterministic edit recipe for the whole episode.

The timeline is the single document the renderer, the caption writer, the
audio mixer and the assembler all read. It says, for every frame of the
episode, which shot is on screen and which simulated second that frame shows:

    sim_second = shot.sim_start + (frame - beat.frame_start) / fps

Simulated time runs at exactly 1x inside every shot. There is no speed ramp,
no freeze, no rewind and no repeated frame, and the timeline refuses to be
built if any of those would be needed: a beat is as long as the story planned
it, and the spoken sentences must fit inside it.

Sentence times come from the MEASURED length of each synthesised wave file. A
sentence that must wait for an event on screen (`after_event`) is placed after
that event's own frame, so the words "it is gone" cannot be heard before the
car is.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import FactoryError
from .util import read_json, seal, verify_seal

TIMELINE_SCHEMA = "episode_timeline_v1"
#: seconds of picture that must remain after the last word of a beat
MIN_TAIL_SECONDS = 0.4

ARM_LABEL = {"baseline": "OPEN CITY", "ruled": "CLOSED CITY"}


class TimelineError(FactoryError):
    stage = "timeline"


def build_timeline(story: dict[str, Any], shots: dict[str, Any], narration: dict[str, Any],
                   voice: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    if narration.get("story_hash") != story.get("story_hash") or \
            narration.get("shots_hash") != shots.get("shots_hash"):
        raise TimelineError("stale_lineage", "the narration was bound to a different story or shots")
    if voice.get("narration_hash") != narration.get("narration_hash"):
        raise TimelineError("stale_lineage", "the voice was synthesised from a different narration")
    fps = int(brief["fps"])
    spoken = {r["id"]: r for r in voice["lines"]}
    by_beat: dict[str, list[dict[str, Any]]] = {}
    for l in narration["lines"]:
        by_beat.setdefault(l["beat"], []).append(l)
        if l["id"] not in spoken:
            raise TimelineError("unspoken_line", f"sentence {l['id']!r} has no synthesised audio")
    pacing = story["pacing"]
    beats = []
    frame = 0
    for b in story["beats"]:
        bid = b["id"]
        shot = shots["shots"].get(bid)
        if shot is None:
            raise TimelineError("missing_shot", f"beat {bid!r} has no shot")
        seconds = float(b["seconds"])
        if abs(shot["seconds"] - seconds) > 1e-9:
            raise TimelineError("stale_lineage", f"beat {bid!r}: the shot was planned for another length")
        n_frames = int(round(seconds * fps))
        if abs(n_frames / fps - seconds) > 1e-9:
            raise TimelineError("bad_length", f"beat {bid!r}: {seconds} s is not a whole number of frames")
        if abs(shot["sim_start"] * fps - round(shot["sim_start"] * fps)) > 1e-6:
            raise TimelineError("off_grid", f"beat {bid!r}: its shot starts at {shot['sim_start']} s, "
                                            "which is not on a frame boundary")
        start_s = frame / fps
        t = float(pacing["lead_in_seconds"])
        ev = b.get("event")
        lines = []
        for l in by_beat.get(bid, []):
            dur = float(spoken[l["id"]]["seconds"])
            if "after_event" in l:
                if ev is None:
                    raise TimelineError("bad_event", f"{l['id']}: waits for an event the beat lacks")
                t = max(t, float(ev["offset_seconds"]) + float(l["after_event"]))
            elif ev is not None and not any("after_event" in x for x in lines) and \
                    t + dur > float(ev["offset_seconds"]) and \
                    any("after_event" in x for x in by_beat[bid]):
                raise TimelineError("narration_overruns_event",
                                    f"{l['id']}: would still be speaking when the event happens")
            lines.append({"id": l["id"], "start": round(start_s + t, 4),
                          "end": round(start_s + t + dur, 4), "beat_offset": round(t, 4),
                          "seconds": dur, "text": l["text"],
                          **({"after_event": l["after_event"]} if "after_event" in l else {})})
            t += dur + float(l["gap_after"])
        last_end = (lines[-1]["end"] - start_s) if lines else 0.0
        if last_end > seconds - MIN_TAIL_SECONDS:
            raise TimelineError(
                "narration_overruns_beat",
                f"beat {bid!r} is {seconds:.0f} s but its sentences end at {last_end:.2f} s; the "
                "timeline does not stretch a shot or speed up a voice to make them fit")
        beats.append({
            "id": bid, "role": b["role"],
            "start": round(start_s, 4), "seconds": seconds, "end": round(start_s + seconds, 4),
            "frame_start": frame, "frames": n_frames,
            "shot": {"arm": shot["arm"], "sim_start": shot["sim_start"], "sim_end": shot["sim_end"],
                     "sim_rate": 1.0, "camera": {k: shot["camera"][k] for k in ("loc", "rot", "fov_deg")}},
            "label": ARM_LABEL[shot["arm"]],
            "lines": lines,
            "silence_after_last_word": round(seconds - last_end, 3),
            **({"event": {"second": ev["second"], "offset_seconds": ev["offset_seconds"],
                          "episode_second": round(start_s + ev["offset_seconds"], 4),
                          "what": ev["what"]}} if ev else {}),
        })
        frame += n_frames
    total = frame / fps
    lo, hi = brief["target_seconds"]
    if not lo <= total <= hi:
        raise TimelineError("length_out_of_range", f"the timeline runs {total:.1f} s; the brief asks "
                                                   f"for {lo:.0f}-{hi:.0f} s")
    speech = sum(l["seconds"] for b in beats for l in b["lines"])
    doc = {
        "schema_version": TIMELINE_SCHEMA,
        "story_hash": story["story_hash"], "shots_hash": shots["shots_hash"],
        "narration_hash": narration["narration_hash"], "voice_hash": voice["voice_hash"],
        "fps": fps, "resolution": list(brief["resolution"]),
        "frame_rule": "sim_second = shot.sim_start + (frame - beat.frame_start) / fps",
        "sim_rate": 1.0,
        "edits_refused": ["freeze frame", "rewind", "speed ramp", "repeated footage", "filler shot"],
        "beats": beats,
        "seconds_total": round(total, 4), "frames_total": frame,
        "seconds_spoken": round(speech, 3), "seconds_without_words": round(total - speech, 3),
        "timeline_hash": "",
    }
    return seal(doc, "timeline_hash")


# --- captions ----------------------------------------------------------------------

def _stamp(t: float, sep: str) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def build_captions(timeline: dict[str, Any], *, min_seconds: float = 1.2,
                   linger_seconds: float = 0.35) -> dict[str, Any]:
    """One caption per spoken sentence: its exact text, over its measured audio."""
    rows = [l for b in timeline["beats"] for l in b["lines"]]
    cues = []
    for i, l in enumerate(rows):
        end = max(l["end"] + linger_seconds, l["start"] + min_seconds)
        if i + 1 < len(rows):
            end = min(end, rows[i + 1]["start"] - 0.05)
        end = min(end, timeline["seconds_total"])
        if end <= l["start"]:
            raise TimelineError("bad_caption", f"caption {l['id']!r} has no time on screen")
        cues.append({"index": i + 1, "id": l["id"], "start": round(l["start"], 3),
                     "end": round(end, 3), "text": l["text"]})
    srt = "".join(f"{c['index']}\n{_stamp(c['start'], ',')} --> {_stamp(c['end'], ',')}\n{c['text']}\n\n"
                  for c in cues)
    vtt = "WEBVTT\n\n" + "".join(
        f"{c['index']}\n{_stamp(c['start'], '.')} --> {_stamp(c['end'], '.')}\n{c['text']}\n\n"
        for c in cues)
    return {"cues": cues, "srt": srt, "vtt": vtt}


def load_timeline(path: str | Path) -> dict[str, Any]:
    doc = read_json(path, "timeline.json", error=TimelineError)
    if doc.get("schema_version") != TIMELINE_SCHEMA:
        raise TimelineError("bad_version", f"timeline.json declares {doc.get('schema_version')!r}")
    try:
        verify_seal(doc, "timeline_hash", "timeline.json")
    except FactoryError as e:
        raise TimelineError("corrupt", e.message)
    return doc
