"""setup — sectioned onboarding wizard.

`atulya-cortex setup`             runs every section in order
`atulya-cortex setup model`       runs only the model section
`atulya-cortex setup persona`     runs only the persona section
... etc

The wizard logic lives in `cortex.setup_wizard.SetupWizard`; this module is
just the CLI surface.
"""

from __future__ import annotations

import argparse
import json
import sys

from cortex.setup_wizard import SECTION_ORDER, ConsolePrompter, SectionResult, SetupWizard

NAME = "setup"
HELP = "Run the onboarding wizard (use a section name to run just one)."


def register(subparsers, common_parents) -> None:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=list(common_parents),
        description="Configure model provider, persona, channels, and skills.",
    )
    parser.add_argument(
        "section",
        nargs="?",
        choices=list(SECTION_ORDER) + ["all"],
        default="all",
        help="Run just one section. Default: all sections in order.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Refuse to prompt; useful for `install.sh --no-interactive` smoke tests.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON summary in addition to the text output.",
    )
    parser.set_defaults(_run=run)


def run(args: argparse.Namespace, *, home) -> int:
    prompter = ConsolePrompter(interactive=not args.non_interactive)
    wizard = SetupWizard(home, prompter)
    if args.section == "all":
        results = wizard.run_all()
    else:
        handler = getattr(wizard, f"run_{args.section}", None)
        if handler is None:
            print(f"error: unknown section {args.section!r}", file=sys.stderr)
            return 2
        results = [handler()]

    _render_text_summary(results)
    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))

    failures = [r for r in results if not r.ok]
    return 1 if failures else 0


def _render_text_summary(results: list[SectionResult]) -> None:
    print()
    print("=" * 60)
    print("setup summary")
    print("=" * 60)
    for r in results:
        status = "ok" if r.ok else "ERROR"
        print(f"[{status}] {r.name}")
        for path in r.changed:
            print(f"    + {path}")
        for path in r.skipped:
            print(f"    = {path}  (unchanged)")
        for note in r.notes:
            print(f"    . {note}")
        for env in r.secrets_recorded:
            print(f"    $ wrote secret to .env: {env}")
        for err in r.errors:
            print(f"    ! {err}")
    print("=" * 60)
    failed = [r.name for r in results if not r.ok]
    if failed:
        print(f"sections with errors: {', '.join(failed)}")
    else:
        print("all sections ok. next:  atulya-cortex chat")
    print()


__all__ = ["NAME", "HELP", "register", "run"]
