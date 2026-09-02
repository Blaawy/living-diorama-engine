"""Shot Direction Plan format V1: the cinematic direction contract.

A shot direction plan is presentation metadata. It says which already-existing
camera anchor should be active over which stretch of the already-locked Phase 17
timeline, and it proves, for every non-neutral shot, which Phase 21 beat asked
for it. It asserts nothing about the world.

The document shape is exact at every level this module governs. A missing key
means the plan is incomplete; an extra key means it was written by something this
contract does not describe. Both are refused, never repaired -- the same
discipline the render, save and story schemas hold.

This module imports only the standard library, the ``living_diorama`` persistence
validation vocabulary, and the Phase 21 story vocabulary it copies. Cinematic
direction is a read-only consumer of a verified story plan and a source-bound
Phase 17 clock, and must never reach into live simulation.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, cast

from living_diorama.cinematic.cinematic_spec import (
    ANCHOR_NAMES,
    BEAT_SHOT_REASONS,
    ESTABLISHING_ANCHOR,
    REASON_ADJACENT_SAME_ANCHOR_MERGED,
    REASON_NEUTRAL_ESTABLISHING,
    REASON_UNKNOWN_BEAT_KIND,
    SHOT_ESTABLISHING,
    SHOT_KINDS,
    UNSHOWN_REASONS,
    catalogue_sha256,
)
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_identifier,
    require_text,
)
from living_diorama.story import EMPHASIS_LEVELS

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in.

Declared here rather than imported from ``living_diorama.events``: the cinematic
layer is forbidden to reach into the event package, and a shared type alias is
not worth a hole in that boundary.
"""

SHOT_PLAN_FORMAT: Final = "living_diorama_shot_direction_plan"
"""The format tag every shot direction plan declares."""

SHOT_SCHEMA_VERSION: Final = 1
"""The shot plan schema version this build reads and writes.

Independent from the story, render and persistence schema versions: the formats
evolve on their own timelines and must never be conflated.
"""

SUPPORTED_STORY_SCHEMA_VERSION: Final = 1
"""The Episode Story Plan schema version this build can direct."""

MOTION_TIME_FORMAT: Final = "living_diorama_motion_time"
"""The format tag of the Phase 17 Motion & Time Spec a plan must be cut against.

Restated as data rather than imported: Phase 17's modules are never reachable
from this layer, so its format identity is carried here the same way the camera
catalogue carries the builders' cameras. The in-Blender structural suite proves
this restated contract against ``motion_time_spec`` itself, so the two cannot
drift silently.
"""

SUPPORTED_MOTION_SCHEMA_VERSION: Final = 1
"""The Motion & Time Spec schema version this build can direct against."""

CANONICAL_MOTION_TIME_SHA256: Final = (
    "bfcbfcfd8d2b33f0ca8a0bc51655a1028babc601a73cdd42ca3c8caf3f9da673"
)
"""The SHA-256 of the one canonical Phase 17 Motion & Time Spec.

The exact bytes of ``visual/blender/config/motion_time_v1.json`` in the locked
tree this build was reviewed against. Phase 22 V1 directs THE locked Phase 17
clock, not any document shaped like one: the binding refuses every byte-distinct
alternative outright, however internally consistent, so a plausible 30 fps or
shifted clock can never produce a plan at all. A future Phase 17 source change
therefore requires an explicit reviewed update of this constant -- a repository
test re-hashes the shipped config against it, so silent drift fails loudly in
both directions.
"""

DIRECTOR_V4_MOTION_TIME_SHA256: Final = (
    "a821049b648c0d37a9bc5c6cbc74142cffb0c21a817ad3e2b10764dfeaa4079c"
)
"""The SHA-256 of the reviewed Director V4 Motion & Time Spec.

The exact bytes of ``visual/blender/config/motion_time_director_v4.json`` in the
locked tree this build was reviewed against. Same discipline as the canonical
pin: a repository test re-hashes the shipped file against this constant, and the
resolved clock below is what that digest resolves to.
"""

