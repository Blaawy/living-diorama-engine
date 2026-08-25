# Episode Narration Plan V1

**NARRATION PLANNING RESTATES SELECTED TRUTH. IT DECIDES NOTHING.**

---

## 1. Why this layer exists

Phase 23 closed with an episode that is complete, verified, and silent about its
own most important content.

Its own documentation says where it stops:

> **No audio, no narration, no assembly.** Explicitly downstream.

And Phase 22, one layer above it, had already recorded something sharper. Two
beat kinds — `DURABLE_CONSEQUENCE` and `CONSEQUENCE_PERSISTED`, both `PRIMARY`,
both the direct expression of this project's promise that consequences are
permanent — are deliberately left **unshown**, because no approved camera can
see the memory register. The Phase 22 policy table says why in its own words:
framing an empty register "would be fabricated visibility", and pointing at the
monument while claiming to show the record would be "symbolism sold as proof".

That decision was right, and it left a hole. In the canonical chain's episode
1 → 2, the law comes back and the wall stays. The wall staying *is* the episode.
It is a `PRIMARY` beat, it is durably recorded, it is bound to an authoritative
fact — and it appears in exactly zero of the 192 rendered frames. An episode
could render, verify, and never mention it.

Words are the only honest way to close that gap. A camera cannot show what no
camera can see, but a sentence can say it without claiming anyone saw it.

Phase 24 writes those sentences, and binds each one to the record it restates.

## 2. Ownership

This layer owns one question: **given an emphasized story and a directed
episode, what truthful sentence restates each beat, and was the viewer shown
it?**

It owns: one narration unit per story beat, in the story's own order; the
sentence each unit carries and where that sentence came from; the visibility
each unit reports, copied from the direction; and the binding proving all of it
came from three specific documents.

It does **not** own emphasis, ranking, shot selection, cuts, cameras, the clock,
frame execution, captions, subtitles, voice, speech, audio, music, editing,
encoding, packaging, publishing, or any runtime language model. Those are
upstream decisions already made, or later concerns.

If Phase 24 disagrees with a valid upstream decision, it restates it.

## 3. Inputs

Three documents, all read as canonical bytes:

| Input | Contributes |
| --- | --- |
| **Episode Story Plan V1** | the beats, their kind, emphasis, subjects and evidence |
| **Shot Direction Plan V1** | whether each beat is shown, by which shot, over which frames — or unshown, and why |
| **Render Export V1** (current) | the memory layer's own recorded sentence for each fact-backed beat |

There is deliberately **no render manifest input**, and the reason is
architectural rather than mechanical. Narration authoring is a semantic layer:
Phase 21 owns what mattered and Phase 22 owns what is framed, and both are
settled before a single pixel exists. A manifest is *execution proof*, whose
per-frame image identities may legitimately differ between two renders of the
same directed episode. Binding narration identity to it would tie a semantic
document's stability to render execution for nothing narration needs. A
narration plan must survive a semantically identical re-render unchanged.

Joining these sentences to the frames a render actually produced is the later
realization layer's work, and the manifest is the document it is handed.

The **previous** export is not an input either. Every fact a transition beat
cites is new in the episode being described, every cited event lives in the
current export's array, and lineage between episodes was already proven by
Phase 21.

## 4. Output

One document, `living_diorama_episode_narration_plan`, schema version 1.

```json
{
  "accounting": {"beats_total": 2, "units_shown": 1, "units_unshown": 1},
  "format": "living_diorama_episode_narration_plan",
  "schema_version": 1,
  "source": {
    "current_export_sha256": "…",
    "episode": 2,
    "mode": "transition",
    "previous_episode": 1,
    "shot_plan_sha256": "…",
    "shot_schema_version": 1,
    "story_plan_sha256": "…",
    "story_schema_version": 1
  },
  "units": [
    {
      "beat_id": "beat_0001",
      "emphasis": "PRIMARY",
      "end_frame": null,
      "fact_id": "fact_0a8d4a3d…",
      "kind": "CONSEQUENCE_PERSISTED",
      "shot_id": null,
      "start_frame": null,
      "subject_ids": ["boundary_ab", "law_movement_sharing", "wall_boundary_ab"],
      "text": "Law \"law_movement_sharing\" (\"movement_resource_sharing\") was restored at tick 22; permanent wall \"wall_boundary_ab\" on boundary \"boundary_ab\", built at tick 9, remained in the world.",
      "text_source": "MEMORY_FACT_SUMMARY",
      "unit_id": "unit_0001",
      "unshown_reason": "NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE",
      "visibility": "UNSHOWN"
    },
    {
      "beat_id": "beat_0002",
      "emphasis": "SECONDARY",
      "end_frame": 144,
      "fact_id": null,
      "kind": "WALL_STATE_CHANGE",
      "shot_id": "shot_0002",
      "start_frame": 25,
      "subject_ids": ["wall_boundary_ab"],
      "text": "At tick 21, wall \"wall_boundary_ab\" changed state.",
      "text_source": "NARRATION_TEMPLATE",
      "unit_id": "unit_0002",
      "unshown_reason": null,
      "visibility": "SHOWN"
    }
  ]
}
```

