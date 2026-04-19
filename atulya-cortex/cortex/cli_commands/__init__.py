"""cli_commands — one subcommand per file.

Each module in this package must define:

- `NAME`     : str — the subcommand name (`atulya-cortex <NAME>`).
- `HELP`     : str — one-line help shown by `atulya-cortex --help`.
- `register(subparsers, common_parents)` — wire the subparser, set
  `_run=<callable>` on it. The callable receives `(args, *, home)` and
  returns an exit code (`int`).

Discovery is lazy and import-driven: `discover()` walks this package and
imports every submodule that does not start with `_`. Modules that fail to
import (because their optional dependency is missing — e.g. dashboard
without `fastapi`) are reported as warnings but never block the CLI.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType
from typing import Iterable

logger = logging.getLogger(__name__)


def discover(package: str = __name__) -> list[ModuleType]:
    """Import every command module under `package`. Returns the imported
    modules in deterministic order (alphabetical by module name).

    Modules that raise on import are logged at WARNING level and skipped.
    """

    pkg = importlib.import_module(package)
    modules: list[ModuleType] = []
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        full_name = f"{package}.{info.name}"
        try:
            module = importlib.import_module(full_name)
        except Exception as exc:  # pragma: no cover - depends on optional deps
            logger.warning("cli_commands: failed to import %s: %s", full_name, exc)
            continue
        if not all(hasattr(module, attr) for attr in ("NAME", "HELP", "register")):
            logger.debug("cli_commands: %s missing NAME/HELP/register; skipping", full_name)
            continue
        modules.append(module)
    return modules


def register_all(subparsers, common_parents: Iterable, modules: Iterable[ModuleType]) -> None:
    """Call `register(subparsers, common_parents)` on each discovered module."""

    parents = list(common_parents)
    for module in modules:
        module.register(subparsers, parents)


__all__ = ["discover", "register_all"]
