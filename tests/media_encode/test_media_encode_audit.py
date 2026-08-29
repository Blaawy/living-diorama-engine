"""The self-contained final-media audit -- V45-V60 audit side, and the V73 leftovers.

Every attack runs against a FRESH ``shutil.copytree`` copy of one real, published
final-media tree built by the shared hand-built helper (see
``build_final_media_tree``), never a hand-typed fixture. The locked upstream
validators inside the audit are identity-patched by the autouse fixture below --
their truth is proven by their own suites, and these tests target Phase 35's own
filesystem and join laws. Style mirrors ``tests/media_assembly``.
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import living_diorama.media_encode.media_encode_audit as audit_module
import living_diorama.media_encode.media_encode_manifest as manifest_module
from living_diorama.caption_serialization.caption_serialization_spec import (
    SRT_SUFFIX,
    VTT_SUFFIX,
    sidecar_filename,
)
from living_diorama.media_encode.media_encode_audit import (
    _audit_media_encode_directory_with_observation,
    audit_media_encode_directory,
)
from living_diorama.media_encode.media_encode_manifest import (
    build_episode_media_encode_manifest_document,
)
from living_diorama.media_encode.media_encode_probe import normalize_probe_document
from living_diorama.media_encode.media_encode_publisher import (
    begin_media_encode_staging,
    publish_media_encode,
    write_final_media,
    write_media_encode_manifest,
    write_provenance_copies,
    write_sidecar_copies,
)
from living_diorama.media_encode.media_encode_schema_v1 import (
    validate_episode_media_encode_manifest,
)
from living_diorama.media_encode.media_encode_spec import (
    ASSEMBLY_MANIFEST_COPY_FILENAME,
    CAPTIONS_MANIFEST_COPY_FILENAME,
    MEDIA_ENCODE_MANIFEST_FILENAME,
    PROVENANCE_DIRECTORY,
    SNAPSHOT_AUDIO_FILENAME,
    WRITING_SUFFIX,
    media_filename,
)
from living_diorama.media_encode.media_encode_staging import _regular_file_link_count
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex

EPISODE_ID = "episode_0000_to_0001"
PRESENTATION_PLAN_SHA256 = "a" * 64
FFMPEG_VERSION = "ffmpeg version 9.0.1-full_build-www.gyan.dev"
FFPROBE_VERSION = "ffprobe version 9.0.1-full_build-www.gyan.dev"


@dataclass(frozen=True)
class PublishedTree:
    """One complete, audited final-media publication plus the sources that built it."""

    final_dir: Path
    output_root: Path
    episode_id: str
    assembly_doc: dict[str, Any]
    assembly_bytes: bytes
    captions_doc: dict[str, Any]
    captions_bytes: bytes
    manifest_doc: dict[str, Any]
    manifest_bytes: bytes
    mp4_bytes: bytes
    srt_bytes: bytes
    vtt_bytes: bytes


@pytest.fixture(autouse=True)
def _identity_upstream_validators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the LOCKED upstream validators with identity, inside both callers.

    The real ``validate_episode_media_assembly_manifest`` and
    ``validate_episode_caption_serialization_manifest`` are heavy and their truth is
    already proven by their own suites; these tests target Phase 35's own filesystem
    and join laws. Both the audit and the manifest builder import those names into
    their own module namespaces, so both must be patched for the hand-built documents
    to flow through untouched.
    """
    monkeypatch.setattr(
        audit_module, "validate_episode_media_assembly_manifest", lambda document: document
    )
    monkeypatch.setattr(
        audit_module, "validate_episode_caption_serialization_manifest", lambda document: document
    )
    monkeypatch.setattr(
        manifest_module, "validate_episode_media_assembly_manifest", lambda document: document
    )
    monkeypatch.setattr(
        manifest_module,
        "validate_episode_caption_serialization_manifest",
        lambda document: document,
    )


# ---------------------------------------------------------------------------
# Shared helper: build one COMPLETE, SCHEMA-VALID published tree BY HAND
# ---------------------------------------------------------------------------


