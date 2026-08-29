"""``python -m living_diorama.cli.verify_media_encode`` -- the tool-free auditing CLI.

Mirrors the Phase 33 verifier's test shape. The CLI audit re-validates the two
provenance copies under their LOCKED upstream schemas; those upstream validators
are already proven by their own phases' suites, and the tiny synthetic
provenance documents this suite builds are not full Phase 33 / Phase 34
documents, so both upstream validators are replaced with identity functions for
the whole module. The manifest itself is built through the REAL manifest
builder, and the encode manifest's own locked validator runs unpatched, so the
byte-truth the CLI decides on is still the real Phase 35 contract.
"""

from pathlib import Path

import pytest

from living_diorama.caption_serialization.caption_serialization_spec import (
    SRT_SUFFIX,
    VTT_SUFFIX,
    sidecar_filename,
)
from living_diorama.cli import verify_media_encode as cli
from living_diorama.media_encode.media_encode_manifest import (
    build_episode_media_encode_manifest_bytes,
)
from living_diorama.media_encode.media_encode_spec import (
    ASSEMBLY_MANIFEST_COPY_FILENAME,
    CAPTIONS_MANIFEST_COPY_FILENAME,
    MEDIA_ENCODE_MANIFEST_FILENAME,
    media_encode_id,
    media_filename,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex

_MODE = "baseline"
_EPISODE = 0
_FPS = 24
_FRAMES = 100
_RATE = 48000
_CHANNELS = 2
_PLAN_SHA256 = "0" * 64
_FFMPEG_VERSION = "ffmpeg version 9.0.1-full_build-www.gyan.dev"
_FFPROBE_VERSION = "ffprobe version 9.0.1"


@pytest.fixture(autouse=True)
def identity_upstream_validators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the two locked upstream validators with identity functions.

    The CLI audit re-validates the provenance copies under the locked Phase 33
    and Phase 34 schemas, and the manifest builder re-validates them before a
    document exists. Both are already proven by their own phases' suites; this
    suite hands over tiny synthetic documents that are not full upstream
    documents, so the two validators are stubbed with ``lambda document: document``
    in BOTH import sites -- the audit module and the manifest module. Everything
    else -- the encode manifest's own locked validator, every digest, every join
    and every byte comparison -- runs unpatched.
    """
    for module in (
        "living_diorama.media_encode.media_encode_audit",
        "living_diorama.media_encode.media_encode_manifest",
    ):
        monkeypatch.setattr(
            f"{module}.validate_episode_media_assembly_manifest", lambda document: document
        )
        monkeypatch.setattr(
            f"{module}.validate_episode_caption_serialization_manifest", lambda document: document
        )


def _synthetic_inputs() -> dict[str, object]:
    """The path-free synthetic inputs of one complete Phase 35 build."""
    episode_id = media_encode_id(mode=_MODE, episode=_EPISODE, previous_episode=None)
    srt_bytes = b"1\n00:00:00,000 --> 00:00:01,000\nSynthetic cue.\n"
    vtt_bytes = b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nSynthetic cue.\n"
    mp4_bytes = b"FAKE-MP4-CAPTURED-OBSERVATION-" * 32
    assembly = {
        "format": "living_diorama_episode_media_assembly_manifest",
        "schema_version": 1,
        "source": {
            "episode": _EPISODE,
            "mode": _MODE,
            "previous_episode": None,
            "presentation_plan_sha256": _PLAN_SHA256,
        },
        "clock": {
            "audio_sample_rate_hz": _RATE,
            "audio_samples_total": _FRAMES * (_RATE // _FPS),
            "fps": _FPS,
            "presentation_frames_total": _FRAMES,
            "samples_per_presentation_frame": _RATE // _FPS,
            "semantic_first_frame": 1,
            "semantic_final_frame": _FRAMES,
            "witness_frame": _FRAMES + 1,
        },
    }
    captions = {
        "format": "living_diorama_episode_caption_serialization_manifest",
        "schema_version": 1,
        "source": {
            "episode": _EPISODE,
            "mode": _MODE,
            "previous_episode": None,
            "presentation_plan_sha256": _PLAN_SHA256,
        },
        "clock": {"fps": _FPS, "presentation_frames_total": _FRAMES},
        "sidecars": {
            "srt": {
                "bytes": len(srt_bytes),
                "file": sidecar_filename(episode_id, SRT_SUFFIX),
                "sha256": sha256_hex(srt_bytes),
            },
            "vtt": {
                "bytes": len(vtt_bytes),
                "file": sidecar_filename(episode_id, VTT_SUFFIX),
                "sha256": sha256_hex(vtt_bytes),
            },
        },
    }
    assembly_bytes = dumps_canonical(assembly, "episode media assembly manifest")
    captions_bytes = dumps_canonical(captions, "episode caption serialization manifest")
    return {
        "episode_id": episode_id,
        "assembly": assembly,
        "assembly_bytes": assembly_bytes,
        "captions": captions,
        "captions_bytes": captions_bytes,
        "srt_bytes": srt_bytes,
        "vtt_bytes": vtt_bytes,
        "mp4_bytes": mp4_bytes,
        "streams": {
            "audio_channels": _CHANNELS,
            "audio_codec": "aac",
            "audio_duration_ts": _FRAMES * (_RATE // _FPS),
            "audio_index": 1,
            "audio_sample_rate": _RATE,
            "audio_samples_decoded": _FRAMES * (_RATE // _FPS),
            "audio_start_time": [0, 1],
            "audio_time_base": [1, _RATE],
            "container_formats": ["mp4"],
            "nb_streams": 2,
            "video_avg_frame_rate": [_FPS, 1],
            "video_codec": "h264",
            "video_duration_ts": _FRAMES,
            "video_frames_counted": _FRAMES,
            "video_height": 720,
            "video_index": 0,
            "video_pix_fmt": "yuv420p",
            "video_r_frame_rate": [_FPS, 1],
            "video_start_time": [0, 1],
            "video_time_base": [1, _FPS],
            "video_width": 1280,
        },
        "ffmpeg_version": _FFMPEG_VERSION,
        "ffprobe_version": _FFPROBE_VERSION,
    }


def _manifest_bytes(inputs: dict[str, object]) -> bytes:
    return build_episode_media_encode_manifest_bytes(
        assembly_manifest=inputs["assembly"],
        assembly_manifest_bytes=inputs["assembly_bytes"],
        captions_manifest=inputs["captions"],
        captions_manifest_bytes=inputs["captions_bytes"],
        video_bytes=len(inputs["mp4_bytes"]),
        video_sha256=sha256_hex(inputs["mp4_bytes"]),
        streams=inputs["streams"],
        ffmpeg_version=inputs["ffmpeg_version"],
        ffprobe_version=inputs["ffprobe_version"],
    )


@pytest.fixture
def published_tree(tmp_path: Path) -> Path:
    """A tiny, byte-truthful final-media directory, hand-built per W11's recipe.

    The manifest is produced by the REAL builder (``build_episode_media_encode_manifest_bytes``)
    from the synthetic inputs above; the directory name, the episode file name and the
    sidecar names all follow the production naming laws, so the self-contained audit
    re-derives them and passes.
    """
    inputs = _synthetic_inputs()
    episode_id = inputs["episode_id"]
    final_dir = tmp_path / episode_id
    provenance = final_dir / "provenance"
    provenance.mkdir(parents=True)
    (final_dir / MEDIA_ENCODE_MANIFEST_FILENAME).write_bytes(_manifest_bytes(inputs))
    (final_dir / media_filename(episode_id)).write_bytes(inputs["mp4_bytes"])
    (final_dir / sidecar_filename(episode_id, SRT_SUFFIX)).write_bytes(inputs["srt_bytes"])
    (final_dir / sidecar_filename(episode_id, VTT_SUFFIX)).write_bytes(inputs["vtt_bytes"])
    (provenance / ASSEMBLY_MANIFEST_COPY_FILENAME).write_bytes(inputs["assembly_bytes"])
    (provenance / CAPTIONS_MANIFEST_COPY_FILENAME).write_bytes(inputs["captions_bytes"])
    return final_dir


def test_exit_zero_on_a_clean_final_media_directory(
    published_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit zero on a clean final media directory."""
    exit_code = cli.main(["--final-dir", str(published_tree)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "passed" in captured.out
    assert captured.err == ""


def test_a_tampered_episode_file_exits_one_with_problem_lines(
    published_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tampered mp4 exits one, with per-problem lines."""
    mp4 = published_tree / media_filename(published_tree.name)
    payload = bytearray(mp4.read_bytes())
    payload[0] ^= 0xFF
    mp4.write_bytes(bytes(payload))
    exit_code = cli.main(["--final-dir", str(published_tree)])
    assert exit_code == 1
    captured = capsys.readouterr()
    problem_lines = [line for line in captured.err.splitlines() if line.startswith("  PROBLEM ")]
    assert len(problem_lines) >= 1
    assert "failed" in captured.err


def test_a_missing_directory_refused(tmp_path: Path) -> None:
    """A missing directory refused."""
    exit_code = cli.main(["--final-dir", str(tmp_path / "does_not_exist")])
    assert exit_code == 1


def test_a_non_directory_refused(tmp_path: Path) -> None:
    """A non directory refused."""
    not_a_directory = tmp_path / "just_a_file.txt"
    not_a_directory.write_bytes(b"x")
    exit_code = cli.main(["--final-dir", str(not_a_directory)])
    assert exit_code == 1


def test_a_symlinked_directory_refused_before_any_query(
    tmp_path: Path, published_tree: Path
) -> None:
    """A symlinked final directory is refused before any query follows it."""
    link = tmp_path / "final_link"
    try:
        link.symlink_to(published_tree, target_is_directory=True)
    except OSError:
        pytest.skip("platform cannot create a symlink")
    exit_code = cli.main(["--final-dir", str(link)])
    assert exit_code == 1


def test_system_exit_when_the_required_flag_is_missing() -> None:
    """The required ``--final-dir`` flag raises SystemExit when absent."""
    with pytest.raises(SystemExit):
        cli.main([])


def test_traceback_never_appears_in_stderr_on_a_failing_directory(
    published_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Traceback never appears in stderr on a failing directory."""
    mp4 = published_tree / media_filename(published_tree.name)
    payload = bytearray(mp4.read_bytes())
    payload[-1] ^= 0xFF
    mp4.write_bytes(bytes(payload))
    exit_code = cli.main(["--final-dir", str(published_tree)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err


def test_the_cli_exposes_only_final_dir() -> None:
    """The CLI exposes only the ``--final-dir`` flag."""
    import inspect

    source = inspect.getsource(cli.main)
    assert source.count("add_argument(") == 1
    assert '"--final-dir"' in source
