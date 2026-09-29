"""The tree variant order and the tree mesh table are one table, not two.

``dressing.tree_slots`` rolls a variant in {0, 1, 2}
(``ldyf/dressing.py``: ``"variant": _digest_int(rid + "|tree", 3)``) and the
spawner indexes the asset table by it, while ``tools_build_trees.py`` walks
``tree_mesh.TREE_VARIANT_ORDER`` and builds ``SM_LD_Tree_<name>`` for each index.
Which shape each index names therefore has to agree across three places, and it
used to be agreed by convention between two of them: reorder
``TREE_VARIANT_ORDER`` or ``dressing_assets.TREE_MESHES`` and every tree in the
city swapped shape with every test still green.

These tests fail if the two ever disagree, in either direction, and they fail if
the shipped order is reordered (which changes what every existing dressing plan
and already-built mesh means).
"""
from __future__ import annotations

from ldyf import dressing_assets as DA
from ldyf.tree_mesh import TREE_VARIANT_ORDER, TREE_VARIANTS

# The shipped order.  Index 0 is the broad street maple: tools_build_trees.py
# builds SM_LD_Tree_<name> in TREE_VARIANT_ORDER order and records the index, and
# dressing_assets' own comment records that sorted() would put the narrow
# columnar where the broad maple belongs.  A change to this tuple re-labels
# every variant left in the built city, so it must be a deliberate edit and this
# test must fail first.
SHIPPED_VARIANT_ORDER = ("maple", "columnar", "sapling")

SHIPPED_TREE_MESHES = ["/Game/LD/Meshes/SM_LD_Tree_Maple",
                       "/Game/LD/Meshes/SM_LD_Tree_Columnar",
                       "/Game/LD/Meshes/SM_LD_Tree_Sapling"]


def test_tree_meshes_are_derived_from_the_variant_order():
    """TREE_MESHES is the variant tuple mapped through the asset-name rule.

    Breaks the moment TREE_MESHES is hand-written again (or the rule changes in
    one place only).
    """
    assert DA.TREE_MESHES == [DA.mesh_path_for_variant(v)
                              for v in TREE_VARIANT_ORDER]


def test_each_mesh_index_names_its_own_variant():
    """Index i of the mesh table names variant i -- not just its position."""
    assert len(DA.TREE_MESHES) == len(TREE_VARIANT_ORDER)
    for i, variant in enumerate(TREE_VARIANT_ORDER):
        mesh = DA.TREE_MESHES[i]
        assert mesh == "%s/SM_LD_Tree_%s" % (DA.TREE_MESH_ROOT,
                                             variant.capitalize()), (i, variant)
        assert variant in mesh.rsplit("/", 1)[-1].lower(), (i, variant, mesh)


def test_shipped_order_is_the_order_that_is_built_and_dressed():
    """Reordering EITHER list (or the variant tuple) breaks this test."""
    assert TREE_VARIANT_ORDER == SHIPPED_VARIANT_ORDER
    assert tuple(DA.TREE_MESHES) == tuple(SHIPPED_TREE_MESHES)


def test_variant_table_and_order_list_the_same_variants():
    """A shape added to one and not the other is a mismatch, not a new tree."""
    assert set(TREE_VARIANTS) == set(TREE_VARIANT_ORDER)
    assert len(TREE_VARIANT_ORDER) == len(set(TREE_VARIANT_ORDER))


def test_dressing_variant_index_space_matches_the_mesh_table():
    """dressing.tree_slots rolls 0..2 (``_digest_int(rid + "|tree", 3)``)."""
    assert len(DA.TREE_MESHES) == 3


def test_reordering_the_variant_order_moves_the_derived_meshes():
    """The coupling is mechanical, not positional coincidence.

    Swapping two entries of the variant tuple re-derives the same swap in the
    mesh table, which is what makes an accidental reorder impossible to
    half-apply.
    """
    a, b = TREE_VARIANT_ORDER[0], TREE_VARIANT_ORDER[1]
    swapped = (b, a) + tuple(TREE_VARIANT_ORDER[2:])
    derived = [DA.mesh_path_for_variant(v) for v in swapped]
    assert derived == [DA.TREE_MESHES[1], DA.TREE_MESHES[0],
                       *DA.TREE_MESHES[2:]]
