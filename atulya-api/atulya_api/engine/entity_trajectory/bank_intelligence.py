"""Bank-level entity intelligence built from entity inventory + trajectories."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Any

import tiktoken
from pydantic import ValidationError

from atulya_api.engine.entity_trajectory.intelligence_persisted_row import entity_intelligence_payload_from_record
from atulya_api.engine.jsonb_compat import decode_jsonb
from atulya_api.engine.llm_wrapper import parse_llm_json
from atulya_api.engine.memory_engine import fq_table
from atulya_api.engine.reflect.delta_ops import DeltaOperationList, apply_operations
from atulya_api.engine.reflect.structured_doc import (
    BulletListBlock,
    ParagraphBlock,
    Section,
    StructuredDocument,
    parse_markdown,
    render_document,
)

if TYPE_CHECKING:
    import asyncpg

    from atulya_api.engine.llm_wrapper import LLMConfig

logger = logging.getLogger(__name__)

_PROMPT_VERSION = "v2-digital-person-map"
_ENCODING = tiktoken.get_encoding("cl100k_base")

_FULL_SYSTEM_PROMPT = """You synthesize bank-level entity intelligence from a structured entity map.

This is not a generic summary. Build a "digital person" from the bank:
- identity anchors: what the user/system repeatedly centers on
- people circles: humans around the user, grouped by relational gravity
- operating system: tools, companies, projects, hardware, platforms, and workflows
- mind map: concepts, anxieties, ambitions, values, decisions, and recurring states
- relationship graph: which entities co-occur and what that suggests
- forward possibilities: grounded next developments, leverage points, and blind spots

Use only the supplied categories, circles, entity counts, relationships, trajectories,
forecasts, and fact previews. Be insightful and causal, but do not invent specific
events, people, or facts not implied by the inventory. Prefer "what this reveals about
the bank/person/system" over repeating entity names. Call out confidence and uncertainty.

Write in plain language. No jargon. If you use a technical term, explain what it means
in the same sentence.

Make the entity representation rich and useful:
- Name the important entities and say what type each appears to be: person, tool, company,
  project, place, event, concept, or unknown.
- Explain the strongest connections between entities in human terms. For example:
  "Antara Das appears close to the user's life context because she co-occurs with marriage
  planning and personal-state facts."
- Use metadata when present: root_type, type_confidence, role_hint, type_evidence, trajectory
  state, forecast, mention count, first/last seen, and relationship count.
- Separate confirmed signals from uncertain signals. Do not pretend weak metadata is certain.
- Prefer concrete entity maps over vague summaries. A useful section should help the reader
  understand who/what exists in the bank, how they relate, and what can be learned next.

Recommended sections:
1. Digital Person Snapshot - what this bank/person/system is mostly about.
2. People Circles - human names, role hints, relationship strength, and uncertainty.
3. Tools, Companies, and Projects - what powers the person's work or environment.
4. Connection Map - important entity-to-entity connections and what each connection means.
5. Mind and Life Themes - recurring concepts, goals, concerns, and decisions.
6. What This Lets Us Predict - likely next needs, risks, and opportunities grounded in evidence.
7. Unknowns to Resolve - ambiguous entities or missing metadata worth clarifying.

Return ONLY JSON matching this schema:
{
  "version": 1,
  "sections": [
    {
      "id": "stable-kebab-id",
      "heading": "Section title",
      "level": 2,
      "blocks": [
        {"type": "paragraph", "text": "..."},
        {"type": "bullet_list", "items": ["..."]}
      ]
    }
  ]
}
"""

_DELTA_SYSTEM_PROMPT = """You update an existing bank-level entity intelligence document.

Return ONLY JSON with one key, "operations", containing structured delta operations against
the current document. Preserve sections that still apply. Prefer small targeted replacements
over rewriting the whole document. Use only the new entity inventory; do not invent facts.
Valid ops: append_block, insert_block, replace_block, remove_block, add_section,
remove_section, replace_section_blocks, rename_section.

