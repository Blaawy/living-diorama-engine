# Motion & Cinematic Time (Phase 17)

## Purpose

Phases 0–14 built a deterministic world that remembers. Phase 15 gave it a
face. Phase 16 grew that face into a city. All of it is still a **still**.

Phase 17 adds TIME — and nothing else. It is the machinery that carries the
existing world from one truthful simulation state to another, on a frame
timeline a later cinematic layer can consume without rewriting anything.

The whole phase answers one question:

> Can the static Living Diorama move through time without inventing history?

## The rule that governs everything

**Motion is downstream.** The simulation is authoritative; the animation layer
visualises differences between two authoritative states and decides nothing.

```
ENGINE → WORLD STATE → EVENT LOG / WORLD MEMORY → RENDER EXPORT V1
                                                        ↓
                                                   MOTION PLAN
                                                        ↓
                                                 BLENDER TIMELINE
```

`src/living_diorama/` still knows nothing about Blender. The pure planning
half of Phase 17 (`motion_time_spec.py`, `motion_plan.py`) knows nothing about
Blender either, and the Blender half knows nothing about the engine. Boundary
tests pin all three directions.

## Why only some channels can be animated at all

The hard contract is **endpoint equivalence**, and it covers the whole world
state — geometry *and* materials:

* at the first semantic frame the scene must equal the ordinary static
  application of Render Export A;
* at the last semantic frame it must equal the ordinary static application of
  Render Export B.

Both halves are machine-compared. `scene_state_at(frame)` evaluates every
object's F-curves; `material_state_at(frame)` evaluates every state-driven
material node socket's F-curve. `compare_endpoint` reports
`objects_equivalent`, `materials_equivalent`, and an `equivalent` that is
true only when **both** are — an animation that lands the geometry perfectly
while leaving the Golden Seal on the wrong emission has still produced a
false frame, and the gate refuses it. The gate also refuses a *vacuous* pass:
if a proof animates no material channel at all, there is nothing for material
equivalence to mean, and that is an error rather than a green tick.

That single requirement decides which channels V1 can carry. A property the
Phase 15 static application never writes cannot be animated, because driving
it would make the animated end state differ from the static end state.
So the V1 channel list is not a wish list — it is exactly the set of
properties the existing state mapping already drives:

| channel | authoritative source | what it drives |
| --- | --- | --- |
| `law_seal_glow` | `world.laws[law_movement_sharing].active` | the Golden Seal's emission (5.0 in force / 0.0 suspended) |
| `district_glazing` | district population ÷ housing capacity | `LD_LitFraction` on that district's glass material |
| `wall_presence` | a wall the engine built appearing between states | staged reveal + rise of the canonical wall objects |
| `depot_slot_presence` | district resource stock ÷ depot capacity | which container slots stand |
| `depot_slot_settle` | the canonical decoration of the two endpoints | reconciles shared containers (see below) |
| `infra_strut_presence` | wall existence + dependency score | which conduit anchors exist |
| `infra_strut_settle` | the re-centred anchor row | reconciles shared struts |

### Refusals, and why they are the right answer

Two transitions the directive names as candidates are **deliberately refused**
in V1, each with an explicit message:

* **Infrastructure condition** (`degraded` flipping). The locked mapping
  expresses condition by *swapping the pipe material*. A material assignment
  is not an animatable value; driving it would mean either keyframing a
  property the static layer never writes, or building a second set of damaged
  pipes — inventing geometry. Refused.
* **Gate mechanism** (a sliding gate door). Phase 15 defines **no gate
  position state at all** — the door is fixed geometry. Animating it would
  mean Phase 17 inventing presentation semantics, and the animated end state
  would then differ from the static application of the export. Refused, and
  not implemented.

Also refused: a wall vanishing between two states (the world remembers), a
wall changing integrity (that changes canonical segment heights, and V1 has no
geometry-morph channel), districts or infrastructure appearing or vanishing, a
conduit changing boundary, a non-boolean law flag, duplicate entity ids,
non-finite numbers, and two districts demanding different truths from one
shared glazing material.

## Layer 1 — the timeline

`visual/blender/config/motion_time_v1.json`, validated by
`motion_time_spec.py`:

```
{"format": "living_diorama_motion_time", "schema_version": 1}
```

