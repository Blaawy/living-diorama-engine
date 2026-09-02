"""Episode Render Plan and Episode Render Manifest formats V1.

A render plan says exactly which frames a render will produce, on which
camera, into which file, under which profile, for which directed episode. A
render manifest says what a render actually produced, with a digest per file.
Between them they make it impossible to hold a directory of images and be
unsure which episode it is, whether it is finished, or whether it is the one
the plan asked for.

The document shape is exact at every level this module governs -- a missing
key means the document is incomplete, an extra key means it was written by
something this contract does not describe, and both are refused rather than
repaired.

This module imports only the standard library, the ``living_diorama``
validation vocabulary, and Phase 22's cinematic contract, which it consumes
read-only. It never imports ``bpy`` and never reaches into live simulation.

V2 mode (``camera_profile="v2"``) is strictly additive and strictly
conditional. The V1 path -- the default, and the only path the pre-V2 code
knew -- validates byte-for-byte the same documents it always did: no V2 field
is ever accepted outside a ``camera_profile == "v2"`` branch.
"""

from collections.abc import Mapping
from typing import Final, cast

from living_diorama.cinematic import cinematic_spec
from living_diorama.cinematic.cinematic_schema_v1 import SHOT_PLAN_FORMAT
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import require_hash_hex, sha256_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_text,
)
from living_diorama.render_execution.render_execution_spec import (
    APPROVED_COMPOSITION_SOURCE_SETS,
    COMPOSITION_SOURCE_KEYS,
    FRAME_ROLES,
    RENDER_MANIFEST_FORMAT,
    RENDER_MANIFEST_SCHEMA_VERSION,
    RENDER_PLAN_FORMAT,
    RENDER_PLAN_SCHEMA_VERSION,
    REVIEWED_CLOCKS,
    ROLE_PLAYBACK,
    ROLE_WITNESS,
    SUPPORTED_SHOT_PLAN_SCHEMA_VERSION,
    WITNESS_DIFFERENCE_TOLERANCE,
    derive_emission,
    frame_filename,
    render_id,
    render_profile_sha256,
)

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in."""

EPISODE_MODES: Final = frozenset({"baseline", "transition"})
"""The two shapes an episode identity can take, mirroring Phase 22's."""

PLAN_TOP_LEVEL_KEYS: Final = frozenset(
    {
        "format",
        "schema_version",
        "source",
        "composition_sources",
        "timeline",
        "emission",
        "profile",
        "destination",
        "frames",
    }
)
"""Exactly the keys an episode render plan carries."""

PLAN_SOURCE_KEYS: Final = frozenset(
    {
        "shot_plan_format",
        "shot_plan_schema_version",
        "shot_plan_sha256",
        "story_plan_sha256",
        "motion_time_sha256",
        "catalogue_sha256",
        "before_export_sha256",
        "after_export_sha256",
        "render_profile_sha256",
        "episode",
        "previous_episode",
        "mode",
    }
)
"""The complete provenance chain a render plan binds itself to.

Everything needed to say which directed episode this render is of, which
world it is composed from, and under which presentation contract -- each one
a digest or an identity copied from a locked upstream document, never
re-derived here.

The two export digests are what make the chain reach all the way down. A
render plan alone could otherwise name an episode while the renderer was
handed the wrong exports to compose, and the frames would be of a different
world than the direction they claim.

Under V2 only, the source may additionally carry ``movement_catalogue_sha256``,
the digest of the plan's derived movement-camera catalogue. The key is
OPTIONAL even in V2 (a plan with no movement shots has no catalogue to bind),
and it is never accepted in V1 mode.
"""

MOVEMENT_CATALOGUE_SOURCE_KEY: Final = "movement_catalogue_sha256"
"""The optional V2-only source key binding a plan's movement-camera catalogue."""

