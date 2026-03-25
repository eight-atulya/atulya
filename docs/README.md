# Documentation Map

This repository should be understandable by structure, not by memory.

## Reading order

1. [`../README.md`](../README.md) — project identity and top-level framing.
2. [`protocol/README.md`](protocol/README.md) — protocol documentation index.
3. [`protocol/design-direction.md`](protocol/design-direction.md) — why the protocol should be shaped the way it is.
4. [`protocol/record-model.md`](protocol/record-model.md) — the canonical record system, type system, and extensibility model.
5. [`architecture/knowledge-compression-loop.md`](architecture/knowledge-compression-loop.md) — text-knowledge compression loop for AI agents and MVP plan.

## Documentation rules

- Keep the top-level `README.md` concise and navigational.
- Put protocol decisions in `docs/protocol/`.
- Add new protocol files instead of growing a single giant document whenever a topic becomes independently reviewable.
- Prefer one document per concern: direction, record model, integrations, governance, lifecycle, and examples.

## Intended future layout

As the repository grows, the protocol docs can expand with files such as:

- `docs/protocol/integrations.md`
- `docs/protocol/governance.md`
- `docs/protocol/event-taxonomy.md`
- `docs/protocol/examples/`

The goal is that a future commit has an obvious home before the diff is even written.

## Architecture notes

- Put adaptive intelligence architecture docs in `docs/architecture/`.
- Keep each architecture topic in a dedicated file that can evolve independently.
