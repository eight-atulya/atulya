import { Activity, Database, Gauge, Server } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { PlatformAdminRequired } from "@/components/platform-admin-required";
import { adminFetch, type SystemHealthResponse } from "@/lib/admin-api";
import { canUsePlatformAdmin, getCurrentIdentity } from "@/lib/server-auth";

export default async function PlatformHealthPage() {
  const identity = await getCurrentIdentity();
  if (!canUsePlatformAdmin(identity)) return <PlatformAdminRequired />;

  let health: SystemHealthResponse | null = null;
  let error: string | null = null;
  try {
    health = await adminFetch<SystemHealthResponse>("/system/health");
  } catch (reason) {
    error = reason instanceof Error ? reason.message : "Platform health unavailable";
  }
  const metrics: Array<[string, string | number, LucideIcon]> = health
    ? [
        ["Status", health.status, Activity],
        ["Workers", health.worker_count, Server],
        [
          "DB connections",
          `${health.db_pool_size - health.db_pool_free}/${health.db_pool_max}`,
          Database,
        ],
        ["API version", health.api_version, Gauge],
      ]
    : [];

  return (
    <div className="space-y-6">
      <div className="border-b pb-5">
        <h1 className="text-2xl font-semibold">System health</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Database, worker, and migration state for platform operators.
        </p>
      </div>
      {error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-5">
          <p className="font-medium">Platform API unavailable</p>
          <p className="mt-1 text-sm text-muted-foreground">{error}</p>
        </div>
      ) : health ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {metrics.map(([label, value, Icon]) => (
              <div key={String(label)} className="rounded-md border bg-card p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs font-medium text-muted-foreground">{String(label)}</p>
                  <Icon className="h-4 w-4 text-muted-foreground" />
                </div>
                <p className="mt-3 text-xl font-semibold tabular-nums">{String(value)}</p>
              </div>
            ))}
          </div>
          <dl className="grid gap-px overflow-hidden rounded-md border bg-border sm:grid-cols-2">
            <div className="bg-background p-4">
              <dt className="text-xs text-muted-foreground">Migration</dt>
              <dd className="mt-1 font-mono text-sm">{health.migration_version || "Unknown"}</dd>
            </div>
            <div className="bg-background p-4">
              <dt className="text-xs text-muted-foreground">Auth schema</dt>
              <dd className="mt-1 font-mono text-sm">{health.admin_schema}</dd>
            </div>
          </dl>
        </>
      ) : null}
    </div>
  );
}
