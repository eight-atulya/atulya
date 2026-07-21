import Link from "next/link";
import { ArrowUpRight, Database, RefreshCw } from "lucide-react";
import { getCurrentIdentity } from "@/lib/server-auth";
import { workspaceFetch, type WorkspaceBank } from "@/lib/workspace-api";

function formatDate(value: string | null): string {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleDateString();
}

export default async function WorkspaceBanksPage() {
  const identity = await getCurrentIdentity();
  let banks: WorkspaceBank[] = [];
  let error: string | null = null;

  try {
    const response = await workspaceFetch<{ banks: WorkspaceBank[] }>("/banks");
    banks = response.banks ?? [];
  } catch (reason) {
    error = reason instanceof Error ? reason.message : "Memory banks unavailable";
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b pb-5">
        <div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Database className="h-3.5 w-3.5" />
            <span>{identity?.org_name || "Workspace"}</span>
          </div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight">Memory banks</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {banks.length} bank{banks.length === 1 ? "" : "s"} available to your access scope.
          </p>
        </div>
        <Link
          href="/dashboard"
          className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm transition-colors hover:bg-accent"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Workspace
        </Link>
      </div>

      {error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4">
          <p className="font-medium">Memory banks unavailable</p>
          <p className="mt-1 text-sm text-muted-foreground">{error}</p>
        </div>
      ) : banks.length === 0 ? (
        <div className="rounded-md border border-dashed p-10 text-center">
          <Database className="mx-auto h-6 w-6 text-muted-foreground" />
          <p className="mt-3 font-medium">No accessible memory banks</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Banks appear here after they are created or assigned to your workspace membership.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-md border">
          <div className="hidden grid-cols-[minmax(0,1fr)_140px_120px] gap-4 border-b bg-muted/30 px-4 py-3 text-xs font-medium uppercase tracking-wide text-muted-foreground sm:grid">
            <span>Bank</span>
            <span>Updated</span>
            <span className="text-right">Open</span>
          </div>
          {banks.map((bank) => (
            <div
              key={bank.bank_id}
              className="grid grid-cols-1 items-start gap-3 border-b px-4 py-4 last:border-b-0 hover:bg-muted/20 sm:grid-cols-[minmax(0,1fr)_140px_120px] sm:items-center sm:gap-4"
            >
              <div className="min-w-0">
                <p className="truncate font-medium">{bank.name || bank.bank_id}</p>
                <p className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
                  {bank.bank_id}
                </p>
              </div>
              <span className="text-sm text-muted-foreground sm:text-left">
                Updated {formatDate(bank.updated_at)}
              </span>
              <Link
                href={`/banks/${encodeURIComponent(bank.bank_id)}?view=data`}
                className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline sm:justify-end"
              >
                View bank
                <ArrowUpRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
