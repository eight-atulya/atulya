"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Brain,
  Building2,
  ChartNoAxesCombined,
  FlaskConical,
  Sparkles,
  Wand2,
} from "lucide-react";
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
    <div className="min-h-screen bg-background flex flex-col">
      <BankSelector />

      <div className="relative min-h-[calc(100vh-80px)] overflow-hidden bg-gradient-to-b from-muted/40 via-background to-background">
        <div className="pointer-events-none absolute inset-0 opacity-60">
          <div className="absolute left-[15%] top-[18%] h-40 w-40 rounded-full bg-red-500/10 blur-3xl" />
          <div className="absolute right-[12%] top-[28%] h-52 w-52 rounded-full bg-orange-500/10 blur-3xl" />
          <div className="absolute left-[35%] bottom-[15%] h-44 w-44 rounded-full bg-rose-500/10 blur-3xl" />
        </div>

        <div className="relative z-10 mx-auto flex h-full w-full max-w-6xl items-center px-6 py-12">
          <div className="grid w-full gap-6 lg:grid-cols-[1.2fr_0.8fr]">
            <section className="rounded-2xl border border-border/60 bg-card/80 p-8 shadow-xl backdrop-blur-sm">
              <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-red-500/20 bg-red-500/10 px-3 py-1 text-xs font-medium text-red-700 dark:text-red-300">
                <Sparkles className="h-3.5 w-3.5" />
                Never stop learning
              </div>
              <h1 className="text-3xl font-bold tracking-tight text-card-foreground md:text-4xl">
                Learn continuously about your people, your workflows, and your organization.
              </h1>
              <p className="mt-4 max-w-2xl text-base text-muted-foreground">
                Build a living memory system that turns historical evidence into better decisions.
                Atulya helps teams move from guesswork to math-backed confidence.
              </p>

              <div className="mt-6 grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-border bg-background/70 p-4">
                  <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
                    <Brain className="h-4 w-4 text-red-600 dark:text-red-400" />
                    Adaptive Organizational Memory
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Capture what happened, why it mattered, and what should happen next.
                  </p>
                </div>
                <div className="rounded-xl border border-border bg-background/70 p-4">
                  <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
                    <ChartNoAxesCombined className="h-4 w-4 text-red-600 dark:text-red-400" />
                    Decision Intelligence
                  </div>
                  <p className="text-sm text-muted-foreground">
                    Use proven signals, trends, and confidence bands before committing to action.
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={openHeaderBankSelector}
                className="mt-6 inline-flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted/70"
                aria-label="Open memory bank selector"
              >
                Select a memory bank above to begin
                <ArrowRight className="h-4 w-4" />
              </button>
              <div className="mt-3 text-xs text-muted-foreground">
                {bankCount > 0
                  ? `${bankCount} memory bank${bankCount === 1 ? "" : "s"} available.`
                  : "No banks yet. Create your first one below in one click."}
              </div>

              <div className="mt-5 rounded-xl border border-border bg-background/60 p-4">
                <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Wand2 className="h-4 w-4 text-red-600 dark:text-red-400" />
                  Quick Start (Create a bank)
                </div>
                <div className="flex w-full max-w-xl flex-col gap-2 sm:grid sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                  <Input
                    value={quickBankId}
                    onChange={(e) => setQuickBankId(e.target.value)}
                    placeholder="e.g. my-org, sales-intel"
                    className="h-11 w-full"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !isCreatingQuickBank) void handleQuickCreate();
                    }}
                  />
                  <Button
                    onClick={handleQuickCreate}
                    disabled={isCreatingQuickBank || !quickBankId.trim()}
                    className="h-11 w-full sm:w-auto sm:px-6"
                  >
                    {isCreatingQuickBank ? "Creating..." : "Create and Start"}
                  </Button>
                </div>
                <div className="mt-3 max-w-xl">
                  <label htmlFor="starter-kit" className="text-xs font-medium text-muted-foreground">
                    Memory starter kit
                  </label>
                  <select
                    id="starter-kit"
                    className="mt-1 flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                    value={starterKit}
                    onChange={(e) => setStarterKit(e.target.value === "codebase" ? "codebase" : "")}
                  >
                    <option value="">Default (blank bank)</option>
                    <option value="codebase">Code repository — retain/reflect tuned + guide cards</option>
                  </select>
                  <p className="mt-1 text-xs text-muted-foreground">
                    The codebase kit adds ASD-friendly retain rules, observation synthesis, three pinned
                    guides, and one evidence-first directive (safe to re-run; skips duplicates).
                  </p>
                </div>
                {quickError ? (
                  <p className="mt-2 text-xs text-red-600 dark:text-red-300">{quickError}</p>
                ) : null}
                {quickMessage ? (
                  <p className="mt-2 text-xs text-emerald-600 dark:text-emerald-300">
                    {quickMessage}
                  </p>
                ) : null}
              </div>
            </section>

            <div className="space-y-6">
              <aside className="rounded-2xl border border-border/60 bg-card/70 p-6 shadow-lg backdrop-blur-sm">
                <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground">
                  <Building2 className="h-4 w-4 text-red-600 dark:text-red-400" />
                  What changes for your team
                </div>
                <div className="space-y-3">
                  <div className="rounded-lg border border-border bg-background/70 p-3">
                    <p className="text-sm font-medium text-foreground">Faster alignment</p>
                    <p className="text-xs text-muted-foreground">
                      Shared memory reduces repeated context-switching across teams.
                    </p>
                  </div>
                  <div className="rounded-lg border border-border bg-background/70 p-3">
                    <p className="text-sm font-medium text-foreground">Lower decision risk</p>
                    <p className="text-xs text-muted-foreground">
                      Historical patterns and quantified influence improve strategic calls.
                    </p>
                  </div>
                  <div className="rounded-lg border border-border bg-background/70 p-3">
                    <p className="text-sm font-medium text-foreground">Compounding intelligence</p>
                    <p className="text-xs text-muted-foreground">
                      Dream and Brain systems keep learning, distilling, and improving over time.
                    </p>
                  </div>
                </div>
              </aside>

              <aside className="rounded-2xl border border-border/60 bg-card/70 p-6 shadow-lg backdrop-blur-sm">
                <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-foreground">
                  <FlaskConical className="h-4 w-4 text-red-600 dark:text-red-400" />
                  Benchmark Lab
                </div>
                <p className="text-sm text-muted-foreground">
                  Run the live local memory-to-skill experiment against a real Atulya API with
                  `.brain` export/import. This is meant to be a fun credibility check for anyone
                  cloning the repo.
                </p>

                <div className="mt-4 flex items-center gap-3">
                  <Button onClick={handleRunBenchmark} disabled={isBenchmarkRunning}>
                    {isBenchmarkRunning ? "Running live benchmark..." : "Run Live Benchmark"}
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    {isBenchmarkLoading
                      ? "Loading last run..."
                      : benchmark?.generated_at
                        ? `Last run: ${new Date(benchmark.generated_at).toLocaleString()}`
                        : "No run yet"}
                  </span>
                </div>

                {benchmarkError ? (
                  <p className="mt-3 text-xs text-red-600 dark:text-red-300">{benchmarkError}</p>
                ) : null}

                <div className="mt-4 grid gap-3 sm:grid-cols-2">
                  <div className="rounded-lg border border-border bg-background/70 p-3">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      API Recall
                    </p>
                    <p className="mt-1 text-lg font-semibold text-foreground">
                      {liveRecall ? `${(liveRecall.recall_accuracy * 100).toFixed(0)}%` : "--"}
                    </p>
                    <p className="text-xs text-muted-foreground">Top-hit live recall accuracy</p>
                  </div>
                  <div className="rounded-lg border border-border bg-background/70 p-3">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Memory-to-Skill
                    </p>
                    <p className="mt-1 text-lg font-semibold text-foreground">
                      {liveOverall
                        ? `${((liveOverall.skill_reuse_success_rate ?? 0) * 100).toFixed(0)}%`
                        : "--"}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Skill reuse success from live artifact flow
                    </p>
                  </div>
                  <div className="rounded-lg border border-border bg-background/70 p-3">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Answer Time
                    </p>
                    <p className="mt-1 text-lg font-semibold text-foreground">
                      {liveOverall?.time_to_useful_answer_ms != null
                        ? `${liveOverall.time_to_useful_answer_ms.toFixed(1)} ms`
                        : "--"}
                    </p>
                    <p className="text-xs text-muted-foreground">Current local benchmark latency</p>
                  </div>
                  <div className="rounded-lg border border-border bg-background/70 p-3">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Scenarios
                    </p>
                    <p className="mt-1 text-lg font-semibold text-foreground">
                      {benchmark?.leaderboard?.scenario_count ?? "--"}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      24 deterministic scenarios in live mode
                    </p>
                  </div>
                </div>

                <p className="mt-4 text-xs text-muted-foreground">
                  Publish/share can come next. For now this gives every downloader a local benchmark
                  lab instead of just a claim in the README.
                </p>
              </aside>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
