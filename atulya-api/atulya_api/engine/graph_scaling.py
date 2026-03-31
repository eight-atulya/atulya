from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..config import get_config
from .graph_intelligence import (
    GraphBuildOptions,
    GraphChangeEvent,
    GraphIntelligenceResponse,
    GraphRelationEdge,
    GraphStateNode,
    _slugify,
    build_graph_intelligence,
)

GraphSurface = Literal["state", "evidence"]
GraphRenderMode = Literal["detail", "compact", "overview"]
GraphStatusTone = Literal["stable", "changed", "contradictory", "stale", "neutral"]
GraphCanvasNodeType = Literal["state", "event", "evidence"]
GraphSummaryItemKind = Literal["cluster", "node"]

DETAIL_NODE_LIMIT = 75
COMPACT_NODE_LIMIT = 250
DETAIL_RENDER_NODE_CAP = 80
DETAIL_RENDER_EDGE_CAP = 180
NEIGHBORHOOD_DEFAULT_NODE_LIMIT = 60
NEIGHBORHOOD_DEFAULT_EDGE_LIMIT = 140
STATE_SUMMARY_BUILD_LIMIT = 320
EVIDENCE_SUMMARY_BUILD_LIMIT = 1200


class GraphSummaryItem(BaseModel):
    id: str
    kind: GraphSummaryItemKind
    title: str
    subtitle: str | None = None
    preview_labels: list[str] = Field(default_factory=list)
    member_count: int = 0
    status_tone: GraphStatusTone = "neutral"
    display_priority: float
    render_mode_hint: GraphRenderMode
    cluster_membership: list[str] = Field(default_factory=list)
    node_ref: str | None = None


class GraphSummaryEdge(BaseModel):
    id: str
    source_id: str
    target_id: str
    weight: float
    label: str | None = None


class GraphSummaryResponse(BaseModel):
    surface: GraphSurface
    mode_hint: GraphRenderMode
    total_nodes: int
    total_edges: int
    clusters: list[GraphSummaryItem] = Field(default_factory=list)
    top_nodes: list[GraphSummaryItem] = Field(default_factory=list)
    bundled_edges: list[GraphSummaryEdge] = Field(default_factory=list)
    initial_focus_ids: list[str] = Field(default_factory=list)
    generated_at: str
    cached: bool = False


class GraphNeighborhoodNode(BaseModel):
    id: str
    node_type: GraphCanvasNodeType
    title: str
    subtitle: str | None = None
    preview: str | None = None
    status_label: str | None = None
    status_tone: GraphStatusTone = "neutral"
    confidence: float | None = None
    evidence_count: int | None = None
    kind_label: str | None = None
    meta: str | None = None
    timestamp_label: str | None = None
    reason: str | None = None
    accent_color: str | None = None
    display_priority: float = 0.0
    node_density_hint: float = 0.0
    cluster_membership: str | None = None
    render_mode_hint: GraphRenderMode = "detail"


class GraphNeighborhoodEdge(BaseModel):
    id: str
    source: str
    target: str
    kind: Literal["relation", "event", "evidence"] = "relation"
    label: str | None = None
    stroke: str | None = None
    dashed: bool = False
    width: float = 1.6
    animated: bool = True
    priority: float = 0.0


class GraphNeighborhoodResponse(BaseModel):
    surface: GraphSurface
    mode_hint: GraphRenderMode
    focus_ids: list[str] = Field(default_factory=list)
    nodes: list[GraphNeighborhoodNode] = Field(default_factory=list)
    edges: list[GraphNeighborhoodEdge] = Field(default_factory=list)
    total_nodes: int
    total_edges: int
    has_more: bool = False
    cursor: str | None = None
    generated_at: str
    cached: bool = False


def select_graph_render_mode(total_nodes: int) -> GraphRenderMode:
    if total_nodes > COMPACT_NODE_LIMIT:
        return "overview"
    if total_nodes > DETAIL_NODE_LIMIT:
        return "compact"
    return "detail"


