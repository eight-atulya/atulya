"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import {
  client,
  type TasteCatalogResponse,
  type TasteDatasetItem,
  type TasteSetItem,
  type TasteSetStatus,
} from "@/lib/api";
import {
  DEFAULT_TASTE_TAGS,
  importTemplate,
  sampleJsonl,
  validateJsonlImport,
} from "@/lib/taste-templates";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  ArrowLeft,
  Brain,
  CheckSquare,
  Download,
  Layers,
  Loader2,
  Palette,
  Sparkles,
  Square,
  Trash2,
  Upload,
  Wand2,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { TasteSetDetailPanel } from "./taste-set-detail-panel";
import {
  FieldLabel,
  ScopePill,
  TasteStudioProvider,
  TasteTooltip,
  ToolbarSection,
} from "./taste-studio-ui";

interface TasteStudioViewProps {
  bankId: string;
  onClose: () => void;
}

type VariantFilter = "all" | "seeds" | "variants";
type ToneOption = "concise" | "formal" | "friendly";

interface PendingTransform {
  op: string;
  params?: Record<string, unknown>;
}

const VARIANT_COUNTS = [1, 2, 4, 8, 16] as const;

function statusBadgeVariant(
  status: TasteSetStatus
): "default" | "secondary" | "outline" | "destructive" {
  if (status === "retained") return "default";
  if (status === "ready") return "secondary";
  return "outline";
}

