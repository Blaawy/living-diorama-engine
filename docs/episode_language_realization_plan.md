# The Episode Language Realization Plan (V1)

> Phase 26. Deterministic human-facing wording over a finished narration plan,
> proven from structure. **No timing, no audio, no captions, no model.**

## 1. Why this layer exists

The locked narration plan is correct and checkable, not well-written -- its own
contract says so, and says that making it read well is exactly what a
downstream realization layer is for. Its sentences quote internal identifiers
(`wall_boundary_ab`) that a voice would speak as run-on words, and its
fact-backed sentences restate machine-recorded summaries verbatim. This layer
produces the reviewed human-facing sentence for every unit -- one to one, in
order -- while proving that nothing about the meaning moved: same actors, same
quantities, same ticks, same emphasis, same visibility, no new causality, no
new facts.

It exists *between* the narration plan and the presentation layers on purpose.
Wording must be settled before anyone asks how long it takes to say: a
one-second slot and a twenty-second slot realize the same unit to the same
bytes, because this layer cannot see slots at all.

## 2. Ownership

Phase 26 owns exactly one question: **how may this locked narration unit be
said to a human without changing what it means?** It does not own when the
human hears it (Phase 27), which voice says it (Phase 28), what was shown
(Phase 22), what mattered (Phase 21), or what is true (the engine). If Phase
26 disagrees with a valid upstream decision, it realizes it.

LANGUAGE REALIZATION RESTATES MEANING IN HUMAN WORDS. IT DECIDES NOTHING.

## 3. Inputs

Exactly three canonical documents:

| Document | Contributes |
| --- | --- |
| Episode Narration Plan V1 | unit identity, order, kind, subjects, emphasis, text-source classification |
| Episode Story Plan V1 | structured beats and evidence: which event, which fact, which tick |
| CURRENT Render Export V1 | the actual events, the facts' structured details, and the world entities labels resolve through |

Deliberately not inputs: the Narration Delivery Plan (timing), the Shot
Direction Plan (visibility is already reported in the narration plan and
re-proven by Phase 24's own cross-check), the Render Plan and Render Manifest
(execution), any audio, any measurement, any model. The shot plan appears in
this layer's *tests* only as scaffolding, because the locked narration planner
needs it to build test inputs.

## 4. Prose is never semantic input

This is the layer's load-bearing rule. Semantic derivation never reads the
narration unit's `text` or the memory fact's `summary` -- not to parse, not to
compare, not to carry. Every atom a realized sentence speaks is recovered from
structure: the beat's event evidence (resolved against the actual export
event), the fact's structured `details`, and the world's own entity records.
The boundary guard bans every read of those two keys -- and of
`details["source_event_payload"]`, whose internals no presentation contract
proves -- across every module of this package, with no exemption. The output
field is named `realized_text` rather than `text` precisely so that ban can be
total.

Two behavioral proofs pin the rule: mutate every source sentence while the
structure stands, and the realized bytes do not move; mutate a fact's summary
while its details stand (rebuilding the chain honestly), and every
`realized_text` is unchanged even though every digest is new.

## 5. The evidence gate

Story validation proves an evidence entry's shape and its agreement with its
beat's kind. It does not prove the entry matches the actual event inside the
export -- nothing upstream opens `export["events"][index]` for event-derived
beats. This layer closes that gap: every event evidence entry is resolved
against the actual event and must agree on `type`, `source_id` and `tick`,
value and Python type both. Every fact evidence entry is resolved to exactly
one exported fact and must agree field for field, the beat must name the
fact's own subjects, and the fact must share a tick with the event it derives
from. A self-consistent lie dies here, not in a seal.

### Fact ancestry

Two further identities bind the chain end to end. A fact-backed narration
unit's own `fact_id` must equal the `fact_id` of the exactly-one memory-fact
evidence entry on its positional story beat -- the sentence and the story's
evidence are about one record, and a standalone-valid narration naming a
different identifier refuses at the join. And the beat's event evidence must
identify the very source event the fact itself declares: `index` must equal
the fact's `source_event_index` and `type` its `source_event_type`, before
the evidence is resolved against the actual export event. Two events sharing
a type, publisher and tick are still distinct moments, distinguished by
where they sit; the declared index is authoritative. The index addresses the
current export's events because the locked story layer only grants a
fact-backed beat to a fact new in the story's own episode, and the joins
bind that story to the very export offered here.

