"""Contract tests for the pure State Response Motion Plan V1 derivation.

Pure pytest -- no Blender, no generated artefact: every export here is built
in-test from the canonical Master Scene Spec's own district list, so the suite
proves the TRANSITION RULES rather than one recorded pair of episodes.

The rule this file exists to defend is the phase's central promise:

    A DIRECTIVE MAY EXIST ONLY BECAUSE THE TWO STATES GENUINELY DIFFER.

That promise is only worth something if both halves are pinned. So the file is
built as a pair of arms that hold each other honest: a planner that always
returned no directives would sail through the unchanged-state test and die on
the one-changed-scalar test, and a planner that emitted a directive per response
would do the reverse. Neither test is evidence without the other.

Everything else here follows from the same idea. A transition between two
documents that describe different worlds is refused rather than eased over; a
world that forgot a durable fact is refused because memory only grows; two
directives may never drive one property; the keys a directive writes land
EXACTLY on the two static applications it claims to join; and the same two plans
always produce the same bytes, whatever order their arrays happened to arrive in.
"""

import copy
import importlib
import random
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "visual" / "blender" / "scripts"
CONFIG_DIR = REPO_ROOT / "visual" / "blender" / "config"


def _load(name: str):
    """Import one pure visual module the same way Blender does: by sibling name."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(SCRIPTS_DIR))


srmp = _load("state_response_motion_plan")
srp = _load("state_response_plan")
srs = _load("state_response_spec")
ss = _load("scene_spec")
mts = _load("motion_time_spec")

MASTER = ss.load_master_scene_spec(CONFIG_DIR / "master_scene_v1.json")
SPEC = srs.load_state_response_spec(CONFIG_DIR / "state_response_v1.json")
TIMELINE = srs.resolve_state_response_timeline(
    SPEC, mts.load_motion_time_spec(CONFIG_DIR / "motion_time_v1.json")["timeline"]
)
"""The real Phase 17 clock, borrowed exactly as the runtime borrows it.

A synthetic timeline would prove the arithmetic and nothing about the two phases
agreeing; this is the same resolved object Phase 17's own planner is handed.
"""

DISTRICT_IDS = tuple(sorted(MASTER["districts"]))

DECLARED_CHANNELS = ("district_air", "memory_record")
"""Phase 20's channels, restated here rather than read from the spec.

