r"""Render one directed episode into its frame assets, and prove what it made.

This is the production execution entry point, not a proof producer. It stands
the locked world up, binds Phase 22's cuts, applies the Phase 23 render
profile, and photographs exactly the frames the Episode Render Plan accounts
for -- one file per semantic frame, each verified and digested as it lands.

REFUSE, NEVER REPAIR. A drifted profile, a camera that is not the directed one
at the frame being rendered, a leftover file nobody planned, a frame whose
bytes do not match what was recorded: each of those stops the render and says
what it found. Nothing is silently overwritten, nothing is deleted outside the
one temporary directory this script owns, and no manifest is written unless
every planned frame exists and verifies.

The script imports ``bpy`` and the locked Blender-side layers. It never
imports the engine package: the render plan and the camera catalogue arrive as
data, exactly as Phase 22's applier receives its catalogue, and the profile
digest is recomputed here with the standard library so both sides can agree
without either reaching across the boundary.

Usage::

    blender --background --factory-startup --python render_episode.py -- \\
        --render-plan episode_render_plan.json --shot-plan shot_plan.json \\
        --catalogue catalogue.json --spec master_scene_v1.json \\
        --production production_world_v1.json --motion motion_time_v1.json \\
        --presence population_presence_v1.json \\
        --mobility daily_life_mobility_v1.json \\
        --state-response state_response_v1.json \\
        --before before.json --after after.json --output-root renders/
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import zlib
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:  # pragma: no cover - import-path bootstrap
    sys.path.insert(0, str(SCRIPTS_DIR))

RENDER_PLAN_FORMAT = "living_diorama_episode_render_plan"
"""The only plan format this executor renders."""

RENDER_PROFILE_SHA256 = "5ae46db5be152a7a3d9c9457ab7eaa6f31024aa2363f63fdfa456e750d9ced61"
"""The render profile this build executes, pinned absolutely.

Restated here rather than imported, exactly as Phase 22's applier restates the
approved camera catalogue digest: the plan supplies the profile as data, and a
plan whose profile is not the approved one is refused whatever the file says
about itself. A matching forged pair -- edited profile plus edited binding --
cannot help it, because the comparison is against this constant first.
"""

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
"""The eight bytes every PNG begins with."""

FRAMES_DIRECTORY = "frames"
WITNESS_DIRECTORY = "witness"
PARTIAL_DIRECTORY = ".partial"
RENDER_PLAN_FILENAME = "episode_render_plan.json"
RENDER_MANIFEST_FILENAME = "episode_render_manifest.json"
RENDER_CHECKPOINT_FILENAME = "render_checkpoint.json"
WITNESS_DIFFERENCE_TOLERANCE = 1.0
RENDER_NOISE_TOLERANCE = 0.5
"""Restated from the engine spec; see docs/episode_render_execution.md."""


def canonical_bytes(document: object) -> bytes:
    """Return the project's canonical JSON encoding of a document.

    Mirrors ``living_diorama.persistence.json_codec.dumps_canonical`` using the
    standard library alone, so the Blender side can verify a digest the engine
    computed without importing the engine.
    """
    return (
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def sha256_hex(payload: bytes) -> str:
    """Return the lowercase hexadecimal SHA-256 digest of some bytes."""
    return hashlib.sha256(payload).hexdigest()


def read_json_document(path: Path, description: str) -> dict:
    """Read one JSON object from disk, refusing anything else.

    Raises:
        ValueError: If the file is not a JSON object or repeats a key.
    """
    data = Path(path).read_bytes()

    def _no_duplicates(pairs: list) -> dict:
        seen: dict = {}
        for key, value in pairs:
            if key in seen:
                raise ValueError(f"{description} repeats the key {key!r}")
            seen[key] = value
        return seen

    document = json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates)
    if type(document) is not dict:
        raise ValueError(f"{description} must be a JSON object")
    return document


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------


def require_render_plan(plan: dict) -> dict:
    """Validate a render plan completely. Kept as the historic entry point.

    V1 had a weaker check here that verified only the format tag and the
    profile digest, and an independent reviewer walked straight through it with
    a plan missing a frame and a plan whose frame name climbed out of the
    render directory. There is now exactly one validator, and this name
    delegates to it so no caller can reach a lenient path by accident.

    Raises:
        PlanRefused: On any violation of the Episode Render Plan contract.
    """
    return require_valid_render_plan(plan)


APPROVED_COMPOSITION_SOURCES = {
    "master_scene_sha256": "cb840ac0243582f2ef28c55c4f36f7368f2241b205835fccd5fc9048b4a7ea91",
    "production_world_sha256": "6906b8cbaa385d0df86eec9586b92ebc2990a2a2ca168e31ba7d98049e88e246",
    "motion_time_sha256": "bfcbfcfd8d2b33f0ca8a0bc51655a1028babc601a73cdd42ca3c8caf3f9da673",
    "population_presence_sha256": (
        "55bb06c794587d1a8bfb7238b6dc540f0071c916a9f0f95642c0d381b4cd4e75"
    ),
    "daily_life_mobility_sha256": (
        "9ca56cc6fe3c1f10b497d90e1b283e91bc64a5d4f989db8e4346b6aea0e92364"
    ),
    "state_response_sha256": "89b561472ead2c2c7704e0b506ea242c4e92f9afd8f90374a164c3362230ce78",
}
"""Every locked document the composed world is built from, pinned absolutely.

Restated here rather than imported, exactly as the render profile digest is:
the plan supplies these as data, and a plan naming any other world is refused
whatever it says about itself.
"""

PLAN_TOP_LEVEL_KEYS = frozenset(
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
PLAN_SOURCE_KEYS = frozenset(
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
TIMELINE_KEYS = frozenset(
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
EMISSION_KEYS = frozenset(
    {
        "first_frame",
        "final_frame",
        "frame_count",
        "witness_frame",
        "playback_fps",
        "playback_seconds",
    }
)
DESTINATION_KEYS = frozenset({"render_id", "frames_dir", "witness_dir"})
FRAME_KEYS = frozenset({"frame", "role", "file", "shot_id", "camera_anchor_id", "source_beat_ids"})
WRITING_SUFFIX = ".writing"
"""The suffix the atomic writer gives a document while it is still being written."""

RENDER_DIRECTORY_ENTRIES = frozenset(
    {
        RENDER_PLAN_FILENAME,
        RENDER_MANIFEST_FILENAME,
        RENDER_CHECKPOINT_FILENAME,
        FRAMES_DIRECTORY,
        WITNESS_DIRECTORY,
    }
)
"""Everything a finished render directory may contain, at its top level.

Restated from the engine spec, and pinned equal to it by a pure test, for the
reason every other restated constant here exists: this side may not import the
engine, and two sides that disagree about what a valid directory is have no
boundary between them. An independent reviewer proved they did disagree --
dropping ``evil.txt`` into a finished render left the production survey calling
it complete while the independent verifier for the same phase refused it.
"""


def classify_render_directory_entry(name, is_directory=False):
    """Say what a top-level entry in a render directory is.

    Three answers, and the difference between the last two decides whether a
    human should go looking for an intruder:

    * ``"owned"`` -- one of the five entries a finished render owns.
    * ``"partial"`` -- this phase's own litter from an interrupted run: the
      ``.partial`` scratch *directory*, or a ``.writing`` temporary of one of
      the documents this phase writes atomically. Recoverable, and not evidence
      of anything hostile, but proof the directory is not finished.
    * ``"foreign"`` -- anything else.

    The name alone is not enough to tell those apart. A file called
    ``evil.writing`` is not this phase's debris, and neither is a *directory*
    called ``x.writing``; both were classified as owned litter when this matched
    on the suffix by itself. So a ``.writing`` entry counts as ours only when it
    is a file whose remaining name is a document this phase actually writes, and
    ``.partial`` counts only when it is a directory.

    Nothing is deleted on the strength of this. It decides what the refusal says.
    """
    if name in RENDER_DIRECTORY_ENTRIES:
        return "owned"
    if name == PARTIAL_DIRECTORY:
        return "partial" if is_directory else "foreign"
    if not is_directory and name.endswith(WRITING_SUFFIX):
        written = name[: -len(WRITING_SUFFIX)]
        if written in {RENDER_PLAN_FILENAME, RENDER_MANIFEST_FILENAME, RENDER_CHECKPOINT_FILENAME}:
            return "partial"
    return "foreign"


SHOT_PLAN_FORMAT = "living_diorama_shot_direction_plan"
HEX_DIGITS = frozenset("0123456789abcdef")

APPROVED_CAMERA_ANCHORS = frozenset(
    {
        "CAM_HERO_SCAR",
        "CAM_HERO_WORLD",
        "CAM_P16_COMPOSITION",
        "CAM_P16_CORE_CONTEXT",
        "CAM_P16_DENSITY",
        "CAM_P16_ROADS",
        "CAM_P16_SCAR_CONTEXT",
        "CAM_P16_SYSTEM",
        "CAM_P16_URBAN",
        "CAM_P16_VALIDITY",
        "CAM_P16_WORLD_HERO",
        "CAM_SCAR_DETAIL",
        "CAM_SEAL_DETAIL",
        "CAM_VERIFY_TOPOLOGY",
    }
)
"""Every camera Phase 22 may direct, restated as data.

An independent reviewer walked a plan naming ``camera_anchor_id = "BANANA"``
straight through this validator, because the only rule here was "a non-blank
string". Checking the plan against its own shot plan did not help: a forged pair
agrees with itself. The engine has always refused an unapproved anchor by
membership, so this side must too, and it cannot import the engine to do it --
so the set is restated, exactly as the render profile digest and the composition
sources above it are, and a pure test proves this frozenset equals
``cinematic_spec.ANCHOR_NAMES``.
"""

CANONICAL_MOTION_TIME_SHA256 = "bfcbfcfd8d2b33f0ca8a0bc51655a1028babc601a73cdd42ca3c8caf3f9da673"
CANONICAL_RESOLVED_TIMELINE = {
    "end_frame": 193,
    "end_hold_frames": 48,
    "fps": 24,
    "start_frame": 1,
    "start_hold_frames": 24,
    "transition_end": 145,
    "transition_frames": 120,
    "transition_start": 25,
}
"""The locked clock and what it resolves to, restated beside each other.

``1 + 25 + 119 + 48`` closes on frame 193 exactly as the locked
``1 + 24 + 120 + 48`` does, so a render plan could restate an alternate clock,
keep the canonical Motion & Time digest, and satisfy every arithmetic rule
below. Phase 22's own applier pins the identical dict for this reason; the
executor pins it too, because a render plan's timeline is a copy of a source and
never a second reading of it.
"""

MAXIMUM_SEMANTIC_FRAME = 9999
"""The largest frame the four-digit naming field can hold, as the engine's."""


class PlanRefused(ValueError):
    """A render plan this executor will not act on."""


def _exact_keys(document, expected, description):
    """Refuse a mapping that is missing a key or carries an unexpected one."""
    if type(document) is not dict:
        raise PlanRefused(f"{description} must be a JSON object")
    observed = set(document)
    missing = sorted(expected - observed)
    extra = sorted(observed - expected)
    if missing:
        raise PlanRefused(f"{description} is missing required keys: {missing}")
    if extra:
        raise PlanRefused(f"{description} carries unexpected keys: {extra}")