def _shorten(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _status_to_tone(value: str | None) -> GraphStatusTone:
    if value in {"stable", "changed", "contradictory", "stale"}:
        return value
    return "neutral"


def _status_display_label(value: str | None) -> str:
    if value == "contradictory":
        return "Conflict"
    if value == "changed":
        return "Changed"
    if value == "stale":
        return "Stale"
    if value == "stable":
        return "Stable"
    return "Unknown"


def _event_display_label(change_type: str) -> str:
    if change_type == "contradiction":
        return "Conflict"
    if change_type == "stale":
        return "Stale"
    return "Change"


def _kind_display_label(kind: str) -> str:
    if kind == "entity":
        return "Entities"
    if kind == "topic":
        return "Topics"
    return "Nodes"


def _weight_to_width(weight: float, minimum: float = 1.25, maximum: float = 3.25) -> float:
    return max(minimum, min(maximum, round(weight, 3)))


def _status_priority(status: GraphStatusTone) -> int:
    order = {
        "contradictory": 4,
        "changed": 3,
        "stale": 2,
        "stable": 1,
        "neutral": 0,
    }
    return order[status]


def _cluster_edge_id(source_id: str, target_id: str, label: str | None) -> str:
    source, target = sorted([source_id, target_id])
    suffix = _slugify(label or "edge")
    return f"summary-edge:{suffix}:{_slugify(source)}:{_slugify(target)}"


def build_state_graph_summary(graph: GraphIntelligenceResponse) -> GraphSummaryResponse:
    mode_hint = select_graph_render_mode(graph.total_nodes)
    top_nodes = sorted(
        graph.nodes,
        key=lambda node: (-node.change_score, -_status_priority(_status_to_tone(node.status)), node.title.lower()),
    )[:8]
    top_ids = {node.id for node in top_nodes}
    grouped: dict[tuple[str, str], list[GraphStateNode]] = defaultdict(list)

    for node in graph.nodes:
        if node.id in top_ids:
            continue
        grouped[(node.status, node.kind)].append(node)

    clusters: list[GraphSummaryItem] = []
    membership: dict[str, str] = {}
    for (status, kind), members in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0][0], item[0][1])):
        cluster_id = f"cluster:state:{status}:{kind}"
        preview_labels = [
            member.title for member in sorted(members, key=lambda node: (-node.change_score, node.title.lower()))[:3]
        ]
        for member in members:
            membership[member.id] = cluster_id
        clusters.append(
            GraphSummaryItem(
                id=cluster_id,
                kind="cluster",
                title=f"{_status_display_label(status)} {_kind_display_label(kind)}",
                subtitle=f"{len(members)} nodes",
                preview_labels=preview_labels,
                member_count=len(members),
                status_tone=_status_to_tone(status),
                display_priority=max((member.change_score for member in members), default=0.0),
                render_mode_hint=mode_hint,
                cluster_membership=[member.id for member in members[:24]],
            )
        )

    top_summary_nodes = [
        GraphSummaryItem(
            id=node.id,
            kind="node",
            title=node.title,
            subtitle=node.subtitle,
            preview_labels=[node.current_state],
            member_count=1,
            status_tone=_status_to_tone(node.status),
            display_priority=node.change_score,
            render_mode_hint=select_graph_render_mode(1),
            cluster_membership=[node.id],
            node_ref=node.id,
        )
        for node in top_nodes
    ]

    aggregated_edges: dict[tuple[str, str, str | None], float] = defaultdict(float)
    for edge in graph.edges:
        source = edge.source_id if edge.source_id in top_ids else membership.get(edge.source_id)
        target = edge.target_id if edge.target_id in top_ids else membership.get(edge.target_id)
        if not source or not target or source == target:
            continue
        aggregated_edges[(source, target, edge.relation_type)] += max(0.1, edge.strength)

    bundled_edges = [
        GraphSummaryEdge(
            id=_cluster_edge_id(source_id, target_id, label),
            source_id=source_id,
            target_id=target_id,
            weight=round(weight, 3),
            label=label,
        )
        for (source_id, target_id, label), weight in sorted(
            aggregated_edges.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
        )
    ]

    return GraphSummaryResponse(
        surface="state",
        mode_hint=mode_hint,
        total_nodes=graph.total_nodes,
        total_edges=len(graph.edges) + len(graph.change_events),
        clusters=clusters,
        top_nodes=top_summary_nodes,
        bundled_edges=bundled_edges,
        initial_focus_ids=[node.id for node in top_nodes[:3]],
        generated_at=graph.generated_at,
        cached=graph.cached,
    )