That is the real episode 1 → 2 plan. The `PRIMARY` beat is the one nobody is
shown; the `SECONDARY` beat is the one that gets 120 frames. Both are stated.

## 5. The two text sources

A narration sentence exists in exactly one of two ways, and the difference is
the design.

**`MEMORY_FACT_SUMMARY`** — the two fact-backed kinds carry the memory layer's
own `summary` **verbatim**. The engine wrote that sentence when it recorded the
fact, from a fixed template, deliberately so that "a later narration phase reads
a stable, checkable string". Rewording it would replace a sentence the world
wrote about itself with a sentence this layer invented.

**`NARRATION_TEMPLATE`** — the five event-backed kinds and the empty-result beat
have no such sentence, so one is composed from a closed, versioned, total table.
The whole parameter surface is two structural values: the beat's sorted subject
identifiers, and the tick its authoritative evidence records. Event payloads are
never opened. The story layer refuses to branch on prose or interpret payload
internals; a narration layer mining `payload` for richer wording would assert
detail no upstream contract proved.

The V1 table, in full:

| Beat kind | Sentence |
| --- | --- |
| `LAW_CHANGE` | `At tick {tick}, law {subjects} changed.` |
| `LAW_RESTORATION` | `At tick {tick}, law {subjects} was restored.` |
| `WALL_RAISED` | `At tick {tick}, wall {subjects} was built.` |
| `WALL_STATE_CHANGE` | `At tick {tick}, wall {subjects} changed state.` |
| `POPULATION_MOVEMENT` | `At tick {tick}, district {subjects} recorded population movement.` |
| `NO_EMPHASIZED_BEATS` | `No beats were emphasized for this episode.` |

The wording is part of the schema version. Changing a template changes what a
plan of this version says, so it is a reviewed version change, never a quiet
edit.

The empty-result sentence says only what its beat says: that the emphasis policy
selected nothing. It must never be read, or written, as a claim that nothing
happened — an episode can publish hundreds of genuine telemetry events and still
emphasise none of them.

## 6. Wording safety

Two closed token lists apply to **every** V1 sentence, whatever its source.

**Causal**: `caused`, `because`, `therefore`, `led to`, `responsible for`,
`resulted in`, and the rest of the declared list. The memory layer already
refuses to write these into a summary; this layer refuses to publish them
whoever wrote them.

**Visual deixis**: `see`, `seen`, `shown`, `watch`, `view`, `camera`, `frame`,
`screen`, `visible`, and the rest. Whether a beat is on screen is Phase 22's
decision and lives in the `visibility` field, where a machine checks it against
the shot plan. Keeping it out of the sentence entirely is what makes it
*structurally impossible* for an unshown beat to be narrated as though the
viewer had just watched it. A sentence cannot fabricate visibility it has no
vocabulary for.

Matching is on whole words, with underscores treated as word characters, so an
entity named `frame_budget_district` is not a hit while the bare word `frame`
is. Subject identifiers are substituted into these sentences, and an entity
whose name merely contains a banned word must not make an honest sentence
unpublishable.

This layer restates a recorded sentence or it refuses. It never rewords one into
something it is willing to publish. **Known limitation:** an authoritative entity
identifier or fact summary that used a banned word as a whole word would stop
the derivation rather than be narrated. That is deliberate and fail-closed — it
means a human looks — and it has never occurred in the canonical chain.

## 7. Shown and unshown

| Case | `visibility` | `shot_id` / frames | `unshown_reason` |
| --- | --- | --- | --- |
| exactly one shot cites the beat | `SHOWN` | copied from that shot | `null` |
| the shot plan lists the beat unshown | `UNSHOWN` | `null` | copied from that entry |

Never fabricated in either direction. A shot span is copied from the citing shot
and checked for equality against it; an unshown reason is copied from the shot
plan's own entry. An unshown unit carries no shot and no frames, because the
beat occupies none.

Where a beat that nobody shows should land on a future audio timeline is a
*pacing* decision belonging to realization. Inventing one here would be this
layer manufacturing presentation truth.

**Merged shots.** When one shot cites several beats — Phase 22's adjacent-anchor
merge — each beat still gets its own unit. They share `shot_id`, `start_frame`
and `end_frame`; their identities are never merged.

**Establishing shots** cite no beats and produce no units. That is not a silent
drop: accounting is defined over beats, and every beat is accounted for.

## 8. Timing

Phase 17 owns the clock. Phase 22 owns shot windows. Phase 23 owns execution.

Phase 24 stores copied semantic frame spans for shown units and nothing else. No
fps, no seconds, no timestamps, no playback or witness vocabulary. Unit order is
the story plan's beat order, which Phase 22 already made identical to timeline
order — "shot order is Phase 21's rank order" — so rank order and presentation
order cannot disagree.

