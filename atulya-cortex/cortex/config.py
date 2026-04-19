"""config.py — typed, deep-merged, env-expanded TOML config.

`CortexConfig` is the schema; `load(home)` is the only function most callers
need. The flow on every load is:

    template defaults  (cortex/templates/config.toml)
        |  deep-merge over
        v
    user config        (home.config_file)
        |  expand ${VAR}
        v
    Pydantic validate  (extra="forbid" — unknown keys are errors)
        |
        v
    CortexConfig

This means a freshly-installed cortex always has every key, a user can keep
a tiny config that only overrides what they care about, and a typo in a key
fails loudly during `atulya-cortex doctor` instead of silently.

Saving uses `tomli_w` and the standard write-then-rename atomic pattern.
"""

from __future__ import annotations

import os
import tempfile
import tomllib
from copy import deepcopy
from importlib import resources
from pathlib import Path
from typing import Any, Final, Mapping

import tomli_w
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from cortex.home import CortexHome

# ---------------------------------------------------------------------------
# Section models
# ---------------------------------------------------------------------------


class _Section(BaseModel):
    """Common base: forbid extra keys so typos surface during `doctor`."""

    model_config = ConfigDict(extra="forbid")


class GeneralConfig(_Section):
    name: str = "atulya-cortex"
    peer: str = "local"
    # Display name of the human running this brain — surfaces in the system
    # prompt as "you are NOT <operator>" when a remote contact messages
    # over WhatsApp / Telegram, so the persona's local-operator anchoring
    # doesn't bleed into other channels.
    operator: str = ""
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        upper = (value or "").upper()
        if upper not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"log_level must be DEBUG|INFO|WARNING|ERROR|CRITICAL, got {value!r}")
        return upper


class ModelConfig(_Section):
    provider: str = "lm_studio"
    model: str = "google/gemma-3-4b"
    base_url: str = "http://localhost:1234/v1"
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=1, le=131072)
    timeout_s: float = Field(default=120.0, gt=0.0)
    max_retries: int = Field(default=1, ge=0, le=10)


class MemoryConfig(_Section):
    bank_id: str = "atulya-cortex"
    api_url: str = "http://localhost:8000"
    api_key_env: str = "ATULYA_API_KEY"
    # When true, each remote peer gets a dedicated atulya-embed bank id
    # ``cortex_<profile>_<peer>`` (see ``cortex.peer_banks.peer_bank_id``).
    # Banks are created on first interaction via ``acreate_bank``; recall +
    # retain use that id for vector memory alongside local JSONL stores.
    peer_banks_enabled: bool = False
    # Channel roots (prefix before ``:``) that participate in per-peer banks.
    peer_banks_channels: list[str] = Field(default_factory=lambda: ["whatsapp", "telegram"])
    # atulya-embed daemon profile name. Empty uses the active cortex profile name.
    embed_profile: str = ""
    recall_top_k: int = Field(default=4, ge=1, le=64)
    recall_kinds: list[str] = Field(default_factory=lambda: ["episodic", "semantic"])
    # Working memory bounds. These guard small local models from blowing
    # their context budget — gemma-4-e2b can't really afford more than a
    # handful of recent turns + a tight char cap. Crank up if you wire a
    # bigger model in.
    history_turns: int = Field(default=8, ge=0, le=64)
    history_char_budget: int = Field(default=1500, ge=0, le=32_000)
    # Long-term memory: how many semantic facts about THIS peer and
    # how many salient past episodes get spliced into the system prompt.
    # Facts are short and high-signal; episodes are richer but pricier.
    # Both default conservatively for small local models.
    recall_facts_top_k: int = Field(default=8, ge=0, le=64)
    recall_episodes_top_k: int = Field(default=3, ge=0, le=16)
    # Consolidation (the brain's "sleep" pass). Episode -> Fact distillation
    # is one LLM call so we gate it: only run when there are enough new
    # episodes AND enough total emotional salience, no faster than the
    # cooldown lets us.
    consolidation_min_episodes: int = Field(default=4, ge=1, le=200)
    consolidation_min_salience: float = Field(default=0.6, ge=0.0, le=10.0)
    consolidation_cooldown_s: float = Field(default=60.0, ge=0.0, le=86400.0)

    @field_validator("recall_kinds")
    @classmethod
    def _validate_kinds(cls, value: list[str]) -> list[str]:
        allowed = {"episodic", "semantic", "procedural", "emotional"}
        bad = [k for k in value if k not in allowed]
        if bad:
            raise ValueError(f"recall_kinds contains unknown kinds {bad}; allowed={sorted(allowed)}")
        return value

    @field_validator("peer_banks_channels")
    @classmethod
    def _normalize_peer_bank_channels(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for raw in value:
            s = (raw or "").strip().lower()
            if s and s not in out:
                out.append(s)
        return out


class TelegramConfig(_Section):
    enabled: bool = False
    token_env: str = "TELEGRAM_BOT_TOKEN"
    allowed_users: list[int] = Field(default_factory=list)
    poll_timeout_s: int = Field(default=30, ge=1, le=600)


class WhatsAppConfig(_Section):
    enabled: bool = False
    backend: str = "baileys"
    bridge_path: str = "scripts/whatsapp-bridge"
    phone_number_id_env: str = "WHATSAPP_PHONE_NUMBER_ID"
    access_token_env: str = "WHATSAPP_ACCESS_TOKEN"
    verify_token_env: str = "WHATSAPP_VERIFY_TOKEN"

    @field_validator("backend")
    @classmethod
    def _validate_backend(cls, value: str) -> str:
        if value not in {"baileys", "cloud"}:
            raise ValueError(f"whatsapp.backend must be baileys|cloud, got {value!r}")
        return value


class DashboardConfig(_Section):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=9120, ge=1, le=65535)


