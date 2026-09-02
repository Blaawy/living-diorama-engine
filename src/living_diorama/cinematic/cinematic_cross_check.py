"""Cross-validation of a Shot Direction Plan against the documents it names.

:func:`living_diorama.cinematic.cinematic_schema_v1.validate_shot_direction_plan`
proves everything a plan can prove about itself. What it cannot prove is that
the plan's claims are *true of its sources*: that the digest it carries names
the story plan actually offered, that every beat that story plan holds is
accounted for, that no beat was invented, and that the clock it restates is the
clock the named Motion & Time Spec actually resolves to. A plan whose SHA field
is syntactically a digest is not thereby source-verified.

This module closes that gap. Given the plan, the Episode Story Plan it claims to
direct, and the exact Motion & Time Spec bytes it claims to be cut against, it
verifies every binding and every per-beat agreement, and then seals the whole
question by re-deriving the plan from those sources: the Shot Direction Plan
contract is a deterministic single-output function of its inputs, so the one
valid plan for a given story and clock is the plan the planner derives. Anything
else is refused, named check by named check first so a failure says which claim
stopped being true.

V2 is an edit layer over the same V1 document: the optional ``camera_movement``
blocks are assigned by ``camera_movement_planner.plan_camera_movements`` from the
shot's own locked fields, so the V2 plan is as deterministic a function of its
sources as the V1 plan is. With ``camera_profile="v2"`` the same named checks
run (the envelope is validated by the V2 validator, which delegates a
movement-free plan to the unchanged V1 validator) and the re-derivation is the
same ``build -> plan_camera_movements -> validate_v2 -> dumps_canonical`` chain,
so every degree of freedom V1's re-derivation closes stays closed for V2.

``camera_grammar`` (default ``"v1"``) selects which movement-assignment lane
``plan_camera_movements`` uses under ``camera_profile="v2"``: ``"v1"`` is
today's table byte for byte, ``"v2"`` is the Director-revision context-first
lane, and ``"v4"`` is the elevated drone-camera lane (which re-binds the
street-level event anchors to elevated catalogue members via the additive
``BEAT_ANCHORS_V4`` table and never emits ``PUSH_IN``/``PULL_OUT``/``PAN``).
The default reproduces today's bytes exactly.
"""

from typing import cast

from living_diorama.cinematic.camera_direction_v4 import plan_camera_movements_v4
from living_diorama.cinematic.camera_direction_v5 import plan_camera_movements_v5
from living_diorama.cinematic.camera_movement_planner import plan_camera_movements
from living_diorama.cinematic.cinematic_schema_v1 import (
    JsonValue,
    validate_shot_direction_plan,
)
from living_diorama.cinematic.cinematic_schema_v2 import validate_shot_direction_plan_v2
from living_diorama.cinematic.cinematic_spec import (
    REASON_ADJACENT_SAME_ANCHOR_MERGED,
    REASON_TRANSITION_BUDGET_EXHAUSTED,
    SHOT_BEAT,
    UNSHOWN_BEAT_KINDS,
    anchor_for_beat,
)
from living_diorama.cinematic.shot_planner import (
    build_shot_direction_plan_bytes,
    build_shot_direction_plan_document,
    resolve_motion_time_binding,
)
from living_diorama.persistence.json_codec import dumps_canonical
from living_diorama.persistence.schema.state_hash import sha256_hex
from living_diorama.story import EMPHASIS_LEVELS, validate_episode_story_plan

CAMERA_GRAMMARS: tuple[str, ...] = ("v1", "v2", "v4", "v5")
"""The closed camera-grammar vocabulary this cross-check threads.

``"v1"`` (default) is today's role table byte for byte; ``"v2"`` is the
Director-revision context-first lane; ``"v4"`` is the elevated drone-camera
lane (additive anchor rebinding plus the permitted STATIC/REVEAL/TRACK set);
``"v5"`` is the absolutely-static drone lane: one locked pose for the whole
episode, so the camera never moves and the world supplies all the motion.
``camera_grammar`` is a different axis from ``camera_profile``: the latter
decides whether movement exists at all.
"""


