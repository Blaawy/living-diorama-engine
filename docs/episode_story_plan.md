# Episode Story Plan — Phase 21

**STORY EMPHASIS IS PRESENTATION METADATA, NOT AUTHORITATIVE WORLD TRUTH.**

Phase 21 converts authoritative episode history into a deterministic,
source-traceable **Episode Story Plan** describing what downstream presentation
should emphasize.

It decides emphasis, not truth. It renders nothing, narrates nothing, changes no
simulation state, moves no camera, and creates no world fact.

---

## 1. Why this layer exists

Render Export V1 already says whose job this is:

> `docs/render_export_format.md` — "Events are never sorted, merged, deduplicated,
> or summarized. The order *is* the history; a later story layer decides
> emphasis, not this format."

And Phase 17 already declined it:

> `docs/motion_time.md` — "No camera direction, shot selection, or cut grammar …
> No story compiler, narration, audio, editing or packaging."

Before Phase 21 the episode's raw event log crossed into presentation and nothing
read it. Which of 318 events matters was a question the architecture asked and
never answered. This layer answers it.

---

## 2. Ownership

Phase 21 owns exactly one responsibility:

> **Which authoritative events and memory facts should downstream presentation
> pay attention to, and in what order?**

It does **not** own camera movement, camera selection, shot ordering, cuts,
lenses, framing, the final edit, audio, subtitles, voiceover, narration, or
packaging. Those are downstream consumers of the plan. Phase 17's cinematic
timeline remains locked and is not redefined here.

---

## 3. Inputs

Phase 21 consumes **Render Export V1 only**. It does not reach back into
simulation internals, and it does not require Blender. Given Python and two
export files, the whole layer is testable.

| Mode | Input | Meaning |
| --- | --- | --- |
| `baseline` | one export, **episode 0 only** | the world before anything happened |
| `transition` | two exports | describes the step from one episode to the next |

**A baseline describes episode 0 and no other episode.** Durable memory is
cumulative, so episode 2's export still carries episode 1's `WALL_BUILT` fact. A
baseline treats every carried fact as new, so building one for a later episode
would report old history as if it had just happened — and would date the wall to
the wrong episode. Asking for a baseline after episode 0 is refused, and the
refusal names the remedy: supply the previous export and get a transition.

For a transition the pair is proven consecutive before anything else happens.

---

## 4. Lineage: what is checked before a transition is described

Filenames and argument order are not evidence. Both documents are validated
against the Render Export V1 envelope first — Phase 21 reuses that contract
rather than holding a second, weaker opinion — and then:

- both declare the same render schema version
- `current.episode == previous.episode + 1`
- `current.parent_state_hash == previous.state_hash`
- the memory checkpoint does not go backwards
- the world keeps its identity: the district and boundary identifier sets are
  unchanged (walls are deliberately excluded — a wall appearing is exactly the
  history this layer exists to notice)

A mismatched pair is **refused, never repaired**. Reordering a pair to make it
fit would produce a plan describing a transition the world never took.

### Memory monotonicity

Durable memory is cumulative and append-only. The current episode's fact list
must begin with the previous episode's list, byte for byte under the canonical
encoder. A fact that vanished, moved, or was edited means the two documents are
not consecutive states of one world, and is refused. The facts new in this
episode are the suffix that remains.

---

## 5. Output

`episode_story_plan_v1.json`, format tag `living_diorama_episode_story_plan`,
schema version `1` — independent of the render and persistence schema versions.

```
{
  "format": "living_diorama_episode_story_plan",
  "schema_version": 1,
  "source": {
    "mode": "transition",
    "render_schema_version": 1,
    "current":  { "episode", "tick", "event_count",
                  "state_hash", "parent_state_hash", "document_sha256" },
    "previous": { ...same shape, or null for a baseline plan }
  },
  "beats": [ ... ],
  "excluded": { "<EVENT_TYPE>": { "count": N, "reason_code": "..." } },
  "unclassified": [ { "kind", "type", "reason_code" } ]
}
```

`document_sha256` is the digest of the export's **canonical** bytes.

The CLI refuses any input file whose bytes are not already their own canonical
encoding, so for file-driven use `document_sha256` is simultaneously the digest
of the canonical document and of the bytes actually on disk — a genuine
raw-byte binding, not a claim about one. A pretty-printed or key-reordered copy
of the same document is refused rather than silently re-serialized.

The in-memory API is deliberately more forgiving: it accepts any dictionary
carrying the document and is stable under key insertion order, because an object
in memory has no bytes of its own. It is the CLI that turns the digest into a
statement about a file.

