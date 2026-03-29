"use client";

import { useMemo } from "react";

import { GraphNeighborhoodResponse, GraphSummaryResponse } from "@/lib/api";

import {
  GraphWorkbench,
  WorkbenchGraphEdge,
  WorkbenchGraphNode,
  WorkbenchOverviewEdge,
  WorkbenchOverviewNode,
  WorkbenchRenderMode,
} from "./graph-workbench";

export interface GraphNode {
  id: string;
  label?: string;
  color?: string;
  size?: number;
  group?: string;
  metadata?: Record<string, any>;
}

export interface GraphLink {
  source: string;
  target: string;
  color?: string;
  width?: number;
  type?: string;
  entity?: string;
  weight?: number;
  metadata?: Record<string, any>;
}

export interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

export interface Graph2DProps {
  data: GraphData;
  summary?: GraphSummaryResponse | null;
  neighborhood?: GraphNeighborhoodResponse | null;
  height?: number;
  showLabels?: boolean;
  selectedNodeId?: string | null;
  highlightedNodeIds?: string[];
  onNodeClick?: (node: GraphNode) => void;
  onNodeHover?: (node: GraphNode | null) => void;
  onBackgroundClick?: () => void;
  onSummaryClick?: (itemId: string) => void;
  nodeColorFn?: (node: GraphNode) => string;
  nodeSizeFn?: (node: GraphNode) => number;
  linkColorFn?: (link: GraphLink) => string;
  linkWidthFn?: (link: GraphLink) => number;
  maxNodes?: number;
  storageKey?: string;
  resetLayoutVersion?: number;
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function truncate(value: string | null | undefined, max: number, fallback = "") {
  const normalized = typeof value === "string" && value.trim().length > 0 ? value.trim() : fallback;
  return normalized.length <= max ? normalized : `${normalized.slice(0, max - 1)}…`;
}

function buildNodeTitle(node: GraphNode) {
  return truncate(node.label, 72, node.id.slice(0, 8));
}

function buildNodePreview(node: GraphNode) {
  const memoryText = typeof node.metadata?.text === "string" ? node.metadata.text : "";
  const contextText = typeof node.metadata?.context === "string" ? node.metadata.context : "";
  return truncate(memoryText || contextText, 150, "Open this memory to inspect the raw evidence.");
}

function buildNodeMeta(node: GraphNode, connections: number, accessCount: number) {
  const entities = typeof node.metadata?.entities === "string" ? node.metadata.entities : "";
  const entitySummary = entities
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean)
    .slice(0, 2)
    .join(" · ");

  if (entitySummary) return truncate(entitySummary, 56);
  if (connections > 0 || accessCount > 0) return `${connections} links · ${accessCount} access`;
  return "Evidence memory";
}

function estimateEvidenceHeight(title: string, meta: string, preview: string, showLabels: boolean) {
  const titleLines = Math.max(1, Math.ceil(title.length / 24));
  const metaLines = Math.max(1, Math.ceil(meta.length / 34));
  const previewLines = showLabels ? Math.max(2, Math.ceil(preview.length / 34)) : 0;
  return Math.max(148, Math.min(228, 82 + titleLines * 22 + metaLines * 16 + previewLines * 18));
}

function linkCategory(type?: string) {
  if (!type) return "semantic";
  if (type === "semantic" || type === "temporal" || type === "entity") return type;
  if (["causes", "caused_by", "enables", "prevents"].includes(type)) return "causal";
  return "semantic";
}

