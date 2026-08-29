"""The FFmpeg executor, driven end-to-end through the fake-runner seam.

This lane deliberately has NO conftest and imports nothing from one. The production
executor is loaded exactly like the Phase 23 precedent
(``tests/render_execution/test_frame_image.py:37-44``): via
``importlib.util.spec_from_file_location``, so this module can be imported and driven
without any real FFmpeg present. The locked upstream audits are NOT monkeypatched to
be weakened -- the executor's calls are replaced by ``lambda p: []`` so REAL inputs can
be fabricated on ``tmp_path``, while ``loads_canonical``, every schema validator, every
command builder and the publisher stay real. ``validate_episode_render_manifest`` is
monkeypatched to identity because the render manifest copy is a stub document whose
only executor-side role is its bound digest.

Every test runs the whole ``main`` pipeline against a scripted :class:`FakeRunner`
whose probe reports are chosen by inspecting whether the piped stdin bytes equal the
preflight payload the fake encoder wrote -- the golden 64x64 preflight probe versus the
golden 1280x720 real probe -- and whose decode returns exactly the locked sample count
as headerless PCM16 zeros. The published directory is the REAL one: five top-level
entries plus two provenance witnesses, built by the real builders, so the happy path
is re-auditable by the real tool-free audit on a no-op re-run.
"""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from living_diorama.caption_serialization.caption_serialization_spec import (
    CAPTION_SERIALIZATION_MANIFEST_FILENAME,
    SRT_SUFFIX,
    VTT_SUFFIX,
    sidecar_filename,
)
from living_diorama.media_assembly.media_assembly_spec import (
    MEDIA_ASSEMBLY_MANIFEST_FILENAME,
    RENDER_MANIFEST_COPY_FILENAME,
    presentation_frame_relative_path,
)
from living_diorama.media_encode.media_encode_command import preflight_wav_bytes
from living_diorama.media_encode.media_encode_spec import (
    ENCODING_SUFFIX,
    MEDIA_ENCODE_MANIFEST_FILENAME,
    PREFLIGHT_MEDIA_FILENAME,
    PROVENANCE_DIRECTORY,
    SNAPSHOT_AUDIO_FILENAME,
    media_filename,
    media_temp_filename,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "media" / "ffmpeg" / "scripts" / "encode_episode.py"

# ---- the locked geometry every fabricated input and every golden probe shares ----
MODE = "baseline"
EPISODE = 0
PREVIOUS = None
EPISODE_ID = "episode_0000_baseline"
FPS = 24
FRAMES = 720
RATE = 24000
CHANNELS = 1
SAMPLES = 720000
WIDTH = 1280
HEIGHT = 720
HEX = "a" * 64  # a valid 64-lowercase-hex digest for every record field
PRESENTATION_SHA = "b" * 64  # the lineage join both manifests must bind

PREFLIGHT_PAYLOAD = b"fake preflight mp4 payload written by the fake encoder"
REAL_PAYLOAD = b"fake real episode mp4 payload written by the fake encoder"
POISON = b"poisoned bytes planted by the fake runner"


def _load_executor() -> Any:
    """Import the production executor without a real FFmpeg present."""
    spec = importlib.util.spec_from_file_location("encode_episode", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor()


def _probe_document(width: int, height: int) -> dict[str, Any]:
    """The golden ffprobe report for one fake payload: 64x64 preflight or 1280x720 real."""
    return {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "pix_fmt": "yuv420p",
                "width": width,
                "height": height,
                "time_base": "1/90000",
                "start_pts": 0,
                "start_time": "0.000000",
                "duration_ts": 2700000,
                "nb_read_frames": FRAMES,
                "avg_frame_rate": "24/1",
                "r_frame_rate": "24/1",
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": CHANNELS,
                "sample_rate": str(RATE),
                "time_base": "1/24000",
                "start_pts": 0,
                "start_time": "0.000000",
                "duration_ts": SAMPLES,
            },
        ],
        "format": {"format_name": "mp4"},
    }