The unchanged-state test asserts that EVERY channel is named as unchanged. Taken
from the spec the planner also reads, that assertion would hold just as well if
both documents were empty; written out, it is a second independent statement
that the two channels exist and that both must report themselves silent.
"""

BASELINE_SCARCITY = {
    "district_a": 0.0,
    "district_b": 0.25,
    "district_c": 0.6,
    "district_d": 1.0,
}
"""Four distinct readings, so a planner emitting one constant cannot pass."""


def district(district_id: str, **overrides: object) -> dict:
    """One export district entry carrying every key the export format declares."""
    entry = {
        "id": district_id,
        "created_tick": 0,
        "population": 100,
        "housing_capacity": 400,
        "production_rate": 10.0,
        "consumption_rate": 0.1,
        "scarcity": BASELINE_SCARCITY[district_id],
        "fear": 0.1,
        "trust": 0.85,
        "institutional_pressure": 0.15,
        "isolation_state": "OPEN",
        "resources": {"FOOD": 60.0, "MATERIALS": 60.0, "ENERGY": 60.0},
    }
    entry.update(overrides)
    return entry


def fact(fact_id: str) -> dict:
    """One durable memory fact, carrying the structured members Phase 20 reads."""
    return {"episode": 1, "fact_id": fact_id, "fact_type": "WALL_BUILT", "tick": 9}


def export(
    *,
    scarcity: dict[str, float] | None = None,
    facts: tuple[str, ...] = ("fact_alpha", "fact_beta"),
    ids: tuple[str, ...] = DISTRICT_IDS,
    episode: int = 0,
) -> dict:
    """A Render Export V1 document agreeing with the canonical master scene."""
    scarcity = scarcity or {}
    districts = []
    for district_id in ids:
        entry = district(district_id)
        if district_id in scarcity:
            entry["scarcity"] = scarcity[district_id]
        districts.append(entry)
    return {
        "format": "living_diorama_render_export",
        "schema_version": 1,
        "source": {
            "engine_version": "0.0.1",
            "episode": episode,
            "tick": episode * 10,
            "state_hash": f"{episode:064d}",
            "parent_state_hash": None,
            "event_count": 0,
            "entity_counts": {
                "districts": len(ids),
                "boundaries": 0,
                "walls": 0,
                "laws": 0,
                "infrastructure": 0,
            },
        },
        "world": {
            "districts": districts,
            "boundaries": [],
            "walls": [],
            "laws": [],
            "infrastructure": [],
        },
        "events": [],
        "memory": {
            "through_episode": episode,
            "through_tick": episode * 10,
            "facts": [fact(fact_id) for fact_id in facts],
        },
    }


def plan_for(document: dict) -> dict:
    """Derive one state response plan from one export."""
    return srp.plan_state_response(document, MASTER, SPEC)


def motion(before: dict, after: dict, timeline: dict | None = None) -> dict:
    """Derive one transition plan between two state response plans."""
    return srmp.plan_state_response_motion(before, after, SPEC, timeline or TIMELINE)


def refuses(before: dict, after: dict, fragment: str, timeline: dict | None = None) -> str:
    """Assert planning refuses this pair for the stated reason, and return why."""
    with pytest.raises(srmp.StateResponseMotionError) as error:
        motion(before, after, timeline)
    message = str(error.value)
    assert fragment in message, message
    return message


def air_response(semantic_id: str, value: float, *, target: dict | None = None) -> dict:
    """One synthetic district-air response, carrying only what the differ reads."""
    return {
        "channel": "district_air",
        "semantic_id": semantic_id,
        "source_path": f"world.districts[{semantic_id}].scarcity",
        "source_value": value,
        "value": value,
        "target": target
        or {
            "kind": "material_node_value",
            "material": f"{srp.AIR_MATERIAL_PREFIX}{semantic_id}",
            "node": srp.AIR_DENSITY_NODE,
            "socket": srp.AIR_DENSITY_SOCKET,
        },
    }


def record_response(fact_id: str, slot: int) -> dict:
    """One synthetic memory-record response, carrying only what the differ reads."""
    return {
        "channel": "memory_record",
        "semantic_id": fact_id,
        "source_path": f"memory.facts[{fact_id}].fact_type",
        "source_value": "WALL_BUILT",
        "value": 1.0,
        "target": {"kind": "object_presence", "object": f"{srp.RECORD_OBJECT_PREFIX}{slot:03d}"},
    }


def synthetic_plan(responses: list[dict], **overrides: object) -> dict:
    """A state response plan shaped exactly as the differ requires, and no more.

    Hand-built rather than derived, because several refusals below describe pairs
    of documents the derivation can never produce -- two districts sharing one
    material, a world that forgot a fact -- and a refusal that only fires on
    inputs nobody can construct is a refusal nobody has tested.
    """
    plan = {
        "format": srp.STATE_RESPONSE_PLAN_FORMAT,
        "source": {"episode": 0, "state_hash": "0" * 64, "tick": 0},
        "responses": responses,
    }
    plan.update(overrides)
    return plan


def directive(**overrides: object) -> dict:
    """One transition directive, as ``keyframes`` sees it."""
    entry = {
        "channel": "district_air",
        "semantic_id": "district_a",
        "target": {"kind": "material_node_value"},
        "interpolation": "linear",
        "samples": 5,
        "start_frame": 0,
        "end_frame": 100,
        "from_value": 0.0,
        "to_value": 1.0,
        "source_before": "world.districts[district_a].scarcity=0.0",
        "source_after": "world.districts[district_a].scarcity=1.0",
    }
    entry.update(overrides)
    return entry


CHANGED_SCARCITY = {"district_b": 0.75}
"""One district's reading moved, and only that district's.

