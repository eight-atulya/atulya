"""_runtime.py — shared "build a real cortex from config" helpers.

`chat`, `whatsapp`, `telegram`, and the future `gateway` all need to do the
same boring work: open a `Language` from the model section of the config,
load `persona.md` and the skills directory, and return a wired-up `Cortex`.
This module is the single place that work lives so a config change never
benefits one channel and skips another.

Naming voice: `build_language_from_config` and `build_cortex_from_config`.
Both are synchronous; nothing here touches the network until a method is
called on the returned object.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from cortex.consolidation import Sleep
from cortex.conversation import ConversationStore
from cortex.cortex import Cortex
from cortex.episodes import EpisodeStore
from cortex.language import Language, Provider
from cortex.peer_memory import PeerMemoryBridge, build_peer_memory_bridge
from cortex.personality import Personality
from cortex.plasticity_prompt_memory import PlasticityPromptMemory, PlasticityPromptSettings
from cortex.self_healing import SelfHealingEngine, SelfHealingSettings
from cortex.semantic_facts import FactStore
from cortex.skills import Skills
from cortex.tool_protocol import ToolSpec
from motors.fine_motor_skills import Hand

if TYPE_CHECKING:
    from cortex.config import CortexConfig
    from cortex.home import CortexHome

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------


def build_language_from_config(config: "CortexConfig") -> Language:
    """Construct a `Language` driver from `config.model`.

    The active provider always sits at index 0 so it is the default; any
    fallback chain configured by the user (currently a v2 idea) would be
    appended after.
    """

    m = config.model
    provider_name = (m.provider or "lm_studio").lower()

    if provider_name == "lm_studio":
        provider = Provider.lm_studio(base_url=m.base_url, model=m.model)
    elif provider_name == "ollama":
        provider = Provider.ollama(base_url=m.base_url, model=m.model)
    elif provider_name == "vllm":
        provider = Provider.vllm(base_url=m.base_url, model=m.model)
    elif provider_name == "openai":
        provider = Provider.openai(api_key=os.environ.get(m.api_key_env, ""), model=m.model)
        provider.base_url = m.base_url or provider.base_url
    elif provider_name == "anthropic":
        provider = Provider.anthropic(api_key=os.environ.get(m.api_key_env, ""), model=m.model)
        provider.base_url = m.base_url or provider.base_url
    elif provider_name == "groq":
        provider = Provider.groq(api_key=os.environ.get(m.api_key_env, ""), model=m.model)
    elif provider_name == "together":
        provider = Provider.together(api_key=os.environ.get(m.api_key_env, ""), model=m.model)
    elif provider_name == "deepseek":
        provider = Provider.deepseek(api_key=os.environ.get(m.api_key_env, ""), model=m.model)
    elif provider_name == "openrouter":
        provider = Provider.openrouter(api_key=os.environ.get(m.api_key_env, ""), model=m.model)
    else:
        # Fallback: assume OpenAI-compatible endpoint with a custom base_url.
        provider = Provider(
            name=provider_name,
            base_url=m.base_url,
            api_key=os.environ.get(m.api_key_env, ""),
            default_model=m.model,
            timeout_s=m.timeout_s,
            max_retries=m.max_retries,
        )

    provider.timeout_s = m.timeout_s
    provider.max_retries = m.max_retries
    return Language([provider])


# ---------------------------------------------------------------------------
# Cortex
# ---------------------------------------------------------------------------


def build_cortex_from_config(
    home: "CortexHome",
    config: "CortexConfig",
    *,
    language: Language | None = None,
) -> Cortex:
    """Wire a `Cortex` with persona + skills from disk and the model section
    of the config. Pass `language=None` to start in echo mode (useful for
    smoke tests when no LLM is up)."""

    persona = Personality.load(home.persona_file) if home.persona_file.exists() else Personality.default()
    skills = Skills([home.skills_dir]) if home.skills_dir.exists() else None
    # Conversations: always wired even if the directory doesn't exist yet
    # (the store creates child folders on first append). This keeps every
    # channel symmetrical — TUI, WhatsApp, Telegram all get the same
    # working-memory behaviour without their CLI having to know the path.
    conversations = ConversationStore(home.conversations_dir)
    episodes = EpisodeStore(home.episodes_dir)
    facts = FactStore(home.facts_dir)
    operator_label = (config.general.operator or config.general.name or "the operator").strip() or "the operator"
    hand, tool_specs = _build_hand_from_config(home, config)

    # Auto-consolidation hook. Only wired when a real Language is present
    # (echo mode has no way to distil). Sharing one `Sleep` instance
    # across every reflect() means the per-peer cooldown + cursor state
    # works across channels — WhatsApp and TUI sessions on the same peer
    # don't redo each other's work.
    auto_consolidate = None
    if language is not None:
        sleep = build_sleep_from_config(home, config, language=language)

        async def _auto_consolidate(channel: str, peer: str) -> Any:
            # Never `force` in the auto path — gates are the whole point,
            # otherwise we'd burn an LLM call on every inbound ping.
            try:
                return await sleep.consolidate(channel=channel, peer=peer)
            except Exception:
                # Consolidation is best-effort; swallow so it never
                # back-pressures the reply path even in logs.
                return None

        auto_consolidate = _auto_consolidate

    peer_bridge: PeerMemoryBridge | None = build_peer_memory_bridge(
        config,
        cortex_profile=home.profile_name,
        whatsapp_mental_models_dir=home.whatsapp_mental_models_dir,
        whatsapp_memory_raw_dir=home.whatsapp_memory_raw_dir,
    )
    recall_fn = None
    if peer_bridge is not None:

        async def _recall_fn(query: str, kind: str, bank: str | None = None):
            return await peer_bridge.cortex_recall(query, kind, bank)

        recall_fn = _recall_fn

    self_healing = SelfHealingEngine(
        SelfHealingSettings(
            enabled=config.self_healing.enabled,
            max_retries=config.self_healing.max_retries,
            min_reply_chars=config.self_healing.min_reply_chars,
            judge_enabled=config.self_healing.judge_enabled,
            judge_provider=config.self_healing.judge_provider,
            judge_model=config.self_healing.judge_model,
            fallback_text=config.self_healing.fallback_text,
            telemetry_enabled=config.self_healing.telemetry_enabled,
        ),
        telemetry_file=home.logs_dir / "self-healing.jsonl",
    )
    plasticity = PlasticityPromptMemory(
        home.plasticity_dir / "prompt-memory.json",
        PlasticityPromptSettings(
            enabled=config.plasticity.enabled,
            per_user_enabled=config.plasticity.per_user_enabled,
            system_enabled=config.plasticity.system_enabled,
            max_directives=config.plasticity.max_directives,
            time_context_enabled=config.plasticity.time_context_enabled,
            distill_enabled=config.plasticity.distill_enabled,
            distill_min_updates=config.plasticity.distill_min_updates,
            distill_cooldown_s=config.plasticity.distill_cooldown_s,
            distill_max_versions=config.plasticity.distill_max_versions,
        ),
    )

    return Cortex(
        name=config.general.name,
        language=language,
        personality=persona,
        skills=skills,
        provider=None,  # use the language driver's default provider
        model=None,  # use the provider's default model
        temperature=config.model.temperature,
        max_tokens=config.model.max_tokens,
        recall=recall_fn,
        recall_kinds=tuple(config.memory.recall_kinds),
        recall_top_k=config.memory.recall_top_k,
        conversations=conversations,
        history_turns=config.memory.history_turns,
        history_char_budget=config.memory.history_char_budget,
        operator_label=operator_label,
        hand=hand,
        tool_specs=tool_specs,
        max_actions=config.tools.max_actions,
        action_only_channels=tuple(config.tools.allowed_channels),
        episodes=episodes,
        facts=facts,
        recall_facts_top_k=config.memory.recall_facts_top_k,
        recall_episodes_top_k=config.memory.recall_episodes_top_k,
        auto_consolidate=auto_consolidate,
        peer_memory=peer_bridge,
        cortex_profile=home.profile_name,
        peer_bank_channels=frozenset(config.memory.peer_banks_channels),
        self_healing=self_healing,
        plasticity=plasticity,
    )


def build_sleep_from_config(
    home: "CortexHome",
    config: "CortexConfig",
    *,
    language: Language,
) -> Sleep:
    """Construct the consolidation `Sleep` engine from config + a real Language.

    Separated from `build_cortex_from_config` because Sleep is only used
    by callers that explicitly want to consolidate (TUI `/sleep`, future
    cron). Building it lazily keeps the cold-start path cheap when
    nobody asks for consolidation.
    """

    return Sleep(
        language=language,
        episodes=EpisodeStore(home.episodes_dir),
        facts=FactStore(home.facts_dir),
        state_path=home.consolidation_state_file,
        min_episodes=config.memory.consolidation_min_episodes,
        min_total_salience=config.memory.consolidation_min_salience,
        cooldown_s=config.memory.consolidation_cooldown_s,
    )


# ---------------------------------------------------------------------------
# Hand / tool wiring — the deliberation arc
# ---------------------------------------------------------------------------


def _build_hand_from_config(
    home: "CortexHome",
    config: "CortexConfig",
) -> tuple[Hand | None, tuple[ToolSpec, ...]]:
    """Construct the `Hand` motor and its advertised tool catalogue.

    Returns `(None, ())` when `config.tools.enabled` is False so the
    cortex falls back to its purely reflexive (single LLM call) arc.

    `safe_root` defaults to the cortex's own home directory; this is
    intentionally generous (so the model can read its own logs and write
    notes) but tight enough that an over-eager LLM cannot escape into
    `/etc` or the user's repos. Operators wanting wider access set
    `safe_root` explicitly in config.
    """

    t = config.tools
    if not t.enabled:
        return None, ()

    safe_root_str = t.safe_root.strip() or str(home.root)
    hand = Hand(
        safe_root=safe_root_str,
        bash_timeout_s=t.bash_timeout_s,
        web_fetch_timeout_s=t.web_fetch_timeout_s,
        web_fetch_max_bytes=t.web_fetch_max_bytes,
    )

    specs: list[ToolSpec] = []
    if t.bash_enabled:
        specs.append(
            ToolSpec(
                name="bash",
                signature="command",
                description="run a shell command and return stdout/stderr/exit_code",
                example_args={"command": "date"},
            )
        )
    specs.append(
        ToolSpec(
            name="read_file",
            signature="path",
            description=f"read a UTF-8 text file under {safe_root_str}",
            example_args={"path": f"{safe_root_str}/persona.md"},
        )
    )
    if t.fs_write_enabled:
        specs.append(
            ToolSpec(
                name="write_file",
                signature="path, content",
                description="overwrite a file under safe_root with content",
                example_args={"path": f"{safe_root_str}/notes/scratch.md", "content": "..."},
            )
        )
        specs.append(
            ToolSpec(
                name="edit_file",
                signature="path, old, new",
                description="atomic str-replace a single occurrence; pass replace_all=true for global",
                example_args={"path": f"{safe_root_str}/notes/scratch.md", "old": "foo", "new": "bar"},
            )
        )
    if t.web_fetch_enabled:
        specs.append(
            ToolSpec(
                name="web_fetch",
                signature="url",
                description="HTTP GET a URL and return text body (no JS rendering)",
                example_args={"url": "https://example.com"},
            )
        )

    # Drop disabled tools from the Hand's registry too so a model that
    # tries them gets an "unknown tool" error rather than silent success.
    enabled_names = {s.name for s in specs}
    for name in list(hand.tool_names()):
        if name not in enabled_names:
            hand._tools.pop(name, None)  # noqa: SLF001 — single source of truth lives here.
    return hand, tuple(specs)


# ---------------------------------------------------------------------------
# Reply helpers shared across channel surfaces
# ---------------------------------------------------------------------------


def pair_pending_message(channel: str, *, name: str = "atulya-cortex") -> str:
    """Friendly "waiting on operator" reply for unpaired channels.

    Channel surfaces (whatsapp, telegram, future gateway) should send this
    text directly when a `Reflex(decision="pair")` is returned, instead of
    invoking the LLM. The operator approves the channel out of band with
    `atulya-cortex pairing approve <channel>`.
    """

    return (
        f"Hi — I'm {name}. This conversation is new to me, so I'm waiting on my "
        "operator to approve it. They'll see your message and either approve or "
        "decline. After approval I'll start replying for real."
    )


__all__ = [
    "build_cortex_from_config",
    "build_language_from_config",
    "pair_pending_message",
]
