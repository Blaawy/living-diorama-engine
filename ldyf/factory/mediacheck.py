"""Phase 5: what `verify` can say about the PICTURE and the SOUND, and what it cannot.

Red-team lane 2 forged a package whose episode, segments and voice recordings were swapped and every
hash recomputed; Phase 4's `verify` and `verify --resimulate` accepted it, because media was only
HASH-BOUND. The text layers (facts, story, shots, narration, timeline) are re-derived and cannot be
forged this way; media cannot be re-derived offline (Movie Render Queue pixels are not reproducible).
These checks close what CAN be closed and the rest is stated, not implied.

standard (every verify, seconds)
    episode.mp4 holds exactly one video and one audio stream and nothing else, and its audio runs as
    long as the timeline; the rendered stills match what each shot's sealed record says they are

deep (--resimulate, minutes)
    the episode is REBUILT from the sealed segments and the sealed mix and must be byte-identical (this
    covers every frame, label, caption and sample); its sound is also compared to the mix (loudness and
    waveform) and sampled frames to the segments; the speech is re-synthesised and the mix rebuilt, both
    byte for byte. Deep verification FAILS CLOSED on a machine whose speech engine or ffmpeg build does
    not reproduce the package: it is an insider check for the machine that made the package

NOT covered, by design: that a segment's pixels are what the engine drew (the engine measurement is
attested by hash), and that the audio of one narrated sentence is the right words (speech-to-text is
not run). `COVERAGE` is printed by `verify` so nobody has to guess.
"""
from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
import tempfile
from array import array
from pathlib import Path
from typing import Any, Callable

from . import FactoryError
from .util import sha256_file

COVERAGE = {
    "standard": ["hash of every file and every top-level manifest field, re-derived",
                 "truth_audit.json, lineage.json, captions equal their re-derivation",
                 "episode.mp4 holds one video and one mono audio stream, audio as long as the timeline",
                 "render stills equal the hashes sealed in each shot; contact_sheet.jpg is the sheet they give",
                 "what the engine says it saw never exceeds what the planner put in view",
                 "no unlisted file, no empty or unlisted directory, no link/junction, no hidden data stream"],
    "deep": ["the episode is rebuilt from the sealed segments and sealed mix and must be byte-identical",
             "episode sound follows the sealed mix (loudness and waveform), sampled frames follow the segments",
             "speech re-synthesised and the mix rebuilt byte for byte, on the engine that made the package",
             "every simulation run again; records, trips, agents and manifests equal the sealed ones"],
    "attested_by_hash_only": ["pixels of each rendered segment (Movie Render Queue is not reproducible)",
                              "the engine's measurement of each shot (bounded, not re-derived)",
                              "that a recording says the words printed beside it (no speech-to-text)",
                              "SUMO console logs (unhashed: their lines hold the wall clock; size- and shape-capped)"],
}


class MediaError(FactoryError):
    stage = "media"


def _run(args: list[str], what: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, text=True)
    except FileNotFoundError:
        raise MediaError("no_ffmpeg", f"{what}: ffmpeg/ffprobe is not installed")


def probe_streams(path: Path) -> list[dict[str, Any]]:
    run = _run(["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_type,duration,channels",
                "-of", "json", str(path)], "stream probe")
    try:
        return list(json.loads(run.stdout)["streams"])
    except (ValueError, KeyError, TypeError) as e:
        raise MediaError("unreadable", f"{path.name}: ffprobe gave no stream list: {e!r}")


