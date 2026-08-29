"""Phase 35 publisher orchestration: staging writes, path-neutrality gates, publication.

Every scenario here drives the REAL publisher functions directly against a hand-built,
schema-valid final-media tree whose two upstream manifests are validated by identity
(see the autouse fixture below) -- the locked Phase 33/34 validators' own suites prove
their truth, and these tests target Phase 35's own filesystem and join laws. Style
mirrors ``tests/media_assembly``: ``tmp_path``, skip-guarded probes, ``raises-match``.
"""

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
from living_diorama.media_encode.media_encode_audit import audit_media_encode_directory
from living_diorama.media_encode.media_encode_manifest import (
    build_episode_media_encode_manifest_document,
)
from living_diorama.media_encode.media_encode_probe import normalize_probe_document
from living_diorama.media_encode.media_encode_publisher import (
    HANDLED_REFUSALS,
    begin_media_encode_staging,
    publish_media_encode,
    write_final_media,
    write_media_encode_manifest,
    write_provenance_copies,
    write_sidecar_copies,
)
from living_diorama.media_encode.media_encode_spec import (
    ENCODING_SUFFIX,
    MEDIA_ENCODE_MANIFEST_FILENAME,
    PARTIAL_SUFFIX,
    PROVENANCE_DIRECTORY,
    PROVENANCE_DIRECTORY_ENTRIES,
    MediaEncodeRefused,
    final_media_directory_entries,
    media_filename,
)
from living_diorama.media_encode.media_encode_staging import MediaEncodeDirectoryRefused
from living_diorama.persistence.json_codec import dumps_canonical
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
    """Build one complete, schema-valid published final-media directory BY HAND.

    Every document is hand-typed (the two upstream ones pass the patched identity
    validators; the media encode manifest must pass the REAL locked validator, so its
    streams block comes from the real ``normalize_probe_document``). The tree is then
    written by the real publisher functions in the frozen order and published, so the
    returned directory is exactly what a finished Phase 35 build leaves behind.
    """
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


def _begin(tmp_path: Path) -> tuple[Path, Path, str]:
    """Begin staging under a fresh output root."""
    return begin_media_encode_staging(tmp_path / "out", EPISODE_ID)