def _entity_tokens_from_row(row: dict[str, Any]) -> list[str]:
    raw = row.get("entities")
    if not isinstance(raw, str):
        return []
    return [value.strip() for value in raw.split(",") if value.strip() and value.strip().lower() != "none"]


def build_evidence_graph_summary(graph_data: dict[str, Any]) -> GraphSummaryResponse:
    table_rows = {row["id"]: row for row in graph_data.get("table_rows", [])}
    connection_counts: dict[str, int] = defaultdict(int)
    for edge in graph_data.get("edges", []):
        edge_data = edge.get("data", {})
        source = edge_data.get("source")
        target = edge_data.get("target")
        if source:
            connection_counts[str(source)] += 1
        if target:
            connection_counts[str(target)] += 1

    raw_nodes = graph_data.get("nodes", [])
    scored_nodes = sorted(
        raw_nodes,
        key=lambda node: (
            -(connection_counts.get(node["data"]["id"], 0) * 6 + int(node["data"].get("accessCount", 0)) * 3),
            str(node["data"].get("label", "")).lower(),
        ),
    )
    top_nodes_raw = scored_nodes[:8]
    top_ids = {node["data"]["id"] for node in top_nodes_raw}

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    membership: dict[str, str] = {}
    for node in scored_nodes:
        node_id = str(node["data"]["id"])
        if node_id in top_ids:
            continue
        row = table_rows.get(node_id, {})
        entities = _entity_tokens_from_row(row)
        cluster_key = entities[0] if entities else str(row.get("fact_type") or "Unlinked evidence")
        grouped[cluster_key].append(node)

    clusters: list[GraphSummaryItem] = []
    for cluster_key, members in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0].lower()))[:12]:
        cluster_id = f"cluster:evidence:{_slugify(cluster_key)}"
        for member in members:
            membership[str(member["data"]["id"])] = cluster_id
        preview_labels = [str(member["data"].get("label") or member["data"]["id"]) for member in members[:3]]
        priority = max(
            (connection_counts.get(str(member["data"]["id"]), 0) * 6 + int(member["data"].get("accessCount", 0)) * 3)
            for member in members
        )
        clusters.append(
            GraphSummaryItem(
                id=cluster_id,
                kind="cluster",
                title=cluster_key,
                subtitle=f"{len(members)} evidence memories",
                preview_labels=preview_labels,
                member_count=len(members),
                status_tone="neutral",
                display_priority=float(priority),
                render_mode_hint=select_graph_render_mode(graph_data.get("total_units", len(raw_nodes))),
                cluster_membership=[str(member["data"]["id"]) for member in members[:24]],
            )
        )

    top_nodes = []
    for node in top_nodes_raw:
        node_id = str(node["data"]["id"])
        row = table_rows.get(node_id, {})
        top_nodes.append(
            GraphSummaryItem(
                id=node_id,
                kind="node",
                title=str(node["data"].get("label") or node_id[:8]),
                subtitle=str(row.get("fact_type") or "Evidence memory"),
                preview_labels=[_shorten(str(row.get("text") or node["data"].get("text") or ""), 120)],
                member_count=1,
                status_tone="neutral",
                display_priority=float(
                    connection_counts.get(node_id, 0) * 6 + int(node["data"].get("accessCount", 0)) * 3
                ),
                render_mode_hint="detail",
                cluster_membership=[node_id],
                node_ref=node_id,
            )
        )

    aggregated_edges: dict[tuple[str, str, str | None], float] = defaultdict(float)
    for edge in graph_data.get("edges", []):
        edge_data = edge.get("data", {})
        source_raw = str(edge_data.get("source"))
        target_raw = str(edge_data.get("target"))
        source = source_raw if source_raw in top_ids else membership.get(source_raw)
        target = target_raw if target_raw in top_ids else membership.get(target_raw)
        if not source or not target or source == target:
            continue
        aggregated_edges[(source, target, edge_data.get("linkType"))] += float(edge_data.get("weight") or 1.0)

    bundled_edges = [
        GraphSummaryEdge(
            id=_cluster_edge_id(source_id, target_id, label),
            source_id=source_id,
            target_id=target_id,
            weight=round(weight, 3),
            label=label,
        )
        for (source_id, target_id, label), weight in sorted(
            aggregated_edges.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
        )
    ]

    total_nodes = int(graph_data.get("total_units", len(raw_nodes)))
    return GraphSummaryResponse(
        surface="evidence",
        mode_hint=select_graph_render_mode(total_nodes),
        total_nodes=total_nodes,
        total_edges=len(graph_data.get("edges", [])),
        clusters=clusters,
        top_nodes=top_nodes,
        bundled_edges=bundled_edges,
        initial_focus_ids=[item.id for item in top_nodes[:3]],
        generated_at=datetime.now(UTC).isoformat(),
        cached=False,
    )


