# Production World (Phase 16)

## Purpose

Phase 16 turns the founding Phase 15 world into a production-scale city
that reads as DESIGNED. The locked simulation, the Render Export
contract, the Master Scene Spec, and every semantic anchor -- the
district plates and their architecture, the wall stations and the scar,
the Golden Seal, the harbor, the depots, the founding avenues -- stay
exactly as reviewed. Around them the production layer builds an authored
city: a designed street network with a real hierarchy, eight visual
quarters nested inside the four authoritative districts, street-fronting
urban fabric with a deliberate middle scale, and intentional
landscaping.

The aesthetic-first mandate (the Phase 16 final redesign) sets the
priorities explicitly: visual beauty, believable urban logic, clean
spatial realism, strong scale, memorable identity, simulation semantic
consistency -- and only then legacy presentation geometry. World HISTORY
is preserved; every old decorative TRANSFORM is not sacred.

The FINAL URBAN COMPOSITION pass states the rule in its sharpest form:

    LOCK MEANING. NOT ARBITRARY PRESENTATION GEOMETRY.

The four authoritative districts keep their identity, state, topology,
and relationships exactly. What they do NOT keep is the circular floor
they happened to be drawn on: the founding plates' ring-road annuli were
useful during the visual proof and read as DISTRICT PODS at production
scale. The composition reinterprets that ground into designed, continuous
city floor, so a viewer sees one city instead of several islands joined
by roads.

## Boundary rules

Everything Phase 15 established still holds at the code level. The
Blender layer consumes only Render Export V1 plus the two presentation
specs; nothing under `visual/blender/` imports the engine (pinned by the
Phase 15 AST sweep, which covers the new files automatically). The five
planning modules -- `production_spec.py`, `road_graph.py`,
`spatial_occupancy.py`, `urban_fabric.py`, `city_ground.py` -- are pure
Python with no `bpy`, so the entire production plan is provable under
ordinary pytest before Blender ever runs.

One Phase 15 source file did change, and it is worth naming rather than
burying: the visual remediation taught `build_master_scene.py` to trim
its avenues and spurs around the founding architecture standing on them,
so the founding build no longer reproduces the original drawing face for
face. Nothing SEMANTIC moved with it -- no district, building, seal,
avenue centre line or camera is at a different place than it was -- and
the structural suite still proves that inside Blender every run. What
changed is which faces get drawn, and `docs/blender_master_scene.md`
states the trim in full.

## The obstacle priority model

The redesign's core rule (`spatial_occupancy.PRIORITY_CLASSES`):

    CLASS A - immutable semantic history: wall lines, founding plates
              and architecture, the Seal, the harbor, water
    CLASS B - chosen city structure: the designed streets and junctions,
              plazas, and the preserved founding groves
    CLASS C - flexible architecture: designed blocks first, then
              production lots (they ladder back or shrink, never
              displace B)
    CLASS D - decoration: production vegetation, planted LAST

Note what is NOT Class A: the circular ring-road surface a plate happens
to be drawn with. The plate's TERRITORY is immutable -- no production
building ever stands on the historic core -- while its FLOOR is
presentation the composition may reshape.

The founding ARCHITECTURE standing on those plates is Class A in its own
right. `spatial_occupancy.founding_building_footprints` replays the
locked Phase 15 lot sampler draw for draw -- eight buildings, none of
them on the port plate -- and now replays each archetype's real GROUND
PLAN with it: the civic podium and its entry canopy, the port shed and
its door trim, the residential block with its balconies and its two
wings, the terrace's stepped tiers. `founding_building_lots` still hands the
obstacle model one conservative disc per building, because over-covering
is the safe direction for a tree, but the disc now sits at the building's
audited position and the rectangles are what every measurement reads.

### The five buildings that keep their founding ground

The census exists because the founding sampler accepted a lot by the
distance from its ORIGIN to a road, while a civic podium and its entry
canopy reach 8.53 m from that origin. Seven founding footprint rectangles
ended up standing in legal driving space, and
`founding_building_footprints` therefore runs an
exhaustive placement pass per lot -- three thousand ladder rungs sorted
by real ground displacement, so a lot moves exactly as far as legality
demands and not a step further, relaxed to a fixpoint so a lot vacating
its ground can free a neighbour the previous round had nowhere to put.

