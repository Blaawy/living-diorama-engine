"""Minimal MCP client for the Unreal Editor's built-in MCP server.

The Director's target UX is "Claude is the factory commander". Claude Code can
attach to the editor directly via `.mcp.json`, but the *factory* also needs to
drive the editor from plain Python (batch jobs, tests, CI, DeepSeek workers).
This module is that path.

Transport: HTTP POST to http://127.0.0.1:8000/mcp, loopback only, no auth --
the server rejects non-loopback origins. Responses may arrive as JSON or as an
SSE (`text/event-stream`) frame; both are handled here.

Nothing in this module may write simulation truth. It drives presentation only.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8000/mcp"
PROTOCOL_VERSION = "2025-06-18"


class UnrealMCPError(RuntimeError):
    pass


def _parse_body(body: str) -> dict[str, Any]:
    """Accept either a bare JSON body or an SSE frame carrying one."""
    text = body.strip()
    if not text:
        raise UnrealMCPError("empty response body")
    if text.startswith("{"):
        return json.loads(text)
    # SSE: lines of "event: ..." / "data: {...}"
    chunks = [
        line[len("data:") :].strip()
        for line in text.splitlines()
        if line.startswith("data:")
    ]
    if not chunks:
        raise UnrealMCPError(f"unrecognised response body: {text[:200]!r}")
    return json.loads("".join(chunks))


class UnrealMCP:
    """A single MCP session against a running Unreal Editor."""

    def __init__(self, url: str = DEFAULT_URL, timeout: float = 120.0) -> None:
        self.url = url
        self.timeout = timeout
        self.session_id: str | None = None
        self._next_id = 0
        self.server_info: dict[str, Any] = {}

    # --- transport --------------------------------------------------------

    def _post(self, payload: dict[str, Any]) -> tuple[int, dict[str, str], str]:
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode(
                    "utf-8", "replace"
                )
        except urllib.error.HTTPError as e:  # surface the server's own message
            raise UnrealMCPError(
                f"HTTP {e.code} from {self.url}: {e.read().decode('utf-8', 'replace')[:400]}"
            ) from e
        except urllib.error.URLError as e:
            raise UnrealMCPError(
                f"cannot reach Unreal MCP at {self.url}: {e.reason}. "
                "Is the editor running with -ModelContextProtocolStartServer?"
            ) from e

    def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._next_id += 1
        status, headers, body = self._post(
            {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}}
        )
        if status != 200:
            raise UnrealMCPError(f"{method}: HTTP {status}")
        sid = headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        doc = _parse_body(body)
        if "error" in doc:
            raise UnrealMCPError(f"{method}: {doc['error']}")
        return doc.get("result")

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})

    # --- protocol ---------------------------------------------------------

    def connect(self, client_name: str = "living-diorama-yf") -> dict[str, Any]:
        result = self._call(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": client_name, "version": "1.0"},
            },
        )
        self.server_info = result or {}
        self._notify("notifications/initialized")
        return self.server_info

    def list_tools(self) -> list[dict[str, Any]]:
        return (self._call("tools/list") or {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._call("tools/call", {"name": name, "arguments": arguments or {}})

    # --- convenience ------------------------------------------------------

    def text_of(self, result: dict[str, Any]) -> str:
        """Flatten a tool result's content blocks into plain text."""
        parts = []
        for block in (result or {}).get("content", []):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)

    def __enter__(self) -> UnrealMCP:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        return None