def _strongest_emphasis(levels: list[str]) -> str:
    """Return the strongest of the given Phase 21 emphasis levels.

    ``EMPHASIS_LEVELS`` is declared strongest-first by Phase 21, so strength is
    position, not an opinion of this layer's.
    """
    return min(levels, key=EMPHASIS_LEVELS.index)


def build_shot_direction_plan_v2_bytes(
    story_plan: object, motion_time: object, *, camera_grammar: str = "v1"
) -> bytes:
    """Return the canonical V2 Shot Direction Plan bytes for the given inputs.

    V2 is an edit layer over the locked V1 document: build the V1 document with
    the unchanged planner call, assign the optional ``camera_movement`` blocks
    with ``plan_camera_movements`` (under the given ``camera_grammar`` lane;
    the ``"v4"`` lane uses the additive elevated-drone assignment instead),
    prove the result under the V2 validator, and serialize with
    ``dumps_canonical``. Every step is deterministic -- movement roles are
    assigned positionally from the shot's own locked fields -- so any verifier
    can re-derive these bytes from the same story plan and clock.
    """
    document = build_shot_direction_plan_document(story_plan, motion_time)
    if camera_grammar == "v4":
        v2_document = plan_camera_movements_v4(document)
    elif camera_grammar == "v5":
        v2_document = plan_camera_movements_v5(document)
    else:
        v2_document = plan_camera_movements(document, camera_grammar=camera_grammar)
    validate_shot_direction_plan_v2(v2_document)
    return dumps_canonical(v2_document, "shot direction plan")