### A beat

```
{
  "beat_id": "beat_0001",
  "rank": 1,
  "kind": "CONSEQUENCE_PERSISTED",
  "emphasis": "PRIMARY",
  "reason_code": "MEMORY_FACT_NEW",
  "subject_ids": ["boundary_ab", "law_movement_sharing", "wall_boundary_ab"],
  "evidence": [
    { "kind": "memory_fact", "fact_id": "fact_0a8d…", "fact_type": "LAW_RESTORED_WALL_PERSISTED",
      "episode": 2, "tick": 22, "source_id": "law_movement_sharing" },
    { "kind": "event", "index": 23, "type": "LAW_RESTORED", "tick": 22,
      "source_id": "law_movement_sharing" }
  ]
}
```

**A story beat means: "downstream presentation should pay attention to this
authoritative thing."** It does *not* mean "the simulation says this thing is
emotionally or morally important." World truth remains owned by simulation,
persistence, and render export.

---

## 6. Traceability

Every beat cites at least one structural reference, and every reference resolves
in the source export:

- **event evidence** cites the event's **index in the canonical array**. The
  index *is* the reference. Render Export defines the events array as append-order
  history, so position carries meaning a sort would destroy, and two events
  sharing a tick remain distinguishable.
- **memory fact evidence** cites `fact_id`, plus the fact's own type, episode and
  tick.

The one exception is `NO_EMPHASIZED_BEATS`, which reports that nothing was
selected and is required to cite **nothing** — citing a record would contradict
it.

### A fact's source event reference is proven, never assumed

A durable fact carries `source_event_index`: the position of the event it came
from **in the event array of the episode that recorded it**. That index is
episode-scoped, and this is the trap. In the canonical chain the episode-1
`WALL_BUILT` fact is still carried in episode 2's cumulative memory, still
pointing at index 61 — which in episode 2's array is an unrelated
`SOCIAL_STABILITY_CHANGED` event, about a different district, at a different
tick. Following it would attach a confidently wrong citation to the beat.

**Every** newly appended fact is validated before it is classified — shape,
episode, and source-event agreement — and only then is its type looked up. Doing
it the other way round would let an unrecognised future fact type walk past these
checks simply by being unrecognised, and "we do not know what this is" is not a
reason to stop asking whether it is well formed.

A new fact must declare the episode being described. Its reference is then
followed, and the referenced event must agree with the fact on all of:

- the index is within this episode's event array
- `event.type == fact.source_event_type`
- `event.source_id == fact.source_id`
- `event.tick == fact.tick`
- and, for a *known* fact type only, `source_event_type` is the one that fact
  type must derive from (`WALL_BUILT` ← `WALL_BUILT`,
  `LAW_RESTORED_WALL_PERSISTED` ← `LAW_RESTORED`)

The referenced event's own `type`, `source_id` and tick are validated with the
canonical validators **before** any comparison, so equality is never asked to do
a type check: `True == 1` in Python, and a boolean tick would otherwise satisfy
an integer one on a pair of unrecognised types that nothing downstream inspects.

An unrecognised fact type is held to every check except the last — no guessed
semantic mapping is applied to it — and, having proven itself structurally sound,
degrades neutrally into `unclassified`. It does not absorb its source event:
nothing absorbs an event on behalf of a beat that does not exist.

Any dangling, malformed, or mismatched reference is **refused**, not ignored. A
citation that cannot be proven is worse than no citation, because it looks like
evidence.

The event array is never sorted, filtered, or rewritten. Only the derived beat
list is ordered.

### The plan proves its own arithmetic

`validate_episode_story_plan` requires:

```
unique event citations + sum(excluded counts) + unclassified event entries
    == source.current.event_count
```

Every event in the episode is emphasised, set aside, or unrecognised — exactly
once. Memory-fact citations are not events and are not counted. An event index
may be cited by at most one beat: one event is one moment, and two beats citing
it would be the same moment reported twice. This is the identity the external
proof audit checks, enforced inside the contract as well so a consumer can trust
a plan without reopening the render export.

---

## 7. The emphasis policy

Deterministic, finite, and small enough to read in one sitting. It lives in
`story_spec.py` as a rule table, not as scattered conditionals.

### Memory fact rules

| fact type | beat kind | emphasis |
| --- | --- | --- |
| `WALL_BUILT` | `DURABLE_CONSEQUENCE` | PRIMARY |
| `LAW_RESTORED_WALL_PERSISTED` | `CONSEQUENCE_PERSISTED` | PRIMARY |

