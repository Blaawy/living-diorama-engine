"""Proof that episodes have stable, content-derived names; that their event log
is typed and append-only; and that a lineage cannot be reordered, gapped,
re-parented or forged.

The centrepiece is the ADVERSARIAL section at the bottom: every attack named in
the Phase 3 lane-1 brief must fail.
"""

from __future__ import annotations

import copy
import hashlib

import pytest

from ldyf.episode import (
    EVENT_KINDS,
    EpisodeError,
    SCHEMA_VERSION,
    _id_from_bytes,
    append_event,
    episode_inputs_digest,
    make_agent_id,
    make_episode_id,
    make_event_id,
    make_world_id,
    new_episode_manifest,
    new_event_log,
    verify_episode_lineage,
    verify_outputs,
)
from ldyf.world_state import ChainError, canonical_bytes, seal, verify

WORLD = make_world_id("riverside")
NET = "1" * 64
ROUTES = ["a" * 64, "b" * 64]
RULES = ["close_edge_A1B1", "open_edge_C1D1"]


def manifest(**over):
    kw = dict(
        world_id=WORLD,
        episode_number=0,
        parent_episode_id=None,
        net_sha256=NET,
        route_sha256=list(ROUTES),
        seed=20260903,
        end_seconds=240.0,
        step_length=0.1,
        rule_ids=list(RULES),
    )
    kw.update(over)
    return new_episode_manifest(**kw)


def chain(n: int):
    out = []
    parent = None
    for i in range(n):
        m = manifest(episode_number=i, parent_episode_id=parent)
        out.append(m)
        parent = m["episode_id"]
    return out


def _log():
    return new_event_log(manifest()["episode_id"])


# --------------------------------------------------------------------------
# IDENTITY
# --------------------------------------------------------------------------

def test_id_prefixes_and_lengths():
    assert make_world_id("riverside").startswith("wld_")
    assert len(make_world_id("riverside")) == 4 + 16
    assert make_episode_id(WORLD, 0, manifest()["inputs"]).startswith("ep_")
    ep = manifest()["episode_id"]
    assert make_event_id(ep, "simulation_ended", 0,
                         {"sim_seconds": 1.0, "steps_completed": 1}).startswith("evt_")
    assert make_agent_id(WORLD, "vehicle", "veh:1").startswith("agt_")


def test_id_hasher_matches_published_sha256_test_vectors():
    """Hard-coded expected id strings, from the SHA-256 standard test vectors.

    They pin the convention -- prefix + the first 16 hex of sha256 of the exact
    bytes hashed -- so any change to the hashing or the truncation is caught.
    """
    assert _id_from_bytes("wld_", b"") == "wld_e3b0c44298fc1c14"
    assert _id_from_bytes("ep_", b"abc") == "ep_ba7816bf8f01cfea"
    assert _id_from_bytes(
        "evt_", b"The quick brown fox jumps over the lazy dog"
    ) == "evt_d7a8fbb307d78094"


def test_world_id_is_pinned_to_a_hard_coded_canonical_vector():
    """The canonical bytes are hard-coded, so the id is fully determined.

    ``world_state.canonical_bytes`` is the ONE serialisation; the expected bytes
    below are written out in full so a change of key order, separators or an
    extra field fails the test on every machine.
    """
    pinned = b'{"name":"riverside","state_hash":""}'
    assert canonical_bytes({"name": "riverside"}) == pinned
    assert make_world_id("riverside") == "wld_" + hashlib.sha256(pinned).hexdigest()[:16]


def test_same_inputs_give_the_same_id_on_any_machine():
    assert make_world_id("riverside") == make_world_id("riverside")
    assert manifest()["episode_id"] == manifest()["episode_id"]
    assert make_agent_id(WORLD, "vehicle", "veh:1") == make_agent_id(WORLD, "vehicle", "veh:1")


def test_id_is_insensitive_to_dict_key_order():
    a = make_episode_id(WORLD, 0, manifest()["inputs"])
    shuffled = dict(reversed(list(manifest()["inputs"].items())))
    assert make_episode_id(WORLD, 0, shuffled) == a