def _exact_int(value, description, *, minimum=None):
    """Refuse anything that is not an exact int -- ``True`` is not a number here.

    ``minimum`` mirrors the engine's ``require_exact_int``, which refuses a
    negative where a count or an index is expected. Without it this side accepted
    ``previous_episode = -1, episode = 0`` as a "direct succession" and derived
    the directory name ``episode_-001_to_0000`` from it.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanRefused(f"{description} must be an int, got {value!r}")
    if minimum is not None and value < minimum:
        raise PlanRefused(f"{description} must be at least {minimum}, got {value}")
    return value


def _digest(value, description):
    """Refuse anything that is not 64 lowercase hexadecimal characters."""
    if type(value) is not str or len(value) != 64 or not set(value) <= HEX_DIGITS:
        raise PlanRefused(f"{description} must be a lowercase 64-character digest, got {value!r}")
    return value


def _plain_name(value, description):
    """Refuse any string carrying path structure of any kind.

    This is the check whose absence let a plan name ``../../owned.png`` and
    have the executor build a destination outside its own directory.
    """
    if type(value) is not str or not value or value != value.strip():
        raise PlanRefused(f"{description} must be a non-blank name, got {value!r}")
    if "/" in value or "\\" in value:
        raise PlanRefused(f"{description} {value!r} must not contain a path separator")
    if ".." in value:
        raise PlanRefused(f"{description} {value!r} must not reference a parent directory")
    if ":" in value:
        raise PlanRefused(f"{description} {value!r} must not name a drive or stream")
    if value.startswith("."):
        raise PlanRefused(f"{description} {value!r} must be an ordinary name")
    return value


def require_valid_render_plan(plan):
    """Validate every load-bearing rule of Episode Render Plan V1, closed.

    The engine owns this contract, and the engine's validator is the reference
    implementation -- but the Blender side may not import the engine, and a
    production boundary that trusts a document because "the planner should have
    built it" is not a boundary. So the contract is restated here in the
    standard library, and a pure test drives both implementations over the same
    mutations to prove they refuse the same things.

    Nothing is written to disk before this returns.

    Raises:
        PlanRefused: On any violation, naming what was wrong.
    """
    _exact_keys(plan, PLAN_TOP_LEVEL_KEYS, "render plan")
    if plan["format"] != RENDER_PLAN_FORMAT:
        raise PlanRefused(f"expected a {RENDER_PLAN_FORMAT!r} document, got {plan['format']!r}")
    if _exact_int(plan["schema_version"], "render plan schema_version") != 1:
        raise PlanRefused(f"unsupported render plan schema version {plan['schema_version']}")

    # --- source
    source = plan["source"]
    _exact_keys(source, PLAN_SOURCE_KEYS, "render plan source")
    if source["shot_plan_format"] != SHOT_PLAN_FORMAT:
        raise PlanRefused(f"render plan names shot plan format {source['shot_plan_format']!r}")
    if _exact_int(source["shot_plan_schema_version"], "shot_plan_schema_version") != 1:
        raise PlanRefused("render plan names an unsupported shot plan schema version")
    for key in (
        "shot_plan_sha256",
        "story_plan_sha256",
        "motion_time_sha256",
        "catalogue_sha256",
        "after_export_sha256",
        "render_profile_sha256",
    ):
        _digest(source[key], f"render plan source {key}")
    mode = source["mode"]
    episode = _exact_int(source["episode"], "render plan source episode", minimum=0)
    previous = source["previous_episode"]
    if mode == "baseline":
        if previous is not None:
            raise PlanRefused("a baseline render plan names a previous episode")
        if source["before_export_sha256"] is not None:
            raise PlanRefused("a baseline render plan binds a before export")
        expected_id = f"episode_{episode:04d}_baseline"
    elif mode == "transition":
        previous = _exact_int(previous, "render plan source previous_episode", minimum=0)
        if episode != previous + 1:
            raise PlanRefused(f"episode {episode} does not directly follow {previous}")
        _digest(source["before_export_sha256"], "render plan source before_export_sha256")
        expected_id = f"episode_{previous:04d}_to_{episode:04d}"
    else:
        raise PlanRefused(f"unknown episode mode {mode!r}")
    if source["render_profile_sha256"] != RENDER_PROFILE_SHA256:
        raise PlanRefused("the render plan's profile binding is not the approved profile digest")

    # --- composition sources, pinned absolutely
    sources = plan["composition_sources"]
    _exact_keys(sources, frozenset(APPROVED_COMPOSITION_SOURCES), "render plan composition_sources")
    for key, expected in sorted(APPROVED_COMPOSITION_SOURCES.items()):
        if _digest(sources[key], f"composition_sources {key}") != expected:
            raise PlanRefused(
                f"render plan names composition source {key} {sources[key]}, but this build "
                f"composes from {expected}"
            )
    if sources["motion_time_sha256"] != source["motion_time_sha256"]:
        raise PlanRefused("the render plan binds two different Motion Time documents")

    # --- profile, absolutely
    profile = plan["profile"]
    if type(profile) is not dict:
        raise PlanRefused("the render plan carries no render profile")
    observed_profile = sha256_hex(canonical_bytes(profile))
    if observed_profile != RENDER_PROFILE_SHA256:
        raise PlanRefused(
            f"the render plan carries render profile {observed_profile}, but this build renders "
            f"under {RENDER_PROFILE_SHA256}; the profile decides what the pixels mean and is "
            "never taken from the document being executed"
        )

    # --- timeline
    timeline = plan["timeline"]
    _exact_keys(timeline, TIMELINE_KEYS, "render plan timeline")
    clock = {
        key: _exact_int(timeline[key], f"timeline {key}", minimum=1 if key == "fps" else 0)
        for key in sorted(TIMELINE_KEYS)
    }
    if (
        clock["transition_start"] != clock["start_frame"] + clock["start_hold_frames"]
        or clock["transition_end"] != clock["transition_start"] + clock["transition_frames"]
        or clock["end_frame"] != clock["transition_end"] + clock["end_hold_frames"]
    ):
        raise PlanRefused("the render plan's timeline disagrees with its own phases")
    if source["motion_time_sha256"] == CANONICAL_MOTION_TIME_SHA256 and (
        clock != CANONICAL_RESOLVED_TIMELINE
    ):
        raise PlanRefused(
            f"the render plan binds the canonical Phase 17 clock, which resolves to "
            f"{CANONICAL_RESOLVED_TIMELINE}, but restates {clock}; a self-consistent "
            "alternative under the canonical digest is a hand-edited clock"
        )

    # --- emission, derived from the clock rather than believed
    emission = plan["emission"]
    _exact_keys(emission, EMISSION_KEYS, "render plan emission")
    for key in ("first_frame", "final_frame", "frame_count", "witness_frame", "playback_fps"):
        _exact_int(emission[key], f"emission {key}")
    if type(emission["playback_seconds"]) is not float:
        raise PlanRefused("emission playback_seconds must be a float")
    phases = clock["start_hold_frames"] + clock["transition_frames"] + clock["end_hold_frames"]
    if phases < 1:
        raise PlanRefused(f"a timeline emitting {phases} frames has no episode in it")
    if clock["start_frame"] < 1 or clock["end_frame"] > MAXIMUM_SEMANTIC_FRAME:
        raise PlanRefused(
            f"the render plan spans frames {clock['start_frame']}..{clock['end_frame']}, which "
            f"does not fit the four-digit naming field (1..{MAXIMUM_SEMANTIC_FRAME})"
        )
    expected_emission = {
        "first_frame": clock["start_frame"],
        "final_frame": clock["end_frame"] - 1,
        "frame_count": phases,
        "witness_frame": clock["end_frame"],
        "playback_fps": clock["fps"],
        "playback_seconds": round(phases / clock["fps"], 6),
    }
    if dict(emission) != expected_emission:
        raise PlanRefused(
            f"the render plan declares emission {dict(emission)}, but its own clock implies "
            f"{expected_emission}"
        )

    # --- destination
    destination = plan["destination"]
    _exact_keys(destination, DESTINATION_KEYS, "render plan destination")
    for key in sorted(DESTINATION_KEYS):
        _plain_name(destination[key], f"render plan destination {key}")
    if destination["render_id"] != expected_id:
        raise PlanRefused(
            f"the render plan declares render_id {destination['render_id']!r}, but its episode "
            f"identity derives {expected_id!r}"
        )

    # --- frames: exactly the emitted set, in order, each named canonically
    frames = plan["frames"]
    if type(frames) is not list or not frames:
        raise PlanRefused("the render plan lists no frames")
    expected_frames = [
        *range(expected_emission["first_frame"], expected_emission["final_frame"] + 1),
        expected_emission["witness_frame"],
    ]
    if len(frames) != len(expected_frames):
        raise PlanRefused(
            f"the render plan lists {len(frames)} frames, but its emission accounts for "
            f"{len(expected_frames)}"
        )
    seen_files = set()
    for position, entry in enumerate(frames):
        where = f"render plan frames[{position}]"
        _exact_keys(entry, FRAME_KEYS, where)
        frame = _exact_int(entry["frame"], f"{where} frame")
        if frame != expected_frames[position]:
            raise PlanRefused(
                f"{where} is frame {frame}, but the emitted sequence expects "
                f"{expected_frames[position]}"
            )
        expected_role = "witness" if frame == expected_emission["witness_frame"] else "playback"
        if entry["role"] != expected_role:
            raise PlanRefused(
                f"{where} declares role {entry['role']!r}, expected {expected_role!r}"
            )
        name = _plain_name(entry["file"], f"{where} file")
        canonical_name = f"frame_{frame:04d}.png"
        if name != canonical_name:
            raise PlanRefused(
                f"{where} names file {name!r}; frame {frame} is written as {canonical_name!r}"
            )
        if name in seen_files:
            raise PlanRefused(f"{where} reuses file name {name!r}")
        seen_files.add(name)
        for key in ("shot_id", "camera_anchor_id"):
            value = entry[key]
            if type(value) is not str or not value or value != value.strip():
                raise PlanRefused(f"{where} {key} must be a non-blank name, got {value!r}")
        if entry["camera_anchor_id"] not in APPROVED_CAMERA_ANCHORS:
            raise PlanRefused(
                f"{where} names camera anchor {entry['camera_anchor_id']!r}, which is not an "
                "approved anchor; Phase 23 renders the cameras Phase 22 selected and knows "
                "no others"
            )
        beats = entry["source_beat_ids"]
        if type(beats) is not list:
            raise PlanRefused(f"{where} source_beat_ids must be a list, got {beats!r}")
        seen_beats = set()
        for beat in beats:
            if type(beat) is not str or not beat or beat != beat.strip():
                raise PlanRefused(f"{where} source_beat_ids holds {beat!r}, not a name")
            if beat in seen_beats:
                raise PlanRefused(f"{where} names beat {beat!r} twice")
            seen_beats.add(beat)
    return plan


SHOT_PLAN_BOUND_SOURCE_KEYS = (
    "story_plan_sha256",
    "motion_time_sha256",
    "catalogue_sha256",
    "mode",
    "episode",
    "previous_episode",
)
"""Every source field the render plan copies verbatim out of the shot plan."""


def require_plan_matches_direction(plan, shot_plan):
    """Kept as the historic entry point; delegates to the complete check.

    V2 compared shot id and camera per frame and nothing else, and an
    independent reviewer walked a plan whose ``source_beat_ids`` said
    ``["FAKE_BEAT"]`` straight through it. There is now one relationship
    validator and this name reaches it, so no caller lands on the narrow path.

    Raises:
        PlanRefused: On any disagreement with the direction.
    """
    return require_plan_matches_shot_plan(plan, shot_plan)


def require_plan_matches_shot_plan(plan, shot_plan):
    """Refuse unless the render plan agrees with its direction, everywhere.

    Binding a shot plan by digest proves the two documents were paired. It does
    not prove the render plan copied honestly out of the one it named -- and
    almost everything in a render plan is a copy: the story, clock and catalogue
    it was cut against, the episode identity, the whole timeline, and three
    fields of every one of the 193 frame records.

    So all of it is compared. The witness frame is derived from the shot windows
    exactly as every playback frame is, because the one frame nobody watches
    must not be the one frame whose direction can be written freely.

    The engine owns this contract and its validator is the reference
    implementation, but this side may not import the engine, so the rules are
    restated in the standard library and a pure test drives both over the same
    mutations.

    Raises:
        PlanRefused: On any disagreement between the two documents.
    """
    shots = shot_plan.get("shots")
    if type(shots) is not list or not shots:
        raise PlanRefused("the shot direction plan lists no shots")

    source = plan["source"]
    shot_source = shot_plan.get("source")
    if type(shot_source) is not dict:
        raise PlanRefused("the shot direction plan carries no source block")
    if source["shot_plan_format"] != shot_plan.get("format"):
        raise PlanRefused(
            f"the render plan names shot plan format {source['shot_plan_format']!r}, but the "
            f"supplied direction declares {shot_plan.get('format')!r}"
        )
    if source["shot_plan_schema_version"] != shot_plan.get("schema_version"):
        raise PlanRefused(
            "the render plan names a shot plan schema version the supplied direction does "
            "not declare"
        )
    for key in SHOT_PLAN_BOUND_SOURCE_KEYS:
        if key not in shot_source:
            raise PlanRefused(f"the shot direction plan carries no {key}")
        if source[key] != shot_source[key]:
            raise PlanRefused(
                f"the render plan binds {key} {source[key]!r}, but the direction it names holds "
                f"{shot_source[key]!r}; a render plan copies its direction's identity"
            )

    if dict(plan["timeline"]) != dict(shot_plan.get("timeline") or {}):
        raise PlanRefused(
            f"the render plan restates timeline {dict(plan['timeline'])}, but the direction it "
            f"was cut from holds {shot_plan.get('timeline')}"
        )

    directed = {}
    for shot in shots:
        for frame in range(shot["start_frame"], shot["end_frame"] + 1):
            directed[frame] = (
                shot["shot_id"],
                shot["camera_anchor_id"],
                list(shot["source_beat_ids"]),
            )
    for entry in plan["frames"]:
        expected = directed.get(entry["frame"])
        if expected is None:
            raise PlanRefused(
                f"frame {entry['frame']} is planned but no shot directs it; Phase 23 renders no "
                "undirected frame"
            )
        shot_id, anchor, beats = expected
        if (entry["shot_id"], entry["camera_anchor_id"]) != (shot_id, anchor):
            raise PlanRefused(
                f"frame {entry['frame']} is planned on {entry['camera_anchor_id']!r} in shot "
                f"{entry['shot_id']!r}, but the direction says {anchor!r} in {shot_id!r}"
            )
        if list(entry["source_beat_ids"]) != beats:
            raise PlanRefused(
                f"frame {entry['frame']} traces to beats {entry['source_beat_ids']!r}, but the "
                f"shot directing it was cut for {beats!r}; beat traceability is copied from the "
                "direction, never asserted beside it"
            )
    return plan


def require_shot_plan_bytes(plan, shot_plan_bytes):
    """Refuse unless these exact bytes are the shot plan the plan was built from.

    The digest is over the bytes as they are, not over a re-serialisation of
    what they parse to. Those are different claims: canonicalising first accepts
    a pretty-printed copy, a copy with reordered keys, a copy with trailing
    whitespace -- the same data written differently, and therefore a file whose
    own digest is not the one the render plan bound. Phase 23 renders the
    episode a specific reviewed file directed.

    Raises:
        PlanRefused: If the bytes are not the bound shot plan.
    """
    observed = sha256_hex(shot_plan_bytes)
    declared = plan["source"]["shot_plan_sha256"]
    if observed != declared:
        raise PlanRefused(
            f"the supplied shot direction plan file hashes to {observed}, but the render plan "
            f"was built from {declared}; the binding is over the file's exact bytes, so a "
            "re-formatted or re-ordered copy of the same data is a different source"
        )
    return plan


def require_approved_catalogue(plan, catalogue):
    """Refuse a camera catalogue that is not the one this render was planned for.

    Phase 22's applier remains the authority on camera authenticity and performs
    the same check again over the composed scene; this is a preflight, not a
    replacement. It exists because composing the world takes minutes and
    discovering a catalogue mismatch afterwards wastes all of them -- and
    because nothing should be built at all for a render that cannot legally
    finish.

    The digest is over the catalogue's CANONICAL serialisation, exactly as
    Phase 22 computes it: the catalogue's values are load-bearing and its
    on-disk formatting is not.

    Raises:
        PlanRefused: If the catalogue is not the approved one the plan binds.
    """
    if type(catalogue) is not dict:
        raise PlanRefused("the camera catalogue must be a JSON object")
    observed = sha256_hex(canonical_bytes(catalogue))
    declared = plan["source"]["catalogue_sha256"]
    if observed != declared:
        raise PlanRefused(
            f"the supplied camera catalogue hashes to {observed}, but this render was planned "
            f"for catalogue {declared}"
        )
    return catalogue


def apply_render_profile(bpy_module, profile: dict) -> dict:
    """Set the settings Phase 23 owns; refuse the ones it must not touch.

    The owned half is applied. The inherited half -- colour management from the
    Phase 15 world build, the clock from Phase 17 -- is checked and never
    written: a scene whose look or clock is not the reviewed one is not this
    episode, and overriding it from inside a render command would hide that.

    Args:
        bpy_module: The Blender module.
        profile: The profile document from the render plan.

    Returns:
        What was applied and what was verified, for the manifest's environment.

    Raises:
        RuntimeError: If an inherited setting disagrees with the profile.
    """
    owned = profile["owned"]
    verified = profile["verified"]
    scene = bpy_module.context.scene
    render = scene.render
    image = render.image_settings

    render.engine = owned["engine"]
    render.resolution_x = owned["resolution_x"]
    render.resolution_y = owned["resolution_y"]
    render.resolution_percentage = owned["resolution_percentage"]
    render.pixel_aspect_x = owned["pixel_aspect_x"]
    render.pixel_aspect_y = owned["pixel_aspect_y"]
    render.film_transparent = owned["film_transparent"]
    render.use_motion_blur = owned["use_motion_blur"]
    render.use_file_extension = False
    render.use_overwrite = True
    render.use_placeholder = False
    image.file_format = owned["file_format"]
    image.color_mode = owned["color_mode"]
    image.color_depth = owned["color_depth"]
    image.compression = owned["compression"]

    cycles = scene.cycles
    cycles.use_adaptive_sampling = owned["cycles_adaptive_sampling"]
    cycles.samples = owned["cycles_samples"]
    cycles.adaptive_threshold = owned["cycles_adaptive_threshold"]
    cycles.use_denoising = owned["cycles_use_denoising"]
    cycles.denoiser = owned["cycles_denoiser"]
    cycles.denoising_input_passes = owned["cycles_denoising_input_passes"]
    cycles.max_bounces = owned["cycles_max_bounces"]
    cycles.volume_bounces = owned["cycles_volume_bounces"]
    cycles.transparent_max_bounces = owned["cycles_transparent_max_bounces"]
    cycles.seed = owned["cycles_seed"]
    cycles.use_animated_seed = owned["cycles_use_animated_seed"]

    observed = {
        "view_transform": scene.view_settings.view_transform,
        "look": scene.view_settings.look,
        "exposure": round(float(scene.view_settings.exposure), 6),
        "fps": render.fps,
        "fps_base": round(float(render.fps_base), 6),
    }
    for key in sorted(verified):
        if observed[key] != verified[key]:
            raise RuntimeError(
                f"the composed scene reports {key} {observed[key]!r}, but this render's profile "
                f"requires {verified[key]!r}; Phase 23 photographs the reviewed world and "
                "never overrides a locked layer's presentation to make a render succeed"
            )
    return {"owned": dict(owned), "verified": observed}


def render_device(bpy_module) -> str:
    """Select the fastest available Cycles device and report which was chosen.

    Follows the locked proof renderer's preference order -- OptiX, then CUDA,
    then CPU -- because the device belongs in the manifest and a render that
    silently fell back to CPU should say so.
    """
    from render_visual_proof import configure_cycles_device

    del bpy_module
    return configure_cycles_device()


# ---------------------------------------------------------------------------
# Frame files
# ---------------------------------------------------------------------------


MAXIMUM_FRAME_EDGE = 16384
"""No frame this phase writes is larger than this on either edge.

