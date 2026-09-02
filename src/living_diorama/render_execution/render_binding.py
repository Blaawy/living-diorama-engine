"""Prove a render plan, its direction and its manifest are the same episode.

Three documents describe one render, and each of them validates on its own.
That is not enough. A document that is internally coherent has proved only that
nobody typed a contradiction into it; it has not proved that the fields it
copied out of an upstream document are the values that document actually holds,
or that the record of what a render produced still agrees with what the render
was asked to produce.

Those are relationship claims, and this module is where they are checked.

* :func:`require_render_plan_matches_shot_plan` -- every field the render plan
  copied or derived from Phase 22 agrees with the shot plan it names.
* :func:`require_shot_plan_bytes` -- the shot plan the caller holds is the exact
  file the render plan was built from, by raw bytes.
* :func:`require_manifest_matches_plan` -- the manifest contradicts its plan
  nowhere, while still being free to record what only a finished render knows.

**Why a separate module.** Standalone validation and relationship validation
answer different questions and must not be able to stand in for one another. A
render plan read off disk with no shot plan beside it can still be checked
completely against its own contract, and callers that only have the one document
keep that. What they no longer get is the *impression* of provenance: binding a
digest proves two documents were paired, never that the pairing was honest about
what it copied. Both are required, so both exist, separately named.

This module imports only the standard library and the locked engine contracts.
The Blender executor restates these relationships in the standard library alone,
on its own side of a boundary neither may cross, and a pure test drives both
implementations over the same mutations.
"""

import re
from typing import Final, cast

from living_diorama.cinematic.cinematic_schema_v1 import validate_shot_direction_plan
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import require_hash_hex, sha256_hex
from living_diorama.persistence.schema.world_schema_v1 import require_exact_keys, require_text
from living_diorama.render_execution.render_execution_schema_v1 import (
    ENVIRONMENT_KEYS,
    JsonValue,
    validate_episode_render_manifest,
    validate_episode_render_plan,
)
from living_diorama.render_execution.render_execution_spec import (
    CHECKPOINT_KEYS,
    FRAME_RESULT_FIELDS,
)

_FRAME_KEY_PATTERN: Final = re.compile(r"[0-9]+")
r"""ASCII digits only. A literal character class, never Unicode-aware ``\d``.

``str.isdigit()`` and ``int()`` both accept far more than this -- Arabic-Indic
digits, superscript digits, anything Unicode classifies as a decimal digit --
and both convert them to the number they represent. A checkpoint frame key is
not a number to be parsed permissively; it is meant to be one exact spelling,
because :func:`record_checkpoint` never writes anything else.
"""


def _require_canonical_frame_key(key: object, description: str) -> int:
    """Refuse a frame key that is not the one canonical spelling of its number.

    The only spelling this phase ever writes is ``str(frame)`` for a plain
    Python ``int`` -- no leading zero, no leading sign, no surrounding
    whitespace, no digit outside ASCII ``0``-``9``. Anything else reaching this
    function is either a hand-edited checkpoint or one two different tools wrote
    two different ways, and a resume that could not tell ``"01"`` from ``"1"``
    would silently treat them as the same frame -- which is a repair, not a
    refusal.

    Raises:
        ValueError: If the key is not ASCII digits, or is not the canonical
            spelling of the frame number it names.
    """
    if type(key) is not str or not _FRAME_KEY_PATTERN.fullmatch(key):
        raise ValueError(f"{description} names frame {key!r}, which is not a frame number")
    try:
        frame = int(key)
    except ValueError as error:
        # A digit string this long is refused for being unreasonable, not for
        # being unparseable -- restated as this function's own refusal so the
        # message names the field, matching every other line here.
        raise ValueError(
            f"{description} names frame {key!r}, which is not a frame number: {error}"
        ) from error
    if str(frame) != key:
        raise ValueError(
            f"{description} names frame {key!r}; the canonical spelling of frame {frame} is "
            f"{str(frame)!r}, and this phase never writes any other"
        )
    return frame


