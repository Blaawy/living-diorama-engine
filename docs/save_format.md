# Save Format — Schema Version 1

This document describes the on-disk format the persistence layer reads and
writes. It is the contract between one episode and the next: Episode N+1 begins
from exactly the world Episode N left behind, and every claim a save makes
about itself is verifiable without trusting the process that wrote it.

## Layout

A save root holds one directory per episode:

```
saves/
├── episode_000/
│   ├── manifest.json
│   ├── world_state.json
│   ├── event_log.json
│   └── world_memory.json
├── episode_001/
│   └── ...
```

Directory names are `f"episode_{episode:03d}"`, so numbers past three digits
simply grow (`episode_1000`). The episode number is an exact non-negative
`int`; `bool` is refused.

A completed episode directory contains exactly those four regular files. No
subdirectories, symbolic links, staging leftovers, or extra files are accepted
on load.

## Canonical encoding

Every file is written by one function:

```python
(
    json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    + b"\n"
)
```

Keys are sorted at every depth and separators are compact, so the bytes depend
on the data and never on the order a mapping happened to be built in. Each file
ends with exactly one newline.

On load, every file is re-encoded through this same function and the result
must equal the exact bytes read. Hashes alone are not enough: they catch a
payload that was reformatted and left with its old digest, but not one that was
reformatted and had the manifest updated to match — and nothing authenticates
the manifest. A save has exactly one representation.

Reading is deliberately stricter than `json.loads`. A save is refused if it
contains duplicate object keys (Python would silently keep the last one),
`NaN`, `Infinity`, `-Infinity`, a numeric literal that overflows to infinity,
trailing content after the document, invalid UTF-8, or a non-string object key.
Tuples, sets, enums, dataclasses, paths, and `int`/`str` subclasses are refused
on the way out, because each would encode into something that no longer loads
back as the same Python type.

A save contains no timestamp, no random identifier, and no filesystem path.

## Hashing

SHA-256, recorded as 64 lowercase hexadecimal characters, computed over the
exact bytes on disk rather than over the parsed document. A payload that has
been reformatted carries the same meaning but different bytes and therefore
fails verification — which is the point.

```
state_hash == SHA-256(exact bytes of world_state.json)
           == manifest.files["world_state.json"].sha256
```

`manifest.json` is not hashed by itself.

## manifest.json

```json
{
  "engine_version": "0.0.1",
  "entity_counts": {
    "boundaries": 0,
    "districts": 0,
    "infrastructure": 0,
    "laws": 0,
    "walls": 0
  },
  "episode": 0,
  "event_count": 0,
  "files": {
    "event_log.json": {"bytes": 0, "sha256": "..."},
    "world_memory.json": {"bytes": 0, "sha256": "..."},
    "world_state.json": {"bytes": 0, "sha256": "..."}
  },
  "format": "living_diorama_episode",
  "parent_state_hash": null,
  "python_version": "3.13.x",
  "schema_version": 1,
  "state_hash": "...",
  "tick": 0
}
```

`python_version` is recorded for diagnosis only and never gates loading. It is
the one field that may legitimately differ between two otherwise identical
saves, so manifest bytes are not required to match across interpreter patch
versions. Payload bytes and hashes are.

## Load verification order

Domain objects are constructed only after every check below has passed, so a
corrupt episode never becomes a half-real world:

1. Directory exists, is a directory, is not a symlink.
2. Directory holds exactly the four expected regular files.
3. Manifest parses strictly and declares `format` and `schema_version` 1.
4. Each payload's byte length matches the manifest.
5. Each payload's SHA-256 matches the manifest.
6. `state_hash` matches the world-state payload hash.
7. Manifest `episode` and `tick` match the world state.
8. Manifest `entity_counts` match the world-state arrays.
9. Manifest `event_count` matches the event log.

Every file is additionally required to be in canonical form (step 3 onward),
and the parent link is verified before any domain object is constructed.

An unsupported `schema_version` fails explicitly. No migration is attempted:
guessing the shape of an unknown version is how a save becomes silently wrong
rather than loudly broken.

## Lineage

Episode 0 records `parent_state_hash: null`. For every later episode:

```
parent_state_hash == state_hash of episode N-1
```

The parent is loaded and fully verified when the child is saved, and the hash
is copied from that verified manifest. A caller-supplied parent hash is never
accepted.

