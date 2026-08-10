# Population Presence (Phase 18)

Phase 15 gave the world a face, Phase 16 gave it a city, Phase 17 gave it time.
Phase 18 gives it **visible human presence**.

The promise is narrow and deliberate:

> Make the city feel inhabited, truthfully, coherently, and deterministically.

Everything below exists to keep the second half of that sentence as true as the
first.

## What a visible person is

A visible body is a **representative population proxy**. One proxy stands for
`residents_per_proxy` real residents of its district, and the manifest says so
in those words on every run.

A proxy is **not** a simulated individual. It has no name, no home, no
destination, no schedule, no job and no behaviour, and there is nowhere in the
plan such a thing could be recorded. Phase 18 answers exactly one question:

> Where, and how, does authoritative district population become visibly present
> in the city?

Nothing here implements crowd simulation, walk cycles, routing, commuting,
traffic, vehicles, pedestrian AI, dialogue, or citizen identity. The Phase 18
boundary test enforces that by reading the layer's **code** — with docstrings
and comments stripped — and refusing any of those tokens.

## Data flow

```
authoritative simulation
        |
        v
Render Export V1  (world.districts[].population)
        |
        v
Population Presence Spec V1        <- the visibility policy
        |
        v
Pedestrian Topology                <- WHERE a body may stand (population-blind)
        |
        v
Population Presence Plan V1        <- HOW MANY, WHICH slots, WHAT posture
        |
        v
LD_POPULATION collection in Blender
```

Three different authorities answer three different questions, and none of them
can answer another's:

| Question | Authority |
| --- | --- |
| How many people are visible? | district population, through the spec's declared mapping |
| Where may a body stand? | the pedestrian topology, proven against Phase 16 occupancy |
| Which bodies are those? | the district's own stable slot pool |

## The scaling rule

This is the whole truth claim of Phase 18, and it lives in the spec rather than
in code:

```
population < visibility_threshold  ->  0 proxies
otherwise  clamp(floor(population / residents_per_proxy),
                 min_proxies_per_district,
                 max_proxies_per_district)
```

The shipped spec uses `residents_per_proxy = 5.0`, which is a declared **visual
density scale**, not a discovered fact. The ratio is a spec value and the tests
prove it: fed `residents_per_proxy = 20.0`, the same code reproduces the
directive's own illustration exactly — 140 residents become 7 proxies, 320
become 16.

A world-wide `global_max_proxies` ceiling exists as a safety limit. It reduces
proportionally by the largest-remainder method when it binds, and the plan
always records whether it did (`global_ceiling_applied`). The canonical world
does not reach it, and says so.

## Stable slot identity

Each district owns a pool of stable slots:

```
district_a__slot_001
district_a__slot_002
...
district_a__slot_032
```

**The pool is computed without ever looking at population.** It is a property
of the district's ground: laid out once, in a fixed order, by a greedy
farthest-point walk over the candidate positions the topology proved clear.
Population then activates a **prefix** of that pool.

That single design decision buys the whole stability contract for free:

```
population 140  ->  28 proxies  ->  slots 001..028
population 320  ->  32 proxies  ->  slots 001..032   (001..028 unmoved)
```

A district that grows **extends** its people; it never re-randomises the street.
A district that shrinks keeps the lowest-numbered slots. Each slot draws its
body variant and posture from a generator seeded by its own slot id, so
activating a twenty-ninth proxy cannot change the appearance of the first
twenty-eight.

## Approved area types

Four, and only four:

| Zone | Ground | Orientation |
| --- | --- | --- |
| `frontage` | the sidewalk band flanking a street's occupied envelope | along the street; the two sides face opposite ways |
| `plaza` | designed plazas, and the civic forecourt ring around the Golden Seal | facing the centre |
| `park` | the landscape plan's declared park zones | facing the centre |
| `promenade` | the landward walk beside the harbour quay | facing the water |

The per-zone `offsets` field means a different thing in each zone, because each
geometry wants a different measure, and the validator enforces the difference:

- `frontage` — metres **outward** from the carriageway edge
- `plaza` — metres **outward** from the source's central protected radius
- `park` — **fractions** of each park zone's own radius (validated to `0 < f < 1`)
- `promenade` — metres **landward** from the quay centre line

