"use client";

import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import {
  client,
  GraphChangeEvent,
  GraphIntelligenceResponse,
  GraphInvestigationResponse,
  GraphNeighborhoodNode,
  GraphNeighborhoodResponse,
  GraphSummaryResponse,
  GraphStateNode as StateGraphNode,
  TimelineResponse,
} from "@/lib/api";
import { useBank } from "@/lib/bank-context";
import { useFeatures } from "@/lib/features-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Calendar,
  ZoomIn,
  ZoomOut,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  RefreshCw,
  CheckCircle,
  Clock,
  Network,
  List,
  Search,
  Tag,
  X,
} from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { MemoryDetailPanel } from "./memory-detail-panel";
import { MemoryDetailModal } from "./memory-detail-modal";
import { MentalModelDetailModal } from "./mental-model-detail-modal";
import { Graph2D, convertAtulyaGraphData, GraphNode } from "../features/graph/components/graph-2d";
import { StateGraph } from "../features/graph/components/state-graph";
import { TimelineGraph } from "../features/graph/components/timeline-graph";

type FactType = "world" | "experience" | "observation";
type ViewMode = "graph" | "table" | "timeline";
type GraphSurfaceMode = "state" | "evidence";

interface DataViewProps {
  factType: FactType;
}

function stateNodeFromNeighborhood(node: GraphNeighborhoodNode): StateGraphNode | null {
  if (node.node_type !== "state") return null;

  const kind = node.meta === "topic" ? "topic" : "entity";
  const status = node.status_tone === "neutral" ? "stable" : node.status_tone;

  return {
    id: node.id,
    title: node.title,
    kind,
    subtitle: node.subtitle ?? null,
    current_state: node.preview ?? "",
    status,
    status_reason: node.reason ?? "",
    confidence: node.confidence ?? 0,
    change_score: node.display_priority ?? 0,
    last_changed_at: node.timestamp_label ?? null,
    primary_timestamp: node.timestamp_label ?? null,
    evidence_count: node.evidence_count ?? 0,
    tags: [],
    evidence_ids: [],
  };
}

