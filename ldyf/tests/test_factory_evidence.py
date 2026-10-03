"""Phase 4 factory, the EVIDENCE half: brief, world, seals, record, facts.

Everything downstream of `facts.json` may only repeat a number this half
measured, so this file attacks the measuring. The unit tests pin each typed
refusal (`FactoryError.stage` / `.code`, never message prose). The fact tests
run against the REAL sealed episode and then against damaged private copies of
it: missing, corrupt, stale, unsealed -- and, the adversarial gate, copies an
INSIDER has doctored and re-sealed so that every hash verifies and only the
cross-checks between the event log and the record can refuse.

The package is read-only. A test that damages evidence copies it first.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import shutil
import struct
from pathlib import Path

import pytest

from ldyf.evidence import verify_rule_manifest
from ldyf.factory import FactoryError
from ldyf.factory.brief import (BRIEF_SCHEMA, BriefError, brief_hash, build_rule,
                                build_rule_manifest, normalise_brief, rule_id_for)
from ldyf.factory.facts import (FACTS_SCHEMA, FactsError, extract_facts, ledger_effects,
                                load_facts)
from ldyf.factory.record import (RECORD_FORMAT, RecordError, Track, dist_to_segments,
                                 load_record, trim_segments)
from ldyf.factory.util import (SealError, canonical_bytes, read_json, seal, sha256_bytes,
                               verify_seal, write_json)
from ldyf.factory.world import WORLDS_DIR, WorldError, load_world, street_name, twin_edge

from .factory_support import BRIEF_PATH, copy_sim, dump, load, reseal_simulation


# --------------------------------------------------------------------------
# brief
# --------------------------------------------------------------------------

def _raw() -> dict:
    return load(BRIEF_PATH)


def _with(**changes) -> dict:
    raw = _raw()
    raw.update(changes)
    return raw


def _without(key: str) -> dict:
    raw = _raw()
    del raw[key]
    return raw


def _rule(**changes) -> dict:
    raw = _raw()
    raw["rule"] = {**raw["rule"], **changes}
    return raw


def _pred(**changes) -> dict:
    raw = _raw()
    raw["prediction"] = {**raw["prediction"], **changes}
    return raw


def test_shipped_brief_normalises_and_fills_every_default():
    """A default that stopped being filled would make downstream stages KeyError or guess."""
    b = normalise_brief(_raw())
    assert b["schema_version"] == BRIEF_SCHEMA
    assert b["fps"] == 24
    assert b["resolution"] == [1920, 1080]
    assert b["target_seconds"] == [480.0, 600.0]
    assert b["voice"] == "Microsoft Zira Desktop"
    assert b["voice_rate"] == -1
    assert b["seed"] == 20260903
    assert b["replicate_seeds"] == [20260904, 20260905]
    assert b["end_seconds"] == 1500.0 and isinstance(b["end_seconds"], float)
    assert b["rule"] == {"kind": "close_street", "edge": "B1B2", "at_second": 30}


def test_normalising_twice_is_idempotent_and_the_hash_is_stable():
    """A normaliser that drifts on re-entry would make every resume look like a new brief."""
    once = normalise_brief(_raw())
    twice = normalise_brief(copy.deepcopy(once))
    assert twice == once
    assert brief_hash(twice) == brief_hash(once) == brief_hash(normalise_brief(_raw()))
    assert len(brief_hash(once)) == 64


def test_normalise_does_not_mutate_its_input():
    """A normaliser that edits the caller's dict would change the brief file's meaning in place."""
    raw = _raw()
    before = copy.deepcopy(raw)
    normalise_brief(raw)
    assert raw == before


def test_brief_hash_ignores_key_order_and_follows_the_seed():
    """Key order must not be identity; the seed must be, or two episodes share a lineage."""
    raw = _raw()
    reordered = {k: raw[k] for k in reversed(list(raw))}
    reordered["rule"] = {k: raw["rule"][k] for k in reversed(list(raw["rule"]))}
    assert list(reordered) != list(raw)
    assert brief_hash(normalise_brief(reordered)) == brief_hash(normalise_brief(raw))
    assert brief_hash(normalise_brief(_with(seed=20260999))) != brief_hash(normalise_brief(raw))


BRIEF_REFUSALS = [
    ("a list is not a brief", lambda: [], "not_an_object"),
    ("a string is not a brief", lambda: "close a street", "not_an_object"),
    ("wrong schema_version", lambda: _with(schema_version="episode_brief_v2"), "bad_version"),
    ("no schema_version", lambda: _without("schema_version"), "bad_version"),
    ("unknown top-level field", lambda: _with(sead=1), "unknown_field"),
    ("missing title", lambda: _without("title"), "missing_field"),
    ("missing world", lambda: _without("world"), "missing_field"),
    ("missing statement", lambda: _without("statement"), "missing_field"),
    ("missing rule", lambda: _without("rule"), "missing_field"),
    ("missing prediction", lambda: _without("prediction"), "missing_field"),
    ("empty title", lambda: _with(title=""), "bad_field"),
    ("blank title", lambda: _with(title="   "), "bad_field"),
    ("title not a string", lambda: _with(title=7), "bad_field"),
    ("world not a string", lambda: _with(world=3), "bad_field"),
    ("statement too short", lambda: _with(statement="ab"), "bad_field"),
    ("statement too long", lambda: _with(statement="x" * 241), "bad_field"),
    ("negative episode number", lambda: _with(episode_number=-1), "bad_field"),
    ("seed is a bool", lambda: _with(seed=True), "bad_field"),
    ("seed is a float", lambda: _with(seed=20260903.0), "bad_field"),
    ("end_seconds zero", lambda: _with(end_seconds=0), "bad_field"),
    ("end_seconds negative", lambda: _with(end_seconds=-5), "bad_field"),
    ("end_seconds infinite", lambda: _with(end_seconds=float("inf")), "bad_field"),
    ("target_seconds reversed", lambda: _with(target_seconds=[600, 480]), "bad_field"),
    ("target_seconds from zero", lambda: _with(target_seconds=[0, 480]), "bad_field"),
    ("target_seconds one value", lambda: _with(target_seconds=[480]), "bad_field"),
    ("target_seconds not a list", lambda: _with(target_seconds="480-600"), "bad_field"),
    ("fps zero", lambda: _with(fps=0), "bad_field"),
    ("fps too high", lambda: _with(fps=121), "bad_field"),
    ("fps a float", lambda: _with(fps=24.0), "bad_field"),
    ("fps a bool", lambda: _with(fps=True), "bad_field"),
    ("resolution one value", lambda: _with(resolution=[1920]), "bad_field"),
    ("resolution too small", lambda: _with(resolution=[8, 8]), "bad_field"),
    ("resolution floats", lambda: _with(resolution=[1920.0, 1080.0]), "bad_field"),
    ("resolution a string", lambda: _with(resolution="1920x1080"), "bad_field"),
    ("empty voice", lambda: _with(voice=""), "bad_field"),
    ("voice_rate too fast", lambda: _with(voice_rate=11), "bad_field"),
    ("voice_rate too slow", lambda: _with(voice_rate=-11), "bad_field"),
    ("voice_rate a float", lambda: _with(voice_rate=1.0), "bad_field"),
    ("duplicate replicate seed", lambda: _with(replicate_seeds=[20260904, 20260904]), "bad_field"),
    ("replicate equal to seed", lambda: _with(replicate_seeds=[20260903]), "bad_field"),
    ("replicate seed not an int", lambda: _with(replicate_seeds=["20260904"]), "bad_field"),
    ("declared_utc date only", lambda: _with(declared_utc="2026-10-03"), "bad_field"),
    ("declared_utc with offset", lambda: _with(declared_utc="2026-10-03T00:00:00+0"), "bad_field"),
    ("declared_utc not a string", lambda: _with(declared_utc=20261003), "bad_field"),
    ("rule not an object", lambda: _with(rule="close B1B2"), "bad_rule"),
    ("unknown rule kind", lambda: _rule(kind="demolish_street"), "bad_rule"),
    ("unknown rule field", lambda: _rule(colour="red"), "bad_rule"),
    ("missing rule field", lambda: _with(rule={"kind": "close_street", "at_second": 30}), "bad_rule"),
    ("missing at_second", lambda: _with(rule={"kind": "close_street", "edge": "B1B2"}), "bad_rule"),
    ("negative at_second", lambda: _rule(at_second=-1), "bad_rule"),
    ("at_second a bool", lambda: _rule(at_second=True), "bad_rule"),
    ("at_second equal to end_seconds", lambda: _rule(at_second=1500), "bad_rule"),
    ("at_second after end_seconds", lambda: _rule(at_second=2000), "bad_rule"),
    ("prediction not an object", lambda: _with(prediction="longer"), "bad_prediction"),
    ("prediction with an extra key", lambda: _pred(confidence=0.9), "bad_prediction"),
    ("prediction missing a key",
     lambda: _with(prediction={"text": "Car trips will take longer.", "direction": "increase"}),
     "bad_prediction"),
    ("prediction text too short", lambda: _pred(text="up"), "bad_prediction"),
    ("bad direction", lambda: _pred(direction="sideways"), "bad_prediction"),
    ("direction not a string", lambda: _pred(direction=[]), "bad_prediction"),
    ("empty metric", lambda: _pred(metric=""), "bad_prediction"),
]


@pytest.mark.parametrize("make,code", [(m, c) for _n, m, c in BRIEF_REFUSALS],
                         ids=[n for n, _m, _c in BRIEF_REFUSALS])
def test_malformed_brief_is_refused_with_its_code(make, code):
    """A brief that is accepted wrongly runs a different episode from the one asked for."""
    with pytest.raises(BriefError) as err:
        normalise_brief(make())
    assert err.value.code == code
    assert err.value.stage == "brief"
    assert isinstance(err.value, FactoryError)


def test_unhashable_rule_kind_is_a_typed_refusal():
    """A malformed brief must be refused as a brief, not crash the factory with a TypeError."""
    with pytest.raises(BriefError) as err:
        normalise_brief(_rule(kind=["close_street"]))
    assert err.value.code == "bad_rule"


def test_declared_utc_that_is_not_a_timestamp_is_refused():
    """The 'declared before the run' claim rests on this field being a real UTC instant."""
    with pytest.raises(BriefError) as err:
        normalise_brief(_with(declared_utc="x" * 19 + "Z"))
    assert err.value.code == "bad_field"


def test_rule_id_is_derived_from_the_rule_content():
    """A random or time-based id would make the same brief seal a different manifest each run."""
    a, b = normalise_brief(_raw()), normalise_brief(_raw())
    assert rule_id_for(a) == rule_id_for(b)
    assert rule_id_for(a).startswith("chg_") and len(rule_id_for(a)) == 20
    assert rule_id_for(normalise_brief(_rule(edge="C1C2"))) != rule_id_for(a)
    assert rule_id_for(normalise_brief(_rule(at_second=60))) != rule_id_for(a)
    # the title is presentation: it must not move the rule's identity
    assert rule_id_for(normalise_brief(_with(title="Another title"))) == rule_id_for(a)


def test_build_rule_carries_the_brief_rule_and_its_content_id():
    """A rule built with another edge, second or id is not the rule the brief declared."""
    b = normalise_brief(_raw())
    rule = build_rule(b)
    assert rule.rule_id == rule_id_for(b)
    assert rule.at_second == 30.0
    assert tuple(rule.edge_ids) == ("B1B2",)


def test_build_rule_refuses_a_value_the_rule_cannot_hold():
    """A rule the Phase 3 contract cannot build must be a typed brief refusal, not a ValueError."""
    b = normalise_brief(_with(rule={"kind": "speed_limit", "edge": "B1B2", "mps": "fast",
                                    "at_second": 30}))
    with pytest.raises(BriefError) as err:
        build_rule(b)
    assert err.value.code == "bad_rule"


def test_rule_manifest_verifies_declares_the_prediction_and_is_byte_stable():
    """A manifest that differs between two builds cannot be 'hashed before the run'."""
    b = normalise_brief(_raw())
    m1 = build_rule_manifest(b, build_rule(b))
    m2 = build_rule_manifest(b, build_rule(b))
    verify_rule_manifest(m1)
    assert m1["schema_version"] == "rule_manifest_v2"
    assert m1["prediction"]["declared_before_run"] is True
    assert m1["prediction"]["direction"] == "increase"
    assert m1["prediction"]["metric"] == "avg_duration_s"
    assert m1["rule_id"] == rule_id_for(b)
    assert m1["change"]["close_edges"]["edge_ids"] == ["B1B2"]
    assert m1["applies_at_sim_second"] == 30.0
    assert len(m1["manifest_hash"]) == 64
    assert canonical_bytes(m1) == canonical_bytes(m2)


def test_rule_manifest_matches_the_one_sealed_in_the_episode(factory_pkg, factory_brief):
    """The manifest the simulation ran under must be the one this brief builds today."""
    built = build_rule_manifest(factory_brief, build_rule(factory_brief))
    sealed = load(factory_pkg / "sim" / "rule_manifest.json")
    assert built["manifest_hash"] == sealed["manifest_hash"]


# --------------------------------------------------------------------------
# world
# --------------------------------------------------------------------------

def _world_copy(tmp_path: Path, name: str = "riverside") -> Path:
    """A private worlds/ directory holding a copy of the shipped world."""
    worlds = tmp_path / "worlds"
    shutil.copytree(WORLDS_DIR / "riverside", worlds / name)
    return worlds


def _edit_world_json(worlds: Path, name: str, **changes) -> None:
    doc = load(worlds / name / "world.json")
    doc.update(changes)
    dump(worlds / name / "world.json", doc)


def test_shipped_world_loads_and_resolves_its_inputs():
    """The locked world must verify as shipped, or nothing can be simulated at all."""
    w = load_world("riverside")
    assert w["name"] == "riverside"
    assert Path(w["_net_path"]).is_file()
    assert [Path(p).name for p in w["_route_paths"]] == ["veh.rou.xml", "ped.rou.xml"]
    assert all(Path(p).is_file() for p in w["_route_paths"])


def test_copied_world_loads_from_another_worlds_dir(tmp_path):
    """Proves the copies below are refused for their damage, not for being copies."""
    w = load_world("riverside", worlds_dir=_world_copy(tmp_path))
    assert Path(w["_dir"]) == tmp_path / "worlds" / "riverside"


def test_one_changed_byte_in_the_network_unlocks_the_world(tmp_path):
    """'The locked Phase 3 world' is a claim about bytes: one changed byte must refuse it."""
    worlds = _world_copy(tmp_path)
    net = worlds / "riverside" / "grid.net.xml"
    data = bytearray(net.read_bytes())
    data[len(data) // 2] ^= 0x01
    net.write_bytes(bytes(data))
    with pytest.raises(WorldError) as err:
        load_world("riverside", worlds_dir=worlds)
    assert err.value.code == "world_not_locked"
    assert err.value.stage == "world"


def test_one_changed_byte_in_a_route_file_unlocks_the_world(tmp_path):
    """Demand is pinned as hard as the network: an edited route file is a different city."""
    worlds = _world_copy(tmp_path)
    rou = worlds / "riverside" / "ped.rou.xml"
    rou.write_bytes(rou.read_bytes() + b" ")
    with pytest.raises(WorldError) as err:
        load_world("riverside", worlds_dir=worlds)
    assert err.value.code == "world_not_locked"


def test_missing_route_file_is_refused(tmp_path):
    """A world without its demand must not be simulated as an empty city."""
    worlds = _world_copy(tmp_path)
    (worlds / "riverside" / "veh.rou.xml").unlink()
    with pytest.raises(WorldError) as err:
        load_world("riverside", worlds_dir=worlds)
    assert err.value.code == "missing_input"


def test_world_with_another_schema_version_is_refused(tmp_path):
    """A world document of an unknown shape must not be read as if it were this one."""
    worlds = _world_copy(tmp_path)
    _edit_world_json(worlds, "riverside", schema_version="factory_world_v2")
    with pytest.raises(WorldError) as err:
        load_world("riverside", worlds_dir=worlds)
    assert err.value.code == "bad_version"


@pytest.mark.parametrize("name", ["../riverside", "river side", "riverside/..", "", "9lives", 7])
def test_world_name_that_is_not_an_identifier_is_refused(name, tmp_path):
    """The name becomes a path component: anything but an identifier could leave worlds/."""
    with pytest.raises(WorldError) as err:
        load_world(name, worlds_dir=tmp_path)
    assert err.value.code == "bad_name"


def test_world_json_that_names_itself_something_else_is_refused(tmp_path):
    """A directory renamed over another world must not answer to the new name."""
    worlds = _world_copy(tmp_path, name="lakeside")
    with pytest.raises(WorldError) as err:
        load_world("lakeside", worlds_dir=worlds)
    assert err.value.code == "name_mismatch"


def test_unknown_world_is_refused_as_missing(tmp_path):
    """A brief naming a world that is not there must stop at the world stage."""
    with pytest.raises(WorldError) as err:
        load_world("atlantis", worlds_dir=tmp_path)
    assert err.value.code == "missing"


def test_world_json_without_its_pins_is_a_typed_refusal(tmp_path):
    """A world with no pinned inputs is not locked; it must be refused, not crash."""
    worlds = _world_copy(tmp_path)
    doc = load(worlds / "riverside" / "world.json")
    del doc["net"]
    dump(worlds / "riverside" / "world.json", doc)
    with pytest.raises(WorldError):
        load_world("riverside", worlds_dir=worlds)


def test_world_json_that_is_not_an_object_is_a_typed_refusal(tmp_path):
    """A parseable but wrong-shaped world.json must be refused with a typed error."""
    worlds = _world_copy(tmp_path)
    (worlds / "riverside" / "world.json").write_text("[]", encoding="utf-8")
    with pytest.raises(WorldError):
        load_world("riverside", worlds_dir=worlds)


def test_twin_edge_is_read_from_the_network(factory_net):
    """The open side of the closed street must be found by junctions, both ways round."""
    assert twin_edge("B1B2", factory_net) == "B2B1"
    assert twin_edge("B2B1", factory_net) == "B1B2"


def test_street_name_names_the_closed_block(factory_world, factory_net):
    """The narrator says this name: a wrong street here is a false sentence in the film."""
    assert street_name("B1B2", factory_world, factory_net) == {
        "street": "Baker Avenue", "from": "Market Street", "to": "Park Street"}
    assert street_name("B2B1", factory_world, factory_net) == {
        "street": "Baker Avenue", "from": "Park Street", "to": "Market Street"}
    assert street_name("B2C2", factory_world, factory_net) == {
        "street": "Park Street", "from": "Baker Avenue", "to": "Cedar Avenue"}


def test_street_name_refuses_an_edge_the_table_cannot_name(factory_world, factory_net):
    """An invented street name would be a stated 'fact' with no source."""
    nameless = {**factory_world, "street_names": {"columns": {"A": "Alder Avenue"}, "rows": {}}}
    with pytest.raises(WorldError) as err:
        street_name("B1B2", nameless, factory_net)
    assert err.value.code == "unnameable"


# --------------------------------------------------------------------------
# util: canonical bytes, seals, JSON files
# --------------------------------------------------------------------------

def test_canonical_bytes_are_sorted_compact_utf8():
    """Any other byte layout would change every hash the factory has ever sealed."""
    assert canonical_bytes({"b": 1, "a": [1.5, "é"]}) == '{"a":[1.5,"é"],"b":1}'.encode("utf-8")
    assert canonical_bytes({"a": 1, "b": 2}) == canonical_bytes({"b": 2, "a": 1})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_canonical_bytes_refuse_non_finite_numbers(bad):
    """NaN has no canonical JSON form: hashing it would seal an unreadable document."""
    with pytest.raises(SealError) as err:
        canonical_bytes({"x": bad})
    assert err.value.code == "not_canonical"
    assert err.value.stage == "seal"


def test_canonical_bytes_refuse_what_json_cannot_hold():
    """A set or a Path silently stringified would hash differently on another machine."""
    with pytest.raises(SealError) as err:
        canonical_bytes({"x": {1, 2}})
    assert err.value.code == "not_canonical"


def test_seal_round_trips_and_does_not_mutate_its_input():
    """A seal that cannot be verified, or that edits its argument, is no seal."""
    doc = {"b": 2, "a": [1, 2, 3], "h": ""}
    sealed = seal(doc, "h")
    assert doc["h"] == ""
    assert len(sealed["h"]) == 64
    verify_seal(sealed, "h", "doc")
    assert seal(sealed, "h") == sealed            # re-sealing a sealed document is stable


def test_changed_sealed_document_is_seal_broken():
    """An edit after sealing is the one thing a seal exists to catch."""
    sealed = seal({"value": 9, "h": ""}, "h")
    sealed["value"] = 0
    with pytest.raises(SealError) as err:
        verify_seal(sealed, "h", "doc")
    assert err.value.code == "seal_broken"


@pytest.mark.parametrize("doc", [{"value": 9}, {"value": 9, "h": ""}, {"value": 9, "h": "abc"},
                                 {"value": 9, "h": 64}])
def test_document_without_a_hash_is_unsealed(doc):
    """A missing or blank hash must not verify as 'nothing to check'."""
    with pytest.raises(SealError) as err:
        verify_seal(doc, "h", "doc")
    assert err.value.code == "unsealed"


def test_verify_seal_refuses_what_is_not_an_object():
    """A list parsed from a damaged file must be a typed refusal, not an AttributeError."""
    with pytest.raises(SealError) as err:
        verify_seal([1, 2], "h", "doc")
    assert err.value.code == "not_an_object"


def test_write_json_is_deterministic_and_replaces_atomically(tmp_path):
    """Same document, same bytes; and no half-written or leftover temp file after a write."""
    a, b = tmp_path / "deep" / "er" / "a.json", tmp_path / "b.json"
    h_a = write_json(a, {"b": 1, "a": [3, 2], "s": "é"})
    h_b = write_json(b, {"s": "é", "a": [3, 2], "b": 1})
    assert a.read_bytes() == b.read_bytes()
    assert h_a == h_b == sha256_bytes(a.read_bytes())
    assert a.read_bytes().endswith(b"\n")
    assert read_json(a, "a") == {"b": 1, "a": [3, 2], "s": "é"}
    # replace, not append; and the temp file is gone
    write_json(a, {"new": True})
    assert read_json(a, "a") == {"new": True}
    assert sorted(p.name for p in a.parent.iterdir()) == ["a.json"]


def test_write_json_refusal_leaves_the_old_file_intact(tmp_path):
    """A document that cannot be written must not truncate the one already on disk."""
    p = tmp_path / "doc.json"
    write_json(p, {"good": 1})
    before = p.read_bytes()
    with pytest.raises((FactoryError, ValueError)):
        write_json(p, {"bad": float("nan")})
    assert p.read_bytes() == before
    assert sorted(x.name for x in tmp_path.iterdir()) == ["doc.json"]


def test_write_json_refuses_nan_with_a_typed_error(tmp_path):
    """Every factory refusal is a FactoryError with a code; a stage writing NaN is one too."""
    with pytest.raises(SealError) as err:
        write_json(tmp_path / "doc.json", {"bad": float("nan")})
    assert err.value.code == "not_canonical"


class _CustomError(FactoryError):
    stage = "custom"


def test_read_json_reports_missing_and_corrupt_with_the_callers_error(tmp_path):
    """The stage that asked must be the stage that refuses, with missing told from corrupt."""
    with pytest.raises(_CustomError) as err:
        read_json(tmp_path / "absent.json", "thing", error=_CustomError)
    assert (err.value.stage, err.value.code) == ("custom", "missing")
    bad = tmp_path / "bad.json"
    bad.write_text('{"cut": ', encoding="utf-8")
    with pytest.raises(_CustomError) as err:
        read_json(bad, "thing", error=_CustomError)
    assert (err.value.stage, err.value.code) == ("custom", "corrupt")
    with pytest.raises(SealError) as err:           # the default error class
        read_json(tmp_path / "absent.json", "thing")
    assert err.value.code == "missing"


# --------------------------------------------------------------------------
# record
# --------------------------------------------------------------------------

_HDR = struct.Struct("<I")
_SMP = struct.Struct("<Ifffff")


def _copy_record(pkg: Path, tmp_path: Path, *, frames: bool = True) -> Path:
    """A private copy of ONE arm's record directory (optionally without its binary)."""
    src, out = pkg / "sim" / "record_baseline", tmp_path / "record_baseline"
    out.mkdir()
    shutil.copy2(src / "record_manifest.json", out / "record_manifest.json")
    if frames:
        shutil.copy2(src / "frames.bin", out / "frames.bin")
    return out


