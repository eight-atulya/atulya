"use client";

import {
  Background,
  BaseEdge,
  Controls,
  Edge,
  EdgeLabelRenderer,
  EdgeProps,
  Handle,
  MarkerType,
  Node,
  NodeChange,
  NodeProps,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  XYPosition,
  applyNodeChanges,
  getSmoothStepPath,
  useReactFlow,
} from "@xyflow/react";
import { Expand, Minimize2, Radar } from "lucide-react";
import {
  Dispatch,
  Fragment,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  SetStateAction,
  type TouchEvent as ReactTouchEvent,
  memo,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  GraphHandleSide,
  GraphLayoutMode,
  GraphSourceHandleId,
  GraphTargetHandleId,
  WorkbenchSurfaceMode,
  layoutGraph,
  toSourceHandleId,
  toTargetHandleId,
} from "../layout/graph-layout";

export type WorkbenchNodeKind = "state" | "event" | "evidence";
export type WorkbenchRenderMode = "overview" | "compact" | "detail";

export interface WorkbenchOverviewNode {
  id: string;
  kind: "cluster" | "node";
  title: string;
  subtitle?: string | null;
  previewLabels?: string[];
  memberCount?: number;
  statusTone?: "stable" | "changed" | "contradictory" | "stale" | "neutral";
  displayPriority: number;
}

export interface WorkbenchOverviewEdge {
  id: string;
  source_id: string;
  target_id: string;
  weight: number;
  label?: string | null;
}

export interface WorkbenchGraphNode {
  id: string;
  kind: WorkbenchNodeKind;
  title: string;
  subtitle?: string | null;
  preview?: string | null;
  statusLabel?: string | null;
  statusTone?: "stable" | "changed" | "contradictory" | "stale" | "neutral";
  confidence?: number | null;
  signalScore?: number | null;
  evidenceCount?: number | null;
  kindLabel?: string | null;
  meta?: string | null;
  timestampLabel?: string | null;
  reason?: string | null;
  accentColor?: string | null;
  width: number;
  height: number;
  priority: number;
}

export interface WorkbenchGraphEdge {
  id: string;
  source: string;
  target: string;
  kind?: "relation" | "event" | "evidence";
  label?: string | null;
  stroke?: string | null;
  dashed?: boolean;
  width?: number;
  animated?: boolean;
  priority?: number;
}

interface WorkbenchGraphProps {
  surfaceMode: WorkbenchSurfaceMode;
  badgeLabel: string;
  renderMode?: WorkbenchRenderMode;
  nodes: WorkbenchGraphNode[];
  edges: WorkbenchGraphEdge[];
  overviewNodes?: WorkbenchOverviewNode[];
  overviewEdges?: WorkbenchOverviewEdge[];
  selectedIds?: string[];
  highlightedNodeIds?: string[];
  highlightedEdgeIds?: string[];
  storageKey?: string;
  resetLayoutVersion?: number;
  height?: number;
  layoutMode?: GraphLayoutMode;
  fullscreenAccessory?: ReactNode;
  onNodeSelect?: (nodeId: string) => void;
  onNodeContextMenu?: (nodeId: string, position: { x: number; y: number }) => void;
  onNodeHover?: (nodeId: string | null) => void;
  onBackgroundClick?: () => void;
}

interface GraphWorkbenchInnerProps extends WorkbenchGraphProps {
  isFullscreen: boolean;
  setIsFullscreen: Dispatch<SetStateAction<boolean>>;
}

type MeasuredNodeSize = {
  width: number;
  height: number;
};

type WorkbenchNodeData = {
  payload: WorkbenchGraphNode;
  renderMode: WorkbenchRenderMode;
  selected: boolean;
  muted: boolean;
  emphasized: boolean;
  onMeasured?: (nodeId: string, size: MeasuredNodeSize) => void;
};

type WorkbenchEdgeData = {
  payload: WorkbenchGraphEdge;
  highlighted: boolean;
  muted: boolean;
  stroke: string;
};

const STORAGE_VERSION = "v1";
const DEFAULT_HEIGHT = 700;
const HANDLE_STYLE = {
  width: 10,
  height: 10,
  border: "none",
  background: "transparent",
  opacity: 0,
  pointerEvents: "none" as const,
};

const STATUS_THEME = {
  stable: {
    border: "border-blue-300/90",
    accent: "bg-blue-500",
    chip: "bg-blue-50 text-blue-700 border-blue-200",
    glow: "shadow-[0_18px_45px_-28px_rgba(37,99,235,0.45)]",
  },
  changed: {
    border: "border-orange-300/90",
    accent: "bg-orange-500",
    chip: "bg-orange-50 text-orange-700 border-orange-200",
    glow: "shadow-[0_18px_45px_-28px_rgba(249,115,22,0.45)]",
  },
  contradictory: {
    border: "border-rose-400/90",
    accent: "bg-rose-700",
    chip: "bg-rose-50 text-rose-800 border-rose-200",
    glow: "shadow-[0_20px_50px_-30px_rgba(190,24,93,0.55)]",
  },
  stale: {
    border: "border-amber-300/90",
    accent: "bg-amber-500",
    chip: "bg-amber-50 text-amber-700 border-amber-200",
    glow: "shadow-[0_18px_45px_-28px_rgba(245,158,11,0.5)]",
  },
  neutral: {
    border: "border-slate-300/90",
    accent: "bg-slate-500",
    chip: "bg-slate-100 text-slate-700 border-slate-200",
    glow: "shadow-[0_18px_45px_-30px_rgba(15,23,42,0.15)]",
  },
} as const;

const PANEL_STYLE = {
  backgroundColor: "var(--graph-panel-bg)",
  borderColor: "var(--graph-panel-border)",
  color: "var(--graph-panel-foreground)",
} as const;

