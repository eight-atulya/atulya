"""cli.py — `atulya-cortex` and `python -m cortex` entry point.

This file is intentionally thin. All real work is in `cli_commands/<name>.py`.
The dispatcher does five things and nothing else:

1. Build a root parser with global flags (`--home`, `--profile`, `--log-level`, `--version`).
2. Auto-discover every command module in `cli_commands/` and let each
   `register()` itself onto the shared subparsers.
3. Resolve `CortexHome`, bootstrap directories, load `~/.atulya/cortex/.env`.
4. Configure logging (level from `--log-level` or env var, never spam stdout).
5. Dispatch to the chosen subcommand and return its exit code.

If no subcommand is given, we run `chat` for backwards-compat with the
previous CLI shape.

Production niceties:
- `KeyboardInterrupt` always returns exit code 130 (UNIX convention).
- Uncaught exceptions are surfaced as `error: <msg>` on stderr; full
  tracebacks only show with `--log-level DEBUG` or `ATULYA_CORTEX_TRACE=1`.
- Optional dependency import failures inside a command module are
  surfaced as warnings and *not* allowed to break the rest of the CLI.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Sequence

from cortex.cli_commands import discover, register_all
from cortex.env_loader import load_env_file
from cortex.home import ENV_HOME, ENV_PROFILE, CortexHome

DEFAULT_SUBCOMMAND = "chat"
TRACE_ENV = "ATULYA_CORTEX_TRACE"
LOG_LEVEL_ENV = "ATULYA_CORTEX_LOG_LEVEL"

_LOG_LEVELS: tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _package_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("atulya-cortex")
    except (PackageNotFoundError, Exception):  # pragma: no cover - editable installs
        return "0.1.0"


def _build_common_parents() -> list[argparse.ArgumentParser]:
    """Args shared across every subcommand. Used as `parents=` so help
    output stays consistent."""

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--home",
        default=None,
        metavar="PATH",
        help=f"Override cortex home dir. Default: ${ENV_HOME} or ~/.atulya/cortex/.",
    )
    common.add_argument(
        "--profile",
        default=None,
        metavar="NAME",
        help=f"Override active profile. Default: ${ENV_PROFILE} or `current_profile` file or `default`.",
    )
    common.add_argument(
        "--log-level",
        default=None,
        choices=list(_LOG_LEVELS),
        help=f"Logging verbosity. Default: ${LOG_LEVEL_ENV} or INFO.",
    )
    common.add_argument(
        "--no-env-file",
        action="store_true",
        help="Skip loading <home>/.env (used by tests).",
    )
    return [common]


def _build_parser() -> argparse.ArgumentParser:
    common_parents = _build_common_parents()
    # The same parent is attached to BOTH the root parser and each
    # subparser so users can write `cortex --home X setup` *or*
    # `cortex setup --home X` and get the same result.
    parser = argparse.ArgumentParser(
        prog="atulya-cortex",
        description="Atulya Cortex — biomimetic AI brain. Run with no subcommand to start a TUI chat.",
        parents=common_parents,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"atulya-cortex {_package_version()}",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    register_all(subparsers, common_parents, discover())
    return parser


def _resolve_log_level(args: argparse.Namespace) -> str:
    if getattr(args, "log_level", None):
        return args.log_level
    env_value = os.environ.get(LOG_LEVEL_ENV, "").upper()
    if env_value in _LOG_LEVELS:
        return env_value
    return "INFO"


def _setup_logging(level: str) -> None:
    # logging.basicConfig is idempotent across a single process; calling it
    # again on the same root logger is a no-op unless `force=True`.
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        stream=sys.stderr,
        force=True,
    )


def _trace_enabled() -> bool:
    return os.environ.get(TRACE_ENV, "").lower() in ("1", "true", "yes", "on")


def main(argv: Sequence[str] | None = None) -> int:
    """Library-friendly entry point. Returns the exit code instead of
    calling `sys.exit` so subprocess tests / library callers can drive it."""

    raw = list(argv) if argv is not None else sys.argv[1:]

    # If the first positional token is not a known flag and not a
    # registered subcommand, we DO NOT silently swap it for `chat`; we let
    # argparse surface a clear "invalid choice" error. But if the user gave
    # zero positional args we default to `chat` for parity with the old CLI.
    if not raw or all(token.startswith("-") for token in raw):
        # Inject the default subcommand AFTER any leading flags. argparse
        # will then treat the rest as args for `chat`.
        first_positional = next((i for i, t in enumerate(raw) if not t.startswith("-")), len(raw))
        raw = raw[:first_positional] + [DEFAULT_SUBCOMMAND] + raw[first_positional:]

    parser = _build_parser()
    args = parser.parse_args(raw)

    level = _resolve_log_level(args)
    _setup_logging(level)
    logger = logging.getLogger("cortex.cli")

    try:
        home = CortexHome.resolve(root=args.home, profile=args.profile).bootstrap()
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2

    if not getattr(args, "no_env_file", False):
        try:
            loaded = load_env_file(home.env_file)
            if loaded:
                logger.debug("loaded %d env keys from %s", len(loaded), home.env_file)
        except Exception as exc:  # defensive: env_loader is meant to never raise
            logger.warning("env_loader: unexpected failure (%s); continuing without .env", exc)

    handler = getattr(args, "_run", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return 2

    try:
        return int(handler(args, home=home) or 0)
    except KeyboardInterrupt:
        return 130
    except SystemExit:
        raise
    except Exception as exc:
        if _trace_enabled() or level == "DEBUG":
            logger.exception("subcommand %r crashed", args.command)
        else:
            sys.stderr.write(f"error: {exc}\n")
        return 1


def main_console() -> None:
    """Console-script entry point: translate the int return to `sys.exit`."""

    sys.exit(main())


if __name__ == "__main__":
    main_console()
