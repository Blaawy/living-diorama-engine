# Cinematic Direction — Phase 22

**CINEMATIC DIRECTION IS PRESENTATION METADATA, NOT AUTHORITATIVE WORLD TRUTH.**

Phase 21 decides *what* authoritative history deserves emphasis. Phase 22 decides
*how* that emphasis is shown, using only camera anchors the world builders already
created and the Phase 17 timeline that is already locked.

It invents no viewpoint, moves no camera, and creates no world fact.

---

## 1. Why this layer exists

Phase 17 named its own successor:

> `docs/motion_time.md` — "Phase 17 adds TIME — and nothing else. It is the
> machinery that carries the existing world from one truthful simulation state to
> another, on a frame timeline a later cinematic layer can consume without
> rewriting anything."

> `docs/motion_time.md` — "No camera direction, shot selection, or cut grammar —
> Phase 17 builds the timeline a later cinematic layer will consume"

What that layer lacked was a principled reason to point anywhere. Phase 21 supplied
it. And Phase 20 had already left a specific, documented gap:

> `docs/state_response.md` — "The record stones read at the Seal detail camera and
> are not legible at the world hero cameras."

The world already draws one cut stone per durable memory fact. Nothing ever looked
at them, because camera selection was fixed and content-blind. This layer is what
looks.

---

## 2. Ownership

Phase 22 owns exactly one responsibility:

> **Which already-existing camera anchor should be active over which stretch of
> the already-locked timeline, and why?**

It does **not** own narration, prose, subtitles, voiceover, audio, music, final
editing beyond ordered fixed-camera cuts, encoding, thumbnails, packaging, or any
camera *movement* whatsoever. Those are later concerns.

---

## 3. Inputs

| Input | Source | How it arrives |
| --- | --- | --- |
| Episode Story Plan V1 | Phase 21 | validated document |
| Motion & Time Spec V1 | Phase 17 | **exact document bytes, passed as data**, never imported |
| Camera anchor catalogue | Phases 15 and 16 | closed constant, test-checked against config |

The clock arrives as the raw bytes of the Phase 17 Motion & Time Spec document
itself, and only ONE document is accepted: the binding pins
`CANONICAL_MOTION_TIME_SHA256` — the SHA-256 of the exact
`motion_time_v1.json` bytes in the locked tree — and refuses anything else
outright, however internally consistent. A well-formed 30 fps document, a
shifted window, resized holds: none of them can produce a plan at all, at the
planner, the CLI, the plan validator, the cross-validator, the Blender runner
(which pins the `--motion` file before any suite runs) or the applier (which
holds the same pinned digest and the canonical resolved values as restated
data). The planner still verifies the format tag, schema version, exact
six-field timeline and Phase 17's own phase arithmetic first — a malformed
document earns its specific refusal before the identity refusal — and the
in-Blender suite proves the restated arithmetic against
`motion_time_spec.resolve_timeline` itself. Phase 17's modules are never
imported — the borrowing rule Phase 19 established, Phase 20 followed, and both
boundary tests enforce — and a repository test re-hashes the shipped config
against the pinned constant, so a future Phase 17 source change requires an
explicit reviewed update rather than being silently accepted.

The camera catalogue is source-bound the same way: the plan's
`catalogue_sha256` is the digest of the approved catalogue's canonical
serialization, recomputed and enforced by the plan validator, and the applier
re-serializes whatever catalogue it is handed and refuses on any digest
disagreement — so a scene mutated to match a mutated catalogue fails on the
catalogue's own identity before any camera is inspected. Key order and on-disk
formatting are immaterial by construction; every value is load-bearing.

Phase 22 never re-opens the Render Export. Phase 21 already read it, and this
layer takes Phase 21's word for what mattered.

---

## 4. The camera anchor catalogue

Fourteen anchors, and nothing else may ever be selected:

| Source | Anchors |
| --- | --- |
| Phase 15 `master_scene_v1.json` | `CAM_HERO_WORLD`, `CAM_HERO_SCAR`, `CAM_SCAR_DETAIL`, `CAM_SEAL_DETAIL`, `CAM_VERIFY_TOPOLOGY` |
| Phase 16 `production_world_v1.json` | `CAM_P16_WORLD_HERO`, `CAM_P16_SYSTEM`, `CAM_P16_URBAN`, `CAM_P16_ROADS`, `CAM_P16_DENSITY`, `CAM_P16_COMPOSITION`, `CAM_P16_CORE_CONTEXT`, `CAM_P16_SCAR_CONTEXT`, `CAM_P16_VALIDITY` |

These are exactly the cameras `build_master_scene.py` and `build_production_world.py`
create into the scene. The `CAM_P18_*` and `CAM_P19_*` names are **deliberately
excluded**: those are built by proof producers at proof time, not by the world
builders, so they are not present in the scene this layer directs.

The catalogue is restated in `cinematic_spec.py` rather than read from those config
files, because the planner is pure and touches no filesystem. Each record carries
the anchor's **whole locked visual identity**: `location`, the `look_at` point its
orientation derives from, `lens_mm`, `f_stop`, the depth-of-field `focus` point,
whether the builder enables depth of field at all (`dof` — off for the three
survey anchors `CAM_VERIFY_TOPOLOGY`, `CAM_P16_ROADS`, `CAM_P16_VALIDITY`), the
builders' uniform far clip (`clip_end`, 1200), and the projection-geometry state
the locked build inherits from the supported Blender's factory camera —
projection type, sensor width, height and fit, both lens shifts, near clip, and
the three bokeh-shape dials on depth-of-field anchors. Any of those would
silently re-frame or re-render the image with the lens untouched (the vertical
sensor fit was demonstrated live by the wave-2 adversarial audit), so the
applier proves every one against the scene. Tests assert the restated
catalogue matches both configs field for field — locations, look-ats and focus
points included, with the builders' own focus defaulting replicated — so the two
cannot drift; the in-Blender suite repeats the same cross-check against the
shipped configs inside the gate.

---

## 5. The direction policy

Deterministic, finite, and small enough to read in one sitting.

| Phase 21 beat kind | Camera anchor | Why |
| --- | --- | --- |
| `LAW_CHANGE` | `CAM_SEAL_DETAIL` | the law is sealed on the Golden Seal plaza |
| `LAW_RESTORATION` | `CAM_SEAL_DETAIL` | same |
| `WALL_RAISED` | `CAM_HERO_SCAR` | the wall stands on the scar |
| `WALL_STATE_CHANGE` | `CAM_SCAR_DETAIL` | the wall itself changing |
| `POPULATION_MOVEMENT` | `CAM_P16_URBAN` | movement reads in the urban fabric |
| `DURABLE_CONSEQUENCE` | — unshown, `NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE` | see below |
| `CONSEQUENCE_PERSISTED` | — unshown, `NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE` | see below |
| `NO_EMPHASIZED_BEATS` | — unshown, `NOTHING_TO_EMPHASIZE` | earns no shot; see §7 |

### Why the durable-memory beats are honestly unshown

Full-world evidence, not symbolism, decides the durable-memory policy — and
the evidence says **no approved fixed anchor genuinely shows the record
register**. Two independent measurements on the fully composed world:

- **A NEW fact's stone does not exist while its beat is on screen.** Phase
  20's locked `memory_record` channel is **step** interpolation over window
  `[0.35, 0.95]` of the transition: the stone appears at a step at the
  window's END — frame `25 + round(0.95 × 120) = 139` on the canonical
  clock — while this layer's derived shot windows (rank order,
  emphasis-weighted durations, fixed holds) place every possible
  durable-consequence shot before that step. Framing an EMPTY register while
  narrating a new record would be fabricated visibility.