@pytest.mark.parametrize(
    "field,value",
    [
        ("net_sha256", "2" * 64),
        ("route_sha256", ["c" * 64, ROUTES[1]]),
        ("route_sha256", [ROUTES[0], "d" * 64]),
        ("route_sha256", [ROUTES[1], ROUTES[0]]),
        ("route_sha256", [ROUTES[0]]),
        ("seed", 20260904),
        ("end_seconds", 241.0),
        ("step_length", 0.2),
        ("rule_ids", list(reversed(RULES))),
        ("rule_ids", [RULES[0]]),
    ],
    ids=[
        "net_hash",
        "route_0",
        "route_1",
        "route_order",
        "route_count",
        "seed",
        "end_seconds",
        "step_length",
        "rule_order",
        "rule_subset",
    ],
)
def test_changing_any_single_input_changes_the_episode_id(field, value):
    base = manifest()
    changed = manifest(**{field: value})
    assert base["episode_id"] != changed["episode_id"]


def test_inputs_digest_covers_every_input_and_its_order():
    base = episode_inputs_digest(
        net_sha256=NET, route_sha256=list(ROUTES), seed=20260903,
        end_seconds=240.0, step_length=0.1, rule_ids=list(RULES),
    )
    assert base == episode_inputs_digest(
        net_sha256=NET, route_sha256=list(ROUTES), seed=20260903,
        end_seconds=240.0, step_length=0.1, rule_ids=list(RULES),
    )
    for changed in (
        dict(net_sha256="2" * 64, route_sha256=list(ROUTES), seed=20260903,
             end_seconds=240.0, step_length=0.1, rule_ids=list(RULES)),
        dict(net_sha256=NET, route_sha256=list(reversed(ROUTES)), seed=20260903,
             end_seconds=240.0, step_length=0.1, rule_ids=list(RULES)),
        dict(net_sha256=NET, route_sha256=list(ROUTES), seed=7,
             end_seconds=240.0, step_length=0.1, rule_ids=list(RULES)),
        dict(net_sha256=NET, route_sha256=list(ROUTES), seed=20260903,
             end_seconds=240.0, step_length=0.1, rule_ids=list(reversed(RULES))),
    ):
        assert episode_inputs_digest(**changed) != base


def test_agent_ids_are_scoped_to_world_kind_and_key():
    a = make_agent_id(WORLD, "vehicle", "veh:1")
    assert a == make_agent_id(WORLD, "vehicle", "veh:1")
    assert a != make_agent_id(WORLD, "person", "veh:1")
    assert a != make_agent_id(WORLD, "vehicle", "veh:2")
    assert a != make_agent_id(make_world_id("elsewhere"), "vehicle", "veh:1")


# --------------------------------------------------------------------------
# THE MANIFEST
# --------------------------------------------------------------------------

def test_manifest_is_sealed_and_carries_the_required_keys():
    m = manifest()
    assert m["schema_version"] == SCHEMA_VERSION
    for key in (
        "schema_version", "world_id", "episode_id", "episode_number",
        "parent_episode_id", "inputs", "rules_applied", "events", "outputs",
        "state_hash",
    ):
        assert key in m
    assert verify(m)
    assert len(m["state_hash"]) == 64


def test_parent_is_null_only_for_episode_zero():
    assert manifest(episode_number=0)["parent_episode_id"] is None
    with pytest.raises(EpisodeError):
        manifest(episode_number=0, parent_episode_id="ep_" + "0" * 16)
    with pytest.raises(EpisodeError):
        manifest(episode_number=1)                          # non-root needs a parent
    first = manifest()
    child = manifest(episode_number=1, parent_episode_id=first["episode_id"])
    assert child["parent_episode_id"] == first["episode_id"]


def test_inputs_carry_the_digest_of_the_covered_fields():
    m = manifest()
    i = m["inputs"]
    assert i["inputs_digest"] == episode_inputs_digest(
        net_sha256=i["net_sha256"], route_sha256=i["route_sha256"], seed=i["seed"],
        end_seconds=i["end_seconds"], step_length=i["step_length"], rule_ids=i["rule_ids"],
    )


def test_rules_applied_defaults_to_the_input_rule_ids():
    assert manifest()["rules_applied"] == list(RULES)


