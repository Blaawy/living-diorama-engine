"""Shot Direction Plan V2: the V1 contract plus OPTIONAL per-shot camera movement.

V2 is a strict superset of V1, nothing else. A shot direction plan that carries
no ``camera_movement`` key anywhere is validated by EXACTLY the V1 code path
(``validate_shot_direction_plan`` is delegated to unchanged), so every golden
V1 fixture validates identically under this module today. The format tag and
``schema_version`` stay the V1 values: V2 is an additive extension of the same
document shape, and a version bump would make a zero-movement plan refuse
under V1 while validating here, which would break the identity guarantee.

When a shot DOES carry ``camera_movement``, that block is governed here and
nowhere else. It is strictly optional: a shot without the key is subject to the
identical rules the V1 validator applies, plus nothing.

The movement block is a statement about the camera the plan selects, not a
replacement for it. V1's rule that Phase 22 never creates, moves, rotates or
animates the FIXED anchors is untouched: ``camera_movement`` describes a NEW,
separate camera identity (realised by ``apply_camera_movement.py``), never the
anchor the shot names. The validator here cannot know whether such a camera can
actually render -- that is decided by the render executor's closed anchor
catalogue, which this module neither extends nor modifies (see the Step 1
findings in the camera movement subsystem report).

``reason_for_move`` is mechanically bound to the shot it sits on: it must
contain the shot's own real ``reason_code`` value, or one of the shot's real
``source_beat_ids``, as a substring. A generic "make it more cinematic" string
that references neither is refused, not warned about -- an unmotivated camera
move is exactly the kind of improvisation this layer exists to prevent.

Transform representation: ``start_transform`` and ``end_transform`` reuse the
exact pose vocabulary the approved camera anchors already use in
``cinematic_spec`` -- a ``location``, the ``look_at`` point its orientation is
derived from, and the ``lens_mm`` -- in the same JSON form the catalogue's
canonical serialization uses (tuples as lists of three numbers). No new
coordinate convention is invented.

The optional ``settle_frame`` field (only ever present on a ``closing_wider``
movement under the Director-revision grammar) names the frame at which the
movement's camera first reaches its fully-settled ``end_transform`` pose. The
Blender applier places its second keyframe there, and every later frame --
including the shot's final playback frame ``end_frame - 1`` and the closure
witness ``end_frame`` -- samples that same settled pose, so the render
pipeline's witness comparison measures pure sampling noise rather than a
still-running ease-out tail. The field is validated to lie inside the shot's
own frame window.
"""

from typing import Final, cast

