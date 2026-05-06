"use client";

/**
 *
 * Landing dashboard — clean single-focus layout.
 * Progressive disclosure: hero CTA → existing banks → starter kits → benchmark.
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, CheckCircle2, FlaskConical, Loader2, Plus, Zap } from "lucide-react";
import { BankSelector } from "@/components/bank-selector";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useBank } from "@/lib/bank-context";
import { BenchmarkResponse, client } from "@/lib/api";

export default function DashboardPage() {
  const router = useRouter();
  const { currentBank, banks, loadBanks, setCurrentBank } = useBank();
  const [quickBankId, setQuickBankId] = useState("my-org");
  const [starterKit, setStarterKit] = useState<"" | "codebase">("");
  const [isCreatingQuickBank, setIsCreatingQuickBank] = useState(false);
  const [quickError, setQuickError] = useState("");
  const [quickMessage, setQuickMessage] = useState("");
  const [benchmark, setBenchmark] = useState<BenchmarkResponse | null>(null);
  const [isBenchmarkLoading, setIsBenchmarkLoading] = useState(true);
  const [isBenchmarkRunning, setIsBenchmarkRunning] = useState(false);
  const [benchmarkError, setBenchmarkError] = useState("");
  const bankCount = useMemo(() => banks.length, [banks]);

  // Redirect to bank page if a bank is selected
  useEffect(() => {
    if (currentBank) {
      router.push(`/banks/${currentBank}?view=data`);
    }
  }, [currentBank, router]);

  useEffect(() => {
    let cancelled = false;
    async function loadBenchmark() {
      setIsBenchmarkLoading(true);
      try {
        const response = await client.getBenchmark("live-api");
        if (!cancelled) {
          setBenchmark(response);
          setBenchmarkError("");
        }
      } catch (error) {
        if (!cancelled) {
          setBenchmarkError(error instanceof Error ? error.message : "Failed to load benchmark");
        }
      } finally {
        if (!cancelled) {
          setIsBenchmarkLoading(false);
        }
      }
    }
    void loadBenchmark();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleQuickCreate = async () => {
    const candidate = quickBankId.trim();
    if (!candidate) return;
    setIsCreatingQuickBank(true);
    setQuickError("");
    setQuickMessage("");
    try {
      await client.createBank(candidate, {
        bankPreset: starterKit || undefined,
      });
      await loadBanks();
      setCurrentBank(candidate);
      setQuickMessage(`Created "${candidate}". Redirecting...`);
      router.push(`/banks/${candidate}?view=data`);
    } catch (error) {
      setQuickError(error instanceof Error ? error.message : "Failed to create bank");
    } finally {
      setIsCreatingQuickBank(false);
    }
  };

  const openHeaderBankSelector = () => {
    window.scrollTo({ top: 0, behavior: "smooth" });
    window.dispatchEvent(new Event("atulya:open-bank-selector"));
  };

  const handleRunBenchmark = async () => {
    setIsBenchmarkRunning(true);
    setBenchmarkError("");
    try {
      const response = await client.runBenchmark("live-api");
      setBenchmark(response);
    } catch (error) {
      setBenchmarkError(error instanceof Error ? error.message : "Failed to run benchmark");
    } finally {
      setIsBenchmarkRunning(false);
    }
  };

  const liveOverall = benchmark?.leaderboard?.strategies?.api_memory_to_skill?.overall;
  const liveRecall = benchmark?.leaderboard?.strategies?.api_recall?.overall;

  return (
    <div className="min-h-screen bg-background">
      <BankSelector />

      {/* Single centered column — grows with viewport */}
      <div className="mx-auto w-full max-w-2xl px-4 sm:px-6 sm:max-w-3xl lg:max-w-4xl xl:max-w-5xl">
        {/* ── Hero ──────────────────────────────────────────────── */}
        <section className="flex flex-col items-center py-16 text-center sm:py-20 lg:py-24">
          {bankCount > 0 && (
            <span className="mb-6 inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/40 px-3 py-1 text-xs text-muted-foreground">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              {bankCount} space{bankCount === 1 ? "" : "s"} ready
            </span>
          )}

          <h1 className="max-w-none whitespace-normal text-3xl font-bold tracking-[-0.03em] text-foreground sm:whitespace-nowrap sm:text-4xl lg:text-[2.75rem] lg:leading-[1.15]">
            {bankCount > 0 ? (
              <>
                Choose a <span className="text-red-500">memory</span> space
              </>
            ) : (
              <>
                Create your first <span className="text-red-500">memory</span> space
              </>
            )}
          </h1>
          <p className="mt-3 text-sm text-muted-foreground sm:text-[15px]">
            {bankCount > 0
              ? "Open an existing space or create one for a brain, team, or workflow."
              : "Create a space for a brain, team, or workflow."}
          </p>

          {/* Quick-create row */}
          <div className="mt-8 flex w-full max-w-sm flex-col gap-2 sm:max-w-lg sm:flex-row">
            <Input
              value={quickBankId}
              onChange={(e) => setQuickBankId(e.target.value)}
              placeholder="e.g. founder-brain, sales-team"
              className="h-11 flex-1"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !isCreatingQuickBank) void handleQuickCreate();
              }}
            />
            <Button
              onClick={handleQuickCreate}
              disabled={isCreatingQuickBank || !quickBankId.trim()}
              className="h-11 shrink-0 gap-2 px-5"
            >
              {isCreatingQuickBank ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plus className="h-4 w-4" />
              )}
              {isCreatingQuickBank ? "Creating..." : "Create space"}
            </Button>
          </div>

          {quickError && (
            <p className="mt-2 text-xs text-red-600 dark:text-red-300">{quickError}</p>
          )}
          {quickMessage && (
            <p className="mt-2 text-xs text-emerald-600 dark:text-emerald-300">{quickMessage}</p>
          )}
        </section>

        {/* ── Your banks ────────────────────────────────────────── */}
        {bankCount > 0 && (
          <>
            <div className="border-t border-border" />
            <section className="py-10 sm:py-12">
              <p className="mb-4 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
                Your banks
              </p>
              <div
                className="grid gap-2"
                style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(100%, 180px), 1fr))" }}
              >
                {banks.map((bank) => (
                  <button
                    key={bank}
                    type="button"
                    onClick={() => setCurrentBank(bank)}
                    className="group flex items-center justify-between rounded-lg border border-border bg-card/60 px-3.5 py-3 text-left text-sm font-medium text-foreground transition-colors hover:bg-accent"
                  >
                    <span className="min-w-0 truncate pr-2">{bank}</span>
                    <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-colors group-hover:text-foreground" />
                  </button>
                ))}
              </div>
            </section>
          </>
        )}

        {/* ── Starter kits ──────────────────────────────────────── */}
        <div className="border-t border-border" />
        <section className="py-10 sm:py-12">
          <p className="mb-4 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
            Starter kits
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            {(
              [
                {
                  id: "" as const,
                  label: "Default (blank bank)",
                  desc: "Start clean with no presets. Best for custom workflows.",
                },
                {
                  id: "codebase" as const,
                  label: "Code repository kit",
                  desc: "Tuned retain/reflect rules, observation synthesis, pinned guides.",
                },
              ] as const
            ).map(({ id, label, desc }) => (
              <button
                key={id || "blank"}
                type="button"
                onClick={() => setStarterKit(id)}
                className={`rounded-xl border p-4 text-left transition-colors ${
                  starterKit === id
                    ? "border-red-500/60 bg-red-500/10"
                    : "border-border bg-card/60 hover:bg-muted/40"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-semibold leading-snug text-foreground">{label}</p>
                  {starterKit === id && (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
                  )}
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{desc}</p>
              </button>
            ))}
          </div>
        </section>

        {/* ── Benchmark Lab ─────────────────────────────────────── */}
        <div className="border-t border-border" />
        <section className="py-10 pb-20 sm:py-12 sm:pb-24">
          <div className="overflow-hidden rounded-xl border border-border bg-card/60">
            {/* Header */}
            <div className="flex items-center justify-between gap-4 px-5 py-4">
              <div className="flex items-center gap-2.5">
                <FlaskConical className="h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
                <p className="text-sm font-semibold text-foreground">Benchmark Lab</p>
                <span className="text-xs text-muted-foreground">
                  {isBenchmarkLoading
                    ? "Loading..."
                    : benchmark?.generated_at
                      ? `Last run ${new Date(benchmark.generated_at).toLocaleDateString()}`
                      : "No run yet"}
                </span>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={handleRunBenchmark}
                disabled={isBenchmarkRunning}
                className="h-8 gap-1.5 px-3 text-xs"
              >
                {isBenchmarkRunning ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Zap className="h-3.5 w-3.5" />
                )}
                {isBenchmarkRunning ? "Running..." : "Run benchmark"}
              </Button>
            </div>

            {/* Metrics — 4 equal columns, always */}
            <div className="grid grid-cols-2 border-t border-border sm:grid-cols-4">
              {[
                {
                  label: "API Recall",
                  value: liveRecall ? `${(liveRecall.recall_accuracy * 100).toFixed(0)}%` : "--",
                },
                {
                  label: "Memory-to-Skill",
                  value: liveOverall
                    ? `${((liveOverall.skill_reuse_success_rate ?? 0) * 100).toFixed(0)}%`
                    : "--",
                },
                {
                  label: "Answer Time",
                  value:
                    liveOverall?.time_to_useful_answer_ms != null
                      ? `${liveOverall.time_to_useful_answer_ms.toFixed(0)} ms`
                      : "--",
                },
                {
                  label: "Scenarios",
                  value: String(benchmark?.leaderboard?.scenario_count ?? "--"),
                },
              ].map(({ label, value }, i) => (
                <div
                  key={label}
                  className={`px-5 py-4 ${i > 0 ? "border-l border-border" : ""} ${i >= 2 ? "border-t border-border sm:border-t-0" : ""}`}
                >
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                    {label}
                  </p>
                  <p className="mt-1.5 font-mono text-xl font-bold leading-none text-foreground">
                    {value}
                  </p>
                </div>
              ))}
            </div>

            {benchmarkError && (
              <p className="border-t border-border px-5 py-3 text-xs text-red-600 dark:text-red-300">
                {benchmarkError}
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