def _assembly_document() -> dict[str, Any]:
    """Return the hand-built Phase 33 assembly manifest dict (validated by identity)."""
    return {
        "schema_version": 1,
        "source": {
            "episode": 1,
            "mode": "transition",
            "previous_episode": 0,
            "presentation_plan_sha256": PRESENTATION_PLAN_SHA256,
        },
        "clock": {
            "fps": 24,
            "presentation_frames_total": 720,
            "audio_sample_rate_hz": 24000,
            "samples_per_presentation_frame": 1000,
            "audio_samples_total": 720000,
            "semantic_first_frame": 1,
            "semantic_final_frame": 192,
            "witness_frame": 193,
        },
    }


def _captions_document(srt: bytes, vtt: bytes) -> dict[str, Any]:
    """Return the hand-built Phase 34 captions manifest dict (validated by identity)."""
    return {
        "schema_version": 1,
        "source": {
            "episode": 1,
            "mode": "transition",
            "previous_episode": 0,
            "presentation_plan_sha256": PRESENTATION_PLAN_SHA256,
        },
        "clock": {"fps": 24, "presentation_frames_total": 720},
        "sidecars": {
            "srt": {
                "bytes": len(srt),
                "file": sidecar_filename(EPISODE_ID, SRT_SUFFIX),
                "sha256": sha256_hex(srt),
            },
            "vtt": {
                "bytes": len(vtt),
                "file": sidecar_filename(EPISODE_ID, VTT_SUFFIX),
                "sha256": sha256_hex(vtt),
            },
        },
    }


def _probe_document(
    *,
    fps: int = 24,
    presentation_frames_total: int = 720,
    audio_sample_rate_hz: int = 24000,
    audio_samples_total: int = 720000,
) -> dict[str, Any]:
    """Return a minimal ffprobe report the real normalize helper accepts."""
    return {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "pix_fmt": "yuv420p",
                "width": 1280,
                "height": 720,
                "time_base": "1/90000",
                "start_pts": 0,
                "start_time": "0.000000",
                "duration_ts": presentation_frames_total * 90000 // fps,
                "duration": "30.000000",
                "avg_frame_rate": f"{fps}/1",
                "r_frame_rate": f"{fps}/1",
                "nb_read_frames": presentation_frames_total,
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "sample_rate": str(audio_sample_rate_hz),
                "time_base": f"1/{audio_sample_rate_hz}",
                "start_pts": 0,
                "start_time": "0.000000",
                "duration_ts": audio_samples_total,
                "duration": "30.000000",
            },
        ],
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
    }


def build_final_media_tree(tmp_path: Path) -> PublishedTree:
    """Build one complete, schema-valid published final-media directory BY HAND."""
    srt = b"1\n00:00:01,000 --> 00:00:07,000\nx\n"
    vtt = b"WEBVTT\n\n00:00:01.000 --> 00:00:07.000\nx\n"
    mp4 = b"FTYPFAKE" + bytes(range(256)) * 8
    assembly_doc = _assembly_document()
    captions_doc = _captions_document(srt, vtt)
    assembly_bytes = dumps_canonical(assembly_doc, "episode media assembly manifest")
    captions_bytes = dumps_canonical(captions_doc, "episode caption serialization manifest")
    streams = normalize_probe_document(_probe_document(), audio_samples_decoded=720000)
    manifest_doc = build_episode_media_encode_manifest_document(
        assembly_manifest=assembly_doc,
        assembly_manifest_bytes=assembly_bytes,
        captions_manifest=captions_doc,
        captions_manifest_bytes=captions_bytes,
        video_bytes=len(mp4),
        video_sha256=sha256_hex(mp4),
        streams=streams,
        ffmpeg_version=FFMPEG_VERSION,
        ffprobe_version=FFPROBE_VERSION,
    )
    manifest_bytes = dumps_canonical(manifest_doc, "episode media encode manifest")

    output_root = tmp_path / "out"
    staging_dir, final_dir, staging_name = begin_media_encode_staging(output_root, EPISODE_ID)
    write_final_media(staging_dir, EPISODE_ID, mp4)
    write_sidecar_copies(
        staging_dir,
        EPISODE_ID,
        captions_manifest=captions_doc,
        srt_bytes=srt,
        vtt_bytes=vtt,
    )
    write_provenance_copies(
        staging_dir,
        assembly_manifest_bytes=assembly_bytes,
        captions_manifest_bytes=captions_bytes,
    )
    write_media_encode_manifest(staging_dir, manifest_bytes, runtime_roots=(str(output_root),))
    publish_media_encode(
        staging_dir,
        final_dir,
        output_root=output_root,
        staging_name=staging_name,
        final_name=EPISODE_ID,
    )
    return PublishedTree(
        final_dir=final_dir,
        output_root=output_root,
        episode_id=EPISODE_ID,
        assembly_doc=assembly_doc,
        assembly_bytes=assembly_bytes,
        captions_doc=captions_doc,
        captions_bytes=captions_bytes,
        manifest_doc=manifest_doc,
        manifest_bytes=manifest_bytes,
        mp4_bytes=mp4,
        srt_bytes=srt,
        vtt_bytes=vtt,
    )


