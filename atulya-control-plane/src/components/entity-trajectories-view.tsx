"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { client, type EntityTrajectoryPayload } from "@/lib/api";
import { useBank } from "@/lib/bank-context";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Loader2, RefreshCw } from "lucide-react";

interface EntityRow {
  id: string;
  canonical_name: string;
  mention_count: number;
}

export function EntityTrajectoriesView() {
  const { currentBank } = useBank();
  const [entities, setEntities] = useState<EntityRow[]>([]);
  const [entityId, setEntityId] = useState<string>("");
  const [loadingList, setLoadingList] = useState(false);
  const [trajectory, setTrajectory] = useState<EntityTrajectoryPayload | null>(null);
  const [loadingTraj, setLoadingTraj] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [recomputing, setRecomputing] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [trajError, setTrajError] = useState<string | null>(null);

  const loadEntities = useCallback(async () => {
    if (!currentBank) return;
    setLoadingList(true);
    setListError(null);
    try {
      const res = await client.listEntities({ bank_id: currentBank, limit: 200, offset: 0 });
      setEntities((res.items || []) as EntityRow[]);
    } catch (e: unknown) {
      setListError(e instanceof Error ? e.message : "Could not list entities");
      setEntities([]);
    } finally {
      setLoadingList(false);
    }
  }, [currentBank]);

  useEffect(() => {
    if (currentBank) {
      loadEntities();
      setEntityId("");
      setTrajectory(null);
      setNotFound(false);
      setTrajError(null);
    }
  }, [currentBank, loadEntities]);

  const loadTrajectory = async (id: string) => {
    if (!currentBank || !id) return;
    setLoadingTraj(true);
    setNotFound(false);
    setTrajError(null);
    try {
      const data = await client.getEntityTrajectory(id, currentBank);
      setTrajectory(data);
    } catch (e: unknown) {
      const status = (e as { status?: number })?.status;
      if (status === 404) {
        setTrajectory(null);
        setNotFound(true);
      } else {
        setTrajectory(null);
        setTrajError(e instanceof Error ? e.message : "Failed to load trajectory");
      }
    } finally {
      setLoadingTraj(false);
    }
  };

  const handleRecompute = async () => {
    if (!currentBank || !entityId) return;
    setRecomputing(true);
    try {
      await client.postEntityTrajectoryRecompute(entityId, currentBank);
      await new Promise((r) => setTimeout(r, 1500));
      await loadTrajectory(entityId);
    } finally {
      setRecomputing(false);
    }
  };

  const forecastData = useMemo(() => {
    if (!trajectory?.forecast_distribution) return [];
    return Object.entries(trajectory.forecast_distribution).map(([name, value]) => ({
      name,
      value: Math.round(value * 1000) / 1000,
    }));
  }, [trajectory]);

  const pathData = useMemo(() => {
    if (!trajectory?.viterbi_path?.length) return [];
    const v = trajectory.state_vocabulary || [];
    const idx = (s: string) => {
      const j = v.indexOf(s);
      return j >= 0 ? j : 0;
    };
    return trajectory.viterbi_path.map((step, i) => ({
      i: i + 1,
      state: step.state,
      y: idx(step.state),
    }));
  }, [trajectory]);

  const matrix = trajectory?.transition_matrix || [];
  const vocab = trajectory?.state_vocabulary || [];

  return (
    <div className="space-y-6">
      {listError && (
        <p className="text-sm text-destructive" role="alert">
          {listError}
        </p>
      )}

      <div className="flex flex-wrap items-end gap-4">
        <div className="min-w-[220px] flex-1">
          <label className="text-sm font-medium text-muted-foreground mb-1 block">Entity</label>
          <Select
            value={entityId}
            onValueChange={(v) => {
              setEntityId(v);
              void loadTrajectory(v);
            }}
            disabled={loadingList || !entities.length}
          >
            <SelectTrigger>
              <SelectValue placeholder={loadingList ? "Loading…" : "Select entity"} />
            </SelectTrigger>
            <SelectContent>
              {entities.map((e) => (
                <SelectItem key={e.id} value={e.id}>
                  {e.canonical_name} ({e.mention_count})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={!entityId || recomputing}
          onClick={() => void handleRecompute()}
        >
          {recomputing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          <span className="ml-2">Recompute</span>
        </Button>
      </div>

      {!loadingList && !listError && entities.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No entities in this bank yet. Retain memories that mention people or organizations, then open this tab
          again.
        </p>
      )}

      {trajError && (
        <p className="text-sm text-destructive" role="alert">
          {trajError}
        </p>
      )}

      {loadingTraj && (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading trajectory…
        </div>
      )}

      {notFound && !loadingTraj && entityId && (
        <div className="text-sm text-muted-foreground space-y-2 max-w-2xl">
          <p>
            No trajectory computed for this entity yet. This is normal until the first successful run.
          </p>
          <p>
            Turn on{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">enable_entity_trajectories</code>{" "}
            for the bank (e.g. <code className="rounded bg-muted px-1 py-0.5 text-xs">ATULYA_API_ENABLE_ENTITY_TRAJECTORIES=true</code>{" "}
            or bank config), ensure the entity has at least three memory facts with embeddings linked via{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">unit_entities</code>, then click{" "}
            <span className="font-medium text-foreground">Recompute</span>. Computation runs in the API{" "}
            <span className="font-medium text-foreground">worker</span>—use{" "}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">./scripts/dev/start.sh --with-worker</code>{" "}
            if jobs stay pending locally.
          </p>
        </div>
      )}

      {trajectory && !loadingTraj && (
        <div className="space-y-8">
          <div className="rounded-lg border border-border bg-card p-4 text-sm space-y-1">
            <div>
              <span className="text-muted-foreground">Current state:</span>{" "}
              <span className="font-semibold">{trajectory.current_state}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Computed:</span>{" "}
              {trajectory.computed_at ? new Date(trajectory.computed_at).toLocaleString() : "—"}
            </div>
            <div>
              <span className="text-muted-foreground">Anomaly score:</span>{" "}
              {trajectory.anomaly_score != null ? trajectory.anomaly_score.toFixed(3) : "—"}
            </div>
            <div>
              <span className="text-muted-foreground">Forward log P:</span>{" "}
              {trajectory.forward_log_prob != null ? trajectory.forward_log_prob.toFixed(2) : "—"}
            </div>
            <div className="text-xs text-muted-foreground truncate">
              Model: {trajectory.llm_model}
            </div>
          </div>

          <div>
            <h2 className="text-lg font-semibold mb-2">Viterbi path</h2>
            <div className="h-[280px] w-full min-w-0">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={pathData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis dataKey="i" name="Step" />
                  <YAxis
                    type="number"
                    domain={[0, Math.max(0, (trajectory.state_vocabulary?.length || 1) - 1)]}
                    width={100}
                    tickFormatter={(v) => trajectory.state_vocabulary?.[Number(v)] ?? String(v)}
                  />
                  <Tooltip
                    formatter={(_value, _name, props) => [
                      (props.payload as { state?: string }).state ?? "",
                      "State",
                    ]}
                  />
                  <Line
                    type="stepAfter"
                    dataKey="y"
                    stroke="hsl(var(--primary))"
                    dot
                    name="State index"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div>
            <h2 className="text-lg font-semibold mb-2">Transition matrix (A)</h2>
            {matrix.length > 0 && vocab.length === matrix.length ? (
              <div className="overflow-x-auto">
                <table className="text-xs border-collapse">
                  <thead>
                    <tr>
                      <th className="p-1" />
                      {vocab.map((h) => (
                        <th
                          key={h}
                          className="p-1 text-left font-medium text-muted-foreground max-w-[72px] truncate"
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {matrix.map((row, ri) => (
                      <tr key={ri}>
                        <td className="p-1 font-medium text-muted-foreground max-w-[96px] truncate">
                          {vocab[ri]}
                        </td>
                        {row.map((cell, ci) => {
                          const c = Math.max(0, Math.min(1, cell));
                          const bg = `rgba(59, 130, 246, ${0.15 + c * 0.75})`;
                          return (
                            <td
                              key={ci}
                              className="p-1 text-center font-mono"
                              style={{ backgroundColor: bg }}
                            >
                              {c.toFixed(2)}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No matrix data.</p>
            )}
          </div>

          <div>
            <h2 className="text-lg font-semibold mb-2">
              Forecast (h = {trajectory.forecast_horizon} steps)
            </h2>
            <div className="h-[280px] w-full min-w-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart layout="vertical" data={forecastData} margin={{ left: 100 }}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                  <XAxis type="number" domain={[0, 1]} />
                  <YAxis type="category" dataKey="name" width={100} />
                  <Tooltip />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                    {forecastData.map((_, i) => (
                      <Cell key={i} fill="hsl(var(--primary))" />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