def _tiny_record(tmp_path: Path, frames: list[list[tuple]], actors: list[dict], **manifest) -> Path:
    """A hand-made record whose manifest is consistent with its binary unless overridden."""
    data = b"".join(_HDR.pack(len(f)) + b"".join(_SMP.pack(*s) for s in f) for f in frames)
    man = {"format": RECORD_FORMAT,
           "binary": {"file": "frames.bin", "sha256": hashlib.sha256(data).hexdigest(),
                      "bytes": len(data), "sample_struct": "<Ifffff", "frame_header_struct": "<I"},
           "actors": actors,
           "clock": {"step_seconds": 0.5, "t_begin": 10.0, "frame_count": len(frames)},
           "counts": {"samples": sum(len(f) for f in frames)}}
    man.update(manifest)
    d = tmp_path / "rec"
    d.mkdir()
    (d / "frames.bin").write_bytes(data)
    dump(d / "record_manifest.json", man)
    return d


_ACTORS = [{"uid": "person:a", "kind": "person"}, {"uid": "vehicle:b", "kind": "vehicle"}]
_FRAMES = [[(0, 1.0, 2.0, 0.0, 90.0, 1.5)],
           [(0, 3.0, 4.0, 0.0, 90.0, 1.5), (1, 100.0, 200.0, 0.0, 0.0, 10.0)],
           [(1, 110.0, 200.0, 0.0, 0.0, 10.0)]]