@pytest.fixture()
def tree(tmp_path: Path) -> PublishedTree:
    """One fresh, published final-media tree per test."""
    return build_final_media_tree(tmp_path)


def _copy_tree(tree: PublishedTree, tmp_path: Path) -> Path:
    """Return a fresh, independent copy of the published tree for one attack."""
    copy = tmp_path / "tree_copy"
    shutil.copytree(tree.final_dir, copy)
    return copy


def _load(path: Path) -> Any:
    return loads_canonical(path.read_bytes(), path.name)


def _save(path: Path, document: Any) -> None:
    path.write_bytes(dumps_canonical(document, path.name))


def _can_hardlink(probe_dir: Path) -> bool:
    probe_dir.mkdir(parents=True, exist_ok=True)
    source = probe_dir / "_probe_source"
    source.write_bytes(b"x")
    try:
        os.link(source, probe_dir / "_probe_link")
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Genuine tree and the one-observation contract
# ---------------------------------------------------------------------------


def test_clean_published_tree_returns_no_problems(tree: PublishedTree) -> None:
    """The genuine published tree audits clean."""
    assert audit_media_encode_directory(tree.final_dir) == []


def test_private_helper_returns_the_one_manifest_observation(tree: PublishedTree) -> None:
    """The private helper returns the manifest bytes/document it read exactly once."""
    manifest_path = tree.final_dir / MEDIA_ENCODE_MANIFEST_FILENAME
    on_disk = manifest_path.read_bytes()
    problems, observed_bytes, observed_document = _audit_media_encode_directory_with_observation(
        tree.final_dir
    )
    assert problems == []
    assert observed_bytes == on_disk
    assert observed_document == loads_canonical(on_disk, "episode media encode manifest")


def test_every_owned_regular_file_has_link_count_one(tree: PublishedTree) -> None:
    """Every owned regular file in a published tree is an independent physical copy."""
    for path in tree.final_dir.rglob("*"):
        if path.is_file():
            assert _regular_file_link_count(path) == 1


# ---------------------------------------------------------------------------
# Missing / non-canonical manifest; missing provenance
# ---------------------------------------------------------------------------


def test_a_missing_manifest_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """A missing manifest means the build never completed."""
    copy = _copy_tree(tree, tmp_path)
    (copy / MEDIA_ENCODE_MANIFEST_FILENAME).unlink()
    problems = audit_media_encode_directory(copy)
    assert any("is missing" in problem for problem in problems)


def test_a_non_canonical_manifest_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """A semantically-equal but reformatted manifest is refused as non-canonical."""
    copy = _copy_tree(tree, tmp_path)
    manifest_path = copy / MEDIA_ENCODE_MANIFEST_FILENAME
    manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
    problems = audit_media_encode_directory(copy)
    assert any("is not canonical bytes" in problem for problem in problems)


def test_a_missing_provenance_directory_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """A missing provenance directory means the build never completed."""
    copy = _copy_tree(tree, tmp_path)
    shutil.rmtree(copy / PROVENANCE_DIRECTORY)
    problems = audit_media_encode_directory(copy)
    assert any("is missing" in problem for problem in problems)


def test_a_missing_assembly_copy_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """A missing assembly manifest copy is a problem."""
    copy = _copy_tree(tree, tmp_path)
    (copy / PROVENANCE_DIRECTORY / ASSEMBLY_MANIFEST_COPY_FILENAME).unlink()
    problems = audit_media_encode_directory(copy)
    assert any("is missing" in problem for problem in problems)


