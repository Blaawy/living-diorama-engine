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

# Only trees that carry FOLIAGE materials. The City Sample birches and the
# alder resolve to a single bark material and render as bare winter branches;
# the maples carry a separate bough/canopy material. 4.2-6.9 m wide, which is a
# street tree rather than a park specimen.
TREE_MESHES = [
    "/Game/Prop/Kit_Tree_Maple_Sugar/Mesh/Tree_Maple_A",
    "/Game/Prop/Kit_Tree_Maple_Sugar/Mesh/Tree_Maple_B",
    "/Game/Prop/Kit_Tree_Maple_Red/Mesh/Tree_Maple_Red_A",
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