## 9. Accounting

Fail-closed, and provable from the document alone:

- exactly one unit per story beat, at the beat's own position
- `unit_0001` restates `beat_0001`, and so on: positional identifiers make a
  reorder, an omission and a duplicate all unrepresentable
- `units_shown + units_unshown == beats_total == len(units)`
- the accounting block is *measured* from the units present, never asserted
  beside them

Excluded and unclassified events are outside the unit universe by upstream
decision. Phase 21 owns significance, and its own accounting already proved
nothing was silently lost before narration ran.

## 10. Determinism

Same three documents, same bytes. Reads and writes go through the repository's
canonical codec, which already refuses `NaN`, infinities, overflowing literals,
duplicate object keys and non-round-tripping types, and emits sorted keys,
compact separators and exactly one trailing newline.

Identifiers are positional. Ordering is the story plan's. Wording is a
compile-time table. No clock, no randomness, no uuid, no environment, no
filesystem outside the CLI, no network, no model call — enforced structurally by
the boundary guard and asserted behaviourally across `PYTHONHASHSEED` 0, 1, 42
and 123456 in subprocesses.

## 11. Source binding

| Document | Bound as |
| --- | --- |
| story plan | `story_plan_sha256` over its canonical bytes |
| shot plan | `shot_plan_sha256` over its canonical bytes |
| current export | `current_export_sha256` over its canonical bytes |

Schema validity and relationship validity are separate, and kept in separate
modules. The schema proves everything the plan can prove about itself. The
cross-check proves the plan's claims are true of its sources: that the digests
name the documents offered, that `current_export_sha256` equals the story plan's
own `source.current.document_sha256`, that the shot plan directs exactly this
story plan, that versions, mode and episodes agree, that every beat is narrated
exactly once with its emphasis and subjects copied unchanged, that every unit's
visibility is what Phase 22 granted, and that every sentence is the sentence
those sources produce.

Then the seal: the plan is re-derived from the three sources and must equal it
byte for byte.

**Refuse, never repair.** Nothing here sorts an unsorted list, fills a missing
field, or trims a sentence.

## 12. Boundaries, enforced structurally

`tests/narration/test_phase24_boundary.py` proves, by parsing the sources rather
than by reading them:

- the layer imports only Phase 21's contracts, Phase 22's contracts, the render
  contract and the shared validation vocabulary
- it never imports `living_diorama.memory` — it reads memory facts *as
  exported*, exactly as the story layer does, because a second opinion about
  what durable memory is would be a second authority
- it never imports `living_diorama.render_execution`, Blender, the network, or
  any source of nondeterminism
- no pure module touches the filesystem; only the CLI reads or writes
- no module defines a name belonging to captions, audio, encoding, packaging,
  publishing, camera re-direction, citizen simulation, or a runtime model
- no module outside `narration_spec` inspects the content of a sentence: prose
  may be carried, never branched on
- exactly one module reads a fact's `summary`, and it carries it whole

Every guard is exercised against a deliberately bad synthetic file, because a
guard nobody has seen fail is a guard nobody has tested.

## 13. The language realization boundary

A future layer may **rephrase** a unit's sentence. It may never add a fact, drop
a unit, change an actor, a quantity or a tick, introduce causality, reorder the
plan, change emphasis, or turn an unshown beat into something the viewer was
shown.

The artifact that makes such a layer checkable is this plan. A realization binds
`narration_plan_sha256`, maps its output one-to-one onto `unit_id`, and can be
mechanically held to the structural invariants above. Any model belongs entirely
inside that later phase, downstream of this document, and is forbidden here.

## 14. Command

```
python -m living_diorama.cli.build_narration_plan \
    --story episode_story_plan_v1.json \
    --shots shot_direction_plan_v1.json \
    --export render_export_ep2.json \
    --output episode_narration_plan_v1.json
```

Inputs must be canonical bytes. The output is never overwritten. The plan is
cross-checked against all three sources before the file is written, so a
narration plan can never exist without its bindings having been proven. Exit 0
on success, 1 on refusal, with a message rather than a traceback.

## 15. Known limitations

- **One episode.** A plan narrates one baseline or one transition. Recognising a
  pattern across five episodes is a different layer's problem, as it is for
  Phase 21 and Phase 22.
- **No payload detail.** `POPULATION_MOVEMENT` says movement was recorded, not
  how many moved or where they went; those live in the event payload this layer
  does not open. Richer wording is a V2 question about which contract should
  expose that detail, not a licence to read it here.
- **One sentence per beat.** No unit combines beats, and none elaborates.
- **English only.** The template table is one language and says so; a second
  would be a schema version, not a runtime option.
- **No prose quality claim.** These sentences are correct and checkable, not
  well-written. Making them read well is exactly what a downstream realization
  layer is for, and it must prove it changed nothing.
- **A banned word in authoritative data stops the derivation.** See §6.
