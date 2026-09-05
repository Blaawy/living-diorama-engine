"""Execute a ``surface_spec_v1`` graph into a real Unreal material, and move the
ground and sidewalk instances onto it.

They were children of City Sample's ``MS_DefaultMaterial``, which this project
cannot compile ("Missing Material Function") and cannot inspect from Python
(``Expressions`` is protected). A material that fails to compile renders with
fallback shading, and that is what the block-interior speckle is. Rather than
keep chasing a dependency we can neither build nor read, the surface is authored
here from Unreal's own material-graph API — the same route already used for the
road paint and the building facades.
"""
import json

import unreal  # type: ignore[import-not-found]

MAT_DIR = "/Game/LD/Materials"
SURFACE_MASTER = MAT_DIR + "/M_LD_Surface"

_OUTPUT_PROPERTY = {
    "BaseColor": "MP_BASE_COLOR",
    "Normal": "MP_NORMAL",
    "Roughness": "MP_ROUGHNESS",
    "Specular": "MP_SPECULAR",
    "Metallic": "MP_METALLIC",
}


def _expression_class(name: str):
    cls = getattr(unreal, name, None)
    if cls is None:
        raise RuntimeError("unreal has no material expression class %r" % name)
    return cls


def _apply_props(node_obj, props: dict) -> list:
    """Set a node's authored properties, reporting any the class rejects.

    A property the engine silently drops would show up only as a wrong-looking
    render, so every rejection is collected and returned rather than swallowed.
    """
    problems = []
    for key, value in sorted(props.items()):
        v = value
        if key == "default_value" and isinstance(value, (list, tuple)):
            if len(value) == 3:
                v = unreal.LinearColor(float(value[0]), float(value[1]),
                                       float(value[2]), 1.0)
            elif len(value) == 4:
                v = unreal.LinearColor(*[float(c) for c in value])
        try:
            node_obj.set_editor_property(key, v)
        except Exception as exc:                       # noqa: BLE001
            problems.append("%s=%r rejected: %s" % (key, value, exc))
    return problems


def build_surface_material(graph: dict, *, master_path: str = SURFACE_MASTER,
                           rebuild: bool = True) -> dict:
    """Create (or rebuild) the master surface material from a graph spec."""
    at = unreal.AssetToolsHelpers.get_asset_tools()
    eal = unreal.EditorAssetLibrary
    mel = unreal.MaterialEditingLibrary

    pkg, name = master_path.rsplit("/", 1)
    if eal.load_asset(master_path) is not None and rebuild:
        eal.delete_asset(master_path)
    mat = eal.load_asset(master_path)
    if mat is None:
        mat = at.create_asset(name, pkg, unreal.Material, unreal.MaterialFactoryNew())

    made, problems = {}, []
    for node in graph["nodes"]:
        obj = mel.create_material_expression(mat, _expression_class(node["class"]),
                                             int(node.get("x", 0)), int(node.get("y", 0)))
        if obj is None:
            problems.append("create_material_expression returned None for %s" % node["id"])
            continue
        made[node["id"]] = obj
        problems += ["%s: %s" % (node["id"], p)
                     for p in _apply_props(obj, node.get("props") or {})]

    linked = 0
    for c in graph["connections"]:
        a, b = made.get(c["from"]), made.get(c["to"])
        if a is None or b is None:
            problems.append("connection names an unbuilt node: %s -> %s"
                            % (c["from"], c["to"]))
            continue
        if mel.connect_material_expressions(a, c.get("from_output", "") or "",
                                            b, c.get("to_input", "") or ""):
            linked += 1
        else:
            problems.append("connect failed %s -> %s.%s"
                            % (c["from"], c["to"], c.get("to_input", "")))

    wired = {}
    for prop_name, node_id in sorted((graph.get("outputs") or {}).items()):
        obj, enum_name = made.get(node_id), _OUTPUT_PROPERTY.get(prop_name)
        if obj is None or enum_name is None:
            problems.append("output %s -> %s could not be wired" % (prop_name, node_id))
            continue
        ok = mel.connect_material_property(obj, "", getattr(unreal.MaterialProperty, enum_name))
        wired[prop_name] = bool(ok)
        if not ok:
            problems.append("connect_material_property failed for %s" % prop_name)

    mel.recompile_material(mat)
    eal.save_loaded_asset(mat, False)
    return {"master": master_path, "nodes": len(made), "connections_linked": linked,
            "outputs_wired": wired, "problems": problems}


def repoint_instance(instance_path: str, *, textures: dict, scalars: dict,
                     master_path: str = SURFACE_MASTER) -> dict:
    """Reparent a material instance onto the authored master and set its values.

    Reads every parameter back afterwards: written is not the same as written,
    and a value the engine refused would otherwise surface only as a bad frame.
    """
    eal = unreal.EditorAssetLibrary
    mel = unreal.MaterialEditingLibrary
    master = eal.load_asset(master_path)
    mi = eal.load_asset(instance_path)
    if master is None or mi is None:
        raise RuntimeError("missing %s or %s" % (master_path, instance_path))
    old_parent = mi.get_editor_property("parent")
    mel.set_material_instance_parent(mi, master)
    for name, tex_path in sorted(textures.items()):
        t = eal.load_asset(tex_path)
        if t is None:
            continue
        mel.set_material_instance_texture_parameter_value(mi, name, t)
    for name, value in sorted(scalars.items()):
        mel.set_material_instance_scalar_parameter_value(mi, name, float(value))
    eal.save_loaded_asset(mi, False)

    readback = {"scalars": {}, "textures": {}, "mismatches": []}
    for name, value in sorted(scalars.items()):
        got = mel.get_material_instance_scalar_parameter_value(mi, name)
        readback["scalars"][name] = got
        if abs(float(got) - float(value)) > 1e-4:
            readback["mismatches"].append({"param": name, "want": value, "got": got})
    for name, tex_path in sorted(textures.items()):
        got = mel.get_material_instance_texture_parameter_value(mi, name)
        gp = str(got.get_path_name()) if got else None
        readback["textures"][name] = gp
        if gp is None or tex_path.split(".")[0] not in gp:
            readback["mismatches"].append({"param": name, "want": tex_path, "got": gp})
    return {"instance": instance_path,
            "old_parent": str(old_parent.get_path_name()) if old_parent else None,
            "new_parent": str(mi.get_editor_property("parent").get_path_name()),
            "readback": readback}
