# Render Export Format V1

## Purpose

A render export is the deterministic, consumer-neutral projection of one
verified persisted episode. It is the boundary artifact between the
simulation engine and every future visual layer: a downstream renderer reads
authoritative world meaning from it without knowing anything about simulation
internals, and the engine never learns what a renderer did with it.

It is **not** a second save format. The episode save remains the only
canonical engine truth; a render export is a reproducible derived artifact
that can always be regenerated from its verified source.

## Read-only by construction

An export is produced only from `SaveManager.load_episode(episode)`, which
verifies the requested episode and its **complete ancestry** — file digests,
canonical encoding, state-hash lineage, semantic reconstruction, and memory
history — before anything is projected. A corrupted episode, or a corrupted
ancestor beneath it, is not exportable merely because its JSON parses.

Producing an export:

- mutates no domain object, no save file, and nothing under the save root;
- draws zero values from the world's random generator;
- may never write its output to a destination that resolves inside the save
  root, and never overwrites an existing destination.

## Top-level shape

Exactly these six keys, no more:

```json
{
  "format": "living_diorama_render_export",
  "schema_version": 1,
  "source": {},
  "world": {},
  "events": [],
  "memory": {}
}
```

`schema_version` is the **render export** schema version. It is independent
of the persistence schema version and the two must never be conflated.

## `source` — provenance of the verified episode

Exactly: `engine_version`, `episode`, `tick`, `state_hash`,
`parent_state_hash`, `event_count`, `entity_counts`.

Every value is copied from the episode's **verified manifest**:
`engine_version` is the version that wrote the source episode (not the
version currently running), `state_hash` is the verified hash of the source
`world_state.json`, and `parent_state_hash` is `null` for episode 0 and a
64-character lowercase SHA-256 hex string otherwise. `entity_counts` carries
exactly `districts`, `boundaries`, `walls`, `laws`, `infrastructure`, and
each count equals the length of the matching `world` array.

There are no timestamps, no filesystem paths, no hostnames, no interpreter
versions, and no generated identifiers. Nothing nondeterministic enters the
document.

## `world` — authoritative state, faithfully

Exactly five arrays: `districts`, `boundaries`, `walls`, `laws`,
`infrastructure`. Each entry is exactly what the locked persistence
serializers produce for that entity, in the same canonical
sorted-by-identifier order. Districts carry their authoritative numbers
(population, resources, rates, scarcity, fear, trust, institutional
pressure, housing, isolation state) — never presentation labels. Boundary
endpoints keep their stored roles: `district_a_id` and `district_b_id` are
world identity and are never swapped or normalized. Walls keep their full
scar state (`permanent`, `integrity`, dependency scores); laws keep their
exact scalar semantics — `null`, `false`, `true`, `1`, `1.0`, and `"1"` are
six different values and stay that way.

The persistence-only top-level fields are deliberately absent: `episode` and
`tick` live under `source`, the persistence `schema_version` describes a
different format, and **`rng_state` never appears anywhere in a render
export** — engine continuation state is not visual state, and exporting must
not change what the next episode would do.

## `events` — raw history, in order

The source episode's own event log, exactly as the event serializer writes
it: each event is `{payload, source_id, tick, type}`, in **append order**.
Events are never sorted, merged, deduplicated, filtered, or summarized. The
order *is* the history; a later story layer decides emphasis, not this
format.

## `memory` — cumulative history, in order

Exactly: `through_episode`, `through_tick`, `facts`. The checkpoint comes
from the verified loaded `WorldMemory` and always equals the source episode
and tick. `facts` is the complete cumulative fact list in the exact canonical
order `WorldMemory` established — never re-sorted, rewritten, compacted, or
filtered. `WorldMemory` is already the engine's durable interpretation layer;
a render export transmits it, it does not reinterpret it.

## Determinism

The bytes are produced by the project's canonical JSON encoder: sorted keys,
compact separators, UTF-8, exactly one trailing newline. The same verified
source episode therefore produces byte-identical exports on every run, in
every interpreter, under every `PYTHONHASHSEED`. Two worlds that differ only
in RNG continuation state share identical `world`, `events`, and `memory`
sections — the visible domain state is RNG-invariant — while their
`source.state_hash` values still differ, because that hash describes the
persisted `world_state.json` bytes, which include continuation state. The
validator governs the envelope: the exact key sets, provenance types, and
cross-section agreements. The nested entity, event, and fact documents are
governed by the locked persistence serializers that produced them.

## What V1 deliberately does not contain

No positions, coordinates, transforms, cameras, materials, meshes, shaders,
textures, colors, frames, animation, shots, narration, or voice. Phase 14
exports authoritative **world meaning**; how entities map into persistent
visual space is the later master-scene layer's decision. The format is
renderer-independent: nothing in it assumes Blender, Godot, or any other
consumer.
