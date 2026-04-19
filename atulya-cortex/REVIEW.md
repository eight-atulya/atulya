# atulya-cortex v1 — Senior-AI Review Packet

Status: **shippable v1**. Six batches landed; tests are green; lint+format are clean.

This is the packet for senior-AI reviewers. The point is biomimetic structure that *runs*, not just paper architecture. We want feedback on (a) the cross-module contracts, (b) the speculative-compute safety story, and (c) whether the small-LLM-friendly default actually works at the eval bar.

---

## 1. What this is

`atulya-cortex` is a personal AI brain in Python. It is biomimetic: each top-level package is a brain organ, each file is one concept. The brain runs on small local LLMs (default: LM Studio + `google/gemma-3-4b`) but pluggably scales to any OpenAI-compatible cloud provider.

The brain talks to humans through three sensors today (TUI, Telegram, WhatsApp), four motors (Reply, Mouth, Hand, Body), and one memory substrate (the existing `atulya-api` via `atulya-embed`). The brainstem mediates every Stimulus before it reaches the cortex.

---

## 2. Module map

| Package | Concept | Files (concept-per-file) |
| --- | --- | --- |
| `cortex/` | The executive | `bus.py`, `cortex.py`, `language.py`, `personality.py`, `skills.py` |
| `sensors/` | Perception in | `tui.py`, `telegram.py`, `whatsapp.py`, `hearing.py` (+ pre-existing biomimetic placeholders) |
| `motors/` | Action out | `messaging.py` (Reply), `speech.py` (Mouth), `fine_motor_skills.py` (Hand), `movement.py` (Body) |
| `memory/` | Long-term store | `hippocampus.py`, `recall.py`, `working_memory.py`, `episodic.py`, `semantic.py`, `procedural.py`, `emotional.py`, `substrate.py`, `in_memory.py` |
| `brainstem/` | Autonomic nervous system | `heartbeat.py`, `breathing.py`, `reflexes.py`, `router.py` |
| `silo/` | Cache & state | `llm_cache.py`, `embedding_cache.py`, `state.py` |
| `quantum/` | Speculative compute | `coherence.py`, `entanglement.py`, `superposition.py`, `decoherence.py` |
| `dream/` | Background consolidation | `consolidation.py`, `skill_distill.py` |

Every cross-module value is a Pydantic model in `cortex/bus.py` (`Stimulus`, `Recollection`, `Thought`, `Action`, `Intent`, `Reflex`, `ActionResult`, `Disposition`, `MediaRef`, `SkillRef`). No ad-hoc dicts cross a module boundary — this is the load-bearing constraint.

---

## 3. The three things to scrutinize hardest

### 3.1 Cross-module contracts

`bus.py` is the only allowed inter-module type surface. The Cortex's `reflect(Stimulus, *, reflex)` returns one `Intent`. Motors take `Intent` and return `ActionResult`. Sensors yield `Stimulus`. If a future module wants a new shape, the rule is: it lands in `bus.py` with the same Pydantic discipline.

**Ask:** are there shapes we should add now — e.g. `Plan` for multi-step delegations, `Memory` write-back receipts, or `Affect` for an explicit emotion bus channel?

### 3.2 Speculative-compute safety (`quantum/superposition.py`)

`Superposition` exists to hide local-LLM latency. v1 only allows `idempotent=True` *and* a name from `SAFE_IDEMPOTENT_TOOLS = {"read_file", "web_fetch"}`. Adding to that allowlist is intentionally a code change, not a config flag. `Decoherence` is the channel-scoped supervisor that rolls back any uncommitted speculation on shutdown / disconnect / deny.

**Ask:** is the allowlist too narrow, or already too broad? Should `web_fetch` actually require a per-domain allowlist? Should we model "speculative *compute*" (e.g. pre-render the prompt, pre-encode the embedding) separately from "speculative *I/O*"?

### 3.3 Small-LLM friendliness

Defaults targeted at gemma-3-4b on LM Studio at port 1234. The cortex runs at `temperature=0.4`, `max_tokens=512`, with `Coherence` (KV cache reuse + `LLMCache` content-addressed disk cache). The eval suite has 25 fixtures across factual / math / code / instruction-following / reasoning. The CI version of the eval runs in stub mode (deterministic, hits 100%) so regressions in the eval *harness* never get hidden. Live mode (`CORTEX_EVAL=1`) targets ≥70% pass rate against gemma-3-4b.

**Ask:** is 70% the right bar for a 4B local model? Should we add fixtures that specifically exercise tool-call decisioning (vs just chat-Q/A)?

---

## 4. What is intentionally not in v1

- **No streaming.** The TUI/Telegram/WhatsApp motors send one final reply. Streaming is a v2 follow-up.
- **No tool-call planning by the LLM.** The cortex emits `kind="reply"` by default. To emit `tool_call` or `delegate` requires either a future structured-output call or an upgraded prompt — left for v2.
- **No vision or audio sensors.** `sensors/hearing.py` is a placeholder. `sensors/vision.py` was pre-existing and untouched.
- **No automatic `dream/skill_distill` invocation.** The cortex doesn't yet feed `record(...)` calls into it from the main loop. The Dreamer is wired and tested; cortex integration is a small follow-up.

---

## 5. Test status

```
$ uv run --package atulya-cortex pytest tests/ -q -o addopts=""
... 137+ passed, 2 skipped (LM Studio + atulya-embed daemons gated) ...
```

Plus:
- `uv run --package atulya-cortex ruff check .` → all checks pass.
- `uv run --package atulya-cortex ruff format --check .` → all formatted.

---

## 6. Decisions to confirm

- [ ] Anatomical naming (Hand/Mouth/Body/Reply) over generic naming (ToolMotor/TTSMotor/SubagentMotor/ChannelMotor) — keep?
- [ ] One `bus.py` for *all* cross-module types — keep?
- [ ] Speculation allowlist as a frozenset constant, not config — keep?
- [ ] Small-LLM-first defaults (gemma-3-4b, LM Studio) — keep?

If "yes" across the board, v1 ships and v2 is: streaming, structured tool calls, vision, automatic skill distillation, and per-domain web allowlists.