`load_episode(N)` verifies the **entire ancestry**, not only the last link.
Every episode from 0 up to N is walked in ascending order and fully verified —
directory shape, canonical bytes, lengths, digests, manifest schema, and full
semantic reconstruction of the world, event log, and memory document — with each
link compared against the manifest the walk has just verified.

Checking only the direct parent's files is not enough, and the difference is not
theoretical. A parent's envelope can be perfectly intact while its world fails
topology validation, its event log records a different episode, or its memory
document is malformed; the parent would be unloadable and the child would load
anyway. And a parent whose own parent link is wrong is itself unloadable, so a
child descending from it descends from nothing this save root can account for.

Episode 0 must record no parent; every later episode must record one, and each
ancestor must exist and verify completely. An episode is loadable only when the
whole chain behind it is.

The walk is iterative and visits each ancestor exactly once, so episode numbering
has no ceiling imposed by recursion depth. Ancestors are released as soon as
their link is checked; only the requested episode is returned. Nothing is
written, no event is published, and no randomness is drawn.

Saving episode N inherits this: the parent is loaded, which now verifies the
full chain behind it before its `state_hash` is copied into the new manifest.

`verify_lineage(parent, child)` requires `child == parent + 1`, independently
verifies both episodes, and compares the recorded hash against the parent's
own. A mismatch modifies nothing on disk.

## world_state.json

```json
{
  "boundaries": [],
  "districts": [],
  "episode": 0,
  "infrastructure": [],
  "laws": [],
  "rng_state": {},
  "schema_version": 1,
  "tick": 0,
  "walls": []
}
```

Entity arrays are sorted by identifier, so registry insertion order cannot
change the bytes or the hash. Event history is **not** sorted — its order is
the history.

### District

```json
{
  "consumption_rate": 0.0,
  "created_tick": 0,
  "fear": 0.0,
  "housing_capacity": 0,
  "id": "district_a",
  "institutional_pressure": 0.0,
  "isolation_state": "OPEN",
  "population": 0,
  "production_rate": 0.0,
  "resources": {"ENERGY": 0.0, "FOOD": 0.0, "MATERIALS": 0.0},
  "scarcity": 0.0,
  "trust": 0.0
}
```

`isolation_state` is one of `OPEN`, `PARTIAL`, `ISOLATED`. All three resource
keys are always present, even at zero.

### Boundary

```json
{
  "created_tick": 0,
  "district_a_id": "district_a",
  "district_b_id": "district_b",
  "id": "boundary_ab",
  "wall_id": null
}
```

Endpoint roles are preserved exactly and never normalized into alphabetical
order: which district is A is part of the world's identity.

### Wall

```json
{
  "active": true,
  "boundary_id": "boundary_ab",
  "built_tick": 20,
  "created_tick": 20,
  "dependency_score": 0.55,
  "id": "wall_boundary_ab",
  "integrity": 1.0,
  "permanent": true,
  "resource_dependency": 0.4,
  "transport_dependency": 0.55
}
```

Dependency fields round-trip exactly. Persistence never decays or recomputes
them, and an inactive permanent wall stays inactive and permanent.

### Infrastructure

```json
{
  "boundary_id": "boundary_ab",
  "capacity": 100.0,
  "created_tick": 0,
  "degraded": false,
  "dependency_score": 0.4,
  "id": "route_ab",
  "infrastructure_type": "TRANSIT_ROUTE"
}
```

`infrastructure_type` is one of `TRANSIT_ROUTE`, `RESOURCE_ROUTE`, `HOUSING`,
`CIVIC_SERVICE`.

### Law

```json
{
  "active": true,
  "changed_episode": 0,
  "created_tick": 0,
  "current_value": true,
  "id": "resource_sharing",
  "name": "Resource Sharing",
  "previous_value": null,
  "restored_tick": null
}
```

`previous_value` and `current_value` hold `null`, an exact `bool`, an exact
`int`, a finite `float`, or a `str`. The Python type is preserved: `true` never
becomes `1`, and `1` never becomes `"1"`. Lists, dicts, enums, and non-finite
numbers are refused.

### rng_state

The generator's own exported state, stored verbatim. Only the seed would not be
enough — resuming means continuing the sequence, not restarting it. On load a
generator is constructed with a placeholder seed and immediately given this
state. Nothing draws a number during save or load, because that would advance
the very sequence the save exists to preserve.

The document must carry exactly `state_format` and `random_state`.
`state_format` must be an exact `int` equal to `1`; `True` is refused even
though `True == 1`. Extra keys are refused. Restorability is proven by handing
the state to a throwaway generator, so a malformed `random_state` fails at save
time rather than at the start of the next episode. This is stricter than
`DeterministicRNG.set_state`, which is locked and unchanged: persistence
enforces the tighter save schema around it.

