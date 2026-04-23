"""setup_wizard.py — onboarding flow as pure, testable logic.

The wizard is intentionally split from `cli_commands/setup.py` so that:

- Tests can drive each section programmatically with a `ScriptedPrompter`.
- The (future) FastAPI dashboard can run the same wizard over HTTP by
  swapping in an HTTP-backed prompter.
- The installer can run individual sections without touching argparse.

Design contract:

- Every section is **idempotent**. Re-running `setup model` after a
  successful run with the same inputs leaves the same files on disk.
- Every section is **resumable**. If `setup` is killed mid-flow, the next
  run picks up from the next un-completed section.
- Nothing the wizard does is irreversible without an explicit `force`.
- Secrets ALWAYS go to `.env`, never to `config.toml`.
- Every section returns a `SectionResult` so the CLI can render a clean
  summary at the end.

Naming voice: section functions are verbs (`run_model`, `run_persona`).
The `SetupWizard` class is the orchestrator the CLI talks to.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import httpx

from cortex import config as config_module
from cortex.config import CortexConfig
from cortex.env_loader import write_env_file
from cortex.home import CortexHome
from cortex.skills_sync import SyncResult
from cortex.skills_sync import sync as sync_skills

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompter abstraction
# ---------------------------------------------------------------------------


class Prompter:
    """Tiny abstraction so tests can drive the wizard without a TTY."""

    def say(self, text: str = "") -> None:
        raise NotImplementedError

    def ask(self, prompt: str, *, default: str | None = None) -> str:
        raise NotImplementedError

    def ask_secret(self, prompt: str) -> str:
        raise NotImplementedError

    def ask_yes_no(self, prompt: str, *, default: bool = False) -> bool:
        raise NotImplementedError

    def ask_choice(self, prompt: str, choices: Sequence[str], *, default_index: int = 0) -> str:
        raise NotImplementedError


class ConsolePrompter(Prompter):
    """Real terminal prompter. Uses `input()` + `getpass` so it works on
    every shell. Honors `--non-interactive` by raising `NonInteractiveError`
    when a question would block."""

    def __init__(self, *, interactive: bool = True) -> None:
        self.interactive = interactive

    def _require_interactive(self, prompt: str) -> None:
        if not self.interactive:
            raise NonInteractiveError(prompt)

    def say(self, text: str = "") -> None:
        print(text)

    def ask(self, prompt: str, *, default: str | None = None) -> str:
        self._require_interactive(prompt)
        suffix = f" [{default}]" if default is not None else ""
        try:
            raw = input(f"{prompt}{suffix}: ").strip()
        except EOFError as exc:
            raise NonInteractiveError(prompt) from exc
        return raw or (default or "")

    def ask_secret(self, prompt: str) -> str:
        self._require_interactive(prompt)
        from getpass import getpass

        try:
            return getpass(f"{prompt}: ").strip()
        except EOFError as exc:
            raise NonInteractiveError(prompt) from exc

    def ask_yes_no(self, prompt: str, *, default: bool = False) -> bool:
        self._require_interactive(prompt)
        marker = "Y/n" if default else "y/N"
        try:
            raw = input(f"{prompt} [{marker}]: ").strip().lower()
        except EOFError as exc:
            raise NonInteractiveError(prompt) from exc
        if not raw:
            return default
        return raw in ("y", "yes")

    def ask_choice(self, prompt: str, choices: Sequence[str], *, default_index: int = 0) -> str:
        self._require_interactive(prompt)
        if not choices:
            raise ValueError("ask_choice requires at least one choice")
        for i, choice in enumerate(choices):
            marker = "*" if i == default_index else " "
            print(f"  {marker} {i + 1}) {choice}")
        try:
            raw = input(f"{prompt} [{default_index + 1}]: ").strip()
        except EOFError as exc:
            raise NonInteractiveError(prompt) from exc
        if not raw:
            return choices[default_index]
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except ValueError:
            pass
        return choices[default_index]


class ScriptedPrompter(Prompter):
    """Drives the wizard from a pre-recorded script. Used in tests.

    Each call to `ask*` pops one entry from the matching queue. If a queue
    runs out we raise (better than silently looping defaults — the test
    contract is "every prompt answered explicitly").
    """

    def __init__(
        self,
        *,
        answers: Iterable[str] = (),
        secrets: Iterable[str] = (),
        yes_nos: Iterable[bool] = (),
        choices: Iterable[str] = (),
    ) -> None:
        self.answers = list(answers)
        self.secrets = list(secrets)
        self.yes_nos = list(yes_nos)
        self.choices = list(choices)
        self.transcript: list[str] = []

    def _pop(self, queue: list, kind: str, prompt: str):
        if not queue:
            raise AssertionError(f"ScriptedPrompter ran out of {kind} answers at prompt: {prompt!r}")
        value = queue.pop(0)
        self.transcript.append(f"{kind}: {prompt!r} -> {value!r}")
        return value

    def say(self, text: str = "") -> None:
        self.transcript.append(f"say: {text!r}")

    def ask(self, prompt: str, *, default: str | None = None) -> str:
        return self._pop(self.answers, "ask", prompt)

    def ask_secret(self, prompt: str) -> str:
        return self._pop(self.secrets, "secret", prompt)

    def ask_yes_no(self, prompt: str, *, default: bool = False) -> bool:
        return bool(self._pop(self.yes_nos, "yes_no", prompt))

    def ask_choice(self, prompt: str, choices: Sequence[str], *, default_index: int = 0) -> str:
        choice = self._pop(self.choices, "choice", prompt)
        if choice not in choices:
            raise AssertionError(f"ScriptedPrompter chose {choice!r} not in available {list(choices)!r}")
        return choice


class NonInteractiveError(RuntimeError):
    """Raised when the wizard needs user input but the prompter refuses."""


# ---------------------------------------------------------------------------
# Provider auto-detection
# ---------------------------------------------------------------------------


@dataclass
class ProviderProbe:
    """Snapshot of what's reachable on this machine right now."""

    lm_studio: bool = False
    ollama: bool = False
    openai_key: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def reachable(self) -> list[str]:
        out: list[str] = []
        if self.lm_studio:
            out.append("lm_studio")
        if self.ollama:
            out.append("ollama")
        if self.openai_key:
            out.append("openai")
        return out


