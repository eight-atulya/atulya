# 02 — Biomimetic Charter

> **Purpose.** This is the **how-we-name-things** contract for `atulya-cortex/`.
> Every file we add must read like a continuation of [sensors/vision.py](../sensors/vision.py)
> (`Eye`, `VisualCortex`, `open_eyelid`, `blink`) — not like a fork into a
> different project.
>
> If a contributor opens a cortex file and the names feel mechanical
> (`MessageHandler`, `ToolRegistry`, `LLMService`), the file is **wrong**. It
> should feel like reading a textbook of human anatomy where the textbook is
> also a Python module.

This charter is short on purpose. Three rules, three contracts, four defaults.
Memorize them.

---

## Rule 1 — One concept per file

Every `.py` file in `atulya-cortex/` owns **exactly one** concept. The file
name IS the concept name. The concept name is biomimetic.

| Good | Bad |
|------|-----|
| `sensors/telegram.py` (`TelegramEar`) | `sensors/messaging_adapter.py` (`MessagingAdapter`) |
| `motors/hand.py` (`Hand` runs tools) | `motors/tool_executor.py` (`ToolExecutor`) |
| `memory/hippocampus.py` (`Hippocampus.encode`) | `memory/storage.py` (`StorageManager.save`) |
| `quantum/coherence.py` (`Coherence` reuses the KV cache) | `quantum/cache.py` |
| `dream/consolidation.py` (`Consolidation` runs at heartbeat) | `dream/background_tasks.py` |

The point is not poetry. The point is that **the directory tree IS the
architecture diagram**. A reviewer can `ls atulya-cortex/sensors/` and read off
the system's input modalities without opening any file. They can `ls
atulya-cortex/memory/` and see the hippocampus + working memory + episodic /
semantic / procedural / emotional — and that is the entire memory taxonomy of
the brain.

**Corollary.** If two files would have the same biomimetic name, they are the
same concept and must merge. If a file's name no longer matches what it does,
rename it (and run `bash scripts/hooks/lint.sh`).

---

## Rule 2 — One location per concept

A concept lives in **exactly one** file. No duplicates, no shims, no
"compatibility aliases". The user said it directly:

> "All the code we write should be semantically kept in the cortex files py
> once because system will be self-evolving like real human brain so file and
> code should be meaningful and well-connected and segmented."

If you find yourself wanting to write `motors/hand_v2.py` or
`sensors/telegram_new.py`, **stop and edit the existing file**.

**Legacy taxonomy (`atulya-cortex/brain/`).** The pre-existing `brain/cortex/`,
`brain/brainstem/`, `brain/limbic_system/` etc. subtree contains 0-byte stubs
of an older, more granular cerebral-anatomy taxonomy. **Live cortex code goes
in the top-level packages** (`cortex/`, `brainstem/`, `memory/`, `motors/`,
`sensors/`, `silo/`, `quantum/`, `dream/`). The legacy `brain/` subtree is
preserved as a placeholder for future deeper biomimetic decomposition; it is
NOT imported by live code in v1.

---

## Rule 3 — Naming voice

The voice is **anatomy verbs and organ names**, not engineering nouns.

| Layer | Anatomy used | Forbidden |
|-------|--------------|-----------|
| Inputs | `Eye`, `Ear`, `Skin`, `Tongue`, `Nose`, `Terminal` (the "screen-eye"), `TelegramEar`, `WhatsAppEar` | `InputAdapter`, `Listener`, `Subscriber` |
| Outputs | `Hand`, `Mouth`, `Voice`, `Body` (subagents), `Reply` | `OutputWriter`, `Sender`, `Producer` |
| Memory | `Hippocampus`, `Recall`, `WorkingMemory`, `EpisodicMemory`, `SemanticMemory`, `ProceduralMemory`, `EmotionalMemory` | `Storage`, `KeyValueStore`, `Cache` (use `Silo` if you mean cache!) |
| Executive | `Cortex`, `Personality`, `Skills`, `Language` | `Agent`, `Engine`, `Service` |
| Autonomic | `Heartbeat`, `Breathing`, `Reflexes`, `Router` (= `Brainstem`) | `Scheduler`, `RateLimiter`, `Middleware` |
| Speculative | `Coherence`, `Entanglement`, `Superposition`, `Decoherence` | `Cache`, `Prefetcher`, `Speculator` |
| Cache / state | `Silo` (`LLMCache`, `EmbeddingCache`, `State`) | `Persistence`, `Repository` |
| Background | `Dream` (`Consolidation`, `SkillDistill`) | `BackgroundJob`, `Worker` |

**Verbs match the anatomy.** Eyes `open_eyelid`, `blink`, `see`. Ears `tune_in`,
`hear`, `tune_out`. Hands `grasp`, `release`, `act`. Hippocampus `encodes`. Cortex
`reflects`. Brainstem `pulses`. Dreams `consolidate`.

**Counter-example to avoid.** Do not invent `LLMService.callApi()`. The right
shape is `Language.speak(thought) -> Utterance` (or whatever bus type fits).
Method names tell you what the **organ** is doing.

---

## Contract A — `Sensor`

A sensor perceives. It has three lifecycle verbs and one perception verb.

```python
class Sensor(Protocol):
    async def awaken(self) -> None: ...
    async def perceive(self) -> AsyncIterator[Stimulus]: ...
    async def rest(self) -> None: ...
