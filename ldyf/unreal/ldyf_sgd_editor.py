"""Spawn `sgd_buildings_v1` orders as City Sample shape-grammar buildings.

`ldyf/sgd_buildings.py` decides where every building goes, how big it is, which
way it faces, how tall it is, which family it wears and its seed. This driver
does nothing but hand those decisions to Epic's own graph. Epic owns the
geometry, facades, windows, storeys and roofs.

The production path, proven on one building before any of this was written:

    /CitySamplePCG/PCG/DataAssets/Buildings/PCG_Bldg_SGD_test   (8 nodes)

driven UNMODIFIED through **graph-instance parameter overrides** on a
`PCGVolume`: `Width`, `Length`, `Height` as floats and `ShapeGrammarDefinition`
as a soft object path. No Epic asset is ever written.

Three hard-won rules are baked in:

* **`Assign_CitySampleBuildings` is the wrong primitive.** It is City Sample's
  city-scale *lot* pipeline and yields only a foundation course. Never use it
  here.
* **Only graph-instance parameter overrides are written.** Every editor crash on
  this project (five of them, all `EXCEPTION_ACCESS_VIOLATION` in
  `python311.dll`) followed a *settings-struct* mutation a call or two earlier.
  `PCGGraphParametersHelpers` has never crashed.
* **An asset must be loaded by its PACKAGE path.** `load_asset` returns None for
  the dotted object path form, and `set_object_parameter` then writes null
  *while reporting success*. So the asset is loaded by package path, verified
  non-null, and set with `set_soft_object_path_parameter`.

Generation is deliberately split from construction: PCG generates
asynchronously, so a caller must configure every volume, then issue generation,
then wait on the HOST side before measuring. A `time.sleep` inside the editor
blocks the game thread and generation never completes.
"""
from __future__ import annotations

import unreal  # type: ignore[import-not-found]

PREFIX = "LD_SGD"
GRAPH_PATH = "/CitySamplePCG/PCG/DataAssets/Buildings/PCG_Bldg_SGD_test"

#: A default `PCGVolume` brush is 100 uu of extent per axis, so a scale of N
#: gives N*100 cm of extent. Measured on a spawned volume, not assumed.
VOLUME_EXTENT_PER_SCALE_CM = 100.0

#: The volume only has to CONTAIN the building; the footprint itself comes from
#: Width/Length. These margins are generous on purpose -- a volume that clips
#: the building silently truncates it.
PLAN_MARGIN = 1.6
HEIGHT_MARGIN = 1.8


def _asset_package_path(sgd_asset: str) -> str:
    """Strip the trailing ``.Object`` from a full object path.

    `EditorAssetLibrary.load_asset` returns None for the dotted object-path
    form, and a None asset then gets written as a null override that reports
    success. The orders carry the object path because the engine's
    `SoftObjectPath` wants it, so the package path is derived here.
    """
    pkg = str(sgd_asset)
    if "." in pkg.rsplit("/", 1)[-1]:
        pkg = pkg.rsplit(".", 1)[0]
    return pkg


def clear(prefix: str = PREFIX) -> int:
    """Destroy every building actor this driver made. Returns how many."""
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    n = 0
    for a in list(EAS.get_all_level_actors()):
        if a is not None and str(a.get_actor_label()).startswith(prefix):
            EAS.destroy_actor(a)
            n += 1
    return n


def _volume_scale(order: dict) -> "unreal.Vector":
    width = float(order["width_cm"])
    length = float(order["length_cm"])
    height = float(order["height_cm"])
    plan = max(width, length) * PLAN_MARGIN / VOLUME_EXTENT_PER_SCALE_CM
    tall = height * HEIGHT_MARGIN / VOLUME_EXTENT_PER_SCALE_CM
    return unreal.Vector(plan, plan, tall)


