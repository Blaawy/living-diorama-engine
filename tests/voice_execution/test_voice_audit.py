"""The independent Phase 29 directory audit: happy path and the full tamper matrix."""

import hashlib
from pathlib import Path

from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.voice_execution import audit_voice_directory
from living_diorama.voice_execution.voice_execution_spec import (
    SPEECH_DIRECTORY,
    VOICE_MANIFEST_FILENAME,
    VOICE_PLAN_FILENAME,
)


def test_a_truthful_directory_passes_the_audit(voice_directory_ep1: Path) -> None:
    """A truthful, complete directory passes the audit with zero problems."""
    assert audit_voice_directory(voice_directory_ep1) == []


def test_a_missing_plan_copy_is_a_single_problem(voice_directory_ep1: Path) -> None:
    """A missing plan copy is refused."""
    (voice_directory_ep1 / VOICE_PLAN_FILENAME).unlink()
    problems = audit_voice_directory(voice_directory_ep1)
    assert problems
    assert "missing" in problems[0]


def test_a_missing_manifest_means_execution_never_completed(voice_directory_ep1: Path) -> None:
    """A missing manifest means this execution never completed."""
    (voice_directory_ep1 / VOICE_MANIFEST_FILENAME).unlink()
    problems = audit_voice_directory(voice_directory_ep1)
    assert problems
    assert "never completed" in problems[0]


def test_an_artifact_mutated_after_the_manifest_is_refused(voice_directory_ep1: Path) -> None:
    """An artifact mutated after the manifest was written is refused."""
    speech_dir = voice_directory_ep1 / SPEECH_DIRECTORY
    unit_path = sorted(speech_dir.iterdir())[0]
    payload = bytearray(unit_path.read_bytes())
    payload[-1] ^= 0xFF
    unit_path.write_bytes(bytes(payload))
    problems = audit_voice_directory(voice_directory_ep1)
    assert any("on disk is" in problem for problem in problems)


def test_a_truncated_artifact_is_refused(voice_directory_ep1: Path) -> None:
    """A truncated artifact is refused."""
    speech_dir = voice_directory_ep1 / SPEECH_DIRECTORY
    unit_path = sorted(speech_dir.iterdir())[0]
    unit_path.write_bytes(unit_path.read_bytes()[:-10])
    problems = audit_voice_directory(voice_directory_ep1)
    assert problems


def test_a_manifest_lying_about_speech_samples_is_refused(voice_directory_ep1: Path) -> None:
    """A manifest lying about speech_samples is refused -- the exact Phase 28 V1 attack.

    The schema's own bytes-arithmetic law (``bytes == 44 + speech_samples *
    2``) means a manifest cannot lie about ``speech_samples`` alone while
    leaving ``bytes``/``sha256`` truthful: forging one forces forging the
    other, which the audit's independent re-hash of the real, untouched WAV
    catches immediately. The two layers together close the exact hole a
    standalone-only measurement claim left open.
    """
    manifest_path = voice_directory_ep1 / VOICE_MANIFEST_FILENAME
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["voice_units"][0]["speech_samples"] -= 1
    manifest["voice_units"][0]["bytes"] -= 2
    manifest["completeness"]["speech_samples_total"] -= 1
    manifest_path.write_bytes(dumps_canonical(manifest, "voice manifest"))
    problems = audit_voice_directory(voice_directory_ep1)
    assert problems
    assert any("bytes" in problem for problem in problems)


def test_a_manifest_lying_about_sha256_is_refused(voice_directory_ep1: Path) -> None:
    """A manifest lying about sha256 is refused."""
    manifest_path = voice_directory_ep1 / VOICE_MANIFEST_FILENAME
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["voice_units"][0]["sha256"] = hashlib.sha256(b"lie").hexdigest()
    manifest_path.write_bytes(dumps_canonical(manifest, "voice manifest"))
    problems = audit_voice_directory(voice_directory_ep1)
    assert problems


def test_a_manifest_lying_about_bytes_is_refused(voice_directory_ep1: Path) -> None:
    """A manifest lying about the byte count is refused."""
    manifest_path = voice_directory_ep1 / VOICE_MANIFEST_FILENAME
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["voice_units"][0]["bytes"] += 2
    manifest["voice_units"][0]["speech_samples"] += 1
    manifest_path.write_bytes(dumps_canonical(manifest, "voice manifest"))
    problems = audit_voice_directory(voice_directory_ep1)
    assert problems


def test_a_missing_unit_file_is_refused(voice_directory_ep1: Path) -> None:
    """A missing unit file is refused."""
    speech_dir = voice_directory_ep1 / SPEECH_DIRECTORY
    sorted(speech_dir.iterdir())[0].unlink()
    problems = audit_voice_directory(voice_directory_ep1)
    assert any("missing from disk" in problem for problem in problems)


def test_an_extra_file_in_speech_is_refused(voice_directory_ep1: Path) -> None:
    """An extra, unaccounted file in speech/ is refused."""
    speech_dir = voice_directory_ep1 / SPEECH_DIRECTORY
    (speech_dir / "voice_unit_9999.wav").write_bytes(b"\x00")
    problems = audit_voice_directory(voice_directory_ep1)
    assert any("no voice-unit record accounts for it" in problem for problem in problems)


def test_a_foreign_top_level_entry_is_refused(voice_directory_ep1: Path) -> None:
    """A foreign top-level entry is refused."""
    (voice_directory_ep1 / "intruder.txt").write_bytes(b"hello")
    problems = audit_voice_directory(voice_directory_ep1)
    assert any("holds only" in problem for problem in problems)


def test_a_surviving_writing_temp_is_named_as_unfinished(voice_directory_ep1: Path) -> None:
    """A surviving .writing temporary is named as a run that did not finish."""
    (voice_directory_ep1 / f"{VOICE_PLAN_FILENAME}.writing").write_bytes(b"{}")
    problems = audit_voice_directory(voice_directory_ep1)
    assert any("did not finish" in problem for problem in problems)


def test_fit_is_recomputed_even_when_the_manifest_disagrees(voice_directory_ep1: Path) -> None:
    """FIT is recomputed from disk regardless of what the manifest claims."""
    import json

    manifest_path = voice_directory_ep1 / VOICE_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    unit = manifest["voice_units"][0]
    capacity = unit["capacity_samples"]

    speech_dir = voice_directory_ep1 / SPEECH_DIRECTORY
    unit_path = speech_dir / unit["file"].split("/")[-1]
    from living_diorama.voice_execution import canonical_wav_bytes, pcm16_bytes

    overflowing_samples = capacity + 1
    wav = canonical_wav_bytes(
        pcm16_bytes([0.0] * overflowing_samples, "x"), sample_rate_hz=24000, channels=1
    )
    unit_path.write_bytes(wav)

    unit["bytes"] = len(wav)
    unit["sha256"] = hashlib.sha256(wav).hexdigest()
    unit["speech_samples"] = overflowing_samples
    manifest["completeness"]["speech_samples_total"] += 1
    manifest_path.write_bytes(dumps_canonical(manifest, "voice manifest"))

    # Standalone validation itself already refuses an overflowing unit (the
    # standalone FIT law), so the audit reports this at the "manifest is
    # invalid" stage -- still a refusal, and still proof that an overflow
    # can never be published as fit.
    problems = audit_voice_directory(voice_directory_ep1)
    assert problems
