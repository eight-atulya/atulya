"use client";

import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { toast } from "sonner";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Brain,
  CheckCircle2,
  Clock3,
  Database,
  Loader2,
  Network,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  Upload,
  Workflow,
  Zap,
} from "lucide-react";
import {
  client,
  type GraphNeighborhoodResponse,
  type MentalModel,
  type ReflectResponse,
} from "@/lib/api";
import { useBank } from "@/lib/bank-context";
import { useFeatures } from "@/lib/features-context";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type BrainStatusPayload = Awaited<ReturnType<typeof client.getBrainStatus>>;
type InfluencePayload = Awaited<ReturnType<typeof client.getBrainInfluence>>;
type PredictionPayload = Awaited<ReturnType<typeof client.getSubRoutinePredictions>>;
type HistogramPayload = Awaited<ReturnType<typeof client.getSubRoutineHistogram>>;
type DirectiveListPayload = Awaited<ReturnType<typeof client.listDirectives>>;
type MentalModelListPayload = Awaited<ReturnType<typeof client.listMentalModels>>;
type OperationListPayload = Awaited<ReturnType<typeof client.listOperations>>;

type CockpitTheme = "midnight" | "monsoon";
type SolverFocus = "stability" | "growth" | "memory";
type EntityTypeFilter = "all" | "memory" | "chunk" | "mental_model";

type CockpitSnapshot = {
  status: BrainStatusPayload | null;
  influence: InfluencePayload | null;
  predictions: PredictionPayload | null;
  histogram: HistogramPayload | null;
  graph: GraphNeighborhoodResponse | null;
  directives: DirectiveListPayload | null;
  mentalModels: MentalModelListPayload | null;
  operations: OperationListPayload | null;
};

type PartialErrors = Partial<Record<keyof CockpitSnapshot, string>>;

type RecallResultPayload = {
  results: Array<Record<string, any>>;
  trace: Record<string, any> | null;
  entities: Array<Record<string, any>> | null;
  chunks: Array<Record<string, any>> | null;
};

type Recommendation = {
  id: string;
  title: string;
  body: string;
  score: number;
  tone: "good" | "warn" | "critical" | "neutral";
  action: string;
};

type CockpitViewModel = {
  pulseTone: "good" | "warn" | "critical" | "neutral";
  pulseLabel: string;
  pulseCopy: string;
  topInfluenceLabel: string;
  pendingOps: number;
  completedOps: number;
  anomalyCount: number;
  modelCount: number;
  directiveCount: number;
  graphNodeCount: number;
  graphEdgeCount: number;
  chartPoints: Array<{ x: number; raw: number; ewma: number; anomaly: boolean }>;
  topPredictionHour: string;
  topPredictionScore: number | null;
  topHistogramHour: string;
  histogramPeakScore: number | null;
  kpis: Array<{
    label: string;
    value: string;
    note: string;
    tone: "good" | "warn" | "critical" | "neutral";
  }>;
};

const COCKPIT_THEME_KEY = "jio-brain-cockpit-theme";
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function formatCompactNumber(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "--";
  return new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(
    value
  );
}

