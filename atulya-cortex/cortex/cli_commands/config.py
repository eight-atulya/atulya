"""config — show, get, set, edit, validate the cortex config."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Any

import tomli_w

from cortex import config as config_module

NAME = "config"
HELP = "Inspect and modify config.toml safely."


def register(subparsers, common_parents) -> None:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=list(common_parents),
        description="Show, get, set, edit, validate, and migrate the cortex config.",
    )
    sub = parser.add_subparsers(dest="config_command", metavar="<action>")

    p_show = sub.add_parser("show", help="Print the merged effective config (TOML).")
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(_config_run=_run_show)

    p_path = sub.add_parser("path", help="Print the path to the active config.toml.")
    p_path.set_defaults(_config_run=_run_path)

    p_get = sub.add_parser("get", help="Get a value by dotted path, e.g. model.provider.")
    p_get.add_argument("key", help="Dotted path into the config (e.g. model.temperature).")
    p_get.set_defaults(_config_run=_run_get)

    p_set = sub.add_parser("set", help="Set a value by dotted path; validates before writing.")
    p_set.add_argument("key", help="Dotted path.")
    p_set.add_argument("value", help="New value (parsed as TOML scalar; quote strings as needed).")
    p_set.set_defaults(_config_run=_run_set)

    p_check = sub.add_parser("check", help="Validate config.toml against the schema. Exit nonzero on failure.")
    p_check.set_defaults(_config_run=_run_check)

    p_edit = sub.add_parser("edit", help="Open config.toml in $EDITOR; re-validate before saving.")
    p_edit.set_defaults(_config_run=_run_edit)

    p_migrate = sub.add_parser(
        "migrate",
        help="Re-write config.toml so every key from the bundled template is present.",
    )
    p_migrate.set_defaults(_config_run=_run_migrate)

    parser.set_defaults(_run=run)


def run(args: argparse.Namespace, *, home) -> int:
    handler = getattr(args, "_config_run", None)
    if handler is None:
        return _run_show(args, home=home)
    return handler(args, home=home)


def _run_show(args: argparse.Namespace, *, home) -> int:
    try:
        cfg = config_module.load(home)
    except config_module.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if getattr(args, "json", False):
        print(json.dumps(cfg.model_dump(mode="python"), indent=2, default=str))
    else:
        sys.stdout.write(tomli_w.dumps(cfg.model_dump(mode="python")))
    return 0


def _run_path(args: argparse.Namespace, *, home) -> int:
    print(home.config_file)
    return 0


def _run_get(args: argparse.Namespace, *, home) -> int:
    try:
        raw = config_module.load_raw(home)
    except config_module.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    value = _walk(raw, args.key)
    if value is _MISSING:
        print(f"error: no such key {args.key!r}", file=sys.stderr)
        return 1
    if isinstance(value, (dict, list)):
        print(json.dumps(value, indent=2))
    else:
        print(value)
    return 0


def _run_set(args: argparse.Namespace, *, home) -> int:
    try:
        raw = config_module.load_raw(home)
    except config_module.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parsed = _parse_scalar(args.value)
    parts = args.key.split(".")
    cursor: dict[str, Any] = raw
    for part in parts[:-1]:
        if part not in cursor or not isinstance(cursor[part], dict):
            print(f"error: cannot set {args.key!r}; {part!r} is not a section", file=sys.stderr)
            return 1
        cursor = cursor[part]
    cursor[parts[-1]] = parsed
    try:
        config_module.write_raw(home, raw)
    except Exception as exc:
        print(f"error: validation failed, config NOT saved: {exc}", file=sys.stderr)
        return 1
    print(f"set {args.key} = {parsed!r}")
    return 0


def _run_check(args: argparse.Namespace, *, home) -> int:
    try:
        config_module.load(home)
    except config_module.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"ok: {home.config_file}")
    return 0


def _run_edit(args: argparse.Namespace, *, home) -> int:
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        for candidate in ("nano", "vim", "vi"):
            if shutil.which(candidate):
                editor = candidate
                break
    if not editor:
        print("error: no $EDITOR set and no nano/vim/vi on PATH", file=sys.stderr)
        return 2
    if not home.config_file.exists():
        config_module.seed(home)
    backup = home.config_file.read_text(encoding="utf-8")
    fd, tmp = tempfile.mkstemp(prefix="cortex-config-", suffix=".toml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(backup)
        subprocess.run([editor, tmp], check=True)
        edited = open(tmp, encoding="utf-8").read()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if edited == backup:
        print("no changes")
        return 0
    try:
        new_raw = tomllib.loads(edited)
        config_module.write_raw(home, new_raw)
    except Exception as exc:
        print(f"error: edit rejected, config unchanged: {exc}", file=sys.stderr)
        return 1
    print(f"saved {home.config_file}")
    return 0


def _run_migrate(args: argparse.Namespace, *, home) -> int:
    # Loading already deep-merges template defaults; saving back persists them.
    try:
        cfg = config_module.load(home)
    except config_module.ConfigError as exc:
        print(f"error: cannot migrate; current config invalid: {exc}", file=sys.stderr)
        return 1
    config_module.save(home, cfg)
    print(f"migrated {home.config_file} (every template key now present)")
    return 0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


_MISSING = object()


def _walk(data: Any, dotted: str) -> Any:
    cursor: Any = data
    for part in dotted.split("."):
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        else:
            return _MISSING
    return cursor


def _parse_scalar(text: str) -> Any:
    """Parse a CLI-supplied value into a TOML-friendly scalar.

    We piggy-back on the TOML parser so the user can write `true`, `42`,
    `1.5`, `"a string"`, or `[1, 2, 3]` and get the natural type. Bare
    strings (no quotes, not a number/bool) come through as `str`.
    """

    text = text.strip()
    try:
        return tomllib.loads(f"v = {text}")["v"]
    except tomllib.TOMLDecodeError:
        return text


__all__ = ["NAME", "HELP", "register", "run"]
