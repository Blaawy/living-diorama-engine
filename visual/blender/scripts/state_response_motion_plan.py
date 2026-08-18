"""StateResponseMotionPlan V1: what changed between two authoritative states, and when.

Pure Python by design -- this module never imports ``bpy`` and never imports the
engine. Given two State Response Plans, the Phase 20 presentation contract and
the borrowed Phase 17 clock, it derives a deterministic, sorted, minimal list of
transition directives over Phase 20's own channels only.

The rule that governs everything here is the one Phase 17 established and this
phase inherits:

    A DIRECTIVE MAY EXIST ONLY BECAUSE THE BEFORE-STATE AND THE AFTER-STATE
    GENUINELY DIFFER, and it must be traceable to the exact authoritative field
    that differs. Unchanged state produces no directive. There is no flourish,
    no settle, no motion added because motion looks alive.

Phase 20 animates only what Phase 20's own static application writes, which is
what makes its endpoints provable: frame one must equal the ordinary static
application of the before-export and the last frame the static application of
the after-export. A channel whose static expression does not exist could not
satisfy either, so it is refused here rather than discovered in a render.

The Phase 17 channel registry, its config and its planner are untouched. This
module borrows the resolved timeline as a clock and nothing else.
"""

import hashlib
import json
import math

from state_response_plan import STATE_RESPONSE_PLAN_FORMAT
from state_response_spec import (
    channel_frames,
    interpolate,
    member_window,
    require_channel,
)

STATE_RESPONSE_MOTION_FORMAT = "living_diorama_state_response_motion_plan"
STATE_RESPONSE_MOTION_SCHEMA_VERSION = 1

PRESENCE_ABSENT = 0.0
PRESENCE_PRESENT = 1.0


class StateResponseMotionError(ValueError):
    """A Phase 20 transition-planning violation.

    Raised when two plans cannot be compared, when the world appears to forget
    something it had remembered, and when a directive would be empty. Always a
    refusal, never a repair.
    """


def _by_semantic_id(plan: dict, channel: str) -> dict[str, dict]:
    """Index one plan's responses on one channel by their semantic identity."""
    indexed: dict[str, dict] = {}
    for response in plan["responses"]:
        if response["channel"] != channel:
            continue
        semantic_id = response["semantic_id"]
        if semantic_id in indexed:
            raise StateResponseMotionError(
                f"plan declares {channel} response {semantic_id!r} twice; "
                "identity is indexed, never taken from array order"
            )
        indexed[semantic_id] = response
    return indexed


def _require_plan(plan: object, label: str) -> dict:
    """Return a state response plan or refuse."""
    if not isinstance(plan, dict):
        raise StateResponseMotionError(f"the {label} plan must be a JSON object")
    if plan.get("format") != STATE_RESPONSE_PLAN_FORMAT:
        raise StateResponseMotionError(
            f"the {label} plan format must be {STATE_RESPONSE_PLAN_FORMAT!r}, "
            f"got {plan.get('format')!r}"
        )
    if not isinstance(plan.get("responses"), list):
        raise StateResponseMotionError(f"the {label} plan must carry a responses array")
    return plan


def _directive(
    *,
    channel: str,
    semantic_id: str,
    target: dict,
    interpolation: str,
    samples: int,
    start_frame: int,
    end_frame: int,
    from_value: float,
    to_value: float,
    source_before: str,
    source_after: str,
) -> dict:
    """Build one transition directive, refusing one that carries no transition.

    ``source_before`` and ``source_after`` are required: a directive that cannot
    say which authoritative reading produced it is not falsifiable, and an
    unfalsifiable directive is decoration.
    """
    for label, value in (("before", from_value), ("after", to_value)):
        # NaN would slip past the equality guard below -- it is equal to nothing,
        # not even itself -- and produce a directive that only fails much later,
        # when the plan is encoded. A reading that is not a number is refused here.
        usable = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not usable or not math.isfinite(value):
            raise StateResponseMotionError(
                f"channel {channel!r} target {semantic_id!r} carries a non-finite "
                f"{label}-value {value!r}"
            )
    if from_value == to_value:
        raise StateResponseMotionError(
            f"channel {channel!r} target {semantic_id!r} reads {from_value!r} at both ends; "
            "refusing an empty directive; unchanged state never produces motion"
        )
    if start_frame >= end_frame:
        raise StateResponseMotionError(
            f"channel {channel!r} target {semantic_id!r} would run from frame {start_frame} "
            f"to {end_frame}; a directive must run forwards"
        )
    return {
        "channel": channel,
        "semantic_id": semantic_id,
        "target": target,
        "interpolation": interpolation,
        "samples": samples,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "from_value": from_value,
        "to_value": to_value,
        "source_before": source_before,
        "source_after": source_after,
    }


def _sort_key(directive: dict) -> tuple:
    """Return a total order that no mapping's iteration order can disturb."""
    return (
        directive["channel"],
        directive["semantic_id"],
        json.dumps(directive["target"], sort_keys=True),
        directive["start_frame"],
        directive["end_frame"],
    )