def test_rules_applied_must_be_an_ordered_subset_of_the_input_rules():
    assert manifest(rules_applied=[RULES[0]])["rules_applied"] == [RULES[0]]
    with pytest.raises(EpisodeError):
        manifest(rules_applied=[RULES[1], RULES[0]])         # wrong order
    with pytest.raises(EpisodeError):
        manifest(rules_applied=["not_a_rule"])


# --------------------------------------------------------------------------
# THE TYPED EVENT LOG
# --------------------------------------------------------------------------

def test_new_event_log_is_empty_and_bound_to_its_episode():
    lg = _log()
    assert lg["events"] == []
    assert lg["episode_id"] == manifest()["episode_id"]


def test_every_kind_in_the_closed_set_is_accepted():
    payloads = {
        "rule_applied": {"rule_id": RULES[0], "change_id": "chg_" + "0" * 16},
        "agent_replanned": {"agent_id": "agt_" + "1" * 16, "destination_edge": "C1D1"},
        "agent_goal_reached": {"agent_id": "agt_" + "1" * 16, "destination_edge": "C1D1"},
        "agent_blocked": {"agent_id": "agt_" + "1" * 16, "edge_id": "A1B1",
                          "reason_code": "closed_edge"},
        "vehicle_rerouted": {"vehicle_id": "veh:1", "from_route_sha256": "a" * 64,
                             "to_route_sha256": "b" * 64},
        "simulation_started": {"seed": 20260903, "end_seconds": 240.0, "step_length": 0.1},
        "simulation_ended": {"sim_seconds": 240.0, "steps_completed": 2400},
    }
    lg = _log()
    for seq, kind in enumerate(EVENT_KINDS):
        lg = append_event(lg, kind=kind, seq=seq, payload=payloads[kind])
    assert [e["kind"] for e in lg["events"]] == list(EVENT_KINDS)


def test_append_event_is_pure_and_append_only():
    lg0 = _log()
    lg1 = append_event(lg0, kind="simulation_started", seq=0,
                       payload={"seed": 1, "end_seconds": 10.0, "step_length": 0.1})
    assert lg0["events"] == []
    assert lg0 is not lg1
    assert [e["seq"] for e in lg1["events"]] == [0]


def test_seq_must_strictly_increase_and_duplicates_raise():
    lg = append_event(_log(), kind="simulation_started", seq=5,
                      payload={"seed": 1, "end_seconds": 10.0, "step_length": 0.1})
    with pytest.raises(EpisodeError):
        append_event(lg, kind="simulation_ended", seq=5,
                     payload={"sim_seconds": 10.0, "steps_completed": 100})
    with pytest.raises(EpisodeError):
        append_event(lg, kind="simulation_ended", seq=4,
                     payload={"sim_seconds": 10.0, "steps_completed": 100})
    lg2 = append_event(lg, kind="simulation_ended", seq=6,
                       payload={"sim_seconds": 10.0, "steps_completed": 100})
    assert [e["seq"] for e in lg2["events"]] == [5, 6]


def test_unknown_event_kinds_raise():
    with pytest.raises(EpisodeError):
        append_event(_log(), kind="world_state_edited", seq=0, payload={})
    with pytest.raises(EpisodeError):
        make_event_id("ep_" + "0" * 16, "made_up", 0, {})


def test_events_have_no_free_text_field():
    """An extra key is refused, so prose cannot be smuggled into the record."""
    for extra in ({"note": "the bridge looked busy"}, {"text": "..."}, {"message": "x"}):
        payload = {"agent_id": "agt_" + "1" * 16, "destination_edge": "C1D1"}
        payload.update(extra)
        with pytest.raises(EpisodeError):
            append_event(_log(), kind="agent_replanned", seq=0, payload=payload)


def test_event_id_is_content_derived_and_seq_sensitive():
    ep = "ep_" + "0" * 16
    p = {"agent_id": "agt_" + "1" * 16, "destination_edge": "C1D1"}
    assert make_event_id(ep, "agent_replanned", 3, p) == make_event_id(ep, "agent_replanned", 3, p)
    assert make_event_id(ep, "agent_replanned", 3, p) != make_event_id(ep, "agent_replanned", 4, p)
    other = dict(p)
    other["destination_edge"] = "D1E1"
    assert make_event_id(ep, "agent_replanned", 3, p) != make_event_id(ep, "agent_replanned", 3, other)


