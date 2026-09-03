"""DRAFT (in-editor, UNVERIFIED) -- Level Sequence authoring + Movie Render Queue
render for the closure bake (Phase-2 closure lane S, contract C3).

Status: this file has NOT run in the Unreal editor. Every `unreal` API below
whose name/shape is not pinned by an existing probe in this repo is annotated
with a one-line "PROBE:" comment -- it must be verified by dir()/introspection
in the editor before the first real run (same discipline as ldyf_playback.py's
"unverified name" comments and EVIDENCE_editor_api_probe.json). The pure,
deterministic side of the lane lives in ldyf/sequence_bake.py (unit-tested);
this module only moves baked keys into a LevelSequence and queues an MRQ job.

Assumption (stated plainly, per lane brief)
------------------------------------------
The possessables are the actors the PLAYBACK module (ldyf/unreal/ldyf_playback.py)
placed into the editor world; MRQ renders in PIE, so those editor-world actors
must exist when PIE starts (playback spawned them into the level -- destroy and
respawn on presence change, ldyf_playback.py:724-735). The Level Sequence's
transform/visibility keys are baked from the sealed record (no wall clock), so
output frame N of the render is presentation second N/fps regardless of render
time (C3).

Label convention -- READ FROM THE PLAYBACK MODULE, not guessed
-------------------------------------------------------------
ldyf_playback.py:690 builds ``"LD_{uid.replace(':', '_')}"``, e.g. uid
"vehicle:12" -> label "LD_vehicle_12" (uid keys are "vehicle:<id>" /
"person:<id>", sumo_record.py:165). The lane brief described these as
"LD_VEHICLE_<uid>" / "LD_PERSON_<uid>"; the module's actual labels keep the
lower-case kind from the uid. Lookup below tries the playback spelling first
and the brief's upper-case spelling second.
"""

from __future__ import annotations

import json
from pathlib import Path

try:  # pragma: no cover - editor-only import
    import unreal  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - plain-Python import stays harmless
    unreal = None

_SEQUENCE_BAKE_V1 = "sequence_bake_v1"
_DEFAULT_ASSET_PATH = "/Game/LD/LS_Preview"


def _need_unreal() -> None:
    if unreal is None:
        raise RuntimeError("ldyf_sequence: editor-only module (no `unreal` import)")


def _label_candidates(uid: str, kind: str) -> list[str]:
    """Playback-spelling first (ldyf_playback.py:690), brief-spelling second."""
    flat = uid.replace(":", "_")
    return [f"LD_{flat}", f"LD_{kind.upper()}_{uid}"]


def _find_level_actor(uid: str, kind: str):
    """First editor actor whose label matches the playback label of `uid`."""
    wanted = set(_label_candidates(uid, kind))
    # PROBE: EditorLevelLibrary.get_all_level_actors() is verified by
    # ldyf_roads_editor.py:27; get_actor_label() verified by ldyf_playback.py.
    for a in unreal.EditorLevelLibrary.get_all_level_actors():
        if a is not None and str(a.get_actor_label() or "") in wanted:
            return a
    return None


def _load_bake(bake_path: str) -> dict:
    doc = json.loads(Path(bake_path).read_text(encoding="utf-8"))
    if doc.get("schema_version") != _SEQUENCE_BAKE_V1:
        raise ValueError(f"{bake_path}: not a sequence_bake_v1 document")
    return doc


def _sequence_or_create(asset_path: str, fps: int):
    """Load /Game/LD/LS_Preview or create it; set display rate + tick res."""
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):  # PROBE: name
        seq = unreal.load_asset(asset_path)                     # verified pattern
    else:
        package_path, _, asset_name = asset_path.rpartition("/")
        # PROBE: AssetToolsHelpers.get_asset_tools() + LevelSequenceFactoryNew
        # + create_asset are the documented UE-5.x create-asset route; shape
        # unverified in this repo (no existing LevelSequence code here).
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        factory = unreal.LevelSequenceFactoryNew()
        seq = tools.create_asset(asset_name, package_path, unreal.LevelSequence, factory)
        if seq is None:
            raise RuntimeError(f"create_asset returned None for {asset_path}")
    # Make one sequence frame == one baked presentation frame:
    # PROBE: ULevelSequence.set_display_rate / set_tick_resolution method names
    # (both are usually on UMovieScene via get_movie_scene()).
    try:
        seq.set_display_rate(unreal.FrameRate(fps, 1))
        seq.set_tick_resolution(unreal.FrameRate(fps, 1))
    except AttributeError:
        movie_scene = seq.get_movie_scene()  # PROBE: get_movie_scene() name
        movie_scene.set_display_rate(unreal.FrameRate(fps, 1))
        movie_scene.set_tick_resolution(unreal.FrameRate(fps, 1))
    return seq


