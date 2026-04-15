"""Curated per-bank configuration presets for create/update bank APIs.

Presets are merged into bank config before explicit request fields (explicit wins).
Keep text lean: retain_custom_instructions replaces the default extraction guideline block.
"""

from __future__ import annotations

import uuid
from typing import Any

_PRESET_MM_NAMESPACE = uuid.UUID("612e9610-4b14-4f6d-a58b-9aae18f7c1e0")


def _preset_mental_model_id(part: str) -> str:
    """Stable mental model id per preset fragment (composite PK with bank_id)."""
    return str(uuid.uuid5(_PRESET_MM_NAMESPACE, f"codebase|{part}"))


_CODEBASE_RETAIN_CUSTOM = """\
══════════════════════════════════════════════════════════════════════════
CODEBASE / REPOSITORY EXTRACTION (ASD-reviewed chunks, source, diffs)
══════════════════════════════════════════════════════════════════════════

ONLY extract facts that help future engineering work:
- APIs, contracts, invariants, error paths, security-sensitive flows
- Dependencies between modules, notable coupling, migration or rollout risks
- Decisions with rationale (why this design, trade-offs, rejected alternatives)
- Test or operational constraints tied to specific paths or symbols
- TODO/FIXME/HACK only when they encode real risk or unfinished obligations

DO NOT extract:
- Boilerplate imports or obvious syntax with no behavioral meaning
- Duplicates of the same fact already stated in the chunk header or context line
- Generic praise, process chatter, or placeholders without technical substance

When the input includes a leading line like `# path lines L-L`, treat path and line
range as authoritative provenance; restate them in `what` or supporting text when
the fact depends on location.

Prefer `world` / durable technical facts. Keep entities limited to code-relevant
symbols, services, repos, and people only when tied to ownership or decisions.

LANGUAGE: Output MUST match the language of the substantive technical content in
the input (comments and identifiers may be mixed; follow the dominant natural language
of the explained behavior).
"""

_CODEBASE_RETAIN_MISSION = (
    "Optimize for repository memory: retain implementation truth, contracts, and risk "
    "that engineers would need months later when debugging or extending the system."
)

_CODEBASE_REFLECT_MISSION = (
    "You reason over a codebase-backed memory bank. Prefer facts tied to file paths, "
    "line ranges, and symbols. If evidence is thin or chunks were unrouted, say so. "
    "Do not invent APIs, callers, or file structure."
)

_CODEBASE_OBSERVATIONS_MISSION = (
    "Synthesize stable engineering observations: architectural layers, ownership boundaries, "
    "recurrent failure modes, and cross-cutting utilities. Ground every observation in "
    "supported facts; note uncertainty when consolidation is weak."
)

BANK_PRESET_CONFIG: dict[str, dict[str, Any]] = {
    "codebase": {
        "retain_extraction_mode": "custom",
        "retain_mission": _CODEBASE_RETAIN_MISSION,
        "retain_custom_instructions": _CODEBASE_RETAIN_CUSTOM,
        "reflect_mission": _CODEBASE_REFLECT_MISSION,
        "observations_mission": _CODEBASE_OBSERVATIONS_MISSION,
        "enable_observations": True,
    },
}


def merge_bank_preset(preset_key: str | None, explicit_updates: dict[str, Any]) -> dict[str, Any]:
    """Return config updates: preset base overlaid by explicit (non-empty) request fields."""
    key = (preset_key or "").strip().lower()
    if key not in BANK_PRESET_CONFIG:
        return dict(explicit_updates)
    merged = dict(BANK_PRESET_CONFIG[key])
    merged.update(explicit_updates)
    return merged


CODEBASE_SEED_DIRECTIVE: dict[str, Any] = {
    "name": "Codebase: evidence-first answers",
    "content": (
        "When answering from this bank's codebase-backed memories, treat file path and line range "
        "in stored facts as primary provenance. Prefer memories tagged with codebase scope over "
        "generic speculation. If routed chunks or facts are missing, say so instead of inventing "
        "APIs, call graphs, or file layout."
    ),
    "priority": 40,
    "tags": ["preset:codebase"],
}

CODEBASE_SEED_MENTAL_MODELS: list[dict[str, Any]] = [
    {
        "id": _preset_mental_model_id("workflow"),
        "name": "Codebase review → memory workflow",
        "source_query": "What is the recommended workflow from import to hydrated memory for a repository bank?",
        "tags": ["preset:codebase", "developer-guide"],
        "content": """## End-to-end workflow

1. **Import** a snapshot (ZIP or supported GitHub path) so files are indexed and ASD chunks exist.
2. **Review** chunks in the control plane: check symbols, regions, and routing targets.
3. **Route** unrouted items to memory (or research) so only intentional code enters retain.
4. **Approve** the snapshot when review is complete so retain/direct hydration can run.
5. **Recall & reflect** using this bank — facts should carry path/line context from ingestion.

Re-run approval when the tree changes materially so hashes and routes stay honest.""",
    },
    {
        "id": _preset_mental_model_id("reading-memories"),
        "name": "How to read code-backed memories",
        "source_query": "How should developers interpret retained code facts, headers, and previews?",
        "tags": ["preset:codebase", "developer-guide"],
        "content": """## Interpreting stored code

- **Chunk text** often begins with a `# path … lines L–H` header baked in at index time — keep it when quoting.
- **Structured columns** (`path`, `start_line`, `end_line`) mirror the same span for APIs and filters.
- **Previews** collapse whitespace; open full chunk detail when you need exact text.
- **Tags** such as `scope:codebase` and `codebase:<id>` scope recall — include them when debugging hydration.

Use **retain** outputs for narrative facts; pair them with **recall** for verbatim evidence when auditing.""",
    },
    {
        "id": _preset_mental_model_id("operating-tips"),
        "name": "Operating tips for engineering banks",
        "source_query": "What practical tips keep codebase memory banks accurate and cheap to run?",
        "tags": ["preset:codebase", "developer-guide"],
        "content": """## Keep the bank trustworthy

- **Route deliberately**: sending noise to memory pollutes embeddings; prefer research or dismiss for generated assets.
- **Refresh after refactors**: line keys change when symbols move; expect re-review when diffs are large.
- **Lean on observations**: with observations enabled, let consolidation summarize cross-file themes instead of duplicating them in every retain call.
- **Reflect honestly**: if the bank is sparse, say so — partial coverage beats confident hallucination.

You can edit or delete these starter cards anytime; they are tagged `preset:codebase`.""",
    },
]