- **A PERSISTED fact's standing stone cannot be seen from the candidate
  anchor.** The full-world gate cast nine sample rays (center plus all eight
  bound corners) from `CAM_SEAL_DETAIL` to the standing stone at the directed
  frame: zero of nine reach it — every ray terminates on `LD_SEAL__disc`,
  the monument's own raised drum, which wholly occludes the record arc laid
  out behind it. That measurement agrees with Phase 20's own record: its
  blind reviewer never saw the stones at the Seal framing, the register is
  not legible at the hero cameras, and Phase 20 needed the **proof-only**
  `CAM_P20_RECORD_ARC` for exactly this reason. Cutting to the monument
  while claiming to show the record would be symbolism sold as proof.

Both beats therefore carry the structured reason
`NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE`; the Story Plan remains authoritative
and every beat is still accounted for exactly once. `CAM_P20_RECORD_ARC`
remains proof-only and is not promoted, and no camera is created: making the
register visible is a world-building decision for a future reviewed phase,
not this layer's improvisation.

An unrecognised beat kind is **never given a guessed viewpoint**. It falls back to
the neutral establishing anchor with reason `UNKNOWN_BEAT_KIND`, so a future
Phase 21 kind produces an honest, slightly flatter plan rather than a confidently
wrong one.

### Screen time

Phase 21 ranks; Phase 22 turns that ranking into duration and nothing more.

`PRIMARY` = 3, `SECONDARY` = 2, `BACKGROUND` = 1. Every shot receives
`MIN_SHOT_FRAMES` (6, a quarter-second at 24 fps) first, and only the surplus is
shared by weight using largest remainder with the group index as tie-break. That
ordering matters: allocating by weight first and repairing minimums afterwards
would make the result depend on which group happened to be repaired.

**Phase 21's meaning is frozen.** Emphasis is copied, never recomputed. A
`BACKGROUND` beat is never promoted, an excluded event is invisible here, and shot
order is Phase 21's rank order.

### Ticks are not frames

A beat carries evidence ticks. This layer deliberately does **not** convert them
into frames: no contract justifies such a mapping, and inventing one would make
Phase 22 assert something about time that Phase 17 owns. Beat *order* comes from
Phase 21's rank, which already encodes history order. Beat *duration* comes from
emphasis weight. Nothing else.

---

## 6. Output

`shot_direction_plan_v1.json`, format tag `living_diorama_shot_direction_plan`,
schema version 1 — independent of the story, render and persistence versions.

```
{
  "format": "living_diorama_shot_direction_plan",
  "schema_version": 1,
  "source": { "mode", "episode", "previous_episode", "catalogue_sha256",
              "story_plan_sha256", "story_schema_version",
              "motion_time_format", "motion_time_schema_version",
              "motion_time_sha256" },
  "timeline": { "fps", "start_frame", "start_hold_frames",
                "transition_frames", "end_hold_frames",
                "transition_start", "transition_end", "end_frame" },
  "shots": [ { "shot_id", "kind", "camera_anchor_id", "start_frame",
               "end_frame", "reason_code", "source_beat_ids", "emphasis" } ],
  "unshown": [ { "beat_id", "reason_code" } ]
}
```

`story_plan_sha256` is the digest of the story plan's own canonical bytes. Because
the CLI refuses any input file that is not already canonical bytes, that digest is
simultaneously the digest of the file on disk — so a shot plan cannot be silently
paired with a different story plan. `motion_time_sha256` is the digest of the
exact Motion & Time Spec bytes the clock was resolved from, and the timeline
section restates the six source fields plus both derived boundaries, which the
validator re-checks against Phase 17's arithmetic. Emphasis comes from Phase 21's
closed vocabulary (imported, not restated), beat-shot reason codes are limited to
their actual derivation cases, multi-beat shots must carry the merge reason, and
unshown entries may carry only the two unshown causes.

### Cross-validation against the sources