### Event rules

| event type | beat kind | emphasis | repeat policy |
| --- | --- | --- | --- |
| `LAW_CHANGED` | `LAW_CHANGE` | PRIMARY | every |
| `LAW_RESTORED` | `LAW_RESTORATION` | PRIMARY | every |
| `WALL_BUILT` | `WALL_RAISED` | PRIMARY | every |
| `WALL_CHANGED` | `WALL_STATE_CHANGE` | SECONDARY | first per subject |
| `POPULATION_MIGRATED` | `POPULATION_MOVEMENT` | SECONDARY | first per subject |

### Deliberate exclusions

`RESOURCE_PRODUCED`, `RESOURCE_CONSUMED`, `RESOURCE_TRANSFERRED`,
`SCARCITY_CHANGED`, `SOCIAL_STABILITY_CHANGED`,
`INSTITUTIONAL_PRESSURE_CHANGED`, `INFRASTRUCTURE_ADAPTED` — reason
`HIGH_FREQUENCY_TELEMETRY`. These fire every tick for every district. They are
the world's telemetry, not its story. **They are counted in `excluded`, never
silently dropped**: a reviewer can see exactly how much was set aside and why.

### Facts outrank events

When a memory fact names the event it came from (`source_event_index`), that
event is **absorbed** into the fact's beat rather than emitting a second, weaker
beat about the same moment. An absorbed event is cited as evidence, so it is not
also counted as excluded — counting it in both buckets would make the plan's own
arithmetic contradict itself.

### Repeat suppression

The wall in the canonical chain publishes `WALL_CHANGED` twelve times in one
episode as its dependency score climbs. A viewer needs to be told once that the
wall's state is moving. The first occurrence per subject earns a beat; the rest
are counted under `REPEAT_SUPPRESSED`.

### Unknown types degrade neutrally

A type the table does not know is **never given invented semantics**. It lands in
`unclassified` with `UNKNOWN_EVENT_TYPE` or `UNKNOWN_FACT_TYPE` and contributes
no beat. A future build that adds an event type will therefore produce an
honest, slightly-thinner plan rather than a confidently wrong one.

### Ordering

Beats are sorted strongest-first by a total order derived entirely from the beat
itself: emphasis weight, then earliest evidence tick, then earliest event index,
then beat kind, then first subject id. There are no ties left to chance, so a
consumer taking the first N beats always gets the N most emphasised. `rank` and
`beat_id` are assigned after ordering and must agree with position.

---

## 8. An empty plan, versus a consequence still standing

These are different results and the plan distinguishes them by **kind**:

- `NO_EMPHASIZED_BEATS` — the emphasis policy selected nothing. This is a
  statement about *this layer's output* and nothing more. It is **not** a claim
  that the world was still: an episode can publish hundreds of genuine
  authoritative telemetry events and still emphasise none of them, and the
  `excluded` tally reports exactly how many were set aside and why. What the
  world did is the simulation's to assert, not this layer's.
- `CONSEQUENCE_PERSISTED` — backed by the `LAW_RESTORED_WALL_PERSISTED` durable
  fact: an earlier consequence remained after the initiating condition changed.

This distinction is drawn from **structured memory evidence**, never inferred
from prose. It is the reason the layer exists: in the canonical chain the law
returns and the damage does not lift, and the honest render of that moment is
almost nothing moving. The plan still says the wall is standing.

## 9. Refusals

| Condition | Response |
| --- | --- |
| Either document fails the Render Export V1 envelope | refused |
| Exports not consecutive, or reversed | refused |
| `parent_state_hash` does not join the chain | refused |
| Memory checkpoint went backwards | refused |
| District or boundary identifier set changed | refused |
| Durable memory shrank, was reordered, or was edited | refused |
| A repeated `fact_id` | refused |
| Unknown beat kind, emphasis, or reason code in a plan | refused |
| A beat with no evidence, or a no-change beat with evidence | refused |
| `rank` disagreeing with position, or beats out of emphasis order | refused |
| Missing or extra keys at any governed level | refused |
| A baseline requested for any episode after 0 | refused |
| A fact reference that is out of range for this episode | refused |
| A fact reference whose event type, subject, or tick disagrees | refused |
| A known fact type naming the wrong source event type | refused |
| `render_schema_version` this build does not read | refused |
| A transition binding non-consecutive episodes, or a broken hash chain | refused |
| A baseline plan whose bound episode is not 0 | refused |
| (CLI) an input file that is not canonical render export bytes | refused |
| A new fact of any type, known or unknown, failing shape/episode/reference checks | refused |
| A duplicate or noncanonical district or boundary identifier | refused |
| A plan with no beats at all | refused |
| A `beat_id` that is not the positional form `beat_NNNN` | refused |
| An event-derived beat not citing exactly one event of its kind's type | refused |
| A fact-derived beat not citing exactly one fact plus the event it names | refused |
| An event evidence index outside `0 <= i < event_count` | refused |
| An event evidence tick after the episode's closing tick | refused |
| The same event index cited by two beats | refused |
| A plan whose event accounting does not balance | refused |
| A source event whose own type, `source_id`, or tick is not canonical | refused |
| An event-derived beat naming any subject other than its event's `source_id` | refused |
| An `unclassified` entry naming a type the policy actually has a rule for | refused |

