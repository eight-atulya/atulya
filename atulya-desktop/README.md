# Atulya Desktop

Desktop shell for Atulya — a living algorithm for machine intelligence (MI).

Built with [Tauri v2](https://v2.tauri.app/). Supports Windows, macOS, and Ubuntu.

## Architecture

`atulya-desktop` is an **orchestrator**, not the business system. It does five things:

1. **Install** — bootstrap runtime artifacts into the user's app data directory
2. **Configure** — manage runtime profiles (Fully Offline / Hybrid)
3. **Start** — spawn and supervise `atulya-api` + Control Plane as child processes
4. **Observe** — health checks, structured logs, diagnostics, support bundles
5. **Update** — signed auto-updates via Tauri updater plugin

The actual memory system runs as local services on `127.0.0.1`.

## Directory Layout

```
atulya-desktop/
├── src-tauri/              # Tauri shell (Rust)
│   ├── src/
│   │   ├── main.rs
│   │   ├── lib.rs                  # App setup + Tauri commands
│   │   ├── process_supervisor.rs   # Generic child process lifecycle
│   │   ├── runtime_manager.rs      # Atulya-specific process orchestration
│   │   ├── runtime_profiles.rs     # Policy layer (offline/hybrid/custom)
│   │   ├── settings_store.rs       # Persistent user settings
│   │   ├── install_state.rs        # Install lifecycle + integrity checks
│   │   ├── diagnostics.rs          # Structured logging + support bundles
│   │   └── updater.rs              # Auto-update lifecycle
│   ├── Cargo.toml
│   ├── build.rs
│   └── tauri.conf.json
├── runtime-manifests/      # Declarative manifests (source, not payloads)
│   ├── profiles/
│   │   ├── fully-offline.env
│   │   └── hybrid.env
│   ├── model-manifest.json
│   ├── runtime-manifest.json
│   └── checksums.json
├── scripts/                # Build + verification scripts
├── packaging/              # Per-OS installer configs
│   ├── macos/
│   ├── linux/
│   └── windows/
├── build/                  # Pipeline documentation
└── .dist/                  # GENERATED ONLY (gitignored)
```

## Runtime Profiles

| Profile | Network | LLM | Embeddings | Reranker | Brain | Remote Learning |
|---------|---------|-----|------------|----------|-------|-----------------|
| Fully Offline | Blocked | Ollama/LM Studio (local) | Local | Local | Enabled | Disabled |
| Hybrid | Allowed | OpenAI / configurable | Local | Local | Enabled | User opt-in |

## Development

### Prerequisites

- Rust 1.77.2+
- Node.js 20+
- Python 3.11+
- Platform-specific Tauri dependencies ([see docs](https://v2.tauri.app/start/prerequisites/))

### Build

```bash
# Assemble runtime artifacts
./scripts/assemble-runtime.sh

# Verify integrity
./scripts/verify-runtime.sh

# Build Tauri app (dev mode)
cd src-tauri && cargo tauri dev
```

### Release

Tag with `desktop-v*` to trigger the CI release pipeline:

```bash
git tag desktop-v0.1.0
git push origin desktop-v0.1.0
```

## Key Design Principles

1. **Repo contains recipes, not payloads** — generated artifacts live in `.dist/` (gitignored)
2. **Desktop supervises, not implements** — no business logic in the shell
3. **Profiles are policies** — offline vs hybrid is a security/operating policy, not a toggle
4. **First-run is a product surface** — bootstrap, migration, recovery are first-class concerns
5. **Every shipped artifact is reproducible** — checksummed, deterministic assembly per OS/arch
