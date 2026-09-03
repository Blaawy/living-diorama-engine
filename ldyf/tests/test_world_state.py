"""Proof that THE WORLD REMEMBERS is enforced, not merely intended."""

from __future__ import annotations

import copy
import json

import pytest

from ldyf.world_state import (
    ChainError,
    canonical_bytes,
    close_edges,
    compute_state_hash,
    inherit,
    load,
    save,
    seal,
    verify,
    verify_lineage,
    verify_or_raise,
)


def make_world(episode: int = 0) -> dict:
    return {
        "schema_version": "world_state_v1",
        "world_id": "riverside",
        "episode_number": episode,
        "state_hash": "",
        "parent_state_hash": None,
        "created_utc": "2026-09-03T00:00:00Z",
        "network": {
            "net_file": "grid.net.xml",
            "net_sha256": "a" * 64,
            "extent_m": {"min_x": 0.0, "min_y": 0.0, "max_x": 600.0, "max_y": 600.0},
        },
        "districts": [],
        "infrastructure": [],
        "persistent_changes_ref": {"file": "persistent_changes.json", "sha256": "b" * 64},
    }


# --- hashing --------------------------------------------------------------

def test_seal_then_verify():
    w = seal(make_world())
    assert verify(w)
    assert len(w["state_hash"]) == 64


def test_hash_ignores_the_hash_field():
    w = make_world()
    a = compute_state_hash(w)
    w["state_hash"] = "deadbeef"
    assert compute_state_hash(w) == a


def test_any_content_change_changes_the_hash():
    w = seal(make_world())
    for mutate in (
        lambda d: d.__setitem__("world_id", "other"),
        lambda d: d.__setitem__("episode_number", 7),
        lambda d: d["network"].__setitem__("net_sha256", "c" * 64),
        lambda d: d["districts"].append({"district_id": "x", "name": "X", "edge_ids": []}),
    ):
        m = copy.deepcopy(w)
        mutate(m)
        assert not verify(m), "a tampered world must fail verification"


def test_key_order_does_not_affect_the_hash():
    w = make_world()
    reordered = dict(reversed(list(w.items())))
    assert compute_state_hash(w) == compute_state_hash(reordered)


def test_canonical_bytes_are_compact_and_sorted():
    b = canonical_bytes(make_world())
    assert b"\n" not in b and b", " not in b
    text = b.decode()
    assert text.index('"created_utc"') < text.index('"districts"') < text.index('"episode_number"')


def test_hash_survives_file_reformatting(tmp_path):
    """The hash is over content, not over file bytes."""
    p = tmp_path / "w.json"
    h = save(make_world(), p)
    doc = json.loads(p.read_text())
    p.write_text(json.dumps(doc, indent=8))          # reformat aggressively
    reloaded = load(p)
    assert reloaded["state_hash"] == h


# --- inheritance ----------------------------------------------------------

def test_inherit_links_to_parent():
    parent = seal(make_world(0))
    child = seal(inherit(parent))
    assert child["parent_state_hash"] == parent["state_hash"]
    assert child["episode_number"] == 1
    assert verify(child)


def test_inherit_refuses_an_unverified_parent():
    """The structural guarantee: no path builds on a broken world."""
    parent = seal(make_world(0))
    parent["world_id"] = "tampered"          # hash now stale
    with pytest.raises(ChainError):
        inherit(parent)


def test_inherit_refuses_a_non_increasing_episode_number():
    parent = seal(make_world(5))
    with pytest.raises(ChainError):
        inherit(parent, episode_number=5)
    with pytest.raises(ChainError):
        inherit(parent, episode_number=4)


def test_version_history_accumulates():
    w0 = seal(make_world(0))
    w1 = seal(inherit(w0))
    w2 = seal(inherit(w1))
    assert [h["episode_number"] for h in w2["version_history"]] == [0, 1]
    assert w2["version_history"][0]["state_hash"] == w0["state_hash"]


# --- lineage --------------------------------------------------------------

def test_verify_lineage_accepts_a_real_chain():
    w0 = seal(make_world(0))
    w1 = seal(inherit(w0))
    w2 = seal(inherit(w1))
    verify_lineage([w0, w1, w2])


def test_verify_lineage_rejects_a_reordered_chain():
    w0 = seal(make_world(0))
    w1 = seal(inherit(w0))
    w2 = seal(inherit(w1))
    with pytest.raises(ChainError):
        verify_lineage([w0, w2, w1])


def test_verify_lineage_rejects_a_spliced_episode():
    """An episode from a different lineage cannot be inserted."""
    w0 = seal(make_world(0))
    w1 = seal(inherit(w0))
    other = make_world(1)
    other["world_id"] = "elsewhere"
    other["parent_state_hash"] = "f" * 64
    other = seal(other)
    with pytest.raises(ChainError):
        verify_lineage([w0, other])
    verify_lineage([w0, w1])          # the real one still passes


def test_verify_lineage_rejects_a_silent_reset():
    """A fresh episode 0 cannot masquerade as the continuation of a lineage."""
    w0 = seal(make_world(0))
    w1 = seal(inherit(w0))
    reset = seal(make_world(2))       # parent_state_hash is None
    with pytest.raises(ChainError):
        verify_lineage([w0, w1, reset])


# --- permanence -----------------------------------------------------------

def test_closure_is_recorded_in_the_world():
    w = close_edges(make_world(1), ["A1B1", "B1C1"], episode_number=1, reason="bridge closed")
    ids = [c["edge_id"] for c in w["network"]["closed_edges"]]
    assert ids == ["A1B1", "B1C1"]


def test_closure_survives_inheritance():
    """The scar outlives the episode that made it."""
    w0 = seal(close_edges(make_world(0), ["A1B1"], episode_number=0, reason="rule"))
    w1 = seal(inherit(w0))
    w2 = seal(inherit(w1))
    assert [c["edge_id"] for c in w2["network"]["closed_edges"]] == ["A1B1"]


def test_closure_is_idempotent():
    w = close_edges(make_world(0), ["A1B1"], episode_number=0, reason="r")
    w = close_edges(w, ["A1B1"], episode_number=1, reason="r again")
    assert len(w["network"]["closed_edges"]) == 1
    assert w["network"]["closed_edges"][0]["closed_in_episode"] == 0


def test_module_exposes_no_way_to_delete_a_closure():
    """DNA-03 enforced structurally: there is no un-close function to call."""
    import ldyf.world_state as ws

    names = [n for n in dir(ws) if not n.startswith("_")]
    for forbidden in ("open_edges", "remove_closure", "delete_closure", "clear_closed_edges"):
        assert forbidden not in names


# --- io -------------------------------------------------------------------

def test_load_refuses_a_tampered_file(tmp_path):
    p = tmp_path / "w.json"
    save(make_world(), p)
    doc = json.loads(p.read_text())
    doc["world_id"] = "tampered"
    p.write_text(json.dumps(doc))
    with pytest.raises(ChainError):
        load(p)


def test_verify_or_raise_message_is_useful():
    w = seal(make_world())
    w["world_id"] = "x"
    with pytest.raises(ChainError) as e:
        verify_or_raise(w)
    assert "failed hash verification" in str(e.value)
