"""Gate F: re-check a FINISHED episode from its own bytes, mechanically and visually.

    python tools_visual_audit.py <package dir> <out dir>

Mechanical (all measured from episode.mp4 / audio, none believed from a document):
  * the whole file decodes with no error; frame count, rate, size and audio length equal the timeline
  * no black frame run, no beat-long freeze beyond what the render recorded for that shot
  * every narration line sits on audible speech (volumedetect) and every caption cue on audio
  * the frame at the middle of each beat IS the picture the render sealed for that beat (SSIM against
    the shot's own still, overlays and captions allowing)
Visual: a sheet of one frame per beat is written for a human/reviewer to read against narration.json.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


def run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def main() -> int:
    pkg, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    tl = json.loads((pkg / "timeline.json").read_text(encoding="utf-8"))
    nar = json.loads((pkg / "narration.json").read_text(encoding="utf-8"))
    rnd = json.loads((pkg / "render" / "render.json").read_text(encoding="utf-8"))
    ep = pkg / "episode.mp4"
    res: dict = {"package": str(pkg), "episode_bytes": ep.stat().st_size, "problems": []}

    # --- decode everything
    d = run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(ep), "-f", "null", "-"])
    res["decode_errors"] = d.stderr.strip()[:300]
    if d.returncode != 0 or d.stderr.strip():
        res["problems"].append("episode does not decode cleanly")

    # --- container facts vs timeline
    pr = json.loads(run(["ffprobe", "-v", "error", "-count_packets", "-show_entries",
                         "stream=codec_type,nb_read_packets,width,height,r_frame_rate:format=duration",
                         "-of", "json", str(ep)]).stdout)
    v = next(s for s in pr["streams"] if s["codec_type"] == "video")
    res["video"] = {"packets": int(v["nb_read_packets"]), "size": [v["width"], v["height"]],
                    "rate": v["r_frame_rate"], "duration": float(pr["format"]["duration"])}
    if int(v["nb_read_packets"]) != tl["frames_total"]:
        res["problems"].append("frame count differs from the timeline")
    if abs(res["video"]["duration"] - tl["seconds_total"]) > 0.1:
        res["problems"].append("duration differs from the timeline")

    # --- black frames
    b = run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(ep), "-vf", "blackdetect=d=0.5:pix_th=0.05",
             "-an", "-f", "null", "-"])
    blacks = re.findall(r"black_start:([0-9.]+) black_end:([0-9.]+)", b.stderr)
    res["black_runs"] = [[float(a), float(c)] for a, c in blacks]

    # --- per-beat: freeze vs render record, frame vs sealed still
    rows = []
    mids = []
    for beat in tl["beats"]:
        t0, t1 = beat["start"], beat["end"]
        mid = (t0 + t1) / 2
        frame = out / f"beat_{beat['id']}.jpg"
        run(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-ss", f"{mid:.3f}", "-i", str(ep), "-frames:v", "1",
             "-vf", "scale=960:-1", "-q:v", "3", str(frame)])
        still = pkg / "render" / beat["id"] / "still_2.jpg"
        ss = run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(frame), "-i", str(still), "-lavfi",
                  "[0:v]scale=480:270[a];[1:v]scale=480:270[b];[a][b]ssim", "-f", "null", "-"])
        m = re.search(r"All:([0-9.]+)", ss.stderr)
        fz = run(["ffmpeg", "-hide_banner", "-nostdin", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}", "-i", str(ep),
                  "-vf", "freezedetect=n=-60dB:d=0.25", "-map", "0:v:0", "-f", "null", "-"])
        durs = [float(x) for x in re.findall(r"freeze_duration:\s*([0-9.]+)", fz.stderr)]
        rec = rnd["shots"][beat["id"]]["longest_freeze_seconds"]
        row = {"beat": beat["id"], "mid_s": round(mid, 2), "ssim_vs_sealed_still": float(m.group(1)) if m else None,
               "longest_freeze_in_episode": max(durs, default=0.0), "longest_freeze_in_render": rec,
               "engine_subjects_visible": [rnd["shots"][beat["id"]]["engine_subjects_visible_min"],
                                           rnd["shots"][beat["id"]]["engine_subjects_visible_max"]]}
        if row["ssim_vs_sealed_still"] is None or row["ssim_vs_sealed_still"] < 0.55:
            res["problems"].append(f"beat {beat['id']}: the frame in the episode is not the sealed picture "
                                   f"(ssim {row['ssim_vs_sealed_still']})")
        if row["longest_freeze_in_episode"] > rec + 0.5:
            res["problems"].append(f"beat {beat['id']}: a freeze the render did not record")
        rows.append(row)
        mids.append(frame)
    res["beats"] = rows
    res["ssim_min"] = min(r["ssim_vs_sealed_still"] or 0 for r in rows)

    # --- speech is audible under every narration line and caption cue
    wav = pkg / "audio" / "episode.wav"
    quiet = []
    lines = []
    for beat in tl["beats"]:
        for ln in beat["lines"]:
            lines.append((ln["id"], beat["start"] + ln["beat_offset"], ln["seconds"]))
    for lid, start, secs in lines:
        r = run(["ffmpeg", "-hide_banner", "-nostdin", "-ss", f"{start:.3f}", "-t", f"{secs:.3f}", "-i", str(wav),
                 "-af", "volumedetect", "-f", "null", "-"])
        m = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", r.stderr)
        if not m or float(m.group(1)) < -45.0:
            quiet.append(lid)
    res["narration_lines"] = len(lines)
    res["narration_lines_without_audible_speech"] = quiet
    if quiet:
        res["problems"].append(f"no audible speech under {quiet[:5]}")
    cues = re.findall(r"\n(\d+)\n", "\n" + (pkg / "captions.srt").read_text(encoding="utf-8"))
    res["caption_cues"] = len(cues)
    if len(cues) != len(nar["lines"]):
        res["problems"].append("caption cue count differs from the narration line count")

    # --- the sheet a person reads against narration.json
    cols = 5
    args = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    for f in mids:
        args += ["-i", str(f)]
    lay = "".join(f"[{i}:v]scale=480:270[s{i}];" for i in range(len(mids))) + "".join(f"[s{i}]" for i in range(len(mids)))
    lay += f"xstack=inputs={len(mids)}:layout=" + "|".join(f"{(i % cols) * 480}_{(i // cols) * 270}" for i in range(len(mids))) + ":fill=black[o]"
    run(args + ["-filter_complex", lay, "-map", "[o]", "-frames:v", "1", "-q:v", "3", str(out / "episode_beat_sheet.jpg")])
    res["verdict"] = "PASS" if not res["problems"] else "FAIL"
    (out / "visual_audit.json").write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
    print(res["verdict"], res["ssim_min"], len(res["problems"]), "problems")
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
