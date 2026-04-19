"""env_loader.py — load `~/.atulya/cortex/.env` paranoidly.

Why a custom loader on top of `python-dotenv`?

1. **Sanitise values.** Tokens copy-pasted from a browser pick up trailing
   CRLF, BOM bytes, and zero-width spaces; these later poison HTTP headers
   ("Invalid header value") with errors that look unrelated. We strip them
   eagerly so a token that *looks* like a token *is* a token.
2. **Never log secrets.** This module logs *which keys* were loaded but
   never the values, and refuses to format values into exception messages.
3. **Don't clobber env.** By default we only set keys that are not already
   in `os.environ`; pass `override=True` to force.
4. **Predictable failure.** Returns the set of keys actually written; never
   raises on missing files.

Naming voice: `load_env_file(path)` and `loaded_keys` are deliberately dull.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

# Bytes routinely smuggled into copy-pasted secrets that we strip before
# anything else looks at the value. Order matters; BOM must come first.
_STRIP_PREFIXES: tuple[str, ...] = ("\ufeff",)
# Characters we drop wherever they appear in the value.
_FORBIDDEN_CHARS: frozenset[str] = frozenset(
    (
        "\u200b",  # zero-width space
        "\u200c",  # zero-width non-joiner
        "\u200d",  # zero-width joiner
        "\u2028",  # line separator
        "\u2029",  # paragraph separator
        "\r",  # carriage return; CRLF -> LF handled below
    )
)


def sanitize_value(raw: str) -> str:
    """Strip BOM/zero-width/CR characters, surrounding whitespace, and matching
    surrounding quotes from a `.env` value.

    Idempotent. Always returns a `str`; never raises.
    """

    if raw is None:  # type: ignore[unreachable]
        return ""
    value = str(raw)
    for prefix in _STRIP_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix) :]
    value = "".join(ch for ch in value if ch not in _FORBIDDEN_CHARS)
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value


def _parse_env_text(text: str) -> dict[str, str]:
    """Tiny, dependency-free `.env` parser. Honors `KEY=VALUE`, comments
    starting with `#`, and blank lines. Values are sanitised."""

    out: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.lstrip("\ufeff").strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        out[key] = sanitize_value(value)
    return out


def load_env_file(
    path: str | os.PathLike[str],
    *,
    override: bool = False,
    skip_keys: Iterable[str] = (),
) -> list[str]:
    """Load env vars from `path` into `os.environ`.

    Returns the sorted list of keys actually written (useful for the doctor
    command). Missing or unreadable files are a no-op (returns `[]`); the
    function never raises on filesystem trouble.

    `override=True` overwrites pre-existing env vars; otherwise existing
    values win (so `export TOKEN=...; cortex setup` keeps the shell value).

    `skip_keys` is a guardrail: keys in this set are never loaded even if
    present in the file (used by tests).
    """

    path_obj = Path(os.fspath(path))
    if not path_obj.exists():
        logger.debug("env_loader: %s does not exist; skipping", path_obj)
        return []
    try:
        text = path_obj.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("env_loader: failed to read %s: %s", path_obj, exc)
        return []

    parsed = _parse_env_text(text)
    skip = set(skip_keys)
    written: list[str] = []
    for key, value in parsed.items():
        if key in skip:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        written.append(key)

    if written:
        logger.debug(
            "env_loader: loaded %d keys from %s (override=%s)",
            len(written),
            path_obj,
            override,
        )
    return sorted(written)


def write_env_file(
    path: str | os.PathLike[str],
    values: dict[str, str],
    *,
    header: str = "# Atulya Cortex secrets — do not commit\n",
) -> None:
    """Write a `.env` file atomically.

    Values are sanitised on the way out. Quoting is applied if the value
    contains whitespace or `#` so the next loader still gets the right thing.
    """

    target = Path(os.fspath(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [header.rstrip("\n") + "\n"]
    for key in sorted(values):
        value = sanitize_value(values[key])
        if any(ch in value for ch in (" ", "\t", "#")):
            value = f'"{value}"'
        lines.append(f"{key}={value}\n")
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text("".join(lines), encoding="utf-8")
    os.replace(tmp, target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        # Best-effort; chmod can fail on some filesystems (e.g. certain mounts
        # in Docker on Windows). The atomic write itself is the load-bearing bit.
        pass


__all__ = ["load_env_file", "sanitize_value", "write_env_file"]
