"""Motion & Time Spec V1: the presentation contract for cinematic time.

Pure Python by design -- this module never imports ``bpy``, so the whole
timeline, the channel policies, and the interpolation mathematics can be
validated and tested without Blender installed.

A Motion Spec is PRESENTATION architecture, never simulation state. It owns
frame rate, the three timeline phases, which visual channels are allowed to
move at all, when each of them is allowed to move inside the transition, and
exactly how a value travels from its before-state to its after-state. It
carries no world state, no entity identifiers, and no story: what actually
changes is decided downstream by :mod:`motion_plan`, from the authoritative
Render Exports alone.

The timeline is deliberately presentation-neutral::

    START HOLD          the before-state, held still
    TRANSITION          the only window in which anything may move
    END HOLD            the after-state, held still

Both holds are at least one frame long: a proof that claims an endpoint has
to have a frame on which that endpoint simply stands still.

Nothing outside this module may invent a frame number. Runtime code asks the
resolved timeline for frames; magic constants never appear beside keyframes.
"""

import json
import math
from pathlib import Path

MOTION_TIME_FORMAT = "living_diorama_motion_time"
MOTION_TIME_SCHEMA_VERSION = 1

INTERPOLATIONS = ("linear", "smoothstep", "step")
"""Every easing this project is allowed to use. Blender's own defaults are
never inherited: an unstated interpolation is a spec error, not a Bezier."""

STRATEGIES = ("together", "staged")
"""How a channel distributes its window across its members: all at once, or
one after another in a stable order."""

SUPPORTED_CHANNELS = (
    "law_seal_glow",
    "district_glazing",
    "wall_presence",
    "depot_slot_presence",
    "depot_slot_settle",
    "infra_strut_presence",
    "infra_strut_settle",
)
"""The V1 motion channels. Each one animates a property that the LOCKED
Phase 15 static application already drives from authoritative state -- which
is what makes endpoint equivalence achievable at all. A channel that has no
static expression cannot be animated without making the animated end state
differ from the ordinary static application of the after-export, so it is
refused by :mod:`motion_plan` rather than invented here."""

TIMELINE_FIELDS = (
    "fps",
    "start_frame",
    "start_hold_frames",
    "transition_frames",
    "end_hold_frames",
    "end_frame",
)

MAX_FPS = 240
MAX_FRAME = 100_000


class MotionSpecError(ValueError):
    """A Motion & Time Spec contract violation.

    Raised for malformed documents, impossible timelines, unknown or
    duplicated channels, and malformed interpolation policies. Always a
    refusal, never a repair and never a silent default.
    """


def _require_object(value: object, description: str) -> dict:
    """Return the value if it is a JSON object, else refuse."""
    if not isinstance(value, dict):
        raise MotionSpecError(f"{description} must be a JSON object, got {type(value).__name__}")
    return value


def _require_int(value: object, description: str, *, minimum: int, maximum: int) -> int:
    """Return a bounded integer, refusing booleans and floats alike.

    ``True`` is an ``int`` in Python and would otherwise silently become
    frame 1; a spec that says ``true`` where a frame belongs is malformed.
    """
    if isinstance(value, bool):
        raise MotionSpecError(f"{description} must be an integer, not a boolean")
    if not isinstance(value, int):
        raise MotionSpecError(f"{description} must be an integer, got {type(value).__name__}")
    if not minimum <= value <= maximum:
        raise MotionSpecError(f"{description} must be within [{minimum}, {maximum}], got {value}")
    return value


def _require_unit(value: object, description: str) -> float:
    """Return a finite number in [0, 1], else refuse."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MotionSpecError(f"{description} must be a number in [0, 1]")
    number = float(value)
    if not math.isfinite(number):
        raise MotionSpecError(f"{description} must be finite, got {value!r}")
    if not 0.0 <= number <= 1.0:
        raise MotionSpecError(f"{description} must be within [0, 1], got {number}")
    return number


def _require_positive(value: object, description: str) -> float:
    """Return a finite number greater than zero, else refuse."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MotionSpecError(f"{description} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise MotionSpecError(f"{description} must be finite, got {value!r}")
    if number <= 0.0:
        raise MotionSpecError(f"{description} must be greater than zero, got {number}")
    return number


