/**
 * Admin › Operations
 *
 * Lists recent async operations across a schema with status filter.
 *
 */

import { CheckCircle2, Clock, ListOrdered, Loader2, XCircle } from "lucide-react";
import { adminFetch, OperationSummaryResponse } from "@/lib/admin-api";

const STATUS_CONFIG: Record<string, { color: string; icon: React.ElementType }> = {
  pending: { color: "text-yellow-600 dark:text-yellow-400", icon: Clock },
  in_progress: { color: "text-blue-600 dark:text-blue-400", icon: Loader2 },
  completed: { color: "text-green-600 dark:text-green-400", icon: CheckCircle2 },
  failed: { color: "text-destructive", icon: XCircle },
};

const STATUS_OPTIONS = ["", "pending", "in_progress", "completed", "failed"];

export default async function AdminOperationsPage({
  searchParams,
}: {
  searchParams: Promise<{ schema?: string; status?: string; limit?: string }>;
}) {
  const { schema: schemaParam, status: statusParam, limit: limitParam } = await searchParams;
  const schema = schemaParam ?? "public";
  const status = statusParam ?? "";
  const limit = limitParam ?? "50";

  let ops: OperationSummaryResponse[] = [];
  let error: string | null = null;

  try {
    const qs = new URLSearchParams({ schema, limit });
    if (status) qs.set("status", status);
    ops = await adminFetch<OperationSummaryResponse[]>(`/operations?${qs}`);
  } catch (e) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  const statusCounts = ops.reduce<Record<string, number>>((acc, op) => {
    acc[op.status] = (acc[op.status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">Operations</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Schema: <code className="text-xs bg-muted px-1 py-0.5 rounded">{schema}</code>
            {status && (
              <>
                {" "}
                · Status: <code className="text-xs bg-muted px-1 py-0.5 rounded">{status}</code>
              </>
            )}
            {" · "}
            {ops.length} rows
          </p>
        </div>
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted">
          <ListOrdered className="h-4 w-4 text-muted-foreground" />
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive flex items-center gap-2">
          <XCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Status summary chips */}
      {ops.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(statusCounts).map(([s, count]) => {
            const cfg = STATUS_CONFIG[s];
            const Icon = cfg?.icon ?? Clock;
            return (
              <div
                key={s}
                className={`flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs bg-card ${cfg?.color ?? ""}`}
              >
                <Icon className="h-3 w-3" />
                <span className="capitalize">{s}:</span>
                <span className="font-semibold">{count}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Table */}
      {ops.length > 0 && (
        <div className="rounded-lg border bg-card shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/30">
            <div className="grid grid-cols-[80px_1fr_1fr_110px_120px_160px] text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <span>ID</span>
              <span>Type</span>
              <span>Bank</span>
              <span>Status</span>
              <span>Worker</span>
              <span>Created</span>
            </div>
          </div>
          {ops.map((op, i) => {
            const cfg = STATUS_CONFIG[op.status];
            const Icon = cfg?.icon ?? Clock;
            return (
              <div
                key={op.operation_id}
                className={`grid grid-cols-[80px_1fr_1fr_110px_120px_160px] items-center px-4 py-2.5 hover:bg-muted/20 transition-colors ${
                  i < ops.length - 1 ? "border-b" : ""
                }`}
              >
                <span className="font-mono text-xs text-muted-foreground">
                  {op.operation_id.slice(0, 8)}
                </span>
                <span className="text-xs truncate">{op.operation_type}</span>
                <span className="font-mono text-xs truncate">{op.bank_id}</span>
                <div className={`flex items-center gap-1 text-xs font-medium ${cfg?.color ?? ""}`}>
                  <Icon className="h-3 w-3 shrink-0" />
                  {op.status}
                </div>
                <span className="font-mono text-xs text-muted-foreground truncate">
                  {op.worker_id?.slice(0, 10) ?? "—"}
                </span>
                <span className="text-xs text-muted-foreground">{op.created_at?.slice(0, 16)}</span>
              </div>
            );
          })}
        </div>
      )}

      {ops.length === 0 && !error && (
        <div className="rounded-lg border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
          No operations found.
        </div>
      )}

      {/* Filter hint */}
      <div className="rounded-lg border bg-muted/30 px-4 py-3">
        <p className="text-xs text-muted-foreground font-medium mb-1">Filter by status</p>
        <div className="flex gap-2 flex-wrap">
          {STATUS_OPTIONS.map((s) => (
            <a
              key={s || "all"}
              href={`/admin/operations?schema=${schema}${s ? `&status=${s}` : ""}&limit=${limit}`}
              className={`text-xs px-2 py-1 rounded border transition-colors hover:bg-accent ${
                status === s
                  ? "bg-accent text-accent-foreground border-border"
                  : "text-muted-foreground border-transparent"
              }`}
            >
              {s || "all"}
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}
