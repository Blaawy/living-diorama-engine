"""Execute a ``facade_spec_v1`` node graph into a real Unreal material.

The graph itself lives in ``ldyf.facade`` as pure data so it can be unit-tested
without an editor; this module is the thin part that actually talks to
``MaterialEditingLibrary``. Keeping the split means a change to the facade
design is caught by tests, not by looking at a render.

Creates one master material plus one ``MaterialInstanceConstant`` per building
kit, so the three kits differ only by parameter values on a shared graph.
"""
import json

import unreal  # type: ignore[import-not-found]

MAT_DIR = "/Game/LD/Materials"
FACADE_MASTER = MAT_DIR + "/M_LD_Facade"
FACADE_INSTANCE = MAT_DIR + "/MI_LD_Facade_%s"

_OUTPUT_PROPERTY = {
    "BaseColor": "MP_BASE_COLOR",
    "Roughness": "MP_ROUGHNESS",
    "Metallic": "MP_METALLIC",
    "Specular": "MP_SPECULAR",
    "EmissiveColor": "MP_EMISSIVE_COLOR",
}


def _expression_class(name: str):
    cls = getattr(unreal, name, None)
    if cls is None:
        raise RuntimeError("unreal has no material expression class %r" % name)
    return cls


def _apply_props(node_obj, props: dict) -> list:
    """Set a node's authored properties, reporting any the class rejects.

    A property that does not exist on this engine version is reported rather
    than swallowed: a silently unset window width would show up only as a
    wrong-looking render, which is exactly the failure mode this project is
    supposed to make impossible.
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


def build_facade_material(graph: dict, *, master_path: str = FACADE_MASTER,
                          rebuild: bool = True) -> dict:
    """Create (or rebuild) the master material from a ``facade_spec_v1`` graph."""
    at = unreal.AssetToolsHelpers.get_asset_tools()
    eal = unreal.EditorAssetLibrary
    mel = unreal.MaterialEditingLibrary

    pkg, name = master_path.rsplit("/", 1)
    existing = eal.load_asset(master_path)
    if existing is not None and rebuild:
        eal.delete_asset(master_path)
        existing = None
    mat = existing
    if mat is None:
        mat = at.create_asset(name, pkg, unreal.Material, unreal.MaterialFactoryNew())
    mat.set_editor_property("two_sided", False)

    made = {}
    problems = []
    for node in graph["nodes"]:
        cls = _expression_class(node["class"])
        obj = mel.create_material_expression(mat, cls,
                                             int(node.get("x", 0)), int(node.get("y", 0)))
        if obj is None:
            problems.append("create_material_expression returned None for %s" % node["id"])
            continue
        made[node["id"]] = obj
        problems += ["%s: %s" % (node["id"], p) for p in _apply_props(obj, node.get("props") or {})]

    linked = 0
    for c in graph["connections"]:
        a, b = made.get(c["from"]), made.get(c["to"])
        if a is None or b is None:
            problems.append("connection names an unbuilt node: %s -> %s" % (c["from"], c["to"]))
            continue
        ok = mel.connect_material_expressions(a, c.get("from_output", "") or "",
                                              b, c.get("to_input", "") or "")
        if not ok:
            problems.append("connect failed %s.%s -> %s.%s"
                            % (c["from"], c.get("from_output", ""), c["to"], c.get("to_input", "")))
        else:
            linked += 1

    wired = {}
    for prop_name, node_id in sorted((graph.get("outputs") or {}).items()):
        obj = made.get(node_id)
        enum_name = _OUTPUT_PROPERTY.get(prop_name)
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


def build_kit_instances(kits: dict, *, master_path: str = FACADE_MASTER) -> dict:
    """One ``MaterialInstanceConstant`` per kit, all sharing the master graph.

    ``kits`` maps kit name -> ``ldyf.facade.kit_parameters(kit)``.
    """
    at = unreal.AssetToolsHelpers.get_asset_tools()
    eal = unreal.EditorAssetLibrary
    mel = unreal.MaterialEditingLibrary
    master = eal.load_asset(master_path)
    if master is None:
        raise RuntimeError("facade master %s does not exist" % master_path)
    out = {}
    for kit in sorted(kits):
        path = FACADE_INSTANCE % kit
        pkg, name = path.rsplit("/", 1)
        mi = eal.load_asset(path)
        if mi is None:
            mi = at.create_asset(name, pkg, unreal.MaterialInstanceConstant,
                                 unreal.MaterialInstanceConstantFactoryNew())
        mel.set_material_instance_parent(mi, master)
        params = kits[kit]
        for pname, value in sorted((params.get("scalar") or {}).items()):
            mel.set_material_instance_scalar_parameter_value(mi, pname, float(value))
        for pname, value in sorted((params.get("vector") or {}).items()):
            mel.set_material_instance_vector_parameter_value(
                mi, pname, unreal.LinearColor(float(value[0]), float(value[1]),
                                              float(value[2]), 1.0))
        eal.save_loaded_asset(mi, False)
        out[kit] = path
    return out


def verify_instances(kits: dict) -> dict:
    """Read the parameter values back off the saved instances.

    Written back is not the same as written: this re-reads every scalar and
    vector so a parameter the engine quietly refused shows up as a mismatch
    instead of as a wrong-looking building.
    """
    eal = unreal.EditorAssetLibrary
    mel = unreal.MaterialEditingLibrary
    report = {}
    for kit in sorted(kits):
        path = FACADE_INSTANCE % kit
        mi = eal.load_asset(path)
        if mi is None:
            report[kit] = {"loaded": False}
            continue
        wanted = kits[kit]
        bad = []
        for pname, value in sorted((wanted.get("scalar") or {}).items()):
            got = mel.get_material_instance_scalar_parameter_value(mi, pname)
            if abs(float(got) - float(value)) > 1e-4:
                bad.append({"param": pname, "want": value, "got": got})
        for pname, value in sorted((wanted.get("vector") or {}).items()):
            got = mel.get_material_instance_vector_parameter_value(mi, pname)
            for i, comp in enumerate(("r", "g", "b")):
                if abs(float(getattr(got, comp)) - float(value[i])) > 1e-3:
                    bad.append({"param": pname, "component": comp,
                                "want": value[i], "got": float(getattr(got, comp))})
        report[kit] = {"loaded": True, "mismatches": bad,
                       "parent": str(mi.get_editor_property("parent").get_path_name())}
    return report
