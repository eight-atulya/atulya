---
title: "Built-in GGUF provider — run Atulya fully offline"
description: Native llama.cpp support with production-grade subprocess management, auto-restart, LoRA adapters, and hardware-tier tuning.
authors: [atulya]
date: 2026-04-28
hide_table_of_contents: true
---

<!--
MetaData: llamacpp provider v2 release post — foundation for fine-tuned Atulya Brain models
-->

Atulya now ships a **built-in GGUF provider** (`llamacpp`) — run the full memory engine locally with no external server, no API key, and no Ollama or LM Studio dependency. Drop in any GGUF model, including fine-tuned adapters, and Atulya manages the subprocess lifecycle automatically.

This is the foundation we're building on for the next phase: **fine-tuned Atulya Brain models running natively on-device**.

<!-- truncate -->

## What's new

### One-command offline setup

```bash
pip install 'atulya-api[local-llm]'
export ATULYA_API_LLM_PROVIDER=llamacpp
atulya-api
```

First run auto-downloads `google_gemma-4-E2B-it-Q4_K_M.gguf` (~3.5 GB) into `~/.atulya/models/`. Every subsequent start reuses the cache — no network call.

### Production-grade subprocess management

The server is managed with the same reliability guarantees we apply to the rest of Atulya:

- **Auto-restart** — if the llama.cpp subprocess dies (OOM, signal) between requests, it is detected immediately and restarted transparently on the next call. No stale state, no hung requests.
- **Resource cleanup** — `atexit` registration ensures the subprocess (and its GPU VRAM) is released on clean Python exit. Registered exactly once per process — no duplicate handlers on recovery restarts.
- **Port-race retry** — up to 3 attempts with a fresh OS port each time, guarding against the TOCTOU gap between port allocation and subprocess bind.
- **No resource leaks** — `try/finally` in `start()` guarantees the log file descriptor and subprocess handle are always closed on failure, even on partial starts.
- **Deterministic cleanup** — `stop()` sends SIGTERM to the full process group, escalates to SIGKILL if the process doesn't exit within 10 s, then closes the log fd in `finally`. Safe to call on a server that was never started.

### LoRA / fine-tuned adapter support

```bash
export ATULYA_API_LLAMACPP_MODEL_PATH=~/.atulya/models/base-model.gguf
export ATULYA_API_LLAMACPP_LORA_PATH=~/.atulya/models/brain-adapter.gguf
```

This is the key capability for the future: load any fine-tuned GGUF adapter on top of a base model at startup.

### Hardware-tier tuning

No more hardcoded flags. Every hardware parameter is configurable with safe defaults:

| Variable | Default | Notes |
|---|---|---|
| `ATULYA_API_LLAMACPP_GPU_LAYERS` | `-1` (all on GPU) | Set `0` for CPU-only |
| `ATULYA_API_LLAMACPP_N_BATCH` | `512` | Safe for &lt;8 GB VRAM; `2048` for 16 GB+ |
| `ATULYA_API_LLAMACPP_FLASH_ATTN` | `false` | **Opt-in only** — requires CUDA/Metal; crashes on CPU |
| `ATULYA_API_LLAMACPP_CONTEXT_SIZE` | `8192` | Reduce to `4096` if OOM at startup |
| `ATULYA_API_LLAMACPP_VERBOSE` | `false` | Model-tensor log noise — off in production |
| `ATULYA_API_LLAMACPP_LORA_PATH` | _(none)_ | Fine-tuned adapter path |

The previous v1 implementation hardcoded `--flash_attn true` and `--n_batch 2048` — both of which crash or OOM on most consumer hardware. Those are now safe-default opt-ins.

## Why this matters

Atulya's memory engine does a lot of LLM work: fact extraction, entity resolution, consolidation, reasoning. Running all of that through a cloud API adds latency, cost, and a privacy surface. With the built-in GGUF provider, the entire memory pipeline can run on a single machine — M-series MacBook, workstation GPU, or edge server.

The next step is fine-tuned models specifically trained on Atulya's memory tasks, loaded via `ATULYA_API_LLAMACPP_LORA_PATH`. This release is the infrastructure that makes that possible.

## Documentation

- [Local LLM guide](/local-llm) — full environment variable reference, hardware tiers, failure modes, architecture
- [Configuration reference](/configuration#llm-provider) — provider list and examples
- [Models reference](/models) — provider default models table