```

- `awaken` opens the channel (camera open, telegram poller starts, TUI screen takes over).
- `perceive` yields `Stimulus` objects until cancelled (a long-running async generator).
- `rest` closes cleanly (`blink` for eyes, `disconnect` for telegram, restore tty for TUI).

**Naming derivation.** `vision.py:Eye.open_eyelid` / `see` / `blink` already
demonstrates this voice; `Sensor`'s ABC just promotes the convention to a typed
contract.

---

## Contract B — `Motor`

A motor acts. It also has three lifecycle verbs and one action verb.

```python
class Motor(Protocol):
    async def prepare(self) -> None: ...
    async def act(self, intent: Action) -> ActionResult: ...
    async def recover(self) -> None: ...
```

- `prepare` warms up (TTS engine boots, telegram bot client connects, tool sandbox primes).
- `act` performs one outbound action.
- `recover` cleans up after a fault (cancel pending sends, reset TTS).

---

## Contract C — `MemoryStore` (Protocol, not ABC)

A memory store remembers. We use a `Protocol` (structural typing) so
`AtulyaEmbedded` satisfies it without us monkey-patching atulya-embed.

```python
class MemoryStore(Protocol):
    async def encode(self, stimulus: Stimulus, *, kind: MemoryKind) -> RetainResult: ...
    async def recall(self, query: str, *, budget: Budget = "mid",
                     kinds: Sequence[MemoryKind] | None = None) -> list[Recollection]: ...
    async def disposition_for(self, bank: str) -> Disposition: ...
```

- `encode` writes a memory (delegates to atulya-embed `retain`).
- `recall` reads memories back (delegates to atulya-embed `recall`).
- `disposition_for` reads bank-level affective state.

The contract intentionally hides retain / recall / reflect / mental_model as a
single `MemoryStore` because cortex thinks at the level of "remember this" and
"recall about that". Lower-level operations live in the concrete adapter
(`memory/hippocampus.py`).

---

## The bus types (defined once, in `cortex/bus.py`)

These are the **only** types passed between modules. Anything else is internal
to a module.

```python
class Stimulus(BaseModel):
    """Anything a sensor perceived. The thing the brain reacts to."""
    channel: ChannelId       # "tui:local" | "telegram:<chat_id>" | "whatsapp:<jid>"
    sender: SenderId         # opaque-but-channel-scoped peer id
    text: str | None         # primary modality; None for non-text stimuli
    media: list[MediaRef]    # optional attachments
    received_at: datetime
    raw: dict[str, Any]      # provenance for debugging; never logged in prod

class Recollection(BaseModel):
    """A single memory the hippocampus surfaced."""
    kind: MemoryKind
    text: str
    score: float
    source: str

class Thought(BaseModel):
    """An intermediate state the cortex holds while reflecting."""
    stimulus: Stimulus
    recollections: list[Recollection]
    persona: str
    skills: list[SkillRef]
    drafted_action: Action | None

class Action(BaseModel):
    """Discriminated union: what the cortex decided to do."""
    kind: Literal["reply", "tool_call", "delegate", "noop"]
    payload: dict[str, Any]   # shape determined by kind

class Intent(BaseModel):
    """An Action plus the channel envelope, ready for a Motor."""
    action: Action
    channel: ChannelId
    sender: SenderId

class Reflex(BaseModel):
    """Brainstem pre-cortex decision. Allow / deny / pair / sandbox."""
    decision: Literal["allow", "deny", "pair", "sandbox"]
    reason: str
    expires_at: datetime | None