Exactly ONE rule is a MANDATE: every part of every building clears every
founding carriageway by 0.6 m. That rule, and only that rule, may
relocate a locked building. The Seal plaza and its compass masts, the
wall alignments, the depot pads, and the gap between two founding
buildings are PRUDENCE -- they bind only a position the ladder is already
moving a building to, never ground Phase 15 chose. The distinction was
learned the hard way: as mandates they relitigate pre-existing conditions
that are nobody's defect, and one of them dragged a building that already
cleared every road by 3.57 m down to 0.70 m to satisfy a gap rule nobody
had asked for.

The honest outcome is that the remediation moves ZERO founding buildings,
and the Director has formally ACCEPTED that outcome as a PERMANENT
COMPATIBILITY EXCEPTION. Five Phase 15 founding buildings intersect legal
carriageway PLAN-SPACE, they will go on intersecting it for as long as
the founding world is reproduced, and nothing here is a fix in progress.
The rest of this section is the whole of it: how it happened, why four of
the five cannot be corrected, why the fifth is a decline rather than an
impossibility, and why the consequences stop at plan space.

The root cause is a LEGACY PHASE 15 PLACEMENT DEFECT, and naming it that
way is the point -- nothing the production layer did caused it.
`founding_building_footprints` pass one replays the founding lot sampler
exactly as Phase 15 wrote it, and Phase 15 accepted a lot when

    _distance_to_polyline(x, y, boundary_path) >= road_clearance

with `road_clearance` 8.5 m on a civic plate and 10.0 m on a residential
one. That is the distance from the LOT ORIGIN to the avenue CENTRELINE,
and it is wrong in three separate ways. It never subtracts the
carriageway's own half-width -- 3.5 m on an avenue, 2.6 m on a ring or a
spur. It never adds the footprint's own reach -- 8.53 m for a civic
podium with its entry canopy, 11.18 m for a residential block with its
two wings. And it never tests the plate rings or the spurs at all, only
the avenue polylines and the wall stations.

The results are as arbitrary as that measure. `LD_BLDG__district_a__000`
cleared the gate by 0.0903 m on a number wrong three ways.
`LD_BLDG__district_a__001` stands 2.33 m from the centreline of
`ring_district_a`, and `LD_BLDG__district_a__002` 2.30 m from the
centreline of `ring_district_d` -- rings pass one never looked at -- so
their podiums sit on the ring road with its centreline running
underneath them.

The five keep their founding ground. They are neither moved nor deleted,
and they are published by NAME:

    LD_BLDG__district_a__000   LD_BLDG__district_a__001
    LD_BLDG__district_a__002   LD_BLDG__district_c__000
    LD_BLDG__district_c__001

as `plan["founding_blocked"]`, counted in the summary as
`founding_blocked_buildings`, and pinned by name rather than by count so
the set cannot quietly change size. Measured from the same footprint
rectangles every other check reads, this is how deep each one reaches
into each carriageway's plan-space -- its own half-width, measured from
its own centreline:

    LD_BLDG__district_a__000  avenue_boundary_ab           1.7214
                              spur_boundary_ab_district_a  0.3934
                              ring_district_a              0.3090
    LD_BLDG__district_a__001  ring_district_a              2.6000
    LD_BLDG__district_a__002  ring_district_a              2.6000
                              ring_district_d              2.6000
    LD_BLDG__district_c__000  avenue_boundary_ac           1.5341
                              ring_district_a              1.3805
                              ring_district_c              0.8307
                              spur_boundary_ac_district_c  0.6341
                              spur_boundary_ac_district_a  0.5561
    LD_BLDG__district_c__001  avenue_boundary_cd           1.8421
                              spur_boundary_cd_district_c  0.9421

A depth of 2.6000 is the collector half-width in full: the ring's own
centreline passes inside the podium rectangle.