def interpolate(kind: str, start_value: float, end_value: float, t: float) -> float:
    """Return the channel value at normalized position ``t`` in [0, 1].

    The three policies are the project's whole easing vocabulary, and each is
    EXACT at both ends: ``t == 0.0`` always returns ``start_value`` and
    ``t == 1.0`` always returns ``end_value``, with no overshoot, no bounce,
    and no procedural noise anywhere in between.

    ``smoothstep`` is the classic ``3t^2 - 2t^3`` S-curve. ``step`` holds the
    start value for the whole window and swaps at its very end, which is how
    a state change is expressed without inventing continuous motion.

    Raises:
        MotionSpecError: On an unknown interpolation or an out-of-range ``t``.
    """
    if kind not in INTERPOLATIONS:
        raise MotionSpecError(f"unknown interpolation {kind!r}; expected one of {INTERPOLATIONS}")
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(float(t)):
        raise MotionSpecError(f"interpolation position must be a finite number, got {t!r}")
    position = float(t)
    if not 0.0 <= position <= 1.0:
        raise MotionSpecError(f"interpolation position must be within [0, 1], got {position}")
    if kind == "step":
        return float(end_value) if position >= 1.0 else float(start_value)
    if position <= 0.0:
        return float(start_value)
    if position >= 1.0:
        return float(end_value)
    weight = position if kind == "linear" else position * position * (3.0 - 2.0 * position)
    return float(start_value) + (float(end_value) - float(start_value)) * weight


def resolve_timeline(document: dict) -> dict:
    """Return the validated frame arithmetic of one Motion Spec.

    Every phase boundary is derived once, here, so no runtime module ever
    computes a frame of its own::

        start_frame .. transition_start      START HOLD
        transition_start .. transition_end   TRANSITION
        transition_end .. end_frame          END HOLD

    Raises:
        MotionSpecError: On a malformed, reversed, or inconsistent timeline.
    """
    timeline = _require_object(document.get("timeline"), "motion spec timeline")
    unknown = sorted(set(timeline) - set(TIMELINE_FIELDS))
    if unknown:
        raise MotionSpecError(f"motion spec timeline has unknown fields: {unknown}")
    missing = sorted(set(TIMELINE_FIELDS) - set(timeline))
    if missing:
        raise MotionSpecError(f"motion spec timeline is missing fields: {missing}")

    fps = _require_int(timeline["fps"], "timeline fps", minimum=1, maximum=MAX_FPS)
    start_frame = _require_int(
        timeline["start_frame"], "timeline start_frame", minimum=0, maximum=MAX_FRAME
    )
    start_hold = _require_int(
        timeline["start_hold_frames"], "timeline start_hold_frames", minimum=1, maximum=MAX_FRAME
    )
    transition = _require_int(
        timeline["transition_frames"], "timeline transition_frames", minimum=1, maximum=MAX_FRAME
    )
    end_hold = _require_int(
        timeline["end_hold_frames"], "timeline end_hold_frames", minimum=1, maximum=MAX_FRAME
    )
    declared_end = _require_int(
        timeline["end_frame"], "timeline end_frame", minimum=0, maximum=MAX_FRAME
    )

    transition_start = start_frame + start_hold
    transition_end = transition_start + transition
    end_frame = transition_end + end_hold
    if declared_end != end_frame:
        raise MotionSpecError(
            f"timeline end_frame {declared_end} disagrees with its own phases: "
            f"{start_frame} + {start_hold} + {transition} + {end_hold} = {end_frame}"
        )
    return {
        "fps": fps,
        "start_frame": start_frame,
        "transition_start": transition_start,
        "transition_end": transition_end,
        "end_frame": end_frame,
        "start_hold_frames": start_hold,
        "transition_frames": transition,
        "end_hold_frames": end_hold,
        "duration_seconds": round((end_frame - start_frame) / fps, 6),
    }


