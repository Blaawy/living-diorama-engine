"""Episode Narration Delivery Plan format V1: the slot contract.

A delivery plan is presentation scheduling bound to authoritative document
identity. It says, for every unit of one Episode Narration Plan, the inclusive
span of playback frames in which that unit may be delivered, and how the span
was derived: anchored to the shot that frames the unit's beat, or allocated to
a unit no camera framed. It asserts nothing about wording, nothing about
visibility, and nothing about the world -- those live in the documents it
binds, and stay there.

Two allocation policies are closed and reviewed: the v1 equal partition and the
v4 content-proportional partition. Every plan declares which one cut its slots,
and a plan cut under any other identifier is refused, never guessed at.

The document shape is exact at every level this module governs. A key that is
missing means the plan is incomplete; a key that is extra means it was written
by something this contract does not describe. Both are refused, never repaired.

This validator is deliberately self-contained: it proves everything the plan
can prove about itself, including the slot arithmetic the timeline block makes
checkable. Whether the plan's claims are true *of* the narration plan and the
shot plan it names is proven by
:func:`living_diorama.narration_delivery.delivery_cross_check.validate_narration_delivery_plan_against_sources`,
which takes those sources as arguments.
"""

from typing import Final, cast

from living_diorama.cinematic.cinematic_schema_v1 import (
    MAX_TIMELINE_FPS,
    MAX_TIMELINE_FRAME,
)
from living_diorama.narration.narration_schema_v1 import (
    MODE_BASELINE,
    PLAN_MODES,
    UNIT_ID_FORM,
)
from living_diorama.narration_delivery.delivery_spec import (
    DELIVERY_ID_FORM,
    DELIVERY_PLAN_FORMAT,
    DELIVERY_POLICY_V1,
    DELIVERY_POLICY_V4,
    DELIVERY_SCHEMA_VERSION,
    PLACEMENT_CLASSES,
    PLACEMENT_SHOT_ANCHORED,
    playback_domain,
)
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_identifier,
    require_text,
)

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in.

Declared here rather than imported from the narration layer for the same reason
Phase 24 declares its own: a shared alias is not worth a hole in a boundary.
"""

SUPPORTED_NARRATION_SCHEMA_VERSION: Final = 1
SUPPORTED_SHOT_SCHEMA_VERSION: Final = 1
"""The upstream contract versions this build schedules."""

TOP_LEVEL_KEYS: Final = frozenset(
    {"accounting", "deliveries", "format", "policy", "schema_version", "source", "timeline"}
)
"""Exactly the top-level keys an episode narration delivery plan carries."""

SOURCE_KEYS: Final = frozenset(
    {
        "episode",
        "mode",
        "motion_time_sha256",
        "narration_plan_sha256",
        "narration_schema_version",
        "previous_episode",
        "shot_plan_sha256",
        "shot_schema_version",
    }
)
"""Exactly the keys binding a plan to the documents it schedules.

Two digests, because delivery joins two documents that must be the same
episode's: the narration plan whose units it schedules and the shot plan whose
segments host them. The narration plan already binds its own story and export
by digest, so those are inherited rather than restated -- duplicating a chain
the cross-check can walk would add copies, not proof.

``motion_time_sha256`` is the one deliberate restatement: this plan restates
resolved clock values in its timeline block, and a resolved clock is pinned
beside the digest of the source that produces it, exactly as Phase 22 and
Phase 23 pin theirs. There is deliberately no render plan or render manifest
binding: a delivery slot is semantic presentation time, settled before a pixel
exists, and a plan that bound execution proof would stop surviving the
re-render of an unchanged episode.
"""

DELIVERY_TIMELINE_KEYS: Final = frozenset(
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
"""Exactly the Phase 17 timeline facts a delivery plan restates.

