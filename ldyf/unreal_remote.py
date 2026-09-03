"""Out-of-process Python into a running Unreal Editor.

Why this exists
---------------
The Unreal MCP sandbox permits only `{time, re, copy, math, json, datetime}` --
no file I/O, no `unreal` module (RT-05). It is the right channel for authoring
and commanding, and the wrong channel for playback: a 6,000-frame record with
~200 concurrent actors would be ~1.2 million JSON-RPC round trips.

Epic ships a second channel: the PythonScriptPlugin's **remote execution**
(`Engine/Plugins/Experimental/PythonScriptPlugin/Content/Python/remote_execution.py`).
A UDP multicast handshake on `239.0.0.1:6766` discovers the editor; a TCP
command connection then runs Python **inside the editor process**, with the
full `unreal` module and file I/O. That is where playback belongs: the record is
read once, inside the editor, and driven by the editor's own tick.

This module wraps that client. It sends *commands*; the heavy lifting lives in
`ldyf/unreal/ldyf_playback.py`, which runs in-editor.

Prerequisite (editor side)
--------------------------
`bRemoteExecution=True` under `[/Script/PythonScriptPlugin.PythonScriptPluginSettings]`
in the project's `DefaultEngine.ini` (or Editor Preferences > Plugins > Python >
Enable Remote Execution). Multicast TTL 0 keeps it on the local host.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

_PLUGIN_PY = Path(
    r"C:\Program Files\Epic Games\UE_5.8\Engine\Plugins\Experimental"
    r"\PythonScriptPlugin\Content\Python"
)


class UnrealRemoteError(RuntimeError):
    pass


def _import_remote_execution():
    if str(_PLUGIN_PY) not in sys.path:
        sys.path.insert(0, str(_PLUGIN_PY))
    try:
        import remote_execution  # type: ignore[import-not-found]
    except ImportError as e:
        raise UnrealRemoteError(
            f"remote_execution.py not importable from {_PLUGIN_PY}: {e}"
        ) from e
    return remote_execution


class UnrealRemote:
    """One command connection to one editor."""

    def __init__(self, discover_timeout: float = 15.0) -> None:
        self._re = _import_remote_execution()
        self._exec = self._re.RemoteExecution()
        self.discover_timeout = discover_timeout
        self.node_id: str | None = None

    # --- lifecycle --------------------------------------------------------

    def connect(self) -> str:
        self._exec.start()
        deadline = time.time() + self.discover_timeout
        while time.time() < deadline:
            nodes = self._exec.remote_nodes
            if nodes:
                self.node_id = nodes[0]["node_id"]
                # The editor answers discovery before it is ready to dial the
                # command socket; opening immediately fails with "Remote party
                # failed to attempt the command socket connection" (seen on
                # 2026-09-03 with an idle editor). Settle, then retry the open.
                last: Exception | None = None
                for attempt in range(4):
                    time.sleep(1.0 + attempt)
                    try:
                        self._exec.open_command_connection(self.node_id)
                        return self.node_id
                    except Exception as e:  # noqa: BLE001 - plugin raises bare RuntimeError
                        last = e
                self._exec.stop()
                raise UnrealRemoteError(f"editor {self.node_id} discovered but the command socket never opened: {last}")
            time.sleep(0.25)
        self._exec.stop()
        raise UnrealRemoteError(
            f"no Unreal Editor answered multicast discovery within "
            f"{self.discover_timeout}s. Is the editor running with "
            "bRemoteExecution=True in PythonScriptPluginSettings?"
        )

    def close(self) -> None:
        try:
            if self._exec.has_command_connection():
                self._exec.close_command_connection()
        finally:
            self._exec.stop()

    def __enter__(self) -> UnrealRemote:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- commands ---------------------------------------------------------

    def exec_file(self, code: str, unattended: bool = True) -> dict[str, Any]:
        """Run multi-statement Python inside the editor."""
        return self._run(code, self._re.MODE_EXEC_FILE, unattended)

    def eval(self, expression: str, unattended: bool = True) -> Any:
        """Evaluate one expression inside the editor and return its value.

        `EvaluateStatement` hands back `str(result)` -- a Python repr, not JSON.
        Decode it so callers get real dicts/lists/numbers: JSON first (in case
        the in-editor code already serialised), then a safe literal parse, else
        the raw string.
        """
        import ast
        import json as _json

        res = self._run(expression, self._re.MODE_EVAL_STATEMENT, unattended)
        raw = res.get("result")
        if not isinstance(raw, str):
            return raw
        for parser in (_json.loads, ast.literal_eval):
            try:
                return parser(raw)
            except Exception:
                continue
        return raw

    def _run(self, command: str, mode: str, unattended: bool) -> dict[str, Any]:
        if not self._exec.has_command_connection():
            raise UnrealRemoteError("not connected; call connect() first")
        res = self._exec.run_command(command, unattended=unattended, exec_mode=mode,
                                     raise_on_failure=False)
        if not res.get("success", False):
            out = "\n".join(
                f"[{o.get('type')}] {o.get('output')}" for o in res.get("output", [])
            )
            raise UnrealRemoteError(f"editor reported failure for command:\n{out[:2000]}")
        return res

    def output_text(self, res: dict[str, Any]) -> str:
        return "\n".join(str(o.get("output", "")) for o in res.get("output", []))
