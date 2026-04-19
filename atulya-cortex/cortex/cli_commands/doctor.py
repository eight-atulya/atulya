"""doctor — run health checks against the cortex install."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from cortex import config as config_module
from cortex.diagnostics import aggregate_status, run_checks

NAME = "doctor"
HELP = "Run diagnostic checks against the cortex install."


def register(subparsers, common_parents) -> None:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=list(common_parents),
        description="Probe Python version, config, persona, skills, channels, and provider reachability.",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply auto-fixes for warnings that have a fix callable (idempotent).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.set_defaults(_run=run)


def run(args: argparse.Namespace, *, home) -> int:
    try:
        config = config_module.load(home)
    except config_module.ConfigError as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(f"error: {exc}\nrun `atulya-cortex setup` to seed a fresh config.", file=sys.stderr)
        return 2

    results = asyncio.run(run_checks(home, config, apply_fixes=args.fix))
    status = aggregate_status(results)

    if args.json:
        print(
            json.dumps(
                {
                    "status": status,
                    "results": [r.to_dict() for r in results],
                },
                indent=2,
            )
        )
    else:
        for r in results:
            note = " (fixed)" if r.fixed else ""
            print(f"[{r.emoji}] {r.name}{note}: {r.message}")
        print(f"overall: {status}")

    return 0 if status in ("ok", "warn", "skip") else 1


__all__ = ["NAME", "HELP", "register", "run"]