const CHIP_STYLE = {
  backgroundColor: "var(--graph-chip-bg)",
  borderColor: "var(--graph-chip-border)",
  color: "var(--graph-chip-foreground)",
} as const;

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function truncate(value: string | null | undefined, max: number, fallback = "") {
  const normalized = typeof value === "string" && value.trim().length > 0 ? value.trim() : fallback;
  return normalized.length <= max ? normalized : `${normalized.slice(0, max - 1)}…`;
}

function formatPercent(value: number | null | undefined) {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  return `${Math.round(value * 100)}%`;
}

function formatMetric(label: string, value: number | null | undefined) {
  const formatted = formatPercent(value);
  if (!formatted) return null;
  return `${label} ${formatted}`;
}

const ALL_HANDLE_SIDES: GraphHandleSide[] = ["left", "right", "top", "bottom"];
const VALID_SOURCE_HANDLES = new Set<GraphSourceHandleId>(
  ALL_HANDLE_SIDES.map((side) => toSourceHandleId(side))
);
const VALID_TARGET_HANDLES = new Set<GraphTargetHandleId>(
  ALL_HANDLE_SIDES.map((side) => toTargetHandleId(side))
);

function resolveSourceHandleId(handleId?: string | null): GraphSourceHandleId {
  return handleId && VALID_SOURCE_HANDLES.has(handleId as GraphSourceHandleId)
    ? (handleId as GraphSourceHandleId)
    : toSourceHandleId("right");
}

function resolveTargetHandleId(handleId?: string | null): GraphTargetHandleId {
  return handleId && VALID_TARGET_HANDLES.has(handleId as GraphTargetHandleId)
    ? (handleId as GraphTargetHandleId)
    : toTargetHandleId("left");
}

function CardHandles() {
  return (
    <>
      {ALL_HANDLE_SIDES.map((side) => {
        const position =
          side === "left"
            ? Position.Left
            : side === "right"
              ? Position.Right
              : side === "top"
                ? Position.Top
                : Position.Bottom;

        return (
          <Fragment key={side}>
            <Handle
              id={toTargetHandleId(side)}
              type="target"
              position={position}
              style={HANDLE_STYLE}
            />
            <Handle
              id={toSourceHandleId(side)}
              type="source"
              position={position}
              style={HANDLE_STYLE}
            />
          </Fragment>
        );
      })}
    </>
  );
}

function NodeFrame({ data, children }: { data: WorkbenchNodeData; children: ReactNode }) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const tone = STATUS_THEME[data.payload.statusTone ?? "neutral"];
  const selectedClass = data.selected
    ? "ring-2 ring-primary/25 shadow-xl scale-[1.01]"
    : "shadow-md";
  const mutedClass = data.muted ? "opacity-35" : "opacity-100";
  const emphasizedClass = data.emphasized && !data.selected ? tone.glow : "";
  const compact = data.renderMode === "compact";
  const accentStyle = data.payload.accentColor
    ? { backgroundColor: data.payload.accentColor }
    : undefined;

  useLayoutEffect(() => {
    const element = frameRef.current;
    if (!element || !data.onMeasured) return;

    const emitMeasurement = () => {
      const rect = element.getBoundingClientRect();
      data.onMeasured?.(data.payload.id, {
        width: Math.ceil(rect.width),
        height: Math.ceil(rect.height),
      });
    };

    emitMeasurement();
    const observer = new ResizeObserver(() => emitMeasurement());
    observer.observe(element);

    return () => observer.disconnect();
  }, [data]);

  return (
    <div
      ref={frameRef}
      className={[
        "relative overflow-hidden rounded-[16px] border bg-card/95 text-card-foreground backdrop-blur-sm transition-[transform,opacity,box-shadow,border-color] duration-200",
        "hover:-translate-y-0.5 hover:shadow-lg",
        compact ? "rounded-[14px]" : "",
        tone.border,
        selectedClass,
        emphasizedClass,
        mutedClass,
      ].join(" ")}
      style={{
        width: data.payload.width,
        minHeight: data.payload.height,
      }}
    >
      <CardHandles />
      <div
        className={`absolute left-4 right-4 top-0 h-[3px] rounded-b-full opacity-80 ${tone.accent}`}
        style={accentStyle}
      />
      {children}
    </div>
  );
}