def test_a_missing_captions_copy_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """A missing caption serialization manifest copy is a problem."""
    copy = _copy_tree(tree, tmp_path)
    (copy / PROVENANCE_DIRECTORY / CAPTIONS_MANIFEST_COPY_FILENAME).unlink()
    problems = audit_media_encode_directory(copy)
    assert any("is missing" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Digest / identity / lineage / clock joins, re-proven from the copies
# ---------------------------------------------------------------------------


def test_an_edited_assembly_copy_is_a_bound_digest_problem(
    tree: PublishedTree, tmp_path: Path
) -> None:
    """An edited assembly copy no longer hashes to the manifest's bound digest."""
    copy = _copy_tree(tree, tmp_path)
    assembly_path = copy / PROVENANCE_DIRECTORY / ASSEMBLY_MANIFEST_COPY_FILENAME
    assembly = _load(assembly_path)
    assembly["clock"]["fps"] = 25
    _save(assembly_path, assembly)
    problems = audit_media_encode_directory(copy)
    assert any("binds media_assembly_manifest_sha256" in problem for problem in problems)


def test_an_identity_mismatch_between_the_two_copies_is_a_problem(
    tree: PublishedTree, tmp_path: Path
) -> None:
    """An episode disagreement between the copies is a problem; lineage still holds."""
    copy = _copy_tree(tree, tmp_path)
    captions_path = copy / PROVENANCE_DIRECTORY / CAPTIONS_MANIFEST_COPY_FILENAME
    captions = _load(captions_path)
    captions["source"]["episode"] = 2
    _save(captions_path, captions)
    problems = audit_media_encode_directory(copy)
    assert any("source.episode" in problem for problem in problems)
    assert not any("descend from different presentations" in problem for problem in problems)


def test_a_lineage_join_mismatch_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """JOIN L: copies binding different presentation shas descend from different presentations."""
    copy = _copy_tree(tree, tmp_path)
    captions_path = copy / PROVENANCE_DIRECTORY / CAPTIONS_MANIFEST_COPY_FILENAME
    captions = _load(captions_path)
    captions["source"]["presentation_plan_sha256"] = "b" * 64
    _save(captions_path, captions)
    problems = audit_media_encode_directory(copy)
    assert any("descend from different presentations" in problem for problem in problems)


def test_a_clock_restatement_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """A rebuilt manifest restating the clock is caught against the copy's own clock."""
    copy = _copy_tree(tree, tmp_path)
    fps = 48
    modified_assembly = dict(tree.assembly_doc)
    modified_assembly["clock"] = dict(tree.assembly_doc["clock"])
    modified_assembly["clock"]["fps"] = fps
    modified_assembly["clock"]["samples_per_presentation_frame"] = 500
    modified_assembly["clock"]["audio_samples_total"] = 360000
    modified_captions = dict(tree.captions_doc)
    modified_captions["clock"] = dict(tree.captions_doc["clock"])
    modified_captions["clock"]["fps"] = fps
    modified_captions["clock"]["presentation_frames_total"] = 720
    modified_assembly_bytes = dumps_canonical(modified_assembly, "episode media assembly manifest")
    modified_captions_bytes = dumps_canonical(
        modified_captions, "episode caption serialization manifest"
    )
    streams = normalize_probe_document(
        _probe_document(
            fps=fps,
            presentation_frames_total=720,
            audio_sample_rate_hz=24000,
            audio_samples_total=360000,
        ),
        audio_samples_decoded=360000,
    )
    rebuilt = build_episode_media_encode_manifest_document(
        assembly_manifest=modified_assembly,
        assembly_manifest_bytes=modified_assembly_bytes,
        captions_manifest=modified_captions,
        captions_manifest_bytes=modified_captions_bytes,
        video_bytes=len(tree.mp4_bytes),
        video_sha256=sha256_hex(tree.mp4_bytes),
        streams=streams,
        ffmpeg_version=FFMPEG_VERSION,
        ffprobe_version=FFPROBE_VERSION,
    )
    manifest_path = copy / MEDIA_ENCODE_MANIFEST_FILENAME
    manifest_path.write_bytes(dumps_canonical(rebuilt, "episode media encode manifest"))
    problems = audit_media_encode_directory(copy)
    assert any("copied assembly's own clock" in problem for problem in problems)


def test_a_renamed_directory_is_never_trusted(tree: PublishedTree, tmp_path: Path) -> None:
    """A directory renamed out of its source-derived id is never trusted by name."""
    copy = _copy_tree(tree, tmp_path)
    renamed = copy.parent / "episode_0009_to_0010"
    copy.rename(renamed)
    problems = audit_media_encode_directory(renamed)
    assert any("never trusted under a name" in problem for problem in problems)


# ---------------------------------------------------------------------------
# The episode file and the carried sidecars
# ---------------------------------------------------------------------------


def test_a_flipped_mp4_byte_is_a_digest_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """A flipped byte in the published episode file is a re-hash problem."""
    copy = _copy_tree(tree, tmp_path)
    mp4 = copy / media_filename(EPISODE_ID)
    mutated = bytearray(mp4.read_bytes())
    mutated[-1] ^= 0xFF
    mp4.write_bytes(bytes(mutated))
    problems = audit_media_encode_directory(copy)
    assert any("hashes to" in problem for problem in problems)


def test_a_changed_mp4_length_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """A changed episode file length is a bytes problem against the manifest record."""
    copy = _copy_tree(tree, tmp_path)
    mp4 = copy / media_filename(EPISODE_ID)
    mp4.write_bytes(mp4.read_bytes() + b"\x00")
    problems = audit_media_encode_directory(copy)
    assert any(
        "published episode file is" in problem and "bytes" in problem for problem in problems
    )


def test_a_missing_episode_file_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """A missing published episode file means the build never completed."""
    copy = _copy_tree(tree, tmp_path)
    (copy / media_filename(EPISODE_ID)).unlink()
    problems = audit_media_encode_directory(copy)
    assert any("is missing" in problem for problem in problems)


def test_a_flipped_srt_byte_is_only_a_file_hash_problem(
    tree: PublishedTree, tmp_path: Path
) -> None:
    """A flipped sidecar byte re-hashes wrong while the captions-record equality holds."""
    copy = _copy_tree(tree, tmp_path)
    sidecar = copy / sidecar_filename(EPISODE_ID, SRT_SUFFIX)
    mutated = bytearray(sidecar.read_bytes())
    mutated[-1] ^= 0xFF
    sidecar.write_bytes(bytes(mutated))
    problems = audit_media_encode_directory(copy)
    assert any("hashes to" in problem and sidecar.name in problem for problem in problems)
    assert not any(
        "copied caption serialization manifest's own record" in problem for problem in problems
    )


def test_a_manifest_caption_record_mismatching_the_copy_is_a_problem(
    tree: PublishedTree, tmp_path: Path
) -> None:
    """A manifest caption record diverging from the P34 copy's own record is a problem."""
    copy = _copy_tree(tree, tmp_path)
    manifest_path = copy / MEDIA_ENCODE_MANIFEST_FILENAME
    manifest = _load(manifest_path)
    manifest["captions"]["srt"]["sha256"] = "0" * 64
    _save(manifest_path, manifest)
    problems = audit_media_encode_directory(copy)
    assert any(
        "copied caption serialization manifest's own record" in problem for problem in problems
    )


def test_a_missing_sidecar_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """A missing carried sidecar means the build never completed."""
    copy = _copy_tree(tree, tmp_path)
    (copy / sidecar_filename(EPISODE_ID, VTT_SUFFIX)).unlink()
    problems = audit_media_encode_directory(copy)
    assert any("is missing" in problem for problem in problems)


# ---------------------------------------------------------------------------
# Path-neutrality: only the schema gate is reachable tool-free; the byte scan
# is asserted publisher-side. The audit's backslash/drive-path scan sits AFTER
# schema validation, so a manifest smuggling a backslash through an extra field
# is refused at validation first ("never trusted") -- see the two tests below.
# ---------------------------------------------------------------------------


def test_a_smuggled_backslash_is_refused_at_validation_before_the_byte_scan(
    tree: PublishedTree, tmp_path: Path
) -> None:
    """Manifest bytes carrying a backslash fail schema validation, never reaching the scan."""
    copy = _copy_tree(tree, tmp_path)
    manifest_path = copy / MEDIA_ENCODE_MANIFEST_FILENAME
    manifest_path.write_bytes(b'{"smuggled": "C:\\tmp"}')
    problems = audit_media_encode_directory(copy)
    assert any("episode media encode manifest is invalid" in problem for problem in problems)


def test_schema_refuses_a_foreign_field_that_could_smuggle_a_host_path(
    tree: PublishedTree,
) -> None:
    """The locked schema refuses extra fields, so no field can carry a host path.

    Crafting canonical manifest bytes that legitimately contain a backslash is
    impossible through the schema, so the audit's backslash byte-scan law is proven
    publisher-side instead: ``write_media_encode_manifest`` refuses a backslash and
    any runtime root (see the publisher suite, V57).
    """
    doc = dict(tree.manifest_doc)
    doc["smuggled"] = "C:\\tmp\\x"
    with pytest.raises((TypeError, ValueError)):
        validate_episode_media_encode_manifest(doc)


# ---------------------------------------------------------------------------
# Indirections, hardlinks, leftovers and foreign entries
# ---------------------------------------------------------------------------


def test_a_hardlinked_episode_file_is_never_accepted(tree: PublishedTree, tmp_path: Path) -> None:
    """An episode file that is a hardlink fails the single-link law (skip-guarded)."""
    if not _can_hardlink(tmp_path / "probe_area"):
        pytest.skip("platform or filesystem cannot create a hardlink")
    copy = _copy_tree(tree, tmp_path)
    mp4 = copy / media_filename(EPISODE_ID)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(mp4.read_bytes())
    mp4.unlink()
    os.link(outside, mp4)
    problems = audit_media_encode_directory(copy)
    assert any("never a hardlink" in problem for problem in problems)


def test_a_symlinked_manifest_is_never_trusted(tree: PublishedTree, tmp_path: Path) -> None:
    """A governed entry reached through a symlink is refused outright (skip-guarded)."""
    copy = _copy_tree(tree, tmp_path)
    manifest_path = copy / MEDIA_ENCODE_MANIFEST_FILENAME
    real_bytes = manifest_path.read_bytes()
    manifest_path.unlink()
    outside = copy.parent / "outside_manifest.json"
    outside.write_bytes(real_bytes)
    try:
        manifest_path.symlink_to(outside)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    problems = audit_media_encode_directory(copy)
    assert any(
        "never trusts a governed entry reached through an indirection" in problem
        for problem in problems
    )


def test_a_foreign_top_level_entry_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """An unaccounted top-level entry is a foreign-entry problem."""
    copy = _copy_tree(tree, tmp_path)
    (copy / "extra.bin").write_bytes(b"x")
    problems = audit_media_encode_directory(copy)
    assert any("not accounted for" in problem for problem in problems)


def test_a_snapshot_audio_leftover_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """A leftover source-audio encoding temp proves a run that did not finish (V73)."""
    copy = _copy_tree(tree, tmp_path)
    (copy / SNAPSHOT_AUDIO_FILENAME).write_bytes(b"x")
    problems = audit_media_encode_directory(copy)
    assert any("left behind by a run that did not finish" in problem for problem in problems)


def test_a_manifest_writing_leftover_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """A leftover manifest .writing temp proves a run that did not finish (V73)."""
    copy = _copy_tree(tree, tmp_path)
    (copy / (MEDIA_ENCODE_MANIFEST_FILENAME + WRITING_SUFFIX)).write_bytes(b"x")
    problems = audit_media_encode_directory(copy)
    assert any("left behind by a run that did not finish" in problem for problem in problems)


def test_a_foreign_provenance_entry_is_a_problem(tree: PublishedTree, tmp_path: Path) -> None:
    """An unaccounted provenance entry is a foreign-entry problem."""
    copy = _copy_tree(tree, tmp_path)
    (copy / PROVENANCE_DIRECTORY / "intruder.json").write_bytes(b"{}")
    problems = audit_media_encode_directory(copy)
    assert any("not accounted for" in problem for problem in problems)


def test_a_non_directory_path_is_a_problem(tmp_path: Path) -> None:
    """The audit refuses a non-directory path with 'is not a directory'."""
    path = tmp_path / "not_a_directory"
    path.write_bytes(b"x")
    problems = audit_media_encode_directory(path)
    assert any("is not a directory" in problem for problem in problems)
