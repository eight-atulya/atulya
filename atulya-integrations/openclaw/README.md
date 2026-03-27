# Atulya Memory Plugin for OpenClaw

Biomimetic long-term memory for [OpenClaw](https://openclaw.ai) using [Atulya](https://github.com/eight-atulya/atulya). Automatically captures conversations and intelligently recalls relevant context.

## Quick Start

```bash
# 1. Configure your LLM provider for memory extraction
# Option A: OpenAI
export OPENAI_API_KEY="sk-your-key"

# Option B: Claude Code (no API key needed)
export ATULYA_API_LLM_PROVIDER=claude-code

# Option C: OpenAI Codex (no API key needed)
export ATULYA_API_LLM_PROVIDER=openai-codex

# 2. Install and enable the plugin
openclaw plugins install @eight-atulya/atulya-openclaw

# 3. Start OpenClaw
openclaw gateway
```

That's it! The plugin will automatically start capturing and recalling memories.

## Features

- **Auto-capture** and **auto-recall** of memories each turn
- **Memory isolation** — configurable per agent, channel, user, or provider via `dynamicBankGranularity`
- **Retention controls** — choose which message roles to retain and toggle auto-retain on/off

## Configuration

Optional settings in `~/.openclaw/openclaw.json` under `plugins.entries.atulya-openclaw.config`:

| Option | Default | Description |
|--------|---------|-------------|
| `apiPort` | `9077` | Port for the local Atulya daemon |
| `daemonIdleTimeout` | `0` | Seconds before daemon shuts down from inactivity (0 = never) |
| `embedPort` | `0` | Port for `atulya-embed` server (`0` = auto-assign) |
| `embedVersion` | `"latest"` | atulya-embed version |
| `embedPackagePath` | — | Local path to `atulya-embed` package for development |
| `bankMission` | — | Agent identity/purpose stored on the memory bank. Helps the engine understand context for better fact extraction. Set once per bank — not a recall prompt. |
| `llmProvider` | auto-detect | LLM provider override for memory extraction (`openai`, `anthropic`, `gemini`, `groq`, `ollama`, `openai-codex`, `claude-code`) |
| `llmModel` | provider default | LLM model override used with `llmProvider` |
| `llmApiKeyEnv` | provider standard env var | Custom env var name for the provider API key |
| `dynamicBankId` | `true` | Enable per-context memory banks |
| `bankIdPrefix` | — | Prefix for bank IDs (e.g. `"prod"`) |
| `dynamicBankGranularity` | `["agent", "channel", "user"]` | Fields used to derive bank ID. Options: `agent`, `channel`, `user`, `provider` |
| `excludeProviders` | `[]` | Message providers to skip for recall/retain (e.g. `slack`, `telegram`, `discord`) |
| `autoRecall` | `true` | Auto-inject memories before each turn. Set to `false` when the agent has its own recall tool. |
| `autoRetain` | `true` | Auto-retain conversations after each turn |
| `retainRoles` | `["user", "assistant"]` | Which message roles to retain. Options: `user`, `assistant`, `system`, `tool` |
| `retainEveryNTurns` | `1` | Retain every Nth turn. `1` = every turn (default). Values > 1 enable chunked retention with a sliding window. |
| `retainOverlapTurns` | `0` | Extra prior turns included when chunked retention fires. Window = `retainEveryNTurns + retainOverlapTurns`. Only applies when `retainEveryNTurns > 1`. |
| `recallBudget` | `"mid"` | Recall effort: `low`, `mid`, or `high`. Higher budgets use more retrieval strategies. |
| `recallMaxTokens` | `1024` | Max tokens for recall response. Controls how much memory context is injected per turn. |
| `recallTypes` | `["world", "experience"]` | Memory types to recall. Options: `world`, `experience`, `observation`. Excludes verbose `observation` entries by default. |
| `recallRoles` | `["user", "assistant"]` | Roles included when building prior context for recall query composition. Options: `user`, `assistant`, `system`, `tool`. |
| `recallTopK` | — | Max number of memories to inject per turn. Applied after API response as a hard cap. |
| `recallContextTurns` | `1` | Number of user turns to include when composing recall query context. `1` keeps latest-message-only behavior. |
| `recallMaxQueryChars` | `800` | Maximum character length for the composed recall query before calling recall. |
| `recallPromptPreamble` | built-in string | Prompt text placed above recalled memories in the injected `<atulya_memories>` block. |
| `atulyaApiUrl` | — | External Atulya API URL (skips local daemon) |
| `atulyaApiToken` | — | Auth token for external API |

## Documentation

For full documentation, configuration options, troubleshooting, and development guide, see:

**[OpenClaw Integration Documentation](https://github.com/eight-atulya/atulya/blob/main/atulya-docs/docs/sdks/integrations/openclaw.md)**

## Development

To test local changes to the Atulya package before publishing:

1. Add `embedPackagePath` to your plugin config in `~/.openclaw/openclaw.json`:
```json
{
  "plugins": {
    "entries": {
      "atulya-openclaw": {
        "enabled": true,
        "config": {
          "embedPackagePath": "/path/to/atulya-wt3/atulya-embed"
        }
      }
    }
  }
}
```

2. The plugin will use `uv run --directory <path> atulya-embed` instead of `uvx atulya-embed@latest`

3. To use a specific profile for testing:
```bash
# Check daemon status
uvx atulya-embed@latest -p openclaw daemon status

# View logs
tail -f ~/.atulya/profiles/openclaw.log

# List profiles
uvx atulya-embed@latest profile list
```

## Links

- [Atulya Documentation](https://github.com/eight-atulya/atulya/tree/main/atulya-docs)
- [OpenClaw Documentation](https://openclaw.ai)
- [GitHub Repository](https://github.com/eight-atulya/atulya)

## License

MIT
