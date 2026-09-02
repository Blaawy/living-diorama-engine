"""Episode Presentation Plan V2: the V1 contract plus OPTIONAL per-hold motion windows.

V2 is a strict superset of V1, nothing else. A presentation plan that carries
no ``motion_windows`` key anywhere is validated by EXACTLY the V1 code path
(``validate_episode_presentation_plan`` is delegated to unchanged), so every
golden V1 plan validates identically under this module today. The format tag
and ``schema_version`` stay the V1 values: V2 is an additive extension of the
same document shape, exactly the strict-superset pattern the cinematic V2
schema already uses, and a version bump would make a zero-motion plan refuse
under V1 while validating here, which would break the identity guarantee.

When a plan DOES carry ``motion_windows``, that block is governed here and
nowhere else. It is the V2 reading of the plan's own holds: the plan's
segments still say how long each hold is and on which semantic onset frame it
sits, and the ``motion_windows`` list says, per held position, which
already-rendered semantic frame to show. The V1 core of the document -- the
envelope, timeline, segments, windows and accounting -- is validated by the
unchanged V1 validator on the same data, so a V2 plan can never be a V1 plan
with a looser core; the extra rules here prove only what V1 cannot express.

The extra rules close four questions V1 structurally cannot ask:

* **Counting.** There is exactly one motion window per held segment, in the
  segments' own order, and each carries exactly as many semantic frames as the
  segment's ``dwell_frames``.
* **Placement.** A motion window sits on its hold's onset frame -- the
  segment's own ``semantic_start_frame`` -- and binds the window (unit) whose
  presentation span contains the hold. A hold is the image of its unit's slot
  onset, exactly as V1's policy demands.
* **Truth preservation.** Every semantic frame in a motion window lies inside
  the owning unit's own slot span (derived from the windows and segments of
  this same document) and inside the same animation phase as the onset frame:
  a ping-pong never borrows a frame a different unit's slot or a different
  phase owns, so no simulation-truth boundary is ever crossed.
* **Shape.** The sequence is a prefix of the canonical pure bounce over its
  own extent (``lo, lo+1, ..., hi, hi-1, ...``), starts on the onset, never
  drops below it, and has consecutive values differing by exactly one: a
  genuine, deterministic, non-constant ping-pong, never a hand-edited tail.
"""

from typing import Final, cast

from living_diorama.persistence.schema.world_schema_v1 import (
    require_exact_int,
    require_exact_keys,
    require_identifier,
)
from living_diorama.presentation.presentation_schema_v1 import (
    TOP_LEVEL_KEYS,
    JsonValue,
    _require_document,
    _require_list,
    validate_episode_presentation_plan,
)
from living_diorama.presentation.presentation_spec import bounce_window

TOP_LEVEL_KEYS_V2: Final = TOP_LEVEL_KEYS | frozenset({"motion_windows"})
"""Exactly the top-level keys a V2 presentation plan may carry: the V1 set plus
the one additive ``motion_windows`` block."""

MOTION_WINDOW_KEYS: Final = frozenset({"onset_frame", "semantic_frames", "window_id"})
"""Exactly the keys one V2 motion window carries.

``onset_frame`` is the hold's semantic onset (the slot's own start frame);
``semantic_frames`` is one index per held presentation position, in
presentation order; ``window_id`` binds the hold to the window (unit) whose
slot it images, so a motion window is never a free-floating frame list.
"""


def _window_semantic_span(
    segments: list[dict[str, JsonValue]], window_start: int, window_end: int
) -> tuple[int, int]:
    """Return the inclusive semantic span the window presents, from its own geometry.

    Walks the plan's segments and maps the presentation positions the window
    covers back to their semantic frames: a dwell-1 run advances one semantic
    frame per presentation frame, and a held segment maps every position to its
    single semantic frame. This is the plan's own slot-to-frame-range data,
    re-derived here rather than imported, so a motion window's safe bounds are
    proven from the document itself.
    """
    first: int | None = None
    last: int | None = None
    for segment in segments:
        segment_start = cast(int, segment["presentation_start_frame"])
        segment_end = cast(int, segment["presentation_end_frame"])
        if segment_end < window_start or segment_start > window_end:
            continue
        semantic_start = cast(int, segment["semantic_start_frame"])
        dwell = cast(int, segment["dwell_frames"])
        overlap_start = max(segment_start, window_start)
        overlap_end = min(segment_end, window_end)
        lo_semantic = semantic_start + (overlap_start - segment_start) // dwell
        hi_semantic = semantic_start + (overlap_end - segment_start) // dwell
        if first is None or lo_semantic < first:
            first = lo_semantic
        if last is None or hi_semantic > last:
            last = hi_semantic
    if first is None or last is None:  # pragma: no cover - a window always spans segments
        raise ValueError(
            f"presentation window [{window_start}, {window_end}] covers no segment; a "
            "window's semantic span is not derivable"
        )
    return first, last


