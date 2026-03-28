# atulya

`atulya` is the bridge package for Atulya.

It gives users a single command to start their first connection with Atulya from the terminal:

```bash
pip install atulya
atulya
```

On first run, the CLI captures a safe system snapshot and summarizes the machine it is attached to.
The default run is preview-only. To persist that snapshot into memory, run `atulya init --store` after reviewing it.

## What it captures

- operating system and architecture
- hostname and workspace name
- CPU count, memory estimate, and disk summary
- a privacy-preserving network summary
- common toolchain versions such as Python, Node, Docker, Cargo, Git, and uv

## What it avoids

- tokens and secrets
- environment variable dumps
- process lists
- raw network topology dumps

## Usage

```bash
atulya
atulya init --profile laptop
atulya init --print-only
atulya init --store
atulya init --json
```

To persist the snapshot in memory, configure Atulya's normal LLM environment variables before running:

```bash
export ATULYA_API_LLM_PROVIDER=openai
export ATULYA_API_LLM_API_KEY=...
export ATULYA_API_LLM_MODEL=gpt-4o-mini
atulya init --store
```
