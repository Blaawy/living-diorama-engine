"""Stage 10: assemble the episode. Segments in timeline order, sound, captions, labels.

The edit is the timeline and nothing else: each beat's rendered segment, whole,
in order, cut to cut. No transition is added, no segment is trimmed, slowed,
looped or reused. The assembled picture must hold exactly the timeline's number
of frames or the stage refuses.

Two things are drawn over the picture, both read from the timeline:

* the ARM and the SIMULATED SECOND, top left ("OPEN CITY  second 103"). The two
  cities look alike; a viewer is never left to guess which one is on screen.
  The second is computed per frame from the shot's own start, so it is the
  record's clock, not a decoration;
* the CAPTIONS: the sentences the truth audit approved, word for word, each
  over the measured length of its own audio.

`episode.mp4` carries both. The captions are also written as sidecar files.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from . import FactoryError
from .timeline import build_captions
from .util import read_json, seal, sha256_file, verify_seal, write_text

ASSEMBLY_SCHEMA = "episode_assembly_v1"
FONT = "C\\:/Windows/Fonts/arialbd.ttf"


class AssemblyError(FactoryError):
    stage = "assemble"


def _run(args: list[str], what: str, cwd: Path | None = None) -> str:
    try:
        run = subprocess.run(args, capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    except FileNotFoundError:
        raise AssemblyError("no_ffmpeg", "ffmpeg is not installed")
    if run.returncode != 0:
        raise AssemblyError("ffmpeg_failed", f"{what}: {run.stderr[-600:]}")
    return run.stdout


def probe(path: Path) -> dict[str, Any]:
    out = _run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                "stream=codec_type,codec_name,width,height,r_frame_rate,nb_read_frames,duration:"
                "format=duration,size", "-of", "json", str(path)], "probe")
    doc = json.loads(out)
    v = next((s for s in doc["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in doc["streams"] if s["codec_type"] == "audio"), None)
    if v is None:
        raise AssemblyError("bad_output", f"{path.name} has no picture")
    return {"video_codec": v["codec_name"], "width": int(v["width"]), "height": int(v["height"]),
            "frame_rate": v["r_frame_rate"], "frames": int(v.get("nb_read_frames") or -1),
            "audio_codec": a["codec_name"] if a else None,
            "audio_seconds": round(float(a["duration"]), 3) if a and a.get("duration") else None,
            "seconds": round(float(doc["format"]["duration"]), 3),
            "bytes": int(doc["format"]["size"])}


def probe_packets(path: Path) -> dict[str, Any]:
    """What the FILE holds, read by ffprobe without decoding (packet counts): fast enough
    for the audit to run on every verify, so a seal never stands in for the file."""
    out = _run(["ffprobe", "-v", "error", "-count_packets", "-show_entries",
                "stream=codec_type,codec_name,width,height,r_frame_rate,nb_read_packets:"
                "format=duration", "-of", "json", str(path)], "probe")
    try:
        doc = json.loads(out)
        v = next((s for s in doc["streams"] if s["codec_type"] == "video"), None)
        a = next((s for s in doc["streams"] if s["codec_type"] == "audio"), None)
        if v is None:
            raise AssemblyError("bad_output", f"{path.name} has no picture")
        return {"video_codec": v["codec_name"], "width": int(v["width"]), "height": int(v["height"]),
                "frame_rate": v["r_frame_rate"], "frames": int(v["nb_read_packets"]),
                "audio_codec": a["codec_name"] if a else None,
                "seconds": round(float(doc["format"]["duration"]), 3)}
    except (KeyError, ValueError, TypeError) as e:
        raise AssemblyError("bad_output", f"{path.name} is not a readable video: {e!r}")


def _label_filter(timeline: dict[str, Any]) -> str:
    """One drawtext per beat: arm + the record's own second for the frame on screen."""
    h = int(timeline["resolution"][1])
    size, pad = max(18, h // 30), max(12, h // 45)
    parts = []
    for b in timeline["beats"]:
        a, e = b["start"], b["end"]
        sim0 = b["shot"]["sim_start"]
        text = f"{b['label']}   second %{{eif\\:{sim0:.4f}+t-{a:.4f}\\:d}}"
        parts.append(
            f"drawtext=fontfile='{FONT}':text='{text}':x={pad * 2}:y={pad * 2}:fontsize={size}:"
            f"fontcolor=white:box=1:boxcolor=black@0.55:boxborderw={pad}:"
            f"enable='gte(t\\,{a:.4f})*lt(t\\,{e:.4f})'")
    return ",".join(parts)


def assemble(timeline: dict[str, Any], render: dict[str, Any], audio: dict[str, Any],
             render_dir: str | Path, audio_dir: str | Path, out_dir: str | Path) -> dict[str, Any]:
    render_dir, audio_dir, out_dir = Path(render_dir), Path(audio_dir), Path(out_dir)
    if render.get("shots_hash") != timeline["shots_hash"] or \
            audio.get("timeline_hash") != timeline["timeline_hash"]:
        raise AssemblyError("stale_lineage", "the render or the sound track belongs to another timeline")
    by_beat = render["shots"]
    lines = []
    for b in timeline["beats"]:
        row = by_beat.get(b["id"])
        seg = render_dir / b["id"] / "segment.mp4"
        if row is None or not seg.is_file():
            raise AssemblyError("render_incomplete", f"beat {b['id']!r} has no rendered segment")
        if sha256_file(seg) != row["segment_sha256"]:
            raise AssemblyError("stale_lineage", f"beat {b['id']!r}: the segment on disk is not the "
                                                 "one the render manifest sealed")
        if row["frames"] != b["frames"]:
            raise AssemblyError("render_incomplete", f"beat {b['id']!r}: segment has {row['frames']} "
                                                     f"frames, the timeline {b['frames']}")
        lines.append("file '" + str(seg.resolve()).replace("\\", "/") + "'\n")
    mix = audio_dir / "episode.wav"
    mix_row = next((s for s in audio["sources"] if s["file"] == "episode.wav"), None)
    if mix_row is None or not mix.is_file() or sha256_file(mix) != mix_row["sha256"]:
        raise AssemblyError("stale_lineage", "the mixed sound track is missing or not the sealed one")

    caps = build_captions(timeline)
    write_text(out_dir / "captions.srt", caps["srt"])
    write_text(out_dir / "captions.vtt", caps["vtt"])
    work = out_dir / "_assemble"
    work.mkdir(parents=True, exist_ok=True)
    (work / "concat.txt").write_text("".join(lines), encoding="utf-8")
    picture = work / "picture.mp4"
    _run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-f", "concat", "-safe", "0",
          "-i", str(work / "concat.txt"), "-c", "copy", str(picture)], "concat")
    fps = int(timeline["fps"])
    h = int(timeline["resolution"][1])
    style = (f"FontName=Arial,FontSize={max(14, h // 54)},PrimaryColour=&H00FFFFFF,"
             "OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=40")
    # run from the package directory so the caption file is a plain relative name
    vf = _label_filter(timeline) + f",subtitles=captions.srt:force_style='{style}'"
    (work / "filter.txt").write_text(vf, encoding="utf-8")
    final = out_dir / "episode.mp4"
    # `-/filter:v <file>` reads the filter graph from a file; `-filter_script` is gone
    # from current FFmpeg
    _run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(picture.resolve()),
          "-i", str(mix.resolve()), "-/filter:v", str((work / "filter.txt").resolve()),
          "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
          "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "160k",
          "-movflags", "+faststart", "-map_metadata", "-1", str(final.resolve())],
         "final encode", cwd=out_dir)
    info = probe(final)
    raw = probe(picture)
    if raw["frames"] != timeline["frames_total"] or info["frames"] != timeline["frames_total"]:
        raise AssemblyError("bad_output", f"the episode holds {info['frames']} frames (picture "
                                          f"{raw['frames']}), the timeline {timeline['frames_total']}")
    if info["audio_codec"] is None:
        raise AssemblyError("bad_output", "the episode has no sound")
    if abs(info["seconds"] - timeline["seconds_total"]) > 0.25:
        raise AssemblyError("bad_output", f"the episode runs {info['seconds']} s, the timeline "
                                          f"{timeline['seconds_total']} s")
    for p in work.iterdir():
        p.unlink()
    work.rmdir()
    doc = {
        "schema_version": ASSEMBLY_SCHEMA,
        "timeline_hash": timeline["timeline_hash"], "render_hash": render["render_hash"],
        "audio_hash": audio["audio_hash"],
        "edit": {"order": [b["id"] for b in timeline["beats"]], "cuts": "hard cut at every beat",
                 "segments_trimmed": 0, "segments_reused": 0, "speed_changes": 0,
                 "transitions": 0},
        "overlays": ["arm label and the record's second (drawtext, from the timeline)",
                     "captions (the audited sentences, from captions.srt)"],
        "captions": {"cues": len(caps["cues"]),
                     "srt_sha256": sha256_file(out_dir / "captions.srt"),
                     "vtt_sha256": sha256_file(out_dir / "captions.vtt")},
        "episode": {"file": "episode.mp4", "sha256": sha256_file(final), **info},
        "assembly_hash": "",
    }
    return seal(doc, "assembly_hash")


def verify_assembly(doc: dict[str, Any], out_dir: str | Path) -> None:
    try:
        verify_seal(doc, "assembly_hash", "assembly.json")
    except FactoryError as e:
        raise AssemblyError("corrupt", e.message)
    p = Path(out_dir) / doc["episode"]["file"]
    if not p.is_file():
        raise AssemblyError("missing", "the assembled episode is missing")
    if sha256_file(p) != doc["episode"]["sha256"]:
        raise AssemblyError("corrupt", "the episode on disk is not the one that was sealed")


def load_assembly(path: str | Path) -> dict[str, Any]:
    doc = read_json(path, "assembly.json", error=AssemblyError)
    if doc.get("schema_version") != ASSEMBLY_SCHEMA:
        raise AssemblyError("bad_version", f"assembly.json declares {doc.get('schema_version')!r}")
    return doc