Restated key-for-key from the Shot Direction Plan rather than imported from the
cinematic package, for the same reason Phase 24 restates the unshown-reason
vocabulary: this contract's shape belongs to this schema version, and a test
asserts the two key sets still agree so drift fails loudly. The two derived
boundaries must equal Phase 17's own arithmetic over the six source fields, and
the cross-check separately proves the whole block equals the offered shot
plan's, so an invented clock dies twice.
"""

DELIVERY_KEYS: Final = frozenset(
    {"delivery_id", "end_frame", "placement", "start_frame", "unit_id"}
)
"""Exactly the keys a delivery record carries.

Deliberately no text, no visibility, no emphasis, no shot citation and no
seconds: wording and visibility stay authoritative in the narration plan the
record's ``unit_id`` names, the hosting shot is re-derivable from the sources,
and frames are the only time unit this layer speaks. A record is a slot and an
identity, nothing more.
"""

ACCOUNTING_KEYS: Final = frozenset({"allocated_unshown", "deliveries_total", "shot_anchored"})
"""Exactly the keys the accounting block carries.

The aggregate verdict, stated in a way a truncated plan cannot fake.
"""


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


def _require_null(value: object, description: str, because: str) -> None:
    if value is not None:
        raise ValueError(f"{description} is {value!r}, but {because}")


def _validate_timeline(value: object) -> dict[str, JsonValue]:
    """Verify the restated clock closes on its own arithmetic, and return it."""
    timeline = _require_document(value, "narration delivery plan timeline")
    require_exact_keys(timeline, DELIVERY_TIMELINE_KEYS, "narration delivery plan timeline")
    resolved = {
        key: require_exact_int(timeline.get(key), f"narration delivery plan timeline {key}")
        for key in sorted(DELIVERY_TIMELINE_KEYS)
    }
    # The bounds are Phase 22's own, enforced with Phase 22's own exported
    # constants, so a restated clock is held to exactly the standard its source
    # was -- no stricter, no looser, and immune to drift between the two.
    if not 1 <= resolved["fps"] <= MAX_TIMELINE_FPS:
        raise ValueError(
            f"narration delivery plan timeline fps must be within [1, {MAX_TIMELINE_FPS}], "
            f"got {resolved['fps']}"
        )
    for key in ("start_frame", "end_frame", "transition_start", "transition_end"):
        if resolved[key] > MAX_TIMELINE_FRAME:
            raise ValueError(
                f"narration delivery plan timeline {key} must be within "
                f"[0, {MAX_TIMELINE_FRAME}], got {resolved[key]}"
            )
    for key in ("start_hold_frames", "transition_frames", "end_hold_frames"):
        if not 1 <= resolved[key] <= MAX_TIMELINE_FRAME:
            raise ValueError(
                f"narration delivery plan timeline {key} must be within "
                f"[1, {MAX_TIMELINE_FRAME}], got {resolved[key]}"
            )
    expected_start = resolved["start_frame"] + resolved["start_hold_frames"]
    if resolved["transition_start"] != expected_start:
        raise ValueError(
            f"narration delivery plan timeline declares transition_start "
            f"{resolved['transition_start']}, but its own phases resolve to {expected_start}"
        )
    expected_end = resolved["transition_start"] + resolved["transition_frames"]
    if resolved["transition_end"] != expected_end:
        raise ValueError(
            f"narration delivery plan timeline declares transition_end "
            f"{resolved['transition_end']}, but its own phases resolve to {expected_end}"
        )
    declared_close = resolved["transition_end"] + resolved["end_hold_frames"]
    if resolved["end_frame"] != declared_close:
        raise ValueError(
            f"narration delivery plan timeline declares end_frame {resolved['end_frame']}, "
            f"but its own phases close on {declared_close}"
        )
    playback_domain(resolved["start_frame"], resolved["end_frame"])
    return timeline


def _validate_delivery(
    value: object,
    description: str,
    position: int,
    playback_first: int,
    playback_final: int,
) -> str:
    """Verify one delivery record, and return its placement class."""
    record = _require_document(value, description)
    require_exact_keys(record, DELIVERY_KEYS, description)

    delivery_id = require_identifier(record.get("delivery_id"), f"{description} delivery_id")
    expected_delivery = DELIVERY_ID_FORM % position
    if delivery_id != expected_delivery:
        raise ValueError(
            f"{description} declares delivery_id {delivery_id!r} but sits at position "
            f"{position}, where the identifier is {expected_delivery!r}; a delivery id is "
            "positional, not a free label"
        )
    unit_id = require_identifier(record.get("unit_id"), f"{description} unit_id")
    expected_unit = UNIT_ID_FORM % position
    if unit_id != expected_unit:
        raise ValueError(
            f"{description} schedules unit {unit_id!r} but sits at position {position}, "
            f"where the narration plan's unit is {expected_unit!r}; delivery follows the "
            "narration plan's own order, one slot per unit"
        )

    placement = _require_member(
        record.get("placement"), PLACEMENT_CLASSES, f"{description} placement"
    )

    start = require_exact_int(record.get("start_frame"), f"{description} start_frame")
    end = require_exact_int(record.get("end_frame"), f"{description} end_frame")
    if end < start:
        raise ValueError(f"{description} ends at frame {end} before it starts at {start}")
    if start < playback_first or end > playback_final:
        raise ValueError(
            f"{description} occupies frames [{start}, {end}], outside the playback domain "
            f"[{playback_first}, {playback_final}]; the boundary witness frame is rendered "
            "once as evidence and never played back, so nothing is ever scheduled on it"
        )
    return placement


def validate_episode_narration_delivery_plan(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Narration Delivery Plan V1 envelope, and return it.

    Checks the exact key sets at every governed level, the format tag, schema
    version and policy identity (one of the two closed policy identifiers), the
    source binding (episode, mode, the digest fields, and the rule that only a
    baseline has no previous episode), the restated timeline's own arithmetic,
    and every delivery record: that its identifiers agree with its position,
    that its placement comes from the closed vocabulary, and that its slot is a
    well-formed inclusive span inside the playback domain. Two whole-document
    rules are enforced too:

    * slots appear in order and never overlap -- for consecutive records,
      the next slot starts after the previous one ends
    * the accounting block agrees with the records actually present

    Raises:
        TypeError: If any value has the wrong Python type.
        ValueError: If any key set, vocabulary member, identity, bound,
            ordering or internal agreement is violated.
    """
    document = _require_document(value, "narration delivery plan")
    require_exact_keys(document, TOP_LEVEL_KEYS, "narration delivery plan")

    tag = require_text(document.get("format"), "narration delivery plan format")
    if tag != DELIVERY_PLAN_FORMAT:
        raise ValueError(
            f"narration delivery plan declares format {tag!r}; this build reads "
            f"{DELIVERY_PLAN_FORMAT!r} only"
        )
    version = require_exact_int(
        document.get("schema_version"), "narration delivery plan schema_version"
    )
    if version != DELIVERY_SCHEMA_VERSION:
        raise ValueError(
            f"narration delivery plan declares unsupported schema version {version}; "
            f"this build reads version {DELIVERY_SCHEMA_VERSION} only"
        )
    policy = require_text(document.get("policy"), "narration delivery plan policy")
    if policy not in (DELIVERY_POLICY_V1, DELIVERY_POLICY_V4):
        raise ValueError(
            f"narration delivery plan declares policy {policy!r}; this build derives and "
            f"validates {DELIVERY_POLICY_V1!r} (equal partition) and "
            f"{DELIVERY_POLICY_V4!r} (content-proportional partition) only, and a slot "
            "cut under another policy must never be mistaken for one of these"
        )

    source = _require_document(document.get("source"), "narration delivery plan source")
    require_exact_keys(source, SOURCE_KEYS, "narration delivery plan source")
    mode = _require_member(source.get("mode"), PLAN_MODES, "narration delivery plan source mode")
    episode = require_exact_int(source.get("episode"), "narration delivery plan source episode")
    narration_version = require_exact_int(
        source.get("narration_schema_version"),
        "narration delivery plan source narration_schema_version",
    )
    if narration_version != SUPPORTED_NARRATION_SCHEMA_VERSION:
        raise ValueError(
            f"narration delivery plan was derived from narration schema version "
            f"{narration_version}; this build schedules version "
            f"{SUPPORTED_NARRATION_SCHEMA_VERSION} only"
        )
    shot_version = require_exact_int(
        source.get("shot_schema_version"), "narration delivery plan source shot_schema_version"
    )
    if shot_version != SUPPORTED_SHOT_SCHEMA_VERSION:
        raise ValueError(
            f"narration delivery plan was derived from shot schema version {shot_version}; "
            f"this build schedules version {SUPPORTED_SHOT_SCHEMA_VERSION} only"
        )
    for field in ("motion_time_sha256", "narration_plan_sha256", "shot_plan_sha256"):
        require_hash_hex(source.get(field), f"narration delivery plan source {field}")

    previous = source.get("previous_episode")
    if mode == MODE_BASELINE:
        _require_null(
            previous,
            "narration delivery plan source previous_episode",
            "a baseline schedules one export's narration and follows no episode",
        )
        if episode != 0:
            raise ValueError(
                f"narration delivery plan is baseline mode but describes episode {episode}; "
                "a baseline describes episode 0 only"
            )
    else:
        previous_episode = require_exact_int(
            previous, "narration delivery plan source previous_episode"
        )
        if episode != previous_episode + 1:
            raise ValueError(
                f"narration delivery plan binds episode {previous_episode} then episode "
                f"{episode}; a transition joins consecutive episodes"
            )

    timeline = _validate_timeline(document.get("timeline"))
    playback_first, playback_final = playback_domain(
        cast(int, timeline["start_frame"]), cast(int, timeline["end_frame"])
    )

    deliveries = _require_list(document.get("deliveries"), "narration delivery plan deliveries")
    if not deliveries:
        raise ValueError(
            "narration delivery plan carries no deliveries; every narration plan holds at "
            "least one unit, and every unit is scheduled exactly once"
        )

    anchored = 0
    allocated = 0
    previous_end: int | None = None
    for position, record in enumerate(deliveries, start=1):
        description = f"narration delivery plan deliveries[{position - 1}]"
        placement = _validate_delivery(
            record, description, position, playback_first, playback_final
        )
        typed = cast(dict[str, JsonValue], record)
        start = cast(int, typed["start_frame"])
        if previous_end is not None and start <= previous_end:
            raise ValueError(
                f"{description} starts at frame {start}, but the previous slot runs "
                f"through frame {previous_end}; slots follow narration order and never "
                "overlap -- one narrator, one sentence at a time"
            )
        previous_end = cast(int, typed["end_frame"])
        if placement == PLACEMENT_SHOT_ANCHORED:
            anchored += 1
        else:
            allocated += 1

    accounting = _require_document(document.get("accounting"), "narration delivery plan accounting")
    require_exact_keys(accounting, ACCOUNTING_KEYS, "narration delivery plan accounting")
    declared = {
        field: require_exact_int(
            accounting.get(field), f"narration delivery plan accounting {field}"
        )
        for field in sorted(ACCOUNTING_KEYS)
    }
    measured = {
        "allocated_unshown": allocated,
        "deliveries_total": len(deliveries),
        "shot_anchored": anchored,
    }
    if declared != measured:
        raise ValueError(
            f"narration delivery plan declares accounting {declared} but carries "
            f"{measured}; every unit is scheduled exactly once, and the verdict is "
            "measured from the records present rather than asserted beside them"
        )
    if declared["shot_anchored"] + declared["allocated_unshown"] != declared["deliveries_total"]:
        raise ValueError(
            f"narration delivery plan accounts for {declared['shot_anchored']} anchored and "
            f"{declared['allocated_unshown']} allocated slots against "
            f"{declared['deliveries_total']} deliveries; every slot is in exactly one "
            "placement class"
        )

    return document
