"""Three canonical serialisers exist. They must produce the same bytes.

`world_state.canonical_bytes`, `persistent_changes._canonical` and
`evidence._canonical` each turn a document into the bytes a hash covers. They
were written at different times and nothing tied them together; a red-team
reviewer flagged that as a place two hashes of "the same" document could
silently disagree.

They are kept as three functions -- each blanks a different hash field and one
of them is part of a sealed Phase 1 contract -- but this file pins what they
share: for any document, the JSON encoding is identical. If someone changes the
separators, the key order, the ASCII escaping or the NaN rule in one of them,
this fails.

It also found a real difference, now closed: the world-state serialiser
accepted NaN and Infinity, which are not JSON, and would have sealed a state
containing one "successfully". All three refuse now.
"""
from __future__ import annotations

import json

import pytest

from ldyf import evidence as ev
from ldyf import persistent_changes as pc
from ldyf import world_state as ws

DOCS = [
    {},
    {"a": 1},
    {"b": 2, "a": 1, "c": {"z": [3, 2, 1], "y": None}},
    {"unicode": "café — 東京", "quote": 'he said "no"', "slash": "a\\b/c"},
    {"floats": [0.1, 1e-9, 1e21, -0.0, 2.5, 1.0, 100.0], "ints": [0, -1, 2 ** 53]},
    {"bools": [True, False], "nested": {"deep": {"deeper": {"deepest": [{"k": "v"}]}}}},
    {"empty": {"list": [], "dict": {}, "str": ""}},
    {"control": "tab\there\nnewline", "nul": "\u0000"},
]


def _bare(doc: dict) -> bytes:
    """What each serialiser is expected to reduce to once its hash field is set."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


@pytest.mark.parametrize("doc", DOCS)
def test_the_three_serialisers_agree_byte_for_byte(doc):
    # each blanks its own hash field, so give every document all three, blanked
    # the way each function blanks it, and compare what is left
    probe = dict(doc)
    ledger_bytes = pc._canonical(probe)
    assert ledger_bytes == _bare(probe)

    with_state = {**probe, "state_hash": "anything"}
    assert ws.canonical_bytes(with_state) == _bare({**probe, "state_hash": ws._EMPTY})

    with_seal = {**probe, "manifest_hash": "anything"}
    assert ev._canonical(with_seal, "manifest_hash") == _bare({**probe, "manifest_hash": ""})


@pytest.mark.parametrize("doc", DOCS)
def test_hashes_of_the_same_content_agree_across_serialisers(doc):
    """Same content, same blanked field, same sha256 -- whichever function ran."""
    import hashlib

    shaped = {**doc, "state_hash": ws._EMPTY}
    a = hashlib.sha256(ws.canonical_bytes({**doc, "state_hash": "x"})).hexdigest()
    b = hashlib.sha256(pc._canonical(shaped)).hexdigest()
    assert a == b


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_no_serialiser_will_hash_a_non_finite_number(bad):
    """NaN is not JSON. A serialiser that emits it seals something unreadable."""
    doc = {"value": bad}
    with pytest.raises((ValueError, pc.LedgerError)):
        pc._canonical(doc)
    with pytest.raises((ValueError, ev.EvidenceError)):
        ev._canonical({**doc, "manifest_hash": ""}, "manifest_hash")
    with pytest.raises(ValueError):
        ws.canonical_bytes({**doc, "state_hash": ""})


def test_key_order_never_changes_the_bytes():
    a = {"x": 1, "y": {"b": 2, "a": 1}}
    b = {"y": {"a": 1, "b": 2}, "x": 1}
    assert pc._canonical(a) == pc._canonical(b)
    assert ws.canonical_bytes({**a, "state_hash": ""}) == ws.canonical_bytes({**b, "state_hash": ""})
