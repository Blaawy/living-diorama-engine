"""Stage 6: the narration, spoken. Local, free, offline.

The voice is the speech synthesiser that ships with Windows (`System.Speech`,
SAPI 5), driven through PowerShell. Nothing is downloaded, no service is
called, nothing is paid for, and no model is involved: the engine reads the
sentence it is handed.

Each sentence is synthesised to ITS OWN wave file. That is what makes the
captions honest: a caption's time on screen is the measured length of the audio
it transcribes, not an estimate of it.

A sentence is spoken from exactly the text the truth audit approved. The
factory never hands the engine a different string from the one it captions.

Fails closed: an unknown voice, a sentence that produced no audio, or a wave
file that is not the declared format stops the pipeline.
"""
from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path
from typing import Any

from . import FactoryError
from .util import read_json, seal, sha256_bytes, sha256_file, verify_seal

VOICE_SCHEMA = "episode_voice_v1"
SAMPLE_RATE = 22050

_PS1 = r'''param([string]$JobPath)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$job = Get-Content -Raw -Encoding UTF8 $JobPath | ConvertFrom-Json
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$names = @($s.GetInstalledVoices() | Where-Object { $_.Enabled } | ForEach-Object { $_.VoiceInfo.Name })
if ($names -notcontains $job.voice) {
  Write-Output ("TTS_NO_VOICE " + ($names -join "|"))
  exit 3
}
$s.SelectVoice($job.voice)
$s.Rate = [int]$job.rate
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo([int]$job.sample_rate, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
foreach ($l in $job.lines) {
  $s.SetOutputToWaveFile($l.wav, $fmt)
  $s.Speak($l.text)
  $s.SetOutputToNull()
}
$info = $s.Voice
Write-Output ("TTS_VOICE " + $info.Name + "|" + $info.Culture + "|" + $info.Gender + "|" + $info.Age)
$s.Dispose()
Write-Output ("TTS_DONE " + $job.lines.Count)
'''


class VoiceError(FactoryError):
    stage = "voice"


def wav_seconds(path: str | Path) -> float:
    """Length of a PCM wave file, read from its own header and data."""
    try:
        with wave.open(str(path), "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                raise VoiceError("bad_audio", f"{Path(path).name} is not 16-bit mono PCM")
            frames, rate = w.getnframes(), w.getframerate()
    except (wave.Error, EOFError, OSError) as e:
        raise VoiceError("bad_audio", f"{Path(path).name} is not a readable wave file: {e}")
    if frames <= 0 or rate <= 0:
        raise VoiceError("bad_audio", f"{Path(path).name} holds no audio")
    return frames / float(rate)


def spoken_text(text: str) -> str:
    """The string handed to the engine. Identity: what is captioned is what is said."""
    return text


def synthesise(lines: list[dict[str, Any]], out_dir: str | Path, *, voice: str, rate: int,
               narration_hash: str, timeout_s: float = 900.0) -> dict[str, Any]:
    """Speak every line (`{"id", "text"}`) to `out_dir/<id>.wav`; returns the sealed voice doc."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not lines:
        raise VoiceError("nothing_to_say", "the narration has no lines")
    ids = [l["id"] for l in lines]
    if len(set(ids)) != len(ids):
        raise VoiceError("duplicate_line", "two narration lines share an id")
    job = {"voice": voice, "rate": int(rate), "sample_rate": SAMPLE_RATE,
           "lines": [{"wav": str((out_dir / f"{l['id']}.wav").resolve()),
                      "text": spoken_text(l["text"])} for l in lines]}
    for row in job["lines"]:
        Path(row["wav"]).unlink(missing_ok=True)
    job_path = out_dir / "tts_job.json"
    job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    ps1 = out_dir / "tts.ps1"
    ps1.write_text(_PS1, encoding="utf-8")
    try:
        run = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(ps1), "-JobPath", str(job_path)],
            capture_output=True, text=True, timeout=timeout_s)
    except FileNotFoundError:
        raise VoiceError("no_engine", "PowerShell (and with it System.Speech) is not available")
    except subprocess.TimeoutExpired:
        raise VoiceError("synthesis_failed", "the speech engine did not finish in time")
    out = run.stdout or ""
    if "TTS_NO_VOICE" in out:
        have = out.split("TTS_NO_VOICE", 1)[1].strip().splitlines()[0]
        raise VoiceError("no_voice", f"voice {voice!r} is not installed (installed: {have})")
    if run.returncode != 0 or f"TTS_DONE {len(lines)}" not in out:
        raise VoiceError("synthesis_failed",
                         f"the speech engine failed (exit {run.returncode}): "
                         f"{(run.stderr or out)[-400:]}")
    engine = "unknown"
    for ln in out.splitlines():
        if ln.startswith("TTS_VOICE "):
            engine = ln[len("TTS_VOICE "):].strip()
    rows = []
    for l in lines:
        wav = out_dir / f"{l['id']}.wav"
        if not wav.is_file():
            raise VoiceError("synthesis_failed", f"line {l['id']!r} produced no audio")
        rows.append({"id": l["id"], "text_sha256": sha256_bytes(spoken_text(l["text"]).encode("utf-8")),
                     "file": wav.name, "sha256": sha256_file(wav),
                     "seconds": round(wav_seconds(wav), 4)})
    job_path.unlink(missing_ok=True)
    ps1.unlink(missing_ok=True)
    doc = {
        "schema_version": VOICE_SCHEMA,
        "narration_hash": narration_hash,
        "engine": {"api": "System.Speech.Synthesis (SAPI 5, ships with Windows)",
                   "voice": voice, "voice_info": engine, "rate": int(rate),
                   "sample_rate": SAMPLE_RATE, "network": False, "cost": "none",
                   "runtime_model": False},
        "lines": rows,
        "total_spoken_seconds": round(sum(r["seconds"] for r in rows), 3),
        "voice_hash": "",
    }
    return seal(doc, "voice_hash")


def verify_voice(doc: dict[str, Any], voice_dir: str | Path) -> None:
    """Re-check a voice document against the wave files on disk."""
    try:
        verify_seal(doc, "voice_hash", "voice.json")
    except FactoryError as e:
        raise VoiceError("corrupt", e.message)
    for r in doc["lines"]:
        p = Path(voice_dir) / r["file"]
        if not p.is_file():
            raise VoiceError("missing", f"spoken line {r['id']!r} is missing: {p.name}")
        if sha256_file(p) != r["sha256"]:
            raise VoiceError("corrupt", f"spoken line {r['id']!r} is not the audio that was sealed")


def load_voice(path: str | Path) -> dict[str, Any]:
    doc = read_json(path, "voice.json", error=VoiceError)
    if doc.get("schema_version") != VOICE_SCHEMA:
        raise VoiceError("bad_version", f"voice.json declares {doc.get('schema_version')!r}")
    verify_voice(doc, Path(path).parent)
    return doc
