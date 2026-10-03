"""Fault lab: prove the production command survives the death of its own process.

A `finally` clause cannot answer `TerminateProcess`. So the lab runs `produce` as a real child
process, watches its output and the package directory, and kills it the hard way at a chosen
moment -- mid-simulation, mid-voice, mid-render, mid-assembly, mid-audit, mid-package -- exactly
as a power cut or `taskkill /F` would. The caller then runs `produce` again and checks what the
resume did.

Used by the Phase 5 tests and by `tools_soak.py`. It imports nothing from the pipeline: it only
starts the CLI and looks at files, so it tests the product boundary and nothing else.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .world import REPO_ROOT

Trigger = Callable[[str, Path], bool]


def line_contains(text: str) -> Trigger:
    """Kill on the first output line containing `text`."""
    return lambda line, pkg: text in line


def path_exists(rel: str) -> Trigger:
    """Kill as soon as `pkg/rel` exists (checked on every output line and every poll)."""
    return lambda line, pkg: (pkg / rel).exists()


def frames_in(beat: str, n: int) -> Trigger:
    """Kill while a shot is being rendered: when `n` frames of `beat` are on disk."""
    return lambda line, pkg: len(list((pkg / "render" / beat / "frames").glob("frame_*.png"))) >= n


def delayed(trigger: Trigger, seconds: float) -> Trigger:
    """Kill `seconds` after `trigger` first fires (to land inside the stage that follows it)."""
    seen: list[float] = []

    def fire(line: str, pkg: Path) -> bool:
        if not seen and trigger(line, pkg):
            seen.append(time.perf_counter())
        return bool(seen) and time.perf_counter() - seen[0] >= seconds
    return fire


def run_produce(brief: str | Path, out: str | Path, *, kill_when: Trigger | None = None,
                timeout_s: float = 7200.0, extra: tuple[str, ...] = (), env: dict[str, str] | None = None,
                status_file: str | Path | None = None) -> dict[str, Any]:
    """Run `python -m ldyf.factory produce` as a child. Returns
    {returncode, killed, trigger_line, lines, seconds, stdout_tail}. `killed` is True when the
    lab terminated it; `returncode` is then the platform's kill code, not a product exit code."""
    out = Path(out).resolve()
    cmd = [sys.executable, "-m", "ldyf.factory", "produce", "--brief", str(brief), "--out", str(out), *extra]
    if status_file:
        cmd += ["--status-file", str(status_file)]
    child_env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", **(env or {})}
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", env=child_env)
    lines: list[str] = []
    state = {"killed": False, "trigger": None}
    lock = threading.Lock()

    def kill(reason: str) -> None:
        with lock:
            if state["killed"] or proc.poll() is not None:
                return
            state["killed"], state["trigger"] = True, reason
            proc.kill()           # TerminateProcess: no finally, no atexit, no flush

    def reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            lines.append(line)
            if kill_when is not None and not state["killed"] and kill_when(line, out):
                kill(line)

    def poller() -> None:
        while proc.poll() is None and not state["killed"]:
            if kill_when is not None and kill_when("", out):
                kill("(poll)")
            if time.perf_counter() - t0 > timeout_s:
                kill("(timeout)")
            time.sleep(0.25)

    threads = [threading.Thread(target=reader, daemon=True), threading.Thread(target=poller, daemon=True)]
    for t in threads:
        t.start()
    rc = proc.wait()
    for t in threads:
        t.join(timeout=10)
    return {"returncode": rc, "killed": state["killed"], "trigger_line": state["trigger"], "lines": lines,
            "seconds": round(time.perf_counter() - t0, 1), "stdout_tail": "\n".join(lines[-12:])}


def status_of(out: str | Path) -> dict[str, Any]:
    """`final_status.json` of a package, or {} when no run has finished."""
    from .production import state_dir_for
    p = state_dir_for(Path(out).resolve()) / "final_status.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tree_digest(root: str | Path, *, skip: tuple[str, ...] = ("run_log.json",)) -> dict[str, str]:
    """{relative path: sha256} of every file under `root` -- what 'untouched' is compared against."""
    from .util import sha256_file
    root = Path(root)
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted(root.rglob("*"))
            if p.is_file() and p.relative_to(root).as_posix() not in skip}


def corrupt_file(path: str | Path, *, mode: str = "flip") -> None:
    """Damage a file the way storage does: flip a byte in the middle ('flip'), cut it short
    ('truncate'), or empty it ('empty'). Written as a NEW file so a hard link elsewhere is
    unaffected."""
    p = Path(path)
    data = p.read_bytes()
    if mode == "flip":
        i = len(data) // 2
        data = data[:i] + bytes([data[i] ^ 0xFF]) + data[i + 1:]
    elif mode == "truncate":
        data = data[: max(1, len(data) // 3)]
    elif mode == "empty":
        data = b""
    else:
        raise ValueError(mode)
    tmp = p.with_name(p.name + ".corrupt")
    tmp.write_bytes(data)
    os.replace(tmp, p)