A declared size beyond it is a corrupt or hostile header, not a very large
picture, and treating it as a dimension would let a garbage file describe
itself as a valid frame.
"""

IHDR_LENGTH = 13
"""An image header is exactly this long; a shorter one cannot be read at all."""

KNOWN_CRITICAL_CHUNKS = frozenset({b"IHDR", b"PLTE", b"IDAT", b"IEND"})
"""The only critical chunks PNG defines.

A chunk is critical when the fifth bit of its first byte is clear -- an
uppercase first letter -- and PNG's own rule is that a decoder which does not
understand one must not proceed, because a critical chunk can change what the
image data means. Ancillary chunks are skippable by design, and Phase 23's
frames carry several: Blender writes ``tEXt``, ``pHYs``, ``oFFs`` and ``eXIf``.
"""

EXPECTED_BIT_DEPTH = 8
EXPECTED_COLOUR_TYPE = 2
EXPECTED_COMPRESSION_METHOD = 0
EXPECTED_FILTER_METHOD = 0
EXPECTED_INTERLACE_METHOD = 0
"""The exact image profile Phase 23 writes: eight-bit, non-interlaced RGB."""

VALID_FILTER_TYPES = frozenset({0, 1, 2, 3, 4})
"""Every per-scanline filter PNG defines. A sixth value is a corrupt file."""


class FrameRefused(ValueError):
    """A file this executor will not treat as a rendered frame.

    Named for the same reason ``PlanRefused`` is: a malformed image has to be an
    ordinary refusal with a sentence attached, not a ``zlib.error`` or an
    ``IndexError`` escaping from inside a parser.
    """


def png_chunks(data: bytes, description: str) -> list:
    """Return every (kind, body) chunk of a structurally legal PNG.

    **One parser, used by both readers.** V3 had two: ``png_facts`` checked
    lengths and CRCs, and ``png_pixels`` walked raw offsets with neither, so the
    two functions disagreed about what "a valid PNG" meant and the executor's
    answer depended on which one you asked. They now ask this.

    Structure is a state machine, not a checklist of chunk types that appear
    somewhere. An independent reviewer walked three files past V3 that had valid
    CRCs and decodable pixels and were still not PNGs: a duplicated ``IEND``, an
    ``IHDR`` after the image data, and an unknown critical chunk.

    Enforced here: the signature; valid lengths and CRCs; ``IHDR`` exactly once,
    first, thirteen bytes; ``IEND`` exactly once, last, empty, ending at end of
    file; at least one ``IDAT``, all consecutive; and no unrecognised critical
    chunk anywhere.

    Raises:
        FrameRefused: If the file is not a structurally legal PNG.
    """
    if not data.startswith(PNG_SIGNATURE):
        raise FrameRefused(f"{description} does not begin with the PNG signature")
    offset = len(PNG_SIGNATURE)
    found = []
    end_offset = None
    while offset < len(data):
        if end_offset is not None:
            raise FrameRefused(f"{description} carries a chunk after its IEND")
        if offset + 8 > len(data):
            raise FrameRefused(f"{description} ends inside a chunk header; the file is truncated")
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        body_start = offset + 8
        body_end = body_start + length
        if body_end + 4 > len(data):
            raise FrameRefused(f"{description} ends inside a {kind!r} chunk; it is truncated")
        body = data[body_start:body_end]
        stored = int.from_bytes(data[body_end : body_end + 4], "big")
        if zlib.crc32(kind + body) & 0xFFFFFFFF != stored:
            raise FrameRefused(f"{description} has a corrupt {kind!r} chunk; its CRC disagrees")
        if len(kind) != 4 or not kind.isalpha() or not kind.isascii():
            raise FrameRefused(
                f"{description} carries a chunk type {kind!r} that is not four ASCII "
                "letters; PNG chunk names are letters and nothing else"
            )
        if kind[2] & 0x20:
            raise FrameRefused(
                f"{description} carries chunk {kind!r} with its reserved bit set; PNG "
                "reserves that bit and a file using it means something this decoder does not "
                "know"
            )
        if not kind[0] & 0x20 and kind not in KNOWN_CRITICAL_CHUNKS:
            raise FrameRefused(
                f"{description} carries the unknown critical chunk {kind!r}; a critical chunk "
                "can change what the image data means"
            )
        if not found and kind != b"IHDR":
            raise FrameRefused(
                f"{description} opens with {kind!r}; a PNG begins with its image header"
            )
        if kind == b"IEND":
            end_offset = body_end + 4
        found.append((kind, body))
        offset = body_end + 4

    kinds = [kind for kind, _ in found]
    headers = kinds.count(b"IHDR")
    if headers != 1:
        raise FrameRefused(f"{description} declares {headers} image headers; one is expected")
    if len(found[0][1]) != IHDR_LENGTH:
        raise FrameRefused(
            f"{description} has a {len(found[0][1])}-byte image header; exactly {IHDR_LENGTH} "
            "are required"
        )
    if end_offset is None:
        raise FrameRefused(f"{description} carries no IEND chunk; the file is truncated")
    if kinds.count(b"IEND") != 1:
        raise FrameRefused(f"{description} carries {kinds.count(b'IEND')} IEND chunks")
    if kinds[-1] != b"IEND":
        raise FrameRefused(f"{description} does not end with its IEND chunk")
    if found[-1][1]:
        raise FrameRefused(
            f"{description} carries {len(found[-1][1])} bytes inside its IEND, which is empty "
            "by definition"
        )
    if end_offset != len(data):
        raise FrameRefused(
            f"{description} carries {len(data) - end_offset} bytes after its IEND chunk; a "
            "frame ends where its image ends"
        )
    if b"IDAT" not in kinds:
        raise FrameRefused(f"{description} carries no image data")
    palettes = kinds.count(b"PLTE")
    if palettes > 1:
        raise FrameRefused(f"{description} carries {palettes} palettes; PNG allows one")
    if palettes and kinds.index(b"PLTE") > kinds.index(b"IDAT"):
        raise FrameRefused(
            f"{description} places its palette after its image data; a palette the decoder "
            "reaches too late is a palette the picture was not drawn with"
        )
    first = kinds.index(b"IDAT")
    last = len(kinds) - 1 - kinds[::-1].index(b"IDAT")
    if kinds[first : last + 1] != [b"IDAT"] * (last - first + 1):
        raise FrameRefused(
            f"{description} splits its image data around another chunk; PNG requires every "
            "IDAT to be consecutive"
        )
    return found


def png_inflate(payload: bytes, description: str) -> bytes:
    """Decompress the image stream, requiring it to be exactly one complete stream.

    ``zlib.decompress`` is too forgiving for this. It stops at the end of the
    first stream and returns what it found, so a valid stream followed by
    arbitrary bytes -- or by a second complete stream -- decompresses happily
    and yields correct-looking pixels. An independent reviewer built exactly
    that: legal chunk order, valid CRCs, valid scanlines, and ``JUNK`` sitting
    after the end of the compressed data. Both decoders accepted it.

    The concatenated IDAT payload of a PNG *is* one zlib stream. So the
    decompressor is driven explicitly and asked three questions afterwards:
    did the stream reach its own terminator (``eof``), is there anything after
    it (``unused_data``), and did anything go unconsumed (``unconsumed_tail``).
    A truncated stream fails the first, trailing bytes fail the second.

    The check applies to the payload of every IDAT joined together, never to
    one chunk at a time -- a real frame here carries 108 to 130 IDAT chunks and
    the stream runs across all of them.

    Raises:
        FrameRefused: If the payload is not exactly one complete zlib stream.
    """
    decompressor = zlib.decompressobj()
    try:
        data = decompressor.decompress(payload)
        data += decompressor.flush()
    except zlib.error as error:
        raise FrameRefused(
            f"{description} image data could not be decompressed: {error}"
        ) from error
    if not decompressor.eof:
        raise FrameRefused(
            f"{description} image data ends before its compressed stream does; the stream "
            "is truncated"
        )
    if decompressor.unused_data:
        raise FrameRefused(
            f"{description} carries {len(decompressor.unused_data)} bytes after the end of "
            "its compressed image stream; the image data is exactly one zlib stream and "
            "nothing follows it"
        )
    if decompressor.unconsumed_tail:
        raise FrameRefused(
            f"{description} left {len(decompressor.unconsumed_tail)} bytes of its image "
            "stream unconsumed"
        )
    return data


def png_header(chunks: list, description: str) -> tuple:
    """Return (width, height) from a validated chunk list, refusing a foreign profile.

    Raises:
        FrameRefused: If the header does not describe what Phase 23 writes.
    """
    header = chunks[0][1]
    width = int.from_bytes(header[0:4], "big")
    height = int.from_bytes(header[4:8], "big")
    depth, colour, compression, filtering, interlace = header[8:13]
    for label, actual, expected in (
        ("bit depth", depth, EXPECTED_BIT_DEPTH),
        ("colour type", colour, EXPECTED_COLOUR_TYPE),
        ("compression method", compression, EXPECTED_COMPRESSION_METHOD),
        ("filter method", filtering, EXPECTED_FILTER_METHOD),
        ("interlace method", interlace, EXPECTED_INTERLACE_METHOD),
    ):
        if actual != expected:
            raise FrameRefused(
                f"{description} declares {label} {actual}, but Phase 23 writes {expected}"
            )
    if not 1 <= width <= MAXIMUM_FRAME_EDGE or not 1 <= height <= MAXIMUM_FRAME_EDGE:
        raise FrameRefused(f"{description} declares implausible dimensions {width}x{height}")
    return width, height


def require_scanline_payload(raw: bytes, width: int, height: int, description: str) -> None:
    """Refuse an inflated stream that is not exactly the scanlines the header implies.

    An empty zlib stream satisfies every terminator assertion -- it is a
    complete, correctly-ended stream that happens to contain nothing -- so the
    digest paths would hash a frame carrying no picture at all while only the
    pixel decoders refused it. The size the header implies is the same fact both
    paths need, so both check it.

    Raises:
        FrameRefused: If the payload is not ``(width * 3 + 1) * height`` bytes.
    """
    expected = (width * 3 + 1) * height
    if len(raw) != expected:
        raise FrameRefused(
            f"{description} decompresses to {len(raw)} bytes, but a {width}x{height} frame is "
            f"{expected} bytes of scanline data"
        )


def png_facts(path: Path) -> dict:
    """Return the size, digest and dimensions of a structurally legal PNG.

    Two digests come back. ``sha256`` is the file. ``image_sha256`` covers the
    **decompressed** image stream, so it changes when the picture changes and
    not when only Blender's embedded render date or its compressor's byte
    choices vary. That is all it claims: it tells a replaced frame from a
    re-stamped one. It is not a reproducibility claim -- two renders of one
    unchanged frame differ in their pixels as well, by a measured 0.02 to 0.03
    levels -- and nothing here should be read as promising otherwise.

    Structure comes from :func:`png_chunks`, so this and :func:`png_pixels`
    cannot disagree about what a valid frame is.

    Raises:
        FrameRefused: If the file is not a complete, structurally legal PNG.
    """
    data = Path(path).read_bytes()
    chunks = png_chunks(data, str(path))
    width, height = png_header(chunks, str(path))
    payload = b"".join(body for kind, body in chunks if kind == b"IDAT")
    if not payload:
        raise FrameRefused(f"{path} carries no image data; a framed empty file is not a frame")
    raw = png_inflate(payload, str(path))
    require_scanline_payload(raw, width, height, str(path))
    return {
        "bytes": len(data),
        "sha256": sha256_hex(data),
        "image_sha256": sha256_hex(raw),
        "width": width,
        "height": height,
    }


def png_pixels(path: Path) -> tuple:
    """Decode one 8-bit RGB PNG into raw samples, using the standard library only.

    Enough of the format to read what this phase writes -- colour type 2, eight
    bits, no interlacing -- and no more. Anything else is refused rather than
    half-decoded, because a comparison of two images this function only partly
    understood would be worse than no comparison at all.

    Raises:
        FrameRefused: If the file is not a PNG this decoder fully understands.
    """
    data = Path(path).read_bytes()
    chunks = png_chunks(data, str(path))
    width, height = png_header(chunks, str(path))
    payload = b"".join(body for kind, body in chunks if kind == b"IDAT")
    if not payload:
        raise FrameRefused(f"{path} carries no image data")
    raw = png_inflate(payload, str(path))
    require_scanline_payload(raw, width, height, str(path))
    stride = width * 3

    out = bytearray(stride * height)
    previous = bytearray(stride)
    position = 0
    for row in range(height):
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position : position + stride])
        position += stride
        if filter_type not in VALID_FILTER_TYPES:
            raise FrameRefused(f"{path} row {row} uses unknown filter {filter_type}")
        if filter_type == 0:
            out[row * stride : (row + 1) * stride] = line
            previous = line
            continue
        if filter_type == 2:
            line = bytearray((a + b) & 0xFF for a, b in zip(line, previous, strict=True))
            out[row * stride : (row + 1) * stride] = line
            previous = line
            continue
        for index in range(stride):
            left = line[index - 3] if index >= 3 else 0
            up = previous[index]
            corner = previous[index - 3] if index >= 3 else 0
            if filter_type == 1:
                line[index] = (line[index] + left) & 0xFF
            elif filter_type == 2:
                line[index] = (line[index] + up) & 0xFF
            elif filter_type == 3:
                line[index] = (line[index] + ((left + up) >> 1)) & 0xFF
            elif filter_type == 4:
                estimate = left + up - corner
                distance_left = abs(estimate - left)
                distance_up = abs(estimate - up)
                distance_corner = abs(estimate - corner)
                if distance_left <= distance_up and distance_left <= distance_corner:
                    predictor = left
                elif distance_up <= distance_corner:
                    predictor = up
                else:
                    predictor = corner
                line[index] = (line[index] + predictor) & 0xFF
        out[row * stride : (row + 1) * stride] = line
        previous = line
    return width, height, out


def require_verified_frame(path: Path, profile: dict) -> dict:
    """Fully verify a freshly rendered file before it takes its final name.

    Named ``verified`` rather than ``publishable`` because the Phase 23 boundary
    guard forbids this phase from defining anything spelled like Phase 24's
    publishing vocabulary, and it is right to: a guard that carves out
    exceptions for the current author stops being a guard. What the function
    does is unchanged -- it is the gate a frame passes through before
    ``os.replace`` gives it the name a reader trusts.

    V3 checked structure and dimensions here and deferred the rest -- colour
    type, bit depth, interlacing, the scanline payload, the row filters, the
    decode itself -- to the independent audit, which runs as a separate command
    possibly much later. That meant a frame whose deeper profile validity was
    unknown could land under its final deterministic filename, be recorded in
    the checkpoint, and be reused by a resume.

    Now a frame is proved to be a complete, legal, correctly-profiled, fully
    decodable picture of exactly the right size *before* ``os.replace`` puts it
    where a reader would trust it. The audit still re-verifies everything later
    from disk; this makes publication itself the point where the claim becomes
    true rather than the point where it starts being assumed.

    Returns:
        The frame's facts, for the checkpoint and the manifest.

    Raises:
        FrameRefused: If the file is not a publishable Phase 23 frame.
    """
    facts = png_facts(path)
    expected_width = profile["owned"]["resolution_x"]
    expected_height = profile["owned"]["resolution_y"]
    if facts["width"] != expected_width or facts["height"] != expected_height:
        raise FrameRefused(
            f"{path} is {facts['width']}x{facts['height']}, but this render's profile requires "
            f"{expected_width}x{expected_height}"
        )
    width, height, samples = png_pixels(path)
    if (width, height) != (expected_width, expected_height):
        raise FrameRefused(
            f"{path} decodes to {width}x{height}, not {expected_width}x{expected_height}"
        )
    if len(samples) != expected_width * expected_height * 3:
        raise FrameRefused(f"{path} decodes to {len(samples)} samples, not a full picture")
    return facts


def png_mean_abs_difference(first: Path, second: Path) -> float:
    """Return the mean absolute per-sample difference between two frames, in levels.

    Zero means the two images are pixel-identical. A small value means they
    differ only by sampling noise. This is measured rather than asserted
    because GPU path tracing is not byte-reproducible even for an unchanged
    scene, and pretending otherwise would put a false claim in the manifest.

    Raises:
        FrameRefused: If either file is not a frame this phase wrote, or the two
            images are not the same size.
    """
    width_a, height_a, samples_a = png_pixels(first)
    width_b, height_b, samples_b = png_pixels(second)
    if (width_a, height_a) != (width_b, height_b):
        raise FrameRefused(
            f"cannot compare {width_a}x{height_a} with {width_b}x{height_b}; the frames are "
            "not the same size"
        )
    if not samples_a:
        raise FrameRefused("cannot compare empty images")
    total = sum(abs(a - b) for a, b in zip(samples_a, samples_b, strict=True))
    return round(total / len(samples_a), 6)


def write_json_atomically(path: Path, document: object) -> None:
    """Write canonical JSON so a reader never sees a half-written document.

    The temporary file is flushed and fsynced before the rename, following the
    save manager's publication discipline: a rename over a complete file is
    atomic, a partially flushed one is not.
    """
    path = Path(path)
    temporary = path.with_name(path.name + ".writing")
    payload = canonical_bytes(document)
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def render_frame_file(
    bpy_module, frame: int, partial_dir: Path, destination: Path, *, profile: dict
) -> dict:
    """Render one semantic frame, prove it, and only then publish it atomically.

    The frame is rendered into a directory this script owns and empties first,
    so Blender cannot leave a numbered stub beside the file that is later
    mistaken for the real one -- the hazard the mobility proof packager
    documents. Exactly one file must appear.

    That file is then verified **completely** -- legal chunk structure, the
    declared image profile, the exact profile resolution, and a full
    decompression and unfilter of every scanline -- before ``os.replace`` moves
    it under its final deterministic name. V3 checked structure and size here
    and left the rest to the independent audit, which is a separate command run
    later; that allowed a frame of unproven profile validity to sit under a
    trusted filename, be recorded in the checkpoint, and be reused by a resume.

    Publication is the moment a file becomes authoritative, so it is the moment
    the claim has to be true. The audit still re-reads and re-verifies every
    frame afterwards, from disk, trusting none of this.

    Args:
        bpy_module: The Blender module.
        frame: The semantic frame number to render.
        partial_dir: The scratch directory this script owns.
        destination: The final path for the frame.
        profile: The render profile this frame must satisfy.

    Returns:
        The published frame's size and digests.

    Raises:
        RuntimeError: If the render produced anything other than one file.
        FrameRefused: If that file is not a publishable Phase 23 frame.
    """
    if partial_dir.exists():
        shutil.rmtree(partial_dir)
    partial_dir.mkdir(parents=True)
    working = partial_dir / destination.name

    scene = bpy_module.context.scene
    scene.frame_set(frame)
    scene.render.filepath = str(working.resolve())
    bpy_module.ops.render.render(write_still=True)

    produced = sorted(entry for entry in partial_dir.iterdir() if entry.is_file())
    if len(produced) != 1:
        raise RuntimeError(
            f"rendering frame {frame} produced {len(produced)} files "
            f"({[entry.name for entry in produced]}); exactly one frame file is expected"
        )
    facts = require_verified_frame(produced[0], profile)
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(produced[0], destination)
    shutil.rmtree(partial_dir, ignore_errors=True)
    return facts


def verify_active_camera(bpy_module, frame: int, expected: str) -> None:
    """Refuse unless Blender's own active camera at this frame is the directed one.

    Phase 22 binds cameras with timeline markers, which Blender evaluates on
    frame change. Asking the scene which camera it actually has -- rather than
    trusting that the markers were written correctly -- is what makes a frame's
    recorded camera a fact about the image instead of a copy of the plan.

    Raises:
        RuntimeError: If the scene has no camera or the wrong one.
    """
    camera = bpy_module.context.scene.camera
    if camera is None:
        raise RuntimeError(f"frame {frame} has no active camera; nothing would be photographed")
    if camera.name != expected:
        raise RuntimeError(
            f"frame {frame} renders through {camera.name!r}, but the shot direction plan "
            f"directs {expected!r}; Phase 23 renders the directed camera or nothing"
        )


# ---------------------------------------------------------------------------
# Destination, checkpoint and resume
# ---------------------------------------------------------------------------


def frame_destination(render_dir: Path, entry: dict) -> Path:
    """Return where one planned frame's file belongs."""
    folder = WITNESS_DIRECTORY if entry["role"] == "witness" else FRAMES_DIRECTORY
    return render_dir / folder / entry["file"]