TIMELINE_KEYS: Final = frozenset(
    {
        "fps",
        "start_frame",
        "end_frame",
        "start_hold_frames",
        "transition_frames",
        "end_hold_frames",
        "transition_start",
        "transition_end",
    }
)
"""Phase 17's clock, copied verbatim from the shot plan."""

EMISSION_KEYS: Final = frozenset(
    {
        "first_frame",
        "final_frame",
        "frame_count",
        "witness_frame",
        "playback_fps",
        "playback_seconds",
    }
)
"""The frame emission contract this render obeys."""

DESTINATION_KEYS: Final = frozenset({"render_id", "frames_dir", "witness_dir"})
"""Where the render lands, relative to a root the plan never names."""

PLAN_FRAME_KEYS: Final = frozenset(
    {"frame", "role", "file", "shot_id", "camera_anchor_id", "source_beat_ids"}
)
"""One planned frame: its number, its role, its file, and its direction."""

MANIFEST_TOP_LEVEL_KEYS: Final = frozenset(
    {
        "format",
        "schema_version",
        "source",
        "composition_sources",
        "emission",
        "environment",
        "frames",
        "completeness",
    }
)
"""Exactly the keys an episode render manifest carries.

``composition_sources`` is here for the same reason it is in the plan, and its
absence was a real hole. A manifest is the document downstream layers are handed
-- editing, audio, encoding read it, not the plan beside it -- and without this
block a manifest could name its episode, its direction and every file it
produced while saying nothing about which world was photographed. It would have
to be trusted to have been written from a plan nobody re-read.
"""

MANIFEST_SOURCE_KEYS: Final = PLAN_SOURCE_KEYS | {"render_plan_sha256"}
"""A manifest binds everything the plan bound, plus the plan itself."""

ENVIRONMENT_KEYS: Final = frozenset({"blender_version", "engine", "device"})
"""What a reader needs to interpret the pixels.

Deliberately small and deliberately honest: these are the facts that decide
whether another machine could be expected to reproduce these bytes, recorded
so nobody has to guess.
"""

MANIFEST_FRAME_KEYS: Final = PLAN_FRAME_KEYS | {"bytes", "sha256", "image_sha256"}
"""One rendered frame: everything planned, plus what landed on disk.

Two digests, because they answer different questions. ``sha256`` is the
file, and identifies exactly the bytes that exist. ``image_sha256`` covers the
decompressed image stream alone, so it changes when the picture changes and
not when only Blender's embedded render date does -- which is what makes it
useful to an auditor deciding whether a frame was replaced or merely
re-stamped. Neither digest is a reproducibility claim: see the phase
documentation, which records what re-rendering actually measures.
"""

COMPLETENESS_KEYS: Final = frozenset(
    {
        "playback_frames_expected",
        "playback_frames_rendered",
        "witness_frames_rendered",
        "witness_mean_abs_difference",
        "witness_within_tolerance",
        "complete",
    }
)
"""The aggregate verdict, stated in a way a partial render cannot fake."""


def _require_document(value: object, description: str) -> dict[str, JsonValue]:
    """Return the value if it is exactly a dict with string keys, else raise.

    Raises:
        TypeError: If the value is not a dict or a key is not a string.
    """
    if type(value) is not dict:
        raise TypeError(f"{description} must be a JSON object, got {type(value).__name__}")
    for key in value:
        if type(key) is not str:
            raise TypeError(f"{description} has a non-string key {key!r}")
    return cast(dict[str, JsonValue], value)


def _require_sequence(value: object, description: str) -> list[JsonValue]:
    """Return the value if it is exactly a list, else raise.

    Raises:
        TypeError: If the value is not a list.
    """
    if type(value) is not list:
        raise TypeError(f"{description} must be a JSON array, got {type(value).__name__}")
    return cast(list[JsonValue], value)


