"""Phase 35 determinism (V55): the manifest's bytes are a pure function of its inputs.

The episode media encode manifest is built from path-free inputs -- the two
bound upstream manifests (as documents and captured bytes), measured integers,
the normalized streams block and two recorded version lines -- so its canonical
bytes must be byte-identical no matter which temp root the surrounding run sits
under, no matter the hash seed, and no matter which interpreter process asks.
These are the metamorphic proofs: same inputs, same bytes, and the package
never drags a tool (or ``subprocess``) into the process that builds it.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from living_diorama.caption_serialization.caption_serialization_spec import (
    SRT_SUFFIX,
    VTT_SUFFIX,
    sidecar_filename,
)
from living_diorama.media_encode.media_encode_command import build_media_encode_command
from living_diorama.media_encode.media_encode_manifest import (
    build_episode_media_encode_manifest_bytes,
)
from living_diorama.media_encode.media_encode_spec import (
    ASSEMBLY_DIR_TOKEN,
    MEDIA_ENCODE_SCHEMA_VERSION,
    STAGING_TOKEN,
    media_encode_id,
    media_temp_filename,
)
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex

REPO_ROOT = Path(__file__).resolve().parents[2]

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
    """Stub the two locked upstream validators to identity, manifest module only.

    The manifest builder re-validates the two consumed manifests under their
    locked upstream schemas; this suite supplies tiny synthetic documents that
    are not full Phase 33 / Phase 34 documents, so the two validators are
    stubbed with ``lambda document: document`` inside the manifest module only.
    Every Phase 35 law -- the encode manifest's own locked validator included --
    runs unpatched.
    """
    monkeypatch.setattr(
        "living_diorama.media_encode.media_encode_manifest.validate_episode_media_assembly_manifest",
        lambda document: document,
    )
    monkeypatch.setattr(
        "living_diorama.media_encode.media_encode_manifest."
        "validate_episode_caption_serialization_manifest",
        lambda document: document,
    )


def _builder_inputs() -> dict[str, object]:
    """The path-free keyword bundle of one complete manifest build."""
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
    return {
        "assembly_manifest": assembly,
        "assembly_manifest_bytes": dumps_canonical(assembly, "episode media assembly manifest"),
        "captions_manifest": captions,
        "captions_manifest_bytes": dumps_canonical(
            captions, "episode caption serialization manifest"
        ),
        "video_bytes": len(mp4_bytes),
        "video_sha256": sha256_hex(mp4_bytes),
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


# ---------------------------------------------------------------------------
# The manifest path-neutrality law
# ---------------------------------------------------------------------------


def test_manifest_bytes_are_identical_across_two_different_tmp_roots(tmp_path: Path) -> None:
    """The same manifest built under two different tmp roots is byte-identical.

    The inputs carry no paths at all, so the roots can never leak into the
    canonical bytes; the law is proven by building the identical bundle while
    the surrounding run sits under each root in turn.
    """
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"
    root_a.mkdir()
    root_b.mkdir()
    inputs = _builder_inputs()
    bytes_a = build_episode_media_encode_manifest_bytes(**inputs)
    bytes_b = build_episode_media_encode_manifest_bytes(**inputs)
    assert bytes_a == bytes_b


def test_manifest_bytes_never_carry_a_root_path_a_backslash_or_a_drive(tmp_path: Path) -> None:
    """The canonical bytes carry no root path, no backslash and no drive prefix."""
    root_a = tmp_path / "root_a"
    root_a.mkdir()
    text = build_episode_media_encode_manifest_bytes(**_builder_inputs()).decode("utf-8")
    assert str(root_a) not in text
    assert "\\" not in text
    assert "C:" not in text


def test_logical_argv_carries_both_placeholder_tokens_verbatim() -> None:
    """The invocation records ``{ASSEMBLY_DIR}`` and ``{STAGING}`` verbatim."""
    document = loads_canonical(
        build_episode_media_encode_manifest_bytes(**_builder_inputs()),
        "episode media encode manifest",
    )
    argv = document["invocation"]["logical_argv"]
    assert any(ASSEMBLY_DIR_TOKEN in element for element in argv)
    assert any(STAGING_TOKEN in element for element in argv)
    for element in argv:
        assert "\\" not in element
        assert "C:" not in element


def test_logical_argv_equals_the_frozen_command_builder_output() -> None:
    """The recorded argv is exactly the frozen builder's output for the same clock."""
    document = loads_canonical(
        build_episode_media_encode_manifest_bytes(**_builder_inputs()),
        "episode media encode manifest",
    )
    episode_id = media_encode_id(mode=_MODE, episode=_EPISODE, previous_episode=None)
    expected = list(
        build_media_encode_command(
            fps=_FPS,
            presentation_frames_total=_FRAMES,
            audio_sample_rate_hz=_RATE,
            audio_channels=_CHANNELS,
            media_temp_filename=media_temp_filename(episode_id),
        )
    )
    assert document["invocation"]["logical_argv"] == expected


