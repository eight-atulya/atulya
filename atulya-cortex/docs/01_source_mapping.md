# 01 — Source Mapping

> **Purpose.** This is the file-by-file mining table for every cortex module. When
> a contributor opens `cortex/language.py` they should be able to look up "where
> did this pattern come from?" in seconds — and when they need to extend it, they
> should know exactly which upstream file to read for inspiration without having
> to re-explore three foreign codebases.

We do **not** vendor or import any of these projects. We **port patterns** —
naming, contracts, control-flow shape, security models, wire formats — into
semantically named Python files inside `atulya-cortex/`. Where another project
already ships an Atulya integration (notably `atulya-integrations/openclaw/`),
we leave that integration operational as a parallel path.

All paths below are absolute under `/home/atulya-agent/atulya-agent/`.

---

## Source repositories at a glance

| Project | Language | Why we mine it | Primary entry to read |
|---------|----------|----------------|------------------------|
| `hermes-agent/` | Python | The closest existing Python AI brain. Real channel adapters, real skill loop, real memory plugin contract, real built-in cron, real subagent spawn. Production-tested. | `hermes-agent/run_agent.py` (`AIAgent`, `run_conversation`) |
| `pi-mono/` | TypeScript | Best-in-class **multi-provider LLM unification** (`pi-ai`), **token-efficient streaming**, **differential TUI render**, **per-file mutation queue**, **subagent extension pattern**, **vLLM pod manager**. We port patterns into Python; we do not ship JS in cortex. | `pi-mono/packages/ai/src/stream.ts`, `pi-mono/packages/agent/src/agent-loop.ts` |
| `openclaw/` | TypeScript | **DM pairing** security model, **WhatsApp** + **Telegram** wire formats, **multi-agent routing** (peer → workspace), plugin manifest contract. We read shapes only. The existing **atulya-integrations/openclaw** plugin remains the parallel ingress for users already on OpenClaw. | `openclaw/src/security/dm-policy-shared.ts`, `openclaw/extensions/whatsapp/`, `openclaw/extensions/telegram/` |
| `atulya/atulya/` (atulya-embed Python SDK) | Python | The **memory substrate**. `AtulyaEmbedded(profile=...)` is what `cortex/memory/` wraps. Zero changes to atulya-api in v1. | `atulya/atulya/atulya/embedded.py`, `atulya/atulya/atulya/api_namespaces.py` |

---

## Cortex-module ↔ source-file map

The leftmost column is the file we will create (or fill, since most exist as
empty 0-byte placeholders). Each row tells the implementer **exactly** which
upstream file to study before writing a single line.

### `cortex/cortex.py` — main loop

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| hermes | `hermes-agent/run_agent.py` | `588-900` (`AIAgent.__init__`), `8668-11852` (`run_conversation`) | Provider selection, history tracking, multi-iteration tool loop, optional streaming. |
| hermes | `hermes-agent/model_tools.py` | `196+` (`get_tool_definitions`), `421+` (`handle_function_call`) | Resolves tool schemas + dispatches calls. |
| pi-mono | `pi-mono/packages/agent/src/agent-loop.ts` | `155-232` (`runLoop`), `336-441` (`executeToolCalls`), `475-525` (`prepareToolCall`) | Cleanest loop body in the wild — stream → tool calls → results → repeat. |

**Port note.** Cortex's loop is a hybrid: hermes' Python ergonomics + pi-mono's
discriminated-union event stream + our biomimetic naming. Personality / skills /
language are pulled in as collaborators, not embedded.

### `cortex/language.py` — multi-provider LLM

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| pi-mono | `pi-mono/packages/ai/src/stream.ts` | `25-59` (`stream`, `complete`, `streamSimple`, `completeSimple`) | Single entry point that resolves `model.api` and dispatches. |
| pi-mono | `pi-mono/packages/ai/src/api-registry.ts` | `23-82` (`ApiProvider`, `registerApiProvider`, `getApiProvider`) | The registry pattern itself — `Model.api` string → registered provider. |
| pi-mono | `pi-mono/packages/ai/src/types.ts` | `135-139` (`StreamFunction`), `233-237` (`Context`), `247-259` (`AssistantMessageEvent`), `388-412` (`Model<TApi>`) | Discriminated-union streaming contract we mirror in Python (TypedDict + Literal). |
| pi-mono | `pi-mono/packages/ai/src/providers/anthropic.ts` | `216+` (`streamAnthropic`) | Concrete provider shape — what an adapter has to satisfy. |
| pi-mono | `pi-mono/packages/ai/src/providers/register-builtins.ts` | `168-210` (`createLazyStream`), `345-426` (registration), `433` (`registerBuiltInApiProviders`) | Lazy provider import (return stream object before module finishes loading). |
| hermes | `hermes-agent/agent/auxiliary_client.py` | `1-120` (`call_llm`, resolution order) | Real-world fallback ladder across OpenRouter / Nous / Codex / Anthropic / custom endpoints. |
| atulya-embed | `atulya/atulya/atulya/embedded.py` | (full file) | Reuse the same env vars / API-key resolution so cortex and atulya-embed share configuration. |