Nothing is repaired. A malformed input is loudly broken rather than quietly wrong.

---

## 10. Determinism

The derivation is a pure function of its inputs. It reads no clock, draws no
randomness, consults no filesystem path, and depends on no iteration order Python
is free to vary.

- canonical serialization via `dumps_canonical` — sorted keys, tight separators,
  `allow_nan=False`, exactly one trailing newline
- no timestamps, paths, hostnames, or host-specific metadata
- no non-deterministic identifiers: `beat_id` is positional, assigned after the
  final ordering is fixed
- proven byte-identical across `PYTHONHASHSEED` values `0`, `1`, `42`, `123456`,
  each in its own interpreter
- proven byte-identical when the input dictionaries are rebuilt in a different
  key order

---

## 11. Boundaries, enforced structurally

`tests/story/test_phase21_boundary.py` proves by AST inspection that the story
layer:

- never imports Blender (`bpy`, `bmesh`)
- never imports live simulation (`entities`, `events`, `memory`, `simulation`,
  `systems`)
- reaches only an explicit allowlist of engine modules — the render contract and
  the persistence validation vocabulary
- never reaches a private name in another package
- never imports `random`, `secrets`, `time`, `datetime`, `uuid`
- never imports any network or model client
- never writes into the documents it reads
- never touches the filesystem outside the CLI entry point
- never references a save root or save manager
- defines no camera, shot, narration, prose, or citizen-level vocabulary
- never reads a memory `summary` — prose may be carried, never branched on

Each guard is also exercised against deliberately bad synthetic files, and
against innocent files that must **not** trip it. A guard nobody has seen fail is
a guard nobody has tested.

---

## 12. Usage

```bash
python -m living_diorama.cli.build_story_plan \
    --current render_export_ep2.json \
    --previous render_export_ep1.json \
    --output episode_story_plan_v1.json
```

Omit `--previous` for a baseline plan — episode 0 only. Like the render
exporter, the command never overwrites an existing output file, and it refuses
any input that is not canonical render export bytes.

Library use:

```python
from living_diorama.story import build_episode_story_plan_document

plan = build_episode_story_plan_document(current_export, previous_export)
```

---

## 13. Downstream consumers

The plan is written for layers that do not exist yet:

- a **cinematic direction** layer, which would decide what to point the camera at
  and for how long — the emphasis ordering is exactly the input shot selection
  needs
- a **narration** layer (`living_diorama/narration/`, still an empty reserved
  package), which would turn emphasised facts into language
- **editing and packaging**, further downstream still

Nothing consumes the plan today. That is expected: this layer exists so that
those layers have a principled upstream instead of inventing significance rules
of their own.

---

## 14. Known limitations

- **Two durable fact types exist**, `WALL_BUILT` and
  `LAW_RESTORED_WALL_PERSISTED`, so the strongest evidence class is small. The
  plan is as rich as the memory vocabulary allows and no richer.
- **No world-state diffing.** Beats are derived from events and memory facts.
  Comparing `previous.world` against `current.world` field by field would widen
  what can be emphasised, but every such claim needs an exact authoritative field
  path behind it, and that was left out of V1 rather than approximated.
- **Emphasis is three levels.** PRIMARY / SECONDARY / BACKGROUND is deliberately
  coarse; a finer scale would imply a precision the rule table does not have.
- **No cross-episode arcs.** A plan spans at most one transition. Recognising a
  pattern across five episodes is a different layer's problem.
- **`excluded` is keyed by type, not by index.** The counts are exact, but the
  plan does not enumerate which individual telemetry events were set aside.
- The repeat policy is **first-per-subject**, not first-and-last. If a value's
  final resting point matters downstream, that is a V2 question.
