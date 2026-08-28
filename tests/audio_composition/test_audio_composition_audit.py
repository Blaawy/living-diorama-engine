"""The independent Phase 31 directory audit: happy path, self-containment, tamper matrix."""

import shutil

import pytest

from living_diorama.audio_composition.audio_composition_audit import (
    audit_audio_composition_directory,
)
from living_diorama.audio_composition.audio_composition_spec import (
    AUDIO_COMPOSITION_MANIFEST_FILENAME,
    AUDIO_TRACK_PLAN_FILENAME,
    VOICE_MANIFEST_FILENAME,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical


def test_happy_path_clean(composition_dir_ep1) -> None:
    """Happy path clean."""
    assert audit_audio_composition_directory(composition_dir_ep1) == []


def test_happy_path_ep0(composition_dir_ep0) -> None:
    """Happy path ep0."""
    assert audit_audio_composition_directory(composition_dir_ep0) == []


def test_happy_path_ep2(composition_dir_ep2) -> None:
    """Happy path ep2."""
    assert audit_audio_composition_directory(composition_dir_ep2) == []


def test_self_contained_after_voice_directory_deleted(
    composition_dir_ep1, voice_directory_ep1
) -> None:
    """Self contained after voice directory deleted."""
    shutil.rmtree(voice_directory_ep1)
    assert audit_audio_composition_directory(composition_dir_ep1) == []


def test_missing_plan_file(composition_dir_ep1) -> None:
    """Missing plan file."""
    (composition_dir_ep1 / AUDIO_TRACK_PLAN_FILENAME).unlink()
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems
    assert any("missing" in problem for problem in problems)


def test_missing_witness_file(composition_dir_ep1) -> None:
    """Missing witness file."""
    (composition_dir_ep1 / VOICE_MANIFEST_FILENAME).unlink()
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems


def test_missing_manifest_file(composition_dir_ep1) -> None:
    """Missing manifest file."""
    (composition_dir_ep1 / AUDIO_COMPOSITION_MANIFEST_FILENAME).unlink()
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems


def test_missing_track_file(composition_dir_ep1) -> None:
    """Missing track file."""
    (composition_dir_ep1 / "audio" / "episode_audio.wav").unlink()
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems


def test_tampered_witness_one_bit_mutation(composition_dir_ep1) -> None:
    """Tampered witness one bit mutation."""
    path = composition_dir_ep1 / VOICE_MANIFEST_FILENAME
    raw = bytearray(path.read_bytes())
    raw[10] ^= 0xFF
    path.write_bytes(bytes(raw))
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems


def test_tampered_witness_reformatted_but_same_content(composition_dir_ep1) -> None:
    """Tampered witness reformatted but same content."""
    path = composition_dir_ep1 / VOICE_MANIFEST_FILENAME
    document = loads_canonical(path.read_bytes(), "voice manifest")
    import json

    reformatted = (json.dumps(document, sort_keys=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(reformatted)
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems


def test_tampered_composed_speech_one_bit_mutation(composition_dir_ep1) -> None:
    """Tampered composed speech one bit mutation."""
    path = composition_dir_ep1 / "audio" / "episode_audio.wav"
    raw = bytearray(path.read_bytes())
    # Flip a bit inside the payload, at a byte guaranteed inside the first
    # placed span (offset from the plan's own first start_sample).
    plan = loads_canonical(
        (composition_dir_ep1 / AUDIO_TRACK_PLAN_FILENAME).read_bytes(), "audio track plan"
    )
    start = plan["speech"][0]["start_sample"]
    offset = 44 + start * 2
    raw[offset] ^= 0xFF
    path.write_bytes(bytes(raw))
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems
    assert any("pcm_sha256" in problem or "reconstructs" in problem for problem in problems)


def test_tampered_silence_region_one_bit_mutation(composition_dir_ep1) -> None:
    """Tampered silence region one bit mutation."""
    path = composition_dir_ep1 / "audio" / "episode_audio.wav"
    raw = bytearray(path.read_bytes())
    raw[44] = 0x01  # first sample byte, before any hold in ep1 -- structural silence
    path.write_bytes(bytes(raw))
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems
    assert any("silence" in problem.lower() or "zero" in problem.lower() for problem in problems)


def test_foreign_entry_at_top_level(composition_dir_ep1) -> None:
    """Foreign entry at top level."""
    (composition_dir_ep1 / "stray.txt").write_text("hi", encoding="utf-8")
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert any("stray.txt" in problem for problem in problems)


def test_foreign_entry_inside_audio_directory(composition_dir_ep1) -> None:
    """Foreign entry inside audio directory."""
    (composition_dir_ep1 / "audio" / "stray.wav").write_bytes(b"\x00")
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert any("stray.wav" in problem for problem in problems)


def test_leftover_writing_file_is_a_problem(composition_dir_ep1) -> None:
    """Leftover writing file is a problem."""
    (composition_dir_ep1 / f"{AUDIO_COMPOSITION_MANIFEST_FILENAME}.writing").write_bytes(b"partial")
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert any("working file" in problem or "did not finish" in problem for problem in problems)


def test_manifest_disagrees_with_plan(composition_dir_ep1) -> None:
    """Manifest disagrees with plan."""
    manifest_path = composition_dir_ep1 / AUDIO_COMPOSITION_MANIFEST_FILENAME
    document = loads_canonical(manifest_path.read_bytes(), "audio composition manifest")
    document = dict(document)
    document["source"] = dict(document["source"])
    document["source"]["episode"] = 999
    document["source"]["mode"] = "baseline"
    document["source"]["previous_episode"] = None
    # This mutation makes the manifest internally inconsistent with itself
    # in ways the schema alone will catch; the audit must still return a
    # non-empty problem list rather than raise.
    try:
        payload = dumps_canonical(document, "audio composition manifest")
        manifest_path.write_bytes(payload)
    except (TypeError, ValueError):
        pytest.skip("mutation produced an undumpable document")
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems


def test_returns_list_never_raises_on_malformed_json(composition_dir_ep1) -> None:
    """Returns list never raises on malformed JSON."""
    (composition_dir_ep1 / AUDIO_TRACK_PLAN_FILENAME).write_bytes(b"{not json")
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems  # a list, not an exception
    assert isinstance(problems, list)


def test_non_canonical_plan_bytes_flagged(composition_dir_ep1) -> None:
    """Non canonical plan bytes flagged."""
    plan_path = composition_dir_ep1 / AUDIO_TRACK_PLAN_FILENAME
    document = loads_canonical(plan_path.read_bytes(), "audio track plan")
    import json

    reformatted = (json.dumps(document, sort_keys=False) + "\n").encode("utf-8")
    plan_path.write_bytes(reformatted)
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems


# ---- V1.5/V1.6/V2 hardening: governed-entry indirection refusal


def test_indirect_composition_dir_refuses(tmp_path, composition_dir_ep1) -> None:
    """A symlinked ``composition_dir`` itself refuses, never audited through the link."""
    link = tmp_path / "link_composition"
    try:
        link.symlink_to(composition_dir_ep1, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    problems = audit_audio_composition_directory(link)
    assert problems
    assert any("symlink or junction" in problem for problem in problems)


def test_indirect_plan_file_refuses_even_though_the_target_is_perfectly_valid(
    tmp_path, composition_dir_ep1
) -> None:
    """A symlinked plan file refuses even though its target is a byte-identical, valid copy.

    Proves the refusal is about the indirection itself, not about the
    target's truthfulness: the real plan is copied verbatim to a second
    location, and the governed path is replaced with a symlink to that
    valid copy -- every other governed entry, and the copy's own content,
    would otherwise audit clean.
    """
    plan_path = composition_dir_ep1 / AUDIO_TRACK_PLAN_FILENAME
    valid_copy = tmp_path / "valid_plan_copy.json"
    valid_copy.write_bytes(plan_path.read_bytes())
    plan_path.unlink()
    try:
        plan_path.symlink_to(valid_copy)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems
    assert any("symlink or junction" in problem for problem in problems)


def test_indirect_witness_file_refuses(tmp_path, composition_dir_ep1) -> None:
    """A symlinked voice manifest witness refuses."""
    witness_path = composition_dir_ep1 / VOICE_MANIFEST_FILENAME
    valid_copy = tmp_path / "valid_witness_copy.json"
    valid_copy.write_bytes(witness_path.read_bytes())
    witness_path.unlink()
    try:
        witness_path.symlink_to(valid_copy)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems
    assert any("symlink or junction" in problem for problem in problems)


def test_indirect_composition_manifest_refuses(tmp_path, composition_dir_ep1) -> None:
    """A symlinked composition manifest refuses."""
    manifest_path = composition_dir_ep1 / AUDIO_COMPOSITION_MANIFEST_FILENAME
    valid_copy = tmp_path / "valid_manifest_copy.json"
    valid_copy.write_bytes(manifest_path.read_bytes())
    manifest_path.unlink()
    try:
        manifest_path.symlink_to(valid_copy)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems
    assert any("symlink or junction" in problem for problem in problems)


def test_indirect_audio_directory_refuses(tmp_path, composition_dir_ep1) -> None:
    """A symlinked ``audio/`` directory refuses."""
    audio_dir = composition_dir_ep1 / "audio"
    valid_copy = tmp_path / "valid_audio_copy"
    shutil.copytree(audio_dir, valid_copy)
    shutil.rmtree(audio_dir)
    try:
        audio_dir.symlink_to(valid_copy, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems
    assert any("symlink or junction" in problem for problem in problems)


def test_indirect_episode_audio_wav_refuses(tmp_path, composition_dir_ep1) -> None:
    """A symlinked ``audio/episode_audio.wav`` refuses."""
    track_path = composition_dir_ep1 / "audio" / "episode_audio.wav"
    valid_copy = tmp_path / "valid_track_copy.wav"
    valid_copy.write_bytes(track_path.read_bytes())
    track_path.unlink()
    try:
        track_path.symlink_to(valid_copy)
    except OSError:
        pytest.skip("symlink creation not permitted on this platform/account")
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert problems
    assert any("symlink or junction" in problem for problem in problems)


# ---- V1.5/V1.6/V2 hardening: expected-error containment


def test_oserror_from_governed_read_becomes_a_problem_not_an_exception(
    composition_dir_ep1, monkeypatch
) -> None:
    """An ``OSError`` from a governed ``read_bytes()`` becomes a problem, never escapes."""
    from pathlib import Path

    real_read_bytes = Path.read_bytes

    def _fail_on_manifest(self, *args, **kwargs):
        if self.name == AUDIO_COMPOSITION_MANIFEST_FILENAME:
            raise OSError("simulated mid-audit read failure")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _fail_on_manifest)
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert isinstance(problems, list)
    assert problems
    assert any("simulated mid-audit read failure" in problem for problem in problems)


def test_oserror_from_governed_stat_becomes_a_problem_not_an_exception(
    composition_dir_ep1, monkeypatch
) -> None:
    """An ``OSError`` from the governed ``track_path.stat()`` becomes a problem, never escapes."""
    from pathlib import Path

    real_stat = Path.stat

    def _fail_on_track(self, *args, **kwargs):
        if self.name == "episode_audio.wav":
            raise OSError("simulated mid-audit stat failure")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _fail_on_track)
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert isinstance(problems, list)
    assert problems
    assert any("simulated mid-audit stat failure" in problem for problem in problems)


def test_oserror_from_governed_iterdir_becomes_a_problem_not_an_exception(
    composition_dir_ep1, monkeypatch
) -> None:
    """An ``OSError`` from the top-level inventory ``iterdir()`` becomes a problem."""
    from pathlib import Path

    real_iterdir = Path.iterdir

    def _fail_on_composition_dir(self, *args, **kwargs):
        if self == composition_dir_ep1:
            raise OSError("simulated mid-audit iterdir failure")
        return real_iterdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "iterdir", _fail_on_composition_dir)
    problems = audit_audio_composition_directory(composition_dir_ep1)
    assert isinstance(problems, list)
    assert problems
    assert any("simulated mid-audit iterdir failure" in problem for problem in problems)


def test_good_directory_still_returns_empty_list_with_the_oserror_boundary_installed(
    composition_dir_ep1,
) -> None:
    """The new OSError safety boundary changes nothing about a genuinely good directory."""
    assert audit_audio_composition_directory(composition_dir_ep1) == []
