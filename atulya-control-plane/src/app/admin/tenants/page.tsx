/**
 * Admin › Tenants
 *
 */

import Link from "next/link";
import { ArrowRight, Building2, XCircle } from "lucide-react";
import { PlatformAdminRequired } from "@/components/platform-admin-required";
import { adminFetch, TenantSummaryResponse } from "@/lib/admin-api";
import { canUsePlatformAdmin, getCurrentIdentity } from "@/lib/server-auth";

export default async function AdminTenantsPage() {
  const identity = await getCurrentIdentity();
  if (!canUsePlatformAdmin(identity)) return <PlatformAdminRequired />;

  let tenants: TenantSummaryResponse[] = [];
  let error: string | null = null;

  try {
    tenants = await adminFetch<TenantSummaryResponse[]>("/tenants");
  } catch (e) {
    error = e instanceof Error ? e.message : "Unknown error";
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Tenants</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {tenants.length} schema{tenants.length !== 1 ? "s" : ""} registered
          </p>
        </div>
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-muted">
          <Building2 className="h-4 w-4 text-muted-foreground" />
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm text-destructive flex items-center gap-2">
          <XCircle className="h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Tenant cards */}
      {tenants.length > 0 && (
        <div className="rounded-lg border bg-card shadow-sm overflow-hidden">
          <div className="px-4 py-3 border-b bg-muted/30">
            <div className="grid grid-cols-[1fr_80px_100px] text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <span>Schema</span>
              <span>Banks</span>
              <span></span>
            </div>
          </div>
          {tenants.map((t, i) => (
            <div
              key={t.schema_name}
              className={`grid grid-cols-[1fr_80px_100px] items-center px-4 py-3 hover:bg-muted/20 transition-colors ${
                i < tenants.length - 1 ? "border-b" : ""
              }`}
            >
              <div className="flex items-center gap-2 min-w-0">
                <div className="h-2 w-2 rounded-full bg-green-500 shrink-0" />
                <span className="font-mono text-sm truncate">{t.schema_name}</span>
              </div>
              <span className="text-sm tabular-nums">
                {t.bank_count}{" "}
                <span className="text-muted-foreground text-xs">
                  {t.bank_count === 1 ? "bank" : "banks"}
                </span>
              </span>
              <Link
                href={`/admin/tenants/${t.schema_name}`}
                className="flex items-center gap-1 text-xs text-primary hover:underline underline-offset-2 justify-end"
              >
                View banks <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
          ))}
        </div>
      )}

      {tenants.length === 0 && !error && (
        <div className="rounded-lg border bg-card px-4 py-8 text-center text-sm text-muted-foreground">
          No tenants registered yet.
        </div>
      )}
    </div>
  );
}
