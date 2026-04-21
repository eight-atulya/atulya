from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from rich.markdown import Markdown
from rich.markup import escape
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.widgets import Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from cortex.bus import Stimulus
from cortex.tui.commands.registry import CommandRegistry
from cortex.tui.plugins.base import PanelSpec
from cortex.tui.plugins.registry import PluginRegistry
from cortex.tui.services.debug_store import DebugStore
from cortex.tui.services.perf_service import PerfService
from cortex.tui.services.prompt_service import PromptService
from cortex.tui.state.session_state import SessionState
from cortex.tui.theme import APP_CSS
from cortex.tui.types import CortexCallable, TuiContext

logger = logging.getLogger(__name__)


class TextualCortexApp(App):
    CSS = APP_CSS
    BINDINGS = [
        ("ctrl+l", "clear_log", "Clear"),
        ("ctrl+d", "quit", "Quit"),
        ("ctrl+p", "toggle_prompt", "Prompt"),
        ("tab", "complete_command", "Complete"),
    ]

    def __init__(self, *, cortex_call: CortexCallable, ctx: TuiContext, history_path: Path, peer: str = "local") -> None:
        super().__init__()
        self._ctx = ctx
        self._peer = peer
        self._channel = f"tui:{peer}"
        self._cortex_call = cortex_call
        self._state = SessionState()
        self._history_path = history_path
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self._commands = CommandRegistry.with_defaults()
        self._perf = PerfService()
        self._prompts = PromptService(ctx)
        self._debug = DebugStore(self._ctx.home_root / "logs" / "debug")
        self._plugins = PluginRegistry()
        self._bg_tasks: set[asyncio.Task] = set()
        self._command_matches: list[str] = []
        self._wire_file_logger()
        self._load_plugins_from_context()

    def _wire_file_logger(self) -> None:
        log_dir = self._ctx.home_root / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "tui-textual.log"
        handler = logging.FileHandler(path, encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root = logging.getLogger("cortex.tui")
        root.setLevel(logging.INFO)
        if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == str(path) for h in root.handlers):
            root.addHandler(handler)

    def _load_plugins_from_context(self) -> None:
        specs = self._ctx.extras.get("panel_plugins", ())
        valid_specs: list[PanelSpec] = []
        for spec in specs:
            if isinstance(spec, PanelSpec):
                valid_specs.append(spec)
        self._plugins.load_builtin(valid_specs)

    def compose(self) -> ComposeResult:
        yield Static(
            f"{self._ctx.provider}/{self._ctx.model}  profile:{self._ctx.profile_name}  channel:{self._channel}  "
            "ctrl+p prompt  ctrl+l clear  ctrl+d quit",
            id="titleBar",
        )
        with Horizontal(id="main"):
            with Vertical(id="leftPane"):
                yield RichLog(id="chatLog", markup=True, auto_scroll=True, wrap=False)
                yield OptionList(id="commandPopup")
                yield Input(placeholder="Type a message or /command", id="composer")
                yield Static("Ready", id="statusBar")
            with Vertical(id="rightPane"):
                yield RichLog(id="promptPane", markup=True, auto_scroll=True, wrap=False)
                yield Static("", id="telemetryPane")
                for panel in self._plugins.list_panels():
                    yield panel.factory.build()

    async def on_mount(self) -> None:
        await self.append_system("Textual TUI ready. Use /help for commands.")
        self.query_one("#commandPopup", OptionList).display = False
        prompt_text = await self._prompts.current()
        await self._write_prompt(prompt_text)
        await self._write_telemetry()
        self._apply_responsive_layout()
        self._debug.append(
            "session_start",
            {
                "channel": self._channel,
                "peer": self._peer,
                "provider": self._ctx.provider,
                "model": self._ctx.model,
                "profile": self._ctx.profile_name,
            },
        )

    def on_resize(self, event: Resize) -> None:
        self._apply_responsive_layout()

    def _apply_responsive_layout(self) -> None:
        right = self.query_one("#rightPane", Vertical)
        # Compact mode for narrow terminals: prioritize the chat transcript.
        right.display = self.size.width >= 120

    async def append_system(self, text: str) -> None:
        self.query_one("#chatLog", RichLog).write(f"[bold #FFD400]system[/] > {escape(text)}")

    async def append_rich(self, renderable) -> None:
        self.query_one("#chatLog", RichLog).write(renderable)

    async def request_exit(self) -> None:
        for task in tuple(self._bg_tasks):
            task.cancel()
        self._debug.append(
            "session_end",
            {
                "channel": self._channel,
                "peer": self._peer,
                "turn_count": self._state.turn_count,
            },
        )
        self.exit()

    @property
    def ctx(self) -> TuiContext:
        return self._ctx

    async def _write_prompt(self, text: str) -> None:
        pane = self.query_one("#promptPane", RichLog)
        pane.clear()
        pane.write(f"[bold #FFD400]system prompt[/]")
        pane.write(text)

    async def _write_telemetry(self) -> None:
        snap = self._perf.snapshot()
        pane = self.query_one("#telemetryPane", Static)
        pane.update(
            f"turns {snap['turns']}   avg_ms {snap['avg_ms']}   errors {snap['errors']}"
        )

    def action_clear_log(self) -> None:
        self.query_one("#chatLog", RichLog).clear()

    async def action_toggle_prompt(self) -> None:
        self._state.show_prompt_panel = not self._state.show_prompt_panel
        pane = self.query_one("#promptPane")
        pane.display = self._state.show_prompt_panel

    def action_complete_command(self) -> None:
        popup = self.query_one("#commandPopup", OptionList)
        if not popup.display or not self._command_matches:
            return
        composer = self.query_one("#composer", Input)
        composer.value = f"{self._command_matches[0]} "
        popup.display = False
        self._command_matches = []
        composer.focus()

    @on(Input.Changed, "#composer")
    async def on_input_changed(self, event: Input.Changed) -> None:
        self._refresh_command_popup((event.value or "").strip())

    @on(OptionList.OptionSelected, "#commandPopup")
    async def on_command_popup_selected(self, event: OptionList.OptionSelected) -> None:
        selected = event.option_id or (
            self._command_matches[event.option_index]
            if 0 <= event.option_index < len(self._command_matches)
            else ""
        )
        if not selected:
            return
        composer = self.query_one("#composer", Input)
        composer.value = f"{selected} "
        popup = self.query_one("#commandPopup", OptionList)
        popup.display = False
        self._command_matches = []
        composer.focus()

    def _refresh_command_popup(self, text: str) -> None:
        popup = self.query_one("#commandPopup", OptionList)
        if not text.startswith("/"):
            popup.display = False
            self._command_matches = []
            return
        query = text.lower()
        specs = self._commands.list()
        matches = [s for s in specs if s.name.startswith(query)]
        if not matches and query == "/":
            matches = list(specs)
        matches = matches[:10]
        popup.clear_options()
        if not matches:
            popup.display = False
            self._command_matches = []
            return
        self._command_matches = [s.name for s in matches]
        popup.add_options([Option(f"{s.name}  {s.description}", id=s.name) for s in matches])
        popup.display = True

    @on(Input.Submitted, "#composer")
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        event.input.value = ""
        self.query_one("#commandPopup", OptionList).display = False
        self._command_matches = []
        if not text:
            return
        if text.startswith("/"):
            await self._handle_command(text)
            return
        await self._handle_chat(text)

    async def _handle_command(self, text: str) -> None:
        name, _, arg = text.partition(" ")
        self._debug.append(
            "command_received",
            {
                "command": name.lower(),
                "arg": arg.strip(),
                "channel": self._channel,
                "peer": self._peer,
            },
        )
        spec = self._commands.get(name.lower())
        if spec is None:
            await self.append_system(f"unknown command {name} (try /help)")
            self._debug.append(
                "command_result",
                {"command": name.lower(), "ok": False, "detail": "unknown command"},
            )
            return
        result = await spec.handler(self, arg.strip())
        self._debug.append(
            "command_result",
            {
                "command": name.lower(),
                "ok": bool(getattr(result, "ok", True)),
                "channel": self._channel,
                "peer": self._peer,
            },
        )
        if name.lower() == "/clear":
            self.action_clear_log()
            await self.append_system("cleared.")
        if name.lower() == "/system":
            await self._write_prompt(await self._prompts.current())

    async def _handle_chat(self, text: str) -> None:
        log = self.query_one("#chatLog", RichLog)
        status = self.query_one("#statusBar", Static)
        turn_id = str(uuid4())
        prompt_snapshot = await self._prompts.current()
        self._debug.append(
            "turn_start",
            {
                "turn_id": turn_id,
                "channel": self._channel,
                "peer": self._peer,
                "provider": self._ctx.provider,
                "model": self._ctx.model,
                "user_text": text,
                "system_prompt": prompt_snapshot,
            },
        )
        log.write(f"[bold #1E90FF]you[/] > {text}")
        self._perf.start()
        status.update("thinking...")
        stim = Stimulus(channel=self._channel, sender=self._peer, text=text)
        ok = True
        try:
            intent = await self._cortex_call(stim)
        except Exception as exc:
            ok = False
            logger.exception("chat turn failed")
            await self.append_system(f"error: {exc}")
            status.update("error")
            elapsed_ms = self._perf.stop(ok=False)
            self._debug.append(
                "turn_result",
                {
                    "turn_id": turn_id,
                    "ok": False,
                    "elapsed_ms": elapsed_ms,
                    "error": str(exc),
                },
            )
            await self._write_telemetry()
            return
        assistant_text = ""
        if intent is None or intent.action.kind != "reply":
            ok = False
            await self.append_system("(no reply)")
        else:
            reply_text = str(intent.action.payload.get("text", "")).strip()
            if reply_text:
                log.write("[bold #39FF14]atulya[/] > ")
                log.write(Markdown(reply_text))
                assistant_text = reply_text
            else:
                ok = False
                await self.append_system("(empty reply)")
        elapsed = self._perf.stop(ok=ok)
        self._state.turn_count += 1
        status.update(f"ready  -  last turn {elapsed}ms")
        logging.getLogger("cortex.tui").info("turn=%s ok=%s elapsed_ms=%s", self._state.turn_count, ok, elapsed)
        self._debug.append(
            "turn_result",
            {
                "turn_id": turn_id,
                "ok": ok,
                "elapsed_ms": elapsed,
                "assistant_text": assistant_text,
                "turn_index": self._state.turn_count,
            },
        )
        await self._write_telemetry()


async def run_textual_tui(*, cortex_call: CortexCallable, ctx: TuiContext, history_path: Path, peer: str = "local") -> None:
    app = TextualCortexApp(cortex_call=cortex_call, ctx=ctx, history_path=history_path, peer=peer)
    await app.run_async()