That four of the five cannot be corrected is established rather than
assumed, and the searches below cover all five. Every rung of every
ladder is refused -- three thousand of them
per lot, twenty-five radial steps of half a metre by a hundred and twenty
angular steps of three degrees, relaxed over three rounds. Lowering the
mandate does not help: re-running the same pass with
`FOUNDING_CARRIAGEWAY_CLEARANCE` set to 0.30, 0.10, 0.05 and finally 0.00
leaves the identical five blocked and still moves nothing. At ZERO
clearance -- asking only that no building overlap a carriageway at all --
not one of the five is freed, so the 0.6 m margin is not what costs them
their positions.

Sweeping each whole plate on a half-metre grid says what does. Of 8497
sampled positions on the civic plate and 5525 on the residential plate,
NOT ONE is legal for any of the five. Ground that clears every
carriageway does exist -- 557 positions for `LD_BLDG__district_a__000`,
863 for `LD_BLDG__district_c__000` -- and every last one of them is
already held by Class A history: on the civic plate by the Golden Seal's
plaza, its compass masts, or a wall corridor; on the residential plate by
a depot pad or by another founding building. The plates are
over-subscribed, and they were over-subscribed the day they were drawn.
Three pairs of founding buildings interpenetrate on their own original
ground right now, by 3.9179 m, 2.3110 m and 0.3807 m.

The fifth, `LD_BLDG__district_a__002`, is in the set for a different
reason, and the difference is worth stating plainly rather than hiding
inside a count of five. The shipped ladder reaches no legal rung for it
and the plate grid finds nothing either, but the adjudication located a
legal position for it OFF the ladder, in a pocket no rung lands in, with
roughly 15 mm of clearance. Reaching it would mean refining the
relocation ladder for the sake of fifteen millimetres. The Director
declined. So four of the five are irreducible and the fifth is a
deliberate decision to leave a locked Phase 15 building where Phase 15
put it. The published residual is five either way, and NONE of the five
is fixed.

What the exception is not is a road drawn through a wall or a vehicle
driven through a podium. The consequences are contained, and containment
is the reason this is acceptable at all:

NO VISIBLE INTRUSION. The drawn road surfaces are trimmed around these
same founding footprints (`docs/blender_master_scene.md`), so no asphalt,
sidewalk, curb or marking is rendered inside a building. Ten drawn faces
stood inside founding architecture before the trim, carrying 52.4261 m2
of built road surface standing on architecture; after it there are zero
faces and zero square metres. Blender proves it on the built meshes
themselves, in `test_no_built_road_mesh_stands_in_founding_architecture`
and `test_no_built_road_face_straddles_founding_architecture`.

NO VEHICLE ROUTED THROUGH ARCHITECTURE. `vehicle_lane_network` refuses
any run whose carriageway capsule intersects founding architecture, and
names the building it hit. Ten runs are refused that way
(`docs/daily_life_mobility.md`), and no canonical circuit uses any of
them.

THE RESIDUAL IS PUBLISHED AND PINNED.
`spatial_occupancy.founding_blocked_buildings` returns the NAMED set, the
plan publishes it as `founding_blocked` and the summary counts it as
`founding_blocked_buildings` = 5. One regression test pins the five BY
NAME rather than by count, so a swap cannot hide inside the total, and
another cross-checks that every building a lane-network refusal names
appears in the published residual.

PLAN-SPACE ONLY. The overlap is between building footprints and declared
carriageway plan-space. It has no presentation consequence and no
mobility consequence; it survives in plan space and nowhere else.

Both protections are permanent for the same reason the residual is. The
trim and the refusals are not workarounds waiting for a fix to land --
they are the accepted terms of the exception, and removing either one
would put road surface back inside a podium or a van back inside a wall.
A residual nobody counts is a residual that grows, which is why this one
is published and pinned rather than merely described.

The planner enforces the hierarchy by ORDER: world structure, historical
anchors, designed primary and secondary streets, LEGACY CLEARING, urban
blocks, massing, public realm, industry, vegetation, detail. The
validator (`PlacementValidator`) is the final physical-law guardrail,
never the city planner: collision-free is necessary, DESIGNED is the
point. Its one sharp edge is that a candidate is exempt from its OWN id
so an entry can be re-audited against everything else -- which is sound
only while ids are unique, so placing a live id twice is now refused
outright rather than allowed to hide a real overlap.

## Standing on the ground that is actually there