def detect_providers(*, timeout_s: float = 1.0) -> ProviderProbe:
    """Synchronous provider probe. Best-effort, never raises."""

    probe = ProviderProbe()
    with httpx.Client(timeout=timeout_s) as client:
        for url, attr in (
            ("http://localhost:1234/v1/models", "lm_studio"),
            ("http://localhost:11434/api/tags", "ollama"),
        ):
            try:
                resp = client.get(url)
                ok = resp.status_code == 200
                setattr(probe, attr, ok)
                probe.raw[attr] = {"status": resp.status_code}
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                probe.raw[attr] = {"error": exc.__class__.__name__}
    probe.openai_key = bool(os.environ.get("OPENAI_API_KEY"))
    probe.raw["openai_key"] = {"present": probe.openai_key}
    return probe


# ---------------------------------------------------------------------------
# Section results
# ---------------------------------------------------------------------------


@dataclass
class SectionResult:
    name: str
    changed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    secrets_recorded: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ok": self.ok,
            "changed": list(self.changed),
            "skipped": list(self.skipped),
            "secrets_recorded": list(self.secrets_recorded),
            "notes": list(self.notes),
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# SetupWizard
# ---------------------------------------------------------------------------


SECTION_ORDER: tuple[str, ...] = (
    "home",
    "model",
    "persona",
    "bank",
    "skills",
    "telegram",
    "whatsapp",
)