def check_streams(episode: Path, seconds_total: float) -> dict[str, Any]:
    """Exactly one video and one audio stream; the audio runs as long as the picture."""
    st = probe_streams(episode)
    kinds = sorted(s.get("codec_type", "?") for s in st)
    if kinds != ["audio", "video"]:
        raise MediaError("bad_streams", f"{episode.name} holds streams {kinds}; an episode holds exactly "
                                        "one video and one audio stream")
    audio = next(s for s in st if s["codec_type"] == "audio")
    if int(audio.get("channels", 0)) != 1:
        raise MediaError("bad_streams", f"{episode.name}: the sound track has {audio.get('channels')} channels; "
                                        "the sealed mix is mono (a second channel could say something else)")
    try:
        dur = float(audio["duration"])
    except (KeyError, ValueError, TypeError):
        raise MediaError("bad_streams", f"{episode.name}: the audio stream states no duration")
    if abs(dur - float(seconds_total)) > 0.25:
        raise MediaError("audio_length", f"{episode.name}: the audio runs {dur:.2f} s, the timeline "
                                         f"{seconds_total:.2f} s")
    return {"streams": kinds, "audio_seconds": round(dur, 3)}


def check_stills(pkg: Path, timeline: dict[str, Any]) -> int:
    """Each shot's stills are the files its sealed record names."""
    n = 0
    for beat in timeline["beats"]:
        p = pkg / "render" / beat["id"] / "shot_render.json"
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            for s in doc["stills"]:
                if sha256_file(pkg / "render" / beat["id"] / s["file"]) != s["sha256"]:
                    raise MediaError("still_changed", f"render/{beat['id']}/{s['file']} is not the still "
                                                      "its shot sealed")
                n += 1
        except MediaError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise MediaError("still_changed", f"render/{beat['id']}: stills cannot be checked: {e!r}")
    return n


