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

The cumulative durable history: every significant fact the world has recorded
since episode 0, carried forward in full. A later episode's payload contains
everything the earlier ones did, so the newest save is self-contained as a
history even though loading an episode still requires its complete ancestry.

Persistence stores this; it does not judge it. Nothing in the save layer decides
significance, writes a summary, invents a fact, or drops one. The `memory`
package produces the history and this layer serializes it.

### Fact schema

Every entry carries exactly these keys:

```json
{
  "details": {},
  "episode": 0,
  "fact_id": "fact_...",
  "fact_type": "WALL_BUILT",
  "source_event_index": 18,
  "source_event_type": "WALL_BUILT",
  "source_id": "wall_boundary_ab",
  "subject_ids": ["boundary_ab", "district_a", "district_b", "wall_boundary_ab"],
  "summary": "Wall ...",
  "tick": 120
}
```

`source_event_index` is the event's zero-based position in the episode's
`event_log.json`. It is part of provenance: the bus permits identical events to
be published more than once, and equality alone cannot tell two occurrences
apart.

`subject_ids` are sorted and unique, so a query for an entity finds every fact
touching it regardless of the role it played. Roles stay in `details`, where
sorting cannot scramble which district was A and which was B.

### The two Phase 11 fact types

`WALL_BUILT` — a permanent wall was raised. Details:

```text
boundary_id, built_tick, district_a_id, district_b_id, permanent,
source_event_payload, wall_id
```

`LAW_RESTORED_WALL_PERSISTED` — a law was restored, and a permanent wall with
recorded build provenance, built strictly *before* that restoration tick, still
existed at the close of the episode. Details:

```text
boundary_id, law_current_value, law_id, law_name, law_previous_value,
restored_tick, source_event_payload, wall_active_at_episode_close,
wall_built_tick, wall_dependency_score_at_episode_close, wall_id,
wall_permanent, wall_resource_dependency_at_episode_close,
wall_transport_dependency_at_episode_close
```

This fact asserts only that both things were true. It never claims the law
caused the wall, that the wall caused the law, that the restoration strengthened
anything, or that the wall was active unless the recorded state says so. One
restoration may produce zero, one, or many such facts — one per qualifying wall,
in wall-identifier order.

The build-tick comparison is strictly `<`. A wall raised during the very tick a
law was restored was not already standing at the restoration moment, so it is
not described as having persisted through it.

`source_event_payload` is a detached, exact JSON copy of the original event
payload. Unfamiliar keys are carried, never dropped or reinterpreted.

### Deterministic fact identifiers

A fact's identifier is derived from its own content, never supplied:

```python
(
    "fact_"
    + sha256(
        json.dumps(
            identity_document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
)
```

The identity document holds `details`, `episode`, `fact_type`,
`source_event_index`, `source_event_type`, `source_id`, `subject_ids`, and
`tick` — not the identifier or the summary, which would make identity circular.
There is **no trailing newline** in the bytes hashed for a fact, unlike a save
file. The `memory` package implements this encoding itself rather than borrowing
the persistence codec, so a fact's identity cannot shift if the save framing ever
changes.

### Deterministic summaries

`summary` is structured prose from a fixed template, not generated text.
Identifiers are quoted with `json.dumps(identifier, ensure_ascii=False,
allow_nan=False)`.

```text
Wall {wall} was built on boundary {boundary} between districts {a} and {b} at tick {tick}; it was marked permanent.

Law {law} ({name}) was restored at tick {tick}; permanent wall {wall} on boundary {boundary}, built at tick {built_tick}, remained in the world.
```

On load, both the identifier and the summary are recomputed from the semantic
content and compared with what the file records. A document whose stored id or
wording disagrees with what its own content implies is rejected rather than
trusted — hashes agreeing does not make a fact loadable.

### Canonical fact ordering

Facts are ordered by:

```text
(episode, tick, source_event_index, fact_type, fact_id)
```

Chronological first, then by the position of the event that produced them, so a
tick that produced several facts replays in the order the engine emitted them. A
loaded memory that is not already in this order is **rejected, never silently
sorted**: reordering would hide that the file came from somewhere else while
changing what the history says happened first.

### Memory lineage: the inherited prefix

World-state lineage proves an episode descends from its parent's *state*. It says
nothing about the parent's *history*, so both are enforced:

```text
current_memory.facts[:len(previous_memory.facts)] == previous_memory.facts
```

Exact and ordered. A child episode may **append only**. It may not drop, rewrite,
replace, reorder, or insert among the facts it inherited, change their summaries,
details, identifiers, or provenance, or reset memory to empty. Without this a
child could forget everything the world remembered and every hash, byte length,
and state-lineage check would still pass.

The suffix — the facts a child adds — must be exactly what that episode's own
events require, and each one is checked against the event it names:

