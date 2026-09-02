"""Deriving an Episode Narration Delivery Plan from a narration plan and a direction.

The derivation is a pure function of its inputs. It reads no clock, draws no
randomness, consults no filesystem path, calls no model, opens no socket, and
depends on no iteration order that Python is free to vary. The same two
documents always produce the same bytes.

What it decides is when each narration unit may be delivered, and only from
structure: unit order, visibility, the citing shots' spans, and the locked
Phase 17 clock the shot plan restates. What it never decides is what is said,
what mattered, or what is framed. Wording stays in the narration plan and --
under the v1 profile, the default and the historical output -- is never read
here: not carried, not measured, not counted. Visibility is the narration
plan's report of Phase 22's decision, re-verified against the shot plan and
never re-judged. Shots are never moved, resized or re-cut.

The v4 delivery profile is this layer's one reviewed exception to the no-text
rule: it counts the words of each unit's finalized sentence to weight a shared
host interval in proportion to the speech that sentence will carry (see
``required_frames_for_word_count`` in ``delivery_spec`` for the calibrated
formula and the safety argument). The measurement is a count only -- the
sentence itself is never carried, compared or emitted.

The slot allocation is deliberately small enough to state in full. Every shot's
playback segment is its span clamped to the playback domain, because the
terminal witness frame is never played back. A SHOWN unit is hosted by its
citing shot's segment. A maximal run of UNSHOWN units is hosted by the free
interval between its SHOWN neighbours' segments when that interval is nonempty;
when it is empty -- the canonical episode 1 case, where two beat shots sit
frame-adjacent around a durable consequence nobody could film -- the run folds
backward into the preceding segment, or forward into the following one when no
preceding SHOWN unit exists. Every host interval is then partitioned among its
claimants in unit order -- equally under v1, and in proportion to each
claimant's required speech frames under v4. Folding backward rather than
forward keeps each segment's first slot starting on its own cut, so a shown
unit's narration never drifts past the footage it belongs to.
"""

from collections.abc import Sequence
from typing import Final, cast