def _pcm(path: Path, rate: int, extra: list[str] | None = None) -> array:
    run = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), *(extra or []),
                          "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"], capture_output=True)
    if run.returncode != 0:
        raise MediaError("unreadable", f"{path.name}: audio does not decode: {run.stderr[-200:]!r}")
    a = array("h")
    a.frombytes(run.stdout[: len(run.stdout) // 2 * 2])
    return a


def _envelope(samples: array, win: int) -> list[float]:
    """RMS per window, in dB (floor -90)."""
    import math
    out = []
    for i in range(0, len(samples) - win + 1, win):
        chunk = samples[i:i + win]
        ms = sum(x * x for x in chunk) / win
        out.append(10.0 * math.log10(ms / (32768.0 ** 2)) if ms > 0 else -90.0)
    return [max(-90.0, v) for v in out]


def check_sound(episode: Path, mix_wav: Path, *, tol_db: float = 3.0, tail: float = 0.01) -> dict[str, Any]:
    """The decoded audio of the episode must follow the sealed mix: per 100 ms window, within `tol_db`
    (AAC at 128 kbit/s moves a window by well under 1 dB). A sine, a different voice, truncated or
    shifted sound fails; so does a swapped sentence."""
    rate = 8000
    ep, mix = _pcm(episode, rate), _pcm(mix_wav, rate)
    if abs(len(ep) - len(mix)) > rate * 0.25:
        raise MediaError("sound_mismatch", f"the episode's sound is {len(ep) / rate:.2f} s, the sealed mix "
                                           f"{len(mix) / rate:.2f} s")
    n = min(len(ep), len(mix))
    win = rate // 10
    e1, e2 = _envelope(ep[:n], win), _envelope(mix[:n], win)
    # windows where either side is near silence are judged by absolute level, not by ratio
    bad = [i for i, (x, y) in enumerate(zip(e1, e2)) if abs(x - y) > tol_db and max(x, y) > -60.0]
    # No window may differ, except the few at either end where the encoder primes and flushes. (An
    # allowance of "about 1 %" would let ~6 s of a ten-minute episode say anything at all.)
    edge = 3
    inner = [i for i in bad if edge <= i < len(e1) - edge]
    if inner:
        raise MediaError("sound_mismatch", f"{len(inner)} of {len(e1)} 100 ms windows of the episode's sound "
                                           f"differ from the sealed mix by more than {tol_db} dB (first at "
                                           f"{inner[0] / 10:.1f} s)")
    # Loudness can be matched by different words, so the WAVEFORM is compared too: per second, the
    # normalised correlation of the decoded episode audio with the sealed mix (AAC keeps it above 0.9).
    import math
    quiet = (32768.0 * 10 ** (-50 / 20)) ** 2
    ncc_bad, worst = [], 1.0
    for s in range(0, n - rate + 1, rate):
        a, b = ep[s:s + rate], mix[s:s + rate]
        sbb = sum(y * y for y in b)
        if sbb / rate < quiet:
            continue
        saa = sum(x * x for x in a)
        if saa == 0:
            ncc = 0.0
        else:
            ncc = sum(x * y for x, y in zip(a, b)) / math.sqrt(saa * sbb)
        worst = min(worst, ncc)
        if ncc < 0.8:
            ncc_bad.append(s // rate)
    if ncc_bad:
        raise MediaError("sound_mismatch", f"the episode's sound is not the sealed mix's waveform in "
                                           f"{len(ncc_bad)} second(s) (first at {ncc_bad[0]} s)")
    return {"windows": len(e1), "windows_off": len(bad), "ncc_min": round(worst, 4)}


def _ssim(a: Path, b: Path) -> float:
    run = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(a), "-i", str(b), "-lavfi",
                          "[0:v]scale=480:270[x];[1:v]scale=480:270[y];[x][y]ssim", "-f", "null", "-"],
                         capture_output=True, text=True)
    m = re.search(r"All:([0-9.]+)", run.stderr)
    return float(m.group(1)) if m else 0.0


def check_picture(pkg: Path, timeline: dict[str, Any], *, per_beat: int = 6, floor: float = 0.8,
                  log: Callable[[str], None] = lambda s: None) -> dict[str, Any]:
    """Frames of the episode against the same moment of each sealed segment. The episode wears the
    arm label and the captions, which is why the floor is not 1.0 (genuine frames measure above 0.9)."""
    worst = 1.0
    with tempfile.TemporaryDirectory(prefix="ldyf_pic_") as td:
        td = Path(td)
        for beat in timeline["beats"]:
            seg = pkg / "render" / beat["id"] / "segment.mp4"
            span = float(beat["end"]) - float(beat["start"])
            for k in range(per_beat):
                off = span * (k + 1) / (per_beat + 1)
                fa, fb = td / "a.png", td / "b.png"
                for src, t, dst in ((pkg / "episode.mp4", float(beat["start"]) + off, fa), (seg, off, fb)):
                    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-ss",
                                        f"{t:.3f}", "-i", str(src), "-frames:v", "1", str(dst)],
                                       capture_output=True, text=True)
                    if r.returncode != 0 or not dst.is_file():
                        raise MediaError("picture_mismatch", f"beat {beat['id']}: no frame at {t:.2f} s of "
                                                             f"{src.name}")
                s = _ssim(fa, fb)
                worst = min(worst, s)
                if s < floor:
                    raise MediaError("picture_mismatch", f"beat {beat['id']}: the episode's frame at "
                                                         f"{beat['start'] + off:.1f} s is not the sealed "
                                                         f"segment's (ssim {s:.3f} < {floor})")
    return {"frames_compared": per_beat * len(timeline["beats"]), "ssim_min": round(worst, 4)}


def check_speech_and_mix(pkg: Path, brief: dict[str, Any], narration: dict[str, Any], voice: dict[str, Any],
                         timeline: dict[str, Any], audio: dict[str, Any], scratch: Path) -> dict[str, Any]:
    """Re-speak every sentence and rebuild the mix. Speech is deterministic on one engine; if the
    engine here is not the one that spoke the package, say so instead of failing it."""
    from . import audio as AU
    from . import voice as V
    out: dict[str, Any] = {}
    vdir = scratch / "voice"
    redo = V.synthesise([{"id": l["id"], "text": l["text"]} for l in narration["lines"]], vdir,
                        voice=brief["voice"], rate=brief["voice_rate"], narration_hash=narration["narration_hash"])
    # FAIL CLOSED. Whether the engine "is the same" must never be decided by a field of the document
    # being verified (an insider writes that field). If the engine here does not reproduce the
    # recordings, deep verification refuses; the standard check remains available on any machine.
    diff = [r["id"] for r in voice["lines"] if sha256_file(vdir / r["file"]) != r["sha256"]]
    if diff:
        engine_note = ("the speech engine here is not the one that spoke the package"
                       if redo["engine"].get("voice_info") != voice["engine"].get("voice_info")
                       else "the same engine gives different bytes")
        raise MediaError("voice_not_reproduced", f"{len(diff)} recording(s) differ from re-speaking the "
                                                 f"audited sentence ({engine_note}): {diff[:4]}. Deep "
                                                 "verification is meaningful only on the engine that made "
                                                 "the package; the standard verification does not need it.")
    out["speech"] = "identical"
    mdir = scratch / "audio"
    rebuilt = AU.build_audio(timeline, redo, vdir, mdir)
    if rebuilt["audio_hash"] != audio["audio_hash"] or sha256_file(mdir / "episode.wav") != sha256_file(
            pkg / "audio" / "episode.wav"):
        raise MediaError("audio_not_reproduced", "rebuilding the mix from the audited speech does not "
                                                 "give the sealed mix")
    out["mix"] = "identical"
    return out