class BreathingConfig(_Section):
    max_actions_per_minute: int = Field(default=60, ge=1)
    max_tokens_per_minute: int = Field(default=60_000, ge=1)
    per_channel: dict[str, int] = Field(default_factory=dict)

    @field_validator("per_channel")
    @classmethod
    def _validate_per_channel(cls, value: dict[str, int]) -> dict[str, int]:
        for channel, rate in value.items():
            if rate < 0:
                raise ValueError(f"breathing.per_channel.{channel} must be >= 0, got {rate}")
        return value


class SkillsConfig(_Section):
    sync_on_start: bool = True
    allow_user_skills: bool = True


class DreamConfig(_Section):
    consolidation_enabled: bool = True
    consolidation_interval_s: int = Field(default=1800, ge=10)
    distill_enabled: bool = True


class LoggingConfig(_Section):
    file: str = "cortex.log"
    rotate_bytes: int = Field(default=5_242_880, ge=1024)
    rotate_backups: int = Field(default=3, ge=0, le=64)


class ToolsConfig(_Section):
    """The deliberation arc — when the cortex is allowed to act, not just talk.

    `enabled=False` keeps the v0 reflexive behaviour (one LLM call, no
    tool dispatch). When `enabled=True`, the cortex builds a `Hand` motor
    and runs a bounded think -> act -> observe loop on stimuli that
    arrive through `allowed_channels`.

    `safe_root` confines `read_file`/`write_file`/`edit_file` to a
    subtree (defaults to the user's home cortex profile so an over-eager
    LLM cannot stomp on `/etc`). `allowed_channels` defaults to TUI only
    so a stranger cannot DM the bot into running shell commands; flip
    `whatsapp` / `telegram` on explicitly when the operator is the only
    person who can reach the brain over those channels.
    """

    enabled: bool = False
    max_actions: int = Field(default=3, ge=1, le=10)
    allowed_channels: list[str] = Field(default_factory=lambda: ["tui"])
    safe_root: str = ""  # empty = $ATULYA_CORTEX_HOME
    bash_enabled: bool = True
    bash_timeout_s: float = Field(default=30.0, gt=0.0, le=600.0)
    web_fetch_enabled: bool = True
    web_fetch_timeout_s: float = Field(default=30.0, gt=0.0, le=600.0)
    web_fetch_max_bytes: int = Field(default=2_000_000, ge=1024, le=20_000_000)
    fs_write_enabled: bool = True


