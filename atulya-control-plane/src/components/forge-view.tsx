"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { useBank } from "@/lib/bank-context";
import { client, type ForgeCatalogResponse, type ForgeRecordItem } from "@/lib/api";
import {
  type ForgeSourceType,
  costTierLabel,
  formatPassRate,
  sourceTemplate,
  validateSourceJson,
} from "@/lib/forge-templates";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  Layers,
  Loader2,
  Palette,
  Play,
  XCircle,
} from "lucide-react";
import { TasteStudioView } from "@/components/taste-studio-view";

interface QualitySummary {
  total: number;
  exportable: number;
  held_back?: number;
  pass_rate: number;
  avg_score: number;
  issue_counts?: Record<string, number>;
}

const STAGE_ORDER = ["queued", "ingest", "purify", "recipe", "audit", "repo_commit"];

const SOURCE_TYPES: Array<{ id: ForgeSourceType; label: string }> = [
  { id: "scenario", label: "Scenario" },
  { id: "chat", label: "Chat" },
  { id: "timeseries", label: "Time-series" },
  { id: "bank_only", label: "Bank only" },
];

function StepBadge({ n }: { n: number }) {
  return (
    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">
      {n}
    </span>
  );
}

export function ForgeView() {
  const { currentBank: bankId } = useBank();
  const [catalog, setCatalog] = useState<ForgeCatalogResponse | null>(null);
  const [recipeId, setRecipeId] = useState("consolidation_pairs");
  const [domainTag, setDomainTag] = useState("startup_ops");
  const [sourceType, setSourceType] = useState<ForgeSourceType>("scenario");
  const [sourceJson, setSourceJson] = useState(() =>
    JSON.stringify(sourceTemplate("scenario"), null, 2)
  );
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [qualityThreshold, setQualityThreshold] = useState(0.6);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [jobStage, setJobStage] = useState<string | null>(null);
  const [records, setRecords] = useState<ForgeRecordItem[]>([]);
  const [qualitySummary, setQualitySummary] = useState<QualitySummary | null>(null);
  const [exportAdapter, setExportAdapter] = useState("atr_jsonl");
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(false);
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  const [tasteStudioOpen, setTasteStudioOpen] = useState(false);

  const selectedRecipe = useMemo(
    () => catalog?.recipes.find((r) => r.recipe_id === recipeId),
    [catalog, recipeId]
  );

  const selectedDomain = useMemo(
    () => catalog?.domain_profiles.find((p) => p.id === domainTag),
    [catalog, domainTag]
  );

  const stageProgress = useMemo(() => {
    if (!jobStage) return 0;
    const idx = STAGE_ORDER.indexOf(jobStage);
    if (idx < 0) return 5;
    return Math.round(((idx + 1) / STAGE_ORDER.length) * 100);
  }, [jobStage]);

  const selectedRecord = useMemo(
    () => records.find((r) => r.record_id === selectedRecordId) ?? records[0] ?? null,
    [records, selectedRecordId]
  );

  const loadCatalog = useCallback(async () => {
    if (!bankId) return;
    const data = await client.listForgeRecipes(bankId, [domainTag]);
    setCatalog(data);
    if (data.suggested_recipes?.[0] && !data.suggested_recipes.includes(recipeId)) {
      setRecipeId(data.suggested_recipes[0]);
    }
  }, [bankId, domainTag, recipeId]);

  useEffect(() => {
    loadCatalog().catch(() => toast.error("Could not load forge recipes"));
  }, [loadCatalog]);

  useEffect(() => {
    const validation = validateSourceJson(sourceJson);
    setSourceError(validation.ok ? null : validation.error);
  }, [sourceJson]);

  const handleSourceTypeChange = (type: ForgeSourceType) => {
    setSourceType(type);
    setSourceJson(JSON.stringify(sourceTemplate(type), null, 2));
    setSourceError(null);
  };

  const pollOperation = async (opId: string) => {
    if (!bankId) return;
    setPolling(true);
    setJobStage("queued");
    try {
      for (let i = 0; i < 90; i++) {
        const status = await client.getOperationStatus(bankId, opId);
        if (status.stage) setJobStage(status.stage);
        if (status.status === "completed") {
          setJobStage("audit");
          const recs = await client.listForgeRecords(bankId, opId);
          setRecords(recs.records ?? []);
          if (recs.records?.[0]?.record_id) setSelectedRecordId(recs.records[0].record_id);
          const result = await client.getOperationResult(bankId, opId);
          const payload = result?.result as { quality_summary?: QualitySummary } | null;
          if (payload?.quality_summary) setQualitySummary(payload.quality_summary);
          toast.success(
            `Forge complete — ${recs.exportable_total ?? recs.total} exportable of ${recs.total} records`
          );
          return;
        }
        if (status.status === "failed") {
          toast.error(status.error_message || "Forge job failed");
          return;
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
      toast.error("Forge is taking longer than expected. Check Operations for status.");
    } finally {
      setPolling(false);
    }
  };

  const handlePurifyAndForge = async () => {
    if (!bankId) return;
    const validation = validateSourceJson(sourceJson);
    if (!validation.ok && sourceType !== "bank_only") {
      toast.error(validation.error);
      return;
    }
    if (selectedRecipe?.requires_ingest && sourceType === "bank_only") {
      toast.error("This recipe needs a source payload — pick scenario, chat, or timeseries.");
      return;
    }

    setLoading(true);
    setQualitySummary(null);
    setRecords([]);
    try {
      const source =
        sourceType === "bank_only" ? undefined : validation.ok ? validation.value : undefined;
      const result = await client.submitForgeJob(bankId, {
        recipe_id: recipeId,
        domain_tags: [domainTag],
        source,
        quality_threshold: qualityThreshold,
        wait_consolidation: true,
        repo_commit_on_complete: false,
      });
      setOperationId(result.operation_id);
      toast.success("Purifying memories and forging training records…");
      await pollOperation(result.operation_id);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to start forge job";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async () => {
    if (!bankId || !operationId) return;
    setLoading(true);
    try {
      const manifest = await client.exportForgeJob(bankId, {
        operation_id: operationId,
        adapter_id: exportAdapter,
        quality_threshold: qualityThreshold,
      });
      const blob = new Blob([manifest.content || ""], { type: "application/jsonl" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `atulya-forge-${recipeId}-${operationId.slice(0, 8)}.jsonl`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`Downloaded ${manifest.exportable_count} training records`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Export failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full min-w-0 space-y-6">
      <header className="border-b border-border/60 pb-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            <div className="rounded-lg bg-primary/10 p-2.5">
              <Layers className="h-7 w-7 text-primary" />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="text-3xl font-bold text-foreground">Data Forge for training models</h1>
              <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted-foreground sm:text-base">
                Turn raw conversations and facts into audited, timeline-grounded training data with
                provenance you can inspect before export.
              </p>
            </div>
          </div>
          <Button variant="secondary" onClick={() => setTasteStudioOpen(true)}>
            <Palette className="mr-2 h-4 w-4" />
            Curate taste
          </Button>
        </div>
      </header>

      {tasteStudioOpen && bankId && (
        <TasteStudioView bankId={bankId} onClose={() => setTasteStudioOpen(false)} />
      )}

      {(polling || jobStage) && (
        <Card className="border-primary/25 bg-primary/[0.03]">
          <CardContent className="space-y-3 pt-6">
            <div className="flex items-center justify-between gap-4 text-sm">
              <span className="flex items-center gap-2 font-medium">
                {polling && <Loader2 className="h-4 w-4 animate-spin" />}
                {catalog?.stages.find((s) => s.id === jobStage)?.label ?? "Working…"}
              </span>
              <span className="tabular-nums text-muted-foreground">{stageProgress}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full bg-primary transition-all duration-500"
                style={{ width: `${stageProgress}%` }}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {qualitySummary && qualitySummary.total > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-lg">Quality dashboard</CardTitle>
            <CardDescription>
              Records that pass audit can be exported for fine-tuning.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div className="rounded-lg border border-border/60 bg-muted/20 px-4 py-3">
                <p className="text-2xl font-semibold tabular-nums">{qualitySummary.total}</p>
                <p className="text-xs text-muted-foreground">Total records</p>
              </div>
              <div className="rounded-lg border border-border/60 bg-muted/20 px-4 py-3">
                <p className="text-2xl font-semibold tabular-nums text-green-600 dark:text-green-400">
                  {qualitySummary.exportable}
                </p>
                <p className="text-xs text-muted-foreground">Exportable</p>
              </div>
              <div className="rounded-lg border border-border/60 bg-muted/20 px-4 py-3">
                <p className="text-2xl font-semibold tabular-nums">
                  {formatPassRate(qualitySummary.pass_rate)}
                </p>
                <p className="text-xs text-muted-foreground">Pass rate</p>
              </div>
              <div className="rounded-lg border border-border/60 bg-muted/20 px-4 py-3">
                <p className="text-2xl font-semibold tabular-nums">
                  {qualitySummary.avg_score.toFixed(2)}
                </p>
                <p className="text-xs text-muted-foreground">Avg quality score</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid w-full grid-cols-1 items-stretch gap-6 xl:grid-cols-2">
        <Card className="flex h-full flex-col">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <StepBadge n={1} />
              Connect your data
            </CardTitle>
            <CardDescription>
              Pick a domain and source shape. Templates are editable.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col gap-5">
            <div className="space-y-2">
              <Label>Domain</Label>
              <Select value={domainTag} onValueChange={setDomainTag}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(catalog?.domain_profiles ?? []).map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedDomain?.description && (
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {selectedDomain.description}
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label>Source type</Label>
              <Tabs
                value={sourceType}
                onValueChange={(v) => handleSourceTypeChange(v as ForgeSourceType)}
              >
                <TabsList className="grid h-auto w-full grid-cols-2 gap-1 p-1 sm:grid-cols-4">
                  {SOURCE_TYPES.map(({ id, label }) => (
                    <TabsTrigger key={id} value={id} className="text-xs sm:text-sm">
                      {label}
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
            </div>

            {sourceType !== "bank_only" ? (
              <div className="flex min-h-[240px] flex-1 flex-col space-y-2">
                <Label>Payload</Label>
                <Textarea
                  className={`min-h-[220px] flex-1 font-mono text-xs ${sourceError ? "border-destructive" : ""}`}
                  value={sourceJson}
                  onChange={(e) => setSourceJson(e.target.value)}
                  spellCheck={false}
                />
                {sourceError && (
                  <p className="flex items-center gap-1 text-xs text-destructive">
                    <AlertCircle className="h-3 w-3 shrink-0" />
                    {sourceError}
                  </p>
                )}
              </div>
            ) : (
              <div className="flex flex-1 flex-col justify-center rounded-lg border border-dashed border-border/80 bg-muted/30 p-4 text-sm leading-relaxed text-muted-foreground">
                Forge will use memories already in this bank. Best after you have retained documents
                or conversations elsewhere.
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="flex h-full flex-col">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <StepBadge n={2} />
              Purify &amp; forge
            </CardTitle>
            <CardDescription className="space-y-2">
              <span className="block">Suggested recipes for this domain:</span>
              {(catalog?.suggested_recipes ?? []).length > 0 ? (
                <span className="flex flex-wrap gap-2">
                  {(catalog?.suggested_recipes ?? []).map((id) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setRecipeId(id)}
                      className={`rounded-md border px-2 py-0.5 text-xs transition-colors ${
                        recipeId === id
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border/80 bg-muted/40 text-muted-foreground hover:border-primary/40 hover:text-foreground"
                      }`}
                    >
                      {id}
                    </button>
                  ))}
                </span>
              ) : (
                <span className="text-muted-foreground">Loading recipes…</span>
              )}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col gap-5">
            <div className="space-y-2">
              <Label>Recipe</Label>
              <Select value={recipeId} onValueChange={setRecipeId}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(catalog?.recipes ?? []).map((r) => (
                    <SelectItem key={r.recipe_id} value={r.recipe_id}>
                      {r.title ?? r.recipe_id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {selectedRecipe && (
                <div className="space-y-2 rounded-lg border border-border/60 bg-muted/30 p-3 text-sm">
                  <p className="leading-relaxed text-muted-foreground">
                    {selectedRecipe.description}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary">{costTierLabel(selectedRecipe.cost_tier)}</Badge>
                    {selectedRecipe.requires_ingest && (
                      <Badge variant="outline">Requires source</Badge>
                    )}
                    {selectedRecipe.training_signal && (
                      <Badge variant="outline">{selectedRecipe.training_signal}</Badge>
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <Label>Quality threshold</Label>
                <span className="text-sm font-medium tabular-nums">
                  {qualityThreshold.toFixed(2)}
                </span>
              </div>
              <Slider
                min={0.3}
                max={0.95}
                step={0.05}
                value={[qualityThreshold]}
                onValueChange={([v]) => setQualityThreshold(v)}
              />
              <p className="text-xs text-muted-foreground">
                Higher = stricter provenance and citation checks before export.
              </p>
            </div>

            <div className="mt-auto pt-2">
              <Button
                className="w-full"
                size="lg"
                onClick={handlePurifyAndForge}
                disabled={loading || polling || !bankId || !!sourceError}
              >
                {loading || polling ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Play className="mr-2 h-4 w-4" />
                )}
                Purify &amp; run forge
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <StepBadge n={3} />
            Preview &amp; export
          </CardTitle>
          <CardDescription>
            Inspect provenance and quality before downloading training files.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
            <div className="min-w-0 flex-1 space-y-2">
              <Label>Export format</Label>
              <Select value={exportAdapter} onValueChange={setExportAdapter}>
                <SelectTrigger className="w-full sm:max-w-md">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(catalog?.exporters ?? []).map((e) => (
                    <SelectItem key={e.adapter_id} value={e.adapter_id}>
                      {e.title ?? e.adapter_id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              className="w-full sm:w-auto shrink-0"
              onClick={handleExport}
              disabled={!operationId || loading || records.length === 0}
            >
              <Download className="mr-2 h-4 w-4" />
              Download JSONL
            </Button>
          </div>

          {records.length > 0 ? (
            <div className="grid w-full grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="max-h-96 space-y-2 overflow-y-auto pr-1">
                {records.map((row) => (
                  <button
                    key={row.record_id}
                    type="button"
                    onClick={() => setSelectedRecordId(row.record_id)}
                    className={`w-full rounded-lg border p-3 text-left transition-colors ${
                      selectedRecord?.record_id === row.record_id
                        ? "border-primary bg-primary/5"
                        : "border-border/60 hover:bg-muted/50"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-mono text-xs">
                        {row.record_id.slice(0, 8)}…
                      </span>
                      {row.exportable ? (
                        <CheckCircle2 className="h-4 w-4 shrink-0 text-green-600" />
                      ) : (
                        <XCircle className="h-4 w-4 shrink-0 text-amber-600" />
                      )}
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                      {row.record?.labels?.answer || row.record?.tasks?.[0]?.query || row.recipe_id}
                    </p>
                    <p className="mt-1 text-xs tabular-nums text-muted-foreground">
                      Score: {row.quality_score.toFixed(2)}
                    </p>
                  </button>
                ))}
              </div>
              {selectedRecord ? (
                <div className="min-h-[12rem] space-y-3 rounded-lg border border-border/60 p-4 text-sm lg:min-h-0">
                  <h4 className="font-semibold">Why this record?</h4>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant={selectedRecord.exportable ? "default" : "secondary"}>
                      {selectedRecord.exportable ? "Exportable" : "Held back"}
                    </Badge>
                    <Badge variant="outline">Score {selectedRecord.quality_score.toFixed(2)}</Badge>
                  </div>
                  {selectedRecord.record?.quality?.issues &&
                    selectedRecord.record.quality.issues.length > 0 && (
                      <div>
                        <p className="mb-1 text-xs font-medium text-muted-foreground">Issues</p>
                        <ul className="space-y-1 text-xs text-amber-700 dark:text-amber-400">
                          {selectedRecord.record.quality.issues.map((issue) => (
                            <li key={issue}>• {issue}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  <pre className="max-h-56 overflow-auto rounded-md bg-muted p-2 text-xs">
                    {JSON.stringify(selectedRecord.record, null, 2)}
                  </pre>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-border/80 bg-muted/20 px-6 py-12 text-center">
              <p className="text-sm text-muted-foreground">
                Run forge to preview training records here.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
