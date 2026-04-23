"""home.py — the single source of truth for cortex on-disk layout.

Every other cortex module asks `CortexHome` for its paths; nothing invents
its own location. This is what lets a user move their brain by setting
`ATULYA_CORTEX_HOME=/somewhere/else` and have every component follow.

Layout (default profile)::

    ~/.atulya/cortex/
    ├── config.toml                primary config (TOML)
    ├── .env                       secrets (loaded by env_loader)
    ├── persona.md                 voice / system-prompt seed
    ├── pairing/pairings.json      DMPairing store
    ├── state/state.json           silo StateStore
    ├── cache/llm/                 LLMCache
    ├── cache/embedding/           EmbeddingCache
    ├── skills/                    synced + user-authored markdown skills
    │   └── .bundled_manifest      mtime-aware sync ledger
    ├── whatsapp/session/          Baileys creds.json
    ├── cron/jobs.json             scheduled stimuli
    ├── conversations/             per-channel JSONL transcripts
    │   └── <channel>/<peer>.jsonl one file per (channel, peer)
    ├── logs/                      rotating log files
    ├── dashboard.lock             PID lock for `cortex dashboard`
    ├── current_profile            text file: name of the active profile
    └── profiles/<name>/           per-profile overlays (see Profile)

A non-default profile shifts these paths to `profiles/<name>/<...>`:
- `config.toml`, `persona.md`, `pairing/`, `state/`, `skills/`, `cron/`.

Caches (`cache/`), the WhatsApp Baileys session, the dashboard lock, and
logs stay shared across profiles to save disk and avoid Baileys re-pairing.

Naming voice: `CortexHome.resolve()` returns a frozen view of paths;
`CortexHome.bootstrap()` ensures every directory exists.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ENV_HOME: Final[str] = "ATULYA_CORTEX_HOME"
ENV_PROFILE: Final[str] = "ATULYA_CORTEX_PROFILE"

DEFAULT_HOME_RELATIVE: Final[str] = ".atulya/cortex"
DEFAULT_PROFILE_NAME: Final[str] = "default"
CURRENT_PROFILE_FILENAME: Final[str] = "current_profile"


def _expand(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(value)))).resolve()


def default_home_root() -> Path:
    """Compute the default home root, honoring `ATULYA_CORTEX_HOME` first."""

    env_value = os.environ.get(ENV_HOME)
    if env_value:
        return _expand(env_value)
    return _expand(Path.home() / DEFAULT_HOME_RELATIVE)


@dataclass(frozen=True)
class CortexHome:
    """Frozen, profile-aware view of every path the cortex uses on disk.

    Construct via `CortexHome.resolve()` (recommended) or directly with an
    explicit `root` and `profile_name`. The dataclass is frozen so callers
    cannot mutate path layout after the cortex is up; if you need a different
    profile, build a fresh `CortexHome` and rewire collaborators around it.
    """

    root: Path
    profile_name: str = DEFAULT_PROFILE_NAME

    @classmethod
    def resolve(
        cls,
        *,
        root: str | os.PathLike[str] | None = None,
        profile: str | None = None,
    ) -> "CortexHome":
        """Materialize a CortexHome from explicit args, env, then defaults.

        Precedence for `root`: explicit arg > `ATULYA_CORTEX_HOME` env > default.
        Precedence for `profile`: explicit arg > `ATULYA_CORTEX_PROFILE` env >
        `current_profile` file > "default".
        """

        resolved_root = _expand(root) if root is not None else default_home_root()
        # Explicit `profile` args (even empty string / bad names) must be
        # validated immediately so the caller learns about typos at the call
        # site instead of silently falling through to the default profile.
        if profile is not None:
            _validate_profile_name(profile)
            resolved_profile = profile
        else:
            resolved_profile = (
                os.environ.get(ENV_PROFILE) or _read_current_profile(resolved_root) or DEFAULT_PROFILE_NAME
            )
            # Env / file inputs may be junk from a previous version; refuse
            # rather than building a CortexHome with an unsafe profile path.
            _validate_profile_name(resolved_profile)
        return cls(root=resolved_root, profile_name=resolved_profile)

    @property
    def is_default_profile(self) -> bool:
        return self.profile_name == DEFAULT_PROFILE_NAME

    @property
    def profile_root(self) -> Path:
        """Where profile-scoped files live. For the default profile this is
        the home root; for any other profile it is `profiles/<name>/`."""

        if self.is_default_profile:
            return self.root
        return self.root / "profiles" / self.profile_name

    # ---- profile-scoped paths --------------------------------------------------

    @property
    def config_file(self) -> Path:
        return self.profile_root / "config.toml"

    @property
    def env_file(self) -> Path:
        return self.profile_root / ".env"

    @property
    def persona_file(self) -> Path:
        return self.profile_root / "persona.md"

    @property
    def pairing_dir(self) -> Path:
        return self.profile_root / "pairing"

    @property
    def pairing_store(self) -> Path:
        return self.pairing_dir / "pairings.json"

    @property
    def state_dir(self) -> Path:
        return self.profile_root / "state"

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def skills_dir(self) -> Path:
        return self.profile_root / "skills"

    @property
    def skills_manifest(self) -> Path:
        return self.skills_dir / ".bundled_manifest"

    @property
    def cron_dir(self) -> Path:
        return self.profile_root / "cron"

    @property
    def cron_jobs_file(self) -> Path:
        return self.cron_dir / "jobs.json"

    @property
    def conversations_dir(self) -> Path:
        # Profile-scoped: each profile has its own conversation history.
        # Sharing across profiles would silently leak private turns from
        # one persona into another (e.g. "work" answers showing up in
        # "play"); easier to start strict and relax later.
        return self.profile_root / "conversations"

    @property
    def episodes_dir(self) -> Path:
        """Episodic memory — one JSONL per (channel, peer).

        Episodic = "what happened" (hippocampus). Each turn becomes one
        episode with the user/assistant text, tools used, and an affect
        tag (valence/arousal/salience) so the consolidation pass can
        prioritise emotionally salient or surprising experiences when
        promoting them to semantic facts.
        """

        return self.profile_root / "episodes"

    @property
    def facts_dir(self) -> Path:
        """Semantic memory — one JSONL of facts per peer.

        Semantic = decontextualised durable knowledge (neocortex). Built
        slowly by `cortex/consolidation.py` reading from `episodes_dir`.
        Surfaces in every system prompt so the brain "knows" the peer.
        """

        return self.profile_root / "facts"

    @property
    def plasticity_dir(self) -> Path:
        """Compiled programs and optimization artifacts from `plasticity/`.

        Profile-scoped because prompt-tuned programs are personality-
        sensitive — the "work" profile should not reuse demos bootstrapped
        against "play" examples.
        """

        return self.profile_root / "plasticity"

    @property
    def consolidation_state_file(self) -> Path:
        """Cursor file: which episodes have already been distilled.

        Lives next to the state dir so a profile reset wipes it cleanly.
        Format: JSON `{ "<channel>:<peer>": "<last_consolidated_iso_ts>" }`.
        """

        return self.state_dir / "consolidation.json"

    # ---- shared paths (not profile-scoped) -------------------------------------

    @property
    def cache_root(self) -> Path:
        return self.root / "cache"

    @property
    def llm_cache_dir(self) -> Path:
        return self.cache_root / "llm"

    @property
    def embedding_cache_dir(self) -> Path:
        return self.cache_root / "embedding"

    @property
    def whatsapp_dir(self) -> Path:
        return self.root / "whatsapp"

    @property
    def whatsapp_session_dir(self) -> Path:
        return self.whatsapp_dir / "session"

    @property
    def whatsapp_mental_models_dir(self) -> Path:
        return self.whatsapp_dir / "mental-models"

    @property
    def whatsapp_memory_raw_dir(self) -> Path:
        return self.whatsapp_dir / "memory-raw"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def dashboard_lock(self) -> Path:
        return self.root / "dashboard.lock"

    @property
    def profiles_root(self) -> Path:
        return self.root / "profiles"

    @property
    def current_profile_file(self) -> Path:
        return self.root / CURRENT_PROFILE_FILENAME

    # ---- bootstrap -------------------------------------------------------------

    def bootstrap(self) -> "CortexHome":
        """Create every directory the cortex will write into.

        Idempotent; safe to call on every startup. Does NOT create files.
        """

        for d in self._directories_to_create():
            d.mkdir(parents=True, exist_ok=True)
        return self

    def _directories_to_create(self) -> tuple[Path, ...]:
        return (
            self.root,
            self.profile_root,
            self.pairing_dir,
            self.state_dir,
            self.skills_dir,
            self.cron_dir,
            self.conversations_dir,
            self.episodes_dir,
            self.facts_dir,
            self.plasticity_dir,
            self.cache_root,
            self.llm_cache_dir,
            self.embedding_cache_dir,
            self.whatsapp_dir,
            self.whatsapp_session_dir,
            self.whatsapp_mental_models_dir,
            self.whatsapp_memory_raw_dir,
            self.logs_dir,
            self.profiles_root,
        )

    def resolve_log_path(self, filename: str | os.PathLike[str]) -> Path:
        """Resolve a logging path: absolute paths pass through; relative paths
        are anchored under `logs_dir`."""

        candidate = Path(filename)
        if candidate.is_absolute():
            return candidate
        return self.logs_dir / candidate


def _read_current_profile(root: Path) -> str:
    f = root / CURRENT_PROFILE_FILENAME
    if not f.exists():
        return ""
    try:
        text = f.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return text


_FORBIDDEN_PROFILE_TOKENS: Final[tuple[str, ...]] = ("/", "\\", "..", "\0")


def _validate_profile_name(name: str) -> None:
    if not name:
        raise ValueError("profile name must be non-empty")
    for token in _FORBIDDEN_PROFILE_TOKENS:
        if token in name:
            raise ValueError(f"profile name {name!r} contains forbidden token {token!r}")
    if name.startswith("."):
        raise ValueError(f"profile name {name!r} must not start with '.'")


__all__ = [
    "CortexHome",
    "DEFAULT_HOME_RELATIVE",
    "DEFAULT_PROFILE_NAME",
    "ENV_HOME",
    "ENV_PROFILE",
    "default_home_root",
]
