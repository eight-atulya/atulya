---
sidebar_position: 4
---

# OpenClaw

Local, long term memory for [OpenClaw](https://openclaw.ai) agents using [Atulya](https://eightengine.com/atulya).

This plugin integrates [atulya-embed](https://eightengine.com/atulya/cli), a standalone daemon that bundles Atulya's memory engine (API + PostgreSQL) into a single command. Everything runs locally on your machine, reuses the LLM you're already paying for, and costs nothing extra.

## Quick Start

**Step 1: Set up LLM for memory extraction**

Choose one provider and set its API key:

```bash
# Option A: OpenAI (uses gpt-4o-mini for memory extraction)
export OPENAI_API_KEY="sk-your-key"

# Option B: Anthropic (uses claude-3-5-haiku for memory extraction)
export ANTHROPIC_API_KEY="your-key"

# Option C: Gemini (uses gemini-2.5-flash for memory extraction)
export GEMINI_API_KEY="your-key"

# Option D: Groq (uses openai/gpt-oss-20b for memory extraction)
export GROQ_API_KEY="your-key"

# Option E: Claude Code (uses claude-sonnet-4-20250514, no API key needed)
export ATULYA_API_LLM_PROVIDER=claude-code

# Option F: OpenAI Codex (uses gpt-4o-mini, no API key needed)
export ATULYA_API_LLM_PROVIDER=openai-codex
```

**Step 2: Install the plugin**

```bash
openclaw plugins install @eight-atulya/atulya-openclaw
```

**Step 3: Start OpenClaw**

```bash
openclaw gateway
```

The plugin will automatically:
- Start a local Atulya daemon (port 9077)
- Capture conversations after each turn
- Inject relevant memories before agent responses

**Important:** The LLM you configure above is **only for memory extraction** (background processing). Your main OpenClaw agent can use any model you configure separately.

## How It Works

**Auto-Capture:** Every conversation is automatically stored after each turn. Facts, entities, and relationships are extracted in the background.

**Auto-Recall:** Before each agent response, relevant memories are automatically injected into the context (up to 1024 tokens). The agent uses past context without needing to call tools.

**Feedback Loop Prevention:** The plugin automatically strips injected memory tags (`<atulya_memories>`) before storing conversations. This prevents recalled memories from being re-extracted as new facts, which would cause exponential memory growth and duplicate entries.

Traditional memory systems give agents a `search_memory` tool - but models don't use it consistently. Auto-recall solves this by injecting memories automatically before every turn.

## Configuration

### Plugin Settings

Optional settings in `~/.openclaw/openclaw.json`:

```json
{
  "plugins": {
    "entries": {
      "atulya-openclaw": {
        "enabled": true,
        "config": {
          "apiPort": 9077,
          "daemonIdleTimeout": 0,
          "embedVersion": "latest"
        }
      }
    }
  }
}
```

**Options:**
- `apiPort` - Port for the openclaw profile daemon (default: `9077`)
- `daemonIdleTimeout` - Seconds before daemon shuts down from inactivity (default: `0` = never)
- `embedVersion` - atulya-embed version (default: `"latest"`)
- `bankMission` - Agent identity/purpose stored on the memory bank. Helps the memory engine understand context for better fact extraction during retain. Set once per bank on first use — not a recall prompt.
- `dynamicBankId` - Enable per-context memory banks (default: `true`)
- `bankIdPrefix` - Optional prefix for bank IDs (e.g. `"prod"` → `"prod-slack-C123"`)
- `dynamicBankGranularity` - Fields used to derive bank ID: `agent`, `channel`, `user`, `provider` (default: `["agent", "channel", "user"]`)
- `excludeProviders` - Message providers to skip for recall/retain (e.g. `["slack"]`, `["telegram"]`, `["discord"]`)
- `autoRecall` - Auto-inject memories before each turn (default: `true`). Set to `false` when the agent has its own recall tool.
- `autoRetain` - Auto-retain conversations after each turn (default: `true`)
- `retainRoles` - Which message roles to retain (default: `["user", "assistant"]`). Options: `user`, `assistant`, `system`, `tool`
- `recallBudget` - Recall effort: `"low"`, `"mid"`, or `"high"` (default: `"mid"`). Higher budgets use more retrieval strategies for better results.
- `recallMaxTokens` - Max tokens for recall response (default: `1024`). Controls how much memory context is injected per turn.

### Memory Isolation

The plugin creates separate memory banks based on conversation context. By default, banks are derived from the `agent`, `channel`, and `user` fields — so each unique combination gets its own isolated memory store.

You can customize which fields are used for bank segmentation with `dynamicBankGranularity`:

```json
{
  "plugins": {
    "entries": {
      "atulya-openclaw": {
        "enabled": true,
        "config": {
          "dynamicBankGranularity": ["provider", "user"]
        }
      }
    }
  }
}
```

In this example, memories are isolated per provider + user, meaning the same user shares memories across all channels within a provider.

Available isolation fields:
- `agent` - The agent/bot identity
- `channel` - The channel or conversation ID
- `user` - The user interacting with the agent
- `provider` - The message provider (e.g. Slack, Discord)

Use `bankIdPrefix` to namespace bank IDs across environments (e.g. `"prod"`, `"staging"`). Set `dynamicBankId` to `false` to use a single shared bank for all conversations.

### Retention Controls

By default, the plugin retains `user` and `assistant` messages after each turn. You can customize this behavior:

```json
{
  "plugins": {
    "entries": {
      "atulya-openclaw": {
        "enabled": true,
        "config": {
          "autoRetain": true,
          "retainRoles": ["user", "assistant", "system"]
        }
      }
    }
  }
}
```

- `autoRetain` - Set to `false` to disable automatic retention entirely (useful if you handle retention yourself)
- `retainRoles` - Controls which message roles are included in the retained transcript. Only messages from the last user message onward are retained each turn, preventing duplicate storage.

### LLM Configuration

The plugin auto-detects your LLM provider from these environment variables:

| Provider | Env Var | Default Model | Notes |
|----------|---------|---------------|-------|
| OpenAI | `OPENAI_API_KEY` | `gpt-4o-mini` | |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-3-5-haiku-20241022` | |
| Gemini | `GEMINI_API_KEY` | `gemini-2.5-flash` | |
| Groq | `GROQ_API_KEY` | `openai/gpt-oss-20b` | |
| Claude Code | `ATULYA_API_LLM_PROVIDER=claude-code` | `claude-sonnet-4-20250514` | No API key needed |
| OpenAI Codex | `ATULYA_API_LLM_PROVIDER=openai-codex` | `gpt-4o-mini` | No API key needed |

**Override with explicit config:**

```bash
export ATULYA_API_LLM_PROVIDER=openai
export ATULYA_API_LLM_MODEL=gpt-4o-mini
export ATULYA_API_LLM_API_KEY=sk-your-key

# Optional: custom base URL (OpenRouter, Azure, vLLM, etc.)
export ATULYA_API_LLM_BASE_URL=https://openrouter.ai/api/v1
```

**Example: Free OpenRouter model**

```bash
export ATULYA_API_LLM_PROVIDER=openai
export ATULYA_API_LLM_MODEL=xiaomi/mimo-v2-flash  # FREE!
export ATULYA_API_LLM_API_KEY=sk-or-v1-your-openrouter-key
export ATULYA_API_LLM_BASE_URL=https://openrouter.ai/api/v1
```

### External API (Advanced)

Connect to a remote Atulya API server instead of running a local daemon. This is useful for:

- **Shared memory** across multiple OpenClaw instances
- **Production deployments** with centralized memory storage
- **Team environments** where agents share knowledge

#### Plugin Configuration

Configure in `~/.openclaw/openclaw.json`:

```json
{
  "plugins": {
    "entries": {
      "atulya-openclaw": {
        "enabled": true,
        "config": {
          "atulyaApiUrl": "https://your-atulya-server.com",
          "atulyaApiToken": "your-api-token"
        }
      }
    }
  }
}
```

**Options:**
- `atulyaApiUrl` - Full URL to external Atulya API (e.g., `https://mcp.atulya.example.com`)
- `atulyaApiToken` - API token for authentication (optional, only if API requires auth)

#### Environment Variables (Alternative)

You can also configure via environment variables:

```bash
export ATULYA_EMBED_API_URL=https://your-atulya-server.com
export ATULYA_EMBED_API_TOKEN=your-api-token  # Optional

openclaw gateway
```

**Note:** Plugin config takes precedence over environment variables.

#### Behavior

When external API mode is enabled:
- **No local daemon** is started (no atulya-embed process)
- **Health check** runs on startup to verify API connectivity
- **All memory operations** (retain, recall, reflect) go to the external API
- **Faster startup** since no local PostgreSQL or embedding models are needed

#### Verification

Check OpenClaw logs for external API mode:

```bash
tail -f /tmp/openclaw/openclaw-*.log | grep Atulya

# Should see on startup:
# [Atulya] External API mode enabled: https://your-atulya-server.com
# [Atulya] External API health check passed
```

If you see daemon startup messages instead, verify your configuration is correct.

## Inspecting Memories

### Check Configuration

View the daemon config that was written by the plugin:

```bash
cat ~/.atulya/profiles/openclaw.env
```

This shows the LLM provider, model, port, and other settings the daemon is using.

### Check Daemon Status

```bash
# Check if daemon is running
uvx atulya-embed@latest -p openclaw daemon status

# View daemon logs
tail -f ~/.atulya/profiles/openclaw.log
```

### Query Memories

```bash
# Search memories
uvx atulya-embed@latest -p openclaw memory recall openclaw "user preferences"

# View recent memories
uvx atulya-embed@latest -p openclaw memory list openclaw --limit 10

# Open web UI (uses openclaw profile's daemon)
uvx atulya-embed@latest -p openclaw ui
```

## Troubleshooting

### Plugin not loading

```bash
openclaw plugins list | grep atulya
# Should show: ✓ enabled │ Atulya Memory │ ...

# Reinstall if needed
openclaw plugins install @eight-atulya/atulya-openclaw
```

### Daemon not starting

```bash
# Check daemon status (note: -p openclaw uses the openclaw profile)
uvx atulya-embed@latest -p openclaw daemon status

# View logs for errors
tail -f ~/.atulya/profiles/openclaw.log

# Check configuration
cat ~/.atulya/profiles/openclaw.env

# List all profiles
uvx atulya-embed@latest profile list
```

### No API key error

Make sure you've set one of the provider API keys (or use a provider that doesn't require one):

```bash
# Option 1: OpenAI
export OPENAI_API_KEY="sk-your-key"

# Option 2: Anthropic
export ANTHROPIC_API_KEY="your-key"

# Option 3: Claude Code (no API key needed)
export ATULYA_API_LLM_PROVIDER=claude-code

# Option 4: OpenAI Codex (no API key needed)
export ATULYA_API_LLM_PROVIDER=openai-codex

# Verify it's set
echo $OPENAI_API_KEY
# or
echo $ATULYA_API_LLM_PROVIDER
```

### Verify it's working

Check gateway logs for memory operations:

```bash
tail -f /tmp/openclaw/openclaw-*.log | grep Atulya

# Should see on startup:
# [Atulya] ✓ Using provider: openai, model: gpt-4o-mini
# or
# [Atulya] ✓ Using provider: claude-code, model: claude-sonnet-4-20250514

# Should see after conversations:
# [Atulya] Retained X messages for session ...
# [Atulya] Auto-recall: Injecting X memories
```
