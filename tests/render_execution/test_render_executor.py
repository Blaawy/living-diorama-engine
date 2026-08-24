"""The Blender executor's logic, exercised against a fake Blender.

These tests own the parts that are hard to prove in a real render: what
happens when a render is interrupted, resumed, corrupted, or pointed at a
directory that belongs to something else. The fake writes real PNG bytes and
the executor's real structural checks run against them, so a truncated file
here fails for exactly the reason it would fail in production.

The real Blender suite proves the other half -- that a real render lands on the
real camera at the real frame -- and neither substitutes for the other.
"""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.render_execution.conftest import png_bytes

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "visual" / "blender" / "scripts" / "render_episode.py"


def _load_executor() -> Any:
    """Import the production executor module without Blender present."""
    spec = importlib.util.spec_from_file_location("render_episode_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


executor = _load_executor()


class FakeImageSettings:
    """The subset of Blender's image settings the profile writes."""

    def __init__(self) -> None:
        """Start from settings the profile must overwrite."""
        self.file_format = "PNG"
        self.color_mode = "RGBA"
        self.color_depth = "16"
        self.compression = 0


class FakeRender:
    """A scene's render settings, at Blender's factory defaults where it matters."""

    def __init__(self) -> None:
        """Start from Blender's defaults, not from the profile's values."""
        self.engine = "EEVEE"
        self.resolution_x = 1920
        self.resolution_y = 1080
        self.resolution_percentage = 50
        self.pixel_aspect_x = 1.0
        self.pixel_aspect_y = 1.0
        self.film_transparent = True
        self.use_motion_blur = True
        self.use_file_extension = True
        self.use_overwrite = False
        self.use_placeholder = True
        self.image_settings = FakeImageSettings()
        self.fps = 24
        self.fps_base = 1.0
        self.filepath = ""


class FakeCycles:
    """A scene's Cycles settings."""

    def __init__(self) -> None:
        """Start from settings no profile would choose."""
        self.device = "CPU"
        self.use_adaptive_sampling = False
        self.samples = 4096
        self.adaptive_threshold = 0.5
        self.use_denoising = False
        self.denoiser = "OPTIX"
        self.denoising_input_passes = "RGB"
        self.max_bounces = 32
        self.volume_bounces = 8
        self.transparent_max_bounces = 32
        self.seed = 7
        self.use_animated_seed = True


class FakeViewSettings:
    """Colour management, which Phase 23 verifies and never writes."""

    def __init__(self) -> None:
        """Start from the colour management the world build produces."""
        self.view_transform = "AgX"
        self.look = "AgX - Medium High Contrast"
        self.exposure = 1.25


class FakeCamera:
    """A named camera object."""

    def __init__(self, name: str) -> None:
        """Name the camera."""
        self.name = name


class FakeScene:
    """A scene that answers which camera is active at the current frame."""

    def __init__(self, cameras: dict[int, str]) -> None:
        """Hold the scene's settings and the camera each frame answers with."""
        self.render = FakeRender()
        self.cycles = FakeCycles()
        self.view_settings = FakeViewSettings()
        self._cameras = cameras
        self.frame_current = 1
        self.camera: FakeCamera | None = FakeCamera(cameras[1])

    def frame_set(self, frame: int) -> None:
        """Step the scene, moving the active camera as markers would."""
        self.frame_current = frame
        name = self._cameras.get(frame)
        self.camera = None if name is None else FakeCamera(name)


class FakeOpsRender:
    """The render operator, which writes a real PNG where it was pointed."""

    def __init__(self, scene: FakeScene, owner: "FakeBpy") -> None:
        """Bind the operator to its scene and its owner."""
        self._scene = scene
        self._owner = owner

    def render(self, write_still: bool = False) -> None:
        """Write the frame the executor asked for, or misbehave on demand."""
        assert write_still is True
        path = Path(self._scene.render.filepath)
        self._owner.rendered_frames.append(self._scene.frame_current)
        if self._owner.fail_at_frame == self._scene.frame_current:
            raise RuntimeError("the renderer died")
        payload = png_bytes(
            width=self._scene.render.resolution_x,
            height=self._scene.render.resolution_y,
            fill=self._scene.frame_current % 256,
        )
        if self._owner.truncate_at_frame == self._scene.frame_current:
            payload = payload[:-6]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        if self._owner.stub_at_frame == self._scene.frame_current:
            (path.parent / (path.stem + "0001.png")).write_bytes(payload)


class FakeOps:
    """``bpy.ops``."""

    def __init__(self, scene: FakeScene, owner: "FakeBpy") -> None:
        """Expose the render operator."""
        self.render = FakeOpsRender(scene, owner)


class FakeContext:
    """``bpy.context``."""

    def __init__(self, scene: FakeScene) -> None:
        """Expose the scene."""
        self.scene = scene


class FakeApp:
    """``bpy.app``."""

    version_string = "4.5.12 LTS (fake)"


class FakeBpy:
    """A Blender stand-in that renders real files and can be made to misbehave."""

    def __init__(self, cameras: dict[int, str]) -> None:
        """Assemble a Blender stand-in with no misbehaviour armed."""
        self.context = FakeContext(FakeScene(cameras))
        self.ops = FakeOps(self.context.scene, self)
        self.app = FakeApp()
        self.rendered_frames: list[int] = []
        self.fail_at_frame: int | None = None
        self.truncate_at_frame: int | None = None
        self.stub_at_frame: int | None = None


@pytest.fixture
def fake_bpy(render_plan: dict[str, Any]) -> FakeBpy:
    """A fake Blender whose camera answers match the plan, at plan resolution."""
    cameras = {entry["frame"]: entry["camera_anchor_id"] for entry in render_plan["frames"]}
    bpy = FakeBpy(cameras)
    owned = render_plan["profile"]["owned"]
    bpy.context.scene.render.resolution_x = owned["resolution_x"]
    bpy.context.scene.render.resolution_y = owned["resolution_y"]
    return bpy


@pytest.fixture(autouse=True)
def _no_device_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """The device probe belongs to real Blender; name a device and move on."""
    monkeypatch.setattr(executor, "render_device", lambda bpy_module: "FAKE_DEVICE")


@pytest.fixture
def small_plan(render_plan: dict[str, Any]) -> dict[str, Any]:
    """The canonical plan, unchanged. Renders here are cheap: the fake is instant."""
    return render_plan


# --------------------------------------------------------------- the profile


def test_the_profile_is_applied_to_the_scene(fake_bpy: FakeBpy, small_plan: dict[str, Any]) -> None:
    """Nothing important is inherited from whatever the scene happened to hold."""
    executor.apply_render_profile(fake_bpy, small_plan["profile"])
    render = fake_bpy.context.scene.render
    cycles = fake_bpy.context.scene.cycles
    assert render.engine == "CYCLES"
    assert (render.resolution_x, render.resolution_y) == (1280, 720)
    assert render.resolution_percentage == 100
    assert render.film_transparent is False
    assert render.use_motion_blur is False
    assert render.image_settings.file_format == "PNG"
    assert render.image_settings.color_mode == "RGB"
    assert render.image_settings.color_depth == "8"
    assert cycles.samples == 96
    assert cycles.seed == 0
    assert cycles.use_animated_seed is False


def test_a_scene_whose_colour_management_drifted_is_refused_not_overridden(
    fake_bpy: FakeBpy, small_plan: dict[str, Any]
) -> None:
    """Overriding a locked layer's look from inside a render would hide the drift."""
    fake_bpy.context.scene.view_settings.look = "AgX - Punchy"
    with pytest.raises(RuntimeError, match="never overrides a locked layer"):
        executor.apply_render_profile(fake_bpy, small_plan["profile"])
    assert fake_bpy.context.scene.view_settings.look == "AgX - Punchy"


def test_a_scene_on_the_wrong_clock_is_refused(
    fake_bpy: FakeBpy, small_plan: dict[str, Any]
) -> None:
    """A 60 fps scene would play the locked episode in a third of its runtime."""
    fake_bpy.context.scene.render.fps = 60
    with pytest.raises(RuntimeError, match="fps"):
        executor.apply_render_profile(fake_bpy, small_plan["profile"])


def test_a_plan_carrying_a_foreign_profile_is_refused(small_plan: dict[str, Any]) -> None:
    """The absolute pin: the profile is never taken from the document being run."""
    forged = json.loads(json.dumps(small_plan))
    forged["profile"]["owned"]["cycles_samples"] = 2048
    forged["source"]["render_profile_sha256"] = executor.sha256_hex(
        executor.canonical_bytes(forged["profile"])
    )
    # Both pins fire on a forged pair: the source binding is checked against the
    # approved digest before the profile body is even hashed, so whichever
    # speaks first, the plan is refused for naming a profile this build does
    # not render under.
    with pytest.raises(executor.PlanRefused, match="approved profile digest|this build renders"):
        executor.require_render_plan(forged)


def test_a_document_that_is_not_a_render_plan_is_refused(small_plan: dict[str, Any]) -> None:
    """A shot plan handed to the renderer is refused by format."""
    forged = json.loads(json.dumps(small_plan))
    forged["format"] = "living_diorama_shot_direction_plan"
    with pytest.raises(executor.PlanRefused, match="expected a"):
        executor.require_render_plan(forged)


# ----------------------------------------------------------------- rendering


def test_a_full_render_produces_every_planned_frame(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """The whole episode, one file per planned frame, nothing else."""
    result = executor.execute_render(fake_bpy, plan=small_plan, render_dir=tmp_path / "render")
    assert len(result["frames"]) == 193
    assert len(result["rendered"]) == 193
    frames_dir = tmp_path / "render" / "frames"
    witness_dir = tmp_path / "render" / "witness"
    assert len(list(frames_dir.iterdir())) == 192
    assert [entry.name for entry in witness_dir.iterdir()] == ["frame_0193.png"]
    assert (frames_dir / "frame_0001.png").is_file()
    assert (frames_dir / "frame_0192.png").is_file()


def test_the_partial_directory_does_not_survive_a_finished_render(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Nothing is left behind that a later run could mistake for a frame."""
    executor.execute_render(fake_bpy, plan=small_plan, render_dir=tmp_path / "render")
    assert not (tmp_path / "render" / ".partial").exists()


def test_a_frame_whose_camera_is_not_the_directed_one_stops_the_render(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Phase 23 renders the directed camera or nothing."""
    fake_bpy.context.scene._cameras[60] = "CAM_P16_URBAN"
    with pytest.raises(RuntimeError, match="directs"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=tmp_path / "render")


def test_a_frame_with_no_active_camera_stops_the_render(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """A scene with no camera would photograph nothing at all."""
    del fake_bpy.context.scene._cameras[60]
    with pytest.raises(RuntimeError, match="no active camera"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=tmp_path / "render")


def test_a_frame_rendered_at_the_wrong_size_is_refused(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The profile decides the frame size; a file that disagrees is not it.

    V3 caught this *after* publishing the frame under its final name. It is now
    caught before ``os.replace`` runs, so the wrong-sized file never occupies
    the path a reader would trust -- which is what the assertion below checks.
    """
    original = executor.png_facts

    def _wrong_size(path: Path) -> dict:
        facts = original(path)
        return {**facts, "width": 640}

    monkeypatch.setattr(executor, "png_facts", _wrong_size)
    render_dir = tmp_path / "render"
    with pytest.raises(executor.FrameRefused, match="requires 1280x720"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)
    assert not (render_dir / "frames" / "frame_0001.png").exists()


def test_a_truncated_frame_is_caught_before_it_is_published(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """The failure a digest alone would never notice."""
    fake_bpy.truncate_at_frame = 3
    with pytest.raises(ValueError, match="truncated"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=tmp_path / "render")
    assert not (tmp_path / "render" / "frames" / "frame_0003.png").exists()


def test_a_numbered_stub_beside_the_frame_stops_the_render(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Blender's own filename suffixing must never publish the wrong file."""
    fake_bpy.stub_at_frame = 2
    with pytest.raises(RuntimeError, match="produced 2 files"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=tmp_path / "render")


# -------------------------------------------------------------------- resume


def test_an_interrupted_render_resumes_where_it_stopped(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """A crash after 120 frames does not throw away 120 verified frames."""
    render_dir = tmp_path / "render"
    first = executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=120)
    assert len(first["rendered"]) == 120

    fake_bpy.rendered_frames.clear()
    second = executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)
    assert len(second["skipped"]) == 120
    assert len(second["rendered"]) == 73
    assert min(fake_bpy.rendered_frames) == 121
    assert len(second["frames"]) == 193


def test_a_resumed_frame_is_re_verified_not_merely_counted(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Existence is never evidence: a changed frame is refused."""
    render_dir = tmp_path / "render"
    executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=5)
    (render_dir / "frames" / "frame_0003.png").write_bytes(
        png_bytes(width=1280, height=720, fill=9)
    )
    with pytest.raises(RuntimeError, match="no longer matches"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)


def test_a_corrupted_existing_frame_is_refused_on_resume(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """A half-written leftover is not quietly re-rendered over."""
    render_dir = tmp_path / "render"
    executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=5)
    target = render_dir / "frames" / "frame_0002.png"
    target.write_bytes(target.read_bytes()[:-8])
    with pytest.raises(ValueError, match="truncated"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)


def test_a_render_directory_belonging_to_another_plan_is_refused(
    fake_bpy: FakeBpy,
    small_plan: dict[str, Any],
    baseline_render_plan: dict[str, Any],
    tmp_path: Path,
) -> None:
    """Two renders never share a directory, and nothing is deleted to make room."""
    render_dir = tmp_path / "render"
    executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=2)
    cameras = {
        entry["frame"]: entry["camera_anchor_id"] for entry in baseline_render_plan["frames"]
    }
    other = FakeBpy(cameras)
    other.context.scene.render.resolution_x = 1280
    other.context.scene.render.resolution_y = 720
    with pytest.raises(RuntimeError, match="different plan"):
        executor.execute_render(other, plan=baseline_render_plan, render_dir=render_dir)


def test_an_unaccounted_file_in_the_frames_directory_is_refused(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Refused rather than deleted: this phase never removes a file it did not make."""
    render_dir = tmp_path / "render"
    executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=2)
    stray = render_dir / "frames" / "frame_0500.png"
    stray.write_bytes(png_bytes())
    with pytest.raises(RuntimeError, match="not a frame this plan accounts for"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)
    assert stray.is_file()


def _complete_render(bpy: FakeBpy, plan: dict[str, Any], render_dir: Path) -> None:
    """Render every frame and write the truthful manifest beside them."""
    result = executor.execute_render(bpy, plan=plan, render_dir=render_dir)
    manifest = executor.assemble_manifest(
        plan,
        executor.sha256_hex(executor.canonical_bytes(plan)),
        result["frames"],
        result["environment"],
        0.0142,
    )
    executor.write_json_atomically(render_dir / "episode_render_manifest.json", manifest)


def test_a_completed_render_is_verified_rather_than_redone(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Re-running a finished render overwrites nothing and re-renders nothing."""
    render_dir = tmp_path / "render"
    _complete_render(fake_bpy, small_plan, render_dir)

    fake_bpy.rendered_frames.clear()
    again = executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)
    assert again["already_complete"] is True
    assert again["rendered"] == []
    assert fake_bpy.rendered_frames == []


def test_a_manifest_that_contradicts_the_checkpoint_is_refused(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """A forged manifest cannot talk the executor into calling a render finished.

    The manifest is not a second opinion the executor defers to: where both
    records exist they must agree, so a directory that contradicts itself stops
    the run instead of certifying it.
    """
    render_dir = tmp_path / "render"
    _complete_render(fake_bpy, small_plan, render_dir)
    manifest_path = render_dir / "episode_render_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["frames"][0]["sha256"] = "0" * 64
    executor.write_json_atomically(manifest_path, manifest)
    with pytest.raises(RuntimeError, match="contradicts itself"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)


def test_a_frame_nothing_vouches_for_is_never_overwritten(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """A file of unknown provenance under a planned name stops the render.

    Without this, a directory holding somebody else's images at exactly the
    names this plan uses would be quietly overwritten -- which is the one thing
    a phase that never deletes what it did not make must not do.
    """
    render_dir = tmp_path / "render"
    (render_dir / "frames").mkdir(parents=True)
    stranger = render_dir / "frames" / "frame_0001.png"
    stranger.write_bytes(png_bytes(width=1280, height=720, fill=7))
    with pytest.raises(RuntimeError, match="provenance"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)
    assert stranger.is_file()


def test_a_complete_render_whose_checkpoint_vanished_is_still_not_overwritten(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """The manifest alone is enough to account for the frames it recorded."""
    render_dir = tmp_path / "render"
    _complete_render(fake_bpy, small_plan, render_dir)
    (render_dir / "render_checkpoint.json").unlink()

    fake_bpy.rendered_frames.clear()
    again = executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)
    assert again["already_complete"] is True
    assert fake_bpy.rendered_frames == []


def test_the_checkpoint_records_the_plan_and_profile_it_belongs_to(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Resume state that did not name its plan would be resumable into anything."""
    render_dir = tmp_path / "render"
    executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=3)
    checkpoint = json.loads((render_dir / "render_checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["render_plan_sha256"] == executor.sha256_hex(
        executor.canonical_bytes(small_plan)
    )
    assert checkpoint["render_profile_sha256"] == executor.RENDER_PROFILE_SHA256
    assert sorted(checkpoint["frames"]) == ["1", "2", "3"]


def test_a_checkpoint_from_another_profile_is_refused(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Frames from two different profiles must never be mixed into one episode."""
    render_dir = tmp_path / "render"
    executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=2)
    path = render_dir / "render_checkpoint.json"
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint["render_profile_sha256"] = "0" * 64
    executor.write_json_atomically(path, checkpoint)
    with pytest.raises(RuntimeError, match="different profile"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)


def test_a_render_that_dies_writes_no_manifest(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """No false completeness survives a crash."""
    render_dir = tmp_path / "render"
    fake_bpy.fail_at_frame = 10
    with pytest.raises(RuntimeError, match="the renderer died"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)
    assert not (render_dir / "episode_render_manifest.json").exists()
    assert (render_dir / "render_checkpoint.json").is_file()


# ------------------------------------------------------------ PNG structure


def test_a_valid_png_reports_its_own_dimensions(tmp_path: Path) -> None:
    """The structural read is what makes a frame's size a fact."""
    path = tmp_path / "frame.png"
    path.write_bytes(png_bytes(width=7, height=5))
    facts = executor.png_facts(path)
    assert (facts["width"], facts["height"]) == (7, 5)
    assert facts["bytes"] == len(path.read_bytes())


def test_a_file_that_is_not_a_png_is_refused(tmp_path: Path) -> None:
    """Not everything with a .png name is one."""
    path = tmp_path / "frame.png"
    path.write_bytes(b"this is not a png")
    with pytest.raises(ValueError, match="PNG signature"):
        executor.png_facts(path)


def test_a_png_with_a_corrupt_chunk_is_refused(tmp_path: Path) -> None:
    """Bit rot inside a chunk is caught by its own CRC."""
    payload = bytearray(png_bytes(width=8, height=8))
    payload[30] ^= 0xFF
    path = tmp_path / "frame.png"
    path.write_bytes(bytes(payload))
    with pytest.raises(ValueError, match="corrupt"):
        executor.png_facts(path)


def test_a_png_without_an_end_chunk_is_refused(tmp_path: Path) -> None:
    """A file that never ended is a file that was still being written."""
    payload = png_bytes(width=8, height=8)
    path = tmp_path / "frame.png"
    path.write_bytes(payload[:-12])
    with pytest.raises(ValueError, match="truncated|IEND"):
        executor.png_facts(path)


# -------------------------------------------------- executor / engine agreement


def test_the_executors_manifest_matches_the_engines_own_builder(
    small_plan: dict[str, Any],
) -> None:
    """The two implementations must never drift apart.

    The Blender side assembles the manifest because it is the side that
    watched the frames land; the engine owns the contract. This test is what
    keeps the mechanical copy honest.
    """
    from living_diorama.persistence.json_codec import dumps_canonical
    from living_diorama.persistence.schema.state_hash import sha256_hex
    from living_diorama.render_execution import build_episode_render_manifest_document

    results = {
        entry["frame"]: {
            "bytes": 1000 + index,
            "sha256": f"{index:064x}",
            "image_sha256": f"{index + 500:064x}",
        }
        for index, entry in enumerate(small_plan["frames"])
    }
    environment = {"blender_version": "4.5.12", "engine": "CYCLES", "device": "OPTIX"}

    from_engine = build_episode_render_manifest_document(
        render_plan=small_plan,
        results=results,
        environment=environment,
        witness_difference=0.0142,
    )
    from_executor = executor.assemble_manifest(
        small_plan,
        sha256_hex(dumps_canonical(small_plan, "episode render plan")),
        results,
        environment,
        0.0142,
    )
    assert from_executor == from_engine


def test_a_witness_beyond_tolerance_is_not_a_complete_render(
    small_plan: dict[str, Any],
) -> None:
    """The closure gate, in the document the process exit code follows.

    V1 wrote a manifest and returned success even when the boundary witness had
    drifted outside tolerance -- the independent audit would have caught it
    later, but the renderer had already announced a finished episode. Now the
    verdict is part of ``complete``, so the document and the exit code cannot
    tell different stories.
    """
    results = {
        entry["frame"]: {
            "bytes": 1000 + index,
            "sha256": f"{index:064x}",
            "image_sha256": f"{index + 500:064x}",
        }
        for index, entry in enumerate(small_plan["frames"])
    }
    plan_digest = executor.sha256_hex(executor.canonical_bytes(small_plan))
    environment = {"blender_version": "x", "engine": "CYCLES", "device": "FAKE"}

    inside = executor.assemble_manifest(small_plan, plan_digest, results, environment, 0.05)
    assert inside["completeness"]["witness_within_tolerance"] is True
    assert inside["completeness"]["complete"] is True

    outside = executor.assemble_manifest(small_plan, plan_digest, results, environment, 9.5)
    assert outside["completeness"]["witness_within_tolerance"] is False
    assert outside["completeness"]["complete"] is False, (
        "a render whose boundary drifted is not a complete episode, however many files it made"
    )


def test_the_engine_agrees_that_a_bad_witness_is_incomplete(
    small_plan: dict[str, Any],
) -> None:
    """Both manifest implementations reach the same verdict on the same numbers."""
    from living_diorama.render_execution import build_episode_render_manifest_document

    results = {
        entry["frame"]: {
            "bytes": 1000 + index,
            "sha256": f"{index:064x}",
            "image_sha256": f"{index + 500:064x}",
        }
        for index, entry in enumerate(small_plan["frames"])
    }
    from_engine = build_episode_render_manifest_document(
        render_plan=small_plan,
        results=results,
        environment={"blender_version": "x", "engine": "CYCLES", "device": "FAKE"},
        witness_difference=9.5,
    )
    assert from_engine["completeness"]["complete"] is False


# --------------------------------------------------------------------------
# One render directory, one execution environment
# --------------------------------------------------------------------------
#
# The manifest names a single Blender version, engine and device for the whole
# render. That sentence is only true if every frame in the directory came from
# that one environment -- so a partial render is resumable by the environment
# that started it and by nothing else. An independent reviewer showed V3 would
# happily resume another machine's frames and then sign the result with this
# machine's name.


def _switch_environment(
    monkeypatch: pytest.MonkeyPatch, bpy: FakeBpy, *, version: str, device: str
) -> None:
    """Make the next invocation look like it is running on a different machine."""
    monkeypatch.setattr(type(bpy.app), "version_string", version)
    monkeypatch.setattr(executor, "render_device", lambda bpy_module: device)


def _complete_render(fake_bpy: FakeBpy, plan: dict[str, Any], render_dir: Path) -> dict[str, Any]:
    """Render an episode to completion and write its manifest, as production does."""
    result = executor.execute_render(fake_bpy, plan=plan, render_dir=render_dir)
    digest = executor.sha256_hex(executor.canonical_bytes(plan))
    manifest = executor.assemble_manifest(
        plan, digest, result["frames"], result["environment"], 0.08
    )
    executor.write_json_atomically(render_dir / "episode_render_manifest.json", manifest)
    return manifest


def test_a_partial_render_is_not_resumed_by_a_different_environment(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduction A: the reviewer's mixed-environment episode, refused.

    Run A renders part of the episode. Run B, on another Blender and another
    device, would reuse A's frames, render the rest itself, and record only its
    own environment -- attributing A's pixels to B. There is no honest manifest
    for that directory, so the resume is refused instead.
    """
    render_dir = tmp_path / "render"
    executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=4)
    before = sorted((render_dir / "frames").iterdir())
    assert before

    _switch_environment(monkeypatch, fake_bpy, version="4.6.0 LTS (other)", device="OTHER_DEVICE")
    with pytest.raises(executor.RenderDirectoryRefused, match="one environment"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)

    # Refused before anything was mixed: not one new frame, not one changed one.
    assert sorted((render_dir / "frames").iterdir()) == before


def test_a_partial_render_resumes_under_the_same_environment(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Reproduction B: the control. Resume still works where it is truthful."""
    render_dir = tmp_path / "render"
    first = executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=4)
    assert len(first["rendered"]) == 4

    second = executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)
    assert second["skipped"][:4] == first["rendered"]
    assert len(second["frames"]) == len(small_plan["frames"])
    assert second["environment"] == first["environment"]


def test_a_complete_render_is_not_reattributed_by_a_later_run(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduction C: re-running a finished render must not rename its machine.

    Zero frames are produced, so nothing is mixed and the run need not be
    refused -- but the manifest already on disk describes pixels made
    elsewhere, and V3 rewrote it with the current environment anyway.
    """
    render_dir = tmp_path / "render"
    manifest = _complete_render(fake_bpy, small_plan, render_dir)
    original = dict(manifest["environment"])
    on_disk = (render_dir / "episode_render_manifest.json").read_bytes()

    _switch_environment(monkeypatch, fake_bpy, version="9.9.9 LTS (new)", device="NEW_DEVICE")
    result = executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)

    assert result["already_complete"] is True
    assert result["rendered"] == []
    assert result["environment"] == original
    assert result["environment"]["device"] != "NEW_DEVICE"
    # And the record itself is untouched, byte for byte.
    assert (render_dir / "episode_render_manifest.json").read_bytes() == on_disk


def test_a_stale_manifest_is_refused_rather_than_repaired(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Reproduction D: right plan digest, right frame hashes, wrong provenance.

    V3 called this directory complete because it checked the plan digest and the
    frame digests and never compared the manifest's own claims to the plan. The
    later path then overwrote the stale document with a freshly assembled one --
    repair, in a phase whose rule is refuse, never repair.
    """
    render_dir = tmp_path / "render"
    manifest = _complete_render(fake_bpy, small_plan, render_dir)
    manifest["source"]["story_plan_sha256"] = "0" * 64
    path = render_dir / "episode_render_manifest.json"
    executor.write_json_atomically(path, manifest)
    stale = path.read_bytes()

    with pytest.raises(executor.RenderDirectoryRefused, match="never rewritten"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)
    assert path.read_bytes() == stale


def test_a_manifest_with_an_altered_environment_is_not_silently_rewritten(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Reproduction E: an edited environment is refused, never quietly corrected."""
    render_dir = tmp_path / "render"
    manifest = _complete_render(fake_bpy, small_plan, render_dir)
    manifest["environment"]["device"] = "SOMETHING_ELSE"
    path = render_dir / "episode_render_manifest.json"
    executor.write_json_atomically(path, manifest)
    edited = path.read_bytes()

    with pytest.raises(executor.RenderDirectoryRefused, match="environment"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)
    assert path.read_bytes() == edited


def test_a_manifest_and_checkpoint_that_disagree_about_the_environment_are_refused(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Reproduction F: one directory cannot have been rendered by two machines."""
    render_dir = tmp_path / "render"
    _complete_render(fake_bpy, small_plan, render_dir)
    checkpoint_path = render_dir / "render_checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["environment"]["blender_version"] = "4.6.0 LTS (other)"
    executor.write_json_atomically(checkpoint_path, checkpoint)

    with pytest.raises(executor.RenderDirectoryRefused, match="disagree about the execution"):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)


# ------------------------------------------------------- the checkpoint itself


CHECKPOINT_ATTACKS = {
    "an extra key": lambda c: c.update(surprise=1),
    "a missing key": lambda c: c.pop("environment"),
    "frames as a list": lambda c: c.update(frames=[]),
    "a frame the plan never had": lambda c: c["frames"].update({"9999": c["frames"]["1"]}),
    "a non-numeric frame key": lambda c: c["frames"].update({"one": c["frames"]["1"]}),
    "a frame record missing a digest": lambda c: c["frames"]["1"].pop("image_sha256"),
    "a frame record with an extra key": lambda c: c["frames"]["1"].update(extra=True),
    "a zero byte count": lambda c: c["frames"]["1"].update(bytes=0),
    "a byte count that is a bool": lambda c: c["frames"]["1"].update(bytes=True),
    "a digest that is not one": lambda c: c["frames"]["1"].update(sha256="nope"),
    "an environment missing a key": lambda c: c["environment"].pop("device"),
    "an environment with an extra key": lambda c: c["environment"].update(gpu="x"),
    "a blank environment value": lambda c: c["environment"].update(device="   "),
    "an environment value that is not a string": lambda c: c["environment"].update(device=7),
}
"""Every malformed checkpoint V3 would have believed.

V3 read this file with ``json.loads`` and used whatever came back. A checkpoint
is what lets a resume *skip* rendering a frame, so a checkpoint nobody validated
is a list of frames nobody has to produce.
"""


@pytest.mark.parametrize("name", sorted(CHECKPOINT_ATTACKS))
def test_a_malformed_checkpoint_is_refused(
    name: str, fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """A checkpoint vouches for work not done; it is validated before it is believed."""
    render_dir = tmp_path / "render"
    executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=3)
    path = render_dir / "render_checkpoint.json"
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    CHECKPOINT_ATTACKS[name](checkpoint)
    executor.write_json_atomically(path, checkpoint)

    with pytest.raises(executor.RenderDirectoryRefused):
        executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)


def test_a_well_formed_checkpoint_is_accepted(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """The control for the attacks above: the real checkpoint validates."""
    render_dir = tmp_path / "render"
    executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=3)
    checkpoint = json.loads((render_dir / "render_checkpoint.json").read_text(encoding="utf-8"))
    digest = executor.sha256_hex(executor.canonical_bytes(small_plan))
    validated = executor.require_valid_checkpoint(checkpoint, small_plan, digest)
    assert sorted(validated["frames"]) == [1, 2, 3]
    assert set(validated["environment"]) == set(executor.ENVIRONMENT_KEYS)


def test_an_unreasonably_long_frame_key_is_refused_not_crashed(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """The executor's own refusal, not a bare ValueError escaping ``int()``.

    A digit string past CPython's int/str conversion limit (4300 digits,
    since 3.11) makes ``int(key)`` itself raise ``ValueError`` -- which must
    still surface as this module's ``RenderDirectoryRefused``, exactly like
    every other illegal frame-key spelling, not as an unrelated exception
    type escaping uncaught.
    """
    render_dir = tmp_path / "render"
    executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=3)
    checkpoint = json.loads((render_dir / "render_checkpoint.json").read_text(encoding="utf-8"))
    huge = "1" * 4301
    checkpoint["frames"][huge] = checkpoint["frames"].pop("1")
    digest = executor.sha256_hex(executor.canonical_bytes(small_plan))
    with pytest.raises(executor.RenderDirectoryRefused, match="frame"):
        executor.require_valid_checkpoint(checkpoint, small_plan, digest)


# --------------------------------------------------------------------------
# Checkpoint, manifest and file must agree on every frame result
# --------------------------------------------------------------------------
#
# A finished directory holds three records of the same facts about each frame.
# V4 compared the checkpoint and the manifest on `sha256` alone and then let the
# checkpoint's record stand in for the manifest's, so a manifest could carry a
# correct digest beside a wrong byte count or a wrong image digest, establish
# completeness, and never be compared to the file it described.


def _complete_with_records(
    fake_bpy: FakeBpy, plan: dict[str, Any], render_dir: Path
) -> tuple[Path, Path]:
    """Render to completion and return the checkpoint and manifest paths."""
    result = executor.execute_render(fake_bpy, plan=plan, render_dir=render_dir)
    digest = executor.sha256_hex(executor.canonical_bytes(plan))
    manifest = executor.assemble_manifest(
        plan, digest, result["frames"], result["environment"], 0.08
    )
    manifest_path = render_dir / "episode_render_manifest.json"
    executor.write_json_atomically(manifest_path, manifest)
    return render_dir / "render_checkpoint.json", manifest_path


def _survey(fake_bpy: FakeBpy, plan: dict[str, Any], render_dir: Path) -> dict[str, Any]:
    """Run the production survey with the environment execute_render would use."""
    environment = {
        "blender_version": fake_bpy.app.version_string,
        "engine": plan["profile"]["owned"]["engine"],
        "device": "FAKE_DEVICE",
    }
    digest = executor.sha256_hex(executor.canonical_bytes(plan))
    return executor.survey_render_directory(render_dir, plan, digest, environment)


RESULT_CONTRADICTIONS = {
    "manifest bytes": ("manifest", lambda d: d["frames"][0].update(bytes=999_999)),
    "manifest image_sha256": ("manifest", lambda d: d["frames"][0].update(image_sha256="0" * 64)),
    "checkpoint bytes": ("checkpoint", lambda d: d["frames"]["1"].update(bytes=999_999)),
    "checkpoint image_sha256": (
        "checkpoint",
        lambda d: d["frames"]["1"].update(image_sha256="0" * 64),
    ),
}
"""One record edited in one field, with `sha256` left correct throughout.

Leaving the digest alone is the point: it is the field V4 compared, so these are
exactly the contradictions that slipped past it.
"""


@pytest.mark.parametrize("name", sorted(RESULT_CONTRADICTIONS))
def test_a_record_that_contradicts_the_file_is_refused(
    name: str, fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Reproductions A-D: every result field, from either record."""
    render_dir = tmp_path / "render"
    checkpoint_path, manifest_path = _complete_with_records(fake_bpy, small_plan, render_dir)
    which, mutate = RESULT_CONTRADICTIONS[name]
    path = checkpoint_path if which == "checkpoint" else manifest_path
    document = json.loads(path.read_text(encoding="utf-8"))
    mutate(document)
    executor.write_json_atomically(path, document)
    before = path.read_bytes()

    with pytest.raises((executor.RenderDirectoryRefused, RuntimeError)):
        _survey(fake_bpy, small_plan, render_dir)
    # Refused, not corrected.
    assert path.read_bytes() == before


def test_a_truthful_checkpoint_and_manifest_together_are_accepted(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Reproduction E: the control. Without it every refusal above is vacuous."""
    render_dir = tmp_path / "render"
    _complete_with_records(fake_bpy, small_plan, render_dir)
    survey = _survey(fake_bpy, small_plan, render_dir)
    assert survey["complete"] is True
    assert len(survey["valid_frames"]) == len(small_plan["frames"])


def test_a_manifest_alone_is_proved_directly_against_the_files(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Reproduction F: with no checkpoint, the manifest answers for every frame itself."""
    render_dir = tmp_path / "render"
    checkpoint_path, manifest_path = _complete_with_records(fake_bpy, small_plan, render_dir)
    checkpoint_path.unlink()
    assert _survey(fake_bpy, small_plan, render_dir)["complete"] is True

    # And it is genuinely being checked, not merely trusted for being alone.
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["frames"][0]["bytes"] = 999_999
    executor.write_json_atomically(manifest_path, manifest)
    with pytest.raises((executor.RenderDirectoryRefused, RuntimeError)):
        _survey(fake_bpy, small_plan, render_dir)


def test_a_partial_render_without_a_manifest_still_resumes(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """Reproduction G: ordinary resume is untouched by any of this."""
    render_dir = tmp_path / "render"
    first = executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=5)
    assert not (render_dir / "episode_render_manifest.json").exists()
    second = executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir)
    assert second["skipped"][:5] == first["rendered"]
    assert len(second["frames"]) == len(small_plan["frames"])


# --------------------------------------------------------------------------
# The render directory's top level
# --------------------------------------------------------------------------


ROOT_INTRUDERS = {
    "a foreign file": lambda d: (d / "evil.txt").write_text("dropped here", encoding="utf-8"),
    "a foreign directory": lambda d: (d / "foreign").mkdir(),
    "a frame at the root": lambda d: (d / "frame_0001.png").write_bytes(png_bytes(fill=3)),
    "an unknown json": lambda d: (d / "unknown.json").write_bytes(b"{}\n"),
}
"""Things that are not Phase 23's, dropped into a finished render directory.

The independent verifier already refused every one of these. The production
survey saw none of them, so the phase had two different definitions of a valid
finished render.
"""


@pytest.mark.parametrize("name", sorted(ROOT_INTRUDERS))
def test_production_refuses_an_unknown_root_entry(
    name: str, fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """And the independent audit must reach the same verdict on the same directory."""
    render_dir = tmp_path / "render"
    _complete_with_records(fake_bpy, small_plan, render_dir)
    assert _survey(fake_bpy, small_plan, render_dir)["complete"] is True

    ROOT_INTRUDERS[name](render_dir)
    with pytest.raises(executor.RenderDirectoryRefused, match="not something Phase 23 put here"):
        _survey(fake_bpy, small_plan, render_dir)

    from living_diorama.cli import verify_render

    assert verify_render.audit_render_directory(render_dir) != []
    # Nothing foreign was removed to reach that verdict.
    assert any(not path.name.startswith("episode") for path in render_dir.iterdir())


def test_a_surviving_partial_directory_stops_a_render_being_called_finished(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """This phase's own litter means the run that made it did not reach the end."""
    render_dir = tmp_path / "render"
    _complete_with_records(fake_bpy, small_plan, render_dir)
    (render_dir / ".partial").mkdir()
    with pytest.raises(executor.RenderDirectoryRefused, match="did not finish"):
        _survey(fake_bpy, small_plan, render_dir)


def test_a_leftover_writing_temporary_is_owned_not_foreign(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """A `.writing` file is this phase's own crash debris, and says so.

    It still stops the directory being called finished -- but the refusal names
    it as an interrupted run rather than as something foreign, because the
    difference decides whether a human should look for an intruder.
    """
    render_dir = tmp_path / "render"
    _complete_with_records(fake_bpy, small_plan, render_dir)
    (render_dir / "episode_render_manifest.json.writing").write_bytes(b"{}")
    with pytest.raises(executor.RenderDirectoryRefused, match="did not finish"):
        _survey(fake_bpy, small_plan, render_dir)


def test_the_two_sides_agree_on_what_a_render_directory_may_hold() -> None:
    """The executor restates the engine's set, and the restatement is pinned."""
    from living_diorama.render_execution.render_execution_spec import (
        RENDER_DIRECTORY_ENTRIES,
        WRITING_SUFFIX,
        classify_render_directory_entry,
    )

    assert executor.RENDER_DIRECTORY_ENTRIES == RENDER_DIRECTORY_ENTRIES
    assert executor.WRITING_SUFFIX == WRITING_SUFFIX
    for name in [*RENDER_DIRECTORY_ENTRIES, ".partial", "x.writing", "evil.txt", "foreign"]:
        assert executor.classify_render_directory_entry(name) == classify_render_directory_entry(
            name
        ), name


# --------------------------------------------------------------------------
# What a second-wave attacker found in the V5 code itself
# --------------------------------------------------------------------------


MALFORMED_RECORDS = {
    "truncated JSON": b"{ not json",
    "a repeated key": b'{"render_plan_sha256": 1, "render_plan_sha256": 2}',
    "a JSON array": b"[]\n",
    "not UTF-8": b"\xff\xfe\x00",
}
"""Records this phase cannot read at all.

These are correct refusals in V4 too -- but of the wrong *kind*. Everything the
survey rejects is a statement about the directory, and these arrived as raw
``json.JSONDecodeError``, which a caller catching ``RenderDirectoryRefused``
would have missed entirely.
"""


@pytest.mark.parametrize("name", sorted(MALFORMED_RECORDS))
def test_a_malformed_record_is_a_directory_refusal(
    name: str, fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """The survey's documented raise contract is the one it actually keeps."""
    render_dir = tmp_path / "render"
    executor.execute_render(fake_bpy, plan=small_plan, render_dir=render_dir, limit=3)
    (render_dir / "render_checkpoint.json").write_bytes(MALFORMED_RECORDS[name])
    with pytest.raises(executor.RenderDirectoryRefused, match="not a readable"):
        _survey(fake_bpy, small_plan, render_dir)


DIRECTORY_ENTRY_KINDS = {
    ("episode_render_manifest.json.writing", False): "partial",
    ("episode_render_plan.json.writing", False): "partial",
    ("render_checkpoint.json.writing", False): "partial",
    (".partial", True): "partial",
    (".partial", False): "foreign",
    ("evil.writing", False): "foreign",
    ("x.writing", True): "foreign",
    ("evil.txt", False): "foreign",
    ("frames", True): "owned",
    ("episode_render_plan.json", False): "owned",
}
"""Every entry kind, and what it is.

The suffix alone was not enough. A file called ``evil.writing`` is not this
phase's crash debris and neither is a *directory* called ``x.writing``; both
were being waved through as owned litter. A ``.writing`` entry is ours only when
it is a file whose remaining name is a document this phase writes, and
``.partial`` is ours only when it is a directory.
"""


@pytest.mark.parametrize(("entry", "expected"), sorted(DIRECTORY_ENTRY_KINDS.items()))
def test_directory_entries_are_classified_by_shape_not_only_by_name(
    entry: tuple[str, bool], expected: str
) -> None:
    """And the engine and the executor answer identically."""
    from living_diorama.render_execution.render_execution_spec import (
        classify_render_directory_entry as engine_classify,
    )

    name, is_directory = entry
    assert executor.classify_render_directory_entry(name, is_directory) == expected
    assert engine_classify(name, is_directory=is_directory) == expected


def test_a_foreign_file_wearing_the_writing_suffix_is_refused(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """`evil.writing` is not this phase's litter, and the refusal says so."""
    render_dir = tmp_path / "render"
    _complete_with_records(fake_bpy, small_plan, render_dir)
    (render_dir / "evil.writing").write_text("not ours", encoding="utf-8")
    with pytest.raises(executor.RenderDirectoryRefused, match="not something Phase 23 put here"):
        _survey(fake_bpy, small_plan, render_dir)


def test_a_genuine_writing_temporary_is_named_as_an_interrupted_run(
    fake_bpy: FakeBpy, small_plan: dict[str, Any], tmp_path: Path
) -> None:
    """The control for the row above: real crash debris is still recognised as ours."""
    render_dir = tmp_path / "render"
    _complete_with_records(fake_bpy, small_plan, render_dir)
    (render_dir / "episode_render_manifest.json.writing").write_bytes(b"{}")
    with pytest.raises(executor.RenderDirectoryRefused, match="did not finish"):
        _survey(fake_bpy, small_plan, render_dir)
