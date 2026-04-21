from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Protocol

from rich.panel import Panel


class CommandHost(Protocol):
    async def append_system(self, text: str) -> None: ...
    async def append_rich(self, renderable) -> None: ...
    async def request_exit(self) -> None: ...

    @property
    def ctx(self): ...


@dataclass
class CommandResult:
    ok: bool = True


async def cmd_help(host: CommandHost, arg: str = "") -> CommandResult:
    lines = [
        "/help /model /clear /skills /pairing /persona /profile /doctor",
        "/history /forget /tools /facts /episodes /sleep [/force] /affect <text>",
        "/system /quit /exit",
    ]
    await host.append_system("\n".join(lines))
    return CommandResult()


async def cmd_model(host: CommandHost, arg: str = "") -> CommandResult:
    await host.append_system(
        f"model provider={host.ctx.provider} id={host.ctx.model} base_url={host.ctx.base_url}"
    )
    return CommandResult()


async def cmd_clear(host: CommandHost, arg: str = "") -> CommandResult:
    await host.append_system("(clear requested)")
    return CommandResult()


async def cmd_skills(host: CommandHost, arg: str = "") -> CommandResult:
    skills_dir: Path = host.ctx.skills_dir
    if not skills_dir.exists():
        await host.append_system("no skills directory yet.")
        return CommandResult(ok=False)
    skills = sorted(p.stem for p in skills_dir.glob("*.md") if not p.name.startswith("."))
    await host.append_system(", ".join(skills) if skills else "no skills installed.")
    return CommandResult()


async def cmd_pairing(host: CommandHost, arg: str = "") -> CommandResult:
    from brainstem.reflexes import DMPairing

    store = DMPairing(host.ctx.pairing_store)
    entries = store.list()
    if not entries:
        await host.append_system("no pairings.")
        return CommandResult()
    rows = [f"{e['channel']} {e.get('status', '?')} {e.get('paired_at', '')}" for e in entries]
    await host.append_system("\n".join(rows))
    return CommandResult()


async def cmd_persona(host: CommandHost, arg: str = "") -> CommandResult:
    await host.append_rich(Panel(host.ctx.persona_summary, title="persona"))
    return CommandResult()


async def cmd_profile(host: CommandHost, arg: str = "") -> CommandResult:
    await host.append_system(f"profile {host.ctx.profile_name} home={host.ctx.home_root}")
    return CommandResult()


async def cmd_doctor(host: CommandHost, arg: str = "") -> CommandResult:
    from cortex import config as config_module
    from cortex.diagnostics import aggregate_status, run_checks
    from cortex.home import CortexHome

    home = CortexHome.resolve(root=host.ctx.home_root, profile=host.ctx.profile_name).bootstrap()
    try:
        cfg = config_module.load(home)
    except config_module.ConfigError as exc:
        await host.append_system(str(exc))
        return CommandResult(ok=False)
    results = await run_checks(home, cfg)
    status = aggregate_status(results)
    lines = [f"{r.status:<4} {r.name} {r.message}" for r in results]
    await host.append_rich(Panel("\n".join(lines), title=f"doctor ({status})"))
    return CommandResult(ok=status == "ok")


async def cmd_history(host: CommandHost, arg: str = "") -> CommandResult:
    from cortex.conversation import ConversationStore

    if host.ctx.conversations_dir is None:
        await host.append_system("conversations dir not configured.")
        return CommandResult(ok=False)
    conv = ConversationStore(host.ctx.conversations_dir).open(host.ctx.active_channel, host.ctx.active_peer)
    turns = conv.recent(turns=12, char_budget=4000)
    if not turns:
        await host.append_system("no recorded turns yet.")
        return CommandResult()
    rows = [f"{t.role:>9} {t.content.strip().replace(chr(10), ' ')[:200]}" for t in turns]
    await host.append_rich(Panel("\n".join(rows), title="history"))
    return CommandResult()