CANONICAL_RESOLVED_TIMELINE: Final[Mapping[str, int]] = MappingProxyType(
    {
        "end_frame": 193,
        "end_hold_frames": 48,
        "fps": 24,
        "start_frame": 1,
        "start_hold_frames": 24,
        "transition_end": 145,
        "transition_frames": 120,
        "transition_start": 25,
    }
)
"""The resolved canonical Phase 17 clock, restated beside its source digest."""

DIRECTOR_V4_RESOLVED_TIMELINE: Final[Mapping[str, int]] = MappingProxyType(
    {
        "end_frame": 319,
        "end_hold_frames": 18,
        "fps": 24,
        "start_frame": 1,
        "start_hold_frames": 24,
        "transition_end": 301,
        "transition_frames": 276,
        "transition_start": 25,
    }
)
"""The resolved Director V4 clock: 314 playback frames at 24 fps (13.0833 s)."""

REVIEWED_CLOCKS: Final[Mapping[str, Mapping[str, int]]] = MappingProxyType(
    {
        CANONICAL_MOTION_TIME_SHA256: CANONICAL_RESOLVED_TIMELINE,
        DIRECTOR_V4_MOTION_TIME_SHA256: DIRECTOR_V4_RESOLVED_TIMELINE,
    }
)
"""The closed set of reviewed Motion & Time clocks this build directs.

A plan is accepted only when its bound digest is one of these AND the clock it
restates is exactly the clock that digest resolves to -- a document cannot claim
one clock while binding another. This is a closed set, never a shape test: any
other digest, however internally consistent, is refused outright.
"""

MAX_TIMELINE_FPS: Final = 240
"""Phase 17's own upper bound on a plausible frame rate, restated as data."""

MAX_TIMELINE_FRAME: Final = 100_000
"""Phase 17's own upper bound on a plausible frame number, restated as data."""

SHOT_ID_FORM: Final = "shot_%04d"
"""A shot identifier is positional and nothing else, so it is derivable."""

TOP_LEVEL_KEYS: Final = frozenset(
    {"format", "schema_version", "shots", "source", "timeline", "unshown"}
)
"""Exactly the top-level keys a shot direction plan carries."""

SOURCE_KEYS: Final = frozenset(
    {
        "catalogue_sha256",
        "episode",
        "mode",
        "motion_time_format",
        "motion_time_schema_version",
        "motion_time_sha256",
        "previous_episode",
        "story_plan_sha256",
        "story_schema_version",
    }
)
"""Exactly the keys binding a plan to the documents it directed.

``story_plan_sha256`` is the digest of the story plan's own canonical bytes;
``motion_time_sha256`` is the digest of the exact Phase 17 Motion & Time Spec
bytes the clock was resolved from, and must be one of the reviewed pinned
sources; ``catalogue_sha256`` is the digest of the approved camera anchor
catalogue's canonical serialization, recomputed and enforced by this validator
-- so a shot plan names not merely an episode and a frame count but the exact
story, the exact locked clock, and the exact approved camera set it was cut for.
Pairing it with a different story plan, an invented alternate clock, or a
tampered catalogue is refused rather than silently accepted.
"""

TIMELINE_KEYS: Final = frozenset(
    {
        "end_frame",
        "end_hold_frames",
        "fps",
        "start_frame",
        "start_hold_frames",
        "transition_end",
        "transition_frames",
        "transition_start",
    }
)
"""Exactly the Phase 17 timeline facts a shot plan restates.

The six source fields are copied from the Motion & Time Spec the plan was cut
against, and the two derived boundaries must equal Phase 17's own arithmetic
over them -- ``transition_start = start_frame + start_hold_frames``,
``transition_end = transition_start + transition_frames``, and the declared
``end_frame`` must close the sum. Phase 22 invents no frames; these values exist
so a consumer can prove which clock the shots were cut against, and a timeline
that disagrees with its own phases is refused outright.
"""

SHOT_KEYS: Final = frozenset(
    {
        "camera_anchor_id",
        "emphasis",
        "end_frame",
        "kind",
        "reason_code",
        "shot_id",
        "source_beat_ids",
        "start_frame",
    }
)
"""Exactly the keys a shot carries."""

