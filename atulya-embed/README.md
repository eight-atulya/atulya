# atulya-embed

Atulya embedded CLI — a living algorithm for machine intelligence (MI), with local memory operations and automatic daemon management.

This package provides a simple CLI for storing and recalling memories using Atulya's memory engine. It automatically manages a background daemon for fast operations - no manual server setup required.

## How It Works

`atulya-embed` uses a background daemon architecture for optimal performance:

1. **First command**: Automatically starts a local daemon (first run downloads dependencies and loads ML models - can take 1-3 minutes)
2. **Subsequent commands**: Near-instant responses (~1-2s) since daemon is already running
3. **Auto-shutdown**: Daemon automatically exits after 5 minutes of inactivity

The daemon runs on `localhost:8888` and uses an embedded PostgreSQL database (pg0) - everything stays local on your machine.

## Installation

```bash
pip install atulya-embed
# or with uvx (no install needed)
uvx atulya-embed --help
```

## Quick Start

```bash
# Interactive setup (configures default profile)
atulya-embed configure

# Or set your LLM API key manually
export OPENAI_API_KEY=sk-...

# Store a memory (bank_id = "default")
atulya-embed memory retain default "User prefers dark mode"

# Recall memories
atulya-embed memory recall default "What are user preferences?"
```

All commands use the "default" profile unless you specify a different one with `--profile` or `ATULYA_EMBED_PROFILE`.

## Commands

### configure

Configure the default profile or create/update named profiles:

```bash
# Interactive setup for default profile
atulya-embed configure

# Create/update named profile with single command
atulya-embed configure --profile my-app \
  --env ATULYA_EMBED_LLM_PROVIDER=openai \
  --env ATULYA_EMBED_LLM_API_KEY=sk-xxx

# Create/update named profile interactively
atulya-embed configure --profile staging
```

This will:
- Let you choose an LLM provider (OpenAI, Groq, Google, Ollama)
- Configure your API key
- Set the model and memory bank ID
- Start the daemon with your configuration

### memory retain

Store a memory:

```bash
atulya-embed memory retain default "User prefers dark mode"
atulya-embed memory retain default "Meeting on Monday" --context work
atulya-embed memory retain myproject "API uses JWT authentication"
```

### memory recall

Search memories:

```bash
atulya-embed memory recall default "user preferences"
atulya-embed memory recall default "upcoming events"
```

Use `-o json` for JSON output:
```bash
atulya-embed memory recall default "user preferences" -o json
```

### memory reflect

Get contextual answers that synthesize multiple memories:

```bash
atulya-embed memory reflect default "How should I set up the dev environment?"
```

### bank list

List all memory banks:

```bash
atulya-embed bank list
```

### profile

Manage configuration profiles:

```bash
# List all profiles with status
atulya-embed profile list

# Show current active profile
atulya-embed profile show

# Set active profile (persists across commands)
atulya-embed profile set-active my-app

# Clear active profile (revert to default)
atulya-embed profile set-active --none

# Delete a profile
atulya-embed profile delete my-app
```

### daemon

Manage the background daemon:

```bash
atulya-embed daemon status    # Check if daemon is running
atulya-embed daemon start     # Start the daemon
atulya-embed daemon stop      # Stop the daemon
atulya-embed daemon logs      # View last 50 lines of logs
atulya-embed daemon logs -f   # Follow logs in real-time
atulya-embed daemon logs -n 100  # View last 100 lines
```

## Configuration

### Interactive Setup

Run `atulya-embed configure` for a guided setup that saves to `~/.atulya/embed`.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ATULYA_EMBED_PROFILE` | Profile name to use (overrides active profile) | None (uses default profile) |
| `ATULYA_EMBED_LLM_API_KEY` | LLM API key (or use `OPENAI_API_KEY`) | Required |
| `ATULYA_EMBED_LLM_PROVIDER` | LLM provider (`openai`, `groq`, `google`, `ollama`) | `openai` |
| `ATULYA_EMBED_LLM_MODEL` | LLM model | `gpt-4o-mini` |
| `ATULYA_EMBED_BANK_ID` | Default memory bank ID (optional, used when not specified in CLI) | `default` |
| `ATULYA_EMBED_API_URL` | Use external API server instead of starting local daemon | None (starts local daemon) |
| `ATULYA_EMBED_API_TOKEN` | Authentication token for external API (sent as Bearer token) | None |
| `ATULYA_EMBED_API_DATABASE_URL` | Database URL for daemon | `pg0://atulya-embed` |
| `ATULYA_EMBED_DAEMON_IDLE_TIMEOUT` | Seconds before daemon auto-exits when idle | `300` |

