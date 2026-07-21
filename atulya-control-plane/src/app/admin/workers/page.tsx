/**
 * Admin › Workers
 *
 * Lists workers with pending/stuck counts.
 * Stuck workers (>5 min no heartbeat) shown with red alert badge.
 *
 */

import { AlertTriangle, Clock, Cpu, XCircle } from "lucide-react";
import { PlatformAdminRequired } from "@/components/platform-admin-required";
import { DecommissionWorkerButton } from "@/components/decommission-worker-button";
import { adminFetch, TenantSummaryResponse, WorkerStatusResponse } from "@/lib/admin-api";
import { canUsePlatformAdmin, getCurrentIdentity } from "@/lib/server-auth";

export default async function AdminWorkersPage({
  searchParams,
}: {
  searchParams: Promise<{ schema?: string }>;
}) {
  const identity = await getCurrentIdentity();
  if (!canUsePlatformAdmin(identity)) return <PlatformAdminRequired />;

  const { schema: schemaParam } = await searchParams;
  const schema = schemaParam ?? "public";
  let workers: WorkerStatusResponse[] = [];
  let tenants: TenantSummaryResponse[] = [];
  let error: string | null = null;

  try {
    [workers, tenants] = await Promise.all([
      adminFetch<WorkerStatusResponse[]>(`/workers?schema=${schema}`),
      adminFetch<TenantSummaryResponse[]>("/tenants"),
    ]);
  } catch (e) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  const stuckCount = workers.reduce((n, w) => n + w.stuck_count, 0);
  const totalPending = workers.reduce((n, w) => n + w.pending_count, 0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Workers</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Schema: <code className="text-xs bg-muted px-1 py-0.5 rounded">{schema}</code>
          </p>
        </div>
        <form className="flex items-center gap-2" action="/admin/platform/workers">
          <label htmlFor="worker-schema" className="sr-only">
            Schema
          </label>
          <select
            id="worker-schema"
            name="schema"
            defaultValue={schema}
            className="h-9 min-w-44 rounded-md border bg-background px-3 text-sm"
          >
            {tenants.map((tenant) => (
              <option key={tenant.schema_name} value={tenant.schema_name}>
                {tenant.schema_name}
              </option>
            ))}
          </select>
          <button className="h-9 rounded-md border px-3 text-sm hover:bg-accent" type="submit">
            Apply
          </button>
        </form>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive flex items-center gap-2">
          <XCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Alert banner for stuck workers */}
      {stuckCount > 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-amber-500/30 bg-amber-50 px-4 py-3 dark:bg-amber-950/20">
          <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-700 dark:text-amber-300">
              {stuckCount} stuck task{stuckCount !== 1 ? "s" : ""} detected
            </p>
            <p className="mt-0.5 text-xs text-amber-600 dark:text-amber-400">
              Release stale claims so healthy workers can continue them.
            </p>
          </div>
          <div className="ml-auto">
            <DecommissionWorkerButton
              workerId="__all_stuck__"
              schema={schema}
              label="Release stuck"
            />
          </div>
        </div>
      )}

      {/* Summary chips */}
      <div className="flex flex-wrap gap-3">
        <div className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs bg-card">
          <Cpu className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">Workers:</span>
          <span className="font-semibold">{workers.length}</span>
        </div>
        <div className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs bg-card">
          <Clock className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">Pending:</span>
          <span className="font-semibold">{totalPending}</span>
        </div>
        <div
          className={`flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs ${stuckCount > 0 ? "bg-destructive/10 border-destructive/30" : "bg-card"}`}
        >
          <AlertTriangle
            className={`h-3.5 w-3.5 ${stuckCount > 0 ? "text-destructive" : "text-muted-foreground"}`}
          />
          <span className="text-muted-foreground">Stuck:</span>
          <span className={`font-semibold ${stuckCount > 0 ? "text-destructive" : ""}`}>
            {stuckCount}
          </span>
        </div>
      </div>

      {/* Workers table */}
      {workers.length > 0 && (
        <div className="rounded-lg border bg-card shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/30">
            <div className="grid grid-cols-[1fr_100px_100px_180px_28px] text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <span>Worker ID</span>
              <span>Pending</span>
              <span>Stuck</span>
              <span>Last Seen</span>
              <span></span>
            </div>
          </div>
          {workers.map((w, i) => (
            <div
              key={w.worker_id}
              className={`grid grid-cols-[1fr_100px_100px_180px_28px] items-center px-4 py-3 hover:bg-muted/20 transition-colors ${
                i < workers.length - 1 ? "border-b" : ""
              } ${w.stuck_count > 0 ? "bg-destructive/5" : ""}`}
            >
              <span className="font-mono text-xs truncate">{w.worker_id}</span>
              <span className="text-sm tabular-nums">{w.pending_count}</span>
              <span
                className={`text-sm font-semibold tabular-nums ${w.stuck_count > 0 ? "text-destructive" : "text-muted-foreground"}`}
              >
                {w.stuck_count > 0 ? w.stuck_count : "—"}
              </span>
              <span className="text-xs text-muted-foreground font-mono">
                {w.last_seen_at?.slice(0, 19) ?? "—"}
              </span>
              <DecommissionWorkerButton workerId={w.worker_id} schema={schema} />
            </div>
          ))}
        </div>
      )}

      {workers.length === 0 && !error && (
        <div className="rounded-lg border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
          No active workers found in schema <code>{schema}</code>.
        </div>
      )}
    </div>
  );
}