**Provider list (v1).** LM Studio (default, `gemma-3-4b`), Ollama, OpenAI, Anthropic, Google
Gemini, Groq, OpenRouter. Selection rule, in order:
`ATULYA_CORTEX_LLM_PROVIDER` env → per-bank disposition (via atulya-embed) →
`lmstudio:gemma-3-4b`.

### `cortex/personality.py` — persona loader

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| hermes | `hermes-agent/agent/prompt_builder.py` | (full file) | `build_skills_system_prompt`, persona slot. |
| hermes | `hermes-agent/skills/dogfood/SKILL.md` | `1-9` | YAML frontmatter shape (`name`, `description`, `version`, optional `metadata`/`hermes` tags). |

**Port note.** Persona is one markdown file with YAML frontmatter — same shape as
hermes' `SOUL.md` but located inside `atulya-cortex/life/01_self/01_identity/`
so the brain literally reads its own identity from disk.

### `cortex/skills.py` — discover skills, expose as tools

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| hermes | `hermes-agent/agent/skill_utils.py` | `52-86` (`parse_frontmatter`) | YAML frontmatter parser with safe loader + fallback. |
| hermes | `hermes-agent/tools/skills_tool.py` | `1-66` (header) | The `SKILL.md` directory layout convention; `skills_list` / `skill_view` / `skill_manage` tool surface. |
| hermes | `hermes-agent/agent/prompt_builder.py` | (`build_skills_system_prompt`) | Index of skills injected via system prompt (progressive disclosure). |
| pi-mono | `pi-mono/packages/coding-agent/src/core/extensions/types.ts` | `370-405` (`ToolDefinition`) | The exact tool surface shape we expose to the LLM. |

**Port note.** Skills are `BRAIN.md` files already on disk under
`atulya-cortex/life/03_systems/03_workflows/`. **Zero new schema.** We parse the
frontmatter and treat the body as the skill instructions.

### `sensors/tui.py` — terminal sensor

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| pi-mono | `pi-mono/packages/tui/src/tui.ts` | `217-221` (`previousLines`), `888-1204` (`doRender`, diff scan, ANSI synchronized output `\x1b[?2026h/l`) | The differential redraw algorithm (cursor motion + `\x1b[2K` clear + only changed rows). Port to Python on top of `rich`. |
| hermes | `hermes-agent/cli.py` | `9899+` (`prompt_toolkit.Application`), `10306+` (`main`) | Interactive REPL pattern with prompt_toolkit. We default to `rich` instead of prompt_toolkit (smaller dep), but study hermes' command palette / streaming hooks. |

**Default backend.** Rich + custom asyncio loop. Port pi-mono's diff-render
algorithm verbatim into Python; do not reach for `Textual` (too heavy for v1).

### `sensors/telegram.py` — telegram sensor

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| hermes | `hermes-agent/gateway/platforms/telegram.py` | `199+` (`TelegramAdapter`), `616-775+` (`connect`, long-poll vs webhook) | Adapter shape using `python-telegram-bot`. PTB Application, handlers (text/command/callback/media), graceful reply chunking. |
| hermes | `hermes-agent/gateway/platforms/telegram_network.py` | (full file) | Network fallbacks (Telegram is fragile in restricted networks). |
| openclaw | `openclaw/extensions/telegram/src/monitor.ts` | `24-80+` (polling/webhook runtimes) | grammY's monitor loop — confirms our shape choice. |
| openclaw | `openclaw/extensions/telegram/src/conversation-route.ts` | `27-120+` (`resolveTelegramConversationRoute`) | How peer / chat / thread map to a routed agent session. |
| openclaw | `openclaw/extensions/telegram/src/outbound-adapter.ts` | `22-100+` | HTML chunking + media sequencing. |

**Default backend.** `python-telegram-bot` (same as hermes — large, stable,
well-documented).