ENVIRONMENT_KEYS = frozenset({"blender_version", "engine", "device"})
"""What a manifest records about the machine that made the pixels."""

CHECKPOINT_KEYS = frozenset(
    {"render_plan_sha256", "render_profile_sha256", "environment", "frames"}
)
"""Exactly the keys a render checkpoint carries."""

FRAME_RESULT_FIELDS = ("bytes", "sha256", "image_sha256")
"""Everything a record says about a frame file that the file can answer for.

Named once, and used for every comparison between the checkpoint, the manifest
and the file itself, so no comparison can quietly cover fewer fields than
another. V4 compared checkpoint and manifest on ``sha256`` alone.
"""

CHECKPOINT_FRAME_KEYS = frozenset(FRAME_RESULT_FIELDS)
"""What the checkpoint records about one published frame."""

MANIFEST_TOP_LEVEL_KEYS = frozenset(
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
MANIFEST_SOURCE_KEYS = PLAN_SOURCE_KEYS | {"render_plan_sha256"}
MANIFEST_FRAME_KEYS = FRAME_KEYS | {"bytes", "sha256", "image_sha256"}
COMPLETENESS_KEYS = frozenset(
    {
        "playback_frames_expected",
        "playback_frames_rendered",
        "witness_frames_rendered",
        "witness_mean_abs_difference",
        "witness_within_tolerance",
        "complete",
    }
)
RENDER_MANIFEST_FORMAT = "living_diorama_episode_render_manifest"


class RenderDirectoryRefused(RuntimeError):
    """A render directory this executor will not act on.

    Distinct from ``PlanRefused`` because the plan may be perfectly good and the
    directory still be one this run must not touch -- a partial render from
    another machine, a stale manifest, a checkpoint that contradicts itself.
    """


def _directory_digest(value, description: str) -> str:
    """A digest check that refuses as a *directory* problem, not a plan problem.

    The two refusals mean different things to a reader: a plan this executor
    will not act on, versus a directory it will not resume. Reusing the plan
    validator's helper here reported a malformed checkpoint as a malformed plan.
    """
    if type(value) is not str or len(value) != 64 or not set(value) <= HEX_DIGITS:
        raise RenderDirectoryRefused(
            f"{description} must be a lowercase 64-character digest, got {value!r}"
        )
    return value


_FRAME_KEY_PATTERN = re.compile(r"[0-9]+")
"""ASCII digits only -- see the identical constant in render_binding.py."""


def _canonical_frame_key(key, description):
    """Refuse a frame key that is not the one canonical spelling of its number.

    Restated from the engine's ``_require_canonical_frame_key`` for the same
    reason every other shared rule here is restated: this side may not import
    the engine, and ``str.isdigit()`` plus ``int()`` accept far more than the
    single spelling :func:`record_checkpoint` ever writes -- leading zeros,
    leading signs, surrounding whitespace, and any Unicode decimal digit.

    Raises:
        RenderDirectoryRefused: If the key is not the canonical spelling of a
            frame number.
    """
    if type(key) is not str or not _FRAME_KEY_PATTERN.fullmatch(key):
        raise RenderDirectoryRefused(
            f"{description} names frame {key!r}, which is not a frame number"
        )
    try:
        frame = int(key)
    except ValueError as error:
        # A digit string this long is refused for being unreasonable, not for
        # being unparseable -- but it must still be *this* function's refusal,
        # not CPython's int/str conversion guard leaking past it uncaught.
        raise RenderDirectoryRefused(
            f"{description} names frame {key!r}, which is not a frame number: {error}"
        ) from error
    if str(frame) != key:
        raise RenderDirectoryRefused(
            f"{description} names frame {key!r}; the canonical spelling of frame {frame} is "
            f"{str(frame)!r}"
        )
    return frame


def require_environment(document, description: str) -> dict:
    """Refuse anything that is not a complete, non-blank execution environment.

    A value carrying leading or trailing whitespace is refused outright rather
    than accepted and later compared literally: ``"CYCLES"`` and ``"CYCLES "``
    would then be two different environments by this phase's own equality
    check, for a difference nothing meaningful produced. The independent audit
    holds this to the same rule; production must not be the lenient half of a
    pair that is supposed to agree.

    Raises:
        RenderDirectoryRefused: If the environment is malformed.
    """
    if type(document) is not dict:
        raise RenderDirectoryRefused(f"{description} must be a JSON object")
    observed = set(document)
    if observed != ENVIRONMENT_KEYS:
        raise RenderDirectoryRefused(
            f"{description} carries keys {sorted(observed)}, expected {sorted(ENVIRONMENT_KEYS)}"
        )
    for key in sorted(ENVIRONMENT_KEYS):
        value = document[key]
        if type(value) is not str or not value or value != value.strip():
            raise RenderDirectoryRefused(f"{description} {key} must be a non-blank name")
    return dict(document)


def require_same_environment(first: dict, second: dict, first_name: str, second_name: str) -> None:
    """Refuse two environments that are not the same execution environment.

    **One render directory, one execution environment.** The manifest states a
    single environment for the whole render, and that statement is only true if
    every frame in the directory was made by it. Reusing frames rendered by
    another Blender, on another device, and then recording this run's
    environment would attribute those pixels to a machine that never produced
    them.

    Raises:
        RenderDirectoryRefused: On any difference.
    """
    differing = sorted(key for key in ENVIRONMENT_KEYS if first.get(key) != second.get(key))
    if differing:
        detail = ", ".join(f"{key}: {first.get(key)!r} vs {second.get(key)!r}" for key in differing)
        raise RenderDirectoryRefused(
            f"the {first_name} and the {second_name} disagree about the execution environment "
            f"({detail}). One render directory holds one environment: a manifest naming a "
            "single Blender, engine and device is only truthful if every frame in it came from "
            "that one. Render into a fresh directory instead"
        )


def require_valid_checkpoint(document, plan: dict, plan_digest: str) -> dict:
    """Validate a resume checkpoint completely before any of it is believed.

    V3 read this file with ``json.loads`` and trusted whatever came back: a
    checkpoint could name frames the plan never had, record a digest that was
    not a digest, or omit its environment entirely, and still vouch for a frame
    that a later run would skip re-rendering.

    Raises:
        RenderDirectoryRefused: On any violation.
    """
    if type(document) is not dict:
        raise RenderDirectoryRefused("the render checkpoint must be a JSON object")
    observed = set(document)
    if observed != CHECKPOINT_KEYS:
        raise RenderDirectoryRefused(
            f"the render checkpoint carries keys {sorted(observed)}, expected "
            f"{sorted(CHECKPOINT_KEYS)}"
        )
    if document["render_plan_sha256"] != plan_digest:
        raise RenderDirectoryRefused(
            f"the checkpoint is for render plan {document['render_plan_sha256']!r}, not "
            f"{plan_digest!r}"
        )
    if document["render_profile_sha256"] != RENDER_PROFILE_SHA256:
        raise RenderDirectoryRefused(
            "the checkpoint was rendered under a different profile; frames from two profiles "
            "are never mixed into one episode"
        )
    environment = require_environment(document["environment"], "the checkpoint environment")

    frames = document["frames"]
    if type(frames) is not dict:
        raise RenderDirectoryRefused("the checkpoint's frames must be a JSON object")
    planned = {entry["frame"] for entry in plan["frames"]}
    resolved: dict = {}
    for key, record in frames.items():
        frame = _canonical_frame_key(key, "the checkpoint")
        if frame in resolved:
            raise RenderDirectoryRefused(f"the checkpoint records frame {frame} twice")
        if frame not in planned:
            raise RenderDirectoryRefused(
                f"the checkpoint vouches for frame {frame}, which this plan never asked for"
            )
        if type(record) is not dict or set(record) != CHECKPOINT_FRAME_KEYS:
            raise RenderDirectoryRefused(
                f"the checkpoint's record for frame {frame} carries "
                f"{sorted(record) if type(record) is dict else type(record).__name__}, expected "
                f"{sorted(CHECKPOINT_FRAME_KEYS)}"
            )
        size = record["bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise RenderDirectoryRefused(
                f"the checkpoint records {size!r} bytes for frame {frame}; an empty frame is "
                "not a frame"
            )
        for digest_key in ("sha256", "image_sha256"):
            _directory_digest(record[digest_key], f"the checkpoint's frame {frame} {digest_key}")
        resolved[frame] = dict(record)
    return {"environment": environment, "frames": resolved}


def require_valid_manifest(document, plan: dict, plan_digest: str) -> dict:
    """Validate an existing manifest completely, against the plan it claims.

    A manifest already on disk is evidence: it is what lets a directory be
    called complete, and what vouches for frames a resume would skip. V3
    checked its ``render_plan_sha256`` and its per-frame digests and nothing
    else, so a manifest naming a different story, a different world or a
    different environment counted as completion evidence -- and the later path
    would overwrite it with a freshly assembled one.

    That is repair, and this phase refuses rather than repairs. A stale or
    contradictory manifest is a reason to stop, not a file to correct.

    The engine owns this contract; this is the standard-library restatement the
    Blender side needs, and a pure test drives both over the same mutations.

    Raises:
        RenderDirectoryRefused: On any violation, or any disagreement with the plan.
    """
    if type(document) is not dict:
        raise RenderDirectoryRefused("the render manifest must be a JSON object")
    observed = set(document)
    if observed != MANIFEST_TOP_LEVEL_KEYS:
        raise RenderDirectoryRefused(
            f"the render manifest carries keys {sorted(observed)}, expected "
            f"{sorted(MANIFEST_TOP_LEVEL_KEYS)}"
        )
    if document["format"] != RENDER_MANIFEST_FORMAT:
        raise RenderDirectoryRefused(f"the render manifest declares format {document['format']!r}")
    if _exact_int(document["schema_version"], "manifest schema_version") != 1:
        raise RenderDirectoryRefused("unsupported render manifest schema version")

    source = document["source"]
    if type(source) is not dict or set(source) != MANIFEST_SOURCE_KEYS:
        raise RenderDirectoryRefused(
            f"the render manifest's source carries "
            f"{sorted(source) if type(source) is dict else type(source).__name__}, expected "
            f"{sorted(MANIFEST_SOURCE_KEYS)}"
        )
    if source["render_plan_sha256"] != plan_digest:
        raise RenderDirectoryRefused(
            f"the manifest binds render plan {source['render_plan_sha256']!r}, but this render "
            f"is {plan_digest!r}"
        )
    for key in sorted(PLAN_SOURCE_KEYS):
        if source[key] != plan["source"][key]:
            raise RenderDirectoryRefused(
                f"the manifest's {key} is {source[key]!r}, but its own render plan says "
                f"{plan['source'][key]!r}; a stale manifest is refused, never rewritten"
            )
    for block in ("composition_sources", "emission"):
        if document[block] != plan[block]:
            raise RenderDirectoryRefused(
                f"the manifest's {block} disagrees with its own render plan"
            )

    environment = require_environment(document["environment"], "the manifest environment")

    frames = document["frames"]
    if type(frames) is not list or len(frames) != len(plan["frames"]):
        raise RenderDirectoryRefused(
            f"the manifest records {len(frames) if type(frames) is list else '?'} frames, but "
            f"its plan accounts for {len(plan['frames'])}"
        )
    playback = witness = 0
    for position, (record, planned) in enumerate(zip(frames, plan["frames"], strict=True)):
        where = f"manifest frames[{position}]"
        if type(record) is not dict or set(record) != MANIFEST_FRAME_KEYS:
            raise RenderDirectoryRefused(f"{where} does not carry a frame record")
        for key in sorted(FRAME_KEYS):
            if record[key] != planned[key]:
                raise RenderDirectoryRefused(
                    f"{where} records {key} {record[key]!r}, but the plan says {planned[key]!r}"
                )
        size = record["bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise RenderDirectoryRefused(f"{where} records {size!r} bytes")
        for digest_key in ("sha256", "image_sha256"):
            _directory_digest(record[digest_key], f"{where} {digest_key}")
        if record["role"] == "witness":
            witness += 1
        else:
            playback += 1

    completeness = document["completeness"]
    if type(completeness) is not dict or set(completeness) != COMPLETENESS_KEYS:
        raise RenderDirectoryRefused("the manifest's completeness block is not the expected shape")
    difference = completeness["witness_mean_abs_difference"]
    if type(difference) is not float or difference < 0.0:
        raise RenderDirectoryRefused(
            f"the manifest records a boundary difference of {difference!r}"
        )
    for key in ("complete", "witness_within_tolerance"):
        if type(completeness[key]) is not bool:
            raise RenderDirectoryRefused(f"the manifest's completeness {key} must be a bool")
    expected_counts = {
        "playback_frames_expected": plan["emission"]["frame_count"],
        "playback_frames_rendered": playback,
        "witness_frames_rendered": witness,
    }
    for key, expected in expected_counts.items():
        if _exact_int(completeness[key], f"manifest completeness {key}") != expected:
            raise RenderDirectoryRefused(
                f"the manifest's completeness {key} is {completeness[key]}, but its own records "
                f"say {expected}"
            )
    within = difference <= WITNESS_DIFFERENCE_TOLERANCE
    if completeness["witness_within_tolerance"] != within:
        raise RenderDirectoryRefused(
            "the manifest's boundary verdict does not follow from its own measurement"
        )
    if completeness["complete"] != (
        playback == plan["emission"]["frame_count"] and witness == 1 and within
    ):
        raise RenderDirectoryRefused(
            "the manifest's completeness verdict does not follow from its own records"
        )
    return {"document": document, "environment": environment}


def read_render_record(path: Path, description: str) -> dict:
    """Read one of this directory's own JSON records, refusing a malformed one.

    ``read_json_document`` raises whatever the parser raises -- a
    ``json.JSONDecodeError`` for a truncated file, a ``ValueError`` for a
    repeated key. Those are correct refusals but the wrong *kind*: everything
    this survey rejects is a statement about the directory, and a caller
    catching ``RenderDirectoryRefused`` would have missed them.

    Raises:
        RenderDirectoryRefused: If the file is not a readable JSON object.
    """
    try:
        return read_json_document(path, description)
    except (ValueError, UnicodeDecodeError) as error:
        raise RenderDirectoryRefused(f"{path} is not a readable {description}: {error}") from error


def read_checkpoint(render_dir: Path) -> dict | None:
    """Return the resume state for this render directory, if any is readable."""
    path = render_dir / RENDER_CHECKPOINT_FILENAME
    if not path.is_file():
        return None
    return read_render_record(path, "render checkpoint")


def survey_render_directory(
    render_dir: Path, plan: dict, plan_digest: str, environment: dict
) -> dict:
    """Decide what already exists here, and refuse anything ambiguous.

    Returns a survey naming which frames are already valid and may be skipped.
    A frame counts as valid only when the checkpoint recorded it under THIS
    plan, the file on disk still hashes to what was recorded, and the records
    vouching for it were written by THIS execution environment -- existence is
    never taken as evidence of completeness.

    **Why the environment is an argument now.** A manifest states one Blender
    version, one engine and one device for the whole render. Reusing frames that
    another machine produced and then recording this run's environment would
    attribute those pixels to hardware that never made them. So a partial render
    is resumable only by the environment that started it.

    A *complete* render is different: nothing is reused because nothing is
    rendered, so a re-run under another environment mixes nothing. It is
    verified and reported, and the environment that actually made those files is
    carried out of here so the existing manifest is never re-attributed.

    Args:
        render_dir: The directory this render owns.
        plan: The validated Episode Render Plan.
        plan_digest: Its canonical digest.
        environment: The environment this invocation would render under.

    Raises:
        RenderDirectoryRefused: If the directory belongs to another render,
            holds files nobody planned, carries an invalid checkpoint or a stale
            manifest, or was rendered by a different environment.
        RuntimeError: If a recorded frame's bytes changed.
    """
    survey = {
        "complete": False,
        "valid_frames": {},
        "manifest": None,
        "environment": environment,
    }
    planned_paths = {frame_destination(render_dir, entry) for entry in plan["frames"]}

    existing_plan = render_dir / RENDER_PLAN_FILENAME
    if existing_plan.is_file():
        recorded = sha256_hex(canonical_bytes(read_render_record(existing_plan, "render plan")))
        if recorded != plan_digest:
            raise RenderDirectoryRefused(
                f"{render_dir} already holds a render of a different plan ({recorded}); this "
                f"render is {plan_digest}. Two renders never share a directory, and nothing "
                "here is deleted to make room"
            )

    # The top level, before anything else is believed about this directory. The
    # independent verifier already refused a render holding a file nobody
    # recognises; production refusing a different set would mean the phase has
    # two definitions of a valid render.
    interrupted = []
    for found in sorted(render_dir.iterdir()):
        kind = classify_render_directory_entry(found.name, found.is_dir())
        if kind == "foreign":
            raise RenderDirectoryRefused(
                f"{found} is not something Phase 23 put here; a render directory holds only "
                f"{sorted(RENDER_DIRECTORY_ENTRIES)}, and this phase refuses a directory it "
                "does not recognise rather than deleting a file it did not make"
            )
        if kind == "partial":
            interrupted.append(found)

    for folder in (FRAMES_DIRECTORY, WITNESS_DIRECTORY):
        directory = render_dir / folder
        if not directory.is_dir():
            continue
        for found in sorted(directory.iterdir()):
            if found.is_dir():
                raise RuntimeError(f"{found} is a directory where a frame file was expected")
            if found not in planned_paths:
                raise RuntimeError(
                    f"{found} is not a frame this plan accounts for; Phase 23 refuses a render "
                    "directory it does not recognise rather than deleting a file it did not make"
                )

    # Recorded digests, from whichever records exist. Both must belong to this
    # plan, and where both exist they must agree: a frame is only skippable if
    # something this render wrote vouches for it.
    # Two records, kept apart. V4 merged them and let the checkpoint's entry win
    # by `setdefault`, so a manifest could carry the right `sha256` beside a
    # wrong `bytes` or a wrong `image_sha256` and never be compared to anything:
    # the file was proved against the checkpoint, and the manifest -- the
    # document that decides whether the render is finished -- was never asked.
    checkpoint_frames: dict[int, dict] = {}
    checkpoint_environment: dict | None = None
    checkpoint = read_checkpoint(render_dir)
    if checkpoint is not None:
        validated = require_valid_checkpoint(checkpoint, plan, plan_digest)
        checkpoint_environment = validated["environment"]
        checkpoint_frames = validated["frames"]

    manifest_path = render_dir / RENDER_MANIFEST_FILENAME
    manifest = None
    manifest_frames: dict[int, dict] = {}
    manifest_environment: dict | None = None
    if manifest_path.is_file():
        # Validated completely before it is allowed to vouch for anything. A
        # manifest is completion evidence, and evidence nobody checked is just
        # a file that happens to be lying beside the frames.
        checked = require_valid_manifest(
            read_render_record(manifest_path, "render manifest"), plan, plan_digest
        )
        manifest = checked["document"]
        manifest_environment = checked["environment"]
        for entry in manifest["frames"]:
            frame = entry["frame"]
            manifest_frames[frame] = {
                "bytes": entry["bytes"],
                "sha256": entry["sha256"],
                "image_sha256": entry["image_sha256"],
            }
            recorded = checkpoint_frames.get(frame)
            if recorded is None:
                continue
            differing = sorted(
                field for field in FRAME_RESULT_FIELDS if recorded[field] != entry[field]
            )
            if differing:
                # All three fields, not just the digest. Two records of one file
                # cannot disagree about its length or its image data and both be
                # true, and there is no way to tell which one is lying.
                detail = ", ".join(
                    f"{field}: {recorded[field]!r} vs {entry[field]!r}" for field in differing
                )
                raise RenderDirectoryRefused(
                    f"{render_dir} holds a manifest and a checkpoint that disagree about frame "
                    f"{frame} ({detail}); a render directory that contradicts itself is refused"
                )
        survey["manifest"] = manifest

    if checkpoint_environment is not None and manifest_environment is not None:
        require_same_environment(
            checkpoint_environment, manifest_environment, "checkpoint", "manifest"
        )

    for entry in plan["frames"]:
        path = frame_destination(render_dir, entry)
        if not path.is_file():
            continue
        frame = entry["frame"]
        sources = {
            name: record
            for name, record in (
                ("checkpoint", checkpoint_frames.get(frame)),
                ("manifest", manifest_frames.get(frame)),
            )
            if record is not None
        }
        if not sources:
            raise RuntimeError(
                f"{path} exists but nothing this render wrote accounts for it; Phase 23 will "
                "not overwrite a frame whose provenance it cannot establish"
            )
        # The same full gate a freshly rendered frame passes before publication:
        # structure, profile, exact resolution, and a complete decode. V3
        # re-checked a reused frame with png_facts alone, so its scanlines and
        # row filters were never looked at on the path that skips re-rendering.
        facts = require_verified_frame(path, plan["profile"])
        # Against EVERY record that exists, on EVERY result field. One record
        # standing in for another is how a manifest came to establish
        # completeness without ever being compared to the file it describes.
        for name, record in sorted(sources.items()):
            wrong = sorted(field for field in FRAME_RESULT_FIELDS if facts[field] != record[field])
            if wrong:
                detail = ", ".join(
                    f"{field}: file {facts[field]!r} vs {name} {record[field]!r}" for field in wrong
                )
                raise RuntimeError(
                    f"{path} no longer matches what the {name} records for frame {frame} "
                    f"({detail}); a changed frame is refused, never re-rendered over"
                )
        survey["valid_frames"][entry["frame"]] = {
            "bytes": facts["bytes"],
            "sha256": facts["sha256"],
            "image_sha256": facts["image_sha256"],
        }

    if manifest is not None:
        survey["complete"] = len(survey["valid_frames"]) == len(plan["frames"])
        if survey["complete"] and interrupted:
            # Every frame verifies and a manifest is present, but this phase's
            # own working files are still lying here -- so the run that wrote
            # them did not reach the end. Resuming is fine; calling it finished
            # is not.
            raise RenderDirectoryRefused(
                f"{render_dir} holds a complete manifest but also "
                f"{[str(path.name) for path in interrupted]}, left by a run that did not "
                "finish; a finished render owns nothing in progress"
            )
        if survey["complete"] and not existing_plan.is_file():
            # A finished render is returned untouched, so it has to already say
            # what it renders. Writing the missing plan here would be repairing
            # a directory into looking complete, which is the one thing this
            # phase does not do.
            raise RenderDirectoryRefused(
                f"{render_dir} holds a complete manifest but no {RENDER_PLAN_FILENAME}; a "
                "finished render says what it is, and this one is not repaired into saying it"
            )

    recorded_environment = manifest_environment or checkpoint_environment
    if recorded_environment is not None:
        if survey["complete"]:
            # Nothing will be rendered, so nothing can be mixed. The environment
            # that actually produced these files is what leaves this function,
            # so a re-run on another machine verifies the render instead of
            # re-attributing it.
            survey["environment"] = recorded_environment
        elif survey["valid_frames"]:
            # A partial render is only resumable by the environment that began
            # it: the frames already here and the frames still to come would
            # otherwise end up under one manifest naming a single machine.
            require_same_environment(
                recorded_environment, environment, "existing render", "current run"
            )
    return survey


def record_checkpoint(render_dir: Path, plan_digest: str, frames: dict, environment: dict) -> None:
    """Persist resume state atomically after each published frame."""
    write_json_atomically(
        render_dir / RENDER_CHECKPOINT_FILENAME,
        {
            "render_plan_sha256": plan_digest,
            "render_profile_sha256": RENDER_PROFILE_SHA256,
            "environment": environment,
            "frames": {str(frame): facts for frame, facts in sorted(frames.items())},
        },
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def execute_render(
    bpy_module,
    *,
    plan: dict,
    render_dir: Path,
    limit: int | None = None,
) -> dict:
    """Render every planned frame that is not already proven present.

    Args:
        bpy_module: The Blender module, with the directed world already composed.
        plan: The validated Episode Render Plan document.
        render_dir: The directory this render owns.
        limit: Stop after this many freshly rendered frames. Used by the
            interruption tests to produce a genuinely partial render; a
            production run passes nothing.

    Returns:
        The render result: per-frame facts, what was skipped, what was
        rendered, the environment that produced the files, and -- when the
        directory was already finished -- the manifest that already describes
        it, so a caller knows there is nothing to write.

    Raises:
        RenderDirectoryRefused: If the directory cannot be resumed truthfully.
        RuntimeError: On any disagreement between the plan and the scene.
    """
    require_render_plan(plan)
    plan_digest = sha256_hex(canonical_bytes(plan))

    # The environment is established BEFORE the directory is surveyed, because
    # whether an existing partial render may be resumed at all depends on it.
    # Neither call writes anything: they configure the scene and read it back.
    device = render_device(bpy_module)
    applied = apply_render_profile(bpy_module, plan["profile"])
    environment = {
        "blender_version": bpy_module.app.version_string,
        "engine": applied["owned"]["engine"],
        "device": device,
    }

    render_dir.mkdir(parents=True, exist_ok=True)
    survey = survey_render_directory(render_dir, plan, plan_digest, environment)

    if survey["complete"]:
        # A finished render is verified, not re-written. Its plan copy is
        # already there and already proven to be this plan, and its manifest is
        # already proven truthful, so touching either would only risk replacing
        # a good record with an identical one -- or, as in V3, with one carrying
        # this run's environment instead of the environment that made the files.
        return {
            "frames": survey["valid_frames"],
            "rendered": [],
            "skipped": sorted(survey["valid_frames"]),
            "environment": survey["environment"],
            "already_complete": True,
            "manifest": survey["manifest"],
        }

    write_json_atomically(render_dir / RENDER_PLAN_FILENAME, plan)

    results = dict(survey["valid_frames"])
    rendered: list[int] = []
    partial_dir = render_dir / PARTIAL_DIRECTORY
    for entry in plan["frames"]:
        frame = entry["frame"]
        if frame in results:
            continue
        if limit is not None and len(rendered) >= limit:
            break
        destination = frame_destination(render_dir, entry)
        bpy_module.context.scene.frame_set(frame)
        verify_active_camera(bpy_module, frame, entry["camera_anchor_id"])
        # Fully verified against the profile inside render_frame_file, before it
        # was published: a frame only reaches this line by being a legal,
        # correctly-profiled, fully decodable picture of exactly the right size.
        facts = render_frame_file(
            bpy_module, frame, partial_dir, destination, profile=plan["profile"]
        )
        results[frame] = {
            "bytes": facts["bytes"],
            "sha256": facts["sha256"],
            "image_sha256": facts["image_sha256"],
        }
        rendered.append(frame)
        record_checkpoint(render_dir, plan_digest, results, environment)

    return {
        "frames": results,
        "rendered": rendered,
        "skipped": sorted(set(results) - set(rendered)),
        "environment": environment,
        "already_complete": False,
        "manifest": None,
    }


def assemble_manifest(
    plan: dict, plan_digest: str, results: dict, environment: dict, difference: float
) -> dict:
    """Assemble the render manifest from the plan and what actually landed.

    Mechanical only: every field is copied from the plan or measured from the
    files, and no field is decided here. The engine owns the manifest contract
    and refuses a manifest that breaks it; a pure test proves this assembly and
    the engine's own builder produce the same document from the same results,
    so the two can never drift apart unnoticed.

    Raises:
        RuntimeError: If a planned frame has no result.
    """
    frames = []
    for entry in plan["frames"]:
        facts = results.get(entry["frame"])
        if facts is None:
            raise RuntimeError(f"frame {entry['frame']} has no result; the render is not complete")
        frames.append(
            {
                **entry,
                "bytes": facts["bytes"],
                "sha256": facts["sha256"],
                "image_sha256": facts["image_sha256"],
            }
        )
    playback = [record for record in frames if record["role"] == "playback"]
    witness = [record for record in frames if record["role"] == "witness"]
    emission = plan["emission"]
    return {
        "format": "living_diorama_episode_render_manifest",
        "schema_version": 1,
        "source": {**plan["source"], "render_plan_sha256": plan_digest},
        "composition_sources": dict(plan["composition_sources"]),
        "emission": dict(emission),
        "environment": {key: str(value) for key, value in sorted(environment.items())},
        "frames": frames,
        "completeness": {
            "playback_frames_expected": emission["frame_count"],
            "playback_frames_rendered": len(playback),
            "witness_frames_rendered": len(witness),
            "witness_mean_abs_difference": difference,
            "witness_within_tolerance": difference <= WITNESS_DIFFERENCE_TOLERANCE,
            "complete": (
                len(playback) == emission["frame_count"]
                and len(witness) == 1
                and difference <= WITNESS_DIFFERENCE_TOLERANCE
            ),
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the production render entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "render-plan",
        "shot-plan",
        "catalogue",
        "spec",
        "production",
        "motion",
        "presence",
        "mobility",
        "state-response",
        "after",
        "output-root",
    ):
        parser.add_argument(f"--{name}", required=True)
    # Required for a transition, refused for a baseline: a baseline has no
    # second world, and accepting one would leave an unbound input able to
    # change the picture.
    parser.add_argument("--before", default=None)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after this many freshly rendered frames (interruption testing only)",
    )
    return parser


def main() -> int:
    """Compose, direct, render and record one episode. Returns a process exit code."""
    import bpy
    import episode_scene

    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    arguments = _build_parser().parse_args(argv)

    # Everything is checked before anything is composed, rendered or written.
    # The order is the contract: a malformed or foreign plan must not create so
    # much as a directory.
    plan = require_valid_render_plan(read_json_document(Path(arguments.render_plan), "render plan"))

    # The shot plan is identified by its EXACT bytes before it is parsed, so a
    # re-formatted or re-ordered copy of the same data -- a different file, with
    # a different digest, which the render plan did not bind -- never reaches
    # the parser on this path at all.
    shot_plan_path = Path(arguments.shot_plan)
    require_shot_plan_bytes(plan, shot_plan_path.read_bytes())
    shot_plan = read_json_document(shot_plan_path, "shot direction plan")
    require_plan_matches_shot_plan(plan, shot_plan)

    # A catalogue preflight, not a replacement for Phase 22's own semantic
    # check: that still runs over the composed scene. This one only refuses a
    # render that cannot legally finish before spending minutes building a world
    # for it.
    catalogue = read_json_document(Path(arguments.catalogue), "camera catalogue")
    require_approved_catalogue(plan, catalogue)

    # Every document the composed world is built from is checked by its RAW
    # bytes. Canonicalising first would accept a pretty-printed or re-ordered
    # copy, and "the same data, differently written" is not the same source:
    # the digests these are compared against are digests of exact files.
    composition_paths = {
        "master_scene_sha256": Path(arguments.spec),
        "production_world_sha256": Path(arguments.production),
        "motion_time_sha256": Path(arguments.motion),
        "population_presence_sha256": Path(arguments.presence),
        "daily_life_mobility_sha256": Path(arguments.mobility),
        "state_response_sha256": Path(arguments.state_response),
    }
    for key, path in sorted(composition_paths.items()):
        expected = plan["composition_sources"][key]
        actual = sha256_hex(path.read_bytes())
        if actual != expected:
            raise SystemExit(
                f"the render plan binds {key} {expected}, but {path} hashes to {actual}; "
                "Phase 23 composes the world its plan names and no other"
            )

    after_path = Path(arguments.after)
    after_digest = sha256_hex(after_path.read_bytes())
    if after_digest != plan["source"]["after_export_sha256"]:
        raise SystemExit(
            f"the render plan binds after_export_sha256 "
            f"{plan['source']['after_export_sha256']}, but {after_path} hashes to {after_digest}"
        )

    if plan["source"]["mode"] == "baseline":
        # A baseline holds one state, so it has no second world to be handed.
        # Composing it from its own bound export at both endpoints is what makes
        # it source-closed: there is no unbound input left to influence it.
        if arguments.before is not None:
            raise SystemExit(
                "a baseline render composes from its own bound export alone; --before names a "
                "second world it must not have"
            )
        before_path = after_path
    else:
        if arguments.before is None:
            raise SystemExit("a transition render requires --before")
        before_path = Path(arguments.before)
        before_digest = sha256_hex(before_path.read_bytes())
        if before_digest != plan["source"]["before_export_sha256"]:
            raise SystemExit(
                f"the render plan binds before_export_sha256 "
                f"{plan['source']['before_export_sha256']}, but {before_path} hashes to "
                f"{before_digest}"
            )

    expected = episode_scene.compose_episode_world(
        spec_path=Path(arguments.spec),
        production_path=Path(arguments.production),
        motion_path=Path(arguments.motion),
        presence_path=Path(arguments.presence),
        mobility_path=Path(arguments.mobility),
        state_response_path=Path(arguments.state_response),
        before_path=before_path,
        after_path=after_path,
    )
    census = episode_scene.census_composed_world(
        bpy, expected, expect_state_response_motion=plan["source"]["mode"] != "baseline"
    )
    episode_scene.direct_episode_world(bpy, shot_plan, catalogue)

    render_dir = Path(arguments.output_root).resolve() / plan["destination"]["render_id"]
    result = execute_render(bpy, plan=plan, render_dir=render_dir, limit=arguments.limit)

    print(f"LD_P23_RENDER_DIR {render_dir}")
    print(f"LD_P23_COMPOSITION {json.dumps(census, sort_keys=True)}")
    print(f"LD_P23_ENVIRONMENT {json.dumps(result['environment'], sort_keys=True)}")
    print(f"LD_P23_RENDERED {len(result['rendered'])} SKIPPED {len(result['skipped'])}")
    if len(result["frames"]) != len(plan["frames"]):
        print(
            f"LD_P23_INCOMPLETE {len(result['frames'])}/{len(plan['frames'])} frames present; "
            "no manifest written"
        )
        return 1

    plan_digest = sha256_hex(canonical_bytes(plan))

    if result["already_complete"]:
        # Nothing was rendered, so there is nothing new to record. The manifest
        # on disk was fully validated against this plan during the survey, and
        # re-assembling it would at best rewrite it with identical content and
        # at worst re-attribute its pixels to whatever machine happened to run
        # this command. A verification run verifies.
        manifest = result["manifest"]
        completeness = manifest["completeness"]
        print(f"LD_P23_ALREADY_COMPLETE {render_dir}")

        # Re-measured from the two images on disk, not read out of the document
        # being reported. "Do not rewrite" is not "do not look": the closure
        # verdict can be checked without touching a byte of the record, and a
        # manifest whose own measurement no longer matches its frames is a
        # manifest that has stopped being true.
        measured = png_mean_abs_difference(
            frame_destination(render_dir, plan["frames"][-2]),
            frame_destination(render_dir, plan["frames"][-1]),
        )
        recorded = completeness["witness_mean_abs_difference"]
        if measured != recorded:
            print(
                f"LD_P23_CLOSURE_FAILED the manifest records a boundary difference of "
                f"{recorded}, but the frames on disk measure {measured}"
            )
            return 1
        print(f"LD_P23_WITNESS_DIFFERENCE {measured}")
        print(f"LD_P23_WITNESS_WITHIN_TOLERANCE {completeness['witness_within_tolerance']}")
        print(f"LD_P23_MANIFEST {render_dir / RENDER_MANIFEST_FILENAME}")
        if not completeness["complete"]:
            print("LD_P23_CLOSURE_FAILED the existing manifest does not claim a complete render")
            return 1
        print(f"LD_P23_COMPLETE {completeness['playback_frames_rendered']} playback frames")
        return 0

    witness_entry = plan["frames"][-1]
    final_entry = plan["frames"][-2]
    difference = png_mean_abs_difference(
        frame_destination(render_dir, final_entry),
        frame_destination(render_dir, witness_entry),
    )
    print(f"LD_P23_WITNESS_DIFFERENCE {difference}")
    manifest = assemble_manifest(
        plan, plan_digest, result["frames"], result["environment"], difference
    )
    write_json_atomically(render_dir / RENDER_MANIFEST_FILENAME, manifest)
    completeness = manifest["completeness"]
    print(f"LD_P23_WITNESS_WITHIN_TOLERANCE {completeness['witness_within_tolerance']}")
    print(f"LD_P23_MANIFEST {render_dir / RENDER_MANIFEST_FILENAME}")

    # The manifest is written either way, because a truthful record of a render
    # that failed its own closure gate is worth having -- but the process does
    # not call that a success. ``complete`` includes the witness verdict, so
    # the document and the exit code cannot disagree.
    if not completeness["complete"]:
        print(
            f"LD_P23_CLOSURE_FAILED witness difference {difference} exceeds the tolerance; "
            "the episode did not end where its contract requires"
        )
        return 1
    print(f"LD_P23_COMPLETE {completeness['playback_frames_rendered']} playback frames")
    return 0


if __name__ == "__main__":  # pragma: no cover - module execution entry
    raise SystemExit(main())
