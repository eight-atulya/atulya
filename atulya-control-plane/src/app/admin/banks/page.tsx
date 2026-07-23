import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  Database,
  FileText,
  Link2,
  RefreshCw,
} from "lucide-react";
import { getCurrentIdentity } from "@/lib/server-auth";
import {
  loadWorkspaceBankSummaries,
  workspaceFetch,
  type WorkspaceBank,
  type WorkspaceBankSummary,
} from "@/lib/workspace-api";

function formatDate(value: string | null): string {
  if (!value) return "Never";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Unknown"
    : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatCount(value: number): string {
  return value.toLocaleString();
}

function getBankState(summary: WorkspaceBankSummary): {
  label: string;
  icon: typeof CheckCircle2;
  className: string;
} {
  if (summary.stats_error || !summary.stats) {
    return {
      label: "Stats unavailable",
      icon: AlertTriangle,
      className: "border-destructive/30 bg-destructive/5 text-destructive",
    };
  }
  if (summary.stats.failed_operations > 0) {
    return {
      label: "Needs attention",
      icon: AlertTriangle,
      className: "border-amber-500/30 bg-amber-500/5 text-amber-600 dark:text-amber-400",
    };
  }
  if (summary.stats.pending_operations > 0 || summary.stats.pending_consolidation > 0) {
    return {
      label: "Processing",
      icon: Clock3,
      className: "border-blue-500/30 bg-blue-500/5 text-blue-600 dark:text-blue-400",
    };
  }
  return {
    label: "Current",
    icon: CheckCircle2,
    className: "border-emerald-500/30 bg-emerald-500/5 text-emerald-600 dark:text-emerald-400",
  };
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Database;
  label: string;
  value: string;
}) {
  return (
    <div className="min-w-0 border-t px-4 py-3 first:border-t-0 sm:border-l sm:border-t-0 sm:first:border-l-0">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        <span>{label}</span>
      </div>
      <p className="mt-1 truncate text-lg font-semibold tabular-nums">{value}</p>
    </div>
  );
}

export default async function WorkspaceBanksPage() {
  const identity = await getCurrentIdentity();
  let banks: WorkspaceBankSummary[] = [];
  let error: string | null = null;

  try {
    const response = await workspaceFetch<{ banks: WorkspaceBank[] }>("/banks");
    banks = await loadWorkspaceBankSummaries(response.banks ?? []);
  } catch (reason) {
    error = reason instanceof Error ? reason.message : "Memory banks unavailable";
  }

  const availableStats = banks.flatMap((bank) => (bank.stats ? [bank.stats] : []));
  const attentionCount = banks.filter((bank) => {
    return (
      bank.stats_error ||
      !bank.stats ||
      bank.stats.failed_operations > 0 ||
      bank.stats.pending_operations > 0 ||
      bank.stats.pending_consolidation > 0
    );
  }).length;

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
            {banks.length} bank{banks.length === 1 ? "" : "s"} in your access scope
            {availableStats.length < banks.length ? " · Some stats unavailable" : ""}.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {attentionCount > 0 && (
            <span className="hidden text-xs text-muted-foreground sm:inline">
              {attentionCount} need{attentionCount === 1 ? "s" : ""} review
            </span>
          )}
          <Link
            href="/admin/banks"
            className="inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm transition-colors hover:bg-accent"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Link>
        </div>
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
        <div className="space-y-3">
          {banks.map((bank) => {
            const stats = bank.stats;
            const state = getBankState(bank);
            const StateIcon = state.icon;
            return (
              <article key={bank.bank_id} className="overflow-hidden rounded-md border bg-card">
                <div className="flex flex-wrap items-start justify-between gap-4 px-4 py-4 sm:px-5">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="truncate font-semibold">{bank.name || bank.bank_id}</h2>
                      <span
                        className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${state.className}`}
                      >
                        <StateIcon className="h-3 w-3" />
                        {state.label}
                      </span>
                    </div>
                    <p className="mt-1 truncate font-mono text-xs text-muted-foreground">
                      {bank.bank_id}
                    </p>
                    {bank.mission && (
                      <p className="mt-2 line-clamp-1 max-w-3xl text-sm text-muted-foreground">
                        {bank.mission}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
                    <span>Updated {formatDate(bank.updated_at)}</span>
                    <Link
                      href={`/banks/${encodeURIComponent(bank.bank_id)}?view=data`}
                      className="inline-flex h-8 items-center gap-1.5 rounded-md border border-highlight px-2.5 font-medium text-highlight transition-colors hover:bg-highlight hover:text-highlight-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-highlight"
                    >
                      Open
                      <ArrowUpRight className="h-3.5 w-3.5" />
                    </Link>
                  </div>
                </div>
                {stats ? (
                  <div className="grid grid-cols-2 border-t sm:grid-cols-3 lg:grid-cols-6">
                    <Metric
                      icon={Database}
                      label="Memories"
                      value={formatCount(stats.total_nodes)}
                    />
                    <Metric
                      icon={Activity}
                      label="Observations"
                      value={formatCount(stats.total_observations)}
                    />
                    <Metric
                      icon={FileText}
                      label="Documents"
                      value={formatCount(stats.total_documents)}
                    />
                    <Metric icon={Link2} label="Links" value={formatCount(stats.total_links)} />
                    <Metric
                      icon={Clock3}
                      label="Queue"
                      value={`${formatCount(stats.pending_operations)} pending`}
                    />
                    <Metric
                      icon={AlertTriangle}
                      label="Failed"
                      value={formatCount(stats.failed_operations)}
                    />
                  </div>
                ) : (
                  <div className="border-t px-4 py-3 text-sm text-muted-foreground">
                    Live stats are temporarily unavailable. The bank is still visible because access
                    was confirmed by the scoped bank list.
                  </div>
                )}
                {stats && (
                  <div className="border-t px-4 py-2.5 text-xs text-muted-foreground">
                    Consolidation: {formatCount(stats.pending_consolidation)} pending
                    {stats.last_consolidated_at
                      ? ` · Last run ${formatDate(stats.last_consolidated_at)}`
                      : " · No completed run yet"}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
