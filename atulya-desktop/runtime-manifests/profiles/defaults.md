# Runtime Profile Defaults

This document explains the rationale behind each profile and the env vars it sets.

## Profile: Fully Offline (`fully-offline.env`)

**Goal**: Zero outbound network connections. Everything runs locally.

| Setting | Value | Rationale |
|---------|-------|-----------|
| `ATULYA_API_DATABASE_URL` | `pg0://atulya-desktop` | Embedded PostgreSQL via pg0. No external DB. |
| `ATULYA_API_LLM_PROVIDER` | `ollama` | Local LLM inference. User must have Ollama running. |
| `ATULYA_API_LLM_BASE_URL` | `http://localhost:11434/v1` | Default Ollama endpoint. |
| `ATULYA_API_EMBEDDINGS_PROVIDER` | `local` | In-process embedding model (`BAAI/bge-small-en-v1.5`). |
| `ATULYA_API_RERANKER_PROVIDER` | `local` | In-process cross-encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`). |
| `ATULYA_API_BRAIN_ENABLED` | `true` | Brain cache + activity prediction enabled. |
| `ATULYA_API_BRAIN_IMPORT_EXPORT_ENABLED` | `true` | Allow local .brain file import/export. |
| `ATULYA_API_BRAIN_STARTUP_WARMUP` | `true` | Pre-warm brain cache on API start. |
| `ATULYA_API_SKIP_LLM_VERIFICATION` | `true` | Don't verify LLM connectivity on startup (may not be running yet). |
| `ATULYA_API_HOST` | `127.0.0.1` | Bind to loopback only. Never exposed publicly. |
| `HF_HOME` | `{DATA_DIR}/models` | Pin HuggingFace cache into app data dir. |

**Network policy**: All outbound connections blocked. Remote brain learning endpoint disabled.

## Profile: Hybrid (`hybrid.env`)

**Goal**: Local embeddings/reranker for consistent offline vector search, but LLM can use a remote provider.

| Setting | Value | Rationale |
|---------|-------|-----------|
| `ATULYA_API_LLM_PROVIDER` | `openai` | Remote LLM. User provides API key in desktop settings. |
| `ATULYA_API_EMBEDDINGS_PROVIDER` | `local` | Stays local so vector search works offline. |
| `ATULYA_API_RERANKER_PROVIDER` | `local` | Stays local for same reason. |
| `ATULYA_API_BRAIN_ENABLED` | `true` | Brain always on for desktop. |

**Network policy**: Outbound allowed for LLM API calls and optional model downloads. Remote brain learning still disabled by default (user must opt in via desktop settings).

## How profiles become env vars

The `runtime_profiles.rs` module in `src-tauri/src/` resolves a profile into a `BTreeMap<String, String>` of environment variables. These are passed to the child processes (`atulya-api` and control plane) when spawned.

The `.env` files in this directory are the **reference specification**. The Rust code must produce equivalent output.

## Adding a custom profile

1. Add a new `.env` file in this directory
2. Add a corresponding variant to `ProfileId` in `runtime_profiles.rs`
3. Implement `to_env_vars()` for the new profile
4. Add it to `builtin_profiles()`