```text
fact.source_event_index  is within the episode log
fact.source_event_type   == event.type
fact.tick                == event.tick
fact.source_id           == event.source_id
fact.details["source_event_payload"] == event.payload_as_dict()
```

The event is resolved by **index**, not by equality: the bus permits identical
events to be published more than once, and only the position tells two
occurrences apart.

Coverage is exact in both directions. Every `WALL_BUILT` event must produce
exactly one construction fact for its own index. Every `LAW_RESTORED` event must
produce exactly one persistence fact per qualifying wall and no others — zero
qualifying walls correctly produces zero facts. A non-significant event produces
none, and a fact its resolved event does not support is refused.

These checks run at **save time**, before anything touches the filesystem, and
again at **load time** for every episode in the ancestry walk. Correct hashes do
not make a false history loadable.

### World time never moves backward

A later episode may close at the same tick as its parent or later, never earlier:

```text
current_memory.through_tick >= previous_memory.through_tick
```

Enforced by the transition contract itself, not only where facts are appended. A
quiet episode adds nothing, so a rollback with nothing to append is exactly the
case that would otherwise slip through — in a save whose every byte, length,
hash, and state-lineage edge is correct.

### Exact identifier types

Every identifier a fact depends on is validated as being exactly a `str`, not
merely equal to one. That covers each entity's own `id`, each typed registry key
as it is actually stored, the aggregate-index key, and every reference between
them: `wall.boundary_id`, `boundary.wall_id`, and both district endpoints.

A `str` subclass hashes and compares like the string it copies, so a registry
lookup finds it and an equality check accepts it. Without the exactness check
such a value would travel into a fact and into a save as something other than
the `str` the engine's stored-state contract requires. The stored key is
therefore located and inspected as itself rather than trusted because a lookup
succeeded.

`fact_id` and `summary` are checked the same way when a document is read, before
being compared with the recomputed values.

### Typed registries must hold real domain entities

Before any entity-specific field is read, the object a typed registry holds is
required to be an instance of the class that registry is for — `Wall`,
`Boundary`, `District`, `Law`. Carrying matching attribute names is not
sufficient: an object that merely answers to `id` and `built_tick` has had none
of the validation those classes perform, so a durable fact derived from it would
record state the engine never agreed to. This matches what the Phase 10
serializers already require.

The check is `isinstance`, not an exact type comparison. Subclassing a domain
entity is not prohibited by any existing contract, and inventing that
prohibition here would be a rule nobody agreed to.

Only the entities a fact actually depends on are validated: the walls, boundary,
districts, and law reached through `WALL_BUILT`, `LAW_RESTORED_WALL_PERSISTED`,
and remembered-wall topology. Unrelated world entities are not scanned.

### Every event used by memory must carry a real EventType

Each entry in the episode log is checked as it is walked:

```text
type(event.type) is EventType
```

A malformed event type is an **error**, not a nonsignificant event. Only real
members of `EventType` are eligible to be classified as significant or
nonsignificant. A plain string, a `str` subclass, a `StrEnum` member spelling the
same name, `None`, a `bool`, a number, an unrelated enum member, and an arbitrary
object are all rejected — including values that spell a *nonsignificant* type,
because treating one as such would let a corrupt log read as an uneventful
episode that recorded nothing.

Nothing is converted: `"WALL_BUILT"` does not become `EventType.WALL_BUILT`.

### MemoryFact document keys must be exact ordinary strings

Every key a fact document exposes is checked before missing and unexpected keys
are computed:

```text
type(key) is str
```

Equality and hashing make a `str` subclass or a `StrEnum` member behave exactly
like the key it copies, so set arithmetic and lookups both succeed and nothing
downstream notices that the save was read through keys the format does not
permit. Iteration is what is inspected, not membership: a mapping may expose one
key while answering lookups with another, and the exposed keys are the document's
actual shape.

Keys are not coerced with `str()`, and no corrected dictionary is built. A
document whose keys are not exact strings is refused as it stands.

### A fact document is read exactly once

Checking the keys is necessary but not sufficient. Nothing obliges a mapping to
answer the same way twice, so one that exposed ordinary keys while being checked
and `str` subclasses afterwards would pass the check and still be read through
keys the format forbids. Validating and then re-reading proves nothing about the
reading that matters.

Reconstruction therefore takes a single snapshot. The caller's mapping is
iterated once, each key is validated as it is exposed, and every subsequent
step — the missing-and-unexpected comparison and every field lookup — works from
that snapshot rather than from the original. Validation and reconstruction are
guaranteed to be looking at the same document because there is only one.

Values are carried across untouched, keys are never coerced, a key exposed twice
is refused, and a rejected mapping is left exactly as it was.

### Cross-fact provenance

