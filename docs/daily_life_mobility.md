# Daily Life & Mobility (Phase 19)

Phase 18 made the city's people visible. Phase 19 makes daily life visibly
*move*: a deterministic subset of the existing population walks, and ambient
traffic drives the streets the city already has.

> **Pedestrian movement and vehicle traffic in Phase 19 are deterministic
> presentation mobility. They are not individual citizen schedules,
> authoritative destinations, or simulated traffic demand.**

A moving body is the same representative population proxy Phase 18 placed. A
vehicle is an ambient mobility prop with no driver, owner, passenger, cargo or
history. Nothing here is written back into world state, and the engine is never
told any of it.

## The layers

Every module below lives in `visual/blender/scripts/`, and the configuration it
reads lives in `visual/blender/config/`.

| Layer | Module | Purity |
| --- | --- | --- |
| Mobility Spec V1 | `mobility_spec.py` + `config/daily_life_mobility_v1.json` | pure |
| Vehicle kit | `vehicle_kit.py` | pure |
| Vehicle lane network | `vehicle_lane_network.py` | pure |
| Pedestrian mobility and gait | `pedestrian_mobility.py` | pure |
| Combined mobility plan | `mobility_plan.py` | pure |
| Blender mobility runtime | `apply_mobility.py` | `bpy` |
| Proof package contract | `mobility_proof_package.py` | pure |
| Proof producer | `produce_mobility_proof.py` | `bpy` |
| Vehicle QA plates and exotic coupe QA views | `produce_vehicle_style_plate.py` | `bpy` |

Everything above the runtime can be derived, hashed and **disproved** on a
machine with no Blender installed. That is the point: the truthfulness of the
movement is checkable independently of what the render happens to look like.

The QA plates are the one entry that is not part of that chain. They build five
cars on an empty backdrop and nothing else — no city, no plan, no manifest
member — so a reviewer can reject a bonnet without paying for a city render.
They are evidence about the kit, never about what the city contains.

## The loop contract is arithmetic

Frame 1 and frame 193 must be the same state. So every route is a **closed
loop** travelled a whole number of times, and a route's length is therefore

```
cycle_seconds = timeline_duration ÷ cycles
length        = speed × cycle_seconds
```

with no freedom left over. Three consequences follow, and they drive the whole
design:

1. **Vehicle circuits must be 32–80 m long.** At the declared 4–10 m/s band over
   the canonical 8 seconds, nothing else can be driven once, at a legal speed,
   and still close.
2. **A pedestrian's excursion is solved, not chosen.** The walker's speed comes
   from its own body; the excursion is then bisected until the loop is exactly
   the length that speed demands.
3. **Wheel revolutions must be whole.** They are not, for a geometric radius, so
   the count is rounded and a **rolling radius** is solved for — the same
   distinction a real, deflected tyre already has. The declared tolerance is
   5 %, because past that the rolling radius has stopped being a tyre and become
   a different wheel; the widest drift the canonical fourteen actually ask for
   is 1.66 %, on the van.

## Pedestrians

`moving_fraction` (0.30) of the 80 proxies walk; the rest keep standing exactly
where Phase 18 put them. Selection is a stable per-slot draw, so growth never
reshuffles who walks, and a slot whose ground cannot carry a legal route is
skipped with its reason recorded while the next eligible slot takes its place.

A route is a **closed racetrack** around a corridor derived from the same
geometry Phase 18 sampled its standing candidates from — a street's own
polyline, a plaza's or park zone's own centre, the harbour's quay line. Out
along one side, a half-turn, back along the other, a half-turn home. The heading
is continuous everywhere; there is no frame on which a walker reverses.

A deterministic ladder is tried in a fixed order, and the whole ring comes
**first**. When a plaza or park ring's circumference is one that *some* legal
walking speed closes in a single cycle, the walker simply strolls all the way
round it at the pace that length demands — there is no half-turn to justify at
all, so it is the best route this phase can offer and it is never held back for
a racetrack. The racetrack ladder follows behind it, and is what a walker gets
when the corridor is not a ring, when the ring is the wrong length, or when the
ring route is offered and fails to prove clear: the walker's own pace and then
progressively slower, and within each pace the anchor at the start, middle or
far end of the walk, and within each anchor both lateral sides — outward before
inward, so the return leg steps away from the carriageway rather than towards
it. Each of those is attempted in both directions along the corridor before the
next is reached. The first candidate that is proven clear wins.