def test_hand_made_record_parses_to_exactly_what_was_written(tmp_path):
    """A parser that shifts a field or a frame would move every body in the film."""
    rec = load_record(_tiny_record(tmp_path, _FRAMES, _ACTORS))
    assert rec.frame_count == 3 and rec.step == 0.5
    a, b = rec.tracks["person:a"], rec.tracks["vehicle:b"]
    assert list(a.frames) == [0, 1] and list(a.x) == [1.0, 3.0] and list(a.y) == [2.0, 4.0]
    assert list(b.frames) == [1, 2] and list(b.x) == [100.0, 110.0] and list(b.speed) == [10.0, 10.0]
    assert [t.uid for t in rec.of_kind("vehicle")] == ["vehicle:b"]
    assert [t.uid for t in rec.select(["vehicle:b", "person:zzz"])] == ["vehicle:b"]
    assert rec.time_of(2) == 11.0 and rec.frame_of(11.0) == 2


def test_record_naming_an_actor_index_the_manifest_lacks_is_corrupt(tmp_path):
    """A sample for an undeclared actor must be refused, not dropped or mis-assigned."""
    frames = [[(5, 1.0, 2.0, 0.0, 0.0, 0.0)]]
    with pytest.raises(RecordError) as err:
        load_record(_tiny_record(tmp_path, frames, _ACTORS))
    assert err.value.code == "corrupt"