Distribution across zones is declared per **district character** (`civic`,
`port`, `residential`, `terrace`) rather than per district id, so the policy
states an urban intention — a port district's people belong on its waterfront —
instead of a lookup table. Slots claim their zone through a divisor-method
interleave that is both proportional to the weights and stable under
truncation; when a zone runs dry the slot falls through to the remaining zones
in weight order rather than being lost.

## Safety: where a body may not stand

Phase 18 reuses the Phase 16 occupancy truth verbatim. Every road capsule,
junction pad, wall corridor, founding building, plate, grove, quay, water
rectangle, production lot, yard row and planted green is already an exact 2D
envelope; the topology loads all of it and tests every candidate against its
own clearance table.

```
ROAD       0.45     JUNCTION   0.45     BUILDING   0.30
VEGETATION 0.25     GROVE      0.25     HISTORY    0.40
WALL       1.20     WATER      1.50
PAVING     open     PLAZA      open     PLATE      open
```

Phase 18 owns a **separate** table rather than extending the locked Phase 16
`POLICY`, because a person is not a building and the two disagree in both
directions: a person may stand on a plaza, on paving and on a founding plate,
which no production building may do, and a person must keep out of the
carriageway that a paving panel is free to meet.

Only three categories are open ground, and all three are designed walking
surfaces. Standing on a founding `PLATE` is safe only because the architecture
rising from it is registered separately as `HISTORY` and keeps its own
clearance — the same reasoning the Phase 16 vegetation policy documents for the
same pair.

Four additions were needed on top of the inherited model, each because the
Phase 16 occupancy model describes *ground* and a standing body is the first
thing that cares about what stands **on** that ground:

1. **Lot plinths** are registered as `BUILDING`. Phase 16 never needed them —
   nothing it places would sit on one — but a plinth is a raised base 0.30m or
   more above the pavement, and a body standing on that footprint at ground
   height would be visibly sunk into it.
2. **Street furniture** — the four Golden Seal lighting masts and every plaza's
   seven masts — is registered explicitly. Both stand on ground the city marks
   walkable, and neither appears anywhere in Phase 16's model. Their replicas
   are pinned against the real Blender objects by the structural suite, and both
   cover the **widest** part of each assembly, because over-covering is the safe
   direction for an obstacle.
3. **Depot pads.** Phase 16 registers each founding depot as a 9.0m circle; the
   pad it stands for is a 13x17 rectangle, which overruns that circle by 1.7m at
   the corners. Those corner lobes are raised industrial ground. Registered here
   as the exact rectangle, so the refusal costs no legitimate pavement.
4. **Ground steps**. The city's floor is deliberately stepped. A body standing
   at the foot of a step is built with the step cutting through its shins, so
   the topology probes a ring at the body's own radius and refuses anything
   where the ground beside it rises more than `STEP_TOLERANCE` (0.12m) above its
   own footing. A kerb is fine; a knee-high edge through a body is not.

Street lamps needed no such treatment: a production lamp post stands at
`class_width / 2 + 0.65`, which is inside the registered road envelope for every
street class the city has (arterial 4.15 < 4.60, collector 3.25 < 3.40).

Every refusal is counted by reason and published in the topology summary. A
silent skip is indistinguishable from ground that was never sampled.

## Standing height

A proxy's feet sit at `presence_ground_level(x, y)`. `city_ground.ground_level_at`
is the authority on the ground the **production** city designed; it is not the
authority on what stands **on** that ground, and everything built on it has to be
added:

- the **founding district plate**, its **ring-road disc** where the composition
  kept it whole, and its raised **civic core** — three solid cylinders Phase 15
  built and Phase 16's ground model never described;
- the **plaza deck**, a 0.14m cylinder raised on the city floor.

This was not free knowledge. The first Phase 18 build placed twelve of eighty
bodies at terrain height on ground whose real floor was up to 0.39m higher —
knee-deep in the founding plates — and the test meant to catch it re-derived the
height from the same function that produced it, so it proved only that the
function agreed with itself. The structural suite now asks **Blender**: an upward
ray from each body's feet that exits through an up-facing surface means the body
is inside a solid, and a downward ray must find real ground within
`MAX_FOOT_DROP`. Buried and hovering are both refusals, measured against the
geometry rather than against the model.