`validate_shot_direction_plan` proves everything a plan can prove about itself.
`validate_shot_direction_plan_against_story(shot_plan, story_plan, motion_time)`
proves the plan against its actual sources: digest and identity bindings for both
documents, exact beat accounting (every story beat shown exactly once or unshown
exactly once, none invented, none omitted), per-beat anchor policy, reason-code
derivation cases, emphasis copied at the strongest cited level, unshown-reason
legality, and Phase 21 rank order — and then **re-derives the plan from the two
sources and requires byte equality**, closing every remaining degree of freedom
(durations, allocation, merging, tiling). A plan is source-verified only when it
is the plan those sources produce. The CLI runs this cross-validation before it
writes anything.

---

## 7. Whole-document rules

These are what make a plan *directable* rather than merely well formed:

- **The shots tile the timeline exactly.** No gap, no overlap, no frame twice, no
  frame left undirected, and no frame outside `start_frame..end_frame`.
- **Adjacent shots never share an anchor.** Cutting to the camera you are already
  on is not a cut, so consecutive beats resolving to the same anchor are merged
  into one longer shot carrying both beat ids.
- **The loop closes.** Phase 17 guarantees frame 1 and frame 193 are the same
  world; the camera must match at both ends, or the loop jumps. Guaranteed
  structurally by opening and closing on the same neutral anchor.
- **A beat is shown once**, or recorded in `unshown` with a reason. Every beat
  Phase 21 supplied is accounted for exactly once.
- **Shot ids are positional** — `shot_0001`, `shot_0002` — so they are derivable
  rather than free labels.

### Baseline and empty results

`NO_EMPHASIZED_BEATS` reports that Phase 21 selected nothing. It is a statement
about Phase 21's output, not about the world, so framing it would be framing
nothing. It earns no shot; the episode gets a single neutral establishing hold
across the whole timeline, and the beat is recorded as `unshown` with reason
`NOTHING_TO_EMPHASIZE`. No story beat is ever fabricated.

If more beat groups exist than the transition can hold at `MIN_SHOT_FRAMES` each,
the excess is recorded as `unshown` with `TRANSITION_BUDGET_EXHAUSTED` — reported,
never silently dropped.

---

## 8. The real canonical episodes