### Gait

The stride is tied to the travel and cannot be set independently:

```
cycles          = round(route_length ÷ (0.83 × height))
stride          = route_length ÷ cycles
leg swing       = asin(stride ÷ (4 × leg_length))
```

so a walker whose feet cycled faster than it travelled is not a bug that can be
introduced — it is a number the arithmetic refuses to produce. Arms swing in
antiphase to the leg on the same side.

The body is the **Phase 18 body**, articulated: limb rings are rigidly rotated
about real joints, so segment lengths are preserved and no seam opens. The
whole figure is then lifted so its lowest foot vertex rests exactly on the
ground, which is what produces the vertical bob a viewer reads as weight.

What a limb is made of is no longer this file's opinion. `body_chains` reads
`figure_kit.CHAIN_SPEC` — the kit's own published description of which
primitives form each chain, how many rings each holds, which articulation
level every ring rides at, and which member's ring each joint is measured
from — and recovers the four chains from the built vertices against it. That
is what let the figure kit's visual rebuild grow a five-ring leg with a calf,
split the arm into a socket-shouldered upper arm, a forearm and a hand, and
hang the hand off the wrist, without one line of walking code changing. A body
whose primitives do not match the published spec is refused, never repaired.

The rebuild left the walking arithmetic alone on purpose: the kit's published
HEIGHTS are bit-frozen, so every speed, every route length and the whole
population layout are exactly what they were.

## Vehicles

Lanes are offsets of the **locked Phase 16 carriageways**, never hand-drawn
paths. `ROAD_CLASS_WIDTHS` is the driveable surface; `road_occupancy` is the
wider envelope including pavement, and a vehicle never reaches it — which is
what makes vehicles and pedestrians structurally separate.

| Policy | Condition |
| --- | --- |
| `dual` | the carriageway holds two lanes plus margins; right-hand traffic puts each on its own side |
| `single` | it holds one centred lane; the run is claimed by exactly one route in one direction |
| `refused` | not even one lane fits |

### Which runs the network will not offer at all

A run is one stretch of carriageway the network could put a lane on. The
canonical world offers **55** of them and refuses **14**, and every refusal
carries the reason it was refused, so a street that cannot take traffic says why
rather than quietly vanishing. Three reasons exist, and the canonical mix is
pinned per reason:

| Refusal | Why | Canonical |
| --- | --- | --- |
| buried | the founding ring sector here was buried by the final composition, so a vehicle driving it would drive through the ground | 4 |
| founding architecture | the carriageway here passes through a founding building, which the reason names | 10 |
| no lane fits | the carriageway half cannot hold one lane of the declared envelope, so `lane_policy` returns `refused` | 0 |

The first is geometric and pre-existing. The second is new, and it is the lane
network declining to TRUST the placement contract. Five founding buildings still
stand in carriageway plan-space, and the Director has formally accepted that as a
**permanent compatibility exception** rather than an open defect: four of them
have no legal position anywhere on their own plate, and the relocation the fifth
could have taken was declined (`docs/production_world.md`). Rather than let
that become a van driving through a podium, `_founding_obstruction` sweeps each
run's carriageway as a capsule against those buildings' real footprint
rectangles — the same rectangles the drawn road is trimmed against, so the
picture and the traffic cannot disagree about where a building stands — and
refuses the whole run. Ten runs are lost that way. **No vehicle is ever routed
through founding architecture, including where the geometry still overlaps.**

Because the overlap is permanent, so is the refusal. These ten runs are not held
back pending a relocation that will eventually free them; there is no such
relocation, and the guard is the accepted term on which the exception stands.

Four of the five buildings are named in refusal texts —
`LD_BLDG__district_a__000`, `LD_BLDG__district_a__002`,
`LD_BLDG__district_c__000` and `LD_BLDG__district_c__001`. The fifth,
`LD_BLDG__district_a__001`, stands on `ring_district_a#2`, a run already refused
for a building the sweep met first. That is why the cross-check below is
containment rather than equality, and no circuit in the canonical plan uses any
refused run.

Pinning the mix per reason rather than as a bare total is deliberate: the two say
different things about the city, and a count that moved from buried to founding,
or the reverse, would leave fourteen untouched while the network had started
refusing a completely different set of streets. Each founding refusal must also
name the building it hit, and every name it gives must be one of the five the
fabric plan publishes as blocked — so a refusal can never point at a building
nobody has admitted to.

