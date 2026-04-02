from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class GraphEvalRetainDoc:
    key: str
    content: str
    days_ago: int
    context: str = "graph intelligence eval"


@dataclass(frozen=True)
class GraphEvalScenario:
    name: str
    focus_titles: tuple[str, ...]
    docs: tuple[GraphEvalRetainDoc, ...]


GRAPH_INTELLIGENCE_REAL_CORPUS: tuple[GraphEvalScenario, ...] = (
    GraphEvalScenario(
        name="contradiction_and_ownership",
        focus_titles=("Anurag", "Atulya"),
        docs=(
            GraphEvalRetainDoc(
                key="anurag_architect",
                content="Anurag is the lead architect for Atulya.",
                days_ago=12,
            ),
            GraphEvalRetainDoc(
                key="anurag_never_coded",
                content="Anurag never wrote code for Atulya.",
                days_ago=2,
            ),
        ),
    ),
    GraphEvalScenario(
        name="state_change",
        focus_titles=("Nadia",),
        docs=(
            GraphEvalRetainDoc(
                key="nadia_openai",
                content="Nadia worked at OpenAI in 2024.",
                days_ago=28,
            ),
            GraphEvalRetainDoc(
                key="nadia_anthropic",
                content="Nadia now works at Anthropic in 2026.",
                days_ago=1,
            ),
        ),
    ),
    GraphEvalScenario(
        name="semantic_duplicate",
        focus_titles=("Priya",),
        docs=(
            GraphEvalRetainDoc(
                key="priya_roadmap_one",
                content="Priya owns the Brain OS roadmap.",
                days_ago=9,
            ),
            GraphEvalRetainDoc(
                key="priya_roadmap_two",
                content="Priya owns the Brain OS roadmap.",
                days_ago=3,
            ),
        ),
    ),
)


async def load_graph_intelligence_real_corpus(memory, request_context, *, bank_id: str) -> None:
    now = datetime.now(UTC)
    contents = []
    for scenario in GRAPH_INTELLIGENCE_REAL_CORPUS:
        for doc in scenario.docs:
            contents.append(
                {
                    "content": doc.content,
                    "context": doc.context,
                    "event_date": now - timedelta(days=doc.days_ago),
                    "document_id": f"{scenario.name}_{doc.key}",
                }
            )

    await memory.retain_batch_async(
        bank_id=bank_id,
        contents=contents,
        request_context=request_context,
    )


def summarize_graph_intelligence(graph: dict[str, Any], *, focus_titles: tuple[str, ...]) -> list[dict[str, Any]]:
    events_by_node: dict[str, list[dict[str, Any]]] = {}
    for event in graph.get("change_events", []):
        events_by_node.setdefault(event["node_id"], []).append(event)

    summary: list[dict[str, Any]] = []
    for node in graph.get("nodes", []):
        if node["title"] not in focus_titles:
            continue
        summary.append(
            {
                "title": node["title"],
                "status": node["status"],
                "current_state": node["current_state"],
                "event_types": [event["change_type"] for event in events_by_node.get(node["id"], [])],
            }
        )
    return summary


async def run_graph_intelligence_eval(
    memory,
    request_context,
    *,
    bank_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    await load_graph_intelligence_real_corpus(memory, request_context, bank_id=bank_id)
    graph = await memory.get_graph_intelligence(
        bank_id=bank_id,
        limit=limit,
        confidence_min=0.0,
        node_kind="entity",
        request_context=request_context,
    )
    focus_titles = tuple(title for scenario in GRAPH_INTELLIGENCE_REAL_CORPUS for title in scenario.focus_titles)
    return summarize_graph_intelligence(graph, focus_titles=focus_titles)


def format_graph_intelligence_eval(summary: list[dict[str, Any]]) -> str:
    lines = []
    for row in summary:
        event_types = ",".join(row["event_types"]) if row["event_types"] else "none"
        lines.append(f"{row['title']}: status={row['status']} events={event_types} state={row['current_state']}")
    return "\n".join(lines)