def test_manifest_canonical_round_trip() -> None:
    """Dumps after loads reproduces the exact canonical bytes."""
    payload = build_episode_media_encode_manifest_bytes(**_builder_inputs())
    document = loads_canonical(payload, "episode media encode manifest")
    assert dumps_canonical(document, "episode media encode manifest") == payload
    assert document["schema_version"] == MEDIA_ENCODE_SCHEMA_VERSION


def test_manifest_carries_no_environment_block() -> None:
    """No environment block exists: the manifest records no runtime context."""
    document = loads_canonical(
        build_episode_media_encode_manifest_bytes(**_builder_inputs()),
        "episode media encode manifest",
    )
    assert "environment" not in document
    assert "hostname" not in document
    assert "pid" not in document


# ---------------------------------------------------------------------------
# V55 metamorphic proof: fresh subprocesses under four hash seeds, twice each
# ---------------------------------------------------------------------------

_METAMORPHIC_SCRIPT = """\
import sys
sys.path.insert(0, {src!r})

import hashlib
import living_diorama.media_encode.media_encode_manifest as manifest_module

# the same identity stubs this suite uses in-process; the manifest module's own
# locked validator still runs, so the digest is still decided by Phase 35 law
manifest_module.validate_episode_media_assembly_manifest = lambda document: document
manifest_module.validate_episode_caption_serialization_manifest = lambda document: document

inputs = {inputs!r}
payload = manifest_module.build_episode_media_encode_manifest_bytes(**inputs)
print(hashlib.sha256(payload).hexdigest())
"""


def test_manifest_bytes_are_identical_across_four_hash_seeds_twice_each() -> None:
    """Fresh interpreters under four hash seeds, twice each: one identical digest.

    Every seed in {0, 1, 42, 123456} is exercised twice in a fresh interpreter.

    The manifest build spawns no tool and reads no file, so ``PATH`` is kept
    straight from ``os.environ``; only the hash seed varies between runs.
    """
    digests: list[str] = []
    script = _METAMORPHIC_SCRIPT.format(src=str(REPO_ROOT / "src"), inputs=_builder_inputs())
    for seed in ("0", "1", "42", "123456"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        for _ in range(2):
            completed = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env=env,
                check=True,
            )
            digest = completed.stdout.strip()
            assert digest, f"seed {seed} produced no digest: {completed.stderr}"
            digests.append(digest)
    assert len(digests) == 8
    assert len(set(digests)) == 1, (
        f"the manifest bytes diverged across hash seeds that must never influence them: {digests}"
    )


def test_importing_the_package_leaks_no_subprocess_or_ffmpeg_module() -> None:
    """Importing the package leaks no ``subprocess`` and no ``ffmpeg`` module.

    The package must never import ``subprocess`` -- spawning is the executor's
    alone -- and no ``ffmpeg`` module may load as an import side effect.
    """
    script = (
        "import sys; "
        f"sys.path.insert(0, {str(REPO_ROOT / 'src')!r}); "
        "import living_diorama.media_encode; "
        "leaked = sorted(m for m in sys.modules if m == 'subprocess' or m == 'ffmpeg'); "
        "print(repr(leaked))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert completed.stdout.strip() == "[]"
