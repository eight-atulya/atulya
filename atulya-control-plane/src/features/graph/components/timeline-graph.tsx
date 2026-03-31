"use client";

import { useMemo } from "react";
import { Activity, Brain, Clock3, GitBranch, Link2, Sparkles } from "lucide-react";

import { TimelineEdge, TimelineItem, TimelineResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

const LABEL_WIDTH = 172;
const COLUMN_WIDTH = 320;
const CARD_WIDTH = 276;
const CARD_HEIGHT = 176;
const CARD_GAP = 28;
const SECTION_HEADER_HEIGHT = 54;
const SECTION_GAP = 28;
const TOP_PADDING = 32;
const BOTTOM_PADDING = 36;
const RAIL_HALF_GAP = 24;

type TimelineSide = "left" | "right";

interface TimelinePosition {
  x: number;
  y: number;
  side: TimelineSide;
  lane: number;
  anchorX: number;
  anchorY: number;
}

interface TimelineSection {
  key: string;
  label: string;
  sublabel: string;
  startY: number;
  count: number;
  firstTime: string | null;
  lastTime: string | null;
}

interface TimelineLayout {
  items: TimelineItem[];
  positions: Map<string, TimelinePosition>;
  sections: TimelineSection[];
  width: number;
  height: number;
  railX: number;
  nonChronologicalEdgeCount: number;
  itemEdgeCounts: Map<string, number>;
  recordedOnlyCount: number;
  futureCount: number;
  modelCount: number;
  observationCount: number;
  dateSpanLabel: string;
}

const kindPriority: Record<TimelineItem["kind"], number> = {
  fact: 0,
  observation: 1,
  mental_model: 2,
};

function itemTimestamp(item: TimelineItem) {
  return item.anchor_at || item.recorded_at;
}

function sortItems(items: TimelineItem[]) {
  return [...items].sort((a, b) => {
    const aTime = itemTimestamp(a) || "";
    const bTime = itemTimestamp(b) || "";
    if (aTime !== bTime) return aTime.localeCompare(bTime);
    if (kindPriority[a.kind] !== kindPriority[b.kind])
      return kindPriority[a.kind] - kindPriority[b.kind];
    return a.id.localeCompare(b.id);
  });
}

function formatSectionDay(value: string | null) {
  if (!value) {
    return { label: "Undated", sublabel: "Shown with recorded context only" };
  }

  const date = new Date(value);
  return {
    label: date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
    sublabel: date.toLocaleDateString("en-US", {
      weekday: "short",
      year: "numeric",
    }),
  };
}

function formatTimeLabel(value: string | null) {
  if (!value) return "No time";
  const date = new Date(value);
  return date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatTimestampLabel(value: string | null) {
  if (!value) return "Undated";
  const date = new Date(value);
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatDateSpan(items: TimelineItem[]) {
  const datedItems = items
    .map((item) => itemTimestamp(item))
    .filter((value): value is string => Boolean(value));
  if (datedItems.length === 0) return "Recorded without temporal anchors";

  const first = new Date(datedItems[0]);
  const last = new Date(datedItems[datedItems.length - 1]);
  const firstLabel = first.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  const lastLabel = last.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  return firstLabel === lastLabel ? firstLabel : `${firstLabel} -> ${lastLabel}`;
}

function shortLabel(item: TimelineItem) {
  if (item.kind === "mental_model" && item.title) return item.title;
  return item.text;
}

function cardSummary(item: TimelineItem) {
  if (item.kind === "mental_model") {
    return item.text;
  }
  return item.context || item.text;
}

function anchorLabel(anchorKind: string) {
  switch (anchorKind) {
    case "event_exact":
      return "Exact event";
    case "event_inferred":
      return "Inferred event";
    case "future_plan":
      return "Future plan";
    case "ongoing_state":
      return "Ongoing state";
    case "derived_snapshot":
      return "Derived snapshot";
    default:
      return "Recorded";
  }
}

function anchorBadgeClass(anchorKind: string) {
  switch (anchorKind) {
    case "event_exact":
      return "border-red-600 bg-red-600 text-white";
    case "event_inferred":
      return "border-amber-300 bg-amber-50 text-amber-900";
    case "future_plan":
      return "border-sky-300 bg-sky-50 text-sky-900";
    case "ongoing_state":
      return "border-emerald-300 bg-emerald-50 text-emerald-900";
    case "derived_snapshot":
      return "border-slate-300 bg-slate-50 text-slate-800";
    default:
      return "border-border bg-muted text-muted-foreground";
  }
}

function cardChromeClass(item: TimelineItem) {
  switch (item.anchor_kind) {
    case "event_exact":
      return "border-red-200 bg-white shadow-[0_10px_30px_rgba(220,38,38,0.08)] hover:border-red-300";
    case "event_inferred":
      return "border-amber-200 bg-amber-50/60 shadow-[0_10px_30px_rgba(245,158,11,0.08)] hover:border-amber-300";
    case "future_plan":
      return "border-sky-200 bg-sky-50/70 shadow-[0_10px_30px_rgba(14,165,233,0.10)] hover:border-sky-300";
    case "ongoing_state":
      return "border-emerald-200 bg-emerald-50/70 shadow-[0_10px_30px_rgba(16,185,129,0.08)] hover:border-emerald-300";
    case "derived_snapshot":
      return "border-slate-300 border-dashed bg-slate-50/70 shadow-[0_10px_30px_rgba(51,65,85,0.06)] hover:border-slate-400";
    default:
      return "border-border bg-white shadow-[0_12px_30px_rgba(15,23,42,0.06)] hover:border-primary/40";
  }
}

function kindBadgeClass(kind: TimelineItem["kind"]) {
  switch (kind) {
    case "observation":
      return "border-purple-200 bg-purple-50 text-purple-900";
    case "mental_model":
      return "border-slate-300 bg-slate-100 text-slate-900";
    default:
      return "border-border bg-background text-muted-foreground";
  }
}

function kindLabel(kind: TimelineItem["kind"]) {
  switch (kind) {
    case "observation":
      return "Observation";
    case "mental_model":
      return "Mental model";
    default:
      return "Fact";
  }
}

function edgeColor(edgeKind: TimelineEdge["edge_kind"]) {
  switch (edgeKind) {
    case "chronological":
      return "#cbd5e1";
    case "temporal":
      return "#0f766e";
    case "semantic":
      return "#dc2626";
    case "entity":
      return "#ca8a04";
    case "causal":
      return "#7c3aed";
    case "derived":
      return "#475569";
    case "source":
      return "#64748b";
    default:
      return "#94a3b8";
  }
}

function edgeOpacity(edgeKind: TimelineEdge["edge_kind"]) {
  switch (edgeKind) {
    case "chronological":
      return 0.8;
    case "source":
    case "derived":
      return 0.4;
    default:
      return 0.72;
  }
}

function lanePreferenceOrder(preferredLane: number) {
  const sequence = [preferredLane];
  for (let offset = 1; offset < 10; offset += 1) {
    sequence.push(preferredLane + offset);
    if (preferredLane - offset >= 0) sequence.push(preferredLane - offset);
  }
  return sequence;
}

function laneToSide(lane: number): TimelineSide {
  return lane % 2 === 0 ? "right" : "left";
}

function laneToColumn(lane: number) {
  return Math.floor(lane / 2);
}

function buildLayout(timeline: TimelineResponse): TimelineLayout | null {
  if (!timeline.items.length) return null;

  const items = sortItems(timeline.items);
  const itemIndex = new Map(items.map((item, index) => [item.id, index]));
  const incomingParents = new Map<string, string[]>();
  const itemEdgeCounts = new Map<string, number>();
  let nonChronologicalEdgeCount = 0;

  timeline.edges.forEach((edge) => {
    if (edge.edge_kind !== "chronological") {
      nonChronologicalEdgeCount += 1;
      itemEdgeCounts.set(edge.source, (itemEdgeCounts.get(edge.source) || 0) + 1);
      itemEdgeCounts.set(edge.target, (itemEdgeCounts.get(edge.target) || 0) + 1);
    }
    if (edge.edge_kind === "chronological") return;
    const sourceIndex = itemIndex.get(edge.source);
    const targetIndex = itemIndex.get(edge.target);
    if (sourceIndex === undefined || targetIndex === undefined || sourceIndex >= targetIndex)
      return;
    const existing = incomingParents.get(edge.target) || [];
    existing.push(edge.source);
    incomingParents.set(edge.target, existing);
  });

  const laneMap = new Map<string, number>();
  const parentChildCounts = new Map<string, number>();
  const seedLanes = [0, 1, 2, 3];
  items.forEach((item, index) => {
    const parents = incomingParents.get(item.id) || [];
    if (parents.length > 0) {
      const parentId = parents[0];
      const parentLane = laneMap.get(parentId) ?? seedLanes[index % seedLanes.length];
      const siblingIndex = parentChildCounts.get(parentId) || 0;
      parentChildCounts.set(parentId, siblingIndex + 1);
      laneMap.set(item.id, lanePreferenceOrder(parentLane)[siblingIndex] ?? parentLane);
      return;
    }

    laneMap.set(item.id, seedLanes[index % seedLanes.length]);
  });

  let maxLeftColumn = 0;
  let maxRightColumn = 0;
  for (const lane of laneMap.values()) {
    const column = laneToColumn(lane);
    if (laneToSide(lane) === "left") {
      maxLeftColumn = Math.max(maxLeftColumn, column);
    } else {
      maxRightColumn = Math.max(maxRightColumn, column);
    }
  }

  const leftColumns = Math.max(1, maxLeftColumn + 1);
  const rightColumns = Math.max(1, maxRightColumn + 1);
  const railX = LABEL_WIDTH + leftColumns * COLUMN_WIDTH + 18;
  const width = LABEL_WIDTH + leftColumns * COLUMN_WIDTH + rightColumns * COLUMN_WIDTH + 80;

  const positions = new Map<string, TimelinePosition>();
  const sections: TimelineSection[] = [];
  let currentSectionKey: string | null = null;
  let y = TOP_PADDING;

  items.forEach((item) => {
    const timestamp = itemTimestamp(item);
    const sectionKey = timestamp ? timestamp.slice(0, 10) : "undated";

    if (sectionKey !== currentSectionKey) {
      if (currentSectionKey !== null) {
        y += SECTION_GAP;
      }
      const formatted = formatSectionDay(timestamp);
      sections.push({
        key: sectionKey,
        label: formatted.label,
        sublabel: formatted.sublabel,
        startY: y,
        count: 0,
        firstTime: timestamp,
        lastTime: timestamp,
      });
      y += SECTION_HEADER_HEIGHT;
      currentSectionKey = sectionKey;
    }

    const section = sections[sections.length - 1];
    section.count += 1;
    section.lastTime = timestamp;
    const lane = laneMap.get(item.id) ?? 0;
    const side = laneToSide(lane);
    const column = laneToColumn(lane);
    const x =
      side === "right"
        ? railX + RAIL_HALF_GAP + column * COLUMN_WIDTH
        : railX - RAIL_HALF_GAP - CARD_WIDTH - column * COLUMN_WIDTH;

    positions.set(item.id, {
      x,
      y,
      side,
      lane,
      anchorX: side === "right" ? x : x + CARD_WIDTH,
      anchorY: y + 72,
    });
    y += CARD_HEIGHT + CARD_GAP;
  });

  return {
    items,
    positions,
    sections,
    width,
    height: y + BOTTOM_PADDING,
    railX,
    nonChronologicalEdgeCount,
    itemEdgeCounts,
    recordedOnlyCount: items.filter((item) => item.anchor_kind === "recorded_only").length,
    futureCount: items.filter((item) => item.temporal_direction === "future").length,
    modelCount: items.filter((item) => item.kind === "mental_model").length,
    observationCount: items.filter((item) => item.kind === "observation").length,
    dateSpanLabel: formatDateSpan(items),
  };
}

function edgePath(
  edge: TimelineEdge,
  source: TimelinePosition,
  target: TimelinePosition,
  railX: number
) {
  const branchX =
    edge.edge_kind === "chronological" ? railX : source.side === "right" ? railX + 10 : railX - 10;
  const targetBranchX =
    edge.edge_kind === "chronological" ? railX : target.side === "right" ? railX + 10 : railX - 10;
  const midpointY = source.anchorY + (target.anchorY - source.anchorY) / 2;

  if (edge.edge_kind === "chronological") {
    return `M ${source.anchorX} ${source.anchorY} H ${railX} V ${target.anchorY} H ${target.anchorX}`;
  }

  return `M ${source.anchorX} ${source.anchorY} H ${branchX} V ${midpointY} H ${targetBranchX} V ${target.anchorY} H ${target.anchorX}`;
}

function MetricCard({
  label,
  value,
  helper,
  icon: Icon,
  toneClass,
}: {
  label: string;
  value: string;
  helper: string;
  icon: typeof Activity;
  toneClass: string;
}) {
  return (
    <div className="rounded-2xl border border-border bg-background/70 p-4 shadow-sm backdrop-blur-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            {label}
          </div>
          <div className="mt-2 text-2xl font-semibold tracking-tight text-foreground">{value}</div>
          <div className="mt-1 text-xs leading-5 text-muted-foreground">{helper}</div>
        </div>
        <div className={cn("rounded-2xl p-2.5", toneClass)}>
          <Icon className="h-4 w-4" />
        </div>
      </div>
    </div>
  );
}

function DesktopTimeline({
  timeline,
  layout,
  onMemoryClick,
  onMentalModelClick,
}: {
  timeline: TimelineResponse;
  layout: TimelineLayout;
  onMemoryClick: (memoryId: string) => void;
  onMentalModelClick: (mentalModelId: string) => void;
}) {
  return (
    <div className="hidden lg:block">
      <div className="overflow-x-auto rounded-[28px] border border-border bg-[linear-gradient(180deg,rgba(255,255,255,0.92),rgba(248,250,252,0.96))]">
        <div
          className="relative"
          style={{ width: `${layout.width}px`, height: `${layout.height}px` }}
        >
          <div
            className="absolute top-0 bottom-0 w-px bg-gradient-to-b from-border via-slate-300 to-border"
            style={{ left: `${layout.railX}px` }}
          />

          {layout.sections.map((section) => (
            <div key={section.key}>
              <div
                className="absolute left-5 rounded-2xl border border-border bg-background/95 px-4 py-3 shadow-sm"
                style={{ top: `${section.startY}px`, width: `${LABEL_WIDTH - 22}px` }}
              >
                <div className="text-lg font-semibold tracking-tight text-foreground">
                  {section.label}
                </div>
                <div className="mt-0.5 text-xs uppercase tracking-[0.14em] text-muted-foreground">
                  {section.sublabel}
                </div>
                <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
                  <span>{section.count} items</span>
                  {section.firstTime ? <span>{formatTimeLabel(section.firstTime)}</span> : null}
                  {section.lastTime && section.lastTime !== section.firstTime ? (
                    <span>to {formatTimeLabel(section.lastTime)}</span>
                  ) : null}
                </div>
              </div>
              <div
                className="absolute h-px bg-gradient-to-r from-transparent via-border to-transparent"
                style={{
                  left: `${LABEL_WIDTH - 6}px`,
                  right: "16px",
                  top: `${section.startY + SECTION_HEADER_HEIGHT - 12}px`,
                }}
              />
            </div>
          ))}

          <svg
            className="absolute inset-0 pointer-events-none"
            width={layout.width}
            height={layout.height}
          >
            {timeline.edges.map((edge, index) => {
              const source = layout.positions.get(edge.source);
              const target = layout.positions.get(edge.target);
              if (!source || !target) return null;
              return (
                <path
                  key={`${edge.source}:${edge.target}:${edge.edge_kind}:${index}`}
                  d={edgePath(edge, source, target, layout.railX)}
                  fill="none"
                  stroke={edgeColor(edge.edge_kind)}
                  strokeWidth={edge.edge_kind === "chronological" ? 1.8 : 1.4}
                  strokeDasharray={
                    edge.edge_kind === "source" || edge.edge_kind === "derived" ? "6 5" : undefined
                  }
                  opacity={edgeOpacity(edge.edge_kind)}
                />
              );
            })}
          </svg>

          {layout.items.map((item) => {
            const position = layout.positions.get(item.id);
            if (!position) return null;
            const connectedEdges = layout.itemEdgeCounts.get(item.id) || 0;
            const clickable = item.kind === "mental_model" ? !!onMentalModelClick : !!onMemoryClick;
            const timeValue = itemTimestamp(item);

            return (
              <div key={item.id}>
                <div
                  className="absolute -translate-x-1/2 rounded-full border border-border bg-background/95 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground shadow-sm"
                  style={{
                    left: `${layout.railX}px`,
                    top: `${position.y + 14}px`,
                  }}
                >
                  {formatTimeLabel(timeValue)}
                </div>

                <button
                  type="button"
                  onClick={() =>
                    item.kind === "mental_model"
                      ? onMentalModelClick(item.id)
                      : onMemoryClick(item.id)
                  }
                  disabled={!clickable}
                  className={cn(
                    "absolute overflow-hidden rounded-[26px] border p-4 text-left transition-all duration-200",
                    "disabled:cursor-default disabled:opacity-100",
                    "hover:-translate-y-0.5 hover:shadow-[0_18px_40px_rgba(15,23,42,0.10)]",
                    cardChromeClass(item)
                  )}
                  style={{
                    left: `${position.x}px`,
                    top: `${position.y}px`,
                    width: `${CARD_WIDTH}px`,
                    minHeight: `${CARD_HEIGHT}px`,
                  }}
                >
                  <div
                    className={cn(
                      "absolute inset-y-0 w-1.5 rounded-full",
                      position.side === "right" ? "left-0" : "right-0",
                      item.anchor_kind === "event_exact" && "bg-red-500",
                      item.anchor_kind === "event_inferred" && "bg-amber-500",
                      item.anchor_kind === "future_plan" && "bg-sky-500",
                      item.anchor_kind === "ongoing_state" && "bg-emerald-500",
                      item.anchor_kind === "derived_snapshot" && "bg-slate-500",
                      item.anchor_kind === "recorded_only" && "bg-slate-300"
                    )}
                  />

                  <div className="flex items-start justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={cn(
                          "rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]",
                          anchorBadgeClass(item.anchor_kind)
                        )}
                      >
                        {anchorLabel(item.anchor_kind)}
                      </span>
                      <span
                        className={cn(
                          "rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-[0.12em]",
                          kindBadgeClass(item.kind)
                        )}
                      >
                        {kindLabel(item.kind)}
                      </span>
                    </div>
                    <div className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
                      {item.temporal_direction}
                    </div>
                  </div>

                  <div className="mt-4 text-lg font-semibold leading-tight tracking-tight text-foreground line-clamp-2">
                    {shortLabel(item)}
                  </div>

                  <div className="mt-2 text-sm leading-6 text-muted-foreground line-clamp-2">
                    {cardSummary(item)}
                  </div>

                  <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {item.temporal_confidence !== null ? (
                      <span className="rounded-full bg-background/80 px-2.5 py-1">
                        {Math.round(item.temporal_confidence * 100)}% confidence
                      </span>
                    ) : null}
                    {item.proof_count > 0 ? (
                      <span className="rounded-full bg-background/80 px-2.5 py-1">
                        {item.proof_count} proofs
                      </span>
                    ) : null}
                    {connectedEdges > 0 ? (
                      <span className="rounded-full bg-background/80 px-2.5 py-1">
                        {connectedEdges} links
                      </span>
                    ) : null}
                    {item.kind === "mental_model" && item.source_memory_ids.length > 0 ? (
                      <span className="rounded-full bg-background/80 px-2.5 py-1">
                        derived from {item.source_memory_ids.length}
                      </span>
                    ) : null}
                  </div>

                  {(item.entities.length > 0 || item.tags.length > 0) && (
                    <div className="mt-4 flex flex-wrap gap-1.5">
                      {item.entities.slice(0, 3).map((entity) => (
                        <span
                          key={`${item.id}:${entity}`}
                          className="rounded-full border border-red-200 bg-red-50 px-2 py-1 text-[11px] font-medium text-red-900"
                        >
                          {entity}
                        </span>
                      ))}
                      {item.tags.slice(0, 2).map((tag) => (
                        <span
                          key={`${item.id}:tag:${tag}`}
                          className="rounded-full border border-slate-200 bg-slate-100 px-2 py-1 text-[11px] font-medium text-slate-700"
                        >
                          #{tag}
                        </span>
                      ))}
                      {item.entities.length + item.tags.length > 5 ? (
                        <span className="rounded-full border border-border bg-background px-2 py-1 text-[11px] text-muted-foreground">
                          +{item.entities.length + item.tags.length - 5}
                        </span>
                      ) : null}
                    </div>
                  )}

                  <div className="mt-4 flex items-center justify-between text-[11px] text-muted-foreground">
                    <span>{formatTimestampLabel(timeValue)}</span>
                    {item.temporal.reference_text ? (
                      <span>{item.temporal.reference_text}</span>
                    ) : (
                      <span />
                    )}
                  </div>
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function MobileTimeline({
  layout,
  onMemoryClick,
  onMentalModelClick,
}: {
  layout: TimelineLayout;
  onMemoryClick: (memoryId: string) => void;
  onMentalModelClick: (mentalModelId: string) => void;
}) {
  const sectionMap = new Map(layout.sections.map((section) => [section.key, section]));
  const groupedItems = layout.items.reduce<Record<string, TimelineItem[]>>((accumulator, item) => {
    const key = itemTimestamp(item) ? itemTimestamp(item)!.slice(0, 10) : "undated";
    accumulator[key] = accumulator[key] || [];
    accumulator[key].push(item);
    return accumulator;
  }, {});

  return (
    <div className="space-y-6 lg:hidden">
      {Object.entries(groupedItems).map(([sectionKey, items]) => {
        const section = sectionMap.get(sectionKey);
        return (
          <section
            key={sectionKey}
            className="rounded-3xl border border-border bg-card p-4 shadow-sm"
          >
            <div className="mb-4 flex items-end justify-between gap-4">
              <div>
                <div className="text-lg font-semibold tracking-tight text-foreground">
                  {section?.label || "Undated"}
                </div>
                <div className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
                  {section?.sublabel || "Recorded context"}
                </div>
              </div>
              <div className="text-xs text-muted-foreground">{items.length} items</div>
            </div>

            <div className="space-y-3 border-l border-border pl-4">
              {items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() =>
                    item.kind === "mental_model"
                      ? onMentalModelClick(item.id)
                      : onMemoryClick(item.id)
                  }
                  className={cn(
                    "w-full rounded-2xl border p-4 text-left shadow-sm transition-colors",
                    cardChromeClass(item)
                  )}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-border bg-background px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                      {formatTimeLabel(itemTimestamp(item))}
                    </span>
                    <span
                      className={cn(
                        "rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.12em]",
                        anchorBadgeClass(item.anchor_kind)
                      )}
                    >
                      {anchorLabel(item.anchor_kind)}
                    </span>
                  </div>
                  <div className="mt-3 text-base font-semibold leading-tight text-foreground line-clamp-2">
                    {shortLabel(item)}
                  </div>
                  <div className="mt-1 text-sm text-muted-foreground line-clamp-2">
                    {cardSummary(item)}
                  </div>
                </button>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

interface TimelineGraphProps {
  timeline: TimelineResponse | null;
  onMemoryClick: (memoryId: string) => void;
  onMentalModelClick: (mentalModelId: string) => void;
}

export function TimelineGraph({ timeline, onMemoryClick, onMentalModelClick }: TimelineGraphProps) {
  const layout = useMemo(() => (timeline ? buildLayout(timeline) : null), [timeline]);

  if (!timeline || timeline.items.length === 0 || !layout) {
    return (
      <div className="rounded-3xl border border-dashed border-border bg-card/70 px-6 py-14 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-muted">
          <Clock3 className="h-5 w-5 text-muted-foreground" />
        </div>
        <div className="mt-4 text-lg font-semibold text-foreground">No Timeline Data</div>
        <div className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted-foreground">
          No timeline-ready memories matched the current filters. When semantic dates are missing,
          recorded time is used automatically.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="rounded-[28px] border border-border bg-[radial-gradient(circle_at_top_left,rgba(239,68,68,0.07),transparent_28%),linear-gradient(180deg,rgba(255,255,255,0.96),rgba(248,250,252,0.98))] p-5 shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-2xl">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              Timeline Intelligence
            </div>
            <div className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
              Memory flow across recorded and semantic time
            </div>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              Exact events, inferred events, ongoing states, future plans, and derived mental models
              are rendered on one chronological rail so you can follow how knowledge forms and
              branches.
            </p>
          </div>

          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span className="rounded-full border border-border bg-background/80 px-3 py-1.5">
              {layout.recordedOnlyCount} recorded-only anchors
            </span>
            <span className="rounded-full border border-border bg-background/80 px-3 py-1.5">
              {layout.nonChronologicalEdgeCount} branch links
            </span>
            <span className="rounded-full border border-border bg-background/80 px-3 py-1.5">
              {layout.dateSpanLabel}
            </span>
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            label="Timeline Span"
            value={layout.dateSpanLabel}
            helper="Chronological coverage of visible memories"
            icon={Clock3}
            toneClass="bg-slate-100 text-slate-700"
          />
          <MetricCard
            label="Connected Branches"
            value={String(layout.nonChronologicalEdgeCount)}
            helper="Semantic, temporal, causal, source, and derived links"
            icon={GitBranch}
            toneClass="bg-red-50 text-red-700"
          />
          <MetricCard
            label="Derived Context"
            value={String(layout.modelCount + layout.observationCount)}
            helper={`${layout.observationCount} observations and ${layout.modelCount} mental models`}
            icon={Brain}
            toneClass="bg-purple-50 text-purple-700"
          />
          <MetricCard
            label="Future Signals"
            value={String(layout.futureCount)}
            helper="Plans or forecasted states anchored ahead of the present"
            icon={Sparkles}
            toneClass="bg-sky-50 text-sky-700"
          />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
          {[
            ["Exact event", "border-red-600 bg-red-600 text-white"],
            ["Inferred event", "border-amber-300 bg-amber-50 text-amber-900"],
            ["Ongoing state", "border-emerald-300 bg-emerald-50 text-emerald-900"],
            ["Future plan", "border-sky-300 bg-sky-50 text-sky-900"],
            ["Derived snapshot", "border-slate-300 bg-slate-50 text-slate-800"],
          ].map(([label, tone]) => (
            <span key={label} className={cn("rounded-full border px-2.5 py-1 font-medium", tone)}>
              {label}
            </span>
          ))}
          <span className="rounded-full border border-border bg-background px-2.5 py-1 font-medium text-muted-foreground">
            Recorded items are placed by mentioned time when semantic time is missing
          </span>
        </div>
      </div>

      <DesktopTimeline
        timeline={timeline}
        layout={layout}
        onMemoryClick={onMemoryClick}
        onMentalModelClick={onMentalModelClick}
      />

      <MobileTimeline
        layout={layout}
        onMemoryClick={onMemoryClick}
        onMentalModelClick={onMentalModelClick}
      />

      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-border bg-card px-4 py-3 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <Link2 className="h-3.5 w-3.5" />
          Chronological rails keep sequence stable while branch lines show semantic or causal
          connections.
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Activity className="h-3.5 w-3.5" />
          Cards favor the clearest label, then context, then proof and link density so important
          memory state reads fast.
        </span>
      </div>
    </div>
  );
}