Plinths, yard rows, junction pads and depot pads are the other raised surfaces,
and all four are registered obstacles — nobody stands on them, so nobody needs
their height.

## Determinism

- Every mapping is iterated in sorted order; nothing depends on insertion order,
  and the tests reverse every spec dict to prove it.
- Candidate coordinates are **rounded before they are checked**, not after. A
  candidate proven clear at full precision and then published rounded is a
  candidate nobody checked, and on a polygon boundary the two answers genuinely
  differ. Rounding first also absorbs the last-ulp disagreement between one
  machine's trigonometry and another's, so the plan hashes identically
  everywhere.
- No builtin `sum()` over floats anywhere in the plan path; counts are summed as
  exact integers and weights through `math.fsum`. (CPython 3.12 changed
  `sum()` over floats to compensated summation, which cost Phase 17 a real bug
  between the host's Python and Blender's.)
- Every proxy draws its variant, pose and heading jitter from a generator seeded
  by its own slot id.
- `plan_hash` and `topology_hash` are SHA-256 over canonical sorted JSON, and the
  gate proves that the topology and the plan Blender derived are the ones the
  host's Python derived. Both are needed: the plan only ever observes the
  candidates its slot pools walk, which on the shipped world is well under half
  of them, so a plan digest alone would leave most of the offer uncompared.

## The Blender layer

```
LD_WORLD
└── LD_POPULATION
    ├── LD_POP__district_a__slot_001
    ├── LD_POP__district_a__slot_002
    └── ...
```

- One object per proxy, semantically named, 28 bytes at the longest — well
  inside Blender's 63-byte limit, past which names are truncated and
  replace-by-name idempotency breaks.
- Materials carry their own `LD_POP_MAT__` prefix so nothing Phase 15 or Phase 16
  counts as its `LD_MAT__` family ever changes.
- Bodies sharing a geometry key *and* a colour set share **one mesh
  datablock**. In the canonical eighty-person scene nothing does: the diversity
  system gives every visible resident a different combination of age, build,
  stature, hair, garment, face and pose, so the honest metrics are
  **80 proxies / 80 distinct body meshes / 0 reused instances / reuse ratio
  0.0**. The manifest reports those four names rather than a `shared_meshes`
  count that reads like a saving nobody made.
- Every build clears the objects, the meshes **and the collection** first, so
  rebuilding the same plan converges on the same scene rather than growing
  `.001` copies, and a cleared file carries no trace of the layer at all.
- Every body carries its own bevel modifier. A bevel is object state, not mesh
  data, so bodies that share a datablock do not inherit it — the first builder
  gave it to twenty proxies and left sixty rendering as hard-edged. It is
  2.2 mm: at 5 mm the structural ray probe caught the bevel rounding an eye
  that stands 9 mm proud of the cheek back down to 1 mm, so edge softening was
  quietly re-burying the feature the previous correction dug out.

### The head and face

Every head is assembled in **one explicit coordinate system** — head-local
`+X` forward, `+Y` left, `+Z` up, origin at the centre of the head in plan and
at its base in height — and then carried into body space by a **single rigid
transform**. There is exactly one face-forward convention and nothing infers it
from a pose or a primitive's orientation.

Each feature is placed by its **front surface**, standing proud of the skull:
brow 9.5 mm, eyes 9 mm, nose 16.5 mm, mouth 6.5 mm. Placing by the front rather
than the centre is what makes burying a feature impossible however the head's
depth changes.

Since the head became a faceted hull there is no longer a flat front *plane* to
stand proud of, so each feature is a **conforming plate**: every one of its
columns is pushed out to `head_surface_x` — the skull's real surface at that
height and lateral offset, computed from the same profile the mesh is lofted
from — and then stood proud of it. A brow spans far enough around the cheek to
need three columns; an eye is narrow enough for two.

That distinction is load-bearing, and it has a second edge to it. The skull is
a **polygon**, so its surface has ridges where two facets meet, and a plate
whose columns straddle a ridge is a chord across it — a chord that passes
*through* it. Each column is therefore placed against the furthest-forward
point of the strip of face it is responsible for, half way to each neighbour,
rather than against the single point directly beneath it.

