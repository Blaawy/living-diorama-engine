"""The Phase 15 local gate: engine story, Blender structure, visual proof.

Plain Python -- never imports ``bpy``. Orchestrates Blender subprocesses and
the real engine to verify, end to end:

1. Blender 4.5.x LTS is available and refuses nothing silently.
2. The real three-episode proof story generates through the locked engine,
   and its Render Exports parse.
3. The master scene builds headlessly and every structural Blender test
   passes (collections, cameras, idempotency, continuity, refusals).
4. The visual proof frames and the master ``.blend`` render headlessly.
5. Nothing under the save chain or the export files changed one byte, and
   nothing was created inside the save root.

Exit code is nonzero on any failure. Usage::

    python visual/blender/run_phase15_checks.py --workspace <fresh dir> \
        [--blender <blender.exe>] [--preview]
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BLENDER_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = BLENDER_DIR / "scripts"
TESTS_DIR = BLENDER_DIR / "tests"
SPEC_PATH = BLENDER_DIR / "config" / "master_scene_v1.json"
PROOF_TOOLS_DIR = BLENDER_DIR.parent.parent / "tools" / "phase15_proof"

sys.path.insert(0, str(PROOF_TOOLS_DIR))

BLENDER_EXECUTABLE_ENV = "BLENDER_EXECUTABLE"


def locate_blender(explicit: str | None, environ: dict[str, str] | None = None) -> Path:
    """Resolve the Blender executable, refusing to guess machine paths.

    Resolution order: the explicit ``--blender`` argument, then the
    ``BLENDER_EXECUTABLE`` environment variable, then ``blender`` on the
    system PATH. Anything else is a clear failure -- the gate never falls
    back to a hard-coded local installation.
    """
    if environ is None:
        environ = dict(os.environ)
    if explicit:
        candidate = Path(explicit)
        if not candidate.exists():
            raise FileNotFoundError(f"--blender executable not found: {candidate}")
        return candidate
    from_env = environ.get(BLENDER_EXECUTABLE_ENV, "").strip()
    if from_env:
        candidate = Path(from_env)
        if not candidate.exists():
            raise FileNotFoundError(
                f"{BLENDER_EXECUTABLE_ENV} points to a missing executable: {candidate}"
            )
        return candidate
    which = shutil.which("blender")
    if which is not None:
        return Path(which)
    raise FileNotFoundError(
        "no Blender executable found; pass --blender, set "
        f"{BLENDER_EXECUTABLE_ENV}, or put blender on PATH (4.5.x LTS required)"
    )


def require_blender_45(blender: Path) -> str:
    """Refuse any Blender that is not 4.5.x LTS, and return the version."""
    completed = subprocess.run(
        [str(blender), "--version"], capture_output=True, text=True, check=True
    )
    first_line = completed.stdout.splitlines()[0].strip()
    match = re.match(r"Blender (4)\.(5)\.(\d+)", first_line)
    if match is None:
        raise RuntimeError(
            f"unsupported Blender for Phase 15: {first_line!r}; 4.5.x LTS is required"
        )
    return first_line


def run_blender(blender: Path, script: Path, script_args: list[str]) -> None:
    """Run one headless Blender script; surface its output on failure."""
    command = [
        str(blender),
        "--background",
        "--factory-startup",
        "--python",
        str(script),
        "--",
        *script_args,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        sys.stderr.write(completed.stdout[-4000:])
        sys.stderr.write(completed.stderr[-4000:])
        raise RuntimeError(f"Blender step failed: {script.name}")


def tree_hashes(root: Path) -> dict[str, str]:
    """SHA-256 of every file under a directory, keyed by relative path."""
    return {
        str(entry.relative_to(root)).replace("\\", "/"): hashlib.sha256(
            entry.read_bytes()
        ).hexdigest()
        for entry in sorted(root.rglob("*"))
        if entry.is_file()
    }


def main(argv: list[str] | None = None) -> int:
    """Run the complete Phase 15 local verification gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="fresh output directory")
    parser.add_argument("--blender", default=None)
    parser.add_argument("--preview", action="store_true", help="fast low-quality renders")
    arguments = parser.parse_args(argv)
    if not arguments.workspace.strip():
        print("phase 15 checks failed: --workspace must not be empty", file=sys.stderr)
        return 1
    workspace = Path(arguments.workspace)

    try:
        blender = locate_blender(arguments.blender)
        blender_version = require_blender_45(blender)
        print(f"[1/6] {blender_version} at {blender}")

        from generate_proof_exports import generate

        summary = generate(workspace)
        walls = summary["after_walls"]
        if not isinstance(walls, list) or len(walls) != 1:
            raise RuntimeError("proof story did not produce exactly one engine-built wall")
        print("[2/6] proof story generated: one engine-built wall, law restored")

        save_root = workspace / "saves"
        before_export = workspace / "render_export_before.json"
        after_export = workspace / "render_export_after.json"
        saves_before = tree_hashes(save_root)
        exports_before = (
            hashlib.sha256(before_export.read_bytes()).hexdigest(),
            hashlib.sha256(after_export.read_bytes()).hexdigest(),
        )

        blender_workdir = workspace / "blender_work"
        blender_workdir.mkdir(exist_ok=True)
        run_blender(
            blender,
            TESTS_DIR / "run_blender_tests.py",
            [
                "--spec",
                str(SPEC_PATH),
                "--before",
                str(before_export),
                "--after",
                str(after_export),
                "--workdir",
                str(blender_workdir),
            ],
        )
        print("[3/6] Blender structural tests passed")

        proof_dir = workspace / "visual_proof"
        blend_path = proof_dir / "living_diorama_master_scene_v1.blend"
        proof_args = [
            "--spec",
            str(SPEC_PATH),
            "--before",
            str(before_export),
            "--after",
            str(after_export),
            "--outdir",
            str(proof_dir),
            "--blend",
            str(blend_path),
        ]
        if arguments.preview:
            proof_args.append("--preview")
        run_blender(blender, SCRIPTS_DIR / "produce_visual_proof.py", proof_args)
        for name in (
            "phase15_before.png",
            "phase15_after.png",
            "phase15_hero_scar.png",
            "phase15_scar_detail.png",
            "phase15_golden_seal_detail.png",
            "phase15_topology_verify.png",
        ):
            frame = proof_dir / name
            if not frame.exists() or frame.stat().st_size == 0:
                raise RuntimeError(f"proof frame missing or empty: {name}")
        if not blend_path.exists():
            raise RuntimeError("master .blend was not saved")
        print("[4/6] visual proof frames and master .blend produced")

        saves_after = tree_hashes(save_root)
        exports_after = (
            hashlib.sha256(before_export.read_bytes()).hexdigest(),
            hashlib.sha256(after_export.read_bytes()).hexdigest(),
        )
        if saves_before != saves_after:
            raise RuntimeError("the save chain changed during Blender generation")
        if exports_before != exports_after:
            raise RuntimeError("a render export changed during Blender generation")
        print("[5/6] read-only guarantee holds: saves and exports untouched")

        render_report = json.loads((proof_dir / "render_report.json").read_text(encoding="utf-8"))
        manifest = {
            "blender_version": blender_version,
            "master_scene_schema_version": 1,
            "render_engine": "CYCLES",
            "resolution": "1280x720 preview" if arguments.preview else "2560x1440",
            "color_management": {
                "view_transform": "AgX",
                "look": "AgX - Medium High Contrast",
                "exposure": 1.5,
            },
            "sampling": {
                "max_samples": 96 if arguments.preview else 1024,
                "adaptive_threshold": 0.08 if arguments.preview else 0.015,
                "denoiser": "OPENIMAGEDENOISE",
            },
            "source_exports": {
                "before": {
                    "file": before_export.name,
                    "sha256": exports_after[0],
                    "episode": 0,
                },
                "after": {
                    "file": after_export.name,
                    "sha256": exports_after[1],
                    "episode": 2,
                },
            },
            "frames": render_report["frames"],
            "outputs": {
                entry.name: hashlib.sha256(entry.read_bytes()).hexdigest()
                for entry in sorted(proof_dir.iterdir())
                if entry.suffix in (".png", ".blend")
            },
        }
        manifest_path = proof_dir / "phase15_visual_proof_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"[6/6] manifest written: {manifest_path}")
    except Exception as error:  # noqa: BLE001 - the gate reports, then fails loudly
        print(f"phase 15 checks failed: {error}", file=sys.stderr)
        return 1
    print("PHASE 15 LOCAL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
