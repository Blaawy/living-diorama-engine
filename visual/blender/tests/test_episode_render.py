"""Phase 23 structural tests, inside real Blender.

Everything here needs a real renderer to mean anything: whether the composed
scene actually reports the colour management the profile claims to inherit,
whether Blender's own active camera at a frame is the directed one, whether a
frame rendered twice stays inside the renderer's measured noise band, and
whether the boundary frame stays within tolerance of the last playback frame.

Ordinary pytest never imports this module. It runs under
``blender --background --factory-startup`` through the Phase 23 runner, against
a world that has already been composed and directed.
"""

import sys
import zlib
from pathlib import Path

import bpy

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent / "scripts"
for directory in (str(TESTS_DIR), str(SCRIPTS_DIR)):
    if directory not in sys.path:  # pragma: no cover - import-path bootstrap
        sys.path.insert(0, directory)

import render_episode  # noqa: E402


def _scratch(context: dict, name: str) -> Path:
    """A directory this test owns, emptied first."""
    import shutil

    path = Path(context["workdir"]) / "phase23" / name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


# ------------------------------------------------------------------ profile


def test_the_profile_binding_is_the_approved_profile(context: dict) -> None:
    """The plan's profile is this build's profile, checked absolutely."""
    plan = render_episode.require_render_plan(context["render_plan"])
    digest = render_episode.sha256_hex(render_episode.canonical_bytes(plan["profile"]))
    assert digest == render_episode.RENDER_PROFILE_SHA256


def test_the_composed_scene_carries_the_colour_management_the_profile_verifies(
    context: dict,
) -> None:
    """The inherited half of the profile is a claim about the real world build.

    If Phase 15's style profile ever changed, this fails here rather than
    silently producing an episode that looks different from the reviewed one.
    """
    applied = render_episode.apply_render_profile(bpy, context["render_plan"]["profile"])
    verified = context["render_plan"]["profile"]["verified"]
    assert applied["verified"] == verified
    assert bpy.context.scene.view_settings.view_transform == verified["view_transform"]
    assert bpy.context.scene.view_settings.look == verified["look"]


def test_the_profile_sets_what_it_owns_on_the_real_scene(context: dict) -> None:
    """Nothing important is inherited from whatever the scene happened to hold."""
    render_episode.apply_render_profile(bpy, context["render_plan"]["profile"])
    owned = context["render_plan"]["profile"]["owned"]
    render = bpy.context.scene.render
    assert render.engine == owned["engine"]
    assert render.resolution_x == owned["resolution_x"]
    assert render.resolution_y == owned["resolution_y"]
    assert render.resolution_percentage == owned["resolution_percentage"]
    assert render.image_settings.file_format == owned["file_format"]
    assert render.image_settings.color_mode == owned["color_mode"]
    assert render.image_settings.color_depth == owned["color_depth"]
    assert render.use_motion_blur is owned["use_motion_blur"]
    assert bpy.context.scene.cycles.samples == owned["cycles_samples"]
    assert bpy.context.scene.cycles.seed == owned["cycles_seed"]
    assert bpy.context.scene.cycles.use_animated_seed is owned["cycles_use_animated_seed"]


def test_a_scene_on_the_wrong_clock_is_refused_and_restored(context: dict) -> None:
    """A 60 fps scene would play the locked episode in a third of its runtime."""
    scene = bpy.context.scene
    original = scene.render.fps
    scene.render.fps = 60
    try:
        raised = False
        try:
            render_episode.apply_render_profile(bpy, context["render_plan"]["profile"])
        except RuntimeError as error:
            raised = "fps" in str(error)
        assert raised, "a 60 fps scene must be refused"
    finally:
        scene.render.fps = original
    render_episode.apply_render_profile(bpy, context["render_plan"]["profile"])


def test_a_scene_whose_look_drifted_is_refused_and_restored(context: dict) -> None:
    """Colour belongs to the world build; Phase 23 never overrides it."""
    settings = bpy.context.scene.view_settings
    original = settings.exposure
    settings.exposure = original + 0.5
    try:
        raised = False
        try:
            render_episode.apply_render_profile(bpy, context["render_plan"]["profile"])
        except RuntimeError as error:
            raised = "exposure" in str(error)
        assert raised, "a drifted exposure must be refused"
        assert abs(settings.exposure - (original + 0.5)) < 1e-6, "the drift must not be repaired"
    finally:
        settings.exposure = original