UNSHOWN_KEYS: Final = frozenset({"beat_id", "reason_code"})
"""Exactly the keys an unshown-beat entry carries."""


def _require_document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    for key in value:
        if type(key) is not str:
            raise TypeError(f"{description} keys must be str, got {type(key).__name__}")
    return cast(dict[str, JsonValue], value)


def _require_list(value: object, description: str) -> list[JsonValue]:
    if type(value) is not list:
        raise TypeError(f"{description} must be a list, got {type(value).__name__}")
    return cast(list[JsonValue], value)


def _require_member(value: object, allowed: tuple[str, ...], description: str) -> str:
    text = require_text(value, description)
    if text not in allowed:
        raise ValueError(f"{description} is {text!r}; expected one of {list(allowed)}")
    return text


def _validate_timeline(value: object) -> dict[str, int]:
    description = "shot direction plan timeline"
    timeline = _require_document(value, description)
    require_exact_keys(timeline, TIMELINE_KEYS, description)
    resolved: dict[str, int] = {}
    for field in sorted(TIMELINE_KEYS):
        resolved[field] = require_exact_int(timeline.get(field), f"{description} {field}")
    if not 1 <= resolved["fps"] <= MAX_TIMELINE_FPS:
        raise ValueError(
            f"{description} fps must be within [1, {MAX_TIMELINE_FPS}], got {resolved['fps']}"
        )
    for field in ("start_frame", "end_frame", "transition_start", "transition_end"):
        if resolved[field] > MAX_TIMELINE_FRAME:
            raise ValueError(
                f"{description} {field} must be within [0, {MAX_TIMELINE_FRAME}], "
                f"got {resolved[field]}"
            )
    for field in ("start_hold_frames", "transition_frames", "end_hold_frames"):
        if not 1 <= resolved[field] <= MAX_TIMELINE_FRAME:
            raise ValueError(
                f"{description} {field} must be within [1, {MAX_TIMELINE_FRAME}], "
                f"got {resolved[field]}"
            )
    expected_transition_start = resolved["start_frame"] + resolved["start_hold_frames"]
    expected_transition_end = expected_transition_start + resolved["transition_frames"]
    expected_end = expected_transition_end + resolved["end_hold_frames"]
    if (
        resolved["transition_start"] != expected_transition_start
        or resolved["transition_end"] != expected_transition_end
        or resolved["end_frame"] != expected_end
    ):
        raise ValueError(
            f"{description} disagrees with its own phases: start {resolved['start_frame']} "
            f"+ hold {resolved['start_hold_frames']} + transition "
            f"{resolved['transition_frames']} + hold {resolved['end_hold_frames']} resolves "
            f"to {expected_transition_start}..{expected_transition_end}..{expected_end}, but "
            f"the timeline declares {resolved['transition_start']}.."
            f"{resolved['transition_end']}..{resolved['end_frame']}"
        )
    return resolved


