"""Copy the City Sample prop kits Phase 2 dresses the streets with.

Whole-kit directory copy (Mesh + Material + Texture live together in a City
Sample kit) into the SAME /Game package path so every internal reference
resolves without fixup. Nothing outside the listed kits is copied; anything a
mesh needs that is not in its kit shows up as a null material in the in-editor
verification step and is reported, never hidden.
"""
from __future__ import annotations
import hashlib, json, shutil, time
from pathlib import Path

YF = Path(r"C:\Users\BLaAw\Desktop\LIVING_DIORAMA_WORK_ARCHIVE\YOUTUBE_FACTORY")
SRC = YF / "CACHE" / "CitySample" / "Content"
DST = YF / "WORKSPACE" / "LivingDioramaYF" / "Content"
EV = YF / "EVIDENCE" / "PHASE_02"

KITS = [
    "Prop/Kit_StreetLamp_A",      # traffic lights, walk signals, lamp poles
    "Prop/Kit_StopSign_A",
    "Prop/Kit_Barricade_A",
    "Prop/Kit_ConstructionCone_RR",
    "Prop/Kit_Trashcan_A",
    "Prop/Kit_bench_RR",
    "Prop/Kit_Tree_Birch",
    "Prop/Kit_Tree_Alder",
    "Prop/Kit_Tree_Maple_Red",
    "Prop/Kit_Tree_Maple_Sugar",
    "Prop/Kit_TreeBase_A",
]
SKIP_DIRS = {"Container"}   # HLOD/packed-cluster containers reference level actors


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main() -> int:
    man = {"imported_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "licence": "Epic Content License (Fab, City Sample); free; no purchase",
           "source_project": str(YF / "CACHE" / "CitySample"),
           "mapping": {"/Game/": "Content/"}, "kits": KITS,
           "skipped_dir_names": sorted(SKIP_DIRS), "copied": [], "missing_kits": []}
    total = 0
    for kit in KITS:
        s = SRC / kit
        if not s.is_dir():
            man["missing_kits"].append(kit)
            continue
        for f in sorted(s.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in (".uasset", ".umap"):
                continue
            if any(part in SKIP_DIRS for part in f.relative_to(s).parts):
                continue
            rel = f.relative_to(SRC)
            d = DST / rel
            d.parent.mkdir(parents=True, exist_ok=True)
            if not d.exists() or d.stat().st_size != f.stat().st_size:
                shutil.copy2(f, d)
            n = d.stat().st_size
            total += n
            man["copied"].append({"package": "/Game/" + rel.with_suffix("").as_posix(),
                                  "file": rel.as_posix(), "bytes": n, "sha256": sha(d)})
    man["total_files"] = len(man["copied"])
    man["total_bytes"] = total
    out = EV / "prop_import_manifest.json"
    out.write_text(json.dumps(man, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"files": man["total_files"], "bytes": total,
                      "missing_kits": man["missing_kits"], "manifest": str(out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