**Using an External API Server:**

To connect to an existing Atulya API server instead of starting the local daemon:

```bash
export ATULYA_EMBED_API_URL=http://your-server:8000
export ATULYA_EMBED_API_TOKEN=your-api-token  # Optional, if API requires auth
atulya-embed memory recall default "query"
```

**Custom Database:**

To use an external PostgreSQL database instead of the embedded pg0 database (useful when running as root or in containerized environments):

```bash
export ATULYA_EMBED_API_DATABASE_URL=postgresql://user:password@localhost:5432/dbname
atulya-embed daemon start
```

**Note:** All banks share a single database. Bank isolation happens within the database via the `bank_id` parameter passed to CLI commands.

### Configuration Profiles

Profiles let you maintain multiple independent configurations (e.g., different API endpoints, LLM providers, or projects). Each profile runs its own daemon on a unique port (8889-9888).

**The Default Profile:**

When you run `atulya-embed configure` without specifying a profile, it configures the "default" profile. This uses the backward-compatible configuration at `~/.atulya/embed` and runs on port 8888.

**Creating Named Profiles:**

```bash
# Create a profile with single command
atulya-embed configure --profile my-app \
  --env ATULYA_EMBED_LLM_PROVIDER=openai \
  --env ATULYA_EMBED_LLM_API_KEY=sk-xxx \
  --env ATULYA_EMBED_LLM_MODEL=gpt-4o-mini

# Create a profile interactively
atulya-embed configure --profile staging
```

**Using Profiles:**

```bash
# Option 1: Environment variable (recommended for apps)
ATULYA_EMBED_PROFILE=my-app atulya-embed memory retain default "text"

# Option 2: CLI flag
atulya-embed --profile my-app memory recall default "query"

# Option 3: Set as active (persists across commands)
atulya-embed profile set-active my-app
atulya-embed memory recall default "query"  # Uses my-app profile

# Clear active profile (revert to default)
atulya-embed profile set-active --none
```

**Profile Management:**

```bash
# List all profiles with status
atulya-embed profile list

# Show active profile
atulya-embed profile show

# Delete a profile
atulya-embed profile delete my-app
```

**Profile Resolution Priority:**
1. `ATULYA_EMBED_PROFILE` environment variable (highest)
2. `--profile` CLI flag
3. Active profile from `~/.atulya/active_profile` file
4. Default profile (lowest)

**Note:** If a profile is specified but doesn't exist, the command will fail with an error. Profiles must be explicitly created using `atulya-embed configure --profile <name>`.

### Files

**Default Profile:**
| Path | Description |
|------|-------------|
| `~/.atulya/embed` | Configuration file for default profile |
| `~/.atulya/daemon.log` | Daemon logs for default profile |
| `~/.atulya/daemon.lock` | Daemon lock file (PID) for default profile |

**Named Profiles:**
| Path | Description |
|------|-------------|
| `~/.atulya/profiles/<name>.env` | Configuration file for profile |
| `~/.atulya/profiles/<name>.log` | Daemon logs for profile |
| `~/.atulya/profiles/<name>.lock` | Daemon lock file (PID) for profile |
| `~/.atulya/profiles/metadata.json` | Profile metadata (ports, timestamps) |
| `~/.atulya/active_profile` | Active profile name (when set with `profile set-active`) |

## Use with AI Coding Assistants

This CLI is designed to work with AI coding assistants like Claude Code, Cursor, and Windsurf. Install the Atulya skill:

```bash
npx skills add https://github.com/eight-atulya/atulya --skill atulya-docs
```

This will configure the LLM provider and install the skill to your assistant's skills directory.

## Troubleshooting

**Daemon won't start:**
```bash
# Check logs for errors
atulya-embed daemon logs

# Stop any stuck daemon and restart
atulya-embed daemon stop
atulya-embed daemon start
```

**Slow first command:**
This is expected - the first command needs to download dependencies, start the daemon, and load ML models. First run can take 1-3 minutes depending on network speed. Subsequent commands will be fast (~1-2s).

**Change configuration:**
```bash
# Re-run configure (automatically restarts daemon)
atulya-embed configure
```

## License

Apache 2.0