def _resolve_channel(entry: object, index: int) -> dict:
    """Validate one channel policy declaration."""
    channel = _require_object(entry, f"motion spec channels[{index}]")
    allowed = {
        "channel",
        "interpolation",
        "strategy",
        "window",
        "member_span",
        "rise_metres",
        "samples",
    }
    unknown = sorted(set(channel) - allowed)
    if unknown:
        raise MotionSpecError(f"channel policy [{index}] has unknown fields: {unknown}")

    name = channel.get("channel")
    if not isinstance(name, str) or name not in SUPPORTED_CHANNELS:
        raise MotionSpecError(
            f"channel policy [{index}] declares unsupported channel {name!r}; "
            f"expected one of {SUPPORTED_CHANNELS}"
        )
    kind = channel.get("interpolation")
    if kind not in INTERPOLATIONS:
        raise MotionSpecError(
            f"channel {name!r} must declare an interpolation from {INTERPOLATIONS}, got {kind!r}"
        )
    strategy = channel.get("strategy")
    if strategy not in STRATEGIES:
        raise MotionSpecError(
            f"channel {name!r} must declare a strategy from {STRATEGIES}, got {strategy!r}"
        )

    window = channel.get("window")
    if not isinstance(window, list) or len(window) != 2:
        raise MotionSpecError(f"channel {name!r} window must be a [start, end] pair")
    window_start = _require_unit(window[0], f"channel {name!r} window start")
    window_end = _require_unit(window[1], f"channel {name!r} window end")
    if window_end <= window_start:
        raise MotionSpecError(
            f"channel {name!r} window is reversed or empty: [{window_start}, {window_end}]"
        )

    span = window_end - window_start
    member_span = channel.get("member_span", span)
    member_span = _require_unit(member_span, f"channel {name!r} member_span")
    if member_span <= 0.0:
        raise MotionSpecError(f"channel {name!r} member_span must be greater than zero")
    if member_span > span + 1.0e-12:
        raise MotionSpecError(
            f"channel {name!r} member_span {member_span} exceeds its own window span {span}"
        )
    if strategy == "together" and abs(member_span - span) > 1.0e-12:
        raise MotionSpecError(
            f"channel {name!r} is 'together' but declares a member_span narrower than its window"
        )

    rise = channel.get("rise_metres", 0.0)
    if isinstance(rise, bool) or not isinstance(rise, (int, float)):
        raise MotionSpecError(f"channel {name!r} rise_metres must be a number")
    rise = float(rise)
    if not math.isfinite(rise) or rise < 0.0:
        raise MotionSpecError(f"channel {name!r} rise_metres must be finite and not negative")

    samples = _require_int(
        channel.get("samples", 8), f"channel {name!r} samples", minimum=1, maximum=64
    )
    if kind == "step" and samples != 1:
        raise MotionSpecError(
            f"channel {name!r} is a step channel and must declare samples 1, got {samples}"
        )
    return {
        "channel": name,
        "interpolation": kind,
        "strategy": strategy,
        "window": (window_start, window_end),
        "member_span": member_span,
        "rise_metres": rise,
        "samples": samples,
    }


def _resolve_proof_samples(document: dict, timeline: dict) -> tuple[dict, ...]:
    """Validate the declared proof frames and resolve them to frame numbers."""
    entries = document.get("proof_samples")
    if not isinstance(entries, list) or not entries:
        raise MotionSpecError("motion spec must declare a non-empty proof_samples list")
    resolved: list[dict] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        sample = _require_object(entry, f"proof_samples[{index}]")
        unknown = sorted(set(sample) - {"name", "position"})
        if unknown:
            raise MotionSpecError(f"proof_samples[{index}] has unknown fields: {unknown}")
        name = sample.get("name")
        if not isinstance(name, str) or not name.strip():
            raise MotionSpecError(f"proof_samples[{index}] name must be a non-empty string")
        if name in seen:
            raise MotionSpecError(f"proof_samples declares {name!r} twice")
        seen.add(name)
        position = sample.get("position")
        if position == "start":
            frame = timeline["start_frame"]
        elif position == "end":
            frame = timeline["end_frame"]
        else:
            unit = _require_unit(position, f"proof_samples[{index}] position")
            frame = frame_at(timeline, unit)
        resolved.append({"name": name, "position": position, "frame": frame})
    frames = [sample["frame"] for sample in resolved]
    if frames != sorted(frames) or len(set(frames)) != len(frames):
        raise MotionSpecError(
            f"proof_samples must resolve to strictly increasing frames, got {frames}"
        )
    return tuple(resolved)


def frame_at(timeline: dict, position: float) -> int:
    """Return the frame at a normalized position inside the TRANSITION.

    ``0.0`` is the first transition frame and ``1.0`` the last; the start and
    end holds are addressed by ``timeline['start_frame']`` and
    ``timeline['end_frame']``. Rounding is half-up on an exact integer count,
    so the same position always resolves to the same frame everywhere.
    """
    unit = _require_unit(position, "timeline position")
    span = timeline["transition_end"] - timeline["transition_start"]
    return timeline["transition_start"] + int(math.floor(unit * span + 0.5))


def channel_frames(policy: dict, timeline: dict) -> tuple[int, int]:
    """Return the whole frame window a channel is allowed to move in."""
    window_start, window_end = policy["window"]
    return frame_at(timeline, window_start), frame_at(timeline, window_end)


