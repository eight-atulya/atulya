# Local LLM — Built-in GGUF Provider (`llamacpp`)

<!--
MetaData: llamacpp provider v2 — production-grade offline inference for Atulya Brain
-->

Run Atulya **completely offline** using any GGUF model — including fine-tuned / LoRA adapters — with zero external dependencies. No Ollama, no LM Studio, no cloud API key.

The `llamacpp` provider manages a [llama-cpp-python](https://github.com/abetlen/llama-cpp-python) HTTP server subprocess internally. It starts on first use, stays alive for the process lifetime, and restarts automatically if it dies (OOM, signal).

---

## Quick Start

### 1. Install extra dependencies

```bash
pip install 'atulya-api[local-llm]'
```

This adds `llama-cpp-python>=0.3.0` and `huggingface-hub>=0.26.0`.

### 2. Enable the provider

```bash
export ATULYA_API_LLM_PROVIDER=llamacpp
atulya-api
```

On first run, Atulya auto-downloads **Gemma-4-E2B-IT Q4_K_M** (~3.5 GB) from HuggingFace into `~/.atulya/models/`. Subsequent starts reuse the cached file.

### 3. Use your own model

```bash
export ATULYA_API_LLM_PROVIDER=llamacpp
export ATULYA_API_LLAMACPP_MODEL_PATH=~/.atulya/models/your-model.gguf
atulya-api
```

Any GGUF model that fits in memory works. The chat template is auto-detected from GGUF metadata — no `CHAT_FORMAT` needed for standard models.

---

## Environment Variables

All variables are optional unless noted. Values shown are defaults.

| Variable | Default | Description |
|---|---|---|
| `ATULYA_API_LLAMACPP_MODEL_PATH` | _(auto-download)_ | Absolute or `~`-relative path to a `.gguf` file. Unset = download default model. |
| `ATULYA_API_LLAMACPP_GPU_LAYERS` | `-1` | GPU layers to offload. `-1` = all (full GPU). `0` = CPU-only. Any positive int = partial offload. |
| `ATULYA_API_LLAMACPP_CONTEXT_SIZE` | `8192` | Context window in tokens. Reduce to `4096` if OOM at startup. |
| `ATULYA_API_LLAMACPP_N_BATCH` | `512` | Prompt batch size. `512` is safe for &lt;8 GB VRAM; increase to `2048` on 16 GB+. |
| `ATULYA_API_LLAMACPP_FLASH_ATTN` | `false` | Flash attention. **Off by default — CUDA or Metal required. Crashes on CPU-only.** |
| `ATULYA_API_LLAMACPP_CHAT_FORMAT` | _(auto-detect)_ | Chat template override (e.g. `chatml`, `llama-2`). Only needed if GGUF metadata is missing. |
| `ATULYA_API_LLAMACPP_VERBOSE` | `false` | Log model-tensor loading metadata. Very noisy — keep `false` in production. |
| `ATULYA_API_LLAMACPP_NO_GRAMMAR` | `false` | Disable JSON grammar enforcement. Faster but less reliable structured output. |
| `ATULYA_API_LLAMACPP_LORA_PATH` | _(none)_ | Path to a LoRA adapter `.gguf` for fine-tuned models. |
| `ATULYA_API_LLAMACPP_EXTRA_ARGS` | _(none)_ | Space-separated extra flags forwarded verbatim to the llama.cpp server CLI. Shell-quoted paths are supported. |

---

## Hardware Tiers

### Tier 1 — Apple Silicon or NVIDIA ≥ 16 GB

Full GPU offload + flash attention + large batch:

```bash
ATULYA_API_LLM_PROVIDER=llamacpp
ATULYA_API_LLAMACPP_GPU_LAYERS=-1
ATULYA_API_LLAMACPP_N_BATCH=2048
ATULYA_API_LLAMACPP_FLASH_ATTN=true       # Metal or CUDA only
ATULYA_API_LLAMACPP_CONTEXT_SIZE=8192
```

### Tier 2 — NVIDIA 8–12 GB

Partial offload — tune `GPU_LAYERS` until VRAM fits:

```bash
ATULYA_API_LLM_PROVIDER=llamacpp
ATULYA_API_LLAMACPP_GPU_LAYERS=28         # lower this until it loads without OOM
ATULYA_API_LLAMACPP_N_BATCH=512
ATULYA_API_LLAMACPP_FLASH_ATTN=false
ATULYA_API_LLAMACPP_CONTEXT_SIZE=4096     # reduce context to save VRAM
```

### Tier 3 — CPU-only

No GPU offload, small batch:

```bash
ATULYA_API_LLM_PROVIDER=llamacpp
ATULYA_API_LLAMACPP_GPU_LAYERS=0
ATULYA_API_LLAMACPP_N_BATCH=256
ATULYA_API_LLAMACPP_FLASH_ATTN=false      # MUST be false on CPU
ATULYA_API_LLAMACPP_CONTEXT_SIZE=4096
ATULYA_API_LLAMACPP_EXTRA_ARGS=--threads 8
```

:::tip CPU performance
CPU inference is slow. For retain operations, consider increasing `ATULYA_API_LLM_TIMEOUT` to `600` and reducing `ATULYA_API_RETAIN_CHUNK_SIZE` to keep prompts short.
:::

---

## Fine-Tuned Models (LoRA Adapters)

The `llamacpp` provider is designed as the **foundation for fine-tuned Atulya Brain models**. Load any LoRA adapter on top of a base GGUF:

```bash
ATULYA_API_LLM_PROVIDER=llamacpp
ATULYA_API_LLAMACPP_MODEL_PATH=~/.atulya/models/base-model.gguf
ATULYA_API_LLAMACPP_LORA_PATH=~/.atulya/models/brain-adapter.gguf
```

The adapter is applied at server startup. Paths with spaces must be quoted — they are parsed with `shlex.split` so shell quoting rules apply in `EXTRA_ARGS`.

---

## Auto-Download Behaviour

When `ATULYA_API_LLAMACPP_MODEL_PATH` is not set, Atulya downloads:

| | |
|---|---|
| **Repo** | `bartowski/google_gemma-4-E2B-it-GGUF` |
| **File** | `google_gemma-4-E2B-it-Q4_K_M.gguf` |
| **Size** | ~3.5 GB |
| **Cache** | `~/.atulya/models/` |

The download happens once. On subsequent starts the cached file is reused without any network call.

To pre-download before first API call:

```python
from atulya_api.engine.providers.llamacpp_llm import _download_default_model
_download_default_model()
```

---

## Architecture

```
atulya-api process
  └─ LlamaCppLLM._ensure_initialized()
       └─ LlamaCppServer (singleton per process)
            └─ subprocess: python -m llama_cpp.server --model ... --port <free_port>
                 └─ OpenAI-compatible HTTP API on 127.0.0.1:<port>/v1
  └─ OpenAICompatibleLLM (delegate)
       └─ HTTP calls to 127.0.0.1:<port>/v1/chat/completions
```

**Key design invariants:**

- **One server per Python process** — all `retain`/`reflect`/`consolidation` workers share a single subprocess. No duplicate GPU memory.
- **Lazy start** — server starts on the first LLM call, not at import time.
- **Auto-restart** — if the subprocess dies (OOM, kill signal) it is automatically restarted on the next request.
- **atexit cleanup** — subprocess is killed on clean Python exit; registered exactly once per process.
- **Port-race retry** — up to 3 attempts with a fresh port if the OS port was grabbed between allocation and bind.

---

## Failure Modes & Mitigations

| Symptom | Likely cause | Fix |
|---|---|---|
| `[ERROR] llama.cpp server exited (code 1) during startup` | Bad model file or missing `.gguf` | Check `ATULYA_API_LLAMACPP_MODEL_PATH`; verify file is not truncated |
| `[ERROR] llama.cpp server exited (code -9) during startup` | OOM killed by kernel | Reduce `CONTEXT_SIZE`, reduce `GPU_LAYERS`, or use a smaller quantization |
| `[ERROR] llama.cpp server did not become ready within 120s` | Very slow cold-load on CPU | Normal for CPU-only. Increase timeout: `ATULYA_API_LLM_TIMEOUT=600` |
| `RuntimeError: Model mismatch: running server uses ...` | Two `LlamaCppLLM` instances pointing at different models | Use one `ATULYA_API_LLAMACPP_MODEL_PATH` globally; do not mix models per-operation |
| Flash attention crash / `SIGILL` | `FLASH_ATTN=true` on a CPU-only or unsupported Metal build | Set `ATULYA_API_LLAMACPP_FLASH_ATTN=false` |
| Noisy logs with tensor metadata | `VERBOSE=true` accidentally set | Set `ATULYA_API_LLAMACPP_VERBOSE=false` |
| GPU VRAM not released after restart | Subprocess orphaned (parent killed with SIGKILL) | Run `pkill -f llama_cpp.server`; atexit cannot fire on SIGKILL |
| `ImportError: llama-cpp-python not installed` | Missing optional dependency | `pip install 'atulya-api[local-llm]'` |

---

## Server Log

The llama.cpp server stderr is captured to:

```
~/.atulya/models/llamacpp_server.log
```

Always check this file first when debugging startup failures — it contains the full model load trace and any error from the C++ runtime.

```bash
tail -f ~/.atulya/models/llamacpp_server.log
```

---

## Comparison with Other Local Providers

| | `llamacpp` (built-in) | `ollama` | `lmstudio` |
|---|---|---|---|
| External server required | No — managed internally | Yes (`ollama serve`) | Yes (GUI app) |
| GGUF model support | Yes | Yes | Yes |
| LoRA adapter support | Yes | No | No |
| Fine-tuned model support | Yes (LoRA) | Limited | Limited |
| Auto-download on first use | Yes | No | No |
| Production subprocess mgmt | Yes (atexit, auto-restart) | External | External |
| GPU control (layer count) | Full | Partial | Partial |
| Flash attention | Opt-in | Auto | Auto |

---

## Related Configuration

- [Configuration Reference — LLM Provider](./configuration.md#llm-provider)
- [Models — Provider Default Models](./models.md#provider-default-models)
- [Performance — Local LLM Tuning](./performance.md)