class CortexConfig(BaseModel):
    """Top-level config. Every section is required to be present after merge
    with template defaults; that guarantees `cfg.model.provider` is always
    safe to read."""

    model_config = ConfigDict(extra="forbid")

    general: GeneralConfig = Field(default_factory=GeneralConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    breathing: BreathingConfig = Field(default_factory=BreathingConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    dream: DreamConfig = Field(default_factory=DreamConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)


# ---------------------------------------------------------------------------
# Defaults / IO
# ---------------------------------------------------------------------------


TEMPLATE_PACKAGE: Final[str] = "cortex.templates"
TEMPLATE_FILENAME: Final[str] = "config.toml"


class ConfigError(RuntimeError):
    """Raised when config load/save fails in a way the caller should handle."""


def template_path() -> Path:
    """Resolve the bundled config template, regardless of install layout.

    Works whether the wheel was installed (`importlib.resources` finds the
    file inside the package) or the repo is checked out (we fall back to the
    source path for editable installs).
    """

    try:
        ref = resources.files(TEMPLATE_PACKAGE).joinpath(TEMPLATE_FILENAME)
        with resources.as_file(ref) as p:
            if p.exists():
                return p
    except (ModuleNotFoundError, FileNotFoundError, AttributeError):
        pass
    here = Path(__file__).parent / "templates" / TEMPLATE_FILENAME
    if here.exists():
        return here
    raise ConfigError(f"bundled template {TEMPLATE_FILENAME} not found")


def template_text() -> str:
    return template_path().read_text(encoding="utf-8")


def template_dict() -> dict[str, Any]:
    return tomllib.loads(template_text())


def default_config() -> CortexConfig:
    """Return a fully-populated `CortexConfig` from the bundled template."""

    return CortexConfig.model_validate(template_dict())


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge `override` into a deep copy of `base`. Lists are
    replaced wholesale (not concatenated); scalars from `override` win."""

    result: dict[str, Any] = deepcopy(dict(base))
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def expand_env(value: Any, env: Mapping[str, str] | None = None) -> Any:
    """Recursively expand `${VAR}` references inside any string leaf.

    Unknown vars are left literal (so `${TELEGRAM_BOT_TOKEN}` survives until
    the `.env` is loaded). Lists/dicts are walked. Non-string scalars pass
    through untouched.
    """

    source = env if env is not None else os.environ
    if isinstance(value, str):
        return os.path.expandvars(value) if "$" in value else value  # cheap fast-path
    if isinstance(value, list):
        return [expand_env(item, source) for item in value]
    if isinstance(value, dict):
        return {k: expand_env(v, source) for k, v in value.items()}
    return value


def load_raw(home: CortexHome) -> dict[str, Any]:
    """Return the merged-but-not-validated config dict (template + user + env).

    Useful for `config show` / migration tools that want the raw shape.
    """

    base = template_dict()
    user_path = home.config_file
    if user_path.exists():
        try:
            user_text = user_path.read_text(encoding="utf-8")
            user = tomllib.loads(user_text) if user_text.strip() else {}
        except OSError as exc:
            raise ConfigError(f"failed to read {user_path}: {exc}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{user_path} is not valid TOML: {exc}") from exc
    else:
        user = {}
    merged = deep_merge(base, user)
    return expand_env(merged)


def load(home: CortexHome) -> CortexConfig:
    """Load and validate the cortex config.

    Raises `ConfigError` with a human-readable message on any failure;
    callers (CLI subcommands, doctor) can surface it directly.
    """

    raw = load_raw(home)
    try:
        return CortexConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(home, exc)) from exc


def seed(home: CortexHome, *, force: bool = False) -> bool:
    """Copy the bundled template into `home.config_file` if missing.

    Returns True if the file was created, False if it already existed (or
    was overwritten because `force=True`). The caller is responsible for
    `home.bootstrap()` first.
    """

    target = home.config_file
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        return False
    target.write_text(template_text(), encoding="utf-8")
    return True


def save(home: CortexHome, config: CortexConfig) -> None:
    """Dump `config` to `home.config_file` atomically."""

    target = home.config_file
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = config.model_dump(mode="python")
    fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".config-", suffix=".toml.tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(tomli_w.dumps(payload).encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_raw(home: CortexHome, raw: Mapping[str, Any]) -> None:
    """Validate `raw` then save. Use this from `config set` to reject bad
    edits before touching disk."""

    config = CortexConfig.model_validate(raw)
    save(home, config)


def _format_validation_error(home: CortexHome, exc: ValidationError) -> str:
    lines = [f"config at {home.config_file} is invalid:"]
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        msg = err.get("msg", "")
        lines.append(f"  - {loc}: {msg}")
    return "\n".join(lines)


__all__ = [
    "BreathingConfig",
    "ConfigError",
    "CortexConfig",
    "DashboardConfig",
    "DreamConfig",
    "GeneralConfig",
    "LoggingConfig",
    "MemoryConfig",
    "ModelConfig",
    "SkillsConfig",
    "TelegramConfig",
    "WhatsAppConfig",
    "deep_merge",
    "default_config",
    "expand_env",
    "load",
    "load_raw",
    "save",
    "seed",
    "template_dict",
    "template_path",
    "template_text",
    "write_raw",
]