### `sensors/whatsapp.py` — whatsapp sensor

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| openclaw | `openclaw/extensions/whatsapp/src/inbound/monitor.ts` | `90-200+` (`attachWebInboxToSocket`) | Inbound handler shape. |
| openclaw | `openclaw/extensions/whatsapp/src/inbound/types.ts` | `38-77` (`WebInboundMessage`) | Normalized inbound envelope. |
| openclaw | `openclaw/extensions/whatsapp/src/session.ts` | `120-170` (`createWaSocket`) | Baileys socket creation. **Backend: Baileys (Node).** |
| openclaw | `openclaw/extensions/whatsapp/src/login.ts` | `10-62` (`loginWeb`) | QR-based pairing, creds under account `authDir`. |
| openclaw | `openclaw/extensions/whatsapp/src/outbound-adapter.ts` | `29-109` (`whatsappOutbound`) | Outbound `ChannelOutboundAdapter` shape. |
| openclaw | `openclaw/extensions/whatsapp/src/inbound/access-control.ts` | `28-196` (`checkInboundAccessControl`) | Pairing-policy enforcement at the WhatsApp boundary. |
| hermes | `hermes-agent/gateway/platforms/whatsapp.py` | `103+` (`WhatsAppAdapter`), `261-442+` (`_start_bridge`), `536-670+` (`send`) | Reference for "Python wrapping a Node bridge subprocess" pattern (hermes uses whatsapp-web.js; openclaw uses Baileys). |

**Backend decision (v1, locked here).** We ship **two** backends behind a
`WhatsAppBackend` Protocol:
1. **Baileys subprocess** (default for dev) — fast onboarding, QR pairing,
   no Meta business account required. Mirrors openclaw exactly.
2. **WhatsApp Cloud API** (recommended for prod) — official Meta API, requires
   business onboarding but immune to bans. Direct HTTP, no subprocess.

The choice is one config flag. Backend churn is the #1 risk in this module —
the Protocol guarantees we can swap without touching `sensors/whatsapp.py`'s
caller.

### `sensors/hearing.py` — voice / mic sensor (placeholder for v1)

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| atulya-cortex | `atulya/atulya-cortex/sensors/hearing.py` (existing 0-byte placeholder) | — | Define the contract; body raises `NotImplementedError("hearing.py: v2")`. |

We declare the interface for future continuity but do not ship a mic in v1.

### `motors/messaging.py` — channel egress

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| openclaw | `openclaw/src/channels/plugins/types.adapters.ts` | `ChannelOutboundAdapter` (re-exported from `outbound.types.js`) | Outbound `ReplyPayload` shape — text + media + buttons + chunking metadata. |
| hermes | `hermes-agent/gateway/platforms/base.py` | `1655-1745` (`handle_message`), `_send_with_retry` in subclasses | Per-platform send semantics with retry. |

**Port note.** A `Reply` motor sees the channel id baked into the inbound
`Stimulus` envelope and routes the egress to the matching sensor's
`Motor`-side method.

### `motors/voice.py` — TTS

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| (none) | — | — | Default to system `say` (macOS) / `espeak` (linux); optional ElevenLabs adapter for cloud TTS. Direct subprocess; no upstream pattern needed. |

### `motors/hand.py` — tool execution

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| pi-mono | `pi-mono/packages/coding-agent/src/core/tools/bash.ts` | `33-36` (`bashSchema`), `75-119` (`createLocalBashOperations`) | Detached shell with timeout, abort signal, kill-tree on cancel. |
| pi-mono | `pi-mono/packages/coding-agent/src/core/tools/read.ts` | `17-21` (`readSchema`) | Read-with-offset/limit shape. |
| pi-mono | `pi-mono/packages/coding-agent/src/core/tools/edit.ts` | `31-51` (`editSchema`) | Multi-edit shape with `oldText`/`newText` pairs. |
| pi-mono | `pi-mono/packages/coding-agent/src/core/tools/write.ts` | `14-17` (`writeSchema`) | File write shape. |
| pi-mono | `pi-mono/packages/coding-agent/src/core/tools/file-mutation-queue.ts` | `15-38` (`withFileMutationQueue`) | **Per-file mutation lock — different files run in parallel, same file serializes.** Direct port. |
| pi-mono | `pi-mono/packages/coding-agent/examples/extensions/sandbox/index.ts` | (full file) | Optional OS-level sandboxing — informs `brainstem/reflexes.py` policy. |
| openclaw | `openclaw/src/agents/sandbox/constants.ts` | `13-28` (`DEFAULT_TOOL_ALLOW`), `31-38` (`DEFAULT_TOOL_DENY`) | Tool allow/deny defaults — copy values verbatim, then add cortex-specific ones. |

