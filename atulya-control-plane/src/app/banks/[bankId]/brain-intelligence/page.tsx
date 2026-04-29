"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { LayoutPanelTop, PanelTopOpen } from "lucide-react";
import { client } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  type TooltipContentProps,
  XAxis,
  YAxis,
} from "recharts";
import dynamic from "next/dynamic";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false }) as any;

// ─── Design tokens (match bank-stats-view palette) ────────────────────────────
const C = {
  raw: "#6366f1", // indigo — raw signal
  ewma: "#f8fafc", // near-white — smooth EWMA line
  band: "#6366f1", // same as raw for confidence band fill
  accent: "#8b5cf6", // purple — bars
  axis: "var(--muted-foreground)",
  grid: "var(--border)",
};

type TrendPoint = { index: number; raw: number; ewma: number; lower: number; upper: number };

// Tooltip shared between charts
type TTP = Partial<TooltipContentProps<number, string>>;
function ChartTooltip({ active, payload, label }: TTP) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border/60 bg-popover/95 backdrop-blur-sm px-3 py-2 shadow-md min-w-[9rem]">
      {label != null && (
        <div className="text-[11px] font-medium text-foreground mb-1.5">Step {label}</div>
      )}
      <div className="space-y-1">
        {payload.map((p, i) => (
          <div key={i} className="flex items-center gap-2 text-[11px]">
            <span
              className="w-2 h-2 rounded-[2px]"
              style={{ backgroundColor: p.color ?? p.stroke }}
            />
            <span className="text-muted-foreground">{p.name}</span>
            <span className="ml-auto pl-3 font-semibold tabular-nums text-foreground">
              {typeof p.value === "number" ? p.value.toFixed(3) : "—"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function EwmaTrendChart({
  trend,
  anomalies,
}: {
  trend: TrendPoint[];
  anomalies: Array<{ index: number; score: number; zscore: number; iqr?: boolean }>;
}) {
  // Flatten upper/lower into same rows for AreaChart fill trick
  const chartData = trend.map((p) => ({
    i: p.index,
    raw: p.raw,
    ewma: p.ewma,
    bandLow: p.lower,
    // recharts area fill: we need bandHigh relative to bandLow
    bandRange: Math.max(0, p.upper - p.lower),
    anomaly: anomalies.find((a) => a.index === p.index) ? p.raw : undefined,
  }));

  const yMin = Math.min(...trend.map((p) => p.lower));
  const yMax = Math.max(...trend.map((p) => p.upper));
  const yPad = (yMax - yMin) * 0.08;

  // Summary stats
  const first = trend[0]?.ewma ?? 0;
  const last = trend[trend.length - 1]?.ewma ?? 0;
  const delta = last - first;
  const direction = delta > 0.01 * first ? "rising" : delta < -0.01 * first ? "falling" : "stable";
  const dirColor =
    direction === "rising" ? "#10b981" : direction === "falling" ? "#ef4444" : "#6b7280";

  return (
    <div className="space-y-3">
      {/* Header row */}
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-foreground">EWMA Trend</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Smoothed signal line to show direction without noisy spikes.
          </p>
        </div>
        <div className="text-right shrink-0">
          <span className="text-xs font-medium" style={{ color: dirColor }}>
            {direction}
          </span>
          <span className="text-xs text-muted-foreground ml-2">·</span>
          <span className="text-xs text-muted-foreground ml-2">now {(last * 100).toFixed(0)}%</span>
          <span className="text-xs text-muted-foreground ml-2">·</span>
          <span className="text-xs tabular-nums" style={{ color: dirColor }}>
            {delta >= 0 ? "+" : ""}
            {(delta * 100).toFixed(0)} pts
          </span>
        </div>
      </div>

      {/* Chart */}
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
            <defs>
              <linearGradient id="ewmaGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={C.raw} stopOpacity={0.18} />
                <stop offset="95%" stopColor={C.raw} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={C.grid} strokeDasharray="3 3" strokeOpacity={0.4} />
            <XAxis
              dataKey="i"
              tick={{ fill: C.axis, fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: C.grid }}
              label={{
                value: "Step",
                position: "insideBottomRight",
                offset: -4,
                fill: C.axis,
                fontSize: 10,
              }}
            />
            <YAxis
              domain={[yMin - yPad, yMax + yPad]}
              tick={{ fill: C.axis, fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              width={42}
              tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
            />
            <Tooltip content={<ChartTooltip />} cursor={{ stroke: C.grid }} />

            {/* Confidence band — stacked area trick */}
            <Area
              dataKey="bandLow"
              stroke="none"
              fill="none"
              legendType="none"
              name="band floor"
              isAnimationActive={false}
            />
            <Area
              dataKey="bandRange"
              stackId="band"
              stroke="none"
              fill={C.band}
              fillOpacity={0.1}
              name="Confidence band"
              isAnimationActive={false}
            />

            {/* Raw signal */}
            <Area
              dataKey="raw"
              stroke={C.raw}
              strokeWidth={1.5}
              fill="url(#ewmaGrad)"
              dot={false}
              name="Raw"
              strokeOpacity={0.7}
              isAnimationActive={false}
            />

            {/* EWMA smooth line */}
            <Line
              type="monotone"
              dataKey="ewma"
              stroke={C.ewma}
              strokeWidth={2.5}
              dot={false}
              activeDot={{ r: 4, fill: C.ewma, strokeWidth: 0 }}
              name="EWMA"
              isAnimationActive={false}
            />

            {/* Anomaly markers */}
            {anomalies.map((a) => (
              <ReferenceDot
                key={a.index}
                x={a.index}
                y={chartData.find((d) => d.i === a.index)?.raw ?? 0}
                r={5}
                fill="#ef4444"
                stroke="var(--background)"
                strokeWidth={1.5}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <p className="text-[11px] text-muted-foreground">
        <span className="font-medium text-foreground/80">How to read:</span> Upward slope means
        influence momentum is increasing, flat means stable, downward means cooling down.
        {anomalies.length > 0 && (
          <span className="ml-2 text-[#ef4444]">
            ● {anomalies.length} anomal{anomalies.length === 1 ? "y" : "ies"} flagged
            {anomalies.some((a) => a.iqr) ? " (z-score + IQR)" : " (z-score)"}
          </span>
        )}
      </p>
    </div>
  );
}

type BrainInfluencePayload = {
  entity_type: string;
  heatmap: Array<{ weekday: number; hour_utc: number; score: number }>;
  trend: Array<{ index: number; raw: number; ewma: number; lower: number; upper: number }>;
  leaderboard: Array<{
    id: string;
    type: string;
    text: string;
    access_count: number;
    influence_score: number;
    contribution: { recency: number; freq: number; graph: number; rerank: number; dream: number };
  }>;
  anomalies: Array<{ index: number; score: number; zscore: number; iqr?: boolean }>;
};

export default function BrainIntelligencePage() {
  const params = useParams<{ bankId: string }>();
  const bankId = params?.bankId;
  const [windowDays, setWindowDays] = useState(14);
  const [topK, setTopK] = useState(20);
  const [entityType, setEntityType] = useState<"all" | "memory" | "chunk" | "mental_model">("all");
  const [data, setData] = useState<BrainInfluencePayload | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorText, setErrorText] = useState("");

  useEffect(() => {
    if (!bankId) return;
    let cancelled = false;
    setIsLoading(true);
    setErrorText("");
    client
      .getBrainInfluence(bankId, { window_days: windowDays, top_k: topK, entity_type: entityType })
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled)
          setErrorText(err instanceof Error ? err.message : "Failed to load analytics");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [bankId, windowDays, topK, entityType]);

  const heatmapZ = useMemo(() => {
    if (!data?.heatmap) return Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => 0));
    const z = Array.from({ length: 7 }, () => Array.from({ length: 24 }, () => 0));
    for (const cell of data.heatmap) z[cell.weekday][cell.hour_utc] = cell.score;
    return z;
  }, [data]);

  const contributionStack = useMemo(() => {
    const rows = data?.leaderboard ?? [];
    return {
      x: rows.map((r) => (r.text || "item").slice(0, 26)),
      recency: rows.map((r) => r.contribution.recency),
      freq: rows.map((r) => r.contribution.freq),
      graph: rows.map((r) => r.contribution.graph),
      rerank: rows.map((r) => r.contribution.rerank),
      dream: rows.map((r) => r.contribution.dream),
    };
  }, [data]);

  const leaderboardTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const row of data?.leaderboard ?? []) {
      counts[row.type] = (counts[row.type] || 0) + 1;
    }
    return counts;
  }, [data]);

  const decisionPanelUrl = `/banks/${bankId}/brain-intelligence/customer-panel`;
  const brainTemplateUrl = `/banks/${bankId}/brain-intelligence/brain-template`;

  const openDecisionPanelPopup = () => {
    if (typeof window === "undefined") return;
    window.open(
      decisionPanelUrl,
      "customer-centric-decision-panel",
      "popup=yes,width=1680,height=980,resizable=yes,scrollbars=yes"
    );
  };

  const openBrainTemplatePopup = () => {
    if (typeof window === "undefined") return;
    window.open(
      brainTemplateUrl,
      "brain-html-simulation-panel",
      "popup=yes,width=1720,height=1020,resizable=yes,scrollbars=yes"
    );
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-foreground">Brain Intelligence</h1>
          <p className="text-sm text-muted-foreground">
            Math-first influence analytics with explainable factors and anomaly-aware trending.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline">
            <Link href={`/banks/${bankId}?view=brain`}>Back to Brain</Link>
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-base font-semibold text-foreground">Choose Workspace</h2>
              <p className="text-sm text-muted-foreground">
                Open the view you want. The main buttons stay in this tab. Separate-window options
                are shown only if you explicitly want them.
              </p>
            </div>
            <div className="grid gap-3 lg:min-w-[720px] lg:grid-cols-2">
              <div className="rounded-lg border border-border bg-background p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <LayoutPanelTop className="h-4 w-4" />
                  Customer Decision Panel
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  Best for daily use. Opens the live customer-facing cockpit with bank-connected
                  actions and decision support.
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button asChild>
                    <Link href={decisionPanelUrl}>Open Decision Panel</Link>
                  </Button>
                  <Button variant="outline" onClick={openDecisionPanelPopup}>
                    <PanelTopOpen className="mr-2 h-4 w-4" />
                    Open in Separate Window
                  </Button>
                </div>
              </div>

              <div className="rounded-lg border border-border bg-background p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <LayoutPanelTop className="h-4 w-4" />
                  BRAIN Powered Simulated Decision Engine
                </div>
                <p className="mt-2 text-sm text-muted-foreground">
                  Opens the simulated decision engine and decision capture engine. Use this for
                  guided walkthroughs, scenario analysis, and structured decision capture with the
                  preserved `brain.html` experience.
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button asChild variant="outline">
                    <Link href={brainTemplateUrl}>Open Simulated Decision Engine</Link>
                  </Button>
                  <Button variant="ghost" onClick={openBrainTemplatePopup}>
                    <PanelTopOpen className="mr-2 h-4 w-4" />
                    Open in Separate Window
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4 flex gap-3 items-end">
          <label className="text-sm">
            Window (days)
            <input
              className="ml-2 rounded border border-input bg-background px-2 py-1"
              type="number"
              min={1}
              max={90}
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value || 14))}
            />
          </label>
          <label className="text-sm">
            Top K
            <select
              className="ml-2 rounded border border-input bg-background px-2 py-1"
              value={String(topK)}
              onChange={(e) => setTopK(Number(e.target.value || 20))}
            >
              <option value="5">5</option>
              <option value="8">8</option>
              <option value="12">12</option>
              <option value="20">20</option>
              <option value="30">30</option>
              <option value="50">50</option>
            </select>
          </label>
          <label className="text-sm">
            Entity Type
            <select
              className="ml-2 rounded border border-input bg-background px-2 py-1"
              value={entityType}
              onChange={(e) =>
                setEntityType(e.target.value as "all" | "memory" | "chunk" | "mental_model")
              }
            >
              <option value="all">all</option>
              <option value="memory">memory</option>
              <option value="chunk">chunk</option>
              <option value="mental_model">mental_model</option>
            </select>
          </label>
          <span className="text-xs text-muted-foreground">
            {isLoading ? "Loading..." : "Updated"}
          </span>
        </CardContent>
      </Card>

      {Object.keys(leaderboardTypeCounts).length > 0 && (
        <Card>
          <CardContent className="p-4">
            <h2 className="font-semibold mb-2">Leaderboard Type Mix</h2>
            <div className="flex flex-wrap gap-2">
              {Object.entries(leaderboardTypeCounts).map(([type, count]) => (
                <span
                  key={type}
                  className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground"
                >
                  {type}: {count}
                </span>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {errorText && (
        <div className="text-xs text-amber-600 dark:text-amber-300 border border-amber-500/30 rounded-md px-3 py-2">
          {errorText}
        </div>
      )}

      <Card>
        <CardContent className="p-4">
          <h2 className="font-semibold mb-2">Access Frequency Heatmap (UTC hour x weekday)</h2>
          <Plot
            data={[{ z: heatmapZ, type: "heatmap", colorscale: "Viridis" }]}
            layout={{ autosize: true, margin: { l: 32, r: 16, t: 16, b: 28 }, height: 340 }}
            style={{ width: "100%" }}
            config={{ displayModeBar: false, responsive: true }}
          />
          <p className="text-xs text-muted-foreground">
            Higher cells indicate concentrated retrieval load windows; use this to schedule
            dream/trance scans.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-5">
          <EwmaTrendChart trend={data?.trend ?? []} anomalies={data?.anomalies ?? []} />
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <h2 className="font-semibold mb-2">Factor Decomposition (top entities)</h2>
          <Plot
            data={[
              {
                x: contributionStack.x,
                y: contributionStack.recency,
                type: "bar",
                name: "recency",
              },
              { x: contributionStack.x, y: contributionStack.freq, type: "bar", name: "frequency" },
              { x: contributionStack.x, y: contributionStack.graph, type: "bar", name: "graph" },
              { x: contributionStack.x, y: contributionStack.rerank, type: "bar", name: "rerank" },
              {
                x: contributionStack.x,
                y: contributionStack.dream,
                type: "bar",
                name: "dream-link",
              },
            ]}
            layout={{
              barmode: "stack",
              autosize: true,
              margin: { l: 32, r: 16, t: 16, b: 80 },
              height: 380,
            }}
            style={{ width: "100%" }}
            config={{ displayModeBar: false, responsive: true }}
          />
          <p className="text-xs text-muted-foreground">
            Each bar explains which math factors drove influence; this is the primary audit surface
            for "why now?".
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-4">
          <h2 className="font-semibold mb-2">Max Use Leaderboard</h2>
          <div className="space-y-2">
            {(data?.leaderboard ?? []).slice(0, topK).map((item, idx) => (
              <div key={item.id} className="rounded border border-border p-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs text-muted-foreground">
                    #{idx + 1} · {item.type}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    accesses {item.access_count} · influence{" "}
                    {(item.influence_score * 100).toFixed(1)}%
                  </div>
                </div>
                <div className="text-sm text-foreground truncate">{item.text}</div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
