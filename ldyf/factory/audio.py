"""Stage 8: the sound track, and the policy that keeps it safe.

POLICY (enforced by `validate_audio_policy`, not merely stated):

* Every sound in an episode is either SYNTHESISED SPEECH from the local Windows
  engine (`ldyf.factory.voice`) or a GENERATED TONE whose formula is written in
  this file and rendered by ffmpeg's own signal generator.
* There is no music file, no sample pack, no downloaded sound effect, no stock
  library and no recording. Nothing in the sound track has an author other
  than this project, so nothing in it can carry a third-party copyright claim.
* The audio manifest lists every source with its kind, its generator and its
  sha256. A file in the audio directory that the manifest does not list, or a
  source whose kind is not one of the two above, fails the episode.

The bed is a quiet sustained chord with a slow swell: enough to stop silence
sounding like a fault, quiet enough to stay out of the way of an A1/A2
listener. It is ducked under the voice by a sidechain compressor. STRATEGIC
SILENCE is silence of WORDS: during a hold the bed carries on under the picture.
A two-note chime marks the beats where the episode turns (the prediction, the
reveals).
"""
from __future__ import annotations

import subprocess
import wave
from array import array
from pathlib import Path
from typing import Any

from . import FactoryError
from .util import read_json, seal, sha256_file, verify_seal
from .voice import SAMPLE_RATE, verify_voice

AUDIO_SCHEMA = "episode_audio_v1"
ALLOWED_KINDS = ("synthesised_speech", "generated_tone", "mix_of_listed_sources")
CHIME_ROLES = ("prediction", "reveal")

#: The bed: A2 + E3 + A3 + C#4 sines under a 0.05 Hz swell. A formula, not a file.
BED_EXPR = ("0.050*(sin(2*PI*110.00*t)+0.60*sin(2*PI*164.81*t)+0.45*sin(2*PI*220.00*t)"
            "+0.22*sin(2*PI*277.18*t))*(0.72+0.28*sin(2*PI*0.05*t))")
#: The chime: E5 then A5, each a decaying sine. Peak well below the voice.
CHIME_EXPR = ("0.16*sin(2*PI*659.25*t)*exp(-5*t)"
              "+0.16*sin(2*PI*880.00*max(t-0.22\\,0))*exp(-5*max(t-0.22\\,0))*gte(t\\,0.22)")
CHIME_SECONDS = 1.4
BED_FADE_SECONDS = 2.0


class AudioError(FactoryError):
    stage = "audio"


def _ffmpeg(args: list[str], what: str) -> None:
    try:
        run = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-y", *args],
                             capture_output=True, text=True)
    except FileNotFoundError:
        raise AudioError("no_ffmpeg", "ffmpeg is not installed")
    if run.returncode != 0:
        raise AudioError("ffmpeg_failed", f"{what}: {run.stderr[-500:]}")


def _pcm(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2 or w.getframerate() != SAMPLE_RATE:
            raise AudioError("bad_audio", f"{path.name} is not {SAMPLE_RATE} Hz 16-bit mono")
        return w.readframes(w.getnframes()), w.getnframes()


def _write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)


_WAV = ["-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", "-fflags", "+bitexact",
        "-flags:a", "+bitexact", "-map_metadata", "-1"]


