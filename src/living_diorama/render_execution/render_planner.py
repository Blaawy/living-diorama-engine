"""Derive an Episode Render Plan from a validated Shot Direction Plan.

The planner answers one question per frame: which camera is looking, and where
does that frame's file go. Both answers come from documents that are already
locked -- Phase 22 says which shot owns which frames, Phase 17 says how many
frames there are -- so this module copies and never decides. The only thing it
adds is the emission contract, and that is derived arithmetic, not taste.

Given the same shot plan bytes, this module produces the same bytes. There is
no clock reading, no path of the machine that ran it, and no ordering that
depends on how a mapping was built.
"""

from typing import cast

from living_diorama.cinematic.cinematic_schema_v1 import validate_shot_direction_plan
from living_diorama.cinematic.cinematic_spec import movement_camera_name, movement_catalogue_sha256
from living_diorama.persistence.json_codec import dumps_canonical, loads_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.render_execution.render_execution_schema_v1 import (
    JsonValue,
    validate_episode_render_plan,
)
from living_diorama.render_execution.render_execution_spec import (
    FRAMES_DIRECTORY,
    RENDER_PLAN_FORMAT,
    RENDER_PLAN_SCHEMA_VERSION,
    ROLE_PLAYBACK,
    ROLE_WITNESS,
    WITNESS_DIRECTORY,
    composition_sources_document,
    derive_emission,
    frame_filename,
    render_id,
    render_profile_document,
    render_profile_sha256,
)
from living_diorama.story import validate_episode_story_plan


def _shot_at_frame(shots: list[dict[str, JsonValue]], frame: int) -> dict[str, JsonValue]:
    """Return the one shot whose window contains this frame.

    Raises:
        ValueError: If no shot covers the frame. Phase 22 proves its shots tile
            the timeline, so this cannot happen for a validated plan -- and if
            it ever does, the honest response is to refuse to render a frame
            nobody directed.
    """
    for shot in shots:
        if cast(int, shot["start_frame"]) <= frame <= cast(int, shot["end_frame"]):
            return shot
    raise ValueError(f"no directed shot covers frame {frame}; Phase 23 renders no undirected frame")


def _is_movement_shot(shot: dict[str, JsonValue]) -> bool:
    """Return whether a shot carries a non-STATIC ``camera_movement`` block."""
    movement = shot.get("camera_movement")
    return isinstance(movement, dict) and movement["movement_type"] != "STATIC"