async def cmd_forget(host: CommandHost, arg: str = "") -> CommandResult:
    from cortex.conversation import ConversationStore

    if host.ctx.conversations_dir is None:
        await host.append_system("conversations dir not configured.")
        return CommandResult(ok=False)
    conv = ConversationStore(host.ctx.conversations_dir).open(host.ctx.active_channel, host.ctx.active_peer)
    bytes_wiped = conv.clear()
    await host.append_system(f"forgot transcript ({bytes_wiped} bytes erased)")
    return CommandResult()


async def cmd_tools(host: CommandHost, arg: str = "") -> CommandResult:
    names = host.ctx.tool_names
    if names is None:
        await host.append_system("tools are off.")
        return CommandResult()
    if not names:
        await host.append_system("tools enabled but no tools registered.")
        return CommandResult(ok=False)
    await host.append_system("\n".join(names))
    return CommandResult()


async def cmd_facts(host: CommandHost, arg: str = "") -> CommandResult:
    if host.ctx.facts_dir is None:
        await host.append_system("facts store not configured.")
        return CommandResult(ok=False)
    from cortex.semantic_facts import FactStore

    facts = FactStore(host.ctx.facts_dir).facts_for(host.ctx.active_peer)
    if not facts:
        await host.append_system("no learned facts yet.")
        return CommandResult()
    facts.sort(key=lambda f: (f.confidence, f.updated_at), reverse=True)
    rows = [f"{f.confidence:.2f} {f.text}" for f in facts]
    await host.append_rich(Panel("\n".join(rows), title="facts"))
    return CommandResult()


async def cmd_episodes(host: CommandHost, arg: str = "") -> CommandResult:
    if host.ctx.episodes_dir is None:
        await host.append_system("episodes store not configured.")
        return CommandResult(ok=False)
    from cortex.episodes import EpisodeStore

    eps = EpisodeStore(host.ctx.episodes_dir).recent(
        channel=host.ctx.active_channel, peer=host.ctx.active_peer, n=12
    )
    if not eps:
        await host.append_system("no episodes yet.")
        return CommandResult()
    rows = [f"{e.ts[5:16]} {'/'.join(e.tools_used)} {e.user_text[:100]}" for e in eps]
    await host.append_rich(Panel("\n".join(rows), title="episodes"))
    return CommandResult()


async def cmd_sleep(host: CommandHost, arg: str = "") -> CommandResult:
    if host.ctx.sleep_now is None:
        await host.append_system("sleep not available.")
        return CommandResult(ok=False)
    force = arg.strip().lower() in {"force", "now", "-f"}
    out = await host.ctx.sleep_now(force=force) if force else await host.ctx.sleep_now()
    await host.append_system(f"sleep {out.get('status', '?')} {out}")
    return CommandResult(ok=out.get("status") == "ok")


async def cmd_affect(host: CommandHost, arg: str = "") -> CommandResult:
    text = arg.strip()
    if not text:
        await host.append_system("usage: /affect <text>")
        return CommandResult(ok=False)
    from cortex.affect import score_text

    a = score_text(text)
    await host.append_system(
        f"valence={a.valence:+.3f} arousal={a.arousal:.3f} salience={a.salience:.3f} triggers={','.join(a.triggers)}"
    )
    return CommandResult()


async def cmd_system(host: CommandHost, arg: str = "") -> CommandResult:
    if host.ctx.system_prompt_provider is None:
        await host.append_system("system prompt inspector is not available.")
        return CommandResult(ok=False)
    text = await host.ctx.system_prompt_provider()
    await host.append_rich(Panel(text.strip() or "(empty system prompt)", title="system prompt"))
    return CommandResult()


async def cmd_exit(host: CommandHost, arg: str = "") -> CommandResult:
    await host.request_exit()
    return CommandResult()


CommandHandler = Callable[[CommandHost, str], Awaitable[CommandResult]]
