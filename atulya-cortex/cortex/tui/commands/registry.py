from __future__ import annotations

from dataclasses import dataclass

from cortex.tui.commands.handlers import (
    CommandHandler,
    cmd_affect,
    cmd_clear,
    cmd_doctor,
    cmd_episodes,
    cmd_exit,
    cmd_facts,
    cmd_forget,
    cmd_help,
    cmd_history,
    cmd_model,
    cmd_pairing,
    cmd_persona,
    cmd_profile,
    cmd_skills,
    cmd_sleep,
    cmd_system,
    cmd_tools,
)


@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    handler: CommandHandler


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, CommandSpec] = {}

    def register(self, spec: CommandSpec) -> None:
        self._commands[spec.name] = spec

    def get(self, name: str) -> CommandSpec | None:
        return self._commands.get(name)

    def list(self) -> tuple[CommandSpec, ...]:
        return tuple(self._commands.values())

    @classmethod
    def with_defaults(cls) -> "CommandRegistry":
        reg = cls()
        for spec in (
            CommandSpec("/help", "list slash commands", cmd_help),
            CommandSpec("/model", "show active provider/model", cmd_model),
            CommandSpec("/clear", "clear transcript panel", cmd_clear),
            CommandSpec("/skills", "list installed skills", cmd_skills),
            CommandSpec("/pairing", "list current pairings", cmd_pairing),
            CommandSpec("/persona", "show active persona", cmd_persona),
            CommandSpec("/profile", "show active profile", cmd_profile),
            CommandSpec("/doctor", "run diagnostics", cmd_doctor),
            CommandSpec("/history", "show recent transcript", cmd_history),
            CommandSpec("/forget", "wipe transcript for peer", cmd_forget),
            CommandSpec("/tools", "show tool surface", cmd_tools),
            CommandSpec("/facts", "show durable facts", cmd_facts),
            CommandSpec("/episodes", "show episodic memory", cmd_episodes),
            CommandSpec("/sleep", "run consolidation now", cmd_sleep),
            CommandSpec("/affect", "debug affect scoring", cmd_affect),
            CommandSpec("/system", "show current system prompt", cmd_system),
            CommandSpec("/quit", "leave session", cmd_exit),
            CommandSpec("/exit", "leave session", cmd_exit),
        ):
            reg.register(spec)
        return reg