def check_reassembly(pkg: Path, timeline: dict[str, Any], scratch: Path) -> dict[str, Any]:
    """Build the episode again from the sealed segments and the sealed mix, with the product's own
    assembler, and require the SAME BYTES. The edit is the timeline and nothing else, and the encoder
    is deterministic on one machine, so this one check covers every frame (the arm label, the captions
    burned in), every sample of sound and the cuts: a forged episode cannot hash like the sealed one.
    What it still cannot prove is the pixels inside each segment (the engine's, attested by hash)."""
    from . import assemble as AS
    from . import audio as AU
    from . import render as R
    from .util import read_json
    render = R.load_render(pkg / "render" / "render.json")
    audio = AU.load_audio(pkg / "audio" / "audio.json")
    sealed = AS.load_assembly(pkg / "assembly.json")
    out_dir = scratch / "reassembly"
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = AS.assemble(timeline, render, audio, pkg / "render", pkg / "audio", out_dir)
    if doc["episode"]["sha256"] != sealed["episode"]["sha256"] or \
            sha256_file(out_dir / "episode.mp4") != sha256_file(pkg / "episode.mp4"):
        raise MediaError("episode_not_reproduced",
                         "building the episode again from the sealed segments and sound does not give "
                         "the sealed episode.mp4 (a forged episode, or a different ffmpeg build than "
                         "the one that made this package)")
    return {"episode": "identical", "sha256": doc["episode"]["sha256"][:16]}


def check_contact_sheet(pkg: Path, timeline: dict[str, Any]) -> dict[str, Any]:
    """contact_sheet.jpg is the first file a reviewer opens. It is rebuilt from the shots' sealed
    stills and must look like it (SSIM); a replaced or blank sheet is refused."""
    stills = [pkg / "render" / b["id"] / "still_2.jpg" for b in timeline["beats"]]
    cols = 5
    with tempfile.TemporaryDirectory(prefix="ldyf_sheet_") as td:
        out = Path(td) / "sheet.jpg"
        args = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y"]
        for p in stills:
            args += ["-i", str(p)]
        lay = "".join(f"[{i}:v]scale=480:270[s{i}];" for i in range(len(stills)))
        lay += "".join(f"[s{i}]" for i in range(len(stills)))
        lay += f"xstack=inputs={len(stills)}:layout=" + "|".join(
            f"{(i % cols) * 480}_{(i // cols) * 270}" for i in range(len(stills))) + ":fill=black[o]"
        r = subprocess.run(args + ["-filter_complex", lay, "-map", "[o]", "-frames:v", "1", "-q:v", "3", str(out)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not out.is_file():
            raise MediaError("contact_sheet_changed", "the contact sheet cannot be rebuilt from the stills")
        s = _ssim_full(pkg / "contact_sheet.jpg", out)
        worst_tile = _worst_tile_difference(pkg / "contact_sheet.jpg", out, len(stills), cols)
    if s < 0.97 or worst_tile > 4.0:
        raise MediaError("contact_sheet_changed", f"contact_sheet.jpg is not the sheet the shots' stills give "
                                                  f"(ssim {s:.3f}, worst tile differs by {worst_tile:.1f}/255)")
    return {"ssim": round(s, 4), "worst_tile_mean_abs_diff": round(worst_tile, 2)}


def _gray(path: Path, w: int, h: int) -> bytes:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), "-vf",
                        f"scale={w}:{h}", "-pix_fmt", "gray", "-f", "rawvideo", "-"], capture_output=True)
    return r.stdout if r.returncode == 0 and len(r.stdout) == w * h else b""


