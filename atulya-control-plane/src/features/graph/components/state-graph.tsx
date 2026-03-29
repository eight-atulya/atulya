"use client";

import { useMemo } from "react";

import {
  GraphChangeEvent,
  GraphIntelligenceResponse,
  GraphNeighborhoodResponse,
  GraphStateNode,
  GraphSummaryResponse,
} from "@/lib/api";

import {
  GraphWorkbench,
  WorkbenchGraphEdge,
  WorkbenchGraphNode,
  WorkbenchOverviewEdge,
  WorkbenchOverviewNode,
  WorkbenchRenderMode,
} from "./graph-workbench";

interface StateGraphProps {
  data: GraphIntelligenceResponse | null;
  summary?: GraphSummaryResponse | null;
  neighborhood?: GraphNeighborhoodResponse | null;
  selectedNodeId?: string | null;
  selectedEventId?: string | null;
  highlightedNodeIds?: string[];
  highlightedEdgeIds?: string[];
  onNodeClick?: (node: GraphStateNode) => void;
  onEventClick?: (event: GraphChangeEvent) => void;
  onSummaryClick?: (itemId: string) => void;
  onBackgroundClick?: () => void;
  height?: number;
  storageKey?: string;
  resetLayoutVersion?: number;
}

const STATUS_ORDER: Record<GraphStateNode["status"], number> = {
  contradictory: 4,
  changed: 3,
  stale: 2,
  stable: 1,
};

const STATUS_LABEL: Record<GraphStateNode["status"], string> = {
  stable: "Stable",
  changed: "Changed",
  contradictory: "Contradiction",
  stale: "Stale",
};

function safeText(value: string | null | undefined, fallback = "") {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : fallback;
}

function estimateStateHeight(node: GraphStateNode) {
  const titleLines = Math.max(1, Math.ceil(safeText(node.title, "Untitled state").length / 24));
  const subtitleLines = Math.max(0, Math.ceil(safeText(node.subtitle).length / 38));
  const previewLines = Math.max(
    3,
    Math.ceil(safeText(node.current_state, "No state summary available.").length / 34)
  );
  const reasonLines = Math.max(0, Math.ceil(safeText(node.status_reason).length / 44));
  return Math.max(
    216,
    Math.min(320, 108 + titleLines * 24 + subtitleLines * 16 + previewLines * 18 + reasonLines * 12)
  );
}

function estimateEventHeight(event: GraphChangeEvent) {
  const summaryLines = Math.max(3, Math.ceil(safeText(event.summary, "Graph signal").length / 34));
  return Math.max(150, Math.min(210, 94 + summaryLines * 18));
}

function formatShortDate(value: string | null | undefined) {
  if (!value) return null;
  try {
    return new Date(value).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  } catch {
    return null;
  }
}