def test_record_with_a_non_finite_position_is_corrupt(tmp_path):
    """A NaN position would poison every distance the fact extractor computes."""
    frames = [[(0, float("nan"), 2.0, 0.0, 0.0, 0.0)]]
    with pytest.raises(RecordError) as err:
        load_record(_tiny_record(tmp_path, frames, _ACTORS))
    assert err.value.code == "corrupt"


def test_record_declaring_fewer_samples_than_it_holds_is_corrupt(tmp_path):
    """The sample count is the manifest's claim about the binary; it is checked as one."""
    with pytest.raises(RecordError) as err:
        load_record(_tiny_record(tmp_path, _FRAMES, _ACTORS, counts={"samples": 3}))
    assert err.value.code == "corrupt"


def test_record_naming_a_uid_twice_is_corrupt(tmp_path):
    """Two actors under one uid would merge two bodies into one track."""
    twice = [{"uid": "person:a", "kind": "person"}, {"uid": "person:a", "kind": "person"}]
    with pytest.raises(RecordError) as err:
        load_record(_tiny_record(tmp_path, _FRAMES, twice))
    assert err.value.code == "corrupt"


def test_record_with_a_malformed_manifest_is_corrupt(tmp_path):
    """A manifest missing its clock must be refused at the door with a typed error."""
    d = _tiny_record(tmp_path, _FRAMES, _ACTORS)
    man = load(d / "record_manifest.json")
    del man["clock"]
    dump(d / "record_manifest.json", man)
    with pytest.raises(RecordError) as err:
        load_record(d)
    assert err.value.code == "corrupt"