def _require_filename(value: object, description: str) -> str:
    """Return a plain file name carrying no path structure at all.

    A frame's file name is joined onto a directory this phase owns, so anything
    that could climb out of it -- a separator, a parent reference, a drive
    letter, an absolute root -- is refused here rather than sanitised later.

    Raises:
        TypeError: If the value is not a str.
        ValueError: If it is blank or carries any path structure.
    """
    name = require_text(value, description)
    if "/" in name or "\\" in name:
        raise ValueError(f"{description} {name!r} must not contain a path separator")
    if ".." in name:
        raise ValueError(f"{description} {name!r} must not reference a parent directory")
    if name.startswith("."):
        raise ValueError(f"{description} {name!r} must be an ordinary file name")
    if ":" in name:
        raise ValueError(f"{description} {name!r} must not name a drive or stream")
    return name


def _validate_episode_identity(source: dict[str, JsonValue], description: str) -> tuple[str, int]:
    """Validate the mode/episode/previous_episode triple, returning mode and episode.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the identity is not a coherent baseline or transition.
    """
    mode = require_text(source.get("mode"), f"{description} mode")
    if mode not in EPISODE_MODES:
        raise ValueError(f"{description} mode {mode!r} is not one of {sorted(EPISODE_MODES)}")
    episode = require_exact_int(source.get("episode"), f"{description} episode")
    previous = source.get("previous_episode")
    before_export = source.get("before_export_sha256")
    if mode == "baseline":
        if previous is not None:
            raise ValueError(f"{description} is a baseline but names previous_episode {previous!r}")
        if before_export is not None:
            raise ValueError(
                f"{description} is a baseline but binds a before export; a baseline holds one "
                "state and has nothing to transition from"
            )
    else:
        previous_episode = require_exact_int(previous, f"{description} previous_episode")
        if episode != previous_episode + 1:
            raise ValueError(
                f"{description} episode {episode} does not directly follow {previous_episode}"
            )
        require_hash_hex(before_export, f"{description} before_export_sha256")
    return mode, episode


def _validate_source(
    document: dict[str, JsonValue],
    keys: frozenset[str],
    description: str,
    *,
    movement_catalogue_allowed: bool = False,
) -> dict[str, JsonValue]:
    """Validate a plan or manifest source block and return it.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If a binding is malformed or the profile digest is not the
            one this build renders under.
    """
    source = _require_document(document.get("source"), f"{description} source")
    expected_keys = keys
    if movement_catalogue_allowed and MOVEMENT_CATALOGUE_SOURCE_KEY in source:
        expected_keys = keys | {MOVEMENT_CATALOGUE_SOURCE_KEY}
    require_exact_keys(source, expected_keys, f"{description} source")

    shot_format = require_text(source.get("shot_plan_format"), f"{description} shot_plan_format")
    if shot_format != SHOT_PLAN_FORMAT:
        raise ValueError(
            f"{description} names shot plan format {shot_format!r}; Phase 23 renders "
            f"{SHOT_PLAN_FORMAT!r} and refuses to guess at another contract"
        )
    shot_version = require_exact_int(
        source.get("shot_plan_schema_version"), f"{description} shot_plan_schema_version"
    )
    if shot_version != SUPPORTED_SHOT_PLAN_SCHEMA_VERSION:
        raise ValueError(
            f"{description} names shot plan schema version {shot_version}; this build renders "
            f"version {SUPPORTED_SHOT_PLAN_SCHEMA_VERSION} only"
        )
    digest_keys = (
        "shot_plan_sha256",
        "story_plan_sha256",
        "motion_time_sha256",
        "catalogue_sha256",
        "after_export_sha256",
        "render_profile_sha256",
        *(("render_plan_sha256",) if "render_plan_sha256" in keys else ()),
    )
    if movement_catalogue_allowed and MOVEMENT_CATALOGUE_SOURCE_KEY in source:
        digest_keys = digest_keys + (MOVEMENT_CATALOGUE_SOURCE_KEY,)
    for digest_key in digest_keys:
        require_hash_hex(source.get(digest_key), f"{description} {digest_key}")

    expected_profile = render_profile_sha256()
    if source.get("render_profile_sha256") != expected_profile:
        raise ValueError(
            f"{description} was produced under render profile "
            f"{source.get('render_profile_sha256')!r}, but this build renders under "
            f"{expected_profile!r}; a render carries the profile it was made with and is "
            "never reinterpreted under another"
        )
    _validate_episode_identity(source, description)
    return source


