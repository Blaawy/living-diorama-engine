# Blender Master Scene (Phase 15)

## Purpose

Phase 15 turns a verified Render Export V1 into the first persistent visual
world: one master geography, rendered as a premium cinematic architectural
diorama. The simulation's numbers become a place — districts, avenues, the
Golden Seal, and the isolation wall the engine itself built — so a viewer can
finally *see* that the world remembers.

## Baseline

- **Blender 4.5.x LTS** only. The runtime refuses any other major/minor
  version. Development and proof rendering for Candidate V1 used Blender
  4.5.12 LTS (portable, from blender.org).
- **Cycles** for all proof frames; OptiX preferred, CUDA then CPU fallback.
  The scene never requires a specific GPU.
- **AgX** view transform, "Medium High Contrast" look, exposure +1.5, at a
  civil-twilight lighting rig (Nishita sky just below the horizon, cool area
  fill, warm practicals, low-density scatter volume).

## Boundary rules

The Blender layer consumes **only** `render_export.json` (Phase 14). It never
reads save files, never imports simulation modules, and never writes anything
into a save root. `bpy` never appears inside `src/living_diorama/…`; all
Blender code lives under `visual/blender/`, and nothing under that tree
imports `living_diorama` (pinned by AST guard tests in `tests/visual/`).
The engine-side proof-story generator — which legitimately drives the real
engine to produce the Render Exports — lives under `tools/phase15_proof/`,
outside the Blender runtime tree, so directory ownership matches the runtime
boundary.

## Master Scene Spec V1

`visual/blender/config/master_scene_v1.json` —
`format: living_diorama_blender_master_scene`, `schema_version: 1`.

Presentation geography only: platform size, district centers/footprints/
elevations/characters/depot capacities, boundary corridor polylines, the
wall station each boundary would carry if an episode builds a wall, the
Golden Seal plaza, the five persistent camera anchors (`CAM_HERO_WORLD`,
`CAM_HERO_SCAR`, `CAM_SCAR_DETAIL`, `CAM_SEAL_DETAIL`,
`CAM_VERIFY_TOPOLOGY`), and the master `visual_seed`. No simulation state,
no episode state.

Topology must agree with the Render Export: unknown districts or boundaries
and endpoint disagreements are refused (`SceneContractError`), never
silently placed, swapped, or redrawn.

## Persistent vs episode state

| Persistent (build_master_scene) | Episode (apply_render_export) |
| --- | --- |
| platform, terrain, harbor, cranes | wall scar: segments, joints, piers, gate |
| district plates, windowed architecture | gate machinery, floodlights, wall washes |
| avenues, markings, spurs, street lights | depot container fill (resources) |
| vegetation clusters, depot pads | glazing lit fraction (population) |
| Golden Seal monument, halo, plaza | seal ring glow (movement law standing) |
| camera anchors, lighting rig | conduit condition + wall anchor struts |

Applying an export is idempotent and reversible: episode objects live in
`LD_EPISODE`, `LD_WALLS`, and `LD_INFRASTRUCTURE`, are cleared on every
apply, and never touch geography. Districts, buildings, seal, avenues, and
cameras are proven byte-identical between before/after states by the
structural tests.

## Roads stop at the architecture standing on them

The road drawing is no longer unconditional. The founding lot sampler
accepted a building by the distance from its ORIGIN to a road, while a
civic podium and its entry canopy reach 8.53 m from that origin, so seven
founding footprint rectangles came to stand in legal driving space — and
on the avenues and spurs, whose decks are drawn above the founding bases,
the slab passed clean through the podium.

`_trimmed_ribbon` cuts a strip into the maximal spans clear of the real
founding footprints (`spatial_occupancy.founding_clear_spans`, which
mitres the strip edges exactly as the ribbon builder does, so a building
sitting in the wedge on the outside of a bend is not missed) and welds
the survivors into ONE mesh with gaps, never into numbered siblings.
Every co-located layer of an avenue goes through it at its own lateral
offset — carriageway, both sidewalks, both curbs, both edge markings —
and so does every spur. The centre dashes are individual boxes rather
than a strip, so they are filtered box by box on
`founding_point_is_covered` instead.

`_ring_disc` and `trim_ring_disc` do the same job for a plate's
seventy-two-wedge ring disc, omitting the wedges a tower stands on and
capping the ends that omission exposes. The helpers live here because the
disc does, but the founding build still draws every disc whole: a plate's
ring is only trimmed when Phase 16 keeps it, which is
`build_production_world`'s call to make and `docs/production_world.md`'s
to state.

A road object may therefore legitimately draw NOTHING.
`LD_SPUR__boundary_cd__district_c` runs 5.65 m and every metre of it lies
inside `LD_BLDG__district_c__001`, so the object is built, named,
materialled and linked with an empty mesh. An empty object is honest
about a road the city cannot show, and nothing that looks the name up is
left holding a reference to something that vanished — which a deletion
would have arranged.

Ten drawn faces stood inside founding architecture before the trim and
none does after; the same ten carried 52.4261 m2 of built road surface
standing on architecture, and after the trim that is zero.
`tests/visual/test_road_trim.py` reconstructs the faces
the builders emit, from the same helpers and the same call-site
constants, and proves the count in both directions: bypassing the trim
and feeding it no footprints each put all ten overlaps back, so a guard
that had quietly stopped guarding fails loudly rather than printing a
pass. The Blender suite then measures the built meshes themselves, since
the dash filter tests a centre point while the box has width.

What the trim does not do is move a building. Five founding buildings
still stand in carriageway plan-space, and the Director has formally
accepted that as a PERMANENT COMPATIBILITY EXCEPTION: four of them have
no legal position anywhere on their own plate, and the relocation the
fifth could have taken was declined. That residual is measured, named and
published by the production layer, and `docs/production_world.md` states
it in full.

