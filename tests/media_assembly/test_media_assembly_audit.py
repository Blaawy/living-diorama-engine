"""The self-contained audit -- Correction K family B, and the mapping/D-chain re-proofs.

Every test here operates on a real, published assembly directory (a fresh,
function-scoped copy of the shared ep1 publication, or a hand-built minimal
directory for isolated attacks), never on a hand-typed fixture. Attacks
marked ``[audit]`` in the frozen adversarial matrix are proven here, on a
hand-built published directory with no upstream path present.
"""

import inspect
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

import living_diorama.media_assembly as media_assembly_package
from living_diorama.media_assembly.media_assembly_audit import (
    _audit_media_assembly_directory_with_observation,
    audit_media_assembly_directory,
)
from living_diorama.media_assembly.media_assembly_spec import (
    AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME,
    AUDIO_DIRECTORY,
    DELIVERY_PLAN_COPY_FILENAME,
    EPISODE_AUDIO_FILENAME,
    MEDIA_ASSEMBLY_MANIFEST_FILENAME,
    PRESENTATION_DIRECTORY,
    PRESENTATION_PLAN_COPY_FILENAME,
    PROVENANCE_DIRECTORY,
    RENDER_MANIFEST_COPY_FILENAME,
    SHOT_PLAN_COPY_FILENAME,
    WRITING_SUFFIX,
    presentation_frame_filename,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical


def _can_hardlink(probe_dir: Path) -> bool:
    probe_dir.mkdir(parents=True, exist_ok=True)
    source = probe_dir / "_probe_source"
    source.write_bytes(b"x")
    try:
        os.link(source, probe_dir / "_probe_link")
    except OSError:
        return False
    return True


def _hardlink_replace(original: Path, target: Path) -> None:
    """Replace ``target`` with a hardlink to ``original``, both real files beforehand."""
    target.unlink()
    os.link(original, target)


def _load(path: Path) -> Any:
    return loads_canonical(path.read_bytes(), path.name)


def _save(path: Path, document: Any) -> None:
    path.write_bytes(dumps_canonical(document, path.name))


# ---------------------------------------------------------------------------
# The public API surface
# ---------------------------------------------------------------------------


def test_clean_directory_returns_no_problems(assembly_dir_ep1: Path) -> None:
    """Clean directory returns no problems."""
    assert audit_media_assembly_directory(assembly_dir_ep1) == []


def test_public_audit_takes_exactly_one_positional_argument() -> None:
    """Public audit takes exactly one positional argument."""
    signature = inspect.signature(audit_media_assembly_directory)
    assert list(signature.parameters) == ["assembly_dir"]


def test_public_all_excludes_the_three_private_helpers() -> None:
    """Public all excludes the three private helpers."""
    exported = set(media_assembly_package.__all__)
    assert "_audit_media_assembly_directory_with_observation" not in exported
    assert "_regular_file_link_count" not in exported
    assert "_require_single_link_regular_file" not in exported


def test_the_private_helper_reads_the_manifest_exactly_once_and_returns_that_observation(
    assembly_dir_ep1: Path,
) -> None:
    """The private helper reads the manifest exactly once and returns that observation."""
    manifest_path = assembly_dir_ep1 / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    on_disk = manifest_path.read_bytes()
    problems, observed_bytes, observed_document = _audit_media_assembly_directory_with_observation(
        assembly_dir_ep1
    )
    assert problems == []
    assert observed_bytes == on_disk
    assert observed_document == loads_canonical(on_disk, "episode media assembly manifest")


def test_a_missing_manifest_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """A missing manifest is a problem."""
    (assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME).unlink()
    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert problems != []


def test_the_audit_writes_nothing(assembly_dir_ep1_copy: Path) -> None:
    """The audit writes nothing."""
    before = {
        str(p.relative_to(assembly_dir_ep1_copy)): p.stat().st_mtime_ns
        for p in sorted(assembly_dir_ep1_copy.rglob("*"))
    }
    audit_media_assembly_directory(assembly_dir_ep1_copy)
    after = {
        str(p.relative_to(assembly_dir_ep1_copy)): p.stat().st_mtime_ns
        for p in sorted(assembly_dir_ep1_copy.rglob("*"))
    }
    assert before == after


def test_an_oserror_becomes_a_problem_string_not_a_raise(
    assembly_dir_ep1_copy: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An oserror becomes a problem string not a raise."""
    real_read_bytes = Path.read_bytes

    def _failing_read_bytes(self: Path, *args: Any, **kwargs: Any) -> bytes:
        if self.name == MEDIA_ASSEMBLY_MANIFEST_FILENAME:
            raise OSError("simulated disk failure")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _failing_read_bytes)
    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert problems != []


def test_audit_succeeds_with_every_upstream_path_deleted(
    assembly_dir_ep1_copy: Path, tmp_path: Path
) -> None:
    """The audit is self-contained: it needs nothing outside the directory it is handed."""
    decoy_upstream = tmp_path / "nonexistent_upstream"
    assert not decoy_upstream.exists()
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) == []


# ---------------------------------------------------------------------------
# Missing / extra / wrong frame
# ---------------------------------------------------------------------------


def test_a_missing_playback_frame_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """A missing playback frame is a problem."""
    (assembly_dir_ep1_copy / PRESENTATION_DIRECTORY / presentation_frame_filename(1)).unlink()
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_an_extra_untracked_frame_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """An extra untracked frame is a problem."""
    manifest = _load(assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME)
    total = manifest["clock"]["presentation_frames_total"]
    extra = assembly_dir_ep1_copy / PRESENTATION_DIRECTORY / presentation_frame_filename(total + 1)
    extra.write_bytes(b"\x89PNG intruder")
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_a_frame_with_wrong_bytes_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """A frame with wrong bytes is a problem."""
    path = assembly_dir_ep1_copy / PRESENTATION_DIRECTORY / presentation_frame_filename(1)
    mutated = bytearray(path.read_bytes())
    mutated[-1] ^= 0xFF
    path.write_bytes(bytes(mutated))
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_a_frame_record_with_wrong_recorded_length_is_a_problem(
    assembly_dir_ep1_copy: Path,
) -> None:
    """A frame record with wrong recorded length is a problem."""
    manifest_path = assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    manifest["frames"][0]["bytes"] += 1
    _save(manifest_path, manifest)
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_a_frame_record_with_wrong_recorded_digest_is_a_problem(
    assembly_dir_ep1_copy: Path,
) -> None:
    """A frame record with wrong recorded digest is a problem."""
    manifest_path = assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    manifest["frames"][0]["sha256"] = "0" * 64
    _save(manifest_path, manifest)
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


# ---------------------------------------------------------------------------
# Missing / extra / renamed document; provenance entries; foreign entries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        RENDER_MANIFEST_COPY_FILENAME,
        PRESENTATION_PLAN_COPY_FILENAME,
        AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME,
    ],
)
def test_a_missing_top_level_document_is_a_problem(
    assembly_dir_ep1_copy: Path, filename: str
) -> None:
    """A missing top level document is a problem."""
    (assembly_dir_ep1_copy / filename).unlink()
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_an_extra_top_level_document_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """An extra top level document is a problem."""
    (assembly_dir_ep1_copy / "extra_document.json").write_bytes(b"{}")
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_a_renamed_top_level_document_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """A renamed top level document is a problem."""
    original = assembly_dir_ep1_copy / RENDER_MANIFEST_COPY_FILENAME
    original.rename(assembly_dir_ep1_copy / "renamed_render_manifest.json")
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_a_missing_provenance_witness_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """A missing provenance witness is a problem."""
    (assembly_dir_ep1_copy / PROVENANCE_DIRECTORY / SHOT_PLAN_COPY_FILENAME).unlink()
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_an_extra_provenance_entry_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """An extra provenance entry is a problem."""
    (assembly_dir_ep1_copy / PROVENANCE_DIRECTORY / "intruder.json").write_bytes(b"{}")
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_a_foreign_top_level_entry_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """A foreign top level entry is a problem."""
    (assembly_dir_ep1_copy / "intruder.txt").write_bytes(b"x")
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_a_writing_leftover_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """A writing leftover is a problem."""
    leftover = assembly_dir_ep1_copy / (RENDER_MANIFEST_COPY_FILENAME + WRITING_SUFFIX)
    leftover.write_bytes(b"{}")
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_a_wrong_wav_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """A wrong WAV is a problem."""
    wav_path = assembly_dir_ep1_copy / AUDIO_DIRECTORY / EPISODE_AUDIO_FILENAME
    mutated = bytearray(wav_path.read_bytes())
    mutated[-1] ^= 0xFF
    wav_path.write_bytes(bytes(mutated))
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_a_manifest_contradicting_a_copied_source_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """A manifest contradicting a copied source is a problem."""
    manifest_path = assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    manifest["source"]["episode"] += 1
    _save(manifest_path, manifest)
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


# ---------------------------------------------------------------------------
# Symlink / junction batteries
# ---------------------------------------------------------------------------


def test_a_symlinked_top_level_document_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """A symlinked top level document is a problem."""
    target = assembly_dir_ep1_copy / RENDER_MANIFEST_COPY_FILENAME
    real_bytes = target.read_bytes()
    target.unlink()
    elsewhere = assembly_dir_ep1_copy.parent / "elsewhere_render_manifest.json"
    elsewhere.write_bytes(real_bytes)
    try:
        target.symlink_to(elsewhere)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_a_symlinked_presentation_directory_is_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """A symlinked presentation directory is a problem."""
    real = assembly_dir_ep1_copy / PRESENTATION_DIRECTORY
    moved = assembly_dir_ep1_copy.parent / "moved_presentation"
    shutil.move(str(real), str(moved))
    try:
        real.symlink_to(moved, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_the_assembly_dir_itself_being_a_symlink_is_a_problem(
    tmp_path: Path, assembly_dir_ep1: Path
) -> None:
    """The assembly dir itself being a symlink is a problem."""
    link = tmp_path / "assembly_link"
    try:
        link.symlink_to(assembly_dir_ep1, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    assert audit_media_assembly_directory(link) != []


# ---------------------------------------------------------------------------
# Correction K -- the audit's own hardlink batteries (K1-K7)
# ---------------------------------------------------------------------------


def test_k1_two_presentation_filenames_hardlinked_to_one_inode(
    assembly_dir_ep1_copy: Path,
) -> None:
    """K1 two presentation filenames hardlinked to one inode."""
    if not _can_hardlink(assembly_dir_ep1_copy.parent / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    frame_one = assembly_dir_ep1_copy / PRESENTATION_DIRECTORY / presentation_frame_filename(1)
    frame_two = assembly_dir_ep1_copy / PRESENTATION_DIRECTORY / presentation_frame_filename(2)
    _hardlink_replace(frame_one, frame_two)
    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert problems != []
    assert any(str(frame_two) in problem for problem in problems)


def test_k2_a_held_run_realised_as_a_hardlink_farm(assembly_dir_ep1_copy: Path) -> None:
    """K2 a held run realised as a hardlink farm."""
    if not _can_hardlink(assembly_dir_ep1_copy.parent / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    frame_one = assembly_dir_ep1_copy / PRESENTATION_DIRECTORY / presentation_frame_filename(1)
    for position in (2, 3, 4, 5):
        target = (
            assembly_dir_ep1_copy / PRESENTATION_DIRECTORY / presentation_frame_filename(position)
        )
        _hardlink_replace(frame_one, target)
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_k3_a_presentation_frame_hardlinked_outside_the_assembly(
    assembly_dir_ep1_copy: Path,
) -> None:
    """K3 a presentation frame hardlinked outside the assembly."""
    if not _can_hardlink(assembly_dir_ep1_copy.parent / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    frame_one = assembly_dir_ep1_copy / PRESENTATION_DIRECTORY / presentation_frame_filename(1)
    outside = assembly_dir_ep1_copy.parent / "outside_copy.png"
    os.link(frame_one, outside)
    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert problems != []
    assert any("2" in problem and str(frame_one) in problem for problem in problems)


def test_k4_the_wav_is_a_hardlink(assembly_dir_ep1_copy: Path) -> None:
    """K4 the WAV is a hardlink."""
    if not _can_hardlink(assembly_dir_ep1_copy.parent / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    wav_path = assembly_dir_ep1_copy / AUDIO_DIRECTORY / EPISODE_AUDIO_FILENAME
    outside = assembly_dir_ep1_copy.parent / "outside_wav.wav"
    shutil.copyfile(wav_path, outside)
    _hardlink_replace(outside, wav_path)
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_k5_a_provenance_witness_is_a_hardlink(assembly_dir_ep1_copy: Path) -> None:
    """K5 a provenance witness is a hardlink."""
    if not _can_hardlink(assembly_dir_ep1_copy.parent / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    witness = assembly_dir_ep1_copy / PROVENANCE_DIRECTORY / SHOT_PLAN_COPY_FILENAME
    outside = assembly_dir_ep1_copy.parent / "outside_shot_plan.json"
    shutil.copyfile(witness, outside)
    _hardlink_replace(outside, witness)
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_k6_a_copied_source_manifest_is_a_hardlink(assembly_dir_ep1_copy: Path) -> None:
    """K6 a copied source manifest is a hardlink."""
    if not _can_hardlink(assembly_dir_ep1_copy.parent / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    document = assembly_dir_ep1_copy / RENDER_MANIFEST_COPY_FILENAME
    outside = assembly_dir_ep1_copy.parent / "outside_render_manifest.json"
    shutil.copyfile(document, outside)
    _hardlink_replace(outside, document)
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_k7_the_assembly_manifest_itself_is_a_hardlink(assembly_dir_ep1_copy: Path) -> None:
    """K7 the assembly manifest itself is a hardlink."""
    if not _can_hardlink(assembly_dir_ep1_copy.parent / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    document = assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    outside = assembly_dir_ep1_copy.parent / "outside_assembly_manifest.json"
    shutil.copyfile(document, outside)
    _hardlink_replace(outside, document)
    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert problems != []


def test_hardlink_problem_names_the_file_and_its_link_count(assembly_dir_ep1_copy: Path) -> None:
    """Hardlink problem names the file and its link count."""
    if not _can_hardlink(assembly_dir_ep1_copy.parent / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    document = assembly_dir_ep1_copy / RENDER_MANIFEST_COPY_FILENAME
    outside = assembly_dir_ep1_copy.parent / "outside_render_manifest.json"
    shutil.copyfile(document, outside)
    _hardlink_replace(outside, document)
    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert any(str(document) in problem and "2" in problem for problem in problems)


# ---------------------------------------------------------------------------
# THE MAPPING RE-PROOF -- F1-F5, hand-built so no upstream path is present
# ---------------------------------------------------------------------------


def test_f1_two_swapped_semantic_frame_declarations_with_correct_pngs(
    assembly_dir_ep1_copy: Path,
) -> None:
    """F1 two swapped semantic frame declarations with correct PNGs.

    Two frame records swap their ``semantic_frame`` declarations, each still carrying its
    own now-mismatched (but individually valid-looking) claim -- the audit must catch this
    via the re-derived mapping, never by trusting either record's own field.
    """
    manifest_path = assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    frames = manifest["frames"]
    # Find two frames with distinct semantic frames to swap.
    first, second = None, None
    for i in range(len(frames) - 1):
        if frames[i]["semantic_frame"] != frames[i + 1]["semantic_frame"]:
            first, second = i, i + 1
            break
    assert first is not None
    frames[first]["semantic_frame"], frames[second]["semantic_frame"] = (
        frames[second]["semantic_frame"],
        frames[first]["semantic_frame"],
    )
    _save(manifest_path, manifest)
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_f4_a_semantic_frame_duplicated_and_another_removed_counts_preserved(
    assembly_dir_ep1_copy: Path,
) -> None:
    """F4 a semantic frame duplicated and another removed counts preserved."""
    manifest_path = assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    frames = manifest["frames"]
    # Overwrite the last frame's semantic_frame with the first's -- duplicate one, drop one,
    # total record count and positions stay identical, so only the mapping re-proof catches it.
    frames[-1]["semantic_frame"] = frames[0]["semantic_frame"]
    _save(manifest_path, manifest)
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


def test_f5_valid_pngs_and_shas_but_ordering_disagrees_with_p27(
    assembly_dir_ep1_copy: Path,
) -> None:
    """F5 valid PNGs and SHAs but ordering disagrees with P27.

    Reverse the frame record order in the manifest while the files on disk stay put --
    every individual byte/digest check can still pass; only positional/order comparison
    against the re-derived mapping catches it.
    """
    manifest_path = assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    frames = manifest["frames"]
    reordered = list(reversed(frames))
    for position, frame in enumerate(reordered, start=1):
        frame["presentation_frame"] = position
    manifest["frames"] = reordered
    _save(manifest_path, manifest)
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


# ---------------------------------------------------------------------------
# A4 -- a frame record whose semantic_frame equals the witness frame
# ---------------------------------------------------------------------------


def test_a4_frame_record_semantic_frame_equal_to_witness_frame(
    assembly_dir_ep1_copy: Path,
) -> None:
    """A4 frame record semantic frame equal to witness frame.

    A forged manifest whose frame record claims the witness frame as its own
    ``semantic_frame`` is refused twice over: standalone schema law refuses it directly,
    and (were schema validation somehow bypassed) the audit's own re-derived mapping never
    produces the witness frame at any position either.
    """
    from living_diorama.media_assembly.media_assembly_schema_v1 import (
        validate_episode_media_assembly_manifest,
    )

    manifest_path = assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    witness = manifest["clock"]["witness_frame"]
    manifest["frames"][0]["semantic_frame"] = witness
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_assembly_manifest(manifest)
    _save(manifest_path, manifest)
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


# ---------------------------------------------------------------------------
# B9 -- any of the five bound digests in the published manifest altered
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "render_manifest_sha256",
        "presentation_plan_sha256",
        "audio_composition_manifest_sha256",
        "delivery_plan_sha256",
        "shot_plan_sha256",
    ],
)
def test_b9_any_bound_digest_altered_is_caught_by_audit_re_hash(
    assembly_dir_ep1_copy: Path, field: str
) -> None:
    """B9 any bound digest altered is caught by audit re hash."""
    manifest_path = assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    manifest["source"][field] = "0" * 64
    _save(manifest_path, manifest)
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


# ---------------------------------------------------------------------------
# D-chain re-proof: D2 failure on a mixed shot-plan assembly
# ---------------------------------------------------------------------------


def test_d2_mixed_shot_plan_assembly_refused_at_audit(
    assembly_dir_ep1_copy: Path, assembly_inputs_ep0: dict[str, Any]
) -> None:
    """D2 mixed shot plan assembly refused at audit.

    Swap the published shot-plan witness for a different, standalone-valid one (ep0's) --
    the D-chain (D3 -> D4 -> D2) must catch the mismatch entirely from published bytes.
    """
    witness_path = assembly_dir_ep1_copy / PROVENANCE_DIRECTORY / SHOT_PLAN_COPY_FILENAME
    witness_path.write_bytes(assembly_inputs_ep0["shot_plan_bytes"])
    assert audit_media_assembly_directory(assembly_dir_ep1_copy) != []


# ---------------------------------------------------------------------------
# G7 -- the published assembly manifest missing is always an audit problem
# ---------------------------------------------------------------------------


def test_g7_missing_manifest_is_always_a_problem(assembly_dir_ep1_copy: Path) -> None:
    """G7 missing manifest is always a problem."""
    (assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME).unlink()
    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert problems != []
    assert any(MEDIA_ASSEMBLY_MANIFEST_FILENAME in problem for problem in problems)


# ---------------------------------------------------------------------------
# The presentation/ inventory sweep enforces the FROZEN FILENAME GRAMMAR
#
# Ownership of an entry under ``presentation/`` is decided by
# ``is_presentation_frame_filename`` alone -- never by an integer scraped off an
# underscore-separated tail. Each attack below adds an EXTRA file while the
# legitimate frame for that coordinate REMAINS PRESENT, so a passing test proves
# an inventory refusal rather than a missing-required-frame refusal.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "foreign_name",
    [
        "evil_0000001.png",
        "frame_1.png",
        "frame_0000001.jpg",
        "frame_\u0661\u0662\u0663\u0664\u0665\u0666\u0667.png",
    ],
    ids=["evil-prefix", "short-digit-field", "wrong-suffix", "non-ascii-digits"],
)
def test_a_foreign_presentation_entry_with_an_in_range_numeric_tail_is_refused(
    assembly_dir_ep1_copy: Path, foreign_name: str
) -> None:
    """A foreign presentation/ entry carrying an in-range numeric tail is refused.

    Every one of these names yields an in-range integer under a naive
    ``int(stem.split("_")[-1])`` classifier and would have escaped the foreign-entry
    sweep. The frozen grammar refuses all four.
    """
    presentation_dir = assembly_dir_ep1_copy / PRESENTATION_DIRECTORY
    legitimate = presentation_dir / presentation_frame_filename(1)
    assert legitimate.is_file(), "the legitimate frame must remain present"
    (presentation_dir / foreign_name).write_bytes(legitimate.read_bytes())

    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert problems != []
    assert any(foreign_name in problem for problem in problems)
    # the legitimate frame is untouched, so this is an inventory refusal, not a
    # missing-frame refusal
    assert legitimate.is_file()


def test_a_writing_leftover_inside_presentation_is_refused(
    assembly_dir_ep1_copy: Path,
) -> None:
    """A .writing leftover inside presentation/ is refused."""
    presentation_dir = assembly_dir_ep1_copy / PRESENTATION_DIRECTORY
    leftover = presentation_dir / (presentation_frame_filename(1) + WRITING_SUFFIX)
    leftover.write_bytes(b"partial")
    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert problems != []
    assert any(leftover.name in problem for problem in problems)


def test_the_legitimate_presentation_inventory_still_passes(assembly_dir_ep1: Path) -> None:
    """The legitimate presentation inventory still passes.

    The grammar tightening must not reject any of the frames the publisher itself
    wrote -- the control for the four refusal cases above.
    """
    assert audit_media_assembly_directory(assembly_dir_ep1) == []


# ---------------------------------------------------------------------------
# THE MAPPING RE-PROOF -- F2 and F3, the two remaining literal mapping attacks
# ---------------------------------------------------------------------------


def _rewrite_positions(assembly_dir: Path, new_semantics: dict[int, int]) -> None:
    """Re-declare and re-materialise the named presentation positions, self-consistently.

    For each ``position -> semantic`` pair the published PNG at that position is
    replaced with the real bytes of that semantic frame (donated by a position in
    this same directory that legitimately carries it -- no upstream path is used),
    and the frame record's ``semantic_frame``, ``bytes`` and ``sha256`` are updated
    to match. ``unique_semantic_frames_used`` is recomputed so the forged manifest
    stays internally consistent.

    The result is a forgery in which EVERY frame record individually agrees with
    the bytes beside it: a naive per-record byte/digest audit accepts it. Only an
    independent re-derivation of the Phase 27 position -> semantic mapping refuses.
    """
    manifest_path = assembly_dir / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    frames = manifest["frames"]

    # Snapshot every donor's payload AND its recorded identity as PLAIN VALUES before
    # any mutation. Holding a reference to the donor record instead would corrupt a
    # later copy, because a donor may itself be one of the positions being rewritten.
    donor_for: dict[int, tuple[bytes, int, str]] = {}
    for record in frames:
        semantic = record["semantic_frame"]
        if semantic not in donor_for:
            donor_for[semantic] = (
                (assembly_dir / record["file"]).read_bytes(),
                record["bytes"],
                record["sha256"],
            )

    for position, semantic in new_semantics.items():
        payload, byte_length, digest = donor_for[semantic]
        record = frames[position - 1]
        (assembly_dir / record["file"]).write_bytes(payload)
        record["semantic_frame"] = semantic
        record["bytes"] = byte_length
        record["sha256"] = digest

    manifest["completeness"]["unique_semantic_frames_used"] = len(
        {record["semantic_frame"] for record in frames}
    )
    _save(manifest_path, manifest)


def _assert_every_record_agrees_with_its_own_bytes(assembly_dir: Path) -> None:
    """Prove the forgery would satisfy a naive per-record byte/digest audit."""
    import hashlib

    manifest = _load(assembly_dir / MEDIA_ASSEMBLY_MANIFEST_FILENAME)
    for record in manifest["frames"]:
        payload = (assembly_dir / record["file"]).read_bytes()
        assert len(payload) == record["bytes"]
        assert hashlib.sha256(payload).hexdigest() == record["sha256"]


def test_f2_a_held_run_permuted_internally(assembly_dir_ep1_copy: Path) -> None:
    """F2 a held run permuted internally.

    The ep1 plan holds semantic frame 25 across presentation positions 25..133.
    This rotates the window [24, 134] -- the held run together with the single
    frame on each side -- one position to the left. Afterwards position 24 shows
    semantic 25, position 133 shows semantic 26 and position 134 shows semantic
    24. Every position still declares a real Phase 23 playback identity and
    carries that identity's real bytes; the total frame count, the per-semantic
    counts and ``unique_semantic_frames_used`` are all unchanged.

    Only the independently re-derived Phase 27 mapping refuses it.
    """
    manifest = _load(assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME)
    before = [record["semantic_frame"] for record in manifest["frames"]]
    assert before[23] == 24
    assert before[24:133] == [25] * 109
    assert before[133] == 26

    window = list(range(24, 135))
    rotated = window[1:] + window[:1]
    _rewrite_positions(
        assembly_dir_ep1_copy,
        {position: before[source - 1] for position, source in zip(window, rotated, strict=True)},
    )

    after_manifest = _load(assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME)
    after = [record["semantic_frame"] for record in after_manifest["frames"]]
    assert after != before
    assert sorted(after) == sorted(before), "the permutation preserves every count"
    assert after_manifest["completeness"]["unique_semantic_frames_used"] == len(set(before))
    _assert_every_record_agrees_with_its_own_bytes(assembly_dir_ep1_copy)

    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert problems != []
    assert any("mapping requires" in problem for problem in problems)


def test_f3_one_hold_shortened_and_another_lengthened_total_unchanged(
    assembly_dir_ep1_copy: Path,
) -> None:
    """F3 one hold shortened and another lengthened, total unchanged.

    The ep1 plan holds semantic frame 25 across positions 25..133 (109 frames) and
    semantic frame 61 across positions 169..494 (326 frames). This moves the final
    position of the first hold into the second: semantic 25 is then held 108 times
    and semantic 61 327 times. The total presentation-frame count is unchanged, no
    semantic frame disappears, every record still declares a real playback identity
    and carries that identity's real bytes.

    Only the independently re-derived Phase 27 mapping refuses it.
    """
    manifest = _load(assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME)
    before = [record["semantic_frame"] for record in manifest["frames"]]
    assert before.count(25) == 109
    assert before.count(61) == 326
    total_before = len(before)

    _rewrite_positions(assembly_dir_ep1_copy, {133: 61})

    after_manifest = _load(assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME)
    after = [record["semantic_frame"] for record in after_manifest["frames"]]
    assert len(after) == total_before, "the total is unchanged"
    assert after.count(25) == 108, "one hold is shorter"
    assert after.count(61) == 327, "another hold is longer"
    assert set(after) == set(before), "no semantic frame vanished"
    assert after_manifest["completeness"]["unique_semantic_frames_used"] == len(set(before))
    _assert_every_record_agrees_with_its_own_bytes(assembly_dir_ep1_copy)

    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert problems != []
    assert any("mapping requires" in problem for problem in problems)


def test_c3_a_valid_different_semantic_frames_png_substituted_at_another_path(
    assembly_dir_ep1_copy: Path,
) -> None:
    """C3 a valid different semantic frame's PNG substituted at another frame's path.

    Position 1 keeps its own (correct) frame record, but the file on disk is
    replaced with the real, valid PNG of a different semantic frame.
    """
    presentation_dir = assembly_dir_ep1_copy / PRESENTATION_DIRECTORY
    manifest = _load(assembly_dir_ep1_copy / MEDIA_ASSEMBLY_MANIFEST_FILENAME)
    first = manifest["frames"][0]
    donor = next(r for r in manifest["frames"] if r["semantic_frame"] != first["semantic_frame"])
    donor_bytes = (assembly_dir_ep1_copy / donor["file"]).read_bytes()
    (presentation_dir / presentation_frame_filename(1)).write_bytes(donor_bytes)

    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert problems != []


def test_b3_the_delivery_witness_swapped_for_another_valid_document_of_its_kind(
    assembly_dir_ep1_copy: Path, assembly_inputs_ep0: dict[str, Any]
) -> None:
    """B3 the delivery witness swapped for another valid document of its kind."""
    witness = assembly_dir_ep1_copy / PROVENANCE_DIRECTORY / DELIVERY_PLAN_COPY_FILENAME
    witness.write_bytes(assembly_inputs_ep0["delivery_plan_bytes"])
    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert problems != []


def test_b4_provenance_documents_consistent_but_not_matching_the_copied_plan(
    assembly_dir_ep1_copy: Path, assembly_inputs_ep0: dict[str, Any]
) -> None:
    """B4 provenance documents internally consistent but not matching the copied plan.

    Both witnesses are replaced with ep0's pair. They agree with EACH OTHER
    perfectly -- ep0's delivery plan really is bound to ep0's shot plan -- so an
    audit that only cross-checked the two witnesses would accept them. Join D3
    refuses because the copied Phase 27 presentation plan binds a different
    delivery digest.
    """
    provenance = assembly_dir_ep1_copy / PROVENANCE_DIRECTORY
    (provenance / DELIVERY_PLAN_COPY_FILENAME).write_bytes(
        assembly_inputs_ep0["delivery_plan_bytes"]
    )
    (provenance / SHOT_PLAN_COPY_FILENAME).write_bytes(assembly_inputs_ep0["shot_plan_bytes"])
    problems = audit_media_assembly_directory(assembly_dir_ep1_copy)
    assert problems != []


# ---------------------------------------------------------------------------
# The JUNCTION half of _is_path_indirection, exercised on a published assembly
# ---------------------------------------------------------------------------


def _junction_only(monkeypatch: pytest.MonkeyPatch, junction_path: Path) -> None:
    """Make exactly one path report as a junction, with symlink still False.

    Windows junction creation is not portable across every filesystem this suite
    may run on, so the junction branch is driven directly. ``is_symlink`` is left
    untouched and keeps returning ``False`` for the same path, so a test that
    passes here proves the junction branch alone produced the refusal.
    """
    real_is_junction = Path.is_junction
    target = str(junction_path)

    def _patched(self: Path) -> bool:
        if str(self) == target:
            return True
        return real_is_junction(self)

    monkeypatch.setattr(Path, "is_junction", _patched)
    assert junction_path.is_junction()
    assert not junction_path.is_symlink()


def test_a_junction_published_assembly_root_is_refused(
    assembly_dir_ep1: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A junction published assembly root is refused."""
    _junction_only(monkeypatch, assembly_dir_ep1)
    problems = audit_media_assembly_directory(assembly_dir_ep1)
    assert problems != []
    assert any("junction" in problem for problem in problems)


@pytest.mark.parametrize(
    "relative",
    [PRESENTATION_DIRECTORY, AUDIO_DIRECTORY, PROVENANCE_DIRECTORY],
)
def test_a_junction_governed_directory_inside_a_published_assembly_is_refused(
    assembly_dir_ep1: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    """A junction governed directory inside a published assembly is refused."""
    _junction_only(monkeypatch, assembly_dir_ep1 / relative)
    problems = audit_media_assembly_directory(assembly_dir_ep1)
    assert problems != []
    assert any("junction" in problem for problem in problems)


@pytest.mark.parametrize(
    "relative",
    [
        RENDER_MANIFEST_COPY_FILENAME,
        PRESENTATION_PLAN_COPY_FILENAME,
        AUDIO_COMPOSITION_MANIFEST_COPY_FILENAME,
        MEDIA_ASSEMBLY_MANIFEST_FILENAME,
        f"{AUDIO_DIRECTORY}/{EPISODE_AUDIO_FILENAME}",
        f"{PROVENANCE_DIRECTORY}/{DELIVERY_PLAN_COPY_FILENAME}",
        f"{PROVENANCE_DIRECTORY}/{SHOT_PLAN_COPY_FILENAME}",
    ],
)
def test_a_junction_governed_file_inside_a_published_assembly_is_refused(
    assembly_dir_ep1: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    """A junction governed regular-file path inside a published assembly is refused."""
    _junction_only(monkeypatch, assembly_dir_ep1 / relative)
    problems = audit_media_assembly_directory(assembly_dir_ep1)
    assert problems != []
    assert any("junction" in problem for problem in problems)


def test_a_junction_presentation_frame_is_refused(
    assembly_dir_ep1: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A junction presentation frame is refused inside the mapping re-proof."""
    frame = assembly_dir_ep1 / PRESENTATION_DIRECTORY / presentation_frame_filename(1)
    _junction_only(monkeypatch, frame)
    problems = audit_media_assembly_directory(assembly_dir_ep1)
    assert problems != []
    assert any("junction" in problem for problem in problems)