def _assembly_document(wav_bytes: bytes, render_bytes: bytes) -> dict[str, Any]:
    """A REAL, schema-valid Phase 33 assembly manifest for the fabricated directory."""
    frames = []
    for position in range(FRAMES):
        frames.append(
            {
                "bytes": 1024,
                "file": presentation_frame_relative_path(position + 1),
                "presentation_frame": position + 1,
                "semantic_frame": (position % (FRAMES - 1)) + 1,
                "sha256": HEX,
            }
        )
    unique = len({frame["semantic_frame"] for frame in frames})
    return {
        "format": "living_diorama_episode_media_assembly_manifest",
        "schema_version": 1,
        "source": {
            "audio_composition_manifest_sha256": HEX,
            "audio_composition_schema_version": 1,
            "delivery_plan_sha256": HEX,
            "episode": EPISODE,
            "mode": MODE,
            "motion_time_sha256": HEX,
            "presentation_plan_sha256": PRESENTATION_SHA,
            "presentation_schema_version": 1,
            "previous_episode": None,
            "render_manifest_sha256": sha256_hex(render_bytes),
            "render_manifest_schema_version": 1,
            "shot_plan_sha256": HEX,
        },
        "clock": {
            "audio_sample_rate_hz": RATE,
            "audio_samples_total": SAMPLES,
            "fps": FPS,
            "presentation_frames_total": FRAMES,
            "samples_per_presentation_frame": RATE // FPS,
            "semantic_final_frame": FRAMES - 1,
            "semantic_first_frame": 1,
            "witness_frame": FRAMES,
        },
        "frames": frames,
        "audio": {
            "audio_samples": SAMPLES,
            "bytes": len(wav_bytes),
            "channels": CHANNELS,
            "file": "audio/episode_audio.wav",
            "sample_rate_hz": RATE,
            "sha256": sha256_hex(wav_bytes),
        },
        "completeness": {
            "complete": True,
            "presentation_frames_assembled": FRAMES,
            "presentation_frames_expected": FRAMES,
            "unique_semantic_frames_used": unique,
        },
    }


def _captions_document(srt_bytes: bytes, vtt_bytes: bytes) -> dict[str, Any]:
    """A REAL, schema-valid Phase 34 caption serialization manifest."""
    return {
        "format": "living_diorama_episode_caption_serialization_manifest",
        "schema_version": 1,
        "policy": "caption_timestamp_policy_v1",
        "source": {
            "caption_plan_sha256": HEX,
            "caption_schema_version": 1,
            "episode": EPISODE,
            "mode": MODE,
            "presentation_plan_sha256": PRESENTATION_SHA,
            "presentation_schema_version": 1,
            "previous_episode": None,
            "realization_plan_sha256": HEX,
            "realization_schema_version": 1,
        },
        "clock": {"fps": FPS, "presentation_frames_total": FRAMES},
        "accounting": {
            "caption_frames_total": FRAMES,
            "captions_total": 1,
            "uncaptioned_frames_total": 0,
        },
        "sidecars": {
            "srt": {
                "bytes": len(srt_bytes),
                "file": sidecar_filename(EPISODE_ID, SRT_SUFFIX),
                "format": "srt",
                "sha256": sha256_hex(srt_bytes),
            },
            "vtt": {
                "bytes": len(vtt_bytes),
                "file": sidecar_filename(EPISODE_ID, VTT_SUFFIX),
                "format": "webvtt",
                "sha256": sha256_hex(vtt_bytes),
            },
        },
    }


