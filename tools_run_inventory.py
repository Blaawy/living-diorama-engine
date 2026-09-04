"""Dump the level and run the LEVEL-WIDE inventory (contract C5)."""
from __future__ import annotations
import json, sys
from pathlib import Path
YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
sys.path.insert(0, str(YF / "WORKSPACE"))
from ldyf.unreal_remote import UnrealRemote
from ldyf.world_inventory import level_inventory, write_level_inventory
EV = YF / "EVIDENCE" / "PHASE_02"
DUMP = EV / "level_dump.json"

CODE = r'''
import unreal, json, sys, importlib
sys.path.insert(0, r"__WS__")
import ldyf.unreal.ldyf_level_dump as D
importlib.reload(D)
r = D.dump_level(r"__OUT__", include_components=True, max_components_per_actor=4000)
print("DUMP " + json.dumps(r, default=str))
'''

code = CODE.replace("__WS__", str(YF / "WORKSPACE")).replace("__OUT__", str(DUMP).replace("\\", "/"))
with UnrealRemote(discover_timeout=180.0) as r:
    print(r.output_text(r.exec_file(code))[-600:])

inv = write_level_inventory(DUMP, EV / "level_inventory.json")
print("ACTORS", inv["actors"])
print("ROLES", json.dumps(inv["counts_by_role"], sort_keys=True))
print("BLOCKOUT", inv["blockout_count"], inv.get("blockout_actors"))
print("KITS", json.dumps(inv["building_kits"]))
print("VEHICLES", json.dumps(inv["vehicles"]))
print("PEDS", json.dumps(inv["pedestrians"]))
print("UNKNOWN", inv.get("unknown_actors"))
print("INVENTORY PASS:", inv["pass"])