def build(doc: dict, *, block_id: str | None = None,
          prefix: str = PREFIX) -> dict:
    """Spawn and configure one `PCGVolume` per order. Does NOT generate.

    `block_id` restricts the build to a single block, which is how the one-block
    gate is run without converting the city.
    """
    eal = unreal.EditorAssetLibrary
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    H = unreal.PCGGraphParametersHelpers

    graph = eal.load_asset(GRAPH_PATH)
    out: dict = {"removed_previous": clear(prefix), "built": [], "problems": [],
                 "graph": GRAPH_PATH, "graph_loaded": graph is not None,
                 "block_id": block_id}
    if graph is None:
        out["problems"].append("graph missing: %s" % GRAPH_PATH)
        return out

    orders = [o for o in (doc.get("orders") or [])
              if block_id is None or o.get("block_id") == block_id]
    out["orders_selected"] = len(orders)

    for order in sorted(orders, key=lambda o: str(o.get("id"))):
        oid = str(order["id"])
        pkg = _asset_package_path(order["sgd_asset"])
        asset = eal.load_asset(pkg)
        if asset is None:
            # named, never skipped silently: a missing grammar is a content
            # problem the reviewer has to see, not a quietly thinner block
            out["problems"].append("%s: SGD asset missing %s" % (oid, pkg))
            continue

        cx, cy = (float(order["center"][0]), float(order["center"][1]))
        actor = EAS.spawn_actor_from_class(
            unreal.PCGVolume, unreal.Vector(cx, cy, 0.0),
            unreal.Rotator(0.0, 0.0, float(order.get("yaw_deg", 0.0))))
        actor.set_actor_label("%s_%s" % (prefix, oid.replace(":", "_")))
        actor.set_editor_property("tags", ["ld_sgd_building"])
        actor.set_actor_scale3d(_volume_scale(order))

        comps = actor.get_components_by_class(unreal.PCGComponent)
        if not comps:
            out["problems"].append("%s: PCGVolume has no PCGComponent" % oid)
            continue
        comp = comps[0]
        comp.set_graph(graph)
        gi = comp.get_editor_property("graph_instance")

        wrote = {}
        for name, value in (("Width", float(order["width_cm"])),
                            ("Length", float(order["length_cm"])),
                            ("Height", float(order["height_cm"]))):
            try:
                H.set_float_parameter(gi, name, value)
                wrote[name] = value
            except Exception as exc:                           # noqa: BLE001
                out["problems"].append("%s: %s rejected: %s"
                                       % (oid, name, exc))
        try:
            H.set_soft_object_path_parameter(
                gi, "ShapeGrammarDefinition",
                unreal.SoftObjectPath(str(order["sgd_asset"])))
        except Exception as exc:                               # noqa: BLE001
            out["problems"].append("%s: ShapeGrammarDefinition rejected: %s"
                                   % (oid, exc))

        # read the override bag back: a null grammar reports success, so the
        # only trustworthy check is that the family name is actually in there
        txt = str(gi.get_editor_property("parameters_overrides").export_text())
        family = str(order["family"])
        if ("SGD_%s_A" % family) not in txt:
            out["problems"].append(
                "%s: ShapeGrammarDefinition did not take (%s absent from "
                "overrides)" % (oid, family))

        out["built"].append({"id": oid, "label": str(actor.get_actor_label()),
                             "family": family, "wrote": wrote,
                             "yaw_deg": float(order.get("yaw_deg", 0.0))})

    out["built_count"] = len(out["built"])
    out["missing"] = out["orders_selected"] - out["built_count"]
    return out


def generate(prefix: str = PREFIX) -> dict:
    """Issue cleanup+generate on every building actor. Returns what was issued.

    The caller must then wait on the HOST side: PCG is asynchronous and a sleep
    inside the editor blocks the game thread so generation never finishes.
    """
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    out: dict = {"issued": [], "problems": []}
    for a in list(EAS.get_all_level_actors()):
        if a is None or not str(a.get_actor_label()).startswith(prefix):
            continue
        for comp in a.get_components_by_class(unreal.PCGComponent):
            try:
                comp.cleanup(True)
                comp.generate(True)
                out["issued"].append(str(a.get_actor_label()))
            except Exception as exc:                           # noqa: BLE001
                out["problems"].append("%s: %s"
                                       % (a.get_actor_label(), str(exc)[:120]))
    out["issued_count"] = len(out["issued"])
    return out


def measure(prefix: str = PREFIX) -> dict:
    """What actually spawned, per building and in total.

    ``levels`` is the set of City Sample level tokens seen. A token other than
    ``0`` means real WALL modules: the foundation ring alone already gives a
    non-zero instance count, so instance count by itself cannot tell a real
    building from a slab.
    """
    EAS = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    out: dict = {"buildings": [], "totals": {}}
    all_levels: dict = {}
    total = 0
    walls_ok = 0
    for a in sorted((x for x in EAS.get_all_level_actors()
                     if x is not None
                     and str(x.get_actor_label()).startswith(prefix)),
                    key=lambda x: str(x.get_actor_label())):
        meshes: dict = {}
        count = 0
        top = None
        for c in a.get_components_by_class(unreal.StaticMeshComponent):
            try:
                sm = c.get_editor_property("static_mesh")
            except Exception:                                  # noqa: BLE001
                sm = None
            if sm is None:
                continue
            name = sm.get_name()
            try:
                n = int(c.get_instance_count())
            except Exception:                                  # noqa: BLE001
                n = 1
            meshes[name] = meshes.get(name, 0) + n
            count += n
            try:
                mz = float(sm.get_bounding_box().max.z)
            except Exception:                                  # noqa: BLE001
                mz = 0.0
            for i in range(n):
                try:
                    t = c.get_instance_transform(i, True)
                except Exception:                              # noqa: BLE001
                    continue
                z = float(t.translation.z) + mz * float(t.scale3d.z)
                top = z if top is None else max(top, z)
        levels = sorted({k.split("_L")[1].split("_")[0]
                         for k in meshes if "_L" in k},
                        key=lambda v: int(v) if v.isdigit() else 99)
        for lv in levels:
            all_levels[lv] = all_levels.get(lv, 0) + 1
        has_walls = any(t.lstrip("0") not in ("", "0") for t in levels)
        if has_walls:
            walls_ok += 1
        total += count
        b0, b1 = a.get_actor_bounds(False)
        out["buildings"].append({
            "label": str(a.get_actor_label()),
            "instances": count, "distinct_meshes": len(meshes),
            "levels": levels, "has_walls": has_walls,
            "top_z_cm": None if top is None else round(top, 1),
            "origin": [round(b0.x, 1), round(b0.y, 1), round(b0.z, 1)],
            "extent": [round(b1.x, 1), round(b1.y, 1), round(b1.z, 1)],
        })
    out["totals"] = {
        "buildings": len(out["buildings"]),
        "with_walls": walls_ok,
        "without_walls": len(out["buildings"]) - walls_ok,
        "instances": total,
        "levels_histogram": dict(sorted(
            all_levels.items(),
            key=lambda kv: int(kv[0]) if kv[0].isdigit() else 99)),
    }
    return out