def member_span_frames(policy: dict, timeline: dict) -> int:
    """Return how many frames one member of a channel occupies."""
    span = int(math.floor(policy["member_span"] * timeline["transition_frames"] + 0.5))
    return max(1, span)


def staged_frames(
    window: tuple[int, int], span: int, index: int, count: int, *, staged: bool
) -> tuple[int, int]:
    """Distribute ``count`` member windows of ``span`` frames across ``window``.

    Integer frame arithmetic, shared by the pure planner and the Blender
    applier so both sides always agree on the exact frame a member moves.
    ``together`` channels -- and any channel with a single member -- hand the
    whole window to every member; a staged channel lays its members out in
    even strides in their stable order, so a wall builds itself segment by
    segment instead of appearing all at once.

    Raises:
        MotionSpecError: On a non-positive count, an out-of-range index, a
            non-positive span, or a member window shorter than one frame.
    """
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise MotionSpecError(f"member count must be a positive integer, got {count!r}")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < count:
        raise MotionSpecError(f"member index {index!r} is outside [0, {count})")
    if isinstance(span, bool) or not isinstance(span, int) or span < 1:
        raise MotionSpecError(f"member span must be at least one frame, got {span!r}")
    window_start, window_end = window
    if window_end <= window_start:
        raise MotionSpecError(f"channel frame window is reversed or empty: {window}")
    if not staged or count == 1:
        return window_start, window_end
    room = (window_end - window_start) - span
    if room < 0:
        raise MotionSpecError(
            f"a {span}-frame member does not fit in the {window_end - window_start}-frame "
            "channel window; widen the window or lengthen the transition"
        )
    start_frame = window_start + int(math.floor(room * index / (count - 1) + 0.5))
    return start_frame, start_frame + span


def member_window(policy: dict, timeline: dict, index: int, count: int) -> tuple[int, int]:
    """Return the (start, end) frames of one member of a channel."""
    return staged_frames(
        channel_frames(policy, timeline),
        member_span_frames(policy, timeline),
        index,
        count,
        staged=policy["strategy"] == "staged",
    )


def load_motion_time_spec(path: str | Path) -> dict:
    """Load and validate the Motion & Time Spec V1.

    Returns a resolved document carrying the frame-exact ``timeline``, the
    channel policies keyed by channel name, and the resolved proof frames.

    Raises:
        MotionSpecError: If the document is not a well-formed motion spec.
    """
    document = _require_object(
        json.loads(Path(path).read_text(encoding="utf-8")), "motion time spec"
    )
    if document.get("format") != MOTION_TIME_FORMAT:
        raise MotionSpecError(
            f"motion spec format must be {MOTION_TIME_FORMAT!r}, got {document.get('format')!r}"
        )
    version = document.get("schema_version")
    if isinstance(version, bool) or version != MOTION_TIME_SCHEMA_VERSION:
        raise MotionSpecError(
            f"motion spec schema_version must be {MOTION_TIME_SCHEMA_VERSION}, got {version!r}"
        )
    unknown = sorted(
        set(document) - {"format", "schema_version", "timeline", "channels", "proof_samples"}
    )
    if unknown:
        raise MotionSpecError(f"motion spec has unknown top-level fields: {unknown}")

    timeline = resolve_timeline(document)

    entries = document.get("channels")
    if not isinstance(entries, list) or not entries:
        raise MotionSpecError("motion spec must declare a non-empty channels list")
    policies: dict[str, dict] = {}
    for index, entry in enumerate(entries):
        policy = _resolve_channel(entry, index)
        if policy["channel"] in policies:
            raise MotionSpecError(f"motion spec declares channel {policy['channel']!r} twice")
        policies[policy["channel"]] = policy

    return {
        "format": MOTION_TIME_FORMAT,
        "schema_version": MOTION_TIME_SCHEMA_VERSION,
        "timeline": timeline,
        "channels": policies,
        "proof_samples": _resolve_proof_samples(document, timeline),
    }


def require_channel(spec: dict, channel: str) -> dict:
    """Return one channel policy, refusing anything the spec did not declare.

    Raises:
        MotionSpecError: If the channel is unknown or simply not enabled.
    """
    policy = spec["channels"].get(channel)
    if policy is None:
        raise MotionSpecError(
            f"channel {channel!r} is not declared by this motion spec; "
            f"declared channels are {sorted(spec['channels'])}"
        )
    return policy