from living_diorama.cinematic import validate_shot_direction_plan_v2
from living_diorama.narration.narration_schema_v1 import (
    UNIT_ID_FORM,
    validate_episode_narration_plan,
)
from living_diorama.narration.narration_spec import VISIBILITY_SHOWN, VISIBILITY_UNSHOWN
from living_diorama.narration_delivery.delivery_schema_v1 import (
    JsonValue,
    validate_episode_narration_delivery_plan,
)
from living_diorama.narration_delivery.delivery_spec import (
    DELIVERY_ID_FORM,
    DELIVERY_PLAN_FORMAT,
    DELIVERY_POLICY_V1,
    DELIVERY_POLICY_V4,
    DELIVERY_SCHEMA_VERSION,
    PLACEMENT_ALLOCATED_UNSHOWN,
    PLACEMENT_SHOT_ANCHORED,
    partition_equally,
    partition_proportionally,
    playback_domain,
    required_frames_for_word_count,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex

FRAMING_FIELDS: Final = ("visibility", "shot_id", "start_frame", "end_frame", "unshown_reason")
"""The five facts Phase 24 copied from the direction, re-verified here.

A narration plan validates on its own without the shot plan in the room, so a
hand-written plan could bind the right digest while its units lied about what
the direction granted. Delivery schedules the framing the direction actually
holds, so every copied field is checked against the shot plan before a single
slot is cut.
"""

__all__ = [
    "build_episode_narration_delivery_plan_bytes",
    "build_episode_narration_delivery_plan_document",
    "resolve_delivery_slots",
]


def _document(value: object, description: str) -> dict[str, JsonValue]:
    if type(value) is not dict:
        raise TypeError(f"{description} must be a dict, got {type(value).__name__}")
    return cast(dict[str, JsonValue], value)


def _require_delivery_profile(delivery_profile: str) -> None:
    """Refuse a delivery profile this build does not derive."""
    if delivery_profile not in ("v1", "v4"):
        raise ValueError(
            f"delivery profile {delivery_profile!r} is not reviewed; this build derives "
            "'v1' (equal partition) and 'v4' (content-proportional partition) only"
        )


def _require_join(
    narration: dict[str, JsonValue], shots: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """Prove the two documents describe one directed episode, and return the binding.

    Digest equality is the load-bearing check: the narration plan already
    recorded which shot plan it reported visibility from, so a delivery layer
    never has to decide whether two files "look like" the same episode. It asks
    the narration plan what it bound and compares against the document offered.

    Raises:
        ValueError: If any binding or identity does not hold.
    """
    narration_source = _document(narration["source"], "episode narration plan source")
    shot_source = _document(shots["source"], "shot direction plan source")

    narration_digest = sha256_hex(dumps_canonical(narration, "episode narration plan"))
    shot_digest = sha256_hex(dumps_canonical(shots, "shot direction plan"))

    if narration_source["shot_plan_sha256"] != shot_digest:
        raise ValueError(
            f"the narration plan reports visibility from shot plan "
            f"{narration_source['shot_plan_sha256']}, but the offered shot plan hashes to "
            f"{shot_digest}; these two documents are not about the same directed episode"
        )
    if narration_source["mode"] != shot_source["mode"]:
        raise ValueError(
            f"the narration plan is {narration_source['mode']!r} mode but the shot plan is "
            f"{shot_source['mode']!r} mode"
        )
    if narration_source["episode"] != shot_source["episode"]:
        raise ValueError(
            f"the narration plan describes episode {narration_source['episode']} but the "
            f"shot plan describes episode {shot_source['episode']}"
        )
    if narration_source["previous_episode"] != shot_source["previous_episode"]:
        raise ValueError(
            f"the narration plan follows episode {narration_source['previous_episode']!r} "
            f"but the shot plan follows episode {shot_source['previous_episode']!r}"
        )

    return {
        "episode": narration_source["episode"],
        "mode": narration_source["mode"],
        "motion_time_sha256": shot_source["motion_time_sha256"],
        "narration_plan_sha256": narration_digest,
        "narration_schema_version": narration["schema_version"],
        "previous_episode": narration_source["previous_episode"],
        "shot_plan_sha256": shot_digest,
        "shot_schema_version": shots["schema_version"],
    }


def _framing_claims(shots: dict[str, JsonValue]) -> dict[str, dict[str, JsonValue]]:
    """Return what the shot plan grants every beat it accounts for."""
    claims: dict[str, dict[str, JsonValue]] = {}
    for shot in cast(list[dict[str, JsonValue]], shots["shots"]):
        for beat_id in cast(list[str], shot["source_beat_ids"]):
            claims[beat_id] = {
                "end_frame": shot["end_frame"],
                "shot_id": shot["shot_id"],
                "start_frame": shot["start_frame"],
                "unshown_reason": None,
                "visibility": VISIBILITY_SHOWN,
            }
    for entry in cast(list[dict[str, JsonValue]], shots["unshown"]):
        claims[cast(str, entry["beat_id"])] = {
            "end_frame": None,
            "shot_id": None,
            "start_frame": None,
            "unshown_reason": entry["reason_code"],
            "visibility": VISIBILITY_UNSHOWN,
        }
    return claims


def _require_framing_agreement(
    narration: dict[str, JsonValue], shots: dict[str, JsonValue]
) -> None:
    """Verify every unit's copied framing is the framing the direction granted.

    Raises:
        ValueError: If a unit's visibility, citation, span or unshown reason
            disagrees with the shot plan, or if the two documents do not
            account for exactly the same beats.
    """
    claims = _framing_claims(shots)
    units = cast(list[dict[str, JsonValue]], narration["units"])
    if len(claims) != len(units):
        raise ValueError(
            f"the shot direction plan accounts for {len(claims)} beats but the narration "
            f"plan restates {len(units)}; the two documents do not describe one story"
        )
    for position, unit in enumerate(units):
        label = f"episode narration plan units[{position}]"
        beat_id = cast(str, unit["beat_id"])
        claim = claims.get(beat_id)
        if claim is None:
            raise ValueError(
                f"{label} restates beat {beat_id!r}, which the shot direction plan neither "
                "shows nor records as unshown; delivery schedules the direction it was "
                "given and never decides visibility for itself"
            )
        for field in FRAMING_FIELDS:
            if unit[field] != claim[field]:
                raise ValueError(
                    f"{label} declares {field} {unit[field]!r}, but the shot direction plan "
                    f"grants {claim[field]!r} for beat {beat_id!r}; what the viewer is shown "
                    "is Phase 22's decision, reported by Phase 24 and never re-made here"
                )


def resolve_delivery_slots(
    unit_segments: Sequence[tuple[int, int] | None],
    playback_first: int,
    playback_final: int,
    *,
    delivery_profile: str = "v1",
    unit_weights: Sequence[int] | None = None,
) -> list[tuple[int, int]]:
    """Return one inclusive playback slot per unit, under the chosen profile.

    Args:
        unit_segments: One entry per narration unit, in unit order: the citing
            shot's playback segment ``(first, last)`` for a SHOWN unit, or
            ``None`` for an UNSHOWN one. Two SHOWN units sharing a merged shot
            pass the same segment pair.
        playback_first: The first playback frame of the episode.
        playback_final: The final playback frame of the episode.
        delivery_profile: ``"v1"`` (the default) partitions every shared host
            interval equally; ``"v4"`` partitions it in proportion to each
            claimant's required frames (``unit_weights``).
        unit_weights: Under ``"v4"``, one strictly positive required-frames
            weight per unit, in unit order. Ignored under ``"v1"``.

    Returns:
        One ``(start_frame, end_frame)`` pair per unit, in unit order. Slots
        never overlap, never leave the playback domain, and never cross unit
        order.

    Raises:
        ValueError: If the profile is unreviewed, if ``unit_weights`` is
            missing or mis-sized under ``"v4"``, if a segment leaves the
            playback domain, if SHOWN segments regress against unit order, or
            if any host interval holds fewer frames than the units claiming it.
    """
    if delivery_profile not in ("v1", "v4"):
        raise ValueError(
            f"delivery profile {delivery_profile!r} is not reviewed; this build resolves "
            "'v1' (equal partition) and 'v4' (content-proportional partition) only"
        )
    total = len(unit_segments)
    if delivery_profile == "v4":
        if unit_weights is None:
            raise ValueError(
                "the v4 profile requires one required-frames weight per unit; none were offered"
            )
        if len(unit_weights) != total:
            raise ValueError(
                f"the v4 profile requires {total} required-frames weights, one per unit, "
                f"but received {len(unit_weights)}"
            )

    hosts: list[tuple[tuple[int, int], list[int]]] = []
    host_by_segment: dict[tuple[int, int], list[int]] = {}
    last_segment: tuple[int, int] | None = None

    def _unit(index: int) -> str:
        return UNIT_ID_FORM % (index + 1)

    def _claim_segment(segment: tuple[int, int], index: int) -> None:
        claimants = host_by_segment.get(segment)
        if claimants is None:
            claimants = []
            host_by_segment[segment] = claimants
            hosts.append((segment, claimants))
        claimants.append(index)

    index = 0
    while index < total:
        segment = unit_segments[index]
        if segment is not None:
            first, last = segment
            if last < first or first < playback_first or last > playback_final:
                raise ValueError(
                    f"{_unit(index)} is hosted by segment [{first}, {last}], which does not "
                    f"lie inside the playback domain [{playback_first}, {playback_final}]"
                )
            if last_segment is not None and segment != last_segment and first <= last_segment[1]:
                raise ValueError(
                    f"{_unit(index)} is hosted by segment [{first}, {last}], which overlaps "
                    f"or precedes the segment [{last_segment[0]}, {last_segment[1]}] already "
                    "reached; shots tile the timeline, narration order is timeline order, "
                    "and slots never cross either"
                )
            _claim_segment(segment, index)
            last_segment = segment
            index += 1
            continue

        run_start = index
        while index < total and unit_segments[index] is None:
            index += 1
        run = list(range(run_start, index))
        next_segment = unit_segments[index] if index < total else None

        free_first = last_segment[1] + 1 if last_segment is not None else playback_first
        free_last = next_segment[0] - 1 if next_segment is not None else playback_final
        if free_first <= free_last:
            hosts.append(((free_first, free_last), run))
        elif last_segment is not None:
            for unit_index in run:
                _claim_segment(last_segment, unit_index)
        elif next_segment is not None:
            for unit_index in run:
                _claim_segment(next_segment, unit_index)
        else:
            raise ValueError(
                f"{_unit(run_start)} has no shown neighbour and no free playback frames; "
                "an episode with playback time always offers at least one host interval"
            )

    slots: list[tuple[int, int] | None] = [None] * total
    for (first, last), claimants in hosts:
        try:
            if delivery_profile == "v4":
                claim_weights = cast(Sequence[int], unit_weights)
                pieces = partition_proportionally(
                    first, last, [claim_weights[unit_index] for unit_index in claimants]
                )
            else:
                pieces = partition_equally(first, last, len(claimants))
        except ValueError as error:
            named = ", ".join(_unit(unit_index) for unit_index in claimants)
            raise ValueError(f"cannot allocate delivery slots for {named}: {error}") from error
        for unit_index, piece in zip(claimants, pieces, strict=True):
            slots[unit_index] = piece

    resolved: list[tuple[int, int]] = []
    for unit_index, slot in enumerate(slots):
        if slot is None:
            raise ValueError(
                f"{_unit(unit_index)} received no delivery slot; the policy is total over "
                "every unit and a gap in it is a defect, not a schedule"
            )
        resolved.append(slot)
    return resolved


def build_episode_narration_delivery_plan_document(
    narration_plan: object, shot_plan: object, *, delivery_profile: str = "v1"
) -> dict[str, JsonValue]:
    """Return the Episode Narration Delivery Plan document for one directed episode.

    Args:
        narration_plan: The Episode Narration Plan V1 whose units are scheduled.
        shot_plan: The Shot Direction Plan V1 whose segments host them, and
            whose restated Phase 17 timeline is the clock every slot lives on.
        delivery_profile: ``"v1"`` (the default) reproduces today's plan byte
            for byte and declares the v1 policy; ``"v4"`` partitions every
            shared host interval in proportion to each unit's required frames
            and declares the v4 policy.

    Returns:
        A validated Episode Narration Delivery Plan V1 document.

    Raises:
        TypeError: If any input has the wrong shape.
        ValueError: If either input fails its own contract, if the two do not
            join, if any unit's framing disagrees with the direction, if the
            profile is unreviewed, or if the policy cannot cut a slot of at
            least one frame for every unit.
    """
    _require_delivery_profile(delivery_profile)
    narration = validate_episode_narration_plan(narration_plan)
    shots = validate_shot_direction_plan_v2(shot_plan)

    source = _require_join(narration, shots)
    _require_framing_agreement(narration, shots)

    timeline = dict(_document(shots["timeline"], "shot direction plan timeline"))
    playback_first, playback_final = playback_domain(
        cast(int, timeline["start_frame"]), cast(int, timeline["end_frame"])
    )

    segments: dict[str, tuple[int, int]] = {}
    for shot in cast(list[dict[str, JsonValue]], shots["shots"]):
        shot_id = cast(str, shot["shot_id"])
        first = cast(int, shot["start_frame"])
        last = min(cast(int, shot["end_frame"]), playback_final)
        if last >= first:
            segments[shot_id] = (first, last)

    units = cast(list[dict[str, JsonValue]], narration["units"])
    unit_segments: list[tuple[int, int] | None] = []
    for position, unit in enumerate(units):
        if unit["visibility"] != VISIBILITY_SHOWN:
            unit_segments.append(None)
            continue
        shot_id = cast(str, unit["shot_id"])
        segment = segments.get(shot_id)
        if segment is None:
            raise ValueError(
                f"episode narration plan units[{position}] is shown by shot {shot_id!r}, "
                "which offers no playback frame; a shot cannot host narration on the "
                "witness boundary alone"
            )
        unit_segments.append(segment)

    weights: list[int] | None = None
    if delivery_profile == "v4":
        weights = [
            required_frames_for_word_count(len(cast(str, unit["text"]).split())) for unit in units
        ]

    slots = resolve_delivery_slots(
        unit_segments,
        playback_first,
        playback_final,
        delivery_profile=delivery_profile,
        unit_weights=weights,
    )

    deliveries: list[JsonValue] = []
    anchored = 0
    for position, (unit, slot) in enumerate(zip(units, slots, strict=True), start=1):
        shown = unit["visibility"] == VISIBILITY_SHOWN
        if shown:
            anchored += 1
        deliveries.append(
            {
                "delivery_id": DELIVERY_ID_FORM % position,
                "end_frame": slot[1],
                "placement": PLACEMENT_SHOT_ANCHORED if shown else PLACEMENT_ALLOCATED_UNSHOWN,
                "start_frame": slot[0],
                "unit_id": unit["unit_id"],
            }
        )

    document: dict[str, JsonValue] = {
        "accounting": {
            "allocated_unshown": len(deliveries) - anchored,
            "deliveries_total": len(deliveries),
            "shot_anchored": anchored,
        },
        "deliveries": deliveries,
        "format": DELIVERY_PLAN_FORMAT,
        "policy": DELIVERY_POLICY_V4 if delivery_profile == "v4" else DELIVERY_POLICY_V1,
        "schema_version": DELIVERY_SCHEMA_VERSION,
        "source": source,
        "timeline": cast(JsonValue, timeline),
    }
    return validate_episode_narration_delivery_plan(document)


def build_episode_narration_delivery_plan_bytes(
    narration_plan: object, shot_plan: object, *, delivery_profile: str = "v1"
) -> bytes:
    """Return the canonical Episode Narration Delivery Plan bytes for the given sources.

    The returned bytes are the one canonical encoding of the plan: sorted keys,
    tight separators, no non-finite floats, and exactly one trailing newline.
    Under ``delivery_profile="v1"`` (the default) the bytes are identical to
    this function's historical output.
    """
    document = build_episode_narration_delivery_plan_document(
        narration_plan, shot_plan, delivery_profile=delivery_profile
    )
    return dumps_canonical(document, "narration delivery plan")
