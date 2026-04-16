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
  type TooltipProps,
  XAxis,
  YAxis,
} from "recharts";
import { Loader2, RefreshCw } from "lucide-react";

/** Design tokens use oklch — use var(--token) in SVG; do not use hsl(var(--primary)). */
const CHART_ACCENT = "var(--chart-1)";
const CHART_GRID = "var(--border)";
const CHART_AXIS = "var(--muted-foreground)";

interface EntityRow {
  id: string;
  canonical_name: string;
  mention_count: number;
}

function TrajectoryTooltip({ active, label, payload }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  const item = payload[0];
  const row = item.payload as {
    i?: number;
    state?: string;
    name?: string;
    value?: number;
  };

  const shell = "rounded-lg border border-border bg-popover px-3 py-2.5 text-xs shadow-md outline-none ring-1 ring-black/5 dark:ring-white/10";

  /* BarChart (forecast): rows are { name, value } only */
  if (typeof row?.name === "string" && typeof row.value === "number" && row.i === undefined) {
    return (
      <div className={shell} style={{ minWidth: "11rem" }}>
        <div className="font-mono text-[11px] font-medium leading-snug text-foreground break-words">
          {row.name}
        </div>
        <div className="mt-2 border-t border-border/60 pt-2 tabular-nums text-sm font-semibold text-foreground">
          {row.value.toFixed(3)}
        </div>
        <p className="mt-2 border-t border-border/40 pt-2 text-[10px] leading-snug text-muted-foreground">
          Share of probability mass for this state in the short look-ahead (not a factual claim about
          the future).
        </p>
      </div>
    );
  }

  /* LineChart (Viterbi): rows are { i, state, y } */
  const stepLabel =
    typeof row?.i === "number" ? `Step ${row.i}` : typeof label === "number" ? `Step ${label}` : String(label ?? "");
  const state = row?.state ?? "";

  return (
    <div className={shell} style={{ minWidth: "11rem" }}>
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{stepLabel}</div>
      {state ? (
        <div className="mt-2 font-mono text-[11px] leading-snug text-foreground break-words">{state}</div>
      ) : null}
    </div>
  );
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

  const viterbiYAxisWidth = useMemo(() => {
    if (!vocab.length) return 148;
    const longest = Math.max(...vocab.map((s) => s.length), 6);
    return Math.min(280, Math.max(148, 12 + longest * 6.8));
  }, [vocab]);

  const forecastLabelWidth = useMemo(() => {
    if (!forecastData.length) return 160;
    const longest = Math.max(...forecastData.map((d) => d.name.length), 6);
    return Math.min(280, Math.max(152, 12 + longest * 6.5));
  }, [forecastData]);

  return (
    <div className="space-y-8">
      {listError && (
        <p className="text-sm text-destructive" role="alert">
          {listError}
        </p>
      )}

      <details className="group rounded-xl border border-border/80 bg-muted/20 text-sm leading-relaxed open:bg-muted/25">
        <summary className="cursor-pointer list-none px-4 py-3 font-heading font-semibold text-foreground marker:content-none [&::-webkit-details-marker]:hidden">
          <span className="mr-2 inline-block text-muted-foreground transition group-open:rotate-90">
            ▸
          </span>
          What is an entity trajectory, and why use it?
        </summary>
        <div className="space-y-3 border-t border-border/70 px-4 pb-4 pt-1 text-muted-foreground">
          <p>
            Each <strong className="font-medium text-foreground">entity</strong> is a canonical thing
            your memories talk about (for example a colleague, a customer, or your own codebase). A{" "}
            <strong className="font-medium text-foreground">trajectory</strong> is not “everything
            about the bank”—it is the <em>story arc of that one entity</em> as facts arrived in time:
            discovery → delivery → maintenance, or whatever labels fit your data.
          </p>
          <p>
            The system proposes short state names, assigns one state per linked memory step, then
            summarizes “how jumpy” the story is (matrix) and “where things might head next”
            (forecast). Use it to spot drift, stale narratives, or sudden shifts worth follow-up—not as
            a ground-truth fact checker.
          </p>
          <ul className="list-disc space-y-1.5 pl-5 text-[13px]">
            <li>
              <span className="font-medium text-foreground">Why one entity?</span> Mixing many subjects
              in one chart would muddy the story; pick the entity you care about from the list.
            </li>
            <li>
              <span className="font-medium text-foreground">What if two states look similar?</span> Names
              are model-generated; rely on ordering and the matrix more than wording.
            </li>
            <li>
              <span className="font-medium text-foreground">What if counts (&quot;5&quot;) are low?</span>{" "}
              Few linked facts mean a thinner story—prefer several distinct memories mentioning this
              entity before drawing conclusions.
            </li>
          </ul>
        </div>
      </details>

      <div className="flex flex-wrap items-end gap-4">
        <div className="min-w-[220px] flex-1">
          <label className="text-sm font-medium text-muted-foreground mb-1.5 block">
            Entity to analyze
          </label>
          <p className="text-[11px] text-muted-foreground mb-2 max-w-xl leading-relaxed">
            Choose who or what this trajectory is <em>about</em>. The number in parentheses is how many
            memories mention this entity—more points usually make a steadier path.
          </p>
          <Select
            value={entityId}
            onValueChange={(v) => {
              setEntityId(v);
              void loadTrajectory(v);
            }}
            disabled={loadingList || !entities.length}
          >
            <SelectTrigger className="bg-background">
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
        <div className="flex shrink-0 flex-col gap-1.5">
          <Button
            variant="outline"
            size="sm"
            disabled={!entityId || recomputing}
            onClick={() => void handleRecompute()}
            className="shrink-0"
          >
            {recomputing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            <span className="ml-2">Recompute</span>
          </Button>
          <p className="max-w-[14rem] text-[10px] leading-snug text-muted-foreground">
            Re-runs the analysis on latest memories. Needs background worker + enough linked facts.
          </p>
        </div>
      </div>

      {!loadingList && !listError && entities.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No entities in this bank yet. Retain memories that mention people or organizations, then
          open this tab again.
        </p>
      )}

      {trajError && (
        <p className="text-sm text-destructive" role="alert">
          {trajError}
        </p>
      )}

      {loadingTraj && (
        <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
          Loading trajectory…
        </div>
      )}

      {notFound && !loadingTraj && entityId && (
        <div className="rounded-xl border border-border/80 bg-muted/20 p-4 text-sm text-muted-foreground space-y-3 max-w-2xl leading-relaxed">
          <p className="text-foreground/90">
            No trajectory computed for this entity yet. This is normal until the first successful
            run.
          </p>
          <p>
            Turn on{" "}
            <code className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-xs">
              enable_entity_trajectories
            </code>{" "}
            for the bank (e.g.{" "}
            <code className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-xs">
              ATULYA_API_ENABLE_ENTITY_TRAJECTORIES=true
            </code>{" "}
            or bank config), ensure the entity has at least three memory facts with embeddings
            linked via{" "}
            <code className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-xs">unit_entities</code>
            , then click <span className="font-medium text-foreground">Recompute</span>.
            Computation runs in the API{" "}
            <span className="font-medium text-foreground">worker</span> — use{" "}
            <code className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-xs">
              ./scripts/dev/start.sh --with-worker
            </code>{" "}
            if jobs stay pending locally.
          </p>
        </div>
      )}

      {trajectory && !loadingTraj && (
        <div className="space-y-10">
          <div className="rounded-xl border border-border/80 bg-card p-4 shadow-sm sm:p-5">
            <h3 className="font-heading text-sm font-semibold uppercase tracking-wide text-muted-foreground mb-1">
              Snapshot
            </h3>
            <p className="mb-4 text-xs leading-relaxed text-muted-foreground">
              Quick read on this entity&apos;s latest trajectory run. States are{" "}
              <span className="text-foreground/90">interpretive labels</span>, not database fields you
              edit—use them as a compact summary of the narrative the model sees in your facts.
            </p>
            <dl className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              <div className="space-y-1.5">
                <dt className="text-xs font-medium text-muted-foreground">Current state</dt>
                <dd className="font-mono text-sm font-semibold text-foreground break-all leading-snug">
                  {trajectory.current_state}
                </dd>
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  The label attached to the <em>most recent</em> memory step after decoding—your best
                  one-line &quot;where this entity sits now&quot; under the model.
                </p>
              </div>
              <div className="space-y-1.5">
                <dt className="text-xs font-medium text-muted-foreground">Computed at</dt>
                <dd className="text-sm tabular-nums text-foreground">
                  {trajectory.computed_at
                    ? new Date(trajectory.computed_at).toLocaleString(undefined, {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })
                    : "—"}
                </dd>
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  When this snapshot was written. Stale? Add memories or hit Recompute so it reflects
                  new evidence.
                </p>
              </div>
              <div className="space-y-1.5">
                <dt className="text-xs font-medium text-muted-foreground">Anomaly score (0–1)</dt>
                <dd className="text-sm tabular-nums text-foreground">
                  {trajectory.anomaly_score != null ? trajectory.anomaly_score.toFixed(3) : "—"}
                </dd>
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  Higher ≈ the observed sequence looks less &quot;typical&quot; under the dynamics
                  inferred here (useful flag for review; not a definitive alarm).
                </p>
              </div>
              <div className="space-y-1.5">
                <dt className="text-xs font-medium text-muted-foreground">Forward log probability</dt>
                <dd className="text-sm tabular-nums text-foreground">
                  {trajectory.forward_log_prob != null ? trajectory.forward_log_prob.toFixed(2) : "—"}
                </dd>
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  Overall fit of the facts to the state + transition model (more negative usually means
                  a harder-to-explain path). Compare entities or time windows only loosely—absolute values
                  are technical.
                </p>
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <dt className="text-xs font-medium text-muted-foreground">Model that labeled states</dt>
                <dd className="font-mono text-xs text-muted-foreground break-all leading-relaxed">
                  {trajectory.llm_model || "—"}
                </dd>
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  Which LLM run produced the state names and per-step tags. Changing bank or global LLM
                  settings can shift wording without changing your underlying memories.
                </p>
              </div>
            </dl>
          </div>

          <section className="rounded-xl border border-border/80 bg-card p-4 shadow-sm sm:p-5">
            <h2 className="font-heading text-lg font-semibold tracking-tight text-foreground mb-1">
              Viterbi path
            </h2>
            <p className="mb-2 text-sm leading-relaxed text-muted-foreground">
              Each point is one memory (in time order) about this entity. The vertical position is{" "}
              <span className="text-foreground/90">which story state</span> best matches that step after
              the model considers the whole sequence—not just that row in isolation.
            </p>
            <p className="mb-4 text-xs leading-relaxed text-muted-foreground">
              <span className="font-medium text-foreground">What to look for:</span> jumps between
              states (phase changes), long flat stretches (stable chapter), or a drift toward a new band
              late in the series. <span className="font-medium text-foreground">What if steps look
              wrong?</span> Check facts out of order, duplicate memories, or mixed topics—those confuse any
              timeline model.
            </p>
            <div className="h-[min(22rem,55vh)] w-full min-w-0 -mx-1 sm:mx-0">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={pathData}
                  margin={{ top: 8, right: 12, bottom: 8, left: 4 }}
                >
                  <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" strokeOpacity={0.55} />
                  <XAxis
                    dataKey="i"
                    tick={{ fill: CHART_AXIS, fontSize: 11 }}
                    tickLine={{ stroke: CHART_GRID }}
                    axisLine={{ stroke: CHART_GRID }}
                    label={{
                      value: "Step",
                      position: "bottom",
                      offset: 0,
                      fill: CHART_AXIS,
                      fontSize: 11,
                    }}
                  />
                  <YAxis
                    type="number"
                    domain={[0, Math.max(0, (trajectory.state_vocabulary?.length || 1) - 1)]}
                    width={viterbiYAxisWidth}
                    tick={{ fill: CHART_AXIS, fontSize: 10 }}
                    tickLine={{ stroke: CHART_GRID }}
                    axisLine={{ stroke: CHART_GRID }}
                    interval={0}
                    tickFormatter={(v) =>
                      trajectory.state_vocabulary?.[Number(v)] ?? String(v)
                    }
                  />
                  <Tooltip content={<TrajectoryTooltip />} cursor={{ stroke: CHART_GRID }} />
                  <Line
                    type="stepAfter"
                    dataKey="y"
                    stroke={CHART_ACCENT}
                    strokeWidth={2}
                    dot={{ r: 3, fill: CHART_ACCENT, strokeWidth: 0 }}
                    activeDot={{ r: 5, fill: CHART_ACCENT, stroke: "var(--background)", strokeWidth: 2 }}
                    name="State index"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="rounded-xl border border-border/80 bg-card p-4 shadow-sm sm:p-5">
            <h2 className="font-heading text-lg font-semibold tracking-tight text-foreground mb-1">
              Transition matrix (A)
            </h2>
            <p className="mb-2 text-sm leading-relaxed text-muted-foreground">
              Rows are <span className="text-foreground/90">&quot;from&quot;</span> states, columns are
              <span className="text-foreground/90"> &quot;to&quot;</span> states. Each row sums to 1: read
              it as &quot;if the narrative was in this row&apos;s state, how often does the next step
              land in each column?&quot; Darker cells mean stronger habitual transitions.
            </p>
            <p className="mb-4 text-xs leading-relaxed text-muted-foreground">
              <span className="font-medium text-foreground">Why it matters:</span> stable work shows up
              as mass on the diagonal; reinvention or hand-offs show up as off-diagonal weight.{" "}
              <span className="font-medium text-foreground">What if the matrix looks noisy?</span> You may
              have too few steps, rapidly changing unrelated facts, or states that are too similar by
              name—try more coherent memories or another recompute after cleanup.
            </p>
            {matrix.length > 0 && vocab.length === matrix.length ? (
              <div className="overflow-x-auto rounded-lg border border-border/60 -mx-1 px-1 sm:mx-0">
                <table className="w-full min-w-[560px] border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-border/80">
                      <th
                        scope="col"
                        className="sticky left-0 z-20 bg-card py-3 pr-3 pl-2 text-left text-[10px] font-medium uppercase tracking-wider text-muted-foreground shadow-[1px_0_0_0_var(--border)]"
                      >
                        From \ To
                      </th>
                      {vocab.map((h) => (
                        <th
                          key={h}
                          scope="col"
                          title={h}
                          className="max-w-[8.5rem] min-w-[4.5rem] px-2 py-2 text-left align-bottom"
                        >
                          <span className="line-clamp-3 break-words font-medium leading-tight text-muted-foreground">
                            {h}
                          </span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {matrix.map((row, ri) => (
                      <tr key={ri} className="border-b border-border/40 last:border-0">
                        <th
                          scope="row"
                          title={vocab[ri]}
                          className="sticky left-0 z-10 bg-card py-2 pr-3 pl-2 text-left font-medium shadow-[1px_0_0_0_var(--border)]"
                        >
                          <span className="line-clamp-3 break-words leading-tight text-foreground">
                            {vocab[ri]}
                          </span>
                        </th>
                        {row.map((cell, ci) => {
                          const c = Math.max(0, Math.min(1, cell));
                          const mix = 18 + Math.round(c * 62);
                          return (
                            <td
                              key={ci}
                              className="px-2 py-2.5 text-center font-mono text-[11px] tabular-nums"
                              style={{
                                backgroundColor: `color-mix(in oklch, var(--primary) ${mix}%, transparent)`,
                              }}
                              title={`P(${vocab[ri]} → ${vocab[ci]}) = ${c.toFixed(4)}`}
                            >
                              <span
                                className={
                                  c > 0.45 ? "text-primary-foreground drop-shadow-sm" : "text-foreground"
                                }
                              >
                                {c.toFixed(2)}
                              </span>
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
          </section>

          <section className="rounded-xl border border-border/80 bg-card p-4 shadow-sm sm:p-5">
            <h2 className="font-heading text-lg font-semibold tracking-tight text-foreground mb-1">
              Forecast (h = {trajectory.forecast_horizon} steps)
            </h2>
            <p className="mb-2 text-sm leading-relaxed text-muted-foreground">
              A <span className="text-foreground/90">short look-ahead only</span>: given the current
              decoded state and the transition habits in the matrix above, this spreads probability mass
              across states a few steps into the future. Bar length is a share (0–100%), not a new fact
              about the world.
            </p>
            <p className="mb-4 text-xs leading-relaxed text-muted-foreground">
              <span className="font-medium text-foreground">How to use it:</span> see which future
              chapters are plausible if today&apos;s rhythm continues.{" "}
              <span className="font-medium text-foreground">What it is not:</span> a guarantee or a
              schedule—it skips real-world forcing factors the bank doesn&apos;t know. Treat as a
              directional cue for planning or debriefs, not a prediction with confidence intervals.
            </p>
            <div className="h-[min(22rem,55vh)] w-full min-w-0 -mx-1 sm:mx-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  layout="vertical"
                  data={forecastData}
                  margin={{ left: 8, right: 20, top: 8, bottom: 8 }}
                >
                  <CartesianGrid stroke={CHART_GRID} strokeDasharray="3 3" horizontal={false} strokeOpacity={0.55} />
                  <XAxis
                    type="number"
                    domain={[0, 1]}
                    tick={{ fill: CHART_AXIS, fontSize: 11 }}
                    tickFormatter={(v) => `${Math.round(Number(v) * 100)}%`}
                    tickLine={{ stroke: CHART_GRID }}
                    axisLine={{ stroke: CHART_GRID }}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={forecastLabelWidth}
                    tick={{ fill: CHART_AXIS, fontSize: 10 }}
                    tickLine={false}
                    axisLine={{ stroke: CHART_GRID }}
                    interval={0}
                  />
                  <Tooltip
                    content={<TrajectoryTooltip />}
                    cursor={{ fill: "color-mix(in oklch, var(--muted-foreground) 12%, transparent)" }}
                  />
                  <Bar
                    dataKey="value"
                    radius={[0, 6, 6, 0]}
                    maxBarSize={36}
                    fill={CHART_ACCENT}
                  >
                    {forecastData.map((_, i) => (
                      <Cell key={i} fill={CHART_ACCENT} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