def _validate_timeline(document: dict[str, JsonValue], description: str) -> dict[str, int]:
    """Validate the copied Phase 17 clock and return it as integers.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the clock does not agree with its own arithmetic.
    """
    timeline = _require_document(document.get("timeline"), f"{description} timeline")
    require_exact_keys(timeline, TIMELINE_KEYS, f"{description} timeline")
    resolved = {
        key: require_exact_int(timeline.get(key), f"{description} timeline {key}")
        for key in sorted(TIMELINE_KEYS)
    }
    expected_transition_start = resolved["start_frame"] + resolved["start_hold_frames"]
    expected_transition_end = expected_transition_start + resolved["transition_frames"]
    expected_end = expected_transition_end + resolved["end_hold_frames"]
    if (
        resolved["transition_start"] != expected_transition_start
        or resolved["transition_end"] != expected_transition_end
        or resolved["end_frame"] != expected_end
    ):
        raise ValueError(
            f"{description} timeline disagrees with its own phases: "
            f"{resolved['start_frame']} + {resolved['start_hold_frames']} + "
            f"{resolved['transition_frames']} + {resolved['end_hold_frames']} implies "
            f"{expected_transition_start}..{expected_transition_end}..{expected_end}, but the "
            f"document declares {resolved['transition_start']}..{resolved['transition_end']}.."
            f"{resolved['end_frame']}"
        )
    return resolved


def _validate_emission(
    document: dict[str, JsonValue], timeline: dict[str, int], description: str
) -> dict[str, object]:
    """Validate the emission block against the contract derived from the clock.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the declared emission is not the one the clock implies.
    """
    emission = _require_document(document.get("emission"), f"{description} emission")
    require_exact_keys(emission, EMISSION_KEYS, f"{description} emission")
    for key in ("first_frame", "final_frame", "frame_count", "witness_frame", "playback_fps"):
        require_exact_int(emission.get(key), f"{description} emission {key}")
    seconds = emission.get("playback_seconds")
    if type(seconds) is not float:
        raise TypeError(f"{description} emission playback_seconds must be a float, got {seconds!r}")

    expected = derive_emission(timeline)
    if dict(emission) != expected:
        raise ValueError(
            f"{description} declares emission {dict(emission)!r}, but the bound timeline "
            f"implies {expected!r}; Phase 23 emits the frames its clock accounts for and "
            "invents no others"
        )
    return expected


