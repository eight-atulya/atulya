"""cortex.py — the executive: stimulus in, intent out.

The Cortex is the orchestrator. It threads together (in this order):

    Stimulus
      -> brainstem.reflexes  (filter / pair / sandbox; usually run upstream)
      -> memory.recall       (surface relevant memories)
      -> personality + skills (load voice + skill catalogue from disk)
      -> language.think      (LLM call with persona + skills + recollections)
      -> Action -> Intent    (envelope back to the matching channel)

Every collaborator is optional: a `Cortex` constructed with no collaborators
falls back to a deterministic "echo" mode (used by Batch 1 tests and by the
TUI smoke test before any LLM is wired in). When `language` *is* provided,
the cortex builds a real prompt and asks the LLM what to do.

Naming voice: `Cortex.reflect` is the load-bearing verb.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Sequence

from cortex.affect import Affect, score_text
from cortex.bus import (
    Action,
    ActionResult,
    Intent,
    Recollection,
    Reflex,
    SkillRef,
    Stimulus,
    Thought,
)
from cortex.conversation import ConversationStore, render_history_block
from cortex.episodes import EpisodeStore, render_episode_block
from cortex.peer_banks import peer_bank_id
from cortex.peer_memory import PeerMemoryBridge
from cortex.personality import Personality
from cortex.plasticity_prompt_memory import PlasticityPromptMemory
from cortex.semantic_facts import FactStore
from cortex.self_healing import SelfHealingEngine
from cortex.skills import Skills, render_skills_block
from cortex.tool_protocol import (
    ToolCall,
    ToolSpec,
    parse_tool_call,
    render_protocol_block,
    render_tool_result,
)

try:
    from cortex.language import Language, Utterance
except ImportError:  # pragma: no cover - language module is in this package
    Language = None  # type: ignore[assignment]
    Utterance = None  # type: ignore[assignment]


RecallCallable = Callable[[str, str, str | None], Awaitable[Sequence[Recollection]]]
"""(query, kind, bank_id) -> recollections.