SHOT_PLAN_BOUND_SOURCE_KEYS: Final = (
    "story_plan_sha256",
    "motion_time_sha256",
    "catalogue_sha256",
    "mode",
    "episode",
    "previous_episode",
)
"""Every source field the render plan copies verbatim out of the shot plan.

Not a subset chosen for convenience: this is the whole intersection of the two
source blocks. The render plan's remaining bindings -- the two export digests,
the profile digest, the shot plan digest itself -- come from the story plan, from
this build, or are the pairing digest, and each is closed elsewhere.
"""

MANIFEST_EXCLUSIVE_SOURCE_KEYS: Final = frozenset({"render_plan_sha256"})
"""The only source field a manifest may hold that its plan does not.

A manifest names the plan it was written for; a plan cannot name a digest of
itself. Everything else in a manifest's source block is a copy, and a copy that
differs from its original is a lie rather than an addition.
"""

MANIFEST_EXCLUSIVE_FRAME_KEYS: Final = frozenset({"bytes", "sha256", "image_sha256"})
"""What a frame record may say that its planned counterpart could not.

These are measurements of a file that did not exist when the plan was written.
Every other field in a manifest frame record was copied from the plan, and is
required to still match it.
"""


def _plan_frame_direction(
    shot_plan: dict[str, JsonValue], frame: int
) -> tuple[str, str, list[str]]:
    """Return the shot id, camera and beats Phase 22 directs at one frame.

    The witness frame is derived exactly as every playback frame is. Phase 22's
    shots tile its whole timeline through ``end_frame`` inclusive, so the
    boundary frame has a directing shot like any other -- and deriving it rather
    than special-casing it is what stops the one frame nobody watches from
    becoming the one frame whose direction can be forged freely.

    Raises:
        ValueError: If no shot covers the frame.
    """
    for entry in cast(list[JsonValue], shot_plan["shots"]):
        shot = cast(dict[str, JsonValue], entry)
        if cast(int, shot["start_frame"]) <= frame <= cast(int, shot["end_frame"]):
            return (
                cast(str, shot["shot_id"]),
                cast(str, shot["camera_anchor_id"]),
                [cast(str, beat) for beat in cast(list[JsonValue], shot["source_beat_ids"])],
            )
    raise ValueError(
        f"frame {frame} is planned, but no shot in the bound direction covers it; Phase 23 "
        "renders no undirected frame"
    )