def _validate_frame_records(
    records: list[JsonValue],
    *,
    keys: frozenset[str],
    emission: Mapping[str, object],
    description: str,
    camera_profile: str = "v1",
) -> list[dict[str, JsonValue]]:
    """Validate an ordered frame list shared by both documents.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the frames are not exactly the emitted set, in order,
            each with its canonical name and a distinct file.
    """
    if not records:
        raise ValueError(f"{description} lists no frames; a render with no frames is not one")
    validated: list[dict[str, JsonValue]] = []
    seen_files: set[str] = set()
    expected_frames = [
        *range(cast(int, emission["first_frame"]), cast(int, emission["final_frame"]) + 1),
        cast(int, emission["witness_frame"]),
    ]
    if len(records) != len(expected_frames):
        raise ValueError(
            f"{description} lists {len(records)} frames, but the emission contract accounts "
            f"for {len(expected_frames)} ({emission['frame_count']} playback frames and one "
            "witness)"
        )
    for position, entry in enumerate(records):
        where = f"{description} frames[{position}]"
        record = _require_document(entry, where)
        require_exact_keys(record, keys, where)
        frame = require_exact_int(record.get("frame"), f"{where} frame")
        if frame != expected_frames[position]:
            raise ValueError(
                f"{where} is frame {frame}, but the emitted sequence expects "
                f"{expected_frames[position]}; frames are listed once each, in order, with "
                "none missing and none repeated"
            )
        role = require_text(record.get("role"), f"{where} role")
        if role not in FRAME_ROLES:
            raise ValueError(f"{where} role {role!r} is not one of {sorted(FRAME_ROLES)}")
        expected_role = ROLE_WITNESS if frame == emission["witness_frame"] else ROLE_PLAYBACK
        if role != expected_role:
            raise ValueError(
                f"{where} declares role {role!r}, but frame {frame} is a {expected_role} frame"
            )
        name = _require_filename(record.get("file"), f"{where} file")
        expected_name = frame_filename(frame)
        if name != expected_name:
            raise ValueError(
                f"{where} names file {name!r}; frame {frame} is written as {expected_name!r} "
                "and the naming contract is not negotiable per frame"
            )
        if name in seen_files:
            raise ValueError(f"{where} reuses file name {name!r}; every frame owns its own file")
        seen_files.add(name)

        require_text(record.get("shot_id"), f"{where} shot_id")
        anchor = require_text(record.get("camera_anchor_id"), f"{where} camera_anchor_id")
        if anchor not in cinematic_spec.ANCHOR_NAMES:
            # V2 only: a frame of a movement shot may carry the derived movement
            # camera identity, re-derived here from the frame's OWN shot id so a
            # forged identity that does not match its shot is still refused. The
            # ANCHOR_NAMES check above is never replaced, only supplemented.
            movement_identity = (
                camera_profile == "v2"
                and anchor == cinematic_spec.movement_camera_name(cast(str, record.get("shot_id")))
            )
            if not movement_identity:
                raise ValueError(
                    f"{where} names camera anchor {anchor!r}, which is not an approved anchor; "
                    "Phase 23 renders the cameras Phase 22 selected and knows no others"
                )
        beats = _require_sequence(record.get("source_beat_ids"), f"{where} source_beat_ids")
        seen_beats: set[str] = set()
        for index, beat in enumerate(beats):
            beat_id = require_text(beat, f"{where} source_beat_ids[{index}]")
            if beat_id in seen_beats:
                raise ValueError(
                    f"{where} names beat {beat_id!r} twice; a frame's beat traceability is a "
                    "set of distinct beats, and a repeated id is a corrupted copy rather than "
                    "a stronger claim"
                )
            seen_beats.add(beat_id)
        if "bytes" in keys:
            size = require_exact_int(record.get("bytes"), f"{where} bytes")
            if size < 1:
                raise ValueError(f"{where} records {size} bytes; an empty frame is not a frame")
            require_hash_hex(record.get("sha256"), f"{where} sha256")
            require_hash_hex(record.get("image_sha256"), f"{where} image_sha256")
        validated.append(record)
    return validated


def _validate_composition_sources(
    document: dict[str, JsonValue], source: dict[str, JsonValue], description: str
) -> dict[str, JsonValue]:
    """Validate the pinned world bindings a plan or a manifest carries.

    Shared by both documents deliberately. The manifest copies this block from
    the plan, and a second implementation of the same rules is how two copies of
    one truth start disagreeing.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If the sources are not the reviewed locked documents, or
            name a different clock than the document's own source block does.
    """
    sources = _require_document(
        document.get("composition_sources"), f"{description} composition_sources"
    )
    require_exact_keys(
        sources, frozenset(COMPOSITION_SOURCE_KEYS), f"{description} composition_sources"
    )
    for key in sorted(COMPOSITION_SOURCE_KEYS):
        require_hash_hex(sources.get(key), f"{description} composition_sources {key}")
    if not any(dict(sources) == dict(approved) for approved in APPROVED_COMPOSITION_SOURCE_SETS):
        raise ValueError(
            f"{description} names composition sources that are not one of the reviewed "
            "locked bundles; the world a render is built from is pinned, not supplied"
        )
    if sources["motion_time_sha256"] != source["motion_time_sha256"]:
        raise ValueError(
            f"{description} binds one Motion Time document through its shot plan and a "
            "different one through its composition sources"
        )
    return sources