def _air_directives(before: dict, after: dict, policy: dict, timeline: dict) -> list[dict]:
    """Derive the district-air transitions, refusing a changed district set."""
    channel = policy["channel"]
    before_air = _by_semantic_id(before, channel)
    after_air = _by_semantic_id(after, channel)
    if set(before_air) != set(after_air):
        raise StateResponseMotionError(
            f"the two plans describe different districts for {channel!r}: "
            f"{sorted(before_air)} and {sorted(after_air)}; a transition between two "
            "different worlds is not a transition"
        )
    start_frame, end_frame = channel_frames(policy, timeline)
    directives: list[dict] = []
    for semantic_id in sorted(after_air):
        start = before_air[semantic_id]
        end = after_air[semantic_id]
        if start["target"] != end["target"]:
            raise StateResponseMotionError(
                f"{channel!r} response {semantic_id!r} changes target between the two plans; "
                "one district's air is one property, not two"
            )
        if start["value"] == end["value"]:
            continue
        directives.append(
            _directive(
                channel=channel,
                semantic_id=semantic_id,
                target=end["target"],
                interpolation=policy["interpolation"],
                samples=policy["samples"],
                start_frame=start_frame,
                end_frame=end_frame,
                from_value=start["value"],
                to_value=end["value"],
                source_before=f"{start['source_path']}={start['source_value']}",
                source_after=f"{end['source_path']}={end['source_value']}",
            )
        )
    return directives


def _record_directives(before: dict, after: dict, policy: dict, timeline: dict) -> list[dict]:
    """Derive the memory-record transitions, refusing a world that forgot.

    Memory is cumulative by construction: the engine's own durable fact list only
    grows. A fact present in the before-plan and absent from the after-plan means
    the two documents are not consecutive states of one world, and no easing
    could make that honest.
    """
    channel = policy["channel"]
    before_records = _by_semantic_id(before, channel)
    after_records = _by_semantic_id(after, channel)
    forgotten = sorted(set(before_records) - set(after_records))
    if forgotten:
        raise StateResponseMotionError(
            f"the after plan no longer remembers {forgotten}; durable memory only grows, "
            "so these two documents are not consecutive states of one world"
        )
    appearing = sorted(set(after_records) - set(before_records))
    directives: list[dict] = []
    for index, semantic_id in enumerate(appearing):
        response = after_records[semantic_id]
        start_frame, end_frame = member_window(policy, timeline, index, len(appearing))
        directives.append(
            _directive(
                channel=channel,
                semantic_id=semantic_id,
                target=response["target"],
                interpolation=policy["interpolation"],
                samples=policy["samples"],
                start_frame=start_frame,
                end_frame=end_frame,
                from_value=PRESENCE_ABSENT,
                to_value=PRESENCE_PRESENT,
                source_before="memory.facts: absent",
                source_after=f"{response['source_path']}={response['source_value']}",
            )
        )
    return directives


def plan_state_response_motion(
    before_plan: dict, after_plan: dict, spec: dict, timeline: dict
) -> dict:
    """Derive one transition plan between two authoritative state response plans.

    Args:
        before_plan: The plan derived from the earlier export.
        after_plan: The plan derived from the later export.
        spec: A resolved state response spec.
        timeline: A resolved Phase 20 timeline, borrowed from Phase 17.

    Returns:
        The transition plan: format, schema_version, the two provenance blocks,
        the directives in total order, and a summary derived from the body.

    Raises:
        StateResponseMotionError: If the two plans cannot be compared, if the
            world appears to have forgotten a durable fact, or if a directive
            would carry no transition.
    """
    before = _require_plan(before_plan, "before")
    after = _require_plan(after_plan, "after")

    directives = _air_directives(before, after, require_channel(spec, "district_air"), timeline)
    directives.extend(
        _record_directives(before, after, require_channel(spec, "memory_record"), timeline)
    )
    directives.sort(key=_sort_key)

    targets: dict[str, str] = {}
    for directive in directives:
        target = json.dumps(directive["target"], sort_keys=True)
        owner = targets.get(target)
        if owner is not None:
            raise StateResponseMotionError(
                f"directives {owner!r} and {directive['semantic_id']!r} drive the same target "
                f"{target}; one property cannot carry two transitions"
            )
        targets[target] = directive["semantic_id"]

    by_channel: dict[str, int] = {}
    for directive in directives:
        by_channel[directive["channel"]] = by_channel.get(directive["channel"], 0) + 1

    return {
        "format": STATE_RESPONSE_MOTION_FORMAT,
        "schema_version": STATE_RESPONSE_MOTION_SCHEMA_VERSION,
        "timeline": dict(sorted(timeline.items())),
        "source_before": before["source"],
        "source_after": after["source"],
        "directives": directives,
        "summary": {
            "directives": len(directives),
            "directives_by_channel": dict(sorted(by_channel.items())),
            "unchanged_channels": sorted(
                policy["channel"]
                for policy in spec["channels"]
                if policy["channel"] not in by_channel
            ),
        },
    }