def build_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Fabricate a REAL assembly dir and captions dir on ``tmp_path``.

    Every JSON file is written through ``dumps_canonical`` -- the exact bytes the
    executor's capture and the digest-bound manifest builders require. The WAV is the
    real ``preflight_wav_bytes`` builder reused as the fake episode track, so its
    digest and length close with the assembly's audio block.
    """
    wav_bytes = preflight_wav_bytes(RATE, CHANNELS, SAMPLES)
    srt_bytes = b"1\n00:00:00,000 --> 00:00:01,000\nhello\n"
    vtt_bytes = b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n"
    render_bytes = dumps_canonical({"schema_version": 1}, "render manifest copy")

    assembly_dir = tmp_path / "assembly"
    captions_dir = tmp_path / "captions"
    (assembly_dir / "audio").mkdir(parents=True)
    captions_dir.mkdir(parents=True)

    (assembly_dir / RENDER_MANIFEST_COPY_FILENAME).write_bytes(render_bytes)
    (assembly_dir / "audio" / "episode_audio.wav").write_bytes(wav_bytes)
    (assembly_dir / MEDIA_ASSEMBLY_MANIFEST_FILENAME).write_bytes(
        dumps_canonical(_assembly_document(wav_bytes, render_bytes), "media assembly manifest")
    )
    (captions_dir / sidecar_filename(EPISODE_ID, SRT_SUFFIX)).write_bytes(srt_bytes)
    (captions_dir / sidecar_filename(EPISODE_ID, VTT_SUFFIX)).write_bytes(vtt_bytes)
    (captions_dir / CAPTION_SERIALIZATION_MANIFEST_FILENAME).write_bytes(
        dumps_canonical(_captions_document(srt_bytes, vtt_bytes), "caption serialization manifest")
    )
    output_root = tmp_path / "output"
    return assembly_dir, captions_dir, output_root


class FakeRunner:
    """A scripted subprocess: version/capability listings, fake encodes, probes, decodes.

    The probe report is chosen by inspecting whether the piped stdin bytes equal the
    preflight payload the fake encoder wrote; the decode returns headerless PCM16 zeros
    for exactly the configured sample count. Every invocation is recorded in ``calls``
    so tests can assert what the executor actually piped.
    """

    def __init__(
        self,
        *,
        encoders_text: str | None = None,
        muxers_text: str | None = None,
        demuxers_text: str | None = None,
        decode_samples: int = SAMPLES,
        preflight_decode_samples: int = SAMPLES,
        encode_returncode: int = 0,
        encode_stderr: bytes = b"",
        real_encode_writes: bool = True,
        preflight_encode_writes: bool = True,
        poison_snapshot: bool = False,
        poison_final_on_decode: bool = False,
        probe_stdout: bytes | None = None,
        probe_returncode: int = 0,
    ) -> None:
        """Configure the scripted runner."""
        self.encoders_text = (
            encoders_text or " V..... libx264  H.264 / AVC / MPEG-4 AVC\n A..... aac\n"
        )
        self.muxers_text = muxers_text or " mp4  mp4 container\n"
        self.demuxers_text = (
            demuxers_text or " image2  image2 demuxer\n wav  wav demuxer\n lavfi  lavfi demuxer\n"
        )
        self.decode_samples = decode_samples
        self.preflight_decode_samples = preflight_decode_samples
        self.encode_returncode = encode_returncode
        self.encode_stderr = encode_stderr
        self.real_encode_writes = real_encode_writes
        self.preflight_encode_writes = preflight_encode_writes
        self.poison_snapshot = poison_snapshot
        self.poison_final_on_decode = poison_final_on_decode
        self.probe_stdout = probe_stdout
        self.probe_returncode = probe_returncode
        self.calls: list[tuple[tuple[str, ...], bytes | None]] = []
        self.probe_stdins: list[bytes] = []
        self.decode_stdins: list[bytes] = []
        self.real_encode_output: str | None = None
        self.preflight_encode_output: str | None = None

    def __call__(self, argv: list[str], stdin_bytes: bytes | None) -> tuple[int, bytes, bytes]:
        """Dispatch one scripted invocation by its argv shape."""
        self.calls.append((tuple(argv), stdin_bytes))
        flags = set(argv)
        if "-version" in flags:
            tool = Path(argv[0]).name
            return (0, f"{tool} version 9.1.2-full_build".encode(), b"")
        if "-encoders" in flags:
            return (0, self.encoders_text.encode("utf-8"), b"")
        if "-muxers" in flags:
            return (0, self.muxers_text.encode("utf-8"), b"")
        if "-demuxers" in flags:
            return (0, self.demuxers_text.encode("utf-8"), b"")
        if argv[0].endswith("ffprobe") or "-print_format" in flags:
            self.probe_stdins.append(stdin_bytes if stdin_bytes is not None else b"")
            if self.probe_stdout is not None or self.probe_returncode != 0:
                return (self.probe_returncode, self.probe_stdout or b"", b"probe failed")
            document = (
                _probe_document(64, 64)
                if stdin_bytes == PREFLIGHT_PAYLOAD
                else _probe_document(WIDTH, HEIGHT)
            )
            return (0, json.dumps(document).encode("utf-8"), b"")
        if argv[-1] == "pipe:1" or "-vn" in flags:
            self.decode_stdins.append(stdin_bytes if stdin_bytes is not None else b"")
            samples = (
                self.preflight_decode_samples
                if stdin_bytes == PREFLIGHT_PAYLOAD
                else self.decode_samples
            )
            return (0, b"\x00" * (samples * 2), b"")
        # an encode invocation: write the fake payload to the output path in argv[-1]
        output = Path(argv[-1])
        is_preflight = output.name == PREFLIGHT_MEDIA_FILENAME
        payload = PREFLIGHT_PAYLOAD if is_preflight else REAL_PAYLOAD
        if is_preflight:
            self.preflight_encode_output = str(output)
        else:
            self.real_encode_output = str(output)
            if self.poison_snapshot:
                (output.parent / SNAPSHOT_AUDIO_FILENAME).write_bytes(POISON)
        if self.encode_returncode != 0:
            return (self.encode_returncode, b"", self.encode_stderr)
        if is_preflight and self.preflight_encode_writes:
            output.write_bytes(payload)
        if not is_preflight and self.real_encode_writes:
            output.write_bytes(payload)
        return (0, b"", b"")


def run_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    runner: FakeRunner,
    *,
    assembly_audit: Any = None,
) -> tuple[int, Path, Path]:
    """Monkeypatch the executor's upstream gates and run ``main`` with the fake runner."""
    assembly_dir, captions_dir, output_root = build_inputs(tmp_path)
    if assembly_audit is None:

        def assembly_audit(path: object) -> list[str]:
            """Assembly audit."""
            return []

    monkeypatch.setattr(executor, "audit_media_assembly_directory", assembly_audit)
    monkeypatch.setattr(executor, "audit_caption_serialization_directory", lambda path: [])
    monkeypatch.setattr(executor, "validate_episode_render_manifest", lambda document: document)
    ffmpeg_path = tmp_path / "ffmpeg"
    ffprobe_path = tmp_path / "ffprobe"
    ffmpeg_path.write_bytes(b"fake tool stand-in; the injected runner never executes it\n")
    ffprobe_path.write_bytes(b"fake tool stand-in; the injected runner never executes it\n")
    argv = [
        "--assembly-dir",
        str(assembly_dir),
        "--captions-dir",
        str(captions_dir),
        "--output-root",
        str(output_root),
        "--ffmpeg",
        str(ffmpeg_path),
        "--ffprobe",
        str(ffprobe_path),
    ]
    exit_code = executor.main(argv, runner=runner)
    return exit_code, output_root, assembly_dir