def _require_canonical_clock(
    source: dict[str, JsonValue], timeline: dict[str, int], description: str
) -> None:
    """Refuse a timeline that is not what the bound Motion & Time source resolves to.

    A clock that closes on its own arithmetic has proved only that it is
    *a* clock. ``1 + 25 + 119 + 48`` closes on frame 193 exactly as the locked
    ``1 + 24 + 120 + 48`` does, emits the same 192 playback frames, and runs the
    same 8.0 seconds -- so every other rule in this contract would hold for a
    document that restated an alternate timeline while still binding the
    canonical Phase 17 digest it never re-derived. The plan would claim one
    clock and its provenance chain another, and nothing would say so.

    The values a render plan carries are copies, not sources. When the bound
    Motion & Time identity is the locked one, the only timeline that identity
    resolves to is the pinned one, and any other is a hand-edited copy.

    Raises:
        ValueError: If the bound clock is canonical but the timeline is not.
    """
    bound = source.get("motion_time_sha256")
    reviewed = REVIEWED_CLOCKS.get(cast(str, bound))
    if reviewed is None:
        return
    expected = dict(reviewed)
    if timeline != expected:
        raise ValueError(
            f"{description} binds the reviewed Phase 17 Motion & Time Spec "
            f"{bound}, which resolves to {expected!r}, but restates "
            f"{timeline!r}; a timeline is copied from the clock it names, and a self-consistent "
            "alternative under a reviewed digest is a hand-edited clock rather than a "
            "second reading of the same one"
        )


def validate_episode_render_plan(
    document: object, *, camera_profile: str = "v1"
) -> dict[str, JsonValue]:
    """Validate one episode render plan, exactly.

    Args:
        document: The parsed plan document.
        camera_profile: ``"v1"`` (default) or ``"v2"``. V2 only accepts the
            optional ``movement_catalogue_sha256`` source key and movement
            camera identities derived from a frame's own shot id; V1 accepts
            neither.

    Returns:
        The same document, once every rule holds.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If any rule of the contract is broken.
    """
    plan = _require_document(document, "episode render plan")
    require_exact_keys(plan, PLAN_TOP_LEVEL_KEYS, "episode render plan")

    declared_format = require_text(plan.get("format"), "episode render plan format")
    if declared_format != RENDER_PLAN_FORMAT:
        raise ValueError(
            f"episode render plan declares format {declared_format!r}, expected "
            f"{RENDER_PLAN_FORMAT!r}"
        )
    version = require_exact_int(plan.get("schema_version"), "episode render plan schema_version")
    if version != RENDER_PLAN_SCHEMA_VERSION:
        raise ValueError(
            f"episode render plan declares schema version {version}; this build reads version "
            f"{RENDER_PLAN_SCHEMA_VERSION} only"
        )

    source = _validate_source(
        plan,
        PLAN_SOURCE_KEYS,
        "episode render plan",
        movement_catalogue_allowed=camera_profile == "v2",
    )
    timeline = _validate_timeline(plan, "episode render plan")
    _require_canonical_clock(source, timeline, "episode render plan")
    emission = _validate_emission(plan, timeline, "episode render plan")

    _validate_composition_sources(plan, source, "episode render plan")

    profile = _require_document(plan.get("profile"), "episode render plan profile")
    observed_profile = sha256_hex(dumps_canonical(profile, "episode render plan profile"))
    if observed_profile != render_profile_sha256():
        raise ValueError(
            f"episode render plan carries render profile {observed_profile}, but this build "
            f"renders under {render_profile_sha256()}; the profile is pinned by digest and "
            "copied verbatim, never edited in place"
        )

    destination = _require_document(plan.get("destination"), "episode render plan destination")
    require_exact_keys(destination, DESTINATION_KEYS, "episode render plan destination")
    for key in sorted(DESTINATION_KEYS):
        _require_filename(destination.get(key), f"episode render plan destination {key}")
    previous = source.get("previous_episode")
    expected_id = render_id(
        mode=cast(str, source["mode"]),
        episode=cast(int, source["episode"]),
        previous_episode=None if previous is None else cast(int, previous),
    )
    if destination.get("render_id") != expected_id:
        raise ValueError(
            f"episode render plan declares render_id {destination.get('render_id')!r}, but its "
            f"own episode identity derives {expected_id!r}"
        )

    frames = _require_sequence(plan.get("frames"), "episode render plan frames")
    _validate_frame_records(
        frames,
        keys=PLAN_FRAME_KEYS,
        emission=emission,
        description="episode render plan",
        camera_profile=camera_profile,
    )
    return plan