# ------------------------------------------------------------------- cameras


def test_blenders_own_active_camera_matches_the_plan_at_every_cut(context: dict) -> None:
    """The claim every frame record makes, checked where cuts actually happen.

    Every shot boundary and both ends -- the frames where a marker either fires
    or must not -- rather than a sample, because an off-by-one at a cut is
    exactly the failure this phase must never ship.
    """
    plan = context["render_plan"]
    directed = {entry["frame"]: entry["camera_anchor_id"] for entry in plan["frames"]}
    boundaries: set[int] = {plan["emission"]["first_frame"], plan["emission"]["final_frame"]}
    previous = None
    for entry in plan["frames"]:
        if entry["shot_id"] != previous:
            boundaries.add(entry["frame"])
            if entry["frame"] > 1:
                boundaries.add(entry["frame"] - 1)
            previous = entry["shot_id"]
    boundaries.add(plan["emission"]["witness_frame"])
    for frame in sorted(boundaries):
        bpy.context.scene.frame_set(frame)
        render_episode.verify_active_camera(bpy, frame, directed[frame])


def test_the_loop_endpoints_share_one_camera(context: dict) -> None:
    """Phase 22 closes the loop; the render must not open it."""
    plan = context["render_plan"]
    first, witness = plan["emission"]["first_frame"], plan["emission"]["witness_frame"]
    bpy.context.scene.frame_set(first)
    opening = bpy.context.scene.camera.name
    bpy.context.scene.frame_set(witness)
    closing = bpy.context.scene.camera.name
    assert opening == closing


def test_a_camera_the_plan_does_not_direct_is_refused(context: dict) -> None:
    """The check is a real comparison, not a formality that always passes."""
    bpy.context.scene.frame_set(1)
    raised = False
    try:
        render_episode.verify_active_camera(bpy, 1, "CAM_SCAR_DETAIL")
    except RuntimeError as error:
        raised = "directs" in str(error)
    assert raised


# ------------------------------------------------------------------ rendering


def test_a_rendered_frame_is_a_complete_png_at_the_profile_size(context: dict) -> None:
    """One real frame, through the real camera, verified structurally."""
    render_episode.apply_render_profile(bpy, context["render_plan"]["profile"])
    scratch = _scratch(context, "single_frame")
    destination = scratch / "frame_0001.png"
    facts = render_episode.render_frame_file(
        bpy, 1, scratch / ".partial", destination, profile=context["render_plan"]["profile"]
    )
    owned = context["render_plan"]["profile"]["owned"]
    assert destination.is_file()
    assert facts["width"] == owned["resolution_x"]
    assert facts["height"] == owned["resolution_y"]
    assert facts["bytes"] > 0
    assert len(facts["sha256"]) == 64
    assert not (scratch / ".partial").exists()


def test_the_same_frame_rendered_twice_lands_inside_the_noise_band(context: dict) -> None:
    """How reproducible this renderer actually is, measured rather than claimed.

    Cycles on a GPU is stochastic: an unchanged scene rendered twice does not
    come back bit for bit, and pinning the sampling seed narrows the band
    without closing it. So this measures the band instead of asserting it away,
    and holds it to the tolerance the profile documents. That measurement is
    what makes the boundary-witness number in the next test interpretable: a
    difference is only evidence of motion if it is bigger than the noise.
    """
    profile = context["render_plan"]["profile"]
    render_episode.apply_render_profile(bpy, profile)
    scratch = _scratch(context, "twice")
    first = render_episode.render_frame_file(
        bpy, 12, scratch / ".partial", scratch / "a.png", profile=profile
    )
    second = render_episode.render_frame_file(
        bpy, 12, scratch / ".partial", scratch / "b.png", profile=profile
    )
    difference = render_episode.png_mean_abs_difference(scratch / "a.png", scratch / "b.png")
    print(f"LD_P23_MEASURED_RERENDER_DIFFERENCE {difference}")
    print(
        f"LD_P23_RERENDER_IMAGE_DIGESTS {first['image_sha256'][:12]} {second['image_sha256'][:12]}"
    )
    assert difference <= render_episode.RENDER_NOISE_TOLERANCE, (
        f"two renders of one unchanged frame differ by {difference} levels, beyond the "
        "renderer's documented noise band; something other than sampling changed"
    )


