"use client";

import { useState, useEffect } from "react";
import { useBank } from "@/lib/bank-context";
import { useFeatures } from "@/lib/features-context";
import { client } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Database, Link2, FolderOpen, Activity, Clock } from "lucide-react";

interface BankStats {
  bank_id: string;
  total_nodes: number;
  total_links: number;
  total_documents: number;
  nodes_by_fact_type: {
    world?: number;
    experience?: number;
    opinion?: number;
  };
  links_by_link_type: {
    temporal?: number;
    semantic?: number;
    entity?: number;
  };
  pending_operations: number;
  failed_operations: number;
  last_consolidated_at: string | null;
  pending_consolidation: number;
  total_observations: number;
}

interface BrainStatus {
  exists: boolean;
  size_bytes: number;
  generated_at: string | null;
}

interface BrainPredictions {
  predictions: Array<{ hour_utc: number; score: number }>;
}

export function BankStatsView() {
  const { currentBank } = useBank();
  const { features } = useFeatures();
  const observationsEnabled = features?.observations ?? false;
  const subRoutineEnabled = features?.sub_routine ?? false;
  const [stats, setStats] = useState<BankStats | null>(null);
  const [mentalModelsCount, setMentalModelsCount] = useState(0);
  const [directivesCount, setDirectivesCount] = useState(0);
  const [brainStatus, setBrainStatus] = useState<BrainStatus | null>(null);
  const [brainPredictions, setBrainPredictions] = useState<BrainPredictions | null>(null);
  const [loading, setLoading] = useState(false);

  const loadData = async () => {
    if (!currentBank) return;

    setLoading(true);
    try {
      const [statsData, mentalModelsData, directivesData, brainStatusData, brainPredictionData] =
        await Promise.all([
          client.getBankStats(currentBank),
          client.listMentalModels(currentBank),
          client.listDirectives(currentBank),
          subRoutineEnabled ? client.getBrainStatus(currentBank) : Promise.resolve(null),
          subRoutineEnabled ? client.getSubRoutinePredictions(currentBank) : Promise.resolve(null),
        ]);
      setStats(statsData as BankStats);
      setMentalModelsCount(mentalModelsData.items?.length || 0);
      setDirectivesCount(directivesData.items?.length || 0);
      setBrainStatus(brainStatusData as BrainStatus | null);
      setBrainPredictions(brainPredictionData as BrainPredictions | null);
    } catch (error) {
      console.error("Error loading bank stats:", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (currentBank) {
      loadData();
      // Refresh stats every 5 seconds
      const interval = setInterval(loadData, 5000);
      return () => clearInterval(interval);
    }
  }, [currentBank]);

  if (loading && !stats) {
    return (
      <div className="flex items-center justify-center py-12">
        <Clock className="w-12 h-12 mx-auto mb-3 text-muted-foreground animate-pulse" />
      </div>
    );
  }

  if (!stats) return null;

  return (
    <div className="space-y-6">
      {/* Stats Overview - Compact cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
        <Card className="min-w-0 overflow-hidden bg-gradient-to-br from-red-500/10 to-red-600/5 border-red-500/20">
          <CardContent className="p-3 sm:p-4">
            <div className="flex min-w-0 items-center gap-2 sm:gap-3">
              <div className="shrink-0 rounded-lg bg-red-500/20 p-2">
                <Database className="h-5 w-5 text-red-500" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-muted-foreground" title="Memories">
                  Memories
                </p>
                <p className="truncate text-xl font-bold tabular-nums text-foreground sm:text-2xl">
                  {stats.total_nodes}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="min-w-0 overflow-hidden bg-gradient-to-br from-purple-500/10 to-purple-600/5 border-purple-500/20">
          <CardContent className="p-3 sm:p-4">
            <div className="flex min-w-0 items-center gap-2 sm:gap-3">
              <div className="shrink-0 rounded-lg bg-purple-500/20 p-2">
                <Link2 className="h-5 w-5 text-purple-500" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-muted-foreground" title="Links">
                  Links
                </p>
                <p className="truncate text-xl font-bold tabular-nums text-foreground sm:text-2xl">
                  {stats.total_links}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="min-w-0 overflow-hidden bg-gradient-to-br from-emerald-500/10 to-emerald-600/5 border-emerald-500/20">
          <CardContent className="p-3 sm:p-4">
            <div className="flex min-w-0 items-center gap-2 sm:gap-3">
              <div className="shrink-0 rounded-lg bg-emerald-500/20 p-2">
                <FolderOpen className="h-5 w-5 text-emerald-500" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-muted-foreground" title="Documents">
                  Documents
                </p>
                <p className="truncate text-xl font-bold tabular-nums text-foreground sm:text-2xl">
                  {stats.total_documents}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card
          className={`min-w-0 overflow-hidden bg-gradient-to-br ${stats.pending_operations > 0 ? "from-amber-500/10 to-amber-600/5 border-amber-500/20" : "from-slate-500/10 to-slate-600/5 border-slate-500/20"}`}
        >
          <CardContent className="p-3 sm:p-4">
            <div className="flex min-w-0 items-center gap-2 sm:gap-3">
              <div
                className={`shrink-0 rounded-lg p-2 ${stats.pending_operations > 0 ? "bg-amber-500/20" : "bg-slate-500/20"}`}
              >
                <Activity
                  className={`h-5 w-5 ${stats.pending_operations > 0 ? "text-amber-500 animate-pulse" : "text-slate-500"}`}
                />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-muted-foreground" title="Pending">
                  Pending
                </p>
                <p className="truncate text-xl font-bold tabular-nums text-foreground sm:text-2xl">
                  {stats.pending_operations}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Memory Type Breakdown */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
        <div className="min-w-0 rounded-xl border border-red-500/20 bg-red-500/10 p-3 text-center sm:p-4">
          <p className="break-words text-[10px] font-semibold uppercase leading-tight tracking-wide text-red-600 dark:text-red-400 sm:text-xs">
            World Facts
          </p>
          <p className="text-2xl font-bold text-red-600 dark:text-red-400 mt-1">
            {stats.nodes_by_fact_type?.world || 0}
          </p>
        </div>
        <div className="min-w-0 rounded-xl border border-purple-500/20 bg-purple-500/10 p-3 text-center sm:p-4">
          <p className="break-words text-[10px] font-semibold uppercase leading-tight tracking-wide text-purple-600 dark:text-purple-400 sm:text-xs">
            Experience
          </p>
          <p className="mt-1 text-2xl font-bold tabular-nums text-purple-600 dark:text-purple-400">
            {stats.nodes_by_fact_type?.experience || 0}
          </p>
        </div>
        <div
          className={`min-w-0 rounded-xl p-3 text-center sm:p-4 ${
            observationsEnabled
              ? "border border-amber-500/20 bg-amber-500/10"
              : "border border-muted bg-muted/50"
          }`}
          title={!observationsEnabled ? "Observations feature is not enabled" : undefined}
        >
          <p
            className={`break-words text-[10px] font-semibold uppercase leading-tight tracking-wide sm:text-xs ${
              observationsEnabled ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"
            }`}
          >
            Observations
            {!observationsEnabled && <span className="ml-1 normal-case">(Off)</span>}
          </p>
          <p
            className={`mt-1 text-2xl font-bold tabular-nums ${
              observationsEnabled ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"
            }`}
          >
            {observationsEnabled ? stats.total_observations || 0 : "—"}
          </p>
        </div>
        <div className="min-w-0 rounded-xl border border-cyan-500/20 bg-cyan-500/10 p-3 text-center sm:p-4">
          <p className="break-words text-[10px] font-semibold uppercase leading-tight tracking-wide text-cyan-600 dark:text-cyan-400 sm:text-xs">
            Mental Models
          </p>
          <p className="mt-1 text-2xl font-bold tabular-nums text-cyan-600 dark:text-cyan-400">
            {mentalModelsCount}
          </p>
        </div>
        <div className="min-w-0 rounded-xl border border-rose-500/20 bg-rose-500/10 p-3 text-center sm:p-4">
          <p className="break-words text-[10px] font-semibold uppercase leading-tight tracking-wide text-rose-600 dark:text-rose-400 sm:text-xs">
            Directives
          </p>
          <p className="mt-1 text-2xl font-bold tabular-nums text-rose-600 dark:text-rose-400">
            {directivesCount}
          </p>
        </div>
      </div>

      {subRoutineEnabled && (
        <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-semibold text-indigo-600 dark:text-indigo-400">
              Atulya Brain Runtime
            </p>
            <p className="text-xs text-muted-foreground">
              Cache {brainStatus?.exists ? "ready" : "not built"}
            </p>
          </div>
          <div className="mt-2 text-xs text-muted-foreground">
            size: {brainStatus?.size_bytes ?? 0} bytes
            {brainStatus?.generated_at
              ? ` • updated ${new Date(brainStatus.generated_at).toLocaleString()}`
              : ""}
          </div>
          {brainPredictions?.predictions && brainPredictions.predictions.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {brainPredictions.predictions.slice(0, 3).map((item) => (
                <span
                  key={item.hour_utc}
                  className="inline-flex items-center rounded-full border border-indigo-500/30 px-2 py-0.5 text-xs text-indigo-600 dark:text-indigo-300"
                >
                  {item.hour_utc.toString().padStart(2, "0")}:00 UTC ({Math.round(item.score * 100)}
                  %)
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