def require_render_plan_matches_shot_plan(
    render_plan: object, shot_plan: object, *, camera_profile: str = "v1"
) -> dict[str, JsonValue]:
    """Refuse unless the render plan agrees with the direction it names, everywhere.

    Both documents are validated on their own first, so a failure here is always
    a disagreement between two valid documents rather than a symptom of one
    being malformed.

    What is proved, in order: the shot plan is the one the render plan binds, by
    canonical digest; every source field the render plan copied out of it still
    holds that value; the timeline is the same timeline, key for key; and every
    single planned frame -- playback and witness alike -- names the shot, the
    camera and the beats that the shot windows actually put there.

    That last check is the one V2 lacked. Comparing shot id and camera while
    leaving ``source_beat_ids`` unread meant a render plan could attribute any
    frame to any beat, keep a valid shot plan digest, and be accepted -- which
    breaks the traceability the whole phase chain exists to provide.

    Args:
        render_plan: The parsed Episode Render Plan.
        shot_plan: The parsed Shot Direction Plan it names.
        camera_profile: ``"v1"`` (default) or ``"v2"``, threaded into the plan
            validator so a V2 plan carrying movement-camera identities and the
            movement-catalogue binding validates under the same profile it was
            built under.

    Returns:
        The validated render plan.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: On any disagreement between the two documents.
    """
    plan = validate_episode_render_plan(render_plan, camera_profile=camera_profile)
    direction = validate_shot_direction_plan(shot_plan)

    plan_source = cast(dict[str, JsonValue], plan["source"])
    shot_source = cast(dict[str, JsonValue], direction["source"])

    if plan_source["shot_plan_format"] != direction["format"]:
        raise ValueError(
            f"the render plan names shot plan format {plan_source['shot_plan_format']!r}, but "
            f"the supplied direction declares {direction['format']!r}"
        )
    if plan_source["shot_plan_schema_version"] != direction["schema_version"]:
        raise ValueError(
            f"the render plan names shot plan schema version "
            f"{plan_source['shot_plan_schema_version']!r}, but the supplied direction declares "
            f"{direction['schema_version']!r}"
        )

    observed = sha256_hex(dumps_canonical(direction, "shot direction plan"))
    if observed != plan_source["shot_plan_sha256"]:
        raise ValueError(
            f"the render plan was built for shot direction plan "
            f"{plan_source['shot_plan_sha256']!r}, but the supplied direction is {observed!r}; "
            "Phase 23 renders the episode it was planned for"
        )

    for key in SHOT_PLAN_BOUND_SOURCE_KEYS:
        if plan_source[key] != shot_source[key]:
            raise ValueError(
                f"the render plan binds {key} {plan_source[key]!r}, but the shot direction plan "
                f"it names holds {shot_source[key]!r}; a render plan copies its direction's "
                "identity and never restates it"
            )

    plan_timeline = cast(dict[str, JsonValue], plan["timeline"])
    shot_timeline = cast(dict[str, JsonValue], direction["timeline"])
    if dict(plan_timeline) != dict(shot_timeline):
        raise ValueError(
            f"the render plan restates timeline {dict(plan_timeline)!r}, but the direction it "
            f"was cut from holds {dict(shot_timeline)!r}; the two describe one episode on one "
            "clock, and a plan whose clock differs from its direction's is not that episode"
        )

    for position, entry in enumerate(cast(list[JsonValue], plan["frames"])):
        record = cast(dict[str, JsonValue], entry)
        frame = cast(int, record["frame"])
        shot_id, anchor, beats = _plan_frame_direction(direction, frame)
        if record["shot_id"] != shot_id:
            raise ValueError(
                f"render plan frames[{position}] attributes frame {frame} to shot "
                f"{record['shot_id']!r}, but the direction puts it in {shot_id!r}"
            )
        if record["camera_anchor_id"] != anchor:
            raise ValueError(
                f"render plan frames[{position}] renders frame {frame} through "
                f"{record['camera_anchor_id']!r}, but the direction points {anchor!r} at it"
            )
        if [cast(str, beat) for beat in cast(list[JsonValue], record["source_beat_ids"])] != beats:
            raise ValueError(
                f"render plan frames[{position}] traces frame {frame} to beats "
                f"{record['source_beat_ids']!r}, but the shot directing it was cut for {beats!r}; "
                "beat traceability is copied from the direction, never asserted beside it"
            )
    return plan


def require_shot_plan_bytes(
    render_plan: object, shot_plan_bytes: bytes, *, camera_profile: str = "v1"
) -> dict[str, JsonValue]:
    """Refuse unless these exact bytes are the shot plan the render plan was built from.

    The digest is taken over the bytes as they are, not over a re-serialization
    of what they parse to. Those are different claims. Canonicalising first would
    accept a pretty-printed copy, a copy with reordered keys, a copy with
    trailing whitespace -- documents that carry the same data written
    differently, and therefore documents whose own digest is not the one the
    render plan bound. Phase 23 renders the episode a specific reviewed file
    directed, and "the same data, differently written" is a different file.

    The bytes are then parsed and validated under Phase 22's own contract before
    anything is derived from them, and the full relationship check runs on the
    result -- so this one call is sufficient to accept a shot plan for rendering.

    Args:
        render_plan: The parsed Episode Render Plan.
        shot_plan_bytes: The shot plan file's exact bytes.
        camera_profile: ``"v1"`` (default) or ``"v2"``, threaded into the plan
            validator and the relationship check below.

    Returns:
        The validated render plan.

    Raises:
        TypeError: If the bytes are not bytes, or a value is of the wrong type.
        ValueError: If the bytes are not the bound shot plan, are not a valid
            Phase 22 document, or disagree with the render plan.
    """
    if type(shot_plan_bytes) is not bytes:
        raise TypeError(f"shot plan bytes must be bytes, got {type(shot_plan_bytes).__name__}")
    plan = validate_episode_render_plan(render_plan, camera_profile=camera_profile)
    bound = cast(dict[str, JsonValue], plan["source"])["shot_plan_sha256"]
    observed = sha256_hex(shot_plan_bytes)
    if observed != bound:
        raise ValueError(
            f"the supplied shot direction plan file hashes to {observed}, but the render plan "
            f"was built from {bound}; the binding is over the file's exact bytes, so a "
            "re-formatted or re-ordered copy of the same data is a different source"
        )
    # Parsed only after the bytes are proved to be the bound file, so a hostile
    # document never reaches Phase 22's parser on this path at all.
    from living_diorama.persistence.json_codec import loads_canonical

    direction = loads_canonical(shot_plan_bytes, "shot direction plan")
    return require_render_plan_matches_shot_plan(plan, direction, camera_profile=camera_profile)


