/**
 * Admin › System Health
 *
 * Server component — stat cards + detail table.
 *
 */

import { redirect } from "next/navigation";
import { Activity, CheckCircle2, Database, GitBranch, Server, XCircle } from "lucide-react";
import { adminFetch, SystemHealthResponse } from "@/lib/admin-api";
import { canUsePlatformAdmin, getCurrentIdentity } from "@/lib/server-auth";

function StatCard({
  icon: Icon,
  label,
  value,
  sub,
  accent,
}: {
  icon: React.ElementType;
  label: string;
  value: string;
  sub?: string;
  accent?: "green" | "red" | "default";
}) {
  const valueColor =
    accent === "green"
      ? "text-green-500 dark:text-green-400"
      : accent === "red"
        ? "text-destructive"
        : "text-foreground";

  return (
    <div className="rounded-xl border bg-card p-5 flex flex-col gap-3 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          {label}
        </p>
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-muted shrink-0">
          <Icon className="h-4 w-4 text-muted-foreground" />
        </div>
      </div>
      <div>
        <p className={`text-2xl font-bold font-mono leading-none ${valueColor}`}>{value}</p>
        {sub && <p className="text-xs text-muted-foreground mt-1.5">{sub}</p>}
      </div>
    </div>
  );
}

export default async function AdminSystemPage() {
  const identity = await getCurrentIdentity();
  if (!canUsePlatformAdmin(identity)) redirect("/admin/api-keys");

  let health: SystemHealthResponse | null = null;
  let error: string | null = null;

  try {
    health = await adminFetch<SystemHealthResponse>("/system/health");
  } catch (e) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div className="border-b pb-5">
        <h1 className="text-2xl font-semibold tracking-tight">System Health</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Live snapshot of the API backend state.
        </p>
      </div>

      {error && (
        <div className="rounded-xl border border-destructive/40 bg-destructive/5 px-5 py-4 text-sm text-destructive flex items-center gap-3">
          <XCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {health && (
        <div className="space-y-8">
          {/* Stat cards — fluid grid: fills width, min 260px per card */}
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))" }}
          >
            <StatCard
              icon={health.status === "healthy" ? CheckCircle2 : XCircle}
              label="Status"
              value={health.status}
              accent={health.status === "healthy" ? "green" : "red"}
            />
            <StatCard
              icon={Server}
              label="API Version"
              value={health.api_version}
              sub="current release"
            />
            <StatCard
              icon={Activity}
              label="Pending Workers"
              value={String(health.worker_count)}
              sub={health.worker_count === 0 ? "all idle" : "tasks in queue"}
              accent={health.worker_count > 0 ? "default" : "green"}
            />
            <StatCard
              icon={Database}
              label="DB Pool"
              value={`${health.db_pool_free} / ${health.db_pool_size}`}
              sub="free / total connections"
              accent={
                health.db_pool_free === 0
                  ? "red"
                  : health.db_pool_free < health.db_pool_size * 0.2
                    ? "red"
                    : "default"
              }
            />
            <StatCard
              icon={Database}
              label="Pool Limits"
              value={`${health.db_pool_min} – ${health.db_pool_max}`}
              sub="min – max connections"
            />
            <StatCard
              icon={GitBranch}
              label="Migration"
              value={health.migration_version?.slice(0, 12) ?? "unknown"}
              sub="latest applied revision"
            />
          </div>

          {/* Detail table */}
          <div className="rounded-xl border bg-card shadow-sm overflow-hidden">
            <div className="px-6 py-4 border-b bg-muted/20">
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                Full Details
              </p>
            </div>
            <div className="divide-y">
              {[
                ["Admin Schema", health.admin_schema],
                ["Full Migration ID", health.migration_version ?? "unknown"],
                ["Pool Free", String(health.db_pool_free)],
                ["Pool Total", String(health.db_pool_size)],
                ["Pool Min", String(health.db_pool_min)],
                ["Pool Max", String(health.db_pool_max)],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="flex items-center px-6 py-3.5 hover:bg-muted/10 transition-colors"
                >
                  <span className="w-48 text-sm text-muted-foreground shrink-0">{label}</span>
                  <span className="font-mono text-sm">{value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