### `motors/movement.py` — subagent spawn

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| hermes | `hermes-agent/tools/delegate_tool.py` | `265-425` (`_build_child_agent`), `427-537+` (`_run_single_child`), `680+` (`delegate_task`) | Build a child agent with `ephemeral_system_prompt`, `skip_memory=True`, restricted toolsets, `quiet_mode=True`; serial + parallel modes; heartbeat. |
| pi-mono | `pi-mono/packages/coding-agent/examples/extensions/subagent/index.ts` | `1-13`, `211+`, `433+` | Single / parallel / chain modes; spawning subprocesses for true isolation. |

### `brainstem/heartbeat.py` — cron

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| hermes | `hermes-agent/cron/scheduler.py` | `1-120+` (`tick`, helpers) | Async cron loop, file lock under home dir, deterministic job persistence. |
| hermes | `hermes-agent/cron/jobs.py` | (full file) | Job persistence primitives. |
| hermes | `hermes-agent/tools/cronjob_tools.py` | (full file) | The user-facing tool surface for managing cron from inside the agent. |

### `brainstem/breathing.py` — token / rate budget

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| pi-mono | `pi-mono/packages/ai/src/types.ts` | `177-190` (`Usage`, nested `cost`) | Per-call usage shape we'll mirror as a Pydantic model. |
| pi-mono | `pi-mono/packages/ai/src/models.ts` | `39-46` (`calculateCost`) | Per-million-token math; integer-cents accounting. |
| pi-mono | `pi-mono/packages/coding-agent/src/modes/interactive/components/footer.ts` | `65-123` | Session-level aggregation pattern (sum assistant `usage.*`). |
| pi-mono | `pi-mono/packages/mom/src/agent.ts` | `487-576` (`runState.totalUsage`) | Run-scoped accumulation pattern. |
| hermes | `hermes-agent/agent/context_compressor.py` | `234+` (`ContextCompressor`) | Auto-compaction trigger: when context use crosses a threshold, summarize-and-prune. We adopt the trigger but compress into atulya-embed memory instead of in-prompt summary. |

### `brainstem/reflexes.py` — pre-cortex guards

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| openclaw | `openclaw/src/security/dm-policy-shared.ts` | `105-196` (`resolveDmGroupAccessDecision`) | The default-pairing policy decision tree. |
| openclaw | `openclaw/src/pairing/pairing-challenge.ts` | `24-48` (`issuePairingChallenge`) | Challenge issuance + `upsertPairingRequest`. |
| openclaw | `openclaw/src/pairing/pairing-store.ts` | `45-61` (`PairingStore`, `AllowFromStore`), `81-111` (path resolvers) | On-disk JSON pairing/allowlist store, per-channel + per-account. |
| openclaw | `openclaw/src/cli/pairing-cli.ts` | `107-165` (`approveChannelPairingCode`) | The operator approval flow we mirror as `python -m atulya_cortex pair approve`. |
| openclaw | `openclaw/src/agents/sandbox/runtime-status.ts` | `16-24` (`shouldSandboxSession`), `128-187` (`formatSandboxToolPolicyBlockedMessage`) | The `non-main` sandbox decision + user-visible block message. |
| openclaw | `openclaw/src/agents/sandbox/tool-policy.ts` | `211-262` (`resolveSandboxToolPolicyForAgent`), `180-203` (`classifyToolAgainstSandboxToolPolicy`) | Allow/deny merge + per-tool classification. |

### `brainstem/router.py` — stimulus → cortex bus

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| hermes | `hermes-agent/gateway/run.py` | `594+` (`GatewayRunner`), `2951+` (`_handle_message`), `3802+` (`_handle_message_with_agent`) | Owns adapter set, session store, cached agent per session, wires `adapter.set_message_handler(self._handle_message)`. |
| openclaw | `openclaw/src/routing/resolve-route.ts` | `610-692+` (`resolveAgentRoute`) | Peer + binding → resolved (`agentId`, `sessionKey`) tuple. |
| openclaw | `openclaw/src/routing/session-key.ts` | `93-114` (`buildAgentSessionKey`), `129+` (`buildAgentPeerSessionKey`) | Deterministic session-key construction. |