def _write_full_staging(staging_dir: Path, tree: PublishedTree) -> None:
    """Run every staging write in the frozen order, without publishing."""
    write_final_media(staging_dir, EPISODE_ID, tree.mp4_bytes)
    write_sidecar_copies(
        staging_dir,
        EPISODE_ID,
        captions_manifest=tree.captions_doc,
        srt_bytes=tree.srt_bytes,
        vtt_bytes=tree.vtt_bytes,
    )
    write_provenance_copies(
        staging_dir,
        assembly_manifest_bytes=tree.assembly_bytes,
        captions_manifest_bytes=tree.captions_bytes,
    )
    write_media_encode_manifest(
        staging_dir, tree.manifest_bytes, runtime_roots=(str(tree.output_root),)
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_publishes_five_top_level_entries_and_two_provenance_copies(
    tree: PublishedTree,
) -> None:
    """Happy path publishes exactly five top entries and two provenance copies."""
    top = {entry.name for entry in tree.final_dir.iterdir()}
    assert top == final_media_directory_entries(EPISODE_ID)
    provenance = {entry.name for entry in (tree.final_dir / PROVENANCE_DIRECTORY).iterdir()}
    assert provenance == PROVENANCE_DIRECTORY_ENTRIES


def test_happy_path_published_tree_passes_its_own_audit(tree: PublishedTree) -> None:
    """The published tree is audited clean under the patched upstream validators."""
    assert audit_media_encode_directory(tree.final_dir) == []


# ---------------------------------------------------------------------------
# write_final_media -- V47/V48
# ---------------------------------------------------------------------------


def test_write_final_media_returns_the_captured_sha256(tmp_path: Path) -> None:
    """write_final_media returns the digest of the captured observation."""
    staging_dir, _, _ = _begin(tmp_path)
    mp4 = b"FTYPFAKE" + bytes(range(256)) * 4
    captured = write_final_media(staging_dir, EPISODE_ID, mp4)
    assert captured == sha256_hex(mp4)
    assert (staging_dir / media_filename(EPISODE_ID)).read_bytes() == mp4


def test_write_final_media_refuses_an_empty_capture(tmp_path: Path) -> None:
    """An empty capture is refused: one truthful encode leaves one non-empty file."""
    staging_dir, _, _ = _begin(tmp_path)
    with pytest.raises(MediaEncodeRefused, match="captured media is empty"):
        write_final_media(staging_dir, EPISODE_ID, b"")


def test_write_final_media_refuses_non_bytes(tmp_path: Path) -> None:
    """A non-bytes capture is a TypeError, not a silent coercion."""
    staging_dir, _, _ = _begin(tmp_path)
    with pytest.raises(TypeError):
        write_final_media(staging_dir, EPISODE_ID, "not bytes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# write_sidecar_copies -- V54
# ---------------------------------------------------------------------------


def test_write_sidecar_copies_refuses_a_captured_byte_mismatch(tmp_path: Path) -> None:
    """A captured sidecar whose length disagrees with the P34 record is refused."""
    staging_dir, _, _ = _begin(tmp_path)
    srt = b"1\n00:00:01,000 --> 00:00:07,000\nx\n"
    vtt = b"WEBVTT\n\n00:00:01.000 --> 00:00:07.000\nx\n"
    captions = _captions_document(srt, vtt)
    captions["sidecars"]["srt"]["bytes"] = len(srt) + 1
    with pytest.raises(MediaEncodeRefused, match="caption serialization manifest records"):
        write_sidecar_copies(
            staging_dir,
            EPISODE_ID,
            captions_manifest=captions,
            srt_bytes=srt,
            vtt_bytes=vtt,
        )


def test_write_sidecar_copies_refuses_a_captured_sha_mismatch(tmp_path: Path) -> None:
    """A captured sidecar whose digest disagrees with the P34 record is refused."""
    staging_dir, _, _ = _begin(tmp_path)
    srt = b"1\n00:00:01,000 --> 00:00:07,000\nx\n"
    vtt = b"WEBVTT\n\n00:00:01.000 --> 00:00:07.000\nx\n"
    captions = _captions_document(srt, vtt)
    captions["sidecars"]["srt"]["sha256"] = "0" * 64
    with pytest.raises(MediaEncodeRefused, match="caption serialization manifest records"):
        write_sidecar_copies(
            staging_dir,
            EPISODE_ID,
            captions_manifest=captions,
            srt_bytes=srt,
            vtt_bytes=vtt,
        )


def test_write_sidecar_copies_refuses_non_bytes(tmp_path: Path) -> None:
    """A non-bytes sidecar payload is a TypeError."""
    staging_dir, _, _ = _begin(tmp_path)
    srt = b"1\n00:00:01,000 --> 00:00:07,000\nx\n"
    vtt = b"WEBVTT\n\n00:00:01.000 --> 00:00:07.000\nx\n"
    captions = _captions_document(srt, vtt)
    with pytest.raises(TypeError):
        write_sidecar_copies(
            staging_dir,
            EPISODE_ID,
            captions_manifest=captions,
            srt_bytes="not bytes",  # type: ignore[arg-type]
            vtt_bytes=vtt,
        )


# ---------------------------------------------------------------------------
# write_media_encode_manifest -- V57 path-neutrality
# ---------------------------------------------------------------------------


def test_write_media_encode_manifest_refuses_a_backslash(tmp_path: Path) -> None:
    """Canonical bytes carrying any backslash are refused outright."""
    staging_dir, _, _ = _begin(tmp_path)
    payload = b'{"smuggled": "C:\\tmp\\x"}'
    with pytest.raises(MediaEncodeRefused, match="backslash"):
        write_media_encode_manifest(staging_dir, payload, runtime_roots=())


def test_write_media_encode_manifest_refuses_a_runtime_root(tmp_path: Path) -> None:
    """Canonical bytes naming any runtime root are refused as path-dependent.

    The root is smuggled in forward-slash form: a backslash-carrying form would
    trip the separate backslash law first, and this test targets the root law.
    """
    staging_dir, _, _ = _begin(tmp_path)
    root = str(tmp_path).replace(chr(92), "/")
    payload = b'{"smuggled": "' + root.encode("utf-8") + b'"}'
    with pytest.raises(MediaEncodeRefused, match="runtime root"):
        write_media_encode_manifest(staging_dir, payload, runtime_roots=(root,))


def test_write_media_encode_manifest_writes_clean_bytes(
    tmp_path: Path, tree: PublishedTree
) -> None:
    """Path-neutral canonical bytes are written, once, to the manifest name."""
    staging_dir, _, _ = _begin(tmp_path)
    write_media_encode_manifest(
        staging_dir, tree.manifest_bytes, runtime_roots=(str(tree.output_root),)
    )
    assert (staging_dir / MEDIA_ENCODE_MANIFEST_FILENAME).read_bytes() == tree.manifest_bytes


# ---------------------------------------------------------------------------
# begin_media_encode_staging -- indirection refusal, stale discard, no-op branch
# ---------------------------------------------------------------------------


def test_begin_refuses_a_symlinked_output_root(tmp_path: Path) -> None:
    """A symlinked output root is refused before anything is created (skip-guarded)."""
    real_root = tmp_path / "real_root"
    real_root.mkdir()
    link_root = tmp_path / "linked_root"
    try:
        link_root.symlink_to(real_root, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(MediaEncodeDirectoryRefused, match="symlink or junction"):
        begin_media_encode_staging(link_root, EPISODE_ID)


def test_begin_refuses_a_symlinked_final_path(tmp_path: Path) -> None:
    """A final path that is an indirection is refused, never followed (skip-guarded)."""
    output_root = tmp_path / "out"
    output_root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    final_link = output_root / EPISODE_ID
    try:
        final_link.symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    with pytest.raises(MediaEncodeDirectoryRefused, match="never follows an indirection"):
        begin_media_encode_staging(output_root, EPISODE_ID)


def test_begin_allows_a_pre_existing_final_directory(tmp_path: Path) -> None:
    """A plain pre-existing final DIRECTORY is the executor's no-op branch: begin passes."""
    output_root = tmp_path / "out"
    final_dir = output_root / EPISODE_ID
    final_dir.mkdir(parents=True)
    staging_dir, resolved_final, staging_name = begin_media_encode_staging(output_root, EPISODE_ID)
    assert resolved_final == final_dir
    assert final_dir.is_dir()
    assert staging_name == f"{EPISODE_ID}{PARTIAL_SUFFIX}"
    assert (staging_dir / PROVENANCE_DIRECTORY).is_dir()


def test_begin_discards_stale_owned_staging(tmp_path: Path) -> None:
    """A stale, provably-owned staging tree from a prior run is discarded fresh."""
    output_root = tmp_path / "out"
    stale = output_root / f"{EPISODE_ID}{PARTIAL_SUFFIX}"
    stale.mkdir(parents=True)
    leftover = stale / f"{media_filename(EPISODE_ID)}{ENCODING_SUFFIX}"
    leftover.write_bytes(b"stale leftover")
    staging_dir, _, _ = begin_media_encode_staging(output_root, EPISODE_ID)
    assert not leftover.exists()
    assert staging_dir.is_dir()
    assert list(staging_dir.iterdir()) == [staging_dir / PROVENANCE_DIRECTORY]


# ---------------------------------------------------------------------------
# publish_media_encode -- V60 terminal gates
# ---------------------------------------------------------------------------


def test_publish_refuses_an_existing_final_and_deletes_nothing(
    tmp_path: Path, tree: PublishedTree
) -> None:
    """Publication onto an existing final refuses; nothing is deleted or overwritten."""
    output_root = tmp_path / "conflict_root"
    output_root.mkdir()
    existing = output_root / EPISODE_ID
    existing.write_bytes(b"a pre-existing final FILE")
    staging_dir, final_dir, staging_name = begin_media_encode_staging(output_root, EPISODE_ID)
    _write_full_staging(staging_dir, tree)
    with pytest.raises(MediaEncodeDirectoryRefused, match="nothing is deleted"):
        publish_media_encode(
            staging_dir,
            final_dir,
            output_root=output_root,
            staging_name=staging_name,
            final_name=EPISODE_ID,
        )
    assert existing.read_bytes() == b"a pre-existing final FILE"


def test_publish_refuses_a_staged_tree_that_failed_its_own_audit(
    tmp_path: Path, tree: PublishedTree
) -> None:
    """A staged tree tampered after the writes fails its own terminal audit."""
    output_root = tmp_path / "tamper_root"
    output_root.mkdir()
    staging_dir, final_dir, staging_name = begin_media_encode_staging(output_root, EPISODE_ID)
    _write_full_staging(staging_dir, tree)
    staged_mp4 = staging_dir / media_filename(EPISODE_ID)
    mutated = bytearray(staged_mp4.read_bytes())
    mutated[-1] ^= 0xFF
    staged_mp4.write_bytes(bytes(mutated))
    with pytest.raises(MediaEncodeRefused, match="failed its own independent audit"):
        publish_media_encode(
            staging_dir,
            final_dir,
            output_root=output_root,
            staging_name=staging_name,
            final_name=EPISODE_ID,
        )
    assert not final_dir.exists()
    assert staging_dir.exists(), "the failed staged tree survives as evidence"


def test_handled_refusals_contains_exactly_the_reviewed_classes() -> None:
    """HANDLED_REFUSALS is exactly the reviewed class tuple, MediaEncodeRefused a ValueError."""
    assert (OSError, TypeError, ValueError, MediaEncodeDirectoryRefused) == HANDLED_REFUSALS
    assert issubclass(MediaEncodeRefused, ValueError)
    assert issubclass(MediaEncodeDirectoryRefused, RuntimeError)