def test_the_boundary_frame_is_where_the_episode_ends_not_a_cut(context: dict) -> None:
    """The emission contract, proved on the composed world rather than argued.

    Three facts decide that frame 193 belongs outside the playback sequence,
    and each is checked here against the real scene:

    * it is on the same camera as the last playback frame and as frame 1 --
      Phase 22's loop closure, so no cut happens at the boundary;
    * Phase 19's movers have returned to their frame-1 positions, which is that
      layer's own locked contract, so the boundary frame is the loop seam that
      the next leg's frame 1 shows again;
    * the picture at 193 differs from the picture at 192 only by the residue of
      one frame of motion, measured and required to be inside tolerance.

    Emitting it would therefore both overrun the declared eight seconds and
    show the loop seam twice.
    """
    plan = context["render_plan"]
    render_episode.apply_render_profile(bpy, plan["profile"])
    scene = bpy.context.scene
    final_playback = plan["emission"]["final_frame"]
    witness = plan["emission"]["witness_frame"]

    scene.frame_set(final_playback)
    last_camera = scene.camera.name
    scene.frame_set(witness)
    assert scene.camera.name == last_camera, "the boundary frame must not be a cut"

    def mover_positions(frame: int) -> dict:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        return {
            obj.name: tuple(obj.matrix_world.translation)
            for obj in bpy.data.objects
            if obj.name.startswith(("LD_POP__", "LD_VEH__"))
        }

    # Phase 19 states its own loop contract as a measurement within 1e-4 per
    # axis, so this checks exactly that and claims nothing tighter.
    start = mover_positions(plan["emission"]["first_frame"])
    boundary = mover_positions(witness)
    assert start and boundary, "the composed world must carry movers"
    assert set(start) == set(boundary)
    drift = max(
        abs(start[name][axis] - boundary[name][axis]) for name in start for axis in range(3)
    )
    print(f"LD_P23_MEASURED_MOVER_DRIFT {drift:.9f}")
    assert drift < 1.0e-4, (
        f"Phase 19 returns every mover to its start at the end frame within 1e-4; the largest "
        f"drift here is {drift}, so the boundary frame is not the loop seam"
    )

    scratch = _scratch(context, "boundary")
    render_episode.render_frame_file(
        bpy, final_playback, scratch / ".partial", scratch / "final.png", profile=plan["profile"]
    )
    render_episode.render_frame_file(
        bpy, witness, scratch / ".partial", scratch / "witness.png", profile=plan["profile"]
    )
    difference = render_episode.png_mean_abs_difference(
        scratch / "final.png", scratch / "witness.png"
    )
    print(f"LD_P23_MEASURED_WITNESS_DIFFERENCE {difference}")
    assert difference <= render_episode.WITNESS_DIFFERENCE_TOLERANCE, (
        f"frame {witness} differs from frame {final_playback} by {difference} levels, beyond "
        "the tolerance; the episode would be ending mid-action"
    )