from living_diorama.cinematic.cinematic_schema_v1 import (
    MOTION_TIME_FORMAT,
    REVIEWED_CLOCKS,
    SHOT_ID_FORM,
    SHOT_PLAN_FORMAT,
    SHOT_SCHEMA_VERSION,
    SOURCE_KEYS,
    SUPPORTED_MOTION_SCHEMA_VERSION,
    SUPPORTED_STORY_SCHEMA_VERSION,
    TOP_LEVEL_KEYS,
    UNSHOWN_KEYS,
    _require_document,
    _require_list,
    _require_member,
    _validate_timeline,
    validate_shot_direction_plan,
)
from living_diorama.cinematic.cinematic_spec import (
    ANCHOR_NAMES,
    BEAT_SHOT_REASONS,
    ESTABLISHING_ANCHORS,
    REASON_ADJACENT_SAME_ANCHOR_MERGED,
    REASON_NEUTRAL_ESTABLISHING,
    REASON_UNKNOWN_BEAT_KIND,
    SHOT_ESTABLISHING,
    SHOT_KINDS,
    STATIC_DRONE_ANCHOR,
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

MOVEMENT_TYPES: Final = (
    "STATIC",
    "PAN",
    "TILT",
    "TRACK",
    "PUSH_IN",
    "PULL_OUT",
    "REVEAL",
)
"""Every movement this build knows, and nothing else.

``STATIC`` is a deliberate hold -- a camera_movement block declaring that the
shot's camera does not move, recorded so a reviewer can see the hold was
chosen rather than defaulted. ``PAN`` and ``TILT`` rotate about a fixed
location; ``TRACK`` translates; ``PUSH_IN``/``PULL_OUT`` move the location
along the view axis; ``REVEAL`` reframes to open the composition.
"""

EASINGS: Final = ("LINEAR", "EASE_IN_OUT")
"""The easing vocabulary. ``EASE_IN_OUT`` is smoothstep (``3t^2 - 2t^3``)."""

TRANSFORM_KEYS: Final = frozenset({"location", "look_at", "lens_mm"})
"""Exactly the keys a movement endpoint carries, matching the anchor pose subset.

``location`` and ``look_at`` are the same three-number world-space vectors the
camera catalogue uses, and ``lens_mm`` is the same lens field -- nothing is
invented, and an endpoint that adds or drops a key is refused.
"""

CAMERA_MOVEMENT_KEYS: Final = frozenset(
    {
        "movement_type",
        "start_transform",
        "end_transform",
        "easing",
        "reason_for_move",
    }
)
"""Exactly the keys a camera_movement block carries without a settle frame.

Every V1 movement and every V2 movement except the Director-revision
``closing_wider`` role validates against this set, exactly as today.
"""

CAMERA_MOVEMENT_KEYS_WITH_SETTLE: Final = CAMERA_MOVEMENT_KEYS | {"settle_frame"}
"""The key set for a movement that also carries ``settle_frame``.

``settle_frame`` is OPTIONAL the same way ``camera_movement`` is optional on a
shot (see ``SHOT_KEYS_V2``): presence, not an optional slot inside one exact
set, decides which key set governs. It names the frame at which a closing
movement's camera first reaches its settled ``end_transform`` pose, and is
checked to lie inside the shot's own frame window.
"""

SHOT_KEYS_V2: Final = frozenset(
    {
        "camera_anchor_id",
        "camera_movement",
        "emphasis",
        "end_frame",
        "kind",
        "reason_code",
        "shot_id",
        "source_beat_ids",
        "start_frame",
    }
)
"""The V2 shot key set: the V1 eight keys plus the OPTIONAL ``camera_movement``."""

TRANSFORM_EPSILON: Final = 1e-6
"""Slack for comparing movement endpoints, matching the applier tolerances."""

MIN_LENS_MM: Final = 5.0
MAX_LENS_MM: Final = 200.0
"""A plausible lens range for a movement camera; the fixed anchors sit in it."""

MIN_VIEW_DISTANCE: Final = 1.0
"""A camera must stay at least one world unit from its look-at point."""


def _require_vector3(value: object, description: str) -> tuple[float, float, float]:
    if type(value) is not list or len(value) != 3:
        raise ValueError(f"{description} must be a list of three numbers, got {value!r}")
    components: list[float] = []
    for position, component in enumerate(value):
        if type(component) not in (int, float) or isinstance(component, bool):
            raise ValueError(f"{description}[{position}] must be a number, got {component!r}")
        components.append(float(component))
    return (components[0], components[1], components[2])


def _vector_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return float(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5)


def reason_for_move_is_bound(reason_for_move: object, shot: dict[str, JsonValue]) -> bool:
    """Return whether ``reason_for_move`` mechanically references the shot itself.

    The reference is a substring match against the shot's own real ``reason_code``
    value, or against one of the shot's real ``source_beat_ids``. Both are data
    this shot already carries, so the check is mechanical: a string that names
    neither the cause nor the subject it moves for is unmotivated.
    """
    if type(reason_for_move) is not str or not reason_for_move.strip():
        return False
    reason_code = shot.get("reason_code")
    if type(reason_code) is str and reason_code and reason_code in reason_for_move:
        return True
    beat_ids = shot.get("source_beat_ids")
    if type(beat_ids) is list:
        for beat_id in beat_ids:
            if type(beat_id) is str and beat_id and beat_id in reason_for_move:
                return True
    return False


def _require_reason_bound(reason_for_move: object, shot: dict[str, JsonValue]) -> str:
    if not reason_for_move_is_bound(reason_for_move, shot):
        reason_code = shot.get("reason_code")
        beat_ids = shot.get("source_beat_ids")
        raise ValueError(
            f"camera_movement reason_for_move {reason_for_move!r} references neither "
            f"the shot's own reason_code {reason_code!r} nor any of its source "
            f"beat ids {beat_ids!r}; an unmotivated camera move is refused"
        )
    return cast(str, reason_for_move)


def _require_transform(value: object, description: str) -> dict[str, JsonValue]:
    transform = _require_document(value, description)
    require_exact_keys(transform, TRANSFORM_KEYS, description)
    location = _require_vector3(transform.get("location"), f"{description} location")
    look_at = _require_vector3(transform.get("look_at"), f"{description} look_at")
    if _vector_distance(location, look_at) < MIN_VIEW_DISTANCE:
        raise ValueError(
            f"{description} places the camera within {MIN_VIEW_DISTANCE} unit of its "
            "look_at point; a camera must stand off its subject"
        )
    lens = transform.get("lens_mm")
    if type(lens) not in (int, float) or isinstance(lens, bool):
        raise ValueError(f"{description} lens_mm must be a number, got {lens!r}")
    if not MIN_LENS_MM <= float(cast("int | float", lens)) <= MAX_LENS_MM:
        raise ValueError(
            f"{description} lens_mm {lens!r} is outside [{MIN_LENS_MM}, {MAX_LENS_MM}]"
        )
    return transform


def validate_camera_movement(
    value: object, shot: dict[str, JsonValue], description: str
) -> dict[str, JsonValue]:
    """Verify one camera_movement block, and return it.

    Checks the exact key set, the movement vocabulary, the endpoint shapes
    (exactly the anchor pose representation), the easing vocabulary, the
    mechanical ``reason_for_move`` binding, and that the declared movement type
    is consistent with the endpoints -- a PAN that moves the location is not a
    pan, a PUSH_IN that moves away is not a push-in, a STATIC whose endpoints
    differ is not static. An optional ``settle_frame`` (the closing movement's
    settled-pose frame) must lie inside the shot's own frame window.

    Raises:
        TypeError: If a value has the wrong Python type.
        ValueError: If a key set, vocabulary member, endpoint or binding is
            violated, or the endpoints contradict the movement type.
    """
    movement = _require_document(value, description)
    settle = movement.get("settle_frame")
    if settle is None:
        require_exact_keys(movement, CAMERA_MOVEMENT_KEYS, description)
    else:
        require_exact_keys(movement, CAMERA_MOVEMENT_KEYS_WITH_SETTLE, description)
        settle_value = require_exact_int(settle, f"{description} settle_frame")
        shot_start = cast(int, shot["start_frame"])
        shot_end = cast(int, shot["end_frame"])
        if not shot_start <= settle_value <= shot_end:
            raise ValueError(
                f"{description} settle_frame {settle_value} lies outside the shot's "
                f"window {shot_start}..{shot_end}; a camera settles inside the shot it "
                "moves in or not at all"
            )

    movement_type = _require_member(
        movement.get("movement_type"), MOVEMENT_TYPES, f"{description} movement_type"
    )
    _require_member(movement.get("easing"), EASINGS, f"{description} easing")
    _require_reason_bound(movement.get("reason_for_move"), shot)
    start = _require_transform(movement.get("start_transform"), f"{description} start_transform")
    end = _require_transform(movement.get("end_transform"), f"{description} end_transform")

    start_location = _require_vector3(start["location"], f"{description} start_transform location")
    end_location = _require_vector3(end["location"], f"{description} end_transform location")
    start_look = _require_vector3(start["look_at"], f"{description} start_transform look_at")
    end_look = _require_vector3(end["look_at"], f"{description} end_transform look_at")

    location_moved = _vector_distance(start_location, end_location) > TRANSFORM_EPSILON
    look_moved = _vector_distance(start_look, end_look) > TRANSFORM_EPSILON
    start_distance = _vector_distance(start_location, start_look)
    end_distance = _vector_distance(end_location, end_look)

    if movement_type == "STATIC":
        if location_moved or look_moved:
            raise ValueError(
                f"{description} is STATIC but its endpoints differ; a static hold keeps one pose"
            )
    elif movement_type == "PAN":
        if location_moved:
            raise ValueError(
                f"{description} is a PAN but moves its location; a pan rotates in place"
            )
        if not look_moved:
            raise ValueError(f"{description} is a PAN but its look_at does not change")
        if abs(end_look[2] - start_look[2]) > TRANSFORM_EPSILON:
            raise ValueError(
                f"{description} is a PAN but changes the look_at height; a pan rotates "
                "about the vertical axis"
            )
    elif movement_type == "TILT":
        if location_moved:
            raise ValueError(
                f"{description} is a TILT but moves its location; a tilt rotates in place"
            )
        if not look_moved:
            raise ValueError(f"{description} is a TILT but its look_at does not change")
        if abs(end_look[2] - start_look[2]) <= TRANSFORM_EPSILON:
            raise ValueError(
                f"{description} is a TILT but keeps the look_at height; a tilt rotates "
                "about a horizontal axis"
            )
    elif movement_type == "REVEAL":
        if location_moved:
            raise ValueError(
                f"{description} is a REVEAL but moves its location; a reveal reframes in place"
            )
        if not look_moved:
            raise ValueError(f"{description} is a REVEAL but its look_at does not change")
    elif movement_type == "TRACK":
        if not location_moved:
            raise ValueError(f"{description} is a TRACK but its location does not change")
    elif movement_type == "PUSH_IN":
        if not location_moved:
            raise ValueError(f"{description} is a PUSH_IN but its location does not change")
        if not start_distance > end_distance + TRANSFORM_EPSILON:
            raise ValueError(
                f"{description} is a PUSH_IN but ends {end_distance} units from the "
                f"look_at point versus {start_distance} at start; a push-in moves closer"
            )
    elif movement_type == "PULL_OUT":
        if not location_moved:
            raise ValueError(f"{description} is a PULL_OUT but its location does not change")
        if not end_distance > start_distance + TRANSFORM_EPSILON:
            raise ValueError(
                f"{description} is a PULL_OUT but ends {end_distance} units from the "
                f"look_at point versus {start_distance} at start; a pull-out moves away"
            )

    return movement


def _validate_shot_v2(
    value: object, description: str, expected_rank: int, timeline: dict[str, int]
) -> dict[str, JsonValue]:
    shot = _require_document(value, description)
    require_exact_keys(shot, SHOT_KEYS_V2, description)

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
        if anchor not in ESTABLISHING_ANCHORS:
            raise ValueError(
                f"{description} is an establishing shot on {anchor!r}; the permitted "
                f"neutral anchors are {', '.join(repr(a) for a in ESTABLISHING_ANCHORS)}"
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
        # The same closed set as the establishing law: an unknown beat kind is
        # never given a GUESSED viewpoint, but the static-drone anchor is not a
        # guess -- under the V5 lane it is the one pose the whole episode is
        # locked to, so an unknown kind sits on it for the same reason every
        # other shot does. Any third anchor is still refused.
        if reason == REASON_UNKNOWN_BEAT_KIND and anchor not in ESTABLISHING_ANCHORS:
            raise ValueError(
                f"{description} carries reason {REASON_UNKNOWN_BEAT_KIND!r} on {anchor!r}; "
                "an unknown beat kind is never given a guessed viewpoint, so it sits on "
                f"one of {ESTABLISHING_ANCHORS!r} only"
            )
        _require_member(emphasis, EMPHASIS_LEVELS, f"{description} emphasis")

    movement = shot.get("camera_movement")
    if movement is not None:
        validate_camera_movement(movement, shot, f"{description} camera_movement")

    return shot


def validate_shot_direction_plan_v2(value: object) -> dict[str, JsonValue]:
    """Verify a Shot Direction Plan document under V2, and return it.

    A plan in which NO shot carries the ``camera_movement`` key at all is handed
    to the V1 validator unchanged -- the exact V1 code path, so acceptance,
    refusal and returned value are identical to V1 today. A plan in which some
    shot carries the key (even as ``null``, a V2-only shape) is validated by the
    same envelope rules with the V2 shot key set and per-shot movement
    validation added.

    Raises:
        TypeError: If any value has the wrong Python type.
        ValueError: If any key set, vocabulary member, ordering, bound or
            internal agreement is violated, including any camera_movement block.
    """
    document = _require_document(value, "shot direction plan")

    # Fast path: no movement key anywhere means V1 identity, by delegation.
    shots_value = document.get("shots")
    if type(shots_value) is not list:
        return validate_shot_direction_plan(document)
    if all(type(shot) is not dict or "camera_movement" not in shot for shot in shots_value):
        return validate_shot_direction_plan(document)

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

    shots = _require_list(document.get("shots"), "shot direction plan shots")
    if not shots:
        raise ValueError(
            "shot direction plan carries no shots; every episode is directed, even a neutral one"
        )

    validated: list[dict[str, JsonValue]] = []
    for position, shot in enumerate(shots):
        description = f"shot direction plan shots[{position}]"
        validated.append(_validate_shot_v2(shot, description, position + 1, timeline))

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
        # Closed exception: the V5 absolutely-static drone lane performs no cuts
        # -- the camera never moves, so a repeat there is the intended single
        # continuous take, not a degenerate cut. The rule protects against a cut
        # that changes nothing; a lane that never cuts cannot violate it. One
        # reviewed anchor only (STATIC_DRONE_ANCHOR); a third anchor shared
        # across a cut is still refused.
        if before == after and after != STATIC_DRONE_ANCHOR:
            raise ValueError(
                f"shot direction plan shots[{position}] cuts to {after!r}, which the "
                "previous shot was already on; adjacent shots never share an anchor -- "
                f"the sole permitted repeat is the static-drone anchor "
                f"{STATIC_DRONE_ANCHOR!r}, held as one continuous take"
            )

    # Loop closure: Phase 17 guarantees frame 1 and the last frame are the same world.
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