Refusals are published, not merely counted: `refused_runs` carries the id and the
reason for each, beside the `runs_offered` and `runs_refused` totals.

Two route families are offered. **Circuits** come from the network's own cycles.
**Out-and-back** routes run between two declared terminations and turn round in
the bulbs the city built for turning — a half circle at a real radius, then a
tangent-continuous merge back into the returning lane.

Selection is an exact search over mutually compatible route sets. It reaches the
canonical vehicle target first, then maximises **geographic spread**, because a
technically valid traffic system that animates one corner of the city is not a
daily-life result. Compatibility is structural, not scheduled: two routes must
never bring the largest vehicle on each within the declared body clearance, at
any point, whatever the timing.

### Two envelopes, named for what they are

The kit reports **two different numbers**, and the distinction is load-bearing:

| Name | What it is |
| --- | --- |
| `RESERVED_PLANNING_ENVELOPE` | A **reservation**. Lane widths, headways, slot pitch and turning fillets were all derived from it before the bodies were ever reshaped, and the fourteen canonical vehicles descend from those numbers. |
| `measured_visual_bounds()` | A **measurement**, read off the vertices the kit actually emits. |

`vehicle_dimensions()` deliberately reports the *reservation*, and the planners
read only that. If it reported the sculpture instead, restyling a car — even
shrinking it — would silently re-plan the city's traffic, and a redesign that
quietly changed which streets carry cars is a far worse defect than an
unconvincing bonnet.

The reservation is therefore not a claim about the geometry; it is a promise the
geometry has to keep. `envelope_contract()` states both numbers side by side
with the proof, and `component_containment()` checks **every emitted lump on its
own** — body, glazing, mirrors, lamps, arches, door furniture and all four
wheels moved to the corners they are actually fitted at. A bounding box over the
whole car is dominated by the body and would hide a mirror hanging out into a
lane the network does not know about.

Only the contract reaches the proof manifest. It carries each archetype's
reservation, measurement and headroom in full, but the containment check reaches
it condensed — a verdict, the number of components measured, and the names of
any that escaped — rather than as a per-part slack table, because those are the
three facts a reader or a gate can act on. And a gate does act on them: a
manifest whose contract block is missing, empty, or names an escapee is refused
outright, since a containment verdict nothing reads is decoration that would
print PASS underneath `contained: false`. The suite also proves the checker is
capable of failing.

### The exotic coupe has its own hull

Four archetypes are a lower body with a cabin standing on it. That construction
is honest for a hatch, an estate, a saloon and a van, and it cannot produce an
exotic — measured on it, the coupe's shoulder line was flat to within 15 mm over
95% of its length, its cabin was inset 255 mm per side from a constant-width
slab, and the hull's top and the cabin's floor met as two flat planes at every
station. No dial on a shared builder fixes that, because the shared builder
cannot vary a body's width along its length.

The coupe therefore has its own procedural longitudinal profile. It is still
deterministic, still low-poly and still inside the same reservation; the volumes
are still separate primitives, because the suite recovers a hull, a cabin and a
boot by measuring them. What changed is the shape:

| | shared builder | coupe hull |
| --- | --- | --- |
| rear haunch over the door waist | 14.7 mm/side | **78.0 mm/side** |
| rear fender over front fender | 0.0 mm | **22.0 mm/side** |
| ledge under the windscreen base | 254.8 mm/side | **62.0 mm/side** |
| shoulder-line fall to the nose | flat over 95.5% | **209.6 mm** |
| deck width over the canopy at the haunch | flat slab | **132.0 mm/side** |
| tyre outline buried in its own fender | 6.25% | **0.00%** |

Three details are constraints rather than taste. The hull's top edge is left
**crisp** while its bottom is chamfered, because that edge is the shoulder line
and everything above the beltline lands on it. The canopy's side stays
**vertical** through the glazed band and leans in only above it, because a side
light has to be flat in Y to read as one pane and so cannot follow a leaning
surface. And the canopy stations between the windscreen's two ends sit exactly
on the straight line joining them, because the windscreen is one flat quad and
anything else lets paint rise through the glass.

## Safety

Every route is proven clear before it is accepted, and then the finished plan is
re-proven from its own published numbers on **every frame** of the canonical
timeline — all 193 of them, because the declared frame stride is 1. Four dynamic
pair classes are swept there:

```
walker / walker            walker / stationary proxy
vehicle / vehicle          walker / vehicle
```

Static checks stopped being enough the moment anything moved: two routes that
never overlap in space are safe, but two that cross are only safe if they never
cross at the same *time*.

**Mover against the static city** is a separate route-validity proof, not a fifth
timeline-swept pair class, because it does not depend on time. A walking route is
proven against the Phase 18 occupancy along its whole length before it is
accepted, and a lane is refused the moment any of its sampled stations leaves
the carriageway, so a route that could touch the city never becomes a plan in the
first place. What the timeline sweep could not catch is the runtime getting the
built scene wrong, so the structural suite re-checks it there instead: walkers
by ray-casting the real geometry under their feet, vehicles by testing their
evaluated transforms against the road graph's own drivable envelope.

There are **no crosswalks in V1**. A pedestrian route may never enter a
carriageway, which is checked explicitly as well as through the clearance table
— redundantly, because a proxy standing in traffic is the single most damaging
thing this phase could ship.

## The Blender layer

`LD_MOBILITY` holds vehicles (`LD_VEH__vehicle_slot_NNN`, each with four wheel
children named `…__wheel_<corner>`), paths (`LD_MOBILITY_PATH__*`), actions
(`LD_MOBILITY__*`) and materials (`LD_VEH_MAT__*`). Two more families are named
for the same reason and are easy to miss: the vehicle mesh datablocks are
`LD_VEH_MESH__*`, so clearing can find and drop them by name rather than by
memory, and the gait shape keys are `LD_GAIT__*`, so what Phase 19 added to a
borrowed Phase 18 body is legible in the file itself.

Motion is a **cyclic poly curve with an animated `eval_time`** rather than baked
keys: Blender's path table is arc-length parameterised, so speed is constant and
the loop closes by construction. The curve must be densely sampled — Blender
interpolates orientation between control points, and a coarse curve reports a
heading averaged across a whole straight.

A walking proxy is **borrowed, never rebuilt**: Phase 19 adds a follow-path
constraint, a set of gait shape keys and a zeroed transform, and takes all three
away again. Clearing restores the exact Phase 18 population, which the structural
suite proves by comparing every transform exactly and every mesh by its vertex and
polygon counts (with the gait shape keys proven gone) before and after.

## The proof cameras are themselves tested

A proof is only worth the pictures it takes, and a camera can fail silently:
stand it outside the round diorama and it renders black, bury it in a wall and
it renders a wall, park it on a carriageway and a van drives through the lens.
None of that shows up in a plan hash, a collision sweep or a loop measurement,
so the structural suite checks the cameras against the built scene:

* every proof camera must land at least half of its own frustum on solid city
  within the 110 m the volumetric shell still transmits, must have its nearest
  surface further than a metre away, and must see at least **three distinct
  objects** — one or two surfaces filling the whole frame is what a camera
  inside a wall renders, and it is not a picture of a city;
* no mover's root may come within 1.5 m of any proof camera on ANY canonical
  frame, swept frame by frame rather than sampled, because a car crossing the
  lens for twenty frames is invisible to a three-frame sample. The sweep
  measures the mover's root, not its body surface, so the threshold is a
  root-distance floor rather than a body-clearance guarantee.

## Honest limitations

* Only part of the road network can carry a legal closed route. The route
  offer is measured and reported — candidates attempted, viable, selected,
  which segments carry traffic and which do not, and for every region that
  offered a route but could not use one, the geometric reason. The proof frames
  deliberately show the whole diorama, including the quiet quarters.
* Ten runs are quiet because founding architecture stands in their carriageway.
  The five buildings responsible are not deleted to make the streets work: four
  have no legal position anywhere on their own plate, the fifth had one and it
  was declined, and the Director has accepted the whole set as a permanent
  compatibility exception. This is a permanent, named and published cost, not a
  defect awaiting a fix. What the phase guarantees is the part that shows: no
  vehicle is routed through a building.
* Junction fillet radii are small by real-car standards. On a 5.2 m collector
  meeting another at a sharp angle the geometry leaves no room for a realistic
  turning circle, so the declared floor is generous rather than strict, and
  turns beyond 150° are refused outright rather than approximated.
* Vehicle speed is constant along a circuit. Cornering is therefore brisker
  than a real driver would take it; this is a declared presentation convention,
  not a claim about traffic behaviour.