Every `LAW_RESTORED_WALL_PERSISTED` fact must rest on exactly one earlier
`WALL_BUILT` fact for the same wall, appearing earlier in canonical order, and
agreeing with it on `wall_id`, `boundary_id`, and the build tick — which must be
strictly earlier than the restoration. An orphan persistence fact would let a
memory assert its own unproven origin: history invented backwards from a
conclusion. This is checked when a memory is constructed, when it is advanced,
when it is deserialized, and during transition validation.

### Quiet episodes still validate history

On every episode — including one in which nothing happened — each remembered
`WALL_BUILT` fact is re-checked against the world: the wall exists under a
canonical key matching its own id, is still exactly `permanent`, has the recorded
build tick, its boundary exists and points back at it, no second wall claims that
boundary, and both district endpoints exist, are distinct, and are the ones the
fact recorded. A quiet episode does not suspend history validation.

### One episode, one event-log snapshot

An `EventLog` is a mutable object owned by the caller, so asking it for its
history twice is asking twice rather than reading twice. Every public operation
captures exactly one snapshot and uses that tuple for all of its work.

For distillation this means chronology verification, fact generation, provenance
checks, and coverage checks all consume the same history. Candidate V4 read the
log five times during one distillation, and a log that answered differently each
time could be classified against one history and validated against another: a
malformed event visible only to fact generation was never type-checked, and an
episode could be recorded as having produced a fact its own chronology never saw.
With one snapshot an event either counts for everything in that operation or for
nothing.

Transition validation follows the same rule. The entry point taking an
`EventLog` captures one snapshot and delegates to an internal path that operates
directly on the tuple, so no nested helper can reacquire a different history
partway through.

### A container snapshot is not a semantic snapshot

Capturing `tuple(event_log.events())` freezes *which* objects the operation will
use. It does not freeze what those objects say. `Event`, `WorldMemory`, and
`MemoryFact` are all accepted by `isinstance`, so a subclass may legitimately
arrive — and a subclass can answer one way while a save is being validated and
another way while it is being written.

That is enough to publish an episode the same implementation refuses to load: an
event whose payload changed after validation leaves `event_log.json` contradicting
the provenance recorded in `world_memory.json`; a memory whose `facts` emptied
after validation leaves a stored history that its own events do not support; a
fact overriding `to_document()` writes a summary its content does not imply.

Every public boundary therefore **normalizes** its inputs into exact base-domain
objects before anything is validated or written:

- Each event field — `tick`, `type`, `source_id`, `payload_as_dict()` — is read
  once and a plain `Event` is rebuilt from the captured values. Occurrence order
  and duplicate occurrences are preserved; no caller-owned Event survives. The
  captured `source_id` is validated **before** the base Event is rebuilt: it must
  be `None` or exactly a `str` that is non-blank and carries no surrounding
  whitespace (internal whitespace stays legal). The base constructor's own
  stripping never runs on snapshot input, so a padded or subclassed identifier
  is refused as it stands — never normalized into a clean one it did not report.
- `WorldMemory` has `through_episode`, `through_tick`, and `facts` read once, and
  is rebuilt through the ordinary constructor so ordering, duplicate identifiers,
  cross-fact provenance, and the checkpoint are re-established on the object that
  will actually be used.
- Each `MemoryFact` has its semantic fields read once and is rebuilt. The rebuilt
  fact derives its own identifier and summary, and the values the caller claimed
  must match them. The claimed `fact_id` and `summary` are required to be **exact
  plain strings** before they are compared — the same standard
  `MemoryFact.from_document` applies to a persisted document — because equality
  alone would accept a `str` subclass, a `StrEnum` member, or any object whose
  `__eq__` chooses to agree. A malformed derived field is refused as it stands,
  never silently replaced with the normalized one. `__eq__`, `to_document()`, and
  `details_as_dict()` are never trusted across phases — only the normalized
  object's own `to_document()` can reach disk.

The first semantic read is authoritative. After normalization the caller's
objects are never consulted again, so a successful save is loadable regardless of
what those objects do afterwards.

Event and memory snapshots alone are still not sufficient, because the `World`
they are validated against remains a live object. That gap is closed by the
authoritative world snapshot below.

`serialize_world_memory()` normalizes for itself rather than trusting its caller,
because it is public and may be called directly.

### Saving what was validated

`save_episode()` reads the caller's log once, then builds a detached `EventLog`
holding exactly those events in exactly that order. Memory-transition validation
and event-log serialization both run against the detached copy, and the
manifest's `event_count` is the length of the same snapshot. The caller's log is
never read again, and neither it nor its events are modified.

The guarantee is one snapshot, not a restriction on the type of log accepted:
`EventLog` is itself mutable, so requiring an exact class would not help.

This is what keeps three numbers in agreement for every saved episode:

```text
manifest.event_count
== len(event_log.json["events"])
== len(the snapshot memory was validated against)
```

