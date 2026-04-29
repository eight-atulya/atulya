/**
 * Admin › Workers
 *
 * Lists workers with pending/stuck counts.
 * Stuck workers (>5 min no heartbeat) shown with red alert badge.
 *
 */

import { AlertTriangle, CheckCircle2, Clock, Cpu, XCircle } from "lucide-react";
import { adminFetch, WorkerStatusResponse } from "@/lib/admin-api";

export default async function AdminWorkersPage({
  searchParams,
}: {
  searchParams: Promise<{ schema?: string }>;
}) {
  const { schema: schemaParam } = await searchParams;
  const schema = schemaParam ?? "public";
  let workers: WorkerStatusResponse[] = [];
  let error: string | null = null;

  try {
    workers = await adminFetch<WorkerStatusResponse[]>(`/workers?schema=${schema}`);
  } catch (e) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  const stuckCount = workers.reduce((n, w) => n + w.stuck_count, 0);
  const totalPending = workers.reduce((n, w) => n + w.pending_count, 0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">Workers</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Schema: <code className="text-xs bg-muted px-1 py-0.5 rounded">{schema}</code>
          </p>
        </div>
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted">
          <Cpu className="h-4 w-4 text-muted-foreground" />
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive flex items-center gap-2">
          <XCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Alert banner for stuck workers */}
      {stuckCount > 0 && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-50 dark:bg-amber-950/20 px-4 py-3 flex items-center gap-3">
          <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-700 dark:text-amber-300">
              {stuckCount} stuck task{stuckCount !== 1 ? "s" : ""} detected
            </p>
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-0.5">
              Call <code className="bg-amber-100 dark:bg-amber-900 px-1 rounded">POST /v1/admin/workers/__all_stuck__/decommission</code> to re-queue
            </p>
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
        <div className={`flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs ${stuckCount > 0 ? "bg-destructive/10 border-destructive/30" : "bg-card"}`}>
          <AlertTriangle className={`h-3.5 w-3.5 ${stuckCount > 0 ? "text-destructive" : "text-muted-foreground"}`} />
          <span className="text-muted-foreground">Stuck:</span>
          <span className={`font-semibold ${stuckCount > 0 ? "text-destructive" : ""}`}>{stuckCount}</span>
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
              <span className={`text-sm font-semibold tabular-nums ${w.stuck_count > 0 ? "text-destructive" : "text-muted-foreground"}`}>
                {w.stuck_count > 0 ? w.stuck_count : "—"}
              </span>
              <span className="text-xs text-muted-foreground font-mono">
                {w.last_seen_at?.slice(0, 19) ?? "—"}
              </span>
              {w.stuck_count > 0 ? (
                <AlertTriangle className="h-3.5 w-3.5 text-destructive" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
              )}
            </div>
          ))}
        </div>
      )}

      {workers.length === 0 && !error && (
        <div className="rounded-lg border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
          No active workers found in schema <code>{schema}</code>.
        </div>
      )}

      {/* Decommission hint */}
      <div className="rounded-lg border bg-muted/30 px-4 py-3">
        <p className="text-xs text-muted-foreground font-medium mb-1">Decommission a worker</p>
        <code className="text-xs font-mono text-foreground">
          POST /v1/admin/workers/&#123;worker_id&#125;/decommission
        </code>
        <p className="text-xs text-muted-foreground mt-1">
          Body: <code className="bg-muted px-1 rounded">{`{"release_stuck": true}`}</code> — re-queues tasks to healthy workers.
        </p>
      </div>
    </div>
  );
}