export function TasteStudioView({ bankId, onClose }: TasteStudioViewProps) {
  const [catalog, setCatalog] = useState<TasteCatalogResponse | null>(null);
  const [datasets, setDatasets] = useState<TasteDatasetItem[]>([]);
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [sets, setSets] = useState<TasteSetItem[]>([]);
  const [setsTotal, setSetsTotal] = useState(0);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectedSet, setSelectedSet] = useState<TasteSetItem | null>(null);
  const [draftJson, setDraftJson] = useState("");
  const [loading, setLoading] = useState(false);
  const [importJsonl, setImportJsonl] = useState("");
  const [newDatasetName, setNewDatasetName] = useState("My taste dataset");
  const [schemaType, setSchemaType] = useState<"openai_chat" | "qa_pair" | "custom">("openai_chat");
  const [exportAdapter, setExportAdapter] = useState("openai_chat_jsonl");
  const [variantFilter, setVariantFilter] = useState<VariantFilter>("all");
  const [variantCount, setVariantCount] = useState<number>(8);
  const [tone, setTone] = useState<ToneOption>("concise");
  const [pendingTransform, setPendingTransform] = useState<PendingTransform | null>(null);
  const [previewItems, setPreviewItems] = useState<
    Array<{
      set_id: string;
      set_key: string;
      before: Record<string, unknown>;
      after: Record<string, unknown>;
    }>
  >([]);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [operationLabel, setOperationLabel] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<"dataset" | "create" | "import">("dataset");

  const activeDataset = useMemo(
    () => datasets.find((d) => d.id === datasetId) ?? null,
    [datasets, datasetId]
  );

  const importSchemaType = activeDataset?.schema_type ?? schemaType;
  const selectedSchemaMeta = catalog?.schema_types.find((s) => s.id === schemaType);
  const selectedExporterMeta = catalog?.exporters.find((e) => e.adapter_id === exportAdapter);

  const loadCatalog = useCallback(async () => {
    const data = await client.listTasteCatalog(bankId);
    setCatalog(data);
    if (data.exporters[0]?.adapter_id) setExportAdapter(data.exporters[0].adapter_id);
  }, [bankId]);

  const loadDatasets = useCallback(async () => {
    const data = await client.listTasteDatasets(bankId);
    setDatasets(data.datasets ?? []);
    if (!datasetId && data.datasets?.[0]?.id) setDatasetId(data.datasets[0].id);
  }, [bankId, datasetId]);

  const loadSets = useCallback(async () => {
    if (!datasetId) {
      setSets([]);
      setSetsTotal(0);
      return;
    }
    const pageSize = 500;
    const first = await client.listTasteSets(bankId, datasetId, pageSize, 0);
    const total = first.total ?? first.sets?.length ?? 0;
    const aggregated = [...(first.sets ?? [])];
    for (let offset = pageSize; offset < total; offset += pageSize) {
      const page = await client.listTasteSets(bankId, datasetId, pageSize, offset);
      aggregated.push(...(page.sets ?? []));
    }
    setSets(aggregated);
    setSetsTotal(total);
  }, [bankId, datasetId]);

  useEffect(() => {
    loadCatalog().catch(() => toast.error("Could not load taste catalog"));
    loadDatasets().catch(() => toast.error("Could not load taste datasets"));
  }, [loadCatalog, loadDatasets]);

  useEffect(() => {
    loadSets().catch(() => toast.error("Could not load taste sets"));
    setSelectedIds(new Set());
    setPreviewItems([]);
    setPendingTransform(null);
  }, [loadSets, datasetId]);

  useEffect(() => {
    if (activeDataset) {
      setImportJsonl((prev) => (prev.trim() ? prev : sampleJsonl(activeDataset.schema_type)));
      setSidebarTab("import");
    }
  }, [activeDataset]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (selectedSet) setSelectedSet(null);
        else onClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, selectedSet]);

  const pollOperation = useCallback(
    async (opId: string, label: string) => {
      setPolling(true);
      setOperationId(opId);
      setOperationLabel(label);
      toast.message(`${label} started`, { description: "Watching job progress…" });
      try {
        for (let i = 0; i < 90; i++) {
          const status = await client.getOperationStatus(bankId, opId);
          if (status.status === "completed") {
            await loadSets();
            await loadDatasets();
            setPreviewItems([]);
            setPendingTransform(null);
            toast.success(`${label} complete`);
            return;
          }
          if (status.status === "failed") {
            toast.error(status.error_message || `${label} failed`);
            return;
          }
          await new Promise((r) => setTimeout(r, i < 8 ? 1000 : 2000));
        }
        toast.message(`${label} still running`, {
          description: "Check Operations for progress.",
        });
      } finally {
        setPolling(false);
        setOperationId(null);
        setOperationLabel(null);
      }
    },
    [bankId, loadDatasets, loadSets]
  );

  const filteredSets = useMemo(() => {
    if (variantFilter === "seeds") return sets.filter((s) => s.variant_index === 0);
    if (variantFilter === "variants") return sets.filter((s) => s.variant_index > 0);
    return sets;
  }, [sets, variantFilter]);

  const transformTargetCount = useMemo(() => {
    if (selectedIds.size > 0) return selectedIds.size;
    return setsTotal || sets.length;
  }, [selectedIds.size, sets.length, setsTotal]);

  const selectedIdList = useMemo(() => Array.from(selectedIds), [selectedIds]);

  const importValidation = useMemo(
    () => (importJsonl.trim() ? validateJsonlImport(importJsonl, importSchemaType) : null),
    [importJsonl, importSchemaType]
  );

  const previewChangedCount = useMemo(
    () =>
      previewItems.filter((item) => JSON.stringify(item.before) !== JSON.stringify(item.after))
        .length,
    [previewItems]
  );

  const busy = loading || polling;

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllVisible = () => {
    setSelectedIds(new Set(filteredSets.map((s) => s.id)));
    toast.message(`Selected ${filteredSets.length} visible sets`);
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
    toast.message("Selection cleared");
  };

  const openSet = (row: TasteSetItem) => {
    setSelectedSet(row);
    setDraftJson(JSON.stringify(row.working_payload, null, 2));
  };

  const handleCreateDataset = async () => {
    setLoading(true);
    try {
      const created = await client.createTasteDataset(bankId, {
        name: newDatasetName,
        schema_type: schemaType,
        taste_tags: DEFAULT_TASTE_TAGS,
      });
      setDatasets((prev) => [created, ...prev]);
      setDatasetId(created.id);
      setImportJsonl(sampleJsonl(schemaType));
      setSidebarTab("import");
      toast.success(`Dataset "${created.name}" created`, {
        description: "Import your first examples to get started.",
      });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to create dataset");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteDataset = async () => {
    if (!datasetId || !activeDataset) return;
    setLoading(true);
    try {
      await client.deleteTasteDataset(bankId, datasetId);
      const remaining = datasets.filter((d) => d.id !== datasetId);
      setDatasets(remaining);
      setDatasetId(remaining[0]?.id ?? null);
      setSets([]);
      setSelectedSet(null);
      setDeleteDialogOpen(false);
      toast.success(`Deleted "${activeDataset.name}"`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Delete failed");
    } finally {
      setLoading(false);
    }
  };

  const handleImport = async () => {
    if (!datasetId) return;
    const validation = validateJsonlImport(importJsonl, importSchemaType);
    if (!validation.ok) {
      toast.error(validation.error);
      return;
    }
    setLoading(true);
    try {
      const result = await client.importTasteSets(bankId, datasetId, { jsonl: importJsonl });
      await loadSets();
      await loadDatasets();
      toast.success(
        `Imported ${result.imported_count} set${result.imported_count === 1 ? "" : "s"}`
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Import failed");
    } finally {
      setLoading(false);
    }
  };

  const handleSaveSet = async () => {
    if (!selectedSet) return;
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(draftJson);
    } catch {
      toast.error("Working payload must be valid JSON");
      return;
    }
    setLoading(true);
    try {
      const updated = await client.updateTasteSet(bankId, selectedSet.id, {
        working_payload: payload,
        status: "ready",
      });
      setSelectedSet(updated);
      setSets((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      toast.success(`Saved ${updated.set_key}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Save failed");
    } finally {
      setLoading(false);
    }
  };

  const handleRevertSet = async () => {
    if (!selectedSet) return;
    setLoading(true);
    try {
      const updated = await client.revertTasteSet(bankId, selectedSet.id);
      setSelectedSet(updated);
      setDraftJson(JSON.stringify(updated.working_payload, null, 2));
      setSets((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      toast.success(`Reverted ${updated.set_key} to seed`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Revert failed");
    } finally {
      setLoading(false);
    }
  };

  const runTransform = async (op: string, preview: boolean, params?: Record<string, unknown>) => {
    if (!datasetId) return;
    if (!preview && transformTargetCount === 0) {
      toast.error("No sets to transform — import examples first");
      return;
    }
    setLoading(true);
    try {
      const result = await client.submitTasteTransform(bankId, {
        dataset_id: datasetId,
        set_ids: selectedIdList.length ? selectedIdList : undefined,
        ops: [{ op, params: params ?? {} }],
        preview,
      });
      if (result.preview) {
        setPreviewItems(result.items ?? []);
        setPendingTransform({ op, params });
        const changed = (result.items ?? []).filter(
          (item) => JSON.stringify(item.before) !== JSON.stringify(item.after)
        ).length;
        toast.message("Preview ready", {
          description: `${changed} of ${result.items?.length ?? 0} sets would change.`,
        });
      } else if (result.operation_id) {
        await pollOperation(result.operation_id, "Transform");
      } else {
        await loadSets();
        setPreviewItems([]);
        setPendingTransform(null);
        toast.success(`Updated ${result.updated_count ?? 0} sets`, {
          description: `Processed ${result.processed_count ?? result.updated_count ?? 0} set(s).`,
        });
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Transform failed");
    } finally {
      setLoading(false);
    }
  };

  const handleApplyPreview = async () => {
    if (!pendingTransform) return;
    await runTransform(pendingTransform.op, false, pendingTransform.params);
  };

  const handleGenerate = async () => {
    if (!datasetId) return;
    const seedIds =
      selectedIdList.length > 0
        ? selectedIdList
        : sets.filter((s) => s.variant_index === 0).map((s) => s.id);
    if (seedIds.length === 0) {
      toast.error("Select seed sets or import examples first");
      return;
    }
    setLoading(true);
    try {
      const result = await client.generateTasteVariants(bankId, datasetId, {
        set_ids: seedIds,
        count: variantCount,
      });
      if ("operation_id" in result && result.operation_id) {
        await pollOperation(result.operation_id, "Variant generation");
      } else if ("created_count" in result) {
        await loadSets();
        await loadDatasets();
        toast.success(
          `Created ${result.created_count} variant${result.created_count === 1 ? "" : "s"}`
        );
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Generate failed");
    } finally {
      setLoading(false);
    }
  };

  const handleRetain = async () => {
    const retainableIds = selectedIdList.filter((id) => {
      const row = sets.find((s) => s.id === id);
      return row && row.status !== "retained";
    });
    if (retainableIds.length === 0) {
      toast.error(
        selectedIdList.length > 0
          ? "Selected sets are already in memory"
          : "Select sets to send to memory"
      );
      return;
    }
    if (retainableIds.length < selectedIdList.length) {
      toast.message("Skipping already-retained sets", {
        description: `Sending ${retainableIds.length} of ${selectedIdList.length} selected.`,
      });
    }
    setLoading(true);
    try {
      const result = await client.retainTasteSets(bankId, { set_ids: retainableIds });
      await loadSets();
      toast.success(
        `Retained ${result.retained_count} set${result.retained_count === 1 ? "" : "s"} into memory`,
        {
          description: "Sets tagged for recall in your bank.",
        }
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Retain failed");
    } finally {
      setLoading(false);
    }
  };

  const handleExport = async () => {
    if (!datasetId) return;
    setLoading(true);
    try {
      const manifest = await client.exportTasteDataset(bankId, {
        dataset_id: datasetId,
        set_ids: selectedIdList.length ? selectedIdList : undefined,
        adapter_id: exportAdapter,
      });
      const blob = new Blob([manifest.content || ""], { type: "application/jsonl" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `taste-${activeDataset?.name ?? datasetId}.jsonl`;
      a.click();
      URL.revokeObjectURL(url);
      const scope = selectedIdList.length ? `${selectedIdList.length} selected` : "full dataset";
      toast.success(`Exported ${manifest.exportable_count} rows`, { description: scope });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Export failed");
    } finally {
      setLoading(false);
    }
  };

  const handleBackdropClose = () => {
    if (selectedSet) {
      setSelectedSet(null);
      toast.message("Inspector closed");
      return;
    }
    onClose();
  };

  return (
    <TasteStudioProvider>
      <div
        className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 lg:p-8"
        role="dialog"
        aria-modal="true"
        aria-label="Taste Studio"
      >
        <button
          type="button"
          className="absolute inset-0 bg-black/50 backdrop-blur-md"
          aria-label="Close Taste Studio"
          onClick={handleBackdropClose}
        />

        <div
          className={cn(
            "relative flex h-full max-h-[min(920px,calc(100vh-2rem))] w-full max-w-[1520px] flex-col overflow-hidden",
            "rounded-2xl border border-border/80 bg-card/95 shadow-2xl backdrop-blur-xl",
            "animate-in fade-in-0 zoom-in-95 duration-200"
          )}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <header className="flex shrink-0 items-center justify-between gap-4 border-b border-border/60 px-5 py-4 sm:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <TasteTooltip content="Return to Data Forge">
                <Button variant="outline" size="sm" onClick={onClose} className="shrink-0 gap-1.5">
                  <ArrowLeft className="h-4 w-4" />
                  <span className="hidden sm:inline">Back</span>
                </Button>
              </TasteTooltip>
              <div className="rounded-xl bg-primary/10 p-2.5">
                <Palette className="h-5 w-5 text-primary" />
              </div>
              <div className="min-w-0">
                <h1 className="text-xl font-bold tracking-tight sm:text-2xl">Taste Studio</h1>
                <p className="truncate text-xs text-muted-foreground sm:text-sm">
                  Curate examples · branch variants · close the loop with memory
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {busy && (
                <div className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {operationLabel ?? "Working"}
                  {operationId ? ` · ${operationId.slice(0, 8)}` : ""}
                </div>
              )}
              <TasteTooltip content="Close (Esc)">
                <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
                  <X className="h-5 w-5" />
                </Button>
              </TasteTooltip>
            </div>
          </header>

          {/* Body */}
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-hidden p-4 sm:p-5 lg:grid-cols-[300px_1fr] lg:gap-5">
            {/* Sidebar */}
            <aside className="flex min-h-0 flex-col gap-3 overflow-y-auto pr-0.5 lg:max-h-full">
              <div className="flex gap-1 rounded-lg border bg-muted/40 p-1">
                {(
                  [
                    ["dataset", "Dataset"],
                    ["create", "New"],
                    ["import", "Import"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setSidebarTab(id)}
                    className={cn(
                      "flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition-colors",
                      sidebarTab === id
                        ? "bg-background text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>

              {sidebarTab === "dataset" && (
                <Card className="border-border/70 shadow-none">
                  <CardHeader className="space-y-1 p-4 pb-2">
                    <CardTitle className="text-sm">Active dataset</CardTitle>
                    <CardDescription className="text-xs">
                      Switch datasets or remove the current one.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3 p-4 pt-0">
                    <FieldLabel
                      label="Dataset"
                      hint="Each dataset has a fixed schema type set at creation."
                    />
                    <Select value={datasetId ?? ""} onValueChange={setDatasetId}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select dataset" />
                      </SelectTrigger>
                      <SelectContent>
                        {datasets.length === 0 ? (
                          <SelectItem value="__none" disabled>
                            No datasets yet
                          </SelectItem>
                        ) : (
                          datasets.map((d) => (
                            <SelectItem key={d.id} value={d.id}>
                              {d.name} ({d.set_count ?? 0})
                            </SelectItem>
                          ))
                        )}
                      </SelectContent>
                    </Select>
                    {activeDataset && (
                      <div className="rounded-lg border border-dashed bg-muted/20 p-3 text-xs">
                        <p className="font-medium">{activeDataset.name}</p>
                        <p className="mt-1 text-muted-foreground">
                          Schema:{" "}
                          <span className="text-foreground">{activeDataset.schema_type}</span>
                        </p>
                        <p className="text-muted-foreground">
                          {activeDataset.set_count ?? sets.length} sets
                        </p>
                        {activeDataset.taste_tags.length > 0 && (
                          <p className="mt-1 truncate text-muted-foreground">
                            {activeDataset.taste_tags.join(", ")}
                          </p>
                        )}
                      </div>
                    )}
                    {datasetId && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-full text-destructive hover:bg-destructive/10 hover:text-destructive"
                        onClick={() => setDeleteDialogOpen(true)}
                        disabled={busy}
                      >
                        <Trash2 className="mr-2 h-4 w-4" />
                        Delete dataset
                      </Button>
                    )}
                  </CardContent>
                </Card>
              )}

              {sidebarTab === "create" && (
                <Card className="border-border/70 shadow-none">
                  <CardHeader className="space-y-1 p-4 pb-2">
                    <CardTitle className="text-sm">Create dataset</CardTitle>
                    <CardDescription className="text-xs">
                      Schema type cannot be changed after creation.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3 p-4 pt-0">
                    <div className="space-y-1.5">
                      <FieldLabel
                        label="Name"
                        hint="A human-readable label for this taste collection."
                      />
                      <Input
                        value={newDatasetName}
                        onChange={(e) => setNewDatasetName(e.target.value)}
                        placeholder="e.g. Code review standards"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <FieldLabel
                        label="Schema"
                        hint="Defines the JSON shape for every imported row."
                      />
                      <Select
                        value={schemaType}
                        onValueChange={(v) => setSchemaType(v as typeof schemaType)}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(catalog?.schema_types ?? []).map((s) => (
                            <SelectItem key={s.id} value={s.id}>
                              {s.title}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {selectedSchemaMeta?.description && (
                        <p className="text-xs text-muted-foreground">
                          {selectedSchemaMeta.description}
                        </p>
                      )}
                    </div>
                    <Button
                      className="w-full"
                      onClick={handleCreateDataset}
                      disabled={busy || !newDatasetName.trim()}
                    >
                      Create dataset
                    </Button>
                  </CardContent>
                </Card>
              )}

              {sidebarTab === "import" && (
                <Card className="border-border/70 shadow-none">
                  <CardHeader className="space-y-1 p-4 pb-2">
                    <CardTitle className="text-sm">Import JSONL</CardTitle>
                    <CardDescription className="text-xs">
                      One JSON object per line · validated before upload
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-3 p-4 pt-0">
                    {!datasetId ? (
                      <p className="text-xs text-muted-foreground">
                        Create or select a dataset first.
                      </p>
                    ) : (
                      <>
                        <p className="text-xs text-muted-foreground">
                          Schema:{" "}
                          <span className="font-medium text-foreground">{importSchemaType}</span>
                          {importValidation?.ok
                            ? ` · ${importValidation.lineCount} valid row(s)`
                            : ""}
                        </p>
                        <Textarea
                          className="min-h-[160px] font-mono text-xs"
                          value={importJsonl}
                          onChange={(e) => setImportJsonl(e.target.value)}
                          placeholder={JSON.stringify(importTemplate(importSchemaType), null, 2)}
                        />
                        {importValidation && !importValidation.ok && (
                          <p className="text-xs text-destructive">{importValidation.error}</p>
                        )}
                        <TasteTooltip content="Append rows to the active dataset">
                          <Button
                            className="w-full"
                            onClick={handleImport}
                            disabled={busy || !(importValidation?.ok ?? false)}
                          >
                            <Upload className="mr-2 h-4 w-4" />
                            Import rows
                          </Button>
                        </TasteTooltip>
                      </>
                    )}
                  </CardContent>
                </Card>
              )}
            </aside>

            {/* Main workspace */}
            <main className="relative flex min-h-0 min-w-0 flex-col gap-3 overflow-hidden">
              {/* Toolbar row */}
              <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <ScopePill
                    selectedCount={selectedIds.size}
                    visibleCount={filteredSets.length}
                    totalCount={setsTotal || sets.length}
                    transformScope={transformTargetCount}
                  />
                  <TasteTooltip content="Select every row matching the current filter">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={selectAllVisible}
                      disabled={busy || filteredSets.length === 0}
                    >
                      <CheckSquare className="mr-1.5 h-4 w-4" />
                      All
                    </Button>
                  </TasteTooltip>
                  <TasteTooltip content="Clear row selection">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={clearSelection}
                      disabled={busy || selectedIds.size === 0}
                    >
                      <Square className="mr-1.5 h-4 w-4" />
                      Clear
                    </Button>
                  </TasteTooltip>
                  <Select
                    value={variantFilter}
                    onValueChange={(v) => setVariantFilter(v as VariantFilter)}
                  >
                    <SelectTrigger className="h-8 w-[128px]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All sets</SelectItem>
                      <SelectItem value="seeds">Seeds only</SelectItem>
                      <SelectItem value="variants">Variants only</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="flex flex-wrap gap-2">
                  <ToolbarSection title="Transform">
                    <TasteTooltip content="Preview spelling and grammar fixes without saving">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => runTransform("spellfix_llm", true)}
                        disabled={busy || !datasetId || transformTargetCount === 0}
                      >
                        <Wand2 className="mr-1.5 h-4 w-4" />
                        Preview
                      </Button>
                    </TasteTooltip>
                    <TasteTooltip content="Apply spellfix to selection, or all sets if none selected">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => runTransform("spellfix_llm", false)}
                        disabled={busy || !datasetId || transformTargetCount === 0}
                      >
                        Apply spellfix
                      </Button>
                    </TasteTooltip>
                    <Select value={tone} onValueChange={(v) => setTone(v as ToneOption)}>
                      <SelectTrigger className="h-8 w-[108px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="concise">Concise</SelectItem>
                        <SelectItem value="formal">Formal</SelectItem>
                        <SelectItem value="friendly">Friendly</SelectItem>
                      </SelectContent>
                    </Select>
                    <TasteTooltip content="Preview tone rewrite before applying">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => runTransform("tone_shift", true, { tone })}
                        disabled={busy || !datasetId || transformTargetCount === 0}
                      >
                        Preview tone
                      </Button>
                    </TasteTooltip>
                    <TasteTooltip content="Rewrite tone while preserving facts and structure">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => runTransform("tone_shift", false, { tone })}
                        disabled={busy || !datasetId || transformTargetCount === 0}
                      >
                        Apply tone
                      </Button>
                    </TasteTooltip>
                  </ToolbarSection>

                  <ToolbarSection title="Variants">
                    <Select
                      value={String(variantCount)}
                      onValueChange={(v) => setVariantCount(Number(v))}
                    >
                      <SelectTrigger className="h-8 w-[68px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {VARIANT_COUNTS.map((n) => (
                          <SelectItem key={n} value={String(n)}>
                            ×{n}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <TasteTooltip content="Generate similar variants from selected seeds, or all seeds if none selected">
                      <Button size="sm" onClick={handleGenerate} disabled={busy || !datasetId}>
                        <Sparkles className="mr-1.5 h-4 w-4" />
                        Generate
                      </Button>
                    </TasteTooltip>
                  </ToolbarSection>

                  <ToolbarSection title="Ship">
                    <TasteTooltip content="Retain selected sets into bank memory with taste tags">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={handleRetain}
                        disabled={busy || selectedIdList.length === 0}
                      >
                        <Brain className="mr-1.5 h-4 w-4" />
                        Memory
                      </Button>
                    </TasteTooltip>
                    <Select value={exportAdapter} onValueChange={setExportAdapter}>
                      <SelectTrigger className="h-8 w-[148px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {(catalog?.exporters ?? []).map((e) => (
                          <SelectItem key={e.adapter_id} value={e.adapter_id}>
                            {e.title}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <TasteTooltip
                      content={
                        selectedExporterMeta?.description ?? "Download JSONL for fine-tuning"
                      }
                    >
                      <Button size="sm" onClick={handleExport} disabled={busy || !datasetId}>
                        <Download className="mr-1.5 h-4 w-4" />
                        Export
                      </Button>
                    </TasteTooltip>
                  </ToolbarSection>
                </div>
              </div>

              {/* Preview banner */}
              {previewItems.length > 0 && (
                <Card className="border-primary/30 bg-primary/5 shadow-none">
                  <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <p className="text-sm font-medium">Transform preview</p>
                      <p className="text-xs text-muted-foreground">
                        {previewChangedCount} of {previewItems.length} sets would change
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setPreviewItems([]);
                          setPendingTransform(null);
                          toast.message("Preview dismissed");
                        }}
                      >
                        Dismiss
                      </Button>
                      <Button
                        size="sm"
                        onClick={handleApplyPreview}
                        disabled={busy || !pendingTransform}
                      >
                        Apply changes
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Table */}
              <Card className="min-h-0 flex-1 overflow-hidden border-border/70 shadow-none">
                <div className="h-full overflow-auto">
                  <Table>
                    <TableHeader className="sticky top-0 z-10 bg-card">
                      <TableRow>
                        <TableHead className="w-10" />
                        <TableHead>Set</TableHead>
                        <TableHead>Variant</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Memory</TableHead>
                        <TableHead className="hidden md:table-cell">Tags</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filteredSets.map((row) => (
                        <TableRow
                          key={row.id}
                          className={cn(
                            "cursor-pointer transition-colors",
                            selectedSet?.id === row.id ? "bg-primary/10" : "hover:bg-muted/40"
                          )}
                          onClick={() => openSet(row)}
                        >
                          <TableCell onClick={(e) => e.stopPropagation()}>
                            <Checkbox
                              checked={selectedIds.has(row.id)}
                              onCheckedChange={() => toggleSelect(row.id)}
                              aria-label={`Select ${row.set_key}`}
                            />
                          </TableCell>
                          <TableCell className="font-medium">{row.set_key}</TableCell>
                          <TableCell>
                            <Badge variant={row.variant_index === 0 ? "default" : "secondary"}>
                              {row.variant_index === 0 ? "seed" : `v${row.variant_index}`}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <Badge variant={statusBadgeVariant(row.status)}>{row.status}</Badge>
                          </TableCell>
                          <TableCell>
                            {(row.memory_unit_ids?.length ?? 0) > 0 ? (
                              <Badge variant="outline" className="font-normal">
                                {row.memory_unit_ids!.length}
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground">—</span>
                            )}
                          </TableCell>
                          <TableCell className="hidden max-w-[160px] truncate text-xs text-muted-foreground md:table-cell">
                            {row.taste_tags.join(", ") || "—"}
                          </TableCell>
                        </TableRow>
                      ))}
                      {filteredSets.length === 0 && (
                        <TableRow>
                          <TableCell colSpan={6}>
                            <div className="flex flex-col items-center justify-center gap-3 py-14 text-center">
                              <div className="rounded-full bg-muted p-4">
                                {sets.length === 0 ? (
                                  <Palette className="h-8 w-8 text-muted-foreground" />
                                ) : (
                                  <Layers className="h-8 w-8 text-muted-foreground" />
                                )}
                              </div>
                              <div>
                                <p className="font-medium">
                                  {sets.length === 0
                                    ? "Start curating taste"
                                    : "No sets match this filter"}
                                </p>
                                <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                                  {sets.length === 0
                                    ? "Create a dataset, import JSONL examples, then transform or generate variants."
                                    : "Try a different filter or import more examples."}
                                </p>
                              </div>
                              {sets.length === 0 && (
                                <div className="flex flex-wrap justify-center gap-2">
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => setSidebarTab("create")}
                                  >
                                    Create dataset
                                  </Button>
                                  <Button
                                    size="sm"
                                    onClick={() => setSidebarTab("import")}
                                    disabled={!datasetId}
                                  >
                                    Import examples
                                  </Button>
                                </div>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </div>
              </Card>

              {selectedSet && (
                <TasteSetDetailPanel
                  tasteSet={selectedSet}
                  draftJson={draftJson}
                  saving={busy}
                  onDraftChange={setDraftJson}
                  onSave={handleSaveSet}
                  onRevert={handleRevertSet}
                  onClose={() => setSelectedSet(null)}
                />
              )}
            </main>
          </div>
        </div>

        <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete dataset?</AlertDialogTitle>
              <AlertDialogDescription>
                This permanently deletes &ldquo;{activeDataset?.name}&rdquo; and all{" "}
                {activeDataset?.set_count ?? sets.length} sets. This cannot be undone.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                onClick={handleDeleteDataset}
              >
                Delete
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </TasteStudioProvider>
  );
}