def build_state_graph_neighborhood(
    graph: GraphIntelligenceResponse,
    *,
    focus_ids: list[str] | None = None,
    depth: int = 1,
    limit_nodes: int = NEIGHBORHOOD_DEFAULT_NODE_LIMIT,
    limit_edges: int = NEIGHBORHOOD_DEFAULT_EDGE_LIMIT,
) -> GraphNeighborhoodResponse:
    edge_records = [(edge.id, edge.source_id, edge.target_id, edge) for edge in graph.edges] + [
        (f"event-edge:{event.id}", event.node_id, f"event:{event.id}", event) for event in graph.change_events
    ]
    adjacency: dict[str, list[str]] = defaultdict(list)
    edge_lookup: dict[tuple[str, str], list[str]] = defaultdict(list)
    for edge_id, source, target, _ in edge_records:
        adjacency[source].append(target)
        adjacency[target].append(source)
        edge_lookup[(source, target)].append(edge_id)
        edge_lookup[(target, source)].append(edge_id)

    state_lookup = {node.id: node for node in graph.nodes}
    event_lookup = {f"event:{event.id}": event for event in graph.change_events}
    initial_focus = [focus_id for focus_id in (focus_ids or []) if focus_id in state_lookup or focus_id in event_lookup]
    if not initial_focus:
        initial_focus = [
            node.id for node in sorted(graph.nodes, key=lambda node: (-node.change_score, node.title.lower()))[:3]
        ]

    queue: deque[tuple[str, int]] = deque((focus_id, 0) for focus_id in initial_focus)
    seen: set[str] = set(initial_focus)
    ordered_ids: list[str] = []

    while queue and len(ordered_ids) < limit_nodes:
        node_id, level = queue.popleft()
        ordered_ids.append(node_id)
        if level >= depth:
            continue
        for neighbor in sorted(adjacency.get(node_id, [])):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append((neighbor, level + 1))

    selected_set = set(ordered_ids)
    selected_edges: list[GraphNeighborhoodEdge] = []
    for edge in graph.edges:
        if edge.source_id in selected_set and edge.target_id in selected_set:
            selected_edges.append(
                GraphNeighborhoodEdge(
                    id=edge.id,
                    source=edge.source_id,
                    target=edge.target_id,
                    kind="relation",
                    label=edge.relation_type,
                    stroke="#64748b",
                    dashed="support" in edge.relation_type or "weak" in edge.relation_type,
                    width=_weight_to_width(1.1 + edge.strength * 1.2),
                    animated=True,
                    priority=edge.strength,
                )
            )
    for event in graph.change_events:
        event_node_id = f"event:{event.id}"
        if event.node_id in selected_set and event_node_id in selected_set:
            selected_edges.append(
                GraphNeighborhoodEdge(
                    id=f"event-edge:{event.id}",
                    source=event.node_id,
                    target=event_node_id,
                    kind="event",
                    stroke="#f97316",
                    width=1.5,
                    animated=True,
                    priority=event.confidence,
                )
            )
    selected_edges = sorted(selected_edges, key=lambda edge: (-edge.priority, edge.id))[:limit_edges]

    nodes: list[GraphNeighborhoodNode] = []
    for node_id in ordered_ids:
        if node_id in state_lookup:
            node = state_lookup[node_id]
            nodes.append(
                GraphNeighborhoodNode(
                    id=node.id,
                    node_type="state",
                    title=node.title,
                    subtitle=node.subtitle,
                    preview=node.current_state,
                    status_label=_status_display_label(node.status),
                    status_tone=_status_to_tone(node.status),
                    confidence=node.confidence,
                    evidence_count=node.evidence_count,
                    kind_label="Entity State" if node.kind == "entity" else "Topic State",
                    meta=node.kind,
                    timestamp_label=node.primary_timestamp,
                    reason=node.status_reason,
                    display_priority=node.change_score,
                    node_density_hint=float(node.evidence_count),
                    render_mode_hint="compact" if graph.total_nodes > DETAIL_NODE_LIMIT else "detail",
                )
            )
        elif node_id in event_lookup:
            event = event_lookup[node_id]
            nodes.append(
                GraphNeighborhoodNode(
                    id=node_id,
                    node_type="event",
                    title=_event_display_label(event.change_type),
                    preview=event.summary,
                    status_label=_event_display_label(event.change_type),
                    status_tone=_status_to_tone(
                        "contradictory"
                        if event.change_type == "contradiction"
                        else "changed"
                        if event.change_type == "change"
                        else "stale"
                    ),
                    confidence=event.confidence,
                    timestamp_label=event.time_window,
                    display_priority=event.confidence,
                    render_mode_hint="compact" if graph.total_nodes > DETAIL_NODE_LIMIT else "detail",
                )
            )

    total_graph_nodes = len(graph.nodes) + len(graph.change_events)
    has_more = total_graph_nodes > len(nodes) or len(selected_edges) >= limit_edges
    return GraphNeighborhoodResponse(
        surface="state",
        mode_hint="compact" if graph.total_nodes > DETAIL_NODE_LIMIT else "detail",
        focus_ids=initial_focus,
        nodes=nodes,
        edges=selected_edges,
        total_nodes=total_graph_nodes,
        total_edges=len(graph.edges) + len(graph.change_events),
        has_more=has_more,
        cursor=f"depth:{depth + 1}" if has_more else None,
        generated_at=graph.generated_at,
        cached=graph.cached,
    )