def _frame_number(n: int):
    # PROBE: unreal.FFrameNumber ctor arity (value=) in UE 5.8 python.
    try:
        return unreal.FFrameNumber(value=n)
    except TypeError:
        return unreal.FFrameNumber(n)


def build_level_sequence(
    bake_path: str,
    asset_path: str = _DEFAULT_ASSET_PATH,
    fps: int = 24,
) -> dict:
    """Possess every baked actor and key its transform + visibility tracks.

    Returns counts {sequence, actors_possessed, transform_keys,
    visibility_sections, missing_actors, frames}. Every unreal call below is a
    PROBE until the first in-editor run (see module docstring).
    """
    _need_unreal()
    doc = _load_bake(bake_path)
    first, last = doc["frames"]
    seq = _sequence_or_create(asset_path, int(doc.get("fps", fps)))
    # PROBE: set playback range so sequence frames == presentation frames
    # (UMovieScene.set_playback_range(start_frame, end_frame)).
    movie_scene = seq.get_movie_scene()
    movie_scene.set_playback_range(_frame_number(first), _frame_number(last))

    actors = doc["actors"]
    counts = {
        "actors_possessed": 0,
        "transform_keys": 0,
        "visibility_sections": 0,
        "missing_actors": [],
    }
    for uid, rec in sorted(actors.items()):
        actor = _find_level_actor(uid, rec["kind"])
        if actor is None:
            counts["missing_actors"].append(uid)
            continue
        # PROBE: add_possessable(actor) return type (FMovieSceneBindingProxy?)
        # and whether binding.add_track(...) exists in UE 5.8 python.
        binding = seq.add_possessable(actor)
        transform_track = binding.add_track(unreal.MovieScene3DTransformTrack)
        if transform_track is None:  # PROBE: may need seq.add_track(cls, binding)
            continue
        section = transform_track.add_section()
        section.set_range(_frame_number(first), _frame_number(last))
        # PROBE: channel access on MovieScene3DTransformSection is the highest-
        # risk API here; community examples use section.get_channels() and
        # channel.add_keys([(frame, value), ...]) -- verify with dir(section).
        channels = section.get_channels()  # location X,Y,Z then rotation X,Y,Z
        added = _add_transform_keys(channels, rec["keys"])
        counts["transform_keys"] += added

        # Visibility: one bool section per presence run.
        visibility_track = binding.add_track(unreal.MovieSceneVisibilityTrack)
        if visibility_track is not None:
            for f_on, f_off in rec.get("presence", []):
                vis_section = visibility_track.add_section()
                vis_section.set_range(_frame_number(f_on), _frame_number(f_off))
                # PROBE: set_is_active / default visibility so the actor is
                # hidden outside its presence runs.
                try:
                    vis_section.set_is_active(True)  # PROBE: name
                except AttributeError:
                    pass
                counts["visibility_sections"] += 1
        counts["actors_possessed"] += 1

    counts["sequence"] = asset_path
    counts["frames"] = [first, last]
    unreal.EditorAssetLibrary.save_asset(asset_path)  # PROBE: save name
    return counts


def _add_transform_keys(channels, keys: list[dict]) -> int:
    """Set one transform key per baked frame. Returns keys added.

    channel order for a MovieScene3DTransformSection is expected to be
    location X, Y, Z, rotation X(roll), Y(pitch), Z(yaw) -- PROBE in editor;
    this ordering is the single most likely thing to be wrong here.
    """
    if not keys:
        return 0
    if len(channels) < 6:
        return 0  # PROBE: not the expected channel layout
    loc_x, loc_y, loc_z, rot_x, rot_y, rot_z = channels[:6]
    time_values = [k["f"] for k in keys]
    # PROBE: MovieSceneChannel.add_keys signature (list of (frame, value)).
    try:
        loc_x.add_keys([(_frame_number(f), k["x"]) for f, k in zip(time_values, keys)])
        loc_y.add_keys([(_frame_number(f), k["y"]) for f, k in zip(time_values, keys)])
        loc_z.add_keys([(_frame_number(f), k["z"]) for f, k in zip(time_values, keys)])
        # rotation channels want radians in UE; baked yaw is Unreal degrees.
        import math

        rot_z.add_keys(
            [(_frame_number(f), math.radians(k["yaw"])) for f, k in zip(time_values, keys)]
        )
    except Exception as exc:  # pragma: no cover - editor path
        raise RuntimeError(f"transform key add failed (PROBE needed): {exc}")
    return len(keys)