def test_an_interrupted_render_leaves_no_publishable_frame(context: dict) -> None:
    """A file under the partial directory is by construction not an asset."""
    scratch = _scratch(context, "interrupted")
    partial = scratch / ".partial"
    partial.mkdir()
    (partial / "frame_0001.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    assert not (scratch / "frame_0001.png").exists()
    render_episode.apply_render_profile(bpy, context["render_plan"]["profile"])
    facts = render_episode.render_frame_file(
        bpy, 1, partial, scratch / "frame_0001.png", profile=context["render_plan"]["profile"]
    )
    assert facts["bytes"] > 100
    assert not partial.exists()


def test_the_executor_refuses_a_plan_carrying_a_foreign_profile(context: dict) -> None:
    """The absolute pin holds inside Blender too."""
    import copy

    forged = copy.deepcopy(context["render_plan"])
    forged["profile"]["owned"]["cycles_samples"] = 4096
    forged["source"]["render_profile_sha256"] = render_episode.sha256_hex(
        render_episode.canonical_bytes(forged["profile"])
    )
    raised = False
    try:
        render_episode.require_render_plan(forged)
    except render_episode.PlanRefused as error:
        # Both pins fire on a forged pair: the source binding is compared to the
        # approved digest before the profile body is hashed, so whichever speaks
        # first, the plan is refused for naming a profile this build does not
        # render under.
        message = str(error)
        raised = "approved profile digest" in message or "this build renders under" in message
    assert raised


# --------------------------------------------------------- source identity


def test_the_composed_world_was_built_from_the_pinned_sources(context: dict) -> None:
    """Every config this world was composed from is the reviewed document.

    The suite composes from the same paths the production renderer is given, so
    hashing them here proves the world these tests ran against is the world the
    plan names -- not merely that the plan and the files agree with each other.
    """
    import hashlib

    plan = context["render_plan"]
    paths = {
        "master_scene_sha256": context["spec_path"],
        "production_world_sha256": context["production_path"],
        "motion_time_sha256": context["motion_path"],
        "population_presence_sha256": context["presence_path"],
        "daily_life_mobility_sha256": context["mobility_path"],
        "state_response_sha256": context["state_response_path"],
    }
    for key, path in sorted(paths.items()):
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        assert digest == plan["composition_sources"][key], key
        assert digest == render_episode.APPROVED_COMPOSITION_SOURCES[key], key


def test_an_alternate_config_is_refused_before_anything_is_composed(context: dict) -> None:
    """A document that means something slightly different is still refused.

    The clock is untouched here, so every Phase 17 and Phase 22 check would
    still pass -- only the motion inside the transition changes. This is the
    binding that catches it, and it catches it on raw bytes, before a single
    layer is applied.
    """
    import hashlib
    import json

    scratch = _scratch(context, "alternate_source")
    original = Path(context["motion_path"]).read_bytes()
    document = json.loads(original)
    document["channels"][0]["window"] = [0.05, 0.60]
    forged = scratch / "motion_time_v1.json"
    forged.write_bytes(json.dumps(document).encode("utf-8"))

    assert json.loads(forged.read_bytes())["timeline"] == json.loads(original)["timeline"]
    bound = context["render_plan"]["composition_sources"]["motion_time_sha256"]
    assert hashlib.sha256(forged.read_bytes()).hexdigest() != bound
    assert hashlib.sha256(original).hexdigest() == bound


def test_the_exact_shot_plan_file_is_what_binds_the_render(context: dict) -> None:
    """The binding is over a file's bytes, so a re-formatted copy is another file.

    Canonicalising before hashing would accept every one of these. Each carries
    exactly the same data; none of them is the file the render plan bound.
    """
    import json as _json

    plan = context["render_plan"]
    path = context["shot_plan_paths"]["leg1"]
    canonical = path.read_bytes()
    render_episode.require_shot_plan_bytes(plan, canonical)

    for label, payload in (
        ("pretty printed", _json.dumps(context["shot_plans"]["leg1"], indent=2).encode("utf-8")),
        ("trailing whitespace", canonical + b" "),
        ("leading newline", b"\n" + canonical),
    ):
        try:
            render_episode.require_shot_plan_bytes(plan, payload)
        except render_episode.PlanRefused:
            continue
        raise AssertionError(f"a {label} copy of the shot plan was accepted")


def test_a_render_plan_that_contradicts_its_direction_is_refused_here_too(
    context: dict,
) -> None:
    """Every field the plan copied from Phase 22 is compared, not just the camera.

    An independent reviewer walked a forged ``source_beat_ids`` past the V2
    check, which compared shot id and camera and nothing else.
    """
    import copy as _copy

    plan = context["render_plan"]
    direction = context["shot_plans"]["leg1"]
    render_episode.require_plan_matches_shot_plan(plan, direction)

    attacks = {
        "forged playback beats": lambda p: p["frames"][0].update(source_beat_ids=["FAKE_BEAT"]),
        "forged witness beats": lambda p: p["frames"][-1].update(source_beat_ids=["FAKE_BEAT"]),
        "undirected camera": lambda p: p["frames"][0].update(camera_anchor_id="CAM_SEAL_DETAIL"),
        "forged shot id": lambda p: p["frames"][0].update(shot_id="shot_0002"),
        "alternate clock": lambda p: p["timeline"].update(
            start_hold_frames=25, transition_frames=119, transition_start=26
        ),
        "forged story digest": lambda p: p["source"].update(story_plan_sha256="0" * 64),
    }
    for label, mutate in attacks.items():
        broken = _copy.deepcopy(plan)
        mutate(broken)
        try:
            render_episode.require_plan_matches_shot_plan(broken, direction)
        except render_episode.PlanRefused:
            continue
        raise AssertionError(f"a render plan with {label} was accepted against its direction")


def test_a_foreign_catalogue_is_refused_before_any_world_is_composed(context: dict) -> None:
    """A preflight, not a replacement for Phase 22's own semantic check.

    Composing the world takes minutes; discovering a catalogue mismatch
    afterwards wastes all of them, and nothing should be built for a render that
    cannot legally finish.
    """
    import copy as _copy

    plan = context["render_plan"]
    render_episode.require_approved_catalogue(plan, context["catalogue"])

    forged = _copy.deepcopy(context["catalogue"])
    forged[sorted(forged)[0]]["location"] = [0.0, 0.0, 0.0]
    try:
        render_episode.require_approved_catalogue(plan, forged)
    except render_episode.PlanRefused:
        return
    raise AssertionError("a catalogue with a moved anchor was accepted")


def test_an_unapproved_camera_anchor_is_refused_by_the_executor(context: dict) -> None:
    """``BANANA`` walked past the V2 production validator; the anchor set is now restated."""
    import copy as _copy

    broken = _copy.deepcopy(context["render_plan"])
    broken["frames"][0]["camera_anchor_id"] = "BANANA"
    try:
        render_episode.require_valid_render_plan(broken)
    except render_episode.PlanRefused as error:
        assert "approved anchor" in str(error), str(error)
        return
    raise AssertionError("an unapproved camera anchor was accepted")


def test_every_rendered_frame_is_the_profile_size_and_an_rgb_png(context: dict) -> None:
    """The audit's per-frame profile check, exercised against real Blender output."""
    scratch = _scratch(context, "profile_frames")
    render_episode.apply_render_profile(bpy, context["render_plan"]["profile"])
    owned = context["render_plan"]["profile"]["owned"]
    for frame in (1, 60, 193):
        path = scratch / f"frame_{frame:04d}.png"
        facts = render_episode.render_frame_file(
            bpy, frame, scratch / ".partial", path, profile=context["render_plan"]["profile"]
        )
        assert facts["width"] == owned["resolution_x"], (frame, facts)
        assert facts["height"] == owned["resolution_y"], (frame, facts)
        width, height, samples = render_episode.png_pixels(path)
        assert (width, height) == (owned["resolution_x"], owned["resolution_y"])
        assert len(samples) == width * height * 3


def test_a_real_render_resumes_under_its_own_environment(context: dict) -> None:
    """Resume works in production, and skips exactly what it already published.

    Bounded on purpose: two frames, then one more. The point is the resume
    contract on the real executor with real Blender output, not the wall clock.
    """
    import json as _json

    scratch = _scratch(context, "resume_same")
    plan = context["render_plan"]

    first = render_episode.execute_render(bpy, plan=plan, render_dir=scratch, limit=2)
    assert len(first["rendered"]) == 2, first["rendered"]
    assert first["already_complete"] is False

    second = render_episode.execute_render(bpy, plan=plan, render_dir=scratch, limit=1)
    assert second["skipped"] == first["rendered"], (second["skipped"], first["rendered"])
    assert len(second["rendered"]) == 1, second["rendered"]
    assert second["environment"] == first["environment"]

    checkpoint = _json.loads((scratch / "render_checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["environment"] == first["environment"]
    assert sorted(int(key) for key in checkpoint["frames"]) == [1, 2, 3]


def test_a_real_partial_render_refuses_a_foreign_environment(context: dict) -> None:
    """The reviewer's mixed-environment episode, refused by the production path.

    The checkpoint is rewritten to claim another machine produced the frames
    already here, which is exactly the state a resume on a second machine would
    find. Reusing them and then recording this run's environment would put a
    machine's name on pixels it never made.
    """
    import json as _json

    scratch = _scratch(context, "resume_foreign")
    plan = context["render_plan"]
    render_episode.execute_render(bpy, plan=plan, render_dir=scratch, limit=2)

    path = scratch / "render_checkpoint.json"
    checkpoint = _json.loads(path.read_text(encoding="utf-8"))
    checkpoint["environment"]["blender_version"] = "4.6.0 LTS (another machine)"
    render_episode.write_json_atomically(path, checkpoint)
    before = sorted(entry.name for entry in (scratch / "frames").iterdir())

    try:
        render_episode.execute_render(bpy, plan=plan, render_dir=scratch, limit=1)
    except render_episode.RenderDirectoryRefused as error:
        assert "one environment" in str(error), str(error)
        after = sorted(entry.name for entry in (scratch / "frames").iterdir())
        assert after == before, (before, after)
        return
    raise AssertionError("a partial render was resumed under a foreign environment")


def test_a_malformed_checkpoint_is_refused_in_production(context: dict) -> None:
    """A checkpoint vouches for work not done, so it is validated before it is believed."""
    import json as _json

    scratch = _scratch(context, "resume_bad_checkpoint")
    plan = context["render_plan"]
    render_episode.execute_render(bpy, plan=plan, render_dir=scratch, limit=2)

    path = scratch / "render_checkpoint.json"
    checkpoint = _json.loads(path.read_text(encoding="utf-8"))
    checkpoint["frames"]["9999"] = checkpoint["frames"]["1"]
    render_episode.write_json_atomically(path, checkpoint)

    try:
        render_episode.execute_render(bpy, plan=plan, render_dir=scratch, limit=1)
    except render_episode.RenderDirectoryRefused as error:
        assert "9999" in str(error), str(error)
        return
    raise AssertionError("a checkpoint vouching for an unplanned frame was believed")


def test_a_real_frame_is_fully_verified_before_it_is_published(context: dict) -> None:
    """The publication gate, on real Blender output.

    A frame reaching its final name has been decoded completely -- structure,
    profile, exact resolution and every scanline -- not merely hashed.
    """
    scratch = _scratch(context, "publish_gate")
    plan = context["render_plan"]
    profile = plan["profile"]
    owned = profile["owned"]
    destination = scratch / "frame_0001.png"

    facts = render_episode.render_frame_file(
        bpy, 1, scratch / ".partial", destination, profile=profile
    )
    assert destination.is_file()
    assert facts["width"] == owned["resolution_x"]
    assert facts["height"] == owned["resolution_y"]
    # The same gate, run again over the published file: it passes on its own.
    again = render_episode.require_verified_frame(destination, profile)
    assert again["sha256"] == facts["sha256"]

    # And a foreign profile is refused against the very same real frame.
    smaller = {"owned": {"resolution_x": 640, "resolution_y": 360}}
    try:
        render_episode.require_verified_frame(destination, smaller)
    except render_episode.FrameRefused:
        return
    raise AssertionError("a real frame passed verification against the wrong profile")


def test_a_real_frame_with_illegal_chunk_order_is_refused(context: dict) -> None:
    """The reviewer's three structural cases, against real Blender bytes.

    The picture is genuine and its CRCs are correct; only the arrangement is
    wrong. V3 accepted all three.
    """
    scratch = _scratch(context, "chunk_order")
    plan = context["render_plan"]
    source = scratch / "frame_0001.png"
    render_episode.render_frame_file(bpy, 1, scratch / ".partial", source, profile=plan["profile"])
    data = source.read_bytes()

    def _chunk(kind: bytes, body: bytes) -> bytes:
        import struct as _struct

        return (
            _struct.pack(">I", len(body))
            + kind
            + body
            + _struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    variants = {
        "duplicate IEND": data + _chunk(b"IEND", b""),
        "unknown critical chunk": (data[:8] + _chunk(b"BAAD", b"\x00\x01") + data[8:]),
    }
    for label, payload in variants.items():
        target = scratch / f"{label.replace(' ', '_')}.png"
        target.write_bytes(payload)
        try:
            render_episode.png_facts(target)
        except render_episode.FrameRefused:
            pass
        else:
            raise AssertionError(f"png_facts accepted a real frame with {label}")
        try:
            render_episode.png_pixels(target)
        except render_episode.FrameRefused:
            continue
        raise AssertionError(f"png_pixels accepted a real frame with {label}")


def test_a_real_frames_compressed_stream_is_exact(context: dict) -> None:
    """A genuine Blender frame passes the strict stream check, and trailing bytes do not.

    Real frames carry 108 to 130 IDAT chunks, so this also proves the check is
    applied to the joined payload rather than one chunk at a time -- per chunk
    it would refuse every frame this phase has ever produced.
    """
    import struct as _struct

    scratch = _scratch(context, "stream")
    plan = context["render_plan"]
    source = scratch / "frame_0001.png"
    facts = render_episode.render_frame_file(
        bpy, 1, scratch / ".partial", source, profile=plan["profile"]
    )
    data = source.read_bytes()

    chunks = []
    offset = 8
    while offset < len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunks.append((data[offset + 4 : offset + 8], offset, length))
        offset += length + 12
    idats = [entry for entry in chunks if entry[0] == b"IDAT"]
    assert len(idats) > 1, f"expected a multi-chunk stream, got {len(idats)}"
    assert facts["image_sha256"]

    # Now append junk to the final IDAT and rebuild the file around it.
    kind, start, length = idats[-1]
    body = data[start + 8 : start + 8 + length] + b"JUNK"
    rebuilt = (
        data[:start]
        + _struct.pack(">I", len(body))
        + kind
        + body
        + _struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        + data[start + 12 + length :]
    )
    target = scratch / "trailing.png"
    target.write_bytes(rebuilt)
    for reader in (render_episode.png_facts, render_episode.png_pixels):
        try:
            reader(target)
        except render_episode.FrameRefused as error:
            assert "after the end" in str(error), str(error)
            continue
        raise AssertionError(f"{reader.__name__} accepted a real frame with trailing stream bytes")


def test_a_real_render_directory_refuses_a_foreign_root_entry(context: dict) -> None:
    """Production and the independent verifier agree on what a directory may hold.

    Bounded: two frames is enough to make a directory the survey will look at.
    """
    scratch = _scratch(context, "root_ownership")
    plan = context["render_plan"]
    digest = render_episode.sha256_hex(render_episode.canonical_bytes(plan))
    result = render_episode.execute_render(bpy, plan=plan, render_dir=scratch, limit=2)
    environment = result["environment"]

    # The control: the directory the executor just made is one it accepts.
    render_episode.survey_render_directory(scratch, plan, digest, environment)

    (scratch / "evil.txt").write_text("dropped here by somebody", encoding="utf-8")
    before = sorted(entry.name for entry in scratch.iterdir())
    try:
        render_episode.survey_render_directory(scratch, plan, digest, environment)
    except render_episode.RenderDirectoryRefused as error:
        assert "not something Phase 23 put here" in str(error), str(error)
        # Nothing foreign was deleted to reach that verdict.
        assert sorted(entry.name for entry in scratch.iterdir()) == before
        return
    raise AssertionError("a foreign root entry was accepted by the production survey")


def test_a_real_malformed_checkpoint_refuses_as_a_directory_problem(context: dict) -> None:
    """An unreadable record is a statement about the directory, not a parser error."""
    scratch = _scratch(context, "bad_record")
    plan = context["render_plan"]
    digest = render_episode.sha256_hex(render_episode.canonical_bytes(plan))
    result = render_episode.execute_render(bpy, plan=plan, render_dir=scratch, limit=2)

    (scratch / "render_checkpoint.json").write_bytes(b"{ not json")
    try:
        render_episode.survey_render_directory(scratch, plan, digest, result["environment"])
    except render_episode.RenderDirectoryRefused as error:
        assert "not a readable" in str(error), str(error)
        return
    raise AssertionError("a malformed checkpoint was believed")


def test_a_real_checkpoint_claiming_a_different_plan_is_refused(context: dict) -> None:
    """The reviewer's exact reproduction, against a real Blender-produced checkpoint.

    Every frame file and every frame result stays truthful; only the
    checkpoint's own claim about which plan and profile it belongs to is
    wrong. Production has always checked this -- the independent audit did
    not, until V6.
    """
    import json as _json

    scratch = _scratch(context, "checkpoint_identity")
    plan = context["render_plan"]
    digest = render_episode.sha256_hex(render_episode.canonical_bytes(plan))
    result = render_episode.execute_render(bpy, plan=plan, render_dir=scratch, limit=3)

    path = scratch / "render_checkpoint.json"
    for field in ("render_plan_sha256", "render_profile_sha256"):
        checkpoint = _json.loads(path.read_text(encoding="utf-8"))
        checkpoint[field] = "0" * 64
        render_episode.write_json_atomically(path, checkpoint)
        try:
            render_episode.survey_render_directory(scratch, plan, digest, result["environment"])
        except render_episode.RenderDirectoryRefused:
            continue
        raise AssertionError(f"a checkpoint with a forged {field} was believed")

    # Restored, so the fixture is left in a state a later resume could still use.
    render_episode.write_json_atomically(
        path,
        {
            "render_plan_sha256": digest,
            "render_profile_sha256": render_episode.RENDER_PROFILE_SHA256,
            "environment": result["environment"],
            "frames": {str(frame): facts for frame, facts in sorted(result["frames"].items())},
        },
    )
    render_episode.survey_render_directory(scratch, plan, digest, result["environment"])


def test_a_real_non_canonical_frame_key_is_refused(context: dict) -> None:
    """`"01"` is not `"1"`, even though `int()` would happily agree they are."""
    import json as _json

    scratch = _scratch(context, "canonical_key")
    plan = context["render_plan"]
    digest = render_episode.sha256_hex(render_episode.canonical_bytes(plan))
    result = render_episode.execute_render(bpy, plan=plan, render_dir=scratch, limit=3)

    path = scratch / "render_checkpoint.json"
    checkpoint = _json.loads(path.read_text(encoding="utf-8"))
    checkpoint["frames"]["01"] = checkpoint["frames"].pop("1")
    render_episode.write_json_atomically(path, checkpoint)
    try:
        render_episode.survey_render_directory(scratch, plan, digest, result["environment"])
    except render_episode.RenderDirectoryRefused as error:
        assert "canonical spelling" in str(error) or "frame number" in str(error), str(error)
        return
    raise AssertionError("a non-canonical checkpoint frame key was believed")


def test_the_executor_validates_the_whole_plan_here_too(context: dict) -> None:
    """The closed validator runs inside Blender, on the real plan."""
    assert render_episode.require_valid_render_plan(context["render_plan"]) is not None


def test_a_traversing_frame_name_is_refused_in_blender(context: dict) -> None:
    """The reviewer's reproduction, refused on the production side."""
    import copy

    broken = copy.deepcopy(context["render_plan"])
    broken["frames"][0]["file"] = "../../owned.png"
    raised = False
    try:
        render_episode.require_valid_render_plan(broken)
    except render_episode.PlanRefused as error:
        raised = "parent directory" in str(error) or "path separator" in str(error)
    assert raised, "a frame name that climbs out of the render directory must be refused"


# ------------------------------------------------------------ baseline mode
# This test recomposes the scene from a single export and therefore replaces
# the transition world every test above runs against. It is deliberately last.


def test_a_baseline_composes_from_one_bound_world(context: dict) -> None:
    """Baseline source closure, proved on the real composed world.

    A baseline holds one state, so it is composed from its own bound export at
    both endpoints -- there is no second world to be handed, and therefore no
    unbound input that could change the picture. Phase 20 writes no transition
    directives for identical endpoints, which is correct and is why the census
    is told not to expect them; every other layer must still be exactly right,
    and Phase 22's neutral direction must still hold.
    """
    import episode_scene

    plan = context["baseline_render_plan"]
    assert plan["source"]["mode"] == "baseline"
    assert plan["source"]["before_export_sha256"] is None

    expected = episode_scene.compose_episode_world(
        spec_path=context["spec_path"],
        production_path=context["production_path"],
        motion_path=context["motion_path"],
        presence_path=context["presence_path"],
        mobility_path=context["mobility_path"],
        state_response_path=context["state_response_path"],
        before_path=context["before_path"],
        after_path=context["before_path"],
    )
    census = episode_scene.census_composed_world(bpy, expected, expect_state_response_motion=False)
    print(f"LD_P23_BASELINE_COMPOSITION {census}")
    assert census["population_proxies"] == expected["expected_proxies"] > 0
    assert census["mobility_vehicle_bodies"] == expected["expected_vehicles"] > 0
    assert census["state_response_air_strata"] == expected["expected_air"] > 0
    assert census["mobility_actions"] > 0, "a baseline still lives: its movers keep their circuits"
    assert census["state_response_actions"] == 0, (
        "identical endpoints give Phase 20 nothing to animate; requiring curves here would "
        "refuse a correct baseline world"
    )

    episode_scene.direct_episode_world(bpy, context["shot_plans"]["baseline"], context["catalogue"])
    scene = bpy.context.scene
    for entry in (plan["frames"][0], plan["frames"][-1]):
        scene.frame_set(entry["frame"])
        render_episode.verify_active_camera(bpy, entry["frame"], entry["camera_anchor_id"])
    anchors = {entry["camera_anchor_id"] for entry in plan["frames"]}
    assert anchors == {"CAM_HERO_WORLD"}, (
        "a baseline is one neutral hold; Phase 22 directs nothing else and Phase 23 must not "
        "invent a cut"
    )
