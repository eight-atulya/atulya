"use client";

import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { useBank } from "@/lib/bank-context";
import {
  client,
  CodebaseFilesResult,
  CodebaseImpactResult,
  CodebaseSummary,
  CodebaseSymbolsResult,
  OperationResult,
  OperationStatus,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import {
  AlertCircle,
  CheckCircle2,
  FileCode2,
  FolderGit2,
  GitBranch,
  Loader2,
  RefreshCw,
  Search,
  Sparkles,
  Upload,
  X,
} from "lucide-react";

type ImportTab = "github" | "zip";
type WorkspaceTab = "files" | "symbols" | "impact";
type ImpactMode = "path" | "symbol" | "query";

type ParsedGithubSource = {
  owner: string;
  repo: string;
  ref?: string;
};

function parseGlobs(raw: string): string[] {
  return raw
    .split(/[\n,]/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function parseGithubRepoUrl(raw: string): ParsedGithubSource | null {
  const value = raw.trim();
  if (!value) return null;

  if (value.startsWith("git@github.com:")) {
    const path = value.split(":", 2)[1] || "";
    const parts = path.split("/").filter(Boolean);
    if (parts.length < 2) return null;
    return {
      owner: parts[0],
      repo: parts[1].replace(/\.git$/i, ""),
    };
  }

  try {
    const parsed = new URL(value);
    if (!["github.com", "www.github.com"].includes(parsed.hostname)) {
      return null;
    }
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (parts.length < 2) return null;
    const source: ParsedGithubSource = {
      owner: parts[0],
      repo: parts[1].replace(/\.git$/i, ""),
    };
    if (parts.length >= 4 && ["tree", "commit", "blob"].includes(parts[2])) {
      source.ref = parts[3];
    }
    return source;
  } catch {
    return null;
  }
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Not available";
  return new Date(value).toLocaleString();
}

function formatRelative(value: string | null | undefined): string {
  if (!value) return "Never";
  const now = Date.now();
  const target = new Date(value).getTime();
  const diffMs = Math.max(0, now - target);
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function statusClasses(status: string | null | undefined): string {
  switch (status) {
    case "approved":
    case "completed":
    case "indexed":
    case "retained":
    case "hydrated":
      return "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
    case "cancelled":
      return "bg-slate-500/10 text-slate-700 dark:text-slate-300";
    case "review_required":
    case "pending_approval":
    case "pending":
    case "processing":
    case "parsing":
    case "hydrated_from_previous_snapshot":
      return "bg-amber-500/10 text-amber-700 dark:text-amber-300";
    case "failed":
    case "parse_failed":
    case "excluded":
      return "bg-rose-500/10 text-rose-700 dark:text-rose-300";
    case "manifest_only":
    case "not_hydrated":
    case "not_ready":
      return "bg-muted text-muted-foreground";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function formatStatusLabel(status: string | null | undefined): string {
  if (!status) return "unknown";
  return status.replace(/_/g, " ");
}

function documentStateLabel(
  item: CodebaseFilesResult["items"][number],
  codebase: CodebaseSummary | null
): string {
  if (item.document_id) return item.document_id;
  if (item.status === "manifest_only") return "preview only";
  if (item.status === "excluded") return "not eligible";
  if (codebase?.approval_status === "pending_approval") return "pending approval";
  return "not hydrated";
}

function sourceLabel(codebase: CodebaseSummary): string {
  if (codebase.source_type === "github") {
    return codebase.source_config.owner && codebase.source_config.repo
      ? `${codebase.source_config.owner}/${codebase.source_config.repo}`
      : codebase.name;
  }
  return codebase.name;
}

export function CodebasesView() {
  const { currentBank } = useBank();

  const [importTab, setImportTab] = useState<ImportTab>("github");
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("files");
  const [codebases, setCodebases] = useState<CodebaseSummary[]>([]);
  const [loadingCodebases, setLoadingCodebases] = useState(false);
  const [selectedCodebaseId, setSelectedCodebaseId] = useState<string | null>(null);
  const [selectedCodebase, setSelectedCodebase] = useState<CodebaseSummary | null>(null);
  const [loadingSelectedCodebase, setLoadingSelectedCodebase] = useState(false);

  const [activeOperationId, setActiveOperationId] = useState<string | null>(null);
  const [operationStatus, setOperationStatus] = useState<OperationStatus | null>(null);
  const [operationResult, setOperationResult] = useState<OperationResult | null>(null);
  const [cancellingOperation, setCancellingOperation] = useState(false);

  const [githubOwner, setGithubOwner] = useState("");
  const [githubRepo, setGithubRepo] = useState("");
  const [githubRef, setGithubRef] = useState("main");
  const [githubRepoUrl, setGithubRepoUrl] = useState("");
  const [githubRootPath, setGithubRootPath] = useState("");
  const [githubInclude, setGithubInclude] = useState("");
  const [githubExclude, setGithubExclude] = useState("");
  const [githubRefreshExisting, setGithubRefreshExisting] = useState(true);
  const [submittingGithub, setSubmittingGithub] = useState(false);

  const [zipFile, setZipFile] = useState<File | null>(null);
  const [zipName, setZipName] = useState("");
  const [zipRootPath, setZipRootPath] = useState("");
  const [zipInclude, setZipInclude] = useState("");
  const [zipExclude, setZipExclude] = useState("");
  const [zipRefreshExisting, setZipRefreshExisting] = useState(true);
  const [submittingZip, setSubmittingZip] = useState(false);

  const [refreshRef, setRefreshRef] = useState("");
  const [refreshingCodebase, setRefreshingCodebase] = useState(false);
  const [approvingCodebase, setApprovingCodebase] = useState(false);

  const [filePathPrefix, setFilePathPrefix] = useState("");
  const [fileLanguage, setFileLanguage] = useState("all");
  const [filesChangedOnly, setFilesChangedOnly] = useState(false);
  const [filesResult, setFilesResult] = useState<CodebaseFilesResult | null>(null);
  const [loadingFiles, setLoadingFiles] = useState(false);

  const [symbolQuery, setSymbolQuery] = useState("");
  const deferredSymbolQuery = useDeferredValue(symbolQuery.trim());
  const [symbolKind, setSymbolKind] = useState("all");
  const [symbolPathPrefix, setSymbolPathPrefix] = useState("");
  const [symbolsResult, setSymbolsResult] = useState<CodebaseSymbolsResult | null>(null);
  const [loadingSymbols, setLoadingSymbols] = useState(false);

  const [impactMode, setImpactMode] = useState<ImpactMode>("path");
  const [impactInput, setImpactInput] = useState("");
  const [impactResult, setImpactResult] = useState<CodebaseImpactResult | null>(null);
  const [loadingImpact, setLoadingImpact] = useState(false);

  const selectedCodebaseSource = useMemo(() => {
    if (!selectedCodebase) return null;
    return sourceLabel(selectedCodebase);
  }, [selectedCodebase]);

  const canCancelActiveOperation =
    Boolean(activeOperationId) && operationStatus?.status === "pending";

  const loadCodebases = async (preserveSelection = true) => {
    if (!currentBank) return;

    setLoadingCodebases(true);
    try {
      const response = await client.listCodebases(currentBank);
      const items = response.items || [];
      setCodebases(items);
      setSelectedCodebaseId((currentSelected) => {
        if (!items.length) return null;
        if (
          preserveSelection &&
          currentSelected &&
          items.some((item) => item.id === currentSelected)
        ) {
          return currentSelected;
        }
        return items[0].id;
      });
    } catch {
      // Error toast handled by API client for JSON requests.
    } finally {
      setLoadingCodebases(false);
    }
  };

  const loadSelectedCodebase = async (codebaseId: string) => {
    if (!currentBank) return;

    setLoadingSelectedCodebase(true);
    try {
      const response = await client.getCodebase(currentBank, codebaseId);
      setSelectedCodebase(response);
      setRefreshRef(response.source_config.ref || "");
    } catch {
      setSelectedCodebase(null);
    } finally {
      setLoadingSelectedCodebase(false);
    }
  };

  const loadFiles = async (codebaseId: string) => {
    if (!currentBank) return;

    setLoadingFiles(true);
    try {
      const response = await client.listCodebaseFiles(currentBank, codebaseId, {
        path_prefix: filePathPrefix || undefined,
        language: fileLanguage === "all" ? undefined : fileLanguage,
        changed_only: filesChangedOnly,
      });
      setFilesResult(response);
    } catch {
      setFilesResult(null);
    } finally {
      setLoadingFiles(false);
    }
  };

  const runSymbolSearch = async (codebaseId: string, query: string) => {
    if (!currentBank || !query) {
      setSymbolsResult(null);
      return;
    }

    setLoadingSymbols(true);
    try {
      const response = await client.searchCodebaseSymbols(currentBank, codebaseId, {
        q: query,
        kind: symbolKind === "all" ? undefined : symbolKind,
        path_prefix: symbolPathPrefix || undefined,
        limit: 50,
      });
      setSymbolsResult(response);
    } catch {
      setSymbolsResult(null);
    } finally {
      setLoadingSymbols(false);
    }
  };

  const runImpactAnalysis = async () => {
    if (!currentBank || !selectedCodebaseId || !impactInput.trim()) return;

    setLoadingImpact(true);
    try {
      const payload =
        impactMode === "path"
          ? { path: impactInput.trim() }
          : impactMode === "symbol"
            ? { symbol: impactInput.trim() }
            : { query: impactInput.trim() };

      const response = await client.analyzeCodebaseImpact(currentBank, selectedCodebaseId, {
        ...payload,
        max_depth: 3,
        limit: 50,
      });
      setImpactResult(response);
    } catch {
      setImpactResult(null);
    } finally {
      setLoadingImpact(false);
    }
  };

  const handleGithubImport = async () => {
    const parsedRepoUrl = parseGithubRepoUrl(githubRepoUrl);
    const effectiveOwner = githubOwner.trim() || parsedRepoUrl?.owner || "";
    const effectiveRepo = githubRepo.trim() || parsedRepoUrl?.repo || "";
    const effectiveRef = githubRef.trim() || parsedRepoUrl?.ref || "";

    if (!currentBank || !effectiveOwner || !effectiveRepo || !effectiveRef) {
      toast.error("GitHub import needs a repo URL or owner/repo, plus a ref.");
      return;
    }

    setSubmittingGithub(true);
    try {
      const response = await client.importCodebaseGithub(currentBank, {
        owner: effectiveOwner,
        repo: effectiveRepo,
        ref: effectiveRef,
        repo_url: githubRepoUrl.trim() || undefined,
        root_path: githubRootPath.trim() || undefined,
        include_globs: parseGlobs(githubInclude),
        exclude_globs: parseGlobs(githubExclude),
        refresh_existing: githubRefreshExisting,
      });
      setSelectedCodebaseId(response.codebase_id);
      setActiveOperationId(response.operation_id);
      setOperationStatus({
        operation_id: response.operation_id,
        status: "pending",
        operation_type: "codebase_import",
        created_at: null,
        updated_at: null,
        completed_at: null,
        error_message: null,
        stage: "queued",
      });
      setOperationResult(null);
      toast.success(`Queued GitHub import for ${effectiveOwner}/${effectiveRepo}@${effectiveRef}.`);
      await loadCodebases(false);
    } finally {
      setSubmittingGithub(false);
    }
  };

  const handleZipImport = async () => {
    if (!currentBank || !zipFile) {
      toast.error("Choose a ZIP archive before importing.");
      return;
    }

    const inferredName = zipName.trim() || zipFile.name.replace(/\.zip$/i, "");
    if (!inferredName) {
      toast.error("ZIP imports need a codebase name.");
      return;
    }

    setSubmittingZip(true);
    try {
      const response = await client.importCodebaseZip(currentBank, {
        archive: zipFile,
        name: inferredName,
        root_path: zipRootPath.trim() || undefined,
        include_globs: parseGlobs(zipInclude),
        exclude_globs: parseGlobs(zipExclude),
        refresh_existing: zipRefreshExisting,
      });
      setSelectedCodebaseId(response.codebase_id);
      setActiveOperationId(response.operation_id);
      setOperationStatus({
        operation_id: response.operation_id,
        status: "pending",
        operation_type: "codebase_import",
        created_at: null,
        updated_at: null,
        completed_at: null,
        error_message: null,
        stage: "queued",
      });
      setOperationResult(null);
      toast.success(`Queued ZIP import for ${inferredName}.`);
      await loadCodebases(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "ZIP import failed.");
    } finally {
      setSubmittingZip(false);
    }
  };

  const handleRefresh = async () => {
    if (!currentBank || !selectedCodebase) return;

    if (selectedCodebase.source_type !== "github") {
      toast.error("Manual refresh is only supported for public GitHub codebases in v1.");
      return;
    }

    setRefreshingCodebase(true);
    try {
      const response = await client.refreshCodebase(currentBank, selectedCodebase.id, {
        ref: refreshRef.trim() || undefined,
      });

      if (response.noop) {
        toast.success("Repository is already up to date.");
        await loadCodebases();
        await loadSelectedCodebase(selectedCodebase.id);
        await loadFiles(selectedCodebase.id);
        return;
      }

      if (response.operation_id) {
        setActiveOperationId(response.operation_id);
        setOperationStatus({
          operation_id: response.operation_id,
          status: "pending",
          operation_type: "codebase_refresh",
          created_at: null,
          updated_at: null,
          completed_at: null,
          error_message: null,
          stage: "queued",
        });
        setOperationResult(null);
        toast.success("Queued refresh. I’ll keep the status card updated.");
      }
    } finally {
      setRefreshingCodebase(false);
    }
  };

  const handleApprove = async () => {
    if (!currentBank || !selectedCodebase?.current_snapshot_id) return;

    setApprovingCodebase(true);
    try {
      const response = await client.approveCodebase(currentBank, selectedCodebase.id, {
        snapshot_id: selectedCodebase.current_snapshot_id,
      });
      setActiveOperationId(response.operation_id);
      setOperationStatus({
        operation_id: response.operation_id,
        status: "pending",
        operation_type: "codebase_approve",
        created_at: null,
        updated_at: null,
        completed_at: null,
        error_message: null,
        stage: "queued",
      });
      setOperationResult(null);
      toast.success("Queued memory hydration for the current reviewed snapshot.");
    } finally {
      setApprovingCodebase(false);
    }
  };

  const handleCancelActiveOperation = async () => {
    if (!currentBank || !activeOperationId) return;

    setCancellingOperation(true);
    try {
      await client.cancelOperation(currentBank, activeOperationId);
      setActiveOperationId(null);
      setOperationResult(null);
      setOperationStatus((previous) =>
        previous
          ? {
              ...previous,
              status: "cancelled",
              completed_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
              stage: null,
            }
          : null
      );
      toast.success("Pending codebase job canceled.");
      await loadCodebases();
      if (selectedCodebaseId) {
        await loadSelectedCodebase(selectedCodebaseId);
        await loadFiles(selectedCodebaseId);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to cancel the pending job.");
    } finally {
      setCancellingOperation(false);
    }
  };

  useEffect(() => {
    if (!currentBank) return;
    void loadCodebases(false);
  }, [currentBank]);

  useEffect(() => {
    if (!currentBank || !selectedCodebaseId) {
      setSelectedCodebase(null);
      setFilesResult(null);
      setSymbolsResult(null);
      setImpactResult(null);
      return;
    }

    void loadSelectedCodebase(selectedCodebaseId);
    void loadFiles(selectedCodebaseId);
    setImpactResult(null);
  }, [currentBank, selectedCodebaseId]);

  useEffect(() => {
    if (!selectedCodebaseId || !deferredSymbolQuery) {
      setSymbolsResult(null);
      return;
    }
    void runSymbolSearch(selectedCodebaseId, deferredSymbolQuery);
  }, [selectedCodebaseId, deferredSymbolQuery, symbolKind, symbolPathPrefix]);

  useEffect(() => {
    if (!currentBank || !activeOperationId) return;

    let cancelled = false;
    const interval = window.setInterval(async () => {
      try {
        const status = await client.getOperationStatus(currentBank, activeOperationId);
        if (cancelled) return;
        setOperationStatus(status);

        if (status.status === "not_found") {
          setOperationStatus((previous) =>
            previous?.status === "pending"
              ? {
                  ...previous,
                  status: "cancelled",
                  completed_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                  stage: null,
                }
              : status
          );
          window.clearInterval(interval);
          setActiveOperationId(null);
          await loadCodebases();
          if (selectedCodebaseId) {
            await loadSelectedCodebase(selectedCodebaseId);
            await loadFiles(selectedCodebaseId);
          }
          return;
        }

        if (status.status === "completed" || status.status === "failed") {
          const result = await client.getOperationResult(currentBank, activeOperationId);
          if (cancelled) return;
          setOperationResult(result);
          window.clearInterval(interval);
          setActiveOperationId(null);
          await loadCodebases();
          if (selectedCodebaseId) {
            await loadSelectedCodebase(selectedCodebaseId);
            await loadFiles(selectedCodebaseId);
          }
          if (status.status === "completed") {
            toast.success(
              status.operation_type === "codebase_approve"
                ? "Memory hydration completed."
                : "Codebase operation completed."
            );
          } else {
            toast.error(status.error_message || "Codebase operation failed.");
          }
        }
      } catch {
        window.clearInterval(interval);
      }
    }, 3000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [activeOperationId, currentBank, selectedCodebaseId]);

  const languageOptions = useMemo(() => {
    const languages = new Set(
      (filesResult?.items || [])
        .map((item) => item.language)
        .filter((value): value is string => Boolean(value))
    );
    return Array.from(languages).sort();
  }, [filesResult]);

  const totalIndexedFiles = selectedCodebase?.stats.indexed_files || 0;
  const totalFiles = selectedCodebase?.stats.total_files || 0;
  const canApproveMemory =
    selectedCodebase?.approval_status === "pending_approval" &&
    Boolean(selectedCodebase.current_snapshot_id);
  const operationMetrics = useMemo(() => {
    if (!operationResult?.result || typeof operationResult.result !== "object") return [];
    const result = operationResult.result as Record<string, unknown>;

    if ("hydrated_files" in result || "reused_files" in result || "deleted_files" in result) {
      return [
        { label: "Hydrated", value: Number(result.hydrated_files ?? 0) },
        { label: "Reused", value: Number(result.reused_files ?? 0) },
        { label: "Deleted", value: Number(result.deleted_files ?? 0) },
      ];
    }

    if ("added_files" in result || "changed_files" in result || "deleted_files" in result) {
      return [
        { label: "Added", value: Number(result.added_files ?? 0) },
        { label: "Changed", value: Number(result.changed_files ?? 0) },
        { label: "Deleted", value: Number(result.deleted_files ?? 0) },
      ];
    }

    return [];
  }, [operationResult]);
  const latestOperationLabel = useMemo(() => {
    switch (operationStatus?.operation_type) {
      case "codebase_approve":
        return "Latest Approval";
      case "codebase_refresh":
        return "Latest Refresh";
      case "codebase_import":
        return "Latest Import";
      default:
        return "Latest Codebase Operation";
    }
  }, [operationStatus?.operation_type]);

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div>
          <h2 className="text-3xl font-bold text-foreground">Codebases</h2>
          <p className="max-w-4xl text-muted-foreground">
            Import repositories from GitHub or ZIP, inspect ASD-parsed snapshots immediately, and
            approve memory hydration only when the repo state looks right.
          </p>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
        <Card className="border-border/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-xl">
              <FolderGit2 className="h-5 w-5 text-primary" />
              Import Codebase
            </CardTitle>
            <CardDescription>
              Use public GitHub for live repositories or ZIP uploads for private and offline
              snapshots.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs value={importTab} onValueChange={(value) => setImportTab(value as ImportTab)}>
              <TabsList className="mb-4 grid w-full grid-cols-2">
                <TabsTrigger value="github">GitHub</TabsTrigger>
                <TabsTrigger value="zip">ZIP</TabsTrigger>
              </TabsList>

              <TabsContent value="github" className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="github-repo-url">Repo URL</Label>
                  <Input
                    id="github-repo-url"
                    value={githubRepoUrl}
                    onChange={(event) => {
                      const nextValue = event.target.value;
                      setGithubRepoUrl(nextValue);
                      const parsed = parseGithubRepoUrl(nextValue);
                      if (parsed) {
                        setGithubOwner((current) => current || parsed.owner);
                        setGithubRepo((current) => current || parsed.repo);
                        if (parsed.ref) {
                          setGithubRef((current) => current || parsed.ref);
                        }
                      }
                    }}
                    placeholder="https://github.com/eight-atulya/atulya.git"
                  />
                  <p className="text-sm text-muted-foreground">
                    Paste a public GitHub URL and we&apos;ll normalize it into the same
                    archive-based import flow. No persistent clone required.
                  </p>
                </div>

                <div className="grid gap-4 md:grid-cols-3">
                  <div className="space-y-2">
                    <Label htmlFor="github-owner">Owner</Label>
                    <Input
                      id="github-owner"
                      value={githubOwner}
                      onChange={(event) => setGithubOwner(event.target.value)}
                      placeholder="openai"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="github-repo">Repo</Label>
                    <Input
                      id="github-repo"
                      value={githubRepo}
                      onChange={(event) => setGithubRepo(event.target.value)}
                      placeholder="openai-cookbook"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="github-ref">Ref</Label>
                    <Input
                      id="github-ref"
                      value={githubRef}
                      onChange={(event) => setGithubRef(event.target.value)}
                      placeholder="main"
                    />
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-3">
                  <div className="space-y-2 md:col-span-1">
                    <Label htmlFor="github-root-path">Root Path</Label>
                    <Input
                      id="github-root-path"
                      value={githubRootPath}
                      onChange={(event) => setGithubRootPath(event.target.value)}
                      placeholder="packages/sdk"
                    />
                  </div>
                  <div className="space-y-2 md:col-span-2">
                    <Label htmlFor="github-refresh-existing">Import Mode</Label>
                    <Select
                      value={githubRefreshExisting ? "refresh" : "new"}
                      onValueChange={(value) => setGithubRefreshExisting(value === "refresh")}
                    >
                      <SelectTrigger id="github-refresh-existing">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="refresh">
                          Refresh existing codebase when names match
                        </SelectItem>
                        <SelectItem value="new">Require a new codebase name</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="github-include">Include Globs</Label>
                    <Textarea
                      id="github-include"
                      value={githubInclude}
                      onChange={(event) => setGithubInclude(event.target.value)}
                      placeholder="src/**&#10;packages/app/**"
                      className="min-h-[96px]"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="github-exclude">Exclude Globs</Label>
                    <Textarea
                      id="github-exclude"
                      value={githubExclude}
                      onChange={(event) => setGithubExclude(event.target.value)}
                      placeholder="coverage/**&#10;**/*.snap"
                      className="min-h-[96px]"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between gap-4 rounded-lg border border-border/70 bg-muted/20 p-4">
                  <div className="text-sm text-muted-foreground">
                    Best for active repos where developers want explicit refresh and commit-aware
                    snapshots with manual promotion into memory.
                  </div>
                  <Button onClick={handleGithubImport} disabled={submittingGithub}>
                    {submittingGithub ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <GitBranch className="mr-2 h-4 w-4" />
                    )}
                    Import From GitHub
                  </Button>
                </div>
              </TabsContent>

              <TabsContent value="zip" className="space-y-4">
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="zip-file">ZIP Archive</Label>
                    <Input
                      id="zip-file"
                      type="file"
                      accept=".zip,application/zip"
                      onChange={(event) => {
                        const file = event.target.files?.[0] || null;
                        setZipFile(file);
                        if (file && !zipName.trim()) {
                          setZipName(file.name.replace(/\.zip$/i, ""));
                        }
                      }}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="zip-name">Codebase Name</Label>
                    <Input
                      id="zip-name"
                      value={zipName}
                      onChange={(event) => setZipName(event.target.value)}
                      placeholder="private-monorepo"
                    />
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-3">
                  <div className="space-y-2 md:col-span-1">
                    <Label htmlFor="zip-root-path">Root Path</Label>
                    <Input
                      id="zip-root-path"
                      value={zipRootPath}
                      onChange={(event) => setZipRootPath(event.target.value)}
                      placeholder="services/api"
                    />
                  </div>
                  <div className="space-y-2 md:col-span-2">
                    <Label htmlFor="zip-refresh-existing">Import Mode</Label>
                    <Select
                      value={zipRefreshExisting ? "refresh" : "new"}
                      onValueChange={(value) => setZipRefreshExisting(value === "refresh")}
                    >
                      <SelectTrigger id="zip-refresh-existing">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="refresh">
                          Replace existing ZIP codebase by name
                        </SelectItem>
                        <SelectItem value="new">Require a new codebase name</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="zip-include">Include Globs</Label>
                    <Textarea
                      id="zip-include"
                      value={zipInclude}
                      onChange={(event) => setZipInclude(event.target.value)}
                      placeholder="src/**&#10;apps/web/**"
                      className="min-h-[96px]"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="zip-exclude">Exclude Globs</Label>
                    <Textarea
                      id="zip-exclude"
                      value={zipExclude}
                      onChange={(event) => setZipExclude(event.target.value)}
                      placeholder="dist/**&#10;node_modules/**"
                      className="min-h-[96px]"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-between gap-4 rounded-lg border border-border/70 bg-muted/20 p-4">
                  <div className="text-sm text-muted-foreground">
                    Best for private repos, offline snapshots, or curated archives you want to
                    review mechanically before hydrating memory.
                  </div>
                  <Button onClick={handleZipImport} disabled={submittingZip || !zipFile}>
                    {submittingZip ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Upload className="mr-2 h-4 w-4" />
                    )}
                    Import ZIP
                  </Button>
                </div>
              </TabsContent>
            </Tabs>
          </CardContent>
        </Card>

        <Card className="border-border/70">
          <CardHeader>
            <CardTitle className="text-xl">Selected Codebase</CardTitle>
            <CardDescription>
              Review the active ASD snapshot, compare it against approved memory, and promote it
              only when you are ready.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {loadingSelectedCodebase ? (
              <div className="flex items-center gap-3 rounded-lg border border-border/70 p-4 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading codebase details...
              </div>
            ) : selectedCodebase ? (
              <>
                <div className="rounded-xl border border-border/70 bg-muted/15 p-4">
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div>
                      <div className="text-lg font-semibold text-foreground">
                        {selectedCodebase.name}
                      </div>
                      <div className="text-sm text-muted-foreground">{selectedCodebaseSource}</div>
                    </div>
                    <div className="flex flex-wrap justify-end gap-2">
                      <span
                        className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusClasses(selectedCodebase.snapshot_status)}`}
                      >
                        Parse: {formatStatusLabel(selectedCodebase.snapshot_status)}
                      </span>
                      <span
                        className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusClasses(selectedCodebase.approval_status)}`}
                      >
                        Memory: {formatStatusLabel(selectedCodebase.approval_status)}
                      </span>
                    </div>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    <div className="rounded-lg border border-border/60 bg-background/70 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Current Snapshot
                      </div>
                      <div className="mt-1 text-sm font-medium text-foreground">
                        {selectedCodebase.current_snapshot_id || "Not imported yet"}
                      </div>
                    </div>
                    <div className="rounded-lg border border-border/60 bg-background/70 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Commit / Ref
                      </div>
                      <div className="mt-1 text-sm font-medium text-foreground">
                        {selectedCodebase.source_commit_sha ||
                          selectedCodebase.source_ref ||
                          "Not available"}
                      </div>
                    </div>
                    <div className="rounded-lg border border-border/60 bg-background/70 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Approved Snapshot
                      </div>
                      <div className="mt-1 text-sm font-medium text-foreground">
                        {selectedCodebase.approved_snapshot_id || "Waiting for approval"}
                      </div>
                    </div>
                    <div className="rounded-lg border border-border/60 bg-background/70 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Indexed Files
                      </div>
                      <div className="mt-1 text-sm font-medium text-foreground">
                        {totalIndexedFiles} of {totalFiles}
                      </div>
                    </div>
                    <div className="rounded-lg border border-border/60 bg-background/70 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Memory State
                      </div>
                      <div className="mt-1 text-sm font-medium text-foreground">
                        {formatStatusLabel(selectedCodebase.memory_status)}
                      </div>
                    </div>
                    <div className="rounded-lg border border-border/60 bg-background/70 p-3">
                      <div className="text-xs uppercase tracking-wide text-muted-foreground">
                        Updated
                      </div>
                      <div className="mt-1 text-sm font-medium text-foreground">
                        {formatRelative(
                          selectedCodebase.snapshot_updated_at || selectedCodebase.updated_at
                        )}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="rounded-lg border border-primary/20 bg-primary/5 p-4 text-sm text-muted-foreground">
                  ASD parsing publishes repo map, symbol search, and impact analysis immediately.
                  Source-file memory hydration stays gated until you explicitly approve this
                  snapshot.
                </div>

                <div className="grid gap-3 lg:grid-cols-[1fr_auto_auto]">
                  <Input
                    value={refreshRef}
                    onChange={(event) => setRefreshRef(event.target.value)}
                    placeholder="Optional ref override for refresh"
                    disabled={selectedCodebase.source_type !== "github"}
                  />
                  <Button
                    variant="outline"
                    onClick={handleRefresh}
                    disabled={refreshingCodebase || selectedCodebase.source_type !== "github"}
                  >
                    {refreshingCodebase ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <RefreshCw className="mr-2 h-4 w-4" />
                    )}
                    Refresh
                  </Button>
                  <Button onClick={handleApprove} disabled={!canApproveMemory || approvingCodebase}>
                    {approvingCodebase ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <CheckCircle2 className="mr-2 h-4 w-4" />
                    )}
                    Approve Memory Import
                  </Button>
                </div>
                {selectedCodebase.source_type !== "github" && (
                  <p className="text-xs text-muted-foreground">
                    ZIP-backed codebases can be updated by re-importing the archive with the same
                    name.
                  </p>
                )}
                {!canApproveMemory && selectedCodebase.approval_status === "approved" && (
                  <p className="text-xs text-muted-foreground">
                    The current snapshot is already the approved memory source for this codebase.
                  </p>
                )}
                {!canApproveMemory && selectedCodebase.approval_status === "parsing" && (
                  <p className="text-xs text-muted-foreground">
                    Approval unlocks after ASD parsing finishes and the snapshot enters review.
                  </p>
                )}
              </>
            ) : (
              <div className="rounded-xl border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                Import your first codebase to unlock repo map, symbol search, and impact analysis.
              </div>
            )}

            {(operationStatus || operationResult) && (
              <div className="rounded-xl border border-border/70 bg-background/70 p-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    {operationStatus?.status === "failed" ? (
                      <AlertCircle className="h-4 w-4 text-rose-500" />
                    ) : operationStatus?.status === "cancelled" ? (
                      <X className="h-4 w-4 text-slate-500" />
                    ) : operationStatus?.status === "completed" ? (
                      <CheckCircle2 className="h-4 w-4 text-emerald-500" />
                    ) : (
                      <Loader2 className="h-4 w-4 animate-spin text-amber-500" />
                    )}
                    <span className="text-sm font-semibold text-foreground">
                      {latestOperationLabel}
                    </span>
                  </div>
                  {operationStatus && (
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusClasses(operationStatus.status)}`}
                      >
                        {formatStatusLabel(operationStatus.status)}
                      </span>
                      {canCancelActiveOperation && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleCancelActiveOperation}
                          disabled={cancellingOperation}
                        >
                          {cancellingOperation ? (
                            <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <X className="mr-2 h-3.5 w-3.5" />
                          )}
                          Cancel Job
                        </Button>
                      )}
                    </div>
                  )}
                </div>

                <div className="space-y-2 text-sm">
                  {operationStatus?.stage && (
                    <div className="text-muted-foreground">
                      Stage:{" "}
                      <span className="font-medium text-foreground">
                        {formatStatusLabel(operationStatus.stage)}
                      </span>
                    </div>
                  )}
                  {operationMetrics.length > 0 && (
                    <div className="grid gap-2 sm:grid-cols-3">
                      {operationMetrics.map((metric) => (
                        <div key={metric.label} className="rounded-lg border border-border/60 p-3">
                          <div className="text-xs uppercase tracking-wide text-muted-foreground">
                            {metric.label}
                          </div>
                          <div className="mt-1 font-semibold text-foreground">{metric.value}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  {operationStatus?.error_message && (
                    <div className="rounded-lg border border-rose-500/20 bg-rose-500/5 p-3 text-rose-700 dark:text-rose-300">
                      {operationStatus.error_message}
                    </div>
                  )}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card className="border-border/70">
        <CardHeader>
          <CardTitle className="text-xl">Imported Codebases</CardTitle>
          <CardDescription>
            Keep active repositories visible and see at a glance which snapshots are still waiting
            for memory approval.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loadingCodebases ? (
            <div className="flex items-center gap-3 rounded-lg border border-border/70 p-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading codebases...
            </div>
          ) : codebases.length ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Files</TableHead>
                    <TableHead>Symbols</TableHead>
                    <TableHead>Updated</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {codebases.map((item) => (
                    <TableRow
                      key={item.id}
                      className={`cursor-pointer hover:bg-muted/40 ${item.id === selectedCodebaseId ? "bg-primary/5" : ""}`}
                      onClick={() => setSelectedCodebaseId(item.id)}
                    >
                      <TableCell className="font-medium text-card-foreground">
                        {item.name}
                      </TableCell>
                      <TableCell className="text-card-foreground">{sourceLabel(item)}</TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1">
                          <span
                            className={`w-fit rounded-full px-2.5 py-1 text-xs font-semibold ${statusClasses(item.snapshot_status)}`}
                          >
                            {formatStatusLabel(item.snapshot_status)}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            Memory: {formatStatusLabel(item.approval_status)}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="text-card-foreground">
                        {item.stats.total_files}
                      </TableCell>
                      <TableCell className="text-card-foreground">
                        {item.stats.symbol_count}
                      </TableCell>
                      <TableCell className="text-card-foreground">
                        <div>{formatRelative(item.snapshot_updated_at || item.updated_at)}</div>
                        <div className="text-xs text-muted-foreground">
                          {formatDateTime(item.snapshot_updated_at || item.updated_at)}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-border/70 p-8 text-center">
              <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
                <FolderGit2 className="h-6 w-6" />
              </div>
              <div className="text-lg font-semibold text-foreground">No codebases imported yet</div>
              <div className="mt-2 text-sm text-muted-foreground">
                Start with a public GitHub repo or a ZIP archive to make this bank a developer-ready
                intelligence workspace.
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-border/70">
        <CardHeader>
          <CardTitle className="text-xl">Code Intelligence Workbench</CardTitle>
          <CardDescription>
            Use the selected codebase to map files, search symbols, and inspect deterministic impact
            before or after memory approval.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs
            value={workspaceTab}
            onValueChange={(value) => setWorkspaceTab(value as WorkspaceTab)}
          >
            <TabsList className="mb-4 grid w-full grid-cols-3">
              <TabsTrigger value="files">Repo Map</TabsTrigger>
              <TabsTrigger value="symbols">Symbol Search</TabsTrigger>
              <TabsTrigger value="impact">Impact</TabsTrigger>
            </TabsList>

            <TabsContent value="files" className="space-y-4">
              <div className="grid gap-4 lg:grid-cols-[1.3fr_0.9fr_0.7fr_auto]">
                <div className="space-y-2">
                  <Label htmlFor="file-path-prefix">Path Prefix</Label>
                  <Input
                    id="file-path-prefix"
                    value={filePathPrefix}
                    onChange={(event) => setFilePathPrefix(event.target.value)}
                    placeholder="src/components"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="file-language">Language</Label>
                  <Select value={fileLanguage} onValueChange={setFileLanguage}>
                    <SelectTrigger id="file-language">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All languages</SelectItem>
                      {languageOptions.map((option) => (
                        <SelectItem key={option} value={option}>
                          {option}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="file-scope">Scope</Label>
                  <Select
                    value={filesChangedOnly ? "changed" : "all"}
                    onValueChange={(value) => setFilesChangedOnly(value === "changed")}
                  >
                    <SelectTrigger id="file-scope">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All files</SelectItem>
                      <SelectItem value="changed">Changed only</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-end">
                  <Button
                    variant="outline"
                    onClick={() => selectedCodebaseId && void loadFiles(selectedCodebaseId)}
                    disabled={!selectedCodebaseId || loadingFiles}
                    className="w-full"
                  >
                    {loadingFiles ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <FileCode2 className="mr-2 h-4 w-4" />
                    )}
                    Load Files
                  </Button>
                </div>
              </div>

              {filesResult?.items?.length ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Path</TableHead>
                        <TableHead>Language</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead>Change</TableHead>
                        <TableHead>Size</TableHead>
                        <TableHead>Document</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {filesResult.items.map((item) => (
                        <TableRow key={`${item.path}-${item.content_hash}`}>
                          <TableCell className="font-mono text-xs text-card-foreground">
                            {item.path}
                          </TableCell>
                          <TableCell className="text-card-foreground">
                            {item.language || "unknown"}
                          </TableCell>
                          <TableCell>
                            <span
                              className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusClasses(item.status)}`}
                            >
                              {item.status}
                            </span>
                          </TableCell>
                          <TableCell className="text-card-foreground">{item.change_kind}</TableCell>
                          <TableCell className="text-card-foreground">
                            {item.size_bytes.toLocaleString()} B
                          </TableCell>
                          <TableCell className="font-mono text-xs text-muted-foreground">
                            {documentStateLabel(item, selectedCodebase)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                  {selectedCodebaseId
                    ? "Load the repo map to inspect paths, languages, and which files are only previewed versus already hydrated into memory."
                    : "Select a codebase first to inspect its file map."}
                </div>
              )}
            </TabsContent>

            <TabsContent value="symbols" className="space-y-4">
              <div className="grid gap-4 lg:grid-cols-[1.4fr_0.8fr_1fr]">
                <div className="space-y-2">
                  <Label htmlFor="symbol-query">Symbol Query</Label>
                  <Input
                    id="symbol-query"
                    value={symbolQuery}
                    onChange={(event) => setSymbolQuery(event.target.value)}
                    placeholder="helper, UserService, renderDashboard"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="symbol-kind">Kind</Label>
                  <Select value={symbolKind} onValueChange={setSymbolKind}>
                    <SelectTrigger id="symbol-kind">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All kinds</SelectItem>
                      <SelectItem value="class">Class</SelectItem>
                      <SelectItem value="function">Function</SelectItem>
                      <SelectItem value="variable">Variable</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="symbol-path-prefix">Path Prefix</Label>
                  <Input
                    id="symbol-path-prefix"
                    value={symbolPathPrefix}
                    onChange={(event) => setSymbolPathPrefix(event.target.value)}
                    placeholder="src/"
                  />
                </div>
              </div>

              <div className="rounded-lg border border-border/70 bg-muted/20 p-3 text-sm text-muted-foreground">
                Symbol search runs automatically as you type and is optimized for exact, prefix, and
                fuzzy matching.
              </div>

              {loadingSymbols ? (
                <div className="flex items-center gap-3 rounded-lg border border-border/70 p-4 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Searching symbols...
                </div>
              ) : symbolsResult?.items?.length ? (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Name</TableHead>
                        <TableHead>Kind</TableHead>
                        <TableHead>Path</TableHead>
                        <TableHead>Container</TableHead>
                        <TableHead>Lines</TableHead>
                        <TableHead>Match</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {symbolsResult.items.map((item) => (
                        <TableRow key={`${item.fq_name}-${item.path}-${item.start_line}`}>
                          <TableCell className="font-medium text-card-foreground">
                            {item.name}
                          </TableCell>
                          <TableCell className="text-card-foreground">{item.kind}</TableCell>
                          <TableCell className="font-mono text-xs text-card-foreground">
                            {item.path}
                          </TableCell>
                          <TableCell className="text-card-foreground">
                            {item.container || "-"}
                          </TableCell>
                          <TableCell className="text-card-foreground">
                            {item.start_line}-{item.end_line}
                          </TableCell>
                          <TableCell>
                            <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-semibold text-primary">
                              {item.match_mode || "exact"}
                            </span>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                  {selectedCodebaseId
                    ? "Start typing a symbol name to search the current snapshot."
                    : "Select a codebase first to search symbols."}
                </div>
              )}
            </TabsContent>

            <TabsContent value="impact" className="space-y-4">
              <div className="grid gap-4 lg:grid-cols-[0.7fr_1.7fr_auto]">
                <div className="space-y-2">
                  <Label htmlFor="impact-mode">Seed Type</Label>
                  <Select
                    value={impactMode}
                    onValueChange={(value) => setImpactMode(value as ImpactMode)}
                  >
                    <SelectTrigger id="impact-mode">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="path">Path</SelectItem>
                      <SelectItem value="symbol">Symbol</SelectItem>
                      <SelectItem value="query">Query</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="impact-input">
                    {impactMode === "path"
                      ? "Changed File Path"
                      : impactMode === "symbol"
                        ? "Symbol"
                        : "Developer Query"}
                  </Label>
                  <Input
                    id="impact-input"
                    value={impactInput}
                    onChange={(event) => setImpactInput(event.target.value)}
                    placeholder={
                      impactMode === "path"
                        ? "src/services/payment.ts"
                        : impactMode === "symbol"
                          ? "processPayment"
                          : "what is affected by auth middleware"
                    }
                  />
                </div>
                <div className="flex items-end">
                  <Button
                    onClick={runImpactAnalysis}
                    disabled={!selectedCodebaseId || loadingImpact || !impactInput.trim()}
                    className="w-full"
                  >
                    {loadingImpact ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Sparkles className="mr-2 h-4 w-4" />
                    )}
                    Analyze
                  </Button>
                </div>
              </div>

              {impactResult ? (
                <div className="space-y-4">
                  <div className="rounded-xl border border-primary/20 bg-primary/5 p-4">
                    <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-foreground">
                      <Search className="h-4 w-4 text-primary" />
                      Deterministic impact summary
                    </div>
                    <p className="text-sm text-muted-foreground">{impactResult.explanation}</p>
                  </div>

                  {impactResult.matched_symbols.length > 0 && (
                    <div className="rounded-xl border border-border/70 p-4">
                      <div className="mb-3 text-sm font-semibold text-foreground">
                        Matched Symbols
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {impactResult.matched_symbols.map((item) => (
                          <span
                            key={`${item.fq_name}-${item.path}-${item.start_line}`}
                            className="rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary"
                          >
                            {item.name} · {item.path}:{item.start_line}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
                    <div className="rounded-xl border border-border/70">
                      <div className="border-b border-border/70 px-4 py-3 text-sm font-semibold text-foreground">
                        Impacted Files
                      </div>
                      <div className="overflow-x-auto">
                        <Table>
                          <TableHeader>
                            <TableRow>
                              <TableHead>Path</TableHead>
                              <TableHead>Depth</TableHead>
                              <TableHead>Status</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {impactResult.impacted_files.map((item) => (
                              <TableRow key={`${item.path}-${item.depth}`}>
                                <TableCell className="font-mono text-xs text-card-foreground">
                                  {item.path}
                                </TableCell>
                                <TableCell className="text-card-foreground">{item.depth}</TableCell>
                                <TableCell>
                                  <span
                                    className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusClasses(item.status)}`}
                                  >
                                    {item.status}
                                  </span>
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </div>
                    </div>

                    <div className="rounded-xl border border-border/70">
                      <div className="border-b border-border/70 px-4 py-3 text-sm font-semibold text-foreground">
                        Graph Edges
                      </div>
                      <div className="max-h-[420px] space-y-2 overflow-y-auto p-4">
                        {impactResult.edges.length ? (
                          impactResult.edges.map((edge, index) => (
                            <div
                              key={`${edge.from_path}-${edge.to_path}-${index}`}
                              className="rounded-lg border border-border/60 bg-background/70 p-3"
                            >
                              <div className="font-mono text-xs text-foreground">
                                {edge.from_path}
                              </div>
                              <div className="my-1 text-xs uppercase tracking-wide text-muted-foreground">
                                {edge.edge_type}
                              </div>
                              <div className="font-mono text-xs text-foreground">
                                {edge.to_path || edge.target_ref || "external target"}
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="text-sm text-muted-foreground">
                            No graph edges matched this seed.
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-border/70 p-6 text-sm text-muted-foreground">
                  Use impact mode the way developers actually think: start from a changed path, a
                  symbol, or a loose query and see what fans out.
                </div>
              )}
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  );
}