def _mrq_json_path(out_dir: str) -> Path:
    return Path(out_dir) / "mrq_render.json"


def render_mrq(
    sequence_path: str,
    out_dir: str,
    fps: int = 24,
    resolution: tuple[int, int] = (1920, 1080),
    preset: str | None = None,
) -> dict:
    """Queue the sequence on a MoviePipelineQueue job and run it in PIE.

    Writes mrq_render.json (fps, expected frames, output dir). All Movie
    Render Queue APIs are PROBEs -- no MRQ code exists anywhere in this repo.
    """
    _need_unreal()
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    # PROBE: MoviePipelineQueueSubsystem access pattern; get_queue() name.
    queue_subsystem = unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem)
    queue = queue_subsystem.get_queue()
    queue.delete_all_jobs()  # PROBE: name
    # PROBE: allocate_new_job(Class) return; job.map expects the current
    # editor world path (PIE inherits the level playback populated).
    job = queue.allocate_new_job(unreal.MoviePipelineExecutorJob)
    job.job_name = "ldyf_closure_preview"
    editor_world = unreal.EditorLevelLibrary.get_editor_world()
    job.map = unreal.SoftObjectPath(editor_world.get_path_name())
    job.sequence = unreal.SoftObjectPath(sequence_path)

    config = job.get_configuration()  # PROBE: name
    # PROBE: find_or_add_setting_by_class returns an existing or new setting.
    output = config.find_or_add_setting_by_class(unreal.MoviePipelineOutputSetting)
    output.output_directory = unreal.DirectoryPath(str(Path(out_dir).resolve()))
    output.file_name_format = "{sequence_name}.{frame_number}"
    output.output_resolution = unreal.IntPoint(int(resolution[0]), int(resolution[1]))
    output.frame_rate = unreal.FrameRate(fps, 1)
    if preset is not None:
        # PROBE: applying a preset to a job/config shape is unverified.
        pass
    image_cls = None
    for candidate in (
        "MoviePipelineAppleProResOutput",
        "MoviePipelineImageSequenceOutput_PNG",
    ):
        if hasattr(unreal, candidate):
            image_cls = getattr(unreal, candidate)
            break
    if image_cls is not None:
        config.find_or_add_setting_by_class(image_cls)

    # Expected frame count from the sequence's own playback range if readable.
    expected = None
    seq = unreal.load_asset(sequence_path)
    if seq is not None:
        # PROBE: playback range accessor return shape (TRange<FFrameNumber>).
        try:
            play_range = seq.get_playback_range()
            lo = play_range.get_lower_bound_value()  # PROBE: name
            hi = play_range.get_upper_bound_value()  # PROBE: name
            expected = int(hi) - int(lo) + 1
        except Exception:
            expected = None

    evidence = {
        "schema_version": "mrq_render_v1",
        "fps": fps,
        "expected_frames": expected,
        "sequence_path": sequence_path,
        "output_dir": str(Path(out_dir).resolve()),
        "resolution": list(resolution),
        "preset": preset,
        "assumption": "possessables are the playback module's editor-world actors; "
                      "MRQ renders in PIE so those actors must exist at PIE start",
        "render_time_authority": "output frame N = presentation second N/fps (C3)",
    }
    _mrq_json_path(out_dir).write_text(
        json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8"
    )

    # PROBE: render_queue_with_executor_instance(executor) and the PIE executor
    # class name; this call blocks until the render finishes in-editor.
    executor = unreal.MoviePipelinePIEExecutor()
    queue_subsystem.render_queue_with_executor_instance(executor)
    return {"queued": True, "executor": "MoviePipelinePIEExecutor",
            "evidence": str(_mrq_json_path(out_dir)),
            "expected_frames": expected}
