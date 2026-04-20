"""store.py — round-trip compiled Programs through a single JSON file.

A compiled artifact is:

    {
      "version": 1,
      "signature": {...},
      "instructions": "...",
      "demos": [...],
      "temperature": 0.2,
      "max_tokens": 512,
      "meta": {"compiled_at": "ISO-8601", ...}
    }

The format is intentionally the same shape `Program.to_dict()` produces so
that `load_compiled(path)` is just `Program.from_dict(json.load(...))`
with a thin version check and optional meta sidechannel.

Artifacts live under `<cortex_home>/plasticity/` by default; callers pass
a path so this module has no home-dir coupling.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plasticity.program import Program

VERSION = 1


@dataclass
class Artifact:
    program: Program
    meta: dict[str, Any] = field(default_factory=dict)


def save_compiled(
    path: str | Path,
    program: Program,
    *,
    meta: dict[str, Any] | None = None,
) -> Path:
    """Write the program to `path`. Creates parent dirs. Returns the path."""

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "version": VERSION,
        **program.to_dict(),
        "meta": {
            "compiled_at": datetime.now(timezone.utc).isoformat(),
            **dict(meta or {}),
        },
    }
    dest.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return dest


def load_compiled(path: str | Path) -> Artifact:
    """Load the JSON at `path` and return an `Artifact`."""

    src = Path(path)
    data = json.loads(src.read_text(encoding="utf-8"))
    version = int(data.get("version", 0))
    if version != VERSION:
        raise ValueError(f"unknown plasticity artifact version {version!r}; expected {VERSION}")
    meta = dict(data.pop("meta", {}) or {})
    data.pop("version", None)
    program = Program.from_dict(data)
    return Artifact(program=program, meta=meta)


__all__ = ["Artifact", "VERSION", "load_compiled", "save_compiled"]