The composition gives the world a stepped floor -- terrain, ground cells,
plate skirts, plate tables -- so 'the ground' is no longer one number per
quarter. Every lot, tree, container row, and plaza is placed on the
height of the highest ground beneath its own position
(`city_ground.ground_level_at`): buildings clear it by a small plinth
lip, trees sit exactly on it. A per-quarter constant would build the
lower quarters sunk into their own pavement and float their trees above
it.

## Legacy clearing: freedom used deterministically

The founding vegetation is decorative presentation (Class D). The
landscape plan declares PARK ZONES; a founding cluster is preserved
exactly when every tree of it stands inside one park zone AND genuinely
clear of the designed streets (canopy envelope plus keep margin).
Everything else is cleared for construction -- roads never bend around a
decorative tree -- and the city is deliberately re-landscaped afterward
with street tree lines, park groups, courtyard trees, and a quay
promenade, every planting individually validated.

The decision is a pure function (`plan_legacy_clearing`), pinned both
directions by tests: the Blender build suppresses exactly the plan's
`removed_objects` and nothing else; resurrecting a cleared cluster or
dropping a preserved one fails validation; and rebuilding the Phase 15
master scene alone restores all forty clusters, proving legacy
reproducibility is untouched.

## The urban ground: removing the pod effect

`city_ground.py` (pure Python, no `bpy`) computes the composition's
ground. Two systems together retire the circles.

TABLES AND SKIRTS reshape each plate. Which ring arcs remain real streets
is READ FROM THE ROAD GRAPH, not declared by hand: every junction on a
founding ring is an azimuth, and any gap between consecutive landings
wider than `bury_gap_deg` carries no traffic and is buried. Per district
the plan emits two terraced tiers -- a TABLE just above the old annulus
(sweeping from inside the historic core edge in buried sectors, from the
annulus edge in kept ones) and a SKIRT stepping down to the surrounding
city on an authored polygonal profile. The civic district keeps its
complete Ring around the Golden Seal by declaration (`ring: full`),
because that circle is intentional civic form rather than an accident:
the phase turns on exactly that distinction.

GROUND CELLS carpet the quarters -- authored polygons of paved block
ground, civic concrete, and park lawn that weld streets, plinths, parks,
and frontages into one continuous fabric.

History keeps its ground unconditionally. Every panel boundary is
SAMPLED, not merely cornered, against the wall corridors, the Seal
plaza, the harbor, and the diorama extent; where a corridor crosses a
sector the ground is never bridged -- the sector SPLITS and the reserved
alignment stays an open seam in the city floor. The planner builds to a
stricter clearance than the contract it is later audited against, so a
panel can never pass its own build and fail its own audit.

Burial is judged as a measured RUN, not a claim: `rim_exposure` walks the
WHOLE circle -- never only the arcs the plan itself chose to bury, which
would let a plate that buried nothing score a vacuous zero -- and reports
the longest stretch of plate rim that is neither covered by a table
panel, nor carried by a kept ring arc, nor legitimately withheld by
history or water. The contract caps it at `MAX_RIM_EXPOSURE_DEG`; the
canonical plan measures at most seven degrees on any plate, which reads
as history's own seam rather than a circle. The number is published in
the plan and the manifest.

Every landing keeps its carriageway. Burying a ring right up to the point
where a road meets it would leave a founding spur ending on bare paving,
so each landing retains a short forecourt of real street and only the
empty sweep between them disappears.

A buried ring is not quietly covered over. The production build
SUPPRESSES the founding ring disc of every partly-buried district and
redraws the kept arcs as real carriageways, and the occupancy contract
follows suit -- a buried sector is neither road nor obstacle, because it
is no longer a street. The Phase 15 legacy build still reproduces all
four discs; suppression happens only when the production world is added,
exactly as it already does for cleared vegetation, and the structural
suite pins both sets in both directions.

A district that KEEPS its ring keeps a real disc, so that disc has to
answer for the towers standing on it. `trim_kept_ring_discs` rebuilds the
disc of every `ring: full` plate as a fan that omits the wedges founding
architecture occupies and caps the ends the omission exposes, from the
same footprints the ribbon trim reads. On the canonical world that is
`district_a` alone, and twenty of its seventy-two wedges are left out.
The object keeps its name and the rest of the circle survives: the civic
ring is still the intentional civic form the composition declared it to
be, minus the paving its own podiums stood on.