The timeline is presentation-neutral and declared in full, then cross-checked
against itself:

```
START HOLD      frames 1 … 25       the before-state, held still
TRANSITION      frames 25 … 145     the only window in which anything moves
END HOLD        frames 145 … 193    the after-state, held still
                24 fps, 8.0 seconds
```

`end_frame` must equal `start_frame + start_hold + transition + end_hold` or
the spec is refused — a typo becomes an error instead of a wrong cut. Both
holds must be at least one frame: an endpoint the film never rests on is not
an endpoint you can prove.

No runtime module computes a frame of its own. Channels declare a normalised
window inside the transition, and `frame_at`, `channel_frames`,
`member_span_frames` and `staged_frames` turn those into integers — one
implementation, shared by the pure planner and the Blender applier, so both
sides always agree on the exact frame a thing moves.

### Interpolation policy

Blender's Bezier default never survives. There are exactly three easings:

* `linear` — `v = a + (b − a)·t`
* `smoothstep` — `v = a + (b − a)·t²(3 − 2t)`, the classic S-curve
* `step` — holds `a` for the whole window and swaps at its very end

Every one of them is exact at both ends: `t = 0` returns `a`, `t = 1` returns
`b`. No overshoot, no bounce, no procedural noise. `smoothstep` and `linear`
curves are **sampled by the project** at a declared number of evenly spaced
frames and written as LINEAR keys, so the curve Blender draws is the curve
this project computed and can assert. `step` curves are two CONSTANT keys.

## Layer 2 — the MotionPlan

`motion_plan.py` is pure Python. Given two Render Exports, the Master Scene
Spec and the Motion Spec, it produces a sorted list of directives:

```
semantic_id      channel        target            value_space
from_value       to_value       start_frame       end_frame
interpolation    strategy       samples           rise_metres
source_before    source_after
```

Properties the tests pin:

* **Deterministic** — same inputs, same plan, same SHA-256, every run and
  every `PYTHONHASHSEED`. `stable_rng` (SHA-256 seeded) is the only randomness
  anywhere near it; Python's `hash()` is never involved.
* **Order-independent** — shuffling any export array produces a byte-identical
  plan.
* **Minimal** — a value that did not change produces no directive at all.
* **Traceable** — every directive names the export fields it came from.
* **Explicit** — an unsupported transition raises `MotionPlanError` with a
  reason instead of being approximated.

### `canonical_offset`: why the last frame is exact

Transform directives never carry absolute coordinates. They carry an offset
from the value the canonical static application of the AFTER export produces,
and **every one of them ends at exactly `0.0`**. The final frame is therefore
the canonical static world bit-for-bit, not something that merely resembles
it. The first key of a reconciling directive is anchored to the measured
before-value so the first frame is bit-exact too (float32 storage would
otherwise leave about two micrometres of drift at city scale).

### The two replicas

The planner has to know which containers and which conduit anchors a given
export would produce *before* Blender produces them, because those object sets
differ between endpoints. It replays the locked samplers directly —
`apply_districts`' own `stable_rng` identity and slot order, and
`apply_infrastructure`'s strut count and centring. These are replays, not
reinventions, and Blender structural tests pin both against the real meshes,
so any drift in the locked builders fails loudly instead of animating a wrong
yard.

## Layer 3 — applying the plan in Blender

`apply_motion_plan.py` creates no geometry. An animated scene is assembled in
a deliberate order:

1. build the master scene, then the production city;
2. apply the BEFORE export the ordinary locked way, and **measure** it;
3. apply the AFTER export the ordinary locked way, and **measure** it;
4. rebuild the before-state, then overlay the after-state *without clearing* —
   the locked builders replace by name, so the result is exactly the union:
   every after-object with its canonical after-properties, plus the
   before-only objects still holding their canonical before-properties;
5. **verify** the union against both measurements and refuse if any canonical
   difference is not covered by a directive;
6. only then create F-curves, from the plan alone.

Step 5 is the honesty check. An animation is not allowed to quietly show the
after-world's decoration at the before-frame, so an uncovered difference is a
hard refusal. The applier also cross-checks every planned value against what
the canonical builders actually produced: if the pure replica and the real
scene ever disagree, nothing is animated.