def keyframes(directive: dict) -> list[tuple[int, float]]:
    """Return the exact keys one directive writes.

    The first key is forced to ``from_value`` and the last to ``to_value``, so a
    sampled curve can never drift off the endpoints the static applications
    define. A step channel writes exactly two keys, because a value that holds
    and then swaps has nothing to sample in between.

    Args:
        directive: One transition directive.

    Returns:
        ``(frame, value)`` pairs in ascending frame order.
    """
    start_frame = directive["start_frame"]
    end_frame = directive["end_frame"]
    from_value = directive["from_value"]
    to_value = directive["to_value"]
    if directive["interpolation"] == "step":
        return [(start_frame, from_value), (end_frame, to_value)]
    span = end_frame - start_frame
    # Never ask for more samples than the window has distinct frames. Sampling a
    # short window more finely than one key per frame would land two keys on one
    # frame, and collapsing those would overwrite an endpoint -- the very value
    # the endpoint proof rests on. Fewer keys is a coarser curve; a moved
    # endpoint is a false frame.
    samples = max(2, min(directive["samples"], span + 1))
    keys: list[tuple[int, float]] = []
    for index in range(samples):
        position = index / (samples - 1)
        frame = start_frame + int(round(position * span))
        value = interpolate(directive["interpolation"], from_value, to_value, position)
        keys.append((frame, value))
    keys[0] = (start_frame, from_value)
    keys[-1] = (end_frame, to_value)
    frames = [frame for frame, _value in keys]
    if len(set(frames)) != len(frames):
        raise StateResponseMotionError(
            f"channel {directive['channel']!r} target {directive['semantic_id']!r} would write "
            f"two keys on one frame across {frames}; refusing a curve whose endpoints "
            "cannot both be honoured"
        )
    return keys


def canonical_plan_bytes(plan: dict) -> bytes:
    """Return the plan's canonical encoding: sorted keys, compact, UTF-8, one newline."""
    payload = json.dumps(
        plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return (payload + "\n").encode("utf-8")


def plan_hash(plan: dict) -> str:
    """Return the SHA-256 of the plan's canonical encoding."""
    return hashlib.sha256(canonical_plan_bytes(plan)).hexdigest()


def validate_state_response_motion_plan(plan: dict) -> list[str]:
    """Re-derive every claim the transition plan makes about itself.

    Args:
        plan: A state response motion plan.

    Returns:
        Every problem found, in the order found. An empty list means the plan
        says only true things about itself.
    """
    problems: list[str] = []
    if plan.get("format") != STATE_RESPONSE_MOTION_FORMAT:
        problems.append(
            f"format must be {STATE_RESPONSE_MOTION_FORMAT!r}, got {plan.get('format')!r}"
        )
    directives = plan.get("directives")
    if not isinstance(directives, list):
        return [*problems, "directives must be a JSON array"]

    keys = [_sort_key(directive) for directive in directives]
    if keys != sorted(keys):
        problems.append("directives are not in their own total order")
    timeline = plan.get("timeline")
    for directive in directives:
        label = directive["semantic_id"]
        if directive["from_value"] == directive["to_value"]:
            problems.append(f"directive {label!r} carries no transition")
        if directive["start_frame"] >= directive["end_frame"]:
            problems.append(f"directive {label!r} does not run forwards")
        if isinstance(timeline, dict):
            if directive["start_frame"] < timeline.get("transition_start", 0):
                problems.append(f"directive {label!r} starts before the transition does")
            if directive["end_frame"] > timeline.get("transition_end", 0):
                problems.append(f"directive {label!r} ends after the transition does")
        written = keyframes(directive)
        if written[0] != (directive["start_frame"], directive["from_value"]):
            problems.append(f"directive {label!r} does not begin on its own before-value")
        if written[-1] != (directive["end_frame"], directive["to_value"]):
            problems.append(f"directive {label!r} does not land on its own after-value")
        for field in ("source_before", "source_after"):
            if not str(directive.get(field, "")).strip():
                problems.append(f"directive {label!r} carries no {field}")

    summary = plan.get("summary")
    if not isinstance(summary, dict):
        return [*problems, "summary must be a JSON object"]
    if summary.get("directives") != len(directives):
        problems.append(
            f"summary claims {summary.get('directives')!r} directives, "
            f"the body carries {len(directives)}"
        )
    by_channel: dict[str, int] = {}
    for directive in directives:
        by_channel[directive["channel"]] = by_channel.get(directive["channel"], 0) + 1
    if summary.get("directives_by_channel") != dict(sorted(by_channel.items())):
        problems.append(
            f"summary claims {summary.get('directives_by_channel')!r} per channel, "
            f"the body carries {dict(sorted(by_channel.items()))}"
        )
    return problems


__all__ = [
    "PRESENCE_ABSENT",
    "PRESENCE_PRESENT",
    "STATE_RESPONSE_MOTION_FORMAT",
    "STATE_RESPONSE_MOTION_SCHEMA_VERSION",
    "StateResponseMotionError",
    "canonical_plan_bytes",
    "keyframes",
    "plan_hash",
    "plan_state_response_motion",
    "validate_state_response_motion_plan",
]