function formatBytes(value: number | null | undefined): string {
  if (!value || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Not yet";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Not yet";
  return date.toLocaleString("en-IN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function safeMetric(
  metrics: Record<string, number> | null | undefined,
  keys: string[]
): number | null {
  if (!metrics) return null;
  for (const key of keys) {
    const value = metrics[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

function parseTags(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function toneClasses(theme: CockpitTheme, tone: "good" | "warn" | "critical" | "neutral"): string {
  const darkMap = {
    good: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
    warn: "border-amber-500/30 bg-amber-500/10 text-amber-200",
    critical: "border-rose-500/30 bg-rose-500/10 text-rose-200",
    neutral: "border-white/10 bg-white/5 text-slate-300",
  } as const;
  const lightMap = {
    good: "border-emerald-300 bg-emerald-50 text-emerald-800",
    warn: "border-amber-300 bg-amber-50 text-amber-800",
    critical: "border-rose-300 bg-rose-50 text-rose-800",
    neutral: "border-slate-200 bg-white/80 text-slate-700",
  } as const;
  return theme === "midnight" ? darkMap[tone] : lightMap[tone];
}

function buildViewModel(snapshot: CockpitSnapshot): CockpitViewModel {
  const leaderboard = snapshot.influence?.leaderboard ?? [];
  const operations = snapshot.operations?.operations ?? [];
  const anomalies = snapshot.influence?.anomalies ?? [];
  const pendingOps = operations.filter((item) => item.status === "pending").length;
  const completedOps = operations.filter((item) => item.status === "completed").length;
  const topInfluence = leaderboard[0];
  const topPrediction = [...(snapshot.predictions?.predictions ?? [])].sort(
    (a, b) => b.score - a.score
  )[0];
  const topHistogram = [...(snapshot.histogram?.histogram ?? [])].sort(
    (a, b) => b.score - a.score
  )[0];
  const queueMetric = pendingOps > 0 ? "watch" : completedOps > 0 ? "steady" : "idle";
  const graphNodeCount = snapshot.graph?.total_nodes ?? 0;
  const graphEdgeCount = snapshot.graph?.total_edges ?? 0;
  const runtimeFailures = snapshot.status?.failure_count ?? 0;
  const enabled = snapshot.status?.enabled ?? false;
  const circuitOpen = snapshot.status?.circuit_open ?? false;
  const pulseTone = !enabled
    ? "neutral"
    : circuitOpen || runtimeFailures > 0
      ? "critical"
      : pendingOps > 0 || anomalies.length > 0
        ? "warn"
        : "good";

  const pulseLabel = !enabled
    ? "Brain runtime unavailable"
    : circuitOpen
      ? "Circuit open"
      : runtimeFailures > 0
        ? "Runtime under pressure"
        : pendingOps > 0
          ? "Live traffic in motion"
          : "Bank connected";

  const pulseCopy = !enabled
    ? "Recall and retain can still run, but the dedicated brain runtime is off for this bank."
    : circuitOpen
      ? "This bank reports an open circuit. Stabilize the runtime before trusting downstream brain signals."
      : pendingOps > 0
        ? `${pendingOps} workflow${pendingOps === 1 ? "" : "s"} are still in flight.`
        : "Brain status, memory graph, and operator lanes are reading from the selected bank.";

  const chartPoints = (snapshot.influence?.trend ?? []).map((point) => ({
    x: point.index,
    raw: point.raw,
    ewma: point.ewma,
    anomaly: anomalies.some((entry) => entry.index === point.index),
  }));

  const writeAmp = safeMetric(snapshot.status?.metrics, [
    "bank_total_writes",
    "total_writes",
    "write_count",
  ]);

  const kpis = [
    {
      label: "Pulse",
      value: pulseLabel,
      note: snapshot.status
        ? formatDateTime(snapshot.status.generated_at ?? snapshot.status.last_modified_at)
        : "No runtime snapshot",
      tone: pulseTone,
    },
    {
      label: "Cache mass",
      value: snapshot.status ? formatBytes(snapshot.status.size_bytes) : "--",
      note: enabled ? "Brain file footprint" : "Runtime disabled",
      tone: enabled ? "neutral" : "warn",
    },
    {
      label: "Influence peak",
      value: topInfluence ? topInfluence.text.slice(0, 22) : "No influence yet",
      note: topInfluence
        ? `${topInfluence.type} · ${topInfluence.influence_score.toFixed(2)}`
        : "Run with a bank that has retrieval history",
      tone: topInfluence ? "good" : "neutral",
    },
    {
      label: "Rhythm",
      value: topPrediction ? `${String(topPrediction.hour_utc).padStart(2, "0")}:00 UTC` : "--",
      note: topPrediction
        ? `forecast score ${topPrediction.score.toFixed(2)}`
        : "No prediction lane yet",
      tone: topPrediction ? "good" : "neutral",
    },
    {
      label: "Guidance",
      value: `${snapshot.mentalModels?.items.length ?? 0} models / ${snapshot.directives?.items.length ?? 0} directives`,
      note: queueMetric === "watch" ? "Operator memory is active" : "Stored guidance snapshot",
      tone: snapshot.directives?.items.length ? "good" : "warn",
    },
    {
      label: "Write amp",
      value: writeAmp !== null ? formatCompactNumber(writeAmp) : "--",
      note: `${graphNodeCount} graph nodes · ${graphEdgeCount} links`,
      tone: writeAmp !== null ? "neutral" : "warn",
    },
  ] satisfies CockpitViewModel["kpis"];

  return {
    pulseTone,
    pulseLabel,
    pulseCopy,
    topInfluenceLabel: topInfluence?.text ?? "No high-signal memory surfaced yet.",
    pendingOps,
    completedOps,
    anomalyCount: anomalies.length,
    modelCount: snapshot.mentalModels?.items.length ?? 0,
    directiveCount: snapshot.directives?.items.length ?? 0,
    graphNodeCount,
    graphEdgeCount,
    chartPoints,
    topPredictionHour: topPrediction
      ? `${String(topPrediction.hour_utc).padStart(2, "0")}:00 UTC`
      : "--",
    topPredictionScore: topPrediction?.score ?? null,
    topHistogramHour: topHistogram
      ? `${String(topHistogram.hour_utc).padStart(2, "0")}:00 UTC`
      : "--",
    histogramPeakScore: topHistogram?.score ?? null,
    kpis,
  };
}

function buildRecommendations(args: {
  snapshot: CockpitSnapshot;
  focus: SolverFocus;
  recallResponse: RecallResultPayload | null;
  reflectResponse: ReflectResponse | null;
  retainDraft: string;
}): Recommendation[] {
  const { snapshot, focus, recallResponse, reflectResponse, retainDraft } = args;
  const recommendations: Recommendation[] = [];
  const pendingOps =
    snapshot.operations?.operations.filter((item) => item.status === "pending").length ?? 0;
  const anomalyCount = snapshot.influence?.anomalies.length ?? 0;
  const directiveCount = snapshot.directives?.items.length ?? 0;
  const modelCount = snapshot.mentalModels?.items.length ?? 0;
  const enabled = snapshot.status?.enabled ?? false;
  const circuitOpen = snapshot.status?.circuit_open ?? false;
  const runtimeFailures = snapshot.status?.failure_count ?? 0;
  const lowPredictionCoverage =
    snapshot.predictions?.sample_count !== undefined && snapshot.predictions.sample_count < 8;
  const recallCount = recallResponse?.results.length ?? 0;

  const focusBoost = (bucket: SolverFocus) => (focus === bucket ? 20 : 0);

  if (!enabled) {
    recommendations.push({
      id: "runtime-off",
      title: "Work from recall-first mode",
      body: "This bank does not expose the dedicated brain runtime right now. Keep the cockpit useful by using recall, reflect, and retain while treating the brain lane as informational only.",
      score: 110 + focusBoost("stability"),
      tone: "warn",
      action: "Run recall and capture operator notes before leaning on brain-only signals.",
    });
  } else if (circuitOpen || runtimeFailures > 0) {
    recommendations.push({
      id: "stabilize-runtime",
      title: "Stabilize the bank runtime",
      body: `The selected bank reports ${runtimeFailures} recent failure${runtimeFailures === 1 ? "" : "s"}${circuitOpen ? " and an open circuit" : ""}.`,
      score: 120 + focusBoost("stability"),
      tone: "critical",
      action:
        "Run sub-routine only after the runtime settles and use the operations lane to inspect the last failing task.",
    });
  }

  if (pendingOps > 0) {
    recommendations.push({
      id: "queue-watch",
      title: "Clear the in-flight queue",
      body: `${pendingOps} operation${pendingOps === 1 ? "" : "s"} are still pending. Fresh reasoning can drift if the bank is mid-refresh.`,
      score: 92 + focusBoost("stability"),
      tone: pendingOps > 3 ? "critical" : "warn",
      action: "Watch the latest operations before treating this snapshot as final.",
    });
  }

  if (anomalyCount > 0) {
    recommendations.push({
      id: "anomaly-lane",
      title: "Inspect the anomaly lane",
      body: `${anomalyCount} anomaly point${anomalyCount === 1 ? "" : "s"} surfaced in influence trend. That is the fastest path to a meaningful operator story.`,
      score: 88 + focusBoost("growth"),
      tone: "warn",
      action:
        "Use reflect on the latest anomaly window and connect the answer to the top influence node.",
    });
  }

  if (directiveCount === 0) {
    recommendations.push({
      id: "directive-gap",
      title: "Add one guiding directive",
      body: "The bank has no active directives in the cockpit snapshot. Reasoning quality improves when the bank has one clear posture or rule to anchor it.",
      score: 80 + focusBoost("memory"),
      tone: "warn",
      action:
        "Create a directive for tone, risk posture, or action boundaries before scaling operator use.",
    });
  }

  if (
    modelCount === 0 ||
    (snapshot.influence?.leaderboard[0]?.type === "memory" && modelCount < 2)
  ) {
    recommendations.push({
      id: "model-promotion",
      title: "Promote a recurring thread into a mental model",
      body: "The highest-signal bank content is still living at the raw memory layer. Distill it once so the next reflect run has something durable to stand on.",
      score: 78 + focusBoost("memory"),
      tone: "good",
      action: "Refresh or create a mental model from the strongest repeated query.",
    });
  }

  if (lowPredictionCoverage) {
    recommendations.push({
      id: "prediction-depth",
      title: "Strengthen the rhythm forecast",
      body: "Prediction coverage is still thin, so the hourly rhythm lane is more directional than reliable.",
      score: 72 + focusBoost("growth"),
      tone: "warn",
      action:
        "Run the sub-routine to deepen the forecast surface before trusting peak-hour recommendations.",
    });
  }

  if (!reflectResponse) {
    recommendations.push({
      id: "reflect-lane",
      title: "Run one operator-grade reflection",
      body: "The cockpit has live status and graph context, but it still needs one synthesized answer to turn signals into action.",
      score: 74 + focusBoost("growth"),
      tone: "good",
      action: "Ask reflect for the biggest current risk or leverage point in this bank.",
    });
  }

  if (recallCount < 3) {
    recommendations.push({
      id: "recall-depth",
      title: "Widen the evidence search",
      body: "The evidence lane is still shallow. A richer recall result makes the graph and recommendation panel sharper.",
      score: 68 + focusBoost("memory"),
      tone: "good",
      action: "Run recall with a broader question and tags to collect more source facts.",
    });
  }

  if (retainDraft.trim().length > 0) {
    recommendations.push({
      id: "retain-ready",
      title: "Commit the operator note",
      body: "You already have a fresh memory draft in the capture lane. Retaining it now will make the cockpit more representative on the next refresh.",
      score: 66 + focusBoost("memory"),
      tone: "good",
      action: "Save the draft into the current bank, then refresh to see its downstream effect.",
    });
  }

  recommendations.push({
    id: "stay-live",
    title: "Keep the bank selector as the source of truth",
    body: "This cockpit is only useful if every lane reflects the bank chosen in the global header. Treat bank changes as a full context switch, not a filter toggle.",
    score: 40,
    tone: "neutral",
    action: "Switch banks from the global selector whenever you want a new cockpit state.",
  });

  return recommendations.sort((a, b) => b.score - a.score).slice(0, 4);
}

function makeHeatmapRows(heatmap: InfluencePayload["heatmap"] | undefined) {
  const rows = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => 0));
  for (const cell of heatmap ?? []) {
    if (rows[cell.weekday]?.[cell.hour_utc] !== undefined) {
      rows[cell.weekday][cell.hour_utc] = cell.score;
    }
  }
  return rows;
}

function makeTrendPath(points: Array<{ x: number; y: number }>, width: number, height: number) {
  if (points.length === 0) return "";
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  return points
    .map((point, index) => {
      const px =
        maxX === minX ? 10 : 10 + ((point.x - minX) / Math.max(1, maxX - minX)) * (width - 20);
      const py =
        maxY === minY
          ? height / 2
          : height - 10 - ((point.y - minY) / Math.max(1e-6, maxY - minY)) * (height - 20);
      return `${index === 0 ? "M" : "L"} ${px.toFixed(1)} ${py.toFixed(1)}`;
    })
    .join(" ");
}

function buildGraphLayout(graph: GraphNeighborhoodResponse | null) {
  const nodes = graph?.nodes.slice(0, 9) ?? [];
  if (nodes.length === 0)
    return { nodes: [], edges: [] as Array<GraphNeighborhoodResponse["edges"][number]> };
  const focusId = graph?.focus_ids[0] ?? nodes[0].id;
  const center = nodes.find((node) => node.id === focusId) ?? nodes[0];
  const ring = nodes.filter((node) => node.id !== center.id);
  const positionedNodes = [
    { node: center, x: 50, y: 50 },
    ...ring.map((node, index) => {
      const angle = -Math.PI / 2 + (index / Math.max(1, ring.length)) * Math.PI * 2;
      const radius = 34 + (index % 2) * 6;
      return {
        node,
        x: 50 + Math.cos(angle) * radius,
        y: 50 + Math.sin(angle) * radius,
      };
    }),
  ];
  const edgeIds = new Set(positionedNodes.map((entry) => entry.node.id));
  const edges = (graph?.edges ?? []).filter(
    (edge) => edgeIds.has(edge.source) && edgeIds.has(edge.target)
  );
  return { nodes: positionedNodes, edges };
}

function MiniBadge({
  children,
  theme,
  tone = "neutral",
}: {
  children: ReactNode;
  theme: CockpitTheme;
  tone?: "good" | "warn" | "critical" | "neutral";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium",
        toneClasses(theme, tone)
      )}
    >
      {children}
    </span>
  );
}

function PanelFrame({
  title,
  body,
  children,
  theme,
  className,
  actions,
}: {
  title: string;
  body: string;
  children: ReactNode;
  theme: CockpitTheme;
  className?: string;
  actions?: ReactNode;
}) {
  return (
    <Card
      className={cn(
        "overflow-hidden border shadow-[0_20px_70px_-42px_rgba(15,23,42,0.55)]",
        theme === "midnight"
          ? "border-white/10 bg-white/[0.04] text-slate-100"
          : "border-sky-200/80 bg-white/80 text-slate-900",
        className
      )}
    >
      <CardContent className="p-0">
        <div
          className={cn(
            "flex items-start justify-between gap-4 border-b px-5 py-4",
            theme === "midnight" ? "border-white/10 bg-white/[0.02]" : "border-sky-100 bg-sky-50/70"
          )}
        >
          <div>
            <h2 className="font-semibold tracking-tight">{title}</h2>
            <p
              className={cn(
                "mt-1 text-sm",
                theme === "midnight" ? "text-slate-400" : "text-slate-600"
              )}
            >
              {body}
            </p>
          </div>
          {actions}
        </div>
        <div className="p-5">{children}</div>
      </CardContent>
    </Card>
  );
}

export function BrainCockpit() {
  const params = useParams<{ bankId: string }>();
  const { currentBank } = useBank();
  const { features } = useFeatures();
  const bankId = params?.bankId ?? currentBank ?? null;

  const [cockpitTheme, setCockpitTheme] = useState<CockpitTheme>("midnight");
  const [windowDays, setWindowDays] = useState(14);
  const [topK, setTopK] = useState(12);
  const [horizonHours, setHorizonHours] = useState(24);
  const [entityType, setEntityType] = useState<EntityTypeFilter>("all");
  const [solverFocus, setSolverFocus] = useState<SolverFocus>("stability");
  const [snapshot, setSnapshot] = useState<CockpitSnapshot>({
    status: null,
    influence: null,
    predictions: null,
    histogram: null,
    graph: null,
    directives: null,
    mentalModels: null,
    operations: null,
  });
  const [partialErrors, setPartialErrors] = useState<PartialErrors>({});
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedMentalModelId, setSelectedMentalModelId] = useState<string>("");

  const [recallQuery, setRecallQuery] = useState(
    "What is changing fastest in this bank right now?"
  );
  const [recallResponse, setRecallResponse] = useState<RecallResultPayload | null>(null);
  const [reflectQuery, setReflectQuery] = useState(
    "What is the sharpest operator action for this bank right now?"
  );
  const [reflectResponse, setReflectResponse] = useState<ReflectResponse | null>(null);
  const [retainDraft, setRetainDraft] = useState("");
  const [retainTags, setRetainTags] = useState("jio, operator-note");
  const [retainContext, setRetainContext] = useState("");
  const [runningAction, setRunningAction] = useState<
    "recall" | "reflect" | "retain" | "brain" | null
  >(null);
  const [brainActionNote, setBrainActionNote] = useState<string>("");

  const loadIdRef = useRef(0);

  useEffect(() => {
    const saved = window.localStorage.getItem(COCKPIT_THEME_KEY);
    if (saved === "monsoon" || saved === "midnight") {
      setCockpitTheme(saved);
    }
  }, []);

  useEffect(() => {
    window.localStorage.setItem(COCKPIT_THEME_KEY, cockpitTheme);
  }, [cockpitTheme]);

  useEffect(() => {
    setRecallResponse(null);
    setReflectResponse(null);
    setSelectedNodeId(null);
    setBrainActionNote("");
    setSelectedMentalModelId("");
  }, [bankId]);

  const refreshCockpit = useCallback(
    async (options?: { silent?: boolean }) => {
      if (!bankId) return;
      const requestId = ++loadIdRef.current;
      if (!options?.silent) {
        setIsRefreshing(true);
      }
      setPartialErrors({});

      const tasks: Array<[keyof CockpitSnapshot, Promise<any>]> = [
        ["status", features?.brain_runtime ? client.getBrainStatus(bankId) : Promise.resolve(null)],
        [
          "influence",
          features?.brain_runtime
            ? client.getBrainInfluence(bankId, {
                window_days: windowDays,
                top_k: topK,
                entity_type: entityType,
              })
            : Promise.resolve(null),
        ],
        [
          "predictions",
          features?.sub_routine && features?.brain_runtime
            ? client.getSubRoutinePredictions(bankId, horizonHours)
            : Promise.resolve(null),
        ],
        [
          "histogram",
          features?.sub_routine && features?.brain_runtime
            ? client.getSubRoutineHistogram(bankId)
            : Promise.resolve(null),
        ],
        [
          "graph",
          client.getGraphNeighborhood({
            bank_id: bankId,
            surface: "state",
            window_days: windowDays,
            depth: 1,
            limit_nodes: 12,
            limit_edges: 18,
          }),
        ],
        ["directives", client.listDirectives(bankId)],
        ["mentalModels", client.listMentalModels(bankId)],
        ["operations", client.listOperations(bankId, { limit: 8 })],
      ];

      const settled = await Promise.allSettled(tasks.map(([, promise]) => promise));
      if (requestId !== loadIdRef.current) return;

      const nextSnapshot: CockpitSnapshot = {
        status: null,
        influence: null,
        predictions: null,
        histogram: null,
        graph: null,
        directives: null,
        mentalModels: null,
        operations: null,
      };
      const nextErrors: PartialErrors = {};

      settled.forEach((result, index) => {
        const [key] = tasks[index];
        if (result.status === "fulfilled") {
          nextSnapshot[key] = result.value;
        } else {
          nextErrors[key] =
            result.reason instanceof Error ? result.reason.message : "Failed to load";
        }
      });

      setSnapshot(nextSnapshot);
      setPartialErrors(nextErrors);
      setLastUpdatedAt(new Date().toISOString());
      setSelectedMentalModelId(
        (current) => current || nextSnapshot.mentalModels?.items?.[0]?.id || ""
      );
      setIsRefreshing(false);
    },
    [
      bankId,
      entityType,
      features?.brain_runtime,
      features?.sub_routine,
      horizonHours,
      topK,
      windowDays,
    ]
  );

  useEffect(() => {
    if (!bankId) return;
    setSnapshot({
      status: null,
      influence: null,
      predictions: null,
      histogram: null,
      graph: null,
      directives: null,
      mentalModels: null,
      operations: null,
    });
    void refreshCockpit();
  }, [bankId, refreshCockpit]);

  const viewModel = useMemo(() => buildViewModel(snapshot), [snapshot]);
  const recommendations = useMemo(
    () =>
      buildRecommendations({
        snapshot,
        focus: solverFocus,
        recallResponse,
        reflectResponse,
        retainDraft,
      }),
    [snapshot, solverFocus, recallResponse, reflectResponse, retainDraft]
  );

  const graphLayout = useMemo(() => buildGraphLayout(snapshot.graph), [snapshot.graph]);
  const selectedNode =
    graphLayout.nodes.find((entry) => entry.node.id === selectedNodeId)?.node ??
    graphLayout.nodes[0]?.node ??
    null;
  const heatmapRows = useMemo(
    () => makeHeatmapRows(snapshot.influence?.heatmap),
    [snapshot.influence]
  );
  const rawTrendPath = useMemo(
    () =>
      makeTrendPath(
        viewModel.chartPoints.map((point) => ({ x: point.x, y: point.raw })),
        380,
        180
      ),
    [viewModel.chartPoints]
  );
  const ewmaTrendPath = useMemo(
    () =>
      makeTrendPath(
        viewModel.chartPoints.map((point) => ({ x: point.x, y: point.ewma })),
        380,
        180
      ),
    [viewModel.chartPoints]
  );

  const shellTheme = cockpitTheme === "midnight";
  const shellClasses = shellTheme
    ? "border-white/10 bg-slate-950 text-slate-100"
    : "border-sky-200/70 bg-slate-50 text-slate-900";
  const shellBackground = shellTheme
    ? "radial-gradient(circle at top left, rgba(34,197,94,0.12), transparent 26%), radial-gradient(circle at top right, rgba(56,189,248,0.12), transparent 24%), linear-gradient(180deg, #020617, #0f172a 48%, #111827)"
    : "radial-gradient(circle at top left, rgba(2,132,199,0.16), transparent 28%), radial-gradient(circle at top right, rgba(14,165,233,0.14), transparent 22%), linear-gradient(180deg, rgba(240,249,255,0.96), rgba(248,250,252,0.98))";

  const handleRecall = async () => {
    if (!bankId || !recallQuery.trim()) return;
    setRunningAction("recall");
    try {
      const response = (await client.recall({
        bank_id: bankId,
        query: recallQuery.trim(),
        trace: true,
        budget: "mid",
        max_tokens: 4096,
        include: {
          entities: { max_tokens: 350 },
          chunks: { max_tokens: 1800 },
        },
      })) as RecallResultPayload;
      setRecallResponse(response);
      toast.success("Recall refreshed");
    } finally {
      setRunningAction(null);
    }
  };

  const handleReflect = async () => {
    if (!bankId || !reflectQuery.trim()) return;
    setRunningAction("reflect");
    try {
      const response = await client.reflect({
        bank_id: bankId,
        query: reflectQuery.trim(),
        budget: "mid",
        include_facts: true,
        include_tool_calls: true,
      });
      setReflectResponse(response);
      toast.success("Reflection updated");
    } finally {
      setRunningAction(null);
    }
  };

  const handleRetain = async () => {
    if (!bankId || !retainDraft.trim()) return;
    setRunningAction("retain");
    try {
      await client.retain({
        bank_id: bankId,
        items: [
          {
            content: retainDraft.trim(),
            context: retainContext.trim() || undefined,
            tags: parseTags(retainTags),
          },
        ],
      });
      toast.success("Memory retained");
      setRetainDraft("");
      setRetainContext("");
      await refreshCockpit({ silent: true });
    } finally {
      setRunningAction(null);
    }
  };

  const handleRunSubRoutine = async () => {
    if (!bankId) return;
    setRunningAction("brain");
    try {
      const result = await client.triggerSubRoutine(bankId, {
        mode: "incremental",
        horizon_hours: horizonHours,
      });
      setBrainActionNote(`Queued sub-routine ${result.operation_id.slice(0, 8)}...`);
      toast.success("Sub-routine queued");
      await refreshCockpit({ silent: true });
    } finally {
      setRunningAction(null);
    }
  };

  const handleRefreshMentalModel = async () => {
    if (!bankId || !selectedMentalModelId) return;
    setRunningAction("brain");
    try {
      const result = await client.refreshMentalModel(bankId, selectedMentalModelId);
      setBrainActionNote(`Queued mental model refresh ${result.operation_id.slice(0, 8)}...`);
      toast.success("Mental model refresh queued");
      await refreshCockpit({ silent: true });
    } finally {
      setRunningAction(null);
    }
  };

  if (!bankId) {
    return (
      <Card className="border-dashed">
        <CardContent className="flex min-h-[320px] flex-col items-center justify-center gap-4 py-16 text-center">
          <Brain className="h-12 w-12 text-muted-foreground" />
          <div>
            <h2 className="text-2xl font-semibold text-foreground">No bank selected</h2>
            <p className="mt-2 max-w-xl text-sm text-muted-foreground">
              Pick a bank from the global selector to open the Jio Brain cockpit. The page uses the
              selected bank as the only source of truth for recall, reflect, retain, and brain
              runtime surfaces.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div
        className={cn("relative overflow-hidden rounded-[28px] border p-4 md:p-6", shellClasses)}
        style={{ backgroundImage: shellBackground }}
      >
        <div className="pointer-events-none absolute inset-0 opacity-70">
          <div
            className={cn(
              "absolute -left-16 top-10 h-40 w-40 rounded-full blur-3xl",
              shellTheme ? "bg-cyan-500/10" : "bg-sky-300/30"
            )}
          />
          <div
            className={cn(
              "absolute right-0 top-0 h-48 w-48 rounded-full blur-3xl",
              shellTheme ? "bg-emerald-500/10" : "bg-cyan-200/40"
            )}
          />
        </div>

        <div className="relative">
          <div
            className={cn(
              "sticky top-4 z-20 mb-6 rounded-3xl border px-4 py-4 backdrop-blur",
              shellTheme ? "border-white/10 bg-slate-900/70" : "border-sky-200/80 bg-white/80"
            )}
          >
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.24em]">
                  <MiniBadge theme={cockpitTheme} tone={viewModel.pulseTone}>
                    {viewModel.pulseLabel}
                  </MiniBadge>
                  <span className={cn(shellTheme ? "text-slate-500" : "text-slate-500")}>
                    Jio India shell
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap items-start gap-3">
                  <div>
                    <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">
                      Jio Brain Cockpit
                    </h1>
                    <p
                      className={cn(
                        "mt-2 max-w-3xl text-sm md:text-base",
                        shellTheme ? "text-slate-400" : "text-slate-600"
                      )}
                    >
                      Live command surface for{" "}
                      <span className="font-medium text-current">{bankId}</span>. The shell speaks
                      in Jio-style operator language, but every number and action below is driven by
                      the selected bank.
                    </p>
                  </div>
                  <Button
                    asChild
                    variant="outline"
                    className={cn(
                      shellTheme
                        ? "border-white/15 bg-white/5 text-slate-100 hover:bg-white/10"
                        : ""
                    )}
                  >
                    <Link href={`/banks/${bankId}?view=brain`}>Back to Brain</Link>
                  </Button>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <label className="text-sm">
                  <span
                    className={cn(
                      "mb-1 block text-xs uppercase tracking-[0.18em]",
                      shellTheme ? "text-slate-500" : "text-slate-500"
                    )}
                  >
                    Window days
                  </span>
                  <Input
                    type="number"
                    min={1}
                    max={90}
                    value={windowDays}
                    onChange={(event) => setWindowDays(Number(event.target.value || 14))}
                    className={cn(shellTheme ? "border-white/10 bg-white/5" : "bg-white")}
                  />
                </label>
                <label className="text-sm">
                  <span
                    className={cn(
                      "mb-1 block text-xs uppercase tracking-[0.18em]",
                      shellTheme ? "text-slate-500" : "text-slate-500"
                    )}
                  >
                    Top K
                  </span>
                  <Input
                    type="number"
                    min={5}
                    max={50}
                    value={topK}
                    onChange={(event) => setTopK(Number(event.target.value || 12))}
                    className={cn(shellTheme ? "border-white/10 bg-white/5" : "bg-white")}
                  />
                </label>
                <label className="text-sm">
                  <span
                    className={cn(
                      "mb-1 block text-xs uppercase tracking-[0.18em]",
                      shellTheme ? "text-slate-500" : "text-slate-500"
                    )}
                  >
                    Horizon hours
                  </span>
                  <Input
                    type="number"
                    min={1}
                    max={72}
                    value={horizonHours}
                    onChange={(event) => setHorizonHours(Number(event.target.value || 24))}
                    className={cn(shellTheme ? "border-white/10 bg-white/5" : "bg-white")}
                  />
                </label>
                <label className="text-sm">
                  <span
                    className={cn(
                      "mb-1 block text-xs uppercase tracking-[0.18em]",
                      shellTheme ? "text-slate-500" : "text-slate-500"
                    )}
                  >
                    Entity lane
                  </span>
                  <select
                    value={entityType}
                    onChange={(event) => setEntityType(event.target.value as EntityTypeFilter)}
                    className={cn(
                      "flex h-10 w-full rounded-md border px-3 py-2 text-sm",
                      shellTheme
                        ? "border-white/10 bg-white/5 text-slate-100"
                        : "border-input bg-white text-slate-900"
                    )}
                  >
                    <option value="all">all</option>
                    <option value="memory">memory</option>
                    <option value="chunk">chunk</option>
                    <option value="mental_model">mental_model</option>
                  </select>
                </label>
              </div>
            </div>

            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-4">
              <div className="flex flex-wrap items-center gap-2">
                <MiniBadge theme={cockpitTheme} tone={viewModel.pulseTone}>
                  {viewModel.pulseCopy}
                </MiniBadge>
                <MiniBadge theme={cockpitTheme} tone="neutral">
                  Updated {lastUpdatedAt ? formatDateTime(lastUpdatedAt) : "just now"}
                </MiniBadge>
                {partialErrors.influence && (
                  <MiniBadge theme={cockpitTheme} tone="warn">
                    influence degraded
                  </MiniBadge>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className={cn(
                    shellTheme ? "border-white/15 bg-white/5 text-slate-100 hover:bg-white/10" : ""
                  )}
                  onClick={() =>
                    setCockpitTheme((current) => (current === "midnight" ? "monsoon" : "midnight"))
                  }
                >
                  {cockpitTheme === "midnight" ? "Monsoon mode" : "Midnight mode"}
                </Button>
                <Button
                  size="sm"
                  className={cn(
                    shellTheme
                      ? "bg-emerald-500 text-slate-950 hover:bg-emerald-400"
                      : "bg-sky-600 text-white hover:bg-sky-500"
                  )}
                  onClick={() => void refreshCockpit()}
                  disabled={isRefreshing}
                >
                  {isRefreshing ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="mr-2 h-4 w-4" />
                  )}
                  Refresh cockpit
                </Button>
              </div>
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.65fr)_360px]">
            <div className="space-y-6">
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {viewModel.kpis.map((kpi) => (
                  <PanelFrame
                    key={kpi.label}
                    title={kpi.label}
                    body={kpi.note}
                    theme={cockpitTheme}
                    className={toneClasses(cockpitTheme, kpi.tone)}
                  >
                    <div className="flex items-end justify-between gap-3">
                      <div className="text-lg font-semibold tracking-tight">{kpi.value}</div>
                      <ArrowUpRight
                        className={cn("h-4 w-4", shellTheme ? "text-slate-500" : "text-slate-400")}
                      />
                    </div>
                  </PanelFrame>
                ))}
              </div>

              <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
                <PanelFrame
                  title="Jio memory lattice"
                  body="Live graph neighborhood for the selected bank. Click a node to anchor the detail lane."
                  theme={cockpitTheme}
                >
                  {snapshot.graph ? (
                    <div className="space-y-4">
                      <svg
                        viewBox="0 0 100 100"
                        className="h-[340px] w-full rounded-3xl border border-white/10 bg-black/10 p-3"
                      >
                        {graphLayout.edges.map((edge) => {
                          const source = graphLayout.nodes.find(
                            (entry) => entry.node.id === edge.source
                          );
                          const target = graphLayout.nodes.find(
                            (entry) => entry.node.id === edge.target
                          );
                          if (!source || !target) return null;
                          return (
                            <line
                              key={edge.id}
                              x1={source.x}
                              y1={source.y}
                              x2={target.x}
                              y2={target.y}
                              stroke={shellTheme ? "rgba(148,163,184,0.35)" : "rgba(51,65,85,0.28)"}
                              strokeWidth={Math.min(2.2, Math.max(0.8, edge.width))}
                              strokeDasharray={edge.dashed ? "2 2" : undefined}
                            />
                          );
                        })}
                        {graphLayout.nodes.map((entry) => {
                          const selected = entry.node.id === selectedNode?.id;
                          const toneColor =
                            entry.node.status_tone === "contradictory"
                              ? "#fb7185"
                              : entry.node.status_tone === "changed"
                                ? "#f59e0b"
                                : entry.node.status_tone === "stable"
                                  ? "#34d399"
                                  : entry.node.status_tone === "stale"
                                    ? "#f97316"
                                    : shellTheme
                                      ? "#38bdf8"
                                      : "#0284c7";
                          return (
                            <g
                              key={entry.node.id}
                              onClick={() => setSelectedNodeId(entry.node.id)}
                              className="cursor-pointer"
                            >
                              <circle
                                cx={entry.x}
                                cy={entry.y}
                                r={selected ? 8.5 : 6.8}
                                fill={toneColor}
                                fillOpacity={selected ? 0.92 : 0.8}
                                stroke={selected ? "#ffffff" : toneColor}
                                strokeOpacity={selected ? 0.9 : 0.3}
                                strokeWidth={selected ? 0.8 : 0.2}
                              />
                              <text
                                x={entry.x}
                                y={entry.y + 11}
                                textAnchor="middle"
                                fontSize="3.2"
                                fill={shellTheme ? "#e2e8f0" : "#0f172a"}
                              >
                                {entry.node.title.slice(0, 18)}
                              </text>
                            </g>
                          );
                        })}
                      </svg>

                      {selectedNode && (
                        <div
                          className={cn(
                            "rounded-2xl border p-4",
                            shellTheme
                              ? "border-white/10 bg-white/[0.04]"
                              : "border-sky-100 bg-white/80"
                          )}
                        >
                          <div className="flex flex-wrap items-start justify-between gap-3">
                            <div>
                              <h3 className="text-lg font-semibold">{selectedNode.title}</h3>
                              <p
                                className={cn(
                                  "mt-1 text-sm",
                                  shellTheme ? "text-slate-400" : "text-slate-600"
                                )}
                              >
                                {selectedNode.preview ||
                                  selectedNode.subtitle ||
                                  selectedNode.meta ||
                                  "No extra preview on this node yet."}
                              </p>
                            </div>
                            <MiniBadge
                              theme={cockpitTheme}
                              tone={
                                selectedNode.status_tone === "contradictory"
                                  ? "critical"
                                  : selectedNode.status_tone === "changed"
                                    ? "warn"
                                    : "good"
                              }
                            >
                              {selectedNode.status_label ||
                                selectedNode.kind_label ||
                                selectedNode.node_type}
                            </MiniBadge>
                          </div>
                          <div className="mt-4 grid gap-3 md:grid-cols-3">
                            <MiniBadge theme={cockpitTheme} tone="neutral">
                              confidence {selectedNode.confidence?.toFixed(2) ?? "--"}
                            </MiniBadge>
                            <MiniBadge theme={cockpitTheme} tone="neutral">
                              evidence {selectedNode.evidence_count ?? 0}
                            </MiniBadge>
                            <MiniBadge theme={cockpitTheme} tone="neutral">
                              {selectedNode.timestamp_label || "no timestamp"}
                            </MiniBadge>
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div
                      className={cn(
                        "rounded-2xl border border-dashed p-8 text-sm",
                        shellTheme
                          ? "border-white/10 text-slate-400"
                          : "border-sky-200 text-slate-600"
                      )}
                    >
                      Graph neighborhood could not be loaded for this bank.
                    </div>
                  )}
                </PanelFrame>

                <div className="space-y-6">
                  <PanelFrame
                    title="Circle load map"
                    body="Hourly demand and recall pressure by weekday. The shell calls it circles; the data comes straight from bank influence heatmap."
                    theme={cockpitTheme}
                  >
                    <div className="space-y-3">
                      <div className="overflow-x-auto">
                        <div
                          className="grid min-w-[620px] gap-1"
                          style={{ gridTemplateColumns: "50px repeat(24, minmax(0, 1fr))" }}
                        >
                          <div />
                          {Array.from({ length: 24 }, (_, index) => (
                            <div
                              key={`hour-${index}`}
                              className={cn(
                                "text-center text-[10px]",
                                shellTheme ? "text-slate-500" : "text-slate-500"
                              )}
                            >
                              {String(index).padStart(2, "0")}
                            </div>
                          ))}
                          {heatmapRows.map((row, rowIndex) => (
                            <FragmentRow
                              key={DAYS[rowIndex]}
                              dayLabel={DAYS[rowIndex]}
                              row={row}
                              theme={cockpitTheme}
                            />
                          ))}
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <MiniBadge theme={cockpitTheme} tone="neutral">
                          peak forecast {viewModel.topPredictionHour}
                        </MiniBadge>
                        <MiniBadge theme={cockpitTheme} tone="good">
                          histogram peak {viewModel.topHistogramHour}
                        </MiniBadge>
                      </div>
                    </div>
                  </PanelFrame>

                  <PanelFrame
                    title="Influence drift"
                    body="Raw influence, smoothed influence, and anomaly markers in one browser-native chart."
                    theme={cockpitTheme}
                  >
                    {viewModel.chartPoints.length > 1 ? (
                      <svg viewBox="0 0 380 180" className="h-[200px] w-full">
                        <path
                          d={rawTrendPath}
                          fill="none"
                          stroke={shellTheme ? "#38bdf8" : "#0284c7"}
                          strokeWidth="2"
                          opacity="0.55"
                        />
                        <path
                          d={ewmaTrendPath}
                          fill="none"
                          stroke={shellTheme ? "#34d399" : "#059669"}
                          strokeWidth="2.5"
                        />
                        {viewModel.chartPoints.map((point, index) => {
                          if (!point.anomaly) return null;
                          const x =
                            10 + (index / Math.max(1, viewModel.chartPoints.length - 1)) * 360;
                          const minY = Math.min(...viewModel.chartPoints.map((item) => item.ewma));
                          const maxY = Math.max(...viewModel.chartPoints.map((item) => item.ewma));
                          const y =
                            maxY === minY
                              ? 90
                              : 170 - ((point.ewma - minY) / Math.max(1e-6, maxY - minY)) * 160;
                          return (
                            <circle
                              key={`anomaly-${point.x}`}
                              cx={x}
                              cy={y}
                              r="4.5"
                              fill="#fb7185"
                            />
                          );
                        })}
                      </svg>
                    ) : (
                      <div
                        className={cn(
                          "rounded-2xl border border-dashed p-8 text-sm",
                          shellTheme
                            ? "border-white/10 text-slate-400"
                            : "border-sky-200 text-slate-600"
                        )}
                      >
                        Not enough trend points yet for a live drift chart.
                      </div>
                    )}
                    <div className="mt-4 flex flex-wrap gap-2">
                      <MiniBadge theme={cockpitTheme} tone="warn">
                        anomalies {viewModel.anomalyCount}
                      </MiniBadge>
                      <MiniBadge theme={cockpitTheme} tone="neutral">
                        top influence {viewModel.topInfluenceLabel.slice(0, 36)}
                      </MiniBadge>
                    </div>
                  </PanelFrame>
                </div>
              </div>

              <PanelFrame
                title="Operator lanes"
                body="Use the same bank context for search, reasoning, capture, and brain operations. This replaces the simulated DITL actions with real bank writes and reads."
                theme={cockpitTheme}
              >
                <Tabs defaultValue="recall" className="w-full">
                  <TabsList
                    className={cn(
                      "mb-4 h-auto w-full justify-start gap-1 overflow-x-auto rounded-2xl p-1",
                      shellTheme ? "bg-white/5" : "bg-sky-100/70"
                    )}
                  >
                    <TabsTrigger value="recall">Signal search</TabsTrigger>
                    <TabsTrigger value="reflect">Reasoning console</TabsTrigger>
                    <TabsTrigger value="retain">Capture pulse</TabsTrigger>
                    <TabsTrigger value="brain">Brain ops</TabsTrigger>
                  </TabsList>

                  <TabsContent value="recall" className="space-y-4">
                    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
                      <Input
                        value={recallQuery}
                        onChange={(event) => setRecallQuery(event.target.value)}
                        placeholder="Search the live bank for the sharpest change, risk, or cluster"
                        className={cn(shellTheme ? "border-white/10 bg-white/5" : "bg-white")}
                      />
                      <Button
                        onClick={() => void handleRecall()}
                        disabled={runningAction === "recall" || !recallQuery.trim()}
                        className={cn(
                          shellTheme
                            ? "bg-cyan-400 text-slate-950 hover:bg-cyan-300"
                            : "bg-sky-600 text-white hover:bg-sky-500"
                        )}
                      >
                        {runningAction === "recall" ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <Search className="mr-2 h-4 w-4" />
                        )}
                        Run recall
                      </Button>
                    </div>

                    {recallResponse ? (
                      <div className="grid gap-3">
                        {(recallResponse.results ?? []).slice(0, 5).map((item, index) => (
                          <div
                            key={`${item.id ?? item.node_id ?? index}`}
                            className={cn(
                              "rounded-2xl border p-4",
                              shellTheme
                                ? "border-white/10 bg-white/[0.04]"
                                : "border-sky-100 bg-white/80"
                            )}
                          >
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div>
                                <div className="text-sm font-medium">
                                  {item.text ?? item.title ?? "Untitled memory"}
                                </div>
                                <p
                                  className={cn(
                                    "mt-1 text-sm",
                                    shellTheme ? "text-slate-400" : "text-slate-600"
                                  )}
                                >
                                  {item.context ??
                                    item.preview ??
                                    item.reason ??
                                    "No additional preview available."}
                                </p>
                              </div>
                              <MiniBadge theme={cockpitTheme} tone="neutral">
                                {item.type ?? item.fact_type ?? "memory"}
                              </MiniBadge>
                            </div>
                          </div>
                        ))}
                        <div className="flex flex-wrap gap-2">
                          <MiniBadge theme={cockpitTheme} tone="good">
                            {recallResponse.results.length} recall hits
                          </MiniBadge>
                          <MiniBadge theme={cockpitTheme} tone="neutral">
                            {(recallResponse.entities ?? []).length} entities
                          </MiniBadge>
                          <MiniBadge theme={cockpitTheme} tone="neutral">
                            {(recallResponse.chunks ?? []).length} chunks
                          </MiniBadge>
                        </div>
                      </div>
                    ) : (
                      <EmptyLane
                        theme={cockpitTheme}
                        copy="Run recall to populate the live evidence lane."
                      />
                    )}
                  </TabsContent>

                  <TabsContent value="reflect" className="space-y-4">
                    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto]">
                      <Textarea
                        value={reflectQuery}
                        onChange={(event) => setReflectQuery(event.target.value)}
                        placeholder="Ask for the strongest operator action, root cause, or leverage point"
                        className={cn(
                          "min-h-[110px]",
                          shellTheme ? "border-white/10 bg-white/5" : "bg-white"
                        )}
                      />
                      <Button
                        onClick={() => void handleReflect()}
                        disabled={runningAction === "reflect" || !reflectQuery.trim()}
                        className={cn(
                          shellTheme
                            ? "bg-emerald-400 text-slate-950 hover:bg-emerald-300"
                            : "bg-emerald-600 text-white hover:bg-emerald-500"
                        )}
                      >
                        {runningAction === "reflect" ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <Sparkles className="mr-2 h-4 w-4" />
                        )}
                        Run reflect
                      </Button>
                    </div>

                    {reflectResponse ? (
                      <div className="space-y-4">
                        <div
                          className={cn(
                            "rounded-2xl border p-4 text-sm leading-7",
                            shellTheme
                              ? "border-white/10 bg-white/[0.04] text-slate-200"
                              : "border-sky-100 bg-white/80 text-slate-800"
                          )}
                        >
                          {reflectResponse.text || "Reflect returned an empty response."}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <MiniBadge theme={cockpitTheme} tone="good">
                            facts {(reflectResponse.based_on?.memories ?? []).length}
                          </MiniBadge>
                          <MiniBadge theme={cockpitTheme} tone="neutral">
                            models {(reflectResponse.based_on?.mental_models ?? []).length}
                          </MiniBadge>
                          <MiniBadge theme={cockpitTheme} tone="neutral">
                            directives {(reflectResponse.based_on?.directives ?? []).length}
                          </MiniBadge>
                          <MiniBadge theme={cockpitTheme} tone="warn">
                            tokens {formatCompactNumber(reflectResponse.usage?.total_tokens ?? 0)}
                          </MiniBadge>
                        </div>
                      </div>
                    ) : (
                      <EmptyLane
                        theme={cockpitTheme}
                        copy="Run reflect to turn the live bank state into one operator-ready answer."
                      />
                    )}
                  </TabsContent>

                  <TabsContent value="retain" className="space-y-4">
                    <Textarea
                      value={retainDraft}
                      onChange={(event) => setRetainDraft(event.target.value)}
                      placeholder="Capture a fresh operator note, investigation finding, or Jio-style lane update"
                      className={cn(
                        "min-h-[140px]",
                        shellTheme ? "border-white/10 bg-white/5" : "bg-white"
                      )}
                    />
                    <div className="grid gap-4 md:grid-cols-2">
                      <Input
                        value={retainTags}
                        onChange={(event) => setRetainTags(event.target.value)}
                        placeholder="Comma-separated tags"
                        className={cn(shellTheme ? "border-white/10 bg-white/5" : "bg-white")}
                      />
                      <Input
                        value={retainContext}
                        onChange={(event) => setRetainContext(event.target.value)}
                        placeholder="Optional context"
                        className={cn(shellTheme ? "border-white/10 bg-white/5" : "bg-white")}
                      />
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      <Button
                        onClick={() => void handleRetain()}
                        disabled={runningAction === "retain" || !retainDraft.trim()}
                        className={cn(
                          shellTheme
                            ? "bg-amber-300 text-slate-950 hover:bg-amber-200"
                            : "bg-amber-500 text-slate-950 hover:bg-amber-400"
                        )}
                      >
                        {runningAction === "retain" ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <Upload className="mr-2 h-4 w-4" />
                        )}
                        Retain into bank
                      </Button>
                      <MiniBadge theme={cockpitTheme} tone="neutral">
                        bank {bankId}
                      </MiniBadge>
                    </div>
                  </TabsContent>

                  <TabsContent value="brain" className="space-y-4">
                    <div className="grid gap-4 md:grid-cols-2">
                      <Button
                        onClick={() => void handleRunSubRoutine()}
                        disabled={runningAction === "brain" || !features?.sub_routine}
                        className={cn(
                          shellTheme
                            ? "bg-violet-300 text-slate-950 hover:bg-violet-200"
                            : "bg-violet-600 text-white hover:bg-violet-500"
                        )}
                      >
                        {runningAction === "brain" ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : (
                          <Workflow className="mr-2 h-4 w-4" />
                        )}
                        Run sub-routine
                      </Button>
                      <div className="space-y-2">
                        <select
                          value={selectedMentalModelId}
                          onChange={(event) => setSelectedMentalModelId(event.target.value)}
                          className={cn(
                            "flex h-10 w-full rounded-md border px-3 py-2 text-sm",
                            shellTheme
                              ? "border-white/10 bg-white/5 text-slate-100"
                              : "border-input bg-white text-slate-900"
                          )}
                        >
                          <option value="">Select mental model</option>
                          {(snapshot.mentalModels?.items ?? []).map((model) => (
                            <option key={model.id} value={model.id}>
                              {model.name}
                            </option>
                          ))}
                        </select>
                        <Button
                          variant="outline"
                          onClick={() => void handleRefreshMentalModel()}
                          disabled={runningAction === "brain" || !selectedMentalModelId}
                          className={cn(
                            shellTheme
                              ? "border-white/15 bg-white/5 text-slate-100 hover:bg-white/10"
                              : ""
                          )}
                        >
                          <RefreshCw className="mr-2 h-4 w-4" />
                          Refresh selected model
                        </Button>
                      </div>
                    </div>
                    {brainActionNote ? (
                      <div
                        className={cn(
                          "rounded-2xl border p-3 text-sm",
                          shellTheme
                            ? "border-white/10 bg-white/[0.04] text-slate-300"
                            : "border-sky-100 bg-white/80 text-slate-700"
                        )}
                      >
                        {brainActionNote}
                      </div>
                    ) : (
                      <EmptyLane
                        theme={cockpitTheme}
                        copy="Queue a sub-routine or refresh a mental model to update the live brain lane."
                      />
                    )}
                  </TabsContent>
                </Tabs>
              </PanelFrame>

              <div className="grid gap-6 xl:grid-cols-3">
                <PanelFrame
                  title="Memory deck"
                  body="Stored mental models that can be refreshed and reused across reflect runs."
                  theme={cockpitTheme}
                >
                  <div className="space-y-3">
                    {(snapshot.mentalModels?.items ?? []).slice(0, 4).map((model: MentalModel) => (
                      <button
                        key={model.id}
                        type="button"
                        onClick={() => setSelectedMentalModelId(model.id)}
                        className={cn(
                          "w-full rounded-2xl border p-4 text-left transition",
                          model.id === selectedMentalModelId
                            ? shellTheme
                              ? "border-emerald-400/60 bg-emerald-400/10"
                              : "border-emerald-400/60 bg-emerald-50"
                            : shellTheme
                              ? "border-white/10 bg-white/[0.03] hover:bg-white/[0.06]"
                              : "border-sky-100 bg-white/70 hover:bg-white"
                        )}
                      >
                        <div className="font-medium">{model.name}</div>
                        <p
                          className={cn(
                            "mt-1 text-sm",
                            shellTheme ? "text-slate-400" : "text-slate-600"
                          )}
                        >
                          {model.content.slice(0, 120) || model.source_query}
                        </p>
                      </button>
                    ))}
                    {!snapshot.mentalModels?.items?.length && (
                      <EmptyLane theme={cockpitTheme} copy="No mental models yet for this bank." />
                    )}
                  </div>
                </PanelFrame>

                <PanelFrame
                  title="Guidance spine"
                  body="Directives and policy anchors shaping how reflect should think."
                  theme={cockpitTheme}
                >
                  <div className="space-y-3">
                    {(snapshot.directives?.items ?? []).slice(0, 4).map((directive) => (
                      <div
                        key={directive.id}
                        className={cn(
                          "rounded-2xl border p-4",
                          shellTheme
                            ? "border-white/10 bg-white/[0.03]"
                            : "border-sky-100 bg-white/70"
                        )}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="font-medium">{directive.name}</div>
                          <MiniBadge
                            theme={cockpitTheme}
                            tone={directive.is_active ? "good" : "warn"}
                          >
                            p{directive.priority}
                          </MiniBadge>
                        </div>
                        <p
                          className={cn(
                            "mt-2 text-sm",
                            shellTheme ? "text-slate-400" : "text-slate-600"
                          )}
                        >
                          {directive.content.slice(0, 140)}
                        </p>
                      </div>
                    ))}
                    {!snapshot.directives?.items?.length && (
                      <EmptyLane
                        theme={cockpitTheme}
                        copy="No directives are active for this bank yet."
                      />
                    )}
                  </div>
                </PanelFrame>

                <PanelFrame
                  title="In-flight work"
                  body="Latest bank operations, with special attention on pending background tasks."
                  theme={cockpitTheme}
                >
                  <div className="space-y-3">
                    {(snapshot.operations?.operations ?? []).slice(0, 6).map((operation) => (
                      <div
                        key={operation.id}
                        className={cn(
                          "rounded-2xl border p-4",
                          shellTheme
                            ? "border-white/10 bg-white/[0.03]"
                            : "border-sky-100 bg-white/70"
                        )}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="font-medium">{operation.task_type}</div>
                          <MiniBadge
                            theme={cockpitTheme}
                            tone={
                              operation.status === "failed"
                                ? "critical"
                                : operation.status === "pending"
                                  ? "warn"
                                  : "good"
                            }
                          >
                            {operation.status}
                          </MiniBadge>
                        </div>
                        <p
                          className={cn(
                            "mt-2 text-sm",
                            shellTheme ? "text-slate-400" : "text-slate-600"
                          )}
                        >
                          {formatDateTime(operation.created_at)} · {operation.items_count} item
                          {operation.items_count === 1 ? "" : "s"}
                        </p>
                      </div>
                    ))}
                    {!snapshot.operations?.operations?.length && (
                      <EmptyLane
                        theme={cockpitTheme}
                        copy="No recent operations to show for this bank."
                      />
                    )}
                  </div>
                </PanelFrame>
              </div>
            </div>

            <aside className="lg:sticky lg:top-28 lg:self-start">
              <PanelFrame
                title="Cockpit solver"
                body="Deterministic recommendations fed by live bank signals, not demo-only deltas."
                theme={cockpitTheme}
                actions={
                  <MiniBadge theme={cockpitTheme} tone={recommendations[0]?.tone ?? "neutral"}>
                    biggest lever
                  </MiniBadge>
                }
              >
                <div className="space-y-5">
                  <div className="grid grid-cols-3 gap-2">
                    {(["stability", "growth", "memory"] as SolverFocus[]).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        onClick={() => setSolverFocus(mode)}
                        className={cn(
                          "rounded-2xl border px-3 py-3 text-sm font-medium capitalize transition",
                          solverFocus === mode
                            ? shellTheme
                              ? "border-cyan-400/60 bg-cyan-400/10 text-cyan-100"
                              : "border-sky-500/50 bg-sky-50 text-sky-800"
                            : shellTheme
                              ? "border-white/10 bg-white/[0.03] text-slate-300 hover:bg-white/[0.06]"
                              : "border-sky-100 bg-white/70 text-slate-700 hover:bg-white"
                        )}
                      >
                        {mode}
                      </button>
                    ))}
                  </div>

                  <div
                    className={cn(
                      "rounded-3xl border p-4",
                      shellTheme
                        ? "border-emerald-400/30 bg-emerald-400/10"
                        : "border-emerald-300 bg-emerald-50"
                    )}
                  >
                    <div className="flex items-start gap-3">
                      <div
                        className={cn(
                          "rounded-2xl p-2",
                          shellTheme ? "bg-black/20" : "bg-white/90"
                        )}
                      >
                        <Zap className="h-5 w-5 text-emerald-500" />
                      </div>
                      <div>
                        <div className="font-semibold">
                          {recommendations[0]?.title ?? "No lever yet"}
                        </div>
                        <p
                          className={cn(
                            "mt-1 text-sm",
                            shellTheme ? "text-slate-300" : "text-slate-700"
                          )}
                        >
                          {recommendations[0]?.body ??
                            "Run a bank refresh to surface the first recommendation."}
                        </p>
                        <p
                          className={cn(
                            "mt-3 text-xs uppercase tracking-[0.18em]",
                            shellTheme ? "text-slate-500" : "text-slate-500"
                          )}
                        >
                          {recommendations[0]?.action ?? "Awaiting live bank state"}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-3">
                    {recommendations.map((recommendation, index) => (
                      <div
                        key={recommendation.id}
                        className={cn(
                          "rounded-2xl border p-4",
                          shellTheme
                            ? "border-white/10 bg-white/[0.03]"
                            : "border-sky-100 bg-white/70"
                        )}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="font-medium">
                            {index + 1}. {recommendation.title}
                          </div>
                          <MiniBadge theme={cockpitTheme} tone={recommendation.tone}>
                            {recommendation.score}
                          </MiniBadge>
                        </div>
                        <p
                          className={cn(
                            "mt-2 text-sm",
                            shellTheme ? "text-slate-400" : "text-slate-600"
                          )}
                        >
                          {recommendation.body}
                        </p>
                        <p
                          className={cn(
                            "mt-3 text-xs",
                            shellTheme ? "text-slate-500" : "text-slate-500"
                          )}
                        >
                          {recommendation.action}
                        </p>
                      </div>
                    ))}
                  </div>

                  <div className="grid gap-3">
                    <StatusRow
                      theme={cockpitTheme}
                      icon={<Activity className="h-4 w-4" />}
                      label="Live pulse"
                      value={viewModel.pulseLabel}
                      tone={viewModel.pulseTone}
                    />
                    <StatusRow
                      theme={cockpitTheme}
                      icon={<Network className="h-4 w-4" />}
                      label="Influence peak"
                      value={viewModel.topInfluenceLabel.slice(0, 36)}
                      tone="good"
                    />
                    <StatusRow
                      theme={cockpitTheme}
                      icon={<Clock3 className="h-4 w-4" />}
                      label="Forecast peak"
                      value={viewModel.topPredictionHour}
                      tone={viewModel.topPredictionScore ? "good" : "warn"}
                    />
                  </div>
                </div>
              </PanelFrame>
            </aside>
          </div>
        </div>
      </div>
    </div>
  );
}

