"""Phase 5 -- production: one command from an episode brief to a verified review package.

    python -m ldyf.factory produce --brief <brief.json> --out <package dir>

`produce` WRAPS the locked Phase 4 pipeline (`pipeline.run_factory`, `verify_package`);
it adds the things a person who walks away from the machine needs and Phase 4 left to
the operator:

  preflight   every dependency and the output location are checked BEFORE anything is
              written, and a missing one is named with the way to fix it
  one run     a lock (pid + process creation time, so a recycled pid cannot hold it),
              an append-only journal, a snapshot of the brief the run was started with
  resume      the same command, run again, continues. A package that is already
              finished and verifies is NEVER touched (`already_complete`); a partial one
              is continued; a finished one that no longer verifies is repaired stage by
              stage, because every Phase 4 reuse check re-hashes what it reuses
  honesty     `package.json` is the only marker of a finished package, so the moment a
              run is about to change a directory it moves that marker aside (into the
              state directory, never deleted). A killed run therefore leaves a directory
              that says "unfinished", never one that looks finished and is not
  verdict     after the build the package is verified from disk, and only then is the
              outcome `complete`. `final_status.json` says what happened, in a machine
              readable form, with a typed exit code and advice that never asks anyone to
              delete a finished package

State that is about a RUN, not about the episode, lives beside the package, in
`<out>.production/`: the lock, `journal.jsonl`, `final_status.json`, the brief snapshot,
and `quarantine/`. The package directory itself holds exactly what Phase 4 put there, so
`verify` and the package manifest are unchanged.

No model is called, nothing is published, nothing is spent.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import FACTORY_VERSION, FactoryError
from . import pipeline as P
from . import winproc
from .brief import BriefError, brief_hash, normalise_brief
from .util import SealError, read_json, sha256_bytes, sha256_file, write_json
from .world import REPO_ROOT, WorldError, load_world

PRODUCTION_VERSION = "production_v1"
STATUS_SCHEMA = "production_status_v1"
STATE_SUFFIX = ".production"

#: Exit codes of `produce`. 0 and 3 are the only non-failures; 3 is a plan, not an episode.
EXIT_CODES: dict[str, int] = {
    "complete": 0,
    "already_complete": 0,
    "planned_not_rendered": 3,
    "brief_invalid": 10,
    "dependency_missing": 11,
    "environment": 12,
    "package_conflict": 13,
    "already_running": 14,
    "simulation_failed": 20,
    "evidence_invalid": 21,
    "story_refused": 22,
    "render_failed": 23,
    "audio_failed": 24,
    "assembly_failed": 25,
    "audit_failed": 26,
    "verification_failed": 27,
    "brief_changed_during_run": 28,
    "interrupted": 30,
    "internal_error": 70,
}

_STAGE_CLASS: dict[str, str] = {
    "brief": "brief_invalid", "world": "evidence_invalid", "simulate": "simulation_failed",
    "seal": "evidence_invalid", "facts": "evidence_invalid", "evidence": "evidence_invalid",
    "story": "story_refused", "camera": "story_refused", "narration": "story_refused",
    "render": "render_failed", "voice": "audio_failed", "timeline": "audio_failed",
    "audio": "audio_failed", "assemble": "assembly_failed", "audit": "audit_failed",
    "pipeline": "verification_failed", "production": "internal_error",
}
_CODE_CLASS: dict[tuple[str, str], str] = {
    ("render", "editor_unreachable"): "dependency_missing",
    ("render", "editor_busy"): "dependency_missing",
    ("simulate", "no_sumo"): "dependency_missing",
    ("voice", "no_engine"): "dependency_missing",
    ("voice", "no_voice"): "dependency_missing",
    ("assemble", "no_ffmpeg"): "dependency_missing",
    ("audio", "no_ffmpeg"): "dependency_missing",
    ("seal", "write_failed"): "environment",
    ("pipeline", "package_belongs_to_another_brief"): "package_conflict",
    ("pipeline", "package_is_finished"): "package_conflict",
    ("pipeline", "audit_failed"): "audit_failed",
    ("pipeline", "package_changed"): "verification_failed",
    ("pipeline", "audit_changed"): "verification_failed",
    ("pipeline", "simulation_not_reproduced"): "verification_failed",
    ("pipeline", "episode_does_not_decode"): "verification_failed",
}

_GENERIC_ADVICE = ("Fix the cause named above and run the very same command again: stages that "
                   "are finished and still verify are reused, everything else is redone. Do not "
                   "delete the output directory.")
#: code -> actionable advice. Nothing here ever recommends deleting a package.
ADVICE: dict[str, str] = {
    "editor_unreachable": ("Start the Unreal editor on LivingDioramaYF (project open, Python Remote "
                           "Execution enabled), wait until it has loaded the level, and run the same "
                           "command again. Finished stages are reused."),
    "editor_busy": ("The editor is still rendering an earlier job. Wait for it to finish (or stop the "
                    "render from the editor), then run the same command again."),
    "wrong_level": ("Open /Game/LD/L_LivingDiorama in the editor and run the same command again."),
    "no_sumo": "Install SUMO 1.27 or put sumo.exe on PATH, then run the same command again.",
    "no_ffmpeg": "Install ffmpeg (with libx264) and put ffmpeg/ffprobe on PATH, then run again.",
    "no_voice": ("Install the Windows voice named in the brief (Settings > Time & language > Speech) "
                 "or name an installed voice in brief.voice, then run again."),
    "dependency_missing": "Install or start what the failing check names, then run the same command again.",
    "editor_connection_lost": ("The connection to the Unreal editor dropped. Check that the editor is "
                               "running and responsive, then run the same command again; finished shots "
                               "are reused."),
    "io_error": ("A file in the output location is locked, missing or unreadable (the message names it). "
                 "Close the program holding it or fix the permissions, then run the same command again; "
                 "nothing was lost."),
    "conflicting_consequence": ("Two independent measurements of this brief's simulation disagree, so the "
                                "factory refuses to narrate it. Running again gives the same refusal. The "
                                "factory is proven for close_baker_avenue.json (block B1B2, second 30); "
                                "see EVIDENCE/PHASE_05/facts_generality_investigation.md. Nothing was "
                                "published; use a supported brief or report this rule."),
    "write_failed": ("A file could not be written or replaced (the message names it): the disk is full, "
                     "the file is locked by another program, or its permissions forbid it. Free space, close "
                     "the program or fix the permissions, then run the same command again; nothing was lost."),
    "disk_space": ("Free disk space on the drive named above (a full episode needs about 20 GB while "
                   "it renders) and run the same command again. Finished stages are kept."),
    "output_not_writable": ("Make the output location writable (clear the read-only attribute, fix "
                            "permissions, close the program holding the file) and run the same "
                            "command again. Nothing in the package was changed."),
    "unknown_world": "Name one of the worlds the factory ships (the brief's \"world\" field).",
    "world_not_locked": ("A pinned world file does not match its hash, so the locked world cannot be "
                         "simulated. Restore ldyf/factory/worlds from the MASTER; nothing was written."),
    "bad_status_path": ("Choose a --status-file outside the package and outside <out>.production, and "
                        "not the brief file. Nothing was written."),
    "bad_output_path": "Choose a different --out (a short path on a local drive, not inside the repository).",
    "package_belongs_to_another_brief": ("This directory holds an episode built from a different brief "
                                         "and is untouched. Give this brief its own --out directory."),
    "foreign_directory": ("This directory holds files that are not an episode package, so nothing was "
                          "written. Choose an empty --out directory."),
    "already_running": ("Another production run holds this package. Wait for it, or if it is dead the "
                        "next run takes over by itself (a dead owner's lock is recovered automatically)."),
    "brief_changed_during_run": ("The brief file was edited while the run was in progress. The package "
                                 "is valid for the brief the run STARTED with (see brief.snapshot.json "
                                 "in the state directory). To build the edited brief, run again with a "
                                 "new --out."),
    "audit_failed": ("The truth audit refused the episode, so no package was published. The first "
                     "failure above names the sentence or link; fix the brief or report it. "
                     "Finished stages are kept."),
    "package_changed": ("Files of the package differ from its manifest. Run the same produce command "
                        "again: the changed stage is redone and the rest is verified and reused."),
    "length_out_of_range": ("The honest length of this story is outside the 8-10 minute target. "
                            "Adjust the brief (target_seconds or the rule) and use a new --out."),
    "no_catalogue": ("The factory tells closed-street episodes; choose a close_street rule."),
    "event_not_visible_in_engine": ("A camera did not hold what the story says it does. Nothing was "
                                    "published. Run again (the editor state may have been stale) and, "
                                    "if it repeats, report the beat named above."),
    "plan_would_overwrite_rendered": ("This directory already contains sealed engine render evidence. "
                                      "Run the normal produce command (with rendering enabled) to recover it, "
                                      "or use a new --out directory for a no-render plan."),
}


class ProductionError(FactoryError):
    stage = "production"


_JOB: winproc.KillOnCloseJob | None = None


def process_job() -> winproc.KillOnCloseJob:
    """ONE kill-on-close job per process, however many runs it makes (a handle per run
    would leak in a long-lived caller such as the soak)."""
    global _JOB
    if _JOB is None:
        _JOB = winproc.KillOnCloseJob()
        _JOB.adopt()
    return _JOB


def exit_class(exc: BaseException) -> str:
    """The `EXIT_CODES` key an exception belongs to."""
    if isinstance(exc, KeyboardInterrupt):
        return "interrupted"
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return "dependency_missing"     # the editor's remote-execution socket dropped
    if isinstance(exc, OSError) and not isinstance(exc, FactoryError):
        return "environment"       # a locked, vanished or unreadable file is the machine, not a bug
    if isinstance(exc, ProductionError):
        return {"dependency_missing": "dependency_missing", "disk_space": "environment",
                "output_not_writable": "environment", "bad_output_path": "environment",
                "already_running": "already_running", "brief_unreadable": "brief_invalid",
                "bad_status_path": "environment",
                "editor_busy": "dependency_missing", "wrong_level": "dependency_missing",
                "unknown_world": "brief_invalid", "world_not_locked": "evidence_invalid",
                "editor_unreachable": "dependency_missing",
                "package_belongs_to_another_brief": "package_conflict",
                "plan_would_overwrite_rendered": "package_conflict",
                "foreign_directory": "package_conflict",
                "brief_changed_during_run": "brief_changed_during_run",
                "verification_failed": "verification_failed"}.get(exc.code, "internal_error")
    if isinstance(exc, FactoryError):
        return _CODE_CLASS.get((exc.stage, exc.code)) or _STAGE_CLASS.get(exc.stage, "internal_error")
    return "internal_error"


#: Failures that come from a busy or briefly unavailable machine, not from the episode: the editor
#: dropping a remote-execution call, a renderer that stalled, a file another process still holds.
#: `produce` retries the (resumable) pipeline a bounded number of times before it reports them.
TRANSIENT = {("render", "editor_unreachable"), ("render", "editor_failed"), ("render", "render_incomplete"),
             ("render", "render_not_started"), ("seal", "write_failed")}


def is_transient(exc: BaseException) -> bool:
    if isinstance(exc, FactoryError):
        return (exc.stage, exc.code) in TRANSIENT
    return isinstance(exc, (PermissionError, ConnectionError, TimeoutError))


def advice_for(code: str, klass: str) -> str:
    return ADVICE.get(code) or ADVICE.get(klass) or _GENERIC_ADVICE


# ---------------------------------------------------------------------------- state dir

def state_dir_for(out: Path) -> Path:
    return out.parent / (out.name + STATE_SUFFIX)


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Journal:
    """Append-only, fsynced line log of a package's runs. Wall-clock evidence, hashed by nothing."""

    def __init__(self, path: Path, run_id: str) -> None:
        self.path, self.run_id = path, run_id

    def write(self, event: str, **fields: Any) -> None:
        row = {"t": _utc(), "run": self.run_id, "event": event, **fields}
        line = (json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            with self.path.open("ab") as f:
                if f.tell() > 0:
                    with self.path.open("rb") as r:     # a killed run can leave a torn last line;
                        r.seek(-1, os.SEEK_END)          # never glue this row onto it
                        if r.read(1) != b"\n":
                            f.write(b"\n")
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            pass     # the journal is evidence, never a reason to stop a run

    @staticmethod
    def previous_run(path: Path) -> dict[str, Any] | None:
        """The last run recorded in the journal and whether it ended."""
        if not path.is_file():
            return None
        last_run, rows = None, []
        try:
            # A hard kill can tear a UTF-8 codepoint as well as the JSON line. Replacement
            # decoding is correct here: the damaged tail is evidence, never authoritative state.
            for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    row = json.loads(ln)
                except (ValueError, RecursionError):
                    continue        # a torn final line from a killed run
                if not isinstance(row, dict):
                    continue
                if row.get("event") == "run_start":
                    last_run, rows = row.get("run"), []
                if row.get("run") == last_run:
                    rows.append(row)
        except OSError:
            return None
        if last_run is None:
            return None
        ended = any(r.get("event") == "run_end" for r in rows)
        stages = [r for r in rows if r.get("event") == "stage"]
        return {"run": last_run, "ended": ended,
                "last_stage": stages[-1]["stage"] if stages else None,
                "last_line": next((r.get("line") for r in reversed(rows) if r.get("event") == "log"), None)}


_LOCK_HANDLES: dict[str, tuple[Any, str]] = {}


def _lock_key(path: Path) -> str:
    return str(path.resolve()).rstrip(" .").casefold()


def _try_byte_lock(f: Any) -> bool:
    """Take the OS lock on byte 0 of the open lock file without waiting. True when taken."""
    f.seek(0)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _drop_byte_lock(f: Any) -> None:
    f.seek(0)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def read_owner(state: Path) -> dict[str, Any] | None:
    """Who last took the package lock (diagnostic: the OS lock, not this file, is the authority)."""
    try:
        doc = json.loads((state / "owner.json").read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {"unreadable": True}
    except FileNotFoundError:
        return None
    except (OSError, ValueError, RecursionError, UnicodeDecodeError):
        return {"unreadable": True}


def lock_is_held(state: Path) -> bool:
    """True when some process holds the package lock RIGHT NOW. Asked of the OS, so it is true for
    a live run and false for a dead one, whatever any file says."""
    lock = state / "lock.json"
    if not lock.exists():
        return False
    try:
        f = lock.open("a+b")
    except OSError:
        return True              # cannot even open it: treat as held rather than guess
    try:
        if _try_byte_lock(f):
            _drop_byte_lock(f)
            return False
        return True
    finally:
        f.close()


def acquire_lock(state: Path, run_id: str, journal: Journal) -> dict[str, Any]:
    """Hold an OS byte-range lock for the entire run.

    `lock.json` holds ONLY the locked byte (never readable metadata: a locked byte range cannot be
    read by anyone else, which hid the owner from `status`). Who owns the lock is written to
    `owner.json`, replaced atomically; the OS lock, not that file, is the authority, and it is
    released by the OS when the process dies, however it dies."""
    lock = state / "lock.json"
    me = {"run": run_id, "pid": os.getpid(), "identity": winproc.own_identity(),
          "host": socket.gethostname(), "started_utc": _utc()}
    f = lock.open("a+b")
    try:
        f.seek(0, os.SEEK_END)
        if f.tell() == 0:
            f.write(b"\0")
            f.flush()
            os.fsync(f.fileno())
        taken = False
        for _try in range(8):
            taken = _try_byte_lock(f)
            if taken:
                break
            time.sleep(0.05)          # a `status` poll holds the byte for microseconds; a real run holds it for hours
        if not taken:
            who = read_owner(state) or {}
            raise ProductionError("already_running",
                                  f"another production process holds this package"
                                  + (f" (run {who.get('run')}, pid {who.get('pid')})" if who.get("pid") else ""))
        held = read_owner(state)
        if held and held.get("released"):
            held = None                      # the previous run ended cleanly: nothing was recovered
        write_json(state / "owner.json", me)
        _LOCK_HANDLES[_lock_key(lock)] = (f, run_id)
        if held is not None:
            journal.write("stale_lock_recovered", previous=held)
        return {"recovered_stale_lock": held}
    except BaseException:
        try:
            f.close()
        except OSError:
            pass
        raise


def release_lock(state: Path, run_id: str) -> None:
    lock = state / "lock.json"
    item = _LOCK_HANDLES.pop(_lock_key(lock), None)
    if not item or item[1] != run_id:
        return
    f = item[0]
    try:
        try:                                  # a clean end is recorded, so the next run recovers nothing
            write_json(state / "owner.json", {"released": True, "run": run_id, "released_utc": _utc()})
        except FactoryError:
            pass
        _drop_byte_lock(f)
    finally:
        f.close()


# ----------------------------------------------------------------------------- preflight

def _check(name: str, ok: bool, detail: str, *, code: str = "dependency_missing",
           fatal: bool = True) -> dict[str, Any]:
    return {"check": name, "status": "pass" if ok else ("fail" if fatal else "warn"),
            "detail": detail, "code": code}


def _tool_version(exe: str) -> tuple[bool, str]:
    path = shutil.which(exe)
    if not path:
        return False, f"{exe} is not on PATH"
    try:
        run = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"{exe} could not be run: {e}"
    first = (run.stdout or run.stderr).splitlines()[:1]
    return run.returncode == 0, (first[0] if first else exe)[:120]


def probe_editor(timeout: float = 25.0) -> dict[str, Any]:
    """Ask the running Unreal editor which level it has open and whether a render is running."""
    from . import render as R
    # While a Movie Render Queue job runs, the editor world is the render's PIE world. Ask for the
    # render state FIRST and never let a failed level query turn "busy" into "unreachable".
    code = ("import unreal, json\n"
            "res = {'rendering': False, 'level': None}\n"
            "try:\n"
            "    res['rendering'] = bool(unreal.get_editor_subsystem(unreal.MoviePipelineQueueSubsystem).is_rendering())\n"
            "except Exception as e:\n"
            "    res['rendering_error'] = str(e)[:200]\n"
            "try:\n"
            "    res['level'] = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world().get_path_name()\n"
            "except Exception as e:\n"
            "    res['level_error'] = str(e)[:200]\n"
            "print('LDYF_PROBE ' + json.dumps(res))\n")
    out = R.run_editor(code)
    m = re.search(r"LDYF_PROBE (\{.*\})", out)
    if not m:
        raise ProductionError("dependency_missing", f"the editor answered but not to the probe: {out[-200:]}")
    return json.loads(m.group(1))


_RESERVED_NAMES = frozenset(["CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$"]
                            + [f"COM{i}" for i in range(1, 10)] + [f"LPT{i}" for i in range(1, 10)]
                            + [f"COM{c}" for c in "¹²³"] + [f"LPT{c}" for c in "¹²³"])


def _bad_component(name: str) -> str | None:
    """Why one path component is unusable on Windows (reserved device name, trailing dot/space,
    forbidden character), or None."""
    if not name or name in (".", ".."):
        return None
    if name != name.rstrip(" ."):
        return f"{name!r} ends with a dot or a space (Windows silently drops it, so two spellings name one folder)"
    if any(c in name for c in '<>:"|?*') or any(ord(c) < 32 for c in name):
        return f"{name!r} contains a character Windows does not allow in a name"
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        return f"{name!r} is a reserved Windows device name"
    return None


def status_path_problem(status_path: Path, pkg: Path, state: Path, brief_path: Path) -> str | None:
    """A --status-file must be a plain new or existing file OUTSIDE the package and its state directory,
    and never the brief: it is overwritten by every run."""
    sp = status_path.resolve()
    bp = brief_path.resolve()
    for root, what in ((pkg, "the package"), (state, "the run's state directory")):
        if sp == root or root in sp.parents:
            return f"--status-file {sp} is inside {what}; it would be written into (and could overwrite) it"
    if sp == bp:
        return f"--status-file {sp} is the brief file itself"
    if sp.exists() and not sp.is_file():
        return f"--status-file {sp} is not a file"
    if sp.name.lower() in {n.lower() for n in _ALLOWED_TOP_FILES} | {"brief.snapshot.json", "owner.json",
                                                                      "lock.json", "journal.jsonl",
                                                                      "final_status.json"}:
        return f"--status-file is named {sp.name}, which is a package or run-state file name"
    return _bad_component(sp.name)


def output_path_problem(pkg: Path) -> str | None:
    """Why `pkg` cannot be a package directory, or None. Pure path logic: creates nothing."""
    s = str(pkg)
    for part in pkg.parts[1:]:
        bad = _bad_component(part)
        if bad:
            return bad
    if pkg.parent == pkg or not pkg.name:
        return "a drive root is not a package directory"
    if len(s) > 150:
        return f"path is {len(s)} characters; the render writes nested files under it (Windows limit)"
    if pkg.exists() and not pkg.is_dir():
        return "the output path exists and is not a directory"
    if REPO_ROOT / "ldyf" in (pkg, *pkg.parents):
        return "the output must not be inside the repository's ldyf/ source tree"
    # Windows aliases trailing dots/spaces away and is case-insensitive. Refuse every spelling
    # that can collide with our sibling <out>.production state directory.
    clean_name = pkg.name.rstrip(" .").casefold()
    if clean_name.endswith(STATE_SUFFIX.casefold()):
        return f"a package directory cannot be called *{STATE_SUFFIX}; that name is a run's state directory"
    # Never create a package inside another package/state tree: it would make the parent package
    # invalid merely by creating the child's state files.
    for parent in pkg.parents:
        if parent == Path(pkg.anchor):
            break
        # A user's own brief.json beside the output is the normal layout; only real package
        # markers (a manifest, or a brief with a sealed simulation next to it, or a state dir) count.
        if ((parent / "package.json").is_file()
                or ((parent / "brief.json").is_file() and (parent / "sim").is_dir())
                or parent.name.rstrip(" .").casefold().endswith(STATE_SUFFIX.casefold())):
            return f"the output is nested inside another episode directory: {parent}"
    return None


_ALLOWED_TOP_FILES = {
    "brief.json", "facts.json", "story.json", "shots.json", "narration.json",
    "timeline.json", "captions.srt", "captions.vtt", "assembly.json", "episode.mp4",
    "truth_audit.json", "lineage.json", "contact_sheet.jpg", "package.json", "run_log.json",
}
_ALLOWED_TOP_DIRS = {"sim", "replicates", "render", "voice", "audio"}


def _is_reparse(path: Path) -> bool:
    try:
        return path.is_symlink() or bool(getattr(os.path, "isjunction", lambda _p: False)(path))
    except OSError:
        return True


def validate_package_tree(pkg: Path) -> None:
    """Refuse links/junctions and obvious foreign top-level files before ANY cleanup/mutation.

    A package is an owned tree, never a traversal mechanism into another directory. A partial
    package may contain any of the factory's known top-level artifacts, but a directory that only
    happens to contain a matching brief plus arbitrary user files is not claimed as ours.
    """
    if not pkg.is_dir():
        return
    for entry in pkg.iterdir():
        if _is_reparse(entry):
            raise ProductionError("foreign_directory", f"{entry} is a symlink/junction/reparse point; refusing the package tree")
        if entry.is_dir():
            if entry.name not in _ALLOWED_TOP_DIRS:
                raise ProductionError("foreign_directory", f"{pkg} contains foreign directory {entry.name!r}")
        elif entry.is_file():
            if entry.name.endswith(".tmp"):
                continue  # owned/interrupted-write handling happens only after this tree is accepted
            if entry.name not in _ALLOWED_TOP_FILES and entry.name.lower() not in _OS_JUNK:
                raise ProductionError("foreign_directory", f"{pkg} contains foreign file {entry.name!r}")
        else:
            raise ProductionError("foreign_directory", f"{entry} is not a regular package file/directory")
    # Recursively refuse reparse directories/files without following them.
    stack = [p for p in pkg.iterdir() if p.is_dir()]
    while stack:
        d = stack.pop()
        if _is_reparse(d):
            raise ProductionError("foreign_directory", f"{d} is a symlink/junction/reparse point")
        try:
            children = list(d.iterdir())
        except OSError as e:
            raise ProductionError("output_not_writable", f"cannot inspect {d}: {e}")
        for p in children:
            if _is_reparse(p):
                raise ProductionError("foreign_directory", f"{p} is a symlink/junction/reparse point")
            if p.is_dir():
                stack.append(p)


def run_preflight(pkg: Path, state: Path, brief: dict[str, Any], *, need_editor: bool,
                  min_free_gb: float, dry: bool = False) -> list[dict[str, Any]]:
    """`dry` (used by `doctor`) creates nothing: writability is probed in the nearest EXISTING ancestor."""
    checks: list[dict[str, Any]] = []
    # -- the output location (already validated by `validate_output_path` before anything is made)
    why = output_path_problem(pkg)
    checks.append(_check("output_path", why is None, why or str(pkg), code="bad_output_path"))
    # -- writable. NEVER probe inside the episode directory: a kill between create/unlink
    # would contaminate a finished package and could race its manifest. The state directory and
    # package parent are on the same volume and are the only places touched by the probe.
    for label, d in (("output_parent", pkg.parent), ("state", state)):
        try:
            if dry:
                while not d.exists() and d.parent != d:
                    d = d.parent
            else:
                d.mkdir(parents=True, exist_ok=True)
            probe = d / f".write_probe_{uuid.uuid4().hex[:8]}"
            with probe.open("xb") as f:
                f.write(b"ldyf")
                f.flush()
                os.fsync(f.fileno())
            probe.unlink()
            checks.append(_check(f"{label}_writable", True, str(d)))
        except OSError as e:
            checks.append(_check(f"{label}_writable", False, f"{d}: {e}", code="output_not_writable"))
    # -- disk space
    try:
        probe_dir = pkg
        while not probe_dir.exists() and probe_dir.parent != probe_dir:
            probe_dir = probe_dir.parent         # the nearest ancestor that exists is on the same volume
        free = shutil.disk_usage(probe_dir).free / 1e9
        checks.append(_check("disk_space", free >= min_free_gb,
                             f"{free:.1f} GB free on {pkg.anchor or pkg}, need {min_free_gb:g} GB",
                             code="disk_space"))
    except OSError as e:
        checks.append(_check("disk_space", False, f"cannot read free space: {e}", code="disk_space"))
    # -- tools
    for exe in ("ffmpeg", "ffprobe"):
        ok, detail = _tool_version(exe)
        checks.append(_check(exe, ok, detail))
    ok_x264 = False
    if shutil.which("ffmpeg"):
        try:
            enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True,
                                 timeout=30).stdout
            ok_x264 = "libx264" in enc
        except (OSError, subprocess.SubprocessError):
            ok_x264 = False
    checks.append(_check("ffmpeg_libx264", ok_x264, "libx264 encoder available" if ok_x264
                         else "this ffmpeg has no libx264 encoder"))
    try:
        from .simulate import find_sumo
        import sumolib  # noqa: F401
        import traci  # noqa: F401
        checks.append(_check("sumo", True, find_sumo()))
    except FactoryError as e:
        checks.append(_check("sumo", False, e.message))
    except ImportError as e:
        checks.append(_check("sumo", False, f"python package missing: {e.name}"))
    # -- the speech voice
    if sys.platform != "win32" or not shutil.which("powershell"):
        checks.append(_check("voice", False, "Windows PowerShell (System.Speech) is not available"))
    else:
        try:
            ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis."
                  "SpeechSynthesizer; ($s.GetInstalledVoices() | ? Enabled | % { $_.VoiceInfo.Name }) "
                  "-join '|'")
            names = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                                   capture_output=True, text=True, timeout=60).stdout.strip().split("|")
            checks.append(_check("voice", brief["voice"] in names,
                                 f"{brief['voice']!r} installed" if brief["voice"] in names
                                 else f"voice {brief['voice']!r} is not installed (have {names})"))
        except (OSError, subprocess.SubprocessError) as e:
            checks.append(_check("voice", False, f"cannot list voices: {e}"))
    # -- the locked world
    try:
        load_world(brief["world"])
        checks.append(_check("world", True, f"{brief['world']} matches its pins"))
    except FactoryError as e:
        checks.append(_check("world", False, e.message,
                             code="world_not_locked" if e.code == "world_not_locked" else "unknown_world"))
    # -- the editor
    if need_editor:
        try:
            st = probe_editor()
            level_ok = bool(st["rendering"]) or (
                str(st["level"]).split(".", 1)[0] == "/Game/LD/L_LivingDiorama")
            checks.append(_check("unreal_editor", level_ok, f"level {st['level']}"
                                 + (" (rendering)" if st["rendering"] else ""),
                                 code="wrong_level"))
            checks.append({"check": "unreal_idle", "status": "pass" if not st["rendering"] else "warn",
                           "detail": "no render running" if not st["rendering"]
                           else "a render is running; the run waits for it", "code": "editor_busy",
                           "rendering": bool(st["rendering"])})
        except FactoryError as e:
            checks.append(_check("unreal_editor", False, e.message[:300], code="editor_unreachable"))
    else:
        checks.append({"check": "unreal_editor", "status": "skipped", "code": "",
                       "detail": "every shot of this package is already rendered and sealed"})
    return checks


