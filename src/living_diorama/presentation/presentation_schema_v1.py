"""Episode Presentation Plan format V1: the viewer-facing timing contract.

A presentation plan is deterministic viewer-facing timing bound to
authoritative document identity. It says, for every locked semantic playback
frame of one directed episode, how many presentation frames the viewer sees it
for, and it binds the exact Narration Delivery Plan whose slots it images, the
exact Narration Plan whose units it presents, and the exact Language
Realization Plan whose sentences those units name. It asserts nothing about
the world, nothing about wording, and nothing about a single rendered pixel --
those live in the documents it binds, and stay there.

The document shape is exact at every level this module governs. A key that is
missing means the plan is incomplete; a key that is extra means it was written
by something this contract does not describe. Both are refused, never repaired.

This validator is deliberately self-contained: it proves everything the plan
can prove about itself, including that its own restated clock closes on its
own arithmetic, that its segments tile the playback domain that clock implies
with no gap, no overlap and no witness, that a held frame is never a run of
frames, and that its own presentation cursor closes on its own arithmetic.
Whether the plan's claims are true *of* its three bound sources -- and true of
the two upstream documents those sources were themselves proven against -- is
proven by
:func:`living_diorama.presentation.presentation_cross_check.validate_episode_presentation_plan_against_sources`,
which takes those sources as arguments.
"""

from typing import Final, cast

from living_diorama.cinematic.cinematic_schema_v1 import MAX_TIMELINE_FPS, MAX_TIMELINE_FRAME
from living_diorama.language_realization.realization_spec import REALIZATION_ID_FORM
from living_diorama.narration.narration_schema_v1 import (
    MODE_BASELINE,
    PLAN_MODES,
    UNIT_ID_FORM,
)
from living_diorama.narration_delivery.delivery_spec import playback_domain
from living_diorama.persistence.schema.state_hash import require_hash_hex
from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_identifier,
    require_text,
)
from living_diorama.presentation.presentation_spec import (
    MAX_PRESENTATION_FRAME,
    PRESENTATION_PLAN_FORMAT,
    PRESENTATION_POLICY_V1,
    PRESENTATION_SCHEMA_VERSION,
    SEGMENT_ID_FORM,
    WINDOW_ID_FORM,
)

SUPPORTED_DELIVERY_SCHEMA_VERSION: Final = 1
SUPPORTED_NARRATION_SCHEMA_VERSION: Final = 1
SUPPORTED_REALIZATION_SCHEMA_VERSION: Final = 1
"""The upstream contract versions this build presents."""

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
"""The JSON value shape this contract works in.

Declared here rather than imported from an upstream layer for the same reason
Phase 24, Phase 25 and Phase 26 each declare their own: a shared alias is not
worth a hole in a boundary.
"""

TOP_LEVEL_KEYS: Final = frozenset(
    {
        "accounting",
        "format",
        "policy",
        "schema_version",
        "segments",
        "source",
        "timeline",
        "windows",
    }
)
"""Exactly the top-level keys an episode presentation plan carries."""

SOURCE_KEYS: Final = frozenset(
    {
        "delivery_plan_sha256",
        "delivery_schema_version",
        "episode",
        "mode",
        "motion_time_sha256",
        "narration_plan_sha256",
        "narration_schema_version",
        "previous_episode",
        "realization_plan_sha256",
        "realization_schema_version",
    }
)
"""Exactly the keys binding a plan to the three documents it presents.

Three digests: the delivery plan whose slots this plan images, the narration
plan whose units it presents (restated rather than inherited, because it is
the join key two independent upstream documents -- delivery and realization --
must be proven to share), and the realization plan whose sentences its windows
name. There is deliberately no story-plan digest, no render-export digest and
no shot-plan digest: this plan claims nothing that those documents alone would
prove, and the two locked upstream source-verification gates this plan's
cross-check runs already consume those three documents as arguments without
needing this plan to restate what they bind.

``motion_time_sha256`` is the one deliberate restatement: this plan restates
resolved clock values in its timeline block, and a resolved clock is pinned
beside the digest of the source that produces it, exactly as Phase 22 and
Phase 25 pin theirs.
"""