def build_episode_render_plan_document(
    shot_plan: object, story_plan: object, *, camera_profile: str = "v1"
) -> dict[str, JsonValue]:
    """Return the render plan document for one directed episode.

    Both upstream documents are required, and the second is not redundant. The
    shot plan says which camera is looking at each frame; the story plan is the
    only document that names the render exports the episode was derived from,
    and a renderer that did not know those would compose whichever world it was
    handed. Binding their digests here is what lets the executor refuse a
    correct plan pointed at the wrong world.

    The story plan is accepted only if its canonical digest is the one the shot
    plan already bound, so the pair cannot be mismatched.

    Args:
        shot_plan: The parsed Shot Direction Plan document. Under
            ``camera_profile="v2"`` it may carry ``camera_movement`` blocks,
            which the V2 validator governs; every V2 field this function writes
            lives inside the ``camera_profile == "v2"`` branch only.
        story_plan: The parsed Episode Story Plan the shot plan was cut from.
        camera_profile: ``"v1"`` (default) or ``"v2"``. V1 produces exactly the
            document this module produced before the V2 integration; V2 only
            additionally emits movement-camera identities on movement shots and
            binds the movement-catalogue digest.

    Returns:
        The complete, self-consistent render plan document.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If either document is invalid, they do not belong together,
            or the timeline does not support a coherent emission contract.
    """
    if camera_profile == "v2":
        from living_diorama.cinematic.cinematic_schema_v2 import validate_shot_direction_plan_v2

        validated = validate_shot_direction_plan_v2(shot_plan)
    else:
        validated = validate_shot_direction_plan(shot_plan)
    story = validate_episode_story_plan(story_plan)
    story_digest = sha256_hex(dumps_canonical(story, "episode story plan"))
    bound_story = cast(dict[str, JsonValue], validated["source"])["story_plan_sha256"]
    if story_digest != bound_story:
        raise ValueError(
            f"the supplied story plan hashes to {story_digest}, but the shot direction plan "
            f"was cut from {bound_story}; a render plan binds one episode's documents, "
            "never a mixed pair"
        )
    story_source = cast(dict[str, JsonValue], story["source"])
    current = cast(dict[str, JsonValue], story_source["current"])
    previous_export = story_source.get("previous")
    before_export = (
        None
        if previous_export is None
        else cast(dict[str, JsonValue], previous_export)["document_sha256"]
    )
    after_export = current["document_sha256"]
    shot_source = cast(dict[str, JsonValue], validated["source"])
    timeline = cast(dict[str, JsonValue], validated["timeline"])
    shots = [cast(dict[str, JsonValue], shot) for shot in cast(list[JsonValue], validated["shots"])]

    emission = derive_emission(cast(dict[str, object], timeline))
    plan_digest = sha256_hex(dumps_canonical(validated, "shot direction plan"))
    previous = shot_source.get("previous_episode")

    movement_binding: dict[str, JsonValue] = {}
    if camera_profile == "v2":
        movement_binding = {
            "movement_catalogue_sha256": movement_catalogue_sha256(validated),
        }

    frames: list[JsonValue] = []
    playback_frames = range(
        cast(int, emission["first_frame"]), cast(int, emission["final_frame"]) + 1
    )
    for frame in (*playback_frames, cast(int, emission["witness_frame"])):
        shot = _shot_at_frame(shots, frame)
        role = ROLE_WITNESS if frame == emission["witness_frame"] else ROLE_PLAYBACK
        camera_anchor_id: JsonValue = shot["camera_anchor_id"]
        if camera_profile == "v2" and _is_movement_shot(shot):
            camera_anchor_id = movement_camera_name(cast(str, shot["shot_id"]))
        frames.append(
            {
                "frame": frame,
                "role": role,
                "file": frame_filename(frame),
                "shot_id": shot["shot_id"],
                "camera_anchor_id": camera_anchor_id,
                "source_beat_ids": list(cast(list[JsonValue], shot["source_beat_ids"])),
            }
        )

    document: dict[str, JsonValue] = {
        "format": RENDER_PLAN_FORMAT,
        "schema_version": RENDER_PLAN_SCHEMA_VERSION,
        "source": {
            "shot_plan_format": validated["format"],
            "shot_plan_schema_version": validated["schema_version"],
            "shot_plan_sha256": plan_digest,
            "story_plan_sha256": shot_source["story_plan_sha256"],
            "motion_time_sha256": shot_source["motion_time_sha256"],
            "catalogue_sha256": shot_source["catalogue_sha256"],
            "before_export_sha256": before_export,
            "after_export_sha256": after_export,
            "render_profile_sha256": render_profile_sha256(),
            "episode": shot_source["episode"],
            "previous_episode": previous,
            "mode": shot_source["mode"],
            **movement_binding,
        },
        # The world is composed against the SAME clock the shot plan was cut
        # against, so a plan can never bind one Motion & Time document through
        # its direction and a different one through its composition sources.
        "composition_sources": cast(
            dict[str, JsonValue],
            composition_sources_document(
                motion_time_sha256=cast(str, shot_source["motion_time_sha256"])
            ),
        ),
        "timeline": dict(timeline),
        "emission": cast(dict[str, JsonValue], emission),
        "profile": cast(dict[str, JsonValue], render_profile_document()),
        "destination": {
            "render_id": render_id(
                mode=cast(str, shot_source["mode"]),
                episode=cast(int, shot_source["episode"]),
                previous_episode=None if previous is None else cast(int, previous),
            ),
            "frames_dir": FRAMES_DIRECTORY,
            "witness_dir": WITNESS_DIRECTORY,
        },
        "frames": frames,
    }
    return validate_episode_render_plan(document, camera_profile=camera_profile)


def build_episode_render_plan_bytes(
    shot_plan: object, story_plan: object, *, camera_profile: str = "v1"
) -> bytes:
    """Return the canonical bytes of one episode render plan."""
    return dumps_canonical(
        build_episode_render_plan_document(shot_plan, story_plan, camera_profile=camera_profile),
        "episode render plan",
    )


def load_episode_render_plan(data: bytes, *, camera_profile: str = "v1") -> dict[str, JsonValue]:
    """Parse and fully validate render plan bytes.

    Raises:
        TypeError: If the bytes do not decode to a document of the right shape.
        ValueError: If the document is not a valid episode render plan.
    """
    if type(data) is not bytes:
        raise TypeError(f"episode render plan bytes must be bytes, got {type(data).__name__}")
    return validate_episode_render_plan(
        loads_canonical(data, "episode render plan"), camera_profile=camera_profile
    )
