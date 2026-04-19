"""tui_app.py — the rich interactive TUI front-end.

Built on `prompt_toolkit` so we get a hermes-style layout:

    +-----------------------------------------------------------+
    |                       (banner + scrollback)                |
    |  you   > what's the weather                                |
    |  atulya> I can't read the weather without a tool, but ...  |
    |                                                            |
    +-----------------------------------------------------------+
    | atulya >                                                   |  <- bottom-anchored input (1-8 lines)
    +-----------------------------------------------------------+
    |  model:lm_studio/google/gemma-3-4b   profile:default       |  <- status bar
    +-----------------------------------------------------------+

Distinct from `sensors/tui.py` (which stays as a minimal headless stdin
sensor used by tests). This module is what `atulya-cortex chat` actually
runs interactively.

Slash commands
--------------
- `/help`      — list slash commands
- `/model`     — print active provider / model
- `/clear`     — wipe scrollback
- `/skills`    — list installed skills
- `/pairing`   — list current pairings
- `/doctor`    — run diagnostics inline
- `/persona`   — print the active persona file path + voice
- `/profile`   — print the active profile name
- `/quit`      — leave (Ctrl-D / Ctrl-C also work)

The cortex pipeline (Stimulus -> Router -> Cortex -> Reply) is still the
backbone; this module is purely the I/O surface.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from prompt_toolkit import HTML, PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from cortex.bus import Action, Intent, Stimulus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------


ATULYA_LOGO = r"""[bold #00D4FF]   █████╗ ████████╗██╗   ██╗██╗  ██╗   ██╗ █████╗[/]
[bold #00D4FF]  ██╔══██╗╚══██╔══╝██║   ██║██║  ╚██╗ ██╔╝██╔══██╗[/]
[bold #00BFD4]  ███████║   ██║   ██║   ██║██║   ╚████╔╝ ███████║[/]
[bold #00A0B0]  ██╔══██║   ██║   ██║   ██║██║    ╚██╔╝  ██╔══██║[/]
[bold #00808A]  ██║  ██║   ██║   ╚██████╔╝███████╗██║   ██║  ██║[/]
[bold #00606A]  ╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚══════╝╚═╝   ╚═╝  ╚═╝[/]
[dim #00BFD4]                            c o r t e x[/]"""


HELP_TEXT = """\
[bold]Slash commands[/bold]
  /help               this list
  /model              show active provider / model
  /clear              clear the scrollback
  /skills             list installed skills
  /pairing            list current channel pairings
  /persona            show the active persona summary
  /profile            show the active profile name
  /doctor             run diagnostics
  /history            show the recent conversation transcript
  /forget             wipe the working memory for this peer
  /tools              list tools the cortex can use this turn
  /facts              show what the brain has learned about this peer
  /episodes           show recent episodic memories for this peer
  /sleep              consolidate recent episodes into durable facts
  /affect <text>      debug the amygdala's score for a snippet
  /quit, /exit        leave

[bold]Keys[/bold]
  Enter               send the message
  Shift-Enter         newline (multi-line input)
  Up / Down           browse history
  Ctrl-L              clear scrollback
  Ctrl-C / Ctrl-D     leave
"""


# ---------------------------------------------------------------------------
# Slash command completer
# ---------------------------------------------------------------------------


_SLASH_COMMANDS: tuple[tuple[str, str], ...] = (
    ("/help", "list slash commands"),
    ("/model", "show active provider / model"),
    ("/clear", "clear the scrollback"),
    ("/skills", "list installed skills"),
    ("/pairing", "list current pairings"),
    ("/persona", "show the active persona"),
    ("/profile", "show the active profile"),
    ("/doctor", "run diagnostics"),
    ("/history", "show recent conversation transcript"),
    ("/forget", "wipe working memory for this peer"),
    ("/tools", "list tools the cortex may call this turn"),
    ("/facts", "show learned facts about this peer"),
    ("/episodes", "show recent episodic memories"),
    ("/sleep", "consolidate episodes into facts now"),
    ("/affect", "debug the affect score for the rest of the line"),
    ("/quit", "leave"),
    ("/exit", "leave"),
)


class _SlashCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for name, desc in _SLASH_COMMANDS:
            if name.startswith(text):
                yield Completion(name, start_position=-len(text), display_meta=desc)


# ---------------------------------------------------------------------------
# TUI session
# ---------------------------------------------------------------------------


CortexCallable = Callable[[Stimulus], Awaitable[Intent | None]]


@dataclass
class TuiContext:
    """Lightweight bag we hand to slash command handlers so they can render
    info without re-loading config from disk on every keystroke."""

    home_root: Path
    profile_name: str
    provider: str
    model: str
    base_url: str
    persona_summary: str
    skills_dir: Path
    pairing_store: Path
    # Conversation transcripts root + the active (channel, peer) tuple so
    # /forget and /history don't have to re-derive the path from
    # CortexHome on every call. None disables those commands gracefully.
    conversations_dir: Path | None = None
    active_channel: str = "tui"
    active_peer: str = "local"
    # Snapshot of the deliberation arc surface for `/tools` introspection.
    # `None` means tools are off; an empty tuple means tools are on but
    # nothing is currently registered (a misconfiguration worth showing).
    tool_names: tuple[str, ...] | None = None
    tool_max_actions: int = 0
    # Long-term memory introspection. Both default to None so the TUI
    # degrades gracefully when wired up in older code paths.
    episodes_dir: Path | None = None
    facts_dir: Path | None = None
    # Async callable that triggers one consolidation pass for
    # (active_channel, active_peer). None disables `/sleep` cleanly.
    sleep_now: Callable[[], Awaitable[dict]] | None = None
    extras: dict = field(default_factory=dict)


class CortexTui:
    """Rich, hermes-style TUI for the cortex.

    Wires keyboard input -> Cortex.reflect -> Rich rendering. Construct with
    a `cortex_call` async callable so the Cortex stays the executive — this
    class is purely an I/O surface.
    """

    def __init__(
        self,
        *,
        cortex_call: CortexCallable,
        ctx: TuiContext,
        history_path: Path,
        peer: str = "local",
    ) -> None:
        self._cortex_call = cortex_call
        self._ctx = ctx
        self._peer = peer
        self._channel = f"tui:{peer}"
        self._console = Console(highlight=False)
        self._stop = False
        self._busy = False
        self._history_path = history_path
        history_path.parent.mkdir(parents=True, exist_ok=True)

        self._kb = KeyBindings()

        @self._kb.add("c-l")
        def _(event):
            self._clear_scrollback()

        self._session: PromptSession[str] = PromptSession(
            history=FileHistory(str(history_path)),
            completer=_SlashCompleter(),
            complete_while_typing=True,
            key_bindings=self._kb,
            multiline=False,
            mouse_support=False,
            style=_PROMPT_STYLE,
            bottom_toolbar=self._bottom_toolbar,
        )

    # ---- public --------------------------------------------------------------

    async def run(self) -> None:
        self._print_banner()
        try:
            while not self._stop:
                try:
                    text = await self._session.prompt_async(self._prompt_fragments())
                except (EOFError, KeyboardInterrupt):
                    return
                text = (text or "").strip()
                if not text:
                    continue
                if text.startswith("/"):
                    await self._handle_slash(text)
                    continue
                await self._handle_message(text)
        finally:
            self._console.print("[dim]session ended.[/dim]")

    # ---- rendering -----------------------------------------------------------

    def _print_banner(self) -> None:
        self._console.print()
        self._console.print(ATULYA_LOGO)
        self._console.print()
        subtitle = (
            f"[#00BFD4]biomimetic AI brain[/]   "
            f"[dim]profile:[/] [bold]{self._ctx.profile_name}[/]   "
            f"[dim]channel:[/] [bold]{self._channel}[/]"
        )
        self._console.print(Panel(subtitle, border_style="#00808A", padding=(0, 2)))
        self._console.print(
            f"[dim]model:[/] [bold]{self._ctx.provider}/{self._ctx.model}[/]   "
            f"[dim]home:[/] [bold]{self._ctx.home_root}[/]"
        )
        self._console.print("[dim]type [bold]/help[/bold] for commands, [bold]/quit[/bold] to leave.[/dim]")
        self._console.print()

    def _prompt_fragments(self):
        # prompt_toolkit "fragments" are (style, text) tuples; we wrap in HTML.
        return HTML('<ansicyan><b>you</b></ansicyan> <ansibrightblack>></ansibrightblack> ')

    def _bottom_toolbar(self):
        cols = shutil.get_terminal_size((100, 24)).columns
        left = f" {self._ctx.provider}/{self._ctx.model}  •  profile:{self._ctx.profile_name}  •  channel:{self._channel} "
        right = "ctrl-l clear  ·  ctrl-d quit "
        pad = max(1, cols - len(left) - len(right))
        spaces = " " * pad
        return HTML(
            f'<style fg="black" bg="#00BFD4">{_html_escape(left)}{spaces}{_html_escape(right)}</style>'
        )

    def _print_user_echo(self, text: str) -> None:
        # prompt_toolkit already echoed the line; we add a faint repeat to the
        # scrollback so the conversation reads top-to-bottom with consistent
        # speaker prefixes after a `/clear`.
        # Actually skip — duplicating clutters the screen. Keep this hook for
        # future "show prompt history" feature.
        return None

    def _print_assistant(self, text: str) -> None:
        # Treat assistant output as markdown so code fences, lists, etc. render.
        prefix = Text("atulya ", style="bold #00D4FF")
        prefix.append("> ", style="dim")
        self._console.print(prefix, end="")
        try:
            self._console.print(Markdown(text))
        except Exception:
            self._console.print(text)

    def _clear_scrollback(self) -> None:
        self._console.clear()
        self._print_banner()

    # ---- handlers ------------------------------------------------------------

    async def _handle_message(self, text: str) -> None:
        stim = Stimulus(channel=self._channel, sender=self._peer, text=text)
        self._busy = True
        try:
            with self._console.status("[#00BFD4]thinking[/]", spinner="dots"):
                intent = await self._cortex_call(stim)
        except Exception as exc:
            self._console.print(f"[red]error:[/] {exc}")
            return
        finally:
            self._busy = False

        if intent is None or intent.action.kind != "reply":
            self._console.print("[dim](no reply)[/dim]")
            return
        reply_text = str(intent.action.payload.get("text", "")).strip()
        if not reply_text:
            self._console.print("[dim](empty reply)[/dim]")
            return
        self._print_assistant(reply_text)

    async def _handle_slash(self, text: str) -> None:
        cmd, _, arg = text.partition(" ")
        cmd = cmd.lower()
        arg = arg.strip()
        handler = _SLASH_HANDLERS.get(cmd)
        if handler is None:
            self._console.print(f"[red]unknown command[/] [bold]{cmd}[/]   (try /help)")
            return
        try:
            # Try the new (tui, arg) signature first, fall back to (tui) for
            # legacy handlers. This keeps the dispatcher one-place-to-edit
            # while letting individual handlers grow optional arguments.
            import inspect
            sig = inspect.signature(handler)
            if len(sig.parameters) >= 2:
                await handler(self, arg)
            else:
                await handler(self)
        except Exception as exc:
            logger.exception("slash command %s crashed", cmd)
            self._console.print(f"[red]{cmd} crashed:[/] {exc}")


# ---------------------------------------------------------------------------
# Slash command handlers (kept module-level so they're trivially testable)
# ---------------------------------------------------------------------------


async def _slash_help(tui: CortexTui) -> None:
    tui._console.print(Panel(HELP_TEXT.strip(), border_style="#00808A", title="help", title_align="left"))


async def _slash_model(tui: CortexTui) -> None:
    tui._console.print(
        f"[bold #00D4FF]model[/]  provider=[bold]{tui._ctx.provider}[/]  "
        f"id=[bold]{tui._ctx.model}[/]  base_url=[dim]{tui._ctx.base_url}[/]"
    )


async def _slash_clear(tui: CortexTui) -> None:
    tui._clear_scrollback()


async def _slash_skills(tui: CortexTui) -> None:
    if not tui._ctx.skills_dir.exists():
        tui._console.print("[dim]no skills directory yet — run [bold]/doctor[/bold] or `atulya-cortex skills sync`.[/dim]")
        return
    skills = sorted(p.stem for p in tui._ctx.skills_dir.glob("*.md") if not p.name.startswith("."))
    if not skills:
        tui._console.print("[dim]no skills installed.[/dim]")
        return
    tui._console.print(Panel(", ".join(skills), border_style="#00808A", title="skills", title_align="left"))


async def _slash_pairing(tui: CortexTui) -> None:
    from brainstem.reflexes import DMPairing

    store = DMPairing(tui._ctx.pairing_store)
    entries = store.list()
    if not entries:
        tui._console.print("[dim]no pairings.[/dim]")
        return
    rows = [f"  [bold]{e['channel']}[/]  [dim]{e.get('status', '?')}[/] {e.get('paired_at', '')}" for e in entries]
    tui._console.print(Panel("\n".join(rows), border_style="#00808A", title="pairings", title_align="left"))


async def _slash_persona(tui: CortexTui) -> None:
    tui._console.print(Panel(tui._ctx.persona_summary, border_style="#00808A", title="persona", title_align="left"))


async def _slash_profile(tui: CortexTui) -> None:
    tui._console.print(f"[bold]profile[/] [bold #00D4FF]{tui._ctx.profile_name}[/]   [dim]home:[/] {tui._ctx.home_root}")


async def _slash_doctor(tui: CortexTui) -> None:
    # Run diagnostics inline; mirrors `atulya-cortex doctor` without --fix.
    from cortex import config as config_module
    from cortex.diagnostics import aggregate_status, run_checks
    from cortex.home import CortexHome

    home = CortexHome.resolve(root=tui._ctx.home_root, profile=tui._ctx.profile_name).bootstrap()
    try:
        cfg = config_module.load(home)
    except config_module.ConfigError as exc:
        tui._console.print(f"[red]{exc}[/red]")
        return
    results = await run_checks(home, cfg)
    status = aggregate_status(results)
    rows = []
    for r in results:
        color = {"ok": "green", "warn": "yellow", "fail": "red", "skip": "dim"}.get(r.status, "white")
        rows.append(f"  [{color}]{r.status:<4}[/]  [bold]{r.name}[/]  [dim]{r.message}[/]")
    tui._console.print(
        Panel("\n".join(rows), border_style="#00808A", title=f"doctor ({status})", title_align="left")
    )


async def _slash_quit(tui: CortexTui) -> None:
    tui._stop = True


async def _slash_history(tui: CortexTui) -> None:
    """Show the recent conversation transcript for this (channel, peer).

    Read-only: we don't mutate the on-disk JSONL. Defensive against missing
    conversations dir so the TUI keeps working in degraded states.
    """

    conv = _open_conversation(tui)
    if conv is None:
        tui._console.print("[dim]conversations dir not configured for this session.[/dim]")
        return
    turns = conv.recent(turns=12, char_budget=4000)
    if not turns:
        tui._console.print(
            f"[dim]no recorded turns yet for [bold]{tui._ctx.active_channel}:{tui._ctx.active_peer}[/bold].[/dim]"
        )
        return
    rows = []
    for t in turns:
        speaker = "atulya" if t.role == "assistant" else t.role
        body = t.content.strip().replace("\n", " ")
        if len(body) > 200:
            body = body[:197] + "..."
        rows.append(f"  [bold]{speaker:>9}[/]  {body}")
    title = f"history ({tui._ctx.active_channel}:{tui._ctx.active_peer}, {len(turns)} turn(s))"
    tui._console.print(Panel("\n".join(rows), border_style="#00808A", title=title, title_align="left"))


async def _slash_facts(tui: CortexTui, arg: str = "") -> None:
    """Render the brain's durable knowledge of the active peer.

    Reads from `FactStore` directly so it always reflects the on-disk
    truth — including facts written by background consolidation since
    the last system-prompt build.
    """

    if tui._ctx.facts_dir is None:
        tui._console.print("[dim]facts store not configured.[/dim]")
        return
    from cortex.semantic_facts import FactStore

    store = FactStore(tui._ctx.facts_dir)
    facts = store.facts_for(tui._ctx.active_peer)
    if not facts:
        tui._console.print(
            f"[dim]no learned facts yet about [bold]{tui._ctx.active_peer}[/]. "
            "Try [bold]/sleep[/bold] after a few exchanges.[/dim]"
        )
        return
    facts.sort(key=lambda f: (f.confidence, f.updated_at), reverse=True)
    rows = []
    for f in facts:
        tags = f" [#00808A]({', '.join(f.tags)})[/]" if f.tags else ""
        rows.append(f"  [bold]{f.confidence:.2f}[/]  {f.text}{tags}  [dim]{f.updated_at[:10]}[/]")
    title = f"facts ({tui._ctx.active_peer}, {len(facts)} known)"
    tui._console.print(Panel("\n".join(rows), border_style="#00808A", title=title, title_align="left"))


async def _slash_episodes(tui: CortexTui, arg: str = "") -> None:
    """Show recent episodic memories for the active peer.

    Episodes are richer than `/history` (working memory): they include
    affect tags, tool-use traces, and consolidation status — useful for
    understanding why the brain remembers what it remembers.
    """

    if tui._ctx.episodes_dir is None:
        tui._console.print("[dim]episodes store not configured.[/dim]")
        return
    from cortex.episodes import EpisodeStore

    store = EpisodeStore(tui._ctx.episodes_dir)
    eps = store.recent(channel=tui._ctx.active_channel, peer=tui._ctx.active_peer, n=12)
    if not eps:
        tui._console.print("[dim]no episodes yet for this peer.[/dim]")
        return
    rows = []
    for ep in eps:
        marker = "✓" if ep.consolidated else " "
        affect = (
            f"v={ep.affect.valence:+.2f} a={ep.affect.arousal:.2f} s={ep.affect.salience:.2f}"
        )
        body = ep.user_text.replace("\n", " ")[:100]
        tools = f" [#00808A][{','.join(ep.tools_used)}][/]" if ep.tools_used else ""
        rows.append(f"  {marker} [dim]{ep.ts[5:16]}[/]  [bold]{affect}[/]{tools}  {body}")
    title = (
        f"episodes ({tui._ctx.active_channel}:{tui._ctx.active_peer}, "
        f"{len(eps)} shown — ✓ = consolidated)"
    )
    tui._console.print(Panel("\n".join(rows), border_style="#00808A", title=title, title_align="left"))


async def _slash_sleep(tui: CortexTui, arg: str = "") -> None:
    """Trigger the consolidation pass for the active peer.

    Pass `force` as the argument to bypass the cooldown / min-episode /
    min-salience gates — useful when you want to see what consolidation
    would extract right now.
    """

    if tui._ctx.sleep_now is None:
        tui._console.print(
            "[dim]sleep not available — needs `[memory]` consolidation wired and a Language driver.[/dim]"
        )
        return
    force = arg.strip().lower() in {"force", "now", "-f"}
    with tui._console.status("[#00BFD4]consolidating[/]", spinner="dots"):
        try:
            if force:
                # The wrapper builds the call with force=True from arg.
                out = await tui._ctx.sleep_now(force=True)  # type: ignore[call-arg]
            else:
                out = await tui._ctx.sleep_now()
        except Exception as exc:
            tui._console.print(f"[red]sleep failed:[/] {exc}")
            return
    status = out.get("status", "?")
    color = {
        "ok": "green",
        "skipped_no_episodes": "dim",
        "skipped_low_salience": "dim",
        "skipped_cooldown": "dim",
        "error": "red",
    }.get(status, "white")
    summary = ", ".join(f"{k}={v}" for k, v in out.items() if k != "status")
    tui._console.print(f"[{color}]sleep[/]  [bold]{status}[/]  [dim]{summary}[/]")


async def _slash_affect(tui: CortexTui, arg: str = "") -> None:
    """Debug: show the amygdala's affective signature for the given snippet."""

    text = arg.strip()
    if not text:
        tui._console.print("[dim]usage: /affect <text>[/dim]")
        return
    from cortex.affect import score_text

    a = score_text(text)
    body = (
        f"  valence  [bold]{a.valence:+.3f}[/]\n"
        f"  arousal  [bold]{a.arousal:.3f}[/]\n"
        f"  salience [bold]{a.salience:.3f}[/]\n"
        f"  triggers [dim]{', '.join(a.triggers) or '(none)'}[/]"
    )
    tui._console.print(Panel(body, border_style="#00808A", title="affect", title_align="left"))


async def _slash_tools(tui: CortexTui) -> None:
    """Show the deliberation-arc surface for this session.

    Surfaces *what the brain may actually do*, separately from what the
    persona promises — so the operator can debug "why did it just answer
    instead of running the command I asked?" without grepping config.
    """

    names = tui._ctx.tool_names
    if names is None:
        tui._console.print(
            "[dim]tools are [bold]off[/bold] — set `[tools] enabled = true` in your config "
            "to let the brain act on the world.[/dim]"
        )
        return
    if not names:
        tui._console.print(
            "[yellow]tools are enabled but no tools are registered. "
            "Check `[tools]` in your config.[/]"
        )
        return
    rows = [f"  [bold]{name}[/]" for name in names]
    title = f"tools (max {tui._ctx.tool_max_actions} per stimulus, channel = {tui._ctx.active_channel})"
    tui._console.print(Panel("\n".join(rows), border_style="#00808A", title=title, title_align="left"))


async def _slash_forget(tui: CortexTui) -> None:
    """Wipe the working-memory transcript for this (channel, peer).

    Equivalent to closing this conversation and starting fresh — useful
    when you've been testing prompts and the model is acting on stale
    context, or when you want to hand the brain to someone else without
    leaking your own prior turns.
    """

    conv = _open_conversation(tui)
    if conv is None:
        tui._console.print("[dim]conversations dir not configured for this session.[/dim]")
        return
    bytes_wiped = conv.clear()
    if bytes_wiped == 0:
        tui._console.print("[dim]nothing to forget — no transcript on disk.[/dim]")
    else:
        tui._console.print(
            f"[#00D4FF]forgot[/] [bold]{tui._ctx.active_channel}:{tui._ctx.active_peer}[/]  "
            f"[dim]({bytes_wiped} bytes erased)[/]"
        )


def _open_conversation(tui: CortexTui):
    """Get a `Conversation` handle for the TUI's active peer, or None.

    Imported lazily so the TUI module stays importable in environments
    where the cortex package is partially installed (e.g. our CLI smoke
    test in a container that lacks pydantic).
    """

    if tui._ctx.conversations_dir is None:
        return None
    from cortex.conversation import ConversationStore

    store = ConversationStore(tui._ctx.conversations_dir)
    return store.open(tui._ctx.active_channel, tui._ctx.active_peer)


_SLASH_HANDLERS: dict[str, Callable[[CortexTui], Awaitable[None]]] = {
    "/help": _slash_help,
    "/model": _slash_model,
    "/clear": _slash_clear,
    "/skills": _slash_skills,
    "/pairing": _slash_pairing,
    "/persona": _slash_persona,
    "/profile": _slash_profile,
    "/doctor": _slash_doctor,
    "/history": _slash_history,
    "/forget": _slash_forget,
    "/tools": _slash_tools,
    "/facts": _slash_facts,
    "/episodes": _slash_episodes,
    "/sleep": _slash_sleep,
    "/affect": _slash_affect,
    "/quit": _slash_quit,
    "/exit": _slash_quit,
}


# ---------------------------------------------------------------------------
# prompt_toolkit style
# ---------------------------------------------------------------------------


_PROMPT_STYLE = Style.from_dict(
    {
        "completion-menu": "bg:#000000 #00D4FF",
        "completion-menu.completion.current": "bg:#00BFD4 #000000",
        "bottom-toolbar": "bg:#00BFD4 #000000",
    }
)


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Entry point used by cli_commands/chat.py
# ---------------------------------------------------------------------------


async def run_tui(*, cortex_call: CortexCallable, ctx: TuiContext, history_path: Path, peer: str = "local") -> None:
    """Run the rich TUI loop. `cortex_call(stim)` returns an `Intent`."""

    tui = CortexTui(cortex_call=cortex_call, ctx=ctx, history_path=history_path, peer=peer)
    with patch_stdout(raw=True):
        await tui.run()


__all__ = ["ATULYA_LOGO", "CortexTui", "TuiContext", "run_tui"]