PRESENTATION_TIMELINE_KEYS: Final = frozenset(
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
"""Exactly the Phase 17 timeline facts a presentation plan restates.

Restated key-for-key from the Narration Delivery Plan rather than imported
from the ``narration_delivery`` package, for the same reason Phase 25 restates
Phase 22's key set rather than importing it: this contract's shape belongs to
this schema version, and a test asserts the two key sets still agree so drift
fails loudly. The two derived boundaries must equal Phase 17's own arithmetic
over the six source fields, and the cross-check separately proves the whole
block equals the offered delivery plan's, so an invented clock dies twice.
"""

SEGMENT_KEYS: Final = frozenset(
    {
        "dwell_frames",
        "presentation_end_frame",
        "presentation_start_frame",
        "segment_id",
        "semantic_end_frame",
        "semantic_start_frame",
    }
)
"""Exactly the keys a presentation segment carries.

A segment is one maximal run of semantic playback frames shown at one uniform
dwell -- its own presentation-frame identity and nothing else. A segment
carries no unit id and no wording: which unit, if any, a held frame belongs to
is a window's claim, never a segment's.
"""

WINDOW_KEYS: Final = frozenset(
    {"presentation_end_frame", "presentation_start_frame", "realization_id", "unit_id", "window_id"}
)
"""Exactly the keys a presentation window carries.

Deliberately no semantic frames, no dwell, no shot citation and no sentence
bytes: a window is the presentation-clock image of its unit's Phase 25 slot
and the identity of the Phase 26 sentence it presents, nothing more. Its
semantic geometry is re-derivable from the bound delivery plan and this plan's
own segments.
"""

ACCOUNTING_KEYS: Final = frozenset({"presentation_frames_total", "segments_total", "windows_total"})
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


def _require_presentation_frame(value: object, description: str) -> int:
    """Return the value if it is a valid presentation-clock coordinate, else raise.

    Bounded by this layer's own ``MAX_PRESENTATION_FRAME`` rail -- never by
    Phase 17's ``MAX_TIMELINE_FRAME``, which rails a different clock.
    """
    number = require_exact_int(value, description)
    if not 1 <= number <= MAX_PRESENTATION_FRAME:
        raise ValueError(
            f"{description} must be within [1, {MAX_PRESENTATION_FRAME}], got {number}"
        )
    return number


def _validate_timeline(value: object) -> dict[str, JsonValue]:
    """Verify the restated clock closes on its own arithmetic, and return it."""
    description = "presentation plan timeline"
    timeline = _require_document(value, description)
    require_exact_keys(timeline, PRESENTATION_TIMELINE_KEYS, description)
    resolved: dict[str, int] = {}
    for field in sorted(PRESENTATION_TIMELINE_KEYS):
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
    expected_start = resolved["start_frame"] + resolved["start_hold_frames"]
    if resolved["transition_start"] != expected_start:
        raise ValueError(
            f"{description} declares transition_start {resolved['transition_start']}, but "
            f"its own phases resolve to {expected_start}"
        )
    expected_end = resolved["transition_start"] + resolved["transition_frames"]
    if resolved["transition_end"] != expected_end:
        raise ValueError(
            f"{description} declares transition_end {resolved['transition_end']}, but its "
            f"own phases resolve to {expected_end}"
        )
    declared_close = resolved["transition_end"] + resolved["end_hold_frames"]
    if resolved["end_frame"] != declared_close:
        raise ValueError(
            f"{description} declares end_frame {resolved['end_frame']}, but its own phases "
            f"close on {declared_close}"
        )
    playback_domain(resolved["start_frame"], resolved["end_frame"])
    return timeline


def _validate_segment(
    value: object, description: str, position: int
) -> tuple[int, int, int, int, int]:
    """Verify one segment record, and return its six geometric fields.

    Returns:
        ``(semantic_start, semantic_end, dwell, presentation_start,
        presentation_end)`` -- five ints, not six, because the segment id is
        proven positionally and carries no further information.
    """
    record = _require_document(value, description)
    require_exact_keys(record, SEGMENT_KEYS, description)

    segment_id = require_identifier(record.get("segment_id"), f"{description} segment_id")
    expected_id = SEGMENT_ID_FORM % position
    if segment_id != expected_id:
        raise ValueError(
            f"{description} declares segment_id {segment_id!r} but sits at position "
            f"{position}, where the identifier is {expected_id!r}; a segment id is "
            "positional, not a free label"
        )

    semantic_start = require_exact_int(
        record.get("semantic_start_frame"), f"{description} semantic_start_frame"
    )
    semantic_end = require_exact_int(
        record.get("semantic_end_frame"), f"{description} semantic_end_frame"
    )
    if semantic_end < semantic_start:
        raise ValueError(
            f"{description} ends at semantic frame {semantic_end} before it starts at "
            f"{semantic_start}"
        )
    dwell = require_exact_int(record.get("dwell_frames"), f"{description} dwell_frames")
    if not 1 <= dwell <= MAX_PRESENTATION_FRAME:
        raise ValueError(
            f"{description} dwell_frames must be within [1, {MAX_PRESENTATION_FRAME}], got {dwell}"
        )
    if dwell > 1 and semantic_end != semantic_start:
        raise ValueError(
            f"{description} holds semantic frames [{semantic_start}, {semantic_end}] for "
            f"{dwell} presentation frames each; a held run spans exactly one semantic "
            "frame, never several -- distributed dilation of moving footage is not "
            "representable"
        )

    presentation_start = _require_presentation_frame(
        record.get("presentation_start_frame"), f"{description} presentation_start_frame"
    )
    presentation_end = _require_presentation_frame(
        record.get("presentation_end_frame"), f"{description} presentation_end_frame"
    )
    expected_length = (semantic_end - semantic_start + 1) * dwell
    expected_end = presentation_start + expected_length - 1
    if presentation_end != expected_end:
        raise ValueError(
            f"{description} spans presentation frames [{presentation_start}, "
            f"{presentation_end}], but {semantic_end - semantic_start + 1} semantic frame(s) "
            f"at dwell {dwell} resolve to [{presentation_start}, {expected_end}]"
        )

    return semantic_start, semantic_end, dwell, presentation_start, presentation_end


def _validate_window(value: object, description: str, position: int) -> tuple[int, int]:
    """Verify one window record, and return its presentation span."""
    record = _require_document(value, description)
    require_exact_keys(record, WINDOW_KEYS, description)

    window_id = require_identifier(record.get("window_id"), f"{description} window_id")
    expected_window = WINDOW_ID_FORM % position
    if window_id != expected_window:
        raise ValueError(
            f"{description} declares window_id {window_id!r} but sits at position "
            f"{position}, where the identifier is {expected_window!r}; a window id is "
            "positional, not a free label"
        )
    unit_id = require_identifier(record.get("unit_id"), f"{description} unit_id")
    expected_unit = UNIT_ID_FORM % position
    if unit_id != expected_unit:
        raise ValueError(
            f"{description} presents unit {unit_id!r} but sits at position {position}, "
            f"where the narration plan's unit is {expected_unit!r}; a presentation window "
            "follows the narration plan's own order, one window per unit"
        )
    realization_id = require_identifier(
        record.get("realization_id"), f"{description} realization_id"
    )
    expected_realization = REALIZATION_ID_FORM % position
    if realization_id != expected_realization:
        raise ValueError(
            f"{description} names realization {realization_id!r} but sits at position "
            f"{position}, where the realization plan's record is "
            f"{expected_realization!r}; a presentation window follows the narration "
            "plan's own order, one window per realized unit"
        )

    start = _require_presentation_frame(
        record.get("presentation_start_frame"), f"{description} presentation_start_frame"
    )
    end = _require_presentation_frame(
        record.get("presentation_end_frame"), f"{description} presentation_end_frame"
    )
    if end < start:
        raise ValueError(f"{description} ends at frame {end} before it starts at {start}")
    return start, end


def validate_episode_presentation_plan(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Presentation Plan V1 envelope, and return it.

    Checks the exact key sets at every governed level, the format tag, schema
    version and policy identity, the source binding (episode, mode, the digest
    fields, the three schema-version fields against the versions this build
    supports, and the rule that only a baseline has no previous episode), the
    restated timeline's own arithmetic, and every segment and window record.
    Four whole-document rules are enforced too, because they are what make the
    plan a presentation rather than merely well formed:

    * segments tile the timeline's own playback domain exactly -- no gap, no
      overlap, no frame twice, and the terminal witness frame never appears
    * presentation coordinates are contiguous from 1, closing on each
      segment's own dwell arithmetic
    * adjacent segments never share a dwell, since a run that could have been
      one segment is not two
    * windows appear in narration order, never overlapping, and the
      accounting block agrees with the records actually present

    This validator is deliberately self-contained: it proves everything the
    plan can prove about itself, and nothing that needs the three bound
    sources. Whether the plan's claims agree with the actual delivery plan,
    narration plan and realization plan -- and everything those in turn were
    proven against -- is proven by
    :func:`living_diorama.presentation.presentation_cross_check.validate_episode_presentation_plan_against_sources`.

    Raises:
        TypeError: If any value has the wrong exact type.
        ValueError: If any key set, vocabulary member, ordering, bound or
            internal agreement is violated.
    """
    document = _require_document(value, "presentation plan")
    require_exact_keys(document, TOP_LEVEL_KEYS, "presentation plan")

    tag = require_text(document.get("format"), "presentation plan format")
    if tag != PRESENTATION_PLAN_FORMAT:
        raise ValueError(
            f"presentation plan declares format {tag!r}; this build reads "
            f"{PRESENTATION_PLAN_FORMAT!r} only"
        )
    version = require_exact_int(document.get("schema_version"), "presentation plan schema_version")
    if version != PRESENTATION_SCHEMA_VERSION:
        raise ValueError(
            f"presentation plan declares unsupported schema version {version}; this build "
            f"reads version {PRESENTATION_SCHEMA_VERSION} only"
        )
    policy = require_text(document.get("policy"), "presentation plan policy")
    if policy != PRESENTATION_POLICY_V1:
        raise ValueError(
            f"presentation plan declares policy {policy!r}; this build derives and "
            f"validates {PRESENTATION_POLICY_V1!r} only, and a window cut under another "
            "policy must never be mistaken for one of these"
        )

    source = _require_document(document.get("source"), "presentation plan source")
    require_exact_keys(source, SOURCE_KEYS, "presentation plan source")
    mode = _require_member(source.get("mode"), PLAN_MODES, "presentation plan source mode")
    episode = require_exact_int(source.get("episode"), "presentation plan source episode")
    delivery_version = require_exact_int(
        source.get("delivery_schema_version"), "presentation plan source delivery_schema_version"
    )
    if delivery_version != SUPPORTED_DELIVERY_SCHEMA_VERSION:
        raise ValueError(
            f"presentation plan was derived from delivery schema version {delivery_version}; "
            f"this build presents version {SUPPORTED_DELIVERY_SCHEMA_VERSION} only"
        )
    narration_version = require_exact_int(
        source.get("narration_schema_version"), "presentation plan source narration_schema_version"
    )
    if narration_version != SUPPORTED_NARRATION_SCHEMA_VERSION:
        raise ValueError(
            f"presentation plan was derived from narration schema version "
            f"{narration_version}; this build presents version "
            f"{SUPPORTED_NARRATION_SCHEMA_VERSION} only"
        )
    realization_version = require_exact_int(
        source.get("realization_schema_version"),
        "presentation plan source realization_schema_version",
    )
    if realization_version != SUPPORTED_REALIZATION_SCHEMA_VERSION:
        raise ValueError(
            f"presentation plan was derived from realization schema version "
            f"{realization_version}; this build presents version "
            f"{SUPPORTED_REALIZATION_SCHEMA_VERSION} only"
        )
    for field in (
        "delivery_plan_sha256",
        "motion_time_sha256",
        "narration_plan_sha256",
        "realization_plan_sha256",
    ):
        require_hash_hex(source.get(field), f"presentation plan source {field}")

    previous = source.get("previous_episode")
    if mode == MODE_BASELINE:
        _require_null(
            previous,
            "presentation plan source previous_episode",
            "a baseline presents one export's narration and follows no episode",
        )
        if episode != 0:
            raise ValueError(
                f"presentation plan is baseline mode but describes episode {episode}; a "
                "baseline describes episode 0 only"
            )
    else:
        previous_episode = require_exact_int(previous, "presentation plan source previous_episode")
        if episode != previous_episode + 1:
            raise ValueError(
                f"presentation plan binds episode {previous_episode} then episode "
                f"{episode}; a transition joins consecutive episodes"
            )

    timeline = _validate_timeline(document.get("timeline"))
    playback_first, playback_final = playback_domain(
        cast(int, timeline["start_frame"]), cast(int, timeline["end_frame"])
    )

    segments = _require_list(document.get("segments"), "presentation plan segments")
    if not segments:
        raise ValueError(
            "presentation plan carries no segments; a locked episode always offers a "
            "nonempty playback domain to tile"
        )

    semantic_cursor = playback_first
    presentation_cursor = 1
    previous_dwell: int | None = None
    for position, segment in enumerate(segments, start=1):
        description = f"presentation plan segments[{position - 1}]"
        semantic_start, semantic_end, dwell, presentation_start, presentation_end = (
            _validate_segment(segment, description, position)
        )
        if semantic_start != semantic_cursor:
            raise ValueError(
                f"{description} starts at semantic frame {semantic_start}, but the "
                f"previous segment left off at {semantic_cursor}; segments tile the "
                "playback domain with no gap and no overlap"
            )
        if presentation_start != presentation_cursor:
            raise ValueError(
                f"{description} starts at presentation frame {presentation_start}, but "
                f"the previous segment left off at {presentation_cursor}; presentation "
                "coordinates are contiguous from frame 1"
            )
        if previous_dwell is not None and dwell == previous_dwell:
            raise ValueError(
                f"{description} declares dwell {dwell}, equal to the previous segment's; "
                "adjacent segments never share a dwell -- a run that could have been one "
                "segment is not two"
            )
        semantic_cursor = semantic_end + 1
        presentation_cursor = presentation_end + 1
        previous_dwell = dwell

    if semantic_cursor != playback_final + 1:
        raise ValueError(
            f"presentation plan segments cover semantic frames up to "
            f"{semantic_cursor - 1}, but the playback domain ends at {playback_final}; "
            "every playback frame is presented, and the witness frame is never one of them"
        )
    presentation_frames_total = presentation_cursor - 1

    windows = _require_list(document.get("windows"), "presentation plan windows")
    if not windows:
        raise ValueError(
            "presentation plan carries no windows; every narration plan holds at least "
            "one unit, and every unit is presented exactly once"
        )

    previous_end: int | None = None
    for position, record in enumerate(windows, start=1):
        description = f"presentation plan windows[{position - 1}]"
        start, end = _validate_window(record, description, position)
        if end > presentation_frames_total:
            raise ValueError(
                f"{description} occupies presentation frames [{start}, {end}], beyond "
                f"the plan's own total of {presentation_frames_total}"
            )
        if previous_end is not None and start <= previous_end:
            raise ValueError(
                f"{description} starts at frame {start}, but the previous window runs "
                f"through frame {previous_end}; windows follow narration order and never "
                "overlap -- one narrator, one sentence at a time"
            )
        previous_end = end

    accounting = _require_document(document.get("accounting"), "presentation plan accounting")
    require_exact_keys(accounting, ACCOUNTING_KEYS, "presentation plan accounting")
    declared_total = require_exact_int(
        accounting.get("presentation_frames_total"),
        "presentation plan accounting presentation_frames_total",
    )
    if declared_total != presentation_frames_total:
        raise ValueError(
            f"presentation plan declares {declared_total} total presentation frames, but "
            f"its own segments close on {presentation_frames_total}; the total is measured "
            "from the segments present rather than asserted beside them"
        )
    declared_segments = require_exact_int(
        accounting.get("segments_total"), "presentation plan accounting segments_total"
    )
    if declared_segments != len(segments):
        raise ValueError(
            f"presentation plan declares {declared_segments} segments but carries "
            f"{len(segments)}; the total is measured from the records present"
        )
    declared_windows = require_exact_int(
        accounting.get("windows_total"), "presentation plan accounting windows_total"
    )
    if declared_windows != len(windows):
        raise ValueError(
            f"presentation plan declares {declared_windows} windows but carries "
            f"{len(windows)}; the total is measured from the records present"
        )

    return document