def test_record_actor_without_a_uid_is_a_typed_refusal(tmp_path):
    """A malformed actor table is a corrupt record, not a KeyError in the caller's lap."""
    with pytest.raises(RecordError) as err:
        load_record(_tiny_record(tmp_path, _FRAMES, [{"kind": "person"}, {"kind": "vehicle"}]))
    assert err.value.code == "corrupt"


def test_record_manifest_that_is_not_an_object_is_a_typed_refusal(tmp_path):
    """A parseable but wrong-shaped manifest must be refused with a typed error."""
    d = _tiny_record(tmp_path, _FRAMES, _ACTORS)
    (d / "record_manifest.json").write_text("[]", encoding="utf-8")
    with pytest.raises(RecordError) as err:
        load_record(d)
    assert err.value.code == "corrupt"


def test_real_record_copy_loads(factory_pkg, factory_recs, tmp_path):
    """Proves the damaged copies below are refused for their damage, not for being copies."""
    d = _copy_record(factory_pkg, tmp_path)
    man = load(d / "record_manifest.json")
    assert man["binary"]["bytes"] == (d / "frames.bin").stat().st_size
    assert factory_recs["baseline"].frames_sha256 == man["binary"]["sha256"]
    assert factory_recs["baseline"].frame_count == man["clock"]["frame_count"]
    assert len(factory_recs["baseline"].tracks) == len(man["actors"])