The trim is therefore permanent too. It is not a stopgap holding the
picture together until the buildings move, because the buildings are
never going to move; it is the standing arrangement that keeps an
accepted plan-space overlap from becoming a visible one. Deleting it
would put road surface back inside a podium the same day.

## Directory structure

    visual/blender/
      config/master_scene_v1.json     the Master Scene Spec V1
      scripts/scene_spec.py           pure contract logic (no bpy)
      scripts/blender_runtime.py      version gate, primitives, materials
      scripts/build_master_scene.py   persistent world builder
      scripts/apply_render_export.py  episode-state application
      scripts/render_visual_proof.py  Cycles device/sampling/render
      scripts/produce_visual_proof.py one-session proof-pack producer
      tests/run_blender_tests.py      in-Blender structural test runner
      tests/test_master_scene.py      persistent-scene contract
      tests/test_apply_render_export.py episode/continuity/refusal contract
      run_phase15_checks.py           the local Phase 15 gate (no bpy)
      assets/                         reserved (procedural-only in V1)

    tools/phase15_proof/
      generate_proof_exports.py       real-engine proof story (no bpy;
                                      engine-side, outside the Blender tree)

    tests/visual/
      test_blender_locator.py         gate executable resolution (pure)
      test_visual_runtime_boundary.py AST import/ownership guards (pure)
      test_road_trim.py               drawn road surface vs founding
                                      architecture (pure)

## Naming contract

Collections: `LD_WORLD` with `LD_DISTRICTS`, `LD_BOUNDARIES`, `LD_WALLS`,
`LD_INFRASTRUCTURE`, `LD_LANDMARKS`, `LD_RULE_OBJECT`, `LD_EPISODE`,
`LD_CAMERAS`, `LD_LIGHTS`. Objects carry semantic ids:
`LD_DISTRICT__district_a`, `LD_ROAD__boundary_ab`,
`LD_WALL__wall_boundary_ab__seg03`, `LD_INFRA__infra_ab_transit__pipe0`,
`LD_SEAL__disc`, `CAM_HERO_WORLD`. Rebuilds and re-applies replace by name;
`.001` growth is a test failure.

## State mapping (V1, deliberately small)

- **Population** → per-district-character glazing lit fraction:
  `0.12 + 0.55 × population/housing_capacity`, driven into the
  `LD_LitFraction` node of that district's glass material. Every pane is
  real recessed glazing whose lit/unlit decision reads a stable per-pane
  `LDCELL` id — deterministic, and constant across each pane by
  construction. Geometry never rebuilds.
- **Resources** → depot container fill: `total stock / depot_capacity`
  (spec) → number of visible containers/stacks.
- **Isolation state** → gate treatment at crossings (OPEN in the proof
  world; the mapping point exists for PARTIAL/ISOLATED).
- **Walls** → full scar architecture at the boundary's wall station:
  precast segments with construction joints, coping caps, buttress piers,
  service band with conduits/junction boxes/wall lamps, upper cable tray,
  guarded catwalk with access ladder, aviation beacons, and a controlled
  gate complex (towers with lit control cabs, machinery lintel, ribbed
  sliding door with hazard chevrons, stop bars, bollards, guard hut,
  floodlights, wall-wash lighting) placed exactly where the avenue crosses
  the wall line; height scales slightly with integrity; presence comes only
  from the export.
- **Infrastructure** → conduit racks along the boundary; `degraded` goes
  dark; `dependency_score` sets the number of struts anchoring the conduit
  into the wall.
- **Law** → the Golden Seal's plaza ring glows while the movement law is in
  force; the artifact itself never moves or redesigns.

Fear, trust, and institutional pressure are deliberately **not** visualized
in Phase 15.

## Determinism

All variation is seeded by SHA-256 over `(visual_seed, entity id, role)` —
never Python's `hash()`, never process randomness. Same spec + same export ⇒
the same semantic scene (names, transforms, assignments), proven by the
structural tests. Pixel output is *not* claimed byte-stable across GPUs or
drivers; the deterministic claim covers scene topology, transforms, semantic
assignments, materials, cameras, and state mapping within Blender 4.5.x.

## Render settings (proof frames)

2560×1440, Cycles, adaptive sampling (max 1024, threshold 0.015),
OpenImageDenoise (albedo+normal), max bounces 8, AgX Medium High Contrast,
exposure +1.5. Preview mode: 1280×720, 96 samples, threshold 0.08.

Six proof frames: `phase15_before` / `phase15_after` share the exact same
comparison camera (`CAM_HERO_WORLD`); `phase15_hero_scar` is a dedicated
cinematic composition (`CAM_HERO_SCAR`, structurally pinned to differ from
the comparison camera); plus `phase15_scar_detail`,
`phase15_golden_seal_detail`, and `phase15_topology_verify`.

## Reproduction

    # engine story + structural tests + proof frames + manifest
    python visual/blender/run_phase15_checks.py --workspace <fresh dir> \
        [--blender <blender.exe>] [--preview]

Blender resolution order: `--blender`, then the `BLENDER_EXECUTABLE`
environment variable, then `blender` on PATH; otherwise the gate fails
clearly. No machine-specific fallback exists.

Individual steps: `tools/phase15_proof/generate_proof_exports.py` (plain
Python, engine-side), then inside Blender `build_master_scene.py`,
`apply_render_export.py`, `render_visual_proof.py`, or
`produce_visual_proof.py` — each documented in its module docstring.

## Non-goals (Phase 15)

No animation, camera direction, traffic/crowds, narration, LLMs, sound,
editing, thumbnails, publishing. No external/paid assets, no asset
downloads: the world is procedural and reproducible from this repository.
No pixel-hash determinism claims. No CI Blender installation.
