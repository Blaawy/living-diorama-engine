"""Deriving a Shot Direction Plan from a story plan and the locked Phase 17 clock.

The derivation is a pure function of its inputs. It reads no clock, draws no
randomness, consults no filesystem path, imports no Blender, and depends on no
iteration order Python is free to vary. The same story plan and Motion & Time
Spec bytes always produce the same bytes.

What it decides is viewpoint and duration. What it never decides is meaning:
Phase 21's ranking is copied, never recomputed, and a beat's emphasis is used to
allocate screen time, never to re-rank it. An event Phase 21 excluded does not
exist here.

Frames are never invented, and neither is the clock they live on. The timeline
arrives as the exact bytes of a Phase 17 Motion & Time Spec document, passed in
as data -- Phase 17 itself is never imported. The plan binds the SHA-256 of those
bytes, restates the six source timeline fields, and derives the phase boundaries
with Phase 17's own arithmetic, so a plan cut against an invented alternate clock
either fails its own arithmetic here or is exposed by its digest the moment
anyone holds the real document. Simulation ticks are deliberately not converted
into frames: beat order comes from Phase 21's rank, which already encodes history
order, and screen time comes from emphasis weight. There is no tick-to-frame
mapping in this layer, because no contract justifies one.
"""

import json
from typing import Final, cast