`bank_id` is None when the active channel has no per-peer atulya-embed bank
(typically TUI or echo tests). Implementations should return [] when
`bank_id` is None unless they intentionally implement a global bank.
"""


def _default_recall_kinds() -> tuple[str, ...]:
    return ("episodic", "semantic")


def _channel_root(channel: str) -> str:
    """Strip the per-peer suffix from a channel id.

    Channel ids are conventionally `<channel>:<peer>` (`whatsapp:91xxx`,
    `tui:local`). For grouping transcripts by transport (one folder per
    channel kind) we only care about the prefix.
    """

    return channel.split(":", 1)[0] if channel else ""


class Cortex:
    """The executive of the brain.

    Construct with whatever collaborators you have:

    >>> Cortex()                                            # echo mode
    >>> Cortex(language=Language.with_lm_studio())          # local LLM
    >>> Cortex(language=lang, recall=memory.recall, skills=Skills([root]))

    `reflect(stimulus, reflex=None)` is the load-bearing call. It returns
    one `Intent` for the motor stack to dispatch.
    """

    def __init__(
        self,
        *,
        name: str = "atulya-cortex",
        language: Any | None = None,
        recall: RecallCallable | None = None,
        recall_kinds: Sequence[str] = (),
        recall_top_k: int = 4,
        personality: Personality | None = None,
        skills: Skills | None = None,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.4,
        max_tokens: int | None = 512,
        conversations: ConversationStore | None = None,
        history_turns: int = 8,
        history_char_budget: int = 1500,
        operator_label: str = "the operator",
        hand: Any | None = None,
        tool_specs: Sequence[ToolSpec] = (),
        max_actions: int = 3,
        action_only_channels: Sequence[str] = ("tui",),
        episodes: EpisodeStore | None = None,
        facts: FactStore | None = None,
        recall_facts_top_k: int = 8,
        recall_episodes_top_k: int = 3,
        auto_consolidate: "Callable[[str, str], Awaitable[Any]] | None" = None,
        peer_memory: PeerMemoryBridge | None = None,
        cortex_profile: str = "default",
        peer_bank_channels: frozenset[str] | None = None,
        self_healing: SelfHealingEngine | None = None,
        plasticity: PlasticityPromptMemory | None = None,
    ) -> None:
        self.name = name
        self._language = language
        self._recall = recall
        self._recall_kinds = tuple(recall_kinds) or _default_recall_kinds()
        self._recall_top_k = max(1, int(recall_top_k))
        self._personality = personality or Personality.default()
        self._skills_catalogue = skills
        self._provider = provider
        self._model = model
        self._temperature = float(temperature)
        self._max_tokens = max_tokens
        # Optional working memory. When None we keep the original stateless
        # behaviour so every existing test (echo mode, single-turn loop)
        # passes unchanged.
        self._conversations = conversations
        self._history_turns = max(0, int(history_turns))
        self._history_char_budget = max(0, int(history_char_budget))
        # Used to disambiguate "the operator" (the human running the brain
        # locally) from a remote contact talking to the brain over WhatsApp
        # or Telegram. The persona file usually anchors on the operator,
        # which is wrong for remote channels — we rewrite the framing in
        # the system prompt for non-`tui:` channels.
        self._operator_label = operator_label

        # The deliberation arc. When `hand` is wired the cortex closes the
        # loop "think -> act -> observe -> think" up to `max_actions`
        # iterations before forcing a final synthesis. With `hand=None`
        # we keep the original single-call behaviour so existing tests
        # and channels that don't want tool access stay simple.
        self._hand = hand
        self._tool_specs: tuple[ToolSpec, ...] = tuple(tool_specs)
        self._max_actions = max(1, int(max_actions))
        # Channels that may invoke tools at all. Default is `("tui",)` —
        # remote contacts cannot trigger shell commands by accident or
        # by social engineering. Add `"telegram"`, `"whatsapp"` etc. only
        # for trusted operator-only deployments.
        self._action_only_channels = tuple(action_only_channels)

        # The two halves of long-term memory. Both are optional so a
        # cortex built with `language=None` (echo mode) or in tests stays
        # zero-dependency. When wired:
        #   - `_episodes` records every turn (with affect tag and tool
        #     trace) so the consolidation pass has raw material.
        #   - `_facts` is read on EVERY system-prompt build and surfaces
        #     "what I know about this peer" so the brain genuinely
        #     remembers Anurag from one boot to the next.
        self._episodes = episodes
        self._facts = facts
        self._recall_facts_top_k = max(0, int(recall_facts_top_k))
        self._recall_episodes_top_k = max(0, int(recall_episodes_top_k))
        # Auto-consolidation hook: fire-and-forget after each turn for
        # non-TUI channels. Takes (channel, peer). The hook itself is
        # responsible for cooldown + min-episode gating; we just fire.
        # Without this hook WhatsApp/Telegram peers accumulate episodes
        # forever but never get semantic facts, because the only path
        # to `Sleep.consolidate` would be the TUI's /sleep command.
        self._auto_consolidate = auto_consolidate
        # Optional atulya-embed bridge: one bank id per (cortex profile, peer).
        self._peer_memory = peer_memory
        self._cortex_profile = (cortex_profile or "default").strip() or "default"
        self._peer_bank_channels = peer_bank_channels or frozenset()
        self._self_healing = self_healing
        self._plasticity = plasticity

    @property
    def has_language(self) -> bool:
        return self._language is not None

    async def reflect(
        self,
        stimulus: Stimulus,
        *,
        reflex: Reflex | None = None,
        peer_key: str | None = None,
    ) -> Intent:
        """Reflect on a single stimulus and return an Intent for the motor stack.

        `peer_key` opts this turn into the working-memory pipeline: prior
        turns from this (channel, peer) are loaded into the system prompt,
        and the new exchange is appended after the LLM call. Pass `None`
        (the default) to keep the cortex stateless — preserves the
        original behaviour for echo-mode tests and single-shot subagents.
        """

        if reflex is not None and reflex.decision == "deny":
            return Intent(
                action=Action(kind="noop", payload={}),
                channel=stimulus.channel,
                sender=stimulus.sender,
            )
        if reflex is not None and reflex.decision == "pair":
            return self._pairing_intent(stimulus)

        if self._language is None:
            return self._echo_intent(stimulus)

        # Per-peer atulya-embed bank (optional): stable id from cortex profile + peer.
        memory_bank_id: str | None = None
        bank_mental_model_prompt = ""
        if (
            peer_key
            and self._peer_memory is not None
            and self._peer_bank_channels
            and _channel_root(stimulus.channel) in self._peer_bank_channels
        ):
            memory_bank_id = peer_bank_id(self._cortex_profile, peer_key)
            await self._peer_memory.ensure_bank(memory_bank_id)
            bank_mental_model_prompt = await self._peer_memory.bank_mental_model_prompt(
                memory_bank_id,
                peer_key=peer_key,
                channel_root=_channel_root(stimulus.channel),
            )

        # Working memory: per (channel, peer) JSONL transcript.
        conv = None
        history: list[Any] = []
        if peer_key and self._conversations is not None and self._history_turns > 0:
            channel_root = _channel_root(stimulus.channel)
            conv = self._conversations.open(channel_root, peer_key)
            history = conv.recent(turns=self._history_turns, char_budget=self._history_char_budget)

        thought = await self.hold(stimulus, memory_bank_id=memory_bank_id)
        sandboxed = reflex is not None and reflex.decision == "sandbox"

        # Deliberation arc: when hand is wired AND this channel is allowed
        # to act AND the reflex didn't sandbox us, run the closed-loop
        # think -> act -> observe -> think pipeline. Otherwise fall back
        # to the single-call reflexive arc.
        if self._can_deliberate(stimulus.channel, sandboxed):
            reply_text, deliberation_log = await self._deliberate(
                thought,
                history=history,
                peer_key=peer_key,
                bank_mental_model_prompt=bank_mental_model_prompt,
            )
        else:
            reply_text = await self._think(
                thought,
                sandboxed=sandboxed,
                history=history,
                peer_key=peer_key,
                bank_mental_model_prompt=bank_mental_model_prompt,
            )
            deliberation_log = []

        if self._self_healing is not None:
            healed = await self._self_healing.heal_reply(
                language=self._language,
                stimulus_text=stimulus.text or "",
                draft_reply=reply_text,
                recollections=[r.text for r in thought.recollections],
                provider=self._provider,
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                channel=stimulus.channel,
                peer_key=peer_key,
            )
            reply_text = healed.text

        # Persist *after* the LLM call so a partial failure (timeout,
        # disconnect) doesn't leave us with a one-sided history that
        # confuses the next turn. We append both halves under the same lock.
        # Tool calls and results are appended too so the next turn's
        # working memory remembers what the brain *did*, not just what
        # it *said*.
        user_text = (stimulus.text or "").strip()
        if conv is not None:
            if user_text:
                conv.append("user", user_text)
            for entry in deliberation_log:
                conv.append(entry["role"], entry["content"], meta=entry.get("meta"))
            if reply_text:
                conv.append("assistant", reply_text)

        # Episodic memory: write a structured episode of *what just
        # happened* — the user text, the assistant reply, the tools
        # invoked, and an affect score. This is the raw material the
        # consolidation pass distils into semantic facts. Done after
        # the conversation append so on a partial failure we still have
        # working memory even if episode persistence trips.
        if peer_key and self._episodes is not None and (user_text or reply_text):
            try:
                self._episodes.append(
                    channel=_channel_root(stimulus.channel),
                    peer=peer_key,
                    user_text=user_text,
                    assistant_text=reply_text,
                    tools_used=tuple(
                        e.get("meta", {}).get("tool")
                        for e in deliberation_log
                        if e.get("meta", {}).get("phase") == "act"
                        and e.get("meta", {}).get("tool")
                    ),
                    affect=score_text(user_text or reply_text),
                )
            except Exception as exc:  # pragma: no cover - defensive
                # An episode-write failure must NEVER block the reply
                # from going out. We log and move on.
                import logging
                logging.getLogger(__name__).warning(
                    "cortex: episode persist failed for %s: %s", peer_key, exc
                )

        # Fire-and-forget consolidation. The Sleep engine has its own
        # cooldown + min-episode + min-salience gates, so this mostly
        # no-ops; when gates open it costs one LLM call in the
        # background without delaying the reply the peer is waiting on.
        # Wrapping in a task means a slow or failing consolidation
        # cannot back-pressure the reply path.
        if peer_key and self._auto_consolidate is not None:
            channel_root = _channel_root(stimulus.channel)
            try:
                import asyncio as _asyncio
                _asyncio.create_task(
                    self._auto_consolidate(channel_root, peer_key),
                    name=f"cortex-consolidate-{channel_root}-{peer_key}",
                )
            except RuntimeError:
                # Not inside a running loop (can happen in tests that
                # call reflect() via asyncio.run). Skip silently.
                pass

        if self._plasticity is not None and (user_text or reply_text):
            try:
                self._plasticity.record_turn(peer_key=peer_key, user_text=user_text, assistant_text=reply_text)
            except Exception:
                pass
            if self._plasticity.distill_enabled and self._language is not None:
                try:
                    import asyncio as _asyncio

                    _asyncio.create_task(
                        self._plasticity.distill_if_due(
                            language=self._language,
                            provider=self._provider,
                            model=self._model,
                            temperature=self._temperature,
                            max_tokens=self._max_tokens,
                            peer_key=peer_key,
                        ),
                        name=f"cortex-plasticity-distill-{_channel_root(stimulus.channel)}",
                    )
                except RuntimeError:
                    pass

        # Vector substrate: retain this turn into the peer's bank (async).
        if self._peer_memory is not None and memory_bank_id and (user_text or reply_text):
            try:
                import asyncio as _asyncio

                _asyncio.create_task(
                    self._peer_memory.retain_turn(stimulus, user_text, reply_text, memory_bank_id),
                    name=f"cortex-retain-{memory_bank_id[:32]}",
                )
            except RuntimeError:
                pass

        return Intent(
            action=Action(kind="reply", payload={"text": reply_text}),
            channel=stimulus.channel,
            sender=stimulus.sender,
        )

    def _can_deliberate(self, channel: str, sandboxed: bool) -> bool:
        """True when this stimulus is eligible for the closed-loop
        deliberation arc (hand wired, channel allowed, not sandboxed)."""

        if self._hand is None or not self._tool_specs:
            return False
        if sandboxed:
            return False
        return _channel_root(channel) in self._action_only_channels

    async def reflect_text(self, stimulus: Stimulus, *, peer_key: str | None = None) -> str:
        """Convenience for subagents and tests: return the LLM text directly."""

        intent = await self.reflect(stimulus, peer_key=peer_key)
        return str(intent.action.payload.get("text", ""))

    async def hold(self, stimulus: Stimulus, *, memory_bank_id: str | None = None) -> Thought:
        """Materialize a Thought with persona, recollections and skill catalogue."""

        recollections: list[Recollection] = []
        if self._recall is not None and stimulus.text:
            for kind in self._recall_kinds:
                try:
                    items = await self._recall(stimulus.text, kind, memory_bank_id)
                except Exception:
                    continue
                for item in items[: self._recall_top_k]:
                    recollections.append(item)
        skills = self._skills_catalogue.discover() if self._skills_catalogue else []
        return Thought(
            stimulus=stimulus,
            recollections=recollections,
            persona=self._personality.system_prompt_block(),
            skills=skills,
        )

    async def _think(
        self,
        thought: Thought,
        *,
        sandboxed: bool,
        history: list[Any] | None = None,
        peer_key: str | None = None,
        bank_mental_model_prompt: str = "",
    ) -> str:
        messages = self._build_messages(
            thought,
            sandboxed=sandboxed,
            history=history or [],
            peer_key=peer_key,
            bank_mental_model_prompt=bank_mental_model_prompt,
        )
        utt: Utterance = await self._language.think(  # type: ignore[union-attr]
            messages,
            provider=self._provider,
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return (utt.text or "").strip()

    async def _deliberate(
        self,
        thought: Thought,
        *,
        history: list[Any] | None,
        peer_key: str | None,
        bank_mental_model_prompt: str = "",
    ) -> tuple[str, list[dict[str, Any]]]:
        """Closed-loop deliberation arc — think, act, observe, repeat.

        Returns `(final_reply, deliberation_log)`. The log captures the
        intermediate `assistant`/`tool` turns so the caller can persist
        them into the working-memory transcript; the model's next
        encounter with this peer will then *remember what it did*, not
        just what it said.

        Bounded by `self._max_actions`; on overflow we synthesise a final
        plain-text answer from whatever was gathered so far. This matches
        how a person stops interrogating a problem and gives their best
        current answer when running out of patience or time.
        """

        messages = self._build_messages(
            thought,
            sandboxed=False,
            history=history or [],
            peer_key=peer_key,
            bank_mental_model_prompt=bank_mental_model_prompt,
            include_tools=True,
        )
        log: list[dict[str, Any]] = []

        for iteration in range(self._max_actions):
            utt: Utterance = await self._language.think(  # type: ignore[union-attr]
                messages,
                provider=self._provider,
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
            text = (utt.text or "").strip()
            call = parse_tool_call(text)
            if call is None:
                # Terminal: model is done acting and produced its reply.
                # We strip any leftover orphan tags defensively, then
                # return. No log entry for the assistant here — the
                # caller appends the final reply with role="assistant".
                return _strip_orphan_tags(text), log

            # The model decided to act. Append its full utterance as the
            # assistant turn so the next iteration sees its own intent,
            # then run the tool and append the result as a "tool" role
            # message. We use the bus Action/Hand contract directly so
            # this stays compatible with any future upgrade to the Hand
            # motor (allowlists, rate limits, dry-run mode).
            messages.append({"role": "assistant", "content": text})
            log.append(
                {
                    "role": "assistant",
                    "content": text,
                    "meta": {"phase": "act", "iteration": iteration, "tool": call.name},
                }
            )
            result_block = await self._invoke_hand(call)
            messages.append({"role": "user", "content": result_block})
            log.append(
                {
                    "role": "tool",
                    "content": result_block,
                    "meta": {"phase": "observe", "iteration": iteration, "tool": call.name},
                }
            )

        # Out of action budget. Force one final synthesis pass with an
        # explicit "no more tools, just answer" nudge — small models
        # otherwise often try one more call and run off the end of
        # whatever budget the channel allows.
        messages.append(
            {
                "role": "user",
                "content": (
                    "You have used your action budget. Now write your final reply "
                    "to the user using only what you already know. Do NOT emit any "
                    "<tool> tags."
                ),
            }
        )
        utt = await self._language.think(  # type: ignore[union-attr]
            messages,
            provider=self._provider,
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return _strip_orphan_tags((utt.text or "").strip()), log

    async def _invoke_hand(self, call: ToolCall) -> str:
        """Dispatch a parsed `<tool>` call through the `Hand` motor.

        Returns a `<tool_result>` block ready to splice into the next
        deliberation turn. We never raise here — failures become error
        results in the protocol so the model can decide whether to retry,
        try a different tool, or just answer with what it has.
        """

        intent = Intent(
            action=Action(kind="tool_call", payload=call.to_action_payload()),
            channel="cortex:deliberation",
            sender="cortex",
        )
        try:
            result: ActionResult = await self._hand.act(intent)  # type: ignore[union-attr]
        except Exception as exc:
            return render_tool_result(
                call.name,
                ok=False,
                output=None,
                detail=f"hand crashed: {type(exc).__name__}: {exc}",
            )
        if not result.ok:
            return render_tool_result(
                call.name,
                ok=False,
                output=result.artifact,
                detail=result.detail,
            )
        # `Hand` packs the actual tool output under `artifact["output"]`.
        return render_tool_result(call.name, ok=True, output=result.artifact.get("output"))

    def _build_messages(
        self,
        thought: Thought,
        *,
        sandboxed: bool,
        history: list[Any] | None = None,
        peer_key: str | None = None,
        bank_mental_model_prompt: str = "",
        include_tools: bool = False,
    ) -> list[dict[str, Any]]:
        system_parts: list[str] = []
        if bank_mental_model_prompt:
            system_parts.append(bank_mental_model_prompt)
        system_parts.append(thought.persona or self._personality.system_prompt_block())
        if self._plasticity is None or self._plasticity.time_context_enabled:
            time_note = self._time_context_note(thought.stimulus)
            if time_note:
                system_parts.append(time_note)
        if self._plasticity is not None:
            adaptive = self._plasticity.prompt_block(peer_key=peer_key)
            if adaptive:
                system_parts.append(adaptive)

        # Per-peer identity hint: persona files almost always anchor on
        # "the operator" (the human running the brain locally). When the
        # stimulus arrives over a remote channel, that framing is wrong —
        # the peer is *not* the operator and we shouldn't recite the
        # operator's name back at them. Without this hint, gemma-4-e2b
        # confidently told a remote WhatsApp contact "your name is Anurag"
        # because that's what the persona told it about the operator.
        identity_note = self._identity_note(thought.stimulus.channel, peer_key)
        if identity_note:
            system_parts.append(identity_note)

        if thought.skills:
            system_parts.append("Skills available:")
            system_parts.append(render_skills_block(list(thought.skills)))
        if thought.recollections:
            system_parts.append("Recollections (most relevant memories first):")
            system_parts.append(_render_recollections(thought.recollections))
        # Long-term semantic memory: durable facts about THIS peer the
        # brain learnt across past sessions. Always injected when present
        # because facts are short, high-signal, and grounded in real
        # past evidence. Without this block, the brain re-meets the same
        # person every session.
        if peer_key and self._facts is not None and self._recall_facts_top_k > 0:
            facts_block = self._facts.render_for_prompt(
                peer_key, top_k=self._recall_facts_top_k
            )
            if facts_block:
                system_parts.append(facts_block)
        # Episodic recall: top-k most salient recent episodes for this
        # peer. Different from `history` (verbatim last N turns) — these
        # are emotionally weighted snapshots that may be days old, the
        # kind of memories that "stick" without rehearsal.
        if (
            peer_key
            and self._episodes is not None
            and self._recall_episodes_top_k > 0
        ):
            channel_root = _channel_root(thought.stimulus.channel)
            top_eps = self._episodes.top_salient(
                channel=channel_root,
                peer=peer_key,
                n=self._recall_episodes_top_k,
            )
            ep_block = render_episode_block(top_eps)
            if ep_block:
                system_parts.append(ep_block)
        if history:
            history_block = render_history_block(history, label="Recent conversation with this peer")
            if history_block:
                system_parts.append(history_block)
        if include_tools and self._tool_specs:
            tools_block = render_protocol_block(self._tool_specs)
            if tools_block:
                system_parts.append(tools_block)
        if sandboxed:
            system_parts.append("This channel is sandboxed: do not call tools or delegate. Reply only with safe text.")
        system_text = "\n\n".join(p for p in system_parts if p.strip())

        user_text = thought.stimulus.text or ""
        return [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ]

    def _identity_note(self, channel: str, peer_key: str | None) -> str:
        """Return a per-peer identity correction for the system prompt.

        Empty for the local TUI (the operator IS the peer) and for
        unspecified peers (no working-memory mode); a short anchoring
        sentence otherwise. Kept tiny on purpose — small models follow
        short imperatives much better than long disclaimers.
        """

        if not peer_key or _channel_root(channel) == "tui":
            return ""
        return (
            f"You are speaking with a remote contact on {_channel_root(channel)} "
            f"({peer_key}). They are NOT {self._operator_label}. Do not assume their "
            "name, location, or relationship to you unless they tell you in this "
            "conversation."
        )

    def _time_context_note(self, stimulus: Stimulus) -> str:
        now = datetime.now(timezone.utc)
        received = stimulus.received_at
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        delta_s = max(0.0, (now - received).total_seconds())
        return (
            "Time context:\n"
            f"- now_utc: {now.isoformat()}\n"
            f"- weekday_utc: {now.strftime('%A')}\n"
            f"- message_received_utc: {received.isoformat()}\n"
            f"- receive_to_reflect_seconds: {delta_s:.3f}"
        )

    def _echo_intent(self, stimulus: Stimulus) -> Intent:
        text = (stimulus.text or "").strip()
        reply_text = f"hello back: {text}" if text else "hello back"
        return Intent(
            action=Action(kind="reply", payload={"text": reply_text}),
            channel=stimulus.channel,
            sender=stimulus.sender,
        )

    def _pairing_intent(self, stimulus: Stimulus) -> Intent:
        # Imported here to avoid a runtime cycle: _runtime imports Cortex.
        from cortex._runtime import pair_pending_message

        return Intent(
            action=Action(kind="reply", payload={"text": pair_pending_message(stimulus.channel, name=self.name)}),
            channel=stimulus.channel,
            sender=stimulus.sender,
        )

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"Cortex(name={self.name!r}, has_language={self.has_language})"


_ORPHAN_TAG_RE = re.compile(r"<(/?tool(?:_result)?[^>]*)>", flags=re.IGNORECASE)


def _strip_orphan_tags(text: str) -> str:
    """Drop stray `<tool>` / `<tool_result>` fragments from a final reply.

    Small models occasionally hallucinate a half-tag in a free-form reply
    after they've run out of action budget; sending that to the user is
    confusing. This is a last-mile cleanup, not a security boundary —
    the parser already rejected anything well-formed.
    """

    if not text:
        return text
    cleaned = _ORPHAN_TAG_RE.sub("", text)
    return cleaned.strip()


def _render_recollections(items: Sequence[Recollection]) -> str:
    lines: list[str] = []
    for r in items:
        snippet = r.text.strip().replace("\n", " ")
        if len(snippet) > 240:
            snippet = snippet[:237] + "..."
        lines.append(f"- [{r.kind}] {snippet}  (source={r.source}, score={r.score:.2f})")
    return "\n".join(lines)


__all__ = ["Cortex", "RecallCallable"]


def _stub_signature() -> dict[str, Any]:
    """Marker used by tests to verify which batch the cortex is at.

    Stays here so `tests/test_skeleton.py` keeps importing cleanly across
    batches; the values shift as we ship features.
    """

    return {"batch": 4, "real_loop": True}