export function DataView({ factType }: DataViewProps) {
  const { currentBank } = useBank();
  const { features } = useFeatures();
  const [isCompactGraphLayout, setIsCompactGraphLayout] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>("graph");
  const [data, setData] = useState<any>(null);
  const [timelineData, setTimelineData] = useState<TimelineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [tagFilters, setTagFilters] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedGraphNode, setSelectedGraphNode] = useState<any>(null);
  const [selectedStateNode, setSelectedStateNode] = useState<StateGraphNode | null>(null);
  const [selectedChangeEvent, setSelectedChangeEvent] = useState<GraphChangeEvent | null>(null);
  const [graphIntelligence, setGraphIntelligence] = useState<GraphIntelligenceResponse | null>(
    null
  );
  const [stateSummary, setStateSummary] = useState<GraphSummaryResponse | null>(null);
  const [evidenceSummary, setEvidenceSummary] = useState<GraphSummaryResponse | null>(null);
  const [stateNeighborhood, setStateNeighborhood] = useState<GraphNeighborhoodResponse | null>(
    null
  );
  const [evidenceNeighborhood, setEvidenceNeighborhood] =
    useState<GraphNeighborhoodResponse | null>(null);
  const [graphInvestigation, setGraphInvestigation] = useState<GraphInvestigationResponse | null>(
    null
  );
  const [graphSurfaceMode, setGraphSurfaceMode] = useState<GraphSurfaceMode>("state");
  const [graphLayoutResetVersion, setGraphLayoutResetVersion] = useState(0);
  const [analystQuery, setAnalystQuery] = useState("");
  const [investigating, setInvestigating] = useState(false);
  const [confidenceMin, setConfidenceMin] = useState(0.55);
  const [nodeKind, setNodeKind] = useState<"all" | "entity" | "topic">("all");
  const [windowDays, setWindowDays] = useState<string>("90");
  const [modalMemoryId, setModalMemoryId] = useState<string | null>(null);
  const [mentalModelModalId, setMentalModelModalId] = useState<string | null>(null);
  const itemsPerPage = 100;
  const timelineV2Enabled = Boolean(features?.timeline_v2);

  // Fetch limit state - how many memories to load from the API
  const [fetchLimit, setFetchLimit] = useState(1000);

  // Consolidation status for mental models
  const [consolidationStatus, setConsolidationStatus] = useState<{
    pending_consolidation: number;
    last_consolidated_at: string | null;
  } | null>(null);

  // Graph controls state
  const [showLabels, setShowLabels] = useState(true);
  const [maxNodes, setMaxNodes] = useState<number | undefined>(undefined);
  const [showControlPanel, setShowControlPanel] = useState(true);
  const [visibleLinkTypes, setVisibleLinkTypes] = useState<Set<string>>(
    new Set(["semantic", "temporal", "entity", "causal"])
  );

  const toggleLinkType = (type: string) => {
    setVisibleLinkTypes((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  };

  const stateLayoutStorageKey = currentBank
    ? `graph-workbench:${currentBank}:${factType}:state`
    : undefined;
  const evidenceLayoutStorageKey = currentBank
    ? `graph-workbench:${currentBank}:${factType}:evidence`
    : undefined;

  const loadStateNeighborhood = useCallback(
    async (focusIds?: string[], depth = 1) => {
      if (!currentBank) return null;
      const neighborhood = await client.getGraphNeighborhood({
        bank_id: currentBank,
        surface: "state",
        type: factType,
        q: searchQuery || undefined,
        tags: tagFilters.length > 0 ? tagFilters : undefined,
        tags_match: "all_strict",
        confidence_min: confidenceMin,
        node_kind: nodeKind,
        window_days: windowDays === "all" ? undefined : Number(windowDays),
        focus_ids: focusIds,
        depth,
        limit_nodes: 60,
        limit_edges: 140,
      });
      setStateNeighborhood(neighborhood);
      return neighborhood;
    },
    [confidenceMin, currentBank, factType, nodeKind, searchQuery, tagFilters, windowDays]
  );

  const loadEvidenceNeighborhood = useCallback(
    async (focusIds?: string[], depth = 1) => {
      if (!currentBank) return null;
      const neighborhood = await client.getGraphNeighborhood({
        bank_id: currentBank,
        surface: "evidence",
        type: factType,
        q: searchQuery || undefined,
        tags: tagFilters.length > 0 ? tagFilters : undefined,
        tags_match: "all_strict",
        focus_ids: focusIds,
        depth,
        limit_nodes: 60,
        limit_edges: 140,
      });
      setEvidenceNeighborhood(neighborhood);
      return neighborhood;
    },
    [currentBank, factType, searchQuery, tagFilters]
  );

  const loadData = async (limit?: number, q?: string, tags?: string[]) => {
    if (!currentBank) return;

    setLoading(true);
    try {
      const effectiveLimit = limit ?? fetchLimit;
      const timelinePromise = timelineV2Enabled
        ? client.getTimeline({
            bank_id: currentBank,
            type: factType,
            limit: effectiveLimit,
            q,
            tags,
            tags_match: "all_strict",
          })
        : Promise.resolve(null);
      const [graphData, timelinePayload, intelligence, nextStateSummary, nextEvidenceSummary] =
        await Promise.all([
          client.getGraph({
            bank_id: currentBank,
            type: factType,
            limit: effectiveLimit,
            q,
            tags,
          }),
          timelinePromise,
          client.getGraphIntelligence({
            bank_id: currentBank,
            type: factType,
            limit: 18,
            q,
            tags,
            tags_match: "all_strict",
            confidence_min: confidenceMin,
            node_kind: nodeKind,
            window_days: windowDays === "all" ? undefined : Number(windowDays),
          }),
          client.getGraphSummary({
            bank_id: currentBank,
            surface: "state",
            type: factType,
            q,
            tags,
            tags_match: "all_strict",
            confidence_min: confidenceMin,
            node_kind: nodeKind,
            window_days: windowDays === "all" ? undefined : Number(windowDays),
          }),
          client.getGraphSummary({
            bank_id: currentBank,
            surface: "evidence",
            type: factType,
            q,
            tags,
            tags_match: "all_strict",
          }),
        ]);
      setData(graphData);
      setTimelineData(timelinePayload);
      setGraphIntelligence(intelligence);
      setStateSummary(nextStateSummary);
      setEvidenceSummary(nextEvidenceSummary);
      if (nextStateSummary.mode_hint === "overview") {
        setSelectedStateNode(null);
        setSelectedChangeEvent(null);
      } else {
        setSelectedStateNode(
          (prev) =>
            intelligence.nodes.find((node) => node.id === prev?.id) ?? intelligence.nodes[0] ?? null
        );
        setSelectedChangeEvent(
          (prev) =>
            intelligence.change_events.find((event) => event.id === prev?.id) ??
            intelligence.change_events[0] ??
            null
        );
      }

      const [nextStateNeighborhood, nextEvidenceNeighborhood] = await Promise.all([
        client.getGraphNeighborhood({
          bank_id: currentBank,
          surface: "state",
          type: factType,
          q,
          tags,
          tags_match: "all_strict",
          confidence_min: confidenceMin,
          node_kind: nodeKind,
          window_days: windowDays === "all" ? undefined : Number(windowDays),
          focus_ids: nextStateSummary.initial_focus_ids.slice(0, 1),
          depth: 1,
          limit_nodes: 60,
          limit_edges: 140,
        }),
        client.getGraphNeighborhood({
          bank_id: currentBank,
          surface: "evidence",
          type: factType,
          q,
          tags,
          tags_match: "all_strict",
          focus_ids: nextEvidenceSummary.initial_focus_ids.slice(0, 1),
          depth: 1,
          limit_nodes: 60,
          limit_edges: 140,
        }),
      ]);
      setStateNeighborhood(nextStateNeighborhood);
      setEvidenceNeighborhood(nextEvidenceNeighborhood);

      // Fetch consolidation status for observations
      if (factType === "observation") {
        const stats: any = await client.getBankStats(currentBank);
        setConsolidationStatus({
          pending_consolidation: stats.pending_consolidation || 0,
          last_consolidated_at: stats.last_consolidated_at || null,
        });
      }
    } catch {
      // Error toast is shown automatically by the API client interceptor
    } finally {
      setLoading(false);
    }
  };

  const runGraphInvestigation = useCallback(async () => {
    if (!currentBank || !analystQuery.trim()) return;

    setInvestigating(true);
    try {
      const investigation = await client.investigateGraph({
        bank_id: currentBank,
        query: analystQuery.trim(),
        type: factType,
        tags: tagFilters.length > 0 ? tagFilters : undefined,
        tags_match: "all_strict",
        confidence_min: confidenceMin,
        node_kind: nodeKind,
        window_days: windowDays === "all" ? undefined : Number(windowDays),
        limit: 18,
      });
      setGraphInvestigation(investigation);
      if (investigation.change_events[0]) {
        setSelectedChangeEvent(investigation.change_events[0]);
      }
      if (graphIntelligence && investigation.focal_node_ids.length > 0) {
        const focal = graphIntelligence.nodes.find(
          (node) => node.id === investigation.focal_node_ids[0]
        );
        if (focal) setSelectedStateNode(focal);
      }
      if (investigation.focal_node_ids.length > 0) {
        void loadStateNeighborhood(investigation.focal_node_ids.slice(0, 1), 1);
      }
    } finally {
      setInvestigating(false);
    }
  }, [
    analystQuery,
    confidenceMin,
    currentBank,
    factType,
    graphIntelligence,
    loadStateNeighborhood,
    nodeKind,
    tagFilters,
    windowDays,
  ]);

  const addTagFilter = (tag: string) => {
    const trimmed = tag.trim();
    if (trimmed && !tagFilters.includes(trimmed)) {
      setTagFilters((prev) => [...prev, trimmed]);
    }
    setTagInput("");
  };

  const removeTagFilter = (tag: string) => {
    setTagFilters((prev) => prev.filter((t) => t !== tag));
  };

  // Table rows are already filtered server-side
  const filteredTableRows = useMemo(() => {
    return data?.table_rows ?? [];
  }, [data]);

  // Helper to get normalized link type
  const getLinkTypeCategory = (type: string | undefined): string => {
    if (!type) return "semantic";
    if (type === "semantic" || type === "temporal" || type === "entity") return type;
    if (["causes", "caused_by", "enables", "prevents"].includes(type)) return "causal";
    return "semantic";
  };

  // Convert data for Graph2D (graph data is already filtered server-side)
  const graph2DData = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    const fullData = convertAtulyaGraphData(data);

    // Filter links based on visible link types
    const links = fullData.links.filter((link) => {
      const category = getLinkTypeCategory(link.type);
      return visibleLinkTypes.has(category);
    });

    return { nodes: fullData.nodes, links };
  }, [data, visibleLinkTypes]);

  // Calculate link stats for display
  const linkStats = useMemo(() => {
    let semantic = 0,
      temporal = 0,
      entity = 0,
      causal = 0,
      total = 0;
    const otherTypes: Record<string, number> = {};
    graph2DData.links.forEach((l) => {
      total++;
      const type = l.type || "unknown";
      if (type === "semantic") semantic++;
      else if (type === "temporal") temporal++;
      else if (type === "entity") entity++;
      else if (
        type === "causes" ||
        type === "caused_by" ||
        type === "enables" ||
        type === "prevents"
      )
        causal++;
      else {
        otherTypes[type] = (otherTypes[type] || 0) + 1;
      }
    });
    return { semantic, temporal, entity, causal, total, otherTypes };
  }, [graph2DData]);

  const selectRawMemoryById = useCallback(
    (memoryId: string) => {
      const nodeData = data?.table_rows?.find((row: any) => row.id === memoryId);
      if (!nodeData) return;

      const accessCount = Math.max(0, Number(nodeData.access_count ?? 0));
      const connectedLinks = graph2DData.links.filter(
        (link) => link.source === memoryId || link.target === memoryId
      );
      const connectionCount = connectedLinks.length;
      const totalLinkWeight = connectedLinks.reduce(
        (sum, link) => sum + Number(link.weight ?? 0),
        0
      );

      setSelectedGraphNode({
        ...nodeData,
        access_count: accessCount,
        graph_stats: {
          access_count: accessCount,
          connection_count: connectionCount,
          total_link_weight: totalLinkWeight,
        },
      });
    },
    [data, graph2DData.links]
  );

  const clearGraphFocus = useCallback(() => {
    setSelectedStateNode(null);
    setSelectedChangeEvent(null);
    setSelectedGraphNode(null);
    setGraphInvestigation(null);
  }, []);

  const focusStateNode = useCallback(
    (node: StateGraphNode | null, preferredEventId?: string | null) => {
      setSelectedStateNode(node);
      if (!node) {
        setSelectedChangeEvent(null);
        return;
      }

      const nodeEvents =
        graphIntelligence?.change_events.filter((event) => event.node_id === node.id) ?? [];
      const preferredEvent =
        (preferredEventId ? nodeEvents.find((event) => event.id === preferredEventId) : null) ??
        (selectedChangeEvent && nodeEvents.some((event) => event.id === selectedChangeEvent.id)
          ? selectedChangeEvent
          : null);
      setSelectedChangeEvent(preferredEvent);
      void loadStateNeighborhood([node.id], 1);
    },
    [graphIntelligence, loadStateNeighborhood, selectedChangeEvent]
  );

  const focusChangeEvent = useCallback(
    (event: GraphChangeEvent | null) => {
      setSelectedChangeEvent(event);
      if (!event) return;
      const node =
        graphIntelligence?.nodes.find((candidate) => candidate.id === event.node_id) ?? null;
      if (node) {
        setSelectedStateNode(node);
      }
      void loadStateNeighborhood([event.node_id], 1);
    },
    [graphIntelligence, loadStateNeighborhood]
  );

  const focusStateSummaryItem = useCallback(
    async (itemId: string) => {
      const item = [...(stateSummary?.top_nodes ?? []), ...(stateSummary?.clusters ?? [])].find(
        (candidate) => candidate.id === itemId
      );
      if (!item) return;
      const focusIds =
        item.kind === "cluster" ? item.cluster_membership.slice(0, 3) : [item.node_ref || item.id];
      const neighborhood = await loadStateNeighborhood(focusIds, 1);
      const focalNodeId = neighborhood?.focus_ids?.[0];
      if (!focalNodeId) return;
      const focal = graphIntelligence?.nodes.find((node) => node.id === focalNodeId) ?? null;
      if (focal) {
        setSelectedStateNode(focal);
      }
    },
    [graphIntelligence, loadStateNeighborhood, stateSummary]
  );

  const focusEvidenceSummaryItem = useCallback(
    async (itemId: string) => {
      const item = [
        ...(evidenceSummary?.top_nodes ?? []),
        ...(evidenceSummary?.clusters ?? []),
      ].find((candidate) => candidate.id === itemId);
      if (!item) return;
      const focusIds =
        item.kind === "cluster" ? item.cluster_membership.slice(0, 3) : [item.node_ref || item.id];
      await loadEvidenceNeighborhood(focusIds, 1);
      const primaryFocusId = focusIds[0];
      if (primaryFocusId) {
        selectRawMemoryById(primaryFocusId);
      }
    },
    [evidenceSummary, loadEvidenceNeighborhood, selectRawMemoryById]
  );

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.key === "Escape" &&
        (selectedGraphNode || selectedStateNode || selectedChangeEvent || graphInvestigation)
      ) {
        clearGraphFocus();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    clearGraphFocus,
    graphInvestigation,
    selectedChangeEvent,
    selectedGraphNode,
    selectedStateNode,
  ]);

  // Handle node click in graph - show in panel
  const handleGraphNodeClick = useCallback(
    (node: GraphNode) => {
      selectRawMemoryById(node.id);
    },
    [selectRawMemoryById]
  );

  const usageStats = useMemo(() => {
    const counts = graph2DData.nodes.map((node) =>
      Math.max(0, Number((node.metadata as any)?.access_count ?? 0))
    );
    const maxCount = counts.length > 0 ? Math.max(...counts) : 0;
    return { maxCount };
  }, [graph2DData.nodes]);

  // Memoized style functions to prevent graph re-initialization
  const nodeColorFn = useCallback(
    (node: GraphNode) => {
      const count = Math.max(0, Number((node.metadata as any)?.access_count ?? 0));
      const maxCount = usageStats.maxCount;
      if (maxCount <= 0) return node.color || "#dc2626";

      // Darker red means higher usage; keeps brand palette.
      const normalized = Math.log1p(count) / Math.log1p(maxCount);
      const lightness = Math.round(58 - normalized * 20); // 58% -> 38%
      return `hsl(0 72% ${lightness}%)`;
    },
    [usageStats.maxCount]
  );

  const nodeSizeFn = useCallback(
    (node: GraphNode) => {
      const count = Math.max(0, Number((node.metadata as any)?.access_count ?? 0));
      const maxCount = usageStats.maxCount;
      if (maxCount <= 0) return 18;

      const normalized = Math.log1p(count) / Math.log1p(maxCount);
      return Math.round(16 + normalized * 24); // 16..40
    },
    [usageStats.maxCount]
  );

  const linkColorFn = useCallback((link: any) => {
    if (link.type === "temporal") return "#991b1b";
    if (link.type === "entity") return "#f59e0b"; // Amber
    if (
      link.type === "causes" ||
      link.type === "caused_by" ||
      link.type === "enables" ||
      link.type === "prevents"
    ) {
      return "#8b5cf6"; // Purple for causal
    }
    return "#dc2626";
  }, []);

  // Reset to first page when filters change
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, tagFilters]);

  // Debounce ref for text search
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Trigger server-side reload when text filter changes (debounced 300ms)
  useEffect(() => {
    if (searchDebounceRef.current) {
      clearTimeout(searchDebounceRef.current);
    }
    searchDebounceRef.current = setTimeout(() => {
      if (currentBank) {
        loadData(
          undefined,
          searchQuery || undefined,
          tagFilters.length > 0 ? tagFilters : undefined
        );
      }
    }, 300);
    return () => {
      if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    };
  }, [searchQuery]);

  // Trigger server-side reload immediately when tag filters change
  useEffect(() => {
    if (currentBank) {
      loadData(undefined, searchQuery || undefined, tagFilters.length > 0 ? tagFilters : undefined);
    }
  }, [tagFilters]);

  useEffect(() => {
    if (currentBank) {
      setGraphInvestigation(null);
      loadData(undefined, searchQuery || undefined, tagFilters.length > 0 ? tagFilters : undefined);
    }
  }, [confidenceMin, nodeKind, windowDays]);

  // Auto-load data when component mounts or factType/currentBank changes
  useEffect(() => {
    if (currentBank) {
      setGraphInvestigation(null);
      loadData();
    }
  }, [factType, currentBank, timelineV2Enabled]);

  // Enforce 50 node limit to prevent UI instability, default to 20 or max whichever is smaller
  useEffect(() => {
    if (data && maxNodes === undefined) {
      if (graph2DData.nodes.length > 50) {
        // Always set maxNodes to 20 when we have >50 nodes (never leave as undefined)
        setMaxNodes(20);
      } else if (graph2DData.nodes.length > 20) {
        setMaxNodes(20);
      }
      // If ≤20 nodes, leave maxNodes undefined to show all
    }
  }, [data, graph2DData.nodes.length, maxNodes]);

  const memoryById = useMemo(
    () => new Map((data?.table_rows ?? []).map((row: any) => [row.id, row])),
    [data]
  );

  const neighborhoodStateNodes = useMemo(() => {
    const entries = (stateNeighborhood?.nodes ?? [])
      .map((node) => stateNodeFromNeighborhood(node))
      .filter((node): node is StateGraphNode => node !== null)
      .map((node) => [node.id, node] as const);
    return new Map(entries);
  }, [stateNeighborhood?.nodes]);

  const resolvedSelectedStateNode = useMemo(() => {
    if (selectedStateNode) return selectedStateNode;
    const focusId = stateNeighborhood?.focus_ids?.[0];
    return focusId ? (neighborhoodStateNodes.get(focusId) ?? null) : null;
  }, [neighborhoodStateNodes, selectedStateNode, stateNeighborhood?.focus_ids]);

  const selectedStateEvents = useMemo(
    () =>
      graphIntelligence?.change_events.filter(
        (event) => event.node_id === resolvedSelectedStateNode?.id
      ) ?? [],
    [graphIntelligence, resolvedSelectedStateNode]
  );

  const selectedEvidenceRows = useMemo<any[]>(() => {
    const evidenceIds =
      selectedChangeEvent?.evidence_ids ??
      resolvedSelectedStateNode?.evidence_ids ??
      graphInvestigation?.evidence_path
        .filter((step) => step.kind === "memory")
        .map((step) => step.id) ??
      [];
    return evidenceIds
      .map((id) => memoryById.get(id))
      .filter(Boolean)
      .slice(0, 6);
  }, [graphInvestigation, memoryById, resolvedSelectedStateNode, selectedChangeEvent]);

  const selectedEvidenceIds = useMemo(
    () => selectedEvidenceRows.map((row: any) => row.id as string),
    [selectedEvidenceRows]
  );

  const highlightedNodeIds = useMemo(() => {
    if (graphInvestigation?.focal_node_ids?.length) return graphInvestigation.focal_node_ids;
    return resolvedSelectedStateNode ? [resolvedSelectedStateNode.id] : [];
  }, [graphInvestigation, resolvedSelectedStateNode]);

  const highlightedEdgeIds = graphInvestigation?.focal_edge_ids ?? [];

  const recommendedChecks = useMemo(() => {
    if (graphInvestigation?.recommended_checks?.length)
      return graphInvestigation.recommended_checks;
    if (selectedChangeEvent?.change_type === "contradiction") {
      return [
        "Review the conflicting evidence with the strongest semantic overlap and confirm which source is most current.",
      ];
    }
    if (
      selectedChangeEvent?.change_type === "change" ||
      resolvedSelectedStateNode?.status === "changed"
    ) {
      return ["Check downstream summaries and observations that depend on this state."];
    }
    if (
      selectedChangeEvent?.change_type === "stale" ||
      resolvedSelectedStateNode?.status === "stale"
    ) {
      return ["Refresh this area with newer evidence before using it operationally."];
    }
    return ["Inspect the supporting evidence before promoting this into a durable mental model."];
  }, [graphInvestigation, resolvedSelectedStateNode, selectedChangeEvent]);

  const switchGraphSurface = useCallback(
    (mode: GraphSurfaceMode) => {
      setGraphSurfaceMode(mode);

      if (mode === "evidence") {
        if (selectedGraphNode) return;
        const firstEvidence = selectedEvidenceRows[0];
        if (firstEvidence) {
          selectRawMemoryById(firstEvidence.id);
        }
      }
    },
    [selectRawMemoryById, selectedEvidenceRows, selectedGraphNode]
  );

  const openEvidenceGraph = useCallback(() => {
    const firstEvidence = selectedEvidenceRows[0];
    if (!firstEvidence) return;
    setGraphSurfaceMode("evidence");
    selectRawMemoryById(firstEvidence.id);
  }, [selectRawMemoryById, selectedEvidenceRows]);

  const openRawEvidence = useCallback(() => {
    const firstEvidence = selectedEvidenceRows[0];
    if (firstEvidence) {
      setModalMemoryId(firstEvidence.id);
    }
  }, [selectedEvidenceRows]);

  const focusNeighborhood = useCallback(() => {
    const focusId = resolvedSelectedStateNode?.id || graphIntelligence?.nodes[0]?.id;
    if (!focusId) return;
    void loadStateNeighborhood([focusId], 2);
  }, [graphIntelligence?.nodes, loadStateNeighborhood, resolvedSelectedStateNode?.id]);

  const stateGraphActions = [
    {
      key: "focus-neighbors",
      label: "Focus Neighbors",
      onClick: focusNeighborhood,
      disabled: !resolvedSelectedStateNode && !graphIntelligence?.nodes?.length,
    },
    {
      key: "open-evidence-graph",
      label: "Open Evidence Graph",
      onClick: openEvidenceGraph,
      disabled: selectedEvidenceRows.length === 0,
    },
    {
      key: "open-raw-memory",
      label: "Open Raw Memory",
      onClick: openRawEvidence,
      disabled: selectedEvidenceRows.length === 0,
    },
    {
      key: "reset-card-positions",
      label: "Reset Card Positions",
      onClick: () => setGraphLayoutResetVersion((value) => value + 1),
      disabled: false,
    },
  ] as const;

  const renderStateGraphActionGrid = (
    gridClassName: string,
    buttonClassName: string,
    contentClassName = "text-center"
  ) => (
    <div className={`grid gap-2 ${gridClassName}`}>
      {stateGraphActions.map((action) => (
        <Button
          key={action.key}
          variant="outline"
          className={buttonClassName}
          onClick={action.onClick}
          disabled={action.disabled}
        >
          <span className={contentClassName}>{action.label}</span>
        </Button>
      ))}
    </div>
  );

  const stateGraphFullscreenAccessory = (
    <div className="space-y-3">
      <div className="space-y-1">
        <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          Canvas Actions
        </div>
        <div className="text-sm font-semibold text-foreground">
          {resolvedSelectedStateNode?.title || "State Graph"}
        </div>
        <p className="text-xs leading-5 text-muted-foreground">
          {recommendedChecks[0] || "Use graph actions without leaving fullscreen mode."}
        </p>
      </div>
      {renderStateGraphActionGrid(
        "grid-cols-2",
        "h-auto min-h-10 min-w-0 whitespace-normal px-3 py-2 text-sm leading-tight"
      )}
    </div>
  );

  const inspectorHeadline =
    graphInvestigation?.answer ||
    selectedChangeEvent?.summary ||
    resolvedSelectedStateNode?.status_reason ||
    resolvedSelectedStateNode?.current_state ||
    "Select a state card to inspect what changed, why Atulya believes it, and what to do next.";
  const selectedStateSupportPercent = resolvedSelectedStateNode
    ? Math.round(resolvedSelectedStateNode.confidence * 100)
    : null;
  const selectedStateSignalPercent = resolvedSelectedStateNode
    ? Math.round(resolvedSelectedStateNode.change_score * 100)
    : null;

  useEffect(() => {
    if (typeof window === "undefined") return;

    const mediaQuery = window.matchMedia("(max-width: 1280px)");
    const syncCompactLayout = () => {
      setIsCompactGraphLayout(mediaQuery.matches);
      setShowControlPanel((current) => (mediaQuery.matches ? true : current));
    };

    syncCompactLayout();
    mediaQuery.addEventListener("change", syncCompactLayout);
    return () => mediaQuery.removeEventListener("change", syncCompactLayout);
  }, []);

  const graphCanvasHeight = isCompactGraphLayout ? 560 : 700;

  return (
    <div>
      {loading && !data ? (
        <div className="text-center py-12">
          <RefreshCw className="w-8 h-8 mx-auto mb-3 text-muted-foreground animate-spin" />
          <p className="text-muted-foreground">Loading memories...</p>
        </div>
      ) : data ? (
        <>
          {/* Always visible filters */}
          <div className="mb-4 space-y-2">
            <div className="flex flex-col gap-2 lg:flex-row lg:items-center">
              {/* Text search */}
              <div className="relative w-full lg:max-w-xs lg:flex-1">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                <Input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Filter by text or context..."
                  className="pl-8 h-9"
                />
              </div>
              {/* Tag input */}
              <div className="relative w-full lg:max-w-xs lg:flex-1">
                <Tag className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                <Input
                  type="text"
                  value={tagInput}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === ",") {
                      e.preventDefault();
                      addTagFilter(tagInput);
                    } else if (e.key === "Backspace" && !tagInput && tagFilters.length > 0) {
                      removeTagFilter(tagFilters[tagFilters.length - 1]);
                    }
                  }}
                  placeholder="Filter by tag…"
                  className="pl-8 h-9"
                />
              </div>
            </div>
            {/* Active tag chips */}
            {tagFilters.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {tagFilters.map((tag) => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-md bg-primary/10 text-primary border border-primary/20 font-medium leading-none"
                  >
                    <span className="opacity-50 select-none font-mono">#</span>
                    {tag}
                    <button
                      onClick={() => removeTagFilter(tag)}
                      className="opacity-50 hover:opacity-100 transition-opacity ml-0.5"
                      aria-label={`Remove tag ${tag}`}
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="mb-6 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:gap-4">
              <div className="text-sm text-muted-foreground">
                {searchQuery || tagFilters.length > 0 ? (
                  `${filteredTableRows.length} matching memories`
                ) : data.table_rows?.length < data.total_units ? (
                  <span>
                    Showing {data.table_rows?.length ?? 0} of {data.total_units} total memories
                    <button
                      onClick={() => {
                        const newLimit = Math.min(data.total_units, fetchLimit + 1000);
                        setFetchLimit(newLimit);
                        loadData(newLimit);
                      }}
                      className="ml-2 text-primary hover:underline"
                    >
                      Load more
                    </button>
                  </span>
                ) : (
                  `${data.total_units} total memories`
                )}
              </div>

              {/* Consolidation status for observations */}
              {factType === "observation" && consolidationStatus && (
                <span
                  className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium border ${
                    consolidationStatus.pending_consolidation === 0
                      ? "bg-green-500/10 text-green-700 dark:text-green-400 border-green-500/20"
                      : "bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/20"
                  }`}
                  title={
                    consolidationStatus.pending_consolidation === 0
                      ? `All memories consolidated${consolidationStatus.last_consolidated_at ? ` (last: ${new Date(consolidationStatus.last_consolidated_at).toLocaleString()})` : ""}`
                      : `${consolidationStatus.pending_consolidation} memories pending consolidation`
                  }
                >
                  {consolidationStatus.pending_consolidation === 0 ? (
                    <>
                      <CheckCircle className="w-3 h-3" />
                      In Sync
                    </>
                  ) : (
                    <>
                      <Clock className="w-3 h-3" />
                      {consolidationStatus.pending_consolidation} Pending
                      <button
                        onClick={() =>
                          loadData(
                            fetchLimit,
                            searchQuery || undefined,
                            tagFilters.length > 0 ? tagFilters : undefined
                          )
                        }
                        disabled={loading}
                        className="ml-0.5 opacity-70 hover:opacity-100 disabled:opacity-40 transition-opacity"
                        title="Refresh observations"
                      >
                        <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
                      </button>
                    </>
                  )}
                </span>
              )}
            </div>
            <div className="flex w-full items-center gap-2 overflow-x-auto rounded-lg bg-muted p-1 xl:w-auto">
              <button
                onClick={() => setViewMode("graph")}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all flex items-center gap-1.5 ${
                  viewMode === "graph"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Network className="w-4 h-4" />
                Graph
              </button>
              <button
                onClick={() => setViewMode("table")}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all flex items-center gap-1.5 ${
                  viewMode === "table"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <List className="w-4 h-4" />
                Table
              </button>
              <button
                onClick={() => setViewMode("timeline")}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all flex items-center gap-1.5 ${
                  viewMode === "timeline"
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                <Calendar className="w-4 h-4" />
                Timeline
              </button>
            </div>
          </div>

          {viewMode === "graph" && (
            <div className="space-y-4">
              <div className="rounded-xl border border-border bg-card p-4 space-y-3">
                <div className="flex flex-col gap-2 xl:flex-row xl:items-center">
                  <div className="flex items-center gap-2 bg-muted rounded-lg p-1">
                    <button
                      onClick={() => switchGraphSurface("state")}
                      className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all ${
                        graphSurfaceMode === "state"
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      State Graph
                    </button>
                    <button
                      onClick={() => switchGraphSurface("evidence")}
                      className={`px-3 py-1.5 rounded-md text-sm font-medium transition-all ${
                        graphSurfaceMode === "evidence"
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      Evidence Graph
                    </button>
                  </div>
                  <div className="relative min-w-0 flex-1 xl:min-w-[260px]">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                    <Input
                      value={analystQuery}
                      onChange={(e) => setAnalystQuery(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          runGraphInvestigation();
                        }
                      }}
                      placeholder="Ask the graph analyst what changed..."
                      className="pl-8"
                    />
                  </div>
                  <div className="flex flex-wrap items-center gap-2 xl:flex-nowrap">
                    <Button
                      onClick={runGraphInvestigation}
                      disabled={investigating || !analystQuery.trim()}
                    >
                      {investigating ? "Analyzing..." : "Investigate"}
                    </Button>
                    <Button variant="outline" onClick={clearGraphFocus}>
                      Clear Focus
                    </Button>
                    <Button
                      variant="outline"
                      onClick={() => setGraphLayoutResetVersion((value) => value + 1)}
                    >
                      Reset Layout
                    </Button>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <label className="text-muted-foreground">Time window</label>
                  <select
                    value={windowDays}
                    onChange={(e) => setWindowDays(e.target.value)}
                    className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                  >
                    <option value="30">30 days</option>
                    <option value="90">90 days</option>
                    <option value="180">180 days</option>
                    <option value="all">All time</option>
                  </select>
                  <label className="text-muted-foreground">Support</label>
                  <select
                    value={String(confidenceMin)}
                    onChange={(e) => setConfidenceMin(Number(e.target.value))}
                    className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                  >
                    <option value="0.4">40%+</option>
                    <option value="0.55">55%+</option>
                    <option value="0.7">70%+</option>
                  </select>
                  <label className="text-muted-foreground">Node kind</label>
                  <select
                    value={nodeKind}
                    onChange={(e) => setNodeKind(e.target.value as "all" | "entity" | "topic")}
                    className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                  >
                    <option value="all">All</option>
                    <option value="entity">Entities</option>
                    <option value="topic">Topics</option>
                  </select>
                  {(graphSurfaceMode === "state" ? stateSummary : evidenceSummary) && (
                    <div className="w-full text-xs text-muted-foreground xl:ml-auto xl:w-auto">
                      {graphSurfaceMode === "state"
                        ? `${stateNeighborhood?.nodes.length ?? graphIntelligence?.nodes.length ?? 0} visible of ${stateSummary?.total_nodes ?? graphIntelligence?.total_nodes ?? 0} state nodes`
                        : `${evidenceNeighborhood?.nodes.length ?? graph2DData.nodes.length} visible of ${evidenceSummary?.total_nodes ?? graph2DData.nodes.length} evidence memories`}
                    </div>
                  )}
                </div>
              </div>

              <div className={`flex gap-0 ${isCompactGraphLayout ? "flex-col" : "flex-row"}`}>
                <div className="flex-1 min-w-0">
                  {graphSurfaceMode === "state" ? (
                    <StateGraph
                      data={graphIntelligence}
                      summary={stateSummary}
                      neighborhood={stateNeighborhood}
                      height={graphCanvasHeight}
                      fullscreenAccessory={stateGraphFullscreenAccessory}
                      selectedNodeId={resolvedSelectedStateNode?.id}
                      selectedEventId={selectedChangeEvent?.id}
                      highlightedNodeIds={highlightedNodeIds}
                      highlightedEdgeIds={highlightedEdgeIds}
                      storageKey={stateLayoutStorageKey}
                      resetLayoutVersion={graphLayoutResetVersion}
                      onBackgroundClick={clearGraphFocus}
                      onNodeClick={(node) => focusStateNode(node)}
                      onEventClick={(event) => focusChangeEvent(event)}
                      onSummaryClick={focusStateSummaryItem}
                    />
                  ) : (
                    <Graph2D
                      data={graph2DData}
                      summary={evidenceSummary}
                      neighborhood={evidenceNeighborhood}
                      height={graphCanvasHeight}
                      showLabels={showLabels}
                      selectedNodeId={selectedGraphNode?.id ?? null}
                      highlightedNodeIds={selectedEvidenceIds}
                      onNodeClick={handleGraphNodeClick}
                      onBackgroundClick={() => setSelectedGraphNode(null)}
                      maxNodes={maxNodes}
                      nodeColorFn={nodeColorFn}
                      nodeSizeFn={nodeSizeFn}
                      linkColorFn={linkColorFn}
                      storageKey={evidenceLayoutStorageKey}
                      resetLayoutVersion={graphLayoutResetVersion}
                      onSummaryClick={focusEvidenceSummaryItem}
                    />
                  )}
                </div>

                {!isCompactGraphLayout && (
                  <button
                    onClick={() => setShowControlPanel(!showControlPanel)}
                    className={`flex-shrink-0 w-5 bg-transparent hover:bg-muted/50 flex items-center justify-center transition-colors`}
                    style={{ height: graphCanvasHeight }}
                    title={showControlPanel ? "Hide panel" : "Show panel"}
                  >
                    {showControlPanel ? (
                      <ChevronRight className="w-3 h-3 text-muted-foreground/60" />
                    ) : (
                      <ChevronLeft className="w-3 h-3 text-muted-foreground/60" />
                    )}
                  </button>
                )}

                <div
                  className={
                    isCompactGraphLayout
                      ? "mt-4 w-full overflow-hidden rounded-xl border border-border bg-card"
                      : `${showControlPanel ? "w-80" : "w-0"} transition-all duration-300 overflow-hidden flex-shrink-0`
                  }
                >
                  <div
                    className={`${isCompactGraphLayout ? "w-full border-t" : "w-80 border-l"} bg-card border-border overflow-y-auto`}
                    style={{ height: graphCanvasHeight }}
                  >
                    {graphSurfaceMode === "state" ? (
                      <div className="p-4 space-y-5">
                        <div>
                          <div className="text-xs font-bold text-muted-foreground uppercase mb-2">
                            Graph Intelligence
                          </div>
                          <h3 className="text-lg font-semibold text-foreground">
                            {resolvedSelectedStateNode?.title || "Top graph signals"}
                          </h3>
                          <p className="text-sm text-muted-foreground mt-1">{inspectorHeadline}</p>
                          <p className="mt-2 text-xs leading-5 text-muted-foreground">
                            Support measures how well the current state is backed by evidence.
                            Signal measures how strongly Atulya is surfacing it after consistency
                            checks like conflict and staleness.
                          </p>
                        </div>

                        {resolvedSelectedStateNode && (
                          <div className="rounded-xl border border-border bg-muted/30 p-4 space-y-2">
                            <div className="text-xs font-bold text-muted-foreground uppercase">
                              What This Is
                            </div>
                            <div className="text-sm font-medium text-foreground">
                              {resolvedSelectedStateNode.subtitle ||
                                `${resolvedSelectedStateNode.kind} state`}
                            </div>
                            <div className="text-sm text-muted-foreground leading-relaxed">
                              {resolvedSelectedStateNode.status_reason}
                            </div>
                            {resolvedSelectedStateNode.status === "contradictory" ? (
                              <div className="text-xs leading-5 text-muted-foreground">
                                Conflict only appears when Atulya sees competing statements with
                                meaningful semantic overlap. Missing embeddings no longer trigger a
                                conflict by fallback.
                              </div>
                            ) : null}
                          </div>
                        )}

                        {resolvedSelectedStateNode && (
                          <div className="grid grid-cols-2 gap-2 text-sm">
                            <div className="p-2 rounded bg-muted/40 border border-border">
                              <div className="text-[11px] text-muted-foreground">Status</div>
                              <div className="font-semibold text-foreground capitalize">
                                {resolvedSelectedStateNode.status === "contradictory"
                                  ? "conflict"
                                  : resolvedSelectedStateNode.status}
                              </div>
                            </div>
                            <div className="p-2 rounded bg-muted/40 border border-border">
                              <div className="text-[11px] text-muted-foreground">Support</div>
                              <div className="font-semibold text-foreground">
                                {selectedStateSupportPercent}%
                              </div>
                            </div>
                            <div className="p-2 rounded bg-muted/40 border border-border">
                              <div className="text-[11px] text-muted-foreground">Signal</div>
                              <div className="font-semibold text-foreground">
                                {selectedStateSignalPercent}%
                              </div>
                            </div>
                            <div className="p-2 rounded bg-muted/40 border border-border">
                              <div className="text-[11px] text-muted-foreground">Evidence</div>
                              <div className="font-semibold text-foreground">
                                {resolvedSelectedStateNode.evidence_count}
                              </div>
                            </div>
                            <div className="p-2 rounded bg-muted/40 border border-border col-span-2">
                              <div className="text-[11px] text-muted-foreground">Kind</div>
                              <div className="font-semibold text-foreground capitalize">
                                {resolvedSelectedStateNode.kind}
                              </div>
                            </div>
                          </div>
                        )}

                        {resolvedSelectedStateNode && (
                          <div>
                            <div className="text-xs font-bold text-muted-foreground uppercase mb-2">
                              Supported State
                            </div>
                            <div className="text-sm text-foreground leading-relaxed">
                              {resolvedSelectedStateNode.current_state}
                            </div>
                            {resolvedSelectedStateNode.primary_timestamp && (
                              <div className="mt-2 text-xs text-muted-foreground">
                                Primary evidence from{" "}
                                {new Date(
                                  resolvedSelectedStateNode.primary_timestamp
                                ).toLocaleString()}
                              </div>
                            )}
                          </div>
                        )}

                        <div>
                          <div className="text-xs font-bold text-muted-foreground uppercase mb-2">
                            What Changed
                          </div>
                          <div className="space-y-2">
                            {(selectedStateEvents.length > 0
                              ? selectedStateEvents
                              : (graphIntelligence?.change_events.slice(0, 3) ?? [])
                            ).map((event) => (
                              <button
                                key={event.id}
                                onClick={() => focusChangeEvent(event)}
                                className={`w-full text-left p-3 rounded-lg border transition-colors ${
                                  selectedChangeEvent?.id === event.id
                                    ? "border-primary bg-primary/5"
                                    : "border-border hover:bg-muted/40"
                                }`}
                              >
                                <div className="text-sm font-medium text-foreground capitalize">
                                  {event.change_type === "contradiction"
                                    ? "Conflict"
                                    : event.change_type}
                                </div>
                                <div className="text-xs text-muted-foreground mt-1">
                                  {event.summary}
                                </div>
                                <div className="mt-2 text-[11px] font-medium text-muted-foreground">
                                  Signal {Math.round(event.confidence * 100)}%
                                </div>
                                {event.change_type === "contradiction" ? (
                                  <div className="mt-1 text-[11px] leading-5 text-muted-foreground">
                                    Semantic overlap verified before Atulya surfaced this conflict.
                                  </div>
                                ) : null}
                              </button>
                            ))}
                          </div>
                        </div>

                        <div>
                          <div className="text-xs font-bold text-muted-foreground uppercase mb-2">
                            Why Atulya Thinks This
                          </div>
                          <div className="space-y-2">
                            {selectedEvidenceRows.length > 0 ? (
                              selectedEvidenceRows.map((row: any) => (
                                <button
                                  key={row.id}
                                  onClick={() => setModalMemoryId(row.id)}
                                  className="w-full text-left p-3 rounded-lg border border-border hover:bg-muted/40 transition-colors"
                                >
                                  <div className="text-sm text-foreground line-clamp-2">
                                    {row.text}
                                  </div>
                                  <div className="text-xs text-muted-foreground mt-1">
                                    {row.mentioned_at
                                      ? new Date(row.mentioned_at).toLocaleString()
                                      : row.occurred_start
                                        ? new Date(row.occurred_start).toLocaleString()
                                        : "No timestamp"}
                                  </div>
                                </button>
                              ))
                            ) : (
                              <div className="text-sm text-muted-foreground">
                                Ask the graph analyst a question or select a state node to surface
                                supporting proof.
                              </div>
                            )}
                          </div>
                        </div>

                        <div>
                          <div className="text-xs font-bold text-muted-foreground uppercase mb-2">
                            Recommended Checks
                          </div>
                          <div className="space-y-2">
                            {recommendedChecks.map((check) => (
                              <div
                                key={check}
                                className="text-sm text-foreground p-3 rounded-lg bg-muted/40 border border-border"
                              >
                                {check}
                              </div>
                            ))}
                          </div>
                        </div>

                        {renderStateGraphActionGrid(
                          isCompactGraphLayout ? "grid-cols-2" : "grid-cols-1",
                          "h-auto min-h-10 w-full min-w-0 whitespace-normal px-4 py-2 text-center leading-tight"
                        )}
                      </div>
                    ) : selectedGraphNode ? (
                      <MemoryDetailPanel
                        memory={selectedGraphNode}
                        onClose={() => setSelectedGraphNode(null)}
                        inPanel
                        bankId={currentBank || undefined}
                      />
                    ) : (
                      <div className="p-4 space-y-5">
                        <div>
                          <h3 className="text-sm font-semibold mb-3 text-foreground">
                            Evidence Graph
                          </h3>
                          <div className="space-y-2">
                            <div className="flex items-center justify-between text-sm">
                              <div className="flex items-center gap-2">
                                <div
                                  className="w-3 h-3 rounded-full"
                                  style={{ backgroundColor: "#dc2626" }}
                                />
                                <span className="text-foreground">Nodes</span>
                              </div>
                              <span className="font-mono text-foreground">
                                {Math.min(
                                  maxNodes ?? graph2DData.nodes.length,
                                  graph2DData.nodes.length
                                )}
                                /{graph2DData.nodes.length}
                              </span>
                            </div>

                            <div className="text-xs font-medium text-muted-foreground mt-2 mb-1">
                              Links ({linkStats.total}){" "}
                              <span className="text-muted-foreground/60">· click to filter</span>
                            </div>
                            <button
                              onClick={() => toggleLinkType("semantic")}
                              className={`w-full flex items-center justify-between text-sm px-2 py-1 rounded transition-all ${
                                visibleLinkTypes.has("semantic")
                                  ? "hover:bg-muted"
                                  : "opacity-40 hover:opacity-60"
                              }`}
                            >
                              <div className="flex items-center gap-2">
                                <div className="w-4 h-0.5 bg-[#dc2626]" />
                                <span className="text-foreground">Semantic</span>
                              </div>
                              <span
                                className={`font-mono ${linkStats.semantic === 0 ? "text-destructive" : "text-foreground"}`}
                              >
                                {linkStats.semantic}
                              </span>
                            </button>
                            <button
                              onClick={() => toggleLinkType("temporal")}
                              className={`w-full flex items-center justify-between text-sm px-2 py-1 rounded transition-all ${
                                visibleLinkTypes.has("temporal")
                                  ? "hover:bg-muted"
                                  : "opacity-40 hover:opacity-60"
                              }`}
                            >
                              <div className="flex items-center gap-2">
                                <div className="w-4 h-0.5 bg-[#991b1b]" />
                                <span className="text-foreground">Temporal</span>
                              </div>
                              <span
                                className={`font-mono ${linkStats.temporal === 0 ? "text-destructive" : "text-foreground"}`}
                              >
                                {linkStats.temporal}
                              </span>
                            </button>
                            <button
                              onClick={() => toggleLinkType("entity")}
                              className={`w-full flex items-center justify-between text-sm px-2 py-1 rounded transition-all ${
                                visibleLinkTypes.has("entity")
                                  ? "hover:bg-muted"
                                  : "opacity-40 hover:opacity-60"
                              }`}
                            >
                              <div className="flex items-center gap-2">
                                <div className="w-4 h-0.5 bg-[#f59e0b]" />
                                <span className="text-foreground">Entity</span>
                              </div>
                              <span className="font-mono text-foreground">{linkStats.entity}</span>
                            </button>
                            <button
                              onClick={() => toggleLinkType("causal")}
                              className={`w-full flex items-center justify-between text-sm px-2 py-1 rounded transition-all ${
                                visibleLinkTypes.has("causal")
                                  ? "hover:bg-muted"
                                  : "opacity-40 hover:opacity-60"
                              }`}
                            >
                              <div className="flex items-center gap-2">
                                <div className="w-4 h-0.5 bg-[#8b5cf6]" />
                                <span className="text-foreground">Causal</span>
                              </div>
                              <span
                                className={`font-mono ${linkStats.causal === 0 ? "text-muted-foreground" : "text-foreground"}`}
                              >
                                {linkStats.causal}
                              </span>
                            </button>
                          </div>
                        </div>

                        <div className="border-t border-border" />

                        <div>
                          <h3 className="text-sm font-semibold mb-3 text-foreground">Display</h3>
                          <div className="space-y-4">
                            <div className="flex items-center justify-between">
                              <Label htmlFor="show-labels" className="text-sm text-foreground">
                                Show labels
                              </Label>
                              <Switch
                                id="show-labels"
                                checked={showLabels}
                                onCheckedChange={setShowLabels}
                              />
                            </div>
                          </div>
                        </div>

                        <div className="border-t border-border" />

                        <div>
                          <h3 className="text-sm font-semibold mb-3 text-foreground">
                            Performance
                          </h3>
                          <div className="space-y-4">
                            <div>
                              <div className="flex items-center justify-between mb-2">
                                <Label className="text-sm text-foreground">Max nodes</Label>
                                <span className="text-xs text-muted-foreground">
                                  {graph2DData.nodes.length > 50
                                    ? `${maxNodes ?? 50} / ${graph2DData.nodes.length}`
                                    : `${maxNodes ?? "All"} / ${graph2DData.nodes.length}`}
                                </span>
                              </div>
                              <Slider
                                value={[
                                  graph2DData.nodes.length > 50
                                    ? maxNodes || 20
                                    : maxNodes || Math.min(graph2DData.nodes.length, 20),
                                ]}
                                min={10}
                                max={Math.min(Math.max(graph2DData.nodes.length, 10), 50)}
                                step={10}
                                onValueChange={([v]) => {
                                  const effectiveMax = Math.min(graph2DData.nodes.length, 50);
                                  if (graph2DData.nodes.length > 50) {
                                    setMaxNodes(v);
                                  } else {
                                    setMaxNodes(v >= effectiveMax ? undefined : v);
                                  }
                                }}
                                className="w-full"
                              />
                            </div>
                            <p className="text-xs text-muted-foreground">
                              All links between visible nodes are shown.
                            </p>
                          </div>
                        </div>

                        <div className="border-t border-border" />
                        <div className="text-xs text-muted-foreground/60 text-center pt-2">
                          Click a node to inspect the raw memory proof
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {viewMode === "table" && (
            <div>
              <div className="w-full">
                <div className="pb-4">
                  {filteredTableRows.length > 0 ? (
                    (() => {
                      const totalPages = Math.ceil(filteredTableRows.length / itemsPerPage);
                      const startIndex = (currentPage - 1) * itemsPerPage;
                      const endIndex = startIndex + itemsPerPage;
                      const paginatedRows = filteredTableRows.slice(startIndex, endIndex);

                      return (
                        <>
                          <div className="border rounded-lg overflow-hidden">
                            <Table className="table-fixed">
                              <TableHeader>
                                <TableRow className="bg-muted/50">
                                  <TableHead
                                    className={factType === "observation" ? "w-[35%]" : "w-[38%]"}
                                  >
                                    {factType === "observation" ? "Observation" : "Memory"}
                                  </TableHead>
                                  <TableHead className="w-[15%]">Entities</TableHead>
                                  <TableHead className="w-[15%]">Tags</TableHead>
                                  {factType === "observation" && (
                                    <TableHead className="w-[10%]">Sources</TableHead>
                                  )}
                                  <TableHead
                                    className={factType === "observation" ? "w-[12%]" : "w-[16%]"}
                                  >
                                    Occurred
                                  </TableHead>
                                  <TableHead
                                    className={factType === "observation" ? "w-[13%]" : "w-[16%]"}
                                  >
                                    Mentioned
                                  </TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {paginatedRows.map((row: any, idx: number) => {
                                  const occurredDisplay = row.occurred_start
                                    ? new Date(row.occurred_start).toLocaleDateString("en-US", {
                                        month: "short",
                                        day: "numeric",
                                        year: "numeric",
                                      })
                                    : null;
                                  const mentionedDisplay = row.mentioned_at
                                    ? new Date(row.mentioned_at).toLocaleDateString("en-US", {
                                        month: "short",
                                        day: "numeric",
                                        year: "numeric",
                                      })
                                    : null;

                                  return (
                                    <TableRow
                                      key={row.id || idx}
                                      onClick={() => setModalMemoryId(row.id)}
                                      className="cursor-pointer hover:bg-muted/50"
                                    >
                                      <TableCell className="py-2">
                                        <div className="line-clamp-2 text-sm leading-snug text-foreground">
                                          {row.text}
                                        </div>
                                        {row.context && factType !== "observation" && (
                                          <div className="text-xs text-muted-foreground mt-0.5 truncate">
                                            {row.context}
                                          </div>
                                        )}
                                      </TableCell>
                                      <TableCell className="py-2">
                                        {row.entities ? (
                                          <div className="flex gap-1 flex-wrap">
                                            {row.entities
                                              .split(", ")
                                              .slice(0, 2)
                                              .map((entity: string, i: number) => (
                                                <span
                                                  key={i}
                                                  className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-medium"
                                                >
                                                  {entity}
                                                </span>
                                              ))}
                                            {row.entities.split(", ").length > 2 && (
                                              <span className="text-[10px] text-muted-foreground">
                                                +{row.entities.split(", ").length - 2}
                                              </span>
                                            )}
                                          </div>
                                        ) : (
                                          <span className="text-xs text-muted-foreground">-</span>
                                        )}
                                      </TableCell>
                                      <TableCell className="py-2">
                                        {row.tags && row.tags.length > 0 ? (
                                          <div className="flex gap-1 flex-wrap">
                                            {(row.tags as string[])
                                              .slice(0, 2)
                                              .map((tag: string, i: number) => (
                                                <span
                                                  key={i}
                                                  className="text-[10px] px-1.5 py-0.5 rounded-md bg-amber-500/10 text-amber-700 border border-amber-500/20 font-medium font-mono"
                                                >
                                                  #{tag}
                                                </span>
                                              ))}
                                            {row.tags.length > 2 && (
                                              <span className="text-[10px] text-muted-foreground">
                                                +{row.tags.length - 2}
                                              </span>
                                            )}
                                          </div>
                                        ) : (
                                          <span className="text-xs text-muted-foreground">-</span>
                                        )}
                                      </TableCell>
                                      {factType === "observation" && (
                                        <TableCell className="text-xs py-2 text-foreground">
                                          {row.proof_count ?? 1}
                                        </TableCell>
                                      )}
                                      <TableCell className="text-xs py-2 text-foreground">
                                        {occurredDisplay || (
                                          <span className="text-muted-foreground">-</span>
                                        )}
                                      </TableCell>
                                      <TableCell className="text-xs py-2 text-foreground">
                                        {mentionedDisplay || (
                                          <span className="text-muted-foreground">-</span>
                                        )}
                                      </TableCell>
                                    </TableRow>
                                  );
                                })}
                              </TableBody>
                            </Table>
                          </div>

                          {/* Pagination Controls */}
                          {totalPages > 1 && (
                            <div className="flex items-center justify-between mt-3 pt-3 border-t">
                              <div className="text-xs text-muted-foreground">
                                {startIndex + 1}-{Math.min(endIndex, filteredTableRows.length)} of{" "}
                                {filteredTableRows.length}
                              </div>
                              <div className="flex items-center gap-1">
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => setCurrentPage(1)}
                                  disabled={currentPage === 1}
                                  className="h-7 w-7 p-0"
                                >
                                  <ChevronsLeft className="h-3 w-3" />
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                                  disabled={currentPage === 1}
                                  className="h-7 w-7 p-0"
                                >
                                  <ChevronLeft className="h-3 w-3" />
                                </Button>
                                <span className="text-xs px-2">
                                  {currentPage} / {totalPages}
                                </span>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                                  disabled={currentPage === totalPages}
                                  className="h-7 w-7 p-0"
                                >
                                  <ChevronRight className="h-3 w-3" />
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => setCurrentPage(totalPages)}
                                  disabled={currentPage === totalPages}
                                  className="h-7 w-7 p-0"
                                >
                                  <ChevronsRight className="h-3 w-3" />
                                </Button>
                              </div>
                            </div>
                          )}
                        </>
                      );
                    })()
                  ) : (
                    <div className="text-center py-12 text-muted-foreground">
                      {data.table_rows?.length > 0
                        ? "No memories match your filter"
                        : "No memories found"}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {viewMode === "timeline" &&
            (timelineV2Enabled ? (
              <TimelineGraph
                timeline={timelineData}
                onMemoryClick={(id) => setModalMemoryId(id)}
                onMentalModelClick={(id) => setMentalModelModalId(id)}
              />
            ) : (
              <TimelineView
                filteredRows={filteredTableRows}
                onMemoryClick={(id) => setModalMemoryId(id)}
              />
            ))}
        </>
      ) : (
        <div className="flex items-center justify-center py-20">
          <div className="text-center">
            <div className="text-4xl mb-2">📊</div>
            <div className="text-sm text-muted-foreground">No data available</div>
          </div>
        </div>
      )}

      {/* Memory Detail Modal */}
      <MemoryDetailModal memoryId={modalMemoryId} onClose={() => setModalMemoryId(null)} />
      <MentalModelDetailModal
        mentalModelId={mentalModelModalId}
        onClose={() => setMentalModelModalId(null)}
      />
    </div>
  );
}

// Timeline View Component - Custom compact timeline with zoom and navigation
type Granularity = "year" | "month" | "week" | "day";

function TimelineView({
  filteredRows,
  onMemoryClick,
}: {
  filteredRows: any[];
  onMemoryClick: (id: string) => void;
}) {
  const [granularity, setGranularity] = useState<Granularity>("month");
  const [currentIndex, setCurrentIndex] = useState(0);
  const timelineRef = useRef<HTMLDivElement>(null);

  // Filter and sort items that have occurred_start dates (using filtered data)
  const { sortedItems, itemsWithoutDates } = useMemo(() => {
    if (!filteredRows || filteredRows.length === 0)
      return { sortedItems: [], itemsWithoutDates: [] };

    const withDates = filteredRows
      .filter((row: any) => row.occurred_start)
      .sort((a: any, b: any) => {
        const dateA = new Date(a.occurred_start).getTime();
        const dateB = new Date(b.occurred_start).getTime();
        return dateA - dateB;
      });

    const withoutDates = filteredRows.filter((row: any) => !row.occurred_start);

    return { sortedItems: withDates, itemsWithoutDates: withoutDates };
  }, [filteredRows]);

  // Group items by granularity
  const timelineGroups = useMemo(() => {
    if (sortedItems.length === 0) return [];

    const getGroupKey = (date: Date): string => {
      const year = date.getFullYear();
      const month = date.getMonth();
      const day = date.getDate();

      switch (granularity) {
        case "year":
          return `${year}`;
        case "month":
          return `${year}-${String(month + 1).padStart(2, "0")}`;
        case "week":
          const startOfWeek = new Date(date);
          startOfWeek.setDate(day - date.getDay());
          return `${startOfWeek.getFullYear()}-W${String(Math.ceil(startOfWeek.getDate() / 7)).padStart(2, "0")}-${String(startOfWeek.getMonth() + 1).padStart(2, "0")}-${String(startOfWeek.getDate()).padStart(2, "0")}`;
        case "day":
          return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      }
    };

    const getGroupLabel = (key: string, date: Date): string => {
      switch (granularity) {
        case "year":
          return key;
        case "month":
          return date.toLocaleDateString("en-US", { year: "numeric", month: "short" });
        case "week":
          const endOfWeek = new Date(date);
          endOfWeek.setDate(date.getDate() + 6);
          return `${date.toLocaleDateString("en-US", { month: "short", day: "numeric" })} - ${endOfWeek.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`;
        case "day":
          return date.toLocaleDateString("en-US", {
            weekday: "short",
            month: "short",
            day: "numeric",
            year: "numeric",
          });
      }
    };

    const groups: { [key: string]: { items: any[]; date: Date } } = {};
    sortedItems.forEach((row: any) => {
      const date = new Date(row.occurred_start);
      const key = getGroupKey(date);
      if (!groups[key]) {
        // For week, parse the start date from key
        let groupDate = date;
        if (granularity === "week") {
          const parts = key.split("-");
          groupDate = new Date(parseInt(parts[0]), parseInt(parts[2]) - 1, parseInt(parts[3]));
        }
        groups[key] = { items: [], date: groupDate };
      }
      groups[key].items.push(row);
    });

    return Object.entries(groups)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, { items, date }]) => ({
        key,
        label: getGroupLabel(key, date),
        items,
        date,
      }));
  }, [sortedItems, granularity]);

  // Get date range info
  const dateRange = useMemo(() => {
    if (sortedItems.length === 0) return null;
    const first = new Date(sortedItems[0].occurred_start);
    const last = new Date(sortedItems[sortedItems.length - 1].occurred_start);
    return { first, last };
  }, [sortedItems]);

  // Navigation
  const scrollToGroup = (index: number) => {
    const clampedIndex = Math.max(0, Math.min(index, timelineGroups.length - 1));
    setCurrentIndex(clampedIndex);
    const element = document.getElementById(`timeline-group-${clampedIndex}`);
    element?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const zoomIn = () => {
    const levels: Granularity[] = ["year", "month", "week", "day"];
    const currentIdx = levels.indexOf(granularity);
    if (currentIdx < levels.length - 1) {
      setGranularity(levels[currentIdx + 1]);
    }
  };

  const zoomOut = () => {
    const levels: Granularity[] = ["year", "month", "week", "day"];
    const currentIdx = levels.indexOf(granularity);
    if (currentIdx > 0) {
      setGranularity(levels[currentIdx - 1]);
    }
  };

  if (sortedItems.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12">
        <Calendar className="w-12 h-12 text-muted-foreground mb-3" />
        <div className="text-base font-medium text-foreground mb-1">No Timeline Data</div>
        <div className="text-xs text-muted-foreground text-center max-w-md">
          No memories have occurred_at dates.
          {itemsWithoutDates.length > 0 && (
            <span className="block mt-1">
              {itemsWithoutDates.length} memories without dates in Table View.
            </span>
          )}
        </div>
      </div>
    );
  }

  const formatDateTime = (dateStr: string) => {
    const date = new Date(dateStr);
    const dateFormatted = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    const timeFormatted = date.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    return { date: dateFormatted, time: timeFormatted };
  };

  const granularityLabels: Record<Granularity, string> = {
    year: "Year",
    month: "Month",
    week: "Week",
    day: "Day",
  };

  return (
    <div className="px-4">
      {/* Timeline */}
      <div>
        {/* Controls */}
        <div className="flex items-center justify-between mb-3 gap-4">
          <div className="text-xs text-muted-foreground">
            {sortedItems.length} memories
            {itemsWithoutDates.length > 0 && ` · ${itemsWithoutDates.length} without dates`}
            {dateRange && (
              <span className="ml-2 text-foreground">
                ({dateRange.first.toLocaleDateString("en-US", { month: "short", year: "numeric" })}{" "}
                → {dateRange.last.toLocaleDateString("en-US", { month: "short", year: "numeric" })})
              </span>
            )}
          </div>

          <div className="flex items-center gap-1">
            {/* Zoom controls */}
            <div className="flex items-center border border-border rounded mr-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={zoomOut}
                disabled={granularity === "year"}
                className="h-7 w-7 p-0"
                title="Zoom out"
              >
                <ZoomOut className="h-3 w-3" />
              </Button>
              <span className="text-[10px] px-2 min-w-[50px] text-center border-x border-border text-foreground">
                {granularityLabels[granularity]}
              </span>
              <Button
                variant="secondary"
                size="sm"
                onClick={zoomIn}
                disabled={granularity === "day"}
                className="h-7 w-7 p-0"
                title="Zoom in"
              >
                <ZoomIn className="h-3 w-3" />
              </Button>
            </div>

            {/* Navigation controls */}
            <div className="flex items-center border border-border rounded">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => scrollToGroup(0)}
                disabled={timelineGroups.length <= 1}
                className="h-7 w-7 p-0"
                title="First"
              >
                <ChevronsLeft className="h-3 w-3" />
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => scrollToGroup(currentIndex - 1)}
                disabled={currentIndex === 0}
                className="h-7 w-7 p-0"
                title="Previous"
              >
                <ChevronLeft className="h-3 w-3" />
              </Button>
              <span className="text-[10px] px-2 min-w-[60px] text-center border-x border-border text-foreground">
                {currentIndex + 1} / {timelineGroups.length}
              </span>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => scrollToGroup(currentIndex + 1)}
                disabled={currentIndex >= timelineGroups.length - 1}
                className="h-7 w-7 p-0"
                title="Next"
              >
                <ChevronRight className="h-3 w-3" />
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => scrollToGroup(timelineGroups.length - 1)}
                disabled={timelineGroups.length <= 1}
                className="h-7 w-7 p-0"
                title="Last"
              >
                <ChevronsRight className="h-3 w-3" />
              </Button>
            </div>
          </div>
        </div>

        <div ref={timelineRef} className="relative max-h-[550px] overflow-y-auto pr-2">
          {/* Vertical line */}
          <div className="absolute left-[60px] top-0 bottom-0 w-0.5 bg-border" />

          {timelineGroups.map((group, groupIdx) => (
            <div key={group.key} id={`timeline-group-${groupIdx}`} className="mb-4">
              {/* Group header */}
              <div
                className="flex items-center mb-2 cursor-pointer hover:opacity-80"
                onClick={() => setCurrentIndex(groupIdx)}
              >
                <div className="w-[60px] text-right pr-3">
                  <span className="text-xs font-semibold text-primary">{group.label}</span>
                </div>
                <div className="w-2 h-2 rounded-full bg-primary z-10" />
                <span className="ml-2 text-[10px] text-muted-foreground">
                  {group.items.length} {group.items.length === 1 ? "item" : "items"}
                </span>
              </div>

              {/* Items in this month */}
              <div className="space-y-1">
                {group.items.map((item: any, idx: number) => (
                  <div
                    key={item.id || idx}
                    onClick={() => onMemoryClick(item.id)}
                    className={`flex items-start cursor-pointer group ${"hover:opacity-80"}`}
                  >
                    {/* Date & Time */}
                    <div className="w-[60px] text-right pr-3 pt-1 flex-shrink-0">
                      <div className="text-[10px] text-muted-foreground">
                        {formatDateTime(item.occurred_start).date}
                      </div>
                      <div className="text-[9px] text-muted-foreground/70">
                        {formatDateTime(item.occurred_start).time}
                      </div>
                    </div>

                    {/* Connector dot */}
                    <div className="flex-shrink-0 pt-2">
                      <div
                        className={`w-1.5 h-1.5 rounded-full z-10 ${"bg-muted-foreground/50 group-hover:bg-primary"}`}
                      />
                    </div>

                    {/* Card */}
                    <div
                      className={`ml-3 flex-1 p-2 rounded border transition-colors ${"bg-card border-border hover:border-primary/50"}`}
                    >
                      <p className="text-xs text-foreground line-clamp-2 leading-relaxed">
                        {item.text}
                      </p>
                      {item.context && (
                        <p className="text-[10px] text-muted-foreground mt-1 truncate">
                          {item.context}
                        </p>
                      )}
                      {item.entities && (
                        <div className="flex gap-1 mt-1 flex-wrap">
                          {item.entities
                            .split(", ")
                            .slice(0, 3)
                            .map((entity: string, i: number) => (
                              <span
                                key={i}
                                className="text-[9px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-medium"
                              >
                                {entity}
                              </span>
                            ))}
                          {item.entities.split(", ").length > 3 && (
                            <span className="text-[9px] text-muted-foreground">
                              +{item.entities.split(", ").length - 3}
                            </span>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