## Designed urban blocks

Streets were already authored; with the final pass the CITY WALL is too.
A block in the Production World Spec is city planning drawn by hand: the
street it fronts, which side, the along-range, depth, unit count, and
height. `_plan_designed_blocks` runs FIRST, before any sampled frontage,
so the composition's deliberate rows, courts, corners, and mid-rise
shoulder claim their ground before opportunistic fabric fills around
them, and an explicit `priority` states what matters most -- adding a
minor mews can never displace the crescent that fronts the orbital.

A block is ONE lot carrying several attached masses, exactly as the row
vocabulary already works, so a terrace's own units never fight each other
for clearance; the block competes with the city, not with itself. It is
still an ordinary Class C candidate: the validator proves it, and a block
that does not fit sheds units from its far end and REPORTS the loss
rather than silently thinning.

The city also gained the vocabulary its ground actually has. Between the
founding plates, avenues, and wall corridors this world leaves parcels
five to eight metres wide -- too narrow for a slab. `midrise_point` and
`midrise_pair` are the middle scale in those parcels: what a real dense
city builds on constrained land. They carry the urban shoulder into slots
that would otherwise hold one lonely cottage, and `INFILL_KINDS` decides
per profile whether a leftover slot builds UP (the shoulder quarters) or
stays genuinely low (garden, meadow, and working quarters).

## Simulation districts vs visual quarters

A SIMULATION DISTRICT remains an authoritative Render Export entity; the
four of them remain the only districts that exist. A VISUAL QUARTER is a
presentation subdivision nested inside one district's expanded
territory:

    district_a (civic)        westfront, wallside
    district_b (port)         quay_north, harborworks
    district_c (residential)  southside, west_meadow
    district_d (terrace)      garden_north, eastgate

The Production World Spec V3
(`visual/blender/config/production_world_v1.json`, format
`living_diorama_blender_production_world`, schema_version 3) declares
per district an `expansion_radius`, per quarter a center, radius,
massing profile, height scale, elevation, and optional plaza anchor or
yard street; in V2 the complete DESIGNED street network and the landscape
plan; and in V3 the DESIGNED BLOCKS and the URBAN GROUND -- per district
a ring mode and skirt profile, plus the authored ground cells. A quarter
referencing an unknown district, standing on a founding plate,
overlapping another quarter, or reaching into the harbor is refused
(`ProductionContractError`), never repaired, and so is a block fronting
an undeclared street or a district missing from the composition. The
quarter count is held to the 8-12 band.

## The designed street network

Every production street is an AUTHORED polyline in the spec --
`road_graph.py` builds exactly what the designer drew and never bends,
trims, or reroutes it. The plan:

- the **orbital boulevard**: one smooth sampled curve (fifty-one
  vertices from a radius profile) sweeping from the port's north gate
  around the north, west, and south of the city to the port's south
  gate; its bulges are geographic -- out around the terrace highlands,
  pinched between the residential highlands and the rim;
- **radial boulevards** from founding ring landings to the orbital
  (north, west, south) plus the **gate_west** civic approach continuing
  the Seal district's axis to the orbital;
- the **cd extension**, continuing the founding cd avenue north to a
  Y-merge with the west boulevard -- production streets grow out of
  founding streets;
- the **eastgate axis**, a straight business spine from the scar-meadow
  overlook to the orbital, threaded between two preserved groves;
- the **southside** high street sweeping up from the south boulevard
  into a small grid with the city's market square;
- the **wallside street**, running parallel to the scar across a green
  buffer -- the quarter that grew against the wall keeps a respectful
  distance the buffer makes visible;
- the **works spine** arcing from the grid corner to the orbital before
  the south port gate, with a container yard lane;
- garden lanes, mews, and service stubs, each ending in a junction or a
  declared termination from the fixed taxonomy.