def _validate_shot(
    value: object, description: str, expected_rank: int, timeline: dict[str, int]
) -> dict[str, JsonValue]:
    shot = _require_document(value, description)
    require_exact_keys(shot, SHOT_KEYS, description)

    shot_id = require_identifier(shot.get("shot_id"), f"{description} shot_id")
    expected_id = SHOT_ID_FORM % expected_rank
    if shot_id != expected_id:
        raise ValueError(
            f"{description} declares shot_id {shot_id!r} but sits at position "
            f"{expected_rank}, where the identifier is {expected_id!r}; a shot id "
            "is positional, not a free label"
        )

    kind = _require_member(shot.get("kind"), SHOT_KINDS, f"{description} kind")
    anchor = _require_member(
        shot.get("camera_anchor_id"), ANCHOR_NAMES, f"{description} camera_anchor_id"
    )

    start = require_exact_int(shot.get("start_frame"), f"{description} start_frame")
    end = require_exact_int(shot.get("end_frame"), f"{description} end_frame")
    if end < start:
        raise ValueError(f"{description} ends at frame {end} before it starts at {start}")
    if start < timeline["start_frame"] or end > timeline["end_frame"]:
        raise ValueError(
            f"{description} spans frames {start}..{end}, outside the locked timeline "
            f"{timeline['start_frame']}..{timeline['end_frame']}; Phase 22 invents no "
            "frames"
        )

    beats = _require_list(shot.get("source_beat_ids"), f"{description} source_beat_ids")
    identifiers: list[str] = []
    for position, entry in enumerate(beats):
        identifiers.append(require_identifier(entry, f"{description} source_beat_ids[{position}]"))
    if len(set(identifiers)) != len(identifiers):
        raise ValueError(f"{description} repeats a source beat id")
    if identifiers != sorted(identifiers):
        raise ValueError(f"{description} source_beat_ids must be sorted")

    emphasis = shot.get("emphasis")
    if kind == SHOT_ESTABLISHING:
        reason = _require_member(
            shot.get("reason_code"), (REASON_NEUTRAL_ESTABLISHING,), f"{description} reason_code"
        )
        if identifiers:
            raise ValueError(
                f"{description} is an establishing shot but cites beats {identifiers}; "
                "it is neutral by definition and claims no emphasis"
            )
        if anchor != ESTABLISHING_ANCHOR:
            raise ValueError(
                f"{description} is an establishing shot on {anchor!r}; the neutral "
                f"anchor is {ESTABLISHING_ANCHOR!r}"
            )
        if emphasis is not None:
            raise ValueError(
                f"{description} is an establishing shot but declares emphasis "
                f"{emphasis!r}; it carries none"
            )
    else:
        reason = _require_member(
            shot.get("reason_code"), BEAT_SHOT_REASONS, f"{description} reason_code"
        )
        if not identifiers:
            raise ValueError(
                f"{description} is a beat shot but cites no beat; every non-neutral "
                "shot is caused by a Phase 21 beat"
            )
        if len(identifiers) > 1 and reason != REASON_ADJACENT_SAME_ANCHOR_MERGED:
            raise ValueError(
                f"{description} cites {len(identifiers)} beats but carries reason "
                f"{reason!r}; only an adjacent-anchor merge puts several beats in one shot"
            )
        if reason == REASON_UNKNOWN_BEAT_KIND and anchor != ESTABLISHING_ANCHOR:
            raise ValueError(
                f"{description} carries reason {REASON_UNKNOWN_BEAT_KIND!r} on {anchor!r}; "
                "an unknown beat kind is never given a guessed viewpoint, so it sits on "
                f"{ESTABLISHING_ANCHOR!r} only"
            )
        _require_member(emphasis, EMPHASIS_LEVELS, f"{description} emphasis")

    return shot