## 6. Entity resolution and relational integrity

The render export's envelope validator deliberately does not re-judge nested
contents, so every referential claim is proven locally, and every lookup must
resolve **exactly once** -- zero is a missing entity, two is an export the
engine never wrote. A boundary must join two different districts, both of
which resolve. A wall must name a boundary that **claims the wall back**
(`boundary.wall_id == wall.id`); a phrase is never built from a relation the
other side denies or contradicts. A fact's restated relationships must agree
with the world -- and first with the fact itself: the details must name the
fact's own publisher (`wall_id` / `law_id` against the fact's `source_id`,
and the persisted wall must be among the fact's own subjects), so a
world-consistent but substituted entity cannot borrow the fact's voice.
`WALL_BUILT` details must name the wall's own boundary and that boundary's
own endpoints, unswapped; every claimed built tick (`built_tick`,
`wall_built_tick`) must equal the world wall's own `built_tick`; the
persistence fact's `law_name` must equal the world law's authoritative
`name`. Any disagreement refuses.

## 7. Label authority

Three closed classes, and nothing else:

- **A. Authoritative world label.** The law's own `name` field, formatted
  under a reviewed rule (`movement_resource_sharing` -> "the movement resource
  sharing law"), guarded by an exact grammar (`^[a-z]+(_[a-z]+)*$`).
- **B. Reviewed mechanical label rule.** District identifiers matching exactly
  `^district_([a-z])$` map to "District A" ... "District Z". Anything else --
  `district_ab`, `district_1`, `districtx` -- refuses. The entity must also
  exist exactly once in the export; matching the grammar alone is not enough.
- **C. Reviewed explicit label table.** Present and **empty** in V1. It is
  the reviewed home a future entity class would occupy, not a prettifier;
  an entity resolving through neither a rule nor an entry refuses.

Walls and boundaries carry no authoritative names, so their referents are
**relationship phrases composed from structure**, never stored aliases: "the
boundary between District A and District B", "the wall between District A and
District B", with endpoints read from the world's own boundary record at
every use. A stored alias could drift from the world; a composed phrase
cannot. Naming a boundary by its defining endpoints is labeling the same
referent, not asserting a new fact -- the relation lives in the same bound
export and is cross-checked against the fact's own restatement of it.

## 8. The realization policy

One finite reviewed table, in the Phase 24 house shape -- one template per
template-backed beat kind, one per supported fact type, with closed parameter
declarations. `NO_EMPHASIZED_BEATS` is carried unchanged (it is already
human-facing, and it must never be read as "nothing happened"). The fact
templates present exactly the atoms the memory layer's own summaries present:
dependency scores, raw law values and the activity flag are deliberately not
promoted into speech, and the permanence flags must be genuinely `True`,
mirroring the memory layer's own refusals. An unknown kind or fact type
refuses; there is no generic wording, no paraphrase, no model, and no
awareness of length or time.

The canonical realizations, derived from the locked chain:

| Episode | Unit | Realized text |
| --- | --- | --- |
| 0 | unit_0001 | No beats were emphasized for this episode. |
| 1 | unit_0001 | At tick 7, the movement resource sharing law changed. |
| 1 | unit_0002 | At tick 9, a permanent wall was built on the boundary between District A and District B. |
| 1 | unit_0003 | At tick 9, the wall between District A and District B changed state. |
| 2 | unit_0001 | At tick 22, the movement resource sharing law was restored; the permanent wall on the boundary between District A and District B, built at tick 9, remained in the world. |
| 2 | unit_0002 | At tick 21, the wall between District A and District B changed state. |

## 9. Wording safety

Every realized sentence is held to the Phase 24 wording authority --
`forbidden_wording_hit`, imported, never copied weaker -- so no causal or
deictic claim can appear, and to two stricter rules of this layer's own: no
underscore and no straight quotation mark, because realized wording names
entities by reviewed label, never by internal identifier. Phase 24's own
quoted-identifier style is deliberately not inherited; that is the point of
this layer. Safety is re-proven on the new sentence, never assumed to
transfer from the source.

## 10. Output

Format `living_diorama_episode_language_realization_plan`, schema version 1,
policy `language_realization_policy_v1` -- the policy identifier is part of
the schema version, so changing a template or a label rule is a reviewed
version change, never a quiet edit.

Top level: `format`, `schema_version`, `policy`, `source`, `realizations`,
`accounting`. Each realization record is `{realization_id, unit_id,
realized_text}` -- a sentence and an identity, nothing more. No timing, no
shots, no visibility, no audio, and no copy of the source sentence.

## 11. Accounting

- exactly one record per narration unit, at the unit's own position;
  `realization_0001` realizes `unit_0001`, and so on -- positional
  identifiers make a reorder, an omission and a duplicate all unrepresentable
- `realizations_total` is measured from the records present
- the `template_backed` / `fact_backed` split closes on the total, and the
  cross-check proves it against the narration plan's own text-source
  classification -- a realization record carries no backing field of its own,
  so the split is verifiable only against the sources, and it is

## 12. Determinism

Same three documents, same bytes. Reads and writes go through the repository's
canonical codec. No clock, no randomness, no uuid, no environment, no locale,
no network, no model call, no filesystem outside the CLI -- enforced
structurally by the boundary guard and asserted behaviourally across
`PYTHONHASHSEED` 0, 1, 42 and 123456 in subprocesses. Labels are byte-level
transforms over exact grammars, so no locale-dependent casing exists anywhere.

## 13. Source binding

| Document | Bound as |
| --- | --- |
| narration plan | `narration_plan_sha256` over its canonical bytes |
| story plan | `story_plan_sha256` over its canonical bytes |
| render export | `current_export_sha256` over its canonical bytes |

The cross-check proves the digests name the documents offered; that the
narration plan itself restates exactly this story plan and carried sentences
from exactly this export; that the story plan read exactly this export; that
mode, episode, previous episode and schema versions agree everywhere stated;
that every record realizes its positional unit and beat under the kind,
subjects, emphasis and text-source the sources hold; that every sentence
equals the one deterministic derivation from structure; and that the
accounting matches the sources. Then the seal: the plan is re-derived from
the three sources and must equal it byte for byte. **Refuse, never repair.**

## 14. Boundaries, enforced structurally

`tests/language_realization/test_phase26_boundary.py` proves, by parsing the
sources rather than by reading them:

- the layer imports only the narration, story and render contracts and the
  shared codec and validation vocabulary -- deliberately no cinematic and no
  delivery, whose timing this layer must not know
- it never imports `living_diorama.narration_delivery`,
  `living_diorama.render_execution`, `living_diorama.memory`, Blender, the
  network, or any source of nondeterminism
- no pure module touches the filesystem; only the CLI reads or writes
- no module defines a name belonging to captions, voice, audio, assembly,
  encoding, publishing, camera re-direction, delivery timing, a runtime
  model, or any non-frame unit of time
- no module reads a narration unit's `text`, a fact's `summary`, or a
  `source_event_payload`, by subscript or by `get` -- an empty allow-list
- no module splits, lowercases or inspects a sentence, and none copies a
  record wholesale
- every guard is exercised against a deliberately bad synthetic file, because
  a guard nobody has seen fail is a guard nobody has tested

## 15. Command

```
python -m living_diorama.cli.build_language_realization_plan \
    --narration episode_narration_plan_v1.json \
    --story episode_story_plan_v1.json \
    --export render_export_ep2.json \
    --output episode_language_realization_plan_v1.json
```

Inputs must be canonical bytes. The output is never overwritten. The plan is
cross-checked against all three sources before the file is written, so a
realization plan can never exist without its bindings having been proven.
Exit 0 on success, 1 on refusal, with a message rather than a traceback.

## 16. Known limitations

- **One episode.** A plan realizes one baseline or one transition, as every
  layer upstream does.
- **English only.** The templates and label rules are one language and say
  so; a second would be a schema version, not a runtime option.
- **The wall referent is its relation.** V1 has one wall, named by the
  districts it separates. A world with two walls on one boundary is
  unrepresentable upstream; a world whose wall needed a name of its own would
  add a reviewed Class C entry, a version change.
- **Wording length is unknown here, on purpose.** Whether a sentence fits a
  presentation window is Phase 27's reviewed decision and the voice layer's
  measured question, in that order. Nothing here counts words, and nothing
  here may.
- **The narration plan remains the audit-of-record.** Realized wording is
  presentation language bound to it, never a replacement for it -- the
  verbatim carried summaries stay exactly where Phase 24 locked them.