class SetupWizard:
    """Orchestrates the onboarding flow.

    Construct with a `home`, a `Prompter`, and an optional `probe_fn`
    (defaults to live `detect_providers`). Each `run_*` method returns a
    `SectionResult`. `run_all()` walks `SECTION_ORDER` and aggregates."""

    def __init__(
        self,
        home: CortexHome,
        prompter: Prompter,
        *,
        probe_fn: Callable[[], ProviderProbe] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.home = home
        self.prompter = prompter
        self._probe_fn = probe_fn or detect_providers
        self._env = env if env is not None else os.environ

    # ---- internal helpers -------------------------------------------------

    def _load_or_seed_config(self) -> CortexConfig:
        config_module.seed(self.home)
        return config_module.load(self.home)

    def _save_config(self, cfg: CortexConfig) -> None:
        config_module.save(self.home, cfg)

    def _read_env_file(self) -> dict[str, str]:
        path = self.home.env_file
        if not path.exists():
            return {}
        out: dict[str, str] = {}
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].lstrip()
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    out[key] = value
        except OSError as exc:
            logger.warning("setup_wizard: failed to read %s: %s", path, exc)
        return out

    def _merge_secret(self, key: str, value: str) -> None:
        existing = self._read_env_file()
        existing[key] = value
        write_env_file(self.home.env_file, existing)
        os.environ[key] = value

    # ---- sections ---------------------------------------------------------

    def run_home(self) -> SectionResult:
        result = SectionResult(name="home")
        self.home.bootstrap()
        result.notes.append(f"home root: {self.home.root}")
        result.notes.append(f"profile:   {self.home.profile_name}")
        if not self.home.config_file.exists():
            config_module.seed(self.home)
            result.changed.append(str(self.home.config_file))
        else:
            result.skipped.append(str(self.home.config_file))
        return result

    def run_model(self) -> SectionResult:
        result = SectionResult(name="model")
        cfg = self._load_or_seed_config()
        probe = self._probe_fn()
        result.notes.append(
            "auto-detect: " + ", ".join(probe.reachable) if probe.reachable else "auto-detect: nothing reachable"
        )
        candidates = ["lm_studio", "ollama", "openai", "anthropic", "groq", "deepseek", "openrouter", "skip"]
        # promote reachable providers to the front of the list, preserving order
        ordered: list[str] = []
        seen: set[str] = set()
        for prov in probe.reachable + candidates:
            if prov not in seen and prov in candidates:
                ordered.append(prov)
                seen.add(prov)
        for prov in candidates:
            if prov not in seen:
                ordered.append(prov)
                seen.add(prov)
        choice = self.prompter.ask_choice(
            "Choose your model provider",
            ordered,
            default_index=0,
        )
        if choice == "skip":
            result.notes.append("model section skipped by user")
            return result

        cfg.model.provider = choice
        if choice == "lm_studio":
            cfg.model.base_url = self.prompter.ask(
                "LM Studio base URL",
                default=cfg.model.base_url or "http://localhost:1234/v1",
            )
            cfg.model.model = self.prompter.ask(
                "LM Studio model id",
                default=cfg.model.model or "google/gemma-3-4b",
            )
        elif choice == "ollama":
            cfg.model.base_url = self.prompter.ask(
                "Ollama base URL",
                default="http://localhost:11434/v1",
            )
            cfg.model.model = self.prompter.ask(
                "Ollama model tag",
                default="gemma3:4b",
            )
        else:
            # Hosted providers: keep base_url default, ask for model and key.
            cfg.model.base_url = self.prompter.ask(
                f"{choice} base URL (leave default unless using a proxy)",
                default=_default_base_url_for(choice),
            )
            cfg.model.model = self.prompter.ask(
                f"{choice} model id",
                default=_default_model_for(choice),
            )
            key_env = self.prompter.ask(
                f"Env var name that holds your {choice} API key",
                default=_default_key_env_for(choice),
            )
            cfg.model.api_key_env = key_env
            secret = self.prompter.ask_secret(f"Paste your {choice} API key (or leave blank to set later)")
            if secret:
                self._merge_secret(key_env, secret)
                result.secrets_recorded.append(key_env)
        self._save_config(cfg)
        result.changed.append(str(self.home.config_file))
        return result

    def run_persona(self) -> SectionResult:
        result = SectionResult(name="persona")
        if self.home.persona_file.exists() and not self.prompter.ask_yes_no(
            f"persona.md already exists at {self.home.persona_file}. Overwrite?",
            default=False,
        ):
            result.skipped.append(str(self.home.persona_file))
            return result
        operator = self.prompter.ask("Your name (used by the persona to address you)", default="Operator")
        name = self.prompter.ask("What should your brain be called", default="Atulya")
        voice = self.prompter.ask("Voice in 2-3 words (e.g. 'warm but terse')", default="warm but terse")
        traits_raw = self.prompter.ask(
            "Top 3 traits, comma-separated",
            default="curious, practical, honest",
        )
        traits = [t.strip() for t in traits_raw.split(",") if t.strip()]
        rendered = _render_persona_template(
            name=name,
            voice=voice,
            traits=traits,
            operator_name=operator,
        )
        self.home.persona_file.parent.mkdir(parents=True, exist_ok=True)
        self.home.persona_file.write_text(rendered, encoding="utf-8")
        result.changed.append(str(self.home.persona_file))
        return result

    def run_bank(self) -> SectionResult:
        result = SectionResult(name="bank")
        cfg = self._load_or_seed_config()
        cfg.memory.bank_id = self.prompter.ask(
            "atulya-embed bank id (used for memory recall + retain)",
            default=cfg.memory.bank_id or "atulya-cortex",
        )
        cfg.memory.api_url = self.prompter.ask(
            "atulya-api endpoint",
            default=cfg.memory.api_url or "http://localhost:8888",
        )
        cfg.memory.peer_banks_backend = self.prompter.ask_choice(
            "Peer-bank backend",
            ["embedded", "api"],
            default_index=0 if (cfg.memory.peer_banks_backend or "embedded") == "embedded" else 1,
        )
        if self.prompter.ask_yes_no("Does your atulya-api require an auth token?", default=False):
            key_env = self.prompter.ask(
                "Env var name for the atulya-api token",
                default=cfg.memory.api_key_env or "ATULYA_API_KEY",
            )
            cfg.memory.api_key_env = key_env
            secret = self.prompter.ask_secret("Paste the atulya-api token")
            if secret:
                self._merge_secret(key_env, secret)
                result.secrets_recorded.append(key_env)
        self._save_config(cfg)
        result.changed.append(str(self.home.config_file))
        return result

    def run_skills(self) -> SectionResult:
        result = SectionResult(name="skills")
        sync_result: SyncResult = sync_skills(self.home)
        for name in sync_result.copied:
            result.changed.append(f"skills/{name}")
        for name in sync_result.skipped:
            result.skipped.append(f"skills/{name}")
        for name in sync_result.preserved:
            result.notes.append(f"preserved user-edited skills/{name}")
        result.errors.extend(sync_result.errors)
        return result

    def run_telegram(self) -> SectionResult:
        result = SectionResult(name="telegram")
        cfg = self._load_or_seed_config()
        if not self.prompter.ask_yes_no("Enable Telegram?", default=False):
            cfg.telegram.enabled = False
            self._save_config(cfg)
            result.notes.append("telegram disabled")
            return result
        token_env = self.prompter.ask(
            "Env var name that holds your Telegram bot token",
            default=cfg.telegram.token_env or "TELEGRAM_BOT_TOKEN",
        )
        cfg.telegram.token_env = token_env
        cfg.telegram.enabled = True
        secret = self.prompter.ask_secret("Paste your Telegram bot token (or leave blank to set later)")
        if secret:
            self._merge_secret(token_env, secret)
            result.secrets_recorded.append(token_env)
        allowed_raw = self.prompter.ask(
            "Allowed Telegram user ids (comma-separated, blank for none)",
            default=",".join(str(u) for u in cfg.telegram.allowed_users),
        )
        allowed: list[int] = []
        for token in allowed_raw.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                allowed.append(int(token))
            except ValueError:
                result.errors.append(f"telegram.allowed_users: {token!r} is not a valid user id")
        cfg.telegram.allowed_users = allowed
        self._save_config(cfg)
        result.changed.append(str(self.home.config_file))
        return result

    def run_whatsapp(self) -> SectionResult:
        result = SectionResult(name="whatsapp")
        cfg = self._load_or_seed_config()
        if not self.prompter.ask_yes_no("Enable WhatsApp?", default=False):
            cfg.whatsapp.enabled = False
            self._save_config(cfg)
            result.notes.append("whatsapp disabled")
            return result
        backend = self.prompter.ask_choice(
            "WhatsApp backend",
            ["baileys", "cloud"],
            default_index=0,
        )
        cfg.whatsapp.backend = backend
        cfg.whatsapp.enabled = True
        if backend == "cloud":
            for slot in ("phone_number_id_env", "access_token_env", "verify_token_env"):
                env_name = self.prompter.ask(
                    f"Env var name for {slot.replace('_env', '')}",
                    default=getattr(cfg.whatsapp, slot),
                )
                setattr(cfg.whatsapp, slot, env_name)
                secret = self.prompter.ask_secret(f"Paste {slot.replace('_env', '')} (or blank to set later)")
                if secret:
                    self._merge_secret(env_name, secret)
                    result.secrets_recorded.append(env_name)
        else:
            result.notes.append(
                "Run `atulya-cortex whatsapp --pair-only` next to scan the QR code with the Baileys bridge."
            )
        self._save_config(cfg)
        result.changed.append(str(self.home.config_file))
        return result

    # ---- orchestrator -----------------------------------------------------

    def run_all(self, sections: Sequence[str] | None = None) -> list[SectionResult]:
        order = list(sections) if sections else list(SECTION_ORDER)
        results: list[SectionResult] = []
        for section in order:
            handler = getattr(self, f"run_{section}", None)
            if handler is None:
                results.append(SectionResult(name=section, errors=[f"unknown section {section!r}"]))
                continue
            try:
                results.append(handler())
            except NonInteractiveError as exc:
                results.append(
                    SectionResult(
                        name=section,
                        errors=[f"non-interactive prompter cannot answer: {exc}"],
                    )
                )
            except Exception as exc:
                logger.exception("setup section %s failed", section)
                results.append(SectionResult(name=section, errors=[str(exc)]))
        return results


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _default_base_url_for(provider: str) -> str:
    return {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "groq": "https://api.groq.com/openai/v1",
        "deepseek": "https://api.deepseek.com/v1",
        "openrouter": "https://openrouter.ai/api/v1",
    }.get(provider, "https://api.openai.com/v1")