from living_diorama.cinematic.cinematic_schema_v1 import (
    MAX_TIMELINE_FPS,
    MAX_TIMELINE_FRAME,
    MOTION_TIME_FORMAT,
    REVIEWED_CLOCKS,
    SHOT_ID_FORM,
    SHOT_PLAN_FORMAT,
    SHOT_SCHEMA_VERSION,
    SUPPORTED_MOTION_SCHEMA_VERSION,
    JsonValue,
    validate_shot_direction_plan,
)
from living_diorama.cinematic.cinematic_spec import (
    ESTABLISHING_ANCHOR,
    MIN_SHOT_FRAMES,
    REASON_ADJACENT_SAME_ANCHOR_MERGED,
    REASON_NEUTRAL_ESTABLISHING,
    REASON_TRANSITION_BUDGET_EXHAUSTED,
    SHOT_BEAT,
    SHOT_ESTABLISHING,
    UNSHOWN_BEAT_KINDS,
    anchor_for_beat,
    catalogue_sha256,
    weight_for_emphasis,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.story import validate_episode_story_plan

MOTION_TIMELINE_SOURCE_KEYS: Final = (
    "end_frame",
    "end_hold_frames",
    "fps",
    "start_frame",
    "start_hold_frames",
    "transition_frames",
)
"""The six timeline fields a Motion & Time Spec declares, restated as data.

Phase 17 is never imported, so there is no name through which this layer could
read its channel registry, extend it, or come to depend on a detail Phase 17 is
still free to change -- the same borrowing rule Phase 19 established and
Phase 20's boundary test enforces. The in-Blender structural suite proves this
restatement and the derivation below against ``motion_time_spec`` itself.
"""


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def _reject_duplicate_keys(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    """Refuse a JSON object that declares the same key twice.

    ``json.loads`` silently keeps the last occurrence, which would let a clock
    document carry two different values for one field while binding a single
    digest -- an ambiguity a source-bound contract must not accept.
    """
    document: dict[str, JsonValue] = {}
    for key, entry in pairs:
        if key in document:
            raise ValueError(f"motion time spec declares key {key!r} twice")
        document[key] = entry
    return document


def _require_bounded_int(value: object, description: str, minimum: int, maximum: int) -> int:
    if type(value) is not int:
        raise TypeError(f"{description} must be an int, got {type(value).__name__}")
    if not minimum <= value <= maximum:
        raise ValueError(f"{description} must be within [{minimum}, {maximum}], got {value}")
    return value


def resolve_motion_time_binding(motion_time: object) -> dict[str, JsonValue]:
    """Resolve the exact bytes of a Motion & Time Spec into a clock binding.

    The argument is the document's raw bytes, exactly as they exist in the
    canonical tree -- not a parsed or re-encoded form -- because the binding
    digest must name the source document itself. The result carries the motion
    format identity, its schema version, the SHA-256 of the bytes, and the
    resolved timeline: the six source fields plus ``transition_start`` and
    ``transition_end``, derived with Phase 17's own arithmetic
    (``transition_start = start_frame + start_hold_frames``,
    ``transition_end = transition_start + transition_frames``, and the declared
    ``end_frame`` must close the sum).

    Only the fields this layer reads are validated: the format tag, the schema
    version, and the timeline. The channel and proof-sample sections belong to
    Phase 17, are already validated by its own loader, and are pinned here by
    the digest rather than re-specified -- restating their schema would make
    this layer refuse a future canonical Motion & Time Spec that Phase 17 is
    free to extend.

    Raises:
        TypeError: If the argument is not ``bytes`` or a field has the wrong
            type.
        ValueError: If the bytes are not UTF-8 JSON, the format or schema
            version is not the one this build directs against, the timeline is
            malformed or out of bounds, or the declared end frame disagrees
            with the timeline's own phase arithmetic.
    """
    if type(motion_time) is not bytes:
        raise TypeError(
            f"motion time spec must arrive as bytes, got {type(motion_time).__name__}; "
            "the binding digest names the source document itself"
        )
    try:
        parsed = json.loads(motion_time.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"motion time spec is not valid UTF-8 JSON: {error}") from None
    document = _document(parsed, "motion time spec")

    tag = document.get("format")
    if tag != MOTION_TIME_FORMAT:
        raise ValueError(
            f"motion time spec declares format {tag!r}; this build directs against "
            f"{MOTION_TIME_FORMAT!r} only"
        )
    version = document.get("schema_version")
    if type(version) is not int or version != SUPPORTED_MOTION_SCHEMA_VERSION:
        raise ValueError(
            f"motion time spec declares schema version {version!r}; this build directs "
            f"against version {SUPPORTED_MOTION_SCHEMA_VERSION} only"
        )

    timeline = _document(document.get("timeline"), "motion time spec timeline")
    unknown = sorted(set(timeline) - set(MOTION_TIMELINE_SOURCE_KEYS))
    if unknown:
        raise ValueError(f"motion time spec timeline has unknown fields: {unknown}")
    missing = sorted(set(MOTION_TIMELINE_SOURCE_KEYS) - set(timeline))
    if missing:
        raise ValueError(f"motion time spec timeline is missing fields: {missing}")

    positive = ("fps", "start_hold_frames", "transition_frames", "end_hold_frames")
    fields: dict[str, int] = {}
    for name in MOTION_TIMELINE_SOURCE_KEYS:
        high = MAX_TIMELINE_FPS if name == "fps" else MAX_TIMELINE_FRAME
        fields[name] = _require_bounded_int(
            timeline[name], f"motion time spec timeline {name}", 1 if name in positive else 0, high
        )

    transition_start = fields["start_frame"] + fields["start_hold_frames"]
    transition_end = transition_start + fields["transition_frames"]
    computed_end = transition_end + fields["end_hold_frames"]
    if fields["end_frame"] != computed_end:
        raise ValueError(
            f"motion time spec timeline end_frame {fields['end_frame']} disagrees with its "
            f"own phases: {fields['start_frame']} + {fields['start_hold_frames']} + "
            f"{fields['transition_frames']} + {fields['end_hold_frames']} = {computed_end}"
        )

    resolved: dict[str, JsonValue] = dict(fields)
    resolved["transition_start"] = transition_start
    resolved["transition_end"] = transition_end

    # Shape and arithmetic prove the document is a plausible Phase 17 clock;
    # this proves it is a REVIEWED clock. A well-formed 30 fps or shifted
    # document, or any document outside the closed reviewed set, is refused
    # here outright, so no plan can ever exist against an alternate source,
    # however internally consistent. Shape runs first purely for diagnostics --
    # a malformed document earns its specific refusal instead of a digest
    # mismatch.
    digest = sha256_hex(motion_time)
    if digest not in REVIEWED_CLOCKS:
        raise ValueError(
            f"motion time spec bytes hash to {digest}, which is not the canonical "
            f"Phase 17 Motion & Time Spec this build was reviewed against "
            f"(admissible reviewed clocks: {', '.join(sorted(REVIEWED_CLOCKS))}); "
            "Phase 22 directs the locked clock, not any document shaped like one"
        )
    return {
        "motion_time_format": MOTION_TIME_FORMAT,
        "motion_time_schema_version": SUPPORTED_MOTION_SCHEMA_VERSION,
        "motion_time_sha256": digest,
        "timeline": resolved,
    }


def _allocate(weights: list[int], total: int) -> list[int]:
    """Split ``total`` frames across weights, deterministically and fairly.

    Every group is given the minimum first, and only the surplus is shared by
    weight using largest remainder with the group index as the tie-break. That
    ordering matters: allocating by weight first and repairing minimums afterwards
    would make the result depend on which group happened to be repaired.
    """
    count = len(weights)
    surplus = total - count * MIN_SHOT_FRAMES
    if surplus < 0:
        raise ValueError(
            f"cannot fit {count} shots of at least {MIN_SHOT_FRAMES} frames into {total} frames"
        )
    weight_total = sum(weights)
    exact = [surplus * weight / weight_total for weight in weights]
    floors = [int(value) for value in exact]
    remainder = surplus - sum(floors)
    order = sorted(range(count), key=lambda index: (-(exact[index] - floors[index]), index))
    for index in order[:remainder]:
        floors[index] += 1
    return [MIN_SHOT_FRAMES + extra for extra in floors]


def build_shot_direction_plan_document(
    story_plan: object, motion_time: object
) -> dict[str, JsonValue]:
    """Return the Shot Direction Plan for one story plan on one locked clock.

    Args:
        story_plan: A validated Episode Story Plan V1 document.
        motion_time: The exact bytes of the Phase 17 Motion & Time Spec the plan
            is cut against, passed in as data. Phase 17 is never imported; the
            plan binds the SHA-256 of these bytes.

    Returns:
        A validated Shot Direction Plan V1 document.

    Raises:
        TypeError: If either input has the wrong shape.
        ValueError: If the story plan fails its own contract, if the motion
            spec is not one this build can direct against, or if the beats
            cannot be fitted into the transition.
    """
    plan = validate_episode_story_plan(story_plan)
    binding = resolve_motion_time_binding(motion_time)
    clock = cast(dict[str, int], binding["timeline"])

    source = _document(plan["source"], "story plan source")
    current = _document(source["current"], "story plan source current")
    mode = cast(str, source["mode"])
    episode = cast(int, current["episode"])
    previous_episode: JsonValue = None
    if mode != "baseline":
        previous = _document(source["previous"], "story plan source previous")
        previous_episode = previous["episode"]

    beats = cast(list[dict[str, JsonValue]], plan["beats"])

    # One anchor per beat, from the closed table. The empty-result beat earns no
    # shot: it reports that nothing was emphasised, and framing nothing is not
    # direction.
    directed: list[dict[str, JsonValue]] = []
    unshown: list[dict[str, JsonValue]] = []
    for beat in beats:
        kind = cast(str, beat["kind"])
        beat_id = cast(str, beat["beat_id"])
        deliberate = UNSHOWN_BEAT_KINDS.get(kind)
        if deliberate is not None:
            unshown.append({"beat_id": beat_id, "reason_code": deliberate})
            continue
        anchor, reason = anchor_for_beat(kind)
        directed.append(
            {
                "anchor": anchor,
                "beat_id": beat_id,
                "emphasis": beat["emphasis"],
                "reason": reason,
            }
        )

    # Consecutive beats resolving to the same anchor become one shot. Cutting to
    # the camera you are already on is not a cut.
    groups: list[dict[str, JsonValue]] = []
    for entry in directed:
        if groups and groups[-1]["anchor"] == entry["anchor"]:
            group = groups[-1]
            cast(list[str], group["beat_ids"]).append(cast(str, entry["beat_id"]))
            group["weight"] = cast(int, group["weight"]) + weight_for_emphasis(
                cast(str, entry["emphasis"])
            )
            group["reason"] = REASON_ADJACENT_SAME_ANCHOR_MERGED
            continue
        groups.append(
            {
                "anchor": entry["anchor"],
                "beat_ids": cast(JsonValue, [cast(str, entry["beat_id"])]),
                "emphasis": entry["emphasis"],
                "reason": entry["reason"],
                "weight": weight_for_emphasis(cast(str, entry["emphasis"])),
            }
        )

    transition_span = clock["transition_end"] - clock["transition_start"]
    capacity = transition_span // MIN_SHOT_FRAMES
    if len(groups) > capacity:
        for group in groups[capacity:]:
            for beat_id in cast(list[str], group["beat_ids"]):
                unshown.append(
                    {
                        "beat_id": beat_id,
                        "reason_code": REASON_TRANSITION_BUDGET_EXHAUSTED,
                    }
                )
        groups = groups[:capacity]

    shots: list[dict[str, JsonValue]] = []
    if not groups:
        # Nothing to emphasise. One neutral shot holds the whole locked timeline.
        shots.append(
            {
                "camera_anchor_id": ESTABLISHING_ANCHOR,
                "emphasis": None,
                "end_frame": clock["end_frame"],
                "kind": SHOT_ESTABLISHING,
                "reason_code": REASON_NEUTRAL_ESTABLISHING,
                "source_beat_ids": cast(JsonValue, []),
                "start_frame": clock["start_frame"],
            }
        )
    else:
        shots.append(
            {
                "camera_anchor_id": ESTABLISHING_ANCHOR,
                "emphasis": None,
                "end_frame": clock["transition_start"] - 1,
                "kind": SHOT_ESTABLISHING,
                "reason_code": REASON_NEUTRAL_ESTABLISHING,
                "source_beat_ids": cast(JsonValue, []),
                "start_frame": clock["start_frame"],
            }
        )
        lengths = _allocate([cast(int, group["weight"]) for group in groups], transition_span)
        cursor = clock["transition_start"]
        for group, length in zip(groups, lengths, strict=True):
            shots.append(
                {
                    "camera_anchor_id": group["anchor"],
                    "emphasis": group["emphasis"],
                    "end_frame": cursor + length - 1,
                    "kind": SHOT_BEAT,
                    "reason_code": group["reason"],
                    "source_beat_ids": cast(JsonValue, sorted(cast(list[str], group["beat_ids"]))),
                    "start_frame": cursor,
                }
            )
            cursor += length
        shots.append(
            {
                "camera_anchor_id": ESTABLISHING_ANCHOR,
                "emphasis": None,
                "end_frame": clock["end_frame"],
                "kind": SHOT_ESTABLISHING,
                "reason_code": REASON_NEUTRAL_ESTABLISHING,
                "source_beat_ids": cast(JsonValue, []),
                "start_frame": cursor,
            }
        )

    # A beat group may resolve to the establishing anchor -- an unknown beat kind
    # does, by design. Merging afterwards keeps the "adjacent shots never share an
    # anchor" rule true without special-casing it during allocation.
    merged: list[dict[str, JsonValue]] = []
    for shot in shots:
        if merged and merged[-1]["camera_anchor_id"] == shot["camera_anchor_id"]:
            previous_shot = merged[-1]
            previous_shot["end_frame"] = shot["end_frame"]
            combined = sorted(
                cast(list[str], previous_shot["source_beat_ids"])
                + cast(list[str], shot["source_beat_ids"])
            )
            previous_shot["source_beat_ids"] = cast(JsonValue, combined)
            if combined:
                previous_shot["kind"] = SHOT_BEAT
                previous_shot["reason_code"] = (
                    REASON_ADJACENT_SAME_ANCHOR_MERGED if len(combined) > 1 else shot["reason_code"]
                )
                if previous_shot["emphasis"] is None:
                    previous_shot["emphasis"] = shot["emphasis"]
            continue
        merged.append(dict(shot))

    for position, shot in enumerate(merged):
        shot["shot_id"] = SHOT_ID_FORM % (position + 1)
        if shot["kind"] == SHOT_ESTABLISHING:
            shot["emphasis"] = None

    document: dict[str, JsonValue] = {
        "format": SHOT_PLAN_FORMAT,
        "schema_version": SHOT_SCHEMA_VERSION,
        "shots": cast(JsonValue, merged),
        "source": cast(
            JsonValue,
            {
                "catalogue_sha256": catalogue_sha256(),
                "episode": episode,
                "mode": mode,
                "motion_time_format": binding["motion_time_format"],
                "motion_time_schema_version": binding["motion_time_schema_version"],
                "motion_time_sha256": binding["motion_time_sha256"],
                "previous_episode": previous_episode,
                "story_plan_sha256": sha256_hex(dumps_canonical(plan, "episode story plan")),
                "story_schema_version": plan["schema_version"],
            },
        ),
        "timeline": cast(JsonValue, dict(clock)),
        "unshown": cast(JsonValue, sorted(unshown, key=lambda entry: cast(str, entry["beat_id"]))),
    }
    return validate_shot_direction_plan(document)


def build_shot_direction_plan_bytes(story_plan: object, motion_time: object) -> bytes:
    """Return the canonical Shot Direction Plan bytes for the given inputs.

    Sorted keys, tight separators, no non-finite floats, exactly one trailing
    newline -- the same canonical encoding every other document in this project
    uses.
    """
    document = build_shot_direction_plan_document(story_plan, motion_time)
    return dumps_canonical(document, "shot direction plan")