# ------------------------------------------------------------------- package assessment

def _is_ours(pkg: Path) -> dict[str, Any] | None:
    """The normalised brief a directory was built from, when it is one of our packages."""
    p = pkg / "brief.json"
    if not p.is_file():
        return None
    try:
        return normalise_brief(json.loads(p.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 - not a brief we wrote
        return None


def _assert_existing_package_readable(pkg: Path) -> None:
    """Turn a transient Windows sharing/read failure into ENVIRONMENT, not CORRUPTION.

    Missing or malformed content is deliberately left for `verify_package` to classify. Only a
    file that exists but cannot be opened is handled here, so a scanner/editor holding a file
    never causes package.json to be quarantined and a valid package to be rebuilt.
    """
    manifest = pkg / "package.json"
    try:
        raw = manifest.read_bytes()
    except FileNotFoundError:
        return
    except OSError as e:
        raise ProductionError("output_not_writable", f"cannot read existing package.json: {e}")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return
    rows = doc.get("files") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("file"), str):
            continue
        rel = Path(row["file"])
        if rel.is_absolute() or ".." in rel.parts:
            continue
        p = pkg / rel
        if not p.exists():
            continue
        try:
            with p.open("rb") as f:
                f.read(1)
        except OSError as e:
            raise ProductionError("output_not_writable", f"cannot read existing package file {row['file']}: {e}")


def assess_package(pkg: Path, brief: dict[str, Any]) -> dict[str, Any]:
    """new | partial | finished_valid | finished_invalid -- or a typed refusal."""
    entries = [c for c in pkg.iterdir()] if pkg.is_dir() else []
    if not entries:
        return {"state": "new"}
    old = _is_ours(pkg)
    if old is None:
        raise ProductionError("foreign_directory",
                              f"{pkg} is not empty and holds no episode brief; refusing to write into it")
    if brief_hash(old) != brief_hash(brief):
        raise ProductionError("package_belongs_to_another_brief",
                              f"{pkg} was built from a different brief ({old['title']!r}); an episode "
                              "package is never continued under another brief")
    if not (pkg / "package.json").is_file():
        return {"state": "partial"}
    _assert_existing_package_readable(pkg)
    try:
        res = P.verify_package(pkg)
        return {"state": "finished_valid", "verify": res}
    except FactoryError as e:
        return {"state": "finished_invalid", "reason": f"[{e.stage}:{e.code}] {e.message[:300]}"}
    except (KeyError, TypeError, ValueError, AttributeError, IndexError, RecursionError) as e:
        return {"state": "finished_invalid", "reason": f"[verify:unreadable] {type(e).__name__}: {e}"[:300]}


def _render_sealed(pkg: Path) -> bool:
    """True when every shot of the package is rendered and sealed (the editor is then optional)."""
    try:
        from . import render as R
        R.load_render(pkg / "render" / "render.json")
        return True
    except Exception:  # noqa: BLE001
        return False


def quarantine(state: Path, src: Path, label: str, journal: Journal) -> str | None:
    """Move a file out of the package into the state directory. Never deletes it."""
    if not src.exists():
        return None
    qdir = state / "quarantine"
    qdir.mkdir(parents=True, exist_ok=True)
    if len(label) > 60:        # the quarantine name must stay short enough for a long package path
        label = label[:40] + "_" + sha256_bytes(label.encode("utf-8"))[:12]
    dst = qdir / f"{time.strftime('%Y%m%dT%H%M%S')}_{label}"
    n = 1
    while dst.exists():
        dst = qdir / f"{time.strftime('%Y%m%dT%H%M%S')}_{n}_{label}"
        n += 1
    os.replace(src, dst)
    journal.write("quarantined", file=src.name, to=str(dst.name))
    return dst.name


_OS_JUNK = frozenset(["thumbs.db", "ehthumbs.db", "desktop.ini", ".ds_store"])


def quarantine_os_junk(pkg: Path, state: Path, journal: Journal) -> list[str]:
    """File-manager droppings (Thumbs.db, desktop.ini, .DS_Store) are not part of an episode; moved aside,
    never sealed into a manifest and never a reason to refuse the package."""
    moved = []
    for p in sorted(pkg.rglob("*")):
        if p.is_file() and not _is_reparse(p) and p.name.lower() in _OS_JUNK:
            rel = p.relative_to(pkg).as_posix()
            quarantine(state, p, "junk_" + rel.replace("/", "__"), journal)
            moved.append(rel)
    return moved


def clean_partial_writes(pkg: Path, state: Path, journal: Journal) -> list[str]:
    """Quarantine interrupted atomic-write `*.tmp` files; never delete them.

    `validate_package_tree` has already refused symlinks/junctions, so this traversal cannot
    escape the package. A quarantined file remains recoverable under the run-state directory.
    """
    moved: list[str] = []
    for p in sorted(pkg.rglob("*.tmp")):
        if not p.is_file() or _is_reparse(p):
            continue
        rel = p.relative_to(pkg).as_posix()
        label = "partial_" + rel.replace("/", "__").replace("\\", "__")
        try:
            quarantine(state, p, label, journal)
            moved.append(rel)
            journal.write("partial_write_quarantined", file=rel)
        except OSError as e:
            raise ProductionError("output_not_writable", f"cannot quarantine interrupted write {rel}: {e}")
    return moved


def reap_orphans(pkg: Path, journal: Journal) -> list[int]:
    """Kill SUMO instances an earlier, killed run of THIS package left running. A SUMO
    process is ours to reap only when its command line points into this package and its
    parent no longer exists."""
    needle = str(pkg).lower().replace("\\", "/").rstrip("/") + "/"
    killed = []
    for row in winproc.find_processes("sumo.exe"):
        cmd = row["command_line"].lower().replace("\\", "/")
        if needle in cmd and winproc.process_identity(row["ppid"]) is None:
            if winproc.kill_pid(row["pid"]):
                killed.append(row["pid"])
                journal.write("orphan_reaped", pid=row["pid"], image="sumo.exe")
    return killed


def wait_editor_idle(journal: Journal, log: Callable[[str], None], *, wait_s: float = 1500.0) -> None:
    """A killed run can leave a Movie Render Queue job running inside the editor. Starting a new
    render on top of it would delete the frames it is still writing, so wait for it."""
    t0 = time.perf_counter()
    waited = False
    while True:
        st = probe_editor()
        if not st["rendering"]:
            if waited:
                journal.write("editor_idle_after_wait", seconds=round(time.perf_counter() - t0, 1))
            return
        if not waited:
            log("[production] the editor is still rendering an earlier job; waiting for it")
            journal.write("editor_busy_wait_started")
            waited = True
        if time.perf_counter() - t0 > wait_s:
            raise ProductionError("editor_busy", f"the editor was still rendering after {wait_s:.0f} s")
        time.sleep(5)


# ---------------------------------------------------------------------------- the run

_STAGE_LINE = re.compile(r"^\[(?P<stage>[^\]]+)\] (?P<status>ran|reused|stopped|refused)\b")


def _stage_cost(run_log: Path) -> dict[str, float]:
    """Best-effort historical timing only. Corrupt/untrusted run_log can never fail a run."""
    cost: dict[str, float] = {}
    try:
        doc = json.loads(run_log.read_text(encoding="utf-8", errors="replace"))
        runs = doc.get("runs", []) if isinstance(doc, dict) else []
        if not isinstance(runs, list):
            return cost
        for r in runs:
            if not isinstance(r, dict) or not isinstance(r.get("stages", []), list):
                continue
            for s in r.get("stages", []):
                if not isinstance(s, dict) or s.get("status") != "ran" or not isinstance(s.get("stage"), str):
                    continue
                try:
                    seconds = float(s.get("seconds", 0.0))
                except (TypeError, ValueError, OverflowError):
                    continue
                if seconds >= 0 and seconds < 1e9:
                    cost[s["stage"]] = max(cost.get(s["stage"], 0.0), seconds)
    except (OSError, ValueError, RecursionError, TypeError, AttributeError):
        return {}
    return cost


def _shot_costs(pkg: Path) -> float:
    total = 0.0
    for t in (pkg / "render").glob("*/timing.json"):
        try:
            doc = json.loads(t.read_text(encoding="utf-8", errors="replace"))
            value = doc.get("total_s", 0.0) if isinstance(doc, dict) else 0.0
            seconds = float(value)
            if 0 <= seconds < 1e9:
                total += seconds
        except (OSError, ValueError, TypeError, OverflowError, RecursionError):
            pass
    return total


def _package_bytes(pkg: Path) -> int:
    total = 0
    try:
        for p in pkg.rglob("*"):
            try:
                if p.is_file() and not _is_reparse(p):
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


def produce(brief_path: str | Path, out_dir: str | Path, *, render: bool = True,
            status_path: str | Path | None = None, min_free_gb: float = 20.0,
            log: Callable[[str], None] = print, sim_ports: tuple[int, int] = (55941, 55942),
            wait_editor_s: float = 1500.0, deep: bool = False,
            retry_backoff_s: tuple[float, ...] = (20.0, 60.0)) -> dict[str, Any]:
    """Run (or continue, or just confirm) one episode. Returns the final status document and
    never raises for a refusal: the refusal IS the status. `KeyboardInterrupt` is reported too.
    The only exceptions that escape are for an unusable state directory."""
    t_start = time.perf_counter()
    t_unix = time.time()
    run_id = uuid.uuid4().hex[:12]
    pkg = Path(out_dir).resolve()
    state = state_dir_for(pkg)
    status: dict[str, Any] = {
        "schema_version": STATUS_SCHEMA, "production_version": PRODUCTION_VERSION,
        "factory_version": FACTORY_VERSION, "run_id": run_id, "started_utc": _utc(),
        "package": {"dir": str(pkg), "state_dir": str(state)},
        "outcome": "failed", "exit_code": EXIT_CODES["internal_error"], "exit_class": "internal_error",
        "code": None, "stage": None, "message": None, "advice": None,
    }
    journal = None
    locked = False
    job = process_job()
    try:
        if status_path is not None:
            # FIRST, before anything can fail: a status path that was not proven safe is never written,
            # whatever else goes wrong (a refusal must not overwrite the user's brief)
            bad_status = status_path_problem(Path(status_path), pkg, state, Path(brief_path))
            if bad_status:
                status_path = None
                raise ProductionError("bad_status_path", bad_status)
        why_bad = output_path_problem(pkg)
        if why_bad:
            raise ProductionError("bad_output_path", f"{pkg}: {why_bad}")
        if state.exists() and (state.is_symlink() or state.is_junction() or not state.is_dir()):
            raise ProductionError("bad_output_path", f"{state} exists and is a link or not a directory; the run "
                                                     "state must be a plain directory beside the package")
        try:
            state.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ProductionError("output_not_writable", f"{state} cannot be created: {e}")
        journal = Journal(state / "journal.jsonl", run_id)
        previous = Journal.previous_run(journal.path)
        lock_info = acquire_lock(state, run_id, journal)
        locked = True
        journal.write("run_start", pid=os.getpid(), brief=str(brief_path), out=str(pkg),
                      job_object=job.adopted, version=PRODUCTION_VERSION)
        # Supersede any prior SUCCESS immediately after ownership is established. If this process
        # is TerminateProcess-killed one instruction later, observers see IN_PROGRESS (or the
        # unfinished journal), never the previous run's COMPLETE. last_success_status.json keeps
        # the historical successful verdict separately.
        status.update(outcome="in_progress", exit_class="in_progress", exit_code=None,
                      code=None, stage="production", message="production run in progress", advice=None)
        try:
            write_json(state / "final_status.json", status)
            if status_path:
                write_json(Path(status_path), status)
        except FactoryError as e:
            raise ProductionError("output_not_writable", f"cannot publish in-progress status: {e.message}")
        resumed: dict[str, Any] = {
            "previous_run_interrupted": bool(previous and not previous["ended"]),
            "interrupted_after_stage": previous["last_stage"] if previous and not previous["ended"] else None,
            "recovered_stale_lock": lock_info["recovered_stale_lock"] is not None,
            "partial_writes_removed": [], "quarantined": [], "os_junk_quarantined": [], "orphans_reaped": []}
        status["resumed"] = resumed
        m0 = winproc.process_memory()

        # ---- the brief: read once, snapshot, normalise
        bp = Path(brief_path)
        try:
            if bp.stat().st_size > 1_000_000:
                raise ProductionError("brief_unreadable", f"{bp} is larger than 1 MB; not a brief")
            raw_bytes = bp.read_bytes()
            raw = json.loads(raw_bytes.decode("utf-8-sig"))
        except ProductionError:
            raise
        except (OSError, ValueError, RecursionError) as e:
            raise ProductionError("brief_unreadable", f"the brief {bp} cannot be read as JSON: {e}")
        brief = normalise_brief(raw)
        wdir = Path(__file__).resolve().parent / "worlds" / str(brief["world"])
        if not str(brief["world"]).isidentifier() or not (wdir / "world.json").is_file():
            raise ProductionError("unknown_world", f"the brief names world {brief['world']!r}; the "
                                  f"factory has {sorted(p.name for p in wdir.parent.iterdir() if p.is_dir() and p.name != '__pycache__')}")
        bh = brief_hash(brief)
        source_sha = sha256_bytes(raw_bytes)
        snap = state / "brief.snapshot.json"
        status["brief"] = {"path": str(bp), "title": brief["title"], "brief_sha256": bh,
                           "source_file_sha256": source_sha}
        journal.write("brief", brief_sha256=bh)

        # ---- what is in the output directory, and may we touch it?
        # Refuse foreign files and every reparse-point traversal before verify/cleanup can walk it.
        validate_package_tree(pkg)
        if _is_ours(pkg) is not None:
            resumed["os_junk_quarantined"].extend(quarantine_os_junk(pkg, state, journal))
        assessment = assess_package(pkg, brief)
        status["package"]["state_at_start"] = assessment["state"]
        journal.write("assessed", state=assessment["state"])
        if not render and assessment["state"] != "new" and _render_sealed(pkg):
            raise ProductionError("plan_would_overwrite_rendered",
                                  "--no-render would replace documents bound to existing engine render evidence")
        # Only an accepted brief may become the recovery snapshot. A refused different brief
        # must never overwrite the snapshot named in recovery advice for the package owner.
        write_json(snap, raw)
        write_json(state / f"brief.snapshot.{run_id}.json", raw)
        if assessment["state"] == "finished_invalid":
            journal.write("finished_package_invalid", reason=assessment["reason"])
            log(f"[production] the finished package no longer verifies: {assessment['reason']}")

        # ---- preflight (before anything in the package is written)
        need_editor = render and not (assessment["state"] == "finished_valid" or _render_sealed(pkg))
        if assessment["state"] == "finished_valid":
            need_editor = False
        checks = run_preflight(pkg, state, brief, need_editor=need_editor, min_free_gb=min_free_gb)
        status["preflight"] = checks
        for c in checks:
            if c["status"] != "pass":
                log(f"[preflight] {c['status'].upper()} {c['check']}: {c['detail']}")
        failed = [c for c in checks if c["status"] == "fail"]
        journal.write("preflight", failed=[c["check"] for c in failed])
        if failed:
            f0 = failed[0]
            raise ProductionError(f0["code"], f"preflight: {f0['check']}: {f0['detail']}")

        # ---- already finished and verified: nothing to do, nothing touched
        if assessment["state"] == "finished_valid":
            man = read_json(pkg / "package.json", "package.json", error=ProductionError)
            _finish_ok(status, pkg, man, "already_complete", t_start, job, m0)
            status["verify"] = assessment["verify"]
            if deep:
                try:
                    status["verify"] = P.verify_package(pkg, deep=True, scratch=state / "deep_scratch",
                                                        log=lambda m: log(f"[deep] {m}"))
                except FactoryError as e:
                    # a package that verified a moment ago and fails the deep check is NOT rebuilt or
                    # touched: the evidence may have been forged, or this machine cannot reproduce it
                    raise ProductionError("verification_failed",
                                          f"deep verification refused a package that passes the standard "
                                          f"check: [{e.stage}:{e.code}] {e.message[:300]}")
                finally:
                    shutil.rmtree(state / "deep_scratch", ignore_errors=True)
            status["stages"] = []
            status["performance"] = _performance(pkg, [], t_start, job, m0, reused_only=True)
            journal.write("already_complete", package_hash=man["package_hash"])
            return _publish(status, state, status_path, journal, log)

        # ---- about to change the directory: it stops claiming to be finished
        if (pkg / "package.json").is_file():
            resumed["quarantined"].append(quarantine(state, pkg / "package.json", "package.json", journal))
        resumed["partial_writes_removed"] = clean_partial_writes(pkg, state, journal)
        resumed["os_junk_quarantined"].extend(quarantine_os_junk(pkg, state, journal))
        resumed["orphans_reaped"] = reap_orphans(pkg, journal)
        if render and need_editor:
            wait_editor_idle(journal, log, wait_s=wait_editor_s)

        # ---- the pipeline
        stage_rows: list[dict[str, Any]] = []

        def hook(line: str) -> None:
            log(line)
            if journal is not None:
                m = _STAGE_LINE.match(line)
                if m:
                    journal.write("stage", stage=m["stage"], status=m["status"], line=line[:300])
                else:
                    journal.write("log", line=line[:300])

        summary = None
        attempts = 0
        while True:
            attempts += 1
            try:
                summary = P.run_factory(snap, pkg, resume=True, render=render, sim_ports=sim_ports, log=hook)
                break
            except BaseException as e:  # noqa: BLE001
                if not is_transient(e) or attempts > len(retry_backoff_s):
                    raise
                wait = retry_backoff_s[attempts - 1]
                journal.write("retry", attempt=attempts, error=f"{type(e).__name__}: {e}"[:300], wait_s=wait)
                log(f"[production] transient failure ({type(e).__name__}); retrying in {wait:g} s "
                    f"(attempt {attempts + 1} of {len(retry_backoff_s) + 1})")
                time.sleep(wait)
                reap_orphans(pkg, journal)
                if render:
                    wait_editor_idle(journal, log, wait_s=wait_editor_s)
        status["attempts"] = attempts
        stage_rows = _stages_of_last_run(pkg, t_unix)
        if summary["outcome"] == "planned_not_rendered":
            status.update(outcome="planned_not_rendered", exit_class="planned_not_rendered",
                          exit_code=EXIT_CODES["planned_not_rendered"], stages=stage_rows,
                          message="planned and audited without the render; this is not an episode")
            status["performance"] = _performance(pkg, stage_rows, t_start, job, m0)
            return _publish(status, state, status_path, journal, log)

        # ---- verify from disk before calling it done (there is no way to skip this)
        try:
            status["verify"] = P.verify_package(pkg, deep=deep, scratch=state / "deep_scratch",
                                                log=lambda m: log(f"[deep] {m}"))
            shutil.rmtree(state / "deep_scratch", ignore_errors=True)
        except FactoryError as e:
            quarantine(state, pkg / "package.json", "package.json.unverified", journal)
            raise ProductionError("verification_failed",
                                  f"the finished package does not verify: [{e.stage}:{e.code}] "
                                  f"{e.message[:300]}")
        # ---- the brief file must still be the one the run started with
        try:
            now_sha = sha256_bytes(bp.read_bytes())
        except OSError:
            now_sha = None
        if now_sha != source_sha:
            status["package"]["valid_for_snapshot"] = True
            raise ProductionError("brief_changed_during_run",
                                  f"{bp} changed while the run was in progress; the package matches the "
                                  "brief the run started with")
        man = read_json(pkg / "package.json", "package.json", error=ProductionError)
        _finish_ok(status, pkg, man, "complete", t_start, job, m0)
        status["stages"] = stage_rows
        status["performance"] = _performance(pkg, stage_rows, t_start, job, m0)
        return _publish(status, state, status_path, journal, log)

    except BaseException as e:  # noqa: BLE001 - every outcome is reported, even Ctrl-C
        if not isinstance(e, (Exception, KeyboardInterrupt)):
            raise
        klass = exit_class(e)
        code = getattr(e, "code", "io_error" if klass == "environment" else (
            "editor_connection_lost" if isinstance(e, (ConnectionError, TimeoutError)) else type(e).__name__))
        stage = getattr(e, "stage", "production")
        status.update(outcome="interrupted" if klass == "interrupted" else "failed",
                      exit_class=klass, exit_code=EXIT_CODES[klass], code=code, stage=stage,
                      message=(getattr(e, "message", None) or str(e) or type(e).__name__)[:1200],
                      advice=advice_for(code, klass))
        if klass in ("internal_error", "environment") and not isinstance(e, FactoryError):
            status["message"] = f"{type(e).__name__}: {e}"[:1200]
        status["package"]["state_at_end"] = _state_at_end(pkg)
        status.setdefault("stages", _stages_of_last_run(pkg, t_unix) if pkg.is_dir() else [])
        status["finished_utc"] = _utc()
        status["wall_seconds"] = round(time.perf_counter() - t_start, 2)
        for k in ("package_hash", "episode", "episode_sha256", "seconds", "frames", "beats", "files",
                  "truth_audit", "review_first"):
            status["package"].pop(k, None)          # a failed run never carries a success's facts
        if code == "already_running":
            return status                           # not the owner: leave the live run's files alone
        if locked and state.is_dir():
            return _publish(status, state, status_path, journal, log)
        if status_path and not locked and code not in ("bad_output_path", "bad_status_path"):
            _write_status_file(Path(status_path), status)
        return status
    finally:
        if locked:
            release_lock(state, run_id)


def _state_at_end(pkg: Path) -> str:
    if (pkg / "package.json").is_file():
        return "marked_finished"
    if not pkg.is_dir() or not any(pkg.iterdir()):
        return "empty"
    return "unfinished_resumable"


def _stages_of_last_run(pkg: Path, since_unix: float | None = None) -> list[dict[str, Any]]:
    """Best-effort display/performance metadata; malformed unhashed run logs never fail recovery."""
    try:
        doc = json.loads((pkg / "run_log.json").read_text(encoding="utf-8", errors="replace"))
        if not isinstance(doc, dict) or not isinstance(doc.get("runs"), list) or not doc["runs"]:
            return []
        last = doc["runs"][-1]
        if not isinstance(last, dict) or not isinstance(last.get("stages"), list):
            return []
        if since_unix is not None and float(last.get("started_unix", 0)) < since_unix - 1.0:
            return []           # that is an EARLIER run's log: this run never reached a stage
        return [s for s in last["stages"] if isinstance(s, dict)]
    except (OSError, ValueError, RecursionError, KeyError, IndexError, TypeError, AttributeError):
        return []


def _finish_ok(status: dict[str, Any], pkg: Path, man: dict[str, Any], outcome: str, t_start: float,
               job: winproc.KillOnCloseJob, m0: dict[str, Any]) -> None:
    status.update(outcome=outcome, exit_class=outcome, exit_code=0, code=None, stage=None,
                  message=None, advice=None)
    status["package"].update({
        "state_at_end": "finished_verified", "package_hash": man["package_hash"],
        "episode": str(pkg / "episode.mp4"), "episode_sha256": next(
            (r["sha256"] for r in man["files"] if r["file"] == "episode.mp4"), None),
        "seconds": man["seconds"], "frames": man["frames"], "beats": man["beats"],
        "files": len(man["files"]), "bytes": _package_bytes(pkg),
        "truth_audit": man["truth_audit"], "review_first": man["review_first"]})
    status["finished_utc"] = _utc()
    status["wall_seconds"] = round(time.perf_counter() - t_start, 2)


def _performance(pkg: Path, stages: list[dict[str, Any]], t_start: float, job: winproc.KillOnCloseJob,
                 m0: dict[str, Any], *, reused_only: bool = False) -> dict[str, Any]:
    cost = _stage_cost(pkg / "run_log.json")
    clean = [s for s in stages if isinstance(s, dict) and isinstance(s.get("stage"), str)]
    ran = {s["stage"]: s.get("seconds") for s in clean if s.get("status") == "ran"}
    reused = [s["stage"] for s in clean if s.get("status") == "reused"]
    avoided = round(sum(cost.get(s, 0.0) for s in reused), 1)
    shot_cost = _shot_costs(pkg)
    m1 = winproc.process_memory()
    peak_job = job.peak_memory_bytes()
    return {
        "wall_seconds": round(time.perf_counter() - t_start, 2),
        "stage_seconds": {s["stage"]: s.get("seconds") for s in clean},
        "stages_ran": sorted(ran), "stages_reused": sorted(reused),
        "reuse_avoided_seconds_estimate": avoided,
        "reused_render_shots_cold_cost_seconds": round(shot_cost, 1) if "render" in ran or reused_only else None,
        "note": ("reuse_avoided_seconds_estimate is historical run_log timing, not a stopwatch; "
                 "job_peak_committed_mb covers this process and its child SUMO/ffmpeg/PowerShell "
                 "processes only and EXCLUDES the separately running Unreal Editor"),
        "process_peak_working_set_mb": round((m1["peak_working_set_bytes"] or 0) / 2**20, 1),
        "job_peak_committed_mb": round(peak_job / 2**20, 1) if peak_job else None,
        "handles_start": m0["handles"], "handles_end": m1["handles"],
    }


def _write_status_file(path: Path, doc: dict[str, Any]) -> None:
    try:
        write_json(path, doc)
    except FactoryError:
        pass


def _publish(status: dict[str, Any], state: Path, status_path: str | Path | None,
             journal: Journal | None, log: Callable[[str], None]) -> dict[str, Any]:
    status.setdefault("finished_utc", _utc())
    try:
        write_json(state / "final_status.json", status)
        if status["exit_code"] == 0:
            # a later refusal (another brief, a missing tool) must not erase the record of success
            write_json(state / "last_success_status.json", status)
    except FactoryError as e:
        log(f"[production] could not write final_status.json: {e.message}")
    if status_path:
        _write_status_file(Path(status_path), status)
    if journal is not None:
        journal.write("run_end", outcome=status["outcome"], exit_code=status["exit_code"],
                      code=status.get("code"))
    return status


# ----------------------------------------------------------------------- status / doctor

def guard_advanced_run(brief_path: str | Path, out_dir: str | Path) -> None:
    """Safety gate for the legacy/debug `run` CLI.

    The advanced runner may continue only an empty or owned partial directory, never a finished
    package, foreign directory, or package currently owned by `produce`. There is intentionally
    no destructive "start over" command.
    """
    pkg = Path(out_dir).resolve()
    why = output_path_problem(pkg)
    if why:
        raise ProductionError("bad_output_path", f"{pkg}: {why}")
    st = read_status(pkg)
    if st.get("run_in_progress"):
        raise ProductionError("already_running", "a production run currently owns this package")
    if not pkg.exists() or not any(pkg.iterdir()):
        return
    validate_package_tree(pkg)
    try:
        raw = json.loads(Path(brief_path).read_bytes().decode("utf-8-sig"))
        brief = normalise_brief(raw)
    except (OSError, ValueError, RecursionError, BriefError) as e:
        raise ProductionError("brief_unreadable", f"cannot validate the advanced-run brief: {e}")
    old = _is_ours(pkg)
    if old is None:
        raise ProductionError("foreign_directory", f"{pkg} is not an owned episode package")
    if brief_hash(old) != brief_hash(brief):
        raise ProductionError("package_belongs_to_another_brief", f"{pkg} belongs to another brief")
    if (pkg / "package.json").is_file():
        raise ProductionError("package_belongs_to_another_brief",
                              "advanced run refuses a finished package; use produce to confirm it")


def read_status(out_dir: str | Path) -> dict[str, Any]:
    """The last recorded outcome of a package, plus whether a run is in progress now."""
    pkg = Path(out_dir).resolve()
    state = state_dir_for(pkg)
    doc: dict[str, Any] = {"package": str(pkg), "state_dir": str(state),
                           "package_state": _state_at_end(pkg) if pkg.is_dir() else "absent"}
    fs = state / "final_status.json"
    if fs.is_file():
        try:
            doc["last_run"] = json.loads(fs.read_text(encoding="utf-8"))
        except ValueError:
            doc["last_run"] = {"unreadable": True}
    running = lock_is_held(state)
    owner = read_owner(state)
    if owner is not None:
        doc["lock"] = owner
    doc["run_in_progress"] = running
    prev = Journal.previous_run(state / "journal.jsonl")
    if prev:
        doc["last_journal_run"] = prev
        last = doc.get("last_run")
        if (not running and not prev["ended"] and isinstance(last, dict)
                and last.get("outcome") == "in_progress"):
            detected = dict(last)
            detected.update(outcome="interrupted", exit_class="interrupted_detected",
                            exit_code=EXIT_CODES["interrupted"],
                            message="the last production process ended before publishing a final verdict")
            doc["last_run"] = detected
    return doc


def doctor(brief_path: str | Path, out_dir: str | Path, *, render: bool = True,
           min_free_gb: float = 20.0) -> dict[str, Any]:
    """Preflight only. It never writes inside the package; writable probes live in the
    sibling state/parent directories. CLI exit is 0 only when no check failed."""
    pkg = Path(out_dir).resolve()
    state = state_dir_for(pkg)
    try:
        raw = json.loads(Path(brief_path).read_bytes().decode("utf-8-sig"))
        brief = normalise_brief(raw)
    except (OSError, ValueError, BriefError) as e:
        return {"ok": False, "checks": [{"check": "brief", "status": "fail", "detail": str(e),
                                         "code": "brief_unreadable"}]}
    # what produce would say about the directory and the lock, without touching either
    extra: list[dict[str, Any]] = []
    try:
        if pkg.is_dir() and any(pkg.iterdir()):
            validate_package_tree(pkg)
            old = _is_ours(pkg)
            if old is None:
                raise ProductionError("foreign_directory", f"{pkg} is not empty and holds no episode brief")
            if brief_hash(old) != brief_hash(brief):
                raise ProductionError("package_belongs_to_another_brief",
                                      f"{pkg} was built from a different brief ({old['title']!r})")
        extra.append(_check("package_directory", True, "new, or this brief's own package"))
    except ProductionError as e:
        extra.append(_check("package_directory", False, e.message, code=e.code))
    if state.exists() and (state.is_symlink() or state.is_junction() or not state.is_dir()):
        extra.append(_check("state_directory", False, f"{state} is a link or not a directory",
                            code="bad_output_path"))
    elif state.exists() and lock_is_held(state):
        extra.append(_check("not_running", False, "a production run holds this package now",
                            code="already_running"))
    checks = run_preflight(pkg, state, brief, need_editor=render and not _render_sealed(pkg),
                           min_free_gb=min_free_gb, dry=True) + extra
    return {"ok": all(c["status"] != "fail" for c in checks), "checks": checks}