def _default_model_for(provider: str) -> str:
    return {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-sonnet-20241022",
        "groq": "llama-3.1-70b-versatile",
        "deepseek": "deepseek-chat",
        "openrouter": "google/gemini-2.5-flash",
    }.get(provider, "gpt-4o-mini")


def _default_key_env_for(provider: str) -> str:
    return {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "groq": "GROQ_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }.get(provider, "OPENAI_API_KEY")


def _render_persona_template(
    *,
    name: str,
    voice: str,
    traits: Sequence[str],
    operator_name: str,
) -> str:
    template_path = Path(__file__).parent / "templates" / "persona.md"
    template = template_path.read_text(encoding="utf-8")
    traits_yaml = "\n".join(f"  - {t}" for t in traits) or "  - curious"
    voice_description = (
        f"You speak with a {voice} voice. You sound like a colleague who knows the operator's "
        "context and won't waste their time."
    )
    return (
        template.replace("{{name}}", name)
        .replace("{{voice}}", voice)
        .replace("{{traits_yaml}}", traits_yaml)
        .replace("{{operator_name}}", operator_name)
        .replace("{{voice_description}}", voice_description)
    )


__all__ = [
    "ConsolePrompter",
    "NonInteractiveError",
    "ProviderProbe",
    "Prompter",
    "ScriptedPrompter",
    "SECTION_ORDER",
    "SectionResult",
    "SetupWizard",
    "detect_providers",
]