def validate_render_checkpoint(
    checkpoint: object, render_plan: object, *, camera_profile: str = "v1"
) -> dict[str, JsonValue]:
    """Validate a resume checkpoint completely, against the plan it claims to be for.

    This is the standalone half, and it was the one missing from the
    independent audit. ``require_checkpoint_matches_manifest`` proves a
    checkpoint agrees with the manifest sitting beside it; it never opens the
    Render Plan, so a checkpoint whose ``render_plan_sha256`` or
    ``render_profile_sha256`` named an entirely different render -- while every
    frame record it carried stayed truthful -- passed the independent audit
    completely. The production executor has always checked a checkpoint against
    the actual plan; the independent half now does too, through this function,
    called separately alongside the relationship check rather than folded into
    it. Standalone validation and relationship validation answer different
    questions, for the same reason the module docstring gives for every other
    pair of functions here.

    Args:
        checkpoint: The parsed render checkpoint.
        render_plan: The parsed Episode Render Plan it claims to describe.
        camera_profile: ``"v1"`` (default) or ``"v2"``, threaded into the plan
            validator so a V2 plan is re-validated under the same profile it
            was built under.

    Returns:
        The checkpoint's frame records, keyed by semantic frame number.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: On any violation, or any disagreement with the plan.
    """
    plan = validate_episode_render_plan(render_plan, camera_profile=camera_profile)
    plan_digest = sha256_hex(dumps_canonical(plan, "episode render plan"))

    if type(checkpoint) is not dict:
        raise TypeError("render checkpoint must be a JSON object")
    require_exact_keys(cast(dict[str, JsonValue], checkpoint), CHECKPOINT_KEYS, "render checkpoint")

    if checkpoint["render_plan_sha256"] != plan_digest:
        raise ValueError(
            f"the checkpoint is for render plan {checkpoint['render_plan_sha256']!r}, but the "
            f"plan beside it is {plan_digest!r}"
        )
    expected_profile = cast(dict[str, JsonValue], plan["source"])["render_profile_sha256"]
    if checkpoint["render_profile_sha256"] != expected_profile:
        raise ValueError(
            f"the checkpoint was rendered under profile {checkpoint['render_profile_sha256']!r}, "
            f"but its own plan binds {expected_profile!r}; frames from two profiles are never "
            "mixed into one episode"
        )

    environment = checkpoint["environment"]
    if type(environment) is not dict:
        raise TypeError("render checkpoint environment must be a JSON object")
    require_exact_keys(
        cast(dict[str, JsonValue], environment), ENVIRONMENT_KEYS, "render checkpoint environment"
    )
    for key in sorted(ENVIRONMENT_KEYS):
        require_text(environment.get(key), f"render checkpoint environment {key}")

    frames = checkpoint["frames"]
    if type(frames) is not dict:
        raise TypeError("render checkpoint frames must be a JSON object")
    planned = {
        cast(int, cast(dict[str, JsonValue], entry)["frame"])
        for entry in cast(list[JsonValue], plan["frames"])
    }
    resolved: dict[str, JsonValue] = {}
    seen: set[int] = set()
    for key, entry in frames.items():
        frame = _require_canonical_frame_key(key, "render checkpoint")
        if frame in seen:
            raise ValueError(f"render checkpoint records frame {frame} twice")
        seen.add(frame)
        if frame not in planned:
            raise ValueError(
                f"the render checkpoint vouches for frame {frame}, which this plan never asked for"
            )
        if type(entry) is not dict:
            raise TypeError(f"render checkpoint record for frame {frame} is not an object")
        require_exact_keys(
            cast(dict[str, JsonValue], entry),
            frozenset(FRAME_RESULT_FIELDS),
            f"render checkpoint frame {frame}",
        )
        size = entry["bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise TypeError(f"render checkpoint frame {frame} bytes must be a positive int")
        require_hash_hex(entry.get("sha256"), f"render checkpoint frame {frame} sha256")
        require_hash_hex(entry.get("image_sha256"), f"render checkpoint frame {frame} image_sha256")
        resolved[key] = cast(JsonValue, entry)
    return resolved


def require_checkpoint_matches_manifest(
    checkpoint: object, manifest: object, *, camera_profile: str = "v1"
) -> dict[str, JsonValue]:
    """Refuse a checkpoint that contradicts the manifest sitting beside it.

    Both documents record what a render produced, frame by frame, and a
    directory holding two records that disagree about one file has no truthful
    reading. The production executor enforces the same agreement before it will
    reuse a frame; this is the independent half, which trusts neither document
    and reads both.

    Only frames the two have in common are compared. A checkpoint from an
    interrupted run legitimately holds fewer frames than a finished manifest --
    that is what resuming means -- but where both speak about a frame they must
    say the same thing about it.

    Args:
        checkpoint: The parsed render checkpoint.
        manifest: The parsed Episode Render Manifest.
        camera_profile: ``"v1"`` (default) or ``"v2"``, threaded into the
            manifest validator.

    Returns:
        The checkpoint's frame records, keyed by semantic frame number.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: On any contradiction, or a malformed checkpoint.
    """
    if type(checkpoint) is not dict:
        raise TypeError("render checkpoint must be a JSON object")
    require_exact_keys(cast(dict[str, JsonValue], checkpoint), CHECKPOINT_KEYS, "render checkpoint")
    frames = checkpoint["frames"]
    if type(frames) is not dict:
        raise TypeError("render checkpoint frames must be a JSON object")

    record = validate_episode_render_manifest(manifest, camera_profile=camera_profile)
    recorded = {
        cast(int, cast(dict[str, JsonValue], entry)["frame"]): cast(dict[str, JsonValue], entry)
        for entry in cast(list[JsonValue], record["frames"])
    }

    resolved: dict[str, JsonValue] = {}
    for key, entry in frames.items():
        frame = _require_canonical_frame_key(key, "render checkpoint")
        if type(entry) is not dict:
            raise TypeError(f"render checkpoint record for frame {frame} is not an object")
        require_exact_keys(
            cast(dict[str, JsonValue], entry),
            frozenset(FRAME_RESULT_FIELDS),
            f"render checkpoint frame {frame}",
        )
        counterpart = recorded.get(frame)
        if counterpart is None:
            raise ValueError(
                f"the render checkpoint vouches for frame {frame}, which the manifest beside it "
                "never records"
            )
        differing = sorted(
            field for field in FRAME_RESULT_FIELDS if entry[field] != counterpart[field]
        )
        if differing:
            detail = ", ".join(
                f"{field}: checkpoint {entry[field]!r} vs manifest {counterpart[field]!r}"
                for field in differing
            )
            raise ValueError(
                f"the checkpoint and the manifest disagree about frame {frame} ({detail}); a "
                "render directory that contradicts itself is refused"
            )
        resolved[key] = cast(JsonValue, entry)

    environment = checkpoint["environment"]
    if environment != record["environment"]:
        raise ValueError(
            f"the checkpoint was written by {environment!r} and the manifest by "
            f"{record['environment']!r}; one render directory holds one execution environment"
        )
    return resolved


def require_manifest_matches_plan(
    manifest: object, render_plan: object, *, camera_profile: str = "v1"
) -> dict[str, JsonValue]:
    """Refuse unless the manifest tells the truth about the plan it names.

    A manifest binds its plan by digest, and V2 checked that binding. But the
    manifest also *copies* most of the plan into itself -- the whole source
    block, the emission contract, the composition sources, and six fields of
    every frame record -- and a copy that was never compared to its original is
    an unchecked assertion. A manifest could keep ``render_plan_sha256``
    untouched, name a different episode, a different world, a different camera
    on a frame, and validate perfectly against its own contract.

    So every copied field is compared. The manifest keeps exactly the freedom it
    needs: it may say what a finished render measured -- a file's length, its
    two digests, the environment, the completion verdict -- because the plan
    could not have known those. It may not disagree about anything the plan
    already said.

    Args:
        manifest: The parsed Episode Render Manifest.
        render_plan: The parsed Episode Render Plan it claims to describe.
        camera_profile: ``"v1"`` (default) or ``"v2"``, threaded into both
            validators so a V2 pair is re-validated under the same profile it
            was built under.

    Returns:
        The validated manifest.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: On any contradiction between the two documents.
    """
    record = validate_episode_render_manifest(manifest, camera_profile=camera_profile)
    plan = validate_episode_render_plan(render_plan, camera_profile=camera_profile)

    plan_digest = sha256_hex(dumps_canonical(plan, "episode render plan"))
    manifest_source = dict(cast(dict[str, JsonValue], record["source"]))
    # Set aside exactly the fields a manifest is entitled to hold alone, so the
    # comparison below covers everything else by construction rather than by a
    # list somebody remembered to keep in step.
    exclusive = {key: manifest_source.pop(key) for key in MANIFEST_EXCLUSIVE_SOURCE_KEYS}
    bound = exclusive["render_plan_sha256"]
    if bound != plan_digest:
        raise ValueError(
            f"the manifest binds render plan {bound!r}, but the plan supplied beside it is "
            f"{plan_digest!r}"
        )

    plan_source = dict(cast(dict[str, JsonValue], plan["source"]))
    if manifest_source != plan_source:
        differing = sorted(
            key
            for key in set(manifest_source) | set(plan_source)
            if manifest_source.get(key) != plan_source.get(key)
        )
        raise ValueError(
            f"the manifest's source disagrees with its own render plan on {differing}; a "
            "manifest records what a render produced and restates the identity it was produced "
            "under, never a different one"
        )

    for block in ("emission", "composition_sources"):
        if dict(cast(dict[str, JsonValue], record[block])) != dict(
            cast(dict[str, JsonValue], plan[block])
        ):
            raise ValueError(
                f"the manifest's {block} disagrees with its own render plan; the render was "
                "executed from that plan and cannot have obeyed a different one"
            )

    planned = {
        cast(int, cast(dict[str, JsonValue], entry)["frame"]): cast(dict[str, JsonValue], entry)
        for entry in cast(list[JsonValue], plan["frames"])
    }
    for position, entry in enumerate(cast(list[JsonValue], record["frames"])):
        actual = cast(dict[str, JsonValue], entry)
        frame = cast(int, actual["frame"])
        expected = planned.get(frame)
        if expected is None:
            raise ValueError(
                f"manifest frames[{position}] records frame {frame}, which its render plan never "
                "accounted for"
            )
        for key in sorted(set(expected) - MANIFEST_EXCLUSIVE_FRAME_KEYS):
            if actual[key] != expected[key]:
                raise ValueError(
                    f"manifest frames[{position}] records frame {frame} {key} {actual[key]!r}, "
                    f"but the plan it was rendered from says {expected[key]!r}"
                )
    if len(cast(list[JsonValue], record["frames"])) != len(planned):
        raise ValueError(
            f"the manifest records {len(cast(list[JsonValue], record['frames']))} frames but its "
            f"plan accounts for {len(planned)}"
        )
    return record