## event_log.json

```json
{
  "episode": 0,
  "events": [],
  "schema_version": 1
}
```

Each event:

```json
{
  "payload": {},
  "source_id": null,
  "tick": 0,
  "type": "RESOURCE_PRODUCED"
}
```

Append order, tick, type, nested payload values, and list order inside payloads
are all preserved exactly. Events are never sorted, deduplicated, merged, or
regenerated, and loaded events are appended to a fresh log rather than
published through an `EventBus` — they already happened.

An event's tick may not exceed the saved world tick, and this is enforced when
writing as well as when reading. A writer and reader that disagreed would
produce a save that could never be opened again. A `source_id` is *not*
required to resolve to a currently registered entity: history may name
something that no longer exists.

## world_memory.json

```json
{
  "facts": [],
  "schema_version": 1
}
```

Phase 10 carries this document; it does not understand it. When no memory is
supplied, the empty placeholder above is written. When one is supplied it must
have exactly these two keys, `schema_version` exactly `1`, and `facts` a list
of JSON-safe values. Fact order is preserved and nothing is filtered,
summarized, deduplicated, or generated. Loading returns a detached, read-only
copy.

Interpreting facts belongs to a later phase.

## Atomicity and immutability

A save is staged entirely in memory, written to a sibling staging directory,
flushed to disk, read back and compared byte-for-byte, and only then published.
The staging directory shares a filesystem with its destination, so publication
is atomic and a reader never sees a partial episode. On any failure the staging
directory is removed and the destination remains absent; cleanup never replaces
the original exception.

Publication uses an operating-system **no-replace** rename rather than
`os.rename`, which on POSIX silently replaces an empty destination directory. A
plain check-then-rename cannot close that window, so the guarantee is taken from
the kernel: `renameat2(RENAME_NOREPLACE)` on Linux, `renamex_np(RENAME_EXCL)` on
macOS, and the natively no-replace `MoveFileExW` behaviour on Windows. On any
other platform, or on a filesystem that does not support the operation,
publication fails explicitly rather than falling back to a rename that could
destroy a published episode.

The destination is also checked with `lexists` rather than `exists`, so a broken
symbolic link — which `exists` reports as absent — is recognized as an occupied
destination and raises `FileExistsError` with the link left untouched.

A published episode is immutable. Saving over one raises `FileExistsError`
rather than merging, repairing, replacing a single file, or overwriting.

## Validation of stored state

Entities remain mutable after construction, so constructor validation cannot
speak for their state at save time. Every stored value is validated exactly as
found and never repaired:

- Identifiers: exactly `str`, non-empty, not whitespace-only, and
  `value.strip() == value`. Internal whitespace such as `"north gate"` is
  legal; surrounding whitespace is not.
- Integer fields (`tick`, `episode`, `created_tick`, `built_tick`,
  `population`, `housing_capacity`, `changed_episode`, `restored_tick`) are
  exact `int`. `bool` is refused.
- Real-valued fields accept `int` or `float`, must be finite, and are written
  and loaded as `float`.
- Normalized fields must satisfy `0.0 <= value <= 1.0`.
- Flags are exactly `bool`; `0`, `1`, and `"true"` are refused.
- Enums must be the real member, not a string naming one.
- A `ResourcePool`'s stored key set must be exactly the `ResourceType` members.
  Serializing only the recognized keys would quietly drop a corrupted entry and
  write a repaired subset, so an unknown, missing, or mistyped key is refused.
- Manifest fields are checked for exact type before being compared. `True == 1`,
  so an equality-only check would accept a bool as the schema version.

The whole aggregate is verified before anything is written: registry keys equal
entity ids, identifiers are unique across all typed registries, every typed
entry resolves through the aggregate index to the same object, the index holds
no phantom entries, boundary endpoints exist and are distinct, wall and
boundary back-references agree, at most one wall stands on a boundary, and
every infrastructure entity points at an existing boundary.

## What this layer does not do

Loading a save runs no system, advances no tick, publishes no event, consumes
no randomness, and changes no law. Persistence has no opinion about what the
state means.

Not implemented here: world-memory interpretation, significance filtering,
`RuleSystem`, CLI orchestration, rendering, narration, databases, cloud
storage, compression, encryption, and migration between schema versions beyond
explicitly refusing unsupported ones.
