"""profile — manage named cortex profiles (overlays)."""

from __future__ import annotations

import argparse
import json

from cortex.profile import Profile

NAME = "profile"
HELP = "List, create, switch, and delete profiles."


def register(subparsers, common_parents) -> None:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=list(common_parents),
        description="Manage profile overlays under <home>/profiles/.",
    )
    sub = parser.add_subparsers(dest="profile_command", metavar="<action>")

    p_list = sub.add_parser("list", help="List profiles; the active one is marked.")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(_profile_run=_run_list)

    p_show = sub.add_parser("show", help="Print the active profile name.")
    p_show.set_defaults(_profile_run=_run_show)

    p_create = sub.add_parser("create", help="Create a new profile overlay.")
    p_create.add_argument("name")
    p_create.set_defaults(_profile_run=_run_create)

    p_switch = sub.add_parser("switch", help="Persist a profile as active.")
    p_switch.add_argument("name")
    p_switch.set_defaults(_profile_run=_run_switch)

    p_delete = sub.add_parser("delete", help="Remove a profile overlay.")
    p_delete.add_argument("name")
    p_delete.add_argument("--force", action="store_true", help="Delete even if currently active.")
    p_delete.set_defaults(_profile_run=_run_delete)

    parser.set_defaults(_run=run)


def run(args: argparse.Namespace, *, home) -> int:
    handler = getattr(args, "_profile_run", None)
    if handler is None:
        return _run_list(args, home=home)
    return handler(args, home=home)


def _run_list(args: argparse.Namespace, *, home) -> int:
    profiles = Profile.list(home)
    rows = [{"name": p.name, "active": p.name == home.profile_name} for p in profiles]
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2))
        return 0
    for row in rows:
        marker = "*" if row["active"] else " "
        print(f"{marker} {row['name']}")
    return 0


def _run_show(args: argparse.Namespace, *, home) -> int:
    print(home.profile_name)
    return 0


def _run_create(args: argparse.Namespace, *, home) -> int:
    try:
        Profile.create(home, args.name)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    print(f"created profile {args.name!r} at {home.profiles_root / args.name}")
    return 0


def _run_switch(args: argparse.Namespace, *, home) -> int:
    try:
        Profile.switch(home, args.name)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    print(f"switched active profile to {args.name!r}; new commands will use it")
    return 0


def _run_delete(args: argparse.Namespace, *, home) -> int:
    try:
        Profile.delete(home, args.name, allow_active=args.force)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    print(f"deleted profile {args.name!r}")
    return 0


__all__ = ["NAME", "HELP", "register", "run"]
