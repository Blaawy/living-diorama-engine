"""State Response Spec V1: which authoritative signals Phase 20 may show, and how far.

Pure Python by design -- this module never imports ``bpy`` and never imports the
engine. It validates the Phase 20 presentation contract and binds it to the
locked Phase 17 timeline, so a response plan can be derived, hashed and tested
without Blender installed.

Phase 20 invents no frames. It reads the resolved Phase 17 timeline -- the same
object ``motion_time_spec.resolve_timeline`` returns -- as a **clock only**,
passed in by the caller. The Phase 17 channel registry, its config document and
its semantics are untouched: this spec declares Phase 20's own channels, over
Phase 20's own normalized windows, and resolves them against that borrowed clock
with the same half-up rounding, so the two phases can never disagree about which
frame a normalized position names.

Two rules govern everything here:

    A CHANNEL MAY EXIST ONLY IF AN AUTHORITATIVE FIELD BACKS IT. A reserved
    concept is not a signal. A signal this spec cannot trace to a field the
    Render Export actually carries is refused, never approximated.

    THE SPEC IS A REFUSAL, NEVER A REPAIR. An unknown key, a duplicate channel,
    a reversed window, a non-finite bound or an unsupported source is an error
    with a reason -- not a default quietly substituted for what the author meant.
"""

import json
import math
from pathlib import Path

STATE_RESPONSE_FORMAT = "living_diorama_state_response_spec"
STATE_RESPONSE_SCHEMA_VERSION = 1

SUPPORTED_CHANNELS = (
    "district_air",
    "memory_record",
)
"""Phase 20's own closed channel vocabulary.

This is not a wish list. Each name here is a property the Phase 20 static
application drives from authoritative state, which is the only reason it may
also be animated: an endpoint the static layer never writes could not be proven
equal to the static application of its own export.
"""

SOURCE_KINDS = (
    "district_scalar",
    "memory_fact",
)
"""How a channel reaches its authoritative source.

``district_scalar`` reads one named unit-interval field of one district.
``memory_fact`` reads the engine's own durable memory facts by their structured
type, never by their prose summary.
"""

DISTRICT_SCALARS = (
    "fear",
    "institutional_pressure",
    "scarcity",
    "trust",
)
"""District fields a ``district_scalar`` channel may read.

Every one is stored on the district, serialized by the locked persistence layer,
and validated into ``[0.0, 1.0]`` at export time. Names outside this tuple are
refused even when they appear in the project's reserved vocabulary, because a
reserved concept that no field backs is a concept, not a signal.
"""

MEMORY_FACT_FIELDS = ("fact_type",)
"""Memory-fact members a ``memory_fact`` channel may key off.

Deliberately one member. ``fact_type`` is a structured identifier the engine
assigns; ``summary`` is prose and parsing it would make presentation an author
of meaning rather than a reader of it.
"""

INTERPOLATIONS = ("linear", "smoothstep", "step")
STRATEGIES = ("together", "staged")

_SPEC_KEYS = frozenset({"format", "schema_version", "statement", "channels", "air", "record"})
_CHANNEL_KEYS = frozenset(
    {
        "channel",
        "source_kind",
        "source_field",
        "interpolation",
        "strategy",
        "window",
        "samples",
        "member_span",
        "response_minimum",
        "response_maximum",
    }
)
_AIR_KEYS = frozenset(
    {
        "base_density",
        "rim_margin_metres",
        "ceiling_metres",
        "floor_density_fraction",
        "anisotropy",
        "tint",
    }
)
_RECORD_KEYS = frozenset(
    {
        "origin",
        "arc_radius_metres",
        "arc_start_degrees",
        "arc_step_degrees",
        "capacity",
        "stone_size_metres",
        "plaza_level_metres",
        "lift_metres",
    }
)
_TIMELINE_FIELDS = ("fps", "start_frame", "transition_start", "transition_end", "end_frame")


class StateResponseSpecError(ValueError):
    """A Phase 20 presentation-contract violation.

    Raised for malformed spec documents, unknown or duplicated channels,
    unsupported sources, and timelines that do not carry the fields Phase 20
    reads. Always a refusal, never a repair.
    """