export function Graph2D({
  data,
  summary,
  neighborhood,
  height = 700,
  showLabels = true,
  selectedNodeId,
  highlightedNodeIds = [],
  onNodeClick,
  onNodeHover,
  onBackgroundClick,
  onSummaryClick,
  nodeColorFn,
  nodeSizeFn,
  linkColorFn,
  linkWidthFn,
  maxNodes,
  storageKey,
  resetLayoutVersion = 0,
}: Graph2DProps) {
  const limitedData = useMemo(() => {
    let nodes = [...data.nodes];
    if (maxNodes && nodes.length > maxNodes) {
      nodes = nodes.slice(0, maxNodes);
    }

    const visibleIds = new Set(nodes.map((node) => node.id));
    const links = data.links.filter(
      (link) => visibleIds.has(link.source) && visibleIds.has(link.target)
    );

    return { nodes, links };
  }, [data, maxNodes]);

  const nodeLookup = useMemo(
    () => new Map(limitedData.nodes.map((node) => [node.id, node])),
    [limitedData.nodes]
  );

  const connectionStats = useMemo(() => {
    const counts = new Map<string, { connections: number; totalWeight: number }>();
    limitedData.links.forEach((link) => {
      const weight = Number(link.weight ?? 0);
      const source = counts.get(link.source) ?? { connections: 0, totalWeight: 0 };
      const target = counts.get(link.target) ?? { connections: 0, totalWeight: 0 };
      source.connections += 1;
      source.totalWeight += weight;
      target.connections += 1;
      target.totalWeight += weight;
      counts.set(link.source, source);
      counts.set(link.target, target);
    });
    return counts;
  }, [limitedData.links]);

  const workbenchNodes = useMemo<WorkbenchGraphNode[]>(() => {
    if (neighborhood?.nodes?.length) {
      return neighborhood.nodes.map((node) => ({
        id: node.id,
        kind: "evidence",
        title: node.title,
        subtitle: node.subtitle,
        preview: node.preview,
        statusLabel: node.status_label,
        statusTone: node.status_tone,
        confidence: node.confidence,
        evidenceCount: node.evidence_count,
        kindLabel: node.kind_label,
        meta: node.meta,
        timestampLabel: node.timestamp_label,
        reason: node.reason,
        accentColor: node.accent_color ?? undefined,
        width: neighborhood.mode_hint === "compact" ? 220 : 258,
        height: neighborhood.mode_hint === "compact" ? 150 : 190,
        priority: node.display_priority,
      }));
    }
    return limitedData.nodes.map((node) => {
      const stats = connectionStats.get(node.id) ?? { connections: 0, totalWeight: 0 };
      const accessCount = Math.max(0, Number(node.metadata?.access_count ?? 0));
      const title = buildNodeTitle(node);
      const meta = buildNodeMeta(node, stats.connections, accessCount);
      const preview = buildNodePreview(node);
      const color = nodeColorFn?.(node) ?? node.color ?? "#dc2626";
      const sizeSignal = clamp(nodeSizeFn?.(node) ?? node.size ?? 20, 16, 40);

      return {
        id: node.id,
        kind: "evidence",
        title,
        meta,
        preview: showLabels ? preview : null,
        reason:
          typeof node.metadata?.mentioned_at === "string"
            ? new Date(node.metadata.mentioned_at).toLocaleString()
            : typeof node.metadata?.occurred_start === "string"
              ? new Date(node.metadata.occurred_start).toLocaleString()
              : null,
        accentColor: color,
        width: showLabels ? 258 : 214,
        height: estimateEvidenceHeight(title, meta, preview, showLabels),
        priority: Math.round(
          sizeSignal * 4 + stats.connections * 6 + accessCount * 3 + stats.totalWeight
        ),
      };
    });
  }, [connectionStats, limitedData.nodes, neighborhood, nodeColorFn, nodeSizeFn, showLabels]);

  const workbenchEdges = useMemo<WorkbenchGraphEdge[]>(() => {
    if (neighborhood?.edges?.length) {
      return neighborhood.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        kind: "evidence",
        label: edge.label,
        stroke: edge.stroke ?? undefined,
        dashed: edge.dashed,
        width: edge.width,
        animated: edge.animated,
        priority: edge.priority,
      }));
    }
    return limitedData.links.map((link, index) => ({
      id: `${link.source}:${link.target}:${index}`,
      source: link.source,
      target: link.target,
      kind: "evidence",
      label: linkCategory(link.type),
      stroke: linkColorFn?.(link) ?? link.color ?? undefined,
      dashed: link.type === "temporal",
      width: clamp(linkWidthFn?.(link) ?? link.width ?? 1.6, 1.2, 3.25),
      animated: true,
      priority: Math.round(Number(link.weight ?? 1) * 10),
    }));
  }, [limitedData.links, linkColorFn, linkWidthFn, neighborhood]);

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
    if (summary?.mode_hint === "overview" && !selectedNodeId) return "overview";
    if (neighborhood?.mode_hint) return neighborhood.mode_hint;
    if (limitedData.nodes.length > 75) return "compact";
    return "detail";
  }, [limitedData.nodes.length, neighborhood?.mode_hint, selectedNodeId, summary?.mode_hint]);

  return (
    <GraphWorkbench
      surfaceMode="evidence"
      badgeLabel="Evidence Workbench"
      renderMode={renderMode}
      nodes={workbenchNodes}
      edges={workbenchEdges}
      overviewNodes={overviewNodes}
      overviewEdges={overviewEdges}
      selectedIds={
        renderMode === "overview"
          ? selectedNodeId
            ? [selectedNodeId]
            : summary?.initial_focus_ids?.length
              ? [summary.initial_focus_ids[0]]
              : []
          : selectedNodeId
            ? [selectedNodeId]
            : neighborhood?.focus_ids?.length
              ? [neighborhood.focus_ids[0]]
              : []
      }
      highlightedNodeIds={highlightedNodeIds}
      storageKey={storageKey}
      resetLayoutVersion={resetLayoutVersion}
      height={height}
      onBackgroundClick={onBackgroundClick}
      onNodeHover={(nodeId) => onNodeHover?.(nodeId ? (nodeLookup.get(nodeId) ?? null) : null)}
      onNodeSelect={(nodeId) => {
        if (renderMode === "overview") {
          onSummaryClick?.(nodeId);
          return;
        }
        const node = nodeLookup.get(nodeId);
        if (node) onNodeClick?.(node);
      }}
    />
  );
}

export function convertAtulyaGraphData(atulyaData: {
  nodes?: Array<{ data: { id: string; label?: string; color?: string; accessCount?: number } }>;
  edges?: Array<{
    data: {
      source: string;
      target: string;
      color?: string;
      lineStyle?: string;
      linkType?: string;
      entityName?: string;
      weight?: number;
      similarity?: number;
    };
  }>;
  table_rows?: Array<{
    id: string;
    text: string;
    entities?: string;
    context?: string;
    access_count?: number;
  }>;
}): GraphData {
  const nodes: GraphNode[] = (atulyaData.nodes || []).map((node) => {
    const tableRow = atulyaData.table_rows?.find((row) => row.id === node.data.id);
    let label = node.data.label;
    if (!label && tableRow?.text) {
      label = tableRow.text.length > 56 ? `${tableRow.text.slice(0, 56)}…` : tableRow.text;
    }

    return {
      id: node.data.id,
      label: label || node.data.id.slice(0, 8),
      color: node.data.color,
      metadata: {
        ...(tableRow || {}),
        access_count: node.data.accessCount ?? tableRow?.access_count ?? 0,
      },
    };
  });

  const links: GraphLink[] = (atulyaData.edges || []).map((edge) => ({
    source: edge.data.source,
    target: edge.data.target,
    color: edge.data.color,
    type: edge.data.linkType || (edge.data.lineStyle === "dashed" ? "temporal" : "semantic"),
    entity: edge.data.entityName,
    weight: edge.data.weight ?? edge.data.similarity,
  }));

  return { nodes, links };
}
