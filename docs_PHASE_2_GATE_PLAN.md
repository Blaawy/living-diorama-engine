# Phase 2 — Automatic Gate Plan (written before Phase 2 starts)

**Purpose:** every Phase 2 gate item gets a *measurement* that will prove it,
decided before any of it is built. "Read the output, never trust the status"
applied to a whole phase. Nothing here is Phase 2 authority; the Phase 1 gate
has not passed at the time of writing.

| # | Gate item (Director's list) | Proof artefact | Measurement that must pass | Who produces it |
|---|---|---|---|---|
| 1 | professional non-blockout world exists | `evidence/world_inventory.json` | zero actors using `/Engine/BasicShapes/*`; road/sidewalk/junction meshes come from PCG-generated or CitySample-derived assets; building count > 0 with ≥ 3 distinct kits | Claude via MCP `SceneTools.find_actors` + asset paths |
| 2 | roads look credible | `evidence/road_geometry_check.json` | every SUMO lane polyline has a spline-mesh strip within 5 cm centreline error; lane widths 3.2 m / 2.0 m match `grid.net.xml`; junction polygons filled | Python: sumolib vs in-editor spline sample via remote exec |
| 3 | traffic aligns with SUMO truth | `evidence/playback_verify.json` (Phase 2 scale) | pinned-frame transform check as Phase 1: 0.0 cm / 0.0° on ≥ 50 sampled actors at 3 frames; **plus** every played actor's yaw within 1° of the record at the frame before/after (interpolation check) | `ldyf/playback_verify.py` extended |
| 4 | believable vehicles exist | `evidence/world_inventory.json` | vehicle actors use a skeletal or static car mesh with ≥ 4 wheel components; wheel rotation rate = `speed / wheel_radius` within 5 % on a sampled vehicle | MCP `get_components` + remote-exec readback |
| 5 | believable humans exist | inventory + screenshot set | pedestrian actors use a skeletal mannequin with an animation blueprint; idle/walk states observed | MCP + `CaptureViewport` |
| 6 | humans visibly move | `evidence/human_motion.json` | for ≥ 30 sampled pedestrians, displacement over 10 s > 5 m for walkers and animation state changes ≥ 1 for those that stop | remote-exec sampling |
| 7 | obvious short loops absent | `evidence/loop_audit.json` | **no actor** repeats a position-sequence of ≥ 8 s within a 120 s window (hash of quantised 1 Hz positions, no duplicate windows); pedestrian destination set size ≥ 0.6 × pedestrian count; spawn timing not periodic (Fourier peak below threshold) | Python over the record + Mass sampling |
| 8 | real road-closure experiment works | sealed `simulation_result.json` + ledger | same law as Phase 1: 500+ vehicles, 200+ pedestrians, exit 0, both outputs valid, deterministic repeat, ≥ 1 measured effect; `routes_actually_changed` > 0 | `ldyf.closure` |
| 9 | preview exists | `preview/phase2_preview.mp4` | 60–120 s, H.264, ffprobe frame count = fps × duration ± 1; **at least one shot shows the closed road and a rerouting vehicle** (frame indices cited) | Movie Render Queue + ffprobe |
| 10 | performance measured | `evidence/performance.json` | editor FPS (viewport) min/median over 60 s; CPU/RAM/VRAM at idle and during playback; MRQ seconds-per-frame; record size; load time | PowerShell + nvidia-smi + MRQ log |
| 11 | no paid dependency | `FREE_DEPENDENCY_LOCK.json` v3 | every new asset/plugin listed with source and licence; `total_recurring_cost_usd = 0`; Fab items marked free | Claude |
| 12 | no truth fabrication | ledger + `verify_ledger(evidence_dir=)` | every public claim in the preview's captions/narration resolves to a ledger `measured_effect` or a sealed field | `episode_manifest.claims` |
| 13 | tests pass | `evidence/test_results.txt` | full suite green in repo and from fresh MASTER extraction | pytest |
| 14 | red team has no Phase 2 blocker | `reports/RED_TEAM_PHASE_2.md` | ≥ 2 independent DeepSeek attackers, questions from the Director's list, every finding executed not opined | flash_bridge |
| 15 | repository committed and clean | git | HEAD recorded, porcelain empty, fsck clean | git |

## Order of work (so proof drives build)

1. Playback path first (item 3) — it already exists; extend the verifier to
   interpolation and larger samples before anything visual changes.
2. Roads from `grid.net.xml` (item 2) — the mapping is the spine; measure
   centreline error before dressing anything.
3. Vehicles on the proven playback (item 4).
4. Buildings and dressing via PCG (item 1).
5. Pedestrians (items 5–7) — after the C++/no-C++ decision in
   `PHASE_2_DESIGN_INPUTS.md` §3.
6. Closure experiment in the new world (item 8), preview (item 9), performance (10).
7. Red team (14), lock (11, 12, 13, 15).

## What would make Phase 2 fail its gate honestly

- The loop audit (item 7) finds a repeating window. A camera cut is not a fix.
- Centreline error > 5 cm anywhere: the visible road is not the simulated road.
- Any claim in the preview without a ledger source.
- Any `/Engine/BasicShapes` actor left in the world.