```

These names are non-negotiable. If a future feature needs a new bus type, add
it here, do not invent a competing one in a peripheral module.

---

## Default 1 — Channel adapters: WhatsApp + TUI + Telegram

- **WhatsApp** ships two backends behind one Protocol (`WhatsAppBackend`):
  Baileys subprocess (dev default, fast onboarding) and WhatsApp Cloud API
  (prod, ban-immune). Selection by config flag. The Protocol is the contract;
  individual backends are private to `sensors/whatsapp.py`.
- **TUI** uses `rich` + a custom asyncio event loop. We port pi-mono's
  diff-render algorithm into the rich layer; we do **not** adopt `Textual` in
  v1 (heavyweight) or `prompt_toolkit` (older API surface).
- **Telegram** uses `python-telegram-bot` (mirrors hermes; battle-tested; large
  community). We do **not** adopt grammY (TS-first ecosystem).

A new channel must (a) implement `Sensor`, (b) emit `Stimulus` with a
correctly-scoped `channel` id, (c) expose its outbound counterpart through
`motors/messaging.py`, (d) reuse `brainstem/reflexes.py` for DM pairing.

---

## Default 2 — LLM transport

- **Default**: LM Studio HTTP (OpenAI-compatible) → `lmstudio:gemma-3-4b`.
- **Opt-in (env / disposition)**: Ollama, OpenAI, Anthropic, Google Gemini,
  Groq, OpenRouter. `llama-cpp-python` in-proc as a power-user opt-in.
- Selection rule: `ATULYA_CORTEX_LLM_PROVIDER` env → per-bank disposition →
  default.

A new provider drops one file under `cortex/providers/` (mirroring
`pi-mono/packages/ai/src/providers/`) and registers itself via
`cortex/language.py:register_provider`. **Zero changes to cortex/cortex.py.**

---

## Default 3 — Skill packaging

A skill is a markdown file with YAML frontmatter, on disk under
`atulya-cortex/life/03_systems/03_workflows/<skill>/SKILL.md` (or
`life/40_knowledge/17_lessons_learned/<lesson>/BRAIN.md` for distilled
lessons). Same parser, same shape.

```yaml
---
name: do_thing
description: One-line LLM-facing description.
version: 1
metadata:
  tags: [tag1, tag2]
---

# Body of the skill
Read me before doing X. Here are the steps. ...
```

**No `SKILL.json`.** No new schema. The frontmatter parser ships in
`cortex/skills.py` and is identical to hermes' `parse_frontmatter` (~30 LoC).

---

## Default 4 — "Does this belong in cortex or atulya-api?"

This is the single most-asked question in the next year. The test:

> **A new file belongs in `atulya-api/` if and only if it ALTERS the durable
> memory substrate. Otherwise it belongs in `atulya-cortex/`.**

Concrete decisions:

| Question | Cortex or API? | Why |
|----------|----------------|-----|
| "Add a new mental-model refresh mode" | **API** (we did this last sprint) | Touches the substrate. |
| "Add a new bank-level disposition" | **API** | Schema change. |
| "Add a new sensor (e.g. discord.py)" | **CORTEX** | Channel — does not touch durable memory. |
| "Add a new tool (e.g. `web_fetch`)" | **CORTEX** | Tool — surface, not substrate. |
| "Tune recall budget for cortex's default" | **CORTEX** | Caller-side default. |
| "Speed up consolidation" | **API** | Substrate algorithm. |
| "Make cortex consolidation fire on heartbeat" | **CORTEX** | Triggering, not algorithm. |
| "Add a new persona / skill" | **CORTEX/life** | Markdown content, not code. |
| "Cache LLM completions across cortex turns" | **CORTEX** (`silo/`) | Cortex-local, ephemeral. |

Edge case: if a feature requires both, **land the API change first** (with
migration), then the cortex change in a separate commit. We followed exactly
this discipline last sprint.

---

## Definition of done (for any cortex file)

A file is "done" when **all** of the following are true:

1. The filename matches the concept (Rule 1).
2. The concept lives nowhere else in the repo (Rule 2).
3. Class/method names follow the anatomy voice (Rule 3).
4. If it crosses a module boundary, it uses a bus type from
   `cortex/bus.py` — never an ad-hoc dict.
5. It implements the relevant Protocol/ABC (`Sensor`, `Motor`, or `MemoryStore`)
   if it lives in the corresponding directory.
6. It has at least one test in `atulya-cortex/tests/` covering the load-bearing
   public method.
7. `bash scripts/hooks/lint.sh` is clean.
8. `uv run pytest atulya-cortex/tests/` is green.
9. Public symbols are documented in their module docstring (one paragraph max).
   No file-level history comments. No "what this code does" line-noise comments.
10. The brain edit guard (`scripts/brain_edit_guard.py`) accepts the change.

---

## What this charter is not

- It is **not** a coding-style guide for whitespace / quotes — those are
  enforced by `ruff` via the lint hook.
- It is **not** a runtime architecture spec — read the **plan** for that.
- It is **not** the place to define new bus types — those go in
  `cortex/bus.py`.
- It is **not** negotiable mid-batch. If a contract here is wrong, it is
  changed in a dedicated PR titled `charter:` and the rest of cortex bends to
  the new contract in the same PR.
