"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Clock3,
  Copy,
  Loader2,
  RefreshCw,
  Search,
  ServerCog,
  XCircle,
} from "lucide-react";
import { client, type LLMRequestRow, type LLMRequestStatsBucket } from "@/lib/api";
import { useBank } from "@/lib/bank-context";
import { useFeatures } from "@/lib/features-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/copy-button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 50;

const OPERATION_OPTIONS = [
  "retain",
  "consolidation",
  "reflect",
  "internet_research",
  "dream",
  "entity_trajectory",
  "entity_intelligence",
  "merge_bank_mission",
  "mental_model_refresh",
];

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "N/A";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return "0";
  return new Intl.NumberFormat().format(value);
}

function formatDuration(value: number | null | undefined): string {
  if (value === null || value === undefined) return "N/A";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)} s`;
}

function shortId(value: string | null | undefined, length = 8): string {
  if (!value) return "N/A";
  return value.length <= length ? value : value.slice(0, length);
}

function labelize(value: string | null | undefined): string {
  if (!value) return "N/A";
  return value.replace(/_/g, " ");
}

function formatJson(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  return JSON.stringify(value, null, 2);
}

function payloadSummary(value: unknown): string {
  if (value === null || value === undefined) return "empty";
  if (typeof value === "string") return `${value.length.toLocaleString()} chars`;
  if (Array.isArray(value)) return `${value.length.toLocaleString()} items`;
  if (typeof value === "object") return `${Object.keys(value).length.toLocaleString()} keys`;
  return typeof value;
}

function statusClass(status: string) {
  if (status === "success") {
    return "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
  }
  if (status === "error") {
    return "border-red-500/20 bg-red-500/10 text-red-700 dark:text-red-300";
  }
  return "border-sky-500/20 bg-sky-500/10 text-sky-700 dark:text-sky-300";
}

function StatBlock({
  label,
  value,
  sub,
  icon: Icon,
}: {
  label: string;
  value: string;
  sub?: string;
  icon: typeof Activity;
}) {
  return (
    <div className="rounded-lg border border-border bg-card/70 p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase text-muted-foreground">{label}</p>
          <p className="mt-1 truncate text-2xl font-semibold text-foreground">{value}</p>
          {sub && <p className="mt-1 truncate text-xs text-muted-foreground">{sub}</p>}
        </div>
        <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
      </div>
    </div>
  );
}

function JsonPanel({ title, value }: { title: string; value: unknown }) {
  const formatted = useMemo(() => formatJson(value), [value]);
  return (
    <div className="min-h-0 rounded-lg border border-border">
      <div className="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{title}</p>
          <p className="text-xs text-muted-foreground">{payloadSummary(value)}</p>
        </div>
        <CopyButton text={formatted} label="Copy JSON" />
      </div>
      <pre className="max-h-[46vh] overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-xs leading-5 text-foreground">
        {formatted}
      </pre>
    </div>
  );
}

function TraceTimeline({ buckets }: { buckets: LLMRequestStatsBucket[] }) {
  const grouped = useMemo(() => {
    const map = new Map<
      string,
      { bucket: string; success: number; error: number; other: number }
    >();
    for (const item of buckets) {
      const current = map.get(item.bucket) ?? {
        bucket: item.bucket,
        success: 0,
        error: 0,
        other: 0,
      };
      if (item.status === "success") current.success += item.count;
      else if (item.status === "error") current.error += item.count;
      else current.other += item.count;
      map.set(item.bucket, current);
    }
    return Array.from(map.values())
      .sort((a, b) => Date.parse(a.bucket) - Date.parse(b.bucket))
      .slice(-28);
  }, [buckets]);

  const maxCount = Math.max(1, ...grouped.map((item) => item.success + item.error + item.other));

  if (!grouped.length) {
    return (
      <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
        No trace activity in this window
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card/70 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">Activity</p>
          <p className="text-xs text-muted-foreground">{grouped.length} buckets</p>
        </div>
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            success
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-red-500" />
            error
          </span>
        </div>
      </div>
      <div className="flex h-28 items-end gap-1.5 overflow-hidden">
        {grouped.map((item) => {
          const total = item.success + item.error + item.other;
          const height = Math.max(8, Math.round((total / maxCount) * 100));
          const errorPct = total ? Math.round((item.error / total) * 100) : 0;
          const label = formatDateTime(item.bucket);
          return (
            <div key={item.bucket} className="flex min-w-3 flex-1 flex-col items-center gap-1">
              <div
                className="flex w-full max-w-5 flex-col justify-end overflow-hidden rounded-sm bg-muted"
                style={{ height: `${height}%` }}
                title={`${label}: ${total} calls, ${item.error} errors`}
              >
                {item.error > 0 && (
                  <div className="bg-red-500" style={{ height: `${errorPct}%` }} />
                )}
                {item.success > 0 && <div className="flex-1 bg-emerald-500" />}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DetailField({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md border border-border bg-muted/30 px-3 py-2">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 truncate font-mono text-xs text-foreground" title={value}>
        {value}
      </p>
    </div>
  );
}

export function LLMTracesView() {
  const { currentBank } = useBank();
  const { features } = useFeatures();
  const [rows, setRows] = useState<LLMRequestRow[]>([]);
  const [stats, setStats] = useState<LLMRequestStatsBucket[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<LLMRequestRow | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [operationFilter, setOperationFilter] = useState<string>("all");
  const [periodHours, setPeriodHours] = useState("24");
  const [providerInput, setProviderInput] = useState("");
  const [traceInput, setTraceInput] = useState("");
  const [providerFilter, setProviderFilter] = useState("");
  const [traceFilter, setTraceFilter] = useState("");

  const loadRows = useCallback(
    async (nextOffset = offset) => {
      if (!currentBank) return;
      setLoading(true);
      try {
        const result = await client.listLLMRequests(currentBank, {
          limit: PAGE_SIZE,
          offset: nextOffset,
          status: statusFilter === "all" ? undefined : statusFilter,
          operation: operationFilter === "all" ? undefined : operationFilter,
          provider: providerFilter || undefined,
          trace_id: traceFilter || undefined,
        });
        setRows(result.items || []);
        setTotal(result.total || 0);
        setOffset(result.offset || 0);
      } catch {
        setRows([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [currentBank, offset, operationFilter, providerFilter, statusFilter, traceFilter]
  );

  const loadStats = useCallback(async () => {
    if (!currentBank) return;
    try {
      const result = await client.getLLMRequestStats(currentBank, {
        period_hours: Number(periodHours),
        trunc: periodHours === "1" ? "minute" : "hour",
      });
      setStats(result.items || []);
    } catch {
      setStats([]);
    }
  }, [currentBank, periodHours]);

  const refresh = useCallback(
    async (nextOffset = offset) => {
      await Promise.all([loadRows(nextOffset), loadStats()]);
    },
    [loadRows, loadStats, offset]
  );

  useEffect(() => {
    if (!currentBank) return;
    setOffset(0);
    void refresh(0);
  }, [currentBank, statusFilter, operationFilter, providerFilter, traceFilter, periodHours]);

  const summary = useMemo(() => {
    const success = stats
      .filter((item) => item.status === "success")
      .reduce((sum, item) => sum + item.count, 0);
    const errors = stats
      .filter((item) => item.status === "error")
      .reduce((sum, item) => sum + item.count, 0);
    const tokens = stats.reduce((sum, item) => sum + (item.total_tokens || 0), 0);
    const providers = new Set(rows.map((row) => row.provider).filter(Boolean)).size;
    const avgMs =
      rows.length > 0
        ? Math.round(rows.reduce((sum, row) => sum + (row.duration_ms || 0), 0) / rows.length)
        : 0;
    return { success, errors, tokens, providers, avgMs };
  }, [rows, stats]);

  const groupedTraceCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of rows) {
      if (row.trace_id) counts.set(row.trace_id, (counts.get(row.trace_id) || 0) + 1);
    }
    return counts;
  }, [rows]);

  const pageEnd = Math.min(offset + PAGE_SIZE, total);
  const featureEnabled = features?.llm_trace ?? false;

  if (!currentBank) return null;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="text-3xl font-bold text-foreground">LLM Traces</h1>
            <Badge
              variant="outline"
              className={cn("capitalize", featureEnabled ? "text-emerald-600" : "text-amber-600")}
            >
              {featureEnabled ? "capture on" : "capture off"}
            </Badge>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            Provider calls, prompts, outputs, usage, and failures.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={periodHours} onValueChange={setPeriodHours}>
            <SelectTrigger className="h-9 w-[135px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="1">Last hour</SelectItem>
              <SelectItem value="24">24 hours</SelectItem>
              <SelectItem value="168">7 days</SelectItem>
              <SelectItem value="720">30 days</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={() => refresh()} disabled={loading}>
            <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <StatBlock
          label="Calls"
          value={formatNumber(summary.success + summary.errors)}
          sub={`${formatNumber(total)} matched rows`}
          icon={Activity}
        />
        <StatBlock
          label="Errors"
          value={formatNumber(summary.errors)}
          sub={`${summary.success} successful in window`}
          icon={XCircle}
        />
        <StatBlock
          label="Tokens"
          value={formatNumber(summary.tokens)}
          sub="input + output + cached"
          icon={ServerCog}
        />
        <StatBlock
          label="Latency"
          value={formatDuration(summary.avgMs)}
          sub={`${summary.providers} providers on page`}
          icon={Clock3}
        />
      </div>

      <TraceTimeline buckets={stats} />

      <div className="rounded-lg border border-border bg-card/70 shadow-sm">
        <div className="border-b border-border p-4">
          <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
            <div className="grid flex-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  Status
                </label>
                <div className="flex h-9 rounded-md bg-muted p-1">
                  {["all", "success", "error"].map((status) => (
                    <button
                      key={status}
                      onClick={() => setStatusFilter(status)}
                      className={cn(
                        "flex-1 rounded-sm px-3 text-sm font-medium capitalize transition-colors",
                        statusFilter === status
                          ? "bg-background text-foreground shadow-sm"
                          : "text-muted-foreground"
                      )}
                    >
                      {status}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  Operation
                </label>
                <Select value={operationFilter} onValueChange={setOperationFilter}>
                  <SelectTrigger className="h-9">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All operations</SelectItem>
                    {OPERATION_OPTIONS.map((operation) => (
                      <SelectItem key={operation} value={operation}>
                        {labelize(operation)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  Provider
                </label>
                <Input
                  className="h-9"
                  value={providerInput}
                  placeholder="openai, groq, gemini"
                  onChange={(event) => setProviderInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      setProviderFilter(providerInput.trim());
                      setOffset(0);
                    }
                  }}
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                  Trace ID
                </label>
                <Input
                  className="h-9 font-mono text-xs"
                  value={traceInput}
                  placeholder="trace_id"
                  onChange={(event) => setTraceInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      setTraceFilter(traceInput.trim());
                      setOffset(0);
                    }
                  }}
                />
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setProviderFilter(providerInput.trim());
                  setTraceFilter(traceInput.trim());
                  setOffset(0);
                }}
              >
                <Search className="h-4 w-4" />
                Apply
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setStatusFilter("all");
                  setOperationFilter("all");
                  setProviderInput("");
                  setTraceInput("");
                  setProviderFilter("");
                  setTraceFilter("");
                  setOffset(0);
                }}
              >
                Clear
              </Button>
            </div>
          </div>
        </div>

        <Table>
          <TableHeader className="sticky top-0 z-10 bg-card">
            <TableRow>
              <TableHead className="w-[150px]">Time</TableHead>
              <TableHead>Operation</TableHead>
              <TableHead>Scope</TableHead>
              <TableHead>Provider</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Tokens</TableHead>
              <TableHead className="text-right">Latency</TableHead>
              <TableHead>Trace</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={8} className="h-32 text-center">
                  <div className="inline-flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Loading traces
                  </div>
                </TableCell>
              </TableRow>
            ) : rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="h-32 text-center text-sm text-muted-foreground">
                  No traces found
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => {
                const traceCount = row.trace_id ? groupedTraceCounts.get(row.trace_id) || 1 : 1;
                return (
                  <TableRow
                    key={row.id}
                    className={cn("cursor-pointer", selected?.id === row.id && "bg-muted/70")}
                    onClick={() => setSelected(row)}
                  >
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {formatDateTime(row.started_at)}
                    </TableCell>
                    <TableCell>
                      <div
                        className="max-w-[170px] truncate font-medium"
                        title={row.operation || ""}
                      >
                        {labelize(row.operation)}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div
                        className="max-w-[180px] truncate font-mono text-xs"
                        title={row.scope || ""}
                      >
                        {row.scope || "N/A"}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="max-w-[180px]">
                        <p className="truncate text-sm font-medium">{row.provider || "N/A"}</p>
                        <p
                          className="truncate text-xs text-muted-foreground"
                          title={row.model || ""}
                        >
                          {row.model || "model unknown"}
                        </p>
                      </div>
                    </TableCell>
                    <TableCell>
                      <span
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium",
                          statusClass(row.status)
                        )}
                      >
                        {row.status === "success" ? (
                          <CheckCircle2 className="h-3 w-3" />
                        ) : (
                          <AlertCircle className="h-3 w-3" />
                        )}
                        {row.status}
                      </span>
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {formatNumber(row.total_tokens)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {formatDuration(row.duration_ms)}
                    </TableCell>
                    <TableCell>
                      <div className="max-w-[170px]">
                        <p className="truncate font-mono text-xs" title={row.trace_id || ""}>
                          {shortId(row.trace_id, 12)}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {traceCount} call{traceCount === 1 ? "" : "s"}
                        </p>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>

        <div className="flex flex-col gap-3 border-t border-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-muted-foreground">
            {total > 0 ? `Showing ${offset + 1}-${pageEnd} of ${total}` : "Showing 0 traces"}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => refresh(Math.max(0, offset - PAGE_SIZE))}
              disabled={offset === 0 || loading}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refresh(offset + PAGE_SIZE)}
              disabled={offset + PAGE_SIZE >= total || loading}
            >
              Next
            </Button>
          </div>
        </div>
      </div>

      <Sheet open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <SheetContent className="flex w-[92vw] max-w-none flex-col p-0 sm:max-w-5xl">
          {selected && (
            <>
              <SheetHeader className="border-b border-border px-5 py-4">
                <div className="flex items-start justify-between gap-8 pr-8">
                  <div className="min-w-0">
                    <SheetTitle className="truncate">{labelize(selected.operation)}</SheetTitle>
                    <SheetDescription className="font-mono text-xs">
                      {selected.trace_id || "trace unavailable"}
                    </SheetDescription>
                  </div>
                  <Badge className={statusClass(selected.status)} variant="outline">
                    {selected.status}
                  </Badge>
                </div>
              </SheetHeader>

              <div className="grid gap-3 border-b border-border p-5 md:grid-cols-3 xl:grid-cols-6">
                <DetailField label="Provider" value={selected.provider || "N/A"} />
                <DetailField label="Model" value={selected.model || "N/A"} />
                <DetailField label="Scope" value={selected.scope || "N/A"} />
                <DetailField label="Started" value={formatDateTime(selected.started_at)} />
                <DetailField label="Latency" value={formatDuration(selected.duration_ms)} />
                <DetailField label="Tokens" value={formatNumber(selected.total_tokens)} />
              </div>

              <Tabs defaultValue="input" className="flex min-h-0 flex-1 flex-col p-5">
                <TabsList className="w-fit">
                  <TabsTrigger value="input">Input</TabsTrigger>
                  <TabsTrigger value="output">Output</TabsTrigger>
                  <TabsTrigger value="error">Error</TabsTrigger>
                  <TabsTrigger value="metadata">Metadata</TabsTrigger>
                </TabsList>
                <TabsContent value="input" className="min-h-0 flex-1">
                  <JsonPanel title="Input payload" value={selected.input} />
                </TabsContent>
                <TabsContent value="output" className="min-h-0 flex-1">
                  <JsonPanel title="Output payload" value={selected.output} />
                </TabsContent>
                <TabsContent value="error" className="min-h-0 flex-1">
                  <JsonPanel title="Error payload" value={selected.error} />
                </TabsContent>
                <TabsContent value="metadata" className="min-h-0 flex-1">
                  <div className="grid gap-4 lg:grid-cols-2">
                    <JsonPanel title="LLM info" value={selected.llm_info} />
                    <JsonPanel title="Operation metadata" value={selected.metadata} />
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <DetailField label="Request ID" value={selected.id} />
                    <DetailField label="Span ID" value={selected.span_id || "N/A"} />
                    <DetailField label="Parent Span" value={selected.parent_span_id || "N/A"} />
                    <div className="flex min-w-0 items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-2">
                      <Copy className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <CopyButton text={selected.trace_id || ""} label="Copy trace ID" />
                    </div>
                  </div>
                </TabsContent>
              </Tabs>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
