"""pairing — list, approve, reject, revoke channel pairings.

Backed by `brainstem.reflexes.DMPairing` rooted at `home.pairing_store` so
all front-ends (CLI, dashboard, future API) share the same source of truth.
"""

from __future__ import annotations

import argparse
import json

from brainstem.reflexes import DMPairing

NAME = "pairing"
HELP = "Manage channel pairings (list / approve / reject / revoke)."


def register(subparsers, common_parents) -> None:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=list(common_parents),
        description="Inspect and modify the DMPairing store.",
    )
    sub = parser.add_subparsers(dest="pairing_command", metavar="<action>")

    p_list = sub.add_parser("list", help="List all pairings (status + paired_at).")
    p_list.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    p_list.set_defaults(_pairing_run=_run_list)

    p_pending = sub.add_parser("pending", help="List channels awaiting approval.")
    p_pending.add_argument("--json", action="store_true", help="Emit JSON.")
    p_pending.set_defaults(_pairing_run=_run_pending)

    p_approve = sub.add_parser("approve", help="Approve a channel.")
    p_approve.add_argument("channel", help="Channel id, e.g. telegram:123456")
    p_approve.set_defaults(_pairing_run=_run_approve)

    p_reject = sub.add_parser("reject", help="Reject a channel.")
    p_reject.add_argument("channel", help="Channel id.")
    p_reject.set_defaults(_pairing_run=_run_reject)

    p_revoke = sub.add_parser("revoke", help="Forget a pairing entirely (channel becomes new on next stimulus).")
    p_revoke.add_argument("channel", help="Channel id.")
    p_revoke.set_defaults(_pairing_run=_run_revoke)

    parser.set_defaults(_run=run)


def run(args: argparse.Namespace, *, home) -> int:
    handler = getattr(args, "_pairing_run", None)
    if handler is None:
        return _run_list(args, home=home)
    return handler(args, home=home)


def _store(home) -> DMPairing:
    return DMPairing(home.pairing_store)


def _run_list(args: argparse.Namespace, *, home) -> int:
    entries = _store(home).list()
    if getattr(args, "json", False):
        print(json.dumps(entries, indent=2))
        return 0
    if not entries:
        print("(no pairings)")
        return 0
    print(f"{'channel':<32} {'status':<10} paired_at")
    print("-" * 70)
    for e in entries:
        print(f"{e['channel']:<32} {e.get('status', '?'):<10} {e.get('paired_at', '')}")
    return 0


def _run_pending(args: argparse.Namespace, *, home) -> int:
    pending = _store(home).pending()
    if getattr(args, "json", False):
        print(json.dumps(pending, indent=2))
        return 0
    if not pending:
        print("(none pending)")
        return 0
    for c in pending:
        print(c)
    return 0


def _run_approve(args: argparse.Namespace, *, home) -> int:
    _store(home).approve(args.channel)
    print(f"approved {args.channel}")
    return 0


def _run_reject(args: argparse.Namespace, *, home) -> int:
    _store(home).reject(args.channel)
    print(f"rejected {args.channel}")
    return 0


def _run_revoke(args: argparse.Namespace, *, home) -> int:
    _store(home).revoke(args.channel)
    print(f"revoked {args.channel}")
    return 0


__all__ = ["NAME", "HELP", "register", "run"]