### `memory/hippocampus.py` — encode

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| atulya-embed | `atulya/atulya/atulya/embedded.py` | (full file — `AtulyaEmbedded.retain`) | Direct adapter. We pass the retain payload through with the right tags. |

### `memory/recall.py` — retrieve

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| atulya-embed | `atulya/atulya/atulya/embedded.py` | (`AtulyaEmbedded.recall`) | Direct adapter. Post-trim to `recallTopK`; budget knobs map to atulya-embed budget enum. |

### `memory/working_memory.py` — in-process LRU

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| (none) | — | — | Pure stdlib (`collections.OrderedDict`-backed LRU + bounded conversation buffer). The only memory store that does NOT round-trip atulya-embed. |

### `memory/episodic.py` / `semantic.py` / `procedural.py` — typed routers

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| atulya-embed | `atulya/atulya/atulya/embedded.py`, `api_namespaces.py` | `MentalModelsAPI`, `DirectivesAPI`, fact / observation tags | Thin wrappers around `hippocampus.encode` / `recall.recall` with `kind` baked in. |
| atulya monorepo | `atulya/BRAIN.md` | (full file — section "Knowledge layers") | The canonical definition of episodic vs semantic vs procedural memory and what each is FOR. Read before deciding what goes in which router. |

### `memory/emotional.py` — disposition

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| atulya-embed | `atulya/atulya/atulya/embedded.py`, `api_namespaces.py` | bank disposition fields | Read-only adapter onto bank disposition. |

### `silo/llm_cache.py` — completion cache

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| (none) | — | — | Diskcache-backed content-addressed cache keyed by `(provider, model, prompt_hash, temperature, seed)`. No upstream we want to copy. |

### `silo/embedding_cache.py` — embedding cache

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| (none) | — | — | Same shape as `llm_cache.py`, keyed on `(model, text_hash)`. |

### `silo/state.py` — durable per-bank conversation state

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| atulya-embed | `atulya/atulya/atulya/embedded.py` | daemon lifecycle | Reuse the same pg0 daemon when available; sqlite fallback otherwise. |

### `quantum/coherence.py` — KV / prefix cache

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| (none) | — | — | The trick is **not** code — it's prompt construction discipline. Keep the system prompt + persona + recalled-memories byte-identical across consecutive turns; only the trailing user message changes. llama.cpp / LM Studio reuse the KV cache automatically when prompts share a prefix. We add the **measurement** (TTFT delta vs no-coherence baseline) and the **post-pass** that strips control tokens (`<|channel|>`-style) before any text crosses into `memory/`. |

### `quantum/entanglement.py` — background recall prefetch

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| pi-mono | `pi-mono/packages/agent/src/agent-loop.ts` | `393-440` (`executeToolCallsParallel`) | Concurrency primitive. Apply to recall prefetch instead of tool execution. |

### `quantum/superposition.py` — speculative tool execution

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| pi-mono | `pi-mono/packages/coding-agent/src/core/tools/file-mutation-queue.ts` | `15-38` (`withFileMutationQueue`) | The serialization pattern that lets us speculatively READ files in parallel without ever speculatively WRITING. |
| pi-mono | `pi-mono/packages/agent/src/agent-loop.ts` | `393-440` (`executeToolCallsParallel`) | Parallel start; we add an `idempotent` decorator and only speculate decorated tools. |

### `quantum/decoherence.py` — speculation rollback

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| (none) | — | — | Pure stdlib (tempfile cleanup, cache eviction). Pattern is "every speculation owns its scratch dir, decoherence wipes the scratch dir". |

### `dream/consolidation.py` — heartbeat-triggered mental model refresh

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| atulya | `atulya/atulya-api/atulya_api/engine/memory_engine.py` (`refresh_mental_model`) | (full method) | The feature we shipped last sprint. Cortex calls it in **delta mode** for every mental model in every bank on each heartbeat tick (default: every 6h). Empty-render guarded; source-query tracked. |

### `dream/skill_distill.py` — distill new skills

| Source | File | Lines | What to copy |
|--------|------|-------|--------------|
| hermes | `hermes-agent/tools/skills_tool.py` | `1-66` (header convention) | Skill markdown layout. |
| hermes | `hermes-agent/agent/skill_utils.py` | `52-86` (`parse_frontmatter`) | Frontmatter we will EMIT (not just parse). |

The artifact distilled is a `BRAIN.md` file under
`atulya-cortex/life/40_knowledge/17_lessons_learned/`. The next agent **literally
reads what the prior agent learned** because skills load from disk. This is
what makes the brain self-evolving.