const StateNodeCard = memo(function StateNodeCard({ data }: NodeProps<Node<WorkbenchNodeData>>) {
  const compact = data.renderMode === "compact";
  return (
    <NodeFrame data={data}>
      <div className={compact ? "p-3 space-y-2.5" : "p-4 space-y-3"}>
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground font-semibold">
              {data.payload.kindLabel || "State"}
            </div>
            <div
              className={
                compact
                  ? "mt-1 text-lg leading-tight font-semibold text-foreground break-words"
                  : "mt-1 text-xl leading-tight font-semibold text-foreground break-words"
              }
            >
              {truncate(data.payload.title, compact ? 48 : 72, "Untitled state")}
            </div>
            {data.payload.subtitle ? (
              <div className="mt-1 text-sm text-muted-foreground leading-snug">
                {truncate(data.payload.subtitle, compact ? 78 : 120)}
              </div>
            ) : null}
          </div>
          {data.payload.statusLabel ? (
            <div
              className={[
                "shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-semibold tracking-[0.08em] uppercase",
                STATUS_THEME[data.payload.statusTone ?? "neutral"].chip,
              ].join(" ")}
            >
              {data.payload.statusLabel}
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {formatMetric("Support", data.payload.confidence) ? (
            <span className="rounded-full bg-foreground px-2.5 py-1 font-semibold text-background">
              {formatMetric("Support", data.payload.confidence)}
            </span>
          ) : null}
          {formatMetric("Signal", data.payload.signalScore) ? (
            <span className="rounded-full border px-2.5 py-1 font-semibold" style={CHIP_STYLE}>
              {formatMetric("Signal", data.payload.signalScore)}
            </span>
          ) : null}
          {typeof data.payload.evidenceCount === "number" ? (
            <span className="rounded-full border px-2.5 py-1 font-medium" style={CHIP_STYLE}>
              {data.payload.evidenceCount} evidence
            </span>
          ) : null}
          {data.payload.meta ? (
            <span className="rounded-full border px-2.5 py-1 font-medium" style={CHIP_STYLE}>
              {truncate(data.payload.meta, 30)}
            </span>
          ) : null}
        </div>

        {data.payload.preview ? (
          <div className="rounded-xl border border-border bg-muted/50 p-3.5">
            <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground font-semibold">
              Supported State
            </div>
            <div
              className={
                compact
                  ? "mt-2 text-[13px] leading-6 text-foreground break-words"
                  : "mt-2 text-[15px] leading-7 text-foreground break-words"
              }
            >
              {truncate(data.payload.preview, compact ? 110 : 180, "No state summary available.")}
            </div>
          </div>
        ) : null}

        {(data.payload.reason || data.payload.timestampLabel) && (
          <div className="space-y-1 text-xs leading-5 text-muted-foreground">
            {data.payload.reason ? (
              <div className="min-w-0 break-words">{truncate(data.payload.reason, 140)}</div>
            ) : null}
            {data.payload.timestampLabel ? <div>{data.payload.timestampLabel}</div> : null}
          </div>
        )}
      </div>
    </NodeFrame>
  );
});

const EventNodeCard = memo(function EventNodeCard({ data }: NodeProps<Node<WorkbenchNodeData>>) {
  const compact = data.renderMode === "compact";
  return (
    <NodeFrame data={data}>
      <div className={compact ? "p-3 space-y-2.5" : "p-4 space-y-3"}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="text-[11px] uppercase tracking-[0.14em] text-muted-foreground font-semibold">
              Signal
            </div>
            <div
              className={
                compact
                  ? "mt-1 text-base leading-tight font-semibold text-foreground"
                  : "mt-1 text-lg leading-tight font-semibold text-foreground"
              }
            >
              {truncate(data.payload.title, compact ? 34 : 52)}
            </div>
          </div>
          {formatMetric("Signal", data.payload.signalScore ?? data.payload.confidence) ? (
            <span className="text-sm font-semibold text-foreground/80">
              {formatMetric("Signal", data.payload.signalScore ?? data.payload.confidence)}
            </span>
          ) : null}
        </div>
        <div
          className={
            compact
              ? "text-[13px] leading-5 text-foreground/80 break-words"
              : "text-sm leading-6 text-foreground/80 break-words"
          }
        >
          {truncate(data.payload.preview, compact ? 120 : 220, "Atulya surfaced a graph signal.")}
        </div>
        {data.payload.timestampLabel ? (
          <div className="text-xs text-muted-foreground">{data.payload.timestampLabel}</div>
        ) : null}
      </div>
    </NodeFrame>
  );
});

const EvidenceNodeCard = memo(function EvidenceNodeCard({
  data,
}: NodeProps<Node<WorkbenchNodeData>>) {
  const compact = data.renderMode === "compact";
  return (
    <NodeFrame data={data}>
      <div className={compact ? "p-3 space-y-2.5" : "p-4 space-y-3"}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div
              className={
                compact
                  ? "text-base leading-tight font-semibold text-foreground break-words"
                  : "text-lg leading-tight font-semibold text-foreground break-words"
              }
            >
              {truncate(data.payload.title, compact ? 54 : 76, "Evidence")}
            </div>
            {data.payload.meta ? (
              <div className="mt-1 text-sm text-muted-foreground">
                {truncate(data.payload.meta, compact ? 48 : 82)}
              </div>
            ) : null}
          </div>
          {formatPercent(data.payload.confidence) ? (
            <span
              className="rounded-full border px-2 py-1 text-xs font-semibold"
              style={CHIP_STYLE}
            >
              {formatMetric("Support", data.payload.confidence) ??
                formatPercent(data.payload.confidence)}
            </span>
          ) : null}
        </div>
        {data.payload.preview ? (
          <div
            className={
              compact
                ? "text-[13px] leading-5 text-foreground/80 break-words"
                : "text-sm leading-6 text-foreground/80 break-words"
            }
          >
            {truncate(data.payload.preview, compact ? 90 : 150)}
          </div>
        ) : null}
        {data.payload.reason ? (
          <div className="text-xs text-muted-foreground">{truncate(data.payload.reason, 90)}</div>
        ) : null}
      </div>
    </NodeFrame>
  );
});

const DEFAULT_NODE_TYPES = Object.freeze({
  state: StateNodeCard,
  event: EventNodeCard,
  evidence: EvidenceNodeCard,
});

const AnimatedGraphEdge = memo(function AnimatedGraphEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  data,
}: EdgeProps<Edge<WorkbenchEdgeData>>) {
  const [path, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 22,
    offset: 24,
  });
  const edgeData = data as WorkbenchEdgeData | undefined;
  const stroke = edgeData?.stroke ?? "var(--graph-edge-neutral)";
  const isHighlighted = Boolean(edgeData?.highlighted);
  const isMuted = Boolean(edgeData?.muted);
  const payload = edgeData?.payload;
  const width = clamp(payload?.width ?? (isHighlighted ? 2.5 : 1.65), 1.25, 3.5);
  const opacity = isMuted ? 0.14 : isHighlighted ? 0.88 : 0.42;

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke,
          strokeWidth: width,
          opacity,
          strokeDasharray: payload?.dashed ? "7 6" : undefined,
        }}
      />
      <path
        d={path}
        fill="none"
        className={payload?.animated === false ? undefined : "atulya-flow-edge"}
        style={{
          stroke,
          strokeWidth: Math.max(1.2, width - 0.35),
          opacity: isMuted ? 0.08 : isHighlighted ? 0.74 : 0.32,
          strokeDasharray: payload?.dashed ? "8 10" : "9 11",
        }}
      />
      {payload?.label ? (
        <EdgeLabelRenderer>
          <div
            className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] shadow-sm"
            style={{
              ...PANEL_STYLE,
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            }}
          >
            {truncate(payload.label, 24)}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
});

const DEFAULT_EDGE_TYPES = Object.freeze({
  animated: AnimatedGraphEdge,
});