`figure_kit.plate_clearance` walks the plate's **real ruled front surface**
(the quad between each pair of adjacent columns, sampled in both directions)
and reports the smallest gap to the skull under that exact point. The contract
is that this minimum is positive; on the shipped vocabulary it is 3.6 mm at
worst, on the mouth.

Both halves of that were got wrong first, and the wrong version *passed*:
placing columns point-wise buried the eyes 0.9 mm, the brow 2.9 mm and the
beard 10.6 mm, while a clearance check that compared one flat plane — the
plate's most-forward vertex — against the skull could not see any of it. A
guard that cannot fail is not a guard.

| Level (fraction of head height) | Feature |
| --- | --- |
| 0.780+ | hairline — no hair may reach below this |
| 0.735 | brow |
| 0.620 | **eyes** — always a mirrored pair |
| 0.440 | **nose** — on the centreline, between the eyes |
| 0.305 | moustache |
| 0.220 | mouth |

Both defects that shipped in the first candidate are now impossible and both
are pinned by tests: the eyes and brow were authored 3 mm *behind* the head's
front face and so were sealed inside the skull — leaving a nose and no eyes —
and the head turn was handed to each feature as its own spin instead of
orbiting the features around the head, so a turned head kept its face pointing
where the body pointed.

`tests/visual/test_face_contract.py` re-derives every invariant from
the generated geometry across every age × hair × facial-hair × face × pose
combination, and the Blender suite **ray-casts each eye and the nose along the
head's own forward axis** on the assembled mesh: the ray must strike the
feature, not the skull behind it.

### The body

Semi-stylised on purpose, and **not built from boxes**. The first version
described a body as a list of axis-aligned boxes, so however carefully the
proportions were tuned the result read as a voxel character: a cuboid skull, a
peg neck, slab torso sections, rectangular stick arms and rectangular column
legs. The kit now emits a closed geometry vocabulary instead, and there is no
box kind left to fall back to:

| Primitive | What it builds |
| --- | --- |
| `faceted_head` | the skull: 8 facets around, 4 rings plus a chin pole and a crown pole |
| `torso_hull` | one lofted body through hip, waist, chest and shoulder cross-sections |
| `tapered_segment` | a limb chain — shoulder→elbow→wrist, hip→knee→ankle — and the neck |
| `foot_wedge` | a foot with a heel behind the ankle and a toe in front |
| `hair_shell` | a covering that follows the round skull, plus rear volumes |
| `face_feature` | a plate that conforms to the curve of the face beneath it |
| `accessory` | garment geometry that sits on a valid body |

The waist is pinched **by construction** rather than by tuning: it is a
fraction of whichever of the hip and the chest is already narrower, and the
largest product of a build waist factor and a presentation waist factor is
`1.02 × 1.02 = 1.0404`, which times `0.84` is `0.874`. Under one for every
combination in the vocabulary, so no figure can be built barrel-sided.

Build drives real shape at a fixed stature: athletic has the hardest
shoulder-to-waist taper, broad the least and the greatest depth, slim the
narrowest everything. Those are measured from the emitted cross-sections in
`tests/visual/test_figure_kit.py`, not read back from a table.

**The silhouette test.** `phase18_population_silhouette_verify.png` renders
representative figures with one neutral material against a bright field. If the
body shape alone does not read as human there, no palette would have saved it.
`phase18_population_body_geometry_verify.png` is the matching full-length plate
under flat light, where a cube skull, a peg neck, a slab torso, a stick arm, a
column leg or a missing foot would each be plainly visible.

#### Geometry budget

| | Cuboid bodies | Now |
| --- | --- | --- |
| Triangles per person (canonical 80) | 205 | 372 |
| Population layer total | 16,392 | **29,728** |
| Ceiling | 30,000 | 30,000 |

The whole increase bought anatomy. The head keeps eight facets because the head
is what gets inspected; the torso and the hair were cut to six to stay under
the ceiling, which is invisible at diorama distance and is the honest reason
those two are not eight -- though the hair SHELLS are, because a shell with
fewer facets than the skull cannot contain it. Eight everywhere was measured
at 30,908 and did not fit; the remaining headroom is 272 triangles.

Four poses, all **standing** attitudes. Phase 18 ships no walk cycle and no
seating geometry, so a pose is a fixed arrangement of limbs and nothing more:

| Pose | Attitude |
| --- | --- |
| `idle` | feet together, arms at the sides |
| `observe` | head turned, one arm carried forward, weight slightly off-square |
| `stroll` | feet staggered fore and aft, arms counter-swung — the silhouette of walking, held still |
| `rest` | weight on one leg, the other set out to the side |

Five body variants and five muted clothing families, chosen to sit inside the
city's existing material range. Presence should read as people, never as
confetti.

### Familiar, not literal

The world stays legible without leaning on real branding. There are no
trademarks, no logos, and no copied brand identities anywhere in this layer.
What makes the city recognisable is category and behaviourless posture — people
on a pavement, people around a monument, people on a waterfront — not product
placement.

## Files

| Path | Role |
| --- | --- |
| `visual/blender/config/population_presence_v1.json` | the shipped spec |
| `visual/blender/scripts/population_presence_spec.py` | spec contract (pure) |
| `visual/blender/scripts/pedestrian_topology.py` | where a body may stand (pure) |
| `visual/blender/scripts/population_presence_plan.py` | the presence plan (pure) |
| `visual/blender/scripts/population_proof_package.py` | proof package inventory (pure) |
| `visual/blender/scripts/apply_population_presence.py` | the Blender layer |
| `visual/blender/scripts/produce_population_presence_proof.py` | the proof pack |
| `visual/blender/run_phase18_checks.py` | the eight-step local gate |
| `visual/blender/tests/run_blender_tests_p18.py` | structural runner (P15 → P16 → P17 → P18) |
| `visual/blender/tests/test_population_presence.py` | structural tests |
| `tests/visual/test_phase18_boundary.py` | import and scope guards |
| `tests/visual/test_population_presence_spec.py` | spec contract tests |
| `tests/visual/test_pedestrian_topology.py` | topology contract tests |
| `tests/visual/test_population_presence_plan.py` | plan contract tests |
| `visual/blender/scripts/figure_kit.py` | the modular figure and head kit (pure) |
| `visual/blender/scripts/produce_population_style_plate.py` | the style and face QA plates |
| `tests/visual/test_figure_kit.py` | figure kit contract tests |
| `tests/visual/test_face_contract.py` | machine-verified face invariants |
| `tests/visual/test_population_proof_package.py` | package integrity tests |

## Reporting

The plan and the manifest publish every reduction, so no cap is ever silent:

| Field | Meaning |
| --- | --- |
| `scaled_proxies` | what the density scale alone would show |
| `earned_proxies` | after `max_proxies_per_district` |
| `clamped_by_policy` | the difference, per district and world-wide |
| `granted_proxies` | after the world-wide `global_max_proxies` ceiling |
| `active_proxies` | after the ground could not site the whole pool |
| `reduced_by_ground` | that last difference |
| `global_ceiling_applied` | whether the world ceiling bound at all |

On the shipped world every one of these differences is zero, and the manifest
says so rather than leaving it to be inferred.

## Running the gate

```
python visual/blender/run_phase18_checks.py --workspace <fresh dir> \
    [--blender <blender.exe>] [--preview] [--base-sha <sha>]
```

Eight steps: Blender located, the real engine story generated, the pure topology
and plan validated, the structural suite passed in phase order, the proof pack
rendered, the engine's saves and exports proven byte-identical, the manifest's
own verdict checked, and the proof package inventoried and verified.

## Known limitations (V1)

- **Founding avenue sidewalks are not used.** Phase 16 registers a founding
  avenue's whole envelope — carriageway *and* its built sidewalk meshes — as one
  5.9m occupancy. Presence therefore stands just beyond the built sidewalk on
  the adjacent ground rather than on it. Valid and safe, but a future phase that
  split the founding avenue envelope would win back the grandest pavements in
  the city.
- **No dedicated promenade proof frame.** Waterfront presence exists (6 proxies
  in the canonical run) and is verified structurally, but the harbour flood
  masts obstruct every clean camera angle onto the quay walk. Park context is
  shown instead; a promenade frame would need port-side lighting geometry that
  is Phase 16's to change, not Phase 18's.
- **Presence is static.** By design. Nobody moves, and the Phase 17 motion layer
  deliberately does not animate a single proxy — the structural suite asserts
  that no proxy carries animation data at all.
