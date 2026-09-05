"""Which mesh each piece of street dressing wears — shared, pure, no Unreal.

These tables were originally constants inside
``ldyf.unreal.ldyf_dressing_editor``, which imports ``unreal`` and therefore
cannot be read outside the editor. The verifier needs exactly the same tables
to assert that a signal wears a signal mesh, so they live here and both sides
import them: one definition, no chance of the spawner and the checker drifting
apart and agreeing on a lie.
"""

from __future__ import annotations

DRESSING_ASSETS_VERSION = "dressing_assets_v1"

MARK_PREFIX = "LD_Mark"
CROSSWALK_PREFIX = "LD_Crosswalk"
SIGNAL_PREFIX = "LD_Signal"
TREE_PREFIX = "LD_Tree"
# NOT "LD_TreeBase": every prefix filter here uses str.startswith and
# "LD_Tree" is a prefix of "LD_TreeBase", which would merge the two families.
TREE_BASE_PREFIX = "LD_Pit"
FURNITURE_PREFIX = "LD_Furniture"
CLOSURE_PREFIX = "LD_ClosureProp"

DRESSING_PREFIXES = (MARK_PREFIX, CROSSWALK_PREFIX, SIGNAL_PREFIX,
                     TREE_BASE_PREFIX, TREE_PREFIX, FURNITURE_PREFIX,
                     CLOSURE_PREFIX)

PAINT_COLOURS = {
    "white": (0.92, 0.92, 0.90),
    "yellow": (0.86, 0.66, 0.08),
}

# Only meshes whose material slots all resolve: the StopLight A/C/D/E variants
# each carry one null slot and are excluded (see EVIDENCE prop_probe.json).
SIGNAL_MESH = {
    "traffic_light": "/Game/Prop/Kit_StreetLamp_A/Mesh/SM_StreetLamp_A_StopLight_B",
    "stop_sign": "/Game/Prop/Kit_StopSign_A/Mesh/SM_StopSign_A",
}

# Real Megascans plants with leaf geometry, from the CitySamplePCG Megaplants
# set. The prop-kit "trees" imported earlier (birch, alder, maple) are branch
# skeletons of 2.5-5k triangles with no leaf cards at all and render as dead
# winter trees in daylight; these carry 42k-85k triangles of actual foliage and
# resolve every material slot. Chosen for street scale: 3.7-4.7 m wide,
# 7.3-10.9 m tall. Note they ship with a single LOD, so the triangle budget is
# roughly 240 x 57k = 13.7M and is carried by Nanite, not by LOD reduction.
TREE_MESHES = [
    "/CitySamplePCG/Megaplants/Tree_European_Beech/Tree_European_Beech_01/SM_European_Beech_01_C",
    "/CitySamplePCG/Megaplants/Tree_European_Beech/Tree_European_Beech_01/SM_European_Beech_01_D",
    "/CitySamplePCG/Megaplants/Tree_European_Aspen/Tree_European_Aspen_01/SM_European_Aspen_01_B",
]
# shrub used for hedges and block-interior planting
SHRUB_MESHES = [
    "/CitySamplePCG/Megaplants/Tree_Common_Hazel/Tree_Common_Hazel_01/SM_Common_Hazel_01_B",
    "/CitySamplePCG/Megaplants/Tree_Common_Hazel/Tree_Common_Hazel_01/SM_Common_Hazel_01_A",
]
TREE_BASE_MESH = "/Game/Prop/Kit_TreeBase_A/Mesh/SM_TreeBase_Circle_A"

FURNITURE_MESH = {
    "lamp": ["/Game/Prop/Kit_StreetLamp_A/Mesh/SM_StreetLamp_A_Pole_Large"],
    "bin": ["/Game/Prop/Kit_Trashcan_A/Mesh/SM_Trashcan_A_01"],
    "sign": ["/Game/Prop/Kit_bench_RR/mesh/SM_street_bench",
             "/Game/Prop/Kit_bench_RR/mesh/SM_park_bench_N01"],
}

CLOSURE_MESH = {
    "barricade": "/Game/Prop/Kit_Barricade_A/Mesh/SM_Barricade_A",
    "cone": "/Game/Prop/Kit_ConstructionCone_RR/Mesh/SM_ConstCone_a_N1",
}

TREE_BURY_CM = 10.0        # a street tree's root flare sits just below grade
DECAL_DEPTH_CM = 60.0      # projection depth; deep enough for the kerb camber