def _phase_index(timeline: dict[str, JsonValue], frame: int) -> int:
    """Return which Phase 17 phase a semantic frame belongs to.

    The three phases resolve from the plan's own restated clock: the opening
    hold ``[start_frame, transition_start - 1]``, the transition
    ``[transition_start, transition_end - 1]`` and the closing hold
    ``[transition_end, end_frame - 1]``.
    """
    if frame < cast(int, timeline["transition_start"]):
        return 0
    if frame < cast(int, timeline["transition_end"]):
        return 1
    return 2


def _validate_motion_windows(
    document: dict[str, JsonValue],
    segments: list[dict[str, JsonValue]],
    windows: list[dict[str, JsonValue]],
    timeline: dict[str, JsonValue],
) -> None:
    """Verify the additive ``motion_windows`` block against the validated V1 core."""
    motion_windows = _require_list(
        document.get("motion_windows"), "presentation plan motion_windows"
    )
    hold_segments = [segment for segment in segments if cast(int, segment["dwell_frames"]) > 1]
    if len(motion_windows) != len(hold_segments):
        raise ValueError(
            f"presentation plan carries {len(motion_windows)} motion windows but "
            f"{len(hold_segments)} held segment(s); every hold is ping-ponged exactly once, "
            "and a motion window for a segment that does not hold is refused"
        )

    for position, (segment, motion) in enumerate(
        zip(hold_segments, motion_windows, strict=True), start=1
    ):
        description = f"presentation plan motion_windows[{position - 1}]"
        record = _require_document(motion, description)
        require_exact_keys(record, MOTION_WINDOW_KEYS, description)

        onset = require_exact_int(record.get("onset_frame"), f"{description} onset_frame")
        if onset != cast(int, segment["semantic_start_frame"]):
            raise ValueError(
                f"{description} declares onset frame {onset}, but the held segment it "
                f"belongs to holds semantic frame "
                f"{segment['semantic_start_frame']}; a motion window sits on its hold's "
                "own onset"
            )
        dwell = cast(int, segment["dwell_frames"])
        semantic_frames = _require_list(
            record.get("semantic_frames"), f"{description} semantic_frames"
        )
        if len(semantic_frames) != dwell:
            raise ValueError(
                f"{description} carries {len(semantic_frames)} semantic frame(s) but its "
                f"held segment dwells {dwell} presentation frames; one index per held "
                "position, no more, no fewer"
            )

        window_id = require_identifier(record.get("window_id"), f"{description} window_id")
        hold_start = cast(int, segment["presentation_start_frame"])
        hold_end = cast(int, segment["presentation_end_frame"])
        owner: dict[str, JsonValue] | None = None
        for window in windows:
            window_start = cast(int, window["presentation_start_frame"])
            window_end = cast(int, window["presentation_end_frame"])
            if window_start <= hold_start and hold_end <= window_end:
                owner = window
                break
        if owner is None:
            raise ValueError(
                f"{description} holds presentation frames [{hold_start}, {hold_end}], but no "
                "window's span contains the hold; a hold lives inside its unit's window"
            )
        if window_id != owner["window_id"]:
            raise ValueError(
                f"{description} binds window {window_id!r}, but the window whose span "
                f"contains the hold is {owner['window_id']!r}"
            )

        slot_start, slot_end = _window_semantic_span(
            segments,
            cast(int, owner["presentation_start_frame"]),
            cast(int, owner["presentation_end_frame"]),
        )
        if onset != slot_start:
            raise ValueError(
                f"{description} sits on onset frame {onset}, but the window it belongs to "
                f"presents a slot starting at {slot_start}; only a delivery slot's own "
                "onset frame may ever hold"
            )

        values: list[int] = []
        for index, value in enumerate(semantic_frames):
            values.append(require_exact_int(value, f"{description} semantic_frames[{index}]"))
        if not values:
            raise ValueError(f"{description} carries an empty semantic_frames list")
        if values[0] != onset:
            raise ValueError(
                f"{description} starts at semantic frame {values[0]}, not the onset frame "
                f"{onset}; the first held position shows the frame the footage already "
                "reached, for continuity into the hold"
            )
        if min(values) != onset:
            raise ValueError(
                f"{description} drops to semantic frame {min(values)}, below its onset "
                f"{onset}; a ping-pong never borrows a frame before its own slot's onset"
            )
        if max(values) > slot_end:
            raise ValueError(
                f"{description} reaches semantic frame {max(values)}, beyond its slot's own "
                f"final frame {slot_end}; a ping-pong never borrows a frame a different "
                "unit's slot owns"
            )
        onset_phase = _phase_index(timeline, onset)
        for value in values:
            if _phase_index(timeline, value) != onset_phase:
                raise ValueError(
                    f"{description} reaches semantic frame {value}, in a different animation "
                    f"phase than its onset frame {onset}; a ping-pong never crosses a phase "
                    "boundary"
                )
        if tuple(values) != bounce_window(min(values), max(values), len(values)):
            raise ValueError(
                f"{description} is not a prefix of the canonical bounce over "
                f"[{min(values)}, {max(values)}]; a V2 hold is the pure deterministic "
                "oscillation, never a hand-edited tail"
            )