# ---------------------------------------------------------------------------
# version, capability and locate gates
# ---------------------------------------------------------------------------


def test_version_refusal_old_major(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Version refusal old major."""

    class OldVersionRunner(FakeRunner):
        def __call__(self, argv, stdin_bytes):
            """Dispatch one scripted invocation by its argv shape."""
            if "-version" in argv and Path(argv[0]).name == "ffmpeg":
                return (0, b"ffmpeg version 8.1.2", b"")
            return super().__call__(argv, stdin_bytes)

    exit_code, _output_root, _assembly = run_main(monkeypatch, tmp_path, OldVersionRunner())
    assert exit_code == 1
    assert "cannot satisfy" in capsys.readouterr().err


def test_missing_capability_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing capability refused."""
    runner = FakeRunner(encoders_text=" A..... aac\n")  # no libx264 token
    exit_code, _output_root, _assembly = run_main(monkeypatch, tmp_path, runner)
    assert exit_code == 1
    assert "libx264" in capsys.readouterr().err


def test_decode_odd_pcm_byte_length_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A decode whose PCM byte length is not divisible by 2 x channels refuses.

    The decode-geometry law runs before any sample count is derived: one stray
    byte on the pipe and the build refuses rather than rounding.
    """

    class OddDecodeRunner(FakeRunner):
        def __call__(self, argv, stdin_bytes):
            """Append one stray byte to every decode response."""
            rc, out, err = super().__call__(argv, stdin_bytes)
            if argv[-1] == "pipe:1" or "-vn" in set(argv):
                return (rc, out + bytes([0]), err)
            return (rc, out, err)

    exit_code, _output_root, _assembly = run_main(monkeypatch, tmp_path, OddDecodeRunner())
    assert exit_code == 1
    assert "not divisible" in capsys.readouterr().err


def test_locate_refusal_no_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Locate refusal no tool."""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(executor.EncodeExecutionRefused, match="no ffmpeg executable found"):
        executor._locate("ffmpeg", None, "FFMPEG_EXECUTABLE", {})


def test_locate_refusal_explicit_path_missing() -> None:
    """Locate refusal explicit path missing."""
    with pytest.raises(executor.EncodeExecutionRefused, match="does not exist"):
        executor._locate("ffmpeg", "/nonexistent/ffmpeg", "FFMPEG_EXECUTABLE", {})


def test_locate_env_var_wins_over_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Locate env var wins over path."""
    tool = tmp_path / "ffmpeg"
    tool.write_bytes(b"tool")
    found = executor._locate("ffmpeg", None, "FFMPEG_EXECUTABLE", {"FFMPEG_EXECUTABLE": str(tool)})
    assert found == str(tool)


# ---------------------------------------------------------------------------
# preflight, encode, probe and decode refusals
# ---------------------------------------------------------------------------


def test_preflight_decode_count_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Preflight decode count mismatch."""
    runner = FakeRunner(preflight_decode_samples=SAMPLES - 1000)  # ONLY the preflight decode
    exit_code, _output_root, _assembly = run_main(monkeypatch, tmp_path, runner)
    assert exit_code == 1
    assert "preflight" in capsys.readouterr().err


def test_encode_nonzero_discards_staging(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Encode nonzero discards staging."""
    runner = FakeRunner(encode_returncode=1, encode_stderr=b"boom")
    exit_code, output_root, _assembly = run_main(monkeypatch, tmp_path, runner)
    assert exit_code == 1
    assert not (output_root / f"{EPISODE_ID}.partial").exists()


def test_encode_signal_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Encode signal refused."""
    runner = FakeRunner(encode_returncode=-9)
    exit_code, _output_root, _assembly = run_main(monkeypatch, tmp_path, runner)
    assert exit_code == 1
    assert "terminated by signal" in capsys.readouterr().err


def test_real_encode_temp_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Real encode temp missing."""
    runner = FakeRunner(real_encode_writes=False)  # preflight writes, real encode does not
    exit_code, output_root, _assembly = run_main(monkeypatch, tmp_path, runner)
    assert exit_code == 1
    assert not (output_root / f"{EPISODE_ID}.partial").exists()


def test_zero_byte_temp_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero byte temp refused."""

    class ZeroRunner(FakeRunner):
        def __call__(self, argv, stdin_bytes):
            """Dispatch one scripted invocation by its argv shape."""
            if Path(argv[-1]).name == media_temp_filename(EPISODE_ID):
                Path(argv[-1]).write_bytes(b"")
                return (0, b"", b"")
            return super().__call__(argv, stdin_bytes)

    exit_code, _output_root, _assembly = run_main(monkeypatch, tmp_path, ZeroRunner())
    assert exit_code == 1
    assert "empty" in capsys.readouterr().err


def test_probe_invalid_json_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Probe invalid json refused."""
    runner = FakeRunner(probe_stdout=b"not json at all")
    exit_code, output_root, _assembly = run_main(monkeypatch, tmp_path, runner)
    assert exit_code == 1
    assert not (output_root / f"{EPISODE_ID}.partial").exists()


def test_real_decode_short_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Real decode short refused."""
    runner = FakeRunner(decode_samples=SAMPLES - 1000)  # ONLY the real decode
    exit_code, _output_root, _assembly = run_main(monkeypatch, tmp_path, runner)
    assert exit_code == 1
    assert "never changes the episode's length" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# post-encode stability
# ---------------------------------------------------------------------------


def test_assembly_changed_during_encode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Assembly changed during encode."""
    calls = {"count": 0}

    def stateful_audit(path):
        """Stateful audit."""
        calls["count"] += 1
        return ["tampered"] if calls["count"] > 1 else []

    exit_code, output_root, _assembly = run_main(
        monkeypatch, tmp_path, FakeRunner(), assembly_audit=stateful_audit
    )
    assert exit_code == 1
    assert "changed during the encode" in capsys.readouterr().err
    assert not (output_root / EPISODE_ID).exists()
    assert not (output_root / f"{EPISODE_ID}.partial").exists()


def test_snapshot_rehash_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Snapshot rehash refused."""
    runner = FakeRunner(poison_snapshot=True)  # the fake encode overwrites the snapshot
    exit_code, output_root, _assembly = run_main(monkeypatch, tmp_path, runner)
    assert exit_code == 1
    assert "snapshot" in capsys.readouterr().err
    assert not (output_root / EPISODE_ID).exists()


# ---------------------------------------------------------------------------
# happy path and the capture law
# ---------------------------------------------------------------------------


def test_happy_path_publishes_complete_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Happy path publishes complete directory."""
    runner = FakeRunner()
    exit_code, output_root, _assembly = run_main(monkeypatch, tmp_path, runner)
    assert exit_code == 0
    final_dir = output_root / EPISODE_ID
    assert final_dir.is_dir()
    owned = {
        MEDIA_ENCODE_MANIFEST_FILENAME,
        media_filename(EPISODE_ID),
        sidecar_filename(EPISODE_ID, SRT_SUFFIX),
        sidecar_filename(EPISODE_ID, VTT_SUFFIX),
        PROVENANCE_DIRECTORY,
    }
    assert {entry.name for entry in final_dir.iterdir()} == owned
    assert {entry.name for entry in (final_dir / PROVENANCE_DIRECTORY).iterdir()} == {
        MEDIA_ASSEMBLY_MANIFEST_FILENAME,
        CAPTION_SERIALIZATION_MANIFEST_FILENAME,
    }
    assert (final_dir / media_filename(EPISODE_ID)).read_bytes() == REAL_PAYLOAD
    manifest = json.loads((final_dir / MEDIA_ENCODE_MANIFEST_FILENAME).read_bytes())
    assert manifest["video"]["sha256"] == sha256_hex(REAL_PAYLOAD)
    assert manifest["streams"]["audio_samples_decoded"] == SAMPLES
    assert manifest["streams"]["video_frames_counted"] == FRAMES
    summary = json.loads(capsys.readouterr().out)
    assert summary["final_dir"] == str(final_dir)
    assert summary["video_sha256"] == sha256_hex(REAL_PAYLOAD)
    assert summary["episode"] == EPISODE
    assert summary["mode"] == MODE


def test_poison_path_capture_law(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Poison path capture law."""

    class PoisonRunner(FakeRunner):
        def __call__(self, argv, stdin_bytes):
            """Dispatch one scripted invocation by its argv shape."""
            result = super().__call__(argv, stdin_bytes)
            if argv[-1] == "pipe:1" and stdin_bytes == REAL_PAYLOAD:
                # AFTER the executor captured the temp, poison the staged final path
                temp = Path(self.real_encode_output)
                staged_final = temp.with_name(temp.name[: -len(ENCODING_SUFFIX)])
                staged_final.write_bytes(POISON)
            return result

    runner = PoisonRunner()
    exit_code, output_root, _assembly = run_main(monkeypatch, tmp_path, runner)
    assert exit_code == 0
    assert runner.probe_stdins[-1] == REAL_PAYLOAD  # the probe saw the captured bytes
    final_dir = output_root / EPISODE_ID
    published = (final_dir / media_filename(EPISODE_ID)).read_bytes()
    assert published == REAL_PAYLOAD  # write_final_media rewrote FROM the captured bytes
    assert sha256_hex(published) == sha256_hex(REAL_PAYLOAD)


def test_noop_rerun_verifies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Noop rerun verifies."""
    runner = FakeRunner()
    first_code, output_root, assembly_dir = run_main(monkeypatch, tmp_path, runner)
    assert first_code == 0
    probes_before = len(runner.probe_stdins)
    decodes_before = len(runner.decode_stdins)
    capsys.readouterr()
    exit_code = executor.main(
        [
            "--assembly-dir",
            str(assembly_dir),
            "--captions-dir",
            str(tmp_path / "captions"),
            "--output-root",
            str(output_root),
            "--ffmpeg",
            str(tmp_path / "ffmpeg"),
            "--ffprobe",
            str(tmp_path / "ffprobe"),
        ],
        runner=runner,
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "VERIFIED NO-OP" in out
    assert "re-probe: captured bytes" in out
    assert f"re-decode: {SAMPLES} samples" in out
    assert len(runner.probe_stdins) > probes_before
    assert len(runner.decode_stdins) > decodes_before
    assert (output_root / EPISODE_ID / media_filename(EPISODE_ID)).read_bytes() == REAL_PAYLOAD


def test_noop_different_assembly_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Noop different assembly refused."""
    runner = FakeRunner()
    first_code, output_root, assembly_dir = run_main(monkeypatch, tmp_path, runner)
    assert first_code == 0
    # rewrite the assembly manifest with different but still-canonical bytes
    manifest_path = assembly_dir / MEDIA_ASSEMBLY_MANIFEST_FILENAME
    document = json.loads(manifest_path.read_bytes())
    document["source"]["motion_time_sha256"] = "c" * 64
    manifest_path.write_bytes(dumps_canonical(document, "media assembly manifest"))
    capsys.readouterr()
    exit_code = executor.main(
        [
            "--assembly-dir",
            str(assembly_dir),
            "--captions-dir",
            str(tmp_path / "captions"),
            "--output-root",
            str(output_root),
            "--ffmpeg",
            str(tmp_path / "ffmpeg"),
            "--ffprobe",
            str(tmp_path / "ffprobe"),
        ],
        runner=runner,
    )
    assert exit_code == 1
    assert "assembles a different" in capsys.readouterr().err