def validate_shot_direction_plan(value: object) -> dict[str, JsonValue]:
    """Verify a document's Shot Direction Plan V1 envelope, and return it.

    Checks the exact key sets at every governed level, the format tag and schema
    version, the story-plan and Motion & Time Spec bindings, the restated
    Phase 17 timeline (including that it agrees with its own phase arithmetic
    and that it is exactly what the bound reviewed digest resolves to),
    and every shot: that its anchor comes from the closed catalogue, its kind,
    reason and emphasis agree and come from the closed vocabularies, its declared
    id matches its position, its frames lie inside the locked timeline, and that
    non-neutral shots cite the beat that caused them.

    Three whole-document rules are enforced too, because they are what make the
    plan directable rather than merely well formed:

    * the shots tile the timeline exactly -- no gap, no overlap, no frame twice
    * adjacent shots never share an anchor, since a cut to the same camera is
      not a cut
    * the first and last frame are on the same anchor, so the Phase 17 loop
      closes visually as well as physically

    This validator is deliberately self-contained: it proves everything the plan
    can prove about itself, and nothing that needs the source documents. Whether
    the plan's claims agree with the actual story plan and the actual Motion &
    Time Spec is proven by
    :func:`living_diorama.cinematic.cinematic_cross_check.validate_shot_direction_plan_against_story`,
    which takes those sources as arguments.

    Raises:
        TypeError: If any value has the wrong Python type.
        ValueError: If any key set, vocabulary member, ordering, bound or
            internal agreement is violated.
    """
    document = _require_document(value, "shot direction plan")
    require_exact_keys(document, TOP_LEVEL_KEYS, "shot direction plan")

    tag = require_text(document.get("format"), "shot direction plan format")
    if tag != SHOT_PLAN_FORMAT:
        raise ValueError(
            f"shot direction plan declares format {tag!r}; this build reads "
            f"{SHOT_PLAN_FORMAT!r} only"
        )
    version = require_exact_int(
        document.get("schema_version"), "shot direction plan schema_version"
    )
    if version != SHOT_SCHEMA_VERSION:
        raise ValueError(
            f"shot direction plan declares unsupported schema version {version}; "
            f"this build reads version {SHOT_SCHEMA_VERSION} only"
        )

    source = _require_document(document.get("source"), "shot direction plan source")
    require_exact_keys(source, SOURCE_KEYS, "shot direction plan source")
    mode = require_text(source.get("mode"), "shot direction plan source mode")
    if mode not in ("baseline", "transition"):
        raise ValueError(
            f"shot direction plan source mode is {mode!r}; expected 'baseline' or 'transition'"
        )
    episode = require_exact_int(source.get("episode"), "shot direction plan source episode")
    story_version = require_exact_int(
        source.get("story_schema_version"), "shot direction plan source story_schema_version"
    )
    if story_version != SUPPORTED_STORY_SCHEMA_VERSION:
        raise ValueError(
            f"shot direction plan was derived from story schema version "
            f"{story_version}; this build directs version "
            f"{SUPPORTED_STORY_SCHEMA_VERSION} only"
        )
    require_hash_hex(
        source.get("story_plan_sha256"), "shot direction plan source story_plan_sha256"
    )
    motion_tag = require_text(
        source.get("motion_time_format"), "shot direction plan source motion_time_format"
    )
    if motion_tag != MOTION_TIME_FORMAT:
        raise ValueError(
            f"shot direction plan was cut against motion format {motion_tag!r}; "
            f"this build directs against {MOTION_TIME_FORMAT!r} only"
        )
    motion_version = require_exact_int(
        source.get("motion_time_schema_version"),
        "shot direction plan source motion_time_schema_version",
    )
    if motion_version != SUPPORTED_MOTION_SCHEMA_VERSION:
        raise ValueError(
            f"shot direction plan was cut against motion schema version {motion_version}; "
            f"this build directs against version {SUPPORTED_MOTION_SCHEMA_VERSION} only"
        )
    motion_digest = require_hash_hex(
        source.get("motion_time_sha256"), "shot direction plan source motion_time_sha256"
    )
    if motion_digest not in REVIEWED_CLOCKS:
        raise ValueError(
            f"shot direction plan was cut against motion time spec {motion_digest}, "
            f"which is not the canonical Phase 17 source this build was reviewed "
            f"against (admissible reviewed clocks: {', '.join(sorted(REVIEWED_CLOCKS))})"
        )
    supplied_catalogue = require_hash_hex(
        source.get("catalogue_sha256"), "shot direction plan source catalogue_sha256"
    )
    approved_catalogue = catalogue_sha256()
    if supplied_catalogue != approved_catalogue:
        raise ValueError(
            f"shot direction plan binds camera catalogue {supplied_catalogue}, which is "
            f"not the approved canonical catalogue ({approved_catalogue}); the fourteen "
            "world-built anchors are closed and a plan cut for any other set is refused"
        )
    previous = source.get("previous_episode")
    if mode == "baseline":
        if previous is not None:
            raise ValueError("shot direction plan is baseline mode but names a previous episode")
        if episode != 0:
            raise ValueError(
                f"shot direction plan is baseline mode but describes episode {episode}; "
                "a baseline describes episode 0 only"
            )
    else:
        previous_episode = require_exact_int(
            previous, "shot direction plan source previous_episode"
        )
        if episode != previous_episode + 1:
            raise ValueError(
                f"shot direction plan binds episode {previous_episode} then episode "
                f"{episode}; a transition joins consecutive episodes"
            )

    timeline = _validate_timeline(document.get("timeline"))

    # The bound digest and the restated clock must name the same document: a
    # plan that binds a reviewed digest but restates the OTHER reviewed clock's
    # timeline (or any hand-edited one) claims one clock while binding another.
    expected_timeline = dict(REVIEWED_CLOCKS[motion_digest])
    if timeline != expected_timeline:
        raise ValueError(
            f"shot direction plan restates timeline {timeline!r}, but the reviewed "
            f"motion time spec {motion_digest} resolves to {expected_timeline!r}; a plan "
            "restates exactly the clock its bound digest resolves to"
        )

    shots = _require_list(document.get("shots"), "shot direction plan shots")
    if not shots:
        raise ValueError(
            "shot direction plan carries no shots; every episode is directed, even a neutral one"
        )

    validated: list[dict[str, JsonValue]] = []
    for position, shot in enumerate(shots):
        validated.append(
            _validate_shot(shot, f"shot direction plan shots[{position}]", position + 1, timeline)
        )

    # The shots must tile the locked timeline exactly.
    cursor = timeline["start_frame"]
    for position, shot in enumerate(validated):
        start = cast(int, shot["start_frame"])
        end = cast(int, shot["end_frame"])
        if start != cursor:
            raise ValueError(
                f"shot direction plan shots[{position}] starts at frame {start} but the "
                f"previous shot left off at {cursor}; the shots tile the timeline with "
                "no gap and no overlap"
            )
        cursor = end + 1
    if cursor != timeline["end_frame"] + 1:
        raise ValueError(
            f"shot direction plan covers frames up to {cursor - 1}, but the timeline "
            f"ends at {timeline['end_frame']}; every frame is directed"
        )

    # A cut to the same camera is not a cut.
    for position in range(1, len(validated)):
        before = validated[position - 1]["camera_anchor_id"]
        after = validated[position]["camera_anchor_id"]
        if before == after:
            raise ValueError(
                f"shot direction plan shots[{position}] cuts to {after!r}, which the "
                "previous shot was already on; adjacent shots never share an anchor"
            )

    # Loop closure: Phase 17 guarantees frame 1 and the final frame are the same
    # world (frame 193 on the canonical clock, frame 315 on the Director V4 one).
    if validated[0]["camera_anchor_id"] != validated[-1]["camera_anchor_id"]:
        raise ValueError(
            f"shot direction plan opens on {validated[0]['camera_anchor_id']!r} and "
            f"closes on {validated[-1]['camera_anchor_id']!r}; the Phase 17 loop is "
            "frame-equivalent, so the camera must match at both ends or the loop jumps"
        )

    seen_ids: set[str] = set()
    seen_beats: set[str] = set()
    for position, shot in enumerate(validated):
        shot_id = cast(str, shot["shot_id"])
        if shot_id in seen_ids:
            raise ValueError(f"shot direction plan repeats shot_id {shot_id!r}")
        seen_ids.add(shot_id)
        for beat_id in cast(list[str], shot["source_beat_ids"]):
            if beat_id in seen_beats:
                raise ValueError(
                    f"shot direction plan shots[{position}] cites beat {beat_id!r}, "
                    "which another shot already cites; a beat is shown once"
                )
            seen_beats.add(beat_id)

    unshown = _require_list(document.get("unshown"), "shot direction plan unshown")
    for position, entry in enumerate(unshown):
        label = f"shot direction plan unshown[{position}]"
        record = _require_document(entry, label)
        require_exact_keys(record, UNSHOWN_KEYS, label)
        beat_id = require_identifier(record.get("beat_id"), f"{label} beat_id")
        _require_member(record.get("reason_code"), UNSHOWN_REASONS, f"{label} reason_code")
        if beat_id in seen_beats:
            raise ValueError(f"{label} lists beat {beat_id!r} as unshown, but a shot cites it")
        seen_beats.add(beat_id)

    return document
