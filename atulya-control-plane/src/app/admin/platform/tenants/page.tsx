import Link from "next/link";
import { ArrowRight, Building2, XCircle } from "lucide-react";
import { PlatformAdminRequired } from "@/components/platform-admin-required";
import { adminFetch, type TenantSummaryResponse } from "@/lib/admin-api";
import { canUsePlatformAdmin, getCurrentIdentity } from "@/lib/server-auth";

export default async function PlatformTenantsPage() {
  const identity = await getCurrentIdentity();
  if (!canUsePlatformAdmin(identity)) return <PlatformAdminRequired />;

  let tenants: TenantSummaryResponse[] = [];
  let error: string | null = null;
  try {
    tenants = await adminFetch<TenantSummaryResponse[]>("/tenants");
  } catch (reason) {
    error = reason instanceof Error ? reason.message : "Tenant inventory unavailable";
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-4 border-b pb-5">
        <div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Building2 className="h-3.5 w-3.5" />
            <span>Deployment inventory</span>
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">Organizations</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {tenants.length} tenant schema{tenants.length === 1 ? "" : "s"} registered.
          </p>
        </div>
      </div>

      {error ? (
        <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <XCircle className="h-4 w-4 shrink-0 text-destructive" />
          {error}
        </div>
      ) : tenants.length === 0 ? (
        <div className="rounded-md border border-dashed p-10 text-center text-sm text-muted-foreground">
          No tenant schemas registered.
        </div>
      ) : (
        <div className="overflow-hidden rounded-md border">
          <div className="hidden grid-cols-[minmax(0,1fr)_120px_140px] gap-4 border-b bg-muted/30 px-4 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground sm:grid">
            <span>Schema</span>
            <span>Banks</span>
            <span />
          </div>
          {tenants.map((tenant) => (
            <div
              key={tenant.schema_name}
              className="grid grid-cols-1 items-start gap-3 border-b px-4 py-4 last:border-b-0 hover:bg-muted/20 sm:grid-cols-[minmax(0,1fr)_120px_140px] sm:items-center sm:gap-4"
            >
              <span className="truncate font-mono text-sm">{tenant.schema_name}</span>
              <span className="text-sm tabular-nums sm:text-left">
                {tenant.bank_count} bank{tenant.bank_count === 1 ? "" : "s"}
              </span>
              <Link
                href={`/admin/platform/tenants/${encodeURIComponent(tenant.schema_name)}`}
                className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline sm:justify-end"
              >
                Inspect banks
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