export function StateGraph({
  data,
  summary,
  neighborhood,
  selectedNodeId,
  selectedEventId,
  highlightedNodeIds = [],
  highlightedEdgeIds = [],
  onNodeClick,
  onEventClick,
  onSummaryClick,
  onBackgroundClick,
  height = 700,
  storageKey,
  resetLayoutVersion = 0,
}: StateGraphProps) {
  const nodeLookup = useMemo(
    () => new Map((data?.nodes ?? []).map((node) => [node.id, node])),
    [data?.nodes]
  );
  const eventLookup = useMemo(
    () => new Map((data?.change_events ?? []).map((event) => [`event:${event.id}`, event])),
    [data?.change_events]
  );

  const workbenchNodes = useMemo<WorkbenchGraphNode[]>(() => {
    if (neighborhood?.nodes?.length) {
      return neighborhood.nodes.map((node) => ({
        id: node.id,
        kind: node.node_type,
        title: safeText(node.title, "Untitled state"),
        subtitle: safeText(node.subtitle),
        preview: safeText(node.preview),
        statusLabel: safeText(node.status_label),
        statusTone: node.status_tone,
        confidence: node.confidence,
        evidenceCount: node.evidence_count,
        kindLabel: safeText(node.kind_label),
        meta: safeText(node.meta),
        timestampLabel: safeText(node.timestamp_label),
        reason: safeText(node.reason),
        accentColor: node.accent_color ?? undefined,
        width: node.node_type === "event" ? 300 : neighborhood.mode_hint === "compact" ? 252 : 312,
        height: node.node_type === "event" ? 164 : neighborhood.mode_hint === "compact" ? 176 : 232,
        priority: node.display_priority,
      }));
    }
    if (!data) return [];

    const stateNodes: WorkbenchGraphNode[] = data.nodes.map((node) => ({
      id: node.id,
      kind: "state",
      title: safeText(node.title, "Untitled state"),
      subtitle: safeText(node.subtitle, `${node.kind} state`),
      preview: safeText(node.current_state, "No state summary available yet."),
      statusLabel: STATUS_LABEL[node.status],
      statusTone: node.status,
      confidence: node.confidence,
      evidenceCount: node.evidence_count,
      kindLabel: node.kind === "entity" ? "Entity State" : "Topic State",
      meta: node.kind,
      timestampLabel: formatShortDate(node.primary_timestamp),
      reason: safeText(node.status_reason),
      width: 312,
      height: estimateStateHeight(node),
      priority:
        STATUS_ORDER[node.status] * 100 +
        Math.round(node.change_score * 10) +
        Math.round(node.confidence * 20) +
        node.evidence_count,
    }));

    const eventNodes: WorkbenchGraphNode[] = data.change_events.map((event) => ({
      id: `event:${event.id}`,
      kind: "event",
      title: event.change_type,
      preview: safeText(event.summary, "Atulya surfaced a graph signal."),
      statusLabel: event.change_type,
      statusTone:
        event.change_type === "contradiction"
          ? "contradictory"
          : event.change_type === "stale"
            ? "stale"
            : "changed",
      confidence: event.confidence,
      timestampLabel: safeText(event.time_window, formatShortDate(event.time_window) ?? ""),
      width: 320,
      height: estimateEventHeight(event),
      priority: 220 + Math.round(event.confidence * 100),
    }));

    return [...stateNodes, ...eventNodes];
  }, [data, neighborhood]);

  const workbenchEdges = useMemo<WorkbenchGraphEdge[]>(() => {
    if (neighborhood?.edges?.length) {
      return neighborhood.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        kind: edge.kind,
        label: edge.label,
        stroke: edge.stroke ?? undefined,
        dashed: edge.dashed,
        width: edge.width,
        animated: edge.animated,
        priority: edge.priority,
      }));
    }
    if (!data) return [];

    const relationEdges = data.edges.map((edge) => ({
      id: edge.id,
      source: edge.source_id,
      target: edge.target_id,
      kind: "relation" as const,
      label: edge.relation_type,
      width: Math.max(1.4, Math.min(3, 1.15 + edge.strength * 1.4)),
      dashed: edge.relation_type.includes("support") || edge.relation_type.includes("weak"),
      animated: true,
    }));

    const eventEdges = data.change_events.map((event) => ({
      id: `event-edge:${event.id}`,
      source: event.node_id,
      target: `event:${event.id}`,
      kind: "event" as const,
      label: null,
      width: 1.5,
      animated: true,
      dashed: false,
    }));

    return [...relationEdges, ...eventEdges];
  }, [data, neighborhood]);

  const overviewNodes = useMemo<WorkbenchOverviewNode[]>(
    () =>
      summary
        ? [...summary.top_nodes, ...summary.clusters].map((item) => ({
            id: item.id,
            kind: item.kind,
            title: item.title,
            subtitle: item.subtitle,
            previewLabels: item.preview_labels,
            memberCount: item.member_count,
            statusTone: item.status_tone,
            displayPriority: item.display_priority,
          }))
        : [],
    [summary]
  );

  const overviewEdges = useMemo<WorkbenchOverviewEdge[]>(
    () =>
      summary
        ? summary.bundled_edges.map((edge) => ({
            id: edge.id,
            source_id: edge.source_id,
            target_id: edge.target_id,
            weight: edge.weight,
            label: edge.label,
          }))
        : [],
    [summary]
  );

  const renderMode = useMemo<WorkbenchRenderMode>(() => {
    if (summary?.mode_hint === "overview" && !selectedNodeId && !selectedEventId) return "overview";
    if (neighborhood?.mode_hint) return neighborhood.mode_hint;
    if (!data) return "detail";
    if (data.total_nodes > 75) return "compact";
    return "detail";
  }, [data, neighborhood?.mode_hint, selectedEventId, selectedNodeId, summary?.mode_hint]);

  const selectedIds = useMemo(
    () =>
      (renderMode === "overview"
        ? [
            selectedNodeId ??
              neighborhood?.focus_ids?.[0] ??
              summary?.initial_focus_ids?.[0] ??
              null,
          ]
        : [
            selectedNodeId ?? neighborhood?.focus_ids?.[0] ?? null,
            selectedEventId ? `event:${selectedEventId}` : null,
          ]
      ).filter(Boolean) as string[],
    [
      renderMode,
      selectedEventId,
      selectedNodeId,
      neighborhood?.focus_ids,
      summary?.initial_focus_ids,
    ]
  );

  const combinedHighlightedNodeIds = useMemo(() => {
    if (!selectedEventId) return highlightedNodeIds;
    const selectedEvent = data?.change_events.find((event) => event.id === selectedEventId);
    if (!selectedEvent) return highlightedNodeIds;
    return Array.from(new Set([...highlightedNodeIds, selectedEvent.node_id]));
  }, [data?.change_events, highlightedNodeIds, selectedEventId]);

  return (
    <GraphWorkbench
      surfaceMode="state"
      badgeLabel="Graph Workbench"
      renderMode={renderMode}
      nodes={workbenchNodes}
      edges={workbenchEdges}
      overviewNodes={overviewNodes}
      overviewEdges={overviewEdges}
      selectedIds={selectedIds}
      highlightedNodeIds={combinedHighlightedNodeIds}
      highlightedEdgeIds={highlightedEdgeIds}
      storageKey={storageKey}
      resetLayoutVersion={resetLayoutVersion}
      height={height}
      onBackgroundClick={onBackgroundClick}
      onNodeSelect={(nodeId) => {
        if (renderMode === "overview") {
          onSummaryClick?.(nodeId);
          return;
        }
        if (nodeId.startsWith("event:")) {
          const event = eventLookup.get(nodeId);
          if (event) onEventClick?.(event);
          return;
        }

        const node = nodeLookup.get(nodeId);
        if (node) onNodeClick?.(node);
      }}
    />
  );
}
