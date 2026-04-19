"""model — inspect and update the model provider section of the config."""

from __future__ import annotations

import argparse
import json
import sys

from cortex import config as config_module
from cortex.setup_wizard import ConsolePrompter, SetupWizard, detect_providers

NAME = "model"
HELP = "Inspect / change the LLM provider."


def register(subparsers, common_parents) -> None:
    parser = subparsers.add_parser(
        NAME,
        help=HELP,
        parents=list(common_parents),
        description="Show, list, and select the active LLM provider.",
    )
    sub = parser.add_subparsers(dest="model_command", metavar="<action>")

    p_show = sub.add_parser("show", help="Print the active provider/model/base URL.")
    p_show.add_argument("--json", action="store_true")
    p_show.set_defaults(_model_run=_run_show)

    p_list = sub.add_parser("list", help="Probe the local environment for reachable providers.")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(_model_run=_run_list)

    p_select = sub.add_parser("select", help="Run the model section of the wizard interactively.")
    p_select.add_argument(
        "--non-interactive",
        action="store_true",
        help="Refuse to prompt; useful for CI smoke tests.",
    )
    p_select.set_defaults(_model_run=_run_select)

    parser.set_defaults(_run=run)


def run(args: argparse.Namespace, *, home) -> int:
    handler = getattr(args, "_model_run", None)
    if handler is None:
        return _run_show(args, home=home)
    return handler(args, home=home)


def _load(home):
    try:
        return config_module.load(home)
    except config_module.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None


def _run_show(args: argparse.Namespace, *, home) -> int:
    cfg = _load(home)
    if cfg is None:
        return 2
    payload = {
        "provider": cfg.model.provider,
        "model": cfg.model.model,
        "base_url": cfg.model.base_url,
        "api_key_env": cfg.model.api_key_env,
        "temperature": cfg.model.temperature,
        "max_tokens": cfg.model.max_tokens,
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
    else:
        for k, v in payload.items():
            print(f"{k:>14} = {v}")
    return 0


def _run_list(args: argparse.Namespace, *, home) -> int:
    probe = detect_providers()
    payload = {
        "lm_studio": probe.lm_studio,
        "ollama": probe.ollama,
        "openai_key_present": probe.openai_key,
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return 0
    for name, ok in payload.items():
        status = "REACHABLE" if ok else "not reachable"
        print(f"  {name:<20} {status}")
    return 0


def _run_select(args: argparse.Namespace, *, home) -> int:
    prompter = ConsolePrompter(interactive=not args.non_interactive)
    wizard = SetupWizard(home, prompter)
    result = wizard.run_model()
    print(f"[{'ok' if result.ok else 'ERROR'}] {result.name}")
    for note in result.notes:
        print(f"    . {note}")
    for path in result.changed:
        print(f"    + {path}")
    for env in result.secrets_recorded:
        print(f"    $ wrote secret to .env: {env}")
    for err in result.errors:
        print(f"    ! {err}")
    return 0 if result.ok else 1


__all__ = ["NAME", "HELP", "register", "run"]
