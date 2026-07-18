"use client";

import { type MouseEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
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

function formatBucketLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
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

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function parseJsonString(value: unknown): unknown {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function unwrapTracePayload(value: unknown): unknown {
  const parsed = parseJsonString(value);
  const record = asRecord(parsed);
  if (!record) return parsed;
  if (record.kind === "array" && Array.isArray(record.items)) return record.items;
  if (record.kind === "text" && typeof record.text === "string") return record.text;
  if (record.kind === "value" && "value" in record) return record.value;
  return parsed;
}

type TraceMessage = {
  role: string;
  content: unknown;
  index: number;
};

type ActivityHoverHint = {
  label: string;
  tone: string;
  description: string;
};

type ActivityTooltip = {
  bucket: string;
  x: number;
  y: number;
  hint?: ActivityHoverHint;
};

function extractMessages(value: unknown): TraceMessage[] {
  const parsed = unwrapTracePayload(value);
  const source = asRecord(parsed)?.messages ?? parsed;
  if (!Array.isArray(source)) return [];

  return source.flatMap((item, index) => {
    const record = asRecord(item);
    if (!record || !("content" in record)) return [];
    return [
      {
        role: typeof record.role === "string" && record.role ? record.role : `message ${index + 1}`,
        content: record.content,
        index,
      },
    ];
  });
}

function textFromContent(value: unknown): string {
  if (typeof value === "string") return value;
  return formatJson(value);
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
  const displayValue = useMemo(() => unwrapTracePayload(value), [value]);
  const formatted = useMemo(() => formatJson(displayValue), [displayValue]);
  return (
    <div className="min-h-0 rounded-lg border border-border">
      <div className="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{title}</p>
          <p className="text-xs text-muted-foreground">{payloadSummary(displayValue)}</p>
        </div>
        <CopyButton text={formatted} label="Copy JSON" />
      </div>
      <pre className="max-h-[46vh] overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-xs leading-5 text-foreground">
        {formatted}
      </pre>
    </div>
  );
}

function InputPayloadPanel({ value }: { value: unknown }) {
  const displayValue = useMemo(() => unwrapTracePayload(value), [value]);
  const formatted = useMemo(() => formatJson(displayValue), [displayValue]);
  const messages = useMemo(() => extractMessages(value), [value]);

  if (!messages.length) {
    return <JsonPanel title="Input payload" value={value} />;
  }

  const totalChars = messages.reduce(
    (sum, message) => sum + textFromContent(message.content).length,
    0
  );

  return (
    <div className="min-h-0 rounded-lg border border-border">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-3 py-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">Input payload</p>
          <p className="text-xs text-muted-foreground">
            {messages.length.toLocaleString()} message{messages.length === 1 ? "" : "s"} |{" "}
            {totalChars.toLocaleString()} chars
          </p>
        </div>
        <CopyButton text={formatted} label="Copy JSON" />
      </div>

      <div className="max-h-[56vh] space-y-3 overflow-auto p-3">
        {messages.map((message) => {
          const contentText = textFromContent(message.content);
          const isText = typeof message.content === "string";

          return (
            <section
              key={`${message.role}-${message.index}`}
              className="overflow-hidden rounded-md border border-border bg-background"
            >
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-muted/30 px-3 py-2">
                <div className="flex min-w-0 items-center gap-2">
                  <Badge variant="outline" className="shrink-0 capitalize">
                    {message.role}
                  </Badge>
                  <span className="truncate text-xs text-muted-foreground">
                    {contentText.length.toLocaleString()} chars
                  </span>
                </div>
                <CopyButton text={contentText} label="Copy text" />
              </div>
              <pre
                className={cn(
                  "max-h-[40vh] overflow-auto whitespace-pre-wrap break-words p-3 leading-6 text-foreground",
                  isText ? "font-sans text-sm" : "font-mono text-xs"
                )}
              >
                {contentText}
              </pre>
            </section>
          );
        })}

        <details className="rounded-md border border-border bg-muted/20">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-muted-foreground">
            Raw JSON
          </summary>
          <pre className="max-h-[32vh] overflow-auto whitespace-pre-wrap break-words border-t border-border p-3 font-mono text-xs leading-5 text-foreground">
            {formatted}
          </pre>
        </details>
      </div>
    </div>
  );
}

function TraceTimeline({ buckets }: { buckets: LLMRequestStatsBucket[] }) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const [tooltip, setTooltip] = useState<ActivityTooltip | null>(null);
  const grouped = useMemo(() => {
    const map = new Map<
      string,
      {
        bucket: string;
        success: number;
        error: number;
        other: number;
        inputTokens: number;
        outputTokens: number;
        cachedTokens: number;
        totalTokens: number;
      }
    >();
    for (const item of buckets) {
      const current = map.get(item.bucket) ?? {
        bucket: item.bucket,
        success: 0,
        error: 0,
        other: 0,
        inputTokens: 0,
        outputTokens: 0,
        cachedTokens: 0,
        totalTokens: 0,
      };
      if (item.status === "success") current.success += item.count;
      else if (item.status === "error") current.error += item.count;
      else current.other += item.count;
      current.inputTokens += item.input_tokens || 0;
      current.outputTokens += item.output_tokens || 0;
      current.cachedTokens += item.cached_tokens || 0;
      current.totalTokens += item.total_tokens || 0;
      map.set(item.bucket, current);
    }
    return Array.from(map.values())
      .sort((a, b) => Date.parse(a.bucket) - Date.parse(b.bucket))
      .slice(-28);
  }, [buckets]);

  const maxCount = Math.max(1, ...grouped.map((item) => item.success + item.error + item.other));
  const maxTokens = Math.max(1, ...grouped.map((item) => item.totalTokens));
  const activeBucket = tooltip ? grouped.find((item) => item.bucket === tooltip.bucket) : null;
  const activeTotal = activeBucket
    ? activeBucket.success + activeBucket.error + activeBucket.other
    : 0;
  const activeSuccessPct =
    activeBucket && activeTotal ? Math.round((activeBucket.success / activeTotal) * 100) : 0;
  const activeErrorPct =
    activeBucket && activeTotal ? Math.round((activeBucket.error / activeTotal) * 100) : 0;

  const setTooltipPosition = (
    bucket: string,
    rawX: number,
    rawY: number,
    hint?: ActivityHoverHint
  ) => {
    const rect = chartRef.current?.getBoundingClientRect();
    if (!rect) return;

    setTooltip((previous) => {
      const nextHint = hint ?? (previous?.bucket === bucket ? previous.hint : undefined);
      const tooltipWidth = 320;
      const tooltipHeight = 230;
      const nextX = rawX + 16;
      const nextY = rawY + 16;

      return {
        bucket,
        hint: nextHint,
        x: Math.min(Math.max(nextX, 12), Math.max(12, rect.width - tooltipWidth - 12)),
        y: Math.min(Math.max(nextY, 12), Math.max(12, rect.height - tooltipHeight - 12)),
      };
    });
  };

  const showTooltip = (
    bucket: string,
    event: MouseEvent<HTMLElement>,
    hint?: ActivityHoverHint
  ) => {
    const rect = chartRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTooltipPosition(bucket, event.clientX - rect.left, event.clientY - rect.top, hint);
  };

  const showTooltipFromElement = (bucket: string, element: HTMLElement) => {
    const rect = chartRef.current?.getBoundingClientRect();
    const elementRect = element.getBoundingClientRect();
    if (!rect) return;
    setTooltipPosition(
      bucket,
      elementRect.left - rect.left + elementRect.width / 2,
      elementRect.top - rect.top
    );
  };

  if (!grouped.length) {
    return (
      <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
        No LLM calls recorded in this window
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card/70 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">Activity</p>
          <p className="text-xs text-muted-foreground">Status by time bucket with token mix</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-x-4 gap-y-2 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            success
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-red-500" />
            error
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-sky-500" />
            other
          </span>
          <span className="hidden h-4 w-px bg-border sm:inline-block" />
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-amber-500" />
            input
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-cyan-500" />
            output
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-zinc-500" />
            cached
          </span>
        </div>
      </div>

      <div ref={chartRef} className="relative mt-4 border-t border-border pt-4">
        <div
          className="flex h-52 items-end gap-2 overflow-x-auto overflow-y-hidden"
          onMouseLeave={() => setTooltip(null)}
        >
          {grouped.map((item) => {
            const total = item.success + item.error + item.other;
            const height = Math.max(16, Math.round((total / maxCount) * 100));
            const label = formatBucketLabel(item.bucket);
            const tokenHeight = Math.max(8, Math.round((item.totalTokens / maxTokens) * 100));
            const tokenRailHeight = Math.max(4, Math.round(tokenHeight / 4));
            const isActive = item.bucket === activeBucket?.bucket;
            return (
              <button
                type="button"
                key={item.bucket}
                className="flex h-full min-w-16 flex-1 flex-col items-center justify-end gap-1.5 rounded-sm bg-transparent p-0 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label={`${label}: ${total} calls, ${item.success} success, ${item.error} error, ${formatNumber(item.totalTokens)} tokens`}
                onBlur={() => setTooltip(null)}
                onFocus={(event) => showTooltipFromElement(item.bucket, event.currentTarget)}
                onMouseEnter={(event) => showTooltip(item.bucket, event)}
                onMouseMove={(event) => showTooltip(item.bucket, event)}
              >
                <span className="font-mono text-[10px] text-muted-foreground">
                  {formatNumber(total)} calls
                </span>
                <div
                  className={cn(
                    "flex w-full min-w-6 max-w-10 flex-col-reverse overflow-hidden rounded-t bg-muted/70 ring-1 transition",
                    isActive ? "ring-2 ring-primary/70" : "ring-border"
                  )}
                  style={{ height: `${height}%` }}
                >
                  {item.success > 0 && (
                    <div
                      className="min-h-1 bg-emerald-500"
                      style={{ flex: item.success }}
                      onMouseEnter={(event) =>
                        showTooltip(item.bucket, event, {
                          label: "Success calls",
                          tone: "text-emerald-600 dark:text-emerald-300",
                          description:
                            "Completed normally and produced an output payload you can inspect in the trace drawer.",
                        })
                      }
                      onMouseMove={(event) =>
                        showTooltip(item.bucket, event, {
                          label: "Success calls",
                          tone: "text-emerald-600 dark:text-emerald-300",
                          description:
                            "Completed normally and produced an output payload you can inspect in the trace drawer.",
                        })
                      }
                    />
                  )}
                  {item.other > 0 && (
                    <div
                      className="min-h-1 bg-sky-500"
                      style={{ flex: item.other }}
                      onMouseEnter={(event) =>
                        showTooltip(item.bucket, event, {
                          label: "Other status",
                          tone: "text-sky-600 dark:text-sky-300",
                          description:
                            "Neither success nor error, such as in-flight, skipped, or provider states that need separate inspection.",
                        })
                      }
                      onMouseMove={(event) =>
                        showTooltip(item.bucket, event, {
                          label: "Other status",
                          tone: "text-sky-600 dark:text-sky-300",
                          description:
                            "Neither success nor error, such as in-flight, skipped, or provider states that need separate inspection.",
                        })
                      }
                    />
                  )}
                  {item.error > 0 && (
                    <div
                      className="min-h-1 bg-red-500"
                      style={{ flex: item.error }}
                      onMouseEnter={(event) =>
                        showTooltip(item.bucket, event, {
                          label: "Errored calls",
                          tone: "text-red-600 dark:text-red-300",
                          description:
                            "Failed before a clean LLM result was recorded. Open a failed row and check the Error tab.",
                        })
                      }
                      onMouseMove={(event) =>
                        showTooltip(item.bucket, event, {
                          label: "Errored calls",
                          tone: "text-red-600 dark:text-red-300",
                          description:
                            "Failed before a clean LLM result was recorded. Open a failed row and check the Error tab.",
                        })
                      }
                    />
                  )}
                </div>
                <div
                  className={cn(
                    "flex w-full max-w-14 overflow-hidden rounded-sm bg-muted/50 ring-1 transition",
                    isActive ? "ring-primary/70" : "ring-border"
                  )}
                  style={{ height: `${tokenRailHeight}px` }}
                >
                  {item.inputTokens > 0 && (
                    <div
                      className="bg-amber-500"
                      style={{ flex: item.inputTokens }}
                      onMouseEnter={(event) =>
                        showTooltip(item.bucket, event, {
                          label: "Input tokens",
                          tone: "text-amber-600 dark:text-amber-300",
                          description:
                            "Prompt, context, schema, memories, and instructions sent into the model.",
                        })
                      }
                      onMouseMove={(event) =>
                        showTooltip(item.bucket, event, {
                          label: "Input tokens",
                          tone: "text-amber-600 dark:text-amber-300",
                          description:
                            "Prompt, context, schema, memories, and instructions sent into the model.",
                        })
                      }
                    />
                  )}
                  {item.outputTokens > 0 && (
                    <div
                      className="bg-cyan-500"
                      style={{ flex: item.outputTokens }}
                      onMouseEnter={(event) =>
                        showTooltip(item.bucket, event, {
                          label: "Output tokens",
                          tone: "text-cyan-600 dark:text-cyan-300",
                          description:
                            "Tokens generated by the model. Higher output means a larger answer or structured result.",
                        })
                      }
                      onMouseMove={(event) =>
                        showTooltip(item.bucket, event, {
                          label: "Output tokens",
                          tone: "text-cyan-600 dark:text-cyan-300",
                          description:
                            "Tokens generated by the model. Higher output means a larger answer or structured result.",
                        })
                      }
                    />
                  )}
                  {item.cachedTokens > 0 && (
                    <div
                      className="bg-zinc-500"
                      style={{ flex: item.cachedTokens }}
                      onMouseEnter={(event) =>
                        showTooltip(item.bucket, event, {
                          label: "Cached tokens",
                          tone: "text-zinc-600 dark:text-zinc-300",
                          description:
                            "Prompt tokens the provider reused from cache, which can reduce latency or cost.",
                        })
                      }
                      onMouseMove={(event) =>
                        showTooltip(item.bucket, event, {
                          label: "Cached tokens",
                          tone: "text-zinc-600 dark:text-zinc-300",
                          description:
                            "Prompt tokens the provider reused from cache, which can reduce latency or cost.",
                        })
                      }
                    />
                  )}
                </div>
                <span className="w-20 truncate text-center text-[10px] text-muted-foreground">
                  {label}
                </span>
              </button>
            );
          })}
        </div>

        {tooltip && activeBucket && (
          <div
            className="pointer-events-none absolute z-20 w-80 rounded-md border border-border bg-popover p-3 text-popover-foreground shadow-xl"
            style={{ left: tooltip.x, top: tooltip.y }}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate font-mono text-xs font-semibold">
                  {formatBucketLabel(activeBucket.bucket)}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {formatNumber(activeTotal)} calls | {activeSuccessPct}% success | {activeErrorPct}
                  % error
                </p>
              </div>
              {tooltip.hint && (
                <span className={cn("shrink-0 text-xs font-medium", tooltip.hint.tone)}>
                  {tooltip.hint.label}
                </span>
              )}
            </div>

            <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
              <div className="rounded border border-border bg-muted/30 px-2 py-1.5">
                <p className="text-muted-foreground">Success</p>
                <p className="font-mono font-semibold text-foreground">
                  {formatNumber(activeBucket.success)}
                </p>
              </div>
              <div className="rounded border border-border bg-muted/30 px-2 py-1.5">
                <p className="text-muted-foreground">Error</p>
                <p className="font-mono font-semibold text-foreground">
                  {formatNumber(activeBucket.error)}
                </p>
              </div>
              <div className="rounded border border-border bg-muted/30 px-2 py-1.5">
                <p className="text-muted-foreground">Other</p>
                <p className="font-mono font-semibold text-foreground">
                  {formatNumber(activeBucket.other)}
                </p>
              </div>
            </div>

            <div className="mt-3">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">Token mix</span>
                <span className="font-mono text-muted-foreground">
                  {formatNumber(activeBucket.totalTokens)} total
                </span>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 font-mono text-xs text-muted-foreground">
                <span>{formatNumber(activeBucket.inputTokens)} in</span>
                <span>{formatNumber(activeBucket.outputTokens)} out</span>
                <span>{formatNumber(activeBucket.cachedTokens)} cached</span>
              </div>
            </div>

            {tooltip.hint && (
              <p className="mt-3 border-t border-border pt-2 text-xs leading-5 text-muted-foreground">
                {tooltip.hint.description}
              </p>
            )}
          </div>
        )}
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
                  <InputPayloadPanel value={selected.input} />
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
