---
sidebar_position: 3
---

# CLI Reference

The Atulya CLI provides command-line access to memory operations and bank management.

## Installation

```bash
curl -fsSL https://atulya.eightengine.com/get-cli | bash
```

## Configuration

Configure the API URL:

```bash
# Interactive configuration
atulya configure

# Or set directly
atulya configure --api-url http://localhost:8888

# Or use environment variable (highest priority)
export ATULYA_API_URL=http://localhost:8888
```

## Core Commands

### Retain (Store Memory)

Store a single memory:

```bash
atulya memory retain <bank_id> "Alice works at Google as a software engineer"

# With context
atulya memory retain <bank_id> "Bob loves hiking" --context "hobby discussion"

# Queue for background processing
atulya memory retain <bank_id> "Meeting notes" --async
```

### Retain Files

Bulk import from files:

```bash
# Single file
atulya memory retain-files <bank_id> notes.txt

# Directory (recursive by default)
atulya memory retain-files <bank_id> ./documents/

# With context
atulya memory retain-files <bank_id> meeting-notes.txt --context "team meeting"

# Background processing
atulya memory retain-files <bank_id> ./data/ --async
```

### Recall (Search)

Search memories using semantic similarity:

```bash
atulya memory recall <bank_id> "What does Alice do?"

# With options
atulya memory recall <bank_id> "hiking recommendations" \
  --budget high \
  --max-tokens 8192

# Filter by fact type
atulya memory recall <bank_id> "query" --fact-type world,opinion

# Show trace information
atulya memory recall <bank_id> "query" --trace
```

### Reflect (Generate Response)

Generate a response using memories and bank disposition:

```bash
atulya memory reflect <bank_id> "What do you know about Alice?"

# With additional context
atulya memory reflect <bank_id> "Should I learn Python?" --context "career advice"

# Higher budget for complex questions
atulya memory reflect <bank_id> "Summarize my week" --budget high
```

## Bank Management

### List Banks

```bash
atulya bank list
```

### View Disposition

```bash
atulya bank disposition <bank_id>
```

### View Statistics

```bash
atulya bank stats <bank_id>
```

### Set Bank Name

```bash
atulya bank name <bank_id> "My Assistant"
```

### Set Background

```bash
atulya bank background <bank_id> "I am a helpful AI assistant interested in technology"

# Skip automatic disposition inference
atulya bank background <bank_id> "Background text" --no-update-disposition
```

## Document Management

```bash
# List documents
atulya document list <bank_id>

# Get document details
atulya document get <bank_id> <document_id>

# Delete document and its memories
atulya document delete <bank_id> <document_id>
```

## Entity Management

```bash
# List entities
atulya entity list <bank_id>

# Get entity details
atulya entity get <bank_id> <entity_id>

# Regenerate entity observations
atulya entity regenerate <bank_id> <entity_id>
```

## Output Formats

```bash
# Pretty (default)
atulya memory recall <bank_id> "query"

# JSON
atulya memory recall <bank_id> "query" -o json

# YAML
atulya memory recall <bank_id> "query" -o yaml
```

## Global Options

| Flag | Description |
|------|-------------|
| `-v, --verbose` | Show detailed output including request/response |
| `-o, --output <format>` | Output format: pretty, json, yaml |
| `--help` | Show help |
| `--version` | Show version |

## Control Plane UI

Launch the web-based Control Plane UI directly from the CLI:

```bash
atulya ui
```

This runs the Control Plane locally on port 9999 using the API URL from your configuration. The UI provides:

- **Memory bank management** — Browse and manage all your banks
- **Entity explorer** — Visualize the knowledge graph
- **Query testing** — Interactive recall and reflect testing
- **Operation history** — View ingestion and processing logs

:::tip
The UI command requires Node.js to be installed. It automatically downloads and runs the `@eight-atulya/atulya-control-plane` package via npx.
:::

## Interactive Explorer

Launch the TUI explorer for visual navigation of your memory banks:

```bash
atulya explore
```

The explorer provides an interactive terminal interface to:

- **Browse memory banks** — View all banks and their statistics
- **Search memories** — Run recall queries with real-time results
- **Inspect entities** — Explore the knowledge graph and entity relationships
- **View facts** — Browse world facts, experiences, and opinions
- **Navigate documents** — See source documents and their extracted memories

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `↑/↓` | Navigate items |
| `Enter` | Select / Expand |
| `Tab` | Switch panels |
| `/` | Search |
| `q` | Quit |

<!-- Screenshot placeholder: explore command TUI -->

## Example Workflow

```bash
# Configure API URL
atulya configure --api-url http://localhost:8888

# Store some memories
atulya memory retain demo "Alice works at Google"
atulya memory retain demo "Bob is a data scientist"
atulya memory retain demo "Alice and Bob are colleagues"

# Search memories
atulya memory recall demo "Who works with Alice?"

# Generate a response
atulya memory reflect demo "What do you know about the team?"

# Check bank disposition
atulya bank disposition demo
```
