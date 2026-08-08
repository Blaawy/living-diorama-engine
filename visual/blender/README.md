# Living Diorama — Blender layer (Phase 15)

Downstream visual layer: consumes verified Render Export V1 documents and
builds the persistent master scene in Blender 4.5 LTS. Never imports engine
internals, never touches save files, never runs simulation. This tree is
literally downstream-only: nothing under `visual/blender/` imports
`living_diorama` (pinned by `tests/visual/test_visual_runtime_boundary.py`).
The real-engine proof-story generator lives in `tools/phase15_proof/`.

- Contract and reproduction guide: `docs/blender_master_scene.md`
- Local gate: `python visual/blender/run_phase15_checks.py --workspace <dir>`
- Master Scene Spec: `config/master_scene_v1.json`

The gate resolves Blender from `--blender`, then the `BLENDER_EXECUTABLE`
environment variable, then the system PATH — never from a hard-coded path.

Ordinary engine pytest never imports `bpy`; every Blender-side test runs via
`blender --background --factory-startup` through the local gate.