The connectivity contract is enforced as data (`validate_road_graph`):
no zero-length legs, no duplicate or collinearly overlapping streets, no
via junction off its street, every crossing registered as a shared node
(including designed vertices resting on another street), every open end
either a shared junction or a termination from the taxonomy, one single
connected component anchored at the founding network, no production
street across any wall-station line (crossing the scar stays the
privilege of the founding avenue and its controlled gate), no street
over a founding plate, none in the harbor water, none beyond the
diorama.

## Urban fabric

`urban_fabric.py` decides every mass through the validator, in the
master-plan order. Designed FRONT RUNS place the street walls first:
continuous mid-rise rows on the declared frontage windows (the westfront
crescent on the orbital, the eastgate business axis). The citywide walk
then fills every street compound-first -- rows, courts, duos, slabs,
sheds from each quarter's profile vocabulary, with second-row companions
-- and only afterward places small in-fill, so big masses claim the
prime frontage. A frontage lot's ray to its street may cross no other
street and no wall alignment: fabric never tunnels into back pockets.
Ground is derived from the lots themselves: rectangular plinths with
paved frontage strips -- blocks against streets, never pods.

### The plinth is validated too

A plinth was the one part of a lot the occupancy contract never saw. The
masses were validated; the ground slab they stand on was not, and it is
wider than they are -- so four production plinths stood inside
carriageway plan-space while every building above them cleared. A
foundation does not belong in the street whether or not anyone can see
it, so `plinth_shape` is now laddered and audited like everything else,
against the carriageways and junction pads directly rather than against
the wider occupancy envelope a frontage strip legitimately meets.

The rule is a PREFERENCE, never a veto. Every placement ladder --
designed blocks, front runs, the citywide walk and its rear companions,
and the interior in-fill -- now tries all of its rungs once demanding a
clear plinth and then, if none took, tries exactly the same rungs again
without that demand. A lot can move to satisfy the rule; a lot can never
be LOST to it. The first attempt did not have that shape, and it did not
push the four offending lots back a rung as intended -- it deleted them,
taking the city from eighteen lots to fourteen.

The four keep their positions and get NARROWER skirts instead.
`_fit_plinth_skirts` walks a per-lot `plinth_margin` down from 1.0 m in
five-centimetre steps to a 0.2 m floor and stops at the first value that
clears. A skirt narrower than the floor stops reading as a base and
starts reading as a building with no footing, so a lot that would need
less keeps its full skirt and has its overlap published instead. Nothing
else about the lot moves: the masses, the rotation and the frontage stay
exactly as the ladder placed them.

`audit_plan` measures the result. `plinth_carriageway_collisions` counts
the lots whose plinth is still in the driving surface, and it is gated at
zero. `plinth_pad_laps` and `worst_plinth_pad_lap` count and measure the
plinths lapping a junction apron, and they are deliberately NOT gated:
the composition accepts two, the worst 0.8839 m. Refusing them was tried
and measured -- it costs an AUTHORED mid-rise block (`wallside_row`,
three units) and takes the city's mid-rise shoulder from nine masses to
five, because a block's position is a design decision with no set-back
ladder to retreat along. Deleting real buildings to buy a slab's last
third of a metre under an apron nobody can see is a bad trade. Published
rather than gated must not decay into unwatched, so the pure suite pins
both: the two, the 0.8839 to four decimals, and an assertion that the
worst lap is above ZERO -- a lap of exactly zero would mean the
measurement had stopped measuring.

The mid-rise tier (five to seven floors) is deliberate vocabulary:
`midrise_slab`, `midrise_court`, `row_mid`, `duo_mid`, and `office_slab`
carry the middle of the skyline between the founding towers and the low
fabric, and they render with their own facade language (taller storeys,
generous glass) through the founding recessed-glazing generator and the
district's own materials -- episode occupancy drives production windows
through the same `LD_LitFraction` mechanism with ZERO new material
roles.

## Landscape

Vegetation is planted LAST, and every tree has an urban reason: formal
street tree lines along the declared boulevard sides (near-regular
spacing, small deterministic jitter), replanted groups inside every park
zone around the preserved founding groves, courtyard trees in court
lots, a plaza tree square, and a waterfront promenade line on the land
side of the quay. Street-tree sides push their facades back so the whole
canopy fits between carriageway and glass; everything else keeps the
tight street wall.