def test_manifest_refuses_a_forged_event_id_and_a_bad_seq_order():
    m0 = manifest()
    eid = m0["episode_id"]
    payload = {"seed": 1, "end_seconds": 10.0, "step_length": 0.1}
    good = {"event_id": make_event_id(eid, "simulation_started", 0, payload),
            "kind": "simulation_started", "seq": 0, "payload": payload}
    assert manifest(events=[good])["events"][0]["event_id"] == good["event_id"]

    forged = dict(good)
    forged["event_id"] = "evt_" + "0" * 16
    with pytest.raises(EpisodeError):
        manifest(events=[forged])

    end = {"event_id": make_event_id(eid, "simulation_ended", 0,
                                     {"sim_seconds": 1.0, "steps_completed": 1}),
           "kind": "simulation_ended", "seq": 0,
           "payload": {"sim_seconds": 1.0, "steps_completed": 1}}
    with pytest.raises(EpisodeError):
        manifest(events=[end, good])                    # duplicate seq 0


# --------------------------------------------------------------------------
# OUTPUTS BOUND TO BYTES ON DISK
# --------------------------------------------------------------------------

def test_outputs_are_validated_at_manifest_build_time():
    ok = manifest(outputs=[{"path": "media/episode.mp4", "sha256": "a" * 64}])
    assert ok["outputs"][0]["path"] == "media/episode.mp4"
    for bad in (
        [{"path": "/abs.mp4", "sha256": "a" * 64}],
        [{"path": "../escape.mp4", "sha256": "a" * 64}],
        [{"path": "x.mp4", "sha256": "nothex"}],
        [{"path": "x.mp4", "sha256": "a" * 64, "note": "hi"}],
        [{"path": "x.mp4", "sha256": "a" * 64}, {"path": "x.mp4", "sha256": "b" * 64}],
    ):
        with pytest.raises(EpisodeError):
            manifest(outputs=bad)


def test_verify_outputs_catches_bytes_edited_after_sealing(tmp_path):
    target = tmp_path / "media" / "episode.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"the reviewed cut")
    sealed = hashlib.sha256(target.read_bytes()).hexdigest()
    m = manifest(outputs=[{"path": "media/episode.mp4", "sha256": sealed}])
    assert verify_outputs(m, tmp_path) is True
    target.write_bytes(b"a different cut")
    with pytest.raises(EpisodeError):
        verify_outputs(m, tmp_path)


def test_verify_outputs_reports_a_missing_or_traversal_path(tmp_path):
    missing = manifest(outputs=[{"path": "media/gone.mp4", "sha256": "a" * 64}])
    with pytest.raises(EpisodeError):
        verify_outputs(missing, tmp_path)
    escape = manifest(outputs=[{"path": "media/keep.mp4", "sha256": "a" * 64}])
    escape["outputs"][0]["path"] = "../keep.mp4"
    with pytest.raises(EpisodeError):
        verify_outputs(escape, tmp_path)


# --------------------------------------------------------------------------
# LINEAGE
# --------------------------------------------------------------------------

def test_verify_episode_lineage_accepts_a_real_chain():
    verify_episode_lineage(chain(3))


def test_empty_lineage_raises():
    with pytest.raises(EpisodeError):
        verify_episode_lineage([])


def test_lineage_must_start_at_episode_zero():
    lone = manifest(episode_number=1, parent_episode_id="ep_" + "0" * 16)
    with pytest.raises(EpisodeError):
        verify_episode_lineage([lone])


def test_reordered_chain_raises():
    c = chain(3)
    with pytest.raises(ChainError):
        verify_episode_lineage([c[0], c[2], c[1]])


def test_gap_in_episode_numbers_raises():
    c = chain(3)
    with pytest.raises(ChainError):
        verify_episode_lineage([c[0], c[2]])


def test_broken_parent_id_raises():
    c = chain(2)
    broken = copy.deepcopy(c[1])
    broken["parent_episode_id"] = "ep_" + "f" * 16
    broken = seal(broken)                    # internally consistent, but mis-parented
    with pytest.raises(EpisodeError):
        verify_episode_lineage([c[0], broken])