def _worst_tile_difference(a: Path, b: Path, tiles: int, cols: int) -> float:
    """Mean absolute grey-level difference of the most different tile (a blacked-out or relabelled tile
    moves a 21-tile mosaic's global SSIM by less than 0.02, but its own tile by tens of levels)."""
    tw, th = 120, 68                     # each 480x270 tile reduced 4x
    rows = (tiles + cols - 1) // cols
    W_, H_ = cols * tw, rows * th
    ga, gb = _gray(a, W_, H_), _gray(b, W_, H_)
    if not ga or not gb:
        return 255.0
    worst = 0.0
    for t in range(tiles):
        x0, y0 = (t % cols) * tw, (t // cols) * th
        tot = 0
        for y in range(y0, y0 + th):
            ra, rb = ga[y * W_ + x0:y * W_ + x0 + tw], gb[y * W_ + x0:y * W_ + x0 + tw]
            tot += sum(abs(i - j) for i, j in zip(ra, rb))
        worst = max(worst, tot / (tw * th))
    return worst


def _ssim_full(a: Path, b: Path) -> float:
    run = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(a), "-i", str(b), "-lavfi",
                          "[0:v]scale=1200:675[x];[1:v]scale=1200:675[y];[x][y]ssim", "-f", "null", "-"],
                         capture_output=True, text=True)
    m = re.search(r"All:([0-9.]+)", run.stderr)
    return float(m.group(1)) if m else 0.0


def check_engine_plausibility(shots: dict[str, Any], render: dict[str, Any], slack: int = 2) -> int:
    """What the engine says it saw is PINNED to what the planner computed for the same shot (the planner's
    counts are re-derived by the audit; the engine differs from them only where a tree or pole blocks a
    sight line, by a subject or two), to the number of subjects the shot holds, and to the shot's own
    requirement: a presence shot cannot have seen fewer than it requires, an absence shot cannot have
    seen more than it allows. A narrated 'at least 40 are in this picture' (or '0 of them') over a shot
    whose planner count is 12 is not an engine measurement."""
    n = 0
    for beat, row in render["shots"].items():
        shot = shots["shots"][beat]
        subj = len(shot["subjects"]["uids"])
        lo, hi = int(row["engine_subjects_visible_min"]), int(row["engine_subjects_visible_max"])
        if not 0 <= lo <= hi <= subj:
            raise MediaError("engine_measurement_implausible",
                             f"beat {beat!r}: the engine claims {lo}..{hi} subjects in view of the {subj} the shot holds")
        try:
            plo, phi = int(shot["subjects_visible_min"]), int(shot["subjects_visible_max"])
        except (KeyError, TypeError, ValueError) as e:
            raise MediaError("engine_measurement_implausible",
                             f"beat {beat!r}: planner visibility bounds are missing or invalid") from e
        if abs(lo - plo) > slack or abs(hi - phi) > slack:
            raise MediaError("engine_measurement_implausible",
                             f"beat {beat!r}: the engine claims {lo}..{hi} but the planner, from the record, "
                             f"counts {plo}..{phi}")
        req = shot.get("require") or {}
        if "min_visible" in req and hi < int(req["min_visible"]):
            raise MediaError("engine_measurement_implausible",
                             f"beat {beat!r}: a shot that requires {req['min_visible']} in view saw at most {hi}")
        if "max_visible" in req and hi > int(req["max_visible"]):
            raise MediaError("engine_measurement_implausible",
                             f"beat {beat!r}: a shot that allows {req['max_visible']} in view saw {hi}")
        n += 1
    return n
