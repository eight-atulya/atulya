"""skills — manage the bundled and user-authored markdown skills."""

from __future__ import annotations

import argparse

from cortex.skills_sync import bundled_skills_dir
from cortex.skills_sync import sync as sync_skills

NAME = "skills"
HELP = "Sync bundled skills, list installed skills."


def register(subparsers, common_parents) -> None:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=list(common_parents),
        description="Operate on the markdown skills directory.",
    )
    sub = parser.add_subparsers(dest="skills_command", metavar="<action>")

    sync_p = sub.add_parser("sync", help="Copy bundled skills into the home skills dir.")
    sync_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite user-edited skills with the bundled version.",
    )
    sync_p.set_defaults(_skills_run=_run_sync)

    list_p = sub.add_parser("list", help="List installed and bundled skills.")
    list_p.set_defaults(_skills_run=_run_list)

    parser.set_defaults(_run=run)


def run(args: argparse.Namespace, *, home) -> int:
    handler = getattr(args, "_skills_run", None)
    if handler is None:
        return _run_list(args, home=home)
    return handler(args, home=home)


def _run_sync(args: argparse.Namespace, *, home) -> int:
    result = sync_skills(home, force=args.force)
    print(f"copied:    {len(result.copied)}")
    for n in result.copied:
        print(f"    + {n}")
    print(f"skipped:   {len(result.skipped)}")
    for n in result.skipped:
        print(f"    = {n}")
    print(f"preserved: {len(result.preserved)}")
    for n in result.preserved:
        print(f"    ~ {n}  (user-edited; pass --force to overwrite)")
    if result.errors:
        print(f"errors:    {len(result.errors)}")
        for e in result.errors:
            print(f"    ! {e}")
        return 1
    return 0


def _run_list(args: argparse.Namespace, *, home) -> int:
    bundled = sorted(p.name for p in bundled_skills_dir().glob("*.md"))
    installed = sorted(p.name for p in home.skills_dir.glob("*.md")) if home.skills_dir.exists() else []
    print(f"bundled skills ({len(bundled)}):")
    for name in bundled:
        print(f"    - {name}")
    print(f"installed at {home.skills_dir} ({len(installed)}):")
    for name in installed:
        marker = "*" if name in bundled else " "
        print(f"  {marker} {name}")
    return 0


__all__ = ["NAME", "HELP", "register", "run"]
