import Link from "next/link";
import { ArrowLeft, Database } from "lucide-react";
import { PlatformAdminRequired } from "@/components/platform-admin-required";
import { adminFetch } from "@/lib/admin-api";
import { canUsePlatformAdmin, getCurrentIdentity } from "@/lib/server-auth";

interface PlatformBankRow {
  bank_id: string;
  name: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export default async function PlatformTenantBanksPage({
  params,
}: {
  params: Promise<{ schema: string }>;
}) {
  const identity = await getCurrentIdentity();
  if (!canUsePlatformAdmin(identity)) return <PlatformAdminRequired />;

  const { schema } = await params;
  let banks: PlatformBankRow[] = [];
  let error: string | null = null;
  try {
    banks = await adminFetch<PlatformBankRow[]>(`/tenants/${encodeURIComponent(schema)}/banks`);
  } catch (reason) {
    error = reason instanceof Error ? reason.message : "Bank inventory unavailable";
  }

  return (
    <div className="space-y-6">
      <div className="border-b pb-5">
        <Link
          href="/admin/platform/tenants"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Organizations
        </Link>
        <div className="mt-4 flex items-center gap-2">
          <Database className="h-4 w-4 text-muted-foreground" />
          <h1 className="text-2xl font-semibold tracking-tight">Bank inventory</h1>
        </div>
        <p className="mt-1 font-mono text-sm text-muted-foreground">{schema}</p>
      </div>

      {error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      ) : (
        <div className="overflow-hidden rounded-md border">
          <div className="hidden grid-cols-[minmax(0,1fr)_160px] gap-4 border-b bg-muted/30 px-4 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground sm:grid">
            <span>Bank</span>
            <span>Created</span>
          </div>
          {banks.map((bank) => (
            <div
              key={bank.bank_id}
              className="grid grid-cols-1 gap-2 border-b px-4 py-4 last:border-b-0 sm:grid-cols-[minmax(0,1fr)_160px] sm:gap-4"
            >
              <div className="min-w-0">
                <p className="truncate font-medium">{bank.name || bank.bank_id}</p>
                <p className="truncate font-mono text-xs text-muted-foreground">{bank.bank_id}</p>
              </div>
              <span className="text-sm text-muted-foreground">
                Created{" "}
                {bank.created_at ? new Date(bank.created_at).toLocaleDateString() : "Unknown"}
              </span>
            </div>
          ))}
          {banks.length === 0 && (
            <p className="p-8 text-center text-sm text-muted-foreground">No banks found.</p>
          )}
        </div>
      )}
    </div>
  );
}