Presence is expressed on both `hide_render` and `hide_viewport` as CONSTANT
steps. An object that appears is unhidden at the **start** of its own window
so it exists for the whole of its reveal; an object that vanishes is hidden at
the **end** of its window so it survives its conceal. A wall additionally
rises `rise_metres` into place along Z, ending at exactly its canonical
height.

### Idempotency

Every action is named `LD_MOTION__obj__<name>` or `LD_MOTION__mat__<name>` and
every application clears those first. Applying the same plan twice produces
the same actions, the same F-curves, the same keyframe counts, no duplicate
actions, and no `.001` growth. Action names are asserted against Blender's
63-byte identifier limit, because silent truncation is how the Phase 16 name
collisions happened.

Rebuilding the world without applying a plan reproduces the canonical static
Phase 16 city exactly, with no animation data on anything.

## The proof story

The proof is the real engine's own three-episode chain — the same one Phase 15
generates, exported one episode further by
`tools/phase17_motion/generate_motion_story.py`:

```
LEG 1   episode 0 → episode 1    THE LAW IS SUSPENDED AND THE WALL RISES
LEG 2   episode 1 → episode 2    THE LAW RETURNS AND THE WALL REMAINS
```

Leg 1 is the rich transition: the Seal goes dark, the engine's wall rises, the
conduits anchor into it, and the yards refill. Leg 2 is the important one for
the project's promise — the law returns to exactly what it was, and the scar
does not. **A truthful planner emits no wall directive at all for leg 2**, and
the gate fails if one appears.

Two channels do not change in this story: population is constant across all
three episodes, so `district_glazing` emits nothing, and no infrastructure ever
degrades. They are not faked.

`district_glazing` is instead proven by a clearly-labelled **synthetic
structural fixture**: it takes the real episode-0 export, changes exactly one
authoritative number (a district's population), and drives that pair through
the ordinary planner, the ordinary union build, and the ordinary Blender
applier — then reads the value the applied F-curve actually produces at the
first and last frames. It proves the code path end to end. It is never
rendered, never packaged, and never presented as something the world did.
That is the distinction this project keeps: a **real-engine motion proof** is
history, a **synthetic structural fixture** is a test of machinery.

## Proof package integrity

A proof package is only evidence if it can prove its own contents, so exactly
one member — `phase17_proof_package_manifest.json` — is the authoritative
inventory, and it obeys one rule: **every member except the inventory itself
is enumerated with its byte size and SHA-256.**

That makes five failure modes decidable instead of matters of opinion, and
`proof_package.verify_package_inventory` refuses each one: a missing member,
an unenumerated extra member, a wrong hash, a wrong size, and a manifest that
points at an artifact the package does not carry. The last one is the reason
both animated `.blend` files are packaged rather than only the transition's.

The per-run manifests deliberately carry no member lists of their own. Each is
written while its own renders are still finishing, so any list it produced
would describe a package that was still being assembled. They record their own
run; the inventory records the package. The gate writes the inventory last and
then verifies it, and the same pure verifier is unit-tested against every one
of the five attacks.

One further honesty note: the story manifest records leg 2's raw resource
change, but the plan emits no depot directives for it, because both endpoints
saturate the depot fill at 1.0. The raw state moved; the *visual mapping* did
not. Reporting both is deliberate.

## Running the gate

```
python visual/blender/run_phase17_checks.py --workspace <fresh dir> --preview
```

Eight steps: Blender 4.5.x present; the real engine story generates and both
legs behave; both MotionPlans are valid, deterministic and minimal; every
structural Blender test passes **in phase order** (Phase 15, then Phase 16,
then Phase 17), with its per-phase counts kept as a package member; the proof
packs render, including both animated `.blend` files; the saves and exports
are untouched; the manifests are clean UTF-8 whose own recorded verdicts --
objects equivalent, materials equivalent, city unmoved -- are all true; and
the package inventory is written and then verified against what is actually
on disk.

## What Phase 17 deliberately does not do

No camera direction, shot selection, or cut grammar — Phase 17 builds the
timeline a later cinematic layer will consume, and the proof uses existing
canonical camera anchors only, so any difference between two frames is the
world changing rather than the camera moving. No pedestrians, crowds, vehicles
or traffic. No story compiler, narration, audio, editing or packaging. No
per-frame baking: the whole animated scene is a small number of semantic
F-curves, and a structural test refuses a density that would suggest
otherwise.