def build_audio(timeline: dict[str, Any], voice: dict[str, Any], voice_dir: str | Path,
                out_dir: str | Path) -> dict[str, Any]:
    """narration.wav, bed.wav, chimes.wav and the mixed episode.wav, plus the sealed manifest."""
    voice_dir, out_dir = Path(voice_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if timeline.get("voice_hash") != voice.get("voice_hash"):
        raise AudioError("stale_lineage", "the timeline was built for a different voice track")
    verify_voice(voice, voice_dir)
    total = float(timeline["seconds_total"])
    n_total = int(round(total * SAMPLE_RATE))
    files = {r["id"]: r for r in voice["lines"]}

    # --- narration: each sentence's own audio, placed at its timeline second ---
    track = bytearray(n_total * 2)
    cursor = 0
    for b in timeline["beats"]:
        for l in b["lines"]:
            pcm, n = _pcm(voice_dir / files[l["id"]]["file"])
            at = int(round(l["start"] * SAMPLE_RATE))
            if at < cursor:
                raise AudioError("overlap", f"sentence {l['id']!r} would be spoken over the one before")
            if at + n > n_total:
                raise AudioError("overrun", f"sentence {l['id']!r} runs past the end of the episode")
            track[at * 2:(at + n) * 2] = pcm
            cursor = at + n
    narration = out_dir / "narration.wav"
    _write_wav(narration, bytes(track))

    # --- generated tones ---------------------------------------------------------
    bed = out_dir / "bed.wav"
    _ffmpeg(["-f", "lavfi", "-i", f"aevalsrc=exprs='{BED_EXPR}':s={SAMPLE_RATE}:d={total:.4f}",
             "-af", f"lowpass=f=900,afade=t=in:d={BED_FADE_SECONDS},"
                    f"afade=t=out:st={max(total - BED_FADE_SECONDS, 0):.4f}:d={BED_FADE_SECONDS}",
             *_WAV, str(bed)], "bed")
    chime = out_dir / "chime.wav"
    _ffmpeg(["-f", "lavfi", "-i", f"aevalsrc=exprs='{CHIME_EXPR}':s={SAMPLE_RATE}:d={CHIME_SECONDS}",
             *_WAV, str(chime)], "chime")
    chime_pcm, chime_n = _pcm(chime)
    marks = [b for b in timeline["beats"] if b["role"] in CHIME_ROLES]
    ctrack = bytearray(n_total * 2)
    for b in marks:
        at = int(round(b["start"] * SAMPLE_RATE))
        end = min(at + chime_n, n_total)
        ctrack[at * 2:end * 2] = chime_pcm[:(end - at) * 2]
    chimes = out_dir / "chimes.wav"
    _write_wav(chimes, bytes(ctrack))

    # --- mix: bed ducked under the voice, chimes on top, one loudness pass --------
    # The three tracks go to ffmpeg as ONE three-channel file. As three inputs they
    # are demuxed on three threads and reach the compressor in an order that varies
    # from run to run, and about one mix in five then differed by a few samples.
    # One input is one stream of frames: every branch sees the same boundaries.
    bed_pcm, _ = _pcm(bed)
    stems = array("h", bytes(n_total * 6))
    for ch, pcm in enumerate((bytes(track), bed_pcm, bytes(ctrack))):
        samples = array("h", pcm[:n_total * 2].ljust(n_total * 2, b"\0"))
        stems[ch::3] = samples
    stems_path = out_dir / "_stems.wav"
    with wave.open(str(stems_path), "wb") as w:
        w.setnchannels(3)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(stems.tobytes())
    mix = out_dir / "episode.wav"
    try:
        _ffmpeg(["-i", str(stems_path), "-filter_complex_threads", "1", "-filter_complex",
                 "[0:a]asplit=3[a][b][c];"
                 "[a]pan=mono|c0=c0,asplit=2[v][key];[b]pan=mono|c0=c1[bd];[c]pan=mono|c0=c2[ch];"
                 "[bd][key]sidechaincompress=threshold=0.02:ratio=6:attack=40:release=600[duck];"
                 "[v][duck][ch]amix=inputs=3:normalize=0:duration=first[m];"
                 "[m]alimiter=limit=0.89[out]",
                 "-map", "[out]", *_WAV, str(mix)], "mix")
    finally:
        stems_path.unlink(missing_ok=True)
    _pcm_mix, n_mix = _pcm(mix)
    if abs(n_mix - n_total) > SAMPLE_RATE // 50:
        raise AudioError("bad_length", f"the mix is {n_mix / SAMPLE_RATE:.3f} s, the timeline {total:.3f} s")

    sources = [{"file": f"voice/{r['file']}", "kind": "synthesised_speech", "sha256": r["sha256"],
                "generator": "System.Speech (local, offline)", "licence": "none: generated by this project",
                "line": r["id"]} for r in voice["lines"]]
    sources += [
        {"file": "bed.wav", "kind": "generated_tone", "sha256": sha256_file(bed), "kept": False,
         "generator": f"ffmpeg aevalsrc: {BED_EXPR}", "licence": "none: generated by this project"},
        {"file": "chime.wav", "kind": "generated_tone", "sha256": sha256_file(chime),
         "generator": f"ffmpeg aevalsrc: {CHIME_EXPR}", "licence": "none: generated by this project"},
        {"file": "chimes.wav", "kind": "mix_of_listed_sources", "sha256": sha256_file(chimes),
         "kept": False,
         "generator": "chime.wav placed at the start of " + ", ".join(b["id"] for b in marks),
         "licence": "none: generated by this project"},
        {"file": "narration.wav", "kind": "mix_of_listed_sources", "sha256": sha256_file(narration),
         "kept": False,
         "generator": "each sentence's wave placed at its timeline second",
         "licence": "none: generated by this project"},
        {"file": "episode.wav", "kind": "mix_of_listed_sources", "sha256": sha256_file(mix),
         "generator": "narration + bed (sidechain-ducked) + chimes, limiter",
         "licence": "none: generated by this project"},
    ]
    # The three full-length intermediate tracks are identified by hash and then
    # dropped: each is ~26 MB a ten-minute episode, and each is re-derivable
    # (the tones from their formula, the narration track from the sentences).
    for s in sources:
        if s.get("kept") is False:
            (out_dir / s["file"]).unlink()
    doc = {
        "schema_version": AUDIO_SCHEMA,
        "timeline_hash": timeline["timeline_hash"], "voice_hash": voice["voice_hash"],
        "policy": {
            "allowed_kinds": list(ALLOWED_KINDS),
            "external_assets": [],
            "music_files": 0, "sample_packs": 0, "downloaded_sound_effects": 0,
            "statement": "Every sound is speech synthesised locally or a tone generated from a "
                         "formula in ldyf/factory/audio.py. No third-party audio is used.",
        },
        "sample_rate": SAMPLE_RATE, "seconds": round(n_mix / SAMPLE_RATE, 4),
        "chime_beats": [b["id"] for b in marks],
        "sources": sources,
        "audio_hash": "",
    }
    return seal(doc, "audio_hash")


def validate_audio_policy(doc: dict[str, Any], audio_dir: str | Path, voice_dir: str | Path) -> None:
    """Refuse a sound track that holds anything the policy does not allow."""
    audio_dir, voice_dir = Path(audio_dir), Path(voice_dir)
    try:
        verify_seal(doc, "audio_hash", "audio.json")
    except FactoryError as e:
        raise AudioError("corrupt", e.message)
    if doc["policy"].get("external_assets"):
        raise AudioError("policy_violation", "the audio manifest declares external assets")
    listed: dict[str, dict[str, Any]] = {}
    for s in doc["sources"]:
        if s.get("kind") not in ALLOWED_KINDS:
            raise AudioError("policy_violation", f"{s.get('file')!r} is a {s.get('kind')!r}; only "
                                                 f"{ALLOWED_KINDS} are allowed")
        if not str(s.get("licence", "")).startswith("none: generated"):
            raise AudioError("policy_violation", f"{s.get('file')!r} carries a licence; nothing in "
                                                 "the sound track may have a third-party author")
        listed[s["file"]] = s
    for name, s in listed.items():
        p = (voice_dir / name[len("voice/"):]) if name.startswith("voice/") else (audio_dir / name)
        if s.get("kept") is False:
            if p.is_file() and sha256_file(p) != s["sha256"]:
                raise AudioError("corrupt", f"audio source {name!r} is not the file that was sealed")
            continue
        if not p.is_file():
            raise AudioError("missing", f"audio source {name!r} is missing")
        if sha256_file(p) != s["sha256"]:
            raise AudioError("corrupt", f"audio source {name!r} is not the file that was sealed")
    # Any file at all, not only a known audio extension: a sound can hide in .mka,
    # .webm, .mp4 or a renamed file.
    for d, prefix, own in ((audio_dir, "", "audio.json"), (voice_dir, "voice/", "voice.json")):
        for p in sorted(d.iterdir()):
            if p.name != own and prefix + p.name not in listed:
                raise AudioError("policy_violation",
                                 f"{prefix + p.name!r} is in the sound directories and the "
                                 "manifest does not list it")


def load_audio(path: str | Path) -> dict[str, Any]:
    doc = read_json(path, "audio.json", error=AudioError)
    if doc.get("schema_version") != AUDIO_SCHEMA:
        raise AudioError("bad_version", f"audio.json declares {doc.get('schema_version')!r}")
    return doc