def build_evidence_graph_neighborhood(
    graph_data: dict[str, Any],
    *,
    focus_ids: list[str] | None = None,
    depth: int = 1,
    limit_nodes: int = NEIGHBORHOOD_DEFAULT_NODE_LIMIT,
    limit_edges: int = NEIGHBORHOOD_DEFAULT_EDGE_LIMIT,
) -> GraphNeighborhoodResponse:
    raw_nodes = graph_data.get("nodes", [])
    raw_edges = graph_data.get("edges", [])
    table_rows = {row["id"]: row for row in graph_data.get("table_rows", [])}
    node_lookup = {str(node["data"]["id"]): node for node in raw_nodes}
    adjacency: dict[str, list[str]] = defaultdict(list)
    connection_counts: dict[str, int] = defaultdict(int)
    for edge in raw_edges:
        edge_data = edge.get("data", {})
        source = str(edge_data.get("source"))
        target = str(edge_data.get("target"))
        adjacency[source].append(target)
        adjacency[target].append(source)
        connection_counts[source] += 1
        connection_counts[target] += 1

    initial_focus = [focus_id for focus_id in (focus_ids or []) if focus_id in node_lookup]
    if not initial_focus:
        initial_focus = [
            node_id
            for node_id, _node in sorted(
                node_lookup.items(),
                key=lambda item: (
                    -(connection_counts.get(item[0], 0) * 6 + int(item[1]["data"].get("accessCount", 0)) * 3),
                    str(item[1]["data"].get("label", "")).lower(),
                ),
            )[:3]
        ]

    queue: deque[tuple[str, int]] = deque((focus_id, 0) for focus_id in initial_focus)
    seen: set[str] = set(initial_focus)
    ordered_ids: list[str] = []
    while queue and len(ordered_ids) < limit_nodes:
        node_id, level = queue.popleft()
        ordered_ids.append(node_id)
        if level >= depth:
            continue
        for neighbor in sorted(adjacency.get(node_id, [])):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append((neighbor, level + 1))

    selected_set = set(ordered_ids)
    nodes: list[GraphNeighborhoodNode] = []
    for node_id in ordered_ids:
        node = node_lookup[node_id]
        row = table_rows.get(node_id, {})
        preview = str(row.get("text") or node["data"].get("text") or row.get("context") or "")
        entities = _entity_tokens_from_row(row)
        meta = " · ".join(entities[:2]) if entities else f"{connection_counts.get(node_id, 0)} links"
        nodes.append(
            GraphNeighborhoodNode(
                id=node_id,
                node_type="evidence",
                title=str(node["data"].get("label") or node_id[:8]),
                subtitle=str(row.get("fact_type") or "Evidence memory"),
                preview=_shorten(preview, 180),
                status_tone="neutral",
                evidence_count=1,
                meta=meta,
                timestamp_label=str(
                    row.get("mentioned_at") or row.get("occurred_start") or row.get("created_at") or ""
                ),
                reason=_shorten(str(row.get("context") or ""), 110) or None,
                accent_color=str(node["data"].get("color") or "#dc2626"),
                display_priority=float(
                    connection_counts.get(node_id, 0) * 6 + int(node["data"].get("accessCount", 0)) * 3
                ),
                node_density_hint=float(connection_counts.get(node_id, 0)),
                render_mode_hint="compact"
                if graph_data.get("total_units", len(raw_nodes)) > DETAIL_NODE_LIMIT
                else "detail",
            )
        )

    edges: list[GraphNeighborhoodEdge] = []
    for index, edge in enumerate(raw_edges):
        edge_data = edge.get("data", {})
        source = str(edge_data.get("source"))
        target = str(edge_data.get("target"))
        if source not in selected_set or target not in selected_set:
            continue
        link_type = str(edge_data.get("linkType") or "semantic")
        edges.append(
            GraphNeighborhoodEdge(
                id=f"{source}:{target}:{index}",
                source=source,
                target=target,
                kind="evidence",
                label=link_type,
                stroke=str(edge_data.get("color") or "#64748b"),
                dashed=link_type == "temporal",
                width=_weight_to_width(float(edge_data.get("weight") or 1.6)),
                animated=True,
                priority=float(edge_data.get("weight") or 1.0),
            )
        )
    edges = sorted(edges, key=lambda edge: (-edge.priority, edge.id))[:limit_edges]

    total_nodes = int(graph_data.get("total_units", len(raw_nodes)))
    return GraphNeighborhoodResponse(
        surface="evidence",
        mode_hint="compact" if total_nodes > DETAIL_NODE_LIMIT else "detail",
        focus_ids=initial_focus,
        nodes=nodes,
        edges=edges,
        total_nodes=total_nodes,
        total_edges=len(raw_edges),
        has_more=total_nodes > len(nodes) or len(edges) >= limit_edges,
        cursor=f"depth:{depth + 1}" if total_nodes > len(nodes) or len(edges) >= limit_edges else None,
        generated_at=datetime.now(UTC).isoformat(),
        cached=False,
    )


def build_state_graph_from_units(
    units: list[Any],
    *,
    limit: int,
    confidence_min: float,
    node_kind: Literal["all", "entity", "topic"],
    window_days: int | None,
    now: datetime,
) -> GraphIntelligenceResponse:
    config = get_config()
    return build_graph_intelligence(
        units,
        GraphBuildOptions(
            limit=limit,
            confidence_min=confidence_min,
            node_kind=node_kind,
            window_days=window_days,
            contradiction_cosine_min=config.graph_contradiction_cosine_min,
            contradiction_cosine_max=config.graph_contradiction_cosine_max,
            contradiction_confidence_penalty=config.graph_contradiction_confidence_penalty,
            now=now,
        ),
    )