## Determinism

Same master spec + same production spec + same visual seed produce the
same clearing, the same graph, and the same plan, bit for bit: all
iteration is sorted, all variation is SHA-256-seeded per entity
(`stable_rng`), mapping insertion order is proven irrelevant, and the
whole pipeline is pure data until the Blender builder instantiates it.
Pixel determinism is not claimed, exactly as in Phase 15.

## Blender layer

`build_production_world.py` first applies the deterministic legacy
clearing (suppressing exactly the planned `LD_TREE__` clusters), then
adds -- never rebuilds -- on top of the built master scene: plinths and
frontage strips, street ribbons per class (staggered deck heights so
crossings never z-fight), arterial center dashes, merged lamp runs, one
merged junction/turnaround mesh, windowed fabric masses with parapets
and rooftop units, the market plaza with mast lighting, container rows,
port flood masts and quay lamps, replanted vegetation, and the nine
Phase 16 camera anchors (`CAM_P16_WORLD_HERO`, `CAM_P16_SYSTEM`,
`CAM_P16_CORE_CONTEXT`, `CAM_P16_SCAR_CONTEXT`, `CAM_P16_ROADS`,
`CAM_P16_DENSITY`, `CAM_P16_VALIDITY`, `CAM_P16_URBAN`,
`CAM_P16_COMPOSITION`). Everything
lives under `LD_PRODUCTION` with `LD_P16_`-prefixed names and replaces
by name on rebuild. The final composition adds the `LD_P16_GROUND`
collection -- one merged terraced object per district plus one per ground
surface -- and the redrawn `LD_P16_RING__` arcs. It also reaches back
once into the founding scene, between suppressing the legacy
presentation and laying the city ground, to re-cut the ring disc of every
district that kept one; the plinths it then builds read each lot's own
`plinth_margin`, so the skirt that is meshed is the skirt that was
audited. The semantic anchors are
proven untouched by snapshot equality in the structural tests, and the
material family is proven unchanged: the ground reuses `pavement`,
`concrete`, and `terrain` and introduces no new role.

## Verification

    # engine story + pure plan + structural tests + proof frames + manifest
    python visual/blender/run_phase16_checks.py --workspace <fresh dir> \
        [--blender <blender.exe>] [--preview]

`run_blender_tests_p16.py` runs every Phase 15 structural test unchanged
against the pure founding scene FIRST, then the production-world tests
(which add the redesigned city and prove the anchor, clearing, ring
suppression, rim-exposure, ground, idempotency, street, plinth, and
budget contracts). `run_phase15_checks.py` itself remains fully
reproducible for V1 compatibility. The pure suite lives in
`tests/visual/` (`test_production_spec.py`, `test_road_graph.py`,
`test_spatial_occupancy.py`, `test_urban_fabric.py`,
`test_city_ground.py`, `test_phase16_boundary.py`).

`produce_production_world_proof.py` renders the Phase 16 pack in one
session: the before-expansion and before-composition references (the
SAME persistent world state, from the same two cameras), the world hero,
system view, CITY COMPOSITION verify, historic core context, scar
context, road network verify, density verify, spatial validity verify,
urbanization verify, the CLEAN-ROADS verify (the street network rendered
alone, so the plan can be judged as a plan), the small-screen sheet, the
composition comparison sheet, and the packed `.blend`, plus a
UTF-8-no-BOM manifest carrying camera definitions, render settings and
times, street, fabric, spatial-validity, city-composition, and
urbanization statistics, scene complexity, and per-file SHA-256.

The composition frame answers one question directly -- does this read as
ONE CITY instead of connected pods? -- from a low western oblique where
urban continuity, block relationships, the mid-rise shoulder, the western
arc, and the civic core are all judgeable at once. The comparison sheet
puts the pre-composition world beside the final one from that same
camera; both halves are the same authoritative episode state, so what
differs is composition, never history.

## Non-goals (Phase 16)

No motion, no traffic or crowds, no camera animation, no construction or
time-lapse, no narration or audio, no engine changes, no new simulation
districts, no new authoritative state, no external assets, no pixel-hash
determinism claims, no CI Blender installation.
