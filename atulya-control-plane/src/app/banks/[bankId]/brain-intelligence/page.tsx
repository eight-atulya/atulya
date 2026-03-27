"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { client } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false }) as any;

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

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold text-foreground">Brain Intelligence</h1>
          <p className="text-sm text-muted-foreground">
            Math-first influence analytics with explainable factors and anomaly-aware trending.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href={`/banks/${bankId}?view=brain`}>Back to Brain</Link>
        </Button>
      </div>

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
        <CardContent className="p-4">
          <h2 className="font-semibold mb-2">Influence Trend (raw vs EWMA)</h2>
          <Plot
            data={[
              {
                x: (data?.trend ?? []).map((p) => p.index),
                y: (data?.trend ?? []).map((p) => p.raw),
                type: "scatter",
                mode: "lines+markers",
                name: "raw",
              },
              {
                x: (data?.trend ?? []).map((p) => p.index),
                y: (data?.trend ?? []).map((p) => p.ewma),
                type: "scatter",
                mode: "lines",
                name: "ewma",
              },
              {
                x: (data?.trend ?? []).map((p) => p.index),
                y: (data?.trend ?? []).map((p) => p.upper),
                type: "scatter",
                mode: "lines",
                line: { width: 0 },
                hoverinfo: "skip",
                showlegend: false,
              },
              {
                x: (data?.trend ?? []).map((p) => p.index),
                y: (data?.trend ?? []).map((p) => p.lower),
                type: "scatter",
                mode: "lines",
                fill: "tonexty",
                fillcolor: "rgba(99,102,241,0.15)",
                line: { width: 0 },
                name: "confidence band",
              },
            ]}
            layout={{ autosize: true, margin: { l: 32, r: 16, t: 16, b: 28 }, height: 320 }}
            style={{ width: "100%" }}
            config={{ displayModeBar: false, responsive: true }}
          />
          <p className="text-xs text-muted-foreground">
            EWMA stabilizes noisy retrieval bursts and surfaces persistent directionality in
            influence.
          </p>
          <p className="text-xs text-muted-foreground">
            anomaly flags: {data?.anomalies?.length ?? 0} (
            {data?.anomalies?.some((a) => a.iqr) ? "z-score + IQR" : "z-score"})
          </p>
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