def test_flipped_byte_in_frames_bin_is_corrupt(factory_pkg, tmp_path):
    """One flipped bit moves one body; the record must not hash to its manifest any more."""
    d = _copy_record(factory_pkg, tmp_path)
    with (d / "frames.bin").open("r+b") as f:
        f.seek((d / "frames.bin").stat().st_size // 2)
        byte = f.read(1)
        f.seek(-1, 1)
        f.write(bytes([byte[0] ^ 0x01]))
    with pytest.raises(RecordError) as err:
        load_record(d)
    assert err.value.code == "corrupt"
    assert err.value.stage == "record"


def test_truncated_frames_bin_is_corrupt(factory_pkg, tmp_path):
    """A record cut short must be a refusal, never a quietly shorter track."""
    d = _copy_record(factory_pkg, tmp_path)
    with (d / "frames.bin").open("r+b") as f:
        f.truncate((d / "frames.bin").stat().st_size - 24)
    with pytest.raises(RecordError) as err:
        load_record(d)
    assert err.value.code == "corrupt"


def test_manifest_declaring_one_more_frame_is_corrupt(factory_pkg, tmp_path):
    """The binary still hashes; only parsing it to the declared frame count catches this."""
    d = _copy_record(factory_pkg, tmp_path)
    man = load(d / "record_manifest.json")
    man["clock"]["frame_count"] += 1
    dump(d / "record_manifest.json", man)
    with pytest.raises(RecordError) as err:
        load_record(d)
    assert err.value.code == "corrupt"


def test_missing_frames_bin_is_missing(factory_pkg, tmp_path):
    """Missing must be told apart from corrupt: one is re-run, the other is investigated."""
    d = _copy_record(factory_pkg, tmp_path, frames=False)
    with pytest.raises(RecordError) as err:
        load_record(d)
    assert err.value.code == "missing"


def test_missing_record_manifest_is_missing(tmp_path):
    """A record directory with no manifest is absent evidence, not an empty record."""
    with pytest.raises(RecordError) as err:
        load_record(tmp_path)
    assert err.value.code == "missing"


@pytest.mark.parametrize("change", [
    {"format": "simulation_record_v2"},
    {"binary_layout": {"sample_struct": "<Iffffff"}},
    {"binary_layout": {"frame_header_struct": "<H"}},
], ids=["format", "sample_struct", "frame_header_struct"])
def test_unknown_record_format_is_bad_format(factory_pkg, tmp_path, change):
    """A record in another layout must not be parsed with this layout's struct."""
    d = _copy_record(factory_pkg, tmp_path, frames=False)
    man = load(d / "record_manifest.json")
    man["binary"].update(change.pop("binary_layout", {}))
    man.update(change)
    dump(d / "record_manifest.json", man)
    with pytest.raises(RecordError) as err:
        load_record(d)
    assert err.value.code == "bad_format"


def test_trim_segments_cuts_both_ends_of_a_polyline():
    """The junction zones are cut by arc length along the whole line, across its corner."""
    ell = [(0.0, 0.0, 100.0, 0.0), (100.0, 0.0, 100.0, 100.0)]
    assert trim_segments(ell, 30.0) == [(30.0, 0.0, 100.0, 0.0), (100.0, 0.0, 100.0, 70.0)]
    assert trim_segments(ell, 0.0) == ell
    # a trim longer than the first leg removes that leg and eats into the next
    long_ell = [(0.0, 0.0, 100.0, 0.0), (100.0, 0.0, 100.0, 400.0)]
    assert trim_segments(long_ell, 150.0) == [(100.0, 50.0, 100.0, 250.0)]


def test_trim_segments_of_a_line_too_short_to_trim_is_empty():
    """A street shorter than its two junction zones has no middle; it must not invert."""
    ell = [(0.0, 0.0, 100.0, 0.0), (100.0, 0.0, 100.0, 100.0)]
    assert trim_segments(ell, 100.0) == []
    assert trim_segments(ell, 120.0) == []
    assert trim_segments([(5.0, 5.0, 5.0, 5.0)], 0.0) == []      # zero-length segment


def test_dist_to_segments_is_the_distance_to_the_nearest_point():
    """Perpendicular inside the span, to the end point outside it, nearest segment wins."""
    seg = [(0.0, 0.0, 100.0, 0.0)]
    assert dist_to_segments(50.0, 40.0, seg) == 40.0
    assert dist_to_segments(-30.0, 40.0, seg) == 50.0             # 3-4-5 to the start point
    assert dist_to_segments(130.0, -40.0, seg) == 50.0            # and to the end point
    assert dist_to_segments(20.0, 0.0, seg) == 0.0
    ell = seg + [(100.0, 0.0, 100.0, 100.0)]
    assert dist_to_segments(90.0, 50.0, ell) == 10.0              # the second leg is nearer
    assert dist_to_segments(8.0, 9.0, [(5.0, 5.0, 5.0, 5.0)]) == 5.0   # a degenerate segment
    assert dist_to_segments(1.0, 1.0, []) == math.inf


def test_track_index_at_and_slice_follow_the_frame_numbers():
    """An actor absent for some frames must read as absent there, not as its neighbour."""
    t = Track("person:x", "person")
    for f in (3, 4, 7, 8):
        t.frames.append(f)
        t.x.append(float(f))
        t.y.append(0.0)
        t.yaw.append(0.0)
        t.speed.append(0.0)
    assert len(t) == 4
    assert [t.index_at(f) for f in (3, 4, 7, 8)] == [0, 1, 2, 3]
    assert [t.index_at(f) for f in (0, 5, 6, 9)] == [-1, -1, -1, -1]
    assert t.slice(4, 7) == range(1, 3)                           # inclusive at both ends
    assert t.slice(5, 6) == range(2, 2) and len(t.slice(5, 6)) == 0
    assert t.slice(0, 2) == range(0, 0)
    assert t.slice(0, 100) == range(0, 4)
    assert len(Track("person:empty", "person").slice(0, 100)) == 0


# --------------------------------------------------------------------------
# facts on the real episode
# --------------------------------------------------------------------------

#: Sources a fact may cite that are NOT artefacts of the sealed simulation
#: result: the result and the rule manifest themselves, the locked world and
#: its route files, and the replicate simulations.
NON_ARTEFACT_SOURCES = {"replicates", "route_files", "rule_manifest", "simulation_result", "world"}

HEADLINE = {
    "walkers_followed": 24,
    "walkers_planned_through": 18,
    "walkers_changed_route": 18,
    "walkers_changed_route_without_rule": 0,
    "cars_never_started": 12,
    "cars_rerouted": 48,
    "cars_asked_to_reroute": 57,
    "cars_found_no_other_way": 9,
    "cars_stood_until_moved": 9,
    "cars_teleported_with_rule": 9,
    "cars_teleported_without_rule": 0,
    "cars_on_closed_block_with_rule": 0,
    "cars_on_closed_block_without_rule": 69,
    "avg_duration_s_without_rule": 130.76,
    "avg_duration_s_with_rule": 165.59,
    "prediction_outcome": "confirmed",
    "seeds_used": 1,
    "all_runs": 3,
}


def test_sealed_facts_round_trip_through_disk(factory_facts, tmp_path):
    """The document the story reads from disk must be the one the extractor sealed."""
    assert factory_facts["schema_version"] == FACTS_SCHEMA
    verify_seal(factory_facts, "facts_hash", "facts")
    write_json(tmp_path / "facts.json", factory_facts)
    assert load_facts(tmp_path / "facts.json") == factory_facts


def test_facts_carry_the_lineage_of_the_evidence_they_were_read_from(factory_facts, factory_pkg,
                                                                      factory_brief):
    """Facts that do not name their brief, result, manifest and ledger cannot be audited."""
    sim = load(factory_pkg / "sim" / "simulation.json")
    result = load(factory_pkg / "sim" / "simulation_result.json")
    assert factory_facts["brief_sha256"] == brief_hash(factory_brief) == sim["brief_sha256"]
    assert factory_facts["simulation_result_hash"] == result["result_hash"]
    assert factory_facts["rule_manifest_hash"] == sim["rule_manifest_hash"]
    assert factory_facts["ledger_hash"] == sim["ledger_hash"]
    assert factory_facts["artifacts"] == {k: v["sha256"] for k, v in result["artifacts"].items()}
    assert factory_facts["records"] == {
        arm: result["artifacts"][f"{arm}_record_frames"]["sha256"] for arm in ("baseline", "ruled")}


def test_every_cross_check_agrees(factory_facts):
    """A sealed fact sheet holding a disagreement would mean the refusal did not fire."""
    checks = factory_facts["cross_checks"]
    assert len(checks) >= 10
    assert [c["name"] for c in checks if c["agree"] is not True] == []


@pytest.mark.parametrize("name,value", sorted(HEADLINE.items()), ids=sorted(HEADLINE))
def test_headline_value_is_pinned(factory_facts, name, value):
    """A silent change in the instrument would change what the film says; pin what it measured."""
    assert factory_facts["facts"][name]["value"] == value


def test_every_fact_states_its_value_unit_sources_and_method(factory_facts):
    """A fact without a source or a method is a bare number, which the audit cannot resolve."""
    known = set(factory_facts["artifacts"]) | NON_ARTEFACT_SOURCES
    assert len(factory_facts["facts"]) > 60
    for name, fact in factory_facts["facts"].items():
        assert set(fact) == {"value", "unit", "from", "how"}, name
        assert isinstance(fact["unit"], str) and fact["unit"], name
        assert isinstance(fact["how"], str) and len(fact["how"]) > 10, name
        assert fact["from"] and fact["from"] == sorted(fact["from"]), name
        assert set(fact["from"]) <= known, (name, fact["from"])
        v = fact["value"]
        assert isinstance(v, (int, float, str, bool)), name
        if isinstance(v, float):
            assert math.isfinite(v) and v == round(v, 3), name


def test_non_artefact_sources_are_the_closed_set(factory_facts):
    """A new source name appearing in `from` must be a decision, not a typo that resolves nowhere."""
    cited = {s for f in factory_facts["facts"].values() for s in f["from"]}
    assert cited - set(factory_facts["artifacts"]) == NON_ARTEFACT_SOURCES
    assert not NON_ARTEFACT_SOURCES & set(factory_facts["artifacts"])


def test_treatment_and_control_partition_the_walkers(factory_facts):
    """An agent in both groups, or in neither, would make the comparison meaningless."""
    g = factory_facts["groups"]
    assert len(g["walkers"]) == 24 and len(set(g["walkers"])) == 24
    assert len(g["treatment"]) == 18 and len(g["control"]) == 6
    assert not set(g["treatment"]) & set(g["control"])
    assert set(g["treatment"]) | set(g["control"]) == set(g["walkers"])
    assert not set(g["other_people"]) & set(g["walkers"])
    assert factory_facts["facts"]["walkers_not_through"]["value"] == 6


def test_replicates_are_other_seeds_of_the_same_rule(factory_facts, factory_brief):
    """'Three runs' must mean three seeds; a repeat of the episode's own seed is one run."""
    reps = factory_facts["replicates"]
    assert [r["seed"] for r in reps] == sorted(factory_brief["replicate_seeds"])
    assert factory_brief["seed"] not in [r["seed"] for r in reps]
    assert len({r["simulation_result_hash"] for r in reps}
               | {factory_facts["simulation_result_hash"]}) == 3
    assert factory_facts["facts"]["repeat_runs"]["value"] == 2
    assert factory_facts["facts"]["all_runs_same_direction"]["value"] == \
        1 + sum(1 for r in reps if r["direction"] == factory_facts["prediction"]["measured"])


def test_extraction_is_deterministic(factory_facts, factory_pkg):
    """Re-extracting from the same sealed evidence must give the hash sealed in the package."""
    on_disk = load_facts(factory_pkg / "facts.json")
    assert factory_facts["facts_hash"] == on_disk["facts_hash"]
    assert factory_facts == on_disk


def test_load_facts_refuses_an_edited_or_foreign_document(factory_facts, tmp_path):
    """A fact edited after sealing, or a document of another schema, must not be read as facts."""
    doc = copy.deepcopy(factory_facts)
    doc["facts"]["cars_never_started"]["value"] = 0
    write_json(tmp_path / "edited.json", doc)
    with pytest.raises(FactsError) as err:
        load_facts(tmp_path / "edited.json")
    assert (err.value.stage, err.value.code) == ("facts", "corrupt_evidence")
    write_json(tmp_path / "foreign.json", {**factory_facts, "schema_version": "episode_facts_v0"})
    with pytest.raises(FactsError) as err:
        load_facts(tmp_path / "foreign.json")
    assert err.value.code == "bad_version"
    with pytest.raises(FactsError) as err:
        load_facts(tmp_path / "absent.json")
    assert err.value.code == "missing"


# --------------------------------------------------------------------------
# facts fail closed
# --------------------------------------------------------------------------

def _refusal(sim_dir: Path, brief: dict, world: dict, **kw) -> FactsError:
    with pytest.raises(FactsError) as err:
        extract_facts(sim_dir, brief, world, **kw)
    assert err.value.stage == "facts"
    return err.value


def _flip_byte(path: Path, offset: int | None = None) -> None:
    with path.open("r+b") as f:
        f.seek(path.stat().st_size // 2 if offset is None else offset)
        byte = f.read(1)
        f.seek(-1, 1)
        f.write(bytes([byte[0] ^ 0x01]))


def test_missing_sealed_artefact_is_missing_evidence(factory_pkg, factory_brief, factory_world,
                                                     tmp_path):
    """A deleted tripinfo must refuse the episode, not yield facts without trip statistics."""
    sim = copy_sim(factory_pkg, tmp_path)
    (sim / "ruled.tripinfo.xml").unlink()
    assert _refusal(sim, factory_brief, factory_world).code == "missing_evidence"


def test_missing_simulation_document_is_refused(factory_brief, factory_world, tmp_path):
    """An empty directory is not a simulation; the refusal comes from the facts stage."""
    assert _refusal(tmp_path, factory_brief, factory_world).code == "missing"


def test_flipped_byte_in_a_record_is_corrupt_evidence(factory_pkg, factory_brief, factory_world,
                                                      tmp_path):
    """A record that no longer hashes to the sealed result must not be measured."""
    sim = copy_sim(factory_pkg, tmp_path)
    _flip_byte(sim / "record_ruled" / "frames.bin")
    assert _refusal(sim, factory_brief, factory_world).code == "corrupt_evidence"


def test_artefact_changed_without_resealing_is_corrupt_evidence(factory_pkg, factory_brief,
                                                                factory_world, tmp_path):
    """The naive tamper: one number changed in the agent log, the sealed hash left alone."""
    sim = copy_sim(factory_pkg, tmp_path)
    doc = load(sim / "agents_ruled.json")
    doc["teleports"] = 0
    dump(sim / "agents_ruled.json", doc)
    assert _refusal(sim, factory_brief, factory_world).code == "corrupt_evidence"


def test_simulation_of_another_brief_is_stale_lineage(factory_pkg, factory_brief, factory_world):
    """Facts must not be extracted for a brief the simulation was not run from."""
    other = normalise_brief({**factory_brief, "title": "What happens when two streets close?"})
    assert brief_hash(other) != brief_hash(factory_brief)
    assert _refusal(factory_pkg / "sim", other, factory_world).code == "stale_lineage"


def test_result_edited_without_resealing_is_seal_broken(factory_pkg, factory_brief, factory_world,
                                                        tmp_path):
    """An edited sealed result must be refused before any artefact it names is trusted."""
    sim = copy_sim(factory_pkg, tmp_path)
    result = load(sim / "simulation_result.json")
    result["seed"] += 1
    dump(sim / "simulation_result.json", result)
    assert _refusal(sim, factory_brief, factory_world).code == "seal_broken"


def test_rule_manifest_edited_without_resealing_is_seal_broken(factory_pkg, factory_brief,
                                                               factory_world, tmp_path):
    """A prediction rewritten after the run must break the manifest's seal."""
    sim = copy_sim(factory_pkg, tmp_path)
    manifest = load(sim / "rule_manifest.json")
    manifest["prediction"]["direction"] = "decrease"
    dump(sim / "rule_manifest.json", manifest)
    assert _refusal(sim, factory_brief, factory_world).code == "seal_broken"


def test_insider_who_removes_a_reroute_event_and_reseals_is_refused(factory_pkg, factory_brief,
                                                                    factory_world, tmp_path):
    """Every hash verifies; only the record, which still shows 18 moved paths, can object."""
    sim = copy_sim(factory_pkg, tmp_path)
    doc = load(sim / "agents_ruled.json")
    at = next(i for i, e in enumerate(doc["events"]) if e["kind"] == "agent_rerouted")
    del doc["events"][at]
    assert sum(1 for e in doc["events"] if e["kind"] == "agent_rerouted") == 17
    dump(sim / "agents_ruled.json", doc)
    reseal_simulation(sim)
    assert _refusal(sim, factory_brief, factory_world).code == "conflicting_consequence"


def test_insider_who_fabricates_a_baseline_reroute_and_reseals_is_refused(
        factory_pkg, factory_brief, factory_world, tmp_path):
    """A baseline arm that reroutes is not a control; a resealed log must not hide that."""
    sim = copy_sim(factory_pkg, tmp_path)
    ruled = load(sim / "agents_ruled.json")
    base = load(sim / "agents_baseline.json")
    assert not [e for e in base["events"] if e["kind"] == "agent_rerouted"]
    fake = copy.deepcopy(next(e for e in ruled["events"] if e["kind"] == "agent_rerouted"))
    base["events"].append(fake)
    dump(sim / "agents_baseline.json", base)
    reseal_simulation(sim)
    assert _refusal(sim, factory_brief, factory_world).code == "uncontrolled_arms"


def test_insider_who_hides_a_stuck_vehicle_and_reseals_is_refused(factory_pkg, factory_brief,
                                                                  factory_world, tmp_path):
    """Nine cars stood for the whole teleport limit in the record; a list of eight contradicts it."""
    sim = copy_sim(factory_pkg, tmp_path)
    doc = load(sim / "agents_ruled.json")
    assert len(doc["vehicles_not_rerouted"]) == 9
    doc["vehicles_not_rerouted"] = doc["vehicles_not_rerouted"][1:]
    dump(sim / "agents_ruled.json", doc)
    reseal_simulation(sim)
    assert _refusal(sim, factory_brief, factory_world).code == "conflicting_consequence"


def test_insider_who_rewrites_counts_in_the_cited_agent_log_and_reseals_is_refused(
        factory_pkg, factory_brief, factory_world, tmp_path):
    """Facts citing `ruled_agents` must agree with that artefact, not with a copy of it elsewhere."""
    sim = copy_sim(factory_pkg, tmp_path)
    doc = load(sim / "agents_ruled.json")
    doc["teleports"] = 0
    doc["vehicle_reroutes_changed"] = 0
    doc["vehicle_reroutes_attempted"] = 0
    dump(sim / "agents_ruled.json", doc)
    reseal_simulation(sim)
    _refusal(sim, factory_brief, factory_world)


def test_episode_passed_as_its_own_replicate_is_uncontrolled(factory_pkg, factory_brief,
                                                             factory_world):
    """Counting the episode's own seed again as a 'repeat' would inflate 'N of N runs agree'."""
    err = _refusal(factory_pkg / "sim", factory_brief, factory_world,
                   replicate_dirs=[factory_pkg / "sim"])
    assert err.code == "uncontrolled_arms"


def _effect(metric: str, baseline: float, ruled: float, extractor: str) -> dict:
    return {"change_type": "measured_effect",
            "payload": {"metric": metric, "baseline_value": baseline, "ruled_value": ruled,
                        "delta": round(ruled - baseline, 4), "unit": "s"},
            "provenance": {"extractor": extractor}}


def test_ledger_effects_reads_measured_effects_and_ignores_other_entries():
    """Only `measured_effect` entries are measurements; a declared change is not one."""
    ledger = {"entries": [{"change_type": "edge_closure", "payload": {"edge_ids": ["B1B2"]}},
                          _effect("avg_duration_s", 130.76, 165.59, "closure_v1"),
                          _effect("avg_waiting_time_s", 10.0, 30.0, "closure_v1")]}
    out = ledger_effects(ledger)
    assert sorted(out) == ["avg_duration_s", "avg_waiting_time_s"]
    assert out["avg_duration_s"] == {"baseline": 130.76, "ruled": 165.59, "delta": 34.83,
                                     "unit": "s", "extractor": "closure_v1"}
    assert ledger_effects({"entries": []}) == {}


def test_ledger_effects_refuses_two_extractors_that_disagree():
    """Two measurements of one metric that differ: neither may be picked silently."""
    ledger = {"entries": [_effect("avg_duration_s", 130.76, 165.59, "closure_v1"),
                          _effect("avg_duration_s", 130.76, 150.00, "agents_v1")]}
    with pytest.raises(FactsError) as err:
        ledger_effects(ledger)
    assert (err.value.stage, err.value.code) == ("facts", "conflicting_consequence")


def test_ledger_effects_accepts_identical_duplicates():
    """Two extractors that agree are corroboration, not a conflict; the first is kept."""
    ledger = {"entries": [_effect("avg_duration_s", 130.76, 165.59, "closure_v1"),
                          _effect("avg_duration_s", 130.76, 165.59, "agents_v1")]}
    out = ledger_effects(ledger)
    assert list(out) == ["avg_duration_s"]
    assert out["avg_duration_s"]["extractor"] == "closure_v1"
    assert (out["avg_duration_s"]["baseline"], out["avg_duration_s"]["ruled"]) == (130.76, 165.59)