Keep the document shaped as digital-person intelligence: people circles, operating system,
mind map, relationship graph, risks/opportunities, and forward possibilities.
Use plain language with no unexplained jargon. Preserve or add clear entity connection detail:
important entities, their likely type, role hints, relationship counts, confidence, and what
each connection means.
"""

_ORG_TERMS = {
    "ai",
    "app",
    "bank",
    "company",
    "corp",
    "corporation",
    "github",
    "google",
    "inc",
    "labs",
    "llc",
    "microsoft",
    "nvidia",
    "openai",
    "organization",
    "platform",
    "studio",
    "team",
    "whatsapp",
}
_TOOL_TERMS = {
    "api",
    "browser",
    "cli",
    "codex",
    "cursor",
    "db",
    "docker",
    "embedding",
    "engine",
    "gpu",
    "hmm",
    "intel",
    "json",
    "llm",
    "lmstudio",
    "memory",
    "model",
    "next",
    "postgres",
    "python",
    "react",
    "server",
    "sql",
    "token",
    "tool",
    "typescript",
    "ui",
    "uv",
    "worker",
}
_PROJECT_TERMS = {
    "agent",
    "atulya",
    "brain",
    "cortex",
    "entity",
    "feature",
    "intelligence",
    "memory",
    "pipeline",
    "project",
    "trajectory",
}
_GOAL_EVENT_TERMS = {
    "decision",
    "goal",
    "marriage",
    "meeting",
    "migration",
    "plan",
    "release",
    "task",
    "wedding",
}
_SELF_TERMS = {"i", "me", "myself", "self", "user", "atulya-agent"}
_HUMAN_PREFIXES = {"mr", "mrs", "ms", "dr", "prof"}
_TITLE_WORD_RE = re.compile(r"^[A-Z][a-zA-Z'.-]+$")


def _token_count(value: Any) -> int:
    return len(_ENCODING.encode(value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))))


def _top_forecast(forecast: Any, *, limit: int = 2) -> str:
    data = decode_jsonb(forecast, {})
    if not isinstance(data, dict):
        return ""
    pairs: list[tuple[str, float]] = []
    for key, raw in data.items():
        try:
            pairs.append((str(key), float(raw)))
        except (TypeError, ValueError):
            continue
    pairs.sort(key=lambda item: item[1], reverse=True)
    return ",".join(f"{name}:{value:.2f}" for name, value in pairs[:limit])


def _recent_previews(viterbi_path: Any, *, limit: int = 2) -> list[str]:
    data = decode_jsonb(viterbi_path, [])
    if not isinstance(data, list):
        return []
    previews: list[str] = []
    for item in data[-limit:]:
        if isinstance(item, dict) and item.get("fact_preview"):
            previews.append(str(item["fact_preview"])[:180])
    return previews


def _dt(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)[:10]


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except (KeyError, TypeError):
        value = default
    return default if value is None else value


def _entity_metadata(row: Any) -> dict[str, Any]:
    metadata = decode_jsonb(_row_get(row, "metadata"), {})
    return metadata if isinstance(metadata, dict) else {}


def _words(name: str) -> list[str]:
    return [part for part in re.split(r"[^A-Za-z0-9_+.#-]+", name) if part]


def categorize_entity_name(name: str, metadata: dict[str, Any] | None = None) -> str:
    """Classify an entity into a coarse digital-person category.

    Entity extraction is intentionally provider-agnostic today, so this uses
    stable metadata when available and conservative name heuristics otherwise.
    The LLM receives the category as evidence, not as an unquestionable truth.
    """

    metadata = metadata or {}
    classification = metadata.get("classification")
    raw_type = str(
        metadata.get("entity_type") or (classification.get("entity_type") if isinstance(classification, dict) else "")
    ).lower()
    if not raw_type:
        raw_type = str(metadata.get("type") or metadata.get("kind") or metadata.get("label") or "").lower()
    if raw_type in {"person", "human", "people"}:
        return "human_name"
    if raw_type in {"org", "organization", "company", "company_name"}:
        return "organization"
    if raw_type in {"tool", "technology", "software", "hardware", "model"}:
        return "tool_technology"
    if raw_type in {"project", "product", "codebase"}:
        return "project_product"
    if raw_type in {"location", "place", "city", "country"}:
        return "place"
    if raw_type == "event":
        return "event_goal"
    if raw_type == "artifact":
        return "digital_artifact"
    if raw_type == "concept":
        return "concept_theme"

    stripped = name.strip()
    lower = stripped.lower()
    tokens = _words(stripped)
    token_set = {token.lower().strip(".,:;()[]{}") for token in tokens}

    if lower in _SELF_TERMS:
        return "self_anchor"
    if any(marker in lower for marker in ("http://", "https://", "@", ".com", ".net", ".org")):
        return "digital_artifact"
    if token_set & _TOOL_TERMS or any(ch in stripped for ch in ("/", "\\", "_")):
        return "tool_technology"
    if token_set & _ORG_TERMS:
        return "organization"
    if token_set & _PROJECT_TERMS:
        return "project_product"
    if token_set & _GOAL_EVENT_TERMS:
        return "event_goal"
    if lower.endswith((".py", ".ts", ".tsx", ".json", ".md", ".yaml", ".yml")):
        return "digital_artifact"
    if (
        2 <= len(tokens) <= 4
        and (tokens[0].rstrip(".").lower() in _HUMAN_PREFIXES or all(_TITLE_WORD_RE.match(token) for token in tokens))
        and not (token_set & (_ORG_TERMS | _TOOL_TERMS | _PROJECT_TERMS))
    ):
        return "human_name"
    if len(tokens) == 1 and tokens[0][:1].isupper() and lower not in _PROJECT_TERMS:
        return "human_or_named_thing"
    return "concept_theme"


def _circle_for_entity(category: str, mentions: int) -> str:
    if category == "self_anchor":
        return "self"
    if category in {"human_name", "human_or_named_thing"}:
        if mentions >= 12:
            return "inner_people"
        if mentions >= 4:
            return "active_people"
        return "peripheral_people"
    if category == "tool_technology":
        return "operating_tools"
    if category == "organization":
        return "institutions_platforms"
    if category == "project_product":
        return "projects_products"
    if category in {"event_goal", "place"}:
        return "life_context"
    if category == "digital_artifact":
        return "artifacts_surfaces"
    return "mind_themes"


def _entity_line(row: Any, *, include_forecast: bool, include_previews: bool) -> dict[str, Any]:
    metadata = _entity_metadata(row)
    name = str(_row_get(row, "canonical_name", ""))[:120]
    mentions = int(_row_get(row, "mention_count", 0) or 0)
    category = categorize_entity_name(name, metadata)
    line: dict[str, Any] = {
        "id": str(_row_get(row, "id", "")),
        "name": name,
        "category": category,
        "circle": _circle_for_entity(category, mentions),
        "mentions": mentions,
        "first_seen": _dt(_row_get(row, "first_seen")),
        "last_seen": _dt(_row_get(row, "last_seen")),
    }
    if metadata.get("entity_type"):
        line["root_type"] = metadata.get("entity_type")
    if metadata.get("entity_type_confidence") is not None:
        line["type_confidence"] = metadata.get("entity_type_confidence")
    if metadata.get("role_hint"):
        line["role_hint"] = str(metadata.get("role_hint"))[:120]
    if metadata.get("entity_type_evidence"):
        line["type_evidence"] = str(metadata.get("entity_type_evidence"))[:160]
    state = _row_get(row, "current_state")
    if state:
        line["state"] = str(state)[:80]
    anomaly = _row_get(row, "anomaly_score")
    if anomaly is not None:
        try:
            line["anomaly"] = round(float(anomaly), 3)
        except (TypeError, ValueError):
            pass
    if include_forecast:
        forecast = _top_forecast(_row_get(row, "forecast_distribution"))
        if forecast:
            line["forecast"] = forecast
    if include_previews:
        previews = _recent_previews(_row_get(row, "viterbi_path"))
        if previews:
            line["recent"] = previews
    return line


def _relationship_line(row: Any, *, name_by_id: dict[str, str], category_by_id: dict[str, str]) -> dict[str, Any]:
    left_id = str(_row_get(row, "entity_id_1", ""))
    right_id = str(_row_get(row, "entity_id_2", ""))
    count = int(_row_get(row, "cooccurrence_count", 0) or 0)
    return {
        "a": name_by_id.get(left_id, left_id)[:120],
        "a_category": category_by_id.get(left_id, "unknown"),
        "b": name_by_id.get(right_id, right_id)[:120],
        "b_category": category_by_id.get(right_id, "unknown"),
        "count": count,
        "last": _dt(_row_get(row, "last_cooccurred")),
    }


def _top_entities(entities: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entity in sorted(entities, key=lambda item: (-int(item.get("mentions", 0) or 0), item.get("name", "")))[:limit]:
        item = {
            "name": entity["name"],
            "mentions": entity.get("mentions", 0),
            "category": entity.get("category"),
            "state": entity.get("state"),
        }
        for key in (
            "root_type",
            "type_confidence",
            "role_hint",
            "type_evidence",
            "first_seen",
            "last_seen",
            "forecast",
        ):
            if entity.get(key):
                item[key] = entity[key]
        out.append(item)
    return out


def _build_digital_person_map(
    entities: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> dict[str, Any]:
    categories = Counter(str(entity.get("category", "unknown")) for entity in entities)
    circles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entity in entities:
        circle = str(entity.get("circle") or "uncategorized")
        if len(circles[circle]) < 10:
            circles[circle].append(
                {
                    "name": entity["name"],
                    "category": entity.get("category"),
                    "mentions": entity.get("mentions", 0),
                    "state": entity.get("state"),
                }
            )

    strong_people = [
        entity for entity in entities if entity.get("category") in {"self_anchor", "human_name", "human_or_named_thing"}
    ]
    operating_system = [
        entity
        for entity in entities
        if entity.get("category") in {"tool_technology", "organization", "project_product", "digital_artifact"}
    ]
    mind_themes = [entity for entity in entities if entity.get("category") in {"concept_theme", "event_goal", "place"}]
    cross_circle_relationships = [rel for rel in relationships if rel.get("a_category") != rel.get("b_category")][:24]

    return {
        "category_counts": dict(categories.most_common()),
        "circles": dict(circles),
        "identity_anchors": _top_entities(
            [entity for entity in entities if entity.get("circle") in {"self", "projects_products"}],
            limit=10,
        ),
        "people_system": _top_entities(strong_people, limit=16),
        "operating_system": _top_entities(operating_system, limit=18),
        "mind_map_themes": _top_entities(mind_themes, limit=18),
        "strong_relationships": relationships[:40],
        "cross_circle_relationships": cross_circle_relationships,
        "high_confidence_typed_entities": [
            {
                "name": entity["name"],
                "root_type": entity.get("root_type"),
                "confidence": entity.get("type_confidence"),
                "role_hint": entity.get("role_hint"),
                "evidence": entity.get("type_evidence"),
                "mentions": entity.get("mentions", 0),
            }
            for entity in entities
            if entity.get("root_type") and float(entity.get("type_confidence") or 0.0) >= 0.7
        ][:30],
        "ambiguous_entities": [
            {
                "name": entity["name"],
                "category": entity.get("category"),
                "mentions": entity.get("mentions", 0),
                "reason": "No root entity_type metadata yet; category comes from fallback evidence.",
            }
            for entity in entities
            if not entity.get("root_type") and entity.get("category") in {"human_or_named_thing", "concept_theme"}
        ][:20],
    }


def build_entity_intelligence_context(
    rows: list[Any],
    *,
    source_entity_count: int,
    max_context_tokens: int,
    min_entities: int,
    relationship_rows: list[Any] | None = None,
) -> dict[str, Any]:
    """Build a compact, token-budgeted entity inventory for the LLM."""

    include_forecast = True
    include_previews = True
    included_rows = list(rows)

    def make_context() -> dict[str, Any]:
        entities = [
            _entity_line(row, include_forecast=include_forecast, include_previews=include_previews)
            for row in included_rows
        ]
        name_by_id = {entity["id"]: entity["name"] for entity in entities}
        category_by_id = {entity["id"]: entity["category"] for entity in entities}
        relationships = [
            _relationship_line(row, name_by_id=name_by_id, category_by_id=category_by_id)
            for row in relationship_rows or []
            if str(_row_get(row, "entity_id_1", "")) in name_by_id
            and str(_row_get(row, "entity_id_2", "")) in name_by_id
        ]
        return {
            "source_entity_count": source_entity_count,
            "included_entity_count": len(entities),
            "omitted_entity_count": max(0, source_entity_count - len(entities)),
            "map_version": "digital-person-v2",
            "digital_person_map": _build_digital_person_map(entities, relationships),
            "entities": entities,
        }

    context = make_context()
    if _token_count(context) <= max_context_tokens:
        return context

    include_previews = False
    context = make_context()
    if _token_count(context) <= max_context_tokens:
        context["compaction"] = "dropped_recent_fact_previews"
        return context

    include_forecast = False
    context = make_context()
    if _token_count(context) <= max_context_tokens:
        context["compaction"] = "dropped_recent_fact_previews_and_forecasts"
        return context

    while len(included_rows) > min_entities and _token_count(context) > max_context_tokens:
        included_rows.pop()
        context = make_context()
    context["compaction"] = "truncated_lowest_signal_entities"
    return context


def _default_document(context: dict[str, Any]) -> StructuredDocument:
    count = int(context.get("included_entity_count") or 0)
    source_count = int(context.get("source_entity_count") or count)
    return StructuredDocument(
        sections=[
            Section(
                id="digital-person",
                heading="Digital Person",
                blocks=[
                    ParagraphBlock(
                        text=(
                            f"This bank currently exposes {count} of {source_count} entities for analysis. "
                            "The intelligence layer needs a successful LLM run before it can build the deeper "
                            "people, tools, company, project, and concept map."
                        )
                    )
                ],
            ),
            Section(
                id="people-circles",
                heading="People Circles",
                blocks=[BulletListBlock(items=["No generated people-circle map yet."])],
            ),
            Section(
                id="operating-system",
                heading="Operating System",
                blocks=[BulletListBlock(items=["No generated tool/company/project map yet."])],
            ),
            Section(
                id="forward-possibilities",
                heading="Forward Possibilities",
                blocks=[BulletListBlock(items=["No generated possibilities yet."])],
            ),
        ]
    )


def _parse_structured_document(raw: Any, *, context: dict[str, Any]) -> StructuredDocument:
    if isinstance(raw, StructuredDocument):
        return raw
    if isinstance(raw, dict):
        return StructuredDocument.model_validate(raw)
    if isinstance(raw, str):
        try:
            parsed = parse_llm_json(raw)
            if isinstance(parsed, dict):
                return StructuredDocument.model_validate(parsed)
        except Exception:
            markdown_doc = parse_markdown(raw)
            if markdown_doc.sections:
                return markdown_doc
    return _default_document(context)


def _parse_delta_text(raw: Any) -> DeltaOperationList:
    if isinstance(raw, DeltaOperationList):
        return raw
    if isinstance(raw, dict):
        return DeltaOperationList.model_validate(raw)
    if not isinstance(raw, str):
        raise TypeError(f"delta LLM returned {type(raw).__name__}")
    try:
        parsed = parse_llm_json(raw)
        return DeltaOperationList.model_validate(parsed)
    except Exception:
        return DeltaOperationList.model_validate_json(raw)


def _snapshot_hash(context: dict[str, Any]) -> str:
    stable = json.dumps(context, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode()).hexdigest()[:32]


async def fetch_previous_entity_intelligence(
    conn: "asyncpg.Connection",
    *,
    bank_id: str,
) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        f"""
        SELECT bank_id, computed_at, entity_count, source_entity_count, entity_snapshot_hash,
               content, structured_content, entity_context, delta_metadata, llm_model, prompt_version
        FROM {fq_table("entity_intelligence")}
        WHERE bank_id = $1
        """,
        bank_id,
    )
    if not row:
        return None
    return entity_intelligence_payload_from_record(row)


class EntityIntelligenceService:
    """Compute and upsert bank-level entity intelligence."""

    @staticmethod
    async def compute_and_persist(
        conn: "asyncpg.Connection",
        *,
        bank_id: str,
        llm_config: "LLMConfig",
        resolved_config: Any,
    ) -> bool:
        if not getattr(resolved_config, "enable_entity_intelligence", False):
            return False

        min_entities = int(getattr(resolved_config, "entity_intelligence_min_entities", 8))
        max_entities = int(getattr(resolved_config, "entity_intelligence_max_entities", 2000))
        max_context_tokens = int(getattr(resolved_config, "entity_intelligence_max_context_tokens", 10_000))
        max_completion_tokens = int(getattr(resolved_config, "entity_intelligence_max_completion_tokens", 4096))
        llm_max_retries = int(
            getattr(
                resolved_config,
                "entity_intelligence_llm_max_retries",
                getattr(resolved_config, "llm_max_retries", 3),
            )
            or 3
        )
        llm_initial_backoff = float(
            getattr(
                resolved_config,
                "entity_intelligence_llm_initial_backoff",
                getattr(resolved_config, "llm_initial_backoff", 1.0),
            )
            or 1.0
        )
        llm_max_backoff = float(
            getattr(
                resolved_config,
                "entity_intelligence_llm_max_backoff",
                getattr(resolved_config, "llm_max_backoff", 60.0),
            )
            or 60.0
        )
        prompt_version = str(getattr(resolved_config, "entity_intelligence_prompt_version", _PROMPT_VERSION))

        source_entity_count = int(
            await conn.fetchval(f"SELECT count(*) FROM {fq_table('entities')} WHERE bank_id = $1", bank_id) or 0
        )
        if source_entity_count < min_entities:
            logger.debug(
                "[ENTITY_INTELLIGENCE] skipped bank=%s: %s entities < min %s",
                bank_id,
                source_entity_count,
                min_entities,
            )
            return False

        rows = await conn.fetch(
            f"""
            SELECT e.id::text AS id,
                   e.canonical_name,
                   e.metadata,
                   e.mention_count,
                   e.first_seen,
                   e.last_seen,
                   et.current_state,
                   et.anomaly_score,
                   et.forecast_distribution,
                   et.viterbi_path,
                   et.computed_at AS trajectory_computed_at
            FROM {fq_table("entities")} e
            LEFT JOIN {fq_table("entity_trajectories")} et
              ON et.bank_id = e.bank_id AND et.entity_id = e.id
            WHERE e.bank_id = $1
            ORDER BY e.mention_count DESC, e.last_seen DESC NULLS LAST, e.canonical_name ASC
            LIMIT $2
            """,
            bank_id,
            max_entities,
        )
        relationship_rows = await conn.fetch(
            f"""
            SELECT ec.entity_id_1::text AS entity_id_1,
                   ec.entity_id_2::text AS entity_id_2,
                   ec.cooccurrence_count,
                   ec.last_cooccurred
            FROM {fq_table("entity_cooccurrences")} ec
            JOIN {fq_table("entities")} e1 ON e1.id = ec.entity_id_1 AND e1.bank_id = $1
            JOIN {fq_table("entities")} e2 ON e2.id = ec.entity_id_2 AND e2.bank_id = $1
            ORDER BY ec.cooccurrence_count DESC, ec.last_cooccurred DESC NULLS LAST
            LIMIT 160
            """,
            bank_id,
        )
        context = build_entity_intelligence_context(
            list(rows),
            source_entity_count=source_entity_count,
            max_context_tokens=max_context_tokens,
            min_entities=min_entities,
            relationship_rows=list(relationship_rows),
        )
        snapshot = _snapshot_hash(context)
        previous = await fetch_previous_entity_intelligence(conn, bank_id=bank_id)

        delta_metadata: dict[str, Any] = {
            "mode": "full",
            "delta_attempted": False,
            "delta_succeeded": False,
            "max_context_tokens": max_context_tokens,
            "max_completion_tokens": max_completion_tokens,
        }
        final_doc: StructuredDocument | None = None

        if previous and isinstance(previous.get("structured_content"), dict) and previous.get("content"):
            delta_metadata["mode"] = "delta"
            delta_metadata["delta_attempted"] = True
            delta_metadata["previous_content"] = previous.get("content") or ""
            try:
                current_doc = StructuredDocument.model_validate(previous["structured_content"])
                user_prompt = (
                    "Current document JSON:\n"
                    f"{current_doc.model_dump_json()}\n\n"
                    "New compact entity inventory JSON:\n"
                    f"{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}\n\n"
                    "Update the document to reflect the bank as a digital person: people circles, tools, "
                    "companies/platforms, projects, concept clusters, relationship graph, risks, "
                    "opportunities, and forward possibilities. Return only the DeltaOperationList JSON."
                )
                raw_delta = await llm_config.call(
                    messages=[
                        {"role": "system", "content": _DELTA_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    scope="entity_intelligence_delta",
                    temperature=0.2,
                    max_completion_tokens=max_completion_tokens,
                    max_retries=llm_max_retries,
                    initial_backoff=llm_initial_backoff,
                    max_backoff=llm_max_backoff,
                )
                op_list = _parse_delta_text(raw_delta)
                outcome = apply_operations(current_doc, op_list.operations)
                final_doc = outcome.document
                delta_metadata["delta_succeeded"] = True
                delta_metadata["applied"] = outcome.applied
                if outcome.skipped:
                    delta_metadata["skipped"] = outcome.skipped
            except Exception as err:  # noqa: BLE001 - full regeneration is safer than failing the task
                logger.warning(
                    "[ENTITY_INTELLIGENCE] delta failed for bank=%s; falling back to full: %s: %s",
                    bank_id,
                    type(err).__name__,
                    err,
                )
                delta_metadata["delta_error"] = f"{type(err).__name__}: {err}"

        if final_doc is None:
            user_prompt = (
                "Build bank-level digital-person intelligence from this compact entity map JSON:\n"
                f"{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}\n\n"
                "Prefer these section ids: digital-person, people-circles, operating-system, "
                "relationship-graph, mind-map, risks-and-blind-spots, opportunities, "
                "forward-possibilities, what-to-watch-next. Make it useful for understanding "
                "what the bank already knows and what can be extracted from it next. Use plain "
                "language, avoid jargon, and include entity names, their likely type, relationship "
                "evidence, metadata confidence, and why each connection matters."
            )
            raw_doc = await llm_config.call(
                messages=[
                    {"role": "system", "content": _FULL_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                scope="entity_intelligence_full",
                temperature=0.25,
                max_completion_tokens=max_completion_tokens,
                max_retries=llm_max_retries,
                initial_backoff=llm_initial_backoff,
                max_backoff=llm_max_backoff,
            )
            try:
                final_doc = _parse_structured_document(raw_doc, context=context)
            except ValidationError as err:
                logger.warning("[ENTITY_INTELLIGENCE] full structured parse failed for bank=%s: %s", bank_id, err)
                final_doc = _default_document(context)

        content = render_document(final_doc)
        if not content.strip():
            final_doc = _default_document(context)
            content = render_document(final_doc)

        model_name = f"{getattr(llm_config, 'provider', '')}/{getattr(llm_config, 'model', '')}"
        await conn.execute(
            f"""
            INSERT INTO {fq_table("entity_intelligence")}
              (bank_id, computed_at, entity_count, source_entity_count, entity_snapshot_hash,
               content, structured_content, entity_context, delta_metadata, llm_model, prompt_version)
            VALUES ($1, now(), $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9, $10)
            ON CONFLICT (bank_id) DO UPDATE SET
              computed_at = now(),
              entity_count = EXCLUDED.entity_count,
              source_entity_count = EXCLUDED.source_entity_count,
              entity_snapshot_hash = EXCLUDED.entity_snapshot_hash,
              content = EXCLUDED.content,
              structured_content = EXCLUDED.structured_content,
              entity_context = EXCLUDED.entity_context,
              delta_metadata = EXCLUDED.delta_metadata,
              llm_model = EXCLUDED.llm_model,
              prompt_version = EXCLUDED.prompt_version
            """,
            bank_id,
            int(context.get("included_entity_count") or 0),
            source_entity_count,
            snapshot,
            content,
            json.dumps(final_doc.model_dump(mode="json")),
            json.dumps(context),
            json.dumps(delta_metadata),
            model_name[:500],
            prompt_version,
        )
        return True