def _require_object(value: object, description: str) -> dict:
    """Return ``value`` as a JSON object or refuse."""
    if not isinstance(value, dict):
        raise StateResponseSpecError(
            f"{description} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _require_keys(document: dict, expected: frozenset, description: str) -> None:
    """Refuse a document that is missing a key or carries one nobody declared."""
    present = set(document)
    missing = sorted(expected - present)
    if missing:
        raise StateResponseSpecError(f"{description} is missing {missing}")
    unexpected = sorted(present - expected)
    if unexpected:
        raise StateResponseSpecError(
            f"{description} declares unexpected keys {unexpected}; "
            "an unrecognised key is refused, never ignored"
        )


def _require_real(value: object, description: str) -> float:
    """Return a finite real number or refuse.

    Booleans are refused outright: ``True`` is not a magnitude, and Python would
    otherwise let it stand in for ``1.0`` without a word.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StateResponseSpecError(f"{description} must be a real number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise StateResponseSpecError(f"{description} must be finite, got {value!r}")
    return number


def _require_positive(value: object, description: str) -> float:
    """Return a finite number greater than zero or refuse."""
    number = _require_real(value, description)
    if number <= 0.0:
        raise StateResponseSpecError(f"{description} must be greater than zero, got {number!r}")
    return number


def _require_exact_int(value: object, description: str) -> int:
    """Return an exact integer or refuse."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise StateResponseSpecError(f"{description} must be an integer, got {value!r}")
    return value


def _require_unit_interval(value: object, description: str) -> float:
    """Return a finite number inside ``[0.0, 1.0]`` or refuse."""
    number = _require_real(value, description)
    if not 0.0 <= number <= 1.0:
        raise StateResponseSpecError(f"{description} must lie in [0, 1], got {number!r}")
    return number


def _require_window(value: object, description: str) -> tuple[float, float]:
    """Return an ordered normalized window or refuse.

    A window is a pair of positions inside the transition, not frame numbers.
    Phase 20 owns no frames; it borrows the Phase 17 clock and resolves against it.
    """
    if not isinstance(value, list) or len(value) != 2:
        raise StateResponseSpecError(f"{description} must be a two-element list, got {value!r}")
    start = _require_unit_interval(value[0], f"{description} start")
    end = _require_unit_interval(value[1], f"{description} end")
    if not start < end:
        raise StateResponseSpecError(
            f"{description} must run forwards, got start={start!r} end={end!r}; "
            "a reversed window is refused, never swapped"
        )
    return start, end


def _require_pair(value: object, description: str) -> tuple[float, float]:
    """Return a two-number pair or refuse."""
    if not isinstance(value, list) or len(value) != 2:
        raise StateResponseSpecError(f"{description} must be a two-element list, got {value!r}")
    return (
        _require_real(value[0], f"{description}[0]"),
        _require_real(value[1], f"{description}[1]"),
    )


def _require_triple(value: object, description: str) -> tuple[float, float, float]:
    """Return a three-number triple or refuse."""
    if not isinstance(value, list) or len(value) != 3:
        raise StateResponseSpecError(f"{description} must be a three-element list, got {value!r}")
    return (
        _require_real(value[0], f"{description}[0]"),
        _require_real(value[1], f"{description}[1]"),
        _require_real(value[2], f"{description}[2]"),
    )


def _resolve_channel(entry: object, index: int) -> dict:
    """Validate one channel policy and return it in canonical form."""
    policy = _require_object(entry, f"channel policy [{index}]")
    channel = policy.get("channel")
    if channel not in SUPPORTED_CHANNELS:
        raise StateResponseSpecError(
            f"channel policy [{index}] declares unsupported channel {channel!r}; "
            f"expected one of {SUPPORTED_CHANNELS}"
        )
    strategy = policy.get("strategy")
    if strategy not in STRATEGIES:
        raise StateResponseSpecError(
            f"channel {channel!r} declares unsupported strategy {strategy!r}; "
            f"expected one of {STRATEGIES}"
        )
    expected = set(_CHANNEL_KEYS)
    if strategy != "staged":
        expected.discard("member_span")
    source_kind = policy.get("source_kind")
    if source_kind not in SOURCE_KINDS:
        raise StateResponseSpecError(
            f"channel {channel!r} declares unsupported source_kind {source_kind!r}; "
            f"expected one of {SOURCE_KINDS}"
        )
    if source_kind != "district_scalar":
        expected.discard("response_minimum")
        expected.discard("response_maximum")
    _require_keys(policy, frozenset(expected), f"channel {channel!r}")

    interpolation = policy.get("interpolation")
    if interpolation not in INTERPOLATIONS:
        raise StateResponseSpecError(
            f"channel {channel!r} declares unsupported interpolation {interpolation!r}; "
            f"expected one of {INTERPOLATIONS}"
        )
    source_field = policy.get("source_field")
    allowed = DISTRICT_SCALARS if source_kind == "district_scalar" else MEMORY_FACT_FIELDS
    if source_field not in allowed:
        raise StateResponseSpecError(
            f"channel {channel!r} reads {source_field!r}, which no authoritative "
            f"{source_kind} carries; expected one of {allowed}"
        )
    window = _require_window(policy.get("window"), f"channel {channel!r} window")
    samples = _require_exact_int(policy.get("samples"), f"channel {channel!r} samples")
    if samples < 1:
        raise StateResponseSpecError(
            f"channel {channel!r} samples must be at least 1, got {samples}"
        )

    resolved = {
        "channel": channel,
        "source_kind": source_kind,
        "source_field": source_field,
        "interpolation": interpolation,
        "strategy": strategy,
        "window": [window[0], window[1]],
        "samples": samples,
    }
    if strategy == "staged":
        resolved["member_span"] = _require_unit_interval(
            policy.get("member_span"), f"channel {channel!r} member_span"
        )
    if source_kind == "district_scalar":
        low = _require_positive(
            policy.get("response_minimum"), f"channel {channel!r} response_minimum"
        )
        high = _require_positive(
            policy.get("response_maximum"), f"channel {channel!r} response_maximum"
        )
        if not low < high:
            raise StateResponseSpecError(
                f"channel {channel!r} response range must widen, got "
                f"minimum={low!r} maximum={high!r}; a collapsed or reversed range would "
                "make a moving signal look still"
            )
        resolved["response_minimum"] = low
        resolved["response_maximum"] = high
    return resolved


def _resolve_air(document: object) -> dict:
    """Validate the district-air field constants."""
    air = _require_object(document, "air block")
    _require_keys(air, _AIR_KEYS, "air block")
    tint = _require_triple(air.get("tint"), "air tint")
    for component in tint:
        if not 0.0 <= component <= 1.0:
            raise StateResponseSpecError(f"air tint components must lie in [0, 1], got {tint!r}")
    if not min(tint) > 0.0:
        raise StateResponseSpecError(
            f"air tint must carry light in every channel, got {tint!r}; "
            "a hue-coded stratum is a heatmap, not weather"
        )
    spread = max(tint) - min(tint)
    if spread > 0.18:
        raise StateResponseSpecError(
            f"air tint spread {spread:.3f} exceeds 0.18; the stratum must stay "
            "near-achromatic so it reads as air rather than as a status colour"
        )
    return {
        "base_density": _require_positive(air.get("base_density"), "air base_density"),
        "rim_margin_metres": _require_positive(
            air.get("rim_margin_metres"), "air rim_margin_metres"
        ),
        "ceiling_metres": _require_positive(air.get("ceiling_metres"), "air ceiling_metres"),
        "floor_density_fraction": _require_unit_interval(
            air.get("floor_density_fraction"), "air floor_density_fraction"
        ),
        "anisotropy": _require_unit_interval(air.get("anisotropy"), "air anisotropy"),
        "tint": [tint[0], tint[1], tint[2]],
    }


def _resolve_record(document: object) -> dict:
    """Validate the memory-record field constants."""
    record = _require_object(document, "record block")
    _require_keys(record, _RECORD_KEYS, "record block")
    origin = _require_pair(record.get("origin"), "record origin")
    size = _require_triple(record.get("stone_size_metres"), "record stone_size_metres")
    for component in size:
        if component <= 0.0:
            raise StateResponseSpecError(
                f"record stone_size_metres must be positive in every axis, got {size!r}"
            )
    capacity = _require_exact_int(record.get("capacity"), "record capacity")
    if capacity < 1:
        raise StateResponseSpecError(f"record capacity must be at least 1, got {capacity}")
    return {
        "origin": [origin[0], origin[1]],
        "arc_radius_metres": _require_positive(
            record.get("arc_radius_metres"), "record arc_radius_metres"
        ),
        "arc_start_degrees": _require_real(
            record.get("arc_start_degrees"), "record arc_start_degrees"
        ),
        "arc_step_degrees": _require_real(
            record.get("arc_step_degrees"), "record arc_step_degrees"
        ),
        "capacity": capacity,
        "stone_size_metres": [size[0], size[1], size[2]],
        "plaza_level_metres": _require_real(
            record.get("plaza_level_metres"), "record plaza_level_metres"
        ),
        "lift_metres": _require_real(record.get("lift_metres"), "record lift_metres"),
    }


def load_state_response_spec(path: str | Path) -> dict:
    """Load and validate one State Response Spec document.

    Args:
        path: Path to the spec JSON.

    Returns:
        The resolved spec: format, schema_version, statement, the channel
        policies in declaration order, and the air and record field constants.

    Raises:
        StateResponseSpecError: If the document is malformed, declares an
            unsupported or duplicated channel, or reads a field no authoritative
            source carries.
    """
    text = Path(path).read_text(encoding="utf-8")
    document = _require_object(json.loads(text), "state response spec")
    _require_keys(document, _SPEC_KEYS, "state response spec")
    if document.get("format") != STATE_RESPONSE_FORMAT:
        raise StateResponseSpecError(
            f"state response spec format must be {STATE_RESPONSE_FORMAT!r}, "
            f"got {document.get('format')!r}"
        )
    version = document.get("schema_version")
    if isinstance(version, bool) or version != STATE_RESPONSE_SCHEMA_VERSION:
        raise StateResponseSpecError(
            f"state response spec schema_version must be {STATE_RESPONSE_SCHEMA_VERSION}, "
            f"got {version!r}"
        )
    statement = document.get("statement")
    if not isinstance(statement, str) or not statement.strip():
        raise StateResponseSpecError("state response spec must carry a non-empty statement")

    entries = document.get("channels")
    if not isinstance(entries, list) or not entries:
        raise StateResponseSpecError("state response spec must declare a non-empty channels list")
    channels = [_resolve_channel(entry, index) for index, entry in enumerate(entries)]
    seen: set[str] = set()
    for policy in channels:
        name = policy["channel"]
        if name in seen:
            raise StateResponseSpecError(
                f"channel {name!r} is declared twice; one channel cannot hold two policies"
            )
        seen.add(name)

    return {
        "format": STATE_RESPONSE_FORMAT,
        "schema_version": STATE_RESPONSE_SCHEMA_VERSION,
        "statement": statement,
        "channels": channels,
        "air": _resolve_air(document.get("air")),
        "record": _resolve_record(document.get("record")),
    }


def require_channel(spec: dict, channel: str) -> dict:
    """Return one declared channel policy or refuse.

    Args:
        spec: A resolved state response spec.
        channel: The channel name to look up.

    Returns:
        The channel's policy.

    Raises:
        StateResponseSpecError: If the spec does not declare that channel.
    """
    for policy in spec["channels"]:
        if policy["channel"] == channel:
            return policy
    declared = sorted(entry["channel"] for entry in spec["channels"])
    raise StateResponseSpecError(
        f"channel {channel!r} is not declared by this state response spec; "
        f"declared channels are {declared}"
    )


def resolve_state_response_timeline(spec: dict, motion_timeline: dict) -> dict:
    """Bind the Phase 20 windows to the locked Phase 17 timeline, read-only.

    Phase 20 invents no frames. It reads the resolved Phase 17 timeline -- the
    same object ``motion_time_spec.resolve_timeline`` returns -- re-validates the
    fields it actually uses with its own error type, and derives nothing that
    would let the two phases disagree.

    Args:
        spec: A resolved state response spec.
        motion_timeline: The resolved Phase 17 timeline block.

    Returns:
        The fields Phase 20 reads, plus the transition span in frames.

    Raises:
        StateResponseSpecError: If the timeline is missing a field Phase 20
            reads, carries a non-integer frame, or does not run forwards.
    """
    timeline = _require_object(motion_timeline, "motion timeline")
    for field in _TIMELINE_FIELDS:
        if field not in timeline:
            raise StateResponseSpecError(
                f"the motion timeline is missing {field!r}; Phase 20 borrows the "
                "Phase 17 clock and cannot supply one of its own"
            )
    resolved = {
        field: _require_exact_int(timeline[field], f"motion timeline {field}")
        for field in _TIMELINE_FIELDS
    }
    if resolved["fps"] < 1:
        raise StateResponseSpecError(f"motion timeline fps must be positive, got {resolved['fps']}")
    ordered = (
        resolved["start_frame"],
        resolved["transition_start"],
        resolved["transition_end"],
        resolved["end_frame"],
    )
    if not ordered[0] <= ordered[1] < ordered[2] <= ordered[3]:
        raise StateResponseSpecError(
            "motion timeline frames must run forwards, got "
            f"start={ordered[0]} transition={ordered[1]}..{ordered[2]} end={ordered[3]}"
        )
    resolved["transition_span"] = ordered[2] - ordered[1]
    _ = spec
    return resolved


def frame_at(timeline: dict, position: float) -> int:
    """Return the frame a normalized position inside the transition names.

    Rounding is half-up, matching the locked Phase 17 helper exactly. If the two
    phases rounded differently, the same normalized position would name adjacent
    frames in the two layers and the shared clock would quietly stop being shared.

    Args:
        timeline: A resolved Phase 20 timeline.
        position: A position inside ``[0.0, 1.0]``.

    Returns:
        The integer frame.

    Raises:
        StateResponseSpecError: If the position lies outside ``[0.0, 1.0]``.
    """
    unit = _require_unit_interval(position, "timeline position")
    span = timeline["transition_span"]
    return int(timeline["transition_start"] + math.floor(unit * span + 0.5))


def channel_frames(policy: dict, timeline: dict) -> tuple[int, int]:
    """Return the first and last frame of one channel's window."""
    window = policy["window"]
    return frame_at(timeline, window[0]), frame_at(timeline, window[1])


def staged_frames(
    window: tuple[int, int], span: int, index: int, count: int, *, staged: bool
) -> tuple[int, int]:
    """Return one member's frame window inside a channel window.

    Args:
        window: The channel's own first and last frame.
        span: The member window's length in frames.
        index: Which member this is.
        count: How many members share the window.
        staged: Whether members are staggered or move together.

    Returns:
        The member's first and last frame.
    """
    start, end = window
    if not staged or count <= 1:
        return start, end
    room = max(0, (end - start) - span)
    offset = int(math.floor((index / (count - 1)) * room + 0.5))
    return start + offset, start + offset + span


def member_span_frames(policy: dict, timeline: dict) -> int:
    """Return one staged member's window length in frames."""
    return int(math.floor(policy["member_span"] * timeline["transition_span"] + 0.5))


def member_window(policy: dict, timeline: dict, index: int, count: int) -> tuple[int, int]:
    """Return one member's frame window, honouring the channel's strategy."""
    return staged_frames(
        channel_frames(policy, timeline),
        member_span_frames(policy, timeline) if policy["strategy"] == "staged" else 0,
        index,
        count,
        staged=policy["strategy"] == "staged",
    )


def interpolate(kind: str, start_value: float, end_value: float, position: float) -> float:
    """Return one eased value, exact at both ends.

    Args:
        kind: One of :data:`INTERPOLATIONS`.
        start_value: The value at position 0.
        end_value: The value at position 1.
        position: A position inside ``[0.0, 1.0]``.

    Returns:
        The eased value. ``position == 0.0`` returns ``start_value`` and
        ``position == 1.0`` returns ``end_value`` exactly, so a sampled curve can
        never drift off its own endpoints.

    Raises:
        StateResponseSpecError: If the interpolation kind is unsupported.
    """
    if kind not in INTERPOLATIONS:
        raise StateResponseSpecError(
            f"unsupported interpolation {kind!r}; expected one of {INTERPOLATIONS}"
        )
    unit = _require_unit_interval(position, "interpolation position")
    if unit == 0.0:
        return start_value
    if unit == 1.0:
        return end_value
    if kind == "step":
        return start_value
    if kind == "smoothstep":
        unit = unit * unit * (3.0 - 2.0 * unit)
    return start_value + (end_value - start_value) * unit


def response_value(policy: dict, signal_value: float) -> float:
    """Map one authoritative unit-interval signal onto its declared response range.

    The mapping is linear and total: the signal's own domain is the whole input,
    and the declared range is the whole output. Phase 20 does not band, threshold
    or curve the reading, because a band would be a judgement the simulation
    never made.

    Args:
        policy: A ``district_scalar`` channel policy.
        signal_value: The authoritative reading, inside ``[0.0, 1.0]``.

    Returns:
        The response magnitude, rounded to six decimal places -- the published
        value is the value that was computed, never a rounded twin nobody checked.

    Raises:
        StateResponseSpecError: If the policy carries no response range, or the
            reading lies outside the unit interval.
    """
    if "response_minimum" not in policy:
        raise StateResponseSpecError(
            f"channel {policy['channel']!r} declares no response range and cannot scale a signal"
        )
    unit = _require_unit_interval(signal_value, f"{policy['source_field']} reading")
    low = policy["response_minimum"]
    high = policy["response_maximum"]
    return round(low + (high - low) * unit, 6)