function computeOverviewLayout(items: WorkbenchOverviewNode[]) {
  const cardWidth = 292;
  const clusterHeight = 122;
  const nodeHeight = 132;
  const gap = 28;
  const columns = Math.max(2, Math.min(4, Math.ceil(Math.sqrt(Math.max(items.length, 1)))));
  const sorted = items
    .slice()
    .sort(
      (left, right) =>
        right.displayPriority - left.displayPriority || left.title.localeCompare(right.title)
    );

  return Object.fromEntries(
    sorted.map((item, index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);
      return [
        item.id,
        {
          x: 72 + column * (cardWidth + gap),
          y: 72 + row * ((item.kind === "cluster" ? clusterHeight : nodeHeight) + gap),
          width: cardWidth,
          height: item.kind === "cluster" ? clusterHeight : nodeHeight,
        },
      ];
    })
  );
}

function OverviewCanvas({
  nodes,
  edges,
  selectedIds,
  highlightedNodeIds,
  onSelect,
  onContextMenu,
  onBackgroundClick,
  onZoomChange,
  fitVersion,
}: {
  nodes: WorkbenchOverviewNode[];
  edges: WorkbenchOverviewEdge[];
  selectedIds: string[];
  highlightedNodeIds: string[];
  onSelect?: (nodeId: string) => void;
  onContextMenu?: (nodeId: string, position: { x: number; y: number }) => void;
  onBackgroundClick?: () => void;
  onZoomChange?: (zoom: number) => void;
  fitVersion: number;
}) {
  const [viewport, setViewport] = useState({ x: 0, y: 0, scale: 1 });
  const panState = useRef<{ x: number; y: number; startX: number; startY: number } | null>(null);
  const layout = useMemo(() => computeOverviewLayout(nodes), [nodes]);
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const highlightedSet = useMemo(() => new Set(highlightedNodeIds), [highlightedNodeIds]);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setViewport({ x: 0, y: 0, scale: 1 });
  }, [fitVersion, nodes]);

  useEffect(() => {
    onZoomChange?.(Math.round(viewport.scale * 100));
  }, [onZoomChange, viewport.scale]);

  const edgePaths = useMemo(() => {
    return edges
      .map((edge) => {
        const source = layout[edge.source_id];
        const target = layout[edge.target_id];
        if (!source || !target) {
          return null;
        }
        const sourceX = source.x + source.width / 2;
        const sourceY = source.y + source.height / 2;
        const targetX = target.x + target.width / 2;
        const targetY = target.y + target.height / 2;
        const midX = sourceX + (targetX - sourceX) / 2;
        return {
          ...edge,
          path: `M ${sourceX} ${sourceY} C ${midX} ${sourceY}, ${midX} ${targetY}, ${targetX} ${targetY}`,
        };
      })
      .filter(Boolean) as Array<WorkbenchOverviewEdge & { path: string }>;
  }, [edges, layout]);

  const handleWheel = useCallback((event: React.WheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    setViewport((current) => ({
      ...current,
      scale: clamp(current.scale + (event.deltaY > 0 ? -0.08 : 0.08), 0.65, 1.4),
    }));
  }, []);

  return (
    <div
      ref={containerRef}
      className="graph-overview-surface relative h-full w-full overflow-hidden"
      onWheel={handleWheel}
      onMouseDown={(event) => {
        if ((event.target as HTMLElement).closest("button")) return;
        panState.current = {
          x: viewport.x,
          y: viewport.y,
          startX: event.clientX,
          startY: event.clientY,
        };
      }}
      onMouseMove={(event) => {
        if (!panState.current) return;
        setViewport((current) => ({
          ...current,
          x: panState.current!.x + (event.clientX - panState.current!.startX),
          y: panState.current!.y + (event.clientY - panState.current!.startY),
        }));
      }}
      onMouseUp={() => {
        panState.current = null;
      }}
      onMouseLeave={() => {
        panState.current = null;
      }}
      onClick={(event) => {
        if (!(event.target as HTMLElement).closest("button")) {
          onBackgroundClick?.();
        }
      }}
    >
      <svg className="absolute inset-0 h-full w-full pointer-events-none">
        <g transform={`translate(${viewport.x} ${viewport.y}) scale(${viewport.scale})`}>
          {edgePaths.map((edge) => {
            const active =
              selectedSet.has(edge.source_id) ||
              selectedSet.has(edge.target_id) ||
              highlightedSet.has(edge.source_id) ||
              highlightedSet.has(edge.target_id);
            return (
              <path
                key={edge.id}
                d={edge.path}
                fill="none"
                stroke={active ? "rgba(220,38,38,0.72)" : "rgba(100,116,139,0.32)"}
                strokeWidth={Math.max(1.2, edge.weight)}
                strokeLinecap="round"
              />
            );
          })}
        </g>
      </svg>
      <div
        className="absolute inset-0"
        style={{
          transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.scale})`,
          transformOrigin: "0 0",
        }}
      >
        {nodes.map((node) => {
          const box = layout[node.id];
          if (!box) return null;
          const selected = selectedSet.has(node.id);
          const highlighted = highlightedSet.has(node.id);
          const tone = STATUS_THEME[node.statusTone ?? "neutral"];
          return (
            <button
              key={node.id}
              onClick={(event) => {
                event.stopPropagation();
                onSelect?.(node.id);
              }}
              onContextMenu={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onContextMenu?.(node.id, { x: event.clientX, y: event.clientY });
              }}
              className={[
                "absolute rounded-[14px] border bg-card/95 p-4 text-left text-card-foreground shadow-sm transition-[transform,box-shadow,opacity,border-color] duration-150 hover:-translate-y-0.5 hover:shadow-lg",
                tone.border,
                selected ? "ring-2 ring-primary/20 shadow-xl" : highlighted ? tone.glow : "",
                selectedSet.size > 0 && !selected && !highlighted ? "opacity-45" : "opacity-100",
              ].join(" ")}
              style={{
                left: box.x,
                top: box.y,
                width: box.width,
                minHeight: box.height,
                borderColor: selected ? "rgba(220,38,38,0.45)" : undefined,
              }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                    {node.kind === "cluster" ? "Cluster" : "Top Node"}
                  </div>
                  <div className="mt-1 text-lg font-semibold leading-tight text-foreground break-words">
                    {truncate(node.title, 56)}
                  </div>
                  {node.subtitle ? (
                    <div className="mt-1 text-sm text-muted-foreground">
                      {truncate(node.subtitle, 72)}
                    </div>
                  ) : null}
                </div>
                <div
                  className={[
                    "rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.08em]",
                    tone.chip,
                  ].join(" ")}
                >
                  {node.memberCount || 1}
                </div>
              </div>
              {node.previewLabels?.length ? (
                <div className="mt-3 text-sm leading-6 text-foreground/80">
                  {truncate(
                    node.previewLabels.slice(0, 2).join(" • "),
                    node.kind === "cluster" ? 92 : 120
                  )}
                </div>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function buildEdgeColor(surfaceMode: WorkbenchSurfaceMode, edge: WorkbenchGraphEdge) {
  if (edge.stroke) return edge.stroke;
  if (surfaceMode === "state") {
    if (edge.kind === "event") return "#f97316";
    return "var(--graph-edge-neutral)";
  }

  switch (edge.label) {
    case "temporal":
      return "#2563eb";
    case "entity":
      return "#7c3aed";
    case "causal":
      return "#dc2626";
    case "causes":
      return "#8b5cf6";
    case "caused_by":
      return "#6366f1";
    case "enables":
      return "#059669";
    case "prevents":
      return "#dc2626";
    default:
      return "var(--graph-edge-neutral)";
  }
}

function useLocalStorageState<T>(key: string | null, fallback: T) {
  const fallbackRef = useRef(fallback);
  fallbackRef.current = fallback;
  const [value, setValue] = useState<T>(fallback);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (!key || typeof window === "undefined") {
      setValue(fallbackRef.current);
      setHydrated(true);
      return;
    }

    try {
      const raw = window.localStorage.getItem(key);
      setValue(raw ? (JSON.parse(raw) as T) : fallbackRef.current);
    } catch {
      setValue(fallbackRef.current);
    } finally {
      setHydrated(true);
    }
  }, [key]);

  const update = useCallback(
    (next: T | ((current: T) => T)) => {
      setValue((current) => {
        const resolved = typeof next === "function" ? (next as (current: T) => T)(current) : next;
        if (key && typeof window !== "undefined") {
          window.localStorage.setItem(key, JSON.stringify(resolved));
        }
        return resolved;
      });
    },
    [key]
  );

  return { value, setValue: update, hydrated };
}

function GraphWorkbenchInner({
  surfaceMode,
  badgeLabel,
  renderMode = "detail",
  nodes,
  edges,
  overviewNodes = [],
  overviewEdges = [],
  selectedIds = [],
  highlightedNodeIds = [],
  highlightedEdgeIds = [],
  storageKey,
  resetLayoutVersion = 0,
  height = DEFAULT_HEIGHT,
  layoutMode = "signal-first",
  fullscreenAccessory,
  onNodeSelect,
  onNodeContextMenu,
  onNodeHover,
  onBackgroundClick,
  isFullscreen,
  setIsFullscreen,
}: GraphWorkbenchInnerProps) {
  const pinsKey = storageKey ? `${storageKey}:${surfaceMode}:pins:${STORAGE_VERSION}` : null;
  const inlineViewportKey = storageKey
    ? `${storageKey}:${surfaceMode}:viewport:inline:${STORAGE_VERSION}`
    : null;
  const fullscreenViewportKey = storageKey
    ? `${storageKey}:${surfaceMode}:viewport:fullscreen:${STORAGE_VERSION}`
    : null;
  const reactFlow = useReactFlow<Node<WorkbenchNodeData>, Edge<WorkbenchEdgeData>>();
  const initializedViewportRef = useRef(false);
  const lastResetVersionRef = useRef(resetLayoutVersion);
  const lastFocusedSelectionRef = useRef("");
  const nodeTypesRef = useRef(DEFAULT_NODE_TYPES);
  const edgeTypesRef = useRef(DEFAULT_EDGE_TYPES);
  const measurementFrameRef = useRef<number | null>(null);
  const pendingMeasurementsRef = useRef<Record<string, MeasuredNodeSize>>({});
  const selectedSet = useMemo(() => new Set(selectedIds.filter(Boolean)), [selectedIds]);
  const highlightedNodeSet = useMemo(() => new Set(highlightedNodeIds), [highlightedNodeIds]);
  const highlightedEdgeSet = useMemo(() => new Set(highlightedEdgeIds), [highlightedEdgeIds]);
  const selectedKey = useMemo(() => selectedIds.filter(Boolean).join("|"), [selectedIds]);
  const highlightedNodeKey = useMemo(() => highlightedNodeIds.join("|"), [highlightedNodeIds]);
  const highlightedEdgeKey = useMemo(() => highlightedEdgeIds.join("|"), [highlightedEdgeIds]);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [zoomLabel, setZoomLabel] = useState(100);
  const [measuredNodeSizes, setMeasuredNodeSizes] = useState<Record<string, MeasuredNodeSize>>({});
  const [layoutSettled, setLayoutSettled] = useState(false);
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });
  const emptyPinsFallback = useMemo(() => ({}), []);
  const emptyViewportFallback = useMemo(() => ({ x: 0, y: 0, zoom: 1 }), []);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const {
    value: pinnedNodes,
    setValue: setPinnedNodes,
    hydrated: pinsHydrated,
  } = useLocalStorageState<Record<string, XYPosition>>(pinsKey, emptyPinsFallback);
  const {
    value: inlineViewport,
    setValue: setInlineViewport,
    hydrated: inlineViewportHydrated,
  } = useLocalStorageState<XYPosition & { zoom: number }>(inlineViewportKey, emptyViewportFallback);
  const {
    value: fullscreenViewport,
    setValue: setFullscreenViewport,
    hydrated: fullscreenViewportHydrated,
  } = useLocalStorageState<XYPosition & { zoom: number }>(
    fullscreenViewportKey,
    emptyViewportFallback
  );
  const [flowNodes, setFlowNodes] = useState<Node<WorkbenchNodeData>[]>([]);
  const [flowEdges, setFlowEdges] = useState<Edge<WorkbenchEdgeData>[]>([]);
  const [overviewZoom, setOverviewZoom] = useState(100);
  const [overviewFitVersion, setOverviewFitVersion] = useState(0);
  const savedViewport = isFullscreen ? fullscreenViewport : inlineViewport;
  const setSavedViewport = isFullscreen ? setFullscreenViewport : setInlineViewport;
  const viewportHydrated = isFullscreen ? fullscreenViewportHydrated : inlineViewportHydrated;

  useEffect(() => {
    return () => {
      if (measurementFrameRef.current !== null) {
        window.cancelAnimationFrame(measurementFrameRef.current);
      }
    };
  }, []);

  useLayoutEffect(() => {
    const element = canvasRef.current;
    if (!element) return;

    const updateSize = () => {
      const rect = element.getBoundingClientRect();
      setCanvasSize({
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      });
    };

    updateSize();
    const observer = new ResizeObserver(() => updateSize());
    observer.observe(element);

    return () => observer.disconnect();
  }, [isFullscreen, height, renderMode]);

  const handleNodeMeasured = useCallback((nodeId: string, size: MeasuredNodeSize) => {
    pendingMeasurementsRef.current[nodeId] = size;
    if (measurementFrameRef.current !== null) {
      return;
    }
    measurementFrameRef.current = window.requestAnimationFrame(() => {
      measurementFrameRef.current = null;
      const pending = pendingMeasurementsRef.current;
      pendingMeasurementsRef.current = {};
      setMeasuredNodeSizes((current) => {
        let changed = false;
        const next = { ...current };
        for (const [id, measured] of Object.entries(pending)) {
          const existing = current[id];
          if (
            existing &&
            existing.width === measured.width &&
            existing.height === measured.height
          ) {
            continue;
          }
          next[id] = measured;
          changed = true;
        }
        return changed ? next : current;
      });
    });
  }, []);

  useEffect(() => {
    initializedViewportRef.current = false;
  }, [storageKey, surfaceMode, isFullscreen]);

  useEffect(() => {
    const activeNodeIds = new Set(nodes.map((node) => node.id));
    setMeasuredNodeSizes((current) => {
      const nextEntries = Object.entries(current).filter(([nodeId]) => activeNodeIds.has(nodeId));
      if (nextEntries.length === Object.keys(current).length) {
        return current;
      }
      return Object.fromEntries(nextEntries);
    });
    setLayoutSettled(false);
  }, [nodes]);

  useEffect(() => {
    if (lastResetVersionRef.current === resetLayoutVersion) return;
    lastResetVersionRef.current = resetLayoutVersion;
    if (!storageKey || typeof window === "undefined") return;
    window.localStorage.removeItem(`${storageKey}:${surfaceMode}:pins:${STORAGE_VERSION}`);
    window.localStorage.removeItem(
      `${storageKey}:${surfaceMode}:viewport:inline:${STORAGE_VERSION}`
    );
    window.localStorage.removeItem(
      `${storageKey}:${surfaceMode}:viewport:fullscreen:${STORAGE_VERSION}`
    );
    initializedViewportRef.current = false;
    setPinnedNodes({});
    setInlineViewport({ x: 0, y: 0, zoom: 1 });
    setFullscreenViewport({ x: 0, y: 0, zoom: 1 });
  }, [
    resetLayoutVersion,
    setFullscreenViewport,
    setInlineViewport,
    setPinnedNodes,
    storageKey,
    surfaceMode,
  ]);

  useEffect(() => {
    if (renderMode === "overview") {
      setLayoutSettled(true);
      setFlowNodes([]);
      setFlowEdges([]);
      return;
    }
    if (!pinsHydrated || !viewportHydrated) return;

    let active = true;
    setLayoutSettled(false);

    const timeoutId = window.setTimeout(async () => {
      const layout = await layoutGraph({
        surfaceMode,
        layoutMode,
        nodes: nodes.map((node) => ({
          id: node.id,
          width: measuredNodeSizes[node.id]?.width ?? node.width,
          height: measuredNodeSizes[node.id]?.height ?? node.height,
          priority: node.priority,
          pinnedPosition: pinnedNodes[node.id] ?? null,
        })),
        edges: edges.map((edge) => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
        })),
        focalNodeId: null,
      });

      if (!active) return;

      const nextNodes: Node<WorkbenchNodeData>[] = nodes.map((node) => {
        const position = pinnedNodes[node.id] ?? layout.positions[node.id] ?? { x: 0, y: 0 };

        return {
          id: node.id,
          type: node.kind,
          position,
          draggable: true,
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
          data: {
            payload: node,
            renderMode,
            selected: false,
            muted: false,
            emphasized: false,
            onMeasured: handleNodeMeasured,
          },
          style: {
            width: measuredNodeSizes[node.id]?.width ?? node.width,
          },
        };
      });

      const nextEdges: Edge<WorkbenchEdgeData>[] = edges.map((edge) => {
        const stroke = buildEdgeColor(surfaceMode, edge);
        const handles = layout.handles[edge.id];

        return {
          id: edge.id,
          type: "animated",
          source: edge.source,
          target: edge.target,
          sourceHandle: resolveSourceHandleId(handles?.sourceHandleId),
          targetHandle: resolveTargetHandleId(handles?.targetHandleId),
          markerEnd:
            edge.kind === "event"
              ? undefined
              : {
                  type: MarkerType.ArrowClosed,
                  color: stroke,
                  width: 18,
                  height: 18,
                },
          data: {
            payload: edge,
            highlighted: false,
            muted: false,
            stroke,
          },
        };
      });

      setFlowNodes(nextNodes);
      setFlowEdges(nextEdges);
      setLayoutSettled(true);
    }, 64);

    return () => {
      active = false;
      window.clearTimeout(timeoutId);
    };
  }, [
    edges,
    layoutMode,
    nodes,
    renderMode,
    pinnedNodes,
    pinsHydrated,
    measuredNodeSizes,
    surfaceMode,
    viewportHydrated,
  ]);

  useEffect(() => {
    if (renderMode === "overview") return;
    const activeNodeIds = new Set([
      ...selectedIds,
      ...highlightedNodeIds,
      ...(hoveredNodeId ? [hoveredNodeId] : []),
    ]);

    const connectedActiveNodes = new Set<string>();
    flowEdges.forEach((edge) => {
      if (activeNodeIds.has(edge.source) || activeNodeIds.has(edge.target)) {
        connectedActiveNodes.add(edge.source);
        connectedActiveNodes.add(edge.target);
      }
    });

    setFlowNodes((current) => {
      let changed = false;
      const next = current.map((node) => {
        const selected = selectedSet.has(node.id);
        const emphasized = selected || highlightedNodeSet.has(node.id) || hoveredNodeId === node.id;
        const muted = activeNodeIds.size > 0 && !emphasized;

        if (
          node.data.selected === selected &&
          node.data.emphasized === emphasized &&
          node.data.muted === muted
        ) {
          return node;
        }
        changed = true;

        return {
          ...node,
          data: {
            ...node.data,
            selected,
            emphasized,
            muted,
          },
        };
      });

      return changed ? next : current;
    });

    setFlowEdges((current) => {
      let changed = false;
      const next = current.map((edge) => {
        const highlighted =
          highlightedEdgeSet.has(edge.id) ||
          selectedSet.has(edge.source) ||
          selectedSet.has(edge.target) ||
          hoveredNodeId === edge.source ||
          hoveredNodeId === edge.target;
        const muted =
          activeNodeIds.size > 0 &&
          !highlighted &&
          !(connectedActiveNodes.has(edge.source) && connectedActiveNodes.has(edge.target));

        if (!edge.data) {
          return edge;
        }

        if (edge.data.highlighted === highlighted && edge.data.muted === muted) {
          return edge;
        }
        changed = true;

        return {
          ...edge,
          data: {
            ...edge.data,
            highlighted,
            muted,
          },
        };
      });

      return changed ? next : current;
    });
  }, [
    flowEdges,
    highlightedEdgeKey,
    highlightedEdgeSet,
    highlightedNodeKey,
    highlightedNodeIds,
    highlightedNodeSet,
    hoveredNodeId,
    selectedIds,
    selectedSet,
  ]);

  useEffect(() => {
    if (renderMode === "overview") return;
    if (!flowNodes.length) return;
    if (canvasSize.width <= 0 || canvasSize.height <= 0) return;

    if (!initializedViewportRef.current) {
      initializedViewportRef.current = true;
      requestAnimationFrame(() => {
        if (
          savedViewport &&
          (savedViewport.x !== 0 || savedViewport.y !== 0 || savedViewport.zoom !== 1)
        ) {
          reactFlow.setViewport(savedViewport, { duration: 0 });
        } else {
          reactFlow.fitView({ padding: 0.18, duration: 350, maxZoom: 1.05 });
        }
      });
    }
  }, [canvasSize.height, canvasSize.width, flowNodes, reactFlow, savedViewport, renderMode]);

  useEffect(() => {
    if (renderMode === "overview") return;
    if (!selectedKey) {
      lastFocusedSelectionRef.current = "";
      return;
    }
    if (!flowNodes.length) return;
    if (lastFocusedSelectionRef.current === selectedKey) return;
    const target = flowNodes.find((node) => node.id === selectedIds[0]);
    if (!target) return;
    lastFocusedSelectionRef.current = selectedKey;

    requestAnimationFrame(() => {
      reactFlow.fitView({
        nodes: [{ id: target.id }],
        padding: 0.28,
        duration: 250,
        maxZoom: surfaceMode === "state" ? 1.12 : 1.18,
      });
    });
  }, [flowNodes, reactFlow, selectedIds, selectedKey, surfaceMode]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && isFullscreen) {
        setIsFullscreen(false);
      }
      if ((event.key === "f" || event.key === "F") && event.metaKey) {
        event.preventDefault();
        setIsFullscreen((current) => !current);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isFullscreen]);

  const onNodesChange = useCallback((changes: NodeChange<Node<WorkbenchNodeData>>[]) => {
    setFlowNodes((current) => applyNodeChanges(changes, current));
  }, []);

  const handleNodeDragStop = useCallback(
    (_event: ReactMouseEvent | ReactTouchEvent, node: Node<WorkbenchNodeData>) => {
      setPinnedNodes((current) => ({
        ...current,
        [node.id]: node.position,
      }));
    },
    [setPinnedNodes]
  );

  const handleNodeMouseEnter = useCallback(
    (_event: ReactMouseEvent, node: Node<WorkbenchNodeData>) => {
      setHoveredNodeId(node.id);
      onNodeHover?.(node.id);
    },
    [onNodeHover]
  );

  const handleNodeMouseLeave = useCallback(() => {
    setHoveredNodeId(null);
    onNodeHover?.(null);
  }, [onNodeHover]);

  const handleNodeClick = useCallback(
    (_event: ReactMouseEvent, node: Node<WorkbenchNodeData>) => {
      onNodeSelect?.(node.id);
    },
    [onNodeSelect]
  );

  const handlePaneClick = useCallback(() => {
    onBackgroundClick?.();
  }, [onBackgroundClick]);

  const handleMoveEnd = useCallback(() => {
    if (renderMode === "overview") return;
    const viewport = reactFlow.getViewport();
    setSavedViewport(viewport);
    setZoomLabel(Math.round(viewport.zoom * 100));
  }, [reactFlow, renderMode, setSavedViewport]);

  const frameClassName = isFullscreen
    ? "fixed inset-4 z-[120] flex flex-col overflow-hidden rounded-[18px] border border-border bg-card shadow-2xl"
    : "overflow-hidden rounded-[18px] border border-border bg-card shadow-sm";
  const shouldVirtualize = initializedViewportRef.current && layoutSettled;
  const showLayoutOverlay =
    renderMode !== "overview" && nodes.length > 0 && (!layoutSettled || flowNodes.length === 0);

  return (
    <>
      {isFullscreen ? (
        <div
          className="fixed inset-0 z-[110] bg-black/32 backdrop-blur-md"
          onClick={() => setIsFullscreen(false)}
          aria-hidden="true"
        />
      ) : null}
      <div className={frameClassName}>
        <div className="flex flex-col gap-3 border-b border-border px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                {badgeLabel}
              </div>
              <div className="text-sm text-muted-foreground lg:truncate">
                Drag cards, scroll to zoom, click empty space to clear.
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground lg:justify-end">
            <div className="rounded-full border px-3 py-1.5 text-sm font-medium" style={CHIP_STYLE}>
              {nodes.length} nodes
            </div>
            <div className="rounded-full border px-3 py-1.5 text-sm font-medium" style={CHIP_STYLE}>
              {edges.length} links
            </div>
            <button
              onClick={() => {
                if (renderMode === "overview") {
                  setOverviewFitVersion((current) => current + 1);
                  return;
                }
                reactFlow.fitView({ padding: 0.18, duration: 240, maxZoom: 1.1 });
              }}
              className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 font-medium text-foreground/80 hover:bg-accent"
            >
              <Radar className="h-4 w-4" />
              Fit
            </button>
            <button
              onClick={() => setIsFullscreen((current) => !current)}
              className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 font-medium text-foreground/80 hover:bg-accent"
            >
              {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Expand className="h-4 w-4" />}
              {isFullscreen ? "Exit" : "Fullscreen"}
            </button>
          </div>
        </div>

        <div
          ref={canvasRef}
          className={
            isFullscreen
              ? "relative min-h-0 flex-1 overflow-hidden rounded-b-[18px]"
              : "relative overflow-hidden rounded-b-[18px]"
          }
          style={isFullscreen ? undefined : { height }}
        >
          {renderMode === "overview" ? (
            <>
              <OverviewCanvas
                nodes={overviewNodes}
                edges={overviewEdges}
                selectedIds={selectedIds}
                highlightedNodeIds={highlightedNodeIds}
                onSelect={onNodeSelect}
                onContextMenu={onNodeContextMenu}
                onBackgroundClick={onBackgroundClick}
                onZoomChange={setOverviewZoom}
                fitVersion={overviewFitVersion}
              />
              <div
                className="pointer-events-none absolute bottom-4 left-4 rounded-full border px-4 py-2 text-sm font-medium shadow-sm"
                style={PANEL_STYLE}
              >
                Scale {overviewZoom}%
              </div>
            </>
          ) : (
            <>
              <ReactFlow<Node<WorkbenchNodeData>, Edge<WorkbenchEdgeData>>
                nodes={flowNodes}
                edges={flowEdges}
                onNodesChange={onNodesChange}
                onNodeDragStop={handleNodeDragStop}
                onNodeClick={handleNodeClick}
                onNodeContextMenu={(event, node) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onNodeContextMenu?.(node.id, { x: event.clientX, y: event.clientY });
                }}
                onNodeMouseEnter={handleNodeMouseEnter}
                onNodeMouseLeave={handleNodeMouseLeave}
                onPaneClick={handlePaneClick}
                onMoveEnd={handleMoveEnd}
                nodeTypes={nodeTypesRef.current}
                edgeTypes={edgeTypesRef.current}
                nodesDraggable
                nodesFocusable
                fitView
                minZoom={0.45}
                maxZoom={1.7}
                panOnDrag
                proOptions={{ hideAttribution: true }}
                selectionOnDrag={false}
                onlyRenderVisibleElements={shouldVirtualize}
                className="graph-surface"
              >
                <Background gap={20} size={1.1} color="var(--graph-dot)" />
                <Controls
                  showInteractive={false}
                  className="!shadow-none [&>button]:!h-10 [&>button]:!w-10 [&>button]:!border-border [&>button]:!bg-card/90 [&>button]:!text-foreground"
                />
                <Panel position="bottom-left">
                  <div
                    className="rounded-full border px-4 py-2 text-sm font-medium shadow-sm"
                    style={PANEL_STYLE}
                  >
                    Scale {zoomLabel}%
                  </div>
                </Panel>
              </ReactFlow>

              {showLayoutOverlay ? (
                <div
                  className="pointer-events-none absolute inset-0 flex items-center justify-center backdrop-blur-[1px]"
                  style={{ backgroundColor: "var(--graph-overlay-bg)" }}
                >
                  <div
                    className="rounded-full border px-4 py-2 text-sm font-medium shadow-sm"
                    style={PANEL_STYLE}
                  >
                    Building graph layout...
                  </div>
                </div>
              ) : null}

              {isFullscreen && fullscreenAccessory ? (
                <div className="pointer-events-none absolute bottom-4 right-4 z-20 flex w-[min(22rem,calc(100%-2rem))] justify-end">
                  <div className="pointer-events-auto max-h-[calc(100%-2rem)] overflow-auto rounded-2xl border border-border bg-card/92 p-3 shadow-xl backdrop-blur-md">
                    {fullscreenAccessory}
                  </div>
                </div>
              ) : null}
            </>
          )}
        </div>
      </div>
    </>
  );
}

export function GraphWorkbench(props: WorkbenchGraphProps) {
  const [isFullscreen, setIsFullscreen] = useState(false);

  return (
    <ReactFlowProvider key={isFullscreen ? "fullscreen" : "inline"}>
      <GraphWorkbenchInner
        {...props}
        isFullscreen={isFullscreen}
        setIsFullscreen={setIsFullscreen}
      />
    </ReactFlowProvider>
  );
}