Without it, a log that changed mid-save could be validated as holding one event,
serialized as holding none, and counted as none — publishing an episode whose
memory recorded a fact the stored history could not support. The writer never
publishes a save that its own loader rejects.

### The authoritative world snapshot

Normalizing events and memory closes only half of the writer/loader gap. A save
also reads the caller-owned `World` — its episode, its tick, its registries, and
every entity field a memory fact depends on — and `World` and its entities all
accept legitimate subclasses. A `Wall` whose `permanent` answered `True` while
memory was validated and `False` while `world_state.json` was written left the
two halves of a published episode disagreeing; a `World` whose `tick` advanced
between checkpoint matching and the manifest silently turned a memory processed
through tick 120 into one checkpointed to 121 on reload.

`save_episode()` therefore consults the live world exactly once, at the top:

```text
caller-owned World
↓
one world_state document          (serialize_world, which validates first)
↓
strict reconstruction             (deserialize_world, into an exact base World)
↓
all remaining validation and metadata use that reconstructed World
```

The reconstruction step is required. `serialize_world()` validates the aggregate
and builds the document, but a stateful subclass may change between those
internal reads — so the produced document is itself reconstructed, proving that
the actual bytes headed for disk describe a world this implementation would
load. When reconstruction fails, no save is published and nothing on the
filesystem is touched.

Everything after the capture reads the reconstructed base world: the episode
number, the destination directory, the parent lookup, memory checkpoint
matching, memory-transition validation, event-log episode and tick validation,
entity counts, and every manifest field. `world_state.json` is the **exact
captured document that passed reconstruction** — the world is never serialized a
second time. The caller's `World` is not consulted again after the capture, so a
caller-owned `World` or entity subclass cannot change what the save means
between memory validation and serialization: whatever single snapshot the
serializer captured is the whole truth the episode is judged by.

The invariant this establishes:

```text
Every successful save can immediately be loaded
by the same SaveManager implementation.
```

A stateful adversary earns one of two honest outcomes — a refusal before any
filesystem mutation (no episode directory, no staging residue, the parent and
the generator untouched), or a coherent episode that reloads to the same world,
event log, memory, and checkpoint semantics that were validated. Publishing an
unloadable episode, or one whose memory comes back checkpointed to a moment the
caller never processed, is not an outcome.

### Exact law state

Before a restoration is believed, `law.active`, `law.changed_episode`, and
`law.restored_tick` are checked for **exact type** and then compared. `True == 1`,
so an equality-only check would accept a boolean where an episode number or a tick
belongs. Law scalars keep the existing contract: `None`, exact `bool`, exact
`int`, finite `float`, or `str` — no enums, no subclasses, no coercion.

### Multi-wall fact ordering

One restoration may produce several persistence facts. Qualifying walls are
traversed in wall-identifier order for determinism, and the resulting facts are
then sorted into canonical memory order before being appended. Those two orders
are **not** the same: every canonical sort field before `fact_id` is equal for
facts from a single event, so the tie falls to a SHA-256 digest, which has no
reason to agree with an alphabetical wall list.

### Hashability

`MemoryFact` and `WorldMemory` are both hashable. A fact hashes by its derived
`fact_id`, which already summarizes its entire content, so equal facts always
hash equally. A memory hashes by its checkpoint and the ordered tuple of its fact
identifiers. Neither uses a generated implementation: both would traverse the
read-only mappings inside `details`, which are not hashable, and would fail the
moment a caller first put one in a set.

### Cumulative and append-only

Nothing removes, replaces, rewrites, merges, or reorders a fact. Duplicate
identifiers are refused, and so is a second claim that the same wall was built.
There is no compaction, no retention limit, no summarization of old facts, and
no deduplication by similarity in this MVP.

### Checkpoints live on the object, not in the file

The Python `WorldMemory` records how far it has been processed
(`through_episode`, `through_tick`). Those fields are deliberately **not** in
`world_memory.json`: the manifest already states the authoritative episode and
tick, and writing them twice would create two sources of truth that could drift
apart. On load, persistence supplies the verified manifest values.

Saving requires the memory's checkpoint to match the captured world snapshot
exactly — the episode and tick the world-state document actually records, which
are the values the loader will later hand back. A mismatch fails before any
filesystem mutation — otherwise the two halves of a save could describe
different moments, and every hash and lineage check would still pass.

### Phase 10 placeholder compatibility

The empty Phase 10 document remains loadable and becomes a memory holding
nothing, checkpointed to the episode it was saved in. Backward compatibility
with arbitrary opaque fact objects is not offered; none was ever produced.

### What this layer still does not do

No narration is generated, no causality is inferred, and no fact is ranked or
interpreted. `MemoryQuery.narration_context()` returns the stored deterministic
summaries and nothing else.

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