| Episode | Shots | Unshown |
| --- | --- | --- |
| 0 (baseline) | one neutral hold on `CAM_HERO_WORLD`, frames 1–193 | the empty-result beat, `NOTHING_TO_EMPHASIZE` |
| 0 → 1 | neutral 1–24 · **Seal** 25–95 (law change) · **Scar detail** 96–144 (wall state) · neutral 145–193 | the NEW durable fact, `NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE` (its stone appears at ~frame 139, after any derivable durable shot; see §5) |
| 1 → 2 | neutral 1–24 · **Scar detail** 25–144 (wall state) · neutral 145–193 | the persisted durable fact, `NO_FIXED_ANCHOR_WITH_VISUAL_EVIDENCE` (its stone stands, but the Seal's own disc wholly occludes it from the only candidate anchor; see §5) |

The camera goes to the Golden Seal when a law is sealed there — something the
anchor genuinely shows. It does **not** go there for the durable-memory
register, because measurement says the register cannot be seen from any
approved anchor: what this phase closes is the *accounting* gap. Every
durable beat now carries an explicit, evidenced verdict — shown where true,
structured-unshown where showing it would be staged — instead of a symbolic
cut that framed a monument and called it the record.

---

## 9. Blender realization

`visual/blender/scripts/apply_cinematic_direction.py` binds each shot to the scene
timeline with a marker, which is Blender's own mechanism for cutting between
cameras during playback and render.

Before a single marker is touched it proves every anchor the plan names is still
the locked viewpoint: present, unique, a camera, un-animated (object and camera
data), on the default XYZ rotation mode, standing at the locked location, aimed
along the locked look-at derivation, carrying the locked lens, far clip and
depth-of-field state (aperture and focus distance where the builder enables
depth of field; disabled where it does not). The orientation check reconstructs
the view axes from the stored euler in pure Python — the same
`to_track_quat("-Z", "Y")` convention the builders use, measured against real
`mathutils` for all fourteen anchors (worst disagreement 2.6e-8) — so it runs
identically under the fake `bpy` and the real one. Tolerances are three or more
orders of magnitude above float32 storage drift and many below any real
mutation. A drifted anchor **fails closed**: it is REFUSED, never repaired,
because repairing it would mean this layer moved a camera.

**Foreign camera-bound markers.** A foreign marker that binds a camera at or
before the directed range's last frame competes for the same mechanism this
phase uses, so the apply is refused and the conflict named. The foreign marker
is never deleted or rewritten; ordinary non-camera markers are ignored and
preserved.

**Ownership and idempotence.** Every marker is named `P22_SHOT_<shot_id>`. Only
markers with that prefix are ever removed, so applying a plan twice converges and
somebody else's timeline state is left exactly as found.

The applier imports nothing from the engine package: the catalogue arrives as
data, which keeps it a thin realization rather than a second decision-maker.

**The structural gate is a true superset.** `run_blender_tests_p22.py` follows
the locked Phase 20 runner: from factory startup it rebuilds the canonical world
and runs the locked Phase 15, 16, 17, 18, 19 and 20 suites unchanged and in
phase order before the Phase 22 suite, and reports per-phase counts. The Phase 22
suite itself runs against the real animated motion scene, proves every anchor
against the shipped configs and real `mathutils`, steps real frames and asserts
Blender's own active-camera selection at every cut and at both loop ends, and
proves the mutation refusals against the real scene. The applier additionally
verifies the scene's EXECUTION clock — `render.fps` equals the plan's bound
fps, `fps_base` neutral, no time remapping, no frame stepping, no sequencer —
because frame numbers alone are not time: a 60 fps scene would play the locked
193 frames in a third of the reviewed duration.

**The visual proof renders the full composed world.** After a fully passing
run the gate stands up every locked prior layer in phase order — the Phase 15
founding scene, the Phase 16 production city, the Phase 17 motion union, the
Phase 18 population, the Phase 19 mobility layer, the Phase 20 state response
(static after-state plus the transition curves) — using those layers' own
planners and appliers with the arguments their own suites use, censuses the
composed scene (population proxies, vehicles, mobility actions, air strata,
record stones, response curves) and refuses to photograph an incomplete world.
Each transition renders on its own composed world; the baseline hold renders
the leg1 world's first held frame, which Phase 17's endpoint equivalence and
Phase 20's motion-endpoint contract make the exact episode-0 state. Before
every frame the scene is stepped, Blender's actual active camera is asserted
against the plan, and each cited beat's expected visual target is verified in
the composed scene — and should any plan ever cite a durable-memory beat, the
actual `LD_SR__record_stone_*` objects must sit inside the active camera's
view cone with an unoccluded ray from the lens, recorded stone by stone in
the proof manifest. That is the check whose nine-of-nine `LD_SEAL__disc` ray
verdict decided the §5 policy: symbolic framing is never accepted as proof of
the response — the Seal being in shot does not certify the record; the stones
themselves must, and since they cannot be seen, the beats are unshown.

---

## 10. Refusals

| Condition | Response |
| --- | --- |
| Story plan fails its own Phase 21 contract | refused |
| Story schema version this build cannot direct | refused |
| Clock that is not the Motion & Time Spec format/schema this build directs against | refused |
| Clock bytes that are not THE canonical pinned Phase 17 source | refused |
| Plan binding a non-canonical clock digest or a non-approved catalogue digest | refused |
| (Applier) supplied catalogue whose canonical digest differs from the plan's binding | refused |
| (Applier) scene execution clock mutated: fps, fps_base, time remap, frame step, sequencer | refused |
| (Applier) parented, constrained, delta-transformed, scaled, focus-object-driven, or evaluated-matrix-drifted anchor | refused |
| Timeline whose fields, bounds, or phase arithmetic disagree with Phase 17's own | refused |
| Non-integer or boolean frame | refused |
| Anchor outside the catalogue | refused |
| Frame outside the locked timeline | refused |
| Gap, overlap, or uncovered frame | refused |
| Two adjacent shots on one anchor | refused |
| Opening and closing anchors differ | refused |
| A beat shown by two shots | refused |
| Emphasis outside Phase 21's vocabulary | refused |
| Reason code that does not match the shot's shape and derivation case | refused |
| Establishing shot citing beats, carrying emphasis, or on another anchor | refused |
| Beat shot citing no beat | refused |
| (Cross-validation) digest, accounting, policy, emphasis or derivation disagreement with the actual sources | refused |
| (CLI) story file that is not canonical bytes | refused |
| (Applier) missing, ambiguous, non-camera, moved, rotated, re-lensed, re-apertured, re-focused, re-clipped, re-sensored, re-fitted, shifted, re-projected, bokeh-reshaped, animated, or mode-changed anchor | refused |
| (Applier) foreign camera-bound marker at or before the directed range's end | refused |
| (Applier) scene frame range disagreeing with the plan | refused |

Nothing is repaired.

---

## 11. Determinism

Pure function of its inputs: no clock, no randomness, no filesystem path, no
Blender import, no iteration order Python is free to vary.

Canonical serialization via `dumps_canonical`; proven byte-identical across
`PYTHONHASHSEED` values 0, 1, 42 and 123456 in separate interpreters, and when the
input dictionaries are rebuilt in reverse key order.

---

## 12. Boundaries, enforced structurally

`tests/visual/test_phase22_boundary.py` proves by AST and source inspection that
the layer never imports Blender (pure side), live simulation, `living_diorama.render`,
any Phase 17 module, any network or model client, or `random`/`time`/`datetime`/`uuid`;
never moves, re-lenses, animates or creates a camera; never touches geometry or
materials; never clears markers it does not own; and defines no narration, audio,
packaging, camera-motion or citizen vocabulary. Each guard is exercised against
deliberately bad synthetic files, and against innocent files that must **not**
trip it.

---

## 13. Usage

```bash
python -m living_diorama.cli.build_shot_plan \
    --story episode_story_plan_v1.json \
    --motion-time visual/blender/config/motion_time_v1.json \
    --output shot_direction_plan_v1.json
```

`--motion-time` is the Phase 17 Motion & Time Spec document itself, read byte
for byte — pretty-printed exactly as Phase 17 ships it. The engine package never
imports the Blender-side spec module; the plan binds the digest of the bytes and
the CLI cross-validates the finished plan against both inputs before writing it.

---

## 14. Known limitations

- **Fixed anchors only.** V1 selects and cuts; it never moves a camera. That is a
  deliberate scope decision protecting Phase 17's property that "any difference
  between two frames is the world changing rather than the camera moving" — which
  now holds *within* every shot, though not across a cut.
- **Hard cuts only.** No crossfades, dissolves, or interpolation.
- **The holds are always neutral.** Emphasis lives entirely in the transition;
  the start and end holds are fixed to the establishing anchor to guarantee loop
  closure. A future version could direct the holds too.
- **Anchors are chosen by beat kind alone.** `subject_ids` are carried but not
  used for selection — with four districts and one wall there is not yet enough
  spatial vocabulary to justify per-subject framing.
- **No cross-episode continuity.** One plan directs one story plan, which spans at
  most one transition.
- **The visual proof pairs each plan with its own world.** The transitions render
  on their own animated motion scenes; the baseline's hold renders on the held
  episode-0 state, which Phase 17's endpoint equivalence makes exactly the
  before-world.
