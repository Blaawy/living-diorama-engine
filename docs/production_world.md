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
ordinary pytest before Blender ever runs. No locked Phase 15 source file changes: the
legacy build reproduces the original scene bit for bit, and the
structural suite proves it inside Blender every run.

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
right. `spatial_occupancy.founding_building_lots` replays the locked
Phase 15 lot sampler draw for draw -- eight buildings across the four
districts -- and registers each under a conservative envelope, so plate
ground can stay open to designed planting without a tree ever growing
through a building that nothing was watching.

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
surface -- and the redrawn `LD_P16_RING__` arcs. The semantic anchors are
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
