---
sidebar_position: 6
---

# CrewAI + Atulya Memory


:::info Complete Application
This is a complete, runnable application demonstrating Atulya integration.
[**View source on GitHub →**](https://github.com/eight-atulya/atulya-cookbook/tree/main/applications/crewai-memory)
:::


Give your CrewAI crews persistent long-term memory. Run a crew multiple times and watch it build on what it learned in previous runs.

## What This Demonstrates

- **Drop-in memory backend** for CrewAI via `atulya-crewai`
- **Persistent memory across runs** - crews remember previous research
- **Reflect tool** - agents explicitly reason over past memories
- **Bank missions** - guide how Atulya organizes memories

## Architecture

```
Run 1: "Research Rust benefits"
    │
    ├─ Researcher agent ──► Atulya reflect (no prior memories)
    │                        ──► produces research findings
    ├─ Writer agent ────────► summarizes findings
    │
    └─ CrewAI auto-stores task outputs to Atulya
                    │
Run 2: "Compare Rust with Go"
    │
    ├─ Researcher agent ──► Atulya reflect (recalls Rust research!)
    │                        ──► builds on prior knowledge
    ├─ Writer agent ────────► writes comparative summary
    │
    └─ Memories accumulate across runs
```

## Prerequisites

1. **Atulya running**

   ```bash
   export OPENAI_API_KEY=your-key

   docker run --rm -it --pull always -p 8888:8888 -p 9999:9999 \
     -e ATULYA_API_LLM_API_KEY=$OPENAI_API_KEY \
     -e ATULYA_API_LLM_MODEL=o3-mini \
     -v $HOME/.atulya-docker:/home/atulya/.pg0 \
     ghcr.io/eight-atulya/atulya:latest
   ```

2. **OpenAI API key** (for CrewAI's LLM)

   ```bash
   export OPENAI_API_KEY=your-key
   ```

3. **Install dependencies**

   ```bash
   cd applications/crewai-memory
   pip install -r requirements.txt
   ```

   > **Note:** `atulya-crewai` is not on PyPI — it is installed directly from the
   > [Atulya repo](https://github.com/eight-atulya/atulya/tree/main/atulya-integrations/crewai) via git.

## Quick Start

```bash
# First run - the crew has no memories yet
python research_crew.py "What are the benefits of Rust?"

# Second run - the crew remembers the Rust research
python research_crew.py "Compare Rust with Go"

# Third run - the crew has context from both prior runs
python research_crew.py "Which language should I pick for a CLI tool?"

# Reset memory and start fresh
python research_crew.py --reset
```

## How It Works

### 1. Configure Atulya

```python
from atulya_crewai import configure, AtulyaStorage

configure(atulya_api_url="http://localhost:8888", verbose=True)

storage = AtulyaStorage(
    bank_id="research-crew",
    mission="Track technology research findings, comparisons, and recommendations.",
)
```

### 2. Add the Reflect Tool

The `AtulyaReflectTool` lets agents explicitly query their memories with disposition-aware synthesis:

```python
from atulya_crewai import AtulyaReflectTool

reflect_tool = AtulyaReflectTool(bank_id="research-crew", budget="mid")

researcher = Agent(
    role="Researcher",
    goal="Research topics thoroughly",
    backstory="Always use atulya_reflect to check what you already know.",
    tools=[reflect_tool],
)
```

### 3. Wire Up the Crew

```python
from crewai.memory.external.external_memory import ExternalMemory

crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, summary_task],
    external_memory=ExternalMemory(storage=storage),
)

crew.kickoff()
```

CrewAI automatically:
- **Queries memories** at the start of each task
- **Stores task outputs** after each task completes

## Core Files

| File | Description |
|------|-------------|
| `research_crew.py` | Complete working example with Researcher + Writer agents |
| `requirements.txt` | Python dependencies |

## Customization

### Per-Agent Memory Banks

Give each agent isolated memory:

```python
storage = AtulyaStorage(
    bank_id="my-crew",
    per_agent_banks=True,  # "my-crew-researcher", "my-crew-writer"
)
```

### Custom Bank Resolver

Full control over bank naming:

```python
storage = AtulyaStorage(
    bank_id="my-crew",
    bank_resolver=lambda base, agent: f"{base}-{agent.lower()}" if agent else base,
)
```

### Configuration Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `bank_id` | (required) | Memory bank identifier |
| `mission` | `None` | Guide how Atulya organizes memories |
| `budget` | `"mid"` | Recall budget: low/mid/high |
| `max_tokens` | `4096` | Max tokens for recall results |
| `per_agent_banks` | `False` | Isolate memory per agent |
| `tags` | `None` | Tags applied when storing |
| `verbose` | `False` | Enable logging |

See the [atulya-crewai documentation](https://github.com/eight-atulya/atulya/tree/main/atulya-integrations/crewai) for the full API reference.

## Common Issues

**"Connection refused"**
- Make sure Atulya is running on `localhost:8888`

**"OPENAI_API_KEY not set"**
```bash
export OPENAI_API_KEY=your-key
```

**"No module named 'atulya_crewai'"**
```bash
pip install -r requirements.txt
```

---

**Built with:**
- [CrewAI](https://crewai.com) - Multi-agent orchestration
- [atulya-crewai](https://github.com/eight-atulya/atulya/tree/main/atulya-integrations/crewai) - Atulya storage backend for CrewAI
- [Atulya](https://github.com/eight-atulya/atulya) - Long-term memory for AI agents