---

## Wire format / contract anchors (do not deviate)

These are the small shapes that **must be byte-stable** across all of cortex.
If any later batch needs to extend them, that change lands in `cortex/bus.py`
and gets called out in the PR description.

| Type | Defined in (cortex) | Source pattern |
|------|---------------------|----------------|
| `Stimulus` | `cortex/bus.py` | hermes `MessageEvent` (`gateway/platforms/base.py`) + openclaw `WebInboundMessage` (`extensions/whatsapp/src/inbound/types.ts:38-77`) |
| `Action` / `Intent` | `cortex/bus.py` | pi-mono `AssistantMessage.content[]` discriminated union (`packages/ai/src/types.ts:177-211`) |
| `Recollection` | `cortex/bus.py` | atulya-embed `recall` response shape |
| `Reflex` | `cortex/bus.py` | openclaw security decision tree (`src/security/dm-policy-shared.ts`) |
| Skill (on disk) | `cortex/skills.py` | hermes `SKILL.md` YAML frontmatter |
| Tool definition (LLM-facing) | `motors/hand.py` | pi-mono `ToolDefinition` (`packages/coding-agent/src/core/extensions/types.ts:370-405`) |
| Provider streaming chunk | `cortex/language.py` | pi-mono `AssistantMessageEvent` (`packages/ai/src/types.ts:247-259`) |
| Pairing store | `brainstem/reflexes.py` | openclaw `PairingStore` JSON files |

---

## What we explicitly do NOT port

- **OpenClaw's UI / A2UI surface.** v1 is text channels (TUI / Telegram / WhatsApp).
  A2UI is interesting future work but adds canvas rendering complexity that
  detracts from the small-model focus.
- **pi-mono's vLLM pod manager.** Reviewers will ask about scale. Our v1 answer
  is: small local model first, multi-provider fallback for everything else; pod
  management belongs in a future `motors/pods.py`, not v1.
- **hermes' Honcho-style dialectic user model.** atulya-embed already gives us
  durable user memory; we do not need a second user model.
- **openclaw's plugin-package contract.** v1 cortex is the only cortex; plugins
  re-emerge naturally if the project grows.

---

## Default decisions (locked in v1)

These were called out as "deferred to batch 0" in the plan; they are now
locked.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **WhatsApp backend** | Baileys subprocess (default), WhatsApp Cloud API (opt-in for prod). Pluggable behind `WhatsAppBackend` Protocol. | Baileys: zero-friction onboarding (QR pair). Cloud API: ban-immune for prod. Two backends behind one Protocol mitigates the #1 risk in this module. |
| **TUI base** | `rich` + custom asyncio loop. Port the diff-render algorithm verbatim from `pi-mono/packages/tui/src/tui.ts`. | Rich is ubiquitous and lightweight. `Textual` is heavier and overkill for v1. Diff-render gives us pi-mono's UX without the framework lock-in. |
| **Local LLM transport** | LM Studio HTTP (OpenAI-compatible) is default. `llama-cpp-python` in-proc is opt-in. | LM Studio is what the user already has running. In-proc is faster but ties cortex to a binary build. |
| **Skill packaging** | Markdown with YAML frontmatter (no `SKILL.json`). Identical to `BRAIN.md`. | Zero new schema. Skills are already on disk under `atulya-cortex/life/`; we just point a parser at them. |
| **Persona file** | `atulya-cortex/life/01_self/01_identity/SOUL.md`. | Mirrors hermes' `SOUL.md` convention; lives where the brain's other identity files live. |
| **Multi-agent routing** | Single-agent in v1. The router knows about peer + channel but always resolves to the single cortex instance. | Multi-agent is a complexity tax we don't need yet. The contract is in place; activation is a flag flip in v2. |
| **Sandbox** | Tool allow/deny only in v1 (no Docker per-session). The Protocol exists for v2. | Docker per-session adds operational surface; tool allow/deny gives us the safety we need without it. |

---

## Cross-references

- The **biomimetic charter** (`02_biomimetic_charter.md`) tells you HOW to write
  cortex code — naming voice, ABCs, "one concept per file" rule, the test for
  whether a new file belongs in cortex or in atulya-api.
- The **plan** (`/.cursor/plans/atulya-cortex-brain-v1_31fd71c9.plan.md`) tells
  you WHAT to build, in what order, and what counts as done.
- The repo brain (`atulya/BRAIN.md`) is the contract for the memory substrate.
  Read it before touching `memory/`.