def validate_episode_render_manifest(
    document: object, *, camera_profile: str = "v1"
) -> dict[str, JsonValue]:
    """Validate one episode render manifest, exactly.

    A manifest that validates says something strong: every frame the plan
    accounted for exists, carries its digests, and is claimed to have been
    rendered by the environment named here. It cannot claim completeness while
    omitting a frame, and it cannot reach a boundary verdict its own measured
    difference does not support.

    Args:
        document: The parsed manifest document.
        camera_profile: ``"v1"`` (default) or ``"v2"``, threaded identically to
            :func:`validate_episode_render_plan`.

    Returns:
        The same document, once every rule holds.

    Raises:
        TypeError: If a value is of the wrong exact type.
        ValueError: If any rule of the contract is broken.
    """
    manifest = _require_document(document, "episode render manifest")
    require_exact_keys(manifest, MANIFEST_TOP_LEVEL_KEYS, "episode render manifest")

    declared_format = require_text(manifest.get("format"), "episode render manifest format")
    if declared_format != RENDER_MANIFEST_FORMAT:
        raise ValueError(
            f"episode render manifest declares format {declared_format!r}, expected "
            f"{RENDER_MANIFEST_FORMAT!r}"
        )
    version = require_exact_int(
        manifest.get("schema_version"), "episode render manifest schema_version"
    )
    if version != RENDER_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"episode render manifest declares schema version {version}; this build reads "
            f"version {RENDER_MANIFEST_SCHEMA_VERSION} only"
        )

    manifest_source = _validate_source(
        manifest,
        MANIFEST_SOURCE_KEYS,
        "episode render manifest",
        movement_catalogue_allowed=camera_profile == "v2",
    )
    _validate_composition_sources(manifest, manifest_source, "episode render manifest")

    emission = _require_document(manifest.get("emission"), "episode render manifest emission")
    require_exact_keys(emission, EMISSION_KEYS, "episode render manifest emission")
    resolved_emission = {key: emission[key] for key in sorted(EMISSION_KEYS) if key in emission}
    for key in ("first_frame", "final_frame", "frame_count", "witness_frame", "playback_fps"):
        require_exact_int(emission.get(key), f"episode render manifest emission {key}")
    if type(emission.get("playback_seconds")) is not float:
        raise TypeError("episode render manifest emission playback_seconds must be a float")
    expected_seconds = round(
        cast(int, emission["frame_count"]) / cast(int, emission["playback_fps"]), 6
    )
    if emission.get("playback_seconds") != expected_seconds:
        raise ValueError(
            f"episode render manifest claims {emission.get('playback_seconds')!r} seconds for "
            f"{emission['frame_count']} frames at {emission['playback_fps']} fps, which is "
            f"{expected_seconds!r}"
        )
    span = cast(int, emission["final_frame"]) - cast(int, emission["first_frame"]) + 1
    if span != emission["frame_count"]:
        raise ValueError(
            f"episode render manifest spans frames {emission['first_frame']}.."
            f"{emission['final_frame']} ({span} frames) but claims a frame count of "
            f"{emission['frame_count']}"
        )
    if emission["witness_frame"] != cast(int, emission["final_frame"]) + 1:
        raise ValueError(
            "episode render manifest witness frame must be the frame directly after the final "
            "playback frame"
        )

    environment = _require_document(
        manifest.get("environment"), "episode render manifest environment"
    )
    require_exact_keys(environment, ENVIRONMENT_KEYS, "episode render manifest environment")
    for key in sorted(ENVIRONMENT_KEYS):
        require_text(environment.get(key), f"episode render manifest environment {key}")

    frames = _require_sequence(manifest.get("frames"), "episode render manifest frames")
    records = _validate_frame_records(
        frames,
        keys=MANIFEST_FRAME_KEYS,
        emission=resolved_emission,
        description="episode render manifest",
        camera_profile=camera_profile,
    )

    completeness = _require_document(
        manifest.get("completeness"), "episode render manifest completeness"
    )
    require_exact_keys(completeness, COMPLETENESS_KEYS, "episode render manifest completeness")
    for key in (
        "playback_frames_expected",
        "playback_frames_rendered",
        "witness_frames_rendered",
    ):
        require_exact_int(completeness.get(key), f"episode render manifest completeness {key}")
    for key in ("complete", "witness_within_tolerance"):
        if type(completeness.get(key)) is not bool:
            raise TypeError(
                f"episode render manifest completeness {key} must be a bool, got "
                f"{completeness.get(key)!r}"
            )
    difference = completeness.get("witness_mean_abs_difference")
    if type(difference) is not float:
        raise TypeError(
            "episode render manifest completeness witness_mean_abs_difference must be "
            f"a float, got {difference!r}"
        )
    if difference < 0.0:
        raise ValueError(
            "episode render manifest reports a negative difference between its witness "
            "and its final playback frame"
        )

    playback = [record for record in records if record.get("role") == ROLE_PLAYBACK]
    witness = [record for record in records if record.get("role") == ROLE_WITNESS]
    if completeness["playback_frames_expected"] != emission["frame_count"]:
        raise ValueError(
            "episode render manifest expects a different number of playback frames than its "
            "own emission contract accounts for"
        )
    if completeness["playback_frames_rendered"] != len(playback):
        raise ValueError(
            f"episode render manifest claims {completeness['playback_frames_rendered']} "
            f"playback frames rendered but records {len(playback)}"
        )
    if completeness["witness_frames_rendered"] != len(witness):
        raise ValueError(
            f"episode render manifest claims {completeness['witness_frames_rendered']} witness "
            f"frames rendered but records {len(witness)}"
        )
    expected_complete = (
        len(playback) == emission["frame_count"]
        and len(witness) == 1
        and difference <= WITNESS_DIFFERENCE_TOLERANCE
    )
    if completeness["complete"] != expected_complete:
        raise ValueError(
            "episode render manifest's completeness verdict does not follow from its own "
            "records: a complete render has every playback frame, exactly one witness, and a "
            "witness inside tolerance"
        )

    if completeness["witness_within_tolerance"] != (difference <= WITNESS_DIFFERENCE_TOLERANCE):
        raise ValueError(
            f"episode render manifest measures {difference} between its witness and its "
            f"final playback frame but reaches the opposite verdict about the "
            f"{WITNESS_DIFFERENCE_TOLERANCE} tolerance; the verdict is computed from the "
            "measurement, never asserted alongside it"
        )
    if witness and not playback:
        raise ValueError("episode render manifest records a witness frame but no playback frames")
    return manifest