function FragmentRow({
  dayLabel,
  row,
  theme,
}: {
  dayLabel: string;
  row: number[];
  theme: CockpitTheme;
}) {
  const max = Math.max(0.0001, ...row);
  return (
    <>
      <div
        className={cn(
          "py-1 text-[11px] font-medium",
          theme === "midnight" ? "text-slate-400" : "text-slate-600"
        )}
      >
        {dayLabel}
      </div>
      {row.map((value, index) => {
        const alpha = value <= 0 ? 0.08 : 0.18 + (value / max) * 0.72;
        const background =
          theme === "midnight"
            ? `rgba(56, 189, 248, ${alpha})`
            : `rgba(2, 132, 199, ${alpha * 0.75})`;
        return (
          <div
            key={`${dayLabel}-${index}`}
            className="aspect-square rounded-[6px] border"
            style={{
              backgroundColor: background,
              borderColor:
                theme === "midnight" ? "rgba(255,255,255,0.06)" : "rgba(148,163,184,0.16)",
            }}
            title={`${dayLabel} ${String(index).padStart(2, "0")}:00 · score ${value.toFixed(2)}`}
          />
        );
      })}
    </>
  );
}

function EmptyLane({ theme, copy }: { theme: CockpitTheme; copy: string }) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-dashed p-6 text-sm",
        theme === "midnight" ? "border-white/10 text-slate-400" : "border-sky-200 text-slate-600"
      )}
    >
      {copy}
    </div>
  );
}

function StatusRow({
  theme,
  icon,
  label,
  value,
  tone,
}: {
  theme: CockpitTheme;
  icon: React.ReactNode;
  label: string;
  value: string;
  tone: "good" | "warn" | "critical" | "neutral";
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between rounded-2xl border px-3 py-3",
        theme === "midnight" ? "border-white/10 bg-white/[0.03]" : "border-sky-100 bg-white/70"
      )}
    >
      <div className="flex items-center gap-3">
        <div className={cn("rounded-xl p-2", toneClasses(theme, tone))}>{icon}</div>
        <div>
          <div
            className={cn(
              "text-xs uppercase tracking-[0.18em]",
              theme === "midnight" ? "text-slate-500" : "text-slate-500"
            )}
          >
            {label}
          </div>
          <div className="text-sm font-medium">{value}</div>
        </div>
      </div>
      {tone === "good" ? (
        <CheckCircle2 className="h-4 w-4 text-emerald-500" />
      ) : tone === "critical" ? (
        <ShieldAlert className="h-4 w-4 text-rose-500" />
      ) : tone === "warn" ? (
        <AlertTriangle className="h-4 w-4 text-amber-500" />
      ) : (
        <Database className="h-4 w-4 text-slate-400" />
      )}
    </div>
  );
}
