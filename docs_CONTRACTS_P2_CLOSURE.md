# Phase 2 closure pass — frozen contracts (2026-09-03)

Every lane builds against this text. Laws from Phase 1 stand: SUMO is mobility truth;
the sealed record (`record_ruled`, frames.bin sha256 `98f7bcfa…`) is the only source of
poses; `ldyf.coords` is the only transform; no typed numbers that are not from the record,
a measured asset property, or an explicit argument; every claim cites a machine file.

## C1 — Ground contact (the Z law)
- For every presentation mesh the **contact offset** is measured at spawn:
  `contact_offset_cm = root_z − world_bounds_bottom_z`, with the actor at a KNOWN root z
  (never subtract absolute bounds origin as if it were local). Bounds come from
  `unreal.SystemLibrary.get_component_bounds(component)` (origin, extent) of the spawned
  mesh component; bottom = origin.z − extent.z.
- Placement: `root_z = record_z + surface_z + contact_offset_cm`, where `surface_z` is the
  measured top of the road strip mesh (`EVIDENCE/PHASE_02/road_mesh_bounds.json`, 20 cm)
  for vehicles and pedestrians on roads; sidewalk top for pedestrians when the record puts
  them on a sidewalk lane is a later refinement — record which surface was used.
- **Contact verification** compares the world-space bottom of the placed mesh to the
  expected ground plane: `contact_error_cm = |world_bounds_bottom_z − (record_z + surface_z)|`.
  A verifier that ignores z is forbidden.

## C2 — 3D playback verification (`ldyf/playback_verify3d.py`)
Sample set: **every actor present** at three record frames chosen from the closure timing
(`closure at t = 150 s`): `before` (t = 100 s → frame 1000), `around` (frame 1500),
`post` (frame 3000). Minimum ≥ 50 actors per frame or all present if fewer.
Per frame, compare the editor's placed actors (label → uid) with the record:
`xy_error_cm` (2-D), `contact_z_error_cm` (C1), `yaw_error_deg` (shortest arc via
`coords.normalise_deg`), `missing` (uid in record, no actor), `extra` (actor with no record
sample at that frame). Interpolation check: at `t = frame_time + step/2` the placed pose must
equal `record_interp.pose_at` within `interp_tol_cm` / `interp_tol_deg` (arguments, defaults
1.0 cm / 1.0°). Report schema `playback_verify3d_v1`:
```
{"schema_version","record_sha256","frames":[{"frame","t","actors_expected","actors_placed","compared",
  "missing":[uid],"extra":[label],"xy":{"max","mean"},"contact_z":{"max","mean","surface_z_used"},
  "yaw":{"max","mean"},"pass"}],"interpolation":[{"t","compared","xy_max","yaw_max","pass"}],
  "tolerances":{...},"pass"}
```
PASS requires every frame's max errors within tolerance, zero missing, zero extra, and
interpolation pass. Tolerances are arguments; the report prints them.

## C3 — Deterministic frame authority (`ldyf/sequence_bake.py` + in-editor `ldyf_sequence.py`)
- `presentation_time(frame, fps) = frame / fps` seconds; `sim_time = t_begin + presentation_time × rate`
  (`rate` fixed per render, default 1.0). No wall clock anywhere in the render path.
- `bake_keys(record, fps, rate, t_start, t_end)` → per uid: transform keys at every output
  frame where present (x, y, z=record_z+surface_z+contact_offset, yaw), presence segments
  (spawn/despawn frames), animation segments for persons (walk/idle by speed), wheel spin
  angle per frame (accumulated from record speed and measured radius) — all pure Python,
  deterministic, unit-tested against `record_interp`.
- In-editor: a Level Sequence `/Game/LD/LS_Preview` with one possessable per visible actor,
  transform tracks with those keys, visibility tracks for presence; Movie Render Queue renders
  it at 24 fps (settings recorded); output frame N of the MP4 is presentation second N/24
  regardless of render time. Evidence: `mrq_render.json` (fps, frame count, sequence range,
  sim time mapping, ffprobe of the MP4).

## C4 — Road geometry proof (`ldyf/road_geometry_check.py`)
Measured from the SPAWNED components, never from the authoring splines: for every
`PCGSplineMeshComponent` read start/end world positions (spline mesh params or component
bounds) and the start/end cross-section scale; reconstruct the strip centreline and width;
compare to the SUMO lane polylines from `road_spec.json` (independent input): `centreline_max_cm`,
`width_error_cm = |scale_y × mesh_width − width_cm_effective|`; junction coverage = dynamic-mesh
bounds cover the junction polygon bbox; z continuity = |slab_top − strip_top| ≤ tolerance.
Report `road_geometry_v1` with per-lane rows and totals; tolerances are arguments (5 cm law).

## C5 — Level-wide inventory (`ldyf/world_inventory.py` v2 + `ldyf/unreal/ldyf_level_dump.py`)
The dump enumerates EVERY actor in the level (all classes) with every component's class and
asset path (case preserved), including PCG-generated components on the PCG volume actor and
dynamic meshes. Blockout rule: case-insensitive match of `/engine/basicshapes/`,
`/engine/enginemeshes/`, and any path containing `basicshapes` in any mount; also
`/engine/editormeshes/`. Roles from component classes and asset paths (roads = PCGSplineMesh
strips from `/citysamplepcg/meshes/roads/`; ground/junction = DynamicMeshComponent with the
LD materials; buildings = assets under `/game/building/` or CitySamplePCG building meshes).
Debug/proof actors (`LD_Lane_*`, `LD_Junction_*`, `LD_Ground_*` spline actors with no mesh)
are classified `authoring` and are allowed; they have no visible mesh.

## C6 — Loop audit v2 (`ldyf/loop_audit.py`)
Keep v1; add: windows {6, 8, 12, 20} s at rates {1, 2} Hz; horizon 300 s and full-record;
route-sequence repetition (quantised heading sequence); repeated destination cycles per
actor (cell sequence of stops); later-session comparison (all pairs, not first occurrence);
stationary vs patrol distinction (cells within 2 of each other over a window count as patrol
if the actor moves ≥ 1 cell per 2 s on average); spawn periodicity with a threshold
argument (default 0.5 score, stated as the Director's to change); two-actor alternation
(compare windows across uids of the same kind). Output lists the boundary of detection.

## C7 — Evidence files (all under EVIDENCE/PHASE_02, shipped)
`contact_offsets.json`, `playback_verify3d.json`, `road_geometry.json`, `level_inventory.json`,
`loop_audit_v2.json`, `performance_profile.json`, `mrq_render.json`, `sequence_bake_summary.json`,
`visual_redteam/*.md`, `truth_redteam/*.md`, captures in `preview/` WITHOUT debug overlays
(captures with overlays go to `evidence/debug_captures/`).