def validate_episode_presentation_plan_v2(value: object) -> dict[str, JsonValue]:
    """Verify a document's Episode Presentation Plan under the V2 profile.

    A plan without ``motion_windows`` is validated by the unchanged V1
    validator and returned as-is -- the strict-superset guarantee. A plan that
    carries the block is validated in two halves: its V1 core (envelope,
    timeline, segments, windows, accounting) by the unchanged V1 validator on
    the same data, and the additive block by :func:`_validate_motion_windows`
    against that validated core.

    Raises:
        TypeError: If any value has the wrong exact type.
        ValueError: If any key set, vocabulary member, ordering, bound or
            internal agreement is violated.
    """
    document = _require_document(value, "presentation plan")
    if "motion_windows" not in document:
        return validate_episode_presentation_plan(document)

    core = dict(document)
    del core["motion_windows"]
    validated_core = validate_episode_presentation_plan(core)
    for key in document:
        if key not in TOP_LEVEL_KEYS_V2:
            raise ValueError(
                f"presentation plan carries unexpected top-level key {key!r}; a V2 plan is "
                "the V1 document plus motion_windows and nothing else"
            )
    segments = cast(list[dict[str, JsonValue]], validated_core["segments"])
    windows = cast(list[dict[str, JsonValue]], validated_core["windows"])
    timeline = cast(dict[str, JsonValue], validated_core["timeline"])
    _validate_motion_windows(document, segments, windows, timeline)
    return document


def validate_presentation_plan(value: object) -> dict[str, JsonValue]:
    """Validate a presentation plan of either profile, returning the document.

    Dispatches on the presence of the additive ``motion_windows`` key: a V2
    plan is validated by :func:`validate_episode_presentation_plan_v2` (which
    itself delegates a V1-shaped plan to the unchanged V1 validator), and any
    other document is validated by the unchanged V1 validator. This is the one
    entry point downstream Phase 33 consumers call so a V2 plan can pass the
    same gates a V1 plan passes.

    Raises:
        TypeError: If any value has the wrong exact type.
        ValueError: If any key set, vocabulary member, ordering, bound or
            internal agreement is violated.
    """
    if type(value) is dict and "motion_windows" in value:
        return validate_episode_presentation_plan_v2(value)
    return validate_episode_presentation_plan(value)


__all__ = [
    "MOTION_WINDOW_KEYS",
    "TOP_LEVEL_KEYS_V2",
    "validate_episode_presentation_plan_v2",
    "validate_presentation_plan",
]