def validate_shot_direction_plan_against_story(
    shot_plan: object,
    story_plan: object,
    motion_time: object,
    *,
    camera_profile: str = "v1",
    camera_grammar: str = "v1",
) -> dict[str, JsonValue]:
    """Verify a Shot Direction Plan against its actual sources, and return it.

    Args:
        shot_plan: The Shot Direction Plan V1 (or, under ``camera_profile``
            ``"v2"``, V2) document to verify.
        story_plan: The Episode Story Plan V1 document the plan claims to
            direct.
        motion_time: The exact Motion & Time Spec bytes the plan claims to be
            cut against.
        camera_profile: ``"v1"`` (default) verifies under the V1 contract and
            re-derives V1 bytes. ``"v2"`` verifies under the V2 contract and
            re-derives V2 bytes through the same deterministic chain the CLI
            uses.
        camera_grammar: which movement-assignment lane the V2 re-derivation
            uses when ``camera_profile="v2"`` -- ``"v1"`` (default) reproduces
            today's bytes exactly, ``"v2"`` selects the Director-revision
            context-first lane, and ``"v4"`` selects the elevated drone-camera
            lane (whose policy re-check consults the additive ``BEAT_ANCHORS_V4``
            table instead of the frozen V1 one). Ignored under
            ``camera_profile="v1"``, which has no movement at all.

    The named checks, in order:

    * both documents validate under their own contracts
    * the plan's ``story_plan_sha256`` is the digest of this story plan's
      canonical bytes, and the schema version, mode, episode and previous
      episode agree with it
    * the plan's motion binding names exactly these Motion & Time Spec bytes,
      and the restated timeline equals the clock those bytes resolve to
    * every story beat is accounted for exactly once -- shown by exactly one
      shot or listed exactly once as unshown -- with no invented and no omitted
      beat id
    * every shown beat agrees with the closed direction policy: its kind's
      anchor is the shot's anchor (under the grammar lane the cross-check is
      running, so a V4 plan is checked against the V4 elevated table, never
      refused for "wrong anchor"), the shot's reason code matches the actual
      derivation case, and the shot's emphasis is the strongest Phase 21
      emphasis among the beats it shows -- copied, never recomputed
    * the empty-result beat is never framed and is unshown only as
      ``NOTHING_TO_EMPHASIZE``; every other unshown beat is
      ``TRANSITION_BUDGET_EXHAUSTED`` only
    * shots cite beats in Phase 21 rank order

    Finally the plan is re-derived from the two sources and must equal it byte
    for byte, which closes every remaining degree of freedom -- durations,
    ordering, merging, tiling and (under V2) movement assignment included.

    Returns:
        The verified shot plan.

    Raises:
        TypeError: If any input has the wrong Python type.
        ValueError: If any binding, accounting, policy or derivation check
            fails, or if ``camera_profile`` is not ``"v1"`` or ``"v2"``, or if
            ``camera_grammar`` is not ``"v1"``, ``"v2"`` or ``"v4"``.
    """
    if camera_profile not in ("v1", "v2"):
        raise ValueError(f"unknown camera profile {camera_profile!r}; expected 'v1' or 'v2'")
    if camera_grammar not in CAMERA_GRAMMARS:
        raise ValueError(
            f"unknown camera grammar {camera_grammar!r}; expected 'v1', 'v2', 'v4' or 'v5'"
        )
    if camera_profile == "v2":
        plan = validate_shot_direction_plan_v2(shot_plan)
    else:
        plan = validate_shot_direction_plan(shot_plan)
    story = validate_episode_story_plan(story_plan)

    source = cast(dict[str, JsonValue], plan["source"])
    story_digest = sha256_hex(dumps_canonical(story, "episode story plan"))
    if source["story_plan_sha256"] != story_digest:
        raise ValueError(
            f"shot direction plan binds story plan {source['story_plan_sha256']!r}, but the "
            f"offered story plan's canonical bytes hash to {story_digest!r}; this plan does "
            "not direct that story"
        )
    if source["story_schema_version"] != story["schema_version"]:
        raise ValueError(
            f"shot direction plan records story schema version "
            f"{source['story_schema_version']}, but the story plan declares "
            f"{story['schema_version']}"
        )
    story_source = cast(dict[str, JsonValue], story["source"])
    if source["mode"] != story_source["mode"]:
        raise ValueError(
            f"shot direction plan is {source['mode']!r} mode but the story plan is "
            f"{story_source['mode']!r} mode"
        )
    story_current = cast(dict[str, JsonValue], story_source["current"])
    if source["episode"] != story_current["episode"]:
        raise ValueError(
            f"shot direction plan describes episode {source['episode']} but the story plan "
            f"describes episode {story_current['episode']}"
        )
    if story_source["mode"] == "baseline":
        if source["previous_episode"] is not None:
            raise ValueError(
                "shot direction plan names a previous episode but the story plan is a baseline"
            )
    else:
        story_previous = cast(dict[str, JsonValue], story_source["previous"])
        if source["previous_episode"] != story_previous["episode"]:
            raise ValueError(
                f"shot direction plan names previous episode {source['previous_episode']} but "
                f"the story plan transitions from episode {story_previous['episode']}"
            )

    binding = resolve_motion_time_binding(motion_time)
    if source["motion_time_sha256"] != binding["motion_time_sha256"]:
        raise ValueError(
            f"shot direction plan was cut against motion time spec "
            f"{source['motion_time_sha256']!r}, but the offered bytes hash to "
            f"{binding['motion_time_sha256']!r}; this plan was not cut against that clock"
        )
    if plan["timeline"] != binding["timeline"]:
        raise ValueError(
            f"shot direction plan restates timeline {plan['timeline']!r}, but the bound "
            f"motion time spec resolves to {binding['timeline']!r}"
        )

    beats_by_id: dict[str, dict[str, JsonValue]] = {
        cast(str, beat["beat_id"]): beat
        for beat in cast(list[dict[str, JsonValue]], story["beats"])
    }
    shots = cast(list[dict[str, JsonValue]], plan["shots"])
    unshown = cast(list[dict[str, JsonValue]], plan["unshown"])

    accounted: set[str] = set()
    for position, shot in enumerate(shots):
        cited = cast(list[str], shot["source_beat_ids"])
        for beat_id in cited:
            if beat_id not in beats_by_id:
                raise ValueError(
                    f"shot direction plan shots[{position}] cites beat {beat_id!r}, which "
                    "the story plan does not hold; no beat is ever invented"
                )
            accounted.add(beat_id)
        if not cited:
            continue

        kinds = [cast(str, beats_by_id[beat_id]["kind"]) for beat_id in cited]
        for beat_id, kind in zip(cited, kinds, strict=True):
            if kind in UNSHOWN_BEAT_KINDS:
                raise ValueError(
                    f"shot direction plan shots[{position}] frames {kind} beat "
                    f"{beat_id!r}, which this layer's policy deliberately leaves "
                    "unshown; framing it would fabricate visibility"
                )
            expected_anchor, _expected_reason = anchor_for_beat(kind, camera_grammar=camera_grammar)
            if shot["camera_anchor_id"] != expected_anchor:
                raise ValueError(
                    f"shot direction plan shots[{position}] shows {kind} beat {beat_id!r} "
                    f"on {shot['camera_anchor_id']!r}, but the direction policy frames "
                    f"that kind on {expected_anchor!r}"
                )
        if len(cited) == 1:
            _expected_anchor, expected_reason = anchor_for_beat(
                kinds[0], camera_grammar=camera_grammar
            )
            if shot["reason_code"] != expected_reason:
                raise ValueError(
                    f"shot direction plan shots[{position}] shows one {kinds[0]} beat but "
                    f"carries reason {shot['reason_code']!r}; that derivation case is "
                    f"{expected_reason!r}"
                )
        elif shot["reason_code"] != REASON_ADJACENT_SAME_ANCHOR_MERGED:
            raise ValueError(
                f"shot direction plan shots[{position}] shows {len(cited)} beats but "
                f"carries reason {shot['reason_code']!r}; several beats share a shot only "
                "through an adjacent-anchor merge"
            )
        emphases = [cast(str, beats_by_id[beat_id]["emphasis"]) for beat_id in cited]
        strongest = _strongest_emphasis(emphases)
        if shot["emphasis"] != strongest:
            raise ValueError(
                f"shot direction plan shots[{position}] declares emphasis "
                f"{shot['emphasis']!r}, but the strongest Phase 21 emphasis among its "
                f"beats is {strongest!r}; emphasis is copied, never recomputed"
            )

    for position, entry in enumerate(unshown):
        beat_id = cast(str, entry["beat_id"])
        beat = beats_by_id.get(beat_id)
        if beat is None:
            raise ValueError(
                f"shot direction plan unshown[{position}] lists beat {beat_id!r}, which "
                "the story plan does not hold; no beat is ever invented"
            )
        accounted.add(beat_id)
        reason = entry["reason_code"]
        required = UNSHOWN_BEAT_KINDS.get(
            cast(str, beat["kind"]), REASON_TRANSITION_BUDGET_EXHAUSTED
        )
        if reason != required:
            raise ValueError(
                f"shot direction plan unshown[{position}] leaves {beat['kind']} beat "
                f"{beat_id!r} unshown as {reason!r}; that kind goes unshown "
                f"only as {required!r}"
            )

    missing = sorted(set(beats_by_id) - accounted)
    if missing:
        raise ValueError(
            f"shot direction plan leaves story beats {missing} unaccounted for; every "
            "beat is shown exactly once or recorded as unshown"
        )

    ranks: list[int] = []
    for shot in shots:
        if shot["kind"] != SHOT_BEAT:
            continue
        ranks.extend(
            cast(int, beats_by_id[beat_id]["rank"])
            for beat_id in cast(list[str], shot["source_beat_ids"])
        )
    if ranks != sorted(ranks):
        raise ValueError(
            f"shot direction plan cites beats in rank order {ranks}; shot order is "
            "Phase 21's rank order, and this layer never reorders history"
        )

    # The contract is a deterministic single-output function of its sources, so
    # the one valid plan for this story and clock is the one the planner derives.
    # Byte equality closes every degree of freedom the named checks above leave
    # open: durations, allocation, merging, ordering, tiling and (under V2)
    # movement assignment.
    if camera_profile == "v2":
        derived = build_shot_direction_plan_v2_bytes(
            story, motion_time, camera_grammar=camera_grammar
        )
    else:
        derived = build_shot_direction_plan_bytes(story, motion_time)
    offered = dumps_canonical(plan, "shot direction plan")
    if offered != derived:
        raise ValueError(
            "shot direction plan does not equal the deterministic derivation from the "
            "story plan and motion time spec it binds; a plan is source-verified only "
            "when it is the plan those sources produce"
        )

    return plan
