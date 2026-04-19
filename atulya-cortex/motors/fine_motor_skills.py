"""fine_motor_skills.py — the `Hand` motor (tool execution).

The `Hand` runs tools when the cortex emits an Action of kind `"tool_call"`.
Payload contract:

    intent.action.payload == {"name": <tool>, "arguments": {...}}

In v1 the toolset is small and side-effect-bounded:

- `bash`        — subprocess with timeout and forbidden-pattern check.
- `read_file`   — file read, sandboxed under `safe_root`.
- `write_file`  — file write, sandboxed under `safe_root`.
- `edit_file`   — atomic str-replace, sandboxed under `safe_root`.
- `web_fetch`   — httpx GET with timeout and size cap.

Adding a tool is one entry in `Hand._tools`. Tools that need broader access
(databases, MCP servers, etc.) belong in `motors/movement.py`, not here.

Naming voice: `Hand.prepare` / `act` / `recover`. The Hand is what touches
the world; everything else is talking about touching it.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from cortex.bus import ActionResult, Intent

Tool = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

_FORBIDDEN_BASH = (
    re.compile(r"\brm\s+-rf?\s+/(?:\s|$)"),
    re.compile(r":\(\)\s*\{.*?:\|:\&"),
    re.compile(r"\bmkfs(\.|\s)"),
    re.compile(r"\bdd\s+if=.+\s+of=/dev/(sd|nvme|hd)"),
)


class Hand:
    """Tool-execution motor with a sandboxed default toolset."""

    def __init__(
        self,
        *,
        safe_root: str | os.PathLike[str] | None = None,
        bash_timeout_s: float = 30.0,
        web_fetch_timeout_s: float = 30.0,
        web_fetch_max_bytes: int = 2_000_000,
    ) -> None:
        self._safe_root = Path(safe_root).resolve() if safe_root is not None else None
        self._bash_timeout_s = bash_timeout_s
        self._web_fetch_timeout_s = web_fetch_timeout_s
        self._web_fetch_max_bytes = web_fetch_max_bytes
        self._tools: dict[str, Tool] = {
            "bash": self._tool_bash,
            "read_file": self._tool_read_file,
            "write_file": self._tool_write_file,
            "edit_file": self._tool_edit_file,
            "web_fetch": self._tool_web_fetch,
        }

    def register(self, name: str, tool: Tool) -> None:
        self._tools[name] = tool

    def tool_names(self) -> list[str]:
        return sorted(self._tools.keys())

    async def prepare(self) -> None:
        return None

    async def recover(self) -> None:
        return None

    async def act(self, intent: Intent) -> ActionResult:
        started = time.monotonic()
        if intent.action.kind != "tool_call":
            return ActionResult(
                ok=False,
                detail=f"Hand motor cannot handle action.kind={intent.action.kind!r}",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        name = str(intent.action.payload.get("name", "")).strip()
        if not name:
            return ActionResult(
                ok=False,
                detail="tool_call payload missing 'name'",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        tool = self._tools.get(name)
        if tool is None:
            return ActionResult(
                ok=False,
                detail=f"unknown tool {name!r}; known={self.tool_names()}",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        args = dict(intent.action.payload.get("arguments") or {})
        try:
            output = await tool(args)
        except Exception as exc:
            return ActionResult(
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                artifact={"elapsed_ms": (time.monotonic() - started) * 1000.0},
            )
        return ActionResult(
            ok=True,
            artifact={
                "tool": name,
                "output": output,
                "elapsed_ms": (time.monotonic() - started) * 1000.0,
            },
        )

    def _resolve_safe(self, raw: str) -> Path:
        path = Path(raw).expanduser().resolve()
        if self._safe_root is not None:
            try:
                path.relative_to(self._safe_root)
            except ValueError as exc:
                raise PermissionError(f"path {path} escapes safe_root {self._safe_root}") from exc
        return path

    async def _tool_bash(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd = str(args.get("command", "")).strip()
        if not cmd:
            raise ValueError("bash: missing 'command'")
        for pattern in _FORBIDDEN_BASH:
            if pattern.search(cmd):
                raise PermissionError(f"bash: command blocked by guard: {pattern.pattern!r}")
        timeout = float(args.get("timeout_s") or self._bash_timeout_s)
        cwd = args.get("cwd")
        if cwd is not None:
            cwd = str(self._resolve_safe(str(cwd)))
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"bash: command exceeded {timeout}s")
        return {
            "exit_code": proc.returncode,
            "stdout": stdout_b.decode("utf-8", errors="replace"),
            "stderr": stderr_b.decode("utf-8", errors="replace"),
        }

    async def _tool_read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_safe(str(args["path"]))
        max_bytes = int(args.get("max_bytes", 1_000_000))

        def _read() -> str:
            with open(path, "rb") as fh:
                return fh.read(max_bytes).decode("utf-8", errors="replace")

        text = await asyncio.get_running_loop().run_in_executor(None, _read)
        return {"path": str(path), "text": text, "bytes": len(text.encode("utf-8"))}

    async def _tool_write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_safe(str(args["path"]))
        content = str(args.get("content", ""))

        def _write() -> int:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                return fh.write(content)

        n = await asyncio.get_running_loop().run_in_executor(None, _write)
        return {"path": str(path), "bytes_written": n}

    async def _tool_edit_file(self, args: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_safe(str(args["path"]))
        old = str(args.get("old", ""))
        new = str(args.get("new", ""))
        if old == "":
            raise ValueError("edit_file: 'old' must be non-empty")

        def _edit() -> dict[str, Any]:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            count = text.count(old)
            if count == 0:
                raise ValueError(f"edit_file: 'old' not found in {path}")
            if count > 1 and not args.get("replace_all"):
                raise ValueError(f"edit_file: 'old' matches {count} times; pass replace_all=true")
            text = text.replace(old, new) if args.get("replace_all") else text.replace(old, new, 1)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            return {
                "path": str(path),
                "replacements": count if args.get("replace_all") else 1,
            }

        return await asyncio.get_running_loop().run_in_executor(None, _edit)

    async def _tool_web_fetch(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx

        url = str(args["url"])
        timeout = float(args.get("timeout_s") or self._web_fetch_timeout_s)
        max_bytes = int(args.get("max_bytes") or self._web_fetch_max_bytes)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            body = resp.content[:max_bytes]
        return {
            "url": url,
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "text": body.decode("utf-8", errors="replace"),
            "bytes": len(body),
        }


__all__ = ["Hand", "Tool"]