def test_lineage_refuses_a_foreign_world():
    c = chain(2)
    other = manifest(world_id=make_world_id("elsewhere"), episode_number=1,
                     parent_episode_id=c[0]["episode_id"])
    with pytest.raises(EpisodeError):
        verify_episode_lineage([c[0], other])


def test_forged_state_hash_raises():
    """Tampering with a manifest and NOT re-sealing is caught by the hash."""
    c = chain(2)
    c[1]["inputs"]["seed"] = 999
    with pytest.raises(ChainError):
        verify_episode_lineage([c[0], c[1]])


def test_content_that_does_not_match_the_episode_id_raises():
    m = manifest()
    m["inputs"]["seed"] = 7
    m = seal(m)                              # hash valid, id no longer matches
    with pytest.raises(EpisodeError):
        verify_episode_lineage([m])


# --------------------------------------------------------------------------
# ADVERSARIAL
# --------------------------------------------------------------------------

def test_invalid_id_formats_are_refused():
    seeds = manifest()["inputs"]
    for bad_world in ("riverside", "", "wld_", "wld_0000", "wld_" + "Z" * 16, "WLD_" + "0" * 16):
        with pytest.raises(EpisodeError):
            make_episode_id(bad_world, 0, seeds)
        with pytest.raises(EpisodeError):
            make_agent_id(bad_world, "vehicle", "v1")
    for bad_ep in ("", "ep_1234", "EP_" + "0" * 16, "evt_" + "0" * 16):
        with pytest.raises(EpisodeError):
            new_event_log(bad_ep)
        with pytest.raises(EpisodeError):
            make_event_id(bad_ep, "simulation_ended", 0,
                          {"sim_seconds": 1.0, "steps_completed": 1})


def test_bad_episode_numbers_and_seq_are_refused():
    seeds = manifest()["inputs"]
    for bad_number in (-1, 1.5, True, "0"):
        with pytest.raises(EpisodeError):
            make_episode_id(WORLD, bad_number, seeds)
    with pytest.raises(EpisodeError):
        make_event_id("ep_" + "0" * 16, "simulation_ended", -1,
                      {"sim_seconds": 1.0, "steps_completed": 1})


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("simulation_started", {"seed": 1, "end_seconds": 10.0}),
        ("simulation_started",
         {"seed": 1, "end_seconds": 10.0, "step_length": 0.1, "note": "hello"}),
        ("simulation_ended", {"sim_seconds": 1.0, "steps_completed": "many"}),
        ("agent_blocked", {"agent_id": "agt_" + "1" * 16, "edge_id": "A1B1",
                           "reason_code": "because I said so"}),
        ("vehicle_rerouted", {"vehicle_id": "veh:1", "from_route_sha256": "zz" * 32,
                              "to_route_sha256": "b" * 64}),
        ("rule_applied", {"rule_id": RULES[0]}),
    ],
    ids=["missing_field", "free_text_field", "wrong_type", "not_a_code",
         "bad_hash", "missing_change_id"],
)
def test_malformed_event_payloads_raise(kind, payload):
    with pytest.raises(EpisodeError):
        append_event(_log(), kind=kind, seq=0, payload=payload)
    with pytest.raises(EpisodeError):
        make_event_id("ep_" + "0" * 16, kind, 0, payload)


def test_append_event_refuses_a_malformed_log():
    with pytest.raises(EpisodeError):
        append_event({"episode_id": "nope", "events": []}, kind="simulation_ended", seq=0,
                     payload={"sim_seconds": 1.0, "steps_completed": 1})
    with pytest.raises(EpisodeError):
        append_event({"episode_id": "ep_" + "0" * 16}, kind="simulation_ended", seq=0,
                     payload={"sim_seconds": 1.0, "steps_completed": 1})


def test_stale_parent_raises():
    """A parent whose hash no longer verifies cannot anchor a chain."""
    c = chain(2)
    c[0]["world_id"] = make_world_id("elsewhere")           # parent content changed
    with pytest.raises(ChainError):
        verify_episode_lineage(c)