``district_b`` reads 0.25 in the baseline, so this is a real move rather than a
rewrite of the same number.
"""


# ---------------------------------------------------------------------------
# The control arm
# ---------------------------------------------------------------------------


def test_the_baseline_pair_of_plans_is_one_the_planner_accepts() -> None:
    """A module that refused everything would pass every refusal test below.

    Every refusal in this file is a mutation of a pair the planner accepts, so
    each of them is only evidence in the presence of this: the unmutated pair
    plans, produces real directives, and audits clean.
    """
    before = plan_for(export())
    after = plan_for(export(scarcity=CHANGED_SCARCITY, facts=("fact_alpha", "fact_beta", "fact_c")))
    plan = motion(before, after)
    assert plan["format"] == srmp.STATE_RESPONSE_MOTION_FORMAT
    assert plan["schema_version"] == srmp.STATE_RESPONSE_MOTION_SCHEMA_VERSION
    assert plan["directives"], "the baseline pair must produce real directives"
    assert plan["source_before"] == before["source"]
    assert plan["source_after"] == after["source"]
    assert plan["timeline"]["transition_start"] == TIMELINE["transition_start"]
    assert srmp.validate_state_response_motion_plan(plan) == []


# ---------------------------------------------------------------------------
# The central promise
# ---------------------------------------------------------------------------


def test_two_identical_states_produce_no_directive_at_all() -> None:
    """Unchanged state produces no motion. This is the phase's whole claim.

    The two plans are derived from two separately built exports carrying the
    same readings, so a planner that compared object identity rather than value
    would emit a directive for every response and fail here.

    Read alone this test would pass a planner that never emitted anything, which
    is why the plans are first asserted to be full of responses and why
    :func:`test_one_changed_district_scalar_produces_exactly_one_directive`
    exists. Together they leave no room for a constant.
    """
    before = plan_for(export())
    after = plan_for(export())
    assert len(before["responses"]) == len(DISTRICT_IDS) + 2
    assert srp.plan_hash(before) == srp.plan_hash(after)

    plan = motion(before, after)
    assert plan["directives"] == []
    assert plan["summary"]["directives"] == 0
    assert plan["summary"]["directives_by_channel"] == {}
    assert plan["summary"]["unchanged_channels"] == sorted(DECLARED_CHANNELS)
    assert srmp.validate_state_response_motion_plan(plan) == []


def test_one_changed_district_scalar_produces_exactly_one_directive() -> None:
    """One field moved, so exactly one district's air moves and nothing else.

    The directive must also be traceable: both provenance strings carry the
    dotted path into the export and the raw reading found there. A planner that
    emitted a directive per district, or one that could not say which reading
    produced it, fails here -- and an unfalsifiable directive is decoration.
    """
    before = plan_for(export())
    after = plan_for(export(scarcity=CHANGED_SCARCITY))
    plan = motion(before, after)

    assert len(plan["directives"]) == 1
    moved = plan["directives"][0]
    assert moved["channel"] == "district_air"
    assert moved["semantic_id"] == "district_b"
    assert moved["source_before"] == "world.districts[district_b].scarcity=0.25"
    assert moved["source_after"] == "world.districts[district_b].scarcity=0.75"

    readings = {
        response["semantic_id"]: response["value"]
        for response in before["responses"]
        if response["channel"] == "district_air"
    }
    assert moved["from_value"] == readings["district_b"]
    assert moved["from_value"] != moved["to_value"]
    assert plan["summary"]["directives_by_channel"] == {"district_air": 1}
    assert plan["summary"]["unchanged_channels"] == ["memory_record"]
    assert srmp.validate_state_response_motion_plan(plan) == []


def test_one_new_memory_fact_produces_exactly_one_presence_directive() -> None:
    """A fact the world newly remembers appears; the ones it already held do not.

    A planner that re-keyed every remembered fact on every transition would
    animate the whole arc into existence again each episode, and would fail the
    count here.
    """
    before = plan_for(export(facts=("fact_alpha",)))
    after = plan_for(export(facts=("fact_alpha", "fact_beta")))
    plan = motion(before, after)

    assert len(plan["directives"]) == 1
    appeared = plan["directives"][0]
    assert appeared["channel"] == "memory_record"
    assert appeared["semantic_id"] == "fact_beta"
    assert appeared["from_value"] == srmp.PRESENCE_ABSENT
    assert appeared["to_value"] == srmp.PRESENCE_PRESENT
    assert appeared["source_before"] == "memory.facts: absent"
    assert "fact_beta" in appeared["source_after"]
    assert plan["summary"]["unchanged_channels"] == ["district_air"]


# ---------------------------------------------------------------------------
# Order and targets
# ---------------------------------------------------------------------------


def test_the_directive_order_does_not_come_from_the_arrays_order() -> None:
    """Identity is indexed, never taken from the order responses arrived in.

    Both input arrays are shuffled independently with different seeds, so a
    planner that zipped the two arrays positionally would pair the wrong
    districts and produce different directives -- or none at all.
    """
    before = plan_for(export())
    after = plan_for(export(scarcity={"district_a": 0.4, "district_c": 0.9}))
    straight = motion(before, after)

    shuffled_before = copy.deepcopy(before)
    shuffled_after = copy.deepcopy(after)
    random.Random(20).shuffle(shuffled_before["responses"])
    random.Random(21).shuffle(shuffled_after["responses"])
    assert shuffled_before["responses"] != before["responses"]
    jumbled = motion(shuffled_before, shuffled_after)

    assert jumbled["directives"] == straight["directives"]
    assert srmp.plan_hash(jumbled) == srmp.plan_hash(straight)
    assert len(straight["directives"]) == 2
    assert [(entry["channel"], entry["semantic_id"]) for entry in straight["directives"]] == sorted(
        (entry["channel"], entry["semantic_id"]) for entry in straight["directives"]
    )


def test_two_directives_can_never_drive_one_target() -> None:
    """One property cannot carry two transitions, whoever asked for them.

    Two districts pointed at one material is a pair the derivation cannot build,
    which is exactly why it is built by hand: a refusal that only fires on inputs
    nobody can construct is a refusal nobody has tested. Without it the second
    directive would silently overwrite the first at apply time and the scene
    would show one district's condition on both.
    """
    shared = {"kind": "material_node_value", "material": "LD_SR_MAT__air_shared"}
    before = synthetic_plan(
        [
            air_response("district_a", 1.0, target=shared),
            air_response("district_b", 1.0, target=shared),
        ]
    )
    after = synthetic_plan(
        [
            air_response("district_a", 2.0, target=shared),
            air_response("district_b", 3.0, target=shared),
        ]
    )
    message = refuses(before, after, "one property cannot carry two transitions")
    assert "district_a" in message and "district_b" in message


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_two_plans_describing_different_districts_are_refused() -> None:
    """A transition between two different worlds is not a transition.

    A planner that took the intersection would produce a plausible, sorted,
    hashable plan of a world that never existed.
    """
    before = synthetic_plan([air_response("district_a", 1.0), air_response("district_b", 1.0)])
    after = synthetic_plan([air_response("district_a", 2.0)])
    message = refuses(before, after, "different districts")
    assert "district_b" in message


def test_a_district_whose_target_changed_is_refused() -> None:
    """One district's air is one property, not two.

    The check fires on the target alone, before the values are compared, so a
    plan that moved a district onto a different material while its reading held
    still is refused rather than passed over as unchanged.
    """
    before = synthetic_plan([air_response("district_a", 1.0)])
    after = synthetic_plan(
        [air_response("district_a", 1.0, target={"kind": "material_node_value", "material": "x"})]
    )
    refuses(before, after, "changes target between the two plans")


def test_a_world_that_forgot_a_memory_fact_is_refused() -> None:
    """Durable memory only grows, so a fact that vanished breaks the pair.

    A planner that treated the disappearance as a stone fading out would be
    animating the world forgetting something, which the engine cannot do; the
    honest conclusion is that these two documents are not consecutive states of
    one world.
    """
    before = synthetic_plan([record_response("fact_alpha", 0), record_response("fact_beta", 1)])
    after = synthetic_plan([record_response("fact_alpha", 0)])
    message = refuses(before, after, "no longer remembers")
    assert "fact_beta" in message


def test_a_directive_window_that_does_not_run_forwards_is_refused() -> None:
    """A directive must run forwards, whatever the clock it was handed.

    A transition one frame long leaves a staged member no room, so its window
    collapses onto a single frame. A planner that shrugged and wrote both keys
    on that frame would produce a curve whose two endpoints are the same
    instant, and the endpoint proof would then be comparing a frame with itself.
    """
    one_frame_long = {
        "fps": 24,
        "start_frame": 1,
        "transition_start": 10,
        "transition_end": 11,
        "end_frame": 20,
    }
    cramped = srs.resolve_state_response_timeline(SPEC, one_frame_long)
    before = plan_for(export(facts=()))
    after = plan_for(export(facts=("fact_alpha", "fact_beta")))
    refuses(before, after, "a directive must run forwards", cramped)


@pytest.mark.parametrize("position", ["before", "after"])
@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        (lambda plan: [], "must be a JSON object"),
        (lambda plan: {**plan, "format": "living_diorama_something_else"}, "format must be"),
        (lambda plan: {**plan, "responses": {}}, "must carry a responses array"),
    ],
)
def test_a_malformed_plan_is_refused(position: str, mutation, fragment: str) -> None:
    """A document that is not a state response plan is refused, not interpreted.

    Both positions are mutated in turn because a planner that validated only the
    first argument would pass a suite that only ever corrupted the first, and
    would then read an arbitrary document as the world's later state.
    """
    good = synthetic_plan([air_response("district_a", 1.0)])
    broken = mutation(synthetic_plan([air_response("district_a", 2.0)]))
    pair = (broken, good) if position == "before" else (good, broken)
    message = refuses(pair[0], pair[1], fragment)
    assert f"the {position} plan" in message


# ---------------------------------------------------------------------------
# Keyframes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("interpolation", ["linear", "smoothstep", "step"])
@pytest.mark.parametrize("samples", [1, 2, 5, 8, 64])
def test_every_curve_begins_and_ends_exactly_on_its_own_endpoints(
    interpolation: str, samples: int
) -> None:
    """Frame one is the before-state and the last frame is the after-state.

    Exactly, not nearly: those two frames are the whole reason a Phase 20
    animation can be proved rather than admired, because each is compared
    against an independent static application of its own export. A sampler that
    rounded its first or last position onto a neighbouring frame, or eased its
    endpoint by a millionth, would break the proof and is caught here.
    """
    entry = directive(interpolation=interpolation, samples=samples, from_value=1.1, to_value=4.7)
    keys = srmp.keyframes(entry)
    assert keys[0] == (entry["start_frame"], entry["from_value"])
    assert keys[-1] == (entry["end_frame"], entry["to_value"])
    frames = [frame for frame, _ in keys]
    assert frames == sorted(frames)
    assert len(set(frames)) == len(frames), f"two keys share a frame: {frames}"


def test_a_step_directive_writes_exactly_two_keys() -> None:
    """A value that holds and then swaps has nothing to sample in between.

    The sample count is deliberately absurd: a sampler that honoured it for a
    step channel would write sixty-four keys along a curve that has exactly two
    states, and a record stone would be caught half-remembered between them.
    """
    keys = srmp.keyframes(directive(interpolation="step", samples=64))
    assert keys == [(0, 0.0), (100, 1.0)]


def test_a_sampled_curve_actually_moves_between_its_endpoints() -> None:
    """Endpoints alone would pass a sampler that wrote only two keys.

    So the interior is checked too: a linear channel samples its declared number
    of keys at even positions, and a smoothstep channel departs from the
    straight line it would otherwise be indistinguishable from.
    """
    linear = srmp.keyframes(directive(interpolation="linear", samples=5))
    assert linear == [(0, 0.0), (25, 0.25), (50, 0.5), (75, 0.75), (100, 1.0)]

    eased = srmp.keyframes(directive(interpolation="smoothstep", samples=5))
    assert [frame for frame, _ in eased] == [0, 25, 50, 75, 100]
    assert eased[1][1] < linear[1][1]
    assert eased[3][1] > linear[3][1]
    assert [value for _, value in eased] == sorted(value for _, value in eased)


def test_a_window_too_short_to_hold_its_samples_still_begins_on_its_before_value() -> None:
    """Two keys on one frame is an ambiguity, and the endpoint must survive it.

    Eight samples cannot fit in a two-frame window. The sampler answers by asking
    for no more keys than the window has distinct frames, rather than by
    collapsing keys after the fact: a collapse that ate the first key would leave
    frame one carrying an interpolated interior value instead of ``from_value``,
    and frame one is exactly what a static application of the before-export is
    compared against. Fewer keys is a coarser curve; a moved endpoint is a false
    frame, and a false frame breaks the only proof Phase 20 offers.

    This test was written against a real defect that did exactly that, so it must
    stay: it is the regression guard for the endpoint invariant itself.
    """
    keys = srmp.keyframes(directive(samples=8, start_frame=40, end_frame=42))
    assert keys[0] == (40, 0.0)
    assert keys[-1] == (42, 1.0)
    assert [frame for frame, _ in keys] == [40, 41, 42]


def test_every_directive_a_real_transition_produces_lands_on_its_endpoints() -> None:
    """The same exactness, on directives the planner actually built.

    The parametrized case above proves the sampler; this proves the sampler is
    fed by the planner in the shape it expects, over both channels at once.
    """
    before = plan_for(export(facts=("fact_alpha",)))
    after = plan_for(export(scarcity=CHANGED_SCARCITY, facts=("fact_alpha", "fact_beta")))
    plan = motion(before, after)
    assert {entry["channel"] for entry in plan["directives"]} == set(DECLARED_CHANNELS)
    for entry in plan["directives"]:
        keys = srmp.keyframes(entry)
        assert keys[0] == (entry["start_frame"], entry["from_value"])
        assert keys[-1] == (entry["end_frame"], entry["to_value"])
        assert len({frame for frame, _ in keys}) == len(keys)
        assert entry["start_frame"] >= TIMELINE["transition_start"]
        assert entry["end_frame"] <= TIMELINE["transition_end"]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_the_same_two_states_always_produce_the_same_bytes() -> None:
    """Same world, same film. Determinism is checked on the bytes, not the dict.

    Two dicts can compare equal and still serialize differently -- key order is
    the obvious way -- and it is the serialized form that gets hashed, published
    and compared against a later run.
    """
    before = plan_for(export())
    after = plan_for(export(scarcity=CHANGED_SCARCITY))
    first = motion(before, after)
    second = motion(copy.deepcopy(before), copy.deepcopy(after))
    assert srmp.canonical_plan_bytes(first) == srmp.canonical_plan_bytes(second)
    assert srmp.plan_hash(first) == srmp.plan_hash(second)
    assert srmp.canonical_plan_bytes(first).endswith(b"\n")


def test_a_changed_reading_changes_the_hash() -> None:
    """A hash that did not move when the world moved would prove nothing.

    Both exports carry the same episode and the same provenance block, so the
    only difference the hash can be reacting to is the reading itself.
    """
    before = plan_for(export())
    quiet = srmp.plan_hash(motion(before, plan_for(export(scarcity={"district_b": 0.75}))))
    louder = srmp.plan_hash(motion(before, plan_for(export(scarcity={"district_b": 0.76}))))
    assert quiet != louder


# ---------------------------------------------------------------------------
# The validator, shown to bite
# ---------------------------------------------------------------------------


def test_the_validator_reports_a_falsified_summary_count() -> None:
    """A plan that miscounts itself is caught by re-deriving the count.

    A validator that read the summary and believed it would return no problems
    here, which is precisely the failure mode a self-describing document has.
    """
    plan = motion(plan_for(export()), plan_for(export(scarcity=CHANGED_SCARCITY)))
    assert srmp.validate_state_response_motion_plan(plan) == []
    plan["summary"]["directives"] = 99
    problems = srmp.validate_state_response_motion_plan(plan)
    assert any("summary claims 99 directives" in problem for problem in problems), problems


def test_the_validator_reports_a_falsified_per_channel_count() -> None:
    """The per-channel breakdown is re-derived from the body as well.

    A summary can be wrong in one field and right in the other, so both are
    rebuilt; a validator that checked only the total would pass this.
    """
    plan = motion(plan_for(export()), plan_for(export(scarcity=CHANGED_SCARCITY)))
    plan["summary"]["directives_by_channel"] = {"memory_record": 1}
    problems = srmp.validate_state_response_motion_plan(plan)
    assert any("per channel" in problem for problem in problems), problems
    assert not any("summary claims 1 directives" in problem for problem in problems), problems


def test_the_validator_reports_a_directive_that_left_the_transition() -> None:
    """An endpoint outside the transition is an endpoint nothing can prove.

    The last frame of a Phase 20 directive is compared against the static
    application of the after-export. A directive that ran past the transition
    would be sampled where no such comparison happens, and the proof would be
    quietly measuring a frame the film never uses.
    """
    plan = motion(plan_for(export()), plan_for(export(scarcity=CHANGED_SCARCITY)))
    moved = plan["directives"][0]
    moved["end_frame"] = plan["timeline"]["transition_end"] + 5
    problems = srmp.validate_state_response_motion_plan(plan)
    assert any("ends after the transition does" in problem for problem in problems), problems
    assert moved["semantic_id"] in problems[0]


def test_the_validator_reports_a_directive_that_carries_no_transition() -> None:
    """A directive whose two ends read alike is motion for its own sake.

    The planner refuses to build one; this proves the published document is
    re-checked rather than trusted, so a plan that acquired one between
    derivation and delivery cannot be applied as though it had been earned.
    """
    plan = motion(plan_for(export()), plan_for(export(scarcity=CHANGED_SCARCITY)))
    moved = plan["directives"][0]
    moved["to_value"] = moved["from_value"]
    problems = srmp.validate_state_response_motion_plan(plan)
    assert any("carries no transition" in problem for problem in problems), problems


def test_the_validator_reports_a_directive_with_no_provenance() -> None:
    """A directive that cannot say what it read is not falsifiable.

    Both provenance fields are checked, because a validator that looked at one
    would accept a plan whose every directive could name its after-state and
    none of them its before-state.
    """
    for field in ("source_before", "source_after"):
        plan = motion(plan_for(export()), plan_for(export(scarcity=CHANGED_SCARCITY)))
        plan["directives"][0][field] = "   "
        problems = srmp.validate_state_response_motion_plan(plan)
        assert any(f"carries no {field}" in problem for problem in problems), problems


def test_the_validator_reports_directives_out_of_their_own_total_order() -> None:
    """The order is a claim the document makes and the validator re-derives it.

    A reader who trusted the published order would apply the plan in whatever
    order it arrived in, so an order nobody re-checks is an order nobody has.
    """
    before = plan_for(export(facts=("fact_alpha",)))
    after = plan_for(export(scarcity=CHANGED_SCARCITY, facts=("fact_alpha", "fact_beta")))
    plan = motion(before, after)
    assert len(plan["directives"]) == 2
    plan["directives"].reverse()
    problems = srmp.validate_state_response_motion_plan(plan)
    assert any("total order" in problem for problem in problems), problems


def test_the_validator_refuses_a_document_that_is_not_a_motion_plan() -> None:
    """A wrong format and a missing body are reported, not raised past.

    The validator returns problems rather than throwing, so a caller can print
    every fault at once; a validator that crashed on the first malformed field
    would tell a reader one thing at a time about a document that is wrong in
    several ways.
    """
    problems = srmp.validate_state_response_motion_plan({"format": "nope", "directives": "many"})
    assert any("format must be" in problem for problem in problems), problems
    assert any("directives must be a JSON array" in problem for problem in problems), problems
